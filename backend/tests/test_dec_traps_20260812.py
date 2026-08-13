"""The 52-page trap packet: five defects, each pinned by its literal trap string.

Source: the owner's synthetic EMC package (Orbin_Contracting_LLC_Policy_Packet,
52p) generated an ACORD 125 with: the Additional Insured schedule missing, Q3
FLAMMABLES = naked "Y" quoting the pollution exclusion, SAFETY MANUAL ticked
from "sample written safety manuals may be requested", loss-history "Check if
none" ticked off "NOT ON FILE", and the producer's office stamped as premises
LOC 4 despite the packet saying "this is not a location of the named insured".
"""
import glob
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("OPENAI_API_KEY", "sk-offline")

import services.extraction_service as es  # noqa: E402
import services.pdf_service as ps  # noqa: E402


def _acord125():
    return json.load(open(
        os.path.join(os.path.dirname(__file__), "..",
                     "forms_schemas", "ACORD_125_schema.json"),
        encoding="utf-8"))


# ── 1. risk_transfer: presence must never lose the vote ─────────────────────

_EMPTY_RT = {"additional_insured_required": False, "additional_insured_names": [],
             "primary_noncontributory_required": False,
             "waiver_of_subrogation_required": False,
             "certificate_holder_name": None, "loss_payee_name": None,
             "mortgagee_name": None, "specific_wording_requirements": None}
_DATA_RT = {"additional_insured_required": True,
            "additional_insured_names": ["Baseline Development Partners LLC",
                                         "Front Range Industrial REIT, Inc.",
                                         "City and County of Denver"],
            "primary_noncontributory_required": False,
            "waiver_of_subrogation_required": True,
            "certificate_holder_name": None, "loss_payee_name": None,
            "mortgagee_name": None, "specific_wording_requirements": None}


def test_one_chunk_with_the_ai_schedule_beats_ten_empty_chunks():
    partials = [{"_chunk_idx": i, "facts": {"risk_transfer": dict(_EMPTY_RT)},
                 "flags": {}} for i in range(10)]
    partials.insert(7, {"_chunk_idx": 99, "facts": {"risk_transfer": dict(_DATA_RT)},
                        "flags": {}})
    rt = es._merge_list_fields(partials, [])["facts"]["risk_transfer"]
    assert rt["additional_insured_required"] is True
    assert rt["waiver_of_subrogation_required"] is True
    assert len(rt["additional_insured_names"]) == 3


def test_a_document_with_no_risk_transfer_content_merges_as_before():
    partials = [{"_chunk_idx": i, "facts": {"risk_transfer": dict(_EMPTY_RT)},
                 "flags": {}} for i in range(3)]
    rt = es._merge_list_fields(partials, [])["facts"]["risk_transfer"]
    assert rt["additional_insured_required"] is False
    assert rt["additional_insured_names"] == []


def test_risk_transfer_union_survives_the_primary_wins_doc_merge():
    docs = [
        {"filename": "companion.pdf", "facts": {"risk_transfer": dict(_DATA_RT)},
         "flags": {}, "text": "x"},
        {"filename": "primary.pdf", "facts": {"risk_transfer": dict(_EMPTY_RT)},
         "flags": {}, "text": "x"},
    ]
    mf, _ = es.merge_facts(docs, docs[1])
    assert mf["risk_transfer"]["additional_insured_required"] is True
    assert len(mf["risk_transfer"]["additional_insured_names"]) == 3


# ── 2. Exclusion/grant clauses are never Y/N evidence ────────────────────────

def test_the_pollution_exclusion_is_not_exposure_evidence():
    assert ps._POLICY_DEFINITION_RE.search(
        "This insurance does not apply to bodily injury or property damage "
        "arising out of the actual, alleged or threatened discharge, dispersal, "
        "seepage, migration, release or escape of pollutants")


def test_the_xcu_grant_is_not_exposure_evidence():
    assert ps._POLICY_DEFINITION_RE.search("XCU exclusions are deleted.")
    assert ps._POLICY_DEFINITION_RE.search(
        "Coverage for explosion, collapse and underground property damage "
        "hazards is included for the classifications scheduled")


def test_a_real_applicant_statement_is_still_evidence():
    for real in ("The applicant stores diesel fuel and welding gases on site.",
                 "Estimated annual payroll exposure for this policy period: $39,300."):
        assert not ps._POLICY_DEFINITION_RE.search(real)


# ── 3. The final coherence sweep ─────────────────────────────────────────────

def test_a_naked_yes_recreated_by_a_late_guard_is_blanked():
    schema = _acord125()
    mapped = {"CommercialPolicy_Question_ABCCode_A": "Y",
              "CommercialPolicy_AnyExposureToFlammableExplosivesChemicalsExplanation_A": None}
    ps._final_yn_coherence(mapped, schema, "ACORD_125", set())
    assert mapped["CommercialPolicy_Question_ABCCode_A"] is None


def test_an_explained_yes_stands():
    schema = _acord125()
    mapped = {"CommercialPolicy_Question_ABCCode_A": "Y",
              "CommercialPolicy_AnyExposureToFlammableExplosivesChemicalsExplanation_A":
                  "Applicant stores diesel fuel on site."}
    ps._final_yn_coherence(mapped, schema, "ACORD_125", set())
    assert mapped["CommercialPolicy_Question_ABCCode_A"] == "Y"


def test_the_safety_manual_trap_an_ai_qualifier_under_a_blank_question():
    schema = _acord125()
    mapped = {"CommercialPolicy_Question_KAACode_A": None,
              "CommercialPolicy_FormalSafetyProgram_SafetyManualIndicator_A": "Yes"}
    gset = {"CommercialPolicy_FormalSafetyProgram_SafetyManualIndicator_A"}
    ps._final_yn_coherence(mapped, schema, "ACORD_125", gset)
    assert mapped["CommercialPolicy_FormalSafetyProgram_SafetyManualIndicator_A"] is None


def test_a_qualifier_under_an_affirmative_question_stands():
    schema = _acord125()
    mapped = {"CommercialPolicy_Question_KAACode_A": "Y",
              "CommercialPolicy_FormalSafetyProgram_SafetyManualIndicator_A": "Yes"}
    # Give the Yes its explanation so the naked-Yes rule leaves it alone, if
    # the schema pairs it; otherwise the qualifier rule is the one under test.
    pairs = ps._question_explanation_pairs(schema)
    exp = pairs.get("CommercialPolicy_Question_KAACode_A")
    if exp:
        mapped[exp] = "Formal safety program in place."
    gset = {"CommercialPolicy_FormalSafetyProgram_SafetyManualIndicator_A"}
    ps._final_yn_coherence(mapped, schema, "ACORD_125", gset)
    assert mapped["CommercialPolicy_FormalSafetyProgram_SafetyManualIndicator_A"] == "Yes"


def test_a_deterministic_tick_is_never_touched_by_the_qualifier_sweep():
    schema = _acord125()
    mapped = {"CommercialPolicy_Question_KAACode_A": None,
              "CommercialPolicy_FormalSafetyProgram_SafetyManualIndicator_A": "Yes"}
    ps._final_yn_coherence(mapped, schema, "ACORD_125", set())   # not AI-authored
    assert mapped["CommercialPolicy_FormalSafetyProgram_SafetyManualIndicator_A"] == "Yes"


def test_the_nature_of_business_grid_is_never_a_qualifier_set():
    """STANDING GUARD, harvested from the real schemas: the qualifier rule must
    keep finding exactly the audited five sets, and the NATURE OF BUSINESS grid
    (BusinessInformation_BusinessType_*) must never appear - blanking the
    Contractor checkbox is the failure this exclusion exists to prevent. A NEW
    run appearing after a schema regeneration fails here until a human
    classifies it (same pattern as _LEGACY_MESSAGE_RULES / _PAIRING_EXCLUDED)."""
    expected = {
        "ACORD_125": {"CommercialPolicy_Question_KAACode_A",
                      "CommercialPolicy_Question_AACCode_A"},
        "ACORD_126": {"GeneralLiabilityLineOfBusiness_Question_KAHCode_A"},
        "ACORD_141": {"CrimeLineOfBusiness_Question_KAQCode_A"},
        "ACORD_160": {"CommercialStructure_Question_KACCode_A"},
    }
    base = os.path.join(os.path.dirname(__file__), "..", "forms_schemas")
    seen = {}
    for path in glob.glob(os.path.join(base, "*_schema.json")):
        form = os.path.basename(path).replace("_schema", "").replace(".json", "")
        form = os.path.basename(path)[: -len("_schema.json")]
        schema = json.load(open(path, encoding="utf-8"))
        qmap = ps._question_qualifier_indicators(schema)
        if qmap:
            seen[form] = set(qmap)
            for run in qmap.values():
                assert not any("BusinessType" in f for f in run), (form, run)
    assert seen == expected, (
        f"qualifier harvest changed: {seen} - classify any new run before shipping")


# ── 4. The loss-history "Check if none" box ──────────────────────────────────

def test_not_on_file_never_ticks_the_none_box():
    # The packet's literal state: no loss facts, no flags, nothing asserted.
    # The box must be an AUTHORITATIVE blank - never handed to gap fill, which
    # is how "Prior Term Loss Experience: NOT ON FILE" became a tick.
    out = ps._resolve_no_loss_checkbox_owned("LossHistory_NoPriorLossesIndicator_A", {})
    assert out is None


def test_an_explicit_no_loss_flag_still_ticks_it():
    out = ps._resolve_no_loss_checkbox_owned(
        "LossHistory_NoPriorLossesIndicator_A", {"no_prior_losses": True})
    assert out == "Yes"


def test_real_claims_still_answer_no():
    out = ps._resolve_no_loss_checkbox_owned(
        "LossHistory_NoPriorLossesIndicator_A", {"num_claims": "2"})
    assert out == "No"


def test_other_fields_are_not_this_resolvers_business():
    assert ps._resolve_no_loss_checkbox_owned("Producer_FullName_A", {}) is ps._SCHED_SKIP


# ── 5 + 7a. Premises: the producer-office trap and the job-sites parse ───────

def _packet_locs():
    return {
        "producer_address": "9780 S. Meridian Blvd., Suite 400, Englewood, CO 80112-6072",
        "property_locations": [
            {"address": "4800 DAHLIA ST STE D13, DENVER, CO 80216-3121", "county": "DENVER"},
            {"address": "14225 E 33RD PL UNIT F, AURORA, CO 80011-8106"},
            {"address": "VARIOUS JOB SITES, STATE OF COLORADO"},
            {"address": "9780 S MERIDIAN BLVD STE 400, ENGLEWOOD, CO 80112-6072"},
        ],
    }


def test_the_producer_office_never_becomes_premises_four():
    facts = _packet_locs()
    es._consolidate_property_locations(facts)
    locs = facts["property_locations"]
    assert len(locs) == 3
    assert all("MERIDIAN" not in str(l.get("address", "")).upper() for l in locs)


def test_the_real_locations_all_survive_the_party_filter():
    facts = _packet_locs()
    es._consolidate_property_locations(facts)
    joined = " | ".join(str(l.get("address", "")).upper()
                        for l in facts["property_locations"])
    assert "DAHLIA" in joined and "33RD" in joined and "JOB SITES" in joined


def test_job_sites_row_prints_no_garbage_city_state_zip():
    facts = _packet_locs()
    es._consolidate_property_locations(facts)
    job = next(l for l in facts["property_locations"]
               if "JOB SITES" in str(l.get("address", "")).upper())
    assert job.get("address_city") is None
    assert job.get("address_state") is None
    assert job.get("address_zip") is None


def test_a_full_state_name_converts_instead_of_wiping():
    facts = {"property_locations": [
        {"address": "100 Main St, Aurora, CO 80010",
         "address_state": "Colorado"}]}
    es._consolidate_property_locations(facts)
    assert facts["property_locations"][0]["address_state"] == "CO"


# -- Second 52p run (2026-08-13): the two quotes that dodged the first fix --

def test_the_exclusion_heading_is_never_evidence():
    # The literal quote the gate KEPT on the re-run: the exclusion's own
    # section title - a bare noun phrase no clause pattern matches.
    assert ps._quote_cites_contract_machinery(
        '"POLLUTION EXCLUSION - FLAMMABLES, EXPLOSIVES AND CHEMICALS"')


def test_the_loss_control_offer_is_never_evidence():
    assert ps._quote_cites_contract_machinery(
        "Sample written safety manuals, monthly safety meeting outlines, "
        "toolbox talk materials, OSHA recordkeeping guidance and jobsite "
        "inspection checklists may be requested from your servicing office")
    assert ps._quote_cites_contract_machinery(
        "Availability of these materials does not obligate the policyholder "
        "to adopt any safety program.")


def test_dec_page_coverage_rows_remain_valid_evidence():
    # The KEPT_YES quotes from the same run that are CORRECT and must survive:
    # coverage indicator rows straight off the auto dec.
    for good in ('"LIABILITY 01 $ 1,000,000 COMBINED SINGLE"',
                 '"AUTO MEDICAL PAYMENTS 07 $ 5,000 EACH PERSON"',
                 '"UNDERINSURED MOTORISTS 07 $ 1,000,000 EACH ACCIDENT"',
                 "Estimated annual payroll exposure for this policy period: $39,300."):
        assert not ps._quote_cites_contract_machinery(good)
