"""ACORD 137 (state Commercial Auto Coverages / Limits) - client Orbin audit
2026-09-11, item 10.

Every auto fact the 137 needs was extracted, and the form still forced the $1M
combined single limit blank, wiped the Med Pay / UM / comp / collision symbols
as "phantom vehicles" and bound nothing to Med Pay, UM or the comp deductible.
`services/state_auto_grid` now decides the grid from the template's own layout.

  1. The module's two tables are anchored to the PRINTED templates, both states.
  2. The live Orbin facts go through `map_facts_to_form` (no raw text, so no
     LLM) and the test reads the boxes the PDF receives.
  3. The edge cases, one at a time.
  4. Fuzz: random packages against the invariants that make a wrong value
     impossible rather than unlikely.
"""

import json
import os
import random
import re
from functools import lru_cache

import pytest

from services import auto_symbols as sym
from services import state_auto_grid as sag
from services.pdf_service import (
    _resolve_auto_liability_limit_cell,
    _resolve_state_auto_grid,
    _SCHED_SKIP,
    compute_form_gaps,
    map_facts_to_form,
)

_BACKEND = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FORMS = ("ACORD_137_CO", "ACORD_137_CA")
BA, TR, MC = sym.BUSINESS_AUTO, sym.TRUCKERS, sym.MOTOR_CARRIER


@lru_cache(maxsize=None)
def _schema_cached(form_id):
    with open(os.path.join(_BACKEND, "forms_schemas", f"{form_id}_schema.json"),
              encoding="utf-8") as fh:
        return json.dumps(json.load(fh))


def _schema(form_id):
    return json.loads(_schema_cached(form_id))


def _digits(v):
    return re.sub(r"\D", "", str(v or ""))


def _ticked(v):
    return str(v or "").strip().lower() in ("yes", "y", "/yes", "on", "x", "true", "1")


def _vehicle_fields(form_id):
    return [f for f in sag.field_families(form_id) if f.startswith("Vehicle_")]


def _decide(facts, form_id="ACORD_137_CO"):
    return {f: sag.resolve(form_id, f, facts) for f in _vehicle_fields(form_id)}


# The live Orbin auto facts exactly as the merge produced them (session
# e7084347, replayed offline 14 Sep), with the session's flags merged in the way
# `process_single_form` merges them.
ORBIN_SYMBOLS = [
    {"symbols": [1], "coverage": "liability"},
    {"symbols": [2], "coverage": "medical payments"},
    {"symbols": [2], "coverage": "uninsured and underinsured motorists"},
    {"symbols": [7], "coverage": "comprehensive"},
    {"symbols": [7], "coverage": "collision"},
    {"symbols": [1], "coverage": "liability"},
    {"symbols": [], "coverage": "comprehensive"},
    {"symbols": [], "coverage": "collision"},
]
ORBIN_AUTO = {
    "applicant_name": "ORBIN CONTRACTING LLC",
    "state_of_operations": "CO",
    "auto_liability_limit": "$ 1,000,000",
    "auto_liability_structure": "combined single limit",
    "auto_med_pay_limit": "$ 5,000",
    "auto_um_uim_limit": "$ 1,000,000",
    "auto_deductible_comp": "$ 1000 DED",
    "auto_deductible_collision": "$ 1000 DED",
    "auto_physical_damage_valuation": "Actual Cash Value",
    "auto_hired_nonowned": "true",
    "auto_covered_symbols": ORBIN_SYMBOLS,
    "auto_vin_schedule": [{
        "gvw": None, "vin": "4S4BRCGC9C3217772", "make": "SUBARU", "year": "2012",
        "model": "OUTBACK SEDAN", "body_type": "PRIV PASSENGER", "coll_symbol": "07",
        "comp_symbol": "07", "class_code": "7383", "territory": "111"}],
    "has_auto_coverage": True, "has_auto_liability": True, "has_commercial_auto": True,
    "has_truckers_coverage": False, "has_motor_carrier_coverage": False,
    "auto_split_limits": False, "auto_has_um_uim": True,
}


def _orbin(**overrides):
    facts = json.loads(json.dumps(ORBIN_AUTO))
    for k, v in overrides.items():
        if v is _DROP:
            facts.pop(k, None)
        else:
            facts[k] = v
    return facts


_DROP = object()


# ─────────────────────────────────────────────────────────────────────────────
# 1. The tables are the templates' own layout
# ─────────────────────────────────────────────────────────────────────────────
_LABEL_OF = {sym.LIABILITY: "LIABILITY", sym.MEDICAL: "MEDICAL", sym.UM_UIM: "UNINSURED",
             sym.TOWING: "TOWING", sym.COMPREHENSIVE: "COMP",
             sag.SPECIFIED_CAUSES: "SPECIFIED", sym.COLLISION: "COLLISION"}
_GRID_OF = {BA: "BusinessAuto", TR: "Truckers", MC: "MotorCarrier"}
_COLUMN_SPLIT = 330     # coverage labels print at x=22 (left grid) and x=338 (right)


@lru_cache(maxsize=None)
def _geometry(form_id):
    pdfplumber = pytest.importorskip("pdfplumber")
    path = os.path.join(_BACKEND, "templates", f"{form_id}.pdf")
    if not os.path.exists(path):
        pytest.skip(f"{form_id} template not present")
    pages = []
    with pdfplumber.open(path) as pdf:
        for page in pdf.pages:
            words = tuple((w["text"].upper(), float(w["x0"]), float(w["top"]))
                          for w in page.extract_words())
            widgets = {}
            for a in page.annots or []:
                name = a.get("title") or ""
                if isinstance(name, bytes):
                    name = name.decode("latin-1", "ignore")
                widgets[str(name)] = (float(a["x0"]), float(a["top"]), float(a["bottom"]))
            pages.append((words, widgets))
    return tuple(pages)


def _page_of(pages, field):
    return next(i for i, (_w, wid) in enumerate(pages) if field in wid)


@pytest.mark.parametrize("form_id", FORMS)
def test_every_vehicle_field_is_placed_on_one_of_the_three_sections(form_id):
    fams = sag.field_families(form_id)
    missing = [f for f in _schema(form_id) if f.startswith("Vehicle_") and f not in fams]
    assert not missing, missing[:10]
    assert set(fams.values()) == {BA, TR, MC}
    for f, fam in fams.items():
        m = sag._GRID_RE.match(f)
        if m:
            assert sag._GRID_FAMILY[m.group("grid")] == fam, f


@pytest.mark.parametrize("form_id", FORMS)
@pytest.mark.parametrize("family", [BA, TR, MC])
def test_every_symbol_row_is_printed_beside_its_coverage(form_id, family):
    pages = _geometry(form_id)
    prefix = f"Vehicle_{_GRID_OF[family]}Symbol_"
    for row, coverage in sag.ROW_COVERAGE[family].items():
        names = [n for n in sag.field_families(form_id)
                 if n.startswith(prefix) and n.endswith(f"Indicator_{row}")]
        assert names, (family, row)
        words, widgets = pages[_page_of(pages, names[0])]
        boxes = [widgets[n] for n in names]
        centre = (min(b[1] for b in boxes) + max(b[2] for b in boxes)) / 2
        left = min(b[0] for b in boxes) < _COLUMN_SPLIT
        # The NEAREST coverage label in the row's own column. Rows sit 24pt
        # apart, so a fixed window catches the label of the row below too.
        label, _x, y = min(((t, x, y) for t, x, y in words
                            if t in _LABEL_OF.values() and (x < _COLUMN_SPLIT) == left),
                           key=lambda w: abs(w[2] - centre))
        assert label == _LABEL_OF[coverage] and abs(y - centre) <= 14, (
            form_id, family, row, label, y, centre)


@pytest.mark.parametrize("form_id", FORMS)
def test_every_limit_basis_tick_sits_on_its_coverage_row(form_id):
    pages = _geometry(form_id)
    fams = sag.field_families(form_id)
    for letter, coverage in sag.LIMIT_BASIS_ROW.items():
        for which in ("CombinedSingleLimit_LimitIndicator", "BodilyInjury_EachPersonLimitIndicator"):
            name = f"Vehicle_{which}_{letter}"
            family = fams[name]
            row = next(r for r, c in sag.ROW_COVERAGE[family].items() if c == coverage)
            grid = [n for n in fams if n.startswith(f"Vehicle_{_GRID_OF[family]}Symbol_")
                    and n.endswith(f"_{row}")]
            words, widgets = pages[_page_of(pages, name)]
            tops = [widgets[n][1] for n in grid]
            assert min(tops) - 4 <= widgets[name][1] <= max(tops) + 4, (form_id, name)


@pytest.mark.parametrize("form_id", FORMS)
def test_business_auto_deductibles_are_the_hired_physical_damage_block(form_id):
    """The page-1 COMP / COLL deductible boxes sit under HIRED PHYSICAL DAMAGE,
    below the whole symbol grid - the owned autos' deductibles are not on the
    137 at all (they belong to ACORD 127's vehicle schedule)."""
    pages = _geometry(form_id)
    words, widgets = pages[0]
    grid_bottom = max(b[2] for n, b in widgets.items()
                      if n.startswith("Vehicle_BusinessAutoSymbol_"))
    hired_top = min(y for t, _x, y in words if t == "HIRED")
    for n in ("Vehicle_Comprehensive_DeductibleAmount_A", "Vehicle_Collision_DeductibleAmount_A"):
        assert widgets[n][1] > grid_bottom and widgets[n][1] >= hired_top - 12, n


@pytest.mark.parametrize("form_id", FORMS)
@pytest.mark.parametrize("family, letter", [(TR, "B"), (MC, "C")])
def test_truckers_and_motor_carrier_deductibles_sit_on_their_own_pd_rows(form_id, family, letter):
    """...whereas on Truckers and Motor Carrier the same box names ARE the owned
    autos' deductibles, printed on the Comprehensive and Collision rows."""
    pages = _geometry(form_id)
    for base, coverage in (("Comprehensive_DeductibleAmount", sym.COMPREHENSIVE),
                           ("Collision_DeductibleAmount", sym.COLLISION)):
        name = f"Vehicle_{base}_{letter}"
        row = next(r for r, c in sag.ROW_COVERAGE[family].items() if c == coverage)
        words, widgets = pages[_page_of(pages, name)]
        tops = [b[1] for n, b in widgets.items()
                if n.startswith(f"Vehicle_{_GRID_OF[family]}Symbol_") and n.endswith(f"_{row}")]
        assert min(tops) - 4 <= widgets[name][1] <= max(tops) + 4, (form_id, name)


# ─────────────────────────────────────────────────────────────────────────────
# 2. The live Orbin package, through the entry point the PDF is built from
# ─────────────────────────────────────────────────────────────────────────────
_ORBIN_TICKS = {("One", "A"), ("Two", "B"), ("Two", "C"), ("Seven", "F"), ("Seven", "H")}


@pytest.mark.parametrize("form_id", FORMS)
def test_orbin_137_carries_every_auto_fact_in_its_own_box(form_id):
    mapped, _conf = map_facts_to_form(_orbin(), _schema(form_id), form_id=form_id, raw_text="")

    # Liability: combined single limit, in the box printed "CSL / BI EA PER".
    assert _ticked(mapped.get("Vehicle_CombinedSingleLimit_LimitIndicator_A"))
    assert not _ticked(mapped.get("Vehicle_BodilyInjury_EachPersonLimitIndicator_A"))
    assert _digits(mapped.get("Vehicle_BodilyInjury_PerPersonLimitAmount_A")) == "1000000"
    assert not _digits(mapped.get("Vehicle_BodilyInjury_PerAccidentLimitAmount_A"))
    assert not _digits(mapped.get("Vehicle_PropertyDamage_PerAccidentLimitAmount_A"))
    # Medical payments $5,000.
    assert _digits(mapped.get("Vehicle_MedicalPayments_PerPersonLimitAmount_A")) == "5000"
    # UM (Colorado's UM includes UIM; the 137 CO prints no separate UIM box).
    assert _ticked(mapped.get("Vehicle_CombinedSingleLimit_LimitIndicator_B"))
    assert not _ticked(mapped.get("Vehicle_BodilyInjury_EachPersonLimitIndicator_B"))
    assert _digits(mapped.get(
        "Vehicle_UninsuredMotorists_BodilyInjuryPerPersonLimitAmount_A")) == "1000000"
    assert not _digits(mapped.get(
        "Vehicle_UninsuredMotorists_BodilyInjuryPerAccidentLimitAmount_A"))
    assert not _digits(mapped.get("Vehicle_UninsuredMotorists_PropertyDamagePerAccidentLimit_A"))
    assert not any("nderinsured" in f for f in _schema(form_id))

    # Symbols: 1 liability, 2 med pay, 2 UM, 7 comp, 7 collision - and nothing else.
    for f in _vehicle_fields(form_id):
        m = sag._GRID_RE.match(f)
        if not m or m.group("grid") != "BusinessAuto" or m.group("kind") != "Indicator":
            continue
        want = (m.group("word"), m.group("row")) in _ORBIN_TICKS
        assert _ticked(mapped.get(f)) == want, (f, mapped.get(f))


@pytest.mark.parametrize("form_id", FORMS)
def test_orbin_sections_it_does_not_carry_stay_blank_and_are_never_asked(form_id):
    mapped, unmatched, _det = compute_form_gaps(form_id, _schema(form_id), _orbin())
    fams = sag.field_families(form_id)
    other = [f for f in _schema(form_id) if f.startswith("Vehicle_") and fams.get(f) in (TR, MC)]
    assert other
    assert not [f for f in other if f in unmatched]
    assert not [f for f in other if _ticked(mapped.get(f)) or _digits(mapped.get(f))]


@pytest.mark.parametrize("form_id", FORMS)
def test_orbin_hired_physical_damage_is_asked_of_the_document(form_id):
    """Orbin's hired-auto physical damage comes from the Auto Elite Extension
    (CA7450 section M: deductible = the largest owned-auto deductible). No
    extracted fact carries it, and the owned deductible is not evidence of it -
    so the document decides, and the 127 binding no longer stamps it."""
    mapped, unmatched, _det = compute_form_gaps(form_id, _schema(form_id), _orbin())
    for f in ("Vehicle_Comprehensive_DeductibleAmount_A", "Vehicle_Collision_DeductibleAmount_A",
              "Vehicle_Coverage_ComprehensiveDeductibleIndicator_A",
              "Vehicle_Coverage_CollisionIndicator_A"):
        assert f in unmatched and not mapped.get(f), f


# ─────────────────────────────────────────────────────────────────────────────
# 3. Edge cases
# ─────────────────────────────────────────────────────────────────────────────
def test_split_liability_fills_three_boxes_and_ticks_each_person():
    d = _decide(_orbin(auto_liability_limit=_DROP, auto_split_limits=True,
                       auto_bi_per_person="$500,000", auto_bi_per_accident="$1,000,000",
                       auto_pd_per_accident="$250,000"))
    assert d["Vehicle_CombinedSingleLimit_LimitIndicator_A"] == "No"
    assert d["Vehicle_BodilyInjury_EachPersonLimitIndicator_A"] == "Yes"
    assert d["Vehicle_BodilyInjury_PerPersonLimitAmount_A"] == "$500,000"
    assert d["Vehicle_BodilyInjury_PerAccidentLimitAmount_A"] == "$1,000,000"
    assert d["Vehicle_PropertyDamage_PerAccidentLimitAmount_A"] == "$250,000"


def test_a_csl_fact_written_as_a_split_is_read_as_the_split():
    d = _decide(_orbin(auto_liability_limit="$500,000/$1,000,000/$250,000"))
    assert d["Vehicle_CombinedSingleLimit_LimitIndicator_A"] == "No"
    assert d["Vehicle_BodilyInjury_PerPersonLimitAmount_A"] == "$500,000"
    assert d["Vehicle_PropertyDamage_PerAccidentLimitAmount_A"] == "$250,000"


@pytest.mark.parametrize("value", ["$1,000,000 CSL / $5,000 med pay",
                                   "$500,000 BI / $250,000 PD each accident",
                                   "1,000,000 2,000,000"])
def test_an_unreadable_limit_is_asked_never_guessed(value):
    d = _decide(_orbin(auto_liability_limit=value))
    for f in ("Vehicle_CombinedSingleLimit_LimitIndicator_A",
              "Vehicle_BodilyInjury_PerPersonLimitAmount_A",
              "Vehicle_BodilyInjury_PerAccidentLimitAmount_A"):
        assert d[f] == sag.ASK, (f, d[f])


def test_no_liability_fact_changes_nothing():
    d = _decide(_orbin(auto_liability_limit=_DROP))
    assert d["Vehicle_BodilyInjury_PerPersonLimitAmount_A"] is sag.SKIP
    assert d["Vehicle_CombinedSingleLimit_LimitIndicator_A"] is sag.SKIP


def test_split_um_fills_its_three_boxes():
    d = _decide(_orbin(auto_um_uim_limit="$25,000/$50,000/$25,000"))
    assert d["Vehicle_CombinedSingleLimit_LimitIndicator_B"] == "No"
    assert d["Vehicle_BodilyInjury_EachPersonLimitIndicator_B"] == "Yes"
    assert d["Vehicle_UninsuredMotorists_BodilyInjuryPerPersonLimitAmount_A"] == "$25,000"
    assert d["Vehicle_UninsuredMotorists_BodilyInjuryPerAccidentLimitAmount_A"] == "$50,000"
    assert d["Vehicle_UninsuredMotorists_PropertyDamagePerAccidentLimit_A"] == "$25,000"


@pytest.mark.parametrize("um, symbols_for_um, expected", [
    (_DROP, [2], sag.ASK),          # carried (a symbol), amount not extracted -> document
    ("Included", [2], sag.ASK),     # no amount in the words -> document
    (_DROP, None, None),            # the symbol table was read and UM is not in it
])
def test_um_without_an_amount(um, symbols_for_um, expected):
    symbols = [e for e in ORBIN_SYMBOLS if "uninsured" not in e["coverage"]]
    if symbols_for_um:
        symbols.append({"coverage": "uninsured motorists", "symbols": symbols_for_um})
    d = _decide(_orbin(auto_um_uim_limit=um, auto_covered_symbols=symbols))
    assert d["Vehicle_UninsuredMotorists_BodilyInjuryPerPersonLimitAmount_A"] == expected
    assert d["Vehicle_CombinedSingleLimit_LimitIndicator_B"] == expected


def test_med_pay_without_an_amount():
    d = _decide(_orbin(auto_med_pay_limit=_DROP))
    assert d["Vehicle_MedicalPayments_PerPersonLimitAmount_A"] == sag.ASK
    d = _decide(_orbin(auto_med_pay_limit=_DROP, auto_covered_symbols=[
        e for e in ORBIN_SYMBOLS if e["coverage"] != "medical payments"]))
    assert d["Vehicle_MedicalPayments_PerPersonLimitAmount_A"] is None


def test_no_symbols_at_all():
    d = _decide(_orbin(auto_covered_symbols=_DROP))
    # Liability row: today's behaviour (the model reads the dec's own line).
    assert d["Vehicle_BusinessAutoSymbol_OneIndicator_A"] is sag.SKIP
    # Rows B-H print word-for-word identical tooltips: never a guess.
    assert d["Vehicle_BusinessAutoSymbol_TwoIndicator_B"] is None
    assert d["Vehicle_BusinessAutoSymbol_SevenIndicator_F"] is None
    # The flags deny truckers and motor carrier: their pages are owned blanks.
    assert d["Vehicle_TruckersSymbol_FortyOneIndicator_A"] is None
    assert d["Vehicle_BodilyInjury_PerPersonLimitAmount_C"] is None


def test_no_symbols_and_no_flags_decides_nothing():
    facts = {"auto_liability_limit": "$1,000,000"}
    assert set(map(id, _decide(facts).values())) == {id(sag.SKIP)}


@pytest.mark.parametrize("liability, other, code", [([5], [], "5"), ([19, 1], [], "19")])
def test_a_symbol_acord_does_not_print_goes_in_the_other_box(liability, other, code):
    d = _decide(_orbin(auto_covered_symbols=[{"coverage": "liability", "symbols": liability}]))
    assert d["Vehicle_BusinessAutoSymbol_OtherSymbolIndicator_A"] == "Yes"
    assert d["Vehicle_BusinessAutoSymbol_OtherSymbolCode_A"] == code
    assert d["Vehicle_BusinessAutoSymbol_OneIndicator_A"] == ("Yes" if 1 in liability else "No")


def test_an_own_family_symbol_the_row_does_not_print_goes_in_the_other_box():
    d = _decide(_orbin(auto_covered_symbols=[{"coverage": "medical payments", "symbols": [1]}]))
    assert d["Vehicle_BusinessAutoSymbol_OtherSymbolIndicator_B"] == "Yes"
    assert d["Vehicle_BusinessAutoSymbol_OtherSymbolCode_B"] == "1"
    assert d["Vehicle_BusinessAutoSymbol_TwoIndicator_B"] == "No"


def test_an_unattributed_legacy_list_never_reaches_rows_b_to_h():
    d = _decide(_orbin(auto_covered_symbols=[1, 7]))
    assert d["Vehicle_BusinessAutoSymbol_OneIndicator_A"] == "Yes"
    assert d["Vehicle_BusinessAutoSymbol_SevenIndicator_A"] == "Yes"
    for row in "BCEFGH":
        assert all(v is None for f, v in d.items()
                   if f.startswith("Vehicle_BusinessAutoSymbol_") and f.endswith(f"_{row}")), row


@pytest.mark.parametrize("label", ["Comprehensive and Collision", "Physical Damage", "Comp/Coll"])
def test_a_combined_physical_damage_label_ticks_both_rows(label):
    d = _decide(_orbin(auto_covered_symbols=[{"coverage": "liability", "symbols": [1]},
                                             {"coverage": label, "symbols": [7]}]))
    assert d["Vehicle_BusinessAutoSymbol_SevenIndicator_F"] == "Yes"
    assert d["Vehicle_BusinessAutoSymbol_SevenIndicator_H"] == "Yes"


def test_a_truckers_policy_fills_the_truckers_page_only():
    facts = _orbin(has_truckers_coverage=True, auto_covered_symbols=[
        {"coverage": "liability", "symbols": [41]},
        {"coverage": "comprehensive", "symbols": [46]},
        {"coverage": "collision", "symbols": [46]}])
    d = _decide(facts)
    assert d["Vehicle_TruckersSymbol_FortyOneIndicator_A"] == "Yes"
    assert d["Vehicle_TruckersSymbol_FortySixIndicator_E"] == "Yes"      # comp row
    assert d["Vehicle_TruckersSymbol_FortySixIndicator_G"] == "Yes"      # collision row
    assert d["Vehicle_BodilyInjury_PerPersonLimitAmount_B"] == "$ 1,000,000"
    assert d["Vehicle_Comprehensive_DeductibleAmount_B"] == "$ 1000 DED"  # owned PD here
    assert d["Vehicle_Collision_DeductibleAmount_B"] == "$ 1000 DED"
    for f, v in d.items():
        if sag.field_families("ACORD_137_CO")[f] in (BA, MC):
            assert v is None, (f, v)


def test_a_package_on_two_families_lets_the_document_place_its_limits():
    d = _decide(_orbin(auto_covered_symbols=[{"coverage": "liability", "symbols": [1, 41]}]))
    assert d["Vehicle_BusinessAutoSymbol_OneIndicator_A"] == "Yes"
    assert d["Vehicle_TruckersSymbol_FortyOneIndicator_A"] == "Yes"
    for f in ("Vehicle_BodilyInjury_PerPersonLimitAmount_A", "Vehicle_BodilyInjury_PerPersonLimitAmount_B",
              "Vehicle_CombinedSingleLimit_LimitIndicator_A", "Vehicle_CombinedSingleLimit_LimitIndicator_D"):
        assert d[f] == sag.ASK, f
    assert d["Vehicle_BodilyInjury_PerPersonLimitAmount_C"] is None     # motor carrier absent


def test_a_garage_only_package_carries_no_137_section():
    d = _decide(_orbin(auto_covered_symbols=[{"coverage": "liability", "symbols": [21]}]))
    assert all(v is None for v in d.values())


def test_a_fleet_never_puts_the_owned_deductible_in_other_sections():
    """The latent defect: with three vehicles the phantom rule stepped aside and
    the 127 binding stamped vehicle 2's and 3's 'collision deductible' into the
    TRUCKERS and MOTOR CARRIER sections."""
    vehicle = ORBIN_AUTO["auto_vin_schedule"][0]
    fleet = [dict(vehicle, vin=f"4S4BRCGC9C321777{i}") for i in range(3)]
    mapped, unmatched, _det = compute_form_gaps("ACORD_137_CO", _schema("ACORD_137_CO"),
                                                _orbin(auto_vin_schedule=fleet))
    for f in ("Vehicle_Collision_DeductibleAmount_B", "Vehicle_Collision_DeductibleAmount_C",
              "Vehicle_Comprehensive_DeductibleAmount_B", "Vehicle_Comprehensive_DeductibleAmount_C"):
        assert not mapped.get(f) and f not in unmatched, f
    assert _ticked(mapped.get("Vehicle_BusinessAutoSymbol_TwoIndicator_B"))
    assert _ticked(mapped.get("Vehicle_BusinessAutoSymbol_SevenIndicator_H"))


def test_facts_in_envelopes_read_the_same():
    wrapped = {k: ({"value": v, "source": "extraction"} if not isinstance(v, bool) else v)
               for k, v in ORBIN_AUTO.items()}
    assert _decide(wrapped) == _decide(_orbin())


@pytest.mark.parametrize("facts", [None, {}, {"auto_covered_symbols": "garbage"},
                                   {"auto_covered_symbols": {"liability": "one"}},
                                   {"auto_um_uim_limit": ["$1M"], "has_auto_coverage": True},
                                   {"auto_liability_limit": 1000000, "has_auto_coverage": "yes"}])
def test_malformed_facts_never_raise(facts):
    for form_id in FORMS:
        out = _decide(facts, form_id)
        assert all(v is sag.SKIP or v is None or isinstance(v, str) for v in out.values())


def test_other_forms_are_not_touched():
    for form_id in ("ACORD_127", "ACORD_25", "ACORD_131", "ACORD_138_CO"):
        for f in _schema(form_id):
            assert sag.resolve(form_id, f, _orbin()) is sag.SKIP
            assert _resolve_state_auto_grid(f, {**_orbin(), "_form_id": form_id}) is _SCHED_SKIP


def test_acord_127_still_stamps_the_owned_deductibles():
    mapped, _u, _d = compute_form_gaps("ACORD_127", _schema("ACORD_127"), _orbin())
    assert _digits(mapped.get("Vehicle_Collision_DeductibleAmount_A")) == "1000"
    assert _digits(mapped.get(
        "Vehicle_Coverage_ComprehensiveOrSpecifiedCauseOfLossDeductibleAmount_A")) == "1000"


_TWO_AMOUNTS = ["$250,000/$500,000/$100,000/$50,000", "$25,000 / $50,000",
                "$1,000,000 CSL / $5,000 deductible", "$500 comp / $1,000 coll"]


@pytest.mark.parametrize("form_id", FORMS)
@pytest.mark.parametrize("two", _TWO_AMOUNTS)
def test_a_box_for_one_amount_never_takes_a_fact_stating_two(form_id, two):
    """Found by the 14 Sep screen-level fuzz: a per-person fact holding four
    limits printed "25,000,050,000,010,000,050,000" in the CSL / BI EA PER box.
    Each box asks the document instead; the sibling boxes are unaffected."""
    ba = {"has_auto_coverage": True,
          "auto_covered_symbols": [{"coverage": "liability", "symbols": [1]},
                                   {"coverage": "medical payments", "symbols": [2]}]}
    split = {**ba, "auto_split_limits": True, "auto_bi_per_person": two,
             "auto_bi_per_accident": "$500,000", "auto_pd_per_accident": "$100,000"}
    assert sag.resolve(form_id, "Vehicle_BodilyInjury_PerPersonLimitAmount_A", split) == sag.ASK
    assert sag.resolve(form_id, "Vehicle_BodilyInjury_PerAccidentLimitAmount_A", split) == "$500,000"
    assert sag.resolve(form_id, "Vehicle_MedicalPayments_PerPersonLimitAmount_A",
                       {**ba, "auto_med_pay_limit": two}) == sag.ASK
    assert sag.resolve(form_id, "Vehicle_MedicalPayments_PerPersonLimitAmount_A",
                       {**ba, "auto_med_pay_limit": "$5,000"}) == "$5,000"
    truckers = {"auto_covered_symbols": [{"coverage": "liability", "symbols": [41]}],
                "auto_deductible_comp": two, "auto_deductible_collision": "$ 1000 DED"}
    fams = sag.field_families(form_id)
    assert fams.get("Vehicle_Comprehensive_DeductibleAmount_B") == TR
    assert sag.resolve(form_id, "Vehicle_Comprehensive_DeductibleAmount_B", truckers) == sag.ASK
    assert sag.resolve(form_id, "Vehicle_Collision_DeductibleAmount_B", truckers) == "$ 1000 DED"


def test_a_dedicated_csl_box_elsewhere_still_takes_the_limit():
    facts = {**_orbin(), "_form_id": "ACORD_25"}
    assert _resolve_auto_liability_limit_cell(
        "Vehicle_CombinedSingleLimit_EachAccidentAmount_A", facts) == "$ 1,000,000"


# ─────────────────────────────────────────────────────────────────────────────
# 4. Fuzz
# ─────────────────────────────────────────────────────────────────────────────
_AMOUNTS = ["$1,000,000", "1000000", "$ 1,000,000", "1,000,000 CSL",
            "$500,000 combined single limit", "$25,000/$50,000", "25/50/25",
            "$100,000 / $300,000 / $50,000", "Included", "", None,
            "$1,000,000 CSL / $5,000 deductible", "See endorsement", "$1M", 1000000,
            "$250,000/$500,000/$100,000/$50,000"]
_DEDUCTIBLES = ["$ 1000 DED", "$500", "1,000", "", None, "Not covered", "$2,500 each auto"]
_COVERAGES = ["liability", "medical payments", "uninsured motorists",
              "uninsured and underinsured motorists", "comprehensive", "collision",
              "towing", "physical damage", "comp and collision", "specified causes of loss",
              "drive other car", "covered autos"]
_POOLS = {fam: sorted(sym.BY_FAMILY[fam]) for fam in (BA, TR, MC, sym.GARAGE)}
_AMOUNT_KEYS = ("auto_liability_limit", "auto_bi_per_person", "auto_bi_per_accident",
                "auto_pd_per_accident", "auto_med_pay_limit", "auto_um_uim_limit",
                "auto_deductible_comp", "auto_deductible_collision")


def _random_facts(rng):
    families = rng.choice([[BA], [BA], [TR], [MC], [BA, TR], [sym.GARAGE], []])
    symbols = []
    for cov in rng.sample(_COVERAGES, rng.randint(0, len(_COVERAGES))):
        nums = []
        for fam in families:
            nums += rng.sample(_POOLS[fam], rng.randint(0, 2))
        if rng.random() < 0.1:
            nums.append(rng.choice([5, 19, 150]))
        symbols.append({"coverage": cov, "symbols": nums})
    if rng.random() < 0.08:
        symbols = [rng.choice(_POOLS[BA]) for _ in range(rng.randint(1, 3))]
    facts = {
        "auto_covered_symbols": symbols,
        "auto_liability_limit": rng.choice(_AMOUNTS),
        "auto_med_pay_limit": rng.choice(["$5,000", "$1,000", None, "", "Included"]),
        "auto_um_uim_limit": rng.choice(_AMOUNTS),
        "auto_deductible_comp": rng.choice(_DEDUCTIBLES),
        "auto_deductible_collision": rng.choice(_DEDUCTIBLES),
        "auto_split_limits": rng.choice([True, False, None, "true", "no"]),
        "has_auto_coverage": rng.choice([True, False, None]),
        "has_truckers_coverage": rng.choice([True, False, None]),
        "has_motor_carrier_coverage": rng.choice([True, False, None]),
        "auto_vin_schedule": [{"vin": f"VIN{i}"} for i in range(rng.randint(0, 4))],
    }
    if rng.random() < 0.4:
        facts.update({"auto_bi_per_person": rng.choice(_AMOUNTS),
                      "auto_bi_per_accident": rng.choice(_AMOUNTS),
                      "auto_pd_per_accident": rng.choice(_AMOUNTS)})
    for k in list(facts):
        if facts[k] is None and rng.random() < 0.5:
            del facts[k]
        elif rng.random() < 0.15 and not isinstance(facts.get(k), bool):
            facts[k] = {"value": facts[k], "source": "extraction"}
    return facts


def _plain(v):
    return v.get("value") if isinstance(v, dict) and "value" in v else v


def _allowed_values(facts):
    out = set()
    for k in _AMOUNT_KEYS:
        v = _plain(facts.get(k))
        if v is None or isinstance(v, (bool, list, dict)):
            continue
        s = str(v).strip()
        out.add(s)
        out.update(p.strip() for p in s.split("/"))
    return out


def _check_invariants(form_id, facts):
    fams = sag.field_families(form_id)
    decided = _decide(facts, form_id)
    present, absent = sag.families(facts)
    allowed = _allowed_values(facts)
    structure, _parts = sag.liability_limits(facts)
    for f, out in decided.items():
        assert out is sag.SKIP or out is None or isinstance(out, str), (f, out)
        page = fams[f]
        if page in absent:
            assert out is None, (f, out)
        elif page not in present:
            assert out is sag.SKIP, (f, out)
        if not isinstance(out, str) or out in ("Yes", "No", sag.ASK):
            continue
        if "SymbolCode" in f:
            assert all(tok.isdigit() for tok in out.split(", ")), (f, out)
            continue
        # A value is ALWAYS an extracted fact or a "/" part of one - never made up.
        assert out in allowed, (f, out, allowed)
        # One box, one amount: the display formatter keeps only the digits, so
        # a two-amount value would print as a number nobody wrote.
        assert len(sag._NUMBER_RE.findall(out)) == 1, (f, out)
        if len(present) > 1:
            raise AssertionError(f"a two-family package stamped {f}={out!r}")
        if structure == "csl" and ("PerAccident" in f or "PropertyDamage_" in f) \
                and "Uninsured" not in f:
            raise AssertionError(f"a CSL policy filled a split box {f}={out!r}")
    for f, out in decided.items():
        m = sag._GRID_RE.match(f)
        if not m or out != "Yes" or m.group("word") == "OtherSymbol":
            continue
        family = fams[f]
        coverage = sag.ROW_COVERAGE[family][m.group("row")]
        number = next(s.number for s in sym.BY_FAMILY[family].values() if s.word == m.group("word"))
        assert number in sag._designated(facts, coverage), (f, number)
    for letter in sag.LIMIT_BASIS_ROW:
        csl = decided.get(f"Vehicle_CombinedSingleLimit_LimitIndicator_{letter}")
        each = decided.get(f"Vehicle_BodilyInjury_EachPersonLimitIndicator_{letter}")
        assert not (csl == "Yes" and each == "Yes"), letter
    for base in sag._PD_BASES:
        out = decided.get(f"Vehicle_{base}_A")
        assert out is sag.SKIP or out is None or out == sag.ASK, (base, out)


@pytest.mark.parametrize("seed", range(8))
def test_fuzz_every_answer_is_a_fact_or_a_tick_the_document_supports(seed):
    rng = random.Random(1400 + seed)
    for i in range(60):
        _check_invariants(FORMS[i % 2], _random_facts(rng))


def test_fuzz_through_the_gap_list_the_llm_would_receive():
    rng = random.Random(9137)
    for i in range(24):
        form_id = FORMS[i % 2]
        facts = _random_facts(rng)
        mapped, unmatched, _det = compute_form_gaps(form_id, _schema(form_id), facts)
        present, absent = sag.families(facts)
        fams = sag.field_families(form_id)
        for f in _schema(form_id):
            if fams.get(f) in absent and f.startswith("Vehicle_"):
                assert f not in unmatched and not mapped.get(f), (f, mapped.get(f))
