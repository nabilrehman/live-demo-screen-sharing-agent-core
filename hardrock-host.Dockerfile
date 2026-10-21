# syntax=docker/dockerfile:1
# LiveKit, the host companion in the Hard Rock Host Companion demo (Hard Rock v2, src/hardrock_host_agent.py): voice only, no browser, so no Chromium or ffmpeg.
# No secrets are baked in: credentials come from LiveKit Cloud agent secrets.
#   docker build -f hardrock-host.Dockerfile -t live-demo-hardrock-host .
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
ENV PATH="/app/.venv/bin:$PATH" AGENT_NAME=live-demo-hardrock-host-grok BRAIN=grok MIN_RT_VOICE=eve SITE_KNOWLEDGE=/app/knowledge/hardrock-host WORKER_PORT=8081
ARG UID=10001
RUN adduser --disabled-password --gecos "" --home /app --shell /sbin/nologin --uid "${UID}" appuser
COPY --from=build --chown=appuser:appuser /app /app
WORKDIR /app
USER appuser
CMD ["python", "src/hardrock_host_agent.py", "start"]
