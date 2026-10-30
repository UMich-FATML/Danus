#!/usr/bin/env python3
"""Small, offline repository invariants. Diagnostics include their remediation."""
from __future__ import annotations

import ast
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]


def check_tracked_paths(paths: list[str]) -> list[str]:
    errors = []
    for name in paths:
        path = Path(name)
        if name.startswith(("runtime/", ".pixi/")) or ".gitstore" in path.parts or path.suffix in {".pem", ".key", ".p12", ".pfx"} or (
            name.startswith("config/") and path.suffix == ".env"
        ):
            errors.append(f"H001 {name}: remove runtime/credential state from the source index; "
                          "keep it ignored (docs/dev/invariants.md#h001-source-containment).")
    return errors


def check_core_imports(path: Path) -> list[str]:
    errors = []
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    for node in ast.walk(tree):
        modules = []
        if isinstance(node, ast.Import):
            modules = [alias.name for alias in node.names]
        elif isinstance(node, ast.ImportFrom) and not node.level:
            modules = [node.module or ""]
        for module in modules:
            if module.split(".")[0] not in sys.stdlib_module_names and not module.startswith("danus.core"):
                errors.append(f"H002 {path}:{node.lineno}: core must stay stdlib-only; move "
                              "runtime/network integration outside core "
                              "(docs/dev/invariants.md#h002-core-boundary).")
    return errors


def check(root: Path = ROOT) -> list[str]:
    paths = subprocess.run(["git", "ls-files", "-z"], cwd=root, check=True,
                           capture_output=True).stdout.decode().split("\0")
    errors = check_tracked_paths([p for p in paths if p])
    for probe in ("runtime/.gitstore/probe.git/config", "runtime/projects/probe/project.json", ".pixi/envs/probe/bin/python"):
        if subprocess.run(["git", "check-ignore", "--no-index", "-q", probe], cwd=root).returncode != 0:
            errors.append(f"H001 {probe}: add its generated root to .gitignore "
                          "(docs/dev/invariants.md#h001-source-containment).")
    for path in sorted((root / "danus/core").glob("*.py")):
        errors.extend(check_core_imports(path))
    for name in ("CONTRIBUTING.md", "docs/dev/index.md", "docs/dev/invariants.md",
                 "docs/git-resume.md", "docs/dsh-migration.md", "docs/tech-debt.md"):
        if not (root / name).is_file():
            errors.append(f"H003 {name}: restore the contributor/runtime map target "
                          "(docs/dev/invariants.md#h003-entry-points).")
    for directory in ("danus/execution", "danus/verify", "danus/authoring"):
        for path in (root / directory).glob("*.py"):
            text = path.read_text(encoding="utf-8")
            if "from danus import codex" in text or "from danus.codex import" in text:
                errors.append(f"H004 {path.relative_to(root)}: use the shared danus.dsh adapter; "
                              "no Codex execution fallback "
                              "(docs/dev/invariants.md#h004-single-runtime).")
    return errors


if __name__ == "__main__":
    failures = check()
    for failure in failures:
        print(failure, file=sys.stderr)
    if not failures:
        print("Harness invariants passed")
    raise SystemExit(bool(failures))
