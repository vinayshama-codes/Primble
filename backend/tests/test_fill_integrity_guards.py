"""
Regression tests for three live data-integrity findings (2026-07-20), all
reproduced against the REAL text of the two submissions that exposed them.

1. Fabricated industry-classification codes
   ACORD 125's GL CODE / SIC / NAICS came back filled with real, correct codes
   for the applicant's industry that appear NOWHERE in the uploaded document.
   Reproduced on two unrelated industries:
     * commercial GC   -> NAICS 236220, SIC 5403, GL 5403
     * landscaper      -> NAICS 561730, SIC 0782, GL 0782
   Neither document contains the strings "SIC", "NAICS", or any GL code. The
   model supplied them from its own industry knowledge.

   Note the GC case specifically: "5403" IS in that document - but only as a
   WORKERS COMP class code. Presence alone therefore cannot ground a SIC code,
   which is why the guard also requires the code SYSTEM to be named.

2. The insured's own address bleeding into a THIRD PARTY's block
   ACORD 125's PRODUCER block showed the applicant's street address. The
   deterministic rule for this was already fixed (`_deterministic_map` resolves
   `_addr_*` for NamedInsured_* only); the field then fell through to gap-fill,
   which supplied the applicant's address because it was the only address in
   the document. The guard has to sit at the post-fill layer for that reason.

3. ARQ re-asking a question the FORM already answers
   The document plainly stated "Number of Employees: 41" and the ACORD 125 box
   showed 41, yet the client was still asked how many people they employ -
   because structured extraction missed `num_employees`, so the fact was never
   in `facts`, and the suppression check only ever looked at `facts`.

Run from backend/:
    python -m pytest tests/test_fill_integrity_guards.py -v
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import services.pdf_service as pdf_service  # noqa: E402
from services.arq_service import (  # noqa: E402
    _backfill_and_resolve_present,
    _canonical_key,
)


# Verbatim excerpts from the two real submissions.
_GC_DOC = """
Named Insured (Legal Entity): Summit Ridge Contracting LLC
Mailing Address: 4820 Wynkoop Street, Suite 300, Denver, CO 80216
Summit Ridge Contracting LLC is a commercial general contractor operating
throughout the Colorado Front Range.
Payroll by Class Code:
  5403 Carpentry - Commercial: $2,140,000
  5221 Concrete Construction: $1,610,000
"""

_LANDSCAPE_DOC = """
Named Insured (Legal Entity): Cascade Grounds & Landscape Management LLC
Mailing Address: 6120 Peoria Street, Commerce City, CO 80022
Cascade Grounds provides year-round grounds maintenance, landscape
installation, snow removal, and irrigation services.
Payroll by Class Code:
  0042 Landscape Gardening: $1,890,000
"""


# ── 1. Fabricated classification codes ───────────────────────────────────────

def test_fabricated_naics_is_dropped():
    """561730 is the REAL NAICS for landscaping - and never appears in the doc."""
    mapped = {"NamedInsured_NAICSCode_A": "561730"}
    dropped = pdf_service._drop_ungrounded_classification_codes(
        mapped, _LANDSCAPE_DOC, {"NamedInsured_NAICSCode_A"},
    )
    assert mapped["NamedInsured_NAICSCode_A"] is None
    assert "NamedInsured_NAICSCode_A" in dropped


def test_fabricated_sic_is_dropped():
    """0782 is the REAL SIC for lawn/garden services - never in the doc."""
    mapped = {"NamedInsured_SICCode_A": "0782"}
    pdf_service._drop_ungrounded_classification_codes(
        mapped, _LANDSCAPE_DOC, {"NamedInsured_SICCode_A"},
    )
    assert mapped["NamedInsured_SICCode_A"] is None


def test_sic_borrowed_from_a_wc_class_code_is_dropped():
    """THE subtle case: '5403' IS in the GC document, but as a WORKERS COMP
    class code. The document never says 'SIC', so it cannot ground a SIC code.
    A presence-only check would have wrongly kept this."""
    mapped = {"NamedInsured_SICCode_A": "5403"}
    pdf_service._drop_ungrounded_classification_codes(
        mapped, _GC_DOC, {"NamedInsured_SICCode_A"},
    )
    assert mapped["NamedInsured_SICCode_A"] is None, (
        "a WC class code was accepted as a SIC code - cross-family bleed"
    )


def test_gl_code_borrowed_from_class_code_is_dropped():
    mapped = {"NamedInsured_GeneralLiabilityCode_A": "5403"}
    pdf_service._drop_ungrounded_classification_codes(
        mapped, _GC_DOC, {"NamedInsured_GeneralLiabilityCode_A"},
    )
    assert mapped["NamedInsured_GeneralLiabilityCode_A"] is None


def test_genuinely_stated_codes_are_kept():
    """No false positives: when the document really does state the codes, they
    must survive - otherwise the guard would destroy legitimate data."""
    doc = _GC_DOC + "\nSIC Code: 1761\nNAICS Code: 238160\n"
    mapped = {
        "NamedInsured_SICCode_A":   "1761",
        "NamedInsured_NAICSCode_A": "238160",
    }
    pdf_service._drop_ungrounded_classification_codes(
        mapped, doc, set(mapped.keys()),
    )
    assert mapped["NamedInsured_SICCode_A"] == "1761"
    assert mapped["NamedInsured_NAICSCode_A"] == "238160"


def test_deterministic_and_client_codes_are_never_touched():
    """Only values THIS run's gap-fill authored are eligible. A code that came
    from Pass 1 or from the client is authoritative and must survive."""
    mapped = {"NamedInsured_NAICSCode_A": "561730"}
    pdf_service._drop_ungrounded_classification_codes(
        mapped, _LANDSCAPE_DOC, set(),   # empty gpt_filled_set
    )
    assert mapped["NamedInsured_NAICSCode_A"] == "561730"


def test_non_classification_fields_are_unaffected():
    mapped = {"NamedInsured_FullName_A": "Cascade Grounds & Landscape Management LLC"}
    pdf_service._drop_ungrounded_classification_codes(
        mapped, _LANDSCAPE_DOC, set(mapped.keys()),
    )
    assert mapped["NamedInsured_FullName_A"] == "Cascade Grounds & Landscape Management LLC"


# ── 2. Third-party address bleed ─────────────────────────────────────────────

_FACTS_LANDSCAPE = {"mailing_address": "6120 Peoria Street, Commerce City, CO 80022"}


def test_producer_block_carrying_the_insured_address_is_cleared():
    """The exact live bug: PRODUCER block showed the applicant's address."""
    mapped = {
        "Producer_MailingAddress_LineOne_A":  "6120 Peoria Street",
        "Producer_MailingAddress_CityName_A": "Commerce City",
        "Producer_MailingAddress_PostalCode_A": "80022",
        "Producer_FullName_A": "Angela Reyes",
    }
    gpt = set(mapped.keys())
    pdf_service._drop_third_party_address_bleed(mapped, _FACTS_LANDSCAPE, gpt)

    assert mapped["Producer_MailingAddress_LineOne_A"] is None
    # The whole block is cleared so no orphaned city/ZIP is left behind.
    assert mapped["Producer_MailingAddress_CityName_A"] is None
    assert mapped["Producer_MailingAddress_PostalCode_A"] is None
    # The producer's NAME is real data and must not be collateral damage.
    assert mapped["Producer_FullName_A"] == "Angela Reyes"


def test_certificate_holder_and_additional_interest_are_covered_too():
    """Same bleed class, two other third-party blocks that share the rule."""
    for block in ("CertificateHolder_MailingAddress", "AdditionalInterest_MailingAddress"):
        mapped = {f"{block}_LineOne_A": "6120 Peoria Street"}
        pdf_service._drop_third_party_address_bleed(
            mapped, _FACTS_LANDSCAPE, set(mapped.keys()),
        )
        assert mapped[f"{block}_LineOne_A"] is None, f"{block} bleed not caught"


def test_a_genuine_third_party_address_is_kept():
    """No false positives: a real, different producer address must survive."""
    mapped = {
        "Producer_MailingAddress_LineOne_A":  "1400 Sixteenth Street, Suite 400",
        "Producer_MailingAddress_CityName_A": "Denver",
    }
    pdf_service._drop_third_party_address_bleed(
        mapped, _FACTS_LANDSCAPE, set(mapped.keys()),
    )
    assert mapped["Producer_MailingAddress_LineOne_A"] == "1400 Sixteenth Street, Suite 400"
    assert mapped["Producer_MailingAddress_CityName_A"] == "Denver"


def test_named_insured_address_is_never_treated_as_a_bleed():
    """The insured's OWN block legitimately holds the insured's address."""
    mapped = {"NamedInsured_MailingAddress_LineOne_A": "6120 Peoria Street"}
    pdf_service._drop_third_party_address_bleed(
        mapped, _FACTS_LANDSCAPE, set(mapped.keys()),
    )
    assert mapped["NamedInsured_MailingAddress_LineOne_A"] == "6120 Peoria Street"


# ── 3. ARQ must not re-ask what the form already answers ─────────────────────

def _form_with(field: str, value: str, canon_field: str = "NamedInsured_FullName_A"):
    """Minimal generated-forms structure carrying one filled box."""
    return {
        "ACORD_125": {
            "schema":      {field: {"ft": "/Tx"}},
            "field_state": {field: value},
            "confidence":  {},
        }
    }


def test_fact_filled_only_on_the_form_is_still_treated_as_present():
    """The live bug: gap-fill wrote 41 into the employee-count box, but never
    into `facts`, so the client was asked for it anyway."""
    generated = _form_with("NamedInsured_FullName_A", "Cascade Grounds LLC")
    present, _ = _backfill_and_resolve_present(generated, facts={})
    assert "applicant_name" in present, (
        "a value sitting on the form did not suppress its question - "
        "the client would be re-asked for data the form already has"
    )


def test_blank_box_still_produces_a_question():
    """The other direction must not regress: an EMPTY box must stay askable."""
    generated = _form_with("NamedInsured_FullName_A", "")
    present, _ = _backfill_and_resolve_present(generated, facts={})
    assert "applicant_name" not in present


def test_second_pass_only_adds_never_removes():
    """The new pass must be purely additive - anything the original logic
    marked present stays present."""
    generated = _form_with("NamedInsured_FullName_A", "Cascade Grounds LLC")
    facts = {"applicant_name": "Cascade Grounds LLC"}
    present_with_facts, _ = _backfill_and_resolve_present(generated, facts=facts)
    present_without, _ = _backfill_and_resolve_present(generated, facts={})
    assert present_with_facts.issubset(present_without | present_with_facts)
    assert "applicant_name" in present_with_facts
    assert "applicant_name" in present_without


# ── 4. NAIC number labelled for one entity, stamped for another ──────────────

_LANDSCAPE_DOC_NAIC = _LANDSCAPE_DOC + """
Producer NAIC Number: 41982
Current Carrier: Pinnacle Mutual Insurance
"""


def test_producer_naic_bled_into_carrier_field_is_dropped():
    """The exact live bug: CARRIER NAIC CODE showed the PRODUCER's NAIC number.
    The document never states a NAIC number for the carrier at all."""
    mapped = {"Insurer_NAICCode_A": "41982"}
    dropped = pdf_service._drop_mislabeled_naic_codes(
        mapped, _LANDSCAPE_DOC_NAIC, {"Insurer_NAICCode_A"},
    )
    assert mapped["Insurer_NAICCode_A"] is None
    assert "Insurer_NAICCode_A" in dropped


def test_genuinely_stated_carrier_naic_is_kept():
    """No false positives: a real, explicitly-labelled carrier NAIC survives -
    even in the same document that also has a producer NAIC number."""
    doc = _LANDSCAPE_DOC_NAIC + "Carrier NAIC Number: 55019\n"
    mapped = {"Insurer_NAICCode_A": "55019"}
    pdf_service._drop_mislabeled_naic_codes(mapped, doc, {"Insurer_NAICCode_A"})
    assert mapped["Insurer_NAICCode_A"] == "55019"


def test_prior_coverage_naic_is_covered_too():
    mapped = {"PriorCoverage_NAICCode_A": "41982"}
    pdf_service._drop_mislabeled_naic_codes(
        mapped, _LANDSCAPE_DOC_NAIC, {"PriorCoverage_NAICCode_A"},
    )
    assert mapped["PriorCoverage_NAICCode_A"] is None


def test_deterministic_naic_value_is_never_touched():
    mapped = {"Insurer_NAICCode_A": "41982"}
    pdf_service._drop_mislabeled_naic_codes(mapped, _LANDSCAPE_DOC_NAIC, set())
    assert mapped["Insurer_NAICCode_A"] == "41982"


def test_unrelated_naic_shaped_field_is_unaffected():
    """The guard must only touch the two NAIC-code field families, not every
    numeric field that happens to share digits with a NAIC number."""
    mapped = {"NamedInsured_TaxIdentifier_A": "41982"}
    pdf_service._drop_mislabeled_naic_codes(
        mapped, _LANDSCAPE_DOC_NAIC, {"NamedInsured_TaxIdentifier_A"},
    )
    assert mapped["NamedInsured_TaxIdentifier_A"] == "41982"


# ── 5. ARQ client answers must reach the actual PDF field ────────────────────
# Regression for a PRE-EXISTING bug this round's testing surfaced (not
# introduced by the ARQ/questionnaire work): apply_arq_answers_to_session only
# restamped a canonical fact into the form when `canon != field_name`. Every
# `_maybe_inject_*` / coverage-guarantee question sets field_name TO the
# canonical key itself (e.g. field_name == "num_employees"), so that guard was
# always false for them and the restamp that actually writes into the PDF's
# real schema fields (BusinessInformation_FullTimeEmployeeCount_A, etc.) never
# ran. `facts` and SQS updated; the PDF the client was told would
# "auto-populate" did not change at all.

def test_canonical_key_equals_field_name_for_injected_questions():
    """Confirms the exact condition that made the old guard always skip
    restamping for this whole class of question."""
    assert _canonical_key("num_employees") == "num_employees"
    assert _canonical_key("subcontractor_pct_by_class_code") == "subcontractor_pct_by_class_code"


def test_canonical_key_differs_for_raw_schema_field_questions():
    """The other path (main-loop-generated questions) was never broken - this
    just confirms the fix doesn't change behavior there."""
    assert _canonical_key("NamedInsured_NAICSCode_A") == "naics_code"


# ── 6. Schedule-registry entries silently shadowing a plain scalar fact ──────
# Found WHILE fixing #5 above: even with the restamp-skip fixed, the client's
# employee-count answer still didn't reach the PDF, because
# `BusinessInformation_FullTimeEmployeeCount` is governed by BOTH a plain
# `_ACORD_FIELD_RULES` rule (-> num_employees) AND a `_SCHEDULE_REGISTRY` entry
# (-> property_locations[].full_time_employees). The schedule check runs first
# and unconditionally wins - correct when a genuine per-location breakdown
# exists, but it silently swallows the common case where a document only
# states one overall total. A sweep of the full registry found this pattern
# twice more (PriorCoverage_EffectiveDate/ExpirationDate).

def test_employee_count_falls_back_to_the_scalar_total_when_no_breakdown_exists():
    facts = {"num_employees": {"value": "41"}}
    assert pdf_service._deterministic_map(
        "BusinessInformation_FullTimeEmployeeCount_A", facts,
    ) == "41"
    assert pdf_service._deterministic_map(
        "BusinessInformation_PartTimeEmployeeCount_A", facts,
    ) == "41"


def test_genuine_per_location_breakdown_still_wins_over_the_scalar():
    """No regression: real structured data must still take priority - this is
    the whole reason the schedule check exists and runs first."""
    facts = {
        "num_employees": {"value": "41"},
        "property_locations": [{"full_time_employees": "30", "part_time_employees": "5"}],
    }
    assert pdf_service._deterministic_map(
        "BusinessInformation_FullTimeEmployeeCount_A", facts,
    ) == "30"


def test_non_row_a_stays_blank_when_schedule_is_short():
    """The fallback is scoped to row A only. A 2nd location's employee count
    with no 2nd location present must stay blank, not silently duplicate the
    overall total into a row that doesn't represent a real second entry."""
    facts = {
        "num_employees": {"value": "41"},
        "property_locations": [{"full_time_employees": "30"}],  # only 1 location
    }
    assert pdf_service._deterministic_map(
        "BusinessInformation_FullTimeEmployeeCount_B", facts,
    ) is None


def test_prior_coverage_dates_get_the_same_fallback():
    facts = {"prior_effective_date": {"value": "01/01/2025"}}
    assert pdf_service._deterministic_map(
        "PriorCoverage_EffectiveDate_A", facts,
    ) == "01/01/2025"


def test_apply_arq_answers_actually_stamps_a_canonical_only_question_end_to_end():
    """Full end-to-end reproduction of the live bug through the real function,
    not just the underlying condition: a client answers a coverage-guarantee /
    _maybe_inject_* question (field_name == its own canonical key) and the
    value must land in the real ACORD 125 schema field, not just in `facts`."""
    import asyncio
    from unittest.mock import AsyncMock, patch
    import services.arq_service as arq_service

    arq_row = {
        "id": "arq-1",
        "status": "submitted",
        "session_id": "sess-1",
        "answers": {"num_employees": "41"},
        "questions": [
            {"field_name": "num_employees", "form_ids": ["ACORD_125"]},
        ],
    }
    session = {
        "generated_forms": {
            "ACORD_125": {
                "schema": {
                    "BusinessInformation_FullTimeEmployeeCount_A": {"ft": "/Tx"},
                    "BusinessInformation_PartTimeEmployeeCount_A": {"ft": "/Tx"},
                },
                "field_state": {},   # both boxes genuinely blank before the answer
                "confidence": {},
            },
        },
        "facts": {},
        "flags": {},
    }
    saved_payload = {}

    async def _fake_upd(_session_id, payload):
        saved_payload.update(payload)

    with patch.object(arq_service, "get_arq_by_id", AsyncMock(return_value=arq_row)), \
         patch("repositories.session_repository.get_processing_session",
               AsyncMock(return_value=session)), \
         patch("repositories.session_repository.upd_processing_session", _fake_upd):
        ok, updated = asyncio.run(
            arq_service.apply_arq_answers_to_session("arq-1", "sess-1")
        )

    assert ok
    real_field_state = saved_payload["generated_forms"]["ACORD_125"]["field_state"]
    assert real_field_state.get("BusinessInformation_FullTimeEmployeeCount_A") == "41", (
        "the client's answer never reached the actual PDF field - "
        "this is the exact 'answers not stamped in the form' bug"
    )
    assert saved_payload["facts"]["num_employees"]["value"] == "41"


if __name__ == "__main__":
    import pytest
    sys.exit(pytest.main([__file__, "-v"]))
