"""One problem, one line on the download screen - the owner's run 0353c36b
(14 Oct 2026): "own or rent?" printed as an ACORD 125 box AND a card, the ACORD 130
officers as three boxes AND a card, and "No Known Losses attested ..." was counted
as an item to fix on all ten forms."""
import json
import pathlib
import shutil
import subprocess

import pytest

from services.needs_attention import box_fold_keys, card_fix_keys

ROOT = pathlib.Path(__file__).resolve().parents[2]
UTIL = ROOT / "frontend" / "src" / "utils" / "needsAttention.js"


def test_the_125_interest_ticks_answer_the_own_or_rent_card():
    for box in ("CommercialStructure_InsuredInterest_OwnerIndicator_A",
                "CommercialStructure_InsuredInterest_TenantIndicator_A"):
        assert "premises_interest" in box_fold_keys(box)
    assert card_fix_keys({"rec_id": "rec_premises_interest", "field": "premises_interest"}) == {"premises_interest"}


def test_the_130_officer_rows_answer_the_officer_card():
    assert "wc_officers" in box_fold_keys("WorkersCompensation_Individual_FullName_A")
    assert "wc_officers" in box_fold_keys("WorkersCompensation_Individual_FullName_C")
    assert {"wc_officer_exclusions", "wc_officers"} <= card_fix_keys(
        {"rec_id": "rec_wc_officer_exclusions", "field": "wc_officer_exclusions"})


def test_an_unrelated_box_folds_into_nothing():
    assert "premises_interest" not in box_fold_keys("NamedInsured_FullName_A")
    assert "wc_officers" not in box_fold_keys("NamedInsured_FullName_A")


@pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")
def test_the_download_list_folds_the_boxes_into_the_cards(tmp_path):
    recs = [
        {"rec_id": "rec_premises_interest", "field": "premises_interest", "fix_facts": ["premises_interest"],
         "message": "ACORD 125 premises: does the insured own or rent 4800 Washington St?"},
        {"rec_id": "rec_wc_officer_exclusions", "field": "wc_officer_exclusions",
         "fix_facts": ["wc_officer_exclusions", "wc_officers"], "message": "ACORD 130 requires owner/officer inclusion/exclusion"},
    ]
    att = {"forms": [
        {"form_id": "ACORD_125", "form_label": "ACORD 125", "rows": [
            {"field": "CommercialStructure_InsuredInterest_OwnerIndicator_A", "status": "missing",
             "fact_key": None, "fold_keys": ["premises_interest"]},
            {"field": "NamedInsured_LLCMemberCount_A", "status": "missing", "fact_key": None, "fold_keys": []}]},
        {"form_id": "ACORD_130", "form_label": "ACORD 130", "rows": [
            {"field": f"WorkersCompensation_Individual_FullName_{x}", "status": "missing",
             "fact_key": None, "fold_keys": ["wc_officers"]} for x in "ABC"]},
    ]}
    # the same loader as test_download_review_seen_earlier_14oct: Vite resolves
    # the extension-less constants import, plain node does not
    import re
    src = re.sub(r'^import \{ API_BASE \} from "\.\./config/constants";\n', 'const API_BASE = "";\n',
                 UTIL.read_text(encoding="utf-8"), flags=re.M)
    mod = tmp_path / "na.mjs"
    mod.write_text(src, encoding="utf-8")
    script = tmp_path / "f.mjs"
    script.write_text(
        f"import * as N from {json.dumps(mod.as_uri())};\n"
        f"const p = N.downloadReviewParts({json.dumps(recs)}, {json.dumps(att)});\n"
        "console.log(JSON.stringify({ missing: p.missing.map((f) => [f.form_id, f.rows.map((r) => r.field)]), recs: p.recommendations.length }));",
        encoding="utf-8")
    run = subprocess.run(["node", str(script)], capture_output=True, text=True, timeout=60)
    assert run.returncode == 0, run.stderr
    o = json.loads(run.stdout)
    assert o["recs"] == 2
    assert o["missing"] == [["ACORD_125", ["NamedInsured_LLCMemberCount_A"]]]


def test_the_start_button_says_it_is_the_first_of_several():
    # 23 Oct 2026 (Brent, Z34-1 #1): the "your last points are on the forms" notice and
    # its "Start with ... (most to confirm)" button are gone - the forms no longer hold
    # points. Each form's to-dos are on the Forms ready meter instead. The TEST pinned
    # the removed button and was updated.
    src = (ROOT / "frontend" / "src" / "components" / "form" / "review" / "ReviewRailLayout.jsx").read_text()
    assert "(most to confirm)" not in src
    assert "data-forms-ready-form={f.formId}" in src
