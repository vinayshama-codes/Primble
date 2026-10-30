"""Choice Electric (stored session ca93ed8f, 5 Oct 2026) - round 3, 7 Oct 2026
(implementer DRYRUN).

#27 - "Before you generate": the download review's form checks (field QA's
hard blocks, the required boxes, the needs-attention Missing list) run on the
forms that WILL be generated, before they are (`services/form_dry_run`), and
list only what a person must supply - each with a fix route proven to fill the
box.

#18 - "this should have turned up TWO building property values": on a package
with two or more location rows the COPE cards open the location table for the
per-building values; the table carries roof material / roof year / protection
class / sprinkler with live ACORD 140 / 160 bindings; filling it clears the card.

The fixture is the stored session's own per-document extraction and the
producer's pre-form answers (tests/fixtures/choice_electric_loc_6oct.json).
No model call anywhere: every LLM entry point is replaced by a function that
fails the test if it is reached.
"""
import asyncio
import copy
import json
import os
import time
from functools import lru_cache

import pytest

from services import extraction_service as es
from services import form_dry_run as fdr
from services import pdf_service as ps
from services import schedule_capture as sc

_HERE = os.path.dirname(os.path.abspath(__file__))
_FIXTURE = os.path.join(_HERE, "fixtures", "choice_electric_loc_6oct.json")
_SCHEMAS = os.path.join(os.path.dirname(_HERE), "forms_schemas")


def _no_llm(*_a, **_k):
    raise AssertionError("the dry run reached a model call")


@pytest.fixture(autouse=True)
def _forbid_llm(monkeypatch):
    monkeypatch.setattr(ps, "_fetch_umbrella_period_sync", _no_llm)
    monkeypatch.setattr(ps, "_judge_evidence_batch", _no_llm)
    monkeypatch.setattr(ps, "_fill_unmatched_with_gpt", _no_llm)
    yield


@lru_cache(maxsize=1)
def _fixture() -> dict:
    with open(_FIXTURE, encoding="utf-8") as fh:
        return json.load(fh)


@lru_cache(maxsize=1)
def _merged():
    docs = [d for d in _fixture()["docs"] if not d.get("excluded")]
    mf, flags = es.merge_facts(docs, es.select_primary_truth(docs))
    return mf, flags


def _schema(form_id: str) -> dict:
    with open(os.path.join(_SCHEMAS, f"{form_id}_schema.json"), encoding="utf-8") as fh:
        return json.load(fh)


def _facts(answers: bool = True) -> dict:
    mf, _ = _merged()
    facts = copy.deepcopy(mf)
    if answers:
        for k, v in _fixture()["producer_answers"].items():
            facts[k] = {"value": v, "source": "producer", "confidence": "filled",
                        "value_state": "present"}
    return facts


def _session(facts: dict, recommendations=None) -> dict:
    from services.form_service import load_all_forms
    _, flags = _merged()
    return {"docs": [d for d in _fixture()["docs"] if not d.get("excluded")],
            "facts": facts, "flags": dict(flags), "all_forms": load_all_forms(),
            "recommendations": recommendations or []}


def _run(facts: dict, form_ids, **kw) -> dict:
    s = _session(facts)
    return fdr.run_dry_run(s, facts, s["flags"], form_ids=form_ids, session_id="ce-test", **kw)


def _items(out: dict, form_id: str):
    return [it for f in out["forms"] if f["form_id"] == form_id for it in f["items"]]


def _boxes(out: dict):
    return {(it["form_id"], b["field"]) for f in out["forms"] for it in f["items"] for b in it["boxes"]}


@lru_cache(maxsize=1)
def _run_125_140_answers() -> str:
    return json.dumps(_run(_facts(True), ["ACORD_125", "ACORD_140"]))


def _out_125_140() -> dict:
    return json.loads(_run_125_140_answers())


# ── 1. Building 2's genuinely missing COPE, before generation ────────────────

def test_building_two_cope_is_listed_before_the_forms_exist():
    out = _out_125_140()
    assert out["status"] == fdr.STATUS_READY
    items = {it["route"]["row"]: it for it in _items(out, "ACORD_140")}
    assert set(items) == {0, 1}
    # Building 2 (LOC 1 / BLDG 002): nothing the producer typed reaches its
    # block - the year / PC answers are ONE scalar, printed on building 1.
    assert items[1]["route"]["columns"] == ["year_built", "roof_material", "protection_class"]
    # Building 1 has the producer's year and PC; only roof material is missing
    # (no document states it - the run's "Composition" was a gap-fill guess).
    assert items[0]["route"]["columns"] == ["roof_material"]
    for it in items.values():
        # 25 Oct 2026: listed before forms, but Carrier-Grade COPE never blocks.
        assert it["blocks_download"] is False
        assert it["resolution"] == {"mode": "schedule", "schedule_key": "property_locations",
                                    "columns": it["route"]["columns"],
                                    "rows": [it["route"]["row"]]}
        assert "LOC 1" in it["label"] and "BLDG 00" in it["label"]
    assert {b["field"] for b in items[1]["boxes"]} == {
        "CommercialStructure_BuiltYear_B", "Construction_RoofMaterialCode_B",
        "BuildingFireProtection_ProtectionClassCode_B"}


def test_with_no_answers_both_buildings_list_year_roof_and_protection_class():
    out = _run(_facts(False), ["ACORD_140"])
    items = _items(out, "ACORD_140")
    cols = {it["route"]["row"]: it["route"]["columns"] for it in items if "row" in (it.get("route") or {})}
    assert cols == {0: ["year_built", "roof_material", "protection_class"],
                    1: ["year_built", "roof_material", "protection_class"]}
    # Occupancy is stated nowhere (package or building rows) and the 140's own
    # check reads it: its card is listed too (G18, 30 Oct 2026 - a deduction
    # always has a card; the TEST predated that and listed table rows only).
    assert [it["route"].get("facts") for it in items if "row" not in (it.get("route") or {})] == [["occupancy_type"]]
    assert out["blocking_count"] == 0     # 25 Oct 2026: listed, never a hard block


# ── 2. No false items ────────────────────────────────────────────────────────

def test_nothing_the_documents_state_is_listed():
    out = _out_125_140()
    boxes = _boxes(out)
    # Construction is printed per building in the documents - never asked.
    assert not any("ConstructionCode" in f for _fid, f in boxes)
    # Every kept box's route target is empty - nothing on file already answers it.
    facts = _facts(True)
    for f in out["forms"]:
        for it in f["items"]:
            r = it["route"]
            targets = ([{**r, "column": c} for c in r["columns"]] if r["mode"] == "schedule" else [r])
            for t in targets:
                assert not fdr._filled(fdr._route_target_value(facts, t)), (f["form_id"], t)


def test_no_signature_and_no_guard_copy_is_ever_an_item():
    out = _out_125_140()
    for _fid, field in _boxes(out):
        assert "Signature" not in field and "Initials" not in field
    assert out["dropped"].get(fdr.R_APPLICANT, 0) >= 1          # the applicant's own step
    # Nothing the guards refused is a request (held back = a value was found).
    assert fdr.R_HELD not in {it.get("reason") for f in out["forms"] for it in f["items"]}


def test_every_item_has_a_route_the_stamper_proves():
    out = _out_125_140()
    facts = _facts(True)
    _, flags = _merged()
    stamp = {**facts, **flags, "_package_form_ids": ["ACORD_125", "ACORD_140"]}
    for f in out["forms"]:
        schema = _schema(f["form_id"])
        for it in f["items"]:
            assert it["resolution"]["mode"] in ("field", "schedule", "narrative")
            for b in it["boxes"]:
                r = it["route"]
                if r["mode"] == "schedule":
                    col = next(c for c in r["columns"]
                               if ps._schedule_def_for_base(b["field"][:-2]).sub_key == c)
                    r = {"mode": "schedule", "schedule_key": r["schedule_key"],
                         "column": col, "row": r["row"]}
                assert fdr.route_fills(f["form_id"], schema, [b["field"]], stamp, r), b


def test_a_declarations_entry_that_names_the_value_drops_the_item():
    facts = _facts(True)
    held = facts.get("dec_page_entries")
    entries = list((held.get("value") if isinstance(held, dict) else held) or [])
    entries.append({"label": "Protection Class", "value": "3", "owner": "policy",
                    "section": "COMMERCIAL PROPERTY"})
    facts["dec_page_entries"] = entries
    out = _run(facts, ["ACORD_140"])
    cols = {it["route"]["row"]: it["route"]["columns"] for it in _items(out, "ACORD_140")}
    assert "protection_class" not in cols.get(1, [])
    assert out["dropped"].get(fdr.R_DOCS, 0) >= 1


def test_a_key_detail_already_on_the_page_is_not_listed_twice():
    out = _out_125_140()
    kd = __import__("services.sqs_service", fromlist=["key_details"]).key_details(
        _facts(True), _merged()[1])
    kd_facts = {f for it in kd.get("missing_items") or []
                for f in ((it.get("resolution") or {}).get("facts") or [])}
    for f in out["forms"]:
        for it in f["items"]:
            if it["route"]["mode"] == "field":
                assert not set(it["route"]["facts"]) <= kd_facts


# ── 3. Filling the table empties it ──────────────────────────────────────────

def _save_table(facts: dict, edits: dict) -> None:
    from services.arq_service import _write_schedule_rows
    rows = sc.rows_from_facts("property_locations", facts)
    for idx, cells in edits.items():
        rows[idx].update(cells)
    clean, _ = sc.validate_rows("property_locations", rows)
    _write_schedule_rows(facts, "property_locations", clean, "producer")


def test_filling_the_location_table_empties_the_140_list_and_its_hard_blocks():
    from services.field_qa import check_hard_block
    facts = _facts(True)
    _save_table(facts, {0: {"roof_material": "Metal"},
                        1: {"year_built": "2001", "roof_material": "Metal",
                            "protection_class": "3"}})
    out = _run(facts, ["ACORD_140"])
    assert _items(out, "ACORD_140") == []
    gen, _ = fdr.stamp_forms(_session(facts), ["ACORD_140"], facts, _merged()[1])
    m = gen["ACORD_140"]["mapped"]
    assert m["Construction_RoofMaterialCode_A"] == "Metal"
    assert m["Construction_RoofMaterialCode_B"] == "Metal"
    assert m["CommercialStructure_BuiltYear_B"] == "2001"
    assert m["BuildingFireProtection_ProtectionClassCode_B"] == "3"
    assert m["CommercialStructure_BuiltYear_A"] == "2001"            # the scalar, row A
    assert check_hard_block(gen, merged_facts=facts) == []


# ── 4. Parity with the download review ───────────────────────────────────────

def test_the_dry_run_promises_exactly_what_the_download_gate_blocks():
    from services.field_qa import check_hard_block, run_field_qa
    from services.needs_attention import STATUS_MISSING, needs_attention_for_session
    facts = _facts(True)
    _, flags = _merged()
    ids = ["ACORD_125", "ACORD_140"]
    out = _out_125_140()
    gen, _ = fdr.stamp_forms(_session(facts), ids, facts, flags)
    # The download gate on the same stamped forms - the function download_routes calls.
    gate = {(b["form_id"], b["field"]) for b in check_hard_block(gen, merged_facts=facts)}
    kept_blocking = {(it["form_id"], b["field"]) for f in out["forms"] for it in f["items"]
                     for b in it["boxes"] if b["blocks_download"]}
    dropped_blocking = {(b["form_id"], b["field"]) for b in out["dropped_blocking"]}
    assert gate == kept_blocking | dropped_blocking
    assert kept_blocking == gate          # nothing blocking was lost (25 Oct: none here)
    # Every other kept box is a finding the download review itself lists.
    qa = run_field_qa(gen, merged_facts=facts, flags=flags)
    att = needs_attention_for_session(gen, facts, flags=flags)
    listed = {(r["form_id"], r["field"]) for r in qa["results"]
              if r["reason_code"] in ("missing_required", "missing_required_gate")}
    listed |= {(f["form_id"], r["field"]) for f in att["forms"] for r in f["rows"]
               if r["status"] == STATUS_MISSING}
    assert _boxes(out) <= listed


def test_the_dry_run_calls_the_download_reviews_own_functions(monkeypatch):
    import services.field_qa as fq
    import services.needs_attention as na
    seen = []
    real_qa, real_na = fq.run_field_qa, na.needs_attention_for_session
    monkeypatch.setattr(fq, "run_field_qa", lambda *a, **k: (seen.append("qa"), real_qa(*a, **k))[1])
    monkeypatch.setattr(na, "needs_attention_for_session",
                        lambda *a, **k: (seen.append("na"), real_na(*a, **k))[1])
    _run(_facts(True), ["ACORD_140"])
    assert seen == ["qa", "na"]


def test_the_probe_is_the_stampers_own_pass_1():
    """`_pass1_value` mirrors `compute_form_gaps` box for box - so a route the
    probe calls working is a route generation stamps."""
    facts = _facts(True)
    _, flags = _merged()
    for fid in ("ACORD_140", "ACORD_126", "ACORD_127"):
        schema = _schema(fid)
        stamp = {**facts, **flags, "_package_form_ids": [fid]}
        mapped, _unmatched, _det = ps.compute_form_gaps(fid, schema, stamp)
        for field in schema:
            got = fdr._pass1_value(fid, schema, field, stamp)
            want = mapped.get(field)
            assert fdr._filled(got) == fdr._filled(want), (fid, field, got, want)
            if fdr._filled(want):
                assert str(got) == str(want), (fid, field)


def test_the_full_recommended_set_runs_with_no_model_call_and_names_its_forms():
    from services.form_service import load_all_forms, match_forms
    facts = _facts(True)
    _, flags = _merged()
    text = "\n".join(d.get("text") or "" for d in _fixture()["docs"])
    recs = match_forms(facts, flags, load_all_forms(), text=text)
    s = _session(facts, recommendations=recs)
    ids, source = fdr.dry_run_form_ids(s)
    assert source == "recommended"
    assert {"ACORD_125", "ACORD_140"} <= set(ids)
    required = {r["form_id"] for r in recs if r.get("tier") == "required"}
    assert set(ids) <= required | {i for i in ids if "__" in i}
    out = fdr.run_dry_run(s, facts, flags, session_id="ce-full")
    assert out["status"] == fdr.STATUS_READY
    assert [f["form_id"] for f in out["checked_forms"]] == ids
    # Only the 125 premises / producer boxes and the 140 per-building COPE remain
    # as BOXES. Since 13 Oct 2026 (Choice Electric #22) a form's own checklist
    # card is listed too, on any form - a typed fact with no box of its own.
    boxed = {f["form_id"] for f in out["forms"] for it in f["items"] if it["boxes"]}
    assert boxed <= {"ACORD_125", "ACORD_140"}
    for f in out["forms"]:
        for it in f["items"]:
            if not it["boxes"]:
                assert it["route"]["mode"] == "field" and it["route"]["facts"]
                assert it["resolution"]["mode"] == "field"


def test_ticked_forms_win_and_unknown_ids_are_dropped():
    s = _session(_facts(True), recommendations=[{"form_id": "ACORD_125", "tier": "required"}])
    assert fdr.dry_run_form_ids(s, ["ACORD_140", "NOT_A_FORM", "ACORD_140"]) == (["ACORD_140"], "selected")
    assert fdr.dry_run_form_ids(s) == (["ACORD_125"], "recommended")
    s["recommendations"] = [{"form_id": "ACORD_101", "tier": "recommended"}]
    assert fdr.dry_run_form_ids(s) == (["ACORD_101"], "recommended")
    s["recommendations"] = []
    assert fdr.dry_run_form_ids(s) == ([], "recommended")
    empty = fdr.run_dry_run(s, {}, {}, session_id="empty")
    assert empty["status"] == fdr.STATUS_READY and empty["count"] == 0


# ── 5. Cache and time bound ──────────────────────────────────────────────────

def test_the_cache_is_keyed_by_facts_and_forms():
    fdr.clear_cache()
    facts = _facts(True)
    s = _session(facts)
    k1, f1, _ = fdr.submit(s, facts, s["flags"], ["ACORD_140"], session_id="c1")
    first = f1.result(timeout=120)
    k2, f2, _ = fdr.submit(s, facts, s["flags"], ["ACORD_140"], session_id="c1")
    assert k1 == k2 and f2.done() and f2.result() is first
    changed = copy.deepcopy(facts)
    changed["roof_year"] = {"value": "2015", "source": "producer"}
    k3, f3, _ = fdr.submit(s, changed, s["flags"], ["ACORD_140"], session_id="c1")
    assert k3 != k1
    f3.result(timeout=120)
    k4, _f4, _ = fdr.submit(s, facts, s["flags"], ["ACORD_126"], session_id="c1")
    assert k4 != k1
    _f4.result(timeout=120)


def test_a_slow_run_answers_pending_then_lands_in_the_cache(monkeypatch):
    fdr.clear_cache()

    def slow(session, facts=None, flags=None, form_ids=None, **kw):
        time.sleep(0.6)
        out = fdr._base_payload(fdr.STATUS_READY, kw["_resolved"][0], kw["_resolved"][1], kw["_key"])
        out["count"] = 7
        return out

    monkeypatch.setattr(fdr, "run_dry_run", slow)
    s = _session(_facts(True))
    first = asyncio.run(fdr.dry_run_payload(s, s["facts"], s["flags"], ["ACORD_140"],
                                            session_id="slow", wait=0.05))
    assert first["status"] == fdr.STATUS_PENDING and first["count"] == 0 and first["reason"]
    time.sleep(1.0)
    again = asyncio.run(fdr.dry_run_payload(s, s["facts"], s["flags"], ["ACORD_140"],
                                            session_id="slow", wait=0.05))
    assert again["status"] == fdr.STATUS_READY and again["count"] == 7
    assert again["fingerprint"] == first["fingerprint"]


def test_a_run_over_budget_or_failing_says_it_was_skipped(monkeypatch):
    out = _run(_facts(True), ["ACORD_140", "ACORD_126"], budget_seconds=1e-9)
    assert out["status"] == fdr.STATUS_SKIPPED and out["reason"] and out["count"] == 0
    monkeypatch.setattr(fdr, "review_findings", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("x")))
    out = _run(_facts(True), ["ACORD_140"])
    assert out["status"] == fdr.STATUS_SKIPPED and out["forms"] == []


def test_no_dry_run_once_forms_exist():
    s = _session(_facts(True))
    s["generated_forms"] = {"ACORD_140": {}}
    assert asyncio.run(fdr.dry_run_payload(s, s["facts"], s["flags"])) is None


# ── 6. Every pre-form response carries it ────────────────────────────────────

def test_the_pre_form_status_carries_the_dry_run(monkeypatch):
    from routes import form_routes as fr

    async def fake(row, facts, flags, form_ids=None, **kw):
        return {"status": "ready", "count": 3, "sid": kw.get("session_id")}

    monkeypatch.setattr(fdr, "dry_run_payload", fake)
    monkeypatch.setattr(fr, "current_package_sqs", lambda *a, **k: {"package_sqs_score": 70})
    row = _session(_facts(True))
    status = asyncio.run(fr._pre_form_status("sid-1", row["facts"], row["flags"], {},
                                             {"id": "u"}, session_row=row))
    pkg, kd = status
    assert pkg == {"package_sqs_score": 70} and isinstance(kd, dict)
    assert status.dry_run == {"status": "ready", "count": 3, "sid": "sid-1"}
    held = asyncio.run(fr._pre_form_status("sid-1", {}, {}, {"review_required": True}, {"id": "u"}))
    assert held == (None, None) and held.dry_run is None


def test_every_pre_form_handler_ships_dry_run():
    import ast
    import io
    path = os.path.join(_HERE, "..", "routes", "form_routes.py")
    tree = ast.parse(io.open(path, encoding="utf-8").read())
    bodies = {n.name: n for n in ast.walk(tree) if isinstance(n, (ast.AsyncFunctionDef, ast.FunctionDef))}
    for name in ("upload_declaration", "submission_integrity_resolve", "document_reclassify",
                 "underwriting_confirm_value", "get_extraction_result"):
        keys = {k.value for n in ast.walk(bodies[name]) if isinstance(n, ast.Dict)
                for k in n.keys if isinstance(k, ast.Constant)}
        assert "dry_run" in keys, f"{name} does not ship the dry run"


# ── 7. #18: the COPE card on 2+ buildings opens the location table ───────────

def _cope_view(facts: dict, code: str):
    from services.issue_registry import build_grouped_view, make_issue
    msg = {"carrier_grade_cope_incomplete": "Carrier-Grade COPE detail incomplete - missing: x",
           "minimum_viable_cope_missing": "Property submission missing Minimum Viable COPE: x"}[code]
    issue = make_issue(code, "soft_warning", msg, ["ACORD_140"])
    view = build_grouped_view([issue], [], [msg], facts=facts)
    clusters = [c for tier in view["warnings"].values() for c in tier]
    return clusters[0]["items"][0]["resolution"], clusters[0]["resolution"]


def _rows(n: int):
    return [{"location_number": "1", "building_number": str(i + 1), "construction_type": "Frame"}
            for i in range(n)]


@pytest.mark.parametrize("code", ["carrier_grade_cope_incomplete", "minimum_viable_cope_missing"])
def test_one_building_cards_are_byte_identical(code):
    from services.issue_registry import resolution_for
    # (28 Oct 2026: with NO premises anywhere the Minimum Viable card also shows
    # the premises address box - `premises_cope._with_premises_box`; a stated
    # address keeps the one-building card byte-identical.)
    for facts in ({"locations": ["100 Main St"]}, {"property_locations": _rows(1)},
                  {"property_locations": [], "locations": ["100 Main St"]}):
        item_res, cluster_res = _cope_view(facts, code)
        assert item_res == resolution_for(code) and cluster_res == resolution_for(code)
    item_res, _ = _cope_view({"occupancy_type": None}, code)
    if code == "minimum_viable_cope_missing":
        assert item_res["facts"] == ["locations"] + resolution_for(code)["facts"]
    else:
        assert item_res == resolution_for(code)


def test_two_buildings_route_the_carrier_grade_card_to_the_table():
    facts = {"property_locations": _rows(2), "occupancy_type": "Office",
             "construction_type": "Frame", "valuation_method": "RCV",
             "coinsurance_percentage": "80%"}
    res, cluster = _cope_view(facts, "carrier_grade_cope_incomplete")
    assert res["mode"] == "schedule" and res["schedule_key"] == "property_locations"
    assert res["columns"] == ["year_built", "roof_year", "sprinkler", "protection_class"]
    assert "facts" not in res and cluster == res
    # A package-level value still missing rides along as a typed input.
    facts.pop("valuation_method")
    res, _ = _cope_view(facts, "carrier_grade_cope_incomplete")
    assert res["facts"] == ["valuation_method"] and res["controls"]["valuation_method"]


def test_occupancy_only_is_just_its_box_and_values_route_together():
    # REVERSED 7 Oct 2026 round 4 (owner, Brent #18): this test pinned "an
    # occupancy-only card stays a field card" - the TEST was wrong under the new
    # decision. That card showed building 1's construction and values as THE
    # package's on a two-building package; every COPE card now opens the table.
    # REVERSED AGAIN 21 Oct 2026 (Brent 17 Oct item 8, b-cope-one-store: "ask
    # only what is missing") for the occupancy-only card: a field window with
    # JUST the occupancy box - no table, and still no per-building box, so the
    # round-4 defect cannot come back. The second half below is unchanged.
    facts = {"property_locations": _rows(2), "construction_type": "Frame",
             "property_building_value": "$1"}
    res, cluster = _cope_view(facts, "minimum_viable_cope_missing")
    assert res["mode"] == "field" and res["facts"] == ["occupancy_type"]
    assert "columns" not in res and cluster == res
    facts = {"property_locations": _rows(2)}
    res, _ = _cope_view(facts, "minimum_viable_cope_missing")
    assert res["mode"] == "schedule"
    assert res["columns"] == ["construction_type", "building_value", "bpp_value"]
    assert res["facts"] == ["occupancy_type"]


def test_the_routed_table_can_hold_every_column_it_asks_for():
    from services.premises_cope import PER_BUILDING_COPE
    cols = {c["key"] for c in sc.SCHEDULE_DEFS["property_locations"]["columns"]}
    assert set(PER_BUILDING_COPE.values()) <= cols
    from tests.test_schedule_capture import test_every_schedule_column_binds_to_a_live_acord_field
    test_every_schedule_column_binds_to_a_live_acord_field()
    s140 = _schema("ACORD_140")
    for base, col in (("Construction_RoofMaterialCode", "roof_material"),
                      ("BuildingFireProtection_ProtectionClassCode", "protection_class"),
                      ("BuildingFireProtection_Alarm_SprinklerPercent", "sprinkler"),
                      ("BuildingImprovement_RoofingYear", "roof_year")):
        assert ps._SCHEDULE_REGISTRY[base].sub_key == col
        assert f"{base}_A" in s140 and f"{base}_B" in s140


def test_filling_the_table_clears_the_card_and_partial_rows_do_not():
    from services.cross_form_validator import _check_carrier_grade_cope_quality
    from services.sqs_service import evaluate_stops
    base = {"property_locations": [{"location_id": "L1", "location_number": "1", "building_number": "1",
                                    "construction_type": "Frame", "building_value": "$1"},
                                   {"location_id": "L2", "location_number": "1", "building_number": "2",
                                    "construction_type": "Frame", "building_value": "$1"}],
            "occupancy_type": "Office", "construction_type": "Frame",
            "property_building_value": "$1", "valuation_method": "RCV",
            "coinsurance_percentage": "80%", "locations": ["a", "b"]}
    flags = {"has_property_coverage": True}
    assert _check_carrier_grade_cope_quality(base, flags, {"ACORD_140"})
    partial = copy.deepcopy(base)
    _save_table(partial, {0: {"year_built": "1990", "roof_year": "2011", "sprinkler": "100",
                              "protection_class": "3"}})
    assert _check_carrier_grade_cope_quality(partial, flags, {"ACORD_140"})   # building 2 open
    full = copy.deepcopy(base)
    cells = {"year_built": "1990", "roof_year": "2011", "sprinkler": "100", "protection_class": "3"}
    _save_table(full, {0: dict(cells), 1: dict(cells, year_built="2001")})
    assert _check_carrier_grade_cope_quality(full, flags, {"ACORD_140"}) == []
    _hard, soft = evaluate_stops(full, flags)
    assert not any("Carrier-Grade COPE" in m for m in soft)
    assert es._fv(full, "year_built") == "1990"                     # row 1 = ACORD row A
    assert full["year_built"]["derivation"]["rule"] == "premises_rows"


def test_a_derived_value_follows_the_rows_and_never_overwrites_a_typed_one():
    from services.premises_cope import derive_package_cope
    facts = {"property_locations": [{"roof_year": "2011"}, {"roof_year": "2012"}],
             "year_built": {"value": "1975", "source": "producer"}}
    facts["property_locations"][0]["year_built"] = "1990"
    facts["property_locations"][1]["year_built"] = "1991"
    assert derive_package_cope(facts) == []
    assert facts["year_built"]["value"] == "1975"                   # typed: untouched
    assert facts["roof_year"]["value"] == "2011"
    facts["property_locations"][0]["roof_year"] = "2015"
    derive_package_cope(facts)
    assert facts["roof_year"]["value"] == "2015"
    facts["property_locations"][1]["roof_year"] = ""
    assert derive_package_cope(facts) == ["roof_year"]
    assert facts["roof_year"]["value"] is None and facts["roof_year"]["value_state"] == "not_stated"
    # The retraction is an envelope the additive session write stores.
    from repositories.session_repository import resolve_facts_write
    stored = resolve_facts_write({"facts": {"roof_year": {"value": "2015"}}},
                                 {"roof_year": facts["roof_year"]})
    assert stored["roof_year"]["value"] is None
    assert derive_package_cope({}) == [] and derive_package_cope(None) == []


def test_one_building_140_owns_its_second_building_fire_boxes_and_keeps_row_a():
    facts = {"property_locations": [{"location_number": "1", "address_line1": "1 Main St",
                                     "address": "1 Main St, Austin, TX 78701"}],
             "fire_protection_class": "4", "sprinkler_system": "Yes", "roof_year": "2011",
             "has_property_coverage": True}
    schema = _schema("ACORD_140")
    mapped, unmatched, _det = ps.compute_form_gaps("ACORD_140", schema, facts)
    assert mapped["BuildingFireProtection_ProtectionClassCode_A"] == "4"     # the scalar, row A
    assert mapped["BuildingImprovement_RoofingYear_A"] == "2011"
    assert not any(f.startswith(("BuildingFireProtection_", "BuildingImprovement_"))
                   and f.endswith("_B") for f in unmatched)                 # no 2nd building asked
    two = copy.deepcopy(facts)
    two["property_locations"].append({"location_number": "2", "address_line1": "9 Elm St",
                                      "protection_class": "6"})
    mapped2, unmatched2, _ = ps.compute_form_gaps("ACORD_140", schema, two)
    assert mapped2["BuildingFireProtection_ProtectionClassCode_B"] == "6"    # its own row
    assert "BuildingFireProtection_HydrantDistanceFeetCount_B" in unmatched2


# ── 8. The on-demand route (poll / re-check against ticked forms) ────────────

def test_the_dry_run_route_is_owner_checked_and_withheld_like_the_rest(monkeypatch):
    from fastapi import HTTPException
    from routes import dry_run_routes as dr

    rows = {"mine": {"user_id": "u1", "facts": {"a": 1}, "flags": {}},
            "other": {"user_id": "u2"},
            "held": {"user_id": "u1", "integrity": {"review_required": True}},
            "done": {"user_id": "u1", "generated_forms": {"ACORD_125": {}}}}

    async def fake_get(sid):
        return rows[sid]

    seen = {}

    async def fake_payload(session, facts, flags, form_ids=None, **kw):
        seen.update(form_ids=form_ids, wait=kw.get("wait"), sid=kw.get("session_id"))
        return {"status": "ready", "count": 0}

    monkeypatch.setattr(dr, "get_processing_session", fake_get)
    monkeypatch.setattr(fdr, "dry_run_payload", fake_payload)

    def body(resp):
        return json.loads(resp.body)

    with pytest.raises(HTTPException) as exc:
        asyncio.run(dr.get_dry_run("other", form_ids="", wait=1.0, current_user={"id": "u1"}))
    assert exc.value.status_code == 403
    assert body(asyncio.run(dr.get_dry_run("held", form_ids="", wait=1.0,
                                           current_user={"id": "u1"})))["dry_run"] is None
    assert body(asyncio.run(dr.get_dry_run("done", form_ids="", wait=1.0,
                                           current_user={"id": "u1"})))["dry_run"] is None
    out = body(asyncio.run(dr.get_dry_run("mine", form_ids="ACORD_140, ACORD_125,", wait=99.0,
                                          current_user={"id": "u1"})))
    assert out["dry_run"] == {"status": "ready", "count": 0}
    assert seen == {"form_ids": ["ACORD_140", "ACORD_125"], "wait": 20.0, "sid": "mine"}


def test_the_dry_run_route_is_registered():
    from main import app
    assert "/api/session/{session_id}/dry-run" in {getattr(r, "path", None) for r in app.routes}
