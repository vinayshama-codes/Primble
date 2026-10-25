"""Build 25 (23 Oct 2026) - Brent's 23 Oct answers on the forms (Z34-1 #3, #5).

#3 "Yes, list the applicable underlying coverages - but do not automatically
require all three. Show applicable: GL, Auto, Employers Liability, Other
applicable underlying liability coverage." / "For follow-form excess, if we can
establish the attachment point/underlying structure, do not deduct points just
because there is no separate retention/SIR. But if we cannot establish the
attachment point or underlying structure, flag it for review."

#5 "Redaction is a byproduct of testing, where users want to protect client
ID. In these cases, partial is acceptable." (the ACORD 125 POLICY PREMIUM total)

The tower is the client's own Choice Electric package (session ca93ed8f,
`tests/fixtures/choice_electric_pol_6oct.json`): the Amerisure Mutual umbrella
over GL / Auto / WC-EL, the Travelers following-form excess above it.
"""
import copy
import json
from pathlib import Path

import pytest

from services import extraction_service as es
from services import form_instances as fi
from services import form_service as fs
from services import needs_attention as na
from services import pdf_service as pdf
from services import question_eligibility as qe
from services import sqs_service as sqs
from services import umbrella_layers as ul
from tests.test_redacted_policies_listed_14oct import _CE_LINES, _CE_RECORDS, _rec

BACKEND = Path(__file__).resolve().parent.parent
_FIXTURE = BACKEND / "tests" / "fixtures" / "choice_electric_pol_6oct.json"
EXCESS = "ACORD_131__excess"
_NO_LLM = {"filled_values": {}, "raw_text_fields": set(), "question_grounding": {}}

_GL_AUTO_EL_BOXES = (
    "UnderlyingPolicy_GeneralLiability_InsurerFullName_A",
    "UnderlyingPolicy_GeneralLiability_PolicyEffectiveDate_A",
    "GeneralLiability_EachOccurrence_LimitAmount_A",
    "GeneralLiability_GeneralAggregate_LimitAmount_A",
    "UnderlyingPolicy_Automobile_InsurerFullName_A",
    "Vehicle_CombinedSingleLimit_EachAccidentAmount_A",
    "UnderlyingCoverage_Coverage_AnyAutoIndicator_A",
    "UnderlyingPolicy_EmployersLiability_InsurerFullName_A",
    "WorkersCompensationEmployersLiability_EmployersLiability_EachAccidentLimitAmount_A",
)


@pytest.fixture(scope="module")
def merged():
    docs = copy.deepcopy(json.load(open(_FIXTURE))["docs"])
    mf, flags = es.merge_facts(docs, es.select_primary_truth(docs))
    return mf, flags, docs


@pytest.fixture(scope="module")
def stamped(merged):
    mf, flags, docs = merged
    session = {"facts": mf, "flags": flags, "docs": docs,
               "all_forms": fs.filter_available_forms(fs.load_all_forms()),
               "selected_form_ids": ["ACORD_125", "ACORD_131", EXCESS]}
    out = {}
    for fid in ("ACORD_131", EXCESS):
        meta = fi.form_meta_for(session["all_forms"], fid, session["facts"])
        out[fid] = fs.process_single_form(meta, session, dict(_NO_LLM))["mapped"]
    return out


def _excess_view(merged):
    mf, flags, _docs = merged
    return fi.facts_for_form({**mf, **flags}, EXCESS)


# =============================================================================
# #3a - the excess 131 lists the applicable underlying lines
# =============================================================================
def test_the_excess_131_prints_the_applicable_lines_beside_the_layer_below(stamped):
    base, exc = stamped["ACORD_131"], stamped[EXCESS]
    for box in _GL_AUTO_EL_BOXES:
        assert exc.get(box), box
        assert exc[box] == base[box], box                 # printed exactly as the plain 131 prints it
    # OTHER POLICY row A is still the umbrella it sits on
    assert exc["UnderlyingPolicy_OtherPolicy_PolicyTypeDescription_A"] == "Commercial Liability Umbrella"
    assert exc["UnderlyingPolicy_OtherPolicy_InsurerFullName_A"] == "AMERISURE MUTUAL INSURANCE COMPANY"
    # no further liability line the umbrella schedules (Cyber / EBL are not) -
    # row B, and the expiring-policy box, stay blank
    assert not exc.get("UnderlyingPolicy_OtherPolicy_InsurerFullName_B")
    assert not exc.get("PriorCoverage_PolicyNumberIdentifier_A")
    # the excess layer's own limit is still its own
    assert exc["ExcessUmbrella_Umbrella_EachOccurrenceAmount_A"] == "4,000,000"


def test_the_marker_names_the_lines_the_umbrella_below_sits_over(merged):
    mf, flags, _docs = merged
    v = _excess_view(merged)
    m = v[ul.MARKER_KEY]
    assert m["underlying_lines"] == ["general_liab", "auto", "workers_comp"]
    assert {r.get("line") for r in m["base_underlying_policies"]} >= {"General Liability",
                                                                      "Automobile Liability"}
    assert sqs._fv(v, "underlying_policies") == []      # the excess's own schedule stays its own
    plain = fi.facts_for_form({**mf, **flags}, "ACORD_131")
    assert "underlying_lines" not in plain[ul.MARKER_KEY]


def test_never_all_three_by_default():
    assert ul.applicable_underlying_lines({}) == []
    assert ul.applicable_underlying_lines(None) == []
    assert ul.applicable_underlying_lines({"has_general_liability": True}) == ["general_liab"]
    assert ul.applicable_underlying_lines(
        {"has_general_liability": True, "has_auto_coverage": True}) == ["general_liab", "auto"]


def _upper(lines, **over):
    held = {"key": "excess", "index": 1, "count": 2, "layer": "excess",
            "below": {"line_printed": "Commercial Liability Umbrella", "carrier": "UMBRELLA CO",
                      "limit": "$5,000,000"},
            "underlying_lines": list(lines), "base_underlying_policies": []}
    held.update(over)
    return {"_form_id": "ACORD_131", ul.MARKER_KEY: held,
            "coverage_lines": [{"line": "Commercial General Liability", "carrier": "ACME INSURANCE COMPANY",
                                "premium": "$1,000", "policy_number": "GL-1234",
                                "effective_date": "01/01/2025", "expiration_date": "01/01/2026"}]}


def test_a_line_that_does_not_apply_stays_an_owned_blank():
    f = _upper(["general_liab"])
    box = pdf._resolve_upper_layer_box
    assert box("UnderlyingPolicy_GeneralLiability_InsurerFullName_A", f) == "ACME INSURANCE COMPANY"
    assert box("GeneralLiability_EachOccurrence_LimitAmount_A", f) is pdf._SCHED_SKIP
    for blank in ("UnderlyingPolicy_Automobile_InsurerFullName_A",
                  "Vehicle_CombinedSingleLimit_EachAccidentAmount_A",
                  "UnderlyingCoverage_Coverage_AnyAutoIndicator_A",
                  "UnderlyingPolicy_EmployersLiability_InsurerFullName_A",
                  "WorkersCompensationEmployersLiability_EmployersLiability_EachAccidentLimitAmount_A",
                  "PriorCoverage_PolicyNumberIdentifier_A",
                  "UnderlyingCoverage_Coverage_AircraftLiabilityIndicator_A",
                  "UnderlyingPolicy_OtherPolicy_InsurerFullName_B"):
        assert box(blank, f) is None, blank
    # row A is the layer below, as before
    assert box("UnderlyingPolicy_OtherPolicy_InsurerFullName_A", f) == "UMBRELLA CO"
    # a copy whose layer left prints no underlying line at all
    gone = _upper(["general_liab"], missing=True)
    assert box("UnderlyingPolicy_GeneralLiability_InsurerFullName_A", gone) is None


def test_the_lowest_layer_and_other_forms_never_reach_the_rule():
    f = _upper(["general_liab"], index=0, layer="umbrella")
    assert pdf._resolve_upper_layer_box("UnderlyingPolicy_Automobile_InsurerFullName_A", f) is pdf._SCHED_SKIP
    g = {**_upper(["general_liab"]), "_form_id": "ACORD_126"}
    assert pdf._resolve_upper_layer_box("GeneralLiability_EachOccurrence_LimitAmount_A", g) is pdf._SCHED_SKIP


# =============================================================================
# #3b - SIR OR attachment point; an excess's attachment from what it sits on
# =============================================================================
def _score(view, flags):
    return sqs.calculate_sqs(view, flags, {}, {}, [EXCESS], [], [], 0, form_id=EXCESS)


def _review_recs(res):
    return [r for r in res.get("recommendations") or []
            if r.get("rec_id") == "rec_umbrella_attachment_review"]


def test_an_excess_with_its_attachment_known_and_no_sir_loses_nothing(merged):
    _mf, flags, _docs = merged
    v = _excess_view(merged)
    assert "umbrella_sir" not in v and not sqs._fv(v, "umbrella_attachment_point")
    assert sqs.umbrella_retention_state(v, flags) == sqs.UMB_RETENTION_ESTABLISHED
    assert sqs._umbrella_retention_checks(v, flags) == [True]
    with_sir = {**v, "umbrella_sir": "$10,000"}
    assert sqs.umbrella_retention_state(with_sir, flags) == sqs.UMB_RETENTION_STATED
    a, b = _score(v, flags), _score(with_sir, flags)
    assert a["sqs_score"] == b["sqs_score"]
    assert a["breakdown"] == b["breakdown"]
    assert not _review_recs(a)
    # ...and the SIR is not asked for it
    assert sqs.umbrella_sir_not_needed(v, flags)


def _single(layer, **over):
    rec = _rec("umbrella", "SOLO EXCESS CO", 5000.0, number="XS-1", layer=layer,
               printed="Excess Liability" if layer == "excess" else "Commercial Umbrella")
    f = {"_line_records": [rec],
         "coverage_lines": [{"line": rec["line_printed"], "carrier": "SOLO EXCESS CO",
                             "premium": "$5,000", "policy_number": "XS-1",
                             "effective_date": "01/01/2025", "expiration_date": "01/01/2026"}],
         "umbrella_limit": "$5,000,000", "applicant_name": "Solo Builders LLC"}
    f.update(over)
    return f


def test_an_excess_with_neither_known_is_flagged_never_deducted():
    flags = {"has_umbrella": True}
    exc = _single("excess")
    assert sqs._umbrella_is_excess_layer(exc)
    assert sqs.umbrella_retention_state(exc, flags) == sqs.UMB_RETENTION_REVIEW
    assert sqs._umbrella_retention_checks(exc, flags) == []        # no item, no deduction
    res = sqs.calculate_sqs(exc, flags, {}, {}, ["ACORD_131"], [], [], 0, form_id="ACORD_131")
    flag = _review_recs(res)
    assert len(flag) == 1 and flag[0]["score_impact"] == 0 and flag[0]["unscored"]
    assert flag[0]["field"] == "umbrella_attachment_point"
    # the same package as a PRIMARY umbrella is charged the item, as always
    prim = _single("umbrella")
    assert not sqs._umbrella_is_excess_layer(prim)
    assert sqs._umbrella_retention_checks(prim, flags) == [False]
    pres = sqs.calculate_sqs(prim, flags, {}, {}, ["ACORD_131"], [], [], 0, form_id="ACORD_131")
    assert not _review_recs(pres)
    assert res["sqs_score"] >= pres["sqs_score"]
    assert res["breakdown"]["structural_completeness"] > pres["breakdown"]["structural_completeness"]
    # a stated attachment point - or an underlying limit - settles it
    for known in ({"umbrella_attachment_point": "$1,000,000"}, {"gl_each_occurrence": "$1,000,000"}):
        k = _single("excess", **known)
        assert sqs.umbrella_retention_state(k, flags) in (sqs.UMB_RETENTION_STATED,
                                                          sqs.UMB_RETENTION_ESTABLISHED)
        assert sqs._umbrella_retention_checks(k, flags) == [True]
        kres = sqs.calculate_sqs(k, flags, {}, {}, ["ACORD_131"], [], [], 0, form_id="ACORD_131")
        assert not _review_recs(kres)


def test_a_primary_umbrella_is_unchanged():
    flags = {"has_umbrella": True}
    for over, met in (({}, False), ({"umbrella_sir": "$10,000"}, True),
                      ({"umbrella_attachment_point": "$1,000,000"}, True),
                      ({"gl_each_occurrence": "$1,000,000"}, False)):
        f = _single("umbrella", **over)
        assert sqs._umbrella_retention_checks(f, flags) == [met], over
    # with no layer records at all (a legacy package): the plain test, unchanged
    assert sqs._umbrella_retention_checks({}, {}) == [False]
    assert sqs._umbrella_retention_checks({"umbrella_attachment_point": "$1M"}, {}) == [True]
    assert not sqs.umbrella_sir_not_needed(_single("umbrella"), flags)
    assert not sqs.umbrella_sir_not_needed(_single("umbrella", gl_each_occurrence="$1,000,000"), flags)
    assert sqs.umbrella_sir_not_needed(_single("umbrella", umbrella_attachment_point="$1,000,000"), flags)


def test_the_sir_is_not_asked_once_the_attachment_point_is_known():
    q = {"_canonical_key": "umbrella_sir", "field_name": "umbrella_sir",
         "audience": "producer", "priority": "important"}
    known = qe.overlay_for(dict(q), _single("umbrella", umbrella_attachment_point="$1,000,000"))
    assert known.get("suppressed") is True
    assert known.get("suppressed_reason") == qe.REASON_ATTACHMENT_KNOWN
    unknown = qe.overlay_for(dict(q), _single("umbrella"))
    assert unknown.get("suppressed_reason") != qe.REASON_ATTACHMENT_KNOWN
    # the attachment point question itself is never retired by this rule
    att = dict(q, _canonical_key="umbrella_attachment_point", field_name="umbrella_attachment_point")
    assert qe.overlay_for(att, _single("umbrella", umbrella_sir="$0")).get(
        "suppressed_reason") != qe.REASON_ATTACHMENT_KNOWN


# =============================================================================
# #5 - a redacted premium: the 125 total is the visible premiums' sum
# =============================================================================
_TOTAL = "Policy_Payment_EstimatedTotalAmount_A"


def _redacted(n):
    """The Choice Electric rows with `n` OTHER-row policies' premiums redacted
    (0, 1, 2): the Federal EPL policy (the stored runs' own), then a second
    redacted dec (aviation liability, its own carrier and term). (A standard
    line's redacted premium - the Cyber box - already left the sum without
    blanking it.)"""
    lines = copy.deepcopy(_CE_LINES)
    recs = copy.deepcopy(_CE_RECORDS)
    if n == 0:
        for e in lines:
            if e["line"].startswith("Employment Practices"):
                e["premium"] = "$1,200.00"
        for r in recs:
            if r["line"] == "epli":
                r["premium"], r["granted"] = 1200.0, True
    if n >= 2:
        recs.append(_rec("aviation_liability", "XYZ SPECIALTY INSURANCE COMPANY",
                         printed="Aviation Liability"))
        lines.append({"line": "Aviation Liability", "carrier": "XYZ SPECIALTY INSURANCE COMPANY",
                      "premium": None, "policy_number": None,
                      "effective_date": "01/01/2025", "expiration_date": "01/01/2026"})
    return {"coverage_lines": lines, "_line_records": recs, "_form_id": "ACORD_125"}


@pytest.mark.parametrize("n", [0, 1, 2])
def test_the_total_is_the_visible_premiums_over_redacted_ones(n):
    f = _redacted(n)
    rows = pdf._other_lob_rows(f) or []
    assert sum(1 for r in rows if r.get("_unpriced")) == n
    printed = pdf._printed_lob_premiums(f)
    assert printed
    got = pdf._resolve_estimated_total(_TOTAL, f)
    assert got == f"${sum(printed):,}"
    # a stated one-policy total beside several carriers' rows is replaced by
    # that sum too - never blank, never the one policy's figure
    stated = pdf._resolve_estimated_total(_TOTAL, {**f, "total_policy_premium": "$10,692"})
    assert stated == f"${sum(printed):,}"


def _form125(rows_shown, total, ticked_blank=0):
    """A stamped ACORD 125 page one: OTHER rows (name, premium) and the total."""
    schema = na._schema_from_disk("ACORD_125")
    others = sorted(pdf._other_lob_premium_boxes(schema).items(), key=lambda kv: kv[1])
    mapped = {}
    for (prem, row), (name, amt) in zip(others, rows_shown):
        mapped[f"Policy_LineOfBusiness_OtherLineOfBusinessDescription_{row}"] = name
        mapped[f"Policy_LineOfBusiness_OtherIndicator_{row}"] = "Yes"
        if amt:
            mapped[prem] = amt
    pairs = list(pdf.lob_premium_box_pairs(schema).items())
    for tick, _prem in pairs[:ticked_blank]:
        mapped[tick] = "Yes"
    if total is not None:
        mapped[_TOTAL] = total
    return schema, mapped


@pytest.mark.parametrize("n", [0, 1, 2])
def test_the_needs_attention_note_says_the_total_is_partial(n):
    shown = [("Cyber", "$4,162.00"), ("Excess Liability", "$10,692.00"),
             ("Employment Practices Liability", None), ("Pollution Liability", None)][:2 + n]
    schema, mapped = _form125(shown, "$14,854")
    out = na.partial_total_boxes("ACORD_125", schema, mapped)
    if n == 0:
        assert out == []
        return
    assert len(out) == 1
    box, label, why = out[0]
    assert box == _TOTAL and "partial" in label.lower()
    assert f"leaves out {n} listed" in why and ("policy " if n == 1 else "policies ") in why
    # through the form's own needs-attention list: one Missing producer to-do
    rows = na.needs_attention({"mapped": mapped, "schema": schema, "confidence": {}}, {}, "ACORD_125")
    hits = [r for r in rows if r["field"] == _TOTAL]
    assert len(hits) == 1 and hits[0]["label"] == label and hits[0]["producer_todo"]
    assert hits[0]["score_effect"] == 0


def test_no_note_on_the_documents_own_total_a_blank_box_or_another_form():
    shown = [("Cyber", "$4,162.00"), ("Excess Liability", "$10,692.00"),
             ("Employment Practices Liability", None)]
    schema, mapped = _form125(shown, "$20,000")        # a stated figure, not the shown sum
    assert na.partial_total_boxes("ACORD_125", schema, mapped) == []
    schema, mapped = _form125(shown, None)
    assert na.partial_total_boxes("ACORD_125", schema, mapped) == []
    assert na.partial_total_boxes("ACORD_126", schema, mapped) == []
    # a ticked standard line printing no premium is left out the same way
    schema, mapped = _form125(shown[:2], "$14,854", ticked_blank=1)
    out = na.partial_total_boxes("ACORD_125", schema, mapped)
    assert len(out) == 1 and "leaves out 1 listed policy " in out[0][2]


# =============================================================================
# Review of Z35 (23 Oct 2026)
# =============================================================================
def _tower_docs(sir_doc_attachment=False):
    """The Choice Electric tower with the umbrella's SIR taken off and an
    attachment point printed by the EXCESS dec (or, `sir_doc_attachment`, by
    the umbrella's own dec)."""
    docs = copy.deepcopy(json.load(open(_FIXTURE))["docs"])
    for d in docs:
        f = d.get("facts") or {}
        if d["filename"].startswith("25-26 Umbrella"):
            f.pop("umbrella_sir", None)
            if sir_doc_attachment:
                f["umbrella_attachment_point"] = {"value": "$1,000,000", "source": "ai",
                                                  "confidence": "ai_high"}
        if d["filename"].startswith("25-26 Excess") and not sir_doc_attachment:
            f["umbrella_attachment_point"] = {"value": "$5,000,000", "source": "ai",
                                              "confidence": "ai_high"}
    return docs


def test_an_upper_layers_attachment_point_never_retires_the_umbrellas_sir_question():
    docs = _tower_docs()
    mf, flags = es.merge_facts(docs, es.select_primary_truth(docs))
    assert sqs._fv(mf, "umbrella_attachment_point") == "$5,000,000"   # the package reads the excess's
    plain = fi.facts_for_form({**mf, **flags}, "ACORD_131")
    assert sqs.umbrella_retention_state(plain, flags) == sqs.UMB_RETENTION_MISSING
    assert not sqs.umbrella_sir_not_needed(mf, flags)
    q = {"_canonical_key": "umbrella_sir", "field_name": "umbrella_sir",
         "audience": "producer", "priority": "important"}
    assert qe.overlay_for(dict(q), mf).get("suppressed_reason") != qe.REASON_ATTACHMENT_KNOWN
    # the umbrella's OWN attachment point does retire it
    docs = _tower_docs(sir_doc_attachment=True)
    mf2, flags2 = es.merge_facts(docs, es.select_primary_truth(docs))
    assert sqs.umbrella_sir_not_needed(mf2, flags2)
    assert qe.overlay_for(dict(q), mf2).get("suppressed_reason") == qe.REASON_ATTACHMENT_KNOWN


def test_the_underlying_line_boxes_are_one_shared_answer_for_both_copies(monkeypatch, merged):
    mf, flags, docs = merged
    session = {"facts": mf, "flags": flags, "docs": docs,
               "all_forms": fs.filter_available_forms(fs.load_all_forms()),
               "selected_form_ids": ["ACORD_125", "ACORD_131", EXCESS]}
    calls = []

    def fake_combined_gap_fill(forms_to_unmatched, facts, raw_text, model=None,
                               forms_to_mapped=None, line_scopes=None):
        marker = (facts or {}).get(ul.MARKER_KEY) or {}
        calls.append({"forms": {f: set(v) for f, v in forms_to_unmatched.items()},
                      "layer": marker.get("key")})
        tag = marker.get("carrier") or "PACKAGE"
        return {fid: {"filled_values": {f: f"{tag}|{f}" for f in fields},
                      "raw_text_fields": set(), "question_grounding": {}, "model_used": "stub"}
                for fid, fields in forms_to_unmatched.items()}

    monkeypatch.setattr(pdf, "combined_gap_fill", fake_combined_gap_fill)
    per_form = fs.shared_gap_fill(session, ["ACORD_125", "ACORD_131", EXCESS])
    own_exc = [c for c in calls if c["layer"] == "excess"]
    shared = [c for c in calls if c["layer"] is None]
    asked_own = {f for c in own_exc for f in c["forms"].get(EXCESS, ())}
    assert not any(ul.underlying_line_family(f) for f in asked_own), sorted(asked_own)
    shared_exc = {f for f in shared[0]["forms"].get(EXCESS, ()) if ul.underlying_line_family(f)}
    shared_base = {f for f in shared[0]["forms"].get("ACORD_131", ()) if ul.underlying_line_family(f)}
    assert shared_exc and shared_exc <= shared_base          # the 5 GL boxes, asked once
    for f in shared_exc:
        assert per_form[EXCESS]["filled_values"][f] == per_form["ACORD_131"]["filled_values"][f]
        assert fi.is_private_field(EXCESS, f) is False
    # the excess's own policy boxes stay its own
    assert fi.is_private_field(EXCESS, "UnderlyingPolicy_OtherPolicy_InsurerFullName_A")
    assert fi.is_private_field(EXCESS, "PriorCoverage_PolicyNumberIdentifier_A")
