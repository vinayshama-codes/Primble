"""Keep everything Transcriber reads (29 Oct 2026, ASG_TRANSCRIBER.md "Keep
everything"): every returned box is kept ENCRYPTED on the document; a form
outside our 17 maps through ACORD's shared field dictionary (a box name every
known form gives the same meaning) and refuses a disagreeing / scope-sensitive
name; the rest is shown, owner-only, as "read from the form" and never becomes a
fact. Stub only - never the network."""
import asyncio
import json
import os

import pytest
from fastapi import HTTPException

from services import asg_transcriber as T
from services.acord_intake import reverse_map as R
from services.acord_intake import transcriber_intake as TI
from services.acord_intake.read import boxes_to_facts, relabel_transcriber_facts

STUB = os.path.join(os.path.dirname(__file__), "fixtures", "transcriber_stub")
PLAIN = ("Cumberland Hearth", "62-3418806", "423440")       # values off the probe's insured


@pytest.fixture(autouse=True)
def _offline(monkeypatch):
    def refuse(*_a, **_k):
        raise AssertionError("no network call in these tests")
    import httpx
    from cryptography.fernet import Fernet
    from utils import crypto
    monkeypatch.setattr(httpx.AsyncClient, "send", refuse)
    monkeypatch.setattr(httpx.Client, "send", refuse)
    monkeypatch.setenv("TRANSCRIBER_STUB_DIR", STUB)
    monkeypatch.setenv("FIELD_ENCRYPTION_KEY", Fernet.generate_key().decode())
    monkeypatch.setattr(crypto, "_fernet", None)
    TI.reset_client()
    tok = TI._PACKAGE_BUDGET.set(None)
    yield
    TI._PACKAGE_BUDGET.reset(tok)
    TI.reset_client()


def _probe(form_number: str = "807") -> T.TranscriberResult:
    """The real UAT reply (our flattened CH125 ACORD 125) as if it were a form we
    hold no schema / map for."""
    with open(os.path.join(STUB, "real_125_probe.json"), encoding="utf-8") as fh:
        res = T.parse_poll_reply(json.dumps(json.load(fh)), {})
    for f in res.forms:
        f.form_number = form_number
        f.form_name = f"ACORD {form_number} {f.edition}"
    return res


def _group(n=5):
    return TI.SendGroup(pages=list(range(n)), acord_numbers=["807"] * n, kinds=["scanned"] * n, data=b"x", hash="h")


def _facts(copies):
    facts, carried = boxes_to_facts(copies)
    relabel_transcriber_facts(facts, copies)
    return facts, carried


# ── 1. keep everything, encrypted ─────────────────────────────────────────────
def test_an_unknown_form_reply_keeps_every_box_encrypted_and_no_plaintext_on_the_document():
    res, g = _probe(), _group()
    copies = TI.copies_from(g, res)
    assert copies and copies[0]["form_id"] == "ACORD_807"
    entry = TI.record_entry(g, TI.GroupResult(group=g, result=res), copies)
    sealed = entry[TI.ELABELS_KEY]
    assert isinstance(sealed, str) and sealed.startswith("enc:")
    dumped = json.dumps(entry)
    for v in PLAIN:
        assert v not in dumped                                  # never plaintext on the session row
    data = TI.read_elabels({"acord": {"transcriber": entry}})
    kept = data["forms"][0]
    assert kept["form_number"] == "807" and kept["edition"] == res.forms[0].edition
    # every box returned - empty, unticked and unmapped ones too
    assert {b["name"] for b in kept["boxes"]} == set(res.forms[0].boxes)
    box = next(b for b in kept["boxes"] if b["name"] == "NamedInsured_MailingAddress_LineOne_A")
    assert box["value"].startswith("Cumberland Hearth") and box["confidence"] is not None and box["page"] == 1


def test_our_own_forms_are_kept_too_and_nothing_is_kept_without_a_key(monkeypatch):
    res, g = _probe("125"), _group()
    entry = TI.record_entry(g, TI.GroupResult(group=g, result=res), TI.copies_from(g, res))
    assert TI.read_elabels({"acord": {"transcriber": entry}})["forms"][0]["form_id"] == "ACORD_125"
    from utils import crypto
    monkeypatch.delenv("FIELD_ENCRYPTION_KEY")
    monkeypatch.setattr(crypto, "_fernet", None)
    entry2 = TI.record_entry(g, TI.GroupResult(group=g, result=res), TI.copies_from(g, res))
    assert TI.ELABELS_KEY not in entry2 and "Cumberland" not in json.dumps(entry2)
    # a plaintext value planted under the key is never read back
    assert TI.read_elabels({"acord": {"transcriber": {TI.ELABELS_KEY: json.dumps({"forms": []})}}}) is None


# ── 2. ACORD's shared field dictionary ────────────────────────────────────────
def test_an_agreed_name_maps_and_scope_sensitive_names_do_not():
    assert R.shared_entry("NamedInsured_FullName_A")["status"] == "agreed"
    assert R.box_targets("ACORD_807", "NamedInsured_FullName_A") == [
        {"t": "fact", "fact": "applicant_name", "part": "whole"}]
    assert R.box_targets("ACORD_807", "NamedInsured_TaxIdentifier_A")[0]["fact"] == "fein"
    # a policy-line record / the 125's proposed carrier / a certificate's coverage row
    for name in ("Policy_EffectiveDate_A", "AdditionalInterest_FullName_A"):
        assert R.shared_entry(name)["status"] == "scope" and R.shared_targets(name) == []
    # a row of one form's own schedule
    e = R.shared_entry("BuildingOccupancy_OccupiedArea_A")
    assert e["status"] == "single_form_schedule" and e["targets"] == []
    # a name none of our forms prints
    assert R.shared_entry("DirectorsAndOfficers_RequestedPerClaimLimitAmount_A")["status"] == "unknown"
    assert R.box_targets("ACORD_807", "DirectorsAndOfficers_RequestedPerClaimLimitAmount_A") == []


def test_a_name_two_known_forms_read_differently_is_refused(monkeypatch):
    from services.acord_intake import recognize as RC
    names = dict(RC.schema_names())
    names = {**names, "ACORD_125": set(names["ACORD_125"]) | {"Shared_Thing_A"},
             "ACORD_126": set(names["ACORD_126"]) | {"Shared_Thing_A"}}
    monkeypatch.setattr(RC, "schema_names", lambda: names)
    real = R.box_targets

    def fake(fid, box):
        if box == "Shared_Thing_A":
            return [{"t": "fact", "fact": "total_revenue" if fid == "ACORD_125" else "gl_aggregate", "part": "whole"}]
        return real(fid, box)
    monkeypatch.setattr(R, "box_targets", fake)
    e = R._entry_for("Shared_Thing_A", names)
    assert e["status"] == "disagree" and e["targets"] == [] and e["forms"] == ["ACORD_125", "ACORD_126"]


def test_our_17_forms_never_use_the_shared_dictionary(monkeypatch):
    from services.acord_intake.recognize import schema_names

    def boom(_box):
        raise AssertionError("a known form consulted the shared dictionary")
    monkeypatch.setattr(R, "shared_targets", boom)
    for fid, names in schema_names().items():
        assert R.is_known_form(fid)
        for box in sorted(names):
            assert R.learned_targets(fid, box) == R.targets(fid, box)
            R.box_targets(fid, box)                           # never reaches `boom`
    assert R.is_known_form("ACORD_131__excess") and not R.is_known_form("ACORD_807")


def test_the_real_probe_as_an_unknown_form_maps_far_more_than_before(monkeypatch):
    """Measured on the UAT probe read as an unknown form number (29 Oct 2026):
    before 8 facts (only the structural layers), after 24 - the true 125 gives 25
    (its header's per-line policy record is scope-sensitive, never guessed)."""
    res, g = _probe(), _group()
    copies = TI.copies_from(g, res)
    with monkeypatch.context() as m:
        m.setattr(R, "shared_targets", lambda _box: [])
        before, _ = _facts(copies)
    after, _carried = _facts(copies)
    # 21, not 24, since the expert review (29 Oct 2026): a form outside our 17
    # never states the PACKAGE proposed term or additional named insureds
    # (an 807's D&O term / signer) - test_expert_review_29oct.py.
    # 19 since Michelle's second review (30 Oct 2026): an outside form's remarks
    # and payment method are its own line's, never the submission's
    # (`reverse_map.OUTSIDE_LINE_SCOPED_FACTS`) - test_michelle_review2_30oct.py.
    assert len(before) <= 10 and len(after) >= 19 and set(before) <= set(after)
    assert "additional_remarks_text" not in after and "payment_method" not in after
    assert "effective_date" not in after and "expiration_date" not in after
    for key in ("applicant_name", "fein", "naics_code", "sic_code", "mailing_address", "operations_description",
                "producer_contact_name", "entity_type"):
        assert key in after and key not in before, key
    assert after["applicant_name"]["value"] == "Cumberland Hearth & Hospitality Supply, Inc."
    assert after["applicant_name"]["confidence"] == "acord_transcriber"        # please verify
    assert "coverage_lines" not in after                                        # scope-sensitive header: not guessed


# ── 3. nothing unmapped reaches the facts ─────────────────────────────────────
def test_unmapped_boxes_never_change_a_fact():
    res, g = _probe(), _group()
    base, _ = _facts(TI.copies_from(g, res))
    changed = 0
    for name, box in res.forms[0].boxes.items():
        if TI._NAME_SPLIT_RE.match(name):
            continue        # a combined name-and-address block gives its first line to the FullName box
        if box.value and not [t for t in R.box_targets("ACORD_807", name) if t.get("t") != "carry"]:
            box.value = "PLANTED VALUE 999"
            changed += 1
    assert changed >= 50
    again, _ = _facts(TI.copies_from(g, res))
    assert again == base
    assert "PLANTED VALUE 999" not in json.dumps(again)


# ── 4. the owner-checked read route ───────────────────────────────────────────
def _doc_for(res, g):
    copies = TI.copies_from(g, res)
    facts, _ = _facts(copies)          # a real document carries its reading's facts
    return {"doc_id": "d1", "filename": "dno_807.pdf", "facts": facts,
            "acord": {"transcriber": TI.record_entry(g, TI.GroupResult(group=g, result=res), copies)}}


def test_the_route_returns_both_groups_to_the_owner_only(monkeypatch):
    from routes import session_documents_routes as SDR
    doc = _doc_for(_probe(), _group())

    async def fake_session(_sid):
        return {"user_id": "owner-1", "docs": [doc]}
    monkeypatch.setattr(SDR, "get_processing_session", fake_session)
    resp = asyncio.run(SDR.document_form_values("s1", "d1", current_user={"id": "owner-1"}))
    body = json.loads(resp.body)
    used = {r["box"]: r for r in body["used"]}
    read = {r["box"]: r for r in body["read"]}
    assert used["NamedInsured_FullName_A"]["value"] == "Cumberland Hearth & Hospitality Supply, Inc."
    assert used["NamedInsured_FullName_A"]["used_for"] == "applicant_name"
    assert used["NamedInsured_FullName_A"]["via"] == "shared_dictionary"
    assert used["NamedInsured_FullName_A"]["label"] == "Named Insured - Full Name (A)"
    assert read and not set(used) & set(read)
    assert all(r["label"] and "—" not in r["label"] for r in body["used"] + body["read"])
    assert body["forms"][0]["form_number"] == "807" and body["forms"][0]["known_form"] is False
    assert body["unticked"] > 0
    with pytest.raises(HTTPException) as ex:
        asyncio.run(SDR.document_form_values("s1", "d1", current_user={"id": "someone-else"}))
    assert ex.value.status_code == 403
    with pytest.raises(HTTPException) as ex:
        asyncio.run(SDR.document_form_values("s1", "nope", current_user={"id": "owner-1"}))
    assert ex.value.status_code == 404


def test_the_documents_list_offers_the_link_only_when_values_are_kept():
    from routes.form_routes import _reader_fields
    doc = _doc_for(_probe(), _group())
    assert _reader_fields(doc)["reader_values"] is True
    doc["acord"]["transcriber"].pop(TI.ELABELS_KEY)
    assert _reader_fields(doc)["reader_values"] is False
    assert _reader_fields({"acord": {"forms": []}}) == {}


def test_readable_labels():
    assert TI.readable_label("DirectorsAndOfficers_RequestedPerClaimLimitAmount_A") == \
        "Directors And Officers - Requested Per Claim Limit Amount (A)"
    assert TI.readable_label("Insurer_NAICCode_B") == "Insurer - NAIC Code (B)"
    assert TI.readable_label("Policy_EffectiveDate") == "Policy - Effective Date"


# ── 5. the whole path: an outside D&O form through the pipeline door ──────────
def test_extract_document_reads_an_unknown_form_and_keeps_everything(tmp_path, monkeypatch):
    import pikepdf
    from services import extraction_pipeline as EP
    stub = tmp_path / "stub"
    stub.mkdir()
    (stub / "default.json").write_text(json.dumps(_probe().to_json()))
    monkeypatch.setenv("TRANSCRIBER_STUB_DIR", str(stub))
    pdf = tmp_path / "dno_807.pdf"
    p = pikepdf.new()
    for _ in range(5):
        p.add_blank_page(page_size=(612, 792))
    p.save(str(pdf))
    text = "\n".join(f"[Document page {i}]\nscanned words of a directors and officers application "
                     f"ACORD 807 (2025/03) Page {i} of 5" for i in range(1, 6))

    async def fake_text(_path):
        return text, []

    async def fake_llm(_text, _dtype, **_kw):
        return {"facts": {}, "flags": {}}
    monkeypatch.setattr(EP, "extract_text", fake_text)
    monkeypatch.setattr(EP, "extract_facts_long", fake_llm)
    monkeypatch.setenv("TRANSCRIBER", "1")
    TI.reset_client()
    doc = asyncio.run(EP.extract_document(str(pdf), "dno_807.pdf", "user-1"))
    assert doc and doc["facts"]["applicant_name"]["value"] == "Cumberland Hearth & Hospitality Supply, Inc."
    assert doc["facts"]["applicant_name"]["confidence"] == "acord_transcriber"
    tr = doc["acord"]["transcriber"]
    assert tr[TI.ELABELS_KEY].startswith("enc:")
    acord_dump = json.dumps(doc["acord"])
    for v in PLAIN:
        assert v not in acord_dump                     # carried too: an unknown form is never regenerated
    assert all(k.split("#")[0] != "ACORD_807" for k in doc["acord"].get("carried") or {})
    values = TI.form_values(doc)
    assert values["used"] and values["read"]
    read_values = {r["value"] for r in values["read"]}
    for k, v in doc["facts"].items():
        fv = v.get("value") if isinstance(v, dict) else None
        if isinstance(fv, str) and len(fv) > 3:
            assert fv not in read_values or any(u["value"] == fv for u in values["used"]), k


def test_the_shared_dictionary_is_built_once_and_matches_the_per_name_verdicts(monkeypatch):
    from services.acord_intake.recognize import schema_names
    names = schema_names()
    n = R.build_shared_dictionary()
    assert R._SHARED_BUILT["done"] and n == len(set().union(*names.values()))
    for box in ("NamedInsured_FullName_A", "Policy_EffectiveDate_A", "BuildingOccupancy_OccupiedArea_A",
                "BusinessInformation_AnnualGrossReceiptsAmount_A", "Producer_FullName_A"):
        assert R.shared_entry(box) == R._entry_for(box, names)
    # built: a lookup never computes again
    monkeypatch.setattr(R, "_entry_for", lambda *_a: (_ for _ in ()).throw(AssertionError("rebuilt")))
    assert R.shared_entry("NamedInsured_FullName_A")["status"] == "agreed"
    assert R.shared_entry("DirectorsAndOfficers_RequestedPerClaimLimitAmount_A")["status"] == "unknown"


def test_unknown_forms_never_carry_plaintext_but_our_forms_still_do():
    from services.acord_intake.intake import _regenerable_only
    carried = {"ACORD_125": {"X_A": "v"}, "ACORD_125#2": {"X_A": "w"}, "ACORD_807": {"Y_A": "secret"},
               "ACORD_807#2": {"Y_A": "secret"}, "ACORD_131__excess": {"Z_A": "z"}}
    assert set(_regenerable_only(carried)) == {"ACORD_125", "ACORD_125#2", "ACORD_131__excess"}
    assert _regenerable_only(None) == {}
