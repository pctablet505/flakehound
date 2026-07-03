"""G8: float equality without tolerance.

`assert a == b` (or `assertEqual`) where an operand is a float literal with a
fractional part, a true-division result, or a `math`/`np` call that produces a
float is comparing IEEE-754 values for exact equality — the classic source of
"passes on my machine, fails on CI" flakiness once either side has gone
through any arithmetic (accumulated rounding, differing libm/BLAS builds,
platform FMA differences). Fix: `math.isclose`/`pytest.approx`/`np.isclose`.
"""

from __future__ import annotations

import ast
from collections.abc import Iterable

from flakehound.rules.base import Confidence, FileContext, Finding, Rule, register

_SENTINELS = {0.0, 1.0, -1.0, 0.5}

_MATH_NON_FLOAT = {
    "floor",
    "ceil",
    "trunc",
    "gcd",
    "lcm",
    "isnan",
    "isclose",
    "isfinite",
    "isinf",
    "isqrt",
    "comb",
    "factorial",
    "perm",
    "frexp",
    "modf",
}

_NP_FLOAT_CALLS = {
    "mean",
    "std",
    "var",
    "median",
    "average",
    "sum",
    "dot",
    "sqrt",
    "log",
    "log2",
    "log10",
    "exp",
    "norm",
    "ptp",
    "trace",
    "corrcoef",
}


def _dotted(node: ast.AST) -> str | None:
    parts: list[str] = []
    while isinstance(node, ast.Attribute):
        parts.append(node.attr)
        node = node.value
    if isinstance(node, ast.Name):
        parts.append(node.id)
        return ".".join(reversed(parts))
    return None


def _literal_float(node: ast.AST) -> float | None:
    """Return the value of a float literal, unwrapping a leading unary +/-."""
    if isinstance(node, ast.Constant) and isinstance(node.value, float):
        return node.value
    if (
        isinstance(node, ast.UnaryOp)
        and isinstance(node.op, ast.USub | ast.UAdd)
        and isinstance(node.operand, ast.Constant)
        and isinstance(node.operand.value, float)
    ):
        value = node.operand.value
        return -value if isinstance(node.op, ast.USub) else value
    return None


def _is_float_producing_call(node: ast.AST) -> bool:
    if not isinstance(node, ast.Call):
        return False
    dotted = _dotted(node.func)
    if dotted is None or "." not in dotted:
        return False
    root, _, _ = dotted.partition(".")
    _, _, attr = dotted.rpartition(".")
    if root == "math":
        return attr not in _MATH_NON_FLOAT
    if root in {"np", "numpy"}:
        return attr in _NP_FLOAT_CALLS
    return False


def _float_evidence(node: ast.AST) -> str | None:
    """Why this operand is suspected of being an imprecise float, if at all."""
    literal = _literal_float(node)
    if literal is not None and not literal.is_integer():
        return "a float literal with a fractional part"
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Div):
        return "a division result"
    if _is_float_producing_call(node):
        return "a float-producing math/np call"
    return None


def _is_approx_wrapped(node: ast.AST) -> bool:
    if not isinstance(node, ast.Call):
        return False
    dotted = _dotted(node.func)
    return dotted is not None and (dotted == "approx" or dotted.endswith(".approx"))


def _is_sentinel_identical_literal(left: ast.AST, right: ast.AST) -> bool:
    lv, rv = _literal_float(left), _literal_float(right)
    return lv is not None and rv is not None and lv == rv and lv in _SENTINELS


def _is_assert_equal_call(node: ast.Call) -> bool:
    return isinstance(node.func, ast.Attribute) and node.func.attr == "assertEqual"


@register
class FloatEqualityWithoutTolerance(Rule):
    id = "G8"
    name = "float-equality-without-tolerance"
    cause = "floating-point/precision"
    confidence = Confidence.HIGH
    fix_suggestion = (
        "compare with tolerance: `math.isclose(a, b, rel_tol=...)`, "
        "`assert a == pytest.approx(b)`, or `np.isclose(a, b)`"
    )

    def check(self, ctx: FileContext) -> Iterable[Finding]:
        for node in ast.walk(ctx.tree):
            pair = self._pair_from(node)
            if pair is None:
                continue
            left, right = pair
            yield from self._check_pair(ctx, node, left, right)

    @staticmethod
    def _pair_from(node: ast.AST) -> tuple[ast.AST, ast.AST] | None:
        if isinstance(node, ast.Compare) and len(node.ops) == 1 and isinstance(node.ops[0], ast.Eq):
            return node.left, node.comparators[0]
        if isinstance(node, ast.Call) and _is_assert_equal_call(node) and len(node.args) >= 2:
            return node.args[0], node.args[1]
        return None

    def _check_pair(
        self, ctx: FileContext, node: ast.AST, left: ast.AST, right: ast.AST
    ) -> Iterable[Finding]:
        if _is_approx_wrapped(left) or _is_approx_wrapped(right):
            return
        evidence = _float_evidence(left) or _float_evidence(right)
        if evidence is None:
            return
        if _is_sentinel_identical_literal(left, right):
            return
        confidence = self.confidence
        if isinstance(left, ast.Constant) and isinstance(right, ast.Constant):
            # Both sides fully static: never flaky (same result every run),
            # still worth a look but the evidence for real risk is weaker.
            confidence = Confidence.MEDIUM
        yield self.finding(
            ctx,
            node,
            f"`==` compares floats where one side is {evidence}; "
            "IEEE-754 rounding makes this brittle without a tolerance",
            confidence=confidence,
        )
