"""The auto split-limit door, after the G1 skeptic (5 Oct 2026, night).

The rebuilt door counted every amount and every slash in the printing, so an
ordinary CSL summary - "$1,000,000 CSL / $5,000 Med Pay", a garage aggregate, a
policy number, a year - read as SPLIT and fired the 60-cap hard stop, while a
split part's own label ("$300,000 Each Accident") outvoted a split structure.
Each amount is now read with the label nearest to it, and the signals rank:
a person > a strong printing > the structure label > the declarations reading
(stored, so the purge cannot move it) > a weak printing > the AI flag / parts.

Measured on the skeptic's seeded fuzz (4,000 CSL + 4,000 split policies, noisy
extractions): CSL misread as split HEAD 46.7%, first cut 11.4%, the version the
skeptic graded 16.2%, now 5.0%; split misread 11.2% / 13.6% / 13.6% / 8.1% (a
printed split: 0). What is left is evidence that contradicts itself.
"""
import pytest

import services.coverage_evidence as ce
import services.pdf_service as ps


@pytest.mark.parametrize("limit", [
    "$1,000,000 CSL / $5,000 Med Pay",
    "$1,000,000 CSL / $1,000,000 UM",
    "$1,000,000 CSL / $1,000,000 Hired & Non-Owned",
    "$1,000,000 Each Accident / $2,000,000 Aggregate",
    "CSL $1,000,000 - Policy CA 7120045",
    "$1,000,000 CSL eff. December 1, 2025",
    "$1,000,000 CSL (MCS-90 $750,000)",
    "$1,000,000 CSL - 14 vehicles - 2,450 miles radius",
    "Timberline Mutual BA-456789 $1M CSL",
    "BI & PD Combined $500,000",
    "$1,000,000 Combined BI/PD",
    "BI/PD $1,000,000",
    "$1,000,000.00 per accident",
    "COMBINED SINGLE LIMIT (Ea accident) $2,000,000",
    "1,000,000 Each Accident (CSL)",
    "| $1,000,000 | CSL |",
])
def test_a_csl_printing_with_other_amounts_is_not_split(limit):
    facts = {"auto_liability_limit": limit, "auto_liability_structure": "CSL"}
    assert not ce.auto_limits_are_split(facts, {"auto_split_limits": False})
    assert not ce.auto_limits_are_split(dict(facts, auto_liability_structure=None),
                                        {"auto_split_limits": True})


@pytest.mark.parametrize("limit", ["25/50/25", "30/60/25", "100K/300K/100K",
                                   "$250,000 per person / $500,000 per accident / $100,000 property damage",
                                   "BI 100/300 PD 100"])
def test_a_printed_split_is_split_whatever_the_label_says(limit):
    assert ce.auto_limits_are_split({"auto_liability_limit": limit,
                                     "auto_liability_structure": "CSL"}, {})


def test_a_split_part_in_the_limit_does_not_outvote_a_split_structure():
    facts = {"auto_liability_limit": "$300,000 (Per accident)", "auto_liability_structure": "split",
             "auto_bi_per_person": "$100,000", "auto_bi_per_accident": "$300,000"}
    assert ce.auto_limits_are_split(facts, {"auto_split_limits": True})
    # ...and the certificate's CSL box stays empty on it
    assert ps._resolve_auto_liability_limit_cell(
        "Vehicle_CombinedSingleLimit_EachAccidentAmount_A", dict(facts, auto_split_limits=True)) is None


@pytest.mark.parametrize("structure,split", [("not split", False), ("non-split", False),
                                             ("Split Limits", True), ("combined single limit", False)])
def test_the_structure_label_is_read_not_substring_matched(structure, split):
    assert ce.auto_limits_are_split({"auto_liability_limit": "$1,000,000",
                                     "auto_liability_structure": structure}, {}) is split


def _dec(label, value):
    return {"dec_page_entries": [{"label": label, "value": value, "line_of_business": "Business Auto"}]}


def test_the_declarations_read_a_combined_limit_label_as_csl():
    assert ce.dec_auto_liability_reading(_dec(
        "Bodily Injury and Property Damage Liability - Combined Single Limit",
        "$1,000,000 Each Accident")) == "csl"
    assert ce.dec_auto_liability_reading(_dec("COVERED AUTOS LIABILITY", "01 $1,000,000 $1,496.00")) == "csl"
    assert ce.dec_auto_liability_reading(_dec("Liability Symbol", "1 - CSL $1,000,000")) == "csl"


def test_pip_and_med_pay_cast_no_split_vote():
    assert ce.dec_auto_liability_reading(_dec("Personal Injury Protection", "$10,000 each person")) is None
    assert ce.dec_auto_liability_reading(_dec("Medical Payments", "$5,000 each person")) is None


def test_the_declarations_reading_survives_the_purge():
    # PURGE_DEC_INDEX_AFTER_GENERATION deletes dec_page_entries; the reading the
    # pipeline stored answers instead, so a save after generation reads the same.
    facts = {"auto_liability_limit": "$1,000,000", ce.DEC_LIABILITY_READING_KEY: "csl",
             "auto_bi_per_person": "$1,000,000", "auto_bi_per_accident": "$2,000,000"}
    assert ce.dec_auto_liability_reading(facts) == "csl"
    assert not ce.auto_limits_are_split(facts, {"auto_split_limits": True})


def test_a_persons_csl_answer_reaches_the_certificate():
    # The resolver used to re-decide "split" from the stray parts behind the
    # door's back and print the GL limits as auto BI (6eda3069's defect).
    facts = {"auto_liability_structure": {"value": "Combined Single Limit", "source": "producer"},
             "auto_bi_per_person": "$1,000,000", "auto_bi_per_accident": "$2,000,000",
             "auto_split_limits": True}
    assert ps._resolve_auto_liability_limit_cell("Vehicle_BodilyInjury_PerPersonLimitAmount_A", facts) is None


def test_liability_amounts_leave_out_other_coverages_premiums_and_codes():
    assert ce.liability_amounts("COVERED AUTOS LIABILITY 01 $1,000,000 $1,496.00") == [1_000_000.0]
    assert ce.liability_amounts("Timberline Mutual BA-456789 $1M CSL") == [1_000_000.0]
    assert ce.liability_amounts("$1,000,000 CSL / $5,000 Med Pay / $1,000 deductible") == [1_000_000.0]
