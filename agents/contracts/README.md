# contracts/ — agent root contracts

The standing system prompt each agent **tier** reads at the top of every session —
the binding operating protocol, distinct from the on-demand skills under
`agents/skills/`. These are data (markdown), not code.

| File | Tier | Reads / writes |
| --- | --- | --- |
| `main_agent.md` | main agent (DSH, explicitly configured model/effort) | reasons continuously, maintains rolling exploratory subagents, reads global memory + fact graph, writes `master_guidance` / `elaboration`, and orchestrates. NO `fact_submit`. |
| `worker.md` | DSH worker | local memory (private) · global memory (`gm_add` / `gm_search`) · fact graph (`fact_submit`); the adaptive proving loop. Loaded per round via the explicit DSH `WORKER.md` role contract. |
| `verifier.md` | DSH verifier (verify service) | judges `{statement, proof}` → strict verdict; called by `fact_submit`; read-only (only `search_arxiv_theorems`); writes its verdict JSON directly to results/{run_id}/verification.json. |

The main DSH overlay loads the root [entry map](../../AGENTS.md), which requires
an operating main agent to read the complete [main-agent contract](main_agent.md)
before acting. That contract is the single home for detailed main operating
rules, including goals, schedules, reviews and operator decisions. It does not
send readers back to the root for missing procedures. Worker/verifier overlays
load their own role contract and skills; this index is not a substitute for them.

## The shared spine

Consistent across all three tiers:

- **The fact graph is the one source of truth** — a content-addressed DAG of
  verifier-accepted facts.
- **A fact enters only through `fact_submit`** (verifier-gated).
- **The verifier is the sole authority on correctness** — `correct` iff zero
  `critical_errors` AND zero `gaps`; no peer/LLM opinion substitutes.
- **Global memory** (incl. `master_guidance`) is shared awareness/strategy, never
  a correctness source — a proof builds only on `fact_id`s.
- **The shared stores change only through the sanctioned MCP tools**, never by hand.
- **All mathematical agents reason in text only** — no executable Python,
  numerical/symbolic computation, brute force, solvers, proof assistants, or
  parallel compute; lightweight reading, retrieval, and orchestration remain
  allowed.

## Who binds to these files

- `danus/gateway` — the exact MCP tool set + role gating (`main` has no
  `fact_submit`; `worker` adds it; `verifier` is read-only (`search_arxiv_theorems` only)).
- `danus/core` — the three-memory data model, the global-memory `kind`s, `fact_id`,
  the global glossary. The contracts are the human-readable statement of that model.
- `danus/verify` — `verifier.md` **is** the verify service's system prompt; its
  P1/P3/P5/P6 prohibitions pair with the server's single-line prechecks (and are
  the sole enforcement wherever those prechecks are off).
- `danus/execution` — loads `worker.md` per round through the DSH `WORKER.md`
  role contract and explicit skill directories; the worker reads `TASK.md` +
  `master_guidance`.
- `agents/skills/worker` & `agents/skills/verify` — the contracts reference `$…`
  skills by name; the reconciliation note in `worker.md` tells inherited skills to
  defer to this data model.
