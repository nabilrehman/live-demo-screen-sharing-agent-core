# syntax=docker/dockerfile:1
# Live demo agent: Gemini Live (sees the shared screen as video) + Jev (picks every click) + headless Chromium, on LiveKit Agents.
# Optional Anam avatar. No secrets baked in: credentials come from LiveKit Cloud agent secrets.
FROM ghcr.io/astral-sh/uv:python3.13-bookworm-slim
ENV PYTHONUNBUFFERED=1 UV_COMPILE_BYTECODE=1 UV_SYSTEM_PYTHON=1 UV_NO_CACHE=1 \
    PLAYWRIGHT_BROWSERS_PATH=/ms-playwright AGENT_NAME=live-demo-lean WORKER_PORT=8081
WORKDIR /app
# ffmpeg: demo_agent/sesslog.py records screen.mp4 for every session
RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg ca-certificates && rm -rf /var/lib/apt/lists/*
COPY requirements.cloud.txt .
RUN uv pip install --system -r requirements.cloud.txt \
 && python -m playwright install --with-deps chromium \
 && rm -rf /var/lib/apt/lists/*
RUN useradd -m -u 10001 agent && chmod -R a+rx /ms-playwright
USER agent
RUN python -m livekit.agents download-files || true
USER root
COPY --chown=agent:agent agent.py cloud_main.py entrypoint.sh ./
COPY --chown=agent:agent demo_agent ./demo_agent
COPY --chown=agent:agent knowledge ./knowledge
RUN mkdir -p sessions && chown agent:agent sessions
USER agent
ENTRYPOINT ["./entrypoint.sh"]
CMD ["start"]
