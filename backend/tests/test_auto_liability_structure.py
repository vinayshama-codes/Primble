"""An auto policy states its liability as a combined single limit OR as split
limits. Never both, and never the same figure in both.

NOT from a client report. Found by the cross-form sweep for the defect shape the
client DID report on ACORD 125 (one fact feeding several parallel columns).

`auto_liability_limit` was mapped into ALL FOUR boxes, so a single $1,000,000
combined single limit was stamped as:

    Combined Single Limit          $1,000,000
    Bodily Injury per person       $1,000,000
    Bodily Injury per accident     $1,000,000
    Property Damage per accident   $1,000,000

which reads as $1M for every part. A real 100/300/50 policy carries $100,000 /
$300,000 / $50,000 - three different numbers. **On ACORD 25, a certificate a
third party relies on, that is a material misstatement of coverage.**
26 boxes across ACORD 25, 131, 137_CA and 137_CO.
"""
import glob
import json
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
os.environ.setdefault("OPENAI_API_KEY", "sk-offline-test")

import services.pdf_service as ps                        # noqa: E402

CSL = "Vehicle_CombinedSingleLimit_EachAccidentAmount_A"
BI_PERSON = "Vehicle_BodilyInjury_PerPersonLimitAmount_A"
BI_ACCIDENT = "Vehicle_BodilyInjury_PerAccidentLimitAmount_A"
PD_ACCIDENT = "Vehicle_PropertyDamage_PerAccidentLimitAmount_A"
SPLIT_BOXES = (BI_PERSON, BI_ACCIDENT, PD_ACCIDENT)


def test_combined_single_limit_policy_fills_only_the_csl_box():
    """The common case, and the one that was misstating coverage."""
    facts = {"auto_liability_limit": "$1,000,000"}
    assert ps._deterministic_map(CSL, facts) == "$1,000,000"
    for field in SPLIT_BOXES:
        assert ps._deterministic_map(field, facts) is None, field


def test_split_limit_policy_fills_the_three_split_boxes():
    facts = {
        "auto_liability_limit": "$300,000",
        "auto_split_limits": True,
        "auto_bi_per_person": "$100,000",
        "auto_bi_per_accident": "$300,000",
        "auto_pd_per_accident": "$50,000",
    }
    assert ps._deterministic_map(BI_PERSON, facts) == "$100,000"
    assert ps._deterministic_map(BI_ACCIDENT, facts) == "$300,000"
    assert ps._deterministic_map(PD_ACCIDENT, facts) == "$50,000"
    # A split-limit policy has no combined single limit to state.
    assert ps._deterministic_map(CSL, facts) is None


def test_split_flagged_but_figures_missing_never_falls_back_to_the_csl():
    """The failure that would reintroduce the misstatement. A combined limit is
    NOT the per-person figure, so blank is the only correct answer."""
    facts = {"auto_liability_limit": "$300,000", "auto_split_limits": True}
    for field in SPLIT_BOXES + (CSL,):
        assert ps._deterministic_map(field, facts) is None, field


@pytest.mark.parametrize("flag_value", ["true", "Yes", "1", True])
def test_the_split_flag_is_read_in_the_shapes_extraction_produces(flag_value):
    facts = {"auto_liability_limit": "$1,000,000", "auto_split_limits": flag_value,
             "auto_bi_per_person": "$100,000"}
    assert ps._deterministic_map(CSL, facts) is None
    assert ps._deterministic_map(BI_PERSON, facts) == "$100,000"


def test_a_missing_flag_is_treated_as_combined_single_limit():
    """Absent flag = the common case = the EXISTING behaviour for that box. This
    change may only remove the three duplicate stamps, never the real one."""
    facts = {"auto_liability_limit": "$1,000,000"}
    assert ps._deterministic_map(CSL, facts) == "$1,000,000"


def test_the_csl_indicator_checkbox_is_not_hijacked():
    """`Vehicle_CombinedSingleLimit_LimitIndicator_A` is a CHECKBOX fed by
    `auto_liability_structure`, not an amount box."""
    assert ps._resolve_auto_liability_limit_cell(
        "Vehicle_CombinedSingleLimit_LimitIndicator_A", {}) is ps._SCHED_SKIP


def test_unrelated_fields_are_untouched():
    for field in ("GeneralLiability_EachOccurrenceLimit_A",
                  "NamedInsured_FullName_A", "Policy_EffectiveDate_A"):
        assert ps._resolve_auto_liability_limit_cell(field, {}) is ps._SCHED_SKIP


def test_no_box_still_takes_the_combined_limit_as_a_split_figure():
    """STANDING GUARD across all 17 forms. With a CSL-only fact set, no split
    box anywhere may show the combined limit."""
    facts = {"auto_liability_limit": "$1,000,000"}
    offenders = []
    for path in glob.glob(os.path.join(os.path.dirname(__file__), "..",
                                       "forms_schemas", "*_schema.json")):
        form_id = os.path.basename(path).replace("_schema.json", "")
        with open(path, encoding="utf-8") as fh:
            for field in json.load(fh):
                if any(tok in field for tok, _f in ps._SPLIT_FIELD_FACTS):
                    if ps._deterministic_map(field, facts) == "$1,000,000":
                        offenders.append(f"{form_id}:{field}")
    assert not offenders, (
        "the combined single limit is being shown as a split figure on:\n  "
        + "\n  ".join(offenders)
    )


def test_the_split_facts_exist_and_are_currency():
    from services.fact_registry import FACT_REGISTRY, _is_currency
    for _token, fact in ps._SPLIT_FIELD_FACTS:
        assert fact in FACT_REGISTRY, fact
        assert FACT_REGISTRY[fact]["validate"] is _is_currency, fact
