"""The last three ACORD 25 defects from the SYS-09 acceptance runs.

  1. A COVERAGE-TYPE LABEL STAMPED AS A VALUE. The GL block's free row printed
     "Commercial Auto" with its checkbox TICKED; the auto block's printed
     "AUTOMOBILE". ACORD's own tooltip says the box is for coverage "NOT FOUND ON
     THE FORM" - and Commercial Auto has its own block eight rows down.

  2. THE CERTIFICATE HOLDER'S STREET LINE MISSING. ACORD 25 printed the holder's
     name, city, state and ZIP but not "870 Wharfside Blvd", while the same
     holder printed in full on ACORD 125 in the same run.

  3. AN INVENTED METHOD OF PAYMENT. "Direct Bill" on one run, "...oducer /
     agency bill" on the next, from a package containing none of those words.

The mechanism behind (3) is confirmed from the schema, not inferred: the two
CHECKBOXES beside that text box carry the tooltips "...the policy is to be
DIRECT BILLED" and "...to be PRODUCER / AGENCY BILLED" - verbatim the two
strings that printed. `_is_tooltip_echo` compares a value only against the
field's OWN tooltip, so a sibling's is invisible to it.
"""
import json
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
os.environ.setdefault("OPENAI_API_KEY", "sk-offline-test")

import services.pdf_service as ps                                # noqa: E402

APPLICANT_ADDR = "2255 Shorebank Avenue, Suite 300, Tacoma, WA 98402"
HOLDER_ADDR = "870 Wharfside Boulevard, Tacoma, WA 98421"

_KIT = {
    "_form_id": "ACORD_25",
    "gl_each_occurrence": "1,000,000", "gl_aggregate": "2,000,000",
    "certificate_holder": "Kestrel Terminal Authority",
    "certificate_holder_address": HOLDER_ADDR,
    "mailing_address": APPLICANT_ADDR,
}


def _schema(form):
    path = os.path.join(os.path.dirname(__file__), "..", "forms_schemas",
                        f"{form}_schema.json")
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def _reaches_gap_fill(field, facts, form="ACORD_25"):
    result = ps._deterministic_map(field, facts)
    if not (result == "UNMATCHED" or ps._is_empty_llm_value(result)):
        return False
    return not ps._is_authoritative_blank_field(field, facts)


# ── 1. The coverage-type label in an "other coverage" row ───────────────────

#
# THE FIRST CUT BLANKED ALL 16 BOXES AND WAS WRONG. An adversarial pass produced
# six kills, every one a correct value deleted: the GL deductible (a live Pass-1
# target), UM/UIM in the auto limit column, the WC PER STATUTE|OTH- selector, the
# auto "Other symbol" box, and the genuine wordings "Excess Employers
# Liability" / "Stop Gap" / "Employee Benefits Liability". A coverage NAME is the
# right content for these boxes; that was never the defect.

_GL_DESC = "GeneralLiability_OtherCoverageDescription_A"
_GL_TICK = "GeneralLiability_OtherCoverageIndicator_A"


def _guard(mapped, form="ACORD_25"):
    out = dict(mapped)
    ps._drop_section_name_in_other_coverage_row(out, {"_form_id": form})
    return out


@pytest.mark.parametrize("value", [
    "Commercial Auto", "AUTOMOBILE", "AUTOMOBILE LIABILITY",
    "Commercial General Liability", "Workers Compensation", "Umbrella",
    "Excess Liab", "Business Auto", "Any Auto",
])
def test_a_section_this_form_already_prints_is_removed(value):
    """THE LIVE CASE: "Commercial Auto" in the GL block with its checkbox ticked,
    on a certificate that prints Commercial Auto in its own block."""
    got = _guard({_GL_DESC: value, _GL_TICK: "Yes"})
    assert got[_GL_DESC] is None
    assert got[_GL_TICK] is None, "the tick came with the description"


@pytest.mark.parametrize("field,value", [
    (_GL_DESC, "Employee Benefits Liability"),
    (_GL_DESC, "Liquor Liability"),
    (_GL_DESC, "Pollution Liability"),
    (_GL_DESC, "Employment Practices Liability"),
    ("ExcessUmbrella_OtherCoverageDescription_A", "Excess Employers Liability"),
    ("WorkersCompensationEmployersLiability_OtherCoverageDescription_A", "Stop Gap"),
    ("Vehicle_OtherCoverage_CoverageDescription_A", "Uninsured Motorist"),
    ("Vehicle_OtherCoverage_CoverageDescription_A", "Hired Auto Physical Damage"),
    ("Vehicle_OtherCoveredAutoDescription_A", "Symbol 19 - mobile equipment"),
])
def test_a_genuine_other_coverage_survives(field, value):
    """THE STRUCTURAL SECOND CONDITION. Canon alone is necessary but not
    sufficient - "Excess Employers Liability" canonicalises to `umbrella` and
    "Stop Gap" to `workers_comp`, and the first cut deleted both. A borrowed
    header is built only from the section's own title words; a real coverage
    adds a word of its own."""
    assert _guard({field: value})[field] == value


def test_a_deductible_never_fills_the_other_coverage_limit():
    """This pinned a Pass-1 rule `GeneralLiability_OtherCoverageLimitAmount` ->
    `gl_deductible`. The box's own tooltip on ACORD 25 and 126 is "Enter limit:
    the general liability, other coverage limit amount", and nothing labels the
    row a deductible - live run 10 (15 Sep 2026) printed the pollution
    endorsement's "$1,000 Each Pollution Incidents" there as a limit. The rule is
    gone; the test was pinning the defect."""
    assert ps._deterministic_map(
        "GeneralLiability_OtherCoverageLimitAmount_A",
        {"_form_id": "ACORD_25", "gl_deductible": "$1,000"}) != "$1,000"


@pytest.mark.parametrize("tick", [
    "WorkersCompensationEmployersLiability_OtherCoverageIndicator_A",
    "Vehicle_OtherCoveredAutoIndicator_A",
])
def test_a_lone_tick_is_left_alone(tick):
    """The WC one is the PER STATUTE | OTH- selector; the auto one is the "Other
    symbol" box the 2026-08-07 auto-symbols work deliberately ticks. Neither is
    a free row, and neither clears without its own description."""
    assert _guard({tick: "Yes"})[tick] == "Yes"


def test_other_forms_are_untouched():
    for form in ("ACORD_126", "ACORD_131", "ACORD_160", ""):
        assert _guard({_GL_DESC: "Commercial Auto"}, form)[_GL_DESC] == "Commercial Auto"


@pytest.mark.parametrize("value", [None, "", "   ", 7, [], {}, b"x", True])
def test_degenerate_other_coverage_values_do_not_raise(value):
    _guard({_GL_DESC: value})


# ── 2. The certificate holder's own address ─────────────────────────────────

_HOLDER_FIELDS = [
    "CertificateHolder_MailingAddress_LineOne_A",
    "CertificateHolder_MailingAddress_LineTwo_A",
    "CertificateHolder_MailingAddress_CityName_A",
    "CertificateHolder_MailingAddress_StateOrProvinceCode_A",
    "CertificateHolder_MailingAddress_PostalCode_A",
]


def test_the_holders_street_now_prints():
    """THE LIVE CASE. The fact existed, had a registry entry and a reader, and
    was bound to no ACORD field anywhere."""
    res = ps.map_facts_to_form(dict(_KIT), _schema("ACORD_25"), "ACORD_25")
    mapped = res[0] if isinstance(res, tuple) else res
    assert mapped["CertificateHolder_FullName_A"] == "Kestrel Terminal Authority"
    assert mapped["CertificateHolder_MailingAddress_LineOne_A"] == "870 Wharfside Blvd"
    assert mapped["CertificateHolder_MailingAddress_CityName_A"] == "Tacoma"
    assert mapped["CertificateHolder_MailingAddress_StateOrProvinceCode_A"] == "WA"
    assert mapped["CertificateHolder_MailingAddress_PostalCode_A"] == "98421"


@pytest.mark.parametrize("addr,line1,city", [
    ("870 Wharfside Boulevard, Tacoma, WA 98421", "870 Wharfside Boulevard", "Tacoma"),
    ("PO Box 4471, Tacoma, WA 98401", "PO Box 4471", "Tacoma"),
    ("50 Dock St, Suite 12, Seattle, WA 98104", "50 Dock St", "Seattle"),
    ("RR 2 Box 118, Chehalis, WA 98532", "RR 2 Box 118", "Chehalis"),
])
def test_a_complete_us_address_parses(addr, line1, city):
    facts = dict(_KIT, certificate_holder_address=addr)
    assert ps._resolve_certificate_holder_address(
        "CertificateHolder_MailingAddress_LineOne_A", facts) == line1
    assert ps._resolve_certificate_holder_address(
        "CertificateHolder_MailingAddress_CityName_A", facts) == city


@pytest.mark.parametrize("addr,why", [
    ("1200 Rue Sherbrooke O, Montreal, QC H3A 1H6",
     "Quebec: the parser yields state 'H3A' and discards QC entirely"),
    ("12 Harbour Road, London, EC1A 4BB", "UK: state 'EC1A', postal '4BB'"),
    ("PO Box 4471 Tacoma WA 98421", "no commas - the city fuses into the street"),
    ("Tacoma, WA 98421", "a locality with no street"),
    ("870 Wharfside Blvd, Tacoma, WA 98421,", "trailing comma - city becomes 'WA 98421'"),
    ("Attn: Risk Management, 870 Wharfside Blvd, Tacoma, WA 98421",
     "an attention line would take the street box"),
    ("Suite 300, Tacoma, WA 98402", "a unit with no street"),
    ("Kestrel Terminal Authority, 870 Wharfside Blvd, Tacoma, WA 98421",
     "the holder's NAME would take the street box"),
])
def test_anything_but_a_complete_US_parse_steps_aside(addr, why):
    """`_parse_address` assumes a US "ST ZIP" tail, and gap fill was ALREADY
    getting four of these five boxes right - so a partial or foreign parse trades
    one missing box for two WRONG ones on a legal document. Tacoma is a
    cross-border port; a Canadian holder is an ordinary input, not an exotic one."""
    facts = dict(_KIT, certificate_holder_address=addr)
    for field in _HOLDER_FIELDS:
        assert ps._resolve_certificate_holder_address(field, facts) \
            is ps._SCHED_SKIP, why


def test_an_insured_operating_AT_the_holders_site_still_prints():
    """No copy-refusal here, deliberately, and unlike the producer block: a food
    distributor placed at the terminal that holds the certificate genuinely
    shares that address, and blanking on a match would empty a correct block."""
    same = "870 Wharfside Blvd, Tacoma, WA 98421"
    facts = dict(_KIT, certificate_holder_address=same, physical_address=same)
    assert ps._resolve_certificate_holder_address(
        "CertificateHolder_MailingAddress_LineOne_A", facts) == "870 Wharfside Blvd"


@pytest.mark.parametrize("bad_facts", [None, [], "x", 7])
def test_a_non_dict_facts_container_does_not_crash(bad_facts):
    """Every degenerate VALUE was handled; the CONTAINER was not."""
    assert ps._resolve_certificate_holder_address(
        "CertificateHolder_MailingAddress_LineOne_A", bad_facts) is ps._SCHED_SKIP


def test_an_absent_holder_address_STEPS_ASIDE_it_does_not_blank():
    """DELIBERATELY the opposite of the producer block, and measured. With no
    producer address stated, gap fill produced the APPLICANT's address - a wrong
    value. With no holder address bound, gap fill produced the holder's real
    city, state and ZIP - right values, one box short. Evidence decides."""
    facts = {k: v for k, v in _KIT.items() if k != "certificate_holder_address"}
    for field in _HOLDER_FIELDS:
        assert ps._resolve_certificate_holder_address(field, facts) is ps._SCHED_SKIP


@pytest.mark.parametrize("value", [
    None, 0, 1, True, 3.5, [], {}, b"x", "   ", "0", "[]",
    "Tacoma",                      # a locality with no street
    "870 Wharfside Blvd",          # a street with no locality
    "x" * 20000,
])
def test_a_fact_that_is_not_an_address_never_reaches_the_form(value):
    """`str()`-ing a list would print "[]" in a street box on a certificate.
    Found by fuzzing this resolver, not by a live run."""
    facts = dict(_KIT, certificate_holder_address=value)
    assert ps._resolve_certificate_holder_address(
        "CertificateHolder_MailingAddress_LineOne_A", facts) is ps._SCHED_SKIP


def test_an_enveloped_fact_is_unwrapped():
    facts = dict(_KIT, certificate_holder_address={"value": HOLDER_ADDR})
    assert ps._resolve_certificate_holder_address(
        "CertificateHolder_MailingAddress_LineOne_A", facts) == "870 Wharfside Boulevard"


def test_it_claims_no_other_partys_address():
    for field in ("Producer_MailingAddress_LineOne_A",
                  "NamedInsured_MailingAddress_LineOne_A",
                  "AdditionalInterest_MailingAddress_LineOne_A"):
        assert ps._resolve_certificate_holder_address(field, _KIT) is ps._SCHED_SKIP


# ── 3. METHOD OF PAYMENT ────────────────────────────────────────────────────

_METHOD = "Policy_PaymentMethod_MethodDescription_A"


def test_no_stated_billing_method_means_an_owned_blank():
    """THE LIVE CASE, twice: "Direct Bill" and "...oducer / agency bill" from a
    package containing neither phrase."""
    assert ps._resolve_payment_method_description(_METHOD, {"applicant_name": "X"}) is None
    assert not _reaches_gap_fill(_METHOD, {"applicant_name": "X"})


@pytest.mark.parametrize("stated", ["Direct Bill", "Agency Bill", "direct bill"])
def test_a_stated_billing_method_still_prints(stated):
    assert ps._resolve_payment_method_description(
        _METHOD, {"billing_plan": stated}) == stated


def test_the_sibling_checkbox_tooltips_are_the_two_strings_that_printed():
    """The mechanism, asserted from the schema rather than inferred - and a
    guard against someone 'fixing' this by widening `_is_tooltip_echo`, which
    only ever reads a field's OWN tooltip."""
    schema = _schema("ACORD_125")
    assert "direct billed" in schema["Policy_Payment_DirectBillIndicator_A"]["tu"].lower()
    assert "producer / agency billed" in \
        schema["Policy_Payment_ProducerBillIndicator_A"]["tu"].lower()
    own = schema[_METHOD]["tu"].lower()
    assert "direct" not in own and "agency" not in own, (
        "the box's own tooltip names neither, which is why the echo guard is blind")


def test_it_claims_no_neighbouring_box_in_that_row():
    for field in ("Policy_Payment_PaymentScheduleCode_A",
                  "Policy_Payment_DepositAmount_A",
                  "Policy_Payment_MinimumPremiumAmount_A",
                  "Policy_Audit_FrequencyCode_A"):
        assert ps._resolve_payment_method_description(field, {"billing_plan": "Direct Bill"}) \
            is ps._SCHED_SKIP


# ── Anti-rot ────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("name", [
    "_resolve_certificate_holder_address",
    "_resolve_payment_method_description",
    "_resolve_stated_limit_cell",
])
def test_every_new_resolver_is_registered(name):
    """An owned blank that is not REGISTERED means "ask the model" - the trap
    `_resolve_gl_hazard_row` fell into for weeks."""
    assert name in ps._AUTHORITATIVE_BLANK_RESOLVERS
    assert callable(getattr(ps, name, None))


def test_the_whole_certificate_survives_a_facts_dict_of_junk():
    """These run inside form generation. A malformed session must produce a
    blank certificate, never an exception."""
    for facts in ({}, {"_form_id": "ACORD_25"},
                  {"_form_id": "ACORD_25", "certificate_holder_address": None,
                   "certificate_holder": 7, "billing_plan": [], "umbrella_limit": {}}):
        res = ps.map_facts_to_form(dict(facts), _schema("ACORD_25"), "ACORD_25")
        mapped = res[0] if isinstance(res, tuple) else res
        assert isinstance(mapped, dict)


# ── A designation box holds a NAME, not a sentence ───────────────────────────

@pytest.mark.parametrize("value", [
    "Two leased delivery vans are operated under a long-term lease",  # LIVE
    "All vehicles are owned by the applicant",
    "Coverage is provided for hired autos",
    "The policy covers mobile equipment",
    "This policy includes hired auto coverage",
])
def test_a_narrative_sentence_is_not_a_coverage_designation(value):
    """These rows NAME the thing covered. The live run of 2026-09-07 put a true,
    grounded sentence about leased vans in one - narrative, which the
    certificate already has its own box for four rows down."""
    got = _guard({"Vehicle_OtherCoveredAutoDescription_A": value})
    assert got["Vehicle_OtherCoveredAutoDescription_A"] is None


@pytest.mark.parametrize("value", [
    "Owned trailers", "Leased equipment", "Rented premises",
    "Covered autos - symbol 8", "Included endorsements",
    "Non-owned watercraft under 26 feet", "Symbol 19 - mobile equipment",
])
def test_a_participle_is_an_adjective_not_a_finite_verb(value):
    """PARTICIPLES ARE NOT SENTENCES. An earlier cut of the verb list carried
    "leased", "rented", "owned", "covered" and "included", and deleted every one
    of these real designations."""
    got = _guard({"Vehicle_OtherCoveredAutoDescription_A": value})
    assert got["Vehicle_OtherCoveredAutoDescription_A"] == value


@pytest.mark.parametrize("value", ["AUTOMOBILE LIABILITY", "Commercial Auto",
                                   "UMBRELLA LIAB"])
def test_a_section_name_in_the_AMOUNT_box_goes_too(value):
    """A limit box holding a coverage NAME is never right - and the ordinary
    amount guards are deliberately permissive there, because "Statutory",
    "Included" and "See schedule" are all legitimate entries in a limit box."""
    got = _guard({"GeneralLiability_OtherCoverageLimitAmount_A": value})
    assert got["GeneralLiability_OtherCoverageLimitAmount_A"] is None


@pytest.mark.parametrize("value", ["1,000,000", "Statutory", "Included",
                                   "See schedule", "$5,000"])
def test_a_real_limit_is_never_touched(value):
    got = _guard({"GeneralLiability_OtherCoverageLimitAmount_A": value,
                  "GeneralLiability_OtherCoverageLimitDescription_A":
                      "Employee Benefits Liability"})
    assert got["GeneralLiability_OtherCoverageLimitAmount_A"] == value
