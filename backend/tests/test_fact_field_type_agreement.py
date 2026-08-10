"""A fact must not be stamped into a box ACORD declares as a different type.

This is the ROLE qualifier from `fix-form-stamping.md`, enforced by sweep rather
than by waiting for a client to spot it. The two instances fixed on 2026-08-09
were both found by READING a client report, not by looking:

  * `NamedInsured_BusinessStartDate` - ACORD declares "Enter date: The date the
    applicant began in business" - was mapped to `years_in_business`, whose own
    registry entry validates "positive integer <= 500". A DURATION was being
    written into a DATE box. On ACORD 125 that was the only field
    `years_in_business` reached, so the duration had nowhere correct to land.
  * `BusinessInformation_PartTimeEmployeeCount` read the overall headcount, so
    one number was stamped into both the full-time and the part-time box.

This test asks the question generically: for every field a Pass-1 rule fills,
does ACORD's own declared type agree with the fact's own declared type?
"""
import glob
import json
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
os.environ.setdefault("OPENAI_API_KEY", "sk-offline-test")

import services.pdf_service as ps                        # noqa: E402
from services.fact_registry import (                     # noqa: E402
    FACT_REGISTRY, _is_currency, _is_date, _is_email, _is_fein,
    _is_percent, _is_phone, _is_positive_int, _is_url,
)

_SCHEMA_DIR = os.path.join(os.path.dirname(__file__), "..", "forms_schemas")

_BY_VALIDATOR = {
    _is_fein: "fein", _is_email: "email", _is_phone: "phone", _is_url: "url",
    _is_currency: "currency", _is_date: "date", _is_percent: "percent",
    _is_positive_int: "int",
}

# What ACORD's declared type will accept. Deliberately generous: the point is to
# catch a DURATION in a DATE box, not to police "Statutory" in an amount box
# (C22's ~49,000-pair sweep settled that amount boxes hold prose legitimately).
_COMPATIBLE = {
    "date":       {"date"},
    "amount":     {"currency", "int"},
    "limit":      {"currency"},
    "deductible": {"currency"},
    "percentage": {"percent"},
    "rate":       {"percent", "currency"},
    "number":     {"int", "currency", "percent", "phone", "fein"},
    "year":       {"int", "date"},
}


def _fact_type(fact_key):
    """The fact's own declared type: its registry validator, or failing that the
    format hint. The hint matters - `years_in_business` uses a lambda validator,
    so a validator-only sweep would have SKIPPED the exact bug this file exists
    for (proved by test_the_sweep_bites_on_the_bug_it_was_written_for)."""
    meta = FACT_REGISTRY.get(fact_key) or {}
    named = _BY_VALIDATOR.get(meta.get("validate"))
    if named:
        return named
    hint = (meta.get("format_hint") or "").lower()
    if "date" in hint:
        return "date"
    if hint.startswith("dollar") or "amount" in hint:
        return "currency"
    if "%" in hint or "percent" in hint:
        return "percent"
    if "whole number" in hint or hint.startswith("number"):
        return "int"
    if "email" in hint:
        return "email"
    if "website" in hint:
        return "url"
    return None


def _sweep():
    """(testable_count, mismatches) across every form."""
    testable, mismatches = 0, []
    for path in sorted(glob.glob(os.path.join(_SCHEMA_DIR, "*_schema.json"))):
        form_id = os.path.basename(path).replace("_schema.json", "")
        with open(path, encoding="utf-8") as fh:
            schema = json.load(fh)
        for field, meta in schema.items():
            fact_key = ps._first_rule_fact(field)
            if not fact_key or fact_key.startswith("_"):
                continue
            declared = ps._tooltip_declared_type(meta)
            fact_type = _fact_type(fact_key)
            if not declared or not fact_type:
                continue
            testable += 1
            if fact_type not in _COMPATIBLE.get(declared, {fact_type}):
                mismatches.append(
                    f"{form_id}:{field} <- {fact_key} "
                    f"(ACORD says {declared}, fact is {fact_type})"
                )
    return testable, mismatches


def test_no_fact_is_stamped_into_an_incompatible_box():
    """STANDING GUARD across all 17 forms."""
    testable, mismatches = _sweep()
    assert not mismatches, (
        "a fact is mapped into a box ACORD declares as another type:\n  "
        + "\n  ".join(sorted(set(mismatches)))
    )


def test_the_sweep_has_teeth():
    """Guards against a vacuously-green pass - the C25 trap. If the testable
    count collapses, the sweep stopped checking anything and the assertion above
    became meaningless."""
    testable, _ = _sweep()
    assert testable >= 250, (
        f"only {testable} mappings were checkable; the sweep lost its teeth"
    )


def test_the_sweep_bites_on_the_bug_it_was_written_for():
    """Reintroduce the real defect and confirm it is caught.

    A validator-only version of `_fact_type` returned None for
    `years_in_business` (its validator is a lambda), so the sweep SKIPPED this
    field and passed. The format-hint fallback is what gives it teeth here."""
    assert _fact_type("years_in_business") == "int"
    with open(os.path.join(_SCHEMA_DIR, "ACORD_125_schema.json"), encoding="utf-8") as fh:
        meta = json.load(fh)["NamedInsured_BusinessStartDate_A"]
    assert ps._tooltip_declared_type(meta) == "date"
    assert "int" not in _COMPATIBLE["date"], (
        "a duration must never be compatible with a date box"
    )


def test_the_two_fixed_mappings_stay_fixed():
    assert ps._first_rule_fact("NamedInsured_BusinessStartDate_A") == "business_start_date"
    assert ps._first_rule_fact(
        "BusinessInformation_PartTimeEmployeeCount_A") == "num_employees_part_time"


@pytest.mark.parametrize("fact_key,expected", [
    ("business_start_date", "date"),
    ("num_employees_part_time", "int"),
    ("fein", "fein"),
    ("applicant_website", "url"),
])
def test_new_facts_declare_their_type(fact_key, expected):
    """A fact with no declared type is invisible to this sweep, so every fact
    added by this workstream must carry one."""
    assert _fact_type(fact_key) == expected
