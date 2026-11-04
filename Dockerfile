# One image, one process: FastAPI serves the built dashboard, the API and the
# WebSocket on a single origin, so the frontend's relative URLs work unchanged.
#
#   docker build -t cardio-twin .
#   docker run -p 8000:8000 cardio-twin      # then open http://localhost:8000

# ── Stage 1: build the dashboard ─────────────────────────────────────────────
# Vite 8 needs Node 20.19+ or 22.12+.
FROM node:22-slim AS frontend
WORKDIR /app/frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

# ── Stage 2: the backend, with the dashboard beside it ───────────────────────
FROM python:3.12-slim
WORKDIR /app

# Unbuffered so log lines reach the host's log viewer as they happen.  The
# twin's per-cycle echo is ~2 KB at 10 Hz per open tab; a hosted log has no
# use for it, and the in-memory log the API returns is unaffected.
ENV PYTHONUNBUFFERED=1 \
    CARDIOTWIN_ECHO_LOG=0

COPY backend/requirements.txt backend/requirements.txt
RUN pip install --no-cache-dir -r backend/requirements.txt

COPY backend/ backend/
COPY presets/ presets/
COPY --from=frontend /app/frontend/dist frontend/dist

WORKDIR /app/backend
EXPOSE 8000

# Hosts such as Render say which port to listen on through $PORT.
CMD ["sh", "-c", "exec uvicorn main:app --host 0.0.0.0 --port ${PORT:-8000} --proxy-headers --forwarded-allow-ips='*'"]
