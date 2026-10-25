"""
Bulk schedule capture (Beta Report Figure 15 — "many vehicle detail questions").

Problem this solves
-------------------
ACORD forms carry repeating rows (vehicles, drivers, locations, class codes,
loss runs, ...). Before this module, `arq_service.generate_arq_questions` turned
EVERY empty repeating-row field into its own client question, ordinal-labelled
via `_group_label`/`_ordinal`. A single ACORD 127 produced ~140 "Please provide
the following details for this vehicle ... (141th vehicle)" cards — the exact
failure the client reported. The ordinal counted FIELDS, not vehicles, so the
number was wrong as well as unusable.

Design
------
The data model was already schedule-shaped: `pdf_service._SCHEDULE_REGISTRY`
binds each repeating ACORD field (e.g. `Vehicle_Year_B`) to a list-backed fact
(`auto_vin_schedule[1]["year"]`). Nothing about the stamping pipeline needed to
change — only the CAPTURE side. So this module:

  * declares, per list-backed fact, the client-facing shape of ONE row
    (`SCHEDULE_DEFS`: columns, types, dedup keys, labels);
  * collapses every repeating field of a given schedule into ONE question of
    `field_type == "schedule"` (see `arq_service`), rendered by the frontend as
    a single editable table with CSV/XLSX import;
  * validates rows (per-cell, per-row) and flags duplicates;
  * round-trips through the EXISTING answer pipeline by serialising rows to a
    JSON string under a reserved `schedule::<list_key>` answer key, so no
    database column, no new answer plumbing, and no change to how scalar
    answers behave.

On apply, rows are written straight back to `facts[list_key]` as a plain list —
which is exactly what `pdf_service._resolve_schedule_row` already reads (via
`_fv`, which transparently unwraps fact envelopes). The full list is always
retained in facts even when it is longer than the form has physical rows; see
`ROW_CAPACITY` / `overflow_count` for how that is surfaced rather than silently
dropped.

Everything here is pure Python with no LLM and no I/O, so it is cheap to call
on every question-generation pass and trivially unit-testable.
"""

from __future__ import annotations

import json
import logging
import re
from functools import lru_cache
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

# Reserved answer-key namespace. A questionnaire answer whose key starts with
# this prefix carries a JSON-encoded list of rows rather than a scalar string.
ANSWER_PREFIX = "schedule::"

# Number of physical repeating rows the ACORD AcroForms expose (A..N — see
# `pdf_service._ROW_LETTER_TO_IDX`). Rows beyond this are still stored in facts
# (lossless) but cannot be stamped onto the form itself.
ROW_CAPACITY = 14

# ── A table row keeps its identity through an edit (6 Oct 2026) ─────────────
# A table shows only its columns, and a save used to rebuild every row from
# those columns alone - so the LOC #, county, interest, revenue, employee
# counts, building values ... a document had put on a premises row were gone
# after any edit (Choice Electric: the producer's LOC # typed on the 125 was
# blanked by three location-table saves). Each row now travels with a hidden
# identity (`ROW_ID_KEY`, never a column) and a save MERGES the typed cells
# into the stored row it came from (`merge_saved_rows`). Only the schedules in
# MERGE_ON_SAVE carry it; the others keep the rebuild-from-columns behaviour.
ROW_ID_KEY = "_row_id"
# Vehicles and drivers joined 7 Oct 2026 (round 4): a vehicle row carries its
# class code, territory, garaging, cost new, use ... and a driver row its
# relationship, gender, MVR facts - none of them columns, all wiped by the old
# rebuild-from-columns save (17 of 17 live vehicles lost class code / territory
# on any edit). Same class as the location table's LOC # loss (Brent #14 / #23).
# The GL classification window joined 21 Oct 2026 (Brent 17 Oct item 6): a GL
# row carries its territory and subcontracted % - no columns, both kept.
# The loss table joined 21 Oct 2026 (lane C review): a claim row carries its
# claim number, total incurred and SUBROGATION code (ACORD 125 prints Y / N
# from it) - no columns, all wiped by a save, and the claims card now sends
# producers into that save (`claim_checks`).
MERGE_ON_SAVE = frozenset({"property_locations", "auto_vin_schedule", "auto_drivers",
                           "gl_class_code_schedule", "loss_history"})
# The stored row's own stable id, per schedule (consolidation issues it).
_STORED_ROW_ID_FIELD: Dict[str, str] = {"property_locations": "location_id"}
# A row a save carries with no usable hidden id (an import, an older copy of
# the table) is matched to a stored row by these identities, in order - each
# only when EVERY key is stated and the value names exactly one stored row AND
# exactly one typed row (two rows sharing a VIN identify nothing). The
# location table keeps its own street / LOC # / BLDG # rule (unchanged).
_MERGE_IDENTITIES: Dict[str, Tuple[Tuple[str, ...], ...]] = {
    "auto_vin_schedule": (("vin",),),
    "auto_drivers": (("license_number",), ("name", "dob")),
    "gl_class_code_schedule": (("location", "class_code"),),
    # A claim: its loss date and line, else those and its description (two
    # claims of one accident). The claim number is no column, so it cannot
    # identify a typed row.
    "loss_history": (("date", "line_of_business"), ("date", "line_of_business", "description")),
}
# A row whose every cell the person CLEARED (the stored row showed values, the
# save shows none) is deleted, not kept by its hidden id: a claim with no date,
# line, description or amounts left is not a claim the person kept (its claim
# number and incurred would print on alone). A row that showed nothing from the
# start still stays (a redacted or column-less row, as for every table).
_CLEARED_ROW_IS_DELETED = frozenset({"loss_history"})
# A hidden field derived from columns goes stale when a person changes them:
# the document's total incurred is its paid + reserve (+ expense), so a typed
# paid or reserve drops it rather than keep a total that no longer adds up.
_STALE_WHEN_CHANGED: Dict[str, Dict[str, Tuple[str, ...]]] = {
    "loss_history": {"amount": ("paid", "reserved_amount"),
                     "incurred": ("paid", "reserved_amount"),
                     "open": ("open_code",)},     # extraction's twin of the status cell
}

# "Unknown - follow up" (21 Oct 2026, Brent 17 Oct item 6: "allow producers to
# mark unknown information for follow-up rather than guess"). A row-level mark,
# never a column (it binds no ACORD box): a table that declares `follow_up`
# keeps it on each row it is ticked on. The row is saved; what it does not
# state stays a gap - the form prints nothing it does not have (the same key
# as `pdf_service._ROW_FOLLOW_UP_KEY`) and no score counts an unknown as an
# answer. A typed non-answer ("unknown", "TBD", "not sure") in such a table's
# cell is not stored: the cell is left blank and the row is marked instead.
FOLLOW_UP_KEY = "follow_up"
_ADDRESS_PART_KEYS = ("address_line1", "address_line2", "address_city",
                      "address_state", "address_zip")

# Hard safety bounds. A 143-vehicle fleet — the case in the bug report — fits
# comfortably; these exist to bound a malicious or runaway payload.
MAX_ROWS = 500
MAX_CELL_LEN = 200


# ---------------------------------------------------------------------------
# Column + schedule definitions
# ---------------------------------------------------------------------------

class Column(dict):
    """One cell definition. `dict` subclass so it serialises to JSON directly."""

    def __init__(
        self,
        key: str,
        label: str,
        type: str = "text",
        required: bool = False,
        placeholder: str = "",
        width: int = 0,
        producer_only: bool = False,
        options: Optional[List[str]] = None,
        units_by: Optional[dict] = None,
        evidence_only: bool = False,
    ):
        super().__init__(
            key=key, label=label, type=type, required=required,
            placeholder=placeholder, width=width,
            producer_only=producer_only,
        )
        # Suggested answers for a closed column (a renderer may offer them as a
        # pick list). Free text stays allowed - a document's own wording
        # ("NON-COMBUSTIBLE - LIGHT STEEL") is never refused for not being one.
        if options:
            self["options"] = list(options)
        # A column no ACORD box prints but the checks read (25 Oct 2026: the loss
        # table's first-made date, expense, incurred and claim number feed the
        # claims checks) - kept on the row, never discarded.
        if evidence_only:
            self["evidence_only"] = True
        # The unit an amount is in, read off another cell of the same row
        # (21 Oct 2026, the GL window: an exposure is dollars on a payroll /
        # sales / cost basis, square feet on an area basis) - {"column": key,
        # "units": {lower-case cell text: unit}}. Shown beside the cell only.
        if units_by:
            self["units_by"] = {"column": str(units_by.get("column") or ""),
                                "units": dict(units_by.get("units") or {})}


class ScheduleDef(dict):
    """Client-facing shape of one repeating schedule.

    `producer_only` (V1 H3, 2026-08-27): the WHOLE table is the producer's -
    it is never raised as a client question and never sent to the insured
    (core principle 5). The officers table is the live case: names are facts,
    but included / excluded is an insurance decision, and one table cannot
    split its audience by column. Default False - the four original tables
    are untouched.

    `row_capacity`: physical rows the ACORD form prints for THIS schedule.
    Defaults to the 14-row (A..N) convention; ACORD 130 prints only four
    officer rows, and an overflow notice counted against 14 would be wrong.

    Added 21 Oct 2026 for the GL classification window (Brent 17 Oct item 6);
    every default leaves the other tables exactly as they were:
      `follow_up`   - each row can be marked "Unknown - follow up" (FOLLOW_UP_KEY);
      `answers`     - facts this table ANSWERS: a card asking one opens the table
                      (`answer_routing.answer_mode`);
      `review_item` - the review shows every open item whose fix opens this
                      whole table as ONE item, this sentence when two or more fire
                      (`issue_registry._fold_one_item_tables`);
      `title` / `intro` - the fix window's own heading and the line under it;
      `restamp_derived` - a save after forms also re-stamps the boxes the stamper
                      DERIVES from these rows (`arq_service.save_session_schedule`).
    """

    def __init__(
        self,
        list_key: str,
        label: str,
        singular: str,
        columns: List[Column],
        dedup_keys: Tuple[str, ...] = (),
        scalar_key: Optional[str] = None,
        vin_decode: bool = False,
        producer_only: bool = False,
        row_capacity: int = ROW_CAPACITY,
        follow_up: bool = False,
        answers: Tuple[str, ...] = (),
        review_item: str = "",
        title: str = "",
        intro: str = "",
        restamp_derived: bool = False,
    ):
        super().__init__(
            list_key=list_key, label=label, singular=singular,
            columns=columns, dedup_keys=list(dedup_keys),
            scalar_key=scalar_key, vin_decode=vin_decode,
            producer_only=producer_only, row_capacity=row_capacity,
        )
        if follow_up:
            self["follow_up"] = True
        if answers:
            self["answers"] = list(answers)
        if review_item:
            self["review_item"] = review_item
        if title:
            self["title"] = title
        if intro:
            self["intro"] = intro
        if restamp_derived:
            self["restamp_derived"] = True


# ACORD 126's own rating-basis legend, printed beside the PREMIUM BASIS box:
# (S) GROSS SALES (P) PAYROLL (A) AREA (C) TOTAL COST (M) ADMISSIONS (U) UNIT
# (T) OTHER. Each word is one `pdf_service.rating_basis_code` reads into its
# letter (pinned by tests/test_build22_gl-window.py). Brent's list (17 Oct item
# 6) leads: Payroll, Gross Sales, Total Cost (his "Subcontractor Cost" - the
# cost of work sublet, which also reads as C), Area, Other; ACORD's other two
# are kept because the box takes them.
GL_RATING_BASES: Tuple[str, ...] = ("Payroll", "Gross Sales", "Total Cost", "Area",
                                    "Admissions", "Units", "Other")
# What an exposure is counted in, by its basis (a letter or a word).
_GL_EXPOSURE_UNITS: Dict[str, str] = {
    "payroll": "$", "p": "$", "gross sales": "$", "sales": "$", "s": "$",
    "total cost": "$", "subcontractor cost": "$", "cost": "$", "c": "$",
    "area": "sq ft", "a": "sq ft", "admissions": "admissions", "m": "admissions",
    "units": "units", "unit": "units", "u": "units",
}


# Column sets mirror the sub_keys actually bound in
# `pdf_service._SCHEDULE_REGISTRY`. Deliberately NOT collecting fields that have
# no ACORD binding — data captured with nowhere to land is a loose end, not a
# feature.
SCHEDULE_DEFS: Dict[str, ScheduleDef] = {
    "auto_vin_schedule": ScheduleDef(
        list_key="auto_vin_schedule",
        label="Vehicle schedule",
        singular="vehicle",
        vin_decode=True,
        dedup_keys=("vin",),
        columns=[
            Column("year",       "Year",       "year",  required=True, placeholder="2021", width=80),
            Column("make",       "Make",       "text",  required=True, placeholder="Ford", width=120),
            Column("model",      "Model",      "text",  required=True, placeholder="F-150", width=120),
            Column("vin",        "VIN",        "vin",   placeholder="1FTFW1ET5DFC10312", width=190),
            Column("body_type",  "Body type",  "text",  placeholder="Pickup", width=110),
            Column("gvw",        "GVW",        "text",  placeholder="6,500", width=90),
            # Covered-auto symbols (2026-08-07). Bound to the real ACORD 127
            # fields Vehicle_ComprehensiveSymbolCode / Vehicle_CollisionSymbolCode
            # - the only symbol boxes that form has. Optional on purpose: a
            # declarations page normally states ONE symbol per coverage for the
            # whole schedule, which pdf_service inherits into every row, so these
            # only need filling when a fleet genuinely varies by vehicle.
            # PRODUCER-ONLY from 2026-08-26. Master-plan 4.9 makes covered-auto
            # symbols a producer decision ("Producer: limits; symbols; coverage
            # structure"), and core principle 5 forbids asking the client to
            # perform insurance classification. There is now a dedicated
            # producer question (`auto_covered_symbols`), so leaving these
            # columns in the CLIENT's copy of the table was a second route to
            # the wrong audience. The producer still sees and fills them - the
            # flag is honoured only where the client's table is built
            # (`arq_routes.client_view`), so pre-loading and stamping are
            # unchanged.
            Column("comp_symbol", "Comp symbol",      "text", placeholder="7", width=110,
                   producer_only=True),
            Column("coll_symbol", "Collision symbol", "text", placeholder="7", width=125,
                   producer_only=True),
        ],
    ),
    "auto_drivers": ScheduleDef(
        list_key="auto_drivers",
        label="Driver schedule",
        singular="driver",
        dedup_keys=("name", "dob"),
        columns=[
            Column("name",             "Full name",        "text",    required=True, placeholder="Jane Smith", width=160),
            Column("dob",              "Date of birth",    "date",    placeholder="05/14/1985", width=120),
            Column("license_number",   "License #",        "text",    placeholder="D1234567", width=140),
            Column("license_state",    "License state",    "state",   placeholder="TX", width=95),
            Column("hire_date",        "Date hired",       "date",    placeholder="01/10/2020", width=120),
            Column("experience_years", "Years experience", "number",  placeholder="8", width=110),
        ],
    ),
    "property_locations": ScheduleDef(
        list_key="property_locations",
        label="Location schedule",
        singular="location",
        # `address_line2` IS A COLUMN, and it has to be (2026-09-01).
        # `rows_from_facts` rebuilds every row from the COLUMNS alone, and
        # `arq_service` writes the result back over `facts[list_key]` wholesale
        # - so a sub-field with no column is destroyed the first time anyone
        # opens the location table. That was harmless while `_parse_address`
        # left the unit designator inside line1; now that it lifts it onto line
        # two, omitting the column would DELETE every suite number from the
        # facts, and `*_PhysicalAddress_LineTwo` would stamp blank on ACORD
        # 125/130/133/140/160/28 after the first save.
        #
        # It is in `dedup_keys` for the same reason: without it, Suite 100 and
        # Suite 200 in one building are byte-identical rows, and the duplicate
        # detector tells the client their two premises are the same one.
        # Measured before the fix: `validate_rows` returned `duplicates: [1]`.
        #
        # ONE ROW PER BUILDING, numbered as ACORD numbers it (6 Oct 2026,
        # Choice Electric #14): LOC # is the premises, BLDG # the building at
        # it - one premises with two buildings is two rows sharing LOC # 1. The
        # COPE card ("N insured locations are missing construction type or
        # building/BPP value") opens THIS table, so the table carries those
        # columns; it used to offer a street, a city and nothing the card asked
        # for (the BUG-05 shape). Every column binds a live ACORD box
        # (`test_every_schedule_column_binds_to_a_live_acord_field`): LOC # /
        # BLDG # the 125 / 140 / 160 premises numbers, construction and year
        # the 140 / 160 building boxes, the two values the 160 limits (and the
        # 140 subject-of-insurance grid, which reads the same row keys).
        # The NUMBERING is the agency's - LOC # is "the producer assigned number
        # of the location" (ACORD 160) - so LOC # / BLDG # are producer-only:
        # stripped from the client's copy, and a client save never touches
        # them (`merge_saved_rows`).
        # The two numbers join the duplicate signature: two buildings at one
        # street are two rows, not a duplicate. The new columns sit AFTER the
        # address ones: a header-less spreadsheet imports positionally, and a
        # one-column list of addresses must still land in "Street address".
        dedup_keys=("address_line1", "address_line2", "address_city",
                    "location_number", "building_number"),
        columns=[
            Column("address_line1",          "Street address", "text",  required=True, placeholder="789 Commerce Dr", width=210),
            Column("address_line2",          "Suite / unit",   "text",  placeholder="Ste 400", width=110),
            Column("address_city",           "City",           "text",  placeholder="Houston", width=130),
            Column("address_state",          "State",          "state", placeholder="TX", width=90),
            Column("address_zip",            "ZIP",            "text",  placeholder="77001", width=100),
            Column("operations_description", "What happens here", "text", placeholder="Warehouse and dispatch", width=220),
            Column("location_number",        "LOC #",          "text",  placeholder="1", width=70,
                   producer_only=True),
            Column("building_number",        "BLDG #",         "text",  placeholder="1", width=70,
                   producer_only=True),
            # ACORD's own construction classes (the ConstructionCode tooltip).
            # The four COPE / value columns are NOT producer-only: binding them
            # makes the 140 / 160 building boxes part of this table, and the
            # client questionnaire used to ask "What is your building mainly made
            # of?" / "What year was your building originally built?" from exactly
            # those boxes - hiding the columns from the client would have dropped
            # the questions (measured on a two-premises 125 + 140 package). The
            # insured knows these per building; the table now asks them so.
            Column("construction_type",      "Construction",   "text",  placeholder="Frame", width=160,
                   options=["Frame", "Joisted Masonry", "Non-Combustible",
                            "Masonry Non-Combustible", "Modified Fire Resistive",
                            "Fire Resistive"]),
            Column("year_built",             "Year built",     "year",  placeholder="1998", width=90),
            Column("building_value",         "Building value", "currency", placeholder="$750,000", width=130),
            Column("bpp_value",              "BPP value",      "currency", placeholder="$75,000", width=120),
            # The rest of each building's COPE (7 Oct 2026, Choice Electric #18):
            # ACORD 140 requires roof material and protection class PER BUILDING
            # (its completeness gate) and the Carrier-Grade COPE card asks roof
            # year, sprinkler and protection class - a second building's values
            # had nowhere to go. Each binds its live 140 / 160 box (deferred, like
            # the columns above). PRODUCER-ONLY: the questionnaire classifies
            # every one of these boxes internal (never asked of the client), so
            # the client's copy of the table is exactly what it was.
            Column("roof_material",          "Roof material",  "text",  placeholder="Metal", width=130,
                   producer_only=True,
                   options=["Composition", "Metal", "Poured", "Slate", "Tile", "Wood Shake"]),
            Column("roof_year",              "Roof year",      "year",  placeholder="2015", width=90,
                   producer_only=True),
            Column("protection_class",       "Protection class", "text", placeholder="3", width=110,
                   producer_only=True),
            Column("sprinkler",              "Sprinkler %",    "percent", placeholder="100", width=100,
                   producer_only=True),
            # ACORD 125's per-location boxes (13 Oct 2026, Choice Electric #27):
            # each was a required box with no place to answer it before forms,
            # so run `ba7c709d` listed them only after generation - once per
            # building. A premises' revenue and staff are asked once, on its
            # first row; a later building at the same LOC # prints none of them
            # (`pdf_service._LOCATION_ONCE_SUBKEYS`) and repeats its city limits.
            # "No" to city limits means OUTSIDE, as extraction already reads it
            # (`pdf_service.city_limits_inside`). PRODUCER-ONLY: the client's
            # copy of the table is exactly what it was.
            Column("annual_revenue",         "Location revenue", "currency", placeholder="$1,200,000", width=135,
                   producer_only=True),
            Column("full_time_employees",    "Full-time staff", "number", placeholder="12", width=95,
                   producer_only=True),
            Column("part_time_employees",    "Part-time staff", "number", placeholder="3", width=95,
                   producer_only=True),
            Column("total_building_area",    "Building sq ft", "number", placeholder="8,500", width=110,
                   producer_only=True),
            Column("is_inside_city_limits",  "Inside city limits", "text", placeholder="Yes", width=120,
                   producer_only=True, options=["Yes", "No"]),
        ],
    ),
    "loss_history": ScheduleDef(
        list_key="loss_history",
        label="Loss history / claims",
        singular="claim",
        dedup_keys=("date", "description"),
        columns=[
            Column("date",             "Date of loss",  "date",     required=True, placeholder="03/15/2022", width=120),
            Column("line_of_business", "Line",          "text",     placeholder="General Liability", width=150),
            Column("description",      "What happened", "text",     required=True, placeholder="Slip and fall at job site", width=240),
            Column("paid",             "Amount paid",   "currency", placeholder="$8,500", width=125),
            Column("reserved_amount",  "Amount reserved", "currency", placeholder="$2,000", width=135),
            # ACORD 125's DATE OF CLAIM and CLAIM OPEN Y/N boxes (21 Oct 2026,
            # Brent's claims file - attachment C). Both were extracted from loss
            # runs and printed, yet a table save dropped them (no column), and an
            # imported claims list had nowhere to put its report date or status,
            # so the claims checks (`claim_checks`: a report date before the loss
            # date, none given, an open claim with no reserve) could not read
            # them. Appended LAST: a header-less list imports by position. "Open"
            # / "Closed" print Y / N (`pdf_service._yn_gate`), as the extracted
            # "O" / "C" already do.
            Column("claim_date",       "Date reported", "date",     placeholder="03/20/2022", width=120),
            Column("open_code",        "Open or closed", "text",    placeholder="Closed", width=115,
                   options=["Open", "Closed"]),
            # The claims checks' other fields (25 Oct 2026, live f575160b): their
            # card asked to correct "incurred $9,200 vs $9,300" and "no date first
            # made", and the table had no column for either - the card could not
            # be cleared from its own window. Appended LAST (position imports).
            # PRODUCER-ONLY (Z42 review A): carrier loss-run figures the claims
            # checks read - the insured's copy of the table asks what happened,
            # never the carrier's claim number, expense or first-made date.
            Column("first_made_date",  "Date first made", "date",   placeholder="03/18/2022", width=125,
                   evidence_only=True, producer_only=True),
            Column("expense",          "Expense",       "currency", placeholder="$500", width=110,
                   evidence_only=True, producer_only=True),
            Column("incurred",         "Total incurred", "currency", placeholder="$11,000", width=125,
                   evidence_only=True, producer_only=True),
            Column("claim_number",     "Claim #",       "text",     placeholder="CL-10234", width=120,
                   evidence_only=True, producer_only=True),
        ],
    ),
    # ── V1 H3 (client section 8.1) - WC exposure at the employee-group level ──
    # ONE table on the EXISTING `wc_class_codes` fact (Principle 1: the stamper,
    # the scorer, the ACORD 130 checklist and the class-code vote all read this
    # key). Column keys are the extraction row keys, so a row the model read
    # from a rating sheet and a row the insured typed are the same shape.
    #
    # The client's group = one ACORD 130 rating row: "Field Employees /
    # Roofing installation / 8 employees / $520,000 / CO". ACORD prints no
    # separate job-title box - its DutiesDescription tooltip asks for "the
    # classification description or a brief statement regarding the duties" -
    # so group and duties are ONE cell (owner 2026-08-27, Q25). Employee count
    # is full-time + part-time because those are the two boxes the form has
    # (Q24). The class code is the PRODUCER's column - core principle 5 - and
    # `rate` rides along producer-only so an extracted manual rate survives a
    # round trip through the table instead of being dropped by `rows_from_facts`.
    "wc_class_codes": ScheduleDef(
        list_key="wc_class_codes",
        label="Employee groups and payroll",
        singular="employee group",
        dedup_keys=("description", "state"),
        columns=[
            Column("description",         "Employee group and what they do", "text",
                   required=True, placeholder="Field employees - roofing installation", width=240),
            Column("full_time_employees", "Full-time",     "number",   placeholder="8", width=85),
            Column("part_time_employees", "Part-time",     "number",   placeholder="0", width=85),
            Column("payroll",             "Annual payroll", "currency", required=True,
                   placeholder="$520,000", width=130),
            Column("state",               "State",         "state",    placeholder="CO", width=80),
            Column("code",                "WC class code", "text",     placeholder="5551", width=110,
                   producer_only=True),
            Column("rate",                "Rate",          "text",     placeholder="12.10", width=90,
                   producer_only=True),
        ],
    ),
    # ── V1 H3 (client section 8.2) - owners / officers and their treatment ────
    # PRODUCER-ONLY, whole table: C4 routes `wc_officers` to the producer (4.4
    # "owner/officer inclusion/exclusion" is insurance judgment) and one table
    # cannot split its audience by row (Q27). The treatment cell is free text
    # read by `coverage_evidence.officer_treatment_code` - "Included" /
    # "Excluded" (or INC / EXC); anything else leaves the ACORD box blank and
    # the officer counted as unresolved by the 6.4 check. Four rows on the
    # form (Q26 / capacity).
    "wc_officers": ScheduleDef(
        list_key="wc_officers",
        label="Owners and officers",
        singular="owner or officer",
        dedup_keys=("name",),
        producer_only=True,
        row_capacity=4,
        columns=[
            Column("name",            "Full name",          "text",    required=True, placeholder="Jane Smith", width=170),
            Column("title",           "Title",              "text",    placeholder="President", width=120),
            Column("ownership_pct",   "Ownership %",        "percent", placeholder="50", width=100),
            Column("state",           "State",              "state",   placeholder="CO", width=80),
            Column("include_exclude", "Included / Excluded", "text",   placeholder="Included", width=130),
            # ACORD 130 prints these beside every officer and the form's own
            # note says an INCLUDED officer's remuneration must appear in the
            # rating section. Added 2026-08-27 (H3-D) so the producer can fill
            # what the model was previously inventing here from the group table.
            Column("duties",          "Duties",             "text",    placeholder="Estimating and sales", width=180),
            Column("remuneration",    "Remuneration",       "currency", placeholder="$85,000", width=125),
        ],
    ),
    # ── Brent 17 Oct item 6 (21 Oct 2026) - ONE GL classification window ──────
    # "Please combine the two existing GL pop-ups into one titled General
    # Liability Classification & Exposure Details." ONE table on the EXISTING
    # `gl_class_code_schedule` fact (never a parallel one): the extraction rows
    # are the prefill, the ACORD 126 schedule of hazards prints the rows
    # (`pdf_service._resolve_gl_hazard_row`), and both GL warnings read them
    # (`sqs_service.gl_class_codes_present` / `_dec_entries_state_payroll`).
    # Each column is a real 126 hazard box (`pdf_service._SCHEDULE_REGISTRY`);
    # the row's territory and subcontracted % ride along (MERGE_ON_SAVE).
    #   * Location - the package's premises (`columns_for`, "Location 1 - <street>",
    #     which the 126 LOC # reads as ACORD 125's number for it);
    #   * Classification - the account's own operations and the documents' own
    #     classifications, or any wording (Other);
    #   * GL class code - only a code a document prints is ever prefilled; never
    #     suggested (Brent: "do not assume the GL class code"); another line's
    #     code is refused at the cell ("do not substitute WC class codes");
    #   * Rating basis - ACORD 126's own legend; Annual exposure - the amount in
    #     the basis' unit.
    # PRODUCER-ONLY: rating classification is insurance judgment (core
    # principle 5) - never a client question. Three rows print on the 126; more
    # are kept and scored.
    "gl_class_code_schedule": ScheduleDef(
        list_key="gl_class_code_schedule",
        label="GL classifications",
        singular="classification",
        dedup_keys=("location", "class_code", "classification"),
        producer_only=True,
        row_capacity=3,
        follow_up=True,
        answers=("gl_class_codes_by_location",),
        review_item=("GL class codes and rating exposures are missing - complete "
                     "them for each operation and location."),
        title="General Liability Classification & Exposure Details",
        intro=("Enter each GL classification and its rating exposure, one row per "
               "operation and location. Pick a location or description from the "
               "list, or type your own (Other). Do not know a value? Leave it blank "
               "and tick Unknown - it stays open for follow-up."),
        restamp_derived=True,
        columns=[
            Column("location",        "Location",           "text",     width=210),
            Column("classification",  "Classification description", "text", width=230),
            Column("class_code",      "GL class code",      "code",     required=True, width=115),
            Column("premium_basis",   "Rating basis",       "text",     required=True,
                   placeholder="Payroll", width=135, options=list(GL_RATING_BASES)),
            Column("exposure_amount", "Annual exposure",    "currency", required=True,
                   placeholder="1,400,000", width=140,
                   units_by={"column": "premium_basis", "units": _GL_EXPOSURE_UNITS}),
        ],
    ),
}
# NOTE: only schedules with LIVE bindings in `pdf_service._SCHEDULE_REGISTRY`
# are defined here. The 2026-07-21 audit found wc_class_codes / wc_officers /
# underlying_policies / prior_coverage_by_line / inland_marine_items /
# additional_named_insureds bound to ZERO real schema fields; the two WC
# schedules had their real ACORD 130 names bound on 2026-08-15/16 and joined
# this table on 2026-08-27 (V1 H3). The other four are still unbound and still
# deliberately omitted rather than shipped as tables that quietly discard
# input. `tests/test_schedule_capture.py::test_every_schedule_column_binds_to_
# a_live_acord_field` is the guard.

# Curated `_FIELD_PREFIX_MAP` group labels (arq_service) → schedule list key.
# These cover questions generated from the curated prefix map rather than from a
# raw ACORD schema field, so both generation paths collapse identically.
GROUP_LABEL_TO_LIST_KEY: Dict[str, str] = {
    "vehicle":  "auto_vin_schedule",
    "driver":   "auto_drivers",
    "location": "property_locations",
    "claim":    "loss_history",
}


def get_def(list_key: str) -> Optional[ScheduleDef]:
    return SCHEDULE_DEFS.get(list_key)


def capacity_for(list_key: str) -> int:
    """Physical rows the form prints for this schedule (see `ScheduleDef`)."""
    defn = SCHEDULE_DEFS.get(list_key)
    if defn is None:
        return ROW_CAPACITY
    try:
        return int(defn.get("row_capacity") or ROW_CAPACITY)
    except (TypeError, ValueError):
        return ROW_CAPACITY


def is_producer_only(list_key: str) -> bool:
    """Whole-table producer ownership - never a client question, never sent."""
    defn = SCHEDULE_DEFS.get(list_key)
    return bool(defn and defn.get("producer_only"))


def client_rows(list_key: str, rows: Any) -> list:
    """The rows the CLIENT's copy of a table carries (7 Oct 2026): every
    producer-only column's VALUE removed, not only its spec - the client never
    sees LOC # / BLDG # / roof / protection class cells the agency filled. Every
    other key (the hidden row id included) stays, so a client save still merges
    into the stored rows (`merge_saved_rows` keeps producer-only cells by row
    identity). Never mutates `rows`."""
    defn = SCHEDULE_DEFS.get(list_key)
    if not isinstance(rows, list):
        return []
    hidden = {c.get("key") for c in ((defn or {}).get("columns") or [])
              if isinstance(c, dict) and c.get("producer_only")}
    if not hidden:
        return list(rows)
    return [{k: v for k, v in r.items() if k not in hidden} if isinstance(r, dict) else r
            for r in rows]


def answer_key(list_key: str) -> str:
    return f"{ANSWER_PREFIX}{list_key}"


def is_schedule_answer_key(key: str) -> bool:
    return isinstance(key, str) and key.startswith(ANSWER_PREFIX)


def list_key_from_answer_key(key: str) -> str:
    return key[len(ANSWER_PREFIX):] if is_schedule_answer_key(key) else ""


def schedule_list_key_for_field(field_name: str) -> Optional[str]:
    """Resolve a raw ACORD schema field (e.g. `Vehicle_Year_B`) to its list key.

    Delegates to `pdf_service`'s registry so detection can never drift from the
    stamping logic. Returns None when the field is not schedule-backed, or is
    schedule-backed by a list we do not (yet) capture as a table.
    """
    try:
        from services.pdf_service import _SCHED_ROW_RE, _SCHEDULE_REGISTRY
    except Exception as ex:  # pragma: no cover - defensive import guard
        logger.warning(f"schedule_capture: pdf_service import failed: {ex}")
        return None

    m = _SCHED_ROW_RE.match(field_name or "")
    if not m:
        return None
    base = m.group(1)
    defn = _SCHEDULE_REGISTRY.get(base)
    if defn is None:
        for prefix, d in _SCHEDULE_REGISTRY.items():
            if base == prefix or base.startswith(prefix + "_") or base.endswith("_" + prefix):
                defn = d
                break
    if defn is None:
        return None
    return defn.list_key if defn.list_key in SCHEDULE_DEFS else None


@lru_cache(maxsize=64)
def _schedules_on_form_from_disk(form_id: str) -> frozenset:
    import json as _json
    import os as _os
    from services.form_instances import base_form_id
    form_id = base_form_id(form_id)     # a form's second copy reads its form's schema
    path = _os.path.join(
        _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))),
        "forms_schemas", f"{form_id}_schema.json",
    )
    try:
        with open(path, "r", encoding="utf-8") as fh:
            schema = _json.load(fh)
    except Exception as exc:                                  # noqa: BLE001
        logger.warning("schedule_capture: schema unavailable for %s - %s", form_id, exc)
        return frozenset()
    return _schedules_in_schema(schema)


def _schedules_in_schema(schema: Any) -> frozenset:
    if not isinstance(schema, dict):
        return frozenset()
    found = set()
    for field_name in schema:
        if binds_a_capturable_column(field_name):
            list_key = schedule_list_key_for_field(field_name)
            if list_key:
                found.add(list_key)
    return frozenset(found)


def schedules_on_form(form_id: str, schema: Any = None) -> frozenset:
    """Which capture tables does THIS form physically carry?

    Answered from the form's own schema, so it states a property of the FORM
    rather than of one submission. `_partition_schedule_fields` previously had
    to infer this from which boxes happened to be blank, which fails in exactly
    the case that matters: when gap fill has written something into every
    identity column, the schedule looks complete and the client is never offered
    the table (BUG-07 companion defect, live 2026-09-07 - a package with no
    fleet at all was offered no vehicle table).

    Measured across the 17 schemas:
      ACORD_127 -> auto_vin_schedule, auto_drivers
      ACORD_125 -> property_locations, loss_history
      ACORD_130 -> property_locations, wc_class_codes, wc_officers, loss_history
      ACORD_131 -> property_locations, loss_history
      ACORD_133 -> property_locations, auto_drivers
      ACORD_25  -> NOTHING (a certificate carries no schedule), which is what
                   keeps the 2026-08-26 C4 fix closed structurally rather than
                   by a name check.
    """
    if isinstance(schema, dict) and schema:
        return _schedules_in_schema(schema)
    # A form's second copy ("ACORD_131__excess") carries its form's schema.
    from services.form_instances import base_form_id
    return _schedules_on_form_from_disk(base_form_id(str(form_id or "")))


def binds_a_capturable_column(field_name: str) -> bool:
    """Is this field an EXACT registry binding, i.e. a real column of the table?

    THE LOOSE PREFIX FALLBACK ABOVE IS WHY THIS EXISTS. It claims any field
    whose base merely STARTS WITH a registry prefix, and ACORD reuses those
    prefixes for things that are not schedule rows at all. Measured 2026-08-26
    on the live C4 run:

      * ACORD 131 - `Vehicle_CombinedSingleLimit_EachAccidentAmount_A` and
        `Vehicle_BodilyInjury_PerAccidentLimitAmount_A` are the UMBRELLA's
        underlying-limit boxes, not a fleet;
      * ACORD 25  - `Vehicle_InsurerLetterCode_A`, `Vehicle_AnyAutoIndicator_A`
        are certificate coverage boxes, not a fleet.

    Both forms therefore raised "Please list the vehicles to be insured" at the
    client, on forms that have no vehicle schedule to fill.

    The loose fallback is DELIBERATELY LEFT INTACT - ACORD 127 resolves 268
    genuine vehicle fields through it, so removing it would break the real
    schedule. This predicate is the separate question the caller actually needs:
    *does this form carry a column the client could type into?* An exact
    registry hit is that, and nothing else is.
    """
    if not field_name:
        return False
    try:
        from services.pdf_service import _SCHED_ROW_RE, _SCHEDULE_REGISTRY
    except Exception:                                         # noqa: BLE001
        return False                                          # fail closed
    m = _SCHED_ROW_RE.match(field_name)
    if not m:
        return False
    defn = _SCHEDULE_REGISTRY.get(m.group(1))
    return bool(defn and defn.list_key in SCHEDULE_DEFS)


# ---------------------------------------------------------------------------
# VIN
# ---------------------------------------------------------------------------

# ISO 3779: 17 characters, and I / O / Q are never used (they are too easily
# confused with 1 / 0). Deliberately NOT enforcing the check digit — imported
# and pre-1981 VINs legitimately fail it, and rejecting a real vehicle is worse
# than accepting a typo the underwriter will catch.
_VIN_RE = re.compile(r"^[A-HJ-NPR-Z0-9]{17}$")


def normalize_vin(raw: Any) -> str:
    return re.sub(r"[\s\-]", "", str(raw or "")).upper()


def is_valid_vin(raw: Any) -> bool:
    return bool(_VIN_RE.match(normalize_vin(raw)))


# ---------------------------------------------------------------------------
# Row validation
# ---------------------------------------------------------------------------

_YEAR_RE = re.compile(r"^(19|20)\d{2}$")
_DATE_RE = re.compile(r"^\d{1,2}/\d{1,2}/\d{4}$|^\d{4}-\d{2}-\d{2}$")
_STATE_RE = re.compile(r"^[A-Za-z]{2}$")
_NUMERIC_RE = re.compile(r"^\d+(\.\d+)?$")
_COUNT_RE = re.compile(r"^\d+$")
_CODE_DIGITS_RE = re.compile(r"\d{3,}")


def _is_marked(raw: Any) -> bool:
    """A row mark as the table sends it (a checkbox) - True / "true" / "yes" / 1."""
    if isinstance(raw, bool):
        return raw
    return str(raw or "").strip().lower() in ("true", "yes", "y", "1", "on")


def _is_non_answer(col: dict, value: str) -> bool:
    """A cell that says only "I don't know" (21 Oct 2026, the GL window): the
    whole cell is a placeholder ("unknown", "TBD", "N/A" -
    `answer_semantics.is_placeholder_text`, the one door for "carries no
    information"), or - in a cell that takes a code, an amount, a date or one of
    its offered choices, never prose - a short uncertainty with no figure ("not
    sure", "need to check", "will follow up"). A description is judged by the
    placeholder test only: "Waiting room services" is a classification."""
    v = str(value or "").strip()
    if not v:
        return False
    try:
        from services.answer_semantics import _UNCERTAIN_RE, is_placeholder_text
    except Exception:                                         # noqa: BLE001
        return False
    if is_placeholder_text(v):
        return True
    closed = col.get("options") or col.get("type") in (
        "code", "currency", "percent", "number", "year", "date", "state", "vin")
    return bool(closed and len(v.split()) <= 5 and not re.search(r"\d", v)
                and _UNCERTAIN_RE.search(v))


def _cell_value(raw: Any) -> Any:
    """A True / False row value (extraction writes city limits that way) shows
    as the Yes / No its column offers, never "True"."""
    if isinstance(raw, bool):
        return "Yes" if raw else "No"
    return raw


def _clean_cell(raw: Any) -> str:
    """Strip markup and clamp length. Mirrors `arq_routes._sanitize_str`."""
    if raw is None:
        return ""
    val = re.sub(r"<[^>]*>", "", str(raw))
    return val.strip()[:MAX_CELL_LEN]


def validate_cell(col: dict, value: str) -> str:
    """Return an error message for one cell, or "" when it is acceptable.

    An empty non-required cell is always acceptable: a partially known fleet is
    better captured than refused. Only REQUIRED emptiness and genuinely
    malformed values are reported.
    """
    val = (value or "").strip()
    ctype = col.get("type", "text")

    if not val:
        return f"{col['label']} is required" if col.get("required") else ""

    if ctype == "vin":
        if not is_valid_vin(val):
            return "VIN must be 17 characters (letters/numbers, no I, O or Q)"
    elif ctype == "year":
        if not _YEAR_RE.match(val):
            # Must state the rule `_YEAR_RE` actually enforces (1900-2099).
            # "4-digit year" rejected 2122 while calling it not-four-digits.
            return f"{col['label']} must be between 1900 and 2099"
    elif ctype == "date":
        if not _DATE_RE.match(val):
            return f"{col['label']} must be MM/DD/YYYY"
    elif ctype == "state":
        if not _STATE_RE.match(val):
            return f"{col['label']} must be a 2-letter state code"
    elif ctype in ("currency", "percent"):
        stripped = val.replace("$", "").replace(",", "").replace("%", "").strip()
        if not _NUMERIC_RE.match(stripped):
            return f"{col['label']} must be a number"
    elif ctype == "number":
        # A count (employees per group). Whole number only - "8", "1,200".
        if not _COUNT_RE.match(val.replace(",", "").strip()):
            return f"{col['label']} must be a whole number"
    elif ctype == "code":
        # A rating class code (the GL window, 21 Oct 2026): its digits - "91580",
        # "GL 91580" - never a word ("Electrical"), which no rater can read.
        if not _CODE_DIGITS_RE.search(val):
            return f"{col['label']} must be the class code's number"
    return ""


def _dedup_signature(defn: ScheduleDef, row: dict) -> Optional[str]:
    """Identity of a row for duplicate detection, or None when unidentifiable.

    ALL of the schedule's dedup keys form one composite signature, and a row
    with none of them populated is not compared at all. Composite rather than
    first-key-wins because a false positive (telling someone two genuinely
    different vehicles are the same) is far more damaging than a false negative:
    a missed duplicate is a cosmetic annoyance, a wrongly-merged vehicle is lost
    coverage. Vehicles dedup on VIN alone, which is already exact.
    """
    parts = []
    populated = False
    for key in defn.get("dedup_keys") or []:
        raw = str(row.get(key) or "").strip()
        if raw:
            populated = True
        norm = normalize_vin(raw) if key == "vin" else re.sub(r"\s+", " ", raw).upper()
        parts.append(f"{key}={norm}")
    if not populated:
        return None
    return "|".join(parts)


def _as_shown(rows: Any) -> Tuple[Dict[str, dict], List[dict]]:
    """`shown` rows by their hidden id, and the ones that carry none."""
    by_id: Dict[str, dict] = {}
    bare: List[dict] = []
    for r in rows if isinstance(rows, list) else []:
        if not isinstance(r, dict):
            continue
        rid = _clean_cell(r.get(ROW_ID_KEY))
        if rid:
            by_id.setdefault(rid, r)
        else:
            bare.append(r)
    return by_id, bare


def validate_rows(list_key: str, rows: Any, shown: Optional[list] = None) -> Tuple[List[dict], dict]:
    """Clean + validate a schedule.

    Returns `(clean_rows, report)`. Rows are ALWAYS returned (validation is
    advisory, never destructive) so a client can save a partially-complete fleet
    and come back to it — matching how scalar questionnaire answers behave.

    `shown` - the rows as the table SHOWED them (`rows_from_facts`). In a table
    with the "Unknown - follow up" mark, a typed non-answer is the mark - but a
    cell left exactly as the table showed it was not typed by this person: a
    document row's "N/A" is kept as it is and marks nothing (review of 21 Oct
    2026 - serving a stored table, or saving another row, used to tick the mark
    on it and delete its value). A row is matched by its hidden id, else (a
    seeded row, which has none) by identical cells. Serving passes the rows it
    serves. None: every non-answer is the mark (a fresh import).

    report = {
        "errors":     {row_index: {col_key: message}},
        "duplicates": [row_index, ...],       # 2nd+ occurrence of a signature
        "row_count":  int,
        "overflow":   int,                    # rows beyond ROW_CAPACITY
        "truncated":  bool,                   # rows dropped by MAX_ROWS
    }
    """
    defn = SCHEDULE_DEFS.get(list_key)
    if defn is None:
        return [], {"errors": {}, "duplicates": [], "row_count": 0,
                    "overflow": 0, "truncated": False}

    if isinstance(rows, str):
        try:
            rows = json.loads(rows)
        except Exception:
            rows = []
    if not isinstance(rows, list):
        rows = []

    truncated = len(rows) > MAX_ROWS
    rows = rows[:MAX_ROWS]

    columns = defn["columns"]
    clean_rows: List[dict] = []
    errors: Dict[int, Dict[str, str]] = {}
    seen: Dict[str, int] = {}
    duplicates: List[int] = []
    _col_keys = [c["key"] for c in columns]
    _shown_by_id, _shown_bare = _as_shown(shown) if defn.get("follow_up") else ({}, [])

    def _shown_row(raw_row: dict) -> Optional[dict]:
        rid = _clean_cell(raw_row.get(ROW_ID_KEY))
        if rid:
            return _shown_by_id.get(rid)
        cells = [_clean_cell(raw_row.get(k)) for k in _col_keys]
        return next((s for s in _shown_bare
                     if [_clean_cell(s.get(k)) for k in _col_keys] == cells), None)

    for idx, raw_row in enumerate(rows):
        # Accept a bare string for scalar schedules (additional named insureds)
        # so an imported one-column CSV round-trips without special handling.
        if not isinstance(raw_row, dict):
            scalar_key = defn.get("scalar_key") or columns[0]["key"]
            raw_row = {scalar_key: raw_row}

        row: Dict[str, str] = {}
        row_errors: Dict[str, str] = {}
        # "Unknown - follow up" (a table that declares it, FOLLOW_UP_KEY): the
        # mark rides on the row; a typed non-answer is the mark, not a value -
        # never a cell left as the table showed it (`shown`, above).
        _follow = bool(defn.get("follow_up")) and _is_marked(raw_row.get(FOLLOW_UP_KEY))
        _was = _shown_row(raw_row) if (_shown_by_id or _shown_bare) else None
        for col in columns:
            val = _clean_cell(raw_row.get(col["key"]))
            if col["type"] == "vin" and val:
                val = normalize_vin(val)
            if (defn.get("follow_up") and val and _is_non_answer(col, val)
                    and not (_was is not None and _clean_cell(_was.get(col["key"])) == val)):
                val = ""
                _follow = True
            row[col["key"]] = val
            msg = validate_cell(col, val)
            if msg:
                row_errors[col["key"]] = msg

        # The hidden row identity (MERGE_ON_SAVE schedules) rides along, never
        # validated. A row that has one is an EXISTING row the person kept - it
        # is never dropped as blank, even when every cell they can see is empty
        # (a redacted street, the client's copy without the agency's columns).
        _rid = _clean_cell(raw_row.get(ROW_ID_KEY))[:40] if list_key in MERGE_ON_SAVE else ""

        # A row where the user typed nothing at all is dropped silently rather
        # than reported as N required-field errors (trailing blank rows are a
        # normal artifact of both the table UI and spreadsheet exports).
        if not any(row.values()) and not _rid:
            continue
        if _rid:
            row[ROW_ID_KEY] = _rid
        if _follow:
            row[FOLLOW_UP_KEY] = True

        sig = _dedup_signature(defn, row)
        if sig is not None:
            if sig in seen:
                duplicates.append(len(clean_rows))
            else:
                seen[sig] = len(clean_rows)

        if row_errors:
            errors[len(clean_rows)] = row_errors
        clean_rows.append(row)

    return clean_rows, {
        "errors":     {str(k): v for k, v in errors.items()},
        "duplicates": duplicates,
        "row_count":  len(clean_rows),
        "overflow":   max(0, len(clean_rows) - capacity_for(list_key)),
        "truncated":  truncated,
    }


def rows_for_facts(list_key: str, rows: List[dict]) -> List[Any]:
    """Shape validated rows for `facts[list_key]`.

    Scalar schedules (whose `_SCHEDULE_REGISTRY` entry has `sub_key is None`)
    store plain strings, everything else stores dicts — matching exactly what
    `pdf_service._resolve_schedule_row` expects to read back.
    """
    defn = SCHEDULE_DEFS.get(list_key)
    if defn is None:
        return []
    scalar_key = defn.get("scalar_key")
    if scalar_key:
        return [str(r.get(scalar_key, "")) for r in rows if str(r.get(scalar_key, "")).strip()]
    if list_key == "wc_class_codes":
        # Client 8.3 "normalize known formatting" - the same tidy-up the merge
        # tail applies to extracted rows, so a producer typing "5551 Roofing"
        # into the code column gets the code in the code box.
        try:
            from services.coverage_evidence import normalize_wc_class_row
            rows = [normalize_wc_class_row(dict(r)) for r in rows]
        except Exception:                                     # noqa: BLE001
            pass
    # The hidden row identity is a property of the TABLE, never a fact.
    return [{k: v for k, v in r.items() if k != ROW_ID_KEY} if isinstance(r, dict) else r
            for r in rows]


# ── Who typed this table (audit G8, 5 Oct 2026) ─────────────────────────────
# A saved schedule is a bare list - no envelope, so nothing says a PERSON typed
# it, and a pre-form re-run rebuilt it from the documents (or, for a Drive Other
# Car package, deleted it). Each human save records its source and a
# fingerprint of the rows it wrote under `facts[HUMAN_SCHEDULES_KEY]`; a re-run
# keeps the stored rows while they still match that fingerprint (anything
# later written over them - a document re-merge - is no longer the person's).
HUMAN_SCHEDULES_KEY = "_human_schedules"


def rows_fingerprint(rows: Any) -> str:
    import hashlib
    try:
        blob = json.dumps(rows, sort_keys=True, default=str)
    except Exception:                                         # noqa: BLE001
        blob = repr(rows)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:16]


def _bare_rows(raw: Any) -> Optional[list]:
    if isinstance(raw, dict) and "value" in raw:
        raw = raw.get("value")
    return raw if isinstance(raw, list) else None


def mark_human_rows(facts: dict, list_key: str, source: str) -> None:
    """Record that a person (`producer` / `client_arq`) saved `facts[list_key]`."""
    if not isinstance(facts, dict) or list_key not in SCHEDULE_DEFS:
        return
    rows = _bare_rows(facts.get(list_key))
    held = dict(facts.get(HUMAN_SCHEDULES_KEY) or {})
    if rows:
        held[list_key] = {"source": str(source or "producer"), "fingerprint": rows_fingerprint(rows)}
    else:
        held.pop(list_key, None)
    facts[HUMAN_SCHEDULES_KEY] = held


def human_rows(facts: Any, list_key: str) -> Tuple[Optional[list], Optional[str]]:
    """(the rows a person saved, their source) while `facts[list_key]` still
    holds exactly what they saved; (None, None) otherwise."""
    if not isinstance(facts, dict):
        return None, None
    mark = (facts.get(HUMAN_SCHEDULES_KEY) or {}).get(list_key)
    rows = _bare_rows(facts.get(list_key))
    if not isinstance(mark, dict) or not rows:
        return None, None
    if mark.get("fingerprint") != rows_fingerprint(rows):
        return None, None
    return list(rows), str(mark.get("source") or "producer")


def refresh_human_mark(facts: dict, list_key: str, source: str) -> None:
    """Re-fingerprint a person-saved table after a writer changed its rows.

    Any writer of a schedule fact must call this (or `mark_human_rows`):
    otherwise the stored fingerprint no longer matches and the next pre-form
    re-run treats the person's table as the documents' and rebuilds it (the
    per-location own / rent answer did exactly that - 5 Oct audit hole). An
    existing mark keeps its source; a table nobody marked yet becomes
    `source`'s, because a person has now written on it."""
    if not isinstance(facts, dict):
        return
    held = (facts.get(HUMAN_SCHEDULES_KEY) or {}).get(list_key)
    src = (held or {}).get("source") if isinstance(held, dict) else None
    mark_human_rows(facts, list_key, src or source)


def _stored_row_id(list_key: str, item: Any, position: int) -> str:
    """The identity a stored row travels with in the table: its own stable id
    (`location_id`), else its position in the stored list."""
    field = _STORED_ROW_ID_FIELD.get(list_key)
    rid = str((item or {}).get(field) or "").strip() if (field and isinstance(item, dict)) else ""
    return rid or f"#{position}"


def _compose_address(row: dict) -> str:
    line1 = " ".join(p for p in (str(row.get("address_line1") or "").strip(),
                                 str(row.get("address_line2") or "").strip()) if p)
    tail = " ".join(p for p in (str(row.get("address_state") or "").strip(),
                                str(row.get("address_zip") or "").strip()) if p)
    return ", ".join(p for p in (line1, str(row.get("address_city") or "").strip(), tail) if p)


def _identity_norm(key: str, raw: Any) -> str:
    """One identity cell, compared loosely on spelling only: a VIN as
    `normalize_vin`, anything else upper-cased with every non-alphanumeric
    removed ("D-123 456" == "d123456", "Jane  Smith" == "JANE SMITH")."""
    cell = _clean_cell(raw)
    if not cell:
        return ""
    if key == "vin":
        return normalize_vin(cell)
    return re.sub(r"[^0-9A-Z]", "", cell.upper())


def merge_saved_rows(list_key: str, stored: Any, typed: List[dict],
                     source: str = "producer", facts: Optional[dict] = None) -> List[Any]:
    """The stored schedule after a person saved `typed` (validated rows).

    Each typed row is matched to the stored row it came from - by its hidden
    identity, else (an older copy of the table, an import) by identical cells,
    else by the schedule's own unique identity (`_MERGE_IDENTITIES`: a VIN; a
    licence number, then name + date of birth), else by a UNIQUE street
    signature, else by a unique LOC # / BLDG # pair - and only the cells the
    person changed are written onto it. Fields the table has no column for
    (county, interest, revenue, employees, areas, the document's own address
    string; a vehicle's class code, territory, garaging, cost new; a driver's
    relationship, gender ...) are never dropped. A stored row no typed row
    claims was deleted; a typed row that claims none is new.

    A CLIENT save never writes a producer-only column - the client's copy of
    the table does not show those columns, so their blank cells are not an
    answer. Schedules outside MERGE_ON_SAVE keep `rows_for_facts`.

    A stored row the table does not SHOW (`_shown_row_indices` with `facts`: the
    GL window's policy-level lines and another line's classes) was never on the
    person's screen, so no save claims, changes or deletes it - it is kept, after
    the rows the save wrote (21 Oct 2026). The "Unknown - follow up" mark of a
    table that declares it is written by a producer save, ticked or cleared."""
    defn = SCHEDULE_DEFS.get(list_key)
    if defn is None:
        return []
    if list_key not in MERGE_ON_SAVE:
        return rows_for_facts(list_key, typed)
    stored_rows = [dict(r) for r in (_bare_rows(stored) or []) if isinstance(r, dict)]
    _shown = _shown_row_indices(list_key, stored_rows, facts)
    hidden = sorted(set(range(len(stored_rows))) - set(_shown)) if _shown is not None else []
    all_keys = [c["key"] for c in defn["columns"]]
    edit_keys = [c["key"] for c in defn["columns"]
                 if source == "producer" or not c.get("producer_only")]
    _vin_cols = {c["key"] for c in defn["columns"] if c.get("type") == "vin"}

    def _view_cell(k: str, raw: Any) -> str:
        # The stored cell as the TABLE showed it (`validate_rows` cleans a VIN
        # the same way), so an untouched cell never reads as an edit.
        cell = _clean_cell(raw)
        return normalize_vin(cell) if (k in _vin_cols and cell) else cell

    views = [{k: _view_cell(k, r.get(k)) for k in all_keys} for r in stored_rows]
    by_id: Dict[str, int] = {}
    for i, r in enumerate(stored_rows):
        by_id.setdefault(_stored_row_id(list_key, r, i), i)
    claimed: set = set(hidden)           # never shown: no save claims them
    identities = _MERGE_IDENTITIES.get(list_key, ())

    def _unique(cands: List[int]) -> Optional[int]:
        return cands[0] if len(cands) == 1 else None

    def _ident(keys: Tuple[str, ...], row: dict) -> Optional[str]:
        vals = [_identity_norm(k, row.get(k)) for k in keys]
        return "|".join(vals) if all(vals) else None

    typed_ident_counts: Dict[Tuple[Tuple[str, ...], str], int] = {}
    for t in typed or []:
        if isinstance(t, dict):
            for keys in identities:
                sig = _ident(keys, t)
                if sig is not None:
                    typed_ident_counts[(keys, sig)] = typed_ident_counts.get((keys, sig), 0) + 1

    def _by_identity(t: dict, free: List[int]) -> Optional[int]:
        for keys in identities:
            sig = _ident(keys, t)
            if sig is None or typed_ident_counts.get((keys, sig), 0) != 1:
                continue
            hit = _unique([i for i in free if _ident(keys, views[i]) == sig])
            if hit is not None:
                return hit
        return None

    out: List[dict] = []
    for t in typed or []:
        if not isinstance(t, dict):
            continue
        rid = str(t.get(ROW_ID_KEY) or "").strip()
        idx = by_id.get(rid) if rid else None
        if idx in claimed:
            idx = None
        free = [i for i in range(len(stored_rows)) if i not in claimed]
        if idx is not None and identities and rid.startswith("#"):
            # A POSITIONAL id (a schedule with no stable row id) points at
            # whatever row now sits there - a stale tab after the list was
            # re-ordered. A unique identity naming a different stored row
            # outranks the position.
            other = _by_identity(t, free)
            if other is not None and other != idx:
                idx = other
        if idx is None:
            idx = _unique([i for i in free
                           if all(views[i][k] == str(t.get(k) or "").strip() for k in edit_keys)])
        if idx is None and identities:
            idx = _by_identity(t, free)
        if idx is None:
            sig = _dedup_signature({"dedup_keys": [k for k in defn.get("dedup_keys") or []
                                                   if k in _ADDRESS_PART_KEYS]}, t)
            if sig is not None:
                idx = _unique([i for i in free if _dedup_signature(
                    {"dedup_keys": [k for k in defn.get("dedup_keys") or []
                                    if k in _ADDRESS_PART_KEYS]}, views[i]) == sig])
        if idx is None:
            num = (str(t.get("location_number") or "").strip(),
                   str(t.get("building_number") or "").strip())
            if all(num):
                idx = _unique([i for i in free
                               if (views[i].get("location_number"), views[i].get("building_number")) == num])
        if (idx is not None and list_key in _CLEARED_ROW_IS_DELETED
                and not any(str(t.get(k) or "").strip() for k in edit_keys)
                and any(views[idx][k] for k in edit_keys)):
            claimed.add(idx)             # every cell cleared: the row is deleted
            continue
        base = stored_rows[idx] if idx is not None else {}
        merged = dict(base)
        address_moved = idx is None
        _stale = _STALE_WHEN_CHANGED.get(list_key, {})
        for k in edit_keys:
            new = str(t.get(k) or "").strip()
            old = views[idx][k] if idx is not None else ""
            if new == old:
                continue
            merged[k] = new or None
            for derived, sources in _stale.items():
                # A derived total the person can see as a column is theirs to
                # keep or change - never dropped because paid moved beside it.
                if k in sources and derived not in edit_keys:
                    merged.pop(derived, None)
            if k in _ADDRESS_PART_KEYS:
                address_moved = True
        if address_moved:
            composed = _compose_address(merged)
            if composed or idx is not None:
                merged["address"] = composed or None
        if defn.get("follow_up") and source == "producer":
            if _is_marked(t.get(FOLLOW_UP_KEY)):
                merged[FOLLOW_UP_KEY] = True
            else:
                merged.pop(FOLLOW_UP_KEY, None)
        merged.pop(ROW_ID_KEY, None)
        if idx is not None:
            claimed.add(idx)
        out.append(merged)
    # The rows the table never showed, as they were (see the docstring).
    out.extend(dict(stored_rows[i]) for i in hidden)

    id_field = _STORED_ROW_ID_FIELD.get(list_key)
    if id_field:
        # A deleted row's id is never re-issued: a stale copy of the table that
        # still names it must not land on a different, new row.
        used = {str(r.get(id_field)) for r in out + stored_rows if r.get(id_field)}
        n = 1
        for r in out:
            if r.get(id_field):
                continue
            while f"L{n}" in used:
                n += 1
            r[id_field] = f"L{n}"
            used.add(f"L{n}")
    dropped = len(stored_rows) - len(claimed)
    if dropped:
        logger.info("merge_saved_rows: %s - %d stored row(s) removed by the save", list_key, dropped)
    return out


def rows_from_facts(list_key: str, facts: dict) -> List[dict]:
    """Read `facts[list_key]` back into table rows (inverse of `rows_for_facts`).

    Tolerates the fact-envelope shape (`{"value": [...]}`) the extraction layer
    may produce, and normalises scalar lists back into single-column rows.
    """
    defn = SCHEDULE_DEFS.get(list_key)
    if defn is None:
        return []

    raw = (facts or {}).get(list_key)
    if isinstance(raw, dict) and "value" in raw:
        raw = raw.get("value")
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except Exception:
            raw = []
    if not isinstance(raw, list):
        raw = []

    scalar_key = defn.get("scalar_key") or defn["columns"][0]["key"]
    # The rows this table shows (21 Oct 2026, the GL window: never another
    # line's class or the carrier's policy-level line) - the others stay in the
    # fact untouched (`merge_saved_rows`). A row keeps its stored position id.
    _shown = _shown_row_indices(list_key, raw[:MAX_ROWS], facts)
    shown = set(_shown) if _shown is not None else None
    out: List[dict] = []
    for _pos, item in enumerate(raw[:MAX_ROWS]):
        if shown is not None and _pos not in shown:
            continue
        if isinstance(item, dict):
            row = {c["key"]: _clean_cell(_cell_value(item.get(c["key"]))) for c in defn["columns"]}
            if list_key in MERGE_ON_SAVE:
                row[ROW_ID_KEY] = _stored_row_id(list_key, item, _pos)
            if list_key == "wc_officers" and not row.get("include_exclude"):
                # The extractor records treatment as two booleans; the table
                # shows one word. ONE reader decides (coverage_evidence).
                try:
                    from services.coverage_evidence import officer_treatment_label
                    row["include_exclude"] = officer_treatment_label(item)
                except Exception:                             # noqa: BLE001
                    pass
            if defn.get("follow_up") and _is_marked(item.get(FOLLOW_UP_KEY)):
                row[FOLLOW_UP_KEY] = True
            out.append(row)
        else:
            row = {c["key"]: "" for c in defn["columns"]}
            row[scalar_key] = _clean_cell(item)
            out.append(row)
    if not out:
        out = _seed_rows_from_facts(list_key, facts)
    return out


def _shown_row_indices(list_key: str, rows: Any, facts: Optional[dict]) -> Optional[List[int]]:
    """The positions of the stored rows a table SHOWS, or None (all of them).

    The GL window (21 Oct 2026, Brent 17 Oct item 6) shows only GL's own
    classifications - `pdf_service.gl_own_row_indices`, the rows the ACORD 126
    prints: a Workers Compensation class a combined package files under GL
    ("do not substitute WC class codes for GL codes") and the carrier's
    policy-level line ("Location 000 / Fungi Or Bacteria Exclusion") are not
    classifications to confirm. Every other table shows every row."""
    if list_key != "gl_class_code_schedule" or not isinstance(rows, list):
        return None
    try:
        from services.pdf_service import gl_own_row_indices
        return list(gl_own_row_indices(rows, facts or {}))
    except Exception as ex:                                   # noqa: BLE001
        logger.warning("schedule_capture: GL rows shown in full (%s)", ex)
        return None


def _seed_rows_from_facts(list_key: str, facts: Optional[dict]) -> List[dict]:
    """The rows a table opens with when it holds none of its own.

    The GL window (21 Oct 2026): the GL class codes the package already holds
    in its other home (`gl_class_codes_by_location` - the documents' "location
    + codes" reading, or the old card's answer), each as a row with its code
    and location, so the producer completes them instead of retyping them
    ("prefill verified information from uploaded documents"). Only a code that
    stands AS a code and is not another line's (`pdf_service.
    _gl_code_only_rows`, the 126's own reader of that home). A seeded row has
    no stored identity: a save writes it as a new row."""
    if list_key != "gl_class_code_schedule" or not isinstance(facts, dict):
        return []
    defn = SCHEDULE_DEFS.get(list_key)
    try:
        from services.pdf_service import _gl_code_only_rows
        seeds = _gl_code_only_rows(facts)
    except Exception as ex:                                   # noqa: BLE001
        logger.warning("schedule_capture: GL rows not seeded (%s)", ex)
        return []
    out: List[dict] = []
    for s in seeds[:MAX_ROWS]:
        if not isinstance(s, dict):
            continue
        row = {c["key"]: "" for c in defn["columns"]}
        row["class_code"] = _clean_cell(s.get("class_code"))
        row["location"] = _clean_cell(s.get("location"))
        if row["class_code"]:
            out.append(row)
    return out


# ── A column's choices for THIS package (21 Oct 2026, the GL window) ─────────
# A static `options` list is the same on every package; some choices can only
# come from the package itself - "Location: dropdown populated with the
# insured's locations", "Classification description: searchable dropdown with
# applicable operations, plus an Other option" (Brent). Served with the table
# (`columns_for`, read by `arq_service.get_session_schedules`), never stored.
_MAX_CHOICES = 40
_MAX_CHOICE_LEN = 150


def _choice_text(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def _add_choice(out: List[str], value: Any) -> None:
    text = _choice_text(value)
    if not text or len(text) > _MAX_CHOICE_LEN or len(out) >= _MAX_CHOICES:
        return
    try:
        from services.answer_semantics import is_placeholder_text
        if is_placeholder_text(text):
            return
    except Exception:                                         # noqa: BLE001
        pass
    if text.lower() not in {o.lower() for o in out}:
        out.append(text)


def gl_location_choices(facts: Optional[dict]) -> List[str]:
    """The insured's locations as the GL window offers them: one per premises
    (the location table's rows - one row per BUILDING, so a premises with two
    buildings is offered once), "Location <n> - <address>" - the label the 126
    LOC # reads back as ACORD 125's number for that premises (`pdf_service.
    _hazard_location_number`). A premises numbered with anything but digits is
    offered by its address (the box takes a number). No premises table: the
    loose location list, as written."""
    facts = facts if isinstance(facts, dict) else {}
    out: List[str] = []
    numbered: set = set()
    rows = _bare_rows(facts.get("property_locations")) or []
    for r in rows:
        if not isinstance(r, dict):
            continue
        num = _choice_text(r.get("location_number"))
        addr = _choice_text(_compose_address(r) or r.get("address"))
        if num.isdigit():
            if int(num) in numbered:
                continue
            numbered.add(int(num))
            _add_choice(out, f"Location {num} - {addr}" if addr else f"Location {num}")
        elif addr:
            _add_choice(out, addr)
    if not out:
        for loc in _bare_rows(facts.get("locations")) or []:
            if isinstance(loc, str):
                _add_choice(out, loc)
    return out


def gl_classification_choices(facts: Optional[dict]) -> List[str]:
    """The account's own operations, as the GL window offers them: the
    classifications its own GL rows state (the documents' words), the business'
    operations description and each premises' "what happens here" - short
    enough to be a classification. Anything else is typed (Other). Never a
    Workers Compensation class description (another line's row is not shown)."""
    facts = facts if isinstance(facts, dict) else {}
    out: List[str] = []
    rows = _bare_rows(facts.get("gl_class_code_schedule")) or []
    _shown = _shown_row_indices("gl_class_code_schedule", rows, facts)
    for i in (_shown if _shown is not None else range(len(rows))):
        r = rows[i]
        if isinstance(r, dict):
            _add_choice(out, r.get("classification"))
    try:
        from services.fact_lineage import envelope_value
        ops = envelope_value(facts.get("operations_description"))
    except Exception:                                         # noqa: BLE001
        ops = facts.get("operations_description")
        ops = ops.get("value") if isinstance(ops, dict) else ops
    if isinstance(ops, str):
        _add_choice(out, ops)
    for loc in _bare_rows(facts.get("property_locations")) or []:
        if isinstance(loc, dict):
            _add_choice(out, loc.get("operations_description"))
    return out


def _gl_refused_codes(facts: Optional[dict]) -> List[str]:
    """The codes the documents give only to ANOTHER line's rating, as the GL
    code cell refuses them ("do not substitute WC class codes for GL codes") -
    exactly the codes `pdf_service._gl_row_is_another_lines` keeps off the 126
    and the score (an ISO GL code's five digits is never refused)."""
    try:
        from services.pdf_service import _ISO_GL_CLASS_CODE_RE, _gl_codes_owned_elsewhere
        return sorted(c for c in _gl_codes_owned_elsewhere(facts or {})
                      if c and not _ISO_GL_CLASS_CODE_RE.match(c))
    except Exception:                                         # noqa: BLE001
        return []


# The GL code cell's refusal - served with the columns (`columns_for`) and
# enforced at the save (`refused_rows`), one sentence for both.
GL_REFUSED_CODE_MESSAGE = ("This is another line's class code in these documents - enter "
                           "the General Liability class code.")
_HIDDEN_ROW_MESSAGE = ("This row reads as the policy's own line, not a classification - "
                       "add its GL class code or rating basis.")


def refused_rows(list_key: str, rows: Any, facts: Optional[dict]) -> Dict[str, Dict[str, str]]:
    """The typed rows the server will not store, {row index: {column: message}};
    {} stores them all.

    A table that shows only some of its rows (`_shown_row_indices` - the GL
    window shows GL's own classifications) HIDES a stored row it does not show:
    a typed row like that was saved, then vanished from the window and the form
    with no word, and no later save could delete it (review of 21 Oct 2026: a
    WC class 5190 typed into the GL window). The cell refuses another line's
    code on screen (`columns_for` "refused"); the server refuses the same rows,
    so what the window offers is what the server stores (BUG-05). Every other
    table: {}."""
    if not isinstance(rows, list) or not rows:
        return {}
    shown = _shown_row_indices(list_key, rows, facts)
    if shown is None:
        return {}
    keep = set(shown)
    refused_codes = set(_gl_refused_codes(facts))
    out: Dict[str, Dict[str, str]] = {}
    for i, r in enumerate(rows):
        if i in keep or not isinstance(r, dict):
            continue
        code = re.sub(r"[^a-z0-9]", "", str(r.get("class_code") or "").lower())
        out[str(i)] = ({"class_code": GL_REFUSED_CODE_MESSAGE} if code and code in refused_codes
                       else {"row": _HIDDEN_ROW_MESSAGE})
    return out


def columns_for(list_key: str, facts: Optional[dict] = None) -> List[dict]:
    """The table's columns as the window shows them for THIS package - a copy
    of the static columns, plus the choices only the package can give (the GL
    window: its locations, its operations, the other lines' codes the code
    cell refuses). Every other table: its columns, unchanged."""
    defn = SCHEDULE_DEFS.get(list_key)
    if defn is None:
        return []
    cols = [dict(c) for c in defn["columns"]]
    if list_key != "gl_class_code_schedule" or not isinstance(facts, dict):
        return cols
    try:
        refused = _gl_refused_codes(facts)
        extra = {
            "location": {"options": gl_location_choices(facts)},
            "classification": {"options": gl_classification_choices(facts)},
            "class_code": ({"refused": refused,
                            "refused_message": GL_REFUSED_CODE_MESSAGE} if refused else {}),
        }
    except Exception as ex:                                   # noqa: BLE001
        logger.warning("schedule_capture: GL window choices skipped (%s)", ex)
        return cols
    for c in cols:
        for k, v in (extra.get(c.get("key")) or {}).items():
            if v:
                c[k] = v
    return cols


@lru_cache(maxsize=None)
def row_family_roots(list_key: str) -> frozenset:
    """The ACORD field-name roots that belong to ONE schedule's repeating row.

    `schedule_list_key_for_field` only recognises the handful of columns the
    capture table binds - 9 of ACORD 127's 67 per-vehicle fields. The other 58
    (garaging address, deductibles, every coverage indicator, radius, rate
    class) are stamped by Pass 1 and answer to nobody, so deleting a vehicle
    left the form printing a garaging address and a $1,000 deductible for a
    unit with no year, make or VIN. Found live 2026-09-08.

    A root is only returned when it maps to EXACTLY ONE capturable schedule.
    That guard is the whole reason this is derived rather than written down:
      * `WorkersCompensation` is a root of BOTH `wc_class_codes` and
        `wc_officers`, so owning it for either would wipe the other's rows;
      * `NamedInsured` is a root of `additional_named_insureds`, and
        `NamedInsured_A` is the APPLICANT.
    Ambiguous roots are dropped, and that schedule simply keeps the older
    bound-columns-only behaviour - never wrong, just less complete.

    Returns an empty set for anything unknown, which callers must read as
    "clear nothing extra".
    """
    try:
        from services.pdf_service import _SCHEDULE_REGISTRY
    except Exception as ex:                                   # pragma: no cover
        logger.warning("schedule_capture: pdf_service import failed: %s", ex)
        return frozenset()

    owners: dict = {}
    for base, defn in _SCHEDULE_REGISTRY.items():
        lk = getattr(defn, "list_key", None)
        if not lk or lk not in SCHEDULE_DEFS:
            continue                       # not a table we capture - not ours
        root = str(base).split("_")[0]
        if root:
            owners.setdefault(root, set()).add(lk)

    return frozenset(
        root for root, keys in owners.items()
        if keys == {list_key}              # unambiguous: this schedule alone
    )


def seed_rows(question: dict) -> List[dict]:
    """The rows WE pre-filled into a schedule question, cleaned exactly the way
    the client's copy was.

    A schedule question is sent to the client already holding what extraction
    (or a producer pre-load) found, so "is this field populated?" is not the same
    question as "did the client provide this?". Callers compare a submitted
    answer against this to tell the two apart.

    `validate_rows` is idempotent, so this compares equal to an answer that made
    the full round trip (client_view -> browser -> sanitize -> submit) without
    being edited. Never raises: an unknown key or a malformed question is simply
    "we pre-filled nothing", which is the safe reading everywhere it is used.
    """
    try:
        rows, _ = validate_rows(
            list_key_from_answer_key(str(question.get("field_name") or "")),
            question.get("current_rows") or [],
        )
        return rows
    except Exception:                                         # noqa: BLE001
        return []


def encode_answer(rows: List[dict]) -> str:
    """Serialise rows for transport through the string-based answer pipeline."""
    return json.dumps(rows, separators=(",", ":"))


def decode_answer(raw: Any) -> List[dict]:
    """Inverse of `encode_answer`, tolerant of an already-decoded list."""
    if isinstance(raw, list):
        return raw
    if not raw:
        return []
    try:
        parsed = json.loads(raw)
    except Exception:
        return []
    return parsed if isinstance(parsed, list) else []


# ---------------------------------------------------------------------------
# Client-facing copy
# ---------------------------------------------------------------------------
# Plain language, no jargon, and no em-dashes (project UI copy rule).

_QUESTION_OVERRIDES = {
    "auto_vin_schedule": (
        "Please list the vehicles to be insured. Add one row per vehicle, or "
        "upload your existing vehicle list as a CSV or Excel file."
    ),
    "auto_drivers": (
        "Please list everyone who drives a business vehicle. Add one row per "
        "driver, or upload your driver list as a CSV or Excel file."
    ),
    "loss_history": (
        "Please list any insurance claims or losses from the past 5 years. Add "
        "one row per claim, or upload your loss runs as a CSV or Excel file. "
        "If you have had no claims, leave this empty."
    ),
    "property_locations": (
        "Please list every business location to be insured. Add one row per "
        "location, or upload your location list as a CSV or Excel file."
    ),
    # V1 H3 8.1. Deliberately worded as the CLIENT would describe their own
    # people - groups of employees and what they do - never as a rating table.
    "wc_class_codes": (
        "Please list your employees by group - for example office staff, sales, "
        "and field crews. Add one row per group, or upload the list as a CSV or "
        "Excel file."
    ),
    "wc_officers": (
        "Please list the owners and officers, and whether each one is included "
        "in or excluded from Workers Compensation coverage. Add one row per "
        "person, or upload the list as a CSV or Excel file."
    ),
}

_HINT_OVERRIDES = {
    "auto_vin_schedule": (
        "The VIN is the 17-character number on the dashboard or the driver's "
        "door frame. Enter a VIN and we will fill in the year, make and model "
        "for you."
    ),
    "auto_drivers": (
        "Include anyone who drives a company vehicle, even occasionally."
    ),
    "loss_history": (
        "Your prior insurance company can provide loss runs if you do not have "
        "them handy."
    ),
    "wc_class_codes": (
        "One row per group of employees who do similar work - for example "
        "office staff, sales, field crew. Give the yearly payroll for each "
        "group and the state they work in. Your broker will handle the class codes."
    ),
    "wc_officers": (
        "Type Included or Excluded for each owner or officer."
    ),
}


# Confirm mode (Chat 5, 14 Sep 2026). A table that already holds rows is not a
# request for a list - the client was offered "Please list the vehicles to be
# insured" with the Subaru the policy prints already in the grid, and read it,
# correctly, as being asked again. With rows held the SAME table is offered as
# "we found these - check them, fix anything wrong, add what we missed", and the
# document the rows came from is named. Nouns are per table because a location
# is a "business location" to the insured and "owner or officer" pluralises
# irregularly.
_CONFIRM_NOUNS = {
    "auto_vin_schedule":  ("vehicle", "vehicles"),
    "auto_drivers":       ("driver", "drivers"),
    "property_locations": ("business location", "business locations"),
    "loss_history":       ("claim", "claims"),
    "wc_class_codes":     ("employee group", "employee groups"),
    "wc_officers":        ("owner or officer", "owners or officers"),
}

_CONFIRM_HINT = (
    "Change any cell that is wrong, remove a row that should not be there, or "
    "add a row for anything we missed. If everything is right, tap "
    "\"Everything here is correct\"."
)


def confirm_question_text(list_key: str, row_count: int,
                          source_labels: Optional[List[str]] = None) -> str:
    """The confirm-mode wording for a table already holding `row_count` rows."""
    defn = SCHEDULE_DEFS.get(list_key)
    if defn is None:
        return ""
    if row_count <= 0:
        return question_text(list_key)
    singular = defn["singular"]
    one, many = _CONFIRM_NOUNS.get(list_key, (singular, f"{singular}s"))
    noun = one if row_count == 1 else many
    try:
        from services.confirm_known import sources_phrase
        where = sources_phrase(source_labels)
    except Exception:                                         # noqa: BLE001
        where = ""
    found = (f"We found {row_count} {noun} in {where}." if where
             else f"We have {row_count} {noun} on file for you.")
    check = "Please check it" if row_count == 1 else "Please check them"
    return f"{found} {check}, correct anything that is wrong, and add any we missed."


def question_text(list_key: str, rows: Optional[List[dict]] = None,
                  source_labels: Optional[List[str]] = None) -> str:
    defn = SCHEDULE_DEFS.get(list_key)
    if defn is None:
        return ""
    if rows:
        return confirm_question_text(list_key, len(rows), source_labels)
    if list_key in _QUESTION_OVERRIDES:
        return _QUESTION_OVERRIDES[list_key]
    # "Please list your ..." and NOT "Please provide your ...", which is
    # `arq_service._MACHINE_QUESTION_PREFIX` - the marker for a question nobody
    # managed to word properly, which `_hide_machine_worded_questions` routes
    # out of the client AND producer workflow. This default template was that
    # exact string, so ANY schedule added without an override above was built,
    # routed, and then silently suppressed (V1 H3-D, found on the first live
    # run). The four original schedules escaped only because each happened to
    # have a hand-written override starting "Please list".
    # `tests/test_h3_wc_data_capture.py::test_no_schedule_question_is_hidden_
    # as_machine_worded` fails the build if this drifts back.
    return (
        f"Please list your {defn['label'].lower()}. Add one row per "
        f"{defn['singular']}, or upload the list as a CSV or Excel file."
    )


def hint_text(list_key: str, confirm: bool = False) -> str:
    defn = SCHEDULE_DEFS.get(list_key)
    if defn is None:
        return ""
    if confirm:
        return _CONFIRM_HINT
    if list_key in _HINT_OVERRIDES:
        return _HINT_OVERRIDES[list_key]
    return f"Add as many {defn['singular']}s as you need. Blank rows are ignored."


def summarize(list_key: str, rows: List[dict]) -> str:
    """One-line human summary for producer-facing lists and activity logs."""
    defn = SCHEDULE_DEFS.get(list_key)
    if defn is None:
        return ""
    n = len(rows)
    if n == 0:
        return f"No {defn['singular']}s provided"
    noun = defn["singular"] if n == 1 else f"{defn['singular']}s"
    return f"{n} {noun}"
