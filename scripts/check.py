#!/usr/bin/env python3
"""Canonical offline checks: fast structural guards, then the complete test suite."""
from __future__ import annotations

import argparse
import os
from pathlib import Path
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]


def isolated_env(home: Path, source: dict[str, str] | None = None) -> dict[str, str]:
    source = os.environ if source is None else source
    env = {key: value for key, value in source.items()
           if not key.startswith(("DANUS_", "CODEX_", "DSH_", "VERIFY_", "VERIFIER_"))
           and not any(word in key.upper() for word in ("API_KEY", "TOKEN", "SECRET", "PASSWORD"))}
    env.update(DSH_HOME=str(home / "dsh"), DSH_AGENTS_HOME=str(home / "agents"),
               DANUS_DSH_RUNS_DIR=str(home / "runs"), PYTHONDONTWRITEBYTECODE="1")
    return env


def commands(root: Path, *, fast: bool = False) -> list[list[str]]:
    result = [[sys.executable, "scripts/harness_lint.py"],
              [sys.executable, "agents/skills/worker/check_conformance.py"]]
    # Parse scripts only: never source deployment settings or execute services.
    shells = set(root.glob("scripts/*.sh")) | set(root.glob("examples/ops/*.sh"))
    for folder in (root / "bin", root / ".githooks"):
        if folder.is_dir():
            for path in folder.iterdir():
                if path.is_file() and not path.is_symlink():
                    first = path.read_bytes().split(b"\n", 1)[0]
                    if first in (b"#!/usr/bin/env bash", b"#!/bin/bash"):
                        shells.add(path)
    result.extend(["bash", "-n", str(path.relative_to(root))] for path in sorted(shells))
    result.extend(["node", "--check", str(path.relative_to(root))]
                  for path in sorted(root.glob(".dsh/*.mjs")))
    if not fast:
        result.extend([
            [sys.executable, "-m", "pytest", "danus/", "scripts/tests/", ".dsh/test_ops.py",
             "agents/skills/verify/test_verification_schema.py", "-q"],
            ["node", "--test", ".dsh/main-checkpoints.test.mjs"],
        ])
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fast", action="store_true", help="Structural/skill/syntax guards only")
    args = parser.parse_args(argv)
    with tempfile.TemporaryDirectory(prefix="danus-check-") as directory:
        env = isolated_env(Path(directory))
        for command in commands(ROOT, fast=args.fast):
            print("+ " + " ".join(command), flush=True)
            result = subprocess.run(command, cwd=ROOT, env=env)
            if result.returncode:
                return result.returncode
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
