"""Orbin items 9 / 10 (14 Sep) - asserted through what the client actually
SEES, not only the primitives the fixes live in (standing rule: fix - and test
- the layer the screen reads; three fixes in one week passed their unit tests
and changed nothing on screen).

  * the cover page PDF (ReportLab and its plain-text fallback) and the cover
    narrative's no-LLM fallback;
  * the scorer's own Applicant Info sub-row;
  * ACORD 137 through `map_facts_to_form`, post-fill guards included - fuzzed;
  * the questionnaire's not-applicable filter - fuzzed.
"""

import asyncio
import io
import os
import random
import re
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from services import auto_symbols as sym  # noqa: E402
from services import cover_service  # noqa: E402
from services import state_auto_grid as sag  # noqa: E402
from services.arq_service import _drop_not_applicable_questions  # noqa: E402
from services.cover_service import _build_cover_page_fallback, build_cover_page_pdf  # noqa: E402
from services.line_presence import ABSENT, line_in_submission  # noqa: E402
from services.pdf_service import _DECLARED_ABSENT_LINE_FAMILIES, map_facts_to_form  # noqa: E402
from services.sqs_service import _compute_category_breakdown  # noqa: E402

from test_coverage_presence_14sep import (  # noqa: E402
    CARRIED, ORBIN_FLAGS, _orbin_facts, _with_borrowed_numbers,
)
from test_state_auto_grid_14sep import FORMS, _random_facts, _schema  # noqa: E402

_ORBIN_FORMS = ["ACORD_125", "ACORD_126", "ACORD_127", "ACORD_131"]
# Every name the client said the cover must NOT print (plus the other menu
# lines the live extraction captured).
_PHANTOM_LINES = ("Property", "Crime", "Fidelity", "Workers", "Farm", "Liquor",
                  "Employment", "Protective", "Pollution", "Equipment Breakdown",
                  "Underground", "Product Withdrawal", "Electronic Data")


def _pdf_text(pdf_bytes):
    pdfplumber = pytest.importorskip("pdfplumber")
    with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
        return "\n".join((p.extract_text() or "") for p in pdf.pages)


def _cover_lob_cell(text):
    """The lines of business as whichever cover the client gets prints them:
    the ReportLab table cell (its label wraps "LINES OF" / "BUSINESS" beside
    the value's own wrapped lines, so the label's second word is removed), or
    the plain-text fallback's "Lines of Business:" line when ReportLab fails."""
    m = re.search(r"LINES OF(.*?)EMPLOYEES", text, re.S)
    if m:
        return re.sub(r"\s+", " ", re.sub(r"\bBUSINESS\b", " ", m.group(1))).strip()
    m = re.search(r"Lines of Business:([^\n]*)", text)
    assert m, text[:600]
    return m.group(1).strip()


# ─────────────────────────────────────────────────────────────────────────────
# The cover page
# ─────────────────────────────────────────────────────────────────────────────
@pytest.mark.parametrize("facts_of", [_orbin_facts, _with_borrowed_numbers],
                         ids=["merged-rows", "per-document-rows-with-borrowed-numbers"])
def test_the_cover_pdf_prints_only_the_lines_orbin_carries(facts_of):
    pdf = build_cover_page_pdf(
        facts=facts_of(), flags=dict(ORBIN_FLAGS), sqs_results={},
        form_ids=list(_ORBIN_FORMS), org_name="ThinkSmith Agency",
        narrative="Neutral narrative.", ai_block={}, sqs_reasoning="", user=None,
        hard_stops=[], soft_stops=[])
    cell = _cover_lob_cell(_pdf_text(pdf))
    for line in CARRIED:
        assert line in cell, cell
    for phantom in _PHANTOM_LINES:
        assert phantom.lower() not in cell.lower(), (phantom, cell)


def test_the_plain_text_fallback_prints_the_same_lines():
    pdf = _build_cover_page_fallback(_with_borrowed_numbers(), {}, list(_ORBIN_FORMS),
                                     "ThinkSmith Agency", "Neutral.", {}, "now",
                                     flags=dict(ORBIN_FLAGS))
    assert f"(Lines of Business: {', '.join(CARRIED)}) Tj".encode("latin-1") in pdf


def test_the_cover_narrative_fallback_names_only_carried_lines(monkeypatch):
    async def _no_llm(*_a, **_k):
        raise RuntimeError("no LLM in tests")

    async def _no_cache(*_a, **_k):
        return None

    monkeypatch.setattr(cover_service, "groq_chat", _no_llm)
    monkeypatch.setattr(cover_service, "_cache_get", _no_cache)
    monkeypatch.setattr(cover_service, "_cache_set", _no_cache)
    out = asyncio.run(cover_service.generate_ai_cover_narrative(
        _with_borrowed_numbers(), dict(ORBIN_FLAGS), {}, list(_ORBIN_FORMS), "ThinkSmith Agency"))
    assert f"covers {', '.join(CARRIED)}" in out["narrative"]
    for phantom in _PHANTOM_LINES:
        assert phantom not in out["narrative"], phantom
    lite = asyncio.run(cover_service.generate_lite_cover_narrative(
        _with_borrowed_numbers(), dict(ORBIN_FLAGS), {"sqs_score": 80, "grade": "B"}, [], [],
        "ThinkSmith Agency"))
    assert f"covering {', '.join(CARRIED)}" in lite["narrative"]


# ─────────────────────────────────────────────────────────────────────────────
# The scorer's Applicant Info sub-row
# ─────────────────────────────────────────────────────────────────────────────
def _applicant_info_score(facts, flags):
    breakdown = _compute_category_breakdown(facts, flags)
    for _pillar, cats in breakdown.items():
        for key, cat in (cats or {}).items():
            if "applicant" in str(key).lower() or "applicant" in str((cat or {}).get("label", "")).lower():
                return cat["score"]
    raise AssertionError(f"no Applicant Info category in {list(breakdown)}")


def test_the_scorer_counts_lines_of_business_only_when_one_is_carried():
    # Identical bases: only the lines-of-business evidence differs, so the
    # difference is exactly that one item of the row's five (20 points).
    base = {"applicant_name": "ORBIN CONTRACTING LLC",
            "mailing_address": "4800 DAHLIA ST # D13, DENVER CO 80216-3121"}
    orbin = _orbin_facts()
    carried = _applicant_info_score(
        {**base, "lines_of_business": orbin["lines_of_business"],
         "coverage_lines": orbin["coverage_lines"]}, dict(ORBIN_FLAGS))
    denied_only = _applicant_info_score(
        {**base, "lines_of_business": ["Property", "Workers' Compensation", "Crime and Fidelity"]},
        {"has_property_coverage": False, "has_workers_comp": False, "has_crime": False})
    menu_only = _applicant_info_score(
        {**base, "lines_of_business": orbin["lines_of_business"],
         "coverage_lines": [r for r in orbin["coverage_lines"]
                            if not str(r.get("premium") or "").strip()
                            and not str(r.get("policy_number") or "").strip()]},
        dict(ORBIN_FLAGS))
    legacy = _applicant_info_score(
        {**base, "lines_of_business": ["General Liability"]}, {})
    assert carried - denied_only == 20
    assert legacy == carried                      # no evidence either way: as today
    assert menu_only <= carried


# ─────────────────────────────────────────────────────────────────────────────
# ACORD 137 through the real fill path, fuzzed
# ─────────────────────────────────────────────────────────────────────────────
def _ticked(v):
    return str(v or "").strip().lower() in ("yes", "y", "/yes", "on", "x", "true", "1")


def _blank(v):
    return str(v or "").strip().lower() in ("", "no", "off", "none", "/off")


_NUM_RE = re.compile(r"\d[\d,]*(?:\.\d+)?")


def _numbers(text):
    """Every amount printed in `text`, as a whole-dollar string, so "$1,000,000",
    "1000000" and "$1,000,000.00" compare equal."""
    return {str(int(float(n.replace(",", "")))) for n in _NUM_RE.findall(str(text or ""))}


@pytest.mark.parametrize("seed", range(3))
def test_fuzz_137_through_map_facts_to_form(seed):
    rng = random.Random(5137 + seed)
    for i in range(10):
        form_id = FORMS[i % 2]
        facts = _random_facts(rng)
        mapped, _conf = map_facts_to_form(dict(facts), _schema(form_id), form_id=form_id, raw_text="")
        fams = sag.field_families(form_id)
        for f, v in mapped.items():
            if not f.startswith("Vehicle_") or f not in fams:
                continue
            m = sag._GRID_RE.match(f)
            if m and _ticked(v) and m.group("word") != "OtherSymbol" and m.group("kind") == "Indicator":
                family = fams[f]
                coverage = sag.ROW_COVERAGE[family].get(m.group("row"))
                number = next((s.number for s in sym.BY_FAMILY[family].values()
                               if s.word == m.group("word")), None)
                if coverage is not None and number is not None:
                    assert number in sag._designated(facts, coverage), (f, number)
            # What the PDF prints is what the grid decided: an owned blank or a
            # box asked of the document is never filled by a later pass (alias
            # stamping, a legacy resolver), and a value prints as decided. A
            # page the grid does not decide runs today's path through the same
            # money formatter (fixed 15 Sep 2026 - tests below).
            decided = sag.resolve(form_id, f, facts)
            if decided is sag.SKIP:
                continue
            if decided is None or decided == sag.ASK:
                assert _blank(v), (f, v, "decided blank or asked, yet stamped")
            elif decided in ("Yes", "No"):
                assert _ticked(v) == (decided == "Yes"), (f, v, decided)
            else:
                # Compared as the formatter PRINTS the decided value: "$1M"
                # prints 1,000,000. The raw-digit comparison only held while the
                # formatter printed "$1M" as "1".
                from services.display_canonicalizer import canonicalize_currency
                assert _numbers(v) <= _numbers(canonicalize_currency(decided)), (f, v, decided)
        for letter in sag.LIMIT_BASIS_ROW:
            assert not (_ticked(mapped.get(f"Vehicle_CombinedSingleLimit_LimitIndicator_{letter}"))
                        and _ticked(mapped.get(f"Vehicle_BodilyInjury_EachPersonLimitIndicator_{letter}")))


# ─────────────────────────────────────────────────────────────────────────────
# The questionnaire filter, fuzzed
# ─────────────────────────────────────────────────────────────────────────────
# These two were strict xfails pinning the held money-formatter defect
# (`display_canonicalizer.canonicalize_currency` kept only the digits: '$1M'
# printed '1', '$1,000,000 / $2,000,000' printed '10,000,002,000,000').
# Fixed 15 Sep 2026 on the owner's go-ahead; they now assert the fix.
_AUTO_SYMBOLS = [{"coverage": "liability", "symbols": [1]},
                 {"coverage": "medical payments", "symbols": [2]}]


def test_the_137_prints_shorthand_limits_at_their_real_size():
    facts = {"has_auto_coverage": True, "auto_covered_symbols": _AUTO_SYMBOLS,
             "auto_liability_limit": "$1M", "auto_med_pay_limit": "$5K"}
    mapped, _ = map_facts_to_form(dict(facts), _schema("ACORD_137_CO"),
                                  form_id="ACORD_137_CO", raw_text="")
    for box, real in (("Vehicle_BodilyInjury_PerPersonLimitAmount_A", "1000000"),
                      ("Vehicle_MedicalPayments_PerPersonLimitAmount_A", "5000")):
        printed = str(mapped.get(box) or "")
        assert _numbers(printed) == {real} or re.search(r"\d\s*[KkMm]\b", printed), (box, printed)


def test_two_amounts_are_never_glued_into_one_number():
    two = "$1,000,000 / $2,000,000"
    for fid in ("ACORD_126", "ACORD_25", "ACORD_131"):
        mapped, _ = map_facts_to_form({"gl_each_occurrence": two}, _schema(fid),
                                      form_id=fid, raw_text="")
        for box, v in mapped.items():
            if v and re.search(r"\d", str(v)) and "EachOccurrence" in box:
                assert _numbers(v) <= {"1000000", "2000000"}, (fid, box, v)
    # A 137 page the grid does not decide (a motor carrier package says nothing
    # about its Business Auto page) runs today's limit resolver - same formatter.
    four = "$250,000/$500,000/$100,000/$50,000"
    mapped, _ = map_facts_to_form(
        {"has_motor_carrier_coverage": True, "has_truckers_coverage": False,
         "auto_split_limits": True, "auto_bi_per_person": four},
        _schema("ACORD_137_CO"), form_id="ACORD_137_CO", raw_text="")
    v = mapped.get("Vehicle_BodilyInjury_PerPersonLimitAmount_A")
    assert _numbers(v) <= {"250000", "500000", "100000", "50000"}, v


_WC_FAMILY_RE = _DECLARED_ABSENT_LINE_FAMILIES[0][0]
_WC_BOXES = sorted({f for fid in ("ACORD_131", "ACORD_25", "ACORD_130")
                    for f in _schema(fid) if _WC_FAMILY_RE.match(f)})
_MENTION_ONLY_BOXES = [
    "AdditionalInterest_WorkersCompensationCarriedCode_A",
    "CommercialVehicleLineOfBusiness_AnyDriversNotCoveredWorkersCompensationExplanation_A",
]
_WC_FACTS = ["wc_xmod", "wc_payroll_period", "employers_liability_limits", "schedule::wc_class_codes"]
_UNRELATED = [("umbrella_limit", "umbrella_limit"), ("auto_liability_limit", "auto_liability_limit"),
              ("applicant_name", "applicant_name"), ("gl_aggregate", "gl_aggregate"),
              ("Vehicle_BusinessAutoSymbol_OneIndicator_A", None), ("NamedInsured_FullName_A", None)]
_POOL_FORMS = ["ACORD_125", "ACORD_126", "ACORD_127", "ACORD_131", "ACORD_25"]
_GRANTED_OTHER_LINES = [
    {"line": "General Liability", "premium": "$3,954.00", "policy_number": "BBC7263"},
    {"line": "Inland Marine", "premium": "$300.00", "policy_number": "6C7-40-02---26"},
    {"line": "Automobile", "premium": "$2,991.00", "policy_number": "6E7-40-02---26"},
    {"line": "Umbrella", "premium": "$3,418.00", "policy_number": "6J7-40-02---26"},
]


def _question(rng, kind):
    forms = rng.sample(_POOL_FORMS, rng.randint(1, 3))
    if kind == "wc_box":
        return {"field_name": rng.choice(_WC_BOXES), "form_ids": forms, "_kind": kind}
    if kind == "mention":
        return {"field_name": rng.choice(_MENTION_ONLY_BOXES), "form_ids": forms, "_kind": kind}
    if kind == "wc_fact":
        key = rng.choice(_WC_FACTS)
        return {"field_name": key, "_canonical_key": None if key.startswith("schedule::") else key,
                "form_ids": forms, "_kind": kind}
    name, canon = rng.choice(_UNRELATED)
    return {"field_name": name, "_canonical_key": canon, "form_ids": forms, "_kind": kind}


@pytest.mark.parametrize("seed", range(6))
def test_fuzz_the_questionnaire_never_drops_a_question_it_should_ask(seed):
    rng = random.Random(3130 + seed)
    for _ in range(80):
        rows = list(_GRANTED_OTHER_LINES) if rng.random() < 0.7 else _GRANTED_OTHER_LINES[:rng.randint(0, 2)]
        wc_granted = rng.random() < 0.25
        wc_literal_denial = (not wc_granted) and rng.random() < 0.2
        if wc_granted:
            rows = rows + [{"line": "Workers Compensation", "premium": "$12,400", "policy_number": "WC-1"}]
        if wc_literal_denial:
            rows = rows + [{"line": "Workers Compensation", "premium": "No Coverage"}]
        facts = {"coverage_lines": rows}
        if rng.random() < 0.3:
            facts["dec_page_entries"] = [{"label": "Section 6 Workers' Compensation Premium",
                                          "value": "No Coverage",
                                          "line_of_business": "Workers' Compensation"}]
        if rng.random() < 0.2:
            facts["wc_xmod"] = "0.95"
        flags = {}
        said = rng.choice([True, False, None, "missing"])
        if said != "missing":
            flags["has_workers_comp"] = said
        form_ids = list(_POOL_FORMS) + (["ACORD_130"] if rng.random() < 0.25 else [])

        kinds = ["unrelated"] + [rng.choice(["wc_box", "mention", "wc_fact", "unrelated"])
                                 for _ in range(rng.randint(1, 8))]
        questions = [_question(rng, k) for k in kinds]
        kept = _drop_not_applicable_questions(list(questions), facts, list(form_ids), flags)

        it = iter(questions)                       # a subsequence, order kept
        assert all(any(k is q for q in it) for k in kept)
        kept_ids = {id(q) for q in kept}
        # A question that is not about WC at all is never touched.
        for q in questions:
            if q["_kind"] in ("unrelated", "mention"):
                assert id(q) in kept_ids, (q, facts, flags)
        # Applying for WC (ACORD 130) means every WC question is asked.
        if "ACORD_130" in form_ids:
            assert len(kept) == len(questions), (facts, flags)
            continue
        wc = line_in_submission("workers_comp", facts, flags, form_ids)
        for q in questions:
            if q["_kind"] != "wc_fact":
                continue
            if wc == ABSENT:
                assert id(q) not in kept_ids, (q["field_name"], facts, flags)
            elif not wc_literal_denial:
                assert id(q) in kept_ids, (q["field_name"], wc, facts, flags)
