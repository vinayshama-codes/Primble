"""Brent's answers of 19 Oct 2026, part A - expiring policies on ACORD 125 and
ACORD 101 (25sepChanges.md part Z28).

  * ACORD 125's PRIOR CARRIER INFORMATION has ONE "Other" column: it holds "the
    primary excess / umbrella policy, unless the agent specifies otherwise";
  * every other expiring policy is listed on ACORD 101 with carrier, policy
    number, term, limit and premium - "never omitted, never forced into a wrong
    column";
  * a premium no document states is blank and flagged "Missing / Requires
    Confirmation" - never $0, never an estimate;
  * page 1's six OTHER rows are lines APPLIED FOR: an Employee Benefits
    Liability part written with the GL policy is ACORD 126's, never a row; the
    rows past six are listed on ACORD 101.

Driven through the real merge over Choice Electric's seven stored decs
(`fixtures/choice_electric_pol_6oct.json`) and through synthetic records.
"""
import copy
import json
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
os.environ.setdefault("OPENAI_API_KEY", "sk-offline-test")

import services.pdf_service as ps                         # noqa: E402
from services import needs_attention as na                # noqa: E402
from services import policy_lines as pl                   # noqa: E402

HERE = os.path.dirname(__file__)
AMER = "AMERISURE INSURANCE COMPANY"
AMER_MUTUAL = "AMERISURE MUTUAL INSURANCE COMPANY"
TRAV = "TRAVELERS PROPERTY CASUALTY COMPANY OF AMERICA"
FED = "Federal Insurance Company"


@pytest.fixture(scope="module")
def ce():
    """Choice Electric's seven decs through the real merge, as generation stamps."""
    from services.extraction_service import merge_facts, select_primary_truth
    with open(os.path.join(HERE, "fixtures", "choice_electric_pol_6oct.json"), encoding="utf-8") as fh:
        docs = json.load(fh)["docs"]
    mf, fl = merge_facts(copy.deepcopy(docs), select_primary_truth(docs))
    return {**mf, **(fl or {})}


def _rec(line, carrier, premium=None, number=None, own=True, eff="01/01/2025",
         exp="01/01/2026", printed=None, layer=None):
    r = {"id": f"{line}{'~' + layer if layer == 'excess' else ''}#{number or 'unnumbered'}",
         "line": line, "line_printed": printed or line, "policy_number": number,
         "carrier_name": carrier, "carrier_naic": None, "effective_date": eff,
         "expiration_date": exp, "granted": premium is not None,
         "printings": {"carrier_name": [carrier]}, "sources": []}
    if premium is not None:
        r["premium"] = premium
    if own:
        r["own_declarations"] = True
    if layer:
        r["layer"] = layer
    return r


def _routed(**over):
    f = {"renewal_dates_routed": True, "current_term_rows_ok": True,
         "prior_effective_date": "01/01/2025",
         "prior_expiration_date": {"value": "01/01/2026", "routed_from": "current_term"},
         "effective_date": "01/01/2026"}
    f.update(over)
    return f


def _cell(f, name):
    return ps._resolve_prior_coverage_cell(name, f)


# ══ 1. Choice Electric, end to end ══════════════════════════════════════════

class TestChoiceElectric:
    def test_the_grid_holds_gl_auto_property_and_the_umbrella(self, ce):
        assert _cell(ce, "PriorCoverage_PolicyYear_A") == "2025"
        assert _cell(ce, "PriorCoverage_GeneralLiability_TotalPremiumAmount_A") == "$ 16,818.00"
        assert _cell(ce, "PriorCoverage_Property_TotalPremiumAmount_A") == "$ 6,275.00"
        assert _cell(ce, "PriorCoverage_Automobile_InsurerFullName_A") == AMER
        assert _cell(ce, "PriorCoverage_Automobile_TotalPremiumAmount_A") is None   # redacted
        assert _cell(ce, "PriorCoverage_OtherLine_InsurerFullName_A") == AMER_MUTUAL
        assert _cell(ce, "PriorCoverage_OtherLine_TotalPremiumAmount_A") == "$ 17,082.00"
        assert _cell(ce, "PriorCoverage_OtherLine_LineOfBusinessCode_A") == "Umbrella"

    def test_acord_101_lists_every_other_expiring_policy_once(self, ce):
        rows = ps.prior_grid_set_aside_rows(ce)
        got = [(r["carrier"], r["premium"]) for r in rows]
        # the excess layer first (the umbrella family), then the largest premium,
        # a policy with no premium last
        assert got == [(TRAV, "$10,692"), (AMER, "$29,278"),
                       ("ACE American Insurance Company", "$4,162"), (AMER, "$2,431"),
                       (AMER, "$500"), (FED, None)]
        # Employee Benefits Liability ($425) is written with the GL policy by
        # Amerisure - a coverage part of it, never its own expiring policy
        # (Z42 review C; Brent, 19 Oct: EBL written with GL belongs on ACORD 126)
        assert rows[0]["limit"] == "$4,000,000 each occurrence"
        assert rows[1]["line"].startswith("Workers' Compensation and Employers' Liability")
        assert "$1,000,000 EL each accident" in rows[1]["limit"]
        assert rows[2]["limit"] == "$1,000,000"
        # the auto dec (redacted) is the umbrella schedule's auto row the grid
        # already prints - one policy, never listed twice
        assert not any("Auto" in r["line"] for r in rows)
        assert all(r["term"] == "01/01/2025 to 01/01/2026" for r in rows)

    def test_the_101_box_prints_the_list_and_names_its_form(self, ce):
        f = {**ce, "_form_id": "ACORD_101", "_package_form_ids": ["ACORD_125", "ACORD_101"]}
        text = ps._resolve_acord101_box("AdditionalRemark_RemarkText_A", f)
        assert text.startswith(ps.PRIOR_CARRIER_CONTINUED_HEADING)
        assert ("Excess (Following Form) Liability | " + TRAV + " | Policy no. not shown | "
                "01/01/2025 to 01/01/2026 | Limit $4,000,000 each occurrence | Premium $10,692") in text
        assert ("Employment Practices Liability Coverage Part | Federal Insurance Company | "
                "Policy no. not shown | 01/01/2025 to 01/01/2026 | Limit $1,000,000 aggregate | "
                "Premium Missing / Requires Confirmation") in text      # its dec's limit (27 Oct)
        assert "$0" not in text
        assert ps._resolve_acord101_box("AdditionalRemark_FormIdentifier_A", f) == "125"
        assert ps._resolve_acord101_box("AdditionalRemark_FormName_A", f) == \
            "COMMERCIAL INSURANCE APPLICATION"
        # the same text the stamper's overflow pass composes
        assert "\n\n".join(ps._compose_acord101_remarks(f)) == text

    def test_page_one_lists_the_lines_applied_for(self, ce):
        rows = ps._other_lob_rows(ce)
        assert [r["name"] for r in rows] == ["Excess (Following Form) Liability",
                                             "Employment Practices Liability"]
        assert not any("Benefit" in r["name"] for r in rows)

    def test_the_policies_table_says_where_each_policy_prints(self, ce):
        rows = {r["id"]: r for r in pl.table_rows(ce)}
        assert rows["umbrella#unnumbered"]["prior_grid"] == "OtherLine"
        assert rows["umbrella#unnumbered"]["prior_other_line"] is True
        assert rows["umbrella~excess#unnumbered"]["prior_grid"] == "ACORD_101"
        assert rows["umbrella~excess#unnumbered"]["prior_other_candidate"] is True
        assert rows["general_liab#unnumbered"]["prior_grid"] == "GeneralLiability"
        assert rows["general_liab#unnumbered"]["prior_other_candidate"] is False
        # the redacted premiums: the auto dec (printed in the Automobile column)
        # and the EPL dec (listed on ACORD 101)
        missing = sorted(k for k, r in rows.items() if r["premium_missing"])
        assert missing == ["auto#unnumbered", "epli#unnumbered"]

    def test_needs_attention_flags_each_missing_premium(self, ce):
        schema125 = json.load(open(os.path.join(HERE, "..", "forms_schemas", "ACORD_125_schema.json")))
        mapped = {"PriorCoverage_Automobile_InsurerFullName_A": AMER,
                  "PriorCoverage_PolicyYear_A": "2025",
                  "PriorCoverage_GeneralLiability_InsurerFullName_A": AMER,
                  "PriorCoverage_GeneralLiability_TotalPremiumAmount_A": "$16,818"}
        rows = na._missing_confirmation_boxes("ACORD_125", schema125, mapped, ce)
        assert [r[0] for r in rows] == ["PriorCoverage_Automobile_TotalPremiumAmount_A"]
        assert rows[0][1] == "Prior carrier premium - Automobile 2025"
        assert na.MISSING_CONFIRMATION in rows[0][2]
        schema101 = json.load(open(os.path.join(HERE, "..", "forms_schemas", "ACORD_101_schema.json")))
        box = ps._resolve_acord101_box("AdditionalRemark_RemarkText_A", {**ce, "_form_id": "ACORD_101"})
        rows = na._missing_confirmation_boxes("ACORD_101", schema101,
                                              {"AdditionalRemark_RemarkText_A": box}, ce)
        assert len(rows) == 1 and rows[0][0] == "AdditionalRemark_RemarkText_A"
        assert "Employment Practices Liability Coverage Part (Federal Insurance Company)" in rows[0][2]
        # a 101 that does not print the list (an edited box) raises nothing
        assert na._missing_confirmation_boxes("ACORD_101", schema101,
                                              {"AdditionalRemark_RemarkText_A": "remarks"}, ce) == []

    def test_the_126_flags_the_ebl_limit_the_package_does_not_print(self, ce):
        schema126 = json.load(open(os.path.join(HERE, "..", "forms_schemas", "ACORD_126_schema.json")))
        rows = na._missing_confirmation_boxes("ACORD_126", schema126, {}, ce)
        assert [r[0] for r in rows] == ["GeneralLiability_EmployeeBenefits_LimitAmount_A"]
        assert na._missing_confirmation_boxes(
            "ACORD_126", schema126, {"GeneralLiability_EmployeeBenefits_LimitAmount_A": "$1,000,000"},
            ce) == []

    def test_a_package_with_acord_125_and_no_101_is_offered_the_101(self, ce):
        from services.cross_form_validator import _check_expiring_policies_need_acord101 as rule
        issues = rule(ce, {}, {"ACORD_125", "ACORD_126"})
        assert len(issues) == 1 and issues[0]["code"] == "acord101_for_expiring_policies"
        assert issues[0]["type"] == "advisory"
        assert issues[0]["resolution"]["add_forms"] == ["ACORD_101"]
        assert "6 expiring policies" in issues[0]["message"]      # EBL is part of GL
        assert rule(ce, {}, {"ACORD_125", "ACORD_101"}) == []      # the 101 prints them
        assert rule(ce, {}, {"ACORD_126"}) == []                   # no 125, nothing to continue


# ══ 2. The OTHER column's one line ═════════════════════════════════════════

class TestTheOtherColumn:
    def test_the_umbrella_before_the_excess_before_the_largest_premium(self):
        recs = [_rec("cyber", "ACE", 40000.0), _rec("umbrella", TRAV, 900.0, layer="excess"),
                _rec("umbrella", AMER_MUTUAL, 1000.0, layer="umbrella")]
        grid, _ = ps._prior_coverage_grid(_routed(_line_records=recs))
        assert grid[("OtherLine", 0)]["carrier"] == AMER_MUTUAL
        grid, _ = ps._prior_coverage_grid(_routed(_line_records=recs[:2]))
        assert grid[("OtherLine", 0)]["carrier"] == TRAV
        assert grid.other_line == "Excess Liability"

    def test_without_an_umbrella_the_largest_premium_and_workers_comp_last(self):
        recs = [_rec("crime", AMER, 500.0), _rec("cyber", "ACE", 4162.0),
                _rec("workers_comp", AMER, 29278.0)]
        grid, _ = ps._prior_coverage_grid(_routed(_line_records=recs))
        assert grid[("OtherLine", 0)]["_family"] == "cyber"
        assert [e["_family"] for e in grid.set_aside] == ["workers_comp", "crime"]
        grid, _ = ps._prior_coverage_grid(_routed(_line_records=[recs[2]]))
        assert grid[("OtherLine", 0)]["_family"] == "workers_comp"     # the only line

    def test_the_agents_choice_wins_and_is_refound_after_a_rerun(self):
        recs = [_rec("cyber", "ACE", 4162.0), _rec("umbrella", AMER_MUTUAL, 1000.0, layer="umbrella")]
        f = _routed(_line_records=recs)
        store, audit = pl.plan_change({"facts": f}, "prior_other", edit_key="cyber#unnumbered")
        assert audit and store[pl.PRIOR_OTHER_KEY]["edit_key"] == "cyber#unnumbered"
        f[pl.STORE_KEY] = store
        grid, _ = ps._prior_coverage_grid(f)
        assert grid[("OtherLine", 0)]["_family"] == "cyber"
        assert [e["_family"] for e in grid.set_aside] == ["umbrella"]
        # a re-run renamed the record: the anchor re-finds it
        f["_line_records"] = [dict(recs[0], id="cyber#ACE-1"), recs[1]]
        assert pl.prior_other_record(f)["id"] == "cyber#ACE-1"
        grid, _ = ps._prior_coverage_grid(f)
        assert grid[("OtherLine", 0)]["_family"] == "cyber"
        # back to the rule
        store2, audit2 = pl.plan_change({"facts": f}, "prior_other", edit_key="")
        assert audit2 and pl.PRIOR_OTHER_KEY not in store2

    def test_a_choice_survives_a_later_edit_and_a_gone_policy_falls_back(self):
        recs = [_rec("cyber", "ACE", 4162.0), _rec("umbrella", AMER_MUTUAL, 1000.0, layer="umbrella")]
        f = _routed(_line_records=recs)
        store, _a = pl.plan_change({"facts": f}, "prior_other", edit_key="cyber#unnumbered")
        f[pl.STORE_KEY] = store
        after, _a = pl.plan_change({"facts": f}, "edit", edit_key="cyber#unnumbered",
                                   fields={"policy_number": "CY-778"})
        assert after[pl.PRIOR_OTHER_KEY]["edit_key"] == "cyber#unnumbered"
        assert pl.read_store({pl.STORE_KEY: after})[pl.PRIOR_OTHER_KEY]["edit_key"] == "cyber#unnumbered"
        f["_line_records"] = [recs[1]]                       # the cyber policy is gone
        grid, _ = ps._prior_coverage_grid(f)
        assert grid[("OtherLine", 0)]["_family"] == "umbrella"

    def test_a_policy_with_a_column_of_its_own_cannot_take_the_other_column(self):
        f = _routed(_line_records=[_rec("general_liab", AMER, 16818.0),
                                   _rec("cyber", "ACE", 4162.0)])
        with pytest.raises(pl.PolicyLineError):
            pl.plan_change({"facts": f}, "prior_other", edit_key="general_liab#unnumbered")
        with pytest.raises(KeyError):
            pl.plan_change({"facts": f}, "prior_other", edit_key="nope#1")

    def test_two_excess_layers_print_the_lowest(self, monkeypatch):
        recs = [_rec("umbrella", "Second Layer Co", 900.0, layer="excess", number="XS-2"),
                _rec("umbrella", "First Layer Co", 1200.0, layer="excess", number="XS-1")]
        recs[0]["id"], recs[1]["id"] = "umbrella~excess#XS-2", "umbrella~excess#XS-1"
        import services.umbrella_layers as ul
        monkeypatch.setattr(ul, "_all_slots", lambda facts: [
            {"layer": "excess", "records": [recs[1]], "record": recs[1]},
            {"layer": "excess", "records": [recs[0]], "record": recs[0]}])
        grid, _ = ps._prior_coverage_grid(_routed(_line_records=recs))
        assert grid[("OtherLine", 0)]["carrier"] == "First Layer Co"
        assert [e["carrier"] for e in grid.set_aside] == ["Second Layer Co"]

    def test_two_policies_in_a_named_column_are_both_listed(self):
        recs = [_rec("general_liab", AMER, 16818.0, number="GL-1"),
                _rec("general_liab", "Second Carrier Co", 5000.0, number="GL-2")]
        f = _routed(_line_records=recs)
        grid, _ = ps._prior_coverage_grid(f)
        assert ("GeneralLiability", 0) not in grid           # one box cannot name both
        assert sorted(e["carrier"] for e in grid.set_aside) == [AMER, "Second Carrier Co"]

    def test_history_older_than_the_grid_is_not_listed(self):
        hist = [{"line": "Inland Marine", "carrier": "Old IM Co", "premium": "$700",
                 "effective": f"01/01/{y}", "expiration": f"01/01/{y + 1}"} for y in (2019, 2024)]
        hist += [{"line": "General Liability", "carrier": "Old Co", "premium": "$1,000",
                  "effective": f"01/01/{y}", "expiration": f"01/01/{y + 1}"} for y in (2022, 2023)]
        hist += [{"line": "Commercial Umbrella", "carrier": "Umb Co", "premium": "$900",
                  "effective": "01/01/2024", "expiration": "01/01/2025"}]
        grid, years = ps._prior_coverage_grid(_routed(prior_coverage_by_line=hist,
                                                      effective_date="01/01/2025"))
        assert grid[("OtherLine", 0)]["carrier"] == "Umb Co"
        assert [e["effective"] for e in grid.set_aside] == ["01/01/2024"]  # 2019 is not listed

    def test_undated_entries_keep_one_line_in_the_other_column(self):
        hist = [{"line": "Inland Marine", "carrier": "IM Co", "premium": "$700"},
                {"line": "Commercial Umbrella", "carrier": "Umb Co", "premium": "$900"},
                {"line": "General Liability", "carrier": "GL Co", "premium": "$1,000"}]
        grid, years = ps._prior_coverage_grid(_routed(prior_coverage_by_line=hist,
                                                      effective_date="01/01/2025"))
        assert years == []
        assert grid[("OtherLine", 0)]["carrier"] == "Umb Co" and ("OtherLine", 1) not in grid
        assert [e["carrier"] for e in grid.set_aside] == ["IM Co"]

    def test_nothing_set_aside_without_current_policies_or_history(self):
        grid, years = ps._prior_coverage_grid({})
        assert grid == {} and years == []
        assert ps.prior_grid_set_aside_rows({}) == []
        assert ps.prior_grid_placements({}) == {}


# ══ 3. Page 1: lines applied for ═══════════════════════════════════════════

class TestPageOneLines:
    def test_ebl_from_its_own_company_keeps_its_row(self):
        lines = [{"line": "Commercial General Liability", "carrier": AMER, "premium": "$16,818"},
                 {"line": "Employee Benefit Liability", "carrier": "Benefit Specialty Co",
                  "premium": "$900"}]
        names = [r["name"] for r in ps._other_lob_rows({"coverage_lines": lines})]
        assert names == ["Employee Benefit Liability"]

    def test_ebl_written_with_the_gl_policy_takes_no_row(self):
        lines = [{"line": "Commercial General Liability", "carrier": AMER, "premium": "$16,818"},
                 {"line": "Employee Benefit Liability", "carrier": AMER, "premium": "$425"}]
        assert ps._other_lob_rows({"coverage_lines": lines}) == []

    def test_ebl_with_no_gl_at_all_keeps_its_row(self):
        lines = [{"line": "Employee Benefit Liability", "carrier": AMER, "premium": "$425"}]
        assert [r["name"] for r in ps._other_lob_rows({"coverage_lines": lines})] == \
            ["Employee Benefit Liability"]

    @pytest.mark.parametrize("raw,clean", [
        ("Employment Practices Liability Coverage Part", "Employment Practices Liability"),
        ("Pollution Liability Coverage Form", "Pollution Liability"),
        ("Directors and Officers Liability Policy", "Directors and Officers Liability"),
        ("Excess (Following Form) Liability", "Excess (Following Form) Liability"),
        ("Liability Coverage Part", "Liability Coverage Part"),     # nothing of its own left
        ("Coverage Part", "Coverage Part"),
        ("", ""),
    ])
    def test_a_row_prints_the_line_not_the_section(self, raw, clean):
        assert ps._clean_other_line_name(raw) == clean

    def test_rows_order_by_premium_with_the_unpriced_last(self):
        lines = [{"line": "Aviation Liability", "carrier": "A Co", "premium": "$1,200"},
                 {"line": "Employment Practices Liability", "carrier": "B Co", "premium": "$5,000"},
                 {"line": "Kidnap and Ransom Liability", "carrier": "C Co", "premium": "$3,000"}]
        names = [r["name"] for r in ps._other_lob_rows({"coverage_lines": lines})]
        assert names == ["Employment Practices Liability", "Kidnap and Ransom Liability",
                         "Aviation Liability"]


# ══ 4. ACORD 101's own boxes ════════════════════════════════════════════════

class TestAcord101Boxes:
    def test_outside_the_101_the_boxes_are_not_claimed(self):
        f = {"additional_remarks_text": "Note", "_form_id": "ACORD_125"}
        for box in ("AdditionalRemark_RemarkText_A", "AdditionalRemark_FormIdentifier_A"):
            assert ps._resolve_acord101_box(box, f) is ps._SCHED_SKIP
        assert ps._resolve_acord101_box("CommercialPolicy_RemarkText_A",
                                        {"_form_id": "ACORD_101"}) is ps._SCHED_SKIP

    def test_nothing_composed_steps_aside_and_the_form_boxes_stay_blank(self):
        f = {"_form_id": "ACORD_101"}
        assert ps._resolve_acord101_box("AdditionalRemark_RemarkText_A", f) is ps._SCHED_SKIP
        assert ps._resolve_acord101_box("AdditionalRemark_FormIdentifier_A", f) is None
        assert ps._resolve_acord101_box("AdditionalRemark_FormName_A", f) is None
        assert ps._is_authoritative_blank_field("AdditionalRemark_FormIdentifier_A", f)
        assert not ps._is_authoritative_blank_field("AdditionalRemark_RemarkText_A", f)

    def test_remarks_alone_name_the_application(self):
        f = {"_form_id": "ACORD_101", "additional_remarks_text": "Seasonal lease at location 5."}
        assert ps._resolve_acord101_box("AdditionalRemark_RemarkText_A", f) == \
            "Seasonal lease at location 5."
        assert ps._resolve_acord101_box("AdditionalRemark_FormIdentifier_A", f) == "125"

    def test_a_package_without_acord_125_does_not_continue_it(self, ce):
        f = {**ce, "_form_id": "ACORD_101", "_package_form_ids": ["ACORD_101", "ACORD_126"]}
        assert ps._resolve_acord101_box("AdditionalRemark_RemarkText_A", f) is ps._SCHED_SKIP
        assert ps._resolve_acord101_box("AdditionalRemark_FormIdentifier_A", f) is None
        # ACORD 130 alone: its endorsement schedule, never the 125's list
        f["_package_form_ids"] = ["ACORD_101", "ACORD_130"]
        text = ps._resolve_acord101_box("AdditionalRemark_RemarkText_A", f)
        assert ps.PRIOR_CARRIER_CONTINUED_HEADING not in text and "ENDORSEMENT SCHEDULE" in text
        assert ps._resolve_acord101_box("AdditionalRemark_FormIdentifier_A", f) == "130"
        f["_package_form_ids"] = ["ACORD_125", "ACORD_101"]
        assert ps._resolve_acord101_box("AdditionalRemark_FormIdentifier_A", f) == "125"


# ══ 5. After forms: a change re-stamps the list ═════════════════════════════

def test_choosing_another_policy_restamps_the_125_and_the_101(ce):
    from services.arq_service import _restamp_changed_boxes
    schema101 = json.load(open(os.path.join(HERE, "..", "forms_schemas", "ACORD_101_schema.json")))
    schema125 = json.load(open(os.path.join(HERE, "..", "forms_schemas", "ACORD_125_schema.json")))
    before = copy.deepcopy(ce)
    # As generation stamps it: with the package (`process_single_form`).
    view_b = {**before, "_form_id": "ACORD_101", "_package_form_ids": ["ACORD_101", "ACORD_125"]}
    old_text = ps._resolve_acord101_box("AdditionalRemark_RemarkText_A", view_b)
    old_other = _cell({**before, "_form_id": "ACORD_125"}, "PriorCoverage_OtherLine_InsurerFullName_A")
    generated = {
        "ACORD_101": {"schema": schema101, "field_state": {"AdditionalRemark_RemarkText_A": old_text},
                      "confidence": {"AdditionalRemark_RemarkText_A": "filled"}},
        "ACORD_125": {"schema": schema125,
                      "field_state": {"PriorCoverage_OtherLine_InsurerFullName_A": old_other},
                      "confidence": {"PriorCoverage_OtherLine_InsurerFullName_A": "filled"}},
    }
    store, _a = pl.plan_change({"facts": before}, "prior_other", edit_key="cyber#unnumbered")
    after = copy.deepcopy(before)
    after[pl.STORE_KEY] = store
    touched = _restamp_changed_boxes(generated, before, after, own_keys=set())
    assert sorted(touched) == ["ACORD_101", "ACORD_125"]
    assert generated["ACORD_125"]["field_state"]["PriorCoverage_OtherLine_InsurerFullName_A"] \
        == "ACE American Insurance Company"
    new_text = generated["ACORD_101"]["field_state"]["AdditionalRemark_RemarkText_A"]
    assert "Commercial Liability Umbrella" in new_text or AMER_MUTUAL in new_text
    assert "ACE American Insurance Company" not in new_text


# ══ The review of 19 Oct evening: a corpus replay of the grid (927 stored
# packages, old tree vs new) found these - each pinned on a synthetic history.

def _grid(entries):
    return ps._prior_coverage_grid_build({"prior_coverage_by_line": entries})


def _rows(grid):
    return {k: (e.get("line"), e.get("policy_no"), e.get("premium")) for k, e in sorted(grid.items())}


def test_a_line_with_its_own_column_is_never_the_other_columns_line():
    """"GL" is general liability even where the column matcher cannot place the
    abbreviation: it was printed under the OTHER column's one line-name box."""
    grid, _years = _grid([
        {"line": "General Liability", "carrier": "Hickory", "policy_no": "GL-1-24", "premium": "$38,420"},
        {"line": "GL", "carrier": "Hickory", "policy_no": "GL-1-23", "premium": "$33,005",
         "effective": "12/01/2023"},
        {"line": "Inland Marine", "carrier": "Ridgeline", "policy_no": "IM-1", "premium": "$2,140"},
    ])
    assert grid.other_line == "Inland Marine"
    assert [e.get("policy_no") for e in grid.set_aside] == ["GL-1-23"]       # listed on ACORD 101
    assert all(e.get("policy_no") != "GL-1-23" for e in grid.values())


def test_with_no_years_one_policy_takes_one_row_and_its_fuller_printing():
    """Undated histories filled two or three rows of a column with ONE policy;
    the first printing won even when a later one carried the premium and term."""
    grid, years = _grid([
        {"line": "Commercial General Liability", "carrier": "Northstar", "policy_no": "WGM-1-25"},
        {"line": "General Liability", "carrier": "Westgate", "policy_no": "WGM-1-25",
         "premium": "$26,900", "effective": "06/01/2025"},
        {"line": "Commercial Auto", "carrier": "Westgate", "policy_no": "AU-9", "premium": "$5,000",
         "effective": "06/01/2025"},
        {"line": "Commercial Auto", "carrier": "Westgate", "policy_no": "AU-9", "premium": "$4,800",
         "effective": "06/01/2024"},                       # a number kept across renewals: two terms
    ])
    # 30 Oct 2026 (live 8aa8f3ad): an undated printing no longer unkeys the
    # grid - the dated policies keep their year rows, the undated repeat of
    # WGM-1-25 is the same policy and is not listed again.
    assert years == ["2025", "2024"]
    assert all(e.get("policy_no") != "WGM-1-25" for e in grid.set_aside)
    rows = _rows(grid)
    gl = [v for k, v in rows.items() if k[0] == "GeneralLiability"]
    assert gl == [("General Liability", "WGM-1-25", "$26,900")]
    assert [v[2] for k, v in rows.items() if k[0] == "Automobile"] == ["$5,000", "$4,800"]


def test_one_policy_printed_under_two_names_is_listed_once():
    """An AMS history ("AUTOB", "WORK") beside the decs' own names: the same
    number and premium is one policy - never relisted on ACORD 101, and never
    the OTHER column's line when its twin sits in a named column."""
    grid, _years = _grid([
        {"line": "Commercial Auto", "carrier": "Hickory", "policy_no": "CA-25", "premium": "$61,775"},
        {"line": "AUTOB", "carrier": "Hickory", "policy_no": "CA-25", "premium": "61775"},
        {"line": "WORK", "carrier": "TEM", "policy_no": "WC-1", "premium": "44810"},
        {"line": "Workers Compensation", "carrier": "TEM", "policy_no": "WC-1", "premium": "$44,810"},
        {"line": "Umbrella", "carrier": "Cardinal", "policy_no": "UMB-1", "premium": "$9,880"},
        {"line": "UMBRC", "carrier": "Cardinal", "policy_no": "UMB-1", "premium": "9880"},
    ])
    assert grid.other_line == "Umbrella"
    listed = [(e.get("line"), e.get("policy_no")) for e in grid.set_aside]
    assert [n for _l, n in listed] == ["WC-1"]                               # once, by either name
    assert all(e.get("policy_no") != "CA-25" for e in grid.set_aside)


def test_package_parts_sharing_a_number_stay_apart():
    """A package number printed for several parts is NOT one printing - each
    part carries its own premium and is listed."""
    grid, _years = _grid([
        {"line": "General Liability", "carrier": "Granite", "policy_no": "CPP-1", "premium": "$38,640"},
        {"line": "Commercial Property", "carrier": "Granite", "policy_no": "CPP-1", "premium": "$14,980"},
        {"line": "Inland Marine", "carrier": "Granite", "policy_no": "CPP-1", "premium": "$2,431"},
        {"line": "Crime", "carrier": "Granite", "policy_no": "CPP-1", "premium": "$500"},
    ])
    placed = {e.get("premium") for e in grid.values()} | {e.get("premium") for e in grid.set_aside}
    assert placed == {"$38,640", "$14,980", "$2,431", "$500"}


@pytest.mark.parametrize("package,has_125,has_130", [
    (["ACORD_25", "ACORD_101"], False, False),
    (["ACORD_125", "ACORD_101"], True, False),
    (["ACORD_125", "ACORD_130", "ACORD_101"], True, True),
])
def test_a_restamp_after_an_answer_keeps_acord_101_to_the_package(ce, package, has_125, has_130):
    """An answer after forms re-stamps every box it decides with the session's
    raw facts. ACORD 101 continues only the forms IN the package; with no
    package in its view, a 25 + 101 package gained the 125 prior-carrier list
    and the 130 endorsement schedule. The re-stamp doors now hand every view
    the package generation saw (the generated forms)."""
    from services.arq_service import _restamp_boxes_the_answer_decides
    schema = json.load(open(os.path.join(HERE, "..", "forms_schemas", "ACORD_101_schema.json")))
    gen_view = {**ce, "_form_id": "ACORD_101", "_package_form_ids": package}
    mapped, conf = ps.map_facts_to_form(gen_view, schema, form_id="ACORD_101", raw_text="",
                                        allow_llm=False)
    state = {k: ("" if v in (None, "None", "UNMATCHED") else v) for k, v in mapped.items()}
    generated = {**{f: {"schema": {}} for f in package if f != "ACORD_101"},
                 "ACORD_101": {"schema": schema, "field_state": dict(state), "confidence": dict(conf)}}
    before, after = dict(ce), dict(ce, additional_remarks_text="Insured requests the renewal by 12/01.")
    _restamp_boxes_the_answer_decides(generated, before, after, {"additional_remarks_text"},
                                      after["additional_remarks_text"], "producer")
    text = str(generated["ACORD_101"]["field_state"].get("AdditionalRemark_RemarkText_A") or "")
    # A short remark prints in ACORD 125's REMARKS box; the 101 repeats it only
    # when the package holds no 125 (Z42 review C: never printed twice).
    assert ("Insured requests the renewal by 12/01." in text) is (not has_125)
    assert (ps.PRIOR_CARRIER_CONTINUED_HEADING in text) is has_125
    assert ("continued from ACORD 130" in text) is has_130


def _ce_records(ce):
    return {r["id"]: r for r in ce["_line_records"]}


def _table(f):
    return {r["id"]: r for r in pl.table_rows(f) if r["id"].startswith("umbrella")}


def test_an_upper_excess_layer_is_listed_and_tagged_where_it_prints(ce, monkeypatch):
    """Two unnumbered excess layers of ONE carrier: the second was dropped as a
    "repeat" of the first (printed nowhere), and the policies table tagged both
    "ACORD 125 Other column". Two records are two policies; the tag says where
    each one PRINTS, and the upper layer can be chosen for the column."""
    import services.umbrella_layers as ul
    recs = _ce_records(ce)
    x1 = copy.deepcopy(recs["umbrella~excess#unnumbered"])
    x1.update(id="umbrella~excess#layer1", policy_number=None, carrier_name="Same Excess Co",
              premium=10692.0, printings={"carrier_name": ["Same Excess Co"]})
    x2 = copy.deepcopy(recs["umbrella~excess#unnumbered"])
    x2.update(id="umbrella~excess#layer2", policy_number=None, carrier_name="Same Excess Co",
              premium=4000.0, printings={"carrier_name": ["Same Excess Co"]})
    f = copy.deepcopy(ce)
    f["_line_records"] = [copy.deepcopy(recs["general_liab#unnumbered"]), x2, x1]
    monkeypatch.setattr(ul, "_all_slots", lambda facts: [
        {"layer": "excess", "records": [x1], "record": x1},
        {"layer": "excess", "records": [x2], "record": x2}])
    grid, _years = ps._prior_coverage_grid(f)
    assert grid[("OtherLine", 0)].get("_record_id") == "umbrella~excess#layer1"     # the lowest layer
    assert [r["premium"] for r in ps.prior_grid_set_aside_rows(f)] == ["$4,000"]
    rows = _table(f)
    assert rows["umbrella~excess#layer1"]["prior_other_line"] is True
    assert rows["umbrella~excess#layer2"]["prior_grid"] == "ACORD_101"
    assert rows["umbrella~excess#layer2"]["prior_other_line"] is False
    assert rows["umbrella~excess#layer2"]["prior_other_candidate"] is True


def test_the_agents_pick_decides_between_two_primary_umbrellas(ce):
    """Two primary umbrellas of two carriers on one line leave the OTHER box
    blank (the picker's question) - and the agent's pick never filled it."""
    recs = _ce_records(ce)
    u2 = copy.deepcopy(recs["umbrella#unnumbered"])
    u2.update(id="umbrella#U-2", carrier_name="Second Umbrella Co", policy_number="U-2", premium=5000.0,
              printings={"carrier_name": ["Second Umbrella Co"], "policy_number": ["U-2"]})
    f = copy.deepcopy(ce)
    f["_line_records"] = [copy.deepcopy(recs["general_liab#unnumbered"]),
                          copy.deepcopy(recs["umbrella#unnumbered"]), u2]
    grid, _years = ps._prior_coverage_grid(f)
    assert grid.get(("OtherLine", 0)) is None
    assert len(ps.prior_grid_set_aside_rows(f)) == 2
    assert all(r["prior_other_candidate"] for r in _table(f).values())
    store, audit = pl.plan_change({"facts": f}, "prior_other", edit_key="umbrella#U-2")
    assert len(audit) == 1
    f[pl.STORE_KEY] = store
    grid, _years = ps._prior_coverage_grid(f)
    assert grid[("OtherLine", 0)].get("carrier") == "Second Umbrella Co"
    assert [r["carrier"] for r in ps.prior_grid_set_aside_rows(f)] == [AMER_MUTUAL]
    assert _table(f)["umbrella#U-2"]["prior_other_line"] is True


def test_a_picked_line_prints_its_name_not_its_key(ce):
    """The agent picks the EPL policy for the OTHER column: the line box printed
    "Epli" (the family key title-cased). It prints the name the policies table
    and ACORD 101 use."""
    f = copy.deepcopy(ce)
    store, _a = pl.plan_change({"facts": f}, "prior_other", edit_key="epli#unnumbered")
    f[pl.STORE_KEY] = store
    grid, _years = ps._prior_coverage_grid(f)
    assert grid.other_line == "Employment Practices Liability"
    assert _cell({**f, "_form_id": "ACORD_125"}, "PriorCoverage_OtherLine_InsurerFullName_A") == FED
