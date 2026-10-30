"""Offline failing-path coverage for the repository's small static guardrails."""
import importlib.util
from pathlib import Path

SPEC = importlib.util.spec_from_file_location(
    "harness_lint", Path(__file__).resolve().parents[1] / "harness_lint.py"
)
lint = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(lint)


def test_generated_state_and_credentials_cannot_be_tracked():
    errors = lint.check_tracked_paths([
        "runtime/projects/demo/project.json", "config/danus.env", ".pixi/envs/default/a", "private.key",
        "config/danus.env.example", "danus/core/schema.py",
    ])
    assert len(errors) == 4
    assert all("H001" in error and "docs/dev/invariants.md" in error for error in errors)


def test_core_stays_stdlib_only(tmp_path):
    path = tmp_path / "core.py"
    path.write_text("import json\nfrom .schema import Fact\nfrom pathlib import Path\n")
    assert lint.check_core_imports(path) == []
    path.write_text("import requests\nfrom danus.gateway import server\n")
    errors = lint.check_core_imports(path)
    assert len(errors) == 2
    assert all("H002" in error and "move" in error for error in errors)


def test_missing_maps_and_legacy_runtime_have_actionable_errors(tmp_path, monkeypatch):
    from types import SimpleNamespace
    monkeypatch.setattr(lint.subprocess, "run", lambda *a, **k:
                        SimpleNamespace(returncode=0, stdout=b""))
    runtime = tmp_path / "danus/execution/loop.py"
    runtime.parent.mkdir(parents=True)
    runtime.write_text("from danus import codex\n")
    failures = lint.check(tmp_path)
    assert any("H003" in item and "restore" in item for item in failures)
    assert any("H004" in item and "shared danus.dsh" in item for item in failures)
