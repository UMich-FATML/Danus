# Danus — Architecture

Danus inherits the Rethlas proof methodology and the upstream Codex/v3 design;
this branch runs the roles on DSH as a multi-agent, long-running,
strategy-steered research system, and renders verified results into papers and
human progress reports. This is the as-built map: the layered model, the folder
layout, the invariants, and the pinned cross-module contracts.

For the main agent's operating contract, see `AGENTS.md`
(→ `agents/contracts/main_agent.md`).

---

## 1. Layered model

```
operator → ① orchestration (main agent + danus CLI)   — continuously reasons at high level; coordinates
              ② strategy   (the main agent's own periodic synthesis: elaboration → master_guidance)
              ③ execution  (worker swarm; each round = one DSH session running the Rethlas proving skills)
   gm_* │         │ fact_submit
        ▼         ▼
   ⑤ truth      ④ verification (cold-start DSH judge; correct ⟺ no critical_errors AND no gaps)
   (fact graph + memory)   — a fact exists iff the verifier accepted it
        ▲
        │ sanctioned shared-store writes go through …
   ⑥ gateway (role-gated MCP: 6 tools; main has NO fact_submit; verifier read-only)

cross-cutting: ⑦ observability (dashboard · theorem-search · human-summary · initialize)
               ⑧ ops/runtime (bootstrap · services · doctor · config)
bottom: inherited Rethlas proving skills and verifier discipline; DSH runtime
output: write-paper (publication) · human-summary (progress report) — each rendered by an isolated DSH
```

---

## 2. Folder layout

```
Danus/
├─ ARCHITECTURE.md              this file (map + invariants + interface contract)
├─ README.md   pyproject.toml   top-level intro + the installable `danus` package
├─ .gitignore  .dsh/            main role wiring + completed-root-turn checkpoint plugin
├─ config/                      env templates (BYO key; only *.env.example committed)
├─ danus/                       THE ENGINE (installable Python package)
│  ├─ dsh.py                    explicit role-aware fresh-session runtime adapter
│  ├─ checkpoints.py            project Git snapshots, restore and generation fencing
│  ├─ core/                     ⑤ truth: schema · factgraph · global/local memory · bm25 · glossary
│  ├─ gateway/                  ⑥ role-gated MCP: 6 tools · role table (roles.py)
│  ├─ verify/                   ④ verification HTTP service · prechecks · cold-start DSH launcher
│  ├─ execution/                ③ worker swarm: round loop · project/worker lifecycle + layout
│  ├─ orchestration/            ① the `danus` CLI verbs
│  ├─ integrations/             arXiv theorem search (Matlas)
│  ├─ observability/            read-only dashboard
│  ├─ authoring/                shared main-only renderer primitives: the one-shot isolated DSH driver + common helpers
│  ├─ write_paper/              write-paper MCP service: assembler + tools (drives `danus.authoring`)
│  └─ human_summary/            human-summary MCP service: scrubbing assembler + tool (drives `danus.authoring`)
├─ agents/                      AGENT CONTRACTS + DSH-FACING SKILLS (data, not Python)
│  ├─ contracts/                main_agent.md · worker.md · verifier.md
│  └─ skills/
│     ├─ worker/                9 proving skills (inherited from Rethlas)
│     ├─ verify/                3 verify skills
│     └─ write-paper/           paper role prompts + house style (embedded by the write-paper MCP)
├─ .agents/skills/              MAIN-AGENT SKILLS (DSH auto-discovers)
│  ├─ elaboration/  human-summary/  initialize/
│  └─ write-paper/              the recipe SKILL.md + driver/ scripts + templates/
├─ bin/                         thin wrappers: danus · danus-mcp · write-paper-mcp · human-summary-mcp · dsh · danus-main
├─ scripts/                     bootstrap · doctor · services · env · setup/check-dsh · start-verify/-dashboard · recover · install-tex
├─ docs/                        human docs: getting started · concepts · operating guide · security & trust · …
└─ examples/                    unattended-ops examples + a toy project
```

---

## 3. Design invariants (must not regress)

1. Three memory tiers, one correctness boundary: local (private) → global
   (shared awareness) → fact graph (the only truth). A proof may build only on
   `fact_id`s; global memory is never a correctness source.
2. Permission is enforced by which tools a role can even see (the gateway role
   table), not by prompt convention. `main` cannot `fact_submit`; `verifier` is
   read-only.
3. The verifier is the sole write-gate. A fact exists only if a `correct` verdict
   came back; the gate lives in the `fact_submit` code path, not in prose.
4. Content-addressed, cascade-revocable fact graph. `fact_id` hashes content
   (problem_id + predecessors + glossary_introduces + statement + proof);
   `external_refs` is deliberately excluded so the paper pipeline can rewrite
   citations without breaking the DAG.
5. Autonomy and resumability. Workers run detached; each fresh DSH round continues
   from persisted memory, not transcript replay. Unsaved reasoning can be lost.
   One Git history per project captures shared stores and worker-private state
   best effort; live capture has no worker drain or writer barrier. External Git
   metadata lives at `runtime/.gitstore/<project>.git`, with no worktree `.git`
   pointer or source-repository submodule. Restore needs quiescent affected writers,
   makes a backup, fences old verdicts, and leaves restored workers stopped.
   See `docs/git-resume.md` for integrity warnings and the inconsistent override.
6. The main agent's own reasoning is the brain. It continuously reasons at the
   high level, maintains rolling speculative DSH subagents, distills shared state
   into an `elaboration`, and writes the
   direction it decides on as the swarm's `master_guidance`. This periodic steer
   is not optional — it is how the swarm gets steered.
7. Portable and BYO. No hardcoded absolute paths, no committed secrets; keys come
   from gitignored `config/*.env` (templates committed as `*.example`).
8. Clean author context. Any agent that produces an artifact for an outside
   audience (a paper, a human report) is a fresh isolated DSH fed a scoped,
   machinery-free prompt, never the orchestrator's own contaminated window. It
   cannot leak `fact_id`s or swarm vocabulary it never received.

---

## 4. Interfaces & ports — the coordination contract

> **Rule:** these rows are the seams where two modules meet. If a change touches a
> row, update both ends in the same change. Ports and contract shapes are pinned:
> one side must treat the other's contract as fixed, and must not change a port or
> interface unilaterally.

**Network ports (loopback — do not renumber):**

| port | service | producer → consumer |
|---|---|---|
| 8090 | isolated DSH Web main (configurable `DANUS_MAIN_PORT`) | operator browser → native main goals/schedules/subagents |
| 8091 | verify `/verify`, `/health` | `danus.gateway` `fact_submit` → `danus.verify` (via `DANUS_VERIFY_URL`) |
| 8099 | dashboard | operator browser → `danus.observability` (read-only) |

**Cross-module contracts (both ends must agree):**

| contract | pinned shape | ends |
|---|---|---|
| MCP tool set + role gating | 6 tools; `roles.py` `ROLE_TOOLS` (main has NO `fact_submit`; verifier read-only) | `danus.gateway` ↔ worker/main/verifier agents |
| MCP launch | `python -m danus.gateway` + `DANUS_ROLE` env | verifier and worker DSH overlays · `.dsh/` main overlay → `danus.gateway` |
| verify HTTP | `POST /verify {statement,proof}` → `{verification_report,verdict,repair_hints}`; verdict ⟺ no critical_errors & no gaps | `danus.gateway.fact_submit` ↔ `danus.verify` |
| fact id inputs | `problem_id + sorted(predecessors) + sorted(glossary) + normalized(statement,proof)`; **external_refs EXCLUDED** | `danus.core` ↔ everyone (write-paper reads `external_refs`) |
| global-memory kinds | the 11 `GLOBAL_KINDS` (incl. `master_guidance`/`elaboration`/`verification`) | `danus.core` ↔ agents |
| write-paper prompt assets | DSH role prompts + style read from `agents/skills/write-paper/` (via `DANUS_WRITE_PAPER_SKILL_DIR`) | `danus.write_paper` assembler ↔ `agents/skills/write-paper/` |
| env-var contract | explicit `DANUS_DSH_BIN`, `DANUS_DSH_PROVIDER`, `DANUS_DSH_PROVIDER_PATCH`; neutral `DANUS_MAIN_MODEL` / `DANUS_MAIN_EFFORT`, worker model, per-service model/effort overrides; no legacy fallback | `danus.dsh` + `config/` + `scripts/env.sh` ↔ worker, verifier, authoring launch sites |
| completed run | stdin prompt; final output accepted only with successful exit and completed-turn evidence | shared DSH adapter ↔ worker/verifier/renderer consumers |
| checkpoint triggers | completed worker round or completed root main turn, never per tool step; `DANUS_SNAPSHOT_AUTO=0` disables auto | worker loop / `.dsh/` plugin → project checkpoint API |
| restore | quiescent writers, pre-restore backup, generation fence, workers left stopped | CLI / checkpoint store ↔ gateway stale-verdict refusal |
