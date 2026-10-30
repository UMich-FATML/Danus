"""Main-only DSH overlay and launcher; no inherited operator GUI profile."""
from __future__ import annotations

import argparse
import asyncio
import json
import os
from pathlib import Path
import sys
import uuid

from danus import dsh

ROOT = Path(__file__).resolve().parents[1]
MCP_TIMEOUT_MS = 3_600_000


def mcp_rows() -> list[dict]:
    timeout = int(os.environ.get("DANUS_AUTHORING_TIMEOUT_SECONDS", "3300"))
    if timeout <= 0 or timeout >= MCP_TIMEOUT_MS // 1000:
        raise ValueError("DANUS_AUTHORING_TIMEOUT_SECONDS must be between 1 and 3599")
    # Secrets are references evaluated by DSH, never copied into the overlay.
    names = {key for key in os.environ if key.startswith("DANUS_")}
    names.update({"PATH", "DSH_HOME", "DSH_AGENTS_HOME", "DANUS_DSH_HOME", "DANUS_DSH_AGENTS_HOME",
                  "DANUS_DSH_ISOLATED", "VERIFIER_RESULTS_DIR", "VERIFY_PORT"})
    _, provider_patch = dsh.provider_config()
    for row in json.loads(provider_patch.read_text(encoding="utf-8")):
        for route in row.get("config", {}).get("providers", {}).values():
            if route.get("apiKeyEnv"):
                names.add(route["apiKeyEnv"])
    env = {key: f"__DANUS_ENV_REF__{key}" for key in sorted(names)}
    env.update(DANUS_ROLE="main", DANUS_AUTHOR="main_agent",
               DANUS_AUTHORING_TIMEOUT_SECONDS=str(timeout), DANUS_VERIFY_TIMEOUT="3500")
    return [{"id": f"danus-{name}-mcp", "name": "@deepseek-ai/dsh-mcp-client", "config": {
        "serverName": name, "transport": "stdio", "command": str(ROOT / "bin" / wrapper),
        "args": [], "cwd": str(ROOT), "env": env.copy(),
        "toolCallTimeoutMs": MCP_TIMEOUT_MS, "failOnStartupError": True,
    }} for name, wrapper in (("danus", "danus-mcp"), ("write-paper", "write-paper-mcp"),
                            ("human-summary", "human-summary-mcp"))]


async def preflight_main(env: dict[str, str], *, verbose: bool = False) -> None:
    from danus.gateway.roles import ROLE_TOOLS
    expected = {"danus": set(ROLE_TOOLS["main"]),
                "write-paper": {"paper_subgraph", "paper_write", "reference_audit", "reference_verify", "paper_revise", "paper_verify_math"},
                "human-summary": {"summary_write"}}
    for row in mcp_rows():
        config = row["config"].copy()
        config["env"] = {key: env.get(value.removeprefix("__DANUS_ENV_REF__"), "")
                         if value.startswith("__DANUS_ENV_REF__") else value
                         for key, value in config["env"].items()}
        names = await dsh.preflight_mcp(config, expected[config["serverName"]])
        if verbose:
            print(f"ok MCP {config['serverName']}: initialized, {len(names)} tools (none called)")


def main_rows(*, headless: bool = False) -> list[dict]:
    provider, provider_patch = dsh.provider_config()
    dsh.validate_model_selection(provider_patch, provider, dsh.model(), dsh.effort())
    rows = dsh.site_patch(model=dsh.model(), effort=dsh.effort(), provider=provider,
                         cwd=ROOT, role="main", instructions="AGENTS.md",
                         skill_dirs=[ROOT / ".agents" / "skills"], sandbox="danger-full-access")
    rows = [row for row in rows if "insert" not in row]
    hook = {"id": "danus-main-checkpoints", "name": str(ROOT / ".dsh" / "main-checkpoints.mjs"),
            "config": {"role": "main", "python": os.environ.get("DANUS_PY", sys.executable), "cwd": str(ROOT),
                       "pendingDir": str(Path(os.environ.get("DANUS_RUNTIME", ROOT / "runtime")).resolve() / "checkpoint-requests")}}
    if headless:
        rows.append({"insert": [*mcp_rows(), hook]})
        return rows
    # Web keeps model/permissions/goals on the host, but tools/instructions live
    # inside a preset. Replace the WHOLE custom preset config, not partial keys.
    preset = json.loads((ROOT / ".dsh" / "main-preset.json").read_text(encoding="utf-8"))
    scoped = {row["id"]: row["config"] for row in rows
              if row.get("id") in {"agent-instructions", "skill-filesystem"}}
    rows = [row for row in rows if row.get("id") not in scoped]
    for plugin in preset["plugins"]:
        if plugin["id"] in scoped:
            plugin["config"] = scoped[plugin["id"]]
    preset["plugins"].extend(mcp_rows())
    hook["config"]["preset"] = "danus-main"
    rows.extend([{"id": "agent-preset-registry", "config": {"default": "danus-main"}},
                 {"id": "hmr", "disabled": True}])
    # Other shipped presets must not offer a way around this role configuration.
    rows.extend({"id": f"preset-{name}", "disabled": True} for name in ("standard", "ptc", "minimal", "cordis"))
    rows.append({"insert": [{"id": "preset-danus-main", "name": "@deepseek-ai/dsh-agent-preset",
                             "config": preset}, hook]})
    return rows


def patch_text(rows: list[dict]) -> str:
    text = json.dumps(rows, indent=2)
    # JSON flow collections are valid YAML; replace only tagged reference values.
    import re
    def reference(match: re.Match) -> str:
        key = match.group(1)
        return "!!js " + json.dumps(f"process.env[{json.dumps(key)}] ?? ''")
    return re.sub(r'"__DANUS_ENV_REF__([A-Za-z_][A-Za-z0-9_]*)"', reference, text) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(description="Launch an isolated loopback Danus Web main host (paid only when tasks run)")
    parser.add_argument("--headless", action="store_true", help="One-shot JSON task instead of resident Web; no schedule service")
    parser.add_argument("--task-file", type=Path, help="Headless only: read task from a file instead of stdin")
    parser.add_argument("--write-patch", type=Path, help="Only write the selected main overlay; no DSH/model invocation")
    args = parser.parse_args()
    if args.task_file and not args.headless:
        parser.error("--task-file requires --headless; use the Web UI to start a resident main session")
    provider, provider_patch = dsh.provider_config()
    rows = main_rows(headless=args.headless)
    if args.write_patch:
        args.write_patch.parent.mkdir(parents=True, exist_ok=True)
        args.write_patch.write_text(patch_text(rows), encoding="utf-8")
        args.write_patch.chmod(0o600)
        print(args.write_patch.resolve())
        return
    # Web homes persist native goals/reminders, but are owned by this deployment,
    # never the current GUI's DSH_HOME. Headless calls get fresh per-run homes.
    runtime = Path(os.environ.get("DANUS_RUNTIME", ROOT / "runtime")).resolve()
    run_dir = runtime / "main-dsh" / (uuid.uuid4().hex if args.headless else "web")
    run_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    patch = run_dir / "main.patch.yml"
    patch.write_text(patch_text(rows), encoding="utf-8")
    patch.chmod(0o600)
    binary = dsh.resolve_bin()
    env = dsh.subprocess_env(binary)
    env["DANUS_DSH_ISOLATED"] = "1"
    for key, name in (("DSH_HOME", "home"), ("DSH_AGENTS_HOME", "agents")):
        path = (run_dir / name).resolve()
        path.mkdir(exist_ok=True, mode=0o700)
        env[key] = env[f"DANUS_{key}"] = str(path)
    profile = "headless" if args.headless else "web"
    command = [binary, "--profile", profile, "--patch", str(provider_patch), "--patch", str(patch.resolve())]
    if args.headless:
        command.append("--json")
    else:
        port = int(os.environ.get("DANUS_MAIN_PORT", "8090"))
        if not 1 <= port <= 65535:
            raise ValueError("DANUS_MAIN_PORT must be between 1 and 65535")
        # Verified against dsh-web-app/lib/startup.js 0.2.1-rc.5, not guessed.
        command.extend(["--host", "127.0.0.1", "--port", str(port), "--no-open"])
        print(f"Starting separate Danus main host at http://127.0.0.1:{port}; existing GUI is untouched.", file=sys.stderr)
    # A failed optional DSH MCP plugin must not silently launch a main without
    # its tools. Check the actual wrapper protocols before any model can run.
    asyncio.run(preflight_main(env))
    if args.task_file:
        task = args.task_file.open("rb")
        os.dup2(task.fileno(), 0)
    os.chdir(ROOT)
    os.execvpe(binary, command, env)


if __name__ == "__main__":
    try:
        main()
    except (OSError, ValueError) as error:
        raise SystemExit(str(error)) from error
