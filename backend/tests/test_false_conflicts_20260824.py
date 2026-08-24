"""The three false conflicts left on the live Run A screen (C1-Q FIX 9).

All three are the client's opening paragraph, verbatim: values that "mean the
same thing but represent them differently because the source documents use
different ... abbreviations; levels of detail; document structures".

  1. `Gl Limits`   - three printings of ONE set of limits, conflicting
  2. `Total Payroll` - three per-CLASS rating bases offered as rivals to the
                       package total
  3. `Contractor Type` - two free-text descriptions of one business

None of them is a disagreement. Each is fixed at its own root cause, and each
keeps the OPPOSITE direction working - a real limits difference, a real payroll
disagreement, and a genuinely different entity all still surface.
"""
import pytest

from services.fact_equivalence import same_fact, value_kind
from services.fact_comparison import compare
from services.underwriting_consistency import (
    _drop_class_exposure_candidates, _class_exposure_amounts,
)

# The client's literal Run A values.
GL_A = ("$1,000,000 Each Occurrence / $2,000,000 General Aggregate / "
        "$2,000,000 Products/Completed Ops Aggregate")
GL_B = "Each Occurrence $1,000,000; General Aggregate $2,000,000"
GL_C = ("$1,000,000 Each Occurrence / $2,000,000 General Aggregate / "
        "$2,000,000 Products-Completed Operations Aggregate / $1,000,000 "
        "Personal and Advertising Injury / $100,000 Damage to Premises Rented "
        "to You / $5,000 Medical Expense")
GL_RIVAL = ("$2,000,000 Each Occurrence / $4,000,000 General Aggregate / "
            "$4,000,000 Products/Completed Ops Aggregate")


# ── 1. A limits SCHEDULE is long, but it is not prose ────────────────────────

def test_three_printings_of_one_limit_set_are_one_fact():
    """THE RUN A CASE. The money branch already owned this ("a composite that
    lists FEWER limits is not disagreeing"), but the 25-word prose floor
    returned INCOMPARABLE before it could run - GL_C is 36 words."""
    r = compare("gl_limits", [GL_A, GL_B, GL_C])
    assert r.verdict == "equivalent", r.groups
    assert len(r.groups) == 1


@pytest.mark.parametrize("a,b", [(GL_A, GL_B), (GL_A, GL_C), (GL_B, GL_C)])
def test_every_pair_of_those_printings_is_the_same_fact(a, b):
    assert same_fact("gl_limits", a, b) == "same"


def test_the_returned_mapping_is_keeper_final_not_a_cycle():
    """`equivalent_index` documents a keeper-final contract. Before the fix it
    returned {0: 1, 1: 0, 2: 0} - 0 and 1 pointing at each other."""
    from services.fact_equivalence import equivalent_index
    m = equivalent_index("gl_limits", [GL_A, GL_B, GL_C]) or {}
    for loser, keeper in m.items():
        assert keeper not in m, f"{keeper} is both a keeper and a loser: {m}"


def test_a_genuinely_different_limit_set_still_conflicts():
    """THE OTHER DIRECTION. Run B's file 6 carries $2M/$4M/$4M - a real
    disagreement about a legal limit, and it must survive."""
    assert compare("gl_limits", [GL_B, GL_RIVAL]).verdict == "conflict"
    assert compare("gl_limits", [GL_C, GL_RIVAL]).verdict == "conflict"


def test_a_real_paragraph_on_a_money_field_is_still_incomparable():
    """The exception is for COMPOSITES, not for length. Two paragraphs that
    happen to quote figures must not start being compared by them."""
    p1 = ("The insured has maintained continuous general liability coverage "
          "throughout the period under review and no material changes to the "
          "program have been reported by the producer or the incumbent carrier "
          "at any point during the current term of the policy.")
    assert same_fact("gl_limits", p1, p1 + " Additional remarks follow.") \
        in ("same", "incomparable")
    assert value_kind("operations_description") == "narrative"


def test_a_single_amount_is_still_never_flattened_into_a_composite():
    """Pre-existing guard that must not be weakened: "$1,000,000" against
    "$1,000,000 / $2,000,000" is one value against a structure naming a larger
    one, not a shorter list."""
    assert same_fact("gl_limits", "$1,000,000", "$1,000,000 / $2,000,000") == "different"


# ── 2. A per-class rating basis is not the package total ─────────────────────

SCHEDULE = {
    "gl_class_code_schedule": [
        {"class_code": "91580", "exposure_amount": "$285,000"},
        {"class_code": "98305", "exposure_amount": "$640,000"},
        {"class_code": "91340", "exposure_amount": "$95,000"},
    ],
}


def _grp(display, method="text_scan"):
    return {"display": display, "normalized": display,
            "sources": [{"raw": display, "source_method": method}]}


def test_the_schedule_exposures_are_read_from_the_package():
    amounts = _class_exposure_amounts(SCHEDULE)
    assert {"285000", "640000", "95000"} <= amounts


def test_class_exposures_are_dropped_as_rivals_to_the_total():
    """THE RUN A CASE: $1,880,000 against the payroll bases of GL classes
    91580 / 98305 / 91340, all three scraped by the text scan from the package's
    own SCHEDULE OF HAZARDS."""
    vals = [_grp("$1,880,000", "llm"), _grp("$285,000"),
            _grp("$640,000"), _grp("$95,000")]
    kept = _drop_class_exposure_candidates("total_payroll", vals, SCHEDULE)
    assert [g["display"] for g in kept] == ["$1,880,000"]


def test_a_value_extraction_produced_is_never_dropped():
    """GUARD 2. A single-class business can legitimately have a total equal to
    its one class basis - and the extractor naming it `total_payroll` is
    independent evidence."""
    vals = [_grp("$285,000", "llm"), _grp("$640,000")]
    kept = _drop_class_exposure_candidates("total_payroll", vals, SCHEDULE)
    assert any(g["display"] == "$285,000" for g in kept)


def test_no_schedule_means_no_opinion():
    """GUARD 1. Positive evidence only."""
    vals = [_grp("$1,880,000", "llm"), _grp("$285,000")]
    assert _drop_class_exposure_candidates("total_payroll", vals, {}) == vals
    assert _drop_class_exposure_candidates("total_payroll", vals, None) == vals


def test_a_real_payroll_disagreement_still_surfaces():
    """THE OTHER DIRECTION - two documents stating different TOTALS."""
    vals = [_grp("$1,880,000", "llm"), _grp("$2,400,000", "llm")]
    assert len(_drop_class_exposure_candidates("total_payroll", vals, SCHEDULE)) == 2


def test_the_filter_never_empties_the_list():
    vals = [_grp("$285,000"), _grp("$640,000")]
    assert _drop_class_exposure_candidates("total_payroll", vals, SCHEDULE)


@pytest.mark.parametrize("bad", [None, "text", 42, {"gl_class_code_schedule": "x"}])
def test_unreadable_schedules_never_raise(bad):
    vals = [_grp("$1", "llm"), _grp("$2")]
    assert _drop_class_exposure_candidates("total_payroll", vals, bad) == vals


# ── 3. A free-text characterisation of the business ──────────────────────────

def test_two_descriptions_of_one_business_are_not_a_conflict():
    """THE RUN A CASE. Both describe one contractor; picking one string fixes
    nothing, and the same package's `operations_description` already folds."""
    a = "Licensed electrical and roofing contractor"
    b = "Commercial General Contractor - Roofing and Electrical"
    assert same_fact("contractor_type", a, b) == "incomparable"
    assert compare("contractor_type", [a, b]).verdict != "conflict"


def test_contractor_type_stays_kind_text_not_narrative():
    """`contractor_type` is deliberately NOT dispatched to KIND_NARRATIVE - a
    real narrative field exits `same_fact` before containment or truncation
    ever run, which is right for an actual paragraph but wrong for a short
    phrase. Reclassifying it that way was tried first and broke the truncation
    test directly below."""
    assert value_kind("contractor_type") == "text"


def test_a_truncated_contractor_type_is_still_SAME_not_merely_incomparable():
    """THE REGRESSION THE FULL-NARRATIVE VERSION OF THIS FIX INTRODUCED. An
    OCR/extraction truncation ("Commercia" cut off mid-word) is proven to be
    one value, not just two we could not otherwise reconcile - the distinction
    matters at n>=3 where only SAME builds the clique that lets a third
    printing merge in too."""
    assert same_fact("contractor_type", "Commercial roofing contractor",
                     "Commercia") == "same"


@pytest.mark.parametrize("key", [
    "construction_type", "occupancy_type", "valuation_method",
    "sprinkler_system", "entity_type", "fire_department_type",
    "auto_liability_structure", "gl_form_type", "billing_plan",
])
def test_no_enumerated_type_field_is_treated_as_soft_text(key):
    """ANTI-ROT, and the reason the soft-text list is EXPLICIT rather than a
    shape test. 39 facts classify as KIND_TEXT and most hold enumerated terms
    where two different values are a real disagreement. A "looks like a phrase"
    heuristic would silence every one of them."""
    from services.fact_equivalence import _SOFT_TEXT_FACT_KEYS
    assert key not in _SOFT_TEXT_FACT_KEYS


def test_two_different_construction_types_still_conflict():
    assert same_fact("construction_type", "Frame", "Joisted Masonry") == "different"


def test_two_different_valuation_methods_still_conflict():
    assert same_fact("valuation_method", "RCV", "ACV") == "different"
