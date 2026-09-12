use std::sync::Arc;
use std::time::Duration;

use dashmap::DashMap;
use serde::{Deserialize, Serialize};
use uuid::Uuid;

use crate::auditor::Finding;
use crate::config::TenguConfig;

// ---------------------------------------------------------------------------
// Persisted audit record (shared by memory, SQLite and PostgreSQL backends)
// ---------------------------------------------------------------------------

#[derive(Debug, Serialize, Deserialize, Clone)]
pub struct AuditRecord {
    pub id: Uuid,
    pub url: String,
    pub status: String,
    pub findings: Vec<Finding>,
    pub created_at: String,
}

// ---------------------------------------------------------------------------
// Store errors
// ---------------------------------------------------------------------------

#[derive(Debug, thiserror::Error)]
pub enum StoreError {
    #[error("database error: {0}")]
    Database(#[from] sqlx::Error),
    #[error("io error: {0}")]
    Io(#[from] std::io::Error),
    #[error("{0}")]
    Config(String),
}

// ---------------------------------------------------------------------------
// Unified audit store
// ---------------------------------------------------------------------------

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum StoreKind {
    Memory,
    Sqlite,
    Postgres,
}

impl StoreKind {
    pub fn as_str(self) -> &'static str {
        match self {
            Self::Memory => "memory",
            Self::Sqlite => "sqlite",
            Self::Postgres => "postgres",
        }
    }
}

enum Backend {
    Memory(DashMap<Uuid, AuditRecord>),
    Sqlite(sqlx::SqlitePool),
    #[cfg(feature = "pg")]
    Postgres(sqlx::PgPool),
}

#[derive(Clone)]
pub struct AuditStore {
    inner: Arc<Backend>,
    max_records: usize,
    kind: StoreKind,
}

impl AuditStore {
    /// In-memory store (DashMap). Used as a fallback when SQLite cannot be
    /// opened and as the test/substrate backend.
    pub fn memory(max_records: usize) -> Self {
        Self {
            inner: Arc::new(Backend::Memory(DashMap::new())),
            max_records: max_records.max(1),
            kind: StoreKind::Memory,
        }
    }

    pub fn kind(&self) -> StoreKind {
        self.kind
    }

    /// Human-readable status used by `/api/health`.
    pub async fn healthcheck(&self) -> bool {
        match self.inner.as_ref() {
            Backend::Memory(_) => true,
            Backend::Sqlite(pool) => sqlx::query_scalar::<_, i64>("SELECT 1")
                .fetch_one(pool)
                .await
                .is_ok(),
            #[cfg(feature = "pg")]
            Backend::Postgres(pool) => sqlx::query_scalar::<_, i64>("SELECT 1")
                .fetch_one(pool)
                .await
                .is_ok(),
        }
    }

    pub async fn list(&self) -> Vec<AuditRecord> {
        match self.inner.as_ref() {
            Backend::Memory(audits) => {
                let mut all: Vec<AuditRecord> = audits.iter().map(|r| r.value().clone()).collect();
                all.sort_by(|a, b| b.created_at.cmp(&a.created_at));
                all
            }
            Backend::Sqlite(pool) => {
                let rows = sqlx::query(
                    "SELECT id, url, status, findings, created_at FROM audits \
                     ORDER BY created_at DESC",
                )
                .fetch_all(pool)
                .await;
                match rows {
                    Ok(rows) => rows
                        .iter()
                        .filter_map(|row| record_from_sqlite_row(row).ok())
                        .collect(),
                    Err(e) => {
                        tracing::error!("SQLite list failed: {}", e);
                        Vec::new()
                    }
                }
            }
            #[cfg(feature = "pg")]
            Backend::Postgres(pool) => {
                let rows = sqlx::query(
                    "SELECT id, url, status, findings, created_at FROM audits \
                     ORDER BY created_at DESC",
                )
                .fetch_all(pool)
                .await;
                match rows {
                    Ok(rows) => rows
                        .iter()
                        .filter_map(|row| record_from_pg_row(row).ok())
                        .collect(),
                    Err(e) => {
                        tracing::error!("PostgreSQL list failed: {}", e);
                        Vec::new()
                    }
                }
            }
        }
    }

    pub async fn get(&self, id: &Uuid) -> Option<AuditRecord> {
        match self.inner.as_ref() {
            Backend::Memory(audits) => audits.get(id).map(|r| r.clone()),
            Backend::Sqlite(pool) => {
                let row = sqlx::query(
                    "SELECT id, url, status, findings, created_at FROM audits WHERE id = ?",
                )
                .bind(id.to_string())
                .fetch_optional(pool)
                .await
                .ok()
                .flatten()?;
                record_from_sqlite_row(&row).ok()
            }
            #[cfg(feature = "pg")]
            Backend::Postgres(pool) => {
                let row = sqlx::query(
                    "SELECT id, url, status, findings, created_at FROM audits WHERE id = $1",
                )
                .bind(*id)
                .fetch_optional(pool)
                .await
                .ok()
                .flatten()?;
                record_from_pg_row(&row).ok()
            }
        }
    }

    /// Write-through insert: memory keeps a bounded DashMap, SQLite/PostgreSQL
    /// persist immediately with an upsert (no background sync loop).
    pub async fn insert(&self, record: AuditRecord) -> Result<(), StoreError> {
        match self.inner.as_ref() {
            Backend::Memory(audits) => {
                audits.insert(record.id, record);
                self.enforce_memory_retention(audits);
            }
            Backend::Sqlite(pool) => {
                let findings =
                    serde_json::to_string(&record.findings).unwrap_or_else(|_| "[]".into());
                sqlx::query(
                    "INSERT INTO audits (id, url, status, findings, created_at) \
                     VALUES (?, ?, ?, ?, ?) \
                     ON CONFLICT(id) DO UPDATE SET \
                         url = excluded.url, status = excluded.status, \
                         findings = excluded.findings, created_at = excluded.created_at",
                )
                .bind(record.id.to_string())
                .bind(&record.url)
                .bind(&record.status)
                .bind(findings)
                .bind(&record.created_at)
                .execute(pool)
                .await?;
                self.enforce_sqlite_retention(pool).await?;
            }
            #[cfg(feature = "pg")]
            Backend::Postgres(pool) => {
                let findings = serde_json::to_value(&record.findings).unwrap_or_default();
                sqlx::query(
                    "INSERT INTO audits (id, url, status, findings, created_at) \
                     VALUES ($1, $2, $3, $4, $5) \
                     ON CONFLICT (id) DO UPDATE SET \
                         url = EXCLUDED.url, status = EXCLUDED.status, \
                         findings = EXCLUDED.findings, created_at = EXCLUDED.created_at",
                )
                .bind(record.id)
                .bind(&record.url)
                .bind(&record.status)
                .bind(&findings)
                .bind(&record.created_at)
                .execute(pool)
                .await?;
                self.enforce_pg_retention(pool).await?;
            }
        }
        Ok(())
    }

    pub async fn delete(&self, id: &Uuid) -> Result<bool, StoreError> {
        match self.inner.as_ref() {
            Backend::Memory(audits) => Ok(audits.remove(id).is_some()),
            Backend::Sqlite(pool) => {
                let result = sqlx::query("DELETE FROM audits WHERE id = ?")
                    .bind(id.to_string())
                    .execute(pool)
                    .await?;
                Ok(result.rows_affected() > 0)
            }
            #[cfg(feature = "pg")]
            Backend::Postgres(pool) => {
                let result = sqlx::query("DELETE FROM audits WHERE id = $1")
                    .bind(*id)
                    .execute(pool)
                    .await?;
                Ok(result.rows_affected() > 0)
            }
        }
    }

    pub async fn clear_all(&self) -> Result<(), StoreError> {
        match self.inner.as_ref() {
            Backend::Memory(audits) => {
                audits.clear();
                Ok(())
            }
            Backend::Sqlite(pool) => {
                sqlx::query("DELETE FROM audits").execute(pool).await?;
                Ok(())
            }
            #[cfg(feature = "pg")]
            Backend::Postgres(pool) => {
                sqlx::query("DELETE FROM audits").execute(pool).await?;
                Ok(())
            }
        }
    }

    pub async fn count(&self) -> usize {
        match self.inner.as_ref() {
            Backend::Memory(audits) => audits.len(),
            Backend::Sqlite(pool) => sqlx::query_scalar::<_, i64>("SELECT COUNT(*) FROM audits")
                .fetch_one(pool)
                .await
                .unwrap_or(0) as usize,
            #[cfg(feature = "pg")]
            Backend::Postgres(pool) => sqlx::query_scalar::<_, i64>("SELECT COUNT(*) FROM audits")
                .fetch_one(pool)
                .await
                .unwrap_or(0) as usize,
        }
    }

    fn enforce_memory_retention(&self, audits: &DashMap<Uuid, AuditRecord>) {
        if audits.len() <= self.max_records {
            return;
        }
        let mut all: Vec<(Uuid, String)> = audits
            .iter()
            .map(|r| (*r.key(), r.value().created_at.clone()))
            .collect();
        all.sort_by(|a, b| b.1.cmp(&a.1));
        let to_remove = all.len().saturating_sub(self.max_records);
        for (id, _) in all.iter().rev().take(to_remove) {
            audits.remove(id);
        }
        tracing::info!("Retention policy pruned {} old audit(s)", to_remove);
    }

    async fn enforce_sqlite_retention(&self, pool: &sqlx::SqlitePool) -> Result<(), StoreError> {
        let count: i64 = sqlx::query_scalar("SELECT COUNT(*) FROM audits")
            .fetch_one(pool)
            .await?;
        if count as usize > self.max_records {
            sqlx::query(
                "DELETE FROM audits WHERE id NOT IN \
                 (SELECT id FROM audits ORDER BY created_at DESC LIMIT ?)",
            )
            .bind(self.max_records as i64)
            .execute(pool)
            .await?;
        }
        Ok(())
    }

    #[cfg(feature = "pg")]
    async fn enforce_pg_retention(&self, pool: &sqlx::PgPool) -> Result<(), StoreError> {
        let count: i64 = sqlx::query_scalar("SELECT COUNT(*) FROM audits")
            .fetch_one(pool)
            .await?;
        if count as usize > self.max_records {
            sqlx::query(
                "DELETE FROM audits WHERE id NOT IN \
                 (SELECT id FROM audits ORDER BY created_at DESC LIMIT $1)",
            )
            .bind(self.max_records as i64)
            .execute(pool)
            .await?;
        }
        Ok(())
    }
}

// ---------------------------------------------------------------------------
// SQLite store (default persistent backend)
// ---------------------------------------------------------------------------

const SQLITE_SCHEMA_VERSION: i64 = 1;

pub async fn create_sqlite_store(
    db_path: &str,
    max_records: usize,
) -> Result<AuditStore, StoreError> {
    use sqlx::sqlite::{
        SqliteConnectOptions, SqliteJournalMode, SqlitePoolOptions, SqliteSynchronous,
    };

    if db_path != ":memory:" {
        if let Some(parent) = std::path::Path::new(db_path).parent() {
            if !parent.as_os_str().is_empty() {
                std::fs::create_dir_all(parent)?;
            }
        }
    }

    let options = SqliteConnectOptions::new()
        .filename(db_path)
        .create_if_missing(true)
        .journal_mode(SqliteJournalMode::Wal)
        .busy_timeout(Duration::from_millis(5000))
        .foreign_keys(true)
        .synchronous(SqliteSynchronous::Normal);

    let pool = SqlitePoolOptions::new()
        .max_connections(5)
        .connect_with(options)
        .await?;

    migrate_sqlite(&pool).await?;

    let store = AuditStore {
        inner: Arc::new(Backend::Sqlite(pool)),
        max_records: max_records.max(1),
        kind: StoreKind::Sqlite,
    };

    let loaded = store.list().await.len();
    tracing::info!(
        "SQLite store ready at {} ({} audit(s) loaded, schema v{})",
        db_path,
        loaded,
        SQLITE_SCHEMA_VERSION
    );

    Ok(store)
}

async fn migrate_sqlite(pool: &sqlx::SqlitePool) -> Result<(), StoreError> {
    sqlx::query("CREATE TABLE IF NOT EXISTS schema_meta (version INTEGER NOT NULL)")
        .execute(pool)
        .await?;
    sqlx::query(
        "CREATE TABLE IF NOT EXISTS audits (
            id TEXT PRIMARY KEY,
            url TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'COMPLETED',
            findings TEXT NOT NULL DEFAULT '[]',
            created_at TEXT NOT NULL
        )",
    )
    .execute(pool)
    .await?;
    sqlx::query(
        "INSERT INTO schema_meta (version) \
         SELECT ? WHERE NOT EXISTS (SELECT 1 FROM schema_meta)",
    )
    .bind(SQLITE_SCHEMA_VERSION)
    .execute(pool)
    .await?;
    sqlx::query("CREATE INDEX IF NOT EXISTS idx_audits_created_at ON audits(created_at DESC)")
        .execute(pool)
        .await?;
    Ok(())
}

fn record_from_sqlite_row(row: &sqlx::sqlite::SqliteRow) -> Result<AuditRecord, StoreError> {
    use sqlx::Row;
    let id_raw: String = row.try_get("id")?;
    let findings_raw: String = row.try_get("findings")?;
    let findings: Vec<Finding> = serde_json::from_str(&findings_raw).unwrap_or_default();
    Ok(AuditRecord {
        id: Uuid::parse_str(&id_raw)
            .map_err(|e| StoreError::Config(format!("invalid audit id '{id_raw}': {e}")))?,
        url: row.try_get("url")?,
        status: row.try_get("status")?,
        findings,
        created_at: row.try_get("created_at")?,
    })
}

// ---------------------------------------------------------------------------
// PostgreSQL store (optional `pg` feature, also write-through)
// ---------------------------------------------------------------------------

#[cfg(feature = "pg")]
pub async fn create_pg_store(
    database_url: &str,
    max_records: usize,
) -> Result<AuditStore, StoreError> {
    use sqlx::postgres::PgPoolOptions;

    let pool = PgPoolOptions::new()
        .max_connections(5)
        .connect(database_url)
        .await?;

    sqlx::query("CREATE TABLE IF NOT EXISTS schema_meta (version INTEGER NOT NULL)")
        .execute(&pool)
        .await?;
    sqlx::query(
        "CREATE TABLE IF NOT EXISTS audits (
            id UUID PRIMARY KEY,
            url TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'COMPLETED',
            findings JSONB NOT NULL DEFAULT '[]'::jsonb,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )",
    )
    .execute(&pool)
    .await?;
    sqlx::query(
        "INSERT INTO schema_meta (version) \
         SELECT 1 WHERE NOT EXISTS (SELECT 1 FROM schema_meta)",
    )
    .execute(&pool)
    .await?;

    let store = AuditStore {
        inner: Arc::new(Backend::Postgres(pool)),
        max_records: max_records.max(1),
        kind: StoreKind::Postgres,
    };

    let loaded = store.list().await.len();
    tracing::info!(
        "PostgreSQL store ready ({} audit(s) loaded, write-through)",
        loaded
    );
    Ok(store)
}

#[cfg(feature = "pg")]
fn record_from_pg_row(row: &sqlx::postgres::PgRow) -> Result<AuditRecord, StoreError> {
    use sqlx::Row;
    let id: Uuid = row.try_get("id")?;
    let findings_json: serde_json::Value = row.try_get("findings")?;
    let findings: Vec<Finding> = serde_json::from_value(findings_json).unwrap_or_default();
    let created_at: chrono::DateTime<chrono::Utc> = row.try_get("created_at")?;
    Ok(AuditRecord {
        id,
        url: row.try_get("url")?,
        status: row.try_get("status")?,
        findings,
        created_at: created_at.to_rfc3339(),
    })
}

#[cfg(not(feature = "pg"))]
pub async fn create_pg_store(
    _database_url: &str,
    _max_records: usize,
) -> Result<AuditStore, StoreError> {
    Err(StoreError::Config(
        "PostgreSQL support not compiled. Build with --features pg".into(),
    ))
}

// ---------------------------------------------------------------------------
// Store factory (used by main)
// ---------------------------------------------------------------------------

pub async fn create_store(cfg: &TenguConfig) -> AuditStore {
    if let Some(db_url) = &cfg.database_url {
        match create_pg_store(db_url, cfg.max_history).await {
            Ok(store) => return store,
            Err(e) => {
                tracing::warn!(
                    "PostgreSQL unavailable ({}); falling back to SQLite at {}",
                    e,
                    cfg.db_path
                );
            }
        }
    }

    match create_sqlite_store(&cfg.db_path, cfg.max_history).await {
        Ok(store) => store,
        Err(e) => {
            tracing::error!(
                "SQLite store unavailable at {} ({}); falling back to in-memory",
                cfg.db_path,
                e
            );
            AuditStore::memory(cfg.max_history)
        }
    }
}

/// Request watermarking
pub fn request_watermark() -> (String, String) {
    let id = Uuid::new_v4().to_string();
    let ts = chrono::Utc::now().to_rfc3339();
    (id, ts)
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

#[cfg(test)]
mod tests {
    use super::*;
    use crate::auditor::Severity;

    fn temp_db_path(tag: &str) -> std::path::PathBuf {
        std::env::temp_dir().join(format!("tengu-test-{tag}-{}.db", Uuid::new_v4()))
    }

    fn cleanup(path: &std::path::Path) {
        for suffix in ["", "-wal", "-shm"] {
            let _ = std::fs::remove_file(format!("{}{}", path.display(), suffix));
        }
    }

    fn record(url: &str, created_at: &str) -> AuditRecord {
        AuditRecord {
            id: Uuid::new_v4(),
            url: url.to_string(),
            status: "COMPLETED".into(),
            findings: vec![Finding {
                category: "seo".into(),
                check: "title".into(),
                severity: Severity::Warning,
                title: "Missing title".into(),
                description: "The page has no <title>".into(),
                snippet: Some("<head></head>".into()),
                page_url: Some(url.to_string()),
            }],
            created_at: created_at.to_string(),
        }
    }

    #[tokio::test]
    async fn sqlite_crud_roundtrip() {
        let path = temp_db_path("crud");
        let store = create_sqlite_store(path.to_str().unwrap(), 100)
            .await
            .unwrap();

        let a = record("https://a.example", "2026-09-12T10:00:00Z");
        let b = record("https://b.example", "2026-09-12T11:00:00Z");
        store.insert(a.clone()).await.unwrap();
        store.insert(b.clone()).await.unwrap();

        assert_eq!(store.count().await, 2);
        let listed = store.list().await;
        assert_eq!(listed[0].url, "https://b.example"); // newest first
        assert_eq!(listed[1].url, "https://a.example");

        let fetched = store.get(&a.id).await.unwrap();
        assert_eq!(fetched.findings.len(), 1);
        assert_eq!(fetched.findings[0].severity, Severity::Warning);

        assert!(store.delete(&a.id).await.unwrap());
        assert!(!store.delete(&a.id).await.unwrap());
        assert_eq!(store.count().await, 1);

        store.clear_all().await.unwrap();
        assert_eq!(store.count().await, 0);
        assert!(store.get(&b.id).await.is_none());

        drop(store);
        cleanup(&path);
    }

    #[tokio::test]
    async fn sqlite_persists_across_reopen() {
        let path = temp_db_path("persist");
        let record = record("https://persist.example", "2026-09-12T12:00:00Z");
        let id = record.id;

        {
            let store = create_sqlite_store(path.to_str().unwrap(), 100)
                .await
                .unwrap();
            store.insert(record.clone()).await.unwrap();
        }

        let reopened = create_sqlite_store(path.to_str().unwrap(), 100)
            .await
            .unwrap();
        let loaded = reopened.get(&id).await.expect("record must survive reopen");
        assert_eq!(loaded.url, "https://persist.example");
        assert_eq!(loaded.findings.len(), 1);
        assert_eq!(reopened.count().await, 1);
        drop(reopened);
        cleanup(&path);
    }

    #[tokio::test]
    async fn sqlite_applies_pragmas_and_schema_meta() {
        let path = temp_db_path("pragma");
        let store = create_sqlite_store(path.to_str().unwrap(), 100)
            .await
            .unwrap();
        let pool = match store.inner.as_ref() {
            Backend::Sqlite(pool) => pool.clone(),
            _ => panic!("expected sqlite backend"),
        };

        let journal: String = sqlx::query_scalar("PRAGMA journal_mode")
            .fetch_one(&pool)
            .await
            .unwrap();
        assert_eq!(journal.to_lowercase(), "wal");
        let fk: i64 = sqlx::query_scalar("PRAGMA foreign_keys")
            .fetch_one(&pool)
            .await
            .unwrap();
        assert_eq!(fk, 1);
        let timeout: i64 = sqlx::query_scalar("PRAGMA busy_timeout")
            .fetch_one(&pool)
            .await
            .unwrap();
        assert_eq!(timeout, 5000);
        let version: i64 = sqlx::query_scalar("SELECT version FROM schema_meta LIMIT 1")
            .fetch_one(&pool)
            .await
            .unwrap();
        assert_eq!(version, SQLITE_SCHEMA_VERSION);
        drop(store);
        cleanup(&path);
    }

    #[tokio::test]
    async fn sqlite_enforces_retention() {
        let path = temp_db_path("retention");
        let store = create_sqlite_store(path.to_str().unwrap(), 2)
            .await
            .unwrap();
        for hour in 0..4 {
            store
                .insert(record(
                    &format!("https://{hour}.example"),
                    &format!("2026-09-12T0{hour}:00:00Z"),
                ))
                .await
                .unwrap();
        }
        assert_eq!(store.count().await, 2);
        let urls: Vec<String> = store.list().await.into_iter().map(|r| r.url).collect();
        assert_eq!(urls, vec!["https://3.example", "https://2.example"]);
        drop(store);
        cleanup(&path);
    }

    #[tokio::test]
    async fn memory_store_retention_and_clear() {
        let store = AuditStore::memory(2);
        assert_eq!(store.kind(), StoreKind::Memory);
        assert!(store.healthcheck().await);
        for hour in 0..3 {
            store
                .insert(record(
                    &format!("https://m{hour}.example"),
                    &format!("2026-09-12T0{hour}:00:00Z"),
                ))
                .await
                .unwrap();
        }
        assert_eq!(store.count().await, 2);
        store.clear_all().await.unwrap();
        assert!(store.list().await.is_empty());
    }
}
