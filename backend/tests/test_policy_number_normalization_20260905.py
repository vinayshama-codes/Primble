"""SYS-07's broader clause, one fact type over: POLICY-NUMBER FORMATTING.

The acceptance criteria names it explicitly - *"part of the broader
normalization requirement that also applies to dates, addresses, POLICY-NUMBER
FORMATTING, and other equivalent values"* - and the picker was still asking a
producer to choose between one policy and itself.

ROOT CAUSE, IDENTICAL TO SYS-07'S OWN: the comparator existed and was correct
(`same_policy_contract`, shipped with SYS-06) and NOTHING ROUTED TO IT. The
Data Consistency picker merges through `_merge_equivalent_value_groups` ->
`fact_equivalence.equivalent_index` -> `same_fact`, whose KIND_IDENTIFIER
branch was exact-alnum equality and whose own comment said proving a prefix
"needs the canonical joiner ... applied upstream". SYS-06 had already built
that proof; the branch never learned. The rule now lives in `fact_equivalence`
with `fact_comparison.same_policy_contract` delegating to it - ONE
implementation, and the import direction unchanged.
"""
import pytest

from services import fact_comparison as fc
from services import fact_equivalence as fe
from services.normalization import is_policy_number_field, strip_leading_label
from services.underwriting_consistency import assess_underwriting_consistency


def _card(fact_key, *values):
    """True when the producer is shown a "documents disagree" card."""
    docs = [{"doc_id": str(i), "filename": f"d{i}.pdf", "doc_type": "policy",
             "text": "", "facts": {"applicant_name": "X LLC", fact_key: v}}
            for i, v in enumerate(values)]
    out = assess_underwriting_consistency(docs, dict(docs[0]["facts"]), {})
    return bool([f for f in out["fields"] if f.get("review_required")])


# ── the client's own package ────────────────────────────────────────────────

@pytest.mark.parametrize("a,b", [
    ("BBC7263", "BBC7263 - 26"),        # dec page vs certificate, LIVE shape
    ("6E74002", "6E7-40-02---26"),      # the 2026-08-17 ACORD 125 Q4 shape
    ("BBC7263", "Policy No. BBC7263"),  # the value carrying its own label
    ("BBC7263", "bbc7263"),
    ("6E7-40-02-26", "6E7 40 02 26"),
])
def test_one_policy_printed_two_ways_asks_no_question(a, b):
    assert fc.compare("policy_number", [a, b]).verdict in ("equivalent", "single")
    assert _card("policy_number", a, b) is False


def test_three_printings_of_one_policy_collapse_to_one():
    assert _card("policy_number", "BBC7263", "BBC7263 - 26",
                 "Policy No. BBC7263") is False


# ── and what must STILL be a conflict ───────────────────────────────────────

@pytest.mark.parametrize("a,b", [
    ("BBC7263", "BBC7264"),             # one character apart, two policies
    ("POL123", "POL12345"),             # digits run together - NOT a term
    ("BBC7263-26", "GL-4471102-26"),    # defect D-1: two carriers' GL policies
    ("BBC7263", "BBC7263 - 261"),       # a 3-digit tail is not a term marker
])
def test_two_real_policies_are_still_two(a, b):
    assert fc.compare("policy_number", [a, b]).verdict == "conflict"
    assert _card("policy_number", a, b) is True


def test_a_term_marker_must_have_been_printed_separated():
    """The ONE condition that keeps this from being a loose prefix match."""
    assert fc.same_policy_contract("BBC7263", "BBC7263 - 26") is True
    assert fc.same_policy_contract("BBC726326", "BBC72632699") is False


def test_a_certificate_number_is_not_a_policy_contract():
    """A certificate is not the contract, so the term-marker rule must not
    reach it - the gate is the FIELD, derived from its own tokens."""
    assert is_policy_number_field("certificate_number") is False
    assert fc.compare("certificate_number",
                      ["BBC7263", "BBC7263 - 26"]).verdict == "conflict"


# ── the structure that keeps it from drifting back ──────────────────────────

def test_there_is_exactly_one_implementation():
    """`fact_comparison.same_policy_contract` must DELEGATE. Two copies of one
    rule is how the Umbrella SIR and auto-symbol bugs each survived their first
    fix, and it is why this defect existed at all: the correct rule in one
    module, an exact-equality copy of the question in another."""
    import inspect
    src = inspect.getsource(fc.same_policy_contract)
    assert "_fe._same_policy_contract" in src
    assert "_POLICY_TERM_TAIL_RE" not in src, (
        "the term-marker regex is back in fact_comparison - that is a second "
        "implementation")


@pytest.mark.parametrize("key,expected", [
    ("policy_number", True), ("prior_policy_number", True),
    ("umbrella_policy_number", True), ("policy_number@auto", True),
    ("certificate_number", False), ("carrier_name", False),
    ("policy_effective_date", False), ("fein", False),
])
def test_the_policy_number_field_test_is_derived_not_a_list(key, expected):
    assert is_policy_number_field(key) is expected


@pytest.mark.parametrize("value,expected", [
    ("Policy No. BBC7263", "BBC7263"),
    ("Policy Number: BBC7263", "BBC7263"),
    ("Cert No BBC7263", "BBC7263"),
    ("BBC7263", "BBC7263"),
    ("POLICY-123", "POLICY-123"),   # no space: part of the number, not a label
])
def test_a_printed_label_is_stripped_and_nothing_else_is(value, expected):
    assert strip_leading_label(value) == expected


def test_the_rule_reaches_the_layer_the_picker_actually_uses():
    """THE WHOLE BUG. `equivalent_index` is what the picker merges through -
    not `compare`. A fix that only taught `compare` would pass every unit test
    and change nothing on screen (the same trap as the AAIS guard, which was
    inert in `normalize_value` for exactly this reason)."""
    assert fe.equivalent_index("policy_number", ["BBC7263", "BBC7263 - 26"])
    assert not fe.equivalent_index("policy_number", ["BBC7263", "BBC7264"])
