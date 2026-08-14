"""C75: a hard stop renders as a hard stop, and a suggestion is not a blocker.

OWNER'S RULE (2026-08-14), verbatim: "If it is a hard stop then show it on the
hard stop not on the warning ... every hardstop/warning should be shown to
user."

TWO DEFECTS, one shared shape - a decision made for one consumer and ignored by
the other:

1. `classify_stops` demotes a hard stop for the PROCEED decision, and the
   display honoured the demotion while the scorer kept reading the raw list.
   Measured on the live ORBIN session: grouped counts said
   {hard_stops: 0, warnings: 1} and the banner read "caps your SQS at 85",
   while the score was capped at 60 by that same stop. The producer was shown
   the wrong severity AND the wrong penalty. The display now reads the same
   arrays the scorer reads, so the two can never disagree. `warning_stops`
   still carries the demoted list, because that is what powers the
   "proceed anyway" banner - the demotion still decides whether you MAY
   proceed, it just no longer decides what you SEE.

2. Cross-form rules run against `triggered_ids`, which pre-selection is the
   RECOMMENDED forms. So a form the producer never chose could raise a hard
   stop about its own missing data - and cap the score by 8 points. Client
   report: "there should not be any Builders Risk questions or an ACORD 133 -
   there is no builders risk exposure". Demoted generically for every
   form-scoped rule, not special-cased to builders risk; the issue stays
   VISIBLE as a warning and returns to full force once that form is selected.
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("OPENAI_API_KEY", "sk-offline")

from services.issue_registry import build_grouped_view          # noqa: E402
from services.sqs_service import classify_stops                 # noqa: E402

ROUTES = open(os.path.join(os.path.dirname(__file__), "..", "routes",
                           "form_routes.py"), encoding="utf-8").read()
PIPELINE = open(os.path.join(os.path.dirname(__file__), "..", "services",
                             "extraction_pipeline.py"), encoding="utf-8").read()

# The live ORBIN stop, verbatim.
_EXPIRED = ("Policy term already expired (07/15/26) - the application proposes "
            "a period that ended. Fix: Update the proposed effective and "
            "expiration dates to the term being applied for.")


# ── 1. Severity on screen matches severity in the score ─────────────────────

def test_the_demoted_stop_is_still_a_hard_stop_on_screen():
    """THE LIVE CASE. On a non-property submission this stop is demoted, and
    the screen used to show it as a warning while the score capped at 60."""
    _can, remaining, downgraded = classify_stops([_EXPIRED],
                                                 {"has_property_coverage": False})
    assert remaining == [] and len(downgraded) == 1, "precondition: it demotes"
    # What the screen used to be given:
    old = build_grouped_view([], remaining, downgraded)["counts"]
    assert old == {"hard_stops": 0, "warnings": 1}
    # What it is given now - the same arrays the scorer reads:
    new = build_grouped_view([], [_EXPIRED], [])["counts"]
    assert new == {"hard_stops": 1, "warnings": 0}


def test_no_call_site_still_feeds_the_display_the_demoted_lists():
    """ANTI-ROT across all five route call sites: the display must never be
    handed `_remaining_hard`, and must never append `_downgraded` to the soft
    list (which would show the same item twice)."""
    assert "_remaining_hard, _final_soft_stops" not in ROUTES
    assert "+ _downgraded" not in ROUTES


def test_the_proceed_anyway_banner_keeps_its_data():
    """`warning_stops` powers the 'proceed anyway' affordance. Emptying it
    would delete a working feature while fixing the severity."""
    assert '"warning_stops": _downgraded' in ROUTES


def test_nothing_is_dropped_from_the_screen_by_the_demotion():
    """The owner's real worry: is anything vanishing entirely? Every raw stop
    must appear in the rendered clusters - count in, count out."""
    hard = [_EXPIRED, "FEIN differs across documents"]
    soft = ["GL coverage detected but no class codes found"]
    counts = build_grouped_view([], hard, soft)["counts"]
    assert counts["hard_stops"] + counts["warnings"] == len(hard) + len(soft)


# ── 2. A recommended-only form cannot raise a blocker ───────────────────────

def test_pre_selection_cross_form_hard_stops_become_warnings():
    assert "Cross-form hard stops demoted to warnings pre-selection" in PIPELINE
    assert "soft_stops = list(soft_stops) + cf_hard" in PIPELINE
    assert "cf_hard = []" in PIPELINE


def test_the_demoted_cross_form_card_matches_the_array_it_lives_in():
    """A demoted issue must not still render as a hard-stop CARD - severity
    has to move on both copies or the screen contradicts itself again."""
    assert 'if _t == "hard_stop":' in PIPELINE
    assert '_t = "soft_warning"' in PIPELINE


def test_the_issue_is_demoted_not_discarded():
    """The owner's rule is that nothing disappears. A demoted cross-form issue
    must still reach the soft list and still get a card."""
    assert "cf_soft = list(cf_soft) + cf_hard" in PIPELINE
    assert "structured_issues.append(make_issue(" in PIPELINE


# ── 3. Blocking means hard stop, and relevance is a precondition ────────────

def test_a_generation_blocking_conflict_is_raised_as_a_hard_stop():
    """The client's own directive for building value is 'require review BEFORE
    FORMS ARE GENERATED' - blocking - and the scorer has always capped at 60
    for it. The display said 'warning'. Owner's rule: blocking = hard stop."""
    assert '"hard_stop" if _blocking else "soft_warning"' in PIPELINE
    assert "hard_stops = list(hard_stops) + [_uw_msg]" in PIPELINE


def test_the_blocking_keys_come_from_the_declared_sets_not_a_local_list():
    """ANTI-ROT: a second copy of 'which fields block' is how these two layers
    drifted apart in the first place."""
    assert "HARD_STOP_RECONCILABLE_KEYS" in PIPELINE
    assert "GENERATION_BLOCKING_RECONCILABLE_KEYS" in PIPELINE


def test_the_declared_sets_still_contain_what_this_relies_on():
    """If someone empties these, the hard-stop routing silently stops."""
    from services.underwriting_consistency import (
        HARD_STOP_RECONCILABLE_KEYS, GENERATION_BLOCKING_RECONCILABLE_KEYS,
    )
    assert "property_building_value" in GENERATION_BLOCKING_RECONCILABLE_KEYS
    assert {"applicant_name", "fein"} <= set(HARD_STOP_RECONCILABLE_KEYS)


def test_an_irrelevant_conflict_is_not_a_blocker():
    """Owner: 'it should only be shown if declaration page has some relevant
    data'. With no property coverage there is no ACORD 140 to generate and no
    box for the number, so a building-value disagreement cannot block - it
    stays a visible warning rather than capping the score."""
    assert '"property_building_value": "has_property_coverage"' in PIPELINE
    assert "_blocking = _key in _blocking_keys and _relevant" in PIPELINE


def test_an_irrelevant_conflict_is_still_shown():
    """Relevance downgrades severity; it must never delete the issue."""
    _i = PIPELINE.index("_blocking = _key in _blocking_keys and _relevant")
    _block = PIPELINE[_i:_i + 900]
    assert "soft_stops = list(soft_stops) + [_uw_msg]" in _block
    assert "structured_issues.append(make_issue(" in _block


# ── 4. One problem, one row (the umbrella period duplicate) ─────────────────

_UMB_CODED = ("Umbrella expiration date (07/15/2026) does not match GL/policy "
              "expiration date (08/15/26). Periods must align or be explained "
              "via ACORD 101.")
_UMB_LEGACY = ("Umbrella and GL expiration dates misaligned. "
               "Fix: Review and correct this before proceeding.")


def test_the_umbrella_period_duplicate_collapses_to_one_row():
    """LIVE 2026-08-14: the same problem rendered twice - the coded rule as a
    HARD stop naming both dates, and the legacy string as a separate WARNING.
    Resolving the hard stop left its twin in the warnings column, which is what
    made warnings look like they only appear after hard stops are cleared."""
    counts = build_grouped_view(
        [{"code": "legacy_umbrella_gl_expiration_misaligned", "message": _UMB_LEGACY}],
        [_UMB_CODED], [_UMB_LEGACY],
        cross_issues=[{"code": "umbrella_gl_expiration_misaligned",
                       "type": "hard_stop", "message": _UMB_CODED}],
    )["counts"]
    assert counts == {"hard_stops": 1, "warnings": 0}, counts


def test_the_legacy_twin_survives_when_the_coded_rule_did_not_fire():
    """Suppression must stay conditional: with no coded twin present the legacy
    warning is the ONLY report of the problem and must never be hidden."""
    counts = build_grouped_view(
        [{"code": "legacy_umbrella_gl_expiration_misaligned", "message": _UMB_LEGACY}],
        [], [_UMB_LEGACY], cross_issues=[],
    )["counts"]
    assert counts["warnings"] == 1


def test_every_suppression_entry_names_a_code_that_can_actually_be_emitted():
    """ANTI-ROT, and it caught a real mistake: the first version of the
    umbrella entry used the RULE name (`..._period_misaligned`) while the code
    on the wire is `..._expiration_misaligned`, so suppression was a silent
    no-op. A code no engine emits can never suppress anything."""
    import re as _re
    from services.issue_registry import _LEGACY_SUPERSEDED_BY_CODE
    cfv = open(os.path.join(os.path.dirname(__file__), "..", "services",
                            "cross_form_validator.py"), encoding="utf-8").read()
    emitted = set(_re.findall(r'"([a-z0-9_]+)"', cfv))
    missing = [c for c in _LEGACY_SUPERSEDED_BY_CODE if c not in emitted]
    assert not missing, f"suppression keyed on codes nothing emits: {missing}"


# ── 5. An empty form set is not a finding ───────────────────────────────────

def test_the_baseline_form_rule_is_silent_before_form_selection():
    """LIVE 2026-08-14: 'ACORD 125 was not detected' showed on every run BEFORE
    form selection, while the system was simultaneously RECOMMENDING ACORD 125
    (verified on the session: recommendations contained ACORD_125,
    selected_form_ids was []). A rule gated on the selected forms cannot answer
    'was it selected?' when nothing is selected."""
    from services.cross_form_validator import run_cross_form_validation as _run

    def _fires(ids):
        return any(i.get("code") == "acord125_missing" for i in _run({}, {}, ids))

    assert not _fires(set()), "an empty form set must produce no finding"
    assert _fires({"ACORD_126", "ACORD_127"}), "a real set missing 125 still warns"
    assert not _fires({"ACORD_125", "ACORD_126"})


def test_the_demotion_is_generic_not_builders_risk_special_cased():
    """ANTI-ROT: the fix must not name a single rule. If someone replaces it
    with an ACORD_133 special case, the whole class reopens."""
    _start = PIPELINE.index("A SUGGESTION MAY NOT BECOME A BLOCKER")
    _end = PIPELINE.index("cf_hard = []", _start)
    _block = PIPELINE[_start:_end]
    # The comment may CITE the client's report; the executable lines may not
    # branch on a form id.
    _code = "\n".join(
        ln for ln in _block.splitlines() if not ln.strip().startswith("#")
    )
    assert "ACORD_133" not in _code, "the demotion must stay rule-agnostic"
    assert "builders" not in _code.lower()
