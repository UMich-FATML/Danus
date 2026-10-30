"""Project-wide, best-effort Git checkpoints and stopped-state restore.

Snapshots deliberately do NOT lock project writers. Their manifest describes the
bytes staged, not a transaction of the live stores. Only checkpoint operations
serialize. Restore and gateway commits share a separate short mutation lock;
network verification never holds it. Git metadata never lives in the worktree.
"""
from __future__ import annotations

import argparse
from contextlib import contextmanager
from datetime import datetime, timezone
import fcntl
import json
import os
from pathlib import Path, PurePosixPath
import re
import stat
import subprocess
import tempfile
from typing import Any, Iterator
import uuid

MANIFEST = ".danus-snapshot.json"
_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*\Z")
_TAG = re.compile(r"snap-([1-9][0-9]*)\Z")
_EXCLUDED_DIRS = {".git", ".gitstore", ".dsh", ".codex", ".claude", ".agents", ".runs",
                  "logs", "sessions", "session_store", "session-store", "node_modules",
                  "__pycache__", ".pytest_cache", ".mypy_cache", ".ruff_cache", ".cache",
                  ".pixi", ".venv", ".aws", ".ssh", "venv", "build", "dist", "cache", "caches", "config"}
_EXCLUDED_NAMES = {MANIFEST, ".pid", ".pid.lock", ".stop", ".status.json", ".run_deadline",
                   ".session.json", ".session", ".session_id", ".dsh-session.json", ".dsh-child.json",
                   ".dsh-session", "credentials", "credentials.json", "auth.json",
                   "id_rsa", "id_ed25519", ".netrc", ".npmrc", ".ds_store"}
_EXCLUDED_SUFFIXES = {".log", ".pid", ".lock", ".tmp", ".pyc", ".pyo", ".pdf", ".aux",
                      ".out", ".toc", ".fls", ".fdb_latexmk", ".synctex", ".pem", ".key",
                      ".p12", ".pfx", ".sqlite", ".sqlite3", ".db"}
_SECRET = re.compile(
    rb"-----BEGIN (?:[A-Z ]*PRIVATE KEY)-----|"
    rb"\b(?:sk-[A-Za-z0-9_-]{20,}|gh[pousr]_[A-Za-z0-9]{20,}|AKIA[A-Z0-9]{16})\b|"
    rb"(?:api[_-]?key|access[_-]?token|secret[_-]?key|password)[\"']?\s*[=:]\s*[\"']?[^\s\"']{8,}|"
    rb"\bBearer\s+[A-Za-z0-9._-]{20,}", re.I)


class CheckpointError(RuntimeError):
    pass


def validate_name(name: str) -> str:
    if not _NAME.fullmatch(name) or name in {".", ".."}:
        raise CheckpointError(f"unsafe project/worker name: {name!r}")
    return name


def _project(project_dir: Path) -> Path:
    path = Path(os.path.abspath(project_dir))
    validate_name(path.name)
    if path.resolve() != path or not path.is_dir():
        raise CheckpointError(f"project must be an existing non-symlink directory: {path}")
    return path


def _paths(project: Path) -> tuple[Path, Path]:
    # Conventional runtime/projects/<name> -> runtime/.gitstore/<name>.git.
    # Custom agents roots use a sibling .gitstore, never the project itself.
    base = project.parent.parent if project.parent.name == "projects" else project.parent
    store = base / ".gitstore"
    if store.is_symlink() or (store.exists() and not store.is_dir()):
        raise CheckpointError("unsafe .gitstore path")
    repo = store / f"{project.name}.git"
    state = store / f"{project.name}.state"
    for path in (repo, state):
        if path.is_symlink():
            raise CheckpointError(f"unsafe metadata path: {path}")
    return repo, state


@contextmanager
def _lock(project: Path, name: str) -> Iterator[Path]:
    _, state = _paths(project)
    state.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd = os.open(state / name, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX)
        yield state
    finally:
        fcntl.flock(fd, fcntl.LOCK_UN)
        os.close(fd)


@contextmanager
def mutation_lock(project_dir: Path, *, restoring: bool = False) -> Iterator[Path]:
    """Fence gateway writes against restore, never used by snapshot capture."""
    project = _project(project_dir)
    with _lock(project, "mutation.lock") as state:
        if not restoring and (state / "restore.json").exists():
            raise CheckpointError("interrupted restore: recover_restore(project_dir) before writing")
        yield state


def _generation(state: Path) -> str:
    path = state / "generation"
    return path.read_text().strip() if path.exists() else "0"


def project_generation(project_dir: Path) -> str:
    with mutation_lock(project_dir) as state:
        return _generation(state)


def generation_matches(state: Path, generation: str) -> bool:
    """Call only while holding mutation_lock."""
    return _generation(state) == generation


def _atomic(path: Path, data: bytes) -> None:
    fd, temporary = tempfile.mkstemp(prefix=".checkpoint-", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as out:
            out.write(data)
            out.flush()
            os.fsync(out.fileno())
        os.replace(temporary, path)
        directory = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def _git(project: Path, *args: str, data: bytes | None = None,
         index: str | None = None) -> bytes:
    repo, _ = _paths(project)
    # Neutralize inherited Git settings (including alternate object/index dirs)
    # and global hooks/config. Every command explicitly targets only this repo.
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    env.update(GIT_CONFIG_NOSYSTEM="1", GIT_CONFIG_GLOBAL=os.devnull,
               GIT_AUTHOR_NAME="Danus checkpoint", GIT_AUTHOR_EMAIL="checkpoint@localhost",
               GIT_COMMITTER_NAME="Danus checkpoint", GIT_COMMITTER_EMAIL="checkpoint@localhost")
    if index:
        env["GIT_INDEX_FILE"] = index
    # Git init --bare rejects --work-tree; initializing metadata is the sole
    # exception. All subsequent plumbing has both explicit isolation paths.
    paths = [f"--git-dir={repo}"]
    if args[0] != "init":
        paths.append(f"--work-tree={project}")
    cmd = ["git", *paths, "-c", "core.hooksPath=/dev/null",
           "-c", "core.bare=true", *args]
    result = subprocess.run(cmd, input=data, stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE, env=env, cwd=project)
    if result.returncode:
        raise CheckpointError(result.stderr.decode(errors="replace").strip())
    return result.stdout


def durable_path(name: str) -> bool:
    path = PurePosixPath(name)
    if path.is_absolute() or not path.parts or any(p in {".", ".."} for p in path.parts):
        return False
    for part in path.parts:
        lower = part.lower()
        if (lower in _EXCLUDED_DIRS or lower in _EXCLUDED_NAMES or
                lower == ".env" or lower.startswith(".env.") or lower.endswith(".env") or
                any(token in lower for token in ("credential", "secret", "session-store")) or
                Path(lower).suffix in _EXCLUDED_SUFFIXES):
            return False
    return True


@contextmanager
def _parent_fd(project: Path, name: str, *, create: bool = False):
    """Traverse beneath root with O_NOFOLLOW, including intermediate directories."""
    parts = PurePosixPath(name).parts
    if not parts or PurePosixPath(name).is_absolute() or any(p in {".", ".."} for p in parts):
        raise CheckpointError(f"unsafe path: {name!r}")
    fd = os.open(project, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        for part in parts[:-1]:
            if create:
                try:
                    os.mkdir(part, dir_fd=fd)
                except FileExistsError:
                    pass
            child = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
            os.close(fd)
            fd = child
        yield fd, parts[-1]
    finally:
        os.close(fd)


def _read(project: Path, name: str) -> tuple[bytes, int]:
    with _parent_fd(project, name) as (parent, leaf):
        fd = os.open(leaf, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=parent)
        with os.fdopen(fd, "rb") as stream:
            mode = os.fstat(stream.fileno()).st_mode
            if not stat.S_ISREG(mode):
                raise CheckpointError(f"not a regular file: {name}")
            return stream.read(), 0o100755 if mode & 0o111 else 0o100644


def _capture(project: Path) -> tuple[dict[str, tuple[bytes, int]], list[str]]:
    files: dict[str, tuple[bytes, int]] = {}
    warnings: list[str] = []
    for root, dirs, names in os.walk(project, followlinks=False):
        rel = Path(root).relative_to(project)
        dirs[:] = sorted(d for d in dirs if durable_path((rel / d).as_posix())
                         and not (Path(root) / d).is_symlink())
        for leaf in sorted(names):
            name = (rel / leaf).as_posix()
            if not durable_path(name) or (project / name).is_symlink():
                continue
            try:
                value = _read(project, name)
            except (OSError, CheckpointError) as exc:
                warnings.append(f"unreadable live file {name}: {type(exc).__name__}")
                continue
            if _SECRET.search(value[0]):
                warnings.append(f"excluded possible secret: {name}")
                continue
            files[name] = value
    return files, warnings


def _inspect(files: dict[str, tuple[bytes, int]]) -> tuple[list[str], int]:
    """Validate only captured bytes. Never read or repair the live truth stores."""
    warnings: list[str] = []
    facts = {PurePosixPath(n).stem for n in files
             if n.startswith("fact_graph/facts/") and n.endswith(".md")}
    for name, (data, _) in files.items():
        if name.endswith((".json", ".jsonl")):
            try:
                text = data.decode("utf-8")
                if name.endswith(".jsonl"):
                    for line in text.split("\n"):
                        if line.strip():
                            json.loads(line)
                else:
                    value = json.loads(text)
                    if name == "project.json":
                        roster = value.get("workers") if isinstance(value, dict) else None
                        if not isinstance(roster, list) or any(
                                not isinstance(worker, str) or
                                not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]*", worker)
                                for worker in roster):
                            warnings.append("malformed project worker roster: project.json")
            except (ValueError, UnicodeError):
                warnings.append(f"malformed JSON/JSONL: {name}")
        if name.startswith("fact_graph/facts/") and name.endswith(".md"):
            try:
                text = data.decode("utf-8")
            except UnicodeError:
                warnings.append(f"malformed fact UTF-8: {name}")
                continue
            match = re.search(r"^predecessors:[ \t]*\[([^\n]*)\][ \t]*$", text, re.M)
            identity = re.search(r"^fact_id:[ \t]*([0-9a-f]{16})[ \t]*$", text, re.M)
            if (not text.startswith("---\n") or "\n---\n" not in text or not match or
                    not identity or identity[1] != PurePosixPath(name).stem or
                    "\n## statement\n" not in text or "\n## proof\n" not in text):
                warnings.append(f"malformed fact: {name}")
            statement_tail = text.partition("\n## statement\n")[2]
            statement, separator, proof = statement_tail.partition("\n## proof\n")
            proof = proof.partition("\n## intuition\n")[0]
            if not separator or not statement.strip() or not proof.strip():
                warnings.append(f"malformed fact empty statement/proof: {name}")
            refs = re.search(r"^external_refs:[ \t]*(.*)$", text, re.M)
            if refs:
                try:
                    if not isinstance(json.loads(refs[1]), list):
                        raise ValueError("external_refs must be a list")
                except ValueError:
                    warnings.append(f"malformed fact external_refs JSON: {name}")
            if match:
                for pred in match[1].split(","):
                    pred = pred.strip().strip("\"'")
                    if pred and pred not in facts:
                        warnings.append(f"dangling dependency: {name} -> {pred}")
    return warnings, len(facts)


def _tags(project: Path) -> list[str]:
    repo, _ = _paths(project)
    if not repo.exists():
        return []
    names = _git(project, "tag", "--list", "snap-*").decode().splitlines()
    return sorted((n for n in names if _TAG.fullmatch(n)), key=lambda n: int(n[5:]))


def _tree_files(project: Path, tag: str) -> dict[str, tuple[bytes, int]]:
    if not _TAG.fullmatch(tag):
        raise CheckpointError(f"invalid snapshot name: {tag!r}")
    files = {}
    for row in _git(project, "ls-tree", "-rz", f"refs/tags/{tag}").split(b"\0"):
        if not row:
            continue
        header, raw_name = row.split(b"\t", 1)
        mode, kind, oid = header.decode().split()
        name = raw_name.decode("utf-8")
        if name == MANIFEST:
            continue
        if not durable_path(name) or kind != "blob" or mode not in {"100644", "100755"}:
            raise CheckpointError(f"unsafe snapshot path/type: {name}")
        data = _git(project, "cat-file", "blob", oid)
        if _SECRET.search(data):
            raise CheckpointError(f"snapshot contains possible secret: {name}")
        files[name] = (data, int(mode, 8))
    return files


def _manifest(project: Path, tag: str) -> dict:
    if not _TAG.fullmatch(tag):
        raise CheckpointError(f"invalid snapshot name: {tag!r}")
    value = json.loads(_git(project, "show", f"refs/tags/{tag}:{MANIFEST}"))
    if not isinstance(value, dict) or value.get("version") != 1 or value.get("project") != project.name:
        raise CheckpointError("unsupported or wrong-project snapshot manifest")
    tree = value.get("content_tree", "")
    if not isinstance(tree, str) or not re.fullmatch(r"[0-9a-f]{40}", tree):
        raise CheckpointError("invalid manifest content tree")
    actual = _git(project, "ls-tree", "-rz", f"refs/tags/{tag}")
    actual = b"\0".join(row for row in actual.split(b"\0")
                         if row and row.split(b"\t", 1)[1] != MANIFEST.encode())
    expected = _git(project, "ls-tree", "-rz", tree).rstrip(b"\0")
    if actual != expected:
        raise CheckpointError("snapshot tree differs from immutable manifest content tree")
    return value


def _code_revision() -> str | None:
    root = Path(__file__).resolve().parent.parent
    # Explicit code repository lookup; never discovers the project's outer repo.
    if not (root / ".git").exists():
        return None
    try:
        result = subprocess.run(["git", f"--git-dir={root / '.git'}", "rev-parse", "HEAD"],
                                capture_output=True, text=True, check=True,
                                env={k: v for k, v in os.environ.items() if not k.startswith("GIT_")})
        return result.stdout.strip()
    except subprocess.CalledProcessError:
        return None


def _worker_metadata(project: Path) -> dict:
    result = {}
    workers = project / "workers"
    if workers.is_dir() and not workers.is_symlink():
        for worker in sorted(workers.iterdir()):
            if not worker.is_dir() or worker.is_symlink():
                continue
            try:
                status = json.loads(_read(project, f"workers/{worker.name}/.status.json")[0])
                if isinstance(status, dict) and not _SECRET.search(json.dumps(status).encode()):
                    result[worker.name] = {key: status[key] for key in
                                          ("round", "session_id", "last_session_id", "last_run_id", "last_fact_id")
                                          if key in status}
            except (OSError, ValueError, CheckpointError):
                pass
    return result


def _publish(project: Path, files: dict[str, tuple[bytes, int]], trigger: dict,
             warnings: list[str], *, force: bool = False) -> dict:
    """Called under checkpoint lock. Tag publication is the final Git operation."""
    repo, state = _paths(project)
    if not repo.exists():
        _git(project, "init", "--bare")
    tags = _tags(project)
    previous = tags[-1] if tags else None
    fd, index = tempfile.mkstemp(prefix="index-", dir=state)
    os.close(fd)
    os.unlink(index)  # Git requires an absent or valid index, not an empty file.
    try:
        _git(project, "read-tree", "--empty", index=index)
        entries = []
        for name, (data, mode) in sorted(files.items()):
            oid = _git(project, "hash-object", "-w", "--stdin", data=data).strip()
            entries.append(f"{mode:o} ".encode() + oid + b"\t" + name.encode() + b"\0")
        if entries:
            _git(project, "update-index", "-z", "--index-info", data=b"".join(entries), index=index)
        content_tree = _git(project, "write-tree", index=index).decode().strip()
        integrity, fact_count = _inspect(files)
        warnings = warnings + integrity
        if previous and not force and _manifest(project, previous).get("content_tree") == content_tree:
            return {"snapshot": previous, "tag": previous, "changed": False, "warnings": warnings}
        manifest = {"version": 1, "project": project.name, "code_revision": _code_revision(),
                    "created_at": datetime.now(timezone.utc).isoformat(), "trigger": trigger,
                    "consistency": "best-effort-live", "content_tree": content_tree,
                    "fact_count": fact_count, "file_count": len(files), "warnings": warnings,
                    "workers": _worker_metadata(project)}
        blob = _git(project, "hash-object", "-w", "--stdin",
                    data=json.dumps(manifest, sort_keys=True, ensure_ascii=False).encode()).strip()
        _git(project, "update-index", "--add", "--cacheinfo", f"100644,{blob.decode()},{MANIFEST}", index=index)
        tree = _git(project, "write-tree", index=index).decode().strip()
        args = ["commit-tree", tree]
        if previous:
            args += ["-p", f"refs/tags/{previous}"]
        kind = str(trigger.get("kind") or "snapshot").replace("\n", " ")
        round_note = f" round {trigger['round']}" if "round" in trigger else ""
        subject = f"Snapshot {kind}{round_note}; {fact_count} facts"
        message = subject + "\n"
        if trigger.get("message"):
            message += "\n" + str(trigger["message"]).strip() + "\n"
        session = trigger.get("session_id") or os.environ.get("DSH_SESSION_ID")
        if session and re.fullmatch(r"[A-Za-z0-9._:-]{1,128}", str(session)):
            message += f"\nDSH-session: {session}\n"
        commit = _git(project, *args, data=message.encode()).decode().strip()
        tag = f"snap-{int(previous[5:]) + 1 if previous else 1}"
        # Expected nonexistent old value makes even an unexpected collision fail.
        _git(project, "update-ref", f"refs/tags/{tag}", commit, "0" * 40)
        return {"snapshot": tag, "tag": tag, "changed": True, "warnings": warnings,
                "manifest": manifest}
    finally:
        if os.path.exists(index):
            os.unlink(index)


def request_snapshot(project_dir: Path, trigger: dict) -> dict:
    project = _project(project_dir)
    if not isinstance(trigger, dict) or _SECRET.search(json.dumps(trigger).encode()):
        raise CheckpointError("invalid trigger or possible secret in snapshot metadata")
    with _lock(project, "checkpoint.lock") as state:
        if (state / "restore.json").exists():
            raise CheckpointError("interrupted restore: recover before creating snapshots")
        files, warnings = _capture(project)
        return _publish(project, files, trigger, warnings)


def snapshot(project_dir: Path, message: str | None = None) -> dict:
    return request_snapshot(project_dir, {"kind": "manual", "message": message})


def list_snapshots(project_dir: Path) -> list[dict]:
    project = _project(project_dir)
    with _lock(project, "checkpoint.lock"):
        return [{"snapshot": tag, **_manifest(project, tag)} for tag in _tags(project)]


def _affected(name: str, worker: str | None) -> bool:
    return worker is None or name.startswith(f"workers/{worker}/")


def _validate_destinations(project: Path, names) -> None:
    for name in names:
        if not durable_path(name):
            raise CheckpointError(f"unsafe restore path: {name}")
        path = project
        parts = PurePosixPath(name).parts
        for i, part in enumerate(parts):
            path = path / part
            if path.is_symlink():
                raise CheckpointError(f"restore refuses symlink destination: {name}")
            if path.exists() and ((i < len(parts) - 1 and not path.is_dir()) or
                                  (i == len(parts) - 1 and not path.is_file())):
                raise CheckpointError(f"restore path type conflict: {name}")


def worker_child_identity(worker_dir: Path) -> dict | None:
    """Read the runtime's durable child lease without following a symlink."""
    project = _project(worker_dir.parents[1])
    try:
        data, _ = _read(project, f"workers/{validate_name(worker_dir.name)}/.dsh-child.json")
    except FileNotFoundError:
        return None
    try:
        identity = json.loads(data)
        if (not isinstance(identity, dict) or not isinstance(identity.get("pid"), int) or
                isinstance(identity["pid"], bool) or identity["pid"] <= 1):
            raise ValueError("invalid pid")
        ticks = identity.get("start_ticks")
        if ticks is not None and (not isinstance(ticks, str) or not ticks.isdigit()):
            raise ValueError("invalid start ticks")
        return identity
    except (ValueError, UnicodeError) as exc:
        raise CheckpointError(f"malformed child identity; inspect {worker_dir.name}/.dsh-child.json") from exc


def process_group_alive(pgid: int) -> bool:
    """Ignore Linux zombies but include live descendants after the leader exits."""
    try:
        os.killpg(pgid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    proc = Path("/proc")
    if not proc.is_dir():
        return True
    for path in proc.iterdir():
        if not path.name.isdigit():
            continue
        try:
            fields = (path / "stat").read_text().rsplit(")", 1)[1].split()
            if int(fields[2]) == pgid and fields[0] != "Z":
                return True
        except (OSError, ValueError, IndexError):
            continue
    return False


def worker_child_active(identity: dict | None) -> bool:
    if identity is None:
        return False
    from danus import dsh
    from danus.orchestration.cli import _alive
    observed = dsh.process_identity(identity["pid"])
    if (identity.get("start_ticks") is not None and observed["start_ticks"] is not None and
            identity["start_ticks"] != observed["start_ticks"]):
        return False  # definitely a recycled PID, not this worker's child
    return (dsh.is_same_process(identity) and _alive(identity["pid"])) or process_group_alive(identity["pid"])


def _ensure_stopped(project: Path, worker: str | None) -> None:
    from danus.orchestration.cli import _alive
    workers = project / "workers"
    if workers.is_symlink():
        raise CheckpointError("unsafe workers directory symlink")
    paths = [workers / worker] if worker else (list(workers.iterdir()) if workers.exists() else [])
    for path in paths:
        if path.is_symlink():
            raise CheckpointError(f"unsafe worker directory: {path.name}")
        for name in (".pid", ".stop", ".status.json", ".session", ".session_id", ".session.json",
                     ".dsh-session", ".dsh-session.json", ".dsh-child.json"):
            metadata = path / name
            if metadata.is_symlink() or (metadata.exists() and not metadata.is_file()):
                raise CheckpointError(f"unsafe process metadata: {metadata}")
        try:
            pid = int((path / ".pid").read_text().strip())
        except (OSError, ValueError):
            pid = None
        if _alive(pid):
            raise CheckpointError(f"stop affected worker before restore: {path.name}")
        if path.is_dir() and worker_child_active(worker_child_identity(path)):
            raise CheckpointError(f"stop live/orphaned DSH child before restore: {path.name}")
    # A main session may be idle, but no project-writing main activity can run.
    # CLI confirmation is the operator assertion for direct writers, which have
    # no lock protocol. An optional lease allows managed main launchers to refuse.
    for name in (".main.pid", ".main-writing.pid"):
        if (project / name).is_symlink():
            raise CheckpointError(f"unsafe main process metadata: {name}")
        try:
            pid = int((project / name).read_text().strip())
        except (OSError, ValueError):
            continue
        if _alive(pid):
            raise CheckpointError("stop project-writing main activity before restore")


def _apply(project: Path, desired: dict[str, tuple[bytes, int]], current: dict,
           worker: str | None) -> None:
    names = {n for n in desired.keys() | current.keys() if _affected(n, worker)}
    _validate_destinations(project, names)
    for name in sorted(names):
        if name not in desired:
            with _parent_fd(project, name) as (parent, leaf):
                os.unlink(leaf, dir_fd=parent)
                os.fsync(parent)
            continue
        data, mode = desired[name]
        with _parent_fd(project, name, create=True) as (parent, leaf):
            temporary = f".checkpoint-{uuid.uuid4().hex}.tmp"
            fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                         0o600, dir_fd=parent)
            try:
                with os.fdopen(fd, "wb") as out:
                    out.write(data)
                    out.flush()
                    os.fchmod(out.fileno(), mode & 0o777)
                    os.fsync(out.fileno())
                os.replace(temporary, leaf, src_dir_fd=parent, dst_dir_fd=parent)
                os.fsync(parent)
            finally:
                try:
                    os.unlink(temporary, dir_fd=parent)
                except FileNotFoundError:
                    pass


def _clear_process_state(project: Path, worker: str | None) -> None:
    workers = project / "workers"
    if not workers.is_dir():
        return
    for path in workers.iterdir():
        if path.is_symlink() or not path.is_dir() or (worker and path.name != worker):
            continue
        for name in (".pid", ".stop", ".status.json", ".session", ".session_id", ".session.json",
                     ".dsh-session", ".dsh-session.json", ".dsh-child.json"):
            target = path / name
            if target.is_symlink():
                raise CheckpointError(f"unsafe process metadata: {target}")
            if target.is_file():
                target.unlink()
        _atomic(path / ".status.json", b'{"state":"stopped","round":0}\n')
    if not worker:
        (project / ".run_deadline").unlink(missing_ok=True)


def recover_restore(project_dir: Path) -> dict:
    """Roll back an interrupted restore from its immutable before-restore backup.

    Gateway mutations remain fail-closed until this completes. This recovery does
    not discard history or pretend an inconsistent live backup was transactional.
    """
    project = _project(project_dir)
    with mutation_lock(project, restoring=True) as state:
        marker = state / "restore.json"
        if not marker.exists():
            return {"recovered": False}
        record = json.loads(marker.read_text())
        worker = record.get("worker")
        if worker:
            validate_name(worker)
        _ensure_stopped(project, worker)
        with _lock(project, "checkpoint.lock"):
            _manifest(project, record["backup"])
            backup = _tree_files(project, record["backup"])
            current, _ = _capture(project)
            _apply(project, backup, current, worker)
            _clear_process_state(project, worker)
            _atomic(state / "generation", uuid.uuid4().hex.encode())
            marker.unlink()
        return {"recovered": True, "backup": record["backup"]}


def restore(project_dir: Path, snapshot: str, *, worker: str | None = None,
            dry_run: bool = False, yes: bool = False,
            allow_inconsistent: bool = False) -> dict:
    """Preview or restore a stopped project. ``yes`` also asserts main is stopped.

    Full restore replaces only durable paths; worker restore leaves all shared
    state untouched. Runtime configs/links are regenerated by worker start.
    """
    project = _project(project_dir)
    if worker:
        validate_name(worker)
    with mutation_lock(project) as state:
        _ensure_stopped(project, worker)
        with _lock(project, "checkpoint.lock"):
            _manifest(project, snapshot)
            desired = _tree_files(project, snapshot)
            if worker and not any(_affected(n, worker) for n in desired):
                raise CheckpointError(f"worker not present in snapshot: {worker}")
            current, capture_warnings = _capture(project)
            warnings, _ = _inspect(desired)
            if worker:
                # Worker notes can cite arbitrary IDs; only best-effort validation
                # is possible without interpreting private mathematical prose.
                warnings.append("worker-only restore: shared state remains current; worker references may be stale")
                integrity = [w for w in warnings if f"workers/{worker}/" in w]
                live_facts = {PurePosixPath(n).stem for n in current
                              if n.startswith("fact_graph/facts/") and n.endswith(".md")}
                for name, (data, _) in desired.items():
                    if _affected(name, worker):
                        candidates = set(re.findall(rb"\b[0-9a-f]{16}\b", data))
                        for candidate in sorted(candidates):
                            fact_id = candidate.decode()
                            if fact_id not in live_facts:
                                warnings.append(f"possible stale worker fact reference: {name} -> {fact_id} (not in current graph)")
            else:
                integrity = warnings
            if integrity and not allow_inconsistent:
                raise CheckpointError("inconsistent snapshot (use --allow-inconsistent): " + "; ".join(integrity))
            names = {n for n in current.keys() | desired.keys() if _affected(n, worker)}
            _validate_destinations(project, names)
            for name in names:
                if name in desired and name not in current and (project / name).exists():
                    raise CheckpointError(f"cannot safely back up excluded/unreadable destination: {name}")
            unreadable = [w for w in capture_warnings if w.startswith("unreadable live file")
                          and (not worker or f"workers/{worker}/" in w)]
            if unreadable:
                raise CheckpointError("cannot back up all affected files: " + "; ".join(unreadable))
            result: dict[str, Any] = {"snapshot": snapshot, "worker": worker,
                "write": sorted(n for n in names if n in desired and current.get(n) != desired[n]),
                "delete": sorted(n for n in names if n not in desired),
                "warnings": warnings + capture_warnings, "dry_run": dry_run,
                "requires": "affected workers and all project-writing main activity stopped"}
            if dry_run:
                return result
            if not yes:
                raise CheckpointError("restore requires confirmation; preview with --dry-run, then pass --yes after stopping main writes")
            # Immutable backup even when bytes are unchanged or inconsistent.
            backup = _publish(project, current, {"kind": "before-restore", "target": snapshot,
                              "worker": worker}, capture_warnings, force=True)
            result["backup"] = backup["snapshot"]
            _atomic(state / "restore.json", json.dumps({"backup": backup["snapshot"],
                    "target": snapshot, "worker": worker}).encode())
            # Advance before any durable mutation, rejecting already-running verifies.
            _atomic(state / "generation", uuid.uuid4().hex.encode())
            _apply(project, desired, current, worker)
            _clear_process_state(project, worker)
            (state / "restore.json").unlink()
            return result


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Internal best-effort checkpoint hook")
    sub = parser.add_subparsers(dest="command", required=True)
    request = sub.add_parser("request-all")
    request.add_argument("--session-id", required=True)
    request.add_argument("--turn-id", required=True)
    args = parser.parse_args(argv)
    from danus.execution import layout as L
    rows = []
    if os.environ.get("DANUS_SNAPSHOT_AUTO", "1") == "0":
        return 0
    for name in L.list_projects():
        try:
            project = L.project_dir(validate_name(name))
            if not (project / "project.json").is_file():
                continue
            rows.append({"project": name, **request_snapshot(project, {
                "kind": "main-completion", "session_id": args.session_id, "turn_id": args.turn_id})})
        except Exception as exc:
            rows.append({"project": name, "error": str(exc)})
    print(json.dumps(rows, ensure_ascii=False))
    return 1 if any("error" in row for row in rows) else 0


if __name__ == "__main__":
    raise SystemExit(main())
