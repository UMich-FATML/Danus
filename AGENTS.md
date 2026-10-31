# Danus — agent entry map

Choose whether you are **changing the repository** or **operating a mathematical
project** before taking action. This file is the map, not the operating manual.

## Coding, tests, documentation, or migration

Start with [CONTRIBUTING.md](CONTRIBUTING.md), then use the
[engineering map](docs/dev/index.md) for the relevant subsystem and checks.
Do **not** initialize a deployment, fill the operator template, start live
services/workers, or make model calls merely because this checkout is
uninitialized. Software tests are not mathematical experimentation.

Use Pixi for Python setup and commands. Do not source the deployment environment
before testing; the check runner isolates and sanitizes its child environment.

```bash
pixi install
pixi run check          # full offline validation
pixi run check --fast   # fast static guards
pixi run lint           # alias for fast guards
pixi run test           # alias for full sanitized validation
pixi run install-hooks  # repository-local fast pre-commit gate
```

Hook installation is local to this repository, not global, and refuses to replace
another configured hooks path without explicit force. Full checks remain the
contributor/CI gate; the fast hook is not a substitute for the test suite.
See [contributor instructions](CONTRIBUTING.md) for supported Python environments.

## Operating a mathematical project

**Before acting, the operating main agent must read the complete
[main-agent operating contract](agents/contracts/main_agent.md), in full.**
Also read [OPERATOR.md](OPERATOR.md), [ARCHITECTURE.md](ARCHITECTURE.md), and the
relevant project's `PROBLEM.md`. Do not substitute this map or a remembered
summary for the contract.

That contract owns the full v3 operating behavior: continuous high-level
mathematics, rolling speculative DSH subagents versus evidentiary Danus workers,
DSH goals and human-authorized rearming, separate schedules and catch-up reviews,
the 30-minute control beat, four-hour audit, and operator decisions.
Workers and verifiers follow their own [role contracts](agents/contracts/README.md).

## Critical boundaries

- The verifier is the sole correctness gate; only verifier-accepted facts in the
  fact graph are truth. The main has no `fact_submit`; speculation is not a fact.
- Do not hand-edit shared truth/memory stores; use the sanctioned MCP/CLI paths.
  The operating main must not read or modify worker-local memory.
- **All mathematical work is text-only.** No executable experimentation, numerical
  or symbolic computation, brute force, solvers, or proof assistants—even tiny
  checks. Repeat this boundary in every mathematical subagent assignment.
- Never finalize, revoke facts, push, or publish without the required operator
  decision. Keep credentials and runtime data out of source history.
- Use explicit provider/role configuration, not ambient GUI settings or silent
  runtime fallback. Coding does not authorize live inference or deployment.

## Where each kind of knowledge lives

| Need | Canonical home |
| --- | --- |
| Development setup, commands, hooks, change discipline | [CONTRIBUTING.md](CONTRIBUTING.md) |
| Engineering navigation and common traps | [Engineering map](docs/dev/index.md) |
| Design rationale and documentation ownership | [Design principles](docs/design.md) |
| Module layout, runtime boundaries, pinned interfaces | [ARCHITECTURE.md](ARCHITECTURE.md) |
| Complete main-agent operating procedure | [Main-agent contract](agents/contracts/main_agent.md) |
| Worker/verifier behavior and skill boundaries | [Role contracts](agents/contracts/README.md) |
| Operator preferences, not credentials | [OPERATOR.md](OPERATOR.md) |
| Enforced guards and diagnostic remedies | [Development invariants](docs/dev/invariants.md) |
| Active/completed decisions and plan status guidance | [Plan index](docs/plans/README.md) |
| Accepted limitations and follow-up work | [Technical debt](docs/tech-debt.md) |
| Deployment settings and migration | [Configuration](docs/configuration.md), [DSH migration](docs/dsh-migration.md) |
| Services, CLI, and project recovery | [Operations](docs/operations.md), [CLI/tools](docs/cli-and-tools.md), [Git recovery](docs/git-resume.md) |

Change a rule at its canonical home, then update its links and guards rather than
copying a second manual here. Preserve the mathematical contracts when changing
harness mechanics; keep observed failures and their fixes legible in tests and
[plans](docs/plans/README.md).
