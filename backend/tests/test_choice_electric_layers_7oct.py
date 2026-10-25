"""Choice Electric #4 (Brent, 7 Oct 2026) - one ACORD 131 per umbrella-family LAYER.

"When we have an umbrella base with excess on top of it, each gets their own
form 131. Layer 1 is Umbrella, with an underlying schedule focus to GL, Auto, and
WC. Layer 2 is Excess, which gets mapped to the underlying umbrella policy."

Replays the client's stored per-document facts (session ca93ed8f,
`tests/fixtures/choice_electric_pol_6oct.json`): Umbrella = Amerisure Mutual,
$5,000,000, premium $17,082, SIR 0; Excess = Travelers, $4,000,000 following
form, premium $10,692, controlling underlying = the Amerisure Mutual umbrella.
"""
import ast
import copy
import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

from services import extraction_service as es
from services import form_instances as fi
from services import form_service as fs
from services import pdf_service as pdf
from services import umbrella_layers as ul

BACKEND = Path(__file__).resolve().parent.parent
FRONTEND = BACKEND.parent / "frontend" / "src"
_FIXTURE = BACKEND / "tests" / "fixtures" / "choice_electric_pol_6oct.json"
EXCESS = "ACORD_131__excess"
EXCESS_DOC = "25-26 Excess Umbrella Policy.pdf"
UMBRELLA_DOC = "25-26 Umbrella Policy.pdf"


def _docs(order="stored", drop=()):
    docs = copy.deepcopy(json.load(open(_FIXTURE))["docs"])
    docs = [d for d in docs if d["filename"] not in drop]
    return list(reversed(docs)) if order == "reversed" else docs


def _merge(order="stored", drop=()):
    docs = _docs(order, drop)
    mf, flags = es.merge_facts(docs, es.select_primary_truth(docs))
    return mf, flags, docs


@pytest.fixture(scope="module")
def merged():
    return _merge()


@pytest.fixture(scope="module")
def single():
    """The same package with the excess declarations removed: ONE umbrella."""
    return _merge(drop=(EXCESS_DOC,))


def _session(merged, ids=("ACORD_125", "ACORD_131", EXCESS)):
    mf, flags, docs = merged
    return {"facts": mf, "flags": flags, "docs": docs,
            "all_forms": fs.filter_available_forms(fs.load_all_forms()),
            "selected_form_ids": list(ids)}


def _v(facts, key):
    return es._fv(facts, key)


def _umb_rows(facts):
    return [(r.get("line"), r.get("carrier")) for r in (_v(facts, "coverage_lines") or [])
            if isinstance(r, dict) and ul._row_layer(r)]


_NO_LLM = {"filled_values": {}, "raw_text_fields": set(), "question_grounding": {}}


@pytest.fixture(scope="module")
def stamped(merged):
    """Both copies stamped deterministically (no LLM) from the real engine."""
    session = _session(merged)
    out = {}
    for fid in ("ACORD_131", EXCESS):
        meta = fi.form_meta_for(session["all_forms"], fid, session["facts"])
        out[fid] = fs.process_single_form(meta, session, dict(_NO_LLM))
    return out


# =============================================================================
# 1. The recommendation: one 131 per layer, in attachment order
# =============================================================================
def test_the_tower_has_two_layers_umbrella_first(merged):
    mf, _flags, _docs = merged
    slots = ul.ordered_layers(mf)
    assert [s["layer"] for s in slots] == ["umbrella", "excess"]
    assert slots[0]["record"]["carrier_name"] == "AMERISURE MUTUAL INSURANCE COMPANY"
    assert slots[1]["record"]["carrier_name"] == "TRAVELERS PROPERTY CASUALTY COMPANY OF AMERICA"
    assert fi.instance_ids(mf) == [EXCESS]
    assert fi.instance_ids(mf, "ACORD_131") == [EXCESS]
    assert fi.instance_ids(mf, "ACORD_125") == []


def test_recommendation_offers_ACORD_131_and_its_excess_copy(merged):
    mf, flags, docs = merged
    recs = fs.match_forms_deterministic(mf, flags, text=" ".join(d["text"] for d in docs))
    ids = [r["form_id"] for r in recs]
    assert "ACORD_131" in ids and EXCESS in ids
    assert ids.index(EXCESS) == ids.index("ACORD_131") + 1          # beside its base
    base = recs[ids.index("ACORD_131")]
    exc = recs[ids.index(EXCESS)]
    assert base["reason_label"].startswith("Umbrella layer - AMERISURE MUTUAL INSURANCE COMPANY")
    assert exc["reason_label"].startswith(
        "Excess layer above the umbrella - TRAVELERS PROPERTY CASUALTY COMPANY OF AMERICA")
    assert "Excess limit: $4,000,000" in exc["reason_label"]
    assert "Umbrella limit: $5,000,000" in base["reason_label"]
    assert exc["form_name"].startswith("ACORD 131 (Excess) - ")
    assert exc["tier"] == base["tier"]
    assert ids.count("ACORD_131") == 1 and ids.count(EXCESS) == 1


def test_upload_order_does_not_change_the_layers():
    a, _f, _d = _merge("stored")
    b, _f2, _d2 = _merge("reversed")
    assert fi.instance_ids(a) == fi.instance_ids(b) == [EXCESS]
    for fid in ("ACORD_131", EXCESS):
        va, vb = fi.facts_for_form(a, fid), fi.facts_for_form(b, fid)
        for k in ("umbrella_limit", "umbrella_sir"):
            assert _v(va, k) == _v(vb, k)
        assert va[ul.MARKER_KEY]["carrier"] == vb[ul.MARKER_KEY]["carrier"]


def test_a_single_umbrella_package_is_unchanged(single):
    mf, flags, docs = single
    assert ul.ordered_layers(mf) == []
    assert fi.instance_ids(mf) == []
    assert ul.DOCS_KEY not in mf                         # nothing written
    assert fi.facts_for_form(mf, "ACORD_131") is mf      # the same object
    recs = fs.match_forms_deterministic(mf, flags, text=" ".join(d["text"] for d in docs))
    ids = [r["form_id"] for r in recs]
    assert ids.count("ACORD_131") == 1 and not any(fi.is_instance(f) for f in ids)
    base = recs[ids.index("ACORD_131")]
    assert base["reason_label"].startswith("Umbrella / Excess")   # today's wording


# =============================================================================
# 2. The overlay: each copy's own values, blank where its layer states none
# =============================================================================
def test_the_excess_copy_is_travelers_4m_no_sir_over_the_umbrella(merged):
    mf, _flags, _docs = merged
    before = copy.deepcopy(mf)
    v = fi.facts_for_form(mf, EXCESS)
    m = v[ul.MARKER_KEY]
    assert m["key"] == "excess" and m["index"] == 1 and m["layer"] == "excess"
    assert m["carrier"] == "TRAVELERS PROPERTY CASUALTY COMPANY OF AMERICA"
    assert m["premium"] == 10692.0
    assert _v(v, "umbrella_limit") == "$4,000,000"
    assert "umbrella_sir" not in v                       # the excess states no SIR
    assert _v(v, "umbrella_effective_date") == "01/01/2025"
    assert _v(v, "underlying_policies") == []
    assert _umb_rows(v) == [("Excess (Following Form) Liability",
                             "TRAVELERS PROPERTY CASUALTY COMPANY OF AMERICA")]
    assert [r["id"] for r in v["_line_records"] if r["line"] == "umbrella"] == \
        ["umbrella~excess#unnumbered"]
    below = m["below"]
    assert below["carrier"] == "AMERISURE MUTUAL INSURANCE COMPANY"
    assert below["limit"] == "$5,000,000"
    assert below["line_printed"] == "Commercial Liability Umbrella"
    assert below["premium"] == 17082.0
    assert mf == before                                  # the package facts are untouched


def test_the_plain_131_prints_only_the_lowest_layer(merged):
    mf, _flags, _docs = merged
    v = fi.facts_for_form(mf, "ACORD_131")
    assert v is not mf
    m = v[ul.MARKER_KEY]
    assert m["key"] == "" and m["index"] == 0 and m["layer"] == "umbrella" and m["below"] is None
    assert m["carrier"] == "AMERISURE MUTUAL INSURANCE COMPANY"
    assert m["premium"] == 17082.0
    assert _v(v, "umbrella_limit") == "$5,000,000"
    assert _v(v, "umbrella_sir") == "0"
    assert _umb_rows(v) == [("Commercial Liability Umbrella", "AMERISURE MUTUAL INSURANCE COMPANY")]
    lines = [r.get("line") for r in _v(v, "underlying_policies")]
    assert "Umbrella Liability" not in lines             # the excess's own underlying rows
    assert {"General Liability", "Automobile Liability"} <= set(lines)


def test_a_view_is_final_and_a_stale_copy_prints_no_layer(merged, single):
    mf, _flags, _docs = merged
    v = fi.facts_for_form(mf, EXCESS)
    assert fi.facts_for_form(v, EXCESS) is v
    assert fi.facts_for_form(v, "ACORD_131") is v
    smf, _f, _d = single
    stale = fi.facts_for_form(smf, EXCESS)
    assert stale[ul.MARKER_KEY].get("missing") is True
    assert not any(k in stale for k in ul.LAYER_FACTS)
    assert _umb_rows(stale) == []
    assert not fi.is_valid_form_id(smf, EXCESS)
    assert fi.form_meta_for(fs.filter_available_forms(fs.load_all_forms()), EXCESS, smf) is None


def test_form_meta_for_a_copy(merged):
    mf, _f, _d = merged
    forms = fs.filter_available_forms(fs.load_all_forms())
    base = fi.form_meta_for(forms, "ACORD_131", mf)
    meta = fi.form_meta_for(forms, EXCESS, mf)
    assert base is next(f for f in forms if f["form_id"] == "ACORD_131")
    assert meta is not base and meta["form_id"] == EXCESS
    assert meta["template_file"] == base["template_file"]
    assert meta["form_name"] == "ACORD 131 (Excess) - Umbrella or Excess Liability Application"
    assert meta["base_form_id"] == "ACORD_131" and meta["instance_key"] == "excess"
    assert fi.form_meta_for(forms, "ACORD_131__excess-2", mf) is None
    assert fi.form_meta_for(forms, "ACORD_999__excess", mf) is None


# =============================================================================
# 3. Layer edge cases (synthetic records, both directions)
# =============================================================================
def _rec(rid, layer, carrier, sources, number=None, premium=None):
    return {"id": rid, "line": "umbrella", "line_printed": f"{layer.title()} Liability",
            "layer": layer, "carrier_name": carrier, "policy_number": number,
            "effective_date": "01/01/2026", "expiration_date": "01/01/2027",
            "granted": True, "sources": list(sources), "premium": premium,
            "printings": {"carrier_name": [carrier]}}


def test_excess_only_or_rival_umbrellas_are_not_a_tower():
    one = {"_line_records": [_rec("umbrella~excess#X1", "excess", "Alpha", ["a.pdf"], "X1", 10.0)]}
    assert ul.ordered_layers(one) == [] and fi.facts_for_form(one, "ACORD_131") is one
    rivals = {"_line_records": [_rec("umbrella#U1", "umbrella", "Alpha", ["a.pdf"], "U1", 10.0),
                                _rec("umbrella#U2", "umbrella", "Beta", ["b.pdf"], "U2", 20.0)]}
    assert ul.ordered_layers(rivals) == [] and fi.instance_ids(rivals) == []
    assert ul.ordered_layers({}) == [] and ul.ordered_layers({"_line_records": "junk"}) == []


@pytest.mark.parametrize("reverse", [False, True])
def test_stacked_excess_layers_order_by_their_attachment(reverse):
    recs = [_rec("umbrella#U1", "umbrella", "Base Mutual", ["u.pdf"], "U1", 100.0),
            _rec("umbrella~excess#HIGH", "excess", "High Re", ["high.pdf"], "HIGH", 30.0),
            _rec("umbrella~excess#LOW", "excess", "Low Casualty", ["low.pdf"], "LOW", 50.0)]
    if reverse:
        recs = list(reversed(recs))
    facts = {"_line_records": recs, ul.DOCS_KEY: {
        "u.pdf": {"umbrella_limit": "$5,000,000"},
        "low.pdf": {"umbrella_limit": "$5,000,000", "umbrella_attachment_point": "$5,000,000"},
        "high.pdf": {"umbrella_limit": "$10,000,000", "umbrella_attachment_point": "$10,000,000"}}}
    assert [s["record"]["id"] for s in ul.ordered_layers(facts)] == \
        ["umbrella#U1", "umbrella~excess#LOW", "umbrella~excess#HIGH"]
    assert fi.instance_ids(facts) == [EXCESS, "ACORD_131__excess-2"]
    top = fi.facts_for_form(facts, "ACORD_131__excess-2")[ul.MARKER_KEY]
    assert top["carrier"] == "High Re" and top["below"]["carrier"] == "Low Casualty"
    assert top["below"]["limit"] == "$5,000,000"
    assert fi.instance_label("ACORD_131__excess-2") == "ACORD 131 (Excess 2)"
    words = [x["reason"] for x in ul.recommendation_layers(facts)]
    assert words == ["Umbrella layer - Base Mutual",
                     "Excess layer above the umbrella - Low Casualty",
                     "Excess layer 2 above the excess layer - High Re"]


def test_a_layer_without_documents_prints_its_identity_and_no_limits():
    facts = {"_line_records": [_rec("umbrella#U1", "umbrella", "Base Mutual", ["u.pdf"], "U1", 100.0),
                               _rec("umbrella~excess#P1", "excess", "Producer Re", [], "P1", 9.0)],
             "umbrella_limit": "$5,000,000", ul.DOCS_KEY: {"u.pdf": {"umbrella_limit": "$5,000,000"}}}
    v = fi.facts_for_form(facts, EXCESS)
    assert v[ul.MARKER_KEY]["carrier"] == "Producer Re"
    assert "umbrella_limit" not in v
    assert ul.layer_text([{"filename": "u.pdf", "text": "UMB"}], facts, EXCESS) == ""


def test_two_documents_of_one_layer_that_disagree_print_nothing():
    facts = {"_line_records": [_rec("umbrella#U1", "umbrella", "Base", ["u.pdf"], "U1", 1.0),
                               _rec("umbrella~excess#E1", "excess", "Top", ["e1.pdf", "e2.pdf"], "E1", 2.0)],
             ul.DOCS_KEY: {"u.pdf": {"umbrella_limit": "$5,000,000"},
                           "e1.pdf": {"umbrella_limit": "$4,000,000"},
                           "e2.pdf": {"umbrella_limit": "$3,000,000", "umbrella_sir": "$10,000"}}}
    v = fi.facts_for_form(facts, EXCESS)
    assert "umbrella_limit" not in v                     # its own documents disagree
    assert _v(v, "umbrella_sir") == "$10,000"            # one printing, kept


# =============================================================================
# 4. Stamping: the real engine, both copies (no LLM)
# =============================================================================
def test_the_base_131_stamps_the_umbrella_layer(stamped):
    r = stamped["ACORD_131"]
    m = r["mapped"]
    assert r["form_id"] == "ACORD_131" and r["sqs"]["form_id"] == "ACORD_131"
    assert m["Insurer_FullName_A"] == "AMERISURE MUTUAL INSURANCE COMPANY"
    assert m["ExcessUmbrella_Umbrella_EachOccurrenceAmount_A"] == "5,000,000"
    assert m["ExcessUmbrella_Umbrella_DeductibleOrRetentionAmount_A"] == "0"
    assert m["Policy_PolicyType_UmbrellaIndicator_A"] == "Yes"
    assert m["Policy_PolicyType_ExcessIndicator_A"] == "No"
    # Layer 1: the underlying schedule is GL, Auto and WC
    assert m["GeneralLiability_GeneralAggregate_LimitAmount_A"] == "2,000,000"
    assert m["Vehicle_CombinedSingleLimit_EachAccidentAmount_A"] == "1,000,000"
    assert m["UnderlyingPolicy_EmployersLiability_InsurerFullName_A"] == "AMERISURE INSURANCE COMPANY"
    assert not m.get("UnderlyingPolicy_OtherPolicy_InsurerFullName_A")


def test_the_excess_131_stamps_travelers_over_the_umbrella(stamped):
    r = stamped[EXCESS]
    m = r["mapped"]
    assert r["form_id"] == EXCESS and r["sqs"]["form_id"] == EXCESS
    assert r["form_name"].startswith("ACORD 131 (Excess)")
    assert r["form"]["template_file"] == "ACORD_131.pdf"
    assert m["Insurer_FullName_A"] == "TRAVELERS PROPERTY CASUALTY COMPANY OF AMERICA"
    assert m["ExcessUmbrella_Umbrella_EachOccurrenceAmount_A"] == "4,000,000"
    assert m["ExcessUmbrella_Umbrella_AggregateAmount_A"] == "4,000,000"
    assert not m.get("ExcessUmbrella_Umbrella_DeductibleOrRetentionAmount_A")   # no SIR
    assert m["Policy_PolicyType_ExcessIndicator_A"] == "Yes"
    assert m["Policy_PolicyType_UmbrellaIndicator_A"] == "No"
    # Layer 2: mapped to the underlying umbrella policy
    assert m["UnderlyingPolicy_OtherPolicy_PolicyTypeDescription_A"] == "Commercial Liability Umbrella"
    assert m["UnderlyingPolicy_OtherPolicy_InsurerFullName_A"] == "AMERISURE MUTUAL INSURANCE COMPANY"
    assert m["UnderlyingPolicy_OtherPolicy_PolicyEffectiveDate_A"] == "01/01/2025"
    assert m["UnderlyingPolicy_OtherPolicy_PolicyExpirationDate_A"] == "01/01/2026"
    assert m["UnderlyingPolicy_OtherPolicy_CombinedSingleLimitAmount_A"].replace("$", "") == "5,000,000"
    # Brent, 23 Oct 2026 (Z34-1 #3, reverses this test's 7 Oct blanks): "list
    # the applicable underlying coverages" - the GL / Auto / EL lines the
    # umbrella sits over print as the plain 131 prints them
    # (tests/test_build25_forms.py); the expiring policy and OTHER row B do not.
    base = stamped["ACORD_131"]["mapped"]
    for box in ("UnderlyingPolicy_GeneralLiability_InsurerFullName_A",
                "GeneralLiability_EachOccurrence_LimitAmount_A",
                "Vehicle_CombinedSingleLimit_EachAccidentAmount_A",
                "UnderlyingPolicy_EmployersLiability_InsurerFullName_A",
                "WorkersCompensationEmployersLiability_EmployersLiability_EachAccidentLimitAmount_A"):
        assert m.get(box) and m[box] == base[box], box
    for box in ("UnderlyingPolicy_OtherPolicy_InsurerFullName_B",
                "PriorCoverage_PolicyNumberIdentifier_A"):
        assert not m.get(box), box
    # the insured is the same insured on both
    assert m["NamedInsured_FullName_A"] == stamped["ACORD_131"]["mapped"]["NamedInsured_FullName_A"]


def test_a_copy_never_writes_a_schema_file():
    tpl = os.path.join(pdf.TEMPLATE_DIR, "ACORD_131.pdf")
    schema = pdf.extract_form_schema(tpl, EXCESS)
    assert schema == pdf.extract_form_schema(tpl, "ACORD_131") and schema
    assert not os.path.exists(os.path.join(pdf.FORMS_SCHEMAS_DIR, f"{EXCESS}_schema.json"))


# =============================================================================
# 5. Gap fill: a layer's own policy boxes never take another layer's answer
# =============================================================================
def test_gap_fill_isolates_each_layers_policy_boxes(monkeypatch, merged):
    calls = []

    def fake_combined_gap_fill(forms_to_unmatched, facts, raw_text, model=None,
                               forms_to_mapped=None, line_scopes=None):
        marker = (facts or {}).get(ul.MARKER_KEY) or {}
        calls.append({"forms": {f: set(v) for f, v in forms_to_unmatched.items()},
                      "layer": marker.get("key"), "text": raw_text})
        tag = marker.get("carrier") or "PACKAGE"
        return {fid: {"filled_values": {f: f"{tag}|{f}" for f in fields},
                      "raw_text_fields": set(), "question_grounding": {}, "model_used": "stub"}
                for fid, fields in forms_to_unmatched.items()}

    monkeypatch.setattr(pdf, "combined_gap_fill", fake_combined_gap_fill)
    session = _session(merged)
    per_form = fs.shared_gap_fill(session, ["ACORD_125", "ACORD_131", EXCESS])
    assert per_form, "the shared gap fill fell back"
    shared = [c for c in calls if c["layer"] is None]
    own_base = [c for c in calls if c["layer"] == ""]
    own_exc = [c for c in calls if c["layer"] == "excess"]
    assert len(shared) == 1 and len(own_base) == 1 and len(own_exc) == 1
    # the shared union never carries a layer's own policy box
    for fid in ("ACORD_131", EXCESS):
        assert not any(ul.is_private_field(f) for f in shared[0]["forms"].get(fid, ()))
    # each layer's own group asks only that copy, only its policy boxes
    assert set(own_base[0]["forms"]) == {"ACORD_131"}
    assert set(own_exc[0]["forms"]) == {EXCESS}
    assert all(ul.is_private_field(f) for f in own_exc[0]["forms"][EXCESS])
    assert own_exc[0]["forms"][EXCESS]
    # ...reading only its own declarations
    docs = {d["filename"]: d["text"] for d in session["docs"]}
    assert own_exc[0]["text"].strip() == docs[EXCESS_DOC].strip()
    assert docs[EXCESS_DOC].strip()[:200] not in own_base[0]["text"]
    assert docs[UMBRELLA_DOC].strip()[:200] in own_base[0]["text"]
    # the answers each copy receives
    exc_vals = per_form[EXCESS]["filled_values"]
    base_vals = per_form["ACORD_131"]["filled_values"]
    for f, val in exc_vals.items():
        if ul.is_private_field(f):
            assert val.startswith("TRAVELERS"), (f, val)
    for f, val in base_vals.items():
        if ul.is_private_field(f):
            assert val.startswith("AMERISURE MUTUAL"), (f, val)
    common = {f for f in exc_vals if not ul.is_private_field(f)} & set(base_vals)
    assert common and all(exc_vals[f] == base_vals[f] for f in common)


def test_gap_fill_without_a_tower_is_one_shared_pass(monkeypatch, single):
    calls = []

    def fake_combined_gap_fill(forms_to_unmatched, facts, raw_text, model=None,
                               forms_to_mapped=None, line_scopes=None):
        calls.append(sorted(forms_to_unmatched))
        return {fid: {"filled_values": {}, "raw_text_fields": set(), "question_grounding": {},
                      "model_used": "stub"} for fid in forms_to_unmatched}

    monkeypatch.setattr(pdf, "combined_gap_fill", fake_combined_gap_fill)
    fs.shared_gap_fill(_session(single, ("ACORD_125", "ACORD_131")), ["ACORD_125", "ACORD_131"])
    assert calls == [["ACORD_125", "ACORD_131"]]


def test_no_shared_answers_means_deterministic_boxes_only(monkeypatch, merged):
    asked = []
    monkeypatch.setattr(pdf, "_fill_unmatched_with_gpt",
                        lambda *a, **k: asked.append(a) or {"filled_values": {}})
    session = _session(merged)
    meta = fi.form_meta_for(session["all_forms"], EXCESS, session["facts"])
    res = fs.process_single_form(meta, session, None)
    assert asked == []
    assert res["mapped"]["Insurer_FullName_A"] == "TRAVELERS PROPERTY CASUALTY COMPANY OF AMERICA"


# =============================================================================
# 6. After generation: edits, restamps, questions
# =============================================================================
def _generated(stamped):
    out = {}
    for fid, r in stamped.items():
        out[fid] = {k: copy.deepcopy(v) for k, v in r.items() if k != "pdf_bytes"}
        out[fid]["field_state"] = dict(r["mapped"])
        out[fid]["confidence"] = dict(r["confidence"])
        out[fid]["client_filled_fields"] = []
    return out


def test_a_package_answer_never_reaches_the_excess_copys_policy_boxes(merged, stamped):
    from services.arq_service import _restamp_canonical_into_forms
    mf, flags, _docs = merged
    facts = {**mf, **flags,
             "umbrella_limit": {"value": "$6,000,000", "source": "producer", "confidence": "filled"}}
    gen = _generated(stamped)
    touched = _restamp_canonical_into_forms(gen, "umbrella_limit", facts, provenance="producer")
    box = "ExcessUmbrella_Umbrella_EachOccurrenceAmount_A"
    assert "ACORD_131" in touched
    assert gen["ACORD_131"]["field_state"][box] == "6,000,000"
    assert gen["ACORD_131"]["confidence"][box] == "producer"
    # the excess layer's own limit is untouched and keeps its label...
    assert gen[EXCESS]["field_state"][box] == "4,000,000"
    assert gen[EXCESS]["confidence"][box] == stamped[EXCESS]["confidence"][box]
    # ...while its UNDERLYING row follows the umbrella it sits on
    csl = "UnderlyingPolicy_OtherPolicy_CombinedSingleLimitAmount_A"
    assert gen[EXCESS]["field_state"][csl].replace("$", "") == "6,000,000"
    assert gen[EXCESS]["confidence"][csl] == "filled"
    changed = {k for k, v in gen[EXCESS]["field_state"].items()
               if v != stamped[EXCESS]["mapped"].get(k)}
    assert changed == {csl}


def test_an_insured_edit_reaches_both_copies(merged, stamped):
    from services.arq_service import propagate_fact_edits, _restamp_changed_boxes
    mf, flags, _docs = merged
    before = {**mf, **flags}
    after = {**before, "applicant_name": {"value": "Choice Electric Inc", "source": "producer"}}
    gen = _generated(stamped)
    touched = propagate_fact_edits(gen, "ACORD_125", before, after, ["applicant_name"])
    assert set(touched) == {"ACORD_131", EXCESS}
    for fid in touched:
        assert gen[fid]["field_state"]["NamedInsured_FullName_A"] == "Choice Electric Inc"
    # a confirmation of the umbrella's limit moves the umbrella's own boxes and
    # the excess copy's UNDERLYING row (the umbrella it sits on) - never the
    # excess layer's own limit
    gen2 = _generated(stamped)
    after2 = {**before, "umbrella_limit": {"value": "$7,000,000", "source": "user_confirmed"}}
    moved = _restamp_changed_boxes(gen2, before, after2, ["umbrella_limit"], "$7,000,000")
    assert sorted(moved) == ["ACORD_131", EXCESS]
    assert gen2["ACORD_131"]["field_state"]["ExcessUmbrella_Umbrella_EachOccurrenceAmount_A"] == "7,000,000"
    exc_state = gen2[EXCESS]["field_state"]
    assert exc_state["ExcessUmbrella_Umbrella_EachOccurrenceAmount_A"] == "4,000,000"
    assert exc_state["UnderlyingPolicy_OtherPolicy_CombinedSingleLimitAmount_A"].replace("$", "") == "7,000,000"
    changed = {k for k, v in exc_state.items() if v != stamped[EXCESS]["mapped"].get(k)}
    assert changed == {"UnderlyingPolicy_OtherPolicy_CombinedSingleLimitAmount_A"}
    # a box EDIT of the umbrella's limit on the base copy reaches the excess
    # copy's underlying row the same way (update_pdf -> propagate_fact_edits)
    gen3 = _generated(stamped)
    after3 = {**before, "umbrella_limit": {"value": "$8,000,000", "source": "producer"}}
    touched3 = propagate_fact_edits(gen3, "ACORD_131", before, after3, ["umbrella_limit"])
    assert EXCESS in touched3
    st3 = gen3[EXCESS]["field_state"]
    assert st3["UnderlyingPolicy_OtherPolicy_CombinedSingleLimitAmount_A"].replace("$", "") == "8,000,000"
    assert st3["ExcessUmbrella_Umbrella_EachOccurrenceAmount_A"] == "4,000,000"


def test_the_excess_copy_asks_the_client_nothing_about_its_policy(merged, stamped):
    import asyncio
    from services.arq_service import generate_arq_questions
    mf, flags, _docs = merged
    gen = _generated(stamped)
    questions = asyncio.run(generate_arq_questions(mf, flags, gen, [], []))
    for q in questions:
        assert EXCESS not in (q.get("form_ids") or []), q.get("field_name")


def test_update_pdf_keeps_a_copys_policy_box_on_that_copy():
    from routes import form_routes as fr
    src = Path(fr.__file__).read_text(encoding="utf-8")
    tree = ast.parse(src)
    fn = next(n for n in ast.walk(tree) if isinstance(n, ast.AsyncFunctionDef) and n.name == "update_pdf")
    body = ast.get_source_segment(src, fn)
    loop = body[body.index("for pdf_field, new_val in req.field_updates.items():"):]
    guard = loop.index("is_private_field(form_id, pdf_field)")
    assert guard < loop.index("for pattern, fact_key in _ACORD_FIELD_RULES:")
    assert "is_private_field(form_id, field_name)" in body      # the audit row names no fact


# =============================================================================
# 7. Scoring, rules, labels, files
# =============================================================================
def test_the_scorer_rules_by_the_form_and_scores_the_copys_view(merged):
    from services.sqs_service import calculate_sqs
    mf, flags, _docs = merged
    kw = dict(flags=flags, mapped_data={}, form_schema={}, hard_stops=[], soft_stops=[],
              tier2_score=50)
    exc = calculate_sqs(facts=mf, selected_form_ids=["ACORD_131", EXCESS], form_id=EXCESS, **kw)
    base = calculate_sqs(facts=mf, selected_form_ids=["ACORD_131", EXCESS], form_id="ACORD_131", **kw)
    assert exc["form_id"] == EXCESS and base["form_id"] == "ACORD_131"
    # the 131 rule set (umbrella SIR / attachment) read on each copy's own view.
    # Brent, 23 Oct 2026 (Z34-1 #3, reverses this test's 7 Oct "<"): the excess
    # states no SIR, but its attachment is the umbrella below - no deduction.
    from services.sqs_service import UMB_RETENTION_ESTABLISHED, umbrella_retention_state
    view = fi.facts_for_form(mf, EXCESS)
    assert "umbrella_sir" not in view
    assert umbrella_retention_state(view, flags) == UMB_RETENTION_ESTABLISHED
    assert exc["breakdown"]["structural_completeness"] == base["breakdown"]["structural_completeness"]


def test_form_keyed_rules_see_the_form_once(merged):
    from services.cross_form_validator import run_cross_form_validation
    mf, flags, _docs = merged
    a = run_cross_form_validation(mf, flags, {"ACORD_125", "ACORD_131"})
    b = run_cross_form_validation(mf, flags, {"ACORD_125", "ACORD_131", EXCESS})
    assert [i.get("code") for i in a] == [i.get("code") for i in b]
    assert pdf._package_form_ids({"_package_form_ids": [EXCESS]}) == {"ACORD_131"}
    from services.fact_state import lines_applied_for
    assert lines_applied_for([EXCESS]) == lines_applied_for(["ACORD_131"])


def test_labels_and_file_names_name_the_copy():
    from services.needs_attention import form_label
    from services.cover_service import _cover_form_label, _score_name
    from services.applicant_signing import form_label as sign_label
    from services.field_qa import _qa_label
    for fn in (form_label, _cover_form_label, sign_label, _qa_label):
        assert fn(EXCESS) == "ACORD 131 (Excess)"
    assert _qa_label("ACORD_137_CO") == "ACORD 137_CO"              # historic wording kept
    assert form_label("ACORD_137_CO") == "ACORD 137 CO"
    assert _score_name("ACORD_131") == "ACORD_131"
    assert fi.file_stem(EXCESS) == "ACORD_131_Excess"
    src = (BACKEND / "routes" / "download_routes.py").read_text(encoding="utf-8")
    assert 'f"{form_id}_' not in src and 'f"{fid}_' not in src     # every name through file_stem
    assert "file_stem(fid)" in src and "file_stem(form_id)" in src


def test_every_131_field_has_a_declared_layer_rule():
    schema = json.load(open(BACKEND / "forms_schemas" / "ACORD_131_schema.json"))
    unruled = [f for f in schema if ul.field_rule(f) is None]
    assert unruled == []
    for f in ("Insurer_FullName_A", "ExcessUmbrella_Umbrella_EachOccurrenceAmount_A",
              "UnderlyingPolicy_OtherPolicy_InsurerFullName_A", "PriorCoverage_PolicyNumberIdentifier_A",
              "CommercialUmbrellaLineOfBusiness_Question_ACBYesIndicator_A", "Policy_PolicyType_ExcessIndicator_A"):
        assert ul.is_private_field(f) and fi.is_private_field(EXCESS, f)
    # Brent, 23 Oct 2026 (Z34-1 #3): the GL / Auto / EL underlying blocks are the
    # same policies under every layer - one shared answer (tests/test_build25_forms.py).
    for f in ("GeneralLiability_EachOccurrence_LimitAmount_A", "GeneralLiability_OccurrenceIndicator_A",
              "UnderlyingPolicy_Automobile_InsurerFullName_A",
              "WorkersCompensationEmployersLiability_EmployersLiability_EachAccidentLimitAmount_A"):
        assert not ul.is_private_field(f) and not fi.is_private_field(EXCESS, f)
    for f in ("NamedInsured_FullName_A", "BusinessInformation_OperationsDescription_A",
              "CommercialUmbrellaLineOfBusiness_Question_AADCode_A", "LossHistory_ClaimDate_A",
              "ExcessUmbrella_PollutionLiability_InsuredEnvironmentalProtectionAgencyIdentifier_A"):
        assert not ul.is_private_field(f)
    assert ul.is_private_field("SomethingNew_Unknown_A")         # unknown: never shared
    assert not fi.is_private_field("ACORD_125", "Insurer_FullName_A")


# =============================================================================
# 8. The guard: no file path is built from a raw form id
# =============================================================================
_PATH_SUFFIXES = (".pdf", "_schema.json", "_alias.json", "_fieldmap.json")
_ID_NAMES = {"form_id", "fid", "form", "name", "base"}


def _formatted_path_names(fn_node):
    """Names formatted into a form-file path inside one function."""
    out = []
    for node in ast.walk(fn_node):
        if not isinstance(node, ast.JoinedStr):
            continue
        tail = "".join(v.value for v in node.values if isinstance(v, ast.Constant)
                       and isinstance(v.value, str))
        if not tail.endswith(_PATH_SUFFIXES):
            continue
        for v in node.values:
            if isinstance(v, ast.FormattedValue):
                out.append(ast.unparse(v.value))
    return out


def test_no_form_file_path_is_built_from_a_copy_id():
    """Every function that formats a form id into a schema / template / alias /
    fieldmap path routes the id through `base_form_id` - a second copy
    ("ACORD_131__excess") must never open or write a file of its own."""
    offenders = []
    files = list((BACKEND / "services").glob("*.py")) + list((BACKEND / "routes").glob("*.py")) \
        + [BACKEND / "worker.py"]
    for path in files:
        src = path.read_text(encoding="utf-8")
        tree = ast.parse(src)
        for fn in ast.walk(tree):
            if not isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            names = [n for n in _formatted_path_names(fn)
                     if n.split("(")[0].split(".")[-1] in _ID_NAMES or "form_id" in n]
            if not names:
                continue
            seg = ast.get_source_segment(src, fn) or ""
            if "base_form_id" in seg or all(("base_form_id(" in n or "file_stem(" in n)
                                            for n in names):
                continue
            # Ids read off the catalogue on disk (forms_index / a directory
            # listing) are base ids by construction - never a request's id.
            if "FORMS_INDEX" in seg or "listdir(" in seg:
                continue
            offenders.append(f"{path.name}:{fn.name} {names}")
    assert offenders == [], offenders


# =============================================================================
# 9. The frontend twin
# =============================================================================
@pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")
def test_the_frontend_names_a_copy_like_the_backend(tmp_path):
    fi_js = FRONTEND / "utils" / "formInstances.js"
    pg_js = FRONTEND / "utils" / "packageGeneration.js"
    ids = ["ACORD_131", "ACORD_137_CO", EXCESS, "ACORD_131__excess-2", "ACORD_131__Excess",
           "ACORD_131__umbrella", "ACORD_131__umbrella-2"]
    script = tmp_path / "check.mjs"
    script.write_text(
        f"import * as F from {json.dumps(fi_js.as_uri())};\n"
        f"import * as P from {json.dumps(pg_js.as_uri())};\n"
        f"const ids = {json.dumps(ids)};\n"
        "console.log(JSON.stringify({\n"
        " label: ids.map(F.formLabel), stem: ids.map(F.fileStem), base: ids.map(F.baseFormId),\n"
        " rows: P.formRows({ACORD_131: {}, ACORD_131__excess: {}}, ['ACORD_131', 'ACORD_131__excess'])\n"
        "        .map(r => r.label),\n"
        "}));\n", encoding="utf-8")
    run = subprocess.run(["node", str(script)], capture_output=True, text=True, timeout=60)
    assert run.returncode == 0, run.stderr
    o = json.loads(run.stdout)
    assert o["label"] == [fi.instance_label(i) for i in ids]
    assert o["stem"] == [fi.file_stem(i) for i in ids]
    assert o["base"] == [fi.base_form_id(i) for i in ids]
    assert o["rows"] == ["ACORD 131", "ACORD 131 (Excess)"]


# =============================================================================
# 10. Round 2 - a generated copy stays on ITS layer
# =============================================================================
LOWER_DOC = "Lower Excess Policy.pdf"
TRAVELERS = "TRAVELERS PROPERTY CASUALTY COMPANY OF AMERICA"
AMERISURE = "AMERISURE MUTUAL INSURANCE COMPANY"


def _lower_excess_doc(limit="$2,000,000", carrier="LOWER LAYER RE"):
    """An excess declarations that arrives AFTER generation and sorts BELOW the
    Travelers excess (a smaller limit; neither states an attachment point)."""
    src = next(d for d in _docs() if d["filename"] == EXCESS_DOC)
    facts = {k: None for k in src["facts"]}
    facts.update({
        "applicant_name": copy.deepcopy(src["facts"].get("applicant_name")),
        "umbrella_limit": limit,
        "umbrella_effective_date": "01/01/2025", "umbrella_expiration_date": "01/01/2026",
        "coverage_lines": [{"line": "Excess Liability", "carrier": carrier, "policy_number": None,
                            "premium": "$3,100", "effective_date": "01/01/2025",
                            "expiration_date": "01/01/2026"}],
        "dec_page_entries": [],
    })
    return {"doc_id": "lower-excess", "filename": LOWER_DOC, "doc_type": "dec_page",
            "flags": copy.deepcopy(src["flags"]), "facts": facts,
            "text": (f"COMMERCIAL EXCESS LIABILITY DECLARATIONS Insurer {carrier} Each Occurrence "
                     f"{limit} Policy Period 01/01/2025 to 01/01/2026 Premium $3,100")}


@pytest.fixture(scope="module")
def inserted(merged):
    """Generation binds both copies; THEN a lower excess layer is uploaded and
    the package re-merges, carrying the binding as `_finalize_pipeline` does."""
    mf = merged[0]
    generated = copy.deepcopy(mf)
    update = fi.binding_update(generated, ["ACORD_125", "ACORD_131", EXCESS])
    docs2 = _docs() + [_lower_excess_doc()]
    mf2, flags2 = es.merge_facts(docs2, es.select_primary_truth(docs2))
    positional = copy.deepcopy(mf2)
    assert fi.carry_bindings(mf2, generated) == [ul.BINDINGS_KEY]
    return {"generated": generated, "update": update, "positional": positional,
            "facts": mf2, "flags": flags2, "docs": docs2}


def test_generation_binds_every_131_copy_to_its_own_layer(merged):
    mf, _f, _d = merged
    facts = copy.deepcopy(mf)
    update = fi.binding_update(facts, ["ACORD_125", "ACORD_131", EXCESS])
    bound = update["facts"][ul.BINDINGS_KEY]
    assert set(bound) == {"", "excess"}
    assert bound[""]["layer"] == "umbrella" and bound[""]["own_documents"] == [UMBRELLA_DOC]
    assert bound["excess"]["layer"] == "excess" and bound["excess"]["own_documents"] == [EXCESS_DOC]
    assert facts[ul.BINDINGS_KEY] == bound                        # applied in memory too
    assert fi.binding_update(facts, ["ACORD_131", EXCESS]) == {}   # already bound: nothing new
    assert fi.binding_update(copy.deepcopy(mf), ["ACORD_125", "ACORD_130"]) == {}
    assert fi.binding_update(None, ["ACORD_131"]) == {}
    assert fi.binding_update({}, ["ACORD_131"]) == {}              # no umbrella-family policy
    for fid in ("ACORD_131", EXCESS):                               # binding changes no value
        a, b = fi.facts_for_form(mf, fid), fi.facts_for_form(facts, fid)
        assert {k: a.get(k) for k in ul.LAYER_FACTS} == {k: b.get(k) for k in ul.LAYER_FACTS}
        assert a[ul.MARKER_KEY] == b[ul.MARKER_KEY]
    assert ul.BINDINGS_KEY in pdf._GAP_FILL_FACTS_EXCLUDE             # never prompt content


def test_a_lower_layer_after_generation_never_repoints_a_copy(inserted):
    # The defect, positional: the generated "excess" copy would print the new layer.
    assert fi.facts_for_form(inserted["positional"], EXCESS)[ul.MARKER_KEY]["carrier"] == "LOWER LAYER RE"
    facts = inserted["facts"]
    base = fi.facts_for_form(facts, "ACORD_131")
    exc = fi.facts_for_form(facts, EXCESS)
    new = fi.facts_for_form(facts, "ACORD_131__excess-2")
    assert base[ul.MARKER_KEY]["carrier"] == AMERISURE and base[ul.MARKER_KEY]["index"] == 0
    assert _v(base, "umbrella_limit") == "$5,000,000"
    m = exc[ul.MARKER_KEY]
    assert (m["carrier"], m["key"], m["index"]) == (TRAVELERS, "excess", 2)
    assert _v(exc, "umbrella_limit") == "$4,000,000"
    assert m["below"]["carrier"] == "LOWER LAYER RE" and m["below"]["limit"] == "$2,000,000"
    n = new[ul.MARKER_KEY]
    assert (n["carrier"], n["key"], n["index"]) == ("LOWER LAYER RE", "excess-2", 1)
    assert _v(new, "umbrella_limit") == "$2,000,000"
    assert n["below"]["carrier"] == AMERISURE
    # the DOCUMENTS decided: the Travelers record id changed under the binding
    assert m["record"] not in inserted["update"]["facts"][ul.BINDINGS_KEY]["excess"]["records"]
    assert fi.instance_ids(facts) == ["ACORD_131__excess-2", EXCESS]      # attachment order
    assert fi.instance_label("ACORD_131__excess-2") == "ACORD 131 (Excess 2)"


def test_the_existing_copy_stamps_its_own_policy_after_the_insert(inserted):
    session = {"facts": inserted["facts"], "flags": inserted["flags"], "docs": inserted["docs"],
               "all_forms": fs.filter_available_forms(fs.load_all_forms()),
               "selected_form_ids": ["ACORD_125", "ACORD_131", EXCESS]}
    meta = fi.form_meta_for(session["all_forms"], EXCESS, session["facts"])
    m = fs.process_single_form(meta, session, dict(_NO_LLM))["mapped"]
    assert m["Insurer_FullName_A"] == TRAVELERS
    assert m["ExcessUmbrella_Umbrella_EachOccurrenceAmount_A"] == "4,000,000"
    assert m["UnderlyingPolicy_OtherPolicy_InsurerFullName_A"] == "LOWER LAYER RE"   # the layer below now
    base = fi.form_meta_for(session["all_forms"], "ACORD_131", session["facts"])
    mb = fs.process_single_form(base, session, dict(_NO_LLM))["mapped"]
    assert mb["Insurer_FullName_A"] == AMERISURE


def test_the_new_layer_is_offered_under_a_new_key(inserted):
    facts, flags, docs = inserted["facts"], inserted["flags"], inserted["docs"]
    recs = fs.match_forms_deterministic(facts, flags, text=" ".join(d["text"] for d in docs))
    by_id = {r["form_id"]: r for r in recs}
    assert {"ACORD_131", EXCESS, "ACORD_131__excess-2"} <= set(by_id)
    assert by_id["ACORD_131"]["reason_label"].startswith(f"Umbrella layer - {AMERISURE}")
    assert by_id["ACORD_131__excess-2"]["reason_label"].startswith(
        "Excess layer above the umbrella - LOWER LAYER RE")
    assert by_id[EXCESS]["reason_label"].startswith(f"Excess layer 2 above the excess layer - {TRAVELERS}")
    present = {"ACORD_125", "ACORD_131", EXCESS}
    offered = [r["form_id"] for r in recs
               if fi.base_form_id(r["form_id"]) == "ACORD_131" and r["form_id"] not in present]
    assert offered == ["ACORD_131__excess-2"]
    forms = fs.filter_available_forms(fs.load_all_forms())
    meta = fi.form_meta_for(forms, "ACORD_131__excess-2", facts)
    assert meta["form_name"].startswith("ACORD 131 (Excess 2) - ")
    # adding it binds it, and the bound copies keep their keys
    added = copy.deepcopy(facts)
    upd = fi.binding_update(added, ["ACORD_131__excess-2"])
    assert set(upd["facts"][ul.BINDINGS_KEY]) == {"", "excess", "excess-2"}
    assert upd["facts"][ul.BINDINGS_KEY]["excess-2"]["own_documents"] == [LOWER_DOC]
    assert fi.instance_ids(added) == ["ACORD_131__excess-2", EXCESS]


def test_every_re_merge_carries_the_binding_and_every_generation_write_stores_it():
    src = (BACKEND / "services" / "extraction_pipeline.py").read_text(encoding="utf-8")
    fn = next(n for n in ast.walk(ast.parse(src))
              if isinstance(n, ast.AsyncFunctionDef) and n.name == "_finalize_pipeline")
    body = ast.get_source_segment(src, fn)
    at = body.index("carry_bindings(merged_facts, prior_facts)")
    assert body.index("carry_and_apply(") < at < body.index("match_forms(merged_facts")
    writers = {("routes", "form_routes.py"): ("select_forms_bulk", "_bg_lite_generate",
                                              "lite_generate_internal"),
               ("services", "form_addition.py"): ("add_form_to_session",),
               ("", "worker.py"): None}
    for (folder, name), fns in writers.items():
        path = BACKEND / folder / name if folder else BACKEND / name
        text = path.read_text(encoding="utf-8")
        tree = ast.parse(text)
        if fns is None:
            assert "binding_update(" in text, name
            continue
        for fname in fns:
            node = next(n for n in ast.walk(tree) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
                        and n.name == fname)
            seg = ast.get_source_segment(text, node)
            assert "generated_forms" in seg and "binding_update(" in seg, (name, fname)
    merged, prior = {}, {ul.BINDINGS_KEY: {"": {"layer": "umbrella", "documents": ["u.pdf"]}}}
    assert fi.carry_bindings(merged, prior) == [ul.BINDINGS_KEY] and merged == prior
    kept = {ul.BINDINGS_KEY: {"excess": {}}}
    assert fi.carry_bindings(kept, prior) == [] and kept == {ul.BINDINGS_KEY: {"excess": {}}}
    assert fi.carry_bindings(None, prior) == [] and fi.carry_bindings({}, None) == []


def _drec(rid, layer, carrier, sources, number=None, premium=None, producer=None, **limits):
    rec = _rec(rid, layer, carrier, sources, number, premium)
    rec["printings"]["policy_number"] = [number] if number else []
    if producer:
        rec["producer_added"] = producer
    rec.update(limits)
    return rec


def _bind(facts, *ids):
    fi.binding_update(facts, list(ids))
    return facts


def test_an_umbrella_arriving_under_a_single_excess_keeps_the_plain_131_on_the_excess():
    exc = _drec("umbrella~excess#E1", "excess", "Top Re", ["e.pdf"], "E1", 5.0)
    facts = _bind({"_line_records": [exc], "umbrella_limit": "$4,000,000"}, "ACORD_131")
    assert fi.facts_for_form(facts, "ACORD_131") is facts           # one layer: unchanged
    umb = _drec("umbrella#U1", "umbrella", "Base Mutual", ["u.pdf"], "U1", 9.0)
    later = {**facts, "_line_records": [umb, exc], "umbrella_limit": "$5,000,000",
             ul.DOCS_KEY: {"u.pdf": {"umbrella_limit": "$5,000,000"},
                           "e.pdf": {"umbrella_limit": "$4,000,000"}}}
    positional = {k: v for k, v in later.items() if k != ul.BINDINGS_KEY}
    assert fi.facts_for_form(positional, "ACORD_131")[ul.MARKER_KEY]["carrier"] == "Base Mutual"
    plain = fi.facts_for_form(later, "ACORD_131")
    pm = plain[ul.MARKER_KEY]
    assert (pm["carrier"], pm["index"], pm["layer"]) == ("Top Re", 1, "excess")
    assert _v(plain, "umbrella_limit") == "$4,000,000"
    assert pm["below"]["carrier"] == "Base Mutual" and pm["below"]["limit"] == "$5,000,000"
    assert fi.instance_ids(later) == ["ACORD_131__umbrella"]
    um = fi.facts_for_form(later, "ACORD_131__umbrella")[ul.MARKER_KEY]
    assert (um["carrier"], um["index"], um["key"]) == ("Base Mutual", 0, "umbrella")
    assert fi.instance_label("ACORD_131__umbrella") == "ACORD 131 (Umbrella)"
    assert fi.file_stem("ACORD_131__umbrella") == "ACORD_131_Umbrella"
    assert [(x["form_id"], x["reason"]) for x in ul.recommendation_layers(later)] == [
        ("ACORD_131__umbrella", "Umbrella layer - Base Mutual"),
        ("ACORD_131", "Excess layer above the umbrella - Top Re")]
    # each copy names its OWN layer's limit in the recommendation evidence
    assert "Excess limit: $4,000,000" in (fs._build_trigger_facts("ACORD_131", plain)[1] or "")
    assert "Umbrella limit: $5,000,000" in (fs._build_trigger_facts(
        "ACORD_131__umbrella", fi.facts_for_form(later, "ACORD_131__umbrella"))[1] or "")
    # a person's package-level answer is the PLAIN 131's, never the new copy's
    answered = {**later, "umbrella_limit": {"value": "$6,000,000", "source": "producer"}}
    assert _v(fi.facts_for_form(answered, "ACORD_131"), "umbrella_limit") == "$6,000,000"
    assert _v(fi.facts_for_form(answered, "ACORD_131__umbrella"), "umbrella_limit") == "$5,000,000"


def test_a_copy_whose_layer_left_prints_no_layer_and_its_key_is_never_reused():
    umb = _drec("umbrella#U1", "umbrella", "Base Mutual", ["u.pdf"], "U1", 9.0)
    p1 = _drec("umbrella~excess#added-PL1", "excess", "First Re", [], "P1", 1.0, producer="PL1")
    facts = _bind({"_line_records": [umb, p1]}, "ACORD_131", EXCESS)
    assert fi.facts_for_form(facts, EXCESS)[ul.MARKER_KEY]["carrier"] == "First Re"
    p2 = _drec("umbrella~excess#added-PL2", "excess", "Second Re", [], "P1", 1.0, producer="PL2")
    later = {**facts, "_line_records": [umb, p2]}            # the producer removed PL1, added PL2
    gone = fi.facts_for_form(later, EXCESS)
    assert gone[ul.MARKER_KEY].get("missing") is True and _umb_rows(gone) == []
    assert fi.instance_ids(later) == ["ACORD_131__excess-2"]
    assert fi.facts_for_form(later, "ACORD_131__excess-2")[ul.MARKER_KEY]["carrier"] == "Second Re"
    assert not fi.is_valid_form_id(later, EXCESS)
    assert fi.form_meta_for(fs.filter_available_forms(fs.load_all_forms()), EXCESS, later) is None
    assert fi.facts_for_form(later, "ACORD_131")[ul.MARKER_KEY]["carrier"] == "Base Mutual"
    # the PLAIN copy's layer leaves (a producer-added umbrella removed): it prints
    # no layer, and the excess copy keeps the one layer left
    pu = _drec("umbrella#added-PL5", "umbrella", "Prod Mutual", [], "PU", 2.0, producer="PL5")
    ex = _drec("umbrella~excess#E1", "excess", "Top Re", ["e.pdf"], "E1", 5.0)
    both = _bind({"_line_records": [pu, ex], "umbrella_limit": "$4,000,000"}, "ACORD_131", EXCESS)
    alone = {**both, "_line_records": [ex]}
    assert fi.facts_for_form(alone, "ACORD_131")[ul.MARKER_KEY].get("missing") is True
    left = fi.facts_for_form(alone, EXCESS)
    assert left[ul.MARKER_KEY]["carrier"] == "Top Re" and left[ul.MARKER_KEY]["count"] == 1
    assert _v(left, "umbrella_limit") == "$4,000,000"
    assert fi.instance_ids(alone) == [EXCESS]


def test_a_single_umbrella_package_stays_byte_identical_once_bound(single):
    mf, flags, docs = single
    facts = copy.deepcopy(mf)
    upd = fi.binding_update(facts, ["ACORD_125", "ACORD_131"])
    assert set(upd["facts"][ul.BINDINGS_KEY]) == {""}
    assert fi.facts_for_form(facts, "ACORD_131") is facts            # the same object
    assert fi.instance_ids(facts) == [] and ul.recommendation_layers(facts) == []
    recs = fs.match_forms_deterministic(facts, flags, text=" ".join(d["text"] for d in docs))
    base = next(r for r in recs if r["form_id"] == "ACORD_131")
    assert base["reason_label"].startswith("Umbrella / Excess")
    assert not any(fi.is_instance(r["form_id"]) for r in recs)


def test_layer_identity_matching_edges():
    umb = _drec("umbrella#U1", "umbrella", "Base Mutual", ["u.pdf"], "U1", 9.0)
    exc = _drec("umbrella~excess#E1", "excess", "Top Re", ["e.pdf", "cert.pdf"], "E1", 5.0)
    facts = _bind({"_line_records": [umb, exc]}, "ACORD_131", EXCESS)
    new = _drec("umbrella~excess#N1", "excess", "New Re", ["n.pdf"], "N1", 2.0)

    def keys(*recs):
        return ul._assign({**facts, "_line_records": list(recs)})[1]

    # the same contract re-printed under a new file name is the same layer
    renamed = _drec("umbrella~excess#E1x", "excess", "Top Re", ["e-final.pdf"], "E-1", 5.0)
    assert keys(umb, renamed, new)["excess"] == 1
    # a shared certificate with a disagreeing number names another policy
    shared = _drec("umbrella~excess#S1", "excess", "Other Re", ["cert.pdf"], "S9", 5.0)
    got = keys(umb, shared)
    assert got["excess"] is None and got["excess-2"] == 1
    # a layer of the other kind is never a bound copy's layer
    umb_from_e = _drec("umbrella#E1", "umbrella", "Top Re", ["e.pdf"], "E1", 5.0)
    assert keys(umb_from_e)["excess"] is None
    # malformed stored bindings are ignored -> positional
    for junk in ("x", ["a"], {"Bad Key": {}}, {"": "x"}, {"excess": None}):
        bad = {"_line_records": [umb, exc], ul.BINDINGS_KEY: junk}
        assert fi.instance_ids(bad) == [EXCESS]
    # a binding's producer id is definitive for a layer the producer added
    p = _drec("umbrella~excess#added-PL1", "excess", "Prod Re", [], "P1", 1.0, producer="PL1")
    pf = _bind({"_line_records": [umb, p]}, "ACORD_131", EXCESS)
    p_edited = {**p, "policy_number": "P1-EDITED", "carrier_name": "Prod Re Corrected",
                "id": "umbrella~excess#added-PL1b", "printings": {"carrier_name": ["x"]}}
    assert ul._assign({**pf, "_line_records": [umb, p_edited]})[1]["excess"] == 1
    # a rival umbrella slot keeps its copy when the producer's rival leaves
    rival = _drec("umbrella#added-PL7", "umbrella", "Rival", [], None, 1.0, producer="PL7")
    rf = _bind({"_line_records": [umb, rival, exc]}, "ACORD_131", EXCESS)
    assert ul._assign({**rf, "_line_records": [umb, exc]})[1] == {"": 0, "excess": 1}


# =============================================================================
# 11. Round 2 - a layer the PRODUCER added prints the limits they stated
# =============================================================================
def _producer_tower(**limits):
    rows = [{"line": "Commercial Umbrella", "carrier": "Base Mutual", "policy_number": "U-100",
             "premium": "$9,000", "effective_date": "01/01/2026", "expiration_date": "01/01/2027"},
            {"line": "Excess Liability", "carrier": "Producer Re", "policy_number": "PX-9",
             "premium": "$1,000", "effective_date": "01/01/2026", "expiration_date": "01/01/2027",
             "_producer_added": "PL1", **limits}]
    docs = [{"filename": "u.pdf", "text": "COMMERCIAL UMBRELLA U-100 Base Mutual",
             "facts": {"coverage_lines": [dict(rows[0])], "umbrella_limit": "$5,000,000"}}]
    facts = {"coverage_lines": rows, "umbrella_limit": "$5,000,000", "umbrella_sir": "$0"}
    facts["_line_records"] = es._build_line_records(facts, docs)
    facts[ul.DOCS_KEY] = {"u.pdf": {"umbrella_limit": "$5,000,000", "umbrella_sir": "$0"}}
    return facts


def _stamp_box(facts, fid):
    schema = pdf.extract_form_schema(os.path.join(pdf.TEMPLATE_DIR, "ACORD_131.pdf"), "ACORD_131")
    mapped, _unmatched, _det = pdf.compute_form_gaps(fid, schema, dict(facts))
    return mapped


def test_the_limit_field_names_agree_with_policies():
    from services.policy_lines import UMBRELLA_LIMIT_FIELDS
    assert set(UMBRELLA_LIMIT_FIELDS) == set(ul._PRODUCER_LIMIT_FIELDS.values()) | {
        ul._PRODUCER_AGGREGATE_FIELD}


def test_a_producer_added_layer_prints_the_limits_the_producer_stated():
    facts = _producer_tower(limit_each_occurrence="$2,000,000", limit_aggregate="$4,000,000",
                            sir="$10,000")
    rec = next(r for r in facts["_line_records"] if r.get("producer_added"))
    assert rec["limit_each_occurrence"] == "$2,000,000" and rec["sources"] == []
    v = fi.facts_for_form(facts, EXCESS)
    assert v["umbrella_limit"]["value"] == "2000000" and v["umbrella_limit"]["source"] == "producer"
    assert v["umbrella_sir"]["value"] == "10000"
    assert v[ul.MARKER_KEY]["producer_layer"] is True and v[ul.MARKER_KEY]["aggregate"] == "4000000"
    m = _stamp_box(facts, EXCESS)
    assert m["Insurer_FullName_A"] == "Producer Re"
    assert m["ExcessUmbrella_Umbrella_EachOccurrenceAmount_A"] == "2000000"
    assert m["ExcessUmbrella_Umbrella_AggregateAmount_A"] == "4000000"
    assert m["ExcessUmbrella_Umbrella_DeductibleOrRetentionAmount_A"] == "10000"
    assert m["UnderlyingPolicy_OtherPolicy_InsurerFullName_A"] == "Base Mutual"
    b = _stamp_box(facts, "ACORD_131")                               # the umbrella is untouched
    assert b["ExcessUmbrella_Umbrella_EachOccurrenceAmount_A"] == "$5,000,000"
    assert b["ExcessUmbrella_Umbrella_AggregateAmount_A"] == "$5,000,000"


def test_a_producer_added_layer_without_limits_prints_none():
    facts = _producer_tower()
    v = fi.facts_for_form(facts, EXCESS)
    assert "umbrella_limit" not in v and "umbrella_sir" not in v
    assert v[ul.MARKER_KEY]["aggregate"] is None
    m = _stamp_box(facts, EXCESS)
    for box in ("ExcessUmbrella_Umbrella_EachOccurrenceAmount_A", "ExcessUmbrella_Umbrella_AggregateAmount_A",
                "ExcessUmbrella_Umbrella_DeductibleOrRetentionAmount_A"):
        assert not m.get(box), box
    none_said = _producer_tower(limit_each_occurrence="none")
    assert "umbrella_limit" not in fi.facts_for_form(none_said, EXCESS)


def test_a_producer_layer_feeds_the_layer_above_and_the_attachment_order():
    umb = _drec("umbrella#U1", "umbrella", "Base Mutual", ["u.pdf"], "U1", 9.0)
    doc_exc = _drec("umbrella~excess#E1", "excess", "Doc Re", ["e.pdf"], "E1", 5.0)
    prod = _drec("umbrella~excess#added-PL1", "excess", "Prod Re", [], "P1", 1.0, producer="PL1",
                 limit_each_occurrence="$2,000,000")
    facts = {"_line_records": [umb, doc_exc, prod],
             ul.DOCS_KEY: {"u.pdf": {"umbrella_limit": "$5,000,000"},
                           "e.pdf": {"umbrella_limit": "$4,000,000"}}}
    assert [s["record"]["carrier_name"] for s in ul.ordered_layers(facts)] == \
        ["Base Mutual", "Prod Re", "Doc Re"]                         # $2M sits below $4M
    top = fi.facts_for_form(facts, "ACORD_131__excess-2")[ul.MARKER_KEY]
    assert top["carrier"] == "Doc Re" and top["below"]["carrier"] == "Prod Re"
    assert top["below"]["limit"] == "2000000"


def test_a_single_producer_added_umbrella_prints_its_limits():
    rec = _drec("umbrella#added-PL1", "umbrella", "Prod Mutual", [], "P1", 1.0, producer="PL1",
                limit_each_occurrence="$1,000,000", limit_aggregate="$2,000,000")
    facts = {"_line_records": [rec]}
    v = fi.facts_for_form(facts, "ACORD_131")
    assert v is not facts and v["umbrella_limit"]["value"] == "1000000"
    assert v[ul.MARKER_KEY]["aggregate"] == "2000000" and v[ul.MARKER_KEY]["count"] == 1
    m = _stamp_box(facts, "ACORD_131")
    assert m["ExcessUmbrella_Umbrella_EachOccurrenceAmount_A"] == "1000000"
    assert m["ExcessUmbrella_Umbrella_AggregateAmount_A"] == "2000000"
    bare = {"_line_records": [{**rec, "limit_each_occurrence": None, "limit_aggregate": None}]}
    assert fi.facts_for_form(bare, "ACORD_131") is bare              # nothing stated: unchanged
    assert fi.instance_ids(facts) == []


def test_the_policies_store_seam_offers_a_lower_added_layer_under_a_new_key(merged):
    """POLICIES adds an excess layer AFTER generation whose limit sorts it below
    the Travelers excess: the generated copies keep their layers, the add-form
    offer names the next free key, and the new copy prints the producer's limits."""
    from services import policy_lines as pl
    mf, flags, docs = merged
    facts, flags = copy.deepcopy(mf), copy.deepcopy(flags)
    fi.binding_update(facts, ["ACORD_125", "ACORD_131", EXCESS])
    facts[pl.STORE_KEY] = {"v": pl.STORE_VERSION, "edits": {}, "flags_set": {}, "added": [{
        "id": "PL1", "line_key": "excess", "carrier_name": "Added Re", "policy_number": "AX-1",
        "effective_date": "01/01/2025", "expiration_date": "01/01/2026", "premium": "$2,500",
        "limit_each_occurrence": "$1,000,000", "limit_aggregate": "$1,000,000", "sir": "$0"}]}
    pl.apply_producer_policy_lines(facts, flags, docs, restore_flags=True)
    assert [s["record"]["carrier_name"] for s in ul.ordered_layers(facts)] == \
        [AMERISURE, "Added Re", TRAVELERS]
    assert fi.facts_for_form(facts, EXCESS)[ul.MARKER_KEY]["carrier"] == TRAVELERS
    session = {"facts": facts, "flags": flags, "docs": docs,
               "all_forms": fs.filter_available_forms(fs.load_all_forms()),
               "selected_form_ids": ["ACORD_125", "ACORD_131", EXCESS],
               "generated_forms": {"ACORD_125": {}, "ACORD_131": {}, EXCESS: {}}}
    assert [o["form_id"] for o in pl.form_offers(session)] == ["ACORD_131__excess-2"]
    v = fi.facts_for_form(facts, "ACORD_131__excess-2")
    assert v[ul.MARKER_KEY]["carrier"] == "Added Re" and v["umbrella_limit"]["value"] == "1000000"
    assert v["umbrella_sir"]["value"] == "0"


# =============================================================================
# 12. Round 2 - the EPIC / Vertafore exports name the ACORD form beside the copy
# =============================================================================
def test_both_exports_carry_the_base_form_id_beside_the_copy_id():
    from routes import form_routes as fr
    src = Path(fr.__file__).read_text(encoding="utf-8")
    builders = [n for n in ast.walk(ast.parse(src))
                if isinstance(n, ast.FunctionDef) and n.name == "_build_payload"]
    assert len(builders) == 2
    for fn in builders:
        ret = next(n for n in ast.walk(fn) if isinstance(n, ast.Return))
        keys = [k.value for k in ret.value.keys if isinstance(k, ast.Constant)]
        assert keys[:3] == ["form_id", "form_name", "base_form_id"] and "fields" in keys
        assert "_fi.base_form_id(fid)" in ast.get_source_segment(src, fn)
