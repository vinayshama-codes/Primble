"""
Figure 21: client response receipt.

Covers the payload builder (pure, no DB) and the encryption/immutability
contract. The builder is where every correctness risk lives - the DB layer is a
single INSERT and a single SELECT.
"""
import json
import os
import sys

import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

# A deterministic key so encrypt/decrypt round-trips are testable without
# depending on the developer's .env.
os.environ.setdefault("FIELD_ENCRYPTION_KEY", "kZ0aQ7Yy3pR8mN2vB6xL9tJ4hG1sD5fW8cE0uI3oA7k=")

from services.arq_receipt_service import (  # noqa: E402
    KIND_ANSWER,
    KIND_BLANK,
    KIND_NOT_SURE,
    KIND_SCHEDULE,
    build_receipt_payload,
)


def _arq(**over):
    base = {
        "id":         "arq-1",
        "session_id": "sess-1",
        "user_id":    "user-1",
        "client_name": "Acme Roofing LLC",
        "email":      "owner@acme.test",
        "submitted_at": "2026-07-21T10:00:00+00:00",
        "questions": [
            {"field_name": "applicant_name", "question": "Legal business name?"},
            {"field_name": "naics_code",     "question": "NAICS code?"},
            {"field_name": "annual_revenue", "question": "Annual revenue?"},
            {"field_name": "never_answered", "question": "Anything else?"},
        ],
        "answers": {
            "applicant_name": "Acme Roofing LLC",
            "annual_revenue": "$2,400,000",
        },
        "not_sure_fields": [{"field_name": "naics_code", "question": "NAICS code?"}],
        "review_fields":   [],
    }
    base.update(over)
    return base


# ---------------------------------------------------------------------------
# Payload shape
# ---------------------------------------------------------------------------

def test_every_asked_question_appears_in_the_receipt():
    """A receipt records what was ASKED, not just what came back - a blank is
    evidence the question was put to the client."""
    p = build_receipt_payload(_arq())
    assert p["question_count"] == 4
    assert [i["field_name"] for i in p["items"]] == [
        "applicant_name", "naics_code", "annual_revenue", "never_answered",
    ]


def test_question_order_is_preserved():
    p = build_receipt_payload(_arq())
    assert [i["question"] for i in p["items"]][0] == "Legal business name?"


def test_kinds_are_classified_correctly():
    p = build_receipt_payload(_arq())
    by_field = {i["field_name"]: i for i in p["items"]}
    assert by_field["applicant_name"]["kind"] == KIND_ANSWER
    assert by_field["applicant_name"]["value"] == "Acme Roofing LLC"
    assert by_field["naics_code"]["kind"] == KIND_NOT_SURE
    assert by_field["never_answered"]["kind"] == KIND_BLANK
    assert "value" not in by_field["never_answered"]


def test_counts_match_the_items():
    p = build_receipt_payload(_arq())
    assert p["answered_count"] == 2
    assert p["not_sure_count"] == 1
    assert len([i for i in p["items"] if i["kind"] == KIND_BLANK]) == 1


def test_not_sure_never_leaks_a_value():
    """The sentinel must never be recorded as though the client answered."""
    arq = _arq(answers={"naics_code": "__NOT_SURE__"})
    p = build_receipt_payload(arq)
    item = next(i for i in p["items"] if i["field_name"] == "naics_code")
    assert item["kind"] == KIND_NOT_SURE
    assert "value" not in item


def test_legacy_not_sure_as_bare_strings_still_classified():
    """Rows written before not_sure_fields held dicts."""
    arq = _arq(not_sure_fields=["naics_code"])
    p = build_receipt_payload(arq)
    item = next(i for i in p["items"] if i["field_name"] == "naics_code")
    assert item["kind"] == KIND_NOT_SURE


def test_review_reason_is_attached_to_its_answer():
    arq = _arq(review_fields=[{"field_name": "annual_revenue", "reason": "unreadable amount"}])
    p = build_receipt_payload(arq)
    item = next(i for i in p["items"] if i["field_name"] == "annual_revenue")
    assert item["review_reason"] == "unreadable amount"
    assert p["review_count"] == 1


def test_answers_for_questions_never_asked_are_ignored():
    """Iterating questions (not answer keys) is what bounds this - a crafted
    payload must not be able to write arbitrary rows into an audit record."""
    arq = _arq(answers={"applicant_name": "Acme", "injected_field": "evil"})
    p = build_receipt_payload(arq)
    assert "injected_field" not in [i["field_name"] for i in p["items"]]


# ---------------------------------------------------------------------------
# Schedules
# ---------------------------------------------------------------------------

def test_schedule_rows_are_recorded_with_a_count():
    rows = [{"vin": "1FT", "make": "Ford"}, {"vin": "2GC", "make": "Chevy"}]
    arq = _arq(
        questions=[{"field_name": "schedule::auto_vin_schedule", "question": "Vehicles"}],
        answers={"schedule::auto_vin_schedule": json.dumps(rows)},
        not_sure_fields=[],
    )
    p = build_receipt_payload(arq)
    item = p["items"][0]
    assert item["kind"] == KIND_SCHEDULE
    assert item["row_count"] == 2
    assert item["rows"] == rows
    assert p["answered_count"] == 1


def test_empty_schedule_is_blank_not_answered():
    arq = _arq(
        questions=[{"field_name": "schedule::auto_vin_schedule", "question": "Vehicles"}],
        answers={"schedule::auto_vin_schedule": "[]"},
        not_sure_fields=[],
    )
    p = build_receipt_payload(arq)
    assert p["items"][0]["kind"] == KIND_BLANK
    assert p["answered_count"] == 0


def test_oversized_schedule_is_capped_and_flagged():
    """Bounded so one crafted answer cannot write an unbounded row, but the
    truncation is declared rather than silent."""
    rows = [{"vin": f"V{i}"} for i in range(500)]
    arq = _arq(
        questions=[{"field_name": "schedule::auto_vin_schedule", "question": "Vehicles"}],
        answers={"schedule::auto_vin_schedule": json.dumps(rows)},
        not_sure_fields=[],
    )
    item = build_receipt_payload(arq)["items"][0]
    assert item["row_count"] == 500
    assert len(item["rows"]) == 200
    assert item["rows_truncated"] is True


# ---------------------------------------------------------------------------
# Robustness - a receipt must never break a submission
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("arq", [
    {},
    {"questions": [], "answers": {}},
    {"questions": None, "answers": None, "not_sure_fields": None, "review_fields": None},
    {"questions": ["not-a-dict", {"no_field_name": 1}], "answers": {}},
    {"questions": [{"field_name": "x", "question": "Q"}], "answers": {"x": None}},
])
def test_builder_never_raises_on_degenerate_rows(arq):
    p = build_receipt_payload(arq)
    assert isinstance(p["items"], list)


def test_long_value_is_clipped():
    arq = _arq(
        questions=[{"field_name": "ops", "question": "Operations?"}],
        answers={"ops": "x" * 99999},
        not_sure_fields=[],
    )
    assert len(build_receipt_payload(arq)["items"][0]["value"]) == 4000


# ---------------------------------------------------------------------------
# Encryption contract
# ---------------------------------------------------------------------------

def test_payload_round_trips_through_encryption():
    from utils.crypto import decrypt_field, encrypt_field
    p = build_receipt_payload(_arq())
    ct = encrypt_field(json.dumps(p))
    assert ct.startswith("enc:")
    assert "Acme Roofing LLC" not in ct          # the PII is not readable at rest
    assert json.loads(decrypt_field(ct)) == p    # and survives the round trip


def test_receipt_service_exposes_no_mutation_api():
    """Immutability is the product requirement, so it is asserted, not assumed:
    if someone later adds an update/delete helper, this fails."""
    import services.arq_receipt_service as svc
    public = [n for n in dir(svc) if not n.startswith("_")]
    for banned in ("update_receipt", "delete_receipt", "edit_receipt", "set_receipt"):
        assert banned not in public
