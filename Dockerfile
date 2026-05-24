FROM python:3.11-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    curl \
    unzip \
    && rm -rf /var/lib/apt/lists/*

# yt-dlp needs a JS runtime for YouTube extraction on server IPs (Cloud Run).
RUN curl -fsSL https://deno.land/install.sh | DENO_INSTALL=/usr/local sh -s -- -q

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Memvid SDK (Python); video ingest still needs memvid CLI on PATH in production images.
# Optional: build memvid-cli with Whisper in a multi-stage image — see README ingest section.
RUN pip install --no-cache-dir memvid-sdk \
    && (memvid models install whisper-small 2>/dev/null || true)

COPY app ./app
COPY config ./config
COPY alembic ./alembic
COPY alembic.ini .
COPY scripts ./scripts

RUN mkdir -p data/jobs data/results

ENV HOST=0.0.0.0
ENV PORT=8000
ENV PYTHONUNBUFFERED=1
ENV PYTHONPATH=/app

EXPOSE 8000

CMD ["sh", "-c", "exec uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
