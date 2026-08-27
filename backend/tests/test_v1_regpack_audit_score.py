"""V1 REQUIRED REGRESSION TEST PACK - Download & SQS ceiling (client tests 17, 18).

Part of the client's REQUIRED V1 REGRESSION TEST PACK. Recurring regression
scenarios: re-run on every change to the download path, the audit record, or
any scoring ceiling.

  Test 17 - Download With Open Issues
  Test 18 - SQS Ceiling Behavior

Test 18 drives the REAL ceiling engine (`sqs_service._resolve_cap` +
`final_score_with_credits`) and the REAL audit ledger (`build_score_trace`)
with the client's three literal examples.

Test 17 drives the REAL download gate (`routes.download_routes.
_enforce_completeness_gate` and `field_qa.check_hard_block`). The route
itself needs Postgres, so the parts that only a live request can execute are
pinned by reading the route's own AST - an offline probe proves the FUNCTION,
never the SEAM around it, so the seam is asserted rather than assumed.
"""
import ast
import inspect
import sys
from pathlib import Path

import pytest
from fastapi import HTTPException

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from routes import download_routes as dr                         # noqa: E402
from services import sqs_service as sq                           # noqa: E402
from services.field_qa import check_hard_block, _HARD_BLOCK_REASON_CODES  # noqa: E402

BACKEND = Path(__file__).resolve().parents[1]


# =============================================================================
# TEST 18 - SQS Ceiling Behavior
# =============================================================================

# The client's three literal examples.
CEILING_EXAMPLES = [
    (88, [], ["Auto exposure detected but no vehicle schedule"], 85, sq.SOFT_STOP_CAP),
    (88, ["Umbrella has no underlying coverage"], [], 60, sq.HARD_STOP_CAP),
    (42, ["Umbrella has no underlying coverage"], [], 42, sq.HARD_STOP_CAP),
]


@pytest.mark.parametrize("raw,hard,soft,displayed,cap", CEILING_EXAMPLES)
def test_r18_client_ceiling_examples(raw, hard, soft, displayed, cap):
    """Raw 88 + warning -> 85; Raw 88 + hard stop -> 60; Raw 42 + hard stop -> 42."""
    resolved_cap, reason = sq._resolve_cap(hard, soft)
    assert resolved_cap == cap
    assert sq.final_score_with_credits(raw, 0, resolved_cap) == displayed


def test_r18_raw_score_is_preserved():
    """The raw score is preserved - the ceiling never overwrites it."""
    raw = 88
    cap, reason = sq._resolve_cap(["Umbrella has no underlying coverage"], [])
    displayed = sq.final_score_with_credits(raw, 0, cap)
    trace = sq.build_score_trace(
        pillars={k: 88.0 for k in sq.SPEC_PILLAR_WEIGHTS},
        weights=sq.SPEC_PILLAR_WEIGHTS,
        raw_uncapped=raw, cap_applied=cap, cap_reason=reason, displayed=displayed,
    )
    arithmetic = trace["arithmetic"]
    assert arithmetic["raw"] == 88          # raw survives the ceiling
    assert arithmetic["displayed"] == 60
    assert arithmetic["raw"] != arithmetic["displayed"]


def test_r18_ceiling_is_preserved():
    """The ceiling itself is preserved on the record, not just applied."""
    cap, reason = sq._resolve_cap([], ["Auto exposure detected but no vehicle schedule"])
    trace = sq.build_score_trace(
        pillars={k: 88.0 for k in sq.SPEC_PILLAR_WEIGHTS},
        weights=sq.SPEC_PILLAR_WEIGHTS,
        raw_uncapped=88, cap_applied=cap, cap_reason=reason,
        displayed=sq.final_score_with_credits(88, 0, cap),
    )
    assert trace["arithmetic"]["ceiling"] == 85

    # An uncapped score records no ceiling - so the 85 above is a real value,
    # not a constant the builder always writes.
    clean_cap, clean_reason = sq._resolve_cap([], [])
    assert clean_cap is None and clean_reason is None
    clean = sq.build_score_trace(
        pillars={k: 88.0 for k in sq.SPEC_PILLAR_WEIGHTS},
        weights=sq.SPEC_PILLAR_WEIGHTS,
        raw_uncapped=88, cap_applied=clean_cap, cap_reason=clean_reason,
        displayed=sq.final_score_with_credits(88, 0, clean_cap),
    )
    assert clean["arithmetic"]["ceiling"] is None
    assert clean["arithmetic"]["displayed"] == 88


def test_r18_reason_is_preserved():
    """The REASON is preserved - a capped score reads as one sentence."""
    hard_msg = "Umbrella policy has no underlying coverage identified"
    soft_msg = "Auto exposure detected but no vehicle schedule provided"

    cap, reason = sq._resolve_cap([hard_msg], [soft_msg])
    assert cap == 60
    assert reason == hard_msg, "a hard stop must name ITS OWN condition, not the warning"

    cap, reason = sq._resolve_cap([], [soft_msg])
    assert cap == 85 and reason == soft_msg

    trace = sq.build_score_trace(
        pillars={k: 88.0 for k in sq.SPEC_PILLAR_WEIGHTS},
        weights=sq.SPEC_PILLAR_WEIGHTS,
        raw_uncapped=88, cap_applied=cap, cap_reason=reason,
        displayed=sq.final_score_with_credits(88, 0, cap),
    )
    assert trace["arithmetic"]["ceiling_reason"] == soft_msg


def test_r18_ceiling_never_raises_a_low_raw_score():
    """A ceiling NEVER raises a low raw score - it is a ceiling, not a floor."""
    for raw in (0, 1, 25, 41, 42, 59):
        cap, _ = sq._resolve_cap(["a hard stop"], [])
        assert sq.final_score_with_credits(raw, 0, cap) == raw, raw
    for raw in (0, 42, 70, 84):
        cap, _ = sq._resolve_cap([], ["a warning"])
        assert sq.final_score_with_credits(raw, 0, cap) == raw, raw


def test_r18_hard_outranks_soft_and_stops_never_stack():
    """One hard stop and fifteen produce the identical ceiling."""
    assert sq._resolve_cap(["a"], ["b"])[0] == sq.HARD_STOP_CAP
    assert sq._resolve_cap(["a"] * 15, [])[0] == sq._resolve_cap(["a"], [])[0]
    assert sq._resolve_cap([], ["b"] * 15)[0] == sq._resolve_cap([], ["b"])[0]
    # Cross-form hard stops cap like any other hard stop.
    assert sq._resolve_cap([], [], hard_cross=["cross"])[0] == sq.HARD_STOP_CAP


def test_r18_credits_add_to_raw_then_the_ceiling_binds():
    """Owner's worked example: raw 65 capped to 60, +10 credited, stops then
    cleared -> 75 (never 70). Credits go onto the RAW score."""
    cap, _ = sq._resolve_cap(["a hard stop"], [])
    assert sq.final_score_with_credits(65, 10, cap) == 60      # cap still binds
    assert sq.final_score_with_credits(65, 10, None) == 75     # stops cleared


def test_r18_displayed_score_is_bounded():
    """A ceiling cannot push a score outside 0-100."""
    assert sq.final_score_with_credits(95, 50, None) == 100
    assert sq.final_score_with_credits(-5, 0, None) == 0


# =============================================================================
# TEST 17 - Download With Open Issues
# =============================================================================

def _form(confidence, mapped, form_id="ACORD_125"):
    return {form_id: {"confidence": confidence, "mapped": mapped, "schema": {}}}


def test_r17_download_remains_possible_with_open_issues():
    """Open SQS issues (hard stops and warnings) never block a download.

    The only download gate is the completeness gate, and its blocking set is
    exactly two reason codes - neither of which an SQS stop can produce.
    """
    assert _HARD_BLOCK_REASON_CODES == frozenset(
        {"placeholder_value", "missing_required_gate"})

    # A form carrying the field-QA equivalents of open issues - an ordinary
    # missing required field and a low-confidence value - blocks nothing.
    gen = _form(
        {"NamedInsured_FullName_A": "missing_required",
         "GeneralLiability_Hazard_ClassCode_A": "low_confidence"},
        {"GeneralLiability_Hazard_ClassCode_A": "some ai guess"},
    )
    assert check_hard_block(gen) == []

    # And the gate lets that package straight through.
    session = {"generated_forms": gen, "facts": {}}
    assert dr._enforce_completeness_gate(session, ["ACORD_125"], False, "") == []


def test_r17_stops_never_gate_the_download_route():
    """THE SEAM: nothing in the download route raises on hard stops or warnings.

    The standing rule is that stops only CAP a score (60/85). This reads the
    route source and fails if a gate on the stop lists is ever introduced.
    """
    src = inspect.getsource(dr)
    tree = ast.parse(src)
    offenders = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Raise):
            continue
        text = ast.unparse(node)
        if any(tok in text for tok in ("hard_stop", "soft_stop", "sqs_score",
                                       "package_sqs", "hard_cross")):
            offenders.append(text)
    assert not offenders, (
        "the download route now blocks on a score/stop - client test 17 requires "
        "download to remain possible with open issues: %s" % offenders)


def test_r17_acknowledgment_is_required_and_sufficient():
    """An acknowledgment is shown: a genuinely incomplete form is downloadable
    only as a labelled draft with a typed reason."""
    gen = _form({"CommercialProperty_Premises_LimitAmount_A": "missing_required_gate"},
                {}, form_id="ACORD_140")
    session = {"generated_forms": gen, "facts": {}}
    blocking = check_hard_block(gen)
    assert blocking, "fixture must actually be blocking for this test to mean anything"

    # No acknowledgment -> the producer is told, with the count and the route out.
    with pytest.raises(HTTPException) as exc:
        dr._enforce_completeness_gate(session, ["ACORD_140"], False, "")
    assert exc.value.status_code == 409
    assert exc.value.detail["error"] == "download_incomplete"

    # A blank reason is not an acknowledgment.
    with pytest.raises(HTTPException):
        dr._enforce_completeness_gate(session, ["ACORD_140"], True, "   ")

    # Acknowledged -> the download proceeds, and the items ride along so the
    # caller can watermark the PDF and log what was overridden.
    items = dr._enforce_completeness_gate(
        session, ["ACORD_140"], True, "Client confirmed building value at bind")
    assert items == blocking
    assert callable(dr.apply_draft_watermark)


def test_r17_open_issues_are_captured_in_the_audit_event():
    """Open material issues are captured in the audit event - on BOTH the
    ordinary download and the overridden draft."""
    src = inspect.getsource(dr.download_pdf)
    tree = ast.parse(src.lstrip())

    audit_calls = [n for n in ast.walk(tree)
                   if isinstance(n, ast.Call)
                   and getattr(n.func, "id", None) == "write_audit_log"]
    assert len(audit_calls) >= 2, "the download route must log both branches"

    for call in audit_calls:
        kwargs = {k.arg for k in call.keywords}
        assert "unresolved_issues" in kwargs, ast.unparse(call)
        assert "user" in kwargs, ast.unparse(call)
        assert "session_id" in kwargs, ast.unparse(call)

    # The draft branch must preserve the open recommendations, not replace them
    # with the override reason alone (the E&O 5.13 defect fixed 2026-08-26).
    draft_call = next(
        c for c in audit_calls
        if any(k.arg == "action" and getattr(k.value, "value", None) == "download_draft"
               for k in c.keywords))
    payload = ast.unparse(
        next(k.value for k in draft_call.keywords if k.arg == "unresolved_issues"))
    assert "open_recommendations" in payload
    assert "override_reason" in payload

    # And the open items really are recomputed for the log, not read from a
    # possibly-stale snapshot.
    assert "get_unresolved_recommendations" in src


def test_r17_user_and_timestamp_are_retained():
    """The user and the timestamp are retained on the audit record."""
    src = (BACKEND / "repositories" / "audit_repository.py").read_text(
        encoding="utf-8", errors="ignore")
    insert = src[src.index("INSERT INTO acord_audit_log"):]
    columns = insert[:insert.index(")")]
    for col in ("user_id", "user_email", "session_id", "unresolved_issues", "timestamp"):
        assert col in columns, "audit record no longer retains %s" % col
