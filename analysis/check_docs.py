"""Check the Markdown files of the repository: links, images and leftover placeholders.

Run from any directory; paths are resolved from this file.

    python analysis/check_docs.py

For every ``*.md`` file (outside .git, virtual environments and tool caches) it checks that

* every relative link and image, in Markdown syntax (``[text](target)``, ``![alt](target)``,
  ``[label]: target``) or as an HTML ``href`` or ``src`` attribute, points to a file or folder
  that exists;
* a link with a ``#fragment`` into a Markdown file (or into the same file) names a heading of
  that file, using GitHub's rules for heading anchors;
* no placeholder token is left: the word REPLACE followed by an underscore, anywhere in the
  file, comments included.

HTML comments are skipped for the link checks, so commented-out image lines (the screenshots
the README will show once they exist) do not count as broken. So are fenced code blocks, inline
code spans and display maths. External links (http, https, mailto) are not fetched. Fragments
into files other than Markdown, such as ``01_data.py#L20-L42``, are checked for the file only.

Exits 1 and lists every problem, or prints a one-line summary and exits 0.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path
from urllib.parse import unquote

REPO = Path(__file__).resolve().parents[1]
SKIP_DIRS = {".git", ".venv", "venv", "env", "__pycache__", ".pytest_cache", ".ruff_cache", "node_modules"}
PLACEHOLDER = "REPLACE" + "_"  # built in two parts so this file does not match itself

COMMENT = re.compile(r"<!--.*?-->", re.DOTALL)
FENCE = re.compile(r"^( {0,3})(`{3,}|~{3,})[^\n]*\n.*?^\1\2[`~]*[ \t]*$", re.DOTALL | re.MULTILINE)
DISPLAY_MATH = re.compile(r"\$\$.*?\$\$", re.DOTALL)
INLINE_CODE = re.compile(r"(`+)(?:(?!\1).)+?\1", re.DOTALL)
INLINE_TARGET = re.compile(r"\]\(\s*(<[^>]*>|[^()\s]+(?:\([^()\s]*\)[^()\s]*)*)(?:\s+(?:\"[^\"]*\"|'[^']*'))?\s*\)")
REFERENCE_TARGET = re.compile(r"^ {0,3}\[[^\]]+\]:\s*(\S+)", re.MULTILINE)
HTML_TARGET = re.compile(r"\b(?:href|src)\s*=\s*[\"']([^\"']+)[\"']", re.IGNORECASE)
HEADING = re.compile(r"^ {0,3}(#{1,6})[ \t]+(.*?)[ \t]*#*[ \t]*$", re.MULTILINE)
HTML_ANCHOR = re.compile(r"<a\s+[^>]*?(?:name|id)\s*=\s*[\"']([^\"']+)[\"']", re.IGNORECASE)
EXTERNAL = re.compile(r"^(?:[a-z][a-z0-9+.-]*:|//)", re.IGNORECASE)


def markdown_files() -> list[Path]:
    files = []
    for path in sorted(REPO.rglob("*.md")):
        parts = set(path.relative_to(REPO).parts[:-1])
        if parts & SKIP_DIRS:
            continue
        files.append(path)
    return files


def blank(match: re.Match) -> str:
    """Replace a match with spaces, keeping its newlines so line numbers stay right."""
    return re.sub(r"[^\n]", " ", match.group(0))


def prose(text: str) -> str:
    """The text with comments, code and display maths blanked out."""
    for pattern in (COMMENT, FENCE, DISPLAY_MATH, INLINE_CODE):
        text = pattern.sub(blank, text)
    return text


def slug(heading: str) -> str:
    """GitHub's anchor for a heading: rendered text, lower case, punctuation dropped, spaces to hyphens."""
    text = re.sub(r"!?\[([^\]]*)\]\([^)]*\)", r"\1", heading)  # links and images: keep the text
    text = re.sub(r"<[^>]+>", "", text)                        # inline HTML tags
    text = text.replace("`", "").replace("*", "")
    text = re.sub(r"(?<![\w])_+|_+(?![\w])", "", text)          # emphasis underscores, not snake_case
    text = text.strip().lower()
    text = re.sub(r"[^\w\- ]", "", text)
    return text.replace(" ", "-")


def anchors(path: Path, cache: dict[Path, set[str]]) -> set[str]:
    if path not in cache:
        text = path.read_text(encoding="utf-8")
        visible = COMMENT.sub(blank, FENCE.sub(blank, text))
        seen: dict[str, int] = {}
        found = set()
        for match in HEADING.finditer(visible):
            base = slug(match.group(2))
            count = seen.get(base, 0)
            found.add(base if count == 0 else f"{base}-{count}")
            seen[base] = count + 1
        found.update(match.group(1) for match in HTML_ANCHOR.finditer(visible))
        cache[path] = found
    return cache[path]


def targets(text: str) -> list[tuple[int, str]]:
    visible = prose(text)
    found = []
    for pattern in (INLINE_TARGET, REFERENCE_TARGET, HTML_TARGET):
        for match in pattern.finditer(visible):
            target = match.group(1).strip()
            if target.startswith("<") and target.endswith(">"):
                target = target[1:-1]
            found.append((visible.count("\n", 0, match.start()) + 1, target))
    return sorted(found)


def check_file(path: Path, cache: dict[Path, set[str]]) -> tuple[list[str], int]:
    text = path.read_text(encoding="utf-8")
    where = path.relative_to(REPO).as_posix()
    problems = []
    for number, line in enumerate(text.splitlines(), start=1):
        if PLACEHOLDER in line:
            problems.append(f"{where}:{number}: placeholder token {PLACEHOLDER}...")
    checked = 0
    for number, target in targets(text):
        if not target or EXTERNAL.match(target):
            continue
        checked += 1
        link, _, fragment = target.partition("#")
        link = unquote(link)
        resolved = path if link == "" else (path.parent / link).resolve()
        if resolved != REPO and REPO not in resolved.parents:
            problems.append(f"{where}:{number}: {target} points outside the repository")
            continue
        if link and not resolved.exists():
            problems.append(f"{where}:{number}: {target} does not exist")
            continue
        if fragment and resolved.is_file() and resolved.suffix.lower() == ".md":
            if unquote(fragment).lower() not in anchors(resolved, cache):
                problems.append(f"{where}:{number}: {target} names no heading in "
                                f"{resolved.relative_to(REPO).as_posix()}")
    return problems, checked


def main() -> int:
    cache: dict[Path, set[str]] = {}
    problems: list[str] = []
    files = markdown_files()
    total = 0
    for path in files:
        found, checked = check_file(path, cache)
        problems += found
        total += checked
    if problems:
        print(f"{len(problems)} problem(s) in the Markdown files:")
        for problem in problems:
            print(f"  {problem}")
        return 1
    print(f"{len(files)} Markdown files, {total} relative links and images, all resolve; no placeholder tokens")
    return 0


if __name__ == "__main__":
    sys.exit(main())
