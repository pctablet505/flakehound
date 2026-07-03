"""G12: `os.environ` mutation inside a test/fixture without `monkeypatch`.

Writing directly to `os.environ` mutates process-global environment state
that outlives the function that set it -- the next test to read that key (or
a wholly unrelated test that assumes its *absence*) now depends on whichever
test ran before it in the same worker process. `monkeypatch.setenv`/
`monkeypatch.delenv` give the identical effect scoped to the fixture/test and
restore the prior value through pytest's own teardown, which still fires on a
raised exception or a fixture-level error -- a hand-rolled `try/finally`
inside the test body does not fully replicate that (nothing runs the restore
if the process is interrupted between the mutation and the `try:`).

Mined from a real ML/trading suite: raw `os.environ[...] = ...` and a
hand-rolled save/restore both coexisted densely alongside 27 files' worth of
`monkeypatch.setenv`/`delenv` and `unittest.mock.patch.dict(os.environ, ...)`
-- the true-positive and false-positive shapes below are drawn from that
corpus. Module-level mutation (import-time, before any function runs) is a
different risk shape already covered by G6; this rule only looks inside
function bodies (test functions and fixtures).
"""

from __future__ import annotations

import ast
from collections.abc import Iterable

from flakehound.rules.base import Confidence, FileContext, Finding, Rule, register

_ENV_MUTATING_METHODS = {"update", "setdefault", "pop", "clear"}
_SINGLE_KEY_METHODS = {"setdefault", "pop"}


def _dotted(node: ast.AST) -> str | None:
    parts: list[str] = []
    while isinstance(node, ast.Attribute):
        parts.append(node.attr)
        node = node.value
    if isinstance(node, ast.Name):
        parts.append(node.id)
        return ".".join(reversed(parts))
    return None


def _is_os_environ(node: ast.AST) -> bool:
    return _dotted(node) == "os.environ"


def _string_key(node: ast.expr | None) -> str | None:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    return None


def _is_patch_dict_environ_call(node: ast.AST) -> bool:
    """`patch.dict(os.environ, ...)` / `mock.patch.dict(os.environ, ...)` --
    saves and restores the *whole* dict on exit, so anything mutated in its
    scope is already safe regardless of what else the code does to it.
    """
    if not isinstance(node, ast.Call):
        return False
    dotted = _dotted(node.func)
    if dotted is None or not dotted.endswith("patch.dict"):
        return False
    return bool(node.args) and _is_os_environ(node.args[0])


def _descend(node: ast.AST) -> Iterable[ast.AST]:
    """Yield `node` and its descendants, but never cross into a nested
    function/lambda's own body -- that is a separate scope, visited on its
    own when the outer walk in `check()` reaches it directly.
    """
    yield node
    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)):
        return
    for child in ast.iter_child_nodes(node):
        yield from _descend(child)


def _own_nodes(func: ast.FunctionDef | ast.AsyncFunctionDef) -> Iterable[ast.AST]:
    for stmt in func.body:
        yield from _descend(stmt)


def _mutation(node: ast.AST) -> tuple[str | None, str] | None:
    """If `node` mutates `os.environ`, return `(literal-key-or-None, rendered-snippet)`.

    The snippet is fully rendered (the literal key substituted in when known)
    so callers never need to reconstruct message text themselves.
    """
    if isinstance(node, ast.Assign):
        for target in node.targets:
            if isinstance(target, ast.Subscript) and _is_os_environ(target.value):
                key = _string_key(target.slice)
                lhs = f"os.environ[{key!r}]" if key is not None else "os.environ[...]"
                return key, f"`{lhs} = ...`"
        return None

    if isinstance(node, ast.Delete):
        for target in node.targets:
            if isinstance(target, ast.Subscript) and _is_os_environ(target.value):
                key = _string_key(target.slice)
                lhs = f"os.environ[{key!r}]" if key is not None else "os.environ[...]"
                return key, f"`del {lhs}`"
        return None

    if isinstance(node, ast.Call):
        is_bare_putenv = isinstance(node.func, ast.Name) and node.func.id == "putenv"
        dotted = _dotted(node.func)
        if is_bare_putenv or dotted == "os.putenv":
            key = _string_key(node.args[0]) if node.args else None
            args = f"{key!r}, ..." if key is not None else "..."
            callee = "putenv" if is_bare_putenv else "os.putenv"
            return key, f"`{callee}({args})`"
        if dotted is None:
            return None
        prefix, _, attr = dotted.rpartition(".")
        if prefix == "os.environ" and attr in _ENV_MUTATING_METHODS:
            key = None
            if attr in _SINGLE_KEY_METHODS and node.args:
                key = _string_key(node.args[0])
            args = f"{key!r}, ..." if key is not None else "..."
            return key, f"`os.environ.{attr}({args})`"

    return None


def _patch_dict_guarded_ids(own: list[ast.AST]) -> set[int]:
    guarded: set[int] = set()
    for node in own:
        if not isinstance(node, (ast.With, ast.AsyncWith)):
            continue
        if not any(_is_patch_dict_environ_call(item.context_expr) for item in node.items):
            continue
        for stmt in node.body:
            for inner in _descend(stmt):
                guarded.add(id(inner))
    return guarded


def _restore_signal(own: list[ast.AST]) -> tuple[set[str], set[int], bool]:
    """Scan every `try/finally` in this function for env-restoring statements.

    Returns the set of literal keys confirmed restored, the ids of the
    restoring statements themselves (never flag the fix as the bug), and
    whether *any* restore signal exists at all (used to soften confidence
    when a restore is present but its key can't be matched statically).
    """
    restored_keys: set[str] = set()
    finally_ids: set[int] = set()
    has_signal = False
    for node in own:
        if not isinstance(node, ast.Try):
            continue
        for stmt in node.finalbody:
            for inner in _descend(stmt):
                mutation = _mutation(inner)
                if mutation is None:
                    continue
                finally_ids.add(id(inner))
                has_signal = True
                key, _ = mutation
                if key is not None:
                    restored_keys.add(key)
    return restored_keys, finally_ids, has_signal


@register
class EnvMutation(Rule):
    id = "G12"
    name = "env-mutation"
    cause = "environment/order-dependence"
    confidence = Confidence.HIGH
    fix_suggestion = (
        "use `monkeypatch.setenv(...)`/`monkeypatch.delenv(...)` -- restores the "
        "prior value through pytest's own teardown, which still runs on a raised "
        "exception or fixture error; for a `with` block, "
        "`unittest.mock.patch.dict(os.environ, {...})` is the equivalent safe form"
    )

    def check(self, ctx: FileContext) -> Iterable[Finding]:
        if ctx.is_conftest:
            return
        for node in ast.walk(ctx.tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                yield from self._check_function(ctx, node)

    def _check_function(
        self, ctx: FileContext, func: ast.FunctionDef | ast.AsyncFunctionDef
    ) -> Iterable[Finding]:
        if any(_is_patch_dict_environ_call(dec) for dec in func.decorator_list):
            return  # whole function body is save/restore-guarded

        own = list(_own_nodes(func))
        guarded_ids = _patch_dict_guarded_ids(own)
        restored_keys, finally_ids, has_restore_signal = _restore_signal(own)

        for node in own:
            mutation = _mutation(node)
            if mutation is None:
                continue
            if id(node) in finally_ids or id(node) in guarded_ids:
                continue
            key, snippet = mutation
            if key is not None and key in restored_keys:
                continue  # hand-rolled try/finally save/restore for this exact key

            confidence = Confidence.MEDIUM if has_restore_signal else None
            note = (
                "; a try/finally save-restore exists elsewhere in this function but "
                "could not be confirmed for this key"
                if has_restore_signal
                else ""
            )
            yield self.finding(
                ctx,
                node,
                f"{snippet} mutates process-global environment state with no "
                f"`monkeypatch` in scope{note}",
                confidence=confidence,
            )
