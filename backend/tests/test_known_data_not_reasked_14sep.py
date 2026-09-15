"""Chat 5 (14 Sep 2026) - do not ask the client for what we already have.

Client, verbatim: "Do not ask the client for information we already have. We
already had the Subaru year/make/model/VIN in the policy, yet the client was
asked for it again. We also had driver questions running through Driver 25.
Primble should prepopulate source-verified information and ask the client to
confirm or correct it, then only ask for what is actually missing."

Every fixture below is the LIVE Orbin shape (D22): the literal page-89 / page-92
text of the 271-page package, the per-document rows extraction stored on the
client's 10 Sep session, and the real ACORD 127 schema - not an all-blank
synthetic form, which is exactly why the earlier "the Subaru is not re-asked"
measurement passed while the live session still re-asked it.
"""
import asyncio
import copy
import json
import os
import pathlib
import re
import sys

import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
os.environ.setdefault("OPENAI_API_KEY", "sk-offline")
os.environ.setdefault("FIELD_ENCRYPTION_KEY", "kZ0aQ7Yy3pR8mN2vB6xL9tJ4hG1sD5fW8cE0uI3oA7k=")

from services import arq_service as A                                  # noqa: E402
from services import confirm_known as ck                               # noqa: E402
from services import schedule_capture as sc                            # noqa: E402
from services.named_individuals import (                               # noqa: E402
    NAMED_INDIVIDUALS_KEY, separate_named_individuals,
)

BACKEND = pathlib.Path(__file__).resolve().parents[1]
REPO = BACKEND.parent
VIN = "4S4BRCGC9C3217772"

# 271page-testdec.txt lines 6110-6128 - Drive Other Car, page 92, verbatim.
PAGE_92 = """[Document page 92]
EMPLOYERS MUTUAL CASUALTY COMPANY POLICY NO: 6E7-40-02---26
ORBIN CONTRACTING LLC EFF DATE: 07/15/25 EXP DATE: 07/15/26
DRIVE OTHER CAR COVERAGE
BROADENED COVERAGE FOR
NAMED INDIVIDUALS
WITH RESPECT TO COVERAGE PROVIDED BY THIS ENDORSEMENT, THE PROVISIONS OF
THE COVERAGE FORM APPLY UNLESS MODIFIED BY THE ENDORSEMENT.
COVERAGES LIMITS/DEDUCTIBLES PREMIUM
COVERED AUTOS
LIABILITY COVERAGE $1,000,000 $ 174.00
AUTO MEDICAL PAYMENTS $ 5,000 $ 4.00
UNINSURED MOTORISTS $1,000,000 $ 26.00
UNDERINSURED MOTORISTS INCLUDED
NAMES OF INDIVIDUALS
ERIN ROYAL
NOTE - WHEN UNINSURED MOTORISTS COVERAGE IS PROVIDED AT LIMITS HIGHER THAN
THE BASIC LIMITS REQUIRED BY A FINANCIAL RESPONSIBILITY LAW, UNDER-
"""

# 271page-testdec.txt lines 6019-6031 - Schedule of Covered Autos, page 89.
PAGE_89 = """COMMERCIAL AUTO DECLARATIONS - BUSINESS AUTO
ITEM THREE - SCHEDULE OF COVERED AUTOS YOU OWN
COVERED AUTO DESCRIPTION / COVERAGE . PREMIUM
LOC: 001 4800 DAHLIA STREET D13
DENVER CO. 80216-3121
VEH NO 1 TERR: 111 .
2012 SUBARU OUTBACK SEDAN ID NO 4S4BRCGC9C3217772.
COST NEW: 26680 RADIUS: NA USE: NA .
PRIV PASSENGER - COMM CLASS: 7383 .
"""

# The rows extraction stored on the client's session (docs[0].facts), verbatim.
ORBIN_DRIVER_ROW = {"dob": None, "name": "ERIN ROYAL", "hire_date": None,
                    "license_state": None, "license_number": None,
                    "experience_years": None, "vehicle_use_percent": None}
ORBIN_VEHICLE_ROW = {"gvw": None, "vin": VIN, "make": "SUBARU", "year": "2012",
                     "model": "OUTBACK SEDAN", "body_type": "PRIV PASSENGER",
                     "coll_symbol": "07", "comp_symbol": "07",
                     "class_code": "7383", "territory": "111"}


def _doc(text, doc_type="dec_page", facts=None, excluded=False):
    return {"filename": "2526 Package Policy (Complete Copy).pdf", "doc_type": doc_type,
            "text": text, "facts": facts or {}, "excluded": excluded}


def _schema(fid):
    with open(BACKEND / "forms_schemas" / f"{fid}_schema.json", encoding="utf-8") as fh:
        return json.load(fh)


def _verified(value):
    return {"value": value, "source": "ai", "confidence": "ai_high",
            "verified_in_text": True}


# ── 1. One person, one role - the Drive Other Car named individual ───────────

def test_orbin_named_individual_leaves_the_driver_list():
    facts = {"auto_drivers": [dict(ORBIN_DRIVER_ROW)]}
    moved = separate_named_individuals(facts, [_doc(PAGE_92)])
    assert moved == ["ERIN ROYAL"]
    assert facts["auto_drivers"] == []
    assert facts[NAMED_INDIVIDUALS_KEY] == [{"name": "ERIN ROYAL", "role": "named_individual"}]


def test_the_real_271_page_text_moves_erin_royal_and_only_her():
    path = REPO / "271page_test_data" / "271page-testdec.txt"
    if not path.exists():
        pytest.skip("271-page OCR dump not present")
    text = path.read_text(encoding="utf-8", errors="replace")
    real_driver = {"name": "JANE SAMPLE", "dob": "01/02/1980", "license_number": "D123"}
    facts = {"auto_drivers": [dict(ORBIN_DRIVER_ROW), real_driver]}
    assert separate_named_individuals(facts, [_doc(text)]) == ["ERIN ROYAL"]
    assert facts["auto_drivers"] == [real_driver]


def test_the_territory_moves_with_her_and_still_fences_the_gl_grid():
    from services.pdf_service import _line_code_witnesses
    facts = {"auto_drivers": [dict(ORBIN_DRIVER_ROW, territory="104")]}
    separate_named_individuals(facts, [_doc(PAGE_92)])
    assert facts[NAMED_INDIVIDUALS_KEY][0]["territory"] == "104"
    assert _line_code_witnesses(facts).get("104") == {"auto"}


def test_a_row_carrying_driver_details_is_never_moved():
    row = dict(ORBIN_DRIVER_ROW, dob="12/01/1976", license_number="94-327-1211")
    facts = {"auto_drivers": [row]}
    assert separate_named_individuals(facts, [_doc(PAGE_92)]) == []
    assert facts["auto_drivers"] == [row]


def test_a_name_under_a_driver_schedule_heading_stays_a_driver():
    text = "SCHEDULE OF DRIVERS\nNAME\nERIN ROYAL\n"
    facts = {"auto_drivers": [dict(ORBIN_DRIVER_ROW)]}
    assert separate_named_individuals(facts, [_doc(text)]) == []


def test_a_name_printed_under_both_headings_stays_a_driver():
    both = PAGE_92 + "\n" + ("X " * 500) + "\nDRIVER INFORMATION\nERIN ROYAL\n"
    facts = {"auto_drivers": [dict(ORBIN_DRIVER_ROW)]}
    assert separate_named_individuals(facts, [_doc(both)]) == []


def test_silence_never_reclassifies():
    facts = {"auto_drivers": [dict(ORBIN_DRIVER_ROW)]}
    # the name printed with no heading above it, and a document that never names her
    assert separate_named_individuals(facts, [_doc("CONTACT: ERIN ROYAL")]) == []
    assert separate_named_individuals(facts, [_doc(PAGE_89)]) == []
    assert separate_named_individuals(facts, []) == []
    assert facts["auto_drivers"] == [ORBIN_DRIVER_ROW]


def test_an_excluded_document_is_not_evidence():
    facts = {"auto_drivers": [dict(ORBIN_DRIVER_ROW)]}
    assert separate_named_individuals(facts, [_doc(PAGE_92, excluded=True)]) == []


def test_the_envelope_shape_is_preserved():
    facts = {"auto_drivers": {"value": [dict(ORBIN_DRIVER_ROW)], "source": "ai"}}
    separate_named_individuals(facts, [_doc(PAGE_92)])
    assert facts["auto_drivers"] == {"value": [], "source": "ai"}


def test_a_longer_name_containing_hers_is_not_a_printing_of_it():
    facts = {"auto_drivers": [dict(ORBIN_DRIVER_ROW)]}
    text = PAGE_92.replace("ERIN ROYAL\n", "ERIN ROYALTON\n")
    assert separate_named_individuals(facts, [_doc(text)]) == []


def test_the_echo_guard_still_knows_her_after_the_move():
    """`_is_name_only_record_echo` blocks the name being used as the evidence for
    a Yes answer (run 6: Q10 'obtain MVR verifications?' = Y, 'ERIN ROYAL').
    It read `auto_drivers` alone; it must still fire once she has moved."""
    from services.pdf_service import _is_name_only_record_echo
    facts = {"auto_drivers": [dict(ORBIN_DRIVER_ROW, territory="104")]}
    separate_named_individuals(facts, [_doc(PAGE_92)])
    assert _is_name_only_record_echo("ERIN ROYAL", facts) is True
    assert _is_name_only_record_echo("The applicant obtains MVRs annually.", facts) is False


# ── 2. The questionnaire, through the real generator, on the Orbin shape ────

def _orbin_127():
    schema = _schema("ACORD_127")
    state = {k: "" for k in schema}
    state.update({
        "Vehicle_ModelYear_A": "2012", "Vehicle_ManufacturersName_A": "Subaru",
        "Vehicle_ModelName_A": "Outback Sedan", "Vehicle_VINIdentifier_A": VIN,
    })
    return {"ACORD_127": {"schema": schema,
                          "confidence": {k: "low_confidence" for k in schema},
                          "field_state": state, "client_filled_fields": []}}


def _orbin_facts():
    facts = {"applicant_name": _verified("ORBIN CONTRACTING LLC"),
             "auto_vin_schedule": [dict(ORBIN_VEHICLE_ROW)],
             "auto_drivers": [dict(ORBIN_DRIVER_ROW)]}
    separate_named_individuals(facts, [_doc(PAGE_92)])
    return facts


def _orbin_docs():
    return [_doc(PAGE_89 + PAGE_92, facts={
        "auto_vin_schedule": [dict(ORBIN_VEHICLE_ROW)],
        "auto_drivers": [dict(ORBIN_DRIVER_ROW)],
        "applicant_name": {"value": "ORBIN CONTRACTING LLC"},
    })]


def _generate(monkeypatch, generated, facts, docs=None, flags=None):
    monkeypatch.setattr(A, "_humanize_fields_with_openai",
                        lambda *a, **k: asyncio.sleep(0))
    present, _ = A._backfill_and_resolve_present(generated, facts)
    return asyncio.run(A.generate_arq_questions(
        facts, flags or {"has_auto_coverage": True}, generated, [], [],
        session_docs=docs, present_fact_keys=present))


def test_the_subaru_is_offered_to_confirm_not_asked_for(monkeypatch):
    qs = _generate(monkeypatch, _orbin_127(), _orbin_facts(), _orbin_docs())
    veh = [q for q in qs if q["field_name"] == "schedule::auto_vin_schedule"]
    assert len(veh) == 1
    q = veh[0]
    assert q["schedule_mode"] == "confirm" and q["confirm"] is True
    assert q["question"].startswith("We found 1 vehicle in your policy declarations.")
    assert "Please list" not in q["question"]
    assert q["current_rows"][0]["vin"] == VIN
    assert q["source_labels"] == ["your policy declarations"]


def test_no_numbered_driver_or_vehicle_card_exists(monkeypatch):
    """Problem 14. 'Driver 25' was a running count of QUESTIONS (the pre-8-Sep
    `group_counts`), not a driver. Pinned on the live 13-driver-row form."""
    qs = _generate(monkeypatch, _orbin_127(), _orbin_facts(), _orbin_docs())
    numbered = [q["question"] for q in qs
                if re.search(r"\(\d+(st|nd|rd|th) (driver|vehicle)\)", q.get("question") or "")]
    assert numbered == []
    visible_driver = [q for q in qs if "driver" in (q.get("question") or "").lower()
                      and q.get("bucket") == "client" and not q.get("suppressed")]
    assert [q["field_name"] for q in visible_driver] == ["schedule::auto_drivers"]


def test_a_policy_with_no_driver_schedule_asks_for_drivers_and_names_nobody(monkeypatch):
    qs = _generate(monkeypatch, _orbin_127(), _orbin_facts(), _orbin_docs())
    drv = next(q for q in qs if q["field_name"] == "schedule::auto_drivers")
    assert drv["schedule_mode"] == "list" and drv["confirm"] is False
    assert drv["current_rows"] == []                      # ERIN ROYAL is not a known driver
    assert drv["question"].startswith("Please list everyone who drives")


def test_a_complete_fleet_is_still_offered_for_confirmation():
    """PASS 1c: no blank box at all, rows held - the client still sees them."""
    schema = _schema("ACORD_127")
    out = A._partition_schedule_fields(
        {}, {}, form_schemas={"ACORD_127": schema},
        facts={"auto_vin_schedule": [dict(ORBIN_VEHICLE_ROW)]})
    assert "auto_vin_schedule" in out


def test_a_confirmed_unchanged_table_is_not_put_to_the_client_again():
    facts = {"auto_vin_schedule": [dict(ORBIN_VEHICLE_ROW)]}
    shown, _ = sc.validate_rows("auto_vin_schedule", sc.rows_from_facts("auto_vin_schedule", facts))
    ck.record_schedule_confirmation(facts, "auto_vin_schedule", shown, "arq1", "2026-09-14")
    assert A._build_schedule_questions({"auto_vin_schedule": {"ACORD_127"}}, facts) == []
    # the fleet changed after the confirmation - it is asked again
    facts["auto_vin_schedule"].append({"year": "2020", "make": "Ford", "model": "F-150",
                                       "vin": "1FTFW1ET5DFC10312"})
    again = A._build_schedule_questions({"auto_vin_schedule": {"ACORD_127"}}, facts)
    assert again and again[0]["question"].startswith("We have 2 vehicles on file")


def test_confirm_wording_is_plain_and_names_every_source():
    rows = [{"address_line1": "4800 DAHLIA ST"}]
    text = sc.question_text("property_locations", rows=rows,
                            source_labels=["your policy declarations",
                                           "your certificate of insurance"])
    assert text == ("We found 1 business location in your policy declarations and your "
                    "certificate of insurance. Please check it, correct anything that "
                    "is wrong, and add any we missed.")
    assert sc.question_text("property_locations").startswith("Please list every business location")
    for key in sc.SCHEDULE_DEFS:
        for t in (sc.question_text(key), sc.question_text(key, rows=[{}, {}]),
                  sc.hint_text(key), sc.hint_text(key, confirm=True)):
            assert "—" not in t                       # UI rule: no em-dash
            assert not t.startswith(A._MACHINE_QUESTION_PREFIX)


# ── 3. Garaging the form already shows is not asked again ────────────────────

def test_garaging_on_the_form_counts_as_known():
    gen = _orbin_127()
    gen["ACORD_127"]["field_state"]["Vehicle_PhysicalAddress_CityName_A"] = "Denver"
    present, _ = A._backfill_and_resolve_present(gen, {})
    assert "auto_garaging_addresses" in present


def test_a_lone_state_code_is_not_a_garaging_address():
    gen = _orbin_127()
    gen["ACORD_127"]["field_state"]["Vehicle_PhysicalAddress_StateOrProvinceCode_A"] = "CO"
    present, _ = A._backfill_and_resolve_present(gen, {})
    assert "auto_garaging_addresses" not in present


# ── 4. An attested "no losses" answers the claims table ──────────────────────

def _loss_q(rows=None):
    return {"field_name": "schedule::loss_history", "question": "Please list any claims",
            "_canonical_key": "loss_history", "current_rows": rows or []}


def test_attested_no_losses_retires_the_empty_claims_table():
    kept = A._apply_loss_state_question_gate(
        [_loss_q(), {"field_name": "fein", "_canonical_key": "fein"}],
        {}, {"no_prior_losses": True})
    assert [q["field_name"] for q in kept] == ["fein"]


def test_claim_rows_that_contradict_the_attestation_stay_visible():
    q = _loss_q([{"date": "03/15/2022", "description": "Slip and fall"}])
    assert A._apply_loss_state_question_gate([q], {}, {"no_prior_losses": True}) == [q]


def test_a_narrative_mention_alone_keeps_the_table():
    q = _loss_q()
    assert A._apply_loss_state_question_gate([q], {}, {"narrative_states_no_losses": True}) == [q]


# ── 5. Confirm-or-correct for the core facts we hold ─────────────────────────

def _form_with(key):
    from services.sqs_service import FORM_FIELD_INVENTORY
    return next(f for f, keys in FORM_FIELD_INVENTORY.items() if key in keys)


def test_a_source_verified_core_fact_is_offered_to_confirm():
    fid = _form_with("applicant_name")
    docs = [_doc("", facts={"applicant_name": {"value": "ORBIN CONTRACTING LLC"}})]
    out = A._build_confirm_questions(
        {"applicant_name": _verified("ORBIN CONTRACTING LLC")}, [fid], [], session_docs=docs)
    q = next(q for q in out if q["field_name"] == "applicant_name")
    assert q["confirm"] is True and q["current_value"] == "ORBIN CONTRACTING LLC"
    assert q["source_labels"] == ["your policy declarations"]
    assert q["audience"] == "client" and q["priority"] == "optional"
    assert q["suppressed"] is False and q["score_impact"]["points"] == 0


def test_a_merely_suggested_value_is_never_shown_as_ours():
    fid = _form_with("applicant_name")
    facts = {"applicant_name": {"value": "ORBIN CONTRACTING LLC", "source": "ai",
                                "confidence": "ai_high"}}
    assert A._build_confirm_questions(facts, [fid], []) == []
    assert A._build_confirm_questions({"applicant_name": "ORBIN CONTRACTING LLC"}, [fid], []) == []


def test_judgment_and_sensitive_facts_are_never_put_to_the_client():
    facts = {"effective_date": _verified("07/15/2025"), "fein": _verified("84-2210987")}
    fids = [_form_with("effective_date"), _form_with("fein")]
    assert A._build_confirm_questions(facts, fids, []) == []


def test_a_contested_or_already_asked_fact_is_not_duplicated():
    fid = _form_with("applicant_name")
    facts = {"applicant_name": _verified("ORBIN CONTRACTING LLC"),
             "_uw_conflict_keys": ["applicant_name"]}
    assert A._build_confirm_questions(facts, [fid], []) == []
    facts.pop("_uw_conflict_keys")
    asked = [{"field_name": "applicant_name", "_canonical_key": "applicant_name"}]
    assert A._build_confirm_questions(facts, [fid], asked) == []


def test_confirm_items_reach_the_list_unselected(monkeypatch):
    facts = _orbin_facts()
    gen = _orbin_127()
    gen["ACORD_125"] = {"schema": _schema("ACORD_125"), "confidence": {},
                        "field_state": {}, "client_filled_fields": []}
    qs = _generate(monkeypatch, gen, facts, _orbin_docs())
    conf = [q for q in qs if q.get("confirm") and q.get("field_type") != "schedule"]
    assert any(q["field_name"] == "applicant_name" for q in conf)
    assert all(not q.get("default_selected") for q in conf)


# ── 6. The answer path: sanitize, submit, apply, receipt ─────────────────────

def test_sanitize_keeps_a_table_confirmation_and_still_cleans_rows():
    from routes.arq_routes import _sanitize_answers
    out = _sanitize_answers({"schedule::auto_vin_schedule": ck.CONFIRMED_SENTINEL,
                             "schedule::auto_drivers": json.dumps([{"name": "<b>Jo Smith</b>"}])})
    assert out["schedule::auto_vin_schedule"] == ck.CONFIRMED_SENTINEL
    assert json.loads(out["schedule::auto_drivers"])[0]["name"] == "Jo Smith"


class _Conn:
    def __init__(self):
        self.calls = []

    async def execute(self, sql, *args):
        self.calls.append((sql, args))


class _Acq:
    def __init__(self, conn):
        self.conn = conn

    async def __aenter__(self):
        return self.conn

    async def __aexit__(self, *exc):
        return False


class _Pool:
    def __init__(self):
        self.conn = _Conn()

    def acquire(self):
        return _Acq(self.conn)


def _submit(monkeypatch, questions, answers, touched=()):
    arq = {"expires_at": "2999-01-01T00:00:00+00:00", "status": "pending",
           "questions": questions}

    async def _get(_token):
        return arq
    pool = _Pool()
    monkeypatch.setattr(A, "get_arq_by_token", _get)
    monkeypatch.setattr(A, "get_pool", lambda: pool)
    ok, _msg, updated, errors = asyncio.run(
        A.submit_arq_answers("tok", answers, "sid", {}, touched_fields=list(touched)))
    assert ok and not errors
    args = pool.conn.calls[0][1]
    return updated, json.loads(args[0]), json.loads(args[2])


def _veh_q(confirm=True):
    shown, _ = sc.validate_rows("auto_vin_schedule", [dict(ORBIN_VEHICLE_ROW)])
    return {"field_name": "schedule::auto_vin_schedule", "question": "We found 1 vehicle",
            "field_type": "schedule", "schedule_key": "auto_vin_schedule",
            "current_rows": shown, "confirm": confirm}


def test_submit_records_a_confirmation_only_on_a_confirm_question(monkeypatch):
    qs = [{"field_name": "applicant_name", "question": "Legal name?", "field_type": "text",
           "confirm": True, "current_value": "ORBIN CONTRACTING LLC"},
          {"field_name": "dba_name", "question": "DBA?", "field_type": "text"},
          _veh_q()]
    updated, stored, review = _submit(monkeypatch, qs, {
        "applicant_name": ck.CONFIRMED_SENTINEL,
        "dba_name": ck.CONFIRMED_SENTINEL,               # crafted - never shown a value
        "schedule::auto_vin_schedule": ck.CONFIRMED_SENTINEL,
    })
    assert stored == {"applicant_name": ck.CONFIRMED_SENTINEL,
                      "schedule::auto_vin_schedule": ck.CONFIRMED_SENTINEL}
    assert set(updated) == set(stored) and review == []


def test_an_untouched_confirm_item_is_not_an_answer(monkeypatch):
    qs = [{"field_name": "applicant_name", "question": "Legal name?", "field_type": "text",
           "confirm": True, "current_value": "ORBIN CONTRACTING LLC"}, _veh_q()]
    q_seed = sc.encode_answer(_veh_q()["current_rows"])
    updated, stored, _ = _submit(monkeypatch, qs, {
        "applicant_name": "", "schedule::auto_vin_schedule": q_seed})
    assert stored == {} and updated == []


def test_removing_a_document_row_applies_but_is_flagged_for_the_producer(monkeypatch):
    updated, stored, review = _submit(
        monkeypatch, [_veh_q()], {"schedule::auto_vin_schedule": "[]"},
        touched=["schedule::auto_vin_schedule"])
    assert json.loads(stored["schedule::auto_vin_schedule"]) == []
    assert len(review) == 1 and "1 row(s) from the documents" in review[0]["reason"]


def test_schedule_row_changes_is_judged_by_row_identity():
    seed, _ = sc.validate_rows("auto_vin_schedule", [dict(ORBIN_VEHICLE_ROW)])
    added = seed + [{"year": "2020", "make": "Ford", "model": "F-150",
                     "vin": "1FTFW1ET5DFC10312", "body_type": "", "gvw": "",
                     "comp_symbol": "", "coll_symbol": ""}]
    altered = [dict(seed[0], year="2013")]
    assert ck.schedule_row_changes("auto_vin_schedule", seed, list(reversed(added))) == 0
    assert ck.schedule_row_changes("auto_vin_schedule", seed, altered) == 1
    assert ck.schedule_row_changes("auto_vin_schedule", seed, []) == 1


def test_apply_writes_provenance_and_never_a_value(monkeypatch):
    import repositories.session_repository as repo
    facts = {"applicant_name": _verified("ORBIN CONTRACTING LLC"),
             "auto_vin_schedule": [dict(ORBIN_VEHICLE_ROW)]}
    session = {"user_id": "u1", "facts": copy.deepcopy(facts), "flags": {},
               "generated_forms": _orbin_127()}
    arq = {"id": "arq1", "status": "submitted",
           "questions": [{"field_name": "applicant_name", "confirm": True,
                          "current_value": "ORBIN CONTRACTING LLC", "form_ids": ["ACORD_125"]},
                         _veh_q()],
           "answers": {"applicant_name": ck.CONFIRMED_SENTINEL,
                       "schedule::auto_vin_schedule": ck.CONFIRMED_SENTINEL}}
    saved = {}

    async def _get_arq(_id):
        return arq

    async def _get_session(_sid):
        return copy.deepcopy(session)

    async def _upd(_sid, payload, delete_facts=None):
        saved.update(payload)
    monkeypatch.setattr(A, "get_arq_by_id", _get_arq)
    monkeypatch.setattr(repo, "get_processing_session", _get_session)
    monkeypatch.setattr(repo, "upd_processing_session", _upd)
    ok, updated = asyncio.run(A.apply_arq_answers_to_session("arq1", "sid"))
    assert ok and updated == []                           # nothing was FILLED
    env = saved["facts"]["applicant_name"]
    assert env["value"] == "ORBIN CONTRACTING LLC"
    from services.fact_state import derive_evidence_state, human_provenance_facts
    assert derive_evidence_state(env)[0] == "user_confirmed"
    assert "applicant_name" in human_provenance_facts(saved["facts"])   # survives a re-run
    assert saved["facts"]["auto_vin_schedule"] == [ORBIN_VEHICLE_ROW]
    assert "schedule::auto_vin_schedule" in saved["facts"][ck.CONFIRMATIONS_KEY]
    # no box was touched and nothing is labelled as client-supplied
    conf = saved["generated_forms"]["ACORD_127"]["confidence"]
    assert "client_arq" not in conf.values()
    # and the next questionnaire does not put the same list to the client again
    assert A._build_schedule_questions({"auto_vin_schedule": {"ACORD_127"}},
                                       saved["facts"]) == []


def test_a_confirmation_of_a_value_that_changed_since_is_not_recorded():
    # A genuinely different entity. (A containment variant such as
    # "ORBIN CONTRACTING, LLC" is the SAME name to the comparison door, and a
    # confirmation of it rightly stands.)
    facts = {"applicant_name": _verified("HALVORSEN STRUCTURAL LLC")}
    assert ck.record_fact_confirmation(facts, "applicant_name", "ORBIN CONTRACTING LLC",
                                       "arq1", "2026-09-14") is False
    assert "evidence_state" not in facts["applicant_name"]
    facts = {"applicant_name": _verified("ORBIN CONTRACTING, LLC")}
    assert ck.record_fact_confirmation(facts, "applicant_name", "ORBIN CONTRACTING LLC",
                                       "arq1", "2026-09-14") is True


def test_the_receipt_files_a_confirmation_as_its_own_kind():
    from services.arq_receipt_service import KIND_CONFIRMED, build_receipt_payload
    payload = build_receipt_payload({
        "id": "arq1", "questions": [
            {"field_name": "applicant_name", "question": "Legal name?",
             "current_value": "ORBIN CONTRACTING LLC", "confirm": True},
            _veh_q()],
        "answers": {"applicant_name": ck.CONFIRMED_SENTINEL,
                    "schedule::auto_vin_schedule": ck.CONFIRMED_SENTINEL},
    })
    kinds = {i["field_name"]: i for i in payload["items"]}
    assert kinds["applicant_name"]["kind"] == KIND_CONFIRMED
    assert kinds["applicant_name"]["value"] == "ORBIN CONTRACTING LLC"
    assert kinds["schedule::auto_vin_schedule"]["kind"] == KIND_CONFIRMED
    assert kinds["schedule::auto_vin_schedule"]["row_count"] == 1
    assert payload["confirmed_count"] == 2 and payload["answered_count"] == 2


def test_both_serializers_carry_confirm_mode():
    """send_arq and client_view are inline in DB-backed routes, so - like the
    Figure 20 suggestions guard - this reads their source: each must route a
    confirm question through `confirm_known`, or the client sees a blank box."""
    import inspect
    from routes import arq_routes
    for fn in (arq_routes.send_arq, arq_routes.client_view):
        body = inspect.getsource(fn)
        assert "confirm_known." in body and '"confirm"' in body, fn.__name__
