#!/bin/bash
# (re)start the hosted controller on :8080 inside the build sandbox; safe to run on every new sandbox session
pkill -f "generator-v2/host/server.py" 2>/dev/null; sleep 1
set -a; . /vercel/gen/.lk.env; set +a
cd /vercel/gen/generator-v2 && setsid nohup /vercel/venv/bin/python host/server.py > /vercel/gen/host-server.log 2>&1 < /dev/null &
for i in $(seq 1 20); do curl -sf -o /dev/null http://localhost:8080/api/demos && { echo up; exit 0; }; sleep 1; done; echo "not up"; exit 1
