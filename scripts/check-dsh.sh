#!/usr/bin/env bash
# Offline configuration and MCP initialize/list-tools only. No inference probe.
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
. "$HERE/env.sh"
exec "$DANUS_PY" "$HERE/check_dsh.py" "$@"
