FROM python:3.12-slim

ARG AGENT_NAME
ENV AGENT_NAME=${AGENT_NAME}

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
        ca-certificates \
    && rm -rf /var/lib/apt/lists/*

COPY agents/requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt

COPY shared /app/shared
COPY adapters /app/adapters
COPY agents /app/agents

ENV PYTHONPATH=/app
ENV ORCHESTRATOR_URL=http://orchestrator:8000

CMD python -m agents.${AGENT_NAME}.main
