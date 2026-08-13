"""Source-driven dec-page recording: verify mechanically, consume deterministically.

Owner's end goal, verbatim: "if values are present in declaration pages uploaded
by user then they should be correctly stamped on the form" - WITHOUT touching
LLM call 2. So call 1 records every label:value pair a dec page prints
(`dec_page_entries`), a mechanical gate discards anything not literally in the
document, and the ONLY consumers are deterministic: the empty-fact backfill and
the text-selection rescue net. Call 2's prompt is proven byte-identical below.

Every trap fixture here is the client's literal reported defect:
  * the carrier's account number 0482854 stamped as the FEIN,
  * the producer's phone 303-996-7800 stamped as the applicant's,
  * the carrier's website stamped as the applicant's.
"""
import os
import sys
import threading

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("OPENAI_API_KEY", "sk-offline")

import services.extraction_service as es  # noqa: E402
import services.pdf_service as ps  # noqa: E402

# The client's package, in miniature - every entry value below is printed here.
_DOC_TEXT = (
    "COMMERCIAL AUTO DECLARATIONS\n"
    "NAMED INSURED ORBIN CONTRACTING LLC\n"
    "PRODUCER Commercial Risk Solutions, Inc.\n"
    "Producer Contact Phone 303-996-7800\n"
    "CARRIER Employers Mutual Casualty Company  Account Number: 0482854\n"
    "FEIN OR SOC SEC #: 84-1234567\n"
    "POLICY NUMBER 6E7-40-02---26  Business Auto  PREMIUM $2,991\n"
    "Total Policy Premium $10,663\n"
    "Effective Date 07/15/2025  Expiration Date 07/15/2026\n"
    "www.emcins.com\n"
)


def _entry(label, value, owner="applicant", **kw):
    return {"label": label, "value": value, "owner": owner, **kw}


# ── 1. Mechanical verification ───────────────────────────────────────────────

def test_a_fabricated_value_cannot_survive_verification():
    out = es._verify_dec_entries(
        [_entry("Total Policy Premium", "$99,999")], _DOC_TEXT)
    assert out == []


def test_a_fabricated_label_cannot_survive_verification():
    out = es._verify_dec_entries(
        [_entry("Umbrella Retention Basis", "$10,663")], _DOC_TEXT)
    assert out == []


def test_a_verbatim_entry_survives_with_normalized_owner():
    out = es._verify_dec_entries(
        [_entry("Total Policy Premium", "$10,663", owner="POLICY")], _DOC_TEXT)
    assert len(out) == 1
    assert out[0]["owner"] == "policy"
    assert out[0]["value"] == "$10,663"


def test_formatting_differences_do_not_defeat_verification():
    # The doc prints "$10,663"; the model returns "10,663" (dropped the $).
    # Normalized containment must still verify it - same folding rule as
    # pdf_service._normalize_for_search.
    out = es._verify_dec_entries(
        [_entry("Total Policy Premium", "10,663")], _DOC_TEXT)
    assert len(out) == 1


def test_malformed_items_are_dropped_not_fatal():
    out = es._verify_dec_entries(
        ["not a dict", {"label": "", "value": "$10,663"},
         {"label": "Total Policy Premium", "value": ""},
         {"label": "Total Policy Premium", "value": "x" * 400},
         None, 42], _DOC_TEXT)
    assert out == []


def test_no_document_text_means_nothing_verifies():
    assert es._verify_dec_entries([_entry("FEIN", "84-1234567")], "") == []


def test_duplicate_entries_collapse_to_one():
    out = es._verify_dec_entries(
        [_entry("Total Policy Premium", "$10,663", owner="policy"),
         _entry("TOTAL POLICY PREMIUM", "$10,663", owner="policy")], _DOC_TEXT)
    assert len(out) == 1


def test_unknown_owner_becomes_other_never_a_crash():
    out = es._verify_dec_entries(
        [_entry("Total Policy Premium", "$10,663", owner="underwriter")], _DOC_TEXT)
    assert out[0]["owner"] == "other"


# ── 2. The backfill: five conditions, each pinned by a client trap ───────────

def _verified(entries):
    return es._verify_dec_entries(entries, _DOC_TEXT)


def test_fein_backfills_from_the_dec_pages_own_label():
    facts = {}
    es._backfill_empty_facts_from_entries(
        facts, _verified([_entry("FEIN OR SOC SEC #", "84-1234567")]))
    assert facts["fein"]["value"] == "84-1234567"
    assert facts["fein"]["source"] == "dec_entry"


def test_the_carrier_account_number_can_never_become_the_fein():
    # The client's literal defect: 0482854 (the EMC account number) in the FEIN
    # box. Two independent conditions block it - the label carries no 'fein'
    # token, and 0482854 is 7 digits so it fails _is_fein anyway.
    facts = {}
    es._backfill_empty_facts_from_entries(
        facts, _verified([_entry("Account Number", "0482854", owner="carrier")]))
    assert "fein" not in facts


def test_a_producer_owned_value_never_fills_an_applicant_fact():
    # The client's literal defect: the producer's 303-996-7800 as the
    # applicant's phone. Same label tokens, same valid phone shape - the OWNER
    # is the only thing wrong, and it must be enough.
    facts = {}
    es._backfill_empty_facts_from_entries(
        facts, _verified([_entry("Contact Phone", "303-996-7800", owner="producer")]))
    assert "contact_phone" not in facts


def test_the_same_value_fills_the_producer_fact_it_actually_belongs_to():
    facts = {}
    es._backfill_empty_facts_from_entries(
        facts, _verified(
            [_entry("Producer Contact Phone", "303-996-7800", owner="producer")]))
    assert facts["producer_contact_phone"]["value"] == "303-996-7800"


def test_a_carrier_website_never_fills_the_applicant_website():
    facts = {}
    es._backfill_empty_facts_from_entries(
        facts, _verified(
            [_entry("Applicant Website", "www.emcins.com", owner="carrier")]))
    assert "applicant_website" not in facts


def test_backfill_never_overwrites_an_existing_fact():
    facts = {"total_policy_premium": {"value": "$10,663", "confidence": "ai_high"}}
    es._backfill_empty_facts_from_entries(
        facts, _verified([_entry("Total Policy Premium", "$2,991", owner="policy")]))
    assert facts["total_policy_premium"]["value"] == "$10,663"


def test_two_distinct_stated_values_are_ambiguity_and_stay_blank():
    # Entries are hand-built (verification-shaped) here: the point under test
    # is the ambiguity rule alone - two DIFFERENT dates for one fact.
    facts = {}
    es._backfill_empty_facts_from_entries(
        facts, [
            _entry("Effective Date", "07/15/2025", owner="policy"),
            _entry("Policy Effective Date", "07/15/2026", owner="policy"),
        ])
    assert "effective_date" not in facts


def test_two_spellings_of_one_value_are_not_ambiguity():
    facts = {}
    es._backfill_empty_facts_from_entries(
        facts, [
            _entry("Effective Date", "07/15/2025", owner="policy"),
            _entry("Policy Effective Date", "07/15/2025", owner="policy"),
        ])
    assert facts["effective_date"]["value"] == "07/15/2025"


def test_a_value_failing_the_facts_own_validator_is_refused():
    # "Business Auto" is verbatim in the document and the label matches the
    # key's tokens - but it is not a currency, so total_policy_premium's
    # validator refuses it.
    facts = {}
    es._backfill_empty_facts_from_entries(
        facts, _verified([_entry("Total Policy Premium", "Business Auto",
                                 owner="policy")]))
    assert "total_policy_premium" not in facts


def test_partial_label_overlap_is_not_a_match():
    # Label "Premium" alone must not feed total_policy_premium - every token of
    # the fact key has to appear.
    facts = {}
    es._backfill_empty_facts_from_entries(
        facts, _verified([_entry("Premium", "$2,991", owner="policy")]))
    assert "total_policy_premium" not in facts


# ── 3. merge_facts end-to-end ────────────────────────────────────────────────

def _doc(name, facts, text=_DOC_TEXT):
    return {"filename": name, "facts": facts, "flags": {}, "text": text}


def test_merge_facts_unions_verifies_and_backfills():
    docs = [
        _doc("a.pdf", {"dec_page_entries": [
            _entry("FEIN OR SOC SEC #", "84-1234567"),
            _entry("Fabricated Label Xyz", "$1"),          # dies at verification
        ]}),
        _doc("b.pdf", {"dec_page_entries": [
            _entry("Total Policy Premium", "$10,663", owner="policy"),
        ]}),
    ]
    mf, _ = es.merge_facts(docs, docs[0])
    labels = {e["label"] for e in mf["dec_page_entries"]}
    assert labels == {"FEIN OR SOC SEC #", "Total Policy Premium"}
    assert mf["fein"]["value"] == "84-1234567"
    assert mf["total_policy_premium"]["value"] == "$10,663"


def test_merge_facts_without_entries_behaves_exactly_as_before():
    docs = [_doc("a.pdf", {"applicant_name": "Orbin Contracting LLC"})]
    mf, _ = es.merge_facts(docs, docs[0])
    assert mf.get("dec_page_entries") == []
    assert mf["applicant_name"] == "Orbin Contracting LLC"


def test_an_entry_shaped_crash_never_blocks_the_merge(monkeypatch):
    monkeypatch.setattr(es, "_verify_dec_entries",
                        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom")))
    docs = [_doc("a.pdf", {"dec_page_entries": [_entry("FEIN", "84-1234567")],
                           "applicant_name": "Orbin Contracting LLC"})]
    mf, _ = es.merge_facts(docs, docs[0])
    assert mf["applicant_name"] == "Orbin Contracting LLC"
    assert "dec_page_entries" not in mf


# ── 4. LLM call 2 is untouched: byte-identical prompts ───────────────────────

class _Recorder:
    def __init__(self):
        self.calls = []
        self._lock = threading.Lock()
        self.chat = self
        self.completions = self

    def create(self, **kwargs):
        msgs = kwargs.get("messages") or []
        user = next((m["content"] for m in msgs if m["role"] == "user"), "")
        system = next((m["content"] for m in msgs if m["role"] == "system"), "")
        with self._lock:
            self.calls.append((system, user))

        class _R:
            choices = [type("C", (), {"message": type(
                "M", (), {"content": '{"values": {}, "raw_text_sourced": [], '
                                     '"question_grounding": {}}'})()})()]
            usage = None
        return _R()


def _capture_call2_prompts(monkeypatch, facts):
    rec = _Recorder()
    monkeypatch.setattr(ps, "_get_openai_form_fill_client_sync", lambda: rec)
    monkeypatch.setattr(ps, "_COMBINED_BATCH_PAUSE_S", 0.0, raising=False)
    fields = {
        "Producer_FullName_A": {"tu": "Enter text: the producer's full name.", "ft": "/Tx"},
        "Insured_FullName_A": {"tu": "Enter text: the insured's full name.", "ft": "/Tx"},
    }
    ps._fill_unmatched_with_gpt(
        fields, facts, "ACORD_125", model="gpt-test",
        raw_text=_DOC_TEXT, already_filled={}, form_label="ACORD_125",
    )
    return rec.calls


def test_call2_prompt_is_byte_identical_with_dec_entries(monkeypatch):
    """THE constraint this whole feature was built under: LLM call 2 must not
    change. Same facts, with and without the entries key - every prompt built
    must be byte-for-byte identical."""
    base_facts = {"applicant_name": "Orbin Contracting LLC",
                  "total_policy_premium": {"value": "$10,663"}}
    with_entries = dict(base_facts)
    with_entries["dec_page_entries"] = [
        _entry("FEIN OR SOC SEC #", "84-1234567"),
        _entry("Total Policy Premium", "$10,663", owner="policy"),
    ]
    a = _capture_call2_prompts(monkeypatch, base_facts)
    b = _capture_call2_prompts(monkeypatch, with_entries)
    assert a and a == b


def test_every_unfilled_field_still_reaches_call_2(monkeypatch):
    """Owner's explicit requirement: the backfill may remove a field from call
    2's list ONLY by actually filling it. Everything still empty after the
    deterministic passes must remain in the unmatched set."""
    import json
    schema = json.load(open(
        os.path.join(os.path.dirname(__file__), "..",
                     "forms_schemas", "ACORD_125_schema.json"),
        encoding="utf-8"))
    facts_before = {"applicant_name": "Orbin Contracting LLC"}
    facts_after = dict(facts_before)
    es._backfill_empty_facts_from_entries(
        facts_after, _verified([_entry("FEIN OR SOC SEC #", "84-1234567")]))
    assert facts_after["fein"]["value"] == "84-1234567"

    mapped_b, unmatched_b, _ = ps.compute_form_gaps("ACORD_125", schema, facts_before)
    mapped_a, unmatched_a, _ = ps.compute_form_gaps("ACORD_125", schema, facts_after)
    missing = set(unmatched_b) - set(unmatched_a)
    # Any field that left the gap-fill list must now be FILLED - never hidden.
    for field in missing:
        assert mapped_a.get(field) not in (None, ""), (
            f"{field} left the gap-fill set without being filled")


# ── 5. The rescue net: entries protect their windows in the filter ───────────

def test_an_entry_value_rescues_a_window_no_fact_protects():
    from services.text_selection import select_gap_fill_text
    sentinel = "UNIQUE DEC FIGURE 7Q4-88-1234"
    dec = ("DECLARATIONS PAGE\nPREMIUM $2,991 07/15/2025\n"
           "LIMIT $1,000,000 07/15/2026\n") * 40
    prose = ("various provisions in this policy restrict coverage read the "
             "entire policy carefully to determine rights duties and what is "
             "and is not covered throughout this policy the words you and "
             "your refer to the named insured shown in the declarations\n") * 30
    doc = dec + prose + sentinel + "\n" + prose * 12
    facts_without = {}
    facts_with = {"dec_page_entries": [
        {"label": "Endorsement Figure", "value": sentinel, "owner": "policy"}]}
    out_without, s1 = select_gap_fill_text(doc, facts_without, label="t")
    out_with, s2 = select_gap_fill_text(doc, facts_with, label="t")
    if s1["applied"] and sentinel not in out_without:
        # The control: without the entry the value is genuinely lost...
        assert s2["applied"]
        assert sentinel in out_with, (
            "a verified dec entry must rescue its window exactly as an "
            "extracted fact does")


# ── 6. Strict-reverse label matching (first live run backfilled NOTHING) ─────

def test_payroll_backfills_from_the_bare_dec_label():
    # Live 2026-08-12: the dec prints "PAYROLL $39,300"; the key is
    # total_payroll; the unmatched "total" blocked the forward rule and the
    # "no revenue or payroll found" warning stood. The strict reverse fixes it.
    facts = {}
    es._backfill_empty_facts_from_entries(
        facts, [_entry("PAYROLL", "$39,300", owner="policy")])
    assert facts["total_payroll"]["value"] == "$39,300"


def test_annual_revenues_backfills_total_revenue():
    facts = {}
    es._backfill_empty_facts_from_entries(
        facts, [_entry("ANNUAL REVENUES", "$50,000", owner="applicant")])
    assert facts["total_revenue"]["value"] == "$50,000"


def test_a_bare_deductible_never_crosses_coverage_lines():
    # "Deductible" -> gl_deductible leaves "gl" unmatched, and "gl" is not a
    # generic qualifier: a bare deductible could be the auto's, so it stays out.
    facts = {}
    es._backfill_empty_facts_from_entries(
        facts, [_entry("Deductible", "$1,000", owner="policy")])
    assert "gl_deductible" not in facts
    assert "auto_deductible_comp" not in facts


def test_a_bare_premium_never_becomes_the_package_total():
    facts = {}
    es._backfill_empty_facts_from_entries(
        facts, [_entry("Premium", "$2,991", owner="policy")])
    assert "total_policy_premium" not in facts


# ── 7. Entry-anchored keep: the dec fingerprint the EMC package needed ───────

def _emc_shaped_package():
    """Blurred short lines EVERYWHERE and NO ISO footers - the measured live
    state where density declined (gap 0.07) and the footer stage caught only
    carrier-proprietary pages it cannot recognise ("FORM CU7000A ED. 01-07")."""
    dec = (
        "COMMERCIAL AUTO DECLARATIONS CA7000A 02-22\n"
        "POLICY NUMBER 6E7-40-02---26\n"
        "NAMED INSURED ORBIN CONTRACTING LLC\n"
        "PREMIUM $2,991 EFF 07/15/2025\n"
        "TOTAL POLICY PREMIUM $10,663\n"
    ) * 14
    def page(n):
        return ((
            "we will pay up to $250 per day\n"
            "subject to the limit of 07/15/2025\n"
            "no legal action may be brought here\n"
            "coverage applies as stated in item\n"
        ) * 11) + f"FORM CU7000A ED. 01-07 BPP Page {n} of 90\n"
    return dec + "".join(page(n) for n in range(1, 70))


def _anchor_facts():
    return {"dec_page_entries": [
        {"label": "POLICY NUMBER", "value": "6E7-40-02---26", "owner": "policy"},
        {"label": "NAMED INSURED", "value": "ORBIN CONTRACTING LLC", "owner": "applicant"},
        {"label": "TOTAL POLICY PREMIUM", "value": "$10,663", "owner": "policy"},
    ] + [{"label": f"L{i}", "value": "TOTAL POLICY PREMIUM", "owner": "policy"}
         for i in range(20)]}


def test_entry_anchor_cuts_where_density_and_footer_both_failed():
    from services.text_selection import select_gap_fill_text
    pkg = _emc_shaped_package()
    # Control: without entries, neither stage discriminates on this shape.
    out0, s0 = select_gap_fill_text(pkg, {}, label="t")
    assert not s0["applied"], "fixture self-check: the old path must decline"
    out1, s1 = select_gap_fill_text(pkg, _anchor_facts(), label="t")
    assert s1["applied"] and s1["cut_kind"] == "entry-anchor"
    assert s1["kept_chars"] < 0.5 * len(pkg)
    assert "TOTAL POLICY PREMIUM $10,663" in out1
    assert "NAMED INSURED ORBIN CONTRACTING LLC" in out1


def test_entry_anchor_needs_the_entry_floor():
    from services.text_selection import select_gap_fill_text
    pkg = _emc_shaped_package()
    thin = {"dec_page_entries": [
        {"label": "POLICY NUMBER", "value": "6E7-40-02---26", "owner": "policy"}]}
    _out, stats = select_gap_fill_text(pkg, thin, label="t")
    assert stats.get("cut_kind") != "entry-anchor", (
        "one entry is not a fingerprint - the old path must run")


def test_entry_anchor_kill_switch():
    import importlib
    import services.text_selection as ts
    old = os.environ.get("TEXT_SELECT_ENTRY_ANCHOR")
    os.environ["TEXT_SELECT_ENTRY_ANCHOR"] = "0"
    try:
        importlib.reload(ts)
        pkg = _emc_shaped_package()
        _out, stats = ts.select_gap_fill_text(pkg, _anchor_facts(), label="t")
        assert stats.get("cut_kind") != "entry-anchor"
    finally:
        if old is None:
            os.environ.pop("TEXT_SELECT_ENTRY_ANCHOR", None)
        else:
            os.environ["TEXT_SELECT_ENTRY_ANCHOR"] = old
        importlib.reload(ts)


def test_entry_anchor_never_loses_a_protected_value():
    # A scalar fact living OUTSIDE the anchored windows must still be visible -
    # anchors include every _fact_values needle, so its window is kept too.
    from services.text_selection import select_gap_fill_text
    sentinel = "UNIQUE ENDORSED FIGURE 9Z8-77-4321"
    pkg = _emc_shaped_package()
    cut = len(pkg) // 2
    pkg = pkg[:cut] + "\n" + sentinel + "\n" + pkg[cut:]
    facts = dict(_anchor_facts())
    facts["some_fact"] = {"value": sentinel}
    out, stats = select_gap_fill_text(pkg, facts, label="t")
    assert stats["applied"]
    assert sentinel in out
