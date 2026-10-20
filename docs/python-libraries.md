# Python Backend Libraries

The backend is a Python 3.12+ application managed with `uv`.

| Package | Role |
|---|---|
| `fastapi` | REST API, WebSocket endpoint and SPA fallback |
| `uvicorn[standard]` | ASGI server (includes `websockets` and `uvloop`) |
| `httpx` | Async HTTP client with redirects, timeouts and retries |
| `beautifulsoup4` | HTML traversal and CSS selector helpers |
| `lxml` | Fast HTML/XML parser used by BeautifulSoup |
| `sqlite3` (stdlib) | Local-first persistence, same schema as the previous backend |
| `pytest` + `pytest-asyncio` | Test suite (extra `test`) |

Playwright/Chromium is not required by the current static engine. It is the
planned next step for browser-based contrast, focus and axe-core checks.

## Commands

```bash
cd backend
uv sync --extra test
uv run pytest -q
uv run python -m tengu --port 8070
```
