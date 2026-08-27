"""test_h2_readiness_presentation.py - V1 H2, client section 7 (2026-08-27).

Client: the early information-gathering screen "can blur SQS, submission
status and information-gathering progress" by leading with a big percentage.
V1 decision: no numeric percentage on that screen; show the qualitative status
of the CURRENT SQS band and, separately, what still needs attention.

What the code did: printed `tier2_score` (the Tier 2 completeness ratio - one
category of one pillar) as "Submission Readiness NN%". A 100% Tier 2 beside
12 warnings. The fix reads the STATUS LABEL off the one package scorer, run on
the facts as they stand, and lists the Tier 1 + Tier 2 checklist as "in place"
/ "missing" from the same item lists the score is built from.

Sections:
  1. key_details is the score's own checklist, split - never a second copy
  2. check_tier1 / check_tier2 are byte-identical after the refactor (C3 pins)
  3. the pre-generation package score: one door, C75 demotion, withholding,
     failure -> None with the session named, persisted score once forms exist
  4. every pre-form response goes through the one helper (AST)
"""
import ast
import io
import logging
import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from services import sqs_service as sq                           # noqa: E402

FULL_T1 = {
    "producer_name": "Best Agency", "applicant_name": "Acme LLC",
    "mailing_address": "1 Main St, Denver, CO 80202", "effective_date": "01/01/2027",
    "lines_of_business": "General Liability", "entity_type": "LLC",
    "contact_phone": "303-555-0100",
}
FULL_T2 = {
    "fein": "12-3456789", "operations_description": "Electrical contracting",
    "total_revenue": "$1,200,000", "num_employees": "12",
    "years_in_business": "8", "naics_code": "238210",
}
ALL_T1_LABELS = list(sq.TIER1_FIELDS.values()) + ["Contact information"]
ALL_T2_LABELS = [
    "FEIN / Tax ID", "Operations description", "Annual revenue",
    "Number of employees", "Years in business", "NAICS or SIC industry code",
]


def _na(value_state="not_applicable"):
    """The live envelope answer_semantics writes for an answered N/A (C3-D)."""
    return {"value": "", "value_state": value_state, "source": "producer"}


# ── 1. key_details IS the checklist, split ───────────────────────────────────

def test_key_details_missing_is_exactly_the_scores_missing_lists():
    facts = {**FULL_T1, "fein": "12-3456789"}
    _, t1_missing = sq.check_tier1(facts, {})
    _, t2_missing = sq.check_tier2(facts, {})
    kd = sq.key_details(facts, {})
    assert kd["missing"] == list(t1_missing) + list(t2_missing)
    assert t1_missing == []
    assert "FEIN / Tax ID" in kd["satisfied"]
    assert "Annual revenue" in kd["missing"]


def test_satisfied_and_missing_partition_the_applicable_checklist():
    facts = {**FULL_T1, **FULL_T2}
    del facts["num_employees"]
    kd = sq.key_details(facts, {})
    assert set(kd["satisfied"]) & set(kd["missing"]) == set()
    assert kd["satisfied"] + kd["missing"] != []
    assert sorted(kd["satisfied"] + kd["missing"]) == sorted(ALL_T1_LABELS + ALL_T2_LABELS)
    assert kd["missing"] == ["Number of employees"]


def test_everything_present_means_nothing_missing():
    kd = sq.key_details({**FULL_T1, **FULL_T2}, {})
    assert kd["missing"] == []
    assert sorted(kd["satisfied"]) == sorted(ALL_T1_LABELS + ALL_T2_LABELS)


def test_nothing_present_means_nothing_in_place():
    kd = sq.key_details({}, {})
    assert kd["satisfied"] == []
    assert kd["missing"] == ALL_T1_LABELS + ALL_T2_LABELS


def test_a_not_applicable_fact_is_in_neither_list():
    """C3 3.6: N/A leaves the denominator - it is neither owed nor in place."""
    facts = {**FULL_T1, **FULL_T2, "num_employees": _na()}
    kd = sq.key_details(facts, {})
    assert "Number of employees" not in kd["satisfied"]
    assert "Number of employees" not in kd["missing"]
    score, missing = sq.check_tier2(facts, {})
    assert (score, missing) == (100, [])


def test_naics_or_sic_is_one_item_and_sic_alone_satisfies_it():
    facts = {**FULL_T1, **FULL_T2}
    del facts["naics_code"]
    assert "NAICS or SIC industry code" in sq.key_details(facts, {})["missing"]
    facts["sic_code"] = "1731"
    kd = sq.key_details(facts, {})
    assert "NAICS or SIC industry code" in kd["satisfied"]
    assert kd["missing"] == []


def test_certificate_package_lists_only_its_two_tier1_items():
    flags = {"is_certificate_doc": True}
    kd = sq.key_details({"applicant_name": "Acme LLC"}, flags)
    assert kd["satisfied"][:1] == ["Applicant legal name"]
    assert "Proposed effective date" in kd["missing"]
    for lbl in ("Producer / Agency name", "Contact information", "Business entity type"):
        assert lbl not in kd["satisfied"] and lbl not in kd["missing"]


def test_producer_name_is_exempt_on_a_dec_page_only_package_in_both_lists():
    """C3 3.3: the exemption removes the item, it does not satisfy it."""
    flags = {"_only_dec_page": True}
    kd = sq.key_details({**FULL_T1, **FULL_T2}, flags)
    assert "Producer / Agency name" not in kd["satisfied"]
    assert "Producer / Agency name" not in kd["missing"]
    assert "Contact information" in kd["satisfied"]        # never waived


def test_a_human_no_answer_counts_as_in_place():
    """Brent 2026-08-24: "there is none" is an answer, not a gap."""
    facts = {**FULL_T1, **FULL_T2,
             "num_employees": {"value": "", "value_state": "explicit_no", "source": "producer"}}
    kd = sq.key_details(facts, {})
    assert "Number of employees" in kd["satisfied"]


def test_key_details_never_raises_on_bad_input():
    assert sq.key_details(None, None) == {"satisfied": [], "missing": ALL_T1_LABELS + ALL_T2_LABELS}


# ── 2. the refactor left the scorers byte-identical ──────────────────────────

@pytest.mark.parametrize("facts,expected", [
    ({}, (False, ALL_T1_LABELS)),
    (FULL_T1, (True, [])),
    ({**FULL_T1, "contact_phone": ""}, (False, ["Contact information"])),
    ({"applicant_name": "x"}, (False, ["Proposed effective date"])),
])
def test_check_tier1_is_unchanged(facts, expected):
    flags = {"is_certificate_doc": True} if facts == {"applicant_name": "x"} else {}
    assert sq.check_tier1(facts, flags) == expected


@pytest.mark.parametrize("facts,expected", [
    ({}, (0, ALL_T2_LABELS)),
    (FULL_T2, (100, [])),
    ({**FULL_T2, "num_employees": None, "years_in_business": None},
     (67, ["Number of employees", "Years in business"])),
    # 3.6: one N/A + one missing over a denominator of five is 80, not 83
    ({**FULL_T2, "num_employees": _na(), "years_in_business": None},
     (80, ["Years in business"])),
    ({k: _na() for k in FULL_T2}, (100, [])),
])
def test_check_tier2_is_unchanged(facts, expected):
    facts = dict(facts)
    if "naics_code" in facts and isinstance(facts["naics_code"], dict):
        facts["sic_code"] = _na()
    assert sq.check_tier2(facts, {}) == expected


# ── 3. the pre-generation package score ──────────────────────────────────────

def _session(**over):
    base = {
        "facts": {**FULL_T1, **FULL_T2},
        "flags": {"has_general_liability": True},
        "hard_stops": [], "soft_stops": [],
        "recommendations": [{"form_id": "ACORD_125"}, {"form_id": "ACORD_126"}],
        "cross_form_issues": [], "docs": [], "integrity": {},
        "generated_forms": {}, "underwriting_consistency": {},
    }
    base.update(over)
    return base


def test_pre_generation_score_is_the_scorers_dict_with_its_label():
    pkg = sq.current_package_sqs(_session(), "sess-1", "user-1")
    assert isinstance(pkg, dict)
    assert pkg["calculation_stage"] == "initial_extract"
    assert pkg["tier"] in ("Submission Ready", "Almost There", "Needs Work", "Major Gaps", "Not Ready")
    # the label IS the ladder applied to the displayed score - one ladder
    assert pkg["tier"] == sq.tier_for_score(pkg["package_sqs_score"])[1]


def test_the_label_is_never_a_relabelled_tier2_ratio():
    """The client's screenshot: Tier 2 at 100% beside 12 warnings. A warning
    caps the SQS at 85, so the band can be "Almost There" at best."""
    sess = _session(soft_stops=[f"warning {i}" for i in range(12)])
    assert sq.check_tier2(sess["facts"], sess["flags"])[0] == 100
    pkg = sq.current_package_sqs(sess, "sess-1")
    assert pkg["cap_applied"] == 85
    assert pkg["tier"] != "Submission Ready"


def test_a_suggested_forms_hard_stop_is_a_warning_before_generation():
    """C75: nothing is selected yet, so a cross-form hard stop raised by a
    RECOMMENDED form's rule caps at 85 (warning), never at 60."""
    sess = _session(
        soft_stops=["ACORD 133 selected but no builders risk exposure"],
        cross_form_issues=[{"type": "hard_stop", "code": "br_no_exposure",
                            "message": "ACORD 133 selected but no builders risk exposure",
                            "forms": ["ACORD_133"]}],
    )
    pkg = sq.current_package_sqs(sess, "sess-1")
    assert pkg["cap_applied"] == 85
    demoted = sq._pre_generation_cross_issues(sess)
    assert [i["type"] for i in demoted] == ["soft_warning"]


def test_cross_issues_are_deduplicated_by_message():
    sess = _session(cross_form_issues=[
        {"type": "soft_warning", "message": "same"},
        {"type": "soft_warning", "message": "same"},
        {"type": "advisory", "message": "other"},
        "not a dict", {"type": "soft_warning", "message": ""},
    ])
    assert [i["message"] for i in sq._pre_generation_cross_issues(sess)] == ["same", "other"]


def test_no_recommended_form_scores_through_the_no_form_path():
    pkg = sq.current_package_sqs(_session(recommendations=[]), "sess-1")
    assert isinstance(pkg, dict) and pkg["tier"]
    # 3.7's arithmetic is pinned in test_c3_sqs_integrity; here only "it scored"


def test_withheld_while_integrity_review_is_pending():
    assert sq.current_package_sqs(_session(integrity={"review_required": True}), "s") is None


def test_once_forms_exist_the_persisted_score_is_returned_not_recomputed(monkeypatch):
    """Every post-generation path maintains `package_sqs` and applies credits
    to it (D33). Recomputing would drop them and be a second score."""
    stored = {"package_sqs_score": 77, "tier": "Needs Work", "credits_applied": 5}
    sess = _session(generated_forms={"ACORD_125": {}}, package_sqs=stored)

    def boom(*a, **k):
        raise AssertionError("must not recompute once forms exist")
    monkeypatch.setattr(sq, "score_package_pre_generation", boom)
    assert sq.current_package_sqs(sess, "s") is stored


def test_forms_exist_but_no_stored_score_gives_none_not_a_fresh_one(monkeypatch):
    sess = _session(generated_forms={"ACORD_125": {}}, package_sqs=None)
    monkeypatch.setattr(sq, "score_package_pre_generation",
                        lambda *a, **k: {"tier": "Submission Ready"})
    assert sq.current_package_sqs(sess, "s") is None


def test_scorer_failure_is_none_and_the_log_names_the_session(monkeypatch, caplog):
    def boom(*a, **k):
        raise RuntimeError("scorer exploded")
    monkeypatch.setattr(sq, "calculate_package_sqs", boom)
    with caplog.at_level(logging.ERROR, logger="services.sqs_service"):
        assert sq.current_package_sqs(_session(), "sess-xyz", "u") is None
    assert any("sess-xyz" in r.getMessage() for r in caplog.records)


def test_pre_generation_scoring_persists_nothing():
    """Stateless: the session dict handed in is not mutated - no sqs_history
    entry, no package_sqs key."""
    sess = _session()
    before = {k: (list(v) if isinstance(v, list) else v) for k, v in sess.items()}
    sq.current_package_sqs(sess, "s")
    assert "package_sqs" not in sess
    assert sess.get("sqs_history") is None
    assert {k: (list(v) if isinstance(v, list) else v) for k, v in sess.items()} == before


def test_score_moves_with_the_facts_at_that_moment():
    """Owner: "whatever the sqs is at that point" - answer a fact, the label
    follows the new score."""
    sparse = _session(facts={**FULL_T1})
    full = _session()
    a = sq.current_package_sqs(sparse, "s")["package_sqs_score"]
    b = sq.current_package_sqs(full, "s")["package_sqs_score"]
    assert b > a


# ── 4. every pre-form response goes through the one helper ───────────────────

_FORM_ROUTES = os.path.join(os.path.dirname(__file__), "..", "routes", "form_routes.py")
_PRE_FORM_HANDLERS = (
    "upload_declaration", "submission_integrity_resolve", "document_reclassify",
    "underwriting_confirm_value", "get_extraction_result",
)


def _handler_bodies():
    tree = ast.parse(io.open(_FORM_ROUTES, encoding="utf-8").read())
    return {n.name: n for n in ast.walk(tree)
            if isinstance(n, (ast.AsyncFunctionDef, ast.FunctionDef))}


def test_every_pre_form_response_reads_the_status_through_the_one_helper():
    bodies = _handler_bodies()
    for name in _PRE_FORM_HANDLERS:
        assert name in bodies, f"{name} handler is gone or renamed"
        calls = {
            (getattr(n.func, "id", None) or getattr(n.func, "attr", None))
            for n in ast.walk(bodies[name]) if isinstance(n, ast.Call)
        }
        assert "_pre_form_status" in calls, f"{name} does not go through _pre_form_status"
        assert "calculate_package_sqs" not in calls, (
            f"{name} scores the package inline - the label must come from "
            "sqs_service.current_package_sqs, the one door")
        keys = {
            k.value for n in ast.walk(bodies[name]) if isinstance(n, ast.Dict)
            for k in n.keys if isinstance(k, ast.Constant)
        }
        assert {"package_sqs", "key_details"} <= keys, f"{name} response lacks package_sqs / key_details"


def test_the_helper_withholds_both_while_integrity_review_is_pending():
    import asyncio
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from routes import form_routes as fr
    out = asyncio.run(
        fr._pre_form_status("s", {}, {}, {"review_required": True}, {"id": "u"})
    )
    assert out == (None, None)


def test_the_helper_never_raises_when_the_session_cannot_be_read(monkeypatch, caplog):
    import asyncio
    from routes import form_routes as fr

    async def boom(_sid):
        raise RuntimeError("db down")
    monkeypatch.setattr(fr, "get_processing_session", boom)
    with caplog.at_level(logging.ERROR):
        pkg, kd = asyncio.run(
            fr._pre_form_status("sess-abc", FULL_T2, {}, {}, {"id": "u"})
        )
    assert pkg is None
    assert kd == sq.key_details(FULL_T2, {})
    assert any("sess-abc" in r.getMessage() for r in caplog.records)
