"""Offline tests for danus.authoring.driver — the one-shot isolated dsh driver.

Uses the deterministic ``fake_dsh.py`` stub (DANUS_DSH_BIN) instead of a real
dsh: exercises stdin→stdout forwarding, the fresh-empty-cwd isolation, and the
return-code / timeout plumbing. Zero network / API spend.

Runs standalone (``python -m danus.authoring.tests.test_driver``) and under pytest.
"""

from __future__ import annotations

import os
import stat
import subprocess
import tempfile
from pathlib import Path

from danus.authoring import driver

from ._fixtures import env

FAKE = Path(__file__).resolve().parent / "fake_dsh.py"


def _ensure_fake_executable():
    FAKE.chmod(FAKE.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)


def test_stdout_forwarded_verbatim():
    _ensure_fake_executable()
    with env(DANUS_DSH_BIN=str(FAKE)):
        cp = driver.run_dsh("please write the paper", timeout=60)
    assert cp.returncode == 0
    assert "\\documentclass{amsart}" in cp.stdout
    assert "\\end{document}" in cp.stdout


def test_cwd_is_a_fresh_temp_dir():
    _ensure_fake_executable()
    with env(DANUS_DSH_BIN=str(FAKE)):
        cp = driver.run_dsh("[[FAKE:cwd]] print your cwd", timeout=60)
    cwd = cp.stdout.strip()
    # the driver hands dsh a brand-new temp dir, NOT the caller's cwd
    assert cwd and cwd != os.getcwd()
    assert "danus-authoring-dsh-" in cwd
    # and it is cleaned up afterwards (TemporaryDirectory context exited)
    assert not Path(cwd).exists()


def test_nonzero_returncode_plumbed():
    _ensure_fake_executable()
    with env(DANUS_DSH_BIN=str(FAKE)):
        cp = driver.run_dsh("boom [[FAKE:exit=7]]", timeout=60)
    assert cp.returncode == 7
    assert cp.stdout.strip() == ""
    assert "forced nonzero exit" in cp.stderr


def test_timeout_raises():
    # a stub that sleeps longer than the timeout → TimeoutExpired is propagated
    with tempfile.TemporaryDirectory() as d:
        sleeper = Path(d) / "sleeper.py"
        sleeper.write_text("#!/usr/bin/env python3\nimport time,sys\ntime.sleep(5)\n", encoding="utf-8")
        sleeper.chmod(sleeper.stat().st_mode | stat.S_IXUSR)
        with env(DANUS_DSH_BIN=str(sleeper)):
            try:
                driver.run_dsh("anything", timeout=1)
                assert False, "should have timed out"
            except subprocess.TimeoutExpired:
                pass


def test_missing_binary_raises_filenotfound():
    with env(DANUS_DSH_BIN="/nonexistent/dsh/binary"):
        try:
            driver.run_dsh("anything", timeout=60)
            assert False, "missing binary should raise FileNotFoundError"
        except FileNotFoundError:
            pass


def test_neutral_default_model_and_effort():
    # the shared driver reads the NEUTRAL env vars for its defaults
    with env(DANUS_MAIN_MODEL="my-model", DANUS_MAIN_EFFORT="low"):
        assert driver.default_model() == "my-model"
        assert driver.default_effort() == "low"
    with env(DANUS_MAIN_MODEL=None,
             DANUS_MAIN_EFFORT=None):
        assert driver.default_model() == driver.DEFAULT_MODEL == "gpt-5.6-sol"
        assert driver.default_effort() == driver.DEFAULT_EFFORT == "xhigh"


def test_resolve_bin_bare_name_resolved_via_which():
    # dsh.py resolve_bin: a bare (non-absolute) DANUS_DSH_BIN name is resolved
    # to its absolute path via PATH (shutil.which). We put a fake 'mydsh' on PATH.
    from danus import dsh
    with tempfile.TemporaryDirectory() as d:
        binp = Path(d) / "mydsh"
        binp.write_text("#!/bin/sh\ntrue\n", encoding="utf-8")
        binp.chmod(binp.stat().st_mode | stat.S_IXUSR)
        old_path = os.environ.get("PATH", "")
        with env(DANUS_DSH_BIN="mydsh"):
            os.environ["PATH"] = d + os.pathsep + old_path
            try:
                resolved = dsh.resolve_bin()
            finally:
                os.environ["PATH"] = old_path
        # resolved to the absolute path found on PATH (not left as the bare name)
        assert resolved == str(binp)


def test_resolve_bin_bare_name_not_on_path_falls_back_to_raw():
    # a bare name not on PATH -> returned raw (exec then surfaces FileNotFoundError)
    from danus import dsh
    with env(DANUS_DSH_BIN="definitely-not-on-path-xyz"):
        assert dsh.resolve_bin() == "definitely-not-on-path-xyz"


def test_subprocess_env_prepends_bin_dir_for_concrete_path():
    # a concrete dsh path -> its dir is prepended to PATH (for the node shebang)
    from danus import dsh
    with tempfile.TemporaryDirectory() as d:
        dsh_bin = str(Path(d) / "dsh")
        senv = dsh.subprocess_env(dsh_bin)
        first = senv["PATH"].split(os.pathsep)[0]
        assert first == str(Path(d))


def test_subprocess_env_bare_name_does_not_inject_cwd():
    # the bare 'dsh' fallback (no dir component) must NOT inject the CWD into PATH
    from danus import dsh
    before = os.environ.get("PATH", "")
    senv = dsh.subprocess_env("dsh")
    assert senv["PATH"] == before, "a bare name must leave PATH unchanged"


def test_call_time_defaults_and_networked_capability(monkeypatch):
    seen = {}
    def capture(prompt, **kwargs):
        seen.update(kwargs)
        return subprocess.CompletedProcess([], 0, stdout="artifact", stderr="")
    monkeypatch.setattr(driver.dsh, "run", capture)
    monkeypatch.setenv("DANUS_MAIN_MODEL", "configured-model")
    monkeypatch.setenv("DANUS_MAIN_EFFORT", "medium")
    monkeypatch.setenv("DANUS_AUTHORING_TIMEOUT_SECONDS", "123")
    driver.run_dsh("prompt", networked=True)
    assert seen["model"] == "configured-model" and seen["effort"] == "medium"
    assert seen["timeout"] == 123 and seen["authoring"] is True
    assert seen["role"] == "verifier" and seen["sandbox"] == "read-only"
    driver.run_dsh("prompt", timeout=0)
    assert seen["timeout"] == 0 and seen["role"] is None


def main() -> None:
    test_stdout_forwarded_verbatim()
    print("  [ok] stdout forwarded verbatim (the artifact)")
    test_cwd_is_a_fresh_temp_dir()
    print("  [ok] dsh cwd = a fresh empty temp dir (isolation), cleaned up after")
    test_nonzero_returncode_plumbed()
    print("  [ok] nonzero returncode + stderr plumbed through")
    test_timeout_raises()
    print("  [ok] timeout -> subprocess.TimeoutExpired")
    test_missing_binary_raises_filenotfound()
    print("  [ok] missing dsh binary -> FileNotFoundError")
    test_neutral_default_model_and_effort()
    print("  [ok] neutral DANUS_MAIN_MODEL / DANUS_MAIN_EFFORT defaults")
    test_resolve_bin_bare_name_resolved_via_which()
    print("  [ok] resolve_bin: bare name resolved via PATH (shutil.which)")
    test_resolve_bin_bare_name_not_on_path_falls_back_to_raw()
    print("  [ok] resolve_bin: bare name not on PATH -> raw fallback")
    test_subprocess_env_prepends_bin_dir_for_concrete_path()
    print("  [ok] subprocess_env: concrete path -> bin dir prepended to PATH")
    test_subprocess_env_bare_name_does_not_inject_cwd()
    print("  [ok] subprocess_env: bare name -> PATH unchanged (no CWD injection)")
    print("ALL DRIVER TESTS PASSED")


if __name__ == "__main__":
    main()
