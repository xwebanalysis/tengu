from __future__ import annotations

import functools
import threading
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from tengu.api import create_app
from tengu.config import Config

FIXTURE_DIR = Path(__file__).resolve().parents[2] / "e2e" / "fixture"


class QuietHandler(SimpleHTTPRequestHandler):
    def log_message(self, *_args):
        pass


@pytest.fixture(scope="session")
def fixture_url():
    if not FIXTURE_DIR.is_dir():
        pytest.skip("e2e fixture not available")
    handler = functools.partial(QuietHandler, directory=str(FIXTURE_DIR))
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{server.server_address[1]}/"
    server.shutdown()
    thread.join(timeout=2)


@pytest.fixture()
def app():
    return create_app(Config(
        db_path=":memory:",
        crawl_delay_min_ms=0,
        crawl_delay_max_ms=0,
        max_crawl_pages=5,
    ))


def test_health_and_metrics(app):
    with TestClient(app) as client:
        health = client.get("/api/health")
        assert health.status_code == 200
        assert health.json()["service"] == "tengu"
        metrics = client.get("/api/metrics")
        assert "tengu_requests_total" in metrics.text
        assert 'backend="sqlite"' in metrics.text


def test_ws_audit_persists_and_exports(app, fixture_url):
    with TestClient(app) as client:
        with client.websocket_connect(
            f"/api/audit/live?url={fixture_url}&mode=single&checks=accessibility"
        ) as ws:
            events = []
            while True:
                event = ws.receive_json()
                events.append(event)
                if event["type"] in ("analysis_completed", "analysis_error"):
                    break
        assert events[0]["type"] == "analysis_started"
        assert events[-1]["type"] == "analysis_completed"
        assert any(event["type"] == "item_found" for event in events)
        assert events[-1]["payload"]["summary"]["total_items"] > 0

        analyses = client.get("/api/analyses").json()
        assert len(analyses) == 1
        audit_id = analyses[0]["id"]
        detail = client.get(f"/api/analyses/{audit_id}")
        assert detail.status_code == 200
        assert detail.json()["findings"]

        csv_response = client.get(f"/api/analyses/{audit_id}/export?format=csv")
        assert csv_response.status_code == 200
        assert csv_response.text.startswith("analysis_id,tool,severity,category,check")


def test_legacy_audits_and_import(app):
    with TestClient(app) as client:
        record = {
            "id": "00000000-0000-0000-0000-000000000001",
            "url": "https://example.com/",
            "status": "COMPLETED",
            "findings": [],
            "created_at": "2026-01-01T00:00:00+00:00",
        }
        imported = client.post("/api/audits/import", json={"records": [record]})
        assert imported.status_code == 200
        assert imported.json()["count"] == 1
        listed = client.get("/api/audits").json()
        assert listed[0]["id"] == record["id"]
        assert client.delete(f"/api/audits/{record['id']}").status_code == 204
        assert client.get("/api/audits").json() == []
