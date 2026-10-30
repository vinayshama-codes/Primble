"""ACORD intake (27 Oct 2026, ACORD_INTAKE.md): filled ACORD forms are read by
box name, flattened ones by template overlay, and merged by the owner table.
Every PDF here is built from our own templates by the real stamper's fill."""
import asyncio
import io
import json
import os

import pytest

from services.acord_intake import intake, merge_rules, overlay, primble_record, read, recognize, reverse_map
from services.pdf_service import extract_form_schema, fill_pdf

BACKEND = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TPL = os.path.join(BACKEND, "templates")
FORMS = sorted(fn[:-4] for fn in os.listdir(TPL) if fn.endswith(".pdf"))


def _filled(tmp_path, form_id, values, name=None):
    pdf = fill_pdf(os.path.join(TPL, f"{form_id}.pdf"), values)
    p = tmp_path / (name or f"{form_id}_FILLED.pdf")
    p.write_bytes(pdf)
    return str(p)


def _flatten(src, dst):
    fitz = pytest.importorskip("fitz")
    d = fitz.open(src)
    d.bake()
    d.save(dst)
    d.close()
    return dst


VALUES_125 = {
    "NamedInsured_FullName_A": "Pinecrest Landscaping LLC",
    "NamedInsured_TaxIdentifier_A": "84-3317790",
    "NamedInsured_MailingAddress_LineOne_A": "2215 Juniper Ave",
    "NamedInsured_MailingAddress_CityName_A": "Boulder",
    "NamedInsured_MailingAddress_StateOrProvinceCode_A": "CO",
    "NamedInsured_MailingAddress_PostalCode_A": "80304",
    "NamedInsured_LegalEntity_LimitedLiabilityCorporationIndicator_A": "Yes",
    "Policy_LineOfBusiness_CommercialGeneralLiability_A": "Yes",
    "Policy_LineOfBusiness_BusinessAutoIndicator_A": "Yes",
    "Policy_LineOfBusiness_OtherIndicator_A": "Yes",
    "Policy_LineOfBusiness_OtherLineOfBusinessDescription_A": "Employment Practices Liability",
    "Policy_EffectiveDate_A": "12/01/2026",
    "Policy_ExpirationDate_A": "12/01/2027",
    "Insurer_FullName_A": "Westbridge Mutual Insurance Company",
    "PriorCoverage_GeneralLiability_InsurerFullName_A": "Old Oak Casualty",
    "PriorCoverage_GeneralLiability_EffectiveDate_A": "12/01/2025",
    "PriorCoverage_GeneralLiability_ExpirationDate_A": "12/01/2026",
    "PriorCoverage_GeneralLiability_TotalPremiumAmount_A": "4,200",
    "PriorCoverage_PolicyYear_A": "2025",
    "Policy_Status_QuoteIndicator_A": "Yes",
}


# ── Recognition ─────────────────────────────────────────────────────────────
@pytest.mark.parametrize("form_id", FORMS)
def test_every_blank_template_is_recognised_as_its_own_form(form_id):
    pages = recognize.recognize(os.path.join(TPL, f"{form_id}.pdf"))
    assert pages and all(p.kind == "fillable" and p.form_id == form_id for p in pages)


def test_a_document_that_is_not_an_acord_form_is_not_recognised(tmp_path):
    from reportlab.pdfgen import canvas
    p = tmp_path / "dec.pdf"
    c = canvas.Canvas(str(p))
    c.drawString(50, 750, "COMMERCIAL GENERAL LIABILITY DECLARATIONS - Policy Number CGL-4471")
    c.drawString(50, 730, "This mentions ACORD 25 in passing but prints no ACORD footer.")
    c.save()
    assert read.read_acord(str(p)) is None


def test_the_footer_tells_the_ca_and_co_variants_apart():
    assert recognize.form_id_for_footer("137", "CO") == "ACORD_137_CO"
    assert recognize.form_id_for_footer("137", "CA") == "ACORD_137_CA"
    assert recognize.form_id_for_footer("999") is None


# ── The fillable read ───────────────────────────────────────────────────────
def test_a_filled_125_reads_back_exactly(tmp_path):
    r = read.read_acord(_filled(tmp_path, "ACORD_125", VALUES_125))
    f = {k: (v.get("value") if isinstance(v, dict) else v) for k, v in r.facts.items()}
    assert f["applicant_name"] == "Pinecrest Landscaping LLC"
    assert f["fein"] == "84-3317790"
    assert f["mailing_address"] == "2215 Juniper Ave, Boulder, CO 80304"
    assert f["entity_type"] == "Limited Liability Company"
    assert set(f["lines_of_business"]) >= {"General Liability", "Business Auto", "Employment Practices Liability"}
    assert f["effective_date"] == "12/01/2026"
    # Page one names the carrier RECEIVING the submission, never the current one.
    assert f["submission_carrier_name"] == "Westbridge Mutual Insurance Company"
    assert "carrier_name" not in f
    prior = f["prior_coverage_by_line"]
    assert prior and prior[0]["carrier"] == "Old Oak Casualty" and prior[0]["year"] == "2025"
    assert all(v.get("source") == "acord_form" for v in r.facts.values() if isinstance(v, dict))


def test_unticked_boxes_never_read_as_ticked(tmp_path):
    vals = dict(VALUES_125)
    vals["NamedInsured_LegalEntity_CorporationIndicator_A"] = "No"
    r = read.read_acord(_filled(tmp_path, "ACORD_125", vals))
    assert r.facts["entity_type"]["value"] == "Limited Liability Company"


def test_two_entity_ticks_give_no_entity_type(tmp_path):
    vals = dict(VALUES_125)
    vals["NamedInsured_LegalEntity_CorporationIndicator_A"] = "Yes"
    r = read.read_acord(_filled(tmp_path, "ACORD_125", vals))
    assert "entity_type" not in r.facts          # blank over wrong


def test_our_own_pointer_text_is_never_a_statement(tmp_path):
    vals = dict(VALUES_125, CommercialPolicy_RemarkText_A="See the attached ACORD 101 Additional Remarks Schedule.")
    r = read.read_acord(_filled(tmp_path, "ACORD_125", vals))
    assert "additional_remarks_text" not in r.facts


def test_per_line_premium_boxes_are_carried_never_mapped(tmp_path):
    vals = dict(VALUES_125, GeneralLiabilityLineOfBusiness_TotalPremiumAmount_A="9,999")
    r = read.read_acord(_filled(tmp_path, "ACORD_125", vals))
    assert not any(isinstance(x, dict) and x.get("premium") == "9,999"
                   for x in (r.facts.get("coverage_lines") or []))


# ── The flattened read ──────────────────────────────────────────────────────
def test_a_flattened_125_reads_the_same_boxes(tmp_path):
    src = _filled(tmp_path, "ACORD_125", VALUES_125)
    flat = _flatten(src, str(tmp_path / "ACORD_125_FLAT.pdf"))
    a = read.read_acord(src)
    b = read.read_acord(flat)
    assert b is not None and b.forms and b.forms[0]["kind"] == "flattened"
    fa = {k: (v.get("value") if isinstance(v, dict) else v) for k, v in a.facts.items()}
    fb = {k: (v.get("value") if isinstance(v, dict) else v) for k, v in b.facts.items()}
    for k in ("applicant_name", "fein", "mailing_address", "entity_type", "effective_date",
              "submission_carrier_name"):
        assert fb.get(k) == fa.get(k), k
    assert set(fb["lines_of_business"]) == set(fa["lines_of_business"])


# ── The merge ───────────────────────────────────────────────────────────────
def _doc(facts, acord=False, prior=False, doc_type="dec_page", name="d.pdf"):
    d = {"filename": name, "doc_type": doc_type, "facts": facts}
    if acord:
        d["acord"] = {"forms": [{"form_id": "ACORD_125"}], "prior_application": prior}
    return d


def test_the_acord_owns_the_applicant_and_the_dec_owns_the_current_policy():
    merged = {"applicant_name": {"value": "PINECREST LANDSCAPING", "source": "ai"},
              "carrier_name": {"value": "Westbridge", "source": "acord_form"}}
    docs = [_doc({"applicant_name": {"value": "Pinecrest Landscaping LLC", "source": "acord_form"},
                  "carrier_name": {"value": "Westbridge", "source": "acord_form"}}, acord=True, name="a.pdf"),
            _doc({"applicant_name": {"value": "PINECREST LANDSCAPING", "source": "ai"},
                  "carrier_name": {"value": "Old Oak Casualty", "source": "ai"}})]
    merge_rules.apply_owner_rules(merged, docs)
    assert merged["applicant_name"]["value"] == "Pinecrest Landscaping LLC"
    assert merged["carrier_name"]["value"] == "Old Oak Casualty"


def test_a_persons_answer_is_never_moved():
    merged = {"applicant_name": {"value": "Typed Name LLC", "source": "producer"}}
    docs = [_doc({"applicant_name": {"value": "Other LLC", "source": "acord_form"}}, acord=True)]
    merge_rules.apply_owner_rules(merged, docs)
    assert merged["applicant_name"]["value"] == "Typed Name LLC"


def test_a_prior_year_acord_gives_identity_never_this_years_term():
    merged = {"effective_date": {"value": "01/01/2020", "source": "acord_form"}}
    docs = [_doc({"applicant_name": {"value": "Old App LLC", "source": "acord_form"},
                  "effective_date": {"value": "01/01/2020", "source": "acord_form"}},
                 acord=True, prior=True)]
    merge_rules.apply_owner_rules(merged, docs)
    assert merged["applicant_name"]["value"] == "Old App LLC"
    assert "effective_date" not in merged


def test_is_prior_application_reads_the_forms_own_term():
    import datetime
    today = datetime.date(2026, 10, 27)
    assert merge_rules.is_prior_application({"facts": {"effective_date": "01/01/2025",
                                                       "expiration_date": "01/01/2026"}}, today)
    assert not merge_rules.is_prior_application({"facts": {"effective_date": "12/01/2026"}}, today)
    assert not merge_rules.is_prior_application({"facts": {}}, today)


def test_two_identical_vans_on_one_form_stay_two_vans():
    van = {"year": "2023", "make": "CHEVROLET", "model": "EXPRESS G3500", "cost_new": "41,200"}
    assert len(merge_rules.fold_rows("auto_vin_schedule", [[dict(van), dict(van)]])) == 2


def test_one_vehicle_on_two_forms_folds_by_vin_only():
    a = {"vin": "1GCWGAFP4K1234567", "year": "2019"}
    b = {"vin": "1GCWGAFP4K1234567", "cost_new": "31,000"}
    c = {"year": "2019", "make": "CHEVROLET"}                 # no VIN - never joined
    out = merge_rules.fold_rows("auto_vin_schedule", [[a], [b, c]])
    assert len(out) == 2 and out[0]["cost_new"] == "31,000"


def test_a_building_printed_on_125_and_140_is_one_building():
    a = {"location_number": "1", "building_number": "001", "annual_revenue": "3,200,000"}
    b = {"location_number": "1", "building_number": "1", "construction_type": "FRAME"}
    c = {"location_number": "1", "building_number": "002", "construction_type": "JOISTED MASONRY"}
    out = merge_rules.fold_rows("property_locations", [[a], [b, c]])
    assert len(out) == 2 and out[0]["construction_type"] == "FRAME"


def test_the_umbrella_and_the_excess_layer_never_fold():
    u = {"line": "Commercial Umbrella", "effective_date": "01/01/2027", "limit": "5,000,000"}
    x = {"line": "Excess Liability", "effective_date": "01/01/2027", "limit": "4,000,000"}
    assert len(merge_rules.fold_rows("coverage_lines", [[u], [x]])) == 2


def test_a_summary_echo_row_spreads_and_goes():
    rows = [{"state": "CO"}, {"code": "5190", "payroll": "$2,000,000"}, {"code": "8810", "payroll": "$200,000"}]
    out = read._drop_summary_echoes(rows)
    assert len(out) == 2 and all(r["state"] == "CO" for r in out)
    rival = [{"state": "TX"}, {"code": "5190", "state": "CO"}, {"code": "8810", "state": "CO"}]
    assert len(read._drop_summary_echoes(rival)) == 3          # a contradicting value may be a real row


# ── Structural rules ────────────────────────────────────────────────────────
@pytest.mark.parametrize("word,n", [("One", 1), ("Seven", 7), ("TwentyOne", 21), ("SeventyOne", 71),
                                    ("FortySix", 46), ("OtherSymbol", None)])
def test_symbol_number_words(word, n):
    assert reverse_map._number_words(word) == n


def test_only_the_liability_row_of_the_symbol_grid_is_read():
    assert reverse_map.structural_targets("Vehicle_BusinessAutoSymbol_OneIndicator_A")[0]["symbol"] == 1
    assert not reverse_map.structural_targets("Vehicle_BusinessAutoSymbol_SevenIndicator_F")


def test_valuation_codes_decode_through_the_stampers_own_table():
    assert [reverse_map.decode("valuation", c) for c in "RAVX"] == ["rcv", "acv", "agreed_amount", None]


def test_the_stored_reverse_map_matches_every_schema():
    """Stale after a schema change -> re-run scripts/build_acord_reverse_map.py."""
    data = json.load(open(reverse_map.MAP_PATH))
    assert data["version"] == reverse_map.MAP_VERSION
    for fid in FORMS:
        schema = extract_form_schema(os.path.join(TPL, f"{fid}.pdf"), fid)
        assert data["forms"][fid]["schema_sha"] == reverse_map.schema_hash(schema), fid


# ── The seam ────────────────────────────────────────────────────────────────
def test_an_all_acord_document_makes_no_extraction_call(tmp_path, monkeypatch):
    import services.extraction_pipeline as ep

    async def boom(*a, **k):
        raise AssertionError("no model call for a document read by box name")
    monkeypatch.setattr(ep, "extract_facts_long", boom)
    p = _filled(tmp_path, "ACORD_125", VALUES_125)
    d = asyncio.run(ep.extract_document(p, "ACORD_125_FILLED.pdf", None))
    assert d["doc_type"] == "application" and d["classification"]["source"] == "acord_form"
    assert d["facts"]["applicant_name"]["value"] == "Pinecrest Landscaping LLC"
    assert d["flags"].get("has_general_liability") and d["acord"]["forms"]


def test_section_forms_set_their_own_line_flag():
    assert intake._flags_from({}, ["ACORD_126"]) == {"has_general_liability": True}
    assert intake._flags_from({}, ["ACORD_130"]) == {"has_workers_comp": True}


# ── The carry ───────────────────────────────────────────────────────────────
def test_carried_boxes_fill_blanks_and_ai_boxes_never_fact_boxes():
    from services.acord_intake.carry import apply_carried
    docs = [{"acord": {"carried": {"ACORD_126": {"Q1": "Y", "Q2": "Yes", "Q3": "N"}}}}]
    mapped = {"Q1": None, "Q2": "No", "Q3": "Y"}
    conf = {"Q2": {"label": "ai"}, "Q3": {"label": "filled"}}
    moved = apply_carried(mapped, conf, docs, "ACORD_126")
    assert mapped == {"Q1": "Y", "Q2": "Yes", "Q3": "Y"} and sorted(moved) == ["Q1", "Q2"]


def test_two_uploaded_copies_that_disagree_carry_nothing():
    from services.acord_intake.carry import carried_for
    docs = [{"acord": {"carried": {"ACORD_126": {"Q1": "Y"}}}}, {"acord": {"carried": {"ACORD_126": {"Q1": "N"}}}}]
    assert carried_for(docs, "ACORD_126") == {}


# ── The Primble record ──────────────────────────────────────────────────────
def test_the_primble_record_restores_answers_and_keeps_ai_boxes_ai(tmp_path, monkeypatch):
    from cryptography.fernet import Fernet
    monkeypatch.setenv("FIELD_ENCRYPTION_KEY", Fernet.generate_key().decode())
    try:
        import utils.crypto as uc
        for attr in ("_fernet", "_FERNET", "_cipher"):
            if hasattr(uc, attr):
                monkeypatch.setattr(uc, attr, None, raising=False)
    except Exception:
        pass
    src = _filled(tmp_path, "ACORD_125", VALUES_125)
    # The package the record comes from names the insured the form names - a
    # record laid into ANOTHER insured's form restores nothing (review 27 Oct,
    # tests/test_acord_intake_review.py); this fixture had used "x".
    session = {"facts": {"occupancy_type": {"value": "Zorblax Warehouse", "source": "producer"},
                         "applicant_name": {"value": "PINECREST LANDSCAPING LLC", "source": "ai"}},
               "generated_forms": {"ACORD_125": {"confidence": {"NamedInsured_TaxIdentifier_A": {"label": "ai"}}}}}
    out = primble_record.attach(open(src, "rb").read(), session, "ACORD_125")
    p = tmp_path / "with_record.pdf"
    p.write_bytes(out)
    raw = open(p, "rb").read()
    assert b"Zorblax" not in raw                                 # encrypted, not readable
    r = read.read_acord(str(p))
    # The answer no box prints comes back as the PACKAGE's person answer, never
    # as this document's printing (round trip, 27 Oct 2026).
    assert r.restored["answers"]["occupancy_type"]["value"] == "Zorblax Warehouse"
    assert "occupancy_type" not in r.facts
    # An AI box comes back onto ITS OWN box, never as a fact (27 Oct 2026, the
    # Orbin round trip: an AI deductible read as a fact printed in two more boxes).
    assert "fein" not in r.facts
    assert r.carried["ACORD_125"]["NamedInsured_TaxIdentifier_A"]
    assert r.primble_record
    merged = {}
    merge_rules.apply_owner_rules(merged, [{"filename": "with_record.pdf", "doc_type": "application",
                                            "facts": r.facts, "acord": {"forms": r.forms, "restored": r.restored}}])
    assert merged["occupancy_type"]["value"] == "Zorblax Warehouse"
    assert merged["occupancy_type"]["source"] == "producer"


def test_the_primble_record_restores_a_table_a_person_saved(tmp_path, monkeypatch):
    from cryptography.fernet import Fernet
    from services.schedule_capture import mark_human_rows
    monkeypatch.setenv("FIELD_ENCRYPTION_KEY", Fernet.generate_key().decode())
    facts = {"gl_class_code_schedule": [{"class_code": "92478", "classification": "Electrical work"}],
             "applicant_name": {"value": "Pinecrest Landscaping LLC", "source": "ai"}}
    mark_human_rows(facts, "gl_class_code_schedule", "producer")
    src = _filled(tmp_path, "ACORD_125", VALUES_125)
    out = primble_record.attach(open(src, "rb").read(), {"facts": facts, "generated_forms": {}}, "ACORD_125")
    p = tmp_path / "with_table.pdf"
    p.write_bytes(out)
    r = read.read_acord(str(p))
    assert r.restored["tables"]["gl_class_code_schedule"]["rows"] == [
        {"class_code": "92478", "classification": "Electrical work"}]
    merged = {}
    merge_rules.apply_restored_answers(merged, [{"filename": "t.pdf", "facts": r.facts,
                                                 "acord": {"forms": r.forms, "restored": r.restored}}])
    assert merged["gl_class_code_schedule"] == [{"class_code": "92478", "classification": "Electrical work"}]
    assert "gl_class_code_schedule" in merged["_human_schedules"]


# ── Owner calls after the review (27 Oct) ───────────────────────────────────
def test_no_primble_record_rides_on_a_certificate(tmp_path):
    src = _filled(tmp_path, "ACORD_25", {"NamedInsured_FullName_A": "Pinecrest Landscaping LLC"})
    raw = open(src, "rb").read()
    out = primble_record.attach(raw, {"facts": {"occupancy_type": {"value": "Zorblax", "source": "producer"}}},
                                "ACORD_25")
    assert out == raw


def test_another_insureds_acord_never_takes_over_the_applicant():
    merged = {"applicant_name": {"value": "CHOICE ELECTRIC LLC", "source": "ai"},
              "fein": {"value": "84-1234567", "source": "ai"}}
    docs = [_doc({"applicant_name": {"value": "Harborline Plumbing LLC", "source": "acord_form"},
                  "fein": {"value": "91-7654321", "source": "acord_form"}}, acord=True, doc_type="application", name="h.pdf"),
            _doc({"applicant_name": {"value": "CHOICE ELECTRIC LLC", "source": "ai"},
                  "fein": {"value": "84-1234567", "source": "ai"}})]
    merge_rules.apply_owner_rules(merged, docs)
    assert merged["applicant_name"]["value"] == "CHOICE ELECTRIC LLC"
    assert merged["fein"]["value"] == "84-1234567"


def test_the_same_insured_spelled_differently_still_takes_over():
    merged = {"applicant_name": {"value": "CHOICE ELECTRIC LLC", "source": "ai"}}
    docs = [_doc({"applicant_name": {"value": "Choice Electric, LLC", "source": "acord_form"}},
                 acord=True, doc_type="application", name="a.pdf"),
            _doc({"applicant_name": {"value": "CHOICE ELECTRIC LLC", "source": "ai"}})]
    merge_rules.apply_owner_rules(merged, docs)
    assert merged["applicant_name"]["value"] == "Choice Electric, LLC"


def test_a_carry_never_fills_a_box_a_resolver_owns_as_blank_by_a_package_rule(monkeypatch):
    # Re-review 27 Oct: only a blank the PACKAGE decides (ACORD 186's "do not
    # answer if attached to ACORD 126") beats the uploaded value; a box an owner
    # leaves blank for want of a fact ("Q_nofact") still takes it - blocking those
    # lost 14 of 135 carried boxes on the Choice Electric round trip.
    from services import pdf_service as ps
    from services.acord_intake.carry import apply_carried
    monkeypatch.setattr(ps, "_owned_blank_claim", lambda box, facts: box == "Q_nofact" or (
        box == "Q_starred" and "ACORD_126" in (facts.get("_package_form_ids") or [])))
    docs = [{"acord": {"carried": {"ACORD_186": {"Q_starred": "Y", "Q_other": "N", "Q_nofact": "Y"}}}}]
    mapped = {"Q_starred": None, "Q_other": None, "Q_nofact": None}
    apply_carried(mapped, {}, docs, "ACORD_186",
                  facts={"_form_id": "ACORD_186", "_package_form_ids": ["ACORD_126", "ACORD_186"]})
    assert mapped == {"Q_starred": None, "Q_other": "N", "Q_nofact": "Y"}


def test_a_certificate_description_is_the_certificates_own_fact():
    t = reverse_map.box_targets("ACORD_25", "CertificateOfLiabilityInsurance_ACORDForm_RemarkText_A")
    assert t == [{"t": "fact", "fact": "certificate_description_of_operations", "part": "whole"}]
