"""``danus`` — the main agent's control surface over DSH workers.

    danus list   [--json]
    danus new    <project> [--roles max:3] [--model M]
    danus assign <project>/<worker> (--task "…" | --file P | --stdin)
    danus finalize <project> [--paper <paper_id>] [<fact_id> ...]
    danus start  <project>[/<worker>]
    danus status <project>[/<worker>] [--json]
    danus stop   <project>[/<worker>] [--force]

This module is the verbs/UX only. The worker outer loop, the on-disk layout, and
the scaffolding they drive live in ``danus.execution`` (imported here as a
library). Reads/writes only files under the project dir — the loop is autonomous;
this CLI just assigns / starts / monitors / stops it.

Notes:
  - the layout + scaffolding + config template are imported from ``danus.execution``
    (no duplicated layout / config template);
  - the verbs are mode-agnostic and identical across deployments.
"""

from __future__ import annotations

import argparse
import fcntl
import json
import os
import signal
import time
from pathlib import Path
from typing import Dict, List, Optional

from danus.execution import layout as L
from danus.execution.scaffold import atomic_write, do_new, spawn_loop
from danus import checkpoints

__all__ = [
    "do_new", "do_assign", "do_start", "do_status", "worker_status",
    "do_list", "do_stop", "do_finalize", "build_parser", "main",
]


# --------------------------------------------------------------------------- #
# read helpers                                                                 #
# --------------------------------------------------------------------------- #

def _read_pid(wl: L.WorkerLayout) -> Optional[int]:
    pf = wl.pid
    if not pf.exists():
        return None
    try:
        return int(pf.read_text().strip())
    except (ValueError, OSError):
        return None


def _alive(pid: Optional[int]) -> bool:
    if not pid:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True  # exists but not ours
    # The pid exists — but a zombie (killed, not yet reaped by its parent) is
    # effectively dead. Linux /proc tells us the process state.
    try:
        stat = Path(f"/proc/{pid}/stat").read_text()
        state = stat.rsplit(")", 1)[1].split()[0]  # field after "(comm)"
        return state != "Z"
    except (OSError, IndexError):
        return True


def _read_status(wl: L.WorkerLayout) -> Dict:
    sp = wl.status
    if not sp.exists():
        return {}
    try:
        return json.loads(sp.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}


# --------------------------------------------------------------------------- #
# assign                                                                       #
# --------------------------------------------------------------------------- #

def do_assign(target: str, task: str) -> Dict:
    """Overwrite (replace, NOT append) a worker's TASK.md, ensuring a trailing
    newline. Rejects a bare project, a nonexistent worker, and an empty task."""
    project, worker = L.resolve_target(target)
    if not worker:
        raise SystemExit("assign needs a specific worker: <project>/<worker>")
    wl = L.WorkerLayout(L.worker_dir(project, worker))
    if not wl.dir.is_dir():
        raise SystemExit(f"no such worker: {project}/{worker}")
    if not task.strip():
        raise SystemExit("refusing to assign an empty task")
    with checkpoints.mutation_lock(wl.project_dir):
        atomic_write(wl.task, task if task.endswith("\n") else task + "\n")
    return {"worker": f"{project}/{worker}", "task_file": str(wl.task)}


# --------------------------------------------------------------------------- #
# finalize                                                                     #
# --------------------------------------------------------------------------- #

def do_finalize(project: str, fact_ids: List[str],
                paper_id: Optional[str] = None) -> Dict:
    """Validate and record final targets under the restore mutation fence."""
    pdir = L.project_dir(project)
    if not pdir.is_dir():
        raise SystemExit(f"no such project: {project}")
    with checkpoints.mutation_lock(pdir):
        return _finalize_locked(project, fact_ids, paper_id)


def _finalize_locked(project: str, fact_ids: List[str],
                     paper_id: Optional[str] = None) -> Dict:
    """Record the finalized target theorem(s) for a PAPER of a project in that
    paper's TARGET.md — the durable slot write-paper reads (never a guess). The
    default paper writes the LEGACY ``<project>/TARGET.md``; a non-default
    ``paper_id`` writes ``<project>/papers/<paper_id>/TARGET.md`` (its own
    workspace). One fact graph per project; per-paper targets.

    Resolves the project dir, VALIDATES every ``fact_id`` against that project's
    fact graph (refuses an id the graph does not have — you cannot record a
    phantom target), then writes the ids to the paper's TARGET.md.

    With NO ``fact_ids`` (suggestion mode): prints the candidate terminal facts
    (facts that are no other fact's predecessor — the ``assemble._terminal_facts``
    helper) as SUGGESTIONS and writes NOTHING (returns ``{"suggested": [...]}``).

    Rejections raise ``SystemExit`` (nonzero exit) with a clear message."""
    from danus.core import FactGraph
    from danus.write_paper import assemble

    pdir = L.project_dir(project)
    if not pdir.is_dir():
        raise SystemExit(f"no such project: {project}")
    fg = FactGraph(pdir)

    if not fact_ids:
        # suggestion mode: never auto-pick — just list candidate terminal facts.
        return {"project": project, "paper_id": paper_id,
                "suggested": assemble._terminal_facts(fg)}

    unknown = [fid for fid in fact_ids if not fg.exists(fid)]
    if unknown:
        raise SystemExit(
            f"cannot finalize: unknown fact id(s) in {project}: {', '.join(unknown)} "
            f"(a target must be a verified fact in the project's graph)"
        )
    # validate a non-default paper_id as a single safe path segment before writing.
    try:
        if not assemble._is_default_paper(paper_id):
            assemble._validate_paper_id(paper_id)  # type: ignore[arg-type]
    except ValueError as e:
        raise SystemExit(f"cannot finalize: {e}")
    # de-dup while preserving order
    seen: set = set()
    ids: List[str] = []
    for fid in fact_ids:
        if fid not in seen:
            seen.add(fid)
            ids.append(fid)
    path = assemble.write_target_fact_ids(pdir, ids, paper_id)
    return {"project": project, "paper_id": paper_id,
            "target_file": str(path), "target_fact_ids": ids}


# --------------------------------------------------------------------------- #
# start                                                                        #
# --------------------------------------------------------------------------- #

def _start_one(wl: L.WorkerLayout) -> str:
    # Restore checks liveness while holding this same fence. A managed worker
    # cannot start in the gap between that check and durable replacement.
    with checkpoints.mutation_lock(wl.project_dir):
        return _start_one_locked(wl)


def _start_one_locked(wl: L.WorkerLayout) -> str:
    """Returns 'started' / 'already-running' / 'locked'. Idempotent via an flock
    on .pid.lock; clears a stale .stop before spawning."""
    wl.dir.mkdir(parents=True, exist_ok=True)
    wl.logs.mkdir(exist_ok=True)
    lock = open(wl.lock, "w")
    try:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return "locked"
        if _alive(_read_pid(wl)):
            return "already-running"
        child = checkpoints.worker_child_identity(wl.dir)
        if checkpoints.worker_child_active(child):
            return "orphaned-child (stop --force first)"
        (wl.dir / ".dsh-child.json").unlink(missing_ok=True)
        wl.stop.unlink(missing_ok=True)  # clear a stale stop flag
        pid = spawn_loop(wl.dir)
        atomic_write(wl.pid, str(pid))
        return "started"
    finally:
        fcntl.flock(lock, fcntl.LOCK_UN)
        lock.close()


def do_start(target: str, stagger: float = 0.2) -> List[Dict]:
    dirs = L.target_worker_dirs(target)
    if not dirs:
        raise SystemExit(f"no workers for target {target!r}")
    out = []
    for i, wdir in enumerate(dirs):
        if i and stagger:
            time.sleep(stagger)
        out.append({"worker": wdir.name, "result": _start_one(L.WorkerLayout(wdir))})
    return out


# --------------------------------------------------------------------------- #
# status                                                                       #
# --------------------------------------------------------------------------- #

def worker_status(wl: L.WorkerLayout) -> Dict:
    pid = _read_pid(wl)
    alive = _alive(pid)
    st = _read_status(wl)
    state = st.get("state", "—")
    now = time.time()
    last = st.get("last_round_at") or st.get("round_started_at") or st.get("updated_at")
    age = (now - last) if isinstance(last, (int, float)) else None

    if alive:
        # a round legitimately runs for hours; only flag truly stale running rounds
        rs = st.get("round_started_at")
        hard = int(os.environ.get("DANUS_ROUND_HARD_TIMEOUT", "14400"))
        if state == "running" and isinstance(rs, (int, float)) and (now - rs) > hard * 1.5:
            label = "stuck?"
        else:
            label = "working"
    else:
        label = state if state in ("stopped", "deadline", "max_rounds", "error",
                                   "terminated", "created") else "dead"
    return {
        "worker": wl.name, "pid": pid, "alive": alive, "state": state,
        "round": st.get("round", 0), "age_s": round(age, 1) if age is not None else None,
        "last_fact_id": st.get("last_fact_id"), "label": label,
    }


def do_status(target: str) -> List[Dict]:
    dirs = L.target_worker_dirs(target)
    if not dirs:
        raise SystemExit(f"no workers for target {target!r}")
    return [worker_status(L.WorkerLayout(d)) for d in dirs]


# --------------------------------------------------------------------------- #
# list                                                                         #
# --------------------------------------------------------------------------- #

def do_list() -> List[Dict]:
    """One row per project: roster + how many workers are live + model."""
    out: List[Dict] = []
    for project in L.list_projects():
        meta = {}
        mp = L.project_dir(project) / "project.json"
        if mp.exists():
            try:
                meta = json.loads(mp.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                meta = {}
        error = None
        try:
            workers = L.list_workers(project)
        except (ValueError, OSError) as exc:
            # Diagnostics must remain usable for damaged state. Do not infer a
            # replacement roster from orphaned directories (restores leave logs).
            workers = []
            error = str(exc)
        live = sum(1 for w in workers
                   if _alive(_read_pid(L.WorkerLayout(L.worker_dir(project, w)))))
        row = {"project": project, "workers": len(workers), "live": live,
               "model": meta.get("model", "—")}
        if error:
            row["error"] = error
        out.append(row)
    return out


def _fmt_list(rows: List[Dict]) -> str:
    head = f"{'PROJECT':<24}{'WORKERS':>8}{'LIVE':>6}  {'MODEL':<12}"
    lines = [head, "-" * len(head)]
    for r in rows:
        suffix = f"  ERROR: {r['error']}" if r.get("error") else ""
        lines.append(f"{r['project']:<24}{r['workers']:>8}{r['live']:>6}  {str(r['model']):<12}{suffix}")
    return "\n".join(lines) if rows else "(no projects under the agents root)"


def _fmt_status(rows: List[Dict]) -> str:
    head = f"{'WORKER':<14}{'LABEL':<12}{'STATE':<13}{'ROUND':>6}  {'AGE':>7}  {'LAST_FACT':<16}"
    lines = [head, "-" * len(head)]
    for r in rows:
        age = f"{r['age_s']:.0f}s" if r["age_s"] is not None else "—"
        lines.append(f"{r['worker']:<14}{r['label']:<12}{r['state']:<13}"
                     f"{r['round']:>6}  {age:>7}  {str(r['last_fact_id'] or '—'):<16}")
    return "\n".join(lines)


# --------------------------------------------------------------------------- #
# stop                                                                         #
# --------------------------------------------------------------------------- #

def _stop_child(wl: L.WorkerLayout) -> bool:
    """Terminate an identifiable detached child; never signal a recycled PID."""
    from danus import dsh
    identity = checkpoints.worker_child_identity(wl.dir)
    if identity is None:
        return False
    if not checkpoints.worker_child_active(identity):
        (wl.dir / ".dsh-child.json").unlink(missing_ok=True)
        return False
    pid = identity["pid"]
    # If the leader is gone, its old birth tick cannot identify remaining group
    # members. Fail closed rather than risk signaling an unrelated reused PGID.
    if (not identity.get("start_ticks") or not _alive(pid) or
            not dsh.is_same_process(identity) or os.getpgid(pid) != pid):
        raise SystemExit(f"cannot safely identify orphan child group for {wl.name}; inspect processes before removing .dsh-child.json")
    try:
        os.killpg(pid, signal.SIGTERM)
    except ProcessLookupError:
        pass
    for _ in range(50):
        if not checkpoints.process_group_alive(pid):
            break
        time.sleep(0.1)
    if checkpoints.process_group_alive(pid):
        # An extant matching leader anchors the group's identity. If it exited,
        # the already-observed group can retain descendants; do not guess a new
        # identity and silently kill an unrelated group.
        observed = dsh.process_identity(pid)
        if observed["start_ticks"] is not None and observed["start_ticks"] != identity["start_ticks"]:
            raise SystemExit(f"child PID reused while stopping {wl.name}; refusing signal")
        try:
            os.killpg(pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        for _ in range(50):
            if not checkpoints.process_group_alive(pid):
                break
            time.sleep(0.1)
    if checkpoints.process_group_alive(pid):
        raise SystemExit(f"child processes remain for {wl.name}; restore stays blocked")
    (wl.dir / ".dsh-child.json").unlink(missing_ok=True)
    return True


def _stop_one(wl: L.WorkerLayout, force: bool) -> str:
    if not force and not _alive(_read_pid(wl)) and checkpoints.worker_child_active(checkpoints.worker_child_identity(wl.dir)):
        return "orphaned-child (use --force)"
    result = _stop_loop(wl, force)
    if force and _stop_child(wl):
        return "killed"
    return result


def _stop_loop(wl: L.WorkerLayout, force: bool) -> str:
    pid = _read_pid(wl)
    if not force:
        if not _alive(pid):
            return "not-running"
        wl.stop.touch()      # graceful: loop exits at round boundary
        return "stopping (graceful)"
    # force: kill the loop's process group (loop + its DSH child), then SIGKILL
    if not _alive(pid):
        wl.pid.unlink(missing_ok=True)
        return "not-running"
    try:
        pgid = os.getpgid(pid)
        os.killpg(pgid, signal.SIGTERM)
    except (ProcessLookupError, PermissionError):
        pass
    for _ in range(50):                          # up to ~5s for a clean exit
        if not _alive(pid):
            break
        time.sleep(0.1)
    if _alive(pid):
        try:
            os.killpg(os.getpgid(pid), signal.SIGKILL)
        except (ProcessLookupError, PermissionError):
            pass
    wl.pid.unlink(missing_ok=True)
    return "killed"


def do_stop(target: str, force: bool = False) -> List[Dict]:
    dirs = L.target_worker_dirs(target)
    if not dirs:
        raise SystemExit(f"no workers for target {target!r}")
    return [{"worker": d.name, "result": _stop_one(L.WorkerLayout(d), force)} for d in dirs]


# --------------------------------------------------------------------------- #
# argparse                                                                      #
# --------------------------------------------------------------------------- #

def _task_from_args(args) -> str:
    import sys
    if args.task is not None:
        return args.task
    if args.file:
        return Path(args.file).read_text(encoding="utf-8")
    if args.stdin:
        return sys.stdin.read()
    raise SystemExit("assign needs one of --task, --file, or --stdin")


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="danus", description="Control DSH workers.")
    sub = p.add_subparsers(dest="cmd", required=True)

    li = sub.add_parser("list", help="list all projects + live worker counts")
    li.add_argument("--json", action="store_true")

    n = sub.add_parser("new", help="scaffold a project + worker dirs")
    n.add_argument("project")
    n.add_argument("--roles", default="max:3", help="e.g. max:3 (default)")
    n.add_argument("--model", default=None)

    a = sub.add_parser("assign", help="write a worker's per-round TASK.md")
    a.add_argument("target", help="<project>/<worker>")
    a.add_argument("--task", default=None)
    a.add_argument("--file", default=None)
    a.add_argument("--stdin", action="store_true")

    f = sub.add_parser("finalize", help="record the finalized target fact_id(s) in "
                                        "a paper's TARGET.md (write-paper reads this)")
    f.add_argument("project")
    f.add_argument("--paper", default=None,
                   help="the paper_id (multiple papers per project). Default / 'main' "
                        "→ legacy <project>/TARGET.md; else "
                        "<project>/papers/<paper_id>/TARGET.md")
    f.add_argument("fact_ids", nargs="*",
                   help="the target fact id(s); omit to print candidate terminal facts")

    s = sub.add_parser("start", help="launch worker loop(s)")
    s.add_argument("target", help="<project> or <project>/<worker>")

    st = sub.add_parser("status", help="liveness + progress")
    st.add_argument("target", help="<project> or <project>/<worker>")
    st.add_argument("--json", action="store_true")

    sp = sub.add_parser("stop", help="stop worker loop(s)")
    sp.add_argument("target", help="<project> or <project>/<worker>")
    sp.add_argument("--force", action="store_true", help="kill now (else finish current round)")

    snap = sub.add_parser("snapshot", help="best-effort project Git checkpoint (writers stay live)")
    snap.add_argument("project")
    snap.add_argument("--message", default=None)
    snaps = sub.add_parser("snapshots", help="list immutable project checkpoints")
    snaps.add_argument("project")
    snaps.add_argument("--json", action="store_true")
    restore = sub.add_parser("restore", help="restore durable state; stop affected workers and main writes first")
    restore.add_argument("project")
    restore.add_argument("snapshot")
    restore.add_argument("--worker", default=None)
    restore.add_argument("--dry-run", action="store_true")
    restore.add_argument("--yes", action="store_true", help="confirm replacement AND that project-writing main activity is stopped")
    restore.add_argument("--allow-inconsistent", action="store_true")
    recover = sub.add_parser("recover-restore", help="roll back an interrupted restore from its immutable backup")
    recover.add_argument("project")
    recover.add_argument("--yes", action="store_true", required=True,
                         help="confirm all affected workers and main writes are stopped")
    return p


def main(argv: Optional[List[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    if args.cmd == "list":
        rows = do_list()
        print(json.dumps(rows, ensure_ascii=False, indent=2) if args.json else _fmt_list(rows))
    elif args.cmd == "new":
        r = do_new(args.project, roles=args.roles, model=args.model)
        print(f"created {args.project} with {len(r['workers'])} workers: "
              f"{', '.join(r['workers'])}\n  {r['project_dir']}")
    elif args.cmd == "assign":
        r = do_assign(args.target, _task_from_args(args))
        print(f"assigned {r['worker']} -> {r['task_file']}")
    elif args.cmd == "finalize":
        r = do_finalize(args.project, args.fact_ids, paper_id=args.paper)
        paper_note = f" (paper {args.paper})" if args.paper else ""
        paper_flag = f" --paper {args.paper}" if args.paper else ""
        if "suggested" in r:
            sug = r["suggested"]
            if sug:
                print(f"no fact_id given — candidate target facts for {r['project']}{paper_note} "
                      f"(terminal facts; nothing depends on them):")
                for fid in sug:
                    print(f"  {fid}")
                print(f"\nrun: danus finalize {r['project']}{paper_flag} <fact_id> [<fact_id> ...] to record")
            else:
                print(f"no candidate terminal facts in {r['project']} "
                      f"(is the fact graph empty?); nothing recorded")
        else:
            print(f"finalized target for {r['project']}{paper_note}: {', '.join(r['target_fact_ids'])}\n"
                  f"  wrote {r['target_file']}")
    elif args.cmd == "start":
        for r in do_start(args.target):
            print(f"{r['worker']}: {r['result']}")
    elif args.cmd == "status":
        rows = do_status(args.target)
        print(json.dumps(rows, ensure_ascii=False, indent=2) if args.json else _fmt_status(rows))
    elif args.cmd == "stop":
        for r in do_stop(args.target, force=args.force):
            print(f"{r['worker']}: {r['result']}")
    elif args.cmd in {"snapshot", "snapshots", "restore", "recover-restore"}:
        try:
            project = L.project_dir(checkpoints.validate_name(args.project))
            if args.cmd == "snapshot":
                result = checkpoints.snapshot(project, args.message)
                print(json.dumps(result, ensure_ascii=False, indent=2))
            elif args.cmd == "snapshots":
                rows = checkpoints.list_snapshots(project)
                if args.json:
                    print(json.dumps(rows, ensure_ascii=False, indent=2))
                else:
                    for row in rows:
                        print(f"{row['snapshot']}  {row['created_at']}  "
                              f"{row['fact_count']} facts  {len(row['warnings'])} warnings")
            elif args.cmd == "recover-restore":
                print(json.dumps(checkpoints.recover_restore(project), indent=2))
            else:
                options = dict(worker=args.worker, allow_inconsistent=args.allow_inconsistent)
                preview = checkpoints.restore(project, args.snapshot, dry_run=True, **options)
                print(json.dumps(preview, ensure_ascii=False, indent=2))
                if not args.dry_run:
                    confirmed = args.yes
                    if not confirmed:
                        import sys
                        if not sys.stdin.isatty():
                            raise checkpoints.CheckpointError("restore needs --yes in noninteractive mode")
                        confirmed = input("Confirm affected workers AND project-writing main activity are stopped; restore? [y/N] ").strip().lower() in {"y", "yes"}
                    if not confirmed:
                        raise checkpoints.CheckpointError("restore cancelled")
                    result = checkpoints.restore(project, args.snapshot, yes=True, **options)
                    print(json.dumps(result, ensure_ascii=False, indent=2))
        except (checkpoints.CheckpointError, OSError, ValueError) as exc:
            raise SystemExit(str(exc)) from exc
    return 0
