"""SYS-06 - carrier and policy number stay LINE-SPECIFIC.

Client, 1 Sep live test:

    "Maintain the relationship Line of Business -> Carrier -> NAIC -> Policy
     Number -> Effective Date -> Expiration Date -> Source. Compare values only
     within the same line/policy context. When the producer confirms a mapping,
     apply it only to the applicable line or lines and populate the
     corresponding forms from that line-specific record. Different policy
     numbers across different lines are valid and must not create a conflict by
     themselves."

THE DEFECT, reproduced from the client's OWN regression table with clean data:
`_coverage_line_dedup_keys` identifies a `coverage_lines` row as (line, policy
number with punctuation stripped), so the dec page's `BBC7263 - 26` and the
certificate's `BBC7263` - ONE General Liability policy printed two ways -
survived the union as TWO rows on one line, and the picker reported "two
policies on the same coverage line in one submission". Meanwhile the codebase
already knew they were one contract in two other places, neither of which was
consulted.

THE ADVERSARIAL CASES ARE FIRST IN THIS FILE, deliberately (H1-F's standing
rule). The whole risk of this change is folding too much: two genuinely
different policies on one coverage line is defect D-1 and the client's own
review trigger, and it must survive every fold below.
"""
import copy
import pathlib

import pytest

from services import extraction_service as es
from services import pdf_service as ps
from services import underwriting_consistency as uc
from services.fact_comparison import same_policy_contract, policy_contract_groups

BACKEND = pathlib.Path(__file__).resolve().parents[1]


# ── The client's regression table, verbatim ─────────────────────────────────
DEC_ROWS = [
    {"line": "Commercial General Liability", "carrier": "EMC Property & Casualty Company",
     "naic": "25186", "policy_number": "BBC7263 - 26", "premium": "$4,000",
     "effective_date": "07/15/2025", "expiration_date": "07/15/2026"},
    {"line": "Commercial Auto", "carrier": "Employers Mutual Casualty Company",
     "naic": "21415", "policy_number": "6E7-40-02---26", "premium": "$2,991",
     "effective_date": "07/15/2025", "expiration_date": "07/15/2026"},
    {"line": "Commercial Umbrella", "carrier": "Employers Mutual Casualty Company",
     "naic": "21415", "policy_number": "6J7-40-02---26", "premium": "$1,500",
     "effective_date": "07/15/2025", "expiration_date": "07/15/2026"},
    {"line": "Commercial Inland Marine", "carrier": "Employers Mutual Casualty Company",
     "naic": "21415", "policy_number": "6C7-40-02---26", "premium": "$900",
     "effective_date": "07/15/2025", "expiration_date": "07/15/2026"},
]
# The same four policies as a certificate prints them: no premiums, and the
# numbers without their separated term marker.
COI_ROWS = [
    {"line": "General Liability", "carrier": "EMC Property & Casualty Company",
     "naic": "25186", "policy_number": "BBC7263"},
    {"line": "Automobile Liability", "carrier": "Employers Mutual Casualty Company",
     "naic": "21415", "policy_number": "6E74002"},
    {"line": "Umbrella Liability", "carrier": "Employers Mutual Casualty Company",
     "naic": "21415", "policy_number": "6J74002"},
]

# TWO REAL POLICIES ON ONE LINE. This is D-1 and the client's own review rule.
RIVAL_GL = [
    {"line": "Commercial General Liability", "carrier": "EMC Property & Casualty Company",
     "naic": "25186", "policy_number": "BBC7263-26", "premium": "$4,000"},
    {"line": "Commercial General Liability", "carrier": "Travelers Property Casualty Company",
     "naic": "36161", "policy_number": "GL-4471102-26", "premium": "$5,200"},
    {"line": "Commercial Auto", "carrier": "Employers Mutual Casualty Company",
     "naic": "21415", "policy_number": "6E7-40-02---26", "premium": "$2,991"},
]


def _doc(fn, dt, rows, **facts):
    f = {"coverage_lines": list(rows)}
    f.update(facts)
    return {"doc_id": fn, "filename": fn, "doc_type": dt, "facts": f, "text": ""}


def _merged(rows, docs=None):
    mf = {"coverage_lines": list(rows)}
    es._build_scoped_fact_store(mf, docs)
    return mf


def _row(out, key):
    return next((f for f in out["fields"] if f["fact_key"] == key), None)


def _union(dec, coi):
    return es._union_list_fact("coverage_lines", dec, coi)


# ════════════════════════════════════════════════════════════════════════════
# 1. ADVERSARIAL FIRST - what the fold must NEVER do
# ════════════════════════════════════════════════════════════════════════════

def test_two_real_policies_on_one_line_are_never_folded():
    """D-1. EMC's GL and Travelers' GL are two contracts, not two printings."""
    assert same_policy_contract("BBC7263-26", "GL-4471102-26") is False
    recs = es._build_line_records({"coverage_lines": RIVAL_GL})
    gl = [r for r in recs if r["line"] == "general_liab"]
    assert len(gl) == 2, [r["id"] for r in recs]


def test_two_real_policies_on_one_line_still_raise_a_conflict():
    """The whole point of scoping is that it is NOT a blanket amnesty."""
    docs = [_doc("dec.pdf", "dec_page", RIVAL_GL)]
    out = uc.assess_underwriting_consistency(docs, _merged(RIVAL_GL, docs), {})
    row = _row(out, "carrier_name")
    assert row["status"] == "conflict"
    assert "same coverage line" in (row["conflict_reason"] or "")


def test_the_conflict_reason_names_the_line_in_dispute():
    """The producer is told WHICH line to look at, not handed the package."""
    docs = [_doc("dec.pdf", "dec_page", RIVAL_GL)]
    out = uc.assess_underwriting_consistency(docs, _merged(RIVAL_GL, docs), {})
    row = _row(out, "carrier_name")
    assert "general liab" in (row["conflict_reason"] or "")
    assert row["conflict_scope"] == ["general_liab"]


def test_a_legacy_store_with_no_record_ids_never_folds():
    """THE BUG THIS FILE'S FIRST DRAFT SHIPPED, caught by an existing test.

    A store written before SYS-06 carries `scope.line` but no `scope.record`.
    Falling back to the line as the record id makes every value on a line look
    like one contract, which silently folded two real carriers into a single
    candidate and deleted the conflict. Absence of a record id is not evidence
    of a shared contract (Principle 3)."""
    legacy = {"carrier_name": [
        {"value": "Alpha Insurance Company",
         "scope": {"line": "general_liab", "policy_number": "A1"}},
        {"value": "Beta Insurance Company",
         "scope": {"line": "general_liab", "policy_number": "B2"}},
    ]}
    values = [{"normalized": "alpha", "display": "Alpha Insurance Company", "sources": []},
              {"normalized": "beta", "display": "Beta Insurance Company", "sources": []}]
    assert len(uc._merge_by_line_record("carrier_name", values, {"_scoped": legacy})) == 2
    scoped, reason, _ = uc._scope_from_store("carrier_name", values, {"_scoped": legacy})
    assert scoped is False and reason and "same coverage line" in reason


def test_digits_that_run_together_are_two_policies():
    """`POL123` / `POL12345`: no separated term marker, so no fold. This one
    condition is what keeps the prefix rule from eating real contracts."""
    assert same_policy_contract("POL123", "POL12345") is False
    assert same_policy_contract("BBC7263", "BBC726399") is False


def test_a_form_number_is_never_a_policy_number():
    """`IM 7100 06 04` names the coverage WORDING. As a policy number it
    manufactures a phantom second policy on the Inland Marine line - one of the
    nine candidates in the client's screenshot."""
    rows = DEC_ROWS + [{"line": "Commercial Inland Marine",
                        "carrier": "Employers Mutual Casualty Company",
                        "policy_number": "IM 7100 06 04"}]
    recs = es._build_line_records({"coverage_lines": rows})
    im = [r for r in recs if r["line"] == "inland_marine"]
    assert len(im) == 1
    assert im[0]["policy_number"] == "6C7-40-02---26"
    assert es._looks_like_a_form_number("IM 7100 06 04")
    assert not es._looks_like_a_form_number("6C7-40-02---26")


def test_a_short_but_real_policy_number_keeps_its_scope():
    """The narrow form-number test must NOT be the broader
    `_looks_like_a_policy_number`, which also rejects anything under four
    characters. `X-1` is short and real."""
    mf = _merged([{"line": "Commercial General Liability", "policy_number": "X-1"}])
    assert mf["_scoped"]["policy_number"][0]["value"] == "X-1"


# ════════════════════════════════════════════════════════════════════════════
# 2. THE DOOR (L1) - one answer to "are these the same policy?"
# ════════════════════════════════════════════════════════════════════════════

@pytest.mark.parametrize("a,b", [
    ("BBC7263 - 26", "BBC7263"),
    ("6E7-40-02---26", "6E74002"),
    ("6J7-40-02---26", "6J74002"),
    ("bbc7263 - 26", "BBC7263"),
])
def test_one_policy_printed_two_ways_is_one_policy(a, b):
    assert same_policy_contract(a, b) is True
    assert same_policy_contract(b, a) is True


@pytest.mark.parametrize("a,b", [(None, "BBC7263"), ("", ""), ("  ", "BBC7263"),
                                 (42, "BBC7263"), ("BBC7263", {})])
def test_the_door_never_raises_on_junk(a, b):
    assert same_policy_contract(a, b) is False


def test_contract_grouping_is_order_independent():
    """The merge sees documents in upload order. The same package uploaded the
    other way round must produce the same grouping."""
    v = ["BBC7263 - 26", "6E7-40-02---26", "6J7-40-02---26", "6C7-40-02---26",
         "BBC7263", "6E74002", "6J74002"]
    fwd = policy_contract_groups(v)
    rev = policy_contract_groups(list(reversed(v)))
    as_values = lambda gs, vals: sorted(tuple(sorted(vals[i] for i in g)) for g in gs)
    assert as_values(fwd, v) == as_values(rev, list(reversed(v)))
    assert len(fwd) == 4


def test_the_stamping_layer_delegates_to_the_door():
    """ANTI-ROT. `pdf_service._same_policy_contract` was the third answer to
    this question and the weakest one decided the picker's behaviour. It is now
    a delegation; if the delegation is removed the two can drift again."""
    import inspect
    src = inspect.getsource(ps._same_policy_contract)
    assert "fact_comparison import same_policy_contract" in src, (
        "the stamping layer holds a second implementation of 'is this the same "
        "policy?' again - route it through services.fact_comparison")


def test_the_delegation_is_behaviour_identical():
    """The in-file fallback is the original body. Sweep both."""
    vals = ["BBC7263 - 26", "BBC7263", "6E7-40-02---26", "6E74002", "POL123",
            "POL12345", "GL-4471102-26", "IM 7100 06 04", "", "x", None]
    for a in vals:
        for b in vals:
            assert ps._same_policy_contract(a, b) == same_policy_contract(a, b), (a, b)


# ════════════════════════════════════════════════════════════════════════════
# 3. THE LINE RECORD (L2) - the client's chain
# ════════════════════════════════════════════════════════════════════════════

def test_the_union_of_eight_rows_is_four_policies():
    """The client's package: a dec page and a certificate describing the SAME
    four policies. Eight `coverage_lines` rows, four contracts."""
    rows = _union(DEC_ROWS, COI_ROWS)
    assert len(rows) > 4, "the union itself is expected to keep both printings"
    recs = es._build_line_records({"coverage_lines": rows})
    assert sorted(r["line"] for r in recs) == [
        "auto", "general_liab", "inland_marine", "umbrella"]


def test_each_record_carries_the_whole_chain():
    """Line -> Carrier -> NAIC -> Policy Number -> Effective -> Expiration ->
    Source, which is the client's acceptance criterion stated as a structure."""
    docs = [_doc("2526 Package Policy.pdf", "dec_page", DEC_ROWS),
            _doc("CRS COI FIO.pdf", "certificate", COI_ROWS)]
    recs = es._build_line_records({"coverage_lines": _union(DEC_ROWS, COI_ROWS)}, docs)
    gl = next(r for r in recs if r["line"] == "general_liab")
    assert gl["carrier_name"] == "EMC Property & Casualty Company"
    assert gl["carrier_naic"] == "25186"
    assert gl["policy_number"] == "BBC7263 - 26"        # the fuller printing
    assert gl["effective_date"] == "07/15/2025"
    assert gl["expiration_date"] == "07/15/2026"
    assert gl["sources"] == ["2526 Package Policy.pdf", "CRS COI FIO.pdf"]


def test_a_certificate_row_corroborates_and_never_rivals():
    """A COI prints no premium, so it is `grants=False` to the stamper. It must
    not therefore become a second policy to the picker - same data, one
    verdict."""
    recs = es._build_line_records({"coverage_lines": _union(DEC_ROWS, COI_ROWS)})
    assert len([r for r in recs if r["line"] == "general_liab"]) == 1


def test_a_line_named_only_by_certificates_is_one_policy_not_three():
    """Three documents mentioning one unnumbered line is not evidence of three
    policies (Principle 3 - absence is not a value)."""
    rows = [{"line": "Commercial Crime", "carrier": "EMC"},
            {"line": "Crime", "carrier": "EMC"},
            {"line": "Commercial Crime Coverage", "carrier": "EMC"}]
    recs = es._build_line_records({"coverage_lines": rows})
    assert len(recs) == 1


def test_an_unmappable_line_produces_no_record():
    """Unknown terminology gets no opinion (client 1.7 / D9)."""
    mf = {"coverage_lines": [{"line": "Widget Protection", "carrier": "Acme",
                              "policy_number": "W-12345"}]}
    es._build_scoped_fact_store(mf)
    assert "_scoped" not in mf and "_line_records" not in mf


@pytest.mark.parametrize("lines", [None, [], "text", 42, [None, 42], [{}], [[]]])
def test_a_malformed_line_list_never_raises(lines):
    mf = {"coverage_lines": lines}
    es._build_scoped_fact_store(mf)
    assert "_scoped" not in mf and "_line_records" not in mf


def test_records_are_deterministic_across_row_order():
    a = es._build_line_records({"coverage_lines": _union(DEC_ROWS, COI_ROWS)})
    b = es._build_line_records({"coverage_lines": list(reversed(_union(DEC_ROWS, COI_ROWS)))})
    assert sorted(r["id"] for r in a) == sorted(r["id"] for r in b)


def test_the_scoped_store_is_derived_from_the_records():
    """One structure, one truth. Every `_scoped` entry must name a record that
    exists, or the picker is comparing against something nothing produced."""
    mf = _merged(_union(DEC_ROWS, COI_ROWS))
    ids = {r["id"] for r in mf["_line_records"]}
    for entries in mf["_scoped"].values():
        for e in entries:
            assert e["scope"]["record"] in ids


def test_the_store_keeps_its_documented_shape():
    """D19's readers look for line / line_printed / policy_number exactly where
    they have always been. The record id is ADDITIVE."""
    mf = _merged(DEC_ROWS)
    entry = mf["_scoped"]["carrier_name"][0]
    assert set(entry) == {"value", "scope"}
    assert {"line", "line_printed", "policy_number", "record"} == set(entry["scope"])


# ════════════════════════════════════════════════════════════════════════════
# 4. THE PICKER (L3) - compare within the line/policy context
# ════════════════════════════════════════════════════════════════════════════

def _client_assessment(confirmations=None):
    docs = [_doc("2526 Package Policy.pdf", "dec_page", DEC_ROWS,
                 policy_number="BBC7263 - 26",
                 carrier_name="Employers Mutual Casualty Company",
                 carrier_naic="21415"),
            _doc("CRS COI FIO.pdf", "certificate", COI_ROWS,
                 policy_number="BBC7263",
                 carrier_name="EMC Property & Casualty Company",
                 carrier_naic="25186")]
    merged = _merged(_union(DEC_ROWS, COI_ROWS), docs)
    return uc.assess_underwriting_consistency(docs, merged, confirmations or {})


@pytest.mark.parametrize("key", ["policy_number", "carrier_name", "carrier_naic"])
def test_the_clients_package_raises_no_conflict(key):
    """THE REPORTED DEFECT. Every one of these was a package-wide "pick one"."""
    row = _row(_client_assessment(), key)
    assert row is not None, f"{key} is not reported at all"
    assert row["status"] == "scoped", row.get("conflict_reason")
    assert row["review_required"] is False


def test_every_policy_number_is_shown_against_its_own_line():
    row = _row(_client_assessment(), "policy_number")
    got = {v["display"]: tuple(v["scope"]) for v in row["values"]}
    assert got == {
        "BBC7263 - 26":   ("general_liab",),
        "6E7-40-02---26": ("auto",),
        "6J7-40-02---26": ("umbrella",),
        "6C7-40-02---26": ("inland_marine",),
    }


def test_the_gl_carrier_and_naic_stay_with_the_gl_line():
    """The client's other half: GL uses a different legal carrier/NAIC."""
    car = _row(_client_assessment(), "carrier_name")
    naic = _row(_client_assessment(), "carrier_naic")
    assert {v["display"]: tuple(v["scope"]) for v in car["values"]}[
        "EMC Property & Casualty Company"] == ("general_liab",)
    assert {v["display"]: tuple(v["scope"]) for v in naic["values"]}[
        "25186"] == ("general_liab",)


def test_the_line_record_table_reaches_the_producer():
    """The relationship is emitted, not left to be inferred from a value list."""
    row = _row(_client_assessment(), "policy_number")
    recs = {r["line"]: r for r in row["line_records"]}
    assert set(recs) == {"general_liab", "auto", "umbrella", "inland_marine"}
    assert recs["auto"]["carrier_naic"] == "21415"
    assert recs["auto"]["sources"]


def test_a_package_with_no_store_behaves_exactly_as_before():
    docs = [_doc("a.pdf", "dec_page", [], carrier_name="Carrier One"),
            _doc("b.pdf", "dec_page", [], carrier_name="Carrier Two")]
    row = _row(uc.assess_underwriting_consistency(docs, {}, {}), "carrier_name")
    assert row["status"] == "conflict"


def test_a_one_line_question_never_offers_another_lines_value():
    """LIVE RUN B, 2026-09-04 - found on screen, not in review.

    The GL question listed THREE policy numbers, including the AUTO one, under
    a button reading "Confirm for general liab". One click would have written
    the Auto policy number onto the General Liability line - the exact
    mis-assignment SYS-06 exists to prevent, offered as an option."""
    docs = [_doc("dec.pdf", "dec_page", RIVAL_GL)]
    out = uc.assess_underwriting_consistency(docs, _merged(RIVAL_GL, docs), {})
    row = _row(out, "policy_number")
    assert row["status"] == "conflict"
    assert row["conflict_scope"] == ["general_liab"]
    offered = {v["display"] for v in row["values"]}
    assert offered == {"BBC7263-26", "GL-4471102-26"}, offered
    assert "6E7-40-02---26" not in offered, (
        "the Auto policy number is a candidate answer to a General Liability "
        "question")


def test_the_restriction_never_collapses_a_real_conflict():
    """It refuses to act unless at least two candidates survive, so it can
    never turn a genuine disagreement into a silent single value."""
    values = [{"display": "Alpha", "normalized": "alpha", "sources": []},
              {"display": "Beta", "normalized": "beta", "sources": []}]
    # No document states either value on the disputed line -> no opinion.
    assert uc._restrict_to_conflicted_lines(
        "carrier_name", values, {"general_liab"}, []) == values


def _noisy(extra_dec=None, dec_scalars=None, extra_coi=None):
    d1 = {"coverage_lines": DEC_ROWS + (extra_dec or [])}
    d1.update(dec_scalars or {})
    docs = [{"doc_id": "d1", "filename": "dec.pdf", "doc_type": "dec_page",
             "text": "", "facts": d1},
            {"doc_id": "d2", "filename": "coi.pdf", "doc_type": "certificate",
             "text": "", "facts": {"coverage_lines": COI_ROWS + (extra_coi or [])}}]
    mf, _ = es.merge_facts(docs, docs[0])
    return uc.assess_underwriting_consistency(docs, mf, {})


def test_one_unplaceable_value_does_not_unscope_the_whole_field():
    """STRESS TEST, 2026-09-04 - the shapes the client's REAL package carried
    and my clean kit did not.

    The all-or-nothing gate handed the entire field to the LEGACY
    character-keyed path the moment one value could not be placed. Measured:
    every chip then printed a POLICY-NUMBER TOKEN ('bbc7263 / bbc726326')
    instead of a coverage line, and the unplaceable value was listed as a real
    policy."""
    row = _row(_noisy(extra_dec=[{
        "line": "Commercial Inland Marine",
        "carrier": "Employers Mutual Casualty Company",
        "policy_number": "IM 7100 06 04"}]), "policy_number")
    assert row["status"] == "scoped", row.get("conflict_reason")
    placed = {v["display"]: tuple(v["scope"]) for v in row["values"] if v["scope"]}
    assert placed == {"BBC7263 - 26": ("general_liab",),
                      "6E7-40-02---26": ("auto",),
                      "6J7-40-02---26": ("umbrella",),
                      "6C7-40-02---26": ("inland_marine",)}, placed
    # ...and the scope is a COVERAGE LINE, never a policy-number token.
    for v in row["values"]:
        for tok in v["scope"] or []:
            assert not tok[0].isdigit() and " " not in tok, (
                f"{tok!r} is a contract token, not a coverage line")


def test_a_package_scalar_no_line_states_never_forces_a_choice():
    """The worst measured shape: a package-level `policy_number` the lines do
    not state used to make the equivalence pass fold FOUR real policies into
    one candidate and ask the producer to choose between it and the scalar.
    Confirm the wrong one and that scalar becomes the GL box's value - the
    client's original complaint, reproduced by the fix meant to end it."""
    row = _row(_noisy(dec_scalars={"policy_number": "PKG-99999"}), "policy_number")
    assert row["status"] == "scoped", row.get("conflict_reason")
    displays = {v["display"] for v in row["values"]}
    for real in ("BBC7263 - 26", "6E7-40-02---26", "6J7-40-02---26", "6C7-40-02---26"):
        assert real in displays, f"{real} was folded away: {displays}"
    assert [v["scope"] for v in row["values"] if v["display"] == "PKG-99999"] == [[]]


def test_two_unplaceable_values_are_still_a_question():
    """Partial scoping is not amnesty. Two values competing for a slot nothing
    can identify is a real question - but about THEM, not about the lines the
    store placed correctly."""
    row = _row(_noisy(dec_scalars={"policy_number": "PKG-99999"},
                      extra_coi=[{"line": "Widget Protection", "carrier": "Acme",
                                  "policy_number": "ZZ-11111"}]), "policy_number")
    assert row["status"] == "conflict"
    assert "could not be matched to a coverage line" in (row["conflict_reason"] or "")
    assert {v["display"] for v in row["values"]} == {"PKG-99999", "ZZ-11111"}


def test_conflict_scope_is_empty_when_the_dispute_is_not_line_specific():
    """A non-line-specific disagreement must not acquire a scope it has not
    earned - the confirm would then be applied to one line by accident."""
    docs = [_doc("a.pdf", "dec_page", DEC_ROWS, applicant_name="Orbin Contracting LLC"),
            _doc("b.pdf", "dec_page", DEC_ROWS, applicant_name="Summit Mechanical Inc")]
    out = uc.assess_underwriting_consistency(docs, _merged(DEC_ROWS, docs), {})
    row = _row(out, "applicant_name")
    assert row["status"] == "conflict"
    assert row["conflict_scope"] == []


# ════════════════════════════════════════════════════════════════════════════
# 5. THE ANSWER (L4) - a confirmation carries its scope
# ════════════════════════════════════════════════════════════════════════════

def test_the_confirmation_key_round_trips():
    k = uc.scoped_confirmation_key("policy_number", "general_liab")
    assert k == "policy_number@general_liab"
    assert uc.parse_confirmation_key(k) == ("policy_number", "general_liab")
    assert uc.scoped_confirmation_key("policy_number", None) == "policy_number"
    assert uc.parse_confirmation_key("policy_number") == ("policy_number", None)


def test_a_scoped_confirmation_edits_only_its_own_line():
    conf = {uc.scoped_confirmation_key("carrier_name", "general_liab"):
            "EMC Property & Casualty Company"}
    out = uc.apply_confirmations({"coverage_lines": copy.deepcopy(RIVAL_GL)}, conf)
    by_line = {}
    for r in out["coverage_lines"]:
        if r.get("_set_aside"):
            continue                       # the rival policy, not relabelled
        by_line.setdefault(es._canon_line(r["line"]), set()).add(r["carrier"])
    assert by_line["general_liab"] == {"EMC Property & Casualty Company"}
    assert by_line["auto"] == {"Employers Mutual Casualty Company"}
    # 17 Sep 2026: the Travelers policy is SET ASIDE, never rewritten as EMC's.
    # Rewriting it printed EMC and EMC's NAIC beside Travelers' GL-4471102-26 -
    # a contract no document states.
    rival = next(r for r in out["coverage_lines"] if r.get("_set_aside"))
    assert rival["premium"] == "$5,200"
    assert rival["carrier"] is None and rival["naic"] is None and rival["policy_number"] is None
    assert not any(r.get("carrier") == "EMC Property & Casualty Company"
                   and r.get("policy_number") == "GL-4471102-26" for r in out["coverage_lines"])


def test_a_scoped_confirmation_never_becomes_the_package_scalar():
    """The client's "do not default a confirmed value to the GL package
    policy", as an assertion."""
    conf = {uc.scoped_confirmation_key("policy_number", "auto"): "6E7-40-02---26"}
    out = uc.apply_confirmations({"coverage_lines": copy.deepcopy(DEC_ROWS)}, conf)
    assert "policy_number" not in out


def test_a_bare_confirmation_still_writes_the_package_scalar():
    """Legacy path, byte-for-byte. Every confirmation stored before SYS-06 is
    a bare key and must keep meaning what it meant."""
    out = uc.apply_confirmations({"coverage_lines": copy.deepcopy(DEC_ROWS)},
                                 {"policy_number": "BBC7263 - 26"})
    assert out["policy_number"]["value"] == "BBC7263 - 26"
    assert out["policy_number"]["source"] == "user_confirmed"


def test_applying_a_scoped_confirmation_does_not_mutate_the_caller():
    """`apply_confirmations` shallow-copies. Editing a row in place would reach
    back into the session's stored facts."""
    rows = copy.deepcopy(RIVAL_GL)
    before = copy.deepcopy(rows)
    uc.apply_confirmations(
        {"coverage_lines": rows},
        {uc.scoped_confirmation_key("carrier_name", "general_liab"): "EMC Property & Casualty Company"})
    assert rows == before


def test_a_fact_that_is_not_line_scoped_cannot_be_confirmed_per_line():
    """One insured however many policies. Scoping `applicant_name` to a line
    would invent a relationship the package does not have."""
    out = uc.apply_confirmations(
        {"coverage_lines": copy.deepcopy(DEC_ROWS)},
        {uc.scoped_confirmation_key("applicant_name", "auto"): "Orbin Contracting LLC"})
    assert "applicant_name" not in out


def test_the_answered_question_does_not_come_back():
    """The candidates also come from each DOCUMENT's own facts, so without the
    rejected-candidate filter the producer is asked forever."""
    docs = [_doc("dec.pdf", "dec_page", RIVAL_GL)]
    conf = {uc.scoped_confirmation_key("carrier_name", "general_liab"):
            "EMC Property & Casualty Company",
            uc.scoped_confirmation_key("policy_number", "general_liab"): "BBC7263-26"}
    merged = uc.apply_confirmations(_merged(RIVAL_GL, docs), conf, docs=docs)
    out = uc.assess_underwriting_consistency(docs, merged, conf)
    row = _row(out, "carrier_name")
    assert row["status"] != "conflict", row.get("conflict_reason")
    assert row["confirmed_scopes"]["general_liab"] == "EMC Property & Casualty Company"


def test_a_confirmed_carrier_brings_its_own_naic():
    """RC1, reopened by the scoped-confirm path and closed again.

    The producer answers three separate cards. Confirming carrier = Redwood
    Basin for General Liability while picking Trinity Ridge's NAIC on the NAIC
    card used to write BOTH onto the GL row - a company beside an identifier
    belonging to a different company, on a signed application. The client's
    rule: carrier and NAIC move as a MATCHED PAIR."""
    K = uc.scoped_confirmation_key
    facts = uc.apply_confirmations(
        {"coverage_lines": copy.deepcopy(RIVAL_GL)},
        {K("carrier_name", "general_liab"): "EMC Property & Casualty Company",
         K("carrier_naic", "general_liab"): "36161"})       # Travelers' NAIC
    gl = dict(facts); gl["_form_id"] = "ACORD_126"
    assert ps._deterministic_map("Insurer_FullName_A", gl) == "EMC Property & Casualty Company"
    assert ps._deterministic_map("Insurer_NAICCode_A", gl) == "25186", (
        "the confirmed carrier was stamped beside another carrier's NAIC")


def test_the_naic_follows_the_carrier_without_being_asked():
    """The pair is read from the document, so answering the carrier card is
    enough - the producer does not have to answer the NAIC card at all."""
    facts = uc.apply_confirmations(
        {"coverage_lines": copy.deepcopy(RIVAL_GL)},
        {uc.scoped_confirmation_key("carrier_name", "general_liab"):
         "Travelers Property Casualty Company"})
    gl = dict(facts); gl["_form_id"] = "ACORD_126"
    assert ps._deterministic_map("Insurer_NAICCode_A", gl) == "36161"


def test_an_unpairable_naic_is_refused_not_guessed():
    """A carrier the documents do not name has no NAIC to pair with. Blank or
    stale is recoverable; a wrong pair on a legal form is not."""
    edits = uc._pair_naic_with_its_carrier(
        copy.deepcopy(RIVAL_GL),
        [("carrier_name", "general_liab", "Some Carrier Nobody Printed"),
         ("carrier_naic", "general_liab", "99999")])
    assert ("carrier_naic", "general_liab", "99999") not in edits
    assert not [e for e in edits if e[0] == "carrier_naic"]


def test_a_scoped_confirmation_reaches_that_lines_form_and_no_other():
    """End to end, through the REAL stamper. The client's "populate the
    corresponding forms from that line-specific record"."""
    docs = [_doc("dec.pdf", "dec_page", RIVAL_GL)]
    conf = {uc.scoped_confirmation_key("carrier_name", "general_liab"):
            "Travelers Property Casualty Company",
            uc.scoped_confirmation_key("policy_number", "general_liab"): "GL-4471102-26"}
    facts = uc.apply_confirmations(_merged(RIVAL_GL, docs), conf, docs=docs)

    gl = dict(facts); gl["_form_id"] = "ACORD_126"
    assert ps._deterministic_map("Policy_PolicyNumberIdentifier_A", gl) == "GL-4471102-26"
    assert ps._deterministic_map("Insurer_FullName_A", gl) == "Travelers Property Casualty Company"

    auto = dict(facts); auto["_form_id"] = "ACORD_127"
    assert ps._deterministic_map("Policy_PolicyNumberIdentifier_A", auto) == "6E7-40-02---26"
    assert ps._deterministic_map("Insurer_FullName_A", auto) == "Employers Mutual Casualty Company"


def test_the_store_is_rebuilt_after_a_scoped_confirmation():
    """`_line_records` is DERIVED from `coverage_lines`. Leaving it stale would
    keep the picker comparing against the value the producer just corrected."""
    docs = [_doc("dec.pdf", "dec_page", RIVAL_GL)]
    conf = {uc.scoped_confirmation_key("carrier_name", "general_liab"):
            "EMC Property & Casualty Company"}
    out = uc.apply_confirmations(_merged(RIVAL_GL, docs), conf, docs=docs)
    gl = [r for r in out["_line_records"] if r["line"] == "general_liab"]
    assert {r["carrier_name"] for r in gl} == {"EMC Property & Casualty Company"}


# ════════════════════════════════════════════════════════════════════════════
# 6. THE REGISTRY (L5) and ANTI-ROT
# ════════════════════════════════════════════════════════════════════════════

@pytest.mark.parametrize("key", ["policy_number", "carrier_naic"])
def test_the_rest_of_the_chain_is_curated(key):
    """An auto-discovered field is DROPPED from the payload when its status is
    "scoped", so the per-line mapping was invisible on a healthy package."""
    assert key in uc.RECONCILABLE_FIELDS
    assert uc.RECONCILABLE_FIELDS[key]["kind"] == "identity"


@pytest.mark.parametrize("key", ["policy_number", "carrier_naic"])
def test_the_curated_chain_fields_are_never_text_scanned(key):
    """Neither has a checkable shape. A bare "4-6 digits" NAIC pattern would
    capture any five-digit number in prose."""
    assert uc._scan_shape(key, uc.RECONCILABLE_FIELDS[key]) is None
    assert key in uc._TEXT_SCAN_EXEMPT_FIELDS


def test_a_store_that_predates_a_fact_does_not_half_scope_the_package():
    """FOUND BY THE FULL SUITE, not by review (`test_r03_multi_insurer_
    documents_raise_no_consistency_conflict`).

    `carrier_naic` was invisible to the picker before SYS-06 - nothing writes
    it as a scalar, so auto-discovery never saw it - and a stored scope written
    before it was curated has no entries for it. Curating it then made a
    legitimately three-carrier package report a NAIC conflict, while the DATA
    had said one NAIC per line all along. A store that covers only part of the
    chain must fall back to the records, not to no opinion at all."""
    lines = [
        {"line": "Commercial General Liability", "carrier": "EMC Property & Casualty",
         "naic": "25186", "policy_number": "BBC7263", "premium": "5,000"},
        {"line": "Business Auto", "carrier": "Employers Mutual Casualty",
         "naic": "21415", "policy_number": "6E7-40-02---26", "premium": "2,991"},
        {"line": "Commercial Liability Umbrella", "carrier": "EMCASCO Insurance Company",
         "naic": "21407", "policy_number": "6J7-40-02---26", "premium": "1,200"},
    ]
    # A pre-SYS-06 store: carrier_name only, and no record ids.
    legacy_store = {"carrier_name": [
        {"value": e["carrier"], "scope": {"line": e["line"], "policy": e["policy_number"]}}
        for e in lines]}
    docs = [{"doc_id": f"d{i}", "filename": f"dec_{i}.pdf", "doc_type": "dec_page",
             "text": "", "facts": {"carrier_name": e["carrier"], "coverage_lines": [e]}}
            for i, e in enumerate(lines, start=1)]
    out = uc.assess_underwriting_consistency(
        docs, {"coverage_lines": lines, "_scoped": legacy_store}, {})
    assert out["conflict_count"] == 0, [
        (f["fact_key"], f["conflict_reason"]) for f in out["fields"]
        if f["status"] == "conflict"]
    assert _row(out, "carrier_naic")["status"] == "scoped"


def test_a_stored_entry_always_wins_over_a_derived_one():
    """The fallback is gap-filling only. If it could override a stored scope it
    would silently change how every existing session is compared."""
    lines = [{"line": "Commercial General Liability", "carrier": "Alpha",
              "policy_number": "A1", "premium": "1"},
             {"line": "Commercial General Liability", "carrier": "Beta",
              "policy_number": "B2", "premium": "1"}]
    stored = {"carrier_name": [{"value": "Alpha", "scope": {"line": "general_liab"}},
                               {"value": "Beta", "scope": {"line": "general_liab"}}]}
    entries = uc._store_entries("carrier_name", {"coverage_lines": lines, "_scoped": stored})
    assert entries == stored["carrier_name"]
    assert all("record" not in e["scope"] for e in entries)


def test_the_builder_and_the_reader_agree_on_the_record_key():
    """ANTI-ROT. The record id is written in `extraction_service` and read in
    `underwriting_consistency`; a rename on one side would silently return the
    picker to line-level comparison, which is the defect."""
    import inspect
    assert '"record":        rec["id"]' in inspect.getsource(es._build_scoped_fact_store)
    assert 'scope.get("record")' in inspect.getsource(uc._scope_of_group)


# ════════════════════════════════════════════════════════════════════════════
# 7. THE FORM'S IDENTITY IS ITS OWN LINE'S (live run A, 2026-09-04)
# ════════════════════════════════════════════════════════════════════════════

CRIME_DEC = {"line": "Crime", "carrier": "Employers Mutual Casualty Company",
             "naic": "21415", "policy_number": "CR-4471", "premium": "$310",
             "effective_date": "07/15/2025", "expiration_date": "07/15/2026"}


def _live_merged():
    """The client's two-document shape, through the REAL merge.

    The Crime line carries a PREMIUM on the dec side deliberately: a
    certificate row prints none, so it is `grants=False` and cannot on its own
    put a line on a form (`_line_entry_grants_coverage`). The first draft of
    this helper put Crime on the certificate only and the 141 assertion failed
    for that reason - the FIXTURE was wrong, not the mapping."""
    docs = [_doc("A1.pdf", "dec_page", DEC_ROWS + [CRIME_DEC]),
            _doc("A2.pdf", "certificate", COI_ROWS + [
                {"line": "Crime", "carrier": "Employers Mutual Casualty Company",
                 "naic": "21415", "policy_number": "CR-4471"}])]
    mf, _ = es.merge_facts(docs, docs[0])
    return mf


def test_the_certificate_prints_its_policy_numbers():
    """LIVE RUN A - the ACORD 25's ENTIRE policy-number column shipped blank.

    `_resolve_current_policy_line_cell` saw `BBC7263 - 26` (dec) and `BBC7263`
    (certificate) on the General Liability line, correctly refused to choose
    between two policy numbers, and blanked the cell. They are ONE contract -
    the package knew it, and this resolver was the last identity site not
    asking the door. The result was a certificate form that could not state the
    certificate's own policy numbers."""
    facts = _live_merged(); facts["_form_id"] = "ACORD_25"
    assert ps._deterministic_map(
        "Policy_GeneralLiability_PolicyNumberIdentifier_A", facts) == "BBC7263 - 26"
    assert ps._deterministic_map(
        "Policy_AutomobileLiability_PolicyNumberIdentifier_A", facts) == "6E7-40-02---26"
    assert ps._deterministic_map(
        "Policy_ExcessLiability_PolicyNumberIdentifier_A", facts) == "6J7-40-02---26"


def test_the_fullest_printing_is_the_one_that_prints():
    """A certificate holder should see `BBC7263 - 26`, not the stub."""
    assert ps._fold_policy_printings({"BBC7263", "BBC7263 - 26"}) == {"BBC7263 - 26"}
    assert ps._fold_policy_printings({"6E74002", "6E7-40-02---26"}) == {"6E7-40-02---26"}


def test_two_real_policies_are_still_refused_by_the_certificate_cell():
    """The resolver must keep refusing to CHOOSE. Folding printings of one
    contract is not the same as picking between two contracts."""
    assert ps._fold_policy_printings(
        {"BBC7263-26", "GL-4471102-26"}) == {"BBC7263-26", "GL-4471102-26"}
    facts = {"coverage_lines": RIVAL_GL, "_form_id": "ACORD_25"}
    assert ps._deterministic_map(
        "Policy_GeneralLiability_PolicyNumberIdentifier_A", facts) is None


def test_acord_141_takes_the_crime_policy_not_the_inland_marine_one():
    """LIVE RUN A. ACORD 141's ACORD title is "CRIME SECTION"; the map said
    inland marine, so the header printed 6C7-40-02---26 while the body carried
    employee-theft limits. One form, two policies."""
    facts = _live_merged(); facts["_form_id"] = "ACORD_141"
    assert ps._deterministic_map("Policy_PolicyNumberIdentifier_A", facts) == "CR-4471"


# The map's entries are checked against each template's OWN printed title. An
# entry may only differ from its form when the mismatch is a FORM choice rather
# than a mapping error - declared here with its reason, never inferred.
_TITLE_EXCEPTIONS = {
    # Template title is "BUSINESS OWNERS SECTION" while the repo treats ACORD
    # 160 as its Cyber Liability form. The mapping is not the defect; the form
    # is. Owner / Brent decision - see the note in _SECTION_FORM_LINE_PHRASES.
    "ACORD_160": "template is a Business Owners section, repo uses 160 as Cyber",
    # ACORD's own titles for these are "COVERAGES / LIMITS SECTION", which names
    # no line at all - the line lives in the state-specific banner above it.
    "ACORD_137_CA": "title names no coverage line",
    "ACORD_137_CO": "title names no coverage line",
    "ACORD_138_CA": "title names no coverage line",
    "ACORD_138_CO": "title names no coverage line",
    "ACORD_28": "evidence form, title names no coverage line",
    # "CONTRACTORS SUPPLEMENT" - a supplement to the GL application (it asks
    # for subcontracted cost and the GL limits required of subs, and prints
    # "MINIMUM GL LIMITS" rather than the words in full). The GL identity is
    # right; the title simply does not name the line.
    "ACORD_186": "contractors supplement to the GL application; title names no line",
}


def test_every_section_form_maps_to_the_line_its_template_names():
    """ANTI-ROT, and it has already earned its keep twice.

    `_SECTION_FORM_LINE_PHRASES` decides WHOSE policy number, carrier and NAIC
    land on a form's header. Every entry had been written from the repo's idea
    of what a form is; two disagreed with the form itself, and one of those
    shipped a live defect. The template's own printed title is the authority.
    """
    import pdfplumber
    from services.lob_canon import canon_line
    offenders = []
    for form_id, phrases in sorted(ps._SECTION_FORM_LINE_PHRASES.items()):
        if form_id in _TITLE_EXCEPTIONS:
            continue
        path = BACKEND / "templates" / f"{form_id}.pdf"
        if not path.exists():                                  # pragma: no cover
            continue
        with pdfplumber.open(str(path)) as pdf:
            text = ((pdf.pages[0].extract_text() or "")[:900]).lower()
        # The mapped line's own words must appear on the form's first page.
        if not any(all(w in text for w in p.lower().split()) for p in phrases):
            offenders.append(f"{form_id} -> {phrases} (not named on the template)")
        # ...and the mapping must be placeable, or the header can never fill.
        if not any(canon_line(p) for p in phrases):
            offenders.append(f"{form_id} -> {phrases} (no canonical family)")
    assert offenders == [], (
        "a form's header identity is mapped to a coverage line its own ACORD "
        f"template does not name: {offenders}")


def test_the_exception_list_is_declared_not_a_dumping_ground():
    """Every exception names a form that really exists and carries a reason."""
    for form_id, why in _TITLE_EXCEPTIONS.items():
        assert (BACKEND / "templates" / f"{form_id}.pdf").exists(), form_id
        assert len(why) > 20, form_id


# ════════════════════════════════════════════════════════════════════════════
# 8. A COMPOSITE IS A WITNESS, NOT A RIVAL ANSWER (live run A, Principle 2)
# ════════════════════════════════════════════════════════════════════════════

def _limits_case(dec_extra, coi_extra):
    base = [{"line": "General Liability", "carrier": "EMC Property & Casualty Company",
             "naic": "25186", "policy_number": "BBC7263 - 26", "premium": "$6,720"},
            {"line": "Commercial Auto", "carrier": "Employers Mutual Casualty Company",
             "naic": "21415", "policy_number": "6E7-40-02---26", "premium": "$2,991"}]
    d1 = {"coverage_lines": base}; d1.update(dec_extra)
    d2 = {"coverage_lines": base}; d2.update(coi_extra)
    docs = [{"doc_id": "d1", "filename": "dec.pdf", "doc_type": "dec_page",
             "text": "", "facts": d1},
            {"doc_id": "d2", "filename": "coi.pdf", "doc_type": "certificate",
             "text": "", "facts": d2}]
    mf, _ = es.merge_facts(docs, docs[0])
    return uc.assess_underwriting_consistency(docs, mf, {})


def test_a_limits_block_rendered_two_ways_is_not_a_conflict():
    """LIVE RUN A. The dec page's `gl_limits` came back "$1,000,000 /
    $2,000,000" and the certificate's "$1,000,000 Each Occurrence", and the
    producer was told "the documents state different amounts". They agree on
    every amount BOTH state - one simply also states the aggregate. Principle 2.

    The comparator is not wrong to refuse an unlabelled single against a
    composite; the QUESTION is wrong. `gl_limits` renders four scalars this
    picker reconciles on its own, and confirming one printing would have let a
    certificate's single row overwrite the dec page's six limits."""
    out = _limits_case(
        {"gl_limits": "$1,000,000 / $2,000,000",
         "gl_each_occurrence": "$1,000,000", "gl_aggregate": "$2,000,000"},
        {"gl_limits": "$1,000,000 Each Occurrence",
         "gl_each_occurrence": "$1,000,000"})
    assert out["conflict_count"] == 0, [
        (f["fact_key"], [v["display"] for v in f["values"]])
        for f in out["fields"] if f["status"] == "conflict"]


def test_the_children_are_still_asked_when_they_really_disagree():
    """POSITIVE CONTROL. Suppressing the composite must not suppress the LIMIT.
    A $1,000,000 occurrence against a $500,000 one is a real disagreement and
    is asked on the field that actually stamps."""
    out = _limits_case(
        {"gl_limits": "$1,000,000 / $2,000,000",
         "gl_each_occurrence": "$1,000,000", "gl_aggregate": "$2,000,000"},
        {"gl_limits": "$500,000 Each Occurrence",
         "gl_each_occurrence": "$500,000"})
    keys = {f["fact_key"] for f in out["fields"] if f["status"] == "conflict"}
    assert "gl_each_occurrence" in keys, keys


def test_a_composite_with_no_children_is_still_asked():
    """POSITIVE CONTROL, and the reason the rule needs positive evidence. When
    the package states the block and none of its parts, the block is the ONLY
    evidence there is - suppressing it would hide a real disagreement behind a
    better question that does not exist."""
    out = _limits_case({"gl_limits": "$1,000,000 / $2,000,000"},
                       {"gl_limits": "$500,000 / $1,000,000"})
    keys = {f["fact_key"] for f in out["fields"] if f["status"] == "conflict"}
    assert "gl_limits" in keys, keys


def test_the_composite_relationship_has_one_owner():
    """ANTI-ROT: the parent/child table lives in `extraction_service`, where the
    merge already uses it. A second copy here would be free to drift."""
    import inspect
    src = inspect.getsource(uc._composite_children)
    assert "_CURRENCY_COMPOSITE_CHILDREN" in src
    assert uc._composite_children("gl_limits"), "the table stopped resolving"
    assert uc._composite_children("applicant_name") == []


# ════════════════════════════════════════════════════════════════════════════
# 9. RENEWALS - last year's number is not a second policy
# ════════════════════════════════════════════════════════════════════════════

_IN_FORCE = {"line": "General Liability", "carrier": "EMC Property & Casualty Company",
             "naic": "25186", "policy_number": "BBC7263 - 26", "premium": "$6,720"}
_EXPIRING = {"line": "General Liability", "carrier": "EMC Property & Casualty Company",
             "naic": "25186", "policy_number": "BBC7263 - 25", "premium": "$6,100"}
_AUTO = {"line": "Commercial Auto", "carrier": "Employers Mutual Casualty Company",
         "naic": "21415", "policy_number": "6E7-40-02---26", "premium": "$2,991"}
_PRIOR_GRID = [{"line": "General Liability", "policy_number": "BBC7263 - 25",
                "carrier": "EMC Property & Casualty Company",
                "effective_date": "09/25/2025", "expiration_date": "09/25/2026"}]


def _renewal(facts):
    docs = [{"doc_id": "d1", "filename": "dec.pdf", "doc_type": "dec_page",
             "text": "", "facts": facts}]
    mf, _ = es.merge_facts(docs, docs[0])
    return mf, uc.assess_underwriting_consistency(docs, mf, {})


def test_last_years_number_is_not_a_second_policy_on_the_line():
    """A renewal dec prints the expiring number beside the in-force one. They
    ARE different contracts (`BBC7263 - 25` vs `- 26`), so nothing folds them -
    and without the prior-term filter they land as two records on one line and
    an ordinary renewal is reported as "two policies on the same coverage
    line". This file already carries that lesson for `dec_page_entries`; the
    line records were the one identity structure not asking."""
    mf, out = _renewal({"coverage_lines": [_IN_FORCE, _EXPIRING, _AUTO],
                        "prior_coverage_by_line": _PRIOR_GRID})
    gl = [r for r in mf["_line_records"] if r["line"] == "general_liab"]
    assert len(gl) == 1 and gl[0]["policy_number"] == "BBC7263 - 26"
    assert _row(out, "policy_number")["status"] == "scoped"


def test_without_a_prior_grid_the_question_is_still_asked():
    """POSITIVE EVIDENCE ONLY. No grid, no proof either number is last year's -
    so two policies on one line stays exactly what it was."""
    _, out = _renewal({"coverage_lines": [_IN_FORCE, _EXPIRING, _AUTO]})
    row = _row(out, "policy_number")
    assert row["status"] == "conflict"
    assert "same coverage line" in (row["conflict_reason"] or "")


def test_a_package_of_only_prior_rows_keeps_them():
    """The filter must not empty the store. A package whose in-force numbers
    are elsewhere still needs its lines."""
    mf, _ = _renewal({"coverage_lines": [_EXPIRING],
                      "prior_coverage_by_line": _PRIOR_GRID})
    assert [r["policy_number"] for r in mf["_line_records"]] == ["BBC7263 - 25"]


def test_the_merge_actually_writes_the_records():
    """SEAM TEST. Standing lesson from the declarations-index arc: an offline
    probe proves the FUNCTION, never the SEAM around it. This drives the real
    `merge_facts`."""
    docs = [_doc("2526 Package Policy.pdf", "dec_page", DEC_ROWS),
            _doc("CRS COI FIO.pdf", "certificate", COI_ROWS)]
    mf, _ = es.merge_facts(docs, docs[0])
    recs = mf.get("_line_records") or []
    assert sorted(r["line"] for r in recs) == [
        "auto", "general_liab", "inland_marine", "umbrella"], [r["id"] for r in recs]
    gl = next(r for r in recs if r["line"] == "general_liab")
    assert gl["policy_number"] == "BBC7263 - 26"
    assert "2526 Package Policy.pdf" in gl["sources"]
