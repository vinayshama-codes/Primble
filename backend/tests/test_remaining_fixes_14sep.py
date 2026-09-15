"""Orbin client review, 11 Sep 2026 - the fixes left after the safe half.

1. Umbrella $3,000,000 -> $1,000,000 is a change over time, not a conflict.
   The certificate states it in words with a date; the rule is
   `fact_comparison.dated_change`, read by BOTH the merge (what stamps) and the
   Data Consistency card, so they cannot disagree.
2. The coverage trigger: `gl_form_type` defined (prompt v21), `umbrella_form_type`
   added, both normalised per document at merge, and the basis ticks stamped
   through the same tick door Field QA compares with.
3. A carrier's own form reference is not a policy number when no verified
   contract names it - and a real second carrier's policy is never hidden.
4. One door for "does this stamped box agree with its source?" - Field QA and
   the post-generation stamp check both ask `pdf_service.box_expectation`.

Every literal is the client's own data (sessions e7084347 / 5037f1a6).
"""
import copy
import inspect
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("OPENAI_API_KEY", "sk-offline")

import pytest                                                     # noqa: E402

from services import extraction_service as es                     # noqa: E402
from services import fact_comparison as fc                        # noqa: E402
from services import field_qa                                     # noqa: E402
from services import narrative_facts as nf                        # noqa: E402
from services import pdf_service as ps                            # noqa: E402
from services import underwriting_consistency as uc               # noqa: E402

# The certificate's remark, verbatim (docs.json of e7084347).
COI_REMARK = ("Note: Reduced Umbrella Limit from $3,000,000 to $1,000,000 "
              "Limit Effective 7/25/25.")
DEC = "2526 Package Policy (Complete Copy).pdf"
COI = "CRS COI FIO - Orbin CERT ONLY.pdf"
NARR = "ORBIN CONTRACTING LLC submission narrative-20260530144518.pdf"

CM = "GeneralLiability_ClaimsMadeIndicator_A"
OC = "GeneralLiability_OccurrenceIndicator_A"


def _orbin_docs(remark=COI_REMARK, dec_type="dec_page"):
    coi_facts = {
        "umbrella_limit": {"value": "$1,000,000", "source": "ai", "confidence": "ai_high"},
        "umbrella_effective_date": {"value": "7/15/2025"},
        "umbrella_expiration_date": {"value": "7/15/2026"},
        "gl_form_type": {"value": "OCCUR", "source": "ai"},
    }
    if remark:
        coi_facts["additional_remarks_text"] = {"value": remark, "source": "ai"}
    return [
        {"doc_id": "d0c881c24b654957b2a19acf3e78834c", "filename": DEC,
         "doc_type": dec_type, "text": "",
         "facts": {
             "umbrella_limit": {"value": "$ 3,000,000", "source": "ai",
                                "confidence": "ai_high"},
             "umbrella_effective_date": {"value": "07/15/2025"},
             "umbrella_expiration_date": {"value": "07/15/2026"},
             "effective_date": {"value": "07/15/25"},
             "expiration_date": {"value": "07/15/26"},
             # e7084347's dec page, verbatim: the UMBRELLA's form title.
             "gl_form_type": {"value": "COMMERCIAL LIABILITY UMBRELLA COVERAGE FORM",
                              "source": "ai"},
         }},
        {"doc_id": "6e4cfad463514d31a16b35cef5ad0b55", "filename": COI,
         "doc_type": "certificate", "text": "", "facts": coi_facts},
        {"doc_id": "143081978f134edc89705c9bd31a8f72", "filename": NARR,
         "doc_type": "narrative", "text": "",
         "facts": {"umbrella_limit": {"value": "$1,000,000", "source": "ai",
                                      "confidence": "ai_high"}}},
    ]


def _merge(docs):
    docs = copy.deepcopy(docs)
    mf, _flags = es.merge_facts(docs, es.select_primary_truth(docs))
    return mf, docs


def _row(res, key):
    return next((f for f in res["fields"] if f["fact_key"] == key), None)


# =============================================================================
# 1a. The certificate's own sentence is read
# =============================================================================

class TestTheChangeSentence:
    def test_the_certificates_literal_remark_is_read(self):
        """Before: zero statements - the subject follows the verb - so the
        umbrella card never carried an explanation."""
        st = next(s for s in nf.mine_statements(COI_REMARK)
                  if s["subject"] == "umbrella_limit")
        assert st["kind"] == "amendment"
        assert (st["from"], st["to"], st["as_of"]) == ("$3,000,000", "$1,000,000", "7/25/25")

    def test_a_subject_before_the_verb_still_reads(self):
        sts = nf.mine_statements("The Umbrella limit was reduced from $3,000,000 "
                                 "to $1,000,000 effective 7/25/25.")
        assert any(s["subject"] == "umbrella_limit" for s in sts)

    def test_no_subject_is_still_no_statement(self):
        assert nf.mine_statements(
            "Reduced from $3,000,000 to $1,000,000 effective 7/25/25.") == []

    def test_a_statement_knows_which_document_prints_it(self):
        st = next(s for s in nf.statements_for_facts({}, None, _orbin_docs())
                  if s["subject"] == "umbrella_limit")
        assert st["source_doc_index"] == 1

    def test_a_conflict_the_rule_cannot_settle_now_carries_the_explanation(self):
        note = nf.explain_conflict("umbrella_limit", ["$ 3,000,000", "$1,000,000"],
                                   nf.mine_statements(COI_REMARK))
        assert note and "7/25/25" in note and "Confirm which applies" in note


# =============================================================================
# 1b. The rule and every gate
# =============================================================================

class TestDatedChangeRule:
    TERM = ("2025-07-15", "2026-07-15")
    ST = [{"kind": "amendment", "subject": "umbrella_limit", "from": "$3,000,000",
           "to": "$1,000,000", "as_of": "7/25/25", "source_doc_index": 1,
           "quote": COI_REMARK}]
    OK = [("$ 3,000,000", "2025-07-15", 0), ("$1,000,000", None, 1),
          ("$1,000,000", None, 2)]

    def test_the_orbin_case_is_a_change(self):
        v = fc.dated_change("umbrella_limit", self.OK, self.ST, self.TERM)
        assert v["current"] == "$1,000,000" and v["prior"] == "$ 3,000,000"
        assert v["as_of"] == "7/25/25" and v["source_doc_index"] == 1

    def test_no_statement_no_change(self):
        assert fc.dated_change("umbrella_limit", self.OK, [], self.TERM) is None

    def test_no_term_no_change(self):
        assert fc.dated_change("umbrella_limit", self.OK, self.ST, None) is None

    def test_a_date_outside_the_term_is_not_this_policys_change(self):
        st = [dict(self.ST[0], as_of="7/25/24")]
        assert fc.dated_change("umbrella_limit", self.OK, st, self.TERM) is None

    def test_an_undated_old_value_is_not_proven_older(self):
        p = [("$ 3,000,000", None, 0)] + self.OK[1:]
        assert fc.dated_change("umbrella_limit", p, self.ST, self.TERM) is None

    def test_an_old_value_printed_after_the_change_is_a_conflict(self):
        p = [("$ 3,000,000", "2025-08-01", 0)] + self.OK[1:]
        assert fc.dated_change("umbrella_limit", p, self.ST, self.TERM) is None

    def test_the_stating_document_must_print_the_new_value(self):
        p = [self.OK[0], self.OK[2]]
        assert fc.dated_change("umbrella_limit", p, self.ST, self.TERM) is None

    def test_the_stating_document_must_not_print_the_old_value(self):
        p = self.OK + [("$3,000,000", None, 1)]
        assert fc.dated_change("umbrella_limit", p, self.ST, self.TERM) is None

    def test_a_third_amount_is_a_conflict(self):
        p = self.OK + [("$2,000,000", None, 2)]
        assert fc.dated_change("umbrella_limit", p, self.ST, self.TERM) is None

    def test_another_facts_statement_does_not_apply(self):
        st = [dict(self.ST[0], subject="gl_aggregate")]
        assert fc.dated_change("umbrella_limit", self.OK, st, self.TERM) is None

    def test_an_increase_works_the_same_way(self):
        st = [dict(self.ST[0], **{"from": "$1,000,000", "to": "$2,000,000"})]
        p = [("$1,000,000", "2025-07-15", 0), ("$2,000,000", None, 1)]
        v = fc.dated_change("umbrella_limit", p, st, self.TERM)
        assert v["current"] == "$2,000,000" and v["prior"] == "$1,000,000"

    def test_a_certificate_is_never_the_proven_older_side(self):
        assert fc.document_as_of({"doc_type": "certificate", "facts": {
            "umbrella_effective_date": "7/15/2025",
            "umbrella_expiration_date": "7/15/2026"}}, "umbrella_limit") is None
        assert fc.document_as_of(_orbin_docs()[0], "umbrella_limit") == "2025-07-15"


# =============================================================================
# 1c. End to end: the merge, the card, the form
# =============================================================================

class TestUmbrellaThroughThePipeline:
    def test_the_merged_limit_is_the_current_one_with_its_history(self):
        mf, _ = _merge(_orbin_docs())
        env = mf["umbrella_limit"]
        assert env["value"] == "$1,000,000"
        assert env["prior_value"] == "$ 3,000,000"
        assert env["as_of"] == "7/25/25"
        assert env["source"] == "document_amendment"
        assert "umbrella_limit" not in (mf.get("_uw_conflicted_keys") or [])

    def test_the_card_shows_a_change_not_a_conflict(self):
        mf, docs = _merge(_orbin_docs())
        res = uc.assess_underwriting_consistency(docs, mf, {})
        row = _row(res, "umbrella_limit")
        assert row["status"] == "changed" and row["review_required"] is False
        assert row["change"]["current"] == "$1,000,000"
        assert row["change"]["prior"] == "$ 3,000,000"
        assert row["change"]["document"] == COI
        assert row["change"]["prior_documents"] == [DEC]
        assert "7/25/25" in row["narrative_note"]
        assert "umbrella_limit" not in uc.unresolved_conflict_keys(res, {})

    def test_131_prints_the_current_limit(self):
        mf, _ = _merge(_orbin_docs())
        sch = ps._all_form_schemas()["ACORD_131"]
        ps._set_schema_context(sch)
        try:
            for f in ("ExcessUmbrella_Umbrella_EachOccurrenceAmount_A",
                      "ExcessUmbrella_Umbrella_AggregateAmount_A"):
                assert ps._deterministic_map(f, {**mf, "_form_id": "ACORD_131"}) \
                    == "$1,000,000", f
        finally:
            ps._set_schema_context(None)

    def test_without_the_sentence_it_is_still_the_producers_question(self):
        mf, docs = _merge(_orbin_docs(remark=None))
        assert (mf["umbrella_limit"] or {}).get("source") != "document_amendment"
        row = _row(uc.assess_underwriting_consistency(docs, mf, {}), "umbrella_limit")
        assert row["status"] == "conflict"

    def test_an_undated_old_value_stays_a_conflict_with_the_explanation(self):
        """The $3,000,000 now comes from a certificate - which carries no
        inception date, so nothing proves it is the OLDER printing."""
        mf, docs = _merge(_orbin_docs(dec_type="certificate"))
        row = _row(uc.assess_underwriting_consistency(docs, mf, {}), "umbrella_limit")
        assert row["status"] == "conflict"
        assert row["narrative_note"] and "7/25/25" in row["narrative_note"]


# =============================================================================
# 2. The coverage trigger
# =============================================================================

class TestCoverageBasis:
    @pytest.mark.parametrize("raw,basis", [
        ("OCCUR", "Occurrence"),                         # the certificate's caption
        ("CLAIMS-MADE", "Claims-made"),
        ("Occurrence", "Occurrence"),
        ("CG 00 01 04 13", "Occurrence"),                # 5037f1a6's dec, verbatim
        ("CG 00 02 04 13", "Claims-made"),
        ("Commercial General Liability Coverage Form (Occurrence)", "Occurrence"),
        ("COMMERCIAL LIABILITY UMBRELLA COVERAGE FORM", None),   # e7084347, verbatim
        ("Commercial General Liability", None),
        ("Business Auto Coverage Form", None),
        ("Each Occurrence $1,000,000", None),            # a limit, not a trigger
        ("Occurrence and Claims-Made", None),
        ("", None),
    ])
    def test_general_liability(self, raw, basis):
        assert es.coverage_basis("gl_form_type", raw) == basis

    def test_the_umbrella_never_reads_the_iso_gl_form(self):
        assert es.coverage_basis("umbrella_form_type", "CG 00 01 04 13") is None
        assert es.coverage_basis("umbrella_form_type", "OCCUR") == "Occurrence"

    def test_each_document_is_normalised_at_merge(self):
        mf, docs = _merge(_orbin_docs())
        assert es._fv(docs[0]["facts"], "gl_form_type") is None
        assert es._fv(docs[1]["facts"], "gl_form_type") == "Occurrence"
        assert es._fv(mf, "gl_form_type") == "Occurrence"

    def test_the_card_no_longer_offers_a_form_name_as_a_basis(self):
        mf, docs = _merge(_orbin_docs())
        row = _row(uc.assess_underwriting_consistency(docs, mf, {}), "gl_form_type")
        assert row is None or row["status"] != "conflict"

    def test_the_prompt_defines_both_and_moved_to_v21(self):
        assert es.PROMPT_VERSION == es.SCHEMA_VERSION == "v21"
        assert '"gl_form_type": "Occurrence"|"Claims-Made"|null' in es._EXTRACT_SCHEMA
        assert '"umbrella_form_type": "Occurrence"|"Claims-Made"|null' in es._EXTRACT_SCHEMA


class TestBasisTicks:
    @pytest.mark.parametrize("fid", ["ACORD_126", "ACORD_131", "ACORD_25"])
    def test_an_occurrence_policy_ticks_occurrence(self, fid):
        ps._set_schema_context(ps._all_form_schemas()[fid])
        try:
            facts = {"gl_form_type": "Occurrence", "_form_id": fid}
            assert ps._deterministic_map(OC, facts) == "Yes"
            assert ps._deterministic_map(CM, facts) == "No"
        finally:
            ps._set_schema_context(None)

    def test_a_form_title_ticks_nothing(self):
        ps._set_schema_context(ps._all_form_schemas()["ACORD_126"])
        try:
            facts = {"gl_form_type": "COMMERCIAL LIABILITY UMBRELLA COVERAGE FORM",
                     "_form_id": "ACORD_126"}
            assert ps._deterministic_map(OC, facts) is None
            assert ps._deterministic_map(CM, facts) is None
        finally:
            ps._set_schema_context(None)

    def test_the_umbrella_boxes_read_the_umbrellas_own_basis(self):
        gl_only = {"gl_form_type": "Claims-made"}
        assert ps._derive_indicator("ExcessUmbrella_OccurrenceIndicator_A", gl_only) is None
        assert ps._derive_indicator("ExcessUmbrella_ClaimsMadeIndicator_A", gl_only) is None
        umb = {"umbrella_form_type": "Occurrence"}
        assert ps._derive_indicator("ExcessUmbrella_OccurrenceIndicator_A", umb) == "Yes"
        assert ps._derive_indicator("ExcessUmbrella_ClaimsMadeIndicator_A", umb) == "No"

    def test_the_stamper_and_field_qa_agree(self):
        fid = "ACORD_126"
        sch = ps._all_form_schemas()[fid]
        facts = {"gl_form_type": "Occurrence"}
        ps._set_schema_context(sch)
        try:
            mapped = {f: ps._deterministic_map(f, {**facts, "_form_id": fid})
                      for f in (OC, CM)}
        finally:
            ps._set_schema_context(None)
        qa = field_qa.run_field_qa(
            {fid: {"mapped": mapped, "schema": {k: sch[k] for k in mapped},
                   "confidence": {}}}, merged_facts=facts)
        assert not [r for r in qa["results"] if r["reason_code"] == "value_mismatch"]


# =============================================================================
# 3. A form reference is not a policy number
# =============================================================================

def _g(display):
    return {"normalized": display.lower(), "display": display,
            "sources": [{"doc_id": "1", "filename": "a.pdf", "raw": display}]}


_INDEX = {"dec_page_entries": [
    {"label": "Policy Number", "value": "BBC7263 - 26", "policy_number": "BBC7263 - 26",
     "line_of_business": "Commercial General Liability"},
    {"label": "Policy Number", "value": "6E7-40-02---26",
     "policy_number": "6E7-40-02---26", "line_of_business": "Commercial Auto"},
]}


class TestFormReferences:
    @pytest.mark.parametrize("form", [
        "CU7001A 11-15", "CU7001A(11/15)", "IL 71 31A 04 01", "CG 70 01A 10 12",
        "IL8383.2A 12-20",                     # all printed in the Orbin package
    ])
    def test_a_carrier_form_reference_is_set_aside(self, form):
        kept = uc._drop_unknown_form_references(
            "policy_number", [_g("BBC7263 - 26"), _g(form)], _INDEX, [])
        assert [g["display"] for g in kept] == ["BBC7263 - 26"]

    def test_a_real_second_carriers_policy_stays(self):
        """Defect D-1: a certificate's GL policy from another carrier is a real
        second policy on the line, and must stay the producer's question."""
        kept = uc._drop_unknown_form_references(
            "policy_number", [_g("BBC7263 - 26"), _g("GL-4471102-26")], _INDEX, [])
        assert len(kept) == 2

    def test_no_index_no_opinion(self):
        vals = [_g("BBC7263 - 26"), _g("CU7001A 11-15")]
        assert len(uc._drop_unknown_form_references("policy_number", vals, {}, [])) == 2

    def test_nothing_proven_nothing_dropped(self):
        vals = [_g("CU7001A 11-15"), _g("IL 71 31A 04 01")]
        assert len(uc._drop_unknown_form_references("policy_number", vals, _INDEX, [])) == 2

    def test_other_facts_are_untouched(self):
        vals = [_g("BBC7263 - 26"), _g("CU7001A 11-15")]
        assert len(uc._drop_unknown_form_references("carrier_name", vals, _INDEX, [])) == 2

    @pytest.mark.parametrize("real", [
        "6E7-40-02---26", "BBC7263 - 26", "6J74002", "0482854", "GL-4471102-26",
        "IM-5540-26", "CPP 4Q 887214 26", "6J7-40-02---26",
    ])
    def test_real_policy_numbers_are_not_form_shaped(self, real):
        assert not uc._FORM_REFERENCE_RE.match(real)


# =============================================================================
# 4. One door for "does this box agree with its source?"
# =============================================================================

class TestOneBoxDoor:
    def test_both_checks_ask_the_same_door(self):
        qa_src = inspect.getsource(field_qa.run_field_qa)
        stamp_src = inspect.getsource(uc.verify_stamped_consistency)
        assert "box_expectation(" in qa_src and "box_expectation(" in stamp_src
        # ...and neither keeps a private copy of the owner lookup.
        assert "authoritative_expected_value(" not in qa_src
        assert "authoritative_expected_value(" not in stamp_src

    def test_an_owned_blank_has_nothing_to_compare(self, monkeypatch):
        monkeypatch.setattr(ps, "authoritative_expected_value", lambda *a, **k: None)
        assert ps.box_expectation(
            "ACORD_131", "ExcessUmbrella_Umbrella_EachOccurrenceAmount_A",
            "umbrella_limit", "$1,000,000", {}, {}) is None

    def test_a_checkbox_is_a_tick_and_a_text_box_a_value(self):
        sch = ps._all_form_schemas()["ACORD_126"]
        assert ps.box_expectation("ACORD_126", OC, "gl_form_type", "OCCUR", {}, sch) \
            == ("tick", "Yes")
        exp = ps.box_expectation("ACORD_126", "GeneralLiability_GeneralAggregate_LimitAmount_A",
                                 "gl_aggregate", "$2,000,000", {}, sch)
        assert exp == ("value", "$2,000,000")

    def test_the_stamp_check_asks_the_owner(self, monkeypatch):
        f = "ExcessUmbrella_Umbrella_EachOccurrenceAmount_A"
        forms = {"ACORD_131": {"mapped": {f: "$5,000,000"},
                               "schema": {f: {"ft": "/Tx"}}}}
        facts = {"umbrella_limit": "$1,000,000"}
        monkeypatch.setattr(ps, "authoritative_expected_value",
                            lambda *a, **k: ps._AUTH_UNOWNED)
        assert uc.verify_stamped_consistency(forms, facts)["mismatches"]
        # The owner says this box holds its own line's $5,000,000.
        monkeypatch.setattr(ps, "authoritative_expected_value",
                            lambda fid, fld, *a, **k: "$5,000,000" if fld == f
                            else ps._AUTH_UNOWNED)
        assert not uc.verify_stamped_consistency(forms, facts)["mismatches"]


# =============================================================================
# 5. Break-it pass (14 Sep): hostile inputs, through the merge and the card.
#    Every case here broke the first cut of fixes 1-3.
# =============================================================================

def _status_and_source(remark):
    mf, docs = _merge(_orbin_docs(remark))
    row = _row(uc.assess_underwriting_consistency(docs, mf, {}), "umbrella_limit")
    held = mf.get("umbrella_limit")
    return (row or {}).get("status"), (held.get("source") if isinstance(held, dict) else None)


class TestBreakValues:
    @pytest.mark.parametrize("remark", [
        "Note: The Umbrella Limit was not reduced from $3,000,000 to $1,000,000 effective 7/25/25.",
        "The Umbrella Limit was never reduced from $3,000,000 to $1,000,000 effective 7/25/25.",
        "The Umbrella Limit wasn't reduced from $3,000,000 to $1,000,000 effective 7/25/25.",
        "Insured requests the Umbrella Limit be reduced from $3,000,000 to $1,000,000 effective 7/25/25.",
        "If approved, the Umbrella Limit will be reduced from $3,000,000 to $1,000,000 effective 7/25/25.",
        "The Umbrella Limit is proposed to be reduced from $3,000,000 to $1,000,000 effective 7/25/25.",
        "Can the Umbrella Limit be reduced from $3,000,000 to $1,000,000 effective 7/25/25?",
        # the same remark then reverses it, or states a second, different change
        COI_REMARK + " Umbrella Limit increased from $1,000,000 to $3,000,000 effective 9/1/25.",
        COI_REMARK + " Umbrella Limit reduced from $3,000,000 to $2,000,000 effective 8/1/25.",
    ])
    def test_a_sentence_that_does_not_assert_one_change_settles_nothing(self, remark):
        status, source = _status_and_source(remark)
        assert status != "changed" and source != "document_amendment"

    @pytest.mark.parametrize("remark", [
        COI_REMARK,
        "Effective 7/25/25, the Umbrella Limit was reduced from $3,000,000 to $1,000,000.",
        "The Umbrella Limit has been reduced from $3,000,000 to $1,000,000 effective July 25, 2025.",
        "Per the insured's request, Umbrella Limit reduced from $3M to $1M effective 7/25/25.",
        # one change printed twice is still one change
        COI_REMARK + " Umbrella Limit reduced from $3,000,000.00 to $1,000,000.00.",
    ])
    def test_an_asserted_change_still_reads(self, remark):
        assert _status_and_source(remark) == ("changed", "document_amendment")

    def test_a_negated_change_is_mined_but_never_explained_as_one(self):
        st = next(s for s in nf.mine_statements(
            "The Umbrella Limit was not reduced from $3,000,000 to $1,000,000 "
            "effective 7/25/25.") if s["subject"] == "umbrella_limit")
        assert st["asserted"] is False and st["as_of"] == "7/25/25"
        assert nf.explain_conflict("umbrella_limit", ["$3,000,000", "$1,000,000"], [st]) is None

    def test_the_clients_literal_is_asserted(self):
        st = next(s for s in nf.mine_statements(COI_REMARK) if s["subject"] == "umbrella_limit")
        assert st["asserted"] is True

    def test_shorthand_amounts_keep_their_multiplier(self):
        st = next(s for s in nf.mine_statements(
            "Umbrella Limit reduced from $3M to $1M effective 7/25/25.")
            if s["subject"] == "umbrella_limit")
        assert (st["from"], st["to"]) == ("$3M", "$1M")

    @pytest.mark.parametrize("raw,basis", [
        ("CLAIMS-MADE OCCUR", None),            # both captions - the tick lost in OCR
        ("CLAIMS-MADE  X OCCUR", None),
        ("X OCCUR", "Occurrence"),
        ("Per Occurrence", None),               # a limit label
        ("Occurrence (CG 00 02)", None),        # the words and the form number disagree
        ("Claims-Made CG 00 01", None),
        ("Occurrence CG 00 01 04 13", "Occurrence"),
        ("Claims Made", "Claims-made"),
        ("CLAIMS MADE BASIS", "Claims-made"),
        ("CG0001", "Occurrence"),
        ("OCC", None),
        ("N/A", None),
    ])
    def test_coverage_basis(self, raw, basis):
        assert es.coverage_basis("gl_form_type", raw) == basis

    @pytest.mark.parametrize("field,val,tick", [
        ("ExcessUmbrella_OccurrenceIndicator_A", "Occurrence", "Yes"),
        ("ExcessUmbrella_ClaimsMadeIndicator_A", "Occurrence", "No"),
        ("ExcessUmbrella_ClaimsMadeIndicator_A", "Claims-made", "Yes"),
    ])
    def test_the_checker_reads_the_umbrella_ticks_as_the_stamper_does(self, field, val, tick):
        assert ps.expected_tick_for_box(field, "umbrella_form_type", val) == tick
        assert ps._derive_indicator(field, {"umbrella_form_type": val}) == tick

    @pytest.mark.parametrize("real", [
        "BOP 7654321 01 26", "CPP 1234567 12-25", "WC 0123456 06/25", "GL 998877 03 26",
        "ABC123456 01-26", "BA 12345678 07 25", "CA 7001234 11 24",
    ])
    def test_a_real_policy_number_with_a_date_shaped_tail_stays(self, real):
        assert not uc._FORM_REFERENCE_RE.match(real)
        kept = uc._drop_unknown_form_references(
            "policy_number", [_g("BBC7263 - 26"), _g(real)], _INDEX, [])
        assert len(kept) == 2

    @pytest.mark.parametrize("form", [
        "IM 7100 06 04", "IM 7201 10 02", "CG 00 01 04 13", "CA 00 01 10 13", "IL 00 17 11 98",
    ])
    def test_iso_and_aais_form_references_still_read_as_forms(self, form):
        assert uc._FORM_REFERENCE_RE.match(form)
