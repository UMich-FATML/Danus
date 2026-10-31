#!/usr/bin/env python3
"""Small offline guardrails, not a complete Python/Markdown/YAML verifier.

Source discovery comes from Git's index plus nonignored untracked files. See the
rule docs for supported Markdown and skill-metadata forms and deliberate limits.
"""
from __future__ import annotations

import ast
import html
import json
from pathlib import Path, PurePosixPath
import re
import subprocess
import sys
import unicodedata
from urllib.parse import unquote, urlsplit

ROOT = Path(__file__).resolve().parents[1]
RULES = {
    "H001": "source-containment", "H002": "core-boundary", "H003": "entry-points",
    "H004": "single-runtime", "H005": "local-markdown-links", "H006": "plan-status",
    "H007": "skill-metadata",
}
MAPS = ("AGENTS.md", "CONTRIBUTING.md", "docs/dev/index.md", "docs/dev/invariants.md",
        "docs/design.md", "docs/plans/README.md", "agents/contracts/main_agent.md",
        "docs/git-resume.md", "docs/dsh-migration.md", "docs/tech-debt.md")
SKILL_ROOTS = (".agents/skills", "agents/skills/worker", "agents/skills/verify")


def diagnostic(rule: str, location: str | Path, remedy: str) -> str:
    return f"{rule} {location}: {remedy} (docs/dev/invariants.md#{rule.lower()}-{RULES[rule]})."


def generated_path(name: str) -> bool:
    parts = PurePosixPath(name).parts
    return bool(parts) and (parts[0] == "runtime" or any(p in {".pixi", ".gitstore"} for p in parts))


def check_tracked_paths(paths: list[str], gitlinks: set[str] | None = None) -> list[str]:
    errors = []
    for name in paths:
        path = PurePosixPath(name)
        leaf = path.name.lower()
        credential = not leaf.endswith(".example") and (
            leaf == ".env" or leaf.endswith(".env") or ".env." in leaf or
            path.suffix.lower() in {".pem", ".key", ".p12", ".pfx"})
        if generated_path(name) or credential or name in (gitlinks or set()):
            errors.append(diagnostic("H001", name, "remove generated/credential state or gitlinks from the source index; keep runtime repositories and credentials ignored, not deleted"))
    return errors


def _package(path: Path, root: Path | None, fallback: str) -> str:
    if root is not None:
        return ".".join(path.relative_to(root).parent.parts)
    parts = path.parts
    if "danus" in parts:
        return ".".join(parts[parts.index("danus"):-1])
    return fallback


def _imports(node: ast.AST, package: str) -> list[str]:
    if isinstance(node, ast.Import):
        return [alias.name for alias in node.names]
    if not isinstance(node, ast.ImportFrom):
        return []
    base = node.module or ""
    if node.level:
        parts = package.split(".")
        if node.level > len(parts):
            return ["<relative import outside package>"]
        base = ".".join(parts[:len(parts) - node.level + 1] + ([base] if base else []))
    # A parent import can introduce a sibling module, including `from .. import
    # gateway` and `from danus import core, gateway`. Keep aliases, not just base.
    return [base] + [f"{base}.{alias.name}" for alias in node.names]


def _within(module: str, prefix: str) -> bool:
    return module == prefix or module.startswith(prefix + ".")


def _syntax(path: Path, rule: str) -> tuple[ast.AST | None, list[str]]:
    try:
        return ast.parse(path.read_text(encoding="utf-8"), filename=str(path)), []
    except (SyntaxError, UnicodeError) as exc:
        return None, [diagnostic(rule, f"{path}:{getattr(exc, 'lineno', 1)}", "repair Python syntax/UTF-8 so static import checks can run")]


def check_core_imports(path: Path, root: Path | None = None) -> list[str]:
    tree, errors = _syntax(path, "H002")
    if tree is None:
        return errors
    package = _package(path, root, "danus.core")
    for node in ast.walk(tree):
        modules = _imports(node, package)
        if not modules:
            continue
        if isinstance(node, ast.ImportFrom):
            # `from danus import core` is legal; bare danus is not itself an
            # imported dependency here. Relative parent aliases get same rule.
            modules = modules[1:] if modules[0] == "danus" else modules[:1]
        if any(module.split(".")[0] not in sys.stdlib_module_names and
               not _within(module, "danus.core") for module in modules):
            errors.append(diagnostic("H002", f"{path}:{node.lineno}", "core must stay stdlib-only; move runtime/network integration outside core"))
    return errors


def check_runtime_imports(path: Path, root: Path | None = None) -> list[str]:
    tree, errors = _syntax(path, "H004")
    if tree is None:
        return errors
    for node in ast.walk(tree):
        if any(_within(module, "danus.codex") or _within(module, "codex")
               for module in _imports(node, _package(path, root, "danus.execution"))):
            errors.append(diagnostic("H004", f"{path}:{node.lineno}", "use the shared danus.dsh adapter; remove the legacy runtime import, not comments describing migration"))
    return errors


def _blank(text: str) -> str:
    return "".join("\n" if char == "\n" else " " for char in text)


def markdown_prose(text: str, *, inline_code: bool = True) -> str:
    """Mask common code/comment forms without moving diagnostic line numbers."""
    lines = text.splitlines(keepends=True)
    fence: tuple[str, int] | None = None
    frontmatter = bool(lines and lines[0].strip() == "---" and
                       any(line.strip() == "---" for line in lines[1:]))
    for index, line in enumerate(lines):
        if frontmatter:
            lines[index] = _blank(line)
            if index and line.strip() == "---":
                frontmatter = False
            continue
        marker = re.match(r"^ {0,3}(`{3,}|~{3,})(.*)$", line)
        if fence:
            lines[index] = _blank(line)
            if marker and marker[1][0] == fence[0] and len(marker[1]) >= fence[1] and not marker[2].strip():
                fence = None
        elif marker:
            fence = (marker[1][0], len(marker[1]))
            lines[index] = _blank(line)
        elif line.startswith(("    ", "\t")):
            lines[index] = _blank(line)
    prose = re.sub(r"<!--[\s\S]*?-->", lambda m: _blank(m[0]), "".join(lines))
    if inline_code:
        prose = re.sub(r"(`+)(?!`)([\s\S]*?)(?<!`)\1(?!`)", lambda m: _blank(m[0]), prose)
    return prose


def _destination(text: str, start: int) -> tuple[str, int] | None:
    """Read an angle destination or a balanced, optionally escaped bare path."""
    pos = start
    while pos < len(text) and text[pos].isspace():
        pos += 1
    if pos >= len(text):
        return None
    if text[pos] == "<":
        end = text.find(">", pos + 1)
        return (text[pos + 1:end], end + 1) if end >= 0 else None
    begin, depth = pos, 0
    while pos < len(text):
        char = text[pos]
        if char == "\\" and pos + 1 < len(text):
            pos += 2
            continue
        if char == "(":
            depth += 1
        elif char == ")":
            if not depth:
                break
            depth -= 1
        elif char.isspace() and not depth:
            break
        pos += 1
    return (text[begin:pos], pos) if depth == 0 else None


def markdown_links(text: str) -> list[tuple[str, int]]:
    """Inline links/images and reference definitions; unknown shortcuts are prose.

    Titles are ignored. Definitions are checked once at their own line, including
    unused definitions. This deliberately does not claim full CommonMark parsing.
    """
    prose = markdown_prose(text)
    links = []
    definitions = list(re.finditer(r"(?m)^ {0,3}\[[^\]\n]+\]:[ \t]*", prose))
    for match in definitions:
        value = _destination(prose, match.end())
        if value:
            links.append((value[0], prose.count("\n", 0, match.start()) + 1))
    pos = 0
    while pos < len(prose):
        if prose[pos] == "\\":
            pos += 2
            continue
        if prose[pos] != "[":
            pos += 1
            continue
        start, depth = pos, 1
        pos += 1
        while pos < len(prose) and depth:
            if prose[pos] == "\\":
                pos += 2
                continue
            depth += (prose[pos] == "[") - (prose[pos] == "]")
            pos += 1
        if depth or pos >= len(prose) or prose[pos] != "(":
            pos = start + 1
            continue
        value = _destination(prose, pos + 1)
        if value:
            destination, end = value
            tail = prose[end:]
            # A destination must be followed by ')' or a conventional title and
            # ')'; do not mistake arbitrary bracketed prose for a local link.
            if re.match(r"\s*(?:\"[^\"]*\"|'[^']*'|\([^)]*\))?\s*\)", tail):
                links.append((destination, prose.count("\n", 0, start) + 1))
        # Also inspect nested image/link labels rather than skipping everything
        # inside an outer link (a common local screenshot/badge pattern).
        pos = start + 1
    return links


def _slug(heading: str) -> str:
    heading = re.sub(r"!?\[([^\]]+)\]\([^)]*\)", r"\1", heading.strip())
    heading = re.sub(r"<[^>]+>", "", heading)
    heading = re.sub(r"(?<!\w)(\*{1,2}|_{1,2})(.+?)\1(?!\w)", r"\2", heading)
    heading = html.unescape(heading.replace("`", "")).lower()
    return "".join("-" if c.isspace() else c for c in heading
                   if c.isspace() or c in "_-" or unicodedata.category(c)[0] in "LNM")


def markdown_anchors(text: str) -> set[str]:
    prose = markdown_prose(text, inline_code=False)
    anchors = set()
    value = r'''\s*=\s*(?:"([^"]+)"|'([^']+)'|([^\s>]+))'''
    for pattern in (r"<[a-z][^>]*?\s+id", r"<a\b[^>]*?\s+name"):
        for match in re.finditer(pattern + value, prose, re.I):
            anchors.add(html.unescape(next(group for group in match.groups() if group is not None)))
    used = set()
    lines = prose.splitlines()
    for index, line in enumerate(lines):
        atx = re.match(r"^ {0,3}#{1,6}[ \t]+(.*?)(?:[ \t]+#+[ \t]*)?$", line)
        heading = atx[1] if atx else None
        if heading is None and index and re.fullmatch(r" {0,3}(?:=+|-+)[ \t]*", line) and lines[index - 1].strip():
            heading = lines[index - 1].strip()
        if heading is None:
            continue
        base = _slug(heading)
        slug, suffix = base, 0
        while slug in used:
            suffix += 1
            slug = f"{base}-{suffix}"
        used.add(slug)
        anchors.add(slug)
    return anchors


def _local_target(root: Path, source: Path, raw: str) -> tuple[Path, str] | None:
    raw = re.sub(r"\\([!\"#$%&'()*+,\-./:;<=>?@\[\\\]^_`{|}~])", r"\1", html.unescape(raw))
    if re.match(r"^[a-zA-Z][a-zA-Z0-9+.-]*:", raw) or raw.startswith("//"):
        return None
    # Operator/runtime placeholders are examples, not repository paths. Do not
    # silently exempt ordinary broken links; this list is intentionally bounded.
    if raw.startswith(("~", "$")) or re.search(r"[{}<>]|\$\(|\$\{|\.\.\.|…", unquote(raw)):
        return None
    parsed = urlsplit(raw)
    path, fragment = unquote(parsed.path), unquote(parsed.fragment)
    target = (root / path.lstrip("/")) if path.startswith("/") else source.parent / path
    if not path:
        target = source
    target = target.resolve()
    try:
        relative = target.relative_to(root.resolve()).as_posix()
    except ValueError:
        return target, fragment  # caller reports an escaping repository path
    return None if generated_path(relative) else (target, fragment)


def check_markdown_links(path: Path, root: Path) -> list[str]:
    errors = []
    text = path.read_text(encoding="utf-8")
    for raw, line in markdown_links(text):
        target = _local_target(root, path, raw)
        if target is None:
            continue
        destination, fragment = target
        location = f"{path.relative_to(root)}:{line}"
        if not destination.is_relative_to(root.resolve()) or not destination.exists():
            errors.append(diagnostic("H005", location, f"repair local link/image target {raw!r}; link to an existing repository path (use code for runtime examples)"))
        elif fragment and destination.is_file() and destination.suffix.lower() == ".md":
            if fragment not in markdown_anchors(destination.read_text(encoding="utf-8")):
                errors.append(diagnostic("H005", location, f"repair fragment {fragment!r} in {raw!r}; use a heading slug or explicit HTML id in the target"))
    return errors


def documentation_path(name: str) -> bool:
    path = PurePosixPath(name)
    if path.suffix.lower() != ".md" or generated_path(name):
        return False
    if path.name.lower() == "readme.md" or len(path.parts) == 1 or path.parts[0] == "docs":
        return True
    prefixes = ("agents/contracts/", "agents/skills/", ".agents/skills/")
    # Skill example projects/rendered reports are fixture output, not navigation;
    # their README guides remain checked by the branch above.
    return name.startswith(prefixes) and not any(p in {"examples", "templates"} for p in path.parts)


def check_entry_points(root: Path) -> list[str]:
    errors = [diagnostic("H003", name, "restore the contributor/runtime map target")
              for name in MAPS if not (root / name).is_file()]
    alternate = root / "CLAUDE.md"
    if alternate.is_file() and alternate.read_text(encoding="utf-8").strip() != "@AGENTS.md":
        errors.append(diagnostic("H003", "CLAUDE.md:1", "replace the alternate entry with only @AGENTS.md; keep one canonical map, not a second manual"))
    entry = root / "AGENTS.md"
    if entry.is_file():
        text = entry.read_text(encoding="utf-8")
        if len(text.splitlines()) > 150:
            errors.append(diagnostic("H003", "AGENTS.md:151", "keep the entry map at most 150 lines; move detailed procedures to their canonical linked documents"))
        expected = (root / "agents/contracts/main_agent.md").resolve()
        if not any(target and target[0] == expected for raw, _ in markdown_links(text)
                   for target in [_local_target(root, entry, raw)]):
            errors.append(diagnostic("H003", "AGENTS.md:1", "link to agents/contracts/main_agent.md so operators can read the complete operating contract; do not duplicate it here"))
    return errors


def check_plan_status(path: Path, root: Path) -> list[str]:
    prose = markdown_prose(path.read_text(encoding="utf-8"))
    statuses = [(line, re.sub(r"\*\*", "", value).strip())
                for line, value in enumerate(prose.splitlines(), 1)
                if re.match(r"^\s*(?:\*\*)?Status(?:\*\*)?\s*:", value)]
    valid = {"Proposed", "In progress", "Completed", "Blocked"}
    if len(statuses) != 1 or statuses[0][1].partition(":")[2].strip() not in valid:
        return [diagnostic("H006", f"{path.relative_to(root)}:{statuses[0][0] if statuses else 1}", "add exactly one Status: Proposed, In progress, Completed, or Blocked outside code examples; update it when the plan changes")]
    return []


def _metadata_scalar(value: str, continuation: list[str]) -> str | None:
    value = value.strip()
    if value.startswith('"'):
        try:
            parsed, end = json.JSONDecoder().raw_decode(value)
            tail = value[end:].strip()
            return parsed if isinstance(parsed, str) and (not tail or tail.startswith("#")) else None
        except ValueError:
            return None
    if value.startswith("'"):
        quoted = re.fullmatch(r"'((?:[^']|'')*)'\s*(?:#.*)?", value)
        return quoted[1].replace("''", "'") if quoted else None
    value = re.sub(r"\s+#.*$", "", value).strip()
    if re.fullmatch(r"[|>][+-]?", value):
        return " ".join(line.strip() for line in continuation).strip()
    if (not value or value.lower() in {"null", "~", "true", "false"} or
            value.startswith(("[", "{", "#", "&", "*", "!")) or
            re.fullmatch(r"[-+]?\d+(?:\.\d+)?", value)):
        return None
    return value


def check_skill_metadata(path: Path, root: Path) -> list[str]:
    location = path.relative_to(root)
    if not path.is_file():
        return [diagnostic("H007", location, "restore the installable SKILL.md descriptor with name and description metadata")]
    lines = path.read_text(encoding="utf-8").splitlines()
    if not lines or lines[0] != "---" or "---" not in lines[1:]:
        return [diagnostic("H007", f"{location}:1", "add leading --- frontmatter with a folder-matching name and a nonempty description")]
    block = lines[1:lines[1:].index("---") + 1]
    fields: dict[str, list[tuple[int, str | None]]] = {}
    for index, line in enumerate(block):
        match = re.match(r"^(name|description):[ \t]*(.*)$", line)
        if not match:
            continue
        following = []
        for extra in block[index + 1:]:
            if extra and not extra[0].isspace():
                break
            following.append(extra)
        fields.setdefault(match[1], []).append((index + 2, _metadata_scalar(match[2], following)))
    errors = []
    for key in ("name", "description"):
        values = fields.get(key, [])
        if len(values) != 1 or not values[0][1] or (key == "name" and values[0][1] != path.parent.name):
            remedy = "set name to the containing skill folder" if key == "name" else "provide a nonempty description string (plain, quoted, or an indented |/> block)"
            errors.append(diagnostic("H007", f"{location}:{values[0][0] if values else 1}", remedy + "; remove duplicate/unsupported required fields"))
    return errors


def check(root: Path = ROOT) -> list[str]:
    root = root.resolve()
    indexed = subprocess.run(["git", "ls-files", "--stage", "-z"], cwd=root, check=True,
                             capture_output=True).stdout.decode().split("\0")
    entries = [row.split("\t", 1) for row in indexed if row]
    tracked = [name for _, name in entries]
    gitlinks = {name for header, name in entries if header.split()[0] == "160000"}
    discovered = subprocess.run(["git", "ls-files", "--cached", "--others", "--exclude-standard", "-z"],
                                cwd=root, check=True, capture_output=True).stdout.decode().split("\0")
    paths = sorted({name for name in discovered if name})
    errors = check_tracked_paths(tracked, gitlinks)
    for probe in ("runtime/.gitstore/probe.git/config", "runtime/projects/probe/project.json",
                  ".pixi/envs/probe/bin/python", "custom/.gitstore/probe.git/config"):
        if subprocess.run(["git", "check-ignore", "--no-index", "-q", probe], cwd=root).returncode != 0:
            errors.append(diagnostic("H001", probe, "add its generated root to .gitignore"))
    errors.extend(check_entry_points(root))
    for name in paths:
        path = root / name
        if generated_path(name):
            continue
        if path.is_file() and path.suffix == ".py" and "tests" not in path.relative_to(root).parts:
            if name.startswith("danus/core/"):
                errors.extend(check_core_imports(path, root))
            if name.startswith(("danus/execution/", "danus/verify/", "danus/authoring/")):
                errors.extend(check_runtime_imports(path, root))
        if path.is_file() and documentation_path(name):
            errors.extend(check_markdown_links(path, root))
        if path.is_file() and name.startswith("docs/plans/") and path.suffix == ".md" and path.name.lower() != "readme.md":
            errors.extend(check_plan_status(path, root))
        if any(path.parent.parent == root / base for base in SKILL_ROOTS) and path.name == "SKILL.md":
            errors.extend(check_skill_metadata(path, root))
    return errors


if __name__ == "__main__":
    failures = check()
    for failure in failures:
        print(failure, file=sys.stderr)
    if not failures:
        print("Harness invariants passed")
    raise SystemExit(bool(failures))
