# Tengu

*Auditor de calidad web -- Rendimiento, SEO, Accesibilidad, Buenas Practicas*

[Tengu](https://github.com/xwebanalysis/tengu) : [XWA](https://github.com/xwebanalysis/meta) submodule focused on web quality auditing -- under active development

[English](../../README.md) | [Espanol](README.md)

---

## Descripcion General

Tengu es un auditor de calidad web que evalua aplicaciones en cuatro dimensiones:

| Categoria | Alcance |
|---|---|
| **Rendimiento** | Peso de pagina, Core Web Vitals (LCP, CLS, INP), cascada de recursos, optimizacion de imagenes, carga de fuentes, politica de cache, compresion, impacto de terceros |
| **SEO** | Etiquetas title, meta descriptions, jerarquia de encabezados, URLs canonicas, Open Graph, Twitter Cards, JSON-LD, sitemaps, robots.txt, hreflang, cadenas de redireccion, enlaces rotos |
| **Accesibilidad** | Texto alternativo, estructura de encabezados, atributos ARIA, elementos landmark, contraste de color (WCAG AA/AAA), navegacion por teclado, etiquetas de formularios, texto de enlaces, tablas, iframes, configuracion de viewport |
| **Buenas Practicas** | HTTPS obligatorio, headers de seguridad (HSTS, CSP, XFO, etc.), auditoria de cookies, deteccion de banner GDPR, validacion de doctype, HTML obsoleto, contenido mixto, SRI, errores de consola |

| Interfaz | Directorio | Lenguaje | Tipo |
|---|---|---|---|
| **Tengu Web** | `/` (raiz del monorepo) | Rust (Axum) + Angular 22 | Aplicacion web (standalone o Docker) |

## Inicio Rapido

### Local (por defecto, SQLite)

```
./tengu.sh            # ./tengu.sh local
```

Backend nativo en `http://localhost:8070` con SQLite en `<repo>/tengu.db`
(configurable con `TENGU_DB_PATH`). Sirve el frontend preconstruido si existe.

### Directo con Cargo

```
TENGU_DB_PATH=/tmp/tengu.db PORT=8070 cargo run --release
```

Web UI en `http://localhost:8070`.

### Version Web (Docker Compose)

```
docker compose up -d --build
```

Web UI en `http://localhost:8070`; la base SQLite persiste en el volumen
`tengu_data` (`/data/tengu.db`).

### Variables de Entorno

| Variable | Por Defecto | Descripcion |
|---|---|---|
| `PORT` | `8070` | Puerto de escucha HTTP |
| `TENGU_DB_PATH` | `tengu.db` (`/data/tengu.db` en Docker) | Fichero SQLite |
| `TENGU_MAX_HISTORY` | `100` | Auditorias persistidas maximas |
| `TENGU_RATE_LIMIT_PER_MINUTE` | `120` | Rate limit REST/WS |
| `TENGU_MAX_PAGES` / `TENGU_CRAWL_DEPTH` | `50` / `2` | Limites del crawl |
| `XWA_CORS_ORIGINS` | localhost/LAN | Origenes CORS permitidos |
| `RUST_LOG` | `tengu=info,tower_http=info` | Verbosidad de logging |

## Documentos Relacionados

| Documento | Descripcion |
|---|---|
| [ROADMAP.md](../../ROADMAP.md) | Fases de desarrollo y hitos |
| [CHANGELOG.md](../../CHANGELOG.md) | Historial de versiones |
| [manual.md](manual.md) | Guia de despliegue y uso |
| [ui-architecture.md](ui-architecture.md) | Arquitectura del frontend |
| [rust-libraries.md](rust-libraries.md) | Dependencias Rust del backend |
| [uses/audit.md](uses/audit.md) | Guia de uso del auditor |

## Estructura del Proyecto

```
tengu/
├── src/
│   ├── main.rs              # Punto de entrada del servidor Axum
│   ├── config.rs            # Configuracion de auditoria
│   ├── api/
│   │   └── routes.rs        # API REST + WebSocket
│   ├── auditor/
│   │   ├── mod.rs           # Orquestador + modelo Finding
│   │   ├── performance.rs   # Peso, recursos, imagenes, fuentes
│   │   ├── seo.rs           # Meta tags, datos estructurados
│   │   ├── a11y.rs          # Cumplimiento WCAG, ARIA
│   │   ├── best_practices.rs# Headers de seguridad, cookies
│   │   └── html_pretty.rs   # Pretty-printing de HTML
│   └── storage/
│       └── mod.rs           # Almacenamiento en memoria / SQLite / PostgreSQL
├── contracts.rs             # Contratos xwa-sdk 0.2.0 (Analysis, Finding, Event)
├── frontend/                # Angular 22 (zoneless, Vitest, Nothing Design)
│   ├── package.json
│   ├── angular.json
│   └── src/app/
│       ├── features/audit/  # Configuracion y resultados
│       └── features/history/# Historial de auditorias
├── docs/                    # Documentacion tecnica
│   ├── manual.md
│   ├── ui-architecture.md
│   ├── rust-libraries.md
│   ├── uses/audit.md
│   └── esp/                 # Documentacion en espanol
├── Dockerfile
├── docker-compose.yml
├── Cargo.toml
├── ROADMAP.md
└── CHANGELOG.md
```

## Script de Inicio

```
./tengu.sh                        # local (por defecto): SQLite nativo :8070
./tengu.sh local                  # igual que arriba
./tengu.sh docker                 # via docker-compose
./tengu.sh docker --rm            # Docker efimero (--rm)
./tengu.sh export [archivo]       # Exportar a ./exports/
./tengu.sh import archivo.json    # Importar JSON
./tengu.sh build                  # Compilar solo el frontend
./tengu.sh clean                  # Delegar en ./clean.sh
```
