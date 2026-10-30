"""Offline-only DSH configuration fixture; never grants a live provider route."""
import json
import os
from contextlib import contextmanager
from pathlib import Path

import pytest


@contextmanager
def configured_dsh(root: Path):
    root.mkdir(parents=True, exist_ok=True)
    patch = root / "fake-provider.json"
    models = ["gpt-5.6-sol", "m", "m-test", "the-model", "test-model"]
    patch.write_text(json.dumps([{"id": "llm-pi-ai", "config": {"providers": {"test": {
        "api": "openai-responses", "baseURL": "http://127.0.0.1:1/never-call",
        "apiKeyEnv": "DANUS_TEST_NO_LIVE_KEY", "models": [{"id": model,
            "reasoningEfforts": {e: e for e in ("low", "medium", "high", "xhigh", "ultra", "e-test")}}
            for model in models]}}}}]), encoding="utf-8")
    values = {"DANUS_DSH_PROVIDER": "test", "DANUS_DSH_PROVIDER_PATCH": str(patch.resolve()),
              "DANUS_DSH_RUNS_DIR": str((root / "dsh-runs").resolve()),
              "DANUS_DSH_BIN": str((root / "LIVE_DSH_IS_FORBIDDEN").resolve()),
              "DANUS_TEST_NO_LIVE_KEY": "offline-test-placeholder", "DANUS_SNAPSHOT_AUTO": "0"}
    previous = {name: os.environ.get(name) for name in values}
    os.environ.update(values)
    try:
        yield
    finally:
        for name, value in previous.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value


@pytest.fixture(autouse=True)
def fake_dsh_environment(tmp_path):
    with configured_dsh(tmp_path / "offline-dsh"):
        yield
