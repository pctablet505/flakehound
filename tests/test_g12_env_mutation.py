"""G12 rule tests -- the TP/FP-guard pattern every rule must follow."""

from __future__ import annotations

import ast

from flakehound.rules.base import Confidence, FileContext
from flakehound.rules.g12_env_mutation import EnvMutation


def _ctx(source: str, name: str = "test_x.py", is_conftest: bool = False) -> FileContext:
    return FileContext(
        path=name,
        source=source,
        tree=ast.parse(source),
        is_test_file=not is_conftest,
        is_conftest=is_conftest,
    )


def _run(source: str, **kwargs):
    return list(EnvMutation().check(_ctx(source, **kwargs)))


def test_detects_bare_env_assignment_in_test():
    src = 'import os\n\ndef test_a():\n    os.environ["JAX_DISABLE_JIT"] = "1"\n'
    findings = _run(src)
    assert len(findings) == 1
    assert findings[0].rule_id == "G12"
    assert findings[0].line == 4
    assert findings[0].confidence == Confidence.HIGH


def test_detects_del_and_setdefault_and_putenv_with_no_restore():
    src = (
        "import os\n\n"
        "def test_a():\n"
        '    del os.environ["FLAG_A"]\n'
        '    os.environ.setdefault("FLAG_B", "1")\n'
        '    os.putenv("FLAG_C", "1")\n'
    )
    findings = _run(src)
    assert len(findings) == 3
    assert [f.line for f in findings] == [4, 5, 6]
    assert all(f.confidence == Confidence.HIGH for f in findings)


def test_downgrades_confidence_when_restore_exists_for_a_different_key():
    src = (
        "import os\n\n"
        "def test_a():\n"
        '    os.environ["OTHER_FLAG"] = "x"\n'
        "    try:\n"
        "        pass\n"
        "    finally:\n"
        '        os.environ["UNRELATED_KEY"] = "y"\n'
    )
    findings = _run(src)
    assert len(findings) == 1
    assert findings[0].line == 4
    assert findings[0].confidence == Confidence.MEDIUM


def test_fp_guard_monkeypatch_setenv_is_clean():
    src = 'def test_a(monkeypatch):\n    monkeypatch.setenv("FLAG", "1")\n'
    assert _run(src) == []


def test_fp_guard_fixture_try_finally_save_restore_is_clean():
    src = (
        "import os\nimport pytest\n\n"
        "@pytest.fixture\n"
        "def isolated_flag():\n"
        '    old = os.environ.get("FLAG")\n'
        '    os.environ["FLAG"] = "1"\n'
        "    try:\n"
        "        yield\n"
        "    finally:\n"
        "        if old is None:\n"
        '            os.environ.pop("FLAG", None)\n'
        "        else:\n"
        '            os.environ["FLAG"] = old\n'
    )
    assert _run(src) == []


def test_fp_guard_patch_dict_context_manager_is_clean():
    src = (
        "import os\n"
        "from unittest.mock import patch\n\n"
        "def test_a():\n"
        '    with patch.dict(os.environ, {"FLAG": "1"}):\n'
        '        os.environ["OTHER"] = "2"\n'
        '        assert os.environ["FLAG"] == "1"\n'
    )
    assert _run(src) == []


def test_fp_guard_patch_dict_decorator_is_clean():
    src = (
        "import os\n"
        "from unittest.mock import patch\n\n"
        '@patch.dict(os.environ, {"FLAG": "1"})\n'
        "def test_a():\n"
        '    os.environ["FLAG"] = "2"\n'
    )
    assert _run(src) == []


def test_fp_guard_conftest_is_excluded():
    src = 'import os\n\ndef _apply():\n    os.environ["FLAKEHOUND_TEST_ENV"] = "1"\n'
    assert _run(src, name="conftest.py", is_conftest=True) == []
