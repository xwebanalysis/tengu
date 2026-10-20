# Librerias Python (Dependencias del Backend)

El backend es una aplicacion Python 3.12+ gestionada con `uv`.

| Paquete | Funcion |
|---|---|
| `fastapi` | API REST, WebSocket y fallback SPA |
| `uvicorn[standard]` | Servidor ASGI (incluye `websockets` y `uvloop`) |
| `httpx` | Cliente HTTP asincrono con redirects, timeouts y reintentos |
| `beautifulsoup4` | Recorrido del DOM y selectores CSS |
| `lxml` | Parser HTML/XML usado por BeautifulSoup |
| `sqlite3` (stdlib) | Persistencia local, mismo esquema que el backend anterior |
| `pytest` + `pytest-asyncio` | Suite de tests (extra `test`) |

Playwright/Chromium no es necesario para el motor estatico actual. Es el
siguiente paso previsto para contraste, foco y axe-core con navegador real.

## Comandos

```bash
cd backend
uv sync --extra test
uv run pytest -q
uv run python -m tengu --port 8070
```
