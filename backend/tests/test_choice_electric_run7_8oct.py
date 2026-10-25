"""Choice Electric, the owner's generation run of 8 Oct 2026 (session 805049a7).

Read 25sepChanges.md part Q before changing anything pinned here. Three defects
from that run, each pinned on the shape that broke:

1. "Back to review" left the app header hidden AND collapsed. Scrolling the PDF
   inside the editor hides the header; leaving the editor removed the element
   whose scroll hid it, so nothing released it - no navbar, a blank band at the
   bottom, until a refresh.
2. The "Since client answers" band was written by EVERY recalculation. The
   owner's own pre-form occupancy answer showed as "1 updated, 1 new" on a
   package no client had seen.
3. A cut-off extraction reply was salvaged and then treated - and cached - as
   the whole document. The WC dec (byte-identical text on every run) came back
   with 75 of 201 schema keys and no flags: no class table, no state.
"""
from __future__ import annotations

import asyncio
import copy
import json
import os

from unittest.mock import patch

import pytest

import repositories.session_repository as sr
import routes.audit_routes as ar
import services.arq_service as arq
import services.audit_service as au
import services.extraction_service as es

HERE = os.path.dirname(os.path.abspath(__file__))
BACKEND = os.path.dirname(HERE)
FRONTEND = os.path.join(os.path.dirname(BACKEND), "frontend", "src")


def _src(*parts):
    with open(os.path.join(*parts), encoding="utf-8") as fh:
        return fh.read()


# ── 1. the header comes back when the editor closes ─────────────────────────

def test_the_header_listens_for_a_reset_and_shows_itself():
    src = _src(FRONTEND, "components", "layout", "Header.jsx")
    assert 'window.addEventListener("app-header:reset", handleReset)' in src
    assert 'window.removeEventListener("app-header:reset", handleReset)' in src
    body = src[src.index("const handleReset = () => {"):]
    body = body[:body.index("};") + 2]
    # both halves of the stuck state are released, and the hide flag the scroll
    # handler reads is cleared with them
    assert "setHidden(false)" in body and "setCollapse(false)" in body
    assert "hiddenLocal = false" in body


def test_every_step_change_asks_for_the_header_back():
    src = _src(FRONTEND, "components", "form", "AcordModal.jsx")
    effect = src[src.index("useEffect(() => {\n    document.body.style.overflow = step === \"editor\""):]
    effect = effect[:effect.index("}, [step]);")]
    assert 'window.dispatchEvent(new Event("app-header:reset"))' in effect
    # and "Back to review" asks too, before it opens a section
    back = src[src.index("const goBackToReview = async (toSection) => {"):]  # takes a page since 23 Oct 2026
    back = back[:back.index("const confirmDocChange")]
    assert back.index('new Event("app-header:reset")') < back.index("showReviewSection(section)")


# ── 2. only a client's answers write "Since client answers" ─────────────────

def _row(**over):
    base = {
        "user_id": "u-run7",
        "facts": {
            "producer_name": "Best Agency", "applicant_name": "Choice Electric LLC",
            "effective_date": "01/01/2027", "lines_of_business": "General Liability",
            "entity_type": "LLC",
        },
        "flags": {"has_general_liability": True},
        "hard_stops": [], "soft_stops": [],
        "recommendations": [{"form_id": "ACORD_125"}],
        "cross_form_issues": [], "structured_issues": [], "docs": [], "integrity": {},
        "generated_forms": {}, "selected_form_ids": [], "underwriting_consistency": {},
    }
    base.update(over)
    return base


class _Session:
    """The REAL recalculation against an in-memory row; DB / audit side
    effects stubbed (same shape as test_step2_orbin_29sep._Session)."""

    def __init__(self, row):
        self.store = copy.deepcopy(row)

    async def _get(self, _sid):
        return copy.deepcopy(self.store)

    async def _upd(self, _sid, payload, delete_facts=None):
        for k, v in (payload or {}).items():
            self.store[k] = copy.deepcopy(v)
        return True

    def run(self, coro_fn, *args, **kwargs):
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
            return asyncio.run(coro_fn(*args, **kwargs))


def test_a_producer_recalculation_never_writes_the_client_band():
    s = _Session(_row())
    impact = s.run(arq.recalculate_session_scores, "sid-run7")
    assert impact.get("issue_diff") is not None, "the diff must still be computed"
    assert "issue_diff_last" not in s.store


def test_a_client_questionnaire_writes_it_and_says_so():
    s = _Session(_row())
    s.run(arq.recalculate_session_scores, "sid-run7", trigger=arq.CLIENT_ANSWERS_TRIGGER)
    stored = s.store.get("issue_diff_last")
    assert isinstance(stored, dict)
    assert stored["trigger"] == "client_answers"
    assert set(("resolved", "updated", "new", "still_open")) <= set(stored)


def test_a_later_producer_recalculation_keeps_the_clients_diff():
    client_diff = {"resolved": [{"cluster": "X"}], "updated": [], "worsened": [], "new": [],
                   "still_open": [], "trigger": "client_answers"}
    s = _Session(_row(issue_diff_last=client_diff))
    s.run(arq.recalculate_session_scores, "sid-run7")
    assert s.store["issue_diff_last"] == client_diff


def test_only_the_two_client_paths_pass_the_client_trigger():
    """Every recalculation caller that passes CLIENT_ANSWERS_TRIGGER, by file.
    A new caller passing it must be a CLIENT's answers taking effect."""
    passers = set()
    for root in ("routes", "services"):
        for name in os.listdir(os.path.join(BACKEND, root)):
            if name.endswith(".py") and "CLIENT_ANSWERS_TRIGGER" in _src(BACKEND, root, name):
                passers.add(f"{root}/{name}")
    passers.discard("services/arq_service.py")          # where it is defined and read
    assert passers == {"routes/arq_routes.py", "services/client_answer_review.py"}


def test_the_band_refuses_a_diff_no_client_wrote():
    src = _src(FRONTEND, "components", "form", "AcordModal.jsx")
    band = src[src.index("function RemediationDiffBand("):]
    band = band[:band.index("const resolved")]
    assert 'diff.trigger !== "client_answers"' in band


# ── 3. a cut-off extraction reply is retried and never cached ───────────────

_WHOLE = json.dumps({
    "facts": {
        "applicant_name": "CHOICE ELECTRIC LLC",
        "carrier_name": "AMERISURE INSURANCE COMPANY",
        "state_of_operations": "CO",
        "wc_class_codes": [{"code": "5190", "state": "CO", "payroll": "2,000,000"}],
    },
    "flags": {"has_workers_comp": True},
})
# The 8 Oct shape: cut part-way through the facts object, flags never reached.
_CUT = ('{"facts": {"applicant_name": "CHOICE ELECTRIC LLC", '
        '"carrier_name": "AMERISURE INSURANCE COMPANY", "state_of_operations": "C')


def test_the_parser_says_when_it_returned_a_fragment():
    r: dict = {}
    asyncio.run(es._safe_json_parse(_CUT, context="t", report=r))
    assert r.get("partial") is True
    r2: dict = {}
    asyncio.run(es._safe_json_parse(_WHOLE, context="t", report=r2))
    assert not r2.get("partial")


def _run_extract(replies, monkeypatch):
    calls, cached = [], []

    async def _chat(*_a, **_k):
        calls.append(1)
        return replies[min(len(calls), len(replies)) - 1]

    async def _miss(_k):
        return None

    async def _set(k, v):
        cached.append(k)

    monkeypatch.setattr(es, "groq_chat", _chat)
    monkeypatch.setattr(es, "_cache_get", _miss)
    monkeypatch.setattr(es, "_cache_set", _set)
    text = "WORKERS' COMPENSATION AND EMPLOYERS' LIABILITY INFORMATION PAGE - CO 001 5190"
    result = asyncio.run(es.extract_facts(text))
    return result, calls, cached


def _value(fact):
    return fact.get("value") if isinstance(fact, dict) and "value" in fact else fact


def test_a_cut_off_reply_is_retried_and_the_whole_one_wins(monkeypatch):
    result, calls, cached = _run_extract([_CUT, _WHOLE], monkeypatch)
    assert len(calls) == 2
    assert _value(result["facts"].get("state_of_operations")) == "CO"
    assert result["facts"].get("wc_class_codes")
    assert result["flags"].get("has_workers_comp") is True
    assert len(cached) == 1, "a complete retry is cached like any complete reply"


def test_a_fragment_is_never_cached(monkeypatch):
    result, calls, cached = _run_extract([_CUT, _CUT], monkeypatch)
    assert len(calls) == 2
    assert _value(result["facts"].get("applicant_name")) == "CHOICE ELECTRIC LLC"
    assert cached == [], "a cut-off reply must not be served to the next upload"


def test_a_complete_first_reply_costs_one_call(monkeypatch):
    result, calls, cached = _run_extract([_WHOLE], monkeypatch)
    assert len(calls) == 1 and len(cached) == 1
    assert _value(result["facts"].get("state_of_operations")) == "CO"


# ── 4. ACORD 125: a cyber coverage part is not a line of business ───────────
# The live shape (805049a7): the cyber dec's one premium, $4,162 (ACE
# American), written against eight coverage parts. The policies table folded
# them into one Cyber row; ACORD 125 printed two of them as OTHER rows and its
# POLICY PREMIUM counted $4,162 three times ($66,709 against printed rows
# adding to $62,547).

import services.pdf_service as ps                                    # noqa: E402

with open(os.path.join(HERE, "fixtures", "choice_electric_805049a7_coverage_lines.json"),
          encoding="utf-8") as _fh:
    _CE_LINES = json.load(_fh)


def _f125(lines):
    return {"coverage_lines": copy.deepcopy(lines), "_form_id": "ACORD_125"}


def test_cyber_parts_are_not_other_rows():
    rows = ps._other_lob_rows(_f125(_CE_LINES))
    names = [r["name"] for r in rows]
    # 19 Oct 2026: the EBL coverage part is the GL policy's (Brent) - no row.
    assert names == ["Excess (Following Form) Liability"]
    assert [r["premium"] for r in rows] == ["$ 10,692"]


def test_the_total_is_the_rows_the_form_prints():
    f = _f125(_CE_LINES)
    printed = ps._printed_lob_premiums(f)
    assert sum(printed) == 57960                    # less the EBL part (19 Oct 2026)
    assert printed.count(4162) == 1, "the cyber premium is printed once"
    assert ps._resolve_estimated_total("Policy_Payment_EstimatedTotalAmount_A", f) == "$57,960"


def test_a_line_of_its_own_keeps_its_row_but_not_another_lines_premium():
    """A named line (EPLI) whose figure is a standard line's carrier and premium
    keeps its row; the premium belongs to the line that owns it."""
    lines = [
        {"line": "Commercial General Liability Coverage Part", "carrier": "Amerisure Insurance Company",
         "premium": "$16,818.00"},
        {"line": "Employment Practices Liability Coverage Part", "carrier": "Amerisure Insurance Company",
         "premium": "$16,818.00"},
    ]
    rows = ps._other_lob_rows(_f125(lines))
    # the row prints the LINE - "Coverage Part" is dropped (19 Oct 2026)
    assert rows == [{"name": "Employment Practices Liability", "premium": None}]


def test_an_odd_line_from_another_carrier_is_untouched():
    lines = [
        {"line": "Cyber Incident Response Team", "carrier": "ACE American Insurance Company",
         "premium": "$4,162.00"},
        {"line": "Employment Practices Liability Coverage Part", "carrier": "Federal Insurance Company",
         "premium": "$4,162.00"},
    ]
    rows = ps._other_lob_rows(_f125(lines))
    assert rows == [{"name": "Employment Practices Liability", "premium": "$4,162.00"}]


# ── 5. an answered cross-form issue leaves Warnings ─────────────────────────
# The upload copies each cross-form issue into structured_issues under its
# rule code; recalculations re-ran the rules but kept the copies, so the
# answered occupancy kept "Minimum Viable COPE: occupancy type" on screen.

import ast                                                           # noqa: E402

import services.cross_form_validator as cfv                         # noqa: E402
from services.issue_registry import retire_stopped_cross_form_issues  # noqa: E402

_OCC = ("Property submission missing Minimum Viable COPE: occupancy type. These fields are "
        "required to submit property to underwriting.")


def test_every_cross_form_rule_passes_a_literal_code():
    """rule_codes() reads the literals; a computed code would go unseen and
    its stale copy would never retire."""
    tree = ast.parse(_src(BACKEND, "services", "cross_form_validator.py"))
    calls = [n for n in ast.walk(tree)
             if isinstance(n, ast.Call) and getattr(n.func, "id", None) == "_issue"]
    assert len(calls) >= 50
    assert all(len(c.args) >= 2 and isinstance(c.args[1], ast.Constant) for c in calls)
    assert "minimum_viable_cope_missing" in cfv.rule_codes()
    assert len(cfv.rule_codes()) == len({c.args[1].value for c in calls})


def test_a_rule_that_stopped_firing_takes_its_copy_with_it():
    persisted = [
        {"code": "minimum_viable_cope_missing", "message": _OCC, "severity": "soft_warning"},
        {"code": "legacy_carrier_grade_cope", "message": "Carrier-Grade COPE incomplete", "severity": "soft_warning"},
        {"code": "doc_conflict_warn_x", "message": "two documents disagree", "severity": "soft_warning"},
        {"code": "unmapped_coverage_line", "message": "Coverage part not recognised: X", "severity": "advisory"},
        {"code": "ocr_low_confidence_fein", "message": "confirm the FEIN", "severity": "soft_warning"},
    ]
    kept = retire_stopped_cross_form_issues(persisted, [])
    assert [i["code"] for i in kept] == [
        "legacy_carrier_grade_cope", "doc_conflict_warn_x", "unmapped_coverage_line",
        "ocr_low_confidence_fein"]


def test_a_rule_still_firing_keeps_its_copy():
    persisted = [{"code": "minimum_viable_cope_missing", "message": _OCC}]
    fresh = [{"code": "minimum_viable_cope_missing", "message": _OCC, "type": "hard_stop"}]
    assert retire_stopped_cross_form_issues(persisted, fresh) == persisted


def test_a_rule_firing_with_a_new_sentence_retires_the_old_one():
    persisted = [{"code": "minimum_viable_cope_missing", "message": _OCC}]
    fresh = [{"code": "minimum_viable_cope_missing",
              "message": "Property submission missing Minimum Viable COPE: construction type."}]
    assert retire_stopped_cross_form_issues(persisted, fresh) == []


def test_the_recalculation_retires_the_answered_occupancy_card():
    row = _row(structured_issues=[
        {"code": "minimum_viable_cope_missing", "message": _OCC, "severity": "soft_warning",
         "forms": ["ACORD_140"]},
    ])
    row["facts"]["occupancy_type"] = {"value": "Warehouse or storage", "source": "producer"}
    s = _Session(row)
    s.run(arq.recalculate_session_scores, "sid-run7")
    assert not any(i.get("code") == "minimum_viable_cope_missing"
                   for i in s.store.get("structured_issues") or [])


# ── 6. a complete reply with one bad character keeps its facts ───────────────
# The real WC reply (b38a4367 / 805049a7 probe): finish_reason "stop", 3,768
# completion tokens, no reasoning - and a stray "{" before "target_markets",
# four closers from the end. The salvage gave up, the 3,000-character LLM repair
# kept 75 of 201 facts, and the class table, state and X-mod were lost on
# every run.

from utils.json_salvage import salvage_truncated_json               # noqa: E402

with open(os.path.join(HERE, "fixtures", "choice_electric_wc_reply_malformed_8oct.txt"),
          encoding="utf-8") as _fh:
    _WC_REPLY = _fh.read()


def test_the_live_reply_is_malformed_not_cut_off():
    with pytest.raises(ValueError):
        json.loads(_WC_REPLY)
    assert _WC_REPLY.rstrip().endswith("}}}}")


def test_the_salvage_keeps_everything_before_the_slip():
    got = salvage_truncated_json(_WC_REPLY)
    facts = got["facts"]
    assert len(facts) >= 200
    codes = [r["code"] for r in facts["wc_class_codes"]]
    assert codes == ["5190", "8742", "8810"]
    assert facts["state_of_operations"] == "CO"
    assert len(got["flags"]) >= 40


def test_the_parser_never_reaches_the_3000_character_repair(monkeypatch):
    calls = []

    async def _repair(*a, **k):
        calls.append(1)
        return "{}"

    monkeypatch.setattr(es, "groq_chat", _repair)
    r: dict = {}
    got = asyncio.run(es._safe_json_parse(_WC_REPLY, context="t", report=r))
    assert calls == []
    assert len(got["facts"]) >= 200 and r.get("partial") is True


def test_a_truncated_reply_is_salvaged_exactly_as_before():
    cut = '{"facts": {"applicant_name": "ORBIN CONTRACTING LLC", "total_payroll": "$39,300", "locations": ["Fargo'
    assert salvage_truncated_json(cut) == {"facts": {"applicant_name": "ORBIN CONTRACTING LLC",
                                                     "total_payroll": "$39,300"}}


# ── 7. a column heading is not the insured ──────────────────────────────────
# b38a4367: the Travelers Excess dec prints "INSURED'S NAME:" (redacted) above
# its billing headings "ACCT. EFF. PREMIUM / S.B. MO. DATE"; the model returned
# "S.B. MO." as the insured. It raised "Possible multiple submissions" over six
# documents of one insured, and won the merge as the package's applicant.

from services.normalization import is_not_a_party_name               # noqa: E402
from services.submission_integrity import assess_submission_integrity  # noqa: E402
from services.insured_scope import other_insured_documents          # noqa: E402

_EXCESS_TEXT = ("1. NAMED INSURED AND MAILING ADDRESS:\n2. THE NAMED INSURED IS A:\n"
                "X CORPORATION SOLE PROPRIETOR PARTNERSHIP OR JOINT VENTURE OTHER\n"
                "INSURED'S NAME:\nACCT. EFF. PREMIUM\nS.B. MO. DATE\n01/25 01/01/2025 10,692.00\n")


@pytest.mark.parametrize("value,expected", [
    ("S.B. MO.", True), ("ACCT. EFF.", True), ("Certificate Holder", True),
    ("CHOICE ELECTRIC LLC", False), ("J. Smith", False), ("U.S. Steel", False),
    ("A.B. Co.", False), ("AT&T", False), ("O.K. Tire", False), ("3M", False), ("", False),
])
def test_a_heading_names_nobody(value, expected):
    assert is_not_a_party_name(value) is expected


def _ce_docs():
    return [
        {"doc_id": "exc", "filename": "25-26 Excess Umbrella Policy.pdf", "doc_type": "dec_page",
         "text": _EXCESS_TEXT,
         "facts": {"applicant_name": {"value": "S.B. MO."}, "entity_type": {"value": "Corporation"},
                   "carrier_name": {"value": "TRAVELERS PROPERTY CASUALTY COMPANY OF AMERICA"}}},
        {"doc_id": "umb", "filename": "25-26 Umbrella Policy.pdf", "doc_type": "dec_page",
         "text": "Item 1. Insured Name:\nCHOICE ELECTRIC LLC\n",
         "facts": {"applicant_name": {"value": "CHOICE ELECTRIC LLC"}, "entity_type": {"value": "LLC"},
                   "carrier_name": {"value": "AMERISURE MUTUAL INSURANCE COMPANY"}}},
        {"doc_id": "pkg", "filename": "25-26 Package Policy.pdf", "doc_type": "dec_page",
         "text": "COMMERCIAL GENERAL LIABILITY COVERAGE PART", "facts": {}},
    ]


def test_integrity_sees_one_insured_and_no_entity_conflict():
    """The Excess dec ticks "X CORPORATION"; the insured's own name says LLC and
    settles it - once the heading is not taken for the Excess dec's own name.
    (This fixture's two carriers with no placed lines raise a separate carrier
    reason, which is not this test's subject.)"""
    r = assess_submission_integrity(_ce_docs())
    reasons = " | ".join(r.get("reasons") or []).lower()
    assert "applicants/insureds" not in reasons
    assert "entity type" not in reasons
    assert (r.get("signals") or {}).get("distinct_applicant_names") == 1


def test_a_heading_applicant_never_makes_a_document_anothers():
    docs = _ce_docs()
    assert other_insured_documents({"applicant_name": {"value": "S.B. MO."}}, docs) == []
    assert other_insured_documents({"applicant_name": {"value": "CHOICE ELECTRIC LLC"}}, docs) == []


def test_the_merge_elects_the_insured_not_the_heading():
    """Even with the heading's document as the PRIMARY - the case the stored
    session never exercised (its primary was the cyber dec)."""
    docs = copy.deepcopy(_ce_docs())
    mf, _flags = es.merge_facts(docs, docs[0])
    assert _value(mf.get("applicant_name")) == "CHOICE ELECTRIC LLC"
    assert "applicant_name" not in docs[0]["facts"], "the per-document copy is cleaned too"


def test_extraction_drops_a_heading_from_each_documents_own_facts():
    src = _src(BACKEND, "services", "extraction_pipeline.py")
    body = src[src.index("async def extract_document("):]
    body = body[:body.index("\nasync def ", 10)] if "\nasync def " in body[10:] else body
    assert "drop_non_party_names(" in body
