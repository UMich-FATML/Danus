"""Offline provisioning and main-overlay regression tests; no live models."""
from __future__ import annotations

import importlib.util
import json
import os
from pathlib import Path
import subprocess

import pytest

ROOT = Path(__file__).resolve().parents[1]


def load_script(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def route(monkeypatch, tmp_path):
    values = {"DANUS_DSH_PROVIDER": "test-route", "DANUS_DSH_API": "openai-responses",
              "DANUS_DSH_API_BASE_URL": "https://invalid.example/v1", "DANUS_DSH_API_KEY": "fake-secret-do-not-write",
              "DANUS_MAIN_MODEL": "test-model", "DANUS_MAIN_EFFORT": "high",
              "DANUS_DSH_REASONING_EFFORTS": "high,xhigh", "DANUS_AUTHORING_TIMEOUT_SECONDS": "3300"}
    for key, value in values.items():
        monkeypatch.setenv(key, value)
    rows = load_script("dsh_config").provider_rows()
    patch = tmp_path / "provider.json"
    patch.write_text(json.dumps(rows))
    monkeypatch.setenv("DANUS_DSH_PROVIDER_PATCH", str(patch))
    return rows


def test_provider_never_writes_secrets(route):
    text = json.dumps(route)
    assert "fake-secret-do-not-write" not in text
    profile = route[0]["config"]["providers"]["test-route"]
    assert profile["apiKeyEnv"] == "DANUS_DSH_API_KEY"
    assert profile["models"][0]["reasoningEfforts"] == {"high": "high", "xhigh": "xhigh"}


def test_setup_rejects_partial_route(monkeypatch):
    monkeypatch.delenv("DANUS_DSH_PROVIDER", raising=False)
    with pytest.raises(ValueError, match="DANUS_DSH_PROVIDER"):
        load_script("dsh_config").provider_rows()


def test_main_overlay_has_three_wrappers_complete_model_and_main_only_hook(route):
    module = load_script("main_dsh")
    rows = module.main_rows(headless=True)
    selection = next(row["config"] for row in rows if row.get("id") == "agent-default-model")
    assert selection == {"provider": "test-route", "model": "test-model", "reasoningEffort": "high"}
    inserted = rows[-1]["insert"]
    clients = inserted[:-1]
    assert {row["config"]["serverName"] for row in clients} == {"danus", "write-paper", "human-summary"}
    for row in clients:
        config = row["config"]
        assert Path(config["command"]).parent == ROOT / "bin"
        assert config["toolCallTimeoutMs"] == 3_600_000
        assert config["env"]["DANUS_DSH_API_KEY"] == "__DANUS_ENV_REF__DANUS_DSH_API_KEY"
        assert config["env"]["DSH_HOME"] == "__DANUS_ENV_REF__DSH_HOME"
    assert inserted[-1]["name"] == str(ROOT / ".dsh" / "main-checkpoints.mjs")
    assert inserted[-1]["config"]["role"] == "main"
    text = module.patch_text(rows)
    assert "fake-secret-do-not-write" not in text
    assert "!!js " in text


def test_web_preset_scopes_main_tools_and_native_timer_config(route):
    rows = load_script("main_dsh").main_rows()
    assert next(row for row in rows if row.get("id") == "agent-preset-registry")["config"] == {"default": "danus-main"}
    inserted = rows[-1]["insert"]
    preset = inserted[0]["config"]
    assert preset["id"] == "danus-main"
    plugins = {row["id"]: row for row in preset["plugins"]}
    assert {"tool-schedule", "tool-goal", "tool-subagent", "tool-subagent-fork"} <= plugins.keys()
    assert plugins["agent-instructions"]["config"]["instructionFileCandidates"] == ["AGENTS.md"]
    assert plugins["skill-filesystem"]["config"]["includeDefaultRoots"] is False
    assert len([row for row in preset["plugins"] if row["name"].endswith("/dsh-mcp-client")]) == 3
    assert inserted[1]["config"]["preset"] == "danus-main"
    assert not any(row.get("name", "").endswith("/dsh-mcp-client") for row in inserted)


@pytest.mark.parametrize("headless", [False, True])
def test_main_launch_uses_profile_flags_and_runtime_owned_homes(route, monkeypatch, tmp_path, headless):
    import sys
    module = load_script("main_dsh")
    monkeypatch.setenv("DANUS_RUNTIME", str(tmp_path))
    monkeypatch.setenv("DANUS_DSH_BIN", "/fake/dsh")
    monkeypatch.setenv("DANUS_MAIN_PORT", "8090")
    monkeypatch.setenv("DSH_HOME", "/user/gui")
    monkeypatch.setenv("DSH_AGENTS_HOME", "/user/gui-agents")
    monkeypatch.setattr(sys, "argv", ["danus-main"] + (["--headless"] if headless else []))
    monkeypatch.setattr(module.os, "chdir", lambda _path: None)
    captured = {}
    async def preflight(env):
        captured["preflight"] = True
    monkeypatch.setattr(module, "preflight_main", preflight)
    monkeypatch.setattr(module.os, "execvpe", lambda binary, command, env: captured.update(binary=binary, command=command, env=env))
    module.main()
    assert captured["command"][1:3] == ["--profile", "headless" if headless else "web"]
    assert captured["command"].count("--patch") == 2
    assert "--model" not in captured["command"]
    assert str(tmp_path) in captured["env"]["DSH_HOME"]
    assert captured["env"]["DANUS_DSH_ISOLATED"] == "1"
    if headless:
        assert captured["command"][-1] == "--json"
    else:
        assert captured["command"][-5:] == ["--host", "127.0.0.1", "--port", "8090", "--no-open"]
        assert captured["env"]["DSH_HOME"] == str(tmp_path / "main-dsh" / "web" / "home")


def test_main_mcp_timeout_fails_closed(route, monkeypatch):
    monkeypatch.setenv("DANUS_AUTHORING_TIMEOUT_SECONDS", "86400")
    with pytest.raises(ValueError, match="3599"):
        load_script("main_dsh").mcp_rows()


def test_env_rejects_gui_home_and_preserves_managed_homes(tmp_path):
    command = 'source scripts/env.sh; printf "%s\\n%s\\n" "$DSH_HOME" "$DSH_AGENTS_HOME"'
    env = {**os.environ, "DSH_HOME": "/user/gui", "DSH_AGENTS_HOME": "/user/agents", "DANUS_DSH_ISOLATED": "0"}
    env.pop("DANUS_DSH_HOME", None); env.pop("DANUS_DSH_AGENTS_HOME", None)
    result = subprocess.run(["bash", "-c", command], cwd=ROOT, env=env, capture_output=True, text=True, check=True)
    assert "/user/" not in result.stdout
    env.update(DANUS_DSH_ISOLATED="1", DSH_HOME=str(tmp_path / "home"), DSH_AGENTS_HOME=str(tmp_path / "agents"))
    result = subprocess.run(["bash", "-c", command], cwd=ROOT, env=env, capture_output=True, text=True, check=True)
    assert result.stdout.splitlines() == [str(tmp_path / "home"), str(tmp_path / "agents")]


def test_isolated_env_never_reloads_deployment_files(tmp_path):
    scripts = tmp_path / "scripts"; scripts.mkdir()
    config = tmp_path / "config"; config.mkdir()
    runtime = tmp_path / "runtime"; runtime.mkdir()
    script = scripts / "env.sh"
    script.write_text((ROOT / "scripts" / "env.sh").read_text())
    for path in (config / "dsh.env", config / "danus.env", runtime / "runtime.env"):
        path.write_text('DANUS_DSH_PROVIDER=wrong\\nDANUS_PY=/stale/python\\n')
    env = {**os.environ, "DANUS_DSH_ISOLATED": "1", "DSH_HOME": str(tmp_path / "home"),
           "DSH_AGENTS_HOME": str(tmp_path / "agents"), "DANUS_DSH_PROVIDER": "resolved-route", "DANUS_PY": "/resolved/python"}
    result = subprocess.run(["bash", "-c", 'source "$1"; printf "%s\\n%s\\n" "$DANUS_DSH_PROVIDER" "$DANUS_PY"', "test", str(script)],
                            env=env, capture_output=True, text=True, check=True)
    assert result.stdout.splitlines() == ["resolved-route", "/resolved/python"]


def test_wrapper_rejects_self_recursion():
    env = {**os.environ, "DANUS_DSH_BIN": str(ROOT / "bin" / "dsh"), "DANUS_DSH_ISOLATED": "0"}
    result = subprocess.run([str(ROOT / "bin" / "dsh"), "--version"], env=env, capture_output=True, text=True, timeout=5)
    assert result.returncode == 2
    assert "itself" in result.stderr
