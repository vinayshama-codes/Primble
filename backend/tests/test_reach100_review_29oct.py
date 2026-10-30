"""Hostile review of the reach-100 rule, 29 Oct 2026 (offline, no model).

Found on the stored session 614c3211 (a lone Transcriber-read ACORD 125, 36 before
forms): the page adds up (36 + 64 = 100) but answering EVERYTHING it lists ended at
85 in page and random order. The hold was "Policy Effective Date: documents disagree
(12/01/2026, 12/01/2025)" (and the same for the expiration) on a ONE-document
package. Two halves of one class, both fixed:

(a) the rival was the SAME document's PRIOR term: the picker's text scan reads the
    first label-adjacent date, and on an ACORD 125 that is the Prior Carrier grid
    ("EFFECTIVE DATE 12/01/2025 ...") - page one prints its proposed dates under
    their column headings. A date the document itself records as its prior term
    (`prior_*`, `prior_coverage_by_line`, retired rows) is never a rival
    (`underwriting_consistency._document_prior_term_dates`); a same-line "Prior /
    Expiring / Previous ..." label is another period's printing too.
(b) the Data Consistency pick did not retire the conflict: every stops reader took
    the STORED assessment, which predates the pick (`stops_now.
    _settled_by_confirmation`).

The package is built from the real Transcriber reply of our own CH125 ACORD 125
(`fixtures/transcriber_stub/real_125_probe.json`, producer scrubbed) through
`copies_from` + `boxes_to_facts`, with a page text composed from its own boxes in the
shape the flattened PDF's text layer prints. No client data."""
import copy
import json
import os
import random

import pytest

from reach100_harness import _env, confirm_conflict, read_page, solve_checked

STUB = os.path.join(os.path.dirname(__file__), "fixtures", "transcriber_stub", "real_125_probe.json")


@pytest.fixture(autouse=True)
def _offline(monkeypatch):
    def refuse(*_a, **_k):
        raise AssertionError("no model or network call")
    import httpx
    monkeypatch.setattr(httpx.Client, "send", refuse)
    monkeypatch.setattr(httpx.AsyncClient, "send", refuse)
    monkeypatch.setenv("NARRATIVE_READER", "0")
    monkeypatch.setenv("EVIDENCE_JUDGE", "0")
    monkeypatch.setenv("CARRIER_NARRATIVE", "0")


_GRID_COLUMNS = ("GeneralLiability", "Automobile", "Property", "OtherLine")


def _transcriber_125():
    """(facts, boxes) of the real Transcriber reply, as the upload reads it."""
    from services import asg_transcriber as T
    from services.acord_intake import transcriber_intake as TI
    from services.acord_intake.read import boxes_to_facts, relabel_transcriber_facts
    with open(STUB, encoding="utf-8") as fh:
        res = T.parse_poll_reply(fh.read(), {})
    g = TI.SendGroup(pages=[0, 1, 2, 3, 4], acord_numbers=["125"] * 5, kinds=["flattened"] * 5,
                     data=b"", hash="r29")
    copies = TI.copies_from(g, res)
    facts, _carried = boxes_to_facts(copies)
    relabel_transcriber_facts(facts, copies)
    return facts, copies[0]["boxes"]


def _flattened_text(boxes: dict) -> str:
    """The text layer's shape: page one's proposed term under its column headings
    (never label-adjacent), page four's Prior Carrier grid one label per row."""
    def grid(field):
        return " ".join(v for v in (boxes.get(f"PriorCoverage_{c}_{field}_A") for c in _GRID_COLUMNS) if v)
    return ("[Document page 1]\nCOMMERCIAL INSURANCE APPLICATION\n"
            "PROPOSED EFF DATE PROPOSED EXP DATE BILLING PLAN PAYMENT PLAN POLICY PREMIUM\n"
            f"{boxes['Policy_EffectiveDate_A']} {boxes['Policy_ExpirationDate_A']} DIRECT\n"
            "[Document page 4]\nPRIOR CARRIER INFORMATION\n"
            "YEAR CATEGORY GENERAL LIABILITY AUTOMOBILE PROPERTY OTHER\n"
            f"EFFECTIVE DATE {grid('EffectiveDate')}\n"
            f"EXPIRATION DATE {grid('ExpirationDate')}\n")


def _package(docs):
    """A stored row as the pipeline writes it: merged facts, the picker's
    assessment, the recommended forms."""
    from services.extraction_service import merge_facts
    from services.form_service import match_forms_deterministic
    from services.underwriting_consistency import assess_underwriting_consistency
    merged, flags = merge_facts(copy.deepcopy(docs), copy.deepcopy(docs[0]))
    text = "\n".join(d.get("text") or "" for d in docs)
    return {"facts": merged, "flags": flags, "docs": docs, "underwriting_confirmations": {},
            "underwriting_consistency": assess_underwriting_consistency(docs, merged, {}, flags=flags),
            "structured_issues": [], "generated_forms": {},
            "recommendations": match_forms_deterministic(merged, flags, text=text)}


def _one_document_renewal():
    facts, boxes = _transcriber_125()
    doc = {"doc_id": "d125", "filename": "ACORD_125_flat.pdf", "doc_type": "application",
           "facts": facts, "text": _flattened_text(boxes), "flags": {}}
    return _package([doc])


def _date_conflicts(row):
    from services.stops_now import stops_now
    st = stops_now(row, pre_form=True, facts=row["facts"], flags=row["flags"])
    return [m for m in st["soft"] + st["hard"] if "Date: documents disagree" in m]


def _open(uw):
    return {f["fact_key"]: sorted(v["display"] for v in f["values"])
            for f in (uw or {}).get("fields") or [] if f.get("review_required")}


def _assess(docs, facts=None):
    from services.underwriting_consistency import assess_underwriting_consistency
    return assess_underwriting_consistency(docs, facts or {}, {}, flags={})


def _doc(name, doc_type, text, **facts):
    return {"doc_id": name, "filename": f"{name}.pdf", "doc_type": doc_type, "text": text,
            "facts": {k: (_env(v) if not isinstance(v, (list, dict)) else v) for k, v in facts.items()}}


# ── (a) the document's own prior term is no rival ─────────────────────────────
def test_the_fixture_is_the_reported_shape():
    facts, boxes = _transcriber_125()
    assert facts["effective_date"]["value"] == "12/01/2026" == boxes["Policy_EffectiveDate_A"]
    assert boxes["PriorCoverage_Automobile_EffectiveDate_A"] == "12/01/2025"
    # the text scan, alone, reads the prior grid - the reported rival
    from services.underwriting_consistency import _text_scan_values
    assert _text_scan_values(_flattened_text(boxes), "effective_date") == ["12/01/2025"]
    assert _text_scan_values(_flattened_text(boxes), "expiration_date") == ["12/01/2026"]


def test_a_one_document_renewal_raises_no_term_conflict():
    row = _one_document_renewal()
    assert _open(row["underwriting_consistency"]) == {}
    assert _date_conflicts(row) == []
    term = {f["fact_key"]: f for f in row["underwriting_consistency"]["fields"]
            if f["fact_key"] in ("effective_date", "expiration_date")}
    assert [v["display"] for v in term["effective_date"]["values"]] == ["12/01/2026"]
    assert [v["display"] for v in term["expiration_date"]["values"]] == ["12/01/2027"]


def test_answering_everything_on_a_one_document_renewal_reaches_100():
    row = _one_document_renewal()
    for order, rnd in (("page", None), ("shuffle", random.Random(3))):
        score, problems = solve_checked(row, order=order, rnd=rnd)
        assert score == 100 and problems == [], (order, score, problems)


def test_a_renewal_dec_s_own_expiring_term_is_no_rival():
    """The other half of the class: a declarations page printing the expiring
    term it renews - recorded by extraction as the document's prior term."""
    text = "RENEWAL DECLARATIONS\nPolicy Period shown below\nEffective Date: 07/15/2025\n"
    dec = _doc("dec", "dec_page", text, effective_date="07/15/2026",
               prior_effective_date="07/15/2025")
    assert _open(_assess([dec])) == {}


def test_a_same_line_prior_label_is_another_period():
    from services.underwriting_consistency import _text_scan_values
    for label in ("Prior Policy Effective Date:", "Expiring Policy Effective Date:",
                  "Previous Effective Date:"):
        assert _text_scan_values(f"{label} 12/01/2025\n", "effective_date") == [], label
    assert _text_scan_values("Prior Policy Expiration Date: 12/01/2026\n", "expiration_date") == []
    assert _text_scan_values("Previous Year Gross Sales: $4,000,000\n", "total_revenue") == []
    # the policy's own labels still read
    assert _text_scan_values("Policy Effective Date: 12/01/2026\n", "effective_date") == ["12/01/2026"]
    assert _text_scan_values("Renewal Effective Date: 12/01/2026\n", "effective_date") == ["12/01/2026"]
    assert _text_scan_values("Expires: 12/01/2027\n", "expiration_date") == ["12/01/2027"]


def test_a_real_rival_still_conflicts():
    """Narrow by construction: a scanned date the document does NOT give its prior
    term, and another document's different reading, are still rivals."""
    grid = [{"line": "General Liability", "effective": "12/01/2025", "expiration": "12/01/2026"}]
    # the same document's label-adjacent date that is no prior-term date
    same = _doc("app", "application", "Policy Effective Date: 01/15/2027\n",
                effective_date="12/01/2026", prior_coverage_by_line=grid)
    assert _open(_assess([same])) == {"effective_date": ["01/15/2027", "12/01/2026"]}
    # two applications proposing different terms
    a = _doc("a", "application", "", effective_date="12/01/2026", prior_coverage_by_line=grid)
    b = _doc("b", "application", "", effective_date="12/15/2026")
    assert _open(_assess([a, b])) == {"effective_date": ["12/01/2026", "12/15/2026"]}


def test_the_roles_are_never_mixed():
    """A renewal's prior EXPIRATION is its proposed EFFECTIVE date: a scanned
    effective date equal to the prior expiration is not excused by it."""
    grid = [{"line": "General Liability", "effective": "12/01/2025", "expiration": "12/01/2026"}]
    doc = _doc("app", "application", "Effective Date: 12/01/2026\n",
               effective_date="12/15/2026", prior_coverage_by_line=grid)
    assert _open(_assess([doc])) == {"effective_date": ["12/01/2026", "12/15/2026"]}


def test_prior_term_dates_read_every_record_of_the_prior_term():
    from services.underwriting_consistency import _document_prior_term_dates as P
    facts = {"prior_effective_date": _env("12/01/2024"),
             "prior_coverage_by_line": _env([{"effective": "12/01/2025", "expiration": "12/01/2026"},
                                             {"effective": None}, "junk"]),
             "prior_coverage_lines": [{"effective_date": "06/01/2023", "expiration_date": "06/01/2024"}]}
    assert P("effective_date", "identity", facts) == {"2024-12-01", "2025-12-01", "2023-06-01"}
    assert P("expiration_date", "identity", facts) == {"2026-12-01", "2024-06-01"}
    assert P("fein", "identity", facts) == set() and P("effective_date", "identity", None) == set()
    assert P("effective_date", "identity", {}) == set()


# ── (b) a confirmed pick retires its conflict, always ─────────────────────────
def _stale_conflict_row():
    """A stored assessment written BEFORE the pick: one open term conflict."""
    return {"facts": {"effective_date": _env("12/01/2026")}, "flags": {}, "docs": [],
            "recommendations": [], "structured_issues": [], "underwriting_confirmations": {},
            "underwriting_consistency": {"review_required": True, "fields": [{
                "fact_key": "effective_date", "label": "Policy Effective Date", "review_required": True,
                "status": "conflict", "conflict_scope": [],
                "values": [{"display": "12/01/2026"}, {"display": "12/01/2025"}]}]}}


def test_a_confirmed_pick_retires_a_stale_stored_conflict():
    from services.stops_now import conflict_stop_issues
    row = _stale_conflict_row()
    assert len(_date_conflicts(row)) == 1 and conflict_stop_issues(row)
    assert confirm_conflict(row, "effective_date")
    assert _date_conflicts(row) == [] and conflict_stop_issues(row) == []


def test_a_line_scoped_pick_retires_only_what_it_answers():
    from services.stops_now import underwriting_conflict_stops as U
    uw = {"review_required": True, "fields": [{
        "fact_key": "policy_number", "label": "Policy Number", "review_required": True,
        "conflict_scope": ["auto", "general_liab"], "values": [{"display": "A-1"}, {"display": "B-2"}]}]}
    assert len(U(uw, {}, None, {"policy_number@auto": "A-1"})) == 1          # one of two lines
    assert U(uw, {}, None, {"policy_number@auto": "A-1", "policy_number@general_liab": "B-2"}) == []
    assert U(uw, {}, None, {"policy_number": "A-1"}) == []                   # submission-wide
    assert len(U(uw, {}, None, {"fein": "12-3456789"})) == 1                 # another fact
    assert len(U(uw, {}, None, None)) == 1                                   # no picks: unchanged


def test_a_form_number_confirmed_as_a_policy_number_settles_nothing():
    from services.stops_now import underwriting_conflict_stops as U
    uw = {"review_required": True, "fields": [{
        "fact_key": "policy_number", "label": "Policy Number", "review_required": True,
        "conflict_scope": [], "values": [{"display": "IM 7100 06 04"}, {"display": "BBC7263-26"}]}]}
    assert len(U(uw, {}, None, {"policy_number": "IM 7100 06 04"})) == 1


def test_a_picked_conflict_leaves_the_page_and_its_points():
    """The page reading of a stale stored conflict: a Data Consistency item with
    its warning before the pick, neither after it."""
    row = _stale_conflict_row()
    row["facts"].update(_one_document_renewal()["facts"])
    _pkg, _kd, items = read_page(row)
    assert [i["fact"] for i in items if i.get("kind") == "dc"] == ["effective_date"]
    confirm_conflict(row, "effective_date")
    pkg2, _kd2, items2 = read_page(row)
    assert not any(i.get("kind") == "dc" for i in items2)
    assert not any("documents disagree" in str(m) for m in (pkg2.get("cap_soft_stops") or []))
    assert "documents disagree" not in str(pkg2.get("cap_reason") or "")


def test_a_scoped_pick_never_hides_a_rival_on_an_unpicked_line():
    """Review, 29 Oct 2026: every DISPUTED line picked, but a third value sits on a
    line the row did not list - the stop stays until that value is accounted for."""
    from services.stops_now import underwriting_conflict_stops as U
    uw = {"review_required": True, "fields": [{
        "fact_key": "policy_number", "label": "Policy Number", "review_required": True,
        "conflict_scope": ["auto", "general_liab"],
        "values": [{"display": "A-1", "scope": ["auto"]}, {"display": "B-2", "scope": ["general_liab"]},
                   {"display": "C-3", "scope": ["umbrella"]}]}]}
    picks = {"policy_number@auto": "A-1", "policy_number@general_liab": "B-2"}
    assert len(U(uw, {}, None, picks)) == 1
    # a value ruled out on its only line is not a rival
    uw["fields"][0]["values"][2] = {"display": "C-3", "scope": ["auto"]}
    assert U(uw, {}, None, picks) == []
