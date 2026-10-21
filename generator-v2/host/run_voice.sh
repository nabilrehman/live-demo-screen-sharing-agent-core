#!/bin/bash
# usage: run_voice.sh <slug> <worker_port>   (inside the build sandbox) - starts the demo's LiveKit voice worker gen-<slug>
SLUG=$1; WP=${2:-8097}
set -a; . /vercel/gen/.lk.env; set +a          # LiveKit creds: loaded, never printed
export SITE_KNOWLEDGE=/vercel/gen/generator-v2/work/$SLUG/knowledge AGENT_NAME=gen-$SLUG BRAIN=grok WORKER_PORT=$WP
cd /vercel/agent && setsid nohup uv run python src/windcreek_agent.py start > /vercel/gen/agent-$SLUG.log 2>&1 < /dev/null &
