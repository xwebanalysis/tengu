#!/usr/bin/env bash
set -e

# Prefer the mise-managed Node 24 LTS for Angular tooling (system Node may be unsupported)
if [ -d "$HOME/.local/share/mise/installs/node/24/bin" ]; then
    case ":$PATH:" in
        *":$HOME/.local/share/mise/installs/node/24/bin:"*) ;;
        *) export PATH="$HOME/.local/share/mise/installs/node/24/bin:$PATH" ;;
    esac
fi

readonly GRN='\033[0;32m'
readonly BLU='\033[0;34m'
readonly YLW='\033[1;33m'
readonly RED='\033[0;31m'
readonly CYN='\033[0;36m'
readonly NC='\033[0m'

log()  { echo -e "${GRN}[tengu]${NC} $1"; }
info() { echo -e "${BLU}[info]${NC} $1"; }
warn() { echo -e "${YLW}[warn]${NC} $1"; }
err()  { echo -e "${RED}[err]${NC} $1"; }

PROJECT_ROOT="$(cd "$(dirname "$0")" && pwd)"
RUST_PID=""

# Defaults (XWA standard port for tengu)
: "${PORT:=8070}"
: "${TENGU_DB_PATH:=$PROJECT_ROOT/tengu.db}"
: "${RUST_LOG:=tengu=info,tower_http=info}"

cleanup() {
    echo ""
    warn "Shutting down..."
    if [ -n "$RUST_PID" ]; then
        kill "$RUST_PID" 2>/dev/null || true
        wait "$RUST_PID" 2>/dev/null || true
    fi
    if command -v docker &>/dev/null; then
        local running
        running=$(docker ps --filter "name=tengu" -q 2>/dev/null)
        if [ -n "$running" ]; then
            docker stop $running 2>/dev/null || true
        fi
    fi
    info "Bye"
    exit 0
}

setup_node_path() {
    # Keep the Angular-compatible Node 24 from mise first on PATH when present.
    local mise_node="$HOME/.local/share/mise/installs/node/24/bin"
    if [ -d "$mise_node" ]; then
        export PATH="$mise_node:$PATH"
    fi
}

check_deps() {
    if ! command -v cargo &>/dev/null; then
        err "Rust (cargo) not found. Install: https://rustup.rs"
        exit 1
    fi
}

has_node() {
    command -v node &>/dev/null
}

detect_static() {
    local candidate
    for candidate in \
        "$PROJECT_ROOT/static/browser" \
        "$PROJECT_ROOT/frontend/dist/tengu/browser" \
        "$PROJECT_ROOT/frontend/dist/browser"; do
        if [ -d "$candidate" ]; then
            echo "$candidate"
            return 0
        fi
    done
    echo "$PROJECT_ROOT/static/browser"
}

build_frontend() {
    setup_node_path
    if ! has_node; then
        warn "Node.js not found (mise node 24 or system node). Skipping frontend build."
        return 1
    fi
    if [ ! -d "frontend/node_modules" ]; then
        info "Installing frontend dependencies (npm ci)..."
        if ! (cd frontend && npm ci); then
            warn "npm ci failed; falling back to npm install"
            (cd frontend && npm install) || { warn "npm install failed"; return 1; }
        fi
    fi
    info "Building frontend (Node $(node -v))..."
    if (cd frontend && npx ng build --output-path="../static"); then
        info "Frontend built successfully"
    else
        warn "Frontend build had issues"
        return 1
    fi
}

wait_for_server() {
    local tries=0
    local max=180
    while [ $tries -lt $max ]; do
        if curl -sf "http://localhost:${PORT}/api/health" > /dev/null 2>&1; then
            return 0
        fi
        if [ $tries -eq 5 ]; then
            info "Waiting for server to be ready (compiling dependencies)..."
        fi
        if [ $((tries % 15)) -eq 0 ] && [ $tries -gt 0 ]; then
            info "Still waiting... (${tries}s)"
        fi
        sleep 1
        tries=$((tries + 1))
    done
    return 1
}

free_port() {
    if command -v fuser &>/dev/null; then
        fuser -k "${PORT}/tcp" 2>/dev/null || true
    elif command -v lsof &>/dev/null; then
        local pid
        pid=$(lsof -t -i ":$PORT" 2>/dev/null) && kill "$pid" 2>/dev/null || true
    fi
    sleep 1
}

start_server() {
    free_port
    local static_dir
    static_dir="$(detect_static)"
    if [ ! -f "$static_dir/index.html" ]; then
        warn "No prebuilt frontend at $static_dir — serving API only (GET / returns JSON status)"
    fi

    log "Starting Tengu on http://localhost:${PORT} (SQLite: ${TENGU_DB_PATH})"
    PORT="$PORT" \
    STATIC_DIR="$static_dir" \
    TENGU_DB_PATH="$TENGU_DB_PATH" \
    RUST_LOG="$RUST_LOG" \
    cargo run --release &
    RUST_PID=$!

    if wait_for_server; then
        log "Server ready"
    else
        err "Timed out waiting for server"
        kill "$RUST_PID" 2>/dev/null || true
        exit 1
    fi
}

print_urls() {
    info "───────────────────────────────────────────"
    info " Tengu is running on http://localhost:${PORT}"
    info " Health: http://localhost:${PORT}/api/health"
    info " WebSocket: ws://localhost:${PORT}/api/audit/live?url=<target>"
    info " SQLite: ${TENGU_DB_PATH}"
    info "───────────────────────────────────────────"
}

show_help() {
    cat <<EOF
${CYN}tengu — web quality auditor${NC}

${BLU}USAGE${NC}
  ./tengu.sh [command] [options]

${BLU}COMMANDS${NC}
  local (default)   Start native server with SQLite on :8070 (prebuilt frontend if present)
  docker            Start via docker-compose :8070 (persistent volume)
  build             Build frontend only, do not start server
  export [file]     Start server and export audits to ./exports/
  import <file>     Start server and import audits from file
  clean             Run ./clean.sh

${BLU}OPTIONS${NC}
  --rm        With docker: ephemeral container (removed on stop)
  -b          Force frontend rebuild before starting
  -h, --help  Show this help

${BLU}ENVIRONMENT${NC}
  PORT                 HTTP port (default 8070)
  TENGU_DB_PATH        SQLite file (default <repo>/tengu.db)
  TENGU_MAX_HISTORY    Retention limit (default 100)
  RUST_LOG             Log filter (default tengu=info,tower_http=info)

${BLU}EXAMPLES${NC}
  ./tengu.sh                        Start local (SQLite) at http://localhost:8070
  ./tengu.sh local                  Same as above
  ./tengu.sh docker                 Start with Docker Compose
  ./tengu.sh docker --rm            Ephemeral Docker
  ./tengu.sh build                  Build frontend only
  ./tengu.sh export                 Export audits (saved to exports/)
  ./tengu.sh export res.json        Export audits to exports/res.json
  ./tengu.sh import res.json        Import audits from exports/res.json
EOF
    exit 0
}

# --- Parse arguments ---

COMMAND=""
EPHEMERAL=false
FORCE_BUILD=false
ACTION_FILE=""

while [[ $# -gt 0 ]]; do
    case "$1" in
        local)  COMMAND="local"; shift ;;
        docker) COMMAND="docker"; shift ;;
        build)  COMMAND="build"; shift ;;
        export) COMMAND="export"; shift ;;
        import) COMMAND="import"; shift ;;
        clean)  COMMAND="clean"; shift ;;
        --rm)   EPHEMERAL=true; shift ;;
        -b)     FORCE_BUILD=true; shift ;;
        --help|-h) show_help ;;
        *)
            # If we already have a command, treat as its argument
            if [ -n "$COMMAND" ]; then
                case "$COMMAND" in
                    export|import)
                        ACTION_FILE="$1"; shift ;;
                    *)
                        err "Unknown option: $1"; exit 1 ;;
                esac
            else
                err "Unknown option: $1"; exit 1
            fi
            ;;
    esac
done

trap cleanup SIGINT SIGTERM

# --- Command dispatch ---

case "$COMMAND" in
    docker)
        if [ ! -f "$PROJECT_ROOT/docker-compose.yml" ]; then
            err "docker-compose.yml not found"
            exit 1
        fi
        if ! command -v docker &>/dev/null; then
            err "Docker not found. Install Docker or use './tengu.sh local'."
            exit 1
        fi
        log "Launching via docker-compose on http://localhost:${PORT}..."
        if [ "$EPHEMERAL" = true ]; then
            (cd "$PROJECT_ROOT" && docker compose up --build --rm)
        else
            (cd "$PROJECT_ROOT" && docker compose up --build)
        fi
        exit 0
        ;;

    build)
        cd "$PROJECT_ROOT"
        setup_node_path
        check_deps
        build_frontend
        log "Build done"
        exit 0
        ;;

    clean)
        exec "$PROJECT_ROOT/clean.sh"
        ;;

    export)
        cd "$PROJECT_ROOT"
        check_deps
        [ "$FORCE_BUILD" = true ] && build_frontend || true

        start_server

        mkdir -p exports
        if [ -z "$ACTION_FILE" ]; then
            ACTION_FILE="exports/tengu-export-$(date +%Y%m%d-%H%M%S).json"
        else
            ACTION_FILE="${ACTION_FILE#./}"
            ACTION_FILE="${ACTION_FILE#exports/}"
            ACTION_FILE="exports/$ACTION_FILE"
        fi

        info "Exporting audits to $ACTION_FILE ..."
        if curl -sf "http://localhost:${PORT}/api/audits/export" -o "$ACTION_FILE"; then
            info "Exported: $ACTION_FILE"
        else
            err "Export failed"
        fi

        print_urls
        wait "$RUST_PID"
        ;;

    import)
        cd "$PROJECT_ROOT"
        if [ -z "$ACTION_FILE" ]; then
            err "Uso: ./tengu.sh import <archivo>"
            exit 1
        fi
        if [ ! -f "$ACTION_FILE" ]; then
            err "File not found: $ACTION_FILE"
            exit 1
        fi

        check_deps
        [ "$FORCE_BUILD" = true ] && build_frontend || true

        start_server

        info "Importing audits from $ACTION_FILE ..."
        if curl -sf -X POST "http://localhost:${PORT}/api/audits/import" \
            -H "Content-Type: application/json" \
            -d @"$ACTION_FILE"; then
            info "Import completed"
        else
            err "Import failed"
        fi

        print_urls
        wait "$RUST_PID"
        ;;

    ""|local)
        cd "$PROJECT_ROOT"
        check_deps
        if [ "$FORCE_BUILD" = true ]; then
            build_frontend
        fi

        start_server
        print_urls
        echo ""

        wait "$RUST_PID"
        ;;

    *)
        err "Comando desconocido: $COMMAND"
        exit 1
        ;;
esac
