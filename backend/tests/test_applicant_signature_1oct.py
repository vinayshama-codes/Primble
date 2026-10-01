"""Orbin item 14 (client, 22 Sep: "How is the applicant (not producer) supposed
to sign these forms?"; owner, 1 Oct 2026: built in, the same draw-or-upload pad
the producer uses).

The producer sends the generated forms for signature; the client opens the
link, reads each filled form, confirms, types their name and signs. The
signature goes ONLY on the application's signature lines - read off the printed
form - with the signing date beside each, and only while the form still holds
what the client signed.
"""
import asyncio
import base64
import io
import json
import os
import re
from pathlib import Path

import pikepdf
import pytest
from PIL import Image

import services.applicant_signing as asg
import services.signature_boxes as sb
from config.settings import TEMPLATE_DIR

BACKEND = Path(__file__).resolve().parents[1]
FRONTEND = BACKEND.parent / "frontend" / "src"
ALL_FORMS = sorted(p.name.replace("_schema.json", "") for p in (BACKEND / "forms_schemas").glob("*_schema.json"))


def _schema(fid):
    return json.loads((BACKEND / "forms_schemas" / f"{fid}_schema.json").read_text(encoding="utf-8"))


def _tpl(fid):
    return os.path.join(TEMPLATE_DIR, f"{fid}.pdf")


def _png(w=440, h=140, stroke=True, mode="RGB", bg=(255, 255, 255)):
    im = Image.new(mode, (w, h), bg if mode == "RGB" else (0, 0, 0, 0))
    if stroke:
        for x in range(60, 300):
            for dy in range(3):
                im.putpixel((x, 60 + (x % 20) + dy), (15, 23, 42) if mode == "RGB" else (15, 23, 42, 255))
    out = io.BytesIO()
    im.save(out, format="PNG")
    return "data:image/png;base64," + base64.b64encode(out.getvalue()).decode()


def _jpeg():
    im = Image.new("RGB", (300, 100), (255, 255, 255))
    for x in range(20, 280):
        im.putpixel((x, 50), (0, 0, 0)); im.putpixel((x, 51), (0, 0, 0))
    out = io.BytesIO()
    im.save(out, format="JPEG")
    return "data:image/jpeg;base64," + base64.b64encode(out.getvalue()).decode()


@pytest.fixture
def key(monkeypatch):
    from cryptography.fernet import Fernet
    import utils.crypto as crypto
    monkeypatch.setenv("FIELD_ENCRYPTION_KEY", Fernet.generate_key().decode())
    monkeypatch.setattr(crypto, "_fernet", None)
    yield
    crypto._fernet = None


# ══ 1. Which lines the applicant signs - read off the printed forms ══════════

def test_every_form_has_exactly_its_application_lines():
    lines = {fid: sb.applicant_signature_lines(_tpl(fid)) for fid in ALL_FORMS}
    signed_forms = {f for f, l in lines.items() if l}
    assert signed_forms == {"ACORD_125", "ACORD_126", "ACORD_127", "ACORD_130", "ACORD_131", "ACORD_133",
                            "ACORD_137_CA", "ACORD_137_CO", "ACORD_138_CA", "ACORD_138_CO",
                            "ACORD_140", "ACORD_141", "ACORD_160"}
    for fid in ("ACORD_25", "ACORD_28", "ACORD_101", "ACORD_186"):
        assert lines[fid] == [], fid
    # every line is an applicant SIGNATURE box, every date an applicant DATE box
    for fid, ls in lines.items():
        schema = _schema(fid)
        for line in ls:
            assert sb.signature_box(line["signature"], schema[line["signature"]]["tu"]) == ("signature", "applicant")
            assert line["date"] and sb.signature_box(line["date"], schema[line["date"]]["tu"]) == ("date", "applicant")


def test_acord_130s_minnesota_attestation_is_never_signed():
    # Signature_A sits under "I further attest that I have no employees and an
    # estimated exposure of zero" - same tooltip as the real line, Signature_B.
    assert sb.applicant_signature_lines(_tpl("ACORD_130")) == [
        {"signature": "NamedInsured_Signature_B", "date": "NamedInsured_SignatureDate_A"}]


def test_dates_pair_by_row_not_by_letter():
    lines = {l["signature"]: l["date"] for l in sb.applicant_signature_lines(_tpl("ACORD_137_CA"))}
    assert lines == {"NamedInsured_Signature_A": "NamedInsured_SignatureDate_A",
                     "NamedInsured_Signature_B": "NamedInsured_SignatureDate_B",
                     "NamedInsured_Signature_C": "NamedInsured_SignatureDate_C"}


def test_initials_are_never_a_line():
    for fid in ALL_FORMS:
        for line in sb.applicant_signature_lines(_tpl(fid)):
            assert "Initials" not in line["signature"] and "Initials" not in (line["date"] or "")


def test_an_unreadable_template_has_no_lines(tmp_path):
    bad = tmp_path / "x.pdf"
    bad.write_bytes(b"not a pdf")
    assert sb.applicant_signature_lines(str(bad)) == []
    assert sb.applicant_signature_lines(str(tmp_path / "missing.pdf")) == []


# ══ 2. The form as signed ════════════════════════════════════════════════════

def test_the_fingerprint_ignores_only_what_signing_fills():
    s = _schema("ACORD_125")
    base = {"NamedInsured_FullName_A": "Orbin LLC", "Policy_EffectiveDate_A": "07/15/2026", "Blank_A": ""}
    fp = sb.form_fingerprint(base, s)
    assert fp == sb.form_fingerprint(dict(reversed(list(base.items()))), s)
    for box in ("NamedInsured_Signature_A", "NamedInsured_SignatureDate_A",
                "Producer_AuthorizedRepresentative_Signature_A"):
        assert sb.form_fingerprint({**base, box: "x"}, s) == fp, box
    # initials are a legal choice (credit notice, UM rejection): they count
    assert sb.form_fingerprint({**base, "NamedInsured_Initials_A": "ER"}, s) != fp
    assert sb.form_fingerprint({**base, "Empty_B": "  "}, s) == fp
    assert sb.form_fingerprint({**base, "NamedInsured_FullName_A": "Orbin LLC "}, s) == fp   # trimmed
    assert sb.form_fingerprint({**base, "NamedInsured_FullName_A": "Orbin Inc"}, s) != fp
    assert sb.form_fingerprint({**base, "Policy_ExpirationDate_A": "07/15/2027"}, s) != fp
    assert sb.form_fingerprint(None) == sb.form_fingerprint({})


def test_a_um_rejection_initialled_after_signing_ends_the_signature(key):
    sess = _signed_session("ACORD_137_CO", values={"NamedInsured_FullName_A": "Orbin LLC"})
    assert sb.applicant_signature_for(sess, "ACORD_137_CO") is not None
    sess["generated_forms"]["ACORD_137_CO"]["field_state"]["NamedInsured_Initials_A"] = "ER"
    assert sb.applicant_signature_state(sess["generated_forms"]["ACORD_137_CO"]) == "stale"
    assert sb.applicant_signature_for(sess, "ACORD_137_CO") is None


def test_signed_then_stale():
    gen = {"form": {"template_file": "ACORD_125.pdf"}, "schema": _schema("ACORD_125"),
           "field_state": {"NamedInsured_FullName_A": "Orbin LLC"}}
    assert sb.applicant_signature_state(gen) is None
    gen[sb.APPLICANT_SIGNATURE_KEY] = {"fingerprint": sb.form_fingerprint(gen["field_state"], gen["schema"])}
    assert sb.applicant_signature_state(gen) == "signed"
    gen["field_state"]["NamedInsured_FullName_A"] = "Orbin Contracting LLC"
    assert sb.applicant_signature_state(gen) == "stale"
    for junk in (None, "x", {}, {sb.APPLICANT_SIGNATURE_KEY: "junk"}, {sb.APPLICANT_SIGNATURE_KEY: {}}):
        assert sb.applicant_signature_state(junk) is None


# ══ 3. The picture: checked, trimmed, never trusted ══════════════════════════

def test_a_drawn_signature_is_trimmed_to_its_ink():
    out = asg.normalize_signature_image(_png())
    assert out.startswith("data:image/png;base64,")
    im = Image.open(io.BytesIO(base64.b64decode(out.split(",", 1)[1])))
    assert im.width < 300 and im.height < 60          # 440 x 140 canvas -> the stroke
    assert asg.normalize_signature_image(_jpeg()).startswith("data:image/png;base64,")
    # a transparent pad's PNG flattens onto white and keeps its ink
    assert asg.normalize_signature_image(_png(mode="RGBA"))


@pytest.mark.parametrize("bad, code", [
    (None, "image"), ("", "image"), ("hello", "image"),
    ("data:image/gif;base64,R0lGODlhAQABAAAAACw=", "image"),
    ("data:image/png;base64,!!!notbase64!!!", "image"),
    ("data:image/png;base64," + base64.b64encode(b"GIF89a" + b"\x00" * 50).decode(), "image"),
    ("data:image/png;base64," + base64.b64encode(b"\x89PNG\r\n\x1a\n" + b"\x00" * 50).decode(), "image"),
    ("data:image/svg+xml;base64," + base64.b64encode(b"<svg/>").decode(), "image"),
])
def test_bad_pictures_are_refused(bad, code):
    with pytest.raises(asg.SigningError) as ei:
        asg.normalize_signature_image(bad)
    assert ei.value.code == code and ei.value.status == 422


def test_a_blank_pad_is_refused():
    with pytest.raises(asg.SigningError) as ei:
        asg.normalize_signature_image(_png(stroke=False))
    assert "empty" in ei.value.message


def test_size_limits():
    with pytest.raises(asg.SigningError):
        asg.normalize_signature_image(_png(w=4100, h=10, stroke=False))
    big = "data:image/png;base64," + base64.b64encode(b"\x89PNG\r\n\x1a\n" + b"\x00" * (asg.MAX_IMAGE_BYTES + 10)).decode()
    with pytest.raises(asg.SigningError) as ei:
        asg.normalize_signature_image(big)
    assert "too large" in ei.value.message
    # a wide signature is scaled down, never refused
    wide = asg.normalize_signature_image(_png(w=3000, h=200))
    assert Image.open(io.BytesIO(base64.b64decode(wide.split(",", 1)[1]))).width <= 1600


@pytest.mark.parametrize("raw, ok", [
    ("Erin Royal", "Erin Royal"), ("  Erin   Royal ", "Erin Royal"), ("O'Brien-Smith", "O'Brien-Smith"),
    ("José Núñez", "José Núñez"), ("E", None), ("", None), (None, None), ("12345", None),
    ("<script>", None), ("a" * 101, None), ("Erin {Royal}", None),
])
def test_the_typed_name(raw, ok):
    if ok:
        assert asg.clean_signer_name(raw) == ok
    else:
        with pytest.raises(asg.SigningError):
            asg.clean_signer_name(raw)


def test_the_signing_date_is_the_signers_day():
    from datetime import datetime, timezone
    late_utc = datetime(2026, 10, 2, 3, 30, tzinfo=timezone.utc)         # 8:30 pm 1 Oct in Denver
    assert asg.signing_date(late_utc, -360) == "10/01/2026"
    assert asg.signing_date(late_utc, 0) == "10/02/2026"
    assert asg.signing_date(late_utc, "junk") == "10/02/2026"
    assert asg.signing_date(late_utc, -100000) == asg.signing_date(late_utc, -14 * 60)   # bounded
    assert re.match(r"^\d{2}/\d{2}/\d{4}$", asg.signing_date())


def test_tokens():
    t = asg.new_token()
    assert asg.valid_token(t) and len(t) == 64 and t != asg.new_token()
    for bad in (None, "", "x" * 64, t.upper(), t[:-1], t + "0", "../" + t[3:], 123):
        assert not asg.valid_token(bad)


def test_a_request_is_open_only_while_pending_and_in_date():
    from datetime import datetime, timedelta, timezone
    future = (datetime.now(timezone.utc) + timedelta(days=1)).isoformat()
    past = (datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat()
    assert asg.check_open({"status": "pending", "expires_at": future})
    for row, code, status in ((None, "not_found", 404), ({"status": "signed", "expires_at": future}, "already_signed", 409),
                              ({"status": "replaced", "expires_at": future}, "replaced", 409),
                              ({"status": "pending", "expires_at": past}, "expired", 410),
                              ({"status": "pending", "expires_at": "junk"}, "expired", 410)):
        with pytest.raises(asg.SigningError) as ei:
            asg.check_open(row)
        assert (ei.value.code, ei.value.status) == (code, status)


# ══ 4. Painting it - on the real templates ═══════════════════════════════════

def _gen(fid, values=None, **extra):
    return {"form_id": fid, "form": {"template_file": f"{fid}.pdf"}, "schema": _schema(fid),
            "field_state": dict(values or {"NamedInsured_FullName_A": "Orbin Contracting LLC"}),
            "confidence": {}, **extra}


def _signed_session(fid, key_fixture=None, values=None, **extra):
    from utils.crypto import encrypt_field
    gen = _gen(fid, values, **extra)
    picture = asg.normalize_signature_image(_png())
    gen[sb.APPLICANT_SIGNATURE_KEY] = {"request_id": "r1", "signed_date": "10/01/2026", "signer_name": "Erin Royal",
                                       "fingerprint": sb.form_fingerprint(gen["field_state"], gen["schema"])}
    return {"generated_forms": {fid: gen}, sb.APPLICANT_IMAGES_KEY: {"r1": encrypt_field(picture)}}


def _fields(pdf_bytes):
    pdf = pikepdf.open(io.BytesIO(pdf_bytes))
    out = {}
    for f in sb._walk_fields(pdf.Root.AcroForm.get("/Fields", [])):
        if f.get("/T") is not None:
            out[str(f.get("/T"))] = str(f.get("/V")) if f.get("/V") is not None else None
    images = sum(1 for p in pdf.pages for k in (p.Resources.get("/XObject") or {}).keys() if str(k).startswith("/SigImg"))
    return out, images


@pytest.mark.parametrize("fid", ["ACORD_125", "ACORD_130", "ACORD_131", "ACORD_137_CO"])
def test_the_applicant_lines_are_signed_and_dated_and_nothing_else(fid, key):
    sess = _signed_session(fid)
    pdf = sb.regenerate_pdf_for_form(sess, fid, force=True)
    fields, images = _fields(pdf)
    lines = sb.applicant_signature_lines(_tpl(fid))
    for line in lines:
        assert line["signature"] not in fields, line                 # painted, widget removed
        assert fields.get(line["date"]) == "10/01/2026", line        # dated
    assert images >= len(lines)
    schema = _schema(fid)
    for name, meta in schema.items():
        box = sb.signature_box(name, meta.get("tu", ""), meta.get("ft", ""))
        if box and box[1] == "producer" and box[0] == "signature":
            assert name in fields, name                              # the producer has not signed
        if box and box[0] == "initials":
            assert name in fields and not fields[name], name         # choices stay the applicant's to make
    assert not any(k.startswith("__primble_hold_") for k in fields)
    if fid == "ACORD_130":
        assert "NamedInsured_Signature_A" in fields                  # the Minnesota attestation untouched
    gen = sess["generated_forms"][fid]
    assert gen[sb.APPLICANT_RENDER_KEY].startswith("r1|") and gen["_pdf_cache_hash"]
    assert sb.regenerate_pdf_for_form(sess, fid) is gen["pdf_bytes"]   # cached


def test_both_parties_sign_one_form(key):
    sess = _signed_session("ACORD_125", signature_applied=True, signature_b64=asg.normalize_signature_image(_jpeg()))
    fields, images = _fields(sb.regenerate_pdf_for_form(sess, "ACORD_125", force=True))
    assert "NamedInsured_Signature_A" not in fields
    assert "Producer_AuthorizedRepresentative_Signature_A" not in fields
    assert fields["NamedInsured_SignatureDate_A"] == "10/01/2026"
    assert images >= 2
    assert sess["generated_forms"]["ACORD_125"]["signature_scope"] == sb.SIGNATURE_SCOPE


def test_a_changed_form_loses_the_signature_and_its_cache(key):
    sess = _signed_session("ACORD_125")
    sb.regenerate_pdf_for_form(sess, "ACORD_125", force=True)
    gen = sess["generated_forms"]["ACORD_125"]
    gen["field_state"]["NamedInsured_FullName_A"] = "Someone Else LLC"
    assert sb.applicant_signature_for(sess, "ACORD_125") is None
    fields, _ = _fields(sb.regenerate_pdf_for_form(sess, "ACORD_125"))
    assert "NamedInsured_Signature_A" in fields and not fields.get("NamedInsured_SignatureDate_A")
    assert sb.APPLICANT_RENDER_KEY not in gen


def test_an_unreadable_image_paints_nothing(key):
    sess = _signed_session("ACORD_125")
    sess[sb.APPLICANT_IMAGES_KEY] = {"r1": "enc:garbage"}
    assert sb.applicant_signature_for(sess, "ACORD_125") is None
    sess.pop(sb.APPLICANT_IMAGES_KEY)
    assert sb.applicant_signature_for(sess, "ACORD_125") is None


def test_a_picture_the_painter_cannot_open_leaves_the_pdf_exactly_as_it_was(key):
    from services.pdf_service import fill_pdf
    base = fill_pdf(_tpl("ACORD_125"), {}, {})
    applicant = {"image": "data:image/png;base64,AAAA", "date": "10/01/2026",
                 "lines": sb.applicant_signature_lines(_tpl("ACORD_125"))}
    assert sb.add_applicant_signature(base, _tpl("ACORD_125"), applicant) is base
    assert sb.add_applicant_signature(base, _tpl("ACORD_125"), {"lines": []}) is base


def test_a_form_with_no_line_is_never_painted(key):
    sess = _signed_session("ACORD_25")
    assert sb.applicant_signature_for(sess, "ACORD_25") is None


def test_the_viewer_boxes(key):
    sess = _signed_session("ACORD_130")
    boxes = sb.signed_applicant_boxes(sess, "ACORD_130")
    assert boxes["NamedInsured_Signature_B"] is True and boxes["NamedInsured_SignatureDate_A"] is True
    assert boxes["NamedInsured_Signature_A"] is False               # not painted, no longer "to sign"
    assert not any("Initials" in b for b in boxes)
    sess["generated_forms"]["ACORD_130"]["field_state"]["X_A"] = "changed"
    assert sb.signed_applicant_boxes(sess, "ACORD_130") == {}


# ══ 5. The producer's to-do list ═════════════════════════════════════════════

def _attention(sess, fid):
    from services.needs_attention import needs_attention
    out = needs_attention(sess["generated_forms"][fid], {}, fid)
    return out if isinstance(out, list) else (out.get("rows") or out.get("items") or [])


def test_signed_forms_drop_the_applicants_rows_and_stale_ones_say_resend(key):
    import services.needs_attention as na
    sess = _signed_session("ACORD_125")
    rows = [r for r in _attention(sess, "ACORD_125") if r.get("applicant_step")]
    assert not [r for r in rows if r["field"] in ("NamedInsured_Signature_A", "NamedInsured_SignatureDate_A")]
    sess["generated_forms"]["ACORD_125"]["field_state"]["NamedInsured_FullName_A"] = "Changed LLC"
    rows = [r for r in _attention(sess, "ACORD_125") if r.get("applicant_step")]
    sig = [r for r in rows if r["field"] == "NamedInsured_Signature_A"]
    assert sig and sig[0]["what_to_do"] == na.APPLICANT_SIGNATURE_STALE


# ══ 6. Signing - every check before any write, and once ══════════════════════

class _Conn:
    def __init__(self, db):
        self.db = db

    async def fetchval(self, sql, *a):
        assert "status = $10" in sql
        row = self.db["row"]
        if row["status"] != a[9]:
            return None
        row.update(status=a[0], signed_at=a[1], signer_name=a[2], signature_data=a[3], consent_text=a[4],
                   signer_ip=a[5], signer_agent=a[6], form_versions=a[7])
        return row["id"]

    async def fetchrow(self, sql, *a):
        return dict(self.db["row"]) if a[0] == self.db["row"]["token"] else None


class _Pool:
    def __init__(self, db):
        self.db = db

    def acquire(self):
        pool = self

        class _Ctx:
            async def __aenter__(self_inner):
                return _Conn(pool.db)

            async def __aexit__(self_inner, *a):
                return False
        return _Ctx()


@pytest.fixture
def signing(monkeypatch, key):
    from datetime import datetime, timedelta, timezone
    token = asg.new_token()
    gen = _gen("ACORD_125")
    session = {"generated_forms": {"ACORD_125": gen, "ACORD_25": _gen("ACORD_25")},
               "selected_form_ids": ["ACORD_125", "ACORD_25"]}
    db = {"row": {"id": "req-1", "token": token, "status": "pending", "session_id": "s1", "user_id": "u1",
                  "form_ids": ["ACORD_125", "ACORD_25"],
                  "expires_at": (datetime.now(timezone.utc) + timedelta(days=7)).isoformat()},
          "writes": []}
    import config.database as cdb
    import repositories.session_repository as sr
    monkeypatch.setattr(cdb, "get_pool", lambda: _Pool(db))

    async def _get(sid):
        return session

    async def _upd(sid, updates, **k):
        db["writes"].append(updates)
    monkeypatch.setattr(sr, "get_processing_session", _get)
    monkeypatch.setattr(sr, "upd_processing_session", _upd)
    versions = asg.form_versions(session, ["ACORD_125"])
    return {"token": token, "db": db, "session": session, "versions": versions}


def _sign(sg, **over):
    args = dict(signer_name="Erin Royal", consent=True, image=_png(), versions=sg["versions"],
                tz_offset_minutes=-360, ip="1.2.3.4", agent="test")
    args.update(over)
    return asyncio.run(asg.sign(sg["token"], **args))


def test_signing_stores_the_signature_and_touches_no_form(signing):
    done = _sign(signing)
    assert done["forms"] == ["ACORD_125"]                        # ACORD 25 has no applicant line
    row = signing["db"]["row"]
    assert row["status"] == "signed" and row["signature_data"].startswith("enc:")
    assert row["consent_text"] == asg.CONSENT_TEXT
    assert {k: v for k, v in row["form_versions"].items() if not k.startswith("_")} == signing["versions"]
    assert row["form_versions"]["_tz_offset_minutes"] == -360
    assert signing["db"]["writes"] == []                         # recorded on submit, after the answers


def test_finalize_records_it_on_the_forms_as_they_print_after_the_answers(signing):
    _sign(signing)
    # the questionnaire's answers changed the 125 after the client signed
    signing["session"]["generated_forms"]["ACORD_125"]["field_state"]["Contact_Phone_A"] = "303-555-0100"
    done = asyncio.run(asg.finalize(signing["token"]))
    assert done["forms"] == ["ACORD_125"] and done["signer_name"] == "Erin Royal"
    write = signing["db"]["writes"][-1]
    meta = write["generated_forms"]["ACORD_125"][sb.APPLICANT_SIGNATURE_KEY]
    gen = signing["session"]["generated_forms"]["ACORD_125"]
    assert meta["fingerprint"] == sb.form_fingerprint(gen["field_state"], gen["schema"])
    assert meta["request_id"] == "req-1" and meta["signer_name"] == "Erin Royal"
    assert re.match(r"^\d{2}/\d{2}/\d{4}$", meta["signed_date"])
    assert write["generated_forms"]["ACORD_125"]["_pdf_cache_hash"] == ""
    assert write[sb.APPLICANT_IMAGES_KEY]["req-1"] == signing["db"]["row"]["signature_data"]
    assert "ACORD_25" not in write["generated_forms"]


def test_finalize_records_once_and_never_revalidates(signing):
    _sign(signing)
    asyncio.run(asg.finalize(signing["token"]))
    # pretend the write landed, then the forms moved on
    gen = signing["session"]["generated_forms"]["ACORD_125"]
    gen[sb.APPLICANT_SIGNATURE_KEY] = signing["db"]["writes"][-1]["generated_forms"]["ACORD_125"][sb.APPLICANT_SIGNATURE_KEY]
    gen["field_state"]["NamedInsured_FullName_A"] = "Changed LLC"
    n = len(signing["db"]["writes"])
    assert asyncio.run(asg.finalize(signing["token"])) is None
    assert len(signing["db"]["writes"]) == n


def test_finalize_does_nothing_without_a_signature(signing):
    assert asyncio.run(asg.finalize(signing["token"])) is None          # pending
    assert asyncio.run(asg.finalize("not-a-token")) is None
    assert signing["db"]["writes"] == []


def test_it_signs_once(signing):
    _sign(signing)
    with pytest.raises(asg.SigningError) as ei:
        _sign(signing)
    assert ei.value.code == "already_signed"


@pytest.mark.parametrize("over, code", [
    ({"image": None}, "image"), ({"image": _png(stroke=False)}, "image"), ({"image": "hello"}, "image"),
    ({"signer_name": "<script>"}, "name"), ({"versions": {"ACORD_125": "stale"}}, "forms_changed"),
])
def test_every_refusal_writes_nothing(signing, over, code):
    with pytest.raises(asg.SigningError) as ei:
        _sign(signing, **over)
    assert ei.value.code == code
    assert signing["db"]["row"]["status"] == "pending" and signing["db"]["writes"] == []


def test_the_signature_alone_is_enough(signing):
    """Owner, 1 Oct night: the question asks only for the signature. No name, no
    consent tick, no forms shown - the signer is the person the questionnaire
    was sent to."""
    signing["db"]["row"]["client_name"] = "  Erin   Royal "
    _sign(signing, signer_name=None, consent=None, versions=None)
    row = signing["db"]["row"]
    assert row["status"] == "signed" and row["signer_name"] == "Erin Royal"
    assert row["consent_text"] is None


def test_forms_edited_after_the_page_opened_are_not_signed(signing):
    signing["session"]["generated_forms"]["ACORD_125"]["field_state"]["NamedInsured_FullName_A"] = "Edited LLC"
    with pytest.raises(asg.SigningError) as ei:
        _sign(signing)
    assert ei.value.code == "forms_changed" and ei.value.status == 409


def test_without_an_encryption_key_nothing_is_stored(signing, monkeypatch):
    import utils.crypto as crypto
    monkeypatch.delenv("FIELD_ENCRYPTION_KEY", raising=False)
    monkeypatch.setattr(crypto, "_fernet", None)
    with pytest.raises(asg.SigningError) as ei:
        _sign(signing)
    assert ei.value.code == "storage" and signing["db"]["row"]["status"] == "pending"


def test_images_are_never_retired():
    sess = {sb.APPLICANT_IMAGES_KEY: {"old": "enc:1", "older": "enc:2"}}
    assert asg.images_after(sess, "new", "enc:4") == {"old": "enc:1", "older": "enc:2", "new": "enc:4"}
    assert asg.images_after({}, "new", "enc:4") == {"new": "enc:4"}


def test_the_producer_status_lines(key):
    sess = _signed_session("ACORD_125")
    sess["generated_forms"]["ACORD_25"] = _gen("ACORD_25")
    sess["generated_forms"]["ACORD_126"] = _gen("ACORD_126")
    st = {f["form_id"]: f for f in asg.form_statuses(sess)}
    assert set(st) == {"ACORD_125", "ACORD_126"}
    assert st["ACORD_125"]["state"] == "signed" and st["ACORD_125"]["signer_name"] == "Erin Royal"
    assert st["ACORD_126"]["state"] == "unsigned" and st["ACORD_126"]["signer_name"] is None
    sess["generated_forms"]["ACORD_125"]["field_state"]["X_A"] = "1"
    assert {f["form_id"]: f["state"] for f in asg.form_statuses(sess)}["ACORD_125"] == "stale"


# ══ 7. The HTTP edge ══════════════════════════════════════════════════════════

def test_the_public_route_refuses_a_bad_token_without_a_lookup(monkeypatch):
    import routes.applicant_sign_routes as r

    async def _never(*a, **k):
        raise AssertionError("looked up a malformed token")

    async def _ok(*a, **k):
        return None
    monkeypatch.setattr(r.asg, "get_by_token", _never)
    monkeypatch.setattr(r, "check_arq_submit_rate_limit", _ok)

    class _Req:
        headers = {}
        client = type("c", (), {"host": "1.2.3.4"})()

        async def body(self):
            return b"{}"
    for token in ("../../etc", "A" * 64, "x"):
        assert asyncio.run(r.sign_forms(token, _Req())).status_code == 404


def test_an_oversized_body_is_refused_before_parsing(monkeypatch):
    import routes.applicant_sign_routes as r

    async def _ok(*a, **k):
        return None
    monkeypatch.setattr(r, "check_arq_submit_rate_limit", _ok)

    class _Req:
        headers = {}
        client = type("c", (), {"host": "1.2.3.4"})()

        async def body(self):
            return b"x" * (asg.MAX_BODY_BYTES + 1)
    resp = asyncio.run(r.sign_forms(asg.new_token(), _Req()))
    assert resp.status_code == 413


def test_the_router_is_mounted_and_the_table_is_declared():
    main = (BACKEND / "main.py").read_text(encoding="utf-8")
    assert "app.include_router(applicant_sign_router)" in main
    db = (BACKEND / "config" / "database.py").read_text(encoding="utf-8")
    assert "CREATE TABLE IF NOT EXISTS signature_requests" in db
    auth = (BACKEND / "routes" / "auth_routes.py").read_text(encoding="utf-8")
    assert 'DELETE FROM signature_requests  WHERE user_id = $1' in auth


def test_only_the_sign_endpoint_is_public():
    src = (BACKEND / "routes" / "applicant_sign_routes.py").read_text(encoding="utf-8")
    assert '"/view/' not in src and "async def view_form_pdf" not in src      # owner: no forms list
    assert '@router.post("/sign/{token}")' in src
    assert "@router.post(\"/send\")" not in src


def test_a_deleted_package_takes_its_signature_data_and_only_the_owner_can(monkeypatch):
    src = (BACKEND / "routes" / "form_routes.py").read_text(encoding="utf-8")
    body = src[src.index("async def delete_session"):src.index("async def send_to_epic")]
    assert 'if str(status or "").strip().endswith(" 1"):' in body
    assert body.index('endswith(" 1")') < body.index("DELETE FROM session_pdf_bytes")
    assert "DELETE FROM signature_requests WHERE session_id = $1 AND user_id = $2" in body
    auth = (BACKEND / "routes" / "auth_routes.py").read_text(encoding="utf-8")
    acct = auth[auth.index("DELETE FROM session_pdf_bytes"):]
    assert acct.index("session_pdf_bytes") < acct.index("DELETE FROM processing_sessions")


def test_every_render_path_keeps_the_applicants_signature():
    fr = (BACKEND / "routes" / "form_routes.py").read_text(encoding="utf-8")
    sr = (BACKEND / "routes" / "signature_routes.py").read_text(encoding="utf-8")
    assert "applicant_signature_for(session, form_id, current_state)" in fr          # save
    assert "applicant_signature_for(proc_session, form_id, field_data)" in sr        # producer Sign
    assert "signed_applicant_boxes(proc_session, form_id)" in fr                     # viewer boxes


# ══ 8. The screens ═══════════════════════════════════════════════════════════

def test_one_pad_for_both_signers():
    modal = (FRONTEND / "components" / "signature" / "SignatureModal.jsx").read_text(encoding="utf-8")
    question = (FRONTEND / "components" / "arq" / "SignatureQuestion.jsx").read_text(encoding="utf-8")
    pad = (FRONTEND / "components" / "signature" / "SignaturePad.jsx").read_text(encoding="utf-8")
    assert "<SignaturePad onChange={setSignature}" in modal and "<SignaturePad onChange=" in question
    assert "<canvas" not in modal and "<canvas" not in question
    # strokes are scaled to the canvas, and the canvas keeps its shape
    assert "canvas.width / r.width" in pad and "canvas.height / r.height" in pad
    assert "aspectRatio: `${CANVAS_W} / ${CANVAS_H}`" in pad
    assert 'accept="image/png,image/jpeg,image/jpg"' in pad
    assert "UPLOAD_MAX_SIDE = 1600" in pad                       # a phone photo is scaled down


def test_the_signature_is_a_questionnaire_question_with_only_the_pad():
    app = (FRONTEND / "App.jsx").read_text(encoding="utf-8")
    assert "/sign/" not in app and "SignPage" not in app
    assert not (FRONTEND / "components" / "signature" / "SignPage.jsx").exists()
    modal = (FRONTEND / "components" / "form" / "AcordModal.jsx").read_text(encoding="utf-8")
    assert "Send for Signature" not in modal and "SendForSignatureModal" not in modal
    q = (FRONTEND / "components" / "arq" / "SignatureQuestion.jsx").read_text(encoding="utf-8")
    for gone in ("View form", "consent", "Your full name", "/api/applicant-sign/view"):
        assert gone not in q, gone                                 # owner: just the signature
    cq = (FRONTEND / "components" / "arq" / "ClientQuestionnaire.jsx").read_text(encoding="utf-8")
    sub = cq[cq.index("const handleSubmit"):]
    assert sub.index("/api/applicant-sign/sign/") < sub.index("/api/arq/submit/")
    assert "tz_offset_minutes: -new Date().getTimezoneOffset()" in sub
    assert "answers: { ...answersForShown(questions, answers), ...signed }" in sub
    assert "fieldType !== 'signature'" in cq                     # no "I'm not sure" on it


def test_the_stale_sentence_is_one_sentence():
    import services.needs_attention as na
    util = (FRONTEND / "utils" / "applicantSignature.js").read_text(encoding="utf-8")
    assert f'SIGNATURE_STALE_TEXT = "{na.APPLICANT_SIGNATURE_STALE}"' in util


def test_the_viewer_draws_nothing_over_a_painted_box():
    viewer = (FRONTEND / "components" / "form" / "PDFJsViewer.jsx").read_text(encoding="utf-8")
    assert "fieldsRef.current.filter(f => f.page === page - 1 && !f.painted)" in viewer
    assert "hitTestBox(fieldsRef.current.filter(f => !f.painted)" in viewer
    assert "if (_applicantSigned(fieldName)) return null;" in viewer
    assert "if (f.applicant_signed) return;" in viewer


@pytest.mark.parametrize("path", [
    FRONTEND / "components" / "arq" / "SignatureQuestion.jsx",
    FRONTEND / "components" / "signature" / "SignaturePad.jsx",
    FRONTEND / "components" / "signature" / "ApplicantSignature.jsx",
    FRONTEND / "utils" / "applicantSignature.js",
])
def test_no_em_dashes(path):
    assert "—" not in path.read_text(encoding="utf-8")


# ══ 9. Owner, 1 Oct night: the signature is a question in the questionnaire ══

def test_the_question_is_offered_for_forms_with_a_line_only():
    gen = {"ACORD_125": _gen("ACORD_125"), "ACORD_25": _gen("ACORD_25"), "ACORD_186": _gen("ACORD_186")}
    q = asg.signature_question({"generated_forms": gen, "selected_form_ids": ["ACORD_25", "ACORD_125", "ACORD_186"]})
    assert q["field_name"] == asg.SIGNATURE_FIELD and q["field_type"] == "signature"
    assert q["form_ids"] == ["ACORD_125"] and q["audience"] == "client" and q["bucket"] == "client"
    assert q["priority"] == "important" and q["force_preselect"] is True
    # it must land in a section the producer's list draws (a made-up topic key
    # left it counted but invisible - the owner's screen, 1 Oct night)
    from services.question_classifier import TOPIC_ORDER, TOPIC_LABELS
    assert q["topic_group"] in TOPIC_ORDER and q["topic_label"] == TOPIC_LABELS[q["topic_group"]]
    assert asg.signature_question({"generated_forms": {"ACORD_25": _gen("ACORD_25")}}) is None
    assert asg.signature_question(None) is None
    from services.question_classifier import apply_default_selection
    qs = [dict(q)]
    apply_default_selection(qs)
    assert qs[0].get("default_selected") is True                 # owner: pre-ticked like the others


def test_the_send_guard_keeps_it():
    from services.arq_service import filter_arq_questions_for_session
    gen = {"ACORD_125": _gen("ACORD_125")}
    q = asg.signature_question({"generated_forms": gen})
    assert filter_arq_questions_for_session(gen, [q]) == [q]


def test_send_rebuilds_it_server_side_and_gives_it_a_signing_request():
    src = (BACKEND / "routes" / "arq_routes.py").read_text(encoding="utf-8")
    send = src[src.index("async def send_arq"):src.index("async def client_view")]
    assert "applicant_signing.signature_question(proc_session)" in send       # never the request body's
    assert "applicant_signing.create_request(" in send and '_q["sign_token"] = _req["token"]' in send
    view = src[src.index("async def client_view"):]
    view = view[:view.index("@router.")]
    assert 'q_item["sign_token"] = q["sign_token"]' in view
    sub = src[src.index('@router.post("/submit/{token}")'):]
    assert sub.index("apply_arq_answers_to_session(") < sub.index("applicant_signing.finalize(") \
        < sub.index("recalculate_session_scores(")


def test_the_answer_is_kept_only_when_the_signature_is_really_stored_and_never_stamped():
    src = (BACKEND / "services" / "arq_service.py").read_text(encoding="utf-8")
    sub = src[src.index("async def submit_arq_answers"):]
    block = sub[sub.index('if q.get("field_type") == "signature":'):sub.index("Explicit client \"I'm not sure\"")]
    assert '_row.get("status") == _asg.STATUS_SIGNED' in block and "continue" in block
    apply = src[src.index("async def apply_arq_answers_to_session"):]
    assert 'if fn in answers and q.get("field_type") != "signature":' in apply


def test_the_receipt_says_signed_and_counts_it_as_a_question():
    from services.arq_receipt_service import build_receipt_payload
    from services.arq_service import response_counts
    q = {**asg.signature_question({"generated_forms": {"ACORD_125": _gen("ACORD_125")}}), "sign_token": "t" * 64}
    row = {"id": "a1", "session_id": "s1", "client_name": "Erin", "email": "e@x.co", "submitted_at": "2026-10-01",
           "questions": [q], "answers": {asg.SIGNATURE_FIELD: asg.SIGNED_ANSWER},
           "not_sure_fields": [], "review_fields": []}
    payload = build_receipt_payload(row)
    item = payload["items"][0]
    assert item["kind"] == "answer" and item["value"] == "Signed"
    counts = response_counts([q], payload["items"])
    assert counts["questions_answered"] == 1 and counts["questions_asked"] == 1


def test_the_old_standalone_pieces_are_gone():
    src = (BACKEND / "routes" / "applicant_sign_routes.py").read_text(encoding="utf-8")
    assert '"/send"' not in src
    email = (BACKEND / "services" / "email_service.py").read_text(encoding="utf-8")
    assert "send_signature_request_email" not in email and "send_applicant_signed_notification" not in email
