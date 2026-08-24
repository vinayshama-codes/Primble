"""Scope is STORED on the fact, not re-derived from its spelling (C1b / D19).

Owner, 2026-08-21: *"we should carry relationship, we should store it somehow,
not just this but for every other important fact."* Client 1.1 puts
Scope/Association BEFORE Reconciliation; until C1b, scope was recovered inside
the comparator from the value's own CHARACTERS.

That weakness has now produced three separate defects:
  B14 - the certificate's umbrella $1,000,000 inherited the GL policy's owner
        because the dec page prints that amount as the GL limit
  G3  - `is_component_of` folded a Denver address into a Lakewood one
  Pass 1b (reverted) - a carrier printed `EMC Prop & Cas Co` on one page and
        `EMC Property & Casualty Company` on another lost its scope entirely,
        turning the client's own "GL carrier and Auto carrier may legitimately
        differ" example into a false conflict

The store is written once at merge, while the line -> carrier -> policy
relationship still exists, and read thereafter.
"""
import pytest

import services.extraction_service as es
from services.underwriting_consistency import assess_underwriting_consistency

GL   = {"line": "Commercial General Liability", "carrier": "EMC Prop & Cas Co",
        "policy_number": "BBC7263-26", "premium": "$6,720"}
AUTO = {"line": "Commercial Automobile Liability",
        "carrier": "Employers Mutual Cas Co",
        "policy_number": "6E7-40-02---26", "premium": "$2,991"}
UMB  = {"line": "Commercial Liability Umbrella",
        "carrier": "Employers Mutual Cas Co",
        "policy_number": "6J7-40-02---26", "premium": "$4,100"}
GL_RIVAL = {"line": "Commercial General Liability",
            "carrier": "Travelers Prop Cas Co of Am",
            "policy_number": "GL-4471102-26", "premium": "$7,410"}


def _store(lines):
    mf = {"coverage_lines": list(lines)}
    es._build_scoped_fact_store(mf)
    return mf


def _doc(fn, dt, **f):
    return {"doc_id": fn, "filename": fn, "doc_type": dt, "facts": f}


# ── 1. The store itself ──────────────────────────────────────────────────────

def test_each_line_scoped_fact_is_stored_with_its_line_and_policy():
    mf = _store([GL, AUTO])
    carriers = mf["_scoped"]["carrier_name"]
    by_line = {c["scope"]["line"]: c["value"] for c in carriers}
    assert by_line == {"general_liab": "EMC Prop & Cas Co",
                       "auto": "Employers Mutual Cas Co"}
    assert all(c["scope"]["policy_number"] for c in carriers)
    assert all(c["scope"]["line_printed"] for c in carriers)


def test_the_store_is_additive_and_the_plain_fact_is_untouched():
    """D19: `merged_facts[key]` keeps its shape so all existing reads stay
    valid. The store is a PARALLEL structure, under a private key."""
    mf = {"coverage_lines": [GL], "carrier_name": "EMC Property & Casualty Company"}
    es._build_scoped_fact_store(mf)
    assert mf["carrier_name"] == "EMC Property & Casualty Company"
    assert mf["_scoped"]["carrier_name"][0]["value"] == "EMC Prop & Cas Co"


def test_an_unmappable_line_is_never_stored():
    """Unknown terminology gets no opinion (client 1.7 / D9)."""
    mf = _store([{"line": "Widget Protection", "carrier": "Acme",
                  "policy_number": "W-1"}])
    assert "_scoped" not in mf


@pytest.mark.parametrize("lines", [None, [], "text", 42, [None, 42], [{}]])
def test_an_unreadable_line_list_leaves_no_store_and_never_raises(lines):
    mf = {"coverage_lines": lines}
    es._build_scoped_fact_store(mf)
    assert "_scoped" not in mf


def test_a_line_with_no_value_for_a_fact_contributes_nothing():
    mf = _store([{"line": "Commercial General Liability", "policy_number": "X-1"}])
    assert "carrier_name" not in mf["_scoped"]
    assert mf["_scoped"]["policy_number"][0]["value"] == "X-1"


def test_the_store_is_rebuilt_not_appended_on_a_second_pass():
    mf = _store([GL])
    es._build_scoped_fact_store(mf)
    assert len(mf["_scoped"]["carrier_name"]) == 1


# ── 2. The behaviour it exists for ───────────────────────────────────────────

def _assess(docs, lines):
    return assess_underwriting_consistency(docs, _store(lines), {})


def _row(out, key):
    return next((f for f in out["fields"] if f["fact_key"] == key), None)


def test_two_carriers_on_DIFFERENT_lines_are_scoped_not_a_conflict():
    """THE CLIENT'S OWN WORKED EXAMPLE - "GL carrier and Auto carrier may
    legitimately differ". Note the abbreviated `EMC Prop & Cas Co` and the full
    `EMC Property & Casualty Company` are ONE carrier; before C1b the variant
    spelling could not find its scope and this row was a false conflict."""
    docs = [_doc("1_dec.pdf", "dec_page", carrier_name=None,
                 coverage_lines=[GL, AUTO, UMB]),
            _doc("2_coi.pdf", "certificate",
                 carrier_name="EMC Property & Casualty Company",
                 coverage_lines=[GL])]
    row = _row(_assess(docs, [GL, AUTO, UMB]), "carrier_name")
    assert row["status"] == "scoped", row.get("conflict_reason")
    assert not row["review_required"]
    scopes = {tuple(v["scope"]) for v in row["values"]}
    assert ("general_liab",) in scopes
    assert any("auto" in s for s in scopes)


def test_two_carriers_on_the_SAME_line_stay_a_conflict():
    """D-1. Travelers and EMC both writing General Liability in one period is
    a real disagreement, and the reason has to say which line."""
    docs = [_doc("1_dec.pdf", "dec_page", carrier_name=None,
                 coverage_lines=[GL, AUTO]),
            _doc("6_conf.pdf", "dec_page", carrier_name=None,
                 coverage_lines=[GL_RIVAL])]
    row = _row(_assess(docs, [GL, AUTO, GL_RIVAL]), "carrier_name")
    assert row["status"] == "conflict"
    assert "same coverage line" in (row["conflict_reason"] or "")


def test_the_umbrella_gate_still_survives_the_stored_scope():
    """THE GATE. `umbrella_limit` is not a line-scoped fact, so the store has
    no entry for it and it can never be scoped into silence - B14, which is
    the bug that silenced the client's $3M-vs-$1M conflict on run 1."""
    mf = _store([GL, AUTO, UMB])
    assert "umbrella_limit" not in (mf.get("_scoped") or {})


def test_a_package_with_no_store_behaves_exactly_as_before():
    """Every pre-C1b session, and any package with no coverage_lines. The
    legacy character-keyed path still runs; nothing regresses to worse."""
    docs = [_doc("a.pdf", "dec_page", carrier_name="Carrier One"),
            _doc("b.pdf", "dec_page", carrier_name="Carrier Two")]
    out = assess_underwriting_consistency(docs, {}, {})
    row = _row(out, "carrier_name")
    assert row["status"] == "conflict"       # no evidence to scope on


# ── 3. ANTI-ROT ──────────────────────────────────────────────────────────────

def test_the_two_column_maps_cannot_drift():
    """The store is BUILT in extraction_service and READ in
    underwriting_consistency. Two copies of "which column states this fact"
    would silently half-scope a package."""
    from services.underwriting_consistency import (
        _LINE_SCOPED_FACT_COLUMN, LINE_SCOPED_FACT_KEYS,
    )
    assert es._SCOPED_FACT_COLUMNS == _LINE_SCOPED_FACT_COLUMN
    assert set(es._SCOPED_FACT_COLUMNS) == set(LINE_SCOPED_FACT_KEYS)


def test_the_store_is_consulted_before_the_character_keyed_path():
    """Order is the whole point: `owners_of` attributes a value by its own
    characters, so consulting it first would re-introduce the defect the store
    exists to remove."""
    import inspect
    from services import underwriting_consistency as uc
    src = inspect.getsource(uc.assess_underwriting_consistency)
    i_store = src.index("_scope_from_store(")
    i_legacy = src.index("_scope_values(fact_key")
    assert i_store < i_legacy


def test_the_scoped_key_is_private_so_no_consumer_treats_it_as_a_fact():
    """Every fact loop skips `_`-prefixed keys; a public name would make the
    store itself look like a reconcilable field."""
    assert es.SCOPED_FACTS_KEY.startswith("_")


# ── 4. The picker's OWN grouping must not use the carrier family map ────────
# LIVE RUN A, 2026-08-23: a Carrier CONFLICT appeared on a package with three
# carriers on three DIFFERENT lines, reason "two policies on the same coverage
# line". Cause: `_normalize` sent an identity value to `normalize_value`, which
# dispatches a carrier to `normalize_carrier` - the curated alias map that folds
# "EMC Property & Casualty Company" and "Employers Mutual Casualty Company" BOTH
# to "emc". The merged group then owned the GL line AND the Auto line and
# collided with itself.
#
# D10 records this exact rule for the comparison door: "the coarse normalisers
# fold two real carriers into one token; that is Round 10 fix 46 and it must not
# come back one layer up." It had come back one layer up.

def test_two_real_carriers_never_share_a_picker_group():
    """Round 10 fix 46, at the picker's own grouping layer."""
    from services.underwriting_consistency import _normalize
    emc = _normalize("EMC Property & Casualty Company", "identity", "carrier_name")
    mutual = _normalize("Employers Mutual Casualty Company", "identity", "carrier_name")
    assert emc and mutual and emc != mutual, (
        "two distinct legal entities collapsed to one grouping key before the "
        "comparison door was ever consulted")


def test_one_carrier_spelled_two_ways_shares_a_picker_group():
    """The other direction - abbreviations must still group together, which is
    what makes splitting on the strict key safe."""
    from services.underwriting_consistency import _normalize
    a = _normalize("EMC Prop & Cas Co", "identity", "carrier_name")
    b = _normalize("EMC Property & Casualty Company", "identity", "carrier_name")
    assert a == b


def test_three_carriers_on_three_lines_are_scoped_not_a_conflict():
    """THE LIVE RUN A CASE, end to end."""
    lines = [
        {"line": "Commercial General Liability", "carrier": "EMC Prop & Cas Co",
         "policy_number": "BBC7263-26"},
        {"line": "Commercial Automobile Liability",
         "carrier": "Employers Mutual Cas Co", "policy_number": "6E7-40-02---26"},
        {"line": "Professional Liability",
         "carrier": "Hartford Fire Insurance Company", "policy_number": "PL-99881-26"},
    ]
    docs = [_doc("1_dec.pdf", "dec_page",
                 carrier_name="EMC Property & Casualty Company",
                 coverage_lines=lines)]
    row = _row(_assess(docs, lines), "carrier_name")
    assert row["status"] == "scoped", row.get("conflict_reason")
    scopes = sorted(tuple(v["scope"]) for v in row["values"])
    assert ("general_liab",) in scopes
    assert ("professional",) in scopes


def test_an_applicant_name_still_groups_by_the_strict_key():
    """The rule is about ENTITY names generally, not carriers specially."""
    from services.underwriting_consistency import _normalize
    a = _normalize("ORBIN CONTRACTING LLC", "identity", "applicant_name")
    b = _normalize("Orbin Contracting, L.L.C.", "identity", "applicant_name")
    assert a == b
