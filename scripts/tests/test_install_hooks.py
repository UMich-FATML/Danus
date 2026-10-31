"""Test hook configuration and propagation without touching the user's Git config."""
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

SCRIPTS = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("install_hooks", SCRIPTS / "install_hooks.py")
hooks = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(hooks)


@pytest.fixture
def repo(tmp_path, monkeypatch):
    monkeypatch.setenv("GIT_CONFIG_NOSYSTEM", "1")
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", os.devnull)
    root = tmp_path / "test repository"
    root.mkdir()
    subprocess.run(["git", "init", "-q", str(root)], check=True)
    hook = root / ".githooks/pre-commit"
    hook.parent.mkdir()
    hook.write_text((SCRIPTS.parent / ".githooks/pre-commit").read_text())
    hook.chmod(0o755)
    return root


def configured(root):
    result = subprocess.run(["git", "config", "--local", "--get", "core.hooksPath"],
                            cwd=root, capture_output=True, text=True)
    return result.stdout.strip()


def test_install_is_local_and_idempotent(repo):
    assert "repository-local" in hooks.install(repo)
    assert configured(repo) == ".githooks"
    assert "already configured" in hooks.install(repo)


def test_existing_custom_hooks_require_explicit_force(repo):
    subprocess.run(["git", "config", "--local", "core.hooksPath", "custom-hooks"], cwd=repo, check=True)
    with pytest.raises(ValueError, match="existing core.hooksPath"):
        hooks.install(repo)
    assert configured(repo) == "custom-hooks"
    hooks.install(repo, force=True)
    assert configured(repo) == ".githooks"


def test_global_hooks_are_not_silently_shadowed(repo, tmp_path, monkeypatch):
    config = tmp_path / "global-config"
    config.write_text("[core]\n\thooksPath = /existing/global/hooks\n")
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", str(config))
    with pytest.raises(ValueError, match="existing core.hooksPath"):
        hooks.install(repo)
    assert configured(repo) == ""
    assert config.read_text() == "[core]\n\thooksPath = /existing/global/hooks\n"


def test_missing_executable_hook_does_not_change_configuration(repo):
    (repo / ".githooks/pre-commit").chmod(0o644)
    with pytest.raises(ValueError, match="executable"):
        hooks.install(repo)
    assert configured(repo) == ""


def test_hook_runs_fast_alias_and_propagates_failure(repo, tmp_path):
    tools = tmp_path / "tools"
    tools.mkdir()
    record = tmp_path / "called.json"
    fake = tools / "pixi"
    fake.write_text(f"#!{sys.executable}\nimport json, os, sys\n"
                    "from pathlib import Path\n"
                    "Path(os.environ['HOOK_TEST_RECORD']).write_text(json.dumps(sys.argv[1:]))\n"
                    "sys.exit(7)\n")
    fake.chmod(0o755)
    env = {**os.environ, "PATH": str(tools) + os.pathsep + os.environ["PATH"],
           "HOOK_TEST_RECORD": str(record)}
    result = subprocess.run(["bash", str(repo / ".githooks/pre-commit")], cwd=repo, env=env)
    assert result.returncode == 7
    assert json.loads(record.read_text()) == ["run", "--manifest-path", str(repo / "pixi.toml"), "lint"]


def test_hook_missing_pixi_explains_how_to_repair(repo, tmp_path):
    import shutil
    tools = tmp_path / "only-git"
    tools.mkdir()
    (tools / "git").symlink_to(shutil.which("git"))
    result = subprocess.run([shutil.which("bash"), str(repo / ".githooks/pre-commit")],
                            cwd=repo, env={**os.environ, "PATH": str(tools)},
                            capture_output=True, text=True)
    assert result.returncode == 1
    assert "install Pixi" in result.stderr and "CONTRIBUTING.md" in result.stderr


def test_hook_directory_cannot_redirect_outside_repository(tmp_path):
    root = tmp_path / "repo"
    root.mkdir()
    subprocess.run(["git", "init", "-q", str(root)], check=True)
    elsewhere = tmp_path / "external-hooks"
    elsewhere.mkdir()
    hook = elsewhere / "pre-commit"
    hook.write_text("#!/bin/bash\nexit 0\n")
    hook.chmod(0o755)
    (root / ".githooks").symlink_to(elsewhere, target_is_directory=True)
    with pytest.raises(ValueError, match="no symlink directories"):
        hooks.install(root)
    assert configured(root) == ""
