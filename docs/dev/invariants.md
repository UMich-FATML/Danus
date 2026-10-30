# Enforced development invariants

Run `pixi run check` locally and in CI. The static guard lives in
[scripts/harness_lint.py](../../scripts/harness_lint.py); runtime guarantees belong
in unit/integration tests, not text matching. Change a rule, its implementation,
and a failing-path test together.

## H001: Source containment

Runtime projects, external snapshot Git stores, Pixi environments, and credential
files must never enter the source Git index. Keep their roots ignored and remove
accidentally staged files from the index without deleting live data. Templates
ending in `.example` are source, not credentials. Git snapshots enforce their own
stricter content policy, separately from the source checkout.

## H002: Core boundary

The core truth/memory package uses Python's standard library only. Provider,
process, gateway, and network integrations belong outside it. This preserves
small deterministic tests and prevents the verifier interface from leaking into
the data model.

## H003: Entry points

The contributor map, runtime migration guide, recovery guide, and debt list must
exist. Coding must not trigger an operator initialization interview or paid model
call. Do not confuse operating instructions with contributor instructions.

## H004: Single runtime

Workers, verifiers, and authoring must use the shared DSH adapter; there is no
Codex execution fallback. Tests cover actual DSH configuration, protocol parsing,
role discovery isolation and failure behavior. A stale provider setting must fail
explicitly instead of silently selecting another account.

## Behavioral invariants (tested)

- Snapshot triggers mean completed full main turns / worker rounds, never each
  tool result or speculative subagent completion.
- Snapshot creation serializes Git operations only and does not stop writers.
- Restore requires stopped writers, preserves a backup, and fences old verifier
  responses. Snapshot validation does not certify the mathematics.
- DSH output is successful only with successful process and turn completion;
  final-text extraction must not mix diagnostic events into published artifacts.
- Role-gated tools remain enforced by the gateway; main cannot submit facts.
