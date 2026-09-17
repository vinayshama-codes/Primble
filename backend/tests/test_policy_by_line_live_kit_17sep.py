"""Policy number by line - the live kit run, 17 Sep 2026.

Brent: "a single policy number is still trying to be represented across all.
Please let me know if this was corrected and it's just a misunderstanding."

The policy-by-line kit (backend/scripts/make_policy_by_line_test_pdfs.py) was
run live. It answered: fixed where every policy has its own declarations, NOT
fixed where one document prints one number for several policies, and the run
found new identity defects on the way:

  1. A renewal summary printing POLICY NUMBER SRC-4410982 once, and saying
     "Each coverage above is issued as a separate policy", put SRC-4410982 on
     ACORD 126, 131 (and both its underlying rows) and all three ACORD 25 rows.
  2. A package number shared by General Liability and Property was read as
     corruption; the repair then blanked BOTH General Liability policies (the
     package's and a project policy from the certificate) everywhere, and the
     Data Consistency card never asked which one applies.
  3. The same repair made the umbrella's "PRIOR UMBRELLA CARRIER: Birchline
     ..." sentence the CURRENT umbrella carrier - on ACORD 131 and as ACORD 25's
     INSURER D - beside another company's NAIC.
  4. "QUILLON SPECIALTY INSURANCE COMPANY" bound from a page header as
     "QUILLON SPECIALTY INSURANCE", dropping the company's NAIC.
  5. Confirming one of two General Liability policies wrote the number onto
     both rows, so each kept its own company - a number beside the wrong insurer.
  6. ACORD 25's Auto row lost its dates (01/01/26 vs 01/01/2026), its insurer
     list lost Quillon Mutual's NAIC (printed as "Co." on the certificate), and
     the GL row was lettered to one of two companies claiming the line.
  7. Field QA flagged every routed renewal's section-form effective date as a
     FAIL, and ACORD 125's proposed expiration was one day short across 29 Feb.
  8. Every downloaded PDF was the blank template: `pikepdf.Boolean` does not
     exist in the pikepdf 9.x a macOS 12 venv installs.

The integration tests replay the LIVE extraction output - what gpt-5.4-mini
returned for the kit's PDFs, stored in tests/fixtures/policy_by_line_live_17sep
.json - through the real merge, Data Consistency, stamper and Field QA.
"""
import copy
import io
import json
import os
import re
from datetime import datetime

import pytest

import services.arq_service as arq
import services.extraction_service as es
import services.field_qa as fqa
import services.pdf_service as ps
import services.underwriting_consistency as uc

BACKEND = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FIXTURE = os.path.join(BACKEND, "tests", "fixtures", "policy_by_line_live_17sep.json")
EMPTY_GPT = {"filled_values": {}, "raw_text_fields": set(), "question_grounding": {}}

QPC, LSG, SIM = "QPC5519 - 26", "LSG-4471102-26", "SIM-7730418"
AUTO, UMB, SRC = "4A8-21-07---26", "4U8-21-07---26", "SRC-4410982"
PC, MUTUAL = "Quillon Property & Casualty Company", "Quillon Mutual Casualty Company"
SPECIALTY, LARCHMONT = "Quillon Specialty Insurance Company", "Larchmont Specialty Insurance Co."


@pytest.fixture(autouse=True)
def _no_llm_judge(monkeypatch):
    """The evidence judge is an LLM call; these tests never make one."""
    monkeypatch.setattr(ps, "_EVIDENCE_JUDGE_ENABLED", False)


def _live_docs(name):
    with open(FIXTURE, encoding="utf-8") as fh:
        return copy.deepcopy(json.load(fh)[name])


def _pipeline(docs, confirmations=None):
    """merge -> confirmations -> Data Consistency -> withheld keys, in the
    order extraction_pipeline._finalize_pipeline runs them."""
    confirmations = confirmations or {}
    mf, _ = es.merge_facts(copy.deepcopy(docs), es.select_primary_truth(docs))
    if confirmations:
        mf = uc.apply_confirmations(mf, confirmations, docs=docs)
    uw = uc.assess_underwriting_consistency(docs, mf, confirmations)
    withheld = set(uc.unresolved_withheld_keys(uw, confirmations)) | set(mf.get("_uw_conflicted_keys") or [])
    if withheld:
        mf["_uw_conflicted_keys"] = sorted(withheld)
    conflicts = set(uc.unresolved_conflict_keys(uw, confirmations)) | withheld
    if conflicts:
        mf["_uw_conflict_keys"] = sorted(conflicts)
    return mf, uw


def _forms(mf, form_ids):
    schemas = ps._all_form_schemas()
    out = {}
    for fid in form_ids:
        guard: list = []
        mapped, conf = ps.map_facts_to_form(copy.deepcopy(mf), schemas[fid], fid, raw_text="",
                                            pre_filled_gpt=EMPTY_GPT, guard_report=guard)
        out[fid] = {"schema": schemas[fid], "mapped": dict(mapped),
                    "confidence": dict(conf), "guard_blanks": guard}
    return out


def _rows(mf):
    return [r for r in es._fv(mf, "coverage_lines") or [] if isinstance(r, dict)]


def _entity(name):
    return ps._carrier_entity_key(name)


def _letter_of(form, company):
    """The ACORD 25 roster letter seated for `company`, or None."""
    for letter in "ABCDEF":
        name = form.get(f"Insurer_FullName_{letter}")
        if name and _entity(name) == _entity(company):
            return letter
    return None


@pytest.fixture(scope="module")
def upload1():
    docs = _live_docs("upload_1_package_and_project_certificate")
    return docs, _pipeline(docs)


@pytest.fixture(scope="module")
def upload2():
    docs = _live_docs("upload_2_one_number_summary")
    return docs, _pipeline(docs)


# ── 1. ONE PRINTED NUMBER IS NOT EVERY LINE'S NUMBER (upload 2) ──────────────

def test_upload2_the_summary_number_is_withheld_from_every_line(upload2):
    _docs, (mf, _uw) = upload2
    rows = _rows(mf)
    assert {es._canon_line(r["line"]) for r in rows} == {"general_liab", "auto", "umbrella"}
    assert all(not r.get("policy_number") for r in rows), rows
    # ...and the index can no longer hand it back to any of those lines
    by_line = es.current_numbers_by_line(mf.get("dec_page_entries"), mf)
    assert not any(SRC in nums for nums in by_line.values()), by_line
    # the companies and terms the page does print are untouched
    assert all(_entity(r["carrier"]) == _entity("Sagebrush Ridge Casualty Company") for r in rows)


def test_upload2_no_form_prints_the_one_number_on_any_line(upload2):
    _docs, (mf, _uw) = upload2
    forms = _forms(mf, ["ACORD_126", "ACORD_131", "ACORD_25"])
    for fid, g in forms.items():
        numbers = {k: v for k, v in g["mapped"].items() if "PolicyNumber" in k and v}
        assert SRC not in numbers.values(), (fid, numbers)
    assert forms["ACORD_126"]["mapped"].get("Insurer_FullName_A") == "SAGEBRUSH RIDGE CASUALTY COMPANY"
    assert forms["ACORD_131"]["mapped"].get("Insurer_FullName_A") == "SAGEBRUSH RIDGE CASUALTY COMPANY"


# ── 2. A PACKAGE NUMBER IS NOT CORRUPTION (upload 1) ─────────────────────────

def test_upload1_general_liability_keeps_both_of_its_policies(upload1):
    _docs, (mf, _uw) = upload1
    gl = {r.get("policy_number") for r in _rows(mf) if es._canon_line(r["line"]) == "general_liab"}
    assert gl == {QPC, LSG}
    prop = {r.get("policy_number") for r in _rows(mf) if es._canon_line(r["line"]) == "property"}
    assert prop == {QPC}


def test_upload1_the_card_asks_about_general_liability_only(upload1):
    _docs, (_mf, uw) = upload1
    field = next(f for f in uw["fields"] if f["fact_key"] == "policy_number")
    assert field["status"] == "conflict"
    assert field["conflict_scope"] == ["general_liab"]
    assert {v["display"] for v in field["values"]} == {QPC, LSG}


def test_upload1_the_policies_table_keeps_each_policy_with_its_own_company(upload1):
    _docs, (_mf, uw) = upload1
    field = next(f for f in uw["fields"] if f["fact_key"] == "policy_number")
    recs = {(r["line"], r["policy_number"]): r for r in field["line_records"]}
    assert set(recs) == {("auto", AUTO), ("general_liab", QPC), ("general_liab", LSG),
                         ("inland_marine", SIM), ("property", QPC), ("umbrella", UMB)}
    assert (_entity(recs[("general_liab", QPC)]["carrier_name"]), recs[("general_liab", QPC)]["carrier_naic"]) \
        == (_entity(PC), "91880")
    assert (_entity(recs[("general_liab", LSG)]["carrier_name"]), recs[("general_liab", LSG)]["carrier_naic"]) \
        == (_entity(LARCHMONT), "93518")
    assert (_entity(recs[("auto", AUTO)]["carrier_name"]), recs[("auto", AUTO)]["carrier_naic"]) \
        == (_entity(MUTUAL), "91872")
    assert (_entity(recs[("inland_marine", SIM)]["carrier_name"]), recs[("inland_marine", SIM)]["carrier_naic"]) \
        == (_entity(SPECIALTY), "91895")
    assert _entity(recs[("umbrella", UMB)]["carrier_name"]) == _entity(MUTUAL)


# ── 3. A PRIOR CARRIER IS NOT THE CURRENT ONE ────────────────────────────────

def test_upload1_the_prior_umbrella_carrier_is_nowhere_current(upload1):
    _docs, (mf, _uw) = upload1
    assert not any("Birchline" in str(r.get("carrier")) for r in _rows(mf))
    forms = _forms(mf, ["ACORD_131", "ACORD_25"])
    for fid, g in forms.items():
        assert not any("Birchline" in str(v) for v in g["mapped"].values()), fid
    m131 = forms["ACORD_131"]["mapped"]
    assert (_entity(m131["Insurer_FullName_A"]), m131["Insurer_NAICCode_A"]) == (_entity(MUTUAL), "91872")


def test_a_carrier_entry_labelled_prior_or_expiring_is_not_indexed():
    entries = [
        {"label": label, "value": "Birchline Specialty Casualty Company", "owner": "carrier",
         "section": "COMMERCIAL UMBRELLA DECLARATIONS", "line_of_business": "Commercial Umbrella",
         "policy_number": UMB}
        for label in ("PRIOR UMBRELLA CARRIER", "EXPIRING INSURER", "Previous Company",
                      "FORMER WRITING COMPANY")
    ] + [{"label": "ISSUING COMPANY", "value": SPECIALTY, "owner": "carrier",
          "section": "COMMERCIAL INLAND MARINE DECLARATIONS",
          "line_of_business": "Inland Marine", "policy_number": SIM}]
    assert es._carriers_by_line(entries) == {"inland_marine": {SPECIALTY}}


def test_the_repair_never_keeps_a_naic_beside_a_company_it_replaced():
    lines = [{"line": "Umbrella", "policy_number": AUTO, "carrier": "Other Casualty Co.",
              "naic": "99999", "premium": "$100"},
             {"line": "Automobile", "policy_number": AUTO, "carrier": MUTUAL, "premium": "$200"}]
    entries = [{"label": "POLICY NUMBER", "value": UMB, "section": "COMMERCIAL UMBRELLA DECLARATIONS",
                "line_of_business": "Commercial Umbrella", "policy_number": UMB, "owner": "policy"},
               {"label": "POLICY NUMBER", "value": AUTO, "section": "BUSINESS AUTO DECLARATIONS",
                "line_of_business": "Business Auto", "policy_number": AUTO, "owner": "policy"},
               {"label": "ISSUING COMPANY", "value": MUTUAL, "section": "COMMERCIAL UMBRELLA DECLARATIONS",
                "line_of_business": "Commercial Umbrella", "policy_number": UMB, "owner": "carrier"}]
    mf = {"coverage_lines": lines, "dec_page_entries": entries}
    es._repair_coverage_lines_from_entries(mf)
    umbrella = next(r for r in mf["coverage_lines"] if r["line"] == "Umbrella")
    assert umbrella["policy_number"] == UMB
    assert umbrella["carrier"] == MUTUAL and umbrella["naic"] is None


# ── The corruption the repair exists for is still repaired ───────────────────

def test_a_package_number_is_not_corruption_but_a_borrowed_number_still_is():
    package = [{"line": "Property", "policy_number": QPC, "premium": "$1"},
               {"line": "Liability", "policy_number": QPC, "premium": "$2"}]
    entries = [{"label": "POLICY NUMBER", "value": QPC, "section": "COMMERCIAL PROPERTY COVERAGE PART",
                "line_of_business": "Commercial Property", "policy_number": QPC},
               {"label": "EACH OCCURRENCE", "value": "$1,000,000", "section": "COMMERCIAL PACKAGE POLICY",
                "line_of_business": "General Liability", "policy_number": QPC}]
    assert es._coverage_lines_are_self_contradictory(package, entries, {}) is False
    assert es._coverage_lines_are_self_contradictory(package) is True       # no evidence: legacy reading
    borrowed = package + [{"line": "Umbrella", "policy_number": QPC, "premium": "$3"}]
    entries_umb = entries + [{"label": "POLICY NUMBER", "value": UMB,
                              "section": "COMMERCIAL UMBRELLA DECLARATIONS",
                              "line_of_business": "Commercial Umbrella", "policy_number": UMB}]
    assert es._coverage_lines_are_self_contradictory(borrowed, entries_umb, {}) is True
    mf = {"coverage_lines": copy.deepcopy(borrowed), "dec_page_entries": entries_umb}
    es._repair_coverage_lines_from_entries(mf)
    got = {r["line"]: r["policy_number"] for r in mf["coverage_lines"]}
    assert got == {"Property": QPC, "Liability": QPC, "Umbrella": UMB}


def test_two_policies_on_one_line_each_keep_their_number_when_the_repair_runs():
    lines = [{"line": "Liability", "policy_number": QPC, "carrier": PC, "premium": "$1"},
             {"line": "Commercial General Liability", "policy_number": LSG, "carrier": LARCHMONT,
              "naic": "93518"},
             {"line": "Umbrella", "policy_number": AUTO, "premium": "$2"},        # the corruption
             {"line": "Automobile", "policy_number": AUTO, "premium": "$3"}]
    entries = [{"label": "POLICY NUMBER", "value": QPC, "section": "GENERAL LIABILITY",
                "line_of_business": "General Liability", "policy_number": QPC},
               {"label": "POLICY NUMBER", "value": LSG, "section": "COVERAGES",
                "line_of_business": "Commercial General Liability", "policy_number": LSG},
               {"label": "POLICY NUMBER", "value": UMB, "section": "COMMERCIAL UMBRELLA DECLARATIONS",
                "line_of_business": "Commercial Umbrella", "policy_number": UMB},
               {"label": "POLICY NUMBER", "value": AUTO, "section": "BUSINESS AUTO DECLARATIONS",
                "line_of_business": "Business Auto", "policy_number": AUTO}]
    mf = {"coverage_lines": lines, "dec_page_entries": entries}
    es._repair_coverage_lines_from_entries(mf)
    got = [(r["line"], r["policy_number"]) for r in mf["coverage_lines"]]
    assert got == [("Liability", QPC), ("Commercial General Liability", LSG),
                   ("Umbrella", UMB), ("Automobile", AUTO)]


# ── 4. A HEADER CARRIER IS THE WHOLE LEGAL NAME ──────────────────────────────

@pytest.mark.parametrize("line,expected", [
    ("QUILLON SPECIALTY INSURANCE COMPANY POLICY NUMBER: SIM-7730418", "QUILLON SPECIALTY INSURANCE COMPANY"),
    ("QUILLON MUTUAL CASUALTY COMPANY POLICY NO: 4A8-21-07---26", "QUILLON MUTUAL CASUALTY COMPANY"),
    ("QUILLON PROPERTY & CASUALTY COMPANY NAIC 91880", "QUILLON PROPERTY & CASUALTY COMPANY"),
    ("TRAVELERS CASUALTY INSURANCE COMPANY OF AMERICA POLICY NUMBER: X1", "TRAVELERS CASUALTY INSURANCE COMPANY OF AMERICA"),
    ("Insurance Company of North America Policy No 12345", "Insurance Company of North America"),
    ("THE INSURANCE COMPANY OF THE STATE OF PENNSYLVANIA POLICY PERIOD", "THE INSURANCE COMPANY OF THE STATE OF PENNSYLVANIA"),
    ("ACME INSURANCE CO., INC. POLICY NUMBER AB1", "ACME INSURANCE CO., INC."),
    ("ERIE INSURANCE EXCHANGE POLICY", "ERIE INSURANCE EXCHANGE"),
    ("HARTFORD FIRE INSURANCE COMPANY OF", "HARTFORD FIRE INSURANCE COMPANY"),
    ("QUILLON INSURANCE GROUP", "QUILLON INSURANCE"),      # a brand line is unchanged
])
def test_the_header_carrier_name_runs_through_its_legal_form(line, expected):
    assert es._header_carrier_name(line).strip(" ,*") == expected


def test_upload1_inland_marine_keeps_its_company_and_naic(upload1):
    _docs, (mf, _uw) = upload1
    im = [r for r in _rows(mf) if es._canon_line(r["line"]) == "inland_marine"]
    assert im and all(_entity(r["carrier"]) == _entity(SPECIALTY) for r in im)
    assert "91895" in {r.get("naic") for r in im}
    forms = _forms(mf, ["ACORD_25"])["ACORD_25"]["mapped"]
    letter = _letter_of(forms, SPECIALTY)
    assert letter and forms[f"Insurer_NAICCode_{letter}"] == "91895"
    assert not any(v == "QUILLON SPECIALTY INSURANCE" for v in forms.values())


# ── 5. THE CERTIFICATE: dates, NAICs and letters ─────────────────────────────

def test_upload1_the_certificate_rows(upload1):
    _docs, (mf, _uw) = upload1
    m = _forms(mf, ["ACORD_25"])["ACORD_25"]["mapped"]
    assert m["Policy_AutomobileLiability_PolicyNumberIdentifier_A"] == AUTO
    assert (m["Policy_AutomobileLiability_EffectiveDate_A"],
            m["Policy_AutomobileLiability_ExpirationDate_A"]) == ("01/01/2026", "01/01/2027")
    assert m["Policy_ExcessLiability_PolicyNumberIdentifier_A"] == UMB
    mutual = _letter_of(m, MUTUAL)
    assert mutual and m[f"Insurer_NAICCode_{mutual}"] == "91872"
    assert m["Vehicle_InsurerLetterCode_A"] == mutual
    assert m["ExcessUmbrella_InsurerLetterCode_A"] == mutual
    # General Liability is contested: no number, and no company letter either
    assert not m.get("Policy_GeneralLiability_PolicyNumberIdentifier_A")
    assert not m.get("GeneralLiability_InsurerLetterCode_A")
    assert not m.get("Policy_WorkersCompensationAndEmployersLiability_PolicyNumberIdentifier_A")


def test_one_date_printed_two_ways_is_one_date_on_the_certificate():
    rows = [{"line": "Automobile", "policy_number": AUTO, "effective_date": "01/01/26", "premium": "$1"},
            {"line": "Automobile Liability", "policy_number": "4A82107", "effective_date": "01/01/2026"}]
    facts = {"coverage_lines": rows, "_form_id": "ACORD_25"}
    assert ps._resolve_current_policy_line_cell(
        "Policy_AutomobileLiability_EffectiveDate_A", facts) == "01/01/2026"
    rows[1]["effective_date"] = "02/01/2026"
    assert ps._resolve_current_policy_line_cell(
        "Policy_AutomobileLiability_EffectiveDate_A", facts) is None


# ── 6. A CONFIRMATION CHOOSES A CONTRACT ─────────────────────────────────────

def test_confirming_the_project_policy_prints_its_own_company(upload1):
    docs, (base_mf, _uw) = upload1
    base = _forms(base_mf, ["ACORD_131", "ACORD_25"])
    mf, uw = _pipeline(docs, {uc.scoped_confirmation_key("policy_number", "general_liab"): LSG})
    field = next(f for f in uw["fields"] if f["fact_key"] == "policy_number")
    assert field["status"] != "conflict"
    forms = _forms(mf, ["ACORD_126", "ACORD_131", "ACORD_25"])
    m126, m25 = forms["ACORD_126"]["mapped"], forms["ACORD_25"]["mapped"]
    assert (m126["Policy_PolicyNumberIdentifier_A"], m126["Insurer_NAICCode_A"]) == (LSG, "93518")
    assert _entity(m126["Insurer_FullName_A"]) == _entity(LARCHMONT)
    assert m25["Policy_GeneralLiability_PolicyNumberIdentifier_A"] == LSG
    larchmont = _letter_of(m25, LARCHMONT)
    assert larchmont and m25["GeneralLiability_InsurerLetterCode_A"] == larchmont
    assert m25[f"Insurer_NAICCode_{larchmont}"] == "93518"
    # C2: no other box moved
    for fid in ("ACORD_131", "ACORD_25"):
        for k, v in base[fid]["mapped"].items():
            if "PolicyNumber" in k and "GeneralLiability" not in k:
                assert forms[fid]["mapped"].get(k) == v, (fid, k)
    assert not any(v == LSG for k, v in forms["ACORD_131"]["mapped"].items())


def test_confirming_the_package_policy_sets_the_project_policy_aside(upload1):
    docs, _ = upload1
    mf, _uw = _pipeline(docs, {uc.scoped_confirmation_key("policy_number", "general_liab"): QPC})
    forms = _forms(mf, ["ACORD_126", "ACORD_25"])
    m126, m25 = forms["ACORD_126"]["mapped"], forms["ACORD_25"]["mapped"]
    assert (m126["Policy_PolicyNumberIdentifier_A"], m126["Insurer_NAICCode_A"]) == (QPC, "91880")
    assert _entity(m126["Insurer_FullName_A"]) == _entity(PC)
    assert m25["GeneralLiability_InsurerLetterCode_A"] == _letter_of(m25, PC)
    assert _letter_of(m25, LARCHMONT) is None
    aside = [r for r in _rows(mf) if r.get("_set_aside")]
    assert len(aside) == 1 and aside[0]["policy_number"] is None


def test_a_typed_number_no_row_prints_stands_beside_no_company():
    rows = [{"line": "Liability", "policy_number": QPC, "carrier": PC, "naic": "91880", "premium": "$1"},
            {"line": "Commercial General Liability", "policy_number": LSG, "carrier": LARCHMONT,
             "naic": "93518"}]
    out = uc.apply_confirmations({"coverage_lines": rows},
                                 {uc.scoped_confirmation_key("policy_number", "general_liab"): "GL-999-26"})
    gl = out["coverage_lines"]
    assert {r["policy_number"] for r in gl} == {"GL-999-26"}
    assert all(r.get("carrier") is None and r.get("naic") is None for r in gl)


def test_a_confirmed_number_outranks_a_dec_index_that_names_only_the_other_policy():
    rows = [{"line": "Liability", "policy_number": QPC, "carrier": PC, "naic": "91880", "premium": "$1"},
            {"line": "Commercial General Liability", "policy_number": LSG, "carrier": LARCHMONT,
             "naic": "93518"}]
    entries = [{"label": "POLICY NUMBER", "value": QPC, "section": "GENERAL LIABILITY DECLARATIONS",
                "line_of_business": "General Liability", "policy_number": QPC}]
    out = uc.apply_confirmations({"coverage_lines": rows, "dec_page_entries": entries},
                                 {uc.scoped_confirmation_key("policy_number", "general_liab"): LSG})
    ctx = {**out, "_form_id": "ACORD_126"}
    assert ps._resolve_section_policy_identity("Policy_PolicyNumberIdentifier_A", ctx) == LSG
    assert ps._resolve_section_policy_identity("Insurer_NAICCode_A", ctx) == "93518"


# ── 7. THE SEPARATE-POLICIES STATEMENT AND THE CONTRACT TEST ─────────────────

@pytest.mark.parametrize("text", [
    "Each coverage above is issued as a separate policy.",
    "Each line of coverage is written on its own policy.",
    "Separate policies are issued for each coverage shown.",
    "These coverages are issued under separate policies.",
    "Individual policy numbers are shown on each policy's own declarations.",
    "Policy numbers are shown on the individual declarations.",
])
def test_a_page_saying_its_coverages_are_separate_policies(text):
    assert es._page_states_separate_policies(text) is True


@pytest.mark.parametrize("text", [
    "No separate policy is issued for each coverage part.",
    "Commercial Auto: see separate policy.",
    "This coverage is not part of package policy QPC5519 - 26.",
    "Each coverage part is billed separately.",
])
def test_a_page_that_does_not_say_so(text):
    assert es._page_states_separate_policies(text) is False


def _withhold(lines, entries=(), text=""):
    mf = {"coverage_lines": copy.deepcopy(lines), "dec_page_entries": copy.deepcopy(list(entries))}
    es._withhold_page_header_numbers(mf, [{"text": text}] if text else [])
    return {r["line"]: r.get("policy_number") for r in mf["coverage_lines"]}


def test_an_umbrella_sharing_a_number_with_its_underlying_line_is_not_one_contract():
    lines = [{"line": "General Liability", "policy_number": "PKG-100200"},
             {"line": "Commercial Umbrella", "policy_number": "PKG-100200"}]
    assert _withhold(lines) == {"General Liability": None, "Commercial Umbrella": None}


def test_a_line_whose_own_declarations_print_the_number_keeps_it():
    lines = [{"line": "General Liability", "policy_number": UMB},
             {"line": "Commercial Umbrella", "policy_number": UMB}]
    home = [{"label": "POLICY NUMBER", "value": UMB, "section": "COMMERCIAL UMBRELLA DECLARATIONS",
             "line_of_business": "Commercial Umbrella", "policy_number": UMB}]
    assert _withhold(lines, home) == {"General Liability": None, "Commercial Umbrella": UMB}


@pytest.mark.parametrize("other", ["Commercial Property", "Stop Gap Employers Liability"])
def test_a_package_number_with_no_statement_is_kept(other):
    lines = [{"line": "General Liability", "policy_number": "PKG-100200"},
             {"line": other, "policy_number": "PKG-100200"}]
    assert _withhold(lines) == {"General Liability": "PKG-100200", other: "PKG-100200"}


def test_a_workers_compensation_policy_is_never_part_of_another_contract():
    lines = [{"line": "General Liability", "policy_number": "PKG-100200"},
             {"line": "Workers Compensation", "policy_number": "PKG-100200"}]
    assert _withhold(lines) == {"General Liability": None, "Workers Compensation": None}


def test_the_statement_must_be_on_a_page_that_prints_the_number():
    lines = [{"line": "General Liability", "policy_number": "PKG-100200"},
             {"line": "Commercial Property", "policy_number": "PKG-100200"}]
    elsewhere = ("[Document page 1]\nPOLICY NUMBER: PKG-100200\nGeneral Liability\nProperty\n"
                 "[Document page 2]\nOTHER SUMMARY\nEach coverage above is issued as a separate policy.\n")
    assert _withhold(lines, text=elsewhere) == {"General Liability": "PKG-100200",
                                                 "Commercial Property": "PKG-100200"}
    same_page = elsewhere.replace("[Document page 2]\nOTHER SUMMARY\n", "")
    assert _withhold(lines, text=same_page) == {"General Liability": None, "Commercial Property": None}


# ── 8. FIELD QA EXPECTS WHAT THE STAMPER PRINTS ──────────────────────────────

def test_upload1_field_qa_raises_no_identity_failure_and_send_to_client_moves_nothing(upload1):
    _docs, (mf, _uw) = upload1
    forms = _forms(mf, ["ACORD_125", "ACORD_126", "ACORD_131", "ACORD_25"])
    qa = fqa.run_field_qa(copy.deepcopy(forms), mf, {})
    ident = re.compile(r"PolicyNumber|Insurer_FullName|NAICCode|EffectiveDate|ExpirationDate")
    fails = [(r.get("form_id"), r.get("field")) for r in qa.get("results") or []
             if r.get("verdict") == "fail" and ident.search(str(r.get("field")))]
    assert fails == []
    after = copy.deepcopy(forms)
    for g in after.values():
        g["field_state"] = dict(g["mapped"])
    arq._backfill_and_resolve_present(after, copy.deepcopy(mf))
    moved = [(fid, k) for fid, g in after.items() for k, v in g["field_state"].items()
             if ident.search(k) and str(forms[fid]["mapped"].get(k) or "") != str(v or "")]
    assert moved == []


def test_upload2_field_qa_accepts_the_proposed_term_on_the_section_forms(upload2):
    _docs, (mf, _uw) = upload2
    forms = _forms(mf, ["ACORD_126", "ACORD_131"])
    for fid, g in forms.items():
        stamped = g["mapped"].get("Policy_EffectiveDate_A")
        expected = ps.authoritative_expected_value(fid, "Policy_EffectiveDate_A", mf, g["schema"])
        assert expected == stamped, (fid, stamped, expected)


def test_the_umbrella_period_override_is_one_door():
    facts = {"umbrella_effective_date": "03/15/2026", "umbrella_expiration_date": "03/15/2027"}
    assert ps._umbrella_period_override("ACORD_131", "Policy_EffectiveDate_A", facts) == "03/15/2026"
    assert ps._umbrella_period_override("ACORD_25", "Policy_ExcessLiability_ExpirationDate_A", facts) == "03/15/2027"
    assert ps._umbrella_period_override("ACORD_126", "Policy_EffectiveDate_A", facts) is None
    assert ps.authoritative_expected_value("ACORD_131", "Policy_EffectiveDate_A", facts) == "03/15/2026"
    names = list(ps._AUTHORITATIVE_BLANK_RESOLVERS)
    assert names.index("_resolve_renewal_proposed_period") < names.index("_resolve_section_policy_identity")


# ── 9. A CALENDAR-YEAR TERM RENEWS FOR A CALENDAR YEAR ───────────────────────

@pytest.mark.parametrize("eff,exp,nxt", [
    ("2026-08-01", "2027-08-01", "2028-08-01"),    # crosses 29 Feb 2028
    ("2025-07-15", "2026-07-15", "2027-07-15"),
    ("2026-01-31", "2027-01-31", "2028-01-31"),
    ("2024-02-29", "2025-02-28", "2026-02-28"),    # not whole months: day count
    ("2026-06-01", "2026-12-01", None),            # not an annual term
])
def test_the_renewed_term_end(eff, exp, nxt):
    got = es._renewed_term_end(datetime.strptime(eff, "%Y-%m-%d"), datetime.strptime(exp, "%Y-%m-%d"))
    assert (got.strftime("%Y-%m-%d") if got else None) == nxt


# ── 10. THE PDF IS ACTUALLY FILLED ───────────────────────────────────────────

def test_no_code_uses_a_pikepdf_class_that_pikepdf_9_lacks():
    offenders = []
    for folder in ("services", "routes", "utils"):
        for root, _dirs, files in os.walk(os.path.join(BACKEND, folder)):
            for fn in files:
                if not fn.endswith(".py"):
                    continue
                with open(os.path.join(root, fn), encoding="utf-8") as fh:
                    for no, line in enumerate(fh, 1):
                        code = line.split("#", 1)[0]
                        if "pikepdf.Boolean(" in code:
                            offenders.append(f"{fn}:{no}")
    assert offenders == []


def test_fill_pdf_writes_the_value_it_is_given():
    import pikepdf
    tpl = os.path.join(BACKEND, "templates", "ACORD_126.pdf")
    with open(tpl, "rb") as fh:
        blank = fh.read()
    out = ps.fill_pdf(tpl, {"Policy_PolicyNumberIdentifier_A": QPC})
    assert out != blank
    pdf = pikepdf.open(io.BytesIO(out))
    assert bool(pdf.Root.AcroForm.get("/NeedAppearances")) is True
    values = {}
    for f in pdf.Root.AcroForm.Fields:
        stack = [f]
        while stack:
            node = stack.pop()
            if "/Kids" in node:
                stack.extend(node.Kids)
            if "/T" in node and "/V" in node:
                values[str(node.T)] = str(node.V)
    assert QPC in values.values()


def test_the_same_policy_under_a_group_name_does_not_blank_the_letter():
    """Only a DIFFERENT policy on the line competes for the INSR LTR box."""
    rows = [{"line": "General Liability", "policy_number": "BBC7263 - 26", "premium": "$4,000",
             "carrier": "EMC Property & Casualty Company", "naic": "25186"},
            {"line": "Commercial General Liability", "policy_number": "BBC7263",
             "carrier": "EMC Insurance Companies"}]
    facts = {"coverage_lines": rows, "_form_id": "ACORD_25"}
    assert ps._resolve_certificate_insurer_letter("GeneralLiability_InsurerLetterCode_A", facts) == "A"
    rows[1]["policy_number"] = "TRV-889900"                     # now a second policy
    assert ps._resolve_certificate_insurer_letter("GeneralLiability_InsurerLetterCode_A", facts) is None


# ── RETEST (17 Sep, second live run) ─────────────────────────────────────────

@pytest.mark.parametrize("numbered", [("Commercial Umbrella",), ("Commercial Auto",), ()])
def test_the_number_is_withheld_even_when_the_rows_do_not_share_it_yet(numbered):
    """The retest's extraction numbered at most ONE row. The withhold read rows
    only, found nothing shared, and the fill then copied SRC-4410982 onto Auto
    and Umbrella from the page-context entries. Sharing is decided over the rows
    AND the per-line index now."""
    docs = _live_docs("upload_2_one_number_summary")
    rows = es._fv(docs[0]["facts"], "coverage_lines")
    for r in rows:
        r["policy_number"] = SRC if r["line"] in numbered else None
    mf, _ = es.merge_facts(docs, es.select_primary_truth(docs))
    assert all(not r.get("policy_number") for r in _rows(mf)), _rows(mf)
    assert not any(SRC in nums for nums in es.current_numbers_by_line(mf.get("dec_page_entries"), mf).values())
    forms = _forms(mf, ["ACORD_126", "ACORD_131", "ACORD_25"])
    for fid, g in forms.items():
        assert SRC not in g["mapped"].values(), fid


def test_confirming_through_the_naic_card_chooses_the_same_contract(upload1):
    docs, _ = upload1
    mf, uw = _pipeline(docs, {uc.scoped_confirmation_key("carrier_naic", "general_liab"): "93518"})
    gl = [r for r in _rows(mf) if es._canon_line(r["line"]) == "general_liab" and not r.get("_set_aside")]
    assert [(r["policy_number"], r["naic"]) for r in gl] == [(LSG, "93518")]
    assert not any(r.get("naic") == "93518" and _entity(r.get("carrier")) == _entity(PC) for r in _rows(mf))
    m126 = _forms(mf, ["ACORD_126"])["ACORD_126"]["mapped"]
    assert (m126["Policy_PolicyNumberIdentifier_A"], m126["Insurer_NAICCode_A"]) == (LSG, "93518")
