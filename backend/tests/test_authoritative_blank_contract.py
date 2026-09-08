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
        # 3 -> 10 on 2026-08-13: the WHOLE transaction-status family, not just
        # the three time boxes. The owner ran one declarations package through
        # TWO accounts and got ISSUE POLICY ticked on one, blank on the other.
        # A document cannot produce two answers - the question was never
        # answerable from it. Renewal still ticks when `is_renewal` says so.
        "_resolve_policy_status": 10,
        # +1 on 2026-08-12: the loss-history "Check if none" box. The 52-page
        # trap run ticked it off "Prior Term Loss Experience: NOT ON FILE" -
        # which means UNKNOWN, not "no losses" - because the deterministic
        # resolver's silence used to fall through to gap fill. Attesting a
        # clean loss history is the one box the client said must never be
        # inferred, so silence is now an owned, authoritative blank.
        "_resolve_no_loss_checkbox_owned": 1,
        # +2 on 2026-08-13 (run 9): TOTAL LOSSES and the years count. The live
        # form shipped "$0" with "Check if none" unchecked and no loss runs -
        # a clean-history attestation the client said must come from the
        # client. Same signals as the checkbox above; silence means empty.
        "_resolve_loss_history_summary": 2,
        # +1 on 2026-08-13: REMARKS / PROCESSING INSTRUCTIONS. Two consecutive
        # live runs filled it off the carrier's policy - first the IL8384A
        # terrorism disclosure, then a 36-entry "Forms Applicable" schedule
        # transcribed from the dec page. Neither is a processing instruction,
        # and neither is knowable from a bound policy: this box says what the
        # PRODUCER wants the underwriter to do with THIS submission, the same
        # category as the "section attached" boxes above. A remark we genuinely
        # hold (`acord101_remarks` / `additional_remarks_text`, from a producer
        # or an ARQ answer) still stamps - and is itself checked for being a
        # forms schedule, since that is how the fact got filled last time.
        # ACORD 101's own AdditionalRemark_* rows are explicitly exempt.
        "_resolve_remark_text": 1,
        # +2 on 2026-08-13 (second entry that day): the FAX boxes. Three
        # consecutive live runs stamped the producer's PHONE into the FAX box -
        # the walk's last remaining field hunts chunk after chunk until the
        # model returns the only phone-shaped thing the package prints. A dec
        # package that states a fax states it labelled "Fax", which extraction
        # captures as `producer_fax`; with no such fact there is no document
        # source for this box. Same reasoning and same shape as
        # `_resolve_applicant_website` above. Producer_FaxNumber_A +
        # AdditionalInterest_Primary_FaxNumber_A on this form.
        "_resolve_party_fax": 2,
        # +1 on 2026-08-13 (third entry that day): the DEPOSIT box. Run 3
        # stamped the package TOTAL as the deposit; run 5 stamped $31 - the
        # terrorism premium, the only other small money figure in the index.
        # This package states no deposit anywhere; the box stamps from a
        # deposit fact or stays blank. Same shape as the fax box above.
        "_resolve_payment_deposit": 1,
        # +1 on 2026-08-14: the PAYMENT PLAN box. Every verified run stamped
        # "AN" - a code invented from "Audit Period: Annual", the GL's AUDIT
        # term. A code abbreviates a printed word, so no verbatim gate can see
        # the invention; fact-or-blank is the only honest resolution. Same
        # shape as the deposit box above.
        "_resolve_payment_schedule": 1,
        # +3 on 2026-08-17: NO. OF MEMBERS AND MANAGERS, rows A/B/C. The
        # client's run printed a fabricated "1". "member" appears 0 times
        # across all 275 dec-index entries and no fact in the registry carries
        # it - an LLC's member count is organisational data the producer
        # supplies, so a declarations page has no reason to state it and gap
        # fill can only invent. Same shape as the deposit box above.
        "_resolve_member_manager_count": 3,
        # +3 and +5 on 2026-09-05 (SYS-09): the PRODUCER's own contact person
        # and mailing block. The client's live test printed the right agency
        # name above the APPLICANT's contact person, phone, email and street
        # address - the exact defect `_resolve_applicant_contact` (24 fields
        # above) was written for in 2026-08-10, running unguarded in the other
        # direction because that guard was written for one party only.
        # A package that states no producer contact/address gives a field-level
        # gap fill only one place to look: the applicant's own submission.
        # `_resolve_producer_mailing` already existed and was already
        # registered - it simply returned _SCHED_SKIP when the fact was absent,
        # which registers nothing. An owning resolver that steps aside on
        # absence owns the easy case and abandons the one that bites.
        "_resolve_producer_contact": 3,
        "_resolve_producer_mailing": 5,
        # +1 on 2026-09-06: the AUDIT box. Three live runs stamped a bare "A"
        # on a package that states no audit term anywhere - the same invention
        # the PAYMENT PLAN box next to it was closed for in 2026-08-14, in the
        # same row, left unowned. A code abbreviates a printed word, so no
        # verbatim or echo check can see it; `audit_period` stamps when a
        # document really prints one.
        "_resolve_audit_frequency": 1,
        # +1 on 2026-09-06: METHOD OF PAYMENT. Two runs printed a SIBLING
        # checkbox's tooltip - "Direct Bill" and "producer / agency billed" are
        # verbatim the `Policy_Payment_DirectBillIndicator` and
        # `ProducerBillIndicator` tooltips - on a package containing neither
        # phrase. `_is_tooltip_echo` compares only against a field's OWN
        # tooltip, so a sibling's is invisible to it.
        "_resolve_payment_method_description": 1,
    }, {k: len(v) for k, v in sorted(claimants.items())}
    # The other three resolvers added on 2026-09-06 claim NOTHING here, and that
    # is deliberate: `_resolve_certificate_other_coverage_row` and
    # `_resolve_certificate_holder_address` are ACORD 25 concepts, and
    # `_resolve_stated_limit_cell` owns sub-limit boxes that ACORD 125 does not
    # carry (they live on 25 / 126 / 131 / 160).
    # 113 of 548 on ACORD 125 (20.6%). The ceiling exists so the contract can
    # never quietly swallow a form, and it BIT on 2026-08-13 when the
    # transaction-status family was added - which is the point. Raised to 25%
    # deliberately, with the arithmetic stated so the next person can judge it:
    #
    #   64  prior-coverage grid   - deterministically stamped from four
    #                               scalars; a CURRENT policy has no prior
    #                               carrier data, so these are not "withheld",
    #                               they are answered
    #   24  applicant contact     - a dec page has no applicant contact
    #   10  transaction status    - what THIS submission is; the producer says
    #    4  section attached      - claims about our own package
    #    3  applicant website
    #    2  loss-history summary  - a clean-history attestation
    #    2  fax
    #  ~4   printed name, no-loss tick, remarks, deposit
    #
    # 88 of the 113 are the two grids. Excluding them the contract owns 25
    # scalar boxes on a 548-field form - under 5%. If this fires again, check
    # whether the NEW entries are grids or scalars before touching the number.
    #
    # 2026-09-05 (SYS-09), MEASURED not carried forward: 117 -> 125 of 548
    # (22.8%), +3 producer contact and +5 producer mailing. The 25% ceiling is
    # NOT touched. Note the numbers above had drifted - the prose said 113/25
    # while the code was already at 117/29 - so both are restated from a real
    # run here rather than incremented.
    assert len(owned) < 0.25 * len(schema), (
        f"{len(owned)} of {len(schema)} fields withheld from the model"
    )
    # ...and the scalar half must stay small, which is the constraint the
    # percentage was really standing in for. The two grids are identified by
    # their OWNING RESOLVER, not by a guessed name prefix - the resolver is the
    # thing that actually decides, and a prefix list would drift from it.
    _grid_owners = {"_resolve_prior_coverage_cell", "_resolve_applicant_contact"}
    _scalar = sum(len(v) for k, v in claimants.items() if k not in _grid_owners)
    # 29 -> 37 on 2026-09-05 (SYS-09), raised DELIBERATELY rather than dodged.
    # The cheap way out was available and refused: the producer contact (3) and
    # producer mailing (5) blocks could have been declared "grids" to keep the
    # count flat, but a grid in this file means a REPEATING structure (rows
    # _A.._N), and each of these is ONE party's single block split across
    # component boxes. They are scalar growth, so they are counted as scalar
    # growth and the ceiling moves in the open.
    #
    #   +3  producer contact person   - name / phone / email, one person
    #   +5  producer mailing block    - line1 / line2 / city / state / zip, one
    #                                   address
    #
    # Both are party-identity blocks that no uploaded document states when the
    # underlying fact is absent - the same bar every other entry in this ledger
    # had to clear. The prose above this assert had drifted to "25" while the
    # code stood at 29; 37 is measured, not incremented.
    #
    # Ceiling 40, deliberately tight: three short of the next block of this
    # size, so whoever adds one still has to argue it here.
    assert _scalar < 40, (
        f"{_scalar} non-grid fields withheld - the contract is growing "
        "scalars, not just repeating structures"
    )


def test_every_named_resolver_exists():
    """A typo in the name list silently disables the contract for that resolver."""
    for name in ps._AUTHORITATIVE_BLANK_RESOLVERS:
        assert callable(getattr(ps, name, None)), f"{name} is not a real resolver"
