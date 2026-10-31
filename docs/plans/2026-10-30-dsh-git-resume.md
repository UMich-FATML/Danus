# DSH runtime and Git project recovery

Status: Completed
Base: upstream/fork `codex` at `6d92e8d415933ca2ef52fd1a4da73fdfcd418f1c`

## Objective

Replace Codex with DSH for every runtime role and add best-effort project Git
checkpoints with fresh-session recovery. Preserve upstream v3's main reasoning
agent, speculative subagents, verifier-gated workers, HTTP/MCP interfaces, and
existing truth-store formats. Do not push, deploy, or run paid model probes as part of implementation.

## Decisions approved by the operator

- A ReAct loop means the complete loop until the agent produces its final answer,
  not each model/tool iteration. Checkpoint on completed worker rounds and completed
  main-agent turns; a persistent main session may contain many turns.
- One project history includes worker-private files AND shared global memory and
  fact graph. Never use one repository per worker or source-repo submodules.
- Capture is best effort while other agents keep running. Serialize only Git
  checkpoint/restore operations. No worker drain or project-wide snapshot barrier.
  The captured files can represent slightly different moments.
- Restore uses fresh DSH sessions reconstructed from assignments, notes, guidance,
  and facts. It does not restore model conversation context.
- Main-agent assignment changes remain ordinary atomic file replacements. No new
  mid-round notification/polling feature is included.

## Implementation scopes

1. **Runtime adapter:** one DSH launcher with stdin prompts, explicit provider/role
   overlays, isolated homes, structured events, final-text extraction, process
   supervision, and role-gated MCP. Replace worker, verifier, and authoring sites.
2. **Provisioning/main:** DSH scripts/wrappers and configuration, explicit credential
   env references, main goals/subagents/scheduling, offline diagnostics, a local
   root-turn completion plugin, and no Codex dependency.
3. **Snapshots:** project worktree plus external Git metadata; exclusions for
   credentials/generated config/symlinks/raw logs/session stores/control state;
   temporary index, immutable snapshot tags, staged-tree validation/manifest,
   unchanged-content skipping, and visible failure reporting.
4. **Restore:** explicit CLI preview/confirmation, refuse live workers, pre-restore
   backup, bounded path replacement, integrity warnings/override, generation fencing
   against old in-flight verifier results, leave workers stopped and regenerate
   runtime configuration on start.
5. **Integration:** unique run logs, CLI status/documentation, Pixi development
   environment, contributor entry point, checks and CI, and offline integration tests.

## Public interfaces

- `danus snapshot <project> [--message TEXT]`
- `danus snapshots <project> [--json]`
- `danus restore <project> <snapshot> [--worker NAME] [--dry-run] [--yes]`
  with explicit `--allow-inconsistent` for structurally unsafe recovery.
- `DANUS_SNAPSHOT_AUTO=0` disables automatic triggers, not manual snapshots.
- DSH provider/binary settings replace Codex-specific configuration. Existing neutral
  and per-role model/effort settings remain; legacy incompatible settings must fail
  with migration instructions, never silently reroute traffic.
- Existing fact IDs, truth-store schemas, verification HTTP interface and gateway
  role restrictions remain unchanged. Checkpoint manifests have their own version.

## Safety and failure semantics

- A snapshot is approximate persisted state, not a transactionally consistent
  distributed checkpoint or a replayable transcript. In-flight unsaved reasoning is
  not recoverable. Validate captured files and record warnings rather than repairing
  truth stores.
- Keep source checkout history and runtime history separate. External Git metadata
  does not protect against arbitrary same-user shell commands; no security claim is
  based on its location.
- Never follow a worker symlink outside the project. Validate paths before replacement
  or deletion. Do not use unrestricted `git clean` or destroy snapshot history.
- Secrets and raw session logs are excluded. Known secret patterns are checked, but
  arbitrary credentials pasted into prose cannot be perfectly detected.
- Restore requires affected workers stopped and main/project writers quiescent.
  An old verifier response must not mutate the restored generation.
- Checkpoint failure is observable but does not terminate a worker's mathematical
  work. Interrupted capture must not invalidate earlier checkpoints.
- Cold verifiers and renderers stay fresh. Final output alone is not success: check
  process exit and completed turn before consuming artifacts.

## Validation

Use temporary real Git repositories and fake DSH processes. Cover configuration and
role isolation, stdin/final parsing, timeout and descendant cleanup, main-turn vs
step/subagent triggers, duplicate events, concurrent checkpoint requests, exclusions,
unsafe paths/symlinks, corrupt state, restore backup/refusal/fencing, unchanged capture,
and restart-safe log names. Preserve existing gateway/core/paper/report regressions.
Validate actual DSH overlays only with an isolated DSH home and no model calls.
Run tests on Python 3.10/3.13 through Pixi/CI.

## Completion checklist

- [x] DSH adapter and role launchers
- [x] Provisioning and main completion hook
- [x] Project snapshots and restore
- [x] Documentation and offline integration coverage
- [x] Full checks and isolated real-DSH configuration validation
- [x] Final diff reviewed for local commits (no push)

## Validation results

- `pixi run -e py310 check`: 483 Python tests and 10 Node tests passed.
- `pixi run -e py313 check`: 483 Python tests and 10 Node tests passed.
- Static invariants, shell syntax, and `git diff --check` passed. Two inherited
  runpy warnings remain in module-as-main tests; they do not fail the suite.
- Installed DSH 0.2.1-rc.5 composed Web/headless main overlays and all four role
  overlays in isolated temporary homes. Main, worker and verifier MCP tool
  discovery was checked without invoking their tools or any model.
- Real-Git/fake-DSH integration covered automatic round capture, mutation, restore,
  a fresh subsequent session and preservation of earlier logs. Startup cancellation
  distinguishes preflight from uncertain spawn; force-stop regressions passed five
  successive runs. Status breadcrumbs decode DSH's escaped tool-result text.
- No live inference, Web host, deployment initialization, m2 mutation, or push was
  performed. Native Web startup with an actual provider remains a deployment smoke
  test, not a claim established by config composition.
- Implementation commits and task journaling are performed by the lead after
  validation; runtime data and operator credentials remain untracked.

## Decision log

- 2026-10-30: Corrected the design note's separate-git-dir assumption: that command
  leaves a discoverable `.git` pointer. Use explicit Git metadata/worktree arguments.
- 2026-10-30: Operator selected fresh-session restore and best-effort capture; rejected
  the need to pause other workers for globally consistent snapshots.
- 2026-10-30: Installed DSH schedules require the native Web host. The main launcher
  therefore defaults to an isolated loopback Web profile with a role-specific
  preset; explicit headless mode is one-shot and does not promise resident timers.
- 2026-10-30: Main checkpoint intents persist outside project snapshots and retry
  after failure/restart against then-current state. Shutdown has a bounded drain,
  not a guarantee that every capture finishes before process exit.
- 2026-10-30: Review added orphan-child birth identities and uncertain-startup leases
  to restore/start checks. A child surviving a dead worker loop cannot be mistaken
  for a stopped worker merely because the loop PID is gone.
