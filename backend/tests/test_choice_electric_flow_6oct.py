"""Choice Electric (session ca93ed8f, 5 Oct 2026) - FLOW fixes, 6 Oct 2026.

1. ONE stops door (`services/stops_now.py`). Every scorer rebuilds its stop
   lists from the STORED facts; the stored `hard_stops` / `soft_stops` are a
   display cache. Live: a Data Consistency confirm re-ran the pipeline, the
   re-run stored "Property Minimum Viable COPE incomplete - missing: occupancy
   type" beside facts that held the producer's occupancy answer, and
   generation capped the package at 60 for it. The pipeline now scores the
   facts it will STORE (`facts_as_stored`).
2. A HARD legacy stop is never hidden behind a coded twin that C75 demoted to
   a warning - the 60 cap it applies is shown, once.
3. A box edit on one form re-stamps its fact into every other generated form
   (`arq_service.propagate_fact_edits`); a person's box on another form stays.
4. A stated radius CLASS ("LOCAL") or a distance with its unit is a stated
   radius of operation (Auto Completeness -5 no longer charged).
5. ONE GL-class-code reader (both homes, minus another line's codes) for the
   legacy stop and the Exposure "Operations" -20.
6. Owner's live bug (session ac300073): a 127-only package capped at 60 by
   "Business Income limit is specified but Period of Restoration is missing".
"""
from __future__ import annotations

import ast
import asyncio
import sys
from contextlib import nullcontext
from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))

from services import stops_now as sn  # noqa: E402

MV_COPE_LEGACY = "Property Minimum Viable COPE incomplete - missing: occupancy type"
MV_COPE_CODED = ("Property submission missing Minimum Viable COPE: occupancy type. "
                 "These fields are required to submit property to underwriting.")


def _property_facts(**extra):
    facts = {
        "applicant_name": "Choice Electric LLC",
        "locations": ["5405 S Lowell Blvd, Littleton, CO 80123"],
        "property_locations": [{"address": "5405 S Lowell Blvd, Littleton, CO 80123",
                                "construction_type": "Frame", "building_value": "$798,556"}],
        "construction_type": "Frame",
        "property_building_value": "$798,556",
        "occupancy_type": {"value": "Contractor shop or yard", "source": "producer",
                           "confidence": "filled"},
    }
    facts.update(extra)
    return facts


_PROPERTY_FLAGS = {"has_property_coverage": True}


# ── 1. The stops door ────────────────────────────────────────────────────────

_SCORERS = {"calculate_package_sqs", "calculate_sqs", "calculate_sqs_from_facts", "_PACKAGE_SCORER"}
_STORED = {"hard_stops", "soft_stops"}


def _reads_stored_list(node: ast.AST, tainted: set) -> bool:
    for sub in ast.walk(node):
        if (isinstance(sub, ast.Call) and isinstance(sub.func, ast.Attribute)
                and sub.func.attr == "get" and sub.args
                and isinstance(sub.args[0], ast.Constant) and sub.args[0].value in _STORED):
            return True
        if (isinstance(sub, ast.Subscript) and isinstance(sub.slice, ast.Constant)
                and sub.slice.value in _STORED):
            return True
        if isinstance(sub, ast.Name) and sub.id in tainted:
            return True
    return False


def _product_files():
    for folder in ("routes", "services"):
        yield from sorted((BACKEND / folder).glob("*.py"))
    yield BACKEND / "worker.py"


def test_no_scorer_is_fed_the_stored_stop_lists():
    """THE CLASS: a scorer handed `session["hard_stops"]` scores whatever facts
    the last pipeline run saw. Every scorer call must take its lists from the
    door (or from lists it rebuilt itself) - never from the stored cache."""
    offenders = []
    for path in _product_files():
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for fn in ast.walk(tree):
            if not isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            tainted: set = set()
            for node in ast.walk(fn):
                if isinstance(node, ast.Assign) and _reads_stored_list(node.value, set()):
                    for tgt in node.targets:
                        for name in ast.walk(tgt):
                            if isinstance(name, ast.Name):
                                tainted.add(name.id)
            for node in ast.walk(fn):
                if not isinstance(node, ast.Call):
                    continue
                fname = (node.func.id if isinstance(node.func, ast.Name)
                         else node.func.attr if isinstance(node.func, ast.Attribute) else "")
                if fname not in _SCORERS:
                    continue
                for kw in node.keywords:
                    if kw.arg in _STORED and _reads_stored_list(kw.value, tainted):
                        offenders.append(f"{path.name}:{node.lineno} {fn.name} -> {fname}({kw.arg}=...)")
    assert not offenders, "scorer fed the stored stop lists:\n" + "\n".join(offenders)


def test_the_door_reads_the_stored_facts_not_the_stored_lists():
    session = {
        "facts": _property_facts(),
        "flags": dict(_PROPERTY_FLAGS),
        # the stale cache a pipeline re-run left behind (live ca93ed8f)
        "hard_stops": [MV_COPE_LEGACY + " Fix: Review and correct this before proceeding."],
        "soft_stops": [],
    }
    out = sn.stops_now(session, ["ACORD_140"], pre_form=False)
    assert not any("Minimum Viable COPE" in m for m in out["hard"])
    assert not any("Minimum Viable COPE" in m for m in out["soft"])
    # ...and the same session WITHOUT the answer does raise it, through the door
    facts = _property_facts()
    facts.pop("occupancy_type")
    out = sn.stops_now({"facts": facts, "flags": dict(_PROPERTY_FLAGS)}, ["ACORD_140"],
                       pre_form=False)
    assert any("Minimum Viable COPE incomplete" in m for m in out["hard"])


def test_cross_form_hard_stops_are_warnings_before_and_after_generation():
    """REVERSED 14 Oct 2026 (owner, one status from start to finish): this test
    pinned generation re-promoting the C75-demoted cross-form hard stops. The
    TEST was wrong for the new rule, not the code: a check keeps its status
    before and after forms (tests/test_one_status_14oct.py)."""
    facts = _property_facts()
    facts.pop("occupancy_type")
    session = {"facts": facts, "flags": dict(_PROPERTY_FLAGS)}
    pre = sn.stops_now(session, ["ACORD_140"], pre_form=True)
    gen = sn.stops_now(session, ["ACORD_140"], pre_form=False)
    assert all(i.get("type") != "hard_stop" for i in pre["cross_issues"])
    assert all(i.get("type") != "hard_stop" for i in gen["cross_issues"])
    # same status per rule (a form choice is deferred before forms - 13 Oct)
    pre_types = {i.get("code"): i.get("type") for i in pre["cross_issues"] if not i.get("form_choice")}
    gen_types = {i.get("code"): i.get("type") for i in gen["cross_issues"] if i.get("code") in pre_types}
    assert pre_types and gen_types == pre_types
    # the field-level legacy copy is hard both times
    assert any("Minimum Viable COPE incomplete" in m for m in pre["hard"])
    assert any("Minimum Viable COPE incomplete" in m for m in gen["hard"])
    # one form is scored with field-level stops only (spec 10)
    assert set(gen["form_hard"]) <= set(gen["hard"])
    assert not any("(Affects:" in m for m in gen["form_hard"] + gen["form_soft"])


def test_generation_scores_without_the_stale_stop():
    from services.sqs_service import calculate_package_sqs
    session = {"facts": _property_facts(), "flags": dict(_PROPERTY_FLAGS),
               "hard_stops": [MV_COPE_LEGACY], "soft_stops": []}
    stops = sn.stops_now(session, ["ACORD_140"], pre_form=False)
    pkg = calculate_package_sqs(
        facts=session["facts"], flags=session["flags"], form_results=[],
        cross_issues=stops["cross_issues"], hard_stops=stops["hard"],
        soft_stops=stops["soft"], session_data=session, _probe=True)
    assert "Minimum Viable COPE" not in str(pkg.get("cap_reason") or "")


def test_the_pre_form_door_ignores_the_stored_lists():
    from services.sqs_service import score_package_pre_generation
    session = {"facts": _property_facts(), "flags": dict(_PROPERTY_FLAGS),
               "hard_stops": [MV_COPE_LEGACY], "soft_stops": [],
               "recommendations": [{"form_id": "ACORD_140"}]}
    pkg = score_package_pre_generation(session)
    assert "Minimum Viable COPE" not in str(pkg.get("cap_reason") or "")


def test_facts_as_stored_is_the_additive_write():
    prior = {"occupancy_type": "Office", "fein": {"value": "1", "source": "ai"},
             "auto_drivers": [{"name": "Erin Royal"}]}
    merged = {"fein": {"value": "2", "source": "ai"}, "occupancy_type": None,
              "construction_type": "Frame", "auto_drivers": []}
    stored = sn.facts_as_stored(prior, merged, ["auto_drivers"])
    assert stored["occupancy_type"] == "Office"          # an empty write never erases
    assert stored["fein"]["value"] == "2"                # a value overwrites
    assert stored["construction_type"] == "Frame"
    assert "auto_drivers" not in stored                  # the planned retraction
    assert sn.facts_as_stored(None, merged) is merged     # first upload: unchanged
    assert sn.facts_as_stored({}, merged) is merged


def test_ocr_warning_is_satisfied_by_a_person():
    docs = [{"manual_confirmation_required": ["fein"]}]
    assert sn.ocr_review_stops(docs, {"fein": {"value": "1", "source": "ai"}})
    assert not sn.ocr_review_stops(docs, {"fein": {"value": "1", "source": "producer"}})
    assert not sn.ocr_review_stops(docs, {}, {"fein": "12-3456789"})
    assert sn.ocr_review_stops(docs, {})[0][1] == \
        "Low OCR confidence on critical field — confirm: fein"


def test_underwriting_conflicts_keep_the_pipeline_rule():
    uw = {"review_required": True, "fields": [
        {"fact_key": "property_building_value", "label": "Building Value", "review_required": True,
         "values": [{"display": "$1"}, {"display": "$2"}]},
        {"fact_key": "umbrella_limit", "label": "Umbrella / Excess Limit", "review_required": True,
         "values": [{"display": "$4,000,000"}, {"display": "$5,000,000"}]},
    ]}
    with_prop = {k: b for k, _m, b in sn.underwriting_conflict_stops(
        uw, {"has_property_coverage": True})}
    without = {k: b for k, _m, b in sn.underwriting_conflict_stops(uw, {})}
    assert without["property_building_value"] is False      # irrelevant -> a warning
    assert with_prop["property_building_value"] is True     # relevant -> blocks (C75)
    assert with_prop["umbrella_limit"] is False
    msgs = [m for _k, m, _b in sn.underwriting_conflict_stops(uw, {})]
    assert msgs[1] == ("Umbrella / Excess Limit: documents disagree ($4,000,000, $5,000,000). "
                       "Fix: Confirm the correct value to apply it across forms.")
    assert sn.underwriting_conflict_stops({"review_required": False, "fields": uw["fields"]}, {}) == []


# ── the pipeline scores what it stores, and agrees with the door ─────────────

_PROP_DOC_TEXT = """COMMERCIAL PROPERTY COVERAGE SCHEDULE
Prem #: 001 Bldg #: 001
Construction Type: FRAME
COVERAGE: BUILDING LIMIT $798,556
"""


def _prop_doc():
    return {"filename": "package.pdf", "doc_type": "dec_page", "text": _PROP_DOC_TEXT,
            "facts": {"applicant_name": "CHOICE ELECTRIC LLC",
                      "construction_type": "FRAME",
                      "property_building_value": "$798,556",
                      "locations": ["5405 S Lowell Blvd, Littleton, CO 80123"]},
            "flags": {"has_property_coverage": True}}


def _run_pipeline(monkeypatch, docs, prior_facts):
    import services.extraction_pipeline as ep
    calls = {}

    async def _upd(session_id, payload, delete_facts=None, **_kw):
        calls["payload"] = payload
        calls["delete_facts"] = delete_facts

    async def _no_account(_user_id):
        return None

    async def _no_learn(_values):
        return 0

    monkeypatch.setattr(ep, "upd_processing_session", _upd)
    monkeypatch.setattr(ep, "_submitting_account_for", _no_account)
    import services.yes_no_lexicon as ynl
    monkeypatch.setattr(ynl, "learn", _no_learn)
    asyncio.run(ep._finalize_pipeline(docs, "user-ce", session_id="sess-ce",
                                      prior_facts=prior_facts, prior_flags={}))
    return calls


def test_a_rerun_scores_the_facts_it_will_store(monkeypatch):
    """A stored value the re-merge leaves empty (here a bare answer the human
    carry-over cannot see) stays in the STORE - so the stops must see it too."""
    calls = _run_pipeline(monkeypatch, [_prop_doc()], {"occupancy_type": "Contractor shop or yard"})
    hard = calls["payload"]["hard_stops"]
    assert not any("Minimum Viable COPE" in m and "occupancy" in m for m in hard)


def test_the_pipeline_and_the_door_agree(monkeypatch):
    prior = {"occupancy_type": {"value": "Office", "source": "producer", "confidence": "filled"}}
    calls = _run_pipeline(monkeypatch, [_prop_doc()], prior)
    payload = dict(calls["payload"])
    payload["facts"] = sn.facts_as_stored(prior, payload["facts"], calls["delete_facts"] or ())
    door = sn.stops_now(payload, None, pre_form=True)
    assert door["hard"] == payload["hard_stops"]
    assert door["soft"] == payload["soft_stops"]


# ── 2. Never hide a blocker behind a demoted warning ────────────────────────

def _messages(obj):
    out = []
    if isinstance(obj, dict):
        for k, v in obj.items():
            if k == "message" and isinstance(v, str):
                out.append(v)
            else:
                out += _messages(v)
    elif isinstance(obj, list):
        for v in obj:
            out += _messages(v)
    return out


def _view(legacy_sev, coded_sev):
    from services.issue_registry import build_grouped_view, make_issue
    legacy = make_issue("legacy_minimum_viable_cope", legacy_sev, MV_COPE_LEGACY)
    coded = make_issue("minimum_viable_cope_missing", coded_sev, MV_COPE_CODED, ["ACORD_140"])
    coded_final = MV_COPE_CODED + " (Affects: ACORD 140. Fix: Review the coverage/limit details.)"
    hard = [m for m, s in ((MV_COPE_LEGACY, legacy_sev), (coded_final, coded_sev)) if s == "hard_stop"]
    soft = [m for m, s in ((MV_COPE_LEGACY, legacy_sev), (coded_final, coded_sev)) if s != "hard_stop"]
    return build_grouped_view([legacy, coded], hard, soft)


def test_a_hard_legacy_stop_is_not_hidden_behind_a_demoted_twin():
    view = _view("hard_stop", "soft_warning")
    hard_msgs = _messages(view.get("hard_stops"))
    warn_msgs = _messages(view.get("warnings"))
    assert any(MV_COPE_LEGACY in m for m in hard_msgs)
    # shown ONCE: the demoted twin is the row hidden
    assert not any(MV_COPE_CODED[:40] in m for m in warn_msgs + hard_msgs)


def test_a_hard_twin_still_supersedes_its_legacy_copy():
    view = _view("hard_stop", "hard_stop")
    msgs = _messages(view)
    assert any(MV_COPE_CODED[:40] in m for m in msgs)
    assert not any(m.startswith(MV_COPE_LEGACY) for m in msgs)


def test_warning_twins_are_unchanged():
    view = _view("soft_warning", "soft_warning")
    msgs = _messages(view)
    assert any(MV_COPE_CODED[:40] in m for m in msgs)
    assert not any(m.startswith(MV_COPE_LEGACY) for m in msgs)


# ── 3. One edit, every form ──────────────────────────────────────────────────

@pytest.fixture
def fake_engine(monkeypatch):
    """The generation engine reduced to "this box prints that fact"."""
    import services.arq_service as arq
    import services.pdf_service as pdf
    boxes = {"Policy_EffectiveDate_A": "effective_date",
             "Policy_ExpirationDate_A": "expiration_date"}

    def _val(facts, key):
        raw = (facts or {}).get(key)
        return raw.get("value") if isinstance(raw, dict) else raw

    monkeypatch.setattr(pdf, "_deterministic_map",
                        lambda box, facts: _val(facts, boxes[box]) if box in boxes else None)
    monkeypatch.setattr(pdf, "display_value_for_box",
                        lambda fid, box, raw, facts=None, **_k: raw)
    monkeypatch.setattr(pdf, "_is_nonfillable_field", lambda box: False)
    monkeypatch.setattr(pdf, "_schema_context", lambda schema: nullcontext())
    monkeypatch.setattr(pdf, "premises_twin_fact", lambda *a, **k: None, raising=False)
    monkeypatch.setattr(arq, "_canonical_keys_for", lambda box: {boxes[box]} if box in boxes else set())
    return arq


def _form(eff, label="low_confidence", exp=None):
    state = {"Policy_EffectiveDate_A": eff}
    conf = {"Policy_EffectiveDate_A": label}
    if exp is not None:
        state["Policy_ExpirationDate_A"] = exp
        conf["Policy_ExpirationDate_A"] = "filled"
    return {"schema": {"Policy_EffectiveDate_A": {}, "Policy_ExpirationDate_A": {}},
            "mapped": dict(state), "field_state": dict(state), "confidence": conf,
            "client_filled_fields": [], "_pdf_cache_hash": "abc", "pdf_bytes": b"x"}


BEFORE = {"effective_date": "01/01/2026", "expiration_date": "01/01/2027"}
AFTER = {"effective_date": {"value": "01/01/2027", "source": "producer"},
         "expiration_date": {"value": "01/01/2028", "source": "producer"}}


def test_an_edit_reaches_every_other_form(fake_engine):
    generated = {"ACORD_125": _form("01/01/2027", "producer"),
                 "ACORD_126": _form("01/01/2026", exp="01/01/2027"),
                 "ACORD_130": _form("01/01/2026")}
    touched = fake_engine.propagate_fact_edits(
        generated, "ACORD_125", BEFORE, AFTER, ["effective_date", "expiration_date"])
    assert sorted(touched) == ["ACORD_126", "ACORD_130"]
    for fid in touched:
        fd = generated[fid]
        assert fd["field_state"]["Policy_EffectiveDate_A"] == "01/01/2027"
        assert fd["confidence"]["Policy_EffectiveDate_A"] == "producer"
        assert fd["pdf_bytes"] is None and fd["_pdf_cache_hash"] == ""
    assert generated["ACORD_126"]["field_state"]["Policy_ExpirationDate_A"] == "01/01/2028"


def test_a_person_box_and_an_edited_box_on_another_form_stay(fake_engine):
    generated = {"ACORD_125": _form("01/01/2027", "producer"),
                 "ACORD_126": _form("02/02/2026", "client_arq"),      # the client's
                 "ACORD_131": _form("03/03/2026")}                    # edited since generation
    touched = fake_engine.propagate_fact_edits(generated, "ACORD_125", BEFORE, AFTER,
                                               ["effective_date"])
    assert touched == []
    assert generated["ACORD_126"]["field_state"]["Policy_EffectiveDate_A"] == "02/02/2026"
    assert generated["ACORD_131"]["field_state"]["Policy_EffectiveDate_A"] == "03/03/2026"


def test_a_cleared_fact_clears_its_engine_copies(fake_engine):
    generated = {"ACORD_125": _form("", "low_confidence"), "ACORD_126": _form("01/01/2026")}
    touched = fake_engine.propagate_fact_edits(
        generated, "ACORD_125", BEFORE, {"expiration_date": "01/01/2027"}, ["effective_date"])
    assert touched == ["ACORD_126"]
    assert generated["ACORD_126"]["field_state"]["Policy_EffectiveDate_A"] == ""
    assert "Policy_EffectiveDate_A" not in generated["ACORD_126"]["confidence"]


def test_update_pdf_propagates_and_rederives():
    src = (BACKEND / "routes" / "form_routes.py").read_text(encoding="utf-8")
    tree = ast.parse(src)
    fn = next(n for n in ast.walk(tree)
              if isinstance(n, ast.AsyncFunctionDef) and n.name == "update_pdf")
    body = ast.get_source_segment(src, fn) or ""
    assert "propagate_fact_edits(" in body
    assert "_rederive_answer_dependent_facts(" in body
    # the dependent facts are re-derived BEFORE the stops are rebuilt
    assert body.index("_rederive_answer_dependent_facts(") < body.index("evaluate_stops(updated_facts")


# ── 4. A stated radius ───────────────────────────────────────────────────────

@pytest.mark.parametrize("value", [
    "LOCAL", "local", "Intermediate", "LONG DISTANCE", "long-distance", "Local radius",
    "LOCAL (0-50 MILES)", "50", "50 miles", "50 mi", "up to 50 miles", "within 200 miles", "75.5",
])
def test_a_stated_radius(value):
    from services.coverage_evidence import radius_stated
    assert radius_stated(value)


@pytest.mark.parametrize("value", [None, "", "NA", "N/A", "None", "SEE SCHEDULE",
                                   "10 vehicles", "local delivery van", [], {}])
def test_not_a_stated_radius(value):
    from services.coverage_evidence import radius_stated
    assert not radius_stated(value)


def test_the_auto_schedule_radius_class_counts():
    from services.coverage_evidence import AUTO_RADIUS_READING_KEY, auto_radius_known
    rows = [{"year": "2001", "make": "CHEVROLET", "radius": "LOCAL"}]
    assert auto_radius_known({"auto_vin_schedule": rows})
    assert not auto_radius_known({"auto_vin_schedule": [{"year": "2001", "radius": "NA"}]})
    # the stored declarations reading survives the index purge
    assert auto_radius_known({AUTO_RADIUS_READING_KEY: "LOCAL"})
    assert not auto_radius_known({})


# ── 5. One GL-class-code reader ──────────────────────────────────────────────

_WC_ROWS = [{"code": "5190", "state": "CO", "payroll": "2,000,000",
             "description": "Electrical Wiring-Within Buildings"},
            {"code": "8810", "state": "CO", "payroll": "200,000", "description": "Clerical"}]


def test_gl_codes_from_either_home_count():
    from services.sqs_service import gl_class_codes_present
    assert gl_class_codes_present({"gl_class_codes_by_location": [{"location": "1", "codes": ["91580"]}]})
    assert gl_class_codes_present({"gl_class_code_schedule": [{"class_code": "91580"}]})
    assert not gl_class_codes_present({})
    assert not gl_class_codes_present({"gl_class_code_schedule": []})
    # a shape the reader cannot parse keeps today's verdict: present
    assert gl_class_codes_present({"gl_class_codes_by_location": [{"location": "1"}]})


def test_another_lines_codes_are_not_gl_codes():
    from services.sqs_service import gl_class_codes, gl_class_codes_present
    facts = {"wc_class_codes": _WC_ROWS,
             "gl_class_code_schedule": [{"class_code": "5190"}, {"class_code": "8810"}]}
    assert gl_class_codes(facts) == []
    assert not gl_class_codes_present(facts)
    facts["gl_class_code_schedule"].append({"class_code": "91580"})
    assert gl_class_codes(facts) == ["91580"]


def test_the_stop_and_the_exposure_bucket_give_one_answer():
    from services.sqs_service import _calculate_exposure_consistency, evaluate_stops
    flags = {"has_general_liability": True}
    for facts, present in (
        ({"gl_class_code_schedule": [{"class_code": "91580"}]}, True),
        ({"wc_class_codes": _WC_ROWS, "gl_class_code_schedule": [{"class_code": "5190"}]}, False),
    ):
        _score, sub = _calculate_exposure_consistency(facts, flags, [], [])
        _hard, soft = evaluate_stops(facts, flags)
        warned = any("no class codes found" in m for m in soft)
        charged = sub["operations_description"] <= 80
        assert warned is (not present) and charged is (not present), facts


# ── 6. Business Income / Period of Restoration on a package without ACORD 140 ─

def _bi_facts():
    return _property_facts(business_income_limit="$1,000,000")


_BI_FLAGS = {"has_property_coverage": True, "property_has_bi_coverage": True}


def test_bi_without_restoration_does_not_block_a_127_only_package():
    from services.cross_form_validator import run_cross_form_validation
    from services.sqs_service import calculate_package_sqs
    codes = {i.get("code") for i in run_cross_form_validation(_bi_facts(), dict(_BI_FLAGS), {"ACORD_127"})}
    assert "bi_missing_period_of_restoration" not in codes
    session = {"facts": _bi_facts(), "flags": dict(_BI_FLAGS)}
    stops = sn.stops_now(session, ["ACORD_127"], pre_form=False)
    assert not any("Period of Restoration" in m for m in stops["hard"])
    pkg = calculate_package_sqs(
        facts=session["facts"], flags=session["flags"], form_results=[],
        cross_issues=stops["cross_issues"], hard_stops=stops["hard"],
        soft_stops=stops["soft"], session_data=session, _probe=True)
    assert "Period of Restoration" not in str(pkg.get("cap_reason") or "")


def test_bi_without_restoration_still_flags_the_140():
    from services.cross_form_validator import run_cross_form_validation
    issues = run_cross_form_validation(_bi_facts(), dict(_BI_FLAGS), {"ACORD_140"})
    assert any(i.get("code") == "bi_missing_period_of_restoration" for i in issues)
