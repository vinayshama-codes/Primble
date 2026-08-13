"""A stated package total cannot be smaller than the lines it totals.

THE DEFECT (live run 2026-08-12): ACORD 125's POLICY PREMIUM box was stamped
$2,991 - the Commercial Auto LINE premium - against a real package total of
$10,663. `_merge_list_fields` ranks candidates on `log1p(freq) + confidence`, so
a line premium printed twice in a 271-page package beats the true total printed
once. The extraction prompt already forbids this ("never a single coverage
part's premium"); the model did it anyway, so the check belongs in code.

WHY THIS IS NOT C23 ALL OVER AGAIN. C23 was "the bigger figure wins", a
PREFERENCE, and it put umbrella limits in GL boxes. This is a VALIDITY
constraint: a total that is smaller than the sum of its own components, or
smaller than any single component, is arithmetically impossible. Nothing here
ever picks a larger number - it refuses an impossible one and falls back to the
sum the resolver already computed. `test_a_larger_stated_total_is_never_forced`
pins that distinction.
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("OPENAI_API_KEY", "sk-offline")

import services.pdf_service as ps  # noqa: E402

FIELD = "Policy_Payment_EstimatedTotalAmount_A"

# The client's real package, verbatim.
LINES = [
    {"line": "Commercial General Liability", "premium": "$3,954", "policy_number": "6E7400226"},
    {"line": "Business Auto",                "premium": "$2,991", "policy_number": "6E7400227"},
    {"line": "Commercial Inland Marine",     "premium": "$300",   "policy_number": "6E7400228"},
    {"line": "Commercial Umbrella",          "premium": "$3,418", "policy_number": "6E7400229"},
]
REAL_TOTAL = "$10,663"


def test_the_live_defect_a_line_premium_stated_as_the_total():
    """$2,991 is the AUTO line premium. It cannot be the package total."""
    got = ps._resolve_estimated_total(
        FIELD, {"total_policy_premium": "$2,991", "coverage_lines": LINES})
    assert got == REAL_TOTAL, (
        f"stamped {got!r}; a total smaller than its own lines must be replaced "
        f"by the computed sum")


def test_a_correct_stated_total_is_kept_verbatim():
    """A stated total is a COPY; a sum is an inference. Never override a valid
    stated figure - the dec page is the authority."""
    got = ps._resolve_estimated_total(
        FIELD, {"total_policy_premium": REAL_TOTAL, "coverage_lines": LINES})
    assert got == REAL_TOTAL


def test_a_larger_stated_total_is_never_forced():
    """The real reason a stated total beats the sum: extraction can MISS a
    line. $12,000 > sum is entirely consistent with a missed line, so it must
    survive. A rule that pushed values toward the sum would be the C23 mistake
    with the sign flipped."""
    got = ps._resolve_estimated_total(
        FIELD, {"total_policy_premium": "$12,000", "coverage_lines": LINES})
    assert got == "$12,000"


def test_no_line_evidence_means_no_second_guessing():
    """With no per-line data there is nothing to contradict the stated figure.
    Acting here would be a guess, not a check."""
    got = ps._resolve_estimated_total(FIELD, {"total_policy_premium": "$2,991"})
    assert got == "$2,991"


def test_falls_back_to_the_sum_when_no_total_is_stated():
    got = ps._resolve_estimated_total(FIELD, {"coverage_lines": LINES})
    assert got == REAL_TOTAL


def test_a_correct_total_survives_an_INFLATED_line_list():
    """THE 2026-08-12 REGRESSION, pinned.

    The first version of this guard used `max(sum, largest line)` as its floor.
    On the client's own package `coverage_lines` carried a duplicate line (page
    4 of that run prints the same policy numbers across the GL, Property AND
    Other columns), so the sum came to $12,822 against a correct stated total of
    $10,663 - and the guard replaced a value the client had explicitly listed
    among the things the pipeline got right.

    A sum is only as trustworthy as the line list. A SINGLE line premium is
    different in kind: whatever else is wrong with the list, a real total cannot
    be smaller than one real component of it.
    """
    inflated = LINES + [
        {"line": "Property", "premium": "$2,159", "policy_number": "BBC7263-P"},
    ]
    assert ps._sum_of_coverage_line_premiums({"coverage_lines": inflated})[0] == 12822
    got = ps._resolve_estimated_total(
        FIELD, {"total_policy_premium": REAL_TOTAL, "coverage_lines": inflated})
    assert got == REAL_TOTAL, (
        f"stamped {got!r} - an inflated sum must never overrule a stated total")


def test_the_floor_is_never_the_sum():
    """Stops the regression being reintroduced by a refactor."""
    import inspect
    src = inspect.getsource(ps._resolve_estimated_total)
    assert "max(_sum_amt" not in src, (
        "the sanity floor is the LARGEST SINGLE LINE, never the sum - see "
        "test_a_correct_total_survives_an_INFLATED_line_list")


def test_a_provably_wrong_total_goes_BLANK_when_no_sum_can_be_built():
    """Blank over wrong, and this is the case that proves the rule.

    $2,991 is smaller than the $3,954 GL line, so it is arithmetically not a
    package total - keeping it would stamp a known-wrong figure. But the second
    line grants coverage (it carries a limit) and has no premium, so no complete
    sum exists either. With both sources disqualified the only honest output is
    an empty box.

    Measured on the client's real session 2026-08-12: `total_policy_premium` was
    "$ 2,991.00" (the AUTO line premium) and the line list summed to $12,822
    against a true total of $10,663 - two wrong numbers and no right one.
    """
    partial = [
        {"line": "Commercial General Liability", "premium": "$3,954", "policy_number": "A1"},
        {"line": "Business Auto", "premium": "", "limit": "$1,000,000", "policy_number": "A2"},
    ]
    assert ps._sum_of_coverage_line_premiums({"coverage_lines": partial}) is None
    got = ps._resolve_estimated_total(
        FIELD, {"total_policy_premium": "$2,991", "coverage_lines": partial})
    assert got is None


def test_auto_coverage_parts_named_after_their_own_line():
    """SECOND regression on this guard, live run 2026-08-12.

    The first fix taught it that "Uninsured Motorists" is a part. It still
    tripped on parts NAMED after their own line - the client's log:

        coverage_lines: policy number '6e7400226' is attached to 2 different
        LINES OF BUSINESS (['auto medical payments', 'covered autos liability'])
        estimated_total: ... leaving the POLICY PREMIUM box empty

    Both are Business Auto parts (dec page "ITEM TWO - SCHEDULE OF COVERAGES AND
    COVERED AUTOS") correctly carrying the auto policy's number. Counting them
    as two lines blanked a computable premium. The check now canonicalises to a
    standard line of business before comparing - see _canonical_lob_for.
    """
    parts = [
        {"line": "Covered Autos Liability", "premium": "$1,842", "policy_number": "6E7-40-02---26"},
        {"line": "Auto Medical Payments", "premium": "$38", "policy_number": "6E7-40-02---26"},
    ]
    assert ps._line_list_is_trustworthy(parts)
    assert ps._canonical_lob_for("Covered Autos Liability") == \
        ps._canonical_lob_for("Auto Medical Payments")


def test_a_coverage_part_may_share_its_lines_policy_number():
    """THE false positive the trustworthiness check produced on its first run.

    UM/UIM, Comprehensive and Collision are PARTS of the auto policy and
    correctly carry its policy number. Only two real LINES OF BUSINESS sharing
    one number is corruption.
    """
    ok = [
        {"line": "Business Auto", "premium": "$2,991", "policy_number": "6E7400226"},
        {"line": "Uninsured Motorists", "premium": "$258", "policy_number": "6E7400226"},
    ]
    assert ps._line_list_is_trustworthy(ok)
    broken = [
        {"line": "Liability", "premium": "$3,954", "policy_number": "6C7400226"},
        {"line": "Automobile", "premium": "$2,991", "policy_number": "6C7400226"},
    ]
    assert not ps._line_list_is_trustworthy(broken)


def test_the_clients_real_line_list_is_rejected():
    """The literal shape from session c2a308a7: ONE policy number - the inland
    marine one, spaced out by OCR - attached to four different lines."""
    real = [
        {"line": "Liability",     "premium": "$3,954.00", "policy_number": "6 C 7 - 4 0 - 0 2---26"},
        {"line": "Inland Marine", "premium": "$300.00",   "policy_number": "6 C 7 - 4 0 - 0 2---26"},
        {"line": "Automobile",    "premium": "$2,991.00", "policy_number": "6 C 7 - 4 0 - 0 2---26"},
        {"line": "Umbrella",      "premium": "$3,418.00", "policy_number": "6 C 7 - 4 0 - 0 2---26"},
    ]
    assert not ps._line_list_is_trustworthy(real)
    assert ps._sum_of_coverage_line_premiums({"coverage_lines": real}) is None
    assert ps._resolve_estimated_total(
        FIELD, {"total_policy_premium": "$ 2,991.00", "coverage_lines": real}) is None


def test_an_entry_that_is_not_a_coverage_line_is_not_a_missing_premium():
    """An entry with neither premium nor limit grants nothing - it is not a
    line, so excluding it leaves a COMPLETE sum over the real lines, and the
    impossible stated total is still corrected."""
    lines = [
        {"line": "Commercial General Liability", "premium": "$3,954", "policy_number": "A1"},
        {"line": "Business Auto",                "premium": "",       "policy_number": "A2"},
    ]
    assert ps._sum_of_coverage_line_premiums({"coverage_lines": lines}) == (3954, 3954)
    got = ps._resolve_estimated_total(
        FIELD, {"total_policy_premium": "$2,991", "coverage_lines": lines})
    assert got == "$3,954"


def test_helper_reports_sum_and_largest():
    out = ps._sum_of_coverage_line_premiums({"coverage_lines": LINES})
    assert out == (10663, 3954)


def test_helper_refuses_a_partial_sum():
    assert ps._sum_of_coverage_line_premiums({"coverage_lines": []}) is None
    assert ps._sum_of_coverage_line_premiums({}) is None
    assert ps._sum_of_coverage_line_premiums({"coverage_lines": [
        {"line": "Business Auto", "premium": "", "policy_number": "A2"}]}) is None


@pytest.mark.parametrize("text,expected", [
    ("$10,663", 10663), ("$3,954.00", 3954), ("10663", 10663),
    ("", 0), (None, 0), ("Statutory", 0),
])
def test_currency_to_int(text, expected):
    assert ps._currency_to_int(text) == expected


def test_one_implementation_of_the_line_sum():
    """The stated-total check and the fallback sum must be the SAME code. Two
    copies of "which entries are real lines" would drift invisibly."""
    import inspect
    src = inspect.getsource(ps._resolve_estimated_total)
    assert src.count("_sum_of_coverage_line_premiums") >= 2, (
        "the resolver must delegate both its sanity floor and its fallback to "
        "the shared helper")
    assert "_lob_indicator_index()" not in src, (
        "line-selection logic has been re-inlined into the resolver")
