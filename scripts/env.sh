#!/usr/bin/env bash
# =============================================================================
# Danus environment — source this in any shell that talks to the system.
#
#   source <repo>/scripts/env.sh
#
# Sources explicit local config, then uses the pixi environment and isolated
# Danus-owned DSH homes. Never borrows the operator's running GUI configuration.
# =============================================================================

# Managed launchers explicitly own fresh homes; preserve them through config reload.
_danus_isolated_home=""; _danus_isolated_agents=""
if [ "${DANUS_DSH_ISOLATED:-0}" = 1 ]; then
  _danus_isolated_home="${DSH_HOME:?isolated launcher requires DSH_HOME}"
  _danus_isolated_agents="${DSH_AGENTS_HOME:?isolated launcher requires DSH_AGENTS_HOME}"
  case "$_danus_isolated_home:$_danus_isolated_agents" in /*:/*) ;; *) echo 'isolated DSH homes must be absolute' >&2; return 2 2>/dev/null || exit 2;; esac
fi

# Self-locate the repo root (this file lives at <repo>/scripts/env.sh).
DANUS_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")/.." && pwd)"
export DANUS_ROOT

# 0) explicit DSH API environment; secrets stay in gitignored config/*.env.
if [ "${DANUS_DSH_ISOLATED:-0}" != 1 ] && [ -f "$DANUS_ROOT/config/dsh.env" ]; then
  set -a; . "$DANUS_ROOT/config/dsh.env"; set +a
fi

# 1) user config (accounts / models / ports / toggles)
if [ "${DANUS_DSH_ISOLATED:-0}" != 1 ] && [ -f "$DANUS_ROOT/config/danus.env" ]; then
  set -a; . "$DANUS_ROOT/config/danus.env"; set +a
fi

# Legacy runtime/runtime.env is intentionally no longer sourced: it may carry
# stale interpreter or removed-runtime paths. Pixi and explicit config own paths.
# Isolated children skip ALL config reloads and inherit the launcher's resolved env.

# 3) defaults for anything still unset
export DANUS_RUNTIME="${DANUS_RUNTIME:-$DANUS_ROOT/runtime}"
export DANUS_AGENTS_ROOT="${DANUS_AGENTS_ROOT:-$DANUS_RUNTIME/projects}"
export VERIFIER_RESULTS_DIR="${VERIFIER_RESULTS_DIR:-$DANUS_RUNTIME/verify-runs}"
# Deliberately ignore inherited DSH_HOME/DSH_AGENTS_HOME from the current GUI.
export DSH_HOME="${DANUS_DSH_HOME:-$DANUS_RUNTIME/dsh-home}"
export DSH_AGENTS_HOME="${DANUS_DSH_AGENTS_HOME:-$DANUS_RUNTIME/dsh-agents}"
if [ -n "$_danus_isolated_home" ]; then
  export DSH_HOME="$_danus_isolated_home" DSH_AGENTS_HOME="$_danus_isolated_agents"
  export DANUS_DSH_HOME="$DSH_HOME" DANUS_DSH_AGENTS_HOME="$DSH_AGENTS_HOME" DANUS_DSH_ISOLATED=1
fi
export DANUS_DSH_PROVIDER_PATCH="${DANUS_DSH_PROVIDER_PATCH:-$DANUS_RUNTIME/dsh-provider.json}"
export VERIFY_PORT="${VERIFY_PORT:-8091}"
export DASHBOARD_PORT="${DASHBOARD_PORT:-8099}"
export DANUS_VERIFY_URL="${DANUS_VERIFY_URL:-http://127.0.0.1:${VERIFY_PORT}/verify}"
# Model/provider routing is explicit. No guessed model or partial route fallback.
export DANUS_MAIN_MODEL="${DANUS_MAIN_MODEL:-}"
export DANUS_MAIN_EFFORT="${DANUS_MAIN_EFFORT:-}"
export DANUS_WORKER_MODEL="${DANUS_WORKER_MODEL:-$DANUS_MAIN_MODEL}"
export DANUS_CHROME_BIN="${DANUS_CHROME_BIN:-}"

# 4) PATH: repo wrappers then the pixi-managed toolchain, never a global install.
_danus_path="$DANUS_ROOT/bin"
[ -d "$DANUS_ROOT/.pixi/envs/default/bin" ] && _danus_path="$_danus_path:$DANUS_ROOT/.pixi/envs/default/bin"
case ":$PATH:" in *":$_danus_path:"*) : ;; *) export PATH="$_danus_path:$PATH" ;; esac

# 5) Prefer an explicitly configured interpreter, then the project's pixi env.
export DANUS_PY="${DANUS_PY:-$DANUS_ROOT/.pixi/envs/default/bin/python}"
export DANUS_NODE="${DANUS_NODE:-$(command -v node || true)}"

# silent unless DANUS_ENV_VERBOSE=1
if [ "${DANUS_ENV_VERBOSE:-0}" = "1" ]; then
  echo "DANUS_ROOT=$DANUS_ROOT"
  echo "DANUS_PY=$DANUS_PY"
  echo "DANUS_AGENTS_ROOT=$DANUS_AGENTS_ROOT"
  echo "DANUS_VERIFY_URL=$DANUS_VERIFY_URL"
  echo "DSH_HOME=$DSH_HOME"
  echo "DSH_AGENTS_HOME=$DSH_AGENTS_HOME"
fi

# 6) verify-service identity probe (shared by doctor.sh / services.sh).
# A bare `/health` 200 does NOT prove the responder is OURS: on a shared host a
# second Danus deployment can hold the same VERIFY_PORT, and its verifier would
# answer our probe (a false "up" that silently routes fact_submit to the wrong
# verifier). This classifies the port by matching the pid /health self-reports
# against our own runtime/run/verify.pid. Echoes one word + sets a code:
#   ours    (0)  -> healthy AND the responder is our pidfile's process
#   foreign (3)  -> something answers, but it is not ours (port collision)
#   stale   (4)  -> our pidfile process is dead and nothing answers the port
#   down    (5)  -> nothing answers and we have no pidfile process
danus_verify_health(){
  local url="http://127.0.0.1:${VERIFY_PORT}/health"
  local pf="$DANUS_RUNTIME/run/verify.pid"
  local our_pid resp health_pid
  our_pid="$(cat "$pf" 2>/dev/null || true)"
  resp="$(curl -s --max-time 5 "$url" 2>/dev/null || true)"
  if [ -z "$resp" ]; then
    if [ -n "$our_pid" ] && kill -0 "$our_pid" 2>/dev/null; then echo down; return 5; fi
    { [ -n "$our_pid" ]; } && { echo stale; return 4; }
    echo down; return 5
  fi
  # pull "pid": <n> out of the JSON without a json dep
  health_pid="$(printf '%s' "$resp" | sed -n 's/.*"pid"[[:space:]]*:[[:space:]]*\([0-9]\{1,\}\).*/\1/p')"
  if [ -n "$our_pid" ] && [ -n "$health_pid" ] && [ "$our_pid" = "$health_pid" ]; then
    echo ours; return 0
  fi
  # answered, but not by our pidfile's process (or an old build with no pid field)
  echo foreign; return 3
}
