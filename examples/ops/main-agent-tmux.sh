#!/usr/bin/env bash
# EXAMPLE ONLY: explicitly launch the separate persistent Danus Web main host.
# Usage: bash examples/ops/main-agent-tmux.sh
# Then open http://127.0.0.1:${DANUS_MAIN_PORT:-8090}; choose this repo workspace
# and start a main session. No server or model is started merely by installation.
# This does not attach to, reconfigure or restart any existing operator GUI.
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
. "$HERE/../../scripts/env.sh"
[ "$#" -eq 0 ] || { echo 'usage: main-agent-tmux.sh (set DANUS_MAIN_PORT in config/danus.env)' >&2; exit 2; }
SESSION="${DANUS_MAIN_TMUX:-danus-main}"
command -v tmux >/dev/null || { echo 'need tmux on PATH' >&2; exit 1; }
if tmux has-session -t "$SESSION" 2>/dev/null; then
  echo "[$SESSION] already running; attach with tmux attach -t $SESSION"
  exit 0
fi
printf -v launch '%q' "$DANUS_ROOT/bin/danus-main"
tmux new-session -d -s "$SESSION" -c "$DANUS_ROOT" "$launch"
echo "[$SESSION] separate main host requested on 127.0.0.1:${DANUS_MAIN_PORT:-8090}; inspect tmux output for readiness"
