"""G11 rule tests — the TP/FP-guard pattern every rule must follow."""

from __future__ import annotations

import ast

from flakehound.rules.base import Confidence, FileContext
from flakehound.rules.g11_leaked_threads_timers import LeakedThreadsTimers


def _ctx(source: str, name: str = "test_x.py") -> FileContext:
    return FileContext(
        path=name,
        source=source,
        tree=ast.parse(source),
        is_test_file=True,
        is_conftest=False,
    )


def _run(source: str):
    return list(LeakedThreadsTimers().check(_ctx(source)))


def test_detects_thread_started_without_join():
    src = (
        "import threading\n"
        "\n"
        "def test_leak():\n"
        "    t = threading.Thread(target=lambda: None)\n"
        "    t.start()\n"
    )
    findings = _run(src)
    assert len(findings) == 1
    assert findings[0].rule_id == "G11"
    assert findings[0].line == 5


def test_detects_timer_without_cancel():
    src = (
        "import threading\n"
        "\n"
        "def test_timer_leak():\n"
        "    timer = threading.Timer(5.0, lambda: None)\n"
        "    timer.start()\n"
    )
    findings = _run(src)
    assert len(findings) == 1
    assert findings[0].line == 5


def test_detects_process_without_join_or_terminate():
    src = (
        "import multiprocessing\n"
        "\n"
        "def test_process_leak():\n"
        "    p = multiprocessing.Process(target=lambda: None)\n"
        "    p.start()\n"
    )
    findings = _run(src)
    assert len(findings) == 1
    assert findings[0].line == 5


def test_detects_executor_without_context_manager_or_shutdown():
    src = (
        "from concurrent.futures import ThreadPoolExecutor\n"
        "\n"
        "def test_executor_leak():\n"
        "    ex = ThreadPoolExecutor(max_workers=2)\n"
        "    ex.submit(lambda: None)\n"
    )
    findings = _run(src)
    assert len(findings) == 1
    assert findings[0].line == 4


def test_detects_inline_thread_never_bound_to_a_name():
    src = (
        "import threading\n"
        "\n"
        "def test_inline_leak():\n"
        "    threading.Thread(target=lambda: None).start()\n"
    )
    findings = _run(src)
    assert len(findings) == 1
    assert findings[0].line == 4


def test_daemon_thread_without_join_is_downgraded_to_advisory():
    src = (
        "import threading\n"
        "\n"
        "def test_daemon_no_join():\n"
        "    t = threading.Thread(target=lambda: None, daemon=True)\n"
        "    t.start()\n"
    )
    findings = _run(src)
    assert len(findings) == 1
    assert findings[0].confidence == Confidence.ADVISORY


def test_fp_guard_executor_context_manager_is_clean():
    src = (
        "from concurrent.futures import ThreadPoolExecutor\n"
        "\n"
        "def test_executor_cm():\n"
        "    with ThreadPoolExecutor(max_workers=2) as ex:\n"
        "        ex.submit(lambda: None)\n"
    )
    assert _run(src) == []


def test_fp_guard_daemon_thread_joined_is_clean():
    src = (
        "import threading\n"
        "\n"
        "def test_daemon_joined():\n"
        "    t = threading.Thread(target=lambda: None, daemon=True)\n"
        "    t.start()\n"
        "    t.join(timeout=5.0)\n"
    )
    assert _run(src) == []


def test_fp_guard_start_join_loops_over_thread_list_is_clean():
    src = (
        "import threading\n"
        "\n"
        "def test_thread_pool():\n"
        "    threads = [threading.Thread(target=lambda: None) for _ in range(4)]\n"
        "    for t in threads:\n"
        "        t.start()\n"
        "    for t in threads:\n"
        "        t.join(timeout=5.0)\n"
    )
    assert _run(src) == []


def test_fp_guard_fixture_yield_then_join_teardown_is_clean():
    src = (
        "import threading\n"
        "import pytest\n"
        "\n"
        "@pytest.fixture\n"
        "def worker():\n"
        "    t = threading.Thread(target=lambda: None)\n"
        "    t.start()\n"
        "    yield t\n"
        "    t.join(timeout=5.0)\n"
    )
    assert _run(src) == []


def test_fp_guard_addfinalizer_registered_is_clean():
    src = (
        "import threading\n"
        "\n"
        "def test_addfinalizer(request):\n"
        "    t = threading.Thread(target=lambda: None)\n"
        "    t.start()\n"
        "    request.addfinalizer(t.join)\n"
    )
    assert _run(src) == []
