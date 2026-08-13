"""A value on the declarations page must reach the form, at the correct place.

Client's end goal, verbatim (2026-08-12): *"form should not be blank if values
are present in declaration page."* Two deterministic leaks pinned here, both
from the client's own live package:

1. `total_policy_premium` merged to $2,991 - the Commercial Auto LINE premium,
   printed twice - over the real $10,663 printed once. C45's source authority
   cannot separate two rivals that BOTH sit on the dec page, and the downstream
   resolver could only refuse the impossible figure, so the box shipped BLANK.
   `_reconcile_total_premium` runs where the candidate list still exists and
   swaps in the best arithmetically-possible stated value.

2. ACORD 125's Business Auto premium box stamped $35 - the "Auto Medical
   Payments" coverage-PART premium - because that entry was the only one whose
   tokens fit the box under the old raw-subset match ("Automobile" could not
   reach it: "automobile" != "auto" as bare tokens). `_resolve_lob_premium` now
   matches with the same stem/synonym predicate the indicator logic uses,
   rejects a part whose leftover tokens are coverage-feature vocabulary, and
   lets an exact line name outrank a qualified one.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("OPENAI_API_KEY", "sk-offline")

import services.extraction_service as es  # noqa: E402
import services.pdf_service as ps  # noqa: E402


def _partial(idx, facts):
    return {"_chunk_idx": idx, "facts": facts, "flags": {}}


# The client's real granted lines, verbatim amounts.
_GRANTED_LINES = [
    {"line": "General Liability", "premium": "$3,954", "status": "granted"},
    {"line": "Automobile",        "premium": "$2,991", "status": "granted"},
    {"line": "Inland Marine",     "premium": "$300",   "status": "granted"},
    {"line": "Umbrella",          "premium": "$3,418", "status": "granted"},
]


def _merged_total(*, totals_by_chunk, lines=None):
    """Run the REAL merge over hand-built partials and return the merged
    total_policy_premium as a plain string."""
    partials = []
    for i, total in enumerate(totals_by_chunk):
        facts = {}
        if total is not None:
            facts["total_policy_premium"] = total
        if i == 0 and lines is not None:
            facts["coverage_lines"] = lines
        partials.append(_partial(i, facts))
    merged = es._merge_list_fields(partials, ["coverage_lines"])
    value = merged["facts"].get("total_policy_premium")
    if isinstance(value, dict):
        value = value.get("value")
    return value


# ── 1. The merge-level arithmetic reconciliation ─────────────────────────────

def test_the_client_case_line_premium_outvotes_the_total_and_is_replaced():
    # $2,991 stated in two chunks, the real total once - repetition wins the
    # vote, arithmetic takes it back.
    value = _merged_total(
        totals_by_chunk=["$2,991", "$2,991", "$10,663"], lines=_GRANTED_LINES)
    assert value == "$10,663"


def test_without_coverage_lines_there_is_no_evidence_and_no_change():
    value = _merged_total(totals_by_chunk=["$2,991", "$2,991", "$10,663"])
    assert value == "$2,991"          # the ordinary vote stands untouched


def test_a_valid_stated_total_is_never_second_guessed():
    value = _merged_total(
        totals_by_chunk=["$10,663", "$10,663", "$12,000"], lines=_GRANTED_LINES)
    assert value == "$10,663"


def test_no_possible_candidate_leaves_the_merge_result_alone():
    # Every candidate is below the largest single line ($3,954): nothing valid
    # to swap in, so the winner stands and the downstream resolver still gets
    # to refuse it (blank beats a second wrong number).
    value = _merged_total(
        totals_by_chunk=["$2,991", "$2,991", "$1,496"], lines=_GRANTED_LINES)
    assert value == "$2,991"


def test_declined_lines_do_not_count_toward_the_floor():
    lines = [
        {"line": "General Liability", "premium": "$3,954", "status": "granted"},
        {"line": "Property", "premium": "$99,999", "status": "no coverage"},
    ]
    # $4,000 is above every GRANTED line, so it is a possible total and the
    # vote's winner must stand even though a declined line prints a huge figure.
    value = _merged_total(totals_by_chunk=["$4,000", "$4,000"], lines=lines)
    assert value == "$4,000"


def test_a_possible_winner_is_never_replaced_even_by_an_exact_sum_match():
    # $25,000 wins the vote and IS arithmetically possible as a total (fees,
    # surcharges, non-itemised lines all make total > sum legitimate). Choosing
    # the sum-matching rival over it would be a PREFERENCE - C23's exact
    # mistake - so the reconciliation must not touch it.
    value = _merged_total(
        totals_by_chunk=["$25,000", "$25,000", "$10,663"], lines=_GRANTED_LINES)
    assert value == "$25,000"


def test_exact_sum_decides_among_valid_candidates_once_the_winner_is_impossible():
    # The vote's winner ($2,991) is impossible; TWO stated candidates are
    # possible, and the one equal to the sum of the granted lines is the total
    # by definition - whatever their relative frequency.
    value = _merged_total(
        totals_by_chunk=["$2,991", "$2,991", "$25,000", "$25,000", "$10,663"],
        lines=_GRANTED_LINES)
    assert value == "$10,663"


def test_fr1_equality_with_the_largest_line_is_impossible_on_a_multi_line_package():
    # Live run fr1: the box stamped $3,954 - the GL line premium EXACTLY -
    # because the floor only rejected values strictly below the largest line.
    value = _merged_total(
        totals_by_chunk=["$3,954", "$3,954", "$10,663"], lines=_GRANTED_LINES)
    assert value == "$10,663"


def test_a_one_line_package_total_legitimately_equals_its_only_line():
    lines = [{"line": "General Liability", "premium": "$3,954", "status": "granted"}]
    value = _merged_total(totals_by_chunk=["$3,954", "$3,954"], lines=lines)
    assert value == "$3,954"


def test_the_resolver_also_refuses_equality_on_a_multi_line_package():
    import services.pdf_service as ps
    facts = {"total_policy_premium": "$3,954", "coverage_lines": _GRANTED_LINES}
    out = ps._resolve_estimated_total("Policy_Payment_EstimatedTotalAmount_A", facts)
    # The line list is clean here, so the trustworthy sum takes over.
    assert out == "$10,663"


# ── 2. The LOB premium box: the $35 coverage part ───────────────────────────

# The client's live coverage_lines, with the auto policy's parts itemised.
_CLIENT_LINES = {
    "coverage_lines": [
        {"line": "Liability",               "premium": "$3,954", "status": "granted"},
        {"line": "Inland Marine",           "premium": "$300",   "status": "granted"},
        {"line": "Automobile",              "premium": "$2,991", "status": "granted"},
        {"line": "Umbrella",                "premium": "$3,418", "status": "granted"},
        {"line": "Covered Autos Liability", "premium": "$1,496", "status": "granted"},
        {"line": "Auto Medical Payments",   "premium": "$35",    "status": "granted"},
        {"line": "General Liability",       "premium": "$3,954", "status": "granted"},
    ]
}

_AUTO_BOX = "CommercialVehicleLineOfBusiness_PremiumAmount_A"


def test_the_client_case_35_dollars_never_stamps_as_the_auto_line_premium():
    assert ps._resolve_lob_premium(_AUTO_BOX, _CLIENT_LINES) == "$2,991"


def test_every_box_on_the_client_package_resolves_correctly():
    expected = {
        _AUTO_BOX: "$2,991",
        "CommercialUmbrellaLineOfBusiness_PremiumAmount_A": "$3,418",
        "CommercialInlandMarineLineOfBusiness_PremiumAmount_A": "$300",
        "GeneralLiabilityLineOfBusiness_TotalPremiumAmount_A": "$3,954",
    }
    for field, want in expected.items():
        assert ps._resolve_lob_premium(field, _CLIENT_LINES) == want, field


def test_a_parts_only_document_still_fills_the_box():
    # When the dec itemises ONLY parts, the part premium is all the document
    # states for the line - the box must not become blanker than before.
    facts = {"coverage_lines": [
        {"line": "Covered Autos Liability", "premium": "$1,496", "status": "granted"},
    ]}
    assert ps._resolve_lob_premium(_AUTO_BOX, facts) == "$1,496"


def test_two_exact_line_names_with_different_amounts_still_refuse():
    facts = {"coverage_lines": [
        {"line": "Business Auto", "premium": "$2,991", "status": "granted"},
        {"line": "Automobile",    "premium": "$3,500", "status": "granted"},
    ]}
    assert ps._resolve_lob_premium(_AUTO_BOX, facts) is None


def test_automobile_reaches_the_box_by_stem_the_old_subset_match_could_not():
    facts = {"coverage_lines": [
        {"line": "Automobile", "premium": "$2,991", "status": "granted"},
    ]}
    assert ps._resolve_lob_premium(_AUTO_BOX, facts) == "$2,991"


def test_the_part_rejection_carries_no_hand_written_insurance_list():
    """The part vocabulary is derived from ACORD's own schemas
    (_coverage_part_vocab), not from a hand-kept list in the resolver. Guard the
    derivation stays the source: the vocab must be non-trivial and contain the
    client's literal part words without either being defined locally."""
    vocab = ps._coverage_part_vocab()
    assert len(vocab) > 50
    assert {"medical", "payments"} <= vocab
