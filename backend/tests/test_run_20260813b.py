"""Second live ACORD 125 of 2026-08-13: the Q4 regression and the section drop.

Fixtures are the client's literal run values, taken from the log lines quoted in
each test. Three fixes shipped; a fourth was tried and reverted, and the reason
is pinned by `test_a_name_only_additional_interest_is_still_legitimate` so nobody
rebuilds it from the same reasoning.
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("OPENAI_API_KEY", "sk-offline")

import services.extraction_service as es                          # noqa: E402
import services.pdf_service as ps                                 # noqa: E402


# ── 1. A FORM number is not a POLICY number ──────────────────────────────────
# Live log:
#   merge coverage_lines FINAL: ... ('Installation Floater', 'None',
#       'IM 7100 06 04'), ('Computer Coverage', 'None', 'IM 7201 10 02')
# and the form printed those in Q4 while the umbrella's 6J7-40-02---26 and the
# GL's BBC7263 fell off the four available rows entirely.

@pytest.mark.parametrize("code", [
    "IM 7100 06 04",      # AAIS Installation Floater - the client's literal value
    "IM 7201 10 02",      # AAIS Computer Coverage    - the client's literal value
    "CG 00 01 04 13",     # ISO CGL occurrence form
    "IL 00 17 11 98",     # ISO Common Policy Conditions
    "IL 70 04 05 09",
])
def test_a_form_number_is_recognised(code):
    assert ps._looks_like_a_form_number(code)


@pytest.mark.parametrize("policy", [
    "6E7-40-02---26",     # Business Auto      - every one of these is a REAL
    "6C7-40-02---26",     # Inland Marine        policy number from the client's
    "6J7-40-02---26",     # Umbrella             package and must survive
    "BBC7263 - 26",       # General Liability
    "0482854",            # the account number
    "CA7000A 02-22",      # a carrier dec-page code, not an ISO/AAIS form number
])
def test_a_real_policy_number_survives(policy):
    assert not ps._looks_like_a_form_number(policy)


def test_a_form_numbered_row_never_reaches_q4():
    """The row is dropped whole, not just its number: the paired line name came
    from the same entry, and leaving it would print a coverage line with an empty
    policy box AND consume one of the four printed rows."""
    facts = {"coverage_lines": [
        {"line": "Installation Floater", "policy_number": "IM 7100 06 04"},
        {"line": "Computer Coverage", "policy_number": "IM 7201 10 02"},
        {"line": "Commercial Liability Umbrella", "policy_number": "6J7-40-02---26"},
        {"line": "Commercial General Liability", "policy_number": "BBC7263 - 26"},
    ]}
    got = {
        letter: (
            ps._resolve_other_policy_cell(f"OtherPolicy_LineOfBusinessCode_{letter}", facts),
            ps._resolve_other_policy_cell(f"OtherPolicy_PolicyNumberIdentifier_{letter}", facts),
        )
        for letter in "ABCD"
    }
    # The two REAL policies are promoted into the first rows the form prints.
    assert got["A"] == ("Commercial Liability Umbrella", "6J7-40-02---26")
    assert got["B"] == ("Commercial General Liability", "BBC7263 - 26")
    assert got["C"] == (None, None)
    for _line, number in got.values():
        assert number != "IM 7100 06 04"
        assert number != "IM 7201 10 02"


def test_a_package_with_only_real_numbers_is_unchanged():
    facts = {"coverage_lines": [
        {"line": "Covered Autos Liability", "policy_number": "6E7-40-02---26"},
        {"line": "Commercial Inland Marine", "policy_number": "6C7-40-02---26"},
    ]}
    assert ps._resolve_other_policy_cell(
        "OtherPolicy_PolicyNumberIdentifier_A", facts) == "6E7-40-02---26"
    assert ps._resolve_other_policy_cell(
        "OtherPolicy_PolicyNumberIdentifier_B", facts) == "6C7-40-02---26"


# ── 2. A dec-page heading that OCR broke apart ───────────────────────────────
# Live log, 45 times:
#   dec_entries SECTION_DROPPED 'COMMERCIAL UMBRELLA DECLARATIONS' - not
#   literally present in the uploaded text
# Every dropped heading is a coverage part the package demonstrably contains, and
# `section` is the C23 discriminator, so the loss landed on exactly the pages
# that need it.

_N = es._dec_norm
_SPLIT_HEADING = _N(
    "COMMERCIAL UMBRELLA\n"
    "EMC Insurance Companies      Page 143 of 271\n"
    "DECLARATIONS\n"
    "Each Occurrence Limit (Liability Coverage) $ 3,000,000\n"
)


def test_a_heading_split_by_page_furniture_is_accepted():
    assert es._section_is_printed(_N("COMMERCIAL UMBRELLA DECLARATIONS"), _SPLIT_HEADING)


def test_a_contiguous_heading_is_still_accepted():
    hay = _N("GENERAL LIABILITY DECLARATIONS  Form CG7000A")
    assert es._section_is_printed(_N("GENERAL LIABILITY DECLARATIONS"), hay)


def test_an_invented_heading_is_still_rejected():
    """THE WHOLE SAFETY CASE. The relaxation may not let the model name a
    coverage part the package does not contain."""
    assert not es._section_is_printed(
        _N("PROFESSIONAL LIABILITY DECLARATIONS"), _SPLIT_HEADING)
    assert not es._section_is_printed(
        _N("WORKERS COMPENSATION DECLARATIONS"), _SPLIT_HEADING)


def test_word_order_is_not_negotiable():
    assert not es._section_is_printed(
        _N("DECLARATIONS UMBRELLA COMMERCIAL"), _SPLIT_HEADING)


def test_words_scattered_across_the_document_do_not_make_a_heading():
    """Ordered containment is bounded. Two words a page apart are a coincidence,
    not a printed heading."""
    hay = _N("COMMERCIAL " + ("filler " * 90) + "DECLARATIONS")
    assert not es._section_is_printed(_N("COMMERCIAL DECLARATIONS"), hay)


def test_the_entry_survives_when_only_its_section_fails():
    """A section is an ATTRIBUTION. Losing it must never lose the value."""
    doc = "GENERAL LIABILITY DECLARATIONS\nEach Occurrence Limit $1,000,000\n"
    out = es._verify_dec_entries([{
        "label": "Each Occurrence Limit", "value": "$1,000,000",
        "section": "PROFESSIONAL LIABILITY DECLARATIONS", "owner": "policy"}], doc)
    assert len(out) == 1 and out[0]["section"] is None
    assert out[0]["value"] == "$1,000,000"


def test_the_umbrella_and_gl_stay_separable():
    """What `section` is FOR (improving-ll.md C23): the identical label carrying
    two different amounts, told apart by the page each was printed on."""
    doc = ("COMMERCIAL UMBRELLA\nEMC   Page 143\nDECLARATIONS\n"
           "Each Occurrence Limit $ 3,000,000\n"
           "GENERAL LIABILITY DECLARATIONS\nEach Occurrence Limit $1,000,000\n")
    out = es._verify_dec_entries([
        {"label": "Each Occurrence Limit", "value": "$ 3,000,000",
         "section": "COMMERCIAL UMBRELLA DECLARATIONS", "owner": "policy"},
        {"label": "Each Occurrence Limit", "value": "$1,000,000",
         "section": "GENERAL LIABILITY DECLARATIONS", "owner": "policy"},
    ], doc)
    assert len(out) == 2
    by_section = {e["section"]: e["value"] for e in out}
    assert by_section["COMMERCIAL UMBRELLA DECLARATIONS"] == "$ 3,000,000"
    assert by_section["GENERAL LIABILITY DECLARATIONS"] == "$1,000,000"
    index = ps._render_dec_index(out)
    assert "$ 3,000,000" in index and "$1,000,000" in index


# ── 3. The guard that abstained must say so ──────────────────────────────────

def test_an_abstention_is_logged_with_its_reason(caplog):
    """Live: the producer's phone was still in the FAX box and this guard passed
    on it in silence, so a correct abstention and a missed catch looked identical
    in the log. The informative case is a duplicate that EXISTS and was spared
    only by the label test."""
    entries = [
        {"label": "Agent Phone", "value": "303-996-7800", "owner": "producer"},
        {"label": "Producer Contact Phone", "value": "303-996-7800", "owner": "producer"},
    ]
    mapped = {"Producer_ContactPerson_PhoneNumber_A": "303-996-7800",
              "Producer_FaxNumber_A": "303-996-7800"}
    import logging
    with caplog.at_level(logging.INFO, logger="services.pdf_service"):
        out = ps._second_claim_on_a_single_printed_value(
            "Producer_FaxNumber_A", mapped, {"Producer_FaxNumber_A"}, entries)
    assert out is None
    assert any("single_printed_value DECLINED" in r.message for r in caplog.records)


def test_no_log_when_there_is_nothing_to_decline(caplog):
    """No duplicate means this guard has no opinion - and must not say so on
    every field of every form."""
    entries = [{"label": "Agent Phone", "value": "303-996-7800", "owner": "producer"}]
    import logging
    with caplog.at_level(logging.INFO, logger="services.pdf_service"):
        ps._second_claim_on_a_single_printed_value(
            "Producer_FaxNumber_A", {"Producer_FaxNumber_A": "303-996-7800"},
            {"Producer_FaxNumber_A"}, entries)
    assert not any("DECLINED" in r.message for r in caplog.records)


def test_the_single_label_case_still_fires():
    entries = [{"label": "Total Policy Premium", "value": "$10,663", "owner": "policy"}]
    mapped = {"Policy_Payment_EstimatedTotalAmount_A": "$10,663",
              "Policy_Payment_DepositAmount_A": "$10,663"}
    assert ps._second_claim_on_a_single_printed_value(
        "Policy_Payment_DepositAmount_A", mapped,
        {"Policy_Payment_DepositAmount_A"}, entries
    ) == "Policy_Payment_EstimatedTotalAmount_A"


# ── 4. The fix that was tried and reverted ───────────────────────────────────

def test_a_name_only_additional_interest_is_still_legitimate():
    """DO NOT REBUILD THE ROW-SHAPE RULE.

    ACORD 125 Q11 shipped `NAME OF TRUST: Emcasco Insurance Company` - the
    carrier's own group company in a third-party box - inside an ADDITIONAL
    INTEREST block that was otherwise empty. "A name with no other detail is not
    a record" is the same structural rule that fixed the driver schedule, and it
    is wrong here: it broke 5 tests, all of them correct. A name-only additional
    interest is a SUPPORTED shape - the vehicle-ownership question answers itself
    by naming the owner and nothing else, and a mortgagee with no address yet is
    an ordinary partial.

    Row shape cannot tell the carrier's name from a lender's. Only identity can,
    and that lives in the ownership guard, which missed `emcasco` because it
    matches its family token `emc` by exact key rather than by prefix. Whether a
    3-character family token may match by prefix is a real question with a real
    case against it (EMCOR Group is a genuine construction firm) and it needs its
    own evidence, not this rule.
    """
    schema = {"AdditionalInterest_FullName_C": {},
              "AdditionalInterest_Primary_PhoneNumber_C": {}}
    mapped = {"AdditionalInterest_FullName_C": "Meridian Fleet Leasing, LLC",
              "AdditionalInterest_Primary_PhoneNumber_C": None}
    assert ps._unanchored_entity_row_fields(mapped, schema) == set()


def test_a_nameless_additional_interest_row_is_still_cleared():
    """The rule that DOES hold, unchanged: details with no subject."""
    schema = {"AdditionalInterest_FullName_C": {},
              "AdditionalInterest_Primary_PhoneNumber_C": {}}
    mapped = {"AdditionalInterest_FullName_C": None,
              "AdditionalInterest_Primary_PhoneNumber_C": "303-555-0100"}
    assert ps._unanchored_entity_row_fields(mapped, schema) == {
        "AdditionalInterest_Primary_PhoneNumber_C"}
