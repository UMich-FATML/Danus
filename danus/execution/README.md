# Execution: worker rounds, layout, and scaffolding

Each worker round is one fresh DSH headless session that continues solving from
persisted project state, not from an old conversation. The standing worker
contract and adaptive proving skills are unchanged; facts enter the shared truth
store only through the worker gateway's verifier-gated `fact_submit`.

## Layout

Projects live under `DANUS_AGENTS_ROOT` (default `runtime/projects`). Each has
`project.json`, shared global memory and fact graph, and `workers/<worker>/`.
The worker directory is its writable workspace and contains `WORKER.md` pointing
to the canonical worker contract, `TASK.md`, `.role`, private local memory,
`.status.json`, PID/stop controls, and logs. The authoritative worker roster is
`project.json`; leftover excluded log directories after restore are not workers.

`scaffold.write_dsh_config` writes an inspectable `.dsh/gateway.patch.json` with
`sys.executable -m danus.gateway`, role/project/author environment, and a one-hour
MCP timeout. Actual launches create fresh full provider/site overlays through
`danus.dsh`. Role-specific instruction candidates and explicit custom skill roots
prevent main-agent/user instruction or skill discovery.

## Launch and completion

The supported command is `dsh --profile headless --patch ABS_PROVIDER --patch
ABS_SITE --json`, with the task on stdin. Provider, model and reasoning effort
belong only in the complete `agent-default-model` overlay row. Required explicit
provider JSON and model/effort declarations fail closed; there is no legacy
runtime or Azure configuration fallback.

`DANUS_WORKER_MODEL` selects the worker default; persisted `.role` preserves each
worker's model and effort. Project-only routing uses both
`DANUS_PROJECT_<TOKEN>_WORKER_DSH_PROVIDER` and
`DANUS_PROJECT_<TOKEN>_WORKER_DSH_PROVIDER_PATCH` (absolute JSON path).

Every run has unique durable homes and raw events under `DANUS_DSH_RUNS_DIR`
(default `runtime/dsh-runs/<uuid>`). Worker logs have unique invocation IDs even
after restarts; status records the DSH session/run IDs. Only process exit zero,
terminal reason `completed`, a session ID, and a lossless final event count as
success. Intermediate projections can be truncated and are not artifacts.

The detached outer loop stops at `.stop`, the project deadline, max rounds, or
the consecutive-failure limit. Defaults: `DANUS_ROUND_BEAT=5`,
`DANUS_ROUND_HARD_TIMEOUT=14400`, `DANUS_MAX_ROUNDS=0` (unlimited), and
`DANUS_MAX_CONSEC_FAILURES=5`. Timeouts terminate then kill the DSH process group,
including MCP children. SIGTERM also performs this cleanup.

After a successful **full round**, with process/log handles closed, the loop
requests a best-effort Git snapshot. Snapshot failure warns and never fails the
worker; `DANUS_SNAPSHOT_AUTO=0` disables it. No per-tool snapshot or writer barrier
is introduced. Restored projects stay stopped and start fresh sessions.

## Offline tests

```bash
pixi run python -m pytest danus/tests danus/execution/tests
```

Tests use fake DSH protocol executables; no model calls or API spend.
