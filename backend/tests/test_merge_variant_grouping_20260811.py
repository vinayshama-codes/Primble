"""The large-document root cause: cross-chunk vote splitting, plus the two
boilerplate leaks it exposes on a 271-page package.

Every scalar fact is asked of EVERY chunk, so a 14-chunk document produces up
to 14 partial answers per key and `_merge_list_fields` picks a winner by
frequency. Keying candidates on the raw lowercased string made two SPELLINGS
of one value into two rivals that split their own vote - measured verbatim in
the 271-page run's merge log:

    effective_date          '07/15/25'(4)       vs '07/15/2025'(3)
    producer_contact_phone  '303-996-7800'(3)   vs '(303)996-7800'(3)
    mailing_address         '..., denver, co'(3) vs '... denver co'(3)

L1 groups variants before the vote (dates through normalize_date, everything
   else folded to alphanumerics) and folds mid-word truncations into their
   complete twin - while keeping genuinely different values competing.
L2 a policy DEFINITION or a cancellation CONDITION can no longer evidence an
   applicant answer (Q3 "chemicals" came from the pollution definition; Q5
   came from the cancellation clause).
L3 a Secondary box duplicating its Primary twin is a copy, not a contact.
"""

import pytest


# ── L1: grouping ─────────────────────────────────────────────────────────────

def _merge(pairs):
    """Run the real merge over one fact expressed by several chunks."""
    from services.extraction_service import _merge_list_fields
    partials = [
        {"_chunk_idx": i, "facts": {k: v}, "flags": {}}
        for i, (k, v) in enumerate(pairs)
    ]
    return _merge_list_fields(partials, [])["facts"]


def test_two_and_four_digit_years_are_one_value_not_two_rivals():
    from services.extraction_service import _variant_group_key
    assert _variant_group_key("07/15/25") == _variant_group_key("07/15/2025")
    # And the complete rendering represents the group.
    out = _merge([("effective_date", "07/15/25"), ("effective_date", "07/15/2025"),
                  ("effective_date", "07/15/25")])
    assert out["effective_date"] == "07/15/2025"


def test_phone_spellings_do_not_split_the_vote():
    from services.extraction_service import _variant_group_key
    assert _variant_group_key("303-996-7800") == _variant_group_key("(303)996-7800")


def test_address_comma_variants_do_not_split_the_vote():
    """This split is what surfaced a phantom 'documents disagree' conflict to
    the user on a submission containing exactly one document."""
    from services.extraction_service import _variant_group_key
    a = "4800 Dahlia St # D13, Denver, CO 80216-3121"
    b = "4800 DAHLIA ST # D13, DENVER CO 80216-3121"
    assert _variant_group_key(a) == _variant_group_key(b)


def test_currency_spacing_variants_do_not_split_the_vote():
    from services.extraction_service import _variant_group_key
    assert _variant_group_key("$1,000,000") == _variant_group_key("$ 1,000,000")
    assert _variant_group_key("$1000 ded") == _variant_group_key("1000 ded")


def test_genuinely_different_values_still_compete():
    from services.extraction_service import _variant_group_key
    for a, b in (("6E7-40-02---26", "6J7-40-02---26"),
                 ("26247", "26263"),
                 ("09/01/2025", "09/01/2026")):
        assert _variant_group_key(a) != _variant_group_key(b), (a, b)


def test_a_midword_truncation_folds_into_its_complete_twin():
    from services.extraction_service import _is_midword_truncation
    assert _is_midword_truncation("commercial general contra",
                                  "commercial general contractor")
    out = _merge([("contractor_type", "commercial general contra"),
                  ("contractor_type", "commercial general contra"),
                  ("contractor_type", "commercial general contractor")])
    assert out["contractor_type"] == "commercial general contractor"


def test_a_qualified_value_is_not_a_truncation():
    """THE SAFETY ARGUMENT: '$1,000,000' is a prefix of '$1,000,000 each
    accident', but the continuation starts at a word boundary. Folding them
    would put 'each accident' into a limit box."""
    from services.extraction_service import _is_midword_truncation
    assert not _is_midword_truncation("$1,000,000", "$1,000,000 each accident")
    assert not _is_midword_truncation("$10,000", "$10,000 (any one person)")


def test_grouping_lets_the_real_majority_win():
    """Five chunks state one date two ways; a single chunk states the PRIOR
    term's date. Before grouping the majority split 3/2 and could lose."""
    out = _merge([("effective_date", "09/01/2026"), ("effective_date", "09/01/26"),
                  ("effective_date", "09/01/2026"), ("effective_date", "09/01/26"),
                  ("effective_date", "09/01/2025")])
    assert out["effective_date"] == "09/01/2026"


# ── L2: boilerplate can't answer applicant questions ─────────────────────────

_POLLUTANT_DEF = ('"pollutants" means any solid, liquid, gaseous or thermal '
                  'irritant or contaminant, including smoke, vapor, soot, '
                  'fumes, acids, alkalis, chemicals and waste.')
_CANCEL_CLAUSE = ("We may cancel this policy by mailing written notice of "
                  "cancellation to the first Named Insured at least 30 days "
                  "before the effective date of cancellation.")


@pytest.mark.parametrize("text", [_POLLUTANT_DEF, _CANCEL_CLAUSE])
def test_policy_boilerplate_is_never_an_applicant_answer(text):
    from services.pdf_service import _is_policy_contract_language
    assert _is_policy_contract_language(
        "CommercialPolicy_UncorrectedFireCodeViolationExplanation_A", text)


def test_a_real_applicant_narrative_is_untouched():
    from services.pdf_service import _is_policy_contract_language
    real = ("The applicant stores paint thinner and solvents in a fire-rated "
            "cabinet in the shop; quantities under 50 gallons.")
    assert not _is_policy_contract_language(
        "CommercialPolicy_UncorrectedFireCodeViolationExplanation_A", real)


def test_acord101_remarks_may_still_carry_policy_text():
    from services.pdf_service import _is_policy_contract_language
    assert not _is_policy_contract_language(
        "AdditionalRemarks_RemarkText_A", _POLLUTANT_DEF)


# ── L3: secondary duplicating primary ────────────────────────────────────────

def test_a_secondary_box_repeating_its_primary_is_a_copy():
    from services.pdf_service import _duplicates_primary_sibling
    mapped = {
        "NamedInsured_Contact_PrimaryPhoneNumber_A": "(720) 555-0142",
        "NamedInsured_Contact_SecondaryPhoneNumber_A": "(720) 555-0142",
        "NamedInsured_Contact_PrimaryEmailAddress_A": "m@summitridgebuilders.com",
        "NamedInsured_Contact_SecondaryEmailAddress_A": "m@summitridgebuilders.com",
    }
    assert _duplicates_primary_sibling(
        "NamedInsured_Contact_SecondaryPhoneNumber_A",
        mapped["NamedInsured_Contact_SecondaryPhoneNumber_A"], mapped)
    assert _duplicates_primary_sibling(
        "NamedInsured_Contact_SecondaryEmailAddress_A",
        mapped["NamedInsured_Contact_SecondaryEmailAddress_A"], mapped)


def test_a_genuine_second_contact_detail_survives():
    from services.pdf_service import _duplicates_primary_sibling
    mapped = {
        "NamedInsured_Contact_PrimaryPhoneNumber_A": "(720) 555-0142",
        "NamedInsured_Contact_SecondaryPhoneNumber_A": "(720) 555-0100",
    }
    assert not _duplicates_primary_sibling(
        "NamedInsured_Contact_SecondaryPhoneNumber_A", "(720) 555-0100", mapped)


if __name__ == "__main__":
    import sys
    sys.exit(pytest.main([__file__, "-q"]))
