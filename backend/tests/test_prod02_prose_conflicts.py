"""PROD-02 - two documents printing different BOILERPLATE are not a conflict.

CLIENT, 2026-09-09: the pre-form IMPORTANT band - the 5-second "fix these first"
shortlist - led with

    "Conflicting values for Specific Wording Requirements across documents -
     Dec Page: If the insured's whereabouts for service of process cannot be
     determined... , Certificate of Insurance: If the certificate holder is an
     ADDITIONAL INSURED, the policy(ies) must have ADDITIONAL INSURED
     provisions or be endorsed... Fix: Review and confirm the correct value."

Neither side is a requirement anyone imposed on this insured. The first is a
service-of-process policy CONDITION; the second is the ACORD 25's own PREPRINTED
footer, printed on every certificate ever issued. There is no correct value to
confirm, the card carried no control to confirm it with, and it capped the SQS
at 85.

ROOT CAUSE - not the paragraph, the COMPARATOR. ``detect_source_conflicts``
compared normalised strings and read "not identical" as "conflict". Two
paragraphs are essentially never identical, so on a prose fact it fired every
time. ``fact_comparison.py``'s own header table has recorded this since C1
(2026-08-21) - of the five places that decided "do these documents disagree?",
this one had **none** - and it was the only one never migrated. The rule it was
missing already existed and already shipped: ``fact_equivalence._PROSE_WORD_
FLOOR``, *"nobody picks between two true paragraphs"* -> INCOMPARABLE.

THE FIX IS A SECOND GATE, NOT A REPLACEMENT. The original distinct-normalised
test still runs first; the door is asked only when that test already says
"conflict". Both are suppressive, so nothing suppressed today can start firing.
The first attempt DID replace it and re-opened the carrier-alias suppression
("Employers Mutual Casualty Company" vs "EMC Property & Casualty Company"),
because the door groups entity names on ``strict_entity_key`` and deliberately
NOT on ``normalize_carrier`` (Round 10 fix 46). The suite caught it; the
ordering is pinned below so it cannot be lost again.
"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from services import fact_comparison
from services.extraction_service import detect_source_conflicts
from services.issue_registry import build_grouped_view, make_issue


# ── The client's LITERAL values (replay-verbatim rule) ──────────────────────
DEC_CLAUSE = (
    "If the insured's whereabouts for service of process cannot be determined "
    "through reasonable effort, the insured agrees to designate and irrevocably "
    "appoint us as the agent of the insured for service of process, pleadings or "
    "other filings in a civil action brought against the insured."
)
COI_FOOTER = (
    "If the certificate holder is an ADDITIONAL INSURED, the policy(ies) must "
    "have ADDITIONAL INSURED provisions or be endorsed. If SUBROGATION IS "
    "WAIVED, subject to the terms and conditions of the policy, certain policies "
    "may require an endorsement."
)


def _doc(facts, doc_type="dec_page"):
    return {"doc_type": doc_type, "facts": facts}


def _two_docs(dec_facts, coi_facts):
    return [_doc(dec_facts), _doc(coi_facts, "certificate")]


def _messages(docs):
    return detect_source_conflicts(docs)


# ── 1. The reported card is gone ───────────────────────────────────────────

def test_the_clients_two_boilerplate_paragraphs_raise_no_card():
    msgs = _messages(_two_docs(
        {"risk_transfer": {"specific_wording_requirements": DEC_CLAUSE}},
        {"risk_transfer": {"specific_wording_requirements": COI_FOOTER}},
    ))
    assert msgs == [], msgs


def test_the_same_paragraphs_as_a_TOP_LEVEL_fact_also_raise_no_card():
    """The fact is nested under risk_transfer today, but the defect belongs to
    the comparator, not to one container - a scalar prose fact must behave the
    same way or the fix is only as wide as the reported shape."""
    assert _messages(_two_docs(
        {"additional_remarks_text": DEC_CLAUSE},
        {"additional_remarks_text": COI_FOOTER},
    )) == []


def test_it_does_not_reach_the_important_band_any_more():
    """Assert through the layer the SCREEN reads, not just the primitive."""
    msgs = _messages(_two_docs(
        {"risk_transfer": {"specific_wording_requirements": DEC_CLAUSE},
         "num_employees": "47"},
        {"risk_transfer": {"specific_wording_requirements": COI_FOOTER},
         "num_employees": "62"},
    ))
    issues = [make_issue("source_conflict_x", "soft_warning", m) for m in msgs]
    view = build_grouped_view(issues, [], list(msgs))
    printed = " ".join(
        c["primary_message"] for c in view["important"]
    ) + " ".join(
        c["primary_message"]
        for tier in view["warnings"].values() for c in tier
    )
    assert "Specific Wording" not in printed
    # ...and the real conflict that shared the package is still on screen.
    assert "Num Employees" in printed


# ── 2. Nothing genuine was removed ─────────────────────────────────────────

@pytest.mark.parametrize("key,a,b", [
    ("num_employees",  "47", "62"),
    ("total_revenue",  "$5,000,000", "$7,200,000"),
    ("effective_date", "07/15/2025", "09/01/2025"),
    ("policy_number",  "6E7-40-02---26", "6J7-40-02---26"),
    ("umbrella_limit", "$3,000,000", "$1,000,000"),
    ("construction_type", "Frame", "Masonry"),
])
def test_a_real_disagreement_still_raises_a_card(key, a, b):
    msgs = _messages(_two_docs({key: a}, {key: b}))
    assert len(msgs) == 1, msgs
    assert a in msgs[0] and b in msgs[0]


@pytest.mark.parametrize("subkey,a,b", [
    ("mortgagee_name", "First National Bank", "Wells Fargo Bank NA"),
    ("certificate_holder_name", "ABC Corporation", "XYZ Holdings LLC"),
    ("loss_payee_name", "Midwest Leasing Co", "Summit Equipment Finance"),
])
def test_a_real_disagreement_inside_risk_transfer_still_raises_a_card(subkey, a, b):
    """The prose sub-key going quiet must not silence its NEIGHBOURS - the
    structured-dict path compares each sub-question independently and that is
    the property that keeps it useful."""
    msgs = _messages(_two_docs(
        {"risk_transfer": {subkey: a, "specific_wording_requirements": DEC_CLAUSE}},
        {"risk_transfer": {subkey: b, "specific_wording_requirements": COI_FOOTER}},
    ))
    assert len(msgs) == 1, msgs
    assert a in msgs[0] and b in msgs[0]
    assert "Specific Wording" not in msgs[0]


@pytest.mark.parametrize("key", [
    "operations_description", "additional_remarks_text", "account_description",
    "certificate_description_of_operations", "wc_description_of_operations",
    "garage_operations_type",
])
def test_a_narrative_fact_no_longer_competes_with_itself(key):
    """The client's OWN 2026-08-17 ruling, now applied consistently.

        "A paragraph containing policy numbers, dates, limits, premiums,
         exclusions, etc. should not be treated as one competing value."

    ``fact_equivalence`` has honoured that since C1 and the Data Consistency
    picker has always asked it. ``detect_source_conflicts`` was the one place
    that did not, so the same package could be quiet on one screen and carry a
    warning on the next. These are the SIX narrative-kind facts in the registry -
    the whole behaviour change, listed rather than implied. A genuinely different
    INSURED is still caught, by `applicant_name`, which is a hard stop."""
    assert _messages(_two_docs(
        {key: "Commercial roofing contractor performing re-roofing"},
        {key: "Full service restaurant and bar with live entertainment"},
    )) == []


@pytest.mark.parametrize("key,a,b", [
    ("construction_type", "Frame", "Masonry"),
    ("entity_type",       "LLC", "Corporation"),
    ("valuation_method",  "Replacement Cost", "Actual Cash Value"),
    ("occupancy_type",    "Owner Occupied", "Tenant"),
])
def test_an_ENUMERATED_type_field_is_still_compared(key, a, b):
    """The boundary that matters. 39 facts classify as free text and most are
    ENUMERATED terms where disagreement is real and material - a "looks like a
    phrase" heuristic would silence every one of them. They must keep competing,
    and `fact_equivalence.test_no_enumerated_type_field_is_treated_as_narrative`
    guards the declaration from the other side."""
    msgs = _messages(_two_docs({key: a}, {key: b}))
    assert len(msgs) == 1, msgs
    assert a in msgs[0] and b in msgs[0]


# ── 3. Gate 1 survived - the regression the first attempt shipped ──────────

def test_carrier_alias_is_still_suppressed_by_the_original_gate():
    """The door groups entity names on strict_entity_key, NOT normalize_carrier
    (its own comment: Round 10 fix 46). Replacing gate 1 instead of adding to it
    re-opened this. Both these names normalise to the same carrier."""
    assert _messages(_two_docs(
        {"carrier_name": "Employers Mutual Casualty Company"},
        {"carrier_name": "EMC Property & Casualty Company"},
    )) == []


@pytest.mark.parametrize("key,a,b", [
    ("total_revenue",  "$5,000,000", "5000000"),
    ("effective_date", "07/15/2025", "2025-07-15"),
])
def test_formatting_only_differences_are_still_suppressed(key, a, b):
    assert _messages(_two_docs({key: a}, {key: b})) == []


# ── 4. The seam, not the function (C25 / "fix the layer the screen reads") ──

def test_the_door_is_actually_consulted(monkeypatch):
    """An offline probe of the comparator proves the COMPARATOR. This proves the
    SEAM: a refactor that quietly unwires the door has to fail a test."""
    seen = []
    real = fact_comparison.conflict

    def spy(fact_key, values, context=None):
        seen.append(fact_key)
        return real(fact_key, values, context)

    monkeypatch.setattr(fact_comparison, "conflict", spy)
    _messages(_two_docs(
        {"num_employees": "47", "risk_transfer": {"mortgagee_name": "A Bank"}},
        {"num_employees": "62", "risk_transfer": {"mortgagee_name": "B Bank"}},
    ))
    assert "num_employees" in seen, "the scalar path bypassed the door"
    assert "risk_transfer_mortgagee_name" in seen, "the dict path bypassed the door"


def test_the_door_can_only_remove_a_card_never_add_one(monkeypatch):
    """Gate ordering, pinned as a property: with the door forced to say
    "conflict" about everything, output must still be exactly what gate 1
    allows - the carrier alias and the formatting-only pair stay silent."""
    monkeypatch.setattr(fact_comparison, "conflict",
                        lambda *a, **k: True)
    assert _messages(_two_docs(
        {"carrier_name": "Employers Mutual Casualty Company",
         "total_revenue": "$5,000,000"},
        {"carrier_name": "EMC Property & Casualty Company",
         "total_revenue": "5000000"},
    )) == []


def test_a_broken_door_keeps_todays_verdict_rather_than_dropping_a_conflict():
    """Fail-open direction. If the door raises, the caller keeps the answer gate
    1 already reached - a real conflict is never lost to an import error."""
    from services import extraction_service as es

    def boom(*_a, **_k):
        raise RuntimeError("door unavailable")

    original = fact_comparison.conflict
    fact_comparison.conflict = boom
    try:
        msgs = es.detect_source_conflicts(
            _two_docs({"num_employees": "47"}, {"num_employees": "62"}))
    finally:
        fact_comparison.conflict = original
    assert len(msgs) == 1 and "47" in msgs[0] and "62" in msgs[0]
