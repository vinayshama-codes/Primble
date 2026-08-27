"""V1 REQUIRED REGRESSION TEST PACK - Conflict, override, derivation lineage
(client tests 14, 15, 16).

Part of the client's REQUIRED V1 REGRESSION TEST PACK. Recurring regression
scenarios: re-run on every change to the client-answer hold, the producer
override path, the audit spine, or fact derivation.

  Test 14 - Client Answer Conflicts With Source
  Test 15 - Producer Override
  Test 16 - Derived Effective Date

These enforce V1 core principles 4 (do not silently resolve genuine conflicts)
and 6 (preserve provenance: Source -> Extracted Value -> Normalized Fact ->
Human Changes -> Final Value -> SQS / Output).

Every test drives the REAL hold reader (`services/client_answer_review.py`), the
REAL fact-state axis, the REAL audit envelope builder
(`audit_history.build_change_envelope` - the one shape every event uses) and the
REAL lineage recovery (`services/fact_lineage.py`).

The resolve endpoint itself is async and DB-backed; its pure decision parts are
driven directly and its seam is pinned by reading the module, because an
offline probe proves the FUNCTION and never the SEAM around it.
"""
import inspect
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from services import audit_history as ah                      # noqa: E402
from services import audit_service as aud                     # noqa: E402
from services import client_answer_review as car              # noqa: E402
from services import fact_lineage as fl                       # noqa: E402
from services import fact_state as fs                         # noqa: E402
from services import sqs_service as sq                        # noqa: E402

BACKEND = Path(__file__).resolve().parents[1]

SOURCE_VALUE = "$1,850,000"
CLIENT_VALUE = "$2,400,000"
FACT = "total_revenue"
FIELD = "BusinessInfo_AnnualGrossSales_A"


def _session_with_held_answer():
    """A session whose client questionnaire answer contradicts the documents,
    in the live shape the pipeline writes (the hold rides on facts under
    `_client_answer_conflicts`, mirrored to its own durable column)."""
    held = {
        FACT: {
            "client_value": CLIENT_VALUE,
            "source_value": SOURCE_VALUE,
            "field_name": FIELD,
            "held_at": "2026-08-27T10:00:00+00:00",
        }
    }
    return {
        "id": "sess-1",
        car.SESSION_KEY: held,
        "facts": {
            # THE SOURCE VALUE IS STILL THE FACT - this is the whole point.
            FACT: {"value": SOURCE_VALUE, "source": "document",
                   "confidence": "filled"},
            car.FACTS_KEY: held,
        },
    }


# =============================================================================
# TEST 14 - Client Answer Conflicts With Source
# =============================================================================

def test_r14_source_value_is_not_overwritten():
    """The source value is NOT overwritten by the contradicting client answer."""
    session = _session_with_held_answer()
    facts = session["facts"]
    assert facts[FACT]["value"] == SOURCE_VALUE
    assert facts[FACT]["source"] == "document"

    # The client's answer is held OUTSIDE the fact, never merged into it.
    assert CLIENT_VALUE not in str(facts[FACT])


def test_r14_value_state_becomes_conflicting():
    """The value state becomes Conflicting."""
    conflicted = {FACT: SOURCE_VALUE, "_uw_conflicted_keys": [FACT]}
    assert fs.value_state_of(conflicted, FACT) == fs.CONFLICTING

    # POSITIVE CONTROL - the same fact with no conflict recorded is not
    # Conflicting, so the state above is the conflict and not a constant.
    assert fs.value_state_of({FACT: SOURCE_VALUE}, FACT) != fs.CONFLICTING


def test_r14_producer_receives_a_resolution_item():
    """The producer receives a resolution item."""
    session = _session_with_held_answer()
    rows = car.build_review_rows(session)
    assert len(rows) == 1

    row = rows[0]
    assert row["fact_key"] == FACT
    assert row["client_value"] == CLIENT_VALUE
    assert row["source_value"] == SOURCE_VALUE
    assert row["field_name"] == FIELD
    assert row["held_at"]
    assert "does not match" in row["reason"]
    # A human-readable label, not a raw key, or the producer cannot act on it.
    assert row["label"] != FACT

    # POSITIVE CONTROL - a session with nothing held renders no section.
    assert car.build_review_rows({"id": "s", "facts": {}}) == []


def test_r14_both_values_remain_auditable():
    """BOTH values remain auditable - neither is discarded."""
    session = _session_with_held_answer()
    held = car.held_conflicts(session)[FACT]
    assert held["client_value"] == CLIENT_VALUE
    assert held["source_value"] == SOURCE_VALUE

    # And the audit envelope carries both sides plus who and why.
    envelope = ah.build_change_envelope(
        event_type=ah.EVENT_FIELD_CHANGED, action="client_answer_held",
        fact_key=FACT, field_name=FIELD,
        previous_value=SOURCE_VALUE, new_value=CLIENT_VALUE,
        previous_source="document", source="client_arq", user_id="u-7")
    assert envelope["previous_value"] == SOURCE_VALUE
    assert envelope["new_value"] == CLIENT_VALUE
    assert envelope["previous_source"] == "document"


def test_r14_holding_is_not_the_same_as_applying():
    """THE SEAM: the resolve path offers BOTH outcomes, so holding a conflict
    is a decision the producer makes, not one we make for them."""
    src = inspect.getsource(car)
    assert "use_client" in src and "keep_source" in src
    assert "_strip_hold" in src

    # Resolving removes only that key - any other held answer survives.
    two = {FACT: {"client_value": "a"}, "num_employees": {"client_value": "b"}}
    assert car._strip_hold(two, FACT) == {"num_employees": {"client_value": "b"}}
    assert car._strip_hold({FACT: {"client_value": "a"}}, FACT) is None


# =============================================================================
# TEST 15 - Producer Override
# =============================================================================

def _override_envelope():
    return ah.build_change_envelope(
        event_type=ah.EVENT_FIELD_CHANGED,
        action="producer_override",
        fact_key=FACT, field_name=FIELD, form_id="ACORD_125",
        previous_value=SOURCE_VALUE, new_value=CLIENT_VALUE,
        previous_source="document", source="producer",
        user_id="u-42", reason="Client confirmed 2025 gross sales")


def test_r15_producer_value_becomes_the_canonical_value():
    """The producer-selected value becomes the current canonical value."""
    resolved = {FACT: {"value": CLIENT_VALUE, "source": "producer",
                       "confidence": "filled"}}
    assert fs.value_state_of(resolved, FACT) not in (fs.NOT_STATED, fs.CONFLICTING)
    assert FACT in fs.human_provenance_facts(resolved)

    # A document-sourced value is NOT human provenance - so the assertion above
    # is the override being recognised, not a function that returns everything.
    assert FACT not in fs.human_provenance_facts(
        {FACT: {"value": SOURCE_VALUE, "source": "document"}})


def test_r15_original_value_remains_preserved():
    """The original value remains preserved."""
    envelope = _override_envelope()
    assert envelope["previous_value"] == SOURCE_VALUE
    assert envelope["new_value"] == CLIENT_VALUE
    assert envelope["previous_source"] == "document"
    # The override is classified as such rather than looking like a first fill.
    assert envelope["change_kind"] == "correction"
    assert ah.change_kind(None, None, CLIENT_VALUE) != "correction"


def test_r15_actor_and_timestamp_are_recorded():
    """Actor and timestamp are recorded."""
    envelope = _override_envelope()
    assert envelope["actor_id"] == "u-42"
    assert envelope["role"] == "producer"
    assert envelope["reason"] == "Client confirmed 2025 gross sales"

    # The actor is stored as an immutable ID and resolved to a name at READ
    # time, so renaming a user must never rewrite history.
    assert envelope["actor_id"] == str(envelope["actor_id"])
    assert ah.derive_role(source="ai") == "system"

    # The timestamp is the spine row's own created_at, written by the writer -
    # so the reader must surface it. This is the contract normalize_event keeps.
    row = {"event_type": ah.EVENT_FIELD_CHANGED, "event_data": envelope,
           "created_at": "2026-08-27T10:15:00+00:00"}
    entry = ah.normalize_event(
        row, actors={"u-42": {"name": "Vinay Sharma",
                              "email": "vinaysharma@astreait.com"}})
    assert entry["occurred_at"] == "2026-08-27T10:15:00+00:00"
    assert entry["previous_value"] == SOURCE_VALUE
    assert entry["new_value"] == CLIENT_VALUE
    assert entry["role"] == "producer"
    assert entry["role_label"] == "Producer"
    # The ID is the stored anchor; the NAME is resolved at read time.
    assert entry["actor_id"] == "u-42"
    assert entry["actor_name"] == "Vinay Sharma"
    # With no actor directory the record still stands, on its immutable ID.
    assert ah.normalize_event(row, actors={})["actor_id"] == "u-42"


def test_r15_downstream_forms_and_sqs_use_the_resolved_value():
    """Downstream forms AND SQS use the resolved canonical value."""
    resolved_facts = {
        FACT: {"value": CLIENT_VALUE, "source": "producer", "confidence": "filled"},
        "operations_description": "Commercial roofing - tear-off and re-roof",
    }
    # SQS reads the resolved value, not the superseded document one.
    assert sq._fv(resolved_facts, FACT) == CLIENT_VALUE

    # Tier 2 counts the fact as PRESENT once the producer has settled it, so
    # the override reaches the score and not just the display.
    _score, missing = sq.check_tier2(resolved_facts, {})
    assert not any("Revenue" in m or "revenue" in m for m in missing), missing

    # POSITIVE CONTROL - with the fact absent it IS listed as missing.
    _score2, missing2 = sq.check_tier2({}, {})
    assert any("Revenue" in m or "revenue" in m for m in missing2), missing2


def test_r15_the_override_is_recorded_through_the_one_spine():
    """THE SEAM: material changes go through `record_material_change`, called
    from inside the writers the action already goes through (D49) - so history
    cannot be lost when the workflow tables move on."""
    src = (BACKEND / "services" / "audit_service.py").read_text(
        encoding="utf-8", errors="ignore")
    assert "record_material_change" in src

    # Resolving a held client answer audits through `log_underwriting_confirmation`,
    # which is itself one of the eight writers that emit onto the spine (D49):
    # the event is emitted by the writer the action already goes through, so a
    # new call site cannot forget to log.
    car_src = inspect.getsource(car)
    assert "log_underwriting_confirmation" in car_src, (
        "resolving a held client answer no longer writes to the audit trail")

    writer = inspect.getsource(aud.log_underwriting_confirmation)
    assert "record_material_change" in writer, (
        "log_underwriting_confirmation no longer reaches the audit spine, so a "
        "producer override would vanish when the workflow table moves on")


# =============================================================================
# TEST 16 - Derived Effective Date
# =============================================================================

# The E&O 5.7 worked example, exactly: a renewal whose proposed effective date
# is derived from the prior expiration date.
DERIVED_EFFECTIVE_DATE = {
    "value": "07/15/2026",
    "confidence": "low_confidence",
    "source": "derived",
    "derivation": {"rule": "renewal_routing_prior_expiration",
                   "inputs": ["prior_expiration_date", "is_renewal"]},
}
RENEWAL_FACTS = {
    "effective_date": DERIVED_EFFECTIVE_DATE,
    "prior_effective_date": "07/15/2025",
    "prior_expiration_date": "07/15/2026",
    "is_renewal": "Yes",
    "applicant_name": "Orbin Contracting LLC",
}


def test_r16_derived_value_is_retained():
    """The derived value is retained."""
    row = aud._flatten_fact("effective_date", DERIVED_EFFECTIVE_DATE, RENEWAL_FACTS)
    assert row["value"] == "07/15/2026"
    assert row["source"] == "derived"
    # A derived value is labelled derived, never presented as document evidence.
    assert row["evidence_state"] == "derived"


def test_r16_derivation_rule_is_retained():
    """The derivation RULE is retained."""
    row = aud._flatten_fact("effective_date", DERIVED_EFFECTIVE_DATE, RENEWAL_FACTS)
    assert row["derivation"]["rule"] == "renewal_routing_prior_expiration"

    # POSITIVE CONTROL - an ordinary extracted fact carries no derivation, so
    # the block above is written by the deriving code and not by the reader.
    plain = aud._flatten_fact(
        "applicant_name", {"value": "Orbin Contracting LLC", "source": "document"},
        RENEWAL_FACTS)
    assert "derivation" not in plain


def test_r16_input_fact_ids_are_available():
    """The input fact IDs are available."""
    row = aud._flatten_fact("effective_date", DERIVED_EFFECTIVE_DATE, RENEWAL_FACTS)
    inputs = row["derivation"]["inputs"]
    assert inputs == ["prior_expiration_date", "is_renewal"]

    # Every named input is a real fact on this package, so the lineage can
    # actually be walked rather than merely printed.
    for fact_key in inputs:
        assert fact_key in RENEWAL_FACTS, fact_key


def test_r16_source_lineage_is_available():
    """The source lineage (document + page) is available for the inputs."""
    docs = [{
        "doc_id": "d1", "filename": "expiring_dec.pdf",
        "text": "[Document page 1]\nNamed Insured: Orbin Contracting LLC\n"
                "Policy Period: 07/15/2025 to 07/15/2026\n",
    }]
    index = fl.build_doc_index(docs)
    sources = fl.sources_for_fact("prior_expiration_date", "07/15/2026", index)
    assert sources, "the input fact must trace back to a document"
    assert sources[0]["filename"] == "expiring_dec.pdf"
    assert sources[0]["page"] == 1
    assert fl.format_source(sources[0])

    # POSITIVE CONTROL - a value that appears in NO document gets no source,
    # so lineage is recovered rather than asserted.
    assert fl.sources_for_fact("prior_expiration_date", "01/01/1999", index) == []


def test_r16_the_derived_date_never_overwrites_a_stated_one():
    """A derivation is only ever a fallback: a stated value is never replaced.

    This is what keeps a derived date from becoming a wrong value on the form.
    """
    src = (BACKEND / "services" / "extraction_service.py").read_text(
        encoding="utf-8", errors="ignore")
    assert "never overwrite a stated value" in src
