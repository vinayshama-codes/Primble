"""A top-level name defined twice in one service module silently replaces the
first definition for every earlier reader. Live-run-11 review (16 Sep 2026): a
new `_EXCLUSION_TITLE_RE` in pdf_service replaced the evidence gate's own
pattern of that name, and exclusion titles could ground a "Yes" again. The
suite caught it only because the gate had its own tests; this catches the class.
"""
import ast
import collections
import os

import pytest

BACKEND = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _top_level_definitions(path):
    with open(path, encoding="utf-8") as fh:
        tree = ast.parse(fh.read())
    seen = collections.defaultdict(list)
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            names = [node.name]
        elif isinstance(node, ast.Assign):
            names = [t.id for t in node.targets if isinstance(t, ast.Name)]
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            names = [node.target.id]
        else:
            names = []
        for n in names:
            seen[n].append(node.lineno)
    return seen


@pytest.mark.parametrize("module", ["pdf_service.py", "extraction_service.py"])
def test_no_top_level_name_is_defined_twice(module):
    seen = _top_level_definitions(os.path.join(BACKEND, "services", module))
    assert {n: lines for n, lines in seen.items() if len(lines) > 1} == {}
