#!/usr/bin/env bash
# Resident verifier HTTP service; each request launches isolated headless DSH.
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
. "$HERE/env.sh"
mkdir -p "$DANUS_RUNTIME/logs" "$VERIFIER_RESULTS_DIR"
export DANUS_DSH_TIMEOUT_SECONDS="${DANUS_DSH_TIMEOUT_SECONDS:-900}"
export VERIFY_HOST="${VERIFY_HOST:-127.0.0.1}" VERIFY_PORT
echo "[start-verify] port=$VERIFY_PORT model=${DANUS_VERIFY_MODEL:-$DANUS_MAIN_MODEL}/${DANUS_VERIFY_EFFORT:-$DANUS_MAIN_EFFORT} (isolated DSH)"
exec "$DANUS_PY" -m danus.verify
