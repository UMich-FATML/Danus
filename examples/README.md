# examples/ — runnable examples (ops + a toy project)

> **Example, not core.** Everything under `examples/` is a copy-pasteable
> demonstration of how to run Danus unattended and what a project looks like on
> disk. **Nothing in the engine depends on `examples/`** — these scripts only wrap
> the real interfaces (`bin/danus` and the `python -m danus.*`
> entry points). Each script also carries an "EXAMPLE, NOT CORE" banner so it is
> never mistaken for the control path.

For unattended operation, keep the **DSH main runtime resident**
(`ops/main-agent-tmux.sh` is an optional tmux example). The **strategic judgment** —
synthesize progress, record `master_guidance`, and dispatch workers — lives in
that main agent and its skills (`elaboration`), *not* in shell.
The `watchdog.sh` loop here is only the unattended **liveness** scaffolding
around that agent.

All scripts resolve paths through `scripts/env.sh` (no hardcoded absolute paths,
no project names baked in) and take the project as a parameter. Operator-facing
prose follows `OPERATOR.md`; the scripts themselves only emit English mechanics.

## `ops/` — unattended-operation scripts

### `main-agent-tmux.sh`
Starts the repository's configured DSH main launcher in tmux. The `.dsh/`
configuration and main overlay wire role-gated MCP, `.agents/skills/` and the
completed-root-turn checkpoint hook; the tmux example is only supervision.
Use persistent goals and separate DSH schedules as described in the
[main-agent operating contract](../agents/contracts/main_agent.md):
list/reuse timers, catch up once on authorized resume, and delete on pause or
completion. Timers do not authorize rearming a disarmed goal.

```bash
bash examples/ops/main-agent-tmux.sh
tmux attach -t danus-main        # watch / interact; DANUS_MAIN_TMUX overrides the name
```

The main launcher's default isolated Web host provides native schedule tools
while running (loopback port `8090`, configurable through `DANUS_MAIN_PORT`).
Its explicit `--headless` alternative is one-shot and has no schedule service;
tmux does not add timers or keep reminders running after process exit. Starting
the main host requires operating authorization and does not modify another GUI.

Requires `tmux` and the repository's explicitly configured DSH binary/provider
route. The main agent is the strategic control path; no shell loop substitutes
for its mathematical reasoning.

### `watchdog.sh <project>`
Liveness / stall alerting. Each beat it probes the verify service at
`DANUS_VERIFY_URL` and reads `danus status <project> --json`, alarming if the
verify endpoint is down or any worker's label is `stuck?` / `dead` / `error`.

```bash
bash examples/ops/watchdog.sh <project>
```

- `DANUS_WATCHDOG_BEAT` — seconds between checks (default `300`).
- `DANUS_VERIFY_URL` — health endpoint (from `env.sh`; not hardcoded).

**The `DANUS_NOTIFY` contract.** Alarms fire `${DANUS_NOTIFY:-:}`, which is any
command the operator sets; the message is passed both as an argument and on
stdin. The default `:` is a silent no-op, so the watchdog is quiet until you
wire a hook. Examples:

```bash
# append to a log
DANUS_NOTIFY='tee -a runtime/logs/watchdog-alarms.log' bash examples/ops/watchdog.sh <project>
# POST the message body to a webhook
DANUS_NOTIFY='curl -fsS -d @- https://example.invalid/hook' bash examples/ops/watchdog.sh <project>
```

There is no Telegram / vendor binding. Set `DANUS_NOTIFY` in
`config/danus.env` to make it the default for a deployment.

### Keeping the loops running
These loops run in the foreground. To make them persist beyond your shell, wrap
them the same way you would anything else — a `tmux` window or `setsid`. Do
**not** register them in the services pidfile/autostart manifest: that registry
belongs to `scripts/services.sh` (which owns `verify` and the dashboard);
`examples/` never touches it.

## `project/` — a toy project on disk
`project/PROBLEM.md` plus a 2-fact `project/fact_graph/` show the shape of a
Danus project — a verbatim problem statement and a content-addressed fact DAG
written to `danus.core`'s real schema. It is **illustrative sample data**, not a
verified run; see `project/fact_graph/README.md`. For a paper-pipeline example,
see the write-paper skill's own toy project under
`agents/skills/write-paper/examples/paper/`.
