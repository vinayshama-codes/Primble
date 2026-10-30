"""Build of 21 Oct 2026, lane B, item b-small-rules (25sepChanges.md part Z30).

Three small fixes, each with its own section:

  1. Brent 17 Oct item 3 - the narrative's "Review data" popup printed cyber
     controls / agreed value = False. Those facts are bare `boolean` in the
     extraction schema, so a False from a document that never mentions them is
     SILENCE (defect B8). One door: `extraction_service.is_silent_boolean`, the
     display form of `unevidenced_boolean_negative`.
  2. Brent 20 Oct rule 3 - the monopolistic-WC check read three inputs nothing
     writes (`wc_carrier_type`, `wc_private_carrier_requested`,
     `wc_requested_private_carrier`).
  3. Brent 20 Oct rule 1 + "only hard stop when verified" - a backwards proposed
     term is a hard stop only when a person typed one of the two dates.
"""
import asyncio
import os
import pathlib
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("OPENAI_API_KEY", "sk-offline")

from routes.form_routes import _document_fact_rows                 # noqa: E402
from services import audit_service as AS                          # noqa: E402
from services import fact_lineage as FL                            # noqa: E402
from services import extraction_service as ES                      # noqa: E402
from services.extraction_service import (                          # noqa: E402
    BOOLEAN_FACT_KEYS, TRISTATE_BOOLEAN_FACTS, is_silent_boolean,
)

BACKEND = pathlib.Path(__file__).resolve().parent.parent


def _env(value, source="ai", **extra):
    """A fact as extraction (or a person's answer) stores it."""
    conf = "filled" if source in ("producer", "client_arq", "user_confirmed") else "ai_high"
    return {"value": value, "source": source, "confidence": conf, **extra}


TWO_WAY = sorted(BOOLEAN_FACT_KEYS - TRISTATE_BOOLEAN_FACTS)


# ══ 1. Silent two-way booleans never print as answers ═══════════════════════

# Brent's 17 Oct narrative, as extraction stores a handwritten note's facts:
# envelopes with the STRING "False" (`_annotate_facts`) and the value_state
# fact_state's string path writes for the word "false".
NARRATIVE_FACTS = {
    "applicant_name":           _env("Berger Owner of Choice Electric"),
    "operations_description":   _env("Electrical contractor, commercial work"),
    "total_revenue":            _env("$3,200,000"),
    "cyber_controls_mfa":       _env("False", value_state="explicit_no"),
    "cyber_controls_backups":   _env("False", value_state="explicit_no"),
    "agreed_value_endorsement": _env("False", value_state="explicit_no"),
}


def test_the_reported_rows_are_gone_and_the_rest_stay():
    rows = {r["key"]: r["value"] for r in _document_fact_rows(NARRATIVE_FACTS)}
    for key in ("cyber_controls_mfa", "cyber_controls_backups",
                "agreed_value_endorsement"):
        assert key not in rows, f"{key} = False printed as an answer"
    assert rows == {
        "applicant_name":         "Berger Owner of Choice Electric",
        "operations_description": "Electrical contractor, commercial work",
        "total_revenue":          "$3,200,000",
    }


def test_the_harvest_is_not_vacuous():
    """The schema still declares the reported facts as two-way booleans - a
    parametrised test over an empty set would pass over a broken door."""
    assert len(TWO_WAY) >= 40
    for key in ("cyber_controls_mfa", "cyber_controls_backups",
                "agreed_value_endorsement"):
        assert key in TWO_WAY


@pytest.mark.parametrize("key", TWO_WAY)
@pytest.mark.parametrize("value", ["False", "false", "FALSE", "No", "N", False])
def test_every_two_way_false_the_schema_declares_is_hidden(key, value):
    """Harvested from the schema, so a two-way boolean added next month is
    covered without anyone remembering this file. Every spelling the model
    emits for a false (string, bool, Y/N word)."""
    assert _document_fact_rows({key: _env(value)}) == []
    assert _document_fact_rows({key: value}) == []           # bare, not wrapped


@pytest.mark.parametrize("key", TWO_WAY)
def test_a_two_way_true_still_prints(key):
    rows = _document_fact_rows({key: _env("True")})
    assert [(r["key"], r["value"]) for r in rows] == [(key, "Yes")]       # a boolean reads Yes (25 Oct)


@pytest.mark.parametrize("key", sorted(TRISTATE_BOOLEAN_FACTS))
def test_a_tristate_false_is_a_real_no_and_still_prints(key):
    """`boolean or null`: the model is told to answer null when the document
    is silent, so its False IS the document saying No."""
    assert TRISTATE_BOOLEAN_FACTS, "the tri-state set vanished"
    rows = _document_fact_rows({key: _env("False")})
    assert [(r["key"], r["value"]) for r in rows] == [(key, "No")]        # a boolean reads No (25 Oct)


@pytest.mark.parametrize("key", ["auto_hired_nonowned", "is_renewal",
                                 "umbrella_follow_form", "operations_description"])
def test_a_string_typed_no_still_prints(key):
    """A `string or null` fact holding "No" is an answer - the model could
    have left it null."""
    assert key not in BOOLEAN_FACT_KEYS
    rows = _document_fact_rows({key: _env("No")})
    assert [(r["key"], r["value"]) for r in rows] == [(key, "No")]


@pytest.mark.parametrize("source", ["producer", "client_arq", "user_confirmed"])
def test_a_persons_no_is_an_answer(source):
    """Who supplied it decides (`fact_state.derive_evidence_state`). A
    producer's / client's / Data Consistency "No" keeps printing."""
    raw = _env("No", source=source)
    assert not is_silent_boolean("agreed_value_endorsement", raw)
    rows = _document_fact_rows({"agreed_value_endorsement": raw})
    assert [r["value"] for r in rows] == ["No"]
    # An explicit evidence label written by the answering code counts too.
    raw2 = {"value": "False", "source": "ai", "evidence_state": "user_confirmed"}
    assert not is_silent_boolean("cyber_controls_mfa", raw2)


@pytest.mark.parametrize("raw", [None, {}, {"value": None}, {"value": ""},
                                 {"value": {"x": "False"}}, {"value": ["True", "False"]},
                                 "", [], {"confidence": "ai_high"}])
def test_empty_missing_and_malformed_values_are_unchanged(raw):
    """Nothing the door cannot read as a No is hidden by it - the old
    behaviour (blank rows dropped, structured values flattened) stands."""
    assert not is_silent_boolean("cyber_controls_mfa", raw)


@pytest.mark.parametrize("value", [["False"], "[False]", "(No)", "False.", " no "])
def test_odd_spellings_follow_the_door_not_a_local_opinion(value):
    """Whatever the comparison door reads as a No, the display hides - and
    nothing else. A one-element list or a bracketed / punctuated False is the
    door's call (it reads them as N)."""
    door = ES.unevidenced_boolean_negative("cyber_controls_mfa", value)
    assert is_silent_boolean("cyber_controls_mfa", {"value": value}) is door


def test_empty_inputs_are_not_an_error():
    assert _document_fact_rows(None) == []
    assert _document_fact_rows({}) == []
    assert not is_silent_boolean("", "False")
    assert not is_silent_boolean(None, "False")


def test_one_door_the_display_rule_is_the_comparison_rule(monkeypatch):
    """No second rule: the display form asks `unevidenced_boolean_negative`
    and nothing else. Flip the door and the popup follows it."""
    facts = {"cyber_controls_mfa": _env("False")}
    monkeypatch.setattr(ES, "unevidenced_boolean_negative", lambda k, v: False)
    assert [r["key"] for r in _document_fact_rows(facts)] == ["cyber_controls_mfa"]
    monkeypatch.setattr(ES, "unevidenced_boolean_negative", lambda k, v: True)
    assert _document_fact_rows({"total_revenue": _env("$1")}) == []


def test_the_popup_endpoint_still_builds_rows_through_the_helper():
    src = (BACKEND / "routes" / "form_routes.py").read_text(encoding="utf-8")
    start = src.index("def _document_fact_rows")
    body = src[start:src.index("\ndef ", start + 10)]
    assert "is_silent_boolean" in body, "the popup no longer asks the door"


def test_the_audit_export_loop_asks_the_same_door():
    src = (BACKEND / "services" / "audit_service.py").read_text(encoding="utf-8")
    start = src.index("async def get_audit_trail_export")
    body = src[start:src.index("\nasync def ", start + 10)
               if "\nasync def " in src[start + 10:] else None]
    assert "is_silent_boolean(key, raw)" in body


# ── the E&O record (audit export) and its lineage ──────────────────────────

def _doc(doc_id, filename, text, facts):
    return {"doc_id": doc_id, "filename": filename, "text": text, "facts": facts}


DOC_TEXT = ("[Document page 1]\nCHOICE ELECTRIC LLC\nThe statement is not false.\n"
            "MFA required on all systems: true\n")


def test_lineage_never_cites_silence_for_a_no():
    """Each document's own False is silence; the text path would find the
    word "false" in ordinary prose. No citation either way."""
    idx = FL.build_doc_index([
        _doc("d1", "Narrative.jpg", DOC_TEXT, {"cyber_controls_mfa": _env("False")}),
        _doc("d2", "COI.pdf", DOC_TEXT, {"cyber_controls_mfa": _env("False")}),
    ])
    assert FL.sources_for_fact("cyber_controls_mfa", _env("False"), idx) == []
    assert FL.sources_for_fact("cyber_controls_mfa", _env("No", "producer"), idx) == []
    # A True is still attributed to the document whose own extraction says so.
    idx2 = FL.build_doc_index([
        _doc("d1", "Cyber app.pdf", DOC_TEXT, {"cyber_controls_mfa": _env("True")}),
        _doc("d2", "COI.pdf", "[Document page 1]\nnothing here\n",
             {"cyber_controls_mfa": _env("False")}),
    ])
    srcs = FL.sources_for_fact("cyber_controls_mfa", _env("True"), idx2)
    assert [s["filename"] for s in srcs if s["method"] == "extracted"] == ["Cyber app.pdf"]
    # A non-boolean fact is untouched.
    idx3 = FL.build_doc_index([_doc("d1", "Dec.pdf", "[Document page 1]\nCHOICE ELECTRIC LLC\n",
                                    {"applicant_name": _env("CHOICE ELECTRIC LLC")})])
    assert FL.sources_for_fact("applicant_name", _env("CHOICE ELECTRIC LLC"), idx3)


def _patch_async(monkeypatch, module, name, value):
    async def _f(*a, **k):
        return value
    monkeypatch.setattr(module, name, _f, raising=False)


def test_the_eo_record_lists_no_silent_no(monkeypatch):
    session = {
        "user_id": "u1",
        "created_at": "2026-10-17T18:00:00+00:00",
        "docs": [
            _doc("d1", "Narrative.jpg", DOC_TEXT, {
                "cyber_controls_mfa": _env("False"),
                "cyber_controls_backups": _env("True"),
                "agreed_value_endorsement": _env("False"),
            }),
            _doc("d2", "Package Dec.pdf", "[Document page 1]\nPACKAGE\n", {
                "cyber_controls_mfa": _env("False"),
                "agreed_value_endorsement": _env("False"),
            }),
        ],
        "facts": {
            # every document silent: the merge keeps the False (by design)
            "cyber_controls_mfa":       _env("False"),
            # a document answered
            "cyber_controls_backups":   _env("True"),
            # a person's answer
            "agreed_value_endorsement": _env("No", source="producer"),
            "applicant_name":           _env("CHOICE ELECTRIC LLC"),
        },
        "generated_forms": {},
    }
    import repositories.session_repository as SR
    import services.arq_receipt_service as RS
    _patch_async(monkeypatch, SR, "get_processing_session", session)
    _patch_async(monkeypatch, RS, "get_receipts_for_session", [])
    for name, val in [
        ("get_marketing_reason", None), ("get_dismissed_recommendations", []),
        ("get_producer_answers", []), ("get_issue_statuses", []),
        ("get_download_audit_log", []), ("get_field_change_log", []),
        ("get_underwriting_confirmations", []),
        ("get_package_download_log", []), ("get_audit_events", []),
        ("get_integrity_audit_log", []),
    ]:
        _patch_async(monkeypatch, AS, name, val)

    export = asyncio.run(AS.get_audit_trail_export("s1"))
    by_key = {r["fact"]: r for r in export["inputs"]}

    assert "cyber_controls_mfa" not in by_key, "a silent False is listed as a captured No"
    assert by_key["cyber_controls_backups"]["value"] == "True"
    assert [s["filename"] for s in by_key["cyber_controls_backups"]["sources"]
            if s["method"] == "extracted"] == ["Narrative.jpg"]
    person = by_key["agreed_value_endorsement"]
    assert person["value"] == "No" and person["source"] == "producer"
    assert person["sources"] == [], "a person's No was attributed to a silent document"
    assert by_key["applicant_name"]["value"] == "CHOICE ELECTRIC LLC"


# ══ 2. The monopolistic-WC check reads only what something writes ═══════════

# Read by `sqs_service.evaluate_stops` until 21 Oct 2026 and written by NOTHING:
# no extraction schema key, no FACT_REGISTRY entry, no stamper / alias map, no
# route, no questionnaire, no frontend. The same class as the five phantom auto
# symbol keys (test_auto_symbols.test_no_check_reads_a_fact_nothing_writes).
_MONOPOLISTIC_PHANTOMS = ("wc_carrier_type", "wc_private_carrier_requested",
                          "wc_requested_private_carrier")
# The FACT `wc_state_fund_acknowledged` is the person's placement answer (the
# rule's one real input). Its FLAG form was a fourth dead read.
_DEAD_FLAG_READ = __import__("re").compile(
    r"""flags\s*(?:\.get\(|\[)\s*["']wc_state_fund_acknowledged["']""")

_FRONTEND = BACKEND.parent / "frontend" / "src"


def _production_sources():
    """Every file production code (and its data) is made of: backend Python
    outside the tests and the venv, the alias maps, the frontend sources."""
    out = []
    for path in BACKEND.rglob("*.py"):
        rel = path.relative_to(BACKEND).parts
        if rel[0] in ("tests", ".venv", "venv", "node_modules") or "site-packages" in rel:
            continue
        out.append(path)
    out.extend((BACKEND / "forms_aliases").glob("*.json"))
    if _FRONTEND.is_dir():
        out.extend(p for p in _FRONTEND.rglob("*") if p.suffix in (".js", ".jsx", ".ts", ".tsx"))
    return out


def test_the_scan_is_not_vacuous():
    srcs = _production_sources()
    assert len(srcs) > 150, f"only {len(srcs)} production files scanned"
    hits = [p.name for p in srcs
            if '"wc_state_fund_acknowledged"' in p.read_text(encoding="utf-8", errors="ignore")]
    # the real input IS found where it lives - the scanner can see a key
    assert {"sqs_service.py", "fact_registry.py", "answer_options.py"} <= set(hits)


@pytest.mark.parametrize("key", _MONOPOLISTIC_PHANTOMS)
def test_no_code_reads_or_writes_a_monopolistic_phantom(key):
    """A quoted reference anywhere in production means the dead input is back -
    or that something now writes it, in which case this test is where to decide
    whether the rule should read it."""
    offenders = []
    for path in _production_sources():
        src = path.read_text(encoding="utf-8", errors="ignore")
        if f'"{key}"' in src or f"'{key}'" in src:
            offenders.append(str(path.relative_to(BACKEND.parent)))
    assert not offenders, f"{key!r} is referenced again in {offenders}"


def test_the_state_fund_answer_is_never_read_as_a_flag():
    offenders = [str(p.relative_to(BACKEND.parent)) for p in _production_sources()
                 if p.suffix == ".py"
                 and _DEAD_FLAG_READ.search(p.read_text(encoding="utf-8", errors="ignore"))]
    assert not offenders, f"the dead flag read is back in {offenders}"


def test_the_extraction_schema_never_asked_for_them():
    from services.extraction_service import _EXTRACT_SCHEMA
    from services.fact_registry import FACT_REGISTRY
    for key in _MONOPOLISTIC_PHANTOMS + ("wc_state_fund_acknowledged",):
        assert key not in _EXTRACT_SCHEMA, f"{key} is asked of the model"
    for key in _MONOPOLISTIC_PHANTOMS:
        assert key not in FACT_REGISTRY, f"{key} became a registry fact"


_WC_MONO_FLAGS = {"has_workers_comp": True, "wc_has_monopolistic_state": True}
_HARD_MONO = "Monopolistic WC state (ND/OH/WA/WY) requires the state fund"
_SOFT_MONO = "Monopolistic WC state detected (ND/OH/WA/WY) - must use state fund"


def _mono_stops(facts, flags=None):
    from services.sqs_service import evaluate_stops
    hard, soft = evaluate_stops(dict(facts),
                                dict(_WC_MONO_FLAGS if flags is None else flags))
    return ([m for m in hard if "Monopolistic" in m],
            [m for m in soft if "Monopolistic" in m and "wc_monopolistic_payroll" not in m])


def test_the_persons_answer_still_decides_both_ways():
    from services.answer_options import WC_STATE_FUND_OPTIONS
    yes, no = WC_STATE_FUND_OPTIONS[0], WC_STATE_FUND_OPTIONS[1]
    assert yes.startswith("Yes") and no.startswith("No")
    hard, soft = _mono_stops({})
    assert hard == [] and soft == [_SOFT_MONO]                 # not answered: a warning
    hard, soft = _mono_stops({"wc_state_fund_acknowledged": _env(no, "producer")})
    assert len(hard) == 1 and hard[0].startswith(_HARD_MONO)   # verified private: hard
    assert soft == []
    hard, soft = _mono_stops({"wc_state_fund_acknowledged": _env(yes, "producer")})
    assert hard == [] and soft == []                           # acknowledged: nothing


def test_the_dead_inputs_are_inert():
    """Set every removed input both ways: the outcome is exactly the one the
    real input alone gives. Proves the reads are gone, not just renamed."""
    phantom_facts = {"wc_carrier_type": _env("private")}
    phantom_flags = dict(_WC_MONO_FLAGS, wc_private_carrier_requested=True,
                         wc_requested_private_carrier=True,
                         wc_state_fund_acknowledged=True)
    assert _mono_stops(phantom_facts, phantom_flags) == _mono_stops({})
    no = "No - private-carrier coverage is being requested for those states"
    real = {"wc_state_fund_acknowledged": _env(no, "producer")}
    assert _mono_stops(dict(real, **phantom_facts), phantom_flags) == _mono_stops(real)


def test_no_monopolistic_state_no_message():
    for flags in ({"has_workers_comp": True}, {"wc_has_monopolistic_state": True}, {}):
        hard, soft = _mono_stops({"wc_state_fund_acknowledged": _env("No", "producer")}, flags)
        assert hard == [] and soft == []


# ══ 3. A backwards term is a hard stop only when a person supplied a date ═══

from utils.validators import (                                     # noqa: E402
    BACKWARDS_TERM_TO_CONFIRM, run_field_validations, validate_date_range,
)

_HARD_BACKWARDS = "Effective date is on or after expiration date - policy period is invalid"
_EFF, _EXP = "07/15/2027", "07/15/2026"          # runs backwards by a year


def _typed(value, source="producer"):
    return {"value": value, "source": source,
            "confidence": "filled" if source == "producer" else "client_arq"}


def _range_stops(eff, exp):
    hard, soft = run_field_validations({"effective_date": eff, "expiration_date": exp})
    return ([m for m in hard if "expiration date" in m],
            [m for m in soft if "expiration date" in m and "could not be parsed" not in m])


# Every way a date reaches the facts WITHOUT a person typing it.
_NOT_TYPED = {
    "bare (legacy shape)":      lambda v: v,
    "AI extraction":            lambda v: {"value": v, "source": "ai", "confidence": "ai_high"},
    "AI, low OCR confidence":   lambda v: {"value": v, "source": "ai", "confidence": "ai_low"},
    "dec-entry backfill":       lambda v: {"value": v, "source": "dec_entry", "confidence": "ai_low",
                                           "evidence_state": "source_verified"},
    "calculated next term":     lambda v: {"value": v, "source": "derived",
                                           "confidence": "low_confidence",
                                           "derivation": {"rule": "next_term_after_current_policy"}},
    "picked in Data Consistency": lambda v: {"value": v, "source": "user_confirmed",
                                             "confidence": "client_arq"},
}
# Every way a PERSON types a date.
_TYPED_BY = {
    "fix window / card / form edit": lambda v: _typed(v, "producer"),
    "client questionnaire":          lambda v: {"value": v, "source": "client_arq",
                                                "confidence": "client_arq"},
}


@pytest.mark.parametrize("how", sorted(_NOT_TYPED))
def test_dates_nobody_typed_are_a_warning_to_confirm(how):
    """Adversarial first: the over-reach would be a document's slip holding the
    whole package at 60 with no person having said anything."""
    wrap = _NOT_TYPED[how]
    hard, soft = _range_stops(wrap(_EFF), wrap(_EXP))
    assert hard == [], f"{how}: a backwards term nobody typed is still a hard stop"
    assert soft == [BACKWARDS_TERM_TO_CONFIRM]


@pytest.mark.parametrize("how", sorted(_TYPED_BY))
def test_both_dates_typed_backwards_is_hard_with_the_same_sentence(how):
    """(c) BOTH dates supplied by a person = verified (21 Oct 2026 review, M2).
    The hard sentence is byte-identical to the old one, so its issue id is too."""
    typed = _TYPED_BY[how]
    hard, soft = _range_stops(typed(_EFF), typed(_EXP))
    assert hard == [_HARD_BACKWARDS] and soft == []
    assert validate_date_range(_EFF, _EXP) == (False, _HARD_BACKWARDS)
    # a producer on one side and the client on the other is two people, still both
    hard, _soft = _range_stops(_TYPED_BY["fix window / card / form edit"](_EFF),
                               _TYPED_BY["client questionnaire"](_EXP))
    assert hard == [_HARD_BACKWARDS]


@pytest.mark.parametrize("how", sorted(_TYPED_BY))
@pytest.mark.parametrize("which", ["effective", "expiration"])
@pytest.mark.parametrize("other", sorted(_NOT_TYPED))
def test_one_retyped_date_beside_an_unverified_one_stays_the_warning(how, which, other):
    """(a) The reviewer's case: documents read 07/15/2027 -> 07/15/2026, the
    producer follows the warning and retypes ONE date. The other side is still
    the document's (or Data Consistency's pick, or our calculation) - the stop
    stays the warning, never a hard stop caused by an unverified date."""
    typed, unverified = _TYPED_BY[how], _NOT_TYPED[other]
    eff = typed(_EFF) if which == "effective" else unverified(_EFF)
    exp = typed(_EXP) if which == "expiration" else unverified(_EXP)
    assert _range_stops(eff, exp) == ([], [BACKWARDS_TERM_TO_CONFIRM])


@pytest.mark.parametrize("eff,exp", [
    ("07/15/2026", "07/15/2027"),          # a normal term
    ("07/15/2026", ""),                    # one date missing
    ("", "07/15/2026"),
    ("not-a-date", "07/15/2026"),          # unparseable: the format rule's job
    (None, None),
])
def test_no_backwards_message_without_a_backwards_term(eff, exp):
    for wrap in list(_NOT_TYPED.values()) + list(_TYPED_BY.values()):
        assert _range_stops(wrap(eff) if eff else eff, wrap(exp) if exp else exp) == ([], [])


@pytest.mark.parametrize("wrap", [_NOT_TYPED["AI extraction"], _TYPED_BY["client questionnaire"]])
def test_the_same_day_twice_is_backwards_too(wrap):
    hard, soft = _range_stops(wrap("07/15/2026"), wrap("07/15/2026"))
    assert len(hard) + len(soft) == 1


def test_one_door_for_whose_date_it_is(monkeypatch):
    """Both term rules ask ONE per-date door (`sqs_service._date_is_person_
    supplied`) - flip it and both severities follow, so the two date rules can
    never disagree about one envelope. The backwards rule needs both dates, the
    expired-term rule the expiration date it judges."""
    import services.sqs_service as sq
    monkeypatch.setattr(sq, "_date_is_person_supplied", lambda facts, key: True)
    assert _range_stops(_EFF, _EXP) == ([_HARD_BACKWARDS], [])
    assert sq.validate_policy_term_not_expired(
        {"effective_date": "01/01/2024", "expiration_date": "01/01/2025"})[0] == "hard"
    monkeypatch.setattr(sq, "_date_is_person_supplied", lambda facts, key: False)
    assert _range_stops(_typed(_EFF), _typed(_EXP)) == ([], [BACKWARDS_TERM_TO_CONFIRM])
    monkeypatch.setattr(sq, "_date_is_person_supplied", lambda facts, key: key == "effective_date")
    assert _range_stops(_typed(_EFF), _typed(_EXP)) == ([], [BACKWARDS_TERM_TO_CONFIRM])
    assert sq.validate_policy_term_not_expired(
        {"effective_date": "01/01/2024", "expiration_date": "01/01/2025"})[0] == "soft"


@pytest.mark.parametrize("other", sorted(_NOT_TYPED))
def test_a_retyped_effective_date_never_makes_a_documents_past_expiration_hard(other):
    """The same trap on the expired-term stop (the reviewer's dates are both in
    the past on 21 Oct 2026): it judges the EXPIRATION date, so only a person's
    expiration makes it hard."""
    import services.sqs_service as sq
    from datetime import datetime, timedelta
    past = (datetime.now() - timedelta(days=200)).strftime("%m/%d/%Y")
    eff = (datetime.now() + timedelta(days=30)).strftime("%m/%d/%Y")
    unverified = _NOT_TYPED[other]
    assert sq.validate_policy_term_not_expired(
        {"effective_date": _typed(eff), "expiration_date": unverified(past)})[0] == "soft"
    assert sq.validate_policy_term_not_expired(
        {"effective_date": unverified(eff), "expiration_date": _typed(past)})[0] == "hard"


@pytest.mark.parametrize("how", sorted(_NOT_TYPED) + sorted(_TYPED_BY))
def test_the_expired_term_rule_reads_provenance_the_same_way(how):
    """The sibling (`validate_policy_term_not_expired`) and this rule give the
    same verdict on the same envelope: person -> hard, otherwise a warning."""
    import services.sqs_service as sq
    wrap = {**_NOT_TYPED, **_TYPED_BY}[how]
    person = how in _TYPED_BY
    backwards_hard = bool(_range_stops(wrap(_EFF), wrap(_EXP))[0])
    expired = sq.validate_policy_term_not_expired(
        {"effective_date": wrap("01/01/2024"), "expiration_date": wrap("01/01/2025")})
    assert backwards_hard is person
    assert (expired[0] == "hard") is person


def test_both_sentences_share_one_row_and_open_the_term_window():
    from services.issue_registry import classify_legacy, resolution_for
    for message, severity in ((_HARD_BACKWARDS, "hard_stop"),
                              (BACKWARDS_TERM_TO_CONFIRM, "soft_warning")):
        code, cluster, tier = classify_legacy(message, severity)
        assert code == "legacy_policy_term_backwards", message
        assert cluster == "Date format & range" and tier == "required"
        res = resolution_for(code)
        assert res["mode"] == "field"
        assert res["facts"] == ["effective_date", "expiration_date", "umbrella_expiration_date"]
    # the FORMAT sentence keeps its own row
    code, _c, _t = classify_legacy("Effective date 'x' could not be parsed", "soft_warning")
    assert code == "legacy_effective_date_format"
    # the warning carries its own Fix line (the pipeline adds a generic one otherwise)
    assert "Fix: " in BACKWARDS_TERM_TO_CONFIRM
    assert "—" not in BACKWARDS_TERM_TO_CONFIRM            # no em-dash in UI text
    # never mistaken for the always-hard sentence by classify_stops
    assert "policy period is invalid" not in BACKWARDS_TERM_TO_CONFIRM


def test_the_review_screen_shows_it_as_a_warning_with_its_window():
    from services.issue_registry import build_grouped_view, build_structured_from_sources
    view = build_grouped_view(
        build_structured_from_sources(legacy_soft=[BACKWARDS_TERM_TO_CONFIRM]),
        [], [BACKWARDS_TERM_TO_CONFIRM])
    assert view["counts"] == {"hard_stops": 0, "warnings": 1, "info": 0}
    item = view["warnings"]["required"][0]["items"][0]
    assert item["code"] == "legacy_policy_term_backwards"
    assert item["resolution"]["mode"] == "field"


def _package_score(facts, flags=None):
    import services.sqs_service as sq
    from services.sqs_service import evaluate_stops
    base = {
        "applicant_name": "Choice Electric LLC", "mailing_address": "1 Main St, Denver CO 80202",
        "lines_of_business": ["General Liability"], "entity_type": "LLC",
        "contact_name": "Eric Berger", "producer_name": "ThinkSmith Agency",
        "fein": "12-3456789", "num_employees": "40", "years_in_business": "12",
        "operations_description": "Commercial electrical contractor",
        "total_revenue": "3200000", "naics_code": "238210",
    }
    base.update(facts)
    flags = {"has_general_liability": True} if flags is None else flags
    hard, soft = evaluate_stops(base, flags)
    tok = sq.SKIP_SHARE_OUT.set(True)
    try:
        return sq.calculate_package_sqs(
            facts=base, flags=flags, form_results=[], cross_issues=[],
            hard_stops=hard, soft_stops=soft, session_data={}, form_fill=False)
    finally:
        sq.SKIP_SHARE_OUT.reset(tok)


def test_the_cap_follows_the_source_through_the_real_scorer():
    """Under the restored caps a warning holds 85 and a hard stop 60, and only
    a hard stop blocks Submission Ready. Both dates in the future, so the
    expired-term rule stays out of it. The read side must show the WARNING
    firing and holding the 85 ceiling - not merely a score under 85."""
    from datetime import datetime, timedelta
    from services.sqs_service import evaluate_stops
    eff = (datetime.now() + timedelta(days=600)).strftime("%m/%d/%Y")
    exp = (datetime.now() + timedelta(days=300)).strftime("%m/%d/%Y")
    read_f = {"effective_date": {"value": eff, "source": "ai"},
              "expiration_date": {"value": exp, "source": "ai"}}
    one_f = {"effective_date": _typed(eff), "expiration_date": {"value": exp, "source": "ai"}}
    both_f = {"effective_date": _typed(eff), "expiration_date": _typed(exp)}
    for facts in (read_f, one_f):
        hard, soft = evaluate_stops(dict(facts), {"has_general_liability": True})
        assert BACKWARDS_TERM_TO_CONFIRM in soft
        assert not [m for m in hard if "expiration date" in m]
        r = _package_score(facts)
        assert r["open_hard_stops"] == 0
        assert r["cap_applied"] == 85
        assert r["cap_reason"] == BACKWARDS_TERM_TO_CONFIRM      # this warning is the ceiling
        assert r["raw_sqs_score"] > 60                           # a 60 cap would have bitten
        assert r["package_sqs_score"] == min(r["raw_sqs_score"], 85)
        assert r["package_sqs_score"] > 60
    typed = _package_score(both_f)
    assert typed["open_hard_stops"] == 1
    assert typed["package_sqs_score"] == 60
    assert typed["cap_applied"] == 60


# ══ review-fixes-1 (21 Oct 2026): M1 - the placement answer is read as an option ══

_MONO_FREE_TEXT = (
    "North Dakota payroll goes to the state fund",
    "North Dakota WSI",
    "Nothing - all payroll is in Colorado",
    "Now with the ND state fund",
    "No private carrier",                       # no separator: can mean the opposite
    "No",                                       # names no private carrier
    "Yes, with a private carrier for ND",
    "No - all payroll with the ND state fund",
    "Nope",
)


@pytest.mark.parametrize("answer", _MONO_FREE_TEXT)
def test_free_text_placement_is_unverified_a_warning_never_the_hard_stop(answer):
    """Adversarial first: four of these began with "no" and raised the HARD
    private-carrier stop by bare prefix. Free "Other" text is unverified - the
    existing warning asking to confirm the placement stays."""
    from services.answer_options import wc_placement
    assert wc_placement(answer) is None
    for source in ("producer", "client_arq"):
        hard, soft = _mono_stops({"wc_state_fund_acknowledged": _env(answer, source)})
        assert hard == [], f"{answer!r} raised the hard stop"
        assert soft == [_SOFT_MONO]


def test_the_canonical_options_and_their_short_forms_still_decide():
    from services.answer_options import OTHER, WC_STATE_FUND_OPTIONS, wc_placement
    yes, no = WC_STATE_FUND_OPTIONS[0], WC_STATE_FUND_OPTIONS[1]
    assert wc_placement(yes) == "state_fund" and wc_placement(no) == "private_carrier"
    assert wc_placement(OTHER) is None
    for text in (no, "No - private carrier", "No (private carrier requested)",
                 "  NO - Private Carrier  ", "no, private carrier for those states"):
        assert wc_placement(text) == "private_carrier", text
        hard, soft = _mono_stops({"wc_state_fund_acknowledged": _env(text, "producer")})
        assert len(hard) == 1 and hard[0].startswith(_HARD_MONO) and soft == []
    for text in (yes, "Yes - placed with the state fund", "Yes", "yes - state fund"):
        assert wc_placement(text) == "state_fund", text
        assert _mono_stops({"wc_state_fund_acknowledged": _env(text, "producer")}) == ([], [])
    for text in ("", None, "Yesterday it moved", OTHER):
        assert wc_placement(text) is None


def test_the_rule_no_longer_reads_the_answer_by_prefix():
    src = (pathlib.Path(__file__).resolve().parents[1] / "services" / "sqs_service.py").read_text(encoding="utf-8")
    assert '_placement.startswith("no")' not in src and '_placement.startswith("yes")' not in src
    assert "_wc_placement(_fv(facts, \"wc_state_fund_acknowledged\"))" in src


# ══ review-fixes-1: M2 - a backwards term a person supplies is refused at the save ══

_STORED_SLIP = {"effective_date": {"value": "07/15/2026", "source": "ai", "confidence": "ai_high"},
                "expiration_date": {"value": "07/15/2025", "source": "ai", "confidence": "ai_high"}}


def test_a_confirm_only_save_of_a_backwards_pair_is_refused():
    """(b) "Confirm these values" sends both shown dates: refused, so the
    warning can never become the hard stop through its own window."""
    from routes.audit_routes import _term_save_refusal
    from utils.validators import TERM_BACKWARDS_REFUSAL
    save = {"effective_date": "07/15/2026", "expiration_date": "07/15/2025"}
    for field, value in save.items():
        assert _term_save_refusal(_STORED_SLIP, field, value, save) == TERM_BACKWARDS_REFUSAL
    assert TERM_BACKWARDS_REFUSAL == "The expiration date must be after the effective date."
    assert not any(e in TERM_BACKWARDS_REFUSAL for e in ("—", "–"))


def test_retyping_one_date_that_leaves_the_pair_backwards_is_refused():
    from routes.audit_routes import _term_save_refusal
    from utils.validators import TERM_BACKWARDS_REFUSAL
    # the effective date confirmed alone: the stored expiration still precedes it
    assert _term_save_refusal(_STORED_SLIP, "effective_date", "07/15/2026") == TERM_BACKWARDS_REFUSAL
    # a recommendation card (no same_save) with another spelling of the same date
    assert _term_save_refusal(_STORED_SLIP, "effective_date", "7/15/26") == TERM_BACKWARDS_REFUSAL


def test_a_save_that_corrects_the_term_is_accepted():
    from datetime import datetime as _dt
    from routes.audit_routes import _term_save_refusal
    # (22 Oct 2026) the same door now refuses a term that has already ENDED, so
    # the corrections are dated from today: a fixed 2027 expiration would read
    # as ended once 07/15/2027 has passed.
    nxt, after = f"07/15/{_dt.now().year + 1}", f"07/15/{_dt.now().year + 2}"
    # correct the slipped expiration alone
    assert _term_save_refusal(_STORED_SLIP, "expiration_date", nxt) == ""
    # move BOTH dates forward in one save: judged as the save, never box by box -
    # the first box (next year) against the stored 2025 expiration alone would be backwards
    save = {"effective_date": nxt, "expiration_date": after}
    assert _term_save_refusal(_STORED_SLIP, "effective_date", nxt, save) == ""
    assert _term_save_refusal(_STORED_SLIP, "expiration_date", after, save) == ""
    # nothing to judge: another field, a missing side, an unreadable date
    assert _term_save_refusal(_STORED_SLIP, "umbrella_expiration_date", "07/15/2020") == ""
    assert _term_save_refusal({}, "effective_date", "07/15/2026") == ""
    assert _term_save_refusal(_STORED_SLIP, "effective_date", "not a date") == ""


def test_a_save_carrying_a_backwards_pair_is_refused_on_every_box_of_it():
    """The umbrella box rides the same save: refused too, so nothing in a
    refused save is half written."""
    from routes.audit_routes import _term_save_refusal
    save = {"effective_date": "07/15/2027", "expiration_date": "07/15/2026",
            "umbrella_expiration_date": "07/15/2026"}
    assert all(_term_save_refusal(_STORED_SLIP, f, v, save) for f, v in save.items())


def test_both_answer_doors_and_the_window_judge_the_whole_save():
    import ast
    root = pathlib.Path(__file__).resolve().parents[1]
    src = (root / "routes" / "audit_routes.py").read_text(encoding="utf-8")
    tree = ast.parse(src)
    callers = {fn.name for fn in ast.walk(tree) if isinstance(fn, ast.AsyncFunctionDef)
               for n in ast.walk(fn) if isinstance(n, ast.Call)
               and getattr(n.func, "id", "") == "_term_save_refusal"}
    assert {"answer_recommendation", "resolve_issue"} <= callers
    assert "_term_save_refusal(_pre_facts, field, value, req.same_save)" in src
    from models.schemas import ResolveIssueRequest
    assert "same_save" in ResolveIssueRequest.model_fields
    modal = (root.parent / "frontend" / "src" / "components" / "form" / "ResolutionModal.jsx").read_text(
        encoding="utf-8")
    assert "same_save: saveValues" in modal and "const saveValues = sameSave(filled);" in modal


def test_the_window_sends_the_whole_save(tmp_path):
    import json
    import shutil
    import subprocess
    if shutil.which("node") is None:
        pytest.skip("node is not installed")
    fw = pathlib.Path(__file__).resolve().parents[1].parent / "frontend" / "src" / "utils" / "fixWindow.js"
    script = tmp_path / "fw.mjs"
    script.write_text(
        f"import * as F from {json.dumps(fw.as_uri())};\n"
        "const t = new Set(['effective_date']);\n"
        "const v = {effective_date: '07/15/2026', expiration_date: '07/15/2025'};\n"
        "const f = ['effective_date', 'expiration_date', 'umbrella_expiration_date'];\n"
        "console.log(JSON.stringify([F.sameSave(F.fieldsToApply(f, v, t).send),\n"
        "  F.sameSave(F.fieldsToApply(f, v, new Set()).send), F.sameSave(null)]));\n",
        encoding="utf-8")
    run = subprocess.run(["node", str(script)], capture_output=True, text=True, timeout=60)
    assert run.returncode == 0, run.stderr
    typed, confirm, empty = json.loads(run.stdout)
    assert typed == {"effective_date": "07/15/2026"}
    assert confirm == {"effective_date": "07/15/2026", "expiration_date": "07/15/2025"}
    assert empty == {}


def test_the_warning_says_correct_and_keeps_its_rule_row():
    from services.issue_registry import classify_legacy
    assert BACKWARDS_TERM_TO_CONFIRM.endswith("Fix: Correct the proposed effective or expiration date.")
    assert "Confirm" not in BACKWARDS_TERM_TO_CONFIRM
    assert classify_legacy(BACKWARDS_TERM_TO_CONFIRM, "soft_warning")[0] == "legacy_policy_term_backwards"
