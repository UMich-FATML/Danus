"""The per-worker autonomous outer loop — the round driver.

Launched detached by ``danus start`` (``python -m danus.execution <worker_dir>``).
Self-contained. Each round runs ONE ``dsh --profile headless`` session
whose internal control loop (worker.md + the worker skills) drives toward a full
verified result — a round is *continue solving from persisted memory*, NOT one
increment. The round ends when dsh's session ends (its stopping rule, the
per-round hard timeout, or it bails); the loop then relaunches a fresh session
that resumes from memory. Stops on the ``.stop`` flag (graceful, at a round
boundary), the project deadline, or a round backstop.

Config:
  - dsh binary resolved via the shared ``danus.dsh`` launcher
    (``DANUS_DSH_BIN`` / PATH);
  - all config read at CALL time from env (matches core/gateway/verify).

Env (all optional; tests inject these):
  DANUS_DSH_BIN            dsh binary (default "dsh")
  DANUS_ROUND_BEAT           seconds to sleep between rounds (default 5)
  DANUS_ROUND_HARD_TIMEOUT   per-round hard timeout, seconds (default 14400 = 4h)
  DANUS_MAX_ROUNDS           round backstop, 0 = unlimited (default 0)
  DANUS_MAX_CONSEC_FAILURES  bail after this many consecutive failed rounds (default 5)
"""

from __future__ import annotations

import json
import os
import re
import signal
import subprocess
import sys
import time
from pathlib import Path
from typing import Optional

from . import layout as L
from . import scaffold
from danus import dsh
import uuid
import logging

_FACT_ID_RE = re.compile(r'"?fact_id"?\s*[:=]\s*"?([0-9a-f]{16})"?')


# --- the per-round prompt (continuation semantics; see worker.md) ----------- #

def kickoff(project: str, worker: str) -> str:
    return (
        f"You are worker '{worker}' on project '{project}'. Continue solving the "
        f"problem (this is a continuation round, not a fresh start).\n"
        f"1. Read TASK.md — your current assignment (which direction/subgoal is yours).\n"
        f"2. Follow WORKER.md (worker.md) exactly — your standing contract (the adaptive "
        f"control loop, memory discipline, the fact_submit gate). Drive toward a full "
        f"verified result.\n"
        f"3. Resume from state: gm_search relevant findings + dead ends, read the fact "
        f"graph and the latest master_guidance — DO NOT restart from zero; build on what "
        f"is already there.\n"
        f"4. Keep going: assess -> pick skills adaptively -> act -> persist, repeatedly. "
        f"An open problem is not a reason to stop. Do NOT finalize prematurely.\n"
        f"5. Persist as you go: rough progress to local memory; shareable findings via "
        f"gm_add; any verified result via fact_submit."
    )


# --- config (read at call time) -------------------------------------------- #

# dsh binary + model/effort defaults are resolved via the shared danus.dsh
# launcher (DANUS_DSH_BIN / DANUS_MAIN_MODEL / DANUS_MAIN_EFFORT); the worker's
# own model comes from DANUS_WORKER_MODEL (falls back to the neutral default).


# --- small helpers --------------------------------------------------------- #

def _read_role(wl: L.WorkerLayout) -> dict:
    out = {"MODEL": dsh.model("DANUS_WORKER_MODEL"),
           "REASONING_EFFORT": "high", "ROLE": "high", "DANUS_AUTHOR": wl.name}
    rp = wl.role
    if rp.exists():
        for line in rp.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                out[k.strip()] = v.strip()
    return out


def write_status(wl: L.WorkerLayout, **fields) -> None:
    """Atomic status write (so `danus status` never reads a half-written file)."""
    path = wl.status
    cur = {}
    if path.exists():
        try:
            cur = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            cur = {}
    cur.update(fields)
    cur["worker"] = wl.name
    cur["pid"] = os.getpid()
    cur["updated_at"] = time.time()
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(cur, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, path)


def _deadline_passed(project_dir: Path) -> bool:
    f = project_dir / L.DEADLINE_FILE
    if not f.exists():
        return False
    try:
        return time.time() >= float(f.read_text().strip())
    except (ValueError, OSError):
        return False


def _parse_last_fact_id(log_path: Path) -> Optional[str]:
    try:
        text = log_path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None
    last = None
    for line in text.split("\n"):
        # DSH projects tool results as JSON-escaped text inside NDJSON. Search
        # decoded result/final text, not the transport's backslash escapes. This
        # remains a status breadcrumb, never an authoritative fact lookup.
        candidate = line
        try:
            event = json.loads(line)
            if isinstance(event, dict):
                value = event.get("result", event.get("text"))
                if isinstance(value, str):
                    candidate = value
        except json.JSONDecodeError:
            pass  # stderr and old plain-text logs remain readable
        ids = _FACT_ID_RE.findall(candidate)
        if ids:
            last = ids[-1]
    return last


# --- one round ------------------------------------------------------------- #

class _Child:
    """Holds the running dsh subprocess so the SIGTERM handler can kill it."""
    proc: "subprocess.Popen | None" = None


def _record_child(wl: L.WorkerLayout, proc: Optional[subprocess.Popen]) -> None:
    marker = wl.dir / ".dsh-child.json"
    if proc is None:
        marker.unlink(missing_ok=True)
    else:
        scaffold.atomic_write(marker, json.dumps(dsh.process_identity(proc.pid)))
    _Child.proc = proc


def run_round(wl: L.WorkerLayout, role: dict, prompt: str, log_path: Path,
              hard_timeout: int) -> int:
    """Run a fresh DSH session; zero requires a full completed final answer."""
    # Publish a lease immediately before Popen, after non-writing MCP preflight.
    # Cancellation during preflight has no worker child; interruption during spawn
    # remains intentionally fail-closed until the uncertain processes are inspected.
    marker = wl.dir / ".dsh-child.json"
    def preparing_child():
        scaffold.atomic_write(marker, json.dumps({"state": "starting", "parent": dsh.process_identity(os.getpid())}))
    clean_exit = False
    try:
        result = dsh.run(prompt, cwd=wl.dir, model=role["MODEL"],
                         effort=role["REASONING_EFFORT"], role="worker",
                         project_dir=wl.project_dir, author=wl.name,
                         instructions="WORKER.md", skill_dirs=[L.worker_skills_dir()],
                         timeout=hard_timeout, log_path=log_path, worker_project=wl.project,
                         on_process=lambda proc: _record_child(wl, proc),
                         on_starting=preparing_child)
        write_status(wl, last_session_id=result.session_id, last_run_id=result.run_id,
                     last_reason=result.reason, last_log=str(log_path))
        if result.stderr:
            with log_path.open("a", encoding="utf-8") as log:
                log.write("\n[DSH stderr]\n" + result.stderr)
        clean_exit = True
        return result.returncode
    except FileNotFoundError as exc:
        with log_path.open("a", encoding="utf-8") as log:
            log.write(f"[worker_loop] DSH binary/config not found: {exc}\n")
        clean_exit = True
        return 127
    except subprocess.TimeoutExpired:
        with log_path.open("a", encoding="utf-8") as log:
            log.write(f"[worker_loop] round hard-timeout after {hard_timeout}s\n")
        clean_exit = True
        return 124
    except (ValueError, OSError) as exc:
        with log_path.open("a", encoding="utf-8") as log:
            log.write(f"[worker_loop] DSH configuration/launch error: {exc}\n")
        clean_exit = True
        return 1
    finally:
        # A signal can arrive between Popen returning and its PID callback. Keep
        # the uncertain startup lease on cancellation/unhandled exceptions; a
        # missing callback is not proof that no child was created.
        if clean_exit and _Child.proc is None:
            marker.unlink(missing_ok=True)


def _snapshot_round(wl: L.WorkerLayout, round_number: int) -> None:
    if os.environ.get("DANUS_SNAPSHOT_AUTO", "1") == "0":
        return
    try:
        from danus.checkpoints import request_snapshot
        status = json.loads(wl.status.read_text(encoding="utf-8"))
        result = request_snapshot(wl.project_dir, {"kind": "worker-round", "worker": wl.name,
            "round": round_number, "session_id": status.get("last_session_id")})
        for warning in result.get("warnings", []):
            logging.getLogger(__name__).warning(f"worker snapshot: {warning}")
    except Exception as exc:
        logging.getLogger(__name__).warning(f"worker snapshot failed (continuing): {exc}")


# --- the loop -------------------------------------------------------------- #

def _cleanup_pid(wl: L.WorkerLayout) -> None:
    """Remove our own .pid if it still points at us (clean exit only)."""
    pf = wl.pid
    try:
        if pf.exists() and pf.read_text().strip() == str(os.getpid()):
            pf.unlink(missing_ok=True)
    except OSError:
        pass


def main(worker_dir: str) -> int:
    wdir = Path(worker_dir).resolve()
    if not wdir.is_dir():
        print(f"worker dir not found: {wdir}", file=sys.stderr)
        return 2
    wl = L.WorkerLayout(wdir)
    project_dir = wl.project_dir
    project = wl.project
    worker = wl.name
    role = _read_role(wl)

    # Pin the worker's gateway to THIS interpreter (sys.executable = the venv
    # python danus runs on), rewritten every start: a moved/rebuilt venv is
    # picked up, and a bare `python3` on dsh's PATH can never resolve the
    # gateway to a different install.
    scaffold.write_dsh_config(wl)

    beat = float(os.environ.get("DANUS_ROUND_BEAT", "5"))
    hard_timeout = int(os.environ.get("DANUS_ROUND_HARD_TIMEOUT", "14400"))
    max_rounds = int(os.environ.get("DANUS_MAX_ROUNDS", "0"))
    max_fail = int(os.environ.get("DANUS_MAX_CONSEC_FAILURES", "5"))
    wl.logs.mkdir(parents=True, exist_ok=True)
    prompt = kickoff(project, worker)

    def _on_term(signum, _frame):
        if _Child.proc is not None:
            dsh.terminate_process_group(_Child.proc)
        write_status(wl, state="terminated")
        _cleanup_pid(wl)
        sys.exit(0)

    signal.signal(signal.SIGTERM, _on_term)

    write_status(wl, state="running", round=0, started_at=time.time())
    rnd = 0
    invocation_id = uuid.uuid4().hex
    consec_fail = 0
    try:
        while True:
            if wl.stop.exists():
                wl.stop.unlink(missing_ok=True)
                write_status(wl, state="stopped")
                break
            if _deadline_passed(project_dir):
                write_status(wl, state="deadline")
                break
            if max_rounds and rnd >= max_rounds:
                write_status(wl, state="max_rounds")
                break

            rnd += 1
            log_path = wl.logs / f"round_{invocation_id}_{rnd}.log"
            write_status(wl, state="running", round=rnd, round_started_at=time.time(),
                         last_session_id=None, last_run_id=None, last_reason=None, last_log=str(log_path))
            rc = run_round(wl, role, prompt, log_path, hard_timeout)
            write_status(
                wl, state="idle", round=rnd, last_round_at=time.time(),
                last_rc=rc, last_fact_id=_parse_last_fact_id(log_path),
            )

            if rc == 0:
                # The subprocess, gateway, and log handles are closed before capture.
                _snapshot_round(wl, rnd)
            if rc == 127:                    # missing installation — do not spin
                write_status(wl, state="error", error="DSH binary/config not found")
                return 127
            consec_fail = consec_fail + 1 if rc not in (0, 124) else 0
            if max_fail and consec_fail >= max_fail:
                write_status(wl, state="error", error=f"{consec_fail} consecutive failed rounds")
                return 1

            if beat > 0:
                time.sleep(beat)
    finally:
        _cleanup_pid(wl)
    return 0
