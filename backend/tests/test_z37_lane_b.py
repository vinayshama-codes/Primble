"""Z37 lane B (24 Oct 2026, owner-approved): agreed value only when affirmed,
umbrella follow form from the umbrella's own documents, ACORD AL3 LOB codes,
and two Z33-PERCENT leftovers (the stale client half, the picker's "$2")."""

import sys
from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))

from services import cross_form_validator as cf                  # noqa: E402
from services import sqs_service as sq                           # noqa: E402
from services import umbrella_layers as ul                       # noqa: E402
from services import lob_canon as lc                             # noqa: E402
from services.coverage_evidence import agreed_value_affirmed     # noqa: E402

PROP = {"has_property_coverage": True}
_BASE = {"locations": ["1450 Lantern Court, Columbus OH 43215"],
         "occupancy_type": "Office", "construction_type": "Frame",
         "property_building_value": "$900,000"}


# ── 1. agreed value ───────────────────────────────────────────────────────────

@pytest.mark.parametrize("value", [False, "False", "false", "No", "N", "no",
                                   "No - coinsurance applies", "no agreed value",
                                   {"value": False, "source": "ai"}, None, ""])
def test_a_no_or_silent_agreed_value_is_not_agreed_value(value):
    facts = {"agreed_value_endorsement": value}
    assert agreed_value_affirmed(facts) is False
    codes = [i["code"] for i in cf._check_property_coinsurance_enforcement(
        dict(_BASE, **facts), PROP, {"ACORD_140"})]
    assert "property_coinsurance_missing" in codes


@pytest.mark.parametrize("value", [True, "True", "Yes", "Y", "yes",
                                   "Yes - agreed value endorsement applies",
                                   "Other: agreed value per schedule",
                                   {"value": "Yes", "source": "producer"}])
def test_an_affirmed_agreed_value_satisfies_the_rule(value):
    facts = dict(_BASE, agreed_value_endorsement=value)
    assert agreed_value_affirmed(facts) is True
    assert not cf._check_property_coinsurance_enforcement(facts, PROP, {"ACORD_140"})


def _sqs_issues(facts, form_id):
    out = sq.calculate_sqs(facts, dict(PROP), {}, {}, [form_id], [], [], 0, form_id=form_id)
    return " | ".join(str(x) for x in out.get("issues") or [])


@pytest.mark.parametrize("form_id", ["ACORD_140", "ACORD_125"])
def test_the_scorer_reads_the_same_reader(form_id):
    msg = "Coinsurance percentage not specified"
    assert msg in _sqs_issues(dict(_BASE, agreed_value_endorsement="False"), form_id)
    assert msg not in _sqs_issues(dict(_BASE, agreed_value_endorsement="Yes"), form_id)
    assert msg not in _sqs_issues(dict(_BASE, coinsurance_percentage="80%",
                                       agreed_value_endorsement="False"), form_id)


# ── 2. umbrella follow form ───────────────────────────────────────────────────

def _rec(rid, layer, sources):
    return {"id": rid, "line": "umbrella", "line_printed": f"{layer.title()} Liability",
            "layer": layer, "carrier_name": layer.title() + " Co", "policy_number": rid[-2:],
            "effective_date": "01/01/2026", "expiration_date": "01/01/2027",
            "granted": True, "sources": list(sources), "premium": 10.0,
            "printings": {"carrier_name": [layer.title() + " Co"]}}


_HEAD = "Follow Form Excess Liability Policy"


def _tower(merged, umb_doc=None):
    store = {"u.pdf": dict(umb_doc or {}), "x.pdf": {"umbrella_follow_form": _HEAD}}
    return {"_line_records": [_rec("umbrella#U1", "umbrella", ["u.pdf"]),
                              _rec("umbrella~excess#X1", "excess", ["x.pdf"])],
            ul.DOCS_KEY: store, **({"umbrella_follow_form": merged} if merged else {})}


def test_the_excess_heading_is_not_the_umbrellas_follow_form():
    facts = _tower({"value": _HEAD, "source": "ai"})
    assert ul.upper_layer_documents(facts) == {"x.pdf"}
    assert ul.settle_umbrella_follow_form(facts) is True
    assert "umbrella_follow_form" not in facts
    # the excess layer keeps its own statement for its own 131
    assert facts[ul.DOCS_KEY]["x.pdf"]["umbrella_follow_form"] == _HEAD
    assert sq._get_follow_form_status(facts)["status"] == "unable_to_determine"


def test_the_umbrellas_own_statement_wins():
    own = {"value": "Umbrella follows form", "source": "ai"}
    facts = _tower({"value": _HEAD, "source": "ai"}, umb_doc={"umbrella_follow_form": own})
    ul.settle_umbrella_follow_form(facts)
    assert facts["umbrella_follow_form"]["value"] == "Umbrella follows form"


def test_a_person_and_a_non_tower_are_untouched():
    person = {"value": "Follows form", "source": "producer"}
    facts = _tower(person)
    assert ul.settle_umbrella_follow_form(facts) is False and facts["umbrella_follow_form"] is person
    # excess only (no umbrella layer): its statement is the only layer's own
    one = {"_line_records": [_rec("umbrella~excess#X1", "excess", ["x.pdf"])],
           "umbrella_follow_form": {"value": _HEAD}}
    assert ul.upper_layer_documents(one) == set()
    assert ul.settle_umbrella_follow_form(one) is False and "umbrella_follow_form" in one
    assert ul.upper_layer_documents({}) == set()


def test_the_pipeline_text_scan_skips_the_upper_layers_documents():
    src = (BACKEND / "services" / "extraction_pipeline.py").read_text(encoding="utf-8")
    assert "settle_umbrella_follow_form(merged_facts)" in src
    assert "_udoc_name not in _upper_docs" in src


# ── 3. ACORD AL3 LOB codes ────────────────────────────────────────────────────

@pytest.mark.parametrize("text,family", [
    ("UMBRC", lc.UMBRELLA), ("EXLIA", lc.UMBRELLA), ("INMRC", lc.INLAND_MARINE),
    ("WORK", lc.WORKERS_COMP), ("WORK (Expiring)", lc.WORKERS_COMP),
    ("PROPC", lc.PROPERTY), ("GARAG", lc.AUTO), ("AUTOB", lc.AUTO),
    ("CGL", lc.GENERAL_LIAB), ("umbrc", lc.UMBRELLA), ("UMBRC - Magnolia", lc.UMBRELLA),
])
def test_the_codes_map(text, family):
    assert lc.canon_line(text) == family


@pytest.mark.parametrize("text", ["Completed Work", "Work performed", "WORKSHOP", "network",
                                  "BOPS", "umbrcx", "CPKGE", "BOP", "Burglary and theft"])
def test_codes_never_match_as_substrings_or_words(text):
    assert lc.canon_line(text) is None


def test_layers_and_containers():
    assert lc.umbrella_layer("EXLIA") == lc.EXCESS_LAYER
    assert lc.umbrella_layer("UMBRC") == lc.UMBRELLA_LAYER
    assert lc.is_container_label("CPKGE") and lc.is_container_label("Commercial Package (CPKGE)")
    assert not lc.is_container_label("BOP")
    assert lc.canon_line("BOP") == lc.canon_line("Businessowners Policy") is None


# ── 4. the percent leftovers ──────────────────────────────────────────────────

def test_the_picker_shows_a_bare_figure_as_written():
    from services.underwriting_consistency import _display_money
    rows = [{"display": "2"}, {"display": "$2"}, {"display": "2%"}]
    _display_money("property_deductible_wind", "currency", rows)
    assert [r["display"] for r in rows] == ["2", "$2", "2%"]
    plain = [{"display": "2500"}]
    _display_money("gl_deductible", "currency", plain)
    assert plain[0]["display"] == "$2,500"


def test_a_stale_client_half_is_cleared_a_producer_half_stays():
    from tests.test_build24_percent_review_b import (
        EQ_AMOUNT, QUAKE, _generated, _pair)
    from services import arq_service as arq
    facts = {"applicant_name": "Acme LLC"}
    after = {**facts, QUAKE: {"value": "2%", "source": "producer"}}
    for person, kept in (("client_arq", ""), ("producer", "25,000")):
        gen = {"ACORD_160": _generated("ACORD_160", facts)}
        gen["ACORD_160"]["field_state"][EQ_AMOUNT] = "25,000"
        gen["ACORD_160"]["confidence"][EQ_AMOUNT] = person
        gen["ACORD_160"]["client_filled_fields"] = [EQ_AMOUNT] if person == "client_arq" else []
        arq._restamp_canonical_into_forms(gen, QUAKE, after, provenance="producer")
        assert _pair(gen["ACORD_160"]["field_state"]) == (kept, "2")
        if not kept:
            assert EQ_AMOUNT not in gen["ACORD_160"]["confidence"]
            assert EQ_AMOUNT not in gen["ACORD_160"]["client_filled_fields"]


# ── 5. per-form scoring matches the form: 141 Crime, 160 Business Owners ──────

def test_the_inventories_name_the_forms_own_facts():
    from services.fact_registry import FACT_REGISTRY
    inv = sq.FORM_FIELD_INVENTORY
    assert "crime_limit" in inv["ACORD_141"] and "coinsurance_percentage" not in inv["ACORD_141"]
    assert "bop_property_limit" in inv["ACORD_160"]
    assert not any(k.startswith("inland_marine") for k in inv["ACORD_160"])
    for fid in ("ACORD_141", "ACORD_160"):
        assert all(k in FACT_REGISTRY for k in inv[fid]), fid


def _form(facts, fid, flags=None):
    return sq.calculate_sqs(facts, dict(flags or {}), {}, {}, [fid], [], [], 0, form_id=fid)


def test_141_is_scored_on_crime_facts_and_never_capped_by_cope():
    out = _form({"applicant_name": "Acme LLC"}, "ACORD_141", PROP)
    text = " | ".join(map(str, out.get("issues") or []))
    assert "Crime section missing: crime limit" in text
    # property on the package is read as on any non-property form: no COPE cap
    assert out.get("cap_applied") is None
    full = _form({"applicant_name": "Acme LLC", "crime_limit": "$250,000",
                  "crime_deductible": "$5,000", "crime_employee_count": "12"}, "ACORD_141")
    assert "Crime section missing" not in " | ".join(map(str, full.get("issues") or []))


def test_160_is_scored_on_business_owners_facts():
    out = _form({"applicant_name": "Acme LLC"}, "ACORD_160")
    text = " | ".join(map(str, out.get("issues") or []))
    assert "Business Owners section missing: BOP property limit" in text
    assert "Inland Marine" not in text
    full = _form({"applicant_name": "Acme LLC", "bop_property_limit": "$500,000",
                  "bop_liability_limit": "$1,000,000", "bop_deductible": "$1,000"}, "ACORD_160")
    assert "Business Owners section missing" not in " | ".join(map(str, full.get("issues") or []))


# ── 6. ACORD 133 is WC, property rules follow the property forms ─────────────

def test_133_is_scored_as_workers_comp_and_never_capped_by_cope():
    out = _form({"applicant_name": "X"}, "ACORD_133", PROP)
    text = " | ".join(map(str, out.get("issues") or []))
    assert out.get("cap_applied") is None
    assert "Workers Compensation section missing: WC class codes" in text
    assert "Builders Risk" not in text
    inv = sq.FORM_FIELD_INVENTORY["ACORD_133"]
    assert "wc_class_codes" in inv and not any(k.startswith("builders_risk") for k in inv)


@pytest.mark.parametrize("forms,fires", [({"ACORD_140"}, True), ({"ACORD_160"}, True),
                                          ({"ACORD_141"}, False), ({"ACORD_133"}, False)])
def test_property_cross_form_rules_follow_the_property_forms(forms, fires):
    facts = dict(_BASE, property_deductible_wind="$5,000")
    coin = cf._check_property_coinsurance_enforcement(facts, PROP, forms)
    ded = cf._check_property_deductible_structure(facts, PROP, forms)
    assert bool(coin) is fires and bool(ded) is fires
    for issue in coin + ded:
        assert "ACORD_141" not in issue.get("forms", issue.get("form_ids", []))


def test_the_140_template_prints_no_earthquake_or_flood_deductible():
    import json
    d = json.loads((BACKEND / "forms_schemas" / "ACORD_140_schema.json").read_text(encoding="utf-8"))
    names = d.get("fields", d)
    names = list(names) if isinstance(names, dict) else [x.get("name") for x in names]
    assert not [n for n in names if "earthquake" in n.lower() or "flood" in n.lower()]
    inv = sq.FORM_FIELD_INVENTORY
    assert "property_deductible_earthquake" in inv["ACORD_160"]
    assert "property_deductible_earthquake" not in inv["ACORD_140"]


# ── Review fixes (24 Oct 2026) ──────────────────────────────────────────────

@pytest.mark.parametrize("value, expected", [
    ("Agreed Value (no coinsurance)", True),
    ("Agreed value; coinsurance does not apply", True),
    ("No coinsurance, agreed value applies", True),
    ("Agreed Value Endorsement - Declined", False),
    ("agreed value endorsement not purchased", False),
    ("Coinsurance applies, no agreed value", False),
    ("No - coinsurance applies", False),
])
def test_agreed_value_reads_its_own_negation_not_coinsurances(value, expected):
    assert agreed_value_affirmed({"agreed_value_endorsement": value}) is expected
