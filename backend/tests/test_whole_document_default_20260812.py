"""Owner decision 2026-08-12: LLM call 2 reads the COMPLETE document.

Coverage DROPPED on a live run with filtering on - the entry-anchored mode
keeps only windows carrying an already-known value, so a dec window whose
values extraction never captured (exactly the fields only call 2 can fill)
lost its source text. Filtering is now OPT-IN (GAP_FILL_TEXT_SELECTION=1);
production default is the whole document, byte for byte.

Also pinned here: Guard 9 (an affirmative whose paired explanation ends up
empty is blanked - the owner saw "Y" with no explanation on two live decs),
and the location fold surviving OCR unit-spacing jitter ("D13" vs "D 13").
"""
import importlib
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("OPENAI_API_KEY", "sk-offline")

import services.extraction_service as es  # noqa: E402
import services.pdf_service as ps  # noqa: E402


def test_the_production_default_is_whole_document():
    """With GAP_FILL_TEXT_SELECTION absent from the environment, the module
    must come up DISABLED and return any document unchanged."""
    import services.text_selection as ts
    old = os.environ.pop("GAP_FILL_TEXT_SELECTION", None)
    try:
        importlib.reload(ts)
        assert not ts._ENABLED
        doc = "COMMERCIAL DECLARATIONS $10,663\n" + ("policy wording line\n" * 20000)
        out, stats = ts.select_gap_fill_text(doc, {"dec_page_entries": [
            {"label": "x", "value": "$10,663", "owner": "policy"}] * 30}, label="t")
        assert out == doc and not stats["applied"]
    finally:
        if old is not None:
            os.environ["GAP_FILL_TEXT_SELECTION"] = old
        importlib.reload(ts)


# ── Guard 9: no naked Yes ────────────────────────────────────────────────────

_SCHEMA = {
    "CommercialPolicy_Question_DRONECode_A": {
        "ft": "/Tx",
        "tu": 'Enter Y for a "Yes" response. Input N for "No" response. The '
              'response to the question, "Does the applicant own drones?"',
    },
    "CommercialPolicy_Question_DRONEExplanation_A": {
        "ft": "/Tx", "tu": "Enter text: the explanation for a Yes response.",
    },
}


def test_a_yes_whose_explanation_was_eaten_is_blanked_with_it():
    mapped = {"CommercialPolicy_Question_DRONECode_A": "Y",
              "CommercialPolicy_Question_DRONEExplanation_A": None}
    ps._enforce_post_fill_guards(mapped, _SCHEMA, {}, set())
    assert mapped["CommercialPolicy_Question_DRONECode_A"] is None


def test_a_yes_with_its_explanation_stands():
    mapped = {"CommercialPolicy_Question_DRONECode_A": "Y",
              "CommercialPolicy_Question_DRONEExplanation_A":
                  "The applicant operates two drones for roof inspections."}
    ps._enforce_post_fill_guards(mapped, _SCHEMA, {}, set())
    assert mapped["CommercialPolicy_Question_DRONECode_A"] == "Y"


def test_a_no_never_needs_an_explanation():
    mapped = {"CommercialPolicy_Question_DRONECode_A": "N",
              "CommercialPolicy_Question_DRONEExplanation_A": None}
    ps._enforce_post_fill_guards(mapped, _SCHEMA, {}, set())
    assert mapped["CommercialPolicy_Question_DRONECode_A"] == "N"


def test_an_unpaired_question_is_never_touched():
    schema = {"CommercialPolicy_Question_LONECode_A": {
        "ft": "/Tx",
        "tu": 'Enter Y for a "Yes" response. Input N for "No" response. The '
              'response to the question, "Is this a lone question?"'}}
    mapped = {"CommercialPolicy_Question_LONECode_A": "Y"}
    ps._enforce_post_fill_guards(mapped, schema, {}, set())
    assert mapped["CommercialPolicy_Question_LONECode_A"] == "Y"


# ── The location fold vs OCR unit spacing ────────────────────────────────────

def test_ocr_split_unit_designator_still_folds_to_one_premises():
    facts = {"property_locations": [
        {"address": "4800 Dahlia St # D13 Denver"},
        {"address": "4800 Dahlia St D 13 Denver CO. 80216-3121"},
        {"address": "Denver CO 80216-3121"},
    ]}
    es._consolidate_property_locations(facts)
    assert len(facts["property_locations"]) == 1


def test_two_real_suites_still_never_fold_compacted():
    facts = {"property_locations": [
        {"address": "4800 Dahlia St # D13, Denver, CO 80216"},
        {"address": "4800 Dahlia St # B5, Denver, CO 80216"},
    ]}
    es._consolidate_property_locations(facts)
    assert len(facts["property_locations"]) == 2
