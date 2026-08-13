"""THE SAME DOCUMENT, TWO ACCOUNTS, TWO DIFFERENT FORMS.

The owner ran one declarations package through two accounts and compared the
ACORD 125s. Two boxes disagreed:

    NAIC CODE        25321 on one account, BLANK on the other
                     (and 26247 on an earlier run of the same document)
    ISSUE POLICY     ticked on one account, blank on the other

**A document cannot produce two answers to the same question.** Divergence
across accounts is not a tuning problem or model jitter to be tolerated - it is
proof that the box was never answerable from the document, and that whatever
filled it was guessing. Both are now closed at the source rather than nudged.

The third finding on that run was ACORD 125 Q3 - "ANY EXPOSURE TO FLAMMABLES,
EXPLOSIVES, CHEMICALS?" = Y, explained by "Limited Pollution Coverage - Work
Sites $150." That value has been caught before, but only by exact membership in
the verified dec-page index, which captured ~250 of an estimated ~750 entries.
A guard that fires only when an upstream sampling step got lucky is not a
guard; it now reads the SHAPE of a priced line item instead.
"""
import json
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("OPENAI_API_KEY", "sk-offline")

import services.pdf_service as ps                                 # noqa: E402
import services.field_qa as fq                                    # noqa: E402

BACKEND = os.path.join(os.path.dirname(__file__), "..")


def _schema(form):
    with open(os.path.join(BACKEND, "forms_schemas", f"{form}_schema.json"),
              encoding="utf-8") as fh:
        return json.load(fh)


# ── 1. NAIC: a number that is nowhere in the document ────────────────────────

def test_a_fabricated_naic_is_blanked():
    """The client's literal value. 25321 appears nowhere in the package, which
    is why it could differ between two accounts."""
    mapped = {"Insurer_NAICCode_A": "25321"}
    dropped = ps._drop_mislabeled_naic_codes(
        mapped,
        "COMMON POLICY DECLARATIONS\nEMPLOYERS MUTUAL CASUALTY COMPANY\n"
        "Policy 6E7-40-02---26\n",
        {"Insurer_NAICCode_A"},
    )
    assert dropped == ["Insurer_NAICCode_A"]
    assert mapped["Insurer_NAICCode_A"] is None


def test_a_naic_the_document_actually_states_survives():
    """The whole point of blank-over-wrong is that it must not cost real data.
    A carrier NAIC printed on the dec page still stamps."""
    mapped = {"Insurer_NAICCode_A": "21415"}
    dropped = ps._drop_mislabeled_naic_codes(
        mapped,
        "CARRIER: EMPLOYERS MUTUAL CASUALTY COMPANY  NAIC CODE 21415\n",
        {"Insurer_NAICCode_A"},
    )
    assert dropped == []
    assert mapped["Insurer_NAICCode_A"] == "21415"


def test_a_naic_present_but_labelled_for_the_producer_still_drops():
    """The guard's ORIGINAL job must survive the new one."""
    mapped = {"Insurer_NAICCode_A": "41982"}
    dropped = ps._drop_mislabeled_naic_codes(
        mapped, "Producer NAIC Number: 41982\n", {"Insurer_NAICCode_A"})
    assert dropped == ["Insurer_NAICCode_A"]


def test_a_deterministic_naic_is_never_touched():
    """Source-scoping is correct here: this judges MODEL BEHAVIOUR. A NAIC that
    came from the extraction fact is not the model's guess."""
    mapped = {"Insurer_NAICCode_A": "25321"}
    assert ps._drop_mislabeled_naic_codes(mapped, "no naic here", set()) == []
    assert mapped["Insurer_NAICCode_A"] == "25321"


# ── 2. STATUS OF TRANSACTION is the producer's to state ──────────────────────

_STATUS_FAMILY = (
    "Policy_Status_QuoteIndicator_A", "Policy_Status_IssueIndicator_A",
    "Policy_Status_BoundIndicator_A", "Policy_Status_ChangeIndicator_A",
    "Policy_Status_CancelIndicator_A", "Policy_Status_RenewIndicator_A",
)


@pytest.mark.parametrize("field", _STATUS_FAMILY)
def test_no_transaction_status_box_can_be_guessed(field):
    schema = _schema("ACORD_125")
    assert field in schema, field
    assert ps._resolve_policy_status(field, {}) is None, field
    assert ps._is_authoritative_blank_field(field, {}), field


def test_a_known_renewal_still_ticks_renew():
    assert ps._resolve_policy_status(
        "Policy_Status_RenewIndicator_A", {"is_renewal": "yes"}) == "Yes"
    # ...and only that box.
    assert ps._resolve_policy_status(
        "Policy_Status_IssueIndicator_A", {"is_renewal": "yes"}) is None


def test_issue_policy_cannot_be_ticked_from_the_document_end_to_end():
    """The client's literal divergence: ISSUE POLICY ticked on one account."""
    f = "Policy_Status_IssueIndicator_A"
    mapped, _ = ps.map_facts_to_form(
        {}, _schema("ACORD_125"), "ACORD_125",
        raw_text="COMMON POLICY DECLARATIONS\nDate of Issue 07/16/2025\n",
        pre_filled_gpt={"filled_values": {f: "Yes"},
                        "raw_text_fields": set(), "question_grounding": {}})
    assert mapped.get(f) is None


def test_the_whole_family_is_deterministic_across_runs():
    """The property the client actually needs: same input, same output, every
    time, whatever the model says."""
    schema = _schema("ACORD_125")
    outs = []
    for guess in ("Yes", None, "Y"):
        mapped, _ = ps.map_facts_to_form(
            {}, schema, "ACORD_125", raw_text="COMMON POLICY DECLARATIONS\n",
            pre_filled_gpt={"filled_values": {f: guess for f in _STATUS_FAMILY},
                            "raw_text_fields": set(), "question_grounding": {}})
        outs.append(tuple(mapped.get(f) for f in _STATUS_FAMILY))
    assert len(set(outs)) == 1, f"the family diverged across runs: {outs}"
    assert outs[0] == (None,) * len(_STATUS_FAMILY)


# ── 3. A priced line item, with no dec index to lean on ──────────────────────

@pytest.mark.parametrize("line", [
    "Limited Pollution Coverage - Work Sites $150.",     # client's literal Q3
    "Limited Pollution Coverage - Work Sites $150",
    "Auto Elite Extension $250",
    "General Liability Elite Extension $500",
    "Premium For Certified Acts Of Terrorism $31.00",
])
def test_a_priced_line_is_recognised_without_the_index(line):
    assert ps._is_priced_coverage_line(line), line
    # ...and therefore as an artifact, with an EMPTY dec index - which is the
    # condition under which this defect shipped.
    assert ps._is_coverage_artifact_text(line, frozenset(), {}), line


@pytest.mark.parametrize("real", [
    "The applicant paid $5,000 to settle a claim in 2023",
    "The deductible for each pollution incident is $1,000",
    "Custom ladder rack mounted on roof.",
    "The applicant stores acetylene and oxygen cylinders in a locked cage",
    "The applicant transports hazardous materials to job sites weekly.",
    "Subcontractors are required to carry coverage.",
])
def test_a_real_statement_is_not_a_priced_line(real):
    assert not ps._is_priced_coverage_line(real), real


def test_q3_flammables_falls_end_to_end_with_no_dec_index():
    """The client's ACORD 125, verbatim, on a session whose dec index never
    captured that line - the exact condition the old check was blind to."""
    q = "CommercialStructure_Question_ABBCode_A"
    tu = ('Enter Y for a "Yes" response. Input N for "No" response. Indicates '
          'the response to the question, "Any exposure to flammables, '
          'explosives, chemicals?"')
    exp = "CommercialStructure_ExposureFlammableExplosiveChemicalExplanation_A"
    fields = {q: {"tu": tu, "ft": "/Tx"},
              exp: {"tu": "Enter text: An explanation", "ft": "/Tx"}}
    doc = "GENERAL LIABILITY DECLARATIONS\nLimited Pollution Coverage - Work Sites $150.\n"
    mapped, _ = ps.map_facts_to_form(
        {}, fields, "ACORD_125", raw_text=doc,
        pre_filled_gpt={"filled_values": {
            q: "Y", exp: "Limited Pollution Coverage - Work Sites $150."},
            "raw_text_fields": set(),
            "question_grounding": {
                q: "Limited Pollution Coverage - Work Sites $150."}})
    assert mapped.get(q) is None, "the Yes stood on a priced coverage grant"
    assert mapped.get(exp) is None


# ── 4. The review screen must stay readable ──────────────────────────────────

def test_cascade_blanks_are_not_reported_as_individual_findings():
    """The client's run produced '131 fields left blank on purpose' on one form
    and 90 on another. Almost all were cells cleared BECAUSE THEIR ROW LOST ITS
    ANCHOR - real, but not 131 separate decisions, and 131 rows of it buries
    the handful a human needs to look at."""
    facts = {"producer_fax": "303-996-7800", "producer_phone": "303-996-7800"}
    report: list = []
    ps.map_facts_to_form(
        facts, _schema("ACORD_125"), "ACORD_125",
        raw_text="COMMON POLICY DECLARATIONS\nAgent Phone 303-996-7800\n",
        pre_filled_gpt={"filled_values": {
            "AdditionalInterest_FullName_A": "Location 000",
            "AdditionalInterest_MailingAddress_LineOne_A": "9780 S Meridian Blvd",
            "AdditionalInterest_MailingAddress_CityName_A": "Englewood",
            "AdditionalInterest_AccountNumberIdentifier_A": "0482854"},
            "raw_text_fields": set(), "question_grounding": {}},
        guard_report=report)
    reported = {e["field"] for e in report}
    # The NAME was judged - a row label is not a party name. The address and
    # account number went with the row and are not separate findings.
    assert "AdditionalInterest_FullName_A" in reported
    for rider in ("AdditionalInterest_MailingAddress_LineOne_A",
                  "AdditionalInterest_MailingAddress_CityName_A",
                  "AdditionalInterest_AccountNumberIdentifier_A"):
        assert rider not in reported, (
            f"{rider} was reported as its own finding; it was cleared with its "
            "row, which is what made the client's advisory row 131 items long")


def test_a_name_only_driver_schedule_raises_no_licence_defect():
    """The client's review screen said 'auto drivers row 1: license number is
    required but missing' for a package whose ground truth has NO driver
    schedule - we were demanding a licence for a driver we had already, and
    correctly, declined to print."""
    qa = fq.run_field_qa(
        {"ACORD_127": {"mapped": {}, "confidence": {}, "schema": {}}},
        merged_facts={"auto_drivers": [{"name": "Erin Royal"}]},
        confirmations={})
    rows = [r for r in qa["results"]
            if r.get("reason_code", "").startswith("schedule_row")]
    assert not rows, f"a name-only driver record raised {len(rows)} defect(s)"


def test_a_real_driver_missing_a_licence_still_raises_it():
    """The check must keep working where it means something."""
    qa = fq.run_field_qa(
        {"ACORD_127": {"mapped": {}, "confidence": {}, "schema": {}}},
        merged_facts={"auto_drivers": [
            {"name": "Erin Royal", "date_of_birth": "04/11/1980"}]},
        confirmations={})
    rows = [r for r in qa["results"]
            if r.get("reason_code", "").startswith("schedule_row")]
    assert rows, "a substantive driver row with no licence raised nothing"
