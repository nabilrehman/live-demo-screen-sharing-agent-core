#!/bin/bash
# Build and deploy the shared LiveKit Cloud agent for generated demos (agent name demo-gen, gen.Dockerfile).
#   generator-v2/host/deploy_agent.sh     first run creates the agent (livekit.toml is kept in the build folder), later runs
#                                         deploy a new version. Only needed when the agent's CODE changes: demos, edits
#                                         and deletes are data (Vercel Blob), not deployments.
# Env: LK_PROJECT (default nabil-demo), DEMO_GEN_AGENT_DIR (build folder, default ~/Downloads/demo-gen-agent),
#      DEMO_GEN_BLOB_ENV (default ~/Downloads/livekit-ops/demo-gen-blob.env: GEN_PACK_PREFIX; never printed).
set -euo pipefail
REPO=$(cd "$(dirname "$0")/../.." && pwd)
OUT=${DEMO_GEN_AGENT_DIR:-$HOME/Downloads/demo-gen-agent}
PROJECT=${LK_PROJECT:-nabil-demo}
BLOB_ENV=${DEMO_GEN_BLOB_ENV:-$HOME/Downloads/livekit-ops/demo-gen-blob.env}
STORE=${GEN_BLOB_BASE:-https://88ev414hvkdji1jn.public.blob.vercel-storage.com}

mkdir -p "$OUT"
rsync -a --delete --exclude livekit.toml --exclude '__pycache__' "$REPO/src" "$REPO/knowledge" "$REPO/pyproject.toml" "$REPO/uv.lock" "$REPO/.dockerignore" "$OUT/"
cp "$REPO/gen.Dockerfile" "$OUT/Dockerfile"

secrets=$(mktemp); trap 'rm -f "$secrets"' EXIT; chmod 600 "$secrets"
echo "GEN_PACK_BASE=$STORE/$(grep -E '^GEN_PACK_PREFIX=' "$BLOB_ENV" | cut -d= -f2)" > "$secrets"
echo "Secrets sent: $(cut -d= -f1 "$secrets" | tr '\n' ' ')"

cd "$OUT"
if grep -q "^[[:space:]]*id[[:space:]]*=" livekit.toml 2>/dev/null; then
  lk agent update-secrets --project "$PROJECT" --secrets-file "$secrets" -y
  lk agent deploy --project "$PROJECT" -y .
else
  lk agent create --project "$PROJECT" --region us-east --secrets-file "$secrets" -y .
fi
lk agent status --project "$PROJECT"
