# Contributing to Danus

This is the entry point for **changing the repository**. Running a mathematical
swarm is a different task: use the [entry map](AGENTS.md), then read the complete
[main-agent operating contract](agents/contracts/main_agent.md).
An uninitialized checkout does not need a deployment interview to run tests.

## Development

Install [Pixi](https://pixi.sh), then:

```bash
pixi install
pixi run check          # full sanitized offline validation
pixi run check --fast   # fast static guards
pixi run lint           # alias for check --fast
pixi run test           # alias for full sanitized check
pixi run install-hooks # local fast pre-commit gate
# supported Python versions
pixi run -e py310 check
pixi run -e py313 check
```

The check command sanitizes deployment/model credentials from its child environment,
checks harness invariants, runs offline Python tests, and tests the local DSH plugin
with Node's built-in test runner. Do not source `scripts/env.sh` before testing.
Tests use fake DSH executables; no provider key, running verifier, deployment setup,
or paid model call is required. Existing worker skill conformance and verifier
schema fixture checks belong in this same feedback loop; they do not claim
runtime verifier-schema enforcement. See [the engineering map](docs/dev/index.md)
and [diagnostic remedies](docs/dev/invariants.md).

### Local hook and full validation

`pixi run install-hooks` sets this repository's local `core.hooksPath` to
`.githooks`; it does not change global Git configuration. The installer is
idempotent for that path and refuses to replace a different configured hooks path
unless you explicitly choose `--force`. Inspect the existing setup before choosing
that override; never silently discard another workflow's hooks.

The pre-commit hook runs fast checks against the **working tree**, plus source
index containment checks, without model calls or service startup. It does not
construct and validate an isolated snapshot of staged files; review partially
staged changes accordingly. CI checks the committed tree.

Run the full sanitized checks before delivery; a passing fast hook alone is not
full validation. CI runs full checks for supported Python versions. Test/lint
failures should name the violated invariant and link to a remedy, not merely
request that the agent try harder.

## Change discipline

- Preserve the boundaries in [ARCHITECTURE.md](ARCHITECTURE.md). A correct verifier
  verdict remains the only entry into the fact graph; Git recovery does not prove
  mathematics.
- Keep runtime state and credentials out of the source Git repository. Temporary
  tests must not touch real deployments or the user's DSH home.
- Prefer the existing launcher, layout helpers, and checkpoint API over duplicate
  paths or subprocess construction. Update both ends when an interface changes.
- Add regression coverage with a concrete failure message when fixing an invariant.
- Follow [design principles](docs/design.md): keep one canonical home per rule,
  link instead of duplicating manuals, and preserve coding/operating separation.
- Put nontrivial plans and decisions in the [plan index](docs/plans/README.md);
  use its status vocabulary and record deferred problems in
  [technical debt](docs/tech-debt.md).

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
