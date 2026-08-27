"""V1 REQUIRED REGRESSION TEST PACK - Classification routing & auto completeness
(client tests 9, 10, 13).

Part of the client's REQUIRED V1 REGRESSION TEST PACK. Recurring regression
scenarios: re-run on every change to question routing, the questionnaire
audience, the NAICS/SIC or WC class-code paths, or the Auto Completeness bucket.

  Test 9  - Missing NAICS/SIC
  Test 10 - Missing WC Class Code
  Test 13 - Owned Auto With No Vehicle Schedule

These enforce V1 core principle 5: the client questionnaire must never ask the
insured to determine NAICS, SIC, WC class codes, GL class codes, coverage
symbols or policy interpretation.

Every test drives the REAL routers (`question_classifier.classify_question`,
`question_eligibility.overlay_for`), the REAL table definitions
(`schedule_capture`), the REAL deduction engine
(`coverage_evidence.auto_completeness_gaps`) and the REAL stop/ceiling engines.
"""
import ast
import inspect
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from config import settings as st                              # noqa: E402
from routes import arq_routes                                  # noqa: E402
from services import coverage_evidence as ce                   # noqa: E402
from services import question_classifier as qc                 # noqa: E402
from services import question_eligibility as qe                # noqa: E402
from services import schedule_capture as sc                    # noqa: E402
from services import sqs_service as sq                         # noqa: E402

BACKEND = Path(__file__).resolve().parents[1]


def _scalar_question(key):
    """A question in the shape the classifier and eligibility overlay see."""
    return {
        "field_name": key,
        "canonical_key": key,
        "audience": qc.AUDIENCE_CLIENT,
        "field_type": "text",
    }


# =============================================================================
# TEST 9 - Missing NAICS/SIC
# =============================================================================

@pytest.mark.parametrize("key", ["naics_code", "sic_code"])
def test_r09_no_client_question(key):
    """No client question is generated for a classification code."""
    classified = qc.classify_question(key, canonical_key=key)
    assert classified["audience"] == qc.AUDIENCE_PRODUCER

    overlay = qe.overlay_for(_scalar_question(key), {})
    assert overlay["audience"] == qc.AUDIENCE_PRODUCER
    assert overlay["suppressed"] is True
    assert overlay["suppressed_reason"] == qe.REASON_INSURANCE_JUDGMENT

    # POSITIVE CONTROL - an ordinary factual business question is left alone,
    # so the suppression above is the classification rule, not a router that
    # suppresses everything.
    ordinary = qe.overlay_for(_scalar_question("years_in_business"), {})
    assert not ordinary.get("suppressed")


@pytest.mark.parametrize("key", ["naics_code", "sic_code"])
def test_r09_producer_remediation_item(key):
    """A PRODUCER remediation item exists - the question is re-routed, not
    deleted."""
    overlay = qe.overlay_for(_scalar_question(key), {})
    assert overlay["producer_review"] is True
    assert overlay["priority"] == qc.PRIORITY_INTERNAL

    counts = {"routed_to_producer": 0}
    questions = [_scalar_question(key)]
    counts = qe.apply_eligibility(questions, {})
    assert counts["routed_to_producer"] == 1
    assert questions[0]["audience"] == qc.AUDIENCE_PRODUCER
    # The producer bucket must move with the audience, or the question keeps
    # rendering in the Client bucket it just left.
    assert questions[0]["bucket"] == qc._AUDIENCE_TO_BUCKET[qc.AUDIENCE_PRODUCER]


def test_r09_no_classification_is_invented():
    """No classification is automatically invented."""
    # The Figure 20 suggester is OFF (C3 3.13); nothing chips a code at all.
    assert st.ENABLE_CLASSIFICATION_SUGGESTIONS is False

    # And even with it on, the suggester is advisory-only by construction: it
    # returns candidates, it never writes a fact. An unrecognisable trade
    # produces NO candidate rather than a plausible guess.
    from services import naics_suggester as ns
    assert ns.suggest("mobile falconry-based bird abatement services") == []

    # A recognised trade DOES produce a candidate - so the empty list above is
    # the "refuse to guess" rule, not a dead function.
    roofing = ns.suggest("Commercial roofing contractor - tear-off and re-roof")
    assert roofing and roofing[0].get("naics")

    # The scorer never manufactures a code either: a missing NAICS raises no
    # value, and only a PRESENT-but-invalid code is ever flagged.
    assert sq.validate_naics_code({}) is None
    assert sq.validate_naics_code({"naics_code": "12"})[0] == "soft"


# =============================================================================
# TEST 10 - Missing WC Class Code
# =============================================================================

def test_r10_no_client_classification_question():
    """No client classification question: the WC class code is a producer-only
    COLUMN, stripped from the client's copy of the employee-group table."""
    defn = sc.get_def("wc_class_codes")
    producer_only = {c["key"] for c in defn["columns"] if c.get("producer_only")}
    assert "code" in producer_only, "the WC class code must be producer-only"
    assert "rate" in producer_only

    # The client still gets the FACTUAL columns - this is a column-level split,
    # not a suppressed table (the insured knows their payroll and headcount).
    client_cols = {c["key"] for c in defn["columns"] if not c.get("producer_only")}
    assert {"description", "payroll", "state"} <= client_cols

    # The owner/officer table is producer-only WHOLE - inclusion/exclusion is
    # insurance judgment and one table cannot split its audience by row.
    assert sc.is_producer_only("wc_officers") is True
    assert sc.is_producer_only("wc_class_codes") is False


def test_r10_scalar_class_code_question_routes_to_producer():
    """Asked as a scalar rather than a table, the class code is an
    insurance-judgment fact and never reaches the client."""
    assert qe.is_insurance_judgment("wc_class_codes") is True
    overlay = qe.overlay_for(_scalar_question("wc_class_codes"), {})
    assert overlay["audience"] == qc.AUDIENCE_PRODUCER
    assert overlay["suppressed"] is True
    assert overlay["suppressed_reason"] == qe.REASON_INSURANCE_JUDGMENT


def test_r10_table_owns_its_audience_split():
    """A schedule question is judged column-by-column, not by its canonical key.

    Judging the whole table as an insurance-judgment fact would flag the
    client's payroll table "producer review" for the one column the client
    never sees - so the overlay deliberately stands aside for tables.
    """
    table_q = dict(_scalar_question("wc_class_codes"),
                   field_type="schedule", schedule_key="wc_class_codes")
    assert qe.overlay_for(table_q, {}) == {}


def test_r10_client_view_strips_the_producer_only_column():
    """THE SEAM: the client's copy of the table really drops producer-only
    columns, and producer-only tables never render to the client at all."""
    src = inspect.getsource(arq_routes.client_view)
    tree = ast.parse(src.lstrip())

    strips = [ast.unparse(n) for n in ast.walk(tree)
              if isinstance(n, ast.ListComp) and "producer_only" in ast.unparse(n)]
    assert strips, ("client_view no longer strips producer-only columns - the "
                    "client would be asked to supply the WC class code")

    assert "is_producer_only" in src, (
        "client_view no longer skips producer-only tables - the officer table "
        "would render to the insured")


def test_r10_no_class_code_is_generated_or_recommended():
    """Primble does not generate a V1 class recommendation.

    The NAICS suggester is the ONLY classification suggester in the codebase;
    there is deliberately no WC equivalent. This fails the build if one appears
    without a product decision.
    """
    services = BACKEND / "services"
    offenders = []
    for path in services.glob("*.py"):
        text = path.read_text(encoding="utf-8", errors="ignore").lower()
        for marker in ("suggest_wc_class", "wc_class_suggest",
                       "recommend_wc_class", "generate_wc_class"):
            if marker in text:
                offenders.append("%s: %s" % (path.name, marker))
    assert not offenders, (
        "a WC class-code generator appeared - client test 10 forbids Primble "
        "generating a V1 class recommendation: %s" % offenders)

    # An empty employee-group table produces no code out of thin air.
    rows, _ = sc.validate_rows("wc_class_codes", [
        {"description": "Field employees - roofing installation",
         "payroll": "520000", "state": "CO"}])
    assert all(not (r.get("code") or "").strip() for r in rows)


# =============================================================================
# TEST 13 - Owned Auto With No Vehicle Schedule
# =============================================================================

# An OWNED auto account (symbol 1 designates any auto) that has supplied every
# Auto Completeness item EXCEPT the vehicle schedule - so the deduction is
# exactly the client's -15 and nothing else.
OWNED_NO_SCHEDULE_FACTS = {
    "has_auto_coverage": True,
    "auto_covered_symbols": [{"coverage": "liability", "symbols": [1]}],
    "auto_drivers": [{"name": "Jane Smith", "license_number": "D1234567",
                      "license_state": "CO"}],
    "auto_garaging_addresses": [{"address": "4800 Dahlia St, Denver, CO 80216"}],
    "auto_radius_of_operation": "50 miles",
    "auto_vehicle_use": "Service",
}
OWNED_NO_SCHEDULE_FLAGS = {"has_auto_coverage": True}


def test_r13_auto_completeness_deducts_15():
    """Auto Completeness -15."""
    assert ce.auto_exposure_kind(
        OWNED_NO_SCHEDULE_FACTS, OWNED_NO_SCHEDULE_FLAGS) == ce.AUTO_OWNED

    gaps = ce.auto_completeness_gaps(OWNED_NO_SCHEDULE_FACTS, OWNED_NO_SCHEDULE_FLAGS)
    assert [g[0] for g in gaps] == ["auto_vin_schedule"]
    assert ce.auto_completeness_deduction(
        OWNED_NO_SCHEDULE_FACTS, OWNED_NO_SCHEDULE_FLAGS) == 15

    # The 15 is the schedule's own weight, read from the production rule table.
    weights = dict((k, p) for k, p, _ in ce.AUTO_COMPLETENESS_RULES)
    assert weights["auto_vin_schedule"] == 15

    # POSITIVE CONTROL - supplying the schedule retires the deduction entirely.
    with_schedule = dict(
        OWNED_NO_SCHEDULE_FACTS,
        auto_vin_schedule=[{"year": "2021", "make": "Ford", "model": "F-150",
                            "vin": "1FTFW1ET5DFC10312"}])
    assert ce.auto_completeness_deduction(with_schedule, OWNED_NO_SCHEDULE_FLAGS) == 0


def test_r13_warning_is_generated():
    """A warning is generated (a warning, not a hard stop)."""
    hard, soft = sq.evaluate_stops(OWNED_NO_SCHEDULE_FACTS, OWNED_NO_SCHEDULE_FLAGS)
    assert not hard, hard
    assert any("vehicle schedule" in m.lower() for m in soft), soft


def test_r13_displayed_sqs_cannot_exceed_85():
    """The displayed SQS cannot exceed 85 while the warning remains."""
    hard, soft = sq.evaluate_stops(OWNED_NO_SCHEDULE_FACTS, OWNED_NO_SCHEDULE_FLAGS)
    cap, reason = sq._resolve_cap(hard, soft)
    assert cap == sq.SOFT_STOP_CAP == 85
    assert "vehicle schedule" in reason.lower()

    for raw in (86, 88, 95, 100):
        assert sq.final_score_with_credits(raw, 0, cap) == 85, raw
    # Still a ceiling, not a floor.
    assert sq.final_score_with_credits(70, 0, cap) == 70

    # POSITIVE CONTROL - once the schedule is supplied the warning clears and
    # the ceiling lifts, so the 85 above is this warning doing the capping.
    fixed = dict(
        OWNED_NO_SCHEDULE_FACTS,
        auto_vin_schedule=[{"year": "2021", "make": "Ford", "model": "F-150",
                            "vin": "1FTFW1ET5DFC10312"}])
    hard2, soft2 = sq.evaluate_stops(fixed, OWNED_NO_SCHEDULE_FLAGS)
    assert not any("vehicle schedule" in m.lower() for m in soft2), soft2


def test_r13_hnoa_only_account_is_not_charged():
    """The -15 is for OWNED auto: a hired/non-owned-only account is exempt.

    This is the boundary that makes test 13 meaningful - without it the
    deduction would fire on every auto package (client test 12).
    """
    hnoa = {"has_auto_coverage": True, "hired_auto_exposure": True,
            "auto_covered_symbols": [{"coverage": "liability", "symbols": [8, 9]}]}
    assert ce.auto_exposure_kind(hnoa, OWNED_NO_SCHEDULE_FLAGS) == ce.AUTO_HNOA_ONLY
    assert ce.auto_completeness_deduction(hnoa, OWNED_NO_SCHEDULE_FLAGS) == 0
