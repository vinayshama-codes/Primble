"""V1 REQUIRED REGRESSION TEST PACK - Loss History (client tests 5, 6, 7, 8).

Part of the client's REQUIRED V1 REGRESSION TEST PACK. These are recurring
regression scenarios: re-run them on every V1 change that touches loss history,
the Loss History pillar, pillar weighting, or the loss questionnaire.

  Test 5 - Verified New Venture
  Test 6 - Loss Runs Pending, Known Claims
  Test 7 - Loss Runs Pending + No-Loss Attestation
  Test 8 - No-Loss Attestation Contradicted by Uploaded Claims

Every test drives the REAL scorer (`sqs_service.calculate_p4_loss_history`),
the REAL state owner (`services/loss_history_state.py`) and the REAL generic
Not-Applicable rescaler (`sqs_service._weighted_pillar_sum`) - never a copy of
the rule. Each negative assertion carries a positive control proving the
machinery fires on the opposite input (a "no question asked" that would also
pass when nothing is asked of anyone proves nothing).

BAND NOTE (Brent ruling 2026-08-24, v1-20AUG.md C2-E): the client's 60 / 50
numbers are the 5+-years and unknown-years column. A business of 1-5 years
("establishing") scores higher by ruling - 85 attested, 70 pending. Both
columns are pinned below so a future edit cannot quietly move either.
"""
import ast
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from services import loss_history_state as lhs                   # noqa: E402
from services import sqs_service as sq                           # noqa: E402
from services import issue_registry as ir                        # noqa: E402

BACKEND = Path(__file__).resolve().parents[1]

# The client's own words for a confirmed New Venture, and the producer flag the
# apply path writes alongside it.
NEW_VENTURE_FACTS = {"new_venture": "Yes - new venture, no prior operations"}
NEW_VENTURE_FLAGS = {"new_venture_confirmed": True}


def _score(facts, flags=None, **kw):
    return sq.calculate_p4_loss_history(facts, flags or {}, **kw)[0]


def _recs(facts, flags=None, **kw):
    return sq.calculate_p4_loss_history(facts, flags or {}, **kw)[1]


# -- TEST 5 - Verified New Venture --------------------------------------------

def test_r05_loss_history_is_not_applicable():
    """Loss History = N/A (the pillar returns None, not a low number)."""
    assert lhs.loss_history_not_applicable(NEW_VENTURE_FACTS, NEW_VENTURE_FLAGS) is True
    assert _score(NEW_VENTURE_FACTS, NEW_VENTURE_FLAGS) is None
    assert lhs.resolve_loss_history_state(
        NEW_VENTURE_FACTS, NEW_VENTURE_FLAGS) == lhs.STATE_NEW_VENTURE

    # POSITIVE CONTROL - without the confirmation the pillar scores a real
    # number, so the None above is the New Venture rule and not a dead path.
    assert _score({}, {}) == 25


def test_r05_prior_carrier_is_not_applicable():
    """prior carrier = N/A - and specifically NOT the -10 'missing' deduction."""
    assert lhs.prior_carrier_applicable(NEW_VENTURE_FACTS, NEW_VENTURE_FLAGS) is False

    # POSITIVE CONTROL - a renewal with no carrier named IS applicable, so the
    # False above is the New Venture gate, not a function that never returns True.
    assert lhs.prior_carrier_applicable({"is_renewal": "Yes"}, {}) is True


def test_r05_prior_claim_count_is_not_applicable():
    """prior claim count = N/A - the count is never asked of a new venture."""
    suppressed = lhs.suppressed_question_fields(NEW_VENTURE_FACTS, NEW_VENTURE_FLAGS)
    assert "num_claims" in suppressed
    assert "total_incurred" in suppressed
    assert "open_claims_count" in suppressed
    assert "prior_carrier" in suppressed


def test_r05_no_loss_run_questionnaire():
    """No loss-run questionnaire item survives a confirmed New Venture."""
    suppressed = lhs.suppressed_question_fields(NEW_VENTURE_FACTS, NEW_VENTURE_FLAGS)
    assert lhs.LOSS_RUN_STATUS_FIELD in suppressed
    assert "loss_history_years" in suppressed
    assert "loss_history_no_prior_losses_indicator" in suppressed

    # POSITIVE CONTROL - the same reader suppresses NOTHING on an ordinary
    # submission, so the set above is the New Venture rule firing.
    assert lhs.suppressed_question_fields({}, {}) == frozenset()


def test_r05_pillar_weights_rescale():
    """Pillar weights RESCALE: Loss History leaves the calculation and the
    remaining pillars' original weights re-normalise to 100%."""
    weights = sq.SPEC_PILLAR_WEIGHTS
    all_pillars = {k: 80.0 for k in weights}

    # Nothing N/A: 80 across the board scores 80.
    assert sq._weighted_pillar_sum(all_pillars, weights) == 80

    # Loss History N/A: the OTHER pillars still produce 80, not 80 x 0.85.
    na = dict(all_pillars, loss_history_alignment=None)
    assert sq._weighted_pillar_sum(na, weights) == 80

    eff = sq.effective_pillar_weights(na, weights)
    assert "loss_history_alignment" not in eff
    # (each weight is rounded to 5dp by the production function, so the sum
    # carries a rounding artefact - the contract is "totals 100%", not exact)
    assert sum(eff.values()) == pytest.approx(1.0, abs=1e-4)
    # Structural was 0.25 of 1.00; with Loss History (0.15) removed it is
    # 0.25 / 0.85 - the weight the score ACTUALLY carried.
    assert eff["structural_completeness"] == round(0.25 / 0.85, 5)

    # It is a rescale, not a free pass: a genuinely weak pillar still drags.
    weak = dict(na, structural_completeness=0.0)
    assert sq._weighted_pillar_sum(weak, weights) < 80


# -- TEST 6 - Loss Runs Pending, Known Claims ---------------------------------

PENDING_WITH_CLAIMS = {
    "num_claims": 3,
    "total_incurred": 42000,
    "loss_run_status": "requested from prior carrier",
}


@pytest.mark.parametrize("years,expected,why", [
    (None, 50, "years unknown - the client's own column"),
    (12,   50, "5+ years - loss runs are required, so pending is worth 50"),
    (3,    70, "1-5 years (Brent 2026-08-24): pending is a satisfactory answer"),
])
def test_r06_path_c_pending_with_known_claims(years, expected, why):
    """Loss History Path C = 50 until evidence arrives."""
    facts = dict(PENDING_WITH_CLAIMS)
    if years is not None:
        facts["years_in_business"] = years
    assert _score(facts, {}) == expected, why


def test_r06_known_claims_and_pending_both_read():
    """The fixture really is 'known claims AND pending' - not one of them."""
    assert lhs.prior_claims_exist(PENDING_WITH_CLAIMS, {}) is True
    assert lhs.loss_runs_pending_stated(PENDING_WITH_CLAIMS, {}) is True
    # Pending outranks known claims (client 2.5 ordering); known claims with
    # NOTHING pending is the 25 floor - so the 50 above is the pending branch.
    assert _score({"num_claims": 3, "total_incurred": 42000}, {}) == 25


def test_r06_followup_remains_visible():
    """The relevant producer/client follow-up remains VISIBLE - not suppressed."""
    recs = _recs(PENDING_WITH_CLAIMS, {})
    assert any("pending" in r.lower() or "requested" in r.lower() for r in recs), recs
    # Nothing is suppressed in this state, so the loss questions stay askable.
    assert lhs.suppressed_question_fields(PENDING_WITH_CLAIMS, {}) == frozenset()
    assert lhs.resolve_loss_history_state(
        PENDING_WITH_CLAIMS, {}) == lhs.STATE_LOSS_RUNS_PENDING


# -- TEST 7 - Loss Runs Pending + No-Loss Attestation -------------------------

ATTESTED_AND_PENDING = {
    "loss_history_no_prior_losses_indicator": "Yes - no known losses",
    "loss_run_status": "pending",
}


@pytest.mark.parametrize("years,expected,why", [
    (None, 60, "years unknown - the client's own number"),
    (12,   60, "5+ years"),
    (3,    85, "1-5 years (Brent 2026-08-24): an attestation is satisfactory"),
])
def test_r07_attestation_outranks_pending(years, expected, why):
    """Loss History = 60 until the runs arrive."""
    facts = dict(ATTESTED_AND_PENDING)
    if years is not None:
        facts["years_in_business"] = years
    assert _score(facts, {}) == expected, why


def test_r07_attestation_is_what_lifted_it():
    """Prove the 60 comes from the attestation, not from 'pending'."""
    # The same package WITHOUT the attestation is the pending score, 50.
    assert _score({"loss_run_status": "pending"}, {}) == 50
    assert lhs.loss_runs_pending_stated(ATTESTED_AND_PENDING, {}) is True
    assert lhs.user_attested_no_losses(ATTESTED_AND_PENDING, {}) is True
    assert lhs.resolve_loss_history_state(
        ATTESTED_AND_PENDING, {}) == lhs.STATE_NO_KNOWN_LOSSES_ATTESTED


# -- TEST 8 - No-Loss Attestation Contradicted by Uploaded Claims -------------

CONTRADICTED = {
    "loss_history_no_prior_losses_indicator": "Yes - no known losses",
    "loss_history_years": 5,
    "num_claims": 3,
    "total_incurred": 45000,
}


def test_r08_conflict_is_created():
    """A conflict is created when the attestation meets real claims."""
    assert sq._loss_history_conflict(CONTRADICTED, {}) is True

    # A CLEAN multi-year loss run CONFIRMS an attestation - it must not
    # manufacture a conflict. This is the false-positive control.
    clean = dict(CONTRADICTED, num_claims=0, total_incurred=0)
    assert sq._loss_history_conflict(clean, {}) is False


def test_r08_loss_history_capped_at_45():
    """Loss History capped at 45 while unresolved."""
    score = _score(CONTRADICTED, {}, has_loss_run_doc=True, loss_run_match="strong")
    assert score == 45
    assert score == sq._LOSS_CONFLICT_CAP

    # It is a CEILING, never a floor: the same contradiction on a package that
    # already scores below 45 is not lifted to 45.
    assert _score(CONTRADICTED, {}, has_loss_run_doc=True,
                  loss_run_match="no_match") <= sq._LOSS_NO_MATCH_CAP

    # Uncapped control: the identical loss runs WITHOUT the false attestation
    # earn their full year-tier credit, so the 45 is the cap doing the work.
    honest = {k: v for k, v in CONTRADICTED.items()
              if k != "loss_history_no_prior_losses_indicator"}
    assert _score(honest, {}, has_loss_run_doc=True, loss_run_match="strong") > 45


def test_r08_producer_resolution_required():
    """Producer resolution is required - the conflict reaches a producer row."""
    recs = _recs(CONTRADICTED, {}, has_loss_run_doc=True, loss_run_match="strong")
    assert any("conflict" in r.lower() for r in recs), recs

    issue = ir.make_issue(
        "loss_history_attestation_conflict", "advisory",
        "Data consistency: a No Known Losses attestation conflicts with claims "
        "found in the uploaded loss runs.")
    assert issue["code"] == "loss_history_attestation_conflict"
    # ADVISORY on purpose: the client caps the PILLAR at 45, not the package -
    # a hard/soft stop here would wrongly ceiling the submission at 60/85.
    assert issue["severity"] == "advisory"


def test_r08_pipeline_emits_the_conflict_row():
    """THE SEAM: `extraction_pipeline` really emits that row, guarded by the
    same `_loss_history_conflict` the 45 cap uses.

    An offline probe proves the FUNCTION, never the SEAM around it - so this
    reads the pipeline source and fails if the emission is ever deleted or
    decoupled from the guard.
    """
    src = (BACKEND / "services" / "extraction_pipeline.py").read_text(
        encoding="utf-8", errors="ignore")
    tree = ast.parse(src)

    emitting_guards = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.If):
            continue
        calls = [n for n in ast.walk(node)
                 if isinstance(n, ast.Call)
                 and getattr(n.func, "id", None) == "make_issue"
                 and n.args and isinstance(n.args[0], ast.Constant)
                 and n.args[0].value == "loss_history_attestation_conflict"]
        if calls:
            emitting_guards.append(ast.unparse(node.test))

    assert emitting_guards, (
        "extraction_pipeline no longer emits the loss_history_attestation_conflict "
        "row - client test 8 requires the producer-facing conflict")
    assert any("_loss_history_conflict" in g for g in emitting_guards), (
        "the conflict row is no longer guarded by _loss_history_conflict, so the "
        "row and the 45 cap can now disagree: %s" % emitting_guards)
