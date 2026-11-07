# Night Shift: one container. Stage 1 builds the React app; stage 2 serves it + the API with FastAPI.

# ---- stage 1: frontend -------------------------------------------------------
FROM node:24-slim AS web
WORKDIR /web
COPY web/package.json web/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY web/ ./
RUN npm run build

# ---- stage 2: API + static files -------------------------------------------------
FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PORT=8000
WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY api.py auth.py config.py data.py engine.py llm.py margins.py options.py review.py store.py ./
COPY demo-data/ ./demo-data/
COPY --from=web /web/dist ./web/dist

# Run as a non-root user; /app stays writable for the small AI reading cache.
RUN useradd --create-home --uid 10001 nightshift && chown -R nightshift /app
USER nightshift

EXPOSE 8000
# Render sets $PORT. --proxy-headers so client IPs (rate limit) come from X-Forwarded-For.
CMD ["sh", "-c", "exec uvicorn api:app --host 0.0.0.0 --port ${PORT:-8000} --proxy-headers --forwarded-allow-ips='*'"]
