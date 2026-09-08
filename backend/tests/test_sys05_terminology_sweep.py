"""SYS-05 coverage sweep - the evidence behind "will this work on a real document?".

The client's instruction for this round was explicit: *"Do NOT fix for these
specific values."* A kit built from their four strings cannot answer whether the
fix generalises, so this file is the breadth measurement instead - real
commercial-lines terminology the client's documents did NOT use, plus thirteen
mutation classes applied to each name, because a declarations page prints in
capitals, with row numbers, inline limits, dashes and trailing colons.

THE NUMBER THAT MATTERS IS NOT THE PASS RATE.

Two failure modes are not equal:

  * placing a term on the WRONG line writes a false statement onto a signed
    application, and nobody sees it happen;
  * failing to place a term produces a visible "Coverage part not recognised"
    review item, which is the honest answer and is what client 1.7 asks for.

So `test_no_phrase_is_ever_assigned_to_the_wrong_line` is the load-bearing test
in this file, and it must stay at zero. The coverage counts below are a floor to
stop silent erosion, deliberately set at the measured value rather than at 100%
- the known gaps are named in `KNOWN_UNPLACED` with the reason each is left.
"""
import pytest

from services.lob_canon import canon_line, canon_part

# The families a package might establish. Passed as context so the shared-phrase
# table is exercised at its HARDEST: with both GL and Auto present, a row both
# lines print ("Medical Payments") must refuse rather than guess.
CTX = frozenset({"auto", "general_liab", "property", "crime"})


def place(phrase, ctx=CTX):
    """What the pipeline concludes for a printed line name."""
    return canon_line(phrase) or canon_part(phrase, ctx)


# ── The vocabulary. None of it is the client's. ─────────────────────────────

AUTO_PARTS = [
    "Uninsured Motorists", "UNINSURED MOTORIST", "Underinsured Motorists",
    "UM/UIM", "UM / UIM", "Uninsured/Underinsured Motorist",
    "UNINSURED AND UNDERINSURED MOTORISTS", "Uninsured Motorists Bodily Injury",
    "Underinsured Motorist Property Damage", "Collision", "COLLISION",
    "Collision Deductible", "Collision Coverage", "Comprehensive", "COMPREHENSIVE",
    "Comprehensive Deductible", "Comprehensive (Other Than Collision)",
    "Other Than Collision", "Towing", "Towing And Labor",
    "Towing and Labor Costs", "Rental Reimbursement",
    "Rental Reimbursement Coverage", "Personal Injury Protection",
    "Auto Medical Payments", "Medical Payments - Auto", "Loss Of Use",
    "Hired Car", "Physical Damage", "Auto Physical Damage",
]
GL_PARTS = [
    "Personal And Advertising Injury", "Personal & Advertising Injury",
    "PERSONAL AND ADVERTISING INJURY", "Advertising Injury",
    "Damage To Premises Rented To You", "Damage to Premises Rented",
    "Premises Rented To You", "Fire Damage Legal Liability",
    "Fire Legal Liability", "Medical Expense", "Medical Expense Limit",
    "Products/Completed Operations Aggregate",
]
PROPERTY_PARTS = [
    "Business Income", "Business Income With Extra Expense",
    "Business Interruption", "Extra Expense", "Ordinance Or Law",
    "Ordinance or Law Coverage", "Equipment Breakdown", "Boiler And Machinery",
    "BUSINESS INCOME",
]
CRIME_PARTS = [
    "Forgery Or Alteration", "Forgery and Alteration", "Computer Fraud",
    "Funds Transfer Fraud", "Money And Securities",
    "Money and Securities - Inside", "Counterfeit Money", "Employee Theft",
]

REAL_LINES = {
    "Commercial General Liability": "general_liab", "General Liability": "general_liab",
    "CGL": "general_liab", "GL": "general_liab", "Commercial Auto": "auto",
    "Business Auto": "auto", "Automobile Liability": "auto", "BAP": "auto",
    "Commercial Vehicle": "auto", "Truckers Liability": "auto",
    "Motor Carrier": "auto", "Garage Liability": "auto",
    "Garagekeepers Legal Liability": "auto", "Commercial Property": "property",
    "Property - Special Form": "property",
    "Commercial Inland Marine": "inland_marine",
    "Contractors Equipment": "inland_marine", "Installation Floater": "inland_marine",
    "Motor Truck Cargo": "inland_marine", "Workers Compensation": "workers_comp",
    "WC": "workers_comp", "Employers Liability": "workers_comp",
    "Commercial Liability Umbrella": "umbrella", "Excess Liability": "umbrella",
    "Umbrella": "umbrella", "Crime": "crime", "Crime - Employee Dishonesty": "crime",
    "Comprehensive Dishonesty, Disappearance And Destruction": "crime",
    "Cyber Liability": "cyber", "Professional Liability": "professional",
    "Errors And Omissions": "professional",
    "Employment Practices Liability": "epli", "Pollution Liability": "pollution",
    "Directors And Officers": "directors_officers",
    "Employee Benefits Liability": "employee_benefits", "Liquor Liability": "liquor",
}

# Phrases built to be misread. The expected value is the CORRECT family, or None
# where nothing may be concluded.
ADVERSARIAL = {
    # "comprehensive" is Auto physical damage, an old name for CGL, AND the ISO
    # 3-D crime policy. `canon_line` runs first so the bare word never votes.
    "Comprehensive General Liability": "general_liab",
    "Comprehensive Crime": "crime",
    "Comprehensive Dishonesty": "crime",
    # "property damage" is a category of LOSS a liability policy pays for.
    "Property Damage Liability": "general_liab",
    "Bodily Injury And Property Damage Liability": "general_liab",
    # An excess layer is never the primary line it sits over (C23).
    "Excess GL": "umbrella", "Excess Auto": "umbrella",
    # Two-letter abbreviations must match whole tokens only, never substrings.
    "Plate Glass": None, "Roofing Shingles": None, "Showcase Coverage": None,
}

# Genuinely unplaceable. Client 1.7's other half: a fix that force-maps
# everything deletes the feature the review item exists to provide.
MUST_STAY_UNKNOWN = [
    "Kidnap And Ransom", "Kidnap & Ransom", "Political Risk Coverage",
    "Widget Protection Coverage", "Special Event Cancellation",
    "Weather Parametric Cover", "Trade Credit", "Representations And Warranties",
]

# Measured 2026-09-03 and left unplaced ON PURPOSE. Each fails SAFE - it becomes
# a visible review item, never a wrong line.
KNOWN_UNPLACED = {
    # Bare 2-4 letter abbreviations. D9 reserves these for product approval, and
    # the owner's 2026-08-28 ruling admitted exactly three (gl / wc / bap) with
    # "NOTHING BEYOND THESE THREE". `OTC` also genuinely collides
    # (over-the-counter), which is the danger that ruling was about.
    "UMBI", "UMPD", "OTC", "PIP",
    # A real crime line that `canon_line` has never placed. Pre-existing, listed
    # so it is a known gap rather than a surprise.
    "Burglary and Theft",
}


def _sweep(items, want, ctx=CTX):
    return [(p, place(p, ctx)) for p in items if place(p, ctx) != want]


# ── 1. THE LOAD-BEARING TEST ────────────────────────────────────────────────

def test_no_phrase_is_ever_assigned_to_the_wrong_line():
    """MUST STAY AT ZERO.

    Failing to place a term is a visible review item. Placing it on the WRONG
    line writes a false statement onto a signed application and nobody sees it.
    Only the second one is a defect worth the word.
    """
    expected = {}
    for items, fam in [(AUTO_PARTS, "auto"), (GL_PARTS, "general_liab"),
                       (PROPERTY_PARTS, "property"), (CRIME_PARTS, "crime")]:
        expected.update({p: fam for p in items})
    expected.update(REAL_LINES)
    expected.update(ADVERSARIAL)
    expected.update({p: None for p in MUST_STAY_UNKNOWN})

    wrong = [(p, place(p), want) for p, want in expected.items()
             if place(p) is not None and place(p) != want]
    assert wrong == [], f"assigned to the WRONG line: {wrong}"


def test_every_mutation_of_a_real_name_is_stable_and_never_wrong():
    """A declarations page prints in capitals, with row numbers, inline limits,
    dashes and trailing colons. None of that may change the answer, and none of
    it may produce a WRONG answer."""
    base = {"Uninsured Motorists": "auto", "Collision": "auto",
            "Comprehensive": "auto", "Towing": "auto",
            "Rental Reimbursement": "auto",
            "Personal and Advertising Injury": "general_liab",
            "Medical Expense": "general_liab",
            "Damage to Premises Rented to You": "general_liab",
            "Business Income": "property", "Ordinance or Law": "property",
            "Equipment Breakdown": "property", "Forgery or Alteration": "crime",
            "Computer Fraud": "crime",
            "Commercial General Liability": "general_liab",
            "Business Auto": "auto", "Commercial Property": "property",
            "Workers Compensation": "workers_comp"}
    wrong, blank = [], []
    for name, want in base.items():
        for mut in (name.upper(), name.lower(), name + " Coverage",
                    "Coverage - " + name, name + "  $1,000,000", "3. " + name,
                    name.replace(" ", "-"), name.replace(" ", "  "), name + ":",
                    name + " (Included)", name.replace(" and ", " & "),
                    "SECTION IV - " + name, "* " + name):
            got = place(mut)
            if got == want:
                continue
            (blank if got is None else wrong).append((mut, got, want))
    assert wrong == [], f"a mutation produced the WRONG line: {wrong}"
    assert blank == [], f"a mutation stopped placing a known name: {blank}"


# ── 2. Coverage floors - a guard against silent erosion ────────────────────

@pytest.mark.parametrize("label,items,want,floor", [
    ("auto parts", AUTO_PARTS, "auto", 30),
    ("GL parts", GL_PARTS, "general_liab", 12),
    ("property parts", PROPERTY_PARTS, "property", 9),
    ("crime parts", CRIME_PARTS, "crime", 8),
])
def test_coverage_floor_per_line(label, items, want, floor):
    placed = sum(1 for p in items if place(p) == want)
    assert placed >= floor, (
        f"{label}: {placed}/{len(items)} placed, floor is {floor}. "
        f"Misses: {_sweep(items, want)}")


def test_every_real_line_name_canonicalises():
    """`canon_line` is what decides GRANT and DENIAL, so a miss here is not
    cosmetic - it removes a line from the package's own evidence."""
    misses = [(p, canon_line(p), want) for p, want in REAL_LINES.items()
              if canon_line(p) != want]
    assert misses == [], f"real line names not placed: {misses}"


def test_the_adversarial_set_is_answered_exactly():
    misses = [(p, place(p), want) for p, want in ADVERSARIAL.items()
              if place(p) != want]
    assert misses == [], f"adversarial phrases misread: {misses}"


def test_unknown_terminology_still_reaches_the_producer():
    leaked = [(p, place(p)) for p in MUST_STAY_UNKNOWN if place(p) is not None]
    assert leaked == [], f"1.7 broken - force-mapped unknown terminology: {leaked}"


# ── 3. The known gaps stay known ───────────────────────────────────────────

def test_the_known_gaps_are_still_exactly_these():
    """If one starts working, delete it from KNOWN_UNPLACED so the list keeps
    meaning something. If a NEW one appears, it belongs in a decision, not in a
    silently growing exception list."""
    still_unplaced = {p for p in KNOWN_UNPLACED if place(p) is None}
    assert still_unplaced == KNOWN_UNPLACED, (
        "a known gap now resolves - update KNOWN_UNPLACED: "
        f"{KNOWN_UNPLACED - still_unplaced}")


def test_a_shared_row_refuses_when_both_parents_are_present():
    """"Medical Payments" prints on a GL dec AND an Auto dec. With both lines in
    the package and nothing structural to separate them, refusing is correct
    (Principle 4) - it is the one deliberate blank in the sweep."""
    assert place("Medical Payments", frozenset({"auto", "general_liab"})) is None
    assert place("Medical Payments", frozenset({"auto"})) == "auto"
    assert place("Medical Payments", frozenset({"general_liab"})) == "general_liab"
