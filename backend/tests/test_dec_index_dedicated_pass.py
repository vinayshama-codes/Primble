"""The dedicated declarations-index pass, and the two root causes beside it.

THE INDEX. `dec_page_entries` was one key among ~170 in the main extraction
schema, and the model budgets its answer across all of them: ~19 entries per
chunk against a 150 allowance and a 16,000-token cap, neither binding. 250
entries recorded from ~30 declarations pages carrying an estimated ~750. The
index is what Stage A of LLM call 2 reads first, so a thin index is a direct
loss of fill quality - and it is why "Limited Pollution Coverage - Work Sites
$150" kept coming back: guards keyed off the index are blind to what it never
recorded. Attention is the constraint, so the fix is SEPARATION.

THE TWO ROOT CAUSES, stated once by rule instead of once per box:
    a PERCENTAGE nothing states  - 74 fields over 8 forms
    a ROW about a party who is not on the form - ACORD's own tooltip convention

THE MISSING STOP. Every date rule looked at the EFFECTIVE date. Nothing
compared the EXPIRATION date to today, so a package whose term ended last month
printed both dates under "PROPOSED EFF/EXP DATE" and raised nothing.
"""
import asyncio
import glob
import json
import os
import re
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("OPENAI_API_KEY", "sk-offline")

import services.extraction_service as es                          # noqa: E402
import services.pdf_service as ps                                 # noqa: E402

BACKEND = os.path.join(os.path.dirname(__file__), "..")


def _schema(form):
    with open(os.path.join(BACKEND, "forms_schemas", f"{form}_schema.json"),
              encoding="utf-8") as fh:
        return json.load(fh)


# ── 1. Routing: only declarations-dense chunks pay for the extra call ────────

_DEC = ("COMMON POLICY DECLARATIONS\nNamed Insured: ORBIN CONTRACTING LLC\n"
        "Policy Number: 6E7-40-02---26\nEffective Date: 07/15/25\n"
        "Total Premium: $10,663.00\nLiability $3,954.00\n")
_WORDING = ("SECTION II - WHO IS AN INSURED. If you are designated in the "
            "Declarations as an individual, you and your spouse are insureds, "
            "but only with respect to the conduct of a business of which you "
            "are the sole owner.")


def test_the_router_separates_dec_pages_from_policy_wording():
    """The whole cost argument rests on this. Same scorer the retrieval filter
    already trusts."""
    assert es.declarations_authority(_DEC) >= es._DEC_INDEX_MIN_AUTHORITY
    assert es.declarations_authority(_WORDING) < es._DEC_INDEX_MIN_AUTHORITY


def test_a_package_of_pure_wording_costs_nothing():
    """No chunk clears the bar, so no call is made at all."""
    chunks = [(_WORDING, 0, len(_WORDING)) for _ in range(6)]
    assert asyncio.run(es._harvest_dec_index(chunks)) == []


def test_the_kill_switch_stops_the_pass(monkeypatch):
    monkeypatch.setattr(es, "_DEC_INDEX_DEDICATED_PASS", False)
    assert asyncio.run(es._harvest_dec_index([(_DEC, 0, len(_DEC))])) == []


def test_the_chunk_cap_bounds_the_cost(monkeypatch):
    """A pathological package cannot buy unbounded calls."""
    # Off by default since 2026-08-23 (Round 8) - switched on explicitly here
    # because this test exercises the machinery, not the product decision.
    monkeypatch.setattr(es, "_DEC_INDEX_DEDICATED_PASS", True)
    seen = []

    async def _fake(model, messages, max_tokens=0):
        seen.append(messages[1]["content"])
        return '{"dec_page_entries": []}'

    monkeypatch.setattr(es, "groq_chat", _fake)
    monkeypatch.setattr(es, "_DEC_INDEX_MAX_CHUNKS", 3)
    asyncio.run(es._harvest_dec_index([(_DEC, 0, 1)] * 20))
    assert len(seen) == 3


def test_a_failed_index_call_never_breaks_extraction(monkeypatch):
    async def _boom(*a, **k):
        raise RuntimeError("429")
    monkeypatch.setattr(es, "groq_chat", _boom)
    assert asyncio.run(es._harvest_dec_index([(_DEC, 0, 1)])) == []


# ── 2. The prompt asks for the one thing, and forbids the known failure ──────

def test_the_index_prompt_is_index_only():
    p = es._DEC_INDEX_SYSTEM_PROMPT
    assert "exactly \nrone job" not in p
    for required in ("VERBATIM", "EXHAUSTIVE", "No Coverage", "section"):
        assert required in p, required
    # It must NOT re-ask for facts or flags - that is the dilution this pass
    # exists to escape.
    assert "flags" not in p.lower()
    assert "dec_page_entries" in p


def test_no_coverage_is_recorded_as_data():
    """'Property - No Coverage' is the affirmative statement that ACORD 140 has
    nothing to fill. Dropping it is how phantom lines get ticked."""
    # Re-pinned 2026-08-23 to the v3 wording, which lists MORE dispositions
    # between the same two anchors. Same guarantee, wider list.
    assert ("'No Coverage', 'NOT COVERED', 'COVERED', 'Included', 'Waived'"
            in es._DEC_INDEX_SYSTEM_PROMPT)


def test_the_main_extraction_prompt_is_untouched():
    """The dedicated pass must not disturb the cached prefix of LLM call 1 -
    a separate system prompt is the whole point."""
    assert es._DEC_INDEX_SYSTEM_PROMPT not in es.FACT_EXTRACTION_PROMPT \
        if hasattr(es, "FACT_EXTRACTION_PROMPT") else True


# ── 3. A percentage needs a source ──────────────────────────────────────────

def test_the_percentage_rule_covers_the_schemas_it_claims_to():
    """The measurement the rule rests on, re-run: no field named *Percent is
    anything other than a percentage, so this can never blank another kind."""
    typed, named = set(), set()
    for p in glob.glob(os.path.join(BACKEND, "forms_schemas", "*_schema.json")):
        with open(p, encoding="utf-8") as fh:
            for k, v in json.load(fh).items():
                if ps._tooltip_declared_type(v) == "percentage":
                    typed.add(k)
                if ps._PERCENT_FIELD_RE.search(k):
                    named.add(k)
    assert len(typed) >= 60
    assert not (named - typed), f"named *Percent but not a percentage: {sorted(named-typed)[:5]}"


def test_an_invented_percentage_is_blanked():
    """The live 2026-08-14 ACORD 125: INSTALLATION 100% and OFF PREMISES 100%,
    neither stated anywhere in 271 pages."""
    schema = _schema("ACORD_125")
    f1 = "CommercialStructure_InstallationRepairWorkPercent_A"
    f2 = "CommercialStructure_InstallationRepairWorkOffPremisesPercent_A"
    mapped, _ = ps.map_facts_to_form(
        {}, schema, "ACORD_125",
        raw_text="RADIUS 100 TERRITORY 111 COMMERCIAL GENERAL CONTRA",
        pre_filled_gpt={"filled_values": {f1: "100", f2: "100"},
                        "raw_text_fields": set(), "question_grounding": {}})
    assert mapped.get(f1) is None
    assert mapped.get(f2) is None


def test_a_percentage_the_document_prints_survives():
    """CONTRACT UPDATED 2026-08-14 (second batch): the guard is quote-gated
    now - rule 8d asks for a grounding quote on every percentage field, and a
    stated percentage survives WITH its citation. The document-wide check this
    test originally pinned was defeated live the same day: an unrelated page's
    '100%' saved an invented installation split. See
    test_run_20260814b_form_fixes.py for the full matrix."""
    schema = _schema("ACORD_125")
    f1 = "CommercialStructure_InstallationRepairWorkPercent_A"
    quote = "Installation work accounts for 15% of total sales."
    mapped, _ = ps.map_facts_to_form(
        {}, schema, "ACORD_125",
        raw_text=quote,
        pre_filled_gpt={"filled_values": {f1: "15%"},
                        "raw_text_fields": set(),
                        "question_grounding": {f1: quote}})
    assert mapped.get(f1) == "15%"


def test_a_bare_number_elsewhere_is_not_a_percentage():
    """'100' as a radius of use is not evidence that 100% of work is off
    premises - the distinction the guard turns on."""
    assert not ps._percentage_is_stated("100", "RADIUS 100 TERR 111")
    assert ps._percentage_is_stated("100", "100% of work is subcontracted")
    assert ps._percentage_is_stated("15%", "installation is 15 percent of sales")


# ── 4. A row about a party who is not on the form ───────────────────────────

def test_the_party_row_rule_uses_acords_own_marker():
    schema = _schema("ACORD_125")
    tu = schema["CommercialPolicy_OperationsDescription_B"]["tu"].lower()
    assert ps._PARTY_ROW_MARKER in tu and "insured" in tu


def test_row_b_operations_fall_without_a_second_insured():
    schema = _schema("ACORD_125")
    f = "CommercialPolicy_OperationsDescription_B"
    mapped, _ = ps.map_facts_to_form(
        {}, schema, "ACORD_125", raw_text="COMMERCIAL GENERAL CONTRA",
        pre_filled_gpt={"filled_values": {f: "COMMERCIAL GENERAL CONTRA"},
                        "raw_text_fields": set(), "question_grounding": {}})
    assert mapped.get(f) is None


def test_row_b_survives_when_the_second_insured_is_real():
    schema = _schema("ACORD_125")
    f = "CommercialPolicy_OperationsDescription_B"
    other = "Summit Ridge Property Holdings LLC leases the Boulder office."
    mapped, _ = ps.map_facts_to_form(
        {"additional_named_insureds": ["Summit Ridge Property Holdings LLC"]},
        schema, "ACORD_125",
        raw_text="Summit Ridge Property Holdings LLC " + other,
        pre_filled_gpt={"filled_values": {f: other},
                        "raw_text_fields": set(), "question_grounding": {}})
    assert mapped.get("NamedInsured_FullName_B")
    assert mapped.get(f) == other


# ── 5. The stop nothing was making ──────────────────────────────────────────

def test_an_expired_policy_term_a_producer_stated_is_a_hard_stop():
    """NARROWED 2026-08-15 on client direction, deliberately.

    This stop shipped on 2026-08-14 asserting "the application proposes a
    period that ended". That assertion only holds if a PERSON proposed the
    period. The dominant real input is a carrier declarations page for the
    policy now ending - uploaded precisely so the next submission can be built
    from it - and hard-stopping on that capped the client's package at 60 and
    made every other remediation look dead (their report: "the system is
    correctly recognizing Renewal in one place while another part treats the
    expired source policy as a defect").

    So the stop now turns on PROVENANCE, which the fact envelope already
    records. A producer-typed dead term is still a block; a term read off an
    uploaded document is a confirm-the-dates warning. Verified against the
    Orbin package, which never uses the word "renewal" in 271 pages - gating
    this on `is_renewal` alone would have fixed nothing.
    """
    from services.sqs_service import evaluate_stops
    hard, _soft = evaluate_stops({
        "effective_date": {"value": "07/15/2020", "source": "producer",
                           "confidence": "filled"},
        "expiration_date": {"value": "07/15/2021", "source": "producer",
                            "confidence": "filled"},
    }, {})
    assert any("already expired" in m for m in hard), hard


def test_an_expired_term_read_off_a_document_is_a_warning_not_a_block():
    from services.sqs_service import evaluate_stops
    hard, soft = evaluate_stops({
        "effective_date": {"value": "07/15/2020", "source": "ai", "confidence": "ai_high"},
        "expiration_date": {"value": "07/15/2021", "source": "ai", "confidence": "ai_high"},
    }, {})
    assert not any("already expired" in m for m in hard), hard
    assert any("already expired" in m for m in soft), soft


def test_a_current_term_raises_nothing():
    from datetime import datetime, timedelta
    from services.sqs_service import evaluate_stops
    future = (datetime.now() + timedelta(days=200)).strftime("%m/%d/%Y")
    hard, soft = evaluate_stops(
        {"effective_date": "01/01/2026", "expiration_date": future}, {})
    assert not any("expired" in m for m in hard + soft)


def test_the_expired_message_classifies_into_a_real_cluster():
    """ANTI-ROT: an unclassified legacy message reaches the user with no
    cluster and no Resolve action."""
    from services.issue_registry import classify_legacy
    code, cluster, tier = classify_legacy(
        "Policy term already expired (07/15/2026) - the application proposes a "
        "period that ended. Fix: Update the dates.", "hard_stop")
    assert code == "legacy_policy_term_expired"
    assert cluster != "Other validations"


def test_the_append_shape_stays_visible_to_the_harvester():
    """tests/test_legacy_rules.py walks this function's AST. A conditional-
    expression append is invisible to it, and the message would then ship with
    no cluster - which is exactly what that harness exists to prevent."""
    src = open(os.path.join(BACKEND, "services", "sqs_service.py"),
               encoding="utf-8").read()
    i = src.index("term_issue = validate_policy_term_not_expired")
    body = src[i:i + 400]
    assert "hard.append(term_issue[1])" in body
    assert "soft.append(term_issue[1])" in body


def test_the_wrapped_reply_shape_is_read(monkeypatch):
    """THE BUG THE FIRST LIVE RUN FOUND. `_safe_json_parse` normalises a bare
    reply into {"facts": {...}, "flags": {}} - which is exactly what this
    prompt returns, because it deliberately does not ask for that wrapper.

    The first cut read the top level only and discarded EIGHT successful calls:
    every one logged "bare dict ... wrapping into {facts: ...}" and then
    "harvested 0 raw entries from 8 chunk(s)". Up to 6,788 tokens of real
    output, paid for and thrown away by the reader.
    """
    # The pass is OFF by default since 2026-08-23 (it lost its A/B - see
    # LLMcall1-promptChange.md Round 8). These tests exercise the machinery
    # itself, so they switch it on explicitly rather than depending on a
    # default that is now a product decision.
    monkeypatch.setattr(es, "_DEC_INDEX_DEDICATED_PASS", True)
    async def _bare(model, messages, max_tokens=0):
        return json.dumps({"dec_page_entries": [
            {"label": "Total Premium", "value": "$10,663.00",
             "section": "COMMON POLICY DECLARATIONS", "owner": "policy"}]})
    monkeypatch.setattr(es, "groq_chat", _bare)
    out = asyncio.run(es._harvest_dec_index([(_DEC, 0, len(_DEC))]))
    assert len(out) == 1 and out[0]["value"] == "$10,663.00"


def test_the_already_wrapped_shape_also_works(monkeypatch):
    """Both shapes must read, so a future parser change cannot silently
    re-break this."""
    # The pass is OFF by default since 2026-08-23 (it lost its A/B - see
    # LLMcall1-promptChange.md Round 8). These tests exercise the machinery
    # itself, so they switch it on explicitly rather than depending on a
    # default that is now a product decision.
    monkeypatch.setattr(es, "_DEC_INDEX_DEDICATED_PASS", True)
    async def _wrapped(model, messages, max_tokens=0):
        return json.dumps({"facts": {"dec_page_entries": [
            {"label": "Liability", "value": "$3,954.00"}]}, "flags": {}})
    monkeypatch.setattr(es, "groq_chat", _wrapped)
    out = asyncio.run(es._harvest_dec_index([(_DEC, 0, len(_DEC))]))
    assert len(out) == 1 and out[0]["label"] == "Liability"


# ── 6. Full coverage: no silent cap on dec-dense chunks (2026-08-14) ─────────

def test_every_dec_dense_chunk_is_indexed_by_default(monkeypatch):
    """The old default of 8 silently skipped dec pages on any package whose
    declarations spread across more chunks - a recall loss with no log line.
    The owner's requirement is FULL coverage: the authority gate is the cost
    boundary, not an arbitrary count."""
    # The pass is OFF by default since 2026-08-23 (it lost its A/B - see
    # LLMcall1-promptChange.md Round 8). These tests exercise the machinery
    # itself, so they switch it on explicitly rather than depending on a
    # default that is now a product decision.
    monkeypatch.setattr(es, "_DEC_INDEX_DEDICATED_PASS", True)
    seen = []

    async def _fake(model, messages, max_tokens=0):
        seen.append(1)
        return '{"dec_page_entries": []}'

    monkeypatch.setattr(es, "groq_chat", _fake)
    monkeypatch.setattr(es, "_DEC_INDEX_MAX_CHUNKS", 0)
    asyncio.run(es._harvest_dec_index([(_DEC, 0, 1)] * 14))
    assert len(seen) == 14


def test_an_env_cap_still_works_as_an_emergency_valve(monkeypatch):
    """DEC_INDEX_MAX_CHUNKS > 0 must keep capping (and the cap now warns -
    see _harvest_dec_index), so a pathological deployment has an off-ramp."""
    # The pass is OFF by default since 2026-08-23 (it lost its A/B - see
    # LLMcall1-promptChange.md Round 8). These tests exercise the machinery
    # itself, so they switch it on explicitly rather than depending on a
    # default that is now a product decision.
    monkeypatch.setattr(es, "_DEC_INDEX_DEDICATED_PASS", True)
    seen = []

    async def _fake(model, messages, max_tokens=0):
        seen.append(1)
        return '{"dec_page_entries": []}'

    monkeypatch.setattr(es, "groq_chat", _fake)
    monkeypatch.setattr(es, "_DEC_INDEX_MAX_CHUNKS", 5)
    asyncio.run(es._harvest_dec_index([(_DEC, 0, 1)] * 20))
    assert len(seen) == 5


# ── 7. The verbatim gate reads tables the way OCR prints them (2026-08-14) ───
# The live runs dropped the ENTIRE GL class table and every 'Section N' = 'No
# Coverage' summary line as DROPPED_UNVERIFIED: the model joined two printed
# cells, OCR interleaves the neighbouring columns between them, and the joined
# string is contiguous nowhere. Real data, killed by the gate. The fix is
# `_entry_is_printed`: verbatim OR ordered containment across one row's width -
# with numbers exempted from the relaxation entirely, because a reformatted
# number is the fabrication the gate exists to stop.

_TABLE_DOC = (
    "General Liability Schedule\n"
    "Loc 001 Class Code 91580 Prem Basis: Payroll Exposure: $39,300\n"
    "Contractors - Executive Supervisors or Executive Superintendents\n"
    "Rate: 33.211 Premium: $1,305\n"
    "SECTION 1 SECTION 3\n"
    "Property Crime and Fidelity\n"
    "No Coverage No Coverage\n"
    "Each Occurrence Limit $1,000,000  EFF DATE 07/16/25\n"
)


def test_a_fused_table_row_survives_when_its_cells_print_in_order():
    """The literal live drop: class code + classification joined into one
    value, with the premium-basis and exposure cells printed between them."""
    out = es._verify_dec_entries(
        [{"label": "Class Code",
          "value": "91580 Contractors - Executive Supervisors or "
                   "Executive Superintendents",
          "owner": "policy"}], _TABLE_DOC)
    assert len(out) == 1


def test_a_two_column_no_coverage_line_survives():
    """'Section 1 Property' = 'No Coverage', where two-column OCR interleaves
    'SECTION 3' between the section number and its name."""
    out = es._verify_dec_entries(
        [{"label": "Section 1 Property", "value": "No Coverage",
          "owner": "policy"}], _TABLE_DOC)
    assert len(out) == 1


def test_a_reformatted_amount_is_still_dropped():
    """The doc prints $1,000,000; the model rewrites it 1000000. Numbers get
    NO ordered-containment latitude - verbatim or gone, rule 1 of the gate."""
    out = es._verify_dec_entries(
        [{"label": "Each Occurrence Limit", "value": "1000000",
          "owner": "policy"}], _TABLE_DOC)
    assert out == []


def test_a_rewritten_date_is_still_dropped():
    """07/16/25 expanded to 07/16/2025: all-digit tokens, strict path only."""
    out = es._verify_dec_entries(
        [{"label": "EFF DATE", "value": "07/16/2025", "owner": "policy"}],
        _TABLE_DOC)
    assert out == []


def test_scattered_words_beyond_one_row_width_still_fail():
    """The words all exist but 120+ chars apart - not a table row, not
    printed. The gap bound is what separates 'OCR split a row' from 'the model
    assembled a sentence out of the whole page'."""
    filler = "word " * 30
    doc = f"umbrella {filler} retention {filler} basis limit $5,000,000"
    out = es._verify_dec_entries(
        [{"label": "Umbrella Retention Basis", "value": "$5,000,000",
          "owner": "policy"}], doc)
    assert out == []


def test_a_fabricated_multiword_label_still_fails():
    """Words that never appear cannot pass ordered containment either."""
    out = es._verify_dec_entries(
        [{"label": "Aircraft Hull Deductible", "value": "$1,000,000",
          "owner": "policy"}], _TABLE_DOC)
    assert out == []


def test_the_prompt_asks_for_one_entry_per_cell():
    """Belt to the gate's braces: the fusion is also forbidden at the source,
    in BOTH recording prompts (the dedicated pass and the main extraction).

    RESTORED 2026-08-23. The main extraction's `dec_page_entries` key was briefly
    removed while the dedicated pass was the sole recorder; the pass lost its A/B
    (see LLMcall1-promptChange.md Round 8) and the key is back, so both recorders
    are checked again. The dedicated pass is off by default but its prompt is
    still the one that runs if it is switched on.
    """
    assert "ONE ENTRY PER PRINTED CELL" in es._DEC_INDEX_SYSTEM_PROMPT
    assert "NEVER weld" in es._DEC_INDEX_SYSTEM_PROMPT
    assert "one entry per CELL" in es._EXTRACT_SCHEMA
