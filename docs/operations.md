# Danus — Operations Runbook

This runbook is for an authorized operating deployment. Repository coding follows
[CONTRIBUTING.md](../CONTRIBUTING.md) without initialization, live services or
model calls. The main DSH agent normally performs these operations for the
operator; commands also provide a manual recovery path.

## Persistent services

Manage services through `scripts/services.sh`, which detaches process groups and
keeps a PID registry under `runtime/run/`:

```bash
bash scripts/services.sh up verify
bash scripts/services.sh up dashboard <project>
bash scripts/services.sh status
bash scripts/services.sh logs <svc> [-f]
bash scripts/services.sh down <svc>  # or all
```

Verify (`127.0.0.1:8091`) is required before proving. Dashboard
(`127.0.0.1:8099`) is optional and read-only; view it by SSH port-forward, not a
public bind. Shared-host ports may belong to another deployment. A bare health
response is insufficient: service diagnostics match the reported PID to the
local PID registry and distinguish a foreign process. Coordinate any configured
port changes at both ends.

The autostart manifest records service invocations for explicit recovery; it is
not a worker roster or a main-agent scheduler.

## Nonbillable health/configuration checks

```bash
bash scripts/check-dsh.sh
bash scripts/doctor.sh
```

These inspect explicit DSH provider/role configuration, toolchain and MCP wiring;
doctor also diagnoses local service health/ownership and optional renderer
requirements. No paid inference is issued. Passing does not prove the provider
endpoint is reachable or accepts a given model/effort. If a live probe is needed,
obtain separate authorization; never silently fall back to another provider.

## Host recovery versus snapshot restore

```bash
bash scripts/recover.sh
```

Recovery prepares the configured Pixi/DSH runtime, clears stale service state,
and replays registered service startup. It is operating work, not an offline test.
Worker loops are not automatically resumed: inspect state and explicitly run
`bin/danus start <project>` when authorized.

To roll project files back to a checkpoint instead, follow
[Git recovery](git-resume.md). First stop workers and project-writing main sessions;
preview restore, retain the pre-restore backup, and restart separately afterward.
Restore uses a new generation fence and fresh sessions, not transcript replay.

## Worker lifecycle

```bash
bin/danus status <project>
bin/danus start <project>
bin/danus stop <project>          # finish current round, then exit
bin/danus stop <project> --force  # terminate process group; unsaved work can be lost
```

Workers run detached. A full round is a complete DSH ReAct loop through the final
answer, not one tool step. Successful rounds trigger a best-effort snapshot unless
`DANUS_SNAPSHOT_AUTO=0`; failures are visible but do not stop proof work solely
because capture failed. `status` provides liveness and a soft `stuck?` signal;
inspect logs and backend errors rather than assuming that a live PID is progress.

Assignments are ordinary atomic `TASK.md` replacements and can change mid-round.
Workers are instructed to reread at round start, but there is no new automatic
mid-round notification or enforced reread before the next round.

## Main continuity and schedule lifecycle

Use the repository's configured main launcher (`bin/danus-main`), not an ambient
GUI session with unrelated provider settings. Its default isolated Web mode binds
loopback port `8090` (`DANUS_MAIN_PORT`) and supplies native goals, subagents and
schedules. It does not modify a different running GUI. Starting this host is an
explicit operating action, never a coding prerequisite. `.dsh/` holds main wiring, and the
main overlay includes the completed-root-turn hook. It checkpoints initialized
projects only at completed main turns, skips unchanged content, and ignores
steps and speculative-subagent completions.

The main reasons continuously at the high level while speculative subagents
explore and evidence workers prove. `get_goal` / `create_goal` / `update_goal`
manage persistent continuity. DSH schedules are separate reminders:

- List existing schedules first, identify this project's timers, reuse/update
  rather than duplicate them.
- Control: `schedule_create` with
  `cron={"expression":"*/30 * * * *","time_zone":"UTC"}`.
- Audit: `schedule_create` with
  `cron={"expression":"0 */4 * * *","time_zone":"UTC"}`.
- On authorized resume, immediately do one catch-up control beat and any
  overdue/missing audit. Coalesce missed intervals and record timestamps to
  tolerate repeated delivery; do not replay a backlog of ceremonial beats.
- Delete timers on pause, stop, or completion. A reminder cannot authorize goal
  rearming: after session resume/fork, `update_goal(action="resume")` needs a direct
  top-level human continuation request. Durably paused goals require the
  operator-facing goal control; active-disarmed rearming is a different operation.

The runtime must be available to deliver/process reminders; neither a persistent
goal nor a timer guarantees work while the process is down. An optional
`examples/ops/main-agent-tmux.sh` supervises the main launcher; the watchdog example
checks liveness only. Strategic decisions remain the main agent's responsibility.

`bin/danus-main --headless --task-file /absolute/path/to/task.txt` is an explicit
one-shot alternative (stdin also accepted). Headless mode has goals/subagents but
**no native schedule service**, and may exit when its task/goals end. Do not
promise timed unattended control in that mode or assume tmux supplies timers.

## Common issues

| Symptom | Check |
|---|---|
| No facts appearing | Verify service ownership/health; submission errors |
| Failed worker rounds | Explicit provider/model/effort, worker round logs and unique DSH run events; offline check first |
| Snapshot missing | Capture warning/status and `DANUS_SNAPSHOT_AUTO`; unchanged trees intentionally skip |
| Restore refused | Stop workers and other project writers; inspect dry-run and integrity warnings |
| Non-`ok` authoring tool | Returned diagnostic `log_path`; final output alone is not successful completion |
| Blank dashboard | Correct project, service and port-forward |
| Stale main strategy | Goal armed by human request, runtime available, schedules present without duplicates |

Raw DSH sessions/events are audit-only and excluded from snapshots. See
[configuration](configuration.md), [security](security-and-trust.md), and
[CLI/tools](cli-and-tools.md).
