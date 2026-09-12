# Arquitectura de la UI de Tengu

## Framework

Angular 22 standalone (sin NgModules), deteccion de cambios zoneless
(`provideZonelessChangeDetection`), TypeScript 6, `@angular/build:application`,
Vitest 4 + jsdom mediante `@angular/build:unit-test`. Requiere Node 24
(`mise`). El build de produccion se emite en `../static` con
`outputHashing: "none"` para que el backend Axum sirva
`static/browser/main.js` y `static/browser/styles.css` sin manifest.

Todo el estado usa signals: los callbacks del WebSocket mutan signals y el
change detection zoneless programa la actualizacion — sin
`ChangeDetectorRef`.

## Estructura de Directorios

```
frontend/
├── public/fonts/                    # woff2 self-hosted (Doto, Space Grotesk, Space Mono)
├── scripts/test.sh                  # wrapper de npm test (unit-test builder)
├── src/
│   ├── _fonts.scss                  # @font-face compilado dentro de styles.css
│   ├── environments/
│   │   ├── environment.ts           # apiBaseUrl/wsBaseUrl runtime :8070
│   │   └── environment.production.ts
│   ├── styles.scss                  # tokens Nothing (incl. --gold), primitivas, dot-grid
│   └── app/
│       ├── core/                    # api, events (WS), live, models, export,
│       │                            # i18n, theme, snippet-locator
│       ├── shared/                  # terminal, html-viewer, metric-card,
│       │                            # severity-tag, status-badge, export-actions
│       └── features/                # audit, history
```

## Arbol de Componentes

```
App (shell: sidebar, toggles de tema/idioma, router-outlet)
├── AuditComponent
│   ├── Formulario (URL, single/fullsite/batch, pestañas de checks)
│   ├── TerminalComponent (lineas de Event, paginas [PAGE], estado live)
│   ├── MetricCardComponent x4 (high/medium/info/pass)
│   ├── Lista de hallazgos (SeverityTag + snippet + linea de origen)
│   ├── HtmlViewerComponent (HTML pretty con resaltado de hallazgos)
│   └── ExportActionsComponent (CSV/JSON/LH/HTML/MD/PDF)
└── HistoryComponent
    ├── StatusBadgeComponent por analisis
    ├── Grafico de tendencia (high / medium / total)
    └── Comparacion de 2 auditorias + diffs de severidad
```

## Rutas

| Ruta | Componente | Descripcion |
|---|---|---|
| `/audit` | `AuditComponent` | Ejecutar y ver auditorias (`?load=<id>` carga del historial) |
| `/history` | `HistoryComponent` | Lista `/api/analyses`, comparacion y tendencia |
| `/` | (redirect) | Redirige a `/audit` |

## Acceso a la API

Todas las URLs salen de `environment.apiBaseUrl` / `environment.wsBaseUrl`
(hostname runtime + puerto 8070). `ApiService` expone health,
`GET/DELETE /api/analyses*`, `DELETE /api/audits/clear` (borrado masivo; no
existe `DELETE /api/analyses`), constructores de URL de export y del WebSocket
`/api/audit/live`. Los payloads se normalizan en `models.ts` (`target` → `url`,
`target_url` → `page_url`, `evidence.snippet` → `snippet`) y la severidad se
normaliza a la escala unificada `pass|info|low|medium|high|critical`
(aceptando etiquetas legacy `Pass/Warning/Error`).

## Protocolo WebSocket (xwa-sdk `Event`)

`LiveService` envuelve el socket en un Observable; cada frame se parsea con
`parseEvent()` y los frames invalidos se ignoran.

| Evento `type` | Payload | Reconstruccion en la UI |
|---|---|---|
| `analysis_started` | `{target, mode}` | Linea `[AUDIT_META]`, guarda `analysis_id` |
| `analysis_progress` | `{message, percent?}` | Linea `[AUDIT]`; `[PAGE] <url>` suma a paginas rastreadas |
| `log` | `{level, message, data}` | Linea `[LEVEL]`; `message=html_source` → HTML pretty en `data.html` |
| `item_found` | `Finding` xwa-sdk | Lista de hallazgos (`Pass→pass`, `Info→info`, `Warning→medium`, `Error→high`) |
| `analysis_completed` | `{status, summary}` | Cierra la ejecucion, `[done]` |
| `analysis_error` | `{code, message, detail, retryable}` | Muestra `[!] CODE: message` y cierra |

Los errores de transporte cierran la ejecucion con `[!] WebSocket connection
error`.

## Historial

`HistoryComponent` lee `/api/analyses` (contrato xwa-sdk) manteniendo todas las
funciones legacy: refrescar, borrar todo, comparar 2 auditorias (`check` +
`category`, cambios de severidad) y tendencia (high / medium / total). Cada fila
se carga en la vista de auditoria via `/audit?load=<id>`.

## Exports

`ExportService` genera blobs en memoria (descarga por anchor temporal): CSV,
JSON, Lighthouse JSON, informe HTML, informe Markdown y PDF (jsPDF + autotable
con import perezoso para no engordar el bundle inicial). El contexto incluye
filtros activos, URL, modo y HTML pretty para numeros de linea.

## Sistema de Diseno

Los tokens Nothing viven en `styles.scss` (`--gold: #ffd700` tokenizado; sin
`#FFD700` hardcodeado). Las fuentes son self-hosted desde `public/fonts` via
`_fonts.scss`; `index.html` ya no referencia Google Fonts. Los colores de
estado se aplican al valor (`.sev-*`, `.text-*`), nunca al fondo de fila; sin
sombras, gradientes (salvo el motivo dot-grid), skeletons ni emojis.

## Tests y Verificacion

```bash
export PATH="$HOME/.local/share/mise/installs/node/24/bin:$PATH"
cd frontend
npm ci
npm test          # api.service, parseo Event, mapeo de severidad, componente export
npm run build     # -> ../static/browser
npm audit --omit=dev
```

`tsconfig.spec.json` habilita `vitest/globals`; los specs viven junto al codigo
(`*.spec.ts`). `scripts/test.sh` acepta el flag `--run` de Vitest.
