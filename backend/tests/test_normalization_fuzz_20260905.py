"""THE BROADER NORMALIZATION CLAUSE, tested instead of asserted (2026-09-05).

SYS-07's "WHAT WE OBSERVED" does not stop at booleans:

    "This is part of the broader normalization requirement that also applies to
     DATES, ADDRESSES, POLICY-NUMBER FORMATTING, and other equivalent values
     before Primble compares data."

and the acceptance criterion is absolute - *"formatting or representation
differences ALONE cannot produce a conflict"*.

Those other types were normalized by earlier work (Workstream-2's normalizers,
C1's comparison door, SYS-06's contract fold), and until now that was ASSERTED
rather than measured. This file measures it, with MESSY REAL-WORLD SHAPES
rather than the clean fixture values each item happened to ship with, in BOTH
directions: an equivalent pair must not conflict, and a genuinely different
pair must.

The sweep found two things on its first run:
  * `15-Jul-2025` vs `07/15/2025` came back a CONFLICT. A real export format
    from carrier and agency-management systems, and a pure formatting
    difference producing a warning. FIXED - `_DATE_FORMATS` gained the
    DD-Mon-YYYY family.
  * `BBC7263 - 26` vs `BBC7263` came back a conflict through `compare()`. NOT a
    defect - the term-marker fold is SYS-06's `same_policy_contract`, a
    different door, and that is the one the picker uses. The test was wrong,
    not the code. Both doors are pinned below so the distinction cannot rot.
"""
import pytest

from services import fact_comparison as fc
from services.normalization import normalize_date

SAME, DIFF = "same", "different"


def _verdict(fact_key, a, b):
    return DIFF if fc.compare(fact_key, [a, b]).verdict == "conflict" else SAME


# ─────────────────────────────────────────────────────────────────────────────
# Equivalent pairs - a representation difference must NEVER produce a conflict
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("key,a,b", [
    # Yes/No (SYS-07 itself)
    ("auto_hired_nonowned", "Yes", "X"),
    ("auto_hired_nonowned", "Yes", "Hired and Non-Owned Auto Coverage - X"),
    ("auto_hired_nonowned", "Yes", True),
    ("sprinkler_system", "Yes", "✓"),
    ("cyber_prior_incidents", "No", "N"),
    # Dates
    ("effective_date", "07/15/25", "07/15/2025"),
    ("effective_date", "7/15/2025", "July 15, 2025"),
    ("effective_date", "2025-07-15", "07/15/2025"),
    ("effective_date", "15-Jul-2025", "07/15/2025"),      # the sweep's find
    ("effective_date", "15/Jul/25", "07/15/2025"),
    ("effective_date", "07.15.2025", "07-15-2025"),
    # Addresses
    ("mailing_address", "4800 DAHLIA ST #D13, DENVER, CO 80216",
                        "4800 Dahlia Street D13, Denver, Colorado 80216-1234"),
    ("mailing_address", "2140 Harborview Pkwy Ste 300 Tacoma WA 98402",
                        "2140 Harborview Parkway, Suite 300, Tacoma, WA 98402"),
    ("mailing_address", "4800 Dahlia St Denver CO 80216", "Denver, Colorado"),
    # Policy numbers (punctuation and OCR letter-spacing)
    ("policy_number", "6E7-40-02---26", "6 E 7 - 4 0 - 0 2 - - - 2 6"),
    ("policy_number", "CSG-GL-770412-26", "csg gl 770412 26"),
    # Entity names / carriers
    ("applicant_name", "ORBIN CONTRACTING LLC", "Orbin Contracting, L.L.C."),
    ("carrier_name", "Travelers", "The Travelers Indemnity Company"),
    ("carrier_name", "Cascade Standard Insurance Co.",
                     "Cascade Standard Insurance Company"),
    # Money
    ("gl_each_occurrence", "$1,000,000", "$ 1,000,000.00"),
    ("gl_each_occurrence", "1000000", "$1M"),
    ("gl_limits", "$1,000,000 / $2,000,000",
                  "$1,000,000 Each Occurrence / $2,000,000 General Aggregate"),
    # Identity / contact
    ("fein", "91-4402873", "914402873"),
    ("producer_contact_phone", "(253) 555-0172", "253-555-0172"),
    ("producer_contact_phone", "+1 253 555 0172", "253.555.0172"),
    ("entity_type", "LLC", "Limited Liability Company"),
    ("entity_type", "Sole Proprietor", "Sole Proprietorship"),
])
def test_a_formatting_difference_never_produces_a_conflict(key, a, b):
    assert _verdict(key, a, b) == SAME, f"{a!r} and {b!r} are one value"


# ─────────────────────────────────────────────────────────────────────────────
# The other direction - normalizing is not an amnesty
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("key,a,b", [
    ("auto_hired_nonowned", "Yes", "No"),
    ("sprinkler_system", "Wet", "Dry"),
    ("effective_date", "07/15/2025", "08/15/2025"),
    ("effective_date", "15-Jul-2025", "16-Jul-2025"),
    ("mailing_address", "4800 Dahlia St Denver CO", "900 Elm St Denver CO"),
    ("policy_number", "CSG-GL-770412-26", "CSG-CA-770418-26"),
    ("carrier_name", "EMC Property & Casualty Company",
                     "Employers Mutual Casualty Company"),
    ("gl_each_occurrence", "$1,000,000", "$3,000,000"),
    ("fein", "91-4402873", "84-2210987"),
    ("entity_type", "LLC", "Inc"),
    ("num_employees", "44", "31"),
])
def test_a_real_difference_still_conflicts(key, a, b):
    assert _verdict(key, a, b) == DIFF, f"{a!r} and {b!r} genuinely differ"


# ─────────────────────────────────────────────────────────────────────────────
# The date widening, and the two formats that must STAY unparsed
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("value", [
    "15-Jul-2025", "15-Jul-25", "15/Jul/2025", "15-July-2025", "Jul-15-2025",
    "07/15/2025", "07/15/25", "2025-07-15", "July 15, 2025", "15 July 2025",
    "07-15-2025", "07.15.2025",
])
def test_every_real_date_export_format_parses(value):
    assert normalize_date(value) == "2025-07-15"


def test_day_first_numeric_stays_unparsed_and_that_is_deliberate():
    """"05/09/2026" is the 5th of September or the 9th of May and NOTHING in the
    string decides which. Parsing day-first numeric would invent a date rather
    than normalise one - the one failure mode worse than a false conflict."""
    assert normalize_date("15/07/2025") is None
    assert normalize_date("25/12/2025") is None


@pytest.mark.parametrize("value", [
    "20250715",                  # 8 digits: an account or policy number
    "CSG-GL-770412-26", "6E7-40-02---26", "BBC7263 - 26",
    "$1,000,000", "91-4402873", "11288",
])
def test_an_identifier_is_never_eaten_as_a_date(value):
    """`same_fact`'s value-shape fallback tries `normalize_date` on NON-date
    fields too, so widening the format list is only safe while identifiers stay
    unparseable. This is the guard on that."""
    assert normalize_date(value) is None


# ─────────────────────────────────────────────────────────────────────────────
# The policy term-marker fold lives behind ITS OWN door (SYS-06)
# ─────────────────────────────────────────────────────────────────────────────

def test_the_contract_fold_is_reached_through_same_policy_contract():
    """The fuzz sweep first reported `BBC7263 - 26` vs `BBC7263` as a failure.
    It is not: `compare()` is the general comparator, and the term-marker fold
    is SYS-06's `same_policy_contract` / `policy_contract_groups`, which is what
    the picker actually calls. Pinned so nobody "fixes" the wrong door."""
    assert fc.same_policy_contract("BBC7263 - 26", "BBC7263") is True
    assert fc.same_policy_contract("CSG-GL-770412-26", "CSG-CA-770418-26") is False
    assert fc.policy_contract_groups(
        ["BBC7263 - 26", "BBC7263", "6E7-40-02---26"]) == [[0, 1], [2]]
