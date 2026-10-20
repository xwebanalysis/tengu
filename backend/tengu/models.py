"""Internal models and xwa-sdk contract adapters."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import Enum
from typing import Any


class Severity(str, Enum):
    PASS = "Pass"
    INFO = "Info"
    WARNING = "Warning"
    ERROR = "Error"


CONTRACT_SEVERITY = {
    Severity.PASS: "pass",
    Severity.INFO: "info",
    Severity.WARNING: "medium",
    Severity.ERROR: "high",
}


@dataclass
class Finding:
    category: str
    check: str
    severity: Severity
    title: str
    description: str
    snippet: str | None = None
    page_url: str | None = None

    def to_legacy(self) -> dict[str, Any]:
        return {
            "category": self.category,
            "check": self.check,
            "severity": self.severity.value,
            "title": self.title,
            "description": self.description,
            "snippet": self.snippet,
            "page_url": self.page_url,
        }

    @classmethod
    def from_legacy(cls, raw: dict[str, Any]) -> Finding:
        return cls(
            category=str(raw.get("category", "")),
            check=str(raw.get("check", "")),
            severity=Severity(str(raw.get("severity", "Info"))),
            title=str(raw.get("title", "")),
            description=str(raw.get("description", "")),
            snippet=raw.get("snippet"),
            page_url=raw.get("page_url"),
        )


@dataclass
class AuditRecord:
    id: str
    url: str
    status: str
    findings: list[Finding] = field(default_factory=list)
    created_at: str = ""

    def to_legacy(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "url": self.url,
            "status": self.status,
            "findings": [f.to_legacy() for f in self.findings],
            "created_at": self.created_at,
        }

    @classmethod
    def from_legacy(cls, raw: dict[str, Any]) -> AuditRecord:
        return cls(
            id=str(raw.get("id", "")),
            url=str(raw.get("url", "")),
            status=str(raw.get("status", "COMPLETED")),
            findings=[Finding.from_legacy(f) for f in raw.get("findings", [])],
            created_at=str(raw.get("created_at", "")),
        )


def utc_now() -> str:
    return datetime.now(UTC).isoformat(timespec="microseconds")


def request_watermark() -> tuple[str, str]:
    return str(uuid.uuid4()), utc_now()


def finding_to_contract(finding: Finding) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "tool": "tengu",
        "severity": CONTRACT_SEVERITY[finding.severity],
        "title": finding.title,
        "description": finding.description,
        "category": finding.category,
        "check": finding.check,
    }
    if finding.page_url:
        payload["target_url"] = finding.page_url
    if finding.snippet:
        payload["evidence"] = {"snippet": finding.snippet}
    return payload


def summary_from_findings(findings: list[Finding]) -> dict[str, Any]:
    by_severity: dict[str, int] = {}
    by_category: dict[str, int] = {}
    for finding in findings:
        severity = CONTRACT_SEVERITY[finding.severity]
        by_severity[severity] = by_severity.get(severity, 0) + 1
        by_category[finding.category] = by_category.get(finding.category, 0) + 1
    return {
        "total_items": len(findings),
        "by_severity": by_severity,
        "by_category": by_category,
    }


def analysis_view(record: AuditRecord, version: str = "0.2.0") -> dict[str, Any]:
    findings = [finding_to_contract(f) for f in record.findings]
    status = {
        "PENDING": "PENDING",
        "RUNNING": "RUNNING",
        "ERROR": "ERROR",
        "CANCELLED": "CANCELLED",
    }.get(record.status, "COMPLETED")
    return {
        "id": record.id,
        "tool": "tengu",
        "target": record.url,
        "status": status,
        "created_at": record.created_at,
        "tool_version": version,
        "analysis_type": "audit",
        "started_at": record.created_at,
        "finished_at": None,
        "error": None,
        "summary": summary_from_findings(record.findings),
        "findings": findings,
    }


def error_envelope(code: str, message: str, *, retryable: bool = False, detail: Any = None) -> dict[str, Any]:
    return {
        "error": {
            "code": code,
            "message": message,
            "detail": detail,
            "retryable": retryable,
        }
    }
