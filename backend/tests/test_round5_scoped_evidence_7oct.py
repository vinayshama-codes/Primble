"""Round 5 (7 Oct 2026) - an AI value belongs to the policy its box describes.

`services/scoped_evidence.py`, three rules (PROBLEMS.md classes 10-12, the owner's
live Choice Electric run, session b248c194):

  (a) per-policy evidence: an AI value in a policy box must be printed by a
      document that can speak for that policy (its line's, a no-line document,
      a multi-line package covering it; on one umbrella LAYER, that layer's own);
  (b) section presence: an AI value in an optional-coverage SECTION (derived from
      the schemas' field names) needs the documents to name the coverage, and not
      only as excluded / not covered - and the shared gap fill never asks it;
  (c) the 131's underlying OTHER rows come from the umbrella's own schedule of
      underlying insurance.

The end-to-end tests replay the redacted Choice Electric declarations
(`tests/fixtures/choice_electric_pol_6oct.json`) through the real merge and
`form_service.process_single_form`, with the live run's AI answers injected as
the shared gap fill's answers. The rest are unit tests on synthetic text.
"""
import copy
import json
import logging
from pathlib import Path

import pytest

from services import extraction_service as es
from services import form_instances as fi
from services import form_service as fs
from services import needs_attention as na
from services import pdf_service as pdf
from services import scoped_evidence as se

BACKEND = Path(__file__).resolve().parent.parent
_FIXTURE = BACKEND / "tests" / "fixtures" / "choice_electric_pol_6oct.json"
EXCESS = "ACORD_131__excess"
EXCESS_DOC = "25-26 Excess Umbrella Policy.pdf"
UMBRELLA_DOC = "25-26 Umbrella Policy.pdf"


def _schema(form_id):
    return json.loads((BACKEND / "forms_schemas" / f"{form_id}_schema.json").read_text())


# ═════════════════════════════════════════════════════════════════════════════
# The Choice Electric package, merged by the real engine
# ═════════════════════════════════════════════════════════════════════════════
@pytest.fixture(scope="module")
def package():
    docs = copy.deepcopy(json.load(open(_FIXTURE))["docs"])
    mf, flags = es.merge_facts(docs, es.select_primary_truth(docs))
    return {"facts": mf, "flags": flags, "docs": docs,
            "all_forms": fs.filter_available_forms(fs.load_all_forms()),
            "selected_form_ids": ["ACORD_125", "ACORD_131", EXCESS, "ACORD_140", "ACORD_137_CO"]}


def _stamp(package, form_id, answers):
    meta = fi.form_meta_for(package["all_forms"], form_id, package["facts"])
    pre = {"filled_values": dict(answers), "raw_text_fields": set(), "question_grounding": {}}
    return fs.process_single_form(meta, package, pre)


def _guard_reasons(result):
    return {g["field"]: g.get("reason") for g in result.get("guard_blanks") or []
            if isinstance(g, dict)}


# The live run's AI answers (session b248c194, PROBLEMS.md 10 / 11).
_EXCESS_AI = {
    "ExcessUmbrella_Umbrella_DeductibleOrRetentionAmount_A": "10,000",
    "ExcessUmbrella_EmployeeBenefits_ProgramName_A": "Employee Benefit Liability Coverage Part",
}
_140_SECTION_AI = {
    "CommercialProperty_Spoilage_LimitAmount_A": "798,556",
    "CommercialProperty_Spoilage_LimitAmount_B": "73,008",
    "CommercialProperty_Spoilage_DeductibleAmount_A": "500",
    "CommercialProperty_Spoilage_DeductibleAmount_B": "5,000",
    "CommercialProperty_Spoilage_PropertyDescription_A": "Building",
    "CommercialProperty_Summary_BlanketLimitAmount_A": "$798,556",
    "CommercialProperty_Summary_BlanketLimitAmount_B": "$73,008",
    "CommercialProperty_Summary_BlanketLimitAmount_C": "$421,714",
    "CommercialProperty_Summary_BlanketLimitAmount_D": "$73,008",
}


def test_the_excess_copy_never_prints_another_policys_retention(package):
    """PROBLEMS.md 10: $10,000 is printed only by the cyber and EPLI
    declarations; the excess states no retention."""
    res = _stamp(package, EXCESS, _EXCESS_AI)
    m = res["mapped"]
    assert not m.get("ExcessUmbrella_Umbrella_DeductibleOrRetentionAmount_A")
    reasons = _guard_reasons(res)
    assert reasons["ExcessUmbrella_Umbrella_DeductibleOrRetentionAmount_A"] == se.REASON_OTHER_POLICY


def test_the_excess_copy_prints_no_employee_benefits_program(package):
    """PROBLEMS.md 10 / 11: the excess declarations never name employee
    benefits (and the umbrella's schedule EXCLUDES it)."""
    res = _stamp(package, EXCESS, _EXCESS_AI)
    assert not res["mapped"].get("ExcessUmbrella_EmployeeBenefits_ProgramName_A")
    assert _guard_reasons(res)["ExcessUmbrella_EmployeeBenefits_ProgramName_A"] \
        == se.REASON_SECTION_ABSENT


def test_the_excess_copy_keeps_the_umbrella_as_its_underlying(package):
    """Brent #4: "Layer 2 is Excess, which gets mapped to the underlying
    umbrella policy" - untouched by this round."""
    m = _stamp(package, EXCESS, _EXCESS_AI)["mapped"]
    assert m.get("UnderlyingPolicy_OtherPolicy_InsurerFullName_A") == \
        "AMERISURE MUTUAL INSURANCE COMPANY"
    assert "5,000,000" in str(m.get("UnderlyingPolicy_OtherPolicy_CombinedSingleLimitAmount_A"))


def test_acord_140_prints_no_spoilage_or_blanket_section(package):
    """PROBLEMS.md 11: no document says "spoilage" or prints a property
    blanket; the AI copied the buildings' own limits into both sections."""
    res = _stamp(package, "ACORD_140", _140_SECTION_AI)
    m = res["mapped"]
    reasons = _guard_reasons(res)
    for f in _140_SECTION_AI:
        assert not m.get(f), f
        assert reasons.get(f) == se.REASON_SECTION_ABSENT, f


def test_a_premises_value_the_package_prints_stands_on_acord_140(package):
    """Look-alike: the same $73,008 in the PREMISES grid is the package's own
    property limit (the package declarations print it) - not a section, kept."""
    ai = dict(_140_SECTION_AI, CommercialProperty_Premises_LimitAmount_C="$73,008")
    res = _stamp(package, "ACORD_140", ai)
    # Whatever another round-5 rule decides about the duplicated row, it is
    # never this module's: the value is the package's own property limit.
    assert _guard_reasons(res).get("CommercialProperty_Premises_LimitAmount_C") \
        not in se.HELD_BACK_TEXT


def test_the_auto_hired_limit_printed_without_a_comma_is_witnessed(package):
    """Look-alike for (a): the auto declarations print the hired-auto physical
    damage limit as "75000"; "$75,000" is the same number."""
    res = _stamp(package, "ACORD_137_CO", {"Vehicle_OtherCoverage_LimitAmount_D": "$75,000"})
    assert _guard_reasons(res).get("Vehicle_OtherCoverage_LimitAmount_D") not in (
        se.REASON_OTHER_POLICY, se.REASON_OTHER_LAYER)


def test_the_umbrella_131_lists_no_cyber_or_ebl_as_underlying(package):
    """PROBLEMS.md 12: the umbrella's schedule of underlying insurance lists GL,
    Auto and WC / EL and EXCLUDES employee benefits; the package's carried cyber
    and EBL policies are not underlying to it."""
    m = _stamp(package, "ACORD_131", {})["mapped"]
    for r in "ABCD":
        assert not m.get(f"UnderlyingCoverage_Coverage_OtherDescription_{r}"), r
        assert not m.get(f"UnderlyingCoverage_Coverage_OtherIndicator_{r}"), r
    assert not m.get("UnderlyingPolicy_OtherPolicy_InsurerFullName_A")


def test_the_shared_gap_fill_never_asks_about_uncarried_coverage(package, monkeypatch):
    """(b), before the model: the Spoilage / Blanket questions on 140 and the
    excess copy's employee-benefits questions are not asked; the premises grid
    and the excess's own limits still are (improving-ll.md C104)."""
    asked = {}

    def _record(forms_to_unmatched, *a, **k):
        for fid, fields in (forms_to_unmatched or {}).items():
            asked.setdefault(fid, set()).update(fields)
        return {}
    monkeypatch.setattr(pdf, "combined_gap_fill", _record)
    fs.shared_gap_fill(package, ["ACORD_140", "ACORD_131", EXCESS])
    q140 = asked.get("ACORD_140", set())
    assert not any(se.coverage_section(f) in ("spoilage", "blanket") for f in q140)
    assert "CommercialProperty_Premises_LimitAmount_C" in q140 or any(
        f.startswith("CommercialProperty_Premises_") for f in q140)
    qx = asked.get(EXCESS, set())
    assert not any(f.startswith("ExcessUmbrella_EmployeeBenefits_") for f in qx)
    assert "ExcessUmbrella_Umbrella_DeductibleOrRetentionAmount_A" in qx


def test_process_single_form_attaches_the_documents(package, monkeypatch):
    seen = {}
    real = pdf.map_facts_to_form

    def _spy(facts, *a, **k):
        seen["docs"] = se._documents(facts)
        return real(facts, *a, **k)
    monkeypatch.setattr(fs, "map_facts_to_form", _spy)
    _stamp(package, "ACORD_140", {})
    assert {d.name for d in seen["docs"]} == {d["filename"] for d in package["docs"]}


def test_the_documents_never_reach_the_prompt_facts_block():
    assert se.DOCS_KEY in pdf._GAP_FILL_FACTS_EXCLUDE


# ═════════════════════════════════════════════════════════════════════════════
# (b) The sections, derived from the schemas (read-only)
# ═════════════════════════════════════════════════════════════════════════════
_EXPECTED_SECTIONS = {
    "ACORD_126": {"employee_benefits": 5},
    "ACORD_131": {"employee_benefits": 7, "watercraft": 8, "aircraft": 2,
                  "garagekeepers": 2, "liquor": 2},
    "ACORD_140": {"spoilage": 10, "blanket": 22, "sinkhole": 6, "mine_subsidence": 6},
    "ACORD_28": {"blanket": 3, "fungus": 5, "equipment_breakdown": 5, "earthquake": 5,
                 "flood": 5},
    "ACORD_138_CA": {"garagekeepers": 7},
    "ACORD_125": {}, "ACORD_127": {}, "ACORD_130": {}, "ACORD_25": {}, "ACORD_101": {},
}


@pytest.mark.parametrize("form_id,expected", sorted(_EXPECTED_SECTIONS.items()))
def test_the_sections_each_schema_declares(form_id, expected):
    got = {}
    for _f, sec in se.coverage_sections(_schema(form_id)).items():
        got[sec] = got.get(sec, 0) + 1
    assert got == expected


def test_every_coverage_in_the_vocabulary_names_a_real_section():
    seen = set()
    for p in sorted((BACKEND / "forms_schemas").glob("*_schema.json")):
        seen |= set(se.coverage_sections(json.loads(p.read_text())).values())
    assert {c.key for c in se.OPTIONAL_COVERAGES} == seen


@pytest.mark.parametrize("field", [
    "GeneralLiabilityLineOfBusiness_WatercraftDocksFloatsOwnedHiredLeasedExplanation_A",
    "Policy_LineOfBusiness_LiquorLiabilityIndicator_A",
    "Policy_SectionAttached_GlassAndSignIndicator_A",
    "EmployeeBenefitPlan_PlanName_A",                  # an ERISA plan, not EBL
    "CommercialProperty_Premises_LimitAmount_A",
])
def test_not_a_coverage_section(field):
    assert se.coverage_section(field) is None


# ═════════════════════════════════════════════════════════════════════════════
# Reading one mention of a coverage (corpus shapes)
# ═════════════════════════════════════════════════════════════════════════════
@pytest.mark.parametrize("phrase,text,want", [
    ("blanket", "CA7479(11-17) – Blanket Primary and Noncontributory Additional Insured", "neutral"),
    ("blanket", "*CU7460 12-15 BLANKET WAIVER OF SUBROG WHEN REQUIR *CU7468", "neutral"),
    ("blanket", "$655,000 $5,000 Blanket business personal property is not written. Coverage", "excluded"),
    ("blanket", "TOTAL INSURABLE VALUE $4,345,000 BLANKET OR SPECIFIC SPECIFIC BY LOCATION", "neutral"),
    ("blanket", "3 Blanket unscheduled tools - $25,000 CM7000A", "neutral"),
    ("blanket", "Waiver of Our Right to Recover from Others Endorsement-Blanket 0.0200 500.00", "neutral"),
    ("blanket", "BLANKET BUILDING AND PERSONAL PROPERTY LIMIT $5,000,000", "named"),
    ("blanket", "Blanket #1 - Combined Building and Contents $3,150,000", "named"),
    ("blanket", "Blanket Limit: $2,000,000", "named"),
    ("spoilage", "FLOOD: EXCLUDED EQUIPMENT BREAKDOWN: INCLUDED SPOILAGE: N/A PROPERTY PREMIUM", "excluded"),
    ("spoilage", "CP 04 40 10 12 SPOILAGE COVERAGE", "named"),
    ("spoilage", "Spoilage (refrigerated stock) $25,000 deductible $500", "named"),
    ("employee benefit", "EXCLUDED Employee Benefits\nLiability Each Employee", "excluded"),
    ("employee benefit", "PROFESSIONAL LIABILITYCOVERAGEPART $\nEMPLOYEE BENEFIT LIABILITY COVERAGE PART $ 425.00", "named"),
    ("employee benefit", "Employee Benefits Liability: Not requested PREMIUM BASIS", "excluded"),
    ("employee benefit", "employee benefits liability coverage is not being purchased on this policy", "excluded"),
    ("employee benefit", "Employee Benefits Liability is not scheduled as underlying insurance", "excluded"),
    ("employee benefit", "EMPLOYEE BENEFITS LIABILITY LIMIT $1,000,000", "named"),
    ("flood", "Earthquake Coverage COVERED Flood Coverage NOT COVERED NEWLY", "excluded"),
    ("earthquake", "Earthquake Coverage COVERED Flood Coverage NOT COVERED NEWLY", "named"),
    ("mine subsidence", "MINE SUBSIDENCE COVERAGE (IL, IN, KY, WV): N/A (California location)", "excluded"),
    ("sink hole", "Is there any exposure to sink hole or mine subsidence? No known", "neutral"),
    ("mine subsidence", "No known sink hole or mine subsidence exposure exists at either location.", "excluded"),
    ("aircraft", "*CU2171 06-15 EXCLUSION-UNMANNED AIRCRAFT *CU2186 12-23", "excluded"),
    ("fungi", "CU 21 27 12 04 FUNGI OR BACTERIA EXCLUSION", "excluded"),
    ("liquor", "LIQUOR LIABILITYCOVERAGEPART $\nPOLLUTION LIABILITYCOVERAGEPART $", "neutral"),
])
def test_a_mention_is_read_as_the_document_means_it(phrase, text, want):
    cov = next(c for c in se.OPTIONAL_COVERAGES if phrase in c.phrases)
    m = se._phrase_regex(phrase).search(text)
    assert m is not None
    assert se._mention_state(text, m.start(), m.end(), cov.modifier) == want


# ═════════════════════════════════════════════════════════════════════════════
# (a) and (b) on synthetic documents
# ═════════════════════════════════════════════════════════════════════════════
def _doc(name, text, lines=None, rows=()):
    facts = {"coverage_lines": [dict(r) for r in rows]} if rows else {}
    flags = {f"has_{ln}": True for ln in (lines or ())}
    return {"filename": name, "text": text, "facts": facts, "flags": flags}


_PROPERTY_DEC = _doc("prop.pdf", "COMMERCIAL PROPERTY COVERAGE PART\nBUILDING LIMIT $500,000 "
                     "DEDUCTIBLE $1,000\nPERSONAL PROPERTY $80,000",
                     rows=[{"line": "Commercial Property", "premium": "$2,000"}])
_WC_DEC = _doc("wc.pdf", "WORKERS COMPENSATION INFORMATION PAGE\nWaiver Endorsement-Blanket "
               "0.0200 500.00\nEmployers Liability $1,000,000",
               rows=[{"line": "Workers Compensation", "premium": "$9,000"}])
_CYBER_DEC = _doc("cyber.pdf", "Cyber Incident Response Each Incident Retention $10,000",
                  rows=[{"line": "Cyber", "premium": "$4,000"}])


def _facts(*docs, **extra):
    f = dict(extra)
    se.attach_documents(f, list(docs))
    return f


def test_nothing_changes_without_documents():
    m = {"CommercialProperty_Spoilage_LimitAmount_A": "500,000"}
    assert se.out_of_scope_values(m, _schema("ACORD_140"), {}, "ACORD_140", set(m)) == {}


def test_a_section_absent_from_the_property_documents_is_dropped():
    facts = _facts(_PROPERTY_DEC, _WC_DEC)
    m = {"CommercialProperty_Spoilage_LimitAmount_A": "500,000",
         "CommercialProperty_Summary_BlanketLimitAmount_A": "$500,000",
         "CommercialProperty_Premises_LimitAmount_A": "$500,000"}
    out = se.out_of_scope_values(m, _schema("ACORD_140"), facts, "ACORD_140", set(m))
    assert out == {"CommercialProperty_Spoilage_LimitAmount_A": se.REASON_SECTION_ABSENT,
                   "CommercialProperty_Summary_BlanketLimitAmount_A": se.REASON_SECTION_ABSENT}


def test_a_section_the_property_declarations_name_stands():
    prop = _doc("prop.pdf", _PROPERTY_DEC["text"] + "\nCP 04 40 10 12 SPOILAGE COVERAGE\n"
                "BLANKET LIMIT $580,000 BUILDING AND PERSONAL PROPERTY",
                rows=[{"line": "Commercial Property", "premium": "$2,000"}])
    facts = _facts(prop)
    m = {"CommercialProperty_Spoilage_LimitAmount_A": "25,000",
         "CommercialProperty_Summary_BlanketLimitAmount_A": "$580,000"}
    assert se.out_of_scope_values(m, _schema("ACORD_140"), facts, "ACORD_140", set(m)) == {}


def test_another_policys_document_never_names_a_section():
    """The WC declarations' "Endorsement-Blanket" is not a property blanket,
    and a WC document cannot speak for a property section anyway."""
    facts = _facts(_PROPERTY_DEC, _WC_DEC)
    assert se.section_state(facts, "ACORD_140",
                            "CommercialProperty_Summary_BlanketLimitAmount_A") == "absent"


def test_a_negative_answer_stands_where_the_documents_exclude_the_coverage():
    prop = _doc("prop.pdf", _PROPERTY_DEC["text"] + "\nSPOILAGE: N/A",
                rows=[{"line": "Commercial Property", "premium": "$2,000"}])
    facts = _facts(prop)
    m = {"CommercialProperty_Spoilage_YesNoCode_A": "N",
         "CommercialProperty_Spoilage_LimitAmount_A": "500,000"}
    out = se.out_of_scope_values(m, _schema("ACORD_140"), facts, "ACORD_140", set(m))
    assert out == {"CommercialProperty_Spoilage_LimitAmount_A": se.REASON_SECTION_EXCLUDED}


def test_a_document_with_no_line_speaks_for_every_line():
    app = _doc("application.pdf", "Spoilage coverage requested: limit $25,000 on the "
                                  "walk-in cooler.")
    facts = _facts(_WC_DEC, app)
    m = {"CommercialProperty_Spoilage_LimitAmount_A": "25,000"}
    assert se.out_of_scope_values(m, _schema("ACORD_140"), facts, "ACORD_140", set(m)) == {}


def test_a_value_printed_only_by_another_policy_is_dropped():
    facts = _facts(_PROPERTY_DEC, _CYBER_DEC)
    m = {"CommercialProperty_Premises_DeductibleAmount_A": "$10,000"}
    out = se.out_of_scope_values(m, _schema("ACORD_140"), facts, "ACORD_140", set(m))
    assert out == {"CommercialProperty_Premises_DeductibleAmount_A": se.REASON_OTHER_POLICY}


@pytest.mark.parametrize("value", ["$1,000", "1000", "1,000.00", "$1,000.00"])
def test_one_number_printed_any_way_is_witnessed(value):
    facts = _facts(_PROPERTY_DEC, _CYBER_DEC)
    m = {"CommercialProperty_Premises_DeductibleAmount_A": value}
    assert se.out_of_scope_values(m, _schema("ACORD_140"), facts, "ACORD_140", set(m)) == {}


def test_a_value_printed_nowhere_is_not_this_rules_question():
    facts = _facts(_PROPERTY_DEC, _CYBER_DEC)
    m = {"CommercialProperty_Premises_DeductibleAmount_A": "$7,777"}
    assert se.out_of_scope_values(m, _schema("ACORD_140"), facts, "ACORD_140", set(m)) == {}


def test_an_insured_fact_box_is_never_judged_by_policy():
    """Gross sales / payroll are the insured's, whichever document states them."""
    meta = {"tu": "Enter amount: The gross sales or receipts amount."}
    assert not se.is_policy_box("ACORD_126", "Hazard_Exposure_A", meta)
    assert se.is_policy_box("ACORD_126", "GeneralLiability_EachOccurrence_LimitAmount_A",
                            {"tu": "Enter limit: The each occurrence limit."})


@pytest.mark.parametrize("form_id", ["ACORD_141", "ACORD_160", "ACORD_138_CA"])
def test_frozen_and_unsure_forms_are_not_judged(form_id):
    facts = _facts(_PROPERTY_DEC, _CYBER_DEC)
    schema = _schema(form_id)
    field = next(iter(se.coverage_sections(schema)), None) or next(iter(schema))
    m = {field: "10,000"}
    assert se.out_of_scope_values(m, schema, facts, form_id, set(m)) == {}


def test_held_back_sentences_are_plain():
    for code, text in se.HELD_BACK_TEXT.items():
        assert "—" not in text and "–" not in text
        assert na.held_back(_schema("ACORD_140"), "CommercialProperty_Spoilage_LimitAmount_A",
                            "500,000", {}, reason=code)[0] == text


# ── One umbrella LAYER reads its own documents ──────────────────────────────
_UMB_DEC = _doc("umbrella.pdf", "UMBRELLA LIABILITY Each Occurrence $5,000,000\n"
                "Self-Insured Retention 0\nEXCLUDED Employee Benefits Liability",
                rows=[{"line": "Umbrella Liability", "premium": "$17,000"}])
_EXC_DEC = _doc("excess.pdf", "EXCESS (FOLLOWING FORM) LIABILITY $4,000,000 any one occurrence",
                rows=[{"line": "Excess (Following Form) Liability", "premium": "$10,000"}])


def _layer(index):
    own = ["umbrella.pdf"] if index == 0 else ["excess.pdf"]
    other = ["excess.pdf"] if index == 0 else ["umbrella.pdf"]
    return {"key": "" if index == 0 else "excess", "index": index, "count": 2,
            "own_documents": own, "other_layer_documents": other}


def test_an_upper_layer_never_takes_the_layer_below_its_figures():
    facts = _facts(_UMB_DEC, _EXC_DEC, _CYBER_DEC, _umbrella_layer=_layer(1))
    m = {"ExcessUmbrella_Umbrella_EachOccurrenceAmount_A": "5,000,000",
         "ExcessUmbrella_Umbrella_DeductibleOrRetentionAmount_A": "10,000"}
    out = se.out_of_scope_values(m, _schema("ACORD_131"), facts, "ACORD_131", set(m))
    assert out == {"ExcessUmbrella_Umbrella_EachOccurrenceAmount_A": se.REASON_OTHER_LAYER,
                   "ExcessUmbrella_Umbrella_DeductibleOrRetentionAmount_A": se.REASON_OTHER_POLICY}


def test_each_layer_keeps_its_own_figures():
    up = _facts(_UMB_DEC, _EXC_DEC, _umbrella_layer=_layer(1))
    low = _facts(_UMB_DEC, _EXC_DEC, _umbrella_layer=_layer(0))
    s131 = _schema("ACORD_131")
    assert se.out_of_scope_values({"ExcessUmbrella_Umbrella_EachOccurrenceAmount_A": "4,000,000"},
                                  s131, up, "ACORD_131",
                                  {"ExcessUmbrella_Umbrella_EachOccurrenceAmount_A"}) == {}
    assert se.out_of_scope_values({"ExcessUmbrella_Umbrella_EachOccurrenceAmount_A": "5,000,000"},
                                  s131, low, "ACORD_131",
                                  {"ExcessUmbrella_Umbrella_EachOccurrenceAmount_A"}) == {}


def test_the_umbrellas_excluded_ebl_blanks_its_ebl_section():
    facts = _facts(_UMB_DEC, _EXC_DEC, _umbrella_layer=_layer(0))
    m = {"ExcessUmbrella_EmployeeBenefits_EachEmployeeLimitAmount_A": "1,000,000"}
    out = se.out_of_scope_values(m, _schema("ACORD_131"), facts, "ACORD_131", set(m))
    assert out == {"ExcessUmbrella_EmployeeBenefits_EachEmployeeLimitAmount_A":
                   se.REASON_SECTION_EXCLUDED}


def test_an_insured_box_reads_the_same_on_every_layer():
    """C102's shared boxes (the insured's watercraft) are one answer for both
    copies: judged over every document, never one layer's."""
    boat = _doc("application.pdf", "Watercraft owned: one 22 ft boat, 150 HP outboard.")
    s131 = _schema("ACORD_131")
    m = {"Watercraft_Length_A": "22"}
    for idx in (0, 1):
        facts = _facts(_UMB_DEC, _EXC_DEC, boat, _umbrella_layer=_layer(idx))
        assert se.section_state(facts, "ACORD_131", "Watercraft_Length_A") == se.NAMED
        assert se.out_of_scope_values(m, s131, facts, "ACORD_131", set(m)) == {}


# ═════════════════════════════════════════════════════════════════════════════
# (c) The 131's underlying OTHER rows
# ═════════════════════════════════════════════════════════════════════════════
_LEFT = [{"line": "Cyber", "premium": "$4,162"},
         {"line": "Employee Benefit Liability Coverage Part", "premium": "$425"},
         {"line": "Liquor Liability", "premium": "$900", "policy_number": "LQ-1"}]
_SCHEDULE = [{"line": "Workers Compensation and Employers Liability", "limit": "$1,000,000"},
             {"line": "General Liability", "limit": "$1,000,000"},
             {"line": "Automobile Liability", "limit": "$1,000,000"}]


def test_only_what_the_umbrella_schedules_is_underlying():
    assert se.scheduled_underlying_leftovers(_LEFT, {"underlying_policies": _SCHEDULE}) == []
    sched = _SCHEDULE + [{"line": "Liquor Liability", "limit": "$1,000,000"}]
    assert [e["line"] for e in se.scheduled_underlying_leftovers(
        _LEFT, {"underlying_policies": sched})] == ["Liquor Liability"]


def test_an_excluded_scheduled_line_is_never_underlying():
    sched = _SCHEDULE + [{"line": "Employee Benefits Liability", "limit": "EXCLUDED"}]
    assert se.scheduled_underlying_leftovers(_LEFT, {"underlying_policies": sched}) == []


def test_with_no_schedule_a_line_the_umbrella_form_excludes_is_never_underlying():
    """No schedule known: cyber and EBL (excluded by the umbrella form unless
    scheduled) never print; a liquor policy still may (round 9's rule)."""
    assert [e["line"] for e in se.scheduled_underlying_leftovers(_LEFT, {})] == \
        ["Liquor Liability"]
    assert se.scheduled_underlying_leftovers([], {"underlying_policies": _SCHEDULE}) == []
    others = [{"line": f, "premium": "$1"} for f in (
        "Employment Practices Liability", "Directors and Officers Liability",
        "Professional Liability", "Pollution Legal Liability", "Network Security Liability")]
    assert se.scheduled_underlying_leftovers(others, {}) == []


def test_an_excess_layers_controlling_umbrella_row_is_no_schedule():
    """Rows naming only the umbrella itself (an excess dec's controlling
    underlying) say nothing about the umbrella's own schedule."""
    sched = [{"line": "Umbrella Liability", "limit": "5,000", "carrier": "X"}]
    assert [e["line"] for e in se.scheduled_underlying_leftovers(
        _LEFT, {"underlying_policies": sched})] == ["Liquor Liability"]


def test_a_cyber_policy_the_umbrella_schedules_is_underlying():
    sched = _SCHEDULE + [{"line": "Cyber Liability", "limit": "$1,000,000"}]
    assert [e["line"] for e in se.scheduled_underlying_leftovers(
        _LEFT, {"underlying_policies": sched})] == ["Cyber"]


def test_a_carried_but_unscheduled_line_fills_no_other_row():
    """The unscheduled half of tests/test_relationship_fixes_20260816's
    liquor case: carried, but the umbrella's schedule lists Auto and GL only."""
    facts = {
        "coverage_lines": [
            {"line": "Commercial General Liability", "premium": "$3,954"},
            {"line": "Business Auto", "premium": "$2,991"},
            {"line": "Commercial Liability Umbrella", "premium": "$3,418",
             "policy_number": "UMB-1"},
            {"line": "Liquor Liability", "premium": "$900", "policy_number": "LQ-1"}],
        "underlying_policies": [
            {"line": "Business Auto", "limit": "$1,000,000", "policy_no": "AU-1"},
            {"line": "General Liability", "limit": "$1,000,000", "policy_no": "GL-1"}],
        "_form_id": "ACORD_131",
    }
    with pdf._schema_context(_schema("ACORD_131")):
        assert pdf._resolve_underlying_coverage_grid(
            "UnderlyingCoverage_Coverage_OtherDescription_A", facts) is None
        assert pdf._resolve_underlying_policy_row(
            "UnderlyingPolicy_OtherPolicy_PolicyTypeDescription_A", facts) is None


def test_a_dropped_row_is_logged(caplog):
    with caplog.at_level(logging.INFO, logger="services.scoped_evidence"):
        se.scheduled_underlying_leftovers(_LEFT, {"underlying_policies": _SCHEDULE})
    assert any(se.REASON_UNSCHEDULED in r.getMessage() for r in caplog.records)
