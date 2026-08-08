"""
Regression tests for Core Underwriting Data Consistency (Beta Report §4.3).

Covers the four acceptance criteria for Gross Sales (total_revenue):
  • Extracted and NORMALIZED where present ($1,000,000 == 1000000 == 1,000,000.00).
  • Conflicting values are flagged for review (non-blocking).
  • The source document of each value is visible.
  • A user-confirmed value is applied as producer-verified evidence and clears
    the review.

Run from backend/:
    python tests/test_underwriting_consistency.py
or:
    python -m pytest tests/test_underwriting_consistency.py -v
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from services.underwriting_consistency import (  # noqa: E402
    assess_underwriting_consistency, apply_confirmations, validate_confirmation,
    _normalize_currency, RECONCILABLE_FIELDS, RECONCILABLE_FIELD_KEYS,
    _text_scan_values, _NAME_LIKE_FIELDS, _TEXT_SCAN_EXEMPT_FIELDS,
    _TEXT_SCAN_PATTERNS, _scan_shape, _scan_min_amount,
    _SCAN_SHAPE_CURRENCY, _SCAN_SHAPE_INTEGER, _SCAN_SHAPE_FEIN, _SCAN_SHAPE_DATE,
    _SCAN_FLOOR_EXPOSURE, _SCAN_FLOOR_RETENTION,
)

# The complete set of bounded (machine-checkable) capture shapes. Used by the
# standing guard to assert no loose prose capture is ever reintroduced.
_BOUNDED_SHAPES = frozenset({
    _SCAN_SHAPE_CURRENCY, _SCAN_SHAPE_INTEGER, _SCAN_SHAPE_FEIN, _SCAN_SHAPE_DATE,
})


def _doc(doc_id, filename, doc_type, revenue):
    return {"doc_id": doc_id, "filename": filename, "doc_type": doc_type,
            "facts": {"total_revenue": revenue}}


def test_currency_normalization_collapses_formatting():
    assert _normalize_currency("$1,000,000") == "1000000"
    assert _normalize_currency("1000000") == "1000000"
    assert _normalize_currency("1,000,000.00") == "1000000"
    assert _normalize_currency(" $ 1,000,000.0 ") == "1000000"
    assert _normalize_currency("1200000.50") == "1200000.5"
    assert _normalize_currency("abc") is None
    assert _normalize_currency("") is None


def test_conflict_flagged_with_sources():
    docs = [
        _doc("a", "dec.pdf", "dec_page", "$1,000,000"),
        _doc("b", "app.pdf", "application", {"value": "1200000", "confidence": "ai_high"}),
    ]
    v = assess_underwriting_consistency(docs, {"total_revenue": "1000000"})
    assert v["review_required"] is True
    assert v["conflict_count"] == 1
    f = v["fields"][0]
    assert f["fact_key"] == "total_revenue"
    assert f["status"] == "conflict"
    assert len(f["values"]) == 2
    # Source documents are visible per value (§4.3 acceptance: "source ... visible").
    filenames = {s["filename"] for val in f["values"] for s in val["sources"]}
    assert filenames == {"dec.pdf", "app.pdf"}


def test_formatting_difference_is_not_a_conflict():
    docs = [
        _doc("a", "dec.pdf", "dec_page", "$1,000,000"),
        _doc("b", "app.pdf", "application", "1000000.00"),
    ]
    v = assess_underwriting_consistency(docs, {"total_revenue": "1000000"})
    assert v["review_required"] is False
    assert v["fields"][0]["status"] == "consistent"


def test_single_value_is_consistent_with_source():
    docs = [_doc("a", "dec.pdf", "dec_page", "$2,500,000")]
    v = assess_underwriting_consistency(docs, {"total_revenue": "2500000"})
    assert v["review_required"] is False
    f = v["fields"][0]
    assert f["status"] == "consistent"
    assert f["values"][0]["sources"][0]["filename"] == "dec.pdf"


def test_absent_field_is_omitted():
    docs = [{"doc_id": "a", "filename": "x.pdf", "doc_type": "dec_page", "facts": {}}]
    v = assess_underwriting_consistency(docs, {})
    assert v["fields"] == []
    assert v["review_required"] is False


def test_confirmation_resolves_and_applies_as_producer_value():
    docs = [
        _doc("a", "dec.pdf", "dec_page", "$1,000,000"),
        _doc("b", "app.pdf", "application", "1200000"),
    ]
    confirmed = {"total_revenue": validate_confirmation("total_revenue", "$1,000,000")}
    v = assess_underwriting_consistency(docs, {"total_revenue": "1000000"}, confirmations=confirmed)
    assert v["review_required"] is False
    assert v["fields"][0]["status"] == "confirmed"

    merged = apply_confirmations({"total_revenue": "stale"}, confirmed)
    env = merged["total_revenue"]
    assert env["value"] == "$1,000,000"
    # Producer-verified (full SQS credit) but labelled distinct from source docs.
    assert env["confidence"] == "client_arq"
    assert env["source"] == "user_confirmed"


def test_validate_confirmation_rejects_non_numeric():
    for bad in ("", "abc", None, "$$"):
        try:
            validate_confirmation("total_revenue", bad)
            assert False, f"expected ValueError for {bad!r}"
        except ValueError:
            pass
    try:
        validate_confirmation("not_a_field", "5")
        assert False, "expected ValueError for unknown field"
    except ValueError:
        pass


def test_engine_is_config_driven():
    # Gross Sales is seeded; the engine is keyed off RECONCILABLE_FIELDS so
    # adding similar fields is a config-only change (§4.3 "and similar fields").
    assert "total_revenue" in RECONCILABLE_FIELDS
    assert RECONCILABLE_FIELDS["total_revenue"]["kind"] == "currency"
    assert "total_revenue" in RECONCILABLE_FIELD_KEYS


def _bldg_doc(doc_id, filename, doc_type, value):
    return {"doc_id": doc_id, "filename": filename, "doc_type": doc_type,
            "facts": {"property_building_value": value}}


def test_building_value_conflict_flagged_for_review():
    # Client Property Integrity: building values inconsistent across documents
    # must be flagged for review before forms are generated.
    docs = [
        _bldg_doc("a", "dec.pdf", "dec_page", "$500,000"),
        _bldg_doc("b", "sov.pdf", "sov", "750000"),
    ]
    v = assess_underwriting_consistency(docs, {"property_building_value": "500000"})
    assert v["review_required"] is True
    f = next(x for x in v["fields"] if x["fact_key"] == "property_building_value")
    assert f["status"] == "conflict"
    assert len(f["values"]) == 2


def test_building_value_formatting_difference_is_not_a_conflict():
    docs = [
        _bldg_doc("a", "dec.pdf", "dec_page", "$500,000"),
        _bldg_doc("b", "sov.pdf", "sov", "500000.00"),
    ]
    v = assess_underwriting_consistency(docs, {"property_building_value": "500000"})
    f = next(x for x in v["fields"] if x["fact_key"] == "property_building_value")
    assert f["status"] == "consistent"
    assert v["review_required"] is False


def test_name_like_fields_never_text_scan():
    # applicant_name / dba_name / carrier_name must return [] unconditionally,
    # regardless of what the raw text contains — the text-scan safety net is
    # architecturally disabled for these fields (see _NAME_LIKE_FIELDS), not
    # filtered case-by-case. Two client-reported bad suggestions (a "WHO IS AN
    # INSURED" list item, then an "architects, engineers or surveyors"
    # exclusion clause) both came from this scan; patching the plausibility
    # filter per-clause is whack-a-mole, so the scan itself is gone for these
    # fields. Every reconcilable name field must be covered by this test.
    assert _NAME_LIKE_FIELDS == frozenset({"applicant_name", "dba_name", "carrier_name"})
    boilerplate = (
        "SECTION II - WHO IS AN INSURED - c. Any person or organization "
        "having proper temporary custody of your property if you die\n"
        "This insurance does not apply to any architects, engineers or "
        "surveyors not engaged by you. Insured: Real Company Name\n"
    )
    for key in _NAME_LIKE_FIELDS:
        assert _text_scan_values(boilerplate, key) == []


def test_address_fields_never_text_scan():
    # Same bug class, different field: mailing_address/physical_address share
    # the exact unbounded, unchecked value-capture pattern that broke
    # applicant_name, just triggered by "mailing"/"physical address" instead
    # of "insured". Both are exempted the same way — proven with the client's
    # literal reproduction, not a synthetic stand-in (per
    # replay-client-report-verbatim).
    mailing_boilerplate = (
        "This policy requires that the mailing of such notice will be "
        "sufficient proof of notice. in compliance with laws, rules, or\n"
        "regulations of any state.\n"
    )
    assert _text_scan_values(mailing_boilerplate, "mailing_address") == []

    physical_boilerplate = (
        "We will pay for physical damage to the property. The physical "
        "address requirement under state law applies to all locations "
        "regardless of use.\n"
    )
    assert _text_scan_values(physical_boilerplate, "physical_address") == []


def test_entity_type_never_text_scans_rating_boilerplate():
    # Found by sweep, not by a client report: entity_type's value is a small
    # free-text set (LLC / Corporation / ...) with no checkable shape, and
    # normalize_entity_type is a synonym passthrough, NOT a validator — it
    # returns unrecognised prose unchanged, so a captured clause would have
    # become a "Suggested" value exactly like the three reported incidents.
    boilerplate = (
        "Coverage is determined based on the business type - not otherwise "
        "classified for rating purposes\nunder this endorsement.\n"
    )
    assert _text_scan_values(boilerplate, "entity_type") == []


def test_exempt_set_is_exactly_the_free_text_fields():
    # The derived exemption must cover every free-text field and NOTHING else.
    # Pinned explicitly so silently exempting a bounded field (which would
    # quietly delete a working safety net) fails the build just as loudly as
    # forgetting to exempt a free-text one.
    assert _TEXT_SCAN_EXEMPT_FIELDS == frozenset({
        "applicant_name", "dba_name", "carrier_name",
        "mailing_address", "physical_address", "entity_type",
    })
    # It is a strict superset of the ranking set — merging the two would
    # change how address conflicts are ranked as a scanning-fix side effect.
    assert _NAME_LIKE_FIELDS < _TEXT_SCAN_EXEMPT_FIELDS


def test_numeric_fields_reject_prose():
    # The other half of the bug: currency/integer fields were routed through
    # the PROSE-shaped generic fallback, so a sentence captured cleanly and
    # (for integer) was then validated by the generic TEXT normalizer with no
    # numeric check at all. Reproduces the sweep finding verbatim.
    assert _text_scan_values(
        "Employee Count - varies seasonally based on staffing needs\n"
        "of the business.\n", "num_employees") == []
    assert _text_scan_values(
        "Umbrella SIR - subject to the terms and conditions stated herein\n",
        "umbrella_sir") == []
    assert _text_scan_values(
        "GL Deductible - none applies under this form\n", "gl_deductible") == []


def test_bounded_fields_still_find_real_values():
    # The safety net must still WORK — its original job (catching a figure the
    # LLM collapsed across documents) is real and unchanged. A fix that
    # silently neutered scanning would pass every negative test above.
    assert _text_scan_values("Employee Count: 47 full-time staff\n",
                             "num_employees") == ["47"]
    assert _text_scan_values("Employee Count: 1,250\n",
                             "num_employees") == ["1,250"]
    assert _text_scan_values("Annual Revenue: $4,500,000\n",
                             "total_revenue") == ["$4,500,000"]
    assert _text_scan_values("Total Payroll: $2,300,000\n",
                             "total_payroll") == ["$2,300,000"]
    assert _text_scan_values("Building Value: $750,000\n",
                             "property_building_value") == ["$750,000"]
    assert _text_scan_values("Policy Effective Date: 07/15/2025\n",
                             "effective_date") == ["07/15/2025"]
    assert _text_scan_values("FEIN: 84-2210987\n", "fein") == ["84-2210987"]
    # Generic-fallback field (no bespoke pattern) with a real currency value.
    assert _text_scan_values("Umbrella SIR: $25,000\n",
                             "umbrella_sir") == ["$25,000"]


def test_every_reconcilable_field_has_a_resolved_scan_shape():
    # STANDING GUARD. The module docstring advertises a new reconcilable field
    # as "a one-line config add, not new bespoke code" — true, but that one
    # line silently inherits whatever the text-scan does by default. Three of
    # the four incidents were exactly that: a field added without anyone
    # deciding whether its value can be safely regex-matched out of raw prose.
    # Every field must resolve to a real capture shape or be knowingly exempt;
    # there is no third state.
    for fact_key, cfg in RECONCILABLE_FIELDS.items():
        shape = _scan_shape(fact_key, cfg)
        assert shape is None or isinstance(shape, str) and shape, fact_key
        if shape is None:
            assert fact_key in _TEXT_SCAN_EXEMPT_FIELDS, fact_key
        else:
            # A scannable field must declare a label (the generic fallback
            # needs one) or ship a bespoke pattern.
            assert cfg.get("label") or fact_key in _TEXT_SCAN_PATTERNS, fact_key
            # And its shape must actually be one of the bounded shapes — never
            # a loose prose capture reintroduced by hand.
            assert shape in _BOUNDED_SHAPES, fact_key


def test_scan_floor_is_derived_from_money_role_not_listed_per_field():
    # The 10,000 floor is right for business-scale EXPOSURE figures reached by
    # loose labels ("revenue", "sales") and wrong for RETENTION figures, which
    # are small by nature. Classification is derived from the key/label, so a
    # field added later lands in the right bucket with no edit to the table.
    for key in ("total_revenue", "total_payroll", "property_building_value"):
        assert _scan_min_amount(key, RECONCILABLE_FIELDS[key]) == _SCAN_FLOOR_EXPOSURE, key
    for key in ("umbrella_sir", "gl_deductible",
                "auto_deductible_comp", "auto_deductible_collision"):
        assert _scan_min_amount(key, RECONCILABLE_FIELDS[key]) == _SCAN_FLOOR_RETENTION, key
    # Counts have no meaningful magnitude floor - "Employee Count: 3" is real.
    assert _scan_min_amount("num_employees", RECONCILABLE_FIELDS["num_employees"]) == 0

    # GENERIC, not hardcoded: fields that do not exist yet classify correctly.
    for future_key in ("property_deductible", "cyber_retention", "wc_sir",
                       "equipment_deductible"):
        assert _scan_min_amount(
            future_key, {"kind": "currency", "label": "x"}
        ) == _SCAN_FLOOR_RETENTION, future_key
    for future_key in ("total_assets", "annual_receipts", "building_limit"):
        assert _scan_min_amount(
            future_key, {"kind": "currency", "label": "x"}
        ) == _SCAN_FLOOR_EXPOSURE, future_key
    # The label alone is enough when the key is abbreviated.
    assert _scan_min_amount(
        "prop_ded_amt", {"kind": "currency", "label": "Property Deductible"}
    ) == _SCAN_FLOOR_RETENTION
    # Token matching, never substring - "sir" must not fire inside a word.
    assert _scan_min_amount(
        "desired_limit", {"kind": "currency", "label": "Desired Limit"}
    ) == _SCAN_FLOOR_EXPOSURE


def test_retention_fields_scan_realistic_small_amounts():
    # The defect: every retention field shared the 10,000 exposure floor, so a
    # realistic deductible was silently discarded and their safety net had
    # never once fired. Uses the client's literal reported figure ($1,000 auto
    # deductible), per replay-client-report-verbatim.
    assert _text_scan_values("Auto Comprehensive Deductible: $1,000\n",
                             "auto_deductible_comp") == ["$1,000"]
    assert _text_scan_values("Auto Collision Deductible: $1,000\n",
                             "auto_deductible_collision") == ["$1,000"]
    assert _text_scan_values("GL Deductible: $500\n",
                             "gl_deductible") == ["$500"]
    # $0 SIR is the normal, healthy structure - it must scan, not be floored.
    assert _text_scan_values("Umbrella SIR: $0\n", "umbrella_sir") == ["$0"]


def test_exposure_floor_still_filters_stray_small_numbers():
    # Removing the floor where it was wrong must not remove it where it works:
    # revenue/payroll labels are loose enough to hit a ratio-table entry.
    assert _text_scan_values("Revenue: $5\n", "total_revenue") == []
    assert _text_scan_values("Total Payroll: $300\n", "total_payroll") == []
    assert _text_scan_values("Annual Revenue: $4,500,000\n",
                             "total_revenue") == ["$4,500,000"]


def test_every_numeric_field_resolves_a_floor():
    # STANDING GUARD, same reason as the scan-shape one: a numeric field added
    # later must land in a known money role rather than inheriting a floor
    # nobody chose for it.
    for fact_key, cfg in RECONCILABLE_FIELDS.items():
        if cfg["kind"] not in ("currency", "integer"):
            continue
        floor = _scan_min_amount(fact_key, cfg)
        assert isinstance(floor, int) and floor >= 0, fact_key
        assert floor in (_SCAN_FLOOR_EXPOSURE, _SCAN_FLOOR_RETENTION, 0), fact_key


def test_no_bespoke_pattern_exists_for_an_exempt_field():
    # A bespoke pattern for an exempt field is unreachable dead code that
    # reads as though scanning were active — the trap that made entity_type
    # look covered while it was quietly producing garbage.
    assert not (_TEXT_SCAN_EXEMPT_FIELDS & set(_TEXT_SCAN_PATTERNS))


def test_address_conflict_still_ranks_by_completeness_not_doc_count():
    # The text-scan removal must NOT change how a genuine address conflict is
    # ranked. Unlike names, addresses have a real structural completeness
    # signal (ZIP+4) — that must stay the primary ranking signal, not get
    # swept into the doc-count-first rule that exists only because names have
    # no such signal. One doc reports a ZIP+4 address, two docs (majority)
    # report the same address without it: completeness must still win.
    docs = [
        {"doc_id": "a", "filename": "app.pdf", "doc_type": "application",
         "facts": {"mailing_address": "123 Main St, Denver, CO 80216-1234"}, "text": ""},
        {"doc_id": "b", "filename": "dec.pdf", "doc_type": "dec_page",
         "facts": {"mailing_address": "456 Oak Ave"}, "text": ""},
        {"doc_id": "c", "filename": "loss_run.pdf", "doc_type": "loss_run",
         "facts": {"mailing_address": "456 Oak Ave"}, "text": ""},
    ]
    v = assess_underwriting_consistency(docs, {})
    f = next(x for x in v["fields"] if x["fact_key"] == "mailing_address")
    assert f["status"] == "conflict"
    assert f["suggested_value"] == "123 Main St, Denver, CO 80216-1234"


def test_mailing_address_conflict_prefers_real_address_over_boilerplate_fragment():
    # End-to-end reproduction of the exact client report: the LLM correctly
    # extracts the real mailing address, but the document's own raw text also
    # carries an unrelated "notice of mailing" clause that the old text-scan
    # would have surfaced as a competing "Suggested" candidate. It must not
    # even survive as a second value.
    text = (
        "This policy requires that the mailing of such notice will be "
        "sufficient proof of notice. in compliance with laws, rules, or\n"
        "regulations of any state.\n"
    )
    docs = [{
        "doc_id": "a", "filename": "package.pdf", "doc_type": "dec_page",
        "facts": {"mailing_address": "789 Industrial Pkwy, Denver, CO 80216"},
        "text": text,
    }]
    v = assess_underwriting_consistency(
        docs, {"mailing_address": "789 Industrial Pkwy, Denver, CO 80216"}
    )
    f = next(x for x in v["fields"] if x["fact_key"] == "mailing_address")
    assert len(f["values"]) == 1
    assert f["status"] == "consistent"


def test_applicant_name_conflict_prefers_real_name_over_boilerplate_fragment():
    # Reproduces both client-reported bad suggestions end-to-end: the LLM
    # correctly extracts the real applicant name from a document whose raw
    # text is full of "WHO IS AN INSURED" / exclusion-clause boilerplate.
    # Since name fields no longer text-scan at all, neither fragment can ever
    # surface as a second candidate.
    text = (
        "SECTION II - WHO IS AN INSURED - c. Any person or organization "
        "having proper temporary custody of your property if you die\n"
        "This insurance does not apply to any architects, engineers or "
        "surveyors not engaged by you but who are engaged by you.\n"
    )
    docs = [{
        "doc_id": "a", "filename": "package.pdf", "doc_type": "dec_page",
        "facts": {"applicant_name": "ORBIN CONTRACTING LLC"},
        "text": text,
    }]
    v = assess_underwriting_consistency(docs, {"applicant_name": "ORBIN CONTRACTING LLC"})
    f = next(x for x in v["fields"] if x["fact_key"] == "applicant_name")
    assert len(f["values"]) == 1
    assert f["status"] == "consistent"


def test_applicant_name_still_flags_genuine_cross_document_conflict():
    # Disabling the text-scan must not disable real conflict detection: two
    # documents whose LLM-extracted names genuinely differ still conflict.
    docs = [
        {"doc_id": "a", "filename": "app.pdf", "doc_type": "application",
         "facts": {"applicant_name": "ORBIN CONTRACTING LLC"}, "text": ""},
        {"doc_id": "b", "filename": "dec.pdf", "doc_type": "dec_page",
         "facts": {"applicant_name": "Summit Builders Inc"}, "text": ""},
    ]
    v = assess_underwriting_consistency(docs, {})
    f = next(x for x in v["fields"] if x["fact_key"] == "applicant_name")
    assert f["status"] == "conflict"
    assert len(f["values"]) == 2


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    passed = 0
    for fn in fns:
        fn()
        passed += 1
        print(f"  ok  {fn.__name__}")
    print(f"\n{passed}/{len(fns)} passed")
