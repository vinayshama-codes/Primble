"""Z39 lane G (25 Oct 2026).

1. The follow-up preview reads the page ITEMS ONLY: no per-form scoring, no
   card share-out (`answer_preview._package_items_only`). The items - ids,
   labels, fixes, cards - are the same as a full reading; every other caller
   keeps the full door. Typed answers are previewed only once complete.
2. Officer titles in the other common layouts ("Jane Roe, President",
   "President: Jane Roe", "Name:" / "Title:", a TITLE column ...), never a
   carrier's signature, a duties line or a city.

Snapshots (read with a SELECT only): laneF/p.pkl (3e835b53), live26/m1.pkl.
"""
from __future__ import annotations

import copy
import json
import os
import pickle
import shutil
import subprocess
import time
from pathlib import Path
from unittest.mock import patch

import pytest

os.environ.setdefault("OPENAI_API_KEY", "sk-offline")
os.environ.setdefault("FIELD_ENCRYPTION_KEY", "kZ0aQ7Yy3pR8mN2vB6xL9tJ4hG1sD5fW8cE0uI3oA7k=")

from services import answer_preview as ap                             # noqa: E402
from services.extraction_service import _titles_printed_for, read_officer_titles  # noqa: E402

SCRATCH = Path("/private/tmp/claude-501/-Users-vinaysharma-Downloads-Primble-16thsep/"
               "427f82bb-424b-4678-bf06-9112a9013561/scratchpad")
SNAPS = [SCRATCH / "laneF" / "p.pkl", SCRATCH / "live26" / "m1.pkl"]
FRONTEND = Path(__file__).resolve().parents[2] / "frontend" / "src"
CLAIMS = "loss_history_no_prior_losses_indicator"


def _rows():
    return [pickle.load(open(p, "rb")) for p in SNAPS if p.exists()]


needs_snap = pytest.mark.skipif(not any(p.exists() for p in SNAPS), reason="snapshots not on this machine")


# ── 1. Items-only reading ─────────────────────────────────────────────────────

@needs_snap
@pytest.mark.parametrize("pick", [None, "no", "yes"])
def test_items_only_reads_exactly_the_items_of_a_full_reading(pick):
    from services.loss_history_state import claims_question_answers
    no, yes = claims_question_answers()
    for row in _rows():
        work = copy.deepcopy(row)
        if pick:
            ap.apply_answer_in_memory(work, CLAIMS, no if pick == "no" else yes)
        uid = str(row["user_id"])
        full = ap.page_items_now(work, "s", uid)
        light = ap.page_items_now(work, "s", uid, items_only=True)
        assert light == full                      # every item dict and every card id


@needs_snap
def test_only_the_preview_takes_the_light_door():
    """The default reading (every caller but the preview) still scores the
    package through `current_package_sqs`; the preview never does."""
    from services import sqs_service as S
    row = _rows()[0]
    uid = str(row["user_id"])
    real = S.current_package_sqs
    calls = []

    def spy(*a, **k):
        calls.append(1)
        return real(*a, **k)

    with patch.object(S, "current_package_sqs", spy):
        ap.page_items_now(row, "s", uid)
        assert len(calls) == 1
        ap.clear_caches()
        ap.preview_follow_ups(row, "s", uid, [(CLAIMS, "No")], [CLAIMS])
        assert len(calls) == 1


@needs_snap
@pytest.mark.parametrize("pick", ["no", "yes"])
def test_follow_ups_equal_the_full_recipe(pick):
    from services.loss_history_state import claims_question_answers
    no, yes = claims_question_answers()
    for row in _rows():
        uid = str(row["user_id"])
        ans = [(CLAIMS, no if pick == "no" else yes)]
        work = copy.deepcopy(row)
        written = []
        for f, v in ans:
            c = ap.apply_answer_in_memory(work, f, v)
            if c:
                written += [c, f]
        before, _ = ap._page_items_now(row, "s", uid)
        after, ids = ap._page_items_now(work, "s", uid)
        with patch.object(ap, "page_items_before", lambda *_a, **_k: (before, {})), \
                patch.object(ap, "page_items_now", lambda *_a, **_k: (after, ids)):
            full = ap._follow_ups(row, work, "s", uid, written, [CLAIMS], "x")
        ap.clear_caches()
        assert ap.preview_follow_ups(row, "s", uid, ans, [CLAIMS]) == full


@needs_snap
def test_the_after_reading_is_faster_than_the_full_one():
    row = pickle.load(open(SNAPS[0], "rb")) if SNAPS[0].exists() else _rows()[0]
    uid = str(row["user_id"])
    work = copy.deepcopy(row)
    ap.apply_answer_in_memory(work, CLAIMS, "No")
    ap.page_items_now(work, "s", uid, items_only=True)          # imports, text caches
    t = time.time()
    ap.page_items_now(work, "s", uid, items_only=True)
    light = time.time() - t
    t = time.time()
    ap.page_items_now(work, "s", uid)
    full = time.time() - t
    assert light < full


def test_items_only_stands_down_on_an_integrity_hold():
    assert ap._package_items_only({"integrity": {"review_required": True}}, "s", "u") is None


# ── 1b. Typed answers previewed only when complete (frontend) ─────────────────

def test_modal_previews_typed_boxes_through_the_completeness_check():
    modal = (FRONTEND / "components" / "form" / "ResolutionModal.jsx").read_text(encoding="utf-8")
    assert "previewableAnswers(nextValues, mine, ctl, typed, left)" in modal
    assert modal.count("onChange={(e) => onTyped(fact, e.target.value)}") == 2
    assert "previewAnswers(nextValues, mine)" not in modal


@pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")
def test_typed_answer_completeness(tmp_path):
    fp = (FRONTEND / "utils" / "followUpPreview.js").as_uri()
    script = tmp_path / "typed.mjs"
    script.write_text(f"""
import * as F from {json.dumps(fp)};
const c = F.typedAnswerComplete;
const out = {{
  date: [c("01/15/2027", "date"), c("2027-01-15", "date"), c("01/15/20", "date"), c("02/30/2027", "date"), c("01/1", "date")],
  num: [c("12", "number"), c("1,200", "number"), c("1,2", "number"), c("None", "number")],
  cur: [c("$1,000,000", "currency"), c("1M", "currency"), c("$", "currency"), c("None", "currency")],
  pct: [c("80", "percent"), c("80%", "percent"), c("%", "percent")],
  code: [c("238160", "code"), c("2", "code")],
  text: [c("A", "text"), c("Ab", "text"), c("", "text"), c("Other", "text")],
}};
const ctl = {{ d: {{ control: "date" }}, q: {{ control: "select", options: ["Yes", "No"] }} }};
const typed = (f) => f === "d";
out.half = F.previewableAnswers({{ d: "01/1", q: "Yes" }}, ["d", "q"], ctl, typed);
out.whole = F.previewableAnswers({{ d: "01/15/2027", q: "Yes" }}, ["d", "q"], ctl, typed);
console.log(JSON.stringify(out));
""", encoding="utf-8")
    run = subprocess.run(["node", str(script)], capture_output=True, text=True, timeout=60)
    assert run.returncode == 0, run.stderr
    o = json.loads(run.stdout)
    assert o["date"] == [True, True, False, False, False]
    assert o["num"] == [True, True, False, True]
    assert o["cur"] == [True, True, False, True]
    assert o["pct"] == [True, True, False]
    assert o["code"] == [True, False]
    assert o["text"] == [False, True, False, False]
    assert o["half"] == [{"field": "q", "value": "Yes"}]
    assert o["whole"] == [{"field": "d", "value": "01/15/2027"}, {"field": "q", "value": "Yes"}]


# ── 2. Officer titles in the other common layouts ─────────────────────────────

_COLUMN = ("Officer Name      DOB          Title             Ownership\n"
           "John Doe          01/02/1970   Secretary         40%\n"
           "Jane Roe          03/04/1975   President         60%\n")


@pytest.mark.parametrize("text,title", [
    ("Officers\nJane Roe, President\n", "President"),
    ("Jane Roe - President", "President"),
    ("Jane Roe – Vice President", "Vice President"),
    ("Jane Roe (President)", "President"),
    ("President: Jane Roe", "President"),
    ("Secretary/Treasurer: Jane Roe 50%", "Secretary/Treasurer"),
    ("Name: Jane Roe\nTitle: President\n", "President"),
    ("Officer Name: Jane Roe\n\nPosition: Managing Member", "Managing Member"),
    ("Name: Jane Roe   Title: President", "President"),
    (_COLUMN, "President"),
    ("- Jane Roe, President and CEO, 60% owner", "President and CEO"),
])
def test_each_layout_reads_the_title(text, title):
    assert _titles_printed_for("Jane Roe", [{"text": text}]) == {title}


def test_column_layout_reads_each_officers_own_cell():
    assert _titles_printed_for("John Doe", [{"text": _COLUMN}]) == {"Secretary"}


@pytest.mark.parametrize("text", [
    "Jane Roe, Denver",
    "Jane Roe, Denver, CO 80202",
    "Jane Roe, President's Day sale",
    "President's Day: Jane Roe",
    "Acme Insurance Company\nJane Roe, President\n",          # a carrier's signature
    "Jane Roe, President\nAcme Mutual Insurance Company",
    "Acme Insurance Company\nBy: ________\nName: Jane Roe\nTitle: President",
    "Duties: Jane Roe, President, oversees crews",
    "Jane Roe - supervises roofing crews",
    "Contact Jane Roe, President",                            # the name does not open the line
    "Name: Jane Roe\nName: John Doe\nTitle: President",       # the title is John Doe's
])
def test_no_title_from_a_look_alike(text):
    assert _titles_printed_for("Jane Roe", [{"text": text}]) == set()


def test_rules_of_the_door_hold_for_the_new_layouts():
    # Two layouts naming different titles: no title (one distinct only).
    mf = {"wc_officers": [{"name": "Jane Roe"}]}
    assert read_officer_titles(mf, [{"text": "Jane Roe, President"},
                                    {"text": "Name: Jane Roe\nTitle: Secretary"}]) == []
    # Agreeing layouts: one title.
    mf = {"wc_officers": [{"name": "Jane Roe"}]}
    assert read_officer_titles(mf, [{"text": "Jane Roe, President"}, {"text": "President: Jane Roe"}])
    assert mf["wc_officers"][0]["title"] == "President"
    # An excluded document and a person's table are never read.
    mf = {"wc_officers": [{"name": "Jane Roe"}]}
    assert read_officer_titles(mf, [{"text": "Jane Roe, President", "excluded": True}]) == []
    mf = {"wc_officers": {"value": [{"name": "Jane Roe"}], "source": "producer"}}
    assert read_officer_titles(mf, [{"text": "Jane Roe, President"}]) == []
    # A stated title is never replaced.
    mf = {"wc_officers": [{"name": "Jane Roe", "title": "Owner"}]}
    assert read_officer_titles(mf, [{"text": "Jane Roe, President"}]) == []


# ── Review (25 Oct 2026): checks that run on any machine ──────────────────────

_FACTS = {
    "producer_name": "Best Agency", "applicant_name": "Acme LLC",
    "mailing_address": "1 Main St, Denver, CO 80202", "effective_date": "01/01/2027",
    "lines_of_business": "General Liability", "entity_type": "LLC",
    "contact_phone": "303-555-0100", "fein": "12-3456789",
    "operations_description": "Electrical contracting", "total_revenue": "$1,200,000",
    "num_employees": "12", "years_in_business": "8", "naics_code": "238210",
}


def _mem_row(flags, forms, facts=None, **over):
    """An in-memory pre-form session row, its card copies mirrored from the
    stops door as `extraction_pipeline` stores them."""
    from services.issue_registry import make_issue
    from services.stops_now import stops_now
    row = {"facts": dict(facts if facts is not None else _FACTS), "flags": dict(flags),
           "hard_stops": [], "soft_stops": [], "cross_form_issues": [], "docs": [],
           "recommendations": [{"form_id": f} for f in forms], "integrity": {},
           "generated_forms": {}, "underwriting_consistency": {}, "user_id": "u"}
    st = stops_now(row, forms, pre_form=True, facts=row["facts"], flags=row["flags"])
    row["structured_issues"] = [
        make_issue(i.get("code"), i.get("type"), i.get("message", ""), i.get("forms"),
                   add_forms=(i.get("resolution") or {}).get("add_forms"))
        for i in st["cross_issues"]]
    row.update(over)
    return row


_SHAPES = [
    # A form choice (ACORD 186 for a contractor) - listed for form selection,
    # never a card. The light reading drew it as a card until this review.
    ({"has_general_liability": True, "is_contractor": True}, ["ACORD_125", "ACORD_126"], None),
    ({"has_general_liability": True, "has_auto_coverage": True},
     ["ACORD_125", "ACORD_126", "ACORD_127"], None),
    # A hard stop open: no proposed term.
    ({"has_general_liability": True}, ["ACORD_125", "ACORD_126"],
     {k: v for k, v in _FACTS.items() if k != "effective_date"}),
]


@pytest.mark.parametrize("flags,forms,facts", _SHAPES)
def test_items_only_equals_a_full_reading_in_memory(flags, forms, facts):
    row = _mem_row(flags, forms, facts)
    full = ap.page_items_now(row, "s", "u")
    light = ap.page_items_now(row, "s", "u", items_only=True)
    assert full[0], "the shape reads no items - the check would pass vacuously"
    assert [ap._ident(i) for i in light[0]] == [ap._ident(i) for i in full[0]]
    assert light[1] == full[1]


def test_a_hard_stop_shape_really_has_one():
    row = _mem_row({"has_general_liability": True}, ["ACORD_125", "ACORD_126"],
                   {k: v for k, v in _FACTS.items() if k != "effective_date"})
    from services.stops_now import stops_now
    assert stops_now(row, ["ACORD_125", "ACORD_126"], pre_form=True)["hard"]


def test_items_only_after_forms_and_on_a_hold_reads_as_the_full_door():
    after = _mem_row({"has_general_liability": True}, ["ACORD_125"],
                     generated_forms={"ACORD_125": {}}, package_sqs={})
    assert ap.page_items_now(after, "s", "u", items_only=True) == ap.page_items_now(after, "s", "u")
    hold = _mem_row({"has_general_liability": True}, ["ACORD_125"],
                    integrity={"review_required": True})
    assert ap.page_items_now(hold, "s", "u", items_only=True) == ([], {})
    assert ap.page_items_now(hold, "s", "u") == ([], {})


_TWO_PAIRS = ("Name       Title          Name       Title\n"
              "Jane Roe   President      John Doe   Secretary\n")
_DUTIES = ("Officer Name      Duties           Title\n"
           "Jane Roe          Manager          \n")


def test_a_second_officer_pair_on_a_row_reads_its_own_title():
    assert _titles_printed_for("Jane Roe", [{"text": _TWO_PAIRS}]) == {"President"}
    assert _titles_printed_for("John Doe", [{"text": _TWO_PAIRS}]) == {"Secretary"}


def test_a_cell_under_another_column_is_never_the_title():
    assert _titles_printed_for("Jane Roe", [{"text": _DUTIES}]) == set()
    both = "Officer Name      Duties           Title\nJane Roe          Manager          President\n"
    assert _titles_printed_for("Jane Roe", [{"text": both}]) == {"President"}


@pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")
def test_typed_answers_a_review_found_unread(tmp_path):
    fp = (FRONTEND / "utils" / "followUpPreview.js").as_uri()
    script = tmp_path / "typed2.mjs"
    script.write_text(f"""
import * as F from {json.dumps(fp)};
const c = F.typedAnswerComplete;
console.log(JSON.stringify({{
  whole: [c("(303) 555-1212", "code"), c("303 555 1212", "code"), c("BBC 7263-26", "code"),
          c("0.5", "number"), c("1.08", "number"), c("0", "currency"), c("$1,000.50", "currency"),
          c("0", "number")],
  half: [c("$2,5", "currency"), c("1,", "currency"), c("$1.", "currency"), c("2,50", "amount_or_percent"),
         c("1.", "number")],
}}));
""", encoding="utf-8")
    run = subprocess.run(["node", str(script)], capture_output=True, text=True, timeout=60)
    assert run.returncode == 0, run.stderr
    o = json.loads(run.stdout)
    assert o["whole"] == [True] * 8
    assert o["half"] == [False] * 5
