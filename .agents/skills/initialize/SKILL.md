---
name: initialize
description: First-run deployment setup for Danus on DSH. Use when the operator asks to initialize, onboard, or reconfigure an operating deployment; in an operating session also check for a missing runtime/.danus-initialized or blank OPERATOR.md. Never auto-initialize during repository coding or migration work. Confirm the explicit provider/model/effort configuration and missing operator preferences, then provision authorized services and record readiness without live model probes.
---

# initialize — first-run deployment interview

## 0. Decide whether initialization is appropriate

Repository coding, tests, documentation and migration implementation follow
`CONTRIBUTING.md`, not this operational interview. A missing sentinel or blank
`OPERATOR.md` is **not** permission to initialize during coding. Leave the blank
template intact, start no live services, choose no new provider, and make no
model calls merely to develop or validate software.

For an authorized operating deployment, explain briefly: the main DSH agent
reasons continuously at the high level, speculative subagents explore, workers
produce candidate proofs, and the verifier alone admits facts. Preferences go in
`OPERATOR.md`; credentials belong only in gitignored `config/*.env`.

## 1. Read existing state

Read `OPERATOR.md`, `docs/configuration.md`, and the applicable env templates.
Inspect the current branch and use `scripts/check-dsh.sh` / `scripts/doctor.sh`
for nonbillable diagnostics. Do not print secret values. Do not overwrite an
existing working provider route or confuse offline checks with live reachability.

## 2. Ask only for missing decisions

Use DSH's question tool or concise conversation questions. Confirm existing
choices before asking for replacements:

- How to address the operator, preferred reply language, timezone and notifications.
- Deployment branch, spending ceiling and worker roster. Do not change branches
  during an unrelated implementation task.
- The explicitly authorized DSH binary/provider overlay and model/effort for each
  role. Do not assume an upstream GPT name or `ultra` is supported, and do not
  silently route to another provider. If configuration is already supplied, reuse
  it rather than presenting a new provider choice.
- Optionally whether automatic best-effort snapshots should remain enabled
  (`DANUS_SNAPSHOT_AUTO=0` disables automatic triggers). Explain that snapshots
  capture persisted state, not transcripts or atomic cross-worker consistency.

Never request that credentials be pasted into the conversation. Ask the operator
to populate the gitignored environment file or approved external secret source.

## 3. Provision the authorized deployment

- Use Pixi for Python setup (`pixi install`; `scripts/bootstrap.sh` uses the
  repository manifest). Do not create a separate venv or use old login tooling.
- Copy missing env templates without replacing existing secrets; set explicit
  `DANUS_DSH_PROVIDER`, provider configuration, `DANUS_MAIN_MODEL` and
  `DANUS_MAIN_EFFORT`. Run `scripts/setup-dsh.sh` or use an approved absolute
  `DANUS_DSH_PROVIDER_PATCH`. See `docs/dsh-migration.md` for legacy-setting removal.
- Use `bin/dsh` / `bin/danus-main` and the `.dsh/` main configuration, not an
  inherited GUI's provider settings. Main MCP and the root completed-turn hook
  must be configured by the main launcher.
- Fill the operator profile in place without duplicates or secrets. Leave project
  mathematics under the project, not in the operator profile.
- Run offline `scripts/check-dsh.sh` and `scripts/doctor.sh`; fix reported errors.
  They do not prove a model endpoint works. No live inference test without a
  separate explicit request.
- Only with operating authorization, run `scripts/services.sh up verify` and
  inspect service health/ownership. The required verifier must actually be up
  before claiming readiness. Optional dashboard/rendering dependencies are not
  mandatory for proving.
- Write `runtime/.danus-initialized` only once the required stack has been checked.
  Do not mark completion on a failed check or automatically commit/push anything.

## 4. Hand off to the mathematical operating loop

Summarize the confirmed route, checked service state and any remaining limitations;
ask for the problem or return to the original operating request. For an active
problem follow root `AGENTS.md`: inspect/create/update the persistent goal, keep
main high-level reasoning and speculative subagents active, and use the separate
DSH schedules for 30-minute control and four-hour audit. List/reuse schedules,
catch up immediately on authorized resume, and delete them on pause/completion.
A scheduled wake-up cannot supply the top-level human request needed to rearm a
disarmed goal.

Read `docs/git-resume.md` for checkpoint/restore boundaries. Fresh sessions resume
from durable project state, not conversation replay. Mention that operator paper
exemplars can later improve the writing style; do not perform rendering or
publication during setup without a request.

## Rules

- Ask rather than guess missing settings; preserve already approved choices.
- State only checked outcomes, and distinguish offline validation from live health.
- Keep secrets out of generated config values, version control and transcripts.
- Invoke repository scripts from the repository root or by absolute path.
- Initialization is deployment work, not a side effect of coding.
