"""Run 9 of 2026-08-13 (the 125/126/127 set sent with the client's audit doc).

Every fabricated value on those three forms traces to one of five doors, each
now closed:

  1. THE FAKE-VERB HOLE. `_quote_asserts_something` read any >=3-letter word
     ending in ed/es/s as a predicate, so printed TITLES were "statements":
       Q8  = Y  "WAIVER OF TRANSFER OF RIGHTS OF RECOVERY"      (rightS)
       Q9  = Y  "NAMES OF INDIVIDUALS ERIN ROYAL"               (nameS)
       126 Q9 = Y "J. BLANKET ADDITIONAL INSUREDS"              (insuredS)
  2. QUOTED PRONOUNS. ISO forms print defined terms in quotes - run 9's Q4:
       '"We" do not cover property that "you" lease or rent to others.'
     The quote characters defeated every \\b-anchored contract-voice pattern.
  3. THE APPLICANT'S OWN ADDRESS as evidence (126 Q7 parking = the premises
     address), exempted from the assertion test by its digit payload.
  4. LOB NAMES AS DATA. The 126 products schedule listed "Commercial Auto
     Liability" and "Commercial Inland Marine" as manufactured products.
  5. CLAIMS-MADE DATES ON AN OCCURRENCE POLICY, $0 LOSS HISTORY WITHOUT
     EVIDENCE, and the truncated "COMMERCIAL GENERAL CONTRA" premises box.
"""
import json
import os
import re
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("OPENAI_API_KEY", "sk-offline")

import services.pdf_service as ps                                 # noqa: E402

BACKEND = os.path.join(os.path.dirname(__file__), "..")


def _schema(form):
    with open(os.path.join(BACKEND, "forms_schemas", f"{form}_schema.json"),
              encoding="utf-8") as fh:
        return json.load(fh)


_YN_TU = ('Enter Y for a "Yes" response. Input N for "No" response. '
          'Indicates the response to the question, "{}"')


# ── 1. A plural noun is not a verb ───────────────────────────────────────────

@pytest.mark.parametrize("title", [
    "WAIVER OF TRANSFER OF RIGHTS OF RECOVERY",
    "NAMES OF INDIVIDUALS ERIN ROYAL",
    "J. BLANKET ADDITIONAL INSUREDS",
    "BROADENINGS OF COVERAGE",
    "SCHEDULE OF COVERED AUTOS",
])
def test_a_printed_title_asserts_nothing(title):
    """MUST NEVER FAIL - the first three are the client's verbatim run-9
    values, each of which grounded a wrong Yes."""
    assert not ps._quote_asserts_something(title), title


@pytest.mark.parametrize("statement", [
    "The applicant transports hazardous materials to job sites weekly.",
    "Custom ladder rack mounted on roof.",
    "The applicant stores acetylene and oxygen cylinders in a locked cage",
    "Erin Royal drives a company vehicle and holds a valid CO license.",
    "Subcontractors are required to carry coverage.",
    "The applicant does not have any subsidiaries.",
    "The company operates a fleet of three trucks in Denver",
])
def test_a_real_statement_still_asserts(statement):
    """The tightening must not eat genuine s-suffix verbs (transports, stores,
    drives, operates) - position separates them: a finite verb sits between
    subject and object; a title-noun hangs off an of/and/or chain."""
    assert ps._quote_asserts_something(statement), statement


def test_the_waiver_title_cannot_ground_a_yes_end_to_end():
    q = "CommercialVehicleLineOfBusiness_Question_AAECode_A"
    fields = {q: {"tu": _YN_TU.format("Any hold harmless agreements?"),
                  "ft": "/Tx"}}
    doc = "BUSINESS AUTO DECLARATIONS\nWAIVER OF TRANSFER OF RIGHTS OF RECOVERY\n"
    mapped, _ = ps.map_facts_to_form(
        {}, fields, "ACORD_127", raw_text=doc,
        pre_filled_gpt={"filled_values": {q: "Y"}, "raw_text_fields": set(),
                        "question_grounding": {
                            q: "WAIVER OF TRANSFER OF RIGHTS OF RECOVERY"}})
    assert mapped.get(q) is None


# ── 2. Quoted pronouns are the policy's signature ────────────────────────────

def test_quoted_pronoun_contract_wording_is_rejected():
    """Run 9 Q4 verbatim: the ISO exclusion with its quoted defined terms."""
    assert ps._is_contract_wording(
        '"We" do not cover property that "you" lease or rent to others.')


def test_the_forms_revision_notice_is_contract_wording():
    """Run 9, 126 Q4 verbatim."""
    assert ps._is_contract_wording(
        "The following forms may be newly introduced to the policy: "
        "BROADENINGS OF COVERAGE")


@pytest.mark.parametrize("genuine", [
    "This policy was cancelled for non-payment of premium.",
    "The applicant leases equipment to others with operators.",
    'The client said "yes" when asked about prior claims.',
])
def test_genuine_statements_are_still_not_contract_wording(genuine):
    assert not ps._is_contract_wording(genuine), genuine


# ── 3. The applicant's own address is not evidence ───────────────────────────

_ADDR_FACTS = {"physical_address": "4800 DAHLIA ST # D13, DENVER, CO 80216-3121"}


def test_the_premises_address_cannot_evidence_parking():
    """Run 9, 126 Q7 verbatim - note the format drift (STREET vs ST #): the
    digit skeleton is the identity, not the spelling."""
    assert ps._is_identity_address_echo(
        "4800 DAHLIA STREET D13, DENVER CO. 80216-3121", _ADDR_FACTS)


def test_a_sentence_containing_the_address_survives():
    assert not ps._is_identity_address_echo(
        "The applicant leases warehouse space at 4800 Dahlia St # D13, "
        "Denver CO 80216-3121 for parking", _ADDR_FACTS)


def test_a_different_address_is_not_an_echo():
    assert not ps._is_identity_address_echo(
        "9780 S MERIDIAN BLVD STE 400, ENGLEWOOD CO 80112-6072", _ADDR_FACTS)


# ── 4. A line of business is not a product ───────────────────────────────────

@pytest.mark.parametrize("lob", [
    "Commercial Auto Liability", "Commercial Inland Marine",
    "Commercial General Liability", "Umbrella", "Workers Compensation",
    "Commercial Liability Umbrella", "Cyber and Privacy",
    "Commercial Property Coverage Part",
])
def test_lob_names_are_recognized(lob):
    assert ps._is_line_of_business_name(lob), lob


@pytest.mark.parametrize("not_lob", [
    "Orbin Contracting LLC", "2012 Subaru Outback", "Contractors' Equipment",
    "General contractor services", "Commercial kitchen equipment",
])
def test_real_values_are_not_lob_names(not_lob):
    assert not ps._is_line_of_business_name(not_lob), not_lob


def test_a_products_row_of_coverage_lines_is_cleared_end_to_end():
    """Run 9's ACORD 126 products schedule, verbatim shape: coverage lines as
    products, the policy effective date as time-in-market."""
    fields = {
        "ProductAndCompletedOperations_ProductName_A": {"tu": "Enter text", "ft": "/Tx"},
        "ProductAndCompletedOperations_IntendedUse_A": {"tu": "Enter text", "ft": "/Tx"},
        "ProductAndCompletedOperations_ProductName_B": {"tu": "Enter text", "ft": "/Tx"},
    }
    pre = {"filled_values": {
               "ProductAndCompletedOperations_ProductName_A": "Commercial Auto Liability",
               "ProductAndCompletedOperations_ProductName_B": "Commercial Inland Marine"},
           "raw_text_fields": set(), "question_grounding": {}}
    doc = "Commercial Auto Liability\nCommercial Inland Marine\n"
    mapped, _ = ps.map_facts_to_form({}, fields, "ACORD_126",
                                     raw_text=doc, pre_filled_gpt=pre)
    assert mapped.get("ProductAndCompletedOperations_ProductName_A") is None
    assert mapped.get("ProductAndCompletedOperations_ProductName_B") is None


def test_lob_names_survive_in_their_legitimate_homes():
    """The Q4 other-insurance LOB labels are values the client explicitly asked
    for (PART 12 item 6) - the allow-list must keep every field whose tooltip
    asks for a line of business."""
    import glob
    missed = []
    for path in glob.glob(os.path.join(BACKEND, "forms_schemas", "*_schema.json")):
        with open(path, encoding="utf-8") as fh:
            for name, meta in json.load(fh).items():
                tu = (meta.get("tu") or "").lower() if isinstance(meta, dict) else ""
                if "line of business" in tu and meta.get("ft") == "/Tx" \
                        and "premium" not in tu and "code" not in name.lower():
                    if not ps._LOB_FIELD_ALLOWED_RE.search(name):
                        missed.append((os.path.basename(path), name))
    assert not missed, (
        f"{len(missed)} line-of-business text boxes are outside the allow-list "
        f"and would be blanked by the LOB guard: {missed[:8]}")


def test_a_bare_amount_in_a_description_box_is_cleared():
    """Run 9: LIMIT APPLIES PER 'OTHER:' description = '$2,000,000'."""
    fields = {"GeneralLiability_GeneralAggregate_LimitAppliesPerOtherDescription_A":
              {"tu": "Enter text", "ft": "/Tx"}}
    pre = {"filled_values": {
        "GeneralLiability_GeneralAggregate_LimitAppliesPerOtherDescription_A":
            "$2,000,000"},
        "raw_text_fields": set(), "question_grounding": {}}
    mapped, _ = ps.map_facts_to_form({}, fields, "ACORD_126",
                                     raw_text="$2,000,000",
                                     pre_filled_gpt=pre)
    assert mapped.get(
        "GeneralLiability_GeneralAggregate_LimitAppliesPerOtherDescription_A") is None


# ── 5. Claims-made dates on an occurrence policy ─────────────────────────────

def test_retro_dates_are_blank_on_an_occurrence_policy():
    """Run 9 verbatim: PROPOSED RETROACTIVE DATE and ENTRY DATE both stamped
    with the policy EFFECTIVE date on a CG 00 01 occurrence form."""
    for f in ("GeneralLiability_ClaimsMade_ProposedRetroactiveDate_A",
              "GeneralLiability_ClaimsMade_UninterruptedCoverageEntryDate_A",
              "GeneralLiability_EmployeeBenefits_RetroactiveDate_A"):
        assert ps._resolve_claims_made_dates(f, {}) is None, f
        assert ps._is_authoritative_blank_field(f, {}), f
        assert ps._resolve_claims_made_dates(
            f, {"gl_is_claims_made": True}) is ps._SCHED_SKIP, f


def test_the_real_126_retro_fields_are_covered():
    schema = _schema("ACORD_126")
    covered = [f for f in schema
               if ps._resolve_claims_made_dates(f, {}) is not ps._SCHED_SKIP]
    assert "GeneralLiability_ClaimsMade_ProposedRetroactiveDate_A" in covered
    assert "GeneralLiability_ClaimsMade_UninterruptedCoverageEntryDate_A" in covered


# ── 6. $0 loss history is an attestation, not a default ──────────────────────

def test_total_losses_stays_blank_without_evidence():
    assert ps._resolve_loss_history_summary("LossHistory_TotalAmount_A", {}) is None
    assert ps._resolve_loss_history_summary(
        "LossHistory_InformationYearCount_A", {}) is None


def test_total_losses_opens_up_with_a_real_signal():
    assert ps._resolve_loss_history_summary(
        "LossHistory_TotalAmount_A",
        {"asserts_no_known_losses": True}) is ps._SCHED_SKIP
    assert ps._resolve_loss_history_summary(
        "LossHistory_TotalAmount_A",
        {"loss_history": [{"date": "01/02/2024", "paid": "$5,000"}]},
    ) is ps._SCHED_SKIP


# ── 7. The truncated premises description gets the full sentence ─────────────

_OPS = ("Contractors - Executive Supervisors or Executive Superintendents; "
        "contractors-sub work-in connection with construction, reconstruction, "
        "repair, erection of buildings - NOC.")


def test_premises_description_prefers_the_full_operations_fact():
    """Client PART 19 item 16: 'COMMERCIAL GENERAL CONTRA' is truncated carrier
    shorthand, not a usable description. The box now fills from the full
    operations_description fact, deterministically."""
    facts = {"property_locations": [{"street": "4800 Dahlia St # D13",
                                     "city": "Denver", "state": "CO",
                                     "zip": "80216-3121"}],
             "contractor_type": "COMMERCIAL GENERAL CONTRA",
             "operations_description": _OPS}
    assert ps._deterministic_map(
        "BuildingOccupancy_OperationsDescription_A", facts) == _OPS
    # Rows B+ stay schedule-scoped: no second location, no second description.
    assert ps._deterministic_map(
        "BuildingOccupancy_OperationsDescription_B", facts) is None


# ── 8. A classification cannot answer an underwriting question ───────────────

def test_the_class_description_cannot_prove_subcontractor_limits():
    """Run 9, 126 Q4 verbatim: 'do your subcontractors carry limits less than
    yours?' = Y, 'explained' by the rating class description that also sits in
    the Schedule of Hazards two sections up."""
    q = "GeneralLiabilityLineOfBusiness_Question_ACGCode_A"
    exp = "GeneralLiabilityLineOfBusiness_SubcontractorsCarryLowerLimitsExplanation_A"
    cls = "GeneralLiability_Hazard_ClassificationDescription_B"
    desc = ("Contrctrs-sub work-in connection w/constrctn,recon,repr,erctn "
            "of buildings - NOC")
    fields = {
        q: {"tu": _YN_TU.format(
            "Do your subcontractors carry coverages or limits less than yours?"),
            "ft": "/Tx"},
        exp: {"tu": "Enter text: An explanation", "ft": "/Tx"},
        cls: {"tu": "Enter text: classification", "ft": "/Tx"},
    }
    facts = {"gl_class_codes": [{"code": "91585", "description": desc}]}
    doc = f"GENERAL LIABILITY DECLARATIONS\n91585 {desc}\n"
    pre = {"filled_values": {q: "Y", exp: desc, cls: desc},
           "raw_text_fields": set(), "question_grounding": {q: desc}}
    mapped, _ = ps.map_facts_to_form(facts, fields, "ACORD_126",
                                     raw_text=doc, pre_filled_gpt=pre)
    assert mapped.get(q) is None, "the Yes stood on a rating classification"
    assert mapped.get(exp) is None


def test_a_genuine_subcontractor_answer_survives():
    q = "GeneralLiabilityLineOfBusiness_Question_ACGCode_A"
    exp = "GeneralLiabilityLineOfBusiness_SubcontractorsCarryLowerLimitsExplanation_A"
    quote = ("Subcontractors carry general liability limits of $500,000, "
             "which is less than the applicant's $1,000,000.")
    fields = {
        q: {"tu": _YN_TU.format(
            "Do your subcontractors carry coverages or limits less than yours?"),
            "ft": "/Tx"},
        exp: {"tu": "Enter text: An explanation", "ft": "/Tx"},
    }
    doc = f"NARRATIVE\n{quote}\n"
    pre = {"filled_values": {q: "Y", exp: quote},
           "raw_text_fields": set(), "question_grounding": {q: quote}}
    mapped, _ = ps.map_facts_to_form({}, fields, "ACORD_126",
                                     raw_text=doc, pre_filled_gpt=pre)
    assert mapped.get(q) == "Y"


# ── 9. Orphan deps under PAIRED questions ────────────────────────────────────

def test_a_paired_questions_sibling_table_is_cleared_when_the_question_is_blank():
    """Run 9, 126 Q5: the equipment table held '840 CONTR. EQUIP. - LEASED OR
    RENTED FROM OTHERS' while Q5's Y/N box was empty - unjudged, because Q5
    has a paired explanation and the sweep skipped paired questions."""
    q = "GeneralLiabilityLineOfBusiness_Question_ACICode_A"
    exp = "GeneralLiabilityLineOfBusiness_MachineryOrEquipmentLoanedRentedOthersExplanation_A"
    dep = "PropertyItem_ItemDetail_InstructionGivenCode_A"
    fields = {
        q: {"tu": _YN_TU.format("Do you rent or loan equipment to others?"),
            "ft": "/Tx"},
        exp: {"tu": "Enter text: An explanation", "ft": "/Tx"},
        dep: {"tu": "Enter text: equipment detail", "ft": "/Tx"},
        "GeneralLiabilityLineOfBusiness_Question_ACJCode_A":
            {"tu": _YN_TU.format("Any watercraft?"), "ft": "/Tx"},
    }
    pre = {"filled_values": {dep: "840 CONTR. EQUIP. - LEASED OR RENTED FROM OTHERS"},
           "raw_text_fields": set(), "question_grounding": {}}
    doc = "840 CONTR. EQUIP. - LEASED OR RENTED FROM OTHERS\n"
    mapped, _ = ps.map_facts_to_form({}, fields, "ACORD_126",
                                     raw_text=doc, pre_filled_gpt=pre)
    assert mapped.get(dep) is None, \
        "a dependent cell stood under a blank paired question"


def test_a_paired_yes_with_explanation_but_empty_table_stands():
    """The other direction must NOT tighten: a paired Yes stands on its
    explanation; the sibling table is optional refinement."""
    q = "GeneralLiabilityLineOfBusiness_Question_ACICode_A"
    exp = "GeneralLiabilityLineOfBusiness_MachineryOrEquipmentLoanedRentedOthersExplanation_A"
    dep = "PropertyItem_ItemDetail_InstructionGivenCode_A"
    quote = "The applicant rents a skid steer to neighboring contractors monthly."
    fields = {
        q: {"tu": _YN_TU.format("Do you rent or loan equipment to others?"),
            "ft": "/Tx"},
        exp: {"tu": "Enter text: An explanation", "ft": "/Tx"},
        dep: {"tu": "Enter text: equipment detail", "ft": "/Tx"},
        "GeneralLiabilityLineOfBusiness_Question_ACJCode_A":
            {"tu": _YN_TU.format("Any watercraft?"), "ft": "/Tx"},
    }
    pre = {"filled_values": {q: "Y", exp: quote},
           "raw_text_fields": set(), "question_grounding": {q: quote}}
    mapped, _ = ps.map_facts_to_form({}, fields, "ACORD_126",
                                     raw_text=f"NARRATIVE\n{quote}\n",
                                     pre_filled_gpt=pre)
    assert mapped.get(q) == "Y"
    assert mapped.get(exp) == quote


# ── 10. The full run-9 127 shape, replayed ───────────────────────────────────

def test_the_three_wrong_127_yeses_all_fall():
    schema = _schema("ACORD_127")
    q8 = "CommercialVehicleLineOfBusiness_Question_AAECode_A"
    q9 = "CommercialVehicleLineOfBusiness_Question_AAKCode_A"
    q4 = "CommercialVehicleLineOfBusiness_Question_AABCode_A"
    fields = {f: schema[f] for f in schema
              if ps._QUESTION_CODE_FIELD_RE.search(f)}
    doc = ("BUSINESS AUTO DECLARATIONS\n"
           "WAIVER OF TRANSFER OF RIGHTS OF RECOVERY\n"
           "NAMES OF INDIVIDUALS ERIN ROYAL\n"
           '"We" do not cover property that "you" lease or rent to others.\n')
    pre = {"filled_values": {q8: "Y", q9: "Y", q4: "Y"},
           "raw_text_fields": set(),
           "question_grounding": {
               q8: "WAIVER OF TRANSFER OF RIGHTS OF RECOVERY",
               q9: "NAMES OF INDIVIDUALS ERIN ROYAL",
               q4: '"We" do not cover property that "you" lease or rent to others.'}}
    mapped, _ = ps.map_facts_to_form({}, fields, "ACORD_127",
                                     raw_text=doc, pre_filled_gpt=pre)
    assert mapped.get(q8) is None
    assert mapped.get(q9) is None
    assert mapped.get(q4) is None
