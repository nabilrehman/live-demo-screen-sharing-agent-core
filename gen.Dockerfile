# syntax=docker/dockerfile:1
# The shared hosted agent for AI-generated demos (src/windcreek_agent.py + src/gen_pack.py): one LiveKit Cloud
# deployment serves every demo; each call loads its demo's knowledge pack from Vercel Blob (see gen_pack.py).
# No secrets are baked in: credentials come from LiveKit Cloud agent secrets.
#   generator-v2/host/deploy_agent.sh builds and deploys it (lk agent create/deploy, project nabil-demo).
ARG PYTHON_VERSION=3.13
FROM ghcr.io/astral-sh/uv:python${PYTHON_VERSION}-bookworm-slim AS base
ENV PYTHONUNBUFFERED=1 \
    UV_COMPILE_BYTECODE=1 \
    HF_HOME=/app/.cache/huggingface

# --- Build stage: dependencies from uv.lock, then the app ---
FROM base AS build
RUN apt-get update && apt-get install -y gcc g++ python3-dev && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY pyproject.toml uv.lock ./
RUN mkdir -p src && uv sync --locked --no-dev --no-install-project
RUN uv run --no-sync --module livekit.agents download-files
COPY . .
RUN uv sync --locked --no-dev

# --- Production stage ---
FROM base
ENV PATH="/app/.venv/bin:$PATH" AGENT_NAME=demo-gen BRAIN=grok VOICE_REC=0 WORKER_PORT=8081
ARG UID=10001
RUN adduser --disabled-password --gecos "" --home /app --shell /sbin/nologin --uid "${UID}" appuser
COPY --from=build --chown=appuser:appuser /app /app
WORKDIR /app
USER appuser
CMD ["python", "src/windcreek_agent.py", "start"]
