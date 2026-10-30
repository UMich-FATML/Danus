# Danus DSH main integration

`bin/danus-main` composes the pinned DSH **0.2.1-rc.5** Web profile with an
explicit provider overlay and a generated main overlay. It launches a separate
loopback host on `DANUS_MAIN_PORT` (default **8090**), never the operator's existing
GUI. Installation, doctor and tests do not start that host. The main Web homes
persist under `runtime/main-dsh/web/{home,agents}`; arbitrary inherited `DSH_*`
GUI settings are stripped. `--headless` is an explicit one-shot alternative with
fresh homes, JSON output and a stdin task (`--task-file` also supported). It does
not provide the native scheduler service.

## Composition

- `main-preset.json` is a complete, explicit Web preset declaration. It has goals,
  native schedule tools and speculative subagents. Instructions stop at this
  repository's `AGENTS.md`; skills use only `.agents/skills`, not user globals.
- `scripts/main_dsh.py` fills absolute local paths and inserts the three main MCP
  wrappers into that preset: `danus`, `write-paper`, and `human-summary`. Headless
  main mounts the same wrappers directly. Worker/verifier/render profiles do not
  use this launcher or the hook.
- DSH replaces a row's **whole config**. Every `agent-default-model` override has
  `provider`, `model`, and `reasoningEffort`; no model CLI flag is used.
- MCP environments explicitly reference required launch values with YAML `!!js`
  expressions; the generated overlay never stores credential values. This is
  essential because DSH strips ambient KEY/TOKEN/SECRET/PASSWORD and `DSH_*` names.
  The initial launcher sources gitignored `config/*.env`; managed isolated children
  do not reload those files or stale `runtime/runtime.env`, preserving resolved values.
- MCP timeout is **3600000ms**. The actual authoring timeout defaults to **3300s**
  and must be below 3600s. Custom provider/model/effort declarations are validated
  before launch; a partial route is an error, never a fallback.

## Completed-turn checkpoints

`main-checkpoints.mjs` uses the installed `ctx.on('session/event', (session,event))`
API. It accepts **only** `turn/end` with `event.data.reason.kind === 'completed'`,
not `step/end`, a tool result, an intermediate assistant message, or an error.
Web events must belong to the `danus-main` preset. Parent lineage, subagent origin
and positive delegation depth are excluded. It deduplicates `(session.id,turn)`.

Accepted requests persist small session/turn intents under
`runtime/checkpoint-requests` and run, serially:

```text
python -m danus.checkpoints request-all --session-id ID --turn-id TURN
```

Python enumerates initialized projects, skips unchanged content and coordinates
with the shared checkpoint implementation. There are no writer barriers. Failed
or interrupted requests remain pending for the next main plugin mount; retrying
can observe **later** live project state, not reconstruct the exact past instant.
Errors go to stderr and never kill mathematical reasoning.

The supervised child timeout defaults to **120s**, configurable with
`DANUS_SNAPSHOT_TIMEOUT_SECONDS`. Teardown drains for 3.5 seconds then cancels an
owned child and leaves pending intents for retry. DSH itself has a five-second
shutdown grace: do not assume that a slow snapshot completes before exit.
`DANUS_SNAPSHOT_AUTO=0` disables both new requests and replay of pending intents.

## Offline checks

```bash
pixi run python -m pytest .dsh/test_ops.py -q
node --test .dsh/main-checkpoints.test.mjs
bash scripts/check-dsh.sh
bash scripts/check-dsh.sh --compose
```

`check-dsh` verifies configuration and initializes/lists the three MCP tool
catalogs without invoking tools or models. `--compose` additionally dumps both
Web/headless compositions privately in temporary isolated homes (the DSH dump
command writes profile scaffolding). It never starts a Web server. These checks
do **not** establish provider authentication, endpoint health, model availability
or correctness of live model output. No `--live` probe is implemented.

## Native goals and schedules

The Web Host owns `schedule`, persistence and its Session controller; the main
preset mounts `dsh-tool-schedule`. Headless cannot mount that service by itself
on this DSH version. Use `get_goal`/`create_goal`/`update_goal` separately from
`schedule_list/create/update/delete`. Wall-clock UTC cron expressions
`*/30 * * * *` and `0 */4 * * *` preserve 30-minute/four-hour boundaries. List
and reuse schedules, catch up once after downtime, and remove reminders when
pausing/stopping. A reminder never authorizes rearming a disarmed goal; durably
paused goals require the operator-facing resume control. See the main operating
contract for the mathematical duties, not a synthetic sleep loop.
