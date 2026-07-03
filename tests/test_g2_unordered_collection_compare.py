"""G2 rule tests — the TP/FP-guard pattern every rule must follow."""

from __future__ import annotations

import ast

from flakehound.rules.base import Confidence, FileContext
from flakehound.rules.g2_unordered_collection_compare import UnorderedCollectionCompare


def _ctx(source: str, name: str = "test_x.py") -> FileContext:
    return FileContext(
        path=name,
        source=source,
        tree=ast.parse(source),
        is_test_file=True,
        is_conftest=False,
    )


def _run(source: str):
    return list(UnorderedCollectionCompare().check(_ctx(source)))


def test_detects_list_of_set_compared_to_literal():
    src = "def test_a():\n    x = {3, 1, 2}\n    assert list(set(x)) == [1, 2, 3]\n"
    findings = _run(src)
    assert len(findings) == 1
    assert findings[0].rule_id == "G2"
    assert findings[0].line == 3
    assert findings[0].confidence == Confidence.HIGH


def test_detects_os_listdir_compared_to_literal_without_sorted():
    src = "import os\ndef test_a():\n    assert os.listdir('.') == ['a.txt', 'b.txt']\n"
    findings = _run(src)
    assert len(findings) == 1
    assert findings[0].line == 3
    assert findings[0].confidence == Confidence.HIGH


def test_detects_dict_values_as_list_downgraded_to_medium():
    src = "def test_a(d):\n    assert list(d.values()) == [1, 2]\n"
    findings = _run(src)
    assert len(findings) == 1
    assert findings[0].line == 2
    assert findings[0].confidence == Confidence.MEDIUM


def test_detects_list_of_dict_ctor_downgraded_to_medium():
    src = "def test_a(pairs):\n    assert list(dict(pairs)) == ['a', 'b']\n"
    findings = _run(src)
    assert len(findings) == 1
    assert findings[0].confidence == Confidence.MEDIUM


def test_fp_guard_sorted_wrapped_is_clean():
    src = "import os\ndef test_a():\n    assert sorted(os.listdir('.')) == ['a.txt', 'b.txt']\n"
    assert _run(src) == []


def test_fp_guard_set_equals_set_is_clean():
    src = "def test_a(x, y):\n    assert set(x) == set(y)\n"
    assert _run(src) == []


def test_fp_guard_set_equals_set_literal_is_clean():
    src = "def test_a(x):\n    assert set(x) == {1, 2, 3}\n"
    assert _run(src) == []


def test_fp_guard_single_element_is_clean():
    src = "def test_a(x):\n    assert list(set(x)) == [1]\n"
    assert _run(src) == []
