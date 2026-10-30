"""End-user review, 29 Oct 2026 - a producer walking the 27-29 Oct features on
messy packages (the 29 Oct kit's Ridgeline sessions, re-read on current code,
and synthetic packages). Each test is a CLASS of package, never one fixture:

1. The review page draws the stops AS THEY STAND: a stored card the current
   rules no longer raise is not drawn, and a live Data Consistency conflict the
   stored list never mirrored is not drawn twice (as its own row AND as an
   "Other validations" warning whose fix opened a phone box).
2. Data Consistency labels and reasons read like a producer, not a key.
3. A row-level money disagreement prints both amounts the same way.
4. A schedule of LOCATIONS (ACORD 130 / 133) lists each premises once, in
   order - no blank row where a second building folded.
5. Buildings past ACORD 140's / 125's premises rows continue on ACORD 101.
6. "N prior claims" counts the package's claims, not one document's count.
7. A share released with Data Consistency picks says so.
"""
from __future__ import annotations

import copy
import os
import random
import sys

os.environ.setdefault("OPENAI_API_KEY", "sk-offline")
for _k in ("EVIDENCE_JUDGE", "NARRATIVE_READER", "CARRIER_NARRATIVE"):
    os.environ.setdefault(_k, "0")
sys.path.insert(0, os.path.dirname(__file__))

import pytest  # noqa: E402


def _env(v, source="ai"):
    return {"value": v, "source": source, "confidence": "ai_high"}


# ── 1. The page draws the stops as they stand ───────────────────────────────

def _package_with_conflict():
    import reach100_harness as H
    from services.underwriting_consistency import assess_underwriting_consistency
    row = H.synthetic_package(random.Random(3))
    f = row["facts"]
    f["num_employees_full_time"] = _env("62")
    docs = row["docs"]
    for d in docs:
        d.setdefault("doc_id", d["filename"])
    a = {"doc_id": "dec1", "filename": "dec.pdf", "doc_type": "dec_page", "text": "Full time employees 62",
         "facts": {"num_employees_full_time": _env("62"),
                   "applicant_name": copy.deepcopy(f["applicant_name"])}}
    b = {"doc_id": "app1", "filename": "outside_125.pdf", "doc_type": "application",
         "text": "Full time employees 58",
         "facts": {"num_employees_full_time": _env("58"),
                   "applicant_name": copy.deepcopy(f["applicant_name"])}}
    docs += [a, b]
    row["underwriting_consistency"] = assess_underwriting_consistency(docs, f, {})
    return row


def _drawn(row):
    from services import sqs_service as S
    from services.review_plan import rendered_cards
    pkg = S.current_package_sqs(row, None, None)
    return pkg, list(rendered_cards(S.review_page_grouped_view(row, pkg)))


def test_a_live_conflict_the_stored_list_never_mirrored_is_drawn_once():
    row = _package_with_conflict()
    row["structured_issues"] = []          # stored before the rule raised it
    fld = next(x for x in row["underwriting_consistency"]["fields"]
               if x["fact_key"] == "num_employees_full_time")
    assert fld["status"] == "conflict"
    _pkg, cards = _drawn(row)
    dup = [c for c in cards if "documents disagree" in str(c.get("message") or "")]
    assert dup == [], [c.get("message") for c in dup]
    assert not any(c.get("code") == "uncovered_soft_stop" and "Employees" in str(c.get("message"))
                   for c in cards)


def test_stored_cards_the_current_rules_no_longer_raise_are_not_drawn():
    from services.issue_registry import make_issue
    row = _package_with_conflict()
    stale = [
        make_issue("legacy_wc_monopolistic_state", "soft_warning",
                   "Monopolistic WC state detected (ND/OH/WA/WY) - must use state fund "
                   "Fix: Review and correct this before proceeding."),
        make_issue("per_location_cope_incomplete", "soft_warning",
                   "1 of 4 insured locations are missing construction type or building/BPP value."),
        make_issue("loss_history_attestation_conflict", "soft_warning",
                   "Data consistency: a No Known Losses attestation conflicts with claims found "
                   "in the uploaded loss runs."),
    ]
    row["structured_issues"] = stale
    _pkg, cards = _drawn(row)
    codes = {c.get("code") for c in cards}
    assert not codes & {"legacy_wc_monopolistic_state", "per_location_cope_incomplete",
                        "loss_history_attestation_conflict"}, codes


def test_an_advisory_or_a_live_stored_card_stays():
    """The retirement only drops what the live stops no longer raise."""
    from services.issue_registry import make_issue, structured_as_they_stand
    keep = make_issue("requested_coverage_change", "advisory", "Requested Umbrella Limit $9,000,000.")
    live = make_issue("legacy_phone_format", "soft_warning", "Phone number looks wrong")
    out = structured_as_they_stand([keep, live], {"facts": {}, "docs": []}, [], ["Phone number looks wrong"])
    assert [i["code"] for i in out] == ["requested_coverage_change", "legacy_phone_format"]
    out = structured_as_they_stand([keep, live], {"facts": {}, "docs": []}, [], [])
    assert [i["code"] for i in out] == ["requested_coverage_change"]


# ── 2. Labels and reasons a producer reads ──────────────────────────────────

@pytest.mark.parametrize("key,label", [
    ("num_employees_part_time", "Part-Time Employees"),
    ("num_employees_full_time", "Full-Time Employees"),
    ("applicant_business_phone", "Business Phone"),
    ("num_locations", "Number of Locations"),
    ("gl_each_occurrence_limit", "GL Each Occurrence Limit"),
])
def test_auto_discovered_labels_read_like_a_producer(key, label):
    from services.underwriting_consistency import _humanize
    assert _humanize(key) == label


def test_no_card_reason_speaks_pipeline():
    from services.underwriting_consistency import _conflict_reason
    vals = [{"display": "(303) 555-0148"}, {"display": "(303) 555-0184"}]
    assert _conflict_reason("applicant_business_phone", "identity", vals) == \
        "the documents state different phone numbers"
    r = _conflict_reason("some_free_text_fact", "identity", [{"display": "a"}, {"display": "b"}])
    assert "normalization" not in r and "scope matching" not in r


def test_the_source_conflict_card_uses_the_same_label():
    from services.extraction_service import _conflict_field_label
    assert _conflict_field_label("num_employees") == "Employee Count"


# ── 3. A row's two amounts print the same way ───────────────────────────────

def test_row_money_rivals_print_alike():
    from services.row_rivals import row_fields, RIVALS_KEY
    rows = [{"date": "05/17/2022", "line_of_business": "Auto", "claim_number": "BA-1", "paid": "$18,420",
             RIVALS_KEY: {"paid": {"kept": {"value": "$18,420", "documents": [{"doc_type": "loss_run"}]},
                                   "others": [{"value": "14,820", "documents": [{"doc_type": "application"}]}]}}}]
    out = row_fields({"loss_history": _env(rows)})
    assert out, "the row card is raised"
    assert [v["display"] for v in out[0]["values"]] == ["$18,420", "$14,820"]
    assert "$14,820" in out[0]["conflict_reason"]


# ── 4 / 5. Locations listed once; buildings past the rows continue ──────────

def _three_buildings():
    return [
        {"address": "4150 S Kalamath St, Denver, CO 80223", "address_line1": "4150 S Kalamath St",
         "address_city": "Denver", "address_state": "CO", "address_zip": "80223",
         "location_number": "1", "premises_number": "1", "building_number": "1",
         "construction_type": "Joisted Masonry", "building_value": "$2,350,000"},
        {"address": "4150 S Kalamath St, Denver, CO 80223", "address_line1": "4150 S Kalamath St",
         "address_city": "Denver", "address_state": "CO", "address_zip": "80223",
         "location_number": "1", "premises_number": "1", "building_number": "2",
         "construction_type": "Non-Combustible", "building_value": "$1,780,000"},
        {"address": "1720 Westland Rd, Cheyenne, WY 82001", "address_line1": "1720 Westland Rd",
         "address_city": "Cheyenne", "address_state": "WY", "address_zip": "82001",
         "location_number": "2", "premises_number": "2", "building_number": "1",
         "construction_type": "Masonry Non-Combustible", "building_value": "$910,000"},
    ]


def _stamp(form_id, facts):
    import json
    from services.pdf_service import map_facts_to_form
    from services.acord_intake.recognize import _SCHEMA_DIR
    schema = json.load(open(os.path.join(_SCHEMA_DIR, f"{form_id}_schema.json")))
    vals, _meta = map_facts_to_form(dict(facts, _form_id=form_id), schema, form_id, allow_llm=False)
    return vals


def _facts():
    return {"applicant_name": _env("Ridgeline Mechanical Services LLC"),
            "property_locations": _env(_three_buildings()),
            "has_property_coverage": _env(True)}


def test_acord_130_lists_each_premises_once_with_no_blank_row():
    vals = _stamp("ACORD_130", _facts())
    loc = {k[-1]: v for k, v in vals.items() if k.startswith("Location_ProducerIdentifier_") and v}
    street = {k[-1]: v for k, v in vals.items() if k.startswith("Location_PhysicalAddress_LineOne_") and v}
    assert loc == {"A": "1", "B": "2"}, loc
    assert street == {"A": "4150 S Kalamath St", "B": "1720 Westland Rd"}, street


def test_acord_125_still_lists_every_building():
    vals = _stamp("ACORD_125", _facts())
    loc = [vals.get(f"CommercialStructure_Location_ProducerIdentifier_{c}") for c in "ABC"]
    assert loc == ["1", "1", "2"], loc


def test_buildings_past_acord_140s_rows_continue_on_acord_101():
    from services.pdf_service import _acord101_blocks
    f = dict(_facts(), _package_form_ids=["ACORD_125", "ACORD_140", "ACORD_101"])
    blocks = [t for form, t in _acord101_blocks(f) if form == "ACORD_140"]
    assert len(blocks) == 1 and "1720 Westland Rd" in blocks[0] and "1 of 3 buildings" in blocks[0]
    # Two buildings fit: nothing continues.
    f2 = dict(f, property_locations=_env(_three_buildings()[:2]))
    assert not [t for form, t in _acord101_blocks(f2) if form == "ACORD_140"]


# ── 6. The claims count is the package's ────────────────────────────────────

def test_the_101_card_counts_the_claims_on_file():
    from services.cross_form_validator import _check_acord101_triggers
    claims = [{"date": f"0{n}/01/2023", "line_of_business": "GL", "paid": "$1,000", "claim_number": f"C{n}"}
              for n in range(1, 8)]
    facts = {"num_claims": _env("3"), "loss_history": _env(claims)}
    out = _check_acord101_triggers(facts, {}, {"ACORD_125"})
    msgs = " ".join(str(i.get("message") or "") for i in (out or []))
    assert "7 prior claims" in msgs, msgs


# ── 7. Holders counted where the page draws them ────────────────────────────

def test_a_share_released_with_data_consistency_picks_says_so():
    from services import review_plan as RP

    def _it(i, pts, kind, **kw):
        return dict({"id": i, "kind": kind, "points": pts, "gain": float(pts), "under": False}, **kw)
    items = [_it("dc:a", 0, "dc", _cleared=["soft"], _did=True),
             _it("card:x", 0, "card", _cleared=["soft"], _did=True),
             _it("dc:b", 3, "dc", _cleared=["soft"], _released=["soft"], _did=True)]
    RP._share_group_releases(items, 3, {"soft": 3})
    assert {i["with_others"] for i in items} == \
        {"counts when all 3 warnings and Data Consistency picks are fixed"}
    items = [_it("dc:a", 0, "dc", _cleared=["soft"], _did=True),
             _it("dc:b", 2, "dc", _cleared=["soft"], _released=["soft"], _did=True)]
    RP._share_group_releases(items, 2, {"soft": 2})
    assert {i["with_others"] for i in items} == {"counts when all 2 Data Consistency picks are fixed"}
