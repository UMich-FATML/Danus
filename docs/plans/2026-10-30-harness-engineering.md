# Adopt harness-engineering practices

Status: Completed
Base: `cb2ca37` on `feat/dsh-git-resume`

## Goal and approval

Make the repository easier for coding agents to navigate and verify, without
changing Danus's mathematical protocols or deployment behavior. The operator
explicitly approved consolidating the root operating manual into the existing
main-agent contract and replacing the root with a short coding/operating map.

## Audit (before changes)

| Probe | Evidence and finding |
| --- | --- |
| Short root map | AGENTS.md is 236 lines, mostly detailed operating procedure: gap |
| Single instructions home | main_agent.md repeats those rules in 143 lines; no CLAUDE.md: gap in duplication, no alternate wrapper to fix |
| Referenced paths | Existing lint checks six fixed documents only, not local links or anchors: gap |
| Design rationale | ARCHITECTURE.md has runtime invariants, but no concise engineering beliefs/decision guide: partial |
| Plans and debt | One completed status-bearing plan and docs/tech-debt.md exist; no plan guide or status check: partial |
| One check command | pixi run check exists; test alias omits harness/Node coverage and environment sanitization: partial |
| Automated gates | CI runs full checks on Python 3.10/3.13; no configured or checked-in local hooks: partial |
| Actionable errors | H001-H004 messages include fixes and documentation anchors: present |
| Mechanical docs checks | No link/map-size/plan-status check: gap |
| Runnable verification | Offline tests, isolated DSH compose/discovery checks, role logs and recovery guides exist: present |
| Toolchain | Pixi environment and supported Python versions documented and locked: present |
| Lessons persisted | Recent migration/resume commits, engineering traps and debt capture observed failures: present |

Highest leverage: consolidate the entry point; enforce documentation and import
boundaries; connect existing skill checks; make local and CI feedback consistent.
Do not add an observability stack, broad formatting churn, or a new type-checking
framework merely for checklist coverage.

## Work and ownership

- **Instructions and rationale:** root map under 150 lines, one authoritative main
  operating contract preserving all requirements, engineering design document, plan
  guide and linked contributor map. Update references rather than duplicate policy.
- **Lints:** Git-aware source containment, exact/relative core import boundaries,
  AST-based legacy runtime import detection, local documentation targets/anchors,
  root map budget, plan statuses. Pair every rule with actionable diagnostics and
  failing-path tests; document parser limits rather than claiming semantic proof.
- **Feedback loop:** preserve canonical sanitized check runner; include existing
  worker conformance and verifier schema tests; add shell/Node syntax checks;
  align Pixi lint/test aliases. Add fast repository-local pre-commit hook and a
  safe installer that refuses to replace another configured hook path.
- **Validation and delivery:** run both supported Python environments, exercise
  failing lint/hook cases offline, review preservation of the operating contract,
  commit locally without push, and log the completed task.

## Acceptance criteria

1. Coding agents see navigation and checks, not a swarm initialization interview.
2. Operating main agents are explicitly directed to read the complete contract;
   scheduling, goal authorization, rolling subagents and truth boundaries survive.
3. Broken local links, oversized root map, missing/invalid plan status and forbidden
   imports produce specific failures with remedies.
4. Existing skill checks run in the same command and CI as engine tests; schema
   tests are not misrepresented as runtime verifier-schema enforcement.
5. Pre-commit checks are fast, do not call a model, and do not overwrite another
   hook configuration. Full tests remain the pre-commit contributor obligation/CI
   gate, not a costly hook on every edit.
6. No live model calls, service starts, deployment configuration changes, push, or
   unrelated style/mathematics changes.

## Decision log

- 2026-10-30: Operator chose consolidation rather than keeping the 236-line root
  contract. Detailed operating instructions move to the existing role contract;
  the root keeps the critical boundaries and required-read pointers.
- 2026-10-30: Reuse existing skill conformance/schema tests and the Pixi runner;
  strengthen guards rather than introduce an independent tooling stack.

## Progress

- [x] Audit and approval
- [x] Instruction consolidation and design map
- [x] Tested lint and feedback-loop improvements
- [x] Supported-version checks and final review

## Validation results

- Root AGENTS.md reduced from 236 to 79 lines; the complete main operating contract
  is consolidated in its existing 248-line home. Review retained the mathematical
  roles, rolling subagents, truth/privacy boundaries, goal authorization, scheduled
  control/audit duties, and operator decisions.
- Seven documented lint rules now cover source containment, core/runtime imports,
  entry maps, bounded local Markdown links/anchors, plan status, and skill metadata.
  Their 64 positive/negative tests passed. Parser limits are explicit rather than
  described as general Python/Markdown/YAML verification.
- `pixi run -e py310 check` and `pixi run -e py313 check` each passed 565 Python
  tests and 10 Node tests, plus worker skill conformance and shell/Node syntax.
  The two inherited runpy warnings remain non-failing.
- `pixi run install-hooks` configured only this repository's core.hooksPath as
  `.githooks`; the actual hook passed. Tests verify idempotence, refusal of an
  existing custom/global hook path without force, failure propagation, missing-Pixi
  guidance, and rejection of symlink hook directories.
- `pixi run test` now uses the same full sanitized runner as `pixi run check`;
  `pixi run lint` aliases the fast path. Existing verifier schema fixtures are
  included, but are not misrepresented as production schema enforcement.
- No live Danus inference, service start, deployment configuration change, broad
  source-formatting rewrite, or push was performed. The pre-commit hook checks the
  working tree and source index containment; CI checks the committed tree.
