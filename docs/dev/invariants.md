# Enforced development invariants

Run `pixi run check` locally and in CI; `pixi run lint` runs the fast guards.
The static guard lives in [harness_lint.py](../../scripts/harness_lint.py), with
[positive and negative tests](../../scripts/tests/test_harness_lint.py).
Every diagnostic includes a rule, source location, remedy, and link to this page.
Change a rule, its implementation, and its failing-path test together.

These checks enforce bounded structural properties, not complete language parsing
or proof of runtime safety. Behavioral guarantees still belong in offline
unit/integration tests. Git discovery includes indexed paths and nonignored
untracked source, so a new document or module is checked before it is staged.

## H001: Source containment

Runtime projects, external snapshot Git stores, Pixi environments, credentials,
and Git submodule entries must never enter the source Git index. The guard rejects:

- Paths under root `runtime/`, and `.pixi` or `.gitstore` at any directory depth.
- Files named `.env`, ending in `.env`, or containing `.env.` anywhere in the
  basename, not just under `config/`.
- Credential suffixes `.pem`, `.key`, `.p12`, and `.pfx`.
- Index mode `160000` (gitlinks), including those outside the usual runtime root.

Credential templates ending in `.example` are allowed; the template exception
never permits generated runtime paths. This is a filename/index guard, **not a
content secret scanner**. Keep generated roots ignored and remove accidentally
staged entries from the index without deleting live data. The check also probes
ignore coverage for normal runtime, custom `.gitstore`, and Pixi paths. A custom
project root outside `runtime/` needs its own ignore rule or an external location.
Git checkpoints enforce their separate, stricter content policy.

## H002: Core boundary

Production modules under `danus/core/` may import Python's standard library or
`danus.core` and its exact dotted descendants. `danus.corefoo` is not core.
Relative imports are resolved using the containing package, so `from ..gateway`
and `from .. import gateway` cannot bypass the boundary. Core test directories
are excluded: test infrastructure is not a production dependency.

Move provider, process, gateway, and network integrations outside the truth/memory
package. This preserves deterministic data-model tests and prevents runtime
interfaces from leaking into the data model. The guard examines ordinary AST
`import`/`from` statements, including aliases and nested statements. It does not
prove control flow or inspect `importlib`, `__import__`, reflection, reexports,
subprocesses, or transitive behavior. Dynamic imports remain a review obligation;
a passing static guard is not a formal boundary proof.

## H003: Entry points

Required navigation targets include the contributor/engineering maps, this rule
page, [design rationale](../design.md), [plan index](../plans/README.md), runtime
migration/recovery guides, the debt list, and the main-agent operating contract.
Restore a missing target rather than adding a second copy of its instructions.

Root `AGENTS.md` is a map of at most **150 physical lines** (about 100 is the design
target). It must contain a real local Markdown link to
[the complete operating contract](../../agents/contracts/main_agent.md).
The checker verifies the link, not an exact prose sentence or whether an agent
actually read it. The map's instruction to read the full contract remains binding.
Coding must not trigger deployment initialization or paid model calls; the detailed
operating procedures belong in the contract, not duplicated in the entry map.
If root `CLAUDE.md` exists, it must contain only `@AGENTS.md` (surrounding whitespace
is allowed). Do not create a second operating manual for another harness.

## H004: Single runtime

Production worker, verifier, and authoring modules must use the shared DSH
adapter. Their AST imports must not name `danus.codex`/its descendants or the
legacy `codex` package. Absolute, relative, parent-package, and aliased imports
are checked; comments, docstrings, and unrelated names such as
`danus.codex_documentation` are not imports and do not trigger this rule.

This is the same bounded static analysis as H002, not a detector for dynamic
imports or shell-command strings. Existing offline tests cover actual DSH
configuration, protocol parsing, role discovery, and failure behavior. A stale
provider setting must fail explicitly instead of silently selecting an account.

## H005: Local Markdown links

Fix broken local links/images at the reported source line. Targets must exist
inside the repository. For a Markdown-file fragment, use its heading slug or an
explicit HTML `id` (legacy `<a name="…">` anchors are also recognized).

The Git-aware check covers root Markdown documents, `docs/`, role contracts,
main/worker/verifier/authoring skill guidance, and source README files (including
module READMEs). Skill `examples/` projects/rendered reports and `templates/`
artifacts are not navigation sources; their README guides **are** checked.

Supported forms are inline Markdown links/images, nested image labels, reference
link definitions, angle-bracket destinations with spaces, escaped/balanced
parentheses, percent-encoded paths, and optional titles. Reference definitions are
checked once at their own line. Root-absolute destinations mean repository-root
paths. Markdown heading fragments use a tested GFM-style subset: ATX and setext
headings, common inline formatting, Unicode letters, duplicate-slug suffixes,
and explicit HTML IDs. Fragment spelling is case-sensitive.

Deliberate limits and exclusions:

- Fenced/indented code, inline code, HTML comments, and leading frontmatter are
  examples/metadata, not navigational prose.
- External URL schemes, protocol-relative URLs, and generated `runtime/`,
  `.pixi`, or `.gitstore` targets are not fetched or validated.
- Destinations using `~`, leading shell variables, `{…}`, `<…>` placeholders,
  command substitution, or ellipses are operator/template examples, not literal
  source paths. Prefer code formatting for such examples.
- This is **not a full CommonMark/GFM parser**. Raw HTML links, undefined shortcut
  references, complex Markdown extensions, and non-Markdown/directory fragment
  semantics are not validated. It does not validate arbitrary malformed markup.
  The heading renderer is intentionally small, not a complete GitHub renderer.

Do not suppress an ordinary missing source target as a template. For an
unsupported genuine Markdown construct, report the exact source/target and add
a narrowly tested parser improvement or use an unambiguous supported form.

## H006: Plan status

Every Markdown plan under `docs/plans/`, except its README index, must have
exactly one visible `Status:` declaration using **Proposed**, **In progress**,
**Completed**, or **Blocked**. Use a plain Markdown line with a plain or bold
label; declarations inside YAML frontmatter or code fences do not count. Update the status when the plan changes, and follow the
[plan index guidance](../plans/README.md) for progress and decision records.
The guard does not infer completion from a checked task list or judge the plan's
substance.

## H007: Skill metadata

Direct `*/SKILL.md` descriptors under `.agents/skills`, `agents/skills/worker`,
and `agents/skills/verify` need leading `---` frontmatter. `name` must match the
containing folder, and `description` must be a nonempty string. Missing, duplicate,
empty, null, or unsupported container-valued required fields are actionable errors.
Write-paper role/style assets are not installable skills and are excluded.

This bounded stdlib reader supports plain scalars, single-quoted strings with
doubled apostrophes, JSON-compatible double-quoted strings, and indented `|`/`>`
blocks with optional `+`/`-` chomping markers. It supports ordinary trailing
comments without treating a quoted `#` as a comment. It is **not a YAML syntax
validator** and does not interpret anchors, aliases, tags, multiline quoted
scalars, or arbitrary YAML extensions. Use the supported simple forms for these
two required fields; other metadata is left to the consuming runtime.

The existing [worker conformance check](../../agents/skills/worker/check_conformance.py)
still owns the known nine-skill roster and forbidden tool references. Existing
verifier schema tests own verifier output shape. Those checks run alongside this
guard rather than being duplicated here. Main/verifier descriptor metadata now
receives the same structural coverage without expanding their tool permissions.

## Behavioral invariants (tested)

The [check runner](../../scripts/check.py) builds an isolated temporary DSH home
and removes deployment/provider credential settings from its child environment.
Fast mode runs structural, skill-conformance, and shell/Node syntax checks without
executing services. Full mode adds the offline Python and plugin suites, including
verifier schema checks. The repository-local pre-commit hook uses fast mode;
installing it must not silently replace a different configured hooks path.
Runner isolation and hook installation have behavioral tests rather than another
text-matching rule. A fast-hook pass never replaces full contributor/CI checks.

- Snapshot triggers mean completed full main turns / worker rounds, never each
  tool result or speculative subagent completion.
- Snapshot creation serializes Git operations only and does not stop writers.
- Restore requires stopped writers, preserves a backup, and fences old verifier
  responses. Snapshot validation does not certify the mathematics.
- DSH output is successful only with successful process and turn completion;
  final-text extraction must not mix diagnostic events into published artifacts.
- Role-gated tools remain enforced by the gateway; main cannot submit facts.
