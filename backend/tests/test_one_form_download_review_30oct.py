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
