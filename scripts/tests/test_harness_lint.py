"""Positive/negative guardrail tests; temporary Git repos never make commits."""
import importlib.util
from pathlib import Path
import subprocess

import pytest

SPEC = importlib.util.spec_from_file_location(
    "harness_lint", Path(__file__).resolve().parents[1] / "harness_lint.py"
)
lint = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(lint)


def put(root, name, text):
    path = root / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


@pytest.fixture
def repo(tmp_path):
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    put(tmp_path, ".gitignore", "runtime/\n.pixi/\n.gitstore/\n")
    for name in lint.MAPS:
        put(tmp_path, name, "# Documentation\n")
    put(tmp_path, "AGENTS.md", "# Map\nRead the full [operating contract](agents/contracts/main_agent.md).\n")
    subprocess.run(["git", "add", "."], cwd=tmp_path, check=True)
    return tmp_path


@pytest.mark.parametrize("name", [
    "runtime/projects/demo/project.json", "runtime/credential.example", ".pixi/envs/default/a",
    "custom/.gitstore/demo.git/config", "nested/.pixi/a", "private.key", "private.pem",
    "config/danus.env", ".env", ".env.local", "nested/service.env.production", "docs/test.env",
])
def test_generated_state_and_credentials_cannot_be_tracked(name):
    errors = lint.check_tracked_paths([name])
    assert len(errors) == 1
    assert "H001" in errors[0] and name in errors[0] and "remove" in errors[0]
    assert "docs/dev/invariants.md#h001-source-containment" in errors[0]


def test_templates_and_normal_source_are_allowed():
    assert lint.check_tracked_paths(["config/danus.env.example", ".env.example", "private.key.example",
                                     "danus/core/schema.py", "docs/environment.md"]) == []


def test_gitlinks_are_rejected_even_when_not_runtime(repo):
    oid = subprocess.run(["git", "hash-object", "-w", "--stdin"], cwd=repo, input=b"gitlink fixture",
                         capture_output=True, check=True).stdout.decode().strip()
    subprocess.run(["git", "update-index", "--add", "--cacheinfo", f"160000,{oid},external-project"], cwd=repo, check=True)
    assert any("H001 external-project" in error and "gitlinks" in error for error in lint.check(repo))


@pytest.mark.parametrize("statement", [
    "import requests", "from danus.gateway import server", "from ..gateway import server",
    "from .. import gateway", "from danus import gateway as gate", "from danus.corefoo import Fact",
    "import danus.corefoo", "from ...outside import value", "from danus import core, gateway",
])
def test_core_rejects_nonstdlib_and_parent_sibling_imports(tmp_path, statement):
    path = put(tmp_path, "danus/core/store.py", statement + "\n")
    errors = lint.check_core_imports(path, tmp_path)
    assert len(errors) == 1 and "H002" in errors[0] and ":1:" in errors[0]
    assert "move runtime/network integration outside core" in errors[0]


def test_core_accepts_stdlib_exact_core_and_relative_core_imports(tmp_path):
    path = put(tmp_path, "danus/core/nested/store.py", """import json
from pathlib import Path
from ..schema import Fact
from . import local
from danus import core
from danus.core.schema import Fact
from __future__ import annotations
""")
    assert lint.check_core_imports(path, tmp_path) == []
    # The compatibility helper also works for a standalone fixture file.
    standalone = put(tmp_path, "core.py", "from .schema import Fact\nimport json\n")
    assert lint.check_core_imports(standalone) == []


@pytest.mark.parametrize("statement", [
    "from danus import codex", "import danus.codex as runner", "from danus.codex import run",
    "from .. import codex as runner", "from ..codex import run", "import codex.client",
])
def test_legacy_runtime_guard_uses_ast_for_aliases_and_relatives(tmp_path, statement):
    path = put(tmp_path, "danus/execution/loop.py", statement + "\n")
    errors = lint.check_runtime_imports(path, tmp_path)
    assert len(errors) == 1 and "H004" in errors[0] and ":1:" in errors[0]
    assert "shared danus.dsh" in errors[0]


def test_ast_does_not_flag_comments_strings_or_similar_prefixes(tmp_path):
    path = put(tmp_path, "danus/execution/loop.py", '''# from danus import codex
note = "from danus.codex import run"
from danus import dsh
import danus.codex_documentation
''')
    assert lint.check_runtime_imports(path, tmp_path) == []
    path.write_text("from danus import (", encoding="utf-8")
    assert "repair Python syntax" in lint.check_runtime_imports(path, tmp_path)[0]


def test_entry_map_bound_and_operating_pointer_are_structural(repo):
    assert lint.check_entry_points(repo) == []
    put(repo, "AGENTS.md", "[Contract](agents/contracts/main_agent.md#arbitrary)\n" + "line\n" * 149)
    assert lint.check_entry_points(repo) == []  # size inclusive; fragments checked by H005
    with (repo / "AGENTS.md").open("a") as stream:
        stream.write("one more\n")
    errors = lint.check_entry_points(repo)
    assert any("AGENTS.md:151" in error and "150" in error for error in errors)
    put(repo, "AGENTS.md", "Read the contract in prose, but no link.\n")
    assert any("link to agents/contracts/main_agent.md" in error for error in lint.check_entry_points(repo))
    (repo / "docs/design.md").unlink()
    (repo / "docs/plans/README.md").unlink()
    assert sum("restore the contributor/runtime map target" in error for error in lint.check_entry_points(repo)) == 2


def test_optional_alternate_entry_is_absent_or_a_pointer_only(repo):
    assert lint.check_entry_points(repo) == []
    put(repo, "CLAUDE.md", "  \n@AGENTS.md\n\t")
    assert lint.check_entry_points(repo) == []
    put(repo, "CLAUDE.md", "@AGENTS.md\n\n# Another operating manual\n")
    errors = lint.check_entry_points(repo)
    assert len(errors) == 1 and "H003 CLAUDE.md:1" in errors[0]
    assert "only @AGENTS.md" in errors[0]


def test_link_checker_handles_images_references_titles_spaces_and_parentheses(repo):
    put(repo, "docs/space file.md", "# Topic\n")
    put(repo, "docs/guide_(new).md", "# Topic\n")
    put(repo, "docs/picture.png", "image fixture")
    source = put(repo, "docs/links.md", '''# Links
[space](<space file.md#topic> "title")
[encoded](space%20file.md#topic)
[balanced](guide_(new).md#topic)
[escaped](guide_\\(new\\).md#topic)
![image](picture.png)
[reference][guide]
[guide]: guide_(new).md#topic "Reference title"
[![nested image](picture.png)](space%20file.md)
[anchor](#links)
''')
    assert lint.check_markdown_links(source, repo) == []
    source.write_text('[bad](missing.md)\n![bad image](missing.png)\n[ref]: gone.md\n'
                      '[![nested](nested-missing.png)](guide_(new).md)\n', encoding="utf-8")
    errors = lint.check_markdown_links(source, repo)
    assert len(errors) == 4
    assert all("H005 docs/links.md:" in error and "repair local link/image target" in error for error in errors)


def test_links_ignore_code_comments_external_and_explicit_dynamic_examples(repo):
    source = put(repo, "docs/links.md", '''# Guide
```markdown
[not a link](missing-fenced.md)
```
~~~
![not an image](missing-tilde.png)
~~~
    [indented example](missing-indented.md)
`[inline example](missing-inline.md)`
<!-- [comment](missing-comment.md) -->
[web](https://example.invalid/missing.md)
[mail](mailto:operator@example.invalid)
![data](data:image/png;base64,abc)
[site](//example.invalid/path)
[project](../runtime/projects/demo/PROBLEM.md)
[template](../runtime/projects/<project>/PROBLEM.md)
[variable](${ROOT}/file.md)
[user](~/.dsh/config.json)
[escaped bracket]\\(not-a-link.md)
''')
    assert lint.check_markdown_links(source, repo) == []
    source.write_text("[outside](../../not-in-repo.md)\n[real missing](ordinary.md)\n", encoding="utf-8")
    assert len(lint.check_markdown_links(source, repo)) == 2


def test_heading_fragments_include_gfm_style_duplicates_unicode_and_html_ids(repo):
    target = put(repo, "docs/headings.md", '''# Hello, **World**!
## Hello, **World**!
## Hello World-1
## Café and `code()`
Setext title
------------
<a id="explicit-ID"></a>
<a name='legacy-name'></a>
<div data-id="not-an-anchor"></div>
<div id=unquoted-anchor></div>
<a id="literal&amp;entity"></a>
## Trailing spaces\x20\x20
```
# Not a heading
<a id="not-an-id"></a>
```
''')
    assert lint.markdown_anchors(target.read_text()) == {
        "hello-world", "hello-world-1", "hello-world-1-1", "café-and-code", "setext-title",
        "explicit-ID", "legacy-name", "unquoted-anchor", "literal&entity", "trailing-spaces",
    }
    source = put(repo, "docs/links.md", "\n".join(
        f"[target](headings.md#{anchor})" for anchor in lint.markdown_anchors(target.read_text())))
    assert lint.check_markdown_links(source, repo) == []
    source.write_text("[bad](headings.md#missing)\n", encoding="utf-8")
    assert "repair fragment 'missing'" in lint.check_markdown_links(source, repo)[0]


@pytest.mark.parametrize("status", ["Proposed", "In progress", "Completed", "Blocked"])
def test_plan_status_accepts_defined_values(repo, status):
    path = put(repo, "docs/plans/new-plan.md", f"# Plan\n\n**Status:** {status}\n")
    assert lint.check_plan_status(path, repo) == []


@pytest.mark.parametrize("body", ["# Plan\n", "Status: Done\n", "Status: Proposed\nStatus: Completed\n",
                                      "```\nStatus: Completed\n```\n",
                                      "---\nStatus: Completed\n---\n# Plan\n"])
def test_plan_status_requires_one_real_defined_status(repo, body):
    path = put(repo, "docs/plans/new-plan.md", body)
    errors = lint.check_plan_status(path, repo)
    assert len(errors) == 1 and "H006" in errors[0] and "add exactly one Status:" in errors[0]


@pytest.mark.parametrize("metadata", [
    'name: example\ndescription: Useful words',
    'name: "example"\ndescription: "A # literal hash" # comment',
    "name: 'example'\ndescription: 'It''s useful'",
    'name: example\ndescription: >-\n  First line\n  Second line',
    'name: example\ndescription: |\n  A literal description',
])
def test_skill_metadata_supports_documented_plain_quoted_and_block_forms(repo, metadata):
    path = put(repo, ".agents/skills/example/SKILL.md", f"---\n{metadata}\n---\n# Skill\n")
    assert lint.check_skill_metadata(path, repo) == []


@pytest.mark.parametrize("metadata", [
    "name: wrong\ndescription: useful", "name: example", "description: useful",
    "name: example\ndescription: ''", "name: example\ndescription: null",
    "name: example\ndescription: # only a comment", "name: example\ndescription: >\n",
    "name: example\ndescription: []", "name: example\ndescription: first\ndescription: second",
    "name: example\ndescription: 42", "name: example\ndescription: *alias",
])
def test_skill_metadata_rejects_missing_empty_wrong_or_ambiguous_required_fields(repo, metadata):
    path = put(repo, "agents/skills/verify/example/SKILL.md", f"---\n{metadata}\n---\n# Skill\n")
    errors = lint.check_skill_metadata(path, repo)
    assert errors and all("H007 agents/skills/verify/example/SKILL.md:" in error for error in errors)
    assert all("docs/dev/invariants.md#h007-skill-metadata" in error for error in errors)


def test_missing_frontmatter_and_deleted_skill_descriptor_are_actionable(repo):
    path = put(repo, "agents/skills/worker/example/SKILL.md", "# no frontmatter\n")
    assert "add leading --- frontmatter" in lint.check_skill_metadata(path, repo)[0]
    path.unlink()
    assert "restore the installable SKILL.md" in lint.check_skill_metadata(path, repo)[0]


def test_git_discovery_checks_untracked_source_but_not_ignored_outputs(repo):
    assert lint.check(repo) == []
    put(repo, "docs/untracked.md", "[bad](missing.md)\n")
    put(repo, "danus/execution/new.py", "from .. import codex\n")
    put(repo, "danus/core/nested/store.py", "from ...gateway import server\n")
    put(repo, "danus/core/tests/test_store.py", "import pytest\n")
    put(repo, "runtime/generated.md", "[bad](missing.md)\n")
    put(repo, ".pixi/README.md", "[bad](missing.md)\n")
    put(repo, "docs/plans/README.md", "# Index needs no Status\n")
    put(repo, "agents/skills/write-paper/roles/README.md", "# Not an installable skill\n")
    failures = lint.check(repo)
    assert len(failures) == 3
    assert {error.split()[0] for error in failures} == {"H002", "H004", "H005"}


def test_rule_diagnostics_have_location_remediation_and_documentation_anchor():
    for rule, slug in lint.RULES.items():
        message = lint.diagnostic(rule, "file.md:3", "repair this fixture")
        assert message.startswith(f"{rule} file.md:3: repair")
        assert f"docs/dev/invariants.md#{rule.lower()}-{slug}" in message
