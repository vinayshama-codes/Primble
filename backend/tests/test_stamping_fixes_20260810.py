"""Regression tests for the 2026-08-10 stamping fixes.

Four fixes, each locked here against reintroduction:

A. Alias-bridge entity discipline: the Producer_ContactPerson_* bridge entries
   must read PRODUCER-scoped facts, never the applicant's contact_* facts, and
   the NamedInsured_BusinessStartDate bridge must read the DATE fact, never the
   years_in_business duration. (Both were live bugs: the applicant's
   name/phone/email stamped into the Producer block, and "15" stamped into a
   date box, whenever the correct fact was absent.)

B. Row-aware indicator guard: a _B/_C row must never inherit the PRIMARY
   record's scalar facts through _INDICATOR_RULES (measured: 22 fields across
   the 17 real schemas, e.g. the 1st insured's entity_type ticking LLC on the
   empty 2nd/3rd Named Insured rows). Those rows fall through to gap fill,
   where the evidence gate governs the answer — so this is a rerouting, not a
   coverage removal.

C. Prompt label honesty: the gap-fill prompt must never claim extraction facts
   are "verified" — no verification of extraction output against the document
   exists anywhere in the pipeline.

D. LOB premium presence backstop: a line-of-business premium amount (>= 4
   digits) that appears nowhere in the uploaded document text must not stamp.
   Amounts under 4 digits are deliberately skipped (fail-open), and amounts
   present in the text stamp exactly as before.
"""

import json
import os

import pytest

_BACKEND = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_SCHEMA_125 = os.path.join(_BACKEND, "forms_schemas", "ACORD_125_schema.json")


def _load_125_schema() -> dict:
    with open(_SCHEMA_125, encoding="utf-8") as fh:
        return json.load(fh)


# ── A. Alias-bridge entity discipline ────────────────────────────────────────

def test_producer_contact_bridge_reads_producer_scoped_facts():
    from services.alias_stamper import CANONICAL_TO_EXTRACTION
    assert CANONICAL_TO_EXTRACTION["producer_contact_person_full_name"] == "producer_contact_name"
    assert CANONICAL_TO_EXTRACTION["producer_contact_person_phone_number"] == "producer_contact_phone"
    assert CANONICAL_TO_EXTRACTION["producer_contact_person_email_address"] == "producer_contact_email"


def test_business_start_date_bridge_reads_the_date_fact():
    from services.alias_stamper import CANONICAL_TO_EXTRACTION
    assert CANONICAL_TO_EXTRACTION["named_insured_business_start_date"] == "business_start_date"


def test_applicant_contact_never_stamps_into_producer_block():
    """The live bug, end to end: applicant contact present, producer contact
    absent -> the Producer block must NOT be filled from the applicant."""
    from services.alias_stamper import stamp_form_fields
    facts = {
        "contact_name": "JANE APPLICANT",
        "contact_phone": "303-555-0000",
        "contact_email": "jane@applicant.com",
    }
    filled = stamp_form_fields("ACORD_125", facts, [
        "Producer_ContactPerson_FullName_A",
        "Producer_ContactPerson_PhoneNumber_A",
        "Producer_ContactPerson_EmailAddress_A",
    ])
    assert filled == {}, f"applicant contact leaked into the Producer block: {filled}"


def test_producer_contact_still_stamps_from_its_own_facts():
    """Coverage check: with the producer's OWN facts present, the alias path
    still fills the Producer block — the fix rerouted, it did not blank."""
    from services.alias_stamper import stamp_form_fields
    facts = {
        "producer_contact_name": "PAT PRODUCER",
        "producer_contact_phone": "720-555-1111",
        "producer_contact_email": "pat@agency.com",
        "contact_name": "JANE APPLICANT",
    }
    filled = stamp_form_fields("ACORD_125", facts, [
        "Producer_ContactPerson_FullName_A",
        "Producer_ContactPerson_PhoneNumber_A",
        "Producer_ContactPerson_EmailAddress_A",
    ])
    assert filled.get("Producer_ContactPerson_FullName_A") == "PAT PRODUCER"
    assert filled.get("Producer_ContactPerson_PhoneNumber_A") == "720-555-1111"
    assert filled.get("Producer_ContactPerson_EmailAddress_A") == "pat@agency.com"


def test_duration_never_stamps_into_the_business_start_date_box():
    from services.alias_stamper import stamp_form_fields
    filled = stamp_form_fields(
        "ACORD_125", {"years_in_business": "15"}, ["NamedInsured_BusinessStartDate_A"],
    )
    assert filled == {}, f"a duration reached a date box via the alias bridge: {filled}"
    filled = stamp_form_fields(
        "ACORD_125", {"business_start_date": "03/15/2010"}, ["NamedInsured_BusinessStartDate_A"],
    )
    assert filled.get("NamedInsured_BusinessStartDate_A") == "03/15/2010"


# ── B. Row-aware indicator guard ─────────────────────────────────────────────

def test_second_insured_rows_do_not_inherit_primary_entity_type():
    from services.pdf_service import _deterministic_map
    facts = {"entity_type": "LLC"}
    # Row A: the primary record — unchanged, still resolves from the scalar.
    assert _deterministic_map(
        "NamedInsured_LegalEntity_LimitedLiabilityCorporationIndicator_A", facts
    ) == "Yes"
    # Rows B/C: must NOT inherit row A's fact. None -> falls through to gap
    # fill (evidence-gated), never a silent deterministic tick.
    for row in ("B", "C"):
        got = _deterministic_map(
            f"NamedInsured_LegalEntity_LimitedLiabilityCorporationIndicator_{row}", facts
        )
        assert got in (None, "UNMATCHED"), (
            f"row {row} inherited the primary insured's entity_type: {got!r}"
        )


def test_business_type_row_b_does_not_inherit_operations_description():
    from services.pdf_service import _deterministic_map
    facts = {"operations_description": "retail bakery and coffee shop"}
    assert _deterministic_map(
        "BusinessInformation_BusinessType_RetailIndicator_A", facts) == "Yes"
    got = _deterministic_map(
        "BusinessInformation_BusinessType_RetailIndicator_B", facts)
    assert got in (None, "UNMATCHED")


def test_row_b_indicator_is_rerouted_to_gap_fill_not_blanked():
    """Coverage guarantee for the fix: the row-B checkbox leaves the
    deterministic path and JOINS the LLM-eligible set — it is not an
    authoritative blank."""
    from services.pdf_service import compute_form_gaps
    schema = _load_125_schema()
    mapped, unmatched, det = compute_form_gaps(
        "ACORD_125", schema, {"entity_type": "LLC"},
    )
    f_b = "NamedInsured_LegalEntity_LimitedLiabilityCorporationIndicator_B"
    assert mapped.get(f_b) is None
    assert f_b in unmatched, "row-B indicator must stay LLM-eligible (coverage)"
    # Row A still resolved deterministically.
    f_a = "NamedInsured_LegalEntity_LimitedLiabilityCorporationIndicator_A"
    assert mapped.get(f_a) == "Yes"


def test_no_indicator_rule_fires_on_any_non_primary_row_of_any_form():
    """The measured defect class, swept across every real schema: zero _B.._N
    fields may resolve 'Yes'/'No' from the scalar _INDICATOR_RULES path."""
    import re
    from services.pdf_service import (
        _INDICATOR_RULES, _deterministic_map, _resolve_schedule_row, _SCHED_SKIP,
    )
    schemas_dir = os.path.join(_BACKEND, "forms_schemas")
    # Facts that satisfy every scalar indicator rule, so any row-blind rule
    # that CAN fire, WILL fire.
    facts = {}
    for _sub, (fk, mv) in _INDICATOR_RULES.items():
        facts[fk] = [{"x": "y"}] if mv == "non-empty" else mv
    offenders = []
    for fname in sorted(os.listdir(schemas_dir)):
        if not fname.endswith("_schema.json"):
            continue
        with open(os.path.join(schemas_dir, fname), encoding="utf-8") as fh:
            schema = json.load(fh)
        for field in schema:
            m = re.match(r"^(.+)_([B-N])$", field)
            if not m:
                continue
            # Schedule-bound fields resolve from row-scoped lists — exempt.
            if _resolve_schedule_row(field, facts) is not _SCHED_SKIP:
                continue
            if not any(sub.lower() in field.lower() for sub in _INDICATOR_RULES):
                continue
            got = _deterministic_map(field, facts)
            if got in ("Yes", "No"):
                offenders.append((fname, field, got))
    assert not offenders, (
        f"non-primary rows resolving from policy-level scalar facts: {offenders[:8]}"
    )


# ── C. Prompt label honesty ──────────────────────────────────────────────────

def test_gap_fill_prompt_never_claims_facts_are_verified():
    import services.pdf_service as pdf_service
    src_path = pdf_service.__file__
    with open(src_path, encoding="utf-8") as fh:
        src = fh.read()
    assert "already verified by document analyzer" not in src, (
        "the gap-fill prompt claims extraction facts are verified — no such "
        "verification exists anywhere in the pipeline"
    )
    from services.pdf_service import _PROMPT_SKELETON
    assert "UNVERIFIED" in _PROMPT_SKELETON
    assert "document text wins" in _PROMPT_SKELETON


# ── D. LOB premium presence backstop ─────────────────────────────────────────

def _run_125(facts: dict, raw_text: str):
    from services.pdf_service import map_facts_to_form
    schema = _load_125_schema()
    mapped, _conf = map_facts_to_form(
        facts, schema, form_id="ACORD_125", raw_text=raw_text,
        pre_filled_gpt={"filled_values": {}, "raw_text_fields": set()},
    )
    return mapped


_GL_PREMIUM_BOX = "GeneralLiabilityLineOfBusiness_TotalPremiumAmount_A"


def test_fabricated_premium_amount_does_not_stamp():
    facts = {"coverage_lines": [
        {"line": "Commercial General Liability", "premium": "$9,876"},
    ]}
    raw = "COMMERCIAL GENERAL LIABILITY COVERAGE PART. Total premium is shown elsewhere."
    mapped = _run_125(facts, raw)
    assert mapped.get(_GL_PREMIUM_BOX) is None, (
        "a premium amount appearing nowhere in the document was stamped"
    )


def test_premium_present_in_document_still_stamps():
    facts = {"coverage_lines": [
        {"line": "Commercial General Liability", "premium": "$3,954"},
    ]}
    raw = "COMMERCIAL GENERAL LIABILITY $3,954 annual premium for the policy period."
    mapped = _run_125(facts, raw)
    assert mapped.get(_GL_PREMIUM_BOX) == "$3,954"


def test_short_premium_amounts_fail_open():
    """Amounts under 4 digits sit below the presence check's reliable-match
    floor — they must stamp exactly as before (never blanked by this guard)."""
    facts = {"coverage_lines": [
        {"line": "Commercial Inland Marine", "premium": "$300"},
    ]}
    raw = "text that does not contain the amount at all"
    mapped = _run_125(facts, raw)
    assert mapped.get("CommercialInlandMarineLineOfBusiness_PremiumAmount_A") == "$300"


if __name__ == "__main__":
    import sys
    sys.exit(pytest.main([__file__, "-q"]))
