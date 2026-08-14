"""Run-3 fixes, 2026-08-14: the three defects the third verified run shipped.

1. DESCRIPTION OF PRIMARY OPERATIONS held "Contractors' equipment coverage and
   installation floater coverage are described, including coverage for ..." -
   a sentence about the POLICY's grants stamped as what the BUSINESS does.
   Run-to-run jitter let the coverage-meta candidate out-score the genuine
   classification text this time. Fixed by a demote-never-discard rule in the
   narrative merge: the policy describing itself may not win while a genuine
   candidate exists.
2. The page-1 mailing address printed as "4800 Dahlia St # D13 Denver CO
   80216-3121" in the STREET box with the city/zip boxes ALSO filled - dec
   pages print addresses as one comma-free run, and _parse_address only split
   on commas. Fixed with structure-anchored tail recovery: a state+zip tail
   is accepted only when the 2-letter token and the ZIP corroborate each
   other, and the city is pulled only when a UNIT designator anchors the end
   of the street ("# D13", "STE 400").
3. PAYMENT PLAN = "AN" on every run - a code invented from "Audit Period:
   Annual" (the GL's AUDIT term). A code is an abbreviation of a printed
   word, so no verbatim gate can see the invention. Fact-or-blank resolver,
   same shape as the deposit and fax boxes.
"""
import json
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("OPENAI_API_KEY", "sk-offline")

import services.extraction_service as es  # noqa: E402
import services.pdf_service as ps  # noqa: E402
from utils.helpers import _parse_address  # noqa: E402

BACKEND = os.path.join(os.path.dirname(__file__), "..")


def _schema(form):
    with open(os.path.join(BACKEND, "forms_schemas", f"{form}_schema.json"),
              encoding="utf-8") as fh:
        return json.load(fh)


def _merge(*facts_per_chunk):
    partials = [
        {"_chunk_idx": i,
         "facts": {k: {"value": v, "confidence": "ai_low"} for k, v in d.items()}}
        for i, d in enumerate(facts_per_chunk)
    ]
    return es._merge_list_fields(partials, [])["facts"]


# ── 1. The policy describing itself is not an operations description ─────────

_COVERAGE_META = ("Contractors' equipment coverage and installation floater "
                  "coverage are described, including coverage for contractors' "
                  "equipment, installation or construction project materials, "
                  "supplies, machinery, fixtures, and equipment.")
_GENUINE_OPS = ("Contractors - Executive Supervisors or Executive "
                "Superintendents; Contrctrs-sub work-in connection "
                "w/constrctn,recon,repr,erctn of buildings - NOC")


def test_the_live_coverage_description_loses_to_the_genuine_operations():
    """The literal run-3 winner must lose to the literal classification text,
    whatever order the chunks arrive in."""
    for order in ((_COVERAGE_META, _GENUINE_OPS), (_GENUINE_OPS, _COVERAGE_META)):
        out = _merge({"operations_description": order[0]},
                     {"operations_description": order[1]})
        chosen = out["operations_description"]
        chosen = chosen.get("value") if isinstance(chosen, dict) else chosen
        assert chosen == _GENUINE_OPS, chosen


def test_a_coverage_description_alone_still_stamps():
    """Demote, never discard: with no genuine rival the meta candidate is
    still the best available statement and must not blank the fact."""
    out = _merge({"operations_description": _COVERAGE_META})
    chosen = out["operations_description"]
    chosen = chosen.get("value") if isinstance(chosen, dict) else chosen
    assert chosen == _COVERAGE_META


def test_the_meta_regex_separates_the_live_pair():
    assert es._COVERAGE_META_RE.search(_COVERAGE_META)
    assert not es._COVERAGE_META_RE.search(_GENUINE_OPS)
    assert not es._COVERAGE_META_RE.search("COMMERCIAL GENERAL CONTRA")


# ── 2. Comma-free address tails ──────────────────────────────────────────────

def test_the_fully_fused_comma_free_address_decomposes():
    p = _parse_address("4800 DAHLIA ST # D13 DENVER CO 80216-3121")
    assert p["line1"] == "4800 DAHLIA ST # D13"
    assert p["city"] == "DENVER"
    assert p["state"] == "CO"
    assert p["zip"] == "80216-3121"


def test_the_live_two_part_fused_city_decomposes():
    """The run-3 page-1 shape: '..., CO 80216-3121' parsed state/zip but left
    'DENVER' fused on the street line while the city box also filled."""
    p = _parse_address("4800 DAHLIA ST # D13 DENVER, CO 80216-3121")
    assert p["line1"] == "4800 DAHLIA ST # D13"
    assert p["city"] == "DENVER"


def test_the_producers_suite_anchored_city_decomposes():
    p = _parse_address("9780 S MERIDIAN BLVD STE 400 ENGLEWOOD, CO 80112-6072")
    assert p["line1"] == "9780 S MERIDIAN BLVD STE 400"
    assert p["city"] == "ENGLEWOOD"


def test_a_directional_is_never_mistaken_for_a_state():
    """'AVE NW 20500': NW is not the state the DC zip implies, so nothing is
    extracted - the corroboration requirement is the whole safety argument."""
    p = _parse_address("1600 PENNSYLVANIA AVE NW 20500")
    assert p["line1"] == "1600 PENNSYLVANIA AVE NW 20500"
    assert not p.get("zip")


def test_no_unit_anchor_means_no_city_guess():
    """'123 OAK PARK DENVER' - the street/city boundary is not decidable
    without a unit designator, so the city stays fused rather than guessed."""
    p = _parse_address("123 OAK PARK DENVER, CO 80216")
    assert p["line1"] == "123 OAK PARK DENVER"
    assert not p.get("city")
    assert p["state"] == "CO"


def test_standard_three_part_addresses_are_untouched():
    p = _parse_address("4800 Dahlia St # D13, Denver, CO 80216-3121")
    assert p["line1"] == "4800 Dahlia St # D13"
    assert p["city"] == "Denver"
    assert p["state"] == "CO"
    assert p["zip"] == "80216-3121"


# ── 3. PAYMENT PLAN is fact-or-blank ─────────────────────────────────────────

_PAY_FIELD = "Policy_Payment_PaymentScheduleCode_A"


def test_the_invented_an_code_is_structurally_impossible_now():
    """No payment_plan fact means the box is an authoritative blank - the
    model's 'AN' (derived from 'Audit Period: Annual') never reaches paper."""
    schema = _schema("ACORD_125")
    mapped, _ = ps.map_facts_to_form(
        {}, schema, "ACORD_125",
        raw_text="Audit Period: Annual",
        pre_filled_gpt={"filled_values": {_PAY_FIELD: "AN"},
                        "raw_text_fields": set(), "question_grounding": {}})
    assert mapped.get(_PAY_FIELD) is None


def test_a_genuinely_printed_payment_plan_stamps():
    schema = _schema("ACORD_125")
    mapped, _ = ps.map_facts_to_form(
        {"payment_plan": "MONTHLY"}, schema, "ACORD_125",
        raw_text="Payment Plan: Monthly", pre_filled_gpt=None)
    assert str(mapped.get(_PAY_FIELD)).upper().startswith("MONTHLY")


def test_extraction_now_asks_for_the_payment_plan():
    """The resolver's fact half must have a source, or fact-or-blank would
    quietly mean always-blank even for documents that print a plan."""
    assert '"payment_plan"' in es._EXTRACT_SCHEMA


# ── 4. The applicant's nameplate offered as Yes evidence (run 4) ─────────────
# ACORD 125 Q3 (flammables) = Y and Q6 (abuse/molestation claims) = Y, both
# carried by "BUSINESS DESC: COMMERCIAL GENERAL CONTRA" on the EXPLANATION
# path. The labelled-fact echo existed for exactly this string but tests FACT
# equality, and this run's contractor_type merged to the EXPANDED "Commercial
# General Contractor" - fact jitter blinded it. The verified index does not
# jitter: the entry 'BUSINESS DESC' = 'COMMERCIAL GENERAL CONTRA' is
# applicant-owned, and who the applicant IS can never evidence what HAPPENED.

_NAMEPLATE_FACTS = {
    "contractor_type": "Commercial General Contractor",   # the drifted merge
    "dec_page_entries": [
        {"label": "BUSINESS DESC", "value": "COMMERCIAL GENERAL CONTRA",
         "owner": "applicant"},
        {"label": "INSURED IS", "value": "LLC", "owner": "applicant"},
        {"label": "Named Insured", "value": "ORBIN CONTRACTING LLC",
         "owner": "applicant"},
    ],
}


def test_the_live_nameplate_explanation_is_an_artifact_despite_fact_drift():
    dec_lines = ps._dec_coverage_line_set(_NAMEPLATE_FACTS)
    assert ps._is_coverage_artifact_text(
        "BUSINESS DESC: COMMERCIAL GENERAL CONTRA", dec_lines, _NAMEPLATE_FACTS)
    assert ps._is_coverage_artifact_text(
        "COMMERCIAL GENERAL CONTRA", dec_lines, _NAMEPLATE_FACTS)


def test_short_codes_keep_their_evidence_status():
    """'INSURED IS: LLC' is pinned legitimate evidence - the 8-char floor is
    what keeps short real answers alive."""
    assert not ps._is_applicant_attribute_echo("LLC", _NAMEPLATE_FACTS)
    dec_lines = ps._dec_coverage_line_set(_NAMEPLATE_FACTS)
    assert not ps._is_coverage_artifact_text(
        "INSURED IS: LLC", dec_lines, _NAMEPLATE_FACTS)


def test_a_real_sentence_is_never_a_nameplate_echo():
    """Equality-only: a genuine statement that merely mentions the business
    keeps its verb and its evidence status."""
    assert not ps._is_applicant_attribute_echo(
        "The applicant stores acetylene and oxygen cylinders in a locked cage",
        _NAMEPLATE_FACTS)


def test_the_live_pair_dies_end_to_end():
    """The literal run-4 shape through the real gate: Y + nameplate
    explanation + nameplate quote must both blank, on both questions."""
    schema = _schema("ACORD_125")
    exp3 = "CommercialPolicy_AnyExposureToFlammableExplosivesChemicalsExplanation_A"
    exp6 = ("CommercialPolicy_PastLossesClaimsRelatingSexualAbuse"
            "DiscriminationNegligentHiringExplanation_A")
    pairs = {e: q for q, e in ps._question_explanation_pairs(schema).items()}
    code3, code6 = pairs[exp3], pairs[exp6]     # ABC / AAD question codes
    assert code3 in schema and code6 in schema, "field names moved - update test"
    lit = "BUSINESS DESC: COMMERCIAL GENERAL CONTRA"
    mapped, _ = ps.map_facts_to_form(
        dict(_NAMEPLATE_FACTS), schema, "ACORD_125",
        raw_text="BUSINESS DESC: COMMERCIAL GENERAL CONTRA  INSURED IS: LLC",
        pre_filled_gpt={"filled_values": {code3: "Y", exp3: lit,
                                          code6: "Y", exp6: lit},
                        "raw_text_fields": set(),
                        "question_grounding": {code3: lit, code6: lit}})
    assert mapped.get(code3) is None, mapped.get(code3)
    assert mapped.get(exp3) is None
    assert mapped.get(code6) is None
    assert mapped.get(exp6) is None
