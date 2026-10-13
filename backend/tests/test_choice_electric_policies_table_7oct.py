"""Choice Electric (Brent, 5 Oct 2026) #10 - the policies table (7 Oct 2026).

"Let's just hide/remove these two blocks because they are redundant to the
table above. In lieu of them, please add a function to sort/group by carrier
within the table." The two blocks were the read-only "Carrier - N policies, M
values - not a conflict" and "Umbrella / Excess Limit - 1 policy, 2 values -
not a conflict" rows under "Policies in this submission".

* The blocks are gone from both review layouts (display only - the backend
  still computes status "scoped"; real conflict cards stay).
* What they showed is not lost: each policy's OWN limit is a table column
  (`policy_lines.record_limits`), read only from that policy's own line family
  or umbrella-family layer, blank when unknown or when two policies share the
  line; and the table groups / sorts by carrier.

Replays the client's stored per-document facts (session ca93ed8f,
`tests/fixtures/choice_electric_pol_6oct.json`) through the real merge. No
database, no network, no LLM.
"""
import copy
import json
import os
import pathlib

import pytest

from services import extraction_service as es
from services import policy_lines as pl
from services.lob_canon import fact_line_family

_HERE = os.path.dirname(__file__)
_FIXTURE = os.path.join(_HERE, "fixtures", "choice_electric_pol_6oct.json")
_FRONT = pathlib.Path(__file__).resolve().parents[2] / "frontend" / "src" / "components" / "form"

UMBRELLA = "umbrella#unnumbered"
EXCESS = "umbrella~excess#unnumbered"


def _docs():
    with open(_FIXTURE, encoding="utf-8") as fh:
        return copy.deepcopy(json.load(fh)["docs"])


@pytest.fixture(scope="module")
def merged():
    docs = _docs()
    mf, flags = es.merge_facts(docs, es.select_primary_truth(docs))
    return mf, flags, docs


def _by_id(facts):
    return {r["id"]: r for r in pl.table_rows(facts)}


def _amounts(row):
    return [p["amount"] for p in row["limit_parts"]]


def _apply(mf, flags, docs, store):
    facts = copy.deepcopy(mf)
    fl = dict(flags)
    facts[pl.STORE_KEY] = store
    pl.apply_producer_policy_lines(facts, fl, docs)
    return facts


def _add(mf, flags, docs, line_key, fields):
    store, _id = pl.store_with_added(pl.empty_store(), line_key, fields, user="u1")
    return _apply(mf, flags, docs, store)


# ── The column reads only a line's OWN facts ──────────────────────────────────

def test_every_limit_fact_belongs_to_the_family_it_is_read_for():
    """Never a package scalar from another line: each fact the Limit column may
    read for a family is that family's own (the one family door)."""
    for family, keys in pl.limit_facts().items():
        assert keys, family
        for key in keys:
            assert fact_line_family(key) == family, (family, key)


# ── The live package's eleven policies ────────────────────────────────────────

def test_one_row_per_line_record_and_the_layers_stay_apart(merged):
    mf, _flags, _docs_ = merged
    rows = pl.table_rows(mf)
    recs = es.policy_line_records(mf["_line_records"])
    assert len(rows) == len(recs) == 11
    lines = [r["line"] for r in rows]
    assert lines.count("umbrella") == 2 and "employee_benefits" in lines
    for r in rows:
        assert r["limit"] == "; ".join(f"{p['amount']} {p['label']}" for p in r["limit_parts"])


def test_the_umbrella_and_excess_layers_each_show_their_own_limit(merged):
    mf, _flags, _docs_ = merged
    rows = _by_id(mf)
    umb, exc = rows[UMBRELLA], rows[EXCESS]
    # The umbrella's own policy: its limit and its stated $0 SIR.
    assert umb["limit_parts"] == [{"label": "each occurrence", "amount": "$5,000,000"},
                                  {"label": "SIR", "amount": "$0"}]
    # The excess layer's own declarations: $4,000,000 and no SIR (it states none -
    # never inherited from the umbrella below it).
    assert exc["limit_parts"] == [{"label": "each occurrence", "amount": "$4,000,000"}]
    assert _amounts(umb) != _amounts(exc)


def test_the_same_values_the_layers_131_copies_print(merged):
    """The umbrella-family limit IS what the layer's own ACORD 131 prints."""
    mf, _flags, _docs_ = merged
    from services import umbrella_layers as ul
    slots, assign = ul._assign(mf)
    keys = ul._keys_by_index(assign)
    rows = _by_id(mf)
    for idx, slot in enumerate(slots):
        view = ul.layer_view(mf, keys[idx])
        printed = pl._amount_text(es._fv(view, "umbrella_limit"))
        assert rows[slot["record"]["id"]]["limit_parts"][0]["amount"] == printed


def test_gl_auto_and_wc_read_their_own_line_facts(merged):
    mf, _flags, _docs_ = merged
    rows = {r["line"]: r for r in pl.table_rows(mf) if r["line"] != "umbrella"}
    gl = rows["general_liab"]
    assert [p["label"] for p in gl["limit_parts"]] == ["each occurrence", "aggregate"]
    assert _amounts(gl) == [pl._amount_text(es._fv(mf, "gl_each_occurrence")),
                            pl._amount_text(es._fv(mf, "gl_aggregate"))]
    auto = rows["auto"]
    assert _amounts(auto) == [pl._amount_text(es._fv(mf, "auto_liability_limit"))]
    assert auto["limit_parts"][0]["label"] in ("CSL", "liability")
    wc = rows["workers_comp"]
    assert [p["label"] for p in wc["limit_parts"]] == [
        "EL each accident", "EL disease each employee", "EL disease policy limit"]
    assert all(a.startswith("$") for a in _amounts(wc))


def test_a_line_with_no_limit_of_its_own_is_blank(merged):
    mf, _flags, _docs_ = merged
    rows = {r["line"]: r for r in pl.table_rows(mf)}
    for line in ("property", "inland_marine", "employee_benefits", "epli"):
        assert rows[line]["limit_parts"] == [] and rows[line]["limit"] == "", line


def test_a_gl_limit_is_never_borrowed_from_the_umbrella(merged):
    """No GL facts -> the GL row is blank, though the umbrella states $5,000,000."""
    mf, _flags, _docs_ = merged
    facts = copy.deepcopy(mf)
    for key in ("gl_each_occurrence", "gl_aggregate", "gl_limits", "gl_products_aggregate"):
        facts.pop(key, None)
    gl = next(r for r in pl.table_rows(facts) if r["line"] == "general_liab")
    assert gl["limit_parts"] == []
    assert _by_id(facts)[UMBRELLA]["limit_parts"][0]["amount"] == "$5,000,000"


# ── Edge cases ────────────────────────────────────────────────────────────────

def test_wc_falls_back_to_the_employers_liability_composite(merged):
    mf, _flags, _docs_ = merged
    facts = copy.deepcopy(mf)
    for key in ("wc_el_each_accident", "wc_el_disease_each_employee"):
        facts.pop(key, None)
    facts["employers_liability_limits"] = (
        "$500,000 Bodily Injury by Accident - each accident; $600,000 Bodily Injury by "
        "Disease - each employee; $700,000 Bodily Injury by Disease - policy limit")
    facts["wc_el_disease_policy_limit"] = "$1,000,000"     # a dedicated fact wins
    wc = next(r for r in pl.table_rows(facts) if r["line"] == "workers_comp")
    assert _amounts(wc) == ["$500,000", "$600,000", "$1,000,000"]


def test_split_auto_limits_print_their_three_parts(merged):
    mf, _flags, _docs_ = merged
    facts = copy.deepcopy(mf)
    facts.pop("auto_liability_limit", None)
    facts["auto_liability_structure"] = "Split Limits"
    facts["auto_bi_per_person"] = "$250,000"
    facts["auto_bi_per_accident"] = "$500,000"
    facts["auto_pd_per_accident"] = "$100,000"
    auto = next(r for r in pl.table_rows(facts) if r["line"] == "auto")
    assert auto["limit_parts"] == [{"label": "BI each person", "amount": "$250,000"},
                                   {"label": "BI each accident", "amount": "$500,000"},
                                   {"label": "PD each accident", "amount": "$100,000"}]


@pytest.mark.parametrize("value", ["Statutory", "Included", "$0", "0", "$1,000,000 / $2,000,000", ""])
def test_a_value_that_is_not_one_amount_is_blank(merged, value):
    mf, _flags, _docs_ = merged
    facts = copy.deepcopy(mf)
    facts["cyber_limit"] = value
    cyber = next(r for r in pl.table_rows(facts) if r["line"] == "cyber")
    assert cyber["limit_parts"] == []


def test_an_envelope_value_is_read(merged):
    mf, _flags, _docs_ = merged
    facts = copy.deepcopy(mf)
    facts["cyber_limit"] = {"value": "2000000", "source": "producer"}
    cyber = next(r for r in pl.table_rows(facts) if r["line"] == "cyber")
    assert cyber["limit_parts"] == [{"label": "limit", "amount": "$2,000,000"}]


def test_two_policies_on_one_line_show_no_line_limit(merged):
    """A GL the producer adds beside the documents' GL: nobody can say whose the
    package's GL facts are, so neither row shows them (and the added one carries
    none of its own)."""
    mf, flags, docs = merged
    facts = _add(mf, flags, docs, "general_liab", {"carrier_name": "Another Mutual Insurance Company"})
    gls = [r for r in pl.table_rows(facts) if r["line"] == "general_liab"]
    assert len(gls) == 2
    assert all(r["limit_parts"] == [] for r in gls)


def test_an_added_line_of_a_new_family_shows_no_borrowed_limit(merged):
    mf, flags, docs = merged
    facts = _add(mf, flags, docs, "crime", {"carrier_name": "Another Mutual Insurance Company"})
    crimes = [r for r in pl.table_rows(facts) if r["line"] == "crime"]
    assert len(crimes) == 2 and all(r["limit_parts"] == [] for r in crimes)


def test_an_added_layer_shows_the_limits_the_producer_stated(merged):
    mf, flags, docs = merged
    facts = _add(mf, flags, docs, "excess", {
        "carrier_name": "Another Specialty Insurance Company", "limit_each_occurrence": "$10,000,000",
        "limit_aggregate": "10000000", "sir": "$0"})
    added = next(r for r in pl.table_rows(facts) if r["producer_added"])
    assert added["limit_parts"] == [{"label": "each occurrence", "amount": "$10,000,000"},
                                    {"label": "aggregate", "amount": "$10,000,000"},
                                    {"label": "SIR", "amount": "$0"}]
    # The documents' two layers keep their own limits.
    rows = _by_id(facts)
    assert _amounts(rows[UMBRELLA])[0] == "$5,000,000"
    assert _amounts(rows[EXCESS]) == ["$4,000,000"]


def test_an_added_layer_without_limits_is_blank(merged):
    mf, flags, docs = merged
    facts = _add(mf, flags, docs, "umbrella", {"carrier_name": "Another Specialty Insurance Company"})
    added = next(r for r in pl.table_rows(facts) if r["producer_added"])
    assert added["limit_parts"] == [] and added["limit"] == ""


def test_a_session_stored_before_line_records_still_gets_limits(merged):
    mf, _flags, _docs_ = merged
    facts = copy.deepcopy(mf)
    facts.pop("_line_records", None)
    facts.pop("_umbrella_layer_docs", None)
    rows = pl.table_rows(facts)
    assert rows
    gl = next(r for r in rows if r["line"] == "general_liab")
    assert gl["limit_parts"]
    umb = [r for r in rows if r["line"] == "umbrella"]
    if len(umb) > 1:          # no layer evidence: whose umbrella_limit? nobody's
        assert all(r["limit_parts"] == [] for r in umb)


def test_no_records_no_rows_never_raises():
    assert pl.table_rows({}) == []
    assert pl.record_limits({}, []) == {}
    assert pl.record_limits(None, [{"id": "x", "line": "general_liab"}]) == {"x": []}


# ── Group by carrier ──────────────────────────────────────────────────────────

def test_each_row_carries_its_carrier_group_key(merged):
    mf, _flags, _docs_ = merged
    rows = pl.table_rows(mf)
    for r in rows:
        assert r["carrier_key"] == pl._carrier_group_key(r["carrier_name"])
        assert r["carrier_key"]
    # Two companies of one group name stay two companies.
    keys = {r["carrier_name"]: r["carrier_key"] for r in rows}
    names = [n for n in keys if "MUTUAL" in n.upper()]
    others = [n for n in keys if n not in names]
    assert all(keys[n] != keys[o] for n in names for o in others)


def test_a_glued_printing_groups_with_the_spaced_one():
    assert pl._carrier_group_key("Example Property & Casualty Company") == \
        pl._carrier_group_key("EXAMPLEPROPERTY&CASUALTYCOMPANY")
    assert pl._carrier_group_key("") == ""


# ── The two blocks are gone; the table carries their content ─────────────────

_LAYOUTS = ("AcordModal.jsx", "review/ReviewRailLayout.jsx")


@pytest.mark.parametrize("name", _LAYOUTS)
def test_no_layout_draws_the_not_a_conflict_blocks(name):
    src = (_FRONT / name).read_text(encoding="utf-8")
    assert 'f.status === "scoped").map' not in src
    assert '"values"} - not a conflict`' not in src
    assert "rr-scoped" not in src and "scoped-${f.fact_key}" not in src
    # The policies table and the real conflict cards stay.
    assert "Policies in this submission" in src
    assert "<PoliciesTable" in src
    assert 'f.status === "conflict"' in src


def test_the_rail_counts_no_scoped_row_as_content():
    src = (_FRONT / "review" / "ReviewRailLayout.jsx").read_text(encoding="utf-8")
    assert '["conflict", "confirmed", "scoped"].includes' not in src
    assert "Your documents agree - there is nothing to confirm." in src


def test_the_table_has_a_limit_column_sort_and_group_by_carrier():
    src = (_FRONT / "review" / "PoliciesTable.jsx").read_text(encoding="utf-8")
    for needle in ("<th>Limit</th>", "limit_parts", "Group by carrier", "aria-pressed",
                   "aria-sort", "carrier_key", "Premium subtotal", 'col="line"',
                   'col="carrier"', 'col="premium"', "colSpan={colCount}"):
        assert needle in src, needle
    assert "—" not in src            # no em-dash in UI text
    assert "colSpan={8}" not in src
