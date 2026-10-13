"""The owner's Choice Electric run `b4d18e8e` (8 Oct 2026) - three defects.

1. Adding a document crashed its AI fill: a SYNC `launch_new_document_fill`
   handed to a Starlette BackgroundTask runs in an AnyIO worker thread, where
   `asyncio.ensure_future` raises and the coroutine is dropped.
2. A document naming a DIFFERENT insured handed the applicant its identity
   (Harborline's DBA / address / FEIN / contacts / revenue / NAICS on Choice
   Electric's forms), lifting the score 38 -> 60 on another company's data.
3. `wc_payroll` was left to the model while `wc_payroll_by_state` was derived,
   so a complete class table produced a false "payroll is missing" warning and
   a 12-point Exposure deduction.
"""
import ast
import asyncio
import inspect
import pathlib

import pytest

from services import insured_scope as IS
from services.extraction_service import derive_wc_facts_from_class_rows

BACKEND = pathlib.Path(__file__).resolve().parent.parent


# ── 1. The background task must run on the event loop ────────────────────────

def test_launch_new_document_fill_is_awaitable():
    """Starlette awaits an async callable and threadpools a sync one. This must
    stay async or `asyncio.ensure_future` inside it has no loop."""
    from services import session_documents as sd
    assert inspect.iscoroutinefunction(sd.launch_new_document_fill)


def test_the_route_still_schedules_that_same_function():
    from starlette.background import BackgroundTask
    from services import session_documents as sd
    task = BackgroundTask(sd.launch_new_document_fill, "sid", {"state": "running"}, "uid")
    assert task.func is sd.launch_new_document_fill
    assert task.is_async is True          # Starlette will await, not threadpool


def test_no_sync_function_schedules_an_asyncio_task():
    """THE CLASS, pinned. A plain `def` that calls `ensure_future` /
    `create_task` works only if something happens to be on a loop thread; from
    a BackgroundTask or a threadpool it raises and silently drops the
    coroutine. Fail the build rather than find it in a live run again."""
    offenders = []
    for folder in ("services", "routes"):
        for path in (BACKEND / folder).rglob("*.py"):
            try:
                tree = ast.parse(path.read_text(encoding="utf-8"))
            except (SyntaxError, UnicodeDecodeError):
                continue
            for node in ast.walk(tree):
                if not isinstance(node, ast.FunctionDef):      # sync def only
                    continue
                for sub in ast.walk(node):
                    if not isinstance(sub, ast.Call):
                        continue
                    name = getattr(sub.func, "attr", None) or getattr(sub.func, "id", None)
                    if name in ("ensure_future", "create_task"):
                        offenders.append(f"{path.name}:{node.lineno} {node.name}()")
    assert not offenders, (
        "a SYNC function schedules an asyncio task - it will raise "
        "'no current event loop' off the loop thread: " + "; ".join(offenders))


# ── 2. Another insured's documents never become the applicant ────────────────

def _doc(name, facts, **kw):
    return {"doc_id": name, "filename": f"{name}.pdf", "facts": facts, **kw}


CHOICE = "CHOICE ELECTRIC LLC"
HARBOR = "HARBORLINE PLUMBING & MECHANICAL, LLC"


def _package():
    """The owner's run, reduced: Choice's decs state no identity (redacted),
    Harborline's dec states all of it."""
    facts = {
        "applicant_name": {"value": CHOICE},
        "dba_name": {"value": "HARBORLINE MECHANICAL", "source": "ai"},
        "fein": {"value": "91-4478123", "source": "ai"},
        "mailing_address": {"value": "P.O. BOX 11820, TACOMA, WA 98411", "source": "ai"},
        "total_revenue": {"value": "$6,650,000", "source": "ai"},
        "naics_code": {"value": "238220", "source": "ai"},
        "occupancy_type": {"value": "Office / fabrication shop", "source": "ai"},
    }
    docs = [
        _doc("choice_package", {"applicant_name": {"value": CHOICE}}),
        _doc("harborline", {
            "applicant_name": {"value": HARBOR},
            "dba_name": {"value": "HARBORLINE MECHANICAL"},
            "fein": {"value": "91-4478123"},
            "mailing_address": {"value": "P.O. BOX 11820, TACOMA, WA 98411"},
            "total_revenue": {"value": "$6,650,000"},
            "naics_code": {"value": "238220"},
            "occupancy_type": {"value": "Office / fabrication shop"},
        }),
    ]
    return facts, docs


def test_the_other_companys_identity_is_dropped():
    facts, docs = _package()
    removed = IS.drop_other_insured_identity(facts, docs)
    for key in ("dba_name", "fein", "mailing_address", "total_revenue",
                "naics_code", "occupancy_type"):
        assert key not in facts, f"{key} is Harborline's and must not be the applicant's"
    assert set(removed) >= {"dba_name", "fein", "mailing_address"}


def test_the_applicants_own_name_is_never_touched():
    """The merge and the Data Consistency picker own that conflict, and it is
    the evidence this module reasons from."""
    facts, docs = _package()
    IS.drop_other_insured_identity(facts, docs)
    assert facts["applicant_name"]["value"] == CHOICE


def test_a_value_the_applicants_own_document_also_states_is_kept():
    facts, docs = _package()
    docs[0]["facts"]["mailing_address"] = {"value": "1200 Elm St, Denver, CO"}
    facts["mailing_address"] = {"value": "1200 Elm St, Denver, CO", "source": "ai"}
    IS.drop_other_insured_identity(facts, docs)
    assert facts["mailing_address"]["value"] == "1200 Elm St, Denver, CO"


def test_a_person_s_answer_is_never_scoped_away():
    """Producer / client provenance is a decision, not a document read."""
    facts, docs = _package()
    facts["total_revenue"] = {"value": "$6,650,000", "source": "producer"}
    IS.drop_other_insured_identity(facts, docs)
    assert facts["total_revenue"]["value"] == "$6,650,000"


def test_one_insured_package_is_untouched():
    """ZERO BLAST RADIUS on every ordinary submission."""
    facts = {"applicant_name": {"value": CHOICE},
             "fein": {"value": "84-2210987", "source": "ai"},
             "mailing_address": {"value": "1200 Elm St, Denver, CO", "source": "ai"}}
    docs = [_doc("a", {"applicant_name": {"value": CHOICE}, "fein": {"value": "84-2210987"}}),
            _doc("b", {"applicant_name": {"value": "Choice Electric, L.L.C."},
                       "mailing_address": {"value": "1200 Elm St, Denver, CO"}})]
    before = dict(facts)
    assert IS.drop_other_insured_identity(facts, docs) == []
    assert facts == before


def test_a_document_naming_no_insured_is_never_judged():
    """Absence is not a verdict - a loss run or narrative contributes as before."""
    facts = {"applicant_name": {"value": CHOICE},
             "total_revenue": {"value": "$2,500,000", "source": "ai"}}
    docs = [_doc("choice", {"applicant_name": {"value": CHOICE}}),
            _doc("loss_run", {"total_revenue": {"value": "$2,500,000"}})]
    assert IS.drop_other_insured_identity(facts, docs) == []
    assert facts["total_revenue"]["value"] == "$2,500,000"


def test_an_excluded_document_carries_no_weight():
    facts, docs = _package()
    docs[1]["excluded"] = True
    assert IS.drop_other_insured_identity(facts, docs) == []


def test_coverage_facts_are_not_in_scope():
    """Limits / premiums are line-scoped by `coverage_lines` and `lob_canon`;
    a second owner of that question would be the defect class, not a fix."""
    for key in ("gl_each_occurrence", "umbrella_limit", "auto_liability_limit",
                "property_building_value", "wc_class_codes", "coverage_lines"):
        assert key not in IS.APPLICANT_SCOPED_FACTS


@pytest.mark.parametrize("bad", [None, {}, {"applicant_name": None}])
def test_never_raises_on_an_odd_package(bad):
    assert IS.drop_other_insured_identity(dict(bad or {}), None) == []
    assert IS.facts_only_another_insured_states(bad, [{"not": "a doc"}]) == {}


# ── 3. The WC payroll scalar the scorer reads ────────────────────────────────

def _wc_rows():
    """The owner's ACORD 130, verbatim: 2,000,000 + 426,500 + 200,000."""
    return [
        {"code": "5190", "state": "CO", "payroll": "2,000,000"},
        {"code": "8742", "state": "CO", "payroll": "426,500"},
        {"code": "8810", "state": "CO", "payroll": "200,000"},
    ]


def test_wc_payroll_is_derived_from_a_complete_class_table():
    facts = {"wc_class_codes": _wc_rows()}
    assert derive_wc_facts_from_class_rows(facts) is True
    assert facts["wc_payroll"]["value"] == "$2,626,500"
    assert facts["wc_payroll"]["evidence_state"] == "derived"


def test_the_scorer_stops_charging_for_a_payroll_we_hold():
    """The whole point: a false warning and a 12-point Exposure deduction on a
    package whose payroll is printed on our own ACORD 130."""
    from services.sqs_service import _calculate_exposure_consistency, evaluate_stops
    flags = {"has_workers_comp": True}
    without = {"wc_class_codes": _wc_rows()}          # the 8 Oct behaviour
    with_it = {"wc_class_codes": _wc_rows()}
    derive_wc_facts_from_class_rows(with_it)
    before, _ = _calculate_exposure_consistency(without, flags, [], [])
    after, _ = _calculate_exposure_consistency(with_it, flags, [], [])
    assert after > before
    _h, soft = evaluate_stops(with_it, flags)
    assert not [m for m in soft if "payroll is missing" in str(m)]


def test_a_stated_payroll_always_stands():
    facts = {"wc_class_codes": _wc_rows(),
             "wc_payroll": {"value": "$3,000,000", "source": "ai"}}
    derive_wc_facts_from_class_rows(facts)
    assert facts["wc_payroll"]["value"] == "$3,000,000"


def test_a_producers_payroll_always_stands():
    facts = {"wc_class_codes": _wc_rows(),
             "wc_payroll": {"value": "$9,000", "source": "producer"}}
    derive_wc_facts_from_class_rows(facts)
    assert facts["wc_payroll"]["value"] == "$9,000"


def test_an_edited_table_never_leaves_a_stale_total():
    facts = {"wc_class_codes": _wc_rows()}
    derive_wc_facts_from_class_rows(facts)
    facts["wc_class_codes"][0]["payroll"] = "1,000,000"
    derive_wc_facts_from_class_rows(facts)
    assert facts["wc_payroll"]["value"] == "$1,626,500"


def test_a_partial_table_derives_nothing():
    """A total built from half the rows is a wrong value, not a derived one."""
    rows = _wc_rows()
    rows[1].pop("payroll")
    facts = {"wc_class_codes": rows}
    derive_wc_facts_from_class_rows(facts)
    assert not facts.get("wc_payroll")


def test_rows_that_stop_supporting_it_retire_it():
    facts = {"wc_class_codes": _wc_rows()}
    derive_wc_facts_from_class_rows(facts)
    assert facts["wc_payroll"]["value"] == "$2,626,500"
    facts["wc_class_codes"] = []
    derive_wc_facts_from_class_rows(facts)
    assert not facts.get("wc_payroll")


def test_multi_state_rows_sum_across_states():
    rows = _wc_rows() + [{"code": "5190", "state": "WY", "payroll": "100,000"}]
    facts = {"wc_class_codes": rows}
    derive_wc_facts_from_class_rows(facts)
    assert facts["wc_payroll"]["value"] == "$2,726,500"
    assert set(facts["wc_payroll_by_state"]["value"]) == {"CO", "WY"}
