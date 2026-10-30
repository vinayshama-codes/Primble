"""Production fuzz of the ACORD reading / merging path (29 Oct 2026, ACORD_INTAKE.md
"Production fuzz"). Seeded and fast; the wider sweep lives in the scratchpad.
No network, no model, no ASG call."""
import io
import json
import os
import random

import pytest

from services.acord_intake import carry, intake, merge_rules, read
from services.pdf_service import fill_pdf

BACKEND = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TPL = os.path.join(BACKEND, "templates")

ALPHA = {"NamedInsured_FullName_A": "Alpha Roofing LLC", "NamedInsured_MailingAddress_LineOne_A": "1 Alpha St",
         "NamedInsured_MailingAddress_CityName_A": "Denver", "NamedInsured_MailingAddress_StateOrProvinceCode_A": "CO",
         "NamedInsured_MailingAddress_PostalCode_A": "80202", "Policy_EffectiveDate_A": "12/01/2026"}
BETA = {"NamedInsured_FullName_A": "Beta Bakery Inc", "NamedInsured_TaxIdentifier_A": "84-3317790",
        "NamedInsured_MailingAddress_LineOne_A": "9 Beta Rd", "NamedInsured_MailingAddress_CityName_A": "Austin",
        "NamedInsured_MailingAddress_StateOrProvinceCode_A": "TX", "NamedInsured_MailingAddress_PostalCode_A": "73301",
        "Policy_EffectiveDate_A": "03/01/2027", "Policy_ExpirationDate_A": "03/01/2028",
        "NamedInsured_LegalEntity_CorporationIndicator_A": "Yes"}


def _bound(tmp_path, *value_sets, form_id="ACORD_125", name="bound.pdf"):
    pikepdf = pytest.importorskip("pikepdf")
    out = pikepdf.new()
    keep = []
    for v in value_sets:
        src = pikepdf.open(io.BytesIO(fill_pdf(os.path.join(TPL, f"{form_id}.pdf"), v)))
        keep.append(src)
        out.pages.extend(src.pages)
    p = tmp_path / name
    out.save(str(p))
    return str(p)


def _values(facts):
    return {k: (v.get("value") if isinstance(v, dict) else v) for k, v in facts.items()}


def _text(path):
    fitz = pytest.importorskip("fitz")
    d = fitz.open(path)
    t = "\n".join(f"[Document page {i + 1}]\n{pg.get_text()}" for i, pg in enumerate(d))
    d.close()
    return t


# ── 1. Two insureds' applications bound into one PDF ─────────────────────────
def test_two_insureds_in_one_pdf_never_make_one_frankenstein_application(tmp_path):
    p = _bound(tmp_path, ALPHA, BETA)
    r = read.read_acord(p)
    f = _values(r.facts)
    assert f["applicant_name"] == "Alpha Roofing LLC"
    assert f["mailing_address"] == "1 Alpha St, Denver, CO 80202"
    # nothing of Beta's is read into Alpha's application
    for k in ("fein", "entity_type", "expiration_date"):
        assert k not in f, k
    assert f["effective_date"] == "12/01/2026"
    assert r.other_insured_pages == [5, 6, 7, 8, 9]
    acord = intake.read_for_document(p, _text(p))
    assert acord["classification"]["confidence"] == "low"                # Needs Verification
    reasons = {e["reason"] for e in acord["record"]["needs_verification"]}
    assert "names another insured than this document's first form" in reasons
    assert "Beta" not in acord["other_text"]                              # nor read by the model


def test_two_copies_of_one_insured_that_disagree_give_no_reading(tmp_path):
    a = dict(ALPHA)
    b = dict(ALPHA, NamedInsured_FullName_A="ALPHA ROOFING, L.L.C.", Policy_EffectiveDate_A="01/15/2027",
             NamedInsured_TaxIdentifier_A="84-1111111")
    r = read.read_acord(_bound(tmp_path, a, b))
    f = _values(r.facts)
    assert f["applicant_name"] == "Alpha Roofing LLC"                     # same company: kept
    assert "effective_date" not in f                                      # two terms: blank over wrong
    assert f["fein"] == "84-1111111"                                      # stated once, same insured
    assert r.other_insured_pages == []


def test_an_address_is_never_one_copys_street_with_anothers_city():
    def copy(n, boxes):
        return {"form_id": "ACORD_125", "copy": n, "pages": [n - 1], "kind": "fillable", "edition": "",
                "boxes": boxes, "kinds": {b: "text" for b in boxes}, "box_page": {b: n - 1 for b in boxes}}
    c1 = copy(1, {"NamedInsured_FullName_A": "Alpha Roofing LLC", "NamedInsured_MailingAddress_LineOne_A": "1 Alpha St",
                  "NamedInsured_MailingAddress_CityName_A": "Denver",
                  "NamedInsured_MailingAddress_StateOrProvinceCode_A": "CO",
                  "NamedInsured_MailingAddress_PostalCode_A": "80202"})
    c2 = copy(2, {"NamedInsured_FullName_A": "Alpha Roofing LLC", "NamedInsured_MailingAddress_LineOne_A": "77 Other Ave",
                  "NamedInsured_MailingAddress_CityName_A": "Boulder",
                  "NamedInsured_MailingAddress_StateOrProvinceCode_A": "CO",
                  "NamedInsured_MailingAddress_PostalCode_A": "80304"})
    facts, _ = read.boxes_to_facts([c1, c2])
    assert "mailing_address" not in facts
    same = copy(2, dict(c1["boxes"]))
    facts, _ = read.boxes_to_facts([c1, same])
    assert _values(facts)["mailing_address"].startswith("1 Alpha St")


# ── 2. Transcriber readings are labelled, in a mixed document too ────────────
def _t_copy(boxes, kinds=None, n=1, pages=(3,)):
    return {"form_id": "ACORD_125", "copy": n, "pages": list(pages), "kind": "transcriber", "edition": "",
            "boxes": boxes, "kinds": kinds or {b: "text" for b in boxes},
            "box_page": {b: pages[0] for b in boxes}, "raw": {}, "confidence": {b: 90 for b in boxes}}


def test_a_transcriber_tick_in_a_mixed_document_is_never_exact():
    exact = {"form_id": "ACORD_126", "copy": 1, "pages": [7], "kind": "fillable", "edition": "",
             "boxes": {"Producer_FullName_A": "Astrea"}, "kinds": {"Producer_FullName_A": "text"},
             "box_page": {"Producer_FullName_A": 7}, "raw": {}}
    t = _t_copy({"NamedInsured_FullName_A": "Alpha Roofing LLC",
                 "NamedInsured_LegalEntity_LimitedLiabilityCorporationIndicator_A": "Yes"},
                kinds={"NamedInsured_FullName_A": "text",
                       "NamedInsured_LegalEntity_LimitedLiabilityCorporationIndicator_A": "check"})
    facts, _ = read.boxes_to_facts([exact, t])
    read.relabel_transcriber_facts(facts, [exact, t])
    assert facts["entity_type"]["confidence"] == read.TRANSCRIBER_CONFIDENCE
    assert facts["applicant_name"]["confidence"] == read.TRANSCRIBER_CONFIDENCE


def test_a_box_transcriber_carried_prints_please_verify_never_filled():
    box = "CommercialPolicy_Question_AAICode_A"
    docs = [{"filename": "scan.pdf", "acord": {"forms": [{"form_id": "ACORD_125"}],
                                              "carried": {"ACORD_125": {box: "N"}},
                                              "carried_transcriber": {"ACORD_125": [box]}}}]
    mapped, conf = {}, {}
    assert carry.apply_carried(mapped, conf, docs, "ACORD_125") == [box]
    assert mapped[box] == "N" and conf[box] == "ai_verified"
    # an exact box read of another upload stating it makes it that form's statement
    docs.append({"filename": "fill.pdf", "acord": {"forms": [{"form_id": "ACORD_125"}],
                                                   "carried": {"ACORD_125": {box: "N"}}}})
    mapped, conf = {}, {}
    carry.apply_carried(mapped, conf, docs, "ACORD_125")
    assert conf[box] == {"label": "filled", "source": "acord_form"}


def test_transcriber_carried_is_computed_per_copy():
    t = _t_copy({"CommercialPolicy_Question_AAICode_A": "N", "NamedInsured_FullName_A": "Alpha Roofing LLC"})
    facts, carried = read.boxes_to_facts([t])
    assert read.transcriber_carried([t], carried) == {"ACORD_125": ["CommercialPolicy_Question_AAICode_A"]}


def test_a_second_transcriber_copy_of_another_insured_is_set_aside():
    a = _t_copy({"NamedInsured_FullName_A": "Alpha Roofing LLC", "Policy_EffectiveDate_A": "12/01/2026"}, n=1, pages=(0,))
    b = _t_copy({"NamedInsured_FullName_A": "Beta Bakery Inc", "NamedInsured_TaxIdentifier_A": "84-3317790"},
                n=2, pages=(1,))
    kept, aside = read._one_insured([a, b])
    assert kept == [a] and aside == [1]


# ── 3. Seeded property fuzz of the fold (no duplicate, no lost row) ──────────
def _rand_vin(rng):
    return "1GC" + "".join(rng.choice("ABCDEFGHJKLMNPRSTUVWXYZ0123456789") for _ in range(14))


@pytest.mark.parametrize("seed", range(3))
def test_vehicles_claims_and_drivers_fold_to_the_union(seed):
    rng = random.Random(seed)
    for _ in range(150):
        n = rng.randint(1, 5)
        vins = [_rand_vin(rng) for _ in range(n)]
        claims = [(f"CL{rng.randint(10000, 99999)}", rng.randint(1, 12), rng.randint(1, 28), rng.randint(2019, 2025),
                   rng.randint(1, 500) * 100) for _ in range(n)]
        docs_v, docs_c, covered = [], [], set()
        for _d in range(rng.randint(2, 3)):
            sub = [j for j in range(n) if rng.random() < .7] or [0]
            covered |= set(sub)
            docs_v.append([{"vin": rng.choice([vins[j], vins[j].lower(), vins[j][:4] + "-" + vins[j][4:],
                                               " ".join((vins[j][:8], vins[j][8:]))]), "year": "2020"} for j in sub])
            docs_c.append([{"claim_number": claims[j][0],
                            "date": rng.choice([f"{claims[j][1]:02d}/{claims[j][2]:02d}/{claims[j][3]}",
                                                f"{claims[j][1]}/{claims[j][2]}/{claims[j][3]}"]),
                            "paid": rng.choice([f"${claims[j][4]:,}", str(claims[j][4]), f"{claims[j][4]:,}.00"])}
                           for j in sub])
        flags = [False] * len(docs_v)
        flags[0] = True
        assert len(merge_rules.fold_rows("auto_vin_schedule", docs_v, flags)) == len(covered)
        assert len(merge_rules.fold_rows("loss_history", docs_c, flags)) == len(covered)


# ── 4. A random fillable form never crashes the reader ───────────────────────
@pytest.mark.parametrize("form_id,seed", [("ACORD_125", 1), ("ACORD_127", 2), ("ACORD_140", 3)])
def test_random_values_never_crash_the_document_door(tmp_path, form_id, seed):
    rng = random.Random(seed)
    schema = json.load(open(os.path.join(BACKEND, "forms_schemas", f"{form_id}_schema.json")))
    pool = ["", "N/A", "TBD", "$1,000,000", "1e9", "13/45/2026", "00/00/0000", "‮ evil", "株式会社テスト",
            "X" * 2000, "1gcw-gafp4k-1234567", "O'Brien & Sons, Ltd.", "Off", "Yes", "0", "-500", "%s%d"]
    vals = {k: rng.choice(pool) for k in schema if rng.random() < 0.3}
    p = tmp_path / "f.pdf"
    p.write_bytes(fill_pdf(os.path.join(TPL, f"{form_id}.pdf"), {k: v for k, v in vals.items() if v}))
    acord = intake.read_for_document(str(p), _text(str(p)))
    if acord is not None:
        intake.overlay_facts({"facts": {}, "flags": {}}, acord)


@pytest.mark.parametrize("blob", [b"", b"hello", b"%PDF-1.7\n%%EOF", b"%PDF-1.4\n1 0 obj<<>>endobj\ntrailer<<>>\n%%EOF"])
def test_broken_files_fall_back_quietly(tmp_path, blob):
    p = tmp_path / "x.pdf"
    p.write_bytes(blob)
    try:
        r = intake.read_for_document(str(p), "")
    except Exception as ex:                                    # pragma: no cover - the property
        pytest.fail(f"read_for_document raised {ex!r}")
    assert r is None or not r.get("facts")


# ── 5. The proposed term is one application's pair ───────────────────────────
def test_two_applications_never_give_one_start_and_the_others_end():
    def app(name, facts):
        return {"filename": name, "doc_type": "application", "acord": {"forms": [{"form_id": "ACORD_125"}]},
                "facts": {k: {"value": v, "source": "acord_form"} for k, v in facts.items()}}
    docs = [app("draft.pdf", {"applicant_name": "Alpha Roofing LLC", "effective_date": "12/01/2026"}),
            app("rev.pdf", {"applicant_name": "Alpha Roofing LLC", "effective_date": "03/01/2027",
                            "expiration_date": "03/01/2028"})]
    merged = {"expiration_date": {"value": "03/01/2028", "source": "acord_form"}}   # the vote's pick
    merge_rules.apply_owner_rules(merged, docs)
    assert _values(merged).get("effective_date") == "12/01/2026"
    assert "expiration_date" not in merged


def test_a_subcontractors_certificate_bound_first_never_sets_the_application_aside():
    cert = {"form_id": "ACORD_25", "copy": 1, "pages": [0], "kind": "fillable", "edition": "",
            "boxes": {"NamedInsured_FullName_A": "Sub Electric LLC"}, "kinds": {"NamedInsured_FullName_A": "text"},
            "box_page": {"NamedInsured_FullName_A": 0}}
    app = {"form_id": "ACORD_125", "copy": 1, "pages": [1], "kind": "fillable", "edition": "",
           "boxes": {"NamedInsured_FullName_A": "Alpha Roofing LLC"}, "kinds": {"NamedInsured_FullName_A": "text"},
           "box_page": {"NamedInsured_FullName_A": 1}}
    kept, aside = read._one_insured([cert, app])
    assert kept == [app] and aside == [0]
