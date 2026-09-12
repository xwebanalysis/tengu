# =============================================================================
# Stage 1: Frontend (Angular 22 static build, optional)
# =============================================================================
FROM node:24-slim AS frontend-builder

WORKDIR /app/frontend

COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci || npm install

COPY frontend/ .
# Angular 17+ emits <out>/browser; keep the path stable even if the build fails
# so the runtime copy never breaks.
RUN mkdir -p /out/static/browser \
    && (npx ng build --output-path=/out/static --configuration=production \
        || npx ng build --output-path=/out/static \
        || echo "Frontend build skipped (serving JSON status at /)")

# =============================================================================
# Stage 2: Backend (Rust)
# =============================================================================
FROM rust:1.98-slim-bookworm AS backend-builder

RUN apt-get update && apt-get install -y --no-install-recommends \
    pkg-config \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Dependency cache layer: build with a stub main, then copy the real sources.
COPY Cargo.toml Cargo.lock build.rs ./
RUN mkdir -p src/api src/auditor src/storage \
    && echo 'fn main() {}' > src/main.rs \
    && cargo build --release --locked \
    && rm -rf src

COPY src ./src
RUN cargo build --release --locked

# =============================================================================
# Stage 3: Runtime (minimal)
# =============================================================================
FROM debian:bookworm-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

RUN adduser --disabled-password --gecos "" tengu

WORKDIR /app

COPY --from=backend-builder /app/target/release/tengu .
COPY --from=frontend-builder /out/static ./static

RUN mkdir -p /data && chown -R tengu:tengu /data /app

USER tengu

ENV PORT=8070 \
    STATIC_DIR=/app/static/browser \
    TENGU_DB_PATH=/data/tengu.db
EXPOSE 8070

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD ["bash", "-c", "exec 3<>/dev/tcp/127.0.0.1/8070"]

CMD ["./tengu"]
