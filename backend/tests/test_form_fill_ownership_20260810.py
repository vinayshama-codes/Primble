"""Regression tests for the 2026-08-10 ownership / row-integrity fixes.

Every scenario replays the CLIENT'S LITERAL values from the Orbin test-7-29
report (per the standing replay-verbatim rule), then locks the generic rule:

1. "Other" LOB rows are owned deterministically: filled only by a GRANTED
   coverage line that matches no standard checkbox; standard lines and
   no-coverage mentions never land there. (Live form showed "Property",
   "Liability", "Crime and Fidelity", "Workers' Compensation" and duplicate
   "Commercial Auto"/"Commercial Liability Umbrella" custom rows.)

2. compute_form_gaps applies the SAME authoritative-blank contract as
   map_facts_to_form — owner-resolved blanks are never shipped to the LLM.

3. Location consolidation drops bare unit fragments ("# D13", "Ste 400") and
   the producer's own address; a parsed line2 is schedule-bound so the unit
   number is never duplicated across LineOne and LineTwo.

4. Unanchored entity rows / anchored detail boxes are CLEARED, not demoted
   (client: "These are not usable records ... should be removed").

5. The gap-fill prompt carries the entity-discipline rule (claims/servicing
   numbers, producer data and relabeled identifiers must not cross parties).
"""

import json
import os

import pytest

_BACKEND = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _schema_125() -> dict:
    with open(os.path.join(_BACKEND, "forms_schemas", "ACORD_125_schema.json"),
              encoding="utf-8") as fh:
        return json.load(fh)


_ORBIN_LINES = [
    {"line": "Commercial General Liability", "premium": "$3,954"},
    {"line": "Business Auto", "premium": "$2,991"},
    {"line": "Commercial Inland Marine", "premium": "$300"},
    {"line": "Commercial Liability Umbrella", "premium": "$3,418"},
]

_OTHER_DESC_ROWS = [f"Policy_LineOfBusiness_OtherLineOfBusinessDescription_{r}"
                    for r in "ABCDEF"]
_OTHER_IND_ROWS = [f"Policy_LineOfBusiness_OtherIndicator_{r}" for r in "ABCDEF"]


# ── 1. Other-LOB rows ────────────────────────────────────────────────────────

def test_standard_lines_never_fill_the_other_rows():
    """The Orbin package: every granted line has its own checkbox, so every
    'Other' row must be an authoritative blank — not an LLM question."""
    from services.pdf_service import compute_form_gaps
    schema = _schema_125()
    mapped, unmatched, det = compute_form_gaps(
        "ACORD_125", schema, {"coverage_lines": _ORBIN_LINES},
    )
    for f in _OTHER_DESC_ROWS + _OTHER_IND_ROWS:
        assert mapped.get(f) is None, f"{f} filled with {mapped.get(f)!r}"
        assert f not in unmatched, f"{f} was shipped to the LLM"
        assert f in det, f"{f} not marked deterministic"


def test_no_coverage_mention_never_fills_an_other_row():
    """A line the dec page declares NOT covered carries no premium/limit —
    it must never appear as a custom 'Other' line."""
    from services.pdf_service import _resolve_other_lob_row
    facts = {"coverage_lines": _ORBIN_LINES + [
        {"line": "Property", "premium": None},
        {"line": "Crime and Fidelity", "premium": "No Coverage"},
        {"line": "Workers' Compensation"},
    ]}
    for f in _OTHER_DESC_ROWS:
        assert _resolve_other_lob_row(f, facts) is None


def test_a_genuine_nonstandard_granted_line_fills_row_a():
    from services.pdf_service import _resolve_other_lob_row
    facts = {"coverage_lines": _ORBIN_LINES + [
        {"line": "Employment Practices Liability", "premium": "$500"},
    ]}
    assert _resolve_other_lob_row(
        "Policy_LineOfBusiness_OtherLineOfBusinessDescription_A", facts
    ) == "Employment Practices Liability"
    assert _resolve_other_lob_row(
        "Policy_LineOfBusiness_OtherIndicator_A", facts) == "Yes"
    # Row B stays blank — only one non-standard line exists.
    assert _resolve_other_lob_row(
        "Policy_LineOfBusiness_OtherLineOfBusinessDescription_B", facts) is None


def test_without_per_line_data_the_legacy_path_is_untouched():
    """No coverage_lines fact -> resolver steps aside -> the rows stay
    LLM-eligible exactly as before (coverage preserved)."""
    from services.pdf_service import compute_form_gaps
    schema = _schema_125()
    _mapped, unmatched, _det = compute_form_gaps("ACORD_125", schema, {})
    assert "Policy_LineOfBusiness_OtherLineOfBusinessDescription_A" in unmatched


# ── 2. compute_form_gaps mirrors the authoritative-blank contract ────────────

def test_owner_resolved_blanks_are_not_shipped_to_the_llm():
    from services.pdf_service import compute_form_gaps
    schema = _schema_125()
    facts = {"coverage_lines": [
        {"line": "Commercial General Liability", "premium": "$3,954",
         "policy_number": "BBC7263-26"},
        {"line": "Business Auto", "premium": "$2,991",
         "policy_number": "6E7-40-02---26"},
    ]}
    _mapped, unmatched, det = compute_form_gaps("ACORD_125", schema, facts)
    # Q4 rows beyond the two real entries: owned, blank, never asked.
    for f in ("OtherPolicy_LineOfBusinessCode_C", "OtherPolicy_LineOfBusinessCode_D",
              "OtherPolicy_PolicyNumberIdentifier_C"):
        assert f not in unmatched, f"{f} was shipped to the LLM"
        assert f in det
    # Prior-coverage grid with no prior_coverage_by_line fact: owned, blank.
    assert "PriorCoverage_GeneralLiability_PolicyNumberIdentifier_A" not in unmatched


# ── 3. Location consolidation ────────────────────────────────────────────────

def test_unit_fragments_and_producer_address_are_not_locations():
    """The client's literal values: one real premises, a '# D13' fragment, a
    'Ste 400' fragment, and the producer's own street — one row survives."""
    from services.extraction_service import _consolidate_property_locations
    facts = {
        "locations": [
            "4800 Dahlia St # D13, Denver, CO 80216-3121",
            "# D13",
            "Ste 400",
            "9780 S Meridian Blvd Ste 400, Englewood, CO 80112-6072",
        ],
        "producer_address": "9780 S Meridian Blvd Ste 400, Englewood, CO 80112-6072",
    }
    _consolidate_property_locations(facts)
    rows = facts["property_locations"]
    assert len(rows) == 1, [r.get("address") for r in rows]
    row = rows[0]
    assert row["location_number"] == "1"
    assert row["address_line1"] == "4800 Dahlia St # D13"
    assert row["address_city"] == "Denver"
    assert row["address_zip"] == "80216-3121"
    assert row.get("address_line2") in (None, "")


def test_a_real_suite_line_two_still_stamps():
    from services.extraction_service import _consolidate_property_locations
    from services.pdf_service import _resolve_schedule_row
    facts = {"locations": ["4800 Dahlia St, # D13, Denver, CO 80216-3121"]}
    _consolidate_property_locations(facts)
    row = facts["property_locations"][0]
    assert row["address_line1"] == "4800 Dahlia St"
    assert row["address_line2"] == "# D13"
    assert _resolve_schedule_row(
        "CommercialStructure_PhysicalAddress_LineTwo_A", facts) == "# D13"


def test_line_two_is_owned_blank_when_no_suite_exists():
    """No separate line2 -> the box is a schedule blank, never an LLM guess —
    the '# D13 printed twice' defect cannot recur."""
    from services.extraction_service import _consolidate_property_locations
    from services.pdf_service import compute_form_gaps
    facts = {"locations": ["4800 Dahlia St # D13, Denver, CO 80216-3121"]}
    _consolidate_property_locations(facts)
    _mapped, unmatched, det = compute_form_gaps("ACORD_125", _schema_125(), facts)
    f = "CommercialStructure_PhysicalAddress_LineTwo_A"
    assert f not in unmatched
    assert f in det


def test_a_multi_location_business_keeps_every_real_location():
    """Coverage guard: the fragment filter must never eat a genuine second
    premises."""
    from services.extraction_service import _consolidate_property_locations
    facts = {"locations": [
        "4800 Dahlia St # D13, Denver, CO 80216-3121",
        "2100 Broadway, Boulder, CO 80302",
    ]}
    _consolidate_property_locations(facts)
    assert len(facts["property_locations"]) == 2


# ── 4. Unanchored rows are cleared ───────────────────────────────────────────

def test_orphan_additional_interest_and_detail_boxes_are_cleared():
    from services.pdf_service import map_facts_to_form
    schema = _schema_125()
    planted = {
        # The live form's residue: a ticked interest + the insured's own city,
        # with NO name — and an ownership percent with NO parent company.
        "AdditionalInterest_Interest_AdditionalInsuredIndicator_A": "Yes",
        "AdditionalInterest_MailingAddress_CityName_A": "Denver",
        "Subsidiary_ParentOwnershipPercent_A": "100%",
    }
    mapped, _conf = map_facts_to_form(
        {}, schema, form_id="ACORD_125", raw_text="Denver 100%",
        pre_filled_gpt={"filled_values": planted, "raw_text_fields": set()},
    )
    for f in planted:
        assert mapped.get(f) is None, f"{f} survived with {mapped.get(f)!r}"


def test_a_named_additional_interest_keeps_its_row():
    """Coverage guard: with a real name present the row is legitimate."""
    from services.pdf_service import map_facts_to_form
    schema = _schema_125()
    planted = {
        "AdditionalInterest_FullName_A": "First Bank of Denver",
        "AdditionalInterest_Interest_MortgageeIndicator_A": "Yes",
        "AdditionalInterest_MailingAddress_CityName_A": "Denver",
    }
    mapped, _conf = map_facts_to_form(
        {}, schema, form_id="ACORD_125",
        raw_text="Mortgagee: First Bank of Denver, Denver",
        pre_filled_gpt={"filled_values": planted, "raw_text_fields": set()},
    )
    # Case-insensitive: display canonicalization title-cases the name.
    assert str(mapped.get("AdditionalInterest_FullName_A")).lower() == "first bank of denver"
    assert mapped.get("AdditionalInterest_MailingAddress_CityName_A") == "Denver"


# ── 5. Prompt entity discipline ──────────────────────────────────────────────

def test_gap_fill_prompt_carries_entity_discipline():
    from services.pdf_service import _PROMPT_SKELETON
    assert "ENTITY DISCIPLINE" in _PROMPT_SKELETON
    assert "Claim Reporting" in _PROMPT_SKELETON
    assert "Agent" in _PROMPT_SKELETON


if __name__ == "__main__":
    import sys
    sys.exit(pytest.main([__file__, "-q"]))
