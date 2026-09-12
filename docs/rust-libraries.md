# Rust Libraries (Backend Dependencies)

Tengu's backend is an Axum 0.8 application on Tokio. Dependencies are pinned in
`Cargo.lock` (versioned). Last audit: 2026-09-12, Rust 1.98.

## Web Framework & Server

| Crate | Version | Purpose |
|---|---|---|
| `axum` | 0.8 | HTTP framework with WebSocket support |
| `tower-http` | 0.7 | CORS middleware |
| `tokio` | 1.53 | Async runtime (`full` features) |

## HTTP Client

| Crate | Version | Purpose |
|---|---|---|
| `reqwest` | 0.13 | HTTP client with rustls, charset, http2, cookies, gzip/brotli, JSON |
| `url` | 2 | URL parsing, normalization and crawl scoping |

## HTML Parsing & Selection

| Crate | Version | Purpose |
|---|---|---|
| `scraper` | 0.27 | HTML parser and CSS selector engine (html5ever + selectors 0.38) |
| `ego-tree` | 0.11 | DOM node references used by `html_pretty` (must match scraper's version) |

`selectors` is no longer a direct dependency (scraper pulls its own);
`fxhash` is no longer in the dependency graph (selectors now uses
`rustc-hash`).

## Persistence

| Crate | Version | Purpose |
|---|---|---|
| `sqlx` | 0.9 | Async SQL; features `runtime-tokio`, `sqlite`, `chrono`, `uuid`, `json` |
| `sqlx` (`pg` feature) | 0.9 | Optional PostgreSQL support (`sqlx/postgres`, `sqlx/tls-rustls`) |
| `dashmap` | 6 | In-memory fallback store and concurrent map |
| `uuid` | 1 | Audit identifiers (v4, serde) |
| `chrono` | 0.4 | Timestamps (serde) |
| `thiserror` | 2 | `StoreError` derivation |

`event-listener` (transitive via `sqlx-core`) is pinned at **5.4.2**, which
remediates RUSTSEC-2026-0221. `rsa` is not compiled (sqlx-mysql is not enabled).

## Serialization & Contracts

| Crate | Version | Purpose |
|---|---|---|
| `serde` | 1 | Serialization framework (derive) |
| `serde_json` | 1 | JSON serialization/deserialization |
| `contracts.rs` | — | Hand-mirrored xwa-sdk 0.2.0 models (`Analysis`, `Finding`, `Event`, `Error`, `Summary`) |

## Logging & Observability

| Crate | Version | Purpose |
|---|---|---|
| `tracing` | 0.1 | Structured logging |
| `tracing-subscriber` | 0.3 | Log output formatting with env-filter |

## Security & Limits

- Token bucket rate limiter implemented in-process (`main.rs`), 120 req/min.
- Constant-time API key comparison.
- CORS via `tower-http`, `XWA_CORS_ORIGINS` driven.
- Crawl: robots.txt parser, jittered delays, exponential backoff, page/depth
  caps and per-request timeouts.

## Removed from earlier versions

| Crate | Why |
|---|---|
| `selectors` | Unused directly; scraper provides selectors |
| `regex` | Unused |
| `sha2` | Unused (SRI hashes are computed externally by site owners) |
| `base64` | Unused (same) |
| `futures` | Unused |
| `tokio-stream` | Unused |
