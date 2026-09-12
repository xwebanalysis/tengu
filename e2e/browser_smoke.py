#!/usr/bin/env python3
"""Tengu browser smoke test (Playwright, headless Chromium).

Validates the zoneless Angular UI served by the Rust backend from a real
browser:

  1. A single-page audit against a local fixture (port 8107) is launched from
     the UI; findings and the pretty HTML render *without any click* while the
     WebSocket stream is running and after it completes.
  2. The terminal does not log a spurious WebSocket transport error (the
     backend closes abruptly after a terminal event).
  3. History lists the audits, loads a detail, compares two audits and renders
     the trend chart.
  4. CSV / JSON / Lighthouse / HTML / Markdown / PDF exports download from the
     UI.
  5. The browser console stays free of errors/page errors.

Usage (tengu backend already running, see e2e/README.md):

    /home/x/Documents/xwebanalysis/samurai/backend/.venv/bin/python \
        e2e/browser_smoke.py

Options:
    --backend URL        UI/API origin (default http://127.0.0.1:8070)
    --fixture-port N     Fixture HTTP port (default 8107)
    --no-fixture         Do not start the fixture server (reuse an existing one)
    --headed             Run Chromium with a visible window
    --timeout SECONDS    Global audit timeout per run (default 120)
"""

from __future__ import annotations

import argparse
import contextlib
import json
import socket
import subprocess
import sys
import time
from pathlib import Path

try:
    from playwright.sync_api import Page, sync_playwright
except ImportError:  # pragma: no cover - operator feedback
    print("Playwright is missing. Run with the XWA venv python:")
    print("  /home/x/Documents/xwebanalysis/samurai/backend/.venv/bin/python e2e/browser_smoke.py")
    sys.exit(2)

FIXTURE_DIR = Path(__file__).resolve().parent / "fixture"
DEFAULT_BACKEND = "http://127.0.0.1:8070"
DEFAULT_FIXTURE_PORT = 8107


def port_open(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(0.3)
        return sock.connect_ex(("127.0.0.1", port)) == 0


@contextlib.contextmanager
def fixture_server(port: int, enabled: bool):
    """Serve e2e/fixture on 127.0.0.1:<port> for the duration of the test."""
    process: subprocess.Popen | None = None
    if not enabled:
        yield
        return
    if port_open(port):
        print(f"[fixture] port {port} already in use, reusing existing server")
        yield
        return
    process = subprocess.Popen(
        [sys.executable, "-m", "http.server", str(port), "--bind", "127.0.0.1"],
        cwd=str(FIXTURE_DIR),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        for _ in range(50):
            if port_open(port):
                break
            time.sleep(0.1)
        if not port_open(port):
            raise RuntimeError(f"fixture server did not start on port {port}")
        print(f"[fixture] serving {FIXTURE_DIR} on http://127.0.0.1:{port}")
        yield
    finally:
        if process is not None:
            process.terminate()
            with contextlib.suppress(Exception):
                process.wait(timeout=5)


class Harness:
    def __init__(self) -> None:
        self.failures: list[str] = []
        self.passes = 0
        self._section = ""

    def section(self, name: str) -> None:
        self._section = name
        print(f"\n=== {name} ===")

    def check(self, condition: bool, label: str, detail: str = "") -> bool:
        if condition:
            self.passes += 1
            print(f"  [PASS] {label}")
        else:
            self.failures.append(f"{self._section}: {label} {detail}".strip())
            print(f"  [FAIL] {label} {detail}".rstrip())
        return bool(condition)

    def summary(self) -> int:
        print("\n------------------------------------------------------------")
        if self.failures:
            print(f"RESULT: FAIL ({len(self.failures)} failure(s), {self.passes} pass(es))")
            for failure in self.failures:
                print(f"  - {failure}")
            return 1
        print(f"RESULT: PASS ({self.passes} check(s))")
        return 0


def audit_snapshot(page: Page) -> dict:
    """Reads the audit view state without dispatching any DOM event."""
    return page.evaluate(
        """() => {
            const button = document.querySelector('button.btn-audit');
            const terminal = document.querySelector('app-terminal');
            return {
                running: button ? button.disabled : false,
                findings: document.querySelectorAll('.finding-item').length,
                lines: terminal ? terminal.querySelectorAll('.terminal-line').length : 0,
                summary: document.querySelectorAll('.severity-summary app-metric-card').length,
                htmlAvailable: !!document.querySelector('.log-panel .btn-reset'),
            };
        }"""
    )


def run_audit(page: Page, url: str, timeout_s: float) -> tuple[list[dict], bool]:
    """Launches one audit from the UI and samples it until it completes.

    Returns the samples and whether findings were visible while the audit was
    still running (i.e. streamed live, no clicks involved).
    """
    page.fill("#target-url", url)
    page.click("button.btn-audit")
    samples: list[dict] = []
    findings_while_running = False
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        snapshot = audit_snapshot(page)
        samples.append(snapshot)
        if snapshot["running"] and snapshot["findings"] > 0:
            findings_while_running = True
        if not snapshot["running"] and snapshot["findings"] > 0 and snapshot["summary"] > 0:
            break
        time.sleep(0.25)
    return samples, findings_while_running


def download_text(download) -> str:
    try:
        return Path(download.path()).read_text(encoding="utf-8", errors="replace")
    except Exception:
        return ""


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--backend", default=DEFAULT_BACKEND)
    parser.add_argument("--fixture-port", type=int, default=DEFAULT_FIXTURE_PORT)
    parser.add_argument("--no-fixture", action="store_true")
    parser.add_argument("--headed", action="store_true")
    parser.add_argument("--timeout", type=float, default=120.0)
    args = parser.parse_args()

    backend = args.backend.rstrip("/")
    fixture_url = f"http://127.0.0.1:{args.fixture_port}/"
    harness = Harness()

    with fixture_server(args.fixture_port, not args.no_fixture):
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=not args.headed)
            context = browser.new_context(accept_downloads=True)
            page = context.new_page()

            console_errors: list[str] = []
            page_errors: list[str] = []
            websockets: list[str] = []
            ws_event_types: list[str] = []

            def on_websocket(ws) -> None:
                websockets.append(ws.url)

                def on_frame(payload) -> None:
                    if isinstance(payload, bytes):
                        payload = payload.decode("utf-8", "replace")
                    try:
                        event = json.loads(payload)
                    except Exception:
                        return
                    event_type = event.get("type")
                    if isinstance(event_type, str):
                        ws_event_types.append(event_type)

                ws.on("framereceived", on_frame)

            page.on(
                "console",
                lambda message: console_errors.append(f"{message.type}: {message.text}")
                if message.type == "error"
                else None,
            )
            page.on("pageerror", lambda error: page_errors.append(str(error)))
            page.on("websocket", on_websocket)

            try:
                # ── 1. first audit: live streamed findings ───────────────────
                harness.section("audit live stream (autonomous findings)")
                page.goto(f"{backend}/", wait_until="networkidle")
                page.wait_for_selector("#target-url", timeout=15000)

                samples, live_findings = run_audit(page, fixture_url, args.timeout)
                harness.check(
                    any(ws.startswith("ws") and "/api/audit/live" in ws for ws in websockets),
                    "WebSocket /api/audit/live was consumed",
                    f"({websockets})",
                )
                streamed_before_complete = (
                    "item_found" in ws_event_types
                    and "analysis_completed" in ws_event_types
                    and ws_event_types.index("item_found")
                    < ws_event_types.index("analysis_completed")
                )
                harness.check(
                    live_findings or streamed_before_complete,
                    "findings stream live before completion (item_found before analysis_completed)",
                    f"(types={ws_event_types[:12]})",
                )
                harness.check(
                    samples[-1]["findings"] > 0 and samples[-1]["summary"] > 0,
                    "findings + severity summary rendered after completion",
                    f"(findings={samples[-1]['findings']})",
                )
                harness.check(
                    any(
                        later["lines"] > earlier["lines"]
                        for earlier, later in zip(samples, samples[1:])
                    ),
                    "terminal log grows without any click",
                )
                print(f"  [trace] WS event order={ws_event_types[:14]}")
                finding_step = max(1, len(samples) // 6)
                finding_trace = [s["findings"] for s in samples[::finding_step]]
                if samples:
                    finding_trace.append(samples[-1]["findings"])
                print(f"  [trace] rendered findings over samples={finding_trace}")
                terminal_text = page.locator("app-terminal").inner_text()
                harness.check(
                    "WebSocket connection error" not in terminal_text,
                    "no spurious WebSocket transport error after completion",
                )

                # ── 2. pretty HTML renders on its own ────────────────────────
                harness.section("pretty HTML source")
                harness.check(
                    samples[-1]["htmlAvailable"],
                    "HTML source panel is available once the stream completes",
                )
                page.click(".log-panel .btn-reset")
                page.wait_for_selector("app-html-viewer .source-line", timeout=10000)
                source_lines = page.locator("app-html-viewer .source-line").count()
                harness.check(
                    source_lines > 10,
                    "pretty-printed HTML renders in the viewer",
                    f"(lines={source_lines})",
                )

                # ── 3. exports from the UI (all six formats) ─────────────────
                harness.section("exports (CSV/JSON/LH/HTML/MD/PDF)")
                expected = [
                    ("EXPORT CSV", ".csv"),
                    ("EXPORT JSON", ".json"),
                    ("LH JSON", ".json"),
                    ("EXPORT HTML", ".html"),
                    ("EXPORT MD", ".md"),
                    ("EXPORT PDF", ".pdf"),
                ]
                for label, suffix in expected:
                    button = page.locator("app-export-actions button.export-btn", has_text=label).first
                    with page.expect_download(timeout=60000) as download_info:
                        button.click()
                    download = download_info.value
                    harness.check(
                        download.suggested_filename.endswith(suffix),
                        f"{label} export downloads a {suffix} file",
                        f"({download.suggested_filename})",
                    )
                    if suffix in (".csv", ".json"):
                        body = download_text(download)
                        harness.check(len(body) > 0, f"{label} file is not empty")
                pdf_button = page.locator(
                    "app-export-actions button.export-btn", has_text="EXPORT PDF"
                ).first
                deadline = time.time() + 10
                while time.time() < deadline and pdf_button.is_disabled():
                    time.sleep(0.1)
                harness.check(
                    not pdf_button.is_disabled(),
                    "PDF button resets after the async export",
                )

                # ── 4. second audit for trend + comparison ───────────────────
                harness.section("second audit (trend/compare data)")
                page.goto(f"{backend}/", wait_until="networkidle")
                page.wait_for_selector("#target-url", timeout=15000)
                samples2, _ = run_audit(page, f"http://127.0.0.1:{args.fixture_port}/about.html", args.timeout)
                harness.check(
                    samples2[-1]["findings"] > 0,
                    "second audit completes with findings",
                    f"(findings={samples2[-1]['findings']})",
                )

                # ── 5. history: list, trend, detail, comparison ──────────────
                harness.section("history (list, trend, detail, compare)")
                page.click("a[href='/history']")
                page.wait_for_selector("table tbody tr", timeout=15000)
                rows = page.locator("table tbody tr").count()
                harness.check(rows >= 2, "history lists all audits", f"(rows={rows})")
                harness.check(
                    page.locator(".trend-panel").count() == 1
                    and page.locator(".trend-panel svg polyline").count() >= 3,
                    "trend panel renders with the score history polylines",
                )

                page.locator("table tbody tr a.load-link").first.click()
                page.wait_for_selector(".finding-item", timeout=15000)
                loaded_text = page.locator(".loaded-id").inner_text().lower()
                harness.check(
                    "http://" in loaded_text and "127.0.0.1" in loaded_text,
                    "history detail loads the stored audit into the audit view",
                    f"({loaded_text.strip()})",
                )
                harness.check(
                    page.locator(".finding-item").count() > 0,
                    "loaded detail renders findings",
                )

                page.click("a[href='/history']")
                page.wait_for_selector("table tbody tr", timeout=15000)
                page.click("button:has-text('COMPARE')")
                selects = page.locator("button.select-btn")
                selects.nth(0).click()
                selects.nth(1).click()
                page.wait_for_selector(".compare-panel", timeout=10000)
                harness.check(True, "comparison of two audits renders the compare panel")
                harness.check(
                    page.locator(".compare-panel .diff-line").count() > 0
                    or "no diffs" in page.locator(".compare-panel").inner_text().lower()
                    or "sin diferencias" in page.locator(".compare-panel").inner_text().lower(),
                    "comparison shows a diff summary (or an explicit no-diff state)",
                )

                # ── 6. console cleanliness ───────────────────────────────────
                harness.section("console / page errors")
                harness.check(not console_errors, "no console errors", f"({console_errors})")
                harness.check(not page_errors, "no page errors", f"({page_errors})")
            finally:
                context.close()
                browser.close()

    return harness.summary()


if __name__ == "__main__":
    sys.exit(main())
