"""Orbin, round 2 test 1 (session 9fc52210, 28 Sep 2026) - two defects fixed.

1. THE PACKAGE WAS THE RECOMMENDATIONS. Generation read `selected_form_ids`
   before the route wrote this request's list, so it saw the analyze step's
   RECOMMENDED forms. ACORD 125 generated alone ticked CONTRACTORS SUPPLEMENT
   because ACORD 186 had been recommended. My round 1 test proved
   `package_form_ids` and never the ROUTE that feeds it - the seam lesson,
   again - so the gate here is a seam test over every generation entry.

2. A NARRATIVE BECAME A VERIFIED LOSS HISTORY. "There have been no losses in
   the past 5 years" (the narrative) printed FOR THE LAST 5 YEARS / TOTAL
   LOSSES $0 beside an unticked "Check if none". The checkbox and the summary
   row read two different doors; the client's 8-19-26 key forbids exactly this.
"""
from __future__ import annotations

import ast
import importlib.util
import json
import os
import sys
from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))
os.environ.setdefault("OPENAI_API_KEY", "sk-offline")

import services.pdf_service as ps                                   # noqa: E402
from services.form_service import (                                 # noqa: E402
    bind_generation_package, package_form_ids)

SCHEMA = json.loads((BACKEND / "forms_schemas" / "ACORD_125_schema.json").read_text())
_RECOMMENDED = ["ACORD_125", "ACORD_126", "ACORD_127", "ACORD_131", "ACORD_186",
                "ACORD_137_CO"]


# ═════════════════════════════════════════════════════════════════════════════
# 1. The package is what THIS request generates
# ═════════════════════════════════════════════════════════════════════════════
def test_the_package_is_the_request_not_the_recommendations():
    session = {"selected_form_ids": list(_RECOMMENDED)}      # the analyze step
    assert "ACORD_186" in package_form_ids(session, "ACORD_125")     # the defect
    assert bind_generation_package(session, ["ACORD_125"]) == ["ACORD_125"]
    assert package_form_ids(session, "ACORD_125") == ["ACORD_125"]


def test_binding_accepts_both_shapes_and_never_empties_a_package():
    session = {"selected_form_ids": ["ACORD_125"]}
    assert bind_generation_package(
        session, [{"form_id": "ACORD_125"}, "ACORD_186", "ACORD_186", " "]
    ) == ["ACORD_125", "ACORD_186"]
    assert bind_generation_package(session, []) == []
    assert session["selected_form_ids"] == ["ACORD_125", "ACORD_186"]


def _stamp(facts: dict, package) -> dict:
    session = {"selected_form_ids": list(_RECOMMENDED)}
    bind_generation_package(session, package)
    f = dict(facts, _form_id="ACORD_125", _package_form_ids=package_form_ids(session))
    mapped, unmatched, _ = ps.compute_form_gaps("ACORD_125", SCHEMA, f)
    return mapped, unmatched


def test_contractors_supplement_follows_the_generated_package():
    box = "CommercialPolicy_Attachment_ContractorsSupplementIndicator_A"
    mapped, unmatched = _stamp({"is_contractor": True}, ["ACORD_125"])
    assert not mapped.get(box) and box not in unmatched
    mapped, _ = _stamp({"is_contractor": True}, ["ACORD_125", "ACORD_186"])
    assert mapped.get(box) == "Y"


# Every generation entry, and the helper the two lite paths share.
_ENTRY_FILES = ["routes/form_routes.py", "services/form_addition.py", "worker.py"]
_GENERATORS = {"process_single_form", "shared_gap_fill"}
_BINDERS = {"bind_generation_package", "_lite_shared_gap_fill"}


def _functions_that_generate():
    for rel in _ENTRY_FILES:
        tree = ast.parse((BACKEND / rel).read_text(encoding="utf-8"))
        # TOP-LEVEL entries, judged whole: a nested `_generate_one` runs inside
        # a caller that has already bound the package.
        for node in tree.body:
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            uses = [n.lineno for n in ast.walk(node)
                    if isinstance(n, ast.Name) and n.id in _GENERATORS]
            if uses:
                yield rel, node, min(uses)


def test_every_generation_entry_binds_its_package_first():
    """THE SEAM. A path that generates before binding reads the analyze step's
    recommendations as the package - the live defect."""
    found, unbound = [], []
    for rel, fn, first_use in _functions_that_generate():
        found.append(f"{rel}:{fn.name}")
        binds = [n.lineno for n in ast.walk(fn) if isinstance(n, ast.Call)
                 and ((isinstance(n.func, ast.Name) and n.func.id in _BINDERS)
                      or (isinstance(n.func, ast.Attribute) and n.func.attr in _BINDERS))]
        if not binds or min(binds) > first_use:
            unbound.append(f"{rel}:{fn.name}")
    # the harvest itself must not be empty, or this test passes vacuously
    assert {"routes/form_routes.py:select_forms_bulk",
            "routes/form_routes.py:_lite_shared_gap_fill",
            "routes/form_routes.py:_bg_lite_generate",
            "routes/form_routes.py:lite_generate_internal",
            "worker.py:_process_form_generation_job",
            "services/form_addition.py:add_form_to_session"} <= set(found), found
    assert unbound == [], unbound


def test_the_lite_helper_binds_before_it_generates():
    src = (BACKEND / "routes/form_routes.py").read_text(encoding="utf-8")
    body = src[src.index("async def _lite_shared_gap_fill"):]
    body = body[:body.index("\nasync def ")]
    assert body.index("bind_generation_package(session, form_ids)") < \
        body.index("shared_gap_fill, session")


# ═════════════════════════════════════════════════════════════════════════════
# 2. A narrative "no losses" is not a verified loss history
# ═════════════════════════════════════════════════════════════════════════════
_ORBIN_LOSS_FACTS = {                    # the stored session, verbatim flags
    "asserts_no_known_losses": True, "narrative_states_no_losses": True,
    "has_loss_history": False, "num_claims": {"value": "0"},
    "loss_history_years": "5",
}
_SUMMARY = ("LossHistory_TotalAmount_A", "LossHistory_InformationYearCount_A")


def test_a_narrative_no_loss_prints_no_summary_and_asks_nobody_to_guess():
    mapped, unmatched = _stamp(_ORBIN_LOSS_FACTS, ["ACORD_125"])
    for box in _SUMMARY:
        assert not mapped.get(box), box
        assert box not in unmatched, f"{box} still reaches the AI gap fill"
    assert not mapped.get("LossHistory_NoPriorLossesIndicator_A")


def test_the_summary_and_the_none_box_read_one_door():
    """Both open on a genuine attestation, both stay shut on a narrative."""
    for facts, opens in ((_ORBIN_LOSS_FACTS, False),
                         (dict(_ORBIN_LOSS_FACTS, no_prior_losses=True), True)):
        verdict = ps.no_loss_attestation_verdict(facts)
        summary = ps._resolve_loss_history_summary("LossHistory_TotalAmount_A", facts)
        assert (verdict == "Yes") is opens
        assert (summary is ps._SCHED_SKIP) is opens


def test_real_losses_still_derive_the_total():
    rows = [{"date": "03/28/2024", "paid": "$4,850", "reserved_amount": "$0"}]
    assert ps._resolve_loss_history_summary(
        "LossHistory_TotalAmount_A", {"loss_history": rows}) == "$4,850"


# ═════════════════════════════════════════════════════════════════════════════
# 3. The key-free audit now sees both on the stored run's shape
# ═════════════════════════════════════════════════════════════════════════════
@pytest.fixture(scope="module")
def audit():
    spec = importlib.util.spec_from_file_location(
        "_t_audit", str(BACKEND / "scripts" / "audit_125_rules.py"))
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def _run(audit, stamped, package):
    raw = "LOSS HISTORY\nThere have been no losses in the past 5 years."
    return {r["id"]: r for r in audit.audit(stamped, {}, raw, {}, package)}


def test_audit_flags_a_converted_narrative(audit):
    res = _run(audit, {"LossHistory_TotalAmount_A": "0",
                       "LossHistory_InformationYearCount_A": "5"}, ["ACORD_125"])
    assert res["C8"]["status"] == "FAIL"
    assert res["C8"]["fail"][0][0] in _SUMMARY


def test_audit_flags_an_attachment_the_package_does_not_contain(audit):
    box = "CommercialPolicy_Attachment_ContractorsSupplementIndicator_A"
    assert _run(audit, {box: "Y"}, ["ACORD_125"])["C17"]["status"] == "FAIL"
    assert _run(audit, {box: "Y"}, ["ACORD_125", "ACORD_186"])["C17"]["status"] == "PASS"
    assert _run(audit, {box: "Y"}, [])["C17"]["status"] == "NOT EXERCISED"
