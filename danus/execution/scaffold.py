"""Project/worker scaffolding + detached loop launch.

``do_new`` writes the on-disk layout a project needs; ``spawn_loop`` launches a
worker's outer loop detached in its own process group. Both are libraries the
``danus`` CLI verbs (``danus.orchestration``) call — kept here beside the loop +
layout so the file names, config template, and launch mechanism live in one place.

Notes:
  - the dsh MCP wiring launches the installed package ``python -m danus.gateway``
    (a pinned interface) rather than an absolute path to a server file;
  - the config template + defaults (verify URL, model) come from env at CALL time
    (with a built-in fallback default), not hard-wired at import time.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Dict, List, Optional

from danus import dsh

from . import layout as L

# --------------------------------------------------------------------------- #
# atomic file helpers                                                         #
# --------------------------------------------------------------------------- #

def atomic_write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)


def symlink(target: Path, link: Path) -> None:
    """Best-effort symlink; degrade gracefully where symlinks are unsupported
    (the dsh config still points at the repo, so the worker isn't broken)."""
    if link.is_symlink() or link.exists():
        return
    try:
        os.symlink(target, link)
    except OSError:
        pass


# --------------------------------------------------------------------------- #
# dsh config template + task placeholder                                    #
# --------------------------------------------------------------------------- #

# DSH launch overlays mount the gateway with this interpreter, not a PATH python.

_TASK_PLACEHOLDER = (
    "# Task\n\n(unassigned — the main agent writes your assignment here via "
    "`danus assign`; you read this file at the start of every round)\n"
)


def _verify_url() -> str:
    # each fact_submit POSTs here; the verify service spawns a fresh dsh to
    # verify. Standard local endpoint by default; override with DANUS_VERIFY_URL.
    return os.environ.get("DANUS_VERIFY_URL", "http://127.0.0.1:8091/verify")


def _default_model() -> str:
    return dsh.model("DANUS_WORKER_MODEL")


def write_dsh_config(wl: "L.WorkerLayout") -> None:
    """Write inspectable gateway wiring; the launcher generates fresh full overlays.

    Rewrite at every start so rebuilt environments never retain a stale Python.
    The role-specific contract name avoids discovering the main AGENTS.md above it.
    """
    contract = L.worker_md()
    if not contract.is_file():
        raise FileNotFoundError(f"worker contract missing: {contract}")
    symlink(contract, wl.dir / "WORKER.md")
    if not (wl.dir / "WORKER.md").is_file():
        atomic_write(wl.dir / "WORKER.md", contract.read_text(encoding="utf-8"))
    atomic_write(wl.dsh_config, json.dumps([{"insert": [dsh.gateway_row(
        role="worker", cwd=wl.dir, project_dir=wl.project_dir, author=wl.name,
    )]}], indent=2))


# --------------------------------------------------------------------------- #
# do_new — scaffold a project                                                 #
# --------------------------------------------------------------------------- #

def do_new(project: str, roles: str = "max:3",
           model: Optional[str] = None) -> Dict:
    """Scaffold a project dir + one worker home per role. Refuses to clobber an
    existing project dir (no silent overwrite of a live fact graph). Returns
    ``{"project_dir", "workers"}``."""
    pdir = L.project_dir(project)
    if pdir.exists():
        raise SystemExit(f"project already exists: {pdir} (pick another name or remove it)")
    role_pairs = L.parse_roles(roles)
    model = model or _default_model()

    L.workers_dir(project).mkdir(parents=True, exist_ok=True)
    (pdir / "global_memory").mkdir(exist_ok=True)
    (pdir / "fact_graph").mkdir(exist_ok=True)

    created: List[str] = []
    for worker, base in role_pairs:
        wl = L.WorkerLayout(L.worker_dir(project, worker))
        wl.local_memory.mkdir(parents=True, exist_ok=True)
        wl.logs.mkdir(exist_ok=True)

        # static contract + skills (symlinks stay in sync with the repo)
        symlink(L.worker_md(), wl.dir / "WORKER.md")
        (wl.dir / ".agents").mkdir(exist_ok=True)
        symlink(L.worker_skills_dir(), wl.dir / ".agents" / "skills")

        # dsh MCP wiring (role=worker)
        write_dsh_config(wl)
        atomic_write(wl.task, _TASK_PLACEHOLDER)
        atomic_write(wl.role,
                     f"MODEL={model}\nREASONING_EFFORT={base}\nROLE={base}\nDANUS_AUTHOR={worker}\n")
        atomic_write(wl.status,
                     json.dumps({"worker": worker, "state": "created", "round": 0}, indent=2))
        created.append(worker)

    meta = {"name": project, "model": model, "roles": roles, "workers": created}
    atomic_write(pdir / "project.json", json.dumps(meta, ensure_ascii=False, indent=2))
    return {"project_dir": str(pdir), "workers": created}


# --------------------------------------------------------------------------- #
# spawn_loop — detached launch of one worker's outer loop                     #
# --------------------------------------------------------------------------- #

def spawn_loop(wdir: Path) -> int:
    """Launch ``python -m danus.execution <wdir>`` detached in its own process
    group (``start_new_session=True``). The loop's SIGTERM handler cleans up
    its in-flight DSH child's separate process group. Returns the loop pid."""
    wl = L.WorkerLayout(wdir)
    wl.logs.mkdir(parents=True, exist_ok=True)
    logf = open(wl.logs / "loop.log", "a", encoding="utf-8")
    try:
        proc = subprocess.Popen(
            [sys.executable, "-m", "danus.execution", str(wdir)],
            stdout=logf, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL,
            start_new_session=True,
        )
    finally:
        logf.close()
    return proc.pid
