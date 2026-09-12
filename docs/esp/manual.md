# Manual de Tengu

## Despliegue

### Local (por defecto, SQLite)

```bash
./tengu.sh            # ./tengu.sh local
```

Servidor Axum nativo en `http://localhost:8070` con SQLite en
`<repo>/tengu.db` (configurable con `TENGU_DB_PATH`).

### Docker (volumen SQLite persistente)

```bash
docker compose up -d --build
```

Interfaz web en `http://localhost:8070`; base de datos en `/data/tengu.db`.

### Standalone

```bash
TENGU_DB_PATH=/tmp/tengu.db PORT=8070 cargo run --release
```

Requiere Rust 1.86+. `build.rs` **no** compila el frontend: solo declara rutas
`rerun-if-changed`. Para construir la UI usa `./tengu.sh build` o, dentro de
`frontend/`, `npm ci && npm run build` con Node 24 (Angular 22 + Nothing
Design; la salida va a `../static`). `npm test` ejecuta la suite Vitest.
Interfaz web en `http://localhost:8070`.

### Script de Inicio

```bash
./tengu.sh                        # local (por defecto): SQLite nativo :8070
./tengu.sh local                  # igual que arriba
./tengu.sh docker                 # via docker-compose
./tengu.sh docker --rm            # Docker efimero (--rm, limpia automaticamente)
./tengu.sh export [archivo]       # Guardar exportacion en ./exports/
./tengu.sh import archivo.json    # Importar JSON de auditoria
./tengu.sh build                  # Solo compilar el frontend
./tengu.sh -b                     # Forzar rebuild del frontend al arrancar
```

## Variables de Entorno

| Variable | Por Defecto | Descripcion |
|---|---|---|
| `PORT` | `8070` | Puerto de escucha HTTP |
| `TENGU_DB_PATH` | `tengu.db` (`/data/tengu.db` en Docker) | Fichero SQLite |
| `DATABASE_URL` | — | DSN PostgreSQL (requiere `--features pg`) |
| `TENGU_MAX_HISTORY` | `100` | Auditorias persistidas maximas |
| `TENGU_MAX_PAGES` / `TENGU_CRAWL_DEPTH` | `50` / `2` | Limites de crawl |
| `TENGU_ROBOTS_TXT` | `1` | Respetar robots.txt (`0` lo desactiva) |
| `TENGU_RATE_LIMIT_PER_MINUTE` | `120` | Token bucket REST/WS |
| `XWA_CORS_ORIGINS` | localhost/LAN | Origenes CORS permitidos |
| `RUST_LOG` | `tengu=info,tower_http=info` | Verbosidad de logging (env-filter) |

## Uso

### Auditoria de URL Unica

1. Ingresa una URL en el campo de texto
2. Selecciona las categorias de auditoria (Rendimiento, SEO, Accesibilidad, Buenas Practicas)
3. Haz clic en START AUDIT
4. Los resultados se transmiten en tiempo real via WebSocket con envelopes
   `Event` de xwa-sdk (`analysis_started`, `analysis_progress`, `item_found`,
   `log`, `analysis_completed` / `analysis_error`)

### Auditoria de Sitio Completo

1. Activa el modo FULL SITE
2. Opcionalmente activa INCLUDE SUBDOMAINS
3. Ingresa la URL inicial
4. Tengu rastrea las paginas descubiertas (hasta 50) y audita cada una

### Interpretacion de Resultados

Cada hallazgo muestra:
- **Severidad**: escala unificada xwa-sdk (`pass`, `info`, `low`, `medium`, `high`, `critical`; el backend mapea `Pass→pass`, `Info→info`, `Warning→medium`, `Error→high`)
- **Check**: Nombre de la comprobacion especifica
- **Titulo**: Resumen del problema
- **Descripcion**: Explicacion detallada con recomendaciones
- **Fragmento**: El elemento HTML relevante (si aplica)
- **Linea**: Numero de linea en el codigo HTML formateado

### Visor de Codigo Fuente

Despues de una auditoria, haz clic en VIEW HTML para ver el codigo fuente formateado. Las lineas con hallazgos se resaltan con un borde rojo a la izquierda.

### Exportacion

Los resultados se pueden exportar en seis formatos:

| Formato | Extension | Contenido |
|---|---|---|
| CSV | `.csv` | Datos tabulares con todos los campos |
| JSON | `.json` | Payload completo con metadatos |
| Lighthouse JSON | `.json` | Formato compatible con Lighthouse |
| PDF | `.pdf` | Informe apaisado con tabla de hallazgos |
| HTML | `.html` | Informe auto-contenido con estilos |
| Markdown | `.md` | Informe de texto ligero |

## Endpoints de API

| Metodo | Ruta | Descripcion |
|---|---|---|
| `GET` | `/api/health` | Health check |
| `GET` | `/api/audit/live` | WebSocket para auditoria en tiempo real |
| `GET` | `/api/audits` | Listar auditorias pasadas |
| `GET` | `/api/audits/:id` | Obtener detalle de auditoria |
| `DELETE` | `/api/audits/:id` | Eliminar auditoria |
| `GET` | `/api/audits/export` | Exportar todas las auditorias como JSON |
| `POST` | `/api/audits/import` | Importar auditorias desde JSON |
| `GET` | `/api/analyses` | Listar analisis (contrato xwa-sdk `Analysis`) |
| `GET` | `/api/analyses/:id` | Analisis + hallazgos |
| `DELETE` | `/api/analyses/:id` | Eliminar analisis |
| `GET` | `/api/analyses/:id/export?format=json\|csv` | Descargar analisis |

## Solucion de Problemas

### La conexion WebSocket falla
Asegurate de que el puerto sea accesible y que ningun firewall bloquee las actualizaciones WebSocket. Usa `RUST_LOG=debug` para ver los detalles de las peticiones.

### La auditoria no devuelve hallazgos
La auditoria analiza el HTML despues de formatearlo. Si la pagina esta vacia, detras de un login o bloquea bots, los resultados pueden estar vacios. Prueba con una pagina accesible publicamente.

### Error de compilacion
- Rust: asegura tener 1.81+ con `rustup update`
- Frontend: `cd frontend && npm ci` para instalar dependencias
- Compilacion limpia: `./clean.sh` y reintenta
