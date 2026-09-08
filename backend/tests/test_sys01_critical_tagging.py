"""SYS-01 (P0 systemic) - Critical tagging in the client questionnaire.

CLIENT, verbatim
----------------
WHAT WE OBSERVED: *"The live test identified specific client questions that
should be treated as Critical when the information is still unresolved,
including core items such as FEIN/Tax ID, annual revenue, employee count, and
NAICS or SIC. The fact that several of these happened to appear first in the
test is incidental; list position does not make a question Critical."*

ACCEPTANCE: *"Apply the Critical tag to the business-defined questions when
their underlying fact is still unfulfilled. If the fact has already been
satisfied by the submission or a prior answer, it should not remain Critical.
Critical status should be driven by the question/fact rule, not by the order in
which the question appears."*

THE DEFECT
----------
`priority` was a STATIC tier label - Critical meant "this fact is in SQS Tier
1", and nothing more. On the reported run every Tier 1 fact was present, so the
Send-to-Client modal reported **0 Critical** and printed *"All critical fields
were already answered from your uploaded documents"* while the pre-form card on
the same session printed *"Key details missing: FEIN / Tax ID, Annual revenue,
Number of employees, NAICS or SIC industry code"*. Two screens, one fact set,
opposite verdicts.

The four the client named are exactly the four Tier 2 entries that were missing
on that run - he read his own "Key details missing" line back to us. So the rule
is "required AND still missing", not a list of four names, and these tests are
written to fail a fix that only satisfies the reported example.

OWNER RULINGS PINNED HERE
-------------------------
  * *"keep the list 1 as it is for critical and add more to it"* - the change is
    ADDITIVE. Nothing that is Critical today stops being Critical.
  * *"keep them in agency and put a critical tag on naic and sic as well"* -
    NAICS / SIC keep the producer audience the client mandated on 2026-08-12
    (*"those come from the producer or underwriter"*) and gain the Critical flag
    inside the Agency bucket. They are never auto-sent to the insured.
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("OPENAI_API_KEY", "sk-offline")

import services.sqs_service as sq                                  # noqa: E402
from services.question_classifier import (                         # noqa: E402
    CRITICAL_FIELDS, PRIORITY_CRITICAL, PRIORITY_IMPORTANT, PRIORITY_OPTIONAL,
    apply_default_selection, classify_question, decorate_questions,
)

# The reported session: Tier 1 complete, plus the two Tier 2 facts the client's
# own Review card listed as "in place". Everything else is genuinely missing.
LIVE_FACTS = {
    "applicant_name":         "ORBIN CONTRACTING LLC",
    "mailing_address":        "4800 Dahlia St D13, Denver, CO 80216",
    "entity_type":            "LLC",
    "effective_date":         "07/15/2025",
    "lines_of_business":      "General Liability, Commercial Auto",
    "contact_name":           "J. Smith",
    "operations_description": "Roofing and general contracting for commercial buildings",
    "years_in_business":      "12",
}

# The client's literal "Key details missing" line from the screenshot.
LIVE_MISSING_LABELS = [
    "FEIN / Tax ID", "Annual revenue", "Number of employees",
    "NAICS or SIC industry code",
]


def _q(key, forms=("ACORD_125",), **extra):
    q = {"field_name": key, "_canonical_key": key, "question": "?",
         "_is_curated_client": True, "form_ids": list(forms)}
    q.update(classify_question(key, list(forms), is_curated_client=True,
                               canonical_key=key))
    q.update(extra)
    return q


def _decorate(keys, facts, flags=None, **kw):
    qs = [_q(k) for k in keys]
    decorate_questions(qs, facts=facts, flags=flags or {}, **kw)
    return {q["field_name"]: q for q in qs}


# -- The reported case, with the client's literal values ----------------------

def test_the_reported_session_produces_the_clients_four_criticals():
    """Must never fail. This is the screenshot."""
    out = _decorate(
        ["fein", "total_revenue", "num_employees", "naics_code", "sic_code"],
        LIVE_FACTS,
    )
    for key in ("fein", "total_revenue", "num_employees"):
        assert out[key]["priority"] == PRIORITY_CRITICAL, key
        assert out[key]["bucket"] == "client", key
    for key in ("naics_code", "sic_code"):
        assert out[key]["priority"] == PRIORITY_CRITICAL, key
        assert out[key]["bucket"] == "agency", (
            key + " must stay the producer's - client PART 13, 2026-08-12")


def test_the_two_tier2_facts_the_run_already_had_are_not_critical():
    """He named four, not six. The other two were satisfied."""
    out = _decorate(["operations_description", "years_in_business"], LIVE_FACTS)
    for key, q in out.items():
        assert q["priority"] != PRIORITY_CRITICAL, key


def test_the_key_details_card_and_the_critical_rule_name_the_same_gaps():
    """The two screens are projections of ONE calculation, so they cannot
    disagree. This is the whole fix, asserted end to end."""
    missing_labels = sq.key_details(LIVE_FACTS, {})["missing"]
    assert set(LIVE_MISSING_LABELS) <= set(missing_labels)
    keys = sq.core_missing_fact_keys(LIVE_FACTS, {})
    assert {"fein", "total_revenue", "num_employees", "naics_code",
            "sic_code"} <= keys


# -- Additive: nothing that is Critical today stops being Critical ------------

def test_every_existing_critical_field_is_still_critical():
    """Owner: 'keep the list 1 as it is for critical and add more to it'."""
    out = _decorate(sorted(CRITICAL_FIELDS), {})
    for key in sorted(CRITICAL_FIELDS):
        assert out[key]["priority"] == PRIORITY_CRITICAL, key


_RANK = {PRIORITY_CRITICAL: 0, PRIORITY_IMPORTANT: 1, PRIORITY_OPTIONAL: 2,
         "internal": 3, "suppressed": 4}

_WIDE_KEYS = sorted(CRITICAL_FIELDS | {
    "fein", "total_revenue", "num_employees", "naics_code", "sic_code",
    "dba_name", "total_payroll", "gl_each_occurrence", "operations_description",
    "years_in_business", "producer_name", "expiration_date", "wc_payroll",
})


def _decorate_without_the_new_pass(keys, facts, monkeypatch):
    """Exactly today's pipeline minus the SYS-01 promotion - i.e. the behaviour
    that shipped before this change. Isolating it matters: `apply_eligibility`
    legitimately re-routes questions to the producer (client 4.4 / 9.1) and
    legitimately demotes a contact question whose requirement is already met
    (client 9.1). Comparing raw `classify_question` output against the finished
    question would blame this pass for both."""
    import services.question_classifier as _qc
    monkeypatch.setattr(_qc, "_promote_missing_core_requirements",
                        lambda *a, **k: None)
    qs = [_q(k) for k in keys]
    decorate_questions(qs, facts=facts, flags={})
    return {q["field_name"]: q for q in qs}


@pytest.mark.parametrize("facts", [{}, LIVE_FACTS, {"sic_code": "1761"}])
def test_the_promotion_only_ever_raises_a_priority(facts, monkeypatch):
    """Owner: 'keep the list 1 as it is for critical and add more to it'.

    Asserted against the PRE-CHANGE pipeline, not against a partial stage, so a
    regression cannot hide behind another layer's legitimate demotion."""
    before = _decorate_without_the_new_pass(_WIDE_KEYS, facts, monkeypatch)
    before = {k: dict(v) for k, v in before.items()}
    monkeypatch.undo()
    after = _decorate(_WIDE_KEYS, facts)
    for k in _WIDE_KEYS:
        assert _RANK.get(after[k]["priority"], 5) <= _RANK.get(before[k]["priority"], 5), (
            k + " was demoted from " + before[k]["priority"] + " to " + after[k]["priority"])
        assert after[k]["audience"] == before[k]["audience"], (
            k + " changed audience - the pass must never re-route")
        assert after[k]["bucket"] == before[k]["bucket"], (
            k + " changed bucket - the pass must never re-route")


def test_the_promotion_function_is_additive_in_isolation():
    """Unit-level twin of the above, driving the pass directly."""
    from services.question_classifier import _promote_missing_core_requirements
    qs = [_q(k) for k in _WIDE_KEYS]
    before = [dict(q) for q in qs]
    _promote_missing_core_requirements(qs, {}, {})
    for was, now in zip(before, qs):
        assert now["audience"] == was["audience"], now["field_name"]
        assert now["bucket"] == was["bucket"], now["field_name"]
        assert _RANK.get(now["priority"], 5) <= _RANK.get(was["priority"], 5),             now["field_name"]
        if now["priority"] != was["priority"]:
            assert now["priority"] == PRIORITY_CRITICAL
            assert now.get("core_requirement") is True


# -- Acceptance criterion 2: satisfied means not Critical ---------------------

@pytest.mark.parametrize("value", [
    "12-3456789",                                       # an ordinary answer
    {"value": "84-2210987", "source": "client_arq"},    # a prior answer
    {"value": "N/A", "source": "client_arq"},           # an answered ABSENCE
])
def test_a_satisfied_fact_is_never_critical(value):
    facts = dict(LIVE_FACTS)
    facts["fein"] = value
    out = _decorate(["fein"], facts)
    assert out["fein"]["priority"] != PRIORITY_CRITICAL


def test_a_not_applicable_fact_is_never_critical():
    """C3 3.6 removes N/A from the denominator, so it is not owed at all."""
    facts = dict(LIVE_FACTS)
    facts["total_revenue"] = {"value": "", "not_applicable": True}
    out = _decorate(["total_revenue"], facts)
    assert out["total_revenue"]["priority"] != PRIORITY_CRITICAL


@pytest.mark.parametrize("kw,reason", [
    ({"present_fact_keys": {"fein"}}, "already_provided"),
    ({"narrative_components": {"operations": True}}, "stated_in_narrative"),
])
def test_a_question_we_already_have_the_answer_to_is_never_promoted(kw, reason):
    key = "fein" if reason == "already_provided" else "operations_description"
    out = _decorate([key], {}, **kw)
    assert out[key]["suppressed_reason"] == reason
    assert out[key]["priority"] != PRIORITY_CRITICAL


def test_one_contact_method_satisfies_the_whole_contact_requirement():
    """Client 9.1. The scorer credits it, so the questionnaire must too - and
    `question_eligibility` demotes these by the same rule. A promotion pass that
    re-raised them would silently undo that."""
    facts = dict(LIVE_FACTS)
    facts["contact_phone"] = "303-555-0175"
    out = _decorate(["contact_name", "contact_email"], facts)
    for key, q in out.items():
        assert q["priority"] != PRIORITY_CRITICAL, key


# -- The paired requirements --------------------------------------------------

def test_a_stated_sic_code_stops_naics_being_critical():
    """Client 3.13 - the two codes are interchangeable. A per-key rule would
    have raised a Critical for a requirement the submission already meets."""
    facts = dict(LIVE_FACTS)
    facts["sic_code"] = "1761"
    out = _decorate(["naics_code", "sic_code"], facts)
    for key, q in out.items():
        assert q["priority"] != PRIORITY_CRITICAL, key


def test_both_codes_absent_makes_both_critical():
    out = _decorate(["naics_code", "sic_code"], LIVE_FACTS)
    for key, q in out.items():
        assert q["priority"] == PRIORITY_CRITICAL, key


def test_the_agencys_own_name_is_never_critical():
    """`producer_name` is a Tier 1 SCORING field and has been excluded from
    CRITICAL_FIELDS since the taxonomy shipped. This door must not reverse a
    decision it was never asked to revisit."""
    assert "producer_name" not in sq.core_missing_fact_keys({}, {})
    out = _decorate(["producer_name"], {})
    assert out["producer_name"]["priority"] != PRIORITY_CRITICAL


# -- "List position does not make a question Critical" ------------------------

def test_priority_is_independent_of_list_position():
    keys = ["fein", "dba_name", "total_revenue", "naics_code", "num_employees",
            "years_in_business", "total_payroll", "applicant_name"]
    forward = _decorate(keys, LIVE_FACTS)
    backward = _decorate(list(reversed(keys)), LIVE_FACTS)
    for k in keys:
        assert forward[k]["priority"] == backward[k]["priority"], k


# -- Routing / send safety ----------------------------------------------------

def test_an_agency_critical_is_never_pre_selected_for_the_client():
    """The Critical flag tells the PRODUCER to act. It must not put a code the
    insured cannot answer into the send list."""
    qs = [_q(k) for k in ("fein", "naics_code", "sic_code")]
    decorate_questions(qs, facts=LIVE_FACTS, flags={})
    apply_default_selection(qs)
    by = {q["field_name"]: q for q in qs}
    assert by["fein"]["default_selected"] is True
    for key in ("naics_code", "sic_code"):
        assert by[key]["default_selected"] is False, key


def test_underwriting_and_never_send_buckets_are_never_promoted():
    fax = _q("Producer_FaxNumber")
    fax["_canonical_key"] = "fein"          # worst case: a core key on a fax field
    xform = _q("total_revenue")
    xform["_is_cross_form"] = True
    xform["audience"], xform["bucket"] = "internal", "underwriting"
    decorate_questions([fax, xform], facts=LIVE_FACTS, flags={})
    assert fax["priority"] != PRIORITY_CRITICAL
    assert xform["bucket"] == "underwriting"


def test_the_critical_badge_is_rebuilt_not_left_stale():
    out = _decorate(["fein", "naics_code"], LIVE_FACTS)
    assert out["fein"]["score_impact"]["submission_readiness"] is True
    assert "Submission readiness" in out["fein"]["score_impact"]["labels"]
    assert out["fein"]["score_impact"]["points"] == 15
    # An agency question does not carry the client SQS badge.
    assert out["naics_code"]["score_impact"]["sqs"] is False


# -- Anti-rot: the two views must stay projections of one rule ----------------

def test_every_missing_label_resolves_to_at_least_one_fact_key():
    """Fails the build if a future checklist entry is added to the LABEL view
    without giving the KEY view anything to promote - which is how the two
    screens drifted apart in the first place."""
    for facts in ({}, LIVE_FACTS, {"sic_code": "1761"}):
        t1_missing = sq._tier1_entries(facts, {})[1]
        t2_missing = sq._tier2_entries(facts)[1]
        for keys, label in list(t1_missing) + list(t2_missing):
            assert keys and all(isinstance(k, str) and k for k in keys), label
        labels = sq.key_details(facts, {})["missing"]
        expected = [lbl for _k, lbl in t1_missing] + [lbl for _k, lbl in t2_missing]
        assert labels == expected


def test_label_view_is_unchanged_by_the_refactor():
    """`check_tier1` / `check_tier2` / `key_details` are the score's inputs.
    The key view was added beside them, never in place of them."""
    ok, missing = sq.check_tier1(LIVE_FACTS, {})
    assert missing == ["Producer / Agency name"] and ok is False
    score, t2_missing = sq.check_tier2(LIVE_FACTS)
    assert t2_missing == LIVE_MISSING_LABELS
    assert score == round(100 - 4 * (100 / 6))


def test_a_schedule_question_floor_never_clobbers_a_critical():
    """`_finalize_schedule_taxonomy` runs AFTER decoration and used to write
    IMPORTANT unconditionally, which would silently defeat this rule the day a
    schedule-backed fact joins the checklist."""
    from services.arq_service import _finalize_schedule_taxonomy
    q = {"field_type": "schedule", "schedule_key": "locations",
         "priority": PRIORITY_CRITICAL, "audience": "client"}
    other = {"field_type": "schedule", "schedule_key": "locations",
             "priority": PRIORITY_OPTIONAL, "audience": "client"}
    _finalize_schedule_taxonomy([q, other])
    assert q["priority"] == PRIORITY_CRITICAL
    assert other["priority"] == PRIORITY_IMPORTANT


def test_the_pass_is_fail_open():
    """An unreadable facts payload must leave every priority exactly as the
    static classifier assigned it - never raise, never blank the questionnaire."""
    class Hostile(dict):
        def get(self, *a, **k):
            raise RuntimeError("boom")
    qs = [_q("fein")]
    decorate_questions(qs, facts=Hostile(), flags={})
    assert qs[0]["priority"] in (PRIORITY_CRITICAL, PRIORITY_IMPORTANT)
