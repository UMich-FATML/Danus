# Verify: the proof-verification HTTP service

This is an informal LLM judge, not a formal proof checker. The worker gateway
calls `POST /verify` and accepts facts only through the existing verifier gate.
The v3 correctness contract remains: `correct` exactly when both critical errors
and gaps are empty. The service returns the structured verifier payload; the
migration does not reinterpret mathematics or turn snapshots into evidence.

## HTTP contract

- `POST /verify {statement, proof}` returns `{verification_report, verdict,
  repair_hints}`. Reports contain `summary`, `critical_errors`, and `gaps`.
- 400: deterministic vacuity/P1/P3/P5 precheck rejection.
- 422: request-model validation failure.
- 500: invalid launch configuration, missing binary, failed/incomplete DSH turn,
  absent output, invalid JSON, or non-object JSON.
- 504: DSH timeout.
- `GET /health` returns `{status: "ok", pid}` asynchronously, without waiting for
  occupied verification threadpool slots.

## Isolated launch

Each request atomically allocates a unique output directory. That directory,
**not a singleton agent home**, is DSH's cwd and writable workspace. It contains
a copy of `VERIFIER.md` and receives `verification.json` (legacy spelling
`verificationt.json` remains accepted). Existing output is never reused as a new
verification result. Only verifier instruction candidates and explicit verify
skill roots load. The MCP plugin runs `sys.executable -m danus.gateway` with
`DANUS_ROLE=verifier`, the existing read-only role, and `toolCallTimeoutMs=3600000`.

The shared `danus.dsh` adapter supplies absolute provider/site JSON patches,
a complete provider/model/effort row, approval `never`, fresh isolated durable
DSH and agents homes, and stdin task delivery. It parses JSON events and requires
process exit zero, terminal reason `{kind: "completed"}`, a session ID and final
event before reading verification output. Raw logs/session IDs remain available
for audit. Timeout cleanup terminates then kills the complete child process group.

## Configuration

| Variable | Meaning/default |
| --- | --- |
| `DANUS_DSH_BIN` | Explicit executable; otherwise repository wrapper/PATH `dsh` |
| `DANUS_DSH_PROVIDER` | Required explicit provider route |
| `DANUS_DSH_PROVIDER_PATCH` | Required absolute provider-only JSON patch |
| `DANUS_VERIFY_MODEL` / `DANUS_VERIFY_EFFORT` | Override neutral `DANUS_MAIN_MODEL` / `DANUS_MAIN_EFFORT` |
| `DANUS_VERIFY_TIMEOUT_SECONDS` | 0 in library; 900 through module entrypoint |
| `VERIFIER_RESULTS_DIR` | Defaults to `runtime/verifier-runs` |
| `DANUS_DSH_RUNS_DIR` | Defaults to `runtime/dsh-runs` for raw runtime audit data |
| `VERIFY_HOST` / `VERIFY_PORT` | `127.0.0.1` / `8091` |

Model and effort must be explicitly supported by the provider patch; historical
library defaults do not imply provider compatibility. Old runtime environment
names and singleton `VERIFY_AGENT_HOME` are not launch configuration. Existing
precheck toggles and thresholds remain unchanged.

```bash
pixi run python -m danus.verify
pixi run python -m pytest danus/verify/tests
```

Tests are deterministic fake-DSH plumbing tests and do not judge mathematics or
call models. Expert review is still needed for research-level results.
