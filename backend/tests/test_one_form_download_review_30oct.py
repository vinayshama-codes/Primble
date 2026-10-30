"""Owner, 30 Oct 2026: a one-form download reviews only what holds that form."""
from services.needs_attention import rows_for_form, row_form_ids

ROWS = [
    {"rec_id": "fieldqa_attn_ACORD_125_missing", "message": "ACORD 125 - Missing (19): ..."},
    {"rec_id": "fieldqa_attn_ACORD_126_missing", "message": "ACORD 126 - Missing (13): ..."},
    {"rec_id": "fieldqa_hardblock_ACORD_140_X", "form_id": "ACORD_140", "component": "ACORD_140",
     "message": "ACORD 140: construction type is required"},
    {"rec_id": "iss_1", "component": "ACORD_101", "forms": ["ACORD_101"],
     "message": "ACORD 125's Prior Carrier Information has no column for 3 expiring policies"},
    {"rec_id": "iss_gl", "message": "GL coverage detected but no class codes found"},
    {"rec_id": "iss_pkg", "message": "Some package-wide sentence no rule group knows"},
    {"rec_id": "fieldqa_attn_ACORD_137_CO_verify", "message": "ACORD 137 CO - Please verify (11)"},
]


def _ids(form):
    return [r["rec_id"] for r in rows_for_form(ROWS, form)]


def test_a_one_form_download_lists_only_that_forms_rows_and_package_rows():
    assert _ids("ACORD_126") == ["fieldqa_attn_ACORD_126_missing", "iss_gl", "iss_pkg"]
    assert _ids("ACORD_140") == ["fieldqa_hardblock_ACORD_140_X", "iss_pkg"]
    assert "iss_1" in _ids("ACORD_125") and "iss_1" in _ids("ACORD_101")
    assert "iss_gl" not in _ids("ACORD_127")
    assert _ids("ACORD_137_CO") == ["iss_pkg", "fieldqa_attn_ACORD_137_CO_verify"]


def test_row_forms_and_bad_input():
    assert row_form_ids({"message": "ACORD 137 CO - Please verify"}) == {"ACORD_137_CO"}
    assert row_form_ids({"message": "Package sentence"}) == set()
    assert rows_for_form([None, 5, {}], "ACORD_126") == [{}] or rows_for_form([None, 5, {}], "ACORD_126") == []


def test_a_card_only_some_forms_list_belongs_to_those_forms():
    """Live d75d50c5: ACORD 186's "Contractors Supplement: add contractor license
    number" carried no form tag and showed on the ACORD 127 download. A card some
    forms' scores list (not all) belongs to those forms."""
    from services.needs_attention import rows_for_form
    gen = {"ACORD_127": {"sqs": {"recommendations": [{"rec_id": "rec_pkg"}]}},
           "ACORD_186": {"sqs": {"recommendations": [{"rec_id": "rec_pkg"},
                                                     {"rec_id": "rec_contractor_license_number"}]}}}
    rows = [{"rec_id": "rec_contractor_license_number", "message": "Contractors Supplement: add contractor license number"},
            {"rec_id": "rec_pkg", "message": "Package item"}]
    one127 = [r["rec_id"] for r in rows_for_form(rows, "ACORD_127", gen)]
    one186 = [r["rec_id"] for r in rows_for_form(rows, "ACORD_186", gen)]
    assert one127 == ["rec_pkg"]
    assert one186 == ["rec_contractor_license_number", "rec_pkg"]


def test_every_open_package_issue_is_on_every_one_form_download():
    """Live 130ad4f4: the ACORD 126 download listed 1 of 8 open items - the
    package's COPE hard stop, its key details (whose sentences name ACORD 125) and
    the proposed-term check were judged by "does it hold this form". A package
    issue is listed on every one-form download; a form issue only on its forms."""
    from services.needs_attention import rows_for_form
    rows = [
        {"rec_id": "iss_cope", "review_issue": True, "code": "legacy_minimum_viable_cope",
         "recommendation_type": "hard_stop", "forms": [],
         "message": "Property Minimum Viable COPE incomplete - missing: occupancy type"},
        {"rec_id": "iss_mail", "review_issue": True, "code": "tier1_missing_Applicant mailing address",
         "recommendation_type": "soft_warning", "forms": [],
         "message": "ACORD 125 minimum field missing: Applicant mailing address"},
        {"rec_id": "iss_term", "review_issue": True, "code": "proposed_term_coverage_gap",
         "recommendation_type": "soft_warning", "forms": ["ACORD_125"], "cross_form": True,
         "message": "The proposed effective date is 365 days after the current policies expire"},
        {"rec_id": "iss_101", "review_issue": True, "code": "acord101_for_expiring_policies",
         "recommendation_type": "soft_warning", "forms": ["ACORD_101"], "cross_form": True,
         "message": "ACORD 125's Prior Carrier Information has no column for 6 expiring policies"},
    ]
    got = {r["rec_id"] for r in rows_for_form(rows, "ACORD_126", {})}
    assert got == {"iss_cope", "iss_mail", "iss_term"}
    assert "iss_101" in {r["rec_id"] for r in rows_for_form(rows, "ACORD_101", {})}


def test_a_legacy_stop_and_its_coded_twin_are_one_download_row():
    """Live 130ad4f4: the missing occupancy was listed as a hard stop AND a
    warning. One row - the hard stop, since a blocker is never hidden."""
    from services.needs_attention import fold_twin_issues
    rows = [
        {"rec_id": "a", "review_issue": True, "code": "legacy_minimum_viable_cope",
         "recommendation_type": "hard_stop",
         "message": "Property Minimum Viable COPE incomplete - missing: occupancy type"},
        {"rec_id": "b", "review_issue": True, "code": "minimum_viable_cope_missing",
         "recommendation_type": "soft_warning",
         "message": "Property submission missing Minimum Viable COPE: occupancy type."},
        {"rec_id": "c", "review_issue": True, "code": "legacy_gl_no_class_codes",
         "recommendation_type": "soft_warning", "message": "GL class codes are missing"},
    ]
    assert [r["rec_id"] for r in fold_twin_issues(rows)] == ["a", "c"]
    # Both warnings: the coded row (it carries the fix) is kept.
    rows[0]["recommendation_type"] = "soft_warning"
    assert [r["rec_id"] for r in fold_twin_issues(rows)] == ["b", "c"]


def test_any_duplicate_row_is_listed_once_hard_stop_wins():
    """Not one twin: any two rows that say the same problem are one row."""
    from services.needs_attention import fold_twin_issues
    rows = [
        {"rec_id": "w", "review_issue": True, "code": "x", "recommendation_type": "soft_warning",
         "message": "Proposed term is missing."},
        {"rec_id": "h", "review_issue": True, "code": "y", "recommendation_type": "hard_stop",
         "message": "Proposed  term is MISSING"},
        {"rec_id": "i1", "review_issue": True, "issue_id": "abc", "message": "One wording"},
        {"rec_id": "i2", "review_issue": True, "issue_id": "abc", "message": "Another wording"},
        # Same words on two forms' boxes stay two rows.
        {"rec_id": "b1", "form_id": "ACORD_126", "field": "Policy_A", "message": "Missing: policy number"},
        {"rec_id": "b2", "form_id": "ACORD_127", "field": "Policy_A", "message": "Missing: policy number"},
    ]
    assert [r["rec_id"] for r in fold_twin_issues(rows)] == ["h", "i1", "b1", "b2"]


def test_the_same_rule_worded_twice_is_one_download_row():
    """Live d56e445b: one ACORD 101 check raised twice, its list in another order."""
    from services.needs_attention import fold_twin_issues
    a = {"rec_id": "i1", "review_issue": True, "code": "acord101_for_expiring_policies", "forms": ["ACORD_101"],
         "recommendation_type": "soft_warning", "message": "ACORD 125's Prior Carrier Information has no column for 6 expiring policies (Cyber, Crime)."}
    b = dict(a, rec_id="i2", message="ACORD 125's Prior Carrier Information has no column for 6 expiring policies (Crime, Cyber).")
    c = {"rec_id": "i3", "review_issue": True, "code": "per_location_cope_incomplete", "forms": ["ACORD_140"],
         "recommendation_type": "soft_warning", "message": "12 Main St: COPE incomplete (year built)."}
    d = dict(c, rec_id="i4", message="40 Oak Ave: COPE incomplete (year built).")
    assert [r["rec_id"] for r in fold_twin_issues([a, b, c, d])] == ["i1", "i3", "i4"]


def test_a_form_held_by_its_own_boxes_is_on_its_download():
    """Live d56e445b: ACORD 125 at 85 (required boxes) - the download screen was empty."""
    from services.needs_attention import form_hold_rows
    gen = {"ACORD_125": {"sqs": {"sqs_score": 85, "raw_sqs_score": 100, "cap_applied": 85,
                                 "cap_reason": "ACORD 125: required box still empty - Number of members (+11 more)"}},
           "ACORD_127": {"sqs": {"sqs_score": 100, "raw_sqs_score": 100, "cap_applied": None, "cap_reason": None}},
           "ACORD_140": {"sqs": {"sqs_score": 60, "raw_sqs_score": 90, "cap_applied": 60,
                                 "cap_reason": 'ACORD 140: "Construction type" is required before download'}}}
    rows = form_hold_rows([], gen)
    assert [(r["rec_id"], r["recommendation_type"]) for r in rows] == [
        ("formhold_ACORD_125", "soft_warning"), ("formhold_ACORD_140", "hard_stop")]
    # a listed warning already saying it: no second row
    listed = [{"recommendation_type": "soft_warning", "message": gen["ACORD_125"]["sqs"]["cap_reason"]}]
    assert [r["rec_id"] for r in form_hold_rows(listed, gen)] == ["formhold_ACORD_140"]
