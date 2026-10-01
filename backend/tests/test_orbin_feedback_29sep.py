"""Orbin client feedback of 22 Sep (Orbin_Testing_09_22_2026.pdf) - Step 1 fixes, 29 Sep 2026.

Baseline: the owner's re-run of the client's own declarations (session 8992d874,
28 Sep, ACORD 125 only), recorded in 25sepChanges.md before any change. Every
shape below is the live run's.

  item 3   no "Important" preview; "(+N related)" can never cut a Fix line
  item 6   a table a card offers is always served, whatever forms are chosen
  item 13  GL CODE from the policy's own GL class schedule
  item 17  a value the PRODUCER typed is labelled the producer's, never "Client"
  G1       the client e-mails say "Commercial Insurance Submission Platform"
  extras   Q4 line names from each policy's own declarations; a one-line
           description breaks at "; "; no New Venture card after a completed term
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))
os.environ.setdefault("OPENAI_API_KEY", "sk-offline")

import services.arq_service as arq                                  # noqa: E402
import services.email_service as email_service                      # noqa: E402
import services.pdf_service as ps                                   # noqa: E402
from services import loss_history_state as lh                       # noqa: E402
from services import sqs_service as sq                              # noqa: E402

SCHEMA = json.loads((BACKEND / "forms_schemas" / "ACORD_125_schema.json").read_text())
FRONTEND_FORM = BACKEND.parent / "frontend" / "src" / "components" / "form"


# ═════════════════════════════════════════════════════════════════════════════
# Item 3 - the "Important" preview repeated the tiers below it
# ═════════════════════════════════════════════════════════════════════════════
@pytest.mark.parametrize("path", [
    FRONTEND_FORM / "AcordModal.jsx",
    FRONTEND_FORM / "review" / "ReviewRailLayout.jsx",
])
def test_no_review_screen_renders_the_important_preview(path):
    src = path.read_text(encoding="utf-8")
    assert "groupedIssues?.important" not in src
    assert "groupedIssues.important" not in src
    # The composition that printed "states it.) (+1 related": a count suffix
    # appended AFTER a message that ends in "(Fix: ...)".
    assert "related)`" not in src


# ═════════════════════════════════════════════════════════════════════════════
# Item 6 - "Open to fix" on the driver warning opened nothing
# ═════════════════════════════════════════════════════════════════════════════
_DRIVER_ISSUE = {
    "code": "legacy_auto_driver_schedule_missing",
    "message": "Driver schedule not provided - list the drivers of the scheduled "
               "vehicles (name, licence, date of birth)",
    "resolution": {"mode": "schedule", "schedule_key": "auto_drivers"},
}


def _proc(**over):
    base = {"facts": {}, "flags": {"has_auto_coverage": True}, "generated_forms": {},
            "selected_form_ids": ["ACORD_125"], "recommendations": [],
            "structured_issues": []}
    base.update(over)
    return base


def test_offered_tables_are_read_from_the_stored_resolution():
    assert arq._schedules_offered_by_issues(_proc(structured_issues=[_DRIVER_ISSUE])) == {"auto_drivers"}


def test_an_issue_stored_without_a_resolution_is_looked_up_by_its_code():
    stored = {k: v for k, v in _DRIVER_ISSUE.items() if k != "resolution"}
    assert arq._schedules_offered_by_issues(_proc(structured_issues=[stored])) == {"auto_drivers"}


def test_a_field_card_offers_no_table():
    field_card = {"code": "tier1_missing_Contact information",
                  "resolution": {"mode": "field", "facts": ["contact_name"]}}
    assert arq._schedules_offered_by_issues(_proc(structured_issues=[field_card])) == set()


@pytest.fixture
def served(monkeypatch):
    import repositories.session_repository as repo

    def run(proc, only_key=None):
        async def _load(_sid):
            return proc
        monkeypatch.setattr(repo, "get_processing_session", _load)
        return asyncio.run(arq.get_session_schedules("s-8992", only_key=only_key))
    return run


def test_the_driver_table_opens_when_only_acord_125_is_chosen(served):
    """The live defect: ACORD 125 chosen alone, the warning on screen."""
    out = served(_proc(structured_issues=[_DRIVER_ISSUE]), only_key="auto_drivers")
    assert [s["schedule_key"] for s in out] == ["auto_drivers"]
    assert out[0]["form_ids"] == [] and out[0]["forms"] == ""


def test_without_a_card_the_driver_table_is_not_served(served):
    assert served(_proc(), only_key="auto_drivers") == []


def test_a_table_no_card_offers_stays_away(served):
    """The 23 Sep narrowing holds: nothing but a card or a chosen form adds one."""
    keys = {s["schedule_key"] for s in served(_proc(structured_issues=[_DRIVER_ISSUE]))}
    assert "auto_drivers" in keys
    assert not keys & {"wc_class_codes", "wc_officers"}


# ═════════════════════════════════════════════════════════════════════════════
# Item 13 - GL CODE blank although the dec rates 91580 and 91585
# ═════════════════════════════════════════════════════════════════════════════
_GL_BOX = "NamedInsured_GeneralLiabilityCode_A"
_ORBIN_GL_SCHEDULE = [
    {"location": "Location 001", "class_code": "91580",
     "classification": "Contractors - Executive Supervisors or Executive Superintendents",
     "premium_basis": "Payroll", "exposure_amount": "$39,300"},
    {"location": "Location 001", "class_code": "91585",
     "classification": "Contrctrs-sub work-in connection w/constrctn,recon,repr,erctn of buildings - NOC",
     "premium_basis": "Total Cost", "exposure_amount": "$350,000"},
]


def test_gl_code_prints_the_policys_own_rated_classes():
    got = ps._resolve_applicant_row_a_scalar(_GL_BOX, {"gl_class_code_schedule": _ORBIN_GL_SCHEDULE})
    assert got == "91580, 91585"


def test_a_stated_applicant_gl_code_still_wins():
    facts = {"gl_class_code_schedule": _ORBIN_GL_SCHEDULE, "applicant_gl_class_code": "92478"}
    assert ps._resolve_applicant_row_a_scalar(_GL_BOX, facts) == "92478"


def test_a_class_printed_twice_prints_once():
    rows = [{"class_code": "91580"}, {"class_code": "91580"}]
    assert ps._resolve_applicant_row_a_scalar(_GL_BOX, {"gl_class_code_schedule": rows}) == "91580"


@pytest.mark.parametrize("facts", [
    {},                                                                     # no schedule at all
    {"gl_class_code_schedule": _ORBIN_GL_SCHEDULE,                          # another entity's classes?
     "additional_named_insureds": [{"name": "Orbin Holdings LLC"}]},
    {"gl_class_code_schedule": [{"class_code": c}                           # more than the box shows
                                for c in ("91580", "91585", "91590", "91595")]},
    {"gl_class_code_schedule": [{"class_code": "8810"}]},                   # not an ISO GL code
])
def test_gl_code_leaves_todays_behaviour_when_it_could_be_wrong(facts):
    assert ps._resolve_applicant_row_a_scalar(_GL_BOX, facts) is ps._SCHED_SKIP


def test_gl_code_stamps_end_to_end_and_sic_naics_stay_blank():
    facts = {"applicant_name": "ORBIN CONTRACTING LLC", "gl_class_code_schedule": _ORBIN_GL_SCHEDULE}
    mapped, _ = ps.map_facts_to_form(facts, SCHEMA, "ACORD_125", raw_text="",
                                     pre_filled_gpt={"filled_values": {}})
    assert mapped.get(_GL_BOX) == "91580, 91585"
    assert not mapped.get("NamedInsured_GeneralLiabilityCode_B")
    assert not mapped.get("NamedInsured_SICCode_A")
    assert not mapped.get("NamedInsured_NAICSCode_A")


# ═════════════════════════════════════════════════════════════════════════════
# Item 17 - "The client didn't fill these green fields in. I did as the producer."
# ═════════════════════════════════════════════════════════════════════════════
def _generated():
    return {"ACORD_125": {"schema": SCHEMA, "field_state": {}, "confidence": {},
                          "client_filled_fields": []}}


_NAME_FACTS = {"applicant_name": "Orbin Contracting LLC"}
_NAME_BOX = "NamedInsured_FullName_A"


def test_a_producer_answer_is_labelled_the_producers():
    gen = _generated()
    arq._restamp_canonical_into_forms(gen, "applicant_name", dict(_NAME_FACTS), provenance="producer")
    form = gen["ACORD_125"]
    assert form["field_state"][_NAME_BOX]
    assert form["confidence"][_NAME_BOX] == "producer"
    assert _NAME_BOX not in form["client_filled_fields"]


def test_a_client_answer_is_still_the_clients():
    gen = _generated()
    arq._restamp_canonical_into_forms(gen, "applicant_name", dict(_NAME_FACTS))
    form = gen["ACORD_125"]
    assert form["confidence"][_NAME_BOX] == "client_arq"
    assert _NAME_BOX in form["client_filled_fields"]


def test_a_producer_overwrite_takes_the_box_off_the_client_list():
    gen = _generated()
    arq._restamp_canonical_into_forms(gen, "applicant_name", dict(_NAME_FACTS))
    arq._restamp_canonical_into_forms(gen, "applicant_name",
                                      {"applicant_name": "Orbin Contracting, LLC"}, provenance="producer")
    form = gen["ACORD_125"]
    assert form["confidence"][_NAME_BOX] == "producer"
    assert _NAME_BOX not in form["client_filled_fields"]


def test_the_producer_answer_path_stamps_as_the_producer(monkeypatch):
    """Through the real door: the "Type your answer" card and "Open to fix"."""
    import repositories.session_repository as repo
    proc = {"facts": {}, "flags": {}, "generated_forms": _generated()}
    saved = {}

    async def _load(_sid):
        return proc

    async def _save(_sid, payload, **_kw):
        saved.update(payload)

    monkeypatch.setattr(repo, "get_processing_session", _load)
    monkeypatch.setattr(repo, "upd_processing_session", _save)
    ok, _ = asyncio.run(arq.apply_producer_answer_to_session("s-8992", "applicant_name",
                                                             "Orbin Contracting LLC"))
    assert ok
    form = saved["generated_forms"]["ACORD_125"]
    assert form["confidence"][_NAME_BOX] == "producer"
    assert _NAME_BOX not in form["client_filled_fields"]


def test_a_producer_box_scores_and_passes_like_any_filled_box():
    from services.field_qa import _CONF_VERDICT
    assert sq.CONFIDENCE_SCORE["producer"] == sq.CONFIDENCE_SCORE["client_arq"] == 1.0
    assert _CONF_VERDICT["producer"] == "pass"
    assert sq.confidence_fill_rate({"a": "x"}, {"a": "producer"}) == 100


# ═════════════════════════════════════════════════════════════════════════════
# G1 - the client e-mail's tagline
# ═════════════════════════════════════════════════════════════════════════════
def test_both_client_emails_say_submission_platform(monkeypatch):
    sent = []

    def _capture(_to, _subject, _txt, html, *_a, **_k):
        sent.append(html)
        return True

    monkeypatch.setattr(email_service, "_send_generic_email", _capture)
    args = ("client@example.com", "Erin", "Michelle Smith", "Michelle", "https://example/q/1")
    email_service.send_arq_email(*args)
    email_service.send_arq_reminder_email(*args)
    assert len(sent) == 2
    for html in sent:
        assert "Commercial Insurance Submission Platform" in html
        assert "{_EMAIL_TAGLINE}" not in html


# ═════════════════════════════════════════════════════════════════════════════
# Extra - question 4 line names, one style: each policy's own declarations title
# ═════════════════════════════════════════════════════════════════════════════
_Q4_LINES = [   # the live coverage summary, in its live order
    {"line": "Liability", "carrier": "EMC Property & Casualty Company", "policy_number": "BBC7263 - 26"},
    {"line": "Inland Marine", "carrier": "EMPLOYERS MUTUAL CASUALTY COMPANY", "policy_number": "6C7-40-02---26"},
    {"line": "Automobile", "carrier": "EMPLOYERS MUTUAL CASUALTY COMPANY", "policy_number": "6E7-40-02---26"},
    {"line": "Umbrella", "carrier": "EMPLOYERS MUTUAL CASUALTY COMPANY", "policy_number": "6J7-40-02---26"},
    {"line": "Commercial Inland Marine", "carrier": "EMPLOYERS MUTUAL CASUALTY COMPANY", "policy_number": "6C7-40-02---26"},
    {"line": "Commercial Auto", "carrier": "Employers Mutual Casualty Company", "policy_number": "6E7-40-02---26"},
    {"line": "Commercial Umbrella", "carrier": "EMPLOYERS MUTUAL CASUALTY COMPANY", "policy_number": "6J7-40-02---26"},
    {"line": "Commercial General Liability", "carrier": "EMC Property & Casualty Company", "policy_number": "BBC7263 - 26"},
]
_Q4_RECORDS = [
    {"line": "auto", "line_printed": "Commercial Auto", "policy_number": "6E7-40-02---26"},
    {"line": "general_liab", "line_printed": "Commercial General Liability", "policy_number": "BBC7263 - 26"},
    {"line": "inland_marine", "line_printed": "Commercial Inland Marine", "policy_number": "6C7-40-02---26"},
    {"line": "umbrella", "line_printed": "Commercial Umbrella", "policy_number": "6J7-40-02---26"},
]


def _q4(facts, attr):
    return [ps._resolve_other_policy_cell(f"OtherPolicy_{attr}_{r}", facts) for r in "ABCD"]


def test_q4_names_each_row_the_way_its_own_declarations_do():
    facts = {"_form_id": "ACORD_125", "coverage_lines": _Q4_LINES, "_line_records": _Q4_RECORDS}
    assert _q4(facts, "LineOfBusinessCode") == [
        "Commercial General Liability", "Commercial Inland Marine", "Commercial Auto", "Commercial Umbrella"]
    assert _q4(facts, "PolicyNumberIdentifier") == [
        "BBC7263 - 26", "6C7-40-02---26", "6E7-40-02---26", "6J7-40-02---26"]


def test_q4_without_a_record_keeps_the_summary_name():
    facts = {"_form_id": "ACORD_125", "coverage_lines": _Q4_LINES}
    lines = _q4(facts, "LineOfBusinessCode")
    assert all(lines) and len(set(lines)) == 4


def test_q4_a_list_the_documents_state_prints_as_stated():
    facts = {"_form_id": "ACORD_125", "_line_records": _Q4_RECORDS, "other_insurance_policies": [
        {"line": "Workers Compensation", "policy_number": "WC-GA-448120"}]}
    assert ps._resolve_other_policy_cell("OtherPolicy_LineOfBusinessCode_A", facts) == "Workers Compensation"


# ═════════════════════════════════════════════════════════════════════════════
# Extra - a one-line DESCRIPTION OF OPERATIONS box and a ";"-joined value
# ═════════════════════════════════════════════════════════════════════════════
@pytest.fixture(scope="module")
def premises_box():
    import pikepdf
    pdf = pikepdf.open(BACKEND / "templates" / "ACORD_125.pdf")

    def find(arr, name):
        for it in arr:
            if str(it.get("/T", "")) == name:
                return it
            kids = it.get("/Kids")
            if kids is not None:
                got = find(kids, name)
                if got is not None:
                    return got
        return None

    box = find(pdf.Root.AcroForm.Fields, "BuildingOccupancy_OperationsDescription_A")
    assert box is not None
    yield box
    pdf.close()


_BOX_NAME = "BuildingOccupancy_OperationsDescription_A"


def test_a_semicolon_list_prints_its_leading_items_at_a_readable_size(premises_box):
    orbin = ("Contractors - Executive Supervisors or Executive Superintendents; "
             "Contrctrs-sub work-in connection w/constrctn,recon,repr,erctn of buildings - NOC")
    assert ps._leading_sentences_that_fit(premises_box, _BOX_NAME, orbin) == (
        "Contractors - Executive Supervisors or Executive Superintendents")


@pytest.mark.parametrize("text,expected", [
    # a paragraph still keeps its leading whole sentence (24 Sep behaviour)
    ("Commercial general contractor. We build tenant improvements and small commercial "
     "buildings across the Denver metro area, with most work subcontracted to licensed "
     "trades under written agreements.", "Commercial general contractor."),
    # a value that fits prints whole, semicolon and all
    ("Roofing contractor; residential only", "Roofing contractor; residential only"),
])
def test_other_descriptions_print_as_before(premises_box, text, expected):
    assert ps._leading_sentences_that_fit(premises_box, _BOX_NAME, text) == expected


def test_a_semicolon_before_a_lowercase_word_is_not_a_break(premises_box):
    text = ("a very long lower case description that goes on and on; and continues with more "
            "words that will never fit the single line box at all because it is long")
    assert ps._leading_sentences_that_fit(premises_box, _BOX_NAME, text) == text


# ═════════════════════════════════════════════════════════════════════════════
# Extra - no New Venture card once the documents show a completed policy term
# ═════════════════════════════════════════════════════════════════════════════
def test_an_ended_term_means_prior_operations():
    facts = {"_line_records": [{"effective_date": "07/15/2025", "expiration_date": "07/15/2026"}],
             "prior_expiration_date": "07/15/26"}
    assert lh.completed_policy_term(facts)
    assert sq._new_venture_prompt(facts, {}) == []


def test_a_first_policy_still_in_force_keeps_the_card():
    facts = {"coverage_lines": [{"line": "GL", "effective_date": "03/01/2026",
                                 "expiration_date": "03/01/2099"}]}
    assert not lh.completed_policy_term(facts)
    assert sq._new_venture_prompt(facts, {}) == [sq._NEW_VENTURE_CONFIRM_REC]


@pytest.mark.parametrize("facts", [
    {},
    {"expiration_date": "01/01/2020"},                                   # a PROPOSED date is not a lived term
    {"_line_records": [{"expiration_date": "see schedule"}]},            # unreadable
])
def test_no_evidence_of_a_completed_term(facts):
    assert not lh.completed_policy_term(facts)


def test_a_prior_grid_row_that_ended_counts():
    assert lh.completed_policy_term({"prior_coverage_by_line": [{"expiration_date": "2024-05-01"}]})


def test_a_producer_confirmation_is_judged_exactly_as_before():
    """The card is not offered, but an explicit confirmation is not overruled by
    this rule - `prior_operations_evidence` is unchanged."""
    facts = {"_line_records": [{"expiration_date": "07/15/2026"}], "new_venture_indicator": "Yes"}
    assert lh.prior_operations_evidence(facts, {}) == []


# ═════════════════════════════════════════════════════════════════════════════
# Live check of Step 1 (session 67e5ccf1, 29 Sep) - two wrong values a FRESH
# extraction and gap fill produced; neither was caused by Step 1.
# ═════════════════════════════════════════════════════════════════════════════
_SUBARU = [{"year": "2012", "make": "SUBARU", "model": "OUTBACK", "class_code": "7383",
            "vehicle_type": "private_passenger"}]
_AUTO_CLASS_ENTRY = [{"label": "PRIV PASSENGER - COMM CLASS", "value": "7383",
                      "section": "ITEM THREE - SCHEDULE OF COVERED AUTOS YOU OWN",
                      "owner": "policy", "policy_number": "6E7-40-02---26",
                      "line_of_business": "Commercial Auto"}]


def test_a_stated_gl_code_the_documents_give_to_the_auto_policy_is_replaced():
    """Live: extraction stated the applicant's GL code as the Subaru's class."""
    facts = {"applicant_gl_class_code": "7383", "gl_class_code_schedule": _ORBIN_GL_SCHEDULE,
             "auto_vin_schedule": _SUBARU, "dec_page_entries": _AUTO_CLASS_ENTRY}
    assert ps._resolve_applicant_row_a_scalar(_GL_BOX, facts) == "91580, 91585"


def test_without_a_gl_schedule_the_borrowed_code_leaves_an_owned_blank():
    """Not sent to gap fill: it would read the same misleading auto line."""
    facts = {"applicant_gl_class_code": "7383", "auto_vin_schedule": _SUBARU}
    assert ps._resolve_applicant_row_a_scalar(_GL_BOX, facts) is None


@pytest.mark.parametrize("facts", [
    # the GL schedule rates it too - it is ours
    {"applicant_gl_class_code": "91580", "gl_class_code_schedule": _ORBIN_GL_SCHEDULE,
     "auto_vin_schedule": [{"class_code": "91580"}]},
    # nothing attributes it to any line - no opinion (FR125's stated 92478)
    {"applicant_gl_class_code": "92478", "auto_vin_schedule": _SUBARU},
])
def test_a_stated_gl_code_is_kept_unless_another_line_owns_it(facts):
    assert ps._resolve_applicant_row_a_scalar(_GL_BOX, facts) == facts["applicant_gl_class_code"]


def test_code_ownership_reads_schedules_and_verified_entries():
    assert ps._code_is_another_lines("7383", {"auto_vin_schedule": _SUBARU}, "general_liab")
    assert ps._code_is_another_lines("7383", {"dec_page_entries": _AUTO_CLASS_ENTRY}, "general_liab")
    assert not ps._code_is_another_lines("7383", {}, "general_liab")
    assert not ps._code_is_another_lines("7383", {"auto_vin_schedule": _SUBARU}, "auto")
    assert not ps._code_is_another_lines("73", {"auto_vin_schedule": [{"class_code": "73"}]},
                                         "general_liab")


_DEC_TEXT = ("Named Insured ORBIN CONTRACTING LLC\nPolicy: BBC7263 - 26\n"
             "VIN 4S4BRCGC9C3217772 PRIV PASSENGER - COMM CLASS: 7383\n")


def _id_guard(values, raw=_DEC_TEXT, gpt=None):
    mapped = dict(values)
    dropped = ps._drop_ungrounded_identifiers(mapped, SCHEMA, raw,
                                             set(values) if gpt is None else gpt)
    return mapped, dropped


def test_an_invented_fein_is_blanked():
    """Live: FEIN 27-0272601 appears nowhere in the 271 pages."""
    mapped, dropped = _id_guard({"NamedInsured_TaxIdentifier_A": "27-0272601"})
    assert dropped == ["NamedInsured_TaxIdentifier_A"]
    assert mapped["NamedInsured_TaxIdentifier_A"] is None


@pytest.mark.parametrize("field,value,raw", [
    # printed with other punctuation and spacing
    ("NamedInsured_TaxIdentifier_A", "27-0272601", "FEIN: 27 0272601"),
    ("OtherPolicy_PolicyNumberIdentifier_A", "BBC7263-26", _DEC_TEXT),
    ("NamedInsured_TaxIdentifier_A", "270272601", "Tax ID 27-0272601"),
])
def test_an_identifier_the_documents_print_is_kept(field, value, raw):
    mapped, dropped = _id_guard({field: value}, raw=raw)
    assert dropped == [] and mapped[field] == value


@pytest.mark.parametrize("field,value", [
    ("Producer_CustomerIdentifier_A", "CUST-99812"),       # the producer assigns it
    ("NamedInsured_TaxIdentifier_A", "123"),               # too short to test
    ("CommercialPolicy_OperationsDescription_A", "Commercial general contractor 9999"),  # not an identifier box
])
def test_boxes_the_guard_does_not_judge(field, value):
    mapped, dropped = _id_guard({field: value})
    assert dropped == [] and mapped[field] == value


def test_a_value_a_fact_supplied_is_never_judged():
    mapped, dropped = _id_guard({"NamedInsured_TaxIdentifier_A": "27-0272601"}, gpt=set())
    assert dropped == [] and mapped["NamedInsured_TaxIdentifier_A"] == "27-0272601"


def test_the_invented_fein_never_reaches_the_form_end_to_end():
    facts = {"applicant_name": "ORBIN CONTRACTING LLC"}
    mapped, conf = ps.map_facts_to_form(
        facts, SCHEMA, "ACORD_125", raw_text=_DEC_TEXT,
        pre_filled_gpt={"filled_values": {"NamedInsured_TaxIdentifier_A": "27-0272601"}})
    assert not mapped.get("NamedInsured_TaxIdentifier_A")


def test_a_fein_the_documents_print_still_fills_end_to_end():
    facts = {"applicant_name": "ORBIN CONTRACTING LLC"}
    mapped, conf = ps.map_facts_to_form(
        facts, SCHEMA, "ACORD_125", raw_text=_DEC_TEXT + "FEIN 84-2210987\n",
        pre_filled_gpt={"filled_values": {"NamedInsured_TaxIdentifier_A": "84-2210987"}})
    assert mapped.get("NamedInsured_TaxIdentifier_A") == "84-2210987"
