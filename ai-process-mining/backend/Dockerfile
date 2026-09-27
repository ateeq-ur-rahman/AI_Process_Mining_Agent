# Build context: repository root (see docker-compose.yml)
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1
WORKDIR /app

COPY backend/requirements.txt ./requirements.txt
RUN pip install -r requirements.txt

COPY backend/ /app/
COPY data/sample_order_to_cash.csv /app/data/sample_order_to_cash.csv

RUN useradd --create-home --uid 1000 app \
    && mkdir -p /data/uploads && chown -R app:app /data/uploads
USER app

EXPOSE 8000
HEALTHCHECK --interval=15s --timeout=3s --retries=5 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/api/health')"

# One worker: engine results are cached in-process (recomputed from PostgreSQL on a miss).
CMD ["sh", "-c", "alembic upgrade head && uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers 1"]
