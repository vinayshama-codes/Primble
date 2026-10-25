"""Choice Electric (Brent, 5 Oct 2026) - the POLICIES round (7 Oct 2026).

#9: "can we add a way to inline edit missing or incorrect fields and/or add a
missing policy line altogether?" - `services/policy_lines.py`,
`routes/policy_line_routes.py`.
#7 remainder: ACORD 130 printed no WC premium although the WC information page
states TOTAL ESTIMATED ANNUAL PREMIUM 29,278.00, POLICY MINIMUM PREMIUM 465.00
and a premium per class - `services/wc_premiums.py`.

Replays the client's own stored per-document facts (session ca93ed8f,
`tests/fixtures/choice_electric_pol_6oct.json`) through the real merge, the real
pipeline re-run, the real stamper and the real Data Consistency engine. No
database, no network, no LLM.
"""
import asyncio
import copy
import json
import os

import pytest
from fastapi import HTTPException

from services import extraction_service as es
from services import pdf_service as ps
from services import policy_lines as pl
from services import wc_premiums as wp
from services.lob_canon import canon_line, umbrella_layer

_HERE = os.path.dirname(__file__)
_FIXTURE = os.path.join(_HERE, "fixtures", "choice_electric_pol_6oct.json")
_SCHEMAS = os.path.join(_HERE, "..", "forms_schemas")

AUTO = "auto#unnumbered"
EXCESS = "umbrella~excess#unnumbered"
UMBRELLA = "umbrella#unnumbered"


def _docs():
    with open(_FIXTURE, encoding="utf-8") as fh:
        return copy.deepcopy(json.load(fh)["docs"])


def _wc_docs():
    return [d for d in _docs() if "Workers" in d["filename"]]


def _schema(form_id):
    with open(os.path.join(_SCHEMAS, f"{form_id}_schema.json"), encoding="utf-8") as fh:
        return json.load(fh)


@pytest.fixture(scope="module")
def merged():
    docs = _docs()
    mf, flags = es.merge_facts(docs, es.select_primary_truth(docs))
    return mf, flags, docs


def _session(mf, flags, docs, **extra):
    return {"user_id": "u1", "docs": copy.deepcopy(docs), "facts": copy.deepcopy(mf),
            "flags": dict(flags), **extra}


def _apply(mf, flags, docs, store, **kw):
    facts = copy.deepcopy(mf)
    fl = dict(flags)
    facts[pl.STORE_KEY] = store
    pl.apply_producer_policy_lines(facts, fl, docs, **kw)
    return facts, fl


def _rows(facts):
    return {r["edit_key"]: r for r in pl.table_rows(facts)}


def _plan(sess, action, **kw):
    store, audit = pl.plan_change(sess, action, user="u1", **kw)
    sess["facts"][pl.STORE_KEY] = store
    return store, audit


# =============================================================================
# 0. The baseline table on the client's package
# =============================================================================
def test_every_policy_of_the_package_is_a_row_with_a_stable_edit_key(merged):
    mf, _flags, _docs_ = merged
    rows = pl.table_rows(mf)
    keys = [r["edit_key"] for r in rows]
    assert len(keys) == len(set(keys)) == 11
    assert AUTO in keys and EXCESS in keys and UMBRELLA in keys
    assert all(not r["producer_added"] and not r["edited_fields"] for r in rows)
    by = _rows(mf)
    assert by[EXCESS]["carrier_name"] == "TRAVELERS PROPERTY CASUALTY COMPANY OF AMERICA"
    assert by[UMBRELLA]["carrier_name"] == "AMERISURE MUTUAL INSURANCE COMPANY"
    assert by[EXCESS]["layer"] == "excess" and by[UMBRELLA]["layer"] == "umbrella"
    assert by["workers_comp#unnumbered"]["premium"] == "$29,278"


def test_no_store_changes_nothing(merged):
    """Byte-identical for every package without producer lines."""
    mf, flags, docs = merged
    facts = copy.deepcopy(mf)
    fl = dict(flags)
    report = pl.apply_producer_policy_lines(facts, fl, docs)
    assert report["changed"] is False
    assert facts == mf and fl == flags
    assert pl.carry_and_apply(facts, fl, docs, None) == {}
    assert facts == mf


def test_line_records_built_with_membership_are_the_same_records(merged):
    mf, _flags, docs = merged
    members = {}
    plain = es._build_line_records(mf, docs)
    with_members = es._build_line_records(mf, docs, members=members)
    assert plain == with_members
    assert {r["id"] for r in plain} <= set(members)
    assert all(isinstance(rows, list) and rows for rows in members.values())


# =============================================================================
# 1. Validation - the one door for what a producer may type
# =============================================================================
def test_the_auto_record_takes_a_valid_policy_number(merged):
    mf, flags, docs = merged
    sess = _session(mf, flags, docs)
    store, audit = _plan(sess, "edit", edit_key=AUTO, fields={"policy_number": "Policy No. BA-7731042"})
    assert audit == [{"field": f"policy::{AUTO}::policy_number", "previous": "", "new": "BA-7731042"}]
    facts, _ = _apply(mf, flags, docs, store)
    rows = _rows(facts)
    auto = rows[AUTO]
    assert auto["policy_number"] == "BA-7731042"
    assert auto["edited_fields"] == ["policy_number"]
    assert auto["sources"] == ["25-26 Business Auto Policy.pdf"]
    assert auto["id"] != AUTO                       # the record is now numbered ...
    assert auto["edit_key"] == AUTO                 # ... and still addressed by its key
    for key, row in _rows(mf).items():
        if key != AUTO:
            assert rows[key] == row, key
    # The section form's header prints it - the producer's number outranks the index.
    with ps._schema_context(_schema("ACORD_127")):
        got = ps._resolve_section_policy_identity(
            "Policy_PolicyNumberIdentifier_A", {**facts, **flags, "_form_id": "ACORD_127"})
    assert got == "BA-7731042"


@pytest.mark.parametrize("value", ["COMMERCIAL AUTO", "pending", "IL DS 71 05 02 08", "12",
                                   "TBD", "N/A", "unknown"])
def test_a_value_that_is_not_a_policy_number_is_refused(merged, value):
    mf, flags, docs = merged
    sess = _session(mf, flags, docs)
    with pytest.raises(pl.PolicyLineError) as exc:
        pl.plan_change(sess, "edit", edit_key=AUTO, fields={"policy_number": value})
    assert set(exc.value.errors) == {"policy_number"}


def test_a_number_the_documents_print_as_a_page_footer_is_refused(merged):
    """The package prints its form number "IL DS 71 05 02 08" as a footer."""
    mf, flags, docs = merged
    sess = _session(mf, flags, docs)
    with pytest.raises(pl.PolicyLineError):
        pl.plan_change(sess, "edit", edit_key="general_liab#unnumbered",
                       fields={"policy_number": "IL DS 71 05 02 08"})


@pytest.mark.parametrize("field,value,ok", [
    ("carrier_naic", "25186", "25186"), ("carrier_naic", " 251 86 ", "25186"),
    ("carrier_naic", "2518", None), ("carrier_naic", "251866", None), ("carrier_naic", "ABCDE", None),
    ("effective_date", "1/1/2026", "01/01/2026"), ("effective_date", "2026-01-01", "01/01/2026"),
    ("effective_date", "02/30/2026", None), ("effective_date", "banana", None),
    ("effective_date", "01/01/1800", None),
    ("premium", "$12,500", "$12,500"), ("premium", "12500.50", "$12,500.50"), ("premium", "$1M", "$1,000,000"),
    ("premium", "USD 2,400", "$2,400"), ("premium", "0", None), ("premium", "about 5000", None),
    ("premium", "$1,000 / $2,000", None), ("premium", "Included", None), ("premium", "-500", None),
    ("carrier_name", "Federal Insurance Company", "Federal Insurance Company"),
    ("carrier_name", "ISO", None), ("carrier_name", "Certificate Holder", None),
    ("carrier_name", "TBD", None), ("carrier_name", "x", None),
])
def test_field_validation(field, value, ok):
    if ok is None:
        with pytest.raises(pl.PolicyLineError) as exc:
            pl.validate_fields({field: value})
        assert field in exc.value.errors
    else:
        assert pl.validate_fields({field: value}) == {field: ok}


def test_empty_clears_a_box_but_never_the_carrier():
    assert pl.validate_fields({"carrier_naic": "", "premium": None}) == {"carrier_naic": "", "premium": ""}
    with pytest.raises(pl.PolicyLineError) as exc:
        pl.validate_fields({"carrier_name": "  "})
    assert "carrier_name" in exc.value.errors


def test_the_term_must_run_forward_including_the_records_other_date():
    with pytest.raises(pl.PolicyLineError) as exc:
        pl.validate_fields({"effective_date": "01/01/2026", "expiration_date": "01/01/2025"})
    assert "expiration_date" in exc.value.errors
    current = {"effective_date": "01/01/2025", "expiration_date": "01/01/2026"}
    with pytest.raises(pl.PolicyLineError):
        pl.validate_fields({"expiration_date": "06/01/2024"}, current=current)
    assert pl.validate_fields({"expiration_date": "01/01/2027"}, current=current) == {
        "expiration_date": "01/01/2027"}


def test_adding_needs_a_line_and_a_carrier(merged):
    mf, flags, docs = merged
    sess = _session(mf, flags, docs)
    with pytest.raises(pl.PolicyLineError) as exc:
        pl.plan_change(sess, "add", line_key="epli", fields={"policy_number": "EPL-1"})
    assert "carrier_name" in exc.value.errors
    with pytest.raises(pl.PolicyLineError) as exc:
        pl.plan_change(sess, "add", line_key="boats", fields={"carrier_name": "Acme Insurance Co"})
    assert "line" in exc.value.errors


def test_an_unchanged_save_is_a_no_op(merged):
    mf, flags, docs = merged
    sess = _session(mf, flags, docs)
    row = _rows(mf)[AUTO]
    store, audit = pl.plan_change(sess, "edit", edit_key=AUTO,
                                  fields={"carrier_name": row["carrier_name"]})
    assert audit == [] and not pl.store_has_content(store)


def test_an_unknown_key_is_refused(merged):
    mf, flags, docs = merged
    sess = _session(mf, flags, docs)
    with pytest.raises(KeyError):
        pl.plan_change(sess, "edit", edit_key="auto#NOPE", fields={"policy_number": "BA-1"})
    with pytest.raises(KeyError):
        pl.plan_change(sess, "remove", line_id="added:nope")
    with pytest.raises(pl.PolicyLineError) as exc:        # a document's policy: correct it instead
        pl.plan_change(sess, "remove", line_id=AUTO)
    assert "cannot be removed" in exc.value.message


@pytest.mark.parametrize("key,family,layer,label,printed", pl.LINE_OPTIONS)
def test_every_line_a_producer_may_add_is_read_as_its_own_family(key, family, layer, label, printed):
    assert canon_line(printed) == family
    assert umbrella_layer(printed) == layer
    assert "—" not in label and "—" not in printed


def test_the_offered_section_forms_are_the_lines_own_forms():
    """Pinned against the stamper's own form -> line table."""
    for family, forms in pl.SECTION_FORMS.items():
        for form_id in forms:
            phrases = ps._SECTION_FORM_LINE_PHRASES.get(form_id) or ()
            assert phrases, form_id
            assert family in {canon_line(p) for p in phrases}, (form_id, family)


# =============================================================================
# 2. The Excess layer is corrected without touching the Umbrella
# =============================================================================
def test_the_excess_layer_is_corrected_alone(merged):
    mf, flags, docs = merged
    sess = _session(mf, flags, docs)
    store, _ = _plan(sess, "edit", edit_key=EXCESS, fields={
        "carrier_name": "Travelers Casualty and Surety Company", "premium": "$11,000",
        "policy_number": "EX-4410022"})
    facts, _ = _apply(mf, flags, docs, store)
    rows = _rows(facts)
    ex = rows[EXCESS]
    assert ex["carrier_name"] == "Travelers Casualty and Surety Company"
    assert ex["premium"] == "$11,000" and ex["policy_number"] == "EX-4410022"
    assert ex["sources"] == ["25-26 Excess Umbrella Policy.pdf"]     # still its own dec
    assert ex["layer"] == "excess"
    assert rows[UMBRELLA] == _rows(mf)[UMBRELLA]
    # The document's printing stays placed on its record: no Data Consistency card.
    from services.underwriting_consistency import assess_underwriting_consistency
    before = assess_underwriting_consistency(docs, mf, {}, flags=flags)
    after = assess_underwriting_consistency(docs, facts, {}, flags=flags)
    assert after["conflict_count"] == before["conflict_count"] == 0
    assert {f["fact_key"]: f["status"] for f in after["fields"]} == \
        {f["fact_key"]: f["status"] for f in before["fields"]}
    # (19 Oct 2026, Brent: source + page for every coverage) built with the same documents.
    assert after["policy_lines"] == pl.table_rows(facts, docs)


def test_two_carriers_on_one_line_are_addressed_separately():
    rows = [
        {"line": "Commercial General Liability", "carrier": "Acme Mutual Insurance Company",
         "premium": "$1,000", "effective_date": "01/01/2026", "expiration_date": "01/01/2027"},
        {"line": "Commercial General Liability", "carrier": "Zenith Casualty Company",
         "premium": "$2,000", "effective_date": "01/01/2026", "expiration_date": "01/01/2027"},
    ]
    facts = {"coverage_lines": copy.deepcopy(rows)}
    es._build_scoped_fact_store(facts, None)
    keys = [r["edit_key"] for r in pl.table_rows(facts)]
    assert len(keys) == 2 and all(k.startswith("general_liab#unnumbered@") for k in keys)
    zenith = next(k for k in keys if "ZENITH" in k)
    store = pl.store_with_edit(pl.empty_store(), zenith, {"policy_number": "ZC-500"},
                               pl.anchor_for(facts, zenith))
    facts[pl.STORE_KEY] = store
    pl.apply_producer_policy_lines(facts, None, None)
    out = {r["carrier_name"]: r for r in pl.table_rows(facts)}
    assert out["Zenith Casualty Company"]["policy_number"] == "ZC-500"
    assert out["Acme Mutual Insurance Company"]["policy_number"] == ""


def _pair_facts():
    facts = {"coverage_lines": [
        {"line": "Commercial General Liability", "carrier": "Acme Mutual Insurance Company",
         "naic": "11111", "policy_number": "GL-100", "premium": "$1,000"},
        {"line": "Business Auto", "carrier": "Zenith Casualty Company", "naic": "22222",
         "policy_number": "BA-200", "premium": "$2,000"},
    ]}
    es._build_scoped_fact_store(facts, None)
    return facts


@pytest.mark.parametrize("new_carrier,typed_naic,expected", [
    ("Zenith Casualty Company", None, "22222"),        # the documents print its one NAIC
    ("Brand New Insurance Company", None, ""),          # another company, no NAIC known
    ("ACME MUTUAL INSURANCE COMPANY", None, "11111"),   # the same company respelled
    ("Brand New Insurance Company", "33333", "33333"),  # the producer typed the pair
])
def test_carrier_and_naic_move_as_a_matched_pair(new_carrier, typed_naic, expected):
    facts = _pair_facts()
    key = next(r["edit_key"] for r in pl.table_rows(facts) if r["line"] == "general_liab")
    fields = {"carrier_name": new_carrier}
    if typed_naic:
        fields["carrier_naic"] = typed_naic
    facts[pl.STORE_KEY] = pl.store_with_edit(pl.empty_store(), key, fields, pl.anchor_for(facts, key))
    pl.apply_producer_policy_lines(facts, None, None)
    gl = next(r for r in pl.table_rows(facts) if r["line"] == "general_liab")
    assert gl["carrier_name"] == new_carrier
    assert gl["carrier_naic"] == expected


def test_a_dormant_edit_is_kept_and_listed():
    facts = _pair_facts()
    key = next(r["edit_key"] for r in pl.table_rows(facts) if r["line"] == "general_liab")
    store = pl.store_with_edit(pl.empty_store(), key, {"premium": "$1,500"}, pl.anchor_for(facts, key))
    # The document that printed the GL policy is gone.
    facts["coverage_lines"] = [r for r in facts["coverage_lines"] if "Liability" not in r["line"]]
    es._build_scoped_fact_store(facts, None)
    facts[pl.STORE_KEY] = store
    report = pl.apply_producer_policy_lines(facts, None, None)
    assert report["unmatched"] == [key]
    assert [u["edit_key"] for u in pl.unmatched_edits(facts)] == [key]
    assert pl.read_store(facts)["edits"][key]["fields"] == {"premium": "$1,500"}


def test_an_edit_re_finds_its_record_by_anchor_when_the_id_changes():
    facts = _pair_facts()
    key = next(r["edit_key"] for r in pl.table_rows(facts) if r["line"] == "auto")
    store = pl.store_with_edit(pl.empty_store(), key, {"premium": "$2,500"}, pl.anchor_for(facts, key))
    # A new document prints the auto number with its term marker - a new id.
    facts["coverage_lines"][1]["policy_number"] = "BA-200-26"
    es._build_scoped_fact_store(facts, None)
    assert key not in {r["id"] for r in es._build_line_records(facts)}
    facts[pl.STORE_KEY] = store
    report = pl.apply_producer_policy_lines(facts, None, None)
    assert report["applied"] == [key] and not report["unmatched"]
    auto = next(r for r in pl.table_rows(facts) if r["line"] == "auto")
    assert auto["premium"] == "$2,500" and auto["edit_key"] == key


# =============================================================================
# 3. Adding an EPLI line and a new excess layer; removing an added line
# =============================================================================
def _with_added_lines(merged):
    mf, flags, docs = merged
    sess = _session(mf, flags, docs)
    _plan(sess, "add", line_key="epli", fields={
        "carrier_name": "Federal Insurance Company", "policy_number": "EPL-55123",
        "effective_date": "01/01/2025", "expiration_date": "01/01/2026"})
    store, audit = _plan(sess, "add", line_key="excess", fields={
        "carrier_name": "Markel American Insurance Company", "policy_number": "XS-90001",
        "premium": "$6,500", "effective_date": "01/01/2025", "expiration_date": "01/01/2026"})
    return sess, store, audit


def test_an_added_epli_line_and_a_second_excess_layer(merged):
    mf, flags, docs = merged
    sess, store, audit = _with_added_lines(merged)
    assert audit[0]["previous"] == "not in package" and audit[0]["new"].startswith("Excess Liability")
    facts, fl = _apply(mf, flags, docs, store)
    added = [r for r in pl.table_rows(facts) if r["producer_added"]]
    assert [r["line"] for r in added] == ["epli", "umbrella"]
    epli, excess = added
    assert epli["edit_key"].startswith(pl.ADDED_PREFIX) and epli["sources"] == []
    assert excess["layer"] == "excess" and excess["id"].startswith("umbrella~excess#added-")
    assert excess["premium"] == "$6,500"
    # The documents' eleven policies are untouched; the tower now has three layers.
    for key, row in _rows(mf).items():
        assert _rows(facts)[key] == row
    layers = sorted(r["layer"] for r in pl.table_rows(facts) if r["line"] == "umbrella")
    assert layers == ["excess", "excess", "umbrella"]
    # An added line is a grant, and its carrier a writer of the programme.
    row = next(r for r in facts["coverage_lines"]
               if r.get(pl.ROW_ADDED) == excess["edit_key"][len(pl.ADDED_PREFIX):])
    assert es._line_entry_grants_coverage(row)
    assert ps._line_entry_evidences_policy(row)
    from services.lob_canon import _grants_coverage
    assert _grants_coverage(row)
    assert "Markel American Insurance Company" in facts["_programme_writers"]
    # No new Data Consistency card.
    from services.underwriting_consistency import assess_underwriting_consistency
    assert assess_underwriting_consistency(docs, facts, {}, flags=fl)["conflict_count"] == 0


def test_an_added_line_without_premium_or_number_is_still_a_policy(merged):
    mf, flags, docs = merged
    sess = _session(mf, flags, docs)
    # Same carrier and term as the package - would read as a header copy if it
    # were a document's row.
    store, _ = _plan(sess, "add", line_key="pollution", fields={
        "carrier_name": "AMERISURE INSURANCE COMPANY",
        "effective_date": "01/01/2025", "expiration_date": "01/01/2026"})
    facts, _ = _apply(mf, flags, docs, store)
    added = [r for r in pl.table_rows(facts) if r["producer_added"]]
    assert [r["line"] for r in added] == ["pollution"]
    assert len(pl.table_rows(facts)) == len(pl.table_rows(mf)) + 1


def test_removing_an_added_line(merged):
    mf, flags, docs = merged
    sess, store, _ = _with_added_lines(merged)
    facts, _ = _apply(mf, flags, docs, store)
    epli = next(r for r in pl.table_rows(facts) if r["producer_added"] and r["line"] == "epli")
    sess["facts"] = facts
    store2, audit = _plan(sess, "remove", line_id=epli["edit_key"])
    assert audit[0]["new"] == "removed"
    facts2, _ = _apply(mf, flags, docs, store2)
    assert [r["line"] for r in pl.table_rows(facts2) if r["producer_added"]] == ["umbrella"]
    with pytest.raises(KeyError):
        pl.plan_change(sess, "remove", line_id="added:nope", user="u1")


def test_an_added_line_can_be_corrected_like_any_other(merged):
    mf, flags, docs = merged
    sess, store, _ = _with_added_lines(merged)
    facts, _ = _apply(mf, flags, docs, store)
    sess["facts"] = facts
    excess = next(r for r in pl.table_rows(facts) if r["producer_added"] and r["line"] == "umbrella")
    store2, audit = _plan(sess, "edit", edit_key=excess["edit_key"], fields={"premium": "$7,000"})
    assert audit[0]["previous"] == "$6,500"
    facts2, _ = _apply(mf, flags, docs, store2)
    again = next(r for r in pl.table_rows(facts2) if r["edit_key"] == excess["edit_key"])
    assert again["premium"] == "$7,000"


def test_flags_follow_added_lines_and_come_back_when_they_go():
    store = pl.empty_store()
    store["added"] = [{"id": "a1", "family": "umbrella", "line_key": "umbrella"}]
    flags = {"has_umbrella": False}
    assert pl._set_line_flags(store, flags, restore=True) == ["has_umbrella"]
    assert flags["has_umbrella"] is True and store["flags_set"] == {"has_umbrella": False}
    store["added"] = []
    pl._set_line_flags(store, flags, restore=True)
    assert flags["has_umbrella"] is False and store["flags_set"] == {}
    # A re-run's flags come fresh from the documents and are left alone.
    store["flags_set"] = {"has_umbrella": None}
    fresh = {"has_umbrella": True}
    pl._set_line_flags(store, fresh, restore=False)
    assert fresh == {"has_umbrella": True}


def test_application_is_idempotent(merged):
    mf, flags, docs = merged
    sess, store, _ = _with_added_lines(merged)
    _plan(sess, "edit", edit_key=AUTO, fields={"policy_number": "BA-7731042"})
    store = sess["facts"][pl.STORE_KEY]
    facts, fl = _apply(mf, flags, docs, store)
    again = copy.deepcopy(facts)
    pl.apply_producer_policy_lines(again, dict(fl), docs)
    assert pl.table_rows(again) == pl.table_rows(facts)
    assert len(again["coverage_lines"]) == len(facts["coverage_lines"])


# =============================================================================
# 4. The store survives every pipeline re-run (and the editor confirm)
# =============================================================================
def _run_pipeline(monkeypatch, docs, prior_facts, prior_flags=None):
    import services.extraction_pipeline as ep
    import services.yes_no_lexicon as ynl
    calls = {}

    async def _upd(session_id, payload, delete_facts=None, **_kw):
        calls["payload"] = payload
        calls["delete_facts"] = delete_facts

    async def _no_account(_user_id):
        return None

    async def _no_learn(_values):
        return 0

    monkeypatch.setattr(ep, "upd_processing_session", _upd)
    monkeypatch.setattr(ep, "_submitting_account_for", _no_account)
    monkeypatch.setattr(ynl, "learn", _no_learn)
    result = asyncio.run(ep._finalize_pipeline(docs, "u1", session_id="s-pol",
                                               prior_facts=prior_facts,
                                               prior_flags=prior_flags or {}))
    calls["result"] = result
    return calls


def test_the_store_survives_a_pipeline_rerun(merged, monkeypatch):
    mf, flags, docs = merged
    sess, _store, _ = _with_added_lines(merged)
    _plan(sess, "edit", edit_key=AUTO, fields={"policy_number": "BA-7731042"})
    _plan(sess, "edit", edit_key=EXCESS, fields={"premium": "$11,000"})
    prior = copy.deepcopy(mf)
    prior[pl.STORE_KEY] = sess["facts"][pl.STORE_KEY]
    run_docs = _docs()
    calls = _run_pipeline(monkeypatch, run_docs, prior, flags)
    facts = calls["payload"]["facts"]
    rows = _rows(facts)
    assert rows[AUTO]["policy_number"] == "BA-7731042"
    assert rows[EXCESS]["premium"] == "$11,000"
    assert sorted(r["line"] for r in rows.values() if r["producer_added"]) == ["epli", "umbrella"]
    uw = calls["payload"]["underwriting_consistency"]
    # (19 Oct 2026, Brent: source + page for every coverage) the documents the run read.
    assert uw["policy_lines"] == pl.table_rows(facts, run_docs)
    assert uw["conflict_count"] == 0 and uw["unmatched_policy_edits"] == []
    # The documents' own rows are kept beside the producer's.
    assert not any(r.get(pl.ROW_ADDED) or r.get(pl.ROW_FIELDS)
                   for r in facts["_coverage_lines_unconfirmed"])
    # ...and a second re-run from what was stored gives the same table.
    again = _run_pipeline(monkeypatch, _docs(), facts, calls["payload"]["flags"])
    assert pl.table_rows(again["payload"]["facts"]) == pl.table_rows(facts)


def test_a_new_line_recommends_its_form_before_forms(monkeypatch):
    """Pre-form recommendation refresh: a WC-only package has no umbrella; an
    added umbrella turns the line on and the recommender adds ACORD 131."""
    first = _run_pipeline(monkeypatch, _wc_docs(), None)
    recs = {r["form_id"] for r in first["payload"]["recommendations"]}
    assert "ACORD_130" in recs and "ACORD_131" not in recs
    facts = copy.deepcopy(first["payload"]["facts"])
    sess = {"user_id": "u1", "docs": _wc_docs(), "facts": facts, "flags": first["payload"]["flags"]}
    _plan(sess, "add", line_key="umbrella", fields={
        "carrier_name": "Amerisure Mutual Insurance Company", "premium": "$17,082"})
    second = _run_pipeline(monkeypatch, _wc_docs(), sess["facts"], first["payload"]["flags"])
    recs2 = {r["form_id"] for r in second["payload"]["recommendations"]}
    assert "ACORD_131" in recs2
    assert second["payload"]["flags"]["has_umbrella"] is True


def test_a_new_excess_layer_reaches_the_recommender(merged, monkeypatch):
    """The layer recommender (LAYERS, 7 Oct) reads the line records: the
    producer's second excess layer is one more ACORD 131 instance."""
    mf, flags, _docs_ = merged
    before = _run_pipeline(monkeypatch, _docs(), copy.deepcopy(mf), flags)
    inst_before = {r["form_id"] for r in before["payload"]["recommendations"] if "__" in r["form_id"]}
    _sess, store, _ = _with_added_lines(merged)
    prior = copy.deepcopy(mf)
    prior[pl.STORE_KEY] = store
    calls = _run_pipeline(monkeypatch, _docs(), prior, flags)
    recs = {r["form_id"] for r in calls["payload"]["recommendations"]}
    assert "ACORD_131" in recs
    excess_records = [r for r in calls["payload"]["facts"]["_line_records"]
                      if r.get("layer") == "excess"]
    assert len(excess_records) == 2
    inst_after = {f for f in recs if "__" in f}
    if inst_before:                       # the layer recommender is present
        assert inst_before < inst_after and len(inst_after) == len(inst_before) + 1


def test_after_forms_a_new_excess_layer_offers_its_own_131(merged):
    mf, flags, docs = merged
    from services.form_service import filter_available_forms, load_all_forms
    session = _session(mf, flags, docs, all_forms=filter_available_forms(load_all_forms()))
    from services.form_service import match_forms
    text = " ".join(d["text"] for d in docs)
    present = [r["form_id"] for r in match_forms(mf, flags, session["all_forms"], text=text)]
    session["generated_forms"] = {f: {} for f in present}
    session["selected_form_ids"] = list(present)
    _plan(session, "add", line_key="excess", fields={
        "carrier_name": "Markel American Insurance Company", "policy_number": "XS-90001"})
    facts, fl = _apply(mf, flags, docs, session["facts"][pl.STORE_KEY], restore_flags=True, force=True)
    session["facts"], session["flags"] = facts, fl
    offers = [o["form_id"] for o in pl.form_offers(session)]
    assert all(o.startswith("ACORD_131") and o not in present for o in offers)
    if any("__" in f for f in present):   # the layer recommender is present
        assert offers == ["ACORD_131__excess-2"]


def test_the_editor_confirm_keeps_the_producer_lines(merged, monkeypatch):
    """`confirm_underwriting_value_in_editor` rebuilds the rows from the
    documents' own; the producer's lines go back on top."""
    import services.extraction_pipeline as ep
    mf, flags, docs = merged
    sess, store, _ = _with_added_lines(merged)
    facts, fl = _apply(mf, flags, docs, store)
    facts[ep.UNCONFIRMED_COVERAGE_LINES_KEY] = copy.deepcopy(
        [r for r in mf["coverage_lines"]])
    session = {"user_id": "u1", "docs": copy.deepcopy(docs), "facts": facts, "flags": fl,
               "underwriting_confirmations": {},
               "generated_forms": {"ACORD_125": {"schema": {}, "field_state": {}, "confidence": {}}},
               "structured_issues": []}
    writes = {}

    async def _upd(_sid, payload, delete_facts=None, **_kw):
        writes.update(payload)

    monkeypatch.setattr(ep, "upd_processing_session", _upd)
    asyncio.run(ep.confirm_underwriting_value_in_editor(
        session, "s1", fact_key="applicant_name", value="CHOICE ELECTRIC LLC"))
    assert pl.table_rows(writes["facts"]) == pl.table_rows(facts)


# =============================================================================
# 5. After forms: re-stamp only the right boxes, keep person-typed boxes
# =============================================================================
def _generate(form_ids, facts, flags, docs):
    text = "\n".join(str(d.get("text") or "") for d in docs)
    out = {}
    for fid in form_ids:
        schema = _schema(fid)
        ctx = {**facts, **flags, "_form_id": fid, "_package_form_ids": list(form_ids)}
        state, conf = {}, {}
        hay = [None]
        with ps._schema_context(schema):
            for box in schema:
                if ps._is_nonfillable_field(box):
                    raw = ps.nonfillable_box_value(box, ctx, schema, text, hay)
                else:
                    raw = ps._deterministic_map(box, ctx)
                    if raw == "UNMATCHED" or raw is ps._SCHED_SKIP:
                        raw = None
                if raw in (None, ""):
                    continue
                state[box] = str(ps.display_value_for_box(fid, box, raw, facts=ctx) or "").strip()
                conf[box] = "filled"
        out[fid] = {"schema": schema, "field_state": state, "mapped": dict(state),
                    "confidence": conf, "client_filled_fields": []}
    return out


@pytest.fixture(scope="module")
def generated(merged):
    mf, flags, docs = merged
    return _generate(["ACORD_125", "ACORD_127", "ACORD_131"], mf, flags, docs)


def test_after_forms_only_the_right_boxes_move_and_person_typed_boxes_stay(merged, generated):
    mf, flags, docs = merged
    gen = copy.deepcopy(generated)
    gen["ACORD_131"]["field_state"]["Policy_PolicyNumberIdentifier_A"] = "TYPED-131"
    gen["ACORD_131"]["confidence"]["Policy_PolicyNumberIdentifier_A"] = "producer"
    session = _session(mf, flags, docs, generated_forms=gen, selected_form_ids=list(gen))
    store, _ = pl.plan_change(session, "edit", edit_key=AUTO, user="u1",
                              fields={"policy_number": "BA-7731042", "premium": "$3,100"})
    writes = {}

    async def _upd(_sid, payload, delete_facts=None, **_kw):
        writes.update(payload)
        writes["_deleted"] = delete_facts

    out = asyncio.run(pl.apply_post_generation(session, "s1", store, upd=_upd))
    assert set(out["forms_updated"]) == {"ACORD_125", "ACORD_127", "ACORD_131"}
    after = writes["generated_forms"]
    moved = {}
    for fid, form in after.items():
        before = generated[fid]["field_state"]
        for box in set(before) | set(form["field_state"]):
            if (before.get(box) or "") != (form["field_state"].get(box) or ""):
                moved[(fid, box)] = form["field_state"].get(box)
    # The person's box stands.
    assert after["ACORD_131"]["field_state"]["Policy_PolicyNumberIdentifier_A"] == "TYPED-131"
    assert after["ACORD_131"]["confidence"]["Policy_PolicyNumberIdentifier_A"] == "producer"
    # The auto policy's own boxes move, labelled the producer's.
    assert moved[("ACORD_127", "Policy_PolicyNumberIdentifier_A")] == "BA-7731042"
    assert moved[("ACORD_125", "OtherPolicy_PolicyNumberIdentifier_A")] == "BA-7731042"
    assert moved[("ACORD_125", "CommercialVehicleLineOfBusiness_PremiumAmount_A")] == "3,100"
    assert moved[("ACORD_131", "UnderlyingPolicy_Automobile_PolicyNumberIdentifier_A")] == "BA-7731042"
    for fid, box in [("ACORD_127", "Policy_PolicyNumberIdentifier_A"),
                     ("ACORD_125", "CommercialVehicleLineOfBusiness_PremiumAmount_A")]:
        assert after[fid]["confidence"][box] == "producer"
    # POLICY PREMIUM (Brent, 8 Oct 2026): a renewal's EXPIRING total never prints on
    # page one, and one typed line premium is not the new term's total - it stays blank.
    assert not generated["ACORD_125"]["field_state"].get("Policy_Payment_EstimatedTotalAmount_A")
    assert ("ACORD_125", "Policy_Payment_EstimatedTotalAmount_A") not in moved
    # Nothing else moved: every moved box belongs to the auto policy's own rows.
    allowed_prefixes = ("OtherPolicy_", "PriorCoverage_Automobile_", "UnderlyingPolicy_Automobile_",
                        "CommercialVehicleLineOfBusiness_", "Policy_Payment_EstimatedTotalAmount_",
                        "CommercialPolicy_Question_AAHCode_", "Policy_PolicyNumberIdentifier_")
    stray = [k for k in moved if not k[1].startswith(allowed_prefixes)]
    assert not stray, stray
    # PDF caches busted on the changed forms only.
    assert all(after[f]["pdf_bytes"] is None and after[f]["_pdf_cache_hash"] == ""
               for f in out["forms_updated"])
    assert writes["facts"][pl.STORE_KEY]["edits"][AUTO]["fields"]["policy_number"] == "BA-7731042"


def test_after_forms_an_added_line_offers_its_form_never_adds_it(merged, monkeypatch):
    first = _run_pipeline(monkeypatch, _wc_docs(), None)
    payload = first["payload"]
    from services.form_service import filter_available_forms, load_all_forms
    session = {"user_id": "u1", "docs": _wc_docs(), "facts": copy.deepcopy(payload["facts"]),
               "flags": dict(payload["flags"]), "all_forms": filter_available_forms(load_all_forms()),
               "generated_forms": {"ACORD_125": {}, "ACORD_130": {}},
               "selected_form_ids": ["ACORD_125", "ACORD_130"]}
    assert pl.form_offers(session) == []                       # nothing added: no offer
    store, _ = pl.plan_change(session, "add", line_key="umbrella", user="u1",
                              fields={"carrier_name": "Amerisure Mutual Insurance Company"})
    facts, fl = _apply(session["facts"], session["flags"], session["docs"], store,
                       restore_flags=True, force=True)
    session["facts"], session["flags"] = facts, fl
    offers = pl.form_offers(session)
    assert [o["form_id"] for o in offers] == ["ACORD_131"]
    assert offers[0]["label"] == "ACORD 131"
    session["generated_forms"]["ACORD_131"] = {}
    assert pl.form_offers(session) == []                       # already in the package


# =============================================================================
# 6. The routes: owner, generation lock, field errors, unknown rows
# =============================================================================
def _route_session():
    return {"user_id": "owner", "docs": [], "facts": {}, "flags": {}}


def test_the_routes_refuse_a_stranger_and_a_live_run(monkeypatch):
    import routes.policy_line_routes as r
    import routes.form_routes as fr
    sess = _route_session()

    async def _get(_sid, include_pdf=False):
        return sess

    async def _running(_session):
        return "running", None

    async def _idle(_session):
        return "none", None

    monkeypatch.setattr(r, "get_processing_session", _get)
    req = r.PolicyLineEditRequest(edit_key=AUTO, fields={"policy_number": "BA-1"})
    with pytest.raises(HTTPException) as exc:
        asyncio.run(r.policy_line_edit("s1", req, current_user={"id": "stranger"}))
    assert exc.value.status_code == 403
    monkeypatch.setattr(fr, "_generation_state_for", _running)
    with pytest.raises(HTTPException) as exc:
        asyncio.run(r.policy_line_edit("s1", req, current_user={"id": "owner"}))
    assert exc.value.status_code == 409
    monkeypatch.setattr(fr, "_generation_state_for", _idle)
    with pytest.raises(HTTPException) as exc:        # no such policy on this package
        asyncio.run(r.policy_line_edit("s1", req, current_user={"id": "owner"}))
    assert exc.value.status_code == 404
    with pytest.raises(HTTPException) as exc:
        asyncio.run(r.policy_line_remove("s1", AUTO, current_user={"id": "owner"}))
    assert exc.value.status_code == 404


def test_a_refused_value_comes_back_as_field_errors(merged, monkeypatch):
    import routes.policy_line_routes as r
    import routes.form_routes as fr
    mf, flags, docs = merged
    sess = _session(mf, flags, docs, user_id="owner")

    async def _get(_sid, include_pdf=False):
        return sess

    async def _idle(_session):
        return "none", None

    monkeypatch.setattr(r, "get_processing_session", _get)
    monkeypatch.setattr(fr, "_generation_state_for", _idle)
    req = r.PolicyLineEditRequest(edit_key=AUTO, fields={"policy_number": "COMMERCIAL AUTO",
                                                         "carrier_naic": "123"})
    resp = asyncio.run(r.policy_line_edit("s1", req, current_user={"id": "owner"}))
    body = json.loads(resp.body)
    assert resp.status_code == 400 and body["success"] is False
    assert set(body["errors"]) == {"policy_number", "carrier_naic"}
    # An unchanged save answers with the table and changes nothing.
    row = _rows(mf)[AUTO]
    resp = asyncio.run(r.policy_line_edit(
        "s1", r.PolicyLineEditRequest(edit_key=AUTO, fields={"carrier_name": row["carrier_name"]}),
        current_user={"id": "owner"}))
    body = json.loads(resp.body)
    # (19 Oct 2026, Brent: source + page for every coverage) the route reads the session's documents.
    assert body["changed"] is False and body["policy_lines"] == pl.table_rows(mf, docs)


def test_the_add_form_route_adds_only_an_offered_form(merged, monkeypatch):
    import routes.policy_line_routes as r
    import routes.form_routes as fr
    mf, flags, docs = merged
    sess = _session(mf, flags, docs, user_id="owner", generated_forms={"ACORD_125": {}})

    async def _get(_sid, include_pdf=False):
        return sess

    async def _idle(_session):
        return "none", None

    monkeypatch.setattr(r, "get_processing_session", _get)
    monkeypatch.setattr(fr, "_generation_state_for", _idle)
    resp = asyncio.run(r.policy_line_add_form("s1", r.PolicyLineAddFormRequest(form_id="ACORD_127"),
                                              current_user={"id": "owner"}))
    body = json.loads(resp.body)
    assert body["success"] is False and body["outcome"] == "not_requested"


def _stub_route_io(monkeypatch, store):
    """The route's I/O, in memory: one session row, every write merged into it."""
    import routes.policy_line_routes as r
    import routes.form_routes as fr
    import services.extraction_pipeline as ep
    import services.yes_no_lexicon as ynl
    import services.audit_service as au
    import services.arq_service as aq
    from repositories.session_repository import resolve_facts_write

    async def _get(_sid, include_pdf=False):
        return copy.deepcopy(store["row"])

    async def _upd(_sid, payload, delete_facts=None, **_kw):
        row = store["row"]
        for k, v in payload.items():
            if k == "facts":
                row["facts"] = resolve_facts_write(row, v) or row.get("facts")
            elif k == "generated_forms":
                row.setdefault("generated_forms", {}).update(v)
            else:
                row[k] = v
        for k in delete_facts or []:
            row["facts"].pop(k, None)

    async def _no_account(_uid):
        return None

    async def _no_learn(_values):
        return 0

    async def _idle(_session):
        return "none", None

    async def _log(**kw):
        store.setdefault("audit", []).append(kw)

    async def _recalc(_sid):
        store["recalculated"] = True
        return {"ok": True}

    for mod in (r, fr):
        monkeypatch.setattr(mod, "get_processing_session", _get)
    monkeypatch.setattr(r, "upd_processing_session", _upd)
    monkeypatch.setattr(ep, "upd_processing_session", _upd)
    monkeypatch.setattr(ep, "_submitting_account_for", _no_account)
    monkeypatch.setattr(ynl, "learn", _no_learn)
    monkeypatch.setattr(fr, "_generation_state_for", _idle)
    monkeypatch.setattr(au, "log_field_change", _log)
    monkeypatch.setattr(aq, "recalculate_session_scores", _recalc)
    import repositories.session_repository as sr
    monkeypatch.setattr(sr, "get_processing_session", _get)
    monkeypatch.setattr(sr, "upd_processing_session", _upd)
    return r


def test_the_route_before_forms_reruns_the_package_and_answers_like_confirm(monkeypatch):
    first = _run_pipeline(monkeypatch, _wc_docs(), None)
    row = {**copy.deepcopy(first["payload"]), "docs": _wc_docs(), "user_id": "owner"}
    row["generated_forms"], row["selected_form_ids"] = {}, []
    store = {"row": row}
    r = _stub_route_io(monkeypatch, store)
    req = r.PolicyLineAddRequest(line="umbrella", fields={
        "carrier_name": "Amerisure Mutual Insurance Company", "premium": "$17,082"})
    resp = asyncio.run(r.policy_line_add("s-pol", req, current_user={"id": "owner"}))
    body = json.loads(resp.body)
    assert resp.status_code == 200 and body["success"] and body["changed"] and not body["after_forms"]
    assert "ACORD_131" in {x["form_id"] for x in body["recommendations"]}
    assert [x["line"] for x in body["policy_lines"] if x["producer_added"]] == ["umbrella"]
    assert body["policy_lines"] == body["underwriting_consistency"]["policy_lines"]
    assert "grouped_issues" in body and "package_sqs" in body and "dry_run" in body
    assert store["audit"][0]["field_name"].startswith("policy::added:")
    # ...and removing it takes the line - and its recommendation - away again.
    line_id = next(x["edit_key"] for x in body["policy_lines"] if x["producer_added"])
    resp = asyncio.run(r.policy_line_remove("s-pol", line_id, current_user={"id": "owner"}))
    body = json.loads(resp.body)
    assert not any(x["producer_added"] for x in body["policy_lines"])
    assert "ACORD_131" not in {x["form_id"] for x in body["recommendations"]}


def test_the_route_after_forms_restamps_rescores_and_offers_the_form(merged, generated, monkeypatch):
    mf, flags, docs = merged
    from services.form_service import filter_available_forms, load_all_forms
    row = _session(mf, flags, docs, user_id="owner", generated_forms=copy.deepcopy(generated),
                   selected_form_ids=list(generated), all_forms=filter_available_forms(load_all_forms()),
                   underwriting_confirmations={}, structured_issues=[], cross_issues_last=[],
                   package_sqs={"package_sqs_score": 80, "tier": "Almost There"})
    store = {"row": row}
    r = _stub_route_io(monkeypatch, store)
    req = r.PolicyLineEditRequest(edit_key=AUTO, fields={"policy_number": "BA-7731042"})
    resp = asyncio.run(r.policy_line_edit("s-pol", req, current_user={"id": "owner"}))
    body = json.loads(resp.body)
    assert resp.status_code == 200 and body["after_forms"] and store.get("recalculated")
    assert "ACORD_127" in body["forms_updated"]
    assert store["row"]["generated_forms"]["ACORD_127"]["field_state"][
        "Policy_PolicyNumberIdentifier_A"] == "BA-7731042"
    assert next(x for x in body["policy_lines"] if x["edit_key"] == AUTO)["policy_number"] == "BA-7731042"
    assert body["add_form_offers"] == []                     # an edit adds no line


def test_the_routes_are_registered():
    import main
    paths = {getattr(rt, "path", "") for rt in main.app.routes}
    for p in ("/api/policy-lines/options", "/api/policy-lines/{session_id}",
              "/api/policy-lines/{session_id}/edit", "/api/policy-lines/{session_id}/add",
              "/api/policy-lines/{session_id}/added/{line_id}",
              "/api/policy-lines/{session_id}/add-form"):
        assert p in paths, p


# =============================================================================
# 7. The 125 presence backstop never refuses a premium a person typed
# =============================================================================
def test_a_typed_premium_prints_though_no_document_states_it(merged):
    mf, flags, docs = merged
    sess = _session(mf, flags, docs)
    text = "\n".join(d["text"] for d in docs)
    hay = ps._normalize_for_search(text)
    # An amount no document prints (the backstop's own test, which matches loosely).
    amount = next(a for a in ("$97,531", "$86,429", "$75,318", "$64,207")
                  if not ps._value_in_raw_text(a, hay))
    store, _ = _plan(sess, "edit", edit_key=AUTO, fields={"premium": amount})
    facts, fl = _apply(mf, flags, docs, store)
    schema = _schema("ACORD_125")
    ctx = {**facts, **fl, "_form_id": "ACORD_125"}
    with ps._schema_context(schema):
        got = ps.nonfillable_box_value("CommercialVehicleLineOfBusiness_PremiumAmount_A",
                                       ctx, schema, text, [None])
    assert got and got.replace("$", "").replace(",", "") == amount.replace("$", "").replace(",", "")
    # ...while an amount extraction put on a row and no document prints is still refused.
    rows = copy.deepcopy(mf["coverage_lines"])
    for row in rows:
        if row.get("line") == "Commercial Auto":
            row["premium"] = amount
    ctx2 = {**mf, **flags, "coverage_lines": rows, "_form_id": "ACORD_125"}
    with ps._schema_context(schema):
        refused = ps.nonfillable_box_value("CommercialVehicleLineOfBusiness_PremiumAmount_A",
                                           ctx2, schema, text, [None])
    assert not refused


# =============================================================================
# 8. ACORD 130 - the WC policy's own stated premiums (#7)
# =============================================================================
def _stamp_130(facts, flags, docs):
    schema = _schema("ACORD_130")
    text = "\n".join(str(d.get("text") or "") for d in docs)
    mapped, _conf = ps.map_facts_to_form({**facts, **flags}, schema, form_id="ACORD_130",
                                         raw_text=text, pre_filled_gpt={})
    return {k: v for k, v in mapped.items() if v and "Premium" in k}


TOTAL = "WorkersCompensationLineOfBusiness_TotalEstimatedAnnualPremiumAllStatesAmount_A"
MINIMUM = "WorkersCompensationLineOfBusiness_TotalMinimumPremiumAllStatesAmount_A"
DEPOSIT = "WorkersCompensationLineOfBusiness_TotalDepositPremiumAllStatesAmount_A"
MANUAL = "WorkersCompensation_RateClass_EstimatedManualPremiumAmount_"


def test_the_wc_information_page_reaches_the_130(merged):
    mf, flags, docs = merged
    assert mf["_wc_premiums"]["minimum"] == "$465"
    assert mf["_wc_premiums"]["totals"] == ["29278"]
    got = _stamp_130(mf, flags, docs)
    # The template prints "$" beside the all-states boxes, so the amount prints bare.
    assert got[TOTAL] == "29,278"
    assert got[MINIMUM] == "465"
    assert DEPOSIT not in got                                  # no deposit premium stated
    assert got[MANUAL + "A"] == "$37,600"                      # 5190
    assert got[MANUAL + "B"] == "$597"                         # 8742
    assert got[MANUAL + "C"] == "$180"                         # 8810
    assert not any(k.startswith(MANUAL) and k[-1] not in "ABC" for k in got)
    # One state (CO): the rating sheet's state totals match.
    assert got["WorkersCompensation_RateState_TotalEstimatedAnnualPremiumAmount_A"] == "29,278"
    assert got["WorkersCompensation_RateState_MinimumPremiumAmount_A"] == "465"


def test_the_130_follows_the_125_page_one_premium_rule(merged):
    mf, flags, docs = merged
    facts = copy.deepcopy(mf)
    facts["premium_is_current_policy"] = True       # a new-business quote: not the proposal's
    facts.pop("renews_current_programme", None)     # ...so not a renewal of its own programme
    assert _stamp_130(facts, flags, docs) == {}
    assert wp.premiums_withheld(facts) is True
    # A premium a PERSON entered is the submission's again - on both forms.
    facts["total_policy_premium"] = {"value": "$60,000", "source": "producer"}
    assert wp.premiums_withheld(facts) is False
    assert _stamp_130(facts, flags, docs)[TOTAL] == "29,278"


def test_a_class_row_a_person_changed_prints_no_premium(merged):
    mf, flags, docs = merged
    facts = copy.deepcopy(mf)
    rows = copy.deepcopy(es._fv(facts, "wc_class_codes"))
    rows[1]["payroll"] = "500,000"                    # 8742 re-rated by the producer
    facts["wc_class_codes"] = rows
    got = _stamp_130(facts, flags, docs)
    assert got[MANUAL + "A"] == "$37,600" and got[MANUAL + "C"] == "$180"
    assert MANUAL + "B" not in got                    # never recomputed as payroll x rate


def test_a_class_premium_is_never_computed():
    """A schedule with code, payroll and rate but no printed premium."""
    text = ("CLASSIFICATION SCHEDULE\nCode Description Payroll Rate\n"
            "CO 5190 Electrical Wiring 2,000,000 1.8800\n")
    row = {"code": "5190", "payroll": "2,000,000", "rate": "1.8800", "state": "CO"}
    assert wp._class_line_premium(row, [text]) is None
    printed = text.replace("1.8800", "1.8800 37,600.00") + "Estimated Annual Premium\n"
    assert wp._class_line_premium(row, ["Estimated Annual Premium\n" + printed]) == "$37,600"


def test_the_wc_total_needs_one_policy_and_a_printed_or_typed_amount(merged):
    mf, _flags, _docs_ = merged
    facts = copy.deepcopy(mf)
    assert wp.policy_premium(facts) == "$29,278"
    # An amount extraction invented (printed nowhere) is refused...
    for rec in facts["_line_records"]:
        if rec["line"] == "workers_comp":
            rec["premium"] = 31000.0
    assert wp.policy_premium(facts) is None
    # ...a premium the producer typed is printed.
    for rec in facts["_line_records"]:
        if rec["line"] == "workers_comp":
            rec["producer_fields"] = ["premium"]
    assert wp.policy_premium(facts) == "$31,000"
    # Two WC policies: no one premium is the policy's.
    second = dict(next(r for r in facts["_line_records"] if r["line"] == "workers_comp"),
                  id="workers_comp#OTHER", carrier_name="Other Mutual", policy_number="WC-2")
    facts["_line_records"] = facts["_line_records"] + [second]
    assert wp.policy_premium(facts) is None


def test_minimum_and_deposit_premiums_are_read_only_when_stated_once():
    entries = [{"label": "Policy Minimum Premium", "value": "465.00",
                "line_of_business": "Workers' Compensation and Employers' Liability"}]
    assert wp._stated_once(wp._MINIMUM_RE, entries, []) == "$465"
    clash = entries + [{"label": "Minimum Premium", "value": "750.00",
                        "line_of_business": "Workers Compensation"}]
    assert wp._stated_once(wp._MINIMUM_RE, clash, []) is None
    # A GL declarations' minimum premium is not the WC policy's.
    gl = [{"label": "Minimum Premium", "value": "500.00",
           "line_of_business": "Commercial General Liability"}]
    assert wp._stated_once(wp._MINIMUM_RE, gl, []) is None
    assert wp._stated_once(wp._DEPOSIT_RE, [], ["DEPOSIT PREMIUM $2,500.00"]) == "$2,500"
    assert wp._stated_once(wp._DEPOSIT_RE, [], ["DEPOSIT PREMIUM 2,500.00 1,200.00"]) is None


def test_only_the_wc_policys_own_declarations_are_read_for_a_minimum(merged):
    _mf, _flags, docs = merged
    names = [d["filename"] for d in wp._wc_documents(docs)]
    assert names == ["25-26 Workers Compensation Policy.pdf"]


def test_a_two_state_policy_prints_no_state_sheet_totals(merged):
    mf, flags, docs = merged
    facts = copy.deepcopy(mf)
    rows = copy.deepcopy(es._fv(facts, "wc_class_codes"))
    rows[2]["state"] = "TX"
    facts["wc_class_codes"] = rows
    facts["wc_payroll_by_state"] = {"CO": "$2,426,500", "TX": "$200,000"}
    got = _stamp_130(facts, flags, docs)
    assert got[TOTAL] == "29,278"
    assert "WorkersCompensation_RateState_TotalEstimatedAnnualPremiumAmount_A" not in got
    assert "WorkersCompensation_RateState_MinimumPremiumAmount_A" not in got


def test_no_wc_premium_ever_reaches_the_gap_fill_model(merged):
    mf, flags, _docs_ = merged
    schema = _schema("ACORD_130")
    _m, unmatched, _ = ps.compute_form_gaps("ACORD_130", schema, {**mf, **flags})
    assert not [f for f in unmatched if "Premium" in f], "a premium reached the model"


# =============================================================================
# 7. Follow-ups (7 Oct): an added umbrella / excess layer's own limits and SIR;
#    the pre-form response's dry run; the re-stamp's before-side text
# =============================================================================
LIMITS = {"limit_each_occurrence": "$5,000,000", "limit_aggregate": "$5,000,000", "sir": "$0"}


def _added_layer(merged, **limits):
    mf, flags, docs = merged
    sess = _session(mf, flags, docs)
    store, audit = _plan(sess, "add", line_key="excess", fields={
        "carrier_name": "Markel American Insurance Company", "policy_number": "XS-90001",
        **limits})
    facts, fl = _apply(mf, flags, docs, store)
    sess["facts"] = facts
    row = next(r for r in pl.table_rows(facts) if r["producer_added"])
    return sess, store, facts, fl, row


def test_the_three_limit_names_layers_reads_are_fixed():
    assert pl.UMBRELLA_LIMIT_FIELDS == ("limit_each_occurrence", "limit_aggregate", "sir")


def test_an_added_umbrella_layer_carries_its_own_limits_and_sir(merged):
    mf, _flags, _docs_ = merged
    _sess, _store, facts, _fl, row = _added_layer(merged, **LIMITS)
    assert row["layer"] == "excess"
    assert {f: row[f] for f in pl.UMBRELLA_LIMIT_FIELDS} == LIMITS      # SIR may be $0
    # On the record (the names LAYERS reads for the layer's own ACORD 131)...
    rec = next(r for r in facts["_line_records"] if r.get("id") == row["id"])
    assert {f: rec.get(f) for f in pl.UMBRELLA_LIMIT_FIELDS} == LIMITS
    # ...and on the producer's row, under its own keys - never the generic column.
    added_id = row["edit_key"][len(pl.ADDED_PREFIX):]
    crow = next(r for r in facts["coverage_lines"] if r.get(pl.ROW_ADDED) == added_id)
    assert {f: crow.get(f) for f in pl.UMBRELLA_LIMIT_FIELDS} == LIMITS
    assert not crow.get("limit")
    # The package's umbrella facts stay the documents' (the first layer's).
    for key in ("umbrella_limit", "umbrella_sir", "umbrella_aggregate"):
        assert facts.get(key) == mf.get(key)
    # The documents' rows are untouched.
    for key, doc_row in _rows(mf).items():
        assert _rows(facts)[key] == doc_row


def test_an_added_layer_without_limits_is_still_a_layer(merged):
    _sess, _store, facts, _fl, row = _added_layer(merged)
    assert all(not row[f] for f in pl.UMBRELLA_LIMIT_FIELDS)
    rec = next(r for r in facts["_line_records"] if r.get("id") == row["id"])
    assert all(not rec.get(f) for f in pl.UMBRELLA_LIMIT_FIELDS)


@pytest.mark.parametrize("line,fields,bad", [
    ("excess", {"limit_each_occurrence": "$5,000,000", "limit_aggregate": "$1,000,000"},
     "limit_aggregate"),
    ("excess", {"sir": "-500"}, "sir"),
    ("excess", {"limit_each_occurrence": "0"}, "limit_each_occurrence"),
    ("excess", {"limit_aggregate": "TBD"}, "limit_aggregate"),
    ("umbrella", {"limit_each_occurrence": "about a million"}, "limit_each_occurrence"),
    ("umbrella", {"sir": "$1,000 / $2,000"}, "sir"),
    ("epli", {"limit_each_occurrence": "$1,000,000"}, "limit_each_occurrence"),
    ("auto", {"sir": "$0"}, "sir"),
])
def test_a_limit_is_refused_when_it_is_not_money_or_not_this_lines(merged, line, fields, bad):
    mf, flags, docs = merged
    sess = _session(mf, flags, docs)
    with pytest.raises(pl.PolicyLineError) as exc:
        pl.plan_change(sess, "add", line_key=line, user="u1",
                       fields={"carrier_name": "Markel American Insurance Company", **fields})
    assert bad in exc.value.errors
    if line not in ("umbrella", "excess"):
        assert exc.value.errors[bad] == pl._LIMITS_NOT_HERE_MSG


def test_a_documents_umbrella_takes_no_typed_limits(merged):
    """Its limits come from the documents and Data Consistency."""
    mf, flags, docs = merged
    sess = _session(mf, flags, docs)
    for key in (EXCESS, UMBRELLA):
        with pytest.raises(pl.PolicyLineError) as exc:
            pl.plan_change(sess, "edit", edit_key=key, user="u1",
                           fields={"limit_each_occurrence": "$9,000,000"})
        assert exc.value.errors == {"limit_each_occurrence": pl._LIMITS_FROM_DOCUMENTS_MSG}
    # The table never offers them on a document row.
    assert not any(f in r for r in pl.table_rows(mf) for f in pl.UMBRELLA_LIMIT_FIELDS)


def test_an_added_layers_limits_are_corrected_against_its_own_values(merged):
    mf, flags, docs = merged
    sess, _store, _facts, _fl, row = _added_layer(merged, **LIMITS)
    # The aggregate may not fall under the stored each-occurrence limit.
    with pytest.raises(pl.PolicyLineError) as exc:
        pl.plan_change(sess, "edit", edit_key=row["edit_key"], user="u1",
                       fields={"limit_aggregate": "$4,000,000"})
    assert "limit_aggregate" in exc.value.errors
    store2, audit = _plan(sess, "edit", edit_key=row["edit_key"],
                          fields={"limit_aggregate": "$10,000,000", "sir": "$25,000"})
    assert {a["previous"] for a in audit} == {"$5,000,000", "$0"}
    facts2, _ = _apply(mf, flags, docs, store2)
    again = next(r for r in pl.table_rows(facts2) if r["edit_key"] == row["edit_key"])
    assert again["limit_aggregate"] == "$10,000,000" and again["sir"] == "$25,000"
    assert again["limit_each_occurrence"] == "$5,000,000"
    # A blank clears a limit.
    sess["facts"] = facts2
    store3, _ = _plan(sess, "edit", edit_key=row["edit_key"], fields={"sir": ""})
    facts3, _ = _apply(mf, flags, docs, store3)
    assert not next(r for r in pl.table_rows(facts3) if r["edit_key"] == row["edit_key"])["sir"]


def test_an_added_layers_limits_survive_a_pipeline_rerun(merged, monkeypatch):
    mf, flags, _docs_ = merged
    sess, _store, _facts, _fl, row = _added_layer(merged, **LIMITS)
    prior = copy.deepcopy(mf)
    prior[pl.STORE_KEY] = sess["facts"][pl.STORE_KEY]
    calls = _run_pipeline(monkeypatch, _docs(), prior, flags)
    facts = calls["payload"]["facts"]
    got = next(r for r in pl.table_rows(facts) if r["producer_added"])
    assert {f: got[f] for f in pl.UMBRELLA_LIMIT_FIELDS} == LIMITS
    rec = next(r for r in facts["_line_records"] if r.get("id") == got["id"])
    assert {f: rec.get(f) for f in pl.UMBRELLA_LIMIT_FIELDS} == LIMITS


def test_the_pre_form_response_carries_the_dry_run_and_passes_the_facts(monkeypatch):
    """DRYRUN #8: the response reads the status OBJECT (`.dry_run`) and hands
    the package's facts to the card builder (COPE card routing)."""
    import routes.form_routes as fr
    import routes.policy_line_routes as r
    seen = {}
    status = {"value": fr.PreFormStatus({"package_sqs_score": 77}, {"missing": []},
                                        {"forms": ["ACORD_125"]})}

    async def _status(_sid, facts, _flags, _integrity, _user, session_row=None, **_kw):
        seen["status_facts"] = facts
        return status["value"]

    def _grouped(_structured, _hard, _soft, pkg, cross_issues=None, facts=None):
        seen["facts"], seen["pkg"] = facts, pkg
        return {"hard_stops": [], "warnings": []}

    monkeypatch.setattr(fr, "_pre_form_status", _status)
    monkeypatch.setattr(fr, "_grouped_with_package_caps", _grouped)
    result = {"session_id": "s-pol", "merged_facts": {"applicant_name": "CHOICE ELECTRIC LLC"},
              "mflags": {}, "hard_stops": [], "soft_stops": [], "structured_issues": [],
              "underwriting_consistency": {"policy_lines": [{"edit_key": AUTO}]}}
    body = asyncio.run(r._pre_form_response("s-pol", result, {"id": "owner"}))
    assert body["dry_run"] == {"forms": ["ACORD_125"]}
    assert body["package_sqs"] == {"package_sqs_score": 77} and body["key_details"] == {"missing": []}
    assert seen["facts"] == {"applicant_name": "CHOICE ELECTRIC LLC"} == seen["status_facts"]
    assert seen["pkg"] == {"package_sqs_score": 77}
    assert body["policy_lines"] == [{"edit_key": AUTO}]
    # A status without a dry run (integrity review pending) answers None.
    status["value"] = fr.PreFormStatus(None, None)
    assert asyncio.run(r._pre_form_response("s-pol", result, {"id": "owner"}))["dry_run"] is None


def test_the_restamp_reads_the_old_value_against_the_old_documents_text(merged):
    """The documents door (an upload): the forms were generated from the OLD
    documents. A premium the old text never printed was left blank; the new
    document prints it, so the box moves - which it cannot when the old value
    is read against the new text (same facts, same text -> no difference)."""
    mf, flags, docs = merged
    # A package whose page-one premiums DO print (a quote states them): this test
    # is about the re-stamp door, not Brent's 8 Oct rule that keeps a renewal's
    # expiring premiums off page one.
    mf = {k: v for k, v in mf.items() if k not in ("premium_is_current_policy",)}
    box = "CommercialInlandMarineLineOfBusiness_PremiumAmount_A"
    old_docs = copy.deepcopy(docs)
    for d in old_docs:
        d["text"] = str(d.get("text") or "").replace("$ 2,431.00", "")
    text_before = "\n".join(d["text"] for d in old_docs)
    text_after = "\n".join(str(d.get("text") or "") for d in docs)
    assert text_before != text_after
    gen = _generate(["ACORD_125"], mf, flags, old_docs)
    full = _generate(["ACORD_125"], mf, flags, docs)
    assert box not in gen["ACORD_125"]["field_state"] and full["ACORD_125"]["field_state"][box]
    view = {**mf, **flags, "_package_form_ids": ["ACORD_125"]}
    # Default (one text for both sides): unchanged behaviour - nothing moves.
    same = copy.deepcopy(gen)
    assert pl.restamp_nonfillable_boxes(same, view, view, text_after) == []
    assert box not in same["ACORD_125"]["field_state"]
    # The before side read against the documents the forms were generated from.
    moved = copy.deepcopy(gen)
    assert pl.restamp_nonfillable_boxes(moved, view, view, text_after,
                                        raw_text_before=text_before) == ["ACORD_125"]
    assert moved["ACORD_125"]["field_state"] == full["ACORD_125"]["field_state"]
    assert moved["ACORD_125"]["confidence"][box] == "filled"
    assert moved["ACORD_125"]["pdf_bytes"] is None
    # A box a person typed still stands.
    typed = copy.deepcopy(gen)
    typed["ACORD_125"]["field_state"][box] = "2,500"
    typed["ACORD_125"]["confidence"][box] = "producer"
    pl.restamp_nonfillable_boxes(typed, view, view, text_after, raw_text_before=text_before)
    assert typed["ACORD_125"]["field_state"][box] == "2,500"
