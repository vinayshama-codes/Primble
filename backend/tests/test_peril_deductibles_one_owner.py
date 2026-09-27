"""The peril-deductible rule: ONE owner, and satisfiable (2026-09-23).

WHAT WAS WRONG. `property_has_peril_deductibles` is set by extraction when the
document shows a wind/hail **or** earthquake **or** flood deductible - ONE is
enough; the prompt says so in terms. THREE separate rules then demanded that all
three amounts be present:

  * `sqs_service.evaluate_stops`                      HARD STOP  (any missing)
  * `cross_form_validator._check_peril_specific_
     deductibles_referenced`                          HARD STOP  (any missing)
  * `cross_form_validator` property-deductible block  soft warn  (0 < present < 3)

So an entirely ordinary property policy - a wind/hail deductible, no earthquake
or flood coverage bought at all - collected two hard stops and a warning, was
capped at 60, and was told to "specify amounts" for perils it does not carry.
CLAUDE.md recorded it as the live report's actual capper (80 earned, held at 60)
and as a duplication of one rule at two severities, which is the shape that let
the Umbrella SIR and auto-symbol defects survive their first fixes.

WHY THE RULE CANNOT SIMPLY BE "TIGHTENED". There is no per-peril coverage
evidence anywhere in the fact set, so "carries flood but did not state the
deductible" and "has no flood coverage" are indistinguishable. Demanding a
number that does not exist is exactly what this project's blank-over-wrong rule
exists to prevent.

WHAT SURVIVES. One rule, in `evaluate_stops`, firing only when peril deductibles
are REFERENCED and no amount was captured at all - the one version a producer
can satisfy - at WARNING severity, matching the client ruling this file's
sibling rules already record (carrier practice varies; flag, never block).
"""
import pytest

from services.sqs_service import evaluate_stops
from services.cross_form_validator import (
    run_cross_form_validation, split_cross_form_issues,
)

_PERIL_PHRASE = "Peril-specific deductibles referenced but not defined"
_FORMS = {"ACORD_125", "ACORD_140"}


def _F(v):
    return {"value": v, "confidence": "filled", "source": "ai_high"}


def _property_facts(**over):
    facts = {
        "applicant_name": _F("PANEL TEST LLC"),
        "property_building_value": _F("1200000"),
        "locations": _F([{"address": "100 Main St, Warren, MI 48089"}]),
        "occupancy_type": _F("Contractor office and shop"),
        "construction_type": _F("Joisted Masonry"),
        "year_built": _F("1998"), "roof_year": _F("2015"),
        "sprinkler_system": _F("Yes - fully sprinklered"),
        "fire_protection_class": _F("Protection Class 4"),
        "valuation_method": _F("Replacement Cost"),
        "coinsurance_percentage": _F("80"),
    }
    facts.update({k: _F(v) for k, v in over.items()})
    return facts


_FLAGS = {"has_property_coverage": True, "property_has_peril_deductibles": True}


def _all_stops(facts, flags=_FLAGS):
    hard, soft = evaluate_stops(facts, flags)
    cf = run_cross_form_validation(facts, flags, _FORMS)
    ch, cs, _adv = split_cross_form_issues(cf)
    return list(hard) + list(ch), list(soft) + list(cs)


@pytest.mark.parametrize("peril_key", [
    "property_deductible_wind",
    "property_deductible_earthquake",
    "property_deductible_flood",
])
def test_one_stated_peril_deductible_is_never_a_stop(peril_key):
    """THE CLIENT-REPORTED SHAPE. A policy that states ONE peril deductible is
    an ordinary policy, not an incomplete one - whichever peril it is."""
    hard, soft = _all_stops(_property_facts(**{peril_key: "25000"}))
    assert not any(_PERIL_PHRASE in m for m in hard), \
        f"a policy stating only {peril_key} was hard-stopped"
    # Scoped to THIS rule's own sentence. "All Other Perils deductible not
    # specified" and "deductible basis not specified" are different, legitimate
    # rules about different facts - a blanket "peril" match would claim them.
    assert not any(_PERIL_PHRASE in m for m in soft), \
        f"a policy stating only {peril_key} still draws the peril warning: {soft}"


def test_a_wind_only_policy_has_no_hard_stop_at_all():
    """The measured regression: 60-capped, and told to specify earthquake and
    flood amounts for coverage it does not buy."""
    hard, _ = _all_stops(_property_facts(property_deductible_wind="25000"))
    assert hard == [], f"an ordinary wind-only property policy is blocked: {hard}"


def test_referenced_with_no_amount_captured_is_still_flagged():
    """The one genuine, satisfiable gap: the document referenced peril
    deductibles and we captured nothing."""
    _hard, soft = _all_stops(_property_facts())
    assert any(_PERIL_PHRASE in m for m in soft), \
        "a referenced peril deductible with no amount at all must still be raised"


def test_the_genuine_gap_is_a_warning_not_a_blocker():
    """Client ruling for this family, recorded three times in sqs_service:
    carrier practice varies, so we flag and never block."""
    hard, _soft = _all_stops(_property_facts())
    assert not any(_PERIL_PHRASE in m for m in hard)


@pytest.mark.parametrize("peril_key", [
    "property_deductible_wind",
    "property_deductible_earthquake",
    "property_deductible_flood",
])
def test_any_one_amount_clears_the_rule(peril_key):
    """The rule must be SATISFIABLE by the producer. Whatever the document
    referenced, stating one real amount closes it - the whole defect was a rule
    that no answer could clear."""
    _h, soft_before = _all_stops(_property_facts())
    assert any(_PERIL_PHRASE in m for m in soft_before)
    _h2, soft_after = _all_stops(_property_facts(**{peril_key: "25000"}))
    assert not any(_PERIL_PHRASE in m for m in soft_after)


def test_the_rule_is_silent_without_the_flag():
    """No evidence, no opinion. A property policy that never mentions a peril
    deductible is not asked about one."""
    flags = {"has_property_coverage": True}
    hard, soft = _all_stops(_property_facts(), flags)
    assert not any(_PERIL_PHRASE in m for m in hard + soft)


def test_no_peril_rule_ever_demands_a_peril_the_policy_may_not_carry():
    """ANTI-ROT, and it earned its keep on the day it was written.

    The fix started from THREE known copies of this rule. This test, walking the
    AST for the real shape of the defect - a peril-deductible message emitted
    under a condition that requires MORE THAN ONE of the three amounts - found
    two more inside `calculate_sqs`'s per-form property gates, both capping the
    form at 60. Five copies, not three.

    The shape, not the wording: any emission site whose guarding condition
    collects "missing perils" across all three keys is demanding amounts for
    coverage the policy may not buy. The only defensible condition is
    `not any(...)` - referenced, and nothing captured at all.
    """
    import ast
    import pathlib

    root = pathlib.Path(__file__).resolve().parent.parent / "services"
    offenders = []
    for path in (root / "sqs_service.py", root / "cross_form_validator.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            # A list comprehension over the three peril keys that KEEPS the
            # missing ones is the defect's fingerprint - it exists only to build
            # "you are missing earthquake and flood".
            if not isinstance(node, (ast.ListComp, ast.GeneratorExp)):
                continue
            src = ast.unparse(node)
            keys = sum(1 for k in ("property_deductible_wind",
                                   "property_deductible_earthquake",
                                   "property_deductible_flood") if k in src)
            if keys == 3 and "not _fv" in src and "any(" not in src:
                offenders.append(f"{path.name}:{node.lineno}  {src[:90]}")
    assert not offenders, (
        "a peril-deductible rule is enumerating MISSING perils again - it will "
        "ask an ordinary wind-only policy for earthquake and flood amounts it "
        f"does not carry: {offenders}"
    )
