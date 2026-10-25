"""Build 22 (21 Oct 2026), lane W: five wrong form values the owner parked on 15 Oct
(25sepChanges.md "P15", Z31-W). Every rule acts on AI gap-fill values only - a
person's value and a deterministic rule's value are never judged - and every
refusal names its reason on the guard row.

  P15-1  ACORD 130 rating effective / normal anniversary rating dates printed the
         EXPIRING term's 01/01/2025 on a renewal for 01/01/2026-27. A rating date
         describes the policy being applied for: an AI date outside the proposed
         term is refused (AI_RATING_DATE_NOT_THE_PROPOSED_TERM).
  P15-2  ACORD 126 PRODUCTS / COMPLETED OPERATIONS row = the business description.
         An AI products row that equals, contains or is whole sentences of the
         package's operations description is refused
         (AI_PRODUCT_IS_THE_BUSINESS_DESCRIPTION); a real product row stands.
  P15-3  ACORD 127 garaging printed with NO vehicle. A garaging box belongs to a
         vehicle row - row A included - so an AI garaging value on a row that
         names no vehicle is refused (AI_GARAGING_WITHOUT_A_VEHICLE).
  P15-4  "Item 3A State: CO" printed as a value. A document's item label plus a
         field label is stripped to the value when the label names the box and
         the value fits it, otherwise refused (AI_DOCUMENT_ITEM_LABEL).
  P15-7  ACORD 131's deterministic ANY AUTO tick was blanked by the naked-Yes
         guard. ROOT CAUSE: position-based pairing ran on a schema whose keys
         were in JSONB order (the copy stored on the session row, which the
         re-stamp door reads), so the tick "paired" with OtherDescription_A. The
         pairing now reads the form's own layout order whatever the dict order;
         and a tick a deterministic rule printed is exempt from the AI
         Yes / explanation pairing guard.

Adversarial cases come first in each part. Offline: the real ACORD schemas, no
database, no model.
"""
import json
import os

import pytest

from services import ai_answer_guards as g
from services import needs_attention as na
from services import pdf_service as ps

HERE = os.path.dirname(os.path.abspath(__file__))


def _schema(form_id):
    with open(os.path.join(HERE, "..", "forms_schemas", f"{form_id}_schema.json"),
              encoding="utf-8") as fh:
        return json.load(fh)


ALL_FORMS = sorted(n[: -len("_schema.json")] for n in os.listdir(
    os.path.join(HERE, "..", "forms_schemas")) if n.startswith("ACORD_") and n.endswith("_schema.json"))
S125, S126, S127, S130, S131 = (_schema(f) for f in
                                ("ACORD_125", "ACORD_126", "ACORD_127", "ACORD_130", "ACORD_131"))


def _jsonb(schema):
    """The key order PostgreSQL JSONB stores an object in: shorter keys first,
    then byte order - what a schema read back from the session row looks like."""
    return {k: schema[k] for k in sorted(schema, key=lambda k: (len(k.encode()), k.encode()))}


def _codes(out):
    return {f: str(why).split(":", 1)[0] for f, why in out.items()}


def _stamp(form_id, facts, ai, raw="", schema=None, monkeypatch=None):
    if monkeypatch is not None:
        monkeypatch.setattr(ps, "_EVIDENCE_JUDGE_ENABLED", False)
    report = []
    mapped, conf = ps.map_facts_to_form(
        dict(facts), schema if schema is not None else _schema(form_id), form_id, raw,
        pre_filled_gpt={"filled_values": dict(ai), "raw_text_fields": set(), "question_grounding": {}},
        guard_report=report, allow_llm=False)
    return mapped, {r.get("field"): r.get("reason") for r in report}, conf


def _person(v):
    return {"value": v, "source": "producer", "confidence": "filled", "value_state": "present"}


# ═══════════════════════════════════════════════════════════════════════════
# P15-1 - a rating date describes the policy being applied for
# ═══════════════════════════════════════════════════════════════════════════

RATING = "Policy_RatingEffectiveDate_A"
ANNIV = "Policy_NormalAnniversaryRatingDate_A"
EFF, EXP = "Policy_EffectiveDate_A", "Policy_ExpirationDate_A"

RENEWAL = {
    "applicant_name": "Choice Electric LLC",
    "effective_date": {"value": "01/01/2026", "source": "derived"},
    "expiration_date": {"value": "01/01/2027", "source": "derived"},
    "prior_effective_date": {"value": "01/01/2025", "routed_from": "current_term"},
    "prior_expiration_date": {"value": "01/01/2026", "routed_from": "current_term"},
    "renewal_dates_routed": True,
    "is_renewal": True,
    "has_workers_comp": True,
}
WC_RAW = ("WORKERS' COMPENSATION AND EMPLOYERS' LIABILITY INFORMATION PAGE\n"
          "Item 2. Policy Period: from\n01/01/2025 TO 01/01/2026\n"
          "CO 9898 Experience Mod 1.0800 2,904.00\nIssue Date 12/13/2024\n")


def _rate(values, mapped_header=("01/01/2026", "01/01/2027"), facts=RENEWAL, ai=None):
    mapped = {EFF: mapped_header[0], EXP: mapped_header[1], **values}
    out = g.refuse_non_answers(mapped, S130, dict(facts), WC_RAW,
                               set(ai if ai is not None else values), "ACORD_130")
    return _codes(out), mapped


def test_p15_1_the_rule_reads_exactly_the_rating_date_boxes_of_all_17_forms():
    hits = {(fid, f) for fid in ALL_FORMS for f, meta in _schema(fid).items()
            if g.is_rating_date_box(f, _schema(fid))}
    assert hits == {("ACORD_130", RATING), ("ACORD_130", ANNIV)}
    # dates that are not rating dates are never this rule's
    for f in ("Form_CompletionDate_A", "Binder_EffectiveDate_A", EFF, EXP,
              "NamedInsured_SignatureDate_A", "WorkersCompensation_Individual_BirthDate_A"):
        assert not g.is_rating_date_box(f, S130), f


@pytest.mark.parametrize("value", ["01/01/2026", "1/1/2026", "2026-01-01", "January 1, 2026",
                                   "07/01/2026", "12/31/2026"])
def test_p15_1_a_date_inside_the_proposed_term_stands(value):
    why, mapped = _rate({RATING: value, ANNIV: value})
    assert RATING not in why and ANNIV not in why
    assert mapped[RATING] == value and mapped[ANNIV] == value


@pytest.mark.parametrize("value", ["01/01/2025", "1/1/2025", "2025-01-01", "January 1, 2025",
                                   "12/31/2025", "01/01/2025 TO 01/01/2026"])
def test_p15_1_the_expiring_terms_date_is_refused(value):
    why, mapped = _rate({RATING: value, ANNIV: value})
    assert why == {RATING: g.REASON_RATING_DATE_OTHER_TERM, ANNIV: g.REASON_RATING_DATE_OTHER_TERM}
    assert mapped[RATING] is None and mapped[ANNIV] is None


@pytest.mark.parametrize("value", ["01/01/2027", "06/30/2027", "01/01/2028"])
def test_p15_1_both_directions_a_date_on_or_after_the_proposed_expiration_is_refused(value):
    why, _m = _rate({RATING: value})
    assert why == {RATING: g.REASON_RATING_DATE_OTHER_TERM}


def test_p15_1_brents_17_oct_run_proposed_2027_rating_2025():
    """Proposed 01/01/2027 (Brent retyped it), rating and anniversary 01/01/2025;
    the 2026 date is the start of the term BEFORE the proposed one too."""
    facts = dict(RENEWAL, effective_date=_person("01/01/2027"), expiration_date=_person("01/01/2028"))
    for value in ("01/01/2025", "01/01/2026"):
        why, _m = _rate({RATING: value, ANNIV: value}, ("01/01/2027", "01/01/2028"), facts)
        assert why == {RATING: g.REASON_RATING_DATE_OTHER_TERM, ANNIV: g.REASON_RATING_DATE_OTHER_TERM}
    why, _m = _rate({RATING: "01/01/2027"}, ("01/01/2027", "01/01/2028"), facts)
    assert not why


def test_p15_1_a_persons_or_a_rules_rating_date_is_never_judged():
    why, mapped = _rate({RATING: "01/01/2025", ANNIV: "01/01/2025"}, ai=set())
    assert not why and mapped[RATING] == "01/01/2025"


def test_p15_1_no_proposed_date_on_the_form_reads_the_facts_then_the_expiring_term():
    # the form's header blank: the proposed effective date fact decides
    why, _m = _rate({RATING: "01/01/2025"}, ("", ""))
    assert why == {RATING: g.REASON_RATING_DATE_OTHER_TERM}
    # no proposed date anywhere (a renewal whose term is asked): the expiring
    # term the merge moved to prior_* decides - before its end is that term's
    asked = {k: v for k, v in RENEWAL.items() if k not in ("effective_date", "expiration_date")}
    why, _m = _rate({RATING: "01/01/2025"}, ("", ""), asked)
    assert why == {RATING: g.REASON_RATING_DATE_OTHER_TERM}
    why, _m = _rate({RATING: "01/01/2026"}, ("", ""), asked)
    assert not why


def test_p15_1_no_term_known_anywhere_is_never_judged():
    why, mapped = _rate({RATING: "01/01/2025"}, ("", ""), {"applicant_name": "X"})
    assert not why and mapped[RATING] == "01/01/2025"


@pytest.mark.parametrize("value", ["Annual", "N/A see mod worksheet", "2025"])
def test_p15_1_a_value_with_no_readable_date_is_not_this_rules(value):
    why, _m = _rate({RATING: value})
    assert why.get(RATING) != g.REASON_RATING_DATE_OTHER_TERM


def test_p15_1_a_backwards_header_bounds_nothing_after_the_effective_date():
    why, _m = _rate({RATING: "03/01/2026"}, ("01/01/2026", "12/01/2025"))
    assert not why
    why, _m = _rate({RATING: "01/01/2025"}, ("01/01/2026", "12/01/2025"))
    assert why == {RATING: g.REASON_RATING_DATE_OTHER_TERM}


def test_p15_1_end_to_end_the_130_prints_no_expiring_rating_date(monkeypatch):
    mapped, why, _c = _stamp("ACORD_130", RENEWAL, {RATING: "01/01/2025", ANNIV: "01/01/2025"},
                             WC_RAW, monkeypatch=monkeypatch)
    assert mapped.get(EFF) == "01/01/2026"
    assert not mapped.get(RATING) and not mapped.get(ANNIV)
    assert why.get(RATING) == g.REASON_RATING_DATE_OTHER_TERM
    assert why.get(ANNIV) == g.REASON_RATING_DATE_OTHER_TERM
    mapped, why, _c = _stamp("ACORD_130", RENEWAL, {RATING: "01/01/2026", ANNIV: "01/01/2026"},
                             WC_RAW + "Rating Effective Date 01/01/2026\n", monkeypatch=monkeypatch)
    assert mapped.get(RATING) == "01/01/2026" and mapped.get(ANNIV) == "01/01/2026"


# ═══════════════════════════════════════════════════════════════════════════
# P15-2 - the products row is the applicant's products, not its description
# ═══════════════════════════════════════════════════════════════════════════

PNAME = "ProductAndCompletedOperations_ProductName_{}"
PSALES = "ProductAndCompletedOperations_AnnualGrossSalesAmount_{}"
PUSE = "ProductAndCompletedOperations_IntendedUse_{}"
OPS = ("Commercial and residential electrical contractor performing tenant finish, service work "
       "and new construction in the Denver metro area. Approximately 70% of the work is new "
       "construction.")
OPS_FACTS = {"applicant_name": "Choice Electric LLC", "operations_description": OPS,
             "has_general_liability": True}


def _products(values, facts=OPS_FACTS, ai=None):
    mapped = dict(values)
    refused, cascade = ps._product_rows_to_refuse(mapped, S126, dict(facts),
                                                  set(ai if ai is not None else values))
    return refused, cascade


@pytest.mark.parametrize("name", [
    "Electrical panels",                              # a phrase inside the description
    "Lighting fixtures and controls",
    "Electrical installation services",               # a service (ACORD allows one)
    "Tenant finish electrical work",
    "commercial and residential electrical contractor",   # a fragment, not a whole sentence
])
def test_p15_2_a_real_product_or_service_row_stands(name):
    refused, cascade = _products({PNAME.format("A"): name, PSALES.format("A"): "$400,000"})
    assert not refused and not cascade


def test_p15_2_a_short_description_cannot_be_told_from_a_name_and_stands():
    facts = dict(OPS_FACTS, operations_description="Electrical contracting")
    refused, _c = _products({PNAME.format("A"): "Electrical contracting"}, facts)
    assert not refused


@pytest.mark.parametrize("name", [
    OPS,                                                           # the whole description
    OPS.upper(),                                                   # its capitals
    OPS.replace(",", "").replace(".", ";"),                        # its punctuation
    ("Commercial and residential electrical contractor performing tenant finish, service work "
     "and new construction in the Denver metro area."),            # one whole sentence
    "Approximately 70% of the work is new construction",           # another whole sentence
    "Products: " + OPS,                                            # contains it all
])
def test_p15_2_the_business_description_is_refused_with_its_row(name):
    refused, cascade = _products({PNAME.format("A"): name, PSALES.format("A"): "$3,200,000"})
    assert refused == {PNAME.format("A"): g.REASON_PRODUCT_IS_OPERATIONS}
    assert cascade == {PSALES.format("A")}


def test_p15_2_every_row_and_every_description_fact_counts():
    wc = "Electrical wiring within buildings, service and repair for commercial customers."
    facts = {"wc_description_of_operations": {"value": wc, "source": "ai"},
             "account_description": "Electrical contractor in business since 2008 with two locations."}
    refused, _c = _products({PNAME.format("B"): wc,
                             PNAME.format("C"): "Electrical contractor in business since 2008 with two locations"},
                            facts)
    assert refused == {PNAME.format("B"): g.REASON_PRODUCT_IS_OPERATIONS,
                       PNAME.format("C"): g.REASON_PRODUCT_IS_OPERATIONS}


def test_p15_2_a_description_cell_is_refused_alone_and_its_named_row_stands():
    refused, cascade = _products({PNAME.format("A"): "Electrical panels", PUSE.format("A"): OPS})
    assert refused == {PUSE.format("A"): g.REASON_PRODUCT_IS_OPERATIONS} and not cascade


def test_p15_2_a_persons_row_and_a_package_with_no_description_are_never_judged():
    refused, cascade = _products({PNAME.format("A"): OPS, PSALES.format("A"): "$3,200,000"}, ai=set())
    assert not refused and not cascade
    refused, _c = _products({PNAME.format("A"): OPS}, {"applicant_name": "X"})
    assert not refused


def test_p15_2_a_persons_typed_description_is_still_the_business_description():
    facts = dict(OPS_FACTS, operations_description=_person(OPS))
    refused, _c = _products({PNAME.format("A"): OPS})
    refused2, _c2 = _products({PNAME.format("A"): OPS}, facts)
    assert refused == refused2 == {PNAME.format("A"): g.REASON_PRODUCT_IS_OPERATIONS}


def test_p15_2_the_rating_class_rules_are_unchanged():
    facts = dict(OPS_FACTS, gl_class_code_schedule=[{"class_code": "91580",
                                                     "classification": "Contractors - Executive Supervisors"}])
    refused, _c = _products({PNAME.format("A"): "91580", PNAME.format("B"): "12345"}, facts)
    assert refused == {PNAME.format("A"): "PRODUCT_IS_A_RATING_CLASS",
                       PNAME.format("B"): "PRODUCT_NAME_IS_A_NUMBER"}


def test_p15_2_end_to_end_the_126_row_is_blank_with_its_reason(monkeypatch):
    mapped, why, _c = _stamp("ACORD_126", OPS_FACTS,
                             {PNAME.format("A"): OPS, PSALES.format("A"): "$3,200,000"},
                             OPS + " Gross sales $3,200,000", monkeypatch=monkeypatch)
    assert not mapped.get(PNAME.format("A")) and not mapped.get(PSALES.format("A"))
    assert why.get(PNAME.format("A")) == g.REASON_PRODUCT_IS_OPERATIONS
    mapped, why, _c = _stamp("ACORD_126", OPS_FACTS,
                             {PNAME.format("A"): "Lighting fixtures and controls"},
                             OPS + " Lighting fixtures and controls", monkeypatch=monkeypatch)
    assert mapped.get(PNAME.format("A"))


# ═══════════════════════════════════════════════════════════════════════════
# P15-3 - a garaging box belongs to a vehicle row, row A included
# ═══════════════════════════════════════════════════════════════════════════

GAR = "Vehicle_PhysicalAddress_{}_{}"
GARAGING_AI = {GAR.format("LineOne", "A"): "4800 DAHLIA STREET D13", GAR.format("CityName", "A"): "DENVER",
               GAR.format("StateOrProvinceCode", "A"): "CO", GAR.format("PostalCode", "A"): "80216"}
AUTO_RAW = ("LOC: 001 4800 DAHLIA STREET D13 DENVER CO. 80216-3121\n"
            "001 2019 FORD TRANSIT 1FTBW2CM5KKA12345 COST NEW 41,800\n")


def _unanchored(mapped, ai=None):
    return ps._unanchored_schedule_row_fields(dict(mapped), S127,
                                              set(ai if ai is not None else mapped), form_id="ACORD_127")


def test_p15_3_row_as_other_boxes_are_still_never_judged():
    """The row-A exemption exists for per-form boxes that share the Vehicle root
    (`Vehicle_Question_ModifiedEquipmentDescription_A`); only the garaging
    column is a vehicle-row box judged on row A."""
    odd = {"Vehicle_Question_ModifiedEquipmentDescription_A": "Ladder racks",
           "CommercialVehicleLineOfBusiness_GarageStorageDescription_A": "Fenced yard at the shop",
           "Vehicle_CostNewAmount_A": "41,800"}
    assert not _unanchored(odd)


def test_p15_3_a_vehicle_on_row_a_keeps_its_garaging_whoever_named_it():
    for vehicle in ({"Vehicle_VINIdentifier_A": "1FTBW2CM5KKA12345"},
                    {"Vehicle_ModelYear_A": "2019", "Vehicle_ManufacturersName_A": "FORD"}):
        assert not _unanchored({**GARAGING_AI, **vehicle})


def test_p15_3_a_persons_or_a_rules_garaging_is_never_judged():
    assert not _unanchored(GARAGING_AI, ai=set())


def test_p15_3_garaging_with_no_vehicle_on_row_a_is_refused():
    assert _unanchored(GARAGING_AI) == set(GARAGING_AI)
    county = {GAR.format("CountyName", "A"): "Denver"}
    assert _unanchored(county) == set(county)


def test_p15_3_rows_beyond_a_vehicle_are_refused_as_before():
    m = {"Vehicle_VINIdentifier_A": "1FTBW2CM5KKA12345", GAR.format("CityName", "A"): "DENVER",
         GAR.format("CityName", "B"): "DENVER", GAR.format("PostalCode", "C"): "80216"}
    assert _unanchored(m) == {GAR.format("CityName", "B"), GAR.format("PostalCode", "C")}


def test_p15_3_end_to_end_no_vehicle_no_garaging_with_its_reason(monkeypatch):
    facts = {"applicant_name": "Choice Electric LLC", "has_auto_coverage": True, "auto_vin_schedule": []}
    mapped, why, _c = _stamp("ACORD_127", facts, GARAGING_AI, AUTO_RAW, monkeypatch=monkeypatch)
    for f in GARAGING_AI:
        assert not mapped.get(f), f
        assert why.get(f) == g.REASON_GARAGING_WITHOUT_A_VEHICLE, (f, why.get(f))


def test_p15_3_the_vehicle_identity_never_comes_from_gap_fill():
    """Why row A's identity is a sound anchor: VIN / year / make / model are the
    schedule's own cells - an owned blank with no schedule row, never asked of the
    AI - so an AI garaging value can never anchor itself on a vehicle it invented."""
    for facts in ({"has_auto_coverage": True, "auto_vin_schedule": []}, {"has_auto_coverage": True}):
        _m, gaps, _d = ps.compute_form_gaps("ACORD_127", S127, dict(facts))
        assert not {"Vehicle_VINIdentifier_A", "Vehicle_ModelYear_A", "Vehicle_ManufacturersName_A",
                    "Vehicle_ModelName_A"} & set(gaps)
        assert GAR.format("CityName", "A") in gaps          # garaging still reaches gap fill


def test_p15_3_end_to_end_a_scheduled_vehicle_keeps_the_ais_garaging(monkeypatch):
    facts = {"applicant_name": "Choice Electric LLC", "has_auto_coverage": True,
             "auto_vin_schedule": [{"vin": "1FTBW2CM5KKA12345", "year": "2019", "make": "FORD",
                                    "model": "TRANSIT"}]}
    mapped, why, _c = _stamp("ACORD_127", facts, GARAGING_AI, AUTO_RAW, monkeypatch=monkeypatch)
    assert mapped.get("Vehicle_VINIdentifier_A") == "1FTBW2CM5KKA12345"
    assert mapped.get(GAR.format("CityName", "A"))
    assert why.get(GAR.format("CityName", "A")) != g.REASON_GARAGING_WITHOUT_A_VEHICLE


# ═══════════════════════════════════════════════════════════════════════════
# P15-4 - a document's item label is not part of the value
# ═══════════════════════════════════════════════════════════════════════════

P1 = "WorkersCompensation_PartOne_StateOrProvinceCode_A"
OTHER_DESC = "WorkersCompensationStateCoverage_Other_CoverageDescription_A"
MAIL_STATE = "NamedInsured_MailingAddress_StateOrProvinceCode_A"


@pytest.mark.parametrize("value", [
    "Part-time employees: 5", "Partners: 2", "Itemized deductible: $500", "Items: 3",
    "Section 8 housing", "Item 1 of 3", "Part 1 Workers Compensation Law of CO",
    "Section 179 property: equipment", "Part 135 operator: charter flights",
    "Each item: $500", "Coverage Part: Commercial Property", "Section I: Property",
    "Partial: 2", "CO", "State: CO", "Item 3A: CO",
])
def test_p15_4_real_values_that_merely_contain_item_section_or_part_are_untouched(value):
    assert g.strip_document_item_label(P1, value, S130) is None, value


@pytest.mark.parametrize("value", [
    "Part 1: States: CO", "Part One - State: CO", "PART ONE - STATE: CO", "part one - state:CO",
    "Part I - State: CO", "Part 1 - States: CO",
])
def test_p15_4_the_label_is_stripped_when_it_names_the_box_and_the_value_fits(value):
    """ACORD 130 prints six state elements, so "State" alone names none of them;
    a reference the box's own name spells ("Part One") picks out Part 1's."""
    assert g.strip_document_item_label(P1, value, S130) == ("CO", None), value


def test_p15_4_other_boxes_and_types():
    assert g.strip_document_item_label(RATING, "Item 6 Rating Effective Date: 01/01/2026", S130) == \
        ("01/01/2026", None)
    assert g.strip_document_item_label(
        "NamedInsured_FullName_A", "Item 1 Name of Insured: Choice Electric LLC", S130) == \
        ("Choice Electric LLC", None)


@pytest.mark.parametrize("field,value,schema", [
    # The label must name the box's own data element, all of it - measured over
    # the 17 schemas with labelled probes, one shared word was not enough:
    ("Producer_FullName_A", "Item 1 Name of Insured: Choice Electric LLC", S130),
    ("Insurer_FullName_A", "Item 1 Name of Insured: Choice Electric LLC", S125),
    ("NamedInsured_MailingAddress_CityName_A", "Item 1 Name of Insured: Choice Electric LLC", S125),
    ("Policy_Audit_FrequencyCode_A", "Item 2 Policy Period: 01/01/2026", S125),
    ("Policy_ExpirationDate_A", "Item 2 Policy Period: 01/01/2026", S130),
    (RATING, "Item 2. Policy Period From: 01-01-2025", S130),    # the policy period, not a rating date
    ("Producer_StateLicenseIdentifier_A", "Item 3A State: CO", S125),
    # the label names the COVERAGE, not a state: refused although CO would fit
    # (blank over wrong - the label is the only witness of what the value is)
    (P1, "Item 3. A. Worker's Compensation Insurance: CO", S130),
])
def test_p15_4_a_label_that_names_another_element_is_refused(field, value, schema):
    new, why = g.strip_document_item_label(field, value, schema)
    assert new is None and str(why).startswith(g.REASON_ITEM_LABEL), (field, value)


@pytest.mark.parametrize("field,value", [
    (P1, "Item 4 Premium: $29,278"),               # the label names another item
    (OTHER_DESC, "Item 3A State: CO"),             # this box does not ask a state
    (OTHER_DESC, "Item 3D Endorsements: SEE EXTENSION OF INFORMATION PAGE"),
    (P1, "Item 3A State:"),                        # a label and nothing after it
    (P1, "Item 3A State: N/A"),                    # a placeholder
    (P1, "Item 3A State: JOHN SMITH"),             # not a code
])
def test_p15_4_otherwise_the_value_is_refused(field, value):
    new, why = g.strip_document_item_label(field, value, S130)
    assert new is None and str(why).split(":", 1)[0] == g.REASON_ITEM_LABEL, (field, value)


def test_p15_4_the_door_judges_ai_text_boxes_only():
    mapped = {P1: "Part One - State: CO", OTHER_DESC: "Item 3A State: CO",
              "WorkersCompensationLineOfBusiness_Question_ABFCode_A": "Item 3 Answer: Y"}
    out = g.document_item_label_values(dict(mapped), S130, {"_form_id": "ACORD_130"}, set(mapped))
    assert out == {P1: ("CO", None), OTHER_DESC: (None, out[OTHER_DESC][1])}
    assert str(out[OTHER_DESC][1]).startswith(g.REASON_ITEM_LABEL)
    assert not g.document_item_label_values(dict(mapped), S130, {"_form_id": "ACORD_130"}, set())
    # the owner's frozen forms are never touched
    assert not g.document_item_label_values({"X_A": "Item 3A State: CO"}, {"X_A": {"tu": "Enter text: state"}},
                                            {"_form_id": "ACORD_160"}, {"X_A"})  # 141 judged since Z41


def test_p15_4_end_to_end_strip_and_refuse_through_the_stamper(monkeypatch):
    """Review of 21 Oct: the first cut printed a clean "CO" here - in the
    insured's MAILING state, from WC Item 3A, where it passes the raw-text check
    because CO is printed. The label was the only witness, and on ACORD 130
    "State" names six elements: refused."""
    facts = {"applicant_name": "Choice Electric LLC", "has_workers_comp": True,
             "effective_date": "01/01/2026", "expiration_date": "01/01/2027"}
    mapped, why, _c = _stamp("ACORD_130", facts,
                             {MAIL_STATE: "Item 3A State: CO",
                              OTHER_DESC: "Item 3D Endorsements: SEE EXTENSION OF INFORMATION PAGE"},
                             "Item 3. A. Worker's Compensation Insurance: CO\n", monkeypatch=monkeypatch)
    assert not mapped.get(MAIL_STATE)
    assert why.get(MAIL_STATE) == g.REASON_ITEM_LABEL
    assert not mapped.get(OTHER_DESC)
    assert why.get(OTHER_DESC) == g.REASON_ITEM_LABEL


# Lines the Choice Electric decs really print (25-26 Workers Compensation /
# Cyber / Umbrella / Excess, read off the local PDFs), as the AI would copy them.
@pytest.mark.parametrize("field,value,expected", [
    (RATING, "Item 2. Policy Period From: 01-01-2025", "refused"),
    (P1, "Item 1. Insured Name:", "refused"),
    (P1, "Item 7 of the Declarations to include: CO", None),              # prose, not a label
    (P1, "Item 3. A. Worker's Compensation Insurance: Part One of the Policy applies to the "
         "Workers Compensation Law of the states listed here:", "refused"),  # not a code
    (P1, "ITEM TWO: SCHEDULE OF COVERAGES AND COVERED AUTOS", None),
    (P1, "SECTION II - COVERED AUTOS LIABILITY", None),
])
def test_p15_4_the_real_dec_lines(field, value, expected):
    got = g.strip_document_item_label(field, value, S130)
    if expected == "refused":
        assert got is not None and got[0] is None and str(got[1]).startswith(g.REASON_ITEM_LABEL)
    else:
        assert got == expected


def test_p15_4_an_explanations_label_may_name_its_question():
    exp = "GeneralLiabilityLineOfBusiness_SubcontractorsCarryLowerLimitsExplanation_A"
    S126_ = _schema("ACORD_126")
    assert g.strip_document_item_label(
        exp, "Section 4 - Subcontractors: every subcontractor carries the same limits", S126_) == \
        ("every subcontractor carries the same limits", None)
    new, why = g.strip_document_item_label(exp, "Item 4 Premium: $29,278", S126_)
    assert new is None and str(why).startswith(g.REASON_ITEM_LABEL)


def test_p15_4_a_stripped_date_is_then_judged_as_a_date(monkeypatch):
    """The strip runs FIRST, so the rating-date rule sees 01/01/2025 and refuses it
    for what it is - the expiring term's date; the proposed term's date prints bare."""
    mapped, why, _c = _stamp("ACORD_130", RENEWAL, {RATING: "Item 6 Rating Effective Date: 01/01/2025"},
                             WC_RAW, monkeypatch=monkeypatch)
    assert not mapped.get(RATING)
    assert why.get(RATING) == g.REASON_RATING_DATE_OTHER_TERM
    mapped, why, _c = _stamp("ACORD_130", RENEWAL, {RATING: "Item 6 Rating Effective Date: 01/01/2026"},
                             WC_RAW + "Rating Effective Date 01/01/2026\n", monkeypatch=monkeypatch)
    assert mapped.get(RATING) == "01/01/2026"
    # ...and a policy period offered as a rating date is the item label's refusal
    mapped, why, _c = _stamp("ACORD_130", RENEWAL, {RATING: "Item 2. Policy Period From: 01-01-2026"},
                             WC_RAW, monkeypatch=monkeypatch)
    assert not mapped.get(RATING) and why.get(RATING) == g.REASON_ITEM_LABEL


# ═══════════════════════════════════════════════════════════════════════════
# P15-7 - a deterministic tick, and pairing read in the form's own order
# ═══════════════════════════════════════════════════════════════════════════

ANY_AUTO = "UnderlyingCoverage_Coverage_AnyAutoIndicator_A"
ANY_AUTO_FACTS = {"applicant_name": "Choice Electric LLC", "has_umbrella": True, "has_auto_coverage": True,
                  "auto_covered_symbols": [{"coverage": "Liability", "symbols": [1]}]}


def test_p15_7_a_synthetic_schema_keeps_its_own_order():
    """Only a schema whose keys ARE a real form's is re-ordered - every synthetic
    schema the older tests build (where dict order is the point) is untouched."""
    sub = {k: S131[k] for k in list(S131)[150:170]}
    rev = dict(reversed(list(sub.items())))
    assert list(ps._in_layout_order(rev)) == list(rev)
    assert ps._in_layout_order(S131) is S131                    # already the layout: same object
    assert list(ps._in_layout_order(_jsonb(S131))) == list(S131)


def test_p15_7_a_stubbed_schema_loader_never_switches_the_door_off(monkeypatch):
    """Order pollution: a test stubs `_all_form_schemas` (lambda: {}). The layout
    table is read off the schema files themselves, so the stub cannot leave it
    empty for every later caller in the run."""
    monkeypatch.setattr(ps, "_LAYOUT_ORDERS_CACHE", None)
    monkeypatch.setattr(ps, "_all_form_schemas", lambda: {})
    assert list(ps._in_layout_order(_jsonb(S131))) == list(S131)
    assert sum(len(v) for v in ps._LAYOUT_ORDERS_CACHE.values()) == len(ALL_FORMS)


@pytest.mark.parametrize("form_id", ALL_FORMS)
def test_p15_7_pairing_is_the_same_in_any_key_order(form_id):
    s = _schema(form_id)
    for shuffled in (_jsonb(s), dict(reversed(list(s.items())))):
        assert ps._question_explanation_pairs(shuffled) == ps._question_explanation_pairs(s)
        assert ps._question_dependent_block(shuffled) == ps._question_dependent_block(s)
        assert ps._question_qualifier_indicators(shuffled) == ps._question_qualifier_indicators(s)


def test_p15_7_the_any_auto_tick_has_no_pair_in_any_order():
    assert ANY_AUTO not in ps._question_explanation_pairs(S131)
    assert ANY_AUTO not in ps._question_explanation_pairs(_jsonb(S131))


def test_p15_7_end_to_end_the_tick_prints_on_a_stored_schema(monkeypatch):
    for schema in (S131, _jsonb(S131)):
        mapped, why, _c = _stamp("ACORD_131", ANY_AUTO_FACTS, {}, "", schema=schema, monkeypatch=monkeypatch)
        assert mapped.get(ANY_AUTO) == "Yes"
        assert ANY_AUTO not in why


def test_p15_7_the_restamp_shape_keeps_the_tick():
    """`arq_service._restamp_changed_boxes` runs the guards over the stored
    (JSONB-ordered) schema with no AI set."""
    trial = {ANY_AUTO: "Yes", "UnderlyingCoverage_Coverage_OtherDescription_A": ""}
    ps._enforce_post_fill_guards(trial, _jsonb(S131), dict(ANY_AUTO_FACTS), gpt_filled_set=set())
    assert trial[ANY_AUTO] == "Yes"


def _generated(form_id, facts, schema):
    """A generated form as generation leaves it: every deterministic box."""
    state, conf = {}, {}
    with ps._schema_context(_schema(form_id)):
        for box in schema:
            if ps._is_nonfillable_field(box):
                continue
            v = ps._deterministic_map(box, {**facts, "_form_id": form_id})
            if v not in (None, "", "UNMATCHED"):
                state[box], conf[box] = str(v), "filled"
    return {form_id: {"schema": schema, "field_state": state, "confidence": conf,
                      "client_filled_fields": []}}


def test_p15_7_the_restamp_door_prints_the_tick_on_the_stored_schema():
    """THE LIVE PATH: the auto symbols arrive after forms (the Business Auto
    Policy added later, item 25) and the re-stamp moves ANY AUTO to Yes - on the
    schema copy read back from the session row."""
    from services.arq_service import _restamp_changed_boxes
    before = {k: v for k, v in ANY_AUTO_FACTS.items() if k != "auto_covered_symbols"}
    after = dict(ANY_AUTO_FACTS)
    gen = _generated("ACORD_131", before, _jsonb(S131))
    assert not gen["ACORD_131"]["field_state"].get(ANY_AUTO)
    _restamp_changed_boxes(gen, before, after, own_keys={"auto_covered_symbols"})
    assert gen["ACORD_131"]["field_state"].get(ANY_AUTO) == "Yes"


def test_p15_7_the_restamp_door_keeps_a_persons_other_interest_tick():
    from services.arq_service import _restamp_changed_boxes
    row = {"location_number": "1", "building_number": "1", "address_line1": "2080 W 60th Ave",
           "address_city": "Denver", "address_state": "CO", "address_zip": "80221"}
    before = {"applicant_name": "Choice Electric LLC",
              "property_locations": [dict(row, is_owner=True, is_tenant=False, is_other_interest=False)]}
    after = {"applicant_name": "Choice Electric LLC",
             "property_locations": [dict(row, is_owner=False, is_tenant=False, is_other_interest=True)]}
    gen = _generated("ACORD_125", before, _jsonb(S125))
    _restamp_changed_boxes(gen, before, after, own_keys={"property_locations"})
    state = gen["ACORD_125"]["field_state"]
    assert state.get(OTHER_TICK_125) == "Yes"
    assert state.get("CommercialStructure_InsuredInterest_OwnerIndicator_A") == "No"


OTHER_TICK_125 = "CommercialStructure_InsuredInterest_OtherIndicator_A"


OTHER_TICK = "CommercialStructure_InsuredInterest_OtherIndicator_A"
OTHER_DESC125 = "CommercialStructure_InsuredInterest_OtherDescription_A"
DRONE_Q = "CommercialPolicy_Question_ABCCode_A"
DRONE_X = "CommercialPolicy_AnyExposureToFlammableExplosivesChemicalsExplanation_A"


def test_p15_7_an_ai_tick_and_every_yes_answer_still_need_their_explanation():
    for gset, ticks in ((set(), None), ({OTHER_TICK}, {OTHER_TICK}), (set(), set())):
        m = {OTHER_TICK: "Yes", OTHER_DESC125: None}
        ps._enforce_post_fill_guards(m, S125, {"_form_id": "ACORD_125"}, gset, deterministic_ticks=ticks)
        assert m[OTHER_TICK] is None, (gset, ticks)
        m = {OTHER_TICK: "Yes", OTHER_DESC125: None}
        ps._final_yn_coherence(m, S125, "ACORD_125", set(gset), deterministic_ticks=ticks)
        assert m[OTHER_TICK] is None, (gset, ticks)
    # a Yes ANSWER (a text Y/N box) is not a tick: a rule's naked Y still goes
    m = {DRONE_Q: "Y", DRONE_X: None}
    ps._enforce_post_fill_guards(m, S125, {"_form_id": "ACORD_125"}, set(), deterministic_ticks={DRONE_Q})
    assert m[DRONE_Q] is None
    m = {DRONE_Q: "Y", DRONE_X: None}
    ps._final_yn_coherence(m, S125, "ACORD_125", set(), deterministic_ticks={DRONE_Q})
    assert m[DRONE_Q] is None


def test_p15_7_a_tick_a_rule_printed_stands_without_its_description():
    m = {OTHER_TICK: "Yes", OTHER_DESC125: None}
    ps._enforce_post_fill_guards(m, S125, {"_form_id": "ACORD_125"}, set(), deterministic_ticks={OTHER_TICK})
    assert m[OTHER_TICK] == "Yes"
    ps._final_yn_coherence(m, S125, "ACORD_125", set(), deterministic_ticks={OTHER_TICK})
    assert m[OTHER_TICK] == "Yes"


def test_p15_7_end_to_end_a_persons_other_interest_tick_prints(monkeypatch):
    """The location table's interest "Other" (no description typed): the tick is
    the person's answer; the description is asked, the tick is not blanked."""
    facts = {"applicant_name": "Choice Electric LLC",
             "property_locations": [{"location_number": "1", "building_number": "1",
                                     "address_line1": "2080 W 60th Ave", "address_city": "Denver",
                                     "address_state": "CO", "address_zip": "80221",
                                     "is_owner": False, "is_tenant": False, "is_other_interest": True}]}
    mapped, why, _c = _stamp("ACORD_125", facts, {}, "", monkeypatch=monkeypatch)
    assert mapped.get(OTHER_TICK) == "Yes"
    assert OTHER_TICK not in why
    # ...and an AI's Other tick with no description still goes
    mapped, why, _c = _stamp("ACORD_125", {"applicant_name": "Choice Electric LLC"},
                             {OTHER_TICK: "Yes"}, "", monkeypatch=monkeypatch)
    assert not mapped.get(OTHER_TICK)


# ═══════════════════════════════════════════════════════════════════════════
# The review says why, in plain words
# ═══════════════════════════════════════════════════════════════════════════

NEW_REASONS = ("REASON_RATING_DATE_OTHER_TERM", "REASON_PRODUCT_IS_OPERATIONS",
               "REASON_GARAGING_WITHOUT_A_VEHICLE", "REASON_ITEM_LABEL")


@pytest.mark.parametrize("name", NEW_REASONS)
def test_every_new_reason_has_its_plain_sentence_and_quotes_nothing(name):
    code = getattr(g, name)
    assert code in g.REASON_CODES
    s = g.held_back_sentence(code)
    assert s and s.endswith(".") and "—" not in s and "–" not in s
    sentence, quotable = na.held_back(S130, RATING, "01/01/2025", {}, None, None, reason=code)
    assert sentence == s and quotable is False


def test_every_new_top_level_name_is_defined_once():
    """A second top-level definition silently replaces the first for every
    earlier reader (tests/test_no_module_name_redefined.py's class) - the first
    cut of P15-2 reused `_SENTENCE_BREAK_RE`, which pdf_service already owns."""
    import ast
    import collections
    mine = {
        "pdf_service.py": {"_word_key", "_operations_descriptions", "_is_the_operations_description",
                           "_OPERATIONS_FACT_KEYS", "_DESCRIPTION_MIN_WORDS", "_OPS_SENTENCE_BREAK_RE",
                           "_in_layout_order", "_layout_orders", "_ticks_a_rule_printed", "_LAYOUT_ORDERS_CACHE",
                           "_SENTENCE_BREAK_RE"},
        "ai_answer_guards.py": {"_RATING_DATE_BOX_RE", "_PROPOSED_TERM_BOXES", "_DATE_IN_TEXT_RE",
                                "is_rating_date_box", "_iso_date", "_dates_in", "_proposed_term",
                                "rating_date_outside_the_term", "_ITEM_NUMBER_WORDS", "_DOC_ITEM_LABEL_RE",
                                "_LABEL_FILLER", "_CAMEL_WORD_RE", "_word_stems", "_DATA_TYPE_WORDS", "_label_names_the_box",
                                "_LABEL_QUANTIFIERS", "_label_stem", "_DATA_TYPE_STEMS", "_element_segments",
                                "_NUMBER_WORD_DIGITS", "_ROMAN_DIGITS", "_REFERENCE_WORDS", "_reference_key",
                                "_box_reference_keys", "_spells_the_name", "_LABEL_BOXES_CACHE",
                                "_boxes_the_label_names", "_label_picks_out_the_box",
                                "strip_document_item_label", "document_item_label_values",
                                "REASON_RATING_DATE_OTHER_TERM", "REASON_ITEM_LABEL",
                                "REASON_PRODUCT_IS_OPERATIONS", "REASON_GARAGING_WITHOUT_A_VEHICLE"},
    }
    for module, names in mine.items():
        with open(os.path.join(HERE, "..", "services", module), encoding="utf-8") as fh:
            tree = ast.parse(fh.read())
        seen = collections.Counter()
        for node in tree.body:
            if isinstance(node, (ast.FunctionDef, ast.ClassDef)):
                seen[node.name] += 1
            elif isinstance(node, ast.Assign):
                for t in node.targets:
                    if isinstance(t, ast.Name):
                        seen[t.id] += 1
            elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
                seen[node.target.id] += 1
        assert {n: seen[n] for n in names if seen[n] != 1} == {}, module


# ═══════════════════════════════════════════════════════════════════════════
# Review fixes (21 Oct): the label must pick out THIS box; stems; one door
# ═══════════════════════════════════════════════════════════════════════════

S125_ = S125
STATE_BOXES_130 = sorted(f for f in S130 if "StateOrProvinceCode" in f and not g._skip_box(f, S130))
EL_ACCIDENT = "WorkersCompensationEmployersLiability_EmployersLiability_EachAccidentLimitAmount_A"
GL_OCC = "GeneralLiability_EachOccurrence_LimitAmount_A"
UMB_OCC = "ExcessUmbrella_Umbrella_EachOccurrenceAmount_A"
INSPECTION = "NamedInsured_InspectionContact_FullName_A"
ACCOUNTING = "NamedInsured_AccountingContact_FullName_A"


def _refused(field, value, schema):
    got = g.strip_document_item_label(field, value, schema)
    return got is not None and got[0] is None and str(got[1]).split(":", 1)[0] == g.REASON_ITEM_LABEL


@pytest.mark.parametrize("value", ["Item 3A State: CO", "Item 3.A. State: CO", "ITEM 3A STATE: CO",
                                   "item 3a state:CO", "Item 3A: State: CO", "Item No. 3A State: CO",
                                   "Item #3A State: CO", "Section 3(a) State: CO"])
def test_review_a_generic_label_is_refused_in_every_box_it_could_be(value):
    """The reviewer's case: WC Item 3A's "CO" for an insured mailing from AZ.
    "State" names the producer's, the insured's mailing, the locations', Part
    1's, Part 3's and the individuals' state on ACORD 130 - none is picked out."""
    assert MAIL_STATE in STATE_BOXES_130 and P1 in STATE_BOXES_130 and len(STATE_BOXES_130) > 20
    for box in STATE_BOXES_130:
        assert _refused(box, value, S130), (box, value)


def test_review_the_refusal_says_the_label_is_ambiguous():
    _new, why = g.strip_document_item_label(MAIL_STATE, "Item 3A State: CO", S130)
    assert why.startswith(g.REASON_ITEM_LABEL + ":") and "names more than one box" in why
    # a label that names another element keeps the plain reason
    _new, why = g.strip_document_item_label(P1, "Item 4 Premium: $29,278", S130)
    assert "names more than one box" not in why


def test_review_a_reference_the_name_spells_picks_its_own_box_only():
    for box in STATE_BOXES_130:
        expect_strip = box.startswith("WorkersCompensation_PartOne_")
        got = g.strip_document_item_label(box, "Part One - State: CO", S130)
        assert (got == ("CO", None)) is expect_strip, box
        got = g.strip_document_item_label(box, "Part Three - State: CO", S130)
        assert (got == ("CO", None)) is box.startswith("WorkersCompensation_PartThree_"), box
    # Part 3's tooltip mentions Part 1 ("states not listed in Part 1"): only names count
    assert "Part 1" in S130["WorkersCompensation_PartThree_StateOrProvinceCode_A"]["tu"]
    assert g._box_reference_keys("WorkersCompensation_PartThree_StateOrProvinceCode_A") == {"part3"}
    # a reference no box's name spells narrows nothing
    assert g._reference_key("Item", "3.A.") == "item3a"
    assert g._reference_key("Section", "II") == "section2" and g._reference_key("Part", "One") == "part1"


def test_review_a_label_naming_one_element_on_its_form_strips():
    schema = {"Applicant_StateOrProvinceCode_A": {"ft": "/Tx", "tu": "Enter code: The applicant's state."},
              "Applicant_StateOrProvinceCode_B": {"ft": "/Tx", "tu": "Enter code: The applicant's state."},
              "Applicant_Remarks_A": {"ft": "/Tx", "tu": "Enter text: Remarks about the state."}}
    for row in ("A", "B"):        # rows are one element
        assert g.strip_document_item_label(f"Applicant_StateOrProvinceCode_{row}", "Item 3A State: CO",
                                           schema) == ("CO", None)
    assert g.strip_document_item_label(RATING, "Item 6 Rating Effective Date: 01/01/2026", S130) == \
        ("01/01/2026", None)
    assert g.strip_document_item_label(EL_ACCIDENT, "Item 3B Each Accident: $1,000,000", S130) == \
        ("$1,000,000", None)


def test_review_a_label_that_spells_the_whole_name_picks_it_out():
    """Closes the first cut's open end: "Name of Insured" no longer strips into
    the insured's inspection / accounting contact boxes."""
    v = "Item 1 Name of Insured: Choice Electric LLC"
    assert g.strip_document_item_label("NamedInsured_FullName_A", v, S130) == ("Choice Electric LLC", None)
    assert _refused(INSPECTION, v, S130) and _refused(ACCOUNTING, v, S130)


@pytest.mark.parametrize("schema,field,value", [
    # C23's shape: an umbrella's limit must never strip into the underlying GL
    # box (or the reverse) on a label that names both - "Each Occurrence"
    # spells the GL box's element only by how ACORD named it
    (S131, GL_OCC, "Item 3 Each Occurrence: $5,000,000"),
    (S131, UMB_OCC, "Item 3 Each Occurrence: $5,000,000"),
    (S131, GL_OCC, "Section II - Limits: $1,000,000"),           # six limits on the 131
    (S131, EL_ACCIDENT, "Item 3B Each Accident: $1,000,000"),    # the auto CSL is each accident too
    (_schema("ACORD_126"), GL_OCC, "Item 3 Each Occurrence: $1,000,000"),   # and damage to rented premises
    (S125_, "CommercialStructure_PhysicalAddress_LineOne_A", "Item 4 Address: 4800 Dahlia St"),
])
def test_review_ambiguous_limit_and_address_labels_are_refused(schema, field, value):
    assert _refused(field, value, schema), (field, value)


def test_review_stems_fold_ed_and_ing_the_same_on_both_sides():
    assert g._word_stems("Named Insured's") == g._word_stems("name insured") == {"nam", "insur"}
    assert g._word_stems("Rating") == g._word_stems("rate") == g._word_stems("rates")
    assert g._word_stems("States") == g._word_stems("stated") == g._word_stems("state")
    assert g._word_stems("addresses") == g._word_stems("address") == {"address"}
    assert g._word_stems("policies") == g._word_stems("policy")
    assert {g._label_stem(w) for w in ("code", "date", "name", "limit", "amount")} <= g._DATA_TYPE_STEMS
    assert g.strip_document_item_label("NamedInsured_FullName_A",
                                       "Item 1 Named Insured: Choice Electric LLC", S125) == \
        ("Choice Electric LLC", None)
    assert g.strip_document_item_label("NamedInsured_FullName_A",
                                       "Item 1 Named Insured: Choice Electric LLC", S130) == \
        ("Choice Electric LLC", None)


@pytest.mark.parametrize("value", ["Item 3B Each Accident: $1,000,000", "Item 4 Per Claim: $1,000,000",
                                   "Item 3 Each Occurrence: $5,000,000"])
def test_review_a_limit_label_opening_each_or_per_is_judged_not_left_with_its_prefix(value):
    """The first cut returned these untouched ("each" read as prose), so the box
    printed the prefix - the P15-4 defect itself."""
    for fid in ("ACORD_130", "ACORD_131"):
        s = _schema(fid)
        for box in s:
            if g._skip_box(box, s) or not box.endswith("Amount_A"):
                continue
            assert g.strip_document_item_label(box, value, s) is not None, (fid, box, value)


@pytest.mark.parametrize("value", ["Item 7 of the Declarations to include: CO",
                                   "Item 3 to be amended: CO", "Section 2 the following: CO"])
def test_review_prose_after_a_reference_is_still_untouched(value):
    assert g.strip_document_item_label(P1, value, S130) is None


def test_review_an_explanation_is_still_named_by_its_question_alone():
    """Two subcontractor explanations share the label word; an explanation's
    words carry their own meaning and the evidence gate judges them."""
    S126_ = _schema("ACORD_126")
    exp = "GeneralLiabilityLineOfBusiness_SubcontractorsCarryLowerLimitsExplanation_A"
    assert g.strip_document_item_label(
        exp, "Section 4 - Subcontractors: every subcontractor carries the same limits", S126_) == \
        ("every subcontractor carries the same limits", None)


@pytest.mark.parametrize("form_id", ALL_FORMS)
def test_review_no_label_strips_into_two_elements_of_one_form(form_id):
    """Over every real form: a generic label strips into at most ONE element."""
    s = _schema(form_id)
    for value in ("Item 3A State: CO", "Item 1 Name: Choice Electric LLC", "Section II - Limits: $1,000,000",
                  "Item 4 City: Denver", "Item 2 Effective Date: 01/01/2026", "Item 3 Each Occurrence: $1,000,000",
                  "Item 5 Premium: $2,991", "Item 1 Name of Insured: Choice Electric LLC"):
        stripped = set()
        for box in s:
            if g._skip_box(box, s) or g._is_narrative_box(box):
                continue
            got = g.strip_document_item_label(box, value, s)
            if got and got[0] is not None:
                stripped.add(g._ROW_RE.match(box).group("base") if g._ROW_RE.match(box) else box)
        assert len(stripped) <= 1, (form_id, value, sorted(stripped))


@pytest.mark.parametrize("form_id", ALL_FORMS)
def test_review_the_other_tick_and_dependent_readers_read_layout_order(form_id):
    """Finding 3: `_other_tick_partners` and `_unpaired_question_deps` were the
    two positional readers still reading raw dict order."""
    s = _schema(form_id)
    pairs = ps._question_explanation_pairs(s)
    for shuffled in (_jsonb(s), dict(reversed(list(s.items())))):
        assert ps._other_tick_partners(shuffled) == ps._other_tick_partners(s)
        for inc in (False, True):
            assert ps._unpaired_question_deps(shuffled, pairs, include_paired=inc) == \
                ps._unpaired_question_deps(s, pairs, include_paired=inc)
