# Implementation plans

Plans record the objective, decisions, ownership, progress and validation of
nontrivial repository work. They are versioned working records, not a second copy
of the current operating contract. Use [design principles](../design.md) for the
rationale, [development invariants](../dev/invariants.md) for enforced rules, and
[technical debt](../tech-debt.md) for accepted limitations and deferred work.

## Plan index

| Plan | Scope |
| --- | --- |
| [Harness-engineering adoption](2026-10-30-harness-engineering.md) | Consolidate agent instructions and add documentation/feedback guards |
| [DSH runtime and Git project recovery](2026-10-30-dsh-git-resume.md) | Explicit DSH roles, completed-turn checkpoints and fresh-session recovery |

Read each plan's `Status:` field for its current state rather than duplicating
status in this index. Add new plans here when they are created; keep completed
plans linked for their decisions and validation evidence.

## Required status

Each plan other than this index must have one plain status line near the top:

```
Status: Proposed
```

The accepted values are:

- **Proposed** — a scoped proposal; implementation is not yet authorized or begun.
- **In progress** — approved work is underway; keep remaining work and validation
  visible rather than implying completion from partial success.
- **Completed** — the objective and acceptance criteria are met, with actual
  validation results and any remaining limitations recorded.
- **Blocked** — a concrete external prerequisite prevents progress; name it,
  identify the next action or owner, and preserve unfinished acceptance criteria.
  Difficulty or an ordinary failing test is not itself an external blocker.

Use these exact spellings so automated checks can catch missing or invalid
status. Plan status is documentation; it does not create, resume, or complete a
DSH persistent goal, and it does not authorize deployment actions.

## What a plan should contain

1. Objective, scope, base revision when useful, and approval context.
2. Evidence behind the change: observed failures or audit gaps, not just intent.
3. Work breakdown, ownership, dependencies and boundaries that must not regress.
4. Acceptance criteria and a validation strategy, distinguishing offline checks
   from any separately authorized live operation.
5. Progress and a short decision log, including meaningful changes of direction.
6. At completion, commands actually run, outcomes, limitations and follow-ups.

Keep the plan focused. When a decision becomes a standing rule, update its
canonical contract or documentation and link to it; do not make future agents
search old plans for required behavior. Never record credentials or sensitive
runtime data. Start development through [CONTRIBUTING.md](../../CONTRIBUTING.md).
