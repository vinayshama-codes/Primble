"""The ACORD 127 root causes, fixed at class level (2026-08-13, fourth session).

The owner's question, verbatim: "why can't we fix the root cause responsible for
these issues". The answer this file pins:

  ROOT CAUSE 2 - the source document is a POLICY; the form asks about the RISK.
  The evidence gate verified a quote EXISTS, never that it is a statement about
  the APPLICANT rather than the policy describing its own coverage. Every wrong
  Y on the live 127 is that one defect:

      Q5 modified cars = Y   <- "Auto Elite Extension $250"      (an endorsement)
      Q3 chemicals     = Y   <- "Limited Pollution Coverage..."  (a coverage grant)
      Q9 family use    = Y   <- "ERIN ROYAL"                     (a DOC name)

  ROOT CAUSE 3 - the phantom-row guard acts only on positive evidence, so a run
  where extraction misses the vehicle schedule leaves all 220 vehicle questions
  to gap fill, and row 2 printed the GL class code 91585 as its rate class.
  The anchor rule needs no schedule fact: a row with no identity is not a row.
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("OPENAI_API_KEY", "sk-offline")

import services.pdf_service as ps                                 # noqa: E402

# The verified dec entries a real ORBIN run carries, in miniature.
_ENTRIES = [
    {"label": "Auto Elite Extension", "value": "$250", "owner": "policy"},
    {"label": "Limited Pollution Coverage - Work Sites", "value": "$150",
     "owner": "policy", "section": "GENERAL LIABILITY SCHEDULE"},
    {"label": "Contractors' Equipment", "value": "$10,000", "owner": "policy"},
    {"label": "Insured is", "value": "LLC", "owner": "applicant"},
    {"label": "Date of Issue", "value": "07/16/2025", "owner": "policy"},
]
_DEC_LINES = ps._dec_coverage_line_set({"dec_page_entries": _ENTRIES})


# ── 1. A coverage line is not evidence ───────────────────────────────────────

@pytest.mark.parametrize("artifact", [
    "Auto Elite Extension $250",                       # the literal Q5 evidence
    "Limited Pollution Coverage - Work Sites $150",    # the literal Q3 evidence
    "Contractors' Equipment $10,000",
])
def test_a_printed_coverage_line_cannot_ground_a_yes(artifact):
    assert ps._is_dec_coverage_line(artifact, _DEC_LINES), artifact


@pytest.mark.parametrize("fact", [
    # THE LOAD-BEARING SIDE, pinned previously by
    # test_a_quote_carrying_real_data_still_grounds_a_yes: dec-page FACT lines
    # are legitimate evidence. The money tail is what separates the two - a
    # coverage line grants at a price, a fact line prices nothing.
    "INSURED IS: LLC",
    "Date of Issue: 07/16/2025",
    "The applicant stores acetylene and oxygen cylinders in a locked cage",
])
def test_a_dec_page_fact_line_is_not_a_coverage_artifact(fact):
    assert not ps._is_dec_coverage_line(fact, _DEC_LINES), fact


def test_no_index_means_no_opinion():
    assert not ps._is_dec_coverage_line("Auto Elite Extension $250", frozenset())


def test_a_bare_name_asserts_nothing_and_carries_nothing():
    """The Q9 evidence. No verb, no digit, no colon value - it can prove
    nothing happened to anybody."""
    assert not ps._quote_asserts_something("ERIN ROYAL")
    assert not ps._DATA_PAYLOAD_RE.search("ERIN ROYAL")


def test_short_data_bearing_quotes_keep_their_payload_exemption():
    for q in ("INSURED IS: LLC", "Date of Issue: 07/16/2025"):
        assert ps._DATA_PAYLOAD_RE.search(q), q


# ── 2. End to end: the literal 127 answers fall, a genuine yes survives ──────

_127_DOC = (
    "BUSINESS AUTO DECLARATIONS\n"
    "Auto Elite Extension $250\n"
    "Limited Pollution Coverage - Work Sites $150\n"
    "CA 99 10 A DRIVE OTHER CAR COVERAGE - NAMES OF INDIVIDUALS: ERIN ROYAL\n"
    "The applicant transports acetylene cylinders to job sites weekly.\n"
)


def _run_gate(fields, filled, grounding, facts=None):
    schema = {f: meta for f, meta in fields.items()}
    pre = {"filled_values": dict(filled), "raw_text_fields": set(filled),
           "question_grounding": dict(grounding)}
    all_facts = {"dec_page_entries": _ENTRIES}
    all_facts.update(facts or {})
    mapped, _ = ps.map_facts_to_form(
        all_facts, schema, "ACORD_127", raw_text=_127_DOC, pre_filled_gpt=pre)
    return mapped


_YN_TU = ('Enter Y for a "Yes" response. Input N for "No" response. '
          'Indicates the response to the question, "{}"')


def test_the_literal_q5_yes_falls_with_its_coverage_line_evidence():
    fields = {
        "CommercialVehicleLineOfBusiness_Question_AAHCode_A":
            {"tu": _YN_TU.format("Any car modified / special equipment?"), "ft": "/Tx"},
    }
    mapped = _run_gate(
        fields,
        {"CommercialVehicleLineOfBusiness_Question_AAHCode_A": "Y"},
        {"CommercialVehicleLineOfBusiness_Question_AAHCode_A":
         "Auto Elite Extension $250"})
    assert mapped.get("CommercialVehicleLineOfBusiness_Question_AAHCode_A") is None


def test_the_literal_q9_yes_falls_with_its_bare_name_evidence():
    fields = {
        "CommercialVehicleLineOfBusiness_Question_AAJCode_A":
            {"tu": _YN_TU.format("Any vehicles used by family members?"), "ft": "/Tx"},
    }
    mapped = _run_gate(
        fields,
        {"CommercialVehicleLineOfBusiness_Question_AAJCode_A": "Y"},
        {"CommercialVehicleLineOfBusiness_Question_AAJCode_A": "ERIN ROYAL"})
    assert mapped.get("CommercialVehicleLineOfBusiness_Question_AAJCode_A") is None


def test_a_genuinely_evidenced_yes_still_stands():
    """THE OTHER DIRECTION, always. A real prose statement about the applicant's
    own operations keeps its Yes - the gate got stricter about coverage
    artifacts, not about evidence."""
    fields = {
        "CommercialVehicleLineOfBusiness_Question_AAKCode_A":
            {"tu": _YN_TU.format(
                "Do operations involve transporting hazardous material?"), "ft": "/Tx"},
    }
    mapped = _run_gate(
        fields,
        {"CommercialVehicleLineOfBusiness_Question_AAKCode_A": "Y"},
        {"CommercialVehicleLineOfBusiness_Question_AAKCode_A":
         "The applicant transports acetylene cylinders to job sites weekly."})
    assert mapped.get("CommercialVehicleLineOfBusiness_Question_AAKCode_A") == "Y"


# ── 3. A schedule row with no identity is not a row ──────────────────────────

def test_the_literal_row_2_leak_is_cleared():
    """Row B carrying the GL class code with no VIN, make, model or year -
    the live form's second vehicle block, verbatim field names."""
    schema = {
        "Vehicle_VINIdentifier_B": {}, "Vehicle_ManufacturersName_B": {},
        "Vehicle_ModelName_B": {}, "Vehicle_ModelYear_B": {},
        "Vehicle_RateClassCode_B": {}, "Vehicle_SpecialIndustryClassCode_B": {},
        "Vehicle_CostNewAmount_B": {}, "Vehicle_PhysicalAddress_CountyName_B": {},
    }
    mapped = {
        "Vehicle_RateClassCode_B": "91585",
        "Vehicle_SpecialIndustryClassCode_B": "91585",
        "Vehicle_CostNewAmount_B": "$10,000",
        "Vehicle_PhysicalAddress_CountyName_B": "Denver",
    }
    ghost = ps._unanchored_schedule_row_fields(mapped, schema, set(mapped))
    assert ghost == set(mapped)


def test_an_anchored_row_keeps_its_details():
    schema = {
        "Vehicle_VINIdentifier_B": {}, "Vehicle_RateClassCode_B": {},
        "Vehicle_CostNewAmount_B": {},
    }
    mapped = {"Vehicle_VINIdentifier_B": "4S4BRCGC9C3217772",
              "Vehicle_RateClassCode_B": "7383",
              "Vehicle_CostNewAmount_B": "$26,680"}
    assert ps._unanchored_schedule_row_fields(mapped, schema, set(mapped)) == set()


def test_row_a_singletons_are_never_judged():
    """`Vehicle_Question_ModifiedEquipmentDescription_A` is a General
    Information answer that merely shares the Vehicle prefix - judging row A
    cleared a genuine equipment description the first time this guard was
    wired, and the test corpus caught it. Pinned so it stays caught."""
    schema = {"Vehicle_VINIdentifier_A": {},
              "Vehicle_Question_ModifiedEquipmentDescription_A": {}}
    mapped = {"Vehicle_Question_ModifiedEquipmentDescription_A":
              "Custom ladder rack mounted on roof."}
    assert ps._unanchored_schedule_row_fields(mapped, schema, set(mapped)) == set()


def test_deterministic_values_are_never_cleared():
    """Only gap-fill values are judged - a resolver-stamped detail implies the
    backing record exists."""
    schema = {"Vehicle_VINIdentifier_B": {}, "Vehicle_CostNewAmount_B": {}}
    mapped = {"Vehicle_CostNewAmount_B": "$26,680"}
    assert ps._unanchored_schedule_row_fields(mapped, schema, set()) == set()


# ── 4. A driver's personal data may only come from the driver record ─────────

@pytest.mark.parametrize("field,value", [
    ("Driver_GenderCode_A", "F"),            # inferred from a first name
    ("Driver_MaritalStatusCode_A", "U"),     # invented outright
    ("Driver_LicensedYear_A", "2012"),       # the VEHICLE'S model year
    ("Driver_TaxIdentifier_A", "4S4BRCGC9C3217772"),
])
def test_the_literal_driver_row_decorations_match(field, value):
    assert ps._DRIVER_PERSONAL_COLUMN_RE.match(field), field


def test_driver_coverage_columns_are_not_personal():
    """The DOC code is legitimately derived from the endorsement that names the
    driver - it must never be swept up here."""
    assert not ps._DRIVER_PERSONAL_COLUMN_RE.match("Driver_Coverage_DriverOtherCarCode_A")
    assert not ps._DRIVER_PERSONAL_COLUMN_RE.match("Driver_FullName_A")


def test_driver_personal_columns_cleared_end_to_end():
    schema = {"Driver_FullName_A": {}, "Driver_GenderCode_A": {},
              "Driver_MaritalStatusCode_A": {}, "Driver_LicensedYear_A": {}}
    pre = {"filled_values": {"Driver_GenderCode_A": "F",
                             "Driver_MaritalStatusCode_A": "U",
                             "Driver_LicensedYear_A": "2012"},
           "raw_text_fields": set(), "question_grounding": {}}
    mapped, _ = ps.map_facts_to_form(
        {"auto_drivers": [{"name": "Erin Royal"}]}, schema, "ACORD_127",
        raw_text=_127_DOC, pre_filled_gpt=pre)
    assert mapped.get("Driver_GenderCode_A") is None
    assert mapped.get("Driver_MaritalStatusCode_A") is None
    assert mapped.get("Driver_LicensedYear_A") is None


# ── 4b. A Yes must carry its explanation (the owner's rule, verbatim) ─────────
# "whenever there is a Y, there should be an explanation mandatory."
# The six unpaired questions on the live 127 were EXACTLY the six wrong Ys;
# their dependent tables (owner names, conviction rows) were all empty.

def test_the_dependent_pairing_is_derived_correctly_from_the_real_127():
    import json
    schema = json.load(open(os.path.join(
        os.path.dirname(__file__), "..", "forms_schemas",
        "ACORD_127_schema.json"), encoding="utf-8"))
    fields = schema.get("fields", schema)
    pairs = ps._question_explanation_pairs(fields)
    deps = ps._unpaired_question_deps(fields, pairs)
    base = "CommercialVehicleLineOfBusiness_Question_{}Code_A"
    # Q1 not-solely-owned -> the VEH#/owner-name table.
    assert any("AdditionalInterest_FullName" in d
               for d in deps[base.format("AAJ")])
    # Q14 convictions -> the AccidentConviction table.
    assert any(d.startswith("AccidentConviction_")
               for d in deps[base.format("AAI")])
    # "(no explanation needed)" questions are EXEMPT - ACORD's own layout says
    # so: the next question follows immediately, leaving no dependent section.
    assert base.format("ABA") not in deps      # >50% employees
    assert base.format("KAG") not in deps      # fleet (also last-bounded)


def test_a_yes_with_an_empty_owner_table_is_blanked():
    """The literal Q1 defect: Y ticked, NAME OF OTHER OWNER empty."""
    fields = {
        "CommercialVehicleLineOfBusiness_Question_AAJCode_A":
            {"tu": _YN_TU.format(
                "are any vehicles not solely owned by the applicant?"), "ft": "/Tx"},
        "AdditionalInterest_FullName_C": {"tu": "Enter text: owner", "ft": "/Tx"},
        "CommercialVehicleLineOfBusiness_Question_ABACode_A":
            {"tu": _YN_TU.format("do over 50% use their autos?"), "ft": "/Tx"},
    }
    mapped = _run_gate(
        fields,
        {"CommercialVehicleLineOfBusiness_Question_AAJCode_A": "Y"},
        {"CommercialVehicleLineOfBusiness_Question_AAJCode_A":
         "The applicant transports acetylene cylinders to job sites weekly."})
    assert mapped.get("CommercialVehicleLineOfBusiness_Question_AAJCode_A") is None


def test_a_yes_with_its_owner_named_stands():
    fields = {
        "CommercialVehicleLineOfBusiness_Question_AAJCode_A":
            {"tu": _YN_TU.format(
                "are any vehicles not solely owned by the applicant?"), "ft": "/Tx"},
        "AdditionalInterest_FullName_C": {"tu": "Enter text: owner", "ft": "/Tx"},
        "CommercialVehicleLineOfBusiness_Question_ABACode_A":
            {"tu": _YN_TU.format("do over 50% use their autos?"), "ft": "/Tx"},
    }
    mapped = _run_gate(
        fields,
        {"CommercialVehicleLineOfBusiness_Question_AAJCode_A": "Y",
         "AdditionalInterest_FullName_C": "Meridian Fleet Leasing, LLC"},
        {"CommercialVehicleLineOfBusiness_Question_AAJCode_A":
         "The applicant transports acetylene cylinders to job sites weekly."})
    assert mapped.get(
        "CommercialVehicleLineOfBusiness_Question_AAJCode_A") == "Y"


def test_a_qualifier_only_run_is_not_an_explanation_section():
    """Safety-manual style checkbox runs are optional refinement, not
    substantiation - the corpus caught the first cut demanding them."""
    fields = {
        "CommercialPolicy_Question_ABDCode_A":
            {"tu": _YN_TU.format("is a formal safety program in operation?"),
             "ft": "/Tx"},
        "CommercialPolicy_FormalSafetyProgram_SafetyManualIndicator_A":
            {"tu": "Check the box", "ft": "/Btn"},
        "CommercialPolicy_Question_ABECode_A":
            {"tu": _YN_TU.format("any exposure to flammables?"), "ft": "/Tx"},
    }
    pairs = ps._question_explanation_pairs(fields)
    deps = ps._unpaired_question_deps(fields, pairs)
    assert "CommercialPolicy_Question_ABDCode_A" not in deps


# ── 5. The fax box ────────────────────────────────────────────────────────────

def test_fax_is_an_authoritative_blank_without_a_fax_fact():
    assert ps._resolve_party_fax("Producer_FaxNumber_A", {}) is None
    assert ps._is_authoritative_blank_field("Producer_FaxNumber_A", {})


def test_a_real_fax_fact_still_stamps():
    assert ps._resolve_party_fax(
        "Producer_FaxNumber_A", {"producer_fax": "303-996-7801"}) == "303-996-7801"


def test_non_fax_fields_are_not_claimed():
    assert ps._resolve_party_fax("Producer_ContactPerson_PhoneNumber_A", {}) \
        is ps._SCHED_SKIP
