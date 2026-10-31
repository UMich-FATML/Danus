# Engineering design principles

This document explains why the repository is organized this way. It does not
replace the [architecture and interface map](../ARCHITECTURE.md), the
[main operating contract](../agents/contracts/main_agent.md), or
[enforced development invariants](dev/invariants.md).

## One fact, one home

The root [agent entry map](../AGENTS.md) selects coding versus operation and
points to the information needed next. Detailed mathematical operating rules live
in the existing main-agent contract, not a second root manual. Workers and
verifiers retain their distinct role contracts: distinct roles are not duplicate
versions of the main role.

Use the [engineering map](dev/index.md) to find each canonical document. Explain a
behavior once, link to it elsewhere, and keep summaries clearly subordinate to
that source. This reduces stale copies and avoids crowding every coding task with
a full operating procedure. Small repeated critical boundaries in the entry map
are deliberate reminders, not independent specifications.

Plans record changing decisions and validation evidence; durable current rules
belong in contracts, architecture, or invariant documentation. A completed plan or
old commit is historical context, not an override of the current contract. Keep
[plan statuses](plans/README.md) current and record deferred limitations in
[technical debt](tech-debt.md).

## Turn failures into useful feedback

A recurring agent mistake is a reason to improve the environment, not just ask
for more care. A failed guard should identify the location, explain the violated
invariant, and point to its remedy. Pair new guards with both passing and failing
regressions; keep guard documentation and implementation aligned.

Use the single sanitized Pixi check runner for local checks and CI. A fast,
repository-local pre-commit hook catches cheap structural failures; full offline
tests remain necessary before delivery. The aliases and installation procedure
live in [CONTRIBUTING.md](../CONTRIBUTING.md). An existing custom hook path is an
operator choice, so installation must not silently replace it or change global
Git configuration.

Prefer existing tests and small inspectable checks over an independent framework.
Validate links, root-map size, plan status, and architectural import boundaries
mechanically where feasible. State parser limits: a passing documentation lint
is not a proof that prose is correct, and a verifier fixture test is not runtime
schema enforcement.

## Keep mathematical authority separate from coordination

The main agent reasons continuously at the high level and coordinates speculative
subagents and evidentiary workers. Only the verifier-gated fact graph is truth;
shared memory and speculative reports remain awareness. The gateway enforces the
sanctioned tool surface so the main cannot submit facts through its MCP role.
Harness changes must preserve these roles rather than redesign proof methodology.

Tool gating is not an operating-system security boundary. A same-user shell with
filesystem access can bypass sanctioned interfaces; trusted contracts and host
isolation still matter. Likewise, an LLM verifier verdict is not a formal proof
certificate. See [security and trust](security-and-trust.md) and the explicitly
recorded [verifier limitation](tech-debt.md#verifier-report-consistency).

## Make provider and role isolation explicit

A runtime route must come from explicit provider/model/effort configuration, not
an ambient GUI, old login state, or silent fallback. Fresh role configurations
control instructions, skills and tool access as well as model routing. Keep the
shared adapter as the launch seam so timeout, completion and final-output handling
cannot diverge across workers, verifiers and renderers.

Use environment references for credentials; do not copy secret values into
committed configuration or project checkpoints. Offline configuration composition,
MCP discovery and fake-runtime tests validate mechanics without live inference.
They cannot establish remote model support, search credentials, or deployment
health. The [configuration reference](configuration.md) owns those dependencies.

## Best-effort checkpoints are an explicit tradeoff

The operator chose live capture without draining workers or a project-wide writer
barrier. This keeps proof work moving, but captured files can represent different
instants. One history includes shared stores and worker durable state; independent
worker repositories would hide those dependencies. External Git metadata keeps
runtime history separate from the source checkout without creating submodules or
worktree pointers; it does not provide a same-user security boundary.

Capture validates recorded bytes and reports defects rather than repairing or
re-proving mathematics. Restore is stricter: stop affected workers and main
writers, retain a backup, fence old verifier results, and restart separately in
fresh sessions. Persisted notes and facts are recovery inputs; raw conversations
are audit material, not replayable state. These choices and their limits are
specified in [Git recovery](git-resume.md), not strengthened by optimistic wording
in an overview.

## Preserve the coding/operating boundary

Developing Danus must work in an uninitialized checkout with a blank operator
profile, fake runtime processes and no paid calls. Operating a real project is a
different authorization: it can start services, consume credentials and spend
budget. Persistent goals, reminder schedules and snapshots also solve different
problems; none grants permission to resume a paused project or publish a result.
Keep the complete operating behavior in the
[main-agent contract](../agents/contracts/main_agent.md).
