# Engineering map

Start at [CONTRIBUTING.md](../../CONTRIBUTING.md) for development or
[AGENTS.md](../../AGENTS.md) for operating a mathematical project.

## Commands

```bash
pixi install
pixi run check          # static invariants, offline Python suite, Node plugin tests
pixi run check --fast   # static invariants only
pixi run -e py310 check
pixi run -e py313 check
```

Checks deliberately remove ambient deployment/model credentials from child processes.
Do not source the deployment environment before tests. A live model smoke test is
separate, opt-in work and is not a prerequisite for coding.

## Fact locations

| Fact | Home |
| --- | --- |
| Runtime architecture and pinned interfaces | [ARCHITECTURE.md](../../ARCHITECTURE.md) |
| Enforced development invariants | [invariants.md](invariants.md) |
| Provider/runtime settings | [configuration.md](../configuration.md) |
| Codex-to-DSH transition | [dsh-migration.md](../dsh-migration.md) |
| Git snapshot contents and restore semantics | [git-resume.md](../git-resume.md) |
| Main/worker/verifier behavior | [contracts](../../agents/contracts/README.md) |
| Decisions and progress | [implementation plan](../plans/2026-10-30-dsh-git-resume.md) |
| Deferred issues | [tech-debt.md](../tech-debt.md) |

## Common traps

- DSH patches replace a row's entire configuration, not individual nested keys.
- The headless parser does not accept Codex flags. Prompts belong on stdin; extract
  final output separately from NDJSON telemetry.
- A completed final event is not enough: check process exit and turn completion.
- MCP startup/config validation is not proof that a provider works. Offline checks
  must not be described as live inference tests.
- A worker cwd inside this checkout does not by itself isolate instruction/skill
  discovery. Role overlays must explicitly control both, including global homes.
- Keep the gateway on Danus's interpreter; a bare system Python can load a different
  install or fail importing the package.
- Real DSH `--dump-config` prepares profile files. Use an isolated test home.
- Git snapshots do not suspend writers and cannot guarantee a globally consistent
  instant. Restore is a separate, explicit operation with stopped writers.
