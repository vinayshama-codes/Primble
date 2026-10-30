"""Hostile round-trip review, 29 Oct 2026 - Primble's own downloaded forms re-uploaded.

Two defects found and fixed:
1. A box a producer edited BY HAND after download (in a PDF reader) was overridden by the
   stale answer another form's record restored: the edited form skipped its own restore,
   the other form restored the old value as a PERSON's answer, and a person's answer
   beats a document's word. The form's new word wins; the stale answer is not restored.
2. A form of ours whose record decrypts but whose insured box no longer matches the
   record's spelling (a typo made after download) stored its full OCR text as document
   evidence - our own printed narrative and AI answers read back as a document's statement.
   A form carrying OUR authenticated record never stores its text, whoever it names.
"""
import os

import pikepdf
import pytest

from services.acord_intake import merge_rules, primble_record, read, intake
from services.pdf_service import fill_pdf

BACKEND = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TPL = os.path.join(BACKEND, "templates")


@pytest.fixture(autouse=True)
def _fernet(monkeypatch):
    from cryptography.fernet import Fernet
    monkeypatch.setenv("FIELD_ENCRYPTION_KEY", Fernet.generate_key().decode())


NAME = "Pinecrest Landscaping LLC"
V125 = {
    "NamedInsured_FullName_A": NAME,
    "NamedInsured_NAICSCode_A": "238210",
    "Policy_EffectiveDate_A": "12/01/2026",
    "Policy_ExpirationDate_A": "12/01/2027",
}
ANSWERS = {"applicant_name": {"value": NAME, "source": "ai"},
           "naics_code": {"value": "238210", "source": "producer", "confidence": "producer"},
           "num_employees": {"value": "12", "source": "producer", "confidence": "producer"}}


def _our_form(tmp_path, form_id, values, name, facts):
    raw = fill_pdf(os.path.join(TPL, f"{form_id}.pdf"), values)
    session = {"facts": dict(facts), "flags": {},
               "generated_forms": {form_id: {"mapped": dict(values), "confidence": {b: "filled" for b in values}}}}
    p = tmp_path / name
    p.write_bytes(primble_record.attach(raw, session, form_id))
    return str(p)


def _retype(src, dst, box, value):
    with pikepdf.open(src) as pdf:
        for f in pdf.Root.AcroForm.Fields:
            if str(f.get("/T")) == box:
                f.V = pikepdf.String(value)
        pdf.save(dst)
    return str(dst)


def _doc(path, fname):
    r = read.read_acord(path)
    return {"filename": fname, "doc_type": "application",
            "facts": dict(r.facts),
            "acord": {"forms": r.forms, "restored": r.restored or {}, "own_form": r.own_form}}


def test_a_hand_edit_after_download_beats_the_stale_answer_on_another_forms_record(tmp_path):
    p125 = _our_form(tmp_path, "ACORD_125", V125, "125.pdf", ANSWERS)
    p126 = _our_form(tmp_path, "ACORD_126", {"NamedInsured_FullName_A": NAME}, "126.pdf", ANSWERS)
    edited = _retype(p125, tmp_path / "125_edited.pdf", "NamedInsured_NAICSCode_A", "238220")
    d125, d126 = _doc(edited, "125.pdf"), _doc(p126, "126.pdf")
    # the edited form reads its new word and restores no stale NAICS of its own
    assert d125["facts"]["naics_code"]["value"] == "238220"
    assert "naics_code" not in (primble_record.restored_of(d125).get("answers") or {})
    # ...but the 126's record still remembers the old answer
    assert primble_record.restored_of(d126)["answers"]["naics_code"]["value"] == "238210"
    merged = {"naics_code": dict(d125["facts"]["naics_code"])}
    merge_rules.apply_restored_answers(merged, [d125, d126])
    assert merged["naics_code"]["value"] == "238220", "the stale record answer overrode the hand edit"
    assert not merge_rules._by_person(merged["naics_code"])
    # an answer no box was edited for still comes back
    assert merged["num_employees"]["value"] == "12" and merge_rules._by_person(merged["num_employees"])


def test_the_edited_boxs_old_answer_is_not_an_echo_to_drop(tmp_path):
    """`drop_answer_echoes` must leave the edited reading on the stored document."""
    p125 = _our_form(tmp_path, "ACORD_125", V125, "125.pdf", ANSWERS)
    p126 = _our_form(tmp_path, "ACORD_126", {"NamedInsured_FullName_A": NAME}, "126.pdf", ANSWERS)
    edited = _retype(p125, tmp_path / "125_edited.pdf", "NamedInsured_NAICSCode_A", "238220")
    d125, d126 = _doc(edited, "125.pdf"), _doc(p126, "126.pdf")
    merge_rules.drop_answer_echoes([d125, d126])
    assert d125["facts"]["naics_code"]["value"] == "238220"


def test_our_form_with_a_retyped_insured_name_never_stores_its_text(tmp_path):
    p125 = _our_form(tmp_path, "ACORD_125", V125, "125.pdf", ANSWERS)
    typo = _retype(p125, tmp_path / "125_typo.pdf", "NamedInsured_FullName_A", "Pinecrest Landscapng LLC")
    text = "[Document page 1]\nPinecrest Landscapng LLC\nDESCRIPTION OF OPERATIONS\nOur own printed narrative."
    got = intake.read_for_document(typo, text)
    assert got is not None and got["classification"]["doc_type"] == "application"
    # the record cannot vouch for a form naming someone else: nothing restored...
    assert not primble_record.restored_of(got["record"]).get("answers")
    # ...and our output is never document evidence
    assert got["stored_text"] is not None and "narrative" not in got["stored_text"]


def test_an_outside_form_keeps_its_text(tmp_path):
    raw = fill_pdf(os.path.join(TPL, "ACORD_125.pdf"), V125)
    p = tmp_path / "outside.pdf"
    p.write_bytes(raw)
    text = "[Document page 1]\nPinecrest Landscaping LLC\nDESCRIPTION OF OPERATIONS\nLandscaping."
    got = intake.read_for_document(str(p), text)
    assert got is not None and got["stored_text"] is None


def test_our_own_form_is_prior_only_when_its_term_has_ended():
    """Owner, 29 Oct 2026: a form carrying our record is last year's application
    only once its term has ENDED - never by the 30-day rule outside forms keep."""
    import datetime
    from services.acord_intake.merge_rules import is_prior_application
    d = {"facts": {"effective_date": {"value": "01/01/2027"}, "expiration_date": {"value": "01/01/2028"}}}
    feb = datetime.date(2027, 2, 15)
    assert is_prior_application(d, today=feb) is True                       # an outside form: 30-day rule
    assert is_prior_application(d, today=feb, own_record=True) is False     # ours: still in force
    assert is_prior_application(d, today=datetime.date(2028, 1, 2), own_record=True) is True
    assert is_prior_application({"facts": {}}, today=feb, own_record=True) is False


def test_a_record_restores_only_for_the_account_that_wrote_it():
    """Owner, 29 Oct 2026: another agency uploading the same company's Primble form
    gets none of the first agency's answers - its AI boxes still read as AI."""
    from services.acord_intake import primble_record as PR
    rec = {"v": PR.VERSION, "applicant": "Acme Hearth LLC", "account": PR.account_key("user-A"),
           "answers": {"total_revenue": {"value": "$900,000", "source": "producer", "confidence": "producer"}},
           "ai_boxes": ["NamedInsured_TaxIdentifier_A"]}

    def facts():
        return {"applicant_name": {"value": "Acme Hearth LLC", "source": "acord_form"},
                "fein": {"value": "12-3456789", "source": "acord_form", "box": "NamedInsured_TaxIdentifier_A"}}
    tok = PR.uploading_account("user-A")
    try:
        got = PR.apply(rec, facts())
        assert got and "total_revenue" in got["answers"]           # the writer's own upload
    finally:
        PR._UPLOADER.reset(tok)
    tok = PR.uploading_account("user-B")
    try:
        f = facts()
        assert PR.apply(rec, f) is None                            # another account: nothing restored
        assert f["fein"]["source"] == "ai"                         # ...but the AI box is still AI
        assert PR.summary_payload(dict(rec, form=PR.SUMMARY_FORM)) is None
    finally:
        PR._UPLOADER.reset(tok)
    assert PR.apply(dict(rec, account=""), facts())                # a record from before 29 Oct
    assert PR.account_key("user-A") != PR.account_key("user-B") and "user-A" not in PR.account_key("user-A")
