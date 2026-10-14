"""One stop, drawn once (14 Oct 2026, the owner's package f83757cf).

After a different insured's dec was kept, the review page printed "Applicant name
differs across documents" THREE times - the coded document-conflict card, the Data
Consistency picker card and a NUMBERED legacy copy (`legacy_hard_0`) of the same
sentence - and counted 4 hard stops for 2 problems. The numbered copy is the stop
arrays stored a second time; it also defeated the picker's supersession, whose
guard never trims a sentence another row still carries.
"""
from services.issue_registry import _drop_numbered_echoes, build_grouped_view, make_issue

NAME = ("Applicant name differs across documents: CHOICE ELECTRIC LLC, MERIDIAN FABRICATION INC "
        "(Source: control_dec.pdf. Fix: Confirm the correct value in the Data Consistency section below.)")
ENTITY = ("Entity type differs across documents: Limited Liability Company, Corporation (Source: "
          "control_dec.pdf. Fix: Confirm the correct value in the Data Consistency section below.)")


def _rows():
    return [
        make_issue("doc_conflict_hard_name_conflict", "hard_stop", NAME),
        make_issue("underwriting_reconciliation_applicant_name", "hard_stop",
                   "Applicant / Named Insured: documents disagree (CHOICE ELECTRIC LLC, MERIDIAN FABRICATION INC)."),
        make_issue("doc_conflict_warn_entity_type", "soft_warning", ENTITY),
        make_issue("underwriting_reconciliation_entity_type", "soft_warning",
                   "Entity Type: documents disagree (Limited Liability Company, Corporation)."),
        make_issue("legacy_hard_0", "hard_stop", NAME),
        make_issue("legacy_soft_2", "soft_warning", ENTITY),
    ]


def _items(view, key):
    if key == "hard_stops":
        return [it for c in view.get("hard_stops") or [] for it in c.get("items") or []]
    return [it for cl in (view.get("warnings") or {}).values() for c in cl for it in c.get("items") or []]


def test_the_live_shape_draws_each_problem_once():
    v = build_grouped_view(_rows(), [NAME], [ENTITY])
    hard = _items(v, "hard_stops")
    assert [i["code"] for i in hard] == ["underwriting_reconciliation_applicant_name"]
    assert v["counts"]["hard_stops"] == 1
    assert not any(str(i.get("code", "")).startswith("legacy_") for i in hard + _items(v, "warnings"))


def test_a_numbered_row_with_no_coded_twin_stays():
    lone = make_issue("legacy_soft_0", "soft_warning", "Something no rule classifies.")
    assert _drop_numbered_echoes([lone]) == [lone]


def test_a_hard_copy_is_never_dropped_beside_a_warning_twin():
    rows = [make_issue("doc_conflict_warn_name_conflict", "soft_warning", NAME),
            make_issue("legacy_hard_0", "hard_stop", NAME)]
    assert [r["code"] for r in _drop_numbered_echoes(rows)] == ["doc_conflict_warn_name_conflict", "legacy_hard_0"]


def test_a_rule_coded_legacy_row_is_not_touched():
    rows = [make_issue("doc_conflict_hard_name_conflict", "hard_stop", NAME),
            make_issue("legacy_carrier_grade_cope", "soft_warning", NAME)]
    assert len(_drop_numbered_echoes(rows)) == 2
