"""G11: threads/timers/processes/executors started but never cleaned up.

A `threading.Thread`/`threading.Timer`/`multiprocessing.Process`/
`concurrent.futures` executor that is started but never joined, cancelled,
terminated, or shut down can outlive the test that created it: it leaks into
later tests sharing the same worker process (state mutation, contention for
shared resources), or leaves teardown hanging on a `pytest-timeout` kill. The
reference corpus mined for this rule shows this is usually paired with a
`time.sleep()` used as an (unreliable) synchronization proxy in place of a
real join — see G3 — and that the dominant safe idiom holds threads in a
list/collection (`threads = [Thread(...) for _ in range(n)]`) rather than a
single name, so the check must look at the whole function body, not just the
line immediately after `.start()`.
"""

from __future__ import annotations

import ast
from collections.abc import Iterable

from flakehound.rules.base import Confidence, FileContext, Finding, Rule, register

_KIND_BY_CTOR = {
    "Thread": "thread",
    "Timer": "timer",
    "Process": "process",
    "ThreadPoolExecutor": "executor",
    "ProcessPoolExecutor": "executor",
}

_CLEANUP_METHODS = {
    "thread": {"join"},
    "timer": {"cancel", "join"},
    "process": {"join", "terminate"},
    "executor": {"shutdown"},
}

_ACTION_BY_KIND = {
    "thread": "`.join()`-ed",
    "timer": "`.cancel()`-ed",
    "process": "`.join()`/`.terminate()`-ed",
    "executor": "used as a context manager or `.shutdown()`-ed",
}

_FIX_BY_KIND = {
    "thread": "join it with a timeout in a teardown/finalizer: `t.join(timeout=5.0)`",
    "timer": "cancel it in a teardown/finalizer: `timer.cancel()`",
    "process": "join or terminate it with a timeout in a teardown/finalizer: `p.join(timeout=5.0)`",
    "executor": (
        "use it as a context manager (`with ThreadPoolExecutor() as ex:`) or "
        "call `.shutdown(wait=True)` in a teardown"
    ),
}


def _ctor_kind(func: ast.AST) -> str | None:
    if isinstance(func, ast.Attribute):
        name = func.attr
    elif isinstance(func, ast.Name):
        name = func.id
    else:
        return None
    return _KIND_BY_CTOR.get(name)


def _is_daemon_true(call: ast.Call) -> bool:
    for kw in call.keywords:
        if kw.arg == "daemon" and isinstance(kw.value, ast.Constant) and kw.value.value is True:
            return True
    return False


def _iter_restricted(node: ast.AST) -> Iterable[ast.AST]:
    """Yield ``node`` and every descendant without crossing into a nested
    function/class/lambda scope — keeps "same function" checks honest."""
    stack = [node]
    while stack:
        current = stack.pop()
        yield current
        if current is not node and isinstance(
            current, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda, ast.ClassDef)
        ):
            continue
        stack.extend(ast.iter_child_nodes(current))


def _own_scope_nodes(func: ast.FunctionDef | ast.AsyncFunctionDef) -> list[ast.AST]:
    out: list[ast.AST] = []
    for stmt in func.body:
        out.extend(_iter_restricted(stmt))
    return out


def _is_method_call_on(call: ast.Call, name: str, methods: set[str]) -> bool:
    func = call.func
    return (
        isinstance(func, ast.Attribute)
        and isinstance(func.value, ast.Name)
        and func.value.id == name
        and func.attr in methods
    )


def _find_direct_call(nodes: list[ast.AST], name: str, methods: set[str]) -> ast.Call | None:
    for node in nodes:
        if isinstance(node, ast.Call) and _is_method_call_on(node, name, methods):
            return node
    return None


def _find_container_call(
    nodes: list[ast.AST], container_name: str, methods: set[str]
) -> ast.Call | None:
    for node in nodes:
        if (
            isinstance(node, ast.For)
            and isinstance(node.target, ast.Name)
            and isinstance(node.iter, ast.Name)
            and node.iter.id == container_name
        ):
            loop_var = node.target.id
            for inner in _iter_restricted(node):
                if isinstance(inner, ast.Call) and _is_method_call_on(inner, loop_var, methods):
                    return inner
        elif isinstance(node, (ast.ListComp, ast.GeneratorExp, ast.SetComp)):
            for gen in node.generators:
                if (
                    isinstance(gen.iter, ast.Name)
                    and gen.iter.id == container_name
                    and isinstance(gen.target, ast.Name)
                    and isinstance(node.elt, ast.Call)
                    and _is_method_call_on(node.elt, gen.target.id, methods)
                ):
                    return node.elt
    return None


def _context_managed(nodes: list[ast.AST], name: str) -> bool:
    for node in nodes:
        if isinstance(node, (ast.With, ast.AsyncWith)):
            for item in node.items:
                if isinstance(item.context_expr, ast.Name) and item.context_expr.id == name:
                    return True
    return False


def _has_finalizer_reference(nodes: list[ast.AST], name: str) -> bool:
    """True if ``name`` is referenced anywhere inside a `*.addfinalizer(...)`
    call's arguments — covers `request.addfinalizer(t.join)` and
    `request.addfinalizer(lambda: t.join(timeout=5))` alike."""
    for node in nodes:
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "addfinalizer"
        ):
            for arg in node.args:
                for sub in ast.walk(arg):
                    if isinstance(sub, ast.Name) and sub.id == name:
                        return True
    return False


@register
class LeakedThreadsTimers(Rule):
    id = "G11"
    name = "leaked-threads-timers"
    cause = "concurrency/resource-leak"
    confidence = Confidence.MEDIUM
    fix_suggestion = (
        "join/cancel/terminate with a timeout in a teardown or finalizer "
        "(`t.join(timeout=5.0)`, `timer.cancel()`, `p.join(timeout=5.0)`), or use "
        "executors as a context manager (`with ThreadPoolExecutor() as ex:`) / "
        "call `.shutdown(wait=True)`"
    )

    def check(self, ctx: FileContext) -> Iterable[Finding]:
        for func in ast.walk(ctx.tree):
            if not isinstance(func, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            yield from self._check_function(ctx, func)

    def _check_function(
        self, ctx: FileContext, func: ast.FunctionDef | ast.AsyncFunctionDef
    ) -> Iterable[Finding]:
        nodes = _own_scope_nodes(func)

        # Named bindings: `x = Thread(...)`, `xs = [Thread(...) for _ in range(n)]`,
        # `xs = [Thread(...), Thread(...)]`.
        for node in nodes:
            if not isinstance(node, ast.Assign):
                continue
            if len(node.targets) != 1 or not isinstance(node.targets[0], ast.Name):
                continue
            name = node.targets[0].id
            value = node.value

            if isinstance(value, ast.Call):
                kind = _ctor_kind(value.func)
                if kind is not None:
                    yield from self._evaluate(ctx, nodes, name, kind, value, is_container=False)
            elif isinstance(value, (ast.ListComp, ast.GeneratorExp, ast.SetComp)):
                elt = value.elt
                if isinstance(elt, ast.Call):
                    kind = _ctor_kind(elt.func)
                    if kind is not None:
                        yield from self._evaluate(ctx, nodes, name, kind, elt, is_container=True)
            elif isinstance(value, (ast.List, ast.Tuple)):
                for elt in value.elts:
                    if isinstance(elt, ast.Call):
                        kind = _ctor_kind(elt.func)
                        if kind is not None:
                            yield from self._evaluate(
                                ctx, nodes, name, kind, elt, is_container=True
                            )
                            break

        # Constructed and started inline, never bound to a name at all: e.g.
        # `threading.Thread(target=fn).start()` — impossible to ever clean up.
        for node in nodes:
            if not isinstance(node, ast.Call):
                continue
            if not (isinstance(node.func, ast.Attribute) and node.func.attr == "start"):
                continue
            inner = node.func.value
            if not isinstance(inner, ast.Call):
                continue
            kind = _ctor_kind(inner.func)
            if kind is None or kind == "executor":
                continue
            yield self.finding(
                ctx,
                node,
                f"a `{kind}` is constructed and started inline without ever being "
                "bound to a name — it can never be joined, cancelled, or cleaned "
                "up in a finalizer",
                fix=_FIX_BY_KIND[kind],
            )

    def _evaluate(
        self,
        ctx: FileContext,
        nodes: list[ast.AST],
        name: str,
        kind: str,
        ctor_call: ast.Call,
        is_container: bool,
    ) -> Iterable[Finding]:
        methods = _CLEANUP_METHODS[kind]
        finder = _find_container_call if is_container else _find_direct_call

        if kind == "executor":
            if _context_managed(nodes, name):
                return
            start_node: ast.AST | None = ctor_call
        else:
            start_node = finder(nodes, name, {"start"})
            if start_node is None:
                return  # constructed but never started: nothing can leak

        if finder(nodes, name, methods) is not None:
            return
        if _has_finalizer_reference(nodes, name):
            return

        confidence = None
        if kind == "thread" and not is_container and _is_daemon_true(ctor_call):
            # A daemon thread dies with the process; still worth flagging (it
            # can leak state into later tests in the same worker), but the
            # static evidence for a *hang* risk is weaker, so downgrade.
            confidence = Confidence.ADVISORY

        what = f"`{name}` (a collection of {kind}s)" if is_container else f"`{name}` ({kind})"
        yield self.finding(
            ctx,
            start_node,
            f"{what} is started but never {_ACTION_BY_KIND[kind]}, and no "
            "finalizer/teardown cleanup was found in this function — it can "
            "outlive the test, leak into later tests, or hang teardown",
            fix=_FIX_BY_KIND[kind],
            confidence=confidence,
        )
