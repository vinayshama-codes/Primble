"""Live run 8 (session 3d7b49b6, 15 Sep 2026, Orbin policy only) - driven with
the LIVE values.

1. The per-line policy-number index counted the umbrella's SCHEDULE OF
   UNDERLYING INSURANCE entries (line "General Liability" / "Commercial Auto",
   policy_number = the umbrella's own 6J7) under GL and auto. Each of those
   lines then looked like two contracts, so "Policies in this submission"
   listed GL and auto with no number, the GL rows never got EMC Property &
   Casualty, the ACORD 126 header carrier went blank, and the auto questions
   read the umbrella's 62 pages.
2. A coverage row with no number takes its line's one verified number.
3. ACORD 126 OTHER COVERAGE printed the umbrella's schedule of underlying
   insurance (Guard 2g), with $150 - an endorsement PREMIUM - as its limit
   (cleared by the unnamed-row sweep once 2g empties the row).
4. ACORD 131 FOREIGN GROSS SALES printed $1,305 - class 91580's premium - and
   ANN GROSS SALES was offered the $39,300 payroll exposure.
"""
import copy
import inspect
import json
import os

import pytest

import services.pdf_service as ps
import services.extraction_service as es

BACKEND = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SKIP = ps._SCHED_SKIP


def _schema(form_id):
    with open(os.path.join(BACKEND, "forms_schemas", f"{form_id}_schema.json"), encoding="utf-8") as fh:
        return json.load(fh)


def _gpt(values, grounding=None):
    return {"filled_values": values, "raw_text_fields": set(), "question_grounding": grounding or {}}


def _dec(label, value, section, line, pol, owner="policy"):
    return {"label": label, "value": value, "section": section, "owner": owner,
            "policy_number": pol, "line_of_business": line}


_GL, _AUTO, _UMB, _IM = "BBC7263 - 26", "6E7-40-02---26", "6J7-40-02---26", "6C7-40-02---26"
_UMB_SCHED = "COMMERCIAL UMBRELLA SCHEDULE"
_EMCC = "EMPLOYERS MUTUAL CASUALTY COMPANY"
_EMCPC = "EMC Property & Casualty Company"
# Run 8's literal entries.
_HOME = [
    _dec("Policy Number", _IM, "COMMERCIAL INLAND MARINE DECLARATIONS", "Inland Marine", _IM),
    _dec("POLICY NUMBER", _AUTO, "COMMERCIAL AUTO DECLARATIONS - BUSINESS AUTO", "Commercial Auto", _AUTO),
    _dec("Policy Number", _UMB, "COMMERCIAL UMBRELLA DECLARATIONS", "Commercial Umbrella", _UMB),
    _dec("Policy", _GL, "General Liability Declarations", "General Liability", _GL),
]
_UNDERLYING = [
    _dec("Policy Number", "BBC7263", _UMB_SCHED, "General Liability", _UMB),
    _dec("Policy Period", "07/15/25 to 07/15/26", _UMB_SCHED, "General Liability", _UMB),
    _dec("Occurrence Basis", "Occurrence Basis", _UMB_SCHED, "General Liability", _UMB),
    _dec("Company", "Employers Mutual Casualty Company", _UMB_SCHED, "Commercial Auto", _UMB, "carrier"),
    _dec("Policy Number", "6E74002", _UMB_SCHED, "Commercial Auto", _UMB),
]
_GL_SCHEDULE = [
    _dec("Location 000", "Limited Pollution Coverage - Work Sites $150", "General Liability Schedule",
         "General Liability", _GL),
    _dec("Policy Level Coverages", "General Liability Elite Extension $500", "General Liability Schedule",
         "General Liability", _GL),
]
_ENTRIES = _HOME + _UNDERLYING + _GL_SCHEDULE
_RUN8_BY_LINE = {"general_liab": {_GL}, "auto": {_AUTO}, "umbrella": {_UMB}, "inland_marine": {_IM}}


def _row(line, carrier, number=None, premium=None):
    return {"line": line, "carrier": carrier, "naic": None, "policy_number": number, "premium": premium,
            "effective_date": None, "expiration_date": None}


def _coverage_lines():
    """Run 8's literal `coverage_lines` (dates dropped)."""
    return [
        _row("Property", _EMCC), _row("Liability", _EMCC, None, "$3,954.00"),
        _row("Crime and Fidelity", _EMCC), _row("Inland Marine", _EMCC, _IM, "$300.00"),
        _row("Automobile", _EMCC, None, "$2,991.00"), _row("Workers' Compensation", _EMCC),
        _row("Umbrella", _EMCC, _UMB, "$3,418.00"),
        _row("Commercial Inland Marine", "Employers Mutual Casualty Company", _IM),
        _row("Inland Marine", _EMCC, _IM), _row("Computer Coverage", _EMCC, _IM),
        _row("Covered Autos Liability", _EMCC, None, "$ 1,496.00"),
        _row("Commercial Liability Umbrella", _EMCC, _UMB, "$ 3,418.00"),
        _row("General Liability", _EMCPC, None, "$3,954.00"),
        _row("Commercial General Liability", "EMC Insurance"),
        _row("Uninsured and Underinsured Motorists", _EMCC, None, "$ 258.00"),
        _row("Comprehensive", _EMCC, None, "$ 134.00"), _row("Collision", _EMCC, None, "$ 289.00"),
        _row("Commercial Auto", _EMCC),
    ]


# Six pages in the package's own order and header shape: common declarations,
# then each policy's section; the umbrella's schedule of underlying insurance
# prints the GL and auto numbers on the umbrella's page.
_DOC = "\n".join([
    "[Document page 1]", "EMPLOYERS MUTUAL CASUALTY COMPANY", "COMMON POLICY DECLARATIONS",
    "ORBIN CONTRACTING LLC",
    "[Document page 2]", _EMCPC, "Policy BBC7263 - 26", "General Liability Declarations",
    "[Document page 3]", "Employers Mutual Casualty Company", "POLICY NUMBER 6E7-40-02---26",
    "COMMERCIAL AUTO DECLARATIONS - BUSINESS AUTO",
    "[Document page 4]", "Employers Mutual Casualty Company", "Policy Number 6J7-40-02---26",
    "COMMERCIAL UMBRELLA DECLARATIONS",
    "[Document page 5]", "Employers Mutual Casualty Company", "Policy Number 6J7-40-02---26",
    "SCHEDULE OF UNDERLYING INSURANCE",
    "Commercial General Liability EMC Property & Casualty Company BBC7263",
    "Commercial Auto Liability Employers Mutual Casualty Company 6E74002",
    "[Document page 6]", "Employers Mutual Casualty Company", "Policy Number 6C7-40-02---26",
    "COMMERCIAL INLAND MARINE DECLARATIONS",
])


def _old_index(monkeypatch):
    """The pre-run-8 behaviour: an entry's number counts under its own line."""
    monkeypatch.setattr(es, "_entry_line", lambda e, home: (es._canon_line(e.get("line_of_business"))
                                                           or es._canon_line(e.get("section"))))
    monkeypatch.setattr(es, "_fill_missing_line_numbers", lambda mf: [])


# ── 1. The per-line index ────────────────────────────────────────────────────

def test_the_umbrella_schedule_does_not_give_gl_and_auto_the_umbrella_number():
    assert es._policy_numbers_by_line(_ENTRIES) == _RUN8_BY_LINE
    assert es.current_numbers_by_line(_ENTRIES, {}) == _RUN8_BY_LINE


def test_the_live_failure_shape_is_what_the_old_rule_produced(monkeypatch):
    _old_index(monkeypatch)
    by = es.current_numbers_by_line(_ENTRIES, {})
    assert by["general_liab"] == {_GL, _UMB} and by["auto"] == {_AUTO, _UMB}


def test_the_rule_holds_with_an_expiring_programme_on_file():
    old = "GL 7784120 25"
    facts = {"prior_coverage_by_line": [{"line": "General Liability", "policy_no": old}]}
    entries = _ENTRIES + [_dec("Policy Number", old, "General Liability Declarations", "General Liability", old)]
    assert es.current_numbers_by_line(entries, facts) == _RUN8_BY_LINE


def test_a_package_policy_printed_for_two_lines_keeps_both():
    pkg = "CPP 4Q 887214 26"
    prop = es._canon_line("Commercial Property")
    entries = [
        _dec("Policy Number", pkg, "COMMERCIAL GENERAL LIABILITY DECLARATIONS", "General Liability", pkg),
        _dec("Policy Number", pkg, "COMMERCIAL PROPERTY DECLARATIONS", "Commercial Property", pkg),
        # A GL figure printed on the property pages: the number is home on
        # BOTH lines, so nothing moves.
        _dec("Deductible", "$1,000", "COMMERCIAL PROPERTY DECLARATIONS", "General Liability", pkg),
    ]
    by = es.current_numbers_by_line(entries, {})
    assert prop and by["general_liab"] == {pkg} and by[prop] == {pkg}


def test_a_cross_line_entry_whose_page_policy_has_no_home_keeps_its_own_line():
    # Nothing proves 6J7 is the umbrella's own number, so nothing is moved.
    entries = [_dec("Policy Number", "BBC7263", _UMB_SCHED, "General Liability", _UMB)]
    assert es.current_numbers_by_line(entries, {}) == {"general_liab": {_UMB}}


def test_an_entry_with_no_line_takes_its_section():
    entries = [_dec("Policy Number", _UMB, "COMMERCIAL UMBRELLA DECLARATIONS", None, _UMB)]
    assert es.current_numbers_by_line(entries, {}) == {"umbrella": {_UMB}}


def test_malformed_entries_are_ignored():
    assert es._entry_home_lines(None) == {}
    assert es._entry_home_lines([None, "x", {"policy_number": None}]) == {}
    assert es.current_numbers_by_line(None, {}) == {}
    assert es.current_numbers_by_line([None, "x", {}], {}) == {}


# ── 2. Unnumbered rows ───────────────────────────────────────────────────────

def test_unnumbered_rows_take_their_lines_one_verified_number():
    mf = {"coverage_lines": _coverage_lines(), "dec_page_entries": copy.deepcopy(_ENTRIES)}
    filled = es._fill_missing_line_numbers(mf)
    got = {r["line"]: r["policy_number"] for r in mf["coverage_lines"]}
    for line in ("Liability", "General Liability", "Commercial General Liability"):
        assert got[line] == _GL, line
    for line in ("Automobile", "Covered Autos Liability", "Commercial Auto"):
        assert got[line] == _AUTO, line
    for line in ("Property", "Crime and Fidelity", "Workers' Compensation"):
        assert got[line] is None, line
    assert len(filled) == 6


def test_the_fill_never_overwrites_a_printed_number():
    mf = {"coverage_lines": [_row("General Liability", _EMCPC, "BBC7263")],
          "dec_page_entries": copy.deepcopy(_ENTRIES)}
    assert es._fill_missing_line_numbers(mf) == []
    assert mf["coverage_lines"][0]["policy_number"] == "BBC7263"


def test_a_row_that_denies_coverage_is_never_numbered():
    mf = {"coverage_lines": [_row("General Liability", _EMCC, None, "NO COVERAGE")],
          "dec_page_entries": copy.deepcopy(_ENTRIES)}
    assert es._fill_missing_line_numbers(mf) == []
    assert mf["coverage_lines"][0]["policy_number"] is None


def test_two_candidate_numbers_fill_nothing():
    entries = [_dec("Policy", _GL, "General Liability Declarations", "General Liability", _GL),
               _dec("Policy", "XYZ9999 - 26", "General Liability Declarations", "General Liability",
                    "XYZ9999 - 26")]
    mf = {"coverage_lines": [_row("General Liability", _EMCPC)], "dec_page_entries": entries}
    assert es._fill_missing_line_numbers(mf) == []


def test_a_form_number_is_never_a_rows_number():
    form = "CG 00 01 04 13"
    mf = {"coverage_lines": [_row("General Liability", _EMCPC)],
          "dec_page_entries": [_dec("Form", form, "General Liability Declarations", "General Liability", form)]}
    assert es._fill_missing_line_numbers(mf) == []


@pytest.mark.parametrize("mf", [{}, {"coverage_lines": None}, {"coverage_lines": []},
                                {"coverage_lines": "x"}, {"coverage_lines": [_row("General Liability", _EMCPC)]},
                                {"coverage_lines": [None, "x"], "dec_page_entries": _ENTRIES}])
def test_nothing_to_read_fills_nothing(mf):
    assert es._fill_missing_line_numbers(copy.deepcopy(mf)) == []


def test_the_merge_numbers_rows_after_the_repair_and_before_carrier_binding():
    src = inspect.getsource(es.merge_facts)
    order = [src.index(s) for s in ("_repair_coverage_lines_from_entries(mf)", "_fill_missing_line_numbers(mf)",
                                    "_bind_carriers_to_contracts(mf, docs)", "_build_scoped_fact_store(mf, docs)")]
    assert order == sorted(order)


# ── 1+2 through the consumers: carriers, records, the 126 header, scopes ─────

def _merged(monkeypatch=None, old=False):
    if old:
        _old_index(monkeypatch)
    mf = {"coverage_lines": _coverage_lines(), "dec_page_entries": copy.deepcopy(_ENTRIES)}
    docs = [{"text": _DOC, "filename": "Orbin-ClientDoc.pdf"}]
    es._fill_missing_line_numbers(mf)
    es._bind_carriers_to_contracts(mf, docs)
    es._build_scoped_fact_store(mf, docs)
    return mf, docs


def test_the_gl_rows_are_bound_to_the_gl_carrier():
    mf, _docs = _merged()
    by = {}
    for r in mf["coverage_lines"]:
        by.setdefault(es._canon_line(r["line"]), set()).add(r["carrier"].lower())
    assert by["general_liab"] == {_EMCPC.lower()}
    for line in ("auto", "umbrella", "inland_marine"):
        assert by[line] == {_EMCC.lower()}, line


def test_every_policy_in_the_submission_carries_its_number_and_carrier():
    mf, docs = _merged()
    recs = {r["line"]: r for r in es._build_line_records(mf, docs)}
    assert {k: recs[k]["policy_number"] for k in recs} == {
        "general_liab": _GL, "auto": _AUTO, "umbrella": _UMB, "inland_marine": _IM}
    assert recs["general_liab"]["carrier_name"] == _EMCPC


def test_the_old_rule_left_gl_and_auto_unnumbered(monkeypatch):
    mf, docs = _merged(monkeypatch, old=True)
    recs = {r["line"]: r for r in es._build_line_records(mf, docs)}
    assert not recs.get("general_liab", {}).get("policy_number")
    assert not recs.get("auto", {}).get("policy_number")


def test_the_126_header_prints_the_gl_carrier_and_number():
    mf, docs = _merged()
    m, _c = ps.map_facts_to_form(mf, _schema("ACORD_126"), form_id="ACORD_126", raw_text=_DOC,
                                 pre_filled_gpt=_gpt({}), guard_report=[])
    assert m.get("Insurer_FullName_A") == _EMCPC
    assert m.get("Policy_PolicyNumberIdentifier_A") == _GL


def test_the_umbrella_pages_are_scoped_to_the_umbrella():
    scopes = ps.build_line_page_scopes([{"text": _DOC}], {"dec_page_entries": _ENTRIES})
    assert set(scopes) == {"general_liab", "auto", "umbrella", "inland_marine"}
    for page in ("[Document page 4]", "[Document page 5]"):
        assert page in scopes["umbrella"] and page not in scopes["auto"]
    assert "[Document page 1]" in scopes["auto"]            # common pages stay common
    assert "[Document page 3]" not in scopes["umbrella"]


def test_the_old_rule_fed_the_umbrella_pages_to_the_auto_questions(monkeypatch):
    _old_index(monkeypatch)
    scopes = ps.build_line_page_scopes([{"text": _DOC}], {"dec_page_entries": _ENTRIES})
    assert "umbrella" not in scopes and "[Document page 4]" in scopes["auto"]


# ── 3. ACORD 126 OTHER COVERAGE ──────────────────────────────────────────────

_UNDERLYING_TEXT = (
    "Commercial General Liability / EMC Property & Casualty Company / BBC7263 / 07/15/25 to 07/15/26 / "
    "Occurrence Basis / Minimum Applicable Limits: General Aggregate $ 2,000,000; Products-Completed "
    "Operations Aggregate $ 2,000,000; Personal and Advertising Injury $ 1,000,000; Each Occurrence "
    "$ 1,000,000. Commercial Auto Liability / Employers Mutual Casualty Company / 6E74002 / 07/15/25 to "
    "07/15/26 / Minimum Applicable Limits: Covered Auto Liability $ 1,000,000 Each Accident.")
_DESC, _TICK = "GeneralLiability_OtherCoverageDescription_A", "GeneralLiability_OtherCoverageIndicator_A"
_LIMIT = "GeneralLiability_OtherCoverageLimitAmount_A"
_LIMIT_DESC = "GeneralLiability_OtherCoverageLimitDescription_A"


def _guard(values, ai=None, entries=None, form_id="ACORD_126"):
    mapped = dict(values)
    facts = {"dec_page_entries": copy.deepcopy(_ENTRIES if entries is None else entries), "_form_id": form_id}
    ps._enforce_post_fill_guards(mapped, _schema(form_id), facts,
                                 set(values) if ai is None else set(ai))
    return mapped


def test_a_description_naming_the_packages_own_policy_is_cleared_with_its_tick():
    out = _guard({_DESC: _UNDERLYING_TEXT, _TICK: "Yes"})
    assert out[_DESC] is None and out[_TICK] is None


@pytest.mark.parametrize("desc", ["Umbrella per policy 6J7-40-02---26", "see 6E74002", "BBC7263 schedule",
                                  # printed with spaces (review of run 8)
                                  "Commercial Auto Liability / 6E7 40 02", "GL BBC 7263 - 26",
                                  "umbrella 6j7-40-02---26"])
def test_any_printing_of_a_package_policy_counts(desc):
    assert _guard({_DESC: desc})[_DESC] is None
    assert _guard({_LIMIT_DESC: desc})[_LIMIT_DESC] is None


@pytest.mark.parametrize("desc", ["Additional Insured - Owners, Lessees Or Contractors CG2010",
                                  "Stop Gap Employers Liability", "Hired Auto 6E7", "per BBC72 endorsement",
                                  "Limited Pollution Coverage - Work Sites", "BBC72634 schedule"])
def test_a_description_that_names_no_package_policy_survives(desc):
    assert _guard({_DESC: desc})[_DESC] == desc


def test_junk_attributions_are_not_package_policies():
    # Live sessions carry a form number, a date and a class code as a page's
    # "policy"; none of them may blank a description (review of run 8).
    junk = _ENTRIES + [_dec("Form", "x", "S", "General Liability", k)
                       for k in ("CG 99 09 12 19", "07/15/2025", "91580", "2026")]
    for desc in ("Blanket Additional Insured CG9909", "Endorsement 2026-CG2010", "Class 91580A rider",
                 "07152025A", "Form CG 99 09 12 19 attached"):
        assert ps._package_policy_named_in(desc, {"dec_page_entries": junk}) is None, desc
    for desc in ("Blanket Additional Insured CG9909", "Endorsement 2026-CG2010", "Class 91580A rider"):
        assert _guard({_DESC: desc}, entries=junk)[_DESC] == desc, desc


@pytest.mark.parametrize("value,expected", [("6E74002", True), ("BBC7263", True), ("BBC7263 - 26", True),
                                            ("6j7-40-02---26", True), ("BBC72", False), ("GL123", False),
                                            ("4402-8891-07", False), ("", False), (None, False)])
def test_is_package_policy_number_uses_the_same_contract_rule(value, expected):
    assert ps._is_package_policy_number(value, {"dec_page_entries": _ENTRIES}) is expected


def test_prefix_stubs_are_two_policies():
    facts = {"dec_page_entries": [_dec("Policy", "GL12345", "S", "General Liability", "GL12345")]}
    assert not ps._is_package_policy_number("GL123", facts)
    assert ps._package_policy_named_in("see GL123 rider", facts) is None


def test_a_deterministic_description_is_never_judged():
    assert _guard({_DESC: _UNDERLYING_TEXT}, ai=set())[_DESC] == _UNDERLYING_TEXT


@pytest.mark.parametrize("form_id,field", [("ACORD_160", "GeneralLiability_OtherCoverageDescription_A"),
                                           ("ACORD_141", "CrimeCoverage_OtherCoverage_CoverageDescription_A")])
def test_141_and_160_are_left_alone(form_id, field):
    assert _guard({field: _UNDERLYING_TEXT}, form_id=form_id)[field] == _UNDERLYING_TEXT


@pytest.mark.parametrize("field,expected", [
    ("GeneralLiability_OtherCoverageDescription_A", True), ("GeneralLiability_OtherCoverageLimitDescription_A", True),
    ("ExcessUmbrella_OtherCoverageDescription_A", True), ("CrimeCoverage_OtherCoverage_CoverageDescription_A", True),
    ("Vehicle_OtherCoverage_SymbolDescription_A", False),
    ("GeneralLiability_OtherCoverageCreditSurchargeDescription_A", False),
])
def test_the_description_boxes_the_guard_reads(field, expected):
    assert bool(ps._OTHER_COVERAGE_DESCRIPTION_RE.search(field)) is expected


def test_a_real_limit_printed_without_a_limit_word_survives():
    """The withdrawn 'never called a limit' guard blanked this (review of run 8)."""
    entries = _ENTRIES + [_dec("Medical Payments", "$5,000", "General Liability Schedule",
                               "General Liability", _GL)]
    out = _guard({_DESC: "Medical Payments", _LIMIT: "$5,000"}, entries=entries)
    assert out[_LIMIT] == "$5,000" and out[_DESC] == "Medical Payments"
    assert not hasattr(ps, "_figure_never_printed_as_a_limit")


def test_run8s_other_coverage_row_ships_blank_end_to_end():
    live = {_DESC: _UNDERLYING_TEXT, _LIMIT: "150", _TICK: "Yes"}
    m, _c = ps.map_facts_to_form({"dec_page_entries": copy.deepcopy(_ENTRIES)}, _schema("ACORD_126"),
                                 form_id="ACORD_126", raw_text=_DOC + "\n" + _UNDERLYING_TEXT,
                                 pre_filled_gpt=_gpt(live), guard_report=[])
    assert not m.get(_DESC) and not m.get(_LIMIT) and not m.get(_TICK)


# ── 4. ACORD 131 business exposures ──────────────────────────────────────────

_CLASS_ROWS = [
    {"location": "Location 001", "class_code": "91580", "premium_basis": "Payroll", "exposure_amount": "$39,300",
     "classification": "Contractors - Executive Supervisors or Executive Superintendents"},
    {"location": "Location 001", "class_code": "91585", "premium_basis": "Total Cost",
     "exposure_amount": "$350,000",
     "classification": "Contrctrs-sub work-in connection w/constrctn,recon,repr,erctn of buildings - NOC"},
]
_ONE_LOC = [{"address_line1": "4800 DAHLIA ST", "address_city": "DENVER", "address_state": "CO",
             "address_zip": "80216-3121", "location_number": "1"}]
_FOREIGN = "BusinessInformation_ForeignGrossSalesAmount_A"
_GROSS = "BusinessInformation_AnnualGrossReceiptsAmount_A"
_PAYROLL = "BusinessInformation_TotalPayrollAmount_A"


def _backfilled(v):
    return {"value": v, "source": "ai", "derivation": {"rule": "dec_entry_backfill"}}


def _f131(**kw):
    base = {"_form_id": "ACORD_131", "gl_class_code_schedule": _CLASS_ROWS, "property_locations": _ONE_LOC,
            "_only_dec_page": True, "_only_certificate": False}
    base.update(kw)
    return base


def test_foreign_sales_is_an_owned_blank_on_a_policy_only_package():
    assert ps._resolve_business_total_payroll(_FOREIGN, _f131()) is None
    assert ps._resolve_business_total_payroll(_FOREIGN, _f131(_only_dec_page=False, _only_certificate=True)) is None


@pytest.mark.parametrize("flags", [{"_only_dec_page": False}, {"_only_dec_page": None}])
def test_with_an_application_uploaded_the_document_decides_foreign_sales(flags):
    assert ps._resolve_business_total_payroll(_FOREIGN, _f131(**flags)) is SKIP


def test_gross_sales_prints_a_stated_revenue_or_nothing():
    assert ps._resolve_business_total_payroll(_GROSS, _f131()) is None                      # run 8
    stated = {"value": "$2,400,000", "source": "ai"}
    assert ps._resolve_business_total_payroll(_GROSS, _f131(total_revenue=stated)) == "$2,400,000"
    assert ps._resolve_business_total_payroll(
        _GROSS, _f131(total_revenue=_backfilled("$1,250,000"))) == "$1,250,000"
    assert ps._resolve_business_total_payroll(_GROSS, _f131(total_revenue="Included")) is None


@pytest.mark.parametrize("box,key,amount", [(_GROSS, "total_revenue", "$39,300"),
                                            (_GROSS, "total_revenue", "$350,000"),
                                            (_PAYROLL, "total_payroll", "$39,300"),
                                            (_PAYROLL, "total_payroll", "$350,000")])
def test_one_class_rating_exposure_is_never_the_business_total(box, key, amount):
    assert ps._resolve_business_total_payroll(box, _f131(**{key: _backfilled(amount)})) is None


def test_a_stated_total_equal_to_a_class_exposure_is_not_second_guessed():
    stated = {"value": "$39,300", "source": "ai"}
    assert ps._resolve_business_total_payroll(_PAYROLL, _f131(total_payroll=stated)) == "$39,300"


def test_other_rows_are_subsidiaries_and_two_premises_are_still_one_business():
    # The 131 prints "NAME AND LOCATION OF PRIMARY AND ALL SUBSIDIARY COMPANIES":
    # its rows are companies, not premises (review of run 8).
    stated = {"value": "$2,400,000", "source": "ai"}
    row_b = _GROSS[:-1] + "B"
    assert ps._resolve_business_total_payroll(row_b, _f131(total_revenue=stated)) is None
    assert ps._resolve_business_total_payroll(row_b, _f131(total_revenue=stated, _only_dec_page=False)) is SKIP
    assert ps._resolve_business_total_payroll(
        _GROSS, _f131(total_revenue=stated, property_locations=_ONE_LOC * 2)) == "$2,400,000"
    assert ps._resolve_business_total_payroll(
        _FOREIGN, _f131(_only_dec_page=False, property_locations=_ONE_LOC * 2)) is SKIP


def test_the_186_boxes_follow_the_same_rule_and_141_160_stay_frozen():
    f = {"gl_class_code_schedule": _CLASS_ROWS, "_form_id": "ACORD_186"}
    assert ps._resolve_business_total_payroll(_PAYROLL, {**f, "total_payroll": _backfilled("$39,300")}) is None
    assert ps._resolve_business_total_payroll(_GROSS, {**f, "total_revenue": _backfilled("$350,000")}) is None
    assert ps._resolve_business_total_payroll(
        _GROSS, {**f, "total_revenue": {"value": "$2,400,000"}}) == "$2,400,000"
    assert ps._resolve_business_total_payroll(_PAYROLL, f) is None
    for frozen in ("ACORD_141", "ACORD_160"):
        assert ps._resolve_business_total_payroll(
            _PAYROLL, {**f, "_form_id": frozen, "total_payroll": _backfilled("$39,300")}) is SKIP
    assert ps._resolve_business_total_payroll(_PAYROLL, {k: v for k, v in f.items() if k != "_form_id"}) is SKIP


def test_the_186_business_boxes_ship_blank_end_to_end():
    # Review of run 8: the alias bridge stamped '39,300' / '350,000' here.
    facts = {"gl_class_code_schedule": _CLASS_ROWS, "total_payroll": _backfilled("$39,300"),
             "total_revenue": _backfilled("$350,000")}
    m, _c = ps.map_facts_to_form(facts, _schema("ACORD_186"), form_id="ACORD_186", raw_text="",
                                 pre_filled_gpt=_gpt({}), guard_report=[])
    assert not m.get(_PAYROLL) and not m.get(_GROSS)


@pytest.mark.parametrize("types,expected", [
    (["dec_page"], True), (["dec_page", "loss_run"], True), (["DEC_PAGE", "certificate", "policy"], True),
    (["dec_page", "supplemental_application"], False), (["dec_page", "unknown"], False),
    (["dec_page", None], False), ([], False), (None, False),
])
def test_carrier_documents_only(types, expected):
    from services.extraction_pipeline import carrier_documents_only
    assert carrier_documents_only(types) is expected


def test_a_dec_page_plus_a_loss_run_is_still_a_policy_only_package():
    assert ps._resolve_business_total_payroll(
        _FOREIGN, _f131(_only_dec_page=False, _carrier_documents_only=True)) is None
    # The newer flag decides when present; the older ones only for stored sessions.
    assert ps._resolve_business_total_payroll(_FOREIGN, _f131(_carrier_documents_only=False)) is SKIP


def test_a_zero_a_person_typed_prints_and_a_model_zero_does_not():
    assert ps._resolve_business_total_payroll(
        _PAYROLL, _f131(total_payroll={"value": "0", "source": "producer"})) == "0"
    assert ps._resolve_business_total_payroll(
        _PAYROLL, _f131(total_payroll={"value": "$0", "source": "client_arq"})) == "$0"
    assert ps._resolve_business_total_payroll(_PAYROLL, _f131(total_payroll={"value": "$0", "source": "ai"})) is None
    assert ps._resolve_business_total_payroll(_PAYROLL, _f131(total_payroll="0")) is None


def test_run8s_131_business_boxes_ship_blank_end_to_end():
    facts = {k: v for k, v in _f131().items() if k != "_form_id"}
    facts["dec_page_entries"] = copy.deepcopy(_ENTRIES)
    live = {_FOREIGN: "$1,305", _GROSS: "$39,300"}
    m, _c = ps.map_facts_to_form(facts, _schema("ACORD_131"), form_id="ACORD_131", raw_text=_DOC,
                                 pre_filled_gpt=_gpt(live), guard_report=[])
    assert not m.get(_FOREIGN) and not m.get(_GROSS)


# ── Adversarial review of this round: index, number fill, ACORD 25 ───────────

def test_a_coverage_part_printed_under_another_parts_heading_keeps_its_number():
    # An umbrella PART of a package policy printed on its GL declarations.
    pkg = "CPP 4Q 887214 26"
    sec = "COMMERCIAL GENERAL LIABILITY COVERAGE PART DECLARATIONS"
    entries = [_dec("Policy Number", pkg, sec, "General Liability", pkg),
               _dec("Each Occurrence", "$1,000,000", sec, "Commercial Umbrella", pkg)]
    by = es.current_numbers_by_line(entries, {})
    assert by["umbrella"] == {pkg} and by["general_liab"] == {pkg}


def test_hired_auto_on_the_gl_policy_keeps_the_gl_number():
    entries = [_dec("Policy", _GL, "General Liability Declarations", "General Liability", _GL),
               _dec("Hired Auto Liability", "$1,000,000", "General Liability Declarations", "Commercial Auto", _GL)]
    assert es.current_numbers_by_line(entries, {})["auto"] == {_GL}


def test_an_umbrella_declarations_whose_entries_carry_no_line_is_still_home():
    home = [e if e["policy_number"] != _UMB else dict(e, line_of_business=None) for e in _HOME]
    assert es.current_numbers_by_line(home + _UNDERLYING, {}) == _RUN8_BY_LINE


@pytest.mark.parametrize("naic", [None, "25674"])
def test_the_fill_never_takes_an_expiring_number(naic):
    old = "CA 7784121 25"
    mf = {"prior_coverage_by_line": [{"line": "Automobile", "policy_no": old}],
          "coverage_lines": [dict(_row("Automobile", "Travelers Indemnity Company"), naic=naic)],
          "dec_page_entries": [_dec("Policy Number", old, "EXPIRING PROGRAMME SUMMARY", "Commercial Auto", old)]}
    assert es._fill_missing_line_numbers(mf) == []
    assert mf["coverage_lines"][0]["policy_number"] is None


def test_two_printings_of_one_contract_are_one_candidate():
    entries = [_dec("Policy", _GL, "General Liability Declarations", "General Liability", _GL),
               _dec("Policy Number", "BBC7263", _UMB_SCHED, "General Liability", "BBC7263")]
    mf = {"coverage_lines": [_row("General Liability", _EMCPC)], "dec_page_entries": entries}
    assert es._fill_missing_line_numbers(mf) == ["General Liability -> BBC7263 - 26"]


def test_a_row_naming_its_own_insurer_is_never_filled_or_rebound():
    trav = dict(_row("General Liability", "Travelers Indemnity Company"), naic="25658")
    mf = {"coverage_lines": _coverage_lines() + [trav], "dec_page_entries": copy.deepcopy(_ENTRIES)}
    es._fill_missing_line_numbers(mf)
    es._bind_carriers_to_contracts(mf, [{"text": _DOC}])
    row = mf["coverage_lines"][-1]
    assert (row["carrier"], row["naic"], row["policy_number"]) == ("Travelers Indemnity Company", "25658", None)


@pytest.mark.parametrize("row,column,expected", [
    ("Liability", "ExcessLiability", True), ("Liability", "AutomobileLiability", True),
    ("Liability", "GeneralLiability", False), ("Commercial Liability Umbrella", "ExcessLiability", False),
    ("Covered Autos Liability", "AutomobileLiability", False), ("Employers Liability",
                                                                "WorkersCompensationAndEmployersLiability", False),
    ("Frobnitz Coverage", "ExcessLiability", False), (None, "ExcessLiability", False), ("Liability", "", False),
])
def test_row_names_another_line(row, column, expected):
    assert ps._row_names_another_line(row, column) is expected


def test_the_certificate_columns_keep_their_own_lines():
    """Review of run 8: once the bare "Liability" row was numbered and re-bound,
    it also claimed the Excess and Auto columns - the umbrella number and two
    INSR LTRs went blank on run 8's own ACORD 25."""
    mf, _docs = _merged()
    m, _c = ps.map_facts_to_form(mf, _schema("ACORD_25"), form_id="ACORD_25", raw_text=_DOC,
                                 pre_filled_gpt=_gpt({}), guard_report=[])
    assert m.get("Policy_GeneralLiability_PolicyNumberIdentifier_A") == _GL
    assert m.get("Policy_AutomobileLiability_PolicyNumberIdentifier_A") == _AUTO
    assert m.get("Policy_ExcessLiability_PolicyNumberIdentifier_A") == _UMB
    gl, auto, umb = (m.get(f) for f in ("GeneralLiability_InsurerLetterCode_A", "Vehicle_InsurerLetterCode_A",
                                         "ExcessUmbrella_InsurerLetterCode_A"))
    assert gl and auto and umb and gl != auto and auto == umb
