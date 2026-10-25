"""The upload's No Known Losses / loss-run conflict leaves the screen once the
live check stops raising it (owner, 23 Oct 2026: answering "we have had claims"
left the warning listed)."""
import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
os.environ.setdefault("OPENAI_API_KEY", "sk-offline-test")

from services import issue_registry as ir

_CONFLICT = {"code": ir.LOSS_CONFLICT_CODE, "message": "Data consistency: a No Known Losses attestation conflicts"}
_OTHER = {"code": "legacy_auto_driver_schedule_missing", "message": "Driver schedule not provided"}


def test_retired_when_the_live_check_no_longer_raises_it(monkeypatch):
    import services.sqs_service as sq
    monkeypatch.setattr(sq, "_loss_history_conflict", lambda f, fl, doc: False)
    out = ir.retire_stopped_loss_conflict([_CONFLICT, _OTHER], {}, {}, [])
    assert out == [_OTHER]


def test_kept_while_the_live_check_still_raises_it(monkeypatch):
    import services.sqs_service as sq
    monkeypatch.setattr(sq, "_loss_history_conflict", lambda f, fl, doc: True)
    assert ir.retire_stopped_loss_conflict([_CONFLICT, _OTHER], {}, {}, []) == [_CONFLICT, _OTHER]


def test_a_check_that_cannot_run_keeps_everything(monkeypatch):
    import services.sqs_service as sq
    def boom(*a):
        raise RuntimeError("x")
    monkeypatch.setattr(sq, "_loss_history_conflict", boom)
    assert ir.retire_stopped_loss_conflict([_CONFLICT], {}, {}, []) == [_CONFLICT]


def test_the_answer_we_have_had_claims_ends_the_conflict():
    facts = {"loss_history_no_prior_losses_indicator": {"value": "Yes - we have had claims or losses", "source": "producer"},
             "num_claims": {"value": "12", "source": "producer"}, "total_incurred": {"value": "322650", "source": "producer"}}
    flags = {"no_prior_losses": False}
    out = ir.retire_stopped_loss_conflict([_CONFLICT], facts, flags, [])
    assert out == []
