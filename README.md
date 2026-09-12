<h1 align="center">Tengu</h1>

<div align="center">
<p><em>Web quality auditor — Performance, SEO, Accessibility, Best Practices</em></p>
</div>

<div align="center">
<a href="README.md">English</a> | <a href="docs/esp/README.md">Español</a>
</div>

<p><em><a href="https://github.com/xwebanalysis/tengu">Tengu</a></em> : <em><a href="https://github.com/xwebanalysis/meta">XWA</a> <strong>submodule focused</strong> on web quality auditing</em></p>

<hr>

## Overview

Tengu is a web quality auditor that evaluates web applications across four dimensions:

| Category | Scope |
|---|---|
| **Performance** | Page weight, Core Web Vitals (LCP, CLS, INP), resource waterfall, image optimization, font loading, cache policy, compression, third-party impact |
| **SEO** | Title tags, meta descriptions, heading hierarchy, canonical URLs, Open Graph, Twitter Cards, JSON-LD, sitemaps, robots.txt, hreflang, redirect chains, broken links |
| **Accessibility** | Alt text, heading structure, ARIA attributes, landmarks, color contrast (WCAG AA/AAA), keyboard navigation, form labels, link text, tables, iframes, viewport configuration |
| **Best Practices** | HTTPS enforcement, security headers (HSTS, CSP, XFO, etc.), cookie audit, GDPR banner detection, doctype validation, deprecated HTML, mixed content, SRI, console errors |

**Local-first**: SQLite persistence by default, no external services required. PostgreSQL is available behind an optional Cargo feature.

## Quick Start

### Native (no Docker) — recommended

```bash
./tengu.sh            # same as: ./tengu.sh local
```

Starts the Axum backend on `http://localhost:8070` with a SQLite database at
`<repo>/tengu.db` and serves the prebuilt Angular frontend when present
(`static/browser/` or `frontend/dist/`).

### Cargo directly

```bash
TENGU_DB_PATH=/tmp/tengu.db PORT=8070 cargo run --release
```

### Frontend (development)

The SPA is Angular 22 (standalone, zoneless, TypeScript 6, `@angular/build`,
Vitest). Node 24 is required.

```bash
export PATH="$HOME/.local/share/mise/installs/node/24/bin:$PATH"
cd frontend
npm ci                        # reproducible install from package-lock.json
npm test                      # Vitest unit tests (api, WS Event parsing, severity, exports)
npm run build                 # production build -> ../static (outputHashing: none)
npm start                     # dev server on :4270, talks to :8070
```

The production build is written to `<repo>/static/browser` and served by the
Axum fallback (`STATIC_DIR`). `outputHashing: none` keeps `main.js`/`styles.css`
stable so Rust can serve them without a manifest. The backend `build.rs` never
compiles the frontend; use `./tengu.sh build` or the npm commands above.

### Docker Compose

```bash
docker compose up -d --build
```

Web UI and API: `http://localhost:8070`. The SQLite database lives in the
`tengu_data` volume at `/data/tengu.db`.

## Launch Script

```bash
./tengu.sh                        # local (default): SQLite native, :8070
./tengu.sh local                  # explicit local mode
./tengu.sh docker                 # docker compose (persistent volume)
./tengu.sh docker --rm            # ephemeral container
./tengu.sh build                  # build frontend only
./tengu.sh export [file]          # start + export audits to ./exports/
./tengu.sh import <file>          # start + import audits from file
./tengu.sh clean                  # delegate to ./clean.sh
./tengu.sh -b                     # force frontend rebuild before starting
```

The script prefers Node 24 from mise (`~/.local/share/mise/installs/node/24/bin`)
when building the frontend. It runs `npm ci` (falling back to `npm install` only
if the lockfile is missing) when `frontend/node_modules` is absent.

## Environment Variables

| Variable | Default | Description |
|---|---|---|
| `PORT` | `8070` | HTTP listen port (XWA standard) |
| `STATIC_DIR` | `static/browser` | Directory served by the SPA fallback |
| `TENGU_DB_PATH` | `tengu.db` (`/data/tengu.db` in Docker) | SQLite database file |
| `DATABASE_URL` | — | PostgreSQL DSN (requires `--features pg`) |
| `TENGU_MAX_HISTORY` | `100` | Maximum persisted audits (retention) |
| `TENGU_API_KEY` | — | Optional API key (`X-API-Key` or `Authorization: Bearer`) |
| `TENGU_HTTP_TIMEOUT` | `30` | HTTP client timeout (seconds) |
| `TENGU_HTTP_MAX_REDIRECTS` | `10` | Redirect limit |
| `TENGU_HTTP_RETRY` | `2` | Retries with exponential backoff + jitter |
| `TENGU_USER_AGENT` | `Tengu/0.2.0 (+https://github.com/xwebanalysis/tengu)` | Crawler user agent |
| `TENGU_RATE_LIMIT_PER_MINUTE` | `120` | REST + WS token bucket rate |
| `TENGU_RATE_LIMIT_BURST` | `30` | Token bucket burst |
| `TENGU_MAX_CONCURRENT` | `3` | Concurrent audits |
| `TENGU_MAX_PAGES` | `50` | Maximum pages per full-site crawl |
| `TENGU_CRAWL_DEPTH` | `2` | Crawl depth from the entry URL |
| `TENGU_CRAWL_DELAY_MIN_MS` / `_MAX_MS` | `200` / `800` | Delay with jitter between crawl requests |
| `TENGU_ROBOTS_TXT` | `1` | Respect `robots.txt` during crawls (`0` disables) |
| `XWA_CORS_ORIGINS` | localhost/LAN | Comma-separated allowed origins (credentials always disabled) |
| `RUST_LOG` | `tengu=info,tower_http=info` | Logging verbosity |

## API Endpoints

| Method | Path | Description |
|---|---|---|
| `GET` | `/api/health` | JSON health: `{"status","service","version","database"}` |
| `GET` | `/api/metrics` | Prometheus text metrics |
| `GET` | `/api/audit/live` | WebSocket streaming xwa-sdk `Event` envelopes |
| `GET` | `/api/audits` | List persisted audits (legacy shape) |
| `GET` | `/api/audits/{id}` | Get an audit (legacy shape) |
| `DELETE` | `/api/audits/{id}` | Delete an audit |
| `DELETE` | `/api/audits/clear` | Clear all audits |
| `GET` | `/api/audits/export` | Export all audits as JSON |
| `POST` | `/api/audits/import` | Import audits from JSON |
| `GET` | `/api/analyses` | List analyses as xwa-sdk `Analysis` |
| `GET` | `/api/analyses/{id}` | Analysis + findings (xwa-sdk contract) |
| `DELETE` | `/api/analyses/{id}` | Delete an analysis |
| `GET` | `/api/analyses/{id}/export?format=json\|csv` | Download analysis (`Content-Disposition`) |

## WebSocket Protocol (xwa-sdk `Event`)

`GET /api/audit/live?url=<target>&mode=<single|fullsite|batch>&checks=...`

Every frame is a JSON `Event` from xwa-sdk 0.2.0:

```json
{
  "seq": 3,
  "type": "item_found",
  "tool": "tengu",
  "analysis_id": "df2c…",
  "ts": "2026-09-12T10:00:00Z",
  "payload": {
    "tool": "tengu",
    "severity": "medium",
    "title": "Missing alt attribute",
    "description": "…",
    "category": "accessibility",
    "check": "alt_text",
    "target_url": "https://example.com/",
    "evidence": {"snippet": "<img src=\"…\">"}
  }
}
```

Event flow: `analysis_started` → `analysis_progress`* → `item_found`* →
`log` (pretty-printed HTML source) → `analysis_completed` (with `summary`) or
`analysis_error` (with the xwa-sdk error envelope).

Severity mapping: `Pass → pass`, `Info → info`, `Warning → medium`,
`Error → high`. The Angular client parses every frame with `parseEvent()`
(`frontend/src/app/core/events.ts`) and rebuilds exactly what the legacy text
protocol provided: meta/log lines in the terminal, crawled pages from
`[PAGE] <url>` progress messages, findings from `item_found`, the pretty HTML
from the `log`/`html_source` payload (`data.html`), and completion/error state
from `analysis_completed`/`analysis_error`.

## Respectful Crawling

Full-site mode honors `robots.txt` by default, paces requests with a random
200–800 ms delay, caps the crawl with `TENGU_MAX_PAGES`/`TENGU_CRAWL_DEPTH`,
and retries transient failures with exponential backoff + jitter.

## Project Structure

```
tengu/
├── src/
│   ├── main.rs              # Axum server, middleware, CORS, rate limit
│   ├── contracts.rs         # xwa-sdk 0.2.0 contract models
│   ├── config.rs            # Environment configuration
│   ├── api/routes.rs        # REST API + WebSocket event streaming
│   ├── auditor/             # Performance, SEO, a11y, best-practices engines
│   └── storage/mod.rs       # Memory / SQLite / PostgreSQL stores
├── frontend/                # Angular 22 SPA (zoneless, Nothing Design, Vitest)
│   ├── src/app/core/        # api, ws/event parsing, theme, i18n, exports
│   ├── src/app/shared/      # terminal, html-viewer, metric-card, tags, exports
│   └── src/app/features/    # audit, history
├── docs/                    # Technical documentation
├── Dockerfile               # Multi-stage Rust + Angular build
├── docker-compose.yml       # Single service with persistent SQLite volume
├── tengu.sh                 # Local-first launch script
└── clean.sh                 # Local + Docker cleanup (removes tengu.db*)
```

## Backend Dependencies

Axum 0.8, Tokio 1.53, tower-http 0.7, reqwest 0.13 (rustls), scraper 0.27,
sqlx 0.9 (SQLite by default; PostgreSQL behind `--features pg`), serde,
tracing, dashmap, thiserror. See `docs/rust-libraries.md`.

## Related Documents

| Document | Description |
|---|---|
| [docs/manual.md](docs/manual.md) | Deployment and usage manual |
| [docs/ui-architecture.md](docs/ui-architecture.md) | Frontend architecture overview |
| [docs/rust-libraries.md](docs/rust-libraries.md) | Rust backend dependency inventory |
| [ROADMAP.md](ROADMAP.md) | Development phases and milestones |
| [CHANGELOG.md](CHANGELOG.md) | Release history and version log |
| [SECURITY.md](SECURITY.md) | Security policy and reporting |

<hr>

<div id="x" align="center">
<h2>X</h2>

<a href="https://dev.xscriptor.com">
  <img src="https://xscriptor.github.io/icons/icons/code/product-design/xsvg/verified-filled.svg" width="24" alt="X Web" />
</a>
 & 
<a href="https://github.com/xscriptor">
  <img src="https://xscriptor.github.io/icons/icons/code/product-design/xsvg/github.svg" width="24" alt="X Github Profile" />
</a>
 & 
<a href="https://www.xscriptor.com">
  <img src="https://xscriptor.github.io/icons/icons/code/product-design/xsvg/quotes.svg" width="24" alt="Xscriptor web" />
</a>

</div>
