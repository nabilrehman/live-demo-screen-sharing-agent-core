#!/bin/sh
# Container entrypoint: turn the Google credentials secret into a file, then run the agent.
# GOOGLE_CREDENTIALS_JSON_B64: base64 of a service-account key (or an authorized-user ADC file) for the GCP project that
# runs Gemini Live on Vertex AI. Set it as a LiveKit Cloud agent secret. Not needed with GOOGLE_API_KEY (Gemini API key).
set -e
if [ -n "$GOOGLE_CREDENTIALS_JSON_B64" ] && [ -z "$GOOGLE_APPLICATION_CREDENTIALS" ]; then
  umask 077; echo "$GOOGLE_CREDENTIALS_JSON_B64" | base64 -d > /tmp/gcp_credentials.json
  export GOOGLE_APPLICATION_CREDENTIALS=/tmp/gcp_credentials.json
fi
exec python src/cloud_main.py "${@:-start}"
