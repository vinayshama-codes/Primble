"""The one door for fixed-format identifiers (30 Oct 2026, owner: globally)."""
import pytest

from services import identifier_checks as I
from services.issue_registry import classify_legacy, resolution_for


def _p(v):
    return {"value": v, "source": "producer", "confidence": "filled"}


def _codes(facts):
    return set(I.impossible_identifiers(facts))


# ── flagged ──────────────────────────────────────────────────────────────────
@pytest.mark.parametrize("facts,code", [
    ({"auto_vin_schedule": [{"vin": "1FTBR1C82PKA4182", "year": "2023"}]}, "legacy_auto_vin_incomplete"),
    ({"auto_vin_schedule": [{"vin": "1FTBR1C82PKA41827X"}]}, "legacy_auto_vin_incomplete"),
    ({"carrier_naic": "251861"}, "legacy_carrier_naic_format"),
    ({"prior_carrier_naic": "251"}, "legacy_prior_carrier_naic_format"),   # own card, own box (30 Oct)
    ({"property_locations": [{"address_state": "CO", "address_zip": "8021"}]}, "legacy_location_zip_format"),
    ({"property_locations": [{"address_state": "TX", "address_zip": "770011"}]}, "legacy_location_zip_format"),
    ({"physical_address": "1 Main St, Denver, CO 8021"}, "legacy_physical_zip_format"),
    ({"applicant_business_phone": "123-456-7890"}, "legacy_us_phone_format"),
    ({"applicant_business_phone": "303-555-012"}, "legacy_us_phone_format"),
    ({"contact_phone": "303-055-0123"}, "legacy_contact_phone_format"),    # own card, own box (30 Oct)
    ({"umbrella_effective_date": "07/15/2026", "umbrella_expiration_date": "07/15/2025"},
     "legacy_umbrella_term_backwards"),
])
def test_flagged(facts, code):
    assert code in _codes(facts)


# ── not flagged: the false-positive guards ───────────────────────────────────
@pytest.mark.parametrize("facts", [
    {"auto_vin_schedule": [{"vin": "1FTBR1C82PKA41827", "year": "2023"}]},
    {"auto_vin_schedule": [{"vin": "1GCZGHFP5", "year": "1975"}]},          # pre-1981
    {"auto_vin_schedule": [{"vin": "", "year": "2024"}]},
    {"carrier_naic": "25186"}, {"carrier_naic": "2518"},                    # dropped leading zero
    {"carrier_naic": "Pending"},
    {"property_locations": [{"address_state": "CO", "address_zip": "80216"}]},
    {"property_locations": [{"address_state": "CO", "address_zip": "80216-1234"}]},
    {"property_locations": [{"address_state": "ON", "address_zip": "M5V 2T6"}]},  # Canada
    {"property_locations": [{"address_state": "", "address_zip": "2000"}]},       # no US state
    {"physical_address": "10 Downing St, London SW1A 2AA"},
    {"physical_address": "1 Main St, Denver, CO 80216"},
    {"applicant_business_phone": "800-555-0199"},                           # toll free
    {"applicant_business_phone": "(303) 555-0123 ext. 42"},                 # extension
    {"applicant_business_phone": "1-303-555-0123"},
    {"applicant_business_phone": "+44 20 7946 0958"},                       # international
    {"applicant_business_phone": "Not provided"},
    {"umbrella_effective_date": "01/01/2026", "umbrella_expiration_date": "07/01/2026"},  # 6 months
    {"umbrella_effective_date": "01/01/2026", "umbrella_expiration_date": "01/01/2029"},  # 3 years
    {"umbrella_effective_date": "garbled", "umbrella_expiration_date": "01/01/2025"},
])
def test_not_flagged(facts):
    assert _codes(facts) == set()


def test_fein_rule():
    assert I.fein_is_impossible("12-345678")
    assert I.fein_is_impossible("00-0000000")
    assert not I.fein_is_impossible("12-3456789")
    assert not I.fein_is_impossible("Applied for")
    from utils.validators import run_field_validations
    assert not any("FEIN" in m for m in run_field_validations({"fein": "Applied for"})[1])
    assert any("FEIN" in m for m in run_field_validations({"fein": "12-345678"})[1])


# ── a person's value is never flagged ────────────────────────────────────────
def test_person_values_are_never_flagged():
    from utils.validators import run_field_validations
    assert _codes({"carrier_naic": _p("251861"), "applicant_business_phone": _p("123-456-7890"),
                   "physical_address": _p("1 Main St, Denver, CO 8021"),
                   "umbrella_effective_date": _p("07/15/2026"),
                   "umbrella_expiration_date": _p("07/15/2025")}) == set()
    assert not any("FEIN" in m for m in run_field_validations({"fein": _p("12-345678")})[1])
    from services.schedule_capture import mark_human_rows
    facts = {"auto_vin_schedule": [{"vin": "1FTBR1C82PKA4182", "year": "2023"}]}
    assert _codes(facts) == {"legacy_auto_vin_incomplete"}
    mark_human_rows(facts, "auto_vin_schedule", "producer")
    assert _codes(facts) == set()


# ── each warning opens its own fix ───────────────────────────────────────────
def test_every_rule_routes_to_its_fix():
    for rule in I.WARNING_RULES:
        msg = I.warning_message(rule, ["x"])
        code = classify_legacy(msg, "soft_warning")[0]
        assert code == rule.code, (msg, code)
        res = resolution_for(code)
        assert res and res["mode"] in ("field", "schedule")
        if rule.home[0] == "schedule":
            assert res.get("schedule_key") == rule.home[1]
        else:
            assert set(res["facts"]) == set(rule.home[1:])


def test_evaluate_stops_raises_one_warning_per_rule():
    from services.sqs_service import evaluate_stops
    _h, soft = evaluate_stops({"carrier_naic": "251861", "prior_carrier_naic": "1"}, {})
    assert sum(m.startswith("Carrier NAIC code is not 5 digits") for m in soft) == 1


def test_probe_corrects_an_impossible_cell():
    assert I.cell_is_impossible("property_locations", "address_zip",
                                {"address_state": "CO", "address_zip": "8021"})
    assert not I.cell_is_impossible("property_locations", "address_zip",
                                    {"address_state": "CO", "address_zip": "80202"})
    from services.review_plan import _column_probe
    assert _column_probe({"key": "address_zip", "type": "text"}) == "80202"



def test_each_card_offers_only_the_box_that_is_wrong():
    from services.identifier_checks import WARNING_RULES
    for r in WARNING_RULES:
        if r.code == "legacy_umbrella_term_backwards":
            continue                     # either date of a backwards term may be the wrong one
        assert r.home[0] == "schedule" or len(r.home) == 2, (r.code, r.home)
