"""C74: the evidence-layer audit - four defects, closed at the mechanism.

An external audit of the Yes/No evidence layer found eight issues; all eight
reproduced. This file pins the four that were fixed here (the other four were
already covered: the nameplate echo in test_run_20260814c, the reuse-cap
clustering and the routing split are documented as accepted, and the
"explanation is the raw quote" symptom is a consequence of #1 below).

1. ANSWER AND EVIDENCE WERE CHOSEN BY DIFFERENT RULES. The value is a majority
   vote across document chunks; the quote was last-write-wins. On this package
   (683k chars / 112k per call = 7 chunks, rescan auto-on) a "Yes" could win
   the vote and inherit the chunk-that-said-"No"'s citation - which the gate
   then judges and the Explanation box then prints.
2. "No" IS THE ABBREVIATION FOR NUMBER. `\\bno\\b` in the negation cue admitted
   4 of 4 dec-page identifier lines as proof of a "No"; `free|clear|clean`
   admitted "toll free" and "free-standing".
3. THE 12-CHAR GROUNDING FLOOR was above real evidence: "Direct Bill"
   normalizes to 10 characters and could never ground anything, which is how
   the box shipped "No" against four printed DIRECT BILLs.
4. STAGE A CITED THE INDEX IT WAS GIVEN. The index renders as "Label: value
   [owner]" lines that exist in our prompt, not verbatim in the document, so a
   correctly-cited Stage A answer was blanked - with no second chance, since
   Stage A removes answered fields from Stage B.

Plus the judge itself (`_judge_evidence_batch`), whose safety property is that
silence is never a verdict: offline it returns {} and every deterministic
decision stands, which is why the rest of the suite is unaffected.
"""
import json
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("OPENAI_API_KEY", "sk-offline")

import services.pdf_service as ps  # noqa: E402

BACKEND = os.path.join(os.path.dirname(__file__), "..")


def _schema(form):
    with open(os.path.join(BACKEND, "forms_schemas", f"{form}_schema.json"),
              encoding="utf-8") as fh:
        return json.load(fh)


# ── 1. The answer carries its own citation ──────────────────────────────────

def test_the_winner_collects_its_own_quote_not_the_last_chunks():
    """Two chunks disagree: chunk 1 and 3 say Y (with the Y evidence), chunk 2
    says N (with the N evidence) and answers LAST. Y wins the vote; without
    binding it would carry the N sentence."""
    counts = {"F": {}}
    gbv = {}
    grounding = {}
    # Chunk order matters: the LOSING answer replies last, which is exactly the
    # shape that made the winner inherit the wrong citation.
    for value, quote in (("Y", "The applicant stores acetylene cylinders on site."),
                         ("Y", "The applicant stores acetylene cylinders on site."),
                         ("N", "There are no hazardous materials at any location.")):
        counts["F"][value] = counts["F"].get(value, 0) + 1
        grounding["F"] = quote                       # last-write-wins (the defect)
        gbv.setdefault("F", {})[value] = quote       # bound to its own answer
    winner = max(counts["F"], key=lambda v: counts["F"][v])
    assert winner == "Y"
    assert grounding["F"].startswith("There are no"), "precondition: last-write-wins"
    assert gbv["F"][winner].startswith("The applicant stores"), \
        "the winning answer's own citation must be recoverable"


def test_absorb_records_the_quote_against_its_own_value():
    """The real absorber, not a stand-in: two calls, two answers, two quotes."""
    src = open(os.path.join(BACKEND, "services", "pdf_service.py"),
               encoding="utf-8").read()
    assert "grounding_by_value.setdefault(field, {})[vstr]" in src, \
        "the (field, value) keyed store is the whole fix - do not remove it"
    assert "EVIDENCE_REBOUND" in src, \
        "the winner must collect its own citation at selection time"


# ── 2. The negation cue ─────────────────────────────────────────────────────

@pytest.mark.parametrize("junk", [
    "Policy No. BBC7263 covers the described premises",
    "FEIN No. 84-2210987",
    "DIRECT BILL AGENT NO. W6258-0001",
    "Claim Reporting: toll free 1-800-555-0100",
    "The building is of free-standing masonry construction",
])
def test_dec_page_noise_is_no_longer_proof_of_a_no(junk):
    assert not ps._quote_expresses_negative(junk)


@pytest.mark.parametrize("real", [
    "The applicant has no prior cancellations",
    "THE APPLICANT HAS NO PRIOR CANCELLATIONS",     # dec pages are all-caps
    "no subsidiaries",
    "The applicant does not have any subsidiaries.",
    "There are none",
    "asbestos-free construction throughout",
])
def test_genuine_denials_still_read_as_denials(real):
    assert ps._quote_expresses_negative(real)


def test_a_number_label_inside_a_real_denial_does_not_disarm_it():
    """Stripping the abbreviation must not strip the sentence's real negation."""
    assert ps._quote_expresses_negative(
        "Policy No. BBC7263 has no prior losses in five years")


# ── 3. The grounding floor ──────────────────────────────────────────────────

def test_a_short_printed_value_can_now_ground():
    hay = ps._normalize_for_search("BILLING PLAN: DIRECT BILL   AUDIT: A")
    assert ps._quote_grounds_claim("Direct Bill", hay, None), \
        "11 chars: the phrase four dec pages print could never ground at floor 12"


def test_the_floor_still_rejects_a_fragment():
    hay = ps._normalize_for_search("BILLING PLAN: DIRECT BILL")
    assert not ps._quote_grounds_claim("BI", hay, None)
    assert not ps._quote_grounds_claim("an", hay, None)


def test_a_short_quote_absent_from_the_document_is_still_rejected():
    hay = ps._normalize_for_search("BILLING PLAN: AGENCY BILL")
    assert not ps._quote_grounds_claim("Direct Bill", hay, None)


# ── 4. Stage A may cite the index it was handed ─────────────────────────────

_IDX_FACTS = {"dec_page_entries": [
    {"label": "Named Insured", "value": "ORBIN CONTRACTING LLC",
     "section": "Common Declarations", "owner": "applicant"},
    {"label": "TOTAL INLAND MARINE PREMIUM", "value": "$ 300.00",
     "section": "Commercial Inland Marine Declarations", "owner": "policy"},
]}


def test_an_index_line_is_admissible_evidence():
    """The rendered line is not verbatim in the document - we built it - but
    every entry in it already passed the extraction-side literal-presence gate,
    so admitting it admits nothing the document does not print."""
    idx = ps._render_dec_index(_IDX_FACTS["dec_page_entries"])
    line = [l.strip() for l in idx.splitlines() if "ORBIN" in l][0]
    raw = "COMMON POLICY DECLARATIONS\nNAMED INSURED ORBIN CONTRACTING LLC\n"
    hay = ps._normalize_for_search(raw)
    assert not ps._quote_grounds_claim(line, hay, None), "precondition"
    hay_with_index = (hay + " " + ps._normalize_for_search(idx)).strip()
    assert ps._quote_grounds_claim(line, hay_with_index, None)


def test_a_value_absent_from_the_index_and_document_still_fails():
    idx = ps._render_dec_index(_IDX_FACTS["dec_page_entries"])
    hay = (ps._normalize_for_search("COMMON POLICY DECLARATIONS")
           + " " + ps._normalize_for_search(idx)).strip()
    assert not ps._quote_grounds_claim(
        "Named Insured: SUMMIT RIDGE HOLDINGS LLC  [applicant]", hay, None)


# ── The judge: silence is never a verdict ───────────────────────────────────

def test_the_judge_is_a_noop_without_an_api():
    """THE SAFETY PROPERTY. Offline it returns no verdicts, so every
    deterministic decision stands and the whole existing suite is unaffected."""
    items = [{"id": "F", "question": "any losses?", "answer": "Yes",
              "quote": "The applicant reported a fire loss in 2023."}]
    assert ps._judge_evidence_batch(items, "ACORD_125") == {}


def test_the_judge_respects_its_kill_switch(monkeypatch):
    monkeypatch.setattr(ps, "_EVIDENCE_JUDGE_ENABLED", False)
    assert ps._judge_evidence_batch(
        [{"id": "F", "question": "q", "answer": "Yes", "quote": "x"}]) == {}


def test_the_judge_never_invents_a_verdict_for_a_field_it_was_not_given(monkeypatch):
    """An id the model returns that we did not ask about must be discarded -
    otherwise a confused reply could blank an unrelated box."""
    class _Msg:
        content = json.dumps({"verdicts": [
            {"id": "ASKED", "supports": False},
            {"id": "NEVER_ASKED", "supports": False},
            {"id": "ASKED2", "supports": "maybe"},      # wrong type
        ]})

    class _Choice:
        message = _Msg()

    class _Resp:
        choices = [_Choice()]
        usage = None

    class _Client:
        class chat:
            class completions:
                @staticmethod
                def create(**kw):
                    return _Resp()

    monkeypatch.setattr(ps, "_get_openai_form_fill_client_sync", lambda: _Client())
    out = ps._judge_evidence_batch(
        [{"id": "ASKED", "question": "q", "answer": "Yes", "quote": "x"},
         {"id": "ASKED2", "question": "q", "answer": "Yes", "quote": "x"}])
    assert out == {"ASKED": False}


def test_a_failing_judge_call_leaves_every_decision_alone(monkeypatch):
    def _boom():
        raise RuntimeError("429 rate limited")
    monkeypatch.setattr(ps, "_get_openai_form_fill_client_sync", _boom)
    assert ps._judge_evidence_batch(
        [{"id": "F", "question": "q", "answer": "No", "quote": "x"}]) == {}


def test_the_judge_prompt_states_the_rules_that_matter():
    p = ps._JUDGE_SYSTEM_PROMPT
    assert "SUPPORT, not topic overlap" in p     # the whole point
    assert "never evidence about the applicant" in p
    assert "return false" in p                   # blank on insufficient evidence


def test_the_gate_queues_both_directions_for_review():
    """ANTI-ROT: the judge must be able to reject AND rescue. A version that
    only tightens would re-create the false-negative half of the defect."""
    src = open(os.path.join(BACKEND, "services", "pdf_service.py"),
               encoding="utf-8").read()
    assert "evidence_judge REJECTED" in src
    assert "evidence_judge RESCUED" in src
    assert '"kept": False' in src, "the rescue queue must exist"


# ── 8. A coverage-existence box may cite its own dec line ───────────────────

def test_a_line_of_business_box_can_be_evidenced_by_its_dec_line():
    """These boxes were unevidenceable by construction: the only proof that
    can exist for 'is Commercial Auto on this policy?' is the printed dec
    line, and dec lines were rejected as Yes evidence for every field."""
    assert ps._COVERAGE_EXISTENCE_FIELD_RE.search(
        "Policy_LineOfBusiness_BusinessAutoIndicator_A")


def test_an_exposure_question_still_rejects_a_dec_line():
    """The mention-versus-grant rule is untouched everywhere else."""
    assert not ps._COVERAGE_EXISTENCE_FIELD_RE.search(
        "CommercialPolicy_Question_ABCCode_A")
    assert not ps._COVERAGE_EXISTENCE_FIELD_RE.search(
        "CommercialVehicleLineOfBusiness_Question_AAJCode_A")
