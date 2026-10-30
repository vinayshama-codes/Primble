"""Data items 4 / 7 / 8 / 9 (29 Oct 2026, owner-approved) - each test a CLASS of
package, never one fixture's values.

7. One claim = one row: a loss run and an ACORD form describing the same claim
   (same date of loss, compatible line; claim numbers decide when both print one)
   are one row whatever their amounts; the loss run's amount stays, the other is
   a rival. Two claims of one day on different lines / carriers stay two.
4. Schedule rows match ACROSS documents (VIN - truncated or one character off -,
   licence / name, location + building, claim); a disagreeing cell keeps the
   authoritative value (declarations / loss run over an ACORD form) and records
   the rival; a row-level Data Consistency card offers both and its pick writes
   that one cell. A person's saved table is never judged.
8. An outside ACORD 125's BUSINESS PHONE # is read as `applicant_business_phone`;
   its premises rows' revenue / staff are the business totals it states (one
   location = the row, several = the sum); a location's revenue above the
   business total is a warning.
9. An address block (name / street / suite / city / state / ZIP in one box) is
   parsed ONCE - never "block, Suite 210, Denver, CO 80223".
"""
from __future__ import annotations

import copy
import os

os.environ.setdefault("OPENAI_API_KEY", "sk-offline")
for _k in ("EVIDENCE_JUDGE", "NARRATIVE_READER", "CARRIER_NARRATIVE"):
    os.environ.setdefault(_k, "0")

import pytest

from services.acord_intake import merge_rules as MR
from services.acord_intake import document_settle as DS
from services import row_rivals as RR


def _env(v, source="ai"):
    return {"value": v, "source": source, "confidence": "ai_high"}


def _doc(i, doc_type, acord=False, **facts):
    d = {"doc_id": f"d{i}", "filename": f"{doc_type}_{i}.pdf", "doc_type": doc_type, "text": "",
         # a schedule is stored as a bare list, like the extraction writes it
         "facts": {k: (v if isinstance(v, list) else _env(v, "acord_form" if acord else "ai"))
                   for k, v in facts.items()}}
    if acord:
        d["acord"] = {"forms": [{"form_id": "ACORD_125", "copy": 1}], "read_keys": []}
    return d


_ID = dict(applicant_name="Ridge Mechanical LLC", fein="84-5512309")


def _merge(docs):
    from services.extraction_service import merge_facts
    docs = copy.deepcopy(docs)
    mf, _fl = merge_facts(docs, docs[0])
    return mf, docs


def _rows(mf, key):
    v = mf.get(key)
    return v.get("value") if isinstance(v, dict) and "value" in v else (v or [])


# ── 7. One claim, one row ────────────────────────────────────────────────────
_RUN_CLAIMS = [
    {"date": "06/09/2022", "claim_number": "GL-22-004417", "paid": "$36,240", "line_of_business": "GL"},
    {"date": "05/17/2022", "claim_number": "BA-22-118830", "paid": "$18,420", "line_of_business": "Auto"},
    {"date": "07/28/2024", "claim_number": "CP-24-033118", "paid": "$48,300", "line_of_business": "Property"},
]
_ACORD_CLAIMS = [
    {"date": "06/09/2022", "paid": "36,240", "line_of_business": "General Lia"},
    {"date": "05/17/2022", "paid": "14,820", "line_of_business": "Commercia"},
    {"date": "07/28/2024", "paid": "48,300", "line_of_business": "Property"},
]


@pytest.mark.parametrize("acord_first", [False, True])
def test_a_restated_claim_with_a_different_amount_is_one_claim(acord_first):
    run = _doc(1, "loss_run", loss_history=_RUN_CLAIMS, **_ID)
    app = _doc(2, "application", acord=True, loss_history=_ACORD_CLAIMS, **_ID)
    mf, _ = _merge([app, run] if acord_first else [run, app])
    claims = _rows(mf, "loss_history")
    assert len(claims) == 3
    auto = next(c for c in claims if c.get("claim_number") == "BA-22-118830")
    assert auto["paid"] == "$18,420"                       # the carrier's loss run
    rv = auto[RR.RIVALS_KEY]["paid"]
    assert rv["kept"]["value"] == "$18,420"
    assert [o["value"] for o in rv["others"]] == ["14,820"]
    # an amount the two state alike is no rival
    assert "paid" not in (next(c for c in claims if c.get("claim_number") == "GL-22-004417").get(RR.RIVALS_KEY) or {})


def test_two_claims_on_one_day_of_different_lines_stay_two():
    a = {"date": "03/01/2023", "paid": "$1,000", "line_of_business": "Auto"}
    b = {"date": "03/01/2023", "paid": "$5,000", "line_of_business": "Workers Compensation"}
    assert not MR.same_claim_event(a, b)
    assert MR.same_claim_event(a, dict(a, paid="$1,200"))
    # carriers that differ = two claims
    assert not MR.same_claim_event(dict(a, carrier="Front Range"), dict(a, carrier="Summit Peak"))
    # claim numbers decide alone
    assert not MR.same_claim_event(dict(a, claim_number="X1"), dict(a, claim_number="X2"))


def test_a_cut_line_name_stands_for_the_lines_it_begins():
    assert "auto" in MR.claim_line_families("Commercia")
    assert MR.claim_line_families("General Lia") == frozenset({"general_liab"})
    assert MR.claim_line_families("") == frozenset()


def test_two_loss_run_claims_of_one_day_and_line_are_narrowed_by_amount():
    pool = [{"date": "01/05/2024", "claim_number": "A", "paid": "$100", "line_of_business": "Auto"},
            {"date": "01/05/2024", "claim_number": "B", "paid": "$900", "line_of_business": "Auto"}]
    assert MR.restates_record_claim({"date": "01/05/2024", "paid": "900", "line_of_business": "Auto"}, pool)
    # neither amount: which claim is unknown - the row is not dropped (blank over wrong)
    assert not MR.restates_record_claim({"date": "01/05/2024", "paid": "500", "line_of_business": "Auto"}, pool)
    # two loss runs printing ONE claim are still one claim
    twice = [pool[0], dict(pool[0], paid="$150")]
    assert MR.restates_record_claim({"date": "01/05/2024", "paid": "120", "line_of_business": "Auto"}, twice)


# ── 4. Vehicles ──────────────────────────────────────────────────────────────
def _veh(vin, model="ProMaster Cargo Van 2500", year="2022", make="Ram", **kw):
    return dict({"vin": vin, "year": year, "make": make, "model": model}, **kw)


def test_a_truncated_vin_joins_its_vehicle_when_the_model_reads_in_other_words():
    dec = [_veh("3C6LRVDG4NE11836"), _veh("1FTBR1C82PKA41827", "Transit 250", "2023", "Ford")]
    app = [_veh("3C6LRVDG4NE118367", "ProMaster 2500"), _veh("1FTBR1C82PKA41827", "Transit 250", "2023", "Ford")]
    out = MR.fold_rows("auto_vin_schedule", [dec, app], [False, True])
    assert len(out) == 2
    assert {r["vin"] for r in out} == {"3C6LRVDG4NE118367", "1FTBR1C82PKA41827"}


def test_one_character_off_full_vin_is_one_vehicle_with_a_rival():
    dec = _doc(1, "dec_page", auto_vin_schedule=[_veh("3C6LRVDG4NE118362", vehicle_number="2")], **_ID)
    app = _doc(2, "acord_form", acord=True,
               auto_vin_schedule=[_veh("3C6LRVDG4NE118367", "ProMaster 2500", vehicle_number="2")], **_ID)
    # without the same VEH # on both: two vehicles (consecutive serials)
    assert len(MR.fold_rows("auto_vin_schedule", [[_veh("3C6LRVDG4NE118362")],
                                                  [_veh("3C6LRVDG4NE118367")]], [False, True])) == 2
    for order in ([dec, app], [app, dec]):
        mf, _ = _merge(order)
        vehs = _rows(mf, "auto_vin_schedule")
        assert len(vehs) == 1
        assert vehs[0]["vin"] == "3C6LRVDG4NE118362"            # the declarations'
        assert [o["value"] for o in vehs[0][RR.RIVALS_KEY]["vin"]["others"]] == ["3C6LRVDG4NE118367"]


def test_a_fleet_of_consecutive_serials_printed_by_both_stays_whole():
    fleet = [_veh("3C6LRVDG4NE118362", vehicle_number="1"), _veh("3C6LRVDG4NE118363", vehicle_number="2")]
    out = MR.fold_rows("auto_vin_schedule", [fleet, copy.deepcopy(fleet)], [False, True])
    assert len(out) == 2
    # one document lists both, the other only one of them, one character off
    # BOTH of them: which one is unknown - not joined
    out = MR.fold_rows("auto_vin_schedule", [fleet, [_veh("3C6LRVDG4NE118367", vehicle_number="3")]], [False, True])
    assert len(out) == 3


def test_a_truncated_vin_is_no_rival():
    dec = _doc(1, "dec_page", auto_vin_schedule=[_veh("3C6LRVDG4NE11836")], **_ID)
    app = _doc(2, "acord_form", acord=True, auto_vin_schedule=[_veh("3C6LRVDG4NE118367", "ProMaster 2500")], **_ID)
    mf, _ = _merge([dec, app])
    vehs = _rows(mf, "auto_vin_schedule")
    assert len(vehs) == 1 and "vin" not in (vehs[0].get(RR.RIVALS_KEY) or {})


# ── 4. Drivers ───────────────────────────────────────────────────────────────
def _drv(name, dob, lic=None):
    return {k: v for k, v in {"name": name, "dob": dob, "license_number": lic}.items() if v}


def test_a_driver_birth_date_two_documents_state_differently_is_a_rival():
    dec = _doc(1, "dec_page", auto_drivers=[_drv("Derek A. Nguyen", "12/03/1991", "14-559-0263")], **_ID)
    app = _doc(2, "acord_form", acord=True, auto_drivers=[_drv("Derek A Nguyen", "12/08/1991", "14-559-0263")], **_ID)
    mf, _ = _merge([app, dec])
    drv = _rows(mf, "auto_drivers")
    assert len(drv) == 1 and drv[0]["dob"] == "12/03/1991"
    assert drv[0][RR.RIVALS_KEY]["dob"]["others"][0]["value"] == "12/08/1991"


def test_a_driver_named_once_on_each_side_with_no_licence_is_one_person():
    dec = [_drv("Derek A. Nguyen", "12/03/1991", "14-559-0263")]
    app = [_drv("Derek A Nguyen", None)]                       # the form prints no DOB
    assert len(MR.fold_rows("auto_drivers", [dec, app], [False, True])) == 1
    # same name, two birth dates, no licence on one side: two people
    assert len(MR.fold_rows("auto_drivers", [dec, [_drv("Derek A Nguyen", "12/08/1991")]],
                            [False, True])) == 2
    # the same name twice on a side (father and son) - never joined by name
    twice = [_drv("Derek A Nguyen", "12/08/1991"), _drv("Derek A Nguyen", "02/02/1965")]
    assert len(MR.fold_rows("auto_drivers", [dec, twice], [False, True])) == 3


# ── 4. Buildings ─────────────────────────────────────────────────────────────
def test_a_building_area_two_documents_state_differently_keeps_the_declarations():
    dec_rows = [{"address": "4150 S Kalamath St, Denver, CO 80223", "building_number": "2",
                 "total_building_area": "22,000"}]
    app_rows = [{"address_line1": "4150 S Kalamath St", "address_city": "Denver", "location_number": "1",
                 "building_number": "2", "total_building_area": "25,000"}]
    merged = {"property_locations": [dict(app_rows[0])]}
    docs = [_doc(1, "application", acord=True, property_locations=app_rows, **_ID),
            _doc(2, "dec_page", property_locations=dec_rows, **_ID)]
    RR.attach_row_rivals(merged, docs)
    row = merged["property_locations"][0]
    assert row["total_building_area"] == "22,000"
    assert row[RR.RIVALS_KEY]["total_building_area"]["others"][0]["value"] == "25,000"
    # another building at that street is not this one
    other = {"property_locations": [dict(app_rows[0], building_number="1")]}
    RR.attach_row_rivals(other, docs)
    assert RR.RIVALS_KEY not in other["property_locations"][0]


# ── 4. The row-level card ────────────────────────────────────────────────────
def _kit_like():
    dec = _doc(1, "dec_page", auto_drivers=[_drv("Derek A. Nguyen", "12/03/1991", "14-559-0263"),
                                           _drv("Tanya R. Whitfield", "09/08/1988", "11-208-7741")], **_ID)
    app = _doc(2, "acord_form", acord=True,
               auto_drivers=[_drv("Derek A Nguyen", "12/08/1991", "14-559-0263"),
                             _drv("Tanya R Whitfield", "09/08/1988", "11-208-7741")], **_ID)
    return [dec, app]


def _assess(mf, docs, conf=None):
    from services.underwriting_consistency import assess_underwriting_consistency
    return assess_underwriting_consistency(docs, mf, conf or {}, {})


def test_a_row_rival_is_a_row_level_card_and_its_pick_writes_that_cell():
    from services.underwriting_consistency import apply_confirmations
    mf, docs = _merge(_kit_like())
    uw = _assess(mf, docs)
    cards = [f for f in uw["fields"] if f.get("row_level")]
    assert len(cards) == 1
    card = cards[0]
    assert card["status"] == "conflict" and card["review_required"] and uw["review_required"]
    assert card["label"] == "Driver schedule row 1 (Derek A. Nguyen): Date of birth"
    assert [v["display"] for v in card["values"]] == ["12/03/1991", "12/08/1991"]
    assert card["values"][1]["sources"][0]["filename"] == "acord_form_2.pdf"
    assert "Documents disagree" in card["conflict_reason"]
    # the key does not move across a re-merge
    mf2, docs2 = _merge(_kit_like())
    assert [f["fact_key"] for f in _assess(mf2, docs2)["fields"] if f.get("row_level")] == [card["fact_key"]]
    # the pick writes ONE cell of ONE row, and the card is confirmed
    conf = {card["fact_key"]: RR.validate_row_confirmation(card["fact_key"], "12/08/1991", mf)}
    after = apply_confirmations(mf, conf, docs=docs)
    drv = _rows(after, "auto_drivers")
    assert drv[0]["dob"] == "12/08/1991" and drv[1]["dob"] == "09/08/1988"
    assert _rows(mf, "auto_drivers")[0]["dob"] == "12/03/1991"        # the input untouched
    again = [f for f in _assess(after, docs, conf)["fields"] if f.get("row_level")][0]
    assert again["status"] == "confirmed" and not again["review_required"]


def test_a_row_card_holds_85_and_is_a_plan_item():
    from services.stops_now import underwriting_conflict_stops, conflict_stop_facts
    mf, docs = _merge(_kit_like())
    uw = _assess(mf, docs)
    key = next(f["fact_key"] for f in uw["fields"] if f.get("row_level"))
    stops = underwriting_conflict_stops(uw, {}, docs, {})
    mine = [s for s in stops if s[0] == key]
    assert mine and mine[0][2] is False                 # a warning (85), never a hard stop
    session = {"underwriting_consistency": uw, "flags": {}, "docs": docs, "facts": mf,
               "underwriting_confirmations": {}}
    assert key in set(conflict_stop_facts(session).values())
    # a pick settles it
    session["underwriting_confirmations"] = {key: "12/03/1991"}
    assert key not in set(conflict_stop_facts(session).values())


@pytest.mark.parametrize("bad", ["", "N/A", "TBD", "unknown"])
def test_a_row_pick_refuses_a_non_answer(bad):
    mf, docs = _merge(_kit_like())
    key = next(f["fact_key"] for f in _assess(mf, docs)["fields"] if f.get("row_level"))
    with pytest.raises(ValueError):
        RR.validate_row_confirmation(key, bad, mf)


def test_a_row_pick_for_an_unknown_row_is_refused():
    with pytest.raises(ValueError):
        RR.validate_row_confirmation("row:auto_drivers:dob:0000000000", "12/08/1991", {})
    with pytest.raises(ValueError):
        RR.validate_row_confirmation("row:auto_drivers:name:abc", "x", {})


def test_a_table_a_person_saved_is_never_judged():
    from services.schedule_capture import mark_human_rows
    mf, docs = _merge(_kit_like())
    mark_human_rows(mf, "auto_drivers", "producer")
    assert not [f for f in _assess(mf, docs)["fields"] if f.get("row_level")]


def test_one_document_raises_no_row_card():
    mf, docs = _merge(_kit_like()[:1])
    assert not [f for f in _assess(mf, docs)["fields"] if f.get("row_level")]


# ── 8. The outside 125's business phone / revenue / staff ────────────────────
def test_the_business_phone_box_is_read_as_the_applicants_phone():
    from services.acord_intake.reverse_map import box_targets
    from services.fact_registry import FACT_REGISTRY
    assert box_targets("ACORD_125", "NamedInsured_Primary_PhoneNumber_A") == [
        {"t": "fact", "fact": "applicant_business_phone", "part": "whole"}]
    entry = FACT_REGISTRY["applicant_business_phone"]
    assert entry["tier"] is None and entry["validate"]("(303) 555-0184")
    assert "applicant_business_phone" in MR.APPLICANT_FACTS


def test_a_document_read_before_the_mapping_promotes_its_carried_phone():
    d = _doc(1, "application", acord=True, **_ID)
    d["acord"]["carried"] = {"ACORD_125": {"NamedInsured_Primary_PhoneNumber_A": "(303) 555-0184",
                                           "Policy_Audit_FrequencyCode_A": "A"}}
    DS.settle_acord_document(d)
    assert d["facts"]["applicant_business_phone"]["value"] == "(303) 555-0184"
    assert "Policy_Audit_FrequencyCode_A" in d["acord"]["carried"]["ACORD_125"]


def test_phones_two_documents_print_differently_meet_as_a_card():
    dec = _doc(1, "dec_page", applicant_business_phone="(303) 555-0148", **_ID)
    app = _doc(2, "application", acord=True, applicant_business_phone="(303) 555-0184", **_ID)
    mf, docs = _merge([dec, app])
    f = next(x for x in _assess(mf, docs)["fields"] if x["fact_key"] == "applicant_business_phone")
    assert f["status"] == "conflict"


_LOCS = [
    {"location_number": "1", "building_number": "1", "address_line1": "4150 S Kalamath St",
     "annual_revenue": "9,200,000", "full_time_employees": "58", "part_time_employees": "4"},
    {"location_number": "1", "building_number": "2", "address_line1": "4150 S Kalamath St",
     "annual_revenue": "9,200,000", "full_time_employees": "58"},          # the premises repeated
    {"location_number": "2", "building_number": "1", "address_line1": "1720 Westland Rd",
     "annual_revenue": "$800,000", "full_time_employees": "6", "part_time_employees": "1"},
]


def test_premises_rows_add_up_to_the_business_totals_each_premises_once():
    assert DS.location_totals(_LOCS[:1]) == {"revenue": 9_200_000, "full_time": 58, "part_time": 4}
    assert DS.location_totals(_LOCS) == {"revenue": 10_000_000, "full_time": 64, "part_time": 5}
    assert DS.location_totals([]) == {}
    d = _doc(1, "application", acord=True, property_locations=_LOCS, **_ID)
    DS.settle_acord_document(d)
    f = d["facts"]
    assert f["total_revenue"]["value"] == "$10,000,000"
    assert f["total_revenue"]["derived_from"] == DS.DERIVED_FROM_LOCATIONS
    assert f["num_employees_full_time"]["value"] == "64"
    assert f["num_employees_part_time"]["value"] == "5"
    assert f["num_employees"]["value"] == "69"
    DS.settle_acord_document(d)                                  # idempotent
    assert f["num_employees"]["value"] == "69"


def test_a_total_the_form_states_is_never_replaced_by_the_sum():
    d = _doc(1, "application", acord=True, property_locations=_LOCS, total_revenue="$12,000,000", **_ID)
    DS.settle_acord_document(d)
    assert d["facts"]["total_revenue"]["value"] == "$12,000,000"


def test_the_sum_meets_the_declarations_total_as_a_card_and_never_outvotes_it():
    dec = _doc(1, "dec_page", total_revenue="$8,450,000", num_employees="68", **_ID)
    app = _doc(2, "application", acord=True, property_locations=_LOCS[:1], **_ID)
    mf, docs = _merge([dec, app])
    assert mf["total_revenue"]["value"] == "$8,450,000"
    fields = {x["fact_key"]: x for x in _assess(mf, docs)["fields"]}
    assert fields["total_revenue"]["status"] == "conflict"
    assert fields["num_employees"]["status"] == "conflict"
    # nothing else states it: the sum is the package's figure
    mf2, _ = _merge([_doc(1, "dec_page", **_ID), _doc(2, "application", acord=True,
                                                      property_locations=_LOCS[:1], **_ID)])
    assert mf2["total_revenue"]["value"] == "$9,200,000"


def test_a_location_revenue_above_the_business_total_is_a_warning():
    from services.cross_form_validator import _check_location_revenue_over_total
    facts = {"total_revenue": "$8,450,000", "property_locations": _LOCS[:1]}
    issues = _check_location_revenue_over_total(facts, {}, set())
    assert len(issues) == 1 and issues[0]["type"] == "soft_warning"
    assert "$9,200,000" in issues[0]["message"] and "$8,450,000" in issues[0]["message"]
    assert not _check_location_revenue_over_total({"total_revenue": "$9,200,000",
                                                   "property_locations": _LOCS[:1]}, {}, set())
    assert not _check_location_revenue_over_total({"property_locations": _LOCS[:1]}, {}, set())
    from services.issue_registry import VERIFY_FIGURE_CODES, resolution_for
    assert "location_revenue_over_total" in VERIFY_FIGURE_CODES
    assert resolution_for("location_revenue_over_total")["facts"] == ["total_revenue"]


# ── 9. Address blocks ────────────────────────────────────────────────────────
@pytest.mark.parametrize("block,want", [
    ("4150 S Kalamath St\nSuite 210\nDenver CO 80223",
     {"line1": "4150 S Kalamath St", "line2": "Suite 210", "city": "Denver", "state": "CO", "zip": "80223"}),
    ("Bluestem Risk Advisors LLC\n320 E Mountain Ave\nSuite 4\nFort Collins CO 80524",
     {"line1": "320 E Mountain Ave", "line2": "Suite 4", "city": "Fort Collins", "state": "CO", "zip": "80524"}),
    ("PO Box 12\nCheyenne, WY 82001-1234",
     {"line1": "PO Box 12", "city": "Cheyenne", "state": "WY", "zip": "82001-1234"}),
])
def test_an_address_block_is_read_once(block, want):
    assert DS.parse_address_block(block) == want


def test_the_garbled_transcriber_address_is_one_clean_address():
    bad = "4150 S Kalamath St\nSuite 210\nDenver CO 80223, Suite 210, Denver, CO 80223"
    assert DS.repair_block_address(bad) == "4150 S Kalamath St, Suite 210, Denver, CO 80223"
    bad2 = "Bluestem Risk Advisors LLC\n320 E Mountain Ave\nSuite 4\nFort Collins, CO 80524, Suite 4, Fort Collins, CO 80524"
    assert DS.repair_block_address(bad2) == "320 E Mountain Ave, Suite 4, Fort Collins, CO 80524"
    assert DS.repair_block_address("4150 S Kalamath St, Denver, CO 80223") is None
    from utils.helpers import _parse_address
    p = _parse_address(DS.repair_block_address(bad))
    assert (p["line1"], p["line2"], p["city"], p["state"], p["zip"]) == (
        "4150 S Kalamath St", "Suite 210", "Denver", "CO", "80223")


def test_the_reader_never_appends_parts_the_block_states():
    from services.acord_intake.read import _compose_address
    parts = {"line1": "4150 S Kalamath St\nSuite 210\nDenver CO 80223", "line2": "Suite 210",
             "city": "Denver", "state": "CO", "zip": "80223"}
    assert _compose_address(parts) == "4150 S Kalamath St, Suite 210, Denver, CO 80223"
    assert _compose_address({"line1": "10 Main St", "city": "Denver", "state": "CO", "zip": "80202"}) \
        == "10 Main St, Denver, CO 80202"


def test_a_stored_garbled_address_is_settled_at_the_merge():
    d = _doc(1, "application", acord=True,
             mailing_address="4150 S Kalamath St\nSuite 210\nDenver CO 80223, Suite 210, Denver, CO 80223", **_ID)
    DS.settle_acord_document(d)
    assert d["facts"]["mailing_address"]["value"] == "4150 S Kalamath St, Suite 210, Denver, CO 80223"
    assert d["facts"]["mailing_address"]["source"] == "acord_form"


# ── LOC # is the premises', never the row's ─────────────────────────────────
def test_buildings_at_one_premises_share_its_loc_number():
    from services.extraction_service import assign_location_numbers
    # no numbers printed: two buildings at one street share LOC 1
    rows = [{"address_line1": "4150 S Kalamath St", "building_number": "1"},
            {"address_line1": "4150 S Kalamath St", "building_number": "2"},
            {"address_line1": "1720 Westland Rd", "building_number": "1"}]
    assign_location_numbers(rows)
    assert [(r["location_number"], r["building_number"]) for r in rows] == [("1", "1"), ("1", "2"), ("2", "1")]
    # a printed premises number decides; a building at its street with none takes it
    rows = [{"address_line1": "1720 Westland Rd", "premises_number": "2", "building_number": "1"},
            {"address_line1": "4150 S Kalamath St", "premises_number": "1", "building_number": "1"},
            {"address_line1": "4150 S Kalamath St", "building_number": "2"}]
    assign_location_numbers(rows)
    assert [r["location_number"] for r in rows] == ["2", "1", "1"]
    # one printed number claimed by two different streets decides nothing
    rows = [{"address_line1": "10 Main St", "premises_number": "1"},
            {"address_line1": "99 Oak Ave", "premises_number": "1"}]
    assign_location_numbers(rows)
    assert len({r["location_number"] for r in rows}) == 2
    # rows with no building numbers keep the old numbering (1, 2, 3)
    rows = [{"address_line1": "10 Main St"}, {"address_line1": "10 Main St", "address_line2": "Suite 2"},
            {"address_line1": "99 Oak Ave"}]
    assign_location_numbers(rows)
    assert [r["location_number"] for r in rows] == ["1", "2", "3"]


def test_the_merge_keeps_the_premises_number_an_acord_form_prints():
    dec_rows = [{"address": "4150 S Kalamath St, Denver, CO 80223", "building_number": "1", "total_building_area": "14,600"},
                {"address": "4150 S Kalamath St, Denver, CO 80223", "building_number": "2", "total_building_area": "22,000"},
                {"address": "1720 Westland Rd, Cheyenne, WY 82001", "building_number": "1", "total_building_area": "8,400"}]
    app_rows = [{"address_line1": "4150 S Kalamath St", "address_city": "Denver", "address_state": "CO",
                 "location_number": "1", "building_number": "2", "total_building_area": "25,000"}]
    mf, docs = _merge([_doc(1, "dec_page", property_locations=dec_rows, **_ID),
                       _doc(2, "application", acord=True, property_locations=app_rows, **_ID)])
    got = {(str(r.get("address_line1")), r.get("building_number")): r.get("location_number")
           for r in _rows(mf, "property_locations")}
    assert got[("4150 S Kalamath St", "1")] == "1" and got[("4150 S Kalamath St", "2")] == "1"
    assert got[("1720 Westland Rd", "1")] == "2"
    card = next(f for f in _assess(mf, docs)["fields"] if f.get("row_level"))
    assert "(Loc 1 Bldg 2 - 4150 S Kalamath St)" in card["label"]


# ── An address echo at a documented premises is that premises ───────────────
def _consolidated(rows, locations=()):
    from services.extraction_service import _consolidate_property_locations
    facts = {"property_locations": [dict(r) for r in rows], "locations": list(locations)}
    _consolidate_property_locations(facts)
    return facts["property_locations"]


_BLDGS_AT_ONE_STREET = [
    {"address": "4150 S Kalamath St, Denver, CO 80223", "building_number": "1",
     "construction_type": "Joisted Masonry", "building_value": "$2,350,000"},
    {"address": "4150 S Kalamath St, Denver, CO 80223", "building_number": "2",
     "construction_type": "Non-Combustible", "building_value": "$1,780,000"},
]


def test_an_address_only_echo_with_its_suite_joins_the_documented_premises():
    rows = _consolidated(_BLDGS_AT_ONE_STREET, ["4150 S Kalamath St, Suite 200, Denver, CO 80223"])
    assert len(rows) == 2
    assert [(r["location_number"], r["building_number"]) for r in rows] == [("1", "1"), ("1", "2")]
    from services.cross_form_validator import _check_per_location_cope_completeness
    assert not _check_per_location_cope_completeness({"property_locations": rows}, {}, {"ACORD_140"})


def test_a_separate_premises_or_one_with_its_own_data_stays():
    # a schedule row at another street (a loose address beside a schedule with
    # data is ruled out by the 5 Oct rule, unchanged)
    rows = _consolidated(_BLDGS_AT_ONE_STREET + [{"address": "1720 Westland Rd, Cheyenne, WY 82001"}])
    assert len(rows) == 3
    own = dict(address="4150 S Kalamath St, Suite 200, Denver, CO 80223", year_built="2001",
               construction_type="Frame")
    assert len(_consolidated(_BLDGS_AT_ONE_STREET + [own])) == 3      # its own building data
    third = dict(address="4150 S Kalamath St, Denver, CO 80223", building_number="3")
    assert len(_consolidated(_BLDGS_AT_ONE_STREET + [third])) == 3    # its own building number


def test_the_same_street_in_another_city_or_zip_is_another_premises():
    other_city = {"address": "4150 S Kalamath St, Englewood, CO 80110"}
    assert len(_consolidated(_BLDGS_AT_ONE_STREET + [other_city])) == 3
    other_zip = {"address": "4150 S Kalamath St, Denver, CO 80219"}
    assert len(_consolidated(_BLDGS_AT_ONE_STREET + [other_zip])) == 3
    # no city / ZIP on one side: still the documented premises
    assert len(_consolidated(_BLDGS_AT_ONE_STREET + [{"address": "4150 S Kalamath St"}])) == 2
    assert len(_consolidated(_BLDGS_AT_ONE_STREET, ["4150 S Kalamath St, Suite 200, Denver, CO 80223-1102"])) == 2
