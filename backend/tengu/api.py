"""FastAPI application: REST, WebSocket events and SPA serving."""

from __future__ import annotations

import asyncio
import hmac
import io
import json
import mimetypes
import time
import uuid
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, PlainTextResponse, Response

from .audit.runner import run_audit
from .config import VERSION, AuditOptions, Config
from .events import EventEmitter, error_code
from .models import (
    AuditRecord,
    analysis_view,
    error_envelope,
    finding_to_contract,
    request_watermark,
    utc_now,
)
from .storage import create_store


class TokenBucket:
    def __init__(self, per_minute: float, burst: int) -> None:
        self.rate = max(1.0, per_minute) / 60.0
        self.max_burst = float(max(1, burst))
        self.tokens = self.max_burst
        self.last = time.monotonic()
        self.lock = asyncio.Lock()

    async def allow(self) -> bool:
        async with self.lock:
            now = time.monotonic()
            self.tokens = min(self.max_burst, self.tokens + (now - self.last) * self.rate)
            self.last = now
            if self.tokens >= 1.0:
                self.tokens -= 1.0
                return True
            return False


def _local_origin_regex() -> str:
    return (
        r"https?://("
        r"localhost|127\.0\.0\.1|\[::1\]|"
        r"10\.\d{1,3}\.\d{1,3}\.\d{1,3}|"
        r"192\.168\.\d{1,3}\.\d{1,3}|"
        r"172\.(1[6-9]|2\d|3[01])\.\d{1,3}\.\d{1,3}"
        r")(:\d+)?$"
    )


def _dump_json(value) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def _parse_bool(value: str | None) -> bool:
    return value in ("1", "true", "True", "yes", "on")


def create_app(cfg: Config | None = None) -> FastAPI:
    cfg = cfg or Config.from_env()
    store = create_store(cfg)
    rate = TokenBucket(cfg.rate_limit_per_minute, cfg.rate_limit_burst)
    semaphore = asyncio.Semaphore(cfg.max_concurrent_audits)
    request_count = 0

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        yield
        close = getattr(store, "close", None)
        if close:
            close()

    app = FastAPI(title="Tengu", version=VERSION, lifespan=lifespan)
    app.state.cfg = cfg
    app.state.store = store
    app.state.rate = rate
    app.state.semaphore = semaphore
    app.state.request_count = 0

    if cfg.cors_origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=cfg.cors_origins,
            allow_credentials=False,
            allow_methods=["*"],
            allow_headers=["*"],
        )
    else:
        app.add_middleware(
            CORSMiddleware,
            allow_origin_regex=_local_origin_regex(),
            allow_credentials=False,
            allow_methods=["*"],
            allow_headers=["*"],
        )

    @app.middleware("http")
    async def auth_and_rate_limit(request: Request, call_next):
        nonlocal request_count
        app.state.request_count += 1
        path = request.url.path

        if path.startswith("/api/") and path not in ("/api/health", "/api/metrics"):
            expected = cfg.api_key
            if expected:
                provided = request.headers.get("x-api-key")
                if not provided:
                    auth = request.headers.get("authorization", "")
                    if auth.startswith("Bearer "):
                        provided = auth[7:]
                if not provided:
                    provided = request.query_params.get("api_key")
                if not provided or not hmac.compare_digest(provided, expected):
                    return JSONResponse(
                        status_code=401,
                        content=error_envelope(
                            "UNAUTHORIZED",
                            "Unauthorized. Provide the X-API-Key header.",
                        ),
                        headers={"WWW-Authenticate": "Bearer"},
                    )

        if path != "/api/health" and request.method != "OPTIONS":
            if not await rate.allow():
                return JSONResponse(
                    status_code=429,
                    content=error_envelope(
                        "RATE_LIMITED", "Rate limit exceeded. Retry later.", retryable=True
                    ),
                    headers={"Retry-After": "1"},
                )
        return await call_next(request)

    @app.get("/api/health")
    async def health():
        ok = store.healthcheck()
        return JSONResponse(
            status_code=200 if ok else 503,
            content={
                "status": "ok" if ok else "error",
                "service": "tengu",
                "version": VERSION,
                "database": "ok" if ok else "error",
            },
        )

    @app.get("/api/metrics")
    async def metrics():
        body = (
            "# HELP tengu_requests_total Total HTTP requests\n"
            "# TYPE tengu_requests_total counter\n"
            f"tengu_requests_total {app.state.request_count}\n\n"
            "# HELP tengu_audits_total Total audits in store\n"
            "# TYPE tengu_audits_total gauge\n"
            f"tengu_audits_total {store.count()}\n\n"
            "# HELP tengu_database_backend Active persistence backend\n"
            "# TYPE tengu_database_backend gauge\n"
            f'tengu_database_backend{{backend="{store.kind}"}} 1\n'
        )
        return PlainTextResponse(body)

    # ---- Legacy /api/audits -------------------------------------------------

    @app.get("/api/audits")
    async def list_audits():
        return [record.to_legacy() for record in store.list()]

    @app.delete("/api/audits/clear")
    async def clear_audits():
        store.clear_all()
        return {"status": "cleared"}

    @app.get("/api/audits/export")
    async def export_audits():
        return {
            "records": [record.to_legacy() for record in store.list()],
            "exported_at": utc_now(),
        }

    @app.post("/api/audits/import")
    async def import_audits(payload: dict):
        records = payload.get("records") if isinstance(payload, dict) else None
        if not isinstance(records, list):
            raise HTTPException(status_code=422, detail="records must be a list")
        imported = 0
        for raw in records:
            try:
                record = AuditRecord.from_legacy(raw)
                if not record.id:
                    continue
                store.insert(record)
                imported += 1
            except (TypeError, ValueError):
                continue
        return {
            "status": "imported",
            "count": imported,
            "message": f"{imported} audit records imported",
        }

    @app.get("/api/audits/{audit_id}")
    async def get_audit(audit_id: str):
        try:
            uuid.UUID(audit_id)
        except ValueError:
            raise HTTPException(status_code=404)
        record = store.get(audit_id)
        if record is None:
            raise HTTPException(status_code=404)
        return record.to_legacy()

    @app.delete("/api/audits/{audit_id}")
    async def delete_audit(audit_id: str):
        if not _valid_uuid(audit_id):
            raise HTTPException(status_code=404)
        if not store.delete(audit_id):
            raise HTTPException(
                status_code=404,
                detail=error_envelope("NOT_FOUND", f"audit {audit_id} not found"),
            )
        return Response(status_code=204)

    # ---- /api/analyses (xwa-sdk contract) -----------------------------------

    @app.get("/api/analyses")
    async def list_analyses():
        return [analysis_view(record, VERSION) for record in store.list()]

    @app.get("/api/analyses/{audit_id}")
    async def get_analysis(audit_id: str):
        if not _valid_uuid(audit_id):
            raise HTTPException(status_code=404)
        record = store.get(audit_id)
        if record is None:
            raise HTTPException(status_code=404)
        return analysis_view(record, VERSION)

    @app.delete("/api/analyses/{audit_id}")
    async def delete_analysis(audit_id: str):
        if not _valid_uuid(audit_id):
            raise HTTPException(status_code=404)
        if not store.delete(audit_id):
            raise HTTPException(
                status_code=404,
                detail=error_envelope("NOT_FOUND", f"analysis {audit_id} not found"),
            )
        return Response(status_code=204)

    @app.get("/api/analyses/{audit_id}/export")
    async def export_analysis(audit_id: str, format: str = "json"):
        if not _valid_uuid(audit_id):
            raise HTTPException(status_code=404)
        record = store.get(audit_id)
        if record is None:
            raise HTTPException(status_code=404)
        fmt = (format or "json").lower()
        if fmt == "json":
            body = json.dumps(analysis_view(record, VERSION), ensure_ascii=False, indent=2)
            return Response(
                body,
                media_type="application/json",
                headers={
                    "Content-Disposition": f'attachment; filename="tengu-{record.id}.json"'
                },
            )
        if fmt == "csv":
            return Response(
                _analysis_csv(record),
                media_type="text/csv; charset=utf-8",
                headers={
                    "Content-Disposition": f'attachment; filename="tengu-{record.id}.csv"'
                },
            )
        raise HTTPException(
            status_code=422,
            detail=error_envelope(
                "INVALID_FORMAT", f"unsupported format '{fmt}' (use json or csv)"
            ),
        )

    # ---- WebSocket audit stream --------------------------------------------

    @app.websocket("/api/audit/live")
    async def audit_live(websocket: WebSocket):
        if cfg.api_key:
            provided = websocket.query_params.get("api_key") or websocket.headers.get("x-api-key")
            if not provided or not hmac.compare_digest(provided, cfg.api_key):
                await websocket.close(code=4401, reason="Unauthorized")
                return
        await websocket.accept()
        query = websocket.query_params
        options = AuditOptions(
            url=query.get("url", ""),
            mode=query.get("mode", ""),
            subdomains=_parse_bool(query.get("subdomains")),
            checks=query.get("checks", "performance,seo,accessibility,best_practices"),
            batch_url=query.get("batch_url", ""),
            batch_format=query.get("batch_format", ""),
        )
        audit_id, created_at = request_watermark()
        emitter = EventEmitter(websocket, audit_id)
        try:
            async with semaphore:
                await emitter.started(options.url, options.mode)
                try:
                    findings = await run_audit(options, emitter, cfg)
                    record = AuditRecord(
                        id=audit_id,
                        url=options.url,
                        status="COMPLETED",
                        findings=findings,
                        created_at=created_at,
                    )
                    store.insert(record)
                    await emitter.completed(findings)
                except Exception as exc:
                    await emitter.error(error_code(str(exc)), str(exc), False)
        except WebSocketDisconnect:
            pass
        finally:
            try:
                await websocket.close()
            except Exception:
                pass

    # ---- SPA fallback -------------------------------------------------------

    @app.get("/{path:path}", response_model=None)
    async def spa(path: str):
        static_dir = Path(cfg.static_dir).expanduser()
        index = static_dir / "index.html"
        target = static_dir / path if path else index
        try:
            target = target.resolve()
            if static_dir.resolve() not in target.parents and target != static_dir.resolve():
                raise ValueError
        except (OSError, ValueError):
            return PlainTextResponse("Not found", status_code=404)

        if target.is_file():
            media_type, _ = mimetypes.guess_type(str(target))
            return FileResponse(
                target,
                media_type=media_type or "application/octet-stream",
            )
        if path == "" and not index.is_file():
            return JSONResponse(
                {
                    "status": "ok",
                    "service": "tengu",
                    "version": VERSION,
                    "database": store.kind,
                }
            )
        if index.is_file():
            return FileResponse(index, media_type="text/html; charset=utf-8")
        return PlainTextResponse("Not found", status_code=404)

    return app


def _valid_uuid(value: str) -> bool:
    try:
        uuid.UUID(value)
        return True
    except ValueError:
        return False


def _csv_escape(value: str) -> str:
    if any(char in value for char in (",", '"', "\n", "\r")):
        return '"' + value.replace('"', '""') + '"'
    return value


def _analysis_csv(record: AuditRecord) -> str:
    output = io.StringIO()
    output.write(
        "analysis_id,tool,severity,category,check,title,description,target_url,evidence\n"
    )
    if not record.findings:
        output.write(f"{record.id},tengu,,,,,,,\n")
        return output.getvalue()
    for finding in record.findings:
        contract = finding_to_contract(finding)
        evidence = _dump_json(contract["evidence"]) if contract.get("evidence") else ""
        row = [
            record.id,
            "tengu",
            contract["severity"],
            contract.get("category", ""),
            contract.get("check", ""),
            contract.get("title", ""),
            contract.get("description", ""),
            contract.get("target_url", ""),
            evidence,
        ]
        output.write(",".join(_csv_escape(str(cell)) for cell in row) + "\n")
    return output.getvalue()
