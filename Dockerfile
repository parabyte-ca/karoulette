# syntax=docker/dockerfile:1

# ---- Stage 1: build the React SPA
FROM node:22-alpine AS web
WORKDIR /web
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY frontend/ ./
RUN npm run build

# ---- Stage 2: Python runtime
FROM python:3.13-slim
ARG APP_UID=568
ARG APP_GID=568
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    DATA_PATH=/data \
    STATIC_DIR=/app/static \
    XDG_CACHE_HOME=/tmp/cache \
    FORWARDED_ALLOW_IPS=127.0.0.1
WORKDIR /app

COPY backend/requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY VERSION ./VERSION
COPY backend/app ./app
COPY backend/scripts ./scripts
COPY --from=web /web/dist ./static

# 568 is the TrueNAS "apps" user; override with --build-arg or compose "user:".
RUN groupadd -g ${APP_GID} apps 2>/dev/null || true \
 && useradd -u ${APP_UID} -g ${APP_GID} -M -d /app -s /usr/sbin/nologin apps 2>/dev/null || true \
 && mkdir -p /data && chown ${APP_UID}:${APP_GID} /data
USER ${APP_UID}:${APP_GID}
VOLUME ["/data"]
EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
  CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/api/health', timeout=4).status == 200 else 1)"

# Single worker on purpose: rotation timers and WebSocket rooms live in this process.
# X-Forwarded-For is only believed from FORWARDED_ALLOW_IPS (your reverse proxy or tunnel), never from anyone:
# otherwise a client could fake its address and slip past the login and search rate limits.
CMD ["uvicorn", "--factory", "app.main:create_app", "--host", "0.0.0.0", "--port", "8000", \
     "--proxy-headers", "--no-server-header"]
