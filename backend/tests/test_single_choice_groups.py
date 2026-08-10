"""Checkbox families where ACORD's own wording allows only one tick.

Client report (ACORD 125, Orbin Contracting) #4:
  "Both Issue Policy and Bound are populated, but no bound date is provided.
   Fix: Select the appropriate status."

THE CLIENT IS PARTLY WRONG HERE, and the schemas say so. ACORD's tooltips put
those two boxes in different families:

    Policy_Status_IssueIndicator - "Indicates the RESPONSE EXPECTED FROM THE
                                    COMPANY is an issued policy."
    Policy_Status_BoundIndicator - "Indicates the COVERAGE HAS BEEN BOUND."

One is a request, the other is a state of the coverage. "Coverage is bound,
please issue the policy" is the ordinary broker workflow, so treating them as
mutually exclusive would blank a legitimate tick.

What IS a contradiction is two boxes from the "response expected" family - you
can only expect one response. That family is DERIVED from ACORD's own phrase so
the boundary is ACORD's and not a guess: 3 boxes on ACORD 125, 3 on 130, 2 on
131, 1 on 133.

Nothing here is ever blanked. Which of two contradictory ticks is right is
genuinely unknowable at this layer; choosing would silently discard a correct
answer. Both are demoted so the broker sees the conflict.
"""
import glob
import json
import os
import re
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
os.environ.setdefault("OPENAI_API_KEY", "sk-offline-test")

import services.pdf_service as ps                        # noqa: E402

_SCHEMA_DIR = os.path.join(os.path.dirname(__file__), "..", "forms_schemas")


def _acord125():
    with open(os.path.join(_SCHEMA_DIR, "ACORD_125_schema.json"), encoding="utf-8") as fh:
        return json.load(fh)


def test_issue_plus_bound_is_not_a_contradiction():
    """THE CLIENT'S REPORTED CASE - and it must NOT be flagged. Different
    families per ACORD's own tooltips; blanking either would lose a real tick."""
    mapped = {
        "Policy_Status_IssueIndicator_A": "Yes",
        "Policy_Status_BoundIndicator_A": "Yes",
    }
    assert ps._contradictory_single_choice_fields(mapped, _acord125()) == set()


def test_two_expected_responses_is_a_contradiction():
    mapped = {
        "Policy_Status_QuoteIndicator_A": "Yes",
        "Policy_Status_IssueIndicator_A": "Yes",
    }
    assert ps._contradictory_single_choice_fields(mapped, _acord125()) == {
        "Policy_Status_QuoteIndicator_A",
        "Policy_Status_IssueIndicator_A",
    }


def test_bound_is_never_dragged_into_the_conflict():
    """Even alongside a real contradiction, Bound is a separate statement."""
    mapped = {
        "Policy_Status_QuoteIndicator_A": "Yes",
        "Policy_Status_IssueIndicator_A": "Yes",
        "Policy_Status_BoundIndicator_A": "Yes",
    }
    flagged = ps._contradictory_single_choice_fields(mapped, _acord125())
    assert "Policy_Status_BoundIndicator_A" not in flagged


def test_a_single_tick_is_never_flagged():
    for field in ("Policy_Status_QuoteIndicator_A", "Policy_Status_IssueIndicator_A",
                  "Policy_Status_RenewIndicator_A"):
        assert ps._contradictory_single_choice_fields({field: "Yes"}, _acord125()) == set()


def test_nothing_is_ever_blanked():
    """THE LOAD-BEARING GUARANTEE. The guard changes a trust label, never a
    value - this may not cost a single filled box."""
    mapped = {
        "Policy_Status_QuoteIndicator_A": "Yes",
        "Policy_Status_IssueIndicator_A": "Yes",
        "Policy_Status_BoundIndicator_A": "Yes",
    }
    before = dict(mapped)
    ps._enforce_post_fill_guards(mapped, _acord125(), {})
    assert mapped == before


def test_no_answer_or_an_explicit_no_is_not_a_tick():
    for value in ("No", "", None, "N"):
        mapped = {
            "Policy_Status_QuoteIndicator_A": "Yes",
            "Policy_Status_IssueIndicator_A": value,
        }
        assert ps._contradictory_single_choice_fields(mapped, _acord125()) == set()


# ── The group definition must stay ACORD's, not ours ─────────────────────────

def test_groups_are_derived_from_a_real_acord_tooltip_phrase():
    """STANDING GUARD. Every marker must actually appear in a shipped schema; a
    marker matching nothing silently disables the check."""
    tooltips = []
    for path in glob.glob(os.path.join(_SCHEMA_DIR, "*_schema.json")):
        with open(path, encoding="utf-8") as fh:
            tooltips += [
                ((m or {}).get("tu") or "").lower() for m in json.load(fh).values()
            ]
    assert tooltips
    for marker in ps._SINGLE_CHOICE_TOOLTIP_MARKERS:
        assert any(marker in t for t in tooltips), (
            f"marker {marker!r} matches no tooltip on any of the 17 forms"
        )


def test_expected_group_membership_across_all_forms():
    """Pins the blast radius: 4 forms, 9 boxes. A jump means the marker started
    matching something it should not."""
    pattern = re.compile(ps._SINGLE_CHOICE_TOOLTIP_MARKERS[0], re.I)
    counts = {}
    for path in sorted(glob.glob(os.path.join(_SCHEMA_DIR, "*_schema.json"))):
        form_id = os.path.basename(path).replace("_schema.json", "")
        with open(path, encoding="utf-8") as fh:
            schema = json.load(fh)
        hits = [f for f, m in schema.items() if pattern.search((m or {}).get("tu") or "")]
        if hits:
            counts[form_id] = len(hits)
    assert counts == {"ACORD_125": 3, "ACORD_130": 3, "ACORD_131": 2, "ACORD_133": 1}, counts


def test_every_group_member_is_a_checkbox():
    """A single-choice family only makes sense for checkboxes."""
    for path in glob.glob(os.path.join(_SCHEMA_DIR, "*_schema.json")):
        with open(path, encoding="utf-8") as fh:
            schema = json.load(fh)
        keys = tuple(schema.keys())
        tips = tuple((schema.get(k) or {}).get("tu") or "" for k in keys)
        for group in ps._single_choice_groups(keys, tips):
            for field in group:
                assert schema[field].get("ft") == "/Btn", field


def test_a_form_with_one_member_forms_no_group():
    """ACORD 133 has a single "expected response" box - nothing to contradict."""
    with open(os.path.join(_SCHEMA_DIR, "ACORD_133_schema.json"), encoding="utf-8") as fh:
        schema = json.load(fh)
    keys = tuple(schema.keys())
    tips = tuple((schema.get(k) or {}).get("tu") or "" for k in keys)
    assert ps._single_choice_groups(keys, tips) == ()
