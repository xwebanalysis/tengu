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
    handler = functools.partial(QuietHandler, directory=str(FIXTURE_DIR))
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{server.server_address[1]}/"
    server.shutdown()
    thread.join(timeout=2)


def test_api_key_protects_audits():
    app = create_app(Config(db_path=":memory:", api_key="secret"))
    with TestClient(app) as client:
        assert client.get("/api/health").status_code == 200
        assert client.get("/api/audits").status_code == 401
        assert client.get("/api/audits", headers={"X-API-Key": "secret"}).status_code == 200
        assert client.get("/api/audits?api_key=secret").status_code == 200


def test_rate_limit_returns_429():
    app = create_app(Config(
        db_path=":memory:",
        rate_limit_per_minute=1,
        rate_limit_burst=1,
    ))
    with TestClient(app) as client:
        client.get("/api/health")
        first = client.get("/api/audits")
        second = client.get("/api/audits")
        assert first.status_code == 200
        assert second.status_code == 429
        assert second.json()["error"]["code"] == "RATE_LIMITED"


def test_static_spa_fallback(tmp_path):
    static = tmp_path / "static" / "browser"
    static.mkdir(parents=True)
    (static / "index.html").write_text("<html><body>tengu-ui</body></html>")
    (static / "main.js").write_text("console.log('ok')")
    app = create_app(Config(db_path=":memory:", static_dir=str(static)))
    with TestClient(app) as client:
        assert "tengu-ui" in client.get("/").text
        assert "tengu-ui" in client.get("/history").text
        assert client.get("/main.js").text == "console.log('ok')"


def test_full_site_crawl(fixture_url):
    app = create_app(Config(
        db_path=":memory:",
        crawl_delay_min_ms=0,
        crawl_delay_max_ms=0,
        max_crawl_pages=5,
        crawl_depth=1,
    ))
    with TestClient(app) as client:
        with client.websocket_connect(
            f"/api/audit/live?url={fixture_url}&mode=fullsite&checks=accessibility"
        ) as ws:
            events = []
            while True:
                event = ws.receive_json()
                events.append(event)
                if event["type"] in ("analysis_completed", "analysis_error"):
                    break
        assert events[-1]["type"] == "analysis_completed"
        pages = [
            event["payload"]["message"]
            for event in events
            if event["type"] == "analysis_progress"
            and event["payload"].get("message", "").startswith("[PAGE] ")
        ]
        assert pages, "expected crawled page announcements"
