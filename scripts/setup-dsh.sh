#!/usr/bin/env bash
# Write a provider patch only; no model call, install, login, or GUI mutation.
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
. "$HERE/env.sh"
[ "$#" -eq 0 ] || { echo 'usage: bash scripts/setup-dsh.sh' >&2; exit 2; }
exec "$DANUS_PY" "$HERE/dsh_config.py"
