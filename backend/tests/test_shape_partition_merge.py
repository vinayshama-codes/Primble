"""Candidate ranking must consider the VALUE, not only how often it repeats.

`_score_value` ranks competing values for a fact as
`tier_weight * (log1p(repetitions) + confidence)`. `tier_weight` multiplies every
candidate of the same field equally, so it cancels out of the ordering - which
leaves a ranking containing NOTHING ABOUT THE VALUE ITSELF. The most-repeated
candidate wins, and on a declarations page the thing that repeats on every page
is the carrier's letterhead.

Two measurements behind this:
  * one extra repetition is worth log1p(2)-log1p(1) = 0.405, while the entire gap
    between `ai_high` (0.85) and `ai_low` (0.50) is 0.35 - a LOW-confidence value
    seen twice beats a HIGH-confidence value seen once;
  * nothing checked whether a candidate could even BE the thing, so a 7-digit
    string repeated three times beat a real 9-digit FEIN stated once.

This is a PARTITION, never a weight: shape-valid candidates rank ahead of ones
that cannot possibly be valid, and if none qualify the list is returned
untouched. It can only reorder; it can never drop the last value.

SHADOW BY DEFAULT. It reorders candidates for every scalar fact in the system,
and that blast radius earns real-document evidence before it changes output.
`SCORE_SHAPE_PARTITION=on` enforces; `off` silences.
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
os.environ.setdefault("OPENAI_API_KEY", "sk-offline-test")

import services.extraction_service as es                 # noqa: E402


@pytest.fixture(autouse=True)
def _restore_mode():
    before = os.environ.get("SCORE_SHAPE_PARTITION")
    yield
    if before is None:
        os.environ.pop("SCORE_SHAPE_PARTITION", None)
    else:
        os.environ["SCORE_SHAPE_PARTITION"] = before


def _merge(partials, mode):
    os.environ["SCORE_SHAPE_PARTITION"] = mode
    return es._merge_list_fields(partials, list_keys=[])["facts"]


def _chunks(field, *values):
    return [
        {"facts": {field: {"value": v, "confidence": c}}, "_chunk_idx": i}
        for i, (v, c) in enumerate(values)
    ]


# The client's case: an EMC ACCOUNT number repeated in a page header beats the
# real FEIN stated once.
FEIN_CHUNKS = _chunks(
    "fein",
    ("0482854", "ai_high"), ("0482854", "ai_high"), ("0482854", "ai_high"),
    ("84-2210987", "ai_low"),
)


def test_shadow_mode_does_not_change_the_result():
    """Default. The old winner still ships - only a log line changes."""
    assert _merge(FEIN_CHUNKS, "shadow")["fein"]["value"] == "0482854"


def test_enforced_mode_prefers_the_only_valid_fein():
    assert _merge(FEIN_CHUNKS, "on")["fein"]["value"] == "84-2210987"


def test_off_mode_is_identical_to_shadow_output():
    assert _merge(FEIN_CHUNKS, "off")["fein"]["value"] == "0482854"


def test_a_value_is_never_lost_when_every_candidate_is_invalid():
    """THE LOAD-BEARING GUARANTEE. Partitioning must never empty the list."""
    chunks = _chunks("fein", ("0482854", "ai_high"), ("123", "ai_low"))
    assert _merge(chunks, "on")["fein"]["value"] == "0482854"


def test_a_single_candidate_is_never_touched():
    chunks = _chunks("fein", ("0482854", "ai_high"))
    assert _merge(chunks, "on")["fein"]["value"] == "0482854"


def test_facts_without_a_hard_shape_are_untouched():
    """Only four validators are enforced. Everything else keeps the existing
    frequency ranking exactly as it was."""
    chunks = _chunks(
        "applicant_name",
        ("Orbin Contracting LLC", "ai_high"),
        ("Orbin Contracting LLC", "ai_high"),
        ("ORBIN", "ai_high"),
    )
    assert _merge(chunks, "on")["applicant_name"]["value"] == "Orbin Contracting LLC"


@pytest.mark.parametrize("field,bad,good", [
    ("contact_email", "ERIN ROYAL", "erin@crsinc.com"),
    ("producer_contact_email", "Claim Reporting: (888) 362-2255", "erin@crsinc.com"),
    ("contact_phone", "ERIN ROYAL", "303-996-7800"),
    ("applicant_website", "not a website at all", "www.orbincontracting.com"),
])
def test_each_hard_shape_prefers_a_valid_candidate(field, bad, good):
    """The bad value is repeated twice so it wins on frequency today."""
    chunks = _chunks(field, (bad, "ai_high"), (bad, "ai_high"), (good, "ai_low"))
    assert _merge(chunks, "shadow")[field]["value"] == bad
    assert _merge(chunks, "on")[field]["value"] == good


def test_the_enforced_set_is_small_and_deliberate():
    """STANDING GUARD. Currency and date validators must NEVER be enforced here:
    C22's ~49,000-pair sweep established that an amount box legitimately holds
    "Statutory", "Included" or "See schedule". Currency ordering belongs to the
    C23 composite-consistency logic, not to this partition."""
    enforced = set(es._hard_shape_facts())
    assert enforced == {
        "fein", "contact_email", "contact_phone", "applicant_website",
        "carrier_website", "producer_contact_email", "producer_contact_phone",
        "producer_fax",
    }, sorted(enforced)
    for currency_fact in ("gl_each_occurrence", "total_revenue", "umbrella_limit"):
        assert currency_fact not in enforced


def test_partition_is_stable_within_each_group():
    """Ordering among equally-valid candidates must not change - that ordering
    carries the existing frequency and confidence ranking, and C23's currency
    logic runs on top of it."""
    scored = [("b", 2.0, {}), ("a", 1.0, {}), ("c", 0.5, {})]
    assert es._partition_by_shape("applicant_name", scored) == scored


def test_partition_helper_survives_a_broken_validator(monkeypatch):
    """A detector fault must never break a merge."""
    def _boom(_v):
        raise RuntimeError("bad validator")
    monkeypatch.setitem(es._hard_shape_facts(), "fein", _boom)
    scored = [("0482854", 2.0, {}), ("84-2210987", 1.0, {})]
    assert es._partition_by_shape("fein", scored) == scored
