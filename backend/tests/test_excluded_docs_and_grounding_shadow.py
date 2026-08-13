"""Two fixes: excluded documents reaching the LLM, and an unused grounding check.

1. EXCLUDED DOCUMENTS WERE STILL SENT TO THE MODEL.
   "Exclude" is an explicit user action - `reclassify_document(action="exclude")`
   sets `doc["excluded"] = True`, meaning "this document is not part of this
   submission". Extraction, fact merging, form matching, submission integrity
   and SQS all honour it (`active_docs = [d for d in docs if not
   d.get("excluded")]`, services/extraction_pipeline.py). The three places that
   built LLM/matching text did NOT, so a removed document was still shipped as
   "RAW DOCUMENT TEXT (AUTHORITATIVE SOURCE)" - and the gap-fill prompt tells
   the model that text OUTRANKS the extracted facts, which had correctly
   dropped it. A deleted document could overwrite a correct value.

   The all-excluded fallback is load-bearing, not defensive padding: an empty
   raw_text makes `_fill_unmatched_with_gpt` return immediately ("no raw_text
   provided - skipping GPT fill"), silently losing every gap-filled field on
   every form.

2. THE GROUNDING CHECK NOBODY USES.
   `_value_in_raw_text` has shipped for a long time and is wired into exactly
   two guards (classification codes, NAIC codes). Every other AI-authored value
   is stamped with nothing checking it came from the document. The shadow
   reporter is REPORT-ONLY on purpose - enforcement must be backed by a measured
   run on real submissions, not by the idea sounding good.
"""
import json
import logging
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
os.environ.setdefault("OPENAI_API_KEY", "sk-offline-test")

import services.pdf_service as ps                        # noqa: E402
from services.form_service import active_document_text   # noqa: E402

_SCHEMA_DIR = os.path.join(os.path.dirname(__file__), "..", "forms_schemas")


def _acord125():
    with open(os.path.join(_SCHEMA_DIR, "ACORD_125_schema.json"), encoding="utf-8") as fh:
        return json.load(fh)


# ── 1. Excluded documents ────────────────────────────────────────────────────

def test_excluded_document_text_never_reaches_the_model():
    session = {"docs": [
        {"text": "KEEP dec page", "excluded": False},
        {"text": "REMOVED wrong insured", "excluded": True},
    ]}
    out = active_document_text(session)
    assert "KEEP dec page" in out
    assert "REMOVED" not in out


def test_documents_without_the_flag_are_included():
    """Absence of the key means "not excluded" - the flag is only set by an
    explicit user action, so most sessions never carry it at all."""
    session = {"docs": [{"text": "alpha"}, {"text": "beta"}]}
    out = active_document_text(session)
    assert "alpha" in out and "beta" in out


def test_all_excluded_falls_back_rather_than_returning_empty():
    """LOAD-BEARING. Empty raw_text makes gap fill skip entirely, which loses
    every AI-filled field on every form - far worse than the original defect."""
    session = {"docs": [
        {"text": "only doc", "excluded": True},
        {"text": "other doc", "excluded": True},
    ]}
    out = active_document_text(session)
    assert "only doc" in out and "other doc" in out


def test_no_docs_is_empty_not_an_exception():
    assert active_document_text({}) == ""
    assert active_document_text({"docs": []}) == ""


def test_non_dict_entries_do_not_crash_the_join():
    session = {"docs": [{"text": "good"}, None, "junk"]}
    assert active_document_text(session) == "good"


def test_every_llm_text_assembly_site_honours_exclusion():
    """STANDING GUARD. A fourth site built the same way would silently
    reintroduce the defect. The helper is the only sanctioned way to build
    document text for a model or a matcher."""
    import re
    roots = [
        os.path.join(os.path.dirname(__file__), "..", "routes", "form_routes.py"),
        os.path.join(os.path.dirname(__file__), "..", "services", "form_service.py"),
    ]
    pattern = re.compile(r'join\([^)]*d\.get\("text"')
    offenders = []
    for path in roots:
        with open(path, encoding="utf-8") as fh:
            for n, line in enumerate(fh, 1):
                if pattern.search(line) and "active_document_text" not in line:
                    offenders.append(f"{os.path.basename(path)}:{n}: {line.strip()[:90]}")
    # form_service.active_document_text's own body is the one sanctioned join.
    offenders = [o for o in offenders if "for d in active" not in o]
    assert not offenders, "unfiltered document-text join(s): " + "; ".join(offenders)


# ── 2. Grounding shadow reporter ─────────────────────────────────────────────

_RAW = (
    "COMMERCIAL INSURANCE APPLICATION\n"
    "Named Insured: Orbin Contracting LLC\n"
    "Mailing Address: 4800 Dahlia St # D13, Denver, CO 80216-3121\n"
    "Producer: Commercial Risk Solutions, Inc.   Phone: 303-996-7800\n"
    "Carrier: Employers Mutual Casualty Company   NAIC: 26247\n"
    "Policy Number: 6E7-40-02---26\n"
    "Policy Period: 07/15/2025 to 07/15/2026\n"
)


def test_the_reporter_never_mutates_anything():
    """THE WHOLE CONTRACT. If this ever fails, a diagnostic has started
    deleting production data."""
    mapped = {
        "NamedInsured_TaxIdentifier_A": "0482854",
        "NamedInsured_Primary_WebsiteAddress_A": "Www.emcins.com",
        "NamedInsured_FullName_A": "Orbin Contracting LLC",
    }
    before = dict(mapped)
    ps._report_ungrounded_ai_values(mapped, _acord125(), _RAW, set(mapped), "ACORD_125")
    assert mapped == before


def test_it_flags_the_two_client_reported_values(caplog):
    """The FEIN box holding EMC's account number, and the carrier's website in
    the applicant's website box - both still open on the client's report."""
    mapped = {
        "NamedInsured_TaxIdentifier_A": "0482854",
        "NamedInsured_Primary_WebsiteAddress_A": "Www.emcins.com",
    }
    with caplog.at_level(logging.INFO, logger=ps.logger.name):
        ps._report_ungrounded_ai_values(mapped, _acord125(), _RAW, set(mapped), "ACORD_125")
    text = caplog.text
    assert "WOULD_BLANK" in text
    assert "NamedInsured_TaxIdentifier_A" in text
    assert "NamedInsured_Primary_WebsiteAddress_A" in text


def test_values_actually_in_the_document_are_not_flagged(caplog):
    mapped = {
        "NamedInsured_FullName_A": "Orbin Contracting LLC",
        "Insurer_NAICCode_A": "26247",
        "Policy_PolicyNumberIdentifier_A": "6E7-40-02---26",
    }
    with caplog.at_level(logging.INFO, logger=ps.logger.name):
        ps._report_ungrounded_ai_values(mapped, _acord125(), _RAW, set(mapped), "ACORD_125")
    assert "WOULD_BLANK" not in caplog.text


@pytest.mark.parametrize("field,value,expected", [
    # Reformatted by the pipeline - presence is meaningless, must be skipped.
    ("Policy_EffectiveDate_A",                            "07/15/2025", "skip"),
    # A tick is not a quotable string.
    ("Policy_Status_BoundIndicator_A",                    "Yes",        "skip"),
    # Too short to search for meaningfully.
    ("NamedInsured_MailingAddress_StateOrProvinceCode_A", "CO",         "skip"),
    # Copied identifiers: must appear character for character.
    ("Insurer_NAICCode_A",                                "26247",      "strict"),
    ("Policy_PolicyNumberIdentifier_A",                   "6E7-40-02---26", "strict"),
    # Free text: the forgiving word-subset path.
    ("NamedInsured_FullName_A",                           "Orbin Contracting LLC", "lenient"),
])
def test_strictness_is_derived_from_acords_own_declared_type(field, value, expected):
    """No new hand-maintained table: the mode comes from the "Enter <type>:"
    prefix ACORD writes into 3,888 of 5,852 tooltips."""
    schema = _acord125()
    if field not in schema:
        pytest.skip(f"{field} not on ACORD 125")
    assert ps._grounding_mode_for(field, schema[field], value) == expected


def test_a_date_stamped_in_a_different_format_is_never_reported(caplog):
    """The pipeline canonicalises "March 1, 2026" to "03/01/2026". Reporting
    that as fabricated would bury the real signal."""
    mapped = {"Policy_EffectiveDate_A": "03/01/2026"}
    with caplog.at_level(logging.INFO, logger=ps.logger.name):
        ps._report_ungrounded_ai_values(
            mapped, _acord125(), "Policy Period: March 1, 2026 to March 1, 2027",
            set(mapped), "ACORD_125")
    assert "WOULD_BLANK" not in caplog.text


def test_deterministic_values_are_not_reported(caplog):
    """Only this run's gap-fill output is in scope; Pass 1 / alias values are
    not the model's guesses."""
    mapped = {"NamedInsured_TaxIdentifier_A": "0482854"}
    with caplog.at_level(logging.INFO, logger=ps.logger.name):
        ps._report_ungrounded_ai_values(mapped, _acord125(), _RAW, set(), "ACORD_125")
    assert "WOULD_BLANK" not in caplog.text


def test_a_broken_schema_cannot_break_a_fill(caplog):
    """A diagnostic must never be able to take down form generation."""
    mapped = {"NamedInsured_FullName_A": "Orbin Contracting LLC"}
    with caplog.at_level(logging.WARNING, logger=ps.logger.name):
        ps._report_ungrounded_ai_values(mapped, None, _RAW, set(mapped), "ACORD_125")
    assert mapped == {"NamedInsured_FullName_A": "Orbin Contracting LLC"}
