"""Client Orbin audit 2026-09-11, items 9 and 10 - which lines and forms the
package HAS.

Every fixture here is the LIVE shape of session e7084347, replayed offline on
14 Sep. The fixture that let the first item-9 fix pass gave denied rows a
"No Coverage" premium and phantom rows no carrier at all. The real extraction
does neither: it attaches "Employers Mutual Casualty Company" to every
endorsement-menu row and to the three rows the declarations deny, with no
premium and no policy number. That is the shape these tests are written from.

  * a row that PRINTS its own denial is not a line item        -> item 9 (ACORD 130)
  * a carrier NAME alone does not prove a policy                -> item 9 (cover page)
  * only a LINE flag names a line, never a sub-flag             -> item 9 (cover / SQS)
  * a form's evidence must be facts of the form's own line      -> item 10 (137 card)
"""

import os

import pytest

from services.form_service import (
    _AUTO_LINE_PHRASES,
    _FORM_EVIDENCE_FACTS,
    _GL_LINE_PHRASES,
    _PROP_LINE_PHRASES,
    _UMB_LINE_PHRASES,
    _WC_LINE_PHRASES,
    _build_trigger_facts,
    _dec_line_present,
    match_forms_deterministic,
)
from services.lob_canon import (
    _flag_families,
    _row_identifies_policy,
    carried_lines_of_business,
)

# The policy's page-1 "Coverages and Premium" table, verbatim from the OCR text
# (271page-testdec.txt lines 28-52), in both renderings the OCR produced.
ORBIN_PAGE_1 = (
    "Coverages and Premium\n"
    "Section Coverage Premium\n"
    "1 Property No Coverage\n"
    "2 Liability $3,954.00\n"
    "3 Crime and Fidelity No Coverage\n"
    "4 Inland Marine $300.00\n"
    "5 Automobile $2,991.00\n"
    "6 Workers' Compensation No Coverage\n"
    "7 Umbrella $3,418.00\n"
    "8 Other\n"
    "Estimated Total Policy Premium $10,663.00\n"
    "[Table - page 1]\n"
    "1 | Property | No Coverage\n"
    "2 | Liability | $3,954.00\n"
    "3 | Crime and Fidelity | No Coverage\n"
    "4 | Inland Marine | $300.00\n"
    "5 | Automobile | $2,991.00\n"
    "6 | Workers' Compensation | No Coverage\n"
    "7 | Umbrella | $3,418.00\n"
    "8 | Other | \n"
)

# IL 02 28 09 07, verbatim (lines 9070-9083): the endorsement MENU.
ORBIN_ENDORSEMENT_MENU = (
    "This endorsement modifies insurance provided under the following:\n"
    "CAPITAL ASSETS PROGRAM (OUTPUT POLICY) COVERAGE PART\n"
    "COMMERCIAL AUTOMOBILE COVERAGE PART\n"
    "COMMERCIAL GENERAL LIABILITY COVERAGE PART\n"
    "COMMERCIAL INLAND MARINE COVERAGE PART\n"
    "COMMERCIAL LIABILITY UMBRELLA COVERAGE PART\n"
    "COMMERCIAL PROPERTY COVERAGE PART\n"
    "CRIME AND FIDELITY COVERAGE PART\n"
    "EMPLOYMENT-RELATED PRACTICES LIABILITY COVERAGE PART\n"
    "EQUIPMENT BREAKDOWN COVERAGE PART\n"
    "FARM COVERAGE PART\n"
    "FARM UMBRELLA LIABILITY POLICY\n"
    "LIQUOR LIABILITY COVERAGE PART\n"
    "PRODUCTS/COMPLETED OPERATIONS LIABILITY COVERAGE PART\n"
)

# `lines_of_business` exactly as the merge produced it on the live package.
ORBIN_LINES_OF_BUSINESS = [
    "Property", "Liability", "Crime and Fidelity", "Inland Marine", "Automobile",
    "Workers' Compensation", "Umbrella",
    "Employment-Related Practices Liability Coverage Part",
    "Equipment Breakdown Coverage Part", "Farm Coverage Part",
    "Liquor Liability Coverage Part", "Electronic Data Liability Coverage Part",
    "Owners and Contractors Protective Liability Coverage Part",
    "Pollution Liability Coverage Part", "Product Withdrawal Coverage Part",
    "Underground Storage Tank Policy", "Contractor Equipment",
]

_EMC = "EMPLOYERS MUTUAL CASUALTY COMPANY"
_MENU_CARRIER = "Employers Mutual Casualty Company"


def _row(line, carrier=None, premium=None, policy_number=None, naic=None, eff=None, exp=None):
    return {"line": line, "naic": naic, "carrier": carrier, "premium": premium,
            "policy_number": policy_number, "effective_date": eff, "expiration_date": exp}


# `coverage_lines` rows copied from the merged live package - every shape it
# carried: denied rows (carrier + term, no premium, no number), granted rows,
# certificate rows (NAIC + number), narrative rows (number only), menu rows
# (carrier only) and an empty row.
ORBIN_COVERAGE_LINES = [
    _row("Property", _EMC, eff="07/15/2025", exp="07/15/2026"),
    _row("Liability", "EMC Property & Casualty Company", "$3,954.00", "BBC7263 - 26",
         eff="07/15/2025", exp="07/15/2026"),
    _row("Crime and Fidelity", _EMC, eff="07/15/2025", exp="07/15/2026"),
    _row("Inland Marine", _EMC, "$300.00", "6C7-40-02---26", eff="07/15/2025", exp="07/15/2026"),
    _row("Automobile", _EMC, "$2,991.00", "6E7-40-02---26", eff="07/15/2025", exp="07/15/2026"),
    _row("Workers' Compensation", _EMC, eff="07/15/2025", exp="07/15/2026"),
    _row("Umbrella", _EMC, "$3,418.00", "6J7-40-02---26", eff="07/15/2025", exp="07/15/2026"),
    _row("Commercial General Liability", "EMC Property & Casualty Company", None,
         "BBC7263 - 26", naic="25186", eff="07/15/25", exp="07/15/26"),
    _row("Umbrella Liability", "Employers Mutual Casualty Co.", None, "6J7-40-02---26",
         naic="21415", eff="7/15/2025", exp="7/15/2026"),
    _row("Installation Floater Coverage", _EMC, None, "6C7-40-02---26"),
    _row("Commercial Property Coverage Part", _MENU_CARRIER),
    _row("Crime and Fidelity Coverage Part", _MENU_CARRIER),
    _row("Liquor Liability Coverage Part", _MENU_CARRIER),
    _row("Pollution Liability Coverage Part", _MENU_CARRIER),
    _row("Employment-Related Practices Liability Coverage Part", _MENU_CARRIER),
    _row("Equipment Breakdown Coverage Part", _MENU_CARRIER),
    _row("Farm Coverage Part", _MENU_CARRIER),
    _row("Owners and Contractors Protective Liability Coverage Part", _MENU_CARRIER),
    _row("Underground Storage Tank Policy", _MENU_CARRIER),
    _row("Contractor Equipment"),
]

# The session's own flags, as stored.
ORBIN_FLAGS = {
    "has_general_liability": True, "has_auto_coverage": True, "has_auto_liability": True,
    "has_commercial_auto": True, "has_inland_marine": True, "has_umbrella": True,
    "has_property_coverage": False, "has_workers_comp": False, "has_crime": False,
    "has_cyber": False, "has_builders_risk": False, "has_truckers_coverage": False,
    "has_motor_carrier_coverage": False, "has_garage_operations": False,
    "has_garage_coverage": False, "has_garage_liability": False, "has_garage_keepers": False,
    "has_garagekeepers_coverage": False, "has_dealers_coverage": False,
    "has_auto_dealer_exposure": False,
    "property_has_bi_coverage": True, "property_has_peril_deductibles": False,
    "auto_has_um_uim": True, "auto_has_physical_damage": True, "auto_has_hired_nonowned": True,
    "is_contractor": True, "is_commercial_policy": True, "is_certificate_doc": True,
    "has_certificate_request": True,
}

CARRIED = ["Liability", "Inland Marine", "Automobile", "Umbrella"]


def _orbin_facts():
    return {
        "applicant_name": "ORBIN CONTRACTING LLC",
        "mailing_address": "4800 DAHLIA ST # D13, DENVER CO 80216-3121",
        "state_of_operations": "CO",
        "auto_liability_limit": "$ 1,000,000",
        "auto_um_uim_limit": "$ 1,000,000",
        "contractor_type": "commercial general contractor",
        "lines_of_business": list(ORBIN_LINES_OF_BUSINESS),
        "coverage_lines": [dict(r) for r in ORBIN_COVERAGE_LINES],
    }


# ─────────────────────────────────────────────────────────────────────────────
# ITEM 9 - a row that prints its own denial is not a line item
# ─────────────────────────────────────────────────────────────────────────────
_LINE_SETS = {
    "workers comp":      ("workers compensation", _WC_LINE_PHRASES),
    "property":          ("commercial property", _PROP_LINE_PHRASES),
    "general liability": ("general liability", _GL_LINE_PHRASES),
    "auto":              ("business auto", _AUTO_LINE_PHRASES),
    "umbrella":          ("umbrella", _UMB_LINE_PHRASES),
}


class TestDeniedRowIsNotALineItem:

    def test_orbin_page_1_does_not_read_workers_comp_as_a_line(self):
        """The reported case: the Umbrella row's premium, one row down, was
        read as the WC line's money signal."""
        assert _dec_line_present(ORBIN_PAGE_1.lower(), _WC_LINE_PHRASES) is False

    def test_orbin_page_1_still_reads_its_priced_umbrella_row(self):
        assert _dec_line_present(ORBIN_PAGE_1.lower(), _UMB_LINE_PHRASES) is True

    @pytest.mark.parametrize("name, phrases", list(_LINE_SETS.values()), ids=list(_LINE_SETS))
    @pytest.mark.parametrize("shape", [
        "{n} no coverage\n7 other line $3,418.00",
        "6 | {n} | no coverage\n7 | other line | $3,418.00",
        "{n} premium: no coverage\n$3,418.00",
        "{n} - not covered\nnext line $1,000",
        "{n} coverage not provided limit",
    ])
    def test_a_denied_row_never_triggers_for_any_line(self, name, phrases, shape):
        assert _dec_line_present(shape.format(n=name), phrases) is False

    @pytest.mark.parametrize("name, phrases", list(_LINE_SETS.values()), ids=list(_LINE_SETS))
    @pytest.mark.parametrize("shape", [
        "{n} $12,400",
        "{n}\n$12,400",                        # wrapped row - unchanged behaviour
        "{n} $12,400 flood not covered",       # priced row, a sub-item denied
        "{n} premium $4,000",
        "{n} no coverage\nx\n{n} $5,000",      # a later real row is still found
    ])
    def test_a_priced_row_still_triggers_for_every_line(self, name, phrases, shape):
        assert _dec_line_present(shape.format(n=name), phrases) is True


class TestOrbinRecommendations:

    def _recs(self):
        text = ORBIN_PAGE_1 + "\n" + ORBIN_ENDORSEMENT_MENU
        return {r["form_id"]: r for r in
                match_forms_deterministic(_orbin_facts(), dict(ORBIN_FLAGS), text=text)}

    def test_acord_130_is_not_offered_when_the_declarations_deny_wc(self):
        assert "ACORD_130" not in self._recs()

    def test_acord_140_is_not_offered_for_a_denied_property_line(self):
        assert "ACORD_140" not in self._recs()

    def test_the_carried_lines_keep_their_forms(self):
        recs = self._recs()
        for fid in ("ACORD_125", "ACORD_126", "ACORD_127", "ACORD_131"):
            assert fid in recs, fid

    def test_acord_137_co_tier_is_unchanged_client_ruling(self):
        """Brent: state forms stay at Needs Confirmation (form_service's 137
        block). Item 10 is the card's EVIDENCE, not the tier."""
        assert self._recs()["ACORD_137_CO"]["tier"] == "needs_confirmation"


# ─────────────────────────────────────────────────────────────────────────────
# ITEM 9 - a carrier name alone does not prove a policy; only line flags count
# ─────────────────────────────────────────────────────────────────────────────
class TestCarriedLinesOnTheLiveShape:

    def test_the_live_package_reports_only_its_four_carried_lines(self):
        """17 mentioned -> 4 carried. Before: 9, including Property, Crime,
        Workers' Compensation, Liquor and Pollution."""
        assert carried_lines_of_business(_orbin_facts(), None) == CARRIED

    def test_the_session_flags_do_not_bring_a_denied_line_back(self):
        """`property_has_bi_coverage` is True on this package. It is a feature
        of a line, not the line - it must not evidence Property."""
        assert carried_lines_of_business(_orbin_facts(), ORBIN_FLAGS) == CARRIED

    def test_the_cover_page_prints_the_same_four(self):
        from services.cover_service import _cover_lines_of_business
        assert _cover_lines_of_business(_orbin_facts()) == CARRIED

    @pytest.mark.parametrize("entry, expected", [
        ({"line": "Farm Coverage Part", "carrier": _MENU_CARRIER}, False),
        ({"line": "Property", "carrier": _EMC, "effective_date": "07/15/2025"}, False),
        ({"line": "GL", "policy_number": "BBC7263 - 26"}, True),
        ({"line": "Auto", "naic": "21415", "carrier": _EMC}, True),
        ({"line": "Auto", "policy_number": "N/A", "carrier": _EMC}, False),
        ({"line": "WC", "policy_number": "No Coverage"}, False),
    ])
    def test_what_identifies_a_policy(self, entry, expected):
        assert _row_identifies_policy(entry) is expected

    @pytest.mark.parametrize("flags, expected", [
        ({"property_has_bi_coverage": True}, set()),
        ({"auto_has_um_uim": True, "auto_has_physical_damage": True}, set()),
        ({"wc_has_monopolistic_state": True, "gl_is_claims_made": True}, set()),
        ({"has_property_coverage": True}, {"property"}),
        ({"has_workers_comp": True}, {"workers_comp"}),
        ({"has_umbrella": True, "has_inland_marine": True}, {"umbrella", "inland_marine"}),
        ({"has_property_coverage": False}, set()),
    ])
    def test_only_a_line_flag_names_a_line(self, flags, expected):
        assert set(_flag_families(flags)) == expected


# ─────────────────────────────────────────────────────────────────────────────
# ITEM 10 - a form's evidence is a fact of the form's own line
# ─────────────────────────────────────────────────────────────────────────────
_TEMPLATE_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "templates")

# form -> (the words its own template prints as its title, the fact prefixes
# its evidence must come from).
_FORM_LINE = {
    "ACORD_137_CA": ("COMMERCIAL AUTO", ("auto_",)),
    "ACORD_137_CO": ("COMMERCIAL AUTO", ("auto_",)),
    "ACORD_138_CA": ("GARAGE AND DEALERS", ("garage",)),
    "ACORD_138_CO": ("GARAGE AND DEALERS", ("garage",)),
    "ACORD_133":    ("WORKERS COMPENSATION", ("wc_", "total_payroll")),
}


class TestFormEvidenceMatchesTheForm:

    @pytest.mark.parametrize("form_id", list(_FORM_LINE))
    def test_evidence_facts_belong_to_the_forms_own_line(self, form_id):
        _title, prefixes = _FORM_LINE[form_id]
        keys = [k for k, _ in _FORM_EVIDENCE_FACTS[form_id]["facts"]]
        assert keys and all(k.startswith(prefixes) for k in keys), keys

    @pytest.mark.parametrize("form_id", list(_FORM_LINE))
    def test_the_template_is_what_the_table_says_it_is(self, form_id):
        """Anchor the table to the form's OWN printed title, so a relabel in
        a doc can never again decide what evidence a form shows."""
        pdfplumber = pytest.importorskip("pdfplumber")
        path = os.path.join(_TEMPLATE_DIR, f"{form_id}.pdf")
        if not os.path.exists(path):
            pytest.skip(f"{form_id} template not present")
        with pdfplumber.open(path) as pdf:
            first_page = (pdf.pages[0].extract_text() or "").upper()
        assert _FORM_LINE[form_id][0] in first_page

    def test_orbin_137_card_cites_the_auto_limit_not_a_contractor_fact(self):
        trig, suffix = _build_trigger_facts("ACORD_137_CO", _orbin_facts())
        assert suffix == "Auto liability limit: $ 1,000,000"
        assert "contractor_type" not in {t["code"] for t in trig}

    def test_the_recommendation_card_reads_the_same(self):
        text = ORBIN_PAGE_1 + "\n" + ORBIN_ENDORSEMENT_MENU
        recs = {r["form_id"]: r for r in
                match_forms_deterministic(_orbin_facts(), dict(ORBIN_FLAGS), text=text)}
        label = recs["ACORD_137_CO"]["reason_label"]
        assert "Auto liability limit: $ 1,000,000" in label
        assert "Contractor" not in label

    def test_a_form_with_none_of_its_facts_keeps_its_generic_message(self):
        assert _build_trigger_facts("ACORD_138_CO", {"contractor_type": "roofing"}) == ([], None)


# ─────────────────────────────────────────────────────────────────────────────
# ITEM 9, second pass - a false line flag outranks a borrowed policy number,
# and the cover page receives the flags it was never given
# ─────────────────────────────────────────────────────────────────────────────
import random  # noqa: E402

from services.lob_canon import (  # noqa: E402
    _flag_denied_families,
    _grants_coverage,
    canon_line,
    denies_coverage,
)

# The PER-DOCUMENT shape of page 1's denied rows, before the merge's repair
# cleared their numbers: extraction put the INLAND MARINE policy number on
# Property, Crime and Workers' Compensation. On a package the repair cannot
# untangle, identity alone would bring all three back.
_DENIED_ROWS_WITH_BORROWED_NUMBER = [
    _row("Property", _EMC, None, "6C7-40-02---26", eff="07/15/2025", exp="07/15/2026"),
    _row("Crime and Fidelity", _EMC, None, "6C7-40-02---26", eff="07/15/2025", exp="07/15/2026"),
    _row("Workers' Compensation", _EMC, None, "6C7-40-02---26", eff="07/15/2025", exp="07/15/2026"),
]
_DENIED = ("Property", "Crime and Fidelity", "Workers' Compensation")


def _with_borrowed_numbers():
    facts = _orbin_facts()
    facts["coverage_lines"] = _DENIED_ROWS_WITH_BORROWED_NUMBER + [
        r for r in facts["coverage_lines"] if r["line"] not in _DENIED]
    return facts


class TestFalseFlagOutranksIdentity:

    def test_borrowed_numbers_do_not_revive_the_denied_lines(self):
        assert carried_lines_of_business(_with_borrowed_numbers(), ORBIN_FLAGS) == CARRIED

    def test_without_the_flags_they_would_come_back(self):
        """Why the cover must be HANDED the flags: identity alone keeps them."""
        out = carried_lines_of_business(_with_borrowed_numbers(), None)
        assert set(_DENIED) <= set(out)

    def test_the_cover_page_now_receives_the_flags(self):
        from services.cover_service import _cover_lines_of_business
        assert _cover_lines_of_business(_with_borrowed_numbers(), ORBIN_FLAGS) == CARRIED

    def test_a_premium_outranks_a_false_flag(self):
        facts = _orbin_facts()
        facts["coverage_lines"] = facts["coverage_lines"] + [
            _row("Property", _EMC, "$1,200.00", "CP-1")]
        assert "Property" in carried_lines_of_business(facts, ORBIN_FLAGS)

    @pytest.mark.parametrize("flags, expected", [
        ({"has_property_coverage": False}, {"property"}),
        ({"has_property_coverage": False, "property_has_bi_coverage": True}, {"property"}),
        ({"has_auto_coverage": True, "has_garage_coverage": False}, set()),
        ({"has_garage_coverage": False, "has_auto_coverage": True}, set()),
        ({"has_auto_coverage": False, "has_commercial_auto": False}, {"auto"}),
        ({"has_workers_comp": None}, set()),
        ({"has_workers_comp": "false"}, set()),       # only a real False counts
        ({"auto_has_um_uim": False}, set()),          # a sub-flag names no line
        (None, set()),
    ])
    def test_which_families_a_flag_denies(self, flags, expected):
        assert set(_flag_denied_families(flags)) == expected


_FUZZ_NAMES = list(ORBIN_LINES_OF_BUSINESS) + [
    "Commercial General Liability", "Business Auto", "Cyber Liability",
    "Professional Liability", "Umbrella Liability", "Commercial Crime"]
_FUZZ_FLAGS = ["has_general_liability", "has_auto_coverage", "has_property_coverage",
               "has_workers_comp", "has_umbrella", "has_inland_marine", "has_crime",
               "has_cyber", "property_has_bi_coverage", "auto_has_um_uim"]


@pytest.mark.parametrize("seed", range(6))
def test_fuzz_carried_lines_never_revive_a_denied_line(seed):
    rng = random.Random(900 + seed)
    for _ in range(150):
        names = rng.sample(_FUZZ_NAMES, rng.randint(0, 10))
        rows = [{"line": rng.choice(_FUZZ_NAMES + ["", None, "Other"]),
                 "carrier": rng.choice([None, "", _EMC, "AAIS"]),
                 "naic": rng.choice([None, "", "21415", "N/A"]),
                 "policy_number": rng.choice([None, "", "6C7-40-02---26", "none", "No Coverage"]),
                 "premium": rng.choice([None, "", "$300.00", "No Coverage", "Included"]),
                 "limit": rng.choice([None, "", "$1,000,000", "Not Covered"])}
                for _ in range(rng.randint(0, 8))]
        flags = {k: rng.choice([True, False, None])
                 for k in rng.sample(_FUZZ_FLAGS, rng.randint(0, len(_FUZZ_FLAGS)))}
        out = carried_lines_of_business({"lines_of_business": names, "coverage_lines": rows}, flags)

        it = iter(names)                              # a subsequence, order kept
        assert all(any(n == m for m in it) for n in out), (names, out)
        denied = _flag_denied_families(flags)
        granted = {canon_line(r["line"]) for r in rows
                   if not denies_coverage(r) and _grants_coverage(r)}
        for n in out:
            fam = canon_line(n)
            assert fam not in denied or fam in granted, (n, flags, rows)
        if not rows and not any(v is True and k.startswith("has_") for k, v in flags.items()):
            # The legacy branch: the raw list, less only what a false flag denies -
            # one name per line since 15 Sep 2026 (the live cover printed
            # "Automobile" AND "Commercial Auto"; see lob_canon._one_name_per_line).
            from services.lob_canon import _one_name_per_line
            assert out == _one_name_per_line([n for n in names if canon_line(n) not in denied])


_DENIAL_WORDS = ["no coverage", "not covered", "coverage not provided", "No Coverage", "NOT COVERED"]
_SEPARATORS = [" ", " | ", " - ", " ..... ", "\t"]


@pytest.mark.parametrize("seed", range(5))
def test_fuzz_a_denied_row_never_counts_whatever_row_follows(seed):
    rng = random.Random(700 + seed)
    keys = list(_LINE_SETS)
    for _ in range(200):
        name, phrases = _LINE_SETS[rng.choice(keys)]
        other = rng.choice([_LINE_SETS[k][0] for k in keys
                            if not any(p in _LINE_SETS[k][0] for p in phrases)])
        sep = rng.choice(_SEPARATORS)
        denied = f"{rng.randint(1, 9)}{sep}{name}{sep}{rng.choice(_DENIAL_WORDS)}"
        priced = f"{rng.randint(1, 9)}{sep}{other}{sep}${rng.randint(1, 9)},{rng.randint(100, 999)}.00"
        rows = [denied, priced] if rng.random() < 0.7 else [priced, denied]
        text = "\n".join(rows).lower()
        assert _dec_line_present(text, phrases) is False, text


# ─────────────────────────────────────────────────────────────────────────────
# ITEM 9 - the questionnaire never asks about a line the package does not carry
# ─────────────────────────────────────────────────────────────────────────────
from services.arq_service import (  # noqa: E402
    _drop_not_applicable_questions,
    generate_arq_questions_from_facts,
)

_ORBIN_FORMS = ["ACORD_125", "ACORD_126", "ACORD_127", "ACORD_131"]


def _q(field, forms, canon=None):
    return {"field_name": field, "form_ids": list(forms), "_canonical_key": canon,
            "question": field}


# What the LIVE "Send to Client" generator put in front of the PRODUCER for
# Orbin (offline replay, 14 Sep), plus the umbrella's underlying EL row.
_ORBIN_WC_QUESTIONS = [
    _q("WorkersCompensationEmployersLiability_EmployersLiability_EachAccidentLimitAmount_A", ["ACORD_131"]),
    _q("WorkersCompensationEmployersLiability_EmployersLiability_DiseasePolicyLimitAmount_A", ["ACORD_131"]),
    _q("WorkersCompensationEmployersLiability_EmployersLiability_DiseaseEachEmployeeLimitAmount_A", ["ACORD_131"]),
    _q("employers_liability_limits", ["ACORD_131"], "employers_liability_limits"),
    _q("UnderlyingPolicy_EmployersLiability_PolicyNumberIdentifier_A", ["ACORD_131"]),
]
# Boxes that MENTION workers comp while asking about someone else - and a
# question about a line the package does carry. Never touched.
_NOT_ABOUT_AN_ABSENT_LINE = [
    _q("AdditionalInterest_WorkersCompensationCarriedCode_A", ["ACORD_126"]),
    _q("CommercialVehicleLineOfBusiness_AnyDriversNotCoveredWorkersCompensationExplanation_A",
       ["ACORD_127"]),
    _q("umbrella_limit", ["ACORD_131"], "umbrella_limit"),
]


class TestQuestionnaireSkipsAbsentLines:

    def test_orbin_is_never_asked_about_workers_comp(self):
        kept = _drop_not_applicable_questions(
            _ORBIN_WC_QUESTIONS + _NOT_ABOUT_AN_ABSENT_LINE, _orbin_facts(),
            _ORBIN_FORMS, ORBIN_FLAGS)
        assert [q["field_name"] for q in kept] == \
               [q["field_name"] for q in _NOT_ABOUT_AN_ABSENT_LINE]

    def test_applying_for_workers_comp_brings_every_question_back(self):
        kept = _drop_not_applicable_questions(
            list(_ORBIN_WC_QUESTIONS), _orbin_facts(), _ORBIN_FORMS + ["ACORD_130"], ORBIN_FLAGS)
        assert len(kept) == len(_ORBIN_WC_QUESTIONS)

    def test_no_evidence_either_way_asks_as_today(self):
        facts = {"lines_of_business": ["General Liability"]}
        kept = _drop_not_applicable_questions(list(_ORBIN_WC_QUESTIONS), facts, _ORBIN_FORMS, {})
        assert len(kept) == len(_ORBIN_WC_QUESTIONS)

    def test_no_form_list_changes_nothing(self):
        kept = _drop_not_applicable_questions(list(_ORBIN_WC_QUESTIONS), _orbin_facts(), None, ORBIN_FLAGS)
        assert len(kept) == len(_ORBIN_WC_QUESTIONS)

    def test_the_questionnaire_path_itself_drops_them(self):
        questions = generate_arq_questions_from_facts(
            _orbin_facts(), dict(ORBIN_FLAGS), list(_ORBIN_FORMS), [], [])
        names = {q.get("field_name") for q in questions}
        assert "employers_liability_limits" not in names
        assert not [n for n in names if str(n).startswith(("WorkersCompensation", "wc_"))]


@pytest.mark.parametrize("seed", range(5))
def test_fuzz_a_priced_row_always_counts(seed):
    rng = random.Random(800 + seed)
    for _ in range(200):
        name, phrases = _LINE_SETS[rng.choice(list(_LINE_SETS))]
        sep = rng.choice(_SEPARATORS)
        price = f"${rng.randint(1, 9)},{rng.randint(100, 999)}"
        shape = rng.choice([f"{name}{sep}{price}", f"{name}\n{price}",
                            f"{name}{sep}{price}{sep}flood {rng.choice(_DENIAL_WORDS)}",
                            f"{name}{sep}premium{sep}{price}"])
        assert _dec_line_present(shape.lower(), phrases) is True, shape
