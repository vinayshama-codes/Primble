"""Live run 15 Sep 2026 - the client's own Orbin policy, session 136e3c11.

One section per fix. Every fixture is the LIVE data shape: the literal values
the stored session carries, run through the real ACORD schemas and templates,
and asserted through the seam the screen reads (`map_facts_to_form` /
`compute_form_gaps`) wherever the defect showed on a form.
"""
import json
import os
import re

import pytest

import services.pdf_service as ps
from services import state_auto_grid as sag
from services.display_canonicalizer import canonicalize_currency
from services.extraction_service import _backfill_empty_facts_from_entries, _backfill_value_for
from services.fact_registry import _is_currency
from services.lob_canon import carried_lines_of_business, is_charge_label, unmapped_material_lines
from services.state_restricted_boxes import outside_its_state, restricted_boxes

_BACKEND = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_ORBIN_ADDRESS = "4800 DAHLIA ST # D13, DENVER, CO 80216-3121"


def _schema(fid):
    with open(os.path.join(_BACKEND, "forms_schemas", f"{fid}_schema.json"), encoding="utf-8") as fh:
        return json.load(fh)


def _gpt(values, grounding=None):
    return {"filled_values": dict(values), "raw_text_fields": set(),
            "question_grounding": dict(grounding or {})}


def _blank(value):
    return value is None or str(value).strip() in ("", "null", "None")


def _digits(value):
    return re.sub(r"\D", "", str(value or ""))


# ─────────────────────────────────────────────────────────────────────────────
# 1. The expiring agency's phone printed as the applicant's business phone
# ─────────────────────────────────────────────────────────────────────────────
def _orbin_producer_facts():
    """The live merge after the producer block moved (Chat 4): the submitting
    agency comes from the login, the documents' agency is `expiring_*`."""
    return {
        "applicant_name": "ORBIN CONTRACTING LLC",
        "mailing_address": _ORBIN_ADDRESS,
        "producer_name": {"value": "Astrea It services", "source": "account",
                          "confidence": "deterministic"},
        "producer_contact_name": {"value": "vinay sharma", "source": "account",
                                  "confidence": "deterministic"},
        "expiring_producer_name": "COMMERCIAL RISK SOLUTIONS, INC.",
        "expiring_producer_address": "9780 S MERIDIAN BLVD STE 400, ENGLEWOOD, CO 80112-6072",
        "expiring_producer_contact_phone": "303-996-7800",
    }


def test_every_producer_fact_has_an_expiring_twin_owned_by_the_producer():
    producer_keys = [k for k in ps._FACT_ENTITY if k.startswith("producer_")]
    assert producer_keys
    for key in producer_keys:
        assert ps._FACT_ENTITY.get("expiring_" + key) == "Producer", key


def test_the_ownership_guard_sees_the_expiring_axis():
    mapped = {"NamedInsured_Primary_PhoneNumber_A": "(303)996-7800"}
    out = ps._drop_foreign_entity_values(mapped, _orbin_producer_facts(), set(mapped))
    assert out == ["NamedInsured_Primary_PhoneNumber_A"]
    assert mapped["NamedInsured_Primary_PhoneNumber_A"] is None


def test_the_live_phone_never_prints_through_the_seam():
    field = "NamedInsured_Primary_PhoneNumber_A"
    mapped, _ = ps.map_facts_to_form(
        _orbin_producer_facts(), _schema("ACORD_125"), form_id="ACORD_125",
        raw_text="DIRECT BILL AGENT PHONE (303)996-7800",
        pre_filled_gpt=_gpt({field: "(303)996-7800"}))
    assert _blank(mapped.get(field))


def test_the_applicants_own_phone_is_kept():
    field = "NamedInsured_Primary_PhoneNumber_A"
    mapped, _ = ps.map_facts_to_form(
        _orbin_producer_facts(), _schema("ACORD_125"), form_id="ACORD_125",
        raw_text="Business phone (720) 555-0199",
        pre_filled_gpt=_gpt({field: "(720) 555-0199"}))
    assert _digits(mapped.get(field)) == "7205550199"


def test_a_number_that_is_also_the_applicants_own_stays():
    """Ambiguity keeps the fill - a captive agency, or a mixed extraction."""
    facts = {**_orbin_producer_facts(), "contact_phone": "(303) 996-7800"}
    mapped = {"NamedInsured_Primary_PhoneNumber_A": "(303)996-7800"}
    assert ps._drop_foreign_entity_values(mapped, facts, set(mapped)) == []


def test_an_expiring_agency_email_is_a_producers():
    facts = {**_orbin_producer_facts(), "contact_email": "terri@commercialrisksolutions.com"}
    assert ps._contact_email_party(facts) == "producer"
    facts["expiring_producer_name"] = ""
    assert ps._contact_email_party(facts) is None


# ─────────────────────────────────────────────────────────────────────────────
# 2. The money formatter read digits, not the amount
# ─────────────────────────────────────────────────────────────────────────────
@pytest.mark.parametrize("raw, printed", [
    ("$1M", "$1,000,000"), ("$5K", "$5,000"), ("$1.5 million", "$1,500,000"),
    ("$500K", "$500,000"), ("$ 1000 DED", "$1,000"), ("1,000 MED", "$1,000"),
    ("$500,000(any one premises)", "$500,000"), ("$1,000,000 CSL", "$1,000,000"),
    ("1,000,000.00", "$1,000,000"), ("$1000000.0", "$1,000,000"), ("2500.50", "$2,500.50"),
])
def test_one_amount_prints_at_its_real_size(raw, printed):
    assert canonicalize_currency(raw) == printed


@pytest.mark.parametrize("raw", [
    "$1,000,000 / $2,000,000", "100 $ 185.00", "$250,000/$500,000/$100,000/$50,000",
    "6E7-40-02---26", "TBD", "Statutory", "Included",
])
def test_anything_but_one_amount_is_returned_as_written(raw):
    assert canonicalize_currency(raw) == raw


def test_a_shorthand_limit_reaches_the_form_at_its_real_size():
    mapped, _ = ps.map_facts_to_form({"has_general_liability": True, "gl_each_occurrence": "$1M"},
                                     _schema("ACORD_126"), form_id="ACORD_126", raw_text="")
    assert _digits(mapped.get("GeneralLiability_EachOccurrence_LimitAmount_A")) == "1000000"


# ─────────────────────────────────────────────────────────────────────────────
# 3. Damage to Rented Premises: printed on the policy, never picked up
# ─────────────────────────────────────────────────────────────────────────────
_PREMISES_ENTRY = {"label": "Damage To Premises Rented To You Limit",
                   "value": "$500,000(any one premises)",
                   "section": "General Liability Declarations", "owner": "policy",
                   "policy_number": "BBC7263 - 26", "line_of_business": "General Liability"}


def test_the_policy_premises_limit_backfills_from_its_printed_name():
    facts: dict = {}
    _backfill_empty_facts_from_entries(facts, [dict(_PREMISES_ENTRY)])
    rec = facts.get("gl_fire_damage_limit")
    assert rec and rec["value"] == "$500,000"
    assert rec["derivation"]["entry_value"] == "$500,000(any one premises)"


@pytest.mark.parametrize("fid", ["ACORD_126", "ACORD_131"])
def test_it_reaches_the_premises_box(fid):
    facts = {"has_general_liability": True, "has_umbrella": True}
    _backfill_empty_facts_from_entries(facts, [dict(_PREMISES_ENTRY)])
    mapped, _ = ps.map_facts_to_form(facts, _schema(fid), form_id=fid, raw_text="")
    box = "GeneralLiability_FireDamageRentedPremises_EachOccurrenceLimitAmount_A"
    assert _digits(mapped.get(box)) == "500000", mapped.get(box)


@pytest.mark.parametrize("entry", [
    {**_PREMISES_ENTRY, "value": "$500,000 each / $1,000,000 aggregate"},   # two amounts
    {**_PREMISES_ENTRY, "owner": "producer"},                                # wrong party
    {**_PREMISES_ENTRY, "label": "Premises Rented Limit"},                   # part of the name
])
def test_the_backfill_still_refuses(entry):
    facts: dict = {}
    _backfill_empty_facts_from_entries(facts, [entry])
    assert "gl_fire_damage_limit" not in facts


def test_two_different_stated_limits_are_ambiguity():
    facts: dict = {}
    _backfill_empty_facts_from_entries(facts, [dict(_PREMISES_ENTRY),
                                               {**_PREMISES_ENTRY, "value": "$300,000"}])
    assert "gl_fire_damage_limit" not in facts


def test_a_stated_value_is_never_overwritten():
    facts = {"gl_fire_damage_limit": {"value": "$100,000"}}
    _backfill_empty_facts_from_entries(facts, [dict(_PREMISES_ENTRY)])
    assert facts["gl_fire_damage_limit"] == {"value": "$100,000"}


@pytest.mark.parametrize("raw, out", [
    ("$500,000(any one premises)", "$500,000"), ("$500,000", "$500,000"),
    ("8556 $ 250.00", None), ("Rated Locations", None),
])
def test_one_amount_with_its_qualifier_is_the_value(raw, out):
    assert _backfill_value_for(_is_currency, raw) == out


# ─────────────────────────────────────────────────────────────────────────────
# 4. A cannabis exclusion's list item stood as a "Yes"
# ─────────────────────────────────────────────────────────────────────────────
_CBD = ('f. Offers retail sales of "CBD products" where such products are marketed '
        'under your own label;')
_Q8 = "GeneralLiabilityLineOfBusiness_Question_ABGCode_A"
_Q8_EXPLANATION = "GeneralLiabilityLineOfBusiness_ProductsUnderLabelOfOthersExplanation_A"


def test_an_acronym_led_defined_term_is_policy_wording():
    assert ps._is_policy_wording_fragment(_CBD)
    assert ps._is_policy_wording_fragment('"autos" you lease, hire, rent or borrow')


@pytest.mark.parametrize("text", [
    "Date of Issue: 07/16/2025",
    "The applicant sells products under the label of Acme Corp.",
    'THE MOST "WE" PAY',
    "Subcontractors are required to carry coverage.",
])
def test_an_applicant_statement_is_not(text):
    assert not ps._is_policy_wording_fragment(text)


def test_the_live_yes_is_refused_through_the_gate():
    raw = "CANNABIS EXCLUSION WITH LIMITED EXCEPTION FOR RETAIL SALES OF CBD PRODUCTS\n" + _CBD
    mapped, _ = ps.map_facts_to_form(
        {}, _schema("ACORD_126"), form_id="ACORD_126", raw_text=raw,
        pre_filled_gpt=_gpt({_Q8: "Y", _Q8_EXPLANATION: _CBD}, {_Q8: _CBD}))
    assert _blank(mapped.get(_Q8))
    assert _blank(mapped.get(_Q8_EXPLANATION))


def test_a_real_statement_still_answers_it():
    fact = "The applicant sells products under the label of Acme Corp."
    mapped, _ = ps.map_facts_to_form(
        {}, _schema("ACORD_126"), form_id="ACORD_126", raw_text=fact,
        pre_filled_gpt=_gpt({_Q8: "Y", _Q8_EXPLANATION: fact}, {_Q8: fact}))
    assert str(mapped.get(_Q8) or "").upper().startswith("Y")


# ─────────────────────────────────────────────────────────────────────────────
# 5a. ACORD 131 TRANSACTION TYPE is the producer's call
# ─────────────────────────────────────────────────────────────────────────────
_131_TRANSACTION = ("ExcessUmbrella_Transactiontype_OtherIndicator_A",
                    "ExcessUmbrella_Transactiontype_OtherDescription_A")


@pytest.mark.parametrize("field", _131_TRANSACTION)
def test_the_131_transaction_type_is_an_owned_blank(field):
    assert ps._resolve_policy_status(field, {}) is None
    assert ps._resolve_policy_status(field, {"is_renewal": "yes"}) is None


def test_the_renew_box_still_follows_a_stated_renewal():
    assert ps._resolve_policy_status("Policy_Status_RenewIndicator_A", {"is_renewal": "yes"}) == "Yes"


def test_the_live_8_other_never_prints():
    _m, unmatched, _d = ps.compute_form_gaps("ACORD_131", _schema("ACORD_131"),
                                             {"applicant_name": "ORBIN CONTRACTING LLC"})
    assert not set(unmatched) & set(_131_TRANSACTION)
    mapped, _ = ps.map_facts_to_form(
        {"applicant_name": "ORBIN CONTRACTING LLC"}, _schema("ACORD_131"), form_id="ACORD_131",
        raw_text="8 Other", pre_filled_gpt=_gpt({_131_TRANSACTION[0]: "Yes",
                                                  _131_TRANSACTION[1]: '"8 Other"'}))
    assert all(_blank(mapped.get(f)) for f in _131_TRANSACTION)


# ─────────────────────────────────────────────────────────────────────────────
# 5b. An OTHER amount whose description a LATER guard removed
# ─────────────────────────────────────────────────────────────────────────────
_OTHER_AMOUNT = "GeneralLiability_OtherCoverageLimitAmount_A"
_OTHER_NAME = "GeneralLiability_OtherCoverageLimitDescription_A"


# The sweep is exercised on ACORD 25 since 16 Sep 2026 (live run 10): the same
# two boxes there are still gap-filled, while the 126's OTHER limit row is owned -
# the GL declarations' own extra limit or blank - so gap fill never fills it.
def test_the_orphan_sweep_runs_after_the_last_guard(monkeypatch):
    """The live order: a guard late in the chain refused the description after
    the sweep had passed. Reproduced by making the LAST guard do it."""
    real = ps._dedupe_stamped_premises_rows

    def late_guard(mapped, *args, **kwargs):
        mapped[_OTHER_NAME] = None
        return real(mapped, *args, **kwargs)

    monkeypatch.setattr(ps, "_dedupe_stamped_premises_rows", late_guard)
    mapped, _ = ps.map_facts_to_form(
        {}, _schema("ACORD_25"), form_id="ACORD_25", raw_text="Stop Gap Liability $1,000,000",
        pre_filled_gpt=_gpt({_OTHER_NAME: "Stop Gap Liability", _OTHER_AMOUNT: "$1,000,000"}))
    assert _blank(mapped.get(_OTHER_AMOUNT))


def test_a_named_other_coverage_keeps_its_amount():
    mapped, _ = ps.map_facts_to_form(
        {}, _schema("ACORD_25"), form_id="ACORD_25", raw_text="Stop Gap Liability $1,000,000",
        pre_filled_gpt=_gpt({_OTHER_NAME: "Stop Gap Liability", _OTHER_AMOUNT: "$1,000,000"}))
    assert not _blank(mapped.get(_OTHER_NAME))
    assert _digits(mapped.get(_OTHER_AMOUNT)) == "1000000"


def test_on_the_126_a_declared_other_limit_keeps_its_amount():
    entries = [{"label": "Stop Gap Liability Limit", "value": "$1,000,000",
                "line_of_business": "Commercial General Liability",
                "section": "General Liability Declarations", "owner": "policy"}]
    mapped, _ = ps.map_facts_to_form(
        {"dec_page_entries": entries}, _schema("ACORD_126"), form_id="ACORD_126")
    assert mapped.get(_OTHER_NAME) == "Stop Gap Liability"
    assert _digits(mapped.get(_OTHER_AMOUNT)) == "1000000"


# ─────────────────────────────────────────────────────────────────────────────
# 5c. ACORD 137 hired autos: cost of hire, days and vehicles
# ─────────────────────────────────────────────────────────────────────────────
_AUTO = {"has_auto_coverage": True, "auto_hired_nonowned": "Yes",
         "auto_liability_limit": "$ 1,000,000",
         "auto_covered_symbols": [{"coverage": "liability", "symbols": [1]},
                                  {"coverage": "medical payments", "symbols": [2]}]}
_HIRED_FIGURES = ("Vehicle_HiredBorrowed_HiredCostAmount_A",
                  "Vehicle_HiredPhysicalDamage_DayCount_A",
                  "Vehicle_HiredPhysicalDamage_VehicleCount_A")


@pytest.mark.parametrize("field", _HIRED_FIGURES)
def test_hired_exposure_figures_are_owned_blanks(field):
    assert sag.resolve("ACORD_137_CO", field, _AUTO) is None


@pytest.mark.parametrize("field", ["Vehicle_HiredBorrowed_YesIndicator_A",
                                   "Vehicle_NonOwned_YesIndicator_A",
                                   "Vehicle_HiredBorrowed_StateOrProvinceCode_A"])
def test_the_hired_and_non_owned_answers_still_reach_the_document(field):
    assert sag.resolve("ACORD_137_CO", field, _AUTO) is not None


def test_the_live_hired_figures_never_print():
    live = {"Vehicle_HiredBorrowed_HiredCostAmount_A": "100",
            "Vehicle_HiredPhysicalDamage_DayCount_A": "100",
            "Vehicle_HiredPhysicalDamage_VehicleCount_A": "1"}
    mapped, _ = ps.map_facts_to_form(dict(_AUTO), _schema("ACORD_137_CO"), form_id="ACORD_137_CO",
                                     raw_text="EXCESS CO IF ANY 100 $ 185.00",
                                     pre_filled_gpt=_gpt(live))
    for field in live:
        assert _blank(mapped.get(field)), field


# ─────────────────────────────────────────────────────────────────────────────
# 5d. Boxes printed under "APPLICABLE ONLY IN <STATE>"
# ─────────────────────────────────────────────────────────────────────────────
_WI_BOXES = frozenset({
    "GeneralLiability_UninsuredUnderinsuredMotorists_CoverageAvailableIndicator_A",
    "GeneralLiability_UninsuredUnderinsuredMotorists_CoverageAvailableNoIndicator_A",
    "GeneralLiability_MedicalPayments_CoverageAvailableIndicator_A",
    "GeneralLiability_MedicalPayments_CoverageAvailableNoIndicator_A",
})


def test_the_template_harvest_is_exactly_what_was_measured():
    """All 17 templates. A template change that moves a box into or out of a
    state block fails here, loudly, instead of silently changing a form."""
    found = {fid: dict(restricted_boxes(fid)) for fid in ps._all_form_schemas()}
    found = {fid: boxes for fid, boxes in found.items() if boxes}
    assert found == {
        "ACORD_126": {f: frozenset({"WI"}) for f in _WI_BOXES},
        "ACORD_131": {"NamedInsured_Initials_E": frozenset({"MT"})},
    }


def test_a_colorado_risk_is_not_asked_the_wisconsin_question():
    facts = {"mailing_address": _ORBIN_ADDRESS}
    assert all(outside_its_state("ACORD_126", f, facts) for f in _WI_BOXES)
    _m, unmatched, _d = ps.compute_form_gaps("ACORD_126", _schema("ACORD_126"), facts)
    assert not set(unmatched) & _WI_BOXES


def test_the_live_tick_never_prints():
    field = "GeneralLiability_MedicalPayments_CoverageAvailableIndicator_A"
    mapped, _ = ps.map_facts_to_form({"mailing_address": _ORBIN_ADDRESS}, _schema("ACORD_126"),
                                     form_id="ACORD_126", raw_text="Auto Medical Payments $5,000",
                                     pre_filled_gpt=_gpt({field: "Yes"}))
    assert _blank(mapped.get(field))


@pytest.mark.parametrize("facts", [
    {"mailing_address": "100 Main St, Madison, WI 53703"},                 # the state itself
    {"mailing_address": _ORBIN_ADDRESS, "locations": [{"state": "WI"}]},  # touches it
    {},                                                                    # nothing known
])
def test_no_opinion_unless_the_risk_is_provably_elsewhere(facts):
    for field in _WI_BOXES:
        assert not outside_its_state("ACORD_126", field, facts)
        assert ps._resolve_out_of_state_box(field, {**facts, "_form_id": "ACORD_126"}) is ps._SCHED_SKIP


# ─────────────────────────────────────────────────────────────────────────────
# 6. Coverage lines: one name per line; a premium subtotal is not a coverage
# ─────────────────────────────────────────────────────────────────────────────
_LIVE_MENTIONS = ["Property", "Liability", "Crime and Fidelity", "Inland Marine", "Automobile",
                  "Workers' Compensation", "Umbrella", "Other", "Commercial Inland Marine",
                  "Computer Coverage", "Commercial Auto", "Commercial Umbrella",
                  "Commercial Liability Umbrella", "Commercial General Liability"]
_LIVE_ROWS = [
    {"line": "Liability", "policy_number": "BBC7263 - 26", "premium": "$3,954.00"},
    {"line": "Inland Marine", "policy_number": "6C7-40-02---26", "premium": "$300.00"},
    {"line": "Automobile", "policy_number": "6E7-40-02---26", "premium": "$2,991.00"},
    {"line": "Umbrella", "policy_number": "6J7-40-02---26", "premium": "$3,418.00"},
    {"line": "COMPREHENSIVE", "premium": "$ 134.00"},
    {"line": "Premium for Attached Items 4, 5, and/or 6", "premium": "$ 322.00"},
    {"line": "Premium for Endorsements", "premium": "$ 457.00"},
]
_LIVE_FLAGS = {"has_property_coverage": False, "has_workers_comp": False}


def test_the_cover_prints_one_name_per_line():
    carried = carried_lines_of_business(
        {"lines_of_business": _LIVE_MENTIONS, "coverage_lines": _LIVE_ROWS}, _LIVE_FLAGS)
    assert carried == ["Liability", "Inland Marine", "Automobile", "Umbrella"]


def test_the_legacy_branch_folds_too():
    carried = carried_lines_of_business({"lines_of_business": ["Automobile", "Commercial Auto"]}, {})
    assert carried == ["Automobile"]


def test_premium_subtotals_are_not_routed_as_unknown_coverages():
    assert unmapped_material_lines(_LIVE_ROWS) == []


def test_a_genuinely_unknown_carried_coverage_still_is():
    rows = _LIVE_ROWS + [{"line": "Wedding Cancellation", "premium": "$410.00"}]
    assert unmapped_material_lines(rows) == ["Wedding Cancellation"]


@pytest.mark.parametrize("name, charge", [
    ("Premium for Endorsements", True), ("Premium for Attached Items 4, 5, and/or 6", True),
    ("Total", True), ("State Surcharge", True), ("Policy Fee", True),
    ("Premises Liability", False), ("Commercial Auto", False), ("Taxi Liability", False),
])
def test_a_charge_label(name, charge):
    assert is_charge_label(name) is charge


# ─────────────────────────────────────────────────────────────────────────────
# 7. Noise: an emptied driver table, and a dead interest row
# ─────────────────────────────────────────────────────────────────────────────
_ERIN = [{"name": "ERIN ROYAL", "role": "named_individual", "territory": "104"}]
_SUBARU = [{"year": "2012", "make": "SUBARU", "model": "OUTBACK SEDAN",
            "vin": "4S4BRCGC9C3217772", "class_code": "7383", "territory": "111"}]


def test_an_emptied_driver_table_is_not_asked_about():
    facts = {"has_auto_coverage": True, "auto_drivers": [], "auto_named_individuals": _ERIN,
             "auto_vin_schedule": _SUBARU, "mailing_address": _ORBIN_ADDRESS}
    _m, unmatched, _d = ps.compute_form_gaps("ACORD_127", _schema("ACORD_127"), facts)
    assert not [f for f in unmatched if f.startswith("Driver_")]


def test_the_live_driver_rows_report_nothing():
    facts = {"has_auto_coverage": True, "auto_drivers": [], "auto_named_individuals": _ERIN,
             "auto_vin_schedule": _SUBARU, "mailing_address": _ORBIN_ADDRESS}
    live = {f"Driver_MailingAddress_CityName_{r}": "Denver" for r in "ABCDEFGHIJKLM"}
    report: list = []
    mapped, _ = ps.map_facts_to_form(facts, _schema("ACORD_127"), form_id="ACORD_127",
                                     raw_text=_ORBIN_ADDRESS, pre_filled_gpt=_gpt(live),
                                     guard_report=report)
    assert all(_blank(mapped.get(f)) for f in live)
    assert not [r for r in report if r["field"].startswith("Driver_")]


def test_an_empty_driver_list_with_nobody_moved_out_changes_nothing():
    facts = {"has_auto_coverage": True, "auto_drivers": [], "auto_vin_schedule": _SUBARU}
    _m, unmatched, _d = ps.compute_form_gaps("ACORD_127", _schema("ACORD_127"), facts)
    assert [f for f in unmatched if f.startswith("Driver_")]


def test_a_real_driver_row_is_still_a_real_row():
    facts = {"auto_drivers": [{"name": "Jane Doe", "dob": "01/02/1980"}],
             "auto_named_individuals": _ERIN}
    ps._set_schema_context(_schema("ACORD_127"))
    assert ps._resolve_phantom_schedule_row("Driver_BirthDate_A", facts) is ps._SCHED_SKIP


def test_a_dead_interest_row_is_one_decision():
    """The live ACORD 125 shape: gap fill proposed an interest row; its
    checkboxes went to the Yes/No gate and its city to the nameless-row guard.
    Every cell used to be reported as its own finding."""
    live = {"AdditionalInterest_CertificateRequiredIndicator_A": "Yes",
            "AdditionalInterest_Interest_LossPayeeIndicator_A": "Yes",
            "AdditionalInterest_MailingAddress_CityName_A": "Denver"}
    report: list = []
    mapped, _ = ps.map_facts_to_form(
        {"applicant_name": "ORBIN CONTRACTING LLC", "mailing_address": _ORBIN_ADDRESS},
        _schema("ACORD_125"), form_id="ACORD_125", raw_text=_ORBIN_ADDRESS,
        pre_filled_gpt=_gpt(live), guard_report=report)
    assert all(_blank(mapped.get(f)) for f in live)
    assert not [r for r in report if r["field"].startswith("AdditionalInterest_")]


# ─────────────────────────────────────────────────────────────────────────────
# 8. The Employee Benefits rule stays on the form it was measured on
# ─────────────────────────────────────────────────────────────────────────────
def test_the_employee_benefits_rule_stays_on_acord_126():
    rows = [{"line": "Liability", "premium": "$3,954"}]
    field = "GeneralLiability_EmployeeBenefits_LimitAmount_A"
    assert ps._resolve_uncarried_coverage_part(field, {"coverage_lines": rows,
                                                       "_form_id": "ACORD_126"}) is None
    for other in ({"coverage_lines": rows, "_form_id": "ACORD_160"}, {"coverage_lines": rows}):
        assert ps._resolve_uncarried_coverage_part(field, other) is ps._SCHED_SKIP
