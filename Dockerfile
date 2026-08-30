# One image, one Cloud Run service: the API and the built front end together.
#
# Two services would need CORS, a second URL and a proxy rule that only exists in Vite's config,
# and the front end talks to the API on same-origin relative paths anyway. `main.py` mounts
# `web/dist` last, so every API route still wins and unknown paths fall through to index.html.

# --- stage 1: build the front end ------------------------------------------------------------
FROM node:22-slim AS web
WORKDIR /web
# Copy manifests first so `npm ci` is cached until a dependency actually changes.
COPY web/package.json web/package-lock.json ./
RUN npm ci
COPY web/ ./
RUN npm run build

# --- stage 2: the service ---------------------------------------------------------------------
FROM python:3.13-slim AS runtime

# Fail fast and log straight through; Cloud Run collects stdout.
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /srv

COPY backend/requirements.txt ./backend/requirements.txt
RUN pip install --no-cache-dir -r backend/requirements.txt

COPY backend/ ./backend/
COPY fixtures/ ./fixtures/
COPY --from=web /web/dist ./web/dist

# Not root. Cloud Run does not require it; running as root anyway is a finding waiting to happen
# in a project whose whole subject is enforced least privilege.
RUN useradd --create-home --uid 10001 interdict && chown -R interdict:interdict /srv
USER interdict

# Cloud Run injects PORT and expects the container to honour it.
ENV PORT=8080
EXPOSE 8080

# `sh -c` so ${PORT} expands. One worker on purpose: the demo control plane holds in-flight case
# tasks and the effects ledger in process memory under PLATFORM_BACKEND=local, so a second worker
# would answer requests from a process that cannot see the first one's cases. Set
# PLATFORM_BACKEND=geap to put that state in Firestore before scaling past one.
CMD ["sh", "-c", "cd backend && exec python -m uvicorn app.main:app --host 0.0.0.0 --port ${PORT}"]
