"""Comparisons that should never happen - Orbin client review, 11 Sep 2026.

*"There are also SQS comparisons that should never happen - for example,
comparing a $2M limit to a Per Location/Per Project yes/no field, or comparing
a Claims Made indicator to the words 'Commercial Liability Umbrella Coverage
Form.'"* ... *"Values should only be compared when they represent the same
field, same LOB/policy and applicable time period."*

Every value here is the client's own data. The rows the producer was shown
were read back from `sqs_recommendation_audit` for session e7084347, the
confirmation from `underwriting_confirmation_audit`; the gl_form_type pair is
the latest Orbin extraction (5037f1a6).

Four guards, one class - a value compared with something that is not the same
kind of thing:
  1. a CHECKBOX is compared as a tick, never with its fact's wording;
  2. the aggregate's BASIS ticks are not the aggregate AMOUNT;
  3. a document's own caption for an option ("OCCUR") is that option, so a
     form number is no longer its rival;
  4. a FORM number confirmed as a policy number is never read as an answer.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("OPENAI_API_KEY", "sk-offline")

import pytest                                                     # noqa: E402

from services import pdf_service as ps                            # noqa: E402
from services import underwriting_consistency as uc               # noqa: E402
from services.answer_options import option_named_by               # noqa: E402
from services.field_qa import run_field_qa                        # noqa: E402

_SCHEMAS = ps._all_form_schemas()

CM = "GeneralLiability_ClaimsMadeIndicator_A"
OC = "GeneralLiability_OccurrenceIndicator_A"


def _form(fid, mapped):
    sch = _SCHEMAS[fid]
    return {"schema": {k: sch[k] for k in mapped}, "mapped": dict(mapped),
            "confidence": {}}


def _mismatches(qa):
    return {(r["form_id"], r["field"]) for r in qa["results"]
            if r["reason_code"] == "value_mismatch"}


# =============================================================================
# 1. A checkbox holds a tick, not the fact's wording
# =============================================================================

class TestBasisTicks:
    @pytest.mark.parametrize("fid", ["ACORD_126", "ACORD_131", "ACORD_25"])
    @pytest.mark.parametrize("stated", [
        "COMMERCIAL LIABILITY UMBRELLA COVERAGE FORM",   # e7084347, verbatim
        "CG 00 01 04 13",                                # 5037f1a6, verbatim
        "Business Auto Coverage Form",                   # an earlier Orbin run
    ])
    def test_a_tick_is_never_compared_with_a_form_name(self, fid, stated):
        """The client's literal rows: 'GeneralLiability ClaimsMadeIndicator on
        ACORD 126 shows "No" but the source value is "COMMERCIAL LIABILITY
        UMBRELLA COVERAGE FORM"' - on 126 and on 131."""
        assert CM in _SCHEMAS[fid] and OC in _SCHEMAS[fid]
        qa = run_field_qa({fid: _form(fid, {CM: "No", OC: "Yes"})},
                          merged_facts={"gl_form_type": {"value": stated}})
        assert not _mismatches(qa)

    @pytest.mark.parametrize("stated", ["Occurrence", "OCCUR"])
    def test_the_right_ticks_agree_with_an_occurrence_policy(self, stated):
        """Measured before the fix: the comparator could not agree with ANY
        value, including the correct one."""
        qa = run_field_qa({"ACORD_126": _form("ACORD_126", {CM: "No", OC: "Yes"})},
                          merged_facts={"gl_form_type": stated})
        assert not _mismatches(qa)

    @pytest.mark.parametrize("stated", ["Occurrence", "OCCUR"])
    def test_a_wrong_tick_is_still_caught(self, stated):
        """The guard removes false alarms only - a real disagreement stays."""
        qa = run_field_qa({"ACORD_126": _form("ACORD_126", {CM: "Yes", OC: "No"})},
                          merged_facts={"gl_form_type": stated})
        assert _mismatches(qa) == {("ACORD_126", CM), ("ACORD_126", OC)}
        row = next(r for r in qa["results"] if r["field"] == CM)
        assert row["expected"] == "No"

    def test_a_claims_made_policy(self):
        facts = {"gl_form_type": "Claims-Made"}
        ok = run_field_qa({"ACORD_126": _form("ACORD_126", {CM: "Yes", OC: "No"})},
                          merged_facts=facts)
        assert not _mismatches(ok)
        bad = run_field_qa({"ACORD_126": _form("ACORD_126", {CM: "No"})},
                           merged_facts=facts)
        assert _mismatches(bad) == {("ACORD_126", CM)}

    def test_a_box_that_declares_no_option_asserts_nothing(self):
        """ACORD 137's CSL box is bound to `auto_liability_structure`, but no
        table says which answer the box stands for - so there is nothing to
        compare, and nothing is invented."""
        f = "Vehicle_CombinedSingleLimit_LimitIndicator_A"
        qa = run_field_qa({"ACORD_137_CO": _form("ACORD_137_CO", {f: "Yes"})},
                          merged_facts={"auto_liability_structure": "Combined Single Limit"})
        assert not _mismatches(qa)

    def test_expected_tick(self):
        assert ps.expected_tick_for_box(OC, "gl_form_type", "OCCUR") == "Yes"
        assert ps.expected_tick_for_box(CM, "gl_form_type", "OCCUR") == "No"
        assert ps.expected_tick_for_box(CM, "gl_form_type", "Claims-made") == "Yes"
        assert ps.expected_tick_for_box(
            CM, "gl_form_type", "COMMERCIAL LIABILITY UMBRELLA COVERAGE FORM") is None
        assert ps.expected_tick_for_box(CM, "gl_form_type", "CG 00 01 04 13") is None
        assert ps.expected_tick_for_box(CM, "gl_form_type", "") is None
        # A yes/no fact IS the tick.
        assert ps.expected_tick_for_box("Any_Indicator_A", "has_umbrella", "Yes") == "Yes"
        assert ps.expected_tick_for_box("Any_Indicator_A", "has_umbrella", True) == "Yes"
        assert ps.expected_tick_for_box(
            "Vehicle_CombinedSingleLimit_LimitIndicator_A",
            "auto_liability_structure", "CSL") is None


# =============================================================================
# 2. The aggregate's BASIS ticks are not the aggregate amount
# =============================================================================

_BASIS_TICKS = (
    "GeneralLiability_GeneralAggregate_LimitAppliesPerPolicyIndicator_A",
    "GeneralLiability_GeneralAggregate_LimitAppliesPerProjectIndicator_A",
    "GeneralLiability_GeneralAggregate_LimitAppliesPerLocationIndicator_A",
    "GeneralLiability_GeneralAggregate_LimitAppliesToOtherIndicator_A",
)


class TestAggregateBasisTicks:
    @pytest.mark.parametrize("fid", ["ACORD_126", "ACORD_25"])
    @pytest.mark.parametrize("field", _BASIS_TICKS)
    def test_no_rule_reads_the_amount_into_a_basis_tick(self, fid, field):
        assert field in _SCHEMAS[fid]
        assert ps._first_rule_fact(field) is None
        assert field not in ps.fact_to_form_fields("gl_aggregate").get(fid, ())

    def test_the_amount_box_still_reads_the_amount(self):
        assert ps._first_rule_fact(
            "GeneralLiability_GeneralAggregate_LimitAmount_A") == "gl_aggregate"

    def test_the_other_description_box_keeps_its_route(self):
        """Deliberately unchanged. Re-routing this /Tx box would ASK gap fill
        about a box that today ships blank (the D2 type guard refuses the
        amount), which is a stamping change, not a comparison fix."""
        assert ps._first_rule_fact(
            "GeneralLiability_GeneralAggregate_LimitAppliesToCode_A") == "gl_aggregate"

    @pytest.mark.parametrize("field", _BASIS_TICKS)
    def test_stamping_is_unchanged(self, field):
        """Before and after: the tick reaches gap fill (None). Before, the Y/N
        gate refused the $2,000,000; now the table itself says so."""
        ps._set_schema_context(_SCHEMAS["ACORD_126"])
        try:
            assert ps._deterministic_map(
                field, {"gl_aggregate": "$2,000,000", "_form_id": "ACORD_126"}) is None
        finally:
            ps._set_schema_context(None)

    def test_the_clients_literal_rows_do_not_come_back(self):
        """'GeneralLiability GeneralAggregate LimitAppliesPerLocationIndicator
        on ACORD 126 shows "No" but the source value is "$2,000,000"'."""
        mapped = {_BASIS_TICKS[1]: "No", _BASIS_TICKS[2]: "No"}
        qa = run_field_qa({"ACORD_126": _form("ACORD_126", mapped)},
                          merged_facts={"gl_aggregate": "$2,000,000"})
        assert not _mismatches(qa)


# =============================================================================
# 3. A document's own caption for an option is that option
# =============================================================================

def _group(display, *raws):
    return {"normalized": display.lower(), "display": display,
            "sources": [{"doc_id": "1", "filename": "a.pdf", "raw": r}
                        for r in (raws or (display,))]}


class TestOptionPrintings:
    def test_option_named_by(self):
        # ACORD 25 prints the GL basis as the checkbox caption "OCCUR".
        assert option_named_by("gl_form_type", "OCCUR") == "Occurrence"
        assert option_named_by("gl_form_type", "Occurrence") == "Occurrence"
        assert option_named_by("gl_form_type", "CLAIMS-MADE") == "Claims-made"
        assert option_named_by("gl_form_type", "Claims") == "Claims-made"
        assert option_named_by("gl_form_type", "CG 00 01 04 13") is None
        assert option_named_by("gl_form_type", "OCC") is None     # too short to name one
        assert option_named_by("gl_form_type", "Other") is None
        assert option_named_by("gl_form_type", "") is None
        assert option_named_by("gl_form_type", None) is None
        assert option_named_by("entity_type", "Limited") is None  # names three options
        assert option_named_by("entity_type", "Corp") == "Corporation"
        assert option_named_by("applicant_name", "Orbin") is None  # no closed list

    def test_a_form_number_is_not_a_rival_to_the_certificates_basis(self):
        """5037f1a6: the card asked the producer to choose between 'CG 00 01
        04 13' and 'OCCUR'. Before, BOTH were judged illegal (exact match
        only), so neither could be dropped."""
        kept = uc._drop_values_outside_declared_domain(
            "gl_form_type", [_group("CG 00 01 04 13"), _group("OCCUR")])
        assert [g["display"] for g in kept] == ["OCCUR"]

    def test_two_printings_of_one_option_are_one_answer(self):
        kept = uc._drop_values_outside_declared_domain(
            "gl_form_type", [_group("Occurrence"), _group("OCCUR")])
        assert len(kept) == 1
        assert len(kept[0]["sources"]) == 2
        assert kept[0]["display"] == "Occurrence"

    def test_two_different_options_still_conflict(self):
        kept = uc._drop_values_outside_declared_domain(
            "gl_form_type", [_group("OCCUR"), _group("CLAIMS-MADE")])
        assert len(kept) == 2

    def test_the_card_with_the_clients_values(self):
        docs = [
            {"doc_id": "d", "filename": "2526 Package Policy (Complete Copy).pdf",
             "doc_type": "dec_page",
             "facts": {"gl_form_type": {"value": "CG 00 01 04 13"}}},
            {"doc_id": "c", "filename": "CRS COI FIO - Orbin CERT ONLY.pdf",
             "doc_type": "certificate",
             "facts": {"gl_form_type": {"value": "OCCUR"}}},
        ]
        res = uc.assess_underwriting_consistency(docs, {}, {})
        row = next((f for f in res["fields"] if f["fact_key"] == "gl_form_type"), None)
        assert row is None or row["status"] != "conflict"


# =============================================================================
# 4. A form number confirmed as a policy number is never read as an answer
# =============================================================================

class TestFormNumberConfirmation:
    # e7084347's stored confirmations, verbatim.
    STORED = {"policy_number": "IM 7100 06 04",
              "producer_name": "COMMERCIAL RISK SOLUTIONS, INC.",
              "umbrella_limit": "$1,000,000"}

    def test_usable_confirmations(self):
        out = uc.usable_confirmations(self.STORED)
        assert "policy_number" not in out
        assert out["umbrella_limit"] == "$1,000,000"
        assert out["producer_name"] == "COMMERCIAL RISK SOLUTIONS, INC."
        assert uc.usable_confirmations({"policy_number@auto": "CG 00 01 04 13"}) == {}
        assert uc.usable_confirmations({"policy_number": "6E7-40-02---26"}) == \
            {"policy_number": "6E7-40-02---26"}
        assert uc.usable_confirmations(None) == {}

    def test_the_card_does_not_render_it_as_the_confirmed_answer(self):
        docs = [{"doc_id": "d", "filename": "policy.pdf", "doc_type": "dec_page",
                 "facts": {"policy_number": {"value": "6E7-40-02---26"}}}]
        res = uc.assess_underwriting_consistency(docs, {}, self.STORED)
        row = next(f for f in res["fields"] if f["fact_key"] == "policy_number")
        assert row["confirmed_value"] is None
        assert row["status"] != "confirmed"

    def test_it_does_not_hide_a_real_conflict(self):
        uw = {"fields": [{"fact_key": "policy_number", "review_required": True}]}
        assert "policy_number" in uc.unresolved_conflict_keys(
            uw, {"policy_number": "IM 7100 06 04"})
        assert "policy_number" not in uc.unresolved_conflict_keys(
            uw, {"policy_number": "6E7-40-02---26"})

    def test_field_qa_never_uses_it_as_the_source_value(self):
        """The client's literal row: 'OtherPolicy PolicyNumberIdentifier on
        ACORD 125 shows "BBC7263 - 26" but the source value is "IM 7100 06
        04"'."""
        f = "OtherPolicy_PolicyNumberIdentifier_A"
        qa = run_field_qa({"ACORD_125": _form("ACORD_125", {f: "BBC7263 - 26"})},
                          merged_facts={},
                          confirmations={"policy_number": "IM 7100 06 04"})
        assert not _mismatches(qa)
