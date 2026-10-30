#!/usr/bin/env bash
# Optional project-local LaTeX toolchain; installs via pixi, never curl | sh.
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
. "$HERE/env.sh"
command -v pixi >/dev/null || { echo 'Install pixi first: https://pixi.sh' >&2; exit 1; }
pixi add --manifest-path "$DANUS_ROOT/pixi.toml" tectonic
echo 'Tectonic added to this project. Set TEX_ENGINE=tectonic in config/danus.env.'
