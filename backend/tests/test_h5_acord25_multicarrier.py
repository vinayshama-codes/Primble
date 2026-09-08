"""V1 H5 - ACORD 25 Multi-Carrier Mapping.

Client, item 10: "An ACORD 25 can legitimately contain several insurers... Each
coverage row then identifies the applicable insurer through INSR LTR. Primble
currently has a case where two legitimate carriers were treated as a Data
Consistency problem merely because both names appeared."

  Orbin: Insurer A -> EMC Property & Casualty Company -> General Liability
         Insurer B -> Employers Mutual Casualty Co.   -> Auto / Umbrella

Two halves, both covered here:

  1. THE FORM (`_resolve_certificate_insurer_row` / `_resolve_certificate_
     insurer_letter`): the roster is built from the package's own granted
     `coverage_lines` and every coverage row's INSR LTR points at its own
     insurer. Driven through the REAL `map_facts_to_form` against the REAL
     ACORD 25 schema, never the resolver alone - the seam is what broke last
     time (the standing lesson from LLMcall1-promptChange.md).
  2. THE PICKER (`underwriting_consistency`): a healthy multi-carrier package
     is `scoped`, never a conflict, and the positive control pins that two
     carriers on ONE line is still a real conflict.

Every negative assertion carries a positive control. That is the rule this
pack's own 2026-08-28 session established after three tests were found passing
vacuously.
"""
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from services import pdf_service as ps                        # noqa: E402
from services import underwriting_consistency as uc           # noqa: E402

BACKEND = Path(__file__).resolve().parents[1]
LETTER_FIELDS = (
    "GeneralLiability_InsurerLetterCode_A",
    "Vehicle_InsurerLetterCode_A",
    "ExcessUmbrella_InsurerLetterCode_A",
    "WorkersCompensationEmployersLiability_InsurerLetterCode_A",
    "OtherPolicy_InsurerLetterCode_A",
)


@pytest.fixture(scope="module")
def schema():
    return json.loads(
        (BACKEND / "forms_schemas" / "ACORD_25_schema.json").read_text(encoding="utf-8"))


def _line(name, carrier, number, naic=None, premium="1,000", **extra):
    """A `coverage_lines` row in the shape RULE 16 actually writes."""
    row = {"line": name, "carrier": carrier, "policy_number": number,
           "premium": premium}
    if naic:
        row["naic"] = naic
    row.update(extra)
    return row


# The client's own package. Two legal entities of one group; the Auto and the
# Umbrella share an insurer, and its name is printed two ways.
ORBIN = [
    _line("Commercial General Liability", "EMC Property & Casualty Company",
          "BBC7263", naic="25186", premium="5,000"),
    _line("Business Auto", "Employers Mutual Casualty Co.",
          "6E7-40-02---26", premium="2,991"),
    _line("Commercial Liability Umbrella", "Employers Mutual Casualty Company",
          "6J7-40-02---26", premium="1,200"),
]


def _stamp(schema, lines, **facts):
    """Drive the REAL Pass-1 stamper, which is where the seam lives."""
    base = {
        "coverage_lines": lines,
        "applicant_name": "Orbin Contracting LLC",
        # The package-level merge winners - the values that used to be the
        # ONLY thing the roster could ever show.
        "carrier_name": "EMC Property & Casualty Company",
        "carrier_naic": "25186",
        "policy_number": "BBC7263",
    }
    base.update(facts)
    mapped, _confidence = ps.map_facts_to_form(base, schema, "ACORD_25")
    return mapped


def _roster(mapped):
    return {L: mapped.get("Insurer_FullName_%s" % L)
            for L in "ABCDEF" if mapped.get("Insurer_FullName_%s" % L)}


# =============================================================================
# The client's example, end to end
# =============================================================================

def test_the_clients_orbin_example_maps_exactly_as_reported(schema):
    """Insurer A -> GL, Insurer B -> Auto AND Umbrella. The client's words."""
    mapped = _stamp(schema, ORBIN)
    roster = _roster(mapped)

    assert len(roster) == 2, roster
    assert roster["A"] == "EMC Property & Casualty Company"
    # ONE insurer, though the package prints its name two ways.
    assert roster["B"] == "Employers Mutual Casualty Company"

    assert mapped["GeneralLiability_InsurerLetterCode_A"] == "A"
    assert mapped["Vehicle_InsurerLetterCode_A"] == "B"
    assert mapped["ExcessUmbrella_InsurerLetterCode_A"] == "B"


def test_every_stamped_letter_resolves_to_a_real_roster_row(schema):
    """The join is the whole feature: a letter that indexes nothing is worse
    than a blank, because it reads as a citation."""
    mapped = _stamp(schema, ORBIN)
    roster = _roster(mapped)
    for field in LETTER_FIELDS:
        letter = mapped.get(field)
        if letter:
            assert letter in roster, "%s -> %r indexes no insurer row" % (field, letter)


def test_a_carriers_naic_is_never_recombined_onto_another_carrier(schema):
    """The client's original defect, one row down: Employers Mutual must not
    inherit EMC P&C's 25186 just because it is the package scalar."""
    mapped = _stamp(schema, ORBIN)
    assert mapped["Insurer_NAICCode_A"] == "25186"        # its own, attested
    assert not mapped.get("Insurer_NAICCode_B")           # none printed -> blank


# =============================================================================
# Right-or-blank: what must NOT be filled
# =============================================================================

def test_a_line_the_package_does_not_carry_gets_no_letter(schema):
    """No Workers Comp in this package, so its INSR LTR is blank - the same
    'never borrowed' rule the policy-number cell already applies."""
    mapped = _stamp(schema, ORBIN)
    assert not mapped["WorkersCompensationEmployersLiability_InsurerLetterCode_A"]


def test_two_insurers_on_one_line_leaves_that_letter_blank(schema):
    """The certificate prints ONE row per coverage, so there is no honest
    letter. Both carriers are still SEATED - the evidence exists - but the row
    cannot cite one of them."""
    lines = [
        _line("Commercial General Liability", "Alpha Insurance Company", "A1", naic="11111"),
        _line("Commercial General Liability", "Beta Insurance Company", "B2", naic="22222"),
    ]
    mapped = _stamp(schema, lines)
    assert len(_roster(mapped)) == 2
    assert not mapped["GeneralLiability_InsurerLetterCode_A"]


def test_a_denied_line_never_seats_its_carrier(schema):
    """A "No Coverage" line still names a carrier. Seating it would tell a
    certificate holder an insurer stands behind coverage that does not exist."""
    lines = [
        _line("Commercial General Liability", "Acme Insurance Company", "X1", naic="11111"),
        {"line": "Property", "carrier": "Ghost Mutual", "premium": "No Coverage"},
    ]
    mapped = _stamp(schema, lines)
    roster = _roster(mapped)
    assert list(roster.values()) == ["Acme Insurance Company"]
    assert "Ghost Mutual" not in str(roster)


def test_unused_roster_rows_are_owned_blanks_not_gap_fill(schema):
    """A package with two insurers has no third. Rows C-F must be OWNED blanks
    so the gap-fill model is never asked to name one - that is how a
    policyholder notice page became "Insurer C" on a delivered certificate."""
    facts = {"coverage_lines": ORBIN, "_form_id": "ACORD_25"}
    for letter in "CDEF":
        field = "Insurer_FullName_%s" % letter
        assert ps._resolve_certificate_insurer_row(field, facts) is None
        assert ps._is_authoritative_blank_field(field, facts) is True


def test_an_unanswerable_letter_is_an_owned_blank_not_gap_fill():
    """THE LOAD-BEARING ONE. `InsurerLetterCode` came off the never-fill list
    so the resolver could run; if the resolver did not OWN its blanks, every
    unanswerable letter would fall through to a model that can only invent it.
    """
    facts = {"coverage_lines": ORBIN, "_form_id": "ACORD_25"}
    field = "WorkersCompensationEmployersLiability_InsurerLetterCode_A"
    assert ps._resolve_certificate_insurer_letter(field, facts) is None
    assert ps._is_authoritative_blank_field(field, facts) is True


def test_no_letter_field_ever_reaches_the_gap_fill_llm(schema):
    """Whole-form proof, through `compute_form_gaps` - the list that becomes
    the LLM's batch. Checked on a package WITH a roster and one without."""
    for lines in (ORBIN, []):
        facts = {"coverage_lines": lines, "applicant_name": "Orbin Contracting LLC"}
        _mapped, unmatched, _det = ps.compute_form_gaps("ACORD_25", schema, facts)
        leaked = [f for f in unmatched if "InsurerLetterCode" in f]
        assert not leaked, leaked


# =============================================================================
# Legacy sessions must be untouched
# =============================================================================

def test_no_coverage_lines_keeps_the_legacy_scalar_path(schema):
    """A session with no per-line evidence behaves exactly as it did before
    H5: the scalar fills row A, and every letter stays blank."""
    mapped = _stamp(schema, [])
    assert mapped["Insurer_FullName_A"] == "EMC Property & Casualty Company"
    assert not any(mapped.get(f) for f in LETTER_FIELDS)


def test_a_single_carrier_package_points_every_line_at_row_a(schema):
    """One insurer, written two ways, is one roster row - and both of its
    lines cite it."""
    lines = [
        _line("Commercial General Liability", "Acme Insurance Company", "X1", naic="11111"),
        _line("Business Auto", "Acme Insurance Co", "X2", naic="11111"),
    ]
    mapped = _stamp(schema, lines)
    assert len(_roster(mapped)) == 1
    assert mapped["GeneralLiability_InsurerLetterCode_A"] == "A"
    assert mapped["Vehicle_InsurerLetterCode_A"] == "A"


# =============================================================================
# Edge cases the roster builder has to survive
# =============================================================================

def test_more_carriers_than_the_form_has_rows(schema):
    """ACORD 25 prints six insurer rows. A seventh carrier is not seated, and
    the six that are still index correctly."""
    lines = [_line("Line %d" % i, "Carrier %d Insurance Company" % i, "P%d" % i)
             for i in range(1, 8)]
    mapped = _stamp(schema, lines)
    roster = _roster(mapped)
    assert len(roster) == 6
    assert "Carrier 7 Insurance Company" not in roster.values()


def test_one_carrier_with_two_different_naics_prints_none(schema):
    """Two readings of one carrier's NAIC is evidence we cannot resolve, and an
    unattested identifier must never print."""
    lines = [
        _line("Commercial General Liability", "Acme Insurance Company", "X1", naic="11111"),
        _line("Business Auto", "Acme Insurance Company", "X2", naic="99999"),
    ]
    mapped = _stamp(schema, lines)
    assert _roster(mapped) == {"A": "Acme Insurance Company"}
    assert not mapped.get("Insurer_NAICCode_A")


def test_a_row_with_no_carrier_is_skipped_without_shifting_letters(schema):
    """A nameless line must not consume a letter - that would make every
    later row's INSR LTR point one insurer too far down."""
    lines = [
        _line("Commercial General Liability", "", "X1"),
        _line("Business Auto", "Acme Insurance Company", "X2", naic="11111"),
    ]
    mapped = _stamp(schema, lines)
    assert _roster(mapped) == {"A": "Acme Insurance Company"}
    assert mapped["Vehicle_InsurerLetterCode_A"] == "A"


def test_the_legacy_carrier_name_column_is_still_read():
    """`carrier`/`naic` is what extraction writes, but one production dedup
    door already tolerates `carrier_name`. Reading only one spelling is how a
    fixture passes while production ships blank (D22), so both are read."""
    facts = {"_form_id": "ACORD_25", "coverage_lines": [
        {"line": "Commercial General Liability", "policy_number": "X1",
         "carrier_name": "Acme Insurance Company", "carrier_naic": "11111",
         "premium": "1,000"}]}
    assert ps._resolve_certificate_insurer_row(
        "Insurer_FullName_A", facts) == "Acme Insurance Company"
    assert ps._resolve_certificate_insurer_row("Insurer_NAICCode_A", facts) == "11111"


def test_a_malformed_naic_never_seats():
    """`_NAIC_SHAPE_RE` is the same shape gate Guard 2c-N applies, so the
    roster cannot hand the guard something it will only blank."""
    facts = {"_form_id": "ACORD_25", "coverage_lines": [
        {"line": "Commercial General Liability", "policy_number": "X1",
         "carrier": "Acme Insurance Company", "naic": "077", "premium": "1,000"}]}
    assert ps._resolve_certificate_insurer_row("Insurer_NAICCode_A", facts) is None


def test_the_roster_only_applies_to_the_certificate():
    """ACORD 25 is the only form with a roster. On a section form the resolver
    must decline so `_resolve_section_policy_identity` keeps its own line
    logic."""
    facts = {"_form_id": "ACORD_131", "coverage_lines": ORBIN}
    assert ps._resolve_certificate_insurer_row(
        "Insurer_FullName_A", facts) is ps._SCHED_SKIP
    assert ps._resolve_certificate_insurer_letter(
        "GeneralLiability_InsurerLetterCode_A", facts) is ps._SCHED_SKIP


# =============================================================================
# Anti-rot: the section->line binding must stay real
# =============================================================================

def test_every_certificate_section_binds_to_its_policy_column(schema):
    """SELF-VERIFYING BINDING. Each INSR LTR box is matched to its coverage
    line using the EXACT column string that row's own policy-number field
    carries, which is what makes the letter and the number on one printed row
    provably the same line. If either name drifts, this fails."""
    for section, column in ps._CERT_SECTION_POLICY_COLUMN.items():
        assert "%s_InsurerLetterCode_A" % section in schema, section
        assert "Policy_%s_PolicyNumberIdentifier_A" % column in schema, column


def test_every_letter_field_on_the_form_is_owned_by_the_resolver(schema):
    """No INSR LTR box may be left to chance. Every one the schema carries is
    matched by the resolver's own regex - including OtherPolicy, which is
    resolved from the leftover line."""
    fields = [f for f in schema if "InsurerLetterCode" in f]
    assert len(fields) == 5, fields
    for f in fields:
        assert ps._CERT_LETTER_RE.match(f), f


def test_the_letter_code_is_no_longer_blanked_before_the_resolver_runs():
    """`_is_nonfillable_field` runs BEFORE every resolver in both
    `map_facts_to_form` and `compute_form_gaps`. While InsurerLetterCode sat in
    its substring list the resolver was unreachable, so this is the gate that
    has to stay open - and the owned-blank tests above are what make it safe."""
    for f in LETTER_FIELDS:
        assert ps._is_nonfillable_field(f) is False, f
    # The list has not been loosened for anything else.
    assert ps._is_nonfillable_field("Producer_AuthorizedRepresentative_Signature_A")
    assert ps._is_nonfillable_field("GeneralLiability_Premium_A")


def test_a_carriers_legal_name_is_printed_as_the_document_prints_it(schema):
    """Display canonicalization title-cases a name, which is right for the
    insured and wrong for an insurer: a live certificate printed "Emc Property
    & Casualty" for EMC Property & Casualty Company, a company that does not
    exist. ACORD asks for the name "as found in the file copy of the policy"."""
    mapped = _stamp(schema, ORBIN)
    assert mapped["Insurer_FullName_A"] == "EMC Property & Casualty Company"
    assert "Emc" not in str(mapped["Insurer_FullName_A"])


def test_the_insured_is_still_canonicalized():
    """POSITIVE CONTROL for the exemption above - it is scoped to the INSURER,
    not switched off. The insured's own name still standardizes."""
    from services.display_canonicalizer import canonicalize_for_field, category_for_field
    assert category_for_field("NamedInsured_FullName_A") == "name"
    assert canonicalize_for_field(
        "NamedInsured_FullName_A", "ORBIN CONTRACTING LLC") == "Orbin Contracting LLC"
    # ...and an insurer's non-name boxes are untouched by the exemption.
    assert category_for_field("Insurer_MailingAddress_CityName_A") == "city"


# =============================================================================
# The other half: the Data Consistency picker
# =============================================================================

def _dec_docs(lines):
    """One dec page per coverage line, in the shape the engine reads."""
    return [{
        "doc_id": "d%d" % i,
        "doc_type": "dec_page",
        "filename": "dec_%d.pdf" % i,
        "facts": {"carrier_name": e["carrier"],
                  "applicant_name": "Orbin Contracting LLC",
                  "coverage_lines": [e]},
        "text": "Named Insured: Orbin Contracting LLC\nInsurer: %s\n"
                "Policy Number %s\n%s" % (e["carrier"], e["policy_number"], e["line"]),
    } for i, e in enumerate(lines, start=1)]


def _scoped_store(lines):
    """`facts["_scoped"]` as `merge_facts` writes it (C1b / D19)."""
    from services.lob_canon import canon_line
    return {"carrier_name": [{"value": e["carrier"],
                              "scope": {"line": canon_line(e["line"]),
                                        "policy_number": e["policy_number"]}}
                             for e in lines]}


def test_the_clients_package_raises_no_carrier_conflict():
    """THE CLIENT'S ACTUAL COMPLAINT. Two legitimate carriers, three lines,
    one insurer's name printed two ways - the coarse carrier normalizer used to
    fuse the two REAL carriers into one candidate, which then straddled two
    coverage lines and was reported as "two policies on the same coverage
    line". Nothing is wrong with this package."""
    merged = {"applicant_name": "Orbin Contracting LLC",
              "coverage_lines": ORBIN, "_scoped": _scoped_store(ORBIN)}
    assessment = uc.assess_underwriting_consistency(_dec_docs(ORBIN), merged)

    carrier = next(f for f in assessment["fields"] if f["fact_key"] == "carrier_name")
    assert carrier["status"] == "scoped", carrier.get("conflict_reason")
    assert assessment["review_required"] is False


def test_the_two_printings_of_one_insurer_are_one_candidate():
    """"Employers Mutual Casualty Co." and "...Company" are one insurer, so
    the producer is shown ONE value for it - and it is the fuller printing."""
    merged = {"applicant_name": "Orbin Contracting LLC",
              "coverage_lines": ORBIN, "_scoped": _scoped_store(ORBIN)}
    assessment = uc.assess_underwriting_consistency(_dec_docs(ORBIN), merged)
    carrier = next(f for f in assessment["fields"] if f["fact_key"] == "carrier_name")
    displays = {v["display"] for v in carrier["values"]}
    assert len(displays) == 2, displays
    assert "Employers Mutual Casualty Company" in displays


def test_two_carriers_on_the_SAME_line_is_still_a_conflict():
    """POSITIVE CONTROL - scoping is not a blanket amnesty. This is the case
    the producer genuinely has to resolve, and it is the same case that leaves
    the certificate's INSR LTR blank."""
    same_line = [
        _line("Commercial General Liability", "Alpha Insurance Company", "A1"),
        _line("Commercial General Liability", "Beta Insurance Company", "B2"),
    ]
    merged = {"applicant_name": "Orbin Contracting LLC",
              "coverage_lines": same_line, "_scoped": _scoped_store(same_line)}
    assessment = uc.assess_underwriting_consistency(_dec_docs(same_line), merged)
    carrier = next(f for f in assessment["fields"] if f["fact_key"] == "carrier_name")
    assert carrier["status"] != "scoped"
    assert assessment["conflict_count"] >= 1


def test_a_genuinely_different_insured_is_still_a_conflict():
    """POSITIVE CONTROL for the widened entity re-split: it must not have made
    the picker agreeable in general. Two different companies named as the
    applicant is still a conflict."""
    docs = _dec_docs(ORBIN)
    docs[1]["facts"]["applicant_name"] = "Summit Mechanical Services Inc"
    docs[1]["text"] = docs[1]["text"].replace(
        "Orbin Contracting LLC", "Summit Mechanical Services Inc")
    merged = {"applicant_name": "Orbin Contracting LLC",
              "coverage_lines": ORBIN, "_scoped": _scoped_store(ORBIN)}
    assessment = uc.assess_underwriting_consistency(docs, merged)
    applicant = next(f for f in assessment["fields"]
                     if f["fact_key"] == "applicant_name")
    assert applicant["status"] != "consistent"
