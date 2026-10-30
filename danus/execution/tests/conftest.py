"""Provide a ``tmp`` fixture (a fresh temp dir Path) for the execution tests, so
each test function reads identically whether run under pytest or the standalone
``main()`` runner (which passes a Path directly)."""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest
from danus.tests.dsh_fixture import fake_dsh_environment


@pytest.fixture
def tmp():
    with tempfile.TemporaryDirectory() as d:
        yield Path(d)
