"""Every box this workstream stopped wrongly filling must still have a way to
get filled correctly.

FOUND BY ADVERSARIAL SWEEP of my own changes, not by a client.

Stopping a wrong fill is only half a fix. `BusinessInformation_PartTimeEmployeeCount`
used to receive the overall headcount (wrong - it is the part-time count) and
`NamedInsured_BusinessStartDate` used to receive `years_in_business` (wrong - the
box is declared "Enter date"). Both were repointed at new, correct facts... which
were registered at `tier: None`, meaning the client questionnaire never asks for
them. Net effect: the box goes blank and nothing can ever fill it. **A pure fill
loss dressed up as a correctness fix.**

The client had already asked for both:
  #14 "Send these questions to the client" (employee counts)
  #15 "Obtain the actual business inception date."

Rule for anyone repointing a mapping: a fact that is the ONLY source for a box a
human is expected to supply must be tier 1 or 2 so it reaches the questionnaire.
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
os.environ.setdefault("OPENAI_API_KEY", "sk-offline-test")

import services.pdf_service as ps                        # noqa: E402
from services.fact_registry import FACT_REGISTRY         # noqa: E402


# Boxes this workstream repointed away from a wrong fact, and the fact that now
# owns them. Each must be recoverable.
REPOINTED = {
    "BusinessInformation_PartTimeEmployeeCount_A": "num_employees_part_time",
    "NamedInsured_BusinessStartDate_A": "business_start_date",
    "NamedInsured_Primary_WebsiteAddress_A": "applicant_website",
}


@pytest.mark.parametrize("field,fact", sorted(REPOINTED.items()))
def test_the_repointed_box_reads_its_new_fact(field, fact):
    assert ps._first_rule_fact(field) == fact


@pytest.mark.parametrize("field,fact", sorted(REPOINTED.items()))
def test_the_new_fact_is_reachable_through_the_questionnaire(field, fact):
    """THE POINT OF THIS FILE. Blanking a box is only correct if the value can
    still arrive some other way."""
    meta = FACT_REGISTRY[fact]
    assert meta.get("tier") in (1, 2), (
        f"{fact} is the only source for {field} but tier={meta.get('tier')!r}, "
        "so the client is never asked and the box can never be filled"
    )
    assert meta.get("question"), f"{fact} has no client-facing question"


def test_producer_facts_are_deliberately_not_asked_of_the_insured():
    """The mirror case. The AGENCY's own fax number and street address must NOT
    become questions for the insured - the agency already knows them, and asking
    is noise. These are filled from the document or left blank."""
    for fact in ("producer_contact_name", "producer_contact_phone",
                 "producer_contact_email", "producer_fax", "producer_address",
                 "carrier_website"):
        assert FACT_REGISTRY[fact].get("tier") is None, (
            f"{fact} would be asked of the insured; it is the agency's or "
            "carrier's own detail"
        )


def test_split_limit_facts_are_not_asked_by_default():
    """Only relevant when `auto_split_limits` is true, which is the minority of
    policies. Asking three limit questions on every submission would be noise;
    they are read from the declarations page instead."""
    for fact in ("auto_bi_per_person", "auto_bi_per_accident", "auto_pd_per_accident"):
        assert FACT_REGISTRY[fact].get("tier") is None


def test_every_new_fact_has_a_validator_and_a_format_hint():
    """A fact with neither is invisible to the shape checks AND to the ROLE
    sweep, so it silently escapes every guard added this session."""
    new_facts = sorted(set(REPOINTED.values()) | {
        "producer_contact_name", "producer_contact_phone", "producer_contact_email",
        "producer_fax", "producer_address", "carrier_website",
        "num_employees_full_time", "auto_bi_per_person", "auto_bi_per_accident",
        "auto_pd_per_accident",
    })
    for fact in new_facts:
        meta = FACT_REGISTRY[fact]
        assert meta.get("validate") is not None, f"{fact} has no validator"
        assert meta.get("format_hint"), f"{fact} has no format hint"
