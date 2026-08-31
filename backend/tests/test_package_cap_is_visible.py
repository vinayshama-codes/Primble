"""A package 60 cap must render as a hard stop, not as a warning.

OWNER RULE, 2026-08-31: **the card must match the cap.** If something holds the
score at 60 it renders as a hard stop - even where the engine that emitted it
called it a warning. Never the reverse: a display problem is never fixed by
changing a score.

The live defect this pins: `calculate_package_sqs` MANUFACTURES a
`property_building_value` hard stop inside itself. It caps the package at 60 and
its own comment claims it "shows in the Hard Stops section" - it never did. The
dict is created locally, never written to `cross_issues_last` or
`structured_issues`, so `build_grouped_view` could not see it:
`grouped_issues.hard_stops` was empty, `counts.hard_stops` was 0, and the
frontend's `hasHardStops` gate hid the banner entirely. Meanwhile
`extraction_pipeline` draws the SAME fact as a soft warning when the package has
no property coverage - so the producer read "warning" while the score read
"blocker". Measured: raw 68 -> displayed 60 with `hard_stops == []`.

Nothing here asserts a score changed. The fix is display-only.
"""
import pytest

from services.sqs_service import (
    calculate_package_sqs, evaluate_stops, HARD_STOP_CAP,
)
from services.issue_registry import build_grouped_view, make_issue


_PICKER_CODE = "underwriting_reconciliation_property_building_value"

# The card `extraction_pipeline` already draws for this fact when the conflict is
# not relevant - a soft warning, with its own wording.
_WARN = ("Property Building Value: documents disagree ($2,500,000, $3,100,000). "
         "Fix: Confirm the correct value to apply it across forms.")

_FACTS = {
    "applicant_name": "ACME LLC", "fein": "84-2210987", "entity_type": "LLC",
    "mailing_address": "123 Main St, Detroit, MI 48226",
    "physical_address": "123 Main St, Detroit, MI 48226",
    "effective_date": "07/15/2026", "expiration_date": "07/15/2027",
    "total_revenue": "5000000", "total_payroll": "1200000", "num_employees": "24",
    "years_in_business": "12", "naics_code": "238160",
    "producer_name": "Midwest Agency", "carrier_name": "EMC",
    "carrier_naic": "25186", "policy_number": "BBC7263",
    "gl_each_occurrence": "$1,000,000", "gl_aggregate": "$2,000,000",
    "gl_class_codes": "5551", "gl_exposure_basis": "payroll",
    "loss_history": "No known losses",
    "loss_history_no_prior_losses_indicator": "Y", "prior_carrier": "EMC",
    "property_building_value": "$2,500,000",
    "operations_description": "Commercial roofing contractor performing re-roofing "
                              "and repair on existing structures.",
    "account_description": "Established roofing contractor, 12 years, stable "
                           "losses, strong safety program.",
}
_FLAGS = {"has_general_liability": True, "has_property_coverage": False}
_UW = {"fields": [{
    "fact_key": "property_building_value", "review_required": True,
    "label": "Property Building Value",
    "values": [{"display": "$2,500,000"}, {"display": "$3,100,000"}],
}]}


def _score(uw=_UW, hard=None, soft=None, facts=None, flags=None):
    facts = facts if facts is not None else _FACTS
    flags = flags if flags is not None else _FLAGS
    session = {"facts": facts, "flags": flags, "docs": []}
    if uw is not None:
        session["underwriting_consistency"] = uw
    _h, _s = evaluate_stops(facts, flags)
    return calculate_package_sqs(
        facts=facts, flags=flags, form_results=[], cross_issues=[],
        hard_stops=_h if hard is None else hard,
        soft_stops=_s if soft is None else soft,
        session_data=session, session_id="t", user_id="t",
        calculation_stage="form_generated",
    )


def test_the_manufactured_stop_is_no_longer_private():
    """The reported shape: a 60 cap whose cause reached no display channel."""
    pkg = _score()
    assert pkg["cap_applied"] == HARD_STOP_CAP
    assert pkg["cap_hard_stops"], "a package 60 cap with no card must surface one"
    assert pkg["cap_reason"] in pkg["cap_hard_stops"]
    # And it names the card that already exists, so the display can promote it.
    assert _PICKER_CODE in pkg["cap_hard_stop_codes"]


def test_promotion_upgrades_the_existing_card_and_does_not_duplicate_it():
    """The warning becomes the hard stop. One row, not two."""
    pkg = _score()
    hard, soft = evaluate_stops(_FACTS, _FLAGS)
    soft = list(soft) + [_WARN]
    structured = [make_issue(_PICKER_CODE, "soft_warning", _WARN)]

    before = build_grouped_view(structured, hard, soft)
    assert before["counts"]["hard_stops"] == 0        # the defect

    after = build_grouped_view(
        structured, hard, soft, promote_codes=pkg["cap_hard_stop_codes"])
    assert after["counts"]["hard_stops"] == 1
    assert len(after["hard_stops"]) == 1
    # The SAME row moved - its wording is preserved, so its Resolve control
    # ("Fix in Data Consistency", derived from the code) moves with it.
    assert after["hard_stops"][0]["items"][0]["message"] == _WARN
    assert after["hard_stops"][0]["items"][0]["code"] == _PICKER_CODE
    # Exactly one row total for this problem.
    assert before["counts"]["warnings"] - after["counts"]["warnings"] == 1


def test_promotion_is_inert_without_codes():
    """No promote_codes -> byte-identical to the previous behaviour."""
    hard, soft = evaluate_stops(_FACTS, _FLAGS)
    soft = list(soft) + [_WARN]
    structured = [make_issue(_PICKER_CODE, "soft_warning", _WARN)]
    assert (build_grouped_view(structured, hard, soft)
            == build_grouped_view(structured, hard, soft, promote_codes=[]))


def test_no_conflict_means_nothing_is_invented():
    pkg = _score(uw={"fields": []})
    assert pkg["cap_hard_stops"] == []
    assert pkg["cap_hard_stop_codes"] == []


def test_never_duplicates_a_stop_the_screen_already_shows():
    """A real hard stop already renders a card; the package cap stays quiet."""
    pkg = _score(hard=["FEIN differs across uploaded documents."], soft=[])
    assert pkg["cap_applied"] == HARD_STOP_CAP
    assert pkg["cap_hard_stops"] == []


def test_no_score_moved_by_this_change():
    """The whole fix is display. The cap and the number are what they were."""
    pkg = _score()
    assert pkg["cap_applied"] == HARD_STOP_CAP
    assert pkg["package_sqs_score"] == min(pkg["raw_sqs_score"], HARD_STOP_CAP)


@pytest.mark.parametrize("has_property", [True, False])
def test_every_package_60_cap_is_said_somewhere(has_property):
    """THE INVARIANT, package half. Whatever holds the package at 60 is either
    already a hard stop the screen draws, or is in cap_hard_stops. A future cap
    source added to calculate_package_sqs cannot go silent without failing here.

    Both relevance branches are driven: Option A (owner, 2026-08-31) keeps the
    cap in BOTH, and requires it to be visible in both.
    """
    flags = dict(_FLAGS, has_property_coverage=has_property)
    pkg = _score(flags=flags)
    if pkg["cap_applied"] != HARD_STOP_CAP:
        pytest.skip("not capped in this branch")
    hard, _ = evaluate_stops(_FACTS, flags)
    assert pkg["cap_reason"] in hard or pkg["cap_reason"] in pkg["cap_hard_stops"], (
        f"package held at 60 by {pkg['cap_reason']!r} with nothing on screen"
    )
