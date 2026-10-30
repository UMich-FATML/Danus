"""Fail-closed DSH 0.2.1-rc.5 headless transport shared by every Danus role.

Provider patches are explicit JSON, never a user's GUI profile. Each invocation
has fresh, durable homes under DANUS_DSH_RUNS_DIR (default runtime/dsh-runs).
Only the lossless terminal ``final.text`` is an artifact; intermediate JSON
projections can be truncated. Exit zero alone does not mean a completed turn.
"""
from __future__ import annotations

import asyncio
import json
import os
import re
import shutil
import signal
import subprocess
import sys
import uuid
from pathlib import Path
from typing import Callable, Optional, Sequence

_REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_MODEL = "gpt-5.6-sol"
DEFAULT_EFFORT = "xhigh"


def resolve_bin() -> str:
    override = os.environ.get("DANUS_DSH_BIN")
    if override:
        return override if os.path.isabs(override) else shutil.which(override) or override
    wrapper = _REPO_ROOT / "bin" / "dsh"
    return str(wrapper) if wrapper.is_file() else shutil.which("dsh") or "dsh"


def model(*overrides: str, default: str = DEFAULT_MODEL) -> str:
    return next((os.environ[n] for n in (*overrides, "DANUS_MAIN_MODEL")
                 if os.environ.get(n)), default)


def effort(*overrides: str, default: str = DEFAULT_EFFORT) -> str:
    return next((os.environ[n] for n in (*overrides, "DANUS_MAIN_EFFORT")
                 if os.environ.get(n)), default)


def subprocess_env(dsh_bin: str) -> dict[str, str]:
    """Copy launch credentials/PATH, but never inherit a GUI session identity."""
    env = os.environ.copy()
    for key in list(env):
        if key.startswith("DSH_"):
            env.pop(key)
    if os.path.dirname(dsh_bin):
        directory = str(Path(dsh_bin).absolute().parent)
        old = env.get("PATH", "")
        if directory not in old.split(os.pathsep):
            env["PATH"] = directory + (os.pathsep + old if old else "")
    env["DSH_TELEMETRY_DISABLED"] = "1"
    return env


def provider_config(worker_project: Optional[str] = None) -> tuple[str, Path]:
    """Resolve an explicit route and JSON patch, rejecting partial/legacy profiles."""
    provider_name, patch_name = "DANUS_DSH_PROVIDER", "DANUS_DSH_PROVIDER_PATCH"
    if worker_project is not None:
        token = re.sub(r"[^A-Za-z0-9]+", "_", worker_project).strip("_").upper()
        if not token:
            raise ValueError("worker project has no environment-safe characters")
        prefix = f"DANUS_PROJECT_{token}_WORKER_"
        if any(k.startswith(prefix + "API_") and v for k, v in os.environ.items()):
            raise ValueError(f"legacy {prefix}API_* is unsupported; configure a DSH provider patch")
        names = (prefix + "DSH_PROVIDER", prefix + "DSH_PROVIDER_PATCH")
        if any(os.environ.get(n) for n in names):
            provider_name, patch_name = names
    provider = os.environ.get(provider_name, "").strip()
    patch = os.environ.get(patch_name, "").strip()
    if not provider or not patch:
        raise ValueError(f"both {provider_name} and {patch_name} are required (no provider fallback)")
    path = Path(patch).expanduser()
    if not path.is_absolute():
        raise ValueError(f"{patch_name} must be an absolute path")
    rows = json.loads(path.read_text(encoding="utf-8"))
    validate_provider_patch(rows, provider)
    return provider, path.resolve()


def validate_provider_patch(rows: object, provider: str) -> None:
    """Provider-only overlays cannot replace permissions, instructions or tools.

    DSH's pi-ai provider profiles use their ``name`` as the route; the native
    adapter exposes ``providerName``. Unknown/misspelled routes fail before spawn.
    """
    if not isinstance(rows, list) or not rows:
        raise ValueError("DSH provider patch must be a nonempty JSON patch list")
    routes = set()
    seen = set()
    for row in rows:
        if not isinstance(row, dict) or set(row) - {"id", "config", "disabled"}:
            raise ValueError("provider patch permits only provider config/disabled rows")
        identity = row.get("id")
        if not isinstance(identity, str) or identity in seen:
            raise ValueError("provider patch row ids must be unique strings")
        seen.add(identity)
        if "disabled" in row and not isinstance(row["disabled"], bool):
            raise ValueError("provider disabled must be a boolean")
        if identity not in {"llm-pi-ai", "llm-deepseek", "llm-deepseek-account"}:
            raise ValueError(f"unexpected provider patch row: {identity!r}")
        if row.get("disabled") is True:
            continue
        config = row.get("config", {})
        if not isinstance(config, dict):
            raise ValueError("provider config must be an object")
        if identity == "llm-pi-ai":
            profiles = config.get("providers", {})
            if not isinstance(profiles, dict):
                raise ValueError("llm-pi-ai providers must be an object keyed by route")
            for route, profile in profiles.items():
                if not isinstance(profile, dict) or not route or not profile.get("apiKeyEnv"):
                    raise ValueError("each provider requires an explicit route and apiKeyEnv")
                if not profile.get("api") or not profile.get("baseURL"):
                    raise ValueError("each provider requires explicit api and baseURL (no fallback)")
                routes.add(route)
        else:
            raise ValueError("Danus provider overlays must configure explicit llm-pi-ai routes; native/account rows may only be disabled")
    if provider not in routes:
        raise ValueError(f"configured provider {provider!r} is absent from the provider patch")


def validate_model_selection(provider_patch: Path, provider: str, model: str, effort: str) -> None:
    """Refuse unsupported model/effort instead of letting a provider choose defaults."""
    rows = json.loads(Path(provider_patch).read_text(encoding="utf-8"))
    validate_provider_patch(rows, provider)
    profiles = [row["config"]["providers"][provider] for row in rows
                if row.get("id") == "llm-pi-ai" and not row.get("disabled")
                and provider in row.get("config", {}).get("providers", {})]
    profile = profiles[-1]
    key_env = profile["apiKeyEnv"]
    if not isinstance(key_env, str) or not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", key_env):
        raise ValueError("apiKeyEnv must name an environment variable")
    if not os.environ.get(key_env):
        raise ValueError(f"provider credential environment variable {key_env} is missing")
    declared = profile.get("models", [])
    if not isinstance(declared, list):
        raise ValueError("provider models must be an explicit list")
    matches = [m for m in declared if isinstance(m, dict) and m.get("id") == model]
    if len(matches) != 1:
        raise ValueError(f"model {model!r} must be explicitly declared once for provider {provider!r}")
    supported = matches[0].get("reasoningEfforts")
    if not isinstance(supported, dict) or effort not in supported or not isinstance(supported[effort], str):
        raise ValueError(f"effort {effort!r} must be explicitly supported for model {model!r}")


def gateway_row(*, role: str, cwd: Path, project_dir: Optional[Path] = None,
                author: Optional[str] = None) -> dict:
    env = {"DANUS_ROLE": role}
    if project_dir is not None:
        env["DANUS_PROJECT_DIR"] = str(Path(project_dir).resolve())
    if author is not None:
        env["DANUS_AUTHOR"] = author
    env["DANUS_VERIFY_URL"] = os.environ.get("DANUS_VERIFY_URL", "http://127.0.0.1:8091/verify")
    return {"id": "danus-gateway", "name": "@deepseek-ai/dsh-mcp-client", "config": {
        "serverName": "danus", "transport": "stdio", "command": sys.executable,
        "args": ["-m", "danus.gateway"], "env": env, "cwd": str(Path(cwd).resolve()),
        "toolCallTimeoutMs": 3600000, "failOnStartupError": True,
    }}


async def preflight_mcp(config: dict, expected_tools: set[str] | None = None,
                        timeout: float = 20) -> set[str]:
    """Initialize/list_tools over the actual stdio transport; never invoke a tool.

    This supplements DSH's plugin-local startup failure handling: a missing or
    mis-scoped gateway must fail the Danus launch, not become an optional plugin.
    """
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client

    async def check() -> set[str]:
        ambient = {key: value for key, value in os.environ.items()
                   if not key.startswith("DSH_") and not re.search(r"KEY|PASSWORD|SECRET|TOKEN", key, re.I)}
        params = StdioServerParameters(command=config["command"], args=config.get("args", []),
            env={**ambient, **config.get("env", {})}, cwd=config.get("cwd"))
        with open(os.devnull, "w") as errlog:
            async with stdio_client(params, errlog=errlog) as (reader, writer):
                async with ClientSession(reader, writer) as session:
                    await session.initialize()
                    result = await session.list_tools()
                    names = {tool.name for tool in result.tools}
                    if expected_tools is not None and names != set(expected_tools):
                        raise ValueError(f"MCP tool surface mismatch: expected {sorted(expected_tools)}, got {sorted(names)}")
                    return names
    try:
        return await asyncio.wait_for(check(), timeout=timeout)
    except Exception as exc:
        raise ValueError(f"required MCP server {config.get('serverName', 'unknown')} failed readiness: {exc}") from exc


def site_patch(*, model: str, effort: str, provider: str, cwd: Path,
               role: Optional[str] = None, project_dir: Optional[Path] = None,
               author: Optional[str] = None, instructions: Optional[str] = None,
               skill_dirs: Sequence[Path] = (), sandbox: str = "workspace-write",
               authoring: bool = False) -> list[dict]:
    """Complete replacement configs, compatible with the shipped headless base."""
    if not all(isinstance(x, str) and x.strip() for x in (provider, model, effort)):
        raise ValueError("provider, model and effort must be explicit nonempty strings")
    if role not in (None, "main", "worker", "verifier"):
        raise ValueError(f"unsupported gateway role {role!r}")
    if instructions and (Path(instructions).name != instructions or instructions in (".", "..")):
        raise ValueError("instructions must be a same-directory filename")
    rows = [
        {"id": "agent-default-model", "config": {"provider": provider, "model": model,
                                                   "reasoningEffort": effort}},
        {"id": "sandbox-policy", "config": {"mode": sandbox, "workspaceRoot": str(Path(cwd).resolve())}},
        {"id": "approval", "config": {"policy": "never"}},
        {"id": "agent-instructions", "config": {"maxBytes": 65536,
            "projectRootMarkers": [instructions] if instructions else [],
            "instructionFileCandidates": [instructions] if instructions else [],
            "localInstructionFileCandidates": []}},
        {"id": "skill-filesystem", "config": {"includeDefaultRoots": False,
            "customSkillDirs": [str(Path(p).resolve()) for p in skill_dirs], "watch": False}},
        {"id": "session-title-llm", "disabled": True},
        {"id": "credentials", "disabled": True},
        {"id": "authorization", "disabled": True},
        {"id": "deepseek-account", "disabled": True},
        {"id": "llm-deepseek-account", "disabled": True},
    ]
    if role:
        rows.append({"insert": [gateway_row(role=role, cwd=cwd, project_dir=project_dir, author=author)]})
    disabled = set()
    if role != "main":
        disabled.update(("tool-subagent", "tool-subagent-fork", "tool-workflow", "tool-goal"))
    if authoring or role is None:
        # Both authoring modes use ONLY their embedded prompt. Networked reference
        # verification adds the read-only MCP/web surface, never filesystem/shell.
        disabled.update(("tool-bash", "tool-pwsh", "tool-fs", "tool-fs-search", "tool-jobs",
                         "tool-working-directory", "tool-skill"))
    if role is None:
        disabled.add("tool-web")
    for tool in sorted(disabled):
        rows.append({"id": tool, "disabled": True})
    return rows


class DshResult(subprocess.CompletedProcess):
    """CompletedProcess contract plus durable invocation/session metadata."""
    session_id: Optional[str] = None
    reason: Optional[str] = None
    run_id: Optional[str] = None
    run_dir: Optional[Path] = None


def process_identity(pid: int) -> dict:
    """PID plus Linux birth tick for durable orphan detection, never just a PID."""
    try:
        # comm can contain spaces/parentheses; fields after its final ')' start at 3.
        tail = Path(f"/proc/{pid}/stat").read_text().rsplit(")", 1)[1].split()
        started = tail[19]
    except (OSError, IndexError):
        started = None
    return {"pid": pid, "start_ticks": started}


def is_same_process(identity: dict) -> bool:
    """Conservative on hosts without /proc; callers may refuse rather than signal."""
    pid = identity.get("pid")
    if not isinstance(pid, int) or isinstance(pid, bool) or pid <= 1:
        raise ValueError("invalid child process identity")
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    observed = process_identity(pid)["start_ticks"]
    recorded = identity.get("start_ticks")
    return recorded is None or observed is None or recorded == observed


def terminate_process_group(proc: subprocess.Popen, grace: float = 5) -> None:
    """Reap the headless process and terminate descendants, including MCP servers."""
    try:
        os.killpg(proc.pid, signal.SIGTERM)
    except ProcessLookupError:
        pass
    try:
        proc.wait(timeout=grace)
    except subprocess.TimeoutExpired:
        pass
    finally:
        # A parent can exit before its descendants; still clean its whole group.
        try:
            os.killpg(proc.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        proc.wait()


def parse_events(path: Path) -> tuple[Optional[str], Optional[str], Optional[str], Optional[str]]:
    session_id = reason = final = error = None
    with path.open(encoding="utf-8", errors="replace") as stream:
        for line in stream:
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                error = "malformed DSH JSON event"
                continue
            if not isinstance(event, dict):
                error = "invalid DSH JSON event"
                continue
            if final is not None:
                error = "DSH event after terminal final"
            if event.get("type") == "session":
                if event.get("truncated"):
                    error = "truncated DSH session event"
                sid = event.get("sessionId")
                if not isinstance(sid, str) or not sid or (session_id and session_id != sid):
                    error = "invalid or conflicting DSH session id"
                else:
                    session_id = sid
            elif event.get("type") == "status" and event.get("phase") == "turn_start":
                reason = None
            elif event.get("type") == "status" and event.get("phase") == "turn_end":
                if event.get("truncated"):
                    error = "truncated DSH terminal status"
                terminal = event.get("reason")
                # 0.2.1-rc.5 emits a tagged object, not a bare string. Keep the
                # string form for simple older fixtures, never accept other types.
                reason = terminal.get("kind") if isinstance(terminal, dict) else terminal
                if not isinstance(reason, str):
                    reason = None
            elif event.get("type") == "final":
                if reason is None:
                    error = "DSH final before terminal status"
                if final is not None or not isinstance(event.get("text"), str) or event.get("truncated"):
                    error = "invalid or duplicate DSH final event"
                else:
                    final = event["text"]
    return session_id, reason, final, error


def run(prompt: str, *, cwd: Path, model: str, effort: str,
        role: Optional[str] = None, project_dir: Optional[Path] = None,
        author: Optional[str] = None, instructions: Optional[str] = None,
        skill_dirs: Sequence[Path] = (), timeout: Optional[float] = None,
        log_path: Optional[Path] = None, worker_project: Optional[str] = None,
        on_process: Optional[Callable] = None, sandbox: str = "workspace-write",
        authoring: bool = False, on_starting: Optional[Callable] = None) -> DshResult:
    provider, provider_patch = provider_config(worker_project)
    validate_model_selection(provider_patch, provider, model, effort)
    cwd = Path(cwd).resolve()
    if role:
        from danus.gateway.roles import ROLE_TOOLS
        config = gateway_row(role=role, cwd=cwd, project_dir=project_dir, author=author)["config"]
        asyncio.run(preflight_mcp(config, set(ROLE_TOOLS[role])))
    run_id = uuid.uuid4().hex
    root = Path(os.environ.get("DANUS_DSH_RUNS_DIR", str(_REPO_ROOT / "runtime" / "dsh-runs"))).resolve()
    run_dir = root / run_id
    run_dir.mkdir(parents=True, mode=0o700)
    for name in ("home", "agents"):
        (run_dir / name).mkdir(mode=0o700)
    provider_copy = run_dir / "provider.patch.json"
    provider_copy.write_text(provider_patch.read_text(encoding="utf-8"), encoding="utf-8")
    validate_model_selection(provider_copy, provider, model, effort)
    patch = run_dir / "site.patch.json"
    patch.write_text(json.dumps(site_patch(model=model, effort=effort, provider=provider, cwd=cwd,
        role=role, project_dir=project_dir, author=author, instructions=instructions,
        skill_dirs=skill_dirs, sandbox=sandbox, authoring=authoring), indent=2), encoding="utf-8")
    binary = resolve_bin()
    cmd = [binary, "--profile", "headless", "--patch", str(provider_copy), "--patch", str(patch), "--json"]
    env = subprocess_env(binary)
    env.update(DSH_HOME=str(run_dir / "home"), DSH_AGENTS_HOME=str(run_dir / "agents"),
               DANUS_DSH_HOME=str(run_dir / "home"), DANUS_DSH_AGENTS_HOME=str(run_dir / "agents"),
               DANUS_DSH_ISOLATED="1")
    events = run_dir / "events.jsonl"
    stderr_path = run_dir / "stderr.log"
    try:
        with events.open("w", encoding="utf-8") as out, stderr_path.open("w", encoding="utf-8") as err:
            if on_starting:
                on_starting()
            proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=out, stderr=err,
                                    cwd=cwd, env=env, text=True, start_new_session=True)
            try:
                if on_process:
                    on_process(proc)
                proc.communicate(prompt, timeout=timeout if timeout and timeout > 0 else None)
                # A buggy/crashed parent can exit leaving its MCP children alive.
                # Quiesce the group even on success before a caller snapshots.
                terminate_process_group(proc)
            except BaseException:
                terminate_process_group(proc)
                raise
            finally:
                if on_process:
                    on_process(None)
    finally:
        if log_path is not None and events.exists():
            Path(log_path).parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(events, log_path)
    session_id, reason, final, error = parse_events(events)
    stderr = stderr_path.read_text(encoding="utf-8", errors="replace")
    rc = proc.returncode
    if rc == 0 and (error or not session_id or reason != "completed" or final is None):
        rc = 1
        stderr += f"\nDSH incomplete run: {error or reason or 'missing completion/session/final'}\n"
    result = DshResult(cmd, rc, stdout=final if final is not None else "", stderr=stderr)
    result.session_id, result.reason, result.run_id, result.run_dir = session_id, reason, run_id, run_dir
    (run_dir / "result.json").write_text(json.dumps({"run_id": run_id, "session_id": session_id,
        "reason": reason, "returncode": rc, "process_returncode": proc.returncode}), encoding="utf-8")
    return result
