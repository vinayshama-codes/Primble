"""A street line must not repeat the locality that has its own boxes.

Live 2026-09-07, ACORD 125's ADDITIONAL INTEREST block:

    AdditionalInterest_MailingAddress_LineOne_A  "870 Wharfside Blvd Tacoma, WA 98421"
    AdditionalInterest_MailingAddress_CityName_A            "Tacoma"
    AdditionalInterest_MailingAddress_StateOrProvinceCode_A "WA"
    AdditionalInterest_MailingAddress_PostalCode_A          "98421"

The locality printed twice on one legal document, once in a box that is not for
it. Generic across every address block on every form - the block is the field
name's own prefix, so no per-form list and no address parsing is involved. It
only ever REMOVES a trailing repetition of values that stay visible in their own
boxes, so it can shorten a line but never lose information.
"""
import json
import os
import random
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
os.environ.setdefault("OPENAI_API_KEY", "sk-offline-test")

import services.pdf_service as ps                                # noqa: E402

P = "AdditionalInterest_MailingAddress_"
LINE = P + "LineOne_A"


def _trim(line, city="Tacoma", state="WA", postal="98421"):
    mapped = {LINE: line}
    if city:
        mapped[P + "CityName_A"] = city
    if state:
        mapped[P + "StateOrProvinceCode_A"] = state
    if postal:
        mapped[P + "PostalCode_A"] = postal
    ps._trim_address_line_repeating_its_own_locality(mapped)
    return mapped[LINE]


@pytest.mark.parametrize("line", [
    "870 Wharfside Blvd Tacoma, WA 98421",          # THE LIVE VALUE
    "870 Wharfside Blvd, Tacoma, WA 98421",
    "870 Wharfside Blvd  Tacoma  WA  98421",
    "870 Wharfside Blvd, Tacoma WA 98421,",
    "870 Wharfside Blvd TACOMA, wa 98421",          # case-insensitive
])
def test_a_line_repeating_its_own_locality_is_trimmed(line):
    assert _trim(line) == "870 Wharfside Blvd"


def test_zip_plus_four():
    assert _trim("870 Wharfside Blvd Tacoma WA 98421-1234",
                 postal="98421-1234") == "870 Wharfside Blvd"


@pytest.mark.parametrize("line", [
    "Tacoma Avenue South",        # a street NAMED after the town
    "WA Highway 16 Business Park",
    "870 Wharfside Blvd",
    "PO Box 4471",
    "Suite 300",
    "1 Tacoma Mall Blvd",
])
def test_a_legitimate_line_is_never_touched(line):
    """Only a TRAILING repetition is removed - a street legitimately named after
    its own town keeps its name."""
    assert _trim(line) == line


def test_no_locality_boxes_means_no_opinion():
    """If nothing else holds the city/state/postal, the line is the only place
    that information exists and must not be shortened."""
    line = "870 Wharfside Blvd Tacoma, WA 98421"
    assert _trim(line, city=None, state=None, postal=None) == line


def test_it_declines_when_trimming_would_empty_the_line():
    """A line that is ONLY the city was never a street; blanking it would lose
    the box's content rather than de-duplicate it."""
    assert _trim("Tacoma", state=None, postal=None) == "Tacoma"


def test_the_live_block_through_the_real_stamper():
    schema_path = os.path.join(os.path.dirname(__file__), "..", "forms_schemas",
                               "ACORD_125_schema.json")
    with open(schema_path, encoding="utf-8") as fh:
        schema = json.load(fh)
    facts = {"applicant_name": "Harborline Provisions LLC",
             "certificate_holder": "Kestrel Terminal Authority",
             "has_general_liability": True, "has_auto_coverage": True}
    gpt = {"filled_values": {
        "AdditionalInterest_FullName_A": "Kestrel Terminal Authority",
        LINE: "870 Wharfside Blvd Tacoma, WA 98421",
        P + "CityName_A": "Tacoma", P + "StateOrProvinceCode_A": "WA",
        P + "PostalCode_A": "98421"},
        "raw_text_fields": set(), "question_grounding": {}}
    res = ps.map_facts_to_form(dict(facts), schema, "ACORD_125", "",
                               pre_filled_gpt=gpt)
    mapped = res[0] if isinstance(res, tuple) else res
    assert mapped[LINE] == "870 Wharfside Blvd"
    assert mapped[P + "CityName_A"] == "Tacoma"
    assert mapped[P + "StateOrProvinceCode_A"] == "WA"
    assert mapped[P + "PostalCode_A"] == "98421"


def test_it_reaches_every_address_block_not_just_this_one():
    """No per-form list: the block is the field name's own prefix."""
    import glob
    claimed = set()
    for path in glob.glob(os.path.join(os.path.dirname(__file__), "..",
                                       "forms_schemas", "*_schema.json")):
        with open(path, encoding="utf-8") as fh:
            claimed |= {k for k in json.load(fh) if ps._ADDR_LINE_RE.match(k)}
    # 39 DISTINCT field names across the 17 schemas (77 occurrences; the same
    # name appears on several forms). Measured, not guessed - the first version
    # of this assertion used the per-schema count and was simply wrong.
    assert len(claimed) >= 39, sorted(claimed)
    for expected in ("NamedInsured_MailingAddress_LineOne_A",
                     "CertificateHolder_MailingAddress_LineOne_A",
                     "AdditionalInterest_MailingAddress_LineOne_A",
                     "Producer_MailingAddress_LineOne_A"):
        assert expected in claimed, expected


@pytest.mark.parametrize("value", [None, 0, "", "   ", [], {}, True, b"x",
                                   3.5, "x" * 400])
def test_degenerate_values_never_raise(value):
    mapped = {LINE: value, P + "CityName_A": "Tacoma"}
    ps._trim_address_line_repeating_its_own_locality(mapped)


@pytest.mark.parametrize("locality", [None, 0, [], {}, True, b"x", 3.5])
def test_degenerate_locality_boxes_never_raise(locality):
    mapped = {LINE: "870 Wharfside Blvd Tacoma", P + "CityName_A": locality}
    ps._trim_address_line_repeating_its_own_locality(mapped)


def test_a_regex_special_character_in_a_city_name():
    """`re.escape` on the pieces - a city with punctuation must not blow up or
    match as a pattern."""
    assert _trim("12 Main St St. Mary's (North)", city="St. Mary's (North)",
                 state=None, postal=None) == "12 Main St"


def test_fuzzed_address_blocks_never_raise():
    rng = random.Random(11)
    vals = [None, 0, "", [], {}, True, b"x", 3.5, "x" * 200,
            "870 Wharfside Blvd Tacoma, WA 98421", "Tacoma", "WA", "98421"]
    for _ in range(2000):
        mapped = {P + k + "_A": rng.choice(vals)
                  for k in ("LineOne", "LineTwo", "CityName",
                            "StateOrProvinceCode", "PostalCode")}
        ps._trim_address_line_repeating_its_own_locality(mapped)
