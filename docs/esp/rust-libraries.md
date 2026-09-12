# Librerias Rust (Dependencias del Backend)

El backend de Tengu es una aplicacion Axum 0.8 sobre Tokio. Las versiones estan
fijadas en `Cargo.lock`. Ultima auditoria: 2026-09-12, Rust 1.98.

## Framework Web y Servidor

| Crate | Version | Proposito |
|---|---|---|
| `axum` | 0.8 | Framework HTTP con soporte WebSocket |
| `tower-http` | 0.7 | Middleware CORS |
| `tokio` | 1.53 | Runtime asincrono (features completas) |

## Cliente HTTP

| Crate | Version | Proposito |
|---|---|---|
| `reqwest` | 0.13 | Cliente HTTP con rustls, charset, http2, cookies y gzip/brotli |
| `url` | 2 | Parseo, normalizacion y alcance de crawl |

## Parseo y Seleccion HTML

| Crate | Version | Proposito |
|---|---|---|
| `scraper` | 0.27 | Parser HTML y motor de seleccion CSS (html5ever + selectors 0.38) |
| `ego-tree` | 0.11 | Nodos DOM usados por `html_pretty` (debe coincidir con scraper) |

`selectors` ya no es dependencia directa; `fxhash` desaparecio del grafo
(selectors usa `rustc-hash`).

## Persistencia

| Crate | Version | Proposito |
|---|---|---|
| `sqlx` | 0.9 | SQL asincrono; features `runtime-tokio`, `sqlite`, `chrono`, `uuid`, `json` |
| `sqlx` (feature `pg`) | 0.9 | PostgreSQL opcional (`sqlx/postgres`, `sqlx/tls-rustls`) |
| `dashmap` | 6 | Almacenamiento en memoria de respaldo |
| `uuid` | 1 | Identificadores de auditoria (v4, serde) |
| `chrono` | 0.4 | Marcas de tiempo (serde) |
| `thiserror` | 2 | Derivacion de `StoreError` |

`event-listener` (transitivo via `sqlx-core`) esta fijado en **5.4.2**,
remediando RUSTSEC-2026-0221.

## Serializacion y Contratos

| Crate | Version | Proposito |
|---|---|---|
| `serde` | 1 | Framework de serializacion (con derive) |
| `serde_json` | 1 | Serializacion/deserializacion JSON |
| `contracts.rs` | — | Modelos xwa-sdk 0.2.0 (`Analysis`, `Finding`, `Event`, `Error`, `Summary`) |

## Logging y Observabilidad

| Crate | Version | Proposito |
|---|---|---|
| `tracing` | 0.1 | Logging estructurado |
| `tracing-subscriber` | 0.3 | Formateo de salida de log con env-filter |

## Eliminadas respecto a versiones anteriores

`selectors`, `regex`, `sha2`, `base64`, `futures`, `tokio-stream` (sin uso
directo).
