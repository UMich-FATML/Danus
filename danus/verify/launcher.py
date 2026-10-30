"""Cold-start DSH verifier: unique writable output cwd, read-only gateway.

Only a completed headless turn with process exit zero may supply verification
JSON. Service/gateway still own the critical_errors + gaps truth gate.
"""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional

from fastapi import HTTPException
from danus import dsh

_HERE = Path(__file__).resolve().parent
_REPO_ROOT = _HERE.parent.parent
VERIFICATION_FILENAMES = ("verification.json", "verificationt.json")


def _results_root() -> Path:
    return Path(os.getenv("VERIFIER_RESULTS_DIR", str(_REPO_ROOT / "runtime" / "verifier-runs"))).resolve()


def _model() -> str:
    return dsh.model("DANUS_VERIFY_MODEL")


def _effort() -> str:
    return dsh.effort("DANUS_VERIFY_EFFORT")


def _timeout() -> Optional[int]:
    return int(os.getenv("DANUS_VERIFY_TIMEOUT_SECONDS", "0")) or None


def _utc_timestamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def generate_run_id(statement: str) -> str:
    return f"{_utc_timestamp()}_{hashlib.sha256(statement.encode('utf-8')).hexdigest()[:12]}"


def _allocate_run_id(statement: str) -> str:
    root = _results_root()
    root.mkdir(parents=True, exist_ok=True)
    base = generate_run_id(statement)
    run_id, suffix = base, 1
    for _ in range(10000):
        try:
            (root / run_id).mkdir(exist_ok=False)
            return run_id
        except FileExistsError:
            suffix += 1
            run_id = f"{base}_{suffix}"
    raise RuntimeError(f"could not allocate a unique run_id under {root}")


def _results_dir(run_id: str) -> Path:
    if Path(run_id).name != run_id or run_id in (".", ".."):
        raise ValueError("invalid verifier run id")
    return _results_root() / run_id


def _verification_path(run_id: str) -> Optional[Path]:
    for filename in VERIFICATION_FILENAMES:
        path = _results_dir(run_id) / filename
        if path.is_file():
            return path
    return None


def build_prompt(run_id: str, statement: str, proof: str) -> str:
    output_path = _results_dir(run_id) / VERIFICATION_FILENAMES[0]
    return (f"Run_id: {run_id}. Statement: {statement}. Proof:\n{proof}\n\n"
            "Use VERIFIER.md to verify the above proof for the statement. "
            f"Write the verification JSON to this exact path: {output_path}.")


def run_dsh_verification(run_id: str, statement: str, proof: str) -> Dict[str, Any]:
    results_dir = _results_dir(run_id)
    results_dir.mkdir(parents=True, exist_ok=True)
    # Unique per request, not the old singleton agent home. Copy the standing
    # contract so even parallel verification requests cannot race relinking it.
    contract = _REPO_ROOT / "agents" / "contracts" / "verifier.md"
    (results_dir / "VERIFIER.md").write_text(contract.read_text(encoding="utf-8"), encoding="utf-8")
    log_path = results_dir / "events.jsonl"
    # A reused run id must never accept an earlier run's output as new evidence.
    if any((results_dir / name).exists() for name in VERIFICATION_FILENAMES):
        raise HTTPException(status_code=500, detail="verifier run already has output; allocate a fresh run id")
    try:
        completed = dsh.run(build_prompt(run_id, statement, proof), cwd=results_dir,
            model=_model(), effort=_effort(), role="verifier", instructions="VERIFIER.md",
            skill_dirs=[_REPO_ROOT / "agents" / "skills" / "verify"],
            timeout=_timeout(), log_path=log_path)
    except subprocess.TimeoutExpired as exc:
        raise HTTPException(status_code=504,
            detail=f"DSH timed out after {exc.timeout}s. See log at {log_path}") from exc
    except (ValueError, OSError) as exc:
        raise HTTPException(status_code=500, detail=f"DSH configuration/launch failed: {exc}") from exc
    (results_dir / "session.json").write_text(json.dumps({"session_id": completed.session_id,
        "run_id": completed.run_id, "reason": completed.reason}), encoding="utf-8")
    if completed.returncode != 0:
        raise HTTPException(status_code=500,
            detail=f"DSH failed with exit code {completed.returncode}, reason {completed.reason!r}. See log at {log_path}")
    verification_path = _verification_path(run_id)
    if verification_path is None:
        raise HTTPException(status_code=500,
            detail=f"verification output was not found at {results_dir / VERIFICATION_FILENAMES[0]}. See log at {log_path}")
    try:
        payload = json.loads(verification_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        raise HTTPException(status_code=500,
            detail=f"verification output at {verification_path} is not valid JSON") from exc
    if not isinstance(payload, dict):
        raise HTTPException(status_code=500,
            detail=f"verification output at {verification_path} must be a JSON object")
    return payload
