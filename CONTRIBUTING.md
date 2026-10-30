# Contributing to Danus

This is the entry point for **changing the repository**. Running a mathematical
swarm is a different task: its operating contract is [AGENTS.md](AGENTS.md).
An uninitialized checkout does not need a deployment interview to run tests.

## Development

Install [Pixi](https://pixi.sh), then:

```bash
pixi install
pixi run check
# supported Python versions
pixi run -e py310 check
pixi run -e py313 check
```

The check command sanitizes deployment/model credentials from its child environment,
checks harness invariants, runs offline Python tests, and tests the local DSH plugin
with Node's built-in test runner. Do not source `scripts/env.sh` before testing.
Tests use fake DSH executables; no provider key, running verifier, deployment setup,
or paid model call is required. See [the engineering map](docs/dev/index.md).

## Change discipline

- Preserve the boundaries in [ARCHITECTURE.md](ARCHITECTURE.md). A correct verifier
  verdict remains the only entry into the fact graph; Git recovery does not prove
  mathematics.
- Keep runtime state and credentials out of the source Git repository. Temporary
  tests must not touch real deployments or the user's DSH home.
- Prefer the existing launcher, layout helpers, and checkpoint API over duplicate
  paths or subprocess construction. Update both ends when an interface changes.
- Add regression coverage with a concrete failure message when fixing an invariant.
- Put nontrivial plans and decisions under `docs/plans/`; record deferred problems
  in [technical debt](docs/tech-debt.md).

## Branches and commits

This fork starts from upstream's `codex` v3 line; feature branches carry engine
changes. Deployment branches may carry operator-specific configuration, but the
source baseline keeps [OPERATOR.md](OPERATOR.md) blank. Never import old Kimi branch
architecture merely because it exists in local Git history.

Commit only your changed paths. Subjects are at most 50 characters, capitalized,
imperative, and have no trailing period. Bodies are at most 280 characters and
explain the before/after/why. Add `DSH-session: <DSH_SESSION_ID>` as a trailer.
Never push unless the operator explicitly asks. Log completed implementation work
using the user's `log-task` skill; do not log conversations without being asked.
