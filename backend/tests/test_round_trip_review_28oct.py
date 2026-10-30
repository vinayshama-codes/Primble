"""Hostile review of the round trip (28 Oct 2026, ACORD_INTAKE.md "Review (28 Oct)").

Our own downloaded forms re-uploaded must never score above the package that
printed them, must bring back every person answer, and must not duplicate a row.
Each test pins one defect found by replaying the owner's three test packages
(Orbin, Choice Electric, CH125) offline through the real download door, reader
and merge - written failing first."""
import asyncio
import copy
import io
import json
import os
import random

import pytest

from services.acord_intake import carry, intake, merge_rules, primble_record, read
from services.pdf_service import fill_pdf

BACKEND = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TPL = os.path.join(BACKEND, "templates")


@pytest.fixture(autouse=True)
def _fernet(monkeypatch):
    from cryptography.fernet import Fernet
    monkeypatch.setenv("FIELD_ENCRYPTION_KEY", Fernet.generate_key().decode())


def _v(facts):
    return {k: (v.get("value") if isinstance(v, dict) and "value" in v else v) for k, v in (facts or {}).items()}


V125 = {
    "NamedInsured_FullName_A": "Pinecrest Landscaping LLC",
    "NamedInsured_TaxIdentifier_A": "84-3317790",
    "NamedInsured_MailingAddress_LineOne_A": "2215 Juniper Ave",
    "NamedInsured_MailingAddress_CityName_A": "Boulder",
    "NamedInsured_MailingAddress_StateOrProvinceCode_A": "CO",
    "NamedInsured_MailingAddress_PostalCode_A": "80304",
    "Policy_EffectiveDate_A": "12/01/2026",
    "Policy_ExpirationDate_A": "12/01/2027",
}
SESSION_FACTS = {"applicant_name": {"value": "Pinecrest Landscaping LLC", "source": "ai"}}


def _our_form(tmp_path, form_id, values, ai_labels, name, facts=None, flags=None):
    """A form downloaded from Primble: filled by the real filler, the record
    attached by the real writer, `ai_labels` = {box: label} the generation gave."""
    raw = fill_pdf(os.path.join(TPL, f"{form_id}.pdf"), values)
    conf = {b: "filled" for b in values}
    conf.update(ai_labels)
    session = {"facts": dict(facts or SESSION_FACTS), "flags": dict(flags or {}),
               "generated_forms": {form_id: {"mapped": dict(values), "confidence": conf}}}
    p = tmp_path / name
    p.write_bytes(primble_record.attach(raw, session, form_id))
    return str(p)


# ── 1. An AI box is never a reading - in a table cell, a tick or a part ─────
def test_an_ai_vehicle_cell_never_becomes_a_vehicle_value(tmp_path):
    vals = {"NamedInsured_FullName_A": "Pinecrest Landscaping LLC",
            "Vehicle_ModelYear_A": "2014", "Vehicle_ManufacturersName_A": "CHEVROLET",
            "Vehicle_ModelName_A": "EXPRESS", "Vehicle_CostNewAmount_A": "78,450"}
    p = _our_form(tmp_path, "ACORD_127", vals, {"Vehicle_CostNewAmount_A": "ai_verified"}, "127.pdf")
    r = read.read_acord(p)
    rows = r.facts.get("auto_vin_schedule") or []
    assert rows and not any(row.get("cost_new") for row in rows)          # was "78,450", exact
    assert r.carried["ACORD_127"]["Vehicle_CostNewAmount_A"] == "78,450"   # back onto its own box
    assert r.carried_ai["ACORD_127"] == ["Vehicle_CostNewAmount_A"]


def test_an_unverified_ai_guess_is_an_ai_box_too():
    """"low_confidence" is the label of an unverified gap fill - the first build
    kept only labels starting "ai", so every unverified guess read back exact."""
    g = {"mapped": {"Vehicle_CostNewAmount_A": "78,450", "Policy_EffectiveDate_A": "12/01/2026",
                    "Producer_MailingAddress_PostalCode_A": "201301", "Empty_A": ""},
         "confidence": {"Vehicle_CostNewAmount_A": "low_confidence", "Policy_EffectiveDate_A": "low_confidence",
                        "Producer_MailingAddress_PostalCode_A": "low_confidence", "Empty_A": "low_confidence"}}
    facts = {"effective_date": {"value": "12/01/2026", "source": "derived", "confidence": "low_confidence"},
             "producer_address": {"value": "C-52, Sector 65, Noida, India, 201301", "source": "account"}}
    boxes = primble_record._ai_boxes(g, facts, "ACORD_127")
    assert "Vehicle_CostNewAmount_A" in boxes
    assert "Policy_EffectiveDate_A" not in boxes            # the calculated next term is a fact
    assert "Producer_MailingAddress_PostalCode_A" not in boxes   # a part of a fact's value
    assert "Empty_A" not in boxes


def test_an_ai_tick_never_becomes_an_entity_type(tmp_path):
    vals = dict(V125, NamedInsured_LegalEntity_LimitedLiabilityCorporationIndicator_A="Yes")
    p = _our_form(tmp_path, "ACORD_125", vals,
                  {"NamedInsured_LegalEntity_LimitedLiabilityCorporationIndicator_A": "low_confidence"}, "125.pdf")
    r = read.read_acord(p)
    assert "entity_type" not in r.facts
    assert r.carried["ACORD_125"]["NamedInsured_LegalEntity_LimitedLiabilityCorporationIndicator_A"] == "Yes"


def test_an_ai_box_typed_over_after_download_is_the_forms_own_statement(tmp_path):
    import pikepdf
    vals = {"NamedInsured_FullName_A": "Pinecrest Landscaping LLC",
            "Vehicle_ModelYear_A": "2014", "Vehicle_ManufacturersName_A": "CHEVROLET",
            "Vehicle_ModelName_A": "EXPRESS", "Vehicle_CostNewAmount_A": "78,450"}
    p = _our_form(tmp_path, "ACORD_127", vals, {"Vehicle_CostNewAmount_A": "ai_verified"}, "127.pdf")
    with pikepdf.open(p) as pdf:          # the producer types the real cost in a PDF reader
        for f in pdf.Root.AcroForm.Fields:
            if str(f.get("/T")) == "Vehicle_CostNewAmount_A":
                f.V = pikepdf.String("81,000")
        out = tmp_path / "edited.pdf"
        pdf.save(out)
    r = read.read_acord(str(out))
    assert [row.get("cost_new") for row in r.facts["auto_vin_schedule"]] == ["81,000"]
    assert "Vehicle_CostNewAmount_A" not in r.carried.get("ACORD_127", {})


def test_another_insureds_record_marks_no_ai_box(tmp_path):
    """An agent's re-used form for another client: the record says nothing."""
    vals = dict(V125, NamedInsured_FullName_A="Front Range Roofing Inc")
    p = _our_form(tmp_path, "ACORD_125", vals, {"NamedInsured_TaxIdentifier_A": "ai_verified"}, "125.pdf")
    r = read.read_acord(p)
    assert not r.own_form and _v(r.facts)["fein"] == "84-3317790"


def test_a_carried_ai_box_keeps_its_ai_label():
    doc = {"filename": "127.pdf", "acord": {"forms": [{"form_id": "ACORD_127"}],
                                           "carried": {"ACORD_127": {"Vehicle_CostNewAmount_A": "78,450",
                                                                     "Vehicle_Question_X_A": "Y"}},
                                           "carried_ai": {"ACORD_127": ["Vehicle_CostNewAmount_A"]},
                                           "ai_labels": {"Vehicle_CostNewAmount_A": "ai_verified"}}}
    mapped, conf = {}, {}
    carry._apply_carried(mapped, conf, [doc], "ACORD_127")
    assert mapped["Vehicle_CostNewAmount_A"] == "78,450"
    assert conf["Vehicle_CostNewAmount_A"] == "ai_verified"          # still a Please verify row
    assert (conf["Vehicle_Question_X_A"] or {}).get("label") == "filled"
    # an outside copy stating the same value is evidence: no AI label
    other = {"filename": "x.pdf", "acord": {"forms": [{"form_id": "ACORD_127"}],
                                           "carried": {"ACORD_127": {"Vehicle_CostNewAmount_A": "78,450"}}}}
    assert carry.carried_ai_labels([doc, other], "ACORD_127") == {}


@pytest.mark.parametrize("seed", range(6))
def test_fuzz_ai_boxes_change_no_reading(tmp_path, seed):
    """Property: our form with AI boxes reads to EXACTLY the facts of the same
    form without them, and every AI box is carried back with its value."""
    rnd = random.Random(seed)
    schema = json.load(open(os.path.join(BACKEND, "forms_schemas", "ACORD_125_schema.json")))
    text = [b for b, m in schema.items() if m.get("ft") == "/Tx" and b not in V125 and not b.startswith("Form_")]
    ticks = [b for b, m in schema.items() if m.get("ft") == "/Btn"]
    ai = {b: f"ZQ{seed}X{i}" for i, b in enumerate(rnd.sample(text, 12))}
    ai.update({b: "Yes" for b in rnd.sample(ticks, 6)})
    labels = {b: rnd.choice(("ai_verified", "low_confidence")) for b in ai}
    with_ai = _our_form(tmp_path, "ACORD_125", {**V125, **ai}, labels, f"a{seed}.pdf")
    without = _our_form(tmp_path, "ACORD_125", dict(V125), {}, f"b{seed}.pdf")
    ra, rb = read.read_acord(with_ai), read.read_acord(without)
    assert json.dumps(_v(ra.facts), sort_keys=True, default=str) == json.dumps(_v(rb.facts), sort_keys=True, default=str)
    for b, val in ai.items():
        assert ra.carried["ACORD_125"].get(b) == val, b


# ── 2. Our own form's words are never document text ─────────────────────────
def test_our_own_form_keeps_no_text_and_an_outside_form_does(tmp_path):
    ours = _our_form(tmp_path, "ACORD_125", dict(V125), {}, "ours.pdf")
    got = intake.read_for_document(ours, "[Document page 1]\nNamed Insured Full Name (A): Pinecrest")
    assert got["stored_text"] == "" and got["record"]["own_form"] is True
    outside = tmp_path / "outside.pdf"
    outside.write_bytes(fill_pdf(os.path.join(TPL, "ACORD_125.pdf"), dict(V125)))
    got = intake.read_for_document(str(outside), "[Document page 1]\nNamed Insured Full Name (A): Pinecrest")
    assert got["stored_text"] is None


def test_the_stored_document_has_no_text_but_keeps_its_identity(tmp_path, monkeypatch):
    """Orbin forms + declarations scored 81 against the package's 79: the
    narrative scan read our printed forms as narrative evidence."""
    import services.extraction_pipeline as ep

    async def _no_model(*a, **k):
        raise AssertionError("no model call for a fully read ACORD form")
    monkeypatch.setattr(ep, "extract_facts_long", _no_model)
    ours = _our_form(tmp_path, "ACORD_125", dict(V125), {}, "ours.pdf")
    doc = asyncio.run(ep.extract_document(ours, "ours.pdf", None))
    assert doc["text"] == "" and doc["text_key"]
    assert ep.stored_text_key(doc) == doc["text_key"]
    # the same file added again is still recognised as already in the package
    again = asyncio.run(ep.extract_document(ours, "ours (1).pdf", None, known_texts={doc["text_key"]}))
    assert again.get("duplicate") is True


# ── 3. A forms-only re-upload keeps what the business IS ────────────────────
def test_the_record_carries_business_flags_never_lines_or_evidence(tmp_path):
    flags = {"is_contractor": True, "auto_has_hired_nonowned": True, "has_umbrella": True,
             "has_loss_run_doc": True, "narrative_states_no_losses": True, "asserts_no_known_losses": True,
             "_carrier_documents_only": True, "has_waiver_of_subrogation": True, "wc_multi_state": False}
    p = _our_form(tmp_path, "ACORD_125", dict(V125), {}, "ours.pdf", flags=flags)
    r = read.read_acord(p)
    assert r.restored["flags"] == {"is_contractor": True, "auto_has_hired_nonowned": True,
                                   "has_waiver_of_subrogation": True}


def test_restored_flags_fill_only_a_flag_no_document_states():
    doc = {"filename": "125.pdf", "doc_type": "application", "facts": {"applicant_name": {"value": "Pinecrest"}},
           "acord": {"forms": [{"form_id": "ACORD_125"}],
                     "restored": {"answers": {}, "tables": {}, "stores": {},
                                  "flags": {"is_contractor": True, "auto_has_hired_nonowned": True}}}}
    mg = {"auto_has_hired_nonowned": False}
    assert merge_rules.apply_restored_flags(mg, [doc]) == ["is_contractor"]
    assert mg == {"auto_has_hired_nonowned": False, "is_contractor": True}
    dec = {"filename": "dec.pdf", "doc_type": "dec_page", "facts": {"applicant_name": {"value": "Front Range Roofing"}}}
    mg = {}
    merge_rules.apply_restored_flags(mg, [doc, dec])                 # beside another insured's documents
    assert mg == {}


# ── 4. Wrong readings found box by box ───────────────────────────────────────
def test_a_contact_block_printing_a_schedule_names_no_package_contact(tmp_path):
    """CH125: row A was the INSPECTION contact, the package contact sat in row B."""
    vals = dict(V125, NamedInsured_Contact_FullName_A="Rafael Quintero",
                NamedInsured_Contact_ContactDescription_A="Inspection",
                NamedInsured_Contact_PrimaryPhoneNumber_A="615-555-0177",
                NamedInsured_Contact_FullName_B="Denise Okafor",
                NamedInsured_Contact_ContactDescription_B="Accounting",
                NamedInsured_Contact_PrimaryPhoneNumber_B="615-555-0165")
    p = tmp_path / "c.pdf"
    p.write_bytes(fill_pdf(os.path.join(TPL, "ACORD_125.pdf"), vals))
    r = read.read_acord(str(p))
    assert not {"contact_name", "contact_phone"} & set(r.facts)
    assert r.carried["ACORD_125"]["NamedInsured_Contact_FullName_A"] == "Rafael Quintero"
    one = tmp_path / "one.pdf"
    one.write_bytes(fill_pdf(os.path.join(TPL, "ACORD_125.pdf"),
                             dict(V125, NamedInsured_Contact_FullName_A="Denise Okafor",
                                  NamedInsured_Contact_PrimaryPhoneNumber_A="615-555-0165")))
    assert _v(read.read_acord(str(one)).facts)["contact_name"] == "Denise Okafor"   # one contact: it is the contact


def test_a_payment_method_box_reads_as_the_payment_method(tmp_path):
    """CH125: "ACH" came back as the billing plan against the dec's "Direct bill"."""
    p = tmp_path / "p.pdf"
    p.write_bytes(fill_pdf(os.path.join(TPL, "ACORD_125.pdf"),
                           dict(V125, Policy_PaymentMethod_MethodDescription_A="ACH")))
    f = _v(read.read_acord(str(p)).facts)
    assert f.get("payment_method") == "ACH" and "billing_plan" not in f
    p2 = tmp_path / "p2.pdf"
    p2.write_bytes(fill_pdf(os.path.join(TPL, "ACORD_125.pdf"),
                            dict(V125, Policy_PaymentMethod_MethodDescription_A="Direct bill")))
    assert _v(read.read_acord(str(p2)).facts).get("billing_plan") == "Direct bill"


def test_a_declaration_agreeing_with_the_form_keeps_its_value():
    """Choice Electric: the excess dec's $4M outvoted the 131's $5M, which the
    umbrella's own dec prints too."""
    app = {"filename": "131.pdf", "doc_type": "acord_form",
           "facts": {"umbrella_limit": {"value": "5,000,000", "source": "acord_form"}},
           "acord": {"forms": [{"form_id": "ACORD_131"}]}}
    excess = {"filename": "excess.pdf", "doc_type": "dec_page",
              "facts": {"umbrella_limit": {"value": "$4,000,000", "source": "ai"}}}
    umb = {"filename": "umbrella.pdf", "doc_type": "dec_page",
           "facts": {"umbrella_limit": {"value": "$5,000,000", "source": "ai"}}}
    merged = {"umbrella_limit": app["facts"]["umbrella_limit"]}
    merge_rules.apply_owner_rules(merged, [app, excess, umb])
    assert merged["umbrella_limit"]["value"] == "$5,000,000" and merged["umbrella_limit"]["source"] == "ai"
    merged = {"umbrella_limit": app["facts"]["umbrella_limit"]}
    merge_rules.apply_owner_rules(merged, [app, excess])              # nobody agrees: a dec still wins
    assert merged["umbrella_limit"]["value"] == "$4,000,000"


# ── 5. Nothing is duplicated ─────────────────────────────────────────────────
def _acord(name, form_id, facts):
    return {"filename": name, "doc_type": "acord_form", "facts": facts,
            "acord": {"forms": [{"form_id": form_id, "copy": 1}], "read_keys": sorted(facts)}}


def _rows(view, key):
    return [r for d in view for r in (merge_rules._fv((d.get("facts") or {}).get(key)) or [])]


def test_the_127s_drivers_fold_into_the_declarations_drivers():
    dec = {"filename": "pkg.pdf", "doc_type": "dec_page", "facts": {"auto_drivers": [
        {"name": "Gregory L. Szymanski", "dob": "1969-02-14", "license_number": "098317562"},
        {"name": "Szymanski, Gregory L"},                       # the dec's own second printing stays
        {"name": "Ambrose, Kyle J"}, {"name": "Pettus, Carl"}]}}
    f127 = _acord("127.pdf", "ACORD_127", {"auto_drivers": [
        {"name": "Gregory L. Szymanski"}, {"name": "Szymanski, Gregory"}, {"name": "Ambrose, Kyle"},
        {"name": "Pettus, Carl", "vehicle_use_percent": "30"}]})
    view, _ = merge_rules.fold_acord_lists([f127, dec], dec)
    rows = _rows(view, "auto_drivers")
    assert len(rows) == 4                                      # was 8
    assert next(r for r in rows if "Pettus" in r["name"])["vehicle_use_percent"] == "30"


def test_two_people_never_fold_by_a_shared_name_word():
    out = merge_rules.fold_rows("auto_drivers", [[{"name": "Carl Pettus"}], [{"name": "Carl Pettus Jr"}]])
    assert len(out) == 2
    out = merge_rules.fold_rows("auto_drivers", [[{"name": "Carl Pettus", "dob": "1980-01-01"}],
                                                [{"name": "Pettus, Carl", "dob": "01/02/1980"}]])
    assert len(out) == 2


def test_a_policy_printed_by_the_125_grid_and_the_dec_is_one_policy():
    dec = {"filename": "pkg.pdf", "doc_type": "dec_page", "facts": {"prior_coverage_by_line": [
        {"line": "UMBRC", "carrier": "Cardinal Excess Insurance Company", "policy_no": "CXS-UMB-220871-25",
         "effective": "12/01/2025", "expiration": "12/01/2026", "premium": "9880"},
        {"line": "Commercial General Liability", "carrier": "Old Hickory Mutual Insurance Company",
         "policy_no": "OHM-GL-4471902-24", "premium": "$38,420"}]}}
    f125 = _acord("125.pdf", "ACORD_125", {"prior_coverage_by_line": [
        {"carrier": "Cardinal Excess Insurance Company", "policy_no": "CXS-UMB-220871-25", "premium": "9,880",
         "effective": "12/01/2025", "expiration": "12/01/2026"},
        {"line": "General Liability", "carrier": "Old Hickory Mutual Insurance Company",
         "policy_no": "OHM-GL-4471902-24", "premium": "38,420"},
        {"line": "General Liability", "carrier": "Old Hickory Mutual Insurance Company",
         "policy_no": "OHM-GL-4471902-23", "premium": "33,005"}]})
    view, _ = merge_rules.fold_acord_lists([f125, dec], dec)
    rows = _rows(view, "prior_coverage_by_line")
    assert len(rows) == 3                                      # the 2023 term is its own policy


def test_the_131s_underlying_rows_fold_into_the_schedule():
    dec = {"filename": "umb.pdf", "doc_type": "dec_page", "facts": {"underlying_policies": [
        {"line": "Commercial General Liability", "carrier": "EMC Property & Casualty Company", "policy_no": "BBC7263"},
        {"line": "Commercial Auto Liability", "carrier": "EMPLOYERS MUTUAL CASUALTY COMPANY", "policy_no": "6E74002"}]}}
    f131 = _acord("131.pdf", "ACORD_131", {"underlying_policies": [
        {"line": "General Liability", "carrier": "EMC Property & Casualty Company", "policy_no": "BBC7263 - 26"},
        {"line": "Automobile Liability", "carrier": "EMPLOYERS MUTUAL CASUALTY COMPANY", "policy_no": "6E7-40-02---26"}]})
    view, _ = merge_rules.fold_acord_lists([f131, dec], dec)
    assert len(_rows(view, "underlying_policies")) == 2          # was 4


def test_the_same_form_uploaded_twice_lists_its_fleet_once():
    vans = [{"year": "2014", "make": "CHEVROLET", "model": "EXPRESS", "vehicle_number": "1"},
            {"year": "2014", "make": "CHEVROLET", "model": "EXPRESS", "vehicle_number": "2"}]
    a = _acord("127.pdf", "ACORD_127", {"auto_vin_schedule": copy.deepcopy(vans)})
    b = _acord("127 (1).pdf", "ACORD_127", {"auto_vin_schedule": copy.deepcopy(vans)})
    view, _ = merge_rules.fold_acord_lists([a, b], a)
    assert len(_rows(view, "auto_vin_schedule")) == 2           # was 4
    twins = [dict(vans[0]), dict(vans[0])]                      # two identical vans on ONE form
    view, _ = merge_rules.fold_acord_lists([_acord("x.pdf", "ACORD_127", {"auto_vin_schedule": twins}),
                                            _acord("y.pdf", "ACORD_127", {"auto_vin_schedule": copy.deepcopy(twins)})],
                                           None)
    assert len(_rows(view, "auto_vin_schedule")) == 2


# ── 6. One set of forms never vouches for itself ─────────────────────────────
def test_another_insureds_forms_set_restores_nothing_beside_this_insureds_decs():
    """Choice Electric's forms (with their ACORD 28) beside ORBIN's declarations:
    the certificate was the "other document" naming Choice Electric, so the 125
    restored 23 Choice Electric answers and took the applicant's identity."""
    restored = {"answers": {"total_revenue": {"value": "$5,000,000", "source": "producer"}},
                "tables": {}, "stores": {}, "flags": {"is_contractor": True}}
    app = {"filename": "ACORD_125.pdf", "doc_type": "application",
           "facts": {"applicant_name": {"value": "Choice Electric LLC", "source": "acord_form"}},
           "acord": {"forms": [{"form_id": "ACORD_125"}], "restored": restored}}
    cert = {"filename": "ACORD_28.pdf", "doc_type": "certificate",
            "facts": {"applicant_name": {"value": "Choice Electric LLC", "source": "acord_form"}},
            "acord": {"forms": [{"form_id": "ACORD_28"}]}}
    dec = {"filename": "orbin.pdf", "doc_type": "dec_page",
           "facts": {"applicant_name": {"value": "ORBIN CONTRACTING LLC", "source": "ai"}}}
    assert merge_rules.restoring_docs([app, cert, dec]) == []
    merged = {"applicant_name": dec["facts"]["applicant_name"]}
    merge_rules.apply_owner_rules(merged, [app, cert, dec])
    assert merged["applicant_name"]["value"] == "ORBIN CONTRACTING LLC" and "total_revenue" not in merged
    flags = {}
    merge_rules.apply_restored_flags(flags, [app, cert, dec])
    assert flags == {}
    # forms only (nobody else names an insured): the set speaks for the package
    assert merge_rules.restoring_docs([app, cert]) == [app]


def test_the_loss_runs_never_verify_themselves_through_two_round_trips():
    from services.acord_intake import primble_record as R
    second = {"facts": {"fein": {"value": "47-2918364", "source": "acord_form"}},
              "docs": [{"doc_type": "loss_run", "facts": {"fein": {"value": "47-2918364"}}},
                       {"doc_type": "application", "facts": {"fein": {"value": "47-2918364", "source": "acord_form",
                                                                      "echo_of": "loss_run"}}}]}
    assert R._loss_run_only_facts(second) == {"fein": "47-2918364"}


# ── 7. A flattened form never reads its hidden overflow text as values ──────
def test_hidden_overflow_text_on_a_flattened_form_is_never_a_value(tmp_path):
    """CH125's flattened 125: the remarks box's 26 warranty claims ran on,
    clipped and invisible, over the loss history and prior-carrier rows - read
    as "d0e8c/k0 9o/v2e0n2 5- ig" occurrence dates and claim text carriers."""
    fitz = pytest.importorskip("fitz")
    long_remark = " ".join(f"{i:02d}/14/2025 W-25{i:02d} Products Warranty claim - Gallatin Pike Diner - "
                           f"Lombardi DP-120 deck oven - igniter; $1,{i:03d} paid;" for i in range(1, 27))
    vals = dict(V125, CommercialPolicy_RemarkText_A=long_remark,
                LossHistory_OccurrenceDate_A="08/09/2025", LossHistory_LineOfBusiness_A="Auto",
                LossHistory_ClaimDate_A="08/11/2025", LossHistory_PaidAmount_A="$5,950",
                LossHistory_OccurrenceDate_B="07/22/2023", LossHistory_LineOfBusiness_B="Property",
                PriorCoverage_Automobile_InsurerFullName_A="Old Hickory Mutual Insurance Company",
                PriorCoverage_Automobile_EffectiveDate_A="12/01/2025")
    src = tmp_path / "f.pdf"
    src.write_bytes(fill_pdf(os.path.join(TPL, "ACORD_125.pdf"), vals))
    dst = str(tmp_path / "flat.pdf")
    d = fitz.open(str(src))
    d.bake()
    d.save(dst)
    d.close()
    exact = {}
    for c in read.read_acord(str(src)).forms:
        exact.update(c["boxes"])
    flat = {}
    for c in read.read_acord(dst).forms:
        flat.update(c["boxes"])
    wrong = {b: v for b, v in flat.items()
             if b.startswith(("LossHistory_", "PriorCoverage_"))
             and " ".join(str(v).split()) != " ".join(str(exact.get(b) or "").split())
             and not (str(v) == "ticked" and exact.get(b))}
    assert wrong == {}


# --- Live CH125 forms + decs (28 Oct): our form's echo of the dec's earlier reading
# disagreed with a fresh reading of the same dec - three Data Consistency cards.
def test_a_form_echo_of_the_documents_is_no_data_consistency_witness():
    from services.acord_intake import primble_record as PR
    from services.underwriting_consistency import assess_underwriting_consistency
    record = {"applicant": "Acme Hearth LLC", "document_read": {"gl_medical_expense": "$5,000"}}
    box = {"applicant_name": {"value": "Acme Hearth LLC", "source": "acord_form"},
           "gl_medical_expense": {"value": "5,000", "source": "acord_form", "box": "GeneralLiability_MedicalExpense_A"}}
    PR.apply(record, box)
    assert box["gl_medical_expense"].get("echo_of") == "documents"
    dec = {"doc_id": "d1", "filename": "dec.pdf", "doc_type": "declarations",
           "facts": {"applicant_name": {"value": "Acme Hearth LLC"}, "gl_medical_expense": {"value": "$10,000"}}}
    form = {"doc_id": "f1", "filename": "ACORD_126.pdf", "doc_type": "acord_form", "facts": box}
    out = assess_underwriting_consistency([dec, form], {"gl_medical_expense": {"value": "$10,000"}})
    row = next((f for f in out.get("fields") or [] if f.get("fact_key") == "gl_medical_expense"), None)
    assert not row or not row.get("review_required"), row
    # forms only: the echo is the one witness and still speaks
    out2 = assess_underwriting_consistency([form], {"gl_medical_expense": {"value": "5,000"}})
    row2 = next((f for f in out2.get("fields") or [] if f.get("fact_key") == "gl_medical_expense"), None)
    assert not row2 or not row2.get("review_required")


def test_a_box_changed_after_download_is_the_forms_own_word():
    from services.acord_intake import primble_record as PR
    record = {"applicant": "Acme Hearth LLC", "document_read": {"gl_medical_expense": "$5,000"}}
    box = {"applicant_name": {"value": "Acme Hearth LLC", "source": "acord_form"},
           "gl_medical_expense": {"value": "25,000", "source": "acord_form"}}
    PR.apply(record, box)
    assert not box["gl_medical_expense"].get("echo_of")


def test_a_person_answer_is_never_listed_as_a_document_reading():
    from services.acord_intake.primble_record import _document_read_facts
    got = _document_read_facts({"gl_medical_expense": {"value": "$5,000", "source": "ai"},
                                "total_revenue": {"value": "$900,000", "source": "producer", "confidence": "producer"},
                                "coverage_lines": {"value": [{"lob": "GL"}]}, "_private": "x"})
    assert got == {"gl_medical_expense": "$5,000"}
