#!/usr/bin/env bash
# Deploy this agent to LiveKit Cloud from your machine.
#   ./deploy.sh            first run creates the agent (writes livekit.toml), later runs deploy a new version
# Reads .env.local for the agent's secrets. LiveKit injects its own URL/key/secret into the cloud agent, so those are not sent.
set -euo pipefail; cd "$(dirname "$0")"
command -v lk >/dev/null || { echo "Install the LiveKit CLI: https://docs.livekit.io/home/cli/"; exit 1; }
[ -f .env.local ] || { echo "Copy .env.example to .env.local and fill it in first."; exit 1; }
PROJECT_FLAG=${LK_PROJECT:+--project $LK_PROJECT}

secrets=$(mktemp); trap 'rm -f "$secrets"' EXIT; chmod 600 "$secrets"
grep -vE '^\s*(#|$)|^LIVEKIT_(URL|API_KEY|API_SECRET)=|^(FAAN_STORAGE_STATE|GOOGLE_APPLICATION_CREDENTIALS)=' .env.local > "$secrets" || true
# files the agent needs, sent as base64 secrets
login_file=$(grep -E '^FAAN_STORAGE_STATE=' .env.local | cut -d= -f2- || true)
[ -n "$login_file" ] && [ -f "$login_file" ] && echo "FAAN_STORAGE_STATE_B64=$(base64 < "$login_file" | tr -d '\n')" >> "$secrets"
gcp_file=${GOOGLE_APPLICATION_CREDENTIALS:-$HOME/.config/gcloud/application_default_credentials.json}
if ! grep -q '^GOOGLE_CREDENTIALS_JSON_B64=' "$secrets" && [ -f "$gcp_file" ]; then
  echo "GOOGLE_CREDENTIALS_JSON_B64=$(base64 < "$gcp_file" | tr -d '\n')" >> "$secrets"
fi
echo "Secrets sent: $(cut -d= -f1 "$secrets" | tr '\n' ' ')"

if grep -q "^[[:space:]]*id[[:space:]]*=" livekit.toml 2>/dev/null; then
  lk agent deploy $PROJECT_FLAG --secrets-file "$secrets" .
else
  lk agent create $PROJECT_FLAG --secrets-file "$secrets" .
fi
lk agent status $PROJECT_FLAG
