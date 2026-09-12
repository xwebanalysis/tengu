# Changelog

All notable changes to the Tengu project will be documented in this file.

## Unreleased

### Frontend

- **Angular 19 → 22** (`@angular/build:application`, TypeScript 6, zoneless
  change detection, standalone/signals) on Node 24; `npm ci` reproducible from
  the regenerated `package-lock.json`.
- **Vitest** unit tests (`@angular/build:unit-test` + jsdom): ApiService URL and
  contract mapping, xwa-sdk `Event` parsing/extraction, unified severity
  mapping and the export toolbar component. `npm test` runs with
  `--watch=false`.
- **Reestructura `core/` / `shared/` / `features/`**: `ApiService` (single
  HttpClient entry point), `LiveService` + `events.ts` (Event parsing),
  `ThemeService`, `TranslateService` (EN/ES signals), `ExportService`;
  `terminal`, `html-viewer`, `metric-card`, `severity-tag`, `status-badge`,
  `export-actions`; `audit` and `history` features.
- **WebSocket adapted to the xwa-sdk `Event` protocol**: meta/progress/log
  terminal lines, `[PAGE]` crawl list, `item_found` findings with unified
  severities (`pass/info/low/medium/high/critical`), pretty HTML from the
  `log`/`html_source` payload and `analysis_completed`/`analysis_error`
  completion.
- **History uses `/api/analyses*`** (xwa-sdk `Analysis` + findings) while
  keeping refresh, clear-all, two-analysis comparison and severity trend.
- **`environment.ts`/`environment.production.ts`** with runtime
  `apiBaseUrl`/`wsBaseUrl` on port 8070; all hardcoded URLs removed.
- **Nothing Design**: `--gold` token (no hardcoded `#FFD700`), no shadows,
  gradients, skeletons or emoji; severity colors applied to values. Fonts
  (Doto, Space Grotesk, Space Mono) self-hosted in `public/fonts` with
  `@font-face`; Google Fonts removed from `index.html`.
- **Tooling/docs**: Dockerfile frontend stage moved to `node:24-slim`,
  `tengu.sh build` prefers `npm ci`, and README/manual/ui-architecture
  documents updated.

## 0.2.0 - 2026-09-12

### Added

- **xwa-sdk 0.2.0 contracts** (`src/contracts.rs`): `Analysis`, `Finding`,
  `Error`, `Summary`, `Event`, `Tool`, `AnalysisStatus`, `Severity`,
  `Confidence`; severity mapping `Pass→pass`, `Info→info`, `Warning→medium`,
  `Error→high`.
- **SQLite persistence by default** (`create_sqlite_store`): `TENGU_DB_PATH`
  (default `<repo>/tengu.db`, `/data/tengu.db` in Docker), WAL,
  `busy_timeout=5000`, `foreign_keys=ON`, `audits` + `schema_meta` tables,
  write-through on insert/delete/clear and load on startup.
- **PostgreSQL** remains optional behind `--features pg`, now write-through
  (the 5 s sync loop that never propagated deletes is gone).
- **REST contract endpoints**: `GET /api/analyses`, `GET/DELETE
  /api/analyses/{id}`, `GET /api/analyses/{id}/export?format=json|csv` with
  `Content-Disposition`, alongside the unchanged `/api/audits*` routes.
- **Health JSON**: `/api/health` now returns
  `{"status","service":"tengu","version","database"}` (503 on failure).
- **WebSocket Event protocol**: `/api/audit/live` emits xwa-sdk `Event`
  envelopes (`analysis_started`, `analysis_progress`, `item_found`, `log` for
  the pretty-printed HTML, `analysis_completed` with `summary`, `analysis_error`
  with the error envelope).
- **REST rate limiting**: in-process token bucket (default 120 req/min,
  burst 30), `/api/health` exempt, 429 + error envelope + `Retry-After`.
- **Configurable CORS** via `XWA_CORS_ORIGINS` (localhost/LAN predicate by
  default) with `allow_credentials=false`.
- **Respectful crawling**: `robots.txt` honored by default
  (`TENGU_ROBOTS_TXT=0` disables), jittered 200–800 ms delays,
  `TENGU_MAX_PAGES` (50) and `TENGU_CRAWL_DEPTH` (2), real retries with
  exponential backoff and per-request timeouts.
- **Tests**: 34 unit tests (contracts, storage CRUD/persistence/PRAGMAs,
  analyzers with HTML fixtures, rate limiter, robots parser, crawl link
  scoping, CSV export).
- `.dockerignore`, `SECURITY.md`, `clean.sh` now removes `tengu.db*`.

### Changed

- Dependency refresh: axum 0.8 (route syntax `{id}`), tower-http 0.7,
  reqwest 0.13 (rustls), scraper 0.27, sqlx 0.9, tokio 1.53, thiserror 2.0.20.
  Removed unused direct dependencies (`selectors`, `regex`, `sha2`, `base64`,
  `futures`, `tokio-stream`).
- Default port is now **8070** (XWA standard) in code, compose and scripts.
- Default DB path replaces the old in-memory-only default; in-memory remains
  as a fallback if SQLite cannot be opened.
- Dockerfile fixed (`--no-install-recommends`), static assets copied from the
  builder stage, healthcheck added; compose uses port 8070 and
  `TENGU_DB_PATH=/data/tengu.db` on a persistent volume.
- `tengu.sh` has a `local` mode as default (SQLite native on :8070, prebuilt
  frontend only) while keeping `docker`, `export`, `import`, `build`, `--rm`.
- All compiler warnings fixed; `cargo fmt --check`, `cargo clippy -- -D
  warnings` (and `--all-features`) and `cargo test` are green.
- `fxhash` removed from the dependency graph; `event-listener` updated to 5.4.2
  (RUSTSEC-2026-0221 remediated).

## 0.1.0 - 2026-07-04

### Added

- Initial project scaffold with Rust (Axum) backend and Angular 19 frontend
- Performance audit engine: page weight, resource waterfall, image optimization, font loading, cache policy, compression, render-blocking detection
- SEO audit engine: title, meta description, heading hierarchy, canonical, Open Graph, Twitter Cards, JSON-LD, meta robots, hreflang, language attribute
- Accessibility audit engine: alt text, heading structure, ARIA attributes, landmark elements, form labels, keyboard navigation, link text, tables, iframes, viewport, language, color contrast
- Best practices audit engine: HTTPS, security headers, cookie attributes, doctype, deprecated HTML, mixed content, SRI
- WebSocket-based real-time audit streaming
- Angular UI with Nothing Design System (dark theme, Space Grotesk + Space Mono, dot-grid motifs)
- Audit configuration form with category toggles
- Real-time findings display with severity badges and detail expansion
- Docker build with multi-stage Rust compilation
- ROADMAP.md with phased development plan
