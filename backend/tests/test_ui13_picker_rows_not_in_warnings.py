"""UI-13: a Data Consistency row does not ALSO print as a warning (2026-09-09).

CLIENT REPORT (UI-13, "Submission review navigation"): a control in the review
area performs no substantive action - it just pushes the producer back up the
page. The control was "Fix in Data Consistency", and the reason it existed at
all is that the same conflict was rendered TWICE on the review screen:

    Data Consistency  (top of the screen)
      Carrier - EMPLOYERS MUTUAL CASUALTY COMPANY | AAIS | EMC Property &
      Casualty Company    [each document's value, a suggestion, Confirm]

    REQUIRED BEFORE SUBMISSION -> DOCUMENT IDENTITY & DATE CONFLICTS  (below)
      Carrier: documents disagree (...). Fix: Confirm the correct value to
      apply it across forms.   [^ Fix in Data Consistency] [Resolve] [Dismiss]

OWNER RULING: the producer fixes it in Data Consistency, so the warnings copy
goes. WARNINGS ONLY - a blocking conflict keeps its red row.

Every assertion drives the real `build_grouped_view`, and the two sweeps drive
the real `RECONCILABLE_FIELDS` / `HARD_STOP_RECONCILABLE_KEYS` declarations
rather than a list of field names copied into this file, so a fact added to the
picker tomorrow is covered the day it ships.
"""
import pytest

from services.issue_registry import (
    build_grouped_view, diff_grouped_views, make_issue, picker_fact_key,
)
from services.underwriting_consistency import (
    HARD_STOP_RECONCILABLE_KEYS, RECONCILABLE_FIELD_KEYS,
)

# The client's literal screenshot rows.
CAR = ("Carrier: documents disagree (EMPLOYERS MUTUAL CASUALTY COMPANY, AAIS, "
       "EMC Property & Casualty Company). "
       "Fix: Confirm the correct value to apply it across forms.")
POL = ("Policy Number: documents disagree (6E7-40-02---26, 6C7-40-02---26, "
       "IM 7100 06 04, IM 7201 10 02, 6J7-40-02---26, BBC7263 - 26, BBC7263, "
       "6E74002, 6J74002). Fix: Confirm the correct value to apply it across forms.")
CON = ("Contact Name: documents disagree (Terri Wroblewski, Erin [LastName]). "
       "Fix: Confirm the correct value to apply it across forms.")
CLIENT_ROWS = [
    ("underwriting_reconciliation_carrier_name", CAR),
    ("underwriting_reconciliation_policy_number", POL),
    ("underwriting_reconciliation_contact_name", CON),
]

# Warnings from OTHER sources, which must never be affected.
OTHER = "Total payroll is missing. Fix: Provide the annual payroll figure."
SOURCE_CONFLICT = "Number of Employees differs across documents: 23, 25."


def _messages(view):
    """Every message the view RENDERS. `important` is excluded on purpose - it
    is an echo of the top warning clusters, so counting it would report a row
    twice (the same reason `counts` excludes it)."""
    out = []
    clusters = list(view.get("hard_stops") or []) + [
        c for tier in (view.get("warnings") or {}).values() for c in tier]
    for cluster in clusters:
        for item in (cluster.get("items") or [cluster]):
            if item.get("message"):
                out.append(item["message"])
    return out


def _warning_messages(view):
    out = []
    for tier in (view.get("warnings") or {}).values():
        for cluster in tier:
            for item in (cluster.get("items") or [cluster]):
                if item.get("message"):
                    out.append(item["message"])
    return out


# -- 1. The reported case, verbatim ------------------------------------------

def test_the_client_screenshot_rows_are_gone_from_the_warnings():
    issues = [make_issue(c, "soft_warning", m) for c, m in CLIENT_ROWS]
    issues.append(make_issue("legacy_soft_payroll", "soft_warning", OTHER))
    soft = [m for _c, m in CLIENT_ROWS] + [OTHER]

    rendered = _messages(build_grouped_view(issues, [], soft))

    for _code, msg in CLIENT_ROWS:
        assert msg not in rendered, "Data Consistency already shows this row"
    # The unrelated warning is untouched - this is a targeted removal, not a
    # quieter warnings section.
    assert OTHER in rendered


def test_the_counts_follow_so_the_toast_cannot_announce_a_hidden_row():
    """The completion toast and the next-step banner read `counts`. A hidden
    row that is still counted is the 2026-08-12 defect in reverse."""
    issues = [make_issue(c, "soft_warning", m) for c, m in CLIENT_ROWS]
    view = build_grouped_view(issues, [], [m for _c, m in CLIENT_ROWS])
    assert view["counts"] == {"hard_stops": 0, "warnings": 0}
    assert _messages(view) == []
    assert view["important"] == []


def test_the_row_is_not_resurrected_under_other_validations():
    """The sentence is STILL in the caller's soft_stops (it is the 85-cap
    input), and the safety net re-adds anything it cannot find in the enriched
    list. Without the local trim the row reappeared as `uncovered_soft_stop`
    under "Other validations" - no card, same sentence, worse cluster."""
    view = build_grouped_view(
        [make_issue("underwriting_reconciliation_carrier_name", "soft_warning", CAR)],
        [], [CAR])
    codes = [i["code"] for tier in view["warnings"].values() for c in tier
             for i in (c.get("items") or [])]
    assert "uncovered_soft_stop" not in codes
    assert _messages(view) == []


def test_an_annotated_stop_string_is_not_resurrected_either():
    """A caller may append "(Affects: ...)" to the stored sentence, so the trim
    matches the same way the safety net's own `_covered_by` does."""
    view = build_grouped_view(
        [make_issue("underwriting_reconciliation_carrier_name", "soft_warning", CAR)],
        [], [CAR + " (Affects: ACORD 125, ACORD 25)"])
    assert _messages(view) == []


# -- 2. A blocker is never hidden --------------------------------------------

def test_a_blocking_picker_row_keeps_its_red_card():
    name = ("Applicant / Named Insured: documents disagree (ORBIN CONTRACTING "
            "LLC, Orbin Contract). Fix: Confirm the correct value to apply it "
            "across forms.")
    view = build_grouped_view(
        [make_issue("underwriting_reconciliation_applicant_name", "hard_stop", name)],
        [name], [])
    assert view["counts"]["hard_stops"] == 1
    assert name in _messages(view)


@pytest.mark.parametrize("key", sorted(HARD_STOP_RECONCILABLE_KEYS))
def test_every_blocking_picker_field_still_renders(key):
    """Driven off the real declaration: if a field is added to
    HARD_STOP_RECONCILABLE_KEYS, its blocker must still reach the screen."""
    msg = "%s: documents disagree (A, B). Fix: Confirm the correct value." % key
    view = build_grouped_view(
        [make_issue("underwriting_reconciliation_%s" % key, "hard_stop", msg)],
        [msg], [])
    assert msg in _messages(view)


def test_a_promoted_row_keeps_its_card():
    """A row the package scorer is capping at 60 renders as the blocker it is -
    and since UI-13 that promotion is the ONLY thing keeping it on this screen,
    so hiding it would take the cap's explanation with it."""
    bv = ("Building Value: documents disagree ($1,200,000, $950,000). "
          "Fix: Confirm the correct value to apply it across forms.")
    code = "underwriting_reconciliation_property_building_value"
    view = build_grouped_view([make_issue(code, "soft_warning", bv)], [], [bv],
                              promote_codes=[code])
    assert view["counts"]["hard_stops"] == 1
    assert bv in _messages(view)


# -- 3. Nothing else moves ---------------------------------------------------

def test_non_picker_warnings_are_untouched():
    issues = [
        make_issue("source_conflict_num_employees", "soft_warning", SOURCE_CONFLICT),
        make_issue("legacy_soft_payroll", "soft_warning", OTHER),
    ]
    view = build_grouped_view(issues, [], [SOURCE_CONFLICT, OTHER])
    rendered = _warning_messages(view)
    assert SOURCE_CONFLICT in rendered
    assert OTHER in rendered
    assert view["counts"]["warnings"] == 2


def test_a_doc_conflict_row_survives_when_the_picker_never_fired():
    """Suppression keys off the PICKER's own code, so the other engine's row on
    a field the picker does not assess is unaffected."""
    lob = ("Lines of business differ across documents: Commercial General "
           "Liability, Commercial Property")
    view = build_grouped_view(
        [make_issue("doc_conflict_warn_lines_of_business", "soft_warning", lob)],
        [], [lob])
    assert lob in _warning_messages(view)


def test_the_callers_stop_arrays_are_not_mutated():
    """Those arrays drive the SQS caps, dismiss credit and issue_id hashing.
    Display work may never touch them."""
    hard, soft = [], [CAR, OTHER]
    hard_before, soft_before = list(hard), list(soft)
    build_grouped_view(
        [make_issue("underwriting_reconciliation_carrier_name", "soft_warning", CAR)],
        hard, soft)
    assert hard == hard_before
    assert soft == soft_before


# -- 4. Derived, not a list --------------------------------------------------

@pytest.mark.parametrize("key", sorted(RECONCILABLE_FIELD_KEYS))
def test_no_curated_picker_field_prints_as_a_warning(key):
    """The whole real declaration, one field at a time. A picker field whose
    conflict is non-blocking must never render in the warnings list."""
    if key in HARD_STOP_RECONCILABLE_KEYS:
        pytest.skip("blocking field - covered by the hard-stop sweep")
    msg = ("%s: documents disagree (A, B). "
           "Fix: Confirm the correct value to apply it across forms." % key)
    view = build_grouped_view(
        [make_issue("underwriting_reconciliation_%s" % key, "soft_warning", msg)],
        [], [msg])
    assert _messages(view) == []


def test_a_fact_nobody_has_added_yet_is_covered():
    """The rule reads the CODE, so a field added to the picker in a later
    release needs no change here."""
    code = "underwriting_reconciliation_some_fact_added_in_2027"
    assert picker_fact_key(code) == "some_fact_added_in_2027"
    msg = "Some Fact: documents disagree (A, B). Fix: Confirm the correct value."
    assert _messages(build_grouped_view(
        [make_issue(code, "soft_warning", msg)], [], [msg])) == []


# -- 5. The remediation diff must not report a phantom fix -------------------

def test_the_diff_does_not_report_a_hidden_row_as_resolved():
    """`recalculate_session_scores` builds the prior and current views through
    this same function, so a row hidden on both sides must produce no cluster
    change - otherwise every recalculation would congratulate the producer for
    fixing a conflict that is still open in the picker."""
    issues = [make_issue(c, "soft_warning", m) for c, m in CLIENT_ROWS]
    soft = [m for _c, m in CLIENT_ROWS]
    diff = diff_grouped_views(build_grouped_view(issues, [], soft),
                              build_grouped_view(issues, [], soft))
    assert not diff.get("resolved")
    assert not diff.get("new")
