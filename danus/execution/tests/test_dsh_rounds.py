"""Round-boundary snapshots, durable identifiers, and restored roster safety."""
import json
import signal
from pathlib import Path

import pytest
from danus import checkpoints, dsh
from danus.execution import layout as L, loop, scaffold


@pytest.fixture
def worker(tmp_path, monkeypatch):
    monkeypatch.setenv("DANUS_AGENTS_ROOT", str(tmp_path / "projects"))
    monkeypatch.setenv("DANUS_ROUND_BEAT", "0")
    monkeypatch.setenv("DANUS_MAX_ROUNDS", "4")
    monkeypatch.setenv("DANUS_MAX_CONSEC_FAILURES", "0")
    scaffold.do_new("P", roles="high:1", model="m")
    old = signal.getsignal(signal.SIGTERM)
    yield L.WorkerLayout(L.worker_dir("P", "high"))
    signal.signal(signal.SIGTERM, old)


def test_snapshot_only_after_completed_round(worker, monkeypatch):
    monkeypatch.setenv("DANUS_SNAPSHOT_AUTO", "1")
    returned = iter([0, 1, 124, 0])
    calls = []
    def fake_round(wl, role, prompt, log_path, hard_timeout):
        with log_path.open("w") as log:
            log.write("round closed")
        loop.write_status(wl, last_session_id="fresh-session")
        return next(returned)
    def snapshot(project, trigger):
        assert loop._Child.proc is None
        assert json.loads(worker.status.read_text())["state"] == "idle"
        calls.append(trigger)
        return {"warnings": []}
    monkeypatch.setattr(loop, "run_round", fake_round)
    monkeypatch.setattr(checkpoints, "request_snapshot", snapshot)
    assert loop.main(str(worker.dir)) == 0
    assert [call["round"] for call in calls] == [1, 4]
    assert all(call["session_id"] == "fresh-session" for call in calls)


def test_snapshot_errors_warn_and_disable_skips(worker, monkeypatch, caplog):
    loop.write_status(worker, last_session_id="s")
    monkeypatch.setenv("DANUS_SNAPSHOT_AUTO", "1")
    def fail(*args, **kwargs):
        raise OSError("snapshot disk error")
    monkeypatch.setattr(checkpoints, "request_snapshot", fail)
    loop._snapshot_round(worker, 1)
    assert "snapshot disk error" in caplog.text
    caplog.clear()
    monkeypatch.setenv("DANUS_SNAPSHOT_AUTO", "0")
    loop._snapshot_round(worker, 2)
    assert not caplog.text


def test_restart_never_overwrites_round_logs(worker, monkeypatch):
    monkeypatch.setenv("DANUS_MAX_ROUNDS", "1")
    paths = []
    def fake_round(wl, role, prompt, path, timeout):
        assert not path.exists()
        path.write_text("new session")
        paths.append(path)
        return 0
    monkeypatch.setattr(loop, "run_round", fake_round)
    loop.main(str(worker.dir))
    loop.main(str(worker.dir))
    assert len(set(paths)) == 2 and all(path.is_file() for path in paths)


def test_roster_ignores_restored_ghost_worker_and_symlink(worker):
    ghosts = worker.dir.parent / "removed"
    ghosts.mkdir()
    (ghosts / "logs").mkdir()
    assert L.list_workers("P") == ["high"]
    with pytest.raises(ValueError, match="roster"):
        L.target_worker_dirs("P/removed")
    metadata = worker.project_dir / "project.json"
    data = json.loads(metadata.read_text())
    data["workers"].append("../../outside")
    metadata.write_text(json.dumps(data))
    with pytest.raises(ValueError, match="roster"):
        L.list_workers("P")


def test_child_marker_tracks_birth_then_clears(worker):
    class Child:
        pid = __import__('os').getpid()
    loop._record_child(worker, Child())
    marker = worker.dir / ".dsh-child.json"
    assert dsh.is_same_process(json.loads(marker.read_text()))
    loop._record_child(worker, None)
    assert not marker.exists() and loop._Child.proc is None
