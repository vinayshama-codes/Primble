"""Brent, 14 Oct 2026, answer 1C: "Yes, we should still list the policy" when
its premium is redacted or blank and its carrier and dates are still known.

Choice Electric's redacted package (stored runs 9744ff72 / 823d58a0 / f83757cf /
ba7c709d) carries a Federal EPL policy whose own declarations print no premium
and no number. The review's policies table listed it; ACORD 125 page one did
not, because every OTHER row needed a premium. The fixtures below are those
runs' own per-policy records and coverage rows.

A policy listed this way ADDS - it never takes a box, a row or a year from a
policy listed today. Which policy takes a scarce shared slot (the prior-carrier
OTHER column, more lines than OTHER rows) is still open (Michelle), so where
that question applies nothing changes.
"""
import copy

import services.pdf_service as ps


def _rec(line, carrier, premium=None, number=None, own=True, eff="01/01/2025",
         exp="01/01/2026", printed=None, layer=None, granted=None):
    r = {"id": f"{line}#{number or 'unnumbered'}", "line": line, "line_printed": printed or line,
         "policy_number": number, "carrier_name": carrier, "carrier_naic": None,
         "effective_date": eff, "expiration_date": exp,
         "granted": bool(premium) if granted is None else granted,
         "printings": {"carrier_name": [carrier]}, "sources": []}
    if premium is not None:
        r["premium"] = premium
    if own:
        r["own_declarations"] = True
    if layer:
        r["layer"] = layer
    return r


AMER = "AMERISURE INSURANCE COMPANY"
FED = "Federal Insurance Company"

# The stored run 9744ff72's records (re-merged from its per-document facts).
_CE_RECORDS = [
    _rec("auto", AMER, printed="Auto Liability"),
    _rec("crime", AMER, 500.0, own=False, printed="Crime and Fidelity"),
    _rec("cyber", "ACE American Insurance Company", 4162.0, eff="01-01-2025", exp="01-01-2026",
         printed="Cyber"),
    _rec("employee_benefits", AMER, 425.0, own=False, printed="Employee Benefit Liability"),
    _rec("epli", FED, eff="January 1, 2025", exp="January 1, 2026",
         printed="Employment Practices Liability Coverage Part"),
    _rec("general_liab", AMER, 16818.0, own=False, printed="Commercial General Liability"),
    _rec("inland_marine", AMER, 2431.0, own=False, printed="Commercial Inland Marine"),
    _rec("property", AMER, 6275.0, own=False, printed="Commercial Property"),
    _rec("umbrella", "AMERISURE MUTUAL INSURANCE COMPANY", 17082.0, layer="umbrella",
         printed="Commercial Liability Umbrella"),
    _rec("umbrella", "TRAVELERS PROPERTY CASUALTY COMPANY OF AMERICA", 10692.0, layer="excess",
         printed="Excess (Following Form) Liability"),
    _rec("workers_comp", AMER, 29278.0, printed="Workers' Compensation and Employers' Liability"),
]

_CE_LINES = [
    {"line": "Auto Liability", "carrier": AMER, "premium": None, "policy_number": None,
     "effective_date": "01/01/2025", "expiration_date": "01/01/2026"},
    {"line": "Cyber", "carrier": "ACE American Insurance Company", "premium": "$4,162.00",
     "policy_number": None, "effective_date": "01-01-2025", "expiration_date": "01-01-2026"},
    {"line": "Employment Practices Liability Coverage Part", "carrier": FED, "premium": None,
     "policy_number": None, "effective_date": "January 1, 2025", "expiration_date": "January 1, 2026"},
    {"line": "Excess (Following Form) Liability", "carrier": "TRAVELERS PROPERTY CASUALTY COMPANY OF AMERICA",
     "premium": "$ 10,692", "policy_number": None, "effective_date": "01/01/2025",
     "expiration_date": "01/01/2026"},
    {"line": "Commercial General Liability", "carrier": AMER, "premium": "$ 16,818.00",
     "policy_number": None, "effective_date": "01/01/2025", "expiration_date": "01/01/2026"},
    {"line": "Commercial Inland Marine", "carrier": AMER, "premium": "$ 2,431.00",
     "policy_number": None, "effective_date": "01/01/2025", "expiration_date": "01/01/2026"},
    {"line": "Commercial Property", "carrier": AMER, "premium": "$ 6,275.00",
     "policy_number": None, "effective_date": "01/01/2025", "expiration_date": "01/01/2026"},
    {"line": "Crime and Fidelity", "carrier": AMER, "premium": "$ 500.00",
     "policy_number": None, "effective_date": "01/01/2025", "expiration_date": "01/01/2026"},
    {"line": "Employee Benefit Liability", "carrier": AMER, "premium": "$ 425.00",
     "policy_number": None, "effective_date": "01/01/2025", "expiration_date": "01/01/2026"},
    {"line": "Commercial Liability Umbrella", "carrier": "AMERISURE MUTUAL INSURANCE COMPANY",
     "premium": "$17,082.00", "policy_number": None, "effective_date": "01/01/2025",
     "expiration_date": "01/01/2026"},
    {"line": "Workers' Compensation and Employers' Liability", "carrier": AMER,
     "premium": "29,278.00", "policy_number": None, "effective_date": "01/01/2025",
     "expiration_date": "01/01/2026"},
    # coverage PARTS of the auto policy: its carrier and term, no premium
    {"line": "Uninsured Motorists", "carrier": AMER, "premium": None, "policy_number": None,
     "effective_date": "01/01/2025", "expiration_date": "01/01/2026"},
    {"line": "Physical Damage Coverage", "carrier": AMER, "premium": None, "policy_number": None,
     "effective_date": "01/01/2025", "expiration_date": "01/01/2026"},
]


def _ce(**over):
    f = {"coverage_lines": copy.deepcopy(_CE_LINES), "_line_records": copy.deepcopy(_CE_RECORDS),
         "_form_id": "ACORD_125"}
    f.update(over)
    return f


# ══ 1. The rule's own condition ═════════════════════════════════════════════

class TestListable:
    def test_the_redacted_dec_is_listable(self):
        epl = next(r for r in _CE_RECORDS if r["line"] == "epli")
        assert ps._redacted_policy_is_listable(epl, {})

    def test_brents_condition_carrier_and_both_own_dates(self):
        epl = next(r for r in _CE_RECORDS if r["line"] == "epli")
        assert not ps._redacted_policy_is_listable(dict(epl, carrier_name=""), {})
        assert not ps._redacted_policy_is_listable(dict(epl, effective_date=None), {})
        assert not ps._redacted_policy_is_listable(dict(epl, expiration_date="SEE SCHEDULE"), {})
        # an inverted term is not a term
        assert not ps._redacted_policy_is_listable(
            dict(epl, effective_date="01/01/2026", expiration_date="01/01/2025"), {})

    def test_something_must_make_it_a_policy_of_its_own(self):
        bare = _rec("epli", FED, own=False)
        assert not ps._redacted_policy_is_listable(bare, {})        # a menu / header row
        assert ps._redacted_policy_is_listable(dict(bare, producer_added="x1"), {})
        assert ps._redacted_policy_is_listable(dict(bare, policy_number="EPL-778812"), {})
        # a form number or a digit-free label is never the number
        assert not ps._redacted_policy_is_listable(dict(bare, policy_number="CG 00 01 04 13"), {})
        assert not ps._redacted_policy_is_listable(dict(bare, policy_number="COMMERCIAL AUTO"), {})


# ══ 2. ACORD 125 page one - the OTHER line-of-business rows ═════════════════

class TestPageOneOtherRows:
    def test_the_epl_policy_takes_the_next_other_row_with_no_premium(self):
        """19 Oct 2026 (Brent): page 1's OTHER rows are lines APPLIED FOR. The
        package's Employee Benefit Liability is a coverage part written with its
        GL policy (same company) - ACORD 126's, never a row here; the EPL row
        prints its LINE ("Coverage Part" dropped); a priced row comes first."""
        rows = ps._other_lob_rows(_ce())
        assert [r["name"] for r in rows] == [
            "Excess (Following Form) Liability", "Employment Practices Liability"]
        assert rows[1]["premium"] is None
        with ps._schema_context(_schema125()):
            assert ps._resolve_other_lob_row("Policy_LineOfBusiness_OtherIndicator_B", _ce()) == "Yes"
            assert ps._resolve_other_lob_row(
                "Policy_LineOfBusiness_OtherLineOfBusinessDescription_B", _ce()) == \
                "Employment Practices Liability"
            # the premium box stays blank - never "$0", never "redacted"
            assert ps._resolve_other_lob_premium("Policy_SectionAttached_OtherPremiumAmount_B", _ce()) is None
            assert ps._resolve_other_lob_row("Policy_LineOfBusiness_OtherIndicator_C", _ce()) is None
            # the priced row keeps its premium
            assert ps._resolve_other_lob_premium("Policy_SectionAttached_OtherPremiumAmount_A", _ce()) == "$ 10,692"

    def test_a_standard_family_or_a_coverage_part_never_becomes_a_row(self):
        names = [r["name"] for r in ps._other_lob_rows(_ce())]
        assert not any("Auto" in n or "Uninsured" in n or "Physical" in n for n in names)

    def test_never_where_a_priced_policy_of_its_line_would_not_be(self):
        """Stored runs 4e23e04b / e4f9f797: a numbered workers comp policy with
        no premium. A PRICED workers comp line is not a 125 OTHER row (its name
        is coverage-part vocabulary), so the unpriced one is not either."""
        recs = _CE_RECORDS + [_rec("workers_comp", "Kestrel Mutual Insurance Company", number="WC-877541-26",
                                   own=False, printed="Workers Compensation And Employers Liability")]
        recs = [r for r in recs if not (r["line"] == "workers_comp" and r.get("premium"))]
        names = [r["name"] for r in ps._other_lob_rows(_ce(_line_records=recs))]
        assert not any("Workers" in n for n in names)
        assert "Employment Practices Liability" in names

    def test_a_record_riding_a_standard_lines_number_adds_nothing(self):
        lines = copy.deepcopy(_CE_LINES)
        for e in lines:
            if e["line"] == "Commercial General Liability":
                e["policy_number"] = "CPP-7781203"
        recs = [dict(r, own_declarations=False, policy_number="CPP-7781203") if r["line"] == "epli" else r
                for r in _CE_RECORDS]
        names = [r["name"] for r in ps._other_lob_rows(_ce(coverage_lines=lines, _line_records=recs))]
        assert not any(n.startswith("Employment Practices") for n in names)

    def test_a_record_without_its_own_declarations_adds_nothing(self):
        recs = [dict(r, own_declarations=False) if r["line"] == "epli" else r for r in _CE_RECORDS]
        names = [r["name"] for r in ps._other_lob_rows(_ce(_line_records=recs))]
        assert not any(n.startswith("Employment Practices") for n in names)

    def test_more_lines_than_rows_print_the_largest_and_list_the_rest(self, monkeypatch):
        """Brent, 19 Oct 2026, settled the slot question: the largest premium
        first, a row with no premium last; the rows past the form's own are
        listed on ACORD 101 (`other_lob_overflow`), never dropped."""
        monkeypatch.setattr(ps, "_other_lob_premium_boxes",
                            lambda schema: {"Policy_SectionAttached_OtherPremiumAmount_A": "A"})
        names = [r["name"] for r in ps._other_lob_rows(_ce())]
        assert names == ["Excess (Following Form) Liability", "Employment Practices Liability"]
        assert [r["name"] for r in ps.other_lob_overflow(_ce())] == ["Employment Practices Liability"]
        block = ps._other_lines_continuation(_ce())
        assert block.startswith("OTHER LINES OF BUSINESS (continued from ACORD 125 page 1):")
        assert "Employment Practices Liability" in block

    def test_a_priced_row_of_the_same_line_is_that_policy(self):
        lines = copy.deepcopy(_CE_LINES)
        for e in lines:
            if e["line"].startswith("Employment Practices"):
                e["premium"] = "$ 3,100.00"
        rows = ps._other_lob_rows(_ce(coverage_lines=lines))
        epl = [r for r in rows if r["name"].startswith("Employment Practices")]
        assert len(epl) == 1 and epl[0]["premium"] == "$ 3,100.00" and not epl[0].get("_unpriced")

    def test_no_records_no_change(self):
        f = _ce()
        f.pop("_line_records")
        assert [r["name"] for r in ps._other_lob_rows(f)] == ["Excess (Following Form) Liability"]

    def test_the_policy_premium_total_is_the_visible_premiums(self):
        """A listed policy's redacted premium leaves the total PARTIAL, and
        partial is acceptable (Brent, 23 Oct 2026, Z34-1 #5 - reverses this
        test's 14 Oct blank): the visible premiums' sum, with a needs-attention
        note (tests/test_build25_forms.py)."""
        without = _ce()
        without.pop("_line_records")
        printed = ps._printed_lob_premiums(without)
        assert ps._printed_sum(without, printed)
        partial = ps._printed_lob_premiums(_ce())
        assert ps._printed_sum(_ce(), partial) == sum(partial)

    def test_a_stated_one_policy_total_never_stands_in(self):
        """The excess dec's own $10,692 total beside five carriers' rows is
        replaced by the rows' sum - with a listed policy's premium redacted that
        sum is partial, and printed (Brent, 23 Oct 2026); never the one
        policy's total."""
        without = _ce(total_policy_premium="$10,692")
        without.pop("_line_records")
        assert str(ps._resolve_estimated_total("Policy_Payment_EstimatedTotalAmount_A", without)).startswith("$")
        partial = sum(ps._printed_lob_premiums(_ce()))
        assert ps._resolve_estimated_total("Policy_Payment_EstimatedTotalAmount_A",
                                           _ce(total_policy_premium="$10,692")) == f"${partial:,}"


def _schema125():
    import json
    import os
    with open(os.path.join(os.path.dirname(__file__), "..", "forms_schemas",
                           "ACORD_125_schema.json")) as fh:
        return json.load(fh)


# ══ 3. ACORD 125 PRIOR CARRIER INFORMATION ══════════════════════════════════

def _routed(**over):
    f = {"renewal_dates_routed": True, "current_term_rows_ok": True,
         "prior_effective_date": "01/01/2025",
         "prior_expiration_date": {"value": "01/01/2026", "routed_from": "current_term"},
         "effective_date": "01/01/2026"}
    f.update(over)
    return f


class TestPriorCarrierGrid:
    def test_the_redacted_policy_is_a_row_with_a_blank_premium(self):
        f = _routed(_line_records=[_rec("epli", FED, eff="January 1, 2025", exp="January 1, 2026",
                                        printed="Employment Practices Liability Coverage Part")])
        rows = ps._current_policy_grid_rows(f, (None, None))
        assert len(rows) == 1 and rows[0]["_unpriced"]
        assert rows[0]["carrier"] == FED and rows[0]["premium"] is None and rows[0]["policy_no"] is None
        assert (rows[0]["effective"], rows[0]["expiration"]) == ("01/01/2025", "01/01/2026")
        grid, years = ps._prior_coverage_grid(f)
        assert years == ["2025"]
        cell = grid[("OtherLine", 0)]
        assert cell["carrier"] == FED and cell["premium"] is None
        assert ps._resolve_prior_coverage_cell("PriorCoverage_OtherLine_InsurerFullName_A", f) == FED
        assert ps._resolve_prior_coverage_cell("PriorCoverage_OtherLine_TotalPremiumAmount_A", f) is None
        assert ps._resolve_prior_coverage_cell("PriorCoverage_OtherLine_EffectiveDate_A", f) == "01/01/2025"

    def test_the_other_column_holds_the_umbrella_and_acord_101_lists_the_rest(self):
        """Brent, 19 Oct 2026: the OTHER column holds "the primary excess /
        umbrella policy" and every other policy is listed on ACORD 101 - never
        omitted. Until then crime, cyber, EBL, inland marine, umbrella, excess,
        WC and EPL all contested one box and the whole column printed blank."""
        f = _routed(_line_records=copy.deepcopy(_CE_RECORDS), coverage_lines=copy.deepcopy(_CE_LINES))
        grid, _years = ps._prior_coverage_grid(f)
        assert grid[("OtherLine", 0)]["_family"] == "umbrella"
        assert grid[("OtherLine", 0)]["_layer"] == "umbrella"
        assert grid.other_line == "Umbrella"
        assert grid[("GeneralLiability", 0)]["premium"] == "$ 16,818.00"
        listed = {e["_family"] for e in grid.set_aside}
        assert {"workers_comp", "cyber", "epli"} <= listed and "umbrella" in listed  # the excess layer
        assert "general_liab" not in listed and "property" not in listed

    def test_a_box_a_listed_policy_holds_is_never_taken(self):
        f = _routed(_line_records=[
            _rec("general_liab", AMER, 16818.0, own=False, printed="Commercial General Liability"),
            _rec("general_liab", "Second Carrier Co", printed="General Liability")])
        f["coverage_lines"] = [{"line": "Commercial General Liability", "carrier": AMER,
                                "premium": "$ 16,818.00"}]
        grid, _ = ps._prior_coverage_grid(f)
        assert grid[("GeneralLiability", 0)]["carrier"] == AMER

    def test_the_underlying_schedules_row_is_never_set_aside(self):
        """The umbrella schedule's auto row (listed today, maybe numbered) keeps
        the Automobile column over the auto dec whose figures are redacted."""
        f = _routed(renews_current_programme=True,
                    _line_records=[_rec("auto", AMER, printed="Auto Liability")],
                    underlying_policies=[{"line": "Automobile Liability", "carrier": AMER,
                                          "policy_no": "BA-00123"}])
        grid, _ = ps._prior_coverage_grid(f)
        assert grid[("Automobile", 0)]["policy_no"] == "BA-00123"

    def test_two_unnumbered_policies_of_one_carrier_are_two(self):
        """Two lines, one OTHER column (19 Oct 2026): one line takes it - with
        no premium on either, the first - and the other is listed on ACORD
        101. One carrier's EPL and D&O are still two policies."""
        f = _routed(_line_records=[_rec("epli", FED, printed="Employment Practices Liability"),
                                   _rec("directors_officers", FED, printed="Directors and Officers Liability")])
        grid, _ = ps._prior_coverage_grid(f)
        assert grid[("OtherLine", 0)]["_family"] == "epli"
        assert [e["_family"] for e in grid.set_aside] == ["directors_officers"]

    def test_a_year_is_added_only_while_the_grid_has_room(self):
        hist = [{"line": "General Liability", "carrier": "Old Co", "policy_no": f"GL-{y}",
                 "premium": "$1,000", "effective": f"01/01/{y}", "expiration": f"01/01/{y + 1}"}
                for y in (2022, 2023, 2024)]
        f = _routed(prior_coverage_by_line=hist, effective_date="01/01/2026",
                    _line_records=[_rec("epli", FED)])
        grid, years = ps._prior_coverage_grid(f)
        assert years == ["2024", "2023", "2022"]      # no listed year pushed off the form
        f2 = _routed(prior_coverage_by_line=hist[1:], effective_date="01/01/2026",
                     _line_records=[_rec("epli", FED)])
        grid2, years2 = ps._prior_coverage_grid(f2)
        assert years2 == ["2025", "2024", "2023"]
        assert grid2[("OtherLine", 0)]["carrier"] == FED
        assert grid2[("GeneralLiability", 1)]["policy_no"] == "GL-2024"

    def test_a_priced_policy_still_lists_exactly_as_before(self):
        f = _routed(_line_records=[_rec("general_liab", AMER, 16818.0, own=False)],
                    coverage_lines=[{"line": "Commercial General Liability", "carrier": AMER,
                                     "premium": "$ 16,818.00"}])
        rows = ps._current_policy_grid_rows(f, (None, None))
        assert len(rows) == 1 and "_unpriced" not in rows[0]


# ══ 4. ACORD 125 question 4 - "other insurance with this company" ═══════════

class TestQuestionFour:
    def _small(self, **over):
        recs = [_rec("epli", FED, printed="Employment Practices Liability"),
                _rec("cyber", "ACE American Insurance Company", 4162.0, printed="Cyber")]
        lines = [{"line": "Employment Practices Liability", "carrier": FED},
                 {"line": "Cyber", "carrier": "ACE American Insurance Company", "premium": "$4,162.00"}]
        f = {"coverage_lines": lines, "_line_records": recs, "_form_id": "ACORD_125"}
        f.update(over)
        return f

    def test_unnumbered_policies_list_with_a_blank_number(self):
        f = self._small()
        rows = ps._other_policy_rows(f)
        assert [r["line"] for r in rows] == ["Employment Practices Liability", "Cyber"]
        assert ps._resolve_other_policy_cell("OtherPolicy_LineOfBusinessCode_A", f) == \
            "Employment Practices Liability"
        assert ps._resolve_other_policy_cell("OtherPolicy_PolicyNumberIdentifier_A", f) is None

    def test_more_policies_than_rows_adds_none(self):
        f = {"coverage_lines": copy.deepcopy(_CE_LINES), "_line_records": copy.deepcopy(_CE_RECORDS),
             "_form_id": "ACORD_125"}
        assert ps._other_policy_rows(f) == []

    def test_a_numbered_row_of_the_line_and_carrier_is_that_policy(self):
        f = self._small()
        f["coverage_lines"][0]["policy_number"] = "EPL-778812"
        rows = ps._other_policy_rows(f)
        assert [(r["line"], r["policy_number"]) for r in rows][0] == \
            ("Employment Practices Liability", "EPL-778812")
        assert sum(1 for r in rows if r["line"].startswith("Employment")) == 1

    def test_the_document_answering_question_4_decides(self):
        f = self._small(other_insurance_policies=[])
        assert ps._other_policy_rows(f) == []

    def test_a_record_with_no_declarations_of_its_own_adds_nothing(self):
        f = self._small(_line_records=[_rec("epli", FED, own=False)])
        assert [r["line"] for r in ps._other_policy_rows(f)] == []


# ══ 5. ACORD 131 - the umbrella's underlying schedule ═══════════════════════

class TestUnderlyingSchedule:
    _EPL = {"line": "Employment Practices Liability", "carrier": FED, "premium": None,
            "policy_number": None, "effective_date": "01/01/2025", "expiration_date": "01/01/2026"}

    def _f(self, extra_lines=(), sched=("Employment Practices Liability",)):
        lines = [dict(self._EPL)] + [dict(e) for e in extra_lines]
        return {"coverage_lines": lines, "_form_id": "ACORD_131",
                "_line_records": [_rec("epli", FED, printed="Employment Practices Liability")],
                "underlying_policies": [{"line": "Commercial Liability Umbrella", "carrier": "U Co"}]
                + [{"line": s, "carrier": FED} for s in sched]}

    def test_a_scheduled_redacted_policy_fills_the_other_row(self):
        f = self._f()
        assert ps._resolve_underlying_policy_row("UnderlyingPolicy_OtherPolicy_InsurerFullName_A", f) == FED
        assert ps._resolve_underlying_policy_row(
            "UnderlyingPolicy_OtherPolicy_PolicyEffectiveDate_A", f) == "01/01/2025"
        assert ps._resolve_underlying_policy_row(
            "UnderlyingPolicy_OtherPolicy_PolicyNumberIdentifier_A", f) is None

    def test_never_beside_a_line_that_already_holds_the_row(self):
        f = self._f(extra_lines=[{"line": "Liquor Liability", "carrier": "L Co", "premium": "$900",
                                  "effective_date": "01/01/2025", "expiration_date": "01/01/2026"}],
                    sched=("Employment Practices Liability", "Liquor Liability"))
        assert ps._resolve_underlying_policy_row(
            "UnderlyingPolicy_OtherPolicy_InsurerFullName_A", f) == "L Co"

    def test_not_scheduled_not_underlying(self):
        f = self._f(sched=())
        f["underlying_policies"] = [{"line": "General Liability", "carrier": AMER}]
        assert ps._resolve_underlying_policy_row("UnderlyingPolicy_OtherPolicy_InsurerFullName_A", f) is None

    def test_the_coverage_grid_lists_it_after_todays_rows(self):
        f = self._f()
        assert ps._resolve_underlying_coverage_grid("UnderlyingCoverage_Coverage_OtherIndicator_A", f) == "Yes"
        assert ps._resolve_underlying_coverage_grid(
            "UnderlyingCoverage_Coverage_OtherDescription_A", f) == "Employment Practices Liability"
        assert ps._resolve_underlying_coverage_grid("UnderlyingCoverage_Coverage_OtherIndicator_B", f) is None

    def test_without_its_own_declarations_nothing_moves(self):
        f = self._f()
        f["_line_records"] = [_rec("epli", FED, own=False)]
        assert ps._resolve_underlying_policy_row("UnderlyingPolicy_OtherPolicy_InsurerFullName_A", f) is None
        assert ps._resolve_underlying_coverage_grid("UnderlyingCoverage_Coverage_OtherIndicator_A", f) is None
