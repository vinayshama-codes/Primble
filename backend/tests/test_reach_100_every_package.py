"""Owner's rule (27 Oct 2026): a producer who answers everything the pre-form screen
asks reaches exactly 100 - on ANY package. Random synthetic packages (no customer
data, `reach100_harness.synthetic_package`) are answered through the page's own items
and write doors; every one must land on 100, with no model or network call.

The wider sweep (hundreds of packages) is `scratchpad/solve/synth.py`; this file keeps
a fixed handful in the build so a new rule without an answer fails it."""
import ast
import os
import random

import pytest

from reach100_harness import solve, solve_checked, synthetic_package, wider_package

_SEEDS = tuple(range(101, 121))


@pytest.fixture(autouse=True)
def _no_network(monkeypatch):
    def refuse(*_a, **_k):
        raise AssertionError("the reach-100 check must make no model or network call")
    import httpx
    monkeypatch.setattr(httpx.Client, "send", refuse)
    monkeypatch.setattr(httpx.AsyncClient, "send", refuse)
    monkeypatch.setenv("NARRATIVE_READER", "0")


@pytest.mark.parametrize("seed", _SEEDS)
def test_answering_everything_reaches_exactly_100(seed):
    row = synthetic_package(random.Random(seed))
    score, detail = solve(row)
    assert score == 100, (row["_kind"], row["_lines"], score, detail)
    assert not detail["not_scored"], detail["not_scored"]   # the root fixes did it, not the net


# The wider generator's edge cases (28 Oct 2026 review - each class it found is
# in tests/test_reach100_review_28oct.py): monopolistic + multi-state WC beside
# an attested no-loss with claims and no term; no lines at all; four buildings
# at one address without COPE; a multi-state new venture; split auto limits
# with no term; no COPE on a multi-state package. Read like the route, the
# numbers checked at every reading, Data Consistency picks made for real.
_WIDER_SEEDS = (301, 302, 315, 326, 331, 337)


@pytest.mark.parametrize("seed", _WIDER_SEEDS)
def test_wider_edge_cases_reach_exactly_100_and_every_reading_adds_up(seed):
    row = wider_package(random.Random(seed))
    score, problems = solve_checked(row)
    assert score == 100 and problems == [], (row["_tags"], score, problems)


_PILLAR_ITEM_FUNCTIONS = ("coverage_deduction_items", "umbrella_deduction_items", "property_gap_items")


def test_every_pillar_deduction_names_a_box_a_person_can_answer():
    """Static: every deduction a pillar item list writes with a literal fact names a
    fact `answer_routing` can answer. A new deduction without a question fails here
    instead of silently holding a score below 100."""
    from services.answer_routing import answer_mode
    path = os.path.join(os.path.dirname(__file__), "..", "services", "sqs_service.py")
    tree = ast.parse(open(path).read())
    found, bad = [], []
    for fn in [n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name in _PILLAR_ITEM_FUNCTIONS]:
        for node in ast.walk(fn):
            fact = None
            if isinstance(node, ast.Call) and getattr(node.func, "id", None) == "_add" and len(node.args) >= 3:
                fact = node.args[2]
            elif isinstance(node, ast.Dict):
                for k, v in zip(node.keys, node.values):
                    if isinstance(k, ast.Constant) and k.value == "fact":
                        fact = v
            if isinstance(fact, ast.Constant) and isinstance(fact.value, str):
                found.append(fact.value)
                if (answer_mode(fact.value) or {}).get("mode") not in ("field", "schedule", "narrative"):
                    bad.append(fact.value)
    assert len(found) >= 15, found          # the harvester must see the lists
    assert not bad, bad
