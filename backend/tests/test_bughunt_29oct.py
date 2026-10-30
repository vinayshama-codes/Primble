"""Bug hunt, 29 Oct 2026 - Transcriber pre-submit and the Primble record's account
binding. Synthetic data only; no network, no ASG, no model."""
import asyncio
import io

import pytest

from services import asg_transcriber as T
from services.acord_intake import transcriber_intake as TI


def _live_cfg(**over):
    base = dict(enabled=True, env="uat", token_url="https://t", base_url="https://b/oauth", upload_url="https://u",
                client_id="id", client_secret="s", api_key="k", scope="", wait_seconds=5, poll_interval=0.01,
                http_timeout=5, max_pages_per_package=40, daily_page_cap=500, send_fillable=True,
                stub_dir="", bearer=False)
    base.update(over)
    return T.TranscriberConfig(**base)


def _mixed_pdf(path):
    """Page 1: a printed (flattened) ACORD 125 page. Page 2: an image only - a scan
    OCR recognises later."""
    from PIL import Image
    from reportlab.lib.utils import ImageReader
    from reportlab.pdfgen import canvas
    c = canvas.Canvas(str(path), pagesize=(612, 792))
    c.drawString(72, 700, "COMMERCIAL INSURANCE APPLICATION")
    c.drawString(72, 40, "ACORD 125 (2016/03)   Page 1 of 4   (c) 1993-2015 ACORD CORPORATION. All rights reserved.")
    c.showPage()
    b = io.BytesIO()
    Image.new("RGB", (200, 200), (200, 200, 200)).save(b, "PNG")
    b.seek(0)
    c.drawImage(ImageReader(b), 0, 0, 612, 792)
    c.showPage()
    c.save()


def _flattened_pdf(path):
    from reportlab.pdfgen import canvas
    c = canvas.Canvas(str(path), pagesize=(612, 792))
    for n in (1, 2):
        c.drawString(72, 700, "COMMERCIAL INSURANCE APPLICATION")
        c.drawString(72, 40, f"ACORD 125 (2016/03)   Page {n} of 4   (c) 1993-2015 ACORD CORPORATION.")
        c.showPage()
    c.save()


def _wire(monkeypatch, cfg):
    from repositories import transcriber_repository as R
    store, sent = {}, []

    async def get(h, env):
        return store.get((h, env))

    async def put(h, env, result, **kw):
        store[(h, env)] = result

    monkeypatch.setattr(R, "get_cached", get)
    monkeypatch.setattr(R, "put_cached", put)
    monkeypatch.setattr(TI, "load_config", lambda: cfg)

    class Fake(T.TranscriberClient):
        async def submit_only(self, data, **kw):
            sent.append(kw.get("pages"))
            return f"req-{len(sent)}"
    monkeypatch.setattr(TI, "_default_client", lambda: Fake(cfg))
    return store, sent


def test_a_pdf_with_a_possible_scan_is_not_pre_submitted(tmp_path, monkeypatch):
    """The pre-submit planned page 1 only (no OCR yet); `extract_document` later
    planned pages 1-2 (OCR found the scan's footer) - a different sub-PDF and hash,
    so page 1 was paid twice and the pending request never collected."""
    pdf = tmp_path / "mixed.pdf"
    _mixed_pdf(pdf)
    cfg = _live_cfg()
    from services.acord_intake import intake
    text = ("[Document page 1]\nCOMMERCIAL INSURANCE APPLICATION\nACORD 125 (2016/03) Page 1 of 4\n"
            "[Document page 2]\nAPPLICANT INFORMATION\nPage 2 of 4\nACORD 125 (2016/03)")
    rec = intake.read_for_document(str(pdf), text)["record"]
    later = TI.plan(str(pdf), rec, has_primble_record=False, ocr_text=text, cfg=cfg)
    assert later is not None and later.pages == [0, 1]
    store, sent = _wire(monkeypatch, cfg)
    assert asyncio.run(TI.presubmit_package([str(pdf)])) == 0
    assert sent == [] and store == {}


def test_a_text_pdf_pre_submit_hash_equals_the_read_time_hash(tmp_path, monkeypatch):
    pdf = tmp_path / "flat.pdf"
    _flattened_pdf(pdf)
    cfg = _live_cfg()
    store, sent = _wire(monkeypatch, cfg)
    assert asyncio.run(TI.presubmit_package([str(pdf)])) == 1 and sent == [2]
    from services.acord_intake import intake
    text = "\n".join(f"[Document page {n}]\nACORD 125 (2016/03) Page {n} of 4" for n in (1, 2))
    rec = intake.read_for_document(str(pdf), text)["record"]
    later = TI.plan(str(pdf), rec, has_primble_record=False, ocr_text=text, cfg=cfg)
    (key,) = store
    assert later is not None and key[0] == later.hash      # collected, never paid twice


def test_the_same_file_twice_in_one_upload_is_sent_once(tmp_path, monkeypatch):
    a, b = tmp_path / "a.pdf", tmp_path / "b.pdf"
    _flattened_pdf(a)
    b.write_bytes(a.read_bytes())
    store, sent = _wire(monkeypatch, _live_cfg())
    assert asyncio.run(TI.presubmit_package([str(a), str(b)])) == 1
    assert sent == [2]


def test_every_package_opens_a_fresh_page_budget(tmp_path, monkeypatch):
    """The worker runs every job in one task: the first package's budget used to be
    spent by every later one."""
    pdf = tmp_path / "flat.pdf"
    _flattened_pdf(pdf)
    cfg = _live_cfg(max_pages_per_package=2)

    async def two_packages():
        store, sent = _wire(monkeypatch, cfg)
        n1 = await TI.presubmit_package([str(pdf)])
        store.clear()                                  # a different file next time
        n2 = await TI.presubmit_package([str(pdf)])
        return n1, n2, sent
    n1, n2, sent = asyncio.run(two_packages())
    assert (n1, n2) == (1, 1) and sent == [2, 2]


@pytest.mark.parametrize("text", [
    "ACORD 125 (2016/03) Page 2 of4",
    "ACORD 125 (2016/03) Page2 of 4",
    "ACORD 125 (2016/03) Page l of 4",
    "(c) 1993-2015 ACORDCORPORATION. All rights reserved.",
    "The ACORD name and logo are registered marks of ACORD",
])
def test_an_ocr_noisy_acord_page_still_reads_as_one(text):
    assert TI.looks_like_acord_page(text)


def test_a_carrier_page_citing_an_acord_form_is_still_refused():
    assert not TI.looks_like_acord_page("Attach a completed ACORD 125 (2016/03) to this quote.")


# ── the Primble record's account binding ─────────────────────────────────────
def test_the_uploader_reaches_a_record_read_off_the_event_loop():
    from services.acord_intake import primble_record as PR
    rec = {"v": 2, "account": PR.account_key("u-1")}

    async def read_as(user):
        PR.uploading_account(user)
        return await asyncio.to_thread(PR.same_account, rec)
    assert asyncio.run(read_as("u-1")) is True
    assert asyncio.run(read_as("u-2")) is False
    # an integer id at write and its text at read (or back) are one account
    rec = {"v": 2, "account": PR.account_key(7)}
    assert asyncio.run(read_as("7")) is True
    # the uploader set inside one upload's task never leaks into the caller's context
    assert PR._UPLOADER.get() is None
    # a record written before the binding, or a read with no uploader: not judged
    assert PR.same_account({"v": 2}) is True


def test_a_refused_send_refunds_only_pages_it_counted(monkeypatch):
    import asyncio
    from services import asg_transcriber as T
    refunds = []

    async def usage(pages, env):
        if pages < 0:
            refunds.append(pages)
            return 0
        return T.USAGE_UNAVAILABLE                # the counter could not be written

    cfg = T.TranscriberConfig(enabled=True, env="uat", token_url="t", base_url="b", upload_url="u", client_id="i",
                              client_secret="s", api_key="k", scope="", wait_seconds=5, poll_interval=0.01,
                              http_timeout=5, max_pages_per_package=40, daily_page_cap=500, send_fillable=True,
                              stub_dir="", bearer=False)
    c = T.TranscriberClient(cfg, usage=usage)
    try:
        asyncio.run(c.extract(b"%PDF", pages=3))
    except T.TranscriberError as ex:
        assert ex.kind == "quota"
    assert refunds == []


def test_add_documents_never_pre_submits():
    import inspect
    from routes import session_documents_routes as R
    assert "presubmit_package(" not in inspect.getsource(R)


def test_one_documents_schedule_amounts_are_not_a_conflict():
    """Live kit cd683556: per-building values / per-class payrolls of ONE dec were
    read as rival answers - "the documents state different amounts" about one
    document. Two documents stating different amounts still conflict."""
    from services.underwriting_consistency import assess_underwriting_consistency

    def doc(i, name, val):
        return {"doc_id": f"d{i}", "filename": name, "doc_type": "dec_page",
                "facts": {"property_building_value": {"value": val}},
                "text": f"Building Value: {val}"}
    one = [doc(1, "dec.pdf", "$2,350,000")]
    one[0]["text"] = "Building 1 Building Value: $2,350,000\nBuilding 2 Building Value: $1,780,000\nBuilding 3 Building Value: $910,000"
    out = assess_underwriting_consistency(one, {"property_building_value": {"value": "$2,350,000"}})
    row = next((f for f in out.get("fields") or [] if f.get("fact_key") == "property_building_value"), None)
    assert not row or not row.get("review_required"), row
    two = [doc(1, "dec.pdf", "$2,350,000"), doc(2, "sov.pdf", "$2,900,000")]
    out2 = assess_underwriting_consistency(two, {"property_building_value": {"value": "$2,350,000"}})
    row2 = next((f for f in out2.get("fields") or [] if f.get("fact_key") == "property_building_value"), None)
    assert row2 and row2.get("review_required")


def test_a_truncated_vin_is_the_same_vehicle_as_its_full_vin():
    """Live kit, 29 Oct 2026: a dec printing a 16-character VIN beside the
    ACORD 127's full 17-character VIN made 4 vehicles 7."""
    from services.acord_intake.merge_rules import _describes_same_vehicle as S
    full = {"vin": "1GCZGHFP5M1203448", "year": "2021", "make": "Chevrolet", "model": "Express"}
    assert S(full, {"vin": "1GCZGHFP5M120344", "year": "2021"}) is True
    assert S({"vin": "1GCZGHFP5M120344", "year": "2021"}, full) is True
    assert S(full, {"vin": "1GCZGHFP5M120344", "year": "2020"}) is False          # another year
    assert S(full, {"vin": "1GCZGHFP5M1203449", "year": "2021"}) is False         # consecutive serial: two vans
    assert S(full, {"vin": "1GCZGHFP", "year": "2021"}) is False                  # too short to identify
    assert S(full, {"vin": "1GCZGHFP5M120344", "year": "2021", "make": "Ford"}) is False
