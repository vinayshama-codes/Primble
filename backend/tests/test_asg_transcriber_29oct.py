"""ASG Transcriber (29 Oct 2026, ASG_TRANSCRIBER.md): the client against every
documented reply shape, the routing, the one-document-one-reading rule, the
labels, and the whole path through the stub - never the network."""
import asyncio
import base64
import gzip
import json
import os

import pytest

from services import asg_transcriber as T
from services.acord_intake import transcriber_intake as TI

STUB = os.path.join(os.path.dirname(__file__), "fixtures", "transcriber_stub")


@pytest.fixture(autouse=True)
def _no_network(monkeypatch):
    def refuse(*_a, **_k):
        raise AssertionError("the Transcriber tests must make no network call")
    import httpx
    monkeypatch.setattr(httpx.AsyncClient, "send", refuse)
    monkeypatch.setattr(httpx.Client, "send", refuse)
    monkeypatch.setenv("TRANSCRIBER_STUB_DIR", STUB)
    TI.reset_client()
    # a package page budget another test opened lives in this thread's context;
    # every test starts with none (production: each request has its own context)
    tok = TI._PACKAGE_BUDGET.set(None)
    yield
    TI._PACKAGE_BUDGET.reset(tok)
    TI.reset_client()


def _stub_cfg(**over):
    base = dict(enabled=True, env="uat", token_url="https://t", base_url="https://b/oauth", upload_url="https://u",
                client_id="", client_secret="", api_key="", scope="", wait_seconds=5, poll_interval=0.01,
                http_timeout=5, max_pages_per_package=40, daily_page_cap=500, send_fillable=True,
                stub_dir=STUB, bearer=False)
    base.update(over)
    return T.TranscriberConfig(**base)


# ── configuration guards ──────────────────────────────────────────────────────
def test_off_by_default_and_never_live_without_all_three_secrets(monkeypatch):
    for k in ("TRANSCRIBER", "TRANSCRIBER_CLIENT_ID", "TRANSCRIBER_CLIENT_SECRET", "TRANSCRIBER_API_KEY",
              "TRANSCRIBER_STUB_DIR"):
        monkeypatch.delenv(k, raising=False)
    assert T.load_config().enabled is False
    monkeypatch.setenv("TRANSCRIBER", "1")
    monkeypatch.setenv("TRANSCRIBER_CLIENT_ID", "id")
    monkeypatch.setenv("TRANSCRIBER_CLIENT_SECRET", "secret")
    cfg = T.load_config()
    assert cfg.enabled and not cfg.live and not cfg.usable       # no API key = no call, no stub = unusable


def test_production_refuses_the_uat_service(monkeypatch):
    monkeypatch.setenv("TRANSCRIBER", "1")
    monkeypatch.setenv("TRANSCRIBER_ENV", "uat")
    monkeypatch.setenv("ENVIRONMENT", "production")
    monkeypatch.delenv("TRANSCRIBER_ALLOW_UAT_IN_PROD", raising=False)
    assert T.load_config().enabled is False
    monkeypatch.setenv("TRANSCRIBER_ALLOW_UAT_IN_PROD", "1")
    assert T.load_config().enabled is True
    monkeypatch.setenv("ENVIRONMENT", "development")


def test_the_stub_makes_the_client_not_live(monkeypatch):
    monkeypatch.setenv("TRANSCRIBER", "1")
    for k, v in (("TRANSCRIBER_CLIENT_ID", "id"), ("TRANSCRIBER_CLIENT_SECRET", "s"), ("TRANSCRIBER_API_KEY", "k")):
        monkeypatch.setenv(k, v)
    cfg = T.load_config()
    assert cfg.usable and not cfg.live


# ── parsing every documented reply shape ──────────────────────────────────────
def _default_body():
    return json.load(open(os.path.join(STUB, "default.json")))


def test_elabel_xml_groups_pages_into_forms_and_keeps_confidence_and_coordinates():
    res = T.parse_poll_reply(json.dumps(_default_body()), {})
    assert res.status == "done"
    assert [f.form_number for f in res.forms] == ["125", "UNKNOWN"]
    f = res.forms[0]
    assert f.pages == [1, 2] and f.accuracy == 91 and not f.rejected
    assert f.boxes["NamedInsured_FullName_A"].value == "Stubworks Fabrication LLC"
    assert f.boxes["NamedInsured_FullName_A"].confidence == 99
    assert f.boxes["NamedInsured_FullName_A"].bbox == (40, 300, 400, 320)
    assert f.boxes["NamedInsured_AnnualRevenueAmount_A"].page == 2
    assert res.forms[1].rejected and res.readable_forms == [f]


def test_processing_rejected_and_critical_rule_shapes():
    proc = json.load(open(os.path.join(STUB, "processing.json")))
    assert T.parse_poll_reply(json.dumps(proc), {}).status == "processing"
    assert T.parse_poll_reply({"status": "accepted", "requestId": "r1", "message": "m"}, {}).status == "processing"
    assert T.parse_poll_reply('{"responseBody":"<ACORD><status>RETRYING</status><message>x</message></ACORD>"}', {}).status == "processing"
    rej = {"responseBody": '<ACORD><ACORD documentName="" documentPageNum="1" formNumber="UNKNOWN" status="Rejected">not supported</ACORD></ACORD>', "ruleExceptionList": []}
    r = T.parse_poll_reply(json.dumps(rej), {})
    assert r.status == "done" and r.readable_forms == []
    with pytest.raises(T.TranscriberError) as ex:
        T.parse_poll_reply({"responseBody": "<ACORD>Failed due to Exception occurred for critical rule</ACORD>"}, {})
    assert ex.value.kind == "rejected"
    assert T.parse_poll_reply({"responseBody": "Unable to extract document. Please contact ASG support."}, {}).status == "failed"


def test_json_elabel_shape_and_the_large_reply_headers():
    j = {"ACORD": {"ACORD": [{"edition": "2016/03", "formNumber": "25", "documentPageNum": "1", "status": "Success",
                              "CertificateHolder_FullName_A": {"content": "Acme Holder", "confidence_score": "88"}}]}}
    r = T.parse_poll_reply({"responseBody": json.dumps(j)}, {})
    assert r.forms[0].form_number == "25" and r.forms[0].boxes["CertificateHolder_FullName_A"].confidence == 88
    gz = base64.b64encode(gzip.compress(json.dumps(_default_body()).encode())).decode()
    r2 = T.parse_poll_reply(gz, {"X-asg-body-compression-enabled": "Y"})
    assert r2.status == "done" and r2.forms[0].form_number == "125"
    r3 = T.parse_poll_reply("https://uat-transcriber.acordsolutions.net/dl?token=abc", {"X-asg-large-response-enabled": "Y"})
    assert r3.status == "download" and r3.message.startswith("https://")


def test_xml_with_entities_or_oversized_is_refused():
    with pytest.raises(ValueError):
        T.parse_elabel_xml('<!DOCTYPE x [<!ENTITY a "b">]><ACORD><ACORD formNumber="25">&a;</ACORD></ACORD>')
    with pytest.raises(ValueError):
        T.parse_elabel_xml("<ACORD>" + "x" * T._XML_MAX_CHARS + "</ACORD>")


def test_http_status_mapping():
    C = T.TranscriberClient
    for status, kind in ((401, "auth"), (403, "forbidden"), (413, "too_large"), (429, "quota"),
                         (400, "bad_request"), (504, "timeout"), (500, "server")):
        with pytest.raises(T.TranscriberError) as ex:
            C._raise_for(status, "body")
        assert ex.value.kind == kind
    C._raise_for(202, ""); C._raise_for(200, "")


def test_result_round_trips_through_json():
    res = T.parse_poll_reply(json.dumps(_default_body()), {})
    again = T.TranscriberResult.from_json(json.loads(json.dumps(res.to_json())))
    assert [f.form_number for f in again.forms] == [f.form_number for f in res.forms]
    assert again.forms[0].boxes["NamedInsured_FullName_A"].bbox == (40, 300, 400, 320)


# ── the client through the stub: no network, usage accounted, caps held ───────
def test_extract_through_the_stub_counts_pages_and_refuses_past_the_daily_cap():
    calls = []

    async def usage(pages, env):
        calls.append((pages, env))
        return sum(p for p, _ in calls)

    # the stub answers without accounting (nothing was sent)
    c = T.TranscriberClient(_stub_cfg(), usage=usage)
    res = asyncio.run(c.extract(b"%PDF-1.4 stub", pages=3, label="125"))
    assert res.status == "done" and calls == []
    # a LIVE config accounts first and refuses past the cap - and never reaches the network
    live = _stub_cfg(stub_dir="", client_id="id", client_secret="s", api_key="k", daily_page_cap=5)
    c2 = T.TranscriberClient(live, usage=usage)
    with pytest.raises(T.TranscriberError) as ex:
        asyncio.run(c2.extract(b"%PDF", pages=6, label="125"))
    # counted, refused, refunded: a request that never reached ASG is not a transaction (review, 29 Oct 2026)
    assert ex.value.kind == "quota" and calls == [(6, "uat"), (-6, "uat")]


def test_unconfigured_client_raises_unavailable_not_network():
    c = T.TranscriberClient(_stub_cfg(stub_dir="", enabled=True))
    with pytest.raises(T.TranscriberError) as ex:
        asyncio.run(c.extract(b"%PDF", pages=1))
    assert ex.value.kind == "unavailable"


# ── routing ───────────────────────────────────────────────────────────────────
def _record(pages):
    return {"pages": [{"page": i + 1, "kind": k, "form_id": None, "acord_number": n, "edition": "2025/03"}
                      for i, (k, n) in enumerate(pages)]}


def test_plan_never_sends_a_primble_record_and_skips_over_the_page_cap(tmp_path):
    import pikepdf
    pdf = tmp_path / "f.pdf"
    p = pikepdf.new()
    for _ in range(3):
        p.add_blank_page(page_size=(612, 792))
    p.save(str(pdf))
    rec = _record([("flattened", "125"), ("flattened", "125"), (None, None)])
    cfg = _stub_cfg()
    ocr = "\n".join(f"[Document page {i}]\nACORD 125 (2025/03) Page {i} of 3" for i in (1, 2, 3))
    assert TI.plan(str(pdf), rec, has_primble_record=True, cfg=cfg, ocr_text=ocr) is None
    # a page showing only the footer (no copyright, no "Page n of m") is never paid for
    assert TI.plan(str(pdf), rec, has_primble_record=False, cfg=cfg) is None
    g = TI.plan(str(pdf), rec, has_primble_record=False, cfg=cfg, ocr_text=ocr)
    assert g is not None and g.pages == [0, 1] and not g.whole_file and g.hash
    assert TI.plan(str(pdf), rec, has_primble_record=False, cfg=_stub_cfg(max_pages_per_package=1), ocr_text=ocr) is None
    # fillable pages follow the switch
    rec2 = _record([("fillable", "126"), ("fillable", "126"), ("fillable", "126")])
    assert TI.plan(str(pdf), rec2, has_primble_record=False, cfg=_stub_cfg(send_fillable=False)) is None
    g2 = TI.plan(str(pdf), rec2, has_primble_record=False, cfg=cfg)
    assert g2 is not None and g2.whole_file and g2.pages == [0, 1, 2]
    # a dec (no ACORD pages) never goes
    assert TI.plan(str(pdf), {"pages": []}, has_primble_record=False, cfg=cfg) is None
    assert TI.plan(str(pdf), None, has_primble_record=False, cfg=cfg) is None


def test_plan_sends_an_image_only_when_its_ocr_text_shows_an_acord_footer(tmp_path):
    img = tmp_path / "scan.png"
    img.write_bytes(b"\x89PNG\r\n\x1a\nfake")
    cfg = _stub_cfg()
    assert TI.plan(str(img), None, has_primble_record=False, ocr_text="a declarations page", cfg=cfg) is None
    g = TI.plan(str(img), None, has_primble_record=False, ocr_text="... ACORD 140 (2016/03) Page 1 of 2", cfg=cfg)
    assert g is not None and g.input_format == "IMAGE" and g.acord_numbers == ["140"]


def test_fetch_prefers_the_cache_and_never_raises():
    g = TI.SendGroup(pages=[0, 1], acord_numbers=["125", "125"], kinds=["flattened"] * 2, data=b"%PDF", hash="h1")
    store = {}

    async def get(h, env):
        return store.get((h, env))

    async def put(h, env, result, **kw):
        store[(h, env)] = result

    c = T.TranscriberClient(_stub_cfg())
    r1 = asyncio.run(TI.fetch(g, client=c, cache_get=get, cache_put=put))
    assert r1.result is not None and not r1.cached and ("h1", "uat") in store
    r2 = asyncio.run(TI.fetch(g, client=c, cache_get=get, cache_put=put))
    assert r2.cached and r2.result.forms[0].form_number == "125"
    # a stub miss is a fallback, not an exception
    c_miss = T.TranscriberClient(_stub_cfg(stub_dir=os.path.join(STUB, "nowhere")))
    r3 = asyncio.run(TI.fetch(g, client=c_miss))
    assert r3.result is None and r3.error == "stub_miss"


# ── reply -> copies -> facts ──────────────────────────────────────────────────
def _group_and_result():
    g = TI.SendGroup(pages=[4, 5, 6], acord_numbers=["125"] * 3, kinds=["scanned"] * 3, data=b"%PDF", hash="h")
    res = T.parse_poll_reply(json.dumps(_default_body()), {})
    return g, res


def test_copies_map_pages_back_ticks_become_checks_and_rejected_pages_give_none():
    g, res = _group_and_result()
    copies = TI.copies_from(g, res)
    assert len(copies) == 1
    c = copies[0]
    assert c["form_id"] == "ACORD_125" and c["kind"] == "transcriber" and c["pages"] == [4, 5]
    assert c["boxes"]["NamedInsured_FullName_A"] == "Stubworks Fabrication LLC"
    assert c["kinds"]["NamedInsured_LegalEntity_LimitedLiabilityCorporationIndicator_A"] == "check"
    assert c["boxes"]["NamedInsured_LegalEntity_LimitedLiabilityCorporationIndicator_A"] == "Yes"
    assert "NamedInsured_LegalEntity_CorporationIndicator_A" not in c["boxes"]     # empty = unticked
    assert c["box_page"]["NamedInsured_AnnualRevenueAmount_A"] == 5
    assert c["confidence"]["NamedInsured_FullName_A"] == 99 and c["accuracy"] == 91


def test_unknown_form_numbers_get_a_generic_form_id():
    assert TI._form_id_for("125", "") == "ACORD_125"
    assert TI._form_id_for("137", "CO") == "ACORD_137_CO"
    assert TI._form_id_for("829", "") == "ACORD_829"
    assert TI._form_id_for("36", "TX") == "ACORD_36_TX"


def test_transcriber_facts_carry_the_transcriber_label_and_score():
    from services.acord_intake.read import boxes_to_facts, relabel_transcriber_facts
    g, res = _group_and_result()
    copies = TI.copies_from(g, res)
    facts, _carried = boxes_to_facts(copies)
    n = relabel_transcriber_facts(facts, copies)
    assert n > 0
    name = facts.get("applicant_name")
    assert isinstance(name, dict) and name["value"] == "Stubworks Fabrication LLC"
    assert name["confidence"] == "acord_transcriber" and name["source"] == "acord_form"
    assert name["confidence_score"] == 99 and name["reader"] == "transcriber"


def test_one_document_one_reading():
    from services.acord_intake.read import merge_transcriber_copies
    g, res = _group_and_result()
    t = TI.copies_from(g, res)[0]
    # (a) a FILLABLE in-house copy on the same pages keeps its values; Transcriber adds scores only
    mine = {"form_id": "ACORD_125", "copy": 1, "pages": [4, 5], "kind": "fillable", "edition": "2025/03",
            "boxes": {"NamedInsured_FullName_A": "Stubworks Fabrication, LLC"}, "kinds": {"NamedInsured_FullName_A": "text"},
            "box_page": {"NamedInsured_FullName_A": 4}}
    out = merge_transcriber_copies([mine], [t])
    assert len(out) == 1 and out[0]["kind"] == "fillable"
    assert out[0]["boxes"]["NamedInsured_FullName_A"] == "Stubworks Fabrication, LLC"
    assert out[0]["confidence"]["NamedInsured_FullName_A"] == 99 and out[0]["transcriber"]["accuracy"] == 91
    # (b) our OVERLAY read of a flattened page folds into the Transcriber copy
    overlay = {"form_id": "ACORD_125", "copy": 1, "pages": [4], "kind": "flattened", "edition": "2025/03",
               "boxes": {"NamedInsured_FullName_A": "Stubworks Fabrication LLC", "Producer_FullName_A": "Astrea"},
               "kinds": {"NamedInsured_FullName_A": "text", "Producer_FullName_A": "text"},
               "box_page": {"NamedInsured_FullName_A": 4, "Producer_FullName_A": 4}}
    out2 = merge_transcriber_copies([overlay], [t])
    assert len(out2) == 1 and out2[0]["kind"] == "transcriber" and out2[0]["overlay_folded"]
    assert out2[0]["boxes"]["Producer_FullName_A"] == "Astrea"
    # (c) no overlap: both stay, numbered in page order
    other = dict(overlay, pages=[0], form_id="ACORD_125")
    out3 = merge_transcriber_copies([other], [t])
    assert [c["copy"] for c in sorted(out3, key=lambda c: c["pages"][0])] == [1, 2]


# ── the whole path: a scanned outside 125 read through the stub ───────────────
def test_read_for_document_folds_the_transcriber_reading_in(tmp_path, monkeypatch):
    import pikepdf
    from services.acord_intake import intake
    pdf = tmp_path / "outside_125.pdf"
    p = pikepdf.new()
    for _ in range(3):
        p.add_blank_page(page_size=(612, 792))
    p.save(str(pdf))
    text = "\n".join(f"[Document page {i}]\nsome scanned words ACORD 125 (2025/03) Page {i} of 3" for i in (1, 2, 3))
    monkeypatch.setenv("TRANSCRIBER", "1")
    TI.reset_client()
    rec_before = (intake.read_for_document(str(pdf), text) or {}).get("record") or {}
    assert [pg["kind"] for pg in rec_before.get("pages") or []] == ["scanned"] * 3
    gr = asyncio.run(TI.read_document(str(pdf), rec_before, has_primble_record=False, ocr_text=text))
    assert gr is not None and gr.result is not None and gr.group.pages == [0, 1, 2]
    acord = intake.read_for_document(str(pdf), text, transcriber=gr)
    assert acord["classification"]["doc_type"] == "application"
    assert acord["classification"]["reader"] == "transcriber"
    assert acord["facts"]["applicant_name"]["confidence"] == "acord_transcriber"
    rec = acord["record"]
    assert rec["transcriber"]["forms"][0]["form_id"] == "ACORD_125"
    assert rec["transcriber"]["forms"][0]["pages"] == [1, 2] and rec["transcriber"]["pages_sent"] == 3
    assert rec["transcriber"]["rejected"][0]["pages"] == [3]
    # the rejected page stays "needs verification"; the read pages do not
    assert [u["page"] for u in rec.get("needs_verification") or []] == [3]
    # the model still reads the unread page's text, never the read pages'
    assert "[Document page 3]" in acord["other_text"] and "[Document page 1]" not in acord["other_text"]


def test_a_transcriber_box_is_please_verify_on_the_generated_form():
    from services.pdf_service import apply_transcriber_labels, prints_a_transcriber_value
    facts = {"applicant_name": {"value": "Stubworks Fabrication LLC", "source": "acord_form",
                                "confidence": "acord_transcriber", "confidence_score": 99}}
    mapped = {"NamedInsured_FullName_A": "Stubworks Fabrication LLC", "Producer_FullName_A": "Astrea"}
    conf = {"NamedInsured_FullName_A": "filled", "Producer_FullName_A": "filled"}
    out = apply_transcriber_labels("ACORD_125", facts, mapped, dict(conf))
    assert out["NamedInsured_FullName_A"] == "ai_verified" and out["Producer_FullName_A"] == "filled"
    assert prints_a_transcriber_value("ACORD_125", "NamedInsured_FullName_A", "Stubworks Fabrication LLC", facts)
    assert prints_a_transcriber_value("ACORD_125", "NamedInsured_FullName_A", "Someone Else", facts) is None


def test_no_secret_reaches_a_log_line(caplog):
    import logging
    caplog.set_level(logging.INFO)
    c = T.TranscriberClient(_stub_cfg(client_id="id-SECRET1", client_secret="SECRET2", api_key="SECRET3"))
    asyncio.run(c.extract(b"%PDF-1.4 stub", pages=1, label="125"))
    for rec in caplog.records:
        assert "SECRET" not in rec.getMessage()


# ── the pipeline door end to end (stub) ───────────────────────────────────────
def test_extract_document_reads_an_outside_scan_through_transcriber(tmp_path, monkeypatch):
    import pikepdf
    from services import extraction_pipeline as EP
    pdf = tmp_path / "scan_125.pdf"
    p = pikepdf.new()
    for _ in range(3):
        p.add_blank_page(page_size=(612, 792))
    p.save(str(pdf))
    text = "\n".join(f"[Document page {i}]\nscanned words of a commercial application ACORD 125 (2025/03) Page {i} of 3"
                     for i in (1, 2, 3))

    async def fake_text(_path):
        return text, []

    async def fake_llm(_text, _dtype, **_kw):
        return {"facts": {"operations_description": "model read this off the unread page"}, "flags": {}}

    monkeypatch.setattr(EP, "extract_text", fake_text)
    monkeypatch.setattr(EP, "extract_facts_long", fake_llm)
    monkeypatch.setenv("TRANSCRIBER", "1")
    TI.reset_client()
    doc = asyncio.run(EP.extract_document(str(pdf), "scan_125.pdf", "user-1"))
    assert doc and doc["doc_type"] == "application"
    assert doc["facts"]["applicant_name"]["value"] == "Stubworks Fabrication LLC"
    assert doc["facts"]["applicant_name"]["confidence"] == "acord_transcriber"
    assert doc["acord"]["transcriber"]["forms"][0]["form_id"] == "ACORD_125"
    assert doc["text"] == text                       # an outside document keeps its text as evidence
    # off: the same upload is read exactly as before (no transcriber record, model reads all pages)
    monkeypatch.setenv("TRANSCRIBER", "0")
    TI.reset_client()
    doc2 = asyncio.run(EP.extract_document(str(pdf), "scan_125.pdf", "user-1"))
    assert doc2 and "transcriber" not in (doc2.get("acord") or {})
    assert "applicant_name" not in doc2["facts"]


def test_a_primble_form_is_never_sent(tmp_path, monkeypatch):
    """A file carrying our record - decryptable or not - stays in-house."""
    import pikepdf
    from services.acord_intake import primble_record as PR
    pdf = tmp_path / "ours.pdf"
    p = pikepdf.new()
    p.add_blank_page(page_size=(612, 792))
    p.docinfo[PR.KEY] = pikepdf.String("not-even-decryptable")
    p.save(str(pdf))
    assert PR.carries_record(str(pdf)) is True
    rec = _record([("flattened", "125")])
    assert TI.plan(str(pdf), rec, has_primble_record=PR.carries_record(str(pdf)), cfg=_stub_cfg()) is None


def test_a_submitted_request_is_resumed_not_paid_twice():
    """A pending mark in the cache (submitted, never collected) makes the next
    attempt poll that request id instead of submitting - and paying - again."""
    g = TI.SendGroup(pages=[0], acord_numbers=["125"], kinds=["scanned"], data=b"%PDF", hash="h-pend")
    store = {("h-pend", "uat"): {"status": "pending", "request_id": "req-OLD", "submitted_at": TI._now_iso()}}
    seen = {}

    async def get(h, env):
        return store.get((h, env))

    async def put(h, env, result, **kw):
        store[(h, env)] = result

    class Spy(T.TranscriberClient):
        async def extract(self, data, **kw):
            seen.update(kw)
            return T.parse_poll_reply(json.dumps(_default_body()), {})

    r = asyncio.run(TI.fetch(g, client=Spy(_stub_cfg()), cache_get=get, cache_put=put))
    assert r.result is not None and seen["resume_request_id"] == "req-OLD"
    assert store[("h-pend", "uat")]["status"] == "done"            # the result replaced the mark
    # a stale mark (older than an hour) is not resumed
    store[("h-pend", "uat")] = {"status": "pending", "request_id": "req-STALE", "submitted_at": "2020-01-01T00:00:00+00:00"}
    seen.clear()
    asyncio.run(TI.fetch(g, client=Spy(_stub_cfg()), cache_get=get, cache_put=put))
    assert seen["resume_request_id"] == ""


def test_transcriber_readings_are_policed_by_the_merge_not_lifted_out(tmp_path, monkeypatch):
    """`read_keys` lists only the EXACT box reads; a Transcriber value stays under
    the merge's guards (a label OCR'd as a value must be refusable)."""
    import pikepdf
    from services.acord_intake import intake
    pdf = tmp_path / "scan.pdf"
    p = pikepdf.new()
    for _ in range(3):
        p.add_blank_page(page_size=(612, 792))
    p.save(str(pdf))
    text = "\n".join(f"[Document page {i}]\nACORD 125 (2025/03) Page {i} of 3" for i in (1, 2, 3))
    monkeypatch.setenv("TRANSCRIBER", "1")
    TI.reset_client()
    rec = (intake.read_for_document(str(pdf), text) or {}).get("record") or {}
    gr = asyncio.run(TI.read_document(str(pdf), rec, has_primble_record=False, ocr_text=text))
    acord = intake.read_for_document(str(pdf), text, transcriber=gr)
    assert "applicant_name" in acord["facts"]
    assert "applicant_name" not in acord["record"]["read_keys"]


def test_auth_style_flips_once_after_a_401(monkeypatch):
    live = _stub_cfg(stub_dir="", client_id="id", client_secret="s", api_key="k")
    c = T.TranscriberClient(live)
    calls = {"submit": 0}

    async def token():
        return "tok"

    async def submit(data, *, input_format="PDF", trace=None):
        calls["submit"] += 1
        if calls["submit"] == 1:
            raise T.TranscriberError("auth", "401", status=401)
        return "req-1", trace or "t"

    async def fetch(rid, trace=None):
        return T.parse_poll_reply(json.dumps(_default_body()), {})

    monkeypatch.setattr(c, "token", token)
    monkeypatch.setattr(c, "submit", submit)
    monkeypatch.setattr(c, "fetch", fetch)
    assert c._bearer is False
    res = asyncio.run(c.extract(b"%PDF", pages=1))
    assert res.status == "done" and calls["submit"] == 2 and c._bearer is True and c._auth_flipped


# ── the REAL reply (UAT probe, 29 Oct 2026: our flattened CH125 ACORD 125, 5 pages) ──
def _real_probe():
    with open(os.path.join(STUB, "real_125_probe.json"), encoding="utf-8") as fh:
        return json.load(fh)


def test_the_real_reply_is_one_form_spanning_its_boxes_pages_with_ticks_as_1_and_0():
    res = T.parse_poll_reply(json.dumps(_real_probe()), {})
    assert res.status == "done" and len(res.forms) == 1
    f = res.forms[0]
    assert (f.form_number, f.edition, f.accuracy, f.status) == ("125", "2025/03", 99.0, "Success")
    assert f.pages == [1, 2, 3, 4, 5]                      # one element, boxes on five pages
    ticks = {b: x.value for b, x in f.boxes.items() if "Indicator" in b and x.value}
    assert set(ticks.values()) == {"0", "1"}
    # the newest 125 prints ONE name-and-address box: no FullName box comes back,
    # the block sits in the mailing-address box (split by `copies_from`)
    assert "NamedInsured_FullName_A" not in f.boxes
    assert f.boxes["NamedInsured_MailingAddress_LineOne_A"].value.startswith("Cumberland Hearth")


def test_the_real_reply_maps_to_the_same_facts_our_own_reader_gives():
    from services.acord_intake.read import boxes_to_facts
    res = T.parse_poll_reply(json.dumps(_real_probe()), {})
    g = TI.SendGroup(pages=[10, 11, 12, 13, 14], acord_numbers=["125"] * 5, kinds=["flattened"] * 5, data=b"", hash="r")
    copies = TI.copies_from(g, res)
    assert len(copies) == 1 and copies[0]["pages"] == [10, 11, 12, 13, 14]
    c = copies[0]
    types = TI._schema_types("ACORD_125")
    assert all(v != "0" for b, v in c["boxes"].items() if types.get(b) == "/Btn")   # unticked tick = no box
    assert c["boxes"]["BusinessInformation_PartTimeEmployeeCount_B"] == "0"          # a count of 0 is a value
    assert "Policy_LineOfBusiness_CyberAndPrivacy_A" not in c["boxes"]                 # "0" on a /Btn = unticked
    assert TI._box_kind("Policy_LineOfBusiness_CyberAndPrivacy_A", "1", "ACORD_125") == "check"   # no "Indicator" in its name
    assert TI._box_kind("Policy_LineOfBusiness_CyberAndPrivacy_A", "0", "ACORD_125") is None
    assert sum(1 for k in c["kinds"].values() if k == "check") >= 30
    # the name split out of the combined block, the block keeps the address
    assert c["boxes"]["NamedInsured_FullName_A"] == "Cumberland Hearth & Hospitality Supply, Inc."
    assert c["boxes"]["NamedInsured_MailingAddress_LineOne_A"].startswith("P.O. Box 41120")
    facts, carried = boxes_to_facts(copies)
    got = {k: (v.get("value") if isinstance(v, dict) else v) for k, v in facts.items()}
    assert got["applicant_name"] == "Cumberland Hearth & Hospitality Supply, Inc."
    assert got["fein"] == "62-3418806" and got["naics_code"] == "423440" and got["sic_code"] == "5046"
    assert got["effective_date"] == "12/01/2026" and got["entity_type"] == "Corporation"
    assert len(got["property_locations"]) == 4 and len(got["loss_history"]) == 3
    assert c["box_page"]["NamedInsured_FullName_A"] == 10 and c["box_page"]["LossHistory_ClaimDate_A"] in (12, 13)


def test_request_id_is_found_in_every_plausible_submit_shape():
    R = T.request_id_from_submit_reply
    rid = "3fd88908-36e8-42d2-b9b9-a5634fe44c2c001"
    assert R(json.dumps({"status": "accepted", "requestId": rid, "callbackUrl": "x"})) == rid
    assert R(json.dumps({"callbackUrl": f"https://uat-api-v1-transcriber.acordsolutions.net/oauth/forms/extract/{rid}"})) == rid
    assert R(json.dumps({"message": "ok", "data": {"messageId": rid}})) == rid
    assert R(json.dumps({"body": {"request_id": rid}})) == rid
    assert R(json.dumps({"url": f"/oauth/forms/extract/{rid}?x=1"})) == rid
    assert R(json.dumps(rid)) == rid
    assert R(rid) == rid
    assert R("", {"Location": f"https://h/oauth/forms/extract/{rid}"}) == rid
    assert R(json.dumps({"status": "accepted", "message": "Message can be retrieved from the following URL"})) == ""


# ── review fixes (29 Oct 2026, hostile review) ────────────────────────────────
def test_list_facts_and_tick_derived_facts_are_transcribers_too_and_stay_under_the_merge_guards(tmp_path, monkeypatch):
    """The real reply gives 24 facts; 7 of them (locations, claims, lines, prior
    policies, named insureds, lines of business, entity_type from a tick group)
    carry no per-box envelope. They were neither labelled Transcriber nor kept out
    of `read_keys` - so an OCR'd table was lifted out of every merge guard and its
    boxes printed as exact. Now every key a Transcriber copy produces is excluded
    from `read_keys`, and a reading with no exact copy labels its box-less
    envelopes too."""
    import pikepdf
    from services.acord_intake import intake
    from services.acord_intake.read import boxes_to_facts, relabel_transcriber_facts
    res = T.parse_poll_reply(json.dumps(_real_probe()), {})
    g = TI.SendGroup(pages=[0, 1, 2, 3, 4], acord_numbers=["125"] * 5, kinds=["flattened"] * 5, data=b"", hash="r")
    copies = TI.copies_from(g, res)
    facts, _ = boxes_to_facts(copies)
    relabel_transcriber_facts(facts, copies)
    assert facts["entity_type"]["confidence"] == "acord_transcriber"       # tick-derived, no box
    assert facts["applicant_name"]["confidence_score"] is not None        # the per-box score still lands
    assert intake._transcriber_keys(copies) >= {"property_locations", "loss_history", "coverage_lines",
                                                "prior_coverage_by_line", "lines_of_business"}
    # through the document door: none of them is lifted out of the merge's guards
    pdf = tmp_path / "scan.pdf"
    p = pikepdf.new()
    for _ in range(5):
        p.add_blank_page(page_size=(612, 792))
    p.save(str(pdf))
    text = "\n".join(f"[Document page {i}]\nACORD 125 (2025/03) Page {i} of 5" for i in range(1, 6))
    gr = TI.GroupResult(group=g, result=res)
    acord = intake.read_for_document(str(pdf), text, transcriber=gr)
    assert "property_locations" in acord["facts"] and "loss_history" in acord["facts"]
    assert acord["record"]["read_keys"] == []
    # a reading WITH an exact copy keeps the exact copy's keys lifted
    exact = {"form_id": "ACORD_126", "copy": 1, "pages": [7], "kind": "fillable", "edition": "",
             "boxes": {"Producer_FullName_A": "Astrea"}, "kinds": {"Producer_FullName_A": "text"},
             "box_page": {"Producer_FullName_A": 7}, "raw": {}}
    facts2, _ = boxes_to_facts([exact] + copies)
    relabel_transcriber_facts(facts2, [exact] + copies)
    # the tick came from the Transcriber copy: its reading, even beside an exact
    # copy (production fuzz, 29 Oct 2026 - this pinned the old "left exact")
    assert facts2["entity_type"]["confidence"] == "acord_transcriber"


def test_a_terminal_envelope_with_no_body_is_a_failure_and_a_malformed_body_is_a_value_error():
    res = T.parse_poll_reply(json.dumps({"status": "FAILED", "message": "model error", "requestId": "r9"}), {})
    assert res.status == "failed" and res.request_id == "r9" and "model error" in res.message
    with pytest.raises(ValueError):
        T.parse_elabel_xml("<ACORD><ACORD formNumber='125'><Box>v</Bo")
    with pytest.raises(ValueError):
        T.parse_poll_reply(json.dumps({"responseBody": "<html><body>502 Bad Gateway<br></body></html>"}), {})
    # a well-formed page that is not an eLabel document reads as "done" with NO form:
    # `transcriber_intake.fetch` treats that as a fallback and never caches it
    assert T.parse_poll_reply(json.dumps({"responseBody": "<html><body>ok</body></html>"}), {}).forms == []


def test_an_empty_done_reply_is_a_fallback_and_is_never_cached():
    g = TI.SendGroup(pages=[0], acord_numbers=["125"], kinds=["scanned"], data=b"%PDF", hash="h-empty")
    store = {}

    async def get(h, env):
        return store.get((h, env))

    async def put(h, env, result, **kw):
        store[(h, env)] = result

    class Empty(T.TranscriberClient):
        async def extract(self, data, **kw):
            return T.TranscriberResult(status="done", request_id="r-empty", forms=[])

    r = asyncio.run(TI.fetch(g, client=Empty(_stub_cfg()), cache_get=get, cache_put=put))
    assert r.result is None and r.error == "empty"
    assert ("h-empty", "uat") not in store


def test_poll_errors_back_off_and_a_failed_submit_refunds_its_pages(monkeypatch):
    live = _stub_cfg(stub_dir="", client_id="id", client_secret="s", api_key="k", wait_seconds=200, poll_interval=0)
    ledger = []

    async def usage(pages, env):
        ledger.append(pages)
        return sum(ledger)

    c = T.TranscriberClient(live, usage=usage)
    sleeps = []

    async def fake_sleep(s):
        sleeps.append(s)
    monkeypatch.setattr(T.asyncio, "sleep", fake_sleep)

    async def token():
        return "tok"

    async def submit_ok(data, *, input_format="PDF", trace=None):
        return "req-1", trace or "t"
    polls = {"n": 0}

    async def fetch(rid, trace=None):
        polls["n"] += 1
        if polls["n"] <= 2:
            raise T.TranscriberError("quota", "429", retryable=True, status=429)
        return T.parse_poll_reply(json.dumps(_default_body()), {})
    monkeypatch.setattr(c, "token", token)
    monkeypatch.setattr(c, "submit", submit_ok)
    monkeypatch.setattr(c, "fetch", fetch)
    res = asyncio.run(c.extract(b"%PDF", pages=3))
    assert res.status == "done" and polls["n"] == 3
    assert [s for s in sleeps if s] == [5.0, 15.0]                 # two 429s, two backoffs
    assert ledger == [3]                                           # the pages were counted once
    # a submit that never reaches ASG gives its pages back
    async def submit_413(data, *, input_format="PDF", trace=None):
        raise T.TranscriberError("too_large", "413", status=413)
    monkeypatch.setattr(c, "submit", submit_413)
    with pytest.raises(T.TranscriberError):
        asyncio.run(c.extract(b"%PDF", pages=4))
    assert ledger == [3, 4, -4]
    # past the daily cap: refused BEFORE sending, and not left on the counter
    tiny = T.TranscriberClient(_stub_cfg(stub_dir="", client_id="id", client_secret="s", api_key="k", daily_page_cap=2),
                               usage=usage)
    monkeypatch.setattr(tiny, "token", token)
    with pytest.raises(T.TranscriberError) as ex:
        asyncio.run(tiny.extract(b"%PDF", pages=5))
    assert ex.value.kind == "quota" and ledger[-2:] == [5, -5]


# ── 29 Oct second pass: pre-submit, auth flip on 401 only, overlaps by form, no plaintext values ──
def test_presubmit_sends_every_outside_pdf_once_and_fetch_resumes_it(tmp_path, monkeypatch):
    import pikepdf
    from repositories import transcriber_repository as R
    pdf = tmp_path / "outside.pdf"
    p = pikepdf.new()
    for _ in range(2):
        p.add_blank_page(page_size=(612, 792))
    p.save(str(pdf))
    store, sent = {}, []

    async def get(h, env):
        return store.get((h, env))

    async def put(h, env, result, **kw):
        store[(h, env)] = result

    monkeypatch.setattr(R, "get_cached", get)
    monkeypatch.setattr(R, "put_cached", put)
    live = _stub_cfg(stub_dir="", client_id="id", client_secret="s", api_key="k")
    monkeypatch.setattr(TI, "load_config", lambda: live)

    class Fake(T.TranscriberClient):
        async def submit_only(self, data, **kw):
            sent.append(kw.get("pages"))
            return "req-PRE"
    monkeypatch.setattr(TI, "_default_client", lambda: Fake(live))
    from services.acord_intake import intake
    from services.acord_intake import recognize as RZ
    from services.acord_intake.recognize import PageForm
    monkeypatch.setattr(RZ, "recognize", lambda path, *a, **k: [
        PageForm(page=i, names=set(), text="", kind="flattened", acord_number="125", edition="2025/03") for i in (0, 1)])
    monkeypatch.setattr(TI, "_page_texts", lambda path, pages, ocr: {i: f"ACORD 125 (2025/03) Page {i + 1} of 2" for i in pages})
    n = asyncio.run(TI.presubmit_package([str(pdf), str(pdf) + ".txt"]))
    assert n == 1 and sent == [2]
    (hit,) = store.values()
    assert hit["status"] == "pending" and hit["request_id"] == "req-PRE"
    # a second pre-submit of the same file sends nothing
    assert asyncio.run(TI.presubmit_package([str(pdf)])) == 0 and sent == [2]


def test_presubmit_is_a_no_op_without_a_live_client():
    assert asyncio.run(TI.presubmit_package(["/nope.pdf"])) == 0


def test_auth_flip_only_on_a_real_401(monkeypatch):
    live = _stub_cfg(stub_dir="", client_id="id", client_secret="s", api_key="k")
    c = T.TranscriberClient(live)

    async def token():
        return "tok"

    async def submit(data, *, input_format="PDF", trace=None):
        raise T.TranscriberError("auth", "token endpoint answered 400", status=400)
    monkeypatch.setattr(c, "token", token)
    monkeypatch.setattr(c, "submit", submit)
    with pytest.raises(T.TranscriberError):
        asyncio.run(c.extract(b"%PDF", pages=1))
    assert c._auth_flipped is False and c._bearer is False


def test_a_transcriber_copy_naming_another_form_is_not_folded_into_ours():
    from services.acord_intake.read import merge_transcriber_copies
    g, res = _group_and_result()
    t = TI.copies_from(g, res)[0]                      # ASG says 125
    ours = {"form_id": "ACORD_126", "copy": 1, "pages": [4], "kind": "flattened", "edition": "2016/09",
            "boxes": {"GeneralLiability_Hazard_ClassificationCode_A": "91580"},
            "kinds": {"GeneralLiability_Hazard_ClassificationCode_A": "text"},
            "box_page": {"GeneralLiability_Hazard_ClassificationCode_A": 4}}
    out = merge_transcriber_copies([ours], [t])
    assert [c["form_id"] for c in out] == ["ACORD_126"] and out[0]["kind"] == "flattened"


def test_a_fillable_overlap_keeps_transcribers_boxes_on_pages_it_does_not_cover():
    from services.acord_intake.read import merge_transcriber_copies
    g, res = _group_and_result()
    t = TI.copies_from(g, res)[0]                      # pages [4, 5]
    mine = {"form_id": "ACORD_125", "copy": 1, "pages": [4], "kind": "fillable", "edition": "2025/03",
            "boxes": {"NamedInsured_FullName_A": "Stubworks Fabrication LLC"},
            "kinds": {"NamedInsured_FullName_A": "text"}, "box_page": {"NamedInsured_FullName_A": 4}}
    out = merge_transcriber_copies([mine], [t])
    extra = [c for c in out if c.get("kind") == "transcriber"]
    assert len(extra) == 1 and extra[0]["pages"] == [5]
    assert "NamedInsured_AnnualRevenueAmount_A" in extra[0]["boxes"]
    assert "NamedInsured_FullName_A" not in extra[0]["boxes"]


def test_the_document_record_keeps_no_values():
    g, res = _group_and_result()
    copies = TI.copies_from(g, res)
    entry = TI.record_entry(g, TI.GroupResult(group=g, result=res), copies)
    assert "elabels" not in entry["forms"][0]
    assert "Stubworks" not in json.dumps(entry)


def test_the_name_split_takes_only_the_insureds_block_and_never_an_address_line():
    B = T.TranscribedBox
    got = TI._split_names_from_address_blocks({
        "NamedInsured_MailingAddress_LineOne_A": B("Acme Hearth Inc.\nP.O. Box 1\nNashville TN"),
        "NamedInsured_MailingAddress_LineOne_B": B("Rural Route 2\nBox 9\nAmes IA"),
        "NamedInsured_MailingAddress_LineOne_C": B("Highway 70 East\nDickson TN"),
        "Producer_MailingAddress_LineOne_A": B("Example Agency\n1 Main St"),
        "AdditionalInterest_MailingAddress_LineOne_A": B("Brightline LP\n3300 W End Ave")})
    assert got == {"NamedInsured_FullName_A": "Acme Hearth Inc."}


def test_image_mime_comes_from_the_bytes():
    assert T._mime_of(b"\x89PNG\r\n\x1a\n") == "image/png"
    assert T._mime_of(b"\xff\xd8\xff\xe0") == "image/jpeg"
    assert T._mime_of(b"II*\x00abcd") == "image/tiff"


def test_the_gateway_request_id_header_is_never_taken_for_ours():
    assert T.request_id_from_submit_reply("{}", {"x-amzn-requestid": "gw-123"}) == ""


def test_one_page_budget_per_package():
    tok = TI._PACKAGE_BUDGET.set({"left": 6})
    try:
        assert TI._spend(5) is True
        assert TI._spend(2) is False          # 1 left
        assert TI._spend(1) is True
    finally:
        TI._PACKAGE_BUDGET.reset(tok)
    assert TI._spend(10 ** 6) is True          # no budget opened = no package cap


def test_usage_fails_closed_when_the_counter_cannot_be_written(monkeypatch):
    from repositories import transcriber_repository as R

    def broken():
        raise RuntimeError("db down")
    monkeypatch.setattr(R, "get_pool", broken)
    assert asyncio.run(R.add_usage(5, "uat")) > 10 ** 6
    assert asyncio.run(R.add_usage(-5, "uat")) == 0


def test_a_transport_error_on_submit_is_refunded(monkeypatch):
    calls = []

    async def usage(pages, env):
        calls.append(pages)
        return sum(calls)
    live = _stub_cfg(stub_dir="", client_id="id", client_secret="s", api_key="k")
    c = T.TranscriberClient(live, usage=usage)

    async def submit(*a, **k):
        raise TimeoutError("read timed out")
    monkeypatch.setattr(c, "submit", submit)
    with pytest.raises(T.TranscriberError):
        asyncio.run(c.extract(b"%PDF", pages=4))
    assert sum(calls) == 0
