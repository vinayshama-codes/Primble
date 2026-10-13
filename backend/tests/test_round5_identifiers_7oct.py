"""Round 5 (7 Oct 2026) - identifiers that are not identifiers.

The owner's live run printed "COMMERCIAL AUTO CA DS 70 01 09 06" as the auto
policy number on ACORD 125 question 4, 127, 137 and the 131 underlying auto
row: the model joined the redacted "POLICYNUMBER: COMMERCIAL AUTO" with the
declarations' own form number printed on the next line. Brent's digit rule
(6 Oct) passed it - it has digits, every one of them the form number's.

The class, measured on the replay corpus (690 sessions): a policy-number value
whose digits belong to something that is not a contract - a form number among
words, a date, an amount, a bare count, a street address, another identifier's
own label, a number cut at its dash. One door (`normalization.
policy_number_refusal` / `is_not_a_policy_number`) and every reader.

Every value here is synthetic or a public form number; the shapes are the
corpus's, the strings are not the client's.
"""
import copy
import json
import os
import random
import string

import pytest

import services.normalization as norm
import services.extraction_service as es
import services.pdf_service as ps

_SCHEMAS = os.path.join(os.path.dirname(__file__), "..", "forms_schemas")


def _schema(form_id):
    with open(os.path.join(_SCHEMAS, f"{form_id}_schema.json")) as fh:
        return json.load(fh)


# =============================================================================
# 1. The live shape: a line label + the declarations' own form number
# =============================================================================
LIVE = "COMMERCIAL AUTO CA DS 70 01 09 06"
# The redacted declarations: the label line, the form number on the next one,
# and the same form number as the page's own footer.
LIVE_TEXT = ("POLICYNUMBER: COMMERCIAL AUTO\nCA DS 70 01 09 06\nBUSINESS AUTO DECLARATIONS\n"
             "EXAMPLE CASUALTY COMPANY\nPage1of7\nCA DS 70 01 09 06 (c)ISO Properties, Inc., 2005\n")
LIVE_ENTRIES = [
    {"label": "POLICYNUMBER", "value": "IL DS 71 05 02 08", "policy_number": None},
    # The redaction left the label beside the form number - the model read it as a contract.
    {"label": "Policy Number", "value": "CA DS 70 01 09 06", "policy_number": None},
]


def test_the_live_value_is_refused_with_its_own_reason():
    assert norm.policy_number_refusal(LIVE) == "LABEL_AND_FORM_NUMBER"
    assert norm.is_not_a_policy_number(LIVE)


def test_no_label_rescues_a_value_that_holds_no_identifier():
    # The entries print the bare form number under a POLICY NUMBER label; the
    # label still rescues that bare value without text (the 6 Oct contract) but
    # never the joined string, with or without the document text.
    assert not norm.is_not_a_policy_number("CA DS 70 01 09 06", LIVE_ENTRIES)
    assert norm.is_not_a_policy_number(LIVE, LIVE_ENTRIES)
    assert norm.is_not_a_policy_number(LIVE, LIVE_ENTRIES, LIVE_TEXT)
    assert norm.is_not_a_policy_number(LIVE, [{"label": "Policy Number", "value": LIVE}])


@pytest.mark.parametrize("value", [
    "COMMERCIAL AUTO CA DS 70 01 09 06",              # designator
    "CA DS 70 01 09 06 COMMERCIAL AUTO",              # form first, label after
    "GENERAL LIABILITY CG 00 01 04 13",               # ISO
    "Inland Marine IM 7100 06 04",                    # AAIS
    "COMMERCIAL UMBRELLA CU7001A 11-15",              # carrier, edition-dated
    "Business Auto CA7450 M",                         # carrier, edition letter
    "POLICY NUMBER: IL DS 71 05 02 08",               # the label itself + a designator
    "Commercial Property - CP DS 70 00 09 06 - INSURED COPY",
    "COMMERCIAL AUTO CA8214(5-12)",                   # bracketed one-digit month
    "Workers Compensation WC 00 00 00 C",
    "AUTO CA DS 70 01 09 06 CA DS 71 12 09 06",       # two forms, no number
])
def test_words_and_a_form_number_never_make_a_policy_number(value):
    assert norm.policy_number_refusal(value) == "LABEL_AND_FORM_NUMBER", value
    assert es._not_a_contract_number(value)
    assert not es._looks_like_a_policy_number(value)
    assert ps._not_a_contract_number(value)


@pytest.mark.parametrize("value", [
    "BA-456789 CA DS 70 01 09 06",        # a real number beside the form number: kept, never cut
    "Commercial Auto: BA-456789",         # a real number beside its line label: kept as is
    "GL 12 34 56 7890",                   # a form-shaped run inside a longer real number
])
def test_a_value_that_still_carries_an_identifier_is_not_refused(value):
    """Measured 7 Oct: no stored fact or box holds either shape - only whole
    schedule rows inside dec-entry values do - so nothing is cut down to "the
    number alone" (a line word can BE a number's prefix: "CPP 4Q 887214 26")."""
    assert norm.policy_number_refusal(value) is None


# =============================================================================
# 2. The bracketed carrier editions (corpus: EMC page footers tagged as numbers)
# =============================================================================
@pytest.mark.parametrize("form", ["CA8214(5-12)", "CA8214.1(5-12)", "CA8282(8-18)",
                                  "CA8112.2(11-15)", "CA7313(11-15)", "CA7007 (11-20)",
                                  "IL7001[1-09]"])
def test_a_bracketed_edition_is_a_form_number(form):
    assert norm.looks_like_a_form_number(form)
    assert ps._looks_like_a_form_number(form)
    assert norm.policy_number_refusal(form) == "FORM_NUMBER"


@pytest.mark.parametrize("policy", ["BBC7263 (26)", "CPP1234567", "BBC7263-26", "CA 7784121 25",
                                    "CPP-4821-2024.00", "POL-554433", "AB 12345678 (09-24)"])
def test_a_bracket_alone_never_makes_a_form(policy):
    assert not norm._BRACKETED_EDITION_FORM_NUMBER_RE.match(policy)


# =============================================================================
# 3. Dates, amounts, counts, addresses, other identifiers, cut-off numbers
# =============================================================================
@pytest.mark.parametrize("value,reason", [
    ("09/01/2026", "DATE_NOT_AN_IDENTIFIER"),
    ("07/15/2025 - 07/15/2026", "DATE_NOT_AN_IDENTIFIER"),
    ("2025-2026", "DATE_NOT_AN_IDENTIFIER"),
    ("2025 - 2026", "DATE_NOT_AN_IDENTIFIER"),
    ("EFFECTIVE DATE: 01/01/2025", "DATE_NOT_AN_IDENTIFIER"),
    ("Policy Number EFFECTIVE DATE 01/01/2025", "DATE_NOT_AN_IDENTIFIER"),
    ("ISSUE DATE:01/23/2025", "DATE_NOT_AN_IDENTIFIER"),
    ("January 1, 2026", "DATE_NOT_AN_IDENTIFIER"),
    ("Effective Jan. 1, 2026", "DATE_NOT_AN_IDENTIFIER"),
    ("$4,600,000", "AMOUNT_NOT_AN_IDENTIFIER"),
    ("$1,000,000 EACH ACCIDENT", "AMOUNT_NOT_AN_IDENTIFIER"),
    ("$ 10,692", "AMOUNT_NOT_AN_IDENTIFIER"),
    ("1,000,000 / 2,000,000", "AMOUNT_NOT_AN_IDENTIFIER"),
    ("80%", "AMOUNT_NOT_AN_IDENTIFIER"),
    ("500.00", "AMOUNT_NOT_AN_IDENTIFIER"),
    ("9", "TOO_SHORT_FOR_AN_IDENTIFIER"),
    ("41", "TOO_SHORT_FOR_AN_IDENTIFIER"),
    ("Beta Testing Round 1", "TOO_SHORT_FOR_AN_IDENTIFIER"),
    ("test 1", "TOO_SHORT_FOR_AN_IDENTIFIER"),
    ("1500 Market Street", "STREET_ADDRESS"),
    ("7740 Foundry Lane", "STREET_ADDRESS"),
    ("9780 S Meridian Blvd Ste 400", "STREET_ADDRESS"),
    ("ACCOUNT 4471100", "OTHER_IDENTIFIER_LABEL"),
    ("Acct# 0482854", "OTHER_IDENTIFIER_LABEL"),
    ("FEIN 84-0000000", "OTHER_IDENTIFIER_LABEL"),
    ("NAIC: 12345", "OTHER_IDENTIFIER_LABEL"),
    ("Phone 303-555-0100", "OTHER_IDENTIFIER_LABEL"),
    ("Tax ID 12-3456789", "OTHER_IDENTIFIER_LABEL"),
    ("CGL-2024-", "TRUNCATED_IDENTIFIER"),
    ("AUTO-2024-", "TRUNCATED_IDENTIFIER"),
    ("6E7-40-02---", "TRUNCATED_IDENTIFIER"),
    ("BBC7263 -", "TRUNCATED_IDENTIFIER"),
])
def test_each_non_identifier_is_refused_with_a_distinct_reason(value, reason):
    assert norm.policy_number_refusal(value) == reason, value
    assert reason in norm.NEW_POLICY_NUMBER_REFUSALS
    assert norm.is_not_a_policy_number(value)
    # ...and no POLICY NUMBER label rescues one
    assert norm.is_not_a_policy_number(value, [{"label": "POLICY NUMBER", "value": value}])


def test_the_older_reasons_are_unchanged():
    entries = [{"label": "Account Number", "value": "0482854"},
               {"label": "POLICYNUMBER", "value": "IL DS 71 05 02 08"}]
    footer = "IL DS 71 05 02 08 INSURED COPY Page 1 of 2\n"
    assert norm.policy_number_refusal("COMMERCIAL AUTO") == "NO_DIGIT"
    assert norm.policy_number_refusal("IM 7100 06 04") == "FORM_NUMBER"
    assert norm.policy_number_refusal("0482854", entries) == "ACCOUNT_NUMBER"
    assert norm.policy_number_refusal("IL DS 71 05 02 08", entries) is None   # label wins
    assert norm.policy_number_refusal("IL DS 71 05 02 08", entries, footer) == "FORM_NUMBER_FOOTER"
    assert norm.policy_number_refusal("BM 1234 05 21",
                                      [{"label": "Policy No.", "value": "BM 1234 05 21"}]) is None
    assert norm.policy_number_refusal("") is None
    assert norm.policy_number_refusal(None) is None
    assert not (norm.NEW_POLICY_NUMBER_REFUSALS
                & {"NO_DIGIT", "FORM_NUMBER", "FORM_NUMBER_FOOTER", "ACCOUNT_NUMBER"})


# =============================================================================
# 4. Every real policy number keeps passing (look-alikes from the corpus shapes)
# =============================================================================
REAL = [
    # Orbin (already pinned elsewhere) and FR125
    "6E7-40-02---26", "6J7-40-02---26", "6C7-40-02---26", "BBC7263-26", "BBC7263 - 26",
    "BBC7263", "6E74002", "6J74002", "6J74002---26", "6E7-40-02-26", "6J7-40-02-26",
    "6 E 7 - 4 0 - 0 2---26", "6 C 7 - 4 0 - 0 2---26", "7263-26",
    "GL-123456", "BA-456789", "CP-567890", "CU-678901",
    # the corpus's look-alike shapes (line-abbreviation prefixes, years, spaced groups)
    "CPP 4Q 887214 26", "XSU 55 210934 25", "GL 7784120 25", "CA 7784121 25", "WC 9930221 26",
    "9930221 26", "4A8 21 07 26", "4A8-21-07---26", "CPP-4821-2024-CO", "CPP-4821-2024.00",
    "TC-GL-7700441-2025", "CGL-2024-845671", "POL-987654321-00", "CPP-2025-AFS-001",
    "UMB-2026-STRONG-001", "OHM-CA-4471903-25", "CR-4471", "WC 558204", "123456", "0482854",
    "SIM7730418", "U6550407", "QPC5519 - 26", "BOP 7654321 01 26", "AB 12345678", "POL123",
    "X-1", "CIN-7741882-WC", "MSG-4471902-CGL", "GL-ST-449102", "CAP-4471-OR-31",
    "L-2024-1187", "2024-1187", "BM 1234 05 21-A",
]


@pytest.mark.parametrize("policy", REAL)
def test_real_policy_numbers_survive_every_reader(policy):
    assert norm.policy_number_refusal(policy) is None, policy
    assert not es._not_a_contract_number(policy)
    assert not ps._not_a_contract_number(policy)
    if len(policy) >= 4:
        assert es._looks_like_a_policy_number(policy)


def test_twenty_thousand_policy_shapes_are_never_refused():
    rng = random.Random(75)
    shapes = ["LLLddddddd", "LLL-dddddd-dd", "dLd-dd-dd---dd", "LLLdddd-dd", "LL dddddddd",
              "LLLdddddd", "LL-ddd-ddd", "dd-LL-dddddd-d", "LL L ddddddd", "LLL dddd dd",
              "LL-LL-dddddd-dd", "LLL-dddd-dddd-LL", "LL dddddd dd", "LLL-LLL-dddd",
              "Ld-dddd", "dddddd", "LLL dd dddddd dd", "LL-dddd-LL-dd", "LLL-ddddddd-dddd"]
    for _ in range(20000):
        v = "".join(rng.choice(string.ascii_uppercase) if c == "L"
                    else rng.choice(string.digits) if c == "d" else c
                    for c in rng.choice(shapes))
        assert norm.policy_number_refusal(v) in (None, "FORM_NUMBER"), v
        if norm.policy_number_refusal(v) == "FORM_NUMBER":
            # only ever a value the form-shape door already refused before today
            assert norm.looks_like_a_form_number(v), v


def test_a_date_inside_a_policy_number_token_is_not_a_date():
    """Token by token, never by substring: "40-02-26" inside "6E7-40-02-26"."""
    assert norm.policy_number_refusal("6E7-40-02-26") is None
    assert norm.policy_number_refusal("GL-01-01-2025-7") is None


def test_the_door_never_raises_on_junk():
    for junk in [0, 12.5, ["6E7"], {"v": 1}, "   ", "\n", "-", "$", "%", ":", "()", "#"]:
        norm.policy_number_refusal(junk)
        norm.is_not_a_policy_number(junk)


# =============================================================================
# 5. Where the value is born: the per-document scrub and the merged scalar
# =============================================================================
def test_the_per_document_scrub_clears_the_live_shape_from_scalar_rows_and_tags():
    facts = {
        "policy_number": {"value": LIVE, "source": "ai", "confidence": "ai_high"},
        "coverage_lines": [{"line": "Commercial Auto", "carrier": "Example Casualty Company",
                            "policy_number": LIVE, "effective_date": "01/01/2025",
                            "expiration_date": "01/01/2026"}],
        "underlying_policies": [{"line": "Automobile Liability", "policy_no": "AUTO-2024-"}],
        "dec_page_entries": [dict(e) for e in LIVE_ENTRIES]
                            + [{"label": "Limit", "value": "1,000,000",
                                "policy_number": "CA8214(5-12)"}],
    }
    cleared = es._scrub_non_contract_identifiers(facts, LIVE_TEXT)
    assert facts["policy_number"]["value"] == ""
    assert facts["policy_number"]["source"] == "ai"
    assert facts["coverage_lines"][0]["policy_number"] is None
    assert facts["coverage_lines"][0]["carrier"] == "Example Casualty Company"   # the row stays
    assert facts["underlying_policies"][0]["policy_no"] is None
    assert facts["dec_page_entries"][-1]["policy_number"] is None
    assert len(cleared) == 4


def test_the_merged_scalar_backstop_clears_it_too():
    mf = {"policy_number": {"value": LIVE, "source": "ai"},
          "prior_policy_number": "07/15/2025 - 07/15/2026",
          "umbrella_policy_number": "XSU 55 210934 26"}
    cleared = es._drop_form_numbers_from_policy_facts(mf)
    assert mf["policy_number"]["value"] == ""
    assert mf["prior_policy_number"] == ""
    assert mf["umbrella_policy_number"] == "XSU 55 210934 26"
    assert len(cleared) == 2


# =============================================================================
# 6. Line records, identity and the Data Consistency card read the one door
# =============================================================================
_ROWS = [
    {"line": "Commercial Auto", "carrier": "Example Casualty Company", "policy_number": LIVE,
     "effective_date": "01/01/2025", "expiration_date": "01/01/2026"},
    {"line": "Commercial General Liability", "carrier": "Example Casualty Company",
     "policy_number": "GL 4400102 25", "premium": "$ 5,000.00",
     "effective_date": "01/01/2025", "expiration_date": "01/01/2026"},
]


def test_a_line_record_never_takes_the_junk_as_its_number():
    """The auto policy is still a policy (its own declarations), just unnumbered."""
    docs = [{"filename": "auto_dec.pdf", "facts": {"coverage_lines": [copy.deepcopy(_ROWS[0])]}},
            {"filename": "package.pdf", "facts": {"coverage_lines": [copy.deepcopy(_ROWS[1])]}}]
    recs = es._build_line_records({"coverage_lines": copy.deepcopy(_ROWS)}, docs)
    auto = [r for r in recs if r["line"] == "auto"]
    assert len(auto) == 1
    assert not auto[0].get("policy_number")
    assert auto[0]["id"] == "auto#unnumbered"
    assert auto[0].get("own_declarations") is True
    gl = [r for r in recs if r["line"] == "general_liab"]
    assert gl[0]["policy_number"] == "GL 4400102 25"
    assert not any(LIVE in str(r) for r in recs)


def test_a_row_identified_only_by_a_junk_number_identifies_nothing():
    assert not es._line_entry_identifies_policy({"line": "Commercial Auto", "policy_number": LIVE})
    assert not es._line_entry_identifies_policy({"line": "Commercial Auto",
                                                 "policy_number": "ACCOUNT 4471100"})
    assert es._line_entry_identifies_policy({"line": "Commercial Auto", "policy_number": "BA-456789"})
    # the carrier still identifies the row, whatever the number cell holds
    assert es._line_entry_identifies_policy({"line": "Commercial Auto", "carrier": "Example Casualty",
                                             "policy_number": LIVE})


def test_the_data_consistency_card_never_offers_it():
    from services.underwriting_consistency import _is_form_number_policy_value
    assert _is_form_number_policy_value("policy_number", LIVE)
    assert _is_form_number_policy_value("policy_number", LIVE, LIVE_ENTRIES, LIVE_TEXT)
    assert _is_form_number_policy_value("prior_policy_number", "ACCOUNT 4471100")
    assert not _is_form_number_policy_value("policy_number", "BBC7263-26")


def test_the_evidence_of_a_policy_needs_a_real_number():
    assert not ps._line_entry_evidences_policy({"line": "Commercial Auto", "policy_number": LIVE})
    assert not ps._line_entry_evidences_policy({"line": "Commercial Auto",
                                                "policy_number": "CGL-2024-"})
    assert ps._line_entry_evidences_policy({"line": "Commercial Auto", "policy_number": "BA-456789"})


def test_a_junk_number_beside_the_real_one_no_longer_blanks_the_line():
    """Corpus shape (a carrier page header "ACCOUNT nnnnnnn" read as a second GL
    number): two candidates on one line used to mean "box left blank"; the
    junk is not a candidate, so the line's one real number prints."""
    rows = copy.deepcopy(_ROWS) + [
        {"line": "Commercial General Liability", "carrier": "Example Casualty Company",
         "policy_number": "ACCOUNT 4400100", "effective_date": "01/01/2025",
         "expiration_date": "01/01/2026"}]
    facts = {"coverage_lines": rows, "_form_id": "ACORD_126"}
    with ps._schema_context(_schema("ACORD_126")):
        got = ps._resolve_section_policy_identity("Policy_PolicyNumberIdentifier_A", facts)
    assert got == "GL 4400102 25"


def test_question_4_never_lists_the_junk_and_its_answer_follows_the_list():
    """ACORD 125 question 4 lists only policies with a real number (24 Sep rule);
    its Y follows the list. The live 'Y' stood on the junk row alone."""
    facts = {"coverage_lines": copy.deepcopy(_ROWS), "_form_id": "ACORD_125"}
    rows = ps._other_policy_rows(facts) or []
    assert [r["policy_number"] for r in rows] == ["GL 4400102 25"]
    only_junk = {"coverage_lines": [copy.deepcopy(_ROWS[0])], "_form_id": "ACORD_125"}
    assert not ps._other_policy_rows(only_junk)
    assert ps._resolve_page_one_receiving_carrier(
        "CommercialPolicy_Question_AAHCode_A", only_junk) != "Y"


_OWN_DEC_RECORD = {"id": "auto#unnumbered", "line": "auto", "policy_number": None,
                   "carrier_name": "Example Casualty Company", "own_declarations": True}


def test_a_policy_with_its_own_declarations_is_a_policy_whatever_its_number():
    """The refused number must not take the policy's carrier and term with it:
    the evidence is the line's own declarations document, never the number."""
    row = {"line": "Commercial Auto", "carrier": "Example Casualty Company", "policy_number": LIVE}
    facts = {"_line_records": [dict(_OWN_DEC_RECORD)]}
    assert not ps._line_entry_evidences_policy(row)                   # no facts: as before
    assert ps._line_entry_evidences_policy(row, facts)
    assert ps._line_entry_evidences_policy(dict(row, policy_number=None), facts)
    # another insurer's row is another policy; no own-declarations record, no evidence
    assert not ps._line_entry_evidences_policy(dict(row, carrier="Other Mutual Company"), facts)
    assert not ps._line_entry_evidences_policy(
        row, {"_line_records": [dict(_OWN_DEC_RECORD, own_declarations=False)]})
    assert not ps._line_entry_evidences_policy(dict(row, line="Commercial General Liability"), facts)
    # a carrier-less row needs exactly one such record
    assert ps._line_entry_evidences_policy(dict(row, carrier=None), facts)
    two = {"_line_records": [dict(_OWN_DEC_RECORD), dict(_OWN_DEC_RECORD, carrier_name="Other Mutual")]}
    assert not ps._line_entry_evidences_policy(dict(row, carrier=None), two)
    # a denied line is never evidence
    assert not ps._line_entry_evidences_policy(dict(row, premium="No Coverage"), facts)


def test_the_131_underlying_auto_keeps_its_term_when_the_number_is_refused():
    facts = {"coverage_lines": [{"line": "Commercial Auto", "carrier": "Example Casualty Company",
                                 "policy_number": LIVE, "effective_date": "01/01/2025",
                                 "expiration_date": "01/01/2026"}],
             "_line_records": [dict(_OWN_DEC_RECORD)], "_form_id": "ACORD_131"}
    with ps._schema_context(_schema("ACORD_131")):
        got = {a: ps._resolve_underlying_policy_row(f"UnderlyingPolicy_Automobile_{a}_A", facts)
               for a in ("PolicyNumberIdentifier", "InsurerFullName",
                         "PolicyEffectiveDate", "PolicyExpirationDate")}
    assert not got["PolicyNumberIdentifier"]
    assert got["InsurerFullName"] == "Example Casualty Company"
    assert got["PolicyEffectiveDate"] == "01/01/2025"
    assert got["PolicyExpirationDate"] == "01/01/2026"


def test_the_underlying_and_prior_grid_readers_skip_it():
    facts = {"underlying_policies": [
        {"line": "Automobile Liability", "carrier": "Example Casualty Company", "policy_no": LIVE},
        {"line": "General Liability", "carrier": "Example Casualty Company", "policy_no": "CGL-2024-"}]}
    assert ps._underlying_policy_number(facts, ("auto", "automobile")) is None
    assert ps._underlying_policy_number(facts, ("general liability",)) is None
    facts["underlying_policies"].append({"line": "Automobile Liability",
                                         "carrier": "Example Casualty Company",
                                         "policy_no": "BA-456789"})
    assert ps._underlying_policy_number(facts, ("auto", "automobile")) == "BA-456789"


# =============================================================================
# 7. The box: every policy-number box, every source, blank with a reason
# =============================================================================
def _guard(mapped, facts=None):
    schema = {f: {"ft": "/Tx", "tu": "Enter identifier: The identifier assigned by the insurer "
                                      "to the policy."} for f in mapped}
    reasons = {}
    ps._GUARD_REASON_CTX.sink = reasons
    try:
        ps._enforce_post_fill_guards(mapped, schema, facts or {}, set())
    finally:
        ps._GUARD_REASON_CTX.sink = None
    return mapped, reasons


def test_the_box_guard_blanks_the_live_value_on_every_form_and_names_its_rule():
    boxes = {
        "OtherPolicy_PolicyNumberIdentifier_A": LIVE,                       # 125 question 4
        "Policy_PolicyNumberIdentifier_A": LIVE,                            # 127 / 137 header
        "UnderlyingPolicy_Automobile_PolicyNumberIdentifier_A": LIVE,       # 131 underlying auto
        "PriorCoverage_Automobile_PolicyNumberIdentifier_A": "09/01/2026",  # 125 prior grid
        "Policy_AutomobileLiability_PolicyNumberIdentifier_A": "$4,600,000",  # ACORD 25 row
    }
    mapped, reasons = _guard(dict(boxes), {"dec_page_entries": LIVE_ENTRIES})
    assert all(mapped[f] is None for f in boxes)
    assert reasons["Policy_PolicyNumberIdentifier_A"] == "NOT_A_POLICY_NUMBER_LABEL_AND_FORM_NUMBER"
    assert reasons["PriorCoverage_Automobile_PolicyNumberIdentifier_A"] == \
        "NOT_A_POLICY_NUMBER_DATE_NOT_AN_IDENTIFIER"
    assert reasons["Policy_AutomobileLiability_PolicyNumberIdentifier_A"] == \
        "NOT_A_POLICY_NUMBER_AMOUNT_NOT_AN_IDENTIFIER"


def test_the_box_guard_keeps_real_numbers_and_the_older_refusals_report_as_before():
    mapped, reasons = _guard({"Policy_PolicyNumberIdentifier_A": "BA-456789",
                              "OtherPolicy_PolicyNumberIdentifier_A": "IM 7100 06 04",
                              "OtherPolicy_PolicyNumberIdentifier_B": "6E7-40-02---26"})
    assert mapped["Policy_PolicyNumberIdentifier_A"] == "BA-456789"
    assert mapped["OtherPolicy_PolicyNumberIdentifier_A"] is None        # form number, as before
    assert "OtherPolicy_PolicyNumberIdentifier_A" not in reasons         # ...and reported as before
    assert mapped["OtherPolicy_PolicyNumberIdentifier_B"] == "6E7-40-02---26"


def test_a_full_stamp_of_the_auto_section_prints_no_junk_number():
    """The 127 header through the real stamper (no LLM): the stored session's
    shape - the merged scalar, the auto row and its record all holding the
    joined value - ships the header blank with the guard's reason."""
    facts = {
        "applicant_name": "Example Electric LLC",
        "policy_number": {"value": LIVE, "source": "ai", "confidence": "ai_high"},
        "carrier_name": "Example Casualty Company",
        "coverage_lines": copy.deepcopy(_ROWS),
        "dec_page_entries": [dict(e) for e in LIVE_ENTRIES],
        "effective_date": "01/01/2025", "expiration_date": "01/01/2026",
    }
    report = []
    mapped, _conf = ps.map_facts_to_form(facts, _schema("ACORD_127"), form_id="ACORD_127",
                                         raw_text=LIVE_TEXT, pre_filled_gpt={},
                                         guard_report=report, allow_llm=False)
    header = mapped.get("Policy_PolicyNumberIdentifier_A")
    assert not header or "CA DS" not in str(header)
    assert not any("CA DS 70" in str(v) for k, v in mapped.items()
                   if "PolicyNumberIdentifier" in k and v)
