"""Regression guards for the gap-fill prompt prefix-cache work (2026-07-29).

These lock in the fixes recorded as C1-C7 in `improving-ll.md`. They make ZERO
OpenAI calls: prefix caching is decided entirely by the BYTES of the prompt, so
it is a deterministic offline property. Testing it against real model calls
would be strictly worse - this pipeline is non-deterministic, so run-to-run
jitter would mask the very regression these guard against.

If one of these fails, read the referenced issue in `improving-ll.md` before
changing the test.
"""
import json
import os
import threading

import pytest

import services.pdf_service as ps


# ── C5: the prompt must ask for OMISSION, never for explicit nulls ───────────

def test_skeleton_is_module_level_and_form_agnostic():
    """C2: the system prompt must not carry a form id.

    It used to be an f-string built per call with `form_id` interpolated into
    line one. Because `combined_gap_fill` passes a BATCH LABEL as `form_id`, the
    model was told "You are filling ACORD form COMBINED_B1of2" - it never learned
    the real form - and the per-batch system message meant nothing ever cached.
    """
    skeleton = ps._PROMPT_SKELETON
    assert isinstance(skeleton, str) and len(skeleton) > 4000
    assert "COMBINED" not in skeleton
    assert "{form_id}" not in skeleton and "{form_label}" not in skeleton
    assert "ACORD_1" not in skeleton          # no specific form number leaked in
    assert ps._SKELETON_CHARS == len(skeleton)


def test_skeleton_never_asks_for_explicit_nulls():
    """C5: 'return JSON null' appeared ~12x against a single 'omit' block, so the
    model emitted nulls that the caller threw away - waste at 6x the input price.
    Omission must be the only stated convention."""
    skeleton = ps._PROMPT_SKELETON
    banned = (
        "return JSON null",
        "set the extra slots to JSON null",
        "return null",
        "= null (unquoted)",
    )
    for phrase in banned:
        assert phrase.lower() not in skeleton.lower(), f"skeleton still says {phrase!r}"
    # The omit protocol and the banned-sentinel list must both survive.
    assert "OMIT-WHEN-UNKNOWN PROTOCOL" in skeleton
    assert "Not Applicable" in skeleton and "TBD" in skeleton


def test_skeleton_has_no_stale_positional_references():
    """The field list now sits at the END of the user message. Rules that told
    the model to look 'above' would point it at the document instead."""
    assert "checkbox — Yes/No' above" not in ps._PROMPT_SKELETON
    assert "blocks below" not in ps._PROMPT_SKELETON


# ── C6: salvage a truncated reply instead of re-billing the whole prompt ──────

def test_salvage_recovers_completed_keys_from_truncated_json():
    truncated = (
        '{"values": {"Producer_FullName_A": "Heartland Brokers", '
        '"Policy_Number_A": "CPP-4471902-03", "Insured_City_A": "Kansas Ci'
    )
    with pytest.raises(json.JSONDecodeError):
        json.loads(truncated)
    salvaged = ps._salvage_truncated_json(truncated)
    assert salvaged is not None
    assert salvaged["values"]["Producer_FullName_A"] == "Heartland Brokers"
    assert salvaged["values"]["Policy_Number_A"] == "CPP-4471902-03"
    # The half-written pair is dropped, not guessed at.
    assert "Insured_City_A" not in salvaged["values"]


def test_salvage_handles_truncation_between_top_level_keys():
    truncated = (
        '{"values": {"A_1": "x", "B_1": "y"}, "raw_text_sourced": ["A_1", "B_1"], '
        '"question_grounding": {"A_1": "some quote'
    )
    salvaged = ps._salvage_truncated_json(truncated)
    assert salvaged is not None
    assert salvaged["values"] == {"A_1": "x", "B_1": "y"}
    assert salvaged["raw_text_sourced"] == ["A_1", "B_1"]


def test_salvage_does_not_invent_data_from_garbage():
    for junk in ("", "not json at all", "{", '{"values": {', "[1,2,3]"):
        assert ps._salvage_truncated_json(junk) is None


def test_salvage_ignores_commas_inside_strings():
    """A comma inside a string value must not be mistaken for an element break."""
    truncated = '{"values": {"Desc_A": "Roofing, siding, and gutters", "Next_A": "trunc'
    salvaged = ps._salvage_truncated_json(truncated)
    assert salvaged is not None
    assert salvaged["values"]["Desc_A"] == "Roofing, siding, and gutters"


# ── C7: only a real response_format rejection may trigger a second call ──────

class _FakeAPIError(Exception):
    def __init__(self, msg, status_code):
        super().__init__(msg)
        self.status_code = status_code


def test_response_format_rejection_detection():
    fmt_400 = _FakeAPIError(
        "Invalid parameter: 'response_format.json_schema' is not supported", 400)
    assert ps._is_response_format_rejection(fmt_400) is True
    # A local SDK rejection sends no request at all - safe to retry.
    assert ps._is_response_format_rejection(TypeError("unexpected keyword")) is True


def test_timeout_and_rate_limit_do_not_trigger_a_second_billed_call():
    """C7: falling back on ANY exception meant a timeout or 429 - where OpenAI
    had already processed and BILLED the request - immediately fired a second
    identical full-prompt call."""
    assert ps._is_response_format_rejection(_FakeAPIError("Rate limited", 429)) is False
    assert ps._is_response_format_rejection(_FakeAPIError("Gateway timeout", 504)) is False
    assert ps._is_response_format_rejection(_FakeAPIError("Server error", 500)) is False
    ctx = _FakeAPIError("This model's maximum context length is 400000 tokens", 400)
    assert ps._is_response_format_rejection(ctx) is False, (
        "a context-length 400 cannot be fixed by json_object - retrying re-bills "
        "a call that can never succeed"
    )


# ── C1/C2/C3: end-to-end prompt shape, captured without calling OpenAI ───────

_FACTS = {
    "applicant_name": "Ridgeline Roofing & Sheet Metal LLC",
    "policy_number": "CPP-4471902-03",
    "carrier_name": "Midwest Mutual Casualty",
    "naics_code": "238160",
    "operations_description": "Residential roof replacement. No blasting.",
    "has_general_liability": True,
    "is_contractor": True,
}
_RAW = (
    "COMMERCIAL INSURANCE APPLICATION\n"
    "Named Insured: Ridgeline Roofing & Sheet Metal LLC\n"
    "Carrier: Midwest Mutual Casualty   Policy No: CPP-4471902-03\n"
    "General Liability - Each Occurrence: $1,000,000\n"
    "Loss History: No known losses in the past five years.\n"
) * 8


class _Recorder:
    """Stands in for the OpenAI sync client; records messages, never calls out."""

    def __init__(self):
        self.calls = []                      # (stage, system, user)
        self._lock = threading.Lock()
        self.chat = self
        self.completions = self

    def create(self, **kwargs):
        msgs = kwargs.get("messages") or []
        system = next((m["content"] for m in msgs if m["role"] == "system"), "")
        user = next((m["content"] for m in msgs if m["role"] == "user"), "")
        # Identify the stage from the SYSTEM PROMPT, never from
        # `prompt_cache_key`: that parameter is only sent when the installed SDK
        # supports it, and the deployed venv runs openai==1.54.4, which does not.
        # Keying off it made these tests silently assert "no gap_fill calls were
        # made" on the box that actually ships.
        stage = "compliance" if system is ps._COMPLIANCE_SYSTEM_PROMPT else "gap_fill"
        with self._lock:
            self.calls.append((stage, system, user))

        class _R:
            choices = [type("C", (), {"message": type(
                "M", (), {"content": '{"values": {}, "raw_text_sourced": [], '
                                     '"question_grounding": {}}'})()})()]
            usage = None
        return _R()


@pytest.fixture
def captured_prompts(monkeypatch):
    """Run the REAL combined_gap_fill over real schemas with a recorded client."""
    rec = _Recorder()
    monkeypatch.setattr(ps, "_get_openai_form_fill_client_sync", lambda: rec)
    monkeypatch.setattr(ps, "_COMBINED_BATCH_PAUSE_S", 0.0, raising=False)

    forms_to_unmatched = {}
    for form_id in ("ACORD_125", "ACORD_25"):
        path = os.path.join(ps.FORMS_SCHEMAS_DIR, f"{form_id}_schema.json")
        with open(path, encoding="utf-8") as fh:
            schema = json.load(fh)
        _mapped, unmatched, _ = ps.compute_form_gaps(form_id, schema, _FACTS)
        forms_to_unmatched[form_id] = unmatched

    ps.combined_gap_fill(forms_to_unmatched, _FACTS, _RAW)
    assert rec.calls, "no LLM calls captured"
    return rec.calls


def _gap_fill_users(calls):
    return [u for st, _s, u in calls if st == "gap_fill"]


def test_system_prompt_is_byte_identical_across_every_call(captured_prompts):
    """C2: a per-batch system message diverges at the first few tokens, so the
    ENTIRE prompt is billed at full price on every call."""
    for stage in {c[0] for c in captured_prompts}:
        systems = {s for st, s, _u in captured_prompts if st == stage}
        assert len(systems) == 1, (
            f"stage={stage} sent {len(systems)} different system prompts - "
            f"prefix caching is dead (improving-ll.md C2)"
        )


def test_model_is_told_the_real_form_names_not_the_batch_label(captured_prompts):
    """C2, second defect: the model could not tell a Workers Comp form from a
    Commercial Auto one because it was handed 'COMBINED_B1of2'."""
    users = _gap_fill_users(captured_prompts)
    assert users
    for u in users:
        assert "ACORD_125" in u and "ACORD_25" in u
        assert "COMBINED_B" not in u, "batch label leaked into the model's prompt"


def test_constant_blocks_precede_the_variable_field_list(captured_prompts):
    """C1: the field list varies per sub-batch. Anything after it is unreachable
    by the cache, so both constant sources must come first - and facts must stay
    ahead of the raw text, since the prompt calls facts the PRIMARY source."""
    for u in _gap_fill_users(captured_prompts):
        i_facts = u.index("=== EXTRACTED FACTS")
        i_raw = u.index("=== RAW DOCUMENT TEXT")
        i_fields = u.index("Fields to fill (")
        assert i_facts < i_raw < i_fields, (
            "prompt order regressed; expected facts -> raw text -> fields"
        )


def test_gap_fill_calls_share_a_prefix_above_the_openai_cache_floor(captured_prompts):
    """C1/C3 combined: OpenAI only caches a prefix of >=1024 tokens, matched from
    the very first token. Anything under that floor caches nothing at all."""
    users = _gap_fill_users(captured_prompts)
    assert len(users) > 1, "need multiple sub-batches to test prefix sharing"

    head = users[0]
    for u in users[1:]:
        n = min(len(head), len(u))
        i = 0
        while i < n and head[i] == u[i]:
            i += 1
        head = head[:i]

    system_chars = next(len(s) for st, s, _u in captured_prompts if st == "gap_fill")
    prefix_tokens = (system_chars + len(head)) / 4.0
    assert prefix_tokens >= 1024, (
        f"shared prefix is only ~{prefix_tokens:.0f} tokens, below OpenAI's 1024-token "
        f"cache floor - nothing will cache (improving-ll.md C1/C3)"
    )
    # The whole document must be inside the shared prefix, not just the header.
    assert "=== RAW DOCUMENT TEXT" in head
    assert "Loss History: No known losses" in head


# Measured on this exact fixture (ACORD_125 + ACORD_25, the same two forms as the
# audit): HEAD before the fix issued 24 gap-fill calls because
# `_pack_field_batches` flushed a partially-filled batch every time it met a
# table group - real runs looked like [40,4,11,24,18,40,40,9]. After the fix it
# issues 18. Each avoided call is a full fixed prompt overhead plus a round trip.
# The threshold has slack for schema churn; it is a fragmentation alarm, not an
# exact-count assertion.
_GAP_FILL_CALLS_BEFORE_FIX = 24
_GAP_FILL_CALLS_CEILING = 20


def test_table_groups_do_not_fragment_the_batch_run(captured_prompts):
    """C4: emitting a table group as its own atomic batch is required for row
    alignment, but FLUSHING the half-full batch in front of it is not - it just
    buys extra calls, each paying the full fixed prompt overhead for nothing."""
    n = len(_gap_fill_users(captured_prompts))
    assert n <= _GAP_FILL_CALLS_CEILING, (
        f"{n} gap-fill calls for this fixture (ceiling {_GAP_FILL_CALLS_CEILING}, "
        f"was {_GAP_FILL_CALLS_BEFORE_FIX} before the fix) - `_pack_field_batches` "
        f"is fragmenting batches again (improving-ll.md C4)"
    )
