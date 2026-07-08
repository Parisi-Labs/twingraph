"""metis_expr/0.1 — a minimal tokenizer + reference extractor (NO evaluation).

Constraints carry typed expressions, not free text (§9.9). At compile we must
prove an expression PARSES and that the identifiers it references RESOLVE — but
we never EVALUATE it. Runtime enforcement is delegated to a registered
evaluator or native component. This keeps "typed kinds, not free text" real
without an interpreter in the dependency-clean core.

stdlib only.
"""

from __future__ import annotations

import re

# Operators / punctuation we accept in a 0.1 expression.
_TOKEN_RE = re.compile(
    r"""
    (?P<number>\d+\.\d+|\d+)
  | (?P<ident>[A-Za-z_][A-Za-z0-9_.:]*)
  | (?P<op><=|>=|==|!=|[-+*/<>()=,])
  | (?P<ws>\s+)
    """,
    re.VERBOSE,
)

# Bareword keywords that are NOT variable references.
_KEYWORDS = frozenset({"and", "or", "not", "min", "max", "abs", "true", "false"})


class ExpressionParseError(ValueError):
    """Raised when a metis_expr string contains an unrecognised token."""


def tokenize(expr: str) -> list[tuple[str, str]]:
    """Return ``[(kind, text), ...]`` for ``expr``; raise on bad tokens."""
    tokens: list[tuple[str, str]] = []
    pos = 0
    for m in _TOKEN_RE.finditer(expr):
        if m.start() != pos:
            raise ExpressionParseError(
                f"unrecognised token at {pos} in {expr!r}: {expr[pos:m.start()]!r}"
            )
        pos = m.end()
        kind = m.lastgroup
        if kind == "ws":
            continue
        tokens.append((kind, m.group()))
    if pos != len(expr):
        raise ExpressionParseError(
            f"unrecognised token at {pos} in {expr!r}: {expr[pos:]!r}"
        )
    return tokens


def extract_references(expr: str) -> list[str]:
    """Return the identifier references in ``expr`` (keywords/functions excluded).

    A reference is an ``ident`` token that is not a keyword. ``var:foo`` and
    ``property:k`` style identifiers are returned whole.
    """
    refs: list[str] = []
    for kind, text in tokenize(expr):
        if kind == "ident" and text.lower() not in _KEYWORDS:
            refs.append(text)
    # De-dup, preserve order.
    seen: set[str] = set()
    out: list[str] = []
    for r in refs:
        if r not in seen:
            seen.add(r)
            out.append(r)
    return out


def replace_identifiers(expr: str, replacements: dict[str, str]) -> str:
    """Return ``expr`` with identifier tokens replaced by exact-token match.

    Whitespace and operators are preserved. Bare identifiers are replaced when
    they are present in ``replacements``. ``var:<id>`` tokens are also rewritten
    when ``<id>`` is present, preserving the ``var:`` prefix. Other namespaced
    identifiers such as ``property:foo`` are left untouched unless the full token
    appears in ``replacements``.
    """
    out: list[str] = []
    pos = 0
    for m in _TOKEN_RE.finditer(expr):
        if m.start() != pos:
            raise ExpressionParseError(
                f"unrecognised token at {pos} in {expr!r}: {expr[pos:m.start()]!r}"
            )
        pos = m.end()
        kind = m.lastgroup
        text = m.group()
        if kind == "ident":
            if text in replacements:
                text = replacements[text]
            elif text.startswith("var:"):
                var_id = text.split(":", 1)[1]
                if var_id in replacements:
                    text = f"var:{replacements[var_id]}"
        out.append(text)
    if pos != len(expr):
        raise ExpressionParseError(
            f"unrecognised token at {pos} in {expr!r}: {expr[pos:]!r}"
        )
    return "".join(out)
