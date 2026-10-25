"""Brent's answers of 19 Oct 2026, part B - WC / EL vs EBL, and the source and
page of every coverage and limit (25sepChanges.md part Z28).

  * "Extract WC class codes, payroll, rates, experience mod and endorsements
    from the supporting schedules": the WC policy's ENDORSEMENT SCHEDULE is
    data (`services/wc_endorsements.py`) - ACORD 130's one-line "SPECIFY
    ADDITIONAL COVERAGES / ENDORSEMENTS (Attach ACORD 101 ...)" box points to
    the ACORD 101 block that lists it, with its source and pages;
  * "Never interchange EL and EBL; never infer EBL": the umbrella's EXCLUDED
    employee benefits never ticks the 131's underlying EBL box;
  * "Keep the source and page reference for every extracted coverage and
    limit": the policies table and the Data Consistency values name the page
    that prints them (`fact_lineage.locate_page`) - never a guess.
"""
import copy
import json
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
os.environ.setdefault("OPENAI_API_KEY", "sk-offline-test")

import services.pdf_service as ps                          # noqa: E402
from services import fact_lineage as fl                    # noqa: E402
from services import policy_lines as pl                    # noqa: E402
from services import wc_endorsements as wce                # noqa: E402

HERE = os.path.dirname(__file__)
WC_DOC = "25-26 Workers Compensation Policy.pdf"


@pytest.fixture(scope="module")
def docs():
    with open(os.path.join(HERE, "fixtures", "choice_electric_pol_6oct.json"), encoding="utf-8") as fh:
        return json.load(fh)["docs"]


@pytest.fixture(scope="module")
def merged(docs):
    from services.extraction_service import merge_facts, select_primary_truth
    mf, flags = merge_facts(copy.deepcopy(docs), select_primary_truth(docs))
    return mf, flags


def _wc_doc(text, name="wc.pdf"):
    return {"filename": name, "text": text,
            "facts": {"coverage_lines": [{"line": "Workers Compensation and Employers Liability"}]}}


# ══ 1. The WC endorsement schedule ═════════════════════════════════════════

class TestEndorsementSchedule:
    def test_choice_electric_schedule_is_read_with_its_pages(self, merged):
        mf, _ = merged
        rows = mf["_wc_endorsements"]
        assert len(rows) == 23
        assert rows[0] == {"state": "CW", "number": "AN6060", "title": "Workers' Compensation Posting Notices",
                           "edition": "03_20", "source": WC_DOC, "page": 5}
        waiver = next(r for r in rows if r["number"] == "WC000313")
        assert waiver["title"] == "Waiver Of Our Right To Recover From Others Endorsement"
        # the wrapped description is whole (the table row, not the page line)
        ownership = next(r for r in rows if r["number"] == "WC000414A")
        assert ownership["title"].endswith("Change In Ownership Endorsement")
        assert rows[-1]["number"] == "RM 1020" and rows[-1]["page"] == 6
        assert rows[-1]["edition"] == "06 18"
        # the page footer ("Issue Date 12/13/2024 | Insured Copy") is no form
        assert not any("Issue" in r["number"] or "12/13" in r["number"] for r in rows)

    def test_the_130_box_points_to_the_101_with_the_source(self, merged):
        mf, flags = merged
        f = {**mf, **flags, "_form_id": "ACORD_130"}
        assert ps._deterministic_map(wce.BOX, f) == (
            "Endorsement schedule (23 forms) - see ACORD 101; source: "
            "25-26 Workers Compensation Policy.pdf pages 5-6")

    def test_the_101_lists_the_schedule_for_the_130(self, merged):
        mf, flags = merged
        f = {**mf, **flags, "_form_id": "ACORD_101",
             "_package_form_ids": ["ACORD_125", "ACORD_130", "ACORD_101"]}
        text = ps._resolve_acord101_box("AdditionalRemark_RemarkText_A", f)
        assert wce.BLOCK_HEADING + " - 23 forms, 25-26 Workers Compensation Policy.pdf pages 5-6:" in text
        assert "CW WC000313 Waiver Of Our Right To Recover From Others Endorsement (04_84)" in text
        assert ps._resolve_acord101_box("AdditionalRemark_FormIdentifier_A", f) == "125, 130"
        assert ps._resolve_acord101_box("AdditionalRemark_FormName_A", f) == \
            "COMMERCIAL INSURANCE APPLICATION; WORKERS COMPENSATION APPLICATION"
        # without ACORD 130 in the package the 101 does not continue it
        f["_package_form_ids"] = ["ACORD_125", "ACORD_101"]
        assert wce.BLOCK_HEADING not in ps._resolve_acord101_box("AdditionalRemark_RemarkText_A", f)
        assert ps._resolve_acord101_box("AdditionalRemark_FormIdentifier_A", f) == "125"

    def test_the_schedule_never_reaches_the_gap_fill_prompt(self):
        assert wce.KEY in ps._GAP_FILL_FACTS_EXCLUDE

    def test_a_package_with_the_130_and_no_101_is_offered_the_101(self, merged):
        from services.cross_form_validator import _check_expiring_policies_need_acord101 as rule
        mf, flags = merged
        out = rule(mf, flags, {"ACORD_130"})
        assert len(out) == 1 and "endorsement schedule (23 forms)" in out[0]["message"]
        assert out[0]["message"].startswith("ACORD 130 points to ACORD 101")
        assert rule(mf, flags, {"ACORD_130", "ACORD_101"}) == []

    def test_ncci_lines_are_read_without_a_table(self):
        text = ("[Document page 1]\nINFORMATION PAGE\n[Document page 2]\nSCHEDULE OF FORMS AND ENDORSEMENTS\n"
                "WC 00 03 13 Waiver Of Our Right To Recover From Others 04 84\n"
                "CO WC 05 04 03 Colorado Premium Credit Endorsement 03-93\n"
                "AN6060 Workers' Compensation Posting Notices 03_20\n")
        rows = wce.read_endorsement_schedule([_wc_doc(text)])
        assert [(r["state"], r["number"], r["page"]) for r in rows] == [
            ("", "WC 00 03 13", 2), ("CO", "WC 05 04 03", 2)]   # a carrier's own number needs the table

    def test_only_the_wc_policys_own_schedule_pages(self):
        table = "[Table - page 1 - DATE]\nCW | WC000313 | Waiver Of Our Right To Recover From Others | 04_84\n[End table]\n"
        no_heading = "[Document page 1]\nCLASSIFICATION SCHEDULE\n" + table
        assert wce.read_endorsement_schedule([_wc_doc(no_heading)]) == []
        gl_doc = {"filename": "gl.pdf", "text": "[Document page 1]\nENDORSEMENT SCHEDULE\n" + table,
                  "facts": {"coverage_lines": [{"line": "Commercial General Liability"}]}}
        assert wce.read_endorsement_schedule([gl_doc]) == []
        ok = "[Document page 1]\nENDORSEMENT SCHEDULE\n" + table
        excluded = dict(_wc_doc(ok), excluded=True)
        assert wce.read_endorsement_schedule([excluded]) == []
        assert len(wce.read_endorsement_schedule([_wc_doc(ok), _wc_doc(ok, "copy.pdf")])) == 1

    @pytest.mark.parametrize("cells", [
        ["Issue Date 12/13/2024", "Insured Copy", "", ""],         # a footer
        ["CW", "WC000313", "Waiver"],                            # no edition, one-word title
        ["CW", "", "Waiver Of Our Right", "04_84"],               # no number
        ["CW", "12/13/2024", "Issue Date Copy", "04_84"],        # a date is no form number
        ["CW", "WC000313", "Waiver Of Our Right", "Insured Copy"],
    ])
    def test_a_row_that_is_not_a_form_is_never_read(self, cells):
        assert wce._table_row(cells) is None

    def test_no_schedule_no_box_no_block(self):
        f = {"_form_id": "ACORD_130"}
        assert ps._resolve_wc_endorsement_box(wce.BOX, f) is ps._SCHED_SKIP
        assert wce.schedule_block({}) is None and wce.box_text({}) is None
        mf = {wce.KEY: [{"number": "X1"}]}
        wce.derive_wc_endorsements(mf, [])
        assert wce.KEY not in mf                                  # idempotent: re-read every merge


# ══ 2. EL vs EBL ════════════════════════════════════════════════════════════

def test_the_umbrellas_excluded_ebl_never_ticks_the_131(docs, merged):
    """The umbrella's SCHEDULE OF UNDERLYING INSURANCE prints "EXCLUDED Employee
    Benefits": an AI "Y" for the 131's underlying EBL box, or an EBL limit on
    its EBL section, never prints (Brent: "never infer EBL")."""
    from services import form_instances as fi
    from services import form_service as fs
    mf, flags = merged
    package = {"facts": mf, "flags": flags, "docs": copy.deepcopy(docs),
               "all_forms": fs.filter_available_forms(fs.load_all_forms()),
               "selected_form_ids": ["ACORD_125", "ACORD_131"]}
    ai = {"UnderlyingCoverage_Coverage_EmployeeBenefitsLiabilityIndicator_A": "Y",
          "ExcessUmbrella_EmployeeBenefits_EachEmployeeLimitAmount_A": "$1,000,000"}
    meta = fi.form_meta_for(package["all_forms"], "ACORD_131", mf)
    res = fs.process_single_form(meta, package, {"filled_values": dict(ai), "raw_text_fields": set(),
                                                 "question_grounding": {}})
    for box in ai:
        assert not res["mapped"].get(box), box


def test_acord_130_has_no_employee_benefits_box_and_the_126_never_takes_el(merged):
    schema130 = json.load(open(os.path.join(HERE, "..", "forms_schemas", "ACORD_130_schema.json")))
    assert not [f for f in schema130 if "EmployeeBenefit" in f]
    mf, flags = merged
    f126 = {**mf, **flags, "_form_id": "ACORD_126"}
    val = ps._deterministic_map("GeneralLiability_EmployeeBenefits_LimitAmount_A", f126)
    assert val in (None, "UNMATCHED") or not str(val).strip()


# ══ 3. Source and page ═════════════════════════════════════════════════════

class TestLocatePage:
    TEXT = ("[Document page 1]\nCOMMON DECLARATIONS\nINLAND MARINE $ 1,425.00\n"
            "[Document page 2]\nEMPLOYEE BENEFIT LIABILITY COVERAGE PART $ 425.00\n"
            "[Document page 3]\nGENERAL LIABILITY EACH OCCURRENCE $1,000,000\n")

    def test_an_amount_only_as_the_same_number(self):
        assert fl.locate_page(self.TEXT, "425.00", ["Employee Benefit"]) == 2   # never 1,425.00
        assert fl.locate_page(self.TEXT, "1,425.00") == 1
        assert fl.locate_page(self.TEXT, "$1,000,000") == 3
        assert fl.locate_page(self.TEXT, "1000000.00") == 3
        # a figure under $1,000 is too common to cite without its line's name
        assert fl.locate_page(self.TEXT, "425.00") is None

    def test_near_words_must_share_the_page(self):
        assert fl.locate_page(self.TEXT, "$1,000,000", ["General Liability"]) == 3
        assert fl.locate_page(self.TEXT, "$1,000,000", ["Inland Marine"]) is None

    def test_no_markers_short_values_and_absences_claim_nothing(self):
        assert fl.locate_page("INLAND MARINE $ 1,425.00", "1,425.00") is None
        assert fl.locate_page(self.TEXT, "CO") is None
        assert fl.locate_page(self.TEXT, "Crime and Fidelity") is None
        assert fl.locate_page("", "x") is None and fl.locate_page(self.TEXT, None) is None


def test_the_policies_table_cites_each_source_page_and_limit(docs, merged):
    mf, _ = merged
    rows = {r["id"]: r for r in pl.table_rows(mf, docs)}
    ebl = rows["employee_benefits#unnumbered"]
    assert ebl["source_refs"] == [{"file": "25-26 Package Policy.pdf", "page": 1}]
    wc = rows["workers_comp#unnumbered"]
    assert wc["source_refs"] == [{"file": WC_DOC, "page": 1}]
    assert all(p.get("page") == 1 and p.get("file") == WC_DOC for p in wc["limit_parts"])
    # the GL limits the package dec does not print are cited where they are:
    # the umbrella's schedule of underlying insurance
    gl = rows["general_liab#unnumbered"]
    assert {p.get("file") for p in gl["limit_parts"]} == {"25-26 Umbrella Policy.pdf"}
    # no documents, no pages (old callers)
    assert "source_refs" not in pl.table_rows(mf)[0]


def test_data_consistency_values_name_their_page(docs, merged):
    from services.underwriting_consistency import assess_underwriting_consistency
    mf, flags = merged
    uw = assess_underwriting_consistency(docs, mf, {}, flags=flags)
    srcs = [s for f in uw["fields"] for v in f.get("values") or [] for s in v.get("sources") or []
            if s.get("source_method") in ("llm", "coverage_line", "text_scan")]
    assert srcs and sum(1 for s in srcs if s.get("page")) >= len(srcs) - 2
    eff = [s for f in uw["fields"] if f["fact_key"] == "effective_date"
           for v in f["values"] for s in v["sources"] if s.get("filename") == WC_DOC]
    assert eff and eff[0]["page"] == 1


def test_the_policy_line_store_never_reaches_the_gap_fill_prompt(docs, monkeypatch):
    """improving-ll.md C108: the policies table's store (edits, and the agent's
    pick for the 125 Other column - who and when) rode every gap-fill call's
    facts block. Recorded on the REAL `combined_gap_fill` (client swapped for a
    recorder): the store, the pick and the user id are out; the line records
    the edits were applied to are still in."""
    import threading
    from services.extraction_service import merge_facts, select_primary_truth

    class _Rec:
        def __init__(self):
            self.calls, self._l = [], threading.Lock()
            self.chat = self.completions = self

        def create(self, **kw):
            with self._l:
                self.calls.append(next((m["content"] for m in kw.get("messages") or []
                                        if m["role"] == "user"), ""))
            msg = type("M", (), {"content": '{"values": {}, "raw_text_sourced": [], "question_grounding": {}}'})
            return type("R", (), {"choices": [type("C", (), {"message": msg})()], "usage": None})()

    rec = _Rec()
    monkeypatch.setattr(ps, "_get_openai_form_fill_client_sync", lambda: rec)
    mf, flags = merge_facts(copy.deepcopy(docs), select_primary_truth(docs))
    facts = {**mf, **(flags or {})}
    store, _a = pl.plan_change({"facts": facts}, "prior_other", edit_key="cyber#unnumbered", user="user-123")
    facts[pl.STORE_KEY] = store
    schema = json.load(open(os.path.join(HERE, "..", "forms_schemas", "ACORD_130_schema.json")))
    _m, unmatched, _ = ps.compute_form_gaps("ACORD_130", schema, {**facts, "_form_id": "ACORD_130"})
    ps.combined_gap_fill({"ACORD_130": dict(list(unmatched.items())[:5])}, facts, "x" * 2000)
    assert rec.calls
    block = rec.calls[0][rec.calls[0].find("=== EXTRACTED FACTS"):rec.calls[0].find("=== END EXTRACTED FACTS")]
    assert block
    for needle in (pl.STORE_KEY, "prior_other", "user-123"):
        assert needle not in block, needle
    assert pl.STORE_KEY in ps._GAP_FILL_FACTS_EXCLUDE
