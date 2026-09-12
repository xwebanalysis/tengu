# Tengu UI Architecture

## Framework

Angular 22 standalone (no NgModules), zoneless change detection
(`provideZonelessChangeDetection`), TypeScript 6, `@angular/build:application`,
Vitest 4 + jsdom through `@angular/build:unit-test`. Node 24 is required
(`mise`). The production build is emitted to `../static` with
`outputHashing: "none"` so the Axum backend can serve `static/browser/main.js`
and `static/browser/styles.css` without a manifest.

All UI state is signal-based: WebSocket callbacks mutate signals and zoneless
change detection schedules the view update automatically.

**Zoneless rule (Angular 22, no `zone.js`).** Signal writes (`set` / `update`)
always schedule change detection. A **plain component property** mutated inside
an asynchronous callback (WebSocket/SSE, `HttpClient`, `setTimeout`, promise)
does **not**; if it is read by the template, inject `ChangeDetectorRef` and call
`this.cdr.markForCheck()` after the mutation (or keep the state in a signal).
The current code follows this rule: audit/history state is signal-based, so no
`ChangeDetectorRef` is needed today — do not add flat async state without
`markForCheck` later.

## Directory Layout

```
frontend/
├── public/fonts/                    # self-hosted woff2 (Doto, Space Grotesk, Space Mono)
├── scripts/test.sh                  # npm test wrapper (Angular unit-test builder)
├── src/
│   ├── _fonts.scss                  # @font-face declarations (compiled into styles.css)
│   ├── environments/
│   │   ├── environment.ts           # runtime apiBaseUrl/wsBaseUrl :8070
│   │   └── environment.production.ts
│   ├── styles.scss                  # Nothing tokens (incl. --gold), primitives, dot-grid
│   └── app/
│       ├── core/
│       │   ├── api.service.ts       # single HttpClient entry point (all URLs)
│       │   ├── events.ts            # xwa-sdk Event parsing/extraction (pure)
│       │   ├── live.service.ts      # WebSocket -> Observable<LiveEvent>
│       │   ├── models.ts            # contract adapters, FindingView, severities
│       │   ├── export.service.ts    # CSV/JSON/Lighthouse/PDF/HTML/MD
│       │   ├── i18n.service.ts      # EN/ES signals + translations
│       │   ├── theme.service.ts     # dark/light signals (localStorage)
│       │   └── snippet-locator.ts   # snippet -> source line, HTML highlighting
│       ├── shared/
│       │   ├── terminal/            # live log panel, auto-scroll
│       │   ├── html-viewer/         # pretty HTML with highlight + finding lines
│       │   ├── metric-card/         # severity summary metric
│       │   ├── severity-tag/        # [ SEVERITY ] unified scale
│       │   ├── status-badge/        # [ COMPLETED | RUNNING | ERROR ]
│       │   ├── export-actions/      # export toolbar
│       │   └── pipes/translate.pipe.ts
│       └── features/
│           ├── audit/               # live audit + results + source viewer
│           └── history/             # analyses table, comparison, trend
```

## Component Tree

```
App (shell: sidebar, theme/language toggles, router-outlet)
├── AuditComponent
│   ├── Audit form (URL, single/fullsite/batch, check tabs)
│   ├── TerminalComponent (Event log lines, [PAGE] list, live state)
│   ├── MetricCardComponent x4 (high/medium/info/pass counts)
│   ├── Findings accordion (SeverityTag + snippet + source line)
│   ├── HtmlViewerComponent (pretty source, finding-line highlight)
│   └── ExportActionsComponent (CSV/JSON/LH/HTML/MD/PDF)
└── HistoryComponent
    ├── StatusBadgeComponent (per analysis)
    ├── Severity trend SVG (high / medium / total)
    └── Two-analysis comparison + severity diffs
```

## Routes

| Path | Component | Description |
|---|---|---|
| `/audit` | `AuditComponent` | Run and view audits (`?load=<id>` loads from history) |
| `/history` | `HistoryComponent` | Browse `/api/analyses`, compare and trend |
| `/` | (redirect) | Redirects to `/audit` |

## API Access

All backend URLs come from `environment.apiBaseUrl` / `environment.wsBaseUrl`
(runtime hostname + port 8070). `ApiService` exposes:

- `GET /api/health`
- `GET /api/analyses`, `GET /api/analyses/{id}`, `DELETE /api/analyses/{id}`
- `DELETE /api/audits/clear` (bulk clear; there is no `DELETE /api/analyses`)
- `/{id}/export?format=json|csv` URL builder
- `/api/audit/live` WebSocket URL builder

Contract payloads are normalized in `models.ts` (`analysisFromContract`,
`findingFromContract`): `target` → `url`, `target_url` → `page_url`,
`evidence.snippet` → `snippet`, and severity is normalized to the unified
`pass | info | low | medium | high | critical` scale (legacy `Pass/Warning/Error`
labels are still accepted).

## WebSocket Protocol (xwa-sdk `Event`)

`LiveService` wraps the socket in an Observable; every frame is parsed by
`parseEvent()` and malformed frames are ignored.

| Event `type` | Payload | UI reconstruction |
|---|---|---|
| `analysis_started` | `{target, mode}` | Terminal `[AUDIT_META]` line, stores `analysis_id` |
| `analysis_progress` | `{message, percent?}` | Terminal `[AUDIT]` line; `[PAGE] <url>` appends to crawled pages |
| `log` | `{level, message, data}` | Terminal `[LEVEL]` line; `message=html_source` → pretty HTML in `data.html` |
| `item_found` | xwa-sdk `Finding` | Finding list (severity mapped `Pass→pass`, `Info→info`, `Warning→medium`, `Error→high`) |
| `analysis_completed` | `{status, summary}` | Marks the run complete, shows `[done]` |
| `analysis_error` | `{code, message, detail, retryable}` | Shows `[!] CODE: message` and completes the run |

Transport errors close the run with `[!] WebSocket connection error`. The
backend drops the socket right after a terminal event without a clean close
frame (browsers report this as an abnormal 1006 closure), so `LiveService`
tracks whether `analysis_completed` / `analysis_error` was received and treats
the subsequent close as `complete()` instead of an error — the UI no longer
appends a spurious transport error after a successful audit.

## History

`HistoryComponent` reads `/api/analyses` (xwa-sdk `Analysis` + findings) and
keeps every feature of the legacy `/api/audits` UI: refresh, clear-all,
two-analysis comparison (`check` + `category`, severity changes) and the
severity trend chart (high / medium / total over time). A table row loads back
into the audit view through `/audit?load=<id>`.

## Exports

`ExportService` generates in-memory blobs (temporary anchor download):
CSV, JSON, Lighthouse JSON, HTML report, Markdown report and PDF
(jsPDF + autotable imported lazily, so they stay out of the initial bundle).
The audit context carries the current filters, URL, mode and pretty HTML so
source-line numbers are included where available.

## Design System

Nothing tokens live in `styles.scss` (`--gold: #ffd700` is tokenized; no
hardcoded `#FFD700` remains). Fonts are self-hosted from `public/fonts` via
`_fonts.scss`; `index.html` no longer references Google Fonts. Data-status
colors are applied to values only (`.sev-*`, `.text-*` helpers), never as row
backgrounds; no shadows, gradients (except the dot-grid motif), skeletons or
emoji are used.

## Tests and Verification

```bash
export PATH="$HOME/.local/share/mise/installs/node/24/bin:$PATH"
cd frontend
npm ci
npm test          # api.service, Event parsing, severity mapping, export component
npm run build     # -> ../static/browser
npm audit --omit=dev
```

`tsconfig.spec.json` enables `vitest/globals`; specs live next to the source
(`*.spec.ts`). `scripts/test.sh` accepts the Vitest `--run` flag.

End-to-end browser validation lives in `e2e/`:
`e2e/browser_smoke.py` (Playwright + headless Chromium) starts the local
fixture server, audits it from the UI, asserts that findings/HTML render
without clicks, exercises History (list, detail, trend, comparison) and every
export format, and fails on any console/page error. See `e2e/README.md`.
