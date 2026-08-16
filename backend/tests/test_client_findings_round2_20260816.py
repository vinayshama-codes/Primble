# Round 2 of the 2026-08-16 fresh-run audit (session 34efbef4), pinned with
# the run's LITERAL values. Round 1's five fixes all held on this run; these
# are the findings that surfaced once they did.
#
#   R1  127 Additional Interest block: name "Trust" (a legal-structure WORD),
#       an address, and REFERENCE/LOAN # = "BBC7263 - 26" - the package's own
#       GL policy number as a third party's loan reference.
#   R2  127 Q4 "Y" on the evidence '"autos" you lease, hire, rent or borrow' -
#       the Business Auto form's own DEFINITION text, verbatim in the doc.
#   R3  131 #28: 0 swimming pools / 0 diving boards - fabricated count zeros
#       (reversal of round 1's number-box exemption; see the reversed test in
#       test_client_findings_20260816.py).
#   R4  125 printed BBC7263 in Q4 and BBC7263 - 26 in the prior grid - the
#       one-printing join now runs on every PolicyNumber box, every pass.
#   R5  index: "CG 99 09 12 19" (an ISO form number) became a fifth policy key.
#   R6  131 Q9 blank while the index PROVES it: hired premium $185.00 and
#       non-ownership premium $137.00 - now a deterministic "Y".

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("OPENAI_API_KEY", "sk-offline")

import services.pdf_service as ps                                 # noqa: E402
from services.extraction_service import _canonicalise_dec_entry_keys  # noqa: E402


def _e(label, value, pol=None, lob=None, section=None, owner="policy"):
    return {"label": label, "value": value, "section": section,
            "owner": owner, "policy_number": pol, "line_of_business": lob}


_ENTRIES = [
    _e("Policy", "BBC7263 - 26", pol="BBC7263 - 26", lob="General Liability"),
    _e("POLICY NUMBER", "6E7-40-02---26", pol="6E7-40-02---26",
       lob="Commercial Auto"),
    _e("TOTAL PREMIUM", "$ 185.00", pol="6E7-40-02---26", lob="Commercial Auto",
       section="ITEM FOUR: SCHEDULE OF HIRED OR BORROWED COVERED AUTO "
               "COVERAGE AND PREMIUMS"),
    _e("TOTAL NON-OWNERSHIP COVERED AUTOS PREMIUM", "$ 137.00",
       pol="6E7-40-02---26", lob="Commercial Auto",
       section="ITEM FIVE: SCHEDULE FOR NON-OWNERSHIP COVERED AUTOS "
               "LIABILITY PREMIUM"),
]
_FACTS = {"dec_page_entries": _ENTRIES}


# ── R1a: a bare legal-structure word is not a name ───────────────────────────

def test_trust_alone_is_blanked_from_a_name_box():
    mapped = {"AdditionalInterest_FullName_B": "Trust"}
    dropped = ps._blank_pseudo_entity_names(mapped, {"AdditionalInterest_FullName_B"})
    assert mapped["AdditionalInterest_FullName_B"] is None
    assert dropped == ["AdditionalInterest_FullName_B"]


def test_a_real_entity_name_with_a_structure_suffix_survives():
    for name in ("Meridian Fleet Leasing, LLC", "The Hartford",
                 "First National Bank as Mortgagee"):
        mapped = {"AdditionalInterest_FullName_C": name}
        ps._blank_pseudo_entity_names(mapped, {"AdditionalInterest_FullName_C"})
        assert mapped["AdditionalInterest_FullName_C"] == name, name


def test_a_deterministic_name_is_never_touched():
    """The guard is scoped to gap fill - a Pass-1 value is not re-litigated."""
    mapped = {"AdditionalInterest_FullName_B": "Trust"}
    ps._blank_pseudo_entity_names(mapped, set())
    assert mapped["AdditionalInterest_FullName_B"] == "Trust"


def test_the_guards_run_inside_the_real_fill_path():
    """ANTI-ROT: the helpers are testable in isolation, but they only protect
    the client if map_facts_to_form actually calls them - and BEFORE the
    orphan sweep, so a de-named row's mates get handled."""
    import inspect
    src = inspect.getsource(ps.map_facts_to_form)
    for helper in ("_blank_pseudo_entity_names", "_blank_own_policy_as_reference",
                   "_join_policy_printings"):
        assert helper in src, helper


# ── R1b: our own policy number is never a loan reference ─────────────────────

def test_the_gl_policy_number_is_blanked_from_the_loan_reference_box():
    """THE CLIENT'S LITERAL CELL: AdditionalInterest_AccountNumberIdentifier_B
    = 'BBC7263 - 26'."""
    mapped = {"AdditionalInterest_AccountNumberIdentifier_B": "BBC7263 - 26"}
    ps._blank_own_policy_as_reference(
        mapped, dict(_FACTS), {"AdditionalInterest_AccountNumberIdentifier_B"})
    assert mapped["AdditionalInterest_AccountNumberIdentifier_B"] is None


def test_a_genuine_loan_number_survives():
    mapped = {"AdditionalInterest_AccountNumberIdentifier_A": "4402-8891-07"}
    ps._blank_own_policy_as_reference(
        mapped, dict(_FACTS), {"AdditionalInterest_AccountNumberIdentifier_A"})
    assert mapped["AdditionalInterest_AccountNumberIdentifier_A"] == "4402-8891-07"


def test_every_printing_of_the_contract_is_caught():
    """The check is canonical: the raw '6E74002' printing matches the elected
    6E7-40-02---26 key."""
    assert ps._is_package_policy_number("6E74002", _FACTS)
    assert ps._is_package_policy_number("BBC7263", _FACTS)
    assert not ps._is_package_policy_number("4402-8891-07", _FACTS)


# ── R2: coverage-form definition text is not evidence ────────────────────────

def test_the_iso_definition_fragment_is_recognised():
    assert ps._is_policy_wording_fragment(
        '"autos" you lease, hire, rent or borrow')


def test_real_answers_and_dec_content_are_not_wording_fragments():
    for text in (
        "Subcontractors are required to carry coverage.",
        'THE MOST "WE" PAY FOR LOSS TO ANY ONE ITEM',   # uppercase - IM schedule
        "Hired/borrowed auto coverage ($ 185.00) is provided.",
        "INSURED IS: LLC",
    ):
        assert not ps._is_policy_wording_fragment(text), text


def test_the_gate_actually_consults_the_fragment_check():
    """ANTI-ROT: `_present` is a closure and cannot be driven directly, so pin
    the wiring - the acceptance path must reject wording fragments before
    accepting presence."""
    import inspect
    src = inspect.getsource(ps.map_facts_to_form)
    assert "_is_policy_wording_fragment(text)" in src


# ── R4: one printing on every PolicyNumber box, whatever pass filled it ──────

def test_the_q4_grid_printing_joins_the_canonical_key():
    mapped = {"OtherPolicy_PolicyNumberIdentifier_A": "BBC7263"}
    ps._join_policy_printings(mapped, dict(_FACTS))
    assert mapped["OtherPolicy_PolicyNumberIdentifier_A"] == "BBC7263 - 26"


def test_junk_in_a_policy_number_box_is_not_rewritten():
    mapped = {"Policy_PolicyNumberIdentifier_A": "COMMERCIAL AUTO"}
    ps._join_policy_printings(mapped, dict(_FACTS))
    assert mapped["Policy_PolicyNumberIdentifier_A"] == "COMMERCIAL AUTO"


# ── R5: an ISO form number is not a contract key ─────────────────────────────

def test_the_form_number_key_is_cleared_and_real_keys_survive():
    entries = [
        _e("Form Number", "CG 99 09 12 19", pol="CG 99 09 12 19",
           lob="General Liability"),
        _e("Policy", "BBC7263 - 26", pol="BBC7263 - 26", lob="General Liability"),
        _e("POLICY NUMBER", "6E7-40-02---26", pol="6E7-40-02---26",
           lob="Commercial Auto"),
        _e("Prior Policy", "WC-99-123", pol="WC-99-123",
           lob="Workers Compensation"),
    ]
    _canonicalise_dec_entry_keys(entries)
    keys = {e["policy_number"] for e in entries}
    assert None in keys and "CG 99 09 12 19" not in keys
    assert {"BBC7263 - 26", "6E7-40-02---26", "WC-99-123"} <= keys
    # the entry itself survives with its value intact
    assert entries[0]["value"] == "CG 99 09 12 19"


# ── R6: hired / non-owned coverage proven by its own premiums ────────────────

def test_q9_is_a_deterministic_yes_with_both_premiums():
    q = "CommercialUmbrellaLineOfBusiness_Question_AAICode_A"
    exp = "CommercialUmbrellaLineOfBusiness_HiredAndNonOwnedCoverageProvidedExplanation_J"
    assert ps._resolve_umbrella_hired_nonowned(q, _FACTS) == "Y"
    text = ps._resolve_umbrella_hired_nonowned(exp, _FACTS)
    assert "$ 185.00" in text and "$ 137.00" in text


def test_one_premium_alone_is_not_proof():
    """The question is conjunctive - a hired premium without a non-owned one
    falls through to the ordinary compliance pass."""
    facts = {"dec_page_entries": [_ENTRIES[0], _ENTRIES[1], _ENTRIES[2]]}
    q = "CommercialUmbrellaLineOfBusiness_Question_AAICode_A"
    assert ps._resolve_umbrella_hired_nonowned(q, facts) is ps._SCHED_SKIP


def test_a_zero_premium_is_not_proof():
    facts = {"dec_page_entries": [
        _ENTRIES[0], _ENTRIES[1],
        _e("TOTAL PREMIUM", "$ 0.00", pol="6E7-40-02---26",
           lob="Commercial Auto", section="ITEM FOUR: SCHEDULE OF HIRED..."),
        _ENTRIES[3],
    ]}
    q = "CommercialUmbrellaLineOfBusiness_Question_AAICode_A"
    assert ps._resolve_umbrella_hired_nonowned(q, facts) is ps._SCHED_SKIP
