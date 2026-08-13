"""Pre/post-download review: repetition + score-contradiction fixes, 2026-08-12.

Client feedback driving this file:
  * "repeated values are there a lot, is there a way we can reduce it" - the
    fresh run showed "No loss history provided - required for carrier
    submission" TWICE, plus ~20 near-identical "high-impact question the AI
    left blank" rows across ACORD 125/126/127.
  * PART 18: "73 unresolved items - that seems like a lot. Does this score
    truly correlate to the amount of info still needed?" - and the same screen
    showed "Score at download: 66/100" above a summary paragraph saying "This
    submission scores 63/100".

Root causes fixed (none touch score computation):
  1. Loss-history recommendations carried POSITIONAL rec_ids
     (`rec_loss_{len(recommendations)}`), so the identical warning emitted by
     two forms' scorers at different list indexes defeated the audit table's
     ON CONFLICT (session_id, rec_id) dedupe -> two rows. Now identity-derived
     via sqs_service._loss_rec_id (digits stripped so a varying "N days old"
     can't fork the id).
  2. audit_service.log_recommendations_presented minted a RANDOM uuid rec_id
     for plain-string recommendations - same dedupe defeat. Now a
     deterministic message hash (_fallback_rec_id).
  3. field_qa.to_recommendation_rows emitted one row per distinct high-impact
     question; distinct questions sharing one form + reason now roll up to a
     single row naming each question.
  4. The narrative endpoint fed the LLM the FIRST form's per-form score while
     the banner renders the PACKAGE score (independent by design) - and the
     prompt told the model to state it. Endpoint now uses package_sqs; the
     prompt forbids restating score/tier/points.

Run from backend/:
    python -m pytest tests/test_preflight_repetition_20260812.py -v
"""

import asyncio
import inspect
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("OPENAI_API_KEY", "sk-offline")

import services.sqs_service as sq  # noqa: E402
from services.audit_service import _fallback_rec_id  # noqa: E402
from services.field_qa import to_recommendation_rows  # noqa: E402


# ── 1. Loss recommendation identity ──────────────────────────────────────────

def test_the_client_duplicate_line_maps_to_one_stable_id():
    msg = "No loss history provided - required for carrier submission"
    assert sq._loss_rec_id(msg) == sq._loss_rec_id(msg)
    assert sq._loss_rec_id(msg).startswith("rec_loss_")


def test_variable_digits_do_not_fork_the_id():
    # Two forms scoring the same session can format the same warning with the
    # same (or a re-measured) age; the id must be the TEMPLATE's, not the run's.
    a = sq._loss_rec_id(
        "Loss runs appear stale (372 days old). Updated loss runs may be required before bind.")
    b = sq._loss_rec_id(
        "Loss runs appear stale (15 days old). Updated loss runs may be required before bind.")
    assert a == b


def test_every_real_loss_message_template_gets_a_distinct_id():
    """The actual message vocabulary of calculate_p4_loss_history - if two
    templates ever collide, one dismissal would silently clear the other."""
    templates = [
        "No loss history provided - required for carrier submission",
        "Loss runs requested / pending - update score when received",
        "No Known Losses (attested by user) - attach loss runs or a signed no-known-loss letter to fully confirm",
        "No Known Losses (stated in narrative) - confirm with the insured, or attach loss runs or a signed no-known-loss letter to corroborate the statement",
        "Prior carrier name missing - add carrier details to strengthen the loss history record",
        "Prior carrier name missing - add carrier details to complete the underwriting picture",
        "Loss runs appear stale (372 days old). Updated loss runs may be required before bind.",
        "Loss run valuation date could not be verified. Updated or currently valued loss runs may be required.",
        "Loss run valuation date not detected - recency unverified. Updated loss runs may be required.",
    ]
    ids = {sq._loss_rec_id(m) for m in templates}
    assert len(ids) == len(templates)


def test_no_positional_rec_ids_remain_in_the_scorer():
    """Anti-rot: a rec_id derived from a list position is the whole defect."""
    src = inspect.getsource(sq).replace(" ", "")
    assert "rec_loss_{len(" not in src


# ── 2. String-recommendation fallback id ─────────────────────────────────────

def test_string_recommendation_fallback_id_is_deterministic():
    assert _fallback_rec_id("Some warning") == _fallback_rec_id("Some warning")
    assert _fallback_rec_id("Some warning") != _fallback_rec_id("Another warning")
    assert _fallback_rec_id("Some warning").startswith("rec_str_")


# ── 3. Field-QA second-tier merge ────────────────────────────────────────────

def _hi(form, field, code="not_answered"):
    return {"form_id": form, "field": field, "reason_code": code,
            "high_impact": True, "message": f"{field} original individual message"}


def test_distinct_high_impact_questions_on_one_form_merge_to_one_named_row():
    # 4 items, 3 DISTINCT questions (the FullName pair is two row-letters of
    # one question) -> one row that names all three.
    qa = {"results": [
        _hi("ACORD_127", "CommercialVehicleLineOfBusiness_QuestionKADCode_A"),
        _hi("ACORD_127", "CommercialVehicleLineOfBusiness_VehiclesLeasedToOthersExplanation_A"),
        _hi("ACORD_127", "AdditionalInterest_FullName_C"),
        _hi("ACORD_127", "AdditionalInterest_FullName_D"),
    ]}
    rows = to_recommendation_rows(qa)
    assert len(rows) == 1
    m = rows[0]["message"]
    assert "ACORD 127: 3 high-impact questions" in m
    assert "left blank" in m
    assert rows[0]["type"] == "suggestion"
    assert rows[0]["component"] == "ACORD_127"


def test_more_than_three_questions_truncate_with_a_more_count():
    qa = {"results": [
        _hi("ACORD_126", f"GeneralLiabilityLineOfBusiness_Question{c}Code_A")
        for c in ("AAB", "AAC", "AAD", "AAE", "AAF")
    ]}
    rows = to_recommendation_rows(qa)
    assert len(rows) == 1
    assert "5 high-impact questions" in rows[0]["message"]
    assert "+2 more" in rows[0]["message"]


def test_forms_and_reasons_still_never_merge_with_each_other():
    qa = {"results": [
        _hi("ACORD_126", "GeneralLiabilityLineOfBusiness_QuestionAABCode_A"),
        _hi("ACORD_126", "GeneralLiabilityLineOfBusiness_QuestionAACCode_A"),
        _hi("ACORD_127", "CommercialVehicleLineOfBusiness_QuestionKADCode_A"),
        _hi("ACORD_127", "CommercialVehicleLineOfBusiness_QuestionKAECode_A", code="low_confidence"),
    ]}
    rows = to_recommendation_rows(qa)
    # 126/not_answered merged; 127/not_answered single; 127/low_confidence single.
    assert len(rows) == 3
    components = sorted(r["component"] for r in rows)
    assert components == ["ACORD_126", "ACORD_127", "ACORD_127"]


def test_the_merged_row_id_is_stable_across_runs():
    qa = {"results": [
        _hi("ACORD_126", "GeneralLiabilityLineOfBusiness_QuestionAABCode_A"),
        _hi("ACORD_126", "GeneralLiabilityLineOfBusiness_QuestionAACCode_A"),
    ]}
    id1 = to_recommendation_rows(qa)[0]["rec_id"]
    id2 = to_recommendation_rows(qa)[0]["rec_id"]
    assert id1 == id2
    assert id1.startswith("fieldqa_")


def test_value_mismatches_stay_individual_rows():
    # A mismatch is a distinct, differently-actioned finding - never rolled up.
    qa = {"results": [
        {"form_id": "ACORD_125", "field": "OtherPolicy_PolicyNumberIdentifier_A",
         "reason_code": "value_mismatch", "high_impact": True, "message": "mismatch one"},
        {"form_id": "ACORD_125", "field": "GeneralLiability_OtherCoverageLimitAmount_A",
         "reason_code": "value_mismatch", "high_impact": True, "message": "mismatch two"},
    ]}
    rows = to_recommendation_rows(qa)
    assert {r["message"] for r in rows} == {"mismatch one", "mismatch two"}


def test_client_run_shape_shrinks_from_twenty_rows_to_three():
    """The literal shape of the client's 2026-08-12 run: 20 high-impact blank
    rows across three forms must render as exactly one named row per form."""
    qa = {"results": (
        [_hi("ACORD_125", f) for f in (
            "CommercialStructure_QuestionABBCode_A", "CommercialStructure_QuestionABBCode_B",
            "CommercialStructure_QuestionABBCode_C", "CommercialStructure_QuestionABBCode_D",
            "NamedInsured_FullName_A", "NamedInsured_FullName_B",
            "AdditionalInterest_Interest_LeasebackOwnerIndicator_A",
            "NamedInsured_Contact_FullName_A", "NamedInsured_Contact_FullName_B",
            "CommercialPolicy_ApplicantOwnLeaseOperateDronesExplanation_A",
            "AdditionalInterest_FullName_A", "AdditionalInterest_FullName_B",
        )]
        + [_hi("ACORD_126", f) for f in (
            "GeneralLiabilityLineOfBusiness_ApplicantLeaseEquipmentToOthersExplanation_A",
            "GeneralLiabilityLineOfBusiness_QuestionACJCode_A",
            "GeneralLiabilityLineOfBusiness_WatercraftDocksFloatsOwnedHiredLeasedExplanation_A",
            "AdditionalInterest_FullName_A", "AdditionalInterest_FullName_B",
            "AdditionalInterest_FullName_C", "AdditionalInterest_FullName_D",
            "AdditionalInterest_FullName_E",
        )]
        + [_hi("ACORD_127", f) for f in (
            "CommercialVehicleLineOfBusiness_OperationInvolveTransportingHazardousMaterialsExplanation_A",
            "CommercialVehicleLineOfBusiness_VehicleMaintenanceProgramInOperationExplanation_A",
            "AdditionalInterest_FullName_A", "AdditionalInterest_FullName_B",
            "AdditionalInterest_FullName_C", "AdditionalInterest_FullName_D",
            "CommercialVehicleLineOfBusiness_QuestionKADCode_A",
        )]
    )}
    rows = to_recommendation_rows(qa)
    assert len(rows) == 3
    assert sorted(r["component"] for r in rows) == ["ACORD_125", "ACORD_126", "ACORD_127"]
    for r in rows:
        assert "high-impact questions" in r["message"]


def test_summary_blank_count_reads_as_by_design_not_failure():
    qa = {"results": [
        {"form_id": "ACORD_125", "field": f"Producer_SomeOptionalField_{s}",
         "reason_code": "not_answered", "high_impact": False, "message": "m"}
        for s in ("A", "B", "C")
    ]}
    rows = to_recommendation_rows(qa)
    assert len(rows) == 1 and rows[0]["rec_id"] == "fieldqa_summary"
    msg = rows[0]["message"]
    assert "left blank by design" in msg
    assert "not covered by the documents" in msg
    assert "the AI left blank" not in msg     # the old scare phrasing


# ── 4. Narrative: one source of truth for the number ─────────────────────────

def test_narrative_prompt_gets_package_score_and_forbids_restating_it():
    captured = {}

    async def fake_chat(model, messages, **kw):
        captured["prompt"] = messages[0]["content"]
        return "The main gap is loss history; reconcile it first."

    import config.settings as cs
    orig = cs.groq_chat
    cs.groq_chat = fake_chat
    try:
        out = asyncio.run(sq.generate_sqs_narrative(
            {"package_sqs_score": 66, "tier": "Major Gaps",
             "top_recommendations": [{"message": "Reconcile loss history"}]},
            delta_this_session=3, resolved_recs=[], ignored_recs=[],
        ))
    finally:
        cs.groq_chat = orig
    p = captured["prompt"]
    assert "66/100" in p                                  # context: the live number
    assert "Do NOT repeat the numeric score" in p         # rule: never restated
    assert "Reconcile loss history" in p                  # package top_recs feed drivers
    assert "{'message'" not in p                          # no dict repr leaks
    assert out.startswith("The main gap")


def test_narrative_endpoint_prefers_the_package_result():
    """The banner renders package_sqs; the prose must be built from the SAME
    object. The first-form fallback survives only for legacy sessions."""
    import routes.audit_routes as ar

    seen = {}

    async def fake_verify(sid, user):
        return None

    async def fake_summary(sid):
        return {"recommendations": {}}

    async def fake_gen(sqs_result, **kw):
        seen["score"] = sqs_result.get("package_sqs_score") or sqs_result.get("sqs_score")
        return "ok"

    orig = (ar._verify_session_owner, ar.get_processing_session,
            ar.get_audit_summary, ar.generate_sqs_narrative)
    try:
        ar._verify_session_owner = fake_verify
        ar.get_audit_summary = fake_summary
        ar.generate_sqs_narrative = fake_gen

        async def with_package(sid):
            return {"package_sqs": {"package_sqs_score": 66, "tier": "T"},
                    "generated_forms": {"ACORD_125": {"sqs": {"sqs_score": 63}}}}
        ar.get_processing_session = with_package
        asyncio.run(ar.sqs_narrative("s1", current_user={"id": "u"}))
        assert seen["score"] == 66, "narrative must be built from the package score"

        async def legacy(sid):
            return {"generated_forms": {"ACORD_125": {"sqs": {"sqs_score": 63}}}}
        ar.get_processing_session = legacy
        asyncio.run(ar.sqs_narrative("s1", current_user={"id": "u"}))
        assert seen["score"] == 63, "legacy sessions still fall back to the first form"
    finally:
        (ar._verify_session_owner, ar.get_processing_session,
         ar.get_audit_summary, ar.generate_sqs_narrative) = orig


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    passed = 0
    for fn in fns:
        fn()
        passed += 1
        print(f"  ok  {fn.__name__}")
    print(f"\n{passed}/{len(fns)} passed")
