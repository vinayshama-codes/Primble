"""
BUG-01 / BUG-02 (client report, 2026-09-08): the client questionnaire showed
1/11 = 9% complete, a green "answers ready" badge and an "Auto-saving in
progress" banner before the client had answered anything.

Root cause: progress measured whether a field HELD content, not whether the
CLIENT put it there. A schedule question ships pre-filled with the rows
extraction found (deliberate - the client edits a known fleet instead of
retyping it), so it counted itself the moment the page loaded.

The same confusion ran three layers deeper than the progress bar, and those are
what this file pins - the counter itself lives in the React component:

  * `submit_arq_answers` stored an untouched pre-filled table as a client
    answer, which re-wrote `facts`, re-stamped the forms and logged a
    `client_arq` audit row for rows the insured never scrolled to;
  * the receipt told the client "2 vehicles provided" for that same table, and
    filed a table they had deliberately EMPTIED as if they had ignored it;
  * `fields_answered_count` was `len(posted_answers)`, and the questionnaire
    posts every question back - so it was the question count, always.

The rule, one sentence, and it is the same sentence in the browser and here:
a question counts when the client TOUCHED it and there is content on one side
or the other (theirs now, or ours that they cleared).
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

os.environ.setdefault("FIELD_ENCRYPTION_KEY", "kZ0aQ7Yy3pR8mN2vB6xL9tJ4hG1sD5fW8cE0uI3oA7k=")

from services import schedule_capture                      # noqa: E402
from services.arq_service import (                         # noqa: E402
    client_supplied_schedule,
    _restamp_schedule_into_forms,
)
from services.arq_receipt_service import (                 # noqa: E402
    KIND_BLANK,
    KIND_SCHEDULE,
    build_receipt_payload,
)

VEH = "auto_vin_schedule"
FIELD = schedule_capture.answer_key(VEH)

# The client's real shape: rows extraction found, sent to them pre-filled.
SEED = [
    {"year": "2012", "make": "Subaru", "model": "Impreza", "vin": "4S4BRCGC9C3217772"},
    {"year": "2019", "make": "Ford", "model": "Transit", "vin": "1FTYE1YM5KKA33191"},
]


def _q(current_rows=None, field_name=FIELD):
    return {
        "field_name":   field_name,
        "question":     "Please confirm the vehicles on the policy",
        "field_type":   "schedule",
        "schedule_key": VEH,
        "current_rows": current_rows if current_rows is not None else [],
    }


def _clean(rows):
    """What the round trip does to rows before either side compares them."""
    out, _ = schedule_capture.validate_rows(VEH, rows)
    return out


# -- seed_rows ---------------------------------------------------------------

def test_seed_rows_returns_what_we_prefilled():
    assert schedule_capture.seed_rows(_q(SEED)) == _clean(SEED)


def test_seed_rows_is_empty_when_nothing_was_prefilled():
    assert schedule_capture.seed_rows(_q([])) == []


def test_seed_rows_never_raises_on_a_malformed_question():
    # An unknown key, a missing name and a junk payload all mean the same safe
    # thing: we pre-filled nothing.
    assert schedule_capture.seed_rows({}) == []
    assert schedule_capture.seed_rows({"field_name": "schedule::not_a_real_key"}) == []
    assert schedule_capture.seed_rows(_q("not-a-list")) == []


def test_seed_rows_survives_the_full_round_trip():
    """The seed goes client_view -> browser JSON -> _sanitize_answers -> submit.
    Each leg re-validates, so the comparison is only sound if that is idempotent.
    """
    once = _clean(SEED)
    twice = _clean(once)
    thrice = _clean(twice)
    assert once == twice == thrice == schedule_capture.seed_rows(_q(SEED))


def test_every_shipped_schedule_is_idempotent_under_validation():
    """Guards the assumption above for schedules that do not exist yet: a new
    ScheduleDef whose validator rewrites its own output would silently make
    every untouched table look edited."""
    for key in schedule_capture.SCHEDULE_DEFS:
        cols = [c["key"] for c in schedule_capture.get_def(key)["columns"]]
        raw = [{c: "  v%d  " % i for c in cols[:3]} for i in range(3)]
        once, _ = schedule_capture.validate_rows(key, raw)
        twice, _ = schedule_capture.validate_rows(key, once)
        assert once == twice, "%s validate_rows is not idempotent" % key


# -- client_supplied_schedule: the one rule ----------------------------------

def test_untouched_prefilled_table_is_not_a_client_answer():
    """The reported bug, at the layer that decides provenance."""
    assert client_supplied_schedule(_q(SEED), _clean(SEED), touched=False) is False


def test_edited_table_is_a_client_answer():
    edited = _clean(SEED + [{"year": "2024", "make": "Ram", "model": "1500",
                             "vin": "1C6SRFFT8RN123456"}])
    assert client_supplied_schedule(_q(SEED), edited, touched=True) is True


def test_edited_table_is_detected_from_the_seed_alone():
    """An older cached page sends no touch list at all. The server still gets it
    right, because it compares against its OWN copy of the seed."""
    edited = _clean(SEED[:1])
    assert client_supplied_schedule(_q(SEED), edited, touched=False) is True


def test_emptying_a_prefilled_table_is_an_answer():
    """"Those are not our vehicles" is a real answer and must be applied - the
    form would otherwise keep printing them."""
    assert client_supplied_schedule(_q(SEED), [], touched=True) is True


def test_emptying_is_an_answer_without_the_touch_list_too():
    assert client_supplied_schedule(_q(SEED), [], touched=False) is True


def test_opening_and_closing_an_empty_table_is_not_an_answer():
    """Nothing pre-filled and nothing entered. Touch alone must not count, or a
    stray tap would report progress."""
    assert client_supplied_schedule(_q([]), [], touched=True) is False


def test_filling_a_table_we_could_not_prefill_is_an_answer():
    assert client_supplied_schedule(_q([]), _clean(SEED), touched=True) is True


def test_deleted_then_retyped_identically_is_still_the_clients_answer():
    """The case a pure seed-vs-now diff gets wrong: the client removed our rows
    and typed the same values back. The rows match the seed, so only the touch
    flag can tell us they did the work."""
    assert client_supplied_schedule(_q(SEED), _clean(SEED), touched=True) is True


def test_a_faked_touch_flag_cannot_invent_content():
    """Worst case for trusting the browser: `touched` is attacker-controlled.
    It can only re-assert rows we ourselves sent, never manufacture any."""
    assert client_supplied_schedule(_q([]), [], touched=True) is False


@pytest.mark.parametrize("key", list(schedule_capture.SCHEDULE_DEFS))
def test_rule_holds_for_every_schedule_type(key):
    """Generic across all six shipped schedules, so no table type is quietly
    exempt - including the producer-only one, which must refuse every case."""
    cols = [c["key"] for c in schedule_capture.get_def(key)["columns"]]
    rows_raw = [{c: "val%d" % i for c in cols[:2]} for i in range(2)]
    rows, _ = schedule_capture.validate_rows(key, rows_raw)
    q = {"field_name": schedule_capture.answer_key(key),
         "schedule_key": key, "current_rows": rows_raw}
    producer_only = schedule_capture.is_producer_only(key)
    assert client_supplied_schedule(q, rows, touched=False) is False      # untouched
    assert client_supplied_schedule(q, rows[:1], touched=False) is (not producer_only)
    assert client_supplied_schedule(q, [], touched=True) is (not producer_only)


# -- guards on the "emptied is an answer" rule -------------------------------
# Both exist because that rule turns ZERO ROWS into a destructive write, and
# zero rows is also what an incomplete request looks like.

def test_a_table_missing_from_the_payload_is_not_a_deletion():
    """A retry, a truncated body or an older client that posts a subset would
    otherwise read as "the client cleared the fleet" and wipe it."""
    assert client_supplied_schedule(_q(SEED), [], touched=False, present=False) is False


def test_absence_beats_even_a_touch_claim():
    """Presence is structural and is checked first, so no combination of
    browser-supplied flags can turn a missing field into a deletion."""
    assert client_supplied_schedule(_q(SEED), [], touched=True, present=False) is False


def test_a_producer_only_table_is_never_a_client_answer():
    """`wc_officers` is never rendered to the insured (client_view drops it), so
    an answer for one can only come from a crafted payload. Refused whatever it
    claims - otherwise a client could empty the agency's own officers table."""
    key = "wc_officers"
    assert schedule_capture.is_producer_only(key) is True
    rows_raw = [{"name": "Jane Doe", "title": "President"}]
    rows, _ = schedule_capture.validate_rows(key, rows_raw)
    q = {"field_name": schedule_capture.answer_key(key),
         "schedule_key": key, "current_rows": rows_raw}
    assert client_supplied_schedule(q, [], touched=True, present=True) is False
    assert client_supplied_schedule(q, rows, touched=True, present=True) is False
    assert client_supplied_schedule(q, rows * 2, touched=True, present=True) is False


def test_a_client_table_is_still_accepted_when_present():
    """The guards above must not have closed the door on the real path."""
    assert client_supplied_schedule(_q(SEED), [], touched=True, present=True) is True


# -- receipt -----------------------------------------------------------------

def _arq(questions, answers, not_sure=None):
    return {
        "id": "arq-1", "session_id": "sess-1", "user_id": "user-1",
        "client_name": "Acme Roofing LLC", "email": "owner@acme.test",
        "submitted_at": "2026-09-08T10:00:00+00:00",
        "questions": questions, "answers": answers,
        "not_sure_fields": not_sure or [], "review_fields": [],
    }


def test_receipt_does_not_credit_an_untouched_prefilled_table():
    """Nothing is stored for it (submit drops it), so it reads as blank rather
    than telling the client they provided two vehicles."""
    p = build_receipt_payload(_arq([_q(SEED)], {}))
    assert p["items"][0]["kind"] == KIND_BLANK
    assert p["answered_count"] == 0


def test_receipt_records_an_emptied_prefilled_table_as_an_answer():
    p = build_receipt_payload(_arq([_q(SEED)], {FIELD: "[]"}))
    assert p["items"][0]["kind"] == KIND_SCHEDULE
    assert p["items"][0]["row_count"] == 0
    assert p["answered_count"] == 1


def test_receipt_keeps_an_empty_table_with_no_prefill_blank():
    """Unchanged from before the fix - pinned so the new "emptied is an answer"
    rule cannot leak into the case where there was nothing to empty."""
    p = build_receipt_payload(_arq([_q([])], {FIELD: "[]"}))
    assert p["items"][0]["kind"] == KIND_BLANK
    assert p["answered_count"] == 0


def test_receipt_still_reports_a_real_fleet():
    full = _clean(SEED + [{"year": "2024", "make": "Ram", "model": "1500",
                           "vin": "1C6SRFFT8RN123456"}])
    p = build_receipt_payload(
        _arq([_q(SEED)], {FIELD: schedule_capture.encode_answer(full)}))
    assert p["items"][0]["kind"] == KIND_SCHEDULE
    assert p["items"][0]["row_count"] == 3
    assert p["answered_count"] == 1


# -- orphaned row sweep ------------------------------------------------------
#
# Live run 2026-09-08: the client deleted both vehicles, the form blanked year /
# make / model / VIN, and kept printing a garaging address of "2140 Harbor Way",
# a $1,000 collision deductible and a full set of ticked coverage boxes for a
# unit with no identity. Only 9 of ACORD 127's 67 per-vehicle fields are bound
# to the capture table; the other 58 come from Pass 1 and answered to nobody
# once the row they described was gone.

import json                                                   # noqa: E402
import os as _os                                               # noqa: E402

_SCHEMA_DIR = _os.path.join(_os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))),
                            "forms_schemas")


def _schema(form_id):
    with open(_os.path.join(_SCHEMA_DIR, f"{form_id}_schema.json"), encoding="utf-8") as fh:
        return json.load(fh)


def _form_127(rows=("A", "B")):
    """A 127 stamped the way Pass 1 leaves it: identity AND the unbound cells,
    plus non-vehicle data that must survive untouched."""
    fs = {}
    for L in rows:
        fs[f"Vehicle_VINIdentifier_{L}"] = f"VIN{L}"
        fs[f"Vehicle_ManufacturersName_{L}"] = f"Make{L}"
        fs[f"Vehicle_PhysicalAddress_LineOne_{L}"] = "2140 Harbor Way"
        fs[f"Vehicle_PhysicalAddress_CityName_{L}"] = "Tacoma"
        fs[f"Vehicle_Collision_DeductibleAmount_{L}"] = "1,000"
        fs[f"Vehicle_Coverage_LiabilityIndicator_{L}"] = "X"
        fs[f"Vehicle_RadiusOfUse_{L}"] = "50"
    fs["NamedInsured_FullName_A"] = "Harborline Freight Services LLC"
    fs["Producer_FullName_A"] = "Cascade Commercial Insurance Group LLC"
    fs["Driver_GivenName_A"] = "Dana"
    return {"ACORD_127": {"schema": _schema("ACORD_127"), "field_state": fs,
                          "confidence": {}, "client_filled_fields": []}}


def _live(gen, prefix="Vehicle_"):
    fs = gen["ACORD_127"]["field_state"]
    return {k: v for k, v in fs.items() if k.startswith(prefix) and str(v).strip()}


def test_emptying_the_fleet_clears_the_whole_row_not_just_the_identity():
    """The reported defect. Nothing about a vehicle may survive the vehicle."""
    gen = _form_127()
    _restamp_schedule_into_forms(gen, "auto_vin_schedule", {"auto_vin_schedule": []})
    assert _live(gen) == {}


def test_the_sweep_never_touches_anything_outside_the_fleet():
    """`NamedInsured_A` is the APPLICANT, not a schedule row. Producer and
    driver data belong to other families. All three must survive an emptied
    fleet - this is the case a bare `_A` suffix rule would destroy."""
    gen = _form_127()
    _restamp_schedule_into_forms(gen, "auto_vin_schedule", {"auto_vin_schedule": []})
    fs = gen["ACORD_127"]["field_state"]
    assert fs["NamedInsured_FullName_A"] == "Harborline Freight Services LLC"
    assert fs["Producer_FullName_A"] == "Cascade Commercial Insurance Group LLC"
    assert fs["Driver_GivenName_A"] == "Dana"


def test_a_surviving_row_keeps_every_one_of_its_cells():
    """Only rows with nothing behind them are swept. Row A keeps its garaging
    address, deductible and radius - those are still true of a real vehicle."""
    gen = _form_127()
    _restamp_schedule_into_forms(gen, "auto_vin_schedule", {"auto_vin_schedule": [
        {"year": "2019", "make": "Freightliner", "model": "M2 106",
         "vin": "1FVACWDT9KHKM4471"},
    ]})
    live = _live(gen)
    assert live["Vehicle_PhysicalAddress_LineOne_A"] == "2140 Harbor Way"
    assert live["Vehicle_Collision_DeductibleAmount_A"] == "1,000"
    assert live["Vehicle_RadiusOfUse_A"] == "50"
    assert live["Vehicle_ManufacturersName_A"] == "Freightliner"
    # Row B had a vehicle and no longer does - it goes entirely.
    assert not [k for k in live if k.endswith("_B")]


def test_shrinking_the_fleet_clears_only_the_rows_that_went():
    gen = _form_127(rows=("A", "B", "C"))
    _restamp_schedule_into_forms(gen, "auto_vin_schedule", {"auto_vin_schedule": [
        {"year": "2019", "make": "Freightliner", "model": "M2 106", "vin": "V1"},
        {"year": "2021", "make": "Isuzu", "model": "NPR-HD", "vin": "V2"},
    ]})
    live = _live(gen)
    assert [k for k in live if k.endswith("_A")]
    assert [k for k in live if k.endswith("_B")]
    assert not [k for k in live if k.endswith("_C")]


def test_sweep_is_a_no_op_when_the_fleet_is_unchanged():
    gen = _form_127()
    before = dict(gen["ACORD_127"]["field_state"])
    _restamp_schedule_into_forms(gen, "auto_vin_schedule", {"auto_vin_schedule": [
        {"vin": "VINA", "make": "MakeA"}, {"vin": "VINB", "make": "MakeB"},
    ]})
    after = gen["ACORD_127"]["field_state"]
    for k, v in before.items():
        if k.startswith(("NamedInsured_", "Producer_", "Driver_")):
            assert after[k] == v


def test_ambiguous_roots_own_nothing():
    """`WorkersCompensation` is a root of BOTH wc_class_codes and wc_officers,
    so neither may claim it - clearing one schedule would wipe the other's
    rows. Derived, so a future ScheduleDef sharing a root is safe by default."""
    assert schedule_capture.row_family_roots("wc_class_codes") == frozenset()
    assert "WorkersCompensation" not in schedule_capture.row_family_roots("wc_officers")
    assert schedule_capture.row_family_roots("wc_officers") == frozenset({"Officer", "Owner"})


def test_named_insured_is_never_a_family_root():
    """It is a root of `additional_named_insureds`, which is not a capturable
    table - and `NamedInsured_A` is the applicant on most forms."""
    for key in schedule_capture.SCHEDULE_DEFS:
        assert "NamedInsured" not in schedule_capture.row_family_roots(key)


def test_row_family_roots_are_unknown_safe():
    assert schedule_capture.row_family_roots("not_a_schedule") == frozenset()


@pytest.mark.parametrize("key", list(schedule_capture.SCHEDULE_DEFS))
def test_no_root_is_claimed_by_two_schedules(key):
    """The invariant the guard exists to hold, stated directly."""
    mine = schedule_capture.row_family_roots(key)
    for other in schedule_capture.SCHEDULE_DEFS:
        if other == key:
            continue
        assert not (mine & schedule_capture.row_family_roots(other)), (
            f"{key} and {other} both claim {mine & schedule_capture.row_family_roots(other)}"
        )


# -- the row-letter is not a row index --------------------------------------
#
# Adversarial audit 2026-09-08, confirmed by reproduction: the orphan sweep
# cleared every field whose ROOT belonged to the schedule, and `_A` is ACORD's
# universal field suffix rather than a row index. On ACORD 125 the
# `BusinessInformation` root - a legitimate `property_locations` root - also
# carries the 12 nature-of-business checkboxes and the parent organisation name,
# all of which exist ONLY at `_A`; `LossHistory` carries the No Prior Losses
# attestation the same way. So a client answering "we have no separate
# locations" erased the contractor's own trade classification, and one answering
# "no claims" erased the no-known-losses tick that the score reads.
#
# The fix is structural: a field is part of a repeating row only when its base
# name appears at MORE THAN ONE row letter on that form.

def _form_125(extra=None):
    fs = {
        "BusinessInformation_BusinessType_ContractorIndicator_A": "X",
        "BusinessInformation_BusinessType_ServiceIndicator_A": "X",
        "BusinessInformation_ParentOrganizationName_A": "Harborline Holdings Inc",
        "LossHistory_NoPriorLossesIndicator_A": "X",
        "LossHistory_TotalAmount_A": "0",
        "LossHistory_InformationYearCount_A": "5",
        "NamedInsured_FullName_A": "Harborline Freight Services LLC",
    }
    fs.update(extra or {})
    return {"ACORD_125": {"schema": _schema("ACORD_125"), "field_state": fs,
                          "confidence": {}, "client_filled_fields": []}}


@pytest.mark.parametrize("list_key", ["property_locations", "loss_history"])
def test_emptying_a_table_never_erases_applicant_level_fields(list_key):
    """The reproduction. Both of these roots are real roots of a real schedule,
    and both carry applicant data at `_A` that no client answer may destroy."""
    gen = _form_125()
    before = dict(gen["ACORD_125"]["field_state"])
    _restamp_schedule_into_forms(gen, list_key, {list_key: []})
    assert gen["ACORD_125"]["field_state"] == before


def test_the_no_prior_losses_attestation_survives_an_empty_loss_table():
    """Named separately because it also feeds the score: `LossHistory_
    NoPriorLossesIndicator` is the ~5-point attestation, and "I have no claims"
    is the single most likely reason a client empties that table."""
    gen = _form_125()
    _restamp_schedule_into_forms(gen, "loss_history", {"loss_history": []})
    assert gen["ACORD_125"]["field_state"]["LossHistory_NoPriorLossesIndicator_A"] == "X"


def test_single_slot_fields_are_never_swept_on_any_form_or_schedule():
    """The invariant, stated over every real schema: a base name that appears at
    exactly one row letter is not a row, whatever its root says."""
    import re
    row_re = re.compile(r"^(.+)_([A-N])$")
    for form_id in ("ACORD_125", "ACORD_127", "ACORD_140"):
        schema = _schema(form_id)
        letters = {}
        for f in schema:
            m = row_re.match(f)
            if m:
                letters.setdefault(m.group(1), set()).add(m.group(2))
        singles = {f for f in schema
                   if row_re.match(f)
                   and len(letters[row_re.match(f).group(1)]) == 1}
        if not singles:
            continue
        for list_key in schedule_capture.SCHEDULE_DEFS:
            if not schedule_capture.row_family_roots(list_key):
                continue
            fs = {f: "SENTINEL" for f in singles}
            gen = {form_id: {"schema": schema, "field_state": fs,
                             "confidence": {}, "client_filled_fields": []}}
            _restamp_schedule_into_forms(gen, list_key, {list_key: []})
            kept = gen[form_id]["field_state"]
            lost = [f for f in singles if kept.get(f) != "SENTINEL"]
            assert not lost, f"{form_id}/{list_key} erased single-slot fields: {lost[:5]}"


def test_a_real_repeating_row_is_still_swept_completely():
    """The guard must not have disarmed the fix: ACORD 127's vehicle family is
    genuinely multi-row (all 67 bases), so an emptied fleet still clears whole."""
    gen = _form_127()
    _restamp_schedule_into_forms(gen, "auto_vin_schedule", {"auto_vin_schedule": []})
    assert _live(gen) == {}


# -- the year message has to describe the rule it enforces -------------------
#
# Reported live: typing 2122 - four digits - produced "Year must be a 4-digit
# year". The regex (1900-2099) was right; the sentence named a rule the value
# already satisfied, so the client had no way to act on it.

def test_year_error_states_the_rule_actually_enforced():
    _, report = schedule_capture.validate_rows(
        "auto_vin_schedule", [{"year": "2122", "make": "Isuzu", "model": "NPR-HD"}])
    msg = report["errors"]["0"]["year"]
    assert "1900" in msg and "2099" in msg
    assert "4-digit" not in msg, "a four-digit value must never be told it is not four digits"


@pytest.mark.parametrize("year,ok", [
    ("2019", True), ("1900", True), ("2099", True),
    ("2122", False), ("1899", False), ("99", False), ("abcd", False),
])
def test_year_rule_itself_is_unchanged(year, ok):
    """Only the wording moved. The accepted range must be exactly as before."""
    _, report = schedule_capture.validate_rows(
        "auto_vin_schedule", [{"year": year, "make": "X", "model": "Y"}])
    assert (report["errors"].get("0", {}).get("year") is None) is ok
