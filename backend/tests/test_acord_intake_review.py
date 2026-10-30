"""Review of the ACORD intake (27 Oct 2026, ACORD_INTAKE.md "Review (27 Oct)").

Each test was written FAILING against the build it reviews, from a defect
reproduced on a real filled / flattened / forged PDF built from our own
templates. Blank over wrong is the bar: a reading the reader cannot be sure of
must come back as no reading, never as a value with `acord_exact` confidence."""
import copy
import json
import os

import pytest

from services.acord_intake import carry, intake, merge_rules, overlay, primble_record, read, recognize, reverse_map
from services.pdf_service import fill_pdf

BACKEND = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TPL = os.path.join(BACKEND, "templates")


def _filled(tmp_path, form_id, values, name=None):
    p = tmp_path / (name or f"{form_id}_FILLED.pdf")
    p.write_bytes(fill_pdf(os.path.join(TPL, f"{form_id}.pdf"), values))
    return str(p)


def _flatten(src, dst):
    fitz = pytest.importorskip("fitz")
    d = fitz.open(src)
    d.bake()
    d.save(dst)
    d.close()
    return dst


def _replace(src, dst, dx=0.0, dy=0.0, scale=1.0):
    """Every page's content re-placed at (scale, dx, dy) on a same-size page -
    what "Fit to page" / a print driver's margin does to a flattened form."""
    fitz = pytest.importorskip("fitz")
    s, d = fitz.open(src), fitz.open()
    for pg in s:
        r = pg.rect
        page = d.new_page(width=r.width, height=r.height)
        page.show_pdf_page(fitz.Rect(dx, dy, dx + r.width * scale, dy + r.height * scale), s, pg.number)
    d.save(dst)
    d.close()
    s.close()
    return dst


def _v(facts):
    return {k: (v.get("value") if isinstance(v, dict) and "value" in v else v) for k, v in (facts or {}).items()}


V125 = {
    "NamedInsured_FullName_A": "Pinecrest Landscaping LLC",
    "NamedInsured_TaxIdentifier_A": "84-3317790",
    "NamedInsured_MailingAddress_LineOne_A": "2215 Juniper Ave",
    "NamedInsured_MailingAddress_CityName_A": "Boulder",
    "NamedInsured_MailingAddress_StateOrProvinceCode_A": "CO",
    "NamedInsured_MailingAddress_PostalCode_A": "80304",
    "NamedInsured_LegalEntity_LimitedLiabilityCorporationIndicator_A": "Yes",
    "Policy_EffectiveDate_A": "12/01/2026",
    "Policy_ExpirationDate_A": "12/01/2027",
    "Insurer_FullName_A": "Westbridge Mutual Insurance Company",
}


# ── 1. A multi-page fillable form is ONE copy ───────────────────────────────
# Every ACORD page repeats the AGENCY CUSTOMER ID box; its first template page
# is page 1, so every page "did not move forward" and began a new copy: boxes on
# pages 2+ were carried under "ACORD_125#2" (never printed again) and a table row
# printed across two pages (the 130's class rows) split into two rows.
def _multi_page_125(tmp_path, name="m125.pdf"):
    vals = dict(V125, Producer_CustomerIdentifier_A="CUST-77",
                CommercialPolicy_OperationsDescription_A="Landscape design and maintenance",
                # page 3+: a Y/N question no fact sits behind - carried box-to-box
                CommercialPolicy_Question_AAICode_A="N")
    return _filled(tmp_path, "ACORD_125", vals, name)


def test_a_multi_page_fillable_form_reads_as_one_copy(tmp_path):
    r = read.read_acord(_multi_page_125(tmp_path))
    assert len(r.forms) == 1, [(c["form_id"], c["copy"], c["pages"]) for c in r.forms]
    assert r.forms[0]["pages"] == list(range(len(r.pages)))
    assert all("#" not in k for k in r.carried)
    assert r.carried["ACORD_125"].get("CommercialPolicy_Question_AAICode_A") == "N"


def test_two_copies_of_one_form_in_one_pdf_are_two_copies(tmp_path):
    pikepdf = pytest.importorskip("pikepdf")
    a = _multi_page_125(tmp_path, "a.pdf")
    b = _filled(tmp_path, "ACORD_125", dict(V125, NamedInsured_FullName_A="Second Copy LLC"), "b.pdf")
    out = tmp_path / "two.pdf"
    with pikepdf.open(a) as pa, pikepdf.open(b) as pb:
        pa.pages.extend(pb.pages)
        pa.save(out)
    r = read.read_acord(str(out))
    assert [c["copy"] for c in r.forms if c["form_id"] == "ACORD_125"] == [1, 2]


def test_pages_out_of_order_are_still_one_copy(tmp_path):
    pikepdf = pytest.importorskip("pikepdf")
    src = _multi_page_125(tmp_path)
    out = tmp_path / "shuffled.pdf"
    with pikepdf.open(src) as pdf:
        second = pdf.pages[1]
        pdf.pages.insert(0, second)              # page 2 first ...
        del pdf.pages[2]                         # ... and not twice
        pdf.save(out)
    r = read.read_acord(str(out))
    assert len([c for c in r.forms if c["form_id"] == "ACORD_125"]) == 1


def test_a_130_class_row_printed_across_two_pages_stays_one_row(tmp_path):
    from services.pdf_service import _SCHEDULE_REGISTRY
    tp = read.template_pages("ACORD_130")
    # A wc_class_codes row A whose columns sit on two template pages.
    cols = {}
    for base, d in _SCHEDULE_REGISTRY.items():
        if d.list_key == "wc_class_codes" and d.sub_key and not d.sub_key.startswith("_"):
            box = f"{base}_A"
            pages = tp.get(box)
            if pages is not None:
                cols.setdefault(min(pages) if isinstance(pages, (set, frozenset)) else pages, (box, d.sub_key))
    if len(cols) < 2:
        pytest.skip("no wc_class_codes row spans two template pages")
    vals = {"NamedInsured_FullName_A": "Acme LLC"}
    for i, (_pg, (box, sub)) in enumerate(sorted(cols.items())):
        vals[box] = "5190" if sub == "code" else ("CO" if "state" in sub else f"V{i}")
    r = read.read_acord(_filled(tmp_path, "ACORD_130", vals))
    assert len(r.facts.get("wc_class_codes") or []) == 1, r.facts.get("wc_class_codes")


# ── 2. A ticked "No" checkbox is ticked ─────────────────────────────────────
def test_a_ticked_no_box_of_a_yes_no_pair_is_carried_ticked(tmp_path):
    no_box = "WorkersCompensationLineOfBusiness_Question_ADCNoIndicator_A"
    r = read.read_acord(_filled(tmp_path, "ACORD_133", {"NamedInsured_FullName_A": "Acme LLC", no_box: "Yes"}))
    assert r.carried.get("ACORD_133", {}).get(no_box) == "Yes"


# ── 3. ACORD 25's insurer roster is joined by INSR LTR, never by position ────
def test_a_certificate_line_takes_the_insurer_its_letter_names(tmp_path):
    vals = {"NamedInsured_FullName_A": "Acme LLC",
            "Insurer_FullName_A": "Granite State Casualty", "Insurer_NAICCode_A": "11111",
            "Insurer_FullName_B": "Blue Ridge WC Mutual", "Insurer_NAICCode_B": "22222",
            "GeneralLiability_InsurerLetterCode_A": "A", "Vehicle_InsurerLetterCode_A": "A",
            "WorkersCompensationEmployersLiability_InsurerLetterCode_A": "B",
            "Policy_GeneralLiability_PolicyNumberIdentifier_A": "GL-100",
            "Policy_AutomobileLiability_PolicyNumberIdentifier_A": "AU-200",
            "Policy_WorkersCompensationAndEmployersLiability_PolicyNumberIdentifier_A": "WC-300"}
    r = read.read_acord(_filled(tmp_path, "ACORD_25", vals))
    by_line = {row["line"]: row for row in r.facts["coverage_lines"]}
    assert by_line["Business Auto"].get("carrier") == "Granite State Casualty"
    assert by_line["Business Auto"].get("naic") == "11111"
    assert by_line["Workers Compensation and Employers Liability"].get("carrier") == "Blue Ridge WC Mutual"
    assert by_line["Commercial General Liability"].get("carrier") == "Granite State Casualty"


def test_a_certificate_row_with_no_letter_takes_no_carrier_from_a_two_insurer_roster(tmp_path):
    vals = {"Insurer_FullName_A": "Granite State Casualty", "Insurer_FullName_B": "Blue Ridge WC Mutual",
            "Policy_AutomobileLiability_PolicyNumberIdentifier_A": "AU-200"}
    r = read.read_acord(_filled(tmp_path, "ACORD_25", vals))
    auto = [x for x in r.facts.get("coverage_lines") or [] if x.get("line") == "Business Auto"]
    assert auto and not auto[0].get("carrier")


# ── 4. An application's header: the proposed term + its own line's identity ─
# ACORD 126's header printed the proposed 01/01/2027 beside a dec's current GL
# policy: the merged GL record read "effective 01/01/2027, expiration 01/01/2026".
# ACORD 160's header was read as a CYBER policy and 138's as an INLAND MARINE one.
_HEADER = {"NamedInsured_FullName_A": "Acme LLC", "Insurer_FullName_A": "Header Market Insurance Co",
           "Insurer_NAICCode_A": "33333", "Policy_PolicyNumberIdentifier_A": "HDR-1",
           "Policy_EffectiveDate_A": "01/01/2027"}


@pytest.mark.parametrize("form_id", ["ACORD_126", "ACORD_127", "ACORD_130", "ACORD_131", "ACORD_133",
                                     "ACORD_137_CO", "ACORD_138_CO", "ACORD_140", "ACORD_141", "ACORD_160",
                                     "ACORD_186"])
def test_a_section_forms_header_date_is_the_proposed_term_never_a_policys(tmp_path, form_id):
    a = intake.read_for_document(_filled(tmp_path, form_id, _HEADER), "")
    rows = a["facts"].get("coverage_lines") or []
    assert not any(r.get("effective_date") == "01/01/2027" for r in rows), rows
    assert _v(a["facts"]).get("effective_date") == "01/01/2027"


@pytest.mark.parametrize("form_id", ["ACORD_160", "ACORD_138_CO", "ACORD_138_CA"])
def test_a_header_never_invents_a_line_the_form_does_not_apply_for(tmp_path, form_id):
    a = intake.read_for_document(_filled(tmp_path, form_id, _HEADER), "")
    rows = a["facts"].get("coverage_lines") or []
    assert not any(r.get("carrier") == "Header Market Insurance Co" for r in rows), rows
    assert "has_cyber" not in a["flags"] and "has_inland_marine" not in a["flags"]


@pytest.mark.parametrize("form_id,line", [("ACORD_126", "general_liab"), ("ACORD_131", "umbrella"),
                                          ("ACORD_141", "crime")])
def test_a_header_carrier_is_its_own_lines_current_policy(tmp_path, form_id, line):
    from services.lob_canon import canon_line
    a = intake.read_for_document(_filled(tmp_path, form_id, _HEADER), "")
    rows = [r for r in a["facts"].get("coverage_lines") or [] if r.get("carrier") == "Header Market Insurance Co"]
    assert rows and all(canon_line(r["line"]) == line for r in rows)
    assert rows[0].get("policy_number") == "HDR-1" and not rows[0].get("effective_date")


def test_a_certificates_header_is_still_the_current_policy(tmp_path):
    vals = {"Insurer_FullName_A": "Granite State Casualty", "Policy_PolicyNumberIdentifier_A": "CP-9",
            "Policy_EffectiveDate_A": "01/01/2026"}
    r = read.read_acord(_filled(tmp_path, "ACORD_28", vals))
    prop = [x for x in r.facts.get("coverage_lines") or [] if x.get("line") == "Commercial Property"]
    assert prop and prop[0].get("policy_number") == "CP-9" and prop[0].get("effective_date") == "01/01/2026"
    assert "effective_date" not in r.facts


# ── 5. Prose boxes: never table rows, never our own composed blocks ─────────
def test_the_remarks_box_never_becomes_a_loss_row(tmp_path):
    remark = ("Agent remark short. ADDITIONAL LOSSES NOT SHOWN IN THE LOSS HISTORY GRID ABOVE (2 of 5 total): "
              "01/04/2024 CLM-3 General Liability Loss desc 3 paid $1,000.")
    r = read.read_acord(_filled(tmp_path, "ACORD_125", dict(V125, CommercialPolicy_RemarkText_A=remark)))
    assert not r.facts.get("loss_history"), r.facts.get("loss_history")
    assert _v(r.facts)["additional_remarks_text"] == "Agent remark short."


def test_our_own_101_continuations_are_not_read_as_remarks_or_a_narrative(tmp_path):
    text = ("SUBMISSION NARRATIVE\nApproved narrative text.\nThe insured added a second shop in 2025.\n"
            "PRIOR CARRIER INFORMATION (continued from ACORD 125)\nAcme Mutual 2023 ...\n"
            "VEHICLE SCHEDULE (continued from ACORD 127) - 1 of 5 vehicles:\n"
            "Vehicle 5 | 2004 CHEVROLET EXPRESS G2500 | Cost new 24,500 | Class 01483")
    r = read.read_acord(_filled(tmp_path, "ACORD_101", {"AdditionalRemark_RemarkText_A": text}))
    f = _v(r.facts)
    assert "qn_carrier_narrative" not in f
    assert "PRIOR CARRIER" not in str(f.get("additional_remarks_text") or "")
    assert "VEHICLE SCHEDULE" not in str(f.get("additional_remarks_text") or "")
    # Primble's own vehicle continuation is still read back as a vehicle.
    assert any(v.get("make") == "CHEVROLET" for v in f.get("auto_vin_schedule") or [])


def test_an_outside_101s_remarks_are_the_remarks(tmp_path):
    r = read.read_acord(_filled(tmp_path, "ACORD_101", {"AdditionalRemark_RemarkText_A":
                                                         "Insured is moving to a new warehouse in March."}))
    assert _v(r.facts)["additional_remarks_text"] == "Insured is moving to a new warehouse in March."


# ── 6. Row B+ is another entity's row; list facts stay lists ────────────────
def test_a_subsidiarys_employee_count_is_not_the_applicants(tmp_path):
    r = read.read_acord(_filled(tmp_path, "ACORD_131", {"NamedInsured_FullName_A": "Acme LLC",
                                                         "BusinessInformation_EmployeeCount_B": "7"}))
    assert "num_employees" not in r.facts


def test_other_named_insureds_read_as_the_list_fact(tmp_path):
    r = read.read_acord(_filled(tmp_path, "ACORD_125", dict(V125, NamedInsured_FullName_B="Acme Holdings Inc",
                                                             NamedInsured_FullName_C="Acme Leasing LLC")))
    assert not [k for k in r.facts if "#" in k]
    assert _v(r.facts)["additional_named_insureds"] == ["Acme Holdings Inc", "Acme Leasing LLC"]


# ── 7. Coverage flags are THIS submission's lines, never a prior term's ─────
def test_a_prior_carrier_row_sets_no_coverage_flag(tmp_path):
    vals = {"NamedInsured_FullName_A": "Acme LLC", "Policy_LineOfBusiness_CommercialGeneralLiability_A": "Yes",
            "PriorCoverage_Property_InsurerFullName_C": "Old Property Mutual",
            "PriorCoverage_Property_EffectiveDate_C": "01/01/2022",
            "PriorCoverage_Property_ExpirationDate_C": "01/01/2023"}
    a = intake.read_for_document(_filled(tmp_path, "ACORD_125", vals), "")
    assert a["flags"].get("has_general_liability")
    assert "has_property_coverage" not in a["flags"]


# ── 8. A prior-year application gives identity only, and only into a gap ───
def _E(v, s="ai"):
    return {"value": v, "source": s}


def test_a_prior_year_application_never_outvotes_this_years_declarations():
    merged = {"total_revenue": _E("$5,000,000"), "num_employees": _E("40"), "applicant_name": _E("ACME LLC")}
    docs = [{"filename": "dec.pdf", "doc_type": "dec_page", "facts": copy.deepcopy(merged)},
            {"filename": "old125.pdf", "doc_type": "application",
             "facts": {"total_revenue": _E("$3,000,000", "acord_form"), "num_employees": _E("22", "acord_form"),
                       "applicant_name": _E("Acme LLC", "acord_form"), "fein": _E("12-3456789", "acord_form")},
             "acord": {"forms": [{"form_id": "ACORD_125"}], "prior_application": True}}]
    merge_rules.apply_owner_rules(merged, docs)
    assert merged["total_revenue"]["value"] == "$5,000,000"
    assert merged["num_employees"]["value"] == "40"
    assert merged["applicant_name"]["value"] == "ACME LLC"
    assert merged["fein"]["value"] == "12-3456789"            # identity fills the gap


def test_a_certificate_does_not_own_the_applicant():
    merged = {"operations_description": _E("Electrical contractor")}
    docs = [{"filename": "dec.pdf", "doc_type": "dec_page", "facts": copy.deepcopy(merged)},
            {"filename": "coi.pdf", "doc_type": "certificate",
             "facts": {"operations_description": _E("Certificate holder is additional insured", "acord_form")},
             "acord": {"forms": [{"form_id": "ACORD_25"}], "prior_application": False}}]
    merge_rules.apply_owner_rules(merged, docs)
    assert merged["operations_description"]["value"] == "Electrical contractor"


# ── 9. The flattened overlay: aligned exactly, or not read at all ───────────
@pytest.fixture(scope="module")
def flat125(tmp_path_factory):
    d = tmp_path_factory.mktemp("flat")
    src = str(d / "f125.pdf")
    open(src, "wb").write(fill_pdf(os.path.join(TPL, "ACORD_125.pdf"), V125))
    flat = _flatten(src, str(d / "f125_flat.pdf"))
    return d, src, flat


@pytest.mark.parametrize("kw", [dict(dx=4, dy=-3), dict(scale=0.97), dict(scale=0.9, dx=30, dy=40)])
def test_a_shifted_or_scaled_flattened_page_never_reads_a_wrong_value(flat125, kw):
    d, src, flat = flat125
    want = _v(read.read_acord(src).facts)
    moved = _replace(flat, str(d / f"moved_{kw}.pdf"), **kw)
    r = read.read_acord(moved)
    got = _v(r.facts) if r else {}
    wrong = {k: (want.get(k), v) for k, v in got.items() if want.get(k) != v}
    assert not wrong, wrong


def test_a_97_percent_print_still_reads_its_values(flat125):
    d, src, flat = flat125
    want = _v(read.read_acord(src).facts)
    r = read.read_acord(_replace(flat, str(d / "p97.pdf"), scale=0.97))
    got = _v(r.facts)
    for k in ("applicant_name", "fein", "effective_date", "submission_carrier_name"):
        assert got.get(k) == want.get(k), k


def test_a_long_value_drawn_over_a_checkbox_does_not_tick_it(flat125, tmp_path):
    fitz = pytest.importorskip("fitz")
    d, src, flat = flat125
    tpl = overlay._template("ACORD_125")
    (x0, top, x1, bottom), _ft = tpl["pages"][0]["boxes"]["NamedInsured_LegalEntity_TrustIndicator_A"]
    doc = fitz.open(flat)
    doc[0].insert_text((x0 - 40, bottom - 2), "OVERFLOWING TEXT RUNS ACROSS THE BOX", fontsize=7)
    out = str(tmp_path / "overflow.pdf")
    doc.save(out)
    doc.close()
    r = read.read_acord(out)
    assert _v(r.facts).get("entity_type") == "Limited Liability Company"


def _dec_page(path, footer_at_bottom=True):
    from reportlab.pdfgen import canvas
    c = canvas.Canvas(path)
    y = 760
    for line in ["COMMERCIAL GENERAL LIABILITY DECLARATIONS", "PRODUCER: Astrea Insurance Agency",
                 "APPLICANT INFORMATION", "NAMED INSURED: Choice Electric LLC  MAILING ADDRESS: 1234 W Colfax Ave",
                 "CARRIER: Amerisure Insurance Company  POLICY NUMBER: CPP-2201",
                 "EFFECTIVE DATE 01/01/2026 EXPIRATION DATE 01/01/2027",
                 "LINES OF BUSINESS  PREMIUM  INDICATE SECTIONS ATTACHED", "GENERAL LIABILITY  $16,818",
                 "PROPERTY  CRIME  UMBRELLA  INLAND MARINE  ATTACHMENTS",
                 "STATUS OF TRANSACTION  QUOTE  ISSUE  RENEW  CANCEL",
                 "SIGNATURE  PRODUCER'S SIGNATURE  APPLICANT'S SIGNATURE"]:
        c.drawString(40, y, line)
        y -= 40
        if not footer_at_bottom and y == 560:
            c.drawString(40, y, "Supporting application on file: ACORD 125 (2025/03), signed by the insured.")
            y -= 40
    if footer_at_bottom:
        c.drawString(40, 30, "Supporting application on file: ACORD 125 (2025/03)")
    c.save()
    return path


@pytest.mark.parametrize("bottom", [True, False])
def test_a_declarations_page_naming_an_acord_footer_is_not_read_as_that_form(tmp_path, bottom):
    p = _dec_page(str(tmp_path / "dec.pdf"), bottom)
    a = intake.read_for_document(p, "x")
    assert not a or (not a["facts"] and not a.get("classification")), a and a["facts"]
    # ... and its text still reaches the model.
    assert not a or a["other_text"] == "x"


# ── 10. The Primble record: authenticated, bound to its insured ─────────────
@pytest.fixture
def key(monkeypatch):
    from cryptography.fernet import Fernet
    monkeypatch.setenv("FIELD_ENCRYPTION_KEY", Fernet.generate_key().decode())
    import utils.crypto as uc
    monkeypatch.setattr(uc, "_fernet", None, raising=False)
    yield


def _with_docinfo(src, dst, blob):
    import pikepdf
    with pikepdf.open(src) as pdf:
        pdf.docinfo[primble_record.KEY] = pikepdf.String(blob)
        pdf.save(dst)
    return dst


def test_a_plaintext_forged_record_is_ignored(tmp_path, key):
    src = _filled(tmp_path, "ACORD_125", V125)
    forged = json.dumps({"v": 2, "form": "ACORD_125", "applicant": "Pinecrest Landscaping LLC",
                         "answers": {"fein": {"value": "99-9999999", "source": "producer"}}, "ai_boxes": []})
    r = read.read_acord(_with_docinfo(src, str(tmp_path / "forged.pdf"), forged))
    assert not r.primble_record and _v(r.facts)["fein"] == "84-3317790"


def test_a_tampered_record_is_ignored(tmp_path, key):
    src = _filled(tmp_path, "ACORD_125", V125)
    session = {"facts": {"applicant_name": {"value": "Pinecrest Landscaping LLC", "source": "ai"},
                         "occupancy_type": {"value": "Office", "source": "producer"}}, "generated_forms": {}}
    good = primble_record.attach(open(src, "rb").read(), session, "ACORD_125")
    import pikepdf
    import io
    with pikepdf.open(io.BytesIO(good)) as pdf:
        blob = str(pdf.docinfo[primble_record.KEY])
    bad = blob[:-6] + ("A" if blob[-6] != "A" else "B") + blob[-5:]
    r = read.read_acord(_with_docinfo(src, str(tmp_path / "tampered.pdf"), bad))
    assert not r.primble_record and "occupancy_type" not in r.facts


def test_a_record_carried_into_another_insureds_form_restores_nothing(tmp_path, key):
    # An agent re-uses Primble's filled 125 for client X as a template for client Y.
    session_x = {"facts": {"applicant_name": {"value": "Xavier Roofing LLC", "source": "ai"},
                           "occupancy_type": {"value": "Warehouse", "source": "producer"}},
                 "generated_forms": {}}
    src_y = _filled(tmp_path, "ACORD_125", V125)                  # the boxes now say Pinecrest
    out = tmp_path / "reused.pdf"
    out.write_bytes(primble_record.attach(open(src_y, "rb").read(), session_x, "ACORD_125"))
    r = read.read_acord(str(out))
    assert "occupancy_type" not in r.facts


def test_a_prior_year_forms_record_restores_no_answer(tmp_path, key):
    vals = dict(V125, Policy_EffectiveDate_A="01/01/2024", Policy_ExpirationDate_A="01/01/2025")
    src = _filled(tmp_path, "ACORD_125", vals)
    session = {"facts": {"applicant_name": {"value": "Pinecrest Landscaping LLC", "source": "ai"},
                         "total_revenue": {"value": "$3,000,000", "source": "producer"},
                         "effective_date": {"value": "01/01/2024", "source": "producer"}},
               "generated_forms": {}}
    out = tmp_path / "old.pdf"
    out.write_bytes(primble_record.attach(open(src, "rb").read(), session, "ACORD_125"))
    r = read.read_acord(str(out))
    assert r.facts.get("total_revenue") is None
    assert (r.facts.get("effective_date") or {}).get("source") == "acord_form"


def test_an_oversized_record_is_ignored(tmp_path, key):
    from utils.crypto import encrypt_field
    src = _filled(tmp_path, "ACORD_125", V125)
    blob = encrypt_field(json.dumps({"v": 2, "applicant": "Pinecrest Landscaping LLC",
                                     "answers": {"occupancy_type": {"value": "X" * 3_000_000,
                                                                    "source": "producer"}}}))
    r = read.read_acord(_with_docinfo(src, str(tmp_path / "huge.pdf"), blob))
    assert "occupancy_type" not in r.facts


# ── 11. Carry ───────────────────────────────────────────────────────────────
def test_a_carried_value_never_replaces_a_value_the_engine_printed_from_a_fact():
    docs = [{"acord": {"carried": {"ACORD_126": {"Q1": "Y"}}}}]
    mapped, conf = {"Q1": "N"}, {"Q1": {"label": "producer"}}
    assert carry.apply_carried(mapped, conf, docs, "ACORD_126") == [] and mapped["Q1"] == "N"


def test_an_excess_copys_carry_lands_on_the_excess_instance_only(tmp_path):
    vals = {"NamedInsured_FullName_A": "Acme LLC", "Policy_PolicyType_ExcessIndicator_A": "Yes"}
    r = read.read_acord(_filled(tmp_path, "ACORD_131", vals))
    assert "ACORD_131" not in r.carried
    assert all(k == "ACORD_131__excess" for k in r.carried)


# ── 12. Box states and box names as other writers leave them ───────────────
def test_a_checkbox_whose_value_names_no_state_it_shows_is_not_ticked(tmp_path):
    import pikepdf
    from utils import form_field_text as fft
    src = _filled(tmp_path, "ACORD_125", V125)
    out = str(tmp_path / "v_no.pdf")
    with pikepdf.open(src) as pdf:
        for g in fft._scan_widgets(pdf).values():
            if fft._qualified_name(g["field"]) == "NamedInsured_LegalEntity_CorporationIndicator_A":
                g["field"].V = pikepdf.Name("/No")             # a writer's "unticked"
                for w in g["widgets"]:
                    w[1].AS = pikepdf.Name("/Off")
        pdf.save(out)
    r = read.read_acord(out)
    assert _v(r.facts)["entity_type"] == "Limited Liability Company"


def test_designer_prefixed_box_names_are_read_as_acords_own(tmp_path):
    import pikepdf
    src = _filled(tmp_path, "ACORD_125", V125)
    out = str(tmp_path / "renamed.pdf")
    with pikepdf.open(src) as pdf:
        for f in pdf.Root.AcroForm.Fields:
            f.T = pikepdf.String(f"form1[0].Page1[0].{f.T}[0]")
        pdf.save(out)
    r = read.read_acord(out)
    assert r.forms and r.forms[0]["kind"] == "fillable"
    assert _v(r.facts)["applicant_name"] == "Pinecrest Landscaping LLC"


def test_a_scanned_acord_page_is_flagged_for_verification(flat125, tmp_path):
    fitz = pytest.importorskip("fitz")
    d, src, flat = flat125
    doc, out = fitz.open(flat), fitz.open()
    for pg in doc:
        page = out.new_page(width=pg.rect.width, height=pg.rect.height)
        page.insert_image(page.rect, pixmap=pg.get_pixmap(dpi=72))
    path = str(tmp_path / "scan.pdf")
    out.save(path)
    ocr = "\n".join(f"[Document page {i + 1}]\nAPPLICANT INFORMATION ...\nACORD 125 (2025/03) Page {i + 1} of 4"
                    for i in range(len(doc)))
    a = intake.read_for_document(path, ocr)
    assert a and not a["facts"] and not a["classification"]
    assert a["record"]["needs_verification"][0]["kind"] == "scanned"
    assert a["other_text"] == ocr


# ── 13. A box's text must fit its fact ──────────────────────────────────────
@pytest.mark.parametrize("masked", ["XX-XXXXXXX", "**-***4567", "XX-XXX4567"])
def test_a_redacted_fein_is_no_fein(tmp_path, masked):
    r = read.read_acord(_filled(tmp_path, "ACORD_125", dict(V125, NamedInsured_TaxIdentifier_A=masked)))
    assert "fein" not in r.facts


def test_a_redacted_fein_never_replaces_the_decs():
    merged = {"fein": _E("84-1234567")}
    docs = [{"filename": "dec.pdf", "doc_type": "dec_page", "facts": {"fein": _E("84-1234567")}},
            {"filename": "a.pdf", "doc_type": "application", "facts": {},
             "acord": {"forms": [{"form_id": "ACORD_125"}], "prior_application": False}}]
    merge_rules.apply_owner_rules(merged, docs)
    assert merged["fein"]["value"] == "84-1234567"


def test_a_words_convention_in_an_amount_box_is_still_read(tmp_path):
    r = read.read_acord(_filled(tmp_path, "ACORD_131", {
        "NamedInsured_FullName_A": "Acme LLC",
        "WorkersCompensationEmployersLiability_EmployersLiability_EachAccidentLimitAmount_A": "1,000,000"}))
    assert _v(r.facts).get("wc_el_each_accident") == "1,000,000"


# ── 14. Mixed and combined PDFs: only what was READ skips the model ────────
def _page_pdf(path, lines):
    from reportlab.pdfgen import canvas
    c = canvas.Canvas(path)
    y = 760
    for line in lines:
        c.drawString(40, y, line)
        y -= 30
    c.save()
    return path


def test_a_combined_pdf_without_a_form_dictionary_is_still_read_by_box(tmp_path):
    """dec + ACORD 125 + loss run, combined by a tool that copies pages but not
    the /AcroForm: the 125's boxes were invisible, its pages counted as "read"
    with 0 boxes, and their text never reached the model either."""
    pikepdf = pytest.importorskip("pikepdf")
    dec = _page_pdf(str(tmp_path / "dec.pdf"), ["COMMERCIAL GENERAL LIABILITY DECLARATIONS", "POLICY CGL-1"])
    loss = _page_pdf(str(tmp_path / "loss.pdf"), ["LOSS RUN REPORT", "Claim 1 01/02/2024 $1,200 paid"])
    app = _filled(tmp_path, "ACORD_125", V125)
    out = tmp_path / "mixed.pdf"
    with pikepdf.open(dec) as pdf:
        for f in (app, loss):
            with pikepdf.open(f) as other:
                pdf.pages.extend(other.pages)
        n = len(pdf.pages)
        pdf.save(out)
    text = "\n".join(f"[Document page {i + 1}]\nPAGE {i + 1} TEXT" for i in range(n))
    a = intake.read_for_document(str(out), text)
    assert _v(a["facts"])["applicant_name"] == "Pinecrest Landscaping LLC"
    assert "PAGE 1 TEXT" in a["other_text"] and f"PAGE {n} TEXT" in a["other_text"]
    assert "PAGE 2 TEXT" not in a["other_text"]


def test_a_flattened_form_that_read_no_box_goes_to_the_model(tmp_path):
    blank = _flatten(os.path.join(TPL, "ACORD_126.pdf"), str(tmp_path / "blank126.pdf"))
    a = intake.read_for_document(blank, "[Document page 1]\nBLANK FORM TEXT")
    assert not a["record"]["forms"] and not a["classification"]
    assert "BLANK FORM TEXT" in a["other_text"]


def test_flattened_pages_out_of_order_are_one_copy(flat125, tmp_path):
    pikepdf = pytest.importorskip("pikepdf")
    d, src, flat = flat125
    out = str(tmp_path / "flat_shuffled.pdf")
    with pikepdf.open(flat) as pdf:
        pdf.pages.insert(0, pdf.pages[1])
        del pdf.pages[2]
        pdf.save(out)
    r = read.read_acord(out)
    assert len([c for c in r.forms if c["form_id"] == "ACORD_125"]) == 1
    assert _v(r.facts)["applicant_name"] == "Pinecrest Landscaping LLC"


# ── 15. An amount whose meaning its row's tick decides ─────────────────────
@pytest.mark.parametrize("tick,fact", [("Vehicle_CombinedSingleLimit_LimitIndicator_A", "auto_liability_limit"),
                                       ("Vehicle_BodilyInjury_EachPersonLimitIndicator_A", "auto_bi_per_person"),
                                       (None, None)])
def test_the_137_liability_amount_is_what_its_tick_says(tmp_path, tick, fact):
    vals = {"NamedInsured_FullName_A": "Acme LLC", "Vehicle_BodilyInjury_PerPersonLimitAmount_A": "250,000"}
    if tick:
        vals[tick] = "Yes"
    f = _v(read.read_acord(_filled(tmp_path, "ACORD_137_CA", vals)).facts)
    for k in ("auto_liability_limit", "auto_bi_per_person"):
        assert f.get(k) == ("250,000" if k == fact else None), (k, f.get(k))


def test_a_certificate_ahead_of_an_application_does_not_type_the_pdf_a_certificate(tmp_path):
    pikepdf = pytest.importorskip("pikepdf")
    cert = _filled(tmp_path, "ACORD_25", {"NamedInsured_FullName_A": "Pinecrest Landscaping LLC"})
    app = _filled(tmp_path, "ACORD_125", V125)
    out = tmp_path / "cert_then_app.pdf"
    with pikepdf.open(cert) as pdf:
        with pikepdf.open(app) as other:
            pdf.pages.extend(other.pages)
        pdf.save(out)
    a = intake.read_for_document(str(out), "")
    assert a["classification"]["doc_type"] == "application"


def test_without_page_markers_unread_pages_are_never_dropped(tmp_path):
    pikepdf = pytest.importorskip("pikepdf")
    app = _filled(tmp_path, "ACORD_125", V125)
    loss = _page_pdf(str(tmp_path / "loss.pdf"), ["LOSS RUN REPORT", "Claim 1 01/02/2024 $1,200 paid"])
    out = tmp_path / "app_loss.pdf"
    with pikepdf.open(app) as pdf:
        with pikepdf.open(loss) as other:
            pdf.pages.extend(other.pages)
        pdf.save(out)
    a = intake.read_for_document(str(out), "WHOLE TEXT WITHOUT MARKERS")
    assert a["other_text"] == "WHOLE TEXT WITHOUT MARKERS"


# ── 16. End to end through the merge: identity, term, FEIN ─────────────────
def _merged_with_dec(tmp_path, values, dec_facts):
    from services.extraction_service import merge_facts
    from services.underwriting_consistency import assess_underwriting_consistency
    a = intake.read_for_document(_filled(tmp_path, "ACORD_125", values), "")
    E = lambda v: {"value": v, "source": "ai", "confidence": "high"}               # noqa: E731
    dec = {"doc_id": "d", "filename": "dec.pdf", "doc_type": "dec_page",
           "facts": {k: E(v) for k, v in dec_facts.items()}, "flags": {}}
    app = {"doc_id": "a", "filename": "ACORD_125.pdf", "doc_type": a["classification"]["doc_type"],
           "facts": a["facts"], "flags": a["flags"], "acord": a["record"]}
    docs = [dec, app]
    merged, flags = merge_facts(docs, docs[0])
    return docs, merged, assess_underwriting_consistency(docs, merged, {}, flags)


def test_the_proposed_term_never_cards_against_the_current_term_and_a_real_fein_difference_does(tmp_path):
    dec = {"applicant_name": "PINECREST LANDSCAPING LLC", "fein": "84-3317790",
           "effective_date": "12/01/2025", "expiration_date": "12/01/2026"}
    _d, merged, uw = _merged_with_dec(tmp_path, V125, dec)
    cards = {f["fact_key"] for f in uw["fields"] if f.get("review_required")}
    assert not cards & {"effective_date", "expiration_date"}, cards
    assert _v(merged)["effective_date"] == "12/01/2026"           # the ACORD's proposed term
    _d, _m, uw = _merged_with_dec(tmp_path, V125, dict(dec, fein="84-9999999"))
    assert "fein" in {f["fact_key"] for f in uw["fields"] if f.get("review_required")}


def test_another_insureds_acord_still_trips_submission_integrity(tmp_path):
    from services.submission_integrity import assess_submission_integrity
    docs, _m, _uw = _merged_with_dec(tmp_path, V125, {"applicant_name": "CHOICE ELECTRIC LLC",
                                                      "fein": "84-1234567"})
    assert assess_submission_integrity(docs)["review_required"]


def test_premises_rows_that_disagree_give_no_package_coinsurance(tmp_path):
    same = {"NamedInsured_FullName_A": "Acme LLC", "CommercialProperty_Premises_CoinsurancePercent_A": "80",
            "CommercialProperty_Premises_CoinsurancePercent_B": "80"}
    assert _v(read.read_acord(_filled(tmp_path, "ACORD_140", same, "s.pdf")).facts)["coinsurance_percentage"] == "80"
    differ = dict(same, CommercialProperty_Premises_CoinsurancePercent_B="90")
    assert "coinsurance_percentage" not in read.read_acord(_filled(tmp_path, "ACORD_140", differ, "d.pdf")).facts


@pytest.mark.parametrize("tick,payee", [("AdditionalInterest_Interest_LossPayeeIndicator_A", "First Bank"),
                                        ("AdditionalInterest_Interest_OtherIndicator_A", None),
                                        (None, None)])
def test_an_additional_interest_is_the_loss_payee_only_when_ticked_so(tmp_path, tick, payee):
    vals = dict(V125, AdditionalInterest_FullName_A="First Bank")
    if tick:
        vals[tick] = "Yes"
    if tick and "Other" in tick:
        vals["AdditionalInterest_Interest_OtherDescription_A"] = "Landlord"
    assert _v(read.read_acord(_filled(tmp_path, "ACORD_125", vals)).facts).get("loss_payee_name") == payee


# ── Re-review (27 Oct): the lead's four changes ────────────────────────────
_STARRED_186 = "Contractors_Question_AABCode_A"       # "* DO NOT ANSWER IF ATTACHED TO ACORD 126"


def _carry_into(form_id, boxes, package):
    docs = [{"acord": {"carried": {form_id: dict(boxes)}}}]
    mapped, conf = {}, {}
    facts = {"_form_id": form_id, "_package_form_ids": list(package)}
    return carry.apply_carried(mapped, conf, docs, form_id, facts=facts), mapped


def test_a_starred_186_answer_is_not_carried_beside_a_126():
    other = "Contractors_Question_AAACode_A"
    moved, mapped = _carry_into("ACORD_186", {_STARRED_186: "N", other: "Y"},
                                ["ACORD_125", "ACORD_126", "ACORD_186"])
    assert _STARRED_186 not in mapped and mapped.get(other) == "Y"
    moved, mapped = _carry_into("ACORD_186", {_STARRED_186: "N"}, ["ACORD_125", "ACORD_186"])
    assert mapped.get(_STARRED_186) == "N"


def test_a_blank_the_engine_owns_for_want_of_data_still_takes_the_uploaded_value():
    """An owner that leaves a box blank because the PACKAGE lacks the fact is not
    a rule against the uploaded form's own typed value: the round trip of the
    Choice Electric forms lost the excess 131's underlying schedule, the 125's
    audit code, the 126's EBL count and the 137's symbol rows B-H this way."""
    moved, mapped = _carry_into("ACORD_125", {"Policy_Audit_FrequencyCode_A": "A"}, ["ACORD_125"])
    assert mapped.get("Policy_Audit_FrequencyCode_A") == "A"
    moved, mapped = _carry_into("ACORD_137_CO", {"Vehicle_BusinessAutoSymbol_SevenIndicator_F": "Yes"},
                                ["ACORD_125", "ACORD_127", "ACORD_137_CO"])
    assert mapped.get("Vehicle_BusinessAutoSymbol_SevenIndicator_F") == "Yes"


def test_an_attachment_tick_is_never_carried(tmp_path):
    """Which forms are attached is THIS package's fact, decided by the engine -
    an uploaded 125's "Contractors Supplement attached" tick is not."""
    vals = dict(V125, CommercialPolicy_Attachment_ContractorsSupplementIndicator_A="Yes")
    r = read.read_acord(_filled(tmp_path, "ACORD_125", vals))
    assert "CommercialPolicy_Attachment_ContractorsSupplementIndicator_A" not in r.carried.get("ACORD_125", {})


def _owner(app_facts, other_docs, prior=False):
    """apply_owner_rules over one ACORD 125 and `other_docs` [(doc_type, facts)]."""
    merged = {}
    docs = []
    for dt, f in other_docs:
        docs.append({"filename": f"{dt}.pdf", "doc_type": dt, "facts": {k: _E(v) for k, v in f.items()}})
        for k, v in f.items():
            merged.setdefault(k, _E(v))
    docs.append({"filename": "a125.pdf", "doc_type": "application",
                 "facts": {k: _E(v, "acord_form") for k, v in app_facts.items()},
                 "acord": {"forms": [{"form_id": "ACORD_125"}], "prior_application": prior}})
    merge_rules.apply_owner_rules(merged, docs)
    return _v(merged)


_APP = {"applicant_name": "Choice Electric LLC", "effective_date": "01/01/2027", "fein": "84-1234567"}


@pytest.mark.parametrize("printed", ["CHOICE ELECTRIC", "Choice Elec. LLC", "The Choice Electric Company",
                                     "CHOICEELECTRICLLC", "Choice Electric Inc"])
def test_a_spelling_of_the_same_insured_keeps_the_acords_ownership(printed):
    """A loss run that abbreviates the insured is still the same insured (the
    test Submission Integrity applies) - it must not hand the PROPOSED term back
    to the documents' current one."""
    m = _owner(_APP, [("loss_run", {"applicant_name": printed, "effective_date": "01/01/2025"})])
    assert m["effective_date"] == "01/01/2027"


def test_a_dba_on_the_dec_is_the_same_insured():
    m = _owner(dict(_APP, applicant_name="Acme Holdings LLC", dba_name="Rocket Roofing"),
               [("dec_page", {"applicant_name": "ROCKET ROOFING", "effective_date": "01/01/2025"})])
    assert m["effective_date"] == "01/01/2027"


def test_the_same_fein_is_the_same_insured_whatever_the_name():
    m = _owner(dict(_APP, applicant_name="Eric Berger dba Choice Electric"),
               [("dec_page", {"applicant_name": "ERIC BERGER", "fein": "841234567",
                              "effective_date": "01/01/2025"})])
    assert m["effective_date"] == "01/01/2027"


def test_another_insureds_acord_owns_nothing_and_a_heading_names_nobody():
    m = _owner(dict(_APP, applicant_name="Front Range Electrical Contractors LLC"),
               [("dec_page", {"applicant_name": "CHOICE ELECTRIC LLC", "effective_date": "01/01/2025"})])
    assert m["applicant_name"] == "CHOICE ELECTRIC LLC" and m["effective_date"] == "01/01/2025"
    # A billing heading read as the insured ("S.B. MO.", 8 Oct) names no party.
    m = _owner(_APP, [("dec_page", {"applicant_name": "S.B. MO.", "effective_date": "01/01/2025"})])
    assert m["effective_date"] == "01/01/2027"


def test_decs_naming_nobody_or_an_acord_naming_nobody_keep_the_ownership():
    assert _owner(_APP, [("dec_page", {"effective_date": "01/01/2025"})])["effective_date"] == "01/01/2027"
    no_name = {k: v for k, v in _APP.items() if k != "applicant_name"}
    assert _owner(no_name, [("dec_page", {"applicant_name": "CHOICE ELECTRIC LLC",
                                          "effective_date": "01/01/2025"})])["effective_date"] == "01/01/2027"


def test_several_decs_one_naming_the_applicant_keep_the_ownership():
    m = _owner(_APP, [("dec_page", {"applicant_name": "CHOICE ELECTRIC LLC", "effective_date": "01/01/2025"}),
                      ("dec_page", {"applicant_name": "HARBORLINE PLUMBING LLC"})])
    assert m["effective_date"] == "01/01/2027"


def test_another_insureds_prior_year_acord_fills_no_gap():
    m = _owner(dict(_APP, applicant_name="Front Range Electrical Contractors LLC", fein="12-3456789"),
               [("dec_page", {"applicant_name": "CHOICE ELECTRIC LLC"})], prior=True)
    assert "fein" not in m


def test_the_record_rides_on_no_certificate(tmp_path, key):
    src = _filled(tmp_path, "ACORD_25", {"NamedInsured_FullName_A": "Pinecrest Landscaping LLC"})
    session = {"facts": {"applicant_name": {"value": "Pinecrest Landscaping LLC", "source": "ai"},
                         "occupancy_type": {"value": "Office", "source": "producer"}}, "generated_forms": {}}
    raw = open(src, "rb").read()
    for fid in ("ACORD_25", "ACORD_28"):
        assert primble_record.attach(raw, session, fid) == raw
    assert primble_record.attach(raw, session, "ACORD_125") != raw


def test_a_certificates_description_box_is_the_certificates_description(tmp_path):
    box = "CertificateOfLiabilityInsurance_ACORDForm_RemarkText_A"
    r = read.read_acord(_filled(tmp_path, "ACORD_25", {box: "Holder is additional insured per written contract"}))
    f = _v(r.facts)
    assert f.get("certificate_description_of_operations") == "Holder is additional insured per written contract"
    assert "operations_description" not in f
