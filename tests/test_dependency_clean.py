"""INVARIANT: the open-source twingraph core depends on stdlib + pydantic only,
and imports no application package code.
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

_PKG_DIR = Path(__file__).resolve().parents[1] / "src" / "twingraph"

# Allowed non-stdlib top-level import roots.
_ALLOWED_THIRD_PARTY = {"pydantic", "twingraph"}

_STDLIB = set(getattr(sys, "stdlib_module_names", set()))


def _module_files() -> list[Path]:
    return sorted(_PKG_DIR.rglob("*.py"))


def _top_level_imports(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(), filename=str(path))
    roots: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                roots.add(alias.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom):
            if node.level and node.level > 0:
                continue  # relative import within twingraph — fine
            if node.module:
                roots.add(node.module.split(".")[0])
    return roots


def test_twingraph_imports_only_stdlib_and_pydantic():
    offenders: dict[str, set[str]] = {}
    for f in _module_files():
        for root in _top_level_imports(f):
            if root in _ALLOWED_THIRD_PARTY:
                continue
            if root in _STDLIB:
                continue
            if root == "__future__":
                continue
            offenders.setdefault(str(f.relative_to(_PKG_DIR)), set()).add(root)
    assert not offenders, f"twingraph imported non-stdlib/non-pydantic modules: {offenders}"
