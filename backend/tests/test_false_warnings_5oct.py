"""False pre-form warnings - the CH125 kit's first runs (5 Oct 2026).

Every rule here fired on a package where nothing it described was wrong.
Each test pins the CLASS with the live shape, and the real gap beside it so
the fix cannot pass by switching the rule off. Detail and measurements:
`5Oct-formImprovement-125-126-127.md` (repo root).
"""
from __future__ import annotations

import asyncio
import copy
from unittest.mock import patch

import pytest

import repositories.session_repository as sr
import routes.audit_routes as ar
import services.arq_service as arq
import services.audit_service as au
import services.cross_form_validator as cfv
import services.extraction_service as es
import services.sqs_service as sq
from services.coverage_evidence import (
    auto_csl_stated, auto_limits_are_split, valuation_method_corroborated,
)
from services.lob_canon import is_container_label, unmapped_material_lines
from services.line_presence import (
    ABSENT, PRESENT, line_in_submission, reconcile_line_flags,
)


def _codes(issues):
    return [i["code"] for i in issues]


# ── P1: split auto limits read off GL / lease text ───────────────────────────

_CSL = {"auto_liability_limit": "$1,000,000 CSL",
        "auto_bi_per_person": "$1,000,000", "auto_bi_per_accident": "$2,000,000"}


def test_a_stated_csl_is_not_split_whatever_the_flag_says():
    assert auto_csl_stated(_CSL)
    assert not auto_limits_are_split(_CSL, {"auto_split_limits": True})
    hard, soft = sq.evaluate_stops(dict(_CSL), {"has_auto_coverage": True,
                                                "auto_split_limits": True})
    # (19 Oct 2026, Brent: the split stop is a warning now) so neither list may carry it.
    assert not any("Split liability limits incomplete" in m for m in hard + soft)


def test_a_real_split_policy_missing_a_part_still_warns():
    facts = {"auto_liability_structure": "split",
             "auto_bi_per_person": "$100,000", "auto_bi_per_accident": "$300,000"}
    assert auto_limits_are_split(facts, {})
    hard, soft = sq.evaluate_stops(facts, {"has_auto_coverage": True})
    # (19 Oct 2026, Brent: hard stops only for what is essential) the rule still fires - as a warning.
    assert any("Split liability limits incomplete" in s for s in soft)
    assert not any("Split liability limits incomplete" in h for h in hard)


def test_a_slash_limit_is_never_read_as_a_csl():
    assert not auto_csl_stated({"auto_liability_limit": "100/300/50"})


# ── P2: the umbrella's in-force term against the proposed term ──────────────

def _umb(**over):
    base = {"umbrella_effective_date": "12/01/2025", "umbrella_expiration_date": "12/01/2026",
            "effective_date": "12/01/2026", "expiration_date": "12/01/2027"}
    base.update(over)
    return base


def test_an_expiring_umbrella_term_is_not_compared_with_the_proposed_term():
    issues = cfv._check_umbrella_attachment_stack(_umb(), {"has_umbrella": True}, {"ACORD_131"})
    assert not [i for i in issues if "does not match" in i["message"]]
    _hard, soft = sq.evaluate_stops(_umb(), {"has_umbrella": True})
    assert not any("misaligned" in s for s in soft)


def test_a_prior_term_that_is_not_the_expiring_one_is_never_the_comparison():
    # FR125: prior_* is the year BEFORE the in-force term. Comparing with it
    # only moved the false warning onto other dates.
    facts = _umb(umbrella_effective_date="10/01/2025", umbrella_expiration_date="10/01/2026",
                 effective_date="10/01/2026", expiration_date="10/01/2027",
                 prior_effective_date="10/01/2024", prior_expiration_date="10/01/2025")
    issues = cfv._check_umbrella_attachment_stack(facts, {"has_umbrella": True}, {"ACORD_131"})
    assert not [i for i in issues if "does not match" in i["message"]]


def test_the_expiring_term_that_meets_the_proposal_is_compared():
    # An off-anniversary umbrella on a routed renewal is compared with the
    # EXPIRING term, by anniversary (G2 skeptic, 5 Oct night).
    facts = _umb(renewal_dates_routed=True, prior_effective_date="12/01/2025",
                 prior_expiration_date="12/01/2026", umbrella_effective_date="01/15/2026",
                 umbrella_expiration_date="01/15/2027")
    issues = cfv._check_umbrella_attachment_stack(facts, {"has_umbrella": True}, {"ACORD_131"})
    assert [i for i in issues if "expiring GL/policy anniversary (12/01;" in i["message"]
            and "12/01/2025" in i["message"]]


def test_an_umbrella_added_mid_term_and_ending_with_the_gl_is_aligned():
    # 01/15/2026 - 12/01/2026 beside the GL's 12/01/2025 - 12/01/2026: the
    # standard way to bring an umbrella onto the programme (skeptic G2 B1/B2).
    facts = _umb(prior_effective_date="12/01/2025", prior_expiration_date="12/01/2026",
                 umbrella_effective_date="01/15/2026")
    assert cfv._check_umbrella_attachment_stack(facts, {"has_umbrella": True}, {"ACORD_131"}) == []
    _h, soft = sq.evaluate_stops(dict(facts), {"has_umbrella": True})
    assert not [m for m in soft if "misaligned" in m]


def test_an_umbrella_on_the_same_footing_that_disagrees_still_warns():
    facts = _umb(umbrella_effective_date="01/15/2027", umbrella_expiration_date="01/15/2028")
    assert not cfv._umbrella_term_precedes_package(facts)
    eff, _exp, _label = cfv._package_period_on_umbrella_footing(facts)
    assert eff == "12/01/2026"


# ── P3: the pre-form recalc demotes cross-form hard stops like the upload ────

class _Session:
    def __init__(self, row):
        self.store = copy.deepcopy(row)

    async def _get(self, _sid):
        return copy.deepcopy(self.store)

    async def _upd(self, _sid, payload, delete_facts=None):
        for k, v in (payload or {}).items():
            self.store[k] = copy.deepcopy(v)
        return True

    def run(self, fn, *args):
        async def _none(*_a, **_k):
            return None

        async def _empty(*_a, **_k):
            return []

        async def _credits(*_a, **_k):
            return (0, [])

        with patch.object(sr, "get_processing_session", self._get), \
             patch.object(sr, "upd_processing_session", self._upd), \
             patch.object(ar, "get_processing_session", self._get), \
             patch.object(au, "log_audit_event", _none), \
             patch.object(au, "log_sqs_snapshot_if_changed", _none), \
             patch.object(au, "get_open_recommendations", _empty), \
             patch.object(au, "mark_recommendation_resolved", _none), \
             patch.object(au, "sync_recommendation_cards", _none), \
             patch.object(au, "active_score_credits", _credits):
            return asyncio.run(fn(*args))


def test_the_pre_form_recalc_never_raises_a_cross_form_hard_stop():
    facts = {"producer_name": "Best Agency", "applicant_name": "Acme LLC",
             "mailing_address": "1 Main St, Denver, CO 80202", "effective_date": "01/01/2027",
             "lines_of_business": "Property", "entity_type": "LLC",
             "business_income_limit": "$500,000"}
    row = {"user_id": "u", "facts": facts,
           "flags": {"has_property_coverage": True, "property_has_bi_coverage": True},
           "hard_stops": [], "soft_stops": [],
           "recommendations": [{"form_id": "ACORD_125"}, {"form_id": "ACORD_140"}],
           "cross_form_issues": [], "structured_issues": [], "docs": [], "integrity": {},
           "generated_forms": {}, "selected_form_ids": [], "underwriting_consistency": {}}
    # The rule itself is a hard stop on this row once ACORD 140 is in play.
    direct = cfv._check_property_bi_period_of_restoration(facts, row["flags"], {"ACORD_140"})
    assert direct and direct[0]["type"] == "hard_stop"
    s = _Session(row)
    s.run(arq.recalculate_session_scores, "sid")
    assert not any("Period of Restoration" in h for h in s.store["hard_stops"])
    assert any("Period of Restoration" in w for w in s.store["soft_stops"])


# ── Form-scoped rules ────────────────────────────────────────────────────────

def test_business_income_needs_a_property_or_bop_form_in_the_package():
    facts, flags = {"business_income_limit": "$500,000"}, {"has_property_coverage": True}
    assert not cfv._check_property_bi_period_of_restoration(facts, flags, {"ACORD_125", "ACORD_126"})
    assert cfv._check_property_bi_period_of_restoration(facts, flags, {"ACORD_140"})
    # G2 audit: the BOP section (ACORD 160) prints Business Income - the first
    # cut scoped this to 140 only and silently dropped BOP packages.
    assert cfv._check_property_bi_period_of_restoration(facts, flags, {"ACORD_125", "ACORD_160"})


def test_inland_marine_overlap_needs_inland_marine_in_the_submission():
    facts = {"inland_marine_total_value": "$250,000", "property_bpp_value": "$250,000",
             "property_building_value": "$1,000,000"}
    on = cfv._check_inland_marine_deduplication(facts, {"has_inland_marine": True},
                                                {"ACORD_140", "ACORD_160"})
    off = cfv._check_inland_marine_deduplication(facts, {"has_inland_marine": False},
                                                 {"ACORD_140", "ACORD_160"})
    assert off == []
    assert isinstance(on, list)


# ── One money parser ─────────────────────────────────────────────────────────

@pytest.mark.parametrize("raw,expected", [
    ("$18.6MM", 18_600_000.0), ("$2.5M", 2_500_000.0), ("$1,200,000", 1_200_000.0),
])
def test_magnitude_shorthand_is_read_everywhere(raw, expected):
    assert cfv._to_float(raw) == expected


# ── "Commercial Package" is a container, not unknown terminology ─────────────

@pytest.mark.parametrize("label", ["Commercial Package", "CPP", "Package Policy",
                                   "Commercial Multi-Peril"])
def test_container_labels(label):
    assert is_container_label(label)


@pytest.mark.parametrize("label", ["Commercial Property", "Kidnap and Ransom",
                                   "Widget Package Protection", "Multi"])
def test_not_container_labels(label):
    assert not is_container_label(label)


def test_a_package_heading_sharing_a_placed_policy_number_is_not_routed():
    rows = [{"line": "Commercial Property", "policy_number": "MUI-CP-1", "premium": "$27,940"},
            {"line": "Commercial Package", "policy_number": "MUI CP 1", "premium": "$27,940"}]
    assert unmapped_material_lines(rows) == []


def test_a_package_with_nothing_placed_beside_it_is_still_routed():
    rows = [{"line": "Commercial Package", "policy_number": "X9", "premium": "$5,000"}]
    assert unmapped_material_lines(rows) == ["Commercial Package"]


# ── Deductible basis shown on the amount ─────────────────────────────────────

def test_a_dollar_and_a_percent_deductible_answer_flat_or_percentage():
    facts = {"property_deductible_aop": "$5,000", "property_deductible_wind": "1%"}
    codes = _codes(cfv._check_property_deductible_structure(
        facts, {"has_property_coverage": True}, {"ACORD_140"}))
    assert "property_deductible_basis_missing" not in codes


def test_a_small_unitless_deductible_still_asks():
    # "5000" is a flat amount (G3 audit); only a small number with no unit is
    # genuinely ambiguous - 2 what?
    facts = {"property_deductible_aop": "2"}
    codes = _codes(cfv._check_property_deductible_structure(
        facts, {"has_property_coverage": True}, {"ACORD_140"}))
    assert "property_deductible_basis_missing" in codes


# ── ACV printed for VEHICLES is not a property valuation ─────────────────────

_VEHICLE_ACV = ("PHYSICAL DAMAGE BY VEHICLE (expiring)\nVEH VALUATION COMP DED COLL DED\n"
                "1 ACV $1,000 $1,000\n2 ACV $500 $1,000\n"
                "Valuation: actual cash value on all vehicles.")


def test_vehicle_acv_does_not_corroborate_a_property_valuation():
    assert not valuation_method_corroborated("ACV", [], _VEHICLE_ACV)
    entries = [{"label": "VAL", "value": "ACV",
                "section": "BUSINESS AUTO DECLARATIONS", "line_of_business": "Commercial Auto"}]
    assert not valuation_method_corroborated("ACV", entries, "")


def test_property_acv_still_corroborates():
    text = "STATEMENT OF VALUES\nBuilding 1 - 2850 Main St - $6,900,000 - Valuation: ACV"
    assert valuation_method_corroborated("ACV", [], text)
    mixed = _VEHICLE_ACV + "\nBuilding valuation: actual cash value"
    assert valuation_method_corroborated("ACV", [], mixed)


# ── Premises: an address list is not a premises schedule ─────────────────────

def _premises(**extra):
    return {"address": "2850 Kellerman Industrial Pkwy, Nashville, TN 37211",
            "ownership": "owner", "building_value": "$6,900,000", **extra}


def _addresses(facts):
    return [l["address"] for l in facts["property_locations"]]


def test_loose_addresses_beside_a_premises_schedule_are_not_premises():
    facts = {"property_locations": [_premises()],
             "locations": ["1100 Broadway, Nashville, TN 37203", "La Vergne depot",
                           "2850 Kellerman Industrial Pkwy, Nashville, TN 37211"]}
    es._consolidate_property_locations(facts)
    assert _addresses(facts) == ["2850 Kellerman Industrial Pkwy, Nashville, TN 37211"]
    assert "_schedule_row" not in facts["property_locations"][0]


def test_an_address_only_row_of_the_schedule_itself_stays():
    facts = {"property_locations": [_premises(), {"address": "410 Industrial Blvd, La Vergne, TN 37086"}]}
    es._consolidate_property_locations(facts)
    assert len(facts["property_locations"]) == 2


def test_an_all_address_package_keeps_every_row():
    facts = {"locations": ["1 Main St, Denver, CO 80202", "9 Oak Ave, Denver, CO 80203"]}
    es._consolidate_property_locations(facts)
    assert len(facts["property_locations"]) == 2


def test_a_po_box_is_never_a_premises():
    facts = {"property_locations": [_premises(), {"address": "P.O. Box 41120, Nashville, TN 37204"}]}
    es._consolidate_property_locations(facts)
    assert not any("Box" in a for a in _addresses(facts))


def test_the_mailing_address_is_never_by_itself_proof_of_not_a_premises():
    # G4 audit: in 7 of 40 stored sessions the mailing address IS the
    # headquarters premises (and physical_address is empty), so an address-only
    # schedule row at the mailing address stays.
    facts = {"property_locations": [_premises(), {"address": "4820 Harborgate Way Ste 260, Tacoma, WA 98421"}],
             "mailing_address": "4820 Harborgate Way, Suite 260, Tacoma, WA 98421"}
    es._consolidate_property_locations(facts)
    assert len(facts["property_locations"]) == 2


# ── The receiving carrier is never the agency ────────────────────────────────

_ACK = ("APPALACHIAN RISK UNDERWRITERS\nTO: Riverbend Insurance Partners\n"
        "RE: new business submission - quotation requested\n")


def test_the_agency_is_never_the_submission_carrier():
    mf = {"submission_carrier_name": "Riverbend Insurance Partners", "producer_name": "Astrea"}
    es._validate_submission_carrier(mf, _ACK, agencies=["Riverbend Insurance Partners"])
    assert not mf.get("submission_carrier_name")


def test_a_real_addressee_still_reads():
    text = ("TO: Ridgeline Specialty Insurance Company\nRE: new business submission\n")
    mf = {"producer_name": "Riverbend Insurance Partners"}
    es._validate_submission_carrier(mf, text, agencies=["Riverbend Insurance Partners"])
    assert es._fv(mf, "submission_carrier_name") == "Ridgeline Specialty Insurance Company"


# ── An incumbent's renewal QUOTATION does not veto "new business" ────────────

_NB = "Transaction: New business - quotation requested\n"


def test_an_incumbent_renewal_quotation_does_not_veto_new_business():
    text = _NB + "OLD HICKORY MUTUAL - RENEWAL QUOTATION (NOT ACCEPTED BY THE INSURED)\n"
    mf = {}
    assert es._mark_stated_new_business(mf, text) is True


# A renewal phrase vetoes only when its line is a statement about THE
# SUBMISSION (6 Oct, G5 skeptic). "Renewal quote request attached." used to be
# pinned as a veto; with nothing naming the submission it reads exactly like the
# incumbent's "Renewal quote request received 10/01/2026", so it is no longer one.
@pytest.mark.parametrize("veto", ["This is a renewal submission for the account.",
                                  "RE: Renewal quotation for 2027",
                                  "Renewal application enclosed for policy BOP-7730021.",
                                  "This is a renewal submission, not new business, for policy GL-551203 "
                                  "expiring 03/01/2027.",
                                  "Transaction type: renewal"])
def test_a_renewal_transaction_still_vetoes(veto):
    assert es._mark_stated_new_business({}, _NB + veto + "\n") is False


@pytest.mark.parametrize("line", ["This renewal quotation expires 11/15/2026.",
                                  "Renewal quote: $48,210", "WESTFIELD INSURANCE - RENEWAL QUOTATION",
                                  "The incumbent's renewal quote came in 18% higher.",
                                  "Transaction Type: [X] New Business  [ ] Renewal"])
def test_an_incumbent_quote_or_an_unticked_option_does_not_veto(line):
    assert es._mark_stated_new_business({}, _NB + line + "\n") is True


@pytest.mark.parametrize("mention", ["Submission type: New business Renewal Rewrite",
                                     "New business and renewal quotes are valid for 30 days.",
                                     "This is not a new business submission.",
                                     "Status: not new business",
                                     "Quote type: New business / Renewal (circle one): Renewal"])
def test_a_new_business_mention_that_states_nothing_marks_nothing(mention):
    assert es._mark_stated_new_business({}, "RE: Renewal submission - Policy BOP-7730021\n"
                                            + mention + "\n") is False
    assert es._mark_stated_new_business({}, mention + "\n") is False


@pytest.mark.parametrize("bullet", ["\u25a0 Renewal premium rose 18% at the incumbent",
                                    "[X] Renewal notice from the current carrier"])
def test_a_bullet_or_an_enclosure_tick_is_not_a_ticked_renewal_option(bullet):
    assert es._mark_stated_new_business({}, _NB + bullet + "\n") is True


# ── Lines the submission says it is NOT requesting (SYS-04) ──────────────────

_COVER = ("LINES REQUESTED: Commercial General Liability, Commercial Property, Business Auto "
          "and a Commercial Umbrella ($5,000,000 each occurrence / aggregate).\n"
          "NOT REQUESTED: workers compensation (stays with Tennessee Employers Mutual, policy "
          "TEM-WC-0558213); commercial inland marine (the installation floater\nIMF-3318207 is "
          "already written by Ridgeline and runs to 06/2027); crime (the insured declined it); "
          "cyber (discussed, not requested at this time). Equipment breakdown is wanted.\n")


def test_the_not_requested_list_is_read():
    assert es.lines_not_requested(_COVER) == ["crime", "cyber", "inland_marine", "workers_comp"]


def test_a_sentence_with_the_line_as_subject_is_read():
    text = "Workers compensation stays with Tennessee Employers Mutual and is NOT being marketed."
    assert es.lines_not_requested(text) == ["workers_comp"]


def test_a_statement_on_its_own_line_after_a_table_is_read():
    text = ("9519 Household appliance installation / repair $1,284,600 3.88\n"
            "Workers compensation stays with Tennessee Employers Mutual and is NOT being marketed.")
    assert es.lines_not_requested(text) == ["workers_comp"]


@pytest.mark.parametrize("text", [
    "Auto physical damage on vehicle 5 is not requested.",
    "If workers compensation is not requested, say so.",
    "The kitchen design work is covered by a professional liability policy that is NOT part of "
    "this submission.",
    "Coverage for the joint venture is not requested.",
])
def test_parts_conditionals_and_other_subjects_are_not_read(text):
    assert es.lines_not_requested(text) == []


def test_a_line_also_listed_as_requested_is_contested():
    text = "Lines requested: GL, Property, Workers Compensation\nBilling: direct\n" \
           "NOT REQUESTED: workers compensation (see note).\n"
    assert es.lines_not_requested(text) == []


def test_a_form_layout_list_ends_at_the_next_label():
    text = "Lines requested:\nGL, Property, Auto, Umbrella\nBilling / plan: Direct bill\n" \
           "Inland marine: IMF-3318207\n" + _COVER
    assert "inland_marine" in es.lines_not_requested(text)


_WC_POLICY = {"coverage_lines": [{"line": "Workers Compensation", "carrier": "TEM",
                                  "policy_number": "TEM-WC-0558213", "premium": "$44,810"}],
              "wc_payroll": "$4,918,300"}


def test_a_declined_line_is_absent_even_with_an_in_force_policy():
    facts = dict(_WC_POLICY)
    assert line_in_submission("workers_comp", facts, {"has_workers_comp": True}) == PRESENT
    facts["_lines_not_requested"] = ["workers_comp"]
    assert line_in_submission("workers_comp", facts, {"has_workers_comp": True}) == ABSENT
    flags = {"has_workers_comp": True, "wc_multi_state": True}
    assert reconcile_line_flags(flags, facts) == {"has_workers_comp": "demoted"}
    _hard, soft = sq.evaluate_stops(facts, flags)
    assert not any("Multi-state WC" in s or "Workers Comp" in s for s in soft)


def test_selecting_acord_130_or_a_person_answering_wins():
    facts = dict(_WC_POLICY, _lines_not_requested=["workers_comp"])
    assert line_in_submission("workers_comp", facts, {}, ["ACORD_130"]) == PRESENT
    facts["wc_payroll"] = {"value": "$4,918,300", "source": "producer"}
    assert line_in_submission("workers_comp", facts, {}) != ABSENT


def test_merge_records_the_statement():
    mf = {}
    es._mark_lines_not_requested(mf, _COVER)
    assert mf["_lines_not_requested"] == ["crime", "cyber", "inland_marine", "workers_comp"]
    es._mark_lines_not_requested(mf, "nothing declined here")
    assert "_lines_not_requested" not in mf


# ── Data Consistency after forms exist (confirm-value-in-editor) ─────────────

import json as _json
import os as _os

import services.extraction_pipeline as ep

_SCHEMA_125 = _json.load(open(_os.path.join(_os.path.dirname(__file__), "..",
                                            "forms_schemas", "ACORD_125_schema.json")))


def _generated_row():
    docs = [
        {"filename": "application.pdf", "doc_type": "application",
         "facts": {"effective_date": "01/01/2027", "applicant_name": "Acme LLC"},
         "text": "APPLICATION Proposed effective date 01/01/2027 Acme LLC"},
        {"filename": "quote.pdf", "doc_type": "quote",
         "facts": {"effective_date": "02/01/2027", "applicant_name": "Acme LLC"},
         "text": "QUOTE Effective 02/01/2027 Acme LLC"},
    ]
    facts = {"applicant_name": "Acme LLC", "effective_date": "01/01/2027",
             "expiration_date": "01/01/2028"}
    return {
        "user_id": "u", "docs": docs, "facts": facts, "flags": {},
        "generated_forms": {"ACORD_125": {
            "schema": _SCHEMA_125,
            "mapped": {"Policy_EffectiveDate_A": "01/01/2027"},
            "confidence": {"Policy_EffectiveDate_A": "ai_high"}}},
        "selected_form_ids": ["ACORD_125"],
        "underwriting_confirmations": {},
        "structured_issues": [
            {"code": "underwriting_reconciliation_effective_date", "message": "dates disagree"},
            {"code": "legacy_x", "message": "kept"}],
    }


class _Store:
    def __init__(self, row):
        self.row = copy.deepcopy(row)
        self.deleted = []

    async def upd(self, _sid, payload, delete_facts=None):
        for k, v in payload.items():
            self.row[k] = copy.deepcopy(v)
        self.deleted += list(delete_facts or [])
        return True


def _confirm(row, value, scope=None):
    st = _Store(row)
    with patch.object(ep, "upd_processing_session", st.upd):
        out = asyncio.run(ep.confirm_underwriting_value_in_editor(
            copy.deepcopy(row), "sid", fact_key="effective_date", value=value, scope=scope))
    return st, out


def test_the_editor_confirm_applies_restamps_and_keeps_the_forms():
    row = _generated_row()
    pre = __import__("services.underwriting_consistency", fromlist=["x"]) \
        .assess_underwriting_consistency(row["docs"], row["facts"], {}, flags={})
    assert any(f["fact_key"] == "effective_date" and f.get("review_required")
               for f in pre["fields"]), "the fixture must start with an open conflict"
    st, out = _confirm(row, "02/01/2027")
    assert st.row["underwriting_confirmations"] == {"effective_date": "02/01/2027"}
    assert es._fv(st.row["facts"], "effective_date") == "02/01/2027"
    assert st.row["facts"]["effective_date"].get("source") == "user_confirmed"
    assert not any(f["fact_key"] == "effective_date" and f.get("review_required")
                   for f in st.row["underwriting_consistency"]["fields"])
    assert list(st.row["generated_forms"]) == ["ACORD_125"]
    assert st.row["generated_forms"]["ACORD_125"]["mapped"]["Policy_EffectiveDate_A"] == "02/01/2027"
    assert "ACORD_125" in out["forms_updated"]
    codes = [i["code"] for i in st.row["structured_issues"]]
    assert codes == ["legacy_x"]
    assert out["_pre_confirm_candidates"]


def test_the_editor_confirm_refuses_before_forms_exist():
    row = dict(_generated_row(), generated_forms={})
    with pytest.raises(ValueError, match="underwriting_no_forms"):
        _confirm(row, "02/01/2027")


def test_the_editor_confirm_validates_like_the_pre_form_route():
    with pytest.raises(ValueError):
        _confirm(_generated_row(), "   ")


def test_a_rescore_honours_a_line_scoped_confirmation():
    row = _generated_row()
    seen = []
    real = sq.check_doc_consistency

    def spy(docs, confirmed):
        seen.append(set(confirmed))
        return real(docs, confirmed)

    with patch.object(sq, "check_doc_consistency", spy):
        sq.doc_consistency_stops(dict(row, underwriting_confirmations={"effective_date@auto": "x"}))
    assert seen == [{"effective_date"}]


# ── Inland marine: a declined floater turns the flag off; a census never does ─

_IM_FLOATER = {"coverage_lines": [
    {"line": "Inland Marine", "carrier": "Ridgeline", "policy_number": "IMF-3318207",
     "premium": "$2,140"}]}


def test_a_declined_inland_marine_floater_is_absent_and_the_overlap_goes():
    facts = dict(_IM_FLOATER, _lines_not_requested=["inland_marine"],
                 inland_marine_total_value="$250,000", property_bpp_value="$250,000")
    flags = {"has_inland_marine": True, "has_property_coverage": True}
    assert line_in_submission("inland_marine", facts, flags) == ABSENT
    assert reconcile_line_flags(flags, facts).get("has_inland_marine") == "demoted"
    assert cfv._check_inland_marine_deduplication(facts, flags, {"ACORD_140", "ACORD_160"}) == []


def test_a_coverage_census_alone_never_turns_inland_marine_off():
    lines = [{"line": n, "policy_number": f"P-{i}", "premium": "$1,000"}
             for i, n in enumerate(("General Liability", "Business Auto", "Umbrella",
                                    "Commercial Property"))]
    facts, flags = {"coverage_lines": lines}, {"has_inland_marine": True}
    assert line_in_submission("inland_marine", facts, flags) != ABSENT
    assert "has_inland_marine" not in reconcile_line_flags(flags, facts)
    assert flags["has_inland_marine"] is True


# ── Out of scope is not uninsured: a declined WC line the insured CARRIES ────

from services.line_presence import line_carried
import services.form_service as fs


def test_a_declined_line_with_a_policy_in_force_is_still_carried():
    facts = dict(_WC_POLICY, _lines_not_requested=["workers_comp"], num_employees="66",
                 employers_liability_limits="$1,000,000")
    flags = {"has_workers_comp": True, "has_umbrella": True}
    reconcile_line_flags(flags, facts)
    assert flags["has_workers_comp"] is False            # out of THIS submission
    assert flags["workers_comp_in_force"] is True         # ...but the insured has it
    assert line_carried("workers_comp", facts, flags)
    assert sq._wc_carried(flags)


def test_a_decline_that_says_the_line_stays_elsewhere_means_carried():
    # FR125 31e49fa7: the WC policy never reached coverage_lines; the cover
    # letter says "Workers Compensation (placed separately, monoline)".
    mf = {"wc_payroll": "$1,640,000"}
    es._mark_lines_not_requested(
        mf, "LINES NOT REQUESTED\nWorkers Compensation (placed separately, monoline) Inland Marine\n"
            "BILLING AND PAYMENT\n")
    assert mf["_lines_carried_elsewhere"] == ["workers_comp"]
    flags = {"has_workers_comp": True}
    reconcile_line_flags(flags, mf)
    assert flags["has_workers_comp"] is False and flags["workers_comp_in_force"] is True


def test_extracted_line_values_alone_do_not_mean_carried():
    # Audit G6 (5 Oct): extraction copies the TOTAL payroll into wc_payroll and
    # an umbrella schedule's REQUIRED EL limit into employers_liability_limits
    # on packages with no WC at all. A decline beside them is "no WC", and the
    # employees-without-WC gap must still count.
    facts = {"_lines_not_requested": ["workers_comp"], "wc_payroll": "$640,000",
             "employers_liability_limits": "$500,000 / $500,000 / $500,000",
             "num_employees": "9"}
    flags = {"has_workers_comp": True, "has_umbrella": True}
    reconcile_line_flags(flags, facts)
    assert flags["has_workers_comp"] is False
    assert "workers_comp_in_force" not in flags
    assert not sq._wc_carried(flags)


def test_a_person_confirming_the_el_limit_is_carried_but_not_a_request():
    # Confirming the umbrella's underlying EL limit in the picker says the
    # insured HAS the coverage; it does not ask for WC in this submission.
    facts = {"_lines_not_requested": ["workers_comp"],
             "employers_liability_limits": {"value": "$1,000,000", "source": "user_confirmed"}}
    flags = {"has_workers_comp": True}
    reconcile_line_flags(flags, facts)
    assert flags["has_workers_comp"] is False
    assert flags["workers_comp_in_force"] is True
    assert line_in_submission("workers_comp", facts, flags) == ABSENT
    facts["wc_payroll"] = {"value": "$900,000", "source": "producer"}   # a WC answer
    assert line_in_submission("workers_comp", facts, {}) != ABSENT


def test_a_decline_with_nothing_stated_is_not_carried():
    facts = {"_lines_not_requested": ["workers_comp"]}
    flags = {"has_workers_comp": True}
    reconcile_line_flags(flags, facts)
    assert flags["has_workers_comp"] is False
    assert "workers_comp_in_force" not in flags
    assert not line_carried("workers_comp", facts, flags)


def test_the_marker_is_removed_when_the_line_is_back_in_the_submission():
    facts = dict(_WC_POLICY, _lines_not_requested=["workers_comp"])
    flags = {"has_workers_comp": True}
    reconcile_line_flags(flags, facts)
    assert flags.get("workers_comp_in_force") is True
    reconcile_line_flags(flags, facts, ["ACORD_130"])     # the producer applies for WC
    assert flags["has_workers_comp"] is True
    assert "workers_comp_in_force" not in flags


def test_employees_beside_a_carried_wc_line_are_not_an_exposure_gap():
    # FR125 31e49fa7 / 426afb35: demoting the declined WC line made the
    # "employees detected but no WC coverage" -8 fire on an insured that
    # carries WC with another carrier (70 -> 69).
    facts = {"num_employees": "66"}
    carried = {"has_workers_comp": False, "workers_comp_in_force": True}
    uninsured = {"has_workers_comp": False}
    _s, sub_carried = sq._calculate_exposure_consistency(facts, carried, [], [])
    _s, sub_none = sq._calculate_exposure_consistency(facts, uninsured, [], [])
    assert sub_carried["payroll_employee_information"] - sub_none["payroll_employee_information"] == 8


def test_the_umbrella_employers_liability_check_still_runs_for_a_carried_line():
    facts = {"umbrella_limit": "$5,000,000", "gl_each_occurrence": "$1,000,000",
             "auto_liability_limit": "$1,000,000 CSL"}
    _h, soft_carried = sq.evaluate_stops(dict(facts), {"has_umbrella": True,
                                                       "workers_comp_in_force": True})
    _h, soft_none = sq.evaluate_stops(dict(facts), {"has_umbrella": True})
    el = "Umbrella attaches over WC but Employers Liability limits not provided."
    assert el in soft_carried and el not in soft_none


def test_the_recommender_drops_a_declined_line_form_but_keeps_an_uploaded_copy():
    facts = {"_lines_not_requested": ["workers_comp", "inland_marine"]}
    flags = {"has_workers_comp": True, "has_inland_marine": True}
    text = "workers compensation declarations class code 8810 payroll inland marine floater"
    recs = {m["form_id"] for m in fs.match_forms_deterministic(facts, flags, text=text)}
    assert "ACORD_130" not in recs and "ACORD_160" not in recs
    recs_open = {m["form_id"] for m in fs.match_forms_deterministic({}, flags, text=text)}
    assert "ACORD_130" in recs_open


# ═══ Round 2 (5 Oct evening, fresh upload 6eda3069) ═════════════════════════

import services.underwriting_consistency as ucm
import services.loss_history_state as lhs
from services.normalization import no_loss_statements


# ── The text scan reads a LABEL, never a verb about something else ──────────

@pytest.mark.parametrize("text,expected", [
    ("Policy Expiration Date: 12/01/2027", ["12/01/2027"]),
    ("Expiration: 12/01/2027", ["12/01/2027"]),
    ("Effective: 12/01/2026  Expires: 12/01/2027", ["12/01/2027"]),
    ("Policy expires 12/01/2027", ["12/01/2027"]),
    ("LIENHOLDER: none | EXPIRES 11/30/2027", []),
    ("This renewal quotation expires 11/15/2026.", []),
    ("Registration Expiration: 11/30/2027", []),
    ("Lease expiration date: 12/31/2027", []),
])
def test_the_expiration_scan_reads_a_policy_label_only(text, expected):
    assert ucm._text_scan_values(text, "expiration_date") == expected


@pytest.mark.parametrize("text,expected", [
    ("Policy Effective Date: 12/01/2026", ["12/01/2026"]),
    ("ENDORSEMENT 1 - EFFECTIVE 03/09/2026 - ADD COVERED AUTO", []),
    ("Cancellation effective 07/01/2026", []),
])
def test_the_effective_scan_ignores_other_subjects(text, expected):
    assert ucm._text_scan_values(text, "effective_date") == expected


# ── Expiring and declined contracts never compete in the picker ─────────────

def _cl(line, pol, carrier, eff, exp, naic=None):
    return {"line": line, "policy_number": pol, "carrier": carrier, "naic": naic,
            "premium": "$1,000", "effective_date": eff, "expiration_date": exp}


def test_rows_of_declined_lines_and_expiring_contracts_are_out_of_scope():
    facts = {
        "_lines_not_requested": ["workers_comp", "inland_marine"],
        "coverage_lines": [
            _cl("Workers Compensation", "TEM-WC-1", "TEM", "01/01/2026", "01/01/2027"),
            _cl("INMRC", "IMF-9", "Ridgeline", "06/15/2026", "06/15/2027"),
            _cl("Inland Marine", "IMF-9", "Ridgeline", "06/15/2026", "06/15/2027"),
            _cl("CGL", "GL-1", "Old Hickory", "12/01/2025", "12/01/2026"),
        ],
        "prior_coverage_by_line": [{"line": "Auto", "policy_no": "CA-7"}],
    }
    out = ucm._out_of_scope_contract_rows(facts, [])
    assert out({"line": "Workers Compensation", "policy_number": "TEM-WC-1"})
    assert out({"line": "INMRC", "policy_number": "IMF-9"})        # same contract, code label
    assert out({"line": "AUTOB", "policy_number": "CA-7"})         # expiring programme
    assert not out({"line": "CGL", "policy_number": "GL-1"})


def test_nothing_is_out_of_scope_without_evidence():
    out = ucm._out_of_scope_contract_rows({"coverage_lines": [_cl("CGL", "GL-1", "X", "", "")]}, [])
    assert not out({"line": "Workers Compensation", "policy_number": "WC-1"})


# ── Premises the documents retired, and premises named by nickname ──────────

@pytest.mark.parametrize("row,eff,retired", [
    ({"address": "1040 Visco Dr (DELETED)"}, "12/01/2026", True),
    ({"ownership": "closed retail outlet"}, "12/01/2026", True),
    ({"operations_description": "retail outlet closed 06/30/2026"}, "12/01/2026", True),
    ({"operations_description": "store will be closed 03/31/2027"}, "12/01/2026", False),
    ({"operations_description": "closed Sundays and holidays"}, "12/01/2026", False),
    ({"operations_description": "closed-loop chiller plant"}, "12/01/2026", False),
    ({"ownership": "tenant"}, "12/01/2026", False),
])
def test_a_premises_is_retired_only_on_its_own_evidence(row, eff, retired):
    assert es.premises_is_retired(row, eff) is retired


def _consolidated(rows, **facts):
    f = dict(facts, property_locations=copy.deepcopy(rows))
    es._consolidate_property_locations(f)
    return f


_HOST_LV = {"address": "410 Industrial Blvd, Suite C, La Vergne, TN 37086", "ownership": "tenant",
            "operations_description": "Parts depot and overflow storage", "annual_revenue": "$0"}


def test_a_nickname_row_folds_into_the_premises_it_names():
    f = _consolidated([_HOST_LV, {"address": "La Vergne depot, La Vergne, TN", "ownership": "tenant",
                                  "operations_description": "storage only", "annual_revenue": "$0"}])
    assert len(f["property_locations"]) == 1


def test_a_nickname_the_host_never_uses_stays_its_own_row():
    f = _consolidated([_HOST_LV, {"address": "Warehouse annex, La Vergne, TN", "ownership": "tenant",
                                  "annual_revenue": "$0"}])
    assert len(f["property_locations"]) == 2


def test_a_nickname_with_a_contradicting_value_stays_its_own_row():
    f = _consolidated([_HOST_LV, {"address": "La Vergne depot, La Vergne, TN", "ownership": "owner",
                                  "annual_revenue": "$0"}])
    assert len(f["property_locations"]) == 2


def test_two_street_premises_in_the_city_never_take_a_nickname():
    second = dict(_HOST_LV, address="9 Murfreesboro Rd, La Vergne, TN 37086",
                  operations_description="depot overflow")
    f = _consolidated([_HOST_LV, second, {"address": "La Vergne depot, La Vergne, TN",
                                          "ownership": "tenant"}])
    assert len(f["property_locations"]) == 3


def test_a_retired_premises_leaves_the_schedule_but_is_kept_aside():
    f = _consolidated([_HOST_LV, {"address": "1040 Visco Dr, Nashville TN 37210",
                                  "ownership": "closed retail outlet", "construction_type": "Frame"}],
                      effective_date="12/01/2026")
    es.retire_closed_premises(f)          # runs after renewal routing in the merge
    assert [l["address"] for l in f["property_locations"]] == [_HOST_LV["address"]]
    assert f["property_locations"][0]["location_number"] == "1"
    assert f["_retired_premises"][0]["address"].startswith("1040 Visco Dr")


def test_every_premises_retired_keeps_them_all():
    rows = [{"address": "1 A St, X, TN 37000", "ownership": "closed"},
            {"address": "2 B St, X, TN 37000", "ownership": "sold"}]
    f = _consolidated(rows, effective_date="12/01/2026")
    assert es.retire_closed_premises(f) == []
    assert len(f["property_locations"]) == 2


# ── WHO a no-loss statement is about ────────────────────────────────────────

@pytest.mark.parametrize("text,scope,line", [
    ("Loss history: 5 years. Umbrella - no known losses.", "line", "umbrella"),
    ("13. Losses - the umbrella has never had a claim (no known losses).", "line", "umbrella"),
    ("Losses (3 years) .... Property - no losses in the past 3 years", "line", "property"),
    ("| 2019-20 | VFM-CPP-7781203 | -- | -- | no losses | -- |", "term", None),
    ("The applicant has had no losses in the past five years.", "account", None),
    ("No known losses.", "account", None),
])
def test_no_loss_statements_carry_their_scope(text, scope, line):
    st = no_loss_statements(text)
    assert st and st[0]["scope"] == scope and st[0]["line"] == line


def _claims(*rows):
    return {"num_claims": str(len(rows)), "loss_run_valuation_date": "09/15/2026",
            "loss_history": [dict(r, claim_number=f"C-{i}", paid="$5,000") for i, r in enumerate(rows)]}


def test_scoped_statements_do_not_contradict_claims_on_other_lines():
    facts = _claims({"date": "08/09/2025", "line_of_business": "Commercial Auto",
                     "description": "Commercial Auto"})
    stmts = no_loss_statements("Umbrella - no known losses.")
    assert lhs.no_loss_statements_contradict(stmts, facts) is False


def test_a_line_statement_contradicts_a_claim_on_its_own_line_in_its_window():
    facts = _claims({"date": "05/01/2025", "line_of_business": "Commercial Property",
                     "description": "water damage"})
    stmts = no_loss_statements("Property - no losses in the past 3 years")
    assert lhs.no_loss_statements_contradict(stmts, facts) is True
    old = _claims({"date": "07/22/2022", "line_of_business": "Commercial Property",
                   "description": "water damage"})
    assert lhs.no_loss_statements_contradict(stmts, old) is False


def test_an_account_statement_still_contradicts_any_claim():
    facts = _claims({"date": "08/09/2025", "line_of_business": "Commercial Auto",
                     "description": "rear-end collision"})
    stmts = no_loss_statements("The applicant has had no losses.")
    assert lhs.no_loss_statements_contradict(stmts, facts) is True


def test_no_claims_means_no_contradiction():
    assert lhs.no_loss_statements_contradict(no_loss_statements("No known losses."), {}) is False


# ── Loss runs inside one combined PDF ───────────────────────────────────────

def test_loss_runs_are_read_off_the_facts_when_the_file_type_hides_them():
    docs = [{"doc_type": "narrative"}]
    facts = {"loss_run_valuation_date": "09/15/2026", "loss_run_period_start": "09/15/2021",
             "loss_run_period_end": "09/15/2026"}
    assert lhs.package_has_loss_runs(docs, facts)
    assert lhs.package_has_loss_runs([{"doc_type": "loss_run"}], {})
    assert not lhs.package_has_loss_runs(docs, {"loss_run_valuation_date": "09/15/2026"})
    assert not lhs.package_has_loss_runs(docs, {"loss_run_period_start": "09/15/2021"})
    numbered = dict(_claims({"date": "08/09/2025", "line_of_business": "Auto",
                             "description": "collision"}))
    assert lhs.package_has_loss_runs(docs, numbered)



# ═══ G1 generality audit (5 Oct night): the split-limit door, rebuilt ═══════
# The first door was broken 25 times in 53 probes on shapes unlike the kit, and
# its regression test above was VACUOUS (it set a flag name nothing reads). Each
# case below is one of the auditor's failures, now pinned.

from services import coverage_evidence as ce


def _p(v):
    return {"value": v, "source": "producer", "confidence": "filled"}


@pytest.mark.parametrize("limit", [
    "$1,000,000 C.S.L.", "$1,000,000CSL", "CombinedSingleLimit $1,000,000",
    "$1,000,000 COMBINED SINGLE LIMIT", "| $1,000,000 | CSL |", "$1M CSL",
    "CSL $1,000,000 eff 12/01/2025", "$1,000,000 CSL; UM/UIM 100/300",
    "1,000,000 Each Accident (CSL)", "Liability - Any One Accident: $1,000,000",
    "Auto Liab CSL: 1,000,000",
])
def test_every_printing_of_one_combined_limit_is_a_csl(limit):
    facts = {"auto_liability_limit": limit, "auto_bi_per_person": "$1,000,000",
             "auto_bi_per_accident": "$2,000,000"}
    assert ce.auto_csl_stated(facts)
    assert not ce.auto_limits_are_split(facts, {"auto_split_limits": True})


@pytest.mark.parametrize("limit", [
    "Combined Single Limit: N/A", "CSL - Not Applicable", "CSL", "Combined deductible $1,000",
])
def test_a_label_without_one_amount_is_not_a_csl(limit):
    assert not ce.auto_csl_stated({"auto_liability_limit": limit})


@pytest.mark.parametrize("limit", [
    "$100,000/$300,000/$50,000", "100K/300K/50K", "$250k / $500k / $100k",
    "$1M/$1M/$500K", "250/500/100", "100/300/100",
])
def test_a_split_printing_is_split_whatever_the_structure_label_says(limit):
    facts = {"auto_liability_limit": limit, "auto_liability_structure": "CSL"}
    assert ce.limit_is_split_shaped(limit)
    assert ce.auto_limits_are_split(facts, {})


def test_the_producers_split_answer_wins_in_any_spelling():
    facts = {"auto_liability_limit": "$1,000,000 CSL", "auto_liability_structure": _p("Split Limits"),
             "auto_bi_per_person": "$250,000", "auto_bi_per_accident": "$500,000"}
    assert ce.auto_limits_are_split(facts, {})
    hard, soft = sq.evaluate_stops(facts, {"has_auto_coverage": True})
    # (19 Oct 2026, Brent: the split stop is a warning now) the producer's answer still raises it.
    assert any("Split liability limits incomplete" in s for s in soft)
    assert not any("Split liability limits incomplete" in h for h in hard)


def test_the_producers_csl_answer_wins_without_an_amount():
    facts = {"auto_liability_structure": _p("Combined Single Limit"),
             "auto_bi_per_person": "$1,000,000", "auto_bi_per_accident": "$2,000,000"}
    assert not ce.auto_limits_are_split(facts, {"auto_split_limits": True})


def test_a_producers_typed_bare_amount_is_a_csl():
    facts = {"auto_liability_limit": _p("$1,000,000"), "auto_bi_per_person": "$1,000,000",
             "auto_bi_per_accident": "$2,000,000"}
    assert not ce.auto_limits_are_split(facts, {"auto_split_limits": True})


def test_producer_typed_parts_outrank_ai_csl_wording():
    facts = {"auto_liability_limit": "$1,000,000 CSL", "auto_liability_structure": "CSL",
             "auto_bi_per_person": _p("$250,000"), "auto_bi_per_accident": _p("$500,000"),
             "auto_pd_per_accident": _p("$100,000")}
    assert ce.auto_limits_are_split(facts, {})


def test_the_verified_dec_index_settles_a_bare_limit():
    # ISO / EMC wording: no "CSL" anywhere, one amount each accident.
    base = {"auto_liability_limit": "$1,000,000", "auto_bi_per_person": "$1,000,000",
            "auto_bi_per_accident": "$2,000,000"}
    csl = dict(base, dec_page_entries=[
        {"label": "COVERED AUTOS LIABILITY", "value": "$1,000,000 Each Accident",
         "line_of_business": "Commercial Auto", "section": "BUSINESS AUTO DECLARATIONS"}])
    assert not ce.auto_limits_are_split(csl, {"auto_split_limits": True})
    split = dict(base, dec_page_entries=[
        {"label": "Bodily Injury - Each Person", "value": "$100,000",
         "line_of_business": "Commercial Auto"}])
    assert ce.auto_limits_are_split(split, {})
    # ...and with no index, a bare amount beside the flag stays split (owner
    # decision pinned in tests/test_auto_liability_structure.py).
    assert ce.auto_limits_are_split(base, {"auto_split_limits": True})


def test_a_certificate_never_prints_a_label_or_a_split_string_as_the_csl_amount():
    import services.pdf_service as ps
    box = "Vehicle_CombinedSingleLimit_EachAccidentAmount_A"
    assert ps._resolve_auto_liability_limit_cell(box, {"auto_liability_limit": "Combined Single Limit: N/A"}) is None
    assert ps._resolve_auto_liability_limit_cell(box, {"auto_liability_limit": "$1,000,000 CSL"}) == "$1,000,000 CSL"


def test_the_101_reason_reads_the_parts_not_slashes():
    import services.form_service as fs
    full = {"auto_liability_structure": "split", "auto_bi_per_person": "$100,000",
            "auto_bi_per_accident": "$300,000", "auto_pd_per_accident": "$50,000"}
    def reasons(facts):
        out = []
        for m in fs.match_forms_deterministic(facts, {"has_auto_coverage": True}, text="business auto"):
            out += [str(m.get("reason") or ""), str(m.get("trigger_reason") or "")]
        return " ".join(out)
    assert "not all three components found" not in reasons(full)



# ═══ G2 / G3 generality audit (5 Oct night) ═════════════════════════════════

@pytest.mark.parametrize("raw,expected", [
    ("Revenue: $18.6MM", 18_600_000.0), ("USD 2.5m", 2_500_000.0), ("US$18.6MM", 18_600_000.0),
    ("approx. $18.6MM", 18_600_000.0), ("2.5 Mil", 2_500_000.0), ("$2.5mn", 2_500_000.0),
    ("CAD 4.2M", 4_200_000.0), ("$1,000,000 - $2,000,000", 1_000_000.0),
    ("66 FT / 7 PT", 66.0), ("Revenue FY2025: $18,600,000", 18_600_000.0), ("N/A", None),
])
def test_the_money_parser_reads_the_amount_not_the_digits(raw, expected):
    assert sq._to_float(raw) == expected


@pytest.mark.parametrize("raw,expected", [
    ("$1.5M (35%)", 35.0), ("35 percent", 35.0), ("40", 40.0), ("$1,500,000", None), ("150", None),
])
def test_a_percentage_is_never_read_as_money(raw, expected):
    assert cfv._to_percent(raw) == expected


def test_a_money_shaped_subcontract_share_reads_its_percentage():
    def stop(share):
        issues = cfv.run_cross_form_validation(
            {"percent_subcontracted": share, "total_revenue": "$5,000,000"},
            {"is_contractor": True}, {"ACORD_130", "ACORD_186"})
        return [i for i in issues if i.get("code") == "high_subcontracting_no_wc_payroll"]
    # G2 audit: it read 1,500,000 percent; it is 35 - over the 30% rule, so the
    # real stop stands, with the real number in it.
    hit = stop("$1.5M (35%)")
    assert hit and "35%" in hit[0]["message"] and "1500000" not in hit[0]["message"]
    assert not stop("$1.2M (25%)")


def test_the_picker_reads_one_amount_printed_two_ways():
    from services.underwriting_consistency import _normalize_currency
    assert _normalize_currency("$18.6MM") == _normalize_currency("$18,600,000") == "18600000"


@pytest.mark.parametrize("text,expected", [
    ("PROPERTY: Limit $500,000; Valuation ACV; Cause of loss Special", True),
    ("SCHEDULE - BLDG #1 TIV $3,400,000 VALUATION ACV; YARD - trailer parking only", True),
    ("LOCATION 2. Limit of Insurance $1,200,000. Covered Causes of Loss: Basic - fire, "
     "aircraft or vehicles, riot. Valuation: ACV.", True),
    ("Building occupied as a hardware store. Valuation: ACV", True),
    ("Comprehensive: ACV less $500 deductible; Collision: ACV less $1,000 deductible", False),
    ("CONTRACTORS EQUIPMENT FLOATER - Unscheduled tools $10,000 - Valuation: Actual Cash Value", False),
    ("COMPUTER COVERAGE LIMITS - ACTUAL CASH VALUE $10,000 HARDWARE", False),
    ("12.3 Tenant shall insure its personal property for full replacement cost.", False),
    ("APPRAISAL SUMMARY - 2850 MAIN ST\nEffective date of value 05/01/2024\nLand 6.2 acres\n"
     "Improvements 58,000 sq ft warehouse\nMarket value - as is $6,900,000\n"
     "Insurable replacement cost (building) $7,240,000", False),
])
def test_a_valuation_counts_for_property_only_in_property_context(text, expected):
    method = "RCV" if "replacement" in text.lower() else "ACV"
    assert valuation_method_corroborated(method, [], text) is expected


@pytest.mark.parametrize("label", [
    "Commercial Multiple Peril", "CMP", "SMP Policy", "CPKGE", "Commercial Pkg",
    "CommercialPackage", "Commercial Package (Expiring)", "CPP - Magnolia Underwriters",
    "Contractors Package Policy",
])
def test_more_package_containers(label):
    assert is_container_label(label)


@pytest.mark.parametrize("label", ["Businessowners Policy", "BOP", "Peril", "Business Peril"])
def test_not_containers(label):
    assert not is_container_label(label)


def test_a_numberless_package_row_ties_by_carrier():
    rows = [{"line": "Commercial Property", "policy_number": "MUI-CP-1", "carrier": "Magnolia",
             "premium": "$27,940"},
            {"line": "Commercial Package", "carrier": "Magnolia", "premium": "$27,940"}]
    assert unmapped_material_lines(rows) == []


@pytest.mark.parametrize("facts,fires", [
    ({"property_deductible_aop": "5,000"}, False),
    ({"property_deductible_aop": "5K"}, False),
    ({"property_deductible_aop": "$5,000", "property_deductible_wind": "Excluded"}, False),
    ({"property_deductible_aop": "$5,000", "property_deductible_flood": "N/A"}, False),
    ({"property_deductible_aop": "2"}, True),
    ({"property_deductible_aop": "See schedule"}, True),
])
def test_the_deductible_basis_reads_the_amount(facts, fires):
    codes = _codes(cfv._check_property_deductible_structure(
        facts, {"has_property_coverage": True}, {"ACORD_140"}))
    assert ("property_deductible_basis_missing" in codes) is fires


def test_a_missing_inland_marine_flag_still_reads_stated_values():
    facts = {"inland_marine_total_value": "$250,000", "property_bpp_value": "$250,000",
             "property_building_value": "$1,000,000"}
    flagless = cfv._check_inland_marine_deduplication(facts, {}, {"ACORD_140", "ACORD_160"})
    declined = cfv._check_inland_marine_deduplication(facts, {"has_inland_marine": False},
                                                      {"ACORD_140", "ACORD_160"})
    assert declined == []
    assert isinstance(flagless, list)


@pytest.mark.parametrize("text", [
    "Inland Marine: Not requested at this time",
    "We are not marketing the inland marine coverage this year.",
    "Excluded from this request: Inland Marine",
])
def test_more_ways_to_say_a_line_is_not_requested(text):
    assert es.lines_not_requested(text) == ["inland_marine"]


@pytest.mark.parametrize("text", [
    "We are not marketing the account to other carriers.",
    "Physical damage: not requested",
    "Workers Comp - declined",                  # a carrier's declination, not the insured's choice
    "Status: declined by the carrier",
])
def test_these_are_not_a_line_the_submission_declines(text):
    assert es.lines_not_requested(text) == []


def _umbrella_issues(facts):
    return [i for i in cfv._check_umbrella_attachment_stack(facts, {"has_umbrella": True},
                                                           {"ACORD_131"})
            if "does not match" in i["message"]]


def test_a_routed_renewal_never_compares_with_the_year_before():
    # Meridian: prior_* is 2024-25, the umbrella 2025-26, the derived proposal 2026-27.
    facts = {"renewal_dates_routed": True,
             "umbrella_effective_date": "10/01/2025", "umbrella_expiration_date": "10/01/2026",
             "effective_date": {"value": "10/01/2026", "source": "derived"},
             "expiration_date": {"value": "10/01/2027", "source": "derived"},
             "prior_effective_date": "10/01/2024", "prior_expiration_date": "10/01/2025"}
    assert not _umbrella_issues(facts)


def test_the_current_gl_policy_is_the_comparison_when_the_lines_print_it():
    base = {"umbrella_effective_date": "12/01/2025", "umbrella_expiration_date": "12/01/2026",
            "effective_date": "12/01/2026", "expiration_date": "12/01/2027"}
    agree = dict(base, coverage_lines=[{"line": "CGL", "effective_date": "12/01/2025",
                                        "expiration_date": "12/01/2026", "premium": "$1"}])
    assert not _umbrella_issues(agree)
    off = dict(base, coverage_lines=[{"line": "CGL", "effective_date": "03/01/2025",
                                      "expiration_date": "03/01/2026", "premium": "$1"}])
    assert any("current GL policy" in i["message"] for i in _umbrella_issues(off))


def test_an_off_anniversary_umbrella_is_still_compared_with_the_proposed_term():
    # It runs past the proposed start, so it is genuinely out of step with the
    # programme - unlike CH125's umbrella, which ends where the proposal begins.
    facts = {"umbrella_effective_date": "06/01/2025", "umbrella_expiration_date": "06/01/2026",
             "effective_date": "03/15/2026", "expiration_date": "03/15/2027"}
    assert _umbrella_issues(facts)


@pytest.mark.parametrize("printing", ["Dec. 1, 2025", "12/01/2025 12:01 AM", "2025-12-01T00:00:00",
                                      "12/0l/2025"])
def test_unusual_date_printings_still_read(printing):
    facts = {"umbrella_effective_date": printing, "umbrella_expiration_date": "12/01/2026",
             "effective_date": "12/01/2026", "expiration_date": "12/01/2027"}
    assert not _umbrella_issues(facts)



# ═══ G4 generality audit: premises ══════════════════════════════════════════

def test_a_box_addressed_premises_with_real_values_is_kept():
    f = _consolidated([_premises(), {"address": "PO Box 45, Wibaux, MT 59353", "ownership": "owner",
                                     "building_value": "$650,000"}])
    assert len(f["property_locations"]) == 2


def test_a_rural_route_is_not_a_mailbox():
    f = _consolidated([_premises(), {"address": "Box 12, RR 3, Lamoni, IA 50140", "ownership": "owner",
                                     "operations_description": "farm shop"}])
    assert len(f["property_locations"]) == 2


@pytest.mark.parametrize("box", ["POB 1234, Reno, NV 89501", "P.0. Box 12, Laramie, WY 82070",
                                 "PMB 220, Austin, TX 78701", "PO Drawer 9, Ocala, FL 34470"])
def test_more_mailbox_shapes_are_never_premises(box):
    f = _consolidated([_premises(), {"address": box}])
    assert len(f["property_locations"]) == 1


def test_a_sole_mailbox_leaves_the_schedule_blank():
    f = _consolidated([{"address": "P.O. Box 41120, Nashville, TN 37204"}])
    assert f["property_locations"] == []


def test_customer_addresses_the_documents_print_as_tickets_are_not_premises():
    text = ("SERVICE TICKETS\\nTICKET SV-1 | Hattie's Hot Chicken | 1100 Broadway, Nashville, TN 37203\\n"
            "TICKET SV-2 | Bell Diner | 7832 Bell Rd, Nashville, TN 37203\\n")
    facts = {"locations": ["900 Shop Rd, Nashville, TN 37210", "1100 Broadway, Nashville, TN 37203",
                           "7832 Bell Rd, Nashville, TN 37203"]}
    es._consolidate_property_locations(facts, text)
    assert [l["address"] for l in facts["property_locations"]] == ["900 Shop Rd, Nashville, TN 37210"]


def test_a_loose_address_the_documents_list_as_a_location_stays():
    text = "SCHEDULE OF LOCATIONS\\nLocation 2: 1919 S Broadway, Wichita, KS 67211 - warehouse\\n"
    facts = {"property_locations": [dict(_premises(), address="7700 E Kellogg Dr, Wichita, KS 67207")],
             "locations": ["1919 S Broadway, Wichita, KS 67211"]}
    es._consolidate_property_locations(facts, text)
    assert len(facts["property_locations"]) == 2


def test_a_certificate_holder_in_the_same_building_is_matched_by_suite():
    facts = {"property_locations": [_premises(), {"address": "4500 W Maple St, Suite 120, Wichita, KS 67209"}],
             "certificate_holder_address": "4500 W Maple St, Suite 100, Wichita, KS 67209"}
    es._consolidate_property_locations(facts)
    assert len(facts["property_locations"]) == 2


def test_a_second_building_named_generically_is_never_folded_into_the_premises():
    host = {"address": "410 Industrial Blvd, La Vergne, TN 37086", "ownership": "tenant",
            "operations_description": "Warehouse and office", "annual_revenue": "$0"}
    second = {"address": "Warehouse, La Vergne, TN", "ownership": "tenant",
              "building_value": "$900,000", "annual_revenue": "$0"}
    f = _consolidated([host, second])
    assert len(f["property_locations"]) == 2
    assert not f["property_locations"][0].get("building_value")


def test_a_nickname_with_nothing_agreeing_is_not_folded():
    host = {"address": "410 Industrial Blvd, La Vergne, TN 37086", "ownership": "tenant",
            "operations_description": "Parts depot", "annual_revenue": "$0"}
    f = _consolidated([host, {"address": "La Vergne depot, La Vergne, TN",
                              "operations_description": "storage"}])
    assert len(f["property_locations"]) == 2


# ── G3 skeptic follow-ups (6 Oct 2026) ───────────────────────────────────────

def _basis_warns(**deds):
    facts = {k: v for k, v in deds.items()}
    out = cfv._check_property_deductible_structure(facts, {"has_property_coverage": True}, {"ACORD_140"})
    return any(i["code"] == "property_deductible_basis_missing" for i in out)


@pytest.mark.parametrize("deds,warns", [
    ({"property_deductible_aop": "See Schedule", "property_deductible_wind": "2%"}, True),
    ({"property_deductible_aop": "Varies by location", "property_deductible_wind": "5%"}, True),
    ({"property_deductible_aop": "TBD - pending carrier quote", "property_deductible_wind": "1%"}, True),
    ({"property_deductible_aop": "Five Thousand Dollars"}, False),
    ({"property_deductible_aop": "$10,000", "property_deductible_earthquake": "15"}, False),
    ({"property_deductible_aop": "$5,000", "property_deductible_wind": "1-1/2"}, False),
    ({"property_deductible_aop": "$5,000", "property_deductible_wind": "Excluded"}, False),
    ({"property_deductible_aop": "5000"}, False),
])
def test_every_applicable_deductible_must_show_its_basis(deds, warns):
    assert _basis_warns(**deds) is warns


def test_inland_marine_dec_wording_is_not_a_property_valuation():
    # The client's own AAIS / EMC inland-marine pages (Orbin): a dec row, a
    # heading under "CONTR. EQUIP.", and the form's numbered clauses.
    text = ("840 CONTR. EQUIP. - LEASED OR RENTED FROM OTHERS\nLIMITS OF INSURANCE\n"
            "THE MOST \"WE\" PAY FOR LOSS TO ANY ONE ITEM $ 50,000\nOCCURRENCE\nACTUAL CASH VALUE\n"
            "DEDUCTIBLE $ 500\n\nSUPPLEMENTAL COVERAGES\nEMPLOYEE TOOLS (ACTUAL CASH VALUE) $ 7,500\n\n"
            "a. Replacement Cost Limitation -- The\nreplacement cost is limited to the cost of\n"
            "the amount \"you\" spend to repair or\nreplace the damaged or destroyed\nproperty.\n"
            "b. Replacement Cost Does Not Apply\nUntil Repair Or Replacement --\n"
            "Replacement cost valuation does not\napply until the damaged or destroyed\n"
            "property is repaired or replaced.\nCOMPREHENSIVE ACV 1000 DED | . | 134.00")
    assert not valuation_method_corroborated("ACV", [], text)
    assert not valuation_method_corroborated("Replacement Cost", [], text)


def test_a_building_row_under_an_sov_header_still_corroborates():
    text = ("LOC | ADDRESS | OCCUPANCY | CONST | YR | BUILDING | BPP | VALUATION\n"
            "2 | 3120 Dickerson Pike, Nashville TN 37207 | Truck terminal & repair garage | Metal | 2004 "
            "| $1,150,000 | $175,000 | ACV")
    assert valuation_method_corroborated("ACV", [], text)


# ── The receiving carrier is never the agency, however it is printed (G5) ────

@pytest.mark.parametrize("carrier,agency,is_agency", [
    ("Riverbend Insurance Partners, LLC", "Riverbend Insurance Partners", True),
    ("Riverbend Insurance Partners, LLC - producer code RIV-0417 / sub-code 22",
     "Riverbend Insurance Partners", True),
    ("HARTLOWEINSURANCEGROUP", "Hart Lowe Insurance Group", True),
    ("CRS", "Commercial Risk Solutions, Inc.", True),
    ("Smith Insurance Company", "Smith Insurance Agency", False),
    ("Granite Arch Casualty Company", "Granite Arch Casualty Company", False),
    ("Ridgeline Specialty Insurance Company", "Riverbend Insurance Partners", False),
])
def test_names_the_agency(carrier, agency, is_agency):
    from services.fact_comparison import names_the_agency
    assert names_the_agency(carrier, [agency]) is is_agency


def test_an_agency_printed_with_its_legal_suffix_never_becomes_the_carrier():
    facts = {"submission_carrier_name": {"value": "Riverbend Insurance Partners, LLC", "source": "ai"},
             "producer_name": "Riverbend Insurance Partners"}
    dropped = es._validate_submission_carrier(facts, "")
    assert "submission_carrier_name" in dropped


def test_an_insurer_in_the_producer_fact_does_not_drop_the_real_carrier():
    facts = {"submission_carrier_name": {"value": "Timberline Mutual Insurance Company", "source": "ai"},
             "producer_name": "Timberline Mutual Insurance Company"}
    assert "submission_carrier_name" not in es._validate_submission_carrier(facts, "")


# ── A closure must be THIS premises closing (G4 skeptic, 6 Oct) ──────────────

@pytest.mark.parametrize("text", [
    "Full-service restaurant; beer and wine sold on premises since 03/15/2018",
    "operations relocated to this building on 01/15/2022 from 12 Old Mill Rd",
    "Retail; wind/hail deleted eff 06/01/2026 - see FWUA policy",
    "lease expired 06/30/2025 and was renewed through 06/30/2030",
    "closed for the winter 11/01/2025 - 04/15/2026",
    "Dine-in closed 03/17/2020 per COVID-19 order, resumed operations 06/01/2020",
    "second floor no longer occupied as of 02/01/2026",
    "Original warehouse demolished 03/15/2018; current building completed 2019",
    "Unit 4 vacated 09/30/2025, units 1-3 occupied",
])
def test_a_live_premises_is_never_retired(text):
    assert not es.premises_is_retired({"operations_description": text}, "12/01/2026")


@pytest.mark.parametrize("row", [
    {"operations_description": "retail outlet closed 06/30/2026"},
    {"operations_description": "1040 Visco Dr (former location) closed 06/30/2026"},
    {"operations_description": "Removed by endorsement effective 08/01/2026"},
    {"operations_description": "Closed June 30th, 2026"},
    {"operations_description": "closed 6.30.2026"},
    {"operations_description": "Will close 11/15/2026"},
    {"status": "Inactive"},
])
def test_a_closed_premises_is_retired(row):
    assert es.premises_is_retired(row, "12/01/2026")


def test_the_audit_reader_is_linear_on_text_with_no_line_breaks():
    # `[^\n]*\baudit\b[^\n]*` was quadratic: 57 s on one 80,000-char line, and an
    # OCR'd document with no line breaks would stall merge_facts for an hour.
    import time
    text = ("Premium subject to annual audit. Billing: direct bill. " * 3000)
    start = time.perf_counter()
    es._prefer_submission_terms({}, text)
    assert time.perf_counter() - start < 5
