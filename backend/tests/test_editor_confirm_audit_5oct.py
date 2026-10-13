"""The Data Consistency confirm AFTER forms exist - fixes from the G7 audit
(5 Oct 2026, night).

The audit replayed 29 real confirmations on four non-kit packages. Every one
returned 200 and closed its card, but:
  * a confirmed mailing address, entity type, payroll or gross receipts left the
    form printing the overruled value (7 of 20 confirmable facts on Orbin), and
    ACORD 125 question 4 printed one policy twice - the re-stamp reached only
    boxes whose canonical key IS the fact;
  * 80 boxes were relabelled "producer" although their value never changed;
  * a second answer on the same line re-applied the whole map onto rows the
    first had rewritten - the policy number landed beside the other company;
  * "banana", "13/45/2026", "N/A" and "TBD" were accepted and stamped;
  * a scope naming no line was stored and silenced warnings;
  * cards for fields the answer settled indirectly stayed in the stored issues.

These pin the fixes without a database. The stored-session replays live in the
tracker (5Oct-formImprovement-125-126-127.md, "Round 3").
"""
import asyncio
import json
import os

import pytest

import services.arq_service as aq
import services.extraction_pipeline as ep
from services import template_tables as tt
from services.underwriting_consistency import (
    confirmed_fact_keys, known_line_scope, validate_confirmation,
)

BACKEND = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


# ── Validation ───────────────────────────────────────────────────────────────

@pytest.mark.parametrize("fact_key,value", [
    ("effective_date", "banana"),
    ("effective_date", "13/45/2026"),
    ("effective_date", "02/30/2026"),
    ("applicant_name", "N/A"),
    ("applicant_name", "TBD"),
    ("mailing_address", "unknown"),
])
def test_a_confirmation_must_be_a_real_value(fact_key, value):
    with pytest.raises(ValueError) as exc:
        validate_confirmation(fact_key, value, docs=[])
    assert str(exc.value) == "underwriting_invalid_value"


@pytest.mark.parametrize("fact_key,value", [
    ("effective_date", "10/01/2026"),
    ("applicant_name", "Cumberland Hearth & Hospitality Supply, Inc."),
    ("mailing_address", "1200 Federal Blvd, Denver, CO 80204"),
])
def test_a_real_value_still_confirms(fact_key, value):
    assert validate_confirmation(fact_key, value, docs=[])


def test_only_a_line_scoped_fact_on_a_known_line_counts_as_confirmed():
    keys = confirmed_fact_keys({"effective_date@auto": "03/01/2026",
                                "mailing_address@auto": "1 Main St",
                                "applicant_name": "Acme"})
    assert keys == {"effective_date", "applicant_name"}
    assert known_line_scope("general_liab") and known_line_scope("auto")
    assert not known_line_scope("bogus_line") and not known_line_scope("")


# ── The editor confirm itself ────────────────────────────────────────────────

def _session(facts, confirmations=None):
    return {"user_id": "u1",
            "docs": [{"filename": "dec.pdf", "doc_type": "dec_page", "text": "", "facts": {}}],
            "facts": facts, "flags": {},
            "underwriting_confirmations": confirmations or {},
            "generated_forms": {"ACORD_125": {"schema": {}, "field_state": {}, "confidence": {}}},
            "structured_issues": []}


def _run(monkeypatch, session, **kw):
    writes = {}

    async def _upd(_sid, payload, delete_facts=None, **_kw):
        writes.update(payload)
        writes["_deleted"] = delete_facts

    monkeypatch.setattr(ep, "upd_processing_session", _upd)
    out = asyncio.run(ep.confirm_underwriting_value_in_editor(session, "s1", **kw))
    return out, writes


def test_a_scope_that_names_no_line_is_refused(monkeypatch):
    with pytest.raises(ValueError) as exc:
        _run(monkeypatch, _session({}), fact_key="policy_number", value="ZZ-0001",
             scope="bogus_line")
    assert str(exc.value) == "underwriting_invalid_scope"
    with pytest.raises(ValueError):
        _run(monkeypatch, _session({}), fact_key="mailing_address", value="1 Main St",
             scope="auto")


def test_changing_a_line_answer_without_the_documents_rows_is_refused(monkeypatch):
    # A session generated before the pipeline kept the unconfirmed rows: its
    # rows already carry the first answer, and a different one cannot be
    # re-applied safely - say so instead of corrupting the line.
    facts = {"coverage_lines": [{"line": "Commercial General Liability",
                                 "policy_number": "BBC7263-26", "_confirmed": True}]}
    session = _session(facts, {"policy_number@general_liab": "BBC7263-26"})
    with pytest.raises(ValueError) as exc:
        _run(monkeypatch, session, fact_key="policy_number", value="6C7-40-02-26",
             scope="general_liab")
    assert str(exc.value) == "underwriting_line_already_confirmed"


def test_the_documents_rows_are_kept_and_restored(monkeypatch):
    pristine = [{"line": "Commercial General Liability", "policy_number": "BBC7263-26",
                 "carrier": "EMC Property & Casualty Company", "premium": "$1,200"}]
    facts = {"coverage_lines": [dict(pristine[0], _confirmed=True, carrier="Rewritten")],
             ep.UNCONFIRMED_COVERAGE_LINES_KEY: pristine}
    _out, writes = _run(monkeypatch, _session(facts), fact_key="applicant_name",
                        value="Cumberland Hearth Supply, Inc.")
    rows = writes["facts"]["coverage_lines"]
    assert rows[0]["carrier"] == "EMC Property & Casualty Company"
    assert writes["facts"][ep.UNCONFIRMED_COVERAGE_LINES_KEY] == pristine


# ── The re-stamp: every box the change moves, labelled honestly ──────────────

def _schema(form_id):
    with open(os.path.join(BACKEND, "forms_schemas", f"{form_id}_schema.json")) as fh:
        return json.load(fh)


def _generated(form_id, facts, person_boxes=None):
    from services.pdf_service import _deterministic_map, _schema_context, _is_nonfillable_field
    schema = _schema(form_id)
    state, conf = {}, {}
    with _schema_context(schema):
        for box in schema:
            if _is_nonfillable_field(box):
                continue
            v = _deterministic_map(box, {**facts, "_form_id": form_id})
            if aq._refill_value(v):
                state[box], conf[box] = str(v), "filled"
    for box, val in (person_boxes or {}).items():
        state[box], conf[box] = val, "producer"
    return {form_id: {"schema": schema, "field_state": state, "confidence": conf,
                      "client_filled_fields": []}}


def test_a_confirmed_address_reaches_every_box_it_moves_and_nothing_else():
    before = {"applicant_name": "Acme Roofing LLC",
              "mailing_address": "100 Main St, Denver, CO 80202"}
    gen = _generated("ACORD_125", before,
                     person_boxes={"NamedInsured_Primary_PhoneNumber_A": "303-555-0100"})
    name_label = gen["ACORD_125"]["confidence"].get("NamedInsured_FullName_A")
    after = dict(before, mailing_address={"value": "1200 Federal Blvd, Aurora, CO 80011",
                                          "source": "user_confirmed"})
    touched = aq._restamp_changed_boxes(gen, before, after, {"mailing_address"},
                                        "1200 Federal Blvd, Aurora, CO 80011")
    form = gen["ACORD_125"]
    assert touched == ["ACORD_125"]
    assert form["field_state"]["NamedInsured_MailingAddress_LineOne_A"] == "1200 Federal Blvd"
    assert form["confidence"]["NamedInsured_MailingAddress_LineOne_A"] == "producer"
    assert form["field_state"]["NamedInsured_MailingAddress_PostalCode_A"] == "80011"
    # nothing the change does not move: the name keeps its value AND its label
    assert form["confidence"].get("NamedInsured_FullName_A") == name_label
    # a person's box stands
    assert form["field_state"]["NamedInsured_Primary_PhoneNumber_A"] == "303-555-0100"
    assert form["confidence"]["NamedInsured_Primary_PhoneNumber_A"] == "producer"


def test_a_box_edited_since_generation_is_not_overwritten_by_a_derived_change():
    before = {"applicant_name": "Acme Roofing LLC",
              "mailing_address": "100 Main St, Denver, CO 80202"}
    gen = _generated("ACORD_125", before)
    gen["ACORD_125"]["field_state"]["NamedInsured_MailingAddress_CityName_A"] = "Englewood"
    gen["ACORD_125"]["confidence"]["NamedInsured_MailingAddress_CityName_A"] = "low_confidence"
    after = dict(before, applicant_name="Acme Roofing Holdings LLC")
    aq._restamp_changed_boxes(gen, before, after, {"applicant_name"}, "Acme Roofing Holdings LLC")
    assert gen["ACORD_125"]["field_state"]["NamedInsured_MailingAddress_CityName_A"] == "Englewood"


# ── The template tables ──────────────────────────────────────────────────────

def test_every_template_has_a_current_precomputed_table():
    from services.pdf_service import PRINTED_CURRENCY_READER_VERSION
    from services.state_restricted_boxes import READER_VERSION
    with open(tt.tables_path()) as fh:
        tables = json.load(fh)["tables"]
    forms = sorted(f[:-4] for f in os.listdir(os.path.dirname(tt.tables_path()))
                   if f.lower().endswith(".pdf"))
    for fid in forms:
        cur = tables["printed_currency_fields"][fid]
        st = tables["state_restricted_boxes"][fid]
        assert cur["sha"] == tt.template_sha(fid) == st["sha"], fid
        assert cur["version"] == PRINTED_CURRENCY_READER_VERSION and st["version"] == READER_VERSION


def test_the_precomputed_tables_equal_a_live_read():
    from services.pdf_service import _fields_with_printed_currency, _read_fields_with_printed_currency
    from services.state_restricted_boxes import read_restricted_boxes, restricted_boxes
    assert _fields_with_printed_currency("ACORD_186") == _read_fields_with_printed_currency("ACORD_186")
    assert dict(restricted_boxes("ACORD_126")) == dict(read_restricted_boxes("ACORD_126"))


def test_a_stale_table_entry_is_never_used(monkeypatch):
    monkeypatch.setattr(tt, "template_sha", lambda _fid: "not-the-template")
    assert tt.stored("printed_currency_fields", "ACORD_186", 1) is None
