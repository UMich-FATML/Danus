#!/usr/bin/env bash
# Read-only non-billable checks. Does not initialize DSH, start MCP, or infer.
set -uo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
. "$HERE/env.sh"
export PYTHONDONTWRITEBYTECODE=1
failures=0
ok(){ printf 'ok   %s\n' "$1"; }
no(){ printf 'FAIL %s\n' "$1"; failures=$((failures+1)); }
wn(){ printf 'warn %s\n' "$1"; }
echo '== Danus doctor (no model requests) =='
[ -f "$DANUS_ROOT/config/danus.env" ] && ok 'deployment env present' || wn 'config/danus.env absent'
[ -f "$DANUS_ROOT/config/dsh.env" ] && ok 'API env present' || wn 'config/dsh.env absent; explicit inherited API env may be used'
if [ -x "$DANUS_PY" ]; then
  "$DANUS_PY" -c 'import danus; from danus._mcp import FastMCP; import fastapi, uvicorn' >/dev/null 2>&1 \
    && ok 'Python runtime imports' || no 'Python dependencies missing; run pixi install'
  PYTHONDONTWRITEBYTECODE=1 "$DANUS_PY" "$HERE/check_dsh.py" --config-only \
    && ok 'provider/site structural validation' || no 'provider/site config invalid'
else
  no 'project Python absent; run scripts/bootstrap.sh with pixi'
fi
version="$("$DANUS_ROOT/bin/dsh" --version 2>/dev/null)"
[ "$version" = '0.2.1-rc.5' ] && ok "DSH $version" || no 'DSH executable missing or not pinned 0.2.1-rc.5'
case "$(danus_verify_health)" in
  ours) ok "verify service :$VERIFY_PORT is this deployment" ;;
  foreign) no "verify :$VERIFY_PORT belongs to another process" ;;
  *) wn 'verify service not running; doctor does not start it' ;;
esac
command -v "${TEX_ENGINE:-pdflatex}" >/dev/null 2>&1 || wn 'TeX unavailable (optional PDF rendering)'
echo 'Model authentication, provider reachability, model availability and billing were NOT tested.'
echo 'Use scripts/check-dsh.sh for offline MCP handshakes; it never calls advertised tools.'
exit "$((failures > 0))"
