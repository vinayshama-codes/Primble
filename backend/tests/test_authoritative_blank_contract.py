"""A resolver that OWNS a field and declines to fill it must leave it EMPTY -
never hand it to the gap-fill LLM.

FOUND ON A REAL RUN, 2026-08-09, after twelve workstreams had shipped. The
prior-coverage grid on a freshly generated ACORD 125 still showed one policy
number sprayed across the General Liability, Property and Other columns - the
exact defect `_resolve_prior_coverage_cell` had been written to stop, with that
resolver correctly returning None for all three.

The resolver was right. The ROUTING above it was not:

    result = _deterministic_map(field, facts)
    if result == "UNMATCHED" or _is_empty_llm_value(result):
        unmatched[field] = schema[field]      # <- "ask the model"

`None` out of `_deterministic_map` does not mean "leave blank". It means "no rule
had an answer, let GPT try the raw text". So every deliberate blank was an
invitation to guess, and gap fill refilled it from the document.

**Every unit test for those resolvers passed**, because they all called
`_deterministic_map` directly and never exercised the routing above it. That is
the lesson worth keeping: a resolver's contract is only real if the caller
honours it.

`_resolve_schedule_row` already had the right contract - "If the row is out of
range, mark as authoritative blank (do NOT send to GPT - we know the row doesn't
exist)". This file makes the three newer resolvers behave the same way.
"""
import json
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
os.environ.setdefault("OPENAI_API_KEY", "sk-offline-test")

import services.pdf_service as ps                        # noqa: E402

_SCHEMA_DIR = os.path.join(os.path.dirname(__file__), "..", "forms_schemas")
_COLUMNS = ("GeneralLiability", "Automobile", "Property", "OtherLine")

# The real-run fact set: CURRENT policy scalars only, no per-line data.
CURRENT_ONLY = {
    "prior_policy_number": "BBC7263",
    "prior_carrier": "Employers Mutual Casualty Company",
    "prior_effective_date": "07/15/2025",
    "prior_expiration_date": "07/15/2026",
    "auto_liability_limit": "$1,000,000",
}


def _would_reach_gap_fill(field, facts):
    """Mirrors the routing decision in `map_facts_to_form`."""
    result = ps._deterministic_map(field, facts)
    if not (result == "UNMATCHED" or ps._is_empty_llm_value(result)):
        return False
    return not ps._is_authoritative_blank_field(field, facts)


@pytest.mark.parametrize("column", _COLUMNS)
@pytest.mark.parametrize("attr", [
    "PolicyNumberIdentifier", "InsurerFullName", "EffectiveDate", "ExpirationDate",
])
def test_prior_coverage_cells_never_reach_gap_fill(column, attr):
    """THE REAL-RUN DEFECT. These blanks were being refilled by the model."""
    field = f"PriorCoverage_{column}_{attr}_A"
    assert not _would_reach_gap_fill(field, CURRENT_ONLY), (
        f"{field} would be handed to gap fill and refilled from raw text"
    )


@pytest.mark.parametrize("field", [
    "Vehicle_BodilyInjury_PerPersonLimitAmount_A",
    "Vehicle_BodilyInjury_PerAccidentLimitAmount_A",
    "Vehicle_PropertyDamage_PerAccidentLimitAmount_A",
])
def test_split_limit_boxes_never_reach_gap_fill_on_a_csl_policy(field):
    """A combined single limit is not the per-person figure. If the model is
    asked, it will copy the CSL straight back in."""
    assert not _would_reach_gap_fill(field, CURRENT_ONLY)


def test_certificate_line_cells_never_reach_gap_fill():
    facts = {"coverage_lines": [
        {"line": "Commercial General Liability", "policy_number": "BBC7263-26"},
        {"line": "Commercial Auto", "policy_number": "6E7-40-02---26"},
    ]}
    # Workers Comp is not on this package - its row must stay empty, not be
    # guessed from the auto policy number sitting in the same document.
    assert not _would_reach_gap_fill(
        "Policy_WorkersCompensationAndEmployersLiability_PolicyNumberIdentifier_A",
        facts,
    )


def test_a_resolver_that_produces_a_value_still_fills_it():
    """The contract must not blank a box the resolver CAN answer."""
    facts = {"coverage_lines": [
        {"line": "Commercial General Liability", "policy_number": "BBC7263-26"},
    ]}
    assert ps._deterministic_map(
        "Policy_GeneralLiability_PolicyNumberIdentifier_A", facts) == "BBC7263-26"


def test_unowned_fields_still_reach_gap_fill():
    """THE LOAD-BEARING GUARANTEE IN THE OTHER DIRECTION. This must not become a
    blanket "blank everything" rule - ordinary fields the resolvers do not own
    must still be offered to the model, or the fix costs fill everywhere."""
    for field in ("CommercialPolicy_OperationsDescription_A",
                  "NamedInsured_DBAName_A",
                  "BusinessInformation_TotalBuildingArea_A"):
        assert _would_reach_gap_fill(field, {}), (
            f"{field} is not owned by any resolver and must still reach gap fill"
        )


def test_ownership_check_is_scoped_to_the_named_resolvers():
    """A bounded surface, accounted for by resolver rather than by a magic
    number - so adding a resolver forces a decision here instead of a bump.

    Every claimed field must be claimed by exactly one named resolver, and the
    unclaimed remainder of the form must still reach the model.
    """
    with open(os.path.join(_SCHEMA_DIR, "ACORD_125_schema.json"), encoding="utf-8") as fh:
        schema = json.load(fh)
    owned = [f for f in schema if ps._is_authoritative_blank_field(f, CURRENT_ONLY)]

    claimants = {}
    for field in owned:
        who = [
            name for name in ps._AUTHORITATIVE_BLANK_RESOLVERS
            if getattr(ps, name)(field, CURRENT_ONLY) is not ps._SCHED_SKIP
        ]
        assert len(who) == 1, f"{field} claimed by {who}"
        claimants.setdefault(who[0], []).append(field)

    # ACORD 125's share: 64 prior-coverage cells, 4 unmapped "section attached"
    # boxes, 3 website rows, 1 producer printed name, and — decision made
    # 2026-08-10 — the 24 applicant-contact fields when NO applicant contact
    # fact exists: three consecutive live runs filled that block with the
    # producer's and the carrier's contacts ("Claim Reporting: (888) 362-2255",
    # contact type "Producer"/"Agent Phone"), because a dec page simply has no
    # applicant contact for the model to find. With a real contact fact the
    # family opens up again (see _resolve_applicant_contact). The certificate,
    # auto-limit, other-LOB and status resolvers own nothing under these facts.
    # +3 on 2026-08-11: the transaction-status TIME boxes (EffectiveTime and
    # its AM/PM indicators). A declarations page prints only the POLICY's
    # inception hour ("12:01 A.M. Standard Time..."), which two live runs
    # lifted into these boxes, AM tick included - a different concept from
    # when a transaction takes effect, and not knowable from any document.
    assert {k: len(v) for k, v in sorted(claimants.items())} == {
        "_resolve_prior_coverage_cell": 64,
        "_resolve_section_attached_indicator": 4,
        "_resolve_applicant_website": 3,
        "_resolve_producer_printed_name": 1,
        "_resolve_applicant_contact": 24,
        "_resolve_policy_status": 3,
        # +1 on 2026-08-12: the loss-history "Check if none" box. The 52-page
        # trap run ticked it off "Prior Term Loss Experience: NOT ON FILE" -
        # which means UNKNOWN, not "no losses" - because the deterministic
        # resolver's silence used to fall through to gap fill. Attesting a
        # clean loss history is the one box the client said must never be
        # inferred, so silence is now an owned, authoritative blank.
        "_resolve_no_loss_checkbox_owned": 1,
    }, {k: len(v) for k, v in sorted(claimants.items())}
    # 96 of 548 on ACORD 125 (17.5%): 64 are the prior-coverage grid
    # (deterministically stamped from four scalars, not withheld) and 24 are
    # the contact block above. The ceiling exists so the contract can never
    # quietly swallow a form.
    assert len(owned) < 0.20 * len(schema), (
        f"{len(owned)} of {len(schema)} fields withheld from the model"
    )


def test_every_named_resolver_exists():
    """A typo in the name list silently disables the contract for that resolver."""
    for name in ps._AUTHORITATIVE_BLANK_RESOLVERS:
        assert callable(getattr(ps, name, None)), f"{name} is not a real resolver"
