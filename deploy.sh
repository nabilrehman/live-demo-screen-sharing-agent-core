#!/usr/bin/env bash
# Deploy this agent to LiveKit Cloud from your machine.
#   ./deploy.sh            first run creates the agent (writes livekit.toml), later runs deploy a new version
# Reads the agent's settings from .env.local and sends the ones listed in SENT as secrets (names are printed, never values).
set -euo pipefail; cd "$(dirname "$0")"
command -v lk >/dev/null || { echo "Install the LiveKit CLI: https://docs.livekit.io/home/cli/"; exit 1; }
[ -f .env.local ] || { echo "Copy .env.example to .env.local and fill it in first."; exit 1; }
PROJECT_FLAG=${LK_PROJECT:+--project $LK_PROJECT}

# Only these settings are sent: the ones src/ reads (avatar keys included). Not sent: LiveKit's URL/key/secret
# (injected), AGENT_NAME/WORKER_PORT (set in the Dockerfile), CHROME_PATH and the file paths below (local only).
SENT=(
  BRAIN GEMINI_LIVE_MODEL GEMINI_VOICE GEMINI_SILENCE_MS GEMINI_START_SENS GOOGLE_API_KEY GOOGLE_CLOUD_PROJECT
  GOOGLE_CLOUD_LOCATION MIN_RT_MODEL MIN_RT_VOICE
  JEV_OPENROUTER_API_KEY TYPESAFE_API_KEY JEV_MODEL JEV_CALL_TIMEOUT JEV_SETTLE_MS PLANNER_MODEL PLANNER_SCREEN_CHARS
  DEBRIEF_MODEL
  DEMO_START_URL TOUR_START_URL DEMO_PROJECT_URL FAAN_STORAGE_STATE_B64 FAAN_DEFAULT_MODE CLEAN_AT_START BLOCK_CLICKS
  ACT_RUN_MAX MISSED_TURN_S SETTLE_S SCREEN_TEXT_CHARS SCREEN_TO_MODEL_FPS SCREEN_W SCREEN_H SCREENCAST_NTH
  HOVER_S CURSOR_SPEED CURSOR_MS_A CURSOR_MS_B CURSOR_MS_MIN CURSOR_MS_MAX CURSOR_SETTLE_MS DEBUG_SHOTS
  VOICE_BRIDGE FLOOR_AUTO_HANDOVER WEBRTC_IP_POLICY MAX_JOBS_PER_WORKER JOB_MEMORY_WARN_MB LOG_URL LOG_SECRET
  AVATAR_PROVIDER AVATAR_NAME AVATAR_JOIN_TIMEOUT_S AVATAR_RESTARTS AVATAR_RESTART_BACKOFF_S LIVEKIT_PUBLIC_URL
  LEMONSLICE_IMAGE_URL LEMONSLICE_AGENT_ID LEMONSLICE_PROMPT LEMONSLICE_IDLE_PROMPT LEMONSLICE_IDLE_TIMEOUT
  ANAM_API_KEY ANAM_AVATAR_ID ANAM_AVATAR_MODEL ANAM_VIDEO_W ANAM_VIDEO_H ANAM_API_URL ANAM_AI_DISCLOSURE
  BEY_API_KEY BEY_AVATAR_ID TAVUS_API_KEY TAVUS_REPLICA_ID TAVUS_PERSONA_ID
  GOOGLE_CREDENTIALS_JSON_B64
)
secrets=$(mktemp); trap 'rm -f "$secrets"' EXIT; chmod 600 "$secrets"
for name in "${SENT[@]}"; do
  grep -E "^${name}=" .env.local | tail -n 1 >> "$secrets" || true
done
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
