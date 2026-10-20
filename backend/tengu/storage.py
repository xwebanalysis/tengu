"""SQLite persistence for audit records (same schema as the Rust backend)."""

from __future__ import annotations

import json
import sqlite3
import threading
from pathlib import Path

from .config import Config
from .models import AuditRecord, Finding

SCHEMA_VERSION = 1


class StoreError(RuntimeError):
    pass


class SqliteStore:
    kind = "sqlite"

    def __init__(self, db_path: str, max_records: int = 100) -> None:
        self.db_path = db_path
        self.max_records = max(1, max_records)
        self._lock = threading.RLock()
        if db_path != ":memory:":
            parent = Path(db_path).expanduser().parent
            if str(parent) not in ("", "."):
                parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(db_path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._migrate()

    def _migrate(self) -> None:
        with self._lock:
            self._conn.execute("PRAGMA journal_mode=WAL")
            self._conn.execute("PRAGMA busy_timeout=5000")
            self._conn.execute("PRAGMA foreign_keys=ON")
            self._conn.execute("PRAGMA synchronous=NORMAL")
            self._conn.execute("CREATE TABLE IF NOT EXISTS schema_meta (version INTEGER NOT NULL)")
            self._conn.execute(
                """CREATE TABLE IF NOT EXISTS audits (
                    id TEXT PRIMARY KEY,
                    url TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'COMPLETED',
                    findings TEXT NOT NULL DEFAULT '[]',
                    created_at TEXT NOT NULL
                )"""
            )
            self._conn.execute(
                "INSERT INTO schema_meta (version) SELECT ? "
                "WHERE NOT EXISTS (SELECT 1 FROM schema_meta)",
                (SCHEMA_VERSION,),
            )
            self._conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_audits_created_at ON audits(created_at DESC)"
            )
            self._conn.commit()

    def healthcheck(self) -> bool:
        try:
            with self._lock:
                self._conn.execute("SELECT 1").fetchone()
            return True
        except sqlite3.Error:
            return False

    def list(self) -> list[AuditRecord]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT id, url, status, findings, created_at FROM audits ORDER BY created_at DESC"
            ).fetchall()
        return [self._row_to_record(row) for row in rows]

    def get(self, audit_id: str) -> AuditRecord | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT id, url, status, findings, created_at FROM audits WHERE id = ?",
                (audit_id,),
            ).fetchone()
        return self._row_to_record(row) if row else None

    def insert(self, record: AuditRecord) -> None:
        findings = json.dumps([f.to_legacy() for f in record.findings], ensure_ascii=False)
        with self._lock:
            self._conn.execute(
                """INSERT INTO audits (id, url, status, findings, created_at)
                   VALUES (?, ?, ?, ?, ?)
                   ON CONFLICT(id) DO UPDATE SET
                     url = excluded.url,
                     status = excluded.status,
                     findings = excluded.findings,
                     created_at = excluded.created_at""",
                (record.id, record.url, record.status, findings, record.created_at),
            )
            self._enforce_retention()
            self._conn.commit()

    def _enforce_retention(self) -> None:
        count = self._conn.execute("SELECT COUNT(*) FROM audits").fetchone()[0]
        if count > self.max_records:
            self._conn.execute(
                "DELETE FROM audits WHERE id NOT IN "
                "(SELECT id FROM audits ORDER BY created_at DESC LIMIT ?)",
                (self.max_records,),
            )

    def delete(self, audit_id: str) -> bool:
        with self._lock:
            cur = self._conn.execute("DELETE FROM audits WHERE id = ?", (audit_id,))
            self._conn.commit()
            return cur.rowcount > 0

    def clear_all(self) -> None:
        with self._lock:
            self._conn.execute("DELETE FROM audits")
            self._conn.commit()

    def count(self) -> int:
        with self._lock:
            return int(self._conn.execute("SELECT COUNT(*) FROM audits").fetchone()[0])

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    def _row_to_record(self, row: sqlite3.Row) -> AuditRecord:
        try:
            findings = [Finding.from_legacy(f) for f in json.loads(row["findings"] or "[]")]
        except (ValueError, TypeError):
            findings = []
        return AuditRecord(
            id=str(row["id"]),
            url=str(row["url"]),
            status=str(row["status"]),
            findings=findings,
            created_at=str(row["created_at"]),
        )


class MemoryStore:
    kind = "memory"

    def __init__(self, max_records: int = 100) -> None:
        self.max_records = max(1, max_records)
        self._records: dict[str, AuditRecord] = {}
        self._lock = threading.RLock()

    def healthcheck(self) -> bool:
        return True

    def list(self) -> list[AuditRecord]:
        with self._lock:
            return sorted(self._records.values(), key=lambda r: r.created_at, reverse=True)

    def get(self, audit_id: str) -> AuditRecord | None:
        with self._lock:
            return self._records.get(audit_id)

    def insert(self, record: AuditRecord) -> None:
        with self._lock:
            self._records[record.id] = record
            if len(self._records) > self.max_records:
                oldest = sorted(self._records.values(), key=lambda r: r.created_at)[
                    : len(self._records) - self.max_records
                ]
                for item in oldest:
                    self._records.pop(item.id, None)

    def delete(self, audit_id: str) -> bool:
        with self._lock:
            return self._records.pop(audit_id, None) is not None

    def clear_all(self) -> None:
        with self._lock:
            self._records.clear()

    def count(self) -> int:
        with self._lock:
            return len(self._records)

    def close(self) -> None:
        self.clear_all()


def create_store(cfg: Config) -> SqliteStore | MemoryStore:
    try:
        return SqliteStore(cfg.db_path, cfg.max_history)
    except Exception:
        return MemoryStore(cfg.max_history)
