"""Run 6 of 2026-08-13: five survivors, each through a door the guards missed.

    FAX = phone (5th time)    <- Pass 1's substring rule stamped the mislabelled
                                 `producer_fax` fact RAW; the owning resolver was
                                 never consulted where values are PRODUCED
    Q3 = Y  "Limited Pollution Coverage - Work Sites"  <- the label, $150 dropped,
                                 so the money-tail requirement missed it
    Q9/Q10 = Y  "ERIN ROYAL"  <- a name-only record's name spent as evidence twice
    Q14 deps = junk, Q14 blank <- dependents standing under a question that is
                                 not Yes (the mirror of YES_WITHOUT_SUBSTANTIATION)
    ADDITIONAL INTEREST name = "Blanket Additional Insured Status For..."
                              <- an endorsement TITLE as a party name
    Premises ops = "COMMERCIAL GENERAL CONTRA" <- the truncated header, back
                                 through a DETERMINISTIC door this time
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("OPENAI_API_KEY", "sk-offline")

import services.pdf_service as ps                                 # noqa: E402


# ── 1. FAX through the Pass-1 door ───────────────────────────────────────────

def test_the_mislabelled_fax_fact_never_stamps_through_pass_1():
    """END TO END through _deterministic_map, which is where run 6's fax came
    from - being an authoritative blank only closed the gap-fill door."""
    facts = {"producer_fax": "303-996-7800",
             "producer_phone": "303-996-7800",
             "producer_name": "Commercial Risk Solutions, Inc."}
    got = ps._deterministic_map("Producer_FaxNumber_A", facts)
    assert got is None, f"the phone stamped as a fax again: {got!r}"


def test_the_identity_check_sweeps_every_phone_fact():
    """Run 6's near-miss: if the one hand-listed phone key was not captured
    that run, the mislabel sailed through on a technicality. Any phone-bearing
    fact now counts."""
    facts = {"producer_fax": "(303) 996-7800",
             "applicant_business_phone": "303.996.7800"}
    assert ps._resolve_party_fax("Producer_FaxNumber_A", facts) is None


def test_a_genuine_fax_still_stamps_through_pass_1():
    facts = {"producer_fax": "303-996-7801", "producer_phone": "303-996-7800"}
    assert ps._deterministic_map("Producer_FaxNumber_A", facts) == "303-996-7801"


# ── 2. A bare dec LABEL needs no money tail ──────────────────────────────────

_DEC = ps._dec_coverage_line_set({"dec_page_entries": [
    {"label": "Limited Pollution Coverage - Work Sites", "value": "$150"},
    {"label": "Insured is", "value": "LLC"},
    {"label": "Date of Issue", "value": "07/16/2025"},
]})


def test_the_bare_label_variant_is_now_caught():
    """Run 6's Q3 explanation, verbatim: the label with the $150 dropped."""
    assert ps._is_dec_coverage_line("Limited Pollution Coverage - Work Sites", _DEC)
    # ...and with the money, and with a row-label prefix, as before.
    assert ps._is_dec_coverage_line(
        "Location 000: Limited Pollution Coverage - Work Sites $150", _DEC)


def test_the_protected_fact_lines_stay_protected():
    """label+value WITHOUT a money tail is a fact line, not a coverage grant -
    the standard the money tail exists to enforce."""
    assert not ps._is_dec_coverage_line("INSURED IS: LLC", _DEC)
    assert not ps._is_dec_coverage_line("Date of Issue: 07/16/2025", _DEC)


# ── 3. A name-only record's name is not evidence ─────────────────────────────

_ERIN_FACTS = {"auto_drivers": [{"name": "Erin Royal"}]}


def test_erin_royal_cannot_substantiate_anything():
    """Q9 AND Q10 spent the same bare name. The record it comes from was
    already ruled not-a-schedule for carrying nothing but the name; its name
    carries exactly as much."""
    assert ps._is_name_only_record_echo("ERIN ROYAL", _ERIN_FACTS)
    assert ps._is_coverage_artifact_text("ERIN ROYAL", frozenset(), _ERIN_FACTS)


def test_a_driver_with_substance_keeps_their_name_as_evidence():
    """A real family member named with a licence is a REAL Q9 answer."""
    facts = {"auto_drivers": [
        {"name": "Erin Royal", "license_number": "12-345-6789"}]}
    assert not ps._is_name_only_record_echo("ERIN ROYAL", facts)


def test_a_name_not_in_any_record_is_not_judged():
    assert not ps._is_name_only_record_echo("JORDAN SMITH", _ERIN_FACTS)


# ── 4. An endorsement title in a party NAME box ──────────────────────────────

def test_an_endorsement_title_cannot_name_a_party():
    """Run 6's fabricated interest, verbatim shape: the name box held a printed
    endorsement label. Blanking it unanchors the row; the late sweep clears the
    producer's address and the account number that rode along."""
    dec = ps._dec_coverage_line_set({"dec_page_entries": [
        {"label": "Blanket Additional Insured Status For Persons Or "
                  "Organizations On A Primary And Non-Contributory Basis",
         "value": "Included"},
    ]})
    assert ps._is_coverage_artifact_text(
        "Blanket Additional Insured Status For Persons Or Organizations On A "
        "Primary And Non-Contributory Basis", dec, {})
    # A real lender is not a printed dec line and survives.
    assert not ps._is_coverage_artifact_text("First Bank of Denver", dec, {})


# ── 5. Dependents standing under a question that is not Yes ──────────────────

_YN_TU = ('Enter Y for a "Yes" response. Input N for "No" response. '
          'Indicates the response to the question, "{}"')


def test_orphan_dep_cells_are_cleared_when_the_question_is_not_yes():
    """Run 6's Q14: the question blank, its conviction table carrying the
    insured's own city as PLACE and a borrowed '1' as YEARS REVOKED."""
    fields = {
        "CommercialVehicleLineOfBusiness_Question_AAICode_A":
            {"tu": _YN_TU.format(
                "Any drivers with convictions for moving traffic violations?"),
             "ft": "/Tx"},
        "AccidentConviction_PlaceOfIncident_A": {"tu": "Enter text", "ft": "/Tx"},
        "AccidentConviction_YearsRevokedCount_A": {"tu": "Enter number", "ft": "/Tx"},
        "CommercialVehicleLineOfBusiness_Question_KAGCode_A":
            {"tu": _YN_TU.format("Are all vehicles part of a fleet?"), "ft": "/Tx"},
    }
    pre = {"filled_values": {
               "AccidentConviction_PlaceOfIncident_A": "DENVER CO. 80216-3121",
               "AccidentConviction_YearsRevokedCount_A": "1"},
           "raw_text_fields": set(), "question_grounding": {}}
    doc = "BUSINESS AUTO DECLARATIONS\nDENVER CO. 80216-3121\n1\n"
    mapped, _ = ps.map_facts_to_form({}, fields, "ACORD_127",
                                     raw_text=doc, pre_filled_gpt=pre)
    assert mapped.get("AccidentConviction_PlaceOfIncident_A") is None
    assert mapped.get("AccidentConviction_YearsRevokedCount_A") is None


# ── 6. The truncated header, through the deterministic door ──────────────────

def test_the_truncated_header_is_caught_from_any_source():
    """Run 6 delivered "COMMERCIAL GENERAL CONTRA" via a FACT path, so the
    guard's old gap-fill-only scope missed it. Inside map_facts_to_form every
    value is document-derived, so the widened scope overrides no one."""
    fields = {"CommercialStructure_OperationsDescription_A":
              {"tu": "Enter text: description of operations.", "ft": "/Tx"}}
    facts = {"contractor_type": "Commercial general contractor",
             "premises_description": "COMMERCIAL GENERAL CONTRA"}
    pre = {"filled_values": {"CommercialStructure_OperationsDescription_A":
                             "COMMERCIAL GENERAL CONTRA"},
           "raw_text_fields": set(), "question_grounding": {}}
    mapped, _ = ps.map_facts_to_form(
        facts, fields, "ACORD_125",
        raw_text="Business Desc: COMMERCIAL GENERAL CONTRA", pre_filled_gpt=pre)
    assert mapped.get("CommercialStructure_OperationsDescription_A") is None
