"""A companion document's list rows survive the merge (D-1, 2026-08-23).

`merge_facts` applies the primary document as a "legacy fallback for unmapped
fields". That loop wrote `mf[k] = v` for EVERY key, so the primary document's
LIST replaced the companions' instead of adding to it.

Measured on the live Run B session `10e6a861-b538-4055-8b41-10e3a6089fa2`:
merged `coverage_lines` was `1_dec_page.pdf`'s four rows byte-for-byte, and
Travelers' General Liability, Travelers' Commercial Property and Hartford's
Professional Liability were gone. The Data Consistency picker was then blamed
for missing a carrier conflict it had never been shown.

The defect was already known and patched TWICE, one key at a time - the
`dec_page_entries` block says so in as many words, and `risk_transfer` has its
own copy. Three list fields never got one. These tests pin the general fix.
"""
import pytest

import services.extraction_service as es


def _doc(name, doc_type, facts):
    return {"filename": name, "doc_type": doc_type, "facts": facts, "flags": {}}


GL_EMC = {"line": "Commercial General Liability", "carrier": "EMC Prop & Cas Co",
          "policy_number": "BBC7263-26", "premium": "$6,720"}
GL_TRAV = {"line": "Commercial General Liability",
           "carrier": "Travelers Prop Cas Co of Am",
           "policy_number": "GL-4471102-26", "premium": "$7,410"}
PROP_TRAV = {"line": "Commercial Property", "carrier": "Travelers Prop Cas Co of Am",
             "policy_number": "CP-4471103-26", "premium": "$3,880"}
AUTO_EMC = {"line": "Commercial Automobile Liability",
            "carrier": "Employers Mutual Cas Co",
            "policy_number": "6E7-40-02---26", "premium": "$2,991"}


def _merge(primary_lines, *companion_lines, doc_types=None):
    primary = _doc("1_dec.pdf", "dec_page", {"coverage_lines": list(primary_lines)})
    docs = [primary]
    for i, rows in enumerate(companion_lines):
        dt = (doc_types or {}).get(i, "dec_page")
        docs.append(_doc(f"{i+2}_other.pdf", dt, {"coverage_lines": list(rows)}))
    mf, _ = es.merge_facts(docs, primary)
    out = mf.get("coverage_lines")
    return out.get("value") if isinstance(out, dict) and "value" in out else out


# ── 1. The reported case ─────────────────────────────────────────────────────

def test_a_rival_policy_on_the_same_line_survives_the_merge():
    """THE D-1 CASE. Two carriers writing General Liability in one period is
    the disagreement the producer must be asked about - it cannot be asked
    about a row that was deleted before the comparison ran."""
    rows = _merge([GL_EMC, AUTO_EMC], [GL_TRAV, PROP_TRAV])
    carriers = {r["carrier"] for r in rows}
    assert "Travelers Prop Cas Co of Am" in carriers
    assert "EMC Prop & Cas Co" in carriers
    numbers = {r["policy_number"] for r in rows}
    assert {"BBC7263-26", "GL-4471102-26"} <= numbers


def test_a_line_only_a_companion_carries_survives():
    """Commercial Property and Professional Liability existed on exactly one
    document each and were deleted outright."""
    rows = _merge([GL_EMC], [PROP_TRAV])
    assert any(r["line"] == "Commercial Property" for r in rows)


def test_the_primary_rows_come_first():
    """Every consumer that takes 'the first matching row' must keep today's
    answer. A companion can only ever APPEND."""
    rows = _merge([GL_EMC, AUTO_EMC], [GL_TRAV])
    assert rows[0]["policy_number"] == "BBC7263-26"
    assert rows[1]["policy_number"] == "6E7-40-02---26"


# ── 2. Identity - what folds and what must not ───────────────────────────────

def test_the_same_policy_on_the_same_line_folds():
    """The GL part is printed on the dec page, the certificate and the second
    dec page. That is one contract printed three times, not three policies."""
    coi = dict(GL_EMC, carrier="EMC Property & Casualty Company", premium=None)
    dec2 = dict(GL_EMC, premium="$6,720.00")
    rows = _merge([GL_EMC], [coi], [dec2])
    gl = [r for r in rows if es._canon_line(r["line"]) == "general_liab"]
    assert len(gl) == 1, f"one GL contract printed 3 ways became {len(gl)} rows"


def test_the_same_policy_number_on_two_different_lines_is_never_folded():
    """`_NATURAL_ID_SUBKEYS` records the measured case: BBC7263-26 legitimately
    carries both Commercial General Liability AND Employee Benefits Liability.
    Keying on the number alone would delete a real coverage part."""
    ebl = {"line": "Employee Benefits Liability", "carrier": "EMC Prop & Cas Co",
           "policy_number": "BBC7263-26"}
    rows = _merge([GL_EMC], [ebl])
    assert len(rows) == 2


def test_a_row_with_no_recognisable_line_is_never_folded():
    """No canonical line, no identity - the positive-evidence rule. Two
    unmappable rows must not be assumed to be the same thing."""
    a = {"line": "Widget Protection", "policy_number": "AAA-1", "premium": "$1"}
    b = {"line": "Gadget Protection", "policy_number": "BBB-2", "premium": "$2"}
    rows = _merge([a], [b])
    assert len(rows) == 2


def test_a_certificate_row_without_a_policy_number_costs_the_form_nothing():
    """A COI row often omits the policy number, so it does NOT fold into the
    dec page's row - the two carry different identities and folding them on
    carrier alone would re-open D-1 the moment one carrier writes two policies
    on a line.

    Measured instead of assumed: `_resolve_section_policy_identity` ignores a
    row with no policy number, so the extra row costs the form nothing. The
    property worth pinning is the STAMPED value, not the row count."""
    from services.pdf_service import _resolve_section_policy_identity
    coi = {"line": "General Liability", "carrier": "EMC Prop & Cas Co"}
    rows = _merge([GL_EMC], [coi])
    facts = {"coverage_lines": rows, "_form_id": "ACORD_126"}
    assert _resolve_section_policy_identity(
        "Policy_PolicyNumberIdentifier_A", facts) == "BBC7263-26"


def test_two_real_policies_on_one_line_leave_the_form_box_BLANK():
    """The other half of the same contract, and the whole point of keeping both
    rows. Two carriers claim General Liability, so which policy the submission
    is for is genuinely unknown - right-or-blank, never a confident guess.

    Before the union fix the box stamped EMC's number with full confidence,
    because Travelers had been deleted from the fact layer."""
    from services.pdf_service import _resolve_section_policy_identity
    rows = _merge([GL_EMC], [GL_TRAV])
    facts = {"coverage_lines": rows, "_form_id": "ACORD_126"}
    assert _resolve_section_policy_identity(
        "Policy_PolicyNumberIdentifier_A", facts) is None
    assert _resolve_section_policy_identity("Insurer_FullName_A", facts) is None


# ── 3. Document role (D23) ───────────────────────────────────────────────────

def test_a_loss_runs_coverage_lines_do_not_enter_the_package_schedule():
    """MEASURED, not reasoned. A loss run pairs the AUTO policy number with
    BOTH 'Business Auto' and 'General Liability' - the claims' lines, not the
    submission's. Letting those in makes one number span two canonical lines,
    which `_coverage_lines_are_self_contradictory` reads as corruption, and the
    repair pass then cleared EVERY policy number on the package."""
    lr = [{"line": "Business Auto", "carrier": "EMC Insurance Companies",
           "policy_number": "6E7 40 02 26"},
          {"line": "General Liability", "carrier": "EMC Insurance Companies",
           "policy_number": "6E7 40 02 26"}]
    rows = _merge([GL_EMC, AUTO_EMC], lr, doc_types={0: "loss_run"})
    assert all("EMC Insurance Companies" not in str(r.get("carrier")) for r in rows)
    # and the pairing survives intact
    by_line = {es._canon_line(r["line"]): r.get("policy_number") for r in rows}
    assert by_line["general_liab"] == "BBC7263-26"
    assert by_line["auto"] == "6E7-40-02---26"


def test_an_unknown_document_role_still_contributes_everything():
    """Fail-open: role scope only ever REMOVES, and an unlisted type is not a
    role we have an opinion about."""
    rows = _merge([GL_EMC], [PROP_TRAV], doc_types={0: "something_new"})
    assert any(r["line"] == "Commercial Property" for r in rows)


# ── 4. lines_of_business folds by FAMILY, not by text ────────────────────────

def _merge_lob(primary, *companions):
    p = _doc("1_dec.pdf", "dec_page", {"lines_of_business": list(primary)})
    docs = [p] + [_doc(f"{i+2}.pdf", "dec_page", {"lines_of_business": list(c)})
                  for i, c in enumerate(companions)]
    mf, _ = es.merge_facts(docs, p)
    out = mf.get("lines_of_business")
    return out.get("value") if isinstance(out, dict) and "value" in out else out


def test_one_coverage_named_five_ways_stays_one_line():
    """Client 1.7: different terminology is not different coverage. A text-only
    union produced 11 lines for a 6-line package."""
    out = _merge_lob(["Commercial General Liability"],
                     ["General Liability"], ["CGL"], ["Commercial Liability"])
    assert out == ["Commercial General Liability"]


def test_the_primary_wording_is_the_one_that_shows():
    out = _merge_lob(["Commercial Automobile Liability"], ["Business Auto"])
    assert out == ["Commercial Automobile Liability"]


def test_a_genuinely_new_line_is_added():
    out = _merge_lob(["Commercial General Liability"], ["Commercial Property"])
    assert len(out) == 2
    assert "Commercial Property" in out


def test_unmappable_terminology_is_never_folded_into_a_family():
    """D9 / client 1.7: unknown terminology stays unmapped, and two different
    unknown names are two different things."""
    out = _merge_lob(["Widget Protection"], ["Gadget Protection"])
    assert len(out) == 2


def test_unmappable_terminology_still_de_duplicates_on_its_own_text():
    out = _merge_lob(["Widget Protection"], ["widget protection"])
    assert len(out) == 1


# ── 5. Nothing else changes ──────────────────────────────────────────────────

def test_a_scalar_field_still_takes_the_primary_value():
    p = _doc("1.pdf", "dec_page", {"applicant_name": "ORBIN CONTRACTING LLC"})
    c = _doc("2.pdf", "dec_page", {"applicant_name": "Someone Else"})
    mf, _ = es.merge_facts([p, c], p)
    v = mf.get("applicant_name")
    v = v.get("value") if isinstance(v, dict) and "value" in v else v
    assert v == "ORBIN CONTRACTING LLC"


def test_a_primary_only_list_is_unchanged():
    rows = _merge([GL_EMC, AUTO_EMC])
    assert len(rows) == 2


def test_a_companion_only_list_still_arrives():
    """The primary has nothing for this key, so the union never runs and the
    merged value must survive untouched."""
    p = _doc("1.pdf", "dec_page", {"applicant_name": "X"})
    c = _doc("2.pdf", "dec_page", {"coverage_lines": [GL_EMC]})
    mf, _ = es.merge_facts([p, c], p)
    out = mf.get("coverage_lines")
    out = out.get("value") if isinstance(out, dict) and "value" in out else out
    assert out and len(out) == 1


@pytest.mark.parametrize("junk", [None, "text", 42, [None, 42], [{}, {"line": None}]])
def test_garbage_rows_never_raise(junk):
    p = _doc("1.pdf", "dec_page", {"coverage_lines": [GL_EMC]})
    c = _doc("2.pdf", "dec_page", {"coverage_lines": junk})
    mf, _ = es.merge_facts([p, c], p)          # must not raise
    assert "coverage_lines" in mf


# ── 6. ANTI-ROT ──────────────────────────────────────────────────────────────

def test_the_primary_loop_does_not_blindly_overwrite_list_fields():
    """The exact line that caused D-1 was `mf[k] = v` for every key. If it
    comes back, every companion document's rows start vanishing again and the
    only symptom is a conflict that never appears."""
    import inspect
    src = inspect.getsource(es.merge_facts)
    start = src.index("legacy fallback for unmapped fields")
    block = src[start:start + 1800]
    assert "_union_list_fact" in block, (
        "merge_facts no longer unions list fields - the primary document's "
        "rows will replace every companion's again (D-1)")


def test_coverage_lines_has_a_registered_identity():
    """Without one the generic scan finds no key on these rows and every
    printing of the GL part survives as its own row."""
    assert "coverage_lines" in es._SCHEDULE_DEDUP_KEYS


def test_the_identity_needs_both_halves():
    """Line alone folds two real policies (D-1); number alone folds two real
    coverage parts (the BBC7263 / EBL case)."""
    keys_gl_emc = es._coverage_line_dedup_keys(GL_EMC)
    keys_gl_trav = es._coverage_line_dedup_keys(GL_TRAV)
    assert keys_gl_emc and keys_gl_trav
    assert keys_gl_emc != keys_gl_trav, "same line, different policy must differ"
    ebl = {"line": "Employee Benefits Liability", "policy_number": "BBC7263-26"}
    assert es._coverage_line_dedup_keys(ebl) != keys_gl_emc, (
        "same policy, different line must differ")


# ── 7. The context rules must say which FACTS they may speak about ──────────
# LIVE REGRESSION, Run B 2026-08-23: "4800 Dahlia St # D13, Denver, CO
# 80216-3121" and "2255 S Wadsworth Blvd Ste 410, Lakewood, CO 80227" came back
# as ONE fact - "treated as equivalent" - and the address conflict the client
# originally reported disappeared from the screen.
#
# Cause: `PackageContext.is_component_of` compares `_alnum(value)`, a rule built
# for "a LINE premium is part of the PACKAGE premium". On an address that yields
# a meaningless token, and the package index happened to hold the Denver one as
# line-level and the Lakewood one as package-level. SECOND TIME a context rule
# keyed on a value's characters silenced a real conflict - C1-H / B14 was the
# first, and `_owner_split_allowed` was the gate added then.

def test_a_component_rule_never_speaks_about_an_address():
    """The client's literal reported values. This must never fold again."""
    from services.fact_equivalence import _component_split_allowed
    assert not _component_split_allowed("mailing_address")
    assert not _component_split_allowed("physical_address")


@pytest.mark.parametrize("key", [
    "mailing_address", "physical_address", "carrier_name", "applicant_name",
    "dba_name", "effective_date", "expiration_date", "policy_number", "fein",
    "contractor_type", "producer_name",
])
def test_no_non_quantity_fact_gets_the_component_rule(key):
    from services.fact_equivalence import _component_split_allowed
    assert not _component_split_allowed(key), (
        f"{key} is not a quantity - 'one is a piece of the other' is meaningless "
        "for it, and the rule can only ever destroy a real conflict")


@pytest.mark.parametrize("key", ["total_policy_premium"])
def test_the_component_rule_survives_for_its_own_purpose(key):
    """The rule's own purpose must survive the gate: a LINE premium IS part of
    the PACKAGE premium, so `$2,991` and `$10,663` are not rivals."""
    from services.fact_equivalence import _component_split_allowed
    assert _component_split_allowed(key)


@pytest.mark.parametrize("key", [
    "gl_each_occurrence", "umbrella_limit", "total_payroll", "num_employees",
    "total_revenue", "property_building_value", "gl_deductible",
])
def test_a_quantity_alone_does_not_get_the_component_rule(key):
    """NARROWED 2026-08-26 on live evidence (C4 test S5). These were previously
    asserted to GET the rule, on the premise that "quantity" was a sufficient
    gate. It is not.

    Two applications stated Annual Gross Sales $2,400,000 and $3,850,000. The
    verified index recorded the per-location class exposure as a LINE-level
    value and the other document's revenue as a PACKAGE-level one, so
    `is_component_of` pronounced a genuine disagreement "a piece of the other"
    and folded it. The producer screen read "All clear" - the third time a
    context rule keyed on a value's characters silenced a real conflict.

    Two candidate answers to the SAME fact are RIVALS. A part/whole reading is
    real only where the package figure is genuinely composed of line figures,
    which on this schema is premiums and nothing else. A per-class payroll
    basis is already handled by
    `underwriting_consistency._drop_class_exposure_candidates`, which requires
    positive evidence from the package's own class schedule - not by this rule.
    """
    from services.fact_equivalence import _component_split_allowed
    assert not _component_split_allowed(key), (
        f"{key}: two documents stating different values for it are rival "
        "answers, and this rule can only ever destroy that conflict")


def test_a_policy_amount_is_money_and_a_policy_number_is_not():
    """`policy` was a STRONG identifier token, tested before money, so every
    `policy_*` AMOUNT was classed `identifier` - which printed "the documents
    carry different identifiers" about a dollar figure and denied the field the
    component rule."""
    from services.fact_equivalence import value_kind
    for k in ("total_policy_premium", "policy_premium", "policy_limit",
              "policy_deductible", "gl_policy_premium"):
        assert value_kind(k) == "money", f"{k} should be money"
    for k in ("policy_number", "prior_policy_number", "policy_form_type"):
        assert value_kind(k) == "identifier", f"{k} should stay an identifier"
    assert value_kind("policy_effective_date") == "date"
