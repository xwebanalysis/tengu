from __future__ import annotations

from tengu.models import AuditRecord, Finding, Severity
from tengu.storage import SqliteStore


def test_sqlite_crud_and_retention(tmp_path):
    store = SqliteStore(str(tmp_path / "test.db"), max_records=2)
    for index in range(3):
        store.insert(AuditRecord(
            id=f"00000000-0000-0000-0000-00000000000{index}",
            url=f"https://{index}.example/",
            status="COMPLETED",
            findings=[Finding("seo", "title", Severity.WARNING, "t", "d")],
            created_at=f"2026-01-0{index + 1}T00:00:00+00:00",
        ))
    assert store.count() == 2
    assert store.get("00000000-0000-0000-0000-000000000000") is None
    assert store.get("00000000-0000-0000-0000-000000000002") is not None
    assert store.delete("00000000-0000-0000-0000-000000000002")
    assert store.count() == 1
    store.clear_all()
    assert store.count() == 0
    assert store.healthcheck()
    store.close()


def test_legacy_roundtrip():
    record = AuditRecord(
        id="00000000-0000-0000-0000-000000000001",
        url="https://example.com/",
        status="COMPLETED",
        findings=[Finding("a11y", "alt_text", Severity.ERROR, "Missing alt", "desc", "<img>")],
        created_at="2026-01-01T00:00:00+00:00",
    )
    assert AuditRecord.from_legacy(record.to_legacy()).findings[0].severity == Severity.ERROR
