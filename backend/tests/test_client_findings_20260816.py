# The five findings from the 2026-08-16 fresh-run audit (session 3855121c),
# each traced to its mechanism before being fixed, each pinned with the run's
# LITERAL values (replay-client-report-verbatim).
#
# Attribution established first, fix second:
#   F1  131 SQ FT OF BLDG OCC = 4800   - street number; number boxes were
#       outside the meaning gate and addresses witnessed nothing.
#   F2  131 Q2 ISO edition = "11 20"   - CA0001's (BUSINESS AUTO) edition
#       answering an UNDERLYING GENERAL LIABILITY question; no resolver owned
#       the field, so gap fill borrowed across the line boundary.
#   F3  127 FACTOR=01 / SEAT CP=5 / RADIUS=50 - fabricated rating cells; the
#       dec literally prints "RADIUS: NA".
#   F4  131 Q7 = "Y" on the composed sentence "Commercial General Liability
#       and Commercial Auto Liability underlying insurance listed on umbrella
#       schedule" - printed nowhere; admitted by the coverage fallback against
#       a punctuation-free TABLE PAGE that the splitter treats as one sentence.
#   F5  125 printed one contract two ways (6E7-40-02---26 in Q4, 6E74002 in
#       the prior grid) - `underlying_policies` rows carry the raw printing
#       and the grid stamped it without joining the canonical key.
#
# The dec-index JSON was correct for all five. Four breaks were in call 2's
# guards/resolvers; one in a deterministic consumer. All five fixes are code.

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("OPENAI_API_KEY", "sk-offline")

import services.pdf_service as ps                                 # noqa: E402


def _e(label, value, pol=None, lob=None, section=None, owner="policy"):
    return {"label": label, "value": value, "section": section,
            "owner": owner, "policy_number": pol, "line_of_business": lob}


# Verbatim shapes from dec_index_3855121c (the run under audit).
_ORBIN_ENTRIES = [
    _e("Named Insured Address", "4800 DAHLIA ST # D13 DENVER, CO 80216-3121",
       owner="applicant"),
    _e("LOCATION", "001 4800 DAHLIA ST # D13 DENVER, CO 80216-3121",
       pol="6C7-40-02---26", lob="Inland Marine", owner="applicant"),
    _e("LOC", "001 4800 DAHLIA STREET D13 DENVER CO. 80216-3121",
       pol="6E7-40-02---26", lob="Commercial Auto"),
    _e("COST NEW", "26680", pol="6E7-40-02---26", lob="Commercial Auto"),
    _e("RADIUS", "NA", pol="6E7-40-02---26", lob="Commercial Auto"),
    _e("USE", "NA", pol="6E7-40-02---26", lob="Commercial Auto"),
    _e("TERR", "111", pol="6E7-40-02---26", lob="Commercial Auto"),
    _e("Endorsement Form", "CG 00 69 12 23", lob="General Liability"),
    _e("Endorsement Form", "CG 21 47 12 07", lob="General Liability"),
    _e("FORM DATE DESCRIPTION/ADDITIONAL INFORMATION PREMIUM - CA0001",
       "11-20 BUSINESS AUTO COVERAGE FORM",
       pol="6E7-40-02---26", lob="Commercial Auto"),
    _e("Each Occurrence Limit", "$1,000,000",
       pol="BBC7263 - 26", lob="General Liability"),
    _e("Policy", "BBC7263 - 26", pol="BBC7263 - 26", lob="General Liability"),
    _e("Policy Number", "6J74002---26",
       pol="6J7-40-02---26", lob="Commercial Umbrella"),
]
_FACTS = {"dec_page_entries": _ORBIN_ENTRIES}


# ── F1: an address digit is not a quantity ───────────────────────────────────

_SQFT_FIELD = "CareCustodyAndControl_Location_OccupiedArea_A"
_SQFT_SCHEMA = {_SQFT_FIELD: {
    "tu": "Enter number: The total square footage of the premises occupied "
          "by the applicant. ", "ft": "/Tx"}}


def test_the_street_number_is_blanked_from_the_sq_ft_box():
    """THE CLIENT'S LITERAL CASE: 4800 (of 4800 Dahlia St) as SQ FT OF BLDG OCC."""
    mapped = {_SQFT_FIELD: "4800"}
    ps._enforce_numeric_meaning_gate(mapped, _SQFT_SCHEMA, dict(_FACTS),
                                     {_SQFT_FIELD})
    assert mapped[_SQFT_FIELD] is None


def test_a_genuinely_printed_area_keeps_the_same_figure():
    """The same 4800 witnessed as a REAL area is mixed evidence - it stands."""
    facts = {"dec_page_entries": _ORBIN_ENTRIES
             + [_e("TOTAL BUILDING AREA", "4800 SQ FT")]}
    mapped = {_SQFT_FIELD: "4800"}
    ps._enforce_numeric_meaning_gate(mapped, _SQFT_SCHEMA, facts, {_SQFT_FIELD})
    assert mapped[_SQFT_FIELD] == "4800"


def test_an_address_bearing_field_is_exempt():
    schema = {"Applicant_MailingAddress_PostalZipCode_A":
              {"tu": "Enter number: The zip code. ", "ft": "/Tx"}}
    mapped = {"Applicant_MailingAddress_PostalZipCode_A": "80216"}
    ps._enforce_numeric_meaning_gate(
        mapped, schema, dict(_FACTS), {"Applicant_MailingAddress_PostalZipCode_A"})
    assert mapped["Applicant_MailingAddress_PostalZipCode_A"] == "80216"


def test_cost_new_still_stamps_with_its_own_witness():
    """26680 is witnessed as COST - the address rule must not touch it."""
    schema = {"Vehicle_CostNewAmount_A":
              {"tu": "Enter amount: The cost new of the vehicle. ", "ft": "/Tx"}}
    mapped = {"Vehicle_CostNewAmount_A": "26680"}
    ps._enforce_numeric_meaning_gate(mapped, schema, dict(_FACTS),
                                     {"Vehicle_CostNewAmount_A"})
    assert mapped["Vehicle_CostNewAmount_A"] == "26680"


def test_a_fabricated_zero_count_is_blanked():
    """REVERSED from round 1, on measurement. The exemption ("a zero count is
    an ordinary answer shape") shipped and the very next run stamped 0 SWIMMING
    POOLS / 0 DIVING BOARDS on a contractor package that never mentions either
    - the client's "absence became an answer" verbatim. A gap-filled zero
    count now needs a category-matched stated zero; the untyped any-zero
    escape stays amount-only, because the package's one real $0 (the SIR)
    must not unlock every fabricated count."""
    schema = {"ApartmentBuilding_SwimmingPoolCount_A":
              {"tu": "Enter number: The number of swimming pools. ",
               "ft": "/Tx"}}
    facts = {"dec_page_entries": _ORBIN_ENTRIES
             + [_e("Self Insured Retention", "$ 0",
                   pol="6J7-40-02---26", lob="Commercial Umbrella")]}
    mapped = {"ApartmentBuilding_SwimmingPoolCount_A": "0"}
    ps._enforce_numeric_meaning_gate(
        mapped, schema, facts, {"ApartmentBuilding_SwimmingPoolCount_A"})
    assert mapped["ApartmentBuilding_SwimmingPoolCount_A"] is None


# ── F2: the underlying GL edition comes from GL evidence or nobody ───────────

_EDITION_FIELD = "UnderlyingPolicy_GeneralLiability_FormEditionDate_A"


def test_the_auto_forms_edition_never_answers_the_gl_question():
    """Orbin: the only 11-20 editions are AUTO forms; GL lists endorsements
    only. Owned blank - and the gap-fill door is closed."""
    assert ps._resolve_underlying_gl_form_edition(_EDITION_FIELD, _FACTS) is None
    assert ps._is_authoritative_blank_field(_EDITION_FIELD, _FACTS)


def test_a_real_cgl_coverage_form_edition_stamps():
    facts = {"dec_page_entries": _ORBIN_ENTRIES
             + [_e("Coverage Form", "CG 00 01 04 13 COMMERCIAL GENERAL "
                   "LIABILITY COVERAGE FORM", lob="General Liability")]}
    assert ps._resolve_underlying_gl_form_edition(_EDITION_FIELD, facts) == "04 13"


def test_gl_endorsement_editions_are_never_the_answer():
    """CG 00 69 / CG 21 47 are ENDORSEMENTS - the question asks for the
    coverage form. Their presence alone still means blank."""
    facts = {"dec_page_entries": [
        _e("Endorsement Form", "CG 00 69 12 23", lob="General Liability")]}
    assert ps._resolve_underlying_gl_form_edition(_EDITION_FIELD, facts) is None


def test_legacy_sessions_without_entries_keep_the_old_path():
    assert ps._resolve_underlying_gl_form_edition(
        _EDITION_FIELD, {}) is ps._SCHED_SKIP


# ── F3: vehicle rating cells - the auto dec's own figures or blank ───────────

def test_the_three_fabricated_rating_cells_are_owned_blanks():
    """FACTOR=01 (the SYMBOL), SEAT CP=5 (stated nowhere), RADIUS=50 (the dec
    prints NA). All three become owned blanks, gap fill excluded."""
    for f in ("Vehicle_PrimaryLiabilityRatingFactor_A",
              "Vehicle_SeatingCapacityCount_A",
              "Vehicle_RadiusOfUse_A",
              "Vehicle_NetRatingFactor_A"):
        assert ps._resolve_vehicle_rating_cell(f, _FACTS) is None, f
        assert ps._is_authoritative_blank_field(f, _FACTS), f


def test_a_numeric_radius_printed_on_the_dec_stamps():
    facts = {"dec_page_entries": [
        _e("RADIUS", "150", pol="6E7-40-02---26", lob="Commercial Auto")]}
    assert ps._resolve_vehicle_rating_cell(
        "Vehicle_RadiusOfUse_A", facts) == "150"


def test_a_schedule_row_column_wins_over_the_dec_scan():
    facts = {"dec_page_entries": _ORBIN_ENTRIES,
             "auto_vin_schedule": [{"vin": "4S4BRCGC9C3217772", "seats": "5"}]}
    assert ps._resolve_vehicle_rating_cell(
        "Vehicle_SeatingCapacityCount_A", facts) == "5"


def test_no_auto_dec_evidence_means_legacy_gap_fill():
    facts = {"dec_page_entries": [
        _e("Each Occurrence Limit", "$1,000,000", lob="General Liability")]}
    assert ps._resolve_vehicle_rating_cell(
        "Vehicle_RadiusOfUse_A", facts) is ps._SCHED_SKIP


# ── F4: coverage against a table page is not evidence ────────────────────────

# The client's literal composed sentence and a punctuation-free umbrella
# schedule page in the shape OCR actually produces (no periods anywhere).
_COMPOSED = ("Commercial General Liability and Commercial Auto Liability "
             "underlying insurance listed on umbrella schedule")
_TABLE_PAGE = (
    "C O M M E R C I A L U M B R E L L A S C H E D U L E "
    "SCHEDULE OF UNDERLYING INSURANCE TYPE OF POLICY CARRIER POLICY NUMBER "
    "POLICY PERIOD LIMITS Commercial General Liability EMC Property and "
    "Casualty Company BBC7263 07/15/25 to 07/15/26 Each Occurrence 1,000,000 "
    "General Aggregate 2,000,000 Products-Completed Operations Aggregate "
    "2,000,000 Commercial Auto Liability Employers Mutual Casualty Company "
    "6E74002 07/15/25 to 07/15/26 Combined Single Limit 1,000,000 Self "
    "Insured Retention 0 Eff Date 07/15/25 Exp Date 07/15/26 insurance "
    "listed for the policy period shown above"
)


def test_the_mechanism_this_pins_was_real():
    """Pre-fix repro: the composed sentence's tokens ARE 75%-covered by the
    table page's vocabulary. If this stops holding, the fixture rotted and the
    cap test below is vacuous."""
    q = ps._sim_tokens(_COMPOSED)
    s = ps._sim_tokens(_TABLE_PAGE)
    assert len(q & s) / len(q) >= ps._QUOTE_COVERAGE_THRESHOLD
    assert len(_TABLE_PAGE) > ps._QUOTE_SENTENCE_MAX_CHARS


def test_a_composed_sentence_cannot_ground_against_a_table_page():
    assert not ps._quote_grounds_claim(
        _COMPOSED, ps._normalize_for_search(_TABLE_PAGE), [_TABLE_PAGE])


def test_a_real_bounded_sentence_still_grounds_by_paraphrase():
    sent = ("The applicant does not own or lease any watercraft "
            "of any kind at this time")
    quote = "applicant does not own or lease any watercraft"
    assert ps._quote_grounds_claim(
        quote, "unrelated haystack text", [sent])


def test_verbatim_containment_is_untouched_by_the_cap():
    """A quote literally printed inside a huge table page still grounds - the
    cap constrains only the paraphrase fallback."""
    hay = ps._normalize_for_search(_TABLE_PAGE)
    assert ps._quote_grounds_claim(
        "Self Insured Retention 0", hay, [_TABLE_PAGE])


# ── F5: one policy, one printing, everywhere ─────────────────────────────────

def test_the_umbrella_schedules_raw_printing_joins_the_canonical_key():
    assert ps._canonical_policy_printing("6E74002", _FACTS) == "6E7-40-02---26"
    assert ps._canonical_policy_printing("BBC7263", _FACTS) == "BBC7263 - 26"


def test_an_ambiguous_stub_and_a_stranger_stay_as_printed():
    assert ps._canonical_policy_printing("6E7", _FACTS) == "6E7"        # short
    assert ps._canonical_policy_printing("WC-99-123", _FACTS) == "WC-99-123"


def test_the_prior_grid_prints_the_canonical_form():
    """End-to-end through the real grid builder on a routed renewal: the
    client's literal 6E74002 row comes out as 6E7-40-02---26."""
    facts = {
        "dec_page_entries": _ORBIN_ENTRIES,
        "is_renewal": "yes",
        "prior_effective_date": "07/15/2025",
        "prior_expiration_date": "07/15/2026",
        "underlying_policies": [
            {"line": "Commercial Auto Liability",
             "carrier": "Employers Mutual Casualty Company",
             "policy_no": "6E74002"},
            {"line": "Commercial General Liability",
             "carrier": "EMC Property & Casualty Company",
             "policy_no": "BBC7263"},
        ],
    }
    grid, _years = ps._prior_coverage_grid(facts)
    numbers = {e.get("policy_no") for e in grid.values() if isinstance(e, dict)}
    assert "6E7-40-02---26" in numbers
    assert "BBC7263 - 26" in numbers
    assert "6E74002" not in numbers


def test_the_stored_fact_keeps_its_verbatim_printing():
    """The join happens on a COPY - the underlying_policies fact is evidence
    and must keep the printing the document actually used."""
    rows = [{"line": "Commercial Auto Liability", "carrier": "X",
             "policy_no": "6E74002"}]
    facts = {"dec_page_entries": _ORBIN_ENTRIES, "is_renewal": "yes",
             "prior_effective_date": "07/15/2025",
             "prior_expiration_date": "07/15/2026",
             "underlying_policies": rows}
    ps._prior_coverage_grid(facts)
    assert rows[0]["policy_no"] == "6E74002"
