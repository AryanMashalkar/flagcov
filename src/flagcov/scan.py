"""Find flag keys read in source code (Python, JS/TS, Go, Java, Ruby, ...).

Static scanning complements runtime recording: it finds flags read by code
your tests never reach, flags missing from Flagsmith (typos!), and flags in
Flagsmith that no code reads any more.
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Iterable

EXTENSIONS = {".py", ".js", ".jsx", ".ts", ".tsx", ".mjs", ".cjs", ".go", ".java", ".kt", ".rb", ".php", ".cs", ".swift", ".dart", ".rs", ".vue", ".svelte"}
SKIP_DIRS = {".git", "node_modules", ".venv", "venv", "__pycache__", "dist", "build", ".tox", ".mypy_cache", ".pytest_cache", ".flagcov", "site-packages"}

_KEY = r"""(?P<q>["'`])(?P<key>[A-Za-z0-9_.:\-]{1,100})(?P=q)"""
PATTERNS = [
    # OpenFeature: get_boolean_value / getStringValue / getBooleanDetails ...
    re.compile(r"\bget_?(?:boolean|bool|string|integer|int|float|number|object)_?(?:value|details)\s*\(\s*" + _KEY, re.I),
    # Flagsmith SDKs: is_feature_enabled / isFeatureEnabled / hasFeature / getValue / get_feature_value / getTrait-free
    re.compile(r"\b(?:is_?feature_?enabled|has_?feature|get_?feature_?value|get_?flag)\s*\(\s*" + _KEY, re.I),
    re.compile(r"\bflagsmith\.(?:getValue|hasFeature)\s*\(\s*" + _KEY),
]
# React: useFlags(["a", "b"])
USE_FLAGS = re.compile(r"\buseFlags\s*\(\s*\[(?P<body>[^\]]*)\]")
STRING = re.compile(r"""["'`]([A-Za-z0-9_.:\-]{2,100})["'`]""")


def iter_files(paths: Iterable[str | os.PathLike[str]]) -> Iterable[Path]:
    for raw in paths:
        p = Path(raw)
        if p.is_file():
            if p.suffix in EXTENSIONS:
                yield p
            continue
        for root, dirs, files in os.walk(p):
            dirs[:] = [d for d in dirs if d not in SKIP_DIRS and not d.startswith(".")]
            for name in files:
                if Path(name).suffix in EXTENSIONS:
                    yield Path(root) / name


_PY_DOCSTRING = re.compile(r'("""|\'\'\')(?:.|\n)*?\1')
_LINE_COMMENT = re.compile(r"(?m)^[ \t]*(?:#|//|\*).*$")


def _blank(match: re.Match[str]) -> str:
    # keep newlines so line numbers stay right
    return re.sub(r"[^\n]", " ", match.group(0))


def strip_comments(text: str, python: bool = False) -> str:
    """Blank out whole-line comments (and Python docstrings), keeping line numbers."""
    if python:
        text = _PY_DOCSTRING.sub(_blank, text)
    return _LINE_COMMENT.sub(_blank, text)


def scan_text(text: str, python: bool = False) -> list[tuple[str, int]]:
    text = strip_comments(text, python)
    hits: dict[int, tuple[str, int]] = {}  # keyed by the key's offset, so overlapping patterns count once
    for pattern in PATTERNS:
        for m in pattern.finditer(text):
            hits.setdefault(m.start("key"), (m.group("key"), text.count("\n", 0, m.start()) + 1))
    for m in USE_FLAGS.finditer(text):
        line = text.count("\n", 0, m.start()) + 1
        for s in STRING.finditer(m.group("body")):
            hits.setdefault(m.start("body") + s.start(1), (s.group(1), line))
    return [hits[k] for k in sorted(hits)]


def changed_flags(base: str, cwd: str | os.PathLike[str] | None = None) -> set[str]:
    """Flag keys on lines added or removed since ``base`` (e.g. ``origin/main``), per ``git diff``."""
    import subprocess

    diff = subprocess.run(
        ["git", "diff", "--unified=0", f"{base}...HEAD"], cwd=cwd, capture_output=True, text=True, check=True
    ).stdout
    keys: set[str] = set()
    for line in diff.splitlines():
        if line[:1] in "+-" and not line.startswith(("+++", "---")):
            keys.update(k for k, _ in scan_text(line[1:]))
    return keys


def scan_paths(paths: Iterable[str | os.PathLike[str]]) -> dict[str, list[str]]:
    """Map each flag key to the ``file:line`` locations that read it."""
    refs: dict[str, list[str]] = {}
    for path in iter_files(paths):
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        for key, line in scan_text(text, python=path.suffix == ".py"):
            refs.setdefault(key, []).append(f"{path.as_posix()}:{line}")
    return dict(sorted(refs.items()))
