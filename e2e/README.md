# Tengu — E2E browser smoke test

`browser_smoke.py` drives the Angular UI served by the Rust backend with
Playwright (headless Chromium). It verifies that WebSocket streamed data renders
**without user interaction** in the zoneless app.

## What it validates

1. **Audit live stream** — a single-page audit against the local fixture
   (`http://127.0.0.1:8107/`) is launched from the UI; `item_found` frames are
   received **before** `analysis_completed` on `/api/audit/live` and findings
   plus the severity summary render on their own after completion.
2. **No spurious WebSocket error** — the backend drops the socket after a
   terminal event (browser sees 1006); the UI must complete cleanly without
   `[!] WebSocket connection error`.
3. **Pretty HTML** — the source panel is available when the stream ends and the
   viewer renders the pretty-printed HTML.
4. **Exports** — CSV, JSON, Lighthouse JSON, HTML, Markdown and PDF all download
   from the UI; the PDF button resets after the async export.
5. **History** — lists the audits, renders the trend chart (≥ 2 audits), loads a
   detail into the audit view (`/audit?load=<id>`) and compares two audits.
6. **Console hygiene** — the run fails on any browser console `error` or
   `pageerror`.

The fixture lives in `e2e/fixture/` (missing metas/headings, images without
`alt`, blocking script, low-contrast text…) and is served automatically on port
8107 by the script.

## Requirements

- Node 24 (mise) to rebuild the UI.
- Python with Playwright + Chromium. The XWA venv already has it:
  `/home/x/Documents/xwebanalysis/samurai/backend/.venv/bin/python`.
- The backend running locally.

## Run

```bash
# 1. Build the UI that the Rust server serves (static/browser)
export PATH="$HOME/.local/share/mise/installs/node/24/bin:$PATH"
cd frontend && npm ci && npm run build

# 2. Start the backend (:8070)
cd .. && ./tengu.sh local

# 3. In another terminal: run the smoke test
/home/x/Documents/xwebanalysis/samurai/backend/.venv/bin/python \
    e2e/browser_smoke.py
```

Useful flags:

```bash
e2e/browser_smoke.py --headed          # visible Chromium
e2e/browser_smoke.py --no-fixture      # reuse an existing fixture server
e2e/browser_smoke.py --backend http://127.0.0.1:8070 --fixture-port 8107
```

The script exits `0` on success and `1` on the first failed expectation,
printing a textual `[PASS]/[FAIL]` report. It terminates the fixture server it
started; stop the backend with `Ctrl+C` when done.

## Notes

- The test creates two audits so the trend chart and the comparison need at
  least two completed records; repeated runs enrich the history further. Use
  `CLEAR ALL` in History if you want a clean trend.
- A fast fixture audit can complete in under a sampling tick; the live-stream
  assertion therefore also checks the WebSocket frame order (`item_found`
  before `analysis_completed`) instead of relying only on the UI snapshot.
