#!/bin/sh
# Container entrypoint: turn a credentials secret into a file, then run the agent.
# GOOGLE_CREDENTIALS_JSON_B64: base64 of a Google service-account key (or an authorized-user ADC file) for the GCP project
# that runs Gemini Live on Vertex AI. Set it as a LiveKit Cloud agent secret.
set -e
if [ -n "$GOOGLE_CREDENTIALS_JSON_B64" ] && [ -z "$GOOGLE_APPLICATION_CREDENTIALS" ]; then
  umask 077; echo "$GOOGLE_CREDENTIALS_JSON_B64" | base64 -d > /tmp/gcp_credentials.json
  export GOOGLE_APPLICATION_CREDENTIALS=/tmp/gcp_credentials.json
fi
exec python cloud_main.py "${@:-start}"
