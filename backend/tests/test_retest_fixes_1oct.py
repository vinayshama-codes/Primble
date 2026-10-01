"""The owner's retest of 1 Oct 2026 (session bfa8711d): what it found, pinned.

* ACORD 126 LOC # printed "4800" - the street number of the hazard row's
  location, which the document printed as the premises' ADDRESS. The box's own
  tooltip asks for "the location number ... as it appears on ACORD 125": the
  number ACORD 125 gives the premises at that address, or blank.
* The cover printed the agent's account name in lower case beside the
  formatted name on every form, and form ids as "ACORD_137_CO".
* The cover hedged a card "up to +7 pts" beside the panel's "+7 pts".
* The side panel: both sections closed by default like every other section,
  the applicant's own steps grouped apart from the producer's Missing boxes,
  and the pending-edits note in the owner's words.
"""
import io
import json
import random
import re
import shutil
import subprocess
from pathlib import Path

import pytest

import services.cover_service as cs
import services.needs_attention as na
import services.pdf_service as ps
from routes import download_routes as dr

BACKEND = Path(__file__).resolve().parents[1]
FRONTEND = BACKEND.parent / "frontend" / "src"
PANEL = FRONTEND / "components" / "form" / "NeedsAttentionPanel.jsx"
UTIL = FRONTEND / "utils" / "needsAttention.js"
ACORD_MODAL = FRONTEND / "components" / "form" / "AcordModal.jsx"


def _loc(number, line1, zip_, line2="", city="Denver", state="CO"):
    return {"location_number": number, "address_line1": line1, "address_line2": line2,
            "address_city": city, "address_state": state, "address_zip": zip_}


HOME = _loc("1", "4800 Juniper St", "80216-3121", line2="# D13")
YARD = _loc("2", "77 Oak Ave", "80202")
FACTS = {"property_locations": {"value": [HOME, YARD], "source": "extracted"}}
LOC = "GeneralLiability_Hazard_LocationProducerIdentifier_{}"
HAZ = "GeneralLiability_Hazard_HazardProducerIdentifier_{}"


# ══ LOC #: an address is the premises' number, never its street number ══════

@pytest.mark.parametrize("text", [
    "4800 Juniper St # D13, Denver, CO 80216-3121",          # the live run's shape
    "4800 JUNIPER STREET D13 / DENVER CO. 80216-3121",
    "Suite D13, 4800 Juniper St, Denver, CO 80216",            # the suite first
    "001 4800 Juniper St, Denver, CO 80216",                   # a bare label, then the address
    "4800 Juniper Street, Unit D13, Denver CO 80216",
    "LOC: 001 4800 JUNIPER STREET",                            # a keyword label decides
])
def test_an_address_prints_the_number_acord_125_gives_that_premises(text):
    assert ps._hazard_location_number(text, FACTS) == "1"


@pytest.mark.parametrize("text", [
    "4800 Juniper St",                       # no ZIP: not pinned to the premises
    "1 Main St, Springfield, IL 62701",      # "1" is a street number here, not location 1
    "2 Commerce Dr, Denver, CO 80202",       # nor is "2", though a premises is numbered 2
    "9100 Industrial Pkwy, Aurora, CO 80011",
    "9 Warehouse",                           # no premises 9
])
def test_an_address_no_premises_matches_is_blank_never_its_street_number(text):
    assert ps._hazard_location_number(text, FACTS) is None


@pytest.mark.parametrize("text, facts, want", [
    ("Location 001", FACTS, "1"), ("Location 001", None, "001"), ("001", FACTS, "1"),
    ("001", None, "001"), ("Loc #2", FACTS, "2"), ("Bldg 2 Loc 1", FACTS, "1"),
    ("Location 000", FACTS, None), ("Site 1", FACTS, "1"), ("2 Warehouse", FACTS, "2"),
    ("Main Street", FACTS, "Main Street"), ("", FACTS, None), (None, FACTS, None),
])
def test_a_label_reads_as_it_did(text, facts, want):
    assert ps._hazard_location_number(text, facts) == want


def test_two_premises_at_one_address_name_no_number():
    facts = {"property_locations": {"value": [HOME, _loc("3", "4800 Juniper St", "80216", line2="# D14")]}}
    assert ps._hazard_location_number("4800 Juniper St # D13, Denver, CO 80216-3121", facts) is None


def _grid(*locations):
    rows = [{"location": loc, "class_code": code, "classification": "Carpentry - interior",
             "premium_basis": "Payroll", "exposure_amount": "$39,300"}
            for loc, code in zip(locations, ("91580", "91585", "91340"))]
    return {**FACTS, "gl_class_code_schedule": {"value": rows, "source": "extracted"}}


def test_the_hazard_grid_prints_the_premises_number_and_owns_an_unmatched_blank():
    addr = "4800 Juniper St # D13, Denver, CO 80216-3121"
    facts = _grid(addr, addr)
    for r in "AB":
        assert ps._resolve_gl_hazard_row(LOC.format(r), facts) == "1"
        assert ps._resolve_phantom_gl_hazard_row(LOC.format(r), facts) is ps._SCHED_SKIP
    assert [ps._resolve_gl_hazard_row(HAZ.format(r), facts) for r in "AB"] == ["1", "2"]
    # an address no premises matches: an owned blank - gap fill never gets the box
    facts = _grid("9100 Industrial Pkwy, Aurora, CO 80011")
    assert ps._resolve_gl_hazard_row(LOC.format("A"), facts) is None
    assert ps._resolve_phantom_gl_hazard_row(LOC.format("A"), facts) is None


_STREETS = ["Juniper", "Oak", "Walnut", "Cedar", "Larkspur", "Quebec", "Federal", "Kipling"]
_TYPES = [("St", "Street"), ("Ave", "Avenue"), ("Rd", "Road"), ("Blvd", "Boulevard"), ("Dr", "Drive")]
_CITIES = ["Denver", "Aurora", "Boulder", "Golden", "Arvada"]


def _printings(rng, num, name, types, suite, city, zip5, zip4):
    short, long_ = types
    z = rng.choice([zip5, f"{zip5}-{zip4}"])
    return [f"{num} {name} {short}, {city}, CO {z}",
            f"{num} {name.upper()} {long_.upper()} {suite} / {city.upper()} CO. {z}",
            f"Suite {suite}, {num} {name} {short}, {city}, CO {zip5}",
            f"{num} {name} {short} # {suite}, {city}, CO {z}"]


@pytest.mark.parametrize("seed", range(40))
def test_any_printing_of_a_premises_address_reaches_its_number_and_no_other(seed):
    rng = random.Random(seed)
    names = rng.sample(_STREETS, rng.randint(1, 4))
    locs, printed = [], []
    for i, name in enumerate(names, start=1):
        num, zip5 = str(rng.randint(10, 99999)), f"80{rng.randint(100, 999)}"
        types, suite, city = rng.choice(_TYPES), f"{rng.choice('ABCD')}{rng.randint(1, 30)}", rng.choice(_CITIES)
        locs.append(_loc(str(i), f"{num} {name} {types[0]}", zip5, city=city))
        printed.append((str(i), num, _printings(rng, num, name, types, suite, city, zip5, rng.randint(1000, 9999))))
    facts = {"property_locations": {"value": locs}}
    for number, street_number, shapes in printed:
        for text in shapes:
            got = ps._hazard_location_number(text, facts)
            assert got == number, (text, got)
            assert got != street_number or street_number == number
    # a street the schedule does not hold: blank, whatever its number
    stranger = f"{rng.randint(10, 99999)} Nowhere Ct, Pueblo, CO 81001"
    assert ps._hazard_location_number(stranger, facts) is None


# ══ The cover: the agent as the forms print it, forms as ACORD names them ═════

@pytest.mark.parametrize("name", ["jane q doe", "  jane   doe ", "JLL Desk", "McAllister Agency",
                                  "ana de la cruz", "o'neil smith"])
def test_the_cover_prints_the_agent_as_the_forms_do(name):
    typed = re.sub(r"\s+", " ", name).strip()
    want = ps.display_value_for_box("ACORD_125", "Producer_ContactPerson_FullName_A", typed,
                                    provenance="account")
    assert cs._agent_name({"full_name": name}) == want
    assert cs._cover_info_values({}, {}, {"full_name": name}, "Org")["agent"] == want
    block = cs.a2a_block({}, {}, org_name="Org", user={"full_name": name}, scores=[], form_ids=[])
    assert block["agent_name"] == want
    if any(ch.isupper() for ch in typed):
        assert want == typed                         # a capital typed: printed as typed
    else:
        assert want != typed and want.lower() == typed.lower()


@pytest.mark.parametrize("user", [None, {}, {"full_name": None}, {"full_name": "   "}])
def test_no_agent_name_is_not_provided(user):
    assert cs._agent_name(user) == ""
    assert cs._cover_info_values({}, {}, user, "Org")["agent"] == cs._COVER_UNKNOWN


def _pdf_text(pdf_bytes):
    import pypdfium2 as pdfium
    doc = pdfium.PdfDocument(io.BytesIO(pdf_bytes))
    return "\n".join(doc[i].get_textpage().get_text_range() for i in range(len(doc)))


def test_the_printed_cover_names_forms_and_agent_as_the_forms_do():
    ids = ["ACORD_125", "ACORD_137_CO", "ACORD_25"]
    pdf = cs.build_cover_page_pdf(
        facts={"applicant_name": {"value": "Acme Builders LLC"}}, flags={}, form_ids=ids,
        sqs_results={f: {"sqs_score": 80} for f in ids}, org_name="Org", narrative="N.",
        ai_block={}, sqs_reasoning="R.", user={"full_name": "jane q doe"})
    text = re.sub(r"\s+", " ", _pdf_text(pdf))          # the PDF wraps lines anywhere
    assert "ACORD 125, ACORD 137 CO, ACORD 25" in text
    assert "ACORD_" not in text
    assert "jane q doe" not in text and cs._agent_name({"full_name": "jane q doe"}) in text
    assert [cs._cover_form_label(f) for f in ids] == ["ACORD 125", "ACORD 137 CO", "ACORD 25"]


# ══ The cover's card points: the panel's number, and its hedge ══════════════

def test_the_cover_prints_each_card_as_the_panel_shows_it():
    generated = {
        "ACORD_125": {"sqs": {"recommendations": [
            {"rec_id": "rec_loss", "score_impact": 7, "impact_is_exact": True},
            {"rec_id": "rec_story", "score_impact": 6, "impact_is_exact": False},
            {"rec_id": "rec_zero", "score_impact": 0, "impact_is_exact": True},
            {"rec_id": "rec_flag", "score_impact": True},           # a bool is not a number
            "not a card", {"score_impact": 3}]}},
        "ACORD_126": {"sqs": {"recommendations": [
            {"rec_id": "rec_loss", "score_impact": 7.0, "impact_is_exact": True}]}},
        "ACORD_127": None,
    }
    live = dr._live_card_points(generated)
    assert live == {"rec_loss": (7, True), "rec_story": (6, False), "rec_zero": (0, True)}
    stored = [
        {"rec_id": "rec_loss", "message": "Loss history", "score_impact": 12, "recommendation_type": "soft_warning"},
        {"rec_id": "rec_story", "message": "Narrative", "score_impact": 6, "recommendation_type": "soft_warning"},
        {"rec_id": "rec_gone", "message": "Old card", "score_impact": 4, "recommendation_type": "soft_warning"},
        {"rec_id": "rec_hard", "message": "Hard", "score_impact": 40, "recommendation_type": "hard_stop"},
    ]
    hard, soft = dr._split_open_recs(stored, frozenset(), live)
    assert soft == ["Loss history (+7 pts)", "Narrative (up to +6 pts)", "Old card (up to +4 pts)"]
    assert hard == ["Hard (-40 pts)"]
    # no live points (a legacy call): every stored number keeps its hedge
    assert dr._split_open_recs(stored)[1][0] == "Loss history (up to +12 pts)"
    assert dr._live_card_points(None) == {} and dr._live_card_points({}) == {}


# ══ The side panel ══════════════════════════════════════════════════════════

def _src(path):
    return path.read_text(encoding="utf-8")


def test_the_side_panel_sections_start_closed_like_every_other_section():
    sections = [line for line in _src(PANEL).splitlines() if "<Section " in line]
    assert len(sections) == 2 and not any("defaultOpen" in line for line in sections)
    assert "function CollapsibleSection({ title, tooltip, titleRight, defaultOpen = false," in _src(ACORD_MODAL)


def test_the_applicant_group_reads_as_the_review_names_it():
    util = _src(UTIL)
    assert f'export const APPLICANT_GROUP_LABEL = "{na._APPLICANT_ROW_TITLE}";' in util
    assert f'hint: "{na._APPLICANT_ROW_NEXT}"' in util
    panel = _src(PANEL)
    # one split for the panel, the review and the review's counts
    assert "attentionGroups(rows).map(" in panel and "attentionGroups(f.rows).map(" in panel
    assert "ATTENTION_STATUS_ORDER" not in panel
    assert '<Tag status={isApplicantStep(row) ? "applicant" : row.status} />' in panel


def test_the_verify_tag_names_calculated_values_too():
    assert 'hint: "Filled by the AI or calculated by us, and not confirmed in your documents."' in _src(UTIL)
    assert "not found word for word in your documents" not in _src(UTIL)


@pytest.mark.parametrize("path", [PANEL, UTIL])
def test_no_em_dashes(path):
    assert "—" not in _src(path)


@pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")
def test_the_groups_split_in_node(tmp_path):
    # the module without its network import (`import.meta.env` is Vite's)
    body = re.sub(r'^import \{ API_BASE \} from "\.\./config/constants";\n', 'const API_BASE = "";\n', _src(UTIL))
    (tmp_path / "na.mjs").write_text(body, encoding="utf-8")
    rows = [{"status": "verify", "field": "v1"}, {"status": "missing", "field": "m1"},
            {"status": "missing", "field": "s1", "applicant_step": True},
            {"status": "ai_held_back", "field": "h1"}, {"status": "missing", "field": "m2"},
            {"status": "missing", "field": "s2", "applicant_step": True},
            {"status": "verify", "field": "x", "applicant_step": True}]   # only a Missing row is a step
    script = tmp_path / "check.mjs"
    script.write_text(
        f"import * as N from {json.dumps((tmp_path / 'na.mjs').as_uri())};\n"
        f"const rows = {json.dumps(rows)};\n"
        "const g = N.attentionGroups(rows).map(x => [x.key, x.label, x.rows.map(r => r.field)]);\n"
        "console.log(JSON.stringify([g, N.attentionGroups(null), N.attentionGroups([{status: 'verify'}]).length]));\n",
        encoding="utf-8")
    run = subprocess.run(["node", str(script)], capture_output=True, text=True, timeout=60)
    assert run.returncode == 0, run.stderr
    groups, empty, one = json.loads(run.stdout)
    assert groups == [["missing", "Missing", ["m1", "m2"]],
                      ["applicant", na._APPLICANT_ROW_TITLE, ["s1", "s2"]],
                      ["ai_held_back", "AI held back", ["h1"]],
                      ["verify", "Please verify", ["v1", "x"]]]
    assert empty == [] and one == 1


# ══ ACORD 126 PRODUCTS / COMPLETED OPERATIONS: the applicant's, not the rating ═
# Live 82a8b15d: class codes 91580 / 91585 as products, each class's premium
# ("3.4240 $1,198 2.293 $803") as gross sales, and a row C out of the policy's
# own coverage form. 4 of 17 stored ACORD 126s carried junk here.

import asyncio
import copy

S126 = json.loads((BACKEND / "forms_schemas" / "ACORD_126_schema.json").read_text(encoding="utf-8"))
P = "ProductAndCompletedOperations_{}_{}"
_SCHEDULE = {"gl_class_code_schedule": {"value": [
    {"location": "Location 001", "class_code": "91580",
     "classification": "Contractors - Executive Supervisors or Executive Superintendents",
     "premium_basis": "Payroll", "exposure_amount": "$39,300"},
    {"location": "Location 001", "class_code": "91585",
     "classification": "Contrctrs-sub work-in connection w/constrctn,recon,repr,erctn of buildings - NOC",
     "premium_basis": "Total Cost", "exposure_amount": "$350,000"}], "source": "ai"}}
# The live run's values, exactly as gap fill wrote them.
_LIVE_PRODUCTS = {
    P.format("ProductName", "A"): "91580", P.format("AnnualGrossSalesAmount", "A"): "$1,198",
    P.format("ProductName", "B"): "91585", P.format("AnnualGrossSalesAmount", "B"): "$803",
    P.format("InMarketMonthCount", "C"): "12", P.format("ExpectedLifeMonthCount", "C"): "12",
    P.format("PrincipalComponents", "C"): "COMMERCIAL GENERAL LIABILITY COVERAGE FORM",
}
_DEC_TEXT = ("91580 Contractors - Executive Supervisors 33.211 $1,305\nor Executive Superintendents\n"
             "91585 Contrctrs-sub work-in connection 3.4240 $1,198 2.293 $803\n"
             "COMMERCIAL GENERAL LIABILITY COVERAGE FORM\nPolicy Period: 12 months\n")


@pytest.fixture
def _no_judge(monkeypatch):
    monkeypatch.setattr(ps, "_judge_evidence_batch", lambda items, form_id="", unjudged=None: {})


def _fill126(values, facts=None, raw=_DEC_TEXT):
    report: list = []
    mapped, conf = ps.map_facts_to_form(
        copy.deepcopy(facts if facts is not None else _SCHEDULE), S126, form_id="ACORD_126",
        raw_text=raw, pre_filled_gpt={"filled_values": dict(values), "raw_text_fields": set(),
                                      "question_grounding": {}},
        guard_report=report)
    return mapped, report


def _products(mapped):
    return {k: v for k, v in mapped.items()
            if k.startswith("ProductAndCompletedOperations_") and str(v or "").strip()}


def test_the_live_rating_rows_leave_the_products_table_empty(_no_judge):
    mapped, report = _fill126(_LIVE_PRODUCTS)
    assert _products(mapped) == {}
    reasons = {r["field"]: r.get("reason") for r in report}
    # the NAMES are the findings, each with its rule; their cells go unreported
    assert reasons[P.format("ProductName", "A")] == "PRODUCT_IS_A_RATING_CLASS"
    assert reasons[P.format("ProductName", "B")] == "PRODUCT_IS_A_RATING_CLASS"
    assert not any(f.startswith("ProductAndCompletedOperations_") and "ProductName" not in f
                   for f in reasons)


def test_classification_wording_split_across_boxes_is_refused(_no_judge):
    """8739a72a: the classification cut in two - name + intended use - and the
    policy's coverage form as a third product."""
    values = {P.format("ProductName", "A"): "Contractors - Executive Supervisors",
              P.format("IntendedUse", "A"): "or Executive Superintendents",
              P.format("ProductName", "B"): "Contrctrs-sub Work-in Connection",
              P.format("IntendedUse", "B"): "w/constrctn,recon,repr,erctn of buildings - NOC",
              P.format("ProductName", "C"): "Commercial General Liability Coverage Form"}
    mapped, _ = _fill126(values)
    assert _products(mapped) == {}


def test_a_real_product_row_is_kept_whole(_no_judge):
    facts = {"gl_class_code_schedule": {"value": [
        {"class_code": "51896", "classification": "Metal goods manufacturing - NOC"}], "source": "ai"}}
    values = {P.format("ProductName", "A"): "Steel mounting brackets",
              P.format("AnnualGrossSalesAmount", "A"): "$2,400,000",
              P.format("IntendedUse", "A"): "Rooftop HVAC unit mounting",
              P.format("PrincipalComponents", "A"): "Galvanized steel",
              P.format("ProductName", "B"): "Metal goods"}   # two words of the class: not enough to call it the class
    raw = ("Products: Steel mounting brackets, annual sales $2,400,000, used for rooftop HVAC unit "
           "mounting, made of galvanized steel. Metal goods. 51896 Metal goods manufacturing - NOC")
    mapped, report = _fill126(values, facts=facts, raw=raw)
    kept = _products(mapped)
    assert str(kept.get(P.format("ProductName", "A"))).lower() == "steel mounting brackets"   # printed in title case
    assert P.format("IntendedUse", "A") in kept and P.format("PrincipalComponents", "A") in kept
    assert str(kept.get(P.format("ProductName", "B"))).lower() == "metal goods"
    assert not any(r.get("reason", "").startswith("PRODUCT_") for r in report)


@pytest.mark.parametrize("name, reason", [
    ("91580", "PRODUCT_IS_A_RATING_CLASS"), ("9 1 5 8 0", "PRODUCT_IS_A_RATING_CLASS"),
    ("12345", "PRODUCT_NAME_IS_A_NUMBER"), ("#2-00", "PRODUCT_NAME_IS_A_NUMBER"),
    ("CONTRACTORS - EXECUTIVE SUPERVISORS OR EXECUTIVE SUPERINTENDENTS", "PRODUCT_IS_A_RATING_CLASS"),
    ("executive supervisors or executive superintendents", "PRODUCT_IS_A_RATING_CLASS"),
    ("Erctn of Buildings NOC", "PRODUCT_IS_A_RATING_CLASS"),
    ("Executive supervisors", None), ("Ready-mix concrete", None), ("3M tape", None),
])
def test_what_a_product_name_may_not_be(name, reason):
    field = P.format("ProductName", "A")
    refused, _cells = ps._product_rows_to_refuse({field: name}, S126, _SCHEDULE, {field})
    assert refused.get(field) == reason


def test_a_row_with_no_name_keeps_no_ai_cell_and_a_named_row_stands():
    mapped = {P.format("AnnualGrossSalesAmount", "A"): "$5", P.format("UnitCount", "A"): "10",
              P.format("ProductName", "B"): "Drywall supplies", P.format("UnitCount", "B"): "40",
              P.format("PrincipalComponents", "C"): "licensed subcontractors"}
    refused, cells = ps._product_rows_to_refuse(mapped, S126, {}, set(mapped))
    assert refused == {}
    assert cells == {P.format("AnnualGrossSalesAmount", "A"), P.format("UnitCount", "A"),
                     P.format("PrincipalComponents", "C")}
    # a name the AI did not write is never judged, and its row stands
    typed = {P.format("ProductName", "A"): "91580", P.format("UnitCount", "A"): "3"}
    assert ps._product_rows_to_refuse(typed, S126, _SCHEDULE, {P.format("UnitCount", "A")}) == ({}, set())


@pytest.mark.parametrize("facts", [None, {}, {"gl_class_code_schedule": None},
                                   {"gl_class_code_schedule": {"value": "91580"}},
                                   {"gl_class_codes": {"value": ["91580 Contractors - Executive Supervisors", 91585, None]},
                                    "wc_class_codes": {"value": [{"code": "5645", "description": "Carpentry - detached dwellings"}]},
                                    "gl_class_codes_by_location": {"value": [{"location": "1", "codes": ["91580"]}, "x"]}}])
def test_malformed_or_missing_schedules_never_raise(facts):
    field = P.format("ProductName", "A")
    refused, _ = ps._product_rows_to_refuse({field: "91585"}, S126, facts, {field})
    assert refused.get(field) in ("PRODUCT_IS_A_RATING_CLASS", "PRODUCT_NAME_IS_A_NUMBER")
    codes, words = ps._rating_class_identities(facts)
    if facts and facts.get("gl_class_codes"):
        assert {"91580", "91585", "5645"} <= codes
        assert ("contractors", "executive", "supervisors") in words
        assert ps._names_a_rating_class("Carpentry - Detached Dwellings", codes, words)


@pytest.mark.parametrize("seed", range(40))
def test_any_spelling_of_a_class_is_refused_and_a_product_is_not(seed):
    rng = random.Random(seed)
    cls = rng.choice([r["classification"] for r in _SCHEDULE["gl_class_code_schedule"]["value"]])
    words = re.findall(r"[A-Za-z0-9]+", cls)
    n = rng.randint(3, len(words))
    piece = words[:n] if rng.random() < 0.5 else words[-n:]
    joiner = rng.choice([" ", " - ", "  ", ","])
    spelled = joiner.join(w.upper() if rng.random() < 0.3 else w for w in piece)
    field = P.format("ProductName", rng.choice("ABC"))
    refused, _ = ps._product_rows_to_refuse({field: spelled}, S126, _SCHEDULE, {field})
    assert refused.get(field) == "PRODUCT_IS_A_RATING_CLASS", spelled
    product = rng.choice(["Kitchen cabinets", "Precast concrete steps", "Custom millwork",
                          "LED fixtures", "Roof trusses"])
    assert ps._product_rows_to_refuse({field: product}, S126, _SCHEDULE, {field})[0] == {}


@pytest.mark.parametrize("value, is_line", [
    ("Commercial General Liability Coverage Form", True), ("Business Auto Coverage Form", True),
    ("COMMERCIAL GENERAL LIABILITY COVERAGE PART", True), ("Commercial Umbrella Endorsement", True),
    ("Commercial Property Form", True), ("General Liability", True),
    ("Kitchen cabinets", False), ("Form 2000 widgets", False), ("Coverage Form", False),
])
def test_a_line_s_own_document_title_is_the_line(value, is_line):
    assert ps._is_line_of_business_name(value) is is_line


# ══ The cover's score paragraph: the package's own tier and routing ══════════

_LIVE_PARAGRAPH = (
    "The Package SQS is 63/100, reflecting a moderate-quality submission with solid structural "
    "elements but notable underwriting gaps. The strongest form in the package is ACORD 126 with a "
    "score of 74, which supports acceptable exposure and structural completeness. The submission "
    "also lacks key contextual underwriting details, which reduces confidence and drives the "
    "package into a Needs Work tier with priority review routing.")
_ONE_FORM = [("ACORD_126", 74)]


def test_the_live_paragraph_falls_back_to_the_true_one():
    out = cs._checked_sqs_reasoning(_LIVE_PARAGRAPH, _ONE_FORM, 63, True, "standard_review")
    assert out == "The package SQS is 63/100. ACORD 126 scored 74. Scores below 75 indicate fields requiring manual review."


@pytest.mark.parametrize("text, routing, kept", [
    (_LIVE_PARAGRAPH.replace("Needs Work tier with priority review", "Major Gaps tier with standard review"),
     "standard_review", True),
    ("The narrative needs work and the package has major gaps. ACORD 126 sits in the Needs Work tier.",
     "standard_review", True),                      # prose, and a FORM's tier
    ("Weak loss history will hold the package back.", "standard_review", True),
    ("The package needs Full Review before quoting.", "standard_review", False),
    ("The package is routed to Standard Review.", None, False),     # a routing nobody supplied
    ("The package sits in the Not Ready tier.", "standard_review", False),
])
def test_a_package_sentence_states_only_the_package_s_tier_and_routing(text, routing, kept):
    out = cs._checked_sqs_reasoning(text, _ONE_FORM, 63, True, routing)
    assert (out == text) is kept


def test_the_prompt_carries_the_package_s_own_tier_and_routing(monkeypatch):
    seen = {}

    async def _fake_chat(model, messages, max_tokens=0):
        seen["prompt"] = messages[0]["content"]
        return json.dumps({"narrative": "N.", "sqs_reasoning": _LIVE_PARAGRAPH})

    async def _miss(_key):
        return None

    async def _store(_key, _val):
        return None

    monkeypatch.setattr(cs, "groq_chat", _fake_chat)
    monkeypatch.setattr(cs, "_cache_get", _miss)
    monkeypatch.setattr(cs, "_cache_set", _store)
    out = asyncio.run(cs.generate_ai_cover_narrative(
        {}, {}, {"ACORD_126": {"sqs_score": 74, "routing_decision": "priority_review"}},
        ["ACORD_126"], "Org", user=None, package_score=63, package_routing="standard_review"))
    assert "Package grade / tier / routing: D / Major Gaps / Standard review" in seen["prompt"]
    assert "must be the package's own" in seen["prompt"]
    assert "Needs Work tier" not in out["sqs_reasoning"]       # the model's slip never prints
    # a legacy caller with no package score gets neither line
    asyncio.run(cs.generate_ai_cover_narrative(
        {}, {}, {"ACORD_126": {"sqs_score": 74}}, ["ACORD_126"], "Org", user=None))
    assert "Package grade / tier / routing" not in seen["prompt"]


def test_both_cover_routes_pass_the_package_routing():
    src = (BACKEND / "routes" / "download_routes.py").read_text(encoding="utf-8")
    assert src.count('package_routing=_pkg_now.get("routing_decision")') == 2


# ══ The pending-edits note: plain pink text (owner, 1 Oct 2026) ═══════════════

def test_the_pending_edits_note_is_plain_pink_text():
    src = _src(ACORD_MODAL)
    i = src.index("You have unsaved field edits. These scores are from the last save. Save to update.")
    block = src[src.rindex("{pendingEdits && (", 0, i):i]
    assert 'color: "#E61B84"' in block
    assert "border" not in block and "borderRadius" not in block and "background" not in block
    # the card around the bars no longer turns amber either
    assert 'border: `1px solid ${pendingEdits ? "#fde68a" : "#e2e8f0"}`' not in src
