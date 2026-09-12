use axum::{
    body::Body,
    extract::{ws::WebSocketUpgrade, Path, Query, State},
    http::{header, StatusCode},
    response::{IntoResponse, Json, Response},
};
use serde::{Deserialize, Serialize};
use serde_json::{json, Value};
use uuid::Uuid;

use crate::auditor::{self, EventEmitter};
use crate::config::AuditOptions;
use crate::contracts::{Analysis, AnalysisStatus, Error as ContractError, Summary, Tool};
use crate::storage::request_watermark;
use crate::AppState;

pub use crate::storage::AuditRecord;

// ---------------------------------------------------------------------------
// Error envelope (xwa-sdk `error.json`)
// ---------------------------------------------------------------------------

#[derive(Debug)]
pub struct ApiError {
    pub status: StatusCode,
    pub code: &'static str,
    pub message: String,
    pub retryable: bool,
}

impl ApiError {
    pub fn new(status: StatusCode, code: &'static str, message: impl Into<String>) -> Self {
        Self {
            status,
            code,
            message: message.into(),
            retryable: false,
        }
    }
}

impl IntoResponse for ApiError {
    fn into_response(self) -> Response {
        let error = ContractError {
            code: self.code.to_string(),
            message: self.message,
            detail: None,
            retryable: self.retryable,
        };
        (self.status, Json(json!({ "error": error }))).into_response()
    }
}

// ---------------------------------------------------------------------------
// /api/audits (legacy, kept stable)
// ---------------------------------------------------------------------------

#[derive(Debug, Deserialize)]
pub struct ImportPayload {
    pub records: Vec<AuditRecord>,
}

pub async fn list_audits(State(state): State<AppState>) -> Json<Vec<AuditRecord>> {
    Json(state.store.list().await)
}

pub async fn get_audit(
    State(state): State<AppState>,
    Path(id): Path<Uuid>,
) -> Result<Json<AuditRecord>, StatusCode> {
    state
        .store
        .get(&id)
        .await
        .map(Json)
        .ok_or(StatusCode::NOT_FOUND)
}

pub async fn delete_audit(
    State(state): State<AppState>,
    Path(id): Path<Uuid>,
) -> Result<StatusCode, ApiError> {
    match state.store.delete(&id).await {
        Ok(true) => Ok(StatusCode::NO_CONTENT),
        Ok(false) => Err(ApiError::new(
            StatusCode::NOT_FOUND,
            "NOT_FOUND",
            format!("audit {id} not found"),
        )),
        Err(e) => Err(ApiError::new(
            StatusCode::INTERNAL_SERVER_ERROR,
            "INTERNAL",
            e.to_string(),
        )),
    }
}

#[derive(Debug, Serialize)]
pub struct ExportResponse {
    pub records: Vec<AuditRecord>,
    pub exported_at: String,
}

pub async fn export_audits(State(state): State<AppState>) -> Json<ExportResponse> {
    Json(ExportResponse {
        records: state.store.list().await,
        exported_at: chrono::Utc::now().to_rfc3339(),
    })
}

pub async fn clear_all_audits(State(state): State<AppState>) -> impl IntoResponse {
    match state.store.clear_all().await {
        Ok(()) => {
            tracing::info!("All audit records cleared");
            (StatusCode::OK, Json(json!({"status": "cleared"}))).into_response()
        }
        Err(e) => ApiError::new(StatusCode::INTERNAL_SERVER_ERROR, "INTERNAL", e.to_string())
            .into_response(),
    }
}

pub async fn import_audits(
    State(state): State<AppState>,
    Json(payload): Json<ImportPayload>,
) -> Result<Json<Value>, ApiError> {
    let count = payload.records.len();
    for record in payload.records {
        state.store.insert(record).await.map_err(|e| {
            ApiError::new(StatusCode::INTERNAL_SERVER_ERROR, "INTERNAL", e.to_string())
        })?;
    }
    Ok(Json(json!({
        "status": "imported",
        "count": count,
        "message": format!("{count} audit records imported")
    })))
}

// ---------------------------------------------------------------------------
// /api/analyses (xwa-sdk Analysis contract)
// ---------------------------------------------------------------------------

#[derive(Debug, Clone, Serialize)]
pub struct AnalysisView {
    #[serde(flatten)]
    pub analysis: Analysis,
    pub findings: Vec<crate::contracts::Finding>,
}

impl AnalysisView {
    pub fn from_record(record: &AuditRecord) -> Self {
        let findings: Vec<crate::contracts::Finding> = record
            .findings
            .iter()
            .map(crate::contracts::finding_from_tengu)
            .collect();
        let status = match record.status.as_str() {
            "PENDING" => AnalysisStatus::Pending,
            "RUNNING" => AnalysisStatus::Running,
            "ERROR" => AnalysisStatus::Error,
            "CANCELLED" => AnalysisStatus::Cancelled,
            _ => AnalysisStatus::Completed,
        };
        let analysis = Analysis {
            id: record.id.to_string(),
            tool: Tool::Tengu,
            target: record.url.clone(),
            status,
            created_at: record.created_at.clone(),
            tool_version: Some(env!("CARGO_PKG_VERSION").to_string()),
            analysis_type: Some("audit".to_string()),
            started_at: Some(record.created_at.clone()),
            finished_at: None,
            error: None,
            summary: Some(Summary::from_findings(&findings)),
        };
        Self { analysis, findings }
    }
}

pub async fn list_analyses(State(state): State<AppState>) -> Json<Vec<AnalysisView>> {
    Json(
        state
            .store
            .list()
            .await
            .iter()
            .map(AnalysisView::from_record)
            .collect(),
    )
}

pub async fn get_analysis(
    State(state): State<AppState>,
    Path(id): Path<Uuid>,
) -> Result<Json<AnalysisView>, StatusCode> {
    state
        .store
        .get(&id)
        .await
        .map(|record| Json(AnalysisView::from_record(&record)))
        .ok_or(StatusCode::NOT_FOUND)
}

pub async fn delete_analysis(
    State(state): State<AppState>,
    Path(id): Path<Uuid>,
) -> Result<StatusCode, ApiError> {
    match state.store.delete(&id).await {
        Ok(true) => Ok(StatusCode::NO_CONTENT),
        Ok(false) => Err(ApiError::new(
            StatusCode::NOT_FOUND,
            "NOT_FOUND",
            format!("analysis {id} not found"),
        )),
        Err(e) => Err(ApiError::new(
            StatusCode::INTERNAL_SERVER_ERROR,
            "INTERNAL",
            e.to_string(),
        )),
    }
}

#[derive(Debug, Deserialize)]
pub struct ExportQuery {
    #[serde(default)]
    pub format: Option<String>,
}

pub async fn export_analysis(
    State(state): State<AppState>,
    Path(id): Path<Uuid>,
    Query(query): Query<ExportQuery>,
) -> Result<Response, ApiError> {
    let record = state.store.get(&id).await.ok_or_else(|| {
        ApiError::new(
            StatusCode::NOT_FOUND,
            "NOT_FOUND",
            format!("analysis {id} not found"),
        )
    })?;

    let format = query.format.unwrap_or_else(|| "json".into()).to_lowercase();
    match format.as_str() {
        "json" => {
            let body = serde_json::to_string_pretty(&AnalysisView::from_record(&record))
                .unwrap_or_else(|_| "{}".into());
            Ok(Response::builder()
                .status(StatusCode::OK)
                .header(header::CONTENT_TYPE, "application/json")
                .header(
                    header::CONTENT_DISPOSITION,
                    format!("attachment; filename=\"tengu-{}.json\"", record.id),
                )
                .body(Body::from(body))
                .unwrap_or_else(|_| StatusCode::INTERNAL_SERVER_ERROR.into_response()))
        }
        "csv" => {
            let body = analysis_csv(&record);
            Ok(Response::builder()
                .status(StatusCode::OK)
                .header(header::CONTENT_TYPE, "text/csv; charset=utf-8")
                .header(
                    header::CONTENT_DISPOSITION,
                    format!("attachment; filename=\"tengu-{}.csv\"", record.id),
                )
                .body(Body::from(body))
                .unwrap_or_else(|_| StatusCode::INTERNAL_SERVER_ERROR.into_response()))
        }
        other => Err(ApiError::new(
            StatusCode::UNPROCESSABLE_ENTITY,
            "INVALID_FORMAT",
            format!("unsupported format '{other}' (use json or csv)"),
        )),
    }
}

fn csv_escape(value: &str) -> String {
    if value.contains(',') || value.contains('"') || value.contains('\n') || value.contains('\r') {
        format!("\"{}\"", value.replace('"', "\"\""))
    } else {
        value.to_string()
    }
}

pub(crate) fn analysis_csv(record: &AuditRecord) -> String {
    let mut out = String::from(
        "analysis_id,tool,severity,category,check,title,description,target_url,evidence\n",
    );
    if record.findings.is_empty() {
        out.push_str(&format!(
            "{},tengu,,,,,,,\n",
            csv_escape(&record.id.to_string())
        ));
        return out;
    }
    for finding in &record.findings {
        let contract = crate::contracts::finding_from_tengu(finding);
        let severity = format!("{:?}", contract.severity).to_lowercase();
        let evidence = contract
            .evidence
            .as_ref()
            .map(|e| e.to_string())
            .unwrap_or_default();
        let row = [
            record.id.to_string(),
            "tengu".to_string(),
            severity,
            contract.category.unwrap_or_default(),
            contract.check.unwrap_or_default(),
            contract.title,
            contract.description,
            contract.target_url.unwrap_or_default(),
            evidence,
        ];
        out.push_str(
            &row.iter()
                .map(|cell| csv_escape(cell))
                .collect::<Vec<_>>()
                .join(","),
        );
        out.push('\n');
    }
    out
}

// ---------------------------------------------------------------------------
// WebSocket: /api/audit/live streams xwa-sdk `Event` envelopes
// ---------------------------------------------------------------------------

pub async fn audit_live(
    State(state): State<AppState>,
    Query(params): Query<AuditOptions>,
    ws_upgrade: WebSocketUpgrade,
) -> impl IntoResponse {
    let store = state.store.clone();
    let sema = state.audit_semaphore.clone();
    let req_counter = state.request_count.clone();
    let cfg = state.config.clone();

    ws_upgrade.on_upgrade(move |mut socket| async move {
        req_counter.fetch_add(1, std::sync::atomic::Ordering::Relaxed);

        let (audit_id, audit_ts) = request_watermark();
        let mut emitter = EventEmitter::new(&mut socket, audit_id.clone());

        let _permit = match sema.acquire().await {
            Ok(permit) => permit,
            Err(_) => {
                emitter
                    .error("BUSY", "Too many concurrent audits. Try again later.", true)
                    .await;
                return;
            }
        };

        emitter.started(&params.url, &params.mode).await;
        tracing::info!(audit_id = %audit_id, url = %params.url, mode = %params.mode, "starting audit");

        match auditor::run_audit(&params, &mut emitter, &cfg).await {
            Ok(findings) => {
                let record = AuditRecord {
                    id: Uuid::parse_str(&audit_id).unwrap_or_else(|_| Uuid::new_v4()),
                    url: params.url.clone(),
                    status: "COMPLETED".to_string(),
                    findings: findings.clone(),
                    created_at: audit_ts,
                };
                if let Err(e) = store.insert(record).await {
                    tracing::error!(audit_id = %audit_id, error = %e, "failed to persist audit");
                }
                emitter.completed(&findings).await;
                tracing::info!(audit_id = %audit_id, "audit completed");
            }
            Err(e) => {
                let code = auditor::error_code(&e);
                emitter.error(code, &e, false).await;
                tracing::error!(audit_id = %audit_id, error = %e, "audit failed");
            }
        }
    })
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::auditor::{Finding as TenguFinding, Severity};

    fn record() -> AuditRecord {
        AuditRecord {
            id: Uuid::new_v4(),
            url: "https://example.com".into(),
            status: "COMPLETED".into(),
            findings: vec![TenguFinding {
                category: "seo".into(),
                check: "title".into(),
                severity: Severity::Warning,
                title: "Missing title".into(),
                description: "No <title>, commas, and \"quotes\"".into(),
                snippet: Some("<head></head>".into()),
                page_url: Some("https://example.com".into()),
            }],
            created_at: "2026-09-12T10:00:00Z".into(),
        }
    }

    #[test]
    fn analysis_view_maps_record_to_contract() {
        let view = AnalysisView::from_record(&record());
        assert_eq!(view.analysis.tool, Tool::Tengu);
        assert_eq!(view.analysis.status, AnalysisStatus::Completed);
        assert_eq!(
            view.analysis.tool_version.as_deref(),
            Some(env!("CARGO_PKG_VERSION"))
        );
        assert_eq!(
            view.findings[0].severity,
            crate::contracts::Severity::Medium
        );
        let summary = view.analysis.summary.unwrap();
        assert_eq!(summary.total_items, Some(1));
        assert_eq!(summary.by_severity["medium"], 1);
        assert_eq!(summary.by_category["seo"], 1);
    }

    #[test]
    fn csv_export_escapes_commas_and_quotes() {
        let csv = analysis_csv(&record());
        assert!(csv.starts_with("analysis_id,tool,severity,category,check,title,description"));
        assert!(csv
            .contains("medium,seo,title,Missing title,\"No <title>, commas, and \"\"quotes\"\"\""));
    }

    #[test]
    fn analysis_view_serializes_required_keys() {
        let value = serde_json::to_value(AnalysisView::from_record(&record())).unwrap();
        for key in ["id", "tool", "target", "status", "created_at", "findings"] {
            assert!(value.get(key).is_some(), "missing {key}");
        }
        assert_eq!(value["tool"], "tengu");
        assert_eq!(value["status"], "COMPLETED");
    }
}
