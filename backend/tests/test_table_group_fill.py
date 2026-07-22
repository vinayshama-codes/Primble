"""
Regression tests for multi-column repeating-TABLE handling in the gap-fill
prompt builder (services/pdf_service.py::_fill_unmatched_with_gpt).

Root cause this covers: ACORD 140's Premises Information schedule is really
ONE table with several DIFFERENT columns (SubjectOfInsuranceCode, LimitAmount,
CoinsurancePercent, DeductibleAmount, FormsAndConditions, ...) all repeating
over the SAME row letters. Before this fix, each column was treated as an
INDEPENDENT "find N distinct values" search with no awareness of its sibling
columns - a live multi-location property test showed this produces exactly
the failure mode you'd expect: a genuine 2nd distinct LimitAmount bled into
the unrelated DeductibleAmount column instead of staying null, and unrelated
document text landed in a free-text "FormsAndConditions" column. Splitting
across separate LLM calls (the batcher) made it structurally impossible to
fix with prompt wording alone, since columns in different calls never see
each other's data.

These tests verify, using the REAL ACORD 140 schema (not a synthetic
fixture) and a mocked OpenAI client (no network / no API key required):
  1. All of a table's columns are sent in ONE LLM call, never split.
  2. The prompt renders ONE combined "TABLE" block for them, not N separate
     "REPEATING GROUP" blocks.
  3. A field family that does NOT form a real table (e.g. a lone 2-slot
     group) is completely unaffected - still renders as an ordinary
     REPEATING GROUP, proving this is additive, not a rewrite.

Run from backend/:
    python tests/test_table_group_fill.py
or:
    python -m pytest tests/test_table_group_fill.py -v
"""

import json
import os
import sys
from unittest.mock import AsyncMock, MagicMock, patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import services.pdf_service as pdf_service  # noqa: E402

_SCHEMA_PATH = os.path.join(os.path.dirname(__file__), "..", "forms_schemas", "ACORD_140_schema.json")
with open(_SCHEMA_PATH, encoding="utf-8") as _f:
    _ACORD_140_SCHEMA = json.load(_f)

# Real Premises Information table columns (see field_qa/pdf_service audit) -
# 6 distinct column bases, each with slots A/B in this test (a subset of the
# real A,B,C,D,E,G,H,I,J,K to keep the test fast).
_PREMISES_COLUMN_BASES = [
    "CommercialProperty_Premises_SubjectOfInsuranceCode",
    "CommercialProperty_Premises_LimitAmount",
    "CommercialProperty_Premises_CoinsurancePercent",
    "CommercialProperty_Premises_DeductibleAmount",
    "CommercialProperty_Premises_FormsAndConditions",
    "CommercialProperty_Premises_ValuationCode",
]


def _build_unmatched_fields():
    fields = {}
    for base in _PREMISES_COLUMN_BASES:
        for row in ("A", "B"):
            key = f"{base}_{row}"
            assert key in _ACORD_140_SCHEMA, f"schema drifted - {key} no longer exists"
            fields[key] = _ACORD_140_SCHEMA[key]
    # A genuine non-table pair (only 2 columns share this exact shape+prefix in
    # the real schema) - must NOT be swept into a table, since <3 co-occurring
    # columns is deliberately left as ordinary independent-column behavior.
    for row in ("A", "B"):
        key = f"CommercialProperty_Spoilage_LimitAmount_{row}"
        assert key in _ACORD_140_SCHEMA, f"schema drifted - {key} no longer exists"
        fields[key] = _ACORD_140_SCHEMA[key]
        key2 = f"CommercialProperty_Spoilage_DeductibleAmount_{row}"
        fields[key2] = _ACORD_140_SCHEMA[key2]
    return fields


def _fake_openai_client(captured_messages):
    """A stand-in for the SYNC OpenAI client - captures every `messages` kwarg
    passed to chat.completions.create and returns a minimal valid JSON reply.

    Sync (not AsyncMock) on purpose: the gap-fill pass runs its calls on
    ThreadPoolExecutor worker threads and therefore uses the synchronous client
    (`_get_openai_form_fill_client_sync`). It previously wrapped an async client
    in `asyncio.run()` per call, which shared one AsyncOpenAI/httpx.AsyncClient
    across a fresh event loop per call and could deadlock a worker forever.
    """
    def _create(**kwargs):
        captured_messages.append(kwargs.get("messages"))
        resp = MagicMock()
        resp.choices = [MagicMock()]
        resp.choices[0].message.content = json.dumps({"values": {}, "raw_text_sourced": []})
        return resp

    client = MagicMock()
    client.chat.completions.create = MagicMock(side_effect=_create)
    return client


def test_table_columns_sent_in_a_single_llm_call():
    captured = []
    with patch.object(pdf_service, "_get_openai_form_fill_client_sync", return_value=_fake_openai_client(captured)):
        pdf_service._fill_unmatched_with_gpt(
            _build_unmatched_fields(),
            facts={},
            form_id="ACORD_140",
            raw_text="Location 1: Building, $3,150,000. Location 2: Building, $2,480,000.",
        )
    # The 6-column x 2-row table (12 fields) must be ONE atomic batch - i.e.
    # exactly one call carries ALL of them together (the compliance pass and
    # any other calls are separate concerns, so we check that at least one
    # call's prompt contains every table field, not that there's only one
    # call in total).
    assert captured, "no LLM calls were made at all"
    user_msgs = [m[1]["content"] for m in captured if len(m) > 1]
    table_fields = [f"{b}_{r}" for b in _PREMISES_COLUMN_BASES for r in ("A", "B")]
    matching_calls = [
        msg for msg in user_msgs
        if all(f in msg for f in table_fields)
    ]
    assert matching_calls, (
        "no single LLM call contained all 12 table fields together - "
        "the table was split across separate calls, which defeats the fix"
    )


def test_prompt_renders_one_table_block_not_six_repeating_groups():
    captured = []
    with patch.object(pdf_service, "_get_openai_form_fill_client_sync", return_value=_fake_openai_client(captured)):
        pdf_service._fill_unmatched_with_gpt(
            _build_unmatched_fields(),
            facts={},
            form_id="ACORD_140",
            raw_text="Location 1: Building, $3,150,000. Location 2: Building, $2,480,000.",
        )
    user_msgs = [m[1]["content"] for m in captured if len(m) > 1]
    combined = "\n".join(user_msgs)
    assert "TABLE 'CommercialProperty_Premises'" in combined, "expected the combined table block to be rendered"
    # None of the 6 columns should ALSO get their own independent REPEATING
    # GROUP header - that would mean the table detection didn't actually
    # divert them.
    for base in _PREMISES_COLUMN_BASES:
        assert f"REPEATING GROUP '{base}'" not in combined, (
            f"{base} still rendered as an independent REPEATING GROUP - "
            "table-group routing did not take effect"
        )


def test_already_filled_row_is_surfaced_and_excluded_from_active_fields():
    """The exact live bug: row A resolved by Pass 1 (_resolve_subject_of_
    insurance_row) never reaches this function's field list at all - so
    without `already_filled`, the model has no way to know a real entry
    (Location 1, $3,150,000) was already captured, and duplicates it into
    row B instead of moving on to Location 2. Verifies the prompt now tells
    the model row A is already spoken for, with its real captured value."""
    # Row A deliberately OMITTED from `unmatched` (mirrors compute_form_gaps
    # removing a deterministically-resolved field before gap-fill ever sees
    # it) - only rows B and C are genuinely being asked about.
    unmatched = {}
    for base in _PREMISES_COLUMN_BASES:
        for row in ("B", "C"):
            key = f"{base}_{row}"
            assert key in _ACORD_140_SCHEMA, f"schema drifted - {key} no longer exists"
            unmatched[key] = _ACORD_140_SCHEMA[key]
    already_filled = {
        "CommercialProperty_Premises_SubjectOfInsuranceCode_A": "Building",
        "CommercialProperty_Premises_LimitAmount_A": "$3,150,000",
        "CommercialProperty_Premises_CoinsurancePercent_A": "80%",
        "CommercialProperty_Premises_ValuationCode_A": "RCV",
    }
    captured = []
    with patch.object(pdf_service, "_get_openai_form_fill_client_sync", return_value=_fake_openai_client(captured)):
        pdf_service._fill_unmatched_with_gpt(
            unmatched,
            facts={},
            form_id="ACORD_140",
            raw_text="Location 1: Building, $3,150,000. Location 2: Building, $2,480,000.",
            already_filled=already_filled,
        )
    user_msgs = [m[1]["content"] for m in captured if len(m) > 1]
    combined = "\n".join(user_msgs)
    assert "already filled" in combined.lower(), "expected the already-filled row A hint to be rendered"
    assert "$3,150,000" in combined, "expected row A's actual captured value to be shown as context"
    normalized = " ".join(combined.lower().split())
    assert "not already captured" in normalized, "expected the RULE text to reference already-captured rows"
    # Row A must never be listed as one of the fillable slots for this call.
    assert "CommercialProperty_Premises_LimitAmount_A" not in combined
    assert "CommercialProperty_Premises_LimitAmount_B" in combined
    assert "CommercialProperty_Premises_LimitAmount_C" in combined


def test_no_already_filled_context_behaves_exactly_as_before():
    """already_filled defaulting to None/empty must be a complete no-op - the
    "Rows already captured" section is absent and the table renders exactly
    as it did before this fix, for the overwhelming majority of calls that
    have no such context to give."""
    captured = []
    with patch.object(pdf_service, "_get_openai_form_fill_client_sync", return_value=_fake_openai_client(captured)):
        pdf_service._fill_unmatched_with_gpt(
            _build_unmatched_fields(),
            facts={},
            form_id="ACORD_140",
            raw_text="Location 1: Building, $3,150,000. Location 2: Building, $2,480,000.",
        )
    user_msgs = [m[1]["content"] for m in captured if len(m) > 1]
    combined = "\n".join(user_msgs)
    assert "already filled" not in combined.lower()
    assert "already captured" not in combined.lower()


def test_table_survives_columns_with_different_active_row_sets():
    """The exact live production bug (confirmed via server logs 2026-07-17):
    different columns of the SAME real table had DIFFERENT unmatched
    row-letter sets - SubjectOfInsuranceCode/LimitAmount were unmatched for
    row A too (property_locations extraction gave no usable data), while
    CoinsurancePercent/ValuationCode/DeductibleAmount had row A ALREADY
    resolved by a separate scalar-fact rule and were only unmatched for rows
    B/C onward. The OLD bucketing (keyed on an EXACT row-letter-set match)
    fragmented this into 4 separate buckets, none reaching the >=3-column
    table threshold with row A visible - so the columns that actually caused
    the duplication never got row-oriented framing at all. This reproduces
    that exact shape and verifies table detection now survives it."""
    schema_bases = _PREMISES_COLUMN_BASES  # 6 columns total
    unmatched = {}
    # Columns 0-1 (SubjectOfInsuranceCode, LimitAmount): unmatched for A,B,C.
    for base in schema_bases[:2]:
        for row in ("A", "B", "C"):
            unmatched[f"{base}_{row}"] = _ACORD_140_SCHEMA[f"{base}_{row}"]
    # Columns 2-5 (CoinsurancePercent, DeductibleAmount, FormsAndConditions,
    # ValuationCode): row A already resolved elsewhere - only B,C unmatched.
    for base in schema_bases[2:]:
        for row in ("B", "C"):
            unmatched[f"{base}_{row}"] = _ACORD_140_SCHEMA[f"{base}_{row}"]

    captured = []
    with patch.object(pdf_service, "_get_openai_form_fill_client_sync", return_value=_fake_openai_client(captured)):
        pdf_service._fill_unmatched_with_gpt(
            unmatched, facts={}, form_id="ACORD_140",
            raw_text="Location 1: Building, $3,150,000. Location 2: Building, $2,480,000.",
        )
    user_msgs = [m[1]["content"] for m in captured if len(m) > 1]
    combined = "\n".join(user_msgs)

    # Must still be treated as ONE table (all 6 columns, even though only 2
    # of them have row A active) - not fragmented into sub-3-column buckets
    # that fall back to independent-column treatment.
    assert "TABLE 'CommercialProperty_Premises'" in combined
    for base in schema_bases:
        assert f"REPEATING GROUP '{base}'" not in combined

    # Row A must appear in the table (it's active for 2 of the 6 columns) with
    # ONLY those 2 columns' field names listed for it - not all 6.
    row_a_line = next(l for l in combined.splitlines() if l.strip().startswith("_A:"))
    assert "CommercialProperty_Premises_SubjectOfInsuranceCode_A" in row_a_line
    assert "CommercialProperty_Premises_LimitAmount_A" in row_a_line
    assert "CommercialProperty_Premises_CoinsurancePercent_A" not in row_a_line
    assert "CommercialProperty_Premises_ValuationCode_A" not in row_a_line

    # Row B must list all 6 columns (all active for B).
    row_b_line = next(l for l in combined.splitlines() if l.strip().startswith("_B:"))
    for base in schema_bases:
        assert f"{base}_B" in row_b_line


def test_non_table_pair_still_uses_ordinary_repeating_group():
    captured = []
    with patch.object(pdf_service, "_get_openai_form_fill_client_sync", return_value=_fake_openai_client(captured)):
        pdf_service._fill_unmatched_with_gpt(
            _build_unmatched_fields(),
            facts={},
            form_id="ACORD_140",
            raw_text="Spoilage limit $50,000.",
        )
    user_msgs = [m[1]["content"] for m in captured if len(m) > 1]
    combined = "\n".join(user_msgs)
    # A coincidental 2-column pair (Spoilage LimitAmount/DeductibleAmount, 2
    # slots each) must NOT be treated as a table (the >=3-column threshold is
    # deliberate) - it should still render as two ordinary REPEATING GROUPs.
    assert "REPEATING GROUP 'CommercialProperty_Spoilage_LimitAmount'" in combined
    assert "REPEATING GROUP 'CommercialProperty_Spoilage_DeductibleAmount'" in combined
    assert "TABLE 'CommercialProperty_Spoilage'" not in combined


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    passed = 0
    for fn in fns:
        fn()
        passed += 1
        print(f"  ok  {fn.__name__}")
    print(f"\n{passed}/{len(fns)} passed")
