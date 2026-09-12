# Tengu Development Roadmap

This document tracks the strategic steps required to evolve Tengu into a full-scale web quality auditing platform.
This file is formatted to be synced automatically with GitHub Issues using the `xgh` roadmap standard.

> Status: 2026-09-12 — backend `0.2.0` (Axum 0.8, SQLite-first, xwa-sdk contracts).
> Frontend on Angular 22 (zoneless, Vitest, Nothing Design) consuming the xwa-sdk `Event` protocol.

## Core Engine <!-- phase:core -->

- [x] HTTP client with configurable timeouts, redirect handling, and retry logic (exponential backoff + jitter, `TENGU_HTTP_RETRY`)
- [x] HTML parser with DOM tree extraction and serialization
- [x] URL normalization and canonicalization
- [x] Batch URL analysis from sitemap, CSV, or single entry
- [x] Crawl mode for full-site auditing with depth/pages configuration (`TENGU_CRAWL_DEPTH`, `TENGU_MAX_PAGES`)
- [x] Request watermarking (request ID, timestamp per analysis)
- [x] `robots.txt` respected by default with jittered 200–800 ms crawl delay
- [x] Bounded concurrency (`TENGU_MAX_CONCURRENT`) and cancel-on-disconnect

## Performance Analysis <!-- phase:performance -->

- [x] Page weight audit (total bytes, DOM node count, request count)
- [x] Largest Contentful Paint (LCP) — noted, requires browser
- [x] Cumulative Layout Shift (CLS) — noted, requires browser
- [x] Interaction to Next Paint (INP) — noted, requires browser
- [x] Resource loading waterfall (blocking vs deferred, render-blocking resources)
- [x] Image optimization audit (missing dimensions, wrong format, oversized)
- [x] Font loading audit (swap/block/fallback behavior, variable font usage)
- [x] Cache policy audit (Cache-Control, ETag, Last-Modified headers)
- [x] Compression audit (gzip/brotli negotiation, content encoding)
- [x] Third-party script performance impact scoring

## SEO Analysis <!-- phase:seo -->

- [x] Title tag presence, length, and uniqueness analysis
- [x] Meta description presence and quality scoring
- [x] Heading hierarchy validation (h1-h6 order, missing levels, multiple h1)
- [x] Canonical URL detection and cross-page consistency check
- [x] Open Graph tag audit (og:title, og:description, og:image, og:type)
- [x] Twitter Card tag audit (card, site, title, description, image)
- [x] JSON-LD structured data extraction and schema validation
- [x] Microdata and RDFa extraction
- [x] Sitemap.xml discovery, parsing, and URL coverage analysis
- [x] Robots.txt parsing, rule interpretation, and directives audit
- [x] Meta robots tag analysis (index/noindex, follow/nofollow)
- [x] hreflang tag audit for multilingual sites
- [x] Redirect chain analysis (301/302 chain length, circular redirect detection)
- [x] Broken link detection (404/410 discovery within crawled pages)

## Accessibility Analysis <!-- phase:a11y -->

- [x] Image alt text presence and quality analysis
- [x] Heading structure and document outline validation
- [x] ARIA attribute usage audit (roles, labels, descriptions)
- [x] Landmark element detection and structure analysis
- [x] Color contrast ratio calculation (WCAG AA/AAA compliance)
- [x] Keyboard navigation audit (focusable elements, tab order, focus indicators)
- [x] Form label association validation (label-for, aria-label, aria-labelledby)
- [x] Video/audio transcript and caption detection
- [x] Language attribute validation (html lang attribute)
- [x] Viewport and zoom configuration audit
- [x] Link text quality analysis (descriptive vs generic text like "click here")
- [x] Table structure validation (headers, captions, scope attributes)
- [x] Iframe title attribute audit
- [x] Focus indicator visibility (outline:none detection in inline styles)

## Best Practices & Compliance <!-- phase:best-practices -->

- [x] HTTPS enforcement audit
- [x] Security headers audit (HSTS, CSP, X-Frame-Options, X-Content-Type-Options, Referrer-Policy, Permissions-Policy)
- [x] Cookie audit (Secure, HttpOnly, SameSite attributes, third-party cookies)
- [x] GDPR cookie consent banner detection and pattern analysis
- [x] Doctype and HTML validation (W3C standards compliance)
- [x] Deprecated HTML element and attribute detection
- [x] Mixed content detection (HTTPS page loading HTTP resources)
- [x] Subresource Integrity (SRI) audit for external scripts and stylesheets
- [x] Console error detection (noted: requires browser runtime)
- [x] Content Security Policy parsing and directive coverage analysis
- [x] Permissions-Policy / Feature-Policy audit

## Backend API <!-- phase:backend -->

- [x] Axum project scaffold with JSON `/api/health` (`status`, `service`, `version`, `database`)
- [x] REST endpoints for audit CRUD (list/get/delete/clear/import/export)
- [x] WebSocket endpoint for real-time audit streaming (`/api/audit/live`)
- [x] SQLite persistence by default (WAL, `busy_timeout`, write-through, `schema_meta`)
- [x] Optional PostgreSQL backend behind `--features pg` (write-through)
- [x] Database export/import following the XWA pattern
- [x] xwa-sdk `Event`/`Analysis`/`Finding` contracts over REST and WS
- [x] Server-side export `format=json|csv` with `Content-Disposition`
- [ ] Long-running task queue (audits run in-process, bounded by a semaphore)

## Web Interface <!-- phase:web-ui -->

- [x] Angular 22 standalone project with Nothing Design tokens (zoneless, Vitest)
- [x] Audit configuration form (URL input, category toggles, crawl depth)
- [x] Real-time progress via WebSocket (xwa-sdk `Event` envelopes)
- [x] Score dashboard with per-category breakdown
- [x] Detailed findings list with severity, category, and check-level filtering
- [x] HTML source snippets with line highlighting
- [x] History page with past audit results, comparison and severity trend
- [x] Dark/light theme toggle
- [x] Self-hosted fonts (Doto, Space Grotesk, Space Mono) and `environment.ts` URLs

## Reporting <!-- phase:reporting -->

- [x] PDF report generation with score summary and findings table
- [x] CSV export of all findings
- [x] JSON export for programmatic consumption
- [x] HTML export
- [x] Markdown export
- [x] Score history trend chart (SVG chart, no external deps)
- [x] Lighthouse-compatible JSON output format
- [x] Comparison report between two audits (before/after)

## Integration <!-- phase:xwa -->

- [x] xwa-sdk 0.2.0 contracts (`Analysis`, `Finding`, `Error`, `Summary`, `Event`)
- [ ] Shared Nothing Design component library with Samurai
- [ ] Unified XWA docker-compose orchestration
- [ ] XWA API gateway integration

## Production Hardening <!-- phase:production -->

- [x] Authentication middleware for API endpoints (`TENGU_API_KEY`, header-first)
- [x] Rate limiting for REST and WebSocket requests (120 req/min default)
- [x] Audit history retention policies and cleanup (`TENGU_MAX_HISTORY`)
- [x] Structured logging with request watermarking (`tracing`)
- [x] Prometheus metrics endpoint (`/api/metrics`)
- [x] Docker multi-stage build and compose with persistent SQLite volume
- [x] Configurable CORS (`XWA_CORS_ORIGINS`, credentials disabled)
- [x] Zero compiler warnings; fmt/clippy/tests green
