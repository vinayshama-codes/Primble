"""The loss-history question the client asked for, without a data migration.

Client, 2026-08-17, verbatim:
  "For loss history, use an explicit confirmation such as: Have you had any
   insurance claims or losses in the past five years? Yes / No. If Yes, request
   the additional information. A blank response should not mean 'No losses.'"

The stored fact means "no prior losses = TRUE", so his question runs the
opposite way round. The dangerous fix is to flip the question and the stored
value together - get one apply path wrong and a clean account silently becomes a
claims account. These tests pin the safe route: the chosen option TEXT is what
gets stored, and the existing attestation reader already reads it correctly.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("OPENAI_API_KEY", "sk-offline")

import pytest

from services.arq_service import (
    NO_LOSS_INDICATOR_FIELD,
    _FIELD_QUESTION_MAP,
    _NO_LOSS_OPTIONS,
    _maybe_inject_no_loss_question,
)
from services.sqs_service import _attested_true, calculate_p4_loss_history


def _pillar(answer):
    return calculate_p4_loss_history({NO_LOSS_INDICATOR_FIELD: answer}, {})[0]


def test_the_question_is_asked_in_the_clients_direction():
    q = _FIELD_QUESTION_MAP[NO_LOSS_INDICATOR_FIELD].lower()
    assert "have you had any insurance claims or losses" in q
    assert "no insurance claims" not in q, "the double negative is back"


def test_the_client_wording_needs_no_inversion():
    """The load-bearing test. If either option is reworded, this must be re-run."""
    no_claims, had_claims = _NO_LOSS_OPTIONS
    assert _attested_true(no_claims) is True, (
        f"{no_claims!r} must attest to No Known Losses"
    )
    assert _attested_true(had_claims) is False, (
        f"{had_claims!r} must NOT attest - this would credit an account WITH claims"
    )


def test_the_pillar_lands_where_the_specification_says():
    no_claims, had_claims = _NO_LOSS_OPTIONS
    assert _pillar(no_claims) == 60, "an attestation is worth 60"
    assert _pillar(had_claims) == 25, "claims are not an attestation"


def test_blank_is_not_no_losses():
    """The client's opening principle, on the question he named."""
    for blank in ("", None):
        assert _pillar(blank) == 25, "silence must score as no information"
        assert _attested_true(blank) is False


def test_the_control_can_express_not_answered():
    """A checkbox cannot: untouched and deliberate-No are the same byte."""
    qs = []
    _maybe_inject_no_loss_question(qs, {}, {})
    assert len(qs) == 1
    q = qs[0]
    assert q["field_type"] == "select", "a checkbox cannot say 'not answered'"
    assert list(q["options"]) == list(_NO_LOSS_OPTIONS)
    assert q["current_value"] == "", "must not pre-answer on the client's behalf"


def test_old_stored_answers_keep_their_meaning():
    """Nothing written before today may change meaning. This is the whole
    reason the question was not simply inverted."""
    assert _pillar("Yes") == 60, "a legacy 'Yes' meant NO losses and still must"
    assert _pillar("No") == 25, "a legacy 'No' meant they had losses and still must"


def test_a_misfiled_year_count_no_longer_swallows_the_question():
    """The live 2026-08-17 case: the loss card's wrong-field bug wrote the words
    "no losses" into `loss_history_years`, the injector read any non-empty value
    as a real year count, and the question was never asked at all."""
    qs = []
    _maybe_inject_no_loss_question(qs, {"loss_history_years": "no losses"}, {})
    assert len(qs) == 1, "text in a year count is not a quantified loss history"

    qs2 = []
    _maybe_inject_no_loss_question(qs2, {"loss_history_years": 5}, {})
    assert qs2 == [], "a REAL year count still means there is nothing to ask"

    qs3 = []
    _maybe_inject_no_loss_question(qs3, {"num_claims": 3}, {})
    assert qs3 == [], "a real claim count still answers it"


def test_it_is_not_asked_when_already_answered():
    for facts in ({NO_LOSS_INDICATOR_FIELD: _NO_LOSS_OPTIONS[0]},
                  {"no_prior_losses": "Yes"}):
        qs = []
        _maybe_inject_no_loss_question(qs, facts, {})
        assert qs == [], f"asked again despite {facts}"


@pytest.mark.parametrize("option", _NO_LOSS_OPTIONS)
def test_every_option_is_readable_by_a_person(option):
    assert len(option) < 60
    assert option[0].isupper()
    assert "—" not in option, "project rule: no em-dashes in UI copy"
