"""Offline end-to-end recovery: real Git, fake DSH, no network or model calls."""
import json
import signal

import pytest

from danus import checkpoints
from danus.execution import layout, loop, scaffold
from danus.orchestration import cli
from danus.tests.dsh_fixture import configured_dsh


def test_worker_checkpoint_restore_and_fresh_restart(tmp_path, monkeypatch):
    fake = tmp_path / "fake-dsh"
    # This fixture records only synthetic test data; it performs no mathematical work.
    fake.write_text(
        "#!/usr/bin/env python3\n"
        "import json, sys, uuid\nfrom pathlib import Path\n"
        "prompt = sys.stdin.read()\n"
        "assert 'TASK.md' in prompt\n"
        "p = Path('local_memory/notes.jsonl')\n"
        "p.parent.mkdir(exist_ok=True)\n"
        "with p.open('a') as f: f.write(json.dumps({'note':'persisted test progress'})+'\\n')\n"
        "print(json.dumps({'type':'session','sessionId':'session-'+str(uuid.uuid4())}))\n"
        "print(json.dumps({'type':'status','phase':'turn_start','turn':1}))\n"
        "print(json.dumps({'type':'status','phase':'turn_end','turn':1,'reason':{'kind':'completed'}}))\n"
        "print(json.dumps({'type':'final','text':'Finished synthetic test round'}))\n"
    )
    fake.chmod(0o755)
    with configured_dsh(tmp_path / "provider"), monkeypatch.context() as patch:
        patch.setenv("DANUS_DSH_BIN", str(fake))
        patch.setenv("DANUS_AGENTS_ROOT", str(tmp_path / "runtime/projects"))
        patch.setenv("DANUS_SNAPSHOT_AUTO", "1")
        patch.setenv("DANUS_MAX_ROUNDS", "1")
        patch.setenv("DANUS_ROUND_BEAT", "0")
        patch.setenv("DANUS_MAIN_MODEL", "m-test")
        scaffold.do_new("demo", roles="high:1", model="m-test")
        cli.do_assign("demo/high", "Original assignment")
        worker = layout.WorkerLayout(layout.worker_dir("demo", "high"))
        before_handler = signal.getsignal(signal.SIGTERM)
        try:
            assert loop.main(str(worker.dir)) == 0
            project = worker.project_dir
            snapshots = checkpoints.list_snapshots(project)
            assert len(snapshots) == 1
            first = snapshots[0]["snapshot"]
            assert snapshots[0]["trigger"]["kind"] == "worker-round"
            assert not (project / ".git").exists()
            assert not (worker.dir / ".git").exists()
            old_logs = {p: p.read_bytes() for p in worker.logs.glob("round_*.log")}
            assert len(old_logs) == 1
            notes = worker.local_memory / "notes.jsonl"
            original = notes.read_bytes()
            old_session = json.loads(worker.status.read_text())["last_session_id"]
            notes.write_text('{"note":"later state"}\n')
            cli.do_assign("demo/high", "Later assignment")
            preview = checkpoints.restore(project, first, dry_run=True)
            assert "workers/high/TASK.md" in preview["write"]
            assert worker.task.read_text() == "Later assignment\n"
            restored = checkpoints.restore(project, first, yes=True)
            assert restored["backup"] != first
            assert notes.read_bytes() == original
            assert worker.task.read_text() == "Original assignment\n"
            assert json.loads(worker.status.read_text())["state"] == "stopped"
            assert loop.main(str(worker.dir)) == 0
            assert json.loads(worker.status.read_text())["last_session_id"] != old_session
            assert len(list(worker.logs.glob("round_*.log"))) == 2
            assert all(p.read_bytes() == contents for p, contents in old_logs.items())
        finally:
            signal.signal(signal.SIGTERM, before_handler)


def test_cancel_before_child_callback_keeps_uncertain_lease(tmp_path, monkeypatch):
    worker = layout.WorkerLayout(tmp_path / "demo/workers/high")
    worker.dir.mkdir(parents=True)
    monkeypatch.setattr(loop._Child, "proc", None)

    def interrupted(*args, **kwargs):
        # Models SIGTERM/SystemExit in the gap after spawn but before on_process.
        kwargs["on_starting"]()
        raise SystemExit(0)

    monkeypatch.setattr(loop.dsh, "run", interrupted)
    with pytest.raises(SystemExit):
        loop.run_round(worker, {"MODEL": "test", "REASONING_EFFORT": "high"},
                       "prompt", worker.dir / "test.log", 1)
    marker = worker.dir / ".dsh-child.json"
    assert json.loads(marker.read_text())["state"] == "starting"
    with pytest.raises(checkpoints.CheckpointError, match="child identity"):
        checkpoints.worker_child_identity(worker.dir)


def test_cancel_during_preflight_leaves_no_child_lease(tmp_path, monkeypatch):
    worker = layout.WorkerLayout(tmp_path / "demo/workers/high")
    worker.dir.mkdir(parents=True)
    monkeypatch.setattr(loop._Child, "proc", None)

    def interrupted(*args, **kwargs):
        # No worker spawn was attempted; the preflight only lists gateway tools.
        raise SystemExit(0)

    monkeypatch.setattr(loop.dsh, "run", interrupted)
    with pytest.raises(SystemExit):
        loop.run_round(worker, {"MODEL": "test", "REASONING_EFFORT": "high"},
                       "prompt", worker.dir / "test.log", 1)
    assert not (worker.dir / ".dsh-child.json").exists()


def test_status_fact_breadcrumb_decodes_dsh_tool_result(tmp_path):
    log = tmp_path / "round.log"
    log.write_text(json.dumps({"type": "tool_result", "result": json.dumps(
        {"accepted": True, "fact_id": "0123456789abcdef"})}) + "\n")
    assert loop._parse_last_fact_id(log) == "0123456789abcdef"
