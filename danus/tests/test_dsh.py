"""Offline protocol, isolation, route, lifecycle and fail-closed regression tests."""
import json
import os
import signal
import subprocess
import sys
from pathlib import Path

import pytest
from danus import dsh


def stub(tmp_path, body):
    path = tmp_path / "fake-dsh"
    path.write_text(f"#!{sys.executable}\n" + body, encoding="utf-8")
    path.chmod(0o755)
    return path


def events(*, reason="completed", final="artifact", session="test-session"):
    return "\n".join(json.dumps(e) for e in [
        {"type": "session", "sessionId": session},
        {"type": "text", "text": "TRUNCATED WRONG ARTIFACT", "truncated": True},
        {"type": "status", "phase": "turn_end", "reason": {"kind": reason}},
        {"type": "final", "text": final}]) + "\n"


def invoke(tmp_path, monkeypatch, text=None, rc=0, body=None, **kwargs):
    if body is None:
        body = f"import sys\nsys.stdin.read()\nsys.stdout.write({(text if text is not None else events())!r})\nsys.exit({rc})\n"
    monkeypatch.setenv("DANUS_DSH_BIN", str(stub(tmp_path, body)))
    return dsh.run("task on stdin", cwd=tmp_path, model="m", effort="high", **kwargs)


def test_lossless_final_and_unique_durable_homes(tmp_path, monkeypatch):
    long = "α" * 100000
    a = invoke(tmp_path, monkeypatch, events(final=long))
    b = invoke(tmp_path, monkeypatch)
    assert a.returncode == b.returncode == 0
    assert a.stdout == long and a.session_id == "test-session"
    assert a.run_dir != b.run_dir and a.run_dir.is_dir()
    assert (a.run_dir / "home").is_dir() and (a.run_dir / "events.jsonl").is_file()
    assert "--model" not in a.args and "--session-id" not in a.args
    assert a.args[1:3] == ["--profile", "headless"]
    assert all(Path(a.args[i + 1]).is_absolute() for i, x in enumerate(a.args) if x == "--patch")


@pytest.mark.parametrize("reason", ["cancelled", "failed", "error", "max_steps", "interrupted", None])
def test_process_zero_incomplete_is_failure(tmp_path, monkeypatch, reason):
    result = invoke(tmp_path, monkeypatch, events(reason=reason))
    assert result.returncode != 0 and "incomplete" in result.stderr


@pytest.mark.parametrize("text", ["", "not-json\n", '{"type":"final","text":"x"}\n',
    '{"type":"session","sessionId":"x"}\n{"type":"status","phase":"turn_end","reason":"completed"}\n',
    events() + '{"type":"final","text":"duplicate"}\n'])
def test_missing_malformed_events_fail_closed(tmp_path, monkeypatch, text):
    assert invoke(tmp_path, monkeypatch, text).returncode != 0


def test_nonzero_process_never_accepted(tmp_path, monkeypatch):
    assert invoke(tmp_path, monkeypatch, rc=7).returncode == 7


def test_stdin_and_isolated_environment(tmp_path, monkeypatch):
    monkeypatch.setenv("DSH_HOME", "/gui-home")
    monkeypatch.setenv("DSH_AGENTS_HOME", "/gui-agents")
    monkeypatch.setenv("DSH_SESSION_ID", "gui-session")
    body = '''import sys, os, json
p=sys.stdin.read()
print(json.dumps({"type":"session","sessionId":"fresh"}))
print(json.dumps({"type":"status","phase":"turn_end","reason":"completed"}))
print(json.dumps({"type":"final","text":json.dumps({"prompt":p,"home":os.environ["DSH_HOME"],"agents":os.environ["DSH_AGENTS_HOME"],"session":os.getenv("DSH_SESSION_ID")})}))
'''
    result = invoke(tmp_path, monkeypatch, body=body)
    data = json.loads(result.stdout)
    assert data["prompt"] == "task on stdin" and data["session"] is None
    assert data["home"] == str(result.run_dir / "home")
    assert data["agents"] == str(result.run_dir / "agents")


def test_role_overlay_complete_and_pinned(tmp_path):
    rows = dsh.site_patch(model="m", effort="ultra", provider="test", cwd=tmp_path,
        role="worker", project_dir=tmp_path, author="w", instructions="WORKER.md", skill_dirs=[tmp_path])
    by_id = {r["id"]: r for r in rows if "id" in r}
    assert by_id["agent-default-model"]["config"] == {"provider":"test","model":"m","reasoningEffort":"ultra"}
    assert by_id["approval"]["config"] == {"policy":"never"}
    assert by_id["agent-instructions"]["config"]["instructionFileCandidates"] == ["WORKER.md"]
    assert by_id["agent-instructions"]["config"]["localInstructionFileCandidates"] == []
    assert not by_id["skill-filesystem"]["config"]["includeDefaultRoots"]
    gateway = next(row for row in rows if "insert" in row)["insert"][0]["config"]
    assert gateway["command"] == sys.executable and gateway["args"] == ["-m", "danus.gateway"]
    assert gateway["toolCallTimeoutMs"] == 3600000 and gateway["env"]["DANUS_ROLE"] == "worker"


def test_env_no_legacy_fallback(monkeypatch, tmp_path):
    monkeypatch.delenv("DANUS_MAIN_MODEL", raising=False)
    monkeypatch.delenv("DANUS_MAIN_EFFORT", raising=False)
    monkeypatch.setenv("DANUS_CODEX_MODEL", "must-not-use")
    monkeypatch.setenv("DANUS_CODEX_EFFORT", "must-not-use")
    assert dsh.model() == dsh.DEFAULT_MODEL and dsh.effort() == dsh.DEFAULT_EFFORT
    monkeypatch.setenv("DANUS_MAIN_MODEL", "neutral")
    monkeypatch.setenv("DANUS_VERIFY_MODEL", "verify")
    assert dsh.model("DANUS_VERIFY_MODEL") == "verify" and dsh.model() == "neutral"
    monkeypatch.setenv("PATH", "/usr/bin:/bin")
    assert dsh.subprocess_env("dsh")["PATH"] == "/usr/bin:/bin"
    assert dsh.subprocess_env("/custom/bin/dsh")["PATH"].startswith("/custom/bin:")


def test_explicit_provider_and_project_profiles(monkeypatch):
    provider, patch = dsh.provider_config()
    monkeypatch.setenv("DANUS_PROJECT_PROJ_WORKER_DSH_PROVIDER", provider)
    with pytest.raises(ValueError, match="both"):
        dsh.provider_config("proj")
    monkeypatch.setenv("DANUS_PROJECT_PROJ_WORKER_DSH_PROVIDER_PATCH", str(patch))
    assert dsh.provider_config("proj") == (provider, patch)
    monkeypatch.setenv("DANUS_PROJECT_PROJ_WORKER_API_KEY", "legacy-secret")
    with pytest.raises(ValueError, match="legacy"):
        dsh.provider_config("proj")


@pytest.mark.parametrize("rows", [[], {}, [{"id":"approval","config":{"policy":"ask"}}],
    [{"id":"llm-pi-ai","config":{"providers":{}}}], [{"insert":[]}],
    [{"id":"llm-pi-ai","config":{"providers":{"test":{"api":"openai-responses","baseURL":"x"}}}}]])
def test_invalid_provider_overlay_rejected(rows):
    with pytest.raises(ValueError):
        dsh.validate_provider_patch(rows, "test")


def test_timeout_kills_descendant_process(tmp_path, monkeypatch):
    child_pid = tmp_path / "child.pid"
    body = f'''import sys, subprocess, time
sys.stdin.read()
p=subprocess.Popen([sys.executable,"-c","import time; time.sleep(60)"])
open({str(child_pid)!r},"w").write(str(p.pid))
time.sleep(60)
'''
    with pytest.raises(subprocess.TimeoutExpired):
        invoke(tmp_path, monkeypatch, body=body, timeout=0.5)
    pid = int(child_pid.read_text())
    proc_stat = Path(f"/proc/{pid}/stat")
    # Reparented zombies have exited; no surviving runnable descendant is allowed.
    assert not proc_stat.exists() or proc_stat.read_text().split()[2] == "Z"


def test_authoring_surface_and_worker_no_delegation(tmp_path):
    for role in (None, "verifier"):
        rows = dsh.site_patch(model="m", effort="high", provider="test", cwd=tmp_path,
                             role=role, authoring=True)
        disabled = {row["id"] for row in rows if row.get("disabled") is True}
        assert {"tool-bash", "tool-fs", "tool-fs-search", "tool-subagent", "tool-subagent-fork", "tool-workflow"} <= disabled
        assert ("tool-web" in disabled) == (role is None)
    rows = dsh.site_patch(model="m", effort="high", provider="test", cwd=tmp_path, role="worker")
    assert any(row.get("id") == "tool-subagent" and row.get("disabled") for row in rows)


def test_model_effort_and_credential_validation(monkeypatch):
    provider, patch = dsh.provider_config()
    dsh.validate_model_selection(patch, provider, "m", "high")
    with pytest.raises(ValueError, match="model"):
        dsh.validate_model_selection(patch, provider, "unknown", "high")
    with pytest.raises(ValueError, match="effort"):
        dsh.validate_model_selection(patch, provider, "m", "unsupported")
    monkeypatch.delenv("DANUS_TEST_NO_LIVE_KEY")
    with pytest.raises(ValueError, match="credential"):
        dsh.validate_model_selection(patch, provider, "m", "high")


def test_gateway_preflight_real_offline_role_surface(tmp_path):
    import asyncio
    from danus.gateway.roles import ROLE_TOOLS
    for role in ("worker", "verifier"):
        row = dsh.gateway_row(role=role, cwd=tmp_path, project_dir=tmp_path, author="test")
        names = asyncio.run(dsh.preflight_mcp(row["config"], set(ROLE_TOOLS[role])))
        assert names == set(ROLE_TOOLS[role])


def test_gateway_preflight_failure_prevents_spawn(tmp_path, monkeypatch):
    async def unavailable(*args, **kwargs):
        raise ValueError("required MCP unavailable")
    monkeypatch.setattr(dsh, "preflight_mcp", unavailable)
    with pytest.raises(ValueError, match="required MCP"):
        invoke(tmp_path, monkeypatch, role="worker", project_dir=tmp_path)


def test_process_birth_identity_rejects_pid_reuse():
    identity = dsh.process_identity(os.getpid())
    assert dsh.is_same_process(identity)
    if identity["start_ticks"] is not None:
        assert not dsh.is_same_process({"pid":os.getpid(), "start_ticks":"-1"})
    with pytest.raises(ValueError):
        dsh.is_same_process({"pid":1})


def test_timeout_escalates_and_reaps(monkeypatch):
    calls = []
    class Proc:
        pid = 987654321
        def wait(self, timeout=None):
            calls.append(("wait", timeout))
            if timeout is not None:
                raise subprocess.TimeoutExpired("dsh", timeout)
    monkeypatch.setattr(os, "killpg", lambda pid, sig: calls.append((pid, sig)))
    dsh.terminate_process_group(Proc(), grace=0.01)
    assert (987654321, signal.SIGTERM) in calls and (987654321, signal.SIGKILL) in calls
    assert calls[-1] == ("wait", None)
