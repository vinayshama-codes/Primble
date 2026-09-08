"""Three form-fill defects found on the H5 live run (2026-09-02).

None of them is H5 - the multi-carrier roster and the INSR LTR join both passed
every check on both packages. These were found by reading the rest of the
generated ACORD 25 and 125 line by line, and all three share ONE root cause:

    a box whose ACORD tooltip declares a free-text or date type had no shape
    test that a nearby value could fail, so gap fill wrote whatever stood
    beside it on the dec page.

  D1  ACORD 125 "DATE BUSINESS STARTED (MM/DD/YYYY)" printed "9" on one
      package and "6" on another - the `years_in_business` fact. The mapping
      rule is correct; the value was invented, and the date check only asked
      "does it contain a digit".
  D2  ACORD 25 "GEN'L AGGREGATE LIMIT APPLIES PER - OTHER:" printed
      "$2,000,000", describing nothing and duplicating the General Aggregate
      limit printed one column to its right. `text` was the one declared type
      with no shape test at all.
  D3  ACORD 125 ADDITIONAL INTEREST named "Dana Ostrander" - the PRODUCER
      CONTACT from the contact block of the same form - with a vehicle from
      the fleet schedule as its item description.

Every fix here is a REFUSAL, so each test carries a positive control proving
the refusal did not also blank legitimate data. That is the standing rule for
this class: a guard that is necessary but not sufficient needs a structural
second condition, and the adversarial case is written first.
"""
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from services import pdf_service as ps                        # noqa: E402

BACKEND = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def s125():
    return json.loads(
        (BACKEND / "forms_schemas" / "ACORD_125_schema.json").read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def s25():
    return json.loads(
        (BACKEND / "forms_schemas" / "ACORD_25_schema.json").read_text(encoding="utf-8"))


# =============================================================================
# D1 - a bare count is not a date
# =============================================================================

_START_DATE = "NamedInsured_BusinessStartDate_A"


@pytest.mark.parametrize("value", ["9", "6", "14", "22", "3", "127", " 9 ", "9."])
def test_a_bare_count_never_prints_as_the_business_start_date(s125, value):
    """The live values. `years_in_business` is a COUNT; this box asks for a
    date, and a count in it is a wrong value on a filed application."""
    assert ps._rejects_declared_type(_START_DATE, s125[_START_DATE], value, s125)


@pytest.mark.parametrize("value", [
    "07/25/2025", "2025-07-25", "July 25, 2025", "25-Jul-25", "7/1/25",
    "01/01/2026", "Jan 1, 2026", "2017", "2026", "03/1998", "09232026",
])
def test_every_real_date_printing_still_survives(s125, value):
    """POSITIVE CONTROL. A date carries a separator, a month word or four
    digits - the refusal above cannot reach any of them."""
    assert ps._rejects_declared_type(_START_DATE, s125[_START_DATE], value, s125) is None


def test_the_refusal_is_scoped_to_date_fields(s125):
    """A bare count is perfectly good in a COUNT box - the refusal must not
    leak into one."""
    for field in ("NamedInsured_YearsInBusiness_A", "BusinessInformation_YearsInBusiness_A"):
        meta = s125.get(field)
        if meta:
            assert ps._rejects_declared_type(field, meta, "9", s125) is None


def test_every_date_field_in_all_17_schemas_accepts_a_real_date():
    """The refusal is added to a shared function, so it is swept across every
    date-declared field on every form, not just the one that failed."""
    import glob
    checked = 0
    for path in glob.glob(str(BACKEND / "forms_schemas" / "*_schema.json")):
        schema = json.loads(Path(path).read_text(encoding="utf-8"))
        for field, meta in schema.items():
            if ps._tooltip_declared_type(meta) != "date":
                continue
            checked += 1
            for good in ("07/25/2025", "Jan 1, 2026", "2026"):
                assert ps._rejects_declared_type(field, meta, good, schema) is None, \
                    f"{field} rejected a real date {good!r}"
            assert ps._rejects_declared_type(field, meta, "9", schema), \
                f"{field} accepted a bare count"
    assert checked > 50, f"only {checked} date fields swept - the harvest looks wrong"


# =============================================================================
# D2 - a description is not an amount
# =============================================================================

_AGG_OTHER = "GeneralLiability_GeneralAggregate_LimitAppliesToCode_A"


@pytest.mark.parametrize("value", [
    "$2,000,000", "2,000,000", "$1,000,000", "$58,900.00", "$0", "1,000,000.00",
])
def test_a_money_figure_never_prints_as_a_description(s25, value):
    """The live defect: the box asks what OTHER basis the aggregate applies to
    and printed the aggregate amount."""
    assert ps._rejects_declared_type(_AGG_OTHER, s25[_AGG_OTHER], value, s25)


@pytest.mark.parametrize("value", [
    "Per Project", "Per Location", "Location", "Windstorm $5,000 deductible",
    "$1M excess of primary", "See schedule", "Statutory", "1200 Industrial Way",
    "Roofing - residential and commercial", "5", "2026", "CO 80202",
])
def test_a_real_description_still_survives(s25, value):
    """POSITIVE CONTROL, and the reason the rule is 'ENTIRELY a money figure'
    rather than 'contains one': these boxes exist to say something a number
    cannot, and a description that MENTIONS an amount is doing its job."""
    assert ps._rejects_declared_type(_AGG_OTHER, s25[_AGG_OTHER], value, s25) is None


def test_the_money_rule_does_not_reach_amount_boxes(s25):
    """A money figure is exactly what an amount box wants. The new refusal is
    scoped to `text`, and this proves it."""
    amount_field = "GeneralLiability_GeneralAggregate_LimitAmount_A"
    assert ps._rejects_declared_type(
        amount_field, s25[amount_field], "$2,000,000", s25) is None


# =============================================================================
# D3 - an interest named for another party on the same form
# =============================================================================

def test_the_producer_contact_is_not_an_additional_interest():
    """The live row: FullName = the producer contact printed in the contact
    block of the same form, item description = a vehicle off the fleet
    schedule. It carried no address, phone or e-mail, so every existing borrow
    test was blind to it and the name anchored the row as a real entity."""
    mapped = {
        "Producer_ContactPerson_FullName_A": "Dana Ostrander",
        "AdditionalInterest_FullName_A": "Dana Ostrander",
        "AdditionalInterest_ItemDescription_A": "Ford F-250 VIN 1FT7W2BT5MED12345",
    }
    gpt = {"AdditionalInterest_FullName_A", "AdditionalInterest_ItemDescription_A"}
    dropped = ps._drop_fabricated_interest_rows(mapped, gpt, {})

    assert "AdditionalInterest_FullName_A" in dropped
    assert mapped["AdditionalInterest_FullName_A"] is None
    # The row dies WHOLE - atomicity, the same principle the guard already
    # applies to a borrowed address.
    assert mapped["AdditionalInterest_ItemDescription_A"] is None
    # ...and the producer's own box is untouched.
    assert mapped["Producer_ContactPerson_FullName_A"] == "Dana Ostrander"


def test_a_carrier_named_as_its_own_additional_interest_dies_too():
    """The same rule reaches the other party. Client, on a live form: 'An
    insurance carrier would not normally be added as an additional insured on
    the policy it services.'"""
    mapped = {
        "Insurer_FullName_A": "EMC Property & Casualty Company",
        "AdditionalInterest_FullName_B": "EMC Property & Casualty Company",
    }
    ps._drop_fabricated_interest_rows(
        mapped, {"AdditionalInterest_FullName_B"}, {})
    assert mapped["AdditionalInterest_FullName_B"] is None


def test_a_genuine_third_party_named_nowhere_else_survives():
    """POSITIVE CONTROL, and the whole reason this is a BORROW test rather than
    a presence test. The rule removed on 2026-08-13 required the name to appear
    in the dec index, which blanked a third party named only in document prose.
    This one refuses a name only on positive evidence that it is already
    another party on this same form."""
    mapped = {
        "Producer_ContactPerson_FullName_A": "Dana Ostrander",
        "Insurer_FullName_A": "EMC Property & Casualty Company",
        "AdditionalInterest_FullName_C": "Meridian Fleet Leasing, LLC",
    }
    dropped = ps._drop_fabricated_interest_rows(
        mapped, {"AdditionalInterest_FullName_C"}, {})
    assert not dropped
    assert mapped["AdditionalInterest_FullName_C"] == "Meridian Fleet Leasing, LLC"


def test_a_producer_entered_interest_is_untouchable():
    """POSITIVE CONTROL 2 - the guard only ever blanks what the MODEL authored.
    A row a human typed survives even when it names the producer, because a
    human may have meant it."""
    mapped = {
        "Producer_ContactPerson_FullName_A": "Dana Ostrander",
        "AdditionalInterest_FullName_A": "Dana Ostrander",
    }
    ps._drop_fabricated_interest_rows(mapped, set(), {})   # nothing gpt-filled
    assert mapped["AdditionalInterest_FullName_A"] == "Dana Ostrander"


def test_a_short_shared_token_cannot_trigger_the_borrow():
    """The pool ignores values of 4 characters or fewer ('co', 'inc' prove
    nothing), so a coincidence cannot kill a real row."""
    mapped = {
        "Producer_FullName_A": "LLC",
        "AdditionalInterest_FullName_A": "LLC",
    }
    ps._drop_fabricated_interest_rows(
        mapped, {"AdditionalInterest_FullName_A"}, {})
    assert mapped["AdditionalInterest_FullName_A"] == "LLC"
