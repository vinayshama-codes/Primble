"""The FR125 kit, the meaning-aware scorer and the key-free rules audit (28 Sep).

Three tools that grade the product, so every one of them is tested in BOTH
directions: it must pass what is right AND fail what is wrong. A grader that
only passes is a grader that cannot see.
"""
from __future__ import annotations

import fnmatch
import importlib.util
import json
import sys
from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parents[1]
SCRIPTS = BACKEND / "scripts"
sys.path.insert(0, str(SCRIPTS))


def _load(name):
    spec = importlib.util.spec_from_file_location(f"_t_{name}", str(SCRIPTS / f"{name}.py"))
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


@pytest.fixture(scope="module")
def sff():
    return _load("score_form_fill")


@pytest.fixture(scope="module")
def kit():
    g = _load("make_fr125_test_pdf")
    schema, defaulted = g.build_key()
    return g, g.assemble(schema), schema, defaulted


@pytest.fixture(scope="module")
def audit():
    return _load("audit_125_rules")


# ═════════════════════════════════════════════════════════════════════════════
# The scorer - exact tier
# ═════════════════════════════════════════════════════════════════════════════
@pytest.mark.parametrize("expected,actual", [
    ("$73,410", "$734,100"), ("1711", "17110"), ("238210", "2382101"),
    ("3456789", "12-3456789"), ("5,000", "15,000"), ("10/01/2025", "10/01/2026"),
    ("8000 Commerce Way", "18000 Commerce Way"),
    ("8000 Commerce Way", "8000 Commerce Way, Denver CO 80216"),
])
def test_a_different_number_is_a_different_value(sff, expected, actual):
    """The old rule accepted any 4-character SUBSTRING, so every one of these
    scored correct - including the kit's own FEIN flagged as the USDOT."""
    assert sff.same(expected, actual) is False
    assert sff.same(actual, expected) is False


@pytest.mark.parametrize("expected,actual", [
    ("12-3456789", "123456789"), ("303-555-0175", "(303) 555-0175"),
    ("06/15/2014", "2014-06-15"), ("06/15/2014", "June 15, 2014"),
    ("Front Range Electrical Contractors LLC", "FRONT RANGE ELECTRICAL CONTRACTORS, LLC"),
    ("Timberline Mutual Insurance Company", "Timberline Mutual"),
    ("Suite 310", "Ste 310"), ("$4,850", "$4,850.00"), ("100%", "100"),
    ("5,000", "5000 sq ft"), ("1", "001"), ("Y", "X"),
])
def test_formatting_is_not_a_difference(sff, expected, actual):
    assert sff.same(expected, actual) is True


# ═════════════════════════════════════════════════════════════════════════════
# The scorer - code tier, read from ACORD's own tooltip
# ═════════════════════════════════════════════════════════════════════════════
def test_a_code_and_its_word_are_the_same_answer(sff):
    f = "Policy_Payment_PaymentScheduleCode_A"
    assert sff.match("AN", "Annual", "exact", "ACORD_125", f)[0] == "code"
    assert sff.match("AN", "Monthly", "exact", "ACORD_125", f)[0] == "no"
    table = sff.tooltip_codes("ACORD_125", "Policy_Audit_FrequencyCode_A")
    assert table == {"a": "annual", "s": "semi-annual", "q": "quarterly",
                     "m": "monthly", "o": "other"}


def test_a_code_letter_is_never_read_as_an_address_word(sff):
    """`norm` expands address abbreviations: "S" became "south" and "N"
    "north". The code tier must compare codes literally."""
    f = "Policy_Audit_FrequencyCode_A"
    assert sff.match("S", "Semi-Annual", "exact", "ACORD_125", f)[0] == "code"
    assert sff.match("S", "Annual", "exact", "ACORD_125", f)[0] == "no"


def test_a_box_without_an_enumerated_tooltip_has_no_code_tier(sff):
    assert sff.tooltip_codes("ACORD_125", "NamedInsured_FullName_A") == {}
    assert sff.tooltip_codes("ACORD_125", "PriorCoverage_OtherLine_LineOfBusinessCode_A") == {}


# ═════════════════════════════════════════════════════════════════════════════
# The scorer - meaning tier
# ═════════════════════════════════════════════════════════════════════════════
_OPS = ("Licensed electrical contractor performing commercial and residential "
        "electrical installation, repair and service. Work includes new wiring, "
        "service upgrades, panel replacement, lighting and electrical "
        "troubleshooting. No utility-line construction or electrical generation "
        "operations.")
_PREM = ("Administrative office, electrical contracting warehouse and material "
         "storage. Crews perform commercial and residential electrical installation, "
         "wiring, panel upgrades, troubleshooting and service work at customer "
         "locations.")
_HAZ = ("Limited quantities of common jobsite adhesives and solvents stored in "
        "approved containers.")


@pytest.mark.parametrize("expected,actual,verdict", [
    (_HAZ, "Applicant stores limited quantities of common jobsite adhesives/solvents "
           "in approved containers.", "meaning"),
    (_OPS, "Licensed electrical contractor providing commercial and residential "
           "electrical installation, repair and service, including new wiring, "
           "service upgrades, panel replacement, lighting and troubleshooting. Does "
           "not perform utility-line construction or electrical generation.", "meaning"),
    ("Insured vehicle rear-ended third party at traffic light",
     "Insured's vehicle rear-ended a third party vehicle at a traffic light.", "meaning"),
    (_OPS, "Licensed electrical contractor doing commercial and residential "
           "electrical installation, repair and service work.", "partial"),
    # ── what a paraphrase test must NOT accept ──
    (_HAZ, "No adhesives or solvents are stored; no approved containers.", "no"),
    (_HAZ, "Stores 500 gallons of adhesives and solvents in approved containers.", "no"),
    (_OPS, "Licensed electrical contractor performing commercial and residential "
           "electrical installation, repair and service, new wiring, service "
           "upgrades, panel replacement, lighting, troubleshooting, utility-line "
           "construction and electrical generation operations.", "no"),
    (_HAZ, _HAZ + " " + _PREM + " " + _OPS, "no"),
    (_OPS, _PREM, "no"),
    (_PREM, _OPS, "no"),
    (_HAZ, "Any exposure to flammables, explosives, chemicals?", "no"),
])
def test_meaning_tier(sff, expected, actual, verdict):
    assert sff.meaning(expected, actual)[0] == verdict


def test_meaning_is_only_ever_used_on_narrative_boxes(sff):
    """A paraphrase scores on a field the key marks semantic and NOT on any
    other - a model rewrites a sentence, it does not rewrite a FEIN."""
    para = "Applicant stores limited quantities of common jobsite adhesives/solvents " \
           "in approved containers."
    key = {"expect": {"ACORD_125": {"X_Explanation_A": _HAZ, "Y_Name_A": _HAZ}},
           "must_be_blank": {"ACORD_125": []},
           "match_modes": {"ACORD_125": {"semantic": ["X_Explanation_A"]}}}
    res = sff.score_form("ACORD_125", key, {"X_Explanation_A": para, "Y_Name_A": para},
                         lambda f: None)
    assert res["tally"]["correct_meaning"] == 1
    assert res["tally"]["wrong"] == 1


# ═════════════════════════════════════════════════════════════════════════════
# The kit
# ═════════════════════════════════════════════════════════════════════════════
def test_the_key_decides_every_field_and_invents_none(kit):
    _g, key, schema, defaulted = kit
    assert set(key["fields"]) == set(schema)
    # only the Additional Interest block defaults - everything else was decided
    assert {f.split("_")[0] for f in defaulted} <= {"AdditionalInterest"}


def test_every_decoy_scope_reaches_a_real_box(kit):
    _g, key, schema, _d = kit
    for scope in key["forbidden"]["ACORD_125"]:
        assert any(fnmatch.fnmatch(f, scope) for f in schema), scope
    for scope in key["expected_absent"]["ACORD_125"]["scope"]:
        assert any(fnmatch.fnmatch(f, scope) for f in schema), scope


def test_the_key_is_consistent_with_its_own_scorer(kit):
    g, key, _s, _d = kit
    assert g._self_consistency(key) == []


def test_the_client_rules_are_in_the_key(kit):
    """Version 2 fills the form like the client's data map WITHOUT bending a
    client rule: the documents verify more, nothing is inferred."""
    _g, key, _s, _d = kit
    f = key["fields"]
    assert f["Insurer_FullName_A"]["value"] == "Granite Arch Casualty Company"
    assert f["Insurer_NAICCode_A"]["value"] == "21334"            # verified on its letter
    assert f["Policy_PolicyNumberIdentifier_A"]["verdict"] == "blank_no_data"   # a quote
    assert f["Policy_Status_QuoteIndicator_A"]["value"] == "Y"
    assert f["Policy_Payment_EstimatedTotalAmount_A"]["verdict"] == "blank_by_rule"
    assert [f[f"PriorCoverage_PolicyYear_{r}"]["value"] for r in "ABC"] == ["2025", "2024", "2023"]
    assert f["PriorCoverage_OtherLine_LineOfBusinessCode_A"]["verdict"] == "not_scored"
    assert f["LossHistory_TotalAmount_A"]["value"] == "$23,550"      # PAID, not incurred
    assert f["CommercialPolicy_Question_KAACode_A"]["value"] == "Y"
    assert f["CommercialPolicy_Question_KAOCode_A"]["source"] == "scanned"
    assert f["NamedInsured_LegalEntity_MemberManagerCount_A"]["source"] == "scanned"
    # a resolution that has not happened is not one
    assert f["CommercialPolicy_UncorrectedFireCodeViolation_ResolutionDescription_A"][
        "verdict"] == "blank_by_rule"


def test_version_2_fills_the_form_like_the_data_map(kit):
    """The owner's ask (28 Sep): the form filled nearly everywhere a document
    can support a value - version 1 expected 106 of 548."""
    _g, key, _s, _d = kit
    assert len(key["expect"]["ACORD_125"]) >= 300


def test_expected_facts_name_real_extraction_facts(kit):
    """A misnamed fact would grade as "extraction missed it"."""
    _g, key, _s, _d = kit
    src = (BACKEND / "services" / "extraction_service.py").read_text(encoding="utf-8")
    ef = key["expected_facts"]
    for name in list(ef["_scalars"]) + list(ef["_lists"]) + ef["_must_be_empty"]:
        assert f'"{name}"' in src, name


# ═════════════════════════════════════════════════════════════════════════════
# The rules audit - no key
# ═════════════════════════════════════════════════════════════════════════════
@pytest.fixture(scope="module")
def world(kit):
    """A perfect Front Range form, and the sentences the rules read."""
    g, key, _s, _d = kit
    import _fr125_data as D
    perfect = dict(key["expect"]["ACORD_125"])
    raw = "\n".join([
        f"TO: {D.CARRIER}  ATTN: {D.UNDERWRITER}, {D.UNDERWRITER_OFFICE}",
        f"{D.CARRIER}   NAIC {D.CARRIER_NAIC}",
        "",
        f"Company: {D.CUR_CARRIER}   NAIC {D.CUR_CARRIER_NAIC}",
        "SCHEDULE OF NAMED INSUREDS",
        D.NAME, *[o["name"] for o in D.OTHER_INSUREDS],
        "",
        f"Lender (mortgagee): {D.MORTGAGEE['name']}",
        f"Lessor and loss payee: {D.LOSS_PAYEE_B}",
        f"Landlord: {D.LANDLORD}",
        "The lease requires the tenant to carry liability insurance. It does not",
        "require the landlord to be named as an additional insured, loss payee or",
        "any other interest.",
        f"{D.CERT_HOLDERS[0][0]}  {D.CERT_HOLDERS[0][1]}",
        "Certificates are evidence of insurance only. No holder is an additional "
        "insured, loss payee, mortgagee or any other interest.",
        "\n".join(str(v) for v in perfect.values()),
        "\n".join(q["stated"] for q in D.QUESTIONS.values()),
    ])
    facts = {"disclosure_answers": [
        {"topic": g._TOPIC[c], "answer": q["answer"], "evidence_quote": q["stated"]}
        for c, q in D.QUESTIONS.items()]}
    return perfect, raw, facts, D


def _fails(audit, stamped, raw, facts, fates=None):
    return [r["id"] for r in audit.audit(stamped, facts, raw, fates or {})
            if r["status"] == "FAIL"]


def test_a_perfect_form_fails_no_rule(audit, world):
    perfect, raw, facts, _D = world
    res = audit.audit(perfect, facts, raw, {})
    assert [r["id"] for r in res if r["status"] in ("FAIL", "REVIEW")] == []


def _plants(D):
    return [
        ({"Insurer_FullName_A": D.CUR_CARRIER}, "C2"),
        ({"Insurer_NAICCode_A": D.CUR_CARRIER_NAIC}, "C3"),
        ({"Policy_PolicyNumberIdentifier_A": "GL-123456"}, "C4"),
        ({"GeneralLiabilityLineOfBusiness_TotalPremiumAmount_A": "$18,450"}, "C5"),
        ({"Policy_EffectiveDate_A": D.CUR_EFF}, "C6"),
        ({"PriorCoverage_GeneralLiability_PolicyNumberIdentifier_B": "GL-099871"}, "C7"),
        ({"LossHistory_NoPriorLossesIndicator_A": "Y"}, "C8"),
        ({"LossHistory_PaidAmount_A": "$3,200", "LossHistory_ReservedAmount_A": "$1,650"}, "C9"),
        ({"Policy_Status_RenewIndicator_A": "Y"}, "C1"),
        ({"CommercialPolicy_AnyExposureToFlammableExplosivesChemicalsExplanation_A": ""}, "C11"),
        ({"CommercialPolicy_PastFiveYearsAnyApplicantIndictedOrConvictedFraudBriberyArsonExplanation_A":
          "A member was convicted of arson."}, "C12"),
        ({"NamedInsured_FullName_B": D.LANDLORD}, "C13"),
        ({"NamedInsured_FullName_B": D.CERT_HOLDERS[0][0]}, "C13"),
        ({"AdditionalInterest_FullName_A": D.LANDLORD}, "C14"),
        ({"AdditionalInterest_FullName_A": D.CERT_HOLDERS[0][0]}, "C14"),
        ({"CommercialPolicy_Question_KANCode_A": "N"}, "C16"),
        ({"NamedInsured_MailingAddress_LineTwo_A": "--"}, "S1"),
        ({"NamedInsured_Signature_A": "Michelle Smith"}, "S2"),
        ({"NamedInsured_TaxIdentifier_A": D.USDOT}, "S3"),
        ({"LossHistory_OccurrenceDescription_B": "Water damage to warehouse from a burst pipe"}, "S4"),
        ({"LossHistory_OccurrenceDate_C": D.LOSS["occurrence"],
          "LossHistory_OccurrenceDescription_C": D.LOSS["desc"]}, "S5"),
        ({"BuildingOccupancy_OccupiedArea_A": "15,000", "Construction_BuildingArea_A": "5,000"}, "S6"),
    ]


def test_every_planted_defect_is_caught_without_a_key(audit, world):
    perfect, raw, facts, D = world
    missed = []
    for delta, rule_id in _plants(D):
        st = dict(perfect)
        st.update(delta)
        if rule_id not in _fails(audit, st, raw, facts):
            missed.append((rule_id, delta))
    assert missed == []


def test_a_negated_role_is_not_a_role(audit, world):
    """The lease and the certificate log both say "no holder is an additional
    insured" - every role word within reach of every name, meaning the
    opposite. Written wrapped over two lines on purpose."""
    perfect, raw, facts, D = world
    st = dict(perfect)
    st["AdditionalInterest_FullName_A"] = D.LANDLORD
    assert "C14" in _fails(audit, st, raw, facts)
    genuine = raw + "\nINTEREST 1\nName Summit Equipment Finance LLC\nType of interest Loss Payee\n"
    st["AdditionalInterest_FullName_A"] = "Summit Equipment Finance LLC"
    assert "C14" not in _fails(audit, st, genuine, facts)


def test_a_rule_the_package_never_triggers_is_not_a_pass(audit, world):
    perfect, raw, _facts, _D = world
    sparse = {k: v for k, v in perfect.items()
              if not (k.startswith("NamedInsured_FullName_") and not k.endswith("_A"))
              and not k.startswith("AdditionalInterest_FullName_")}
    res = {r["id"]: r["status"] for r in audit.audit(sparse, {}, raw, {})}
    assert res["C16"] == "NOT EXERCISED"          # no facts, so it cannot judge
    assert res["C13"] == "NOT EXERCISED"          # rows B and C are empty
    assert res["C14"] == "NOT EXERCISED"          # no interest named


def test_a_silent_topic_answered_by_the_ai_is_a_review_not_a_verdict(audit, world):
    """The gap fill's evidence gate may hold a quote the dump does not carry,
    so an AI answer with no extracted statement is flagged for a human; the
    same answer from a DETERMINISTIC pass had no evidence at all."""
    perfect, raw, facts, _D = world
    f2 = {"disclosure_answers": [r for r in facts["disclosure_answers"]
                                 if r["topic"] != "foreign_operations"]}
    box = "CommercialPolicy_Question_KACCode_A"
    by = {r["id"]: r["status"] for r in audit.audit(perfect, f2, raw, {box: "call2"})}
    assert by["C16"] == "REVIEW"
    by = {r["id"]: r["status"] for r in audit.audit(perfect, f2, raw, {box: "pass1"})}
    assert by["C16"] == "FAIL"


def test_the_audit_reads_the_products_own_question_blocks(audit):
    """It must never disagree with the stamper about which boxes a question owns."""
    src = (SCRIPTS / "audit_125_rules.py").read_text(encoding="utf-8")
    for door in ("_NONADJACENT_DEPENDENT_FIELDS", "_question_dependent_block",
                 "_question_explanation_pairs", "_disclosure_field_map",
                 "_LOSS_OVERFLOW_MARKER", "is_placeholder_text"):
        assert door in src, door


@pytest.mark.parametrize("facts,status", [
    # the cover letter's REQUESTED line carries the receiving carrier and no
    # number - it is not an existing policy
    ({"coverage_lines": [{"line": "GL", "carrier": "Granite Arch Casualty Company"}]},
     "NOT EXERCISED"),
    ({"coverage_lines": [{"line": "GL", "carrier": "Granite Arch Casualty Company",
                          "policy_number": "GL-1"}]}, "FAIL"),
    # a one-carrier renewal legitimately prints the incumbent on page one
    ({"coverage_lines": [{"line": "GL", "carrier": "Granite Arch Casualty Company",
                          "policy_number": "GL-1"}], "is_renewal": True}, "REVIEW"),
])
def test_page_one_carrier_rule_knows_a_requested_line_and_a_renewal(audit, facts, status):
    st = {"Insurer_FullName_A": "Granite Arch Casualty Company",
          "Policy_Status_QuoteIndicator_A": "Y"}
    res = {r["id"]: r["status"] for r in audit.audit(st, facts, "Granite Arch", {})}
    assert res["C2"] == status


def test_a_dump_is_graded_as_the_pdf_prints_it(sff):
    """A dump stores an unticked checkbox as "No"; the PDF prints it EMPTY.
    Grading the raw dump counted 26 unticked boxes as made-up values on the
    Front Range run (28 Sep). Text boxes pass through untouched."""
    got = sff.as_printed("ACORD_125", {
        "Policy_Status_QuoteIndicator_A": "No",
        "Policy_Status_RenewIndicator_A": "Yes",
        "NamedInsured_LegalEntity_LimitedLiabilityCorporationIndicator_A": "1",
        "CommercialPolicy_Question_AAHCode_A": "N",          # a TEXT Y/N box
        "NamedInsured_FullName_A": None})
    assert got == {"Policy_Status_QuoteIndicator_A": "",
                   "Policy_Status_RenewIndicator_A": "Y",
                   "NamedInsured_LegalEntity_LimitedLiabilityCorporationIndicator_A": "Y",
                   "CommercialPolicy_Question_AAHCode_A": "N",
                   "NamedInsured_FullName_A": ""}


def test_a_parenthetical_qualifier_does_not_change_the_code(sff):
    f = "Policy_Payment_PaymentScheduleCode_A"
    assert sff.match("AN", "Annual (paid in full)", "exact", "ACORD_125", f)[0] == "code"
    assert sff.match("AN", "Monthly (installments)", "exact", "ACORD_125", f)[0] == "no"


def test_grounding_is_local_not_anywhere(audit):
    """In a 500,000-character package every common word is printed SOMEWHERE,
    so "each word exists" grounded an invented loss description (28 Sep). The
    words must stand together; a faithful paraphrase still passes."""
    raw = ("Customer ceiling damaged by water from a nicked sprinkler pipe during rough-in.\n"
           + "Clause text about coverage territory and premium audit.\n" * 120
           + "The warehouse stores wire and conduit. A burst of calls came in March.\n"
           + "Clause text about coverage territory and premium audit.\n" * 120
           + "A mechanics lien was recorded against the applicant on 08/14/2023. "
             "The lien was released on 02/27/2024 following settlement.\n")
    hay = audit.Hay(raw)
    assert hay.grounded("Water damage to warehouse from a burst pipe", narrative=True)[0] is False
    assert hay.grounded("A mechanics lien was recorded and later released following "
                        "settlement.", narrative=True)[0] is True


def test_a_name_given_another_role_on_its_own_line_is_that_role(audit):
    raw = ("SCHEDULE OF NAMED INSUREDS\nAlpha Electric LLC\nBeta Service LLC\n"
           "Landlord: Gamma Partners LP\n")
    assert audit._stated_in_role(raw, "Beta Service LLC", audit._INSURED_ROLE) is True
    assert audit._stated_in_role(raw, "Gamma Partners LP", audit._INSURED_ROLE) is False
