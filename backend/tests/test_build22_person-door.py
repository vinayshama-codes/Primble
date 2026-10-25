"""Build of 21 Oct 2026, second run, lane P (25sepChanges.md part Z31-P).

ONE DOOR FOR "DID A PERSON SUPPLY THIS VALUE?" - review finding L1 of Z30.

Two doors answered it differently:
  * the term rules (`sqs_service._date_is_person_supplied`, read by the
    expired-term stop and, through `validators._term_typed_by_a_person`, the
    backwards-term stop) read `source in {producer, client_arq, user, human}`
    OR `confidence in {filled, deterministic}`;
  * the display door (`extraction_service.is_silent_boolean`) read
    `fact_state.derive_evidence_state(...) == user_confirmed`.

Now `services/fact_state.py` asks two named questions:
  * `typed_by_person`     - a person ENTERED the value (producer / client);
  * `confirmed_by_person` - typed, or a person picked / confirmed it (Data
                            Consistency, the client's confirm-or-correct).

What this file proves:
  1. the door's answer for EVERY envelope shape the code writes - most built
     by calling the real writer - and for every malformed / never-written
     shape (adversarial cases first);
  2. every routed reader answers exactly as before on every written shape,
     against a FROZEN copy of its old predicate; the only differences are the
     documented ones (the term door's confidence read, and vocabulary no code
     has ever written);
  3. the term stops end to end: hard only on a typed date, a picked or
     confirmed date is the warning, a document's "filled" date is the warning;
  4. anti-rot: every fact source the code writes is classified, every person
     envelope carries a value, no term-date writer leans on a confidence, the
     routed readers carry no vocabulary of their own.
"""
import ast
import copy
import inspect
import os
import pathlib
import sys
from datetime import datetime, timedelta

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("OPENAI_API_KEY", "sk-offline")

from services import fact_state as FS                              # noqa: E402
from services import extraction_service as ES                      # noqa: E402
from services import sqs_service as SQ                             # noqa: E402
from services import coverage_evidence as CE                       # noqa: E402
from services import line_presence as LP                           # noqa: E402
from utils import validators as V                                  # noqa: E402

BACKEND = pathlib.Path(__file__).resolve().parent.parent


# ══ The envelope matrix ══════════════════════════════════════════════════════
# Every shape the code WRITES (most from the real writer), then the malformed
# and never-written ones. `written` = some writer in services / routes / utils
# produces this shape today (anti-rot test 4a ties the matrix to the harvest).

def _answer(source, confidence, text="$1,000,000", key="total_revenue"):
    from services.answer_semantics import build_fact_envelope, interpret_answer
    return build_fact_envelope(key, interpret_answer(key, text), source, confidence)


def _annotated(env, key="total_revenue"):
    facts = {key: copy.deepcopy(env)}
    FS.annotate_fact_states(facts)
    return facts[key]


def _picker(value="01/01/2027"):
    from services.underwriting_consistency import apply_confirmations
    return apply_confirmations({}, {"effective_date": value})["effective_date"]


def _confirm_or_correct(held):
    from services.confirm_known import record_fact_confirmation
    facts = {"applicant_name": dict(held)}
    assert record_fact_confirmation(facts, "applicant_name", held["value"], "arq-1",
                                    "2026-10-21T10:00:00Z")
    return facts["applicant_name"]


def _premises(source):
    from services.premises_cope import derive_package_cope
    facts = {"property_locations": [{"year_built": "2001", "address_line1": "1 Main St"}]}
    derive_package_cope(facts, source=source)
    return facts["year_built"]


def _followed_expiration():
    facts = {
        "prior_effective_date": {"value": "07/15/2024", "source": "ai", "confidence": "ai_high"},
        "prior_expiration_date": {"value": "07/15/2025", "source": "ai", "confidence": "ai_high"},
        "effective_date": {"value": "08/01/2026", "source": "producer", "confidence": "filled"},
    }
    assert ES.follow_proposed_expiration(facts)
    return facts["expiration_date"]


AI = {"value": "Choice Electric LLC", "confidence": "ai_high", "source": "ai"}
DEC_BACKFILL = {"value": "Choice Electric LLC", "confidence": "ai_low", "source": "dec_entry",
                "evidence_state": "source_verified"}

# name: (builder, written, typed, confirmed, writer)
SHAPES = {
    # ── a person ENTERED it ──────────────────────────────────────────────────
    "producer_answer":        (lambda: _answer("producer", "filled"), True, True, True,
                               "arq_service.apply_producer_answer / umbrella_layers"),
    "producer_absence":       (lambda: _answer("producer", "filled", "None"), True, True, True,
                               "arq_service.apply_producer_answer ('None')"),
    "producer_annotated":     (lambda: _annotated(_answer("producer", "filled")), True, True, True,
                               "fact_state.annotate_fact_states over an answer"),
    "producer_form_edit":     (lambda: {"value": "x", "confidence": "filled", "source": "producer"},
                               True, True, True, "form_routes.update_pdf / _annotate_facts(producer)"),
    "producer_codes":         (lambda: {"value": ["91580"], "source": "producer", "confidence": "producer"},
                               True, True, True, "audit_routes GL class codes"),
    "producer_table":         (lambda: _premises("producer"), True, True, True,
                               "premises_cope.derive_package_cope (producer table)"),
    "producer_table_retract": (lambda: {"value": None, "source": "producer", "confidence": "filled",
                                        "value_state": "not_stated",
                                        "derivation": {"rule": "premises_rows", "retracted": True}},
                               True, True, True, "premises_cope.derive_package_cope (retracted)"),
    "client_answer":          (lambda: _answer("client_arq", "client_arq"), True, True, True,
                               "arq_service.apply_arq_answers_to_session"),
    "client_fallback":        (lambda: {"value": "x", "confidence": "client_arq", "source": "client_arq"},
                               True, True, True, "arq_service fallback / extraction_pipeline marketing reason"),
    "client_table":           (lambda: _premises("client_arq"), True, True, True,
                               "premises_cope.derive_package_cope (client table)"),
    # ── a person PICKED / CONFIRMED it ───────────────────────────────────────
    "picker_pick":            (lambda: _picker("01/01/2027"), True, False, True,
                               "underwriting_consistency.apply_confirmations"),
    "picker_typed_value":     (lambda: _picker("02/02/2027"), True, False, True,
                               "underwriting_consistency.apply_confirmations (a typed value)"),
    "confirm_or_correct":     (lambda: _confirm_or_correct(AI), True, False, True,
                               "confirm_known.record_fact_confirmation"),
    "confirm_dec_entry":      (lambda: _confirm_or_correct(DEC_BACKFILL), True, False, True,
                               "confirm_known.record_fact_confirmation (dec entry)"),
    "account_profile":        (lambda: ES._account_producer_envelope("Brent Agency"), True, False, True,
                               "extraction_service._account_producer_envelope"),
    # ── nobody: documents and our own derivations ───────────────────────────
    "ai_high":                (lambda: dict(AI), True, False, False, "extraction merge"),
    "ai_low":                 (lambda: {**AI, "confidence": "ai_low"}, True, False, False, "extraction merge"),
    "ai_annotated":           (lambda: _annotated(AI, "applicant_name"), True, False, False,
                               "annotate_fact_states (suggested)"),
    "ai_text_verified":       (lambda: _annotated({**AI, "verified_in_text": True}, "applicant_name"),
                               True, False, False, "annotate_text_verification"),
    "dec_entry_backfill":     (lambda: dict(DEC_BACKFILL), True, False, False,
                               "extraction_service._backfill_empty_facts_from_entries"),
    "dec_entry_filled":       (lambda: {"value": "yes", "confidence": "filled", "source": "dec_entry"},
                               True, False, False, "is_renewal / payment_method writers"),
    "document_text_filled":   (lambda: {"value": "$1,000,000", "confidence": "filled",
                                        "source": "document_text", "verified_in_text": True},
                               True, False, False, "umbrella underlying / billing_plan writers"),
    "policy_doc_text_filled": (lambda: {"value": "CG 00 01 04 13", "confidence": "filled",
                                        "source": "policy_doc_text"},
                               True, False, False, "extraction_pipeline edition / follow form"),
    "document_amendment":     (lambda: {"value": "x", "source": "document_amendment",
                                        "confidence": "ai_high"},
                               True, False, False, "extraction_service dated change"),
    "line_limit":             (lambda: ES._line_limit_envelope(None, "$1,000,000", "rule"),
                               True, False, False, "extraction_service._line_limit_envelope"),
    "derived_deterministic":  (lambda: {"value": "x", "confidence": "deterministic", "source": "derived"},
                               True, False, False, "extraction_service derivations"),
    "derived_labelled":       (lambda: {"value": "x", "confidence": "deterministic", "source": "derived",
                                        "evidence_state": "derived"},
                               True, False, False, "extraction_service H1 derivations"),
    "derived_new_venture":    (lambda: {"value": "", "confidence": "deterministic", "source": "derived",
                                        "evidence_state": "derived", "value_state": "not_applicable"},
                               True, False, False, "loss_history_state new venture"),
    "derived_stale_label":    (lambda: {"value": "x", "source": "derived", "confidence": "deterministic",
                                        "evidence_state": "suggested"},
                               True, False, False, "extraction_service carrier_naic spread copy"),
    "derived_term":           (_followed_expiration, True, False, False,
                               "extraction_service.follow_proposed_expiration"),
    # ── malformed and never written (adversarial) ───────────────────────────
    "dead_user":              (lambda: {"value": "x", "source": "user"}, False, False, False, "-"),
    "dead_human":             (lambda: {"value": "x", "source": "human"}, False, False, False, "-"),
    "dead_client":            (lambda: {"value": "x", "source": "client"}, False, False, False, "-"),
    "dead_manual":            (lambda: {"value": "x", "source": "manual"}, False, False, False, "-"),
    "confidence_only_client": (lambda: {"value": "x", "source": "ai", "confidence": "client_arq"},
                               False, False, True, "-"),
    "stale_label_person":     (lambda: {"value": "x", "source": "producer", "confidence": "filled",
                                        "evidence_state": "suggested"}, False, True, True, "-"),
    "explicit_label_upper":   (lambda: {"value": "x", "source": "ai", "evidence_state": "USER_CONFIRMED"},
                               False, False, True, "-"),
    "padded_source":          (lambda: {"value": "x", "source": "  Producer ", "confidence": "filled"},
                               False, True, True, "-"),
    "upper_source":           (lambda: {"value": "x", "source": "CLIENT_ARQ"}, False, True, True, "-"),
    "int_source":             (lambda: {"value": "x", "source": 5}, False, False, False, "-"),
    "none_source":            (lambda: {"value": "x", "source": None}, False, False, False, "-"),
    "no_source":              (lambda: {"value": "x"}, False, False, False, "-"),
    "valueless_person":       (lambda: {"source": "producer", "confidence": "filled"}, False, False, False, "-"),
    "valueless_filled":       (lambda: {"confidence": "filled"}, False, False, False, "-"),
    "valueless_picker":       (lambda: {"source": "user_confirmed"}, False, False, False, "-"),
    "empty_dict":             (lambda: {}, False, False, False, "-"),
    "value_none":             (lambda: {"value": None}, False, False, False, "-"),
    "bare_none":              (lambda: None, False, False, False, "-"),
    "bare_text":              (lambda: "07/15/2026", False, False, False, "legacy bare value"),
    "bare_false":             (lambda: False, False, False, False, "legacy bare value"),
    "bare_true":              (lambda: True, False, False, False, "-"),
    "bare_zero":              (lambda: 0, False, False, False, "-"),
    "bare_list":              (lambda: ["x"], False, False, False, "-"),
}
NAMES = sorted(SHAPES)
WRITTEN = sorted(n for n in NAMES if SHAPES[n][1])


def shape(name):
    return SHAPES[name][0]()


def with_value(raw, value):
    """The same envelope holding another value; non-envelopes stay as they are."""
    if isinstance(raw, dict) and "value" in raw:
        out = copy.deepcopy(raw)
        out["value"] = value
        out.pop("answer_text", None)
        out.pop("normalized", None)
        if out.get("value_state") in ("explicit_no", "not_applicable", "not_stated"):
            out["value_state"] = "present"
        return out
    return copy.deepcopy(raw)


# ══ Frozen OLD predicates (the code as it stood before this change) ═════════
# A fixed reference, not a re-implementation of the new code: each is the old
# body verbatim, so "unchanged" is measured against what shipped.

_OLD_TERM_SOURCES = frozenset({"producer", "client_arq", "user", "human"})


def old_term_person(raw):          # sqs_service._date_is_person_supplied
    if isinstance(raw, dict):
        if str(raw.get("source") or "").strip().lower() in _OLD_TERM_SOURCES:
            return True
        if str(raw.get("confidence") or "").strip().lower() in ("filled", "deterministic"):
            return True
    return False


_OLD_EVIDENCE = {"source_verified", "user_confirmed", "derived", "suggested"}
_OLD_HUMAN = {"user_confirmed", "producer", "client_arq"}


def old_evidence_state(raw):       # fact_state.derive_evidence_state (state only)
    env = raw if isinstance(raw, dict) and "value" in raw else {}
    explicit = str(env.get("evidence_state") or "").strip().lower()
    if explicit in _OLD_EVIDENCE:
        return explicit
    source = str(env.get("source") or "").strip().lower()
    confidence = str(env.get("confidence") or "").strip().lower()
    if source in _OLD_HUMAN or confidence == "client_arq":
        return "user_confirmed"
    if source == "derived":
        return "derived"
    if env.get("verified_in_text") is True or source in ("dec_entry", "policy_doc_text") \
            or confidence in ("deterministic", "filled"):
        return "source_verified"
    return "suggested"


def old_user_confirmed(raw):
    return old_evidence_state(raw) == "user_confirmed"


def old_payroll_person(raw):       # coverage_evidence._payroll_source_is_annual (person part)
    env = raw if isinstance(raw, dict) and "value" in raw else {}
    return str(env.get("source") or "").lower() in ("producer", "client_arq", "client")


def old_family_person(raw):        # pdf_service._producer_asserts_family (per fact)
    return isinstance(raw, dict) and \
        str(raw.get("source") or "").strip().lower() in {"producer", "client_arq", "user", "human"}


_OLD_VEHICLE_USE_PERSON = frozenset({"producer", "client", "client_arq", "user", "manual",
                                     "user_confirmed"})


def old_vehicle_use_as_operations(facts):    # normalization.vehicle_use_as_operations
    from services.normalization import description_restates_vehicle_use
    raw = facts.get("operations_description")
    env = raw if isinstance(raw, dict) else {}
    if str(env.get("source") or "").lower() in _OLD_VEHICLE_USE_PERSON \
            or str(env.get("evidence_state") or "").lower() == "user_confirmed":
        return False
    use = facts.get("auto_vehicle_use")
    use = use.get("value") if isinstance(use, dict) else use
    return description_restates_vehicle_use(env.get("value") if env else raw, use)


# Shapes on which a routed reader's answer CHANGES, with why. Anything not
# listed must answer exactly as before.
_LATENT_CONFIDENCE = {   # written, but never on a term date (test 4c)
    "account_profile", "dec_entry_filled", "document_text_filled", "policy_doc_text_filled",
    "derived_deterministic", "derived_labelled", "derived_new_venture", "derived_stale_label",
}
TERM_CHANGES = _LATENT_CONFIDENCE | {"dead_user", "dead_human", "valueless_person", "valueless_filled"}
CONFIRMED_CHANGES = {"stale_label_person"}          # never written: a person's source wins
PAYROLL_CHANGES = {"dead_client", "padded_source"}  # never written
FAMILY_CHANGES = {"dead_user", "dead_human", "valueless_person"}  # never written
VEHICLE_USE_CHANGES = {"dead_user", "dead_client", "dead_manual", "padded_source",
                       "confidence_only_client"}               # never written


def test_every_documented_change_is_a_shape_no_term_date_carries():
    """The only answers that move are on shapes no code writes, or - for the
    term door alone - the dropped confidence read on shapes no code writes on
    a term date (test 4c and the writer inventory in Z31-P)."""
    never = {n for n in NAMES if not SHAPES[n][1]}
    for changes in (CONFIRMED_CHANGES, PAYROLL_CHANGES, FAMILY_CHANGES, VEHICLE_USE_CHANGES,
                    TERM_CHANGES - _LATENT_CONFIDENCE):
        assert changes <= never, changes - never
    assert _LATENT_CONFIDENCE <= set(WRITTEN)


# ══ 1. The door ══════════════════════════════════════════════════════════════

@pytest.mark.parametrize("name", NAMES)
def test_the_door_answers_its_two_questions(name):
    raw = shape(name)
    _b, _w, typed, confirmed, writer = SHAPES[name]
    assert FS.typed_by_person(raw) is typed, (name, writer, raw)
    assert FS.confirmed_by_person(raw) is confirmed, (name, writer, raw)


@pytest.mark.parametrize("name", NAMES)
def test_typed_always_implies_confirmed(name):
    raw = shape(name)
    if FS.typed_by_person(raw):
        assert FS.confirmed_by_person(raw)


@pytest.mark.parametrize("name", NAMES)
def test_confirmed_is_the_evidence_axis_on_every_shape_but_one(name):
    """`confirmed_by_person` == `derive_evidence_state == user_confirmed`; the
    only difference is a person's source beside a stale evidence label, which
    no writer produces (test 4b)."""
    raw = shape(name)
    axis = FS.derive_evidence_state(raw)[0] == FS.USER_CONFIRMED
    if name in CONFIRMED_CHANGES:
        assert FS.confirmed_by_person(raw) and not axis
    else:
        assert FS.confirmed_by_person(raw) is axis, name


@pytest.mark.parametrize("name", NAMES)
def test_derive_evidence_state_is_untouched(name):
    raw = shape(name)
    assert FS.derive_evidence_state(raw)[0] == old_evidence_state(raw), name


def test_the_door_never_reads_a_confidence():
    """A confidence is never provenance: `filled` / `deterministic` are written
    by document readers and derivations as much as by people."""
    for conf in ("filled", "deterministic", "client_arq", "producer", "high", "ai_high"):
        for src in ("ai", "dec_entry", "document_text", "policy_doc_text", "derived", ""):
            assert not FS.typed_by_person({"value": "x", "source": src, "confidence": conf})
    assert "confidence" not in _body(FS.typed_by_person)


def test_the_vocabulary_is_one_table():
    """`_HUMAN_SOURCES` (read by cross_form_validator and coverage_evidence)
    names exactly the door's two source sets, with the same actors."""
    assert set(FS._HUMAN_SOURCES) == FS.PERSON_ENTRY_SOURCES | FS.PERSON_CHOICE_SOURCES
    assert FS.PERSON_ENTRY_SOURCES == {"producer", "client_arq"}
    assert FS.PERSON_CHOICE_SOURCES == {"user_confirmed"}
    assert not FS.PERSON_ENTRY_SOURCES & FS.PERSON_CHOICE_SOURCES
    assert FS._HUMAN_SOURCES == {"user_confirmed": "producer", "producer": "producer",
                                 "client_arq": "client"}


def test_the_picker_stores_a_pick_and_a_typed_value_alike():
    """Why a value TYPED into Data Consistency is not 'typed': the picker
    keeps no marker. Its route sends only the value, `apply_confirmations`
    writes one envelope for any value, so a typed value is a choice like a
    pick (the 21 Oct ruling stands for both)."""
    pick, typed = _picker("01/01/2027"), _picker("02/02/2027")
    assert {k for k in pick if k not in ("value", "normalized")} == \
           {k for k in typed if k not in ("value", "normalized")}
    assert pick["source"] == typed["source"] == "user_confirmed"
    from models.schemas import UnderwritingConfirmRequest as _Req
    fields = getattr(_Req, "model_fields", None) or _Req.__fields__
    assert set(fields) <= {"session_id", "fact_key", "value", "scope", "note"}


# ══ 2. Every routed reader answers as before ═════════════════════════════════

@pytest.mark.parametrize("name", NAMES)
def test_term_door_matches_the_old_one_except_the_confidence_read(name):
    raw = shape(name)
    new = SQ._date_is_person_supplied({"effective_date": raw}, "effective_date")
    assert new is FS.typed_by_person(raw)
    if name in TERM_CHANGES:
        assert old_term_person(raw) and not new, name
    else:
        assert new is old_term_person(raw), name


@pytest.mark.parametrize("name", NAMES)
def test_silent_boolean_matches_the_old_door(name):
    raw = with_value(shape(name), "False")
    key = "cyber_controls_mfa"
    assert key in ES.BOOLEAN_FACT_KEYS and key not in ES.TRISTATE_BOOLEAN_FACTS
    value = raw.get("value") if isinstance(raw, dict) and "value" in raw else raw
    silence = ES.unevidenced_boolean_negative(key, value)
    old = silence and not (isinstance(raw, dict) and old_user_confirmed(raw))
    new = ES.is_silent_boolean(key, raw)
    if name in CONFIRMED_CHANGES:
        assert old and not new
    else:
        assert new is old, name


@pytest.mark.parametrize("name", NAMES)
def test_human_provenance_carries_the_same_facts(name):
    raw = shape(name)
    got = "k" in FS.human_provenance_facts({"k": raw}, include_absence=True)
    old = False
    if isinstance(raw, dict) and "value" in raw:
        v = raw.get("value")
        blank = v is None or (isinstance(v, str) and not v.strip())
        absent = str(raw.get("value_state") or "") in ("explicit_no", "not_applicable")
        old = (not blank or absent) and old_user_confirmed(raw)
    if name in CONFIRMED_CHANGES:
        assert got and not old
    else:
        assert got is old, name


def _routed_term(eff):
    return {
        "prior_effective_date": {"value": "07/15/2024", "source": "ai", "confidence": "ai_high"},
        "prior_expiration_date": {"value": "07/15/2025", "source": "ai", "confidence": "ai_high"},
        "effective_date": eff,
    }


@pytest.mark.parametrize("name", NAMES)
def test_the_expiration_follows_the_same_effective_dates(name):
    raw = with_value(shape(name), "08/01/2026")
    facts = _routed_term(raw)
    new = ES.follow_proposed_expiration(facts)
    dated = isinstance(raw, dict) and "value" in raw
    old = dated and old_evidence_state(raw) in ("user_confirmed", "derived")
    if raw == "07/15/2026":                 # a bare date: no provenance, never followed
        old = False
    if name in CONFIRMED_CHANGES:
        assert new and not old
    else:
        assert new is old, name


@pytest.mark.parametrize("name", NAMES)
def test_human_set_and_line_presence_match(name):
    raw = shape(name)
    old = isinstance(raw, dict) and old_user_confirmed(raw)
    for got in (CE._human_set({"k": raw}, "k"), LP._is_a_persons(raw)):
        if name in CONFIRMED_CHANGES:
            assert got and not old
        else:
            assert got is old, name


@pytest.mark.parametrize("name", NAMES)
def test_a_client_answer_is_held_against_the_same_values(name, monkeypatch):
    from services import arq_service as ARQ
    monkeypatch.setattr(ARQ, "ENABLE_CLIENT_ANSWER_CONFLICT_ROUTING", True)
    raw = with_value(shape(name), "$1,000,000")
    got = ARQ._client_answer_conflicts_with_source("total_revenue", raw, "$1,000,000", "$5,000,000")
    old = not old_user_confirmed(raw)       # not a person's -> the comparison holds it
    if name in CONFIRMED_CHANGES:
        assert old and not got
    else:
        assert got is old, name


def test_the_hold_control_really_compares(monkeypatch):
    from services import arq_service as ARQ
    monkeypatch.setattr(ARQ, "ENABLE_CLIENT_ANSWER_CONFLICT_ROUTING", True)
    assert ARQ._client_answer_conflicts_with_source("total_revenue", dict(AI), "$1,000,000",
                                                    "$5,000,000") is True
    assert ARQ._client_answer_conflicts_with_source("total_revenue", dict(AI), "$1,000,000",
                                                    "$1,000,000") is False


@pytest.mark.parametrize("name", NAMES)
def test_a_typed_payroll_is_annual_as_before(name):
    raw = with_value(shape(name), "$500,000")
    if isinstance(raw, dict):
        raw.pop("period_basis", None)
    got = CE._payroll_source_is_annual({"wc_payroll": raw})
    if name in PAYROLL_CHANGES:
        assert got is not old_payroll_person(raw)
    else:
        assert got is old_payroll_person(raw), name


@pytest.mark.parametrize("name", NAMES)
def test_the_vehicle_use_ruling_spares_the_same_descriptions(name):
    from services.normalization import vehicle_use_as_operations
    facts = {"operations_description": with_value(shape(name), "LOCAL SERVICE"),
             "auto_vehicle_use": {"value": "service", "source": "ai"}}
    got = vehicle_use_as_operations(facts)
    old = old_vehicle_use_as_operations(facts)
    if name in VEHICLE_USE_CHANGES:
        assert got is not old, name
    else:
        assert got is old, name


@pytest.mark.parametrize("name", NAMES)
def test_a_person_still_holds_a_coverage_family(name):
    from services import pdf_service as PS
    raw = shape(name)
    got = PS._producer_asserts_family({"advertisers_media": raw}, ("advertisers_",))
    if name in FAMILY_CHANGES:
        assert old_family_person(raw) and not got
    else:
        assert got is old_family_person(raw), name


# ══ 3. The term stops, end to end ════════════════════════════════════════════

PAST = (datetime.now() - timedelta(days=120)).strftime("%m/%d/%Y")


@pytest.mark.parametrize("name", WRITTEN)
def test_the_expired_term_is_hard_only_on_a_typed_expiration(name):
    raw = with_value(shape(name), PAST)
    sev, _msg = SQ.validate_policy_term_not_expired({"expiration_date": raw})
    assert sev == ("hard" if FS.typed_by_person(raw) else "soft"), name
    old = "hard" if old_term_person(raw) else "soft"
    if name in TERM_CHANGES:
        assert (old, sev) == ("hard", "soft")
    else:
        assert sev == old, name
    # renewal wording keeps every shape a warning, as before
    sev_r, _ = SQ.validate_policy_term_not_expired({"expiration_date": raw, "is_renewal": "yes"})
    assert sev_r == "soft"


def _backwards(eff_name, exp_name):
    facts = {"effective_date": with_value(shape(eff_name), "07/15/2026"),
             "expiration_date": with_value(shape(exp_name), "07/15/2025")}
    return V.run_field_validations(facts)


@pytest.mark.parametrize("eff,exp,hard", [
    ("producer_answer", "producer_answer", True),
    ("client_answer", "producer_form_edit", True),
    ("producer_form_edit", "client_fallback", True),
    ("producer_answer", "picker_pick", False),       # a picked date is not typed
    ("picker_pick", "picker_typed_value", False),    # picked or typed into the picker
    ("confirm_or_correct", "producer_answer", False),
    ("producer_answer", "ai_high", False),
    ("dec_entry_filled", "document_text_filled", False),   # the dropped confidence read
    ("derived_deterministic", "derived_deterministic", False),
    ("derived_term", "producer_answer", False),
])
def test_the_backwards_term_is_hard_only_when_both_dates_were_typed(eff, exp, hard):
    h, s = _backwards(eff, exp)
    backwards_hard = [m for m in h if "Expiration date" in m or "expiration" in m.lower()]
    assert bool(backwards_hard) is hard, (eff, exp, h)
    assert (V.BACKWARDS_TERM_TO_CONFIRM in s) is (not hard), (eff, exp, s)


def test_the_term_doors_ask_the_one_door():
    both = {"effective_date": shape("producer_answer"), "expiration_date": shape("client_answer")}
    one = {"effective_date": shape("producer_answer"), "expiration_date": shape("picker_pick")}
    none = {"effective_date": shape("dec_entry_filled"), "expiration_date": shape("account_profile")}
    assert SQ._term_dates_both_person_supplied(both) and V._term_typed_by_a_person(both)
    assert not SQ._term_dates_both_person_supplied(one) and not V._term_typed_by_a_person(one)
    assert SQ._dates_are_producer_asserted(one)
    assert not SQ._dates_are_producer_asserted(none)
    for facts in ({}, None, {"effective_date": None}, {"expiration_date": "07/15/2026"}):
        assert not SQ._term_dates_both_person_supplied(facts or {})
        assert not SQ._dates_are_producer_asserted(facts or {})


# ══ 4. Anti-rot ══════════════════════════════════════════════════════════════

_NOT_A_PERSON = frozenset({"ai", "dec_entry", "document_text", "policy_doc_text",
                           "document_amendment", "derived", "account"})


def _module_consts(tree):
    out = {}
    for n in tree.body:
        if isinstance(n, ast.Assign) and isinstance(n.value, ast.Constant) \
                and isinstance(n.value.value, str):
            for t in n.targets:
                if isinstance(t, ast.Name):
                    out[t.id] = n.value.value
    return out


def _strings(node, consts):
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return [node.value]
    if isinstance(node, ast.Name) and node.id in consts:
        return [consts[node.id]]
    if isinstance(node, (ast.BoolOp, ast.IfExp)):
        parts = node.values if isinstance(node, ast.BoolOp) else [node.body, node.orelse]
        return [s for p in parts for s in (_strings(p, consts) or [])] or None
    return None


def _harvest():
    """{source: [where]} for every fact envelope literal ({"value", "source"})
    and every `build_fact_envelope` call, plus person-source dicts without a
    value."""
    sources, builder, valueless = {}, {}, []
    person = FS.PERSON_ENTRY_SOURCES | FS.PERSON_CHOICE_SOURCES
    for sub in ("services", "routes", "utils", "models"):
        for p in sorted((BACKEND / sub).rglob("*.py")):
            tree = ast.parse(p.read_text(encoding="utf-8"))
            consts = _module_consts(tree)
            for node in ast.walk(tree):
                if isinstance(node, ast.Dict):
                    keys = {k.value: v for k, v in zip(node.keys, node.values)
                            if isinstance(k, ast.Constant)}
                    if "source" not in keys:
                        continue
                    found = _strings(keys["source"], consts) or []
                    where = f"{p.relative_to(BACKEND)}:{node.lineno}"
                    if "value" in keys:
                        for s in found:
                            sources.setdefault(s, []).append(where)
                    elif set(found) & person:
                        valueless.append((where, frozenset(k for k in keys if isinstance(k, str))))
                elif isinstance(node, ast.Call):
                    fn = node.func.attr if isinstance(node.func, ast.Attribute) \
                        else getattr(node.func, "id", "")
                    if fn == "build_fact_envelope" and len(node.args) >= 3:
                        for s in _strings(node.args[2], consts) or ["<dynamic>"]:
                            builder.setdefault(s, []).append(f"{p.relative_to(BACKEND)}:{node.lineno}")
    return sources, builder, valueless


def test_every_fact_source_the_code_writes_is_classified():
    """A new source literal must be decided in the door (a person's entry, a
    person's choice, or neither) - otherwise a new way for a person to supply
    a value would silently read as a document's."""
    sources, builder, _ = _harvest()
    known = FS.PERSON_ENTRY_SOURCES | FS.PERSON_CHOICE_SOURCES | _NOT_A_PERSON
    unknown = {s: w[:3] for s, w in sources.items() if s not in known}
    assert not unknown, f"classify these fact sources in fact_state: {unknown}"
    assert set(builder) <= FS.PERSON_ENTRY_SOURCES, builder
    assert FS.PERSON_ENTRY_SOURCES <= set(sources) | set(builder)
    assert FS.PERSON_CHOICE_SOURCES <= set(sources)


def test_the_matrix_covers_every_written_source():
    sources, _b, _v = _harvest()
    covered = set()
    for name in WRITTEN:
        raw = shape(name)
        if isinstance(raw, dict):
            covered.add(str(raw.get("source") or "").strip().lower())
    assert set(sources) <= covered, set(sources) - covered


def test_every_person_envelope_carries_a_value():
    """Why the door can require an envelope: no code writes a person's source
    on a FACT without a value. The one person-source dict with no value is the
    `_human_schedules` table mark (`{"source", "fingerprint"}`, a private
    record that a person saved a table) - not a fact, and the door is never
    asked about it (it answers False: not an envelope)."""
    _s, _b, valueless = _harvest()
    envelopes = [(w, k) for w, k in valueless if not ("fingerprint" in k and "confidence" not in k)]
    assert envelopes == []
    for where, keys in valueless:
        assert keys == {"source", "fingerprint"}, where
    assert not FS.typed_by_person({"source": "producer", "fingerprint": "abc"})
    assert not FS.confirmed_by_person({"source": "producer", "fingerprint": "abc"})


def test_no_term_date_writer_leans_on_a_confidence():
    """The dropped read was latent: every literal write of a proposed-term date
    is a person's, or carries a confidence the old door never counted."""
    offenders = []
    for sub in ("services", "routes", "utils"):
        for p in sorted((BACKEND / sub).rglob("*.py")):
            tree = ast.parse(p.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if not (isinstance(node, ast.Assign) and isinstance(node.value, ast.Dict)):
                    continue
                for t in node.targets:
                    if isinstance(t, ast.Subscript) and isinstance(t.slice, ast.Constant) \
                            and t.slice.value in ("effective_date", "expiration_date"):
                        keys = {k.value: v for k, v in zip(node.value.keys, node.value.values)
                                if isinstance(k, ast.Constant)}
                        conf = keys.get("confidence")
                        src = keys.get("source")
                        c = conf.value if isinstance(conf, ast.Constant) else None
                        s = src.value if isinstance(src, ast.Constant) else None
                        if c in ("filled", "deterministic") and s not in FS.PERSON_ENTRY_SOURCES:
                            offenders.append(f"{p.relative_to(BACKEND)}:{node.lineno}")
    assert offenders == []


def _body(fn):
    """A module-level function's code without its docstring, read from the
    module file AS IT IS NOW and found by name. Not `inspect.getsource`: it
    maps the import-time line numbers onto the current file, so an edit to
    the file after import (another lane's, during a parallel build) returns
    a neighbouring function."""
    path = pathlib.Path(inspect.getsourcefile(fn))
    tree = ast.parse(path.read_text(encoding="utf-8"))
    node = next(n for n in tree.body
                if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == fn.__name__)
    if node.body and isinstance(node.body[0], ast.Expr) \
            and isinstance(getattr(node.body[0], "value", None), ast.Constant):
        node.body = node.body[1:]
    return ast.unparse(node)


def _routed():
    from services import arq_service as ARQ
    from services import pdf_service as PS
    from services import normalization as N
    return {
        "typed_by_person": [SQ._date_is_person_supplied, CE._payroll_source_is_annual,
                            PS._producer_asserts_family],
        "confirmed_by_person": [ES.is_silent_boolean, FS.human_provenance_facts,
                                ES.follow_proposed_expiration, CE._human_set, LP._is_a_persons,
                                ARQ._client_answer_conflicts_with_source,
                                N.vehicle_use_as_operations],
    }


@pytest.mark.parametrize("door", ["typed_by_person", "confirmed_by_person"])
def test_every_routed_reader_asks_the_door(door):
    for fn in _routed()[door]:
        body = _body(fn)
        assert door in body, fn.__name__
        assert "_PERSON_DATE_SOURCES" not in body and "_PRODUCER_FACT_SOURCES" not in body


def test_no_routed_person_check_keeps_a_vocabulary_of_its_own():
    from services.normalization import vehicle_use_as_operations
    for fn in (SQ._date_is_person_supplied, CE._human_set, LP._is_a_persons,
               ES.is_silent_boolean, ES.follow_proposed_expiration, vehicle_use_as_operations):
        body = _body(fn)
        for word in ('"producer"', '"client_arq"', '"user_confirmed"', '"human"', '"user"',
                     "'producer'", "'client_arq'", "USER_CONFIRMED"):
            assert word not in body, (fn.__name__, word)
    payroll = _body(CE._payroll_source_is_annual)
    assert '"producer"' not in payroll and "'producer'" not in payroll
    family = _body(_routed()["typed_by_person"][2])
    assert '"producer"' not in family and "'producer'" not in family


def test_the_old_private_vocabularies_are_gone():
    from services import pdf_service as PS
    from services import normalization as N
    assert not hasattr(SQ, "_PERSON_DATE_SOURCES")
    assert not hasattr(PS, "_PRODUCER_FACT_SOURCES")
    assert not hasattr(N, "_PERSON_FACT_SOURCES")
