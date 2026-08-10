"""Per-line coverage data: the LOB premium column, derived from ACORD's tooltips.

Client report (ACORD 125, Orbin Contracting): the policy carries four lines with
four separate premiums -

    Commercial General Liability  $3,954
    Commercial Inland Marine        $300
    Commercial Auto               $2,991
    Commercial Umbrella           $3,418
    Total package premium        $10,663

...and the form's entire PREMIUM column came back empty. Not an oversight: the
word "Premium" is in `_NONFILLABLE_SUBSTRINGS`, and `map_facts_to_form` blanks
those BEFORE any deterministic resolution runs, so no fact could ever reach them.
There was also no per-line premium fact anywhere in the system.

Which premium box belongs to which line is read from ACORD's OWN tooltips, not a
hand-written synonym table - see `_lob_premium_index`.
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
os.environ.setdefault("OPENAI_API_KEY", "sk-offline-test")

import services.pdf_service as ps                        # noqa: E402
import services.extraction_service as es                 # noqa: E402


# The client's literal dec-page values.
ORBIN_LINES = [
    {"line": "Commercial General Liability", "premium": "$3,954"},
    {"line": "Commercial Inland Marine",     "premium": "$300"},
    {"line": "Commercial Auto",              "premium": "$2,991"},
    {"line": "Commercial Umbrella",          "premium": "$3,418"},
]

_EXPECTED = {
    "GeneralLiabilityLineOfBusiness_TotalPremiumAmount_A": "$3,954",
    "CommercialInlandMarineLineOfBusiness_PremiumAmount_A": "$300",
    "CommercialVehicleLineOfBusiness_PremiumAmount_A": "$2,991",
    "CommercialUmbrellaLineOfBusiness_PremiumAmount_A": "$3,418",
}


@pytest.mark.parametrize("field,expected", sorted(_EXPECTED.items()))
def test_client_reported_premiums_land_in_the_right_boxes(field, expected):
    facts = {"coverage_lines": ORBIN_LINES}
    assert ps._resolve_lob_premium(field, facts) == expected


def test_lines_with_no_coverage_stay_blank():
    """The decs say "Property - No Coverage" and "Crime and Fidelity - No
    Coverage", so those lines are absent from coverage_lines and their premium
    boxes must not borrow another line's figure."""
    facts = {"coverage_lines": ORBIN_LINES}
    for field in ("CrimeLineOfBusiness_PremiumAmount_A",
                  "CommercialPropertyLineOfBusiness_PremiumAmount_A",
                  "CyberAndPrivacyLineOfBusiness_PremiumAmount_A"):
        assert ps._resolve_lob_premium(field, facts) is None


def test_business_auto_and_commercial_auto_both_reach_the_vehicle_box():
    """ACORD names that box "Commercial Vehicle (Business Auto)"; documents say
    either. The parenthetical synonym is parsed out of ACORD's own tooltip."""
    field = "CommercialVehicleLineOfBusiness_PremiumAmount_A"
    for wording in ("Commercial Auto", "Business Auto", "Commercial Vehicle"):
        facts = {"coverage_lines": [{"line": wording, "premium": "$2,991"}]}
        assert ps._resolve_lob_premium(field, facts) == "$2,991", wording


def test_ambiguous_line_wording_is_refused_not_guessed():
    """A bare "Liability" fits General Liability, Fiduciary Liability AND Liquor
    Liability. A premium is a figure on a signed application - blank beats
    plausible."""
    facts = {"coverage_lines": [{"line": "Liability", "premium": "$9,999"}]}
    for field in ("GeneralLiabilityLineOfBusiness_TotalPremiumAmount_A",
                  "FiduciaryLineOfBusiness_PremiumAmount_A",
                  "LiquorLiabilityLineOfBusiness_PremiumAmount_A"):
        assert ps._resolve_lob_premium(field, facts) is None


def test_two_amounts_for_one_box_leaves_it_blank():
    """Cannot tell which is right, so show neither."""
    facts = {"coverage_lines": [
        {"line": "Commercial General Liability", "premium": "$3,954"},
        {"line": "General Liability",            "premium": "$4,100"},
    ]}
    assert ps._resolve_lob_premium(
        "GeneralLiabilityLineOfBusiness_TotalPremiumAmount_A", facts) is None


def test_same_amount_twice_still_stamps():
    """Two spellings of one line agreeing is not ambiguity."""
    facts = {"coverage_lines": [
        {"line": "Commercial General Liability", "premium": "$3,954"},
        {"line": "General Liability",            "premium": "$3,954"},
    ]}
    assert ps._resolve_lob_premium(
        "GeneralLiabilityLineOfBusiness_TotalPremiumAmount_A", facts) == "$3,954"


def test_missing_or_malformed_fact_is_survivable():
    for facts in ({}, {"coverage_lines": None}, {"coverage_lines": []},
                  {"coverage_lines": "not a list"},
                  {"coverage_lines": [{"line": "GL"}]},          # no premium
                  {"coverage_lines": [{"premium": "$1"}]}):      # no line
        assert ps._resolve_lob_premium(
            "GeneralLiabilityLineOfBusiness_TotalPremiumAmount_A", facts) is None


# ── The index itself, derived from the shipped schemas ───────────────────────

def test_every_lob_premium_box_on_acord_125_is_indexed():
    """15 line-of-business premium boxes; all 15 must be resolvable from ACORD's
    own tooltip wording. A schema regeneration that reworded them would fail
    here rather than silently blanking the column again."""
    idx = ps._lob_premium_index()
    import json
    schema = json.load(open(
        os.path.join(os.path.dirname(__file__), "..",
                     "forms_schemas", "ACORD_125_schema.json"), encoding="utf-8"))
    grid = [f for f in schema if "LineOfBusiness_" in f and "PremiumAmount" in f]
    assert len(grid) == 15, f"expected 15 LOB premium boxes, found {len(grid)}"
    missing = [f for f in grid if f not in idx]
    assert not missing, f"not derivable from their tooltips: {missing}"


def test_a_premium_box_rejects_a_coverage_statement():
    """FOUND ON A REAL RUN. Extraction returned
    `{"line": "Commercial Property", "premium": "No Coverage"}` and the words
    "No Coverage" were stamped into the premium column of the generated PDF.

    A premium is always a figure. This is deliberately STRICTER than a limit box,
    which legitimately holds "Statutory" / "Included" / "See schedule" (C22)."""
    facts = {"coverage_lines": [
        {"line": "Commercial Property", "premium": "No Coverage"},
        {"line": "Crime", "premium": "Not Covered"},
        {"line": "Business Auto", "premium": "$2,991"},
    ]}
    assert ps._resolve_lob_premium(
        "CommercialPropertyLineOfBusiness_PremiumAmount_A", facts) is None
    assert ps._resolve_lob_premium(
        "CrimeLineOfBusiness_PremiumAmount_A", facts) is None
    # ...and a real premium is untouched.
    assert ps._resolve_lob_premium(
        "CommercialVehicleLineOfBusiness_PremiumAmount_A", facts) == "$2,991"


def test_workers_comp_in_an_other_row_is_correct_not_a_defect():
    """ACORD 125's line-of-business grid has NO Workers Compensation box, so an
    "Other" row is genuinely where that line belongs. Guard 7 must leave it -
    blanking it would lose the only place the line can be declared. (Whether WC
    should be listed at all is a GRANT question, handled by
    `apply_declared_absent_downgrades`.)"""
    mapped = {
        "Policy_LineOfBusiness_OtherIndicator_A": "Yes",
        "Policy_LineOfBusiness_OtherLineOfBusinessDescription_A": "Workers' Compensation",
    }
    ps._enforce_post_fill_guards(mapped, _acord125(), {})
    assert mapped["Policy_LineOfBusiness_OtherLineOfBusinessDescription_A"] == \
        "Workers' Compensation"


def test_a_minimum_premium_box_is_not_a_line_premium_box():
    """FOUND BY ADVERSARIAL SWEEP, not by a client.

    ACORD 160 carries TWO premium boxes for Business Owners - "the minimum
    premium amount for..." and "the total estimated premium amount for...". Both
    tooltips name the same line, so leaving the minimum in the index did two
    kinds of damage: it risked stamping the line premium into the minimum box,
    and - worse, because it was silent - the two boxes matched each other, tripped
    the ambiguity refusal, and made the LEGITIMATE Business Owners premium box on
    ACORD 160 permanently unfillable.
    """
    facts = {"coverage_lines": [{"line": "Business Owners", "premium": "$7,500"}]}
    assert ps._resolve_lob_premium(
        "BusinessOwnersLineOfBusiness_PremiumAmount_A", facts) == "$7,500"
    assert ps._resolve_lob_premium(
        "BusinessOwnersLineOfBusiness_MinimumPremiumAmount_A", facts) is None
    assert not [f for f in ps._lob_premium_index() if "Minimum" in f]


def test_a_total_premium_box_IS_a_line_premium_box():
    """The exclusion is read from ACORD's wording ("minimum premium"), not from
    the field name - General Liability's box is named TotalPremiumAmount and is
    the real line premium."""
    assert ps._is_lob_premium_field(
        "GeneralLiabilityLineOfBusiness_TotalPremiumAmount_A") is True


def test_indexed_boxes_are_recognised_as_lob_premium_fields():
    assert ps._is_lob_premium_field(
        "GeneralLiabilityLineOfBusiness_TotalPremiumAmount_A") is True
    # A premium field with no line-of-business tooltip must NOT be claimed.
    assert ps._is_lob_premium_field("Policy_Payment_MinimumPremiumAmount_A") is False


def test_gpt_is_still_never_asked_for_a_premium():
    """The half of the old block that was right stays right: compute_form_gaps
    must keep treating premium boxes as non-fillable, so the LLM can never invent
    one. Only the deterministic path was unblocked."""
    assert ps._is_nonfillable_field(
        "GeneralLiabilityLineOfBusiness_TotalPremiumAmount_A") is True


# ── Registration guards ──────────────────────────────────────────────────────

def test_coverage_lines_is_registered_as_a_list_fact():
    """Unregistered, a scalar reply is not recovered AND the cross-chunk merge
    keeps only one chunk's list - so a dec page split across chunks would lose
    lines. Both registries, not one."""
    assert "coverage_lines" in es._LIST_FIELDS
    assert "coverage_lines" in es._LONG_DOC_LIST_KEYS


# ── "Other" rows that are not other (client #5) ──────────────────────────────
# "The two 'Other' descriptions merely duplicate the standard Business Auto and
# Umbrella selections." The grid ends with blank Other rows for lines ACORD gives
# no box to; the client's form used two of them for lines already ticked above.

def _acord125():
    import json
    with open(os.path.join(os.path.dirname(__file__), "..",
                           "forms_schemas", "ACORD_125_schema.json"),
              encoding="utf-8") as fh:
        return json.load(fh)


def test_other_rows_duplicating_a_ticked_box_are_removed():
    """THE CLIENT'S CASE, verbatim wording."""
    mapped = {
        "Policy_LineOfBusiness_BusinessAutoIndicator_A": "Yes",
        "Policy_LineOfBusiness_UmbrellaIndicator_A": "Yes",
        "Policy_LineOfBusiness_OtherIndicator_A": "Yes",
        "Policy_LineOfBusiness_OtherLineOfBusinessDescription_A": "Commercial Auto",
        "Policy_LineOfBusiness_OtherIndicator_B": "Yes",
        "Policy_LineOfBusiness_OtherLineOfBusinessDescription_B":
            "Commercial Liability Umbrella",
    }
    ps._enforce_post_fill_guards(mapped, _acord125(), {})
    # The duplicates and their own Other ticks go...
    for field in ("Policy_LineOfBusiness_OtherLineOfBusinessDescription_A",
                  "Policy_LineOfBusiness_OtherIndicator_A",
                  "Policy_LineOfBusiness_OtherLineOfBusinessDescription_B",
                  "Policy_LineOfBusiness_OtherIndicator_B"):
        assert mapped[field] is None, field
    # ...and the lines are still declared, by the boxes that own them.
    assert mapped["Policy_LineOfBusiness_BusinessAutoIndicator_A"] == "Yes"
    assert mapped["Policy_LineOfBusiness_UmbrellaIndicator_A"] == "Yes"


def test_a_genuine_other_line_survives():
    """ACORD has no Professional Liability box, so that row is doing its job."""
    mapped = {
        "Policy_LineOfBusiness_BusinessAutoIndicator_A": "Yes",
        "Policy_LineOfBusiness_OtherIndicator_A": "Yes",
        "Policy_LineOfBusiness_OtherLineOfBusinessDescription_A": "Professional Liability",
    }
    ps._enforce_post_fill_guards(mapped, _acord125(), {})
    assert mapped["Policy_LineOfBusiness_OtherLineOfBusinessDescription_A"] == \
        "Professional Liability"


def test_an_other_line_whose_standard_box_is_not_ticked_survives():
    """The guard removes a DUPLICATE, never information. With the Auto box
    unticked, this row is the only place that line is declared."""
    mapped = {
        "Policy_LineOfBusiness_OtherIndicator_A": "Yes",
        "Policy_LineOfBusiness_OtherLineOfBusinessDescription_A": "Commercial Auto",
    }
    ps._enforce_post_fill_guards(mapped, _acord125(), {})
    assert mapped["Policy_LineOfBusiness_OtherLineOfBusinessDescription_A"] == \
        "Commercial Auto"


def test_vague_other_wording_is_left_alone():
    """"Liability" fits three boxes, so it cannot be called a duplicate of any
    one of them."""
    mapped = {
        "Policy_LineOfBusiness_CommercialGeneralLiability_A": "Yes",
        "Policy_LineOfBusiness_OtherIndicator_A": "Yes",
        "Policy_LineOfBusiness_OtherLineOfBusinessDescription_A": "Liability",
    }
    ps._enforce_post_fill_guards(mapped, _acord125(), {})
    assert mapped["Policy_LineOfBusiness_OtherLineOfBusinessDescription_A"] == "Liability"


def test_indicator_index_covers_the_whole_lob_grid():
    schema = _acord125()
    boxes = [f for f in schema
             if f.startswith("Policy_LineOfBusiness_")
             and (schema[f] or {}).get("ft") == "/Btn"
             and "Other" not in f]
    index = ps._lob_indicator_index()
    missing = [f for f in boxes if f not in index]
    assert not missing, f"not derivable from their tooltips: {missing}"


def test_every_list_shaped_extraction_fact_is_registered():
    """STANDING GUARD. Harvests the list fields out of the real extraction schema
    and fails if any is missing from either registry, so the next list fact
    cannot be added the way this one nearly was."""
    import re
    # Harvesting this correctly took two attempts and both failure modes matter.
    #
    # Too greedy: sub-keys INSIDE a list-of-objects ("codes" within
    # gl_class_codes_by_location, "additional_insured_names" within
    # risk_transfer) get reported as unregistered top-level facts. So strip the
    # [{...}] bodies first and drop four-space-indented nested keys.
    #
    # Too strict: anchoring on "^  " alone misses top-level facts that share a
    # line with another key - the schema packs several per line, and
    # `lines_of_business` and `wc_class_codes` both live mid-line. That version
    # passed while silently checking 16 of 18 facts, which is exactly the
    # vacuously-green trap improving-ll.md C25 warns about.
    flat = re.sub(r'\[\{.*?\}\]', '[]', es._EXTRACT_SCHEMA, flags=re.S)
    declared = set(re.findall(r'"(\w+)":\s*\[', flat))
    declared -= set(re.findall(r'(?m)^    "(\w+)":\s*\[', flat))
    assert declared, "harvest found nothing - the schema format changed"
    # Self-check: two facts the harvest is known to be able to miss.
    for canary in ("coverage_lines", "lines_of_business"):
        assert canary in declared, f"harvest regressed - it no longer sees {canary}"
    unregistered = sorted(f for f in declared if f not in es._LIST_FIELDS)
    assert not unregistered, (
        f"list facts missing from _LIST_FIELDS: {unregistered}"
    )
    unmerged = sorted(f for f in declared if f not in es._LONG_DOC_LIST_KEYS)
    assert not unmerged, (
        "list facts missing from _LONG_DOC_LIST_KEYS - the cross-chunk merge "
        f"will keep only one chunk's rows for these: {unmerged}"
    )
