"""WebSocket event emitter for the xwa-sdk Event protocol."""

from __future__ import annotations

from typing import Any

from fastapi import WebSocket

from .models import Finding, finding_to_contract, summary_from_findings, utc_now


class EventEmitter:
    def __init__(self, socket: WebSocket, analysis_id: str) -> None:
        self.socket = socket
        self.analysis_id = analysis_id
        self.seq = 0

    async def emit(self, event_type: str, payload: dict[str, Any] | None = None) -> None:
        self.seq += 1
        event: dict[str, Any] = {
            "seq": self.seq,
            "type": event_type,
            "tool": "tengu",
            "analysis_id": self.analysis_id,
            "ts": utc_now(),
        }
        if payload is not None:
            event["payload"] = payload
        try:
            await self.socket.send_json(event)
        except Exception:
            # The client may have disconnected; audit work can continue and persist.
            pass

    async def started(self, target: str, mode: str) -> None:
        await self.emit("analysis_started", {"target": target, "mode": mode})

    async def progress(self, message: str, percent: float | None = None) -> None:
        payload: dict[str, Any] = {"message": message}
        if percent is not None:
            payload["percent"] = max(0.0, min(100.0, percent))
        await self.emit("analysis_progress", payload)

    async def log(self, level: str, message: str, data: dict[str, Any] | None = None) -> None:
        payload: dict[str, Any] = {"level": level, "message": message}
        if data is not None:
            payload["data"] = data
        await self.emit("log", payload)

    async def item_found(self, finding: Finding) -> None:
        await self.emit("item_found", finding_to_contract(finding))

    async def completed(self, findings: list[Finding]) -> None:
        await self.emit(
            "analysis_completed",
            {"status": "COMPLETED", "summary": summary_from_findings(findings)},
        )

    async def error(self, code: str, message: str, retryable: bool = False) -> None:
        await self.emit(
            "analysis_error",
            {"code": code, "message": message, "detail": None, "retryable": retryable},
        )


def error_code(message: str) -> str:
    lower = message.lower()
    if "invalid url" in lower or "invalid target" in lower:
        return "INVALID_TARGET"
    if "robots" in lower:
        return "ROBOTS_DENIED"
    if "timeout" in lower or "timed out" in lower:
        return "TIMEOUT"
    if "fetch" in lower or "network" in lower or "dns" in lower:
        return "NETWORK_ERROR"
    return "INTERNAL"
