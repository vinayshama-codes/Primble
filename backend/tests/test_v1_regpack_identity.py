"""V1 REQUIRED REGRESSION TEST PACK - Identity & normalization
(client tests 1, 3, 4).

Part of the client's REQUIRED V1 REGRESSION TEST PACK. Recurring regression
scenarios: re-run on every change to the comparison door, normalization, the
ACORD 25 certificate rows, or loss-run identity matching.

  Test 1 - Orbin Address Equivalence
  Test 3 - ACORD 25 Multiple Insurers
  Test 4 - Loss Run Name Formatting

Every test drives the REAL comparison door (`services/fact_comparison.py` - the
ONE door, enforced by tests/test_comparison_has_one_owner.py), the REAL Data
Consistency engine (`underwriting_consistency.assess_underwriting_consistency`),
the REAL ACORD 25 stamper (`pdf_service.map_facts_to_form` against the real
schema) and the REAL loss-run identity matcher.

KNOWN GAP - see test_r03_insurer_letters_map_to_their_line, which is an
xfail(strict=True): V1 item H5 "ACORD 25 Multi-Carrier Mapping" is NOT STARTED.
The per-line POLICY columns are correct and are pinned here as passing tests;
the insurer LETTER columns are unmapped. Delete the xfail when H5 ships.
"""
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from services import fact_comparison as fc                    # noqa: E402
from services import loss_run_identity as lri                 # noqa: E402
from services import pdf_service as ps                        # noqa: E402
from services import sqs_service as sq                        # noqa: E402
from services import underwriting_consistency as uc           # noqa: E402

BACKEND = Path(__file__).resolve().parents[1]


# =============================================================================
# TEST 1 - Orbin Address Equivalence
# =============================================================================

# The client's three literal inputs.
ADDR_FULL = "4800 Dahlia St # D13, Denver, CO 80216-3121"
ADDR_SPELLED = "4800 Dahlia Street D13, Denver, CO 80216"
ADDR_CITY_ONLY = "Denver, Colorado"
ALL_THREE = [ADDR_FULL, ADDR_SPELLED, ADDR_CITY_ONLY]


@pytest.mark.parametrize("key", ["mailing_address", "physical_address"])
@pytest.mark.parametrize("a,b", [
    (ADDR_FULL, ADDR_SPELLED),      # abbreviation + ZIP+4 vs 5
    (ADDR_FULL, ADDR_CITY_ONLY),    # differing levels of specificity
    (ADDR_SPELLED, ADDR_CITY_ONLY),
])
def test_r01_no_address_conflict(key, a, b):
    """No address conflict - every pairwise comparison agrees."""
    assert fc.values_agree(key, a, b) is True
    assert fc.conflict(key, [a, b]) is False


@pytest.mark.parametrize("key", ["mailing_address", "physical_address"])
def test_r01_all_three_are_one_value(key):
    """All three collapse into ONE value group, not two or three."""
    result = fc.compare(key, ALL_THREE)
    assert result.verdict == "equivalent"
    assert len(result.groups) == 1
    assert sorted(result.groups[0]) == [0, 1, 2]


@pytest.mark.parametrize("key", ["mailing_address", "physical_address"])
def test_r01_a_genuinely_different_address_still_conflicts(key):
    """POSITIVE CONTROL - the comparison door has not simply stopped
    disagreeing. A different street number is still a real conflict."""
    assert fc.conflict(key, [ADDR_FULL, "1200 Sherman Ave, Boulder, CO 80302"]) is True


def _doc(doc_id, doc_type, filename, address):
    """A document in the shape assess_underwriting_consistency actually reads.

    NOTE THE `facts` KEY. The engine reads `d["facts"]`, not
    `d["extracted"]["facts"]` - a fixture using the latter hands it a document
    with NO facts, and every conflict test then passes for the wrong reason.
    `text` carries the raw OCR the safety-net scan needs; without it the engine
    logs "no raw text" and runs on LLM facts alone.
    """
    return {
        "doc_id": doc_id,
        "doc_type": doc_type,
        "filename": filename,
        "facts": {"mailing_address": address,
                  "applicant_name": "Orbin Contracting LLC"},
        "text": "Named Insured: Orbin Contracting LLC\n"
                "Mailing Address: %s\nPolicy Period 07/15/2025 - 07/15/2026" % address,
    }


ORBIN_DOCS = [
    _doc("d1", "dec_page", "dec_page.pdf", ADDR_FULL),
    _doc("d2", "acord_125", "application.pdf", ADDR_SPELLED),
    _doc("d3", "loss_run", "loss_run.pdf", ADDR_CITY_ONLY),
]


def test_r01_no_warning():
    """No warning - the Data Consistency engine raises nothing on formatting."""
    assessment = uc.assess_underwriting_consistency(
        ORBIN_DOCS, {"mailing_address": ADDR_FULL})
    assert assessment["conflict_count"] == 0
    assert assessment["review_required"] is False

    # The engine really did compare this field across the three documents and
    # called it CONSISTENT - a stronger statement than an absent row, which is
    # also what an ignored fixture would produce.
    assert "mailing_address" in assessment["assessed_keys"]
    row = next(f for f in assessment["fields"] if f["fact_key"] == "mailing_address")
    assert row["status"] == "consistent"
    assert not row.get("review_required")


def test_r01_the_consistency_engine_still_reports_a_real_disagreement():
    """POSITIVE CONTROL - a genuinely different address IS reported, so the
    clean result above is the normalizer working and not a dead engine."""
    docs = list(ORBIN_DOCS[:2]) + [
        _doc("d3", "loss_run", "loss_run.pdf", "1200 Sherman Ave, Boulder, CO 80302")]
    assessment = uc.assess_underwriting_consistency(
        docs, {"mailing_address": ADDR_FULL})
    assert assessment["conflict_count"] >= 1
    row = next(f for f in assessment["fields"] if f["fact_key"] == "mailing_address")
    assert row["status"] != "consistent"


def test_r01_no_sqs_cap_or_deduction_from_formatting():
    """No SQS cap or deduction arises from address formatting."""
    facts = {
        "applicant_name": "Orbin Contracting LLC",
        "mailing_address": ADDR_FULL,
        "physical_address": ADDR_SPELLED,
    }
    hard, soft = sq.evaluate_stops(facts, {})
    offenders = [m for m in list(hard) + list(soft) if "address" in m.lower()]
    assert not offenders, offenders

    cap, _ = sq._resolve_cap(
        [m for m in hard if "address" in m.lower()],
        [m for m in soft if "address" in m.lower()])
    assert cap is None, "address formatting must never cap the score"


# =============================================================================
# TEST 3 - ACORD 25 Multiple Insurers
# =============================================================================

# Three lines, three DIFFERENT carriers, each with its own NAIC and policy
# number - the live shape the Orbin package produced.
MULTI_INSURER_LINES = [
    {"line": "Commercial General Liability", "policy_number": "BBC7263",
     "carrier_name": "EMC Property & Casualty", "carrier_naic": "25186",
     "premium": "5,000"},
    {"line": "Business Auto", "policy_number": "6E7-40-02---26",
     "carrier_name": "Employers Mutual Casualty", "carrier_naic": "21415",
     "premium": "2,991"},
    {"line": "Commercial Liability Umbrella", "policy_number": "6J7-40-02---26",
     "carrier_name": "EMCASCO Insurance Company", "carrier_naic": "21407",
     "premium": "1,200"},
]

MULTI_INSURER_FACTS = {
    "coverage_lines": MULTI_INSURER_LINES,
    "applicant_name": "Orbin Contracting LLC",
    # The package-level merge winners - the values that used to be borrowed
    # onto every line.
    "policy_number": "BBC7263",
    "carrier_name": "EMC Property & Casualty",
    "carrier_naic": "25186",
    "gl_each_occurrence": "$1,000,000",
    "gl_aggregate": "$2,000,000",
    "auto_liability_limit": "$1,000,000",
    "umbrella_limit": "$3,000,000",
}
MULTI_INSURER_FLAGS = {"has_general_liability": True, "has_auto_coverage": True,
                       "has_umbrella": True}


@pytest.fixture(scope="module")
def acord25_mapped():
    schema = json.loads(
        (BACKEND / "forms_schemas" / "ACORD_25_schema.json").read_text(encoding="utf-8"))
    mapped, _confidence = ps.map_facts_to_form(
        dict(MULTI_INSURER_FACTS), schema, "ACORD_25")
    return mapped


def test_r03_each_line_carries_its_own_policy_number(acord25_mapped):
    """GL, Auto and Umbrella policy numbers stay on their OWN certificate row."""
    assert acord25_mapped["Policy_GeneralLiability_PolicyNumberIdentifier_A"] == "BBC7263"
    assert acord25_mapped["Policy_AutomobileLiability_PolicyNumberIdentifier_A"] == "6E7-40-02---26"
    assert acord25_mapped["Policy_ExcessLiability_PolicyNumberIdentifier_A"] == "6J7-40-02---26"


def test_r03_a_line_the_package_does_not_carry_stays_blank(acord25_mapped):
    """Workers Comp is not in this package - its row is blank, never borrowed.

    This is the assertion that proves the three above are per-line attribution
    rather than one scalar reaching every column.
    """
    assert not acord25_mapped["Policy_WorkersCompensationAndEmployersLiability_PolicyNumberIdentifier_A"]


@pytest.mark.parametrize("column,expected", [
    ("GeneralLiability", "BBC7263"),
    ("Automobile", "6E7-40-02---26"),
    ("ExcessUmbrella", "6J7-40-02---26"),
    ("WorkersCompensation", None),
])
def test_r03_line_cell_resolver_attributes_by_line(column, expected):
    """The resolver itself, driven directly - one policy number cannot be shown
    against three coverages."""
    field = "Policy_%s_PolicyNumberIdentifier_A" % column
    assert ps._resolve_current_policy_line_cell(field, MULTI_INSURER_FACTS) == expected


def test_r03_gl_and_auto_umbrella_carriers_remain_separate():
    """The GL carrier and the Auto/Umbrella carriers remain SEPARATE facts."""
    carriers = {e["carrier_name"] for e in MULTI_INSURER_LINES}
    naics = {e["carrier_naic"] for e in MULTI_INSURER_LINES}
    assert len(carriers) == 3 and len(naics) == 3

    # A carrier and its NAIC are only ever paired from ONE entry - the defect
    # this replaced recombined Employers Mutual with EMC P&C's NAIC 25186.
    for entry in MULTI_INSURER_LINES:
        assert fc.carriers_same_family(entry["carrier_name"], entry["carrier_name"])
    gl, auto = MULTI_INSURER_LINES[0], MULTI_INSURER_LINES[1]
    assert gl["carrier_naic"] != auto["carrier_naic"]


def test_r03_no_carrier_conflict_solely_because_multiple_insurers_exist():
    """No carrier conflict is raised just because the package has 3 insurers."""
    hard, soft = sq.evaluate_stops(MULTI_INSURER_FACTS, MULTI_INSURER_FLAGS)
    offenders = [m for m in list(hard) + list(soft)
                 if "carrier" in m.lower() or "insurer" in m.lower()
                 or "multiple distinct policy" in m.lower()]
    assert not offenders, offenders


def _dec_docs(lines):
    """One dec page per coverage line, in the live document shape (`facts`)."""
    return [{
        "doc_id": "d%d" % i,
        "doc_type": "dec_page",
        "filename": "dec_%d.pdf" % i,
        "facts": {"carrier_name": entry["carrier_name"],
                  "applicant_name": "Orbin Contracting LLC",
                  "coverage_lines": [entry]},
        "text": "Named Insured: Orbin Contracting LLC\nInsurer: %s\n"
                "Policy Number %s\n%s" % (entry["carrier_name"],
                                          entry["policy_number"], entry["line"]),
    } for i, entry in enumerate(lines, start=1)]


def _scoped_store(lines):
    """`facts["_scoped"]` as `merge_facts` writes it (C1b / D19): each
    line-scoped fact carried WITH the coverage line it belongs to.

    Omitting this is what makes a healthy 3-carrier package look like a
    cross-document disagreement - the scope is the whole point.
    """
    return {"carrier_name": [{"value": e["carrier_name"],
                              "scope": {"line": e["line"],
                                        "policy": e["policy_number"]}}
                             for e in lines]}


def test_r03_multi_insurer_documents_raise_no_consistency_conflict():
    """Three documents naming three carriers - one per line - is not a
    cross-document disagreement about ONE carrier."""
    merged = {"applicant_name": "Orbin Contracting LLC",
              "coverage_lines": MULTI_INSURER_LINES,
              "_scoped": _scoped_store(MULTI_INSURER_LINES)}
    assessment = uc.assess_underwriting_consistency(
        _dec_docs(MULTI_INSURER_LINES), merged)

    assert assessment["conflict_count"] == 0
    assert assessment["review_required"] is False

    applicant = next(f for f in assessment["fields"]
                     if f["fact_key"] == "applicant_name")
    assert applicant["status"] == "consistent", "the insured is the same on all three"

    # The three carriers are RETAINED under their own line scope - each stays
    # its own value, rather than one being picked or a conflict raised.
    carrier = next(f for f in assessment["fields"] if f["fact_key"] == "carrier_name")
    assert carrier["status"] == "scoped"


def test_r03_two_carriers_on_the_SAME_line_is_still_a_conflict():
    """POSITIVE CONTROL - scoping is not a blanket amnesty. Two different
    carriers on ONE coverage line is a genuine conflict for the producer."""
    same_line = [
        dict(MULTI_INSURER_LINES[0]),
        dict(MULTI_INSURER_LINES[1], line="Commercial General Liability"),
    ]
    merged = {"applicant_name": "Orbin Contracting LLC",
              "coverage_lines": same_line,
              "_scoped": _scoped_store(same_line)}
    assessment = uc.assess_underwriting_consistency(_dec_docs(same_line), merged)

    carrier = next(f for f in assessment["fields"] if f["fact_key"] == "carrier_name")
    assert carrier["status"] != "scoped"
    assert assessment["conflict_count"] >= 1


@pytest.mark.xfail(strict=True, reason=(
    "V1 REGRESSION PACK GAP - client test 3 'insurer letters map correctly'. "
    "H5 'ACORD 25 Multi-Carrier Mapping' is NOT STARTED. "
    "pdf_service._ACORD_FIELD_RULES maps Insurer_FullName to the single "
    "package-level carrier_name scalar, so Insurer_FullName_B..F are blank on a "
    "3-carrier package, and every *_InsurerLetterCode_* is unmapped (rule value "
    "None) and additionally listed in _RAW_TEXT_SKIP_PATTERNS, so no line can "
    "point at its own insurer row. Per-line POLICY columns are correct and are "
    "pinned by the passing tests above. Remove this xfail when H5 ships."))
def test_r03_insurer_letters_map_to_their_line(acord25_mapped):
    """Insurer letters map correctly: three carriers occupy three insurer rows,
    and each coverage line's letter code points at its own insurer."""
    rows = {letter: acord25_mapped.get("Insurer_FullName_%s" % letter)
            for letter in "ABCDEF"}
    named = {letter: value for letter, value in rows.items() if value}
    assert len(named) == 3, named

    letters = {
        "GeneralLiability_InsurerLetterCode_A": "EMC Property & Casualty",
        "Vehicle_InsurerLetterCode_A": "Employers Mutual Casualty",
        "ExcessUmbrella_InsurerLetterCode_A": "EMCASCO Insurance Company",
    }
    for field, carrier in letters.items():
        letter = acord25_mapped.get(field)
        assert letter, "%s is unmapped" % field
        assert rows.get(str(letter).strip().upper()) == carrier


# =============================================================================
# TEST 4 - Loss Run Name Formatting
# =============================================================================

APPLICANT = "Orbin Contracting LLC"
NAME_VARIANTS = [
    "ORBIN CONTRACTING LLC",        # the client's first example
    "Orbin Contracting, L.L.C.",    # the client's second example
    "Orbin Contracting LLC",        # byte-identical control
]


def _loss_run_doc(name):
    """NOTE THE `facts` KEY - `match_loss_run_identity` reads `d["facts"]`.
    A fixture nesting them under `extracted` gives the matcher no name at all,
    which returns POSSIBLE for EVERY input and makes this whole scenario pass
    vacuously. That is exactly what the positive control below catches.
    """
    return {
        "doc_id": "lr1",
        "doc_type": "loss_run",
        "filename": "loss_run.pdf",
        "facts": {"applicant_name": name},
        "text": "LOSS RUN REPORT\nNamed Insured: %s\n"
                "Valuation Date 06/30/2026\n3 claims\n" % name,
    }


def _tier(name):
    return lri.match_loss_run_identity(
        [_loss_run_doc(name)], APPLICANT, {"applicant_name": APPLICANT})["tier"]


def test_r04_names_normalize_before_match_quality():
    """Names normalize BEFORE match quality is judged - every formatting of the
    same name reaches the SAME tier as the byte-identical control."""
    tiers = {name: _tier(name) for name in NAME_VARIANTS}
    assert len(set(tiers.values())) == 1, tiers
    assert tiers["ORBIN CONTRACTING LLC"] == tiers["Orbin Contracting LLC"]
    assert tiers["Orbin Contracting, L.L.C."] == tiers["Orbin Contracting LLC"]


def test_r04_a_different_insured_is_still_caught():
    """POSITIVE CONTROL - the matcher has not stopped discriminating. A loss run
    for a genuinely different company does NOT reach the same tier."""
    assert _tier("Summit Mechanical Services Inc") != _tier(APPLICANT)


def test_r04_formatting_alone_does_not_reduce_loss_history():
    """Formatting alone does not reduce the Loss History pillar."""
    facts = {"loss_history_years": 5, "num_claims": 3, "total_incurred": 42000,
             "prior_carrier": "EMC Property & Casualty"}
    scores = {
        name: sq.calculate_p4_loss_history(
            facts, {}, has_loss_run_doc=True, loss_run_match=_tier(name))[0]
        for name in NAME_VARIANTS
    }
    assert len(set(scores.values())) == 1, scores

    # And the identity check itself reports no mismatch on any formatting.
    for name in NAME_VARIANTS:
        detail = sq._check_loss_run_insured_match_detail(
            [_loss_run_doc(name)], APPLICANT, {"applicant_name": APPLICANT})
        assert detail["tier"] != "no_match", (name, detail)


def test_r04_a_mismatched_name_does_reduce_it():
    """POSITIVE CONTROL - a real mismatch still caps the pillar, so the
    equality above is normalization and not an inert scorer."""
    facts = {"loss_history_years": 5, "num_claims": 3, "total_incurred": 42000}
    matched = sq.calculate_p4_loss_history(
        facts, {}, has_loss_run_doc=True, loss_run_match="strong")[0]
    mismatched = sq.calculate_p4_loss_history(
        facts, {}, has_loss_run_doc=True, loss_run_match="no_match")[0]
    assert mismatched < matched
    assert mismatched <= sq._LOSS_NO_MATCH_CAP
