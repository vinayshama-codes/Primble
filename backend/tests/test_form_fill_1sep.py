"""
Tests for the 1 Sep 2026 form-fill work. See `1sep-form-filling-increase.md`.

Every test here is written from the LIVE run's own data (session 4a527824,
document `t1_test_data/T1_verdant_slope_package.pdf`), not from an invented
fixture. That matters: the two bugs this repo has previously introduced *by* a
fix both passed their unit tests, because both fixtures were easier than reality.

Each issue gets two kinds of test:

  * a DEFECT test, which fails before the fix and passes after it, and
  * one or more GUARD tests, which pass BOTH before and after - these pin the
    behaviour the original code was written to protect. A fix that breaks a
    guard test is not a fix.
"""
from __future__ import annotations

import os
import re

import pytest


def _amt(v):
    """The stamped amount without a leading currency symbol.

    ACORD prints "$" beside most money boxes, so `pdf_service` no longer
    stamps one there (2026-09-05, the live "$ $3,954" defect). These tests
    are about WHICH BOX GOT WHICH AMOUNT, never about the symbol.
    """
    return str(v or "").strip().lstrip("$").strip()


os.environ.setdefault("OPENAI_API_KEY", "sk-offline-tests")


# ═════════════════════════════════════════════════════════════════════════════
# I2 - a schedule row printed twice must merge into one
# ═════════════════════════════════════════════════════════════════════════════
# The live document prints its loss run twice: once in a summary table with no
# reserve column, and again in a "Supplemental Loss Detail" block ~14 pages
# later WITH reserves. Both printings were kept, so ACORD 131 printed six rows
# for five losses and every cell after row C described the wrong claim.
_LIVE_LOSSES = [
    {"claim_number": "GL-2025-30712", "date": "02/28/2025", "paid": "$91,000",
     "reserved_amount": None, "description": "Fall from scaffold"},
    {"claim_number": "GL-2023-11884", "date": "07/22/2023", "paid": "$38,400",
     "reserved_amount": None, "description": "Water damage to third party finishes"},
    {"claim_number": "GL-2025-41220", "date": "09/03/2025", "paid": "$0",
     "reserved_amount": None, "description": "Alleged faulty installation"},
    {"claim_number": "GL-2025-30712", "date": "02/28/2025", "paid": "$91,000",
     "reserved_amount": "$145,000", "description": "Fall from scaffold"},
    {"claim_number": "GL-2023-11884", "date": "07/22/2023", "paid": "$38,400",
     "reserved_amount": "$0", "description": "Water damage to third party finishes"},
    {"claim_number": "GL-2025-41220", "date": "09/03/2025", "paid": "$0",
     "reserved_amount": "$75,000", "description": "Alleged faulty installation"},
    {"claim_number": "AU-2024-20551", "date": "11/09/2024", "paid": "$6,215",
     "reserved_amount": "$0", "description": "Backing collision"},
    {"claim_number": "PR-2022-08109", "date": "05/16/2022", "paid": "$212,880",
     "reserved_amount": "$0", "description": "Hail damage to owned warehouse roof"},
]

_LIVE_UNDERLYING = [
    {"line": "General Liability", "policy_no": "CPP 4Q 887214 26",
     "carrier": "Cascade Summit Mutual Insurance Company",
     "limit": "$1,000,000 each occurrence / $2,000,000 aggregate"},
    {"line": "Automobile Liability", "policy_no": "CPP 4Q 887214 26",
     "carrier": "Cascade Summit Mutual Insurance Company", "limit": "$1,000,000 CSL"},
    {"line": "Employers Liability", "policy_no": "WC 9930221 26",
     "carrier": "Foundry State Compensation Fund", "limit": "$1,000,000 / $1,000,000"},
    {"line": "Contractors Pollution Liability", "policy_no": "CPL 3308821 26",
     "carrier": "Meridian Environmental Indemnity Company", "limit": "$1,000,000 CSL"},
    # the second printing - note the GL row carries the UMBRELLA's limit, which
    # is wrong; the merge must keep the FIRST, correct value.
    {"line": "General Liability", "policy_no": "CPP 4Q 887214 26",
     "carrier": "Cascade Summit Mutual Insurance Company", "limit": "$5,000,000"},
    {"line": "Automobile Liability", "policy_no": "CPP 4Q 887214 26",
     "carrier": "Cascade Summit Mutual Insurance Company", "limit": "$1,000,000"},
    {"line": "Employers Liability", "policy_no": "WC 9930221 26",
     "carrier": "Foundry State Compensation Fund", "limit": None},
    {"line": "Contractors Pollution Liability", "policy_no": "CPL 3308821 26",
     "carrier": "Meridian Environmental Indemnity Company", "limit": "$1,000,000"},
]

_LIVE_GL_HAZARDS = [
    {"location": "001", "class_code": "91340", "premium_basis": "Payroll",
     "exposure_amount": "1,318,000", "territory": "008"},
    {"location": "002", "class_code": "91580", "premium_basis": "Total Cost",
     "exposure_amount": "2,145,000", "territory": "008"},
    {"location": "004", "class_code": "92478", "premium_basis": "Payroll",
     "exposure_amount": "486,000", "territory": "008"},
    # the second printing, with the raw "(p)" basis codes - and note extraction
    # put the WRONG location on the first of them (002, should be 001).
    {"location": "002", "class_code": "91340", "premium_basis": "(p) Payroll",
     "exposure_amount": "1,318,000", "territory": "008"},
    {"location": "002", "class_code": "91580", "premium_basis": "(c) Total Cost",
     "exposure_amount": "2,145,000", "territory": "008"},
    {"location": "004", "class_code": "92478", "premium_basis": "(p) Payroll",
     "exposure_amount": "486,000", "territory": "008"},
]


def _dedupe(list_key, items):
    from services.extraction_service import _dedupe_schedule_rows
    return _dedupe_schedule_rows(list_key, items)


def test_i2_loss_run_printed_twice_merges_on_claim_number():
    """DEFECT. 8 rows, 5 real claims. Before the fix this returned 8."""
    out = _dedupe("loss_history", _LIVE_LOSSES)
    assert len(out) == 5, [r.get("claim_number") for r in out]
    assert {r["claim_number"] for r in out} == {
        "GL-2025-30712", "GL-2023-11884", "GL-2025-41220",
        "AU-2024-20551", "PR-2022-08109"}


def test_i2_merge_recovers_the_reserve_from_the_second_printing():
    """The two printings are COMPLEMENTARY - the summary has no reserves, the
    supplemental block does. Merging must gain data, never lose it."""
    out = {r["claim_number"]: r for r in _dedupe("loss_history", _LIVE_LOSSES)}
    assert out["GL-2025-30712"]["reserved_amount"] == "$145,000"
    assert out["GL-2025-41220"]["reserved_amount"] == "$75,000"
    assert out["GL-2025-30712"]["paid"] == "$91,000"


def test_i2_two_different_claims_never_merge():
    """GUARD. Distinct claim numbers are distinct losses however alike they read."""
    rows = [
        {"claim_number": "GL-2025-00001", "paid": "$5,000", "description": "Slip and fall"},
        {"claim_number": "GL-2025-00002", "paid": "$5,000", "description": "Slip and fall"},
    ]
    assert len(_dedupe("loss_history", rows)) == 2


def test_i2_a_loss_row_with_no_claim_number_is_never_merged():
    """GUARD. Positive evidence only - the rule the whole module follows. Two
    losses with no identifier might be one loss or two, and we must not guess."""
    rows = [
        {"date": "01/02/2025", "paid": "$1,000", "description": "Loss A"},
        {"date": "01/02/2025", "paid": "$1,000", "description": "Loss A"},
    ]
    assert len(_dedupe("loss_history", rows)) == 2


def test_i2_underlying_policies_merge_on_line_and_policy_pair():
    """DEFECT. 8 rows, 4 real policies. GL and Auto legitimately SHARE one
    package policy number, so the number alone cannot be the key."""
    out = _dedupe("underlying_policies", _LIVE_UNDERLYING)
    assert len(out) == 4, [(r.get("line"), r.get("policy_no")) for r in out]
    by_line = {r["line"]: r for r in out}
    # the FIRST, correct GL limit survives - not the umbrella's $5,000,000
    assert by_line["General Liability"]["limit"].startswith("$1,000,000")


def test_i2_two_policies_on_the_same_line_are_kept():
    """GUARD. The D-1 defect: two different carriers' GL policies are two
    policies. Merging them on the line alone hid a real conflict."""
    rows = [
        {"line": "General Liability", "policy_no": "BBC7263-26", "carrier": "EMC"},
        {"line": "General Liability", "policy_no": "GL-4471102-26", "carrier": "Travelers"},
    ]
    assert len(_dedupe("underlying_policies", rows)) == 2


def test_i2_one_policy_number_across_several_lines_is_kept():
    """GUARD. The inverse, and the reason `policy_number` must never join the
    generic identifier set: one contract carries many coverage parts."""
    rows = [
        {"line": "General Liability", "policy_no": "CPP 4Q 887214 26"},
        {"line": "Automobile Liability", "policy_no": "CPP 4Q 887214 26"},
        {"line": "Employers Liability", "policy_no": "CPP 4Q 887214 26"},
    ]
    assert len(_dedupe("underlying_policies", rows)) == 3


def test_i2_gl_hazard_rows_printed_twice_merge():
    """DEFECT. 6 rows, 3 real classifications. The duplicate carries a WRONG
    location, so location cannot be part of the key - the fix keys on
    class + territory + exposure, mirroring `_wc_class_dedup_keys`."""
    out = _dedupe("gl_class_code_schedule", _LIVE_GL_HAZARDS)
    assert len(out) == 3, [(r.get("class_code"), r.get("location")) for r in out]
    by_code = {r["class_code"]: r for r in out}
    # the FIRST row's correct location survives the merge
    assert by_code["91340"]["location"] == "001"
    assert by_code["91340"]["exposure_amount"] == "1,318,000"


def test_i2_same_gl_class_with_different_exposure_is_two_rows():
    """GUARD, inherited verbatim from `_wc_class_dedup_keys`' own reasoning:
    one class code at two locations with DIFFERENT exposures is two real rows,
    and folding them would keep only the first exposure."""
    rows = [
        {"location": "001", "class_code": "91340", "exposure_amount": "500,000", "territory": "008"},
        {"location": "002", "class_code": "91340", "exposure_amount": "250,000", "territory": "008"},
    ]
    assert len(_dedupe("gl_class_code_schedule", rows)) == 2


def test_i2_gl_hazard_row_missing_any_key_part_is_never_merged():
    """GUARD. A row with no exposure (or no territory) gets NO key, exactly as
    a WC row missing its payroll does."""
    rows = [
        {"location": "001", "class_code": "91340", "territory": "008"},
        {"location": "001", "class_code": "91340", "territory": "008"},
    ]
    assert len(_dedupe("gl_class_code_schedule", rows)) == 2


def test_i2_policy_number_is_not_a_generic_natural_identifier():
    """ANTI-ROT. `policy_number` must never be added to `_NATURAL_ID_SUBKEYS`:
    one policy carries many coverage parts, so merging on it DELETES real
    lines. Measured on session 7d95a6e6. If a future change adds it, this
    fails and the reader is sent to the comment that explains why."""
    from services.extraction_service import _NATURAL_ID_SUBKEYS
    for banned in ("policy_number", "policy_no", "claim_date"):
        assert banned not in _NATURAL_ID_SUBKEYS, (
            f"{banned!r} is not unique to one real-world entity - see the "
            "comment on _NATURAL_ID_SUBKEYS")


def test_i2_claim_number_survives_identifier_normalisation():
    """The generic key path strips spaces/hyphens/dots and requires >= 6 chars.
    A real claim number must clear that bar - checked directly rather than
    assumed, because a shorter scheme would silently stop de-duplicating."""
    from services.extraction_service import _natural_id_keys
    keys = _natural_id_keys({"claim_number": "GL-2025-30712"})
    assert any("30712" in k for k in keys), keys
    # ...and a stub too short to be an identifier produces NO key at all
    assert _natural_id_keys({"claim_number": "12"}) == []


# ═════════════════════════════════════════════════════════════════════════════
# I5 - a comma-free US address must still split
# ═════════════════════════════════════════════════════════════════════════════
# Dec pages routinely print the whole address as one comma-free run. Before the
# fix the unit designator stayed inside line 1 and, with no unit to anchor on,
# the CITY was lost entirely.
_ADDRESS_CASES = [
    # (raw, line1, line2, city, state, zip)
    ("1188 Larimer Crossing Ste 400 Denver CO 80204",
     "1188 Larimer Crossing", "Ste 400", "Denver", "CO", "80204"),
    ("3390 E Overland Rd Unit B Aurora CO 80011",
     "3390 E Overland Rd", "Unit B", "Aurora", "CO", "80011"),
    ("704 N Weber St Unit 12 Colorado Springs CO 80903",
     "704 N Weber St", "Unit 12", "Colorado Springs", "CO", "80903"),
    # NO unit designator - this is the shape that lost its city entirely
    ("15 Foothills Service Rd Golden CO 80401",
     "15 Foothills Service Rd", "", "Golden", "CO", "80401"),
    ("2201 S Yuma Frontage Rd Pueblo CO 81004",
     "2201 S Yuma Frontage Rd", "", "Pueblo", "CO", "81004"),
    ("9420 E Costilla Ave Bldg 3 Greenwood Village CO 80112",
     "9420 E Costilla Ave", "Bldg 3", "Greenwood Village", "CO", "80112"),
    # adversarial: a street NAMED like a city, and a city containing a
    # street-suffix word. Both must split on the LAST suffix, not the first.
    ("100 Golden Rd Denver CO 80204", "100 Golden Rd", "", "Denver", "CO", "80204"),
    ("77 Park Ave Court Denver CO 80204", "77 Park Ave Court", "", "Denver", "CO", "80204"),
    ("12 Main St Grand Junction CO 81501",
     "12 Main St", "", "Grand Junction", "CO", "81501"),
    # the 2026-08-12 live shape, kept as a regression pin
    ("4800 DAHLIA ST # D13 DENVER CO 80216-3121",
     "4800 DAHLIA ST", "# D13", "DENVER", "CO", "80216-3121"),
]


@pytest.mark.parametrize("raw,line1,line2,city,state,zipc", _ADDRESS_CASES)
def test_i5_comma_free_address_splits(raw, line1, line2, city, state, zipc):
    from utils.helpers import _parse_address
    got = _parse_address(raw)
    assert got.get("line1") == line1, got
    assert (got.get("line2") or "") == line2, got
    assert got.get("city") == city, got
    assert got.get("state") == state, got
    assert got.get("zip") == zipc, got


def test_i5_no_house_number_means_no_guess():
    """GUARD. A PO box or a bare name has no street/city boundary we can
    establish, so nothing is invented - the same positive-evidence rule the
    rest of the address code follows."""
    from utils.helpers import _parse_address
    got = _parse_address("PO Box 4417 Cheyenne WY 82003")
    assert got.get("city") in (None, "", "Cheyenne")
    assert not (got.get("line2") or "")


def test_i5_ordinary_comma_addresses_are_unchanged():
    """GUARD. The comma-separated forms are the common case and must behave
    exactly as before - this fix only ever acts where commas are absent."""
    from utils.helpers import _parse_address
    a = _parse_address("4820 Prospect Ave, Suite 210, Kansas City, MO 64130")
    assert a["line1"] == "4820 Prospect Ave"
    assert a["line2"] == "Suite 210"
    assert a["city"] == "Kansas City"
    assert a["state"] == "MO" and a["zip"] == "64130"

    b = _parse_address("123 Main St, Littleton, CO 80127")
    assert b["line1"] == "123 Main St"
    assert b["city"] == "Littleton"
    assert b["state"] == "CO" and b["zip"] == "80127"
    assert not b.get("line2")


def test_i5_empty_and_junk_never_raise():
    from utils.helpers import _parse_address
    assert _parse_address("") == {}
    assert isinstance(_parse_address("   "), dict)
    assert isinstance(_parse_address("not an address at all"), dict)


# ── I5's blast radius: the premises grouping key ─────────────────────────────
# `_consolidate_property_locations` groups premises on
# `normalize_address(line1)`. Moving the unit designator OUT of line1 would have
# made two suites in ONE building collapse to a single key and a single ACORD
# 125 premises row - DELETING a real location. C48's own comment relies on the
# unit being present: "Two different suites diverge before the tail ... so they
# never fold." The key therefore has to span line1 AND line2.
def test_i5_grouping_key_is_stable_wherever_the_unit_sits():
    """The key must be byte-identical whether the unit is inside line1 (the
    pre-fix parse) or split into line2 (the post-fix parse). If it is not,
    every legacy session regroups its premises on the next recompute."""
    from services.normalization import normalize_address

    def key(line1, line2=""):
        return normalize_address(f"{line1} {line2}".strip())

    assert key("4800 DAHLIA ST # D13") == key("4800 DAHLIA ST", "# D13")
    assert key("1188 Larimer Crossing Ste 400") == key("1188 Larimer Crossing", "Ste 400")


def test_i5_two_suites_in_one_building_stay_two_premises():
    """GUARD, and the reason the grouping key had to change with the parser:
    Suite 400 and Suite 900 at one street address are two premises rows, and
    folding them would silently drop one from ACORD 125."""
    from services.normalization import normalize_address

    def key(line1, line2=""):
        return normalize_address(f"{line1} {line2}".strip())

    assert key("1188 Larimer Crossing", "Ste 400") != key("1188 Larimer Crossing", "Ste 900")


def test_i5_consolidation_keeps_two_suites_apart_end_to_end():
    """The seam, not the function: drive the real consolidator. An offline
    probe of `normalize_address` proves the key; only this proves the caller."""
    from services.extraction_service import _consolidate_property_locations
    facts = {"property_locations": [
        {"address": "1188 Larimer Crossing Ste 400 Denver CO 80204", "county": "Denver"},
        {"address": "1188 Larimer Crossing Ste 900 Denver CO 80204", "county": "Denver"},
    ]}
    _consolidate_property_locations(facts)
    assert len(facts["property_locations"]) == 2, facts["property_locations"]


# ── I5's blast radius, round 2: TWO MORE doors keyed on line1 alone ──────────
# Found by an adversarial review AFTER the first fix shipped and the full suite
# was green. Both are the same class as the grouping key, and neither was caught
# by any existing test. The lesson is in the shape: moving a value between two
# fields breaks every comparator that reads only one of them, and there were
# THREE such comparators, not one.
def test_i5_the_location_schedule_carries_the_unit_designator():
    """REGRESSION (data loss). `rows_from_facts` rebuilds each row from the
    COLUMNS alone and `arq_service` writes it back over `facts[list_key]`
    wholesale. A sub-field with no column is destroyed the first time anyone
    opens the location table - so with the unit now on line two, omitting the
    column would delete every suite number in the file."""
    import services.schedule_capture as sc
    defn = sc.SCHEDULE_DEFS["property_locations"]        # a dict subclass
    cols = [c["key"] if isinstance(c, dict) else c.key for c in defn["columns"]]
    assert "address_line2" in cols, cols
    assert "address_line2" in defn["dedup_keys"], defn["dedup_keys"]


def test_i5_two_suites_survive_the_location_schedule_round_trip():
    """The seam: consolidate -> render for the human -> save back. The suite
    must still be there, and the two premises must not read as duplicates."""
    from services.extraction_service import _consolidate_property_locations
    import services.schedule_capture as sc
    facts = {"property_locations": [
        {"address": "4800 Dahlia St Ste 100 Denver CO 80216"},
        {"address": "4800 Dahlia St Ste 200 Denver CO 80216"},
    ]}
    _consolidate_property_locations(facts)
    rows = sc.rows_from_facts("property_locations", facts)
    assert len(rows) == 2 and rows[0] != rows[1], rows
    assert [r["address_line2"] for r in rows] == ["Ste 100", "Ste 200"]
    _rows, meta = sc.validate_rows("property_locations", rows)
    assert meta["duplicates"] == [], "the client is told two real premises are one"
    back = sc.rows_for_facts("property_locations", rows)
    assert [r.get("address_line2") for r in back] == ["Ste 100", "Ste 200"], back


def test_i5_a_premises_in_the_producers_building_is_not_dropped():
    """REGRESSION (silent deletion). `_is_location_entry` compares the entry's
    street against the producer's. With the unit lifted off line1, the agency's
    Suite 400 and the INSURED's Suite 100 in the same building reduced to one
    key and the insured's real premises was deleted. Measured: 2 in, 1 out."""
    from services.extraction_service import _consolidate_property_locations
    facts = {
        "producer_address": "9780 S Meridian Blvd Ste 400, Englewood, CO 80112",
        "property_locations": [
            {"address": "9780 S Meridian Blvd Ste 100 Englewood"},
            {"address": "123 Main St Denver CO 80204"},
        ],
    }
    _consolidate_property_locations(facts)
    streets = [(r.get("address_line1"), r.get("address_line2"))
               for r in facts["property_locations"]]
    assert len(facts["property_locations"]) == 2, streets
    assert ("9780 S Meridian Blvd", "Ste 100") in streets, streets


def test_i5_the_producers_own_office_is_still_dropped():
    """GUARD, the other direction (live 2026-08-12): the agency's own address
    swept into the premises list printed as 'LOC # 4' on the client's form. It
    must still be removed - same building AND same unit is the producer."""
    from services.extraction_service import _consolidate_property_locations
    facts = {
        "producer_address": "9780 S Meridian Blvd Ste 400, Englewood, CO 80112",
        "property_locations": [
            {"address": "9780 S Meridian Blvd Ste 400, Englewood, CO 80112"},
            {"address": "123 Main St Denver CO 80204"},
        ],
    }
    _consolidate_property_locations(facts)
    streets = [str(r.get("address_line1") or "") for r in facts["property_locations"]]
    assert not any("Meridian" in s for s in streets), streets


# ═════════════════════════════════════════════════════════════════════════════
# I1 + I3 - a premium the dec page PRINTS is a transcription, not a computation
# ═════════════════════════════════════════════════════════════════════════════
# `_is_nonfillable_field` blanks anything named *Premium* / *Rate* BEFORE any
# deterministic resolution runs. That is right for a figure the model would
# invent and wrong for one the declarations page states under its own label.
#
# THE GATE IS NOT TOUCHED. This is a third carve-out inside `map_facts_to_form`,
# exactly like the two already there (prior-coverage premium, `_is_lob_premium_
# field`), so `compute_form_gaps` still refuses and the gap-fill LLM is still
# never asked for a premium. The asymmetry is deliberate and documented in
# `improving-ll.md`: "the deterministic path was unblocked in map_facts_to_form
# only". The three adversarial tests below are the ones a blast-radius trace
# said must never break; they are written first, per the H1-F standing lesson.
_DEC_ENTRIES = [
    {"label": "AUTOMOBILE PREMIUM", "value": "$32,170",
     "line_of_business": "Commercial Auto", "owner": "policy"},
    {"label": "AUTO COMBINED SINGLE LIMIT PREMIUM", "value": "$18,240",
     "line_of_business": "Commercial Auto", "owner": "policy"},
    {"label": "GL PREMISES/OPERATIONS PREMIUM", "value": "$46,900",
     "line_of_business": "General Liability", "owner": "policy"},
    {"label": "GL PRODUCTS/COMPLETED OPERATIONS PREMIUM", "value": "$14,555",
     "line_of_business": "General Liability", "owner": "policy"},
    {"label": "EMPLOYERS LIABILITY PREMIUM", "value": "$71,410",
     "line_of_business": "Workers Compensation", "owner": "policy"},
    {"label": "EMPLOYERS LIABILITY MODIFICATION FACTOR", "value": "0.94",
     "line_of_business": "Workers Compensation", "owner": "policy"},
    {"label": "EXCESS LIABILITY PREMIUM", "value": "$23,900",
     "line_of_business": "Commercial Umbrella", "owner": "policy"},
]


def _schema(form_id):
    import json as _json
    from pathlib import Path as _Path
    raw = _json.loads((_Path(__file__).resolve().parents[1] / "forms_schemas" /
                       f"{form_id}_schema.json").read_text(encoding="utf-8"))
    return raw["fields"] if isinstance(raw, dict) and "fields" in raw else raw


def _map131(facts):
    from services.pdf_service import map_facts_to_form
    out = map_facts_to_form(dict(facts), _schema("ACORD_131"), "ACORD_131", raw_text="")
    return out[0] if isinstance(out, tuple) else out


# ── ADVERSARIAL 1: the form must never sign itself ───────────────────────────
def test_i1_the_form_still_does_not_sign_itself():
    """The single most dangerous thing a change here can do. 16 of 17 forms have
    a Pass-1 rule (`producer_contact_name`) that WOULD claim a Signature box -
    `_deterministic_map` returns 'JANE DOE' for it - and only this gate stops
    it. Client report #20 was an auto-signed application."""
    from services.pdf_service import map_facts_to_form
    facts = {"producer_contact_name": "JANE DOE", "producer_name": "Acme Brokers"}
    for form_id in ("ACORD_125", "ACORD_131", "ACORD_126"):
        schema = _schema(form_id)
        out = map_facts_to_form(dict(facts), schema, form_id, raw_text="")
        mapped = out[0] if isinstance(out, tuple) else out
        for field in schema:
            if "Signature" in field or "_Sig" in field or "_Initials" in field:
                assert not str(mapped.get(field) or "").strip(), \
                    f"{form_id}/{field} was signed by the machine"


# ── ADVERSARIAL 2: agency identifiers must never reach the model ─────────────
def test_i1_group_a_identifiers_never_reach_the_gap_fill_model():
    """Of the fields this gate blocks, one group must stay blank HOWEVER WELL
    EVIDENCED - signatures, initials, attestations, licence numbers, agency
    codes. The state-licence bug proves grounding is not the discriminator:
    the wrong value WAS printed on the dec page ("Agent Number"). Audience is."""
    from services.pdf_service import compute_form_gaps
    from pathlib import Path
    import json as _json
    group_a = ("Signature", "_Sig", "_Initials", "InformationPracticesNotice",
               "StateLicense", "Producer_NationalIdentifier", "CustomerIdentifier")
    leaked = []
    for p in sorted((Path(__file__).resolve().parents[1] / "forms_schemas")
                    .glob("ACORD_*_schema.json")):
        form_id = p.name.replace("_schema.json", "")
        raw = _json.loads(p.read_text(encoding="utf-8"))
        schema = raw["fields"] if isinstance(raw, dict) and "fields" in raw else raw
        _m, unmatched, _d = compute_form_gaps(form_id, schema,
                                              {"dec_page_entries": _DEC_ENTRIES})
        leaked += [f"{form_id}/{f}" for f in unmatched
                   if any(g in f for g in group_a)]
    assert not leaked, leaked[:12]


# ── ADVERSARIAL 3: the LOB premium column must not go dark ───────────────────
def test_i1_lob_premium_column_still_fills():
    """`_resolve_lob_premium` is called from exactly ONE place - inside the
    non-fillable branch of `map_facts_to_form`. Break that branch and the 15
    ACORD 125 line-of-business premium boxes lose their only filler and ship
    permanently blank: the client-reported defect fixed on 2026-08-09."""
    from services.pdf_service import map_facts_to_form
    facts = {"coverage_lines": [
        {"line": "General Liability", "premium": "$3,954"},
        {"line": "Commercial Auto", "premium": "$2,991"},
    ]}
    raw = ("COMMERCIAL GENERAL LIABILITY PREMIUM $3,954  "
           "COMMERCIAL AUTOMOBILE PREMIUM $2,991")
    out = map_facts_to_form(dict(facts), _schema("ACORD_125"), "ACORD_125", raw_text=raw)
    mapped = out[0] if isinstance(out, tuple) else out
    stamped = {v for v in mapped.values() if v}
    assert "3,954" in {_amt(v) for v in stamped}, "the GL line premium box went dark"


# ── ADVERSARIAL 4: the gap-fill LLM is still never asked for a premium ───────
def test_i1_compute_form_gaps_still_refuses_every_premium():
    """The documented asymmetry. `compute_form_gaps` feeds the gap-fill union;
    if a blocked box enters it, the model is asked to invent a rating figure.

    The invariant is stated against the PREDICATE, not against the substring
    "Premium". `GeneralLiability_Hazard_PremiumBasisCode_*` contains it and is
    deliberately allow-listed - the premium BASIS ("(p) Payroll") is a data
    column a broker fills, not a carrier computation. Asserting on the
    substring failed here before any change, which is exactly what a guard
    test is for."""
    from services.pdf_service import compute_form_gaps, _is_nonfillable_field
    for form_id in ("ACORD_125", "ACORD_126", "ACORD_131", "ACORD_130"):
        _m, unmatched, _d = compute_form_gaps(
            form_id, _schema(form_id), {"dec_page_entries": _DEC_ENTRIES})
        bad = [f for f in unmatched if _is_nonfillable_field(f)]
        assert not bad, f"{form_id}: {bad[:6]}"


# ── THE FIX ITSELF ───────────────────────────────────────────────────────────
def test_i1_underlying_premiums_stamp_from_the_dec_index():
    """DEFECT. Every one of these is printed on the dec page under its own
    label and was shipping blank because the field name contains 'Premium'."""
    mapped = _map131({"dec_page_entries": _DEC_ENTRIES})
    assert _amt(mapped.get("UnderlyingPolicy_GeneralLiability_PremisesOperationsPremiumAmount_A")) == "46,900"
    assert _amt(mapped.get("UnderlyingPolicy_GeneralLiability_ProductsPremiumAmount_A")) == "14,555"
    assert _amt(mapped.get("UnderlyingPolicy_Automobile_CombinedSingleLimitPremiumAmount_A")) == "18,240"
    assert _amt(mapped.get("UnderlyingPolicy_EmployersLiability_PremiumAmount_A")) == "71,410"


def test_i1_the_rating_mod_box_fills_by_owner_decision_not_by_accident():
    """SUPERSEDED PIN, 2 Sep 2026. This test used to freeze the MOD box blank
    so it could not start filling BY ACCIDENT. The owner then approved the
    transcription explicitly ("works, and i dont want this to be hardcoded"),
    the adversarial stress test hardened the rule (see the M1 suite - the
    "SEE ITEM 4"/"$500"/ARAP/increased-limits/date cases all stay refused, one
    entry can never stamp two boxes), and the read shipped inside the row's one
    owner. The pin now points the other way: the dec index printing the line's
    own factor under a leftover-free label MUST stamp, and the M1 suite is what
    keeps that from ever widening back into the junk the old ruling recorded."""
    mapped = _map131({"dec_page_entries": _DEC_ENTRIES + [
        {"label": "EMPLOYERS LIABILITY MODIFICATION FACTOR", "value": "0.94",
         "line_of_business": "Employers Liability", "owner": "policy",
         "section": "SCHEDULE OF UNDERLYING INSURANCE"}]})
    assert mapped.get(
        "UnderlyingPolicy_EmployersLiability_ModificationFactor_A") == "0.94"


def test_i1_a_label_from_another_line_never_fills_the_box():
    """GUARD. The auto line prints TWO premiums - the whole-line 'AUTOMOBILE
    PREMIUM' ($32,170) and the CSL premium ($18,240). The CSL box must take the
    CSL figure, and the umbrella's own premium must reach neither."""
    mapped = _map131({"dec_page_entries": _DEC_ENTRIES})
    csl = mapped.get("UnderlyingPolicy_Automobile_CombinedSingleLimitPremiumAmount_A")
    assert _amt(csl) == "18,240", csl
    assert csl != "$32,170" and csl != "$23,900"


def test_i1_no_dec_entry_means_the_box_stays_blank():
    """GUARD, positive evidence only. With nothing printed, nothing is stamped -
    the box behaves exactly as it does today."""
    mapped = _map131({"dec_page_entries": []})
    for f in ("UnderlyingPolicy_GeneralLiability_PremisesOperationsPremiumAmount_A",
              "UnderlyingPolicy_EmployersLiability_PremiumAmount_A",
              "UnderlyingPolicy_EmployersLiability_ModificationFactor_A"):
        assert not str(mapped.get(f) or "").strip(), (f, mapped.get(f))


def test_i1_two_matching_labels_are_ambiguous_and_stamp_nothing():
    """GUARD. Two dec rows that both answer one box is a conflict, not a
    ranking - the same rule the underlying-policy grid already applies."""
    entries = [
        {"label": "EMPLOYERS LIABILITY PREMIUM", "value": "$71,410",
         "line_of_business": "Workers Compensation", "owner": "policy"},
        {"label": "EMPLOYERS LIABILITY PREMIUM", "value": "$99,999",
         "line_of_business": "Workers Compensation", "owner": "policy"},
    ]
    mapped = _map131({"dec_page_entries": entries})
    assert not str(
        mapped.get("UnderlyingPolicy_EmployersLiability_PremiumAmount_A") or "").strip()


def test_i1_a_multi_row_column_never_takes_a_policy_level_value():
    """GUARD, and the reason the rule is scoped to single-row fields. A dec
    index is policy-level and has no row concept, so it cannot say WHICH row of
    a repeating grid a figure belongs to. `UnderlyingPolicy_OtherPolicy_*` has
    rows A and B, so it is out of scope even though a matching label exists."""
    from services.pdf_service import map_facts_to_form
    entries = _DEC_ENTRIES + [
        {"label": "OTHER POLICY PREMIUM", "value": "$4,860",
         "line_of_business": "Contractors Pollution", "owner": "policy"}]
    mapped = _map131({"dec_page_entries": entries})
    assert not str(
        mapped.get("UnderlyingPolicy_OtherPolicy_PremiumAmount_A") or "").strip()


def test_i5_one_premises_mentioned_two_ways_still_folds_to_one():
    """GUARD (C48, live 2026-08-12): the SAME premises printed comma-free in
    several shapes must still collapse to ONE row, not three."""
    from services.extraction_service import _consolidate_property_locations
    facts = {"property_locations": [
        {"address": "4800 Dahlia St # D13 Denver"},
        {"address": "4800 Dahlia St # D13 Denver CO 80216"},
        {"address": "Denver CO 80216"},
    ]}
    _consolidate_property_locations(facts)
    assert len(facts["property_locations"]) == 1, facts["property_locations"]


# =============================================================================
# I6 - a printed grid must be asked row-by-row, not column-by-column
# =============================================================================
# `_table_prefix` bucketed columns by the first TWO name segments, and ACORD
# names most columns `Root_Column` - exactly two - so each became a bucket of
# one, never reached the 3-column bar, and fell through to `_slot_group_block`
# ("find N values in the order they appear"), which has no concept of a row.
#
# The live run's evidence, verbatim: the named-insured phone column slid one row
# down (row A got the CONTACT's phone, B got A's, C got B's) and row C's SIC and
# NAICS came from insured B - while `NamedInsured_MailingAddress`, which DID
# reach 3 columns and was row-framed, came back 100% correct on the same run.

_I6_NAMED_INSURED_COLUMNS = [
    "NamedInsured_SICCode",
    "NamedInsured_NAICSCode",
    "NamedInsured_Primary_PhoneNumber",
    "NamedInsured_TaxIdentifier",
    "NamedInsured_GeneralLiabilityCode",
]


def _acord_schema(form_id: str) -> dict:
    import json
    path = os.path.join(os.path.dirname(__file__), "..", "forms_schemas",
                        f"{form_id}_schema.json")
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def _capture_gap_fill_prompt(unmatched: dict, form_id: str,
                             already_filled: dict | None = None,
                             raw_text: str = "Named Insured: Verdant Slope LLC") -> str:
    """Drive the REAL `_fill_unmatched_with_gpt` and return every user prompt.

    Rule 4 of `1sep-form-filling-increase.md`: an offline probe proves the
    function, never the seam. The bucketing, the batching and the rendering all
    have to agree for a table to arrive whole in one call, so the assertion has
    to be made against the bytes that would go to OpenAI.
    """
    import json
    from unittest.mock import MagicMock, patch
    import services.pdf_service as ps

    captured = []

    def _create(**kwargs):
        captured.append(kwargs.get("messages"))
        resp = MagicMock()
        resp.choices = [MagicMock()]
        resp.choices[0].message.content = json.dumps(
            {"values": {}, "raw_text_sourced": []})
        return resp

    client = MagicMock()
    client.chat.completions.create = MagicMock(side_effect=_create)
    with patch.object(ps, "_get_openai_form_fill_client_sync", return_value=client):
        ps._fill_unmatched_with_gpt(
            unmatched, facts={}, form_id=form_id, raw_text=raw_text,
            already_filled=already_filled or {},
        )
    assert captured, "no LLM call was made at all"
    return "\n".join(m[1]["content"] for m in captured if len(m) > 1)


def _unmatched_from(form_id: str, bases, rows="ABC") -> dict:
    schema = _acord_schema(form_id)
    out = {}
    for base in bases:
        for row in rows:
            key = f"{base}_{row}"
            if key in schema:
                out[key] = schema[key]
    assert out, f"schema drifted - none of {bases} exist on {form_id}"
    return out


def test_i6_named_insured_columns_are_asked_as_one_table():
    """DEFECT. The five orphan named-insured columns must arrive as ONE
    row-oriented table block, not five independent 'find N values' searches."""
    fields = _unmatched_from("ACORD_125", _I6_NAMED_INSURED_COLUMNS)
    prompt = _capture_gap_fill_prompt(fields, "ACORD_125")
    assert "TABLE 'NamedInsured#ABC'" in prompt, prompt[:2000]
    for base in _I6_NAMED_INSURED_COLUMNS:
        assert f"REPEATING GROUP '{base}'" not in prompt, (
            f"{base} is still asked column-wise - I6 did not take effect")


def test_i6_the_products_grid_is_asked_as_one_table():
    """DEFECT (this is also I8's root cause). Every ACORD 126 products column is
    a two-segment name, so all seven were independent searches - which is how
    three years of revenue became three product rows on the live run."""
    bases = [
        "ProductAndCompletedOperations_ProductName",
        "ProductAndCompletedOperations_AnnualGrossSalesAmount",
        "ProductAndCompletedOperations_UnitCount",
        "ProductAndCompletedOperations_InMarketMonthCount",
        "ProductAndCompletedOperations_ExpectedLifeMonthCount",
        "ProductAndCompletedOperations_IntendedUse",
        "ProductAndCompletedOperations_PrincipalComponents",
    ]
    prompt = _capture_gap_fill_prompt(_unmatched_from("ACORD_126", bases), "ACORD_126")
    assert "TABLE 'ProductAndCompletedOperations#ABC'" in prompt


def test_i6_a_table_names_its_own_schedule_and_disowns_the_others():
    """DEFECT (part 2). A framed table still slid a value in from a DIFFERENT
    schedule, because the row block said 'one distinct real-world entry' without
    ever saying one entry OF WHAT.

    Uses two genuinely different schedules (named insureds vs the building
    occupancy grid - the loss run cannot serve, it is schedule-BOUND and never
    reaches gap fill at all). The original version used the named-insured
    ADDRESS columns as the second table - and the run-4 TABLE_JOIN fix now
    correctly merges those into ONE named-insured table, pinned separately
    below."""
    fields = _unmatched_from("ACORD_125", _I6_NAMED_INSURED_COLUMNS)
    fields.update(_unmatched_from("ACORD_125", [
        "PriorCoverage_GeneralLiability_InsurerFullName",
        "PriorCoverage_GeneralLiability_PolicyNumberIdentifier",
        "PriorCoverage_GeneralLiability_EffectiveDate",
        "PriorCoverage_GeneralLiability_ExpirationDate",
    ]))
    prompt = _capture_gap_fill_prompt(fields, "ACORD_125")
    assert "This is the Named Insured table." in prompt
    assert "SEPARATE tables" in prompt
    assert "Prior Coverage" in prompt


def test_i6_one_schedule_printed_as_two_buckets_is_asked_as_one_table():
    """DEFECT (run 4, 2 Sep 2026). `NamedInsured_MailingAddress` qualifies as a
    table on its own (rule 1) and the identity columns qualify as orphans
    (rule 2) - one printed schedule asked as TWO tables. Measured live: the
    identity half aligned on all three rows while the address half returned
    nothing for B and C - 12 of ACORD 125's 20 remaining blanks. They must
    arrive as ONE nine-column table."""
    fields = _unmatched_from("ACORD_125", _I6_NAMED_INSURED_COLUMNS)
    fields.update(_unmatched_from("ACORD_125", [
        "NamedInsured_MailingAddress_LineOne",
        "NamedInsured_MailingAddress_CityName",
        "NamedInsured_MailingAddress_PostalCode",
    ]))
    prompt = _capture_gap_fill_prompt(fields, "ACORD_125")
    assert "TABLE 'NamedInsured#ABC'" in prompt
    assert "TABLE 'NamedInsured_MailingAddress'" not in prompt, (
        "the address columns are still their own table - the schedule is split")
    _table = prompt.split("TABLE 'NamedInsured#ABC'", 1)[1].split("RULE:", 1)[0]
    for col in ("LineOne", "CityName", "PostalCode", "SICCode", "PhoneNumber"):
        assert col in _table, f"{col} missing from the merged table"


def test_i6_the_join_never_reaches_across_row_universes():
    """GUARD. The join requires root AND row universe to match - ACORD 127's
    4-row vehicle schedule must never absorb the 2-row Vehicle_Question pair,
    which shares the root but not the rows."""
    fields = _unmatched_from("ACORD_127", [
        "Vehicle_RatingTerritoryCode", "Vehicle_RateClassCode",
        "Vehicle_SpecialIndustryClassCode", "Vehicle_RadiusOfUse",
        "Vehicle_CostNewAmount",
    ], rows="ABCD")
    fields.update(_unmatched_from("ACORD_127", [
        "Vehicle_Question_ModifiedEquipmentDescription",
        "Vehicle_Question_ModifiedEquipmentCostAmount",
    ], rows="AB"))
    prompt = _capture_gap_fill_prompt(fields, "ACORD_127", raw_text="2019 Ford F-250")
    assert "TABLE 'Vehicle#ABCD'" in prompt
    _table = prompt.split("TABLE 'Vehicle#ABCD'", 1)[1].split("RULE:", 1)[0]
    assert "ModifiedEquipment" not in _table


def test_i6_the_row_block_says_a_table_can_be_printed_in_two_places():
    """DEFECT (part 3). The GL hazard grid prints identity+exposure in one block
    and rates+premiums in another, the way a real dec page does; the pipeline
    filled from the first and never joined the second."""
    fields = _unmatched_from("ACORD_125", _I6_NAMED_INSURED_COLUMNS)
    prompt = _capture_gap_fill_prompt(fields, "ACORD_125")
    assert "PRINTED as TWO OR MORE separate blocks" in prompt
    assert "NEVER by its position on the page" in prompt


def test_i6_a_pair_of_columns_is_still_not_a_table():
    """GUARD. `>=3 co-occurring columns` is deliberate - a coincidental PAIR
    sharing a prefix is far more likely to be two unrelated small groups. Two
    orphan columns must NOT be promoted just because they share a root."""
    fields = _unmatched_from("ACORD_125", [
        "NamedInsured_SICCode", "NamedInsured_NAICSCode"])
    prompt = _capture_gap_fill_prompt(fields, "ACORD_125")
    assert "TABLE 'NamedInsured" not in prompt
    assert "REPEATING GROUP 'NamedInsured_SICCode'" in prompt


def test_i6_a_general_information_answer_is_not_swept_into_the_schedule():
    """GUARD, and the reason the orphan key carries the ROW UNIVERSE and not the
    root alone. `Vehicle_Question_ModifiedEquipment*` is a General Information
    answer with rows A/B; the vehicle schedule has rows A-D. Bucketing on the
    root alone put the question INSIDE the schedule, which would tell the model
    row B of the question describes vehicle 2."""
    import services.pdf_service as ps
    fields = _unmatched_from("ACORD_127", [
        # VIN / make / model are schedule-BOUND (Pass 1 owns them), so the
        # columns that actually reach gap fill are the rating ones.
        "Vehicle_RatingTerritoryCode", "Vehicle_RateClassCode",
        "Vehicle_SpecialIndustryClassCode", "Vehicle_RadiusOfUse",
        "Vehicle_CostNewAmount",
    ], rows="ABCD")
    fields.update(_unmatched_from("ACORD_127", [
        "Vehicle_Question_ModifiedEquipmentDescription",
        "Vehicle_Question_ModifiedEquipmentCostAmount",
    ], rows="AB"))
    prompt = _capture_gap_fill_prompt(fields, "ACORD_127", raw_text="2019 Ford F-250")
    assert "TABLE 'Vehicle#ABCD'" in prompt
    _table = prompt.split("TABLE 'Vehicle#ABCD'", 1)[1].split("RULE:", 1)[0]
    assert "ModifiedEquipment" not in _table, (
        "a General Information answer was swept into the vehicle schedule")


def test_i6_two_roles_sharing_one_base_stay_two_groups():
    """GUARD. ACORD reuses `AdditionalInterest_FullName` for the lienholder
    schedule (_A/_B) and 'the other owner of the vehicle' (_C/_D), split only by
    tooltip. The row universe must never be widened across that split - doing so
    would merge the two roles that `repeating_group_key` exists to separate."""
    from services.pdf_service import repeating_group_key
    schema = _acord_schema("ACORD_127")
    tips = {r: (schema.get(f"AdditionalInterest_FullName_{r}") or {}).get("tu", "")
            for r in "ABCD"}
    keys = {repeating_group_key(f"AdditionalInterest_FullName_{r}", tips[r])
            for r in "ABCD"}
    assert len(keys) > 1, ("the tooltip split has gone - the row-universe widening "
                           "in _row_universe is now unguarded")


def test_i6_bucketing_can_only_ever_add_table_framing():
    """ANTI-ROT, over all 17 real schemas. The orphan rule is additive BY
    CONSTRUCTION: rule 1 (the legacy 2-segment prefix) claims first, and rule 2
    only ever picks up what rule 1 left behind. If a future edit lets rule 2 take
    a column away from a qualifying prefix bucket, a table that works today
    silently reshapes - this fails the build instead."""
    import collections
    import glob
    import json
    row_re = re.compile(r"^(.+)_([A-N])$")
    schema_dir = os.path.join(os.path.dirname(__file__), "..", "forms_schemas")
    total_gained = 0
    for path in sorted(glob.glob(os.path.join(schema_dir, "ACORD_*_schema.json"))):
        with open(path, encoding="utf-8") as fh:
            schema = json.load(fh)
        rows = collections.defaultdict(set)
        for name in schema:
            m = row_re.match(name or "")
            if m:
                rows[m.group(1)].add(m.group(2))
        cands = {b: frozenset(r) for b, r in rows.items() if len(r) >= 2}
        legacy = collections.defaultdict(list)
        for base in cands:
            legacy["_".join(base.split("_")[:2])].append(base)
        assign = {}
        for prefix, bs in legacy.items():
            if len(bs) >= 3:
                for base in bs:
                    assign[base] = prefix
        before = set(assign)
        orphan = collections.defaultdict(list)
        for base in cands:
            if base not in assign:
                orphan[(base.split("_")[0], cands[base])].append(base)
        for (root, rw), bs in orphan.items():
            if len(bs) >= 3:
                for base in bs:
                    assign[base] = root + "#" + "".join(sorted(rw))
        assert not (before - set(assign)), (
            f"{os.path.basename(path)}: the orphan rule took columns away from a "
            f"qualifying prefix bucket: {sorted(before - set(assign))}")
        total_gained += len(assign) - len(before)
    assert total_gained >= 200, (
        f"only {total_gained} columns gained row framing - I6 measured 212 across "
        "the 17 schemas; a big drop means the rule stopped firing")


def test_i6_kill_switch_restores_the_previous_bucketing(monkeypatch):
    """GUARD. `TABLE_ROOT_BUCKETS=0` must return the exact pre-I6 behaviour, so
    the change can be reverted in an environment without a deploy.

    The flag is patched on the MODULE, never re-imported. An earlier version of
    this test called `importlib.reload(pdf_service)` and took 16 unrelated tests
    down with it across the full suite: the module defines identity sentinels
    (`_SCHED_SKIP` is a bare `object()`), so a reload leaves every other module
    holding the OLD sentinel while the resolvers return the NEW one, and every
    `is _SCHED_SKIP` comparison in the codebase silently starts returning False.
    Never reload a module inside a test in this suite."""
    import services.pdf_service as ps
    fields = _unmatched_from("ACORD_125", _I6_NAMED_INSURED_COLUMNS)
    monkeypatch.setattr(ps, "_TABLE_ROOT_BUCKETS", False, raising=False)
    prompt = _capture_gap_fill_prompt(fields, "ACORD_125")
    assert "TABLE 'NamedInsured#ABC'" not in prompt
    assert "REPEATING GROUP 'NamedInsured_SICCode'" in prompt


# =============================================================================
# I7 - an amount box took a figure the document states as something else
# =============================================================================
# Live run: `Contractors_SubcontractorsPaidAmount_A` shipped $1,804,000, the
# applicant's total PAYROLL. `_enforce_numeric_meaning_gate` exists to catch
# exactly that and stood aside, because the payroll is a plain scalar fact and
# the gate only ever consulted dec-page entries, the GL schedule, coverage lines
# and three hard-coded fact keys.
_I7_FACTS = {
    "payroll": "$1,804,000",
    "total_revenue": "$9,410,000",
    "subcontract_cost": "$2,145,000",
    "gl_class_code_schedule": [
        {"class_code": "91340", "premium_basis": "(p) Payroll",
         "exposure_amount": "1,318,000", "territory": "008"},
        {"class_code": "91580", "premium_basis": "(c) Total Cost",
         "exposure_amount": "2,145,000", "territory": "008"},
    ],
}


def _gate(field, value, form_id="ACORD_126", facts=None):
    from services.pdf_service import _enforce_numeric_meaning_gate
    schema = _acord_schema(form_id)
    assert field in schema, f"schema drifted - {field} is not on {form_id}"
    mapped = {field: value}
    _enforce_numeric_meaning_gate(mapped, schema, facts or _I7_FACTS, {field})
    return mapped[field]


def test_i7_the_payroll_cannot_stamp_as_subcontractors_paid():
    """DEFECT, the live value. The field classifies as a COST figure and the
    document states $1,804,000 as PAYROLL - a cross-category borrow."""
    assert _gate("Contractors_SubcontractorsPaidAmount_A", "$1,804,000") is None


def test_i7_the_real_subcontract_cost_still_stamps():
    """GUARD, and the half that matters. Blanking the wrong figure is worth
    nothing if it also blanks the right one: $2,145,000 is witnessed as a COST
    twice over (the `subcontract_cost` fact and the GL row whose premium basis
    is Total Cost), so it must survive."""
    assert _gate("Contractors_SubcontractorsPaidAmount_A", "$2,145,000") == "$2,145,000"


def test_i7_revenue_still_stamps_in_a_sales_box():
    """GUARD. Every new witness can only ever cause MORE blanking, so the
    ordinary case has to be pinned: the revenue fact in a gross-sales box is a
    category MATCH and must be untouched."""
    assert _gate("BusinessInformation_AnnualGrossReceiptsAmount_A", "$9,410,000",
                 form_id="ACORD_131") == "$9,410,000"


def test_i7_a_composite_fact_never_becomes_a_witness():
    """GUARD. `gl_limits` reads "each occurrence $1,000,000; aggregate
    $2,000,000". Stripping its non-digits yields one nonsense figure - the exact
    `_currency_magnitude` mistake C23 was written for - so a value that is not
    ONE amount end to end must never be registered."""
    from services.pdf_service import _build_amount_witnesses
    w = _build_amount_witnesses({
        "gl_limits": "each occurrence limit $1,000,000; aggregate $2,000,000"})
    assert not any(v for v in w.values()), w


def test_i7_a_sentence_is_not_an_amount():
    """DEFECT. `BusinessInformation_ForeignGrossSalesAmount_A` shipped the prose
    "no foreign gross sales" in a money box."""
    assert _gate("BusinessInformation_ForeignGrossSalesAmount_A",
                 "no foreign gross sales", form_id="ACORD_131") is None


@pytest.mark.parametrize("kept", ["Included", "Statutory", "None", "Not applicable"])
def test_i7_acords_own_wordless_amounts_survive(kept):
    """GUARD. An amount box legitimately holds these; the rule needs three words
    AND a negation cue AND no digit, so all four are below the bar."""
    assert _gate("BusinessInformation_ForeignGrossSalesAmount_A", kept,
                 form_id="ACORD_131") == kept


# =============================================================================
# I8 - a grid the applicant does not have was fabricated whole
# =============================================================================
def test_i8_the_table_block_says_an_empty_table_is_a_valid_answer():
    """DEFECT (the prompt half - the framing half is I6). The row block told the
    model what to do with FEWER entries than rows and never what to do with
    NONE, and the live document says 'The applicant manufactures no products.'
    """
    bases = [
        "ProductAndCompletedOperations_ProductName",
        "ProductAndCompletedOperations_AnnualGrossSalesAmount",
        "ProductAndCompletedOperations_UnitCount",
        "ProductAndCompletedOperations_IntendedUse",
    ]
    prompt = _capture_gap_fill_prompt(_unmatched_from("ACORD_126", bases), "ACORD_126")
    assert "return NOTHING for this table" in prompt
    assert "An empty table is the correct answer" in prompt


# =============================================================================
# I10 - an endorsement TITLE grounded a fabricated "Yes"
# =============================================================================
# Two runs of the identical document disagreed on three ACORD 126 questions. The
# fabricated one - "is vendors coverage required?" - was grounded on
# "CG 20 10 12 19 Additional Insured - Owners, Lessees Or Contractors", a line
# off the forms-and-endorsements schedule. The document never mentions vendors
# coverage.
_I10_FORM_CITATIONS = [
    "CG 20 10 12 19 Additional Insured - Owners, Lessees Or Contractors",
    "CG 00 01 04 13 Commercial General Liability Coverage Form",
    "IL 00 17 11 98 Common Policy Conditions",
    "CA 00 01 10 13 Business Auto Coverage Form",
]
# Every one of these is either a real affirmative quote from a past live run or
# a sentence a previous session measured as WRONGLY blanked. None may be lost.
_I10_REAL_QUOTES = [
    "Crime Coverage Policy No. BBC7263",
    "Subcontractors are required to carry coverage.",
    "The applicant does not have any subsidiaries.",
    "Date of Issue: 07/16/2025",
    "Blanket Primary and Noncontributory Additional Insured",
    "the applicant had a molestation claim in 2023; CG 21 46 was added at renewal",
    "Payroll = $210,000",
    "",
]


@pytest.mark.parametrize("quote", _I10_FORM_CITATIONS)
def test_i10_a_leading_form_number_is_a_citation_not_evidence(quote):
    from services.pdf_service import _quote_is_a_form_citation
    assert _quote_is_a_form_citation(quote) is True


@pytest.mark.parametrize("quote", _I10_REAL_QUOTES)
def test_i10_a_real_quote_is_never_a_form_citation(quote):
    """GUARD. Anchored at the START on purpose - a real Yes may MENTION a form
    ("...; CG 21 46 was added at renewal") and must survive. Two broader rules
    for this shape were already built and rejected by measurement (see the
    ACORD 127 Q8 block in pdf_service); this one judges only the printed form
    NUMBER, which no applicant statement carries."""
    from services.pdf_service import _quote_is_a_form_citation
    assert _quote_is_a_form_citation(quote) is False


def test_i10_the_gate_only_rejects_a_citation_on_the_yes_side():
    """GUARD. Same asymmetry as the exclusion-title rule: over-firing on the
    "No" side deletes correct answers with no fallback, so the citation check
    must be reachable only when `negative` is False."""
    import inspect
    from services import pdf_service
    src = inspect.getsource(pdf_service.map_facts_to_form)
    assert "not negative and _quote_is_a_form_citation(quote)" in src, (
        "the form-citation gate is no longer Y-only")


# =============================================================================
# 3b - the hazard grid's two ROW-LABEL columns were switched off by name
# =============================================================================
# `GeneralLiability_Hazard_LocationProducerIdentifier` (LOC #) and
# `..._HazardProducerIdentifier` (HAZ #) were blocked by the broad
# "ProducerIdentifier" substring in `_is_nonfillable_field`, which exists for
# AGENCY-assigned codes. Neither is one: ACORD's own tooltips read "the location
# number of the risk's location" and "a unique (within location) number
# distinguishing this unit-at-risk from the others". The identical carve-out was
# already made for `CommercialStructure_Location_ProducerIdentifier_` one form
# over. LOC # is a fact the schedule has always carried and nothing read; HAZ #
# is derived from ACORD's own definition.
_T1_HAZARDS = [
    {"location": "001", "class_code": "91340", "premium_basis": "(p) Payroll",
     "classification": "Carpentry - construction of residential property not "
                       "exceeding three stories",
     "exposure_amount": "1,318,000", "territory": "008"},
    {"location": "002", "class_code": "91580", "premium_basis": "(c) Total Cost",
     "classification": "Contractors - subcontracted work - in connection with "
                       "construction",
     "exposure_amount": "2,145,000", "territory": "008"},
    {"location": "004", "class_code": "92478", "premium_basis": "(p) Payroll",
     "classification": "Roofing - all kinds",
     "exposure_amount": "486,000", "territory": "008"},
]


def _map126(rows):
    from services.pdf_service import map_facts_to_form
    res = map_facts_to_form({"gl_class_code_schedule": rows},
                            _acord_schema("ACORD_126"), form_id="ACORD_126")
    return res[0] if isinstance(res, tuple) else res


def test_3b_the_loc_number_reaches_the_hazard_grid():
    """DEFECT, the live values. The location has been in every extraction of this
    schedule and no code ever read it."""
    m = _map126(_T1_HAZARDS)
    got = [m.get(f"GeneralLiability_Hazard_LocationProducerIdentifier_{r}")
           for r in "ABC"]
    assert got == ["001", "002", "004"], got


def test_3b_the_haz_number_is_the_ordinal_within_its_location():
    """DEFECT + the definition. All three T1 rows are at DIFFERENT locations, so
    each is hazard 1 of its own - a naive row ordinal would print 1/2/3 and be
    wrong on every row but the first."""
    m = _map126(_T1_HAZARDS)
    got = [m.get(f"GeneralLiability_Hazard_HazardProducerIdentifier_{r}")
           for r in "ABC"]
    assert got == ["001", "001", "001"], got


def test_3b_two_hazards_at_one_location_are_numbered_one_and_two():
    """DEFECT, the other direction - the case a row ordinal gets right by
    accident and a location ordinal has to get right on purpose."""
    m = _map126([
        {"location": "001", "class_code": "91340"},
        {"location": "001", "class_code": "91580"},
        {"location": "002", "class_code": "92478"},
    ])
    assert [m.get(f"GeneralLiability_Hazard_HazardProducerIdentifier_{r}")
            for r in "ABC"] == ["001", "002", "001"]


def test_3b_a_row_with_no_location_is_not_labelled_by_a_guess():
    """GUARD. The ordinal is defined WITHIN a location. With no location there is
    no ordinal, and the box must fall through rather than invent a number."""
    from services.pdf_service import _hazard_ordinal_within_location
    assert _hazard_ordinal_within_location(
        [{"class_code": "91340"}], 0) == "UNMATCHED"


def test_3b_a_row_past_the_end_of_the_schedule_stays_blank():
    """GUARD, C46's phantom-row rule. A known, non-empty schedule shorter than
    this row letter means the row is not there - the new columns must obey that
    as strictly as the five that were already mapped."""
    m = _map126(_T1_HAZARDS)
    for col in ("LocationProducerIdentifier", "HazardProducerIdentifier"):
        assert not str(m.get(f"GeneralLiability_Hazard_{col}_D") or "").strip()


def test_3b_the_rate_and_premium_columns_are_still_owned_blanks():
    """GUARD, and it pins an OWNER DECISION, not an implementation detail. The
    four rate/premium columns are carrier-computed, `gl_class_code_schedule` has
    no key for them, and every route to them runs through a standing ruling
    ("producers rate, we don't"). If they ever start filling, that must be a
    decision someone took, not a side effect."""
    from services.pdf_service import _GL_HAZARD_FILLABLE_RE, _is_nonfillable_field
    for col in ("PremisesOperationsRate", "ProductsRate",
                "PremisesOperationsPremiumAmount", "ProductsPremiumAmount"):
        field = f"GeneralLiability_Hazard_{col}_A"
        assert not _GL_HAZARD_FILLABLE_RE.match(field), field
        assert _is_nonfillable_field(field), field


def test_3b_no_agency_identifier_was_opened_by_this_change():
    """GUARD, over all 17 schemas. The broad "ProducerIdentifier" block exists
    for AGENCY-assigned codes and the client's auto-signed-application report.
    Widening a hazard-grid carve-out must not let one of those through."""
    import glob
    import json
    from services.pdf_service import _is_nonfillable_field
    schema_dir = os.path.join(os.path.dirname(__file__), "..", "forms_schemas")
    opened = []
    for path in sorted(glob.glob(os.path.join(schema_dir, "ACORD_*_schema.json"))):
        with open(path, encoding="utf-8") as fh:
            schema = json.load(fh)
        for name in schema:
            if ("NationalIdentifier" in name or "CustomerIdentifier" in name
                    or "StateLicense" in name or "Signature" in name
                    or "_Initials" in name) and not _is_nonfillable_field(name):
                opened.append(f"{os.path.basename(path)}:{name}")
    assert not opened, opened


# =============================================================================
# R1 - the EXPIRING programme was being read as the policy being applied for
# =============================================================================
# Live, run 3 (1 Sep 2026). The same document was uploaded twice. The second
# extraction read 43% MORE off the declarations pages (167 -> 238 verified
# entries) and the forms came out WORSE - the opposite of what more evidence
# should do. The extra entries were last year's policy numbers, and nothing
# could tell them from the in-force ones:
#
#   line-identity: dec entries name 2 policy numbers for line
#   ('general liability',) (['CPP 4Q 887214 26', 'GL 7784120 25'])
#   - box left blank rather than choosing
#
# Refusing is the right instinct. It cost seven of eight coverage lines their
# policy number and stamped the EXPIRING umbrella number on ACORD 131.
_R1_PRIOR_GRID = [
    {"line": "General Liability", "carrier": "Sentinel Prairie Casualty Company",
     "policy_no": "GL 7784120 25", "effective": "03/15/2025", "expiration": "03/15/2026"},
    {"line": "Automobile", "carrier": "Sentinel Prairie Casualty Company",
     "policy_no": "CA 7784121 25", "effective": "03/15/2025", "expiration": "03/15/2026"},
    {"line": "Property", "carrier": "Sentinel Prairie Casualty Company",
     "policy_no": "CF 7784122 25", "effective": "03/15/2025", "expiration": "03/15/2026"},
    {"line": "Umbrella", "carrier": "Ridgeline Specialty Indemnity Company",
     "policy_no": "XSU 55 210934 25", "effective": "03/15/2025", "expiration": "03/15/2026"},
]
# The live entries, trimmed to the ones that decide the umbrella line.
_R1_ENTRIES = [
    {"label": "POLICY NUMBER", "value": "CPP 4Q 887214 26",
     "section": "COMMERCIAL GENERAL LIABILITY COVERAGE PART DECLARATIONS",
     "owner": "policy", "policy_number": "CPP 4Q 887214 26",
     "line_of_business": "General Liability"},
    {"label": "POLICY NUMBER", "value": "XSU 55 210934 26",
     "section": "COMMERCIAL EXCESS LIABILITY DECLARATIONS", "owner": "policy",
     "policy_number": "XSU 55 210934 26", "line_of_business": "Commercial Umbrella"},
    {"label": "POLICY NUMBER", "value": "GL 7784120 25",
     "section": "EXPIRING PROGRAMME SUMMARY", "owner": "policy",
     "policy_number": "GL 7784120 25", "line_of_business": "General Liability"},
    {"label": "POLICY NUMBER", "value": "XSU 55 210934 25",
     "section": "EXPIRING PROGRAMME SUMMARY", "owner": "policy",
     "policy_number": "XSU 55 210934 25", "line_of_business": "Commercial Umbrella"},
    # The live artifact: ONE entry inside the expiring block carrying the
    # CURRENT package number under a garbled header label. It made the package
    # number a third candidate for the UMBRELLA line.
    {"label": "LINE EXPIRING INSURER POLICY N", "value": "Umbrella",
     "section": "EXPIRING PROGRAMME SUMMARY", "owner": "policy",
     "policy_number": "CPP 4Q 887214 26", "line_of_business": "Commercial Umbrella"},
]
_R1_FACTS = {"dec_page_entries": _R1_ENTRIES,
             "prior_coverage_by_line": _R1_PRIOR_GRID,
             "policy_number": {"value": "CPP 4Q 887214 26"}}


def test_r1_prior_term_numbers_come_from_the_prior_grid():
    """DEFECT. `prior_coverage_by_line` is the fact whose entire MEANING is
    'the expiring programme' - so the structure says which numbers are last
    year's and no vocabulary has to."""
    from services.extraction_service import prior_term_policy_numbers
    got = prior_term_policy_numbers(_R1_FACTS)
    assert got == {"gl778412025", "ca778412125", "cf778412225", "xsu5521093425"}, got


def test_r1_a_same_number_renewal_is_not_a_prior_number():
    """GUARD. A renewal often keeps its number, and then the prior grid documents
    the policy that is still IN FORCE - `_current_number_from_prior_grid` relies
    on exactly that. A number that IS the session's own `policy_number` must
    never be reported as prior."""
    from services.extraction_service import prior_term_policy_numbers
    facts = {"prior_coverage_by_line": [{"line": "General Liability",
                                         "policy_no": "CPP 4Q 887214 26"}],
             "policy_number": {"value": "CPP 4Q 887214 26"}}
    assert prior_term_policy_numbers(facts) == set()


def test_r1_the_umbrella_line_resolves_to_this_years_policy():
    """DEFECT, the live values. Three candidates went in; the in-force one comes
    out. Last year's umbrella number is dropped because it is in the prior grid;
    the package number is dropped for this line because its only attribution to
    the umbrella came from inside the expiring block."""
    from services.extraction_service import current_numbers_by_line
    by_line = current_numbers_by_line(_R1_ENTRIES, _R1_FACTS)
    umbrella = [v for k, v in by_line.items() if "umbrella" in k.lower()]
    assert umbrella and umbrella[0] == {"XSU 55 210934 26"}, by_line


def test_r1_general_liability_keeps_the_package_number():
    """GUARD. The package number is perfectly real - it is only its position
    INSIDE the expiring block that makes that one attribution worthless. Its
    own declarations section must still resolve GL to it."""
    from services.extraction_service import current_numbers_by_line
    by_line = current_numbers_by_line(_R1_ENTRIES, _R1_FACTS)
    gl = [v for k, v in by_line.items() if "general" in k.lower()]
    assert gl and gl[0] == {"CPP 4Q 887214 26"}, by_line


def test_r1_the_filter_is_a_tie_breaker_and_can_never_empty_a_line():
    """GUARD, and it is THE safety property. A line whose every candidate comes
    from the expiring programme keeps them ALL, so this can never turn a box that
    resolves today into a blank."""
    from services.extraction_service import current_numbers_by_line
    entries = [{"label": "POLICY NUMBER", "value": "GL 7784120 25",
                "section": "EXPIRING PROGRAMME SUMMARY", "owner": "policy",
                "policy_number": "GL 7784120 25", "line_of_business": "General Liability"},
               {"label": "POLICY NUMBER", "value": "CA 7784121 25",
                "section": "EXPIRING PROGRAMME SUMMARY", "owner": "policy",
                "policy_number": "CA 7784121 25", "line_of_business": "Commercial Auto"}]
    facts = {"dec_page_entries": entries, "prior_coverage_by_line": _R1_PRIOR_GRID}
    by_line = current_numbers_by_line(entries, facts)
    assert by_line, "the filter emptied every line - it must be a tie-breaker only"
    for line, nums in by_line.items():
        assert nums, f"{line} was emptied"


def test_r1_one_renewal_mention_does_not_condemn_a_section():
    """GUARD, and the reason the section rule needs TWO. A real declarations page
    prints 'Renewal of policy GL 7784120 25' in its COMMON POLICY DECLARATIONS.
    One prior number under a heading is a note in passing; two is a summary table
    of last year's programme."""
    from services.extraction_service import _prior_programme_sections
    entries = [
        {"section": "COMMON POLICY DECLARATIONS", "policy_number": "GL 7784120 25"},
        {"section": "COMMON POLICY DECLARATIONS", "policy_number": "CPP 4Q 887214 26"},
        {"section": "EXPIRING PROGRAMME SUMMARY", "policy_number": "GL 7784120 25"},
        {"section": "EXPIRING PROGRAMME SUMMARY", "policy_number": "CA 7784121 25"},
    ]
    prior = {"gl778412025", "ca778412125"}
    got = _prior_programme_sections(entries, prior)
    assert got == {"expiring programme summary"}, got


def test_r1_no_prior_grid_means_no_filtering_at_all():
    """GUARD. A session with no prior-coverage evidence behaves exactly as it did
    before this change - fail-open, byte for byte."""
    from services.extraction_service import current_numbers_by_line, _policy_numbers_by_line
    facts = {"dec_page_entries": _R1_ENTRIES}
    assert current_numbers_by_line(_R1_ENTRIES, facts) == _policy_numbers_by_line(_R1_ENTRIES)


def test_r1_the_section_rule_reads_no_heading_vocabulary():
    """ANTI-ROT. Our fixture writes 'EXPIRING PROGRAMME SUMMARY'; a real carrier
    writes 'PRIOR POLICY', 'RENEWAL OF' or nothing. If anyone ever matches on the
    words, this fails - the rule must stay learned from where the numbers are."""
    import inspect
    from services import extraction_service as es
    src = inspect.getsource(es._prior_programme_sections)
    body = src.split('"""', 2)[-1]           # strip the docstring's own examples
    # ...and the comments: a comment QUOTING the fixture's heading is
    # documentation of a measured defect, not a match rule. Only executable
    # lines may be held to the no-vocabulary bar.
    body = "\n".join(l.split("#", 1)[0] for l in body.splitlines())
    for word in ("expiring", "prior polic", "renewal of", "previous", "last year"):
        assert word not in body.lower(), (
            f"_prior_programme_sections now matches heading wording ({word!r}) - "
            "that is a fixture allow-list, not a derived rule")


# =============================================================================
# R2 - the CONTACT's phone was being written into the NAMED INSURED's box
# =============================================================================
def test_r2_the_contact_phone_never_reaches_the_business_phone_box():
    """DEFECT, over all 17 schemas. `NamedInsured_Primary_PhoneNumber` is ACORD's
    BUSINESS PHONE # box - its own tooltip reads 'The named insured's primary
    phone number.' The contact has a separate box on the same form."""
    import glob
    import json
    from services.pdf_service import compute_form_gaps
    facts = {"contact_phone": "(303) 555-0147", "contact_name": "Delphine Ostrander",
             "applicant_name": "Verdant Slope Builders, LLC"}
    schema_dir = os.path.join(os.path.dirname(__file__), "..", "forms_schemas")
    offenders = []
    for path in sorted(glob.glob(os.path.join(schema_dir, "ACORD_*_schema.json"))):
        fid = os.path.basename(path).replace("_schema.json", "")
        with open(path, encoding="utf-8") as fh:
            schema = json.load(fh)
        mapped, _unmatched, _ = compute_form_gaps(fid, schema, facts)
        for field, value in mapped.items():
            if value is None or str(value).strip() != "(303) 555-0147":
                continue
            if "Contact" not in field:
                offenders.append(f"{fid}:{field}")
    assert not offenders, offenders


def test_r2_the_contact_still_gets_its_own_box():
    """GUARD. Removing the wrong mapping must not lose the right one - the
    contact's phone has a correct home and has always filled it."""
    import json
    from services.pdf_service import compute_form_gaps
    schema = _acord_schema("ACORD_125")
    mapped, _u, _ = compute_form_gaps("ACORD_125", schema,
                                      {"contact_phone": "(303) 555-0147"})
    assert mapped.get("NamedInsured_Contact_PrimaryPhoneNumber_A") == "(303) 555-0147"


def test_r2_the_business_phone_box_reaches_gap_fill_with_its_siblings():
    """DEFECT (the half that fixes the slide). With row A no longer pre-filled
    WRONGLY, all three rows are asked together, so the model finds the three
    companies' phones as one table instead of starting one row down."""
    from services.pdf_service import compute_form_gaps
    schema = _acord_schema("ACORD_125")
    _m, unmatched, _ = compute_form_gaps("ACORD_125", schema,
                                         {"contact_phone": "(303) 555-0147"})
    for row in "ABC":
        assert f"NamedInsured_Primary_PhoneNumber_{row}" in unmatched, row


def test_r2_no_rule_writes_a_contact_fact_into_a_named_insured_identity_box():
    """ANTI-ROT. The same category error is easy to reintroduce the next time a
    box looks unfilled. A `contact_*` fact belongs in a `*_Contact_*` box."""
    from services.pdf_service import _ACORD_FIELD_RULES
    bad = [(f, k) for f, k in _ACORD_FIELD_RULES
           if isinstance(k, str) and k.startswith("contact_")
           and f.startswith("NamedInsured_") and "_Contact_" not in f]
    assert not bad, bad


# =============================================================================
# Y1 - the option boxes of ONE question are one answer, not four borrows
# =============================================================================
# ACORD asks some questions as one question plus a row of option boxes:
#   2. IS A FORMAL SAFETY PROGRAM IN OPERATION?
#      [ ] SAFETY MANUAL [ ] SAFETY POSITION [ ] MONTHLY MEETINGS [ ] OSHA
# One document sentence legitimately ticks all four. The reuse cap counted one
# use per FIELD, so the cluster size was 4, `4 > _EVIDENCE_YES_QUOTE_REUSE_MAX`
# (1), and all four were blanked - measured identically on runs 3 and 4, on a
# form that answered the parent question Y and then left every option empty.


def test_y1_option_boxes_share_one_parent():
    from services.pdf_service import _checkbox_option_group
    schema = _acord_schema("ACORD_125")
    parents = {
        _checkbox_option_group(f"CommercialPolicy_FormalSafetyProgram_{o}", schema)
        for o in ("SafetyManualIndicator_A", "MonthlyMeetingsIndicator_B",
                  "SafetyPositionIndicator_B", "OSHAIndicator_B")
    }
    assert parents == {"CommercialPolicy_FormalSafetyProgram"}, parents


def test_y1_a_compliance_question_is_never_an_option():
    """GUARD, and the entire safety argument. Each `..._Question_<code>Code_`
    field is a DIFFERENT question, where a shared quote IS a borrow - the
    false-Yes flood the cap was built for. They must stay outside the rule."""
    from services.pdf_service import _checkbox_option_group
    schema = _acord_schema("ACORD_125")
    for f in ("CommercialPolicy_Question_AAJCode_A",
              "CommercialPolicy_Question_KANCode_A",
              "CommercialPolicy_Question_ABCCode_A"):
        assert _checkbox_option_group(f, schema) is None, f


def test_y1_no_own_question_checkbox_gets_an_option_group_anywhere():
    """ANTI-ROT, all 17 schemas. A checkbox-PAIR compliance question carries
    `response to the question,` in its tooltip; if one ever receives an option
    group, the reuse cap goes free across the compliance family."""
    import glob
    import json
    from services.pdf_service import _checkbox_option_group
    schema_dir = os.path.join(os.path.dirname(__file__), "..", "forms_schemas")
    leaked = []
    for path in sorted(glob.glob(os.path.join(schema_dir, "ACORD_*_schema.json"))):
        with open(path, encoding="utf-8") as fh:
            schema = json.load(fh)
        for f, m in schema.items():
            if not isinstance(m, dict) or "/Btn" not in str(m.get("ft") or ""):
                continue
            if "response to the question," in str(m.get("tu") or "")                     and _checkbox_option_group(f, schema):
                leaked.append(f"{os.path.basename(path)}:{f}")
    assert not leaked, leaked


def test_y1_the_reuse_cap_counts_answer_units_not_fields():
    """DEFECT, at the seam. Four option boxes citing one sentence must count as
    ONE use; four different Question codes citing one sentence must count as
    FOUR. Asserted against the source so the counting cannot silently revert."""
    import inspect
    from services import pdf_service
    src = inspect.getsource(pdf_service.map_facts_to_form)
    assert "_checkbox_option_group(_f, schema) or _f" in src
    assert "_quote_cluster_units" in src


# =============================================================================
# L1 - TOTAL LOSSES is the whole schedule's arithmetic or a blank
# =============================================================================
# Runs 3 and 4, identical output: the model summed the THREE rows the ACORD 125
# grid displays ($129,400) and called it the total, while the extracted schedule
# holds FIVE losses and the document states $568,495.
_L1_LOSSES = [
    {"claim_number": "GL-2025-30712", "paid": "$91,000", "reserved_amount": "$145,000"},
    {"claim_number": "GL-2023-11884", "paid": "$38,400", "reserved_amount": "$0"},
    {"claim_number": "GL-2025-41220", "paid": "$0", "reserved_amount": "$75,000"},
    {"claim_number": "AU-2024-20551", "paid": "$6,215", "reserved_amount": "$0"},
    {"claim_number": "PR-2022-08109", "paid": "$212,880", "reserved_amount": "$0"},
]


def test_l1_the_total_is_derived_from_the_whole_schedule():
    """DEFECT, the live values - and the assertion CORRECTED 2 Sep 2026.

    The box shipped a partial sum of the three DISPLAYED rows while the
    schedule holds five losses. The derivation fixes that. What the first
    version ALSO got wrong: it summed paid + reserved ($348,495 + $220,000)
    and matched the document's printed "TOTAL LOSSES $568,495" exactly - but
    that headline is TOTAL INCURRED, and ACORD's tooltip on this box asks for
    "the amount that has been PAID on all losses to date". Matching a number
    the document prints is not evidence it belongs in the box.
    """
    from services.pdf_service import _resolve_loss_history_summary
    got = _resolve_loss_history_summary(
        "LossHistory_TotalAmount_A", {"loss_history": _L1_LOSSES})
    assert _amt(got) == "348,495", got


def test_l1_a_row_that_cannot_be_summed_makes_the_box_an_owned_blank():
    """GUARD - right-or-blank. A partial sum labelled TOTAL understates the
    account's loss history on a signed application; blank beats it. Prose in a
    paid cell fails the parse rather than counting as zero."""
    from services.pdf_service import _resolve_loss_history_summary
    for rows in ([{"claim_number": "X", "reserved_amount": "$5,000"}],
                 [{"paid": "see attached summary"}],
                 [_L1_LOSSES[0], {"claim_number": "Y"}]):
        assert _resolve_loss_history_summary(
            "LossHistory_TotalAmount_A", {"loss_history": rows}) is None, rows


def test_l1_no_schedule_is_an_owned_blank_not_a_gap_fill_question():
    """GUARD. With no schedule, the only thing gap fill can do here is re-run
    the measured defect - sum whatever rows it can see."""
    from services.pdf_service import _resolve_loss_history_summary, compute_form_gaps
    assert _resolve_loss_history_summary("LossHistory_TotalAmount_A", {}) is None
    schema = _acord_schema("ACORD_125")
    _m, unmatched, _ = compute_form_gaps("ACORD_125", schema, {})
    assert "LossHistory_TotalAmount_A" not in unmatched


def test_l1_reserved_never_enters_the_total():
    """CORRECTED 2 Sep 2026. ACORD's tooltip scopes this box to "the amount
    that has been PAID on all losses to date", so a reserve - money the prior
    carrier is holding OPEN, not money paid - is not part of it. The reserve
    is still READ per row, because a row stating a reserve and no paid amount
    is the unsummable case the owned-blank rule refuses."""
    from services.pdf_service import _resolve_loss_history_summary
    got = _resolve_loss_history_summary(
        "LossHistory_TotalAmount_A",
        {"loss_history": [{"paid": "$1,000"}, {"paid": "$500", "reserved_amount": "$250"}]})
    assert _amt(got) == "1,500", got


# =============================================================================
# S1 - a column bound to a live schedule fact is DATA, not an owned blank
# =============================================================================
# Four `_SCHEDULE_REGISTRY` binding families were already written, already
# pointed at real facts, and could never fire - `_is_nonfillable_field` ran
# BEFORE the registry lookup. 40 fields; the census verified NONE is Group A.
_S1_FACTS = {
    "wc_class_codes": [
        {"code": "5551", "description": "Roofing", "state": "CO",
         "payroll": "$1,318,000", "rate": "18.42", "location_number": "001"},
        {"code": "8810", "description": "Clerical", "state": "CO",
         "payroll": "$260,000", "rate": "0.31", "location_number": "001"},
    ],
    "property_locations": [
        {"address_line1": "1188 Larimer Crossing", "address_city": "Denver",
         "location_number": "1"},
        {"address_line1": "3390 E Overland Rd", "address_city": "Aurora",
         "location_number": "2"},
    ],
}


def test_s1_a_bound_rate_column_stamps_from_the_extracted_schedule():
    """DEFECT. `wc_class_codes.rate` is an extracted v17 fact and its binding
    existed; the name gate threw it away."""
    from services.pdf_service import compute_form_gaps
    schema = _acord_schema("ACORD_130")
    mapped, _u, _ = compute_form_gaps("ACORD_130", schema, _S1_FACTS)
    assert mapped.get("WorkersCompensation_RateClass_Rate_A") == "18.42"
    assert mapped.get("WorkersCompensation_RateClass_Rate_B") == "0.31"
    assert mapped.get("Location_ProducerIdentifier_A") == "1"
    assert mapped.get("Location_ProducerIdentifier_B") == "2"


def test_s1_a_row_past_the_schedule_stays_an_owned_blank():
    """GUARD. The registry only wins when it HAS a value - no value, and the
    box stays exactly as blocked as before."""
    from services.pdf_service import compute_form_gaps
    schema = _acord_schema("ACORD_130")
    mapped, unmatched, _ = compute_form_gaps("ACORD_130", schema, _S1_FACTS)
    assert mapped.get("WorkersCompensation_RateClass_Rate_C") is None
    assert "WorkersCompensation_RateClass_Rate_C" in mapped
    assert "WorkersCompensation_RateClass_Rate_C" not in unmatched


def test_s1_no_rate_or_premium_ever_reaches_the_model():
    """GUARD - the standing invariant. The fix is an ORDERING change on the
    deterministic path; the gap-fill union must be untouched by it."""
    from services.pdf_service import compute_form_gaps, _is_nonfillable_field
    schema = _acord_schema("ACORD_130")
    _m, unmatched, _ = compute_form_gaps("ACORD_130", schema, _S1_FACTS)
    leaked = [f for f in unmatched
              if _is_nonfillable_field(f) and "PageNumber" not in f]
    assert not leaked, leaked


def test_s1_group_a_is_untouched_by_the_ordering_change():
    """ANTI-ROT, all 17 schemas: no signature, initials, licence or agency
    identifier is registry-bound, so the new door cannot open one."""
    import glob
    import json
    import re
    import services.pdf_service as ps
    schema_dir = os.path.join(os.path.dirname(__file__), "..", "forms_schemas")
    bad = []
    for path in sorted(glob.glob(os.path.join(schema_dir, "ACORD_*_schema.json"))):
        with open(path, encoding="utf-8") as fh:
            schema = json.load(fh)
        for f in schema:
            m = re.match(r"^(.+)_([A-N])$", f)
            if not m:
                continue
            base = m.group(1)
            if base not in ps._SCHEDULE_REGISTRY:
                continue
            if any(t in f for t in ("Signature", "_Initials", "StateLicense",
                                    "NationalIdentifier", "CustomerIdentifier")):
                bad.append(f"{os.path.basename(path)}:{f}")
    assert not bad, bad


# =============================================================================
# I8 - the borrowed-value backstop was MEASURED AND REJECTED. Do not build it.
# =============================================================================
def test_i8_the_borrowed_value_rule_stays_unbuilt():
    """ANTI-ROT for a NEGATIVE result. The candidate backstop - "reject a table
    cell whose value already appears in a different family on the same form" -
    was measured over two live runs against the answer key: **0 true positives,
    54 false positives** (every mailing address, every physical address, every
    prior policy number legitimately co-occurs across families). Building it
    would delete real data and catch nothing. This test greps the module so it
    cannot arrive quietly; remove the test only WITH a new measurement."""
    import inspect
    from services import pdf_service
    src = inspect.getsource(pdf_service)
    assert "borrowed_value" not in src.lower().replace("-", "_"), (
        "a borrowed-value rule appeared - it measured 0 TP / 54 FP on 1-2 Sep "
        "2026; re-measure before shipping anything by this name")


# =============================================================================
# R3 - run 5's three faces of one defect: the expiring programme, again
# =============================================================================
# Run 5's extraction attributed EVERY expiring-block entry to the CURRENT
# package number (its "which policy does this page belong to" guess) and put
# the actual prior numbers in the printed VALUES. Three consequences, measured:
# the section went unidentified (R1's rule read attributions only), the
# umbrella box refused and fell through to the prior-grid rescue, and that
# rescue stamped the EXPIRING umbrella number - and its carrier twin stamped
# the EXPIRING carrier - as CURRENT on the section headers.
_R3_ENTRIES = [
    {"label": "POLICY NUMBER", "value": "XSU 55 210934 26", "owner": "policy",
     "section": "COMMERCIAL EXCESS LIABILITY DECLARATIONS",
     "policy_number": "XSU 55 210934 26", "line_of_business": "Commercial Umbrella"},
    # The run-5 shape: prior numbers as VALUES, attribution = the package no.
    {"label": "POLICY NUMBER", "value": "GL 7784120 25", "owner": "policy",
     "section": "EXPIRING PROGRAMME SUMMARY",
     "policy_number": "CPP 4Q 887214 26", "line_of_business": "General Liability"},
    {"label": "POLICY NUMBER", "value": "XSU 55 210934 25", "owner": "policy",
     "section": "EXPIRING PROGRAMME SUMMARY",
     "policy_number": "CPP 4Q 887214 26", "line_of_business": "Umbrella"},
    {"label": "EXPIRING INSURER", "value": "Sentinel Prairie Casualty Company",
     "owner": "carrier", "section": "EXPIRING PROGRAMME SUMMARY",
     "policy_number": "CPP 4Q 887214 26", "line_of_business": "General Liability"},
]
_R3_FACTS = {"dec_page_entries": _R3_ENTRIES,
             "prior_coverage_by_line": [
                 {"line": "General Liability", "policy_no": "GL 7784120 25",
                  "effective": "03/15/2025", "expiration": "03/15/2026"},
                 {"line": "Umbrella", "policy_no": "XSU 55 210934 25",
                  "carrier": "Ridgeline Specialty Indemnity Company",
                  "effective": "03/15/2025", "expiration": "03/15/2026"}],
             "policy_number": {"value": "CPP 4Q 887214 26"}}


def test_r3_prior_numbers_printed_as_values_identify_the_section():
    """DEFECT (A). Two distinct prior-term numbers in the entries' VALUES mark
    the section, whichever field they arrived in."""
    from services.extraction_service import (_prior_programme_sections,
                                             prior_term_policy_numbers)
    got = _prior_programme_sections(_R3_ENTRIES, prior_term_policy_numbers(_R3_FACTS))
    assert got == {"expiring programme summary"}, got


def test_r3_prior_numbers_glued_inside_one_value_still_identify_the_section():
    """DEFECT (run 6, 2 Sep 2026). That extraction glued each expiring row into
    ONE entry whose value is the whole printed line, so a whole-value equality
    test missed every prior number and the section went unidentified a THIRD
    time. A normalised prior number is 10+ alphanumerics - substring at that
    length is unambiguous."""
    from services.extraction_service import (_prior_programme_sections,
                                             prior_term_policy_numbers)
    entries = [
        {"section": "EXPIRING PROGRAMME SUMMARY",
         "label": "LINE EXPIRING INSURER POLICY N",
         "value": "GENERAL LIABILITY Sentinel Prairie Casualty Company GL 7784120 25 $54,120",
         "policy_number": "CPP 4Q 887214 26"},
        {"section": "EXPIRING PROGRAMME SUMMARY",
         "label": "LINE EXPIRING INSURER POLICY N",
         "value": "UMBRELLA Ridgeline Specialty Indemnity Com XSU 55 210934 25 $21,300",
         "policy_number": "CPP 4Q 887214 26"},
        # one renewal mention elsewhere must still NOT condemn its section
        {"section": "COMMON POLICY DECLARATIONS", "label": "TRANSACTION",
         "value": "Renewal of policy GL 7784120 25",
         "policy_number": "CPP 4Q 887214 26"},
    ]
    got = _prior_programme_sections(entries, prior_term_policy_numbers(_R3_FACTS))
    assert got == {"expiring programme summary"}, got


def test_r3_the_manufactured_attribution_dies_with_its_section():
    """DEFECT (A), the consequence. The CPP->umbrella attribution lives only
    inside the expiring block, so once the block is identified the umbrella
    line resolves to this year's own number."""
    from services.extraction_service import current_numbers_by_line
    by_line = current_numbers_by_line(_R3_ENTRIES, _R3_FACTS)
    umb = [v for k, v in by_line.items() if "umbrella" in k.lower() or "mbrella" in k.lower()]
    assert umb and umb[0] == {"XSU 55 210934 26"}, by_line


def test_r3_the_prior_grid_rescue_defers_to_the_lines_own_term():
    """DEFECT (B). The routed prior term is package-level FALLBACK evidence.
    When the line's own coverage_lines entry states its term, the rescue must
    not widen the match with the prior term - that stamped the EXPIRING number
    (and carrier) as CURRENT on a section header."""
    from services.pdf_service import (_current_number_from_prior_grid,
                                      _current_carrier_from_prior_grid)
    facts = {"prior_coverage_by_line": _R3_FACTS["prior_coverage_by_line"],
             "prior_effective_date": "03/15/2025",
             "prior_expiration_date": "03/15/2026"}
    matched = [{"line": "Umbrella", "effective_date": "03/15/2026",
                "expiration_date": "03/15/2027"}]
    phrases = ("umbrella", "excess")
    assert _current_number_from_prior_grid(facts, phrases, matched) is None
    assert _current_carrier_from_prior_grid(facts, phrases, matched) is None
    # GUARD - the Orbin case this rescue exists for: the line's own entries
    # carry NO dates, so the routed prior term is the only witness and the
    # rescue still fires.
    undated = [{"line": "Umbrella"}]
    assert _current_number_from_prior_grid(facts, phrases, undated) == "XSU 55 210934 25"


def test_r3_the_expiring_carrier_never_enters_the_carrier_index():
    """DEFECT (the carrier axis). The only owner='carrier' entries for a line
    often sit INSIDE the expiring block ("EXPIRING INSURER"); indexing them
    wrote the outgoing carrier onto coverage_lines and the ACORD 126 header."""
    from services.extraction_service import _carriers_by_line
    with_facts = _carriers_by_line(_R3_ENTRIES, _R3_FACTS)
    for line, names in with_facts.items():
        assert "Sentinel Prairie Casualty Company" not in names, (line, names)
    # Fail-open: without facts the index behaves exactly as before.
    without = _carriers_by_line(_R3_ENTRIES)
    assert any("Sentinel Prairie Casualty Company" in v for v in without.values())


def test_r3_anchored_rows_name_their_own_entity_in_the_prompt():
    """DEFECT (C). Runs 4 and 5 each showed one half of this: rows B/C came
    back empty, then row C took row B's company. The known FullName cells are
    deterministic and were invisible to the table block (FullName is never an
    ACTIVE column). The block must anchor each known row to its entity."""
    fields = _unmatched_from("ACORD_125", _I6_NAMED_INSURED_COLUMNS)
    fields.update(_unmatched_from("ACORD_125", [
        "NamedInsured_MailingAddress_LineOne",
        "NamedInsured_MailingAddress_CityName",
        "NamedInsured_MailingAddress_PostalCode",
    ]))
    already = {
        "NamedInsured_FullName_A": "Verdant Slope Builders, LLC",
        "NamedInsured_FullName_B": "Halewood Ridge Framing, Inc.",
        "NamedInsured_FullName_C": "Cotter Bench Equipment Leasing, LLC",
    }
    prompt = _capture_gap_fill_prompt(fields, "ACORD_125", already_filled=already)
    assert "ROWS WITH KNOWN IDENTITY" in prompt
    assert "_B belongs to: FullName=Halewood Ridge Framing, Inc." in prompt
    assert "_C belongs to: FullName=Cotter Bench Equipment Leasing, LLC" in prompt
    assert "NEVER assign a different entry to one of these rows" in prompt


def test_r3_a_fully_resolved_row_is_still_a_skip_not_an_anchor():
    """GUARD. A known row with NO requested fields keeps the original contract:
    shown only so its entry is not re-found, never part of the response."""
    fields = _unmatched_from("ACORD_125", _I6_NAMED_INSURED_COLUMNS, rows="BC")
    already = {"NamedInsured_FullName_A": "Verdant Slope Builders, LLC",
               "NamedInsured_SICCode_A": "1761"}
    prompt = _capture_gap_fill_prompt(fields, "ACORD_125", already_filled=already)
    assert "_A (already filled):" in prompt
    assert "_A belongs to:" not in prompt


# =============================================================================
# M1 - the rating MOD box, shipped in the shape the stress test demanded
# =============================================================================
# OWNER APPROVED 1 Sep 2026 ("works, and i dont want this to be hardcoded and
# it should work correctly for real client docs"). The adversarial stress test
# then defeated the rule AS FIRST DESIGNED 11 times out of 12 - including the
# exact "SEE ITEM 4" and "$500" junk the original ruling was written about -
# so the approval's own condition gates this suite: every one of those cases
# is pinned here, permanently. The transcription lives INSIDE
# `_resolve_underlying_policy_row` (the row's one owner), so compute_form_gaps
# still refuses and the gap-fill LLM is still never asked.


def _dec_probe(field, entries, form_id="ACORD_131"):
    import services.pdf_service as ps
    schema = _acord_schema(form_id)
    ps._SCHEMA_CTX.schema = schema
    return ps._dec_index_rating_value(field, {"dec_page_entries": entries})


def _mod_entry(label, value, line="Employers Liability"):
    return {"label": label, "value": value, "line_of_business": line,
            "owner": "policy", "section": "SCHEDULE OF UNDERLYING INSURANCE"}


_M1_FIELD = "UnderlyingPolicy_EmployersLiability_ModificationFactor_A"


def test_m1_a_leftover_free_mod_label_transcribes():
    """The approved behaviour: the dec prints the line's own combined mod under
    a clean label, and the figure stamps."""
    got = _dec_probe(_M1_FIELD, [_mod_entry("EMPLOYERS LIABILITY MODIFICATION FACTOR", "0.94")])
    assert got == "0.94", got


def test_m1_the_mod_fills_through_its_one_owner_end_to_end():
    """Through the REAL resolver chain (rule 4: the seam, not the function).
    The read sits inside `_resolve_underlying_policy_row`; the LLM path stays
    closed (compute_form_gaps must still refuse the field)."""
    from services.pdf_service import map_facts_to_form, compute_form_gaps
    schema = _acord_schema("ACORD_131")
    facts = {"dec_page_entries": [
        _mod_entry("EMPLOYERS LIABILITY MODIFICATION FACTOR", "0.94"),
        _mod_entry("AUTO MODIFICATION FACTOR", "1.00", "Commercial Automobile")]}
    res = map_facts_to_form(facts, schema, form_id="ACORD_131")
    mapped = res[0] if isinstance(res, tuple) else res
    assert mapped.get(_M1_FIELD) == "0.94"
    assert mapped.get("UnderlyingPolicy_Automobile_ModificationFactor_A") == "1.00"
    _m, unmatched, _ = compute_form_gaps("ACORD_131", schema, facts)
    assert _M1_FIELD not in unmatched, "the LLM is being asked for a rating factor"


@pytest.mark.parametrize("name,label,value", [
    ("experience-only is not the combined mod", "EXPERIENCE MODIFICATION FACTOR", "0.87"),
    ("ARAP is a different rating step", "ARAP MODIFICATION FACTOR", "1.15"),
    ("increased-limits is a different step",
     "EMPLOYERS LIABILITY INCREASED LIMITS MODIFICATION FACTOR", "1.10"),
    ("prose never stamps a rate box",
     "EMPLOYERS LIABILITY MODIFICATION FACTOR", "SEE ITEM 4 OF THE INFORMATION PAGE"),
    ("a dollar amount never stamps a factor box",
     "EMPLOYERS LIABILITY MODIFICATION FACTOR", "$500"),
    ("an effective DATE row is not the factor",
     "EMPLOYERS LIABILITY MODIFICATION FACTOR EFFECTIVE DATE", "07/13/2026"),
])
def test_m1_the_stress_tests_mod_cases_stay_refused(name, label, value):
    assert _dec_probe(_M1_FIELD, [_mod_entry(label, value)]) is None, name


@pytest.mark.parametrize("name,label,value", [
    ("the line TOTAL is not a component premium",
     "EMPLOYERS LIABILITY TOTAL PREMIUM", "$71,410"),
    ("an EXPIRING premium is last year's",
     "EMPLOYERS LIABILITY EXPIRING PREMIUM", "$68,000"),
])
def test_m1_the_stress_tests_premium_cases_stay_refused(name, label, value):
    got = _dec_probe("UnderlyingPolicy_EmployersLiability_PremiumAmount_A",
                     [_mod_entry(label, value)])
    assert got is None, name


def test_m1_one_entry_can_never_stamp_two_boxes():
    """The stress test's LIVE finding: uniqueness ran entry-to-field only, and
    one "COMMERCIAL PROPERTY PREMIUM $18,400" entry stamped TEN ACORD 160
    boxes. The reverse direction now refuses: measured over every rating field
    on the schema, one entry stamps at most one box - here, zero, because ten
    columns fit it equally."""
    spray = [{"label": "COMMERCIAL PROPERTY PREMIUM", "value": "$18,400",
              "line_of_business": "Commercial Property", "owner": "policy",
              "section": "S"}]
    import services.pdf_service as ps
    schema = _acord_schema("ACORD_160")
    ps._SCHEMA_CTX.schema = schema
    stamped = [f for f in schema if ps._DEC_RATING_FIELD_RE.match(f)
               and ps._dec_index_rating_value(f, {"dec_page_entries": spray})]
    assert len(stamped) <= 1, stamped


def test_m1_acords_own_compound_products_label_still_stamps():
    """GUARD for the exclusivity rule's one calibrated allowance: ACORD itself
    names the products part "Products/Completed Operations", so that compound
    is the SAME figure, not a qualifier - refusing it cost the live $14,555."""
    got = _dec_probe(
        "UnderlyingPolicy_GeneralLiability_ProductsPremiumAmount_A",
        [_mod_entry("GL PRODUCTS/COMPLETED OPERATIONS PREMIUM", "$14,555",
                    "General Liability")])
    assert _amt(got) == "14,555", got


def test_m1_the_live_t1_values_all_still_stamp():
    """GUARD - the hardening must not cost the four premiums batch 1 shipped."""
    entries = [
        _mod_entry("GL PREMISES/OPERATIONS PREMIUM", "$46,900", "General Liability"),
        _mod_entry("GL PRODUCTS/COMPLETED OPERATIONS PREMIUM", "$14,555", "General Liability"),
        _mod_entry("AUTO COMBINED SINGLE LIMIT PREMIUM", "$18,240", "Commercial Automobile"),
        _mod_entry("EMPLOYERS LIABILITY PREMIUM", "$71,410"),
    ]
    for field, want in (
            ("UnderlyingPolicy_GeneralLiability_PremisesOperationsPremiumAmount_A", "$46,900"),
            ("UnderlyingPolicy_GeneralLiability_ProductsPremiumAmount_A", "$14,555"),
            ("UnderlyingPolicy_Automobile_CombinedSingleLimitPremiumAmount_A", "$18,240"),
            ("UnderlyingPolicy_EmployersLiability_PremiumAmount_A", "$71,410")):
        assert _dec_probe(field, entries) == want, field


def test_m1_the_expiring_programme_never_transcribes():
    """The R3 door, wired in here too: an entry printed inside an identified
    prior-programme section describes LAST YEAR's figure."""
    entries = [
        _mod_entry("EMPLOYERS LIABILITY MODIFICATION FACTOR", "0.99"),
        # two prior numbers identify the section...
        {"label": "POLICY NUMBER", "value": "GL 7784120 25", "owner": "policy",
         "section": "EXPIRING PROGRAMME SUMMARY", "policy_number": "GL 7784120 25",
         "line_of_business": "General Liability"},
        {"label": "POLICY NUMBER", "value": "CA 7784121 25", "owner": "policy",
         "section": "EXPIRING PROGRAMME SUMMARY", "policy_number": "CA 7784121 25",
         "line_of_business": "Commercial Auto"},
    ]
    entries.append({**_mod_entry("EMPLOYERS LIABILITY MODIFICATION FACTOR", "1.30"),
                    "section": "EXPIRING PROGRAMME SUMMARY"})
    facts = {"dec_page_entries": entries,
             "prior_coverage_by_line": [
                 {"line": "General Liability", "policy_no": "GL 7784120 25"},
                 {"line": "Automobile", "policy_no": "CA 7784121 25"}]}
    import services.pdf_service as ps
    ps._SCHEMA_CTX.schema = _acord_schema("ACORD_131")
    got = ps._dec_index_rating_value(_M1_FIELD, facts)
    assert got == "0.99", got


# =============================================================================
# P1 - the table block carries per-column cautions and the business-itself rule
# =============================================================================
def test_p1_the_phone_column_carries_the_contact_caution():
    """Run 6's one wrong cell: row A took the CONTACT's direct line. The
    clarification machinery existed for singles only - a column promoted into a
    table silently LOST its caution."""
    fields = _unmatched_from("ACORD_125", _I6_NAMED_INSURED_COLUMNS)
    prompt = _capture_gap_fill_prompt(fields, "ACORD_125")
    assert "named insured COMPANY's own business phone" in prompt
    assert "NEVER this value" in prompt


def test_p1_the_table_rule_forbids_the_business_itself_as_a_row():
    """The products grid's four-run fabrication pattern, addressed at the rule
    it keeps violating: the applicant's trade, revenue, headcounts and dates
    are not schedule entries of ANY table."""
    fields = _unmatched_from("ACORD_126", [
        "ProductAndCompletedOperations_ProductName",
        "ProductAndCompletedOperations_AnnualGrossSalesAmount",
        "ProductAndCompletedOperations_UnitCount",
    ])
    prompt = _capture_gap_fill_prompt(fields, "ACORD_126")
    assert "never the applicant's BUSINESS ITSELF" in prompt
    assert "Re-using" in prompt


# =============================================================================
# X1 - the audit fixes, 2 Sep 2026
# =============================================================================
def test_x1_the_loss_total_is_paid_not_incurred():
    """ACORD's tooltip: "the amount that has been PAID on all losses to date."
    The derivation used to sum paid + reserved and was pleased to reproduce the
    document's printed "TOTAL LOSSES $568,495" - which is TOTAL INCURRED. The
    same document prints TOTAL PAID $348,495. Reproducing a number the document
    prints is not evidence it belongs in the box."""
    from services.pdf_service import _resolve_loss_history_summary
    rows = [{"paid": "$91,000", "reserved_amount": "$145,000"},
            {"paid": "$38,400", "reserved_amount": "$0"},
            {"paid": "$0", "reserved_amount": "$75,000"}]
    assert _resolve_loss_history_summary(
        "LossHistory_TotalAmount_A", {"loss_history": rows}) == "$129,400"


def test_x1_losses_the_grid_cannot_print_are_disclosed_in_remarks():
    """The grid prints 3 rows; the document reported 5. The two dropped included
    a $212,880 hail loss - the largest in the package - and NOTHING on the form
    said so. Silent truncation of a loss run is the worst failure mode here: not
    a wrong value a broker can spot, a missing one they cannot."""
    from services.pdf_service import _resolve_loss_history_summary  # noqa: F401
    import services.pdf_service as ps
    schema = _acord_schema("ACORD_125")
    ps._SCHEMA_CTX.schema = schema
    rows = [{"date": f"0{i}/01/2025", "claim_number": f"C{i}", "paid": "$1,000"}
            for i in range(1, 6)]
    got = ps._resolve_loss_overflow_remark(
        "CommercialPolicy_RemarkText_A", {"loss_history": rows})
    assert got and "2 of 5" in got and "C4" in got and "C5" in got, got


def test_x1_a_schedule_within_capacity_leaves_remarks_alone():
    """GUARD - the disclosure fires ONLY when rows were actually dropped."""
    import services.pdf_service as ps
    ps._SCHEMA_CTX.schema = _acord_schema("ACORD_125")
    for n in (1, 2, 3):
        rows = [{"date": "01/01/2025", "claim_number": "C", "paid": "$1"}] * n
        assert ps._resolve_loss_overflow_remark(
            "CommercialPolicy_RemarkText_A", {"loss_history": rows}) is ps._SCHED_SKIP


def test_x1_the_grid_capacity_is_read_from_the_form_not_assumed():
    """GENERIC - capacity comes from the form's own schema, so a form with a
    different number of loss rows needs no change here."""
    from services.pdf_service import _loss_grid_capacity
    assert _loss_grid_capacity(_acord_schema("ACORD_125")) == 3
    assert _loss_grid_capacity({}) == 0


@pytest.mark.parametrize("value", [
    "www.verdantslopebuilders.com",
    "dostrander@verdantslopebuilders.com",
    "https://example.com/path",
    "verdantslopebuilders.com",
])
def test_x1_a_machine_token_is_never_recased(value):
    """A URL or an e-mail is an address for a MACHINE. The website and e-mail
    boxes are classed as "name", so the name title-caser printed
    `Www.verdantslopebuilders.com` on a filed ACORD 125. The local part of an
    e-mail is case-SENSITIVE per RFC 5321 - re-casing one can make it
    undeliverable."""
    from services.display_canonicalizer import canonicalize_for_field
    for field in ("NamedInsured_Primary_WebsiteAddress_A",
                  "NamedInsured_Contact_PrimaryEmailAddress_A",
                  "AdditionalInterest_FullName_A"):
        assert canonicalize_for_field(field, value) == value, (field, value)


def test_x1_a_dotted_initialism_keeps_its_case():
    """"N.A." is the designation of a US national bank. It was printing as
    "N.a." on a filed application."""
    from services.display_canonicalizer import canonicalize_for_field
    got = canonicalize_for_field("AdditionalInterest_FullName_A",
                                 "Bank of the Front Range, N.A.")
    assert got == "Bank Of The Front Range, N.A.", got


def test_x1_ordinary_names_and_addresses_still_canonicalize():
    """GUARD - the two rules above must not switch canonicalisation off."""
    from services.display_canonicalizer import canonicalize_for_field as c
    assert c("NamedInsured_FullName_A", "VERDANT SLOPE BUILDERS, LLC")         == "Verdant Slope Builders, LLC"
    assert c("NamedInsured_FullName_B", "halewood ridge framing, inc.")         == "Halewood Ridge Framing, Inc."
    assert c("NamedInsured_MailingAddress_LineOne_A", "9420 e costilla ave bldg 3")         == "9420 E Costilla Ave Bldg 3"


def test_x1_a_question_pairs_past_one_intervening_box():
    """ACORD 131's tail-coverage question sits ONE position from its own
    explanation - an EffectiveDate box named under a DIFFERENT root sits
    between, so no same-stem run forms and the third fallback cannot see it.
    Unpaired means rules 2/4/5 are OFF, and that box shipped an ORPHAN
    explanation about the wrong subject."""
    from services.pdf_service import _question_explanation_pairs
    pairs = _question_explanation_pairs(_acord_schema("ACORD_131"))
    hit = [q for q in pairs if "ACFCode" in q]
    assert hit, "the tail-coverage question is still unpaired"
    assert "TailCoverage" in pairs[hit[0]] and "Explanation" in pairs[hit[0]]


def test_x1_pairing_never_crosses_a_section_root():
    """THE structural second condition. Without it the same widening paired an
    ACORD 126 `CommercialInlandMarineProperty_*` field to a
    `GeneralLiabilityLineOfBusiness_*` explanation - the coincidental adjacency
    `_question_explanation_pairs`' own docstring exists to refuse. Pinned on the
    forms the widening actually touches; pre-existing distance-1 pairs on other
    forms are out of scope and unchanged."""
    from services.pdf_service import _question_explanation_pairs
    for form in ("ACORD_131", "ACORD_130", "ACORD_125"):
        for q, exp in _question_explanation_pairs(_acord_schema(form)).items():
            assert q.split("_", 1)[0] == exp.split("_", 1)[0], (form, q, exp)


def test_x1_the_widening_did_not_disturb_the_existing_pairs():
    """GUARD - measured before/after: only ACORD 131 moved, by exactly one."""
    from services.pdf_service import _question_explanation_pairs
    assert len(_question_explanation_pairs(_acord_schema("ACORD_125"))) == 30
    assert len(_question_explanation_pairs(_acord_schema("ACORD_126"))) == 37
    assert len(_question_explanation_pairs(_acord_schema("ACORD_131"))) == 26
