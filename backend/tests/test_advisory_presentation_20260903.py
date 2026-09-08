"""An item says what it can and cannot do to the score, and to itself.

Owner, 2026-09-03, two rulings taken together:

  1. *"if by clicking a resolve button and adding something, a producer can
     clear it then it's well and good and if it can't be cleared by a value
     then don't show resolve button and just show a disclaimer."*
  2. *"show it under a specific warning which can't move the score and treat
     loss history one as a proper warning as it is capping the score."*

THE TRAP THIS SUITE EXISTS TO PIN. The obvious implementation of #2 is
`severity == "advisory"`, and it is wrong. Measured before writing this: of the
ten advisory-typed issues, the underlying condition of nearly every one already
costs something elsewhere - `loss_history_attestation_conflict` caps the Loss
History pillar at 45, `auto_um_uim_not_specified` drives ACORD 137's structural
score and an 8-point recommendation, `acv_high_value_building` /
`rcv_old_building` read a fact the scorer mentions 18 times. "Advisory" in this
codebase is a DISPLAY ROUTING choice, not a promise about the score. So
neutrality is DECLARED per code, after tracing it, and silence means scoring.
"""
import pytest

from services.issue_registry import (
    SCORE_NEUTRAL_CODES, build_grouped_view, is_score_neutral, make_issue,
    resolution_for,
)


# ── 1. No dead button (owner ruling 1) ───────────────────────────────────────

def test_unmapped_coverage_line_has_a_resolution_at_all():
    """It had NONE, which is why the message said "Confirm which line it
    belongs to" over a control that opened nothing."""
    assert resolution_for("unmapped_coverage_line") is not None


def test_it_offers_a_note_and_never_a_typed_input():
    res = resolution_for("unmapped_coverage_line")
    assert res["mode"] == "none", "no value clears it - a typed input would lie"
    assert res.get("note"), "mode 'none' without a note is the dead button again"
    assert "facts" not in res and "schedule_key" not in res


def test_the_note_says_what_to_actually_do():
    note = resolution_for("unmapped_coverage_line")["note"]
    assert len(note) <= 140, "the owner asked for short"
    assert "source document" in note.lower()


# ── 2. Score-neutral is declared, never inferred ─────────────────────────────

def test_the_reported_item_is_marked_score_neutral():
    assert is_score_neutral("unmapped_coverage_line")
    assert make_issue("unmapped_coverage_line", "advisory", "x")["score_neutral"]


def test_the_loss_history_conflict_gets_a_REAL_fix_not_a_note():
    """It is typeable, unlike the terminology row: the conflict is between an
    attestation and a claim count, and stating the truth retires it (and lifts
    the 45 cap) on the next pipeline run. It earned a resolution the moment it
    earned its own cluster - `test_every_cross_form_cluster_code_has_a_
    resolution` caught the gap, which is that guard doing its job."""
    res = resolution_for("loss_history_attestation_conflict")
    assert res["mode"] == "field"
    assert "loss_history_no_prior_losses_indicator" in res["facts"]
    assert {"num_claims", "total_incurred"} <= set(res["facts"])
    assert "no_prior_losses" not in res["facts"], "a flag, not a writable fact"


def test_the_loss_history_conflict_is_NOT_score_neutral():
    """It caps the Loss History pillar at 45 (`_LOSS_CONFLICT_CAP`). Printing
    "does not affect your score" on it would be a false statement about a
    number, which is the failure this whole design avoids."""
    assert not is_score_neutral("loss_history_attestation_conflict")


@pytest.mark.parametrize("code", [
    "auto_um_uim_not_specified",        # drives ACORD 137 struct + an 8pt rec
    "auto_pip_medpay_not_specified",    # same, via auto_med_pay_limit
    "acv_high_value_building",          # valuation_method is all over the scorer
    "rcv_old_building",
    "acord101_required",                # additional_remarks_text downgrades stops
])
def test_advisory_severity_alone_never_earns_the_note(code):
    """Each of these is advisory-typed AND has a traced score effect. If a
    future change starts deriving the note from severity, this fails."""
    assert not is_score_neutral(code)


def test_an_unknown_code_is_never_assumed_neutral():
    """Silence is not a promise. A new advisory earns the note only after
    somebody has traced what its condition costs."""
    assert not is_score_neutral("some_future_rule")
    assert not is_score_neutral(None)
    assert not is_score_neutral("")


def test_the_neutral_set_stays_deliberately_small():
    """A guard on carelessness, not on the number. Adding a code here means
    claiming, in public, that nothing it touches moves a score."""
    assert "loss_history_attestation_conflict" not in SCORE_NEUTRAL_CODES
    assert "unmapped_coverage_line" in SCORE_NEUTRAL_CODES


# ── 3. It survives the grouped view, which is what the screen reads ──────────

def _view(*issues):
    return build_grouped_view(list(issues), [], [])


def _clusters(view):
    return {c["cluster"]: c
            for tier in view["warnings"].values() for c in tier}


def test_the_flag_reaches_the_cluster_the_screen_renders():
    v = _view(make_issue("unmapped_coverage_line", "advisory", "Coverage part not recognised: X."))
    cl = _clusters(v)["Coverage terminology not recognised"]
    assert cl["score_neutral"] is True
    assert cl["resolution"]["mode"] == "none"


def test_the_loss_conflict_cluster_carries_no_promise():
    v = _view(make_issue("loss_history_attestation_conflict", "soft_warning", "Loss history conflict."))
    assert _clusters(v)["Loss history conflict"]["score_neutral"] is False


def test_a_cluster_is_neutral_only_when_EVERY_member_is():
    """One scoring member makes the sentence false for the whole cluster."""
    mixed = [
        {"code": "unmapped_coverage_line", "severity": "advisory",
         "message": "a", "cluster": "Shared", "tier": "recommended"},
        {"code": "loss_history_attestation_conflict", "severity": "soft_warning",
         "message": "b", "cluster": "Shared", "tier": "recommended"},
    ]
    assert _clusters(build_grouped_view(mixed, [], []))["Shared"]["score_neutral"] is False


def test_the_flag_is_re_derived_from_the_code_not_trusted_from_the_payload():
    """Issues reach this view from persisted sessions and legacy arrays that
    never went through make_issue, so a stale or absent key must not decide it."""
    lying = [{"code": "unmapped_coverage_line", "severity": "advisory",
              "message": "x", "score_neutral": False}]
    assert _clusters(build_grouped_view(lying, [], []))[
        "Coverage terminology not recognised"]["score_neutral"] is True

    lying_other_way = [{"code": "loss_history_attestation_conflict",
                        "severity": "soft_warning", "message": "y",
                        "score_neutral": True}]
    assert _clusters(build_grouped_view(lying_other_way, [], []))[
        "Loss history conflict"]["score_neutral"] is False


# ── 4. Placement: it stops shouting from the IMPORTANT band ─────────────────

def test_it_no_longer_displaces_a_real_item_from_important():
    """The client's screenshot had it in IMPORTANT. `binder_followup` is
    excluded from that promotion by design, so advice stops outranking work."""
    v = _view(
        make_issue("unmapped_coverage_line", "advisory", "Coverage part not recognised: X."),
        make_issue("acord125_missing", "soft_warning", "Missing baseline form."),
    )
    important = [c["cluster"] for c in v["important"]]
    assert "Coverage terminology not recognised" not in important
    assert "Missing baseline form" in important


def test_the_two_no_longer_share_one_generic_cluster():
    """Both fell into DEFAULT_CLUSTER, which put advice-only terminology and a
    pillar-capping conflict under one "Other validations" heading - and made
    the cluster mixed, so neither could carry an honest note."""
    v = _view(
        make_issue("unmapped_coverage_line", "advisory", "a"),
        make_issue("loss_history_attestation_conflict", "soft_warning", "b"),
    )
    names = set(_clusters(v))
    assert {"Coverage terminology not recognised", "Loss history conflict"} <= names
    assert "Other validations" not in names


# ── 5. Nothing about the score itself moved ─────────────────────────────────

def test_retyping_the_loss_conflict_changes_no_count_and_no_cap():
    """`structured_issues` is read by build_grouped_view and the audit export
    and by NOTHING in any scoring path; advisory and soft_warning land in the
    same warning bucket, so the retype is display-only."""
    as_advisory = _view(make_issue("loss_history_attestation_conflict", "advisory", "b"))
    as_warning = _view(make_issue("loss_history_attestation_conflict", "soft_warning", "b"))
    assert as_advisory["counts"] == as_warning["counts"]
    assert as_advisory["counts"]["hard_stops"] == 0


def test_a_score_neutral_item_is_still_counted_and_still_listed():
    """Owner: keep them in the warnings list. The note explains, it never hides."""
    v = _view(make_issue("unmapped_coverage_line", "advisory", "Coverage part not recognised: X."))
    assert v["counts"]["warnings"] == 1
    assert "Coverage terminology not recognised" in _clusters(v)
