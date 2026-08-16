# The dec-index join keys are canonicalised in CODE, not by the prompt.
#
# WHY THIS FILE EXISTS. `policy_number` and `line_of_business` are what every
# downstream consumer joins on - the ACORD 131 underlying grid, the 125
# prior-carrier grid, the Q4 "other insurance" grid, the section-form header
# identity. On the client's Orbin package ONE contract carried up to three
# printings, so each of those surfaces saw a fraction of its evidence.
#
# Prompt rules 8 and 9 asked the model to do this and were MEASURED FAILING on a
# re-run of the same package (a third umbrella spelling appeared; off-vocabulary
# line names went 2 -> 7). They were deleted. These tests pin the deterministic
# replacement so nobody puts that job back in the prompt.

import copy

from services.extraction_service import _canonicalise_dec_entry_keys


def _e(pn=None, lob=None, label="L", value="V"):
    return {"label": label, "value": value, "section": None,
            "owner": "policy", "policy_number": pn, "line_of_business": lob}


# ── The live printings, verbatim from the 2026-08-16 run ─────────────────────

def test_the_three_umbrella_printings_become_one_key():
    """'6J74002---26' (5 entries) appeared beside '6J7-40-02---26' (20) on the
    run AFTER the prompt was told not to do that. Code settles it."""
    entries = [_e("6J7-40-02---26"), _e("6J74002---26"), _e("6 J 7 - 4 0 - 0 2---26")]
    _canonicalise_dec_entry_keys(entries)
    assert len({e["policy_number"] for e in entries}) == 1


def test_the_general_liability_printings_become_one_key():
    entries = [_e("BBC7263 - 26"), _e("BBC7263")]
    _canonicalise_dec_entry_keys(entries)
    assert len({e["policy_number"] for e in entries}) == 1


def test_the_auto_printings_become_one_key():
    entries = [_e("6E7-40-02---26"), _e("6E74002")]
    _canonicalise_dec_entry_keys(entries)
    assert len({e["policy_number"] for e in entries}) == 1


def test_the_ocr_spaced_inland_marine_number_joins_its_own_policy():
    """This exact key printed on the client's ACORD 125 Q4 grid."""
    entries = [_e("6C7-40-02---26"), _e("6 C 7 - 4 0 - 0 2---26")]
    _canonicalise_dec_entry_keys(entries)
    keys = {e["policy_number"] for e in entries}
    assert keys == {"6C7-40-02---26"}


# ── The line vocabulary ──────────────────────────────────────────────────────

def test_every_live_line_wording_maps_onto_the_canonical_vocabulary():
    """The seven off-vocabulary values the 2026-08-16 run produced."""
    live = ["Liability", "Automobile", "Umbrella", "Crime and Fidelity",
            "Commercial General Liability", "Commercial Auto Liability",
            "Commercial Liability Umbrella"]
    entries = [_e("P-1", lob=w) for w in live]
    _canonicalise_dec_entry_keys(entries)
    assert {e["line_of_business"] for e in entries} == {
        "General Liability", "Commercial Auto", "Commercial Umbrella", "Crime"}


def test_an_unplaceable_line_wording_is_left_exactly_as_printed():
    """Blank-over-wrong does NOT apply to an attribution the model established
    and the canonicaliser merely cannot classify - dropping it would destroy
    evidence. `_canon_line` returns None for 'Builders Risk'."""
    entries = [_e("P-1", lob="Builders Risk")]
    _canonicalise_dec_entry_keys(entries)
    assert entries[0]["line_of_business"] == "Builders Risk"


# ── The guarantees that keep this safe ───────────────────────────────────────

def test_two_genuinely_different_policies_are_never_merged():
    entries = [_e("BBC7263"), _e("6E74002"), _e("6C7-40-02---26"), _e("WC-99-123")]
    _canonicalise_dec_entry_keys(entries)
    assert len({e["policy_number"] for e in entries}) == 4


def test_label_and_value_are_never_touched():
    """`value` is EVIDENCE - `_verify_dec_entries` guarantees it is literally
    printed in the document. Rewriting it would break that guarantee."""
    entries = [_e("6E74002", lob="Automobile",
                  label="Policy Number", value="6 E 7 - 4 0 - 0 2---26")]
    before = copy.deepcopy(entries)
    _canonicalise_dec_entry_keys(entries)
    assert entries[0]["label"] == before[0]["label"]
    assert entries[0]["value"] == before[0]["value"]


def test_it_never_invents_a_printing_that_was_not_present():
    entries = [_e("BBC7263 - 26"), _e("BBC7263")]
    _canonicalise_dec_entry_keys(entries)
    assert {e["policy_number"] for e in entries} <= {"BBC7263 - 26", "BBC7263"}


def test_null_keys_and_junk_input_are_survivable():
    entries = [_e(None, None), {"label": "x"}, "not a dict", _e("", "")]
    _canonicalise_dec_entry_keys(entries)          # must not raise
    _canonicalise_dec_entry_keys([])
    _canonicalise_dec_entry_keys(None)


def test_the_prompt_no_longer_asks_the_model_to_do_this():
    """Anti-rot: rules 8 and 9 were measured making both metrics worse. If they
    come back, this job is being done twice and one of them is wrong."""
    from services import extraction_service as es
    p = es._DEC_INDEX_SYSTEM_PROMPT
    assert "ONE canonical form per policy" not in p
    assert "EXACTLY one of: General Liability" not in p


def test_rule_7_states_its_one_case_and_yields_to_rule_5():
    """THE GL CLASS TABLE REGRESSION, pinned.

    Rule 7's first wording was the GENERAL instruction "Give the value the
    caption printed above or beside it". That is a second theory of what a label
    is, and on a rating table it beat rule 5's. Rule 5: 'Payroll' labels
    '$39,300'. Rule 7 pointed one row higher at the column header 'Prem Basis',
    made 'Payroll' the value, and the amount had nowhere left to go - 6 entries
    became 1 and $39,300 / $350,000 / 91585 / 'Total Cost' left the index.

    Two conditions, both required: rule 7 must SCOPE itself to the identical-text
    case, and it must say out loud that rule 5 wins on table cells. A future
    reword that drops either one reopens the conflict.
    """
    from services import extraction_service as es
    p = es._DEC_INDEX_SYSTEM_PROMPT
    assert "SAME TEXT as its value" in p, "rule 7 lost its scope"
    assert "rule 5 wins" in p, "rule 7 no longer yields on table cells"
    # The unscoped general instruction must not return.
    assert "Give the value the caption printed above or beside it" not in p


def test_rule_5_still_carries_the_wording_that_preserves_both_cells():
    """The 2026-08-16 rewrite of rule 5 collapsed the GL class table from six
    entries to one and lost $39,300, $350,000, class 91585 and the Total Cost
    basis. The original wording is imperfect but keeps both values."""
    from services import extraction_service as es
    p = es._DEC_INDEX_SYSTEM_PROMPT
    assert "the amount's LABEL, not a separate entry" in p
    assert "never split one printed fact into two entries" not in p


# ── An identifier that keys only its own entry is not a contract key ────────

def _acct(pn="0482854"):
    return {"label": "Account Number", "value": "0482854", "section":
            "Common Declarations", "owner": "policy", "policy_number": pn,
            "line_of_business": None}


def test_the_account_number_stops_being_a_fifth_policy():
    """Run 47556cd2: the common declarations page belongs to ALL four policies,
    so the model reached for the only identifier in front of it and keyed the
    entry to itself."""
    entries = [_acct(), _e("BBC7263 - 26"), _e("6E7-40-02---26")]
    _canonicalise_dec_entry_keys(entries)
    assert entries[0]["policy_number"] is None
    assert {e["policy_number"] for e in entries[1:]} == {"BBC7263 - 26", "6E7-40-02---26"}


def test_a_policy_number_entry_keeping_its_own_key_is_untouched():
    """Same self-reference, but the label says the value IS a policy number."""
    entries = [{"label": "POLICY NUMBER", "value": "6C7-40-02---26",
                "section": "IM DECLARATIONS", "owner": "policy",
                "policy_number": "6C7-40-02---26", "line_of_business": "Inland Marine"}]
    _canonicalise_dec_entry_keys(entries)
    assert entries[0]["policy_number"] == "6C7-40-02---26"


def test_a_key_other_entries_are_filed_under_survives_even_if_self_referential():
    """Both conditions are required. A thin document where a real policy has
    one supporting entry must not lose its key."""
    entries = [_acct(), _e("0482854", label="Named Insured", value="ACME LLC")]
    _canonicalise_dec_entry_keys(entries)
    assert entries[0]["policy_number"] == "0482854"


def test_clearing_a_phantom_key_never_drops_the_entry_or_its_value():
    entries = [_acct()]
    _canonicalise_dec_entry_keys(entries)
    assert len(entries) == 1
    assert entries[0]["label"] == "Account Number"
    assert entries[0]["value"] == "0482854"


def test_rule_5_does_not_try_to_split_captionless_rating_rows():
    """ANTI-ROT, and it pins a REMOVAL rather than an addition.

    An example was added asking the model to split `COVERED AUTOS LIABILITY:
    '01 $ 1,000,000 .$ 1,496.00'` into symbol / limit / premium. Run c655a44b
    returned those rows byte-identical - zero effect - so it was removed rather
    than kept as harmless. Nothing downstream needs the split
    (`auto_covered_symbols` owns the symbols, `_resolve_lob_premium` the line
    premiums), and splitting a rating row positionally is C46's phantom-row
    pattern. The clause that MUST survive is the one that keeps
    'Exposure: $39,300' legal - that shape restored the GL class table.
    """
    from services import extraction_service as es
    p = es._DEC_INDEX_SYSTEM_PROMPT
    assert "'Payroll $39,300') is the amount's LABEL" in p
    assert "several figures with no caption between them" not in p
