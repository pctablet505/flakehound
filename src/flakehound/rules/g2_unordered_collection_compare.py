"""G2: equality assertions on unordered-collection materializations.

Converting a `set`, a dict view, or a filesystem listing into a `list` and then
comparing it to a literal with `==` bakes in an iteration order Python does not
promise: `set` iteration order depends on hashes (and `PYTHONHASHSEED` for
str/bytes), and `os.listdir`/`glob.glob` order is filesystem/platform
dependent. The test then passes or fails on incidental order, not on outcome.
"""

from __future__ import annotations

import ast
from collections.abc import Iterable

from flakehound.rules.base import Confidence, FileContext, Finding, Rule, register

_DICT_VIEW_ATTRS = {"keys", "values", "items"}
_FS_LISTING_CALLS = {("os", "listdir"), ("glob", "glob")}


def _dotted(node: ast.AST) -> str | None:
    parts: list[str] = []
    while isinstance(node, ast.Attribute):
        parts.append(node.attr)
        node = node.value
    if isinstance(node, ast.Name):
        parts.append(node.id)
        return ".".join(reversed(parts))
    return None


def _call_dotted(node: ast.AST) -> str | None:
    if isinstance(node, ast.Call):
        return _dotted(node.func)
    return None


def _is_set_like(node: ast.AST) -> bool:
    """`{...}` set literal or a `set(...)` call."""
    if isinstance(node, ast.Set):
        return True
    return _call_dotted(node) == "set"


def _unwrap_list_call(node: ast.AST) -> ast.expr | None:
    """If `node` is `list(x)`, return `x`; otherwise None."""
    if (
        isinstance(node, ast.Call)
        and _dotted(node.func) == "list"
        and len(node.args) == 1
        and not node.keywords
    ):
        return node.args[0]
    return None


def _is_ordered_literal(node: ast.expr) -> bool:
    """A list/tuple literal with >=2 elements — order can actually be wrong."""
    return isinstance(node, (ast.List, ast.Tuple)) and len(node.elts) >= 2


def _classify(node: ast.expr) -> tuple[str, Confidence] | None:
    """If `node` is an order-unsafe collection materialization, describe why."""
    inner = _unwrap_list_call(node)

    if inner is not None and _is_set_like(inner):
        return (
            "`list(set(...))` materializes a set into a list; set iteration "
            "order is not guaranteed to be stable across runs",
            Confidence.HIGH,
        )

    if inner is not None and _call_dotted(inner) == "dict":
        return (
            "`list(dict(...))` returns the dict's keys in construction order; "
            "if that dict was built from an unordered source (a set, a kwargs "
            "merge, a parallel/async collection) the order is not guaranteed",
            Confidence.MEDIUM,
        )

    view_call = inner if inner is not None else node
    if (
        isinstance(view_call, ast.Call)
        and isinstance(view_call.func, ast.Attribute)
        and view_call.func.attr in _DICT_VIEW_ATTRS
        and not view_call.args
        and not view_call.keywords
    ):
        return (
            f"comparing `.{view_call.func.attr}()` to a list literal treats a "
            "dict view as an ordered sequence",
            Confidence.MEDIUM,
        )

    fs_call = inner if inner is not None else node
    dotted = _call_dotted(fs_call)
    if dotted is not None:
        prefix, _, attr = dotted.rpartition(".")
        if (prefix, attr) in _FS_LISTING_CALLS:
            return (
                f"`{dotted}(...)` order is filesystem/platform dependent, not "
                "guaranteed across runs or machines",
                Confidence.HIGH,
            )

    return None


@register
class UnorderedCollectionCompare(Rule):
    id = "G2"
    name = "unordered-collection-compare"
    cause = "iteration-order/nondeterminism"
    confidence = Confidence.HIGH
    fix_suggestion = (
        "sort both sides before comparing (`sorted(x) == sorted(y)`), or compare "
        "as sets/dicts directly (`set(x) == set(y)`) if order was never the point"
    )

    def check(self, ctx: FileContext) -> Iterable[Finding]:
        for node in ast.walk(ctx.tree):
            if not isinstance(node, ast.Compare):
                continue
            if len(node.ops) != 1 or not isinstance(node.ops[0], ast.Eq):
                continue
            if len(node.comparators) != 1:
                continue
            left, right = node.left, node.comparators[0]

            if _is_set_like(left) and _is_set_like(right):
                continue  # `set(...) == set(...)` / `set(...) == {...}` is the fix, not the bug

            for risky, literal in ((left, right), (right, left)):
                if not _is_ordered_literal(literal):
                    continue
                classification = _classify(risky)
                if classification is None:
                    continue
                message, confidence = classification
                yield self.finding(ctx, risky, message, confidence=confidence)
                break  # one finding per comparison
