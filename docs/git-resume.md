# Project snapshots and fresh-session recovery

A checkpoint is **best-effort persisted project state**, not a transactionally
consistent distributed checkpoint, a proof certificate, or a conversation backup.
Snapshots do not pause/drain workers and do not acquire a project-wide writer
barrier. Only Git checkpoint/restore operations are serialized. Different files
can reflect different moments, including partially written notes or a dangling
fact dependency. Review captured-state warnings; do not assume notes are complete.

## One history per project

By default the worktree is `runtime/projects/<project>/`; Git metadata is
external at `runtime/.gitstore/<project>.git`. There is no `.git` pointer in the
project, no worker-by-worker repository, and no source-repository submodule. The
outer source checkout ignores default runtime data.

For a custom agents root, `.gitstore` lives alongside the project directories;
if the root directory is named `projects`, it lives one level above that root.
Ignoring `.gitstore` protects only the checkpoint metadata from accidental source
commits. If a custom project root is inside the source checkout, explicitly ignore
its durable contents too, or place it outside the checkout; the default runtime
ignore does not cover arbitrary roots. Back up project history separately for
host-loss protection; a local snapshot is not an off-host backup.

The history includes shared global memory and fact graph alongside worker
assignments and private durable memory. Operational snapshots do not authorize
the mathematical main agent to read worker-private notes. Credentials, generated
role configuration, symlinks, PID/stop flags, raw run logs and DSH session stores
are excluded. DSH session logs remain outside snapshots for audit only.
Secret-pattern checks cannot detect arbitrary credentials pasted into prose;
external Git metadata is organization, not a security boundary against same-user
shell access.

## Capture and inspect

```bash
bin/danus snapshot <project> --message "Before changing the route"
bin/danus snapshots <project>
bin/danus snapshots <project> --json
```

Automatic capture runs after a **complete ReAct loop ending in a final answer**:
a successfully completed worker round, or a completed root main-agent turn. It
is not per model response, tool call, step, or speculative subagent completion.
A persistent main session can contain many completed turns. The main completion
hook may visit all initialized projects and skips unchanged captured content.
`DANUS_SNAPSHOT_AUTO=0` disables automatic triggers, not manual snapshots.
Capture failures are reported without terminating mathematical work; inspect
warnings/errors rather than inferring that a final answer implies a saved snapshot.

## Restore deliberately

1. For full restore, stop all workers for the project and wait until they have
   exited. For `--worker NAME`, stop the affected worker; unaffected workers may
   continue. Graceful stop finishes a round; use force only when you accept
   losing unsaved reasoning.
2. Stop or quiesce the main session and every other project writer, including
   scheduled actions. The CLI cannot prove arbitrary external writers are idle.
3. List snapshots, select an identifier, and preview the intended replacement.

```bash
bin/danus stop <project>
bin/danus status <project>
bin/danus restore <project> <snapshot> --dry-run
bin/danus restore <project> <snapshot> --yes
```

Restore always publishes an immutable pre-restore backup, even when content is
unchanged or inconsistent, and advances a generation fence so old in-flight
verifier results cannot mutate the restored generation. Affected workers are
left **stopped**. Review the restored problem, shared guidance and facts, then
start separately with `bin/danus start <project>` when authorized. New DSH
sessions reconstruct work from assignments and durable stores; there is **no
transcript replay** or recovery of unsaved in-context reasoning. Generated role
configuration is recreated at start.

`--worker NAME` replaces only that worker's durable files; current shared stores
and other workers are untouched. It still uses the single project history and
requires the affected worker and project-writing main activity stopped. Other
workers may remain live, so inspect the dry-run's scope and do not treat the
worker's historical notes as synchronized with current shared facts.

Structurally inconsistent captured state is refused unless the operator explicitly
chooses `--allow-inconsistent`. This override acknowledges risk; it does not
repair malformed records, fill missing predecessors, certify a proof, or relax
path/secret safety checks. Prefer a healthier checkpoint when available. A
snapshot manifest describes the captured tree and warnings, not global atomicity.
Validation checks structural defects, not mathematical completeness: a partially
written proof that remains nonempty, valid UTF-8/Markdown can escape those checks.
Existing fact IDs and stored proof bytes are not rewritten during validation;
there is no attempt to re-prove captured mathematics or reconstruct hashes from
potentially ambiguous Markdown section boundaries.

## Interrupted restore

The sibling `runtime/.gitstore/<project>.state` contains checkpoint/mutation
coordination, generation state and a restore recovery marker. If restore is
interrupted, the marker blocks gateway mutations, worker start and new snapshots.
Do not delete it by hand. With affected writers stopped, use
`bin/danus recover-restore <project> --yes` to roll back from the immutable
pre-restore backup, inspect the result, then start workers separately. This is
recovery of a partial filesystem operation, not transcript resumption.

## Assignments and continuation

`danus assign` atomically replaces mutable `TASK.md`; it can change mid-round.
Workers are instructed to read assignments at each round start. There is no
mid-round notification/injection feature and no enforced reread before the next
round. Avoid promising immediate uptake of a reassignment.

Persistent DSH goals and schedules are separate runtime state, not project
transcripts. After restore, a direct human continuation request is needed to
rearm a disarmed goal. Run one catch-up control beat and any due audit, list/reuse
schedules to avoid duplicates, and never rearm merely because a reminder arrived.
See [the operating guide](operating-guide.md) and [migration](dsh-migration.md).
