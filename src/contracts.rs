//! XWA SDK contracts (mirror of `xwa-sdk` 0.2.0 Rust binding).
//!
//! Tengu speaks the shared ecosystem contract on both REST and WebSocket:
//! [`Analysis`], [`Finding`], [`Event`], [`Error`] and [`Summary`]. The serde
//! representation is intentionally identical to the canonical JSON Schemas in
//! `xwa-sdk/bindings/python/xwa_sdk/schemas` so a unified XWA consumer can
//! deserialize Tengu payloads without adapters.

use std::collections::BTreeMap;
use std::fmt;

use serde::{Deserialize, Serialize};
use serde_json::Value;

/// Producing module.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash, Serialize, Deserialize)]
#[serde(rename_all = "lowercase")]
pub enum Tool {
    Samurai,
    Shinobi,
    Tengu,
    Kensei,
    Kabuki,
    Yari,
    Musha,
    Azuma,
}

/// Analysis lifecycle state.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash, Serialize, Deserialize)]
pub enum AnalysisStatus {
    #[serde(rename = "PENDING")]
    Pending,
    #[serde(rename = "RUNNING")]
    Running,
    #[serde(rename = "COMPLETED")]
    Completed,
    #[serde(rename = "ERROR")]
    Error,
    #[serde(rename = "CANCELLED")]
    Cancelled,
}

impl AnalysisStatus {
    pub fn as_str(self) -> &'static str {
        match self {
            Self::Pending => "PENDING",
            Self::Running => "RUNNING",
            Self::Completed => "COMPLETED",
            Self::Error => "ERROR",
            Self::Cancelled => "CANCELLED",
        }
    }
}

impl fmt::Display for AnalysisStatus {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.write_str(self.as_str())
    }
}

/// Unified severity scale.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash, PartialOrd, Ord, Serialize, Deserialize)]
#[serde(rename_all = "lowercase")]
pub enum Severity {
    Pass,
    Info,
    Low,
    Medium,
    High,
    Critical,
}

/// Detection confidence (present in the shared `Finding` schema).
#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash, Serialize, Deserialize)]
#[serde(rename_all = "lowercase")]
pub enum Confidence {
    High,
    Medium,
    Low,
}

/// Streaming event type.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum EventType {
    AnalysisStarted,
    AnalysisProgress,
    ItemFound,
    AnalysisCompleted,
    AnalysisError,
    Log,
}

/// Structured failure attached to an analysis.
#[derive(Debug, Clone, Default, PartialEq, Serialize, Deserialize)]
pub struct Error {
    pub code: String,
    pub message: String,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub detail: Option<Value>,
    #[serde(default)]
    pub retryable: bool,
}

/// Aggregated result counts.
#[derive(Debug, Clone, Default, PartialEq, Serialize, Deserialize)]
pub struct Summary {
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub total_items: Option<i64>,
    #[serde(default)]
    pub by_severity: BTreeMap<String, i64>,
    #[serde(default)]
    pub by_category: BTreeMap<String, i64>,
}

impl Summary {
    /// Build a summary from a set of findings, keyed by unified severity and
    /// Tengu category (also accepted by the schema's `additionalProperties`).
    pub fn from_findings(findings: &[Finding]) -> Self {
        let mut by_severity: BTreeMap<String, i64> = BTreeMap::new();
        let mut by_category: BTreeMap<String, i64> = BTreeMap::new();
        for finding in findings {
            *by_severity
                .entry(format!("{:?}", finding.severity).to_lowercase())
                .or_insert(0) += 1;
            if let Some(category) = &finding.category {
                *by_category.entry(category.clone()).or_insert(0) += 1;
            }
        }
        Self {
            total_items: Some(findings.len() as i64),
            by_severity,
            by_category,
        }
    }
}

/// Top-level unit of work produced by a tool.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct Analysis {
    pub id: String,
    pub tool: Tool,
    pub target: String,
    pub status: AnalysisStatus,
    pub created_at: String,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub tool_version: Option<String>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub analysis_type: Option<String>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub started_at: Option<String>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub finished_at: Option<String>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub error: Option<Error>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub summary: Option<Summary>,
}

impl Default for Analysis {
    fn default() -> Self {
        Self {
            id: String::new(),
            tool: Tool::Tengu,
            target: String::new(),
            status: AnalysisStatus::Pending,
            created_at: String::new(),
            tool_version: None,
            analysis_type: None,
            started_at: None,
            finished_at: None,
            error: None,
            summary: None,
        }
    }
}

/// A single observation mapped to the unified severity scale.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct Finding {
    pub tool: Tool,
    pub severity: Severity,
    pub title: String,
    pub description: String,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub id: Option<String>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub category: Option<String>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub check: Option<String>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub target_url: Option<String>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub evidence: Option<Value>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub cvss_score: Option<String>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub confidence: Option<Confidence>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub detected_at: Option<String>,
}

/// Streaming envelope for live analysis progress.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct Event {
    pub seq: i64,
    #[serde(rename = "type")]
    pub event_type: EventType,
    pub tool: Tool,
    pub analysis_id: String,
    pub ts: String,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub payload: Option<Value>,
}

/// Map Tengu's internal severity to the unified XWA scale.
///
/// `Pass → pass`, `Info → info`, `Warning → medium`, `Error → high` (same
/// mapping documented by `xwa-sdk::map_severity`).
pub fn map_severity(severity: crate::auditor::Severity) -> Severity {
    use crate::auditor::Severity as TenguSeverity;
    match severity {
        TenguSeverity::Pass => Severity::Pass,
        TenguSeverity::Info => Severity::Info,
        TenguSeverity::Warning => Severity::Medium,
        TenguSeverity::Error => Severity::High,
    }
}

/// Convert an internal Tengu finding into the shared [`Finding`] contract.
pub fn finding_from_tengu(finding: &crate::auditor::Finding) -> Finding {
    let evidence = finding.snippet.as_ref().map(|snippet| {
        serde_json::json!({
            "snippet": snippet,
        })
    });

    Finding {
        tool: Tool::Tengu,
        severity: map_severity(finding.severity),
        title: finding.title.clone(),
        description: finding.description.clone(),
        id: None,
        category: Some(finding.category.clone()),
        check: Some(finding.check.clone()),
        target_url: finding.page_url.clone(),
        evidence,
        cvss_score: None,
        confidence: None,
        detected_at: None,
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn minimal_analysis_json() -> serde_json::Value {
        serde_json::json!({
            "id": "audit-42",
            "tool": "tengu",
            "target": "https://example.com",
            "status": "COMPLETED",
            "created_at": "2026-09-12T10:00:00Z"
        })
    }

    #[test]
    fn analysis_deserializes_fixture() {
        let analysis: Analysis = serde_json::from_value(minimal_analysis_json()).unwrap();
        assert_eq!(analysis.tool, Tool::Tengu);
        assert_eq!(analysis.status, AnalysisStatus::Completed);
        assert_eq!(analysis.id, "audit-42");
        assert_eq!(analysis.target, "https://example.com");
    }

    #[test]
    fn analysis_serializes_required_fields() {
        let analysis: Analysis = serde_json::from_value(minimal_analysis_json()).unwrap();
        let value = serde_json::to_value(&analysis).unwrap();
        for key in ["id", "tool", "target", "status", "created_at"] {
            assert!(value.get(key).is_some(), "missing required key {key}");
        }
        // Optional fields are skipped when None, matching the Python `to_dict`.
        assert!(value.get("summary").is_none());
        assert!(value.get("error").is_none());
        assert_eq!(value["status"], "COMPLETED");
        assert_eq!(value["tool"], "tengu");
    }

    #[test]
    fn finding_deserializes_fixture_and_maps_severity() {
        let fixture = serde_json::json!({
            "tool": "tengu",
            "severity": "medium",
            "title": "Missing alt attribute",
            "description": "Images must have alternate text",
            "category": "accessibility",
            "check": "img_alt",
            "target_url": "https://example.com/page",
            "evidence": {"snippet": "<img src=\"a.png\">"}
        });
        let finding: Finding = serde_json::from_value(fixture).unwrap();
        assert_eq!(finding.severity, Severity::Medium);
        assert_eq!(finding.category.as_deref(), Some("accessibility"));
        assert_eq!(
            finding.evidence.as_ref().unwrap()["snippet"],
            "<img src=\"a.png\">"
        );

        let value = serde_json::to_value(&finding).unwrap();
        assert_eq!(value["severity"], "medium");
        assert_eq!(value["tool"], "tengu");
        assert!(value.get("confidence").is_none());
    }

    #[test]
    fn tengu_severity_mapping_is_faithful() {
        use crate::auditor::Severity as T;
        assert_eq!(map_severity(T::Pass), Severity::Pass);
        assert_eq!(map_severity(T::Info), Severity::Info);
        assert_eq!(map_severity(T::Warning), Severity::Medium);
        assert_eq!(map_severity(T::Error), Severity::High);
    }

    #[test]
    fn event_deserializes_fixture_and_serializes_type_key() {
        let fixture = serde_json::json!({
            "seq": 7,
            "type": "item_found",
            "tool": "tengu",
            "analysis_id": "audit-42",
            "ts": "2026-09-12T10:00:01Z",
            "payload": {"title": "Finding"}
        });
        let event: Event = serde_json::from_value(fixture).unwrap();
        assert_eq!(event.seq, 7);
        assert_eq!(event.event_type, EventType::ItemFound);
        let value = serde_json::to_value(&event).unwrap();
        assert_eq!(value["type"], "item_found");
        assert!(value.get("payload").is_some());
    }

    #[test]
    fn event_omits_empty_payload() {
        let event = Event {
            seq: 1,
            event_type: EventType::AnalysisStarted,
            tool: Tool::Tengu,
            analysis_id: "id-1".into(),
            ts: "2026-09-12T10:00:00Z".into(),
            payload: None,
        };
        let value = serde_json::to_value(&event).unwrap();
        assert!(value.get("payload").is_none());
        assert_eq!(value["type"], "analysis_started");
    }

    #[test]
    fn error_and_summary_fixtures() {
        let error: Error = serde_json::from_value(serde_json::json!({
            "code": "NETWORK_ERROR",
            "message": "connection reset",
            "retryable": true
        }))
        .unwrap();
        assert!(error.retryable);
        assert!(serde_json::to_value(&error)
            .unwrap()
            .get("detail")
            .is_none());

        let summary: Summary = serde_json::from_value(serde_json::json!({
            "total_items": 2,
            "by_severity": {"high": 1, "medium": 1},
            "by_category": {"seo": 2}
        }))
        .unwrap();
        assert_eq!(summary.total_items, Some(2));
        assert_eq!(summary.by_severity["high"], 1);
    }
}
