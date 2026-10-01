"""Step 2 of the Orbin 22 Sep feedback (owner decisions, 29 Sep 2026).

Read 25sepChanges.md (repo root) "Step 2" before changing anything pinned here.
Each section is one client item from `Orbin_Testing_09_22_2026.pdf`.

Items 4 / 11 - THE PROPOSED TERM FROM THE DEC. The client: the proposed
effective date is the dec's expiration date. An ended current-policy term now
proposes the next term (reverses the 15 Sep "ended -> ask" rule); a stale dec
(the next term is over, or ends within 30 days) is still asked. And the live
finding from the owner's third run: a proposed effective date a PERSON supplies
takes its expiration with it, by the policy's own term.

Items 7 / 8 - a dec upload renews its programme (page-one premiums, carrier).
Item 5 - a contact name alone keeps the phone and e-mail questions pre-ticked.

Item 15 - NO KNOWN LOSSES IS NOT APPLICABLE. Michelle: "Why is Loss Runs still
showing 60%? We've confirmed No Known Losses. It should not calculate against
the score." An attestation nothing contradicts now takes Loss History out of
the score (package and per form) exactly as a confirmed New Venture does.

Every date here is relative to today, so nothing ages out of the test.
"""
from __future__ import annotations

import asyncio
import copy
import json
import os
from datetime import datetime, timedelta
from unittest.mock import patch

import pytest

import repositories.session_repository as sr
import services.arq_service as arq
import services.extraction_service as es

HERE = os.path.dirname(os.path.abspath(__file__))


def _v(x):
    return x.get("value") if isinstance(x, dict) and "value" in x else x


def _year_shift(dt, years):
    try:
        return dt.replace(year=dt.year + years)
    except ValueError:                                   # 29 Feb -> 28 Feb
        return dt.replace(year=dt.year + years, day=28)


def _annual_term_ended(days_ago):
    exp = datetime.now() - timedelta(days=days_ago)
    if (exp.month, exp.day) == (2, 29):
        exp -= timedelta(days=1)
    return _year_shift(exp, -1), exp


def _mdY(dt):
    return dt.strftime("%m/%d/%Y")


def _schema(fid):
    with open(os.path.join(HERE, "..", "forms_schemas", f"{fid}_schema.json"), encoding="utf-8") as fh:
        return json.load(fh)


# ══ Items 4 / 11 - the proposed term ═════════════════════════════════════════

def _routed_orbin_facts(**over):
    """Facts after the merge routed an ended annual dec (Orbin's shape)."""
    eff, exp = _annual_term_ended(76)
    f = {
        "prior_effective_date": {"value": eff.strftime("%m/%d/%y"), "source": "ai",
                                 "confidence": "ai_high", "routed_from": "current_term"},
        "prior_expiration_date": {"value": exp.strftime("%m/%d/%y"), "source": "ai",
                                  "confidence": "ai_high", "routed_from": "current_term"},
        "renewal_dates_routed": True,
    }
    f.update(over)
    return f, eff, exp


class TestTheExpirationFollowsAPersonsEffectiveDate:
    def test_a_typed_effective_date_takes_its_expiration(self):
        facts, _eff, _exp = _routed_orbin_facts(
            effective_date={"value": "08/01/2026", "source": "producer", "confidence": "filled"})
        assert es.follow_proposed_expiration(facts) is True
        env = facts["expiration_date"]
        assert env["value"] == "08/01/2027"
        assert env["source"] == "derived" and env["confidence"] == "low_confidence"
        assert env["derivation"]["rule"] == "proposed_expiration_follows_effective"

    @pytest.mark.parametrize("source", ["producer", "client_arq", "user_confirmed"])
    def test_every_human_door_counts(self, source):
        facts, _e, _x = _routed_orbin_facts(
            effective_date={"value": "08/01/2026", "source": source, "confidence": "filled"})
        assert es.follow_proposed_expiration(facts) is True

    def test_our_derived_expiration_is_re_followed(self):
        facts, _e, _x = _routed_orbin_facts(
            effective_date={"value": "09/01/2026", "source": "producer"},
            expiration_date={"value": "07/15/2027", "source": "derived",
                             "derivation": {"rule": "renewal_routing_prior_term_length"}})
        assert es.follow_proposed_expiration(facts) is True
        assert _v(facts["expiration_date"]) == "09/01/2027"

    @pytest.mark.parametrize("held", [
        {"value": "12/31/2026", "source": "producer"},          # a person typed it
        {"value": "12/31/2026", "source": "ai", "confidence": "ai_high"},   # a document
        "12/31/2026",                                           # bare legacy value
    ])
    def test_a_stated_expiration_is_never_touched(self, held):
        facts, _e, _x = _routed_orbin_facts(
            effective_date={"value": "08/01/2026", "source": "producer"}, expiration_date=held)
        before = copy.deepcopy(facts)
        assert es.follow_proposed_expiration(facts) is False
        assert facts == before

    def test_a_documents_own_effective_date_is_not_followed(self):
        # A document stating an effective date and no expiration stays as before.
        facts, _e, _x = _routed_orbin_facts(
            effective_date={"value": "08/01/2026", "source": "ai", "confidence": "ai_high"})
        assert es.follow_proposed_expiration(facts) is False
        assert "expiration_date" not in facts

    def test_no_known_term_leaves_it_blank(self):
        facts = {"effective_date": {"value": "08/01/2026", "source": "producer"}}
        assert es.follow_proposed_expiration(facts) is False
        assert "expiration_date" not in facts

    def test_a_term_we_would_not_repeat_leaves_it_blank(self):
        facts = {"effective_date": {"value": "08/01/2026", "source": "producer"},
                 "prior_effective_date": "01/01/2026", "prior_expiration_date": "07/01/2026"}
        assert es.follow_proposed_expiration(facts) is False

    def test_a_calendar_month_term_is_leap_day_safe(self):
        facts = {"effective_date": {"value": "02/29/2028", "source": "producer"},
                 "prior_effective_date": "03/01/2026", "prior_expiration_date": "03/01/2027"}
        assert es.follow_proposed_expiration(facts) is True
        assert _v(facts["expiration_date"]) == "02/28/2029"

    @pytest.mark.parametrize("junk", [None, "", "TBD", 7, ["x"], {"value": None}, {"value": "13/45/2026"}])
    def test_junk_never_raises(self, junk):
        facts = {"effective_date": junk, "prior_effective_date": junk,
                 "prior_expiration_date": junk, "expiration_date": junk}
        assert es.follow_proposed_expiration(facts) is False
        assert es.follow_proposed_expiration("not a dict") is False


def _apply(field, value, *, facts, generated=None):
    """Drive the REAL producer-answer door against an in-memory session."""
    store = {"facts": copy.deepcopy(facts), "flags": {}, "generated_forms": generated or {}}

    async def _get(_sid):
        return copy.deepcopy(store)

    async def _upd(_sid, payload, delete_facts=None):
        for k, v in (payload or {}).items():
            store[k] = v
        return True

    with patch.object(sr, "get_processing_session", _get), \
         patch.object(sr, "upd_processing_session", _upd):
        ok, updated = asyncio.run(arq.apply_producer_answer_to_session("sid-step2", field, value))
    return ok, updated, store


class TestTheAnswerDoorsFollow:
    def test_pre_form_card_writes_both_dates(self):
        facts, _e, _x = _routed_orbin_facts()
        ok, _upd, store = _apply("effective_date", "08/01/2026", facts=facts)
        assert ok is True
        assert _v(store["facts"]["effective_date"]) == "08/01/2026"
        assert _v(store["facts"]["expiration_date"]) == "08/01/2027"
        assert store["facts"]["expiration_date"]["derivation"]["rule"] == \
            "proposed_expiration_follows_effective"

    def test_a_generated_125_gets_the_expiration_box_labelled_filled(self):
        facts, _e, _x = _routed_orbin_facts()
        gen = {"ACORD_125": {"schema": _schema("ACORD_125"), "mapped": {},
                             "confidence": {}, "client_filled_fields": []}}
        ok, updated, store = _apply("effective_date", "08/01/2026", facts=facts, generated=gen)
        assert ok is True
        form = store["generated_forms"]["ACORD_125"]
        state = form.get("field_state") or form.get("mapped")
        assert state.get("Policy_ExpirationDate_A") == "08/01/2027"
        assert form["confidence"]["Policy_ExpirationDate_A"] == "filled"
        assert "Policy_ExpirationDate_A" not in (form.get("client_filled_fields") or [])
        assert "ACORD_125" in updated

    def test_a_typed_expiration_then_wins(self):
        # The Tier 1 card now offers both boxes; the modal applies them in order.
        facts, _e, _x = _routed_orbin_facts()
        _ok, _u, store = _apply("effective_date", "08/01/2026", facts=facts)
        _ok, _u, store = _apply("expiration_date", "02/01/2027", facts=store["facts"])
        assert _v(store["facts"]["expiration_date"]) == "02/01/2027"
        assert store["facts"]["expiration_date"]["source"] == "producer"
        # ...and a later change of the effective date never overwrites it.
        _ok, _u, store = _apply("effective_date", "09/01/2026", facts=store["facts"])
        assert _v(store["facts"]["expiration_date"]) == "02/01/2027"


def test_the_tier1_card_offers_the_pair():
    from services.issue_registry import _tier1_resolution
    res = _tier1_resolution("Proposed effective date")
    assert res["mode"] == "field"
    assert res["facts"] == ["effective_date", "expiration_date"]


def test_a_persons_date_is_never_held_against_our_derived_one():
    """On a pipeline re-run the merge derives the term again. A typed date that
    differs from OUR derivation is restored, never held as a document conflict."""
    import inspect
    from services import extraction_pipeline
    src = inspect.getsource(extraction_pipeline._finalize_pipeline)
    assert "is_derived_proposed_term" in src
    assert "follow_proposed_expiration" in src
    assert es.is_derived_proposed_term(
        {"value": "07/15/2026", "source": "derived",
         "derivation": {"rule": "next_term_after_current_policy"}}) is True
    assert es.is_derived_proposed_term({"value": "07/15/2026", "source": "ai"}) is False
    assert es.is_derived_proposed_term(
        {"value": "07/15/2026", "source": "derived",
         "derivation": {"rule": "years_since_business_start_date"}}) is False


def test_the_orbin_replay_proposes_the_next_term_and_nothing_else_moves():
    """The stored live facts, re-routed: page one's two proposed boxes change and
    the prior-carrier grid keeps the current policies as year one."""
    import services.pdf_service as ps
    path = os.path.join(HERE, "fixtures", "orbin_live_24sep.json")
    if not os.path.exists(path):
        pytest.skip("live Orbin fixture not present")
    with open(path, encoding="utf-8") as fh:
        fx = json.load(fh)
    facts = fx.get("merged_facts") or fx.get("facts") or {}
    if not facts:
        pytest.skip("fixture carries no merged facts")
    eff, exp = _annual_term_ended(76)
    mf = copy.deepcopy(facts)
    for k in ("effective_date", "expiration_date", "prior_effective_date",
              "prior_expiration_date", "renewal_dates_routed", es.REJECTED_FACTS_KEY):
        mf.pop(k, None)
    mf["effective_date"] = {"value": eff.strftime("%m/%d/%y"), "source": "ai", "confidence": "ai_high"}
    mf["expiration_date"] = {"value": exp.strftime("%m/%d/%y"), "source": "ai", "confidence": "ai_high"}
    docs = [{"doc_type": "dec_page", "facts": {"effective_date": _v(mf["effective_date"]),
                                               "expiration_date": _v(mf["expiration_date"])}}]
    es._route_renewal_dates(mf, docs)
    assert _v(mf["effective_date"]) == _mdY(exp)
    assert _v(mf["expiration_date"]) == _mdY(_year_shift(exp, 1))
    schema = _schema("ACORD_125")
    facts_for = {**mf, "_form_id": "ACORD_125"}
    assert ps._resolve_renewal_proposed_period("Policy_EffectiveDate_A", facts_for) == _mdY(exp)
    assert ps._resolve_renewal_proposed_period("Policy_ExpirationDate_A", facts_for) == \
        _mdY(_year_shift(exp, 1))
    assert "Policy_EffectiveDate_A" in schema


# ══ Items 7 / 8 - page-one carrier and premiums on a dec upload ══════════════
# A package that is only the current programme's own paperwork renews it: the
# dec's line premiums and total print on page one, and so does the carrier when
# ONE company writes every policy. Several writing companies keep CARRIER blank
# and an unscored card asks for it. NAIC and POLICY NUMBER keep their own rules.

_EMCC = "EMPLOYERS MUTUAL CASUALTY COMPANY"
_EMCPC = "EMC Property & Casualty Company"
_ORBIN_LINES = [
    {"line": "General Liability", "carrier": _EMCPC, "policy_number": "BBC7263 - 26", "premium": "$3,954.00"},
    {"line": "Automobile", "carrier": _EMCC, "policy_number": "6E7-40-02---26", "premium": "$2,991.00"},
    {"line": "Inland Marine", "carrier": _EMCC, "policy_number": "6C7-40-02---26", "premium": "$300.00"},
    {"line": "Umbrella", "carrier": _EMCC, "policy_number": "6J7-40-02---26", "premium": "$3,418.00"},
    {"line": "Property"},
]


def _page_one_mf(lines=None, **over):
    mf = {"carrier_name": {"value": _EMCC, "source": "ai"},
          "total_policy_premium": "$10,663",
          "coverage_lines": copy.deepcopy(lines if lines is not None else _ORBIN_LINES),
          "effective_date": {"value": "07/15/2026", "source": "derived",
                             "derivation": {"rule": "next_term_after_current_policy"}}}
    mf.update(over)
    return mf


def _doc(role="dec_page", **facts):
    return {"doc_type": role, "facts": facts}


class TestTheRenewalPresumption:
    def test_orbin_two_writers_premiums_print_carrier_stays_asked(self):
        mf = _page_one_mf()
        marked = es._mark_page_one_current_policy(mf, [_doc()])
        assert marked == ["carrier"]
        assert mf["renews_current_programme"] is True
        assert mf["carrier_is_current_policy"] is True
        assert "premium_is_current_policy" not in mf
        assert mf["current_term_rows_ok"] is True

    def test_one_writer_prints_its_carrier_too(self):
        one = [dict(r, carrier=_EMCC) for r in _ORBIN_LINES if r.get("carrier")]
        mf = _page_one_mf(lines=one)
        assert es._mark_page_one_current_policy(mf, [_doc()]) == []
        assert mf["renews_current_programme"] is True

    @pytest.mark.parametrize("role", ["policy", "binder", "endorsement"])
    def test_the_programmes_own_paperwork_counts(self, role):
        mf = _page_one_mf()
        es._mark_page_one_current_policy(mf, [_doc(role)])
        assert mf.get("renews_current_programme") is True

    @pytest.mark.parametrize("docs", [
        [_doc("certificate")],                       # a COI describes, it does not renew
        [_doc("loss_run")],
        [_doc("narrative")],
        [_doc(), _doc("quote")],                     # a quote decides by its own rules
        [_doc(), _doc("application")],
        [dict(_doc(), excluded=True)],               # an excluded dec is not uploaded
    ])
    def test_other_uploads_are_not_presumed(self, docs):
        mf = _page_one_mf()
        es._mark_page_one_current_policy(mf, docs)
        assert "renews_current_programme" not in mf

    @pytest.mark.parametrize("over", [
        {"submission_is_new_business": True},                          # stated new business
        {"submission_carrier_name": "Granite Arch Casualty Company"},  # another addressee (FR125)
        {"effective_date": None},                                      # stale / odd dec: dates asked
        {"carrier_name": {"value": "Travelers", "source": "ai"}},      # writes no current policy
    ])
    def test_the_negative_controls_keep_the_15_sep_marks(self, over):
        mf = _page_one_mf(**over)
        if over.get("effective_date", 1) is None:
            mf.pop("effective_date")
        es._mark_page_one_current_policy(mf, [_doc()])
        assert "renews_current_programme" not in mf
        assert mf.get("premium_is_current_policy") is True

    def test_the_marks_are_recomputed_not_sticky(self):
        # A replay or a re-merge on stored facts reflects the current rule.
        mf = _page_one_mf(premium_is_current_policy=True, carrier_is_current_policy=True)
        es._mark_page_one_current_policy(mf, [_doc()])
        assert "premium_is_current_policy" not in mf

    @pytest.mark.parametrize("mf,docs", [(None, None), ({}, "x"), ({"coverage_lines": "junk"}, [None, 3])])
    def test_junk_never_raises(self, mf, docs):
        assert es._renews_current_programme(mf, docs) is False
        es._mark_page_one_current_policy(mf, docs)

    def test_writers_are_read_once(self):
        assert es._current_policy_writers(_ORBIN_LINES) == [
            es._current_policy_writers([_ORBIN_LINES[0]])[0],
            es._current_policy_writers([_ORBIN_LINES[1]])[0]]
        assert es._current_policy_writers("junk") == []
        assert es._current_policy_writers([{"carrier": "X Co"}]) == []   # no number, no premium


def test_page_one_premiums_print_through_the_stamper():
    import services.pdf_service as ps
    mf = _page_one_mf()
    es._mark_page_one_current_policy(mf, [_doc()])
    facts = {**mf, "_form_id": "ACORD_125"}
    assert ps._resolve_estimated_total("Policy_Payment_EstimatedTotalAmount_A", facts) not in (None, "")
    # CARRIER names BOTH writing companies (owner, 30 Sep 2026 - reverses the 29
    # Sep owned blank; ACORD's "company name(s)"), owned, never sent to gap fill.
    assert ps.authoritative_expected_value("ACORD_125", "Insurer_FullName_A", facts) == \
        f"{_EMCPC}; {_EMCC}"
    assert ps.authoritative_expected_value("ACORD_125", "Insurer_NAICCode_A", facts) is None


class TestTheCarrierCard:
    def _score(self, facts, mapped):
        import services.sqs_service as sq
        return sq.calculate_sqs(facts=facts, flags={}, mapped_data=mapped,
                                form_schema=_schema("ACORD_125"), selected_form_ids=["ACORD_125"],
                                hard_stops=[], soft_stops=[], tier2_score=50, form_id="ACORD_125")

    def _card(self, r):
        return [x for x in r.get("recommendations") or []
                if x.get("rec_id") == "rec_submission_carrier_name"]

    def test_a_blank_page_one_carrier_raises_an_unscored_card(self):
        # 30 Sep 2026 (owner): a renewed two-company programme now PRINTS both
        # companies, so no card. The card still fires where no company can be
        # named - a quote in the package, its market not stated.
        mf = _page_one_mf()
        es._mark_page_one_current_policy(mf, [_doc()])
        assert self._card(self._score(mf, {})) == []
        mf = _page_one_mf()
        es._mark_page_one_current_policy(mf, [_doc(), _doc("quote")])
        assert mf.get("renews_current_programme") is not True
        r = self._score(mf, {})                 # before generation: the resolver decides
        card = self._card(r)
        assert len(card) == 1
        assert card[0]["field"] == "submission_carrier_name"
        assert card[0]["score_impact"] == 0 and card[0]["unscored"] is True
        assert card[0]["message"] == "ACORD 125 missing: carrier receiving this submission"
        assert "—" not in card[0]["message"]
        r2 = self._score(mf, {"Insurer_FullName_A": "", "NamedInsured_FullName_A": "X"})
        assert len(self._card(r2)) == 1         # after generation: the stamped box decides

    def test_the_card_is_worth_nothing_and_goes_once_answered(self):
        mf = _page_one_mf()
        es._mark_page_one_current_policy(mf, [_doc()])
        before = self._score(mf, {"NamedInsured_FullName_A": "X"})
        mf2 = dict(mf, submission_carrier_name={"value": "EMC Insurance", "source": "producer"})
        after = self._score(mf2, {"NamedInsured_FullName_A": "X", "Insurer_FullName_A": "EMC Insurance"})
        assert self._card(after) == []
        assert before["sqs_score"] == after["sqs_score"]

    def test_no_card_when_one_writer_prints(self):
        one = [dict(r, carrier=_EMCC) for r in _ORBIN_LINES if r.get("carrier")]
        mf = _page_one_mf(lines=one)
        es._mark_page_one_current_policy(mf, [_doc()])
        assert self._card(self._score(mf, {})) == []

    def test_the_card_offers_a_box_the_server_accepts(self):
        from services.answer_routing import answer_mode
        assert answer_mode("submission_carrier_name", {})["mode"] == "field"


def test_the_grader_accepts_a_renewal_programme_and_still_catches_fr125():
    import sys
    sys.path.insert(0, os.path.join(HERE, "..", "scripts"))
    import audit_125_rules as A
    assert A._renews_programme(type("C", (), {"facts": {"renews_current_programme": True}})()) is True
    assert A._renews_programme(type("C", (), {"facts": {}})()) is False


# ══ Item 5 - "Contacts are in the dec": a name is not a way to reach anyone ══
# The 271-page dec prints no insured contact (checked). While Michelle is asked
# which contact she means, the owner's rule "phone and e-mail stay asked" is
# enforced: a contact NAME alone (typed by the producer, as in the fourth live
# check) no longer un-ticks the phone and e-mail questions. A known phone or
# e-mail keeps the H4 demotion exactly as before.

def _contact_q(canon):
    from services.question_eligibility import overlay_for
    return overlay_for({"field_name": canon, "_canonical_key": canon, "audience": "client",
                        "priority": "critical", "suppressed": False,
                        "score_impact": {"points": 15, "submission_readiness": True,
                                         "labels": ["Submission readiness"]}},
                       {"contact_name": {"value": "Erin Royal", "source": "producer"}})


@pytest.mark.parametrize("canon", ["contact_phone", "contact_email"])
def test_a_name_alone_keeps_phone_and_email_pre_ticked(canon):
    from services.question_eligibility import _only_contact_name_known
    assert _only_contact_name_known({"contact_name": {"value": "Erin Royal", "source": "producer"}})
    out = _contact_q(canon)
    assert out.get("priority") == "important"                 # Tier 1 is met: no readiness points
    assert out.get("force_preselect") is True
    assert "Submission readiness" not in (out.get("score_impact") or {}).get("labels", [])


def test_a_known_phone_keeps_the_h4_demotion_exactly():
    from services.question_eligibility import _only_contact_name_known, overlay_for
    facts = {"contact_phone": {"value": "3035551212", "source": "producer"}}
    assert _only_contact_name_known(facts) is False
    for canon in ("contact_name", "contact_email"):
        out = overlay_for({"field_name": canon, "_canonical_key": canon, "audience": "client",
                           "priority": "critical", "suppressed": False}, facts)
        assert out.get("priority") == "important"
        assert not out.get("force_preselect")


def test_default_selection_honours_the_overlay():
    from services.question_classifier import apply_default_selection
    qs = [{"field_name": "contact_phone", "audience": "client", "priority": "important",
           "sqs_points": 0, "force_preselect": True},
          {"field_name": "contact_email", "audience": "client", "priority": "important",
           "sqs_points": 0}]
    apply_default_selection(qs)
    assert qs[0]["default_selected"] is True
    assert qs[1]["default_selected"] is False


@pytest.mark.parametrize("facts", [None, {}, {"contact_name": None}, {"contact_name": {"value": "N/A"}}])
def test_the_name_rule_fails_closed(facts):
    from services.question_eligibility import _only_contact_name_known
    assert _only_contact_name_known(facts) in (False, True)   # never raises


# ══ Item 15 - an attested No Known Losses is Not Applicable ══════════════════
#
# Owner decision 29 Sep 2026. The pillar leaves the score, package AND per
# form, and the other pillars rescale - the New Venture mechanism - in every
# years band. Documents outrank the attestation, a corroborated claim keeps the
# 45 conflict ceiling, and the questionnaire state does not move: an
# established business is not a New Venture (Orbin has a real prior carrier),
# so its prior-carrier questions are still asked.

from services import audit_service as _audit              # noqa: E402
from services import loss_history_state as lhs            # noqa: E402
from services import sqs_service as sq                     # noqa: E402

_NO_LOSSES, _HAD_CLAIMS = arq._NO_LOSS_OPTIONS
_INDICATOR = arq.NO_LOSS_INDICATOR_FIELD
_NA_STATE = "no_known_losses_not_applicable"
_NA_LABEL = "Not applicable - No Known Losses attested"


def _env(value, source):
    return {"value": value, "confidence": "filled", "source": source}


# Every door an attestation arrives through: the client's questionnaire option
# (with the flag its apply path sets), a producer typing on the card, the ACORD
# 125 "Check if none" box written back as "Yes", and the flag alone.
_DOORS = {
    "client option": ({_INDICATOR: _env(_NO_LOSSES, "client_arq")}, {"no_prior_losses": True}),
    "producer text": ({_INDICATOR: _env("no losses", "producer")}, {"no_prior_losses": True}),
    "form box Yes": ({_INDICATOR: _env("Yes", "producer")}, {}),
    "flag": ({}, {"no_prior_losses": True}),
}

# An ordinary established GL account with healthy other pillars and no loss
# runs - the shape Michelle attested on.
_ACCOUNT = {
    "applicant_name": "Acme Roofing LLC", "mailing_address": "1 Main St, Troy, MI 48083",
    "effective_date": "07/15/2026", "lines_of_business": ["General Liability"],
    "entity_type": "LLC", "contact_name": "Jo", "producer_name": "Broker Inc",
    "fein": "12-3456789", "num_employees": "40", "years_in_business": "12",
    "operations_description": "Residential roofing contractor with 12 crews",
    "total_revenue": "2000000", "naics_code": "238160",
}
_GL = {"has_general_liability": True}
_UMBRELLA = {
    "umbrella_limit": "3000000", "gl_each_occurrence": "1000000",
    "gl_aggregate": "2000000", "schedule_of_underlying_insurance": "GL $1M/$2M",
    "umbrella_follow_form": "Yes - follows form",
}
_CLAIM_ROW = [{"date": "03/15/2024", "description": "Slip and fall at job site",
               "paid": "12000"}]
_LOSS_RUN_DOC = {"doc_id": "lr", "doc_type": "loss_run",
                 "text": "LOSS RUN - ACME ROOFING LLC - no losses in the period"}


def _attested(door="client option", **extra):
    a_facts, a_flags = _DOORS[door]
    facts = {**copy.deepcopy(_ACCOUNT), **copy.deepcopy(a_facts), **extra}
    return facts, {**_GL, **a_flags}


def _package(facts, flags, docs=None):
    return sq.calculate_package_sqs(
        facts=facts, flags=flags, form_results=[{"confidence_fill_rate": 80}],
        cross_issues=[], hard_stops=[], soft_stops=[],
        session_data={"docs": docs or [], "sqs_history": []})


def _form(facts, flags, **kw):
    return sq.calculate_sqs(
        facts=facts, flags=flags, mapped_data={"a": "x"}, form_schema={"a": {}},
        selected_form_ids=["ACORD_125"], hard_stops=[], soft_stops=[],
        tier2_score=80, form_id="ACORD_125", **kw)


def _loss_recs(result):
    return [r for r in result.get("recommendations") or []
            if r.get("component") == "loss_history_alignment"]


class TestItem15EveryDoorTakesThePillarOut:
    @pytest.mark.parametrize("door", sorted(_DOORS))
    def test_the_scorer(self, door):
        facts, flags = _attested(door)
        assert lhs.attested_no_losses_not_applicable(facts, flags) is True
        score, recs = sq.calculate_p4_loss_history(facts, flags)
        assert score is None
        assert recs == [sq._ATTESTED_NOT_APPLICABLE_REC]

    @pytest.mark.parametrize("door", sorted(_DOORS))
    def test_the_package(self, door):
        pkg = _package(*_attested(door))
        assert pkg["pillars"]["loss_history_alignment"] is None
        assert pkg["loss_history_state"] == _NA_STATE
        assert sq.LOSS_HISTORY_STATE_LABELS[_NA_STATE] == _NA_LABEL
        # 1 Oct 2026 (item 15): the client word says what happened - the
        # insured attested; "None corroborated" read as "nothing was checked".
        assert pkg["loss_history_state_client_label"] == "Attested - no known losses"
        cat = pkg["category_breakdown"]["loss_history_alignment"]["loss_history"]
        assert cat["score"] is None and cat["status"] == "not_applicable"
        # Not a gap, so never a "points available" row on the package.
        assert all(r.get("pillar") != "loss_history_alignment"
                   for r in pkg["top_recommendations"])

    @pytest.mark.parametrize("door", sorted(_DOORS))
    def test_the_form(self, door):
        res = _form(*_attested(door))
        assert res["breakdown"]["loss_history_alignment"] is None
        assert res["loss_history_state"] == _NA_STATE
        assert res["loss_history_state_client_label"] == "Attested - no known losses"

    @pytest.mark.parametrize("years", ["3", "12", None])
    def test_every_years_band(self, years):
        """Including 1-5 years, which scored 85 - "not calculated" is literal."""
        facts, flags = _attested()
        if years is None:
            facts.pop("years_in_business")
        else:
            facts["years_in_business"] = years
        assert sq.calculate_p4_loss_history(facts, flags)[0] is None
        assert sq._get_loss_history_state(facts, flags) == _NA_STATE

    def test_a_contradicted_new_venture_keeps_its_notice(self):
        facts, flags = _attested(new_venture_indicator=lhs.NEW_VENTURE_OPTIONS[0],
                                 prior_carrier="Travelers")
        score, recs = sq.calculate_p4_loss_history(facts, flags)
        assert score is None
        assert recs[0].startswith("New Venture status conflicts with evidence")
        assert recs[-1] == sq._ATTESTED_NOT_APPLICABLE_REC


class TestItem15WhatKeepsThePillarScored:
    @pytest.mark.parametrize("claim", [
        {"loss_history": _CLAIM_ROW},                 # a TYPED claim row
        {"num_claims": "1"},                          # a bare scalar, origin unknown
        {"num_claims": _env("2", "producer")},        # a person stated it
    ])
    def test_a_corroborated_claim_keeps_the_45_ceiling(self, claim):
        facts, flags = _attested(**copy.deepcopy(claim))
        assert lhs.attested_no_losses_not_applicable(facts, flags) is False
        score, recs = sq.calculate_p4_loss_history(facts, flags)
        assert score == 45
        assert any(r.startswith("Loss history conflict") for r in recs)
        assert sq._get_loss_history_state(facts, flags) == "loss_history_conflicting"
        assert _package(facts, flags)["pillars"]["loss_history_alignment"] == 45
        assert _form(facts, flags)["breakdown"]["loss_history_alignment"] == 45

    def test_a_loss_run_with_claims_keeps_the_ceiling(self):
        facts, flags = _attested(loss_history_years="5", num_claims="3",
                                 total_incurred="50000", loss_run_age_days="30",
                                 prior_carrier="EMC")
        score, _ = sq.calculate_p4_loss_history(
            facts, flags, has_loss_run_doc=True, loss_run_match="strong")
        assert score == 45
        pkg = _package(facts, flags, docs=[_LOSS_RUN_DOC])
        assert pkg["pillars"]["loss_history_alignment"] is not None
        assert pkg["pillars"]["loss_history_alignment"] <= 45

    def test_documents_outrank_the_attestation(self):
        facts, flags = _attested(loss_history_years="5", loss_run_age_days="30",
                                 prior_carrier="EMC")
        assert lhs.attested_no_losses_not_applicable(facts, flags, has_loss_run_doc=True) is False
        score, _ = sq.calculate_p4_loss_history(
            facts, flags, has_loss_run_doc=True, loss_run_match="strong")
        assert score == 100
        pkg = _package(facts, flags, docs=[_LOSS_RUN_DOC])
        assert pkg["pillars"]["loss_history_alignment"] is not None
        assert pkg["loss_history_state"] != _NA_STATE

    def test_a_model_only_claim_figure_does_not_hold_the_pillar(self):
        """The conflict door ignores a figure only the extraction model supplied
        (2026-09-05), so it cannot keep the pillar in the score either."""
        facts, flags = _attested(num_claims=_env("2", "ai"))
        assert sq._loss_history_conflict(facts, flags) is False
        assert sq.calculate_p4_loss_history(facts, flags)[0] is None

    def test_a_narrative_mention_is_not_an_attestation(self):
        facts, flags = copy.deepcopy(_ACCOUNT), {**_GL, "narrative_states_no_losses": True}
        assert lhs.attested_no_losses_not_applicable(facts, flags) is False
        assert sq.calculate_p4_loss_history(facts, flags)[0] == 40
        assert sq._get_loss_history_state(facts, flags) == "narrative_states_no_losses"

    def test_a_stale_flag_beside_a_claims_answer_is_scored_not_na(self):
        facts = {**copy.deepcopy(_ACCOUNT), _INDICATOR: _env(_HAD_CLAIMS, "client_arq")}
        flags = {**_GL, "no_prior_losses": True}
        assert lhs.attested_no_losses_not_applicable(facts, flags) is False
        assert sq.calculate_p4_loss_history(facts, flags)[0] is not None
        assert sq._get_loss_history_state(facts, flags) == "user_states_no_losses"


class TestItem15TheUnderAYearRoutesAreUnchanged:
    def test_young_and_attested_keeps_its_own_notice_and_state(self):
        facts, flags = _attested(years_in_business="0.5")
        score, recs = sq.calculate_p4_loss_history(facts, flags)
        assert score is None
        assert recs and recs[0].startswith("Business has under a year of operating history")
        assert sq._ATTESTED_NOT_APPLICABLE_REC not in recs
        assert sq._get_loss_history_state(facts, flags) == "no_operating_history_not_applicable"
        assert lhs.resolve_loss_history_state(facts, flags) == lhs.STATE_NEW_VENTURE

    def test_young_and_pending_is_na_and_young_and_silent_still_scores(self):
        young = {**copy.deepcopy(_ACCOUNT), "years_in_business": "1"}
        assert sq.calculate_p4_loss_history({**young, "loss_run_status": "pending"}, dict(_GL))[0] is None
        assert sq.calculate_p4_loss_history(young, dict(_GL))[0] == 25


class TestItem15TheQuestionnaireDoesNotMove:
    _PRIOR = ("prior_carrier", "prior_carrier_naic", "prior_policy_number",
              "prior_effective_date", "prior_expiration_date")

    def _questions(self):
        return [{"field_name": k, "_canonical_key": k, "question": k} for k in self._PRIOR]

    @pytest.mark.parametrize("door", sorted(_DOORS))
    def test_the_state_stays_attested_and_prior_carrier_is_still_asked(self, door):
        facts, flags = _attested(door)
        assert lhs.resolve_loss_history_state(facts, flags) == lhs.STATE_NO_KNOWN_LOSSES_ATTESTED
        assert lhs.suppressed_question_fields(facts, flags) == frozenset()
        kept = arq._apply_loss_state_question_gate(self._questions(), facts, flags)
        assert [q["field_name"] for q in kept] == list(self._PRIOR)

    def test_orbins_shape_a_carrier_derived_from_the_expiring_policies(self):
        facts, flags = _attested()
        facts["prior_carrier"] = {
            "value": "EMPLOYERS MUTUAL CASUALTY COMPANY", "source": "derived",
            "derivation": {"rule": lhs.PRIOR_CARRIER_DERIVATION_RULE,
                           "inputs": ["coverage_lines"]}}
        assert sq.calculate_p4_loss_history(facts, flags)[0] is None
        assert lhs.resolve_loss_history_state(facts, flags) == lhs.STATE_NO_KNOWN_LOSSES_ATTESTED
        kept = arq._apply_loss_state_question_gate(self._questions(), facts, flags)
        assert len(kept) == len(self._PRIOR)

    def test_control_a_confirmed_new_venture_does_drop_them(self):
        """The gate is live: the same questions go for a New Venture."""
        facts = {**copy.deepcopy(_ACCOUNT), "new_venture_indicator": lhs.NEW_VENTURE_OPTIONS[0]}
        assert arq._apply_loss_state_question_gate(self._questions(), facts, dict(_GL)) == []


class TestItem15WithdrawingTheAttestationRestoresThePillar:
    @staticmethod
    def _door(value, store):
        async def _get(_sid):
            return copy.deepcopy(store)

        async def _upd(_sid, payload, delete_facts=None):
            for k, v in (payload or {}).items():
                store[k] = v
            return True

        with patch.object(sr, "get_processing_session", _get), \
             patch.object(sr, "upd_processing_session", _upd):
            ok, _updated = asyncio.run(
                arq.apply_producer_answer_to_session("sid-item15", _INDICATOR, value))
        assert ok is True
        return store

    def test_answering_we_have_had_claims_restores_it(self):
        store = {"facts": copy.deepcopy(_ACCOUNT), "flags": dict(_GL), "generated_forms": {}}
        self._door(_NO_LOSSES, store)
        assert store["flags"]["no_prior_losses"] is True
        assert sq.calculate_p4_loss_history(store["facts"], store["flags"])[0] is None
        self._door(_HAD_CLAIMS, store)
        assert store["flags"]["no_prior_losses"] is False
        assert sq.calculate_p4_loss_history(store["facts"], store["flags"])[0] == 25
        assert sq._get_loss_history_state(store["facts"], store["flags"]) == "prior_claims_exist"
        # No derived fact was written, so there is nothing to clean up.
        assert set(store["facts"]) == set(_ACCOUNT) | {_INDICATOR}


class TestItem15TheLedgerReconciles:
    @staticmethod
    def _shape(umbrella):
        facts, flags = _attested()
        if umbrella:
            facts.update(copy.deepcopy(_UMBRELLA))
            flags["has_umbrella"] = True
        return facts, flags

    @pytest.mark.parametrize("umbrella", [True, False], ids=["loss N/A", "loss and umbrella N/A"])
    def test_the_package(self, umbrella):
        pkg = _package(*self._shape(umbrella))
        tr = pkg["score_trace"]
        assert tr["reconciles"] is True
        assert tr["arithmetic"]["raw"] == pkg["raw_sqs_score"]
        rows = {r["pillar"]: r for r in tr["pillars"]}
        assert rows["loss_history_alignment"]["not_applicable"] is True
        assert rows["loss_history_alignment"]["contribution"] == 0.0
        assert rows["umbrella_limit_adequacy"]["not_applicable"] is (not umbrella)
        live = 0.85 if umbrella else 0.75
        assert rows["structural_completeness"]["effective_weight"] == pytest.approx(0.25 / live, rel=1e-3)
        # Effective weights are stored rounded, so they sum to 1 within that.
        assert sum(r["effective_weight"] for r in tr["pillars"]) == pytest.approx(1.0, abs=1e-3)
        # The headline IS the rescale of what remains.
        assert pkg["raw_sqs_score"] == sq._weighted_pillar_sum(pkg["pillars"], sq.SPEC_PILLAR_WEIGHTS)

    @pytest.mark.parametrize("umbrella", [True, False], ids=["loss N/A", "loss and umbrella N/A"])
    def test_the_form(self, umbrella):
        res = _form(*self._shape(umbrella))
        tr = res["score_trace"]
        assert tr["reconciles"] is True
        assert tr["arithmetic"]["raw"] == res["raw_sqs_score"]
        rows = {r["pillar"]: r for r in tr["pillars"]}
        assert rows["loss_history_alignment"]["not_applicable"] is True
        assert rows["umbrella_limit_adequacy"]["not_applicable"] is (not umbrella)


class TestItem15TheNoticeAndTheCard:
    def test_the_notice_is_informational(self):
        recs = [r for r in _loss_recs(_form(*_attested()))
                if r["message"] == sq._ATTESTED_NOT_APPLICABLE_REC]
        assert len(recs) == 1
        rec = recs[0]
        assert rec["score_impact"] == 0 and rec["priority"] == 3
        assert rec["requires_doc"] is False
        assert rec["field"] is None
        assert sq.loss_recommendation_field(rec["message"]) is None
        assert any(p in rec["message"].lower() for p, _f in sq._LOSS_RECOMMENDATION_FIELDS)
        assert "\u2014" not in rec["message"], "no em-dash in UI text"

    def test_the_card_is_worth_exactly_zero_when_attesting_cannot_raise_the_score(self):
        """An EMPTY package: the pillars that remain average below the 25 the
        loss pillar holds, so taking it out cannot raise the number. The card
        used to fall back to its typed +8."""
        def score(facts):
            return sq.calculate_sqs(
                facts=facts, flags={}, mapped_data={}, form_schema={},
                selected_form_ids=["ACORD_125"], hard_stops=[], soft_stops=[],
                tier2_score=50, form_id="ACORD_125")
        before = score({})
        card = next(r for r in _loss_recs(before) if r.get("field") == _INDICATOR)
        assert card["message"].startswith("No loss history provided")
        assert card["score_impact"] == 0 and card["impact_is_exact"] is True
        assert score({_INDICATOR: "Yes"})["raw_sqs_score"] <= before["raw_sqs_score"]

    def test_only_the_attestation_card_trusts_a_flat_measurement(self):
        attest = {"field": _INDICATOR, "component": "loss_history_alignment", "score_impact": 8}
        other = {"field": "some_numeric_field", "component": "loss_history_alignment",
                 "score_impact": 8}
        out = sq._measure_recommendation_impacts(
            [attest, other], baseline=50, breakdown={"loss_history_alignment": 25},
            weights=sq.SPEC_PILLAR_WEIGHTS, rescore=lambda _f: 47, facts={})
        assert out[id(attest)] == (0, True)
        pts, exact = out[id(other)]
        assert pts > 0 and exact is False, "a wrong-shaped probe still falls back"

        def boom(_f):
            raise RuntimeError("scorer exploded")
        attest2 = dict(attest)
        out = sq._measure_recommendation_impacts(
            [attest2], baseline=50, breakdown={"loss_history_alignment": 25},
            weights=sq.SPEC_PILLAR_WEIGHTS, rescore=boom, facts={})
        pts, exact = out[id(attest2)]
        assert pts > 0 and exact is False, "no measurement, no exact zero"


class TestItem15AStaleCreditCannotStackOnTheRescale:
    """A dismissed "attested by user" card earned a credit for the attested 60
    sitting short of 100. That gap no longer exists once the same attestation
    removes the pillar, and the card has no field, so nothing else retires it."""
    _MSG = ("No Known Losses (attested by user) - attach loss runs or a signed "
            "no-known-loss letter to fully confirm")

    def _credits(self, monkeypatch, facts, rows=None):
        rows = rows if rows is not None else [{
            "rec_id": sq._loss_rec_id(self._MSG), "field": None, "message": self._MSG,
            "override_reason": "carrier accepts the attestation", "score_impact": 6}]

        async def _fake(_sid):
            return rows
        monkeypatch.setattr(_audit, "get_dismissed_recommendations", _fake)
        return asyncio.run(_audit.active_score_credits("sid-item15", facts=facts))

    def test_it_retires_once_the_attestation_makes_the_pillar_na(self, monkeypatch):
        facts, _flags = _attested()
        total, kept = self._credits(monkeypatch, facts)
        assert (total, kept) == (0, [])

    def test_it_stands_while_the_card_is_still_on_screen(self, monkeypatch):
        facts, flags = _attested(loss_history=copy.deepcopy(_CLAIM_ROW))
        recs = sq.calculate_p4_loss_history(facts, flags)[1]
        assert any(r.startswith("No Known Losses (attested by user)") for r in recs)
        assert self._credits(monkeypatch, facts)[0] == 6

    def test_no_facts_and_other_cards_are_untouched(self, monkeypatch):
        assert self._credits(monkeypatch, None)[0] == 6
        assert self._credits(monkeypatch, {})[0] == 6
        stale = [{"rec_id": "rec_loss_loss_runs_appear_stale", "field": None,
                  "message": "Loss runs appear stale (400 days old). Updated loss runs "
                             "may be required before bind.",
                  "override_reason": "ordered", "score_impact": 5}]
        facts, _flags = _attested()
        assert self._credits(monkeypatch, facts, rows=stale)[0] == 5


def test_item15_the_frontend_mirrors_the_new_state():
    """AcordModal prints the state label and its provenance card from two maps
    that mirror the backend. A state missing there renders as its raw key."""
    import re
    path = os.path.join(HERE, "..", "..", "frontend", "src", "components", "form", "AcordModal.jsx")
    if not os.path.exists(path):
        pytest.skip("frontend not present")
    with open(path, encoding="utf-8") as fh:
        src = fh.read()
    for block in ("LOSS_HISTORY_STATE_LABEL", "LOSS_STATE_PROV"):
        body = re.search(r"const %s = \{(.*?)\n\};" % block, src, re.S).group(1)
        for state in sq.LOSS_HISTORY_STATE_LABELS:
            assert re.search(r"\b%s\s*:" % state, body), (block, state)
    assert '"%s"' % _NA_LABEL in src


# ══ Item 2 - the score before forms ═══════════════════════════════════════════
# Michelle: "Do not require forms to get the score ... Hide or change the
# 'calculated after forms are generated' line?" Owner-approved, 29 Sep 2026:
# the pre-form Review screen prints the package SQS NUMBER, labelled "so far"
# (generation can still move it), and the line is gone. Reverses the 27 Aug
# tier-only card (V1 H2, tests/test_h2_readiness_presentation.py).
#
# The number is the one door's - `sqs_service.current_package_sqs` - never
# `tier2_score`. And there is ONE recipe before forms: a pre-form Resolve /
# Reopen / answer used to persist the 3.7 no-form score while every reload
# recomputed the door's, so the shown number moved after an unrelated Apply and
# moved back on reload (Orbin 60 vs 61). The recalc now persists what the door
# recomputes, and resolve / reopen report the door's number and key details.

import ast                                                           # noqa: E402
import shutil                                                        # noqa: E402
import subprocess                                                    # noqa: E402
from pathlib import Path                                             # noqa: E402

import routes.audit_routes as ar                                     # noqa: E402
import services.audit_service as au                                  # noqa: E402
from models.schemas import ReopenIssueRequest, ResolveIssueRequest   # noqa: E402
from services import sqs_service as sq                               # noqa: E402

_FRONTEND_SRC = Path(HERE).resolve().parents[1] / "frontend" / "src"
_ACORD_MODAL = _FRONTEND_SRC / "components" / "form" / "AcordModal.jsx"
_RAIL = _FRONTEND_SRC / "components" / "form" / "review" / "ReviewRailLayout.jsx"
_FORMATTERS = _FRONTEND_SRC / "utils" / "formatters.js"
_OLD_LINE = "calculated after forms are generated"
_CAN_CHANGE = "It can change when forms are generated."
_RAIL_NOTE = "Submission Quality Score so far. " + _CAN_CHANGE
_EM_DASHES = ("\u2014", "\u2013")   # em dash, en dash


def _src(path):
    return path.read_text(encoding="utf-8")


# ── the screens ──────────────────────────────────────────────────────────────

@pytest.mark.parametrize("path", [_ACORD_MODAL, _RAIL], ids=["classic", "rail"])
def test_neither_review_screen_says_the_score_waits_for_forms(path):
    src = _src(path)
    assert _OLD_LINE not in src
    assert "scoreSoFar(packageSqs)" in src
    assert _CAN_CHANGE in src
    assert "so far" in src


def test_the_rail_prints_the_number_with_the_gauge_and_in_the_footer():
    src = _src(_RAIL)
    # the number sits between the gauge and the tier, and only when there is one
    gauge = src[src.index('<div className="rr-gauge">'):src.index('<div className="rr-ready__copy">')]
    assert gauge.index("<Gauge ") < gauge.index("soFar.score") < gauge.index("rr-gauge__tier")
    assert '{tierName || "Not scored yet"}' in gauge
    # the note replaces the old line, only when there is a score
    assert "{soFar && (" in src and _RAIL_NOTE in src
    # the rail footer
    assert '<div className="rr-rail-foot__label">Score so far</div>' in src
    assert 'soFar ? soFar.text : "Not scored yet"' in src
    assert "Submission readiness</div>" not in src
    # kept: the panel title, the key-details lines, the tier ladder, Progress
    for kept in ('title="Submission Readiness"', "Key details in place:",
                 "<KeyDetailsMissing keyDetails={keyDetails}", "TIER_LADDER.map", 'title="Your Progress"'):
        assert kept in src, kept
    # "Key details missing" is now its own component, each detail a fix (30 Sep)
    assert "Key details missing:" in (_FRONTEND_SRC / "components" / "form" / "review" / "KeyDetailsMissing.jsx").read_text()


def test_the_classic_card_prints_the_score_so_far():
    src = _src(_ACORD_MODAL)
    assert "Current Submission Readiness" not in src
    card = src[src.index("const soFar = scoreSoFar(packageSqs);"):]
    card = card[:card.index("})()}")]
    assert "Submission Quality Score so far" in card
    assert "{soFar.text}" in card
    assert _CAN_CHANGE in card
    # same colour as before: the grade of the package score
    assert "gradeColor(sqsGradeFromScore(packageSqs.package_sqs_score))" in card
    assert "Key details in place:" in card and "<KeyDetailsMissing keyDetails={keyDetails}" in card


def test_the_new_copy_carries_no_em_dash():
    rail, modal = _src(_RAIL), _src(_ACORD_MODAL)
    for text, where in ((_RAIL_NOTE, rail), ("Score so far", rail),
                        ("Submission Quality Score so far", modal), (_CAN_CHANGE, modal)):
        assert text in where, text
        assert not any(d in text for d in _EM_DASHES), text
    for src in (rail, modal):
        for line in src.splitlines():
            if "so far" in line and "//" not in line and "{/*" not in line:
                assert not any(d in line for d in _EM_DASHES), line


def test_the_formatter_template_is_n_of_100_then_the_tier():
    src = _src(_FORMATTERS)
    body = src[src.index("export const scoreSoFar"):]
    body = body[:body.index("\n};") + 3]
    assert "`${score} / 100 - ${tier}`" in body
    assert "`${score} / 100`" in body
    assert not any(d in body for d in _EM_DASHES)
    # the Number(null) === 0 trap: a missing score is never printed as 0
    assert "Number.isFinite(score)" in body
    assert 'typeof raw !== "number" && typeof raw !== "string"' in body


@pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")
def test_the_formatter_behaves(tmp_path):
    """Run the REAL formatter (frontend/package.json makes it an ES module)."""
    script = tmp_path / "check.mjs"
    script.write_text(
        f"import {{ scoreSoFar }} from {json.dumps(_FORMATTERS.as_uri())};\n"
        "const cases = [null, undefined, {}, {package_sqs_score: null, tier: 'Major Gaps'},\n"
        "  {package_sqs_score: '', tier: 'Major Gaps'}, {package_sqs_score: '  '},\n"
        "  {package_sqs_score: 'abc'}, {package_sqs_score: NaN}, {package_sqs_score: Infinity},\n"
        "  {package_sqs_score: true}, {package_sqs_score: 61, tier: 'Major Gaps'},\n"
        "  {package_sqs_score: 0, tier: 'Not Ready'}, {package_sqs_score: '85', tier: 'Almost There'},\n"
        "  {package_sqs_score: 72}];\n"
        "console.log(JSON.stringify(cases.map((c) => scoreSoFar(c))));\n",
        encoding="utf-8",
    )
    run = subprocess.run(["node", str(script)], capture_output=True, text=True, timeout=60)
    assert run.returncode == 0, run.stderr
    assert json.loads(run.stdout) == [
        None, None, None, None, None, None, None, None, None, None,
        {"score": 61, "text": "61 / 100 - Major Gaps"},
        {"score": 0, "text": "0 / 100 - Not Ready"},
        {"score": 85, "text": "85 / 100 - Almost There"},
        {"score": 72, "text": "72 / 100"},
    ]


def test_a_resolve_or_reopen_replaces_the_card_and_its_key_details():
    src = _src(_ACORD_MODAL)
    body = src[src.index("const _applyCrossIssuePanelUpdate = (data) => {"):]
    body = body[:body.index("const handleIssueResolved")]
    assert "if (data.package_sqs !== undefined) {" in body
    assert "setPackageSqs(data.package_sqs || null);" in body
    assert "if (data.key_details !== undefined) setKeyDetails(data.key_details || null);" in body
    # the editor's headline merge is still there, as the fallback
    assert "} else if (data.new_package_sqs_score != null) {" in body


def test_the_form_selection_screen_gains_no_score():
    src = _src(_ACORD_MODAL)
    block = src[src.index('{step === "form_selection" && ('):src.index('{step === "editor" && (')]
    assert "scoreSoFar" not in block and "so far" not in block
    assert "packageSqs" not in block


# ── one recipe before forms ──────────────────────────────────────────────────

_T1 = {
    "producer_name": "Best Agency", "applicant_name": "Acme LLC",
    "mailing_address": "1 Main St, Denver, CO 80202", "effective_date": "01/01/2027",
    "lines_of_business": "General Liability", "entity_type": "LLC",
}
_T2 = {
    "fein": "12-3456789", "operations_description": "Electrical contracting",
    "total_revenue": "$1,200,000", "num_employees": "12",
    "years_in_business": "8", "naics_code": "238210",
}


def _row(**over):
    """A pre-form row: nothing generated, nothing selected, two recommended
    forms, Contact information missing (Tier 1)."""
    base = {
        "user_id": "u-item2", "facts": {**_T1, **_T2},
        "flags": {"has_general_liability": True},
        "hard_stops": [], "soft_stops": [],
        "recommendations": [{"form_id": "ACORD_125"}, {"form_id": "ACORD_126"}],
        "cross_form_issues": [], "structured_issues": [], "docs": [], "integrity": {},
        "generated_forms": {}, "selected_form_ids": [], "underwriting_consistency": {},
    }
    base.update(over)
    return base


def _generated_125():
    return {"ACORD_125": {
        "mapped": {"NamedInsured_FullName_A": "Acme LLC"},
        "confidence": {"NamedInsured_FullName_A": "ai_high"},
        "schema": {"NamedInsured_FullName_A": {"ft": "/Tx", "tu": "Enter name"}},
    }}


class _Session:
    """The REAL recalc, answer and route code against an in-memory row. Every
    audit / DB side effect is stubbed; `credits` is what active_score_credits
    returns, and `credit_calls` counts the calls."""

    def __init__(self, row, credits=(0, [])):
        self.store = copy.deepcopy(row)
        self.credits = credits
        self.credit_calls = 0

    async def _get(self, _sid):
        return copy.deepcopy(self.store)

    async def _upd(self, _sid, payload, delete_facts=None):
        for k, v in (payload or {}).items():
            self.store[k] = copy.deepcopy(v)
        for k in (delete_facts or []):
            self.store.get("facts", {}).pop(k, None)
        return True

    async def _credits(self, *_a, **_k):
        self.credit_calls += 1
        return self.credits

    def run(self, coro_fn, *args, **kwargs):
        async def _none(*_a, **_k):
            return None

        async def _empty(*_a, **_k):
            return []

        async def _true(*_a, **_k):
            return True

        with patch.object(sr, "get_processing_session", self._get), \
             patch.object(sr, "upd_processing_session", self._upd), \
             patch.object(ar, "get_processing_session", self._get), \
             patch.object(ar, "log_field_change", _none), \
             patch.object(ar, "set_issue_status", _true), \
             patch.object(au, "log_audit_event", _none), \
             patch.object(au, "log_sqs_snapshot_if_changed", _none), \
             patch.object(au, "get_open_recommendations", _empty), \
             patch.object(au, "mark_recommendation_resolved", _none), \
             patch.object(au, "sync_recommendation_cards", _none), \
             patch.object(au, "active_score_credits", self._credits):
            return asyncio.run(coro_fn(*args, **kwargs))

    def reload(self):
        """What any pre-form screen prints on reload - the one door."""
        return sq.current_package_sqs(copy.deepcopy(self.store), "sid-item2", "u-item2")


def test_the_fixture_tells_the_two_recipes_apart():
    """Guard for the guard: on this row the 3.7 no-form recipe the recalc used
    to persist is NOT the door's number, so the equality tests below would fail
    on the old code rather than pass by coincidence."""
    row = _row()
    old = sq.calculate_package_sqs(
        facts=row["facts"], flags=row["flags"], form_results=[], cross_issues=[],
        hard_stops=[], soft_stops=[], session_data=row, calculation_stage="arq_remediated")
    assert old["package_sqs_score"] != sq.score_package_pre_generation(row)["package_sqs_score"]


def test_a_pre_form_recalc_persists_what_the_door_recomputes():
    s = _Session(_row())
    impact = s.run(arq.recalculate_session_scores, "sid-item2")
    persisted = s.store["package_sqs"]
    reloaded = s.reload()
    assert persisted["package_sqs_score"] == reloaded["package_sqs_score"] == impact["score_after"]
    assert persisted["tier"] == reloaded["tier"] == impact["tier"]
    assert persisted["pillars"] == reloaded["pillars"]
    assert persisted["cap_applied"] == reloaded["cap_applied"]
    # labelled as the remediation it was; the label never moves the number
    assert persisted["calculation_stage"] == "arq_remediated"
    assert reloaded["calculation_stage"] == "initial_extract"


def test_a_producer_answer_moves_the_persisted_number_and_the_reload_together():
    s = _Session(_row())
    before = s.reload()["package_sqs_score"]
    ok, _upd = s.run(arq.apply_producer_answer_to_session, "sid-item2",
                     "contact_phone", "303-555-0100")
    assert ok is True
    s.run(arq.recalculate_session_scores, "sid-item2")
    assert s.store["package_sqs"]["package_sqs_score"] == s.reload()["package_sqs_score"] > before


def test_no_credit_is_applied_before_forms_exist():
    """The door never applies a credit before forms exist (the cards that earn
    one live in the editor), so the pre-form recalc must not either - or the
    persisted number is one no reload can reproduce."""
    s = _Session(_row(), credits=(10, [{"rec_id": "rec_x", "score_impact": 10}]))
    s.run(arq.recalculate_session_scores, "sid-item2")
    assert s.credit_calls == 0
    assert s.store["package_sqs"].get("credits_applied") in (None, 0)
    assert s.store["package_sqs"]["package_sqs_score"] == s.reload()["package_sqs_score"]


def _spy_package_scorer(monkeypatch):
    seen = []
    real = sq.calculate_package_sqs

    def spy(*a, **k):
        seen.append({"forms": len(k.get("form_results") or []),
                     "stage": k.get("calculation_stage")})
        return real(*a, **k)

    def door(*_a, **_k):
        raise AssertionError("the pre-form door must not score this row")

    monkeypatch.setattr(sq, "calculate_package_sqs", spy)
    monkeypatch.setattr(sq, "score_package_pre_generation", door)
    return seen


def test_a_clarity_row_keeps_its_own_recipe(monkeypatch):
    """Clarity / Lite: selected ids, nothing generated. Exactly as before - the
    per-selected-form facts scorer, then the package, credits re-applied."""
    seen = _spy_package_scorer(monkeypatch)
    s = _Session(_row(selected_form_ids=["ACORD_125", "ACORD_126"]),
                 credits=(5, [{"rec_id": "rec_x", "score_impact": 5}]))
    s.run(arq.recalculate_session_scores, "sid-item2")
    assert seen == [{"forms": 2, "stage": "arq_remediated"}]
    assert s.credit_calls == 1
    assert s.store["package_sqs"]["credits_applied"] == 5


def test_a_post_generation_row_is_untouched(monkeypatch):
    seen = _spy_package_scorer(monkeypatch)
    s = _Session(_row(generated_forms=_generated_125(), selected_form_ids=["ACORD_125"]),
                 credits=(4, [{"rec_id": "rec_x", "score_impact": 4}]))
    s.run(arq.recalculate_session_scores, "sid-item2")
    assert seen == [{"forms": 1, "stage": "arq_remediated"}]
    assert s.credit_calls == 1
    assert s.store["package_sqs"]["credits_applied"] == 4


@pytest.mark.parametrize("row,expected", [
    ({}, True),
    ({"generated_forms": {}, "selected_form_ids": []}, True),
    ({"selected_form_ids": ["ACORD_125"]}, False),
    ({"generated_forms": {"ACORD_125": {}}}, False),
    (None, False),
    ("not a row", False),
])
def test_the_pre_form_predicate(row, expected):
    assert sq.is_pre_form_session(row) is expected


# ── resolve / reopen report the door before forms ────────────────────────────

_CONTACT = "tier1_missing_Contact information"


def _resolve(s, **req):
    body = s.run(ar.resolve_issue, ResolveIssueRequest(session_id="sid-item2", **req),
                 current_user={"id": "u-item2"})
    return json.loads(body.body)


def _reopen(s, **req):
    body = s.run(ar.reopen_issue, ReopenIssueRequest(session_id="sid-item2", **req),
                 current_user={"id": "u-item2"})
    return json.loads(body.body)


def test_resolve_then_reopen_report_the_number_a_reload_prints():
    s = _Session(_row())
    out = _resolve(s, mode="field", field="contact_phone", value="303-555-0100",
                   code=_CONTACT, issue_id="iss-contact")
    assert out["success"] is True
    reloaded = s.reload()
    assert out["package_sqs"]["package_sqs_score"] == out["new_package_sqs_score"] \
        == s.store["package_sqs"]["package_sqs_score"] == reloaded["package_sqs_score"]
    assert out["new_package_tier"] == reloaded["tier"]
    # key details are refreshed - the supplied item is no longer "missing"
    assert out["key_details"] == sq.key_details(s.store["facts"], s.store["flags"])
    assert "Contact information" in out["key_details"]["satisfied"]
    assert out["key_details"]["missing"] == []

    back = _reopen(s, code=_CONTACT, issue_id="iss-contact")
    assert back["cleared"] is True
    reloaded = s.reload()
    assert back["package_sqs"]["package_sqs_score"] == back["new_package_sqs_score"] \
        == s.store["package_sqs"]["package_sqs_score"] == reloaded["package_sqs_score"]
    assert back["new_package_sqs_score"] < out["new_package_sqs_score"]
    assert back["key_details"]["missing"] == ["Contact information"]


@pytest.mark.parametrize("over", [
    {"generated_forms": _generated_125(), "selected_form_ids": ["ACORD_125"]},
    {"selected_form_ids": ["ACORD_125", "ACORD_126"]},
], ids=["editor", "clarity"])
def test_editor_and_clarity_responses_carry_nothing_new(over):
    s = _Session(_row(**over))
    out = _resolve(s, mode="field", field="contact_phone", value="303-555-0100",
                   code=_CONTACT, issue_id="iss-contact")
    after_resolve = s.store["package_sqs"]["package_sqs_score"]
    back = _reopen(s, code=_CONTACT, issue_id="iss-contact")
    after_reopen = s.store["package_sqs"]["package_sqs_score"]
    for body, persisted in ((out, after_resolve), (back, after_reopen)):
        assert "package_sqs" not in body and "key_details" not in body
        # the persisted, credit-bearing score, exactly as before
        assert body["new_package_sqs_score"] == persisted


def test_a_pending_integrity_review_withholds_both():
    card = asyncio.run(ar._pre_form_readiness(
        _row(integrity={"review_required": True}), "sid-item2", {"id": "u-item2"}))
    assert card == {"package_sqs": None, "key_details": None}


def test_the_card_helper_is_none_off_the_review_screen():
    for over in ({"generated_forms": _generated_125()}, {"selected_form_ids": ["ACORD_125"]}):
        assert asyncio.run(ar._pre_form_readiness(
            _row(**over), "sid-item2", {"id": "u-item2"})) is None


def test_both_handlers_ship_the_card_and_fold_the_doors_caps():
    """Structural twin of the behaviour above: each handler asks the one helper,
    spreads its result into the reply, and builds the Review cards from the
    score it reports (so a 60 the door holds keeps its card)."""
    tree = ast.parse(_src(Path(ar.__file__)))
    handlers = {n.name: n for n in ast.walk(tree)
                if isinstance(n, ast.AsyncFunctionDef) and n.name in ("resolve_issue", "reopen_issue")}
    assert set(handlers) == {"resolve_issue", "reopen_issue"}
    for name, fn in handlers.items():
        calls = [n for n in ast.walk(fn) if isinstance(n, ast.Call)]
        called = {getattr(c.func, "id", None) or getattr(c.func, "attr", None) for c in calls}
        assert "_pre_form_readiness" in called, name
        views = [c for c in calls if getattr(c.func, "id", None) == "_form_selection_view"]
        assert views and all(any(k.arg == "package_sqs" for k in c.keywords) for c in views), name
        spreads = [v for n in ast.walk(fn) if isinstance(n, ast.Dict)
                   for k, v in zip(n.keys, n.values)
                   if k is None and isinstance(v, ast.BoolOp)
                   and any(isinstance(x, ast.Name) and x.id == "_review_card" for x in v.values)]
        assert spreads, f"{name} does not spread the pre-form card into its reply"


def test_a_pre_form_resolve_scores_the_row_once(monkeypatch):
    """The recalc already scored THIS row through the door's recipe; the route
    reuses it (`package_rescored`) instead of paying for a second scoring."""
    calls = []
    real = sq.score_package_pre_generation

    def counting(*a, **k):
        calls.append(k.get("calculation_stage"))
        return real(*a, **k)

    monkeypatch.setattr(sq, "score_package_pre_generation", counting)
    s = _Session(_row())
    out = _resolve(s, mode="field", field="contact_phone", value="303-555-0100",
                   code=_CONTACT, issue_id="iss-contact")
    assert calls == ["arq_remediated"]
    assert out["package_sqs"]["package_sqs_score"] == s.reload()["package_sqs_score"]


def test_a_failed_recalc_score_falls_back_to_the_door(monkeypatch):
    """No fresh score -> the one helper decides, exactly as a reload would: a
    scorer that fails prints no number ("Not scored yet"), never a stale one."""
    def boom(*_a, **_k):
        raise RuntimeError("scorer exploded")

    monkeypatch.setattr(sq, "score_package_pre_generation", boom)
    s = _Session(_row())
    out = _resolve(s, mode="field", field="contact_phone", value="303-555-0100",
                   code=_CONTACT, issue_id="iss-contact")
    assert out["success"] is True
    assert out["package_sqs"] is None and out["new_package_sqs_score"] is None
    assert out["key_details"] == sq.key_details(s.store["facts"], s.store["flags"])
    assert s.reload() is None


# ══ Item 12 / G2 - the ONE premises: its interest, its revenue, its landlord ══
#
# Client (22 Sep): "The dec notes a tenant policy, not owner; as tenant, revenue
# should be $0 by default." G2: "If there is a landlord, the client must give the
# landlord's full name and address for certificates." Owner's ruling (29 Sep):
# TENANT is never silently inferred - the producer gets a one-click confirm card
# that shows its evidence; location revenue is NEVER $0 by default - with exactly
# one location whose own revenue is blank, ACORD 125's ANNUAL REVENUES box takes
# the business's `total_revenue`; a tenant is asked for the landlord's full name
# and address (recorded, printed nowhere yet). Two or more locations: no copy, no
# card, no landlord ask. See services/premises_interest.py and
# pdf_service._ONE_PREMISES_TWINS.

import re

import services.pdf_service as _pi_ps
import services.premises_interest as _pi
import services.sqs_service as _pi_sqs
from services import schedule_capture as _pi_sc

_PI_OWNER = "CommercialStructure_InsuredInterest_OwnerIndicator_A"
_PI_TENANT = "CommercialStructure_InsuredInterest_TenantIndicator_A"
_PI_OTHER = "CommercialStructure_InsuredInterest_OtherIndicator_A"
_PI_OTHER_DESC = "CommercialStructure_InsuredInterest_OtherDescription_A"
_PI_REVENUE = "CommercialStructure_AnnualRevenueAmount_A"
_PI_BOXES = (_PI_OWNER, _PI_TENANT, _PI_OTHER, _PI_OTHER_DESC, _PI_REVENUE)
_PI_TENANT_OPT = "Tenant - the business rents its space"
_PI_OWNER_OPT = "Owner - the business owns the building"

# The client's own premises row (Orbin session 8992d874), verbatim.
_PI_ORBIN_ROW = {
    "address": "4800 DAHLIA STREET D13, DENVER CO. 80216-3121", "building_number": "001",
    "address_line1": "4800 DAHLIA ST", "address_line2": "# D13", "address_city": "DENVER",
    "address_state": "CO", "address_zip": "80216-3121", "location_id": "L1",
    "location_number": "1", "address_county": None, "is_owner": None, "is_tenant": None,
    "is_other_interest": None, "other_interest_description": None,
    "is_inside_city_limits": None, "is_outside_city_limits": None,
}
_PI_ORBIN_FLAGS = {"has_property_coverage": False, "has_general_liability": True,
                   "has_auto_coverage": True, "has_umbrella": True}
_PI_SECOND_ROW = {"address": "900 Market St, Denver, CO 80202", "address_line1": "900 Market St",
                  "address_line2": None, "address_city": "Denver", "address_state": "CO",
                  "address_zip": "80202", "location_number": "2", "is_owner": None,
                  "is_tenant": None, "is_other_interest": None,
                  "other_interest_description": None}


def _pi_facts(**over):
    """The Orbin shape: one premises with a unit, no property line, no revenue."""
    f = {
        "applicant_name": {"value": "ORBIN CONTRACTING LLC", "source": "ai"},
        "property_locations": [copy.deepcopy(_PI_ORBIN_ROW)],
        "coverage_lines": [
            {"line": "Commercial General Liability", "premium": "$3,954.00",
             "policy_number": "BBC7263-26"},
            {"line": "Property", "premium": None, "policy_number": None},
        ],
    }
    f.update(over)
    return f


def _pi_person(v, source="producer"):
    return {"value": v, "source": source, "confidence": "filled"}


def _pi_row(**over):
    return dict(copy.deepcopy(_PI_ORBIN_ROW), **over)


def _pi_three_doors(facts, flags=None, form_id="ACORD_125"):
    """(_deterministic_map, compute_form_gaps, map_facts_to_form, sent to gap fill)
    for the five premises boxes - the three doors every box goes through."""
    schema = _schema(form_id)
    f = {**facts, **(flags if flags is not None else _PI_ORBIN_FLAGS)}
    boxes = [b for b in _PI_BOXES if b in schema]
    with _pi_ps._schema_context(schema):
        det = {b: _pi_ps._deterministic_map(b, {**f, "_form_id": form_id}) for b in boxes}
    mapped, unmatched, _det = _pi_ps.compute_form_gaps(form_id, schema, dict(f))
    gaps = {b: mapped.get(b) for b in boxes}
    out = _pi_ps.map_facts_to_form(dict(f), schema, form_id, raw_text="",
                                   pre_filled_gpt={"filled_values": {}})
    stamped = out[0] if isinstance(out, tuple) else out
    fill = {b: stamped.get(b) for b in boxes}
    return det, gaps, fill, [b for b in boxes if b in unmatched]


def _pi_blank(v):
    return v in (None, "")


def _pi_card(facts, flags=None, mapped=None):
    res = _pi_sqs.calculate_sqs(
        facts=facts, flags=flags if flags is not None else _PI_ORBIN_FLAGS,
        mapped_data=mapped or {"NamedInsured_FullName_A": "ORBIN CONTRACTING LLC"},
        form_schema=_schema("ACORD_125"), selected_form_ids=["ACORD_125"], hard_stops=[],
        soft_stops=[], tier2_score=60, form_id="ACORD_125")
    recs = {r.get("rec_id"): r for r in res.get("recommendations") or []
            if isinstance(r, dict)}
    return res, recs


# ── 1. Tenant is never inferred ──────────────────────────────────────────────

def test_the_orbin_shape_ticks_nothing_at_any_door_and_asks_no_model():
    before = copy.deepcopy(_pi_facts())
    facts = _pi_facts()
    det, gaps, fill, sent = _pi_three_doors(facts)
    for door in (det, gaps, fill):
        assert all(_pi_blank(v) for v in door.values()), door
    assert sent == [], "an interest box must never reach gap fill"
    assert facts == before, "no door may write an interest into the facts"
    assert "premises_interest" not in facts


def test_the_consolidation_still_leaves_a_silent_dec_unknown():
    facts = {"property_locations": [{"address": "4800 Dahlia St # D13, Denver, CO 80216-3121"}]}
    es._consolidate_property_locations(facts)
    row = facts["property_locations"][0]
    assert row["is_owner"] is None and row["is_tenant"] is None
    assert row["is_other_interest"] is None and "premises_interest" not in facts


def test_the_wording_rule_moved_unchanged():
    # The consolidation's own block, now one door for documents AND answers.
    assert _pi.interest_from_wording("owned, rented or occupied by the named insured") is None
    assert _pi.interest_from_wording("tenant") == (_pi.TENANT, None)
    assert _pi.interest_from_wording("owner") == (_pi.OWNER, None)
    assert _pi.interest_from_wording("Tenant (leased office space)") == (_pi.TENANT, None)
    assert _pi.interest_from_wording("Licensee under a shared-use agreement") == (
        _pi.OTHER, "Licensee under a shared-use agreement")
    assert _pi.interest_from_wording("leased") == (_pi.OTHER, "leased")
    assert _pi.interest_from_wording("") is None and _pi.interest_from_wording(None) is None
    facts = {"property_locations": [{"address": "1 Main St, Denver, CO 80202",
                                     "ownership": "Licensee under a shared-use agreement"}]}
    es._consolidate_property_locations(facts)
    row = facts["property_locations"][0]
    assert (row["is_owner"], row["is_tenant"], row["is_other_interest"]) == (False, False, True)
    assert row["other_interest_description"] == "Licensee under a shared-use agreement"


def test_a_label_on_the_dec_index_never_backfills_the_interest():
    """The validator is deliberately not `_is_*`, so the dec-entry backfill -
    which fills only `_is_*` typed facts from printed labels - never reads an
    interest off a page."""
    facts = _pi_facts()
    entries = [{"label": "Premises Interest", "value": "Tenant", "owner": "applicant"},
               {"label": "Insured Interest", "value": "Tenant", "owner": "applicant"}]
    es._backfill_empty_facts_from_entries(facts, entries)
    assert "premises_interest" not in facts


def test_the_new_facts_sit_on_no_line_and_score_nothing():
    from services.fact_registry import FACT_REGISTRY, TIER1_REQUIRED_FIELDS, TIER2_SCORED_FIELDS
    from services.lob_canon import fact_line_family
    for key in ("premises_interest", "landlord_name", "landlord_address"):
        assert key in FACT_REGISTRY and not key.startswith("property_")
        assert fact_line_family(key) is None
        assert key not in TIER1_REQUIRED_FIELDS and key not in TIER2_SCORED_FIELDS
        assert all(key not in inv for inv in _pi_sqs.FORM_FIELD_INVENTORY.values()), (
            f"{key} in an inventory would be asked on every package")


# ── 2. The evidence ─────────────────────────────────────────────────────────

def test_orbin_suggests_tenant_for_two_reasons():
    ev = _pi.tenant_evidence(_pi_facts(), _PI_ORBIN_FLAGS)
    assert ev["owner"] == []
    assert len(ev["tenant"]) == 2
    assert "# D13" in ev["tenant"][0] and "no property coverage" in ev["tenant"][1]
    assert _pi.suggested_kind(ev) == _pi.TENANT


@pytest.mark.parametrize("over", [
    {"property_locations": [_pi_row(building_value="$385,000")]},
    {"property_building_value": {"value": "$1,480,000", "source": "ai"}},
    {"mortgagee_name": {"value": "First Western Bank", "source": "ai"}},
])
def test_an_owner_signal_means_no_suggestion(over):
    facts = _pi_facts(**over)
    ev = _pi.tenant_evidence(facts, _PI_ORBIN_FLAGS)
    assert ev["owner"] and _pi.suggested_kind(ev) is None
    _res, recs = _pi_card(facts)
    card = recs["rec_premises_interest"]
    assert "suggested_answer" not in card and "suggestion_evidence" not in card


def test_one_signal_shows_its_evidence_but_selects_nothing():
    carried = {**_PI_ORBIN_FLAGS, "has_property_coverage": True}
    _res, recs = _pi_card(_pi_facts(), flags=carried)
    card = recs["rec_premises_interest"]
    assert "# D13" in card["suggestion_evidence"]
    assert "suggested_answer" not in card
    no_unit = _pi_facts(property_locations=[_pi_row(address_line2=None)])
    _res, recs = _pi_card(no_unit)
    card = recs["rec_premises_interest"]
    assert "no property coverage" in card["suggestion_evidence"]
    assert "suggested_answer" not in card


def test_a_state_and_zip_are_not_a_floor_number():
    row = _pi_row(address_line1="123 Ocean Dr FL 33101", address_line2=None,
                  address_city="Miami", address_state="FL", address_zip="33101")
    ev = _pi.tenant_evidence(_pi_facts(property_locations=[row]), _PI_ORBIN_FLAGS)
    assert not any("unit" in r for r in ev["tenant"])


def test_no_card_when_the_document_states_the_interest_or_two_locations():
    stated = _pi_facts(property_locations=[_pi_row(is_owner=False, is_tenant=True,
                                                   is_other_interest=False)])
    _res, recs = _pi_card(stated)
    assert "rec_premises_interest" not in recs
    two = _pi_facts(property_locations=[_pi_row(), copy.deepcopy(_PI_SECOND_ROW)])
    _res, recs = _pi_card(two)
    assert not any(k in recs for k in ("rec_premises_interest", "rec_landlord_name",
                                       "rec_landlord_address"))
    assert _pi.tenant_evidence(two, _PI_ORBIN_FLAGS) == {"tenant": [], "owner": []}


# ── 3. Confirming ticks the right boxes, at all three doors ─────────────────

@pytest.mark.parametrize("answer,expect", [
    (_PI_TENANT_OPT, {_PI_OWNER: "No", _PI_TENANT: "Yes", _PI_OTHER: "No", _PI_OTHER_DESC: None}),
    (_PI_OWNER_OPT, {_PI_OWNER: "Yes", _PI_TENANT: "No", _PI_OTHER: "No", _PI_OTHER_DESC: None}),
    ("Other: licensee under a shared-use agreement",
     {_PI_OWNER: "No", _PI_TENANT: "No", _PI_OTHER: "Yes",
      _PI_OTHER_DESC: "licensee under a shared-use agreement"}),
])
def test_a_confirmed_interest_ticks_its_box_at_every_door(answer, expect):
    facts = _pi_facts(premises_interest=_pi_person(answer))
    det, gaps, fill, sent = _pi_three_doors(facts)
    for door in (det, gaps, fill):
        for box, want in expect.items():
            if want is None:
                assert _pi_blank(door[box]), (box, door[box])
            else:
                assert door[box] == want, (box, door[box])
    assert sent == []


def test_the_form_160_premises_boxes_are_untouched():
    facts = _pi_facts(premises_interest=_pi_person(_PI_TENANT_OPT))
    schema = _schema("ACORD_160")
    with _pi_ps._schema_context(schema):
        got = _pi_ps._deterministic_map(_PI_OWNER, {**facts, **_PI_ORBIN_FLAGS,
                                                    "_form_id": "ACORD_160"})
    assert _pi_blank(got), "the twin is ACORD 125's only"


# ── 4. Every option label resolves to its own kind ──────────────────────────

def test_every_option_label_reads_back_as_its_own_kind():
    from services.answer_options import OTHER, options_for
    from services.answer_semantics import VALUE, interpret_answer
    from services.fact_registry import FACT_REGISTRY
    opts = options_for("premises_interest")
    assert opts[-1] == OTHER and len(opts) == 3
    check = FACT_REGISTRY["premises_interest"]["validate"]
    for label in opts[:-1]:
        kind = label.split(" ", 1)[0].lower()
        assert _pi.kind_of_answer(label) == (kind, None)
        # The wording rule reads the same label the same way (the WORDING TRAP:
        # a Tenant label naming "rents OR leases" would read as undetermined).
        assert _pi.interest_from_wording(label) == (kind, None)
        assert " or " not in label.lower()
        r = interpret_answer("premises_interest", label)
        assert r.intent == VALUE and r.value == label and check(r.value)
        assert _pi.option_for_kind(kind) == label
    assert _pi.kind_of_answer("Other") == (_pi.OTHER, None)
    for non_answer in ("Yes", "No", "owned, rented or occupied", "", None):
        assert _pi.kind_of_answer(non_answer) is None


# ── 5. A document-stated interest outranks the fact ─────────────────────────

def test_the_documents_interest_outranks_a_persons_answer():
    facts = _pi_facts(property_locations=[_pi_row(is_owner=True, is_tenant=False,
                                                  is_other_interest=False)],
                      premises_interest=_pi_person(_PI_TENANT_OPT))
    det, gaps, fill, _sent = _pi_three_doors(facts)
    for door in (det, gaps, fill):
        assert door[_PI_OWNER] == "Yes" and door[_PI_TENANT] == "No"
    assert _pi.single_premises_interest(facts) == _pi.OWNER
    _res, recs = _pi_card(facts)
    assert not any(k in recs for k in ("rec_premises_interest", "rec_landlord_name"))


# ── 6. Two locations: nothing copied, nothing ticked ────────────────────────

def test_two_locations_copy_nothing_and_tick_nothing():
    facts = _pi_facts(property_locations=[_pi_row(), copy.deepcopy(_PI_SECOND_ROW)],
                      total_revenue={"value": "$1,200,000", "source": "ai"},
                      premises_interest=_pi_person(_PI_TENANT_OPT))
    det, gaps, fill, sent = _pi_three_doors(facts)
    for door in (det, gaps, fill):
        assert all(_pi_blank(v) for v in door.values()), door
    assert sent == []
    assert _pi.single_premises_interest(facts) is None
    assert _pi_ps.source_fact_for_field(_PI_REVENUE, {**facts, "_form_id": "ACORD_125"}) is None


# ── 7. Revenue: the business's own, never a $0 by default ───────────────────

def _pi_revenue(facts):
    det, gaps, fill, sent = _pi_three_doors(facts)
    assert _PI_REVENUE not in sent
    return det[_PI_REVENUE], gaps[_PI_REVENUE], fill[_PI_REVENUE]


def test_a_blank_row_takes_the_business_revenue():
    got = _pi_revenue(_pi_facts(total_revenue={"value": "$1,200,000", "source": "ai"}))
    assert got[0] == "$1,200,000" and got[1] == "$1,200,000"
    assert re.sub(r"[^\d]", "", str(got[2])) == "1200000"


def test_the_rows_own_revenue_wins():
    facts = _pi_facts(property_locations=[_pi_row(annual_revenue="$250,000")],
                      total_revenue={"value": "$1,200,000", "source": "ai"})
    assert _pi_revenue(facts)[0] == "$250,000"
    assert _pi_ps.source_fact_for_field(_PI_REVENUE, {**facts, "_form_id": "ACORD_125"}) is None


@pytest.mark.parametrize("total", [
    {"value": "$0", "source": "ai"},                       # a model's zero
    {"value": "0", "source": "dec_entry"},                 # a document's zero
    {"value": "$1M - $2M", "source": "ai"},                # a range
    "Included",                                            # not an amount
    {"value": "$39,300", "source": "ai",                   # one class's exposure
     "derivation": {"rule": "dec_entry_backfill"}},
])
def test_what_the_revenue_box_never_prints(total):
    facts = _pi_facts(total_revenue=total, gl_class_code_schedule=[
        {"location": "Location 001", "class_code": "91580", "premium_basis": "Payroll",
         "exposure_amount": "$39,300",
         "classification": "Contractors - Executive Supervisors or Executive Superintendents"}])
    for v in _pi_revenue(facts):
        assert _pi_blank(v), v


@pytest.mark.parametrize("source", ["producer", "client_arq"])
def test_a_persons_zero_prints(source):
    det, gaps, fill = _pi_revenue(_pi_facts(total_revenue=_pi_person("$0", source)))
    assert det == "$0" and gaps == "$0"
    assert re.sub(r"[^\d]", "", str(fill)) == "0"         # printed, not blanked


def test_the_131_gross_sales_box_is_unchanged_by_the_extraction():
    base = {"_form_id": "ACORD_131", "property_locations": [_pi_row()],
            "_only_dec_page": True, "_only_certificate": False}
    box = "BusinessInformation_AnnualGrossReceiptsAmount_A"
    assert _pi_ps._resolve_business_total_payroll(
        box, {**base, "total_revenue": {"value": "$2,400,000", "source": "ai"}}) == "$2,400,000"
    assert _pi_ps._resolve_business_total_payroll(
        box, {**base, "total_revenue": {"value": "$0", "source": "ai"}}) is None
    assert _pi_ps._resolve_business_total_payroll(
        box, {**base, "total_revenue": _pi_person("$0")}) == "$0"


# ── 8. The twins survive a location-table edit ──────────────────────────────

def _pi_generated(facts):
    schema = _schema("ACORD_125")
    out = _pi_ps.map_facts_to_form({**facts, **_PI_ORBIN_FLAGS}, schema, "ACORD_125",
                                   raw_text="", pre_filled_gpt={"filled_values": {}})
    mapped, conf = out if isinstance(out, tuple) else (out, {})
    return {"ACORD_125": {"schema": schema, "field_state": dict(mapped),
                          "confidence": dict(conf or {}), "client_filled_fields": []}}


def test_the_twins_survive_a_location_table_edit_and_keep_honest_labels():
    facts = _pi_facts(total_revenue={"value": "$1,200,000", "source": "ai"},
                      premises_interest=_pi_person(_PI_TENANT_OPT))
    gen = _pi_generated(facts)
    rows = _pi_sc.rows_from_facts("property_locations", facts)
    clean, _rep = _pi_sc.validate_rows("property_locations", rows)
    clean[0]["address_city"] = "Denver"                   # an EDIT, not a confirm
    edited = copy.deepcopy(facts)
    edited["property_locations"] = _pi_sc.rows_for_facts("property_locations", clean)
    arq._restamp_schedule_into_forms(gen, "property_locations", edited)
    form = gen["ACORD_125"]
    state, conf = form["field_state"], form["confidence"]
    assert state[_PI_TENANT] == "Yes" and state[_PI_OWNER] == "No"
    assert re.sub(r"[^\d]", "", str(state[_PI_REVENUE])) == "1200000"
    # The revenue came from a DOCUMENT - never relabelled as the client's.
    assert conf.get(_PI_REVENUE) != "client_arq"
    assert _PI_REVENUE not in (form.get("client_filled_fields") or [])


# ── 9. A restamp after an answer ────────────────────────────────────────────

def test_a_client_revenue_answer_stamps_the_premises_box_as_the_clients():
    facts = _pi_facts()
    gen = _pi_generated(facts)
    assert _pi_blank(gen["ACORD_125"]["field_state"].get(_PI_REVENUE))
    facts["total_revenue"] = _pi_person("$300,000", "client_arq")
    touched = arq._restamp_canonical_into_forms(gen, "total_revenue", facts)
    form = gen["ACORD_125"]
    assert "ACORD_125" in touched
    # The form prints the "$" beside this box, so the value carries none - as
    # generation prints it (display_value_for_box, 29 Sep 2026).
    assert form["field_state"][_PI_REVENUE] == "300,000"
    assert form["confidence"][_PI_REVENUE] == "client_arq"
    assert _PI_REVENUE in form["client_filled_fields"]


def test_a_rows_own_revenue_is_never_relabelled_as_the_clients():
    facts = _pi_facts(property_locations=[_pi_row(annual_revenue="$250,000")])
    gen = _pi_generated(facts)
    label_before = gen["ACORD_125"]["confidence"].get(_PI_REVENUE)
    value_before = gen["ACORD_125"]["field_state"].get(_PI_REVENUE)
    facts["total_revenue"] = _pi_person("$300,000", "client_arq")
    arq._restamp_canonical_into_forms(gen, "total_revenue", facts)
    form = gen["ACORD_125"]
    assert form["field_state"].get(_PI_REVENUE) == value_before
    assert form["confidence"].get(_PI_REVENUE) == label_before != "client_arq"
    assert _PI_REVENUE not in form["client_filled_fields"]


def test_a_changed_answer_leaves_no_stale_other_description():
    facts = _pi_facts(premises_interest=_pi_person("Other: licensee"))
    gen = _pi_generated({k: v for k, v in facts.items() if k != "premises_interest"})
    arq._restamp_canonical_into_forms(gen, "premises_interest", facts, provenance="producer")
    state = gen["ACORD_125"]["field_state"]
    assert state[_PI_OTHER] == "Yes" and state[_PI_OTHER_DESC] == "licensee"
    facts["premises_interest"] = _pi_person(_PI_TENANT_OPT)
    arq._restamp_canonical_into_forms(gen, "premises_interest", facts, provenance="producer")
    state, conf = gen["ACORD_125"]["field_state"], gen["ACORD_125"]["confidence"]
    assert state[_PI_TENANT] == "Yes" and state[_PI_OTHER] == "No"
    assert _pi_blank(state[_PI_OTHER_DESC]) and _PI_OTHER_DESC not in conf
    assert conf[_PI_TENANT] == "producer"


# ── 10. The producer's answer, and Reopen, through the real doors ───────────

def _pi_session(facts, generated):
    return {"facts": copy.deepcopy(facts), "flags": dict(_PI_ORBIN_FLAGS),
            "generated_forms": generated}


def _pi_run(store, coro_fn):
    async def _get(_sid, include_pdf=False):
        return copy.deepcopy(store)

    async def _upd(_sid, payload, delete_facts=None):
        for k, v in (payload or {}).items():
            store[k] = v
        for k in delete_facts or ():
            (store.get("facts") or {}).pop(k, None)
        return True

    with patch.object(sr, "get_processing_session", _get), \
         patch.object(sr, "upd_processing_session", _upd):
        return asyncio.run(coro_fn())


def test_the_card_answer_ticks_tenant_and_reopen_clears_it():
    facts = _pi_facts()
    store = _pi_session(facts, _pi_generated(facts))
    ok, _upd = _pi_run(store, lambda: arq.apply_producer_answer_to_session(
        "sid-pi", "premises_interest", _PI_TENANT_OPT))
    assert ok is True
    form = store["generated_forms"]["ACORD_125"]
    assert form["field_state"][_PI_TENANT] == "Yes"
    assert form["field_state"][_PI_OWNER] == "No"
    assert form["confidence"][_PI_TENANT] == "producer"
    assert _v(store["facts"]["premises_interest"]) == _PI_TENANT_OPT
    ok, _upd = _pi_run(store, lambda: arq.clear_producer_answer_from_session(
        "sid-pi", "premises_interest"))
    assert ok is True
    form = store["generated_forms"]["ACORD_125"]
    for box in (_PI_OWNER, _PI_TENANT, _PI_OTHER):
        assert _pi_blank(form["field_state"].get(box)), box
        assert box not in form["confidence"]


def test_reopen_never_reaches_a_second_locations_row():
    two = _pi_facts(property_locations=[_pi_row(annual_revenue="$250,000"),
                                        copy.deepcopy(_PI_SECOND_ROW)])
    gen = _pi_generated(two)
    before = gen["ACORD_125"]["field_state"][_PI_REVENUE]
    assert re.sub(r"[^\d]", "", str(before)) == "250000"
    gen["ACORD_125"]["confidence"][_PI_REVENUE] = "client_arq"   # a table edit's label
    two["total_revenue"] = _pi_person("$300,000")
    cleared = arq._clear_canonical_from_forms(gen, "total_revenue", two)
    assert gen["ACORD_125"]["field_state"][_PI_REVENUE] == before
    assert "ACORD_125" not in cleared


# ── 11. A conflict withhold on total_revenue blanks the copy ────────────────

def test_an_unresolved_revenue_conflict_withholds_the_copy():
    facts = _pi_facts(total_revenue={"value": "$1,200,000", "source": "ai"},
                      _uw_conflicted_keys=["total_revenue"])
    assert _pi_ps.source_fact_for_field(_PI_REVENUE, {**facts, "_form_id": "ACORD_125"}) \
        == "total_revenue"
    for v in _pi_revenue(facts):
        assert _pi_blank(v), v
    conf = _pi_ps.apply_fact_state_confidence_labels(
        "ACORD_125", {**facts, "_uw_conflict_keys": ["total_revenue"]},
        {_PI_REVENUE: "$1,200,000"}, {_PI_REVENUE: "filled"})
    assert conf[_PI_REVENUE] == "conflicted"


# ── 12. The questionnaire ────────────────────────────────────────────────────

def _pi_questions(facts, forms=("ACORD_125",), flags=None):
    qs = arq.generate_arq_questions_from_facts(
        copy.deepcopy(facts), dict(flags if flags is not None else _PI_ORBIN_FLAGS),
        list(forms), [], [])
    return {q["field_name"]: q for q in qs
            if q["field_name"] in ("premises_interest", "landlord_name", "landlord_address")}


def test_the_insured_is_asked_optionally_with_no_evidence():
    qs = _pi_questions(_pi_facts())
    assert set(qs) == {"premises_interest"}
    q = qs["premises_interest"]
    assert q["field_type"] == "select"
    assert q["options"] == [_PI_TENANT_OPT, _PI_OWNER_OPT, "Other"]
    assert q["audience"] == "client" and q["default_selected"] is False
    text = (q["question"] + " " + q.get("hint", "")).lower()
    assert "d13" not in text and "evidence" not in text and "property coverage" not in text


def test_no_question_without_acord_125_or_with_two_locations():
    assert _pi_questions(_pi_facts(), forms=("ACORD_126",)) == {}
    two = _pi_facts(property_locations=[_pi_row(), copy.deepcopy(_PI_SECOND_ROW)])
    assert _pi_questions(two) == {}


def test_the_landlord_is_asked_only_of_a_tenant():
    tenant = _pi_facts(premises_interest=_pi_person(_PI_TENANT_OPT))
    qs = _pi_questions(tenant)
    assert set(qs) == {"landlord_name", "landlord_address"}
    assert all(q["default_selected"] is False and q["audience"] == "client"
               for q in qs.values())
    assert _pi_questions(_pi_facts(premises_interest=_pi_person(_PI_OWNER_OPT))) == {}
    done = dict(tenant, landlord_name=_pi_person("Dahlia Holdings LLC"),
                landlord_address=_pi_person("1 Main St, Denver, CO 80202"))
    assert _pi_questions(done) == {}
    stated = _pi_facts(property_locations=[_pi_row(is_owner=False, is_tenant=True,
                                                   is_other_interest=False)])
    assert set(_pi_questions(stated)) == {"landlord_name", "landlord_address"}


def test_a_form_already_ticked_is_not_asked_again():
    facts = _pi_facts()
    gen = _pi_generated(facts)
    gen["ACORD_125"]["field_state"][_PI_TENANT] = "Yes"      # the producer ticked it
    qs = asyncio.run(arq.generate_arq_questions(
        facts=copy.deepcopy(facts), flags=dict(_PI_ORBIN_FLAGS), generated_forms=gen,
        hard_stops=[], soft_stops=[], session_docs=[]))
    assert "premises_interest" not in {q["field_name"] for q in qs}
    _res, recs = _pi_card(facts, mapped=gen["ACORD_125"]["field_state"])
    assert "rec_premises_interest" not in recs


def test_the_fr125_package_gets_no_new_question():
    dump = os.path.join(HERE, "..", "..", "fr125_test_data", "runs", "r2t8_e3cebd88_dump.json")
    if not os.path.exists(dump):
        pytest.skip("FR125 run dump not present")
    with open(dump, encoding="utf-8") as fh:
        d = json.load(fh)
    facts, flags = d["merged_facts"], d.get("flags") or {}
    assert _pi.one_premises_row(facts) is None               # eight rows
    assert _pi_questions(facts, flags=flags) == {}
    _res, recs = _pi_card(facts, flags=flags)
    assert not any(k in recs for k in ("rec_premises_interest", "rec_landlord_name",
                                       "rec_landlord_address"))


# ── 13. The card ────────────────────────────────────────────────────────────

def test_the_card_is_a_zero_point_field_card_with_its_suggestion():
    res, recs = _pi_card(_pi_facts())
    card = recs["rec_premises_interest"]
    assert card["field"] == "premises_interest" and card["answer_mode"] == "field"
    assert card["answer_options"] == [_PI_TENANT_OPT, _PI_OWNER_OPT, "Other"]
    assert card["suggested_answer"] == _PI_TENANT_OPT
    assert "# D13" in card["suggestion_evidence"]
    assert "—" not in card["suggestion_evidence"] + card["message"]
    assert card["score_impact"] == 0 and card["unscored"] is True
    assert "4800 DAHLIA ST # D13" in card["message"]
    assert "rec_landlord_name" not in recs
    # The card moves no score.
    with patch.object(_pi_sqs, "_premises_recommendations", lambda *_a, **_k: []):
        bare, bare_recs = _pi_card(_pi_facts())
    assert "rec_premises_interest" not in bare_recs
    assert bare["sqs_score"] == res["sqs_score"]


def test_the_card_is_gone_after_the_answer_and_the_landlord_follows():
    facts = _pi_facts(premises_interest=_pi_person(_PI_TENANT_OPT))
    _res, recs = _pi_card(facts)
    assert "rec_premises_interest" not in recs
    for key in ("rec_landlord_name", "rec_landlord_address"):
        assert recs[key]["answer_mode"] == "field" and recs[key]["score_impact"] == 0
        assert recs[key]["unscored"] is True and "certificates" in recs[key]["message"]
    done = dict(facts, landlord_name=_pi_person("Dahlia Holdings LLC"),
                landlord_address=_pi_person("1 Main St, Denver, CO 80202"))
    _res, recs = _pi_card(done)
    assert not any(k in recs for k in ("rec_premises_interest", "rec_landlord_name",
                                       "rec_landlord_address"))
    # Recorded for certificates, printed nowhere.
    det, gaps, fill, _sent = _pi_three_doors(done)
    for door in (det, gaps, fill):
        assert "Dahlia Holdings LLC" not in {str(v) for v in door.values()}


# ── Review finding (29 Sep): the card answer is the RECEIVING carrier ────────
# It is written to `submission_carrier_name` (never the documents' own
# `carrier_name`), page one is re-judged at once, and a market that does not
# write the current policies never prints beside their premiums.

_P1_PREMIUMS = {"GeneralLiabilityLineOfBusiness_TotalPremiumAmount_A": "3,954",
                "CommercialVehicleLineOfBusiness_PremiumAmount_A": "2,991",
                "CommercialInlandMarineLineOfBusiness_PremiumAmount_A": "300",
                "CommercialUmbrellaLineOfBusiness_PremiumAmount_A": "3,418",
                "Policy_Payment_EstimatedTotalAmount_A": "10,663"}


def _orbin_generated_125():
    mf = _page_one_mf()
    es._mark_page_one_current_policy(mf, [_doc()])
    mapped = dict(_P1_PREMIUMS, NamedInsured_FullName_A="Orbin Contracting LLC")
    gen = {"ACORD_125": {"schema": _schema("ACORD_125"), "mapped": dict(mapped),
                         "field_state": dict(mapped),
                         "confidence": {k: "filled" for k in mapped}, "client_filled_fields": []}}
    return mf, gen


def _apply_with_docs(field, value, facts, generated):
    store = {"facts": copy.deepcopy(facts), "flags": {}, "generated_forms": generated,
             "docs": [_doc()]}

    async def _get(_sid):
        return copy.deepcopy(store)

    async def _upd(_sid, payload, delete_facts=None):
        store.update(payload or {})
        return True

    with patch.object(sr, "get_processing_session", _get), \
         patch.object(sr, "upd_processing_session", _upd):
        ok, updated = asyncio.run(arq.apply_producer_answer_to_session("sid-p1", field, value))
    return ok, updated, store


def test_a_new_market_prints_as_carrier_and_the_dec_premiums_go():
    mf, gen = _orbin_generated_125()
    ok, updated, store = _apply_with_docs("submission_carrier_name", "Travelers Casualty Company",
                                          mf, gen)
    assert ok is True and "ACORD_125" in updated
    f = store["generated_forms"]["ACORD_125"]
    assert f["field_state"]["Insurer_FullName_A"] == "Travelers Casualty Company"
    assert f["confidence"]["Insurer_FullName_A"] == "producer"
    assert "Insurer_FullName_A" not in f["client_filled_fields"]
    assert not str(f["field_state"].get("Insurer_NAICCode_A") or "").strip()
    for box in _P1_PREMIUMS:
        assert not str(f["field_state"].get(box) or "").strip(), box
    facts = store["facts"]
    assert _v(facts["carrier_name"]) == _EMCC                  # the documents' fact is untouched
    assert facts.get("premium_is_current_policy") is True
    assert "renews_current_programme" not in facts


def test_naming_a_company_that_writes_the_policies_keeps_the_renewal():
    mf, gen = _orbin_generated_125()
    ok, _u, store = _apply_with_docs("submission_carrier_name", _EMCPC, mf, gen)
    f = store["generated_forms"]["ACORD_125"]
    assert f["field_state"]["Insurer_FullName_A"] == _EMCPC
    for box, val in _P1_PREMIUMS.items():
        assert f["field_state"][box] == val, box
    assert store["facts"].get("renews_current_programme") is True


def test_the_presumption_reads_the_addressee_against_the_writers():
    assert es._renews_current_programme(
        _page_one_mf(submission_carrier_name={"value": _EMCPC, "source": "producer"}), [_doc()]) is True
    assert es._renews_current_programme(
        _page_one_mf(submission_carrier_name={"value": "Travelers", "source": "producer"}), [_doc()]) is False


def test_the_receiving_carrier_is_producer_only():
    from services.question_eligibility import INSURANCE_JUDGMENT_FACTS
    assert "submission_carrier_name" in INSURANCE_JUDGMENT_FACTS


def test_a_re_merge_re_judges_page_one_with_the_producers_carrier():
    import inspect
    from services import extraction_pipeline
    src = inspect.getsource(extraction_pipeline._finalize_pipeline)
    assert "submission_carrier_name" in src and "_mark_page_one_current_policy" in src


# ── Review findings #2, #3, #5, #6 (29 Sep) ─────────────────────────────────

def test_the_carrier_card_does_not_fire_before_forms_when_the_carrier_prints():
    # The facts-only scorer passes a mapping keyed by fact names; that is not a
    # blank CARRIER box.
    import services.sqs_service as sq
    one = [dict(r, carrier=_EMCC) for r in _ORBIN_LINES if r.get("carrier")]
    mf = _page_one_mf(lines=one)
    es._mark_page_one_current_policy(mf, [_doc()])
    assert sq._page_one_carrier_printed(mf, {"applicant_name": "X"}) is True
    assert sq._page_one_carrier_printed(mf, {"Insurer_FullName_A": ""}) is False


def test_reopening_the_effective_date_takes_its_followed_expiration():
    import inspect
    src = inspect.getsource(arq.clear_producer_answer_from_session)
    assert "proposed_expiration_follows_effective" in src
    assert "submission_carrier_name" in src and "_refresh_acord125_page_one" in src


def test_a_new_market_answer_deletes_the_dropped_flags_from_storage():
    mf, gen = _orbin_generated_125()
    deleted = {}
    store = {"facts": copy.deepcopy(mf), "flags": {}, "generated_forms": gen, "docs": [_doc()]}

    async def _get(_sid):
        return copy.deepcopy(store)

    async def _upd(_sid, payload, delete_facts=None):
        deleted["keys"] = list(delete_facts or [])
        return True

    with patch.object(sr, "get_processing_session", _get), \
         patch.object(sr, "upd_processing_session", _upd):
        asyncio.run(arq.apply_producer_answer_to_session("sid-p1", "submission_carrier_name",
                                                         "Travelers Casualty Company"))
    assert "renews_current_programme" in deleted["keys"]


@pytest.mark.parametrize("line1,line2,unit", [
    ("4800 DAHLIA ST", "# D13", "# D13"),
    ("12 Main St Suite 210", "", "Suite 210"),
    ("9 Oak Rd Unit B", "", "Unit B"),
    ("500 Ste Genevieve Ave", "", None),
    ("8 Apt Ln", "", None),
    ("55 Unit Dr", "", None),
])
def test_a_street_name_is_not_a_unit(line1, line2, unit):
    from services.premises_interest import _unit_designator
    assert _unit_designator({"address_line1": line1, "address_line2": line2}) == unit


def test_an_old_renewal_with_an_unrepeatable_term_is_asked():
    # A 6-month renewal term that ended well over a year ago: its derived
    # effective date would be long past.
    eff, exp = datetime.now() - timedelta(days=800), datetime.now() - timedelta(days=620)
    mf = {"is_renewal": "yes",
          "effective_date": {"value": _mdY(eff), "source": "ai"},
          "expiration_date": {"value": _mdY(exp), "source": "ai"}}
    es._route_renewal_dates(mf, [{"doc_type": "dec_page", "facts": {}}])
    assert "effective_date" not in mf and "expiration_date" not in mf


def test_an_answered_box_prints_as_generation_prints_it():
    """Live run b8d6cb2d: the client's $300,000 printed "300000" on page 2."""
    import services.pdf_service as ps
    assert ps.display_value_for_box("ACORD_125", "CommercialStructure_AnnualRevenueAmount_A",
                                    "300000") == "300,000"
    assert ps.display_value_for_box("ACORD_125", "NamedInsured_TaxIdentifier_A",
                                    "30-0000000") == "30-0000000"
    assert ps.display_value_for_box("ACORD_125", "Policy_ExpirationDate_A",
                                    "08/01/2027") == "08/01/2027"
    assert ps.display_value_for_box("ACORD_125", "X", None) is None


def test_a_status_notice_card_does_not_ask_for_a_document():
    """Live run b8d6cb2d: "No Known Losses attested ..." rendered with "attach a
    supporting document or dismiss it with a note"."""
    from services import answer_routing as ar_
    rec = {"rec_id": "x", "field": None, "informational": True,
           "message": "No Known Losses attested - Loss History is Not Applicable ..."}
    ar_.stamp_recommendation(rec, {})
    assert rec["answer_mode"] == "none"
    assert rec["answer_note"] == ar_.NOTE_INFORMATIONAL
    assert "document" not in rec["answer_note"]
    plain = {"rec_id": "y", "field": None, "message": "something else"}
    ar_.stamp_recommendation(plain, {})
    assert plain["answer_note"] == ar_.NOTE_NO_FIELD             # everything else unchanged
