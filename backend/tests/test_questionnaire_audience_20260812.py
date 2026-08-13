"""Client questionnaire review, 2026-08-12 (client test PARTS 13-15).

PART 13: "We should not be asking the client for the NAICS or SIC class codes;
         those come from the producer or underwriter."

PART 15: On the 26 agency-side questions - "Auto-populate: Form edition
         identifier. Pull from agency profile or AMS: Producer NPN and customer
         ID. Agency verification only: GL hazard producer identifier. Never ask
         the client: all four. They ... should not reduce the client's
         submission-quality score."

Two of those were already satisfied and are pinned here so they stay that way;
two were real defects and are fixed.
"""
import json
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("OPENAI_API_KEY", "sk-offline")

import services.pdf_service as ps  # noqa: E402
from services.question_classifier import (  # noqa: E402
    classify_question, AUDIENCE_CLIENT, AUDIENCE_PRODUCER,
)

_SCHEMA_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "forms_schemas")


# ── PART 13: classification codes belong to the producer ────────────────────

@pytest.mark.parametrize("field", ["naics_code", "sic_code"])
def test_classification_codes_are_not_client_questions(field):
    tax = classify_question(field, ["ACORD_125"], is_curated_client=True)
    assert tax["audience"] == AUDIENCE_PRODUCER


@pytest.mark.parametrize("field", ["naics_code", "sic_code"])
def test_classification_codes_do_not_dock_the_client_score(field):
    """"They ... should not reduce the client's submission-quality score as
    though the client failed to provide underwriting information." """
    impact = classify_question(field, ["ACORD_125"], is_curated_client=True)["score_impact"]
    assert impact["sqs"] is False
    assert impact["form_completion"] is False
    assert impact["points"] == 0


@pytest.mark.parametrize("field", [
    "dba_name", "gl_class_codes", "wc_class_codes", "contact_name", "contact_email",
    "ContractorsUnderwriting_ResidentialWorkPercent_A",
])
def test_the_change_did_not_sweep_in_neighbours(field):
    """LOAD-BEARING. `sic_code` was added to the substring-matched producer
    patterns; these must all stay client-facing."""
    assert classify_question(
        field, ["ACORD_125"], is_curated_client=True)["audience"] == AUDIENCE_CLIENT


# ── PART 15: the agency panel must not touch the client's score ─────────────

@pytest.mark.parametrize("field", [
    "Form_EditionIdentifier_A",
    "Insurer_ProducerIdentifier_A",
    "Insurer_SubProducerIdentifier_A",
    "GeneralLiability_Hazard_HazardProducerIdentifier_A",
    "Producer_NationalProducerNumber_A",
])
def test_agency_items_are_producer_side_and_score_neutral(field):
    tax = classify_question(field, ["ACORD_125"])
    assert tax["audience"] == AUDIENCE_PRODUCER
    assert tax["escalatable_to_client"] is False
    impact = tax["score_impact"]
    assert impact["sqs"] is False
    assert impact["form_completion"] is False
    assert impact["submission_readiness"] is False
    assert impact["points"] == 0


# ── PART 15: the form's own edition auto-populates ──────────────────────────

def test_the_edition_is_read_from_the_form_itself():
    assert ps._form_edition_identifier("ACORD_125") == "ACORD 125 (2025/03)"


def test_the_edition_is_per_form_not_a_constant():
    """THE reason this reads the template instead of hardcoding one string:
    the editions genuinely differ, and a wrong edition on a legal document is a
    misstatement."""
    editions = {
        f: ps._form_edition_identifier(f)
        for f in ("ACORD_125", "ACORD_127", "ACORD_140", "ACORD_186")
    }
    assert all(editions.values()), editions
    assert len(set(editions.values())) > 1, editions
    assert editions["ACORD_127"] != editions["ACORD_125"]


def test_the_edition_box_is_never_asked_of_anyone():
    with open(os.path.join(_SCHEMA_DIR, "ACORD_125_schema.json"), encoding="utf-8") as fh:
        schema = json.load(fh)
    mapped, unmatched, det = ps.compute_form_gaps(
        "ACORD_125", schema, {"applicant_name": "Orbin Contracting LLC"})
    assert mapped.get("Form_EditionIdentifier_A") == "ACORD 125 (2025/03)"
    assert "Form_EditionIdentifier_A" not in unmatched, "still being sent to the model"
    assert "Form_EditionIdentifier_A" in det


def test_an_unreadable_template_never_breaks_generation():
    assert ps._form_edition_identifier("ACORD_DOES_NOT_EXIST") is None
    assert ps._form_edition_identifier("") is None


def test_both_fill_paths_agree_on_the_edition():
    """compute_form_gaps and map_facts_to_form each stamp this; if they drift,
    the combined path and the per-form path disagree on a printed value."""
    import inspect
    for fn in (ps.compute_form_gaps, ps.map_facts_to_form):
        assert "_FORM_EDITION_FIELD_RE" in inspect.getsource(fn), fn.__name__
