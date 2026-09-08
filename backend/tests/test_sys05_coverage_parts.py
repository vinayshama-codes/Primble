"""SYS-05 - a coverage PART is not an unrecognised line of business.

Client, 2026-09-01 live test (P0, "Coverage normalization"):

    "Terms such as UNINSURED AND UNDERINSURED MOTORISTS, COMPREHENSIVE,
     COLLISION, and Uninsured Motorists are being treated as unrecognized
     coverage parts. They are components of Automobile coverage and should not
     become standalone unknown lines. Map these terms into the Commercial
     Auto/Automobile coverage family before cross-document comparison. Once
     normalized, the warning should disappear unless the source documents
     genuinely conflict on the Auto coverage itself."

The root cause is NOT an Auto vocabulary gap. A declarations page prints a
SCHEDULE OF COVERAGES whose rows are the coverage PARTS of one line, and
`coverage_lines` has one bucket for two different concepts. The same hole was
measured on GL and Property parts, so the whole class is covered here - fixing
only the four words in the screenshot is the pinpoint patch the client's own
instructions forbid.

THE INVARIANT THAT MUST SURVIVE: a part is placeable, not a line. It must never
become independent evidence that a line exists or is denied - that stays
`canon_line`, which is what `denied_families`, `coverage_evidence` and
`_coverage_lines_are_self_contradictory` all read.
"""
import pytest

from services.lob_canon import (
    AUTO, GENERAL_LIAB, PROPERTY, CRIME,
    canon_line, canon_part, canon_line_or_part, coverage_families_present,
    unmapped_material_lines, denied_families, policy_number_families,
)


def _row(line, **kw):
    return dict(line=line, **kw)


# The client's own document, verbatim from the screenshot.
CLIENT_ROWS = [
    _row("BUSINESS AUTO", premium="$2,991", policy_number="6E7-40-02---26"),
    _row("COMPREHENSIVE", limit="ACV less $1,000 ded", premium="$412"),
    _row("COLLISION", limit="ACV less $1,000 ded", premium="$688"),
    _row("UNINSURED AND UNDERINSURED MOTORISTS", limit="$1,000,000"),
    _row("Uninsured Motorists", limit="$1,000,000"),
    _row("MEDICAL PAYMENTS", limit="$5,000"),
]


# ── 1. The reported case ─────────────────────────────────────────────────────

def test_the_client_reported_case_is_silent():
    """Must never fail. These are the client's literal printed values."""
    assert unmapped_material_lines(CLIENT_ROWS) == []


@pytest.mark.parametrize("phrase", [
    "UNINSURED AND UNDERINSURED MOTORISTS",
    "Uninsured Motorists",
    "COLLISION",
    "Underinsured Motorists",
    "UM/UIM",
])
def test_each_unambiguous_auto_part_places_without_any_context(phrase):
    assert canon_part(phrase) == AUTO


def test_the_ambiguous_parts_place_against_the_packages_own_auto_line():
    present = coverage_families_present(CLIENT_ROWS)
    assert AUTO in present
    assert canon_part("COMPREHENSIVE", present) == AUTO
    assert canon_part("MEDICAL PAYMENTS", present) == AUTO


# ── 2. The whole class, not just Auto (CHANGE QUALITY BAR gate 1) ────────────

@pytest.mark.parametrize("phrase,family", [
    ("Personal and Advertising Injury",   GENERAL_LIAB),
    ("Damage to Premises Rented to You",  GENERAL_LIAB),
    ("Fire Damage Legal Liability",       GENERAL_LIAB),
    ("Medical Expense",                   GENERAL_LIAB),
    ("Business Income",                   PROPERTY),
    ("Business Interruption",             PROPERTY),
    ("Extra Expense",                     PROPERTY),
    ("Ordinance or Law",                  PROPERTY),
    ("Equipment Breakdown",               PROPERTY),
    ("Boiler and Machinery",              PROPERTY),
    # Crime insuring agreements. Found by the SYS-05 live fixture, not by
    # review: it printed "Forgery Or Alteration" under a 3-D policy and the row
    # surfaced as unplaceable terminology - the reported defect, one line over.
    ("Forgery Or Alteration",             CRIME),
    ("Computer Fraud",                    CRIME),
    ("Funds Transfer Fraud",              CRIME),
    ("Money and Securities",              CRIME),
])
def test_parts_of_other_lines_place_too(phrase, family):
    """The client reported Auto; the defect class covers every line."""
    assert canon_part(phrase) == family


def test_a_building_alteration_is_not_a_crime_coverage():
    """"alteration" is deliberately absent from the crime table - only the
    paired "Forgery Or Alteration" places, via the word forgery."""
    assert canon_part("Building Alteration Costs") is None


def test_a_gl_schedule_of_coverages_raises_nothing_either():
    rows = [
        _row("Commercial General Liability", premium="$4,100"),
        _row("Personal and Advertising Injury", limit="$1,000,000"),
        _row("Damage to Premises Rented to You", limit="$100,000"),
        _row("Medical Expense", limit="$5,000"),
    ]
    assert unmapped_material_lines(rows) == []


# ── 3. The pre-existing false mapping this uncovered ─────────────────────────

@pytest.mark.parametrize("phrase", [
    "Property Damage Liability",
    "Bodily Injury and Property Damage Liability",
    "BODILY INJURY AND PROPERTY DAMAGE LIABILITY",
])
def test_property_damage_liability_is_general_liability_not_property(phrase):
    """Measured 2026-09-03: it returned PROPERTY.

    "Property damage" is a category of LOSS a LIABILITY policy pays for - the
    standard second half of every GL and Auto liability limit. Reading it as
    the Commercial Property line let a COI's GL limit row argue about a
    Property line the package does not carry.
    """
    assert canon_line(phrase) == GENERAL_LIAB


@pytest.mark.parametrize("phrase", [
    "Commercial Property",
    "Business Personal Property",
    "Property",
    "BPP - Business Personal Property",
])
def test_the_property_line_itself_is_untouched(phrase):
    """The blind phrase masks one bigram, never the family's own word."""
    assert canon_line(phrase) == PROPERTY


# ── 3b. The SAME hole existed in pdf_service's independent matcher ──────────
# Found on the SYS-05 LIVE RUN, not by review. `canon_line` was fixed while
# `_lob_tokens` / `_lob_indicator_index` - which compares a document's words to
# ACORD's own checkbox tooltips - still matched "Bodily Injury And Property
# Damage Liability" to the Commercial Property checkbox, whose token set is
# literally {"property"}. Consequence: the GL policy number appeared to span two
# lines of business, `_line_list_is_trustworthy` declared the list corrupt, and
# the package's TOTAL PREMIUM could not be computed at all.

def test_the_pdf_service_matcher_no_longer_reads_property_damage_as_property():
    from services.pdf_service import (
        _lob_indicator_index, _lob_tokens, _tokens_describe_same_line,
    )
    toks = _lob_tokens("Bodily Injury And Property Damage Liability")
    assert "property" not in toks
    idx = _lob_indicator_index()
    matched = [f for f, tss in idx.items()
               if any(_tokens_describe_same_line(toks, ts) for ts in tss)]
    assert matched == [], f"still matches a line-of-business checkbox: {matched}"


@pytest.mark.parametrize("phrase", ["Commercial Property", "Property",
                                    "Business Personal Property"])
def test_the_real_property_line_still_matches_its_checkbox(phrase):
    """The mask removes one phrase, never the family's own word."""
    from services.pdf_service import (
        _lob_indicator_index, _lob_tokens, _tokens_describe_same_line,
    )
    toks = _lob_tokens(phrase)
    idx = _lob_indicator_index()
    assert any(any(_tokens_describe_same_line(toks, ts) for ts in tss)
               for f, tss in idx.items() if "CommercialProperty" in f)


# ── 3c. A line spelled its OWN way still fills its premium box ─────────────
# SYS-05 live run, ACORD 125: the dec printed Crime under its ISO name,
# "Comprehensive Dishonesty, Disappearance And Destruction". The Crime premium
# box accepts the single ACORD token {"crime"}, so no box fit and the premium
# shipped BLANK - on a form whose CRIME checkbox was ticked and whose total
# premium included the $1,225. A ticked line with no premium, and an
# itemisation that does not add up to its own printed total.

_CRIME_BOX = "CrimeLineOfBusiness_PremiumAmount_A"


def _lob_facts(*rows):
    return {"coverage_lines": [{"line": n, "premium": p, "policy_number": k}
                               for n, p, k in rows]}


def test_a_line_named_its_own_way_still_fills_its_premium_box():
    from services.pdf_service import _resolve_lob_premium
    facts = _lob_facts(
        ("General Liability", "$7,412", "P1"),
        ("Business Auto", "$5,168", "P2"),
        ("Commercial Property", "$3,940", "P3"),
        ("Comprehensive Dishonesty, Disappearance And Destruction", "$1,225", "P4"),
    )
    assert _resolve_lob_premium(_CRIME_BOX, facts) == "$1,225"


def test_the_family_fallback_is_derived_and_refuses_a_shared_family():
    """`auto` is claimed by Business Auto, Garage and Dealers AND Truckers, so
    the family can never choose between them - the same discipline as
    `len(fits) != 1`. It is absent from the map for exactly that reason."""
    from services.pdf_service import _lob_premium_field_by_family
    m = _lob_premium_field_by_family()
    assert m.get("crime") == _CRIME_BOX
    assert "auto" not in m


def test_two_lines_of_one_family_still_leave_the_box_blank():
    """The fallback narrows which BOX a line belongs to. It never relaxes the
    rule that two candidate amounts cannot be told apart."""
    from services.pdf_service import _resolve_lob_premium
    facts = _lob_facts(
        ("Comprehensive Dishonesty, Disappearance And Destruction", "$1,225", "A"),
        ("Employee Dishonesty Bond", "$980", "B"),
    )
    assert _resolve_lob_premium(_CRIME_BOX, facts) is None


def test_the_fallback_only_fires_when_the_acord_wording_matched_NOTHING():
    """A phrase that fits two boxes by wording is still "too vague" - the
    family is asked only when no box fit at all, so it can never override a
    wording decision."""
    from services.pdf_service import _resolve_lob_premium
    facts = _lob_facts(("Liability", "$500", "A"))
    assert _resolve_lob_premium(
        "GeneralLiabilityLineOfBusiness_TotalPremiumAmount_A", facts) is None


def test_a_premium_box_still_holds_money_only():
    from services.pdf_service import _resolve_lob_premium
    facts = _lob_facts(
        ("Comprehensive Dishonesty, Disappearance And Destruction", "No Coverage", "A"))
    assert _resolve_lob_premium(_CRIME_BOX, facts) is None


def test_the_package_total_premium_survives_a_gl_dec_page():
    """The money check. Five real lines total $18,605; every coverage PART also
    prints its own premium and none of them may be added."""
    from services.pdf_service import _sum_of_coverage_line_premiums
    gl, au, pr, cr, kr = "P-GL-1", "P-BA-2", "P-CP-3", "P-CR-4", "P-KR-5"
    rows = [("General Liability", "$7,412", gl),
            ("Bodily Injury And Property Damage Liability", "$2,140", gl),
            ("Personal And Advertising Injury", "$0", gl),
            ("Medical Expense", "$188", gl),
            ("Business Auto", "$5,168", au),
            ("Collision", "$1,663", au),
            ("Medical Payments", "$213", au),
            ("Commercial Property", "$3,940", pr),
            ("Ordinance Or Law", "$402", pr),
            ("Comprehensive Dishonesty, Disappearance And Destruction", "$1,225", cr),
            ("Forgery Or Alteration", "$310", cr),
            ("Kidnap And Ransom", "$860", kr)]
    facts = {"coverage_lines": [{"line": n, "premium": p, "policy_number": k}
                                for n, p, k in rows]}
    assert _sum_of_coverage_line_premiums(facts) == (18605, 7412)


# ── 4. A part is NOT a line - the load-bearing distinction ───────────────────

@pytest.mark.parametrize("phrase", [
    "COLLISION", "Uninsured Motorists", "COMPREHENSIVE", "Business Income",
    "Personal and Advertising Injury",
])
def test_canon_line_still_refuses_a_part(phrase):
    """`canon_line` decides GRANT and DENIAL. A part must never reach it, or a
    lone "COLLISION - NO COVERAGE" row would deny the whole Auto line and a
    Collision row would flip an HNOA-only account into an owned fleet."""
    assert canon_line(phrase) is None


def test_a_denied_part_does_not_deny_the_parent_line():
    rows = [_row("COLLISION", premium="No Coverage"),
            _row("Business Auto", premium="$2,991")]
    assert AUTO not in denied_families(rows)


def test_a_part_alone_does_not_grant_the_line_to_denied_families():
    """Positive evidence for a LINE stays `canon_line`'s job, both directions."""
    assert denied_families([_row("COLLISION", premium="$688")]) == frozenset()


# ── 5. Ambiguity refuses to guess (Principle 7) ──────────────────────────────

def test_a_bare_comprehensive_with_no_auto_line_is_still_routed_to_the_producer():
    """"Comprehensive" is Auto physical damage, Comprehensive Crime, and the
    pre-1986 name for CGL. Without a parent line in the package we cannot say,
    so it keeps going to the producer."""
    rows = [_row("Crime and Fidelity", premium="$900"),
            _row("COMPREHENSIVE", premium="$100")]
    assert unmapped_material_lines(rows) == ["COMPREHENSIVE"]


@pytest.mark.parametrize("phrase,family", [
    ("Comprehensive General Liability", GENERAL_LIAB),
    ("Comprehensive Crime",             CRIME),
    ("Comprehensive Dishonesty",        CRIME),
])
def test_a_phrase_that_names_a_line_is_never_dragged_into_auto(phrase, family):
    """`canon_line` runs first, so the bare word never gets a vote."""
    assert canon_line(phrase) == family
    assert canon_part(phrase) is None
    assert canon_line_or_part(phrase, {AUTO}) == family


def test_an_ambiguous_part_never_fires_without_a_present_families_argument():
    """Callers that pass nothing get today's behaviour, never a guess."""
    assert canon_part("COMPREHENSIVE") is None
    assert canon_part("Bodily Injury") is None


@pytest.mark.parametrize("phrase", ["BODILY INJURY", "PROPERTY DAMAGE",
                                    "MEDICAL PAYMENTS"])
def test_a_row_both_present_lines_print_is_refused_not_guessed(phrase):
    """These are the standard liability limit rows on a GL dec AND an Auto dec.
    Two candidates and nothing to separate them is a genuine ambiguity, and
    Principle 4 forbids picking one."""
    assert canon_part(phrase, {AUTO}) == AUTO
    assert canon_part(phrase, {GENERAL_LIAB}) == GENERAL_LIAB
    assert canon_part(phrase, {AUTO, GENERAL_LIAB}) is None


def test_a_crime_policy_is_not_dragged_into_auto_by_the_word_comprehensive():
    """"Comprehensive Dishonesty, Disappearance and Destruction" is the ISO 3-D
    crime policy. Found by this suite while writing it - the CRIME table only
    held "employee dishonesty", so the bare phrase reached the ambiguous
    Auto table on any package carrying an auto line."""
    assert canon_line("Comprehensive Dishonesty, Disappearance and Destruction") == CRIME
    assert canon_part("Comprehensive Dishonesty", {AUTO}) is None


# ── 5b. Structural evidence settles a real ambiguity ────────────────────────

_AUTO_PN, _GL_PN = "6E7-40-02---26", "BBC7263"

_TWO_LINE_PACKAGE = [
    _row("BUSINESS AUTO", premium="$2,991", policy_number=_AUTO_PN),
    _row("COMPREHENSIVE", premium="$412", policy_number=_AUTO_PN),
    _row("COLLISION", premium="$688", policy_number=_AUTO_PN),
    _row("MEDICAL PAYMENTS", limit="$5,000", policy_number=_AUTO_PN),
    _row("BODILY INJURY", limit="$1,000,000", policy_number=_AUTO_PN),
    _row("Commercial General Liability", premium="$4,100", policy_number=_GL_PN),
    _row("MEDICAL EXPENSE", limit="$5,000", policy_number=_GL_PN),
]


def test_the_contract_a_row_was_printed_under_settles_it():
    """A MEDICAL PAYMENTS row carrying the auto policy's number is the auto
    policy's medical payments. Strongest evidence in the data, and it is the
    common shape on a real multi-line package."""
    assert unmapped_material_lines(_TWO_LINE_PACKAGE) == []


def test_without_that_evidence_the_ambiguous_rows_still_reach_the_producer():
    """Strip the policy numbers and the honest answer comes back."""
    stripped = [{k: v for k, v in r.items() if k != "policy_number"}
                for r in _TWO_LINE_PACKAGE]
    assert unmapped_material_lines(stripped) == ["MEDICAL PAYMENTS", "BODILY INJURY"]


def test_policy_evidence_cannot_place_terminology_that_is_not_a_part():
    """It NARROWS candidates the part tables already produced. A row sharing
    the auto policy number is still unknown terminology if its phrase is."""
    rows = _TWO_LINE_PACKAGE + [_row("Kidnap and Ransom", limit="$500,000",
                                     policy_number=_AUTO_PN)]
    assert unmapped_material_lines(rows) == ["Kidnap and Ransom"]


def test_a_policy_number_on_two_different_lines_is_not_trusted():
    """The corrupt pairing `_coverage_lines_are_self_contradictory` already
    rejects must not be allowed to settle an ambiguity."""
    assert policy_number_families([
        _row("Business Auto", policy_number="X1"),
        _row("General Liability", policy_number="X1"),
    ]) == {}


def test_a_part_never_defines_the_contract_it_is_then_placed_by():
    """Built from rows that NAME a line only - otherwise the reasoning is
    circular and a part could bootstrap its own family."""
    assert policy_number_families([_row("COLLISION", policy_number="X1")]) == {}


# ── 6. Genuinely unknown terminology still reaches the producer (1.7) ────────

def test_unknown_terminology_is_still_surfaced():
    """The other half of client 1.7. A fix that force-maps everything would
    delete the feature this warning exists to provide."""
    rows = [_row("Kidnap and Ransom", limit="$500,000"),
            _row("Widget Protection Coverage", premium="$1,200")]
    assert unmapped_material_lines(rows) == ["Kidnap and Ransom",
                                             "Widget Protection Coverage"]


def test_an_unrecognised_part_that_is_not_carried_stays_silent():
    """MATERIAL is unchanged - a row with no premium and no limit is a
    certificate row, not a coverage part being carried (D26)."""
    assert unmapped_material_lines([_row("Widget Protection")]) == []


# ── 7. Cross-document comparison, the half the client named ─────────────────

def test_a_dec_page_and_a_coi_describe_ONE_auto_line_not_two_sets():
    """"Map these terms into the Commercial Auto family BEFORE cross-document
    comparison." The dec prints the schedule; the COI prints the line. Same
    coverage, two levels of detail."""
    dec = ["Business Auto", "COMPREHENSIVE", "COLLISION",
           "UNINSURED AND UNDERINSURED MOTORISTS", "MEDICAL PAYMENTS"]
    coi = ["Automobile Liability"]

    def fold(values):
        present = {c for x in values if (c := canon_line(x))}
        present |= {c for x in values if (c := canon_part(x))}
        return frozenset(canon_line_or_part(x, present) or x.lower() for x in values)

    assert fold(dec) == fold(coi) == frozenset({AUTO})


def test_folding_can_only_remove_a_difference_never_create_one():
    """A line nothing can place keeps its own text, so an extra REAL policy on
    one document still shows as a difference."""
    def fold(values):
        present = coverage_families_present([{"line": v} for v in values])
        return frozenset(canon_line_or_part(x, present) or x.lower() for x in values)

    assert fold(["General Liability", "Kidnap and Ransom"]) != fold(["General Liability"])


# ── 8. Robustness ────────────────────────────────────────────────────────────

@pytest.mark.parametrize("bad", [None, "", 0, {}, "   ", [], {"line": None}])
def test_nothing_raises_on_unreadable_input(bad):
    assert canon_part(bad) is None
    assert canon_line_or_part(bad) is None
    assert coverage_families_present(bad) == frozenset()
    assert unmapped_material_lines(bad) == []


def test_present_families_tolerates_a_non_iterable():
    assert canon_part("COMPREHENSIVE", 7) is None


def test_coverage_families_present_reads_parts_as_well_as_lines():
    """A package can name a line ONLY through its parts - the client's case."""
    rows = [_row("COLLISION", premium="$688"), _row("COMPREHENSIVE", premium="$412")]
    assert coverage_families_present(rows) == frozenset({AUTO})
