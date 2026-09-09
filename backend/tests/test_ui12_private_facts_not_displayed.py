"""UI-12 - the "Review extracted data" popup must never print pipeline machinery.

CLIENT REPORT (UI-12, live test 2026-09-01): the extracted-data popup on the
pre-form screen opened with a row headed **MERGE REJECTED** followed by a wall
of unpunctuated values - "reads like an internal processing/debug state rather
than a useful user explanation".

ROOT CAUSE: `_merge_rejected` is the merge's private note of the candidate
values it did NOT elect. `merge_facts` consumes it (via
`_flag_intra_document_limit_conflicts`) and pops it at the package level, but
the per-DOCUMENT path never does, so it stays in `doc["facts"]`. The endpoint
then walked every key in that dict with no filter, and the popup's CSS
uppercased the humanised label:

    "_merge_rejected"  ->  "Merge Rejected"  ->  MERGE REJECTED

The leading underscore is this codebase's marker for "machinery, not a fact",
and roughly twenty other generic walkers already honour it - `audit_service`
shipped the identical fix on 2026-08-26 after junk rows like
"_scoped: [structured value]" reached the same client. This popup was the last
generic walker over `facts` that did not.

SUPPRESSED, NOT DELETED - and that distinction is what
`test_the_private_note_still_reaches_its_real_consumer` exists to pin. The note
is the INPUT to the Data Consistency picker, which is the plain-language "let
the user choose" that UI-12 asks for in place of the raw dump. A fix that
stripped the key at extraction would have silenced that picker on
single-document packages: a fix that breaks the feature the client wants.
"""
import os
import pathlib
import re
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("OPENAI_API_KEY", "sk-offline")

from routes.form_routes import _document_fact_rows          # noqa: E402

BACKEND = pathlib.Path(__file__).resolve().parent.parent


def _env(value, **extra):
    """A fact as extraction really stores it - an annotated envelope."""
    return {"value": value, "source": "ai", "confidence": "ai_high", **extra}


# ── The client's literal run ────────────────────────────────────────────────
#
# Taken verbatim from the reproduction session's stored per-document facts, not
# invented: a fix can pass every synthetic test and still fail the reported case
# (standing rule - replay the client's LITERAL values).

LIVE_MERGE_REJECTED = {
    "entity_type":          ["LLC"],
    "policy_number":        ["UMB-2026-6J7402"],
    "total_revenue":        ["$5,240,000"],
    "total_policy_premium": ["$3,418.00"],
}

LIVE_FACTS = {
    "_merge_rejected":          LIVE_MERGE_REJECTED,
    "applicant_name":           _env("Halloran Freight Services LLC"),
    "carrier_name":             _env("Sentinel Ridge Mutual Insurance Company"),
    "policy_number":            _env("PKG-2026-118840"),
    "total_revenue":            _env("$4,850,000"),
    "total_policy_premium":     _env("$10,663.00"),
    "gl_each_occurrence":       _env("$1,000,000"),
    "gl_aggregate":             _env("$2,000,000"),
    "umbrella_limit":           _env("$3,000,000"),
    "entity_type":              _env("Limited Liability Company"),
    # Real extracted "no" answers. They LOOK like debug output and are not:
    # extraction wraps a genuine boolean answer in an envelope as the string
    # "False" with an explicit value_state. They must keep rendering.
    "agreed_value_endorsement": _env("False", value_state="explicit_no"),
    "cyber_controls_mfa":       _env("False", value_state="explicit_no"),
    "num_employees":            _env("34"),
    "years_in_business":        _env("17"),
}


def test_the_reported_row_is_gone():
    rows = _document_fact_rows(LIVE_FACTS)
    assert not [r for r in rows if r["key"].startswith("_")], \
        f"a private key still renders: {[r['key'] for r in rows if r['key'].startswith('_')]}"
    labels = {r["label"] for r in rows}
    assert "Merge Rejected" not in labels
    # The popup uppercases the label, which is how the client saw it.
    assert not any("MERGE REJECTED" in r["label"].upper() for r in rows)


def test_no_losing_value_leaks_through_any_row():
    """Not just the label - the VALUES the note carried must not print either.

    Necessary because the same amounts are legitimate values of OTHER facts in
    the same run ($5,240,000 is the audited gross sales). So this asserts the
    losing values do not appear under a key that never held them, rather than
    that the strings are absent from the payload entirely.
    """
    rows = {r["key"]: r["value"] for r in _document_fact_rows(LIVE_FACTS)}
    assert rows["total_revenue"] == "$4,850,000"          # the elected value
    assert rows["policy_number"] == "PKG-2026-118840"
    assert rows["total_policy_premium"] == "$10,663.00"
    assert rows["entity_type"] == "Limited Liability Company"


def test_every_real_fact_still_renders_unchanged():
    """No collateral. Same rows, same labels, same values, same order."""
    rows = _document_fact_rows(LIVE_FACTS)
    expected_keys = sorted(
        (k for k in LIVE_FACTS if not k.startswith("_")),
        key=lambda k: k.replace("_", " ").title(),
    )
    assert [r["key"] for r in rows] == expected_keys
    assert len(rows) == len(LIVE_FACTS) - 1               # exactly one dropped
    for r in rows:
        assert r["confidence"] == "ai_high"
        assert r["label"] == r["key"].replace("_", " ").title()


def test_a_real_no_answer_is_not_mistaken_for_debug_output():
    """`agreed_value_endorsement: False` is an ANSWER, not machinery.

    It reads like debug output and is not - `audit_service` drops BARE python
    bools for that reason, but these arrive as envelopes carrying an explicit
    `value_state`. Dropping them would blank real extracted answers, which is
    the opposite of the standing blank-over-wrong rule.
    """
    rows = {r["key"]: r["value"] for r in _document_fact_rows(LIVE_FACTS)}
    assert rows["agreed_value_endorsement"] == "False"
    assert rows["cyber_controls_mfa"] == "False"


def test_only_a_LEADING_underscore_is_private():
    """Every real fact key contains underscores. Only the first one counts."""
    rows = _document_fact_rows({
        "gl_each_occurrence": _env("$1,000,000"),
        "wc_payroll_by_state": _env("OH: $2,100,000"),
        "_scoped": {"carrier_name": ["x"]},
    })
    assert [r["key"] for r in rows] == ["gl_each_occurrence", "wc_payroll_by_state"]


def test_empty_and_missing_facts_are_not_an_error():
    assert _document_fact_rows({}) == []
    assert _document_fact_rows(None) == []
    # A private key on its own must not produce a one-row popup either.
    assert _document_fact_rows({"_merge_rejected": LIVE_MERGE_REJECTED}) == []


# ── Anti-rot ────────────────────────────────────────────────────────────────
#
# An anti-rot harvester is only as wide as the emission path it walks (standing
# lesson, BUG-05). So this HARVESTS the private keys the pipeline really writes
# out of the source, instead of listing the ones known today - a private key
# added next month is covered without anyone remembering this file exists.

_PRIVATE_WRITE_RE = re.compile(
    r"""(?:facts|mf|merged_facts)\s*"""
    r"""(?:\[|\.get\(|\.setdefault\(|\.pop\()\s*["'](_[a-z][a-z0-9_]*)["']"""
)
# Some are written through a module constant (`LINE_RECORDS_KEY = "_line_records"`).
_PRIVATE_CONST_RE = re.compile(
    r"""(?m)^[A-Z][A-Z0-9_]*KEY\s*=\s*["'](_[a-z][a-z0-9_]*)["']"""
)


def _harvest_private_fact_keys() -> set:
    found = set()
    for folder in ("services", "routes"):
        for path in (BACKEND / folder).glob("*.py"):
            src = path.read_text(encoding="utf-8", errors="ignore")
            found |= set(_PRIVATE_WRITE_RE.findall(src))
            found |= set(_PRIVATE_CONST_RE.findall(src))
    return found


def test_the_harvester_actually_harvests():
    """Guard against a vacuous pass.

    A regex that silently stops matching would make the test below succeed over
    a broken filter - exactly the trap the coverage test fell into in C25. The
    floor is deliberately below today's count so an ordinary refactor does not
    fail the build, but a dead regex does.
    """
    keys = _harvest_private_fact_keys()
    assert len(keys) >= 6, f"harvester found only {sorted(keys)} - the regex has rotted"
    assert "_merge_rejected" in keys, "the reported key is no longer harvested"


@pytest.mark.parametrize("key", sorted(_harvest_private_fact_keys()))
def test_no_private_key_the_pipeline_writes_can_reach_the_popup(key):
    rows = _document_fact_rows({
        key: {"some_field": ["a value"]},
        "applicant_name": _env("Halloran Freight Services LLC"),
    })
    assert [r["key"] for r in rows] == ["applicant_name"], \
        f"{key} rendered as a user-facing row"


def test_the_endpoint_still_goes_through_this_door():
    """Fix the layer the screen reads.

    The filter lives in `_document_fact_rows`; the value of every test above is
    zero if the route quietly grows its own inline loop again. This fails the
    build if `get_document_extracted_data` stops calling the shared helper.
    """
    src = (BACKEND / "routes" / "form_routes.py").read_text(encoding="utf-8")
    start = src.index("async def get_document_extracted_data")
    body = src[start:src.index("\n@router.", start)]
    assert "_document_fact_rows(" in body, \
        "the extracted-data endpoint no longer builds its rows through the one door"
    assert "for key, raw in facts.items()" not in body, \
        "the endpoint has grown an inline fact loop again - it will bypass the filter"


def test_the_private_note_still_reaches_its_real_consumer():
    """The note must still be COMPUTED. Only its display was the defect.

    `_merge_rejected` is what tells `_flag_intra_document_limit_conflicts` that a
    document disagreed with itself, which is what raises the Data Consistency
    question the client asked for. If a later change strips it at extraction to
    "clean up the facts", this fails.
    """
    from services.extraction_service import (
        _LONG_DOC_LIST_KEYS, _flag_intra_document_limit_conflicts,
        _merge_list_fields,
    )

    merged = _merge_list_fields(
        [{"_chunk_idx": 0, "flags": {}, "facts": {"umbrella_limit": "$3,000,000"}},
         {"_chunk_idx": 1, "flags": {}, "facts": {"umbrella_limit": "$1,000,000"}}],
        list_keys=list(_LONG_DOC_LIST_KEYS),
    )
    facts = merged.get("facts") or {}
    rejected = facts.get("_merge_rejected") or {}
    assert rejected.get("umbrella_limit"), \
        "the merge no longer records the value it did not elect"

    _flag_intra_document_limit_conflicts(facts, rejected)
    assert "umbrella_limit" in (facts.get("_uw_conflicted_keys") or []), \
        "the conflict is no longer withheld for the picker"

    # ... and it is still invisible to the popup.
    assert not [r for r in _document_fact_rows(facts) if r["key"].startswith("_")]
