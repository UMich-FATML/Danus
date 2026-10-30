"""Offline checks only: config, pinned executable, and MCP discovery (no calls)."""
from __future__ import annotations

import argparse
import asyncio
import os
from pathlib import Path
import subprocess
import tempfile

from danus import dsh
from main_dsh import main_rows, patch_text, preflight_main


def validate_config() -> None:
    dsh.provider_config()
    main_rows()


def isolated_env(directory: Path) -> dict[str, str]:
    env = dsh.subprocess_env(dsh.resolve_bin())
    env.update(DSH_HOME=str(directory / "home"), DSH_AGENTS_HOME=str(directory / "agents"),
               DANUS_DSH_HOME=str(directory / "home"), DANUS_DSH_AGENTS_HOME=str(directory / "agents"),
               DANUS_DSH_ISOLATED="1")
    return env


def check_executable() -> None:
    with tempfile.TemporaryDirectory(prefix="danus-dsh-version-") as directory:
        result = subprocess.run([dsh.resolve_bin(), "--version"], capture_output=True, text=True,
                                env=isolated_env(Path(directory)), timeout=30)
    if result.returncode or result.stdout.strip() != "0.2.1-rc.5":
        raise ValueError("DSH executable must report 0.2.1-rc.5; configure DANUS_DSH_BIN")


def check_composition() -> None:
    # --dump-config initializes a profile. Always use a disposable test home;
    # never touch the operator's profile or print evaluated credentials.
    with tempfile.TemporaryDirectory(prefix="danus-dsh-compose-") as directory:
        root = Path(directory)
        _, provider_patch = dsh.provider_config()
        for profile in ("web", "headless"):
            patch = root / f"main-{profile}.patch.yml"
            patch.write_text(patch_text(main_rows(headless=profile == "headless")), encoding="utf-8")
            result = subprocess.run([dsh.resolve_bin(), "--profile", profile, "--patch",
                                     str(provider_patch), "--patch", str(patch), "--dump-config"],
                                    capture_output=True, text=True, env=isolated_env(root), timeout=60)
            if result.returncode:
                # Startup errors can embed secrets. Keep diagnostics private.
                raise ValueError(f"DSH isolated {profile} composition failed (exit {result.returncode}); no model request made")
            required = ["danus-main-checkpoints"]
            if profile == "web":
                required += ["preset-danus-main", "@deepseek-ai/dsh-schedule", "@deepseek-ai/dsh-tool-schedule",
                             "@deepseek-ai/dsh-tool-goal", "@deepseek-ai/dsh-tool-subagent"]
            if any(name not in result.stdout for name in required):
                raise ValueError(f"DSH {profile} composed config missing a required main plugin")


async def check_handshakes() -> None:
    with tempfile.TemporaryDirectory(prefix="danus-mcp-check-") as directory:
        await preflight_main(isolated_env(Path(directory)), verbose=True)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config-only", action="store_true", help="No subprocess/profile/MCP startup")
    parser.add_argument("--compose", action="store_true", help="Also dump config privately in an isolated temporary home")
    args = parser.parse_args()
    validate_config()
    print("ok explicit provider/site config structure; credentials and endpoint NOT verified")
    if args.config_only:
        return
    check_executable()
    print("ok installed DSH version 0.2.1-rc.5")
    if args.compose:
        check_composition()
        print("ok isolated DSH profile composition (not inference)")
    asyncio.run(asyncio.wait_for(check_handshakes(), timeout=60))
    print("Offline checks passed. No model call made; model availability, authentication and billing remain untested.")


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        # Do not serialize exception groups / server stderr into config reports.
        raise SystemExit(f"Offline DSH check failed: {type(error).__name__}: {error}") from error
