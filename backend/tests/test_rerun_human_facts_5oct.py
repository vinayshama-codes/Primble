"""A pipeline RE-RUN must not crash and must not drop a person's answers (5 Oct 2026).

Live, CH125 kit, session fa2f62da: every Data Consistency "Confirm" returned 500
("Failed to confirm the underwriting value"). `extraction_pipeline` called `_fv`
in two places and never imported it:

  * line 1520 (since 16 Sep) - reached on every re-run (confirm, reclassify,
    integrity resolve, exclude) of a package whose driver list held a Drive Other
    Car named individual. NameError -> 500.
  * line 580 (since 24 Aug, V1 C1-D / D15) - inside a try, so the NameError was
    swallowed as "human-fact preservation skipped": a producer's or client's
    answer was never carried across a re-run. A producer's correction of a value
    the documents also print was reverted to the document's value.

Why nothing caught it: no test ever EXECUTED `_finalize_pipeline` with a
session - the existing tests read its source. These do execute it (DB and
account lookups stubbed), and the last test fails the build on ANY undefined
name in the product code, the class this bug belongs to.

The rule for a human answer on a re-run (the same documents are re-read, so a
re-run never brings new evidence):
  * documents silent or agreeing -> the human envelope is restored (provenance kept);
  * documents disagree, PRODUCER answer (a card, a form edit, a picker
    confirmation, an accepted client answer) -> the producer's decision stands;
    it was made with these documents in view, so re-asking would undo it;
  * documents disagree, CLIENT questionnaire answer -> held for the producer,
    the same rule the questionnaire applies at write time (F7, rule 1.5).
"""
from __future__ import annotations

import asyncio
import logging
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))

import services.extraction_pipeline as ep  # noqa: E402

DOC_TEXT = """BUSINESS AUTO DECLARATIONS
Named insured: Cumberland Hearth & Hospitality Supply, Inc.
FEIN 62-3418806
DRIVE OTHER CAR - BROADENED COVERAGE FOR NAMED INDIVIDUALS (CA 99 10)
Named individual: Margaret A. Ellison
"""


def _doc(drivers):
    return {"filename": "auto_dec.pdf", "doc_type": "dec_page", "text": DOC_TEXT,
            "facts": {"applicant_name": "Cumberland Hearth & Hospitality Supply, Inc.",
                      "fein": "62-3418806", "naics_code": "423430",
                      "auto_drivers": drivers},
            "flags": {"has_auto_coverage": True}}


def _run(monkeypatch, docs, prior_facts):
    calls = {}

    async def _upd(session_id, payload, delete_facts=None, **_kw):
        calls["session_id"] = session_id
        calls["payload"] = payload
        calls["delete_facts"] = delete_facts

    async def _no_account(_user_id):
        return None

    async def _no_learn(_values):
        return 0

    monkeypatch.setattr(ep, "upd_processing_session", _upd)
    monkeypatch.setattr(ep, "_submitting_account_for", _no_account)
    import services.yes_no_lexicon as ynl
    monkeypatch.setattr(ynl, "learn", _no_learn)
    asyncio.run(ep._finalize_pipeline(docs, "user-ch125", session_id="sess-ch125",
                                      prior_facts=prior_facts, prior_flags={}))
    return calls


def _val(facts, key):
    raw = facts.get(key)
    return raw.get("value") if isinstance(raw, dict) else raw


PRIOR = {
    # documents silent - a producer's card answer
    "num_employees": {"value": "73", "source": "producer", "confidence": "producer"},
    # documents disagree - a producer's correction of the extracted FEIN
    "fein": {"value": "62-3418807", "source": "producer", "confidence": "producer"},
    # documents disagree - a client questionnaire answer
    "naics_code": {"value": "423440", "source": "client_arq", "confidence": "client_arq"},
    # documents agree - the client confirmed the extracted name
    "applicant_name": {"value": "Cumberland Hearth & Hospitality Supply, Inc.",
                       "source": "client_arq", "confidence": "client_arq"},
}


def test_a_rerun_with_a_named_individual_no_longer_crashes(monkeypatch):
    """The live 500: the only 'driver' is the Drive Other Car named individual."""
    calls = _run(monkeypatch, [_doc([{"name": "Margaret A. Ellison"}])], {})
    assert calls["session_id"] == "sess-ch125"
    # she moved out, nobody is left - the stale stored driver row is retracted
    assert calls["delete_facts"] == ["auto_drivers"]
    named = _val(calls["payload"]["facts"], "auto_named_individuals") or []
    assert any("Ellison" in str(r) for r in named)


def test_a_real_driver_beside_the_named_individual_is_kept(monkeypatch):
    drivers = [{"name": "Margaret A. Ellison"},
               {"name": "Marcus T. Bellweather", "dob": "06/11/1984",
                "license_number": "104883127", "license_state": "TN"}]
    calls = _run(monkeypatch, [_doc(drivers)], {})
    assert calls["delete_facts"] is None          # a driver remains - nothing to retract
    left = _val(calls["payload"]["facts"], "auto_drivers") or []
    assert [r.get("name") for r in left] == ["Marcus T. Bellweather"]


def test_human_answers_survive_the_rerun(monkeypatch, caplog):
    caplog.set_level(logging.INFO, logger="services.extraction_pipeline")
    calls = _run(monkeypatch, [_doc([{"name": "Margaret A. Ellison"}])], dict(PRIOR))
    facts = calls["payload"]["facts"]
    assert "human-fact preservation skipped" not in caplog.text

    # silent -> restored, provenance kept
    assert facts["num_employees"]["value"] == "73"
    assert facts["num_employees"]["source"] == "producer"
    # agree -> the human envelope (the client's confirmation) is kept
    assert facts["applicant_name"]["source"] == "client_arq"
    # producer disagrees with the document -> the producer's decision stands
    assert _val(facts, "fein") == "62-3418807"
    assert facts["fein"]["source"] == "producer"
    held = calls["payload"]["client_answer_conflicts"]
    assert "fein" not in held
    # client disagrees with the document -> held for the producer, document stands
    assert _val(facts, "naics_code") == "423430"
    assert held["naics_code"]["client_value"] == "423440"
    assert held["naics_code"]["source_value"] == "423430"


def test_a_picker_confirmation_is_a_producer_decision(monkeypatch):
    """`user_confirmed` (the Data Consistency picker) counts as the producer's."""
    prior = {"fein": {"value": "62-3418807", "source": "user_confirmed"}}
    calls = _run(monkeypatch, [_doc([])], prior)
    assert _val(calls["payload"]["facts"], "fein") == "62-3418807"
    assert "fein" not in calls["payload"]["client_answer_conflicts"]


def test_a_document_value_is_never_overwritten_without_a_human(monkeypatch):
    """No prior human fact -> the documents decide, exactly as before."""
    calls = _run(monkeypatch, [_doc([])], {"fein": {"value": "99-9999999", "source": "ai"}})
    assert _val(calls["payload"]["facts"], "fein") == "62-3418806"


def test_no_undefined_name_anywhere_in_the_product_code():
    """The CLASS: a name used but never bound (F821), an undefined name in
    __all__ (F822), a local read before it is assigned (F823). Each one is a
    NameError / UnboundLocalError that only fires when its branch runs - this
    bug hid for six weeks behind a rarely-true condition and a try/except."""
    ruff = shutil.which("ruff") or str(Path(sys.executable).parent / "ruff")
    if not Path(ruff).exists():
        pytest.skip("ruff is not installed in this environment")
    targets = [p for p in ("services", "routes", "utils", "config", "repositories", "models",
                           "main.py", "worker.py") if (BACKEND / p).exists()]
    out = subprocess.run([ruff, "check", "--select", "F821,F822,F823", "--no-cache",
                          "--output-format", "concise", *targets],
                         cwd=str(BACKEND), capture_output=True, text=True)
    assert out.returncode == 0, out.stdout + out.stderr


# ── Audit G8 (5 Oct night): what the re-run must also keep ───────────────────

_TYPED_DRIVERS = [{"name": "jane smith", "dob": "08/09/2002", "license_number": "D12352",
                   "license_state": "TX"}]


def test_a_typed_driver_beside_a_named_individual_survives_a_rerun(monkeypatch):
    # Stored session cc3ecfcc's shape, saved before tables were marked: the
    # stored list holds a driver a person typed AND the named individual. The
    # documents print no driver. The retract used to delete both.
    prior = {"auto_drivers": [{"name": "Margaret A. Ellison"}] + _TYPED_DRIVERS}
    calls = _run(monkeypatch, [_doc([{"name": "Margaret A. Ellison"}])], prior)
    assert calls["delete_facts"] is None
    assert [r.get("name") for r in calls["payload"]["facts"]["auto_drivers"]] == ["jane smith"]


def test_a_marked_typed_table_survives_a_rerun_whose_documents_print_rows(monkeypatch):
    from services import schedule_capture as sc
    prior = {"auto_drivers": list(_TYPED_DRIVERS) + [
        {"name": "Ana Ruiz", "dob": "01/02/1990", "license_number": "R55", "license_state": "TX"}]}
    sc.mark_human_rows(prior, "auto_drivers", "producer")
    docs = [_doc([{"name": "Margaret A. Ellison"},
                  {"name": "Marcus T. Bellweather", "dob": "06/11/1984",
                   "license_number": "104883127", "license_state": "TN"}])]
    calls = _run(monkeypatch, docs, prior)
    facts = calls["payload"]["facts"]
    assert [r.get("name") for r in facts["auto_drivers"]] == ["jane smith", "Ana Ruiz"]
    rows, src = sc.human_rows(facts, "auto_drivers")
    assert src == "producer" and len(rows) == 2


def test_a_table_the_documents_rewrote_is_no_longer_a_persons():
    from services import schedule_capture as sc
    facts = {"auto_drivers": list(_TYPED_DRIVERS)}
    sc.mark_human_rows(facts, "auto_drivers", "client_arq")
    assert sc.human_rows(facts, "auto_drivers")[1] == "client_arq"
    facts["auto_drivers"] = [{"name": "Someone Else"}]        # a later document re-merge
    assert sc.human_rows(facts, "auto_drivers") == (None, None)


def test_a_producer_none_answer_stands_over_a_document_value(monkeypatch):
    from services.answer_semantics import build_fact_envelope, interpret_answer
    env = build_fact_envelope("dba_name", interpret_answer("dba_name", "None"), "producer", "filled")
    doc = _doc([{"name": "Margaret A. Ellison"}])
    doc["facts"]["dba_name"] = "LSR ROOFING"
    calls = _run(monkeypatch, [doc], {"dba_name": env})
    facts = calls["payload"]["facts"]
    assert facts["dba_name"]["source"] == "producer"
    assert facts["dba_name"].get("value_state") in ("explicit_no", "not_applicable")
    assert "dba_name" not in calls["payload"]["client_answer_conflicts"]


def test_a_client_none_answer_against_a_document_value_is_held(monkeypatch):
    from services.answer_semantics import build_fact_envelope, interpret_answer
    env = build_fact_envelope("dba_name", interpret_answer("dba_name", "None"), "client_arq",
                              "client_arq")
    doc = _doc([{"name": "Margaret A. Ellison"}])
    doc["facts"]["dba_name"] = "LSR ROOFING"
    calls = _run(monkeypatch, [doc], {"dba_name": env})
    assert _val(calls["payload"]["facts"], "dba_name") == "LSR ROOFING"
    assert calls["payload"]["client_answer_conflicts"]["dba_name"]["client_value"] == "None"


def test_a_none_answer_the_documents_are_silent_on_is_remembered(monkeypatch):
    from services.answer_semantics import build_fact_envelope, interpret_answer
    env = build_fact_envelope("num_employees", interpret_answer("num_employees", "None"),
                              "producer", "filled")
    calls = _run(monkeypatch, [_doc([{"name": "Margaret A. Ellison"}])], {"num_employees": env})
    kept = calls["payload"]["facts"]["num_employees"]
    assert kept["source"] == "producer" and kept.get("value_state") in ("explicit_no", "not_applicable")


def test_a_login_derived_producer_fact_is_read_fresh_not_carried(monkeypatch):
    # Account Settings renamed the agency: the stored copy from the old login
    # must not survive a re-run (the merge reads the account every time).
    prior = {"producer_name": {"value": "Bluebonnet Insurance Agency", "source": "account",
                               "confidence": "deterministic", "evidence_state": "user_confirmed",
                               "evidence_actor": "producer"}}
    calls = _run(monkeypatch, [_doc([{"name": "Margaret A. Ellison"}])], prior)
    assert _val(calls["payload"]["facts"], "producer_name") != "Bluebonnet Insurance Agency"
