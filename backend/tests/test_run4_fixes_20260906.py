"""Two defects still visible on SYS-09 live run 4, both pre-existing.

  1. THE CITY BOX READ "Suite 300 Tacoma". Runs 2 and 4 both printed it; run 3
     did not, which is why it briefly looked fixed. It was never fixed - run 3's
     extraction happened to emit a second comma. Luck is not a fix, and this
     file exists so it cannot look fixed by luck again.

  2. THE AUDIT BOX PRINTED A BARE "A" on a package that states no audit term
     anywhere. The PAYMENT PLAN box beside it was closed for the identical
     invention on 2026-08-14 ("AN", derived from "Audit Period: Annual"); the
     AUDIT box itself was left unowned for another three weeks.
"""
import json
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
os.environ.setdefault("OPENAI_API_KEY", "sk-offline-test")

import services.pdf_service as ps                                # noqa: E402
from utils.helpers import _parse_address                         # noqa: E402


# ── 1. A unit glued to the city ─────────────────────────────────────────────

def test_the_live_case_splits_the_unit_off_the_city():
    """Every ACORD and letterhead prints the unit on the street line and the
    city on the next; extraction joins them with ONE comma."""
    got = _parse_address("2255 Shorebank Avenue, Suite 300 Tacoma, WA 98402")
    assert got["line1"] == "2255 Shorebank Avenue"
    assert got["line2"] == "Suite 300"
    assert got["city"] == "Tacoma"
    assert got["state"] == "WA" and got["zip"] == "98402"


def test_the_already_correct_shape_parses_identically():
    """Run 3's spelling, with the second comma. Both must land the same way, or
    the result still depends on which comma the extractor felt like emitting."""
    a = _parse_address("2255 Shorebank Avenue, Suite 300 Tacoma, WA 98402")
    b = _parse_address("2255 Shorebank Avenue, Suite 300, Tacoma, WA 98402")
    assert a == b


@pytest.mark.parametrize("addr,line2,city", [
    ("123 Main St, Ste 400 Englewood, CO 80112", "Ste 400", "Englewood"),
    ("9 Wharf Rd, # D13 Tacoma, WA 98421", "# D13", "Tacoma"),
    ("50 Kings Way, Floor 3 Boston, MA 02110", "Floor 3", "Boston"),
    ("7 Bay St, Unit B Miami, FL 33101", "Unit B", "Miami"),
])
def test_every_unit_designator_is_recognised(addr, line2, city):
    got = _parse_address(addr)
    assert got.get("line2") == line2 and got.get("city") == city


@pytest.mark.parametrize("addr,city", [
    ("4800 Dahlia St, Denver, CO 80216", "Denver"),
    ("12 Elm St, Salt Lake City, UT 84101", "Salt Lake City"),
    ("1 Plaza, Suite City, NY 10001", "Suite City"),
])
def test_a_city_with_no_unit_in_front_is_never_cut(addr, city):
    """The split fires ONLY when the leading chunk is a unit and nothing else,
    so a multi-word city - including one that starts with a unit word - is
    left alone."""
    assert _parse_address(addr).get("city") == city


def test_the_comma_free_recovery_still_works():
    """The 2026-08-14 recovery this one sits beside must be untouched."""
    got = _parse_address("4800 Dahlia St # D13 Denver CO 80216")
    assert got["city"] == "Denver" and got["line1"] == "4800 Dahlia St"


@pytest.mark.parametrize("addr", ["", None, ",", "  ,  ,  ", "Suite 300"])
def test_degenerate_addresses_do_not_raise(addr):
    assert isinstance(_parse_address(addr) if addr else {}, dict)


def test_the_city_box_on_the_real_form_is_the_city():
    """Through the real stamper, because the CITY box is what the client saw."""
    path = os.path.join(os.path.dirname(__file__), "..", "forms_schemas",
                        "ACORD_125_schema.json")
    with open(path, encoding="utf-8") as fh:
        schema = json.load(fh)
    facts = {"applicant_name": "Harborline Provisions LLC",
             "mailing_address": "2255 Shorebank Avenue, Suite 300 Tacoma, WA 98402"}
    res = ps.map_facts_to_form(dict(facts), schema, "ACORD_125")
    mapped = res[0] if isinstance(res, tuple) else res
    assert mapped.get("NamedInsured_MailingAddress_CityName_A") == "Tacoma"
    # "Ste 300", not "Suite 300": display canonicalisation abbreviates the unit
    # (and "Avenue" -> "Ave") on the STAMPED value by design. What matters here
    # is that the unit is in the line-two box at all rather than fused into the
    # city, so assert the separation, not the spelling.
    assert mapped.get("NamedInsured_MailingAddress_LineTwo_A") in ("Suite 300", "Ste 300")
    assert "300" not in str(mapped.get("NamedInsured_MailingAddress_CityName_A"))


# ── 2. The AUDIT box ────────────────────────────────────────────────────────

_AUDIT = "Policy_Audit_FrequencyCode_A"


def test_no_audit_term_means_an_owned_blank():
    """THE LIVE CASE. Three runs printed "A" off a package that never mentions
    an audit."""
    assert ps._resolve_audit_frequency(_AUDIT, {"applicant_name": "X"}) is None


def test_a_stated_audit_term_still_stamps():
    """Fact-or-blank, not blank-always. A guard that swallows real data is a
    worse bug than the one it fixes."""
    assert ps._resolve_audit_frequency(_AUDIT, {"audit_period": "Annual"}) == "Annual"


def test_the_audit_box_never_reaches_gap_fill():
    """An owned blank that is not REGISTERED means "ask the model", which is how
    `_resolve_gl_hazard_row` shipped a fix that did nothing for weeks."""
    assert "_resolve_audit_frequency" in ps._AUTHORITATIVE_BLANK_RESOLVERS
    assert ps._is_authoritative_blank_field(_AUDIT, {"applicant_name": "X"}) is True


def test_it_claims_no_other_box_in_that_row():
    """The row is BILLING PLAN / PAYMENT PLAN / METHOD OF PAYMENT / AUDIT /
    DEPOSIT / MINIMUM PREMIUM, and each has its own owner or none."""
    for field in ("Policy_Payment_DepositAmount_A",
                  "Policy_Payment_MinimumPremiumAmount_A",
                  "Policy_BillingPlanCode_A",
                  "NamedInsured_FullName_A"):
        assert ps._resolve_audit_frequency(field, {"audit_period": "Annual"}) \
            is ps._SCHED_SKIP, field
    # Rows B-N ARE claimed, deliberately and like every sibling resolver in this
    # family: an audit term belongs to the policy, so if a form ever prints the
    # box on a second row it is the same answer, not a new question.
    assert ps._resolve_audit_frequency(
        "Policy_Audit_FrequencyCode_B", {"audit_period": "Annual"}) == "Annual"


# ── 3. A party fact that is an exact COPY of another party's ────────────────
#
# ACCEPTANCE RUN, 2026-09-06: the PRODUCER block on ACORD 25 *and* ACORD 125
# printed "2255 Shorebank Ave, Ste 300, Tacoma WA 98402" - byte-identical to the
# INSURED block beneath it. The resolver held; extraction had written the
# APPLICANT's address into `producer_address`, so the box was reading its own
# party's fact and every ownership check passed.
#
# It was written on 2026-09-05 that this shape is uncatchable. It is not: an
# exact copy of another party's value is a structural signal, and only a
# PLAUSIBLE INVENTION is genuinely invisible.

_APPLICANT_ADDR = "2255 Shorebank Avenue, Suite 300, Tacoma, WA 98402"


@pytest.mark.parametrize("field", [
    "Producer_MailingAddress_LineOne_A", "Producer_MailingAddress_CityName_A",
    "Producer_MailingAddress_PostalCode_A",
])
def test_a_producer_address_copied_from_the_applicant_is_an_owned_blank(field):
    facts = {"applicant_name": "Harborline Provisions LLC",
             "mailing_address": _APPLICANT_ADDR,
             "producer_address": _APPLICANT_ADDR}
    assert ps._resolve_producer_mailing(field, facts) is None


def test_a_producer_address_copied_from_the_PHYSICAL_address_is_caught_too():
    facts = {"physical_address": _APPLICANT_ADDR, "producer_address": _APPLICANT_ADDR}
    assert ps._resolve_producer_mailing(
        "Producer_MailingAddress_LineOne_A", facts) is None


def test_a_genuine_producer_address_still_stamps():
    """The guard must not blank a real agency address - that would be the same
    defect pointing the other way."""
    facts = {"mailing_address": _APPLICANT_ADDR,
             "producer_address": "88 Ledger Street, Suite 410, Seattle, WA 98101"}
    assert ps._resolve_producer_mailing(
        "Producer_MailingAddress_CityName_A", facts) == "Seattle"


def test_the_copy_test_ignores_formatting():
    facts = {"mailing_address": "2255 Shorebank Ave, Ste 300, Tacoma WA 98402",
             "producer_address": "2255 SHOREBANK AVENUE, SUITE 300, TACOMA, WA 98402"}
    got = ps._resolve_producer_mailing("Producer_MailingAddress_LineOne_A", facts)
    assert got is None, "punctuation and case must not defeat the copy test"


def test_a_producer_contact_copied_from_the_applicant_is_an_owned_blank():
    facts = {"contact_name": "Marguerite Vasseur",
             "producer_contact_name": "Marguerite Vasseur"}
    assert ps._resolve_producer_contact(
        "Producer_ContactPerson_FullName_A", facts) is None


def test_a_genuine_producer_contact_still_steps_aside():
    facts = {"contact_name": "Marguerite Vasseur",
             "producer_contact_name": "Delphine Ostrander"}
    assert ps._resolve_producer_contact(
        "Producer_ContactPerson_FullName_A", facts) is ps._SCHED_SKIP


def test_the_applicants_own_side_is_NEVER_the_one_blanked():
    """Asymmetric on purpose. The applicant's address is corroborated all over a
    submission and is a Tier 1 field; the producer's is stated once. On an exact
    duplicate the producer's is the borrowed one, and blanking the applicant's
    would cost more than the defect does."""
    facts = {"mailing_address": _APPLICANT_ADDR, "producer_address": _APPLICANT_ADDR,
             "contact_name": "Marguerite Vasseur",
             "producer_contact_name": "Marguerite Vasseur"}
    assert ps._deterministic_map(
        "NamedInsured_MailingAddress_CityName_A", facts) == "Tacoma"
    assert ps._resolve_applicant_contact(
        "NamedInsured_Contact_FullName_A", facts) is ps._SCHED_SKIP


# ── 4. A role riding along in the contact NAME box ──────────────────────────

def test_the_role_is_dropped_when_the_type_box_already_prints_it():
    """CONTACT NAME read "Marguerite Vasseur, Controller" while CONTACT TYPE,
    beside it, read "Controller"."""
    mapped = {"NamedInsured_Contact_FullName_A": "Marguerite Vasseur, Controller",
              "NamedInsured_Contact_ContactDescription_A": "Controller"}
    ps._strip_role_echoed_from_the_type_box(mapped)
    assert mapped["NamedInsured_Contact_FullName_A"] == "Marguerite Vasseur"
    assert mapped["NamedInsured_Contact_ContactDescription_A"] == "Controller"


@pytest.mark.parametrize("mapped", [
    {"NamedInsured_Contact_FullName_A": "Smith, John"},
    {"NamedInsured_Contact_FullName_A": "Smith, John",
     "NamedInsured_Contact_ContactDescription_A": "Owner"},
    {"NamedInsured_Contact_FullName_A": "Marguerite Vasseur",
     "NamedInsured_Contact_ContactDescription_A": "Controller"},
])
def test_a_name_is_never_cut_without_proof(mapped):
    """NO TITLE VOCABULARY: "Smith, John" is a legitimate name, and a job-title
    list would blank it. The tail goes only when that row's own CONTACT TYPE box
    already prints it, so nothing is lost."""
    before = dict(mapped)
    ps._strip_role_echoed_from_the_type_box(mapped)
    assert mapped == before


def test_it_works_for_any_party_block_and_any_row():
    mapped = {"Producer_Contact_FullName_B": "Dana Reid, Account Manager",
              "Producer_Contact_ContactDescription_B": "account manager"}
    ps._strip_role_echoed_from_the_type_box(mapped)
    assert mapped["Producer_Contact_FullName_B"] == "Dana Reid"


@pytest.mark.parametrize("value", [None, "", "   ", ",", ", Controller", 7])
def test_degenerate_name_values_do_not_raise(value):
    mapped = {"NamedInsured_Contact_FullName_A": value,
              "NamedInsured_Contact_ContactDescription_A": "Controller"}
    ps._strip_role_echoed_from_the_type_box(mapped)


# ── 5. Sub-limits copied sideways on a CERTIFICATE ──────────────────────────
#
# Live 2026-09-06, ACORD 25 on a package stating ONE GL limit and NO umbrella:
#   DAMAGE TO RENTED PREMISES $1,000,000 / PERSONAL & ADV INJURY $1,000,000 /
#   UMBRELLA LIAB EACH OCCURRENCE $1,000,000 - none of them stated anywhere.
# The umbrella one is the serious case: a certificate is what a landlord or
# terminal relies on, and this one asserted cover that does not exist.

_KIT = {"gl_each_occurrence": "1,000,000", "gl_aggregate": "2,000,000"}

_SUBLIMITS = [
    "GeneralLiability_FireDamageRentedPremises_EachOccurrenceLimitAmount_A",
    "GeneralLiability_MedicalExpense_EachPersonLimitAmount_A",
    "GeneralLiability_PersonalAndAdvertisingInjury_LimitAmount_A",
    "GeneralLiability_ProductsAndCompletedOperations_AggregateLimitAmount_A",
    "ExcessUmbrella_Umbrella_EachOccurrenceAmount_A",
    "ExcessUmbrella_Umbrella_AggregateAmount_A",
]


@pytest.mark.parametrize("field", _SUBLIMITS)
def test_an_unstated_sublimit_is_an_owned_blank(field):
    assert ps._resolve_stated_limit_cell(field, _KIT) is None
    assert ps._is_authoritative_blank_field(field, _KIT) is True, (
        "an unregistered None means 'ask the model', which is the whole defect")


def test_the_umbrella_row_is_the_one_that_matters():
    """A certificate asserting umbrella cover a package does not carry is a
    coverage misstatement to a third party, not a fill-rate question."""
    assert ps._deterministic_map(
        "ExcessUmbrella_Umbrella_EachOccurrenceAmount_A", _KIT) is None


@pytest.mark.parametrize("field,fact,value", [
    ("GeneralLiability_FireDamageRentedPremises_EachOccurrenceLimitAmount_A",
     "gl_fire_damage_limit", "100,000"),
    ("GeneralLiability_PersonalAndAdvertisingInjury_LimitAmount_A",
     "gl_personal_advertising_injury", "1,000,000"),
    ("ExcessUmbrella_Umbrella_EachOccurrenceAmount_A",
     "umbrella_limit", "5,000,000"),
])
def test_a_stated_sublimit_still_prints(field, fact, value):
    """Fact-or-blank, not blank-always. Every one of these already had a Pass-1
    rule pointing at its own fact; only the absent case was open."""
    facts = dict(_KIT, **{fact: value})
    assert ps._resolve_stated_limit_cell(field, facts) is ps._SCHED_SKIP
    assert ps._deterministic_map(field, facts) == value


@pytest.mark.parametrize("field", [
    "GeneralLiability_EachOccurrence_LimitAmount_A",
    "GeneralLiability_GeneralAggregate_LimitAmount_A",
])
def test_the_PRIMARY_gl_limits_are_deliberately_left_alone(field):
    """They are what a dec page prints largest, extraction gets them, and on a
    rare miss gap fill reading them off the raw text beats a blank. The measured
    failure was the copy INTO the siblings, so that is what is closed."""
    assert ps._resolve_stated_limit_cell(field, _KIT) is ps._SCHED_SKIP


def test_a_sublimit_box_on_another_form_behaves_the_same():
    """These boxes live on ACORD 25, 126, 131 and 160. The rule is the meaning
    of the box, not which form it sits on."""
    assert ps._resolve_stated_limit_cell(
        "GeneralLiability_MedicalExpense_EachPersonLimitAmount_B", _KIT) is None


@pytest.mark.parametrize("field", [
    "", "NotAField", "GeneralLiability_EachOccurrence_LimitAmount",
    "NamedInsured_FullName_A",
])
def test_unrelated_fields_are_not_claimed(field):
    assert ps._resolve_stated_limit_cell(field, _KIT) is ps._SCHED_SKIP
