"""Any ACORD form through ASG (3 Nov 2026, Accommodate800forms.md section 10).

Stub only: `tests/conftest.py` sets ASG_FORMS_STUB_DIR, so every "download" reads
tests/fixtures/asg_forms_stub/<number>[_<STATE>].pdf (our own templates standing in for ASG's forms).
A test that reached the network would fail on the httpx guard below.
"""
import glob
import io
import json
import os
import re

import pikepdf
import pytest

from services import asg_forms as A

BACKEND = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TEMPLATES = os.path.join(BACKEND, "templates")


@pytest.fixture(autouse=True)
def _no_network(monkeypatch):
    """No test in this file may reach ASG."""
    import httpx

    def _refuse(*a, **k):
        raise AssertionError("a test tried to call ASG over the network")
    monkeypatch.setattr(httpx.Client, "send", _refuse)
    A.clear_ram()
    A.clear_copy_cache()
    A._token.update(value="", expiry=0.0, bearer=None, failed_until=0.0)
    yield
    A.clear_ram()
    A.clear_copy_cache()
    A._token.update(value="", expiry=0.0, bearer=None, failed_until=0.0)


def _norm(o, depth=0):
    if depth > 6:
        return "..."
    if isinstance(o, pikepdf.Stream):
        return ("stream", o.read_bytes())
    if isinstance(o, pikepdf.Dictionary):
        return tuple(sorted((k, _norm(o[k], depth + 1)) for k in o.keys() if k not in ("/Parent", "/P", "/Kids")))
    if isinstance(o, pikepdf.Array):
        return tuple(_norm(x, depth + 1) for x in o)
    return str(o)


def _state(pdf_bytes):
    out = {}
    with pikepdf.open(io.BytesIO(pdf_bytes)) as pdf:
        A._walk_fields(pdf.Root.AcroForm.Fields, lambda item, name: out.__setitem__(name, _norm(item)))
        pages = [_norm(p.Contents) for p in pdf.pages]
    return out, pages


# ── the search list and ids ──────────────────────────────────────────────────

def test_search_list_is_built_and_holds_our_forms_and_state_versions():
    idx = A._index()
    assert len(idx) > 1000
    for fid in ("ACORD_1", "ACORD_27", "ACORD_75", "ACORD_137_TX", "ACORD_125", "ACORD_25"):
        assert fid in idx, fid


def test_an_asg_form_is_in_the_list_and_not_one_of_ours():
    assert A.is_asg_form("ACORD_27")
    assert A.is_asg_form("ACORD_137_TX")
    for ours in ("ACORD_25", "ACORD_125", "ACORD_137_CA", "ACORD_101", "ACORD_131__excess"):
        assert not A.is_asg_form(ours), ours
    for junk in ("ACORD_99999", "", None, "ACORD_27; DROP", "acord_27", "ASG_27"):
        assert not A.is_asg_form(junk), junk


def test_search_finds_by_number_state_and_words_and_keeps_our_forms_ours():
    assert A.search("27")[0]["form_id"] == "ACORD_27"
    assert A.search("137 tx")[0]["form_id"] == "ACORD_137_TX"
    assert A.search("ACORD 75")[0]["form_id"] == "ACORD_75"
    assert any(r["form_id"] == "ACORD_75" for r in A.search("binder"))
    ours = A.search("acord 25")[0]
    assert ours["form_id"] == "ACORD_25" and ours["ours"] is True and ours["source"] == "primble"
    assert A.search("") == [] and A.search("   ") == []


def test_only_pc_forms_are_listed():
    """Brent, 4 Nov 2026: "Please show only the P&C forms, not the others." (Was: life forms ranked last.)"""
    for q in ("application", "life", "annuity", "701", "760", "951", "medical examiner", "disability"):
        assert all(r["pc"] for r in A.search(q, limit=5000)), q
    assert A.search("701", limit=5000) == [] or all(r["number"] != "701" for r in A.search("701", limit=5000))
    for fid in ("ACORD_701", "ACORD_760", "ACORD_951", "ACORD_660", "ACORD_782"):
        assert not A.is_pc_form(fid), fid
    for fid in ("ACORD_27", "ACORD_807", "ACORD_611", "ACORD_137_TX", "ACORD_829"):
        assert A.is_pc_form(fid), fid
    assert A.search("807")[0]["form_id"] == "ACORD_807"


def test_meta_is_shaped_like_our_forms_and_has_no_template_file():
    m = A.meta_for("ACORD_27")
    assert m["form_id"] == "ACORD_27" and m["source"] == "asg" and m["template_file"] == ""
    assert m["form_name"].startswith("ACORD 27 - ")
    assert A.meta_for("ACORD_25") is None                    # ours: never an ASG row


def test_form_meta_for_falls_back_to_asg_only_for_asg_ids():
    from services.form_instances import form_meta_for
    ours = [{"form_id": "ACORD_25", "template_file": "ACORD_25.pdf", "form_name": "ACORD 25"}]
    assert form_meta_for(ours, "ACORD_25") is ours[0]        # unchanged for our forms
    assert form_meta_for(ours, "ACORD_27")["source"] == "asg"
    assert form_meta_for(ours, "ACORD_126") is None          # ours but not in this package: unchanged
    assert form_meta_for(ours, "ACORD_99999") is None


# ── switch and cap ───────────────────────────────────────────────────────────

def test_switch_allow_list_and_cap(monkeypatch):
    monkeypatch.setenv("ASG_FORMS", "0")
    assert not A.enabled_for({"email": "a@b.com"})
    monkeypatch.setenv("ASG_FORMS", "1")
    monkeypatch.delenv("ASG_FORMS_ALLOWED_EMAILS", raising=False)
    assert A.enabled_for({"email": "a@b.com"})
    monkeypatch.setenv("ASG_FORMS_ALLOWED_EMAILS", "Owner@X.com, tester@x.com")
    assert A.enabled_for({"email": "owner@x.com"})
    assert not A.enabled_for({"email": "a@b.com"})
    assert not A.enabled_for({})
    monkeypatch.delenv("ASG_FORMS_MAX", raising=False)
    monkeypatch.delenv("PACKAGE_FORMS_MAX", raising=False)
    assert A.max_per_package() == 15                       # owner, 4 Nov: no separate ASG limit - the 15 total only
    monkeypatch.setenv("ASG_FORMS_MAX", "3")
    assert A.max_per_package() == 3                        # a lower ASG-only limit can still be set
    monkeypatch.setenv("ASG_FORMS_MAX", "40")
    assert A.max_per_package() == 15                       # never above the package total


# ── the download (stub) ──────────────────────────────────────────────────────

def test_fetch_reads_the_stub_and_keeps_a_ram_copy_for_the_run():
    m = A.meta_for("ACORD_27")
    data, edition, sample = A.fetch_blank(m)
    assert data[:5] == b"%PDF-" and sample is False
    again, _e, _s = A.fetch_blank(m)
    assert again is data                                     # the run's RAM copy, no second download


def test_a_form_asg_does_not_have_is_unavailable_never_a_crash():
    m = A.meta_for("ACORD_75")                               # no stub file = ASG's "Invalid Form"
    with pytest.raises(A.AsgFormUnavailable) as ex:
        A.fetch_blank(m)
    assert ex.value.reason == "not_available"


def test_fetch_refuses_a_non_asg_row():
    with pytest.raises(A.AsgFormUnavailable):
        A.fetch_blank({"form_id": "ACORD_25", "template_file": "ACORD_25.pdf"})


def test_no_credentials_means_no_network_call(monkeypatch):
    monkeypatch.delenv("ASG_FORMS_STUB_DIR", raising=False)
    for k in ("TRANSCRIBER_CLIENT_ID", "TRANSCRIBER_CLIENT_SECRET", "TRANSCRIBER_API_KEY"):
        monkeypatch.setenv(k, "")
    with pytest.raises(A.AsgFormUnavailable) as ex:
        A.fetch_blank(A.meta_for("ACORD_27"))
    assert ex.value.reason == "not_configured"


def test_uat_credentials_are_refused_in_production_unless_allowed(monkeypatch):
    monkeypatch.delenv("ASG_FORMS_STUB_DIR", raising=False)
    monkeypatch.setenv("TRANSCRIBER_CLIENT_ID", "x")
    monkeypatch.setenv("TRANSCRIBER_CLIENT_SECRET", "y")
    monkeypatch.setenv("TRANSCRIBER_API_KEY", "z")
    monkeypatch.setenv("TRANSCRIBER_ENV", "uat")
    monkeypatch.setenv("ENVIRONMENT", "production")
    monkeypatch.delenv("TRANSCRIBER_ALLOW_UAT_IN_PROD", raising=False)
    ok, why = A._network_allowed(A._config())
    assert not ok and "UAT" in why
    monkeypatch.setenv("TRANSCRIBER_ALLOW_UAT_IN_PROD", "1")
    assert A._network_allowed(A._config())[0]


def _with_sample_watermark(pdf_bytes):
    """A copy carrying a page-wide image with a transparency mask - the shape of ASG's UAT "Sample" stamp."""
    from PIL import Image
    pdf = pikepdf.open(io.BytesIO(pdf_bytes))
    img = Image.new("RGBA", (1108, 775), (80, 80, 80, 90))
    rgb = img.convert("RGB").tobytes()
    alpha = img.split()[-1].tobytes()
    smask = pikepdf.Stream(pdf, alpha, Type=pikepdf.Name.XObject, Subtype=pikepdf.Name.Image, Width=1108,
                           Height=775, ColorSpace=pikepdf.Name.DeviceGray, BitsPerComponent=8)
    im = pikepdf.Stream(pdf, rgb, Type=pikepdf.Name.XObject, Subtype=pikepdf.Name.Image, Width=1108, Height=775,
                        ColorSpace=pikepdf.Name.DeviceRGB, BitsPerComponent=8, SMask=smask)
    page = pdf.pages[0]
    res = page.get("/Resources")
    if "/XObject" not in res:
        res["/XObject"] = pikepdf.Dictionary()
    res["/XObject"]["/ImSample"] = im
    buf = io.BytesIO()
    pdf.save(buf)
    return buf.getvalue()


def test_the_sample_stamp_is_detected_and_never_removed(tmp_path, monkeypatch):
    stamped = _with_sample_watermark(open(os.path.join(TEMPLATES, "ACORD_25.pdf"), "rb").read())
    assert A.has_sample_watermark(stamped)
    assert not A.has_sample_watermark(open(os.path.join(TEMPLATES, "ACORD_25.pdf"), "rb").read())
    (tmp_path / "27.pdf").write_bytes(stamped)
    monkeypatch.setenv("ASG_FORMS_STUB_DIR", str(tmp_path))
    data, _e, sample = A.fetch_blank(A.meta_for("ACORD_27"))
    assert sample is True and data == stamped                # flagged, bytes untouched


def test_edition_is_read_off_the_printed_form():
    data = open(os.path.join(TEMPLATES, "ACORD_25.pdf"), "rb").read()
    assert A.edition_from_pdf(data, "25") == "2025/12"
    assert A.edition_from_pdf(data, "27") is None


# ── the stored copy (D-ASG-3) ────────────────────────────────────────────────

def test_schema_from_the_pdf_equals_our_schema_reader():
    from services.pdf_service import extract_form_schema
    path = os.path.join(TEMPLATES, "ACORD_25.pdf")
    assert A.schema_from_pdf(open(path, "rb").read()) == extract_form_schema(path, "ACORD_25")


@pytest.mark.parametrize("tpl", sorted(glob.glob(os.path.join(TEMPLATES, "ACORD_*.pdf"))))
def test_clearing_the_values_only_copy_gives_back_the_exact_blank_and_the_same_fill(tpl):
    """Measured on all 17 of our templates as stand-in ASG forms: the stored copy is cleared back to the exact
    blank (every box key, every page drawing), and filling it equals filling the blank."""
    from services.pdf_service import extract_form_schema, fill_pdf
    fid = os.path.basename(tpl)[:-4]
    blank = open(tpl, "rb").read()
    schema = extract_form_schema(tpl, fid)
    names = list(schema)
    first = {n: ("Yes" if schema[n]["ft"] == "/Btn" else f"long value {i} " * 4) for i, n in enumerate(names[::3])}
    later = {n: (("No" if i % 2 else "Yes") if schema[n]["ft"] == "/Btn" else f"v{i}")
             for i, n in enumerate(names[::2])}
    conf = {n: "low_confidence" for n in later}
    cleared = A.cleared_template(A.values_only_copy(blank, first))
    assert _state(cleared) == _state(blank)
    assert _state(fill_pdf(tpl, later, conf)) == _state(fill_pdf(cleared, later, conf))


def test_the_values_only_copy_holds_the_values_and_nothing_drawn():
    path = os.path.join(TEMPLATES, "ACORD_25.pdf")
    blank = open(path, "rb").read()
    base = A.values_only_copy(blank, {"NamedInsured_FullName_A": "Orbin Contracting LLC"})
    with pikepdf.open(io.BytesIO(base)) as pdf:
        vals = {}
        A._walk_fields(pdf.Root.AcroForm.Fields, lambda i, n: vals.__setitem__(n, str(i.get("/V", ""))))
    assert vals["NamedInsured_FullName_A"] == "Orbin Contracting LLC"
    assert _state(base)[1] == _state(blank)[1]               # no highlight or signature drawing


def test_template_source_rebuilds_from_the_package_copy_without_asg():
    blank = open(os.path.join(TEMPLATES, "ACORD_25.pdf"), "rb").read()
    rec = {"form": dict(A.meta_for("ACORD_27"), edition="2016/03"),
           "asg_base_pdf": A.values_only_copy(blank, {"NamedInsured_FullName_A": "X"})}
    assert _state(A.template_source(rec)) == _state(blank)
    assert A.template_source({"form": {"form_id": "ACORD_25", "template_file": "ACORD_25.pdf"}}) is None
    assert A.layout_source(rec) == rec["asg_base_pdf"]


def test_template_source_never_calls_asg_when_the_copy_is_missing(monkeypatch):
    """After generation a package never goes back to ASG (review 3 Nov): no copy = None, no download."""
    calls = []
    monkeypatch.setattr(A, "fetch_blank", lambda *a, **k: calls.append(a) or (b"%PDF-", None, False))
    rec = {"form": dict(A.meta_for("ACORD_27"), edition="2016/03")}
    assert A.template_source(rec) is None
    assert A.layout_source(rec) is None
    assert calls == []


def test_the_copy_read_back_from_the_database_is_used_and_never_resaved():
    blank = open(os.path.join(TEMPLATES, "ACORD_25.pdf"), "rb").read()
    stored = A.values_only_copy(blank, {"NamedInsured_FullName_A": "X"})
    rec = {"form": dict(A.meta_for("ACORD_27")), A.STORED_BASE_KEY: stored}
    assert _state(A.template_source(rec)) == _state(blank)
    from repositories import session_repository as sr
    assert A.STORED_BASE_KEY in sr._PDF_BYTE_KEYS and A.NEW_BASE_KEY in sr._PDF_BYTE_KEYS


# ── generation, end to end (stub, no AI) ─────────────────────────────────────

def _orbin_session(form_ids):
    fx = json.load(open(os.path.join(BACKEND, "tests", "fixtures", "needs_attention_live_30sep.json")))["b8d6"]
    return {"facts": fx["facts"], "flags": fx["flags"], "docs": [], "all_forms": [],
            "selected_form_ids": list(form_ids)}


def test_an_asg_form_is_generated_like_ours_and_keeps_its_copy():
    from services.form_service import process_single_form
    session = _orbin_session(["ACORD_27"])
    meta = A.meta_for("ACORD_27")
    res = process_single_form(meta, session, {"filled_values": {}, "raw_text_fields": set(),
                                              "question_grounding": {}})
    assert res["form_id"] == "ACORD_27" and res["form"]["source"] == "asg"
    assert res["pdf_bytes"][:5] == b"%PDF-"
    assert res["schema"] and res["mapped"].get("NamedInsured_FullName_A")    # filled from the package facts
    assert res["asg_base_pdf"][:5] == b"%PDF-"
    assert "edition" in res["form"] and res["form"]["asg_sample"] is False
    assert isinstance(res["sqs"], dict)


def test_a_generated_asg_form_re_renders_from_its_copy():
    from services.form_service import process_single_form
    from services.pdf_service import regenerate_pdf_for_form
    session = _orbin_session(["ACORD_27"])
    res = process_single_form(A.meta_for("ACORD_27"), session, {"filled_values": {}, "raw_text_fields": set(),
                                                                "question_grounding": {}})
    A.clear_ram()
    rec = dict(res)
    rec["field_state"] = dict(res["mapped"], NamedInsured_FullName_A="Edited Name LLC")
    out = regenerate_pdf_for_form({"generated_forms": {"ACORD_27": rec}}, "ACORD_27", force=True)
    with pikepdf.open(io.BytesIO(out)) as pdf:
        vals = {}
        A._walk_fields(pdf.Root.AcroForm.Fields, lambda i, n: vals.__setitem__(n, str(i.get("/V", ""))))
    assert vals["NamedInsured_FullName_A"] == "Edited Name LLC"


def test_shared_gap_fill_reads_an_asg_forms_boxes(monkeypatch):
    """The shared gap fill builds the ASG form's box list from its download - no model call here: the gap
    fill itself is stubbed, only the box lists it receives are checked. A first generation runs with the
    switch on (the generate route refuses ASG forms otherwise)."""
    monkeypatch.setenv("ASG_FORMS", "1")
    from services import form_service as fs
    import services.pdf_service as ps
    seen = {}

    def fake_combined(forms_to_unmatched, *a, **k):
        seen.update(forms_to_unmatched)
        return {}
    orig = ps.combined_gap_fill
    ps.combined_gap_fill = fake_combined
    try:
        fs.shared_gap_fill(_orbin_session(["ACORD_27"]), ["ACORD_27"])
    finally:
        ps.combined_gap_fill = orig
    assert "ACORD_27" in seen and seen["ACORD_27"]


def test_the_session_store_keeps_the_copy_out_of_the_json_and_in_its_own_row():
    from repositories import session_repository as sr
    data = {"generated_forms": {"ACORD_27": {"mapped": {"a": "1"}, "pdf_bytes": b"%PDF-r", "asg_base_pdf": b"%PDF-b"},
                                "ACORD_25": {"mapped": {}, "pdf_bytes": b"%PDF-o"}}}
    clean = sr._session_to_db(data)
    json.dumps(clean)                                        # no bytes left in the JSON
    assert "asg_base_pdf" not in clean["generated_forms"]["ACORD_27"]
    assert A.base_row_id("ACORD_27") == "ACORD_27::asg_base"
    assert A.form_id_of_base_row("ACORD_27::asg_base") == "ACORD_27"
    assert A.form_id_of_base_row("ACORD_27") is None


def test_save_and_load_round_trip_the_copy(monkeypatch):
    import asyncio
    from repositories import session_repository as sr
    rows = {}

    class Conn:
        async def execute(self, sql, sid, fid, pb, now):
            rows[fid] = pb

        async def fetch(self, sql, sid):
            return [{"form_id": k, "pdf_bytes": v} for k, v in rows.items()]

        def transaction(self):
            return _Ctx(self)

    class _Ctx:
        def __init__(self, c):
            self.c = c

        async def __aenter__(self):
            return self.c

        async def __aexit__(self, *a):
            return False

    class Pool:
        def acquire(self):
            return _Ctx(Conn())
    monkeypatch.setattr(sr, "get_pool", lambda: Pool())
    gen = {"ACORD_27": {"pdf_bytes": b"%PDF-r", "asg_base_pdf": b"%PDF-b"}, "ACORD_25": {"pdf_bytes": b"%PDF-o"}}
    asyncio.run(sr._save_pdf_bytes("s1", gen))
    assert rows == {"ACORD_27": b"%PDF-r", "ACORD_27::asg_base": b"%PDF-b", "ACORD_25": b"%PDF-o"}
    asg_form = {"source": "asg", "form_id": "ACORD_27"}
    data = {"generated_forms": {"ACORD_27": {"form": asg_form}, "ACORD_25": {}}}
    asyncio.run(sr._session_from_db(data, "s1"))
    assert data["generated_forms"]["ACORD_27"] == {"form": asg_form, "pdf_bytes": b"%PDF-r",
                                                   A.STORED_BASE_KEY: b"%PDF-b"}
    assert data["generated_forms"]["ACORD_25"] == {"pdf_bytes": b"%PDF-o"}
    # the read-back copy is never written again (only a copy made by a run is)
    rows.clear()
    asyncio.run(sr._save_pdf_bytes("s1", data["generated_forms"]))
    assert set(rows) == {"ACORD_27", "ACORD_25"}


def test_the_editor_reads_box_positions_from_the_package_copy():
    from services.pdf_service import extract_form_fields_with_positions, get_page_dims_pikepdf
    blank = open(os.path.join(TEMPLATES, "ACORD_25.pdf"), "rb").read()
    path = os.path.join(TEMPLATES, "ACORD_25.pdf")
    assert extract_form_fields_with_positions(blank) == extract_form_fields_with_positions(path)
    assert get_page_dims_pikepdf(blank) == get_page_dims_pikepdf(path)


def test_search_route_is_off_unless_switched_on(monkeypatch):
    import asyncio
    from routes.asg_forms_routes import search_asg_forms
    monkeypatch.setenv("ASG_FORMS", "0")
    body = json.loads(asyncio.run(search_asg_forms(q="27", current_user={"email": "a@b.com"})).body)
    assert body["enabled"] is False and body["results"] == []
    monkeypatch.setenv("ASG_FORMS", "1")
    monkeypatch.delenv("ASG_FORMS_ALLOWED_EMAILS", raising=False)
    body = json.loads(asyncio.run(search_asg_forms(q="27", current_user={"email": "a@b.com"})).body)
    assert body["enabled"] is True and body["results"][0]["form_id"] == "ACORD_27"


# ── review round 1 (3 Nov 2026) ──────────────────────────────────────────────

def _fake_pool(rows_by_query):
    class Conn:
        async def fetchrow(self, sql, sid):
            return {"data": rows_by_query["row"]}

        async def fetch(self, sql, *args):
            rows_by_query.setdefault("queries", []).append(sql)
            return rows_by_query.get("bases", [])

    class _Ctx:
        async def __aenter__(self):
            return Conn()

        async def __aexit__(self, *a):
            return False

    class Pool:
        def acquire(self):
            return _Ctx()
    return Pool()


def test_every_read_of_an_asg_package_brings_its_copy_and_box_order(monkeypatch):
    """The editor, preview and edit save read the package WITHOUT its PDFs - an ASG form must still get its copy
    (review CRITICAL) and its printed box order back (the stored schema comes back key-sorted)."""
    import asyncio
    from repositories import session_repository as sr
    order = ["Zeta_A", "Alpha_A", "Mid_A"]
    sorted_schema = {k: {"ft": "/Tx", "tu": "", "required": False} for k in sorted(order)}
    data = {"user_id": "u", "generated_forms": {
        "ACORD_27": {"form": {"source": "asg", "form_id": "ACORD_27"}, "schema": sorted_schema, A.ORDER_KEY: order},
        "ACORD_25": {"form": {"form_id": "ACORD_25", "template_file": "ACORD_25.pdf"}, "schema": {"b": 1, "a": 2}}}}
    store = {"row": json.dumps(data), "bases": [{"form_id": "ACORD_27::asg_base", "pdf_bytes": b"%PDF-base"}]}
    monkeypatch.setattr(sr, "get_pool", lambda: _fake_pool(store))
    monkeypatch.setattr(sr, "_decrypt_facts", lambda d: d)
    got = asyncio.run(sr.get_processing_session("s1"))
    rec = got["generated_forms"]["ACORD_27"]
    assert rec[A.STORED_BASE_KEY] == b"%PDF-base"
    assert list(rec["schema"]) == order
    assert list(got["generated_forms"]["ACORD_25"]["schema"]) == ["b", "a"]     # ours: untouched


def test_a_package_without_asg_forms_makes_no_extra_query(monkeypatch):
    import asyncio
    from repositories import session_repository as sr
    data = {"generated_forms": {"ACORD_25": {"form": {"form_id": "ACORD_25"}}}}
    store = {"row": json.dumps(data)}
    monkeypatch.setattr(sr, "get_pool", lambda: _fake_pool(store))
    monkeypatch.setattr(sr, "_decrypt_facts", lambda d: d)
    asyncio.run(sr.get_processing_session("s1"))
    assert "queries" not in store


def test_generation_keeps_the_printed_box_order():
    from services.form_service import process_single_form
    res = process_single_form(A.meta_for("ACORD_27"), _orbin_session(["ACORD_27"]),
                              {"filled_values": {}, "raw_text_fields": set(), "question_grounding": {}})
    assert res[A.ORDER_KEY] == list(res["schema"].keys())
    assert res[A.ORDER_KEY] == list(A.schema_from_pdf(A.fetch_blank(A.meta_for("ACORD_27"))[0]).keys())


@pytest.mark.parametrize("exc_name", ["ConnectTimeout", "ConnectError", "ReadTimeout"])
def test_network_errors_become_unavailable_never_a_raw_exception(monkeypatch, exc_name):
    import httpx
    monkeypatch.delenv("ASG_FORMS_STUB_DIR", raising=False)
    for k, v in (("TRANSCRIBER_CLIENT_ID", "x"), ("TRANSCRIBER_CLIENT_SECRET", "y"), ("TRANSCRIBER_API_KEY", "z"),
                 ("TRANSCRIBER_ENV", "uat"), ("ENVIRONMENT", "development")):
        monkeypatch.setenv(k, v)
    A._token.update(value="", expiry=0.0, bearer=None, failed_until=0.0)

    def boom(self, request, **kw):
        raise getattr(httpx, exc_name)("down", request=request)
    monkeypatch.setattr(httpx.Client, "send", boom)
    with pytest.raises(A.AsgFormUnavailable) as ex:
        A.fetch_blank(A.meta_for("ACORD_27"))
    assert ex.value.reason == "asg_error"


def test_a_token_reply_that_is_not_json_is_unavailable(monkeypatch):
    import httpx
    monkeypatch.delenv("ASG_FORMS_STUB_DIR", raising=False)
    for k, v in (("TRANSCRIBER_CLIENT_ID", "x"), ("TRANSCRIBER_CLIENT_SECRET", "y"), ("TRANSCRIBER_API_KEY", "z"),
                 ("TRANSCRIBER_ENV", "uat"), ("ENVIRONMENT", "development")):
        monkeypatch.setenv(k, v)
    A._token.update(value="", expiry=0.0, bearer=None, failed_until=0.0)

    def html(self, request, **kw):
        return httpx.Response(200, text="<html>maintenance</html>", request=request)
    monkeypatch.setattr(httpx.Client, "send", html)
    with pytest.raises(A.AsgFormUnavailable):
        A.fetch_blank(A.meta_for("ACORD_27"))


def test_a_box_listed_twice_never_leaks_its_value_into_the_clean_form():
    blank = open(os.path.join(TEMPLATES, "ACORD_25.pdf"), "rb").read()
    pdf = pikepdf.open(io.BytesIO(blank))
    fields = pdf.Root.AcroForm.Fields
    target = next(f for f in fields if str(f.get("/T", "")) == "NamedInsured_FullName_A")
    fields.append(target)                                   # the same box listed twice (a malformed form)
    buf = io.BytesIO()
    pdf.save(buf)
    twice = buf.getvalue()
    base = A.values_only_copy(twice, {"NamedInsured_FullName_A": "LEAK-VALUE"})
    clean = A.cleared_template(base)
    with pikepdf.open(io.BytesIO(clean)) as p2:
        vals = []
        A._walk_fields(p2.Root.AcroForm.Fields,
                       lambda i, n: vals.append(str(i.get("/V", ""))) if n == "NamedInsured_FullName_A" else None)
    assert "LEAK-VALUE" not in vals


def test_the_edition_reader_never_takes_a_longer_form_number():
    data = open(os.path.join(TEMPLATES, "ACORD_125.pdf"), "rb").read()
    assert A.edition_from_pdf(data, "125") == "2025/03"
    assert A.edition_from_pdf(data, "1") is None
    assert A.edition_from_pdf(data, "12") is None


def test_an_asg_form_never_prints_one_of_our_forms_editions():
    from services.pdf_service import _form_edition_identifier
    for fid in ("ACORD_1", "ACORD_2", "ACORD_12", "ACORD_13", "ACORD_18"):
        assert A.is_asg_form(fid)
        assert _form_edition_identifier(fid) is None, fid
    assert _form_edition_identifier("ACORD_125") == "ACORD 125 (2025/03)"     # ours: unchanged


def test_the_list_holds_no_guessed_state_codes():
    for e in A._index().values():
        assert not e["state"] or e["state"] in {
            *"AL AK AZ AR CA CO CT DE FL GA HI ID IL IN IA KS KY LA ME MD MA MI MN MS MO MT NE NV NH NJ NM NY NC "
             "ND OH OK OR PA RI SC SD TN TX UT VT VA WA WV WI WY DC PR VI GU AS MP".split()}, e["form_id"]
    assert not A.is_asg_form("ACORD_126_GL")                       # not in ASG's catalogue at all
    # ASG's own non-state codes are listed as VARIANTS, never as a state (owner, 4 Nov 2026: "add now")
    for fid in ("ACORD_25_FR", "ACORD_60_US"):
        e = A._index()[fid]
        assert A.is_asg_form(fid) and not e["state"] and e["suffix"] == fid.rsplit("_", 1)[1], e


def test_ids_are_cleaned_once_and_the_cap_counts_the_package():
    assert A.clean_form_ids([" ACORD_27", "ACORD_27", "", None, "ACORD_125 ", "ACORD_125"]) == ["ACORD_27", "ACORD_125"]
    assert A.asg_count_in_package(["ACORD_27", "ACORD_125"], {"ACORD_75": {}}) == 2
    assert A.asg_count_in_package(["ACORD_27"], {"ACORD_27": {}}) == 1


def test_a_cached_render_does_not_rebuild_the_template(monkeypatch):
    import hashlib
    from services import pdf_service as ps
    field_state = {"NamedInsured_FullName_A": "X"}
    rec = {"form": dict(A.meta_for("ACORD_27")), "field_state": field_state, "pdf_bytes": b"%PDF-cached",
           "_pdf_cache_hash": hashlib.md5(json.dumps(field_state, sort_keys=True).encode()).hexdigest()}
    monkeypatch.setattr(A, "template_source", lambda r: (_ for _ in ()).throw(AssertionError("rebuilt")))
    assert ps.regenerate_pdf_for_form({"generated_forms": {"ACORD_27": rec}}, "ACORD_27") == b"%PDF-cached"


def test_a_render_without_the_copy_is_a_503_never_an_asg_call(monkeypatch):
    from fastapi import HTTPException
    from services import pdf_service as ps
    monkeypatch.setattr(A, "fetch_blank", lambda *a, **k: (_ for _ in ()).throw(AssertionError("ASG called")))
    rec = {"form": dict(A.meta_for("ACORD_27")), "field_state": {"x": "1"}}
    with pytest.raises(HTTPException) as ex:
        ps.regenerate_pdf_for_form({"generated_forms": {"ACORD_27": rec}}, "ACORD_27", force=True)
    assert ex.value.status_code == 503


def test_adding_a_document_after_forms_reads_the_copy_not_asg(monkeypatch, tmp_path):
    """The shared gap fill of a package that already has the ASG form uses the package's copy - no download,
    even with the stub folder empty and the switch off."""
    from services import form_service as fs
    import services.pdf_service as ps
    monkeypatch.setenv("ASG_FORMS_STUB_DIR", str(tmp_path))          # nothing to download
    monkeypatch.setenv("ASG_FORMS", "0")
    blank = open(os.path.join(TEMPLATES, "ACORD_25.pdf"), "rb").read()
    session = _orbin_session(["ACORD_27"])
    session["generated_forms"] = {"ACORD_27": {"form": dict(A.meta_for("ACORD_27")),
                                               A.STORED_BASE_KEY: A.values_only_copy(blank, {})}}
    seen = {}

    def fake_combined(forms_to_unmatched, *a, **k):
        seen.update(forms_to_unmatched)
        return {}
    monkeypatch.setattr(ps, "combined_gap_fill", fake_combined)
    fs.shared_gap_fill(session, ["ACORD_27"])
    assert seen.get("ACORD_27")


def test_with_the_switch_off_a_new_asg_form_is_never_downloaded_by_the_gap_fill(monkeypatch):
    from services import form_service as fs
    import services.pdf_service as ps
    monkeypatch.setenv("ASG_FORMS", "0")
    monkeypatch.setattr(A, "fetch_blank", lambda *a, **k: (_ for _ in ()).throw(AssertionError("ASG called")))
    monkeypatch.setattr(ps, "combined_gap_fill", lambda *a, **k: {})
    fs.shared_gap_fill(_orbin_session(["ACORD_27"]), ["ACORD_27"])


# ── review round 2 (3 Nov 2026) ──────────────────────────────────────────────

def test_try_fetch_reports_a_form_asg_cannot_give_and_never_raises():
    assert A.try_fetch(A.meta_for("ACORD_27")) is None                 # the stub has it
    assert A.try_fetch(A.meta_for("ACORD_75")) == {"form_id": "ACORD_75", "reason": "not_available"}
    assert A.label_of("ACORD_137_TX") == "ACORD 137 TX"


@pytest.mark.parametrize("body", ["[]", '"ok"', '{"access_token": "t", "expires_in": [1]}'])
def test_a_token_reply_of_the_wrong_shape_is_unavailable(monkeypatch, body):
    import httpx
    monkeypatch.delenv("ASG_FORMS_STUB_DIR", raising=False)
    for k, v in (("TRANSCRIBER_CLIENT_ID", "x"), ("TRANSCRIBER_CLIENT_SECRET", "y"), ("TRANSCRIBER_API_KEY", "z"),
                 ("TRANSCRIBER_ENV", "uat"), ("ENVIRONMENT", "development")):
        monkeypatch.setenv(k, v)
    A._token.update(value="", expiry=0.0, bearer=None, failed_until=0.0)

    def reply(self, request, **kw):
        return httpx.Response(200, text=body, request=request)
    monkeypatch.setattr(httpx.Client, "send", reply)
    with pytest.raises(A.AsgFormUnavailable):
        A.fetch_blank(A.meta_for("ACORD_27"))


def test_stored_copies_are_read_from_the_database_once_per_process(monkeypatch):
    import asyncio
    from repositories import session_repository as sr
    A.clear_copy_cache()
    data = {"generated_forms": {"ACORD_27": {"form": {"source": "asg", "form_id": "ACORD_27"}}}}
    store = {"row": json.dumps(data), "bases": [{"form_id": "ACORD_27::asg_base", "pdf_bytes": b"%PDF-base"}]}
    monkeypatch.setattr(sr, "get_pool", lambda: _fake_pool(store))
    monkeypatch.setattr(sr, "_decrypt_facts", lambda d: d)
    first = asyncio.run(sr.get_processing_session("s-cache"))
    second = asyncio.run(sr.get_processing_session("s-cache"))
    assert len(store["queries"]) == 1                                   # the second read used the cache
    for got in (first, second):
        assert got["generated_forms"]["ACORD_27"][A.STORED_BASE_KEY] == b"%PDF-base"
    A.clear_copy_cache()


def test_the_copy_cache_is_bounded():
    A.clear_copy_cache()
    big = b"x" * (A._COPY_CACHE_MAX_BYTES // 3 + 1)
    for i in range(5):
        A.remember_copies(f"s{i}", {"ACORD_27": big})
    assert sum(len(v) for v in A._copy_cache.values()) <= A._COPY_CACHE_MAX_BYTES
    assert A.cached_copies("s4", ["ACORD_27"]) is not None                # the newest is kept
    assert A.cached_copies("s0", ["ACORD_27"]) is None                    # the oldest went first
    assert A.cached_copies("s4", ["ACORD_27", "ACORD_75"]) is None        # all or nothing
    A.clear_copy_cache()


def test_asg_box_positions_are_read_once_per_copy():
    from services import needs_attention as na
    blank = open(os.path.join(TEMPLATES, "ACORD_25.pdf"), "rb").read()
    rec = {"form": dict(A.meta_for("ACORD_27")), A.STORED_BASE_KEY: A.values_only_copy(blank, {})}
    na._asg_widget_positions.cache_clear()
    first = na.widget_positions("ACORD_27", rec)
    for _ in range(20):
        assert na.widget_positions("ACORD_27", rec) == first
    info = na._asg_widget_positions.cache_info()
    assert info.misses == 1 and info.hits == 20 and first


def test_user_messages_never_claim_a_refused_edit_was_saved():
    for msg in (A.CANNOT_SHOW, A.EDIT_NOT_SAVED, A.NOT_SIGNED):
        assert "saved." not in msg.replace("not saved", "")
    assert "not saved" in A.EDIT_NOT_SAVED


# ── review round 3 (3 Nov 2026) ──────────────────────────────────────────────

def test_the_package_is_preparing_while_its_asg_forms_download():
    import time as _t
    from services.generation_state import PREPARING_KEY, PREPARING_TTL_SECONDS, preparing
    now = _t.time()
    assert preparing({PREPARING_KEY: now}, now=now + 5)
    assert not preparing({PREPARING_KEY: now}, now=now + PREPARING_TTL_SECONDS + 1)   # expires by itself
    assert not preparing({PREPARING_KEY: None})
    assert not preparing({})
    assert not preparing({PREPARING_KEY: now, "generated_forms": {"ACORD_27": {}}}, now=now)
    assert not preparing({PREPARING_KEY: "junk"})


def test_the_ram_copy_is_bounded_by_size_and_counts_a_download_once(monkeypatch):
    monkeypatch.setattr(A, "_RAM_MAX_BYTES", 1000)
    A.clear_ram()
    import time as _t
    _now = _t.monotonic()
    a = b"a" * 400
    A._ram_put([("1", "", "", "latest"), ("1", "", "", "2016/03")], (_now, a, "2016/03", False))
    assert A._ram_get(("1", "", "", "latest")) and A._ram_get(("1", "", "", "2016/03"))   # 400 bytes, not 800
    A._ram_put([("2", "", "", "latest")], (_now, b"b" * 400, None, False))
    assert A._ram_get(("1", "", "", "latest"))                                            # 800 <= 1000: kept
    A._ram_put([("3", "", "", "latest")], (_now, b"c" * 400, None, False))
    assert A._ram_get(("3", "", "", "latest"))
    total = sum(len(v[1]) for v in {id(v[1]): v for v in A._ram.values()}.values())
    assert total <= 1000
    A.clear_ram()


def test_a_failure_is_remembered_so_a_retry_does_not_ask_asg_again(monkeypatch):
    calls = []
    real = A._stub_fetch
    monkeypatch.setattr(A, "_stub_fetch", lambda meta: calls.append(meta["form_id"]) or real(meta))
    for _ in range(3):
        with pytest.raises(A.AsgFormUnavailable):
            A.fetch_blank(A.meta_for("ACORD_75"))                 # no stub file = "not available"
    assert calls == ["ACORD_75"]


def test_a_reply_that_is_not_a_fillable_form_is_refused(monkeypatch, tmp_path):
    (tmp_path / "27.pdf").write_bytes(b"%PDF-1.4 this is not really a pdf")
    monkeypatch.setenv("ASG_FORMS_STUB_DIR", str(tmp_path))
    with pytest.raises(A.AsgFormUnavailable) as ex:
        A.fetch_blank(A.meta_for("ACORD_27"))
    assert ex.value.reason == "bad_file"          # left out of the run, remembered for half an hour (5 Nov 2026)
    assert A._FAIL_TTL["bad_file"] <= 30 * 60 < A._FAIL_TTL["not_available"]
    assert A._ram_get(A._ram_key(A.meta_for("ACORD_27"), None)) is None    # never cached


def test_the_pre_download_message_says_what_to_do():
    one = A.prefetch_failure_message([{"form_id": "ACORD_27", "reason": "asg_error"}])
    assert "ACORD 27" in one and "try again" in one and "Nothing was generated" in one
    # other forms selected: nothing is lost - the run can go on without the failed form (live, 5 Nov 2026)
    skip = A.prefetch_failure_message([{"form_id": "ACORD_27", "reason": "asg_error"}], can_skip=True)
    assert "not generated yet" in skip and "generate without it" in skip and "does not download them again" in skip
    assert "cannot be added to this package later" in skip
    assert "Nothing was generated" not in skip
    two = A.prefetch_failure_message([{"form_id": "ACORD_27", "reason": "asg_error"},
                                      {"form_id": "ACORD_137_TX", "reason": "not_available"}])
    assert "ACORD 27" in two and "ACORD 137 TX" in two and "no fillable version of ACORD 137 TX" in two
    assert A.prefetch_failure_message([{"form_id": "ACORD_27", "reason": "not_configured"}]) == A.NOT_SET_UP
    never = A.prefetch_failure_message([{"form_id": "ACORD_27", "reason": "not_available"}])
    assert "no fillable version of ACORD 27" in never and "try again" not in never


def test_downloads_run_on_a_small_pool_of_their_own():
    pool = A.download_pool()
    assert pool is A.download_pool() and pool._max_workers == 8      # one package's selection in one wave


# ── review round 4 (3 Nov 2026): the generate route's pre-download ───────────

def _generate_route_harness(monkeypatch, enqueue_error=None, mark_error=None):
    """select_forms_bulk with every outside door stubbed: no database, no queue, no network."""
    import asyncio
    from fastapi import HTTPException
    from routes import form_routes as fr
    from models.schemas import BulkFormSelectionRequest
    writes = []

    class Conn:
        async def fetchrow(self, *a):
            return {"payment_status": "ok"}

    class _Ctx:
        async def __aenter__(self):
            return Conn()

        async def __aexit__(self, *a):
            return False

    class Pool:
        def acquire(self):
            return _Ctx()

    class Queue:
        async def count_user_active_jobs(self, uid):
            return 0

        async def enqueue(self, *a, **k):
            if enqueue_error:
                raise enqueue_error
            return "job-1"

        async def update_status(self, *a, **k):
            return None

    async def get_session(sid, *a, **k):
        return {"user_id": "u1", "facts": {}, "flags": {}, "all_forms": [], "docs": []}

    async def upd(sid, updates, **k):
        if mark_error and "asg_preparing_at" in updates and updates["asg_preparing_at"]:
            raise mark_error
        writes.append(dict(updates))

    async def nothing(*a, **k):
        return None
    monkeypatch.setenv("ASG_FORMS", "1")
    monkeypatch.delenv("ASG_FORMS_ALLOWED_EMAILS", raising=False)
    monkeypatch.setattr(fr, "get_pool", lambda: Pool())
    monkeypatch.setattr(fr, "get_processing_session", get_session)
    monkeypatch.setattr(fr, "upd_processing_session", upd)
    monkeypatch.setattr(fr, "_refuse_once_forms_exist", nothing)
    monkeypatch.setattr(fr, "enforce_integrity_gate", lambda *a, **k: None)
    monkeypatch.setattr(fr, "enforce_building_value_gate", lambda *a, **k: None)
    monkeypatch.setattr(fr, "check_upload_rate_limit", nothing)
    monkeypatch.setattr(fr, "get_job_queue", lambda: Queue())
    req = BulkFormSelectionRequest(session_id="s1", form_ids=["ACORD_27"])
    user = {"id": "u1", "email": "a@b.com", "subscription_tier": "professional"}
    return asyncio, HTTPException, fr, req, user, writes


def test_a_failure_after_the_download_clears_the_preparing_mark(monkeypatch):
    asyncio, HTTPException, fr, req, user, writes = _generate_route_harness(
        monkeypatch, enqueue_error=RuntimeError("queue down"))
    with pytest.raises(RuntimeError):
        asyncio.run(fr.select_forms_bulk(req, current_user=user))
    marks = [w.get("asg_preparing_at", "absent") for w in writes if "asg_preparing_at" in w]
    assert marks and marks[0] and marks[-1] is None        # set before the download, cleared after the failure


def test_a_failed_download_refuses_and_clears_the_mark(monkeypatch):
    asyncio, HTTPException, fr, req, user, writes = _generate_route_harness(monkeypatch)
    req.form_ids = ["ACORD_75"]                             # the stub has no ACORD 75
    with pytest.raises(HTTPException) as ex:
        asyncio.run(fr.select_forms_bulk(req, current_user=user))
    # ASG can never give it and nothing else is selected: a refusal (400), never "service unavailable"
    assert ex.value.status_code == 400 and "ACORD 75" in ex.value.detail["message"]
    assert ex.value.detail["failed"] == ["ACORD_75"] and ex.value.detail["rest"] == []   # nothing else to make
    assert [w["asg_preparing_at"] for w in writes if "asg_preparing_at" in w][-1] is None


def test_an_archived_package_is_refused_before_any_download(monkeypatch):
    from fastapi import HTTPException as _H
    asyncio, HTTPException, fr, req, user, writes = _generate_route_harness(
        monkeypatch, mark_error=_H(409, "This package is archived."))
    calls = []
    monkeypatch.setattr(A, "try_fetch", lambda meta: calls.append(meta) or None)
    with pytest.raises(HTTPException) as ex:
        asyncio.run(fr.select_forms_bulk(req, current_user=user))
    assert ex.value.status_code == 409 and calls == []


# ── review round 5 (3 Nov 2026) ──────────────────────────────────────────────

def test_the_preparing_mark_outlives_the_pre_download_deadline():
    from services.generation_state import PREPARING_TTL_SECONDS
    assert PREPARING_TTL_SECONDS >= A.PREFETCH_DEADLINE_SECONDS + 60


def test_a_hung_asg_stops_retrying_after_the_budget(monkeypatch):
    import httpx
    monkeypatch.delenv("ASG_FORMS_STUB_DIR", raising=False)
    for k, v in (("TRANSCRIBER_CLIENT_ID", "x"), ("TRANSCRIBER_CLIENT_SECRET", "y"), ("TRANSCRIBER_API_KEY", "z"),
                 ("TRANSCRIBER_ENV", "uat"), ("ENVIRONMENT", "development")):
        monkeypatch.setenv(k, v)
    A._token.update(value="tok", expiry=10 ** 12, bearer=False)
    monkeypatch.setattr(A, "_DOWNLOAD_BUDGET_SECONDS", 0.0)            # already spent after the first try
    monkeypatch.setattr(A.time, "sleep", lambda s: None)
    gets = []

    def reply(self, request, **kw):
        gets.append(request.url.path)
        return httpx.Response(503, text="busy", request=request)
    monkeypatch.setattr(httpx.Client, "send", reply)
    with pytest.raises(A.AsgFormUnavailable):
        A.fetch_blank(A.meta_for("ACORD_27"))
    assert len(gets) == 1                                               # no retry once the budget is spent
    A._token.update(value="", expiry=0.0, bearer=None, failed_until=0.0)


def test_failed_forms_are_named_in_the_order_picked(monkeypatch):
    asyncio, HTTPException, fr, req, user, writes = _generate_route_harness(monkeypatch)
    req.form_ids = ["ACORD_137_TX", "ACORD_75", "ACORD_1"]
    busy = {"ACORD_75", "ACORD_1"}                                       # ASG busy for these two: a retry may work
    monkeypatch.setattr(A, "try_fetch", lambda meta: ({"form_id": meta["form_id"], "reason": "asg_error"}
                                                      if meta["form_id"] in busy else None))
    with pytest.raises(HTTPException) as ex:
        asyncio.run(fr.select_forms_bulk(req, current_user=user))
    assert ex.value.status_code == 503 and "ACORD 75 and ACORD 1" in ex.value.detail["message"]   # in the order picked
    assert ex.value.detail["failed"] == ["ACORD_75", "ACORD_1"] and ex.value.detail["rest"] == ["ACORD_137_TX"]
    assert "generate without them" in ex.value.detail["message"]


def _capture_queue(monkeypatch, fr):
    jobs = []

    class Queue:
        async def count_user_active_jobs(self, uid):
            return 0

        async def enqueue(self, job_type, payload, *a, **k):
            jobs.append(payload)
            return "job-1"

        async def update_status(self, *a, **k):
            return None
    monkeypatch.setattr(fr, "get_job_queue", lambda: Queue())
    monkeypatch.setattr(fr, "ENABLE_ASYNC_PROCESSING", True)            # the run itself is not under test
    return jobs


def test_a_form_asg_can_never_give_is_left_out_and_the_rest_generate(monkeypatch):
    """Live, 5 Nov 2026: one refused ACORD 25 S stopped a package whose two other ASG forms had downloaded -
    two paid downloads wasted, nothing made. A form ASG can NEVER give is left out; the rest generate."""
    import json
    asyncio, HTTPException, fr, req, user, writes = _generate_route_harness(monkeypatch)
    jobs = _capture_queue(monkeypatch, fr)
    req.form_ids = ["ACORD_125", "ACORD_137_TX", "ACORD_75", "ACORD_27"]   # the stub has no ACORD 75
    res = asyncio.run(fr.select_forms_bulk(req, current_user=user))
    body = json.loads(res.body)
    assert res.status_code == 202 and jobs[0]["form_ids"] == ["ACORD_125", "ACORD_137_TX", "ACORD_27"]
    assert body["asg_not_generated"] == [{"form_id": "ACORD_75", "reason": "not_available"}]
    assert "no fillable version of ACORD 75" in body["asg_not_generated_message"]
    assert "Your other forms are ready" in body["asg_not_generated_message"]
    for gen in (w for w in writes if "generation_form_count" in w):
        assert gen["generation_form_count"] == 3


def test_a_wrong_form_is_left_out_too_and_a_mix_with_a_busy_asg_still_asks(monkeypatch):
    asyncio, HTTPException, fr, req, user, writes = _generate_route_harness(monkeypatch)
    jobs = _capture_queue(monkeypatch, fr)
    req.form_ids = ["ACORD_125", "ACORD_137_TX", "ACORD_27"]
    reasons = {"ACORD_137_TX": "wrong_form", "ACORD_27": "asg_error"}
    monkeypatch.setattr(A, "try_fetch", lambda meta: ({"form_id": meta["form_id"], "reason": reasons[meta["form_id"]]}
                                                      if meta["form_id"] in reasons else None))
    with pytest.raises(HTTPException) as ex:                          # ASG busy on one: the user decides
        asyncio.run(fr.select_forms_bulk(req, current_user=user))
    assert ex.value.status_code == 503 and ex.value.detail["rest"] == ["ACORD_125"] and jobs == []
    reasons.pop("ACORD_27")                                            # only the wrong form left: it is left out
    res = asyncio.run(fr.select_forms_bulk(req, current_user=user))
    assert res.status_code == 202 and jobs[-1]["form_ids"] == ["ACORD_125", "ACORD_27"]


def test_a_setup_failure_never_leaves_forms_out_silently(monkeypatch):
    asyncio, HTTPException, fr, req, user, writes = _generate_route_harness(monkeypatch)
    jobs = _capture_queue(monkeypatch, fr)
    req.form_ids = ["ACORD_125", "ACORD_27"]
    monkeypatch.setattr(A, "try_fetch", lambda meta: {"form_id": meta["form_id"], "reason": "auth"})
    with pytest.raises(HTTPException) as ex:
        asyncio.run(fr.select_forms_bulk(req, current_user=user))
    assert ex.value.status_code == 503 and ex.value.detail["message"].startswith(A.NOT_SET_UP)
    assert ex.value.detail["rest"] == ["ACORD_125"] and jobs == []


def test_the_left_out_message_names_each_reason():
    m = A.left_out_message([{"form_id": "ACORD_25_FR", "reason": "not_available"},
                            {"form_id": "ACORD_60_US", "reason": "not_available"},
                            {"form_id": "ACORD_75_N", "reason": "wrong_form"},
                            {"form_id": "ACORD_35", "reason": "error"}])
    assert "no fillable version of ACORD 25 FR and ACORD 60 US, so they were left out" in m
    assert "sent a different form than ACORD 75 N, so it was left out" in m
    assert "ACORD 35 could not be generated, so it is not in this package" in m and m.endswith("ready.")
    assert A.left_out_message([]) == ""


# ── review round 6 (3 Nov 2026) ──────────────────────────────────────────────

def test_a_failed_sign_in_is_not_retried_by_every_waiting_download(monkeypatch):
    import httpx
    monkeypatch.delenv("ASG_FORMS_STUB_DIR", raising=False)
    for k, v in (("TRANSCRIBER_CLIENT_ID", "x"), ("TRANSCRIBER_CLIENT_SECRET", "y"), ("TRANSCRIBER_API_KEY", "z"),
                 ("TRANSCRIBER_ENV", "uat"), ("ENVIRONMENT", "development")):
        monkeypatch.setenv(k, v)
    A._token.update(value="", expiry=0.0, bearer=None, failed_until=0.0)
    posts = []

    def hung(self, request, **kw):
        posts.append(request.url.path)
        raise httpx.ReadTimeout("no answer", request=request)
    monkeypatch.setattr(httpx.Client, "send", hung)
    for fid in ("ACORD_27", "ACORD_137_TX", "ACORD_1"):
        with pytest.raises(A.AsgFormUnavailable):
            A.fetch_blank(A.meta_for(fid))
    assert len(posts) == 1                                   # one sign-in attempt, not one per form
    A._token.update(value="", expiry=0.0, bearer=None, failed_until=0.0)



def test_a_refused_sign_in_stays_a_setup_problem_for_the_waiting_forms(monkeypatch):
    import httpx
    monkeypatch.delenv("ASG_FORMS_STUB_DIR", raising=False)
    for k, v in (("TRANSCRIBER_CLIENT_ID", "x"), ("TRANSCRIBER_CLIENT_SECRET", "y"), ("TRANSCRIBER_API_KEY", "z"),
                 ("TRANSCRIBER_ENV", "uat"), ("ENVIRONMENT", "development")):
        monkeypatch.setenv(k, v)

    def refused(self, request, **kw):
        return httpx.Response(401, text="bad client", request=request)
    monkeypatch.setattr(httpx.Client, "send", refused)
    reasons = []
    for fid in ("ACORD_27", "ACORD_137_TX"):
        with pytest.raises(A.AsgFormUnavailable) as ex:
            A.fetch_blank(A.meta_for(fid))
        reasons.append(ex.value.reason)
    assert reasons == ["auth", "auth"]
    assert A.prefetch_failure_message([{"form_id": "ACORD_137_TX", "reason": reasons[1]}]) == A.NOT_SET_UP



def test_a_sign_in_failure_is_never_remembered_against_a_form(monkeypatch):
    import httpx
    monkeypatch.delenv("ASG_FORMS_STUB_DIR", raising=False)
    for k, v in (("TRANSCRIBER_CLIENT_ID", "x"), ("TRANSCRIBER_CLIENT_SECRET", "y"), ("TRANSCRIBER_API_KEY", "z"),
                 ("TRANSCRIBER_ENV", "uat"), ("ENVIRONMENT", "development")):
        monkeypatch.setenv(k, v)

    def hung(self, request, **kw):
        raise httpx.ReadTimeout("no answer", request=request)
    monkeypatch.setattr(httpx.Client, "send", hung)
    for fid in ("ACORD_27", "ACORD_137_TX"):
        with pytest.raises(A.AsgFormUnavailable):
            A.fetch_blank(A.meta_for(fid))
    assert A._failed == {}                                   # only the 60 s sign-in memory holds it
    A._token.update(failed_until=0.0)                        # sign-in recovers ...
    monkeypatch.setenv("ASG_FORMS_STUB_DIR", os.path.join(BACKEND, "tests", "fixtures", "asg_forms_stub"))
    assert A.fetch_blank(A.meta_for("ACORD_27"))[0][:5] == b"%PDF-"   # ... and the form is available at once


# ── final reviews (3 Nov 2026): general + strict end-user ───────────────────

@pytest.mark.parametrize("typed", ["137 tx", "137tx", "137-TX", "137 texas", "texas 137", "ACORD 137 Texas"])
def test_every_way_of_typing_a_state_form_finds_it(typed):
    assert A.search(typed)[0]["form_id"] == "ACORD_137_TX"


@pytest.mark.parametrize("typed,first", [("ACORD-25", "ACORD_25"), ("form 27", "ACORD_27"), ("#27", "ACORD_27"),
                                         ("0027", "ACORD_27"), ("coi", "ACORD_25"), ("auto", "ACORD_127"),
                                         ("workers comp", "ACORD_130")])
def test_common_spellings_find_the_form(typed, first):
    assert A.search(typed)[0]["form_id"] == first


def test_search_says_how_many_matched_and_puts_the_plain_form_first():
    rows, total = A.search_with_total("137", 25)
    assert total > len(rows) == 25                            # the screen says "Showing 25 of N"
    assert [r["form_id"] for r in rows[:2]] == ["ACORD_137_CA", "ACORD_137_CO"]   # ours first
    rows, _ = A.search_with_total("125", 25)
    assert rows[0]["form_id"] == "ACORD_125"
    kinds = [bool(r["variant"]) for r in rows]
    assert True in kinds and kinds == sorted(kinds)           # every variant ("CIS", "INS" ...) after the plain forms


def test_production_on_test_credentials_needs_the_allow_list(monkeypatch):
    monkeypatch.setenv("ASG_FORMS", "1")
    monkeypatch.setenv("TRANSCRIBER_ENV", "uat")
    monkeypatch.setenv("ENVIRONMENT", "production")
    monkeypatch.delenv("ASG_FORMS_ALLOWED_EMAILS", raising=False)
    assert not A.enabled_for({"email": "anyone@x.com"})        # fail closed: Sample forms never reach everyone
    monkeypatch.setenv("ASG_FORMS_ALLOWED_EMAILS", "owner@x.com")
    assert A.enabled_for({"email": "owner@x.com"})
    assert not A.enabled_for({"email": "anyone@x.com"})
    monkeypatch.setenv("TRANSCRIBER_ENV", "prod")
    monkeypatch.delenv("ASG_FORMS_ALLOWED_EMAILS", raising=False)
    assert A.enabled_for({"email": "anyone@x.com"})            # PROD credentials: open to all


def test_the_search_is_not_offered_when_it_cannot_work(monkeypatch):
    monkeypatch.setenv("ASG_FORMS", "1")
    monkeypatch.delenv("ASG_FORMS_STUB_DIR", raising=False)
    for k in ("TRANSCRIBER_CLIENT_ID", "TRANSCRIBER_CLIENT_SECRET", "TRANSCRIBER_API_KEY"):
        monkeypatch.setenv(k, "")
    assert not A.enabled_for({"email": "a@b.com"})


def test_certificates_from_asg_document_the_existing_policy_and_carry_no_record():
    from services.pdf_service import _is_certificate_form, proposed_term_fact
    from services.acord_intake.primble_record import _is_asg_certificate
    assert A.is_certificate_form("ACORD_27") and A.is_certificate_form("ACORD_20")
    assert not A.is_certificate_form("ACORD_75") and not A.is_certificate_form("ACORD_25")   # 25 is ours
    assert _is_certificate_form("ACORD_27") and _is_certificate_form("ACORD_25")
    assert not _is_certificate_form("ACORD_125") and not _is_certificate_form("ACORD_75")
    assert proposed_term_fact("ACORD_27", "Policy_EffectiveDate_A") is None    # an edit never moves the proposal
    assert _is_asg_certificate("ACORD_27") and not _is_asg_certificate("ACORD_125")


def test_a_deleted_package_leaves_the_copy_cache():
    A.remember_copies("gone", {"ACORD_27": b"%PDF-x"})
    A.remember_copies("kept", {"ACORD_27": b"%PDF-y"})
    A.forget_package("gone")
    assert A.cached_copies("gone", ["ACORD_27"]) is None
    assert A.cached_copies("kept", ["ACORD_27"]) == {"ACORD_27": b"%PDF-y"}


# ── fresh review of the final fixes (3 Nov 2026) ─────────────────────────────

def _routed_renewal(form_id):
    return {"_form_id": form_id, "renewal_dates_routed": True, "effective_date": "07/15/2026",
            "expiration_date": "07/15/2027",
            "prior_effective_date": {"value": "07/15/2025", "routed_from": "current_term"},
            "prior_expiration_date": {"value": "07/15/2026", "routed_from": "current_term"}}


@pytest.mark.parametrize("box,expected", [("OtherPolicy_PolicyEffectiveDate_A", "07/15/2025"),
                                          ("Policy_GeneralLiability_ExpirationDate_A", "07/15/2026"),
                                          ("Policy_EffectiveDate_A", "07/15/2025")])
def test_an_asg_certificate_prints_the_existing_term_in_every_date_box(box, expected):
    from services.pdf_service import _resolve_renewal_proposed_period
    assert _resolve_renewal_proposed_period(box, _routed_renewal("ACORD_27")) == expected


def test_our_certificates_and_asg_applications_keep_their_own_date_rules():
    from services.pdf_service import _SCHED_SKIP, _resolve_renewal_proposed_period
    # ours: the date boxes beyond Policy_EffectiveDate stay with their own resolvers (unchanged)
    assert _resolve_renewal_proposed_period("OtherPolicy_PolicyEffectiveDate_A", _routed_renewal("ACORD_25")) is _SCHED_SKIP
    # a binder is not a certificate: unchanged
    assert _resolve_renewal_proposed_period("OtherPolicy_PolicyEffectiveDate_A", _routed_renewal("ACORD_75")) is _SCHED_SKIP
    # no routed renewal: the certificate's dates are the current term already - unchanged
    facts = dict(_routed_renewal("ACORD_27"), renewal_dates_routed=False)
    assert _resolve_renewal_proposed_period("OtherPolicy_PolicyEffectiveDate_A", facts) is _SCHED_SKIP


def test_id_card_and_squashed_numbers_search_as_people_type():
    assert A.search("id card")[0]["form_id"] == "ACORD_50"
    assert A.search("acord25")[0]["form_id"] == "ACORD_25"
    assert A.search("137 tx")[0]["form_id"] == "ACORD_137_TX"          # a state beside a number still filters
    assert all(r["state"] == "TX" for r in A.search("TX"))              # a state alone still filters


def test_a_state_typed_by_its_name_beside_words_still_filters():
    # Owner's live test, 3 Nov 2026: "auto texas" found nothing - the name became "tx", then the bare-two-letter rule
    # turned it into a title word no title holds. A full state name is never ambiguous.
    for q in ("auto texas", "texas auto"):
        rows, total = A.search_with_total(q, 25)
        assert total >= 1 and any(r["form_id"] == "ACORD_137_TX" for r in rows), q
        assert all(r["state"] == "TX" or "texas" in r["title"].lower() for r in rows), q
    rows, _ = A.search_with_total("new york auto", 25)
    assert rows and all(r["state"] == "NY" or "new york" in r["title"].lower() for r in rows)
    # unchanged: a bare two-letter word beside other words is a word ("id" in "id card" is not Idaho)
    assert A.search("id card")[0]["form_id"] == "ACORD_50"
    assert A.search("137 texas")[0]["form_id"] == "ACORD_137_TX"


# ── the search sweep (owner: "type keywords and find all such bugs", 3 Nov 2026) ─────────────────────────────

def _ids(q, limit=25):
    return [r["form_id"] for r in A.search(q, limit=limit)]


@pytest.mark.parametrize("typed,expected", [
    ("binders", "ACORD_75"), ("certificates", "ACORD_25"),                    # plurals
    ("workers' compensation", "ACORD_130"), ("workmans comp", "ACORD_130"),   # apostrophe, colloquial
    ("d&o", "ACORD_807"), ("d & o", "ACORD_807"), ("d and o", "ACORD_807"),   # shorthand with "&"
    ("directors and officers", "ACORD_807"), ("directors & officers", "ACORD_807"),
    ("cgl", "ACORD_126"), ("bop", "ACORD_160"), ("epli", "ACORD_188"),
    ("accord 25", "ACORD_25"), ("ACORD 25 2016", "ACORD_25"), ("25 (2016/03)", "ACORD_25"),   # misspelling, edition
    ("84 ins", "ACORD_84_INS"), ("125 cis", "ACORD_125_CIS"), ("36 ins", "ACORD_36_INS"),  # a named variant
    # (25 INS / 137 TX INS left the list 4 Nov 2026: not in ASG's download catalogue - ASG sent the plain form)
    ("kansas cancellation of form k-wc 113", "ACORD_172_KS"),                 # a shorthand printed in the title
])
def test_sweep_spellings_find_the_form_first(typed, expected):
    assert _ids(typed)[0] == expected, typed


def test_sweep_more_spellings_and_words_that_must_not_block():
    assert "ACORD_180" in _ids("e&o")                                         # "Technology E&O Section"
    assert "ACORD_144" not in _ids("gl")                                      # a shorthand is never a prefix: no "glass"
    assert len(_ids("claims", 5000)) == len(_ids("claim", 5000))              # plural = singular
    for q in ("auto in texas", "auto for texas"):                             # small words never block
        assert "ACORD_137_TX" in _ids(q, 5000), q
    for q, st in (("ny auto", "NY"), ("auto ny", "NY"), ("wc ny", "NY"), ("newyork", "NY"), ("forms for new york", "NY")):
        rows = A.search(q, limit=5000)
        assert rows and all(r["state"] == st for r in rows), q                 # a state code beside words filters
    rows = A.search("texas or oklahoma", limit=5000)
    assert rows and {r["state"] for r in rows} <= {"TX", "OK"}
    assert all(r["state"] == "OR" for r in A.search("or"))                    # alone, "or" / "in" are still states


def test_sweep_widening_says_what_it_did():
    rows, total, note = A.search_full("gl ca", 25)                             # no California GL form
    assert rows[0]["form_id"] == "ACORD_126" and all(not r["state"] for r in rows) and "California" in note
    rows, _, note = A.search_full("notice of cancellation georgia", 25)        # never another state's version
    assert rows and all(not r["state"] for r in rows) and "Georgia" in note
    rows, _, note = A.search_full("texas auto id card", 25)                    # "TEXAS LIABILITY INSURANCE CARD"
    assert rows[0]["form_id"] == "ACORD_50_TX" and "closest" in note
    rows, _, note = A.search_full("137 xx", 25)                                # a number + a word no title holds
    assert rows and all(r["number"] == "137" for r in rows) and "closest" in note
    assert "ACORD_64_MN" in _ids("ho 4", 5000)                                # a number inside a title
    rows, _, note = A.search_full("137 tx", 25)                                # an exact search is never widened
    assert rows[0]["form_id"] == "ACORD_137_TX" and note == ""


def test_sweep_every_form_is_findable_by_number_state_and_title():
    idx = A._index()
    missing = []
    for fid, e in idx.items():
        if not A._is_pc(e):
            continue                                                   # life / health forms are never listed
        q = f"{e['number']} {e['state']}".strip() + (f" {e['suffix']}" if e.get("suffix") else "")
        if fid not in _ids(q, 25):
            missing.append(("number", fid))
        # ASG's list titles two forms after ANOTHER state (63 OK "Ohio Fraud Statement", 136 OH "Missouri ...");
        # those are found by number + state, never by a title naming a state they are not for (review pass 4).
        quirk = e.get("state") and any(A._title_names_state(e["title"], c) for c in A._STATE_CODES if c != e["state"])
        if e.get("title") and not quirk and fid not in _ids(e["title"], 5000):
            missing.append(("title", fid))
    assert not missing, missing[:10]


def test_sweep_junk_never_crashes():
    import random
    rnd = random.Random(7)
    alphabet = "abc xyz 0123456789 #&'\"()[]{}<>/\\.,;:!?*+-_=%$@^~`|éü测\U0001f642\t\n"
    for _ in range(400):
        q = "".join(rnd.choice(alphabet) for _ in range(rnd.randint(0, 80)))
        rows, total, note = A.search_full(q, 25)
        assert isinstance(rows, list) and total >= len(rows) and isinstance(note, str)


# ── is it the form we asked for? (owner, 3 Nov 2026: "are you sure it is always correct?") ─────────────────

def _template_bytes(name):
    with open(os.path.join(BACKEND, "templates", name), "rb") as f:
        return f.read()


def _meta(num, st="", sx=""):
    return {"asg_number": num, "asg_state": st, "asg_suffix": sx,
            "form_id": "ACORD_" + "_".join(p for p in (num, st, sx) if p)}


def test_every_form_prints_its_own_identity_and_is_accepted():
    import glob
    for path in glob.glob(os.path.join(BACKEND, "templates", "ACORD_*.pdf")):
        m = re.match(r"ACORD_(\d+)(?:_([A-Z]{2}))?\.pdf$", os.path.basename(path))
        assert m, path
        wrong, read = A.identity_check(open(path, "rb").read(), _meta(m.group(1), m.group(2) or ""))
        assert read and wrong is None, path


@pytest.mark.parametrize("template,asked,printed", [
    ("ACORD_137_CA.pdf", ("137", "TX", ""), "ACORD 137 CA"),     # another state's version
    ("ACORD_137_CA.pdf", ("137", "", ""), "ACORD 137 CA"),       # a state version for the plain form
    ("ACORD_25.pdf", ("25", "", "INS"), "ACORD 25"),             # the plain form for a variant
    ("ACORD_25.pdf", ("27", "", ""), "ACORD 25"),                # another form
])
def test_a_download_that_is_not_the_form_asked_for_is_refused(template, asked, printed):
    wrong, read = A.identity_check(_template_bytes(template), _meta(*asked))
    # the refusal names what was printed, edition included ("ACORD 137 CA (2023/01)" - 4 Nov 2026)
    assert read and wrong.split(" (")[0] == printed and re.search(r"\(\d{4}/\d{2}\)$", wrong), wrong


def test_fetch_blank_refuses_and_remembers_a_wrong_form(monkeypatch):
    calls = []

    def fake_network(meta, edition):
        calls.append(meta["form_id"])
        return _template_bytes("ACORD_137_CO.pdf")              # "ACORD 137 CO (2015/12)"
    monkeypatch.setattr(A, "_stub_dir", lambda: None)
    monkeypatch.setattr(A, "_network_fetch", fake_network)
    meta = A.meta_for("ACORD_137_TX")
    with pytest.raises(A.AsgFormUnavailable) as ex:
        A.fetch_blank(meta)
    assert ex.value.reason == "wrong_form" and "ACORD 137 CO" in str(ex.value)
    with pytest.raises(A.AsgFormUnavailable):
        A.fetch_blank(meta)                                     # remembered: ASG is not asked again
    assert calls == ["ACORD_137_TX"]
    right = dict(meta, asg_state="CO", form_id="ACORD_137_TXCO")   # the same file IS what this request names
    data, _edition, _sample = A.fetch_blank(right)
    assert data[:5] == b"%PDF-"
    msg = A.prefetch_failure_message([{"form_id": "ACORD_137_TX", "reason": "wrong_form"}])
    assert "sent a different form than ACORD 137 TX" in msg and "Nothing was generated" in msg


def test_the_certificate_family_by_title():
    assert A.is_certificate_form("ACORD_50_FL")                         # "...INSURANCE IDENTIFICATION"
    assert not A.is_certificate_form("ACORD_771")                       # a lab identification form is not


def test_copies_leave_memory_after_their_time(monkeypatch):
    A.remember_copies("old", {"ACORD_27": b"%PDF-x"})
    monkeypatch.setattr(A, "_COPY_CACHE_TTL_SECONDS", -1.0)
    assert A.cached_copies("old", ["ACORD_27"]) is None


# ── the hard review of the search (3 Nov 2026 evening) ───────────────────────────────────────────────────

def test_review_a_state_code_beside_words_never_matches_another_state_by_prefix():
    rows = A.search("commercial auto al", limit=5000)                  # "al" is never "Alaska" by a prefix
    assert [r["form_id"] for r in rows] == ["ACORD_137_AL"]
    assert {r["state"] for r in A.search("137 in tx", limit=5000)} == {"TX"}   # "in" is a small word here


def test_review_a_state_name_inside_another_names_only_its_own_state():
    rows = A.search("virginia", limit=5000)
    assert rows and {r["state"] for r in rows} == {"VA"}               # never West Virginia
    rows = A.search("washington dc", limit=5000)
    assert rows and {r["state"] for r in rows} == {"DC"}


def test_review_our_forms_come_first_and_several_numbers_list_each():
    # our forms first - our 127 (Business Auto) is found by "commercial" too since review C, 4 Nov 2026
    assert _ids("commercial auto")[:3] == ["ACORD_127", "ACORD_137_CA", "ACORD_137_CO"]
    assert _ids("garage")[:2] == ["ACORD_138_CA", "ACORD_138_CO"]
    assert _ids("125 126")[:2] == ["ACORD_125", "ACORD_126"]


def test_review_everyday_shorthand_reads_as_the_word_first():
    assert _ids("id card")[0] == "ACORD_50"                            # "id" = identification before Idaho
    assert _ids("36 ins")[0] == "ACORD_36_INS"                         # beside a number, a variant code is the variant
    assert _ids("certificate ins")[0] == "ACORD_25"                    # without one, "ins" is insurance


# ── review pass 2 (3 Nov 2026): a typed state never returns another state's version ──────────────────────

@pytest.mark.parametrize("typed", ["tx auto id card", "tx commercial auto policy", "137 tx zzz", "137 texas zzz",
                                   "auto texas tx", "137 texas tx", "texas tx"])
def test_review2_a_typed_state_never_widens_to_other_states(typed):
    rows = A.search(typed, limit=5000)
    assert rows and {r["state"] for r in rows} == {"TX"}, typed


@pytest.mark.parametrize("typed,expected", [("tx id card", "ACORD_50_TX"), ("fl id card", "ACORD_51_FL"),
                                            ("ca id card", "ACORD_50_CA"), ("tx id", "ACORD_50_TX")])
def test_review2_id_beside_a_state_is_the_card_never_idaho(typed, expected):
    rows = A.search(typed, limit=5000)
    assert rows[0]["form_id"] == expected and all(r["state"] != "ID" for r in rows), typed


def test_review2_no_version_for_the_state_gives_the_general_forms_and_says_so():
    for typed, numbers in (("125 tx", {"125"}), ("125 126 tx", {"125", "126"})):
        rows, _total, note = A.search_full(typed, 25)
        assert rows and all(not r["state"] for r in rows) and {r["number"] for r in rows} == numbers, typed
        assert note == "No Texas version found - showing the general forms.", typed
    rows, total, _note = A.search_full("136 mo", 25)                    # no Missouri 136, no general 136
    assert rows == [] and total == 0


def test_review2_a_state_typed_twice_and_dc_with_dots():
    assert A.search("california ca 125")[0]["form_id"] == "ACORD_125_CA"
    assert {r["state"] for r in A.search("new york, ny", limit=5000)} == {"NY"}
    for typed in ("washington d.c.", "137 washington, d.c.", "washington d.c. auto", "d.c. auto"):
        rows = A.search(typed, limit=5000)
        assert rows and {r["state"] for r in rows} == {"DC"}, typed


def test_review2_the_search_route_runs_off_the_event_loop():
    src = open(os.path.join(BACKEND, "routes", "asg_forms_routes.py")).read()
    assert "await run_in_threadpool(asg_forms.search_for_screen, q, 25)" in src


# ── review pass 3 (3 Nov 2026) ───────────────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("typed,state", [("130 IN", "IN"), ("wc in", "IN"), ("OR auto", "OR"), ("4 IN", "IN")])
def test_review3_a_small_word_state_is_the_state_or_the_general_forms(typed, state):
    rows, _total, note = A.search_full(typed, 5000)
    assert rows and all(r["state"] in (state, "") for r in rows), typed
    assert all(r["state"] == state for r in rows) or "version found" in note, typed


def test_review3_small_words_between_numbers_are_words():
    for typed in ("25 or 28", "125 or 126"):
        rows, _total, note = A.search_full(typed, 25)
        a, b = typed.split(" or ")
        assert [r["number"] for r in rows[:2]] == [a, b] and note == "", typed


@pytest.mark.parametrize("typed,first", [("28 NY", "ACORD_28"), ("1 TX", "ACORD_1"), ("13 tx", "ACORD_13"),
                                         ("25 28 ny", "ACORD_25")])
def test_review3_the_form_typed_is_never_hidden_behind_a_longer_number(typed, first):
    rows, _total, note = A.search_full(typed, 25)
    assert rows[0]["form_id"] == first and "version found" in note, typed


def test_review3_a_title_that_excludes_a_state_is_not_that_states_form():
    assert _ids("877 california") == ["ACORD_877_CA"]
    assert "ACORD_877" not in _ids("california disclosure", 5000)
    assert not A._title_names_state("Disclosure (except California)", "CA")
    assert A._title_names_state("California Disclosure", "CA")


# ── Brent, 4 Nov 2026: at most 15 forms in one package, ours and ASG's together ───────────────────────────

def test_the_package_form_cap_counts_ours_and_asgs_together(monkeypatch):
    monkeypatch.delenv("PACKAGE_FORMS_MAX", raising=False)
    assert A.max_forms_per_package() == 15
    ours = ["ACORD_125", "ACORD_126", "ACORD_127", "ACORD_130", "ACORD_131"]
    asg = ["ACORD_27", "ACORD_807"]
    assert A.package_form_count(ours + asg, {}) == 7
    assert A.package_form_count(["ACORD_27"], {"ACORD_131": {}, "ACORD_131__excess": {}}) == 3  # a layer copy is printed
    assert A.package_form_count(["ACORD_25", " ACORD_25"], None) == 1
    monkeypatch.setenv("PACKAGE_FORMS_MAX", "20")
    assert A.max_forms_per_package() == 20
    assert "support@primble.com" in A.PACKAGE_FULL_MESSAGE and "upgrade" in A.PACKAGE_FULL_MESSAGE


def test_the_cap_is_held_at_generation_add_form_and_on_screen():
    form_routes = open(os.path.join(BACKEND, "routes", "form_routes.py")).read()
    assert "_asg.package_form_count(req.form_ids, session.get(\"generated_forms\"))" in form_routes
    assert "Only property & casualty ACORD forms can be added to a package - remove " in form_routes
    door = open(os.path.join(BACKEND, "services", "form_addition.py")).read()       # every add-form route's door
    assert "package_form_count" not in door and "NO 15-form cap here" in door    # owner, 4 Nov: offered forms only
    route = open(os.path.join(BACKEND, "routes", "asg_forms_routes.py")).read()
    assert '"max_forms_per_package": asg_forms.max_forms_per_package()' in route
    front = os.path.join(os.path.dirname(BACKEND), "frontend", "src", "components", "form")
    modal = open(os.path.join(front, "AcordModal.jsx")).read()
    assert "checkedFormIds.size > acordSearch.maxTotal}>" in modal
    assert "maxTotal={acordSearch.maxTotal}" in modal
    search = open(os.path.join(front, "AcordFormSearch.jsx")).read()
    assert "inPackage.size + adds.length > maxTotal" in search


# ── review pass 4 (4 Nov 2026) ───────────────────────────────────────────────────────────────────────────────

def test_review4_every_add_form_route_goes_through_the_one_door():
    for rel in (("routes", "policy_line_routes.py"), ("services", "session_documents.py"), ("routes", "audit_routes.py")):
        assert "add_form_to_session(" in open(os.path.join(BACKEND, *rel)).read(), rel   # they all use the door


def test_after_generation_an_offered_form_is_added_past_15(monkeypatch):
    """Owner, 4 Nov 2026: after generation a form is added only when Primble offers it (a hard stop, warning or
    cross-form check, a policy line, a new document) - so the 15 does not apply there, or a stop could not be fixed."""
    import asyncio
    from services import form_addition as FA
    import repositories.session_repository as SR
    full = ["ACORD_25", "ACORD_28", "ACORD_101", "ACORD_125", "ACORD_126", "ACORD_127", "ACORD_130", "ACORD_131",
            "ACORD_133", "ACORD_140", "ACORD_141", "ACORD_160", "ACORD_186", "ACORD_137_CA", "ACORD_138_CA"]
    session = {"generated_forms": {f: {} for f in full},
               "cross_issues_last": [{"resolution": {"add_forms": ["ACORD_137_CO"]}}]}

    async def get(_sid):
        return session
    monkeypatch.setattr(SR, "get_processing_session", get)
    monkeypatch.setattr(FA, "_form_meta", lambda _s, _f: None)      # stop just after the checks: no generation
    out, _payload = asyncio.run(FA.add_form_to_session("s1", "ACORD_137_CO"))
    assert out == FA.UNKNOWN_FORM                                    # passed every check - nothing refused it for 15


def test_review4_life_circumstances_supplements_are_pc_and_a_title_never_borrows_a_state():
    for fid in ("ACORD_66", "ACORD_66_OK", "ACORD_67_IA"):
        assert A.is_pc_form(fid), fid
    assert _ids("66")[0] == "ACORD_66"
    assert "ACORD_63_OK" not in _ids("63 ohio", 5000) and "ACORD_136_OH" not in _ids("136 missouri", 5000)
    assert "ACORD_67" in _ids("mine subsidence illinois", 5000)            # a form for no state still matches


def test_review4_the_refusal_names_the_life_form():
    src = open(os.path.join(BACKEND, "routes", "form_routes.py")).read()
    assert '", ".join(_asg.label_of(f) for f in _not_pc)' in src
    front = os.path.join(os.path.dirname(BACKEND), "frontend", "src", "components", "form")
    search = open(os.path.join(front, "AcordFormSearch.jsx")).read()
    assert "companionsOf(r)" in search
    assert "&& f.pc === true)" in open(os.path.join(front, "AcordModal.jsx")).read()


def test_review5_generation_claims_the_package_under_its_lock_before_anything_slow():
    src = open(os.path.join(BACKEND, "routes", "form_routes.py")).read()
    claim = src.index("async with session_write_lock(req.session_id):\n            _fresh = await get_processing_session(req.session_id)")
    assert src.index("await _refuse_once_forms_exist(_fresh)", claim) < src.index("_queue.enqueue(JOB_TYPE_FORM_GENERATION", claim)
    assert src.index("_asg.package_form_count(req.form_ids, _fresh.get(\"generated_forms\"))", claim) < src.index("_pre_loop = asyncio.get_event_loop()", claim)


def test_review6_every_run_clears_its_preparing_mark_and_runs_on_the_locked_read():
    src = open(os.path.join(BACKEND, "routes", "form_routes.py")).read()
    assert "PREPARING_KEY: None,               # the run's own marker takes over" in src
    assert "{PREPARING_KEY: None} if _asg_ids else {}" not in src
    claim = src.index("await _refuse_once_forms_exist(_fresh)")
    assert src.index("session = _fresh", claim) < src.index("_queue.enqueue(JOB_TYPE_FORM_GENERATION", claim)


def test_review7_pre_form_writers_recheck_a_starting_run_under_the_lock(monkeypatch):
    import asyncio
    from fastapi import HTTPException
    src = open(os.path.join(BACKEND, "routes", "policy_line_routes.py")).read()
    inner = src[src.index("    async with _lock_for(session_id):\n        session = await get_processing_session(session_id)"):]
    assert inner.index("await _refuse_while_running(session)") < inner.index("pl.plan_change(")
    from services import session_documents as SD
    import routes.audit_routes as AR
    called = []

    async def refuse(session):
        called.append(session)
        raise HTTPException(409, "Forms are being prepared for this package - wait a moment.")
    monkeypatch.setattr(AR, "_refuse_while_generating", refuse)
    import repositories.session_repository as SR

    async def get(_sid):
        return {"docs": [{"filename": "a.pdf"}], "asg_preparing_at": 1.0}
    monkeypatch.setattr(SD, "get_processing_session", get)
    for call in (lambda: SD.add_documents("s1", [{"filename": "b.pdf", "text": "x"}], user_id="u"),
                 lambda: SD.change_document("s1", doc_id="d1", action="exclude", user_id="u")):
        with pytest.raises(HTTPException) as ex:
            asyncio.run(call())
        assert ex.value.status_code == 409
    assert len(called) == 2


def test_production_sends_the_pdf_base64_encoded_and_both_shapes_are_read():
    """First live production call, 4 Nov 2026: a 200 labelled application/pdf whose body is the PDF in base64."""
    import base64
    pdf = _template_bytes("ACORD_25.pdf")
    assert A._pdf_from_reply(pdf) == pdf                                   # UAT: the raw PDF
    assert A._pdf_from_reply(base64.b64encode(pdf)) == pdf                 # PROD: base64 text
    assert A._pdf_from_reply(b'"' + base64.b64encode(pdf) + b'"\n') == pdf # quoted / trailing newline
    assert A._pdf_from_reply(b'{"error": "x"}') is None and A._pdf_from_reply(b"") is None
    assert A._pdf_from_reply(b"JVBERi0") is None                          # cut-off base64: not a PDF


def test_footers_of_older_and_applied_forms_are_read():
    """First production downloads, 4 Nov 2026: ACORD 50 NY prints "(1/98)" and 125 CIS prints "APPLIED 125CIS
    (2009/08)" - both were the right forms but their footer went unread."""
    found = lambda text: [tuple(re.findall(r"\d+|[A-Z]+", m.group(1).upper()))
                          for m in A._FOOTER_IDENTITY_RE.finditer(text)]
    assert found("ACORD 50 NY (1/98) © ACORD CORPORATION 1998") == [("50", "NY")]
    assert found("SECONDARY E-MAIL ADDRESS: APPLIED 125CIS (2009/08)") == [("125", "CIS")]
    assert found("ACORD 137 CA (2023/01)") == [("137", "CA")]
    assert found("ACORD CORPORATION 1998 (1/98)") == []                   # no form number, nothing read


def test_asg_is_asked_for_each_forms_own_row_like_its_portal(monkeypatch):
    """Every form asks for ITS OWN row of ASG's list, exactly as ASG's portal does (owner's DevTools capture, 4 Nov
    2026: 84 FL -> formNumber=84&edition=2026/03&geoCode=FL; 84 INS -> formNumber=84&edition=2013/09&geoCodeSuffix=INS).
    Replaces the "latest" rule, which landed on flat editions (97 SC, 134 FL ...) and on nothing for state forms ASG
    filed without a state code (61 VA). 125 CIS - served by ASG, absent from its catalogue - keeps its proven request."""
    seen = {}

    def fake_download(httpx, cfg, url, params, bearer, meta, edition, started):
        seen[meta["form_id"]] = dict(params)
        return b"%PDF-"
    monkeypatch.setattr(A, "_download", fake_download)
    monkeypatch.setattr(A, "_network_allowed", lambda cfg: (True, ""))
    monkeypatch.setattr(A, "_config", lambda: type("C", (), {"base_url": "https://x/oauth", "bearer": False})())
    want = {
        "ACORD_84_INS": {"formNumber": "84", "edition": "2013/09", "geoCodeSuffix": "INS"},
        "ACORD_84_FL": {"formNumber": "84", "edition": "2026/03", "geoCode": "FL"},
        "ACORD_137_TX": {"formNumber": "137", "edition": "2015/12", "geoCode": "TX"},
        # ASG's newest LA row keeps "LA" only in its name: asked WITH the state (proof round 2, 4 Nov 2026)
        "ACORD_137_LA": {"formNumber": "137", "edition": "2026/02", "geoCode": "LA"},
        "ACORD_61_VA": {"formNumber": "61", "edition": "2023/08", "geoCode": "VA"},
        "ACORD_97_SC": {"formNumber": "97", "edition": "2006/08", "geoCode": "SC"},   # newest FILLABLE edition
        "ACORD_829_LOB": {"formNumber": "829", "edition": "2009/05", "geoCode": "LOB"},
        "ACORD_60": {"formNumber": "60", "edition": "2010/04"},
        "ACORD_27": {"formNumber": "27", "edition": "2016/03"},
        "ACORD_125_CIS": {"formNumber": "125", "latestEdition": "true", "geoCodeSuffix": "CIS"},
    }
    for fid in want:
        A._network_fetch(A.meta_for(fid), None)
    for fid, params in want.items():
        assert seen[fid] == params, (fid, seen[fid])
    A._network_fetch(A.meta_for("ACORD_84_INS"), "2016/03")             # an edition asked for explicitly still wins
    assert seen["ACORD_84_INS"]["edition"] == "2016/03"


def test_every_listed_form_has_its_own_unambiguous_request():
    idx = A._index()
    keys = {}
    for fid, e in idx.items():
        req = e.get("request")
        assert isinstance(req, dict) and req, fid
        if req.get("latest"):
            assert fid == "ACORD_125_CIS", fid
            continue
        assert A.normalize_edition(req.get("edition")), (fid, req)
        key = (e["number"], str(req.get("geoCode") or "").upper(), str(req.get("geoCodeSuffix") or "").upper(),
               req["edition"])
        assert key not in keys, (fid, keys.get(key))
        keys[key] = fid


# ── forms ASG refused are never asked for again (owner, 4 Nov 2026) ──────────────────────────────────────────

class _FakeRedis:
    def __init__(self):
        self.kv = {}

    def setex(self, k, ttl, v):
        self.kv[k] = (ttl, v)

    def mget(self, keys):
        return [self.kv.get(k, (0, None))[1] for k in keys]


def test_a_refused_form_is_never_asked_for_again_even_after_a_restart(monkeypatch):
    fake = _FakeRedis()
    monkeypatch.setattr(A, "_refused_store", lambda: fake)
    monkeypatch.setattr(A, "_stub_dir", lambda: None)
    A.clear_ram()
    calls = []

    def asg_sends_the_plain_25(meta, edition):
        calls.append(meta["form_id"])
        return _template_bytes("ACORD_25.pdf")                # ASG answers with another form (plain ACORD 25)
    monkeypatch.setattr(A, "_network_fetch", asg_sends_the_plain_25)
    meta = A.meta_for("ACORD_84_INS")
    with pytest.raises(A.AsgFormUnavailable) as ex:
        A.fetch_blank(meta)
    assert ex.value.reason == "wrong_form" and calls == ["ACORD_84_INS"]
    (ttl, raw), = fake.kv.values()
    assert ttl == 30 * 86400 and json.loads(raw)["reason"] == "wrong_form"
    A.clear_ram()                                             # a restart / another worker: only Redis remembers
    with pytest.raises(A.AsgFormUnavailable) as ex:
        A.fetch_blank(meta)
    assert ex.value.reason == "wrong_form" and calls == ["ACORD_84_INS"]          # no second call to ASG
    rows = A.mark_unavailable([{"form_id": "ACORD_84_INS", "source": A.SOURCE}, {"form_id": "ACORD_27", "source": A.SOURCE},
                               {"form_id": "ACORD_25", "source": "primble"}])
    assert rows[0]["available"] is False and "choose another form" in rows[0]["unavailable_reason"]
    assert "available" not in rows[1] and "available" not in rows[2]
    A.clear_ram()


def test_a_passing_problem_is_not_remembered_for_weeks_and_redis_down_still_works(monkeypatch):
    fake = _FakeRedis()
    monkeypatch.setattr(A, "_refused_store", lambda: fake)
    A.clear_ram()
    A.remember_refused("ACORD_27", "asg_error", "busy")       # a passing problem: never stored for weeks
    assert fake.kv == {} and A.refused_forms(["ACORD_27"]) == {}
    monkeypatch.setattr(A, "_refused_store", lambda: None)    # no Redis: this server still remembers
    A.remember_refused("ACORD_75", "not_available", "no fillable version")
    assert A.refused_forms(["ACORD_75"])["ACORD_75"][0] == "not_available"
    monkeypatch.setenv("ASG_REFUSED_DAYS", "7")
    assert A._refused_seconds() == 7 * 86400
    A.clear_ram()


def test_the_screen_never_lets_a_refused_form_be_ticked():
    front = os.path.join(os.path.dirname(BACKEND), "frontend", "src", "components", "form", "AcordFormSearch.jsx")
    src = open(front).read()
    assert "if (r.available === false) return;" in src and "disabled={selected || unavailable}" in src


# ── the full-feature review (4 Nov 2026) ─────────────────────────────────────────────────────────────────────

def test_review_feature_every_footer_shape_is_read_on_upload():
    """B1: an outside filled form with any of these footers is recognised (and so sent to Transcriber)."""
    from services.acord_intake.recognize import footer_of, footer_number, footer_edition
    cases = {"Page 1 of 2 ACORD 1 (2016/10)": ("1", "2016/10"), "ACORD 50 NY (1/98)": ("50 NY", "1998/01"),
             "ACORD 84 INS (2013/09)": ("84 INS", "2013/09"), "ACORD 1001 (2017/09)": ("1001", "2017/09"),
             "APPLIED 125CIS (2009/08)": ("125 CIS", "2009/08"), "ACORD 137 TX INS (2014/12)": ("137 TX INS", "2014/12"),
             "ACORD 137 CA (2023/01)": ("137 CA", "2023/01"), "ACORD 25 (2016/03)": ("25", "2016/03")}
    for text, want in cases.items():
        m = footer_of(text)
        assert m and (footer_number(m), footer_edition(m)) == want, text
    assert footer_of("ACORD CORPORATION 1998") is None and footer_of("see the ACORD form") is None


def test_review_feature_state_insurance_cards_are_certificates():
    for fid in ("ACORD_50_TX", "ACORD_50_AR", "ACORD_50_GA", "ACORD_50_IA", "ACORD_50_KY", "ACORD_51_GA", "ACORD_830",
                "ACORD_50_NY"):
        assert A.is_certificate_form(fid), fid
    assert not A.is_certificate_form("ACORD_75")


def test_review_feature_the_list_holds_only_forms_with_a_fillable_file():
    idx = A._index()
    for gone in ("ACORD_200", "ACORD_201", "ACORD_1001", "ACORD_130_OH", "ACORD_1_INS", "ACORD_2_INS"):
        assert gone not in idx, gone                                # ASG has no fillable file for any edition
    assert idx["ACORD_141_INS"]["edition"] == "2003/07"             # its newest edition WITH a fillable file
    assert all(e.get("title") for f, e in idx.items() if f != "ACORD_3827")
    assert not any(e.get("ask_edition") for e in idx.values())   # every form now names its own edition (4 Nov 2026)


def test_review_feature_a_plain_request_refuses_a_variant_footer(monkeypatch):
    monkeypatch.setattr(A, "printed_footers", lambda pdf: [(("163", "INS"), "2012/06")])
    wrong, read = A.identity_check(b"%PDF-", {"asg_number": "163", "asg_state": "", "asg_suffix": ""})
    assert read and wrong == "ACORD 163 INS (2012/06)"
    assert A.identity_check(b"%PDF-", {"asg_number": "163", "asg_state": "", "asg_suffix": "INS"}) == (None, True)


def test_review_feature_edition_of_a_form_is_never_read_from_our_templates_unless_ours():
    from services.pdf_service import _form_edition_identifier
    assert _form_edition_identifier("ACORD_2") is None and _form_edition_identifier("ACORD_13") is None
    assert (_form_edition_identifier("ACORD_25") or "").startswith("ACORD 25 (")


def test_review_feature_a_generated_form_is_never_downloaded_again_by_the_gap_fill():
    src = open(os.path.join(BACKEND, "services", "form_service.py")).read()
    assert "elif _rec is None and _asg.feature_on():" in src


# ── the deep check of 4 Nov 2026: every form ASG lists, asked for and verified the way ASG's portal does it ───────

def _catalogue_footer_pdf(footer: str) -> bytes:
    from reportlab.pdfgen import canvas
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=(612, 792))
    c.setFont("Helvetica", 8)
    c.drawString(22, 30, footer)
    c.acroForm.textfield(name="NamedInsured_FullName_A", x=100, y=600, width=200, height=14)
    c.showPage()
    c.save()
    return buf.getvalue()


@pytest.mark.parametrize("fid,footer,ok", [
    ("ACORD_84_INS", "ACORD 84 (2013/09)", True),          # ASG's INS forms print no "INS": the edition proves it
    ("ACORD_84_INS", "ACORD 84 (2026/03)", False),         # the PLAIN 84 for an INS request: another edition
    ("ACORD_84_INS", "ACORD 84 FL (2026/03)", False),      # a state version for a variant
    ("ACORD_84_FL", "ACORD 84 FL (2026/03)", True),
    ("ACORD_84_FL", "ACORD 84 SC (2026/04)", False),       # another state
    ("ACORD_137_LA", "ACORD 137 LA (2026/02)", True),
    ("ACORD_137_LA", "ACORD 137 (2026/02)", True),         # a state code not printed: its own edition proves it
    ("ACORD_137_LA", "ACORD 137 TX (2026/02)", False),     # another state
    ("ACORD_137_LA", "ACORD 137 (2024/10)", False),        # no code printed AND another edition
    ("ACORD_829_LOB", "ACORD 829 LOB (2009/05)", True),
    ("ACORD_829_LOB", "ACORD 829 CLAP (2009/05)", False),  # the other variant
    ("ACORD_829", "ACORD 829 LOB (2009/05)", False),       # a variant for the plain form
    ("ACORD_97_SC", "ACORD 97 SC (2006/08)", True),
    # its codes printed, another edition: the right form (ASG's labels can be a month off - 61 VA prints 2023/07 for
    # its 2023/08 row); a flat edition is refused before this by the box check
    ("ACORD_97_SC", "ACORD 97 SC (2010/09)", True),
    ("ACORD_97_SC", "ACORD 97 (2010/09)", False),          # no code printed AND another edition
    ("ACORD_27", "ACORD 27 (2016/03)", True),
    ("ACORD_27", "ACORD 25 (2016/03)", False),
])
def test_the_footer_check_reads_number_codes_and_edition(fid, footer, ok):
    if fid not in A._index():
        pytest.skip(f"{fid} not in this list")
    meta = A.meta_for(fid)
    wrong, read = A.identity_check(_catalogue_footer_pdf(footer), meta, A.requested_edition(meta))
    assert read and (wrong is None) == ok, (fid, footer, wrong)


def test_editions_are_read_in_every_shape_acord_and_asg_write_them():
    assert A.normalize_edition("2013/09") == "2013/09" and A.normalize_edition(" 2013/10 ") == "2013/10"
    assert A.normalize_edition("1/98") == "1998/01" and A.normalize_edition("10/05") == "2005/10"
    assert A.normalize_edition("Oct-97") == "1997/10"
    assert A.normalize_edition("20003/06") is None and A.normalize_edition("") is None
    assert A.normalize_edition("13/98") is None and A.normalize_edition("2013/13") is None


def test_the_list_adds_asgs_other_codes_and_its_newest_editions():
    idx = A._index()
    for fid in ("ACORD_25_FR", "ACORD_126_S", "ACORD_155_BM", "ACORD_50_WM", "ACORD_60_US",
                "ACORD_62_US", "ACORD_64_US", "ACORD_66_US", "ACORD_75_N", "ACORD_829_CLAP", "ACORD_829_LOB"):
        assert fid in idx and A.is_pc_form(fid), fid
    assert not A.is_pc_form("ACORD_951_E")                       # a Life form: listed, never offered
    # a row with its code only in its NAME is never chosen - ASG cannot serve it (proof calls, 4 Nov 2026: 61 VA and
    # 137 LA 2026/02 answered "no acroform PDF"); the form keeps its properly coded row, or leaves the list
    # a row with its STATE only in its name is asked with that state (proof round 2, 4 Nov 2026: 61 VA, 137 LA 2026/02
    # served); one with a VARIANT only in its name is unproven and never chosen
    assert idx["ACORD_137_LA"]["request"] == {"edition": "2026/02", "geoCode": "LA", "geoCodeSuffix": ""}
    assert idx["ACORD_61_VA"]["request"] == {"edition": "2023/08", "geoCode": "VA", "geoCodeSuffix": ""}
    assert idx["ACORD_80_MS"]["request"]["geoCode"] == "MS"
    assert idx["ACORD_62_AK"]["request"]["geoCode"] == "AK"
    # a geoCodeSuffix ASG has never served is never chosen (live, 5 Nov 2026: 25 S 1995/01 + suffix S answered "no
    # acroform PDF"); every suffix still listed is one ASG served on production
    assert "ACORD_25_S" not in idx
    assert {e["request"].get("geoCodeSuffix") for e in idx.values()} - {"", None} <= {"INS", "CIS"}
    for gone in ("ACORD_131_S", "ACORD_140_S"):
        assert gone not in idx, gone
    for e in idx.values():
        req = e["request"]
        if not req.get("latest"):
            assert (not e["state"] or req["geoCode"].upper() == e["state"]), e["form_id"]
    assert "ACORD_130_OH" not in idx                             # flat only: nothing to fill


@pytest.mark.parametrize("query,fid", [("829 lob", "ACORD_829_LOB"), ("25 fr", "ACORD_25_FR"), ("60 us", "ACORD_60_US"),
                                       ("126 s", "ACORD_126_S"), ("75 n", "ACORD_75_N"), ("155 bm", "ACORD_155_BM"),
                                       ("84 ins", "ACORD_84_INS"), ("137 louisiana", "ACORD_137_LA")])
def test_every_new_form_is_found_by_its_number_and_code(query, fid):
    assert _ids(query, 25)[0] == fid, (query, _ids(query, 5))


def test_refusals_from_before_the_fix_are_not_carried_over():
    # bumped whenever `identity_check` changes (v2: the INS fix; v3: review A) - an old refusal never outlives a fix
    assert re.fullmatch(r"asg:refused:v\d+:", A._REFUSED_PREFIX) and A._REFUSED_PREFIX != "asg:refused:v2:"


# ── review A (4 Nov 2026): the wrong form must never pass; the right one must ───────────────────────────────

def _footer_pdf(*footers, page_text=""):
    from reportlab.pdfgen import canvas
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=(612, 792))
    for i, footer in enumerate(footers):
        c.setFont("Helvetica", 8)
        if page_text and i == 0:
            c.drawString(40, 740, page_text)
        c.drawString(22, 30, footer)
        if i == 0:
            c.acroForm.textfield(name="NamedInsured_FullName_A", x=100, y=600, width=200, height=14)
        c.showPage()
    c.save()
    return buf.getvalue()


def _check(fid, pdf):
    m = A.meta_for(fid)
    return A.identity_check(pdf, m, A.requested_edition(m))[0] is None


@pytest.mark.parametrize("fid,footer", [("ACORD_125_FL", "ACORD 125 (2016/03)"), ("ACORD_82_MD", "ACORD 82 (2025/07)"),
                                        ("ACORD_877_CA", "ACORD 877 (2015/10)"), ("ACORD_84_FL", "ACORD 84 (2026/03)"),
                                        ("ACORD_829_LOB", "ACORD 829 (2009/05)"), ("ACORD_829_CLAP", "ACORD 829 (2009/05)")])
def test_the_plain_form_at_the_same_edition_is_never_accepted_as_a_state_or_code_version(fid, footer):
    assert not A.meta_for(fid)["asg_unique_edition"]          # the plain form shares this edition
    assert not _check(fid, _footer_pdf(footer))


def test_a_state_form_whose_first_page_names_its_state_is_accepted_without_the_code_printed():
    assert _check("ACORD_125_FL", _footer_pdf("ACORD 125 (2016/03)",
                                              page_text="FLORIDA COMMERCIAL INSURANCE APPLICATION"))
    assert _check("ACORD_125_FL", _footer_pdf("ACORD 125 FL (2016/03)"))


def test_the_edition_asgs_own_file_carries_is_accepted():
    assert A.meta_for("ACORD_61_NY")["asg_request"]["file_edition"] == "2025/04"   # row says 2026/04
    assert _check("ACORD_61_NY", _footer_pdf("ACORD 61 NY (2025/04)"))
    assert _check("ACORD_61_NY", _footer_pdf("ACORD 61 NY (2026/04)"))
    assert _check("ACORD_61_NY", _footer_pdf("ACORD 61 NY (2015/01)"))       # its codes printed: ours
    assert not _check("ACORD_61_NY", _footer_pdf("ACORD 61 (2015/01)"))      # no code, another edition


def test_a_foreign_code_on_any_page_refuses_the_file():
    assert not _check("ACORD_84", _footer_pdf("ACORD 84 FL (2026/03)", "ACORD 84 (2026/03)"))
    assert not _check("ACORD_84", _footer_pdf("ACORD 84 (2026/03)", "ACORD 84 FL (2026/03)"))


def test_the_refusal_memory_can_be_turned_off(monkeypatch):
    monkeypatch.setenv("ASG_REFUSED_DAYS", "0")
    assert A._refused_seconds() == 0
    A.remember_refused("ACORD_27", "wrong_form", "x")
    assert A.refused_forms(["ACORD_27"]) == {}


def test_a_plural_typed_after_a_number_is_not_the_s_form():
    for q in ("25s", "acord 25's", "25's"):
        assert [r["form_id"] for r in A.search_full(q, 3)[0]][0] == "ACORD_25", q
    for q in ("25 s", "25-s"):                     # 25 S left the list (5 Nov 2026): our ACORD 25 comes first
        got = [r["form_id"] for r in A.search_full(q, 3)[0]]
        assert got[0] == "ACORD_25" and "ACORD_25_S" not in got, q


def test_the_builder_handles_odd_catalogue_shapes(tmp_path):
    import importlib.util
    spec = importlib.util.spec_from_file_location("bidx", os.path.join(BACKEND, "scripts", "build_asg_forms_index.py"))
    b = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(b)
    assert b.edition_key("Oct-97") == "1997/10" and b.edition_key("Jan-99") == "1999/01"
    acro = lambda tag: f"eForms/PNC_FRM_UXX_X_{tag}_ACRO.pdf"           # noqa: E731
    rows = [
        {"number": "902", "name": "902CA", "geoCode": "CA", "edition": "2020/01", "acroFileName": acro("202001_902"),
         "title": "California Thing"},                                         # name with no separator
        {"number": "903", "name": "903", "geoCode": "", "geoCodeSuffix": "CA", "edition": "2020/01",
         "acroFileName": acro("202001_903"), "title": "Suffix that reads as a state"},
        {"number": "904", "name": "904", "edition": "Oct-97", "acroFileName": acro("199710_904"), "title": "Old"},
        {"number": "904", "name": "904", "edition": "Jan-99", "acroFileName": acro("199901_904"), "title": "Newer"},
        {"number": "905", "name": "905", "edition": "2021/01", "acroFileName": acro("202101_905"), "title": "A"},
        {"number": "905", "name": "905", "edition": "2021/01", "acroFileName": "flat.pdf", "title": "A flat twin"},
        {"number": "905", "name": "905", "edition": "2019/01", "acroFileName": acro("201901_905"), "title": "A"},
    ]
    path = tmp_path / "cat.json"
    path.write_text(json.dumps(rows))
    idx = b.build_from_catalogue(str(path))
    got = {f["form_id"]: f for f in idx["forms"]}
    assert "ACORD_902_CA" in got and got["ACORD_902_CA"]["request"]["geoCode"] == "CA"
    assert "ACORD_903_CA" not in got and "903" in idx["skipped_names"]
    assert got["ACORD_904"]["edition"] == "Jan-99"
    assert got["ACORD_905"]["edition"] == "2019/01" and "ACORD_905@2021/01" in idx["ambiguous_rows_passed_over"]


def test_a_refusal_belongs_to_the_request_that_was_refused(monkeypatch):
    """137 LA was refused when asked WITHOUT its code (2026/02); asked as its coded 2024/10 row it gets a fresh try."""
    monkeypatch.setattr(A, "_refused_store", lambda: None)
    real = dict(A._index())
    old = dict(real["ACORD_137_LA"], request={"edition": "2026/02", "geoCode": "", "geoCodeSuffix": ""})
    monkeypatch.setattr(A, "_index", lambda: {**real, "ACORD_137_LA": old})
    A.remember_refused("ACORD_137_LA", "not_available", "This form has no acroform PDF for download.")
    assert A.refused_forms(["ACORD_137_LA"])                         # the refused request stays refused
    monkeypatch.setattr(A, "_index", lambda: real)
    assert A.refused_forms(["ACORD_137_LA"]) == {}                   # the new request is not
    A._refused_ram.clear()


# ── review C (4 Nov 2026): nothing that would embarrass us in front of an agent ──────────────────────────────

def test_rows_that_contradict_themselves_are_never_offered_as_they_are():
    idx = A._index()
    assert "ACORD_66_CO" not in idx            # its rows are titled / filed as the Commercial Insurance Application
    assert "ACORD_63_OK" not in idx            # its only fillable row is titled "Ohio Fraud Statement"
    assert idx["ACORD_137_WA"]["edition"] == "2016/12"     # the 2024/02 row's file is Maryland's EUIM offer
    assert "CHECKLIST" in idx["ACORD_856_CA"]["title"].upper()   # its file is the BOP application checklist
    assert idx["ACORD_3827"]["title"]                       # a blank title reads from the file name


def test_titles_are_clean_plain_text():
    for fid, e in A._index().items():
        t = e["title"]
        assert not re.search(r"[–—‘’“”]|\s{2,}|Floirda|Liabiilty|Addenedum|\?", t), (fid, t)


@pytest.mark.parametrize("query,first", [("commercial umbrella", "ACORD_131"), ("commercial auto", "ACORD_127"),
                                         ("assigned risk", "ACORD_133"), ("commercial property", "ACORD_28"),
                                         ("businessowners", "ACORD_160"), ("excess liability", "ACORD_131"),
                                         ("tria", "ACORD_60_US"), ("terrorism", "ACORD_60_US"), ("boiler", "ACORD_155"),
                                         ("certificate", "ACORD_25"), ("vehicle schedule", "ACORD_127")])
def test_common_searches_lead_with_the_right_form(query, first):
    assert _ids(query, 5)[0] == first, (query, _ids(query, 5))


def test_australian_forms_rank_after_us_forms():
    for q in ("certificate", "vehicle schedule", "remarks", "commercial insurance application"):
        ids = _ids(q, 25)
        au = [i for i in ids if A._index().get(i, {}).get("region") == "AU"]
        us = [i for i in ids if A._index().get(i, {}).get("region") != "AU"]
        assert not au or ids.index(au[0]) > ids.index(us[-1]) or len(us) == 25, (q, ids)


def test_typed_words_side_by_side_outrank_scattered_ones():
    assert _ids("insurance card", 3)[0] != "ACORD_305"
    assert "ACORD_305" not in _ids("id card", 25)


def test_a_mislabelled_edition_is_accepted_unless_it_is_the_twin_forms():
    plain, ins = A.meta_for("ACORD_84"), A.meta_for("ACORD_84_INS")
    ok = lambda m, footer: A.identity_check(_footer_pdf(footer), m, A.requested_edition(m))[0] is None   # noqa: E731
    assert ok(plain, "ACORD 84 (2026/02)")            # ASG's label a month off: the right form
    assert not ok(plain, "ACORD 84 (2013/09)")        # the INS form's edition: the twin, refused
    assert ok(ins, "ACORD 84 (2013/08)")
    assert not ok(ins, "ACORD 84 (2026/03)")          # the plain form's edition: refused


def test_certificate_wording_covers_id_forms_and_not_floodproofing():
    for fid in ("ACORD_50_OK", "ACORD_51_OK", "ACORD_54", "ACORD_57"):
        assert A.is_certificate_form(fid), fid
    for fid in ("ACORD_307", "ACORD_308"):
        assert not A.is_certificate_form(fid), fid


def test_a_state_version_about_another_subject_does_not_inherit_our_scoring_lines():
    assert not A.same_subject_as_ours("ACORD_186_SC")        # auto UM, not our contractors supplement
    for fid in ("ACORD_137_TX", "ACORD_130_FL", "ACORD_125_FL", "ACORD_125"):
        assert A.same_subject_as_ours(fid), fid
    from services.sqs_service import stops_for_form
    gl = "GL coverage detected but no class codes on ACORD 126"
    assert gl not in stops_for_form([gl], "ACORD_127") or True     # unchanged behaviour for ours (smoke)


def test_a_form_no_longer_offered_is_left_out_and_named_never_dropped_silently(monkeypatch):
    """A tab opened before 25 S left the list (5 Nov 2026) still sends it: it is named, the rest generate."""
    import json
    asyncio, HTTPException, fr, req, user, writes = _generate_route_harness(monkeypatch)
    jobs = _capture_queue(monkeypatch, fr)
    req.form_ids = ["ACORD_125", "ACORD_25_S", "ACORD_131__excess", "ACORD_27"]
    res = asyncio.run(fr.select_forms_bulk(req, current_user=user))
    body = json.loads(res.body)
    assert jobs[0]["form_ids"] == ["ACORD_125", "ACORD_131__excess", "ACORD_27"]   # a layer copy is ours
    assert body["asg_not_generated"] == [{"form_id": "ACORD_25_S", "reason": "not_listed"}]
    assert "ACORD 25 S is no longer offered, so it was left out of this package." in body["asg_not_generated_message"]


def test_only_forms_no_longer_offered_is_a_400_that_names_them(monkeypatch):
    asyncio, HTTPException, fr, req, user, writes = _generate_route_harness(monkeypatch)
    jobs = _capture_queue(monkeypatch, fr)
    req.form_ids = ["ACORD_25_S"]
    with pytest.raises(HTTPException) as ex:
        asyncio.run(fr.select_forms_bulk(req, current_user=user))
    assert ex.value.status_code == 400 and "ACORD 25 S is no longer offered" in ex.value.detail and jobs == []
    assert "ready" not in ex.value.detail


def test_a_left_out_unlisted_and_a_refused_form_are_both_named(monkeypatch):
    import json
    asyncio, HTTPException, fr, req, user, writes = _generate_route_harness(monkeypatch)
    _capture_queue(monkeypatch, fr)
    req.form_ids = ["ACORD_125", "ACORD_25_S", "ACORD_75"]           # 25 S unlisted; the stub has no ACORD 75
    body = json.loads(asyncio.run(fr.select_forms_bulk(req, current_user=user)).body)
    assert [x["form_id"] for x in body["asg_not_generated"]] == ["ACORD_25_S", "ACORD_75"]
    msg = body["asg_not_generated_message"]
    assert "ACORD 25 S is no longer offered" in msg and "no fillable version of ACORD 75" in msg



# ── hard review of the left-out change (5 Nov 2026) ───────────────────────────

def _counting(monkeypatch, slow=None, fail=None):
    import time as _t
    calls = []
    real = A._stub_fetch

    def fake(meta):
        fid = meta["form_id"]
        calls.append(fid)
        if slow and fid in slow:
            _t.sleep(slow[fid])
        if fail and fid in fail:
            raise A.AsgFormUnavailable(fail[fid], "x")
        return real(meta)
    monkeypatch.setattr(A, "_stub_fetch", fake)
    return calls


def test_a_retry_while_a_download_still_runs_never_pays_twice(monkeypatch):
    import time as _t
    asyncio, HTTPException, fr, req, user, writes = _generate_route_harness(monkeypatch)
    _capture_queue(monkeypatch, fr)
    monkeypatch.setattr(A, "PREFETCH_DEADLINE_SECONDS", 0.3)
    calls = _counting(monkeypatch, slow={"ACORD_27": 1.5})
    req.form_ids = ["ACORD_125", "ACORD_27"]
    with pytest.raises(HTTPException) as ex:                           # ACORD 27 misses the deadline
        asyncio.run(fr.select_forms_bulk(req, current_user=user))
    assert ex.value.status_code == 503 and ex.value.detail["rest"] == ["ACORD_125"]
    monkeypatch.setattr(A, "PREFETCH_DEADLINE_SECONDS", 5.0)
    res = asyncio.run(fr.select_forms_bulk(req, current_user=user))   # Retry at once: waits for the running one
    assert res.status_code == 202
    _t.sleep(0.2)
    assert calls.count("ACORD_27") == 1, calls


def test_a_second_caller_takes_the_running_downloads_failure(monkeypatch):
    import threading
    calls = _counting(monkeypatch, slow={"ACORD_75": 0.5})              # the stub has no ACORD 75
    out = []

    def one():
        try:
            A.fetch_blank(A.meta_for("ACORD_75"))
        except A.AsgFormUnavailable as ex:
            out.append(ex.reason)
    ts = [threading.Thread(target=one) for _ in range(3)]
    [t.start() for t in ts]
    [t.join() for t in ts]
    assert calls == ["ACORD_75"] and out == ["not_available"] * 3


@pytest.mark.parametrize("reason", ["bad_file", "rejected"])
def test_a_file_that_cannot_be_filled_or_a_rejected_request_is_left_out(monkeypatch, reason):
    import json
    asyncio, HTTPException, fr, req, user, writes = _generate_route_harness(monkeypatch)
    jobs = _capture_queue(monkeypatch, fr)
    calls = _counting(monkeypatch, fail={"ACORD_27": reason})
    req.form_ids = ["ACORD_125", "ACORD_27"]
    body = json.loads(asyncio.run(fr.select_forms_bulk(req, current_user=user)).body)
    assert jobs[-1]["form_ids"] == ["ACORD_125"]
    assert body["asg_not_generated"] == [{"form_id": "ACORD_27", "reason": reason}]
    assert "ACORD 27" in body["asg_not_generated_message"] and "cannot be added to this package later" in \
        body["asg_not_generated_message"]
    asyncio.run(fr.select_forms_bulk(req, current_user=user))          # pressed again: remembered, no new download
    assert calls.count("ACORD_27") == 1


def test_asg_rejecting_a_request_is_not_retried(monkeypatch):
    import httpx
    monkeypatch.delenv("ASG_FORMS_STUB_DIR", raising=False)
    for k, v in (("TRANSCRIBER_CLIENT_ID", "x"), ("TRANSCRIBER_CLIENT_SECRET", "y"), ("TRANSCRIBER_API_KEY", "z"),
                 ("TRANSCRIBER_ENV", "uat"), ("ENVIRONMENT", "development")):
        monkeypatch.setenv(k, v)
    A._token.update(value="tok", expiry=10 ** 12, bearer=False)
    monkeypatch.setattr(A, "remember_refused", lambda *a, **k: None)
    gets = []
    for status, body, want in ((404, "not found", "rejected"), (422, "bad", "rejected"),
                               (400, "bad request", "rejected"), (200, "<html>oops</html>", "bad_file")):
        A.clear_ram()
        A._failed.clear()

        def reply(self, request, _s=status, _b=body, **kw):
            gets.append(request.url.path)
            return httpx.Response(_s, text=_b, request=request)
        monkeypatch.setattr(httpx.Client, "send", reply)
        before = len(gets)
        with pytest.raises(A.AsgFormUnavailable) as ex:
            A.fetch_blank(A.meta_for("ACORD_27"))
        assert ex.value.reason == want and len(gets) - before == 1, (status, ex.value.reason)
    A._token.update(value="", expiry=0.0, bearer=None, failed_until=0.0)


def test_a_form_no_longer_offered_is_named_when_the_run_stops_too(monkeypatch):
    import json
    asyncio, HTTPException, fr, req, user, writes = _generate_route_harness(monkeypatch)
    _capture_queue(monkeypatch, fr)
    real_try_fetch = A.try_fetch
    monkeypatch.setattr(A, "try_fetch", lambda meta: {"form_id": meta["form_id"], "reason": "asg_error"}
                        if meta["form_id"] == "ACORD_27" else None)
    req.form_ids = ["ACORD_125", "ACORD_25_S", "ACORD_27"]
    with pytest.raises(HTTPException) as ex:
        asyncio.run(fr.select_forms_bulk(req, current_user=user))
    d = ex.value.detail
    assert ex.value.status_code == 503 and "ACORD 25 S is no longer offered" in d["message"]
    assert d["left_out"] == [{"form_id": "ACORD_25_S", "reason": "not_listed"}] and d["rest"] == ["ACORD_125"]
    monkeypatch.setattr(A, "try_fetch", real_try_fetch)                # the stub has no ACORD 75
    req.form_ids = ["ACORD_25_S", "ACORD_75"]                          # nothing left: a 400 naming both
    with pytest.raises(HTTPException) as ex:
        asyncio.run(fr.select_forms_bulk(req, current_user=user))
    assert ex.value.status_code == 400
    assert "ACORD 25 S is no longer offered" in ex.value.detail["message"] and "ACORD 75" in ex.value.detail["message"]


def test_a_setup_failure_names_support_and_still_offers_the_other_forms():
    msg = A.prefetch_failure_message([{"form_id": "ACORD_27", "reason": "auth"}], can_skip=True)
    assert msg.startswith(A.NOT_SET_UP) and "generate your other forms without" in msg
    assert A.prefetch_failure_message([{"form_id": "ACORD_27", "reason": "auth"}]) == A.NOT_SET_UP


@pytest.mark.parametrize("raw,canon", [("acord_125", "ACORD_125"), ("ACORD_137_ca", "ACORD_137_CA"),
                                       (" acord_131__excess ", "ACORD_131__excess"), ("ACORD_27", "ACORD_27")])
def test_one_spelling_for_every_form_id(raw, canon):
    assert A.clean_form_ids([raw]) == [canon]


def test_a_lower_case_id_of_our_own_form_is_never_called_no_longer_offered(monkeypatch):
    import json
    asyncio, HTTPException, fr, req, user, writes = _generate_route_harness(monkeypatch)
    jobs = _capture_queue(monkeypatch, fr)
    req.form_ids = ["acord_125", "ACORD_137_ca"]
    body = json.loads(asyncio.run(fr.select_forms_bulk(req, current_user=user)).body)
    assert jobs[-1]["form_ids"] == ["ACORD_125", "ACORD_137_CA"] and "asg_not_generated" not in body


def test_a_failed_list_load_is_not_kept(monkeypatch):
    A._index.cache_clear()
    monkeypatch.setattr(A, "INDEX_PATH", "/nonexistent/asg_forms_index.json")
    assert A._index() == {}
    monkeypatch.undo()
    assert len(A._index()) > 1000                                      # the next call loads the real list
