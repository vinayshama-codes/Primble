"""`clean_text` must remove page furniture and NOTHING else.

This function runs on every uploaded document before extraction, before gap
fill, before anything. Whatever it deletes is invisible to the whole rest of the
pipeline - including `_verify_coverage`, which reports 100% coverage of what
SURVIVES this function and will happily declare success over a shredded
document. That is exactly what happened: three filters here were measured
deleting 56% of a realistic declarations page (the named insured, both General
Liability limits, and a vehicle schedule row) while the pipeline reported
"671654/671654 chars - 100%".

If a test in this file fails, do not adjust the test. A filter has been added
back that deletes content.
"""
import pytest

from utils.text_cleaner import clean_text


_DEC_PAGE = """COMMERCIAL LINES POLICY DECLARATIONS
NAMED INSURED RIDGELINE SHEET METAL AND ROOFING CONTRACTORS LLC
MAILING ADDRESS 4820 PROSPECT AVENUE SUITE 210 DENVER COLORADO 80216
EACH OCCURRENCE LIMIT OF LIABILITY IS ONE MILLION DOLLARS PER CLAIM
GENERAL AGGREGATE LIMIT APPLIES PER POLICY AND EQUALS TWO MILLION DOLLARS
VEHICLE SCHEDULE ITEM ONE 2012 FORD F250 GARAGED AT DENVER CO 80202
VEHICLE SCHEDULE ITEM TWO 2014 RAM 2500 GARAGED AT DENVER CO 80202
"""


def test_all_caps_declarations_content_survives():
    """Declarations pages are written in capitals. An ALL-CAPS filter here is
    not a boilerplate filter, it is a content filter."""
    out = clean_text(_DEC_PAGE)
    for line in _DEC_PAGE.strip().splitlines():
        assert line.strip() in out, (
            f"ALL-CAPS content line was deleted: {line.strip()!r}\n"
            f"An uppercase-ratio filter has been reintroduced. Dec pages are "
            f"uppercase; this deletes named insureds and coverage limits."
        )


def test_no_meaningful_content_is_lost_overall():
    out = clean_text(_DEC_PAGE)
    kept = len(out) / len(_DEC_PAGE)
    assert kept > 0.90, (
        f"clean_text kept only {kept:.0%} of a declarations page. It is supposed "
        f"to strip page furniture, not content."
    )


@pytest.mark.parametrize("value", [
    "80216",            # a postcode alone in a table cell
    "1000000",          # a limit
    "2012",             # a model year
    "91560",            # a GL class code
])
def test_a_bare_number_on_its_own_line_survives(value):
    """`^\\s*\\d+\\s*$` used to delete these. In an ACORD table a lone number is
    far more often a real value than a page number."""
    doc = f"POLICY SECTION\n\n{value}\n\nEND OF SECTION"
    assert value in clean_text(doc), (
        f"bare number {value!r} was deleted - the digit-only-line rule is back"
    )


@pytest.mark.parametrize("value", ["CO 80216", "$1,000,000", "07/15/25", "ACV"])
def test_short_real_values_survive(value):
    """A 10-character paragraph floor deleted these."""
    doc = f"COVERAGE DETAIL\n\n{value}\n\nNEXT SECTION HEADING"
    assert value in clean_text(doc), (
        f"short value {value!r} was deleted - a paragraph length floor is back"
    )


def test_a_repeated_fleet_row_is_not_collapsed():
    """The MD5 dedup deleted real repeated data. Three trucks garaged at one
    address legitimately produce that address three times."""
    doc = ("VIN 1FT7W2BT4NEC10473\n\nGaraged: 4820 Prospect Ave\n\n"
           "VIN 3C63RRHL9MG551208\n\nGaraged: 4820 Prospect Ave\n\n"
           "VIN 54DC4W1D0PS812640\n\nGaraged: 4820 Prospect Ave")
    out = clean_text(doc)
    assert out.count("Garaged: 4820 Prospect Ave") == 3, (
        f"fleet garaging rows collapsed to {out.count('Garaged: 4820 Prospect Ave')} "
        f"of 3 - global paragraph de-duplication is back on"
    )
    for vin in ("1FT7W2BT4NEC10473", "3C63RRHL9MG551208", "54DC4W1D0PS812640"):
        assert vin in out


def test_page_furniture_is_still_removed():
    """The legitimate job must keep working."""
    doc = "Named Insured: Acme\nPage 3 of 12\nPolicy CPP-1234\n- 7 -\nCarrier: Meridian"
    out = clean_text(doc)
    assert "Page 3 of 12" not in out
    assert "\n- 7 -" not in out
    assert "Named Insured: Acme" in out
    assert "Policy CPP-1234" in out
    assert "Carrier: Meridian" in out


def test_optional_dedup_kills_headers_but_keeps_fleet_rows(monkeypatch):
    """If someone re-enables de-duplication it must require MANY repeats, so a
    271-page running header goes and a 3-row fleet stays."""
    import utils.text_cleaner as tc
    monkeypatch.setattr(tc, "_DEDUP_MIN_REPEATS", 5)

    header = "EMPLOYERS MUTUAL CASUALTY COMPANY"
    fleet = "Garaged: 4800 Dahlia St"
    doc = "\n\n".join([header] * 10 + [fleet] * 3 + ["REAL BODY TEXT HERE"])
    out = tc.clean_text(doc)

    assert out.count(header) == 1, "a 10x running header should collapse to one"
    assert out.count(fleet) == 3, (
        "a 3x fleet row must NOT be treated as furniture even with dedup on"
    )


# ── The loss metric must be measured on CONTENT, not raw length ──────────────
# The alarm exists so a content deletion can never be silent again. That only
# works if it fires on content deletion and NOT on the whitespace collapse, which
# is lossless. pdfplumber pads columns with runs of spaces, so a perfectly intact
# layout-extracted declarations page loses ~22% of its BYTES to the collapse - and
# an alarm that fires on the normal case gets ignored, then disbelieved on the day
# it is real. That is exactly how the original 56% deletion survived several
# rounds of review.

def test_whitespace_collapse_is_not_reported_as_content_loss(caplog):
    """A column-padded page: every token survives, so nothing may be flagged."""
    import logging
    page = ("Named Insured:        RIDGELINE SHEET METAL LLC\n"
            "Policy Number:        GL-4471          Effective:   07/25/25\n"
            "Each Occurrence:      $1,000,000       Aggregate:   $2,000,000\n") * 300
    with caplog.at_level(logging.WARNING, logger="utils.text_cleaner"):
        out = clean_text(page)

    assert "RIDGELINE SHEET METAL LLC" in out
    assert "$2,000,000" in out
    assert len(out) < len(page), "the whitespace collapse should still happen"
    assert not [r for r in caplog.records if "CONTENT" in r.message], (
        "the loss alarm fired on a page that lost ZERO content - it is measuring "
        "raw length instead of non-whitespace characters, and will be ignored"
    )


def test_real_content_loss_still_raises_the_alarm(caplog, monkeypatch):
    """The inverse: if a filter ever starts eating content, it must be loud."""
    import logging
    import utils.text_cleaner as tc
    # Simulate a regression by re-enabling aggressive de-duplication.
    monkeypatch.setattr(tc, "_DEDUP_MIN_REPEATS", 2)
    monkeypatch.setattr(tc, "_DEDUP_MAX_LEN", 500)
    doc = "\n\n".join(["A REAL PARAGRAPH OF POLICY TEXT THAT REPEATS"] * 50)
    with caplog.at_level(logging.WARNING, logger="utils.text_cleaner"):
        tc.clean_text(doc)
    assert [r for r in caplog.records if "CONTENT" in r.message], (
        "content was deleted and the alarm stayed silent"
    )


def test_ink_counts_only_non_whitespace():
    import utils.text_cleaner as tc
    assert tc._ink("a b\tc\nd") == 4
    assert tc._ink("   \n\n\t  ") == 0
    assert tc._ink("") == 0
    assert tc._ink(None) == 0
