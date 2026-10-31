#!/usr/bin/env python3
"""Install this repository's fast pre-commit gate without changing global Git config."""
from __future__ import annotations

import argparse
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[1]


def install(root: Path, *, force: bool = False) -> str:
    root = root.resolve()
    actual = Path(subprocess.run(["git", "rev-parse", "--show-toplevel"], cwd=root,
                                check=True, text=True, capture_output=True).stdout.strip()).resolve()
    if actual != root:
        raise ValueError("run the hook installer at the Danus repository root")
    hook = root / ".githooks" / "pre-commit"
    if (hook.parent.is_symlink() or not hook.is_file() or hook.is_symlink()
            or not hook.stat().st_mode & 0o111):
        raise ValueError("restore a real executable .githooks/pre-commit (no symlink directories) before installing hooks")
    current = subprocess.run(["git", "config", "--get", "core.hooksPath"], cwd=root,
                             capture_output=True, text=True)
    if current.returncode not in (0, 1):
        raise ValueError("cannot inspect the current Git hooks path; no configuration changed")
    value = current.stdout.strip()
    if value:
        selected = Path(value).expanduser()
        if not selected.is_absolute():
            selected = root / selected
        if selected.resolve() == (root / ".githooks").resolve():
            return "Danus hooks already configured; no changes made."
        if not force:
            raise ValueError(f"existing core.hooksPath={value!r}; preserve or integrate those hooks, "
                             "or explicitly run pixi run install-hooks --force to replace the local setting")
    subprocess.run(["git", "config", "--local", "core.hooksPath", ".githooks"],
                   cwd=root, check=True)
    return "Installed repository-local fast pre-commit checks; global Git configuration unchanged."


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--force", action="store_true", help="Explicitly override an existing hooks path locally")
    args = parser.parse_args(argv)
    try:
        print(install(ROOT, force=args.force))
    except (ValueError, OSError, subprocess.CalledProcessError) as error:
        parser.exit(1, f"Danus hooks: {error}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
