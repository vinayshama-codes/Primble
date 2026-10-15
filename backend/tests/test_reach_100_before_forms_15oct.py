"""Everything the pre-form review screen asks can take a package to 100 (15 Oct 2026).

The owner asked whether answering every item on the pre-form screen makes the score 100
on any package. A replay that answered every hard stop, warning, key detail,
Recommendations row and Data Consistency pick the way a producer would (14 stored
packages) found two places where it could not, whatever was typed:

1. THE UMBRELLA PILLAR HAD NO BOX. Exposure and Property list one row per deduction with
   the box that closes it (13 Oct 2026, the decision that the SQS reaches 100 before
   forms); the Umbrella pillar still listed ONE row - "Improve umbrella limit adequacy" -
   with no field, plus a box-less "Unable to determine whether umbrella follows form"
   review row. c7c4cdb5 stopped at 94 with the pillar at 50 (umbrella limit -25,
   schedule of underlying insurance -15, follow form -10), every one of them a fact a
   producer can type. Now `umbrella_deduction_items` holds the pillar's deductions (the
   pillar is 100 minus their sum, floored at 0) and `umbrella_gap_items` lists each with
   its box.
2. AN ENTITY TYPE WARNING NOTHING COULD CLEAR. `check_doc_consistency` compared each
   document's RAW entity type ("Corporation" on two decs whose insured is "... LLC") while
   the Data Consistency picker, the merge and Submission Integrity read the SETTLED one
   (`settle_document_entity_type`): the warning said "Fix in the Data Consistency
   section", the picker showed agreement and nothing to confirm, and the score sat at 85
   (9acec031). It now reads through Integrity's own door.
"""
import itertools
import random

import pytest

from services import sqs_service as S
from services.sqs_service import check_doc_consistency


def _env(v):
    return {"value": v, "source": "producer", "confidence": "producer"}


# ── 1. The umbrella pillar is its items, and every item has its box ───────────
def _client_table(facts, flags):
    """The client-approved deductions, as the pillar always took them."""
    gl = S._to_int(S._fv(facts, "gl_each_occurrence") or S._fv(facts, "gl_limits"))
    auto = S._to_int(S._fv(facts, "auto_liability_limit"))
    split = auto is None and S._auto_liability_stated(facts)
    d = 0
    if not S._fv(facts, "umbrella_limit"):
        d += 25
    if gl is not None and gl < S._UMB_GL_OCC_MIN:
        d += 20
    elif gl is None and flags.get("has_general_liability"):
        d += 20
    agg = S._to_int(S._fv(facts, "gl_aggregate"))
    if agg is not None and agg < S._UMB_GL_AGG_MIN:
        d += 20
    if auto is not None and auto < S._UMB_AUTO_CSL_MIN:
        d += 20
    elif auto is None and flags.get("has_auto_coverage") and not split:
        d += 20
    if S._wc_carried(flags):
        el = S._to_int(S._fv(facts, "employers_liability_limits"))
        d += 25 if el is None or el < S._UMB_EL_OK else (0 if el >= S._UMB_EL_FULL else 10)
    if not S._umbrella_schedule_present(facts):
        d += 15
    if not S._has_explicit_follow_form(" ".join([S._narrative_remarks_text(facts),
                                                 str(S._fv(facts, "umbrella_follow_form") or ""),
                                                 str(S._fv(facts, "policy_notes") or "")])):
        d += 10
    return max(0, 100 - d)


_CHOICES = {
    "umbrella_limit": [None, "5000000"],
    "gl_each_occurrence": [None, "500000", "1000000"],
    "gl_aggregate": [None, "1000000", "2000000"],
    "auto_liability_limit": [None, "500000", "1000000"],
    "employers_liability_limits": [None, "100000", "500000", "1000000"],
    "schedule_of_underlying_insurance": [None, "General Liability $1,000,000 / Auto Liability $1,000,000"],
    "umbrella_follow_form": [None, "Follows form - explicitly stated in the submitted documents",
                             "Does not follow form - the umbrella has its own terms"],
}


@pytest.mark.parametrize("seed", range(25))
def test_the_pillar_is_its_items_and_never_moved(seed):
    rng = random.Random(seed)
    for _ in range(60):
        facts = {k: _env(v) for k, opts in _CHOICES.items() for v in [rng.choice(opts)] if v is not None}
        flags = {"has_umbrella": True, "has_general_liability": rng.random() < 0.8,
                 "has_auto_coverage": rng.random() < 0.6, "has_workers_comp": rng.random() < 0.5}
        pillar = S._calculate_umbrella_adequacy(facts, flags)
        if not S._umbrella_has_underlying(facts):
            assert pillar == 0
            items = S.umbrella_gap_items(facts, flags)
            assert [i["points"] for i in items] == [100] and items[0]["fact"]
            continue
        assert pillar == _client_table(facts, flags)                  # no score moves
        items = S.umbrella_gap_items(facts, flags)
        assert sum(i["points"] for i in items) == 100 - pillar        # the rows add up to the gap
        assert all(i.get("fact") for i in items)                      # every one has its box


def test_no_umbrella_no_items_and_a_full_pillar_lists_nothing():
    assert S.umbrella_gap_items({}, {"has_umbrella": False}) == []
    facts = {"umbrella_limit": _env("5000000"), "gl_each_occurrence": _env("1000000"),
             "gl_aggregate": _env("2000000"),
             "schedule_of_underlying_insurance": _env("General Liability $1,000,000"),
             "umbrella_follow_form": _env("Follows form - explicitly stated in the submitted documents")}
    flags = {"has_umbrella": True, "has_general_liability": True}
    assert S._calculate_umbrella_adequacy(facts, flags) == 100
    assert S.umbrella_gap_items(facts, flags) == []


def test_every_umbrella_box_is_a_question_the_fix_window_can_ask():
    from services.answer_routing import answer_mode
    for fact in ("umbrella_limit", "gl_each_occurrence", "gl_aggregate", "auto_liability_limit",
                 "employers_liability_limits", "schedule_of_underlying_insurance", "umbrella_follow_form"):
        assert (answer_mode(fact) or {}).get("mode") == "field", fact


def test_the_employers_liability_box_is_probed_with_an_amount():
    # no validator on the free-text limit: a "Yes" probe states no amount and the
    # row would measure nothing, so it would never be listed
    assert S._package_probe_answer("employers_liability_limits") == ("1000000", True)


def _umbrella_package():
    facts = {k: _env("x") for k in list(S.TIER1_FIELDS) + list(S.TIER2_FIELDS)}
    facts.update({"applicant_name": _env("Acme LLC"), "effective_date": _env("01/01/2027"),
                  "expiration_date": _env("01/01/2028"), "contact_name": _env("Dana"),
                  "num_employees": _env("0"), "naics_code": _env("238210"),
                  "total_revenue": _env("$5,000,000"), "years_in_business": _env("17"),
                  "fein": _env("12-3456789"), "operations_description": _env("Electrical contractor"),
                  "gl_each_occurrence": _env("1000000"), "gl_aggregate": _env("2000000")})
    flags = {"has_umbrella": True, "has_general_liability": True}
    kw = dict(flags=flags, form_results=[], cross_issues=[], hard_stops=[], soft_stops=[],
              session_data={"docs": []}, form_fill=False)
    return facts, kw


def test_the_real_scorer_lists_each_umbrella_gap_with_its_box_and_answering_them_closes_it():
    facts, kw = _umbrella_package()
    pkg = S.calculate_package_sqs(facts=facts, **kw)
    assert pkg["pillars"]["umbrella_limit_adequacy"] == 50           # -25 limit, -15 schedule, -10 follow form
    rows = [r for r in pkg["top_recommendations"] if r.get("pillar") == "umbrella_limit_adequacy"]
    fields = {r.get("field") for r in rows}
    assert {"umbrella_limit", "schedule_of_underlying_insurance", "umbrella_follow_form"} <= fields
    assert None not in fields                                         # no box-less umbrella row
    assert all((r.get("resolution") or {}).get("mode") == "field" or r.get("answer_mode") == "field" for r in rows)
    # each row is worth its own deduction: limit 25 > schedule 15 > follow form 10
    by = {r["field"]: r["points_available"] for r in rows}
    assert by["umbrella_limit"] > by["schedule_of_underlying_insurance"] > by["umbrella_follow_form"] > 0
    # the follow-form review row is not added beside its own box
    assert not [r for r in pkg["top_recommendations"]
                if r.get("review_item") and "follow" in str(r.get("action")).lower()]
    answered = dict(facts, umbrella_limit=_env("5000000"),
                    schedule_of_underlying_insurance=_env("General Liability $1,000,000 / Auto Liability $1,000,000"),
                    umbrella_follow_form=_env("Follows form - explicitly stated in the submitted documents"))
    after = S.calculate_package_sqs(facts=answered, **kw)
    assert after["pillars"]["umbrella_limit_adequacy"] == 100
    assert after["raw_sqs_score"] > pkg["raw_sqs_score"]
    # every listed row answered: the shares add up exactly to the move (the
    # umbrella rows' own shares are measured after the bigger rows above them)
    shared = [r for r in pkg["top_recommendations"] if r.get("answer_gain_share")]
    every = dict(facts)
    for r in shared:
        every[r["field"]] = S._package_probe_answer(r["field"])[0]
    done = S.calculate_package_sqs(facts=every, **kw)
    assert done["raw_sqs_score"] - pkg["raw_sqs_score"] == sum(r["answer_gain"] for r in shared)
    assert done["pillars"]["umbrella_limit_adequacy"] == 100


# ── 2. The entity type warning reads the settled value ─────────────────────────
def _doc(name, fname, entity, insured, text=""):
    return {"filename": fname, "doc_type": "declarations_page", "text": text,
            "facts": {"applicant_name": {"value": insured}, "entity_type": {"value": entity}}}


def test_a_name_designator_settles_a_contradicting_reading():
    docs = [_doc("a", "auto.pdf", "Corporation", "Choice Electric LLC"),
            _doc("b", "umbrella.pdf", "Corporation", "Choice Electric LLC"),
            _doc("c", "excess.pdf", "LLC", "Choice Electric LLC")]
    issues = check_doc_consistency(docs, set())
    assert not [i for i in issues if i.startswith("[warning]") and "Entity type" in i]
    assert [i for i in issues if "entity_type_normalized" in i]       # shown as a note, never scored


def test_two_genuinely_different_entity_types_still_warn():
    docs = [_doc("a", "a.pdf", "Partnership", "Smith and Jones"),
            _doc("b", "b.pdf", "Sole Proprietorship", "Smith and Jones")]
    assert [i for i in check_doc_consistency(docs, set()) if i.startswith("[warning]") and "Entity type" in i]


def test_a_confirmed_entity_type_is_never_rechecked():
    docs = [_doc("a", "a.pdf", "Partnership", "Smith and Jones"),
            _doc("b", "b.pdf", "Sole Proprietorship", "Smith and Jones")]
    assert not [i for i in check_doc_consistency(docs, {"entity_type"}) if "Entity type" in i]


# ── 3. A document-conflict warning the documents no longer raise leaves the list ──
def test_one_code_derivation_for_upload_and_recalculation():
    from services.issue_registry import doc_conflict_code
    assert doc_conflict_code("[hard_stop] code=name_conflict Applicant name differs") == "doc_conflict_hard_name_conflict"
    assert doc_conflict_code("[warning] field=entity_type Entity type differs") == "doc_conflict_warn_entity_type"
    assert doc_conflict_code("[warning] Something odd") == "doc_conflict_warn_conflict"
    assert doc_conflict_code("[info] code=entity_type_normalized Entity type: A | B") is None
    assert doc_conflict_code("unlabelled") == "doc_conflict_warn_unknown"


def test_a_settled_warning_is_retired_and_a_live_one_kept():
    from services.issue_registry import retire_stopped_doc_conflict_issues
    stale = {"code": "doc_conflict_warn_entity_type", "message": "Entity type differs across documents: Corporation, LLC"}
    other = {"code": "legacy_contact", "message": "Contact information"}
    cross = {"code": "umbrella_gl_period_misaligned", "message": "x"}
    settled = [_doc("a", "auto.pdf", "Corporation", "Choice Electric LLC"),
               _doc("c", "excess.pdf", "LLC", "Choice Electric LLC")]
    out = retire_stopped_doc_conflict_issues([stale, other, cross], settled)
    assert stale not in out and other in out and cross in out
    genuine = [_doc("a", "a.pdf", "Partnership", "Smith and Jones"),
               _doc("b", "b.pdf", "Sole Proprietorship", "Smith and Jones")]
    assert stale in retire_stopped_doc_conflict_issues([stale], genuine)
    # a confirmed field no longer conflicts: its copy goes
    assert retire_stopped_doc_conflict_issues([stale], genuine, {"entity_type"}) == []
    # one document left: nothing can conflict
    assert retire_stopped_doc_conflict_issues([stale], genuine[:1]) == []


def test_a_check_that_cannot_run_keeps_everything(monkeypatch):
    from services import issue_registry as IR
    stale = {"code": "doc_conflict_warn_entity_type", "message": "m"}
    monkeypatch.setattr(S, "check_doc_consistency", lambda *_a, **_k: (_ for _ in ()).throw(RuntimeError("x")))
    assert IR.retire_stopped_doc_conflict_issues([stale], [_doc("a", "a", "LLC", "X"), _doc("b", "b", "LLC", "X")]) == [stale]
