# danus/orchestration — the `danus` CLI verbs

The operator's lifecycle commands. **Verbs/UX only** — the on-disk layout, the
round loop, and scaffolding live in `danus/execution`; this module parses arguments
and calls into it. Run via `bin/danus`.

```
danus/orchestration/
  cli.py        the verbs: list / new / assign / finalize / start / status / stop
  __main__.py   `python -m danus.orchestration` (what bin/danus execs)
  tests/{test_cli_verbs.py, test_orchestration.py}
```

## Verbs

| verb | does |
|---|---|
| `list [--json]` | projects + live worker counts + model |
| `new <p> [--roles max:3] [--model M]` | → `execution.scaffold.do_new` |
| `assign <p>/<w> (--task/--file/--stdin)` | overwrite that worker's `TASK.md` |
| `finalize <p> [<fact_id>…]` | record target(s) in `TARGET.md` (no id ⇒ suggest terminal facts); records only, does not stop workers |
| `start <p>[/<w>]` | → `execution.scaffold.spawn_loop` (idempotent via `.pid.lock`) |
| `status <p>[/<w>] [--json]` | per-worker liveness + round + `stuck?` soft signal |
| `stop <p>[/<w>] [--force]` | graceful `.stop` / `--force` `killpg` |
| `snapshot <p> [--message TEXT]` | best-effort live project checkpoint; skips unchanged content |
| `snapshots <p> [--json]` | list immutable `snap-N` checkpoints and integrity warnings |
| `restore <p> <snap-N> [--worker NAME] [--dry-run] [--yes] [--allow-inconsistent]` | preview/restore stopped durable state, with immutable before-restore backup |
| `recover-restore <p> --yes` | roll back an interrupted restore from its backup; leave workers stopped |

## Notes

- Liveness is **zombie-aware** (`os.kill(pid,0)` + a `/proc/<pid>/stat` Z-state
  check), so `status`/`list` don't lie and `start` can restart a crashed worker.
- No `assign`-all, no pause/resume — restart = `stop` then `start`.
- `new` creates empty shared-store directories. Restore replaces captured durable
  files, but never verifies, repairs, or invents truth.
- Restore requires affected workers and all project-writing main activity stopped.
  `--yes` confirms that precondition; it does not stop processes for you. Worker-only
  restore keeps shared stores/current other workers unchanged and warns about
  possibly stale fact references. Malformed or dangling captured state needs an
  explicit `--allow-inconsistent` override.
- Checkpoint Git metadata lives outside the worktree at
  `runtime/.gitstore/<project>.git`. Snapshots never acquire a writer barrier.
  Restore uses a separate generation fence against stale verifier results and
  blocks gateway mutations until an interrupted restore is recovered.
- A dead worker loop does not imply its detached DSH child stopped. A durable
  child lease blocks restore/restart while that child or its process group remains
  active. `stop --force` cleans an identifiable child group; unresolved startup
  leases or leaderless groups require operator inspection rather than unsafe
  signaling of possibly reused process IDs.

## Tests

`pixi run python -m pytest danus/orchestration/ danus/checkpoint_tests/`
(offline; fake DSH, stub projects, and real temporary Git repositories).
