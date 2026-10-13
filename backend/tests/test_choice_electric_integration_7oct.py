"""Choice Electric round 3 - the integrator's own changes (7 Oct 2026).

1. A NUMBER is "in the documents" only as the same number (`pdf_service._value_in_raw_text`).
2. The client's copy of a table carries no producer-only VALUES (`schedule_capture.client_rows`).
3. Premium boxes are re-stamped after a document change (the documents door) and a post-generation
   Data Consistency confirmation, each side judged against its own documents' text.
4. The editor confirmation asks the engine with generation's own input (facts + flags + forms).
"""
import inspect
from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parents[1]


# ── 1. numbers ───────────────────────────────────────────────────────────────

@pytest.mark.parametrize("value,text,expected", [
    ("$3,100", "TOTAL $23,100.00 due", False),             # the reported shape
    ("$3,100", "premium $3,100 per year", True),
    ("$3,100.00", "premium $3,100 per year", True),        # cents, either way round
    ("$3,100", "premium $3,100.00 per year", True),
    ("$3,100", "limit $3,100,000 aggregate", False),       # the number goes on
    ("$100,000", "limit $2,100,000 aggregate", False),     # the tail of a longer number
    ("$100,000", "limit $100,000 each", True),
    ("$1,000,000", "$1,000,000/$2,000,000", True),
    ("$2,000,000", "$1,000,000/$2,000,000", True),
    ("$3,100", "page 100 of 3", False),                    # no word-subset fallback for numbers
    ("12.50", "rate 12.5000 per 100", True),              # a decimal printed with trailing zeros
    ("12.50", "rate 112.50 per 100", False),
    ("303-521-0561", "call 303-521-0561 123 Main St", True),   # a phone is not a grouped amount
    ("303-521-0561", "call 1 303 521 0561", True),
    ("2001", "001 2001CHEVROLET EXPRESS", False),
    ("2001", "Year built 2001 frame", True),
    ("01/01/2025", "From 01/01/2025 to 01/01/2026", True),
    ("16,818", "COVERAGE PART $ 16,818.00", True),
    ("ACE American Insurance Co", "ACE American Insurance Company", True),   # text keeps its fallback
])
def test_a_number_is_present_only_as_the_same_number(value, text, expected):
    from services.pdf_service import _normalize_for_search, _value_in_raw_text
    assert _value_in_raw_text(value, _normalize_for_search(text)) is expected


def test_short_values_stay_unverifiable():
    from services.pdf_service import _normalize_for_search, _value_in_raw_text
    assert _value_in_raw_text("1.08", _normalize_for_search("Mod 1.0800")) is False   # 3 characters


# ── 2. the client's copy of a table ──────────────────────────────────────────

def test_the_client_copy_drops_producer_only_values_and_keeps_the_row_id():
    from services import schedule_capture as sc
    cols = sc.SCHEDULE_DEFS["property_locations"]["columns"]
    hidden = {c["key"] for c in cols if c.get("producer_only")}
    assert {"location_number", "building_number"} <= hidden
    rows = [{"address_line1": "107 Main St", "location_number": "1", "building_number": "002",
             sc.ROW_ID_KEY: "r1"}]
    out = sc.client_rows("property_locations", rows)
    assert out == [{"address_line1": "107 Main St", sc.ROW_ID_KEY: "r1"}]
    assert rows[0]["location_number"] == "1"            # never mutates the stored rows
    assert sc.client_rows("property_locations", None) == []
    assert sc.client_rows("no_such_table", rows) == rows


def test_the_client_view_route_uses_it():
    src = (BACKEND / "routes" / "arq_routes.py").read_text(encoding="utf-8")
    view = src[src.index("async def client_view"):]
    view = view[:view.index("@router.")]
    assert "schedule_capture.client_rows(_lk, _rows)" in view


# ── 3. premium boxes after a document change / a confirmation ───────────────

def test_the_documents_door_restamps_premiums_with_each_sides_own_text(monkeypatch):
    from services import session_documents as sd
    import services.arq_service as arq
    import services.policy_lines as pl
    calls = {}
    monkeypatch.setattr(arq, "_restamp_changed_boxes", lambda *a, **k: [])

    def _np(generated, before, after, raw_text=None, *, raw_text_before=None):
        calls.update(after_text=raw_text, before_text=raw_text_before)
        return ["ACORD_125"]
    monkeypatch.setattr(pl, "restamp_nonfillable_boxes", _np)
    gen = {"ACORD_125": {"field_state": {}, "confidence": {}}}
    touched, _moved = sd.restamp_forms(gen, {}, {}, raw_text_before="OLD", raw_text_after="OLD NEW")
    assert touched == ["ACORD_125"]
    assert calls == {"after_text": "OLD NEW", "before_text": "OLD"}


def test_the_door_passes_both_texts_from_its_call_site():
    src = inspect.getsource(__import__("services.session_documents", fromlist=["x"]))
    assert "raw_text_before=_text_before, raw_text_after=_text_after" in src


def test_without_a_text_the_door_stays_as_it_was(monkeypatch):
    from services import session_documents as sd
    import services.arq_service as arq
    import services.policy_lines as pl
    monkeypatch.setattr(arq, "_restamp_changed_boxes", lambda *a, **k: ["ACORD_126"])
    monkeypatch.setattr(pl, "restamp_nonfillable_boxes",
                        lambda *a, **k: (_ for _ in ()).throw(AssertionError("must not run")))
    touched, _ = sd.restamp_forms({"ACORD_126": {"field_state": {}}}, {}, {})
    assert touched == ["ACORD_126"]


# ── 5. the prior-coverage grid is built once per stamp, with the same output ─

def test_the_grid_is_built_once_per_stamp_and_the_output_is_identical(monkeypatch):
    import copy
    import json
    import services.pdf_service as ps
    from services.extraction_service import merge_facts, select_primary_truth
    fx = json.loads((BACKEND / "tests" / "fixtures" / "choice_electric_pol_6oct.json").read_text())
    docs = fx["docs"]
    mf, fl = merge_facts(copy.deepcopy(docs), select_primary_truth(docs))
    facts = {**mf, **(fl or {})}
    text = "\n".join(str(d.get("text") or "") for d in docs)
    schema = json.loads((BACKEND / "forms_schemas" / "ACORD_125_schema.json").read_text())
    builds = {"n": 0}
    real = ps._prior_coverage_grid_build

    def _count(f):
        builds["n"] += 1
        return real(f)
    monkeypatch.setattr(ps, "_prior_coverage_grid_build", _count)

    def _stamp(fn):
        return fn(copy.deepcopy(facts), schema, form_id="ACORD_125", raw_text=text,
                  pre_filled_gpt={}, allow_llm=False)
    with_memo = _stamp(ps.map_facts_to_form)
    assert builds["n"] == 1
    builds["n"] = 0
    without = _stamp(ps.map_facts_to_form.__wrapped__)
    assert builds["n"] > 1
    assert with_memo == without
    # outside a stamp call nothing is memoised (field QA, direct callers)
    builds["n"] = 0
    ps._prior_coverage_grid(facts)
    ps._prior_coverage_grid(facts)
    assert builds["n"] == 2


# ── 4. the editor confirmation asks the engine like generation does ─────────

def test_the_editor_confirm_uses_generation_input_and_restamps_premiums():
    from services import extraction_pipeline as ep
    src = inspect.getsource(ep.confirm_underwriting_value_in_editor)
    assert '_view_before = {**facts_before, **flags, "_package_form_ids": _pkg}' in src
    assert '_view_after = {**facts, **flags, "_package_form_ids": _pkg}' in src
    assert "_restamp_changed_boxes(generated, _view_before, _view_after," in src
    assert "restamp_nonfillable_boxes(generated, _view_before, _view_after, _raw)" in src


# ── 6. a client table is compared as the client saw it (round 4 integration) ─

def test_an_untouched_client_table_with_producer_only_values_is_not_a_change():
    from services import schedule_capture as sc
    from services.arq_service import client_supplied_schedule
    seed = [{"address_line1": "107 Main St", "location_number": "1", "building_number": "001",
             sc.ROW_ID_KEY: "r1"}]
    q = {"schedule_key": "property_locations", "field_name": sc.answer_key("property_locations"),
         "current_rows": seed}
    came_home = sc.client_rows("property_locations", sc.seed_rows(q))   # what the client's page sent back
    assert client_supplied_schedule(q, came_home, touched=False) is False
    edited = [dict(came_home[0], address_line1="109 Main St")]
    assert client_supplied_schedule(q, edited, touched=False) is True


def test_the_row_change_review_ignores_producer_only_values():
    from services import confirm_known as ck
    from services import schedule_capture as sc
    seed = [{"address_line1": "107 Main St", "location_number": "1", sc.ROW_ID_KEY: "r1"}]
    shown = sc.client_rows("property_locations", seed)
    assert ck.schedule_row_changes("property_locations", sc.client_rows("property_locations", seed),
                                   sc.client_rows("property_locations", shown)) == 0
    src = (BACKEND / "services" / "arq_service.py").read_text(encoding="utf-8")
    assert "schedule_capture.client_rows(_list_key, schedule_capture.seed_rows(q))" in src


def test_a_premises_row_without_an_address_still_counts_as_a_location():
    from services.extraction_service import location_list_from_rows
    from services.schedule_capture import ROW_ID_KEY
    out = location_list_from_rows([
        {"address": "1 A St"},
        {"address_line1": "9 B St", "address_city": "Denver"},
        {"location_number": "1", "building_number": "002", "construction_type": "FRAME"},
        {"building_value": "$5"},
        {ROW_ID_KEY: "r9"}, {},
    ])
    assert out == ["1 A St", "9 B St, Denver", "Location 1 / Building 002", "Location 4"]


# ── 7. the AI reading of an added document (C103) - the integrator's wiring ──

def test_policy_edits_and_editor_confirms_wait_for_the_document_fill():
    pl_src = (BACKEND / "routes" / "policy_line_routes.py").read_text(encoding="utf-8")
    body = pl_src[pl_src.index("async def _refuse_while_running"):]
    body = body[:body.index("\nasync def ")]
    assert "document_fill_running(session)" in body and "DOCUMENT_FILL_LOCKED" in body
    fr_src = (BACKEND / "routes" / "form_routes.py").read_text(encoding="utf-8")
    body = fr_src[fr_src.index("async def underwriting_confirm_value_in_editor"):]
    body = body[:body.index("confirm_underwriting_value_in_editor(")]
    assert "document_fill_running(session)" in body


def test_the_download_review_lists_open_document_suggestions():
    src = (BACKEND / "routes" / "audit_routes.py").read_text(encoding="utf-8")
    body = src[src.index("async def get_needs_attention"):]
    body = body[:body.index("@router.")]
    assert 'result["document_suggestions"] = document_suggestion_rows(' in body
    fe = (BACKEND.parent / "frontend" / "src" / "components" / "form" / "NeedsAttentionPanel.jsx").read_text(encoding="utf-8")
    assert "document-suggestions-summary" in fe
