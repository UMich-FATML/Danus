"""Provide a ``tmp`` fixture for the orchestration tests (parity with the
standalone ``main()`` runner, which passes a Path directly)."""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest
from danus.tests.dsh_fixture import fake_dsh_environment  # noqa: F401


@pytest.fixture
def tmp():
    with tempfile.TemporaryDirectory() as d:
        yield Path(d)
