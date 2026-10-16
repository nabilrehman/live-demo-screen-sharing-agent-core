# syntax=docker/dockerfile:1
# The live demo agent on LiveKit Cloud: the agent worker plus headless Chromium (Playwright) and ffmpeg.
# No secrets are baked in: credentials come from LiveKit Cloud agent secrets.
ARG PYTHON_VERSION=3.13
FROM ghcr.io/astral-sh/uv:python${PYTHON_VERSION}-bookworm-slim AS base
ENV PYTHONUNBUFFERED=1 \
    UV_COMPILE_BYTECODE=1 \
    HF_HOME=/app/.cache/huggingface \
    PLAYWRIGHT_BROWSERS_PATH=/ms-playwright

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
ENV PATH="/app/.venv/bin:$PATH" AGENT_NAME=live-demo-lean WORKER_PORT=8081
# ffmpeg records sessions/<room>/screen.mp4; Chromium and its system libraries for the shared browser
RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg ca-certificates && rm -rf /var/lib/apt/lists/*
ARG UID=10001
RUN adduser --disabled-password --gecos "" --home /app --shell /sbin/nologin --uid "${UID}" appuser
COPY --from=build --chown=appuser:appuser /app /app
WORKDIR /app
RUN python -m playwright install --with-deps chromium && rm -rf /var/lib/apt/lists/* && chmod -R a+rx /ms-playwright
RUN mkdir -p sessions && chown appuser:appuser sessions
USER appuser
ENTRYPOINT ["./entrypoint.sh"]
CMD ["start"]
