"""Money and umbrella-period readers, after the G2 skeptic (5 Oct 2026, night).

* `sqs_service._to_float` read "$1.2-1.5M" as 1.2 (an absurd 53,333,333%
  payroll warning and an 85 cap), "$18,600 (000s)" as 18,600 and "8810:
  250,000" as 8,810. Every number is now read with what stands beside it.
* The umbrella period checks compared FULL dates and kept choosing the wrong
  "comparable term" (a renewal dec issued early, a proposed GL row, an umbrella
  renewal beside a GL still in force), and the legacy copy that caps the score
  still read "12:01 AM EST" / "Dec. 1, 2025" strictly. Alignment is now read by
  policy ANNIVERSARY in all three copies, through one helper.
"""
import pytest

import services.cross_form_validator as cfv
import services.sqs_service as sq


@pytest.mark.parametrize("text,amount", [
    ("$1.2-1.5M", 1_200_000), ("$1.2 to $1.5 million", 1_200_000), ("$12-15 million", 12_000_000),
    ("$18-19MM", 18_000_000), ("$18,600 (000s)", 18_600_000), ("18,600 (in thousands)", 18_600_000),
    ("Revenue ($000): 18,600", 18_600_000), ("18.6 Millions", 18_600_000),
    ("2 locations, 18,600,000 combined revenue", 18_600_000),
    ("Total incurred for 5 years: 45,000", 45_000), ("8810: 250,000", 250_000),
    ("$18,6O0,000", 18_600_000), ("Revenue: $18.6MM", 18_600_000), ("2025 revenue 18,600,000", 18_600_000),
    ("$1,000,000 - $2,000,000", 1_000_000), ("US$18.6MM", 18_600_000), ("$0", 0.0),
])
def test_money_is_read_as_the_amount_meant(text, amount):
    assert sq._to_float(text) == amount


@pytest.mark.parametrize("text", ["N/A", "TBD", "", None])
def test_no_amount_is_no_reading(text):
    assert sq._to_float(text) is None


def test_a_revenue_range_raises_no_payroll_warning():
    facts = {"total_revenue": "$1.2-1.5M", "wc_payroll": "$640,000", "total_payroll": "$640,000"}
    flags = {"has_workers_comp": True, "has_general_liability": True}
    cf = cfv._check_wc_payroll_reconciliation(dict(facts), dict(flags),
                                              {"ACORD_125", "ACORD_126", "ACORD_130"})
    assert not [i for i in cf if "revenue" in i["message"].lower()]
    assert not [s for s in sq.evaluate_stops(dict(facts), dict(flags))[1] if "Revenue-to-payroll" in s]


def test_the_other_engine_reads_a_subcontracting_percent_as_a_percent():
    issues = sq.cross_validate({"percent_subcontracted": "$1.5M (35%)"},
                               {"has_general_liability": True, "is_contractor": True},
                               ["ACORD_125", "ACORD_126"])
    assert [i for i in issues if "(35%)" in i["message"]]
    assert not [i for i in issues if "1500000" in i["message"]]


# ── Umbrella periods, by anniversary ─────────────────────────────────────────

def _issues(facts):
    return cfv._check_umbrella_attachment_stack(facts, {"has_umbrella": True}, {"ACORD_131"})


@pytest.mark.parametrize("facts", [
    # a GL renewal dec issued early, beside the EXPIRING umbrella dec
    {"umbrella_effective_date": "12/01/2025", "umbrella_expiration_date": "12/01/2026",
     "effective_date": "12/01/2026", "expiration_date": "12/01/2027",
     "coverage_lines": [{"line": "Commercial General Liability", "effective_date": "12/01/2026",
                         "expiration_date": "12/01/2027", "premium": "$5,000"}]},
    # an umbrella RENEWAL issued early, beside a GL still in force
    {"umbrella_effective_date": "12/01/2026", "umbrella_expiration_date": "12/01/2027",
     "effective_date": "12/01/2025", "expiration_date": "12/01/2026"},
    # printed with a time and zone, or ISO-CU wording
    {"umbrella_effective_date": "12/01/2025 12:01 AM EST", "umbrella_expiration_date": "12/01/2026 12:01 AM EST",
     "effective_date": "12/01/2026", "expiration_date": "12/01/2027"},
    {"umbrella_effective_date": "12/01/2025 12:01 A.M. Standard Time",
     "umbrella_expiration_date": "12/01/2026 12:01 A.M. Standard Time",
     "effective_date": "12/01/2026", "expiration_date": "12/01/2027"},
    # an umbrella added mid-term, co-terminous with the GL
    {"umbrella_effective_date": "03/01/2026", "umbrella_expiration_date": "12/01/2026",
     "effective_date": "12/01/2026", "expiration_date": "12/01/2027",
     "coverage_lines": [{"line": "Commercial General Liability", "effective_date": "12/01/2025",
                         "expiration_date": "12/01/2026", "premium": "$5,000"}]},
])
def test_an_aligned_umbrella_raises_nothing_in_either_engine(facts):
    assert _issues(dict(facts)) == []
    assert not [s for s in sq.evaluate_stops(dict(facts), {"has_umbrella": True})[1] if "misaligned" in s]


@pytest.mark.parametrize("umb_eff,umb_exp", [("12/09/2025", "12/09/2026"), ("11/28/2025", "11/28/2026"),
                                             ("12/16/2026", "12/16/2027")])
def test_an_umbrella_off_the_anniversary_is_reported(umb_eff, umb_exp):
    facts = {"umbrella_effective_date": umb_eff, "umbrella_expiration_date": umb_exp,
             "effective_date": "12/01/2026", "expiration_date": "12/01/2027"}
    issues = _issues(facts)
    assert issues
    # across policy years the message compares anniversaries, never 2025 beside 2026
    assert not any("2025" in i["message"] and "(12/01/2026)" in i["message"] for i in issues)


@pytest.mark.parametrize("printing", ["01/01/2026 12:01 AM EST", "2026.01.01"])
def test_a_misaligned_auto_term_is_read_whatever_its_printing(printing):
    facts = {"umbrella_effective_date": "12/01/2025", "umbrella_expiration_date": "12/01/2026",
             "auto_effective_date": printing, "auto_expiration_date": "01/01/2027",
             "effective_date": "12/01/2025", "expiration_date": "12/01/2026"}
    issues = cfv._check_umbrella_period_vs_auto_wc(
        facts, {"has_umbrella": True, "has_auto_coverage": True}, {"ACORD_127", "ACORD_131"})
    assert [i for i in issues if i["code"] == "umbrella_auto_period_misaligned"]


def test_an_unreadable_proposed_date_is_no_comparison():
    facts = {"umbrella_effective_date": "12/01/2025", "umbrella_expiration_date": "12/01/2026",
             "effective_date": "Upon binding", "expiration_date": "12 months from binding"}
    assert _issues(facts) == []
