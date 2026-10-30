# Migrate a deployment to DSH

This branch ports the upstream Codex/v3 runtime to DeepSeek Harness (DSH), while
retaining the main agent's continuous high-level mathematics, rolling speculative
subagents, verifier-gated workers, truth-store formats and HTTP/MCP boundaries.
Upstream research reports and historical achievements remain attributed to their
original system; migrating the harness does not establish a new DSH research run.

## Before changing a deployment

For implementation work, follow [CONTRIBUTING.md](../CONTRIBUTING.md); do not run
initialization, start services, or contact a model as a coding prerequisite.
For an actual deployment migration, stop workers and project-writing main sessions,
retain an independent backup of project data, and preserve the old configuration
securely outside version control. Do not copy old session transcripts into DSH.

## Configure an explicit route

1. Use Pixi for the Python environment (`pixi install`; see
   [getting started](getting-started.md)). Use an operator-approved installed DSH
   binary; this migration does not reconfigure an existing GUI or choose a provider.
2. Copy `config/dsh.env.example` to gitignored `config/dsh.env` and configure
   `DANUS_DSH_BIN`, `DANUS_DSH_PROVIDER`, and the provider configuration. Set
   `DANUS_MAIN_MODEL` and `DANUS_MAIN_EFFORT` explicitly to values supported by that
   route. Names inherited from upstream, including GPT models or `ultra`, are not
   evidence that a provider supports them.
3. Run `bash scripts/setup-dsh.sh` to generate the provider overlay, or supply a
   reviewed absolute `DANUS_DSH_PROVIDER_PATCH` JSON path. Provider identity is
   explicit in either case; secrets are referenced through environment variables.
4. Run `bash scripts/check-dsh.sh` and `bash scripts/doctor.sh`. These are
   nonbillable configuration/diagnostic checks, not live inference tests and not
   proof of provider reachability. Any real model test needs separate authorization.

Legacy `CODEX_*` / `DANUS_CODEX_*` settings and per-project `_WORKER_API_*` routes
are not compatibility aliases. Remove them from the active environment after
translating the intended settings; incompatible configuration fails closed rather
than silently selecting a different backend. Old login/setup flows, config files,
and sandbox/yolo CLI flags are not DSH configuration. There is no Codex fallback.

For project-specific worker routing, use the explicit pair
`DANUS_PROJECT_<TOKEN>_WORKER_DSH_PROVIDER` and
`DANUS_PROJECT_<TOKEN>_WORKER_DSH_PROVIDER_PATCH`; partial pairs fail closed.
See [configuration](configuration.md) for model overrides and locations.

## Start fresh, retain the mathematical state

The repository DSH wrappers use isolated homes and role overlays, not an ambient
GUI session's configuration. `bin/danus-main` defaults to an isolated loopback Web
main (port `8090`, `DANUS_MAIN_PORT`) with native goals/schedules/subagents; do not
start it during coding. The explicit `--headless` one-shot alternative lacks the
schedule service and cannot fulfill timed unattended operation by itself. Main configuration lives under `.dsh/`; the main
launcher wires main-only gateway and authoring tools plus the root-turn snapshot
hook. Worker, verifier, and renderer invocations use separate role configurations.
Fresh worker sessions read assignments, local memory, shared guidance and facts.
Verifiers and renderers remain cold, scoped sessions. Existing fact IDs and
verifier acceptance rules do not change.

A complete run requires successful process exit, completed-turn evidence and final
output; intermediate text is not a successful result. Raw DSH events/session logs
are audit material outside project snapshots, never replay input.

After authorized service startup, explicitly start the desired workers. For main
continuity inspect `get_goal`, create/update the goal as appropriate, and rearm a
disarmed goal only in response to a direct top-level human continuation request.
Replace the old sleep-based strategy loop with DSH schedules: list/reuse first,
UTC `*/30 * * * *` control and `0 */4 * * *` audit, immediate coalesced catch-up on
resume, delete on pause/stop/completion. Timers do not replace the persistent goal.

## Recovery is project-scoped

Use `danus snapshot`, `danus snapshots`, and `danus restore` as documented in
[Git recovery](git-resume.md). One history covers shared stores and workers; live
capture is intentionally best effort without draining workers or a writer barrier.
Restore requires stopped workers and a quiescent main writer, creates a backup,
fences old verifier results, and leaves workers stopped. A malformed or dangling
capture requires explicit `--allow-inconsistent`; it is not automatically repaired.
`DANUS_SNAPSHOT_AUTO=0` disables automatic capture when desired.
