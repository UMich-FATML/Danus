#!/usr/bin/env bash
# Never source deployment settings from the development check entry point.
set -euo pipefail
ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
exec python "$ROOT/scripts/check.py" "$@"
