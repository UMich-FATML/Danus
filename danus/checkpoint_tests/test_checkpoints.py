"""Real Git integration tests; no model calls or live mathematical projects."""
import concurrent.futures
import json
import os
from pathlib import Path
import subprocess
import threading

import pytest

from danus import checkpoints as C
from danus.core import FactGraph, GlobalMemory
from danus.gateway import server
from danus.orchestration import cli


@pytest.fixture
def project(tmp_path, monkeypatch):
    root = tmp_path / "runtime" / "projects"
    p = root / "demo"
    (p / "workers" / "high" / "local_memory").mkdir(parents=True)
    (p / "workers" / "other").mkdir()
    (p / "project.json").write_text('{"name":"demo","workers":["high","other"]}')
    (p / "PROBLEM.md").write_text("Problem\n")
    (p / "workers/high/TASK.md").write_text("old task\n")
    (p / "workers/high/.role").write_text("ROLE=high\n")
    (p / "workers/high/local_memory/notes.md").write_text("old notes\n")
    (p / "workers/other/TASK.md").write_text("other old\n")
    monkeypatch.setenv("DANUS_AGENTS_ROOT", str(root))
    monkeypatch.setenv("DANUS_PROJECT_DIR", str(p))
    return p


def put(project, name, text):
    path = project / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    return path


def test_snapshot_git_isolation_filters_and_manifest(project, tmp_path, monkeypatch):
    subprocess.run(["git", "init", str(tmp_path)], check=True, capture_output=True)
    before = subprocess.run(["git", "-C", str(tmp_path), "status", "--porcelain"], capture_output=True).stdout
    put(project, "papers/paper/main.tex", "paper source")
    put(project, "TARGET.md", "target")
    for name in (".env", "workers/high/.dsh/config.json", "workers/high/logs/round.log",
                 "workers/high/.session_id", "workers/high/.pid", "build/output.md",
                 "papers/paper/main.pdf", "config/key.env", "credentials.json",
                 "papers/paper/.runs/run/log.md", ".main.pid", ".main-writing.pid"):
        put(project, name, "excluded")
    put(project, "workers/high/.status.json", '{"round":3,"last_session_id":"session-1"}')
    put(project, "accidental.md", "api_key=verysecret1234")
    external = tmp_path / "outside.txt"
    external.write_text("must not follow")
    (project / "link.md").symlink_to(external)
    (project / "workers/high/AGENTS.md").symlink_to(external)
    monkeypatch.setenv("GIT_DIR", str(tmp_path / ".git"))
    monkeypatch.setenv("GIT_INDEX_FILE", str(tmp_path / "poison-index"))
    result = C.snapshot(project, "initial")
    assert result["snapshot"] == "snap-1"
    files = C._tree_files(project, "snap-1")
    assert set(files) == {"project.json", "PROBLEM.md", "TARGET.md", "papers/paper/main.tex",
                          "workers/high/TASK.md", "workers/high/.role",
                          "workers/high/local_memory/notes.md", "workers/other/TASK.md"}
    manifest = result["manifest"]
    assert manifest["version"] == 1 and manifest["workers"]["high"]["round"] == 3
    assert manifest["fact_count"] == 0
    assert any("secret" in w for w in manifest["warnings"])
    repo, _ = C._paths(project)
    assert repo == tmp_path / "runtime/.gitstore/demo.git"
    assert repo.is_dir() and not (project / ".git").exists()
    assert not (tmp_path / "poison-index").exists()
    assert not (tmp_path / ".git/index").exists()
    # No command accidentally initialized or staged the outer repo.
    assert not list((tmp_path / ".git/refs/tags").iterdir())
    assert before


def test_unchanged_trigger_and_live_counters_do_not_create_commit(project):
    first = C.request_snapshot(project, {"kind": "round", "timestamp": 1})
    put(project, "workers/high/.status.json", '{"round":2}')
    second = C.request_snapshot(project, {"kind": "round", "timestamp": 2})
    assert first["changed"] and not second["changed"]
    assert len(C.list_snapshots(project)) == 1


def test_concurrent_checkpoints_serialize_without_writer_barrier(project):
    # A held gateway mutation lock must not block snapshotting.
    with C.mutation_lock(project):
        with concurrent.futures.ThreadPoolExecutor(max_workers=6) as pool:
            futures = [pool.submit(C.snapshot, project) for _ in range(6)]
            results = [future.result(timeout=10) for future in futures]
    assert sum(r["changed"] for r in results) == 1
    assert len(C.list_snapshots(project)) == 1


def test_manifest_counts_staged_not_later_live_tree(project, monkeypatch):
    fg = FactGraph(project)
    fg.add(problem_id="P", author="test", statement="one", proof="proof")
    original = C._publish
    def late_write(p, files, trigger, warnings, **kw):
        fg.add(problem_id="P", author="test", statement="two", proof="proof")
        return original(p, files, trigger, warnings, **kw)
    monkeypatch.setattr(C, "_publish", late_write)
    snap = C.snapshot(project)
    assert snap["manifest"]["fact_count"] == 1
    assert len(fg.list()) == 2


def test_failed_publication_has_no_visible_tag(project, monkeypatch):
    original = C._git
    def fail(p, *args, **kw):
        if args[0] == "update-ref":
            raise C.CheckpointError("injected publication failure")
        return original(p, *args, **kw)
    monkeypatch.setattr(C, "_git", fail)
    with pytest.raises(C.CheckpointError, match="injected"):
        C.snapshot(project)
    assert C.list_snapshots(project) == []
    monkeypatch.setattr(C, "_git", original)
    assert C.snapshot(project)["snapshot"] == "snap-1"


def test_full_restore_preview_backup_and_history(project):
    C.snapshot(project)
    put(project, "PROBLEM.md", "changed")
    put(project, "new-note.md", "new")
    put(project, "workers/high/.pid", "99999999")
    put(project, "workers/high/.status.json", '{"state":"running","last_session_id":"old"}')
    put(project, "workers/high/logs/keep.log", "log")
    put(project, ".run_deadline", "123")
    generation = C.project_generation(project)
    preview = C.restore(project, "snap-1", dry_run=True)
    assert preview["delete"] == ["new-note.md"]
    assert (project / "PROBLEM.md").read_text() == "changed"
    assert len(C.list_snapshots(project)) == 1
    with pytest.raises(C.CheckpointError, match="confirmation"):
        C.restore(project, "snap-1")
    result = C.restore(project, "snap-1", yes=True)
    assert result["backup"] == "snap-2"
    assert C._tree_files(project, "snap-2")["PROBLEM.md"][0] == b"changed"
    assert (project / "PROBLEM.md").read_text() == "Problem\n"
    assert not (project / "new-note.md").exists()
    assert not (project / "workers/high/.pid").exists()
    assert (project / "workers/high/logs/keep.log").read_text() == "log"
    assert json.loads((project / "workers/high/.status.json").read_text())["state"] == "stopped"
    assert C.project_generation(project) != generation
    assert not (project / ".run_deadline").exists()
    assert len(C.list_snapshots(project)) == 2


def test_partial_restore_leaves_shared_and_other_worker_current(project):
    C.snapshot(project)
    put(project, "PROBLEM.md", "new shared")
    put(project, "workers/high/TASK.md", "new task")
    put(project, "workers/other/TASK.md", "new other")
    put(project, "workers/other/.pid", str(os.getpid()))
    result = C.restore(project, "snap-1", worker="high", yes=True)
    assert (project / "workers/high/TASK.md").read_text() == "old task\n"
    assert (project / "workers/other/TASK.md").read_text() == "new other"
    assert (project / "PROBLEM.md").read_text() == "new shared"
    assert any("references" in w for w in result["warnings"])


def test_restore_rejects_live_workers_and_main(project):
    C.snapshot(project)
    pid = put(project, "workers/high/.pid", str(os.getpid()))
    with pytest.raises(C.CheckpointError, match="stop affected worker"):
        C.restore(project, "snap-1", yes=True)
    pid.unlink()
    put(project, ".main-writing.pid", str(os.getpid()))
    with pytest.raises(C.CheckpointError, match="main activity"):
        C.restore(project, "snap-1", yes=True)


def test_inconsistent_snapshot_warns_and_restore_requires_override(project):
    put(project, "global_memory/plan.jsonl", '{"ok":1}\n{broken')
    FactGraph(project).add(problem_id="P", author="test", statement="one", proof="proof",
                           predecessors=["missing"])
    result = C.snapshot(project)
    assert any("malformed JSON" in w for w in result["warnings"])
    assert any("dangling dependency" in w for w in result["warnings"])
    with pytest.raises(C.CheckpointError, match="inconsistent"):
        C.restore(project, "snap-1", yes=True)
    C.restore(project, "snap-1", yes=True, allow_inconsistent=True)
    assert len(C.list_snapshots(project)) == 2  # backup even unchanged inconsistent bytes
    assert (project / "global_memory/plan.jsonl").read_text().endswith("{broken")


def test_restore_failure_marker_blocks_gateway_then_recovers(project, monkeypatch):
    C.snapshot(project)
    put(project, "PROBLEM.md", "before restore")
    original = C._apply
    def fail(*args):
        put(project, "PROBLEM.md", "partial corruption")
        raise OSError("injected interrupted restore")
    monkeypatch.setattr(C, "_apply", fail)
    with pytest.raises(OSError, match="injected"):
        C.restore(project, "snap-1", yes=True)
    with pytest.raises(C.CheckpointError, match="interrupted"):
        server.gm_add("plan", "must not land")
    with pytest.raises(C.CheckpointError, match="interrupted"):
        C.snapshot(project)
    monkeypatch.setattr(C, "_apply", original)
    assert C.recover_restore(project)["recovered"]
    assert (project / "PROBLEM.md").read_text() == "before restore"
    assert server.gm_add("plan", "now writable")["id"]


def test_outstanding_verifier_result_cannot_cross_restore_generation(project, monkeypatch):
    C.snapshot(project)
    entered, resume = threading.Event(), threading.Event()
    def verify(statement, proof):
        entered.set()
        assert resume.wait(10)
        return {"verdict": "correct"}
    monkeypatch.setattr(server, "_verify", verify)
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
        pending = pool.submit(server.fact_submit, "old result", "proof",
                              glossary_introduces={"X": "old glossary"})
        assert entered.wait(10)
        C.restore(project, "snap-1", yes=True)
        resume.set()
        result = pending.result(timeout=10)
    assert not result["accepted"] and "restored" in result["error"]
    assert FactGraph(project).list() == []
    assert not (project / "fact_graph/glossary.json").exists()
    assert GlobalMemory(project).read("verification") == []


def test_invalid_paths_and_symlink_destination_refuse_before_backup(project, tmp_path):
    C.snapshot(project)
    for name in ("../demo", "/tmp", "a/b", ".", ".."):
        with pytest.raises(C.CheckpointError):
            C.restore(project, "snap-1", worker=name, yes=True)
    with pytest.raises(C.CheckpointError):
        C.restore(project, "HEAD", yes=True)
    target = project / "PROBLEM.md"
    target.unlink()
    outside = tmp_path / "outside"
    outside.write_text("do not touch")
    target.symlink_to(outside)
    with pytest.raises(C.CheckpointError, match="symlink"):
        C.restore(project, "snap-1", yes=True)
    assert outside.read_text() == "do not touch"
    assert len(C.list_snapshots(project)) == 1


def test_cli_snapshot_list_restore_and_path_validation(project, capsys):
    assert cli.main(["snapshot", "demo", "--message", "test"]) == 0
    assert "snap-1" in capsys.readouterr().out
    assert cli.main(["snapshots", "demo", "--json"]) == 0
    assert json.loads(capsys.readouterr().out)[0]["snapshot"] == "snap-1"
    put(project, "PROBLEM.md", "changed")
    assert cli.main(["restore", "demo", "snap-1", "--dry-run"]) == 0
    capsys.readouterr()
    assert (project / "PROBLEM.md").read_text() == "changed"
    assert cli.main(["restore", "demo", "snap-1", "--yes"]) == 0
    capsys.readouterr()
    with pytest.raises(SystemExit, match="unsafe"):
        cli.main(["snapshot", "../demo"])


def test_live_writer_can_pause_mid_json_while_snapshot_finishes(project):
    path = put(project, "global_memory/plan.jsonl", "")
    halfway, finish = threading.Event(), threading.Event()
    def writer():
        with path.open("w") as stream:
            stream.write('{"claim":')
            stream.flush()
            halfway.set()
            assert finish.wait(10)
            stream.write('"complete"}\n')
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
        pending = pool.submit(writer)
        assert halfway.wait(10)
        try:
            snap = C.snapshot(project)
            assert any("malformed JSON/JSONL" in w for w in snap["warnings"])
        finally:
            finish.set()
        pending.result(timeout=10)
    assert json.loads(path.read_text()) == {"claim": "complete"}


def test_unicode_jsonl_separator_is_not_record_boundary(project):
    put(project, "global_memory/plan.jsonl", json.dumps({"claim": "before\u2028after"}, ensure_ascii=False) + "\n")
    assert C.snapshot(project)["warnings"] == []


def test_worker_reference_warnings_and_commit_provenance(project):
    put(project, "workers/high/TASK.md", "Use 0123456789abcdef and fedcba9876543210")
    result = C.request_snapshot(project, {"kind": "worker", "round": 7, "session_id": "session-123"})
    message = C._git(project, "log", "-1", "--format=%B", "refs/tags/snap-1").decode()
    assert "round 7" in message and "0 facts" in message and "DSH-session: session-123" in message
    preview = C.restore(project, result["snapshot"], worker="high", dry_run=True)
    assert any("0123456789abcdef" in w for w in preview["warnings"])
    assert any("fedcba9876543210" in w for w in preview["warnings"])


def test_secret_json_and_trigger_are_not_stored(project):
    put(project, "note.json", '{"api_key": "opaque-value-012345"}')
    with pytest.raises(C.CheckpointError, match="secret"):
        C.request_snapshot(project, {"message": "password=opaque-value-012345"})
    result = C.snapshot(project)
    assert "note.json" not in C._tree_files(project, result["snapshot"])
    assert any("excluded possible secret" in w for w in result["warnings"])


def test_restore_cannot_overwrite_an_unbacked_secret(project):
    C.snapshot(project)
    put(project, "PROBLEM.md", "api_key=opaque-value-012345")
    with pytest.raises(C.CheckpointError, match="cannot safely back up"):
        C.restore(project, "snap-1", yes=True)
    assert len(C.list_snapshots(project)) == 1
    assert (project / "PROBLEM.md").read_text() == "api_key=opaque-value-012345"


def test_process_metadata_symlink_rejected_before_any_mutation(project, tmp_path):
    C.snapshot(project)
    put(project, "PROBLEM.md", "changed")
    outside = tmp_path / "outside"
    outside.write_text("outside")
    (project / "workers/high/.status.json").symlink_to(outside)
    with pytest.raises(C.CheckpointError, match="unsafe process"):
        C.restore(project, "snap-1", yes=True)
    assert len(C.list_snapshots(project)) == 1
    assert (project / "PROBLEM.md").read_text() == "changed"
    assert outside.read_text() == "outside"


def test_backup_publication_failure_changes_nothing(project, monkeypatch):
    C.snapshot(project)
    put(project, "PROBLEM.md", "changed")
    generation = C.project_generation(project)
    original = C._git
    def fail(p, *args, **kwargs):
        if args[0] == "update-ref":
            raise C.CheckpointError("backup publication failed")
        return original(p, *args, **kwargs)
    monkeypatch.setattr(C, "_git", fail)
    with pytest.raises(C.CheckpointError, match="backup publication"):
        C.restore(project, "snap-1", yes=True)
    assert (project / "PROBLEM.md").read_text() == "changed"
    assert C.project_generation(project) == generation
    assert len(C.list_snapshots(project)) == 1


def test_checkpoint_lock_serializes_separate_processes(project):
    import sys
    code = ('import json,sys; from pathlib import Path; '
            'from danus.checkpoints import snapshot; '
            'print(json.dumps(snapshot(Path(sys.argv[1]))))')
    processes = [subprocess.Popen([sys.executable, "-c", code, str(project)],
                  stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True) for _ in range(3)]
    try:
        results = []
        for proc in processes:
            stdout, stderr = proc.communicate(timeout=15)
            assert proc.returncode == 0, stderr
            results.append(json.loads(stdout))
        assert sum(result["changed"] for result in results) == 1
        assert {result["snapshot"] for result in results} == {"snap-1"}
    finally:
        for proc in processes:
            if proc.poll() is None:
                proc.kill()
                proc.wait()


def test_request_all_failure_remains_retryable(project, capsys, monkeypatch):
    def fail(*args, **kwargs):
        raise C.CheckpointError("injected git failure")
    monkeypatch.setattr(C, "request_snapshot", fail)
    assert C.main(["request-all", "--session-id", "s", "--turn-id", "1"]) == 1
    assert "injected git failure" in json.loads(capsys.readouterr().out)[0]["error"]


@pytest.mark.parametrize("body", [b"", b"\xff"])
def test_malformed_fact_body_requires_restore_override(project, body):
    fact_id = FactGraph(project).add(problem_id="P", author="w", statement="S", proof="proof")
    path = project / f"fact_graph/facts/{fact_id}.md"
    prefix = path.read_bytes().split(b"\n## proof\n")[0]
    path.write_bytes(prefix + b"\n## proof\n" + body + b"\n")
    result = C.snapshot(project)
    assert any("malformed fact" in warning for warning in result["warnings"])
    with pytest.raises(C.CheckpointError, match="inconsistent"):
        C.restore(project, "snap-1", yes=True)
    assert path.read_bytes().endswith(body + b"\n")


def test_invalid_project_roster_is_captured_but_restore_requires_override(project):
    put(project, "project.json", "[]")
    result = C.snapshot(project)
    assert any("malformed project worker roster" in warning for warning in result["warnings"])
    with pytest.raises(C.CheckpointError, match="inconsistent"):
        C.restore(project, "snap-1", yes=True)


def test_manifest_content_tree_mismatch_refuses_restore(project, tmp_path):
    C.snapshot(project)
    index = str(tmp_path / "test-index")
    C._git(project, "read-tree", "refs/tags/snap-1", index=index)
    blob = C._git(project, "hash-object", "-w", "--stdin", data=b"unexpected bytes").decode().strip()
    C._git(project, "update-index", "--cacheinfo", f"100644,{blob},PROBLEM.md", index=index)
    tree = C._git(project, "write-tree", index=index).decode().strip()
    commit = C._git(project, "commit-tree", tree, data=b"simulate storage corruption\n").decode().strip()
    C._git(project, "update-ref", "refs/tags/snap-1", commit)
    with pytest.raises(C.CheckpointError, match="differs from immutable manifest"):
        C.restore(project, "snap-1", yes=True)
    assert (project / "PROBLEM.md").read_text() == "Problem\n"
    assert C._tags(project) == ["snap-1"]


def test_orphan_dsh_child_blocks_restore_restart_and_force_stop_cleans(project):
    import sys
    from danus import dsh
    child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"], start_new_session=True)
    try:
        put(project, "workers/high/.dsh-child.json", json.dumps(dsh.process_identity(child.pid)))
        C.snapshot(project)
        assert "workers/high/.dsh-child.json" not in C._tree_files(project, "snap-1")
        with pytest.raises(C.CheckpointError, match="orphaned DSH child"):
            C.restore(project, "snap-1", yes=True)
        assert "orphaned-child" in cli.do_start("demo/high")[0]["result"]
        assert "orphaned-child" in cli.do_stop("demo/high")[0]["result"]
        assert cli.do_stop("demo/high", force=True)[0]["result"] == "killed"
        child.wait(timeout=5)
        assert not (project / "workers/high/.dsh-child.json").exists()
        C.restore(project, "snap-1", yes=True)
    finally:
        if child.poll() is None:
            child.kill()
        child.wait()


def test_starting_child_lease_fails_closed(project):
    C.snapshot(project)
    put(project, "workers/high/.dsh-child.json", json.dumps({"state": "starting", "parent": {"pid": 123}}))
    with pytest.raises(C.CheckpointError, match="child identity"):
        C.restore(project, "snap-1", yes=True)
    with pytest.raises(C.CheckpointError, match="child identity"):
        cli.do_start("demo/high")
    assert (project / "workers/high/.dsh-child.json").exists()


def test_orphan_descendants_with_exited_leader_still_block_restore(project):
    import signal
    import sys
    from danus import dsh
    code = ('import subprocess,sys,time; '
            'child=subprocess.Popen([sys.executable,"-c","import time; time.sleep(30)"], '
            'stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL); '
            'print(child.pid,flush=True); time.sleep(0.2)')
    leader = subprocess.Popen([sys.executable, "-c", code], start_new_session=True,
                              stdout=subprocess.PIPE, text=True)
    identity = dsh.process_identity(leader.pid)
    try:
        assert leader.stdout.readline().strip().isdigit()
        leader.wait(timeout=5)
        put(project, "workers/high/.dsh-child.json", json.dumps(identity))
        C.snapshot(project)
        assert C.worker_child_active(identity)
        with pytest.raises(C.CheckpointError, match="orphaned DSH child"):
            C.restore(project, "snap-1", yes=True)
        with pytest.raises(SystemExit, match="cannot safely identify"):
            cli.do_stop("demo/high", force=True)
    finally:
        try:
            os.killpg(leader.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        leader.wait()
        leader.stdout.close()


def test_recycled_child_pid_is_not_killed_or_restore_blocked(project):
    import sys
    from danus import dsh
    child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"], start_new_session=True)
    try:
        identity = dsh.process_identity(child.pid)
        identity["start_ticks"] = str(int(identity["start_ticks"]) + 1)
        put(project, "workers/high/.dsh-child.json", json.dumps(identity))
        C.snapshot(project)
        C.restore(project, "snap-1", yes=True)
        assert child.poll() is None
    finally:
        child.kill()
        child.wait()


def test_worker_only_recovery_leaves_shared_state_and_other_worker_current(project, monkeypatch):
    C.snapshot(project)
    put(project, "workers/high/TASK.md", "before worker restore")
    put(project, "PROBLEM.md", "shared current")
    put(project, "workers/other/TASK.md", "other current")
    original = C._apply
    def fail(*args):
        put(project, "workers/high/TASK.md", "partial worker restore")
        raise OSError("worker interrupted")
    monkeypatch.setattr(C, "_apply", fail)
    with pytest.raises(OSError, match="worker interrupted"):
        C.restore(project, "snap-1", worker="high", yes=True)
    monkeypatch.setattr(C, "_apply", original)
    C.recover_restore(project)
    assert (project / "workers/high/TASK.md").read_text() == "before worker restore"
    assert (project / "workers/other/TASK.md").read_text() == "other current"
    assert (project / "PROBLEM.md").read_text() == "shared current"


def test_request_all_hook_skips_unchanged(project, capsys):
    assert C.main(["request-all", "--session-id", "s", "--turn-id", "1"]) == 0
    assert json.loads(capsys.readouterr().out)[0]["changed"]
    C.main(["request-all", "--session-id", "s", "--turn-id", "2"])
    assert not json.loads(capsys.readouterr().out)[0]["changed"]
