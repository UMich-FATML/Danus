"""One-shot DSH authoring with a fresh empty cwd and embedded prompt.

The CompletedProcess stdout contract is the lossless terminal final.text, never
DSH's JSON stream or intermediate (possibly truncated) projections. Offline
writers have no filesystem, shell, web or delegation tools. Reference verifiers
retain a read-only gateway and web tools in an isolated read-only workspace.
"""
from __future__ import annotations

import os
import subprocess
import tempfile
from pathlib import Path

from danus import dsh

DEFAULT_MODEL = dsh.DEFAULT_MODEL
DEFAULT_EFFORT = dsh.DEFAULT_EFFORT
DEFAULT_TIMEOUT = 7200


def default_model() -> str:
    return dsh.model()


def default_effort() -> str:
    return dsh.effort()


def run_dsh(prompt: str, *, model: str | None = None, effort: str | None = None,
            timeout: int | None = None, networked: bool = False,
            gateway_role: str = "verifier") -> subprocess.CompletedProcess:
    """Run one fresh session. Propagate timeout/missing binary and honest failure.

    The networked path permits only the existing read-only verifier gateway role;
    no authoring caller may obtain a worker's fact_submit capability.
    """
    if networked and gateway_role != "verifier":
        raise ValueError("networked authoring requires the read-only verifier role")
    if timeout is None:
        timeout = int(os.environ.get("DANUS_AUTHORING_TIMEOUT_SECONDS", str(DEFAULT_TIMEOUT)))
    with tempfile.TemporaryDirectory(prefix="danus-authoring-dsh-") as empty_cwd:
        return dsh.run(prompt, cwd=Path(empty_cwd),
                       model=default_model() if model is None else model,
                       effort=default_effort() if effort is None else effort,
                       timeout=timeout, role="verifier" if networked else None,
                       sandbox="read-only", authoring=True)
