#!/bin/bash
# (re)start the hosted controller on :8080 inside the build sandbox; safe to run on every new sandbox session.
# Runs host/product_main.py (server.py + product layer) when present, else plain host/server.py.
# Builds are detached (own session), so restarting the controller never interrupts a running build.
# Kill ONLY the controller process. Anchored on the start of the command line: a bare "generator-v2/host/server.py"
# pattern also matches running `claude -p` builds (their prompt text mentions that path) and kills them.
pkill -f '^/vercel/venv/bin/python host/(server|product_main)\.py$' 2>/dev/null; sleep 1
set -a; . /vercel/gen/.lk.env; [ -f /vercel/gen/.blob.env ] && . /vercel/gen/.blob.env; set +a   # LiveKit + Blob (publish.py)
cd /vercel/gen/generator-v2
ENTRY=host/server.py; [ -f host/product_main.py ] && [ -f host/product.py ] && ENTRY=host/product_main.py
setsid nohup /vercel/venv/bin/python $ENTRY > /vercel/gen/host-server.log 2>&1 < /dev/null &
for i in $(seq 1 20); do curl -sf -o /dev/null http://localhost:8080/api/demos && { echo "up ($ENTRY)"; exit 0; }; sleep 1; done; echo "not up"; exit 1
