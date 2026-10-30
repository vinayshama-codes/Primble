"""GLOBAL RULE G18 (owner, 30 Oct 2026): on a package whose every package item is
done, answering every card a form lists takes THAT form to exactly 100 - any form,
any package. A deduction with no card is a dead end (Choice Electric live 6823e106:
ACORD 28 at 73 and the excess 131 at 98 with nothing to answer; every ACORD 101 at
87 on a phantom fact). Random packages from the contract harness, solved to 100,
then all 17 forms scored and their own cards answered with the plan's own sample
answers (`review_plan.probe_value`)."""
import glob
import os
import random

import pytest

import reach100_harness as H
from services import sqs_service as S
from services import review_plan as RP

_FORMS = sorted(os.path.basename(p).replace("_schema.json", "")
                for p in glob.glob(os.path.join(os.path.dirname(__file__), "..", "forms_schemas",
                                                "ACORD_*_schema.json")))
_SEEDS = (5001, 5004, 5006, 5009, 5013, 5017, 5020, 5027, 5033, 5039)


def _score(row, fid):
    st = __import__("services.stops_now", fromlist=["stops_now"]).stops_now(
        row, [fid], pre_form=False, facts=row["facts"], flags=row["flags"])
    return S.calculate_sqs_from_facts(
        facts=row["facts"], flags=row["flags"], selected_form_ids=[fid],
        hard_stops=st["form_hard"], soft_stops=st["form_soft"], tier2_score=100, form_id=fid,
        session_data=row, cross_issues_full=st["cross_issues"])


def _narrative_covering_every_topic() -> str:
    """What a producer writes into a narrative card that names its missing
    topics: a sentence on each - two of each topic's own signal phrases (the
    scorer credits two distinct signals), plus the depth signals."""
    parts = []
    for table in (S._NARRATIVE_SCORE_SIGNALS, S._NARRATIVE_SUBSTANCE_SIGNALS):
        for _k, sigs in table.items():
            parts.append("; ".join(list(sigs)[:2]) + ".")
    return " ".join(parts)


def _answer(row, field):
    from services.answer_routing import answer_mode
    if answer_mode(field, row["facts"]).get("mode") == "narrative":
        row["facts"][field] = {"value": _narrative_covering_every_topic(), "source": "producer",
                               "confidence": "filled"}
        return True
    val = RP.probe_value(field, row["facts"], row)
    if val in (None, ""):
        return False
    row["facts"][field] = {"value": val, "source": "producer", "confidence": "filled"}
    return True


@pytest.mark.parametrize("seed", _SEEDS)
def test_answering_a_forms_cards_reaches_100_on_every_form(seed):
    row = H.contract_package(random.Random(seed))
    final, _problems, row = H.solve_contract(row, order="page", rnd=random.Random(seed), every_step=False)
    assert final == 100
    stuck = []
    for fid in _FORMS:
        r = {**row, "facts": dict(row["facts"]), "flags": dict(row["flags"])}
        q = _score(r, fid)
        for _ in range(4):
            if (q.get("raw_sqs_score") or 0) >= 100:
                break
            moved = False
            for rec in q.get("recommendations") or []:
                f = (rec or {}).get("field")
                # A narrative card asks for MORE text on remarks that exist; a
                # field card for a box still empty.
                if f and (rec.get("answer_mode") == "narrative" or not S._answered(r["facts"], f)):
                    moved = _answer(r, f) or moved
            if not moved:
                break
            q = _score(r, fid)
        if (q.get("raw_sqs_score") or 0) < 100:
            stuck.append((fid, q.get("raw_sqs_score"),
                          {k: v for k, v in (q.get("breakdown") or {}).items() if isinstance(v, (int, float)) and v < 100},
                          [x.get("field") for x in q.get("recommendations") or []]))
    assert stuck == [], (row["_tags"], stuck)


def test_every_fact_a_forms_checks_read_is_declared():
    """One declaration, two readers: every `_fv(facts, "x")` inside a form's own
    `fid == "ACORD_N"` branch of `calculate_sqs` is in that form's
    `FORM_FIELD_INVENTORY` (or an either-or partner of one) - else the card net
    cannot offer a card for it and the form has a dead end."""
    import ast
    src = open(os.path.join(os.path.dirname(__file__), "..", "services", "sqs_service.py")).read()
    fn = next(n for n in ast.walk(ast.parse(src)) if isinstance(n, ast.FunctionDef) and n.name == "calculate_sqs")
    alts = {x for g in S._EITHER_OR_FACTS for x in g}
    missing = {}
    for n in ast.walk(fn):
        if (isinstance(n, ast.If) and isinstance(n.test, ast.Compare) and isinstance(n.test.left, ast.Name)
                and n.test.left.id == "fid" and n.test.comparators
                and isinstance(n.test.comparators[0], ast.Constant)):
            fid = n.test.comparators[0].value
            inv = set(S.FORM_FIELD_INVENTORY.get(fid) or [])
            for b in n.body:
                for m in ast.walk(b):
                    if (isinstance(m, ast.Call) and getattr(m.func, "id", None) == "_fv" and len(m.args) >= 2
                            and isinstance(m.args[1], ast.Constant)):
                        f = m.args[1].value
                        if f not in inv and not (f in alts and any(f in g and inv & set(g) for g in S._EITHER_OR_FACTS)):
                            missing.setdefault(fid, set()).add(f)
    assert missing == {}, missing
