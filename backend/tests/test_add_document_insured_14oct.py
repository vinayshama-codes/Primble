"""Fix B (owner, 14 Oct 2026, run `f83757cf`) - what the Documents list says
about a document, what the add-document message says, and what another
insured's document may do to the forms.

  B1  "after adding the tag is showing 'strong match' even if they are from
      different insured, why": the pill measured how sure we are of the
      document's TYPE. It now says so ("Type: sure"), and a SEPARATE insured
      tag - decided by the backend (`services/document_tags.py`), never by
      comparing names in JS - reads "Different insured: <NAME>" (plus "- kept
      by you" after the producer's override) on a document naming another
      insured than the package's applicant.
  B2  "i added a filled acord form and it was picked not as a acord form but
      commercial insurance application, why": the type stays "application"
      (an ACORD 125's printed title IS that); the label names the printed form
      - "Commercial Insurance Application (ACORD 125)" - read by the
      recommender's own stamp detector.
  B3  Choice Electric #25: "No new issues on the review page." beside a new
      warning (one in, one out) and a score that fell 99 -> 85. The review
      page is now compared BY IDENTITY, with the package score.
  B4  control_dec.pdf (MERIDIAN FABRICATION INC) added to the Choice Electric
      package: the new-document AI fill wrote 8 boxes. Another insured's
      document now only SUGGESTS.

The stored-row figures quoted here were replayed read-only from the saved
`f83757cf` row (wf14/B/scripts/measure_b3.py, measure_b4.py).
"""
from __future__ import annotations

import ast
import asyncio
import copy
import json
import shutil
import subprocess
from pathlib import Path

import pytest

import routes.form_routes as fr
import routes.session_documents_routes as sdr
import services.document_tags as dtags
import services.needs_attention as na
import services.session_documents as sd

import test_new_document_fill_7oct as tnd
from test_new_document_fill_7oct import env  # noqa: F401  (the shared fill fixture)

BACKEND = Path(__file__).resolve().parents[1]
FRONTEND = BACKEND.parent / "frontend" / "src"


def run(coro):
    return asyncio.run(coro)


# ── The f83757cf integrity record, as stored (ids shortened) ────────────────

def F837_INTEGRITY(overridden=True):
    return {
        "status": "low",
        "clusters": [
            {"label": "CHOICE ELECTRIC LLC", "doc_ids": ["umb", "bap"], "cluster_id": 0},
            {"label": "MERIDIAN FABRICATION INC", "doc_ids": ["ctl"], "cluster_id": 1},
        ],
        "override": ({"action": "continue_anyway",
                      "acknowledged_entities": ["CHOICE ELECTRIC LLC", "MERIDIAN FABRICATION INC"]}
                     if overridden else None),
        "overridden": overridden,
        "documents": [
            {"doc_id": "cyber", "filename": "25-26 Cyber Policy.pdf", "applicant": "(no applicant name detected)"},
            {"doc_id": "pkg", "filename": "25-26 Package Policy.pdf", "applicant": "(no applicant name detected)"},
            {"doc_id": "umb", "filename": "25-26 Umbrella Policy.pdf", "applicant": "CHOICE ELECTRIC LLC"},
            {"doc_id": "bap", "filename": "25-26 Business Auto Policy.pdf", "applicant": "CHOICE ELECTRIC LLC"},
            {"doc_id": "a125", "filename": "ACORD_125_FILLED 2.pdf", "applicant": "(no applicant name detected)"},
            {"doc_id": "ctl", "filename": "control_dec.pdf", "applicant": "MERIDIAN FABRICATION INC"},
        ],
        "detected_entities": ["CHOICE ELECTRIC LLC", "MERIDIAN FABRICATION INC"],
    }


# ══ B2. The type label names the printed ACORD form ══════════════════════════

ACORD125_TEXT = ("COMMERCIAL INSURANCE APPLICATION\nAPPLICANT INFORMATION SECTION\n"
                 "see ACORD 45 for more Additional Interests\nACORD 125 (2025/03)\n")


@pytest.mark.parametrize("doc,label", [
    ({"doc_type": "application", "text": ACORD125_TEXT}, "Commercial Insurance Application (ACORD 125)"),
    ({"doc_type": "certificate", "text": "CERTIFICATE OF LIABILITY INSURANCE\nACORD 25 (2016/03)"},
     "Certificate of Insurance (ACORD 25)"),
    ({"doc_type": "acord_form", "text": "EVIDENCE OF COMMERCIAL PROPERTY INSURANCE ACORD 28 (2016/03)"}, "ACORD 28"),
    ({"doc_type": "supplemental_application",
      "text": "ACORD 126 (2016/09)\nACORD 125 (2016/03)\nACORD 137 CO (2017/09)"},
     "Supplemental Application (ACORD 125, ACORD 126, ACORD 137 CO)"),
    # a bare cross-reference is not the form's own stamp
    ({"doc_type": "dec_page", "text": "Additional insureds: see ACORD 45"}, "Dec Page"),
    # a stamp of a form this system does not carry names nothing
    ({"doc_type": "acord_form", "text": "ACORD 45 (2016/03)"}, "ACORD Form"),
    ({"doc_type": "application", "text": ""}, "Commercial Insurance Application"),
    ({"doc_type": "application", "text": 12345}, "Commercial Insurance Application"),
    ({"doc_type": None}, "Unknown"),
    (None, "Unknown"),
])
def test_the_label_names_the_printed_form(doc, label):
    assert dtags.document_type_label(doc) == label


def test_the_label_never_changes_the_type_and_reuses_the_one_detector():
    doc = {"doc_type": "application", "text": ACORD125_TEXT, "classification": {"confidence": "high"}}
    row = fr._doc_summary_entry(doc)
    assert row["doc_type"] == "application"                       # rules key on the type
    assert row["doc_type_label"] == "Commercial Insurance Application (ACORD 125)"
    src = (BACKEND / "services" / "document_tags.py").read_text(encoding="utf-8")
    assert "_detect_uploaded_acord_forms" in src
    # never a second stamp reader
    assert "re.compile" not in src and "ACORD[" not in src


def test_the_review_data_window_uses_the_same_label():
    src = ast.get_source_segment((BACKEND / "routes" / "form_routes.py").read_text(encoding="utf-8"), next(
        n for n in ast.walk(ast.parse((BACKEND / "routes" / "form_routes.py").read_text(encoding="utf-8")))
        if isinstance(n, ast.AsyncFunctionDef) and n.name == "get_document_extracted_data"))
    assert "document_type_label(doc)" in src and "DOC_TYPE_LABELS.get(" not in src


# ══ B1. Whose document it is ═════════════════════════════════════════════════

def test_f83757cf_control_dec_reads_different_insured_kept_by_you():
    st = dtags.document_insured_statuses(F837_INTEGRITY())
    assert st["ctl"] == {"state": "different", "name": "MERIDIAN FABRICATION INC", "kept_by_you": True}
    assert st["umb"] == st["bap"] == {"state": "same"}
    for nobody in ("cyber", "pkg", "a125"):
        assert st[nobody] == {"state": "none"}                    # never judged
    assert dtags.package_applicant(F837_INTEGRITY())["name"] == "CHOICE ELECTRIC LLC"


def test_without_the_override_it_is_not_kept_by_you():
    st = dtags.document_insured_statuses(F837_INTEGRITY(overridden=False))
    assert st["ctl"] == {"state": "different", "name": "MERIDIAN FABRICATION INC", "kept_by_you": False}


def _three(names, clusters=None):
    docs = [{"doc_id": f"d{i}", "applicant": n} for i, n in enumerate(names)]
    out = {"documents": docs}
    if clusters is not None:
        out["clusters"] = clusters
    return out


def test_the_cluster_with_the_most_documents_is_the_applicant_and_a_tie_goes_to_the_earliest():
    integ = _three(["MERIDIAN FABRICATION INC", "CHOICE ELECTRIC LLC", "MERIDIAN FABRICATION INC"],
                   [{"label": "MERIDIAN FABRICATION INC", "doc_ids": ["d0", "d2"]},
                    {"label": "CHOICE ELECTRIC LLC", "doc_ids": ["d1"]}])
    st = dtags.document_insured_statuses(integ)
    assert st["d1"]["state"] == "different" and st["d0"]["state"] == st["d2"]["state"] == "same"
    tie = _three(["CHOICE ELECTRIC LLC", "MERIDIAN FABRICATION INC"])          # no clusters stored
    st = dtags.document_insured_statuses(tie)
    assert st["d0"] == {"state": "same"}
    assert st["d1"]["state"] == "different" and st["d1"]["name"] == "MERIDIAN FABRICATION INC"


def test_a_confirmed_applicant_decides_between_the_groups():
    integ = _three(["MERIDIAN FABRICATION INC", "CHOICE ELECTRIC LLC", "MERIDIAN FABRICATION INC"],
                   [{"label": "MERIDIAN FABRICATION INC", "doc_ids": ["d0", "d2"]},
                    {"label": "CHOICE ELECTRIC LLC", "doc_ids": ["d1"]}])
    by_map = dtags.document_insured_statuses(integ, {"applicant_name": "CHOICE ELECTRIC LLC"})
    by_card = dtags.document_insured_statuses(integ, None, {"fields": [
        {"fact_key": "applicant_name", "status": "confirmed", "confirmed_value": "Choice Electric, LLC"}]})
    for st in (by_map, by_card):
        assert st["d1"] == {"state": "same"}
        assert st["d0"]["state"] == st["d2"]["state"] == "different"


def test_a_confirmed_name_no_document_prints_never_tags_the_applicants_own_documents():
    """The one door calls "Choice Electric" and "CHOICE ELECTRIC LLC" two
    companies; a typed confirmation that matches no document falls back to
    the documents' own majority instead of tagging every document."""
    integ = F837_INTEGRITY()
    st = dtags.document_insured_statuses(integ, {"applicant_name": "Choice Electric"})
    assert st["umb"] == st["bap"] == {"state": "same"}
    assert st["ctl"]["state"] == "different"


def test_a_one_document_package_and_documents_naming_nobody():
    one = {"documents": [{"doc_id": "x", "applicant": "MERIDIAN FABRICATION INC"}], "clusters": []}
    assert dtags.document_insured_statuses(one) == {"x": {"state": "same"}}
    nobody = {"documents": [{"doc_id": "x", "applicant": "(no applicant name detected)"},
                            {"doc_id": "y", "applicant": "S.B. MO."},              # a heading, not a party
                            {"doc_id": "z", "applicant": "Named Insured"}]}
    assert dtags.document_insured_statuses(nobody) == {k: {"state": "none"} for k in "xyz"}
    assert dtags.package_applicant(nobody) is None


@pytest.mark.parametrize("integrity", [
    None, {}, "low", [], {"documents": "control_dec.pdf"}, {"documents": [None, 3, "x"]},
    {"documents": [{"applicant": "MERIDIAN FABRICATION INC"}]},                     # no doc id
])
def test_no_or_malformed_integrity_record_says_nothing(integrity):
    assert dtags.document_insured_statuses(integrity) == {}
    assert dtags.session_insured_statuses({"integrity": integrity}) == {}
    assert dtags.other_insured_of({}, ["x"]) is None


def test_malformed_clusters_and_override_are_never_iterated_as_text():
    integ = F837_INTEGRITY()
    integ["clusters"] = [{"label": "CHOICE ELECTRIC LLC", "doc_ids": "umb"}, "x", None]
    integ["override"] = {"acknowledged_entities": "MERIDIAN FABRICATION INC"}        # a string, not a list
    st = dtags.document_insured_statuses(integ)
    assert st["ctl"] == {"state": "different", "name": "MERIDIAN FABRICATION INC", "kept_by_you": False}
    assert st["umb"] == st["bap"] == {"state": "same"}
    integ["override"] = "continue_anyway"
    assert dtags.document_insured_statuses(integ)["ctl"]["kept_by_you"] is False


def test_judged_without_the_new_documents_two_cannot_outvote_the_package():
    """The fill asks about the documents being added with the applicant
    decided WITHOUT them: two MERIDIAN decs added to a package holding one
    CHOICE dec are another insured's, although they are the majority."""
    integ = _three(["CHOICE ELECTRIC LLC", "MERIDIAN FABRICATION INC", "MERIDIAN FABRICATION INC"],
                   [{"label": "CHOICE ELECTRIC LLC", "doc_ids": ["d0"]},
                    {"label": "MERIDIAN FABRICATION INC", "doc_ids": ["d1", "d2"]}])
    full = dtags.document_insured_statuses(integ)
    assert full["d0"]["state"] == "different"                     # the list's rule: the majority
    judged = dtags.document_insured_statuses(integ, judge_without=["d1", "d2"])
    assert judged["d0"] == {"state": "same"}
    assert dtags.other_insured_of(judged, ["d1", "d2"]) == "MERIDIAN FABRICATION INC"
    assert dtags.different_insured_ids(judged, ["d1", "d2", "d0"]) == ["d1", "d2"]
    # nothing else names anybody: the new documents cannot be judged
    alone = _three(["(no applicant name detected)", "MERIDIAN FABRICATION INC"])
    assert dtags.other_insured_of(dtags.document_insured_statuses(alone, judge_without=["d1"]), ["d1"]) is None


def test_a_new_document_in_the_applicants_own_integrity_group_is_the_applicants():
    """Integrity grouped them (same FEIN); the one door alone would call the
    names two companies. The group decides - no false 'different'."""
    integ = {"documents": [{"doc_id": "old", "applicant": "CHOICE ELECTRIC LLC"},
                           {"doc_id": "new", "applicant": "Choice Electric"}],
             "clusters": [{"label": "CHOICE ELECTRIC LLC", "doc_ids": ["old", "new"]}]}
    st = dtags.document_insured_statuses(integ, judge_without=["new"])
    assert st == {"old": {"state": "same"}, "new": {"state": "same"}}


def test_every_document_summary_goes_through_the_one_door():
    """Each response's doc_summary carries `insured_status`: every
    `_doc_summary_entry` call in form_routes is inside `_doc_summaries`."""
    src = (BACKEND / "routes" / "form_routes.py").read_text(encoding="utf-8")
    tree = ast.parse(src)
    owners = []
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            seg = ast.get_source_segment(src, node) or ""
            if "_doc_summary_entry(" in seg and node.name not in ("_doc_summary_entry",):
                owners.append(node.name)
    assert owners == ["_doc_summaries"], owners
    rows = fr._doc_summaries([{"doc_id": "ctl", "filename": "control_dec.pdf", "doc_type": "dec_page"},
                              {"doc_id": "umb", "filename": "u.pdf", "doc_type": "dec_page"},
                              {"doc_id": "new", "filename": "n.pdf", "doc_type": "narrative"}, "x"],
                             "u.pdf", F837_INTEGRITY())
    by = {r["doc_id"]: r for r in rows}
    assert by["ctl"]["insured_status"]["state"] == "different"
    assert by["umb"]["insured_status"] == {"state": "same"} and by["umb"]["is_primary"]
    assert by["new"]["insured_status"] is None                    # not assessed (yet)
    assert all(r["insured_status"] is None for r in fr._doc_summaries([{"doc_id": "a"}], "", None))


# ══ B3. New on the review page, by identity, with the score ══════════════════

def _page(hard=(), warn=(), dc=(), score=None, counts=True):
    def cl(items):
        return [{"cluster": "c", "issue_id": i[0], "primary_message": i[2], "count": 1,
                 "items": [{"issue_id": i[0], "code": i[1], "message": i[2], "forms": []}]} for i in items]
    grouped = {"hard_stops": cl(hard), "warnings": {"required": cl(warn), "recommended": [], "binder_followup": []}}
    if counts:
        grouped["counts"] = {"hard_stops": len(hard), "warnings": len(warn)}
    page = {"grouped_issues": grouped,
            "underwriting_consistency": {"fields": [{"fact_key": k, "status": s} for k, s in dc]}}
    if score is not None:
        page["package_sqs"] = {"package_sqs_score": score}
    return page


EMPLOYEE = ("iss_c828acd9d9ec", "underwriting_stamp_mismatch",
            "Employee Count appears inconsistently across generated forms (ACORD 125).")
DRIVERS = ("iss_8bfe1f76751e", "legacy_auto_driver_schedule_missing",
           "Driver schedule not provided - list the drivers of the scheduled vehicles")


def test_choice_electric_25_one_in_one_out_is_one_new_warning_and_the_score_says_so():
    """The stored f83757cf rows, replayed: before the Business Auto Policy the
    page held one warning, after it one different warning; 99 -> 85."""
    before, after = _page(warn=[EMPLOYEE], score=99), _page(warn=[DRIVERS], score=85)
    old = sd.new_on_review(sd.review_counts(before), sd.review_counts(after))
    assert old["total"] == 0                                      # the "No new issues" the owner saw
    new = sd.new_on_review(sd.review_snapshot(before), sd.review_snapshot(after))
    assert new == {"hard_stops": 0, "warnings": 1, "data_consistency": 0, "total": 1,
                   "score_before": 99, "score_after": 85}


def test_a_rule_firing_under_new_words_is_not_new_but_a_second_one_is():
    a = ("iss_a", "legacy_minimum_viable_cope", "Minimum Viable COPE incomplete - missing: occupancy, roof year")
    a2 = ("iss_a2", "legacy_minimum_viable_cope", "Minimum Viable COPE incomplete - missing: occupancy")
    a3 = ("iss_a3", "legacy_minimum_viable_cope", "Minimum Viable COPE incomplete - missing: roof year")
    b, c = _page(hard=[a]), _page(hard=[a2])
    assert sd.new_on_review(sd.review_snapshot(b), sd.review_snapshot(c))["hard_stops"] == 0
    d = _page(hard=[a2, a3])                                      # one renamed, one more
    assert sd.new_on_review(sd.review_snapshot(b), sd.review_snapshot(d))["hard_stops"] == 1


def test_catch_all_codes_never_pair():
    x = ("iss_x", "uncovered_soft_stop", "Some sentence no rule claims")
    y = ("iss_y", "uncovered_soft_stop", "A different sentence no rule claims")
    out = sd.new_on_review(sd.review_snapshot(_page(warn=[x])), sd.review_snapshot(_page(warn=[y])))
    assert out["warnings"] == 1


def test_a_warning_that_became_a_hard_stop_is_new_on_the_hard_stops():
    w = ("iss_w", "umbrella_gl_period_misaligned", "Umbrella effective date does not match")
    out = sd.new_on_review(sd.review_snapshot(_page(warn=[w])), sd.review_snapshot(_page(hard=[w])))
    assert out["hard_stops"] == 1 and out["warnings"] == 0


def test_dismissed_items_are_hidden_and_a_resolved_one_that_still_fires_stays_listed():
    w = ("iss_w", "c1", "Warning one")
    v = ("iss_v", "c2", "Warning two")
    before = sd.review_snapshot(_page(warn=[w]), dismissed={"iss_w"})
    assert before["ids"]["warnings"] == []
    after = sd.review_snapshot(_page(warn=[w, v]), dismissed={"iss_w"})
    assert sd.new_on_review(before, after)["warnings"] == 1       # only iss_v
    # the route reads only DISMISSED statuses (resolvedIssues.splitClusters)
    src = ast.get_source_segment((BACKEND / "routes" / "session_documents_routes.py").read_text(encoding="utf-8"),
                                 next(n for n in ast.walk(ast.parse(
                                     (BACKEND / "routes" / "session_documents_routes.py").read_text(encoding="utf-8")))
                                      if isinstance(n, ast.AsyncFunctionDef) and n.name == "_dismissed_issue_ids"))
    assert 'r.get("status") == "dismissed"' in src


def test_data_consistency_is_compared_by_fact_key():
    before = sd.review_snapshot(_page(dc=[("applicant_name", "conflict"), ("fein", "confirmed")]))
    after = sd.review_snapshot(_page(dc=[("applicant_name", "conflict"), ("fein", "confirmed"),
                                         ("entity_type", "conflict"), ("mailing_address", "consistent")]))
    assert before["ids"]["data_consistency"] == ["applicant_name"]
    assert sd.new_on_review(before, after)["data_consistency"] == 1


@pytest.mark.parametrize("sb,sa,shown", [
    (99, 60, True), (60, 99, True), (None, 60, False), (99, None, False),
])
def test_the_score_is_carried_only_when_both_sides_know_it(sb, sa, shown):
    out = sd.new_on_review(sd.review_snapshot(_page(score=sb)), sd.review_snapshot(_page(score=sa)))
    assert (("score_before" in out) and ("score_after" in out)) is shown
    if shown:
        assert (out["score_before"], out["score_after"]) == (sb, sa)


@pytest.mark.parametrize("raw,score", [
    (True, None), ({"x": 1}, None), ("n/a", None), ([], None), ("99", 99), (85.0, 85),
])
def test_the_score_shapes_read_as_a_number_or_unknown(raw, score):
    page = _page()
    page["package_sqs"] = {"package_sqs_score": raw}
    assert sd.review_snapshot(page).get("score") == score
    page["package_sqs"] = "60"
    assert "score" not in sd.review_snapshot(page)


def test_dismissed_ids_come_from_the_stored_statuses(monkeypatch):
    import services.audit_service as asv

    async def _rows(_sid):
        return [{"issue_id": "iss_a", "status": "dismissed"}, {"issue_id": "iss_b", "status": "resolved"},
                {"issue_id": "", "status": "dismissed"}, "junk", {"status": "dismissed"}]
    monkeypatch.setattr(asv, "get_issue_statuses", _rows)
    assert run(sdr._dismissed_issue_ids("s")) == {"iss_a"}

    async def _boom(_sid):
        raise RuntimeError("no database")
    monkeypatch.setattr(asv, "get_issue_statuses", _boom)
    assert run(sdr._dismissed_issue_ids("s")) == set()


def test_old_payloads_fall_back_to_the_count_difference():
    stored = {"warnings": 0, "hard_stops": 0, "data_consistency": 0}     # the f83757cf row's shape
    after = sd.review_snapshot(_page(hard=[DRIVERS], warn=[EMPLOYEE], score=60))
    out = sd.new_on_review(stored, after)
    assert out == {"hard_stops": 1, "warnings": 1, "data_consistency": 0, "total": 2}
    assert sd.new_on_review(None, after) is None and sd.new_on_review(stored, None) is None
    assert sd.new_on_review({"hard_stops": "x"}, {"hard_stops": 2})["hard_stops"] == 2


@pytest.mark.parametrize("page", [None, {}, {"success": True, "session_id": "s"}, "x"])
def test_a_page_that_could_not_be_built_is_unknown_not_empty(page):
    assert sd.review_snapshot(page) is None
    assert sd.new_on_review(sd.review_snapshot(_page()), sd.review_snapshot(page)) is None


@pytest.mark.parametrize("page", [
    {"grouped_issues": ["not", "a", "view"], "hard_stops": ["a"]},
    {"grouped_issues": {"counts": "x"}, "hard_stops": "a", "soft_stops": None},
    {"grouped_issues": {"hard_stops": "x", "warnings": ["y"]}, "underwriting_consistency": ["z"]},
    {"hard_stops": ["a", "b"], "underwriting_consistency": {"fields": "conflict"}},
])
def test_a_malformed_page_never_breaks_the_counts(page):
    """The add route builds its answer from these AFTER the documents door has
    changed the package - a malformed page must never become a 500 there."""
    counts = sd.review_counts(page)
    assert set(counts) == {"hard_stops", "warnings", "data_consistency"}
    assert all(isinstance(v, int) for v in counts.values())
    snap = sd.review_snapshot(page)
    assert snap is None or set(counts) <= set(snap)
    sd.new_on_review(snap, snap)


def test_items_without_an_id_and_clusters_without_items():
    page = {"grouped_issues": {
        "hard_stops": [{"cluster": "c", "primary_message": "Hard one", "forms": ["ACORD_125"], "count": 1}],
        "warnings": {"required": [{"cluster": "c", "items": [{"message": "Warn one", "forms": [], "code": "k"}]}]},
    }}
    snap = sd.review_snapshot(page)
    from services.issue_registry import issue_id_for
    assert snap["ids"]["hard_stops"] == [issue_id_for("Hard one", ["ACORD_125"])]
    assert snap["ids"]["warnings"] == [issue_id_for("Warn one", [])]
    assert snap["rules"] == {issue_id_for("Warn one", []): "k"}


def test_the_status_endpoint_compares_by_identity(monkeypatch):
    before = sd.review_snapshot(_page(warn=[EMPLOYEE], score=99))
    row = {"user_id": "u1", "generated_forms": {"ACORD_125": {}},
           sd.FILL_KEY: {"state": "done", "run_id": "r", "doc_ids": ["d"], "documents": ["a.pdf"],
                         "review_counts_before": before, "other_insured": "MERIDIAN FABRICATION INC",
                         "other_insured_documents": ["a.pdf"], "suggestions": 2}}

    async def _get(_sid, include_pdf=False):
        return copy.deepcopy(row)

    async def _pagef(_sid, _user):
        return _page(warn=[DRIVERS], score=85)

    async def _dismissed(_sid):
        return set()
    monkeypatch.setattr(sdr, "get_processing_session", _get)
    monkeypatch.setattr(sdr, "_package_page", _pagef)
    monkeypatch.setattr(sdr, "_dismissed_issue_ids", _dismissed)
    out = json.loads(run(sdr.document_fill_status_route("s", None, {"id": "u1"})).body)
    assert out["new_on_review"] == {"hard_stops": 0, "warnings": 1, "data_consistency": 0, "total": 1,
                                    "score_before": 99, "score_after": 85}
    assert out["review_counts"] == {"hard_stops": 0, "warnings": 1, "data_consistency": 0}
    fill = out["ai_fill"]
    assert "review_counts_before" not in fill and "run_id" not in fill and "doc_ids" not in fill
    assert fill["other_insured"] == "MERIDIAN FABRICATION INC"
    assert fill["other_insured_documents"] == ["a.pdf"]


def test_the_add_route_records_the_page_by_identity(env, monkeypatch):
    """The route's own snapshot of the page before the add (ids, rules,
    score) is what the AI reading's status is later compared with."""
    import io
    from starlette.datastructures import UploadFile

    async def _dismissed(_sid):
        return set()
    monkeypatch.setattr(sdr, "_dismissed_issue_ids", _dismissed)
    tnd.make_package(env)
    resp = run(sdr.add_session_documents(
        session_id=tnd.SID,
        files=[UploadFile(file=io.BytesIO(tnd.NARR_TEXT.encode()), filename="narrative.txt")],
        progress_token=None, as_supporting=False, doc_type=None, confirm_same_insured=False,
        current_user=tnd.USER))
    out = json.loads(resp.body)
    before = env["store"].rows[tnd.SID][sd.FILL_KEY]["review_counts_before"]
    assert set(before["ids"]) == {"hard_stops", "warnings", "data_consistency"}
    assert isinstance(before.get("rules"), dict)
    assert "review_counts_before" not in out["ai_fill"]
    assert set(out["new_on_review"]) >= {"hard_stops", "warnings", "data_consistency", "total"}


# ══ B4. Another insured's document only suggests ═════════════════════════════

def _form(boxes, schema=None):
    state = {k: v[0] for k, v in boxes.items()}
    return {"field_state": dict(state), "mapped": dict(state),
            "confidence": {k: v[1] for k, v in boxes.items() if v[1]}, "client_filled_fields": [],
            "schema": schema or {}}


SCHEMA = {"Ops_A": {"ft": "/Tx"}, "Tick_A": {"ft": "/Btn"}, "Untick_A": {"ft": "/Btn"},
          "Other_A": {"ft": "/Tx"}, "Ai_A": {"ft": "/Tx"}, "Rule_A": {"ft": "/Tx"}, "Person_A": {"ft": "/Tx"}}
NEW_TEXT = "NAMED INSURED: MERIDIAN FABRICATION INC\nOperations: metal fabrication shop\n"


def _plan(other):
    stored = _form({"Ops_A": ("", None), "Tick_A": ("", None), "Untick_A": ("", None),
                    "Other_A": ("", None), "Ai_A": ("Office", "ai_verified"),
                    "Rule_A": ("Choice Electric LLC", "filled"), "Person_A": ("Typed", "producer")}, SCHEMA)
    new = {"Ops_A": "Metal fabrication shop", "Tick_A": "Yes", "Untick_A": "No",
           "Other_A": "4800 Washington St", "Ai_A": "Metal fabrication shop",
           "Rule_A": "MERIDIAN FABRICATION INC", "Person_A": "X"}
    conf = {k: "ai_verified" for k in new}
    guard = [{"field": "Held_A", "reason": "UNGROUNDED"}]
    return sd.plan_form_fill("ACORD_125", stored, new, conf, {}, guard, (), other_insured=other,
                             documents=["control_dec.pdf"], new_text=NEW_TEXT)


def test_another_insureds_document_writes_nothing_and_suggests_what_it_prints():
    plan = _plan("MERIDIAN FABRICATION INC")
    assert plan["fills"] == {} and plan["held_back"] == []
    by = {s["field"]: s for s in plan["suggestions"]}
    assert set(by) == {"Ops_A", "Tick_A", "Ai_A"}
    assert by["Ops_A"]["current"] == "" and by["Ops_A"]["suggested"] == "Metal fabrication shop"
    assert by["Tick_A"]["suggested"] == "Yes"                     # a tick is judged by the gate
    assert by["Ai_A"]["current"] == "Office"
    assert all(s["other_insured"] == "MERIDIAN FABRICATION INC" for s in plan["suggestions"])
    assert all(s["documents"] == ["control_dec.pdf"] for s in plan["suggestions"])
    # Untick_A (an unticked tick shows nothing), Other_A (the document does not
    # print it - the facts block did), Rule_A / Person_A (never the AI's) are not offered


@pytest.mark.parametrize("other", [None, "", "   "])
def test_the_applicants_own_or_a_nameless_document_behaves_exactly_as_before(other):
    plan = _plan(other)
    assert set(plan["fills"]) == {"Ops_A", "Tick_A", "Untick_A", "Other_A"}
    assert [s["field"] for s in plan["suggestions"]] == ["Ai_A"]
    assert "other_insured" not in plan["suggestions"][0]
    assert [g["field"] for g in plan["held_back"]] == ["Held_A"]


def test_a_blank_box_suggestion_lives_while_the_box_stays_blank():
    stored = _form({"Ops_A": ("", None)}, SCHEMA)
    plan = {"fills": {}, "held_back": [],
            "suggestions": [{"form_id": "ACORD_125", "field": "Ops_A", "current": "", "suggested": "Metal shop",
                             "label": "ai_verified", "documents": ["c.pdf"], "other_insured": "M INC"}]}
    gen = {"ACORD_125": copy.deepcopy(stored)}
    out = sd.apply_form_fills(gen, {"ACORD_125": copy.deepcopy(stored)}, {"ACORD_125": plan})
    assert out["filled"] == {} and len(out["suggestions"]) == 1
    assert gen["ACORD_125"]["field_state"]["Ops_A"] == ""          # nothing written
    assert sd.merge_suggestions([], out["suggestions"], gen) == out["suggestions"]
    rows = na.document_suggestion_rows(gen, out["suggestions"])
    assert len(rows) == 1 and rows[0]["suggested"] == "Metal shop"
    # a person types the box: the suggestion retires everywhere
    typed = copy.deepcopy(gen)
    typed["ACORD_125"]["field_state"]["Ops_A"] = "Electrical"
    typed["ACORD_125"]["confidence"]["Ops_A"] = "producer"
    assert sd.merge_suggestions(out["suggestions"], [], typed) == []
    assert na.document_suggestion_rows(typed, out["suggestions"]) == []
    # a rule prints it later: retired too
    ruled = copy.deepcopy(gen)
    ruled["ACORD_125"]["field_state"]["Ops_A"] = ruled["ACORD_125"]["mapped"]["Ops_A"] = "Electrical"
    ruled["ACORD_125"]["confidence"]["Ops_A"] = "filled"
    assert sd.merge_suggestions(out["suggestions"], [], ruled) == []
    # applied after a person typed it meanwhile: never offered
    out2 = sd.apply_form_fills(typed, {"ACORD_125": copy.deepcopy(stored)}, {"ACORD_125": plan})
    assert out2["suggestions"] == []


FOREIGN_MARKER = "HARBORLINE DECLARATIONS"
FOREIGN_OPS = "Commercial plumbing installation, service and repair"
FOREIGN_TEXT = (f"{FOREIGN_MARKER}\nNAMED INSURED: Harborline Plumbing LLC\n"
                f"Operations: {FOREIGN_OPS.lower()}.\n")


def _foreign():
    return tnd._doc("d-foreign", "harborline.txt", "dec_page", FOREIGN_TEXT,
                    {"applicant_name": {"value": "Harborline Plumbing LLC", "confidence": "ai_high",
                                        "source": "ai"}})


def test_end_to_end_another_insureds_document_only_suggests(env):
    """The real door, merge, integrity check, shared gap fill and stamping
    engine: a Harborline declarations added (the producer said "they belong
    to this insured") to the Bluebird Electric package."""
    tnd.make_package(env)
    box = tnd.OPS_BOX
    assert box in tnd.gap_fields(env) and not tnd.form(env)["field_state"].get(box)
    env["model"].answers = {box: FOREIGN_OPS}
    result = run(sd.add_documents(tnd.SID, [_foreign()], user_id="u1", purge_dec_index=True,
                                  confirm_same_insured=True))
    row = env["store"].rows[tnd.SID]
    assert row["integrity"]["overridden"] is True
    status = run(sd.start_new_document_fill(tnd.SID, result["documents_added"], "u1"))
    recalcs = len(env["calls"].get("recalc", []))
    out = run(sd.run_new_document_fill(tnd.SID, status["doc_ids"], "u1", run_id=status["run_id"]))
    assert out["state"] == sd.FILL_DONE
    assert len(env["calls"].get("recalc", [])) == recalcs        # nothing moved, nothing re-scored
    assert out["other_insured"] == "Harborline Plumbing LLC"
    assert out["other_insured_documents"] == ["harborline.txt"]
    assert out["boxes_filled"] == 0 and out["filled_by_form"] == {} and out["held_back"] == 0
    f = tnd.form(env)
    assert not f["field_state"].get(box)                          # nothing written
    held = env["store"].rows[tnd.SID][sd.SUGGESTIONS_KEY]
    sug = [s for s in held if s["field"] == box]
    assert len(sug) == 1 and sug[0]["current"] == "" and sug[0]["suggested"] == FOREIGN_OPS
    assert sug[0]["other_insured"] == "Harborline Plumbing LLC"
    assert out["suggestions"] == len(held)
    events = [a for a, _k in env["calls"].get("log_audit_event", [])
              if len(a) > 2 and a[2] == "forms_filled_from_new_documents"]
    assert events and events[-1][3]["other_insured"] == "Harborline Plumbing LLC"
    # The Documents list says whose it is - the server decides, kept by you.
    page = json.loads(run(fr.get_extraction_result(tnd.SID, current_user=tnd.USER)).body)
    by = {d["doc_id"]: d for d in page["doc_summary"]}
    assert by["d-foreign"]["insured_status"] == {"state": "different", "name": "Harborline Plumbing LLC",
                                                 "kept_by_you": True}
    assert by["d-dec"]["insured_status"] == {"state": "same"}


def test_end_to_end_the_applicants_own_narrative_still_fills(env):
    """The control: the same reading of the applicant's own narrative (it
    names Bluebird Electric) fills the blank box as it always has."""
    tnd.make_package(env)
    env["model"].answers = {tnd.OPS_BOX: tnd.OPS}
    out = tnd.add_narrative(env)
    assert out["other_insured"] is None and out["other_insured_documents"] == []
    assert out["boxes_filled"] == 1 and tnd.form(env)["field_state"][tnd.OPS_BOX] == tnd.OPS


def test_the_fill_judges_the_new_documents_without_them():
    src = ast.get_source_segment((BACKEND / "services" / "session_documents.py").read_text(encoding="utf-8"),
                                 next(n for n in ast.walk(ast.parse(
                                     (BACKEND / "services" / "session_documents.py").read_text(encoding="utf-8")))
                                      if isinstance(n, ast.FunctionDef) and n.name == "names_another_insured"))
    assert "judge_without=ids" in src
    session = {"integrity": _three(["CHOICE ELECTRIC LLC", "MERIDIAN FABRICATION INC", "MERIDIAN FABRICATION INC"],
                                   [{"label": "CHOICE ELECTRIC LLC", "doc_ids": ["d0"]},
                                    {"label": "MERIDIAN FABRICATION INC", "doc_ids": ["d1", "d2"]}])}
    got = sd.names_another_insured(session, [{"doc_id": "d1", "filename": "a.pdf"},
                                             {"doc_id": "d2", "filename": "b.pdf"}])
    assert got == {"name": "MERIDIAN FABRICATION INC", "documents": ["a.pdf", "b.pdf"]}
    # the applicant's own document added beside one of another company's
    mixed = {"integrity": _three(["CHOICE ELECTRIC LLC", "MERIDIAN FABRICATION INC", "CHOICE ELECTRIC LLC"],
                                 [{"label": "CHOICE ELECTRIC LLC", "doc_ids": ["d0", "d2"]},
                                  {"label": "MERIDIAN FABRICATION INC", "doc_ids": ["d1"]}])}
    assert sd.names_another_insured(mixed, [{"doc_id": "d2", "filename": "c.pdf"}]) is None
    assert sd.names_another_insured({}, [{"doc_id": "d1"}]) is None
    assert sd.names_another_insured(None, None) is None


# ══ The screens ══════════════════════════════════════════════════════════════

_EM = ("—", "–")


@pytest.mark.parametrize("rel", [
    "utils/addDocuments.js", "components/form/review/AddDocumentsPanel.jsx",
    "components/form/review/ReviewRailLayout.jsx",
])
def test_no_em_dashes(rel):
    assert not any(d in (FRONTEND / rel).read_text(encoding="utf-8") for d in _EM), rel


def test_both_layouts_draw_the_same_two_tags_and_compare_no_names():
    rail = (FRONTEND / "components" / "form" / "review" / "ReviewRailLayout.jsx").read_text(encoding="utf-8")
    modal = (FRONTEND / "components" / "form" / "AcordModal.jsx").read_text(encoding="utf-8")
    assert "import { documentTypeTag, documentInsuredTag, INSURED_TAG_STYLE } from \"../../../utils/addDocuments\"" in rail
    assert "documentTypeTag, documentInsuredTag, INSURED_TAG_STYLE" in modal
    for text in (rail, modal):
        assert "documentTypeTag(d)" in text and "documentInsuredTag(d)" in text
        assert 'data-testid="doc-type-tag"' in text and 'data-testid="doc-insured-tag"' in text
        assert "style={INSURED_TAG_STYLE}" in text
        for gone in ('? "Strong match"', '"Likely match" :', ">you set this<", "confLabel", "confColor"):
            assert gone not in text, gone
    block = modal[modal.index("Two tags, two questions"):modal.index('className="doc-filename"')]
    assert not any(d in block for d in _EM)
    lib = (FRONTEND / "utils" / "addDocuments.js").read_text(encoding="utf-8")
    tag_fn = lib[lib.index("export function documentInsuredTag"):]
    assert "same_entity" not in tag_fn and "toLowerCase" not in tag_fn   # the server decides


@pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")
def test_the_words_in_node(tmp_path):
    lib = (FRONTEND / "utils" / "addDocuments.js").as_uri()
    script = tmp_path / "check.mjs"
    script.write_text(
        f"import * as A from {json.dumps(lib)};\n"
        "const fill = (o) => ({state: 'done', documents: ['control_dec.pdf'], suggestions: 0, ...o});\n"
        "const out = {\n"
        " one: A.fillStatusLines(fill({other_insured: 'MERIDIAN FABRICATION INC', other_insured_documents: ['control_dec.pdf'], suggestions: 5})),\n"
        " none: A.fillStatusLines(fill({other_insured: 'MERIDIAN FABRICATION INC', other_insured_documents: ['control_dec.pdf']})),\n"
        " two: A.fillStatusLines(fill({documents: ['a.pdf', 'b.pdf'], other_insured: 'M INC', other_insured_documents: ['a.pdf', 'b.pdf'], suggestions: 1})),\n"
        " mixed: A.fillStatusLines(fill({documents: ['a.pdf', 'b.pdf'], other_insured: 'M INC', other_insured_documents: ['b.pdf']})),\n"
        " older: A.fillStatusLines(fill({other_insured: 'M INC'})),\n"
        " own: A.fillStatusLines(fill({other_insured: null, boxes_filled: 2})),\n"
        " bap: A.newOnReviewText({hard_stops: 0, warnings: 1, data_consistency: 0, score_before: 99, score_after: 85}),\n"
        " drop: A.newOnReviewText({hard_stops: 0, warnings: 0, data_consistency: 0, score_before: 99, score_after: 60}),\n"
        " up: A.newOnReviewText({hard_stops: 0, warnings: 0, data_consistency: 0, score_before: 60, score_after: 99}),\n"
        " flat: A.newOnReviewText({hard_stops: 0, warnings: 0, data_consistency: 0, score_before: 99, score_after: 99}),\n"
        " oneside: A.newOnReviewText({hard_stops: 0, warnings: 0, data_consistency: 0, score_before: 99}),\n"
        " sections: [A.firstNewSection({warnings: 0, score_before: 99, score_after: 60}), A.firstNewSection({warnings: 1, score_before: 99, score_after: 60}), A.firstNewSection({score_before: 60, score_after: 99}), A.firstNewSection(null)],\n"
        " types: [A.documentTypeTag({doc_type_confidence: 'high'}), A.documentTypeTag({doc_type_confidence: 'medium'}), A.documentTypeTag({doc_type_confidence: 'low'}), A.documentTypeTag({doc_type_overridden: true, doc_type_confidence: 'low'}), A.documentTypeTag({}), A.documentTypeTag(null), A.documentTypeTag({doc_type_confidence: 3})],\n"
        " insured: [A.documentInsuredTag({insured_status: {state: 'different', name: 'MERIDIAN FABRICATION INC', kept_by_you: true}}), A.documentInsuredTag({insured_status: {state: 'different', name: 'MERIDIAN FABRICATION INC', kept_by_you: false}}), A.documentInsuredTag({insured_status: {state: 'same'}}), A.documentInsuredTag({insured_status: {state: 'none'}}), A.documentInsuredTag({insured_status: {state: 'different', name: '  '}}), A.documentInsuredTag({}), A.documentInsuredTag({insured_status: 'different'})],\n"
        "};\nconsole.log(JSON.stringify(out));\n", encoding="utf-8")
    proc = subprocess.run(["node", str(script)], capture_output=True, text=True, timeout=60)
    assert proc.returncode == 0, proc.stderr
    o = json.loads(proc.stdout)
    assert o["one"] == [{"kind": "warn", "text": (
        "control_dec.pdf names a different insured (MERIDIAN FABRICATION INC), so the AI did not fill your "
        "forms from it - 5 values to review under New document.")}]
    assert o["none"][0]["text"].endswith("so the AI did not fill your forms from it.")
    assert o["two"][0]["text"].startswith("a.pdf and b.pdf name a different insured (M INC), so the AI did not "
                                          "fill your forms from them - 1 value to review")
    assert o["mixed"][0]["text"] == ("b.pdf names a different insured (M INC), so the AI did not fill your "
                                     "forms from a.pdf and b.pdf.")
    assert o["older"][0]["text"].startswith("control_dec.pdf names a different insured (M INC)")
    assert len(o["one"]) == len(o["none"]) == 1                   # one short line
    assert o["own"][0]["text"].startswith("Read control_dec.pdf into your forms: the AI filled 2 boxes")
    assert o["bap"] == "New on the review page: 1 warning. Your score went from 99 to 85."
    assert o["drop"] == "Your score went from 99 to 60 - see the review page."
    assert o["up"] == o["flat"] == o["oneside"] == "No new issues on the review page."
    assert o["sections"] == ["overview", "warnings", None, None]
    labels = [t and t["label"] for t in o["types"]]
    assert labels == ["Type: sure", "Type: likely", "Type: unsure", "Type: set by you", None, None, None]
    assert all("TYPE" in t["title"] for t in o["types"][:3])
    ins = o["insured"]
    assert ins[0]["label"] == "Different insured: MERIDIAN FABRICATION INC - kept by you"
    assert ins[1]["label"] == "Different insured: MERIDIAN FABRICATION INC"
    assert ins[2:] == [None, None, None, None, None]
    for text in [o["one"][0]["text"], o["two"][0]["text"], o["bap"], o["drop"], ins[0]["label"], ins[0]["title"]]:
        assert not any(d in text for d in _EM)


# ── The side panel's words for a held suggestion (lead, 14 Oct 2026) ──────────

def test_a_blank_box_suggestion_reads_as_empty_and_names_the_other_insured():
    from services.needs_attention import document_suggestion_rows
    gen = {"ACORD_127": {"field_state": {"Vehicle_ModelName_B": ""}, "confidence": {},
                         "schema": {"Vehicle_ModelName_B": {"tu": "Enter text: The model name of the vehicle."}}}}
    sug = [{"id": "s1", "form_id": "ACORD_127", "field": "Vehicle_ModelName_B", "current": "",
            "suggested": "F-250", "documents": ["control_dec.pdf"], "other_insured": "MERIDIAN FABRICATION INC"}]
    rows = document_suggestion_rows(gen, sug)
    assert rows and '""' not in rows[0]["reason"]
    assert "this box is empty" in rows[0]["reason"]
    assert "MERIDIAN FABRICATION INC" in rows[0]["reason"]
    assert rows[0]["other_insured"] == "MERIDIAN FABRICATION INC"
    # the ordinary case keeps its words
    sug2 = [dict(sug[0], other_insured=None, current="", suggested="F-250")]
    gen["ACORD_127"]["field_state"]["Vehicle_ModelName_B"] = ""
    assert "different insured" not in document_suggestion_rows(gen, sug2)[0]["reason"]
