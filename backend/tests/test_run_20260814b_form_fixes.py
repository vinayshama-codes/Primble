"""Run-verification fixes, 2026-08-14 second batch - four ACORD 125 defects.

THE RUN (session f26d8685, the ORBIN package, verified against the ground-truth
fixture) shipped four wrong-value clusters, each pinned here by its literal
stamped values:

1. A FABRICATED ADDITIONAL INTEREST - FullName "Blanket Additional Insureds"
   (a GL endorsement TITLE), city/zip/phone all the PRODUCER's, email the
   carrier's claims address. Other guards blanked 22 of the row's fields and
   left these six, which reads like a real interest with sparse data.
2. DIRECT BILL STAMPED "No" against four dec pages printing DIRECT BILL -
   extraction merged `billing_plan` empty (the phrase only prints FUSED into
   label runs), so gap fill answered the checkbox from nothing. Plus the
   umbrella's audit note stamped as METHOD OF PAYMENT.
3. INSTALLATION WORK 100% - invented, and the document-wide percentage guard
   passed it because SOME unrelated page prints a "100%". The guard is now
   quote-gated (rule 8d): cite the sentence or the box stays blank.
4. ONE PREMISES AS THREE LOCATION ROWS - three printings of one address
   stamped as three rows, one of them a street-less orphan.
"""
import json
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("OPENAI_API_KEY", "sk-offline")

import services.extraction_service as es  # noqa: E402
import services.pdf_service as ps  # noqa: E402

BACKEND = os.path.join(os.path.dirname(__file__), "..")


def _schema(form):
    with open(os.path.join(BACKEND, "forms_schemas", f"{form}_schema.json"),
              encoding="utf-8") as fh:
        return json.load(fh)


def _gpt(filled=None, grounding=None):
    return {"filled_values": dict(filled or {}),
            "raw_text_fields": set(),
            "question_grounding": dict(grounding or {})}


# ── 1. The fabricated Additional Interest row ────────────────────────────────

_LIVE_AI_ROW = {
    "AdditionalInterest_FullName_A": "Blanket Additional Insureds",
    "AdditionalInterest_MailingAddress_CityName_A": "Englewood",
    "AdditionalInterest_MailingAddress_PostalCode_A": "80112-6072",
    "AdditionalInterest_Primary_PhoneNumber_A": "303-996-7800",
    "AdditionalInterest_Primary_EmailAddress_A": "claimreporting@emcins.com",
    "AdditionalInterest_AccountNumberIdentifier_A": "BBC7263",
}
_PRODUCER_FIELDS = {
    "Producer_MailingAddress_CityName_A": "Englewood",
    "Producer_MailingAddress_PostalCode_A": "80112-6072",
    "Producer_ContactPerson_PhoneNumber_A": "303-996-7800",
}


def test_the_live_fabricated_interest_row_dies_whole():
    """The client's literal run: every surviving fragment of the assembled
    interest goes, not just the borrowed ones - atomicity is the fix."""
    mapped = {**_PRODUCER_FIELDS, **_LIVE_AI_ROW}
    gpt = set(_LIVE_AI_ROW)
    dropped = ps._drop_fabricated_interest_rows(mapped, gpt)
    assert set(dropped) == set(_LIVE_AI_ROW)
    for f in _LIVE_AI_ROW:
        assert mapped[f] is None, f
    for f, v in _PRODUCER_FIELDS.items():
        assert mapped[f] == v, "the producer's own fields must be untouched"


def test_an_interest_with_its_own_identity_survives():
    mapped = {
        **_PRODUCER_FIELDS,
        "AdditionalInterest_FullName_A": "First National Bank of Boulder",
        "AdditionalInterest_MailingAddress_LineOne_A": "100 Bank Street",
        "AdditionalInterest_MailingAddress_CityName_A": "Boulder",
        "AdditionalInterest_MailingAddress_PostalCode_A": "80301",
    }
    gpt = {f for f in mapped if f.startswith("AdditionalInterest_")}
    assert ps._drop_fabricated_interest_rows(mapped, gpt) == []
    assert mapped["AdditionalInterest_FullName_A"]


def test_sharing_the_applicants_address_is_not_a_borrow():
    """A landlord or loss payee at the insured premises legitimately shares
    the APPLICANT's address - only producer/carrier details mark a borrow."""
    mapped = {
        **_PRODUCER_FIELDS,
        "NamedInsured_MailingAddress_CityName_A": "Denver",
        "NamedInsured_MailingAddress_PostalCode_A": "80216-3121",
        "AdditionalInterest_FullName_A": "Dahlia Street Properties LLC",
        "AdditionalInterest_MailingAddress_CityName_A": "Denver",
        "AdditionalInterest_MailingAddress_PostalCode_A": "80216-3121",
    }
    gpt = {f for f in mapped if f.startswith("AdditionalInterest_")}
    assert ps._drop_fabricated_interest_rows(mapped, gpt) == []


def test_an_interest_without_a_name_is_not_an_interest():
    mapped = {"AdditionalInterest_MailingAddress_LineOne_A": "100 Bank Street"}
    gpt = set(mapped)
    dropped = ps._drop_fabricated_interest_rows(mapped, gpt)
    assert dropped == ["AdditionalInterest_MailingAddress_LineOne_A"]
    assert mapped["AdditionalInterest_MailingAddress_LineOne_A"] is None


def test_a_producer_entered_interest_is_untouchable():
    """Only model-authored fields may be blanked - a row that arrived from
    facts or the producer stays even if it looks borrowed."""
    mapped = {**_PRODUCER_FIELDS, **_LIVE_AI_ROW}
    dropped = ps._drop_fabricated_interest_rows(mapped, set())
    assert dropped == []
    assert mapped["AdditionalInterest_FullName_A"] == "Blanket Additional Insureds"


# ── 2. Direct Bill and the method-of-payment box ─────────────────────────────

def test_billing_plan_backfills_from_the_fused_printed_phrase():
    """The live shape: DIRECT BILL prints only fused into a label run, so the
    fact merged empty. The closed two-value vocabulary recovers it."""
    facts = {}
    es._backfill_billing_plan(
        facts, "BILL: DIRECT BILL AGENT PHONE: (303)996-7800 AGENT NO. W6258")
    assert facts["billing_plan"]["value"] == "DIRECT BILL"
    assert facts["billing_plan"]["source"] == "dec_entry"


def test_prose_about_direct_billing_does_not_match():
    """Word-bounded: 'direct billing disputes' is not a billing method."""
    facts = {}
    es._backfill_billing_plan(
        facts, "we may review direct billing disputes with the insurer")
    assert "billing_plan" not in facts


def test_both_methods_printed_is_ambiguous_and_stays_blank():
    facts = {}
    es._backfill_billing_plan(
        facts, "Section 1: DIRECT BILL ... Section 2: AGENCY BILL")
    assert "billing_plan" not in facts


def test_the_backfill_never_overwrites():
    facts = {"billing_plan": "AGENCY BILL"}
    es._backfill_billing_plan(facts, "DIRECT BILL")
    assert facts["billing_plan"] == "AGENCY BILL"


def test_direct_bill_stamps_yes_and_method_description_from_the_fact():
    """End to end: with the fact present, Pass 1 owns BOTH payment boxes and
    the model can never stamp 'No' or borrow an audit note into them."""
    schema = _schema("ACORD_125")
    mapped, _ = ps.map_facts_to_form(
        {"billing_plan": "DIRECT BILL"}, schema, "ACORD_125",
        raw_text="PAYMENT: DIRECT BILL", pre_filled_gpt=_gpt())
    assert str(mapped.get("Policy_Payment_DirectBillIndicator_A")) in ("Yes", "Y")
    assert mapped.get("Policy_PaymentMethod_MethodDescription_A") == "DIRECT BILL"


# ── 3. The percentage guard is quote-gated now ───────────────────────────────

_PCT_FIELD = "CommercialStructure_InstallationRepairWorkPercent_A"


def test_the_live_defeat_an_unrelated_100pct_no_longer_saves_an_invented_one():
    """THE 2026-08-14 LIVE CASE: nothing states an installation split, but an
    unrelated endorsement prints '100%', which satisfied the old document-wide
    check. Quote-gating closes it: no citation, no percentage."""
    schema = _schema("ACORD_125")
    mapped, _ = ps.map_facts_to_form(
        {}, schema, "ACORD_125",
        raw_text="The carrier pays 100% of the audit noncompliance charge.",
        pre_filled_gpt=_gpt(filled={_PCT_FIELD: "100"}))
    assert mapped.get(_PCT_FIELD) is None


def test_a_percentage_with_its_own_verbatim_quote_survives():
    quote = "Installation work accounts for 15% of total sales."
    schema = _schema("ACORD_125")
    mapped, _ = ps.map_facts_to_form(
        {}, schema, "ACORD_125",
        raw_text="OPERATIONS NARRATIVE. " + quote,
        pre_filled_gpt=_gpt(filled={_PCT_FIELD: "15%"},
                            grounding={_PCT_FIELD: quote}))
    assert mapped.get(_PCT_FIELD) == "15%"


def test_a_fabricated_quote_cannot_save_a_percentage():
    """The quote must be verbatim in the uploaded text - citing a sentence the
    document never printed proves nothing."""
    schema = _schema("ACORD_125")
    mapped, _ = ps.map_facts_to_form(
        {}, schema, "ACORD_125",
        raw_text="RADIUS 100 TERRITORY 111",
        pre_filled_gpt=_gpt(filled={_PCT_FIELD: "15%"},
                            grounding={_PCT_FIELD: "Installation is 15% of sales."}))
    assert mapped.get(_PCT_FIELD) is None


def test_the_prompt_asks_for_the_percentage_quote():
    """The gate and the ask must move together (same rule as the evidence
    gate): blanking unquoted percentages without asking for quotes would blank
    every legitimate one."""
    assert "A PERCENTAGE field" in ps._PROMPT_SKELETON
    assert "question_grounding" in ps._PROMPT_SKELETON


# ── 4. One premises, one row ─────────────────────────────────────────────────

_LIVE_PREMISES = {
    "CommercialStructure_PhysicalAddress_LineOne_A": "4800 Dahlia St # D13 Denver",
    "CommercialStructure_PhysicalAddress_PostalCode_A": "80216-3121",
    "CommercialStructure_PhysicalAddress_CityName_B": "Denver",
    "CommercialStructure_PhysicalAddress_StateOrProvinceCode_B": "CO",
    "CommercialStructure_PhysicalAddress_PostalCode_B": "80216-3121",
    "CommercialStructure_PhysicalAddress_LineOne_C": "4800 Dahlia St D13 Denver",
    "CommercialStructure_PhysicalAddress_PostalCode_C": "80216-3121",
    "CommercialStructure_OperationsDescription_C": "COMMERCIAL GENERAL CONTRA",
}


def test_the_live_triple_folds_to_one_row_with_no_orphans():
    """Rows B (street-less fragment) and C ('#'-stripped variant) fold into A,
    and C's description goes with its row - no orphan remnants."""
    mapped = dict(_LIVE_PREMISES)
    gpt = set(_LIVE_PREMISES)
    dropped = ps._dedupe_stamped_premises_rows(mapped, gpt)
    assert mapped["CommercialStructure_PhysicalAddress_LineOne_A"]
    assert mapped["CommercialStructure_PhysicalAddress_PostalCode_A"]
    for f in _LIVE_PREMISES:
        if f.endswith(("_B", "_C")):
            assert mapped[f] is None, f
            assert f in dropped


def test_two_real_suites_never_fold():
    mapped = {
        "CommercialStructure_PhysicalAddress_LineOne_A": "4800 Dahlia St # D13",
        "CommercialStructure_PhysicalAddress_PostalCode_A": "80216-3121",
        "CommercialStructure_PhysicalAddress_LineOne_B": "4800 Dahlia St # D14",
        "CommercialStructure_PhysicalAddress_PostalCode_B": "80216-3121",
    }
    gpt = set(mapped)
    assert ps._dedupe_stamped_premises_rows(mapped, gpt) == []
    assert mapped["CommercialStructure_PhysicalAddress_LineOne_B"]


def test_a_streetless_row_with_a_different_zip_is_kept():
    """Street-less folding requires the zip to MATCH a kept row - a fragment
    pointing at a different zip is not provably the same premises."""
    mapped = {
        "CommercialStructure_PhysicalAddress_LineOne_A": "4800 Dahlia St # D13",
        "CommercialStructure_PhysicalAddress_PostalCode_A": "80216-3121",
        "CommercialStructure_PhysicalAddress_CityName_B": "Boulder",
        "CommercialStructure_PhysicalAddress_PostalCode_B": "80301",
    }
    gpt = set(mapped)
    assert ps._dedupe_stamped_premises_rows(mapped, gpt) == []
    assert mapped["CommercialStructure_PhysicalAddress_CityName_B"] == "Boulder"


def test_garaging_rows_are_never_touched_c18_safety():
    """Three trucks garaged in one city legitimately print identical
    Vehicle_PhysicalAddress rows - deleting those was the C18 disaster, and
    this guard is scoped by NAME so it structurally cannot repeat it."""
    mapped = {
        f"Vehicle_PhysicalAddress_CityName_{r}": "DENVER" for r in "ABC"
    }
    mapped.update({
        f"Vehicle_PhysicalAddress_PostalCode_{r}": "80216-3121" for r in "ABC"
    })
    gpt = set(mapped)
    assert ps._dedupe_stamped_premises_rows(mapped, gpt) == []
    assert all(v for v in mapped.values())


def test_the_dedupe_is_source_agnostic():
    """CONTRACT REVERSED after run 2 of 2026-08-14: the first cut spared
    Pass-1 rows and the very next run shipped the SAME tripled premises
    through Pass 1 (the consolidator's three-variant deadlock). A duplicate
    premises row is provably wrong from any door - the guard charter is
    'corrects values from any source'."""
    mapped = dict(_LIVE_PREMISES)
    dropped = ps._dedupe_stamped_premises_rows(mapped, set())
    assert dropped, "Pass-1 duplicate rows must fold too"
    assert mapped["CommercialStructure_PhysicalAddress_CityName_B"] is None
    assert mapped["CommercialStructure_PhysicalAddress_LineOne_C"] is None
    assert mapped["CommercialStructure_PhysicalAddress_LineOne_A"]


# ── 4b. The consolidator's three-variant deadlock (run 2, 2026-08-14) ────────

def test_three_parse_variants_of_one_premises_fold_to_one_row():
    """THE LIVE DEADLOCK: with three chained shapes every key sees TWO hosts,
    the exactly-one rule skipped all of them, and three rows stamped. Chained
    hosts that are pairwise the same premises must fold."""
    facts = {
        "property_locations": [
            {"address": "4800 DAHLIA ST # D13 DENVER, CO 80216-3121",
             "address_line1": "4800 DAHLIA ST # D13 DENVER",
             "address_zip": "80216-3121"},
            {"address": "4800 DAHLIA STREET D13, DENVER CO. 80216-3121",
             "address_line1": "4800 DAHLIA STREET D13",
             "address_city": "DENVER", "address_zip": "80216-3121"},
            {"address": "4800 DAHLIA STREET D13 DENVER CO. 80216-3121",
             "address_line1": "4800 DAHLIA STREET D13 DENVER",
             "address_zip": "80216-3121"},
        ],
        "locations": [
            "4800 DAHLIA ST # D13 DENVER, CO 80216-3121",
            "4800 DAHLIA STREET D13, DENVER CO. 80216-3121",
            "4800 DAHLIA STREET D13 DENVER CO. 80216-3121",
        ],
    }
    es._consolidate_property_locations(facts)
    assert len(facts["property_locations"]) == 1, \
        [e.get("address_line1") for e in facts["property_locations"]]


def test_a_fragment_between_two_different_premises_still_stays_put():
    """The ambiguity rule's real purpose survives the deadlock fix: a shape
    that could belong to TWO genuinely different premises folds into neither."""
    facts = {
        "property_locations": [
            {"address": "4800 Dahlia St D13 Denver, CO 80216",
             "address_line1": "4800 Dahlia St D13 Denver"},
            {"address": "4800 Dahlia St D13 Boulder, CO 80301",
             "address_line1": "4800 Dahlia St D13 Boulder"},
            {"address": "4800 Dahlia St D13",
             "address_line1": "4800 Dahlia St D13"},
        ],
        "locations": [],
    }
    es._consolidate_property_locations(facts)
    assert len(facts["property_locations"]) == 3


# ── 1b. Run 2's fabrication variant: borrowed from the INDEX, not the form ───

_RUN2_AI_ROW = {
    "AdditionalInterest_FullName_A":
        "Persons Or Organizations With Whom You Have Agreed In A Written "
        "Contract Or Agreement",
    "AdditionalInterest_MailingAddress_CityName_A": "Denver",
    "AdditionalInterest_MailingAddress_PostalCode_A": "80216-3121",
    "AdditionalInterest_Primary_PhoneNumber_A": "(720)200-3700",
    "AdditionalInterest_AccountNumberIdentifier_A": "0482854",
}
_RUN2_ENTRIES = [
    {"label": "SERVICING CARRIER", "value": "(720)200-3700", "owner": "carrier"},
    {"label": "Named Insured", "value": "ORBIN CONTRACTING LLC", "owner": "applicant"},
    {"label": "Account Number", "value": "0482854", "owner": "policy"},
]


def test_run2s_servicing_carrier_phone_is_a_borrow_via_the_index():
    """The live run-2 row: its phone is the SERVICING CARRIER's number, which
    no ACORD 125 field stamps - the form-side pool was blind. The dec index
    records it with owner=carrier, and the pool now reads the index."""
    mapped = dict(_RUN2_AI_ROW)
    gpt = set(_RUN2_AI_ROW)
    dropped = ps._drop_fabricated_interest_rows(
        mapped, gpt, {"dec_page_entries": _RUN2_ENTRIES})
    assert set(dropped) == set(_RUN2_AI_ROW)
    assert all(mapped[f] is None for f in _RUN2_AI_ROW)


def test_a_party_named_in_prose_survives_even_with_an_index_present():
    """A name the index never recorded must NOT die for that reason alone: the
    2026-08-13 evidence-gate contract protects a third party named in document
    PROSE (the owner behind a Yes answer), and prose parties are exactly what
    the index never records. A name-witness rule was tried and removed the
    same day it was written - the suite caught it blanking 'Meridian Fleet
    Leasing, LLC'. Only borrows and namelessness kill a row."""
    mapped = {
        "AdditionalInterest_FullName_A": "Meridian Fleet Leasing, LLC",
        "AdditionalInterest_MailingAddress_LineOne_A": "100 Bank Street",
        "AdditionalInterest_MailingAddress_CityName_A": "Boulder",
    }
    gpt = set(mapped)
    assert ps._drop_fabricated_interest_rows(
        mapped, gpt, {"dec_page_entries": _RUN2_ENTRIES}) == []
    assert mapped["AdditionalInterest_FullName_A"]


def test_no_facts_at_all_never_triggers_a_kill_beyond_the_form_pool():
    """Blanking on absent evidence is the C46 mistake - with no index and no
    borrowable form values, a named row with its own details stands."""
    mapped = {
        "AdditionalInterest_FullName_A": "First National Bank of Boulder",
        "AdditionalInterest_MailingAddress_LineOne_A": "100 Bank Street",
    }
    gpt = set(mapped)
    assert ps._drop_fabricated_interest_rows(mapped, gpt, {}) == []


# ── 2b. The GL exposure warning reads the index (run 2, 2026-08-14) ──────────

def test_the_gl_warning_is_suppressed_by_a_split_cell_payroll_basis():
    """Run 2's literal index shape: 'Prem Basis'='Payroll' + 'Exposure'=
    '$39,300' as separate entries. The document plainly states a payroll
    exposure basis; the warning must not fire."""
    from services.sqs_service import evaluate_stops
    facts = {"dec_page_entries": [
        {"label": "Prem Basis", "value": "Payroll", "owner": "policy"},
        {"label": "Exposure", "value": "$39,300", "owner": "policy"},
    ]}
    _hard, soft = evaluate_stops(facts, {"has_general_liability": True})
    assert not any("no revenue or payroll" in m for m in soft), soft


def test_the_gl_warning_is_suppressed_by_a_paired_payroll_entry():
    from services.sqs_service import evaluate_stops
    facts = {"dec_page_entries": [
        {"label": "PAYROLL", "value": "$39,300", "owner": "policy"},
    ]}
    _hard, soft = evaluate_stops(facts, {"has_general_liability": True})
    assert not any("no revenue or payroll" in m for m in soft), soft


def test_the_gl_warning_still_fires_when_nothing_states_payroll():
    from services.sqs_service import evaluate_stops
    facts = {"dec_page_entries": [
        {"label": "Prem Basis", "value": "Total Cost", "owner": "policy"},
    ]}
    _hard, soft = evaluate_stops(facts, {"has_general_liability": True})
    assert any("no revenue or payroll" in m for m in soft), soft


# ── 5. The index prompt chases full table rows and verbatim headings ─────────

def test_the_index_prompt_asks_for_every_numeric_column():
    """The GL class table's rate/premium cells (33.211, $1,305, 2.293, $803)
    were the run's remaining index misses - the ask now names them."""
    p = es._DEC_INDEX_SYSTEM_PROMPT
    assert "rate, factor, exposure, cost new" in p


def test_the_index_prompt_forbids_row_id_only_labels():
    """Run 2 regression of the per-cell rule: the model labeled a dozen IM
    sub-limits 'CONTRACTORS EQUIPMENT 801' each, so identical (label, value)
    pairs deduped away and 26 entries replaced 80. Labels must carry the
    printed caption, not just the row id."""
    p = es._DEC_INDEX_SYSTEM_PROMPT
    # Re-pinned 2026-08-23 to the v3 wording of the same two guarantees.
    assert "NEVER label several different cells with only the shared row identifier" in p
    assert "is that amount's LABEL" in p


def test_the_index_prompt_forbids_paraphrased_headings():
    """'COMMERCIAL UMBRELLA DECLARATIONS' was the model's own rewording of a
    heading the document never prints - 17 entries lost their section to it."""
    p = es._DEC_INDEX_SYSTEM_PROMPT
    assert "Never shorten, reorder or reword" in p
