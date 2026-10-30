#!/usr/bin/env bash
# Provision project dependencies with pixi, never change a global DSH/GUI install.
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
. "$HERE/env.sh"
command -v pixi >/dev/null || { echo 'Install pixi first: https://pixi.sh' >&2; exit 1; }
pixi install --manifest-path "$DANUS_ROOT/pixi.toml"
DANUS_PY="$DANUS_ROOT/.pixi/envs/default/bin/python"
"$DANUS_PY" -c 'import danus; from danus._mcp import FastMCP; import fastapi, uvicorn'
version="$("$DANUS_ROOT/bin/dsh" --version)"
[ "$version" = '0.2.1-rc.5' ] || { echo "Unsupported DSH version: $version; expected 0.2.1-rc.5" >&2; exit 1; }
echo "Project pixi environment ready; existing DSH $version verified. No model requests made."
echo 'Fill config/dsh.env and config/danus.env, then run scripts/setup-dsh.sh and scripts/check-dsh.sh.'
echo 'Optional human-summary JS assets: pixi run npm --prefix .agents/skills/human-summary install --no-fund --no-audit'
