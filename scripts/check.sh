#!/usr/bin/env bash
# Run through `pixi run check`; never source the deployment environment here.
set -euo pipefail
ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
exec python - "$ROOT" "$@" <<'PY'
import os
from pathlib import Path
import subprocess
import sys
import tempfile

root = Path(sys.argv[1])
args = sys.argv[2:]
if args not in ([], ["--fast"]):
    raise SystemExit("usage: pixi run check [--fast]")
env = {k: v for k, v in os.environ.items()
       if not k.startswith(("DANUS_", "CODEX_", "KIMI_", "DSH_", "VERIFY_", "VERIFIER_"))
       and not any(word in k.upper() for word in ("API_KEY", "ACCESS_TOKEN", "SECRET", "PASSWORD"))}
with tempfile.TemporaryDirectory(prefix="danus-check-") as tmp:
    env.update(DSH_HOME=str(Path(tmp) / "dsh"),
               DSH_AGENTS_HOME=str(Path(tmp) / "agents"),
               DANUS_DSH_RUNS_DIR=str(Path(tmp) / "runs"),
               PYTHONDONTWRITEBYTECODE="1")
    commands = [[sys.executable, "scripts/harness_lint.py"]]
    if not args:
        commands.extend([
            [sys.executable, "-m", "pytest", "danus/", "scripts/tests/", ".dsh/test_ops.py", "-q"],
            ["node", "--test", ".dsh/main-checkpoints.test.mjs"],
        ])
    for cmd in commands:
        print("+ " + " ".join(cmd), flush=True)
        result = subprocess.run(cmd, cwd=root, env=env)
        if result.returncode:
            raise SystemExit(result.returncode)
PY
