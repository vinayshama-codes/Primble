"""Explicit No is reachable from a DOCUMENT (client 1.3, C1-Q FIX 6).

Client 1.3 lists six value states and gives three examples of "Explicit No /
Absent" - *No prior losses*, *No subcontracting*, *No Property coverage*.

All three landed as **Not Stated**. `explicit_no` was only reachable from a
human answer or from a literal negation STRING, so the distinction the client
asked for could not be expressed by any document.

Two grounded routes now exist, and NEITHER weakens defect B8 (a certificate
that never mentioned subcontractors produced `false`, which manufactured a
cross-document conflict and an 85 cap):

  1. A fact whose extraction contract is `boolean or null` - the model is told
     to answer null when the document is silent - so `false` IS the document
     saying no.
  2. A flag that AFFIRMATIVELY asserts absence (`asserts_no_known_losses` is
     true "ONLY if the document affirmatively states the insured has had NO
     prior or known losses").

Everything else stays `not_stated`. Turning silence into a No is the one
direction the client forbids (Principle 3).
"""
import pytest

from services.extraction_service import (
    TRISTATE_BOOLEAN_FACTS, ABSENCE_ASSERTION_FLAGS,
)
from services.fact_state import (
    derive_value_state, annotate_fact_states,
    EXPLICIT_NO, NOT_STATED, PRESENT,
)

DOC = {"source": "policy_doc_text", "confidence": "deterministic"}


# ── 1. Tri-state facts ───────────────────────────────────────────────────────

@pytest.mark.parametrize("key", sorted(TRISTATE_BOOLEAN_FACTS))
def test_a_tristate_false_from_a_document_is_an_explicit_no(key):
    assert derive_value_state(key, {**DOC, "value": False}) == EXPLICIT_NO


@pytest.mark.parametrize("key", sorted(TRISTATE_BOOLEAN_FACTS))
def test_a_tristate_null_is_still_not_stated(key):
    assert derive_value_state(key, {**DOC, "value": None}) == NOT_STATED


@pytest.mark.parametrize("key", sorted(TRISTATE_BOOLEAN_FACTS))
def test_a_tristate_true_is_present(key):
    assert derive_value_state(key, {**DOC, "value": True}) == PRESENT


def test_the_tristate_set_is_derived_from_the_schema_not_hand_listed():
    """ANTI-ROT. A hand list drifts from the prompt the moment someone edits
    the schema, and the failure is silent in the dangerous direction: a field
    demoted to a bare boolean would keep turning silence into a No."""
    import re
    import services.extraction_service as es
    expected = set(re.findall(r'"([a-z_][a-z0-9_]*)":\s*boolean or null',
                              es._EXTRACT_SCHEMA))
    assert set(TRISTATE_BOOLEAN_FACTS) == expected
    assert expected, "the schema no longer declares any tri-state boolean"


# ── 2. B8 must not come back ─────────────────────────────────────────────────

@pytest.mark.parametrize("key", [
    "has_property_coverage", "has_workers_comp", "has_umbrella",
    "has_crime", "auto_has_hired_nonowned", "gl_is_claims_made",
    "property_has_bi_coverage", "wc_multi_state",
])
def test_a_bare_boolean_false_is_still_not_stated(key):
    """THE B8 GUARD. These are declared as a plain `boolean` in the schema, so
    `false` is indistinguishable from "the document never mentioned it"."""
    assert key not in TRISTATE_BOOLEAN_FACTS
    assert derive_value_state(key, {**DOC, "value": False}) == NOT_STATED


def test_a_human_false_is_still_an_explicit_no():
    """Unchanged: a person answering "no" has answered, whatever the schema
    says about the field."""
    assert derive_value_state(
        "has_subcontractors", {"value": False, "source": "client_arq"}) == EXPLICIT_NO


# ── 3. The absence assertion - the client's own first example ────────────────

def _facts(value, asserted):
    return {"loss_history": {**DOC, "value": value},
            "_flags": {"asserts_no_known_losses": asserted}}


def test_no_known_losses_makes_the_loss_facts_an_explicit_no():
    f = _facts(None, True)
    for key in ABSENCE_ASSERTION_FLAGS["asserts_no_known_losses"]:
        assert derive_value_state(key, {**DOC, "value": None}, f) == EXPLICIT_NO


def test_the_flag_being_false_asserts_nothing():
    f = _facts(None, False)
    assert derive_value_state("loss_history", f["loss_history"], f) == NOT_STATED


def test_a_missing_flag_asserts_nothing():
    f = {"loss_history": {**DOC, "value": None}}
    assert derive_value_state("loss_history", f["loss_history"], f) == NOT_STATED


def test_a_real_claim_always_beats_the_assertion():
    """Positive evidence only, in both directions: a fact that HAS a value is
    evidence in its own right and can never be overruled by a flag."""
    f = _facts([{"date": "03/28/2024", "paid": "$4,850"}], True)
    assert derive_value_state("loss_history", f["loss_history"], f) == PRESENT


def test_an_unrelated_fact_is_untouched_by_the_loss_assertion():
    f = _facts(None, True)
    assert derive_value_state("total_payroll", {**DOC, "value": None}, f) == NOT_STATED


def test_every_asserted_key_is_a_real_fact_key():
    """A mapping onto a key nothing writes is a silent no-op."""
    from services.fact_registry import FACT_REGISTRY
    import services.extraction_service as es
    for flag, keys in ABSENCE_ASSERTION_FLAGS.items():
        assert f'"{flag}"' in es._EXTRACT_SCHEMA, f"{flag} is not in the schema"
        for k in keys:
            assert k in FACT_REGISTRY or f'"{k}"' in es._EXTRACT_SCHEMA, (
                f"{flag} asserts about {k}, which nothing produces")


# ── 4. The annotation pass carries the flags without persisting them ────────

def test_annotate_uses_the_flags_and_leaves_facts_clean():
    facts = {"loss_history": {**DOC, "value": None}}
    annotate_fact_states(facts, {"asserts_no_known_losses": True})
    assert facts["loss_history"]["value_state"] == EXPLICIT_NO
    assert "_flags" not in facts, "the flags must not be persisted onto facts"


def test_annotate_without_flags_still_works():
    facts = {"loss_history": {**DOC, "value": None}}
    annotate_fact_states(facts)
    assert facts["loss_history"]["value_state"] == NOT_STATED
    assert "_flags" not in facts
