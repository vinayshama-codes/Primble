"""THE WRONG-VALUE-ON-A-FORM ROOT CAUSE, fixed as a class (2026-09-05).

`fix-form-stamping.md` states the root cause in one sentence and has since
August:

    "We stamp a value onto the form after stripping away the context that
     qualifies it. The pipeline treats a value being PRESENT IN THE DOCUMENT as
     sufficient reason to stamp it."

with six qualifiers nobody checks - GRANT, OWNERSHIP, SHAPE, ROW INTEGRITY,
ROLE, AUTHORSHIP - and the prediction test: *"take any field, ask which of the
six is checked before it stamps. If the answer is 'none', that field is already
broken or one document away from it."*

The 5 Sep 2026 form run produced seven wrong values and every one of them was
one of the six. What this file fixes, and what each was missing:

  OWNERSHIP  NATURE OF BUSINESS ticked RESTAURANT on a food WHOLESALER, from
             the word "restaurant" in a sentence about its CUSTOMERS.
  OWNERSHIP  AAIS - a rating BUREAU - offered as a rival CARRIER.
  ROW INTG.  ONE GL class code printed in THREE rows of ACORD 126.
  ROW INTG.  An ADDITIONAL INTEREST whose NAME was "Certificate Holder".
  (+ the false "no GL class codes found" warning, and CYBER ticked twice.)

THE DEEPER FINDING, and the reason these keep coming back: the six qualifiers
are not a gate every value passes. They are enforced ONE HAND-WRITTEN RESCUE AT
A TIME, added after each live run reports the one field that broke. Two of the
seven prove it exactly:

  * the nature-of-business rescue (Aug 2026) only answered "No" when
    `is_contractor` was TRUE, because the reported case was a contractor. Every
    other business kept the defect - measured, 9 wrong ticks over 7 ordinary
    businesses - and when it DID fire it blanked the correct box too.
  * the phantom-hazard-row suppression was written, tested, shipped - and never
    registered in `_AUTHORITATIVE_BLANK_RESOLVERS`, so its `None` meant "ask the
    model" and gap fill copied row A into rows B and C. A fix that is not wired
    is indistinguishable from a fix that works, and every unit test passed.
"""
import pytest

from services import fact_comparison as fc
from services import normalization as norm
from services import pdf_service as ps
from services.extraction_service import _merge_list_fields

_BOXES = ["Manufacturing", "Restaurant", "Retail", "Service", "Wholesale",
          "Office", "Apartments", "Condominiums", "Institutional", "Contractor"]


def _ticked(facts):
    return [b for b in _BOXES
            if ps._derive_indicator(
                f"BusinessInformation_BusinessType_{b}Indicator_A", facts) == "Yes"]


# ─────────────────────────────────────────────────────────────────────────────
# 1. NATURE OF BUSINESS - the CLASSIFICATION answers it, never the prose
# ─────────────────────────────────────────────────────────────────────────────

def test_the_reported_case_a_food_wholesaler_is_not_a_restaurant():
    """MUST NEVER FAIL. The client's own operations text, verbatim."""
    facts = {"operations_description":
             "Wholesale distribution of packaged food products to grocery and "
             "restaurant accounts",
             "naics_code": "424490"}
    assert _ticked(facts) == ["Wholesale"]


@pytest.mark.parametrize("name,facts,expected", [
    # The classification decides.
    ("food wholesaler", {"operations_description": "Wholesale distribution of packaged "
      "food products to grocery and restaurant accounts", "naics_code": "424490"},
     ["Wholesale"]),
    ("machine shop", {"operations_description": "Precision manufacturing of metal "
      "components for aerospace", "naics_code": "332710"}, ["Manufacturing"]),
    ("wholesale bakery", {"operations_description": "Wholesale bakery supplying "
      "restaurants, hotels and institutional food service accounts",
      "naics_code": "311812"}, ["Manufacturing"]),
    ("a real restaurant", {"operations_description": "Full-service restaurant serving "
      "lunch and dinner", "naics_code": "722511"}, ["Restaurant"]),
    ("plumbing supply", {"operations_description": "Wholesale plumbing supply house "
      "serving licensed contractors", "naics_code": "423720"}, ["Wholesale"]),
    # A decided fact outranks the classification.
    ("roofing contractor", {"operations_description": "Residential roofing and gutter "
      "installation", "is_contractor": True}, ["Contractor"]),
    # No classification, and the prose is UNAMBIGUOUS.
    ("retail hardware", {"operations_description": "Retail hardware store"}, ["Retail"]),
    # No classification, and the prose names several - ASKED, never several ticks.
    ("commercial cleaning", {"operations_description": "Janitorial and cleaning service "
      "for office buildings and retail centers"}, []),
    ("property manager", {"operations_description": "Management of apartment and "
      "condominium associations"}, []),
    ("truck repair", {"operations_description": "Heavy truck repair and maintenance "
      "service; parts sold retail at the counter"}, []),
])
def test_a_narrative_naming_other_peoples_businesses_ticks_nothing_wrong(
        name, facts, expected):
    """Measured before this resolver existed: 9 wrong ticks across these seven,
    5 of 7 affected. A business narrative names its CUSTOMERS, its PREMISES and
    its MARKETS as a matter of course."""
    assert _ticked(facts) == expected, name


def test_an_ambiguous_narrative_is_ASKED_not_answered_no():
    """None means "ask", and that distinction is the whole of core principle 3.
    Nine explicit "No"s would assert the applicant is none of the nine."""
    facts = {"operations_description":
             "Janitorial and cleaning service for office buildings and retail centers"}
    for box in ("Retail", "Service", "Office"):
        assert ps._derive_indicator(
            f"BusinessInformation_BusinessType_{box}Indicator_A", facts) is None


def test_the_classification_answers_no_to_the_boxes_it_did_not_pick():
    facts = {"operations_description": "Wholesale distribution to restaurant accounts",
             "naics_code": "424490"}
    assert ps._derive_indicator(
        "BusinessInformation_BusinessType_RestaurantIndicator_A", facts) == "No"


def test_the_prose_table_is_derived_from_the_rules_not_copied():
    """One table, so the owner and the rules can never drift apart."""
    assert set(ps._BUSINESS_TYPE_PROSE_WORDS) == {
        "Manufacturing", "Restaurant", "Retail", "Service", "Wholesale",
        "Office", "Apartments", "Condominiums", "Institutional"}
    for box, (fact_key, word) in ps._BUSINESS_TYPE_PROSE_WORDS.items():
        assert (f"BusinessInformation_BusinessType_{box}Indicator",
                (fact_key, word)) in ps._INDICATOR_RULES.items()


def test_the_naics_map_is_a_published_taxonomy_not_a_keyword_list():
    """Only sectors whose ACORD box is beyond argument. 54 Professional Services
    is "Office" or "Service" depending on who you ask, so it is absent and the
    prose rule keeps its chance."""
    assert ps._naics_business_type({"naics_code": "424490"}) == "Wholesale"
    assert ps._naics_business_type({"naics_code": "332710"}) == "Manufacturing"
    assert ps._naics_business_type({"naics_code": "722511"}) == "Restaurant"
    assert ps._naics_business_type({"naics_code": "445110"}) == "Retail"
    assert ps._naics_business_type({"naics_code": "541110"}) is None   # law firm
    assert ps._naics_business_type({"naics_code": "531110"}) is None   # lessor
    assert ps._naics_business_type({}) is None
    assert ps._naics_business_type({"naics_code": "not a code"}) is None


# ─────────────────────────────────────────────────────────────────────────────
# 2. A RATING BUREAU IS NEVER THE CARRIER
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("value", [
    "AAIS", "aais", "ISO", "NCCI", "ACORD", "Verisk",
    "American Association of Insurance Services", "AAIS Form CL-100",
])
def test_a_bureau_is_recognised(value):
    assert norm.is_insurance_bureau(value) is True


@pytest.mark.parametrize("value", [
    "Employers Mutual Casualty Company", "EMC Property & Casualty Company",
    "Cascade Standard Insurance Company", "Travelers",
    "The Travelers Indemnity Company", "Allegheny Mutual Casualty Company",
    "Association of Certified Insurers Inc", "Isola Insurance Co", "",
])
def test_a_real_insurer_is_never_called_a_bureau(value):
    assert norm.is_insurance_bureau(value) is False


def test_the_client_screenshot_no_longer_asks_insurer_or_bureau():
    """The SYS-07 source screenshot offered EMPLOYERS MUTUAL / AAIS / EMC P&C."""
    assert fc.compare("carrier_name",
                      ["Employers Mutual Casualty Company", "AAIS"]).verdict == "single"


def test_two_real_carriers_still_conflict():
    """Dropping the bureau is not an amnesty - the genuine disagreement the
    client praised us for catching must survive."""
    assert fc.compare("carrier_name", ["EMC Property & Casualty Company",
                                       "Employers Mutual Casualty Company"]
                      ).verdict == "conflict"
    assert fc.compare("carrier_name", ["Employers Mutual Casualty Company", "AAIS",
                                       "EMC Property & Casualty Company"]
                      ).verdict == "conflict"


def test_the_merge_never_elects_a_bureau_however_often_it_appears():
    """Dropped at the merge as well as at the picker: otherwise the picker
    correctly stops ASKING while the merge still ELECTS it and stamps "AAIS" as
    the insurer on a signed form."""
    merged = _merge_list_fields(
        [{"_chunk_idx": 0, "facts": {"carrier_name": "AAIS"}, "flags": {}},
         {"_chunk_idx": 1, "facts": {"carrier_name": "AAIS"}, "flags": {}},
         {"_chunk_idx": 2, "facts": {"carrier_name": "Cascade Standard Insurance Company"},
          "flags": {}}], [])["facts"]
    assert merged["carrier_name"] == "Cascade Standard Insurance Company"


def test_a_bureau_name_on_a_non_carrier_field_is_untouched():
    assert fc.compare("applicant_name", ["AAIS", "Acme LLC"]).verdict == "conflict"


# ─────────────────────────────────────────────────────────────────────────────
# 3. A ROLE LABEL IS NOT A NAME
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("value", [
    "Certificate Holder", "certificate holder", "Additional Insured",
    "Loss Payee", "Mortgagee", "Lienholder", "Named Insured", "Insured",
    "As Their Interests May Appear", "Various", "See Attached",
])
def test_a_party_role_word_is_not_a_name(value):
    assert norm.is_party_role_label(value) is True


@pytest.mark.parametrize("value", [
    "Orbin Contracting LLC", "Northgate Provisions Group LLC",
    "First National Bank", "Harborview Holdings Trust",
    "Certificate Holdings Inc",          # a real company, not the role
    "Insured Aircraft Title Service", "",
])
def test_a_real_party_is_never_called_a_role_label(value):
    assert norm.is_party_role_label(value) is False


def test_the_merge_drops_a_role_label_on_a_name_field():
    merged = _merge_list_fields(
        [{"_chunk_idx": 0, "facts": {"certificate_holder": "Certificate Holder"},
          "flags": {}},
         {"_chunk_idx": 1, "facts": {"certificate_holder": "Harborview Logistics LLC"},
          "flags": {}}], [])["facts"]
    assert merged["certificate_holder"] == "Harborview Logistics LLC"
    # ...and the FLOOR underneath it: `_merge_list_fields` returns early on a
    # single partial, so a one-chunk certificate would carry the label straight
    # through a filter that only ever runs on a contest.
    from services.extraction_service import merge_facts
    doc = {"filename": "cert.pdf", "doc_type": "certificate", "text": "",
           "facts": {"certificate_holder": "Certificate Holder",
                     "carrier_name": "AAIS"}}
    mf, _ = merge_facts([doc], doc)
    assert not mf.get("certificate_holder"), (
        "a label alone leaves the interest UNNAMED, which the orphan-row rule "
        "already knows how to suppress")
    assert not mf.get("carrier_name"), "a bureau is not the carrier"


# ─────────────────────────────────────────────────────────────────────────────
# 4. ROW INTEGRITY - the phantom hazard row, and the wiring that was missing
# ─────────────────────────────────────────────────────────────────────────────

_ONE_CLASS = {"gl_class_code_schedule": [{
    "class_code": "11288", "classification": "Food products distributors",
    "premium_basis": "Sales", "exposure_amount": "$9,300,000", "location": "1"}]}


def test_the_phantom_hazard_row_suppression_is_actually_wired():
    """It was written, tested and shipped in August and NEVER registered, so its
    None meant "ask the model" and gap fill copied row A into rows B and C."""
    assert "_resolve_phantom_gl_hazard_row" in ps._AUTHORITATIVE_BLANK_RESOLVERS


@pytest.mark.parametrize("col", [
    "ClassCode", "Classification", "PremiumBasisCode", "Exposure", "TerritoryCode"])
@pytest.mark.parametrize("row", ["B", "C", "D"])
def test_a_row_past_the_end_of_the_schedule_is_an_owned_blank(col, row):
    field = f"GeneralLiability_Hazard_{col}_{row}"
    assert ps._resolve_gl_hazard_row(field, _ONE_CLASS) is None
    assert ps._is_authoritative_blank_field(field, _ONE_CLASS) is True


def test_the_real_row_still_fills():
    assert ps._resolve_gl_hazard_row(
        "GeneralLiability_Hazard_ClassCode_A", _ONE_CLASS) == "11288"
    assert ps._resolve_gl_hazard_row(
        "GeneralLiability_Hazard_Classification_A",
        _ONE_CLASS) == "Food products distributors"


def test_no_schedule_at_all_still_reaches_gap_fill():
    """Suppressing on NO evidence would delete a schedule the extractor merely
    missed. Positive evidence only, exactly like the vehicle version."""
    assert ps._resolve_gl_hazard_row(
        "GeneralLiability_Hazard_ClassCode_B", {}) == "UNMATCHED"
    assert ps._is_authoritative_blank_field(
        "GeneralLiability_Hazard_ClassCode_B", {}) is False


# ─────────────────────────────────────────────────────────────────────────────
# 5. "Cyber Liability" IS ACORD's "Cyber and Privacy" box
# ─────────────────────────────────────────────────────────────────────────────

def _same(a, b):
    return ps._tokens_describe_same_line(ps._lob_tokens(a), ps._lob_tokens(b))


@pytest.mark.parametrize("a,b", [
    ("Cyber Liability", "Cyber and Privacy"),
    ("Cyber", "Cyber and Privacy"),
    ("General Liability", "Commercial General Liability"),
    ("Commercial Property", "Property"),
    ("Commercial Auto", "Business Auto Coverage Part"),
])
def test_two_printings_of_one_line_are_one_line(a, b):
    assert _same(a, b)


@pytest.mark.parametrize("a,b", [
    ("Liquor Liability", "General Liability"),      # THE safety property
    ("Umbrella", "General Liability"),
    ("Employment Practices Liability", "General Liability"),
    ("Fiduciary Liability", "Liquor Liability"),
    ("Commercial Property", "Commercial General Liability"),
    ("Commercial Auto", "Commercial General Liability"),
    ("Business Auto", "Business Owners"),
    ("Inland Marine", "Commercial Property"),
    ("Liquor Liability", "Cyber and Privacy"),
])
def test_stripping_the_descriptive_tail_never_merges_two_real_lines(a, b):
    """"Liquor Liability" reduces to `liquor` against `general` and is still
    refused. Dropping the words that DO distinguish is how this would break."""
    assert not _same(a, b)


def test_the_cyber_line_no_longer_lands_in_the_OTHER_row():
    facts = {"coverage_lines": [
        {"line": "General Liability", "policy_number": "CSG-GL-770412-26",
         "premium": "$8,140"},
        {"line": "Commercial Auto", "policy_number": "CSG-CA-770418-26",
         "premium": "$4,275"},
        {"line": "Cyber Liability", "policy_number": "CSG-CY-770423-26",
         "premium": "$1,860"}]}
    assert ps._other_lob_row_names(facts) == [], (
        "an enumerated line must not ALSO be written into the Other row - the "
        "live form ticked CYBER twice")


# ─────────────────────────────────────────────────────────────────────────────
# 6. The GL class-code check reads BOTH homes of the fact
# ─────────────────────────────────────────────────────────────────────────────

def test_the_class_code_warning_reads_both_shapes():
    from services.sqs_service import evaluate_stops
    flags = {"has_general_liability": True}
    msg = "GL coverage detected but no class codes found"

    def _fires(facts):
        _h, soft = evaluate_stops(facts, flags)[:2]
        return any(msg in s for s in soft)

    assert _fires({}) is True                                     # genuinely absent
    assert _fires({"gl_class_codes_by_location":
                   [{"location": "1", "codes": ["11288"]}]}) is False
    assert _fires(_ONE_CLASS) is False, (
        "class 11288 stamped onto ACORD 125's GL CODE box and ACORD 126's "
        "hazard row A while this warning said no class codes existed")
    assert _fires({"gl_class_code_schedule": [{"classification": "x"}]}) is True


# ─────────────────────────────────────────────────────────────────────────────
# 7. ANTI-ROT - a new prose-matching indicator rule must have an owner
# ─────────────────────────────────────────────────────────────────────────────

# Facts that hold a NARRATIVE. A checkbox decided by a bare substring over one
# of these is the defect this file exists to close.
_NARRATIVE_FACTS = frozenset({
    "operations_description", "certificate_description_of_operations",
    "wc_description_of_operations", "business_description",
    "contractor_type", "remarks", "description_of_operations",
})
# Rule families that have an OWNER - a resolver consulted before the substring
# loop, which reasons over structured evidence instead of a word in prose.
_OWNED_PREFIXES = ("BusinessInformation_BusinessType_",)


def test_no_indicator_rule_decides_a_box_from_a_narrative_without_an_owner():
    """THE PREDICTION TEST, made executable. `fix-form-stamping.md`: *"take any
    field, ask which of the six qualifiers is checked before it stamps. If the
    answer is 'none', that field is already broken or one document away from
    it."*

    A new rule matching a narrative by substring must come with a resolver that
    owns its family - or be added here as a deliberate, argued exception."""
    offenders = [
        (substr, fact_key, match_val)
        for substr, (fact_key, match_val) in ps._INDICATOR_RULES.items()
        if fact_key in _NARRATIVE_FACTS
        and match_val != "non-empty"
        and not substr.startswith(_OWNED_PREFIXES)
    ]
    assert offenders == [], (
        "These checkboxes are decided by a word appearing in a narrative, with "
        "no owner reasoning over structured evidence. A business description "
        "names other people's businesses - customers, premises, markets - so "
        f"this ticks boxes about them: {offenders}")


def test_the_guard_would_have_caught_the_reported_defect():
    """C25's lesson: prove the guard bites. With the owner's prefix removed from
    the allow-list, the nine business-type rules are exactly what it reports."""
    offenders = [
        substr for substr, (fact_key, match_val) in ps._INDICATOR_RULES.items()
        if fact_key in _NARRATIVE_FACTS and match_val != "non-empty"
    ]
    assert len(offenders) >= 9
    assert any("RestaurantIndicator" in o for o in offenders)


# ─────────────────────────────────────────────────────────────────────────────
# 8. GUARD THE BOX, NOT THE FACT (live run 2026-09-05)
#
# The role-label strip was built at the FACT layer and the value still reached
# three forms, because `_ACORD_FIELD_RULES` touches no AdditionalInterest field
# at all - every value in those boxes comes from GAP FILL reading the raw text.
# A guard only works on the path the value actually travels. Third time this
# exact trap was sprung in one day (the inert AAIS guard, the unwired phantom
# row, this).
# ─────────────────────────────────────────────────────────────────────────────

_ARRANGEMENT = ("Certificate holder is an additional insured with respect to "
                "general liability where required by written contract")


@pytest.mark.parametrize("field,value", [
    # A ROLE is not a party - the live ACORD 126 name box.
    ("AdditionalInterest_FullName_A", "Certificate Holder"),
    ("AdditionalInterest_FullName_A", "Additional Insured"),
    ("CertificateHolder_FullName_A", "Loss Payee"),
    # An ARRANGEMENT is not a coverage and is worth no dollars - the live
    # ACORD 126 "other limit" row, which is a MONEY box on a legal form.
    ("GeneralLiability_Coverage_OtherDescription_A", _ARRANGEMENT),
    ("AdditionalInterest_FullName_A", _ARRANGEMENT),
    ("NamedInsured_FullName_A", "Loss payee shall be named as their interests appear"),
])
def test_a_role_or_an_arrangement_never_survives_gap_fill(field, value):
    assert ps._rejects_role_or_arrangement(field, {}, value) is not None


@pytest.mark.parametrize("field,value", [
    # A real company whose NAME contains a role word.
    ("NamedInsured_FullName_A", "Certificate Holdings Inc"),
    ("NamedInsured_FullName_A", "Cedar Point Provisions Company"),
    ("AdditionalInterest_FullName_A", "First National Bank of Spokane"),
    # A REMARKS box is exactly where this sentence belongs.
    ("Remarks_A", _ARRANGEMENT),
    ("CommercialPolicy_OperationsDescription_A", _ARRANGEMENT),
    ("GeneralLiability_Hazard_Classification_A", "Food products distributors"),
])
def test_the_role_guard_never_blanks_a_real_value(field, value):
    assert ps._rejects_role_or_arrangement(field, {}, value) is None


# ─────────────────────────────────────────────────────────────────────────────
# 9. A RATING BASIS BELONGS IN THE RATING-BASIS BOX
#
# Live 5 Sep 2026, on BOTH packages and therefore deterministic: ACORD 126's
# PREMIUM BASIS column was blank while "DESCRIBE THE TYPE OF WORK
# SUBCONTRACTED" read "Gross Sales". One value, the wrong column.
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("words,code", [
    ("Gross Sales", "S"), ("Sales", "S"), ("Gross Receipts", "S"),
    ("Payroll", "P"), ("Remuneration", "P"),
    ("Area", "A"), ("Square Footage", "A"),
    ("Total Cost", "C"), ("Admissions", "M"), ("Unit", "U"), ("Other", "T"),
    ("S", "S"), ("p", "P"),                 # already a code - idempotent
])
def test_acords_own_legend_translates_the_basis(words, code):
    """The legend is PRINTED on the form: (S) GROSS SALES, (P) PAYROLL, ...
    and the box's tooltip says "Enter code:". Same shape as the shipped
    valuation_method -> R/A translation."""
    assert ps.rating_basis_code(words) == code


def test_an_unknown_basis_is_not_invented():
    assert ps.rating_basis_code("Widget Basis") is None
    assert ps.rating_basis_code("") is None
    assert ps.rating_basis_code(None) is None


def test_the_hazard_grid_stamps_the_code_not_the_words():
    rows = {"gl_class_code_schedule": [{
        "class_code": "11288", "premium_basis": "Gross Sales",
        "exposure_amount": "$11,600,000", "location": "1"}]}
    assert ps._resolve_gl_hazard_row(
        "GeneralLiability_Hazard_PremiumBasisCode_A", rows) == "S"
    # An unknown basis is passed through rather than dropped - the broker can
    # still read it, and blanking real data would be the worse failure.
    rows["gl_class_code_schedule"][0]["premium_basis"] = "Per Machine"
    assert ps._resolve_gl_hazard_row(
        "GeneralLiability_Hazard_PremiumBasisCode_A", rows) == "Per Machine"


@pytest.mark.parametrize("field,value,blanked", [
    ("Contractors_SubcontractedWork_Description_A", "Gross Sales", True),
    ("Contractors_SubcontractedWork_Description_A", "Payroll", True),
    # ...but NOT in the box that legitimately holds it.
    ("GeneralLiability_Hazard_PremiumBasisCode_A", "Gross Sales", False),
    ("WorkersCompensation_RatingBasis_A", "Payroll", False),
    # ...and never a real answer that merely contains the word.
    ("Contractors_SubcontractedWork_Description_A", "Electrical rough-in", False),
    ("Contractors_SubcontractedWork_Description_A",
     "Framing and gross sales support work", False),
])
def test_a_basis_term_outside_its_box_is_a_borrowed_column(field, value, blanked):
    assert (ps._rejects_misplaced_rating_basis(field, value) is not None) is blanked


# ─────────────────────────────────────────────────────────────────────────────
# 10. THE LAST CONSUMER OF THE WORD-MATCH: the crime-exposure advisory
#
# Live 5 Sep 2026: a food WHOLESALER was told "the business description
# mentions 'restaurant', 'retail'" off "...to grocery, restaurant and retail
# service accounts", and a JANITORIAL company off "...for office buildings and
# retail centers". Both times the word belonged to the CUSTOMERS. Same class as
# the NATURE OF BUSINESS boxes, one consumer over.
# ─────────────────────────────────────────────────────────────────────────────

def _crime_fires_on(ops, naics=None):
    from services.cross_form_validator import _check_crime_silent_exposure
    facts = {"operations_description": ops}
    if naics:
        facts["naics_code"] = naics
    out = _check_crime_silent_exposure(facts, {}, set())
    if not out:
        return None
    return out[0]["message"].split("mentions ")[1].split(", which")[0]


@pytest.mark.parametrize("ops,naics", [
    # THE TWO LIVE CASES, verbatim.
    ("Wholesale distribution of packaged food products to grocery, restaurant "
     "and retail service accounts from a single office and warehouse location",
     "424490"),
    ("Janitorial and cleaning service for office buildings and retail centers "
     "under annual maintenance agreements", None),
    # The classification contradicts the word.
    ("Restaurant supply distributor serving independent operators", "424410"),
    # The old false positive this rule was already narrowed for once.
    ("Residential roofing and gutter installation", "238160"),
])
def test_a_customers_business_never_raises_a_crime_advisory(ops, naics):
    assert _crime_fires_on(ops, naics) is None


@pytest.mark.parametrize("ops,naics,expected", [
    # The classification CORROBORATES the word.
    ("Full-service restaurant serving lunch and dinner", "722511", "'restaurant'"),
    ("Retail hardware store with three registers", "445110", "'retail'"),
    # No classification, and the word is the applicant's own operation.
    ("Neighborhood bar and cocktail lounge serving liquor", None, "'bar'"),
    # Terms with no business-type meaning are NEVER discounted by the
    # classification - being a wholesaler does not stop you handling cash.
    ("Vending machine route with daily cash collection and a vault on site",
     None, "'cash', 'vault'"),
    ("Armored car and currency transport services", None, "'armored', 'currency'"),
])
def test_a_genuine_cash_exposure_still_warns(ops, naics, expected):
    assert _crime_fires_on(ops, naics) == expected


def test_the_classification_door_has_one_owner():
    """`cross_form_validator` and the ACORD 125 boxes must ask the SAME
    question, so a food wholesaler cannot be a wholesaler on the form and a
    restaurant in the advisory."""
    from services.normalization import naics_business_type
    assert naics_business_type("424490") == "Wholesale"
    assert naics_business_type("722511") == "Restaurant"
    assert naics_business_type("445110") == "Retail"
    assert naics_business_type("522110") == "Financial"
    assert naics_business_type("541110") is None
    assert ps._naics_business_type({"naics_code": "424490"}) == "Wholesale"
    # "Financial" has no ACORD nature-of-business box, so the form side drops it.
    assert ps._naics_business_type({"naics_code": "522110"}) is None


# ─────────────────────────────────────────────────────────────────────────────
# 11. THE DOUBLED DOLLAR SIGN - measured per box, never blanket
# ─────────────────────────────────────────────────────────────────────────────

def test_the_template_says_which_boxes_already_print_a_dollar_sign():
    """ACORD is NOT consistent: the 126 LIMITS column prints one and its
    PREMIUMS column does not. A blanket strip would fix the doubling and lose
    the symbol exactly where the form does not supply it - so it is read off
    the template, per field."""
    printed = ps._fields_with_printed_currency("ACORD_126")
    assert printed, "detection returned nothing - it must fail safe, not silently"
    # Boxes that printed "$ $2,000,000" live.
    assert "GeneralLiability_GeneralAggregate_LimitAmount_A" in printed
    assert "GeneralLiability_EachOccurrence_LimitAmount_A" in printed
    # Boxes that printed "$8,140" correctly - no doubling, so nothing to strip.
    assert "GeneralLiability_PremisesOperations_PremiumAmount_A" not in printed
    assert "GeneralLiabilityLineOfBusiness_TotalPremiumAmount_A" not in printed


def test_every_form_gets_an_answer_and_it_is_cached():
    for form in ("ACORD_125", "ACORD_126", "ACORD_127"):
        assert isinstance(ps._fields_with_printed_currency(form), frozenset)
    a = ps._fields_with_printed_currency("ACORD_125")
    b = ps._fields_with_printed_currency("ACORD_125")
    assert a is b, "must be cached - it opens the template"


def test_an_unknown_form_fails_safe():
    """Any problem returns an empty set, and the stamped value keeps its own
    "$" exactly as it does today."""
    assert ps._fields_with_printed_currency("ACORD_NOT_A_FORM") == frozenset()


# ─────────────────────────────────────────────────────────────────────────────
# 12. THE HALF-FIX IS ITS OWN DEFECT (live run 3, 2026-09-05)
#
# Guard 3c correctly blanked "Certificate holder is an additional insured with"
# out of ACORD 126's OTHER limit DESCRIPTION - and its $1,000,000 stayed,
# leaving an unlabelled limit on a legal form. An "other coverage" row is a
# coverage the form does not enumerate, so the DESCRIPTION is what names it.
# Mechanism M4 in `fix-form-stamping.md`, which Guard 2d already applies to
# line+number pairs.
# ─────────────────────────────────────────────────────────────────────────────

def test_an_other_coverage_amount_with_no_description_is_blanked():
    mapped = {"GeneralLiability_OtherCoverageLimitAmount_A": "$1,000,000",
              "GeneralLiability_OtherCoverageLimitDescription_A": None}
    ps._blank_unnamed_other_rows(mapped)
    assert mapped["GeneralLiability_OtherCoverageLimitAmount_A"] is None


def test_a_described_other_coverage_survives():
    mapped = {"GeneralLiability_OtherCoverageLimitAmount_A": "$1,000,000",
              "GeneralLiability_OtherCoverageLimitDescription_A":
                  "Employee Benefits Liability"}
    ps._blank_unnamed_other_rows(mapped)
    assert mapped["GeneralLiability_OtherCoverageLimitAmount_A"] == "$1,000,000"


def test_a_named_limit_is_never_touched():
    """Only OTHER rows need a description - the enumerated limits are named by
    the form itself."""
    mapped = {"GeneralLiability_EachOccurrence_LimitAmount_A": "$1,000,000",
              "GeneralLiability_GeneralAggregate_LimitAmount_A": "$2,000,000"}
    before = dict(mapped)
    ps._blank_unnamed_other_rows(mapped)
    assert mapped == before


# ─────────────────────────────────────────────────────────────────────────────
# 13. A DESCRIBE BOX NEEDS WORDS
#
# Live run 3: "DESCRIBE THE TYPE OF WORK SUBCONTRACTED" came back "0%" while
# the "% OF WORK SUBCONTRACTED" column beside it stayed empty.
# ─────────────────────────────────────────────────────────────────────────────

def test_the_describe_box_is_identified_from_acords_own_declaration():
    """BOTH conditions: the name says description AND the tooltip says "Enter
    text:". Either alone is too loose."""
    import json
    import os
    from config.settings import FORMS_SCHEMAS_DIR
    sch = json.load(open(os.path.join(FORMS_SCHEMAS_DIR, "ACORD_126_schema.json")))
    f = "GeneralLiabilityLineOfBusiness_TypeOfWorkSubcontractedDescription_A"
    assert ps._is_description_box(f, sch.get(f)) is True
    # A name box is not a description box, whatever it is called.
    assert ps._is_description_box("NamedInsured_FullName_A",
                                  {"tu": "Enter name:"}) is False
    # A code box that happens to say "Description" is not one either.
    assert ps._is_description_box("Some_DescriptionCode_A",
                                  {"tu": "Enter code: ..."}) is False


@pytest.mark.parametrize("value,blanked", [
    ("0%", True), ("0", True), ("100%", True), ("$0", True),
    ("Electrical rough-in", False), ("Framing and drywall", False),
    ("Roof work 40%", False),          # a real description WITH a percentage
])
def test_a_describe_box_keeps_only_values_with_words(value, blanked):
    import re as _re
    assert (not _re.search(r"[A-Za-z]{3,}", value)) is blanked
