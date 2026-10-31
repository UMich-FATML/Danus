"""The advertised commands must share the same safe offline feedback path."""
import importlib.util
from pathlib import Path
import sys

SCRIPTS = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("danus_check", SCRIPTS / "check.py")
check = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(check)


def test_check_environment_drops_ambient_routes_and_credentials(tmp_path):
    env = check.isolated_env(tmp_path, {
        "PATH": "/usr/bin", "HOME": "/example", "DANUS_MAIN_MODEL": "live",
        "DSH_SESSION_ID": "live-session", "CODEX_HOME": "/private", "KIMI_MODEL_NAME": "live",
        "OPENAI_API_KEY": "not-a-real-key", "GH_TOKEN": "not-a-real-token",
        "VERIFY_PORT": "9999", "DATABASE_PASSWORD": "not-a-real-password",
    })
    assert env["PATH"] == "/usr/bin" and env["HOME"] == "/example"
    assert env["DSH_HOME"] == str(tmp_path / "dsh")
    assert env["DSH_AGENTS_HOME"] == str(tmp_path / "agents")
    assert env["DANUS_DSH_RUNS_DIR"] == str(tmp_path / "runs")
    assert not any(key in env for key in ("DANUS_MAIN_MODEL", "DSH_SESSION_ID", "CODEX_HOME",
                                          "KIMI_MODEL_NAME", "OPENAI_API_KEY", "GH_TOKEN",
                                          "VERIFY_PORT", "DATABASE_PASSWORD"))


def test_fast_checks_reuse_skill_guard_and_parse_shell_and_js(tmp_path):
    for name, content in (("scripts/example.sh", "#!/bin/bash\nexit 1\n"),
                          ("bin/launcher", "#!/usr/bin/env bash\nexit 1\n"),
                          (".githooks/pre-commit", "#!/usr/bin/env bash\nexit 1\n"),
                          (".dsh/overlay.mjs", "throw new Error('must not execute')")):
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content)
    commands = check.commands(tmp_path, fast=True)
    assert [sys.executable, "agents/skills/worker/check_conformance.py"] in commands
    assert ["bash", "-n", "scripts/example.sh"] in commands
    assert ["bash", "-n", "bin/launcher"] in commands
    assert ["bash", "-n", ".githooks/pre-commit"] in commands
    assert ["node", "--check", ".dsh/overlay.mjs"] in commands
    assert not any("pytest" in command or "--test" in command for command in commands)


def test_full_checks_include_verifier_schema_and_main_hook_tests(tmp_path):
    commands = check.commands(tmp_path)
    pytest = next(command for command in commands if "pytest" in command)
    assert "agents/skills/verify/test_verification_schema.py" in pytest
    assert "danus/" in pytest and "scripts/tests/" in pytest and ".dsh/test_ops.py" in pytest
    assert ["node", "--test", ".dsh/main-checkpoints.test.mjs"] in commands


def test_pixi_aliases_share_canonical_runner():
    text = (SCRIPTS.parent / "pixi.toml").read_text()
    assert 'check = "bash scripts/check.sh"' in text
    assert 'test = "bash scripts/check.sh"' in text
    assert 'lint = "bash scripts/check.sh --fast"' in text


def test_runner_stops_at_first_failure_without_running_later_checks(tmp_path, monkeypatch):
    from types import SimpleNamespace
    calls = []
    monkeypatch.setattr(check, "ROOT", tmp_path)
    monkeypatch.setattr(check, "commands", lambda *a, **k: [["first"], ["must-not-run"]])
    def fail(command, **kwargs):
        calls.append(command)
        assert kwargs["env"]["DSH_HOME"].endswith("/dsh")
        return SimpleNamespace(returncode=9)
    monkeypatch.setattr(check.subprocess, "run", fail)
    assert check.main(["--fast"]) == 9
    assert calls == [["first"]]
