FROM python:3.12-slim

WORKDIR /app

# System deps minimal
RUN apt-get update && apt-get install -y --no-install-recommends \
        curl ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Install Python deps first for layer cache
COPY orchestrator/requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt

# Copy code (note: monorepo, so we copy everything the orchestrator imports)
COPY shared /app/shared
COPY adapters /app/adapters
COPY orchestrator /app/orchestrator
COPY frontend /app/frontend

ENV PYTHONPATH=/app
ENV ORCHESTRATOR_PORT=8000

EXPOSE 8000

HEALTHCHECK --interval=15s --timeout=3s --retries=3 \
    CMD curl -fsS http://localhost:8000/health || exit 1

CMD ["uvicorn", "orchestrator.app.main:app", "--host", "0.0.0.0", "--port", "8000"]
