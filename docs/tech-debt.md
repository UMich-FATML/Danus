# Accepted limitations and follow-up work

These are explicit limits, not claims that the current migration solves them.

## Verifier report consistency

Inherited upstream behavior accepts a fact when the returned dictionary's
`verdict` is `correct`; consistency with nested `critical_errors` and `gaps` is
primarily a verifier contract. The DSH migration preserves the interface and
rejects unsuccessful process/turn/artifact production, but a comprehensive
versioned verifier-report schema and cross-field validation are separate work.

## Best-effort snapshots

The operator chose live snapshots without pausing writers. Files in a checkpoint
can represent different instants and may contain malformed/inconsistent state.
Capture warnings and explicit restore overrides make this visible; there is no
claim of transactionally consistent distributed recovery. Unpersisted reasoning
and raw DSH conversations are not recovered.

## Direct writers and restore

Gateway mutations and worker start operations participate in restore coordination,
but arbitrary shell/file writes by the same user cannot be reliably fenced without
an operating-system isolation boundary. Stop project-writing main activity before
restore. External Git metadata and clean DSH homes are organization/isolation
mechanisms, not protection against malicious same-user processes.

## Provider and model semantics

A structurally valid DSH provider overlay and successful offline MCP handshake do
not establish that a remote model exists or supports a requested effort. Live
provider probes require explicit operator authorization and credentials; fake-CLI
regressions are not a substitute for a deployment smoke test.
