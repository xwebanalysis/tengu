# =============================================================================
# Stage 1: Frontend (Angular 22 static build)
# =============================================================================
FROM node:24-slim AS frontend-builder

WORKDIR /app/frontend

COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci || npm install

COPY frontend/ .
RUN mkdir -p /out/static/browser \
    && (npx ng build --output-path=/out/static --configuration=production \
        || npx ng build --output-path=/out/static \
        || echo "Frontend build skipped (serving JSON status at /)")

# =============================================================================
# Stage 2: Python backend
# =============================================================================
FROM ghcr.io/astral-sh/uv:0.13.3 AS uv

FROM python:3.12-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

COPY --from=uv /uv /usr/local/bin/uv

RUN adduser --disabled-password --gecos "" tengu

WORKDIR /app

COPY backend ./backend
RUN cd backend && uv sync --frozen --no-dev

COPY --from=frontend-builder /out/static ./static

RUN mkdir -p /data && chown -R tengu:tengu /data /app

USER tengu

ENV PORT=8070 \
    STATIC_DIR=/app/static/browser \
    TENGU_DB_PATH=/data/tengu.db

EXPOSE 8070

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8070/api/health', timeout=3)"]

CMD ["/app/backend/.venv/bin/python", "-m", "tengu", "--host", "0.0.0.0", "--port", "8070"]
