# Tengu Manual

## Deployment

### Local (default, SQLite)

```bash
./tengu.sh            # ./tengu.sh local
```

Starts the native Axum server on `http://localhost:8070` using SQLite at
`<repo>/tengu.db` (override with `TENGU_DB_PATH`). If a prebuilt frontend exists
(`static/browser/` or `frontend/dist/tengu/browser/`), it is served at `/`.

### Cargo directly

```bash
TENGU_DB_PATH=/tmp/tengu.db PORT=8070 cargo run --release
```

Requires Rust 1.86+ (edition 2021). `build.rs` does **not** compile the
frontend: it only declares `rerun-if-changed` paths so Cargo rebuilds when
frontend metadata changes. To build the UI use `./tengu.sh build` or, inside
`frontend/`, `npm ci && npm run build` with Node 24 (Angular 22 + Nothing
Design; output goes to `../static`). `npm test` runs the Vitest suite.

### Docker (persistent SQLite volume)

```bash
docker compose up -d --build
```

Web UI and API at `http://localhost:8070`. The database is persisted in the
`tengu_data` volume at `/data/tengu.db`.

### Launch Script

```bash
./tengu.sh                        # local (default): SQLite native, :8070
./tengu.sh local                  # same as above
./tengu.sh docker                 # docker compose
./tengu.sh docker --rm            # ephemeral container
./tengu.sh export [file]          # start + export audits to ./exports/
./tengu.sh import <file>          # start + import audits from file
./tengu.sh build                  # build frontend only
./tengu.sh clean                  # delegate to ./clean.sh
./tengu.sh -b                     # force frontend rebuild before starting
```

## Environment Variables

| Variable | Default | Description |
|---|---|---|
| `PORT` | `8070` | HTTP listen port |
| `STATIC_DIR` | `static/browser` | SPA assets directory |
| `TENGU_DB_PATH` | `tengu.db` (`/data/tengu.db` in Docker) | SQLite database file |
| `DATABASE_URL` | — | PostgreSQL DSN (requires `--features pg`) |
| `TENGU_MAX_HISTORY` | `100` | Maximum persisted audits |
| `TENGU_API_KEY` | — | Optional API key (`X-API-Key` header) |
| `TENGU_HTTP_TIMEOUT` | `30` | HTTP client timeout (s) |
| `TENGU_HTTP_MAX_REDIRECTS` | `10` | Redirect limit |
| `TENGU_HTTP_RETRY` | `2` | Retry count (backoff + jitter) |
| `TENGU_USER_AGENT` | `Tengu/<version> (+repo)` | Crawler user agent |
| `TENGU_RATE_LIMIT_PER_MINUTE` | `120` | REST/WS token bucket |
| `TENGU_RATE_LIMIT_BURST` | `30` | Token bucket burst |
| `TENGU_MAX_CONCURRENT` | `3` | Concurrent audits |
| `TENGU_MAX_PAGES` | `50` | Max pages per full-site crawl |
| `TENGU_CRAWL_DEPTH` | `2` | Crawl depth |
| `TENGU_CRAWL_DELAY_MIN_MS` / `_MAX_MS` | `200` / `800` | Jittered delay |
| `TENGU_ROBOTS_TXT` | `1` | Respect robots.txt (`0` disables) |
| `XWA_CORS_ORIGINS` | localhost/LAN | Allowed CORS origins |
| `RUST_LOG` | `tengu=info,tower_http=info` | Logging verbosity |

## Usage

### Single URL Audit

1. Enter a URL in the input field.
2. Select the audit categories (Performance, SEO, Accessibility, Best Practices).
3. Click START AUDIT.
4. Events stream in real time over the WebSocket (`analysis_started`,
   `analysis_progress`, `item_found`, `log`, `analysis_completed` /
   `analysis_error`) and are rendered in the terminal, findings list and HTML
   source viewer.

### Full Site Audit

1. Toggle FULL SITE mode.
2. Optionally enable INCLUDE SUBDOMAINS.
3. Enter the starting URL.
4. Tengu checks `robots.txt`, crawls up to `TENGU_MAX_PAGES` pages to
   `TENGU_CRAWL_DEPTH` levels with a jittered 200–800 ms delay, and audits each.

### Understanding Results

Each finding displays severity in the unified xwa-sdk scale (`pass`, `info`,
`low`, `medium`, `high`, `critical`), check name, title, description, HTML
snippet and source line. The backend maps the internal Tengu severities:
`Pass → pass`, `Info → info`, `Warning → medium`, `Error → high`.

### HTML Source Viewer

After an audit completes, click VIEW HTML to see the pretty-printed source.
The source also travels as the payload of a `log` event.

### Export

Client-side exports (CSV/JSON/PDF/HTML/Markdown) are generated in the browser.
Server-side exports:

- `GET /api/analyses/{id}/export?format=json|csv`
- `GET /api/audits/export` (all records, legacy shape)

## API Endpoints

| Method | Path | Description |
|---|---|---|
| `GET` | `/api/health` | JSON health (`status`, `service`, `version`, `database`) |
| `GET` | `/api/metrics` | Prometheus text metrics |
| `GET` | `/api/audit/live` | WebSocket streaming xwa-sdk `Event` |
| `GET` | `/api/audits` | List past audits |
| `GET` | `/api/audits/{id}` | Get audit details |
| `DELETE` | `/api/audits/{id}` | Delete audit |
| `GET` | `/api/audits/export` | Export all audits as JSON |
| `POST` | `/api/audits/import` | Import audits from JSON |
| `GET` | `/api/analyses` | List analyses (xwa-sdk `Analysis`) |
| `GET` | `/api/analyses/{id}` | Analysis + findings |
| `DELETE` | `/api/analyses/{id}` | Delete analysis |
| `GET` | `/api/analyses/{id}/export?format=json\|csv` | Download analysis |

## Persistence

SQLite is the default store:

- PRAGMAs: `journal_mode=WAL`, `busy_timeout=5000`, `foreign_keys=ON`.
- Schema: `audits(id TEXT PRIMARY KEY, url, status, findings TEXT DEFAULT '[]', created_at)` plus `schema_meta(version)`.
- Writes are write-through on every insert/delete/clear; records are loaded on startup.
- `TENGU_MAX_HISTORY` prunes the oldest rows beyond the retention limit.

PostgreSQL remains optional (`cargo build --release --features pg` +
`DATABASE_URL`); it now uses the same write-through interface (no 5 s sync loop).

## Security

- Optional `TENGU_API_KEY` via `X-API-Key` or `Authorization: Bearer`
  (query-string `api_key` remains accepted for compatibility).
- In-process token bucket on every `/api/*` route except `/api/health`
  (default 120 req/min, burst 30), returning HTTP 429 with the error envelope.
- CORS restricted to localhost/LAN by default, or to `XWA_CORS_ORIGINS`,
  always with `allow_credentials=false`.
- Respectful crawling: robots.txt, jittered delays, page/depth caps, retries
  with backoff, timeouts, bounded concurrency.

## Troubleshooting

### WebSocket connection fails
Ensure the port is reachable and no firewall blocks WebSocket upgrades. Check
`RUST_LOG=debug` for request details.

### Audit returns no findings
The audit parses the HTML after pretty-printing. If the page is empty, behind a
login wall, or blocks bots, results may be empty. Try a publicly accessible page.

### Build fails
- Rust: ensure 1.86+ with `rustup update`.
- Frontend: `./tengu.sh build` (uses Node 24 from mise when available).
- Clean build: `./clean.sh` then retry (it also removes `tengu.db*`).
