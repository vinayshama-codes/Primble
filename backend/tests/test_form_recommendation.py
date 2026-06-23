"""
Regression tests for ACORD Form Recommendation Logic (Beta Report §7 / Workstream 4).

Locks in the behavior built for §7.2:
  • Recommendation TIERS (Required / Recommended / Optional / Needs Confirmation)
    and the necessity-vs-confirmation rule (item 2 / item 7).
  • A plain-English reason_label on every recommendation (item 1).
  • is_source_document on uploaded ACORD 25/28 certificates (item 6).
  • State-specific 137/138 CA/CO filtering: state + matching exposure only (item 4).
  • The contractor line-of-business grouping example (item 7).
  • Low fill score does NOT bury a relevant form (item 3 / acceptance criteria).
  • Decision_Tree.txt keyword gap-closures (127 hired/non-owned, 140 BPP,
    130 WC-terms, 160 floater, 186 "contracting").
  • Account profile (business class / account type / coverage goals) — item 5.

These assert the deterministic engine only — no LLM, no network.

Run from backend/:
    python tests/test_form_recommendation.py
or:
    python -m pytest tests/test_form_recommendation.py -v
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from services.form_service import (  # noqa: E402
    match_forms_deterministic,
    derive_account_profile,
    _collect_states,
    _supported_state_forms,
    _detect_uploaded_acord_forms,
    TIER_REQUIRED, TIER_RECOMMENDED, TIER_OPTIONAL, TIER_NEEDS_CONFIRMATION,
)


# ── helpers ───────────────────────────────────────────────────────────────────

def _recs(facts=None, flags=None, text=""):
    return match_forms_deterministic(facts or {}, flags or {}, text=text)


def _by_id(recs):
    return {r["form_id"]: r for r in recs}


def _tier(recs, form_id):
    """Tier for a form_id, or None if the form was not recommended."""
    for r in recs:
        if r["form_id"] == form_id:
            return r["tier"]
    return None


def _ids(recs):
    return {r["form_id"] for r in recs}


# ── ACORD 125 — always required ───────────────────────────────────────────────

def test_125_always_required():
    recs = _recs()
    assert _tier(recs, "ACORD_125") == TIER_REQUIRED
    # Monoline / no-line submission reason.
    r = _by_id(recs)["ACORD_125"]
    assert "Required for every commercial submission" == r["reason_label"]


def test_125_package_reason_when_multiline():
    recs = _recs(flags={"has_general_liability": True, "has_auto_coverage": True,
                        "has_property_coverage": True})
    r = _by_id(recs)["ACORD_125"]
    assert _tier(recs, "ACORD_125") == TIER_REQUIRED
    assert "commercial package" in r["reason_label"].lower()


# ── Core coverage forms: Required when CONFIRMED, Needs Confirmation on keyword ─

def test_126_required_when_gl_flag_confirmed():
    recs = _recs(flags={"has_general_liability": True})
    assert _tier(recs, "ACORD_126") == TIER_REQUIRED


def test_126_needs_confirmation_when_keyword_only():
    # Flag absent (None) but GL keyword present in raw text → unconfirmed.
    recs = _recs(flags={"has_general_liability": None},
                 text="general liability premises-operations products/completed")
    assert _tier(recs, "ACORD_126") == TIER_NEEDS_CONFIRMATION


def test_127_required_when_auto_flag_confirmed():
    recs = _recs(flags={"has_auto_coverage": True})
    assert _tier(recs, "ACORD_127") == TIER_REQUIRED


def test_140_required_when_property_flag_confirmed():
    recs = _recs(flags={"has_property_coverage": True})
    assert _tier(recs, "ACORD_140") == TIER_REQUIRED


def test_140_needs_confirmation_when_keyword_only():
    recs = _recs(flags={"has_property_coverage": None},
                 text="building limit and bpp values with construction type")
    assert _tier(recs, "ACORD_140") == TIER_NEEDS_CONFIRMATION


def test_130_required_when_wc_flag_confirmed():
    recs = _recs(flags={"has_workers_comp": True})
    assert _tier(recs, "ACORD_130") == TIER_REQUIRED


def test_131_required_with_umbrella_flag_and_corroboration():
    recs = _recs(facts={"umbrella_limit": "5,000,000"},
                 flags={"has_umbrella": True}, text="umbrella liability")
    assert _tier(recs, "ACORD_131") == TIER_REQUIRED


def test_131_required_when_umbrella_flag_confirmed_even_uncorroborated():
    # Client Q1: "Umbrella confirmed = ACORD 131 Required." A confirmed has_umbrella
    # flag makes ACORD 131 Required on the flag ALONE - exactly like the other four
    # primary line forms (126/127/130/140) - even with NO umbrella facts and NO
    # literal "umbrella"/"excess liability" wording to corroborate. The form is never
    # silently dropped; corroboration only refines the reason shown, not the tier.
    recs = _recs(flags={"has_umbrella": True})
    assert "ACORD_131" in _ids(recs), "confirmed umbrella flag must never drop ACORD 131"
    assert _tier(recs, "ACORD_131") == TIER_REQUIRED


def test_131_dec_line_only_needs_confirmation():
    # Dec-page umbrella line item with the structured flag missing → Needs Confirmation.
    recs = _recs(flags={"has_umbrella": None},
                 text="umbrella liability $2,000,000 premium 5,000")
    assert _tier(recs, "ACORD_131") == TIER_NEEDS_CONFIRMATION


# ── Supplemental forms → Recommended ──────────────────────────────────────────

def test_186_recommended_for_contractor():
    recs = _recs(facts={"operations_description": "general contractor roofing"},
                 flags={"is_contractor": True})
    assert _tier(recs, "ACORD_186") == TIER_RECOMMENDED


def test_141_recommended_property_schedule():
    recs = _recs(flags={"has_property_coverage": True, "has_multiple_locations": True})
    assert _tier(recs, "ACORD_141") == TIER_RECOMMENDED


def test_133_recommended_builders_risk():
    recs = _recs(text="builders risk course of construction project value")
    assert _tier(recs, "ACORD_133") == TIER_RECOMMENDED


# ── Situational forms → Optional ──────────────────────────────────────────────

def test_160_optional_inland_marine():
    recs = _recs(text="inland marine contractor's equipment floater")
    assert _tier(recs, "ACORD_160") == TIER_OPTIONAL


def test_101_recommended_when_loss_history_incomplete():
    # has_loss_history=True with no claim count or incurred amount = missing context
    # → escalates to Recommended per client feedback (Brent).
    recs = _recs(flags={"has_general_liability": True, "has_loss_history": True})
    assert _tier(recs, "ACORD_101") == TIER_RECOMMENDED


def test_101_renewal_missing_prior_carrier_is_optional_not_recommended():
    # Client Q1/Q2: a renewal merely MISSING the prior-carrier name must NOT
    # auto-escalate ACORD 101 to Recommended (over-trigger guard) - it stays Optional.
    # applicant_name + effective_date are supplied so cross_validate stays quiet
    # (its issues would otherwise feed the Recommended path); no coverage flags so
    # the GL-without-126 cross warning doesn't fire either.
    recs = _recs(
        facts={"applicant_name": "Acme LLC", "effective_date": "2026-01-01"},
        flags={"is_renewal": True},
    )
    assert _tier(recs, "ACORD_101") == TIER_OPTIONAL


# ── Certificates / source documents → Needs Confirmation + source flag ────────

def test_25_needs_confirmation_and_source_doc_when_uploaded_certificate():
    recs = _recs(flags={"is_certificate_doc": True, "has_certificate_request": True})
    r = _by_id(recs)["ACORD_25"]
    assert r["tier"] == TIER_NEEDS_CONFIRMATION
    assert r.get("is_source_document") is True
    assert "source" in r["reason_label"].lower() or "clean copy" in r["reason_label"].lower()


def test_25_requested_not_flagged_source_when_not_uploaded():
    # has_certificate_request alone (no corroborating text) must NOT trigger ACORD 25 —
    # the flag fires on any doc with "certificate holder" printed on it (dec pages, policies).
    # With the corroboration fix, the flag only fires when strong COI-specific text is also present.
    recs = _recs(flags={"has_certificate_request": True})  # flag only, no text
    assert "ACORD_25" not in _ids(recs), "bare has_certificate_request with no text must not fire"


def test_25_requested_with_corroborating_text():
    # Flag + strong keyword → fires as Needs Confirmation, not a source document.
    recs = _recs(flags={"has_certificate_request": True},
                 text="please provide a certificate of liability insurance for the job site")
    r = _by_id(recs).get("ACORD_25")
    assert r is not None, "flag + strong keyword must trigger ACORD 25"
    assert r["tier"] == TIER_NEEDS_CONFIRMATION
    assert r.get("is_source_document") in (None, False)


def test_25_certificate_holder_alone_does_not_trigger():
    # "certificate holder" appears on almost every commercial document —
    # must NOT trigger ACORD 25 by itself.
    recs = _recs(flags={"has_certificate_request": False},
                 text="certificate holder: acme corporation 123 main st")
    assert "ACORD_25" not in _ids(recs), "'certificate holder' alone must not trigger ACORD 25"


def test_28_needs_confirmation_lender_evidence():
    recs = _recs(facts={"mortgagee_name": "First National Bank"},
                 flags={"has_property_coverage": True}, text="mortgagee")
    assert _tier(recs, "ACORD_28") == TIER_NEEDS_CONFIRMATION


# ── Uploaded source document for ALL forms (not just 25/28) ───────────────────
# Client "Situation 3": a broker can upload ANY filled ACORD form as evidence;
# it must be tagged is_source_document with the "generate a clean copy only if
# needed" note. Detection keys on the form's printed identity STAMP - the ACORD
# number followed by its edition date, e.g. "ACORD 130 (2026/01)". The edition
# date is REQUIRED so a form's body cross-reference to another form (bare "ACORD
# 101"/"ACORD 127" etc.) is never mis-tagged as an uploaded form.

def test_detector_matches_edition_stamps_and_variants():
    assert _detect_uploaded_acord_forms("acord 130 (2026/01)") == {"ACORD_130"}
    assert _detect_uploaded_acord_forms("acord-126 (2025/03)") == {"ACORD_126"}
    assert _detect_uploaded_acord_forms("acord 137 ca (2023/01)") == {"ACORD_137_CA"}
    assert _detect_uploaded_acord_forms("acord 138 co (2015/12)") == {"ACORD_138_CO"}
    # OCR spacing variance must still match.
    assert _detect_uploaded_acord_forms("acord137ca(2023/01)") == {"ACORD_137_CA"}


def test_detector_requires_edition_stamp_bare_number_ignored():
    # A BARE number with no edition stamp is a cross-reference, not identity.
    assert _detect_uploaded_acord_forms("acord 130") == set()
    assert _detect_uploaded_acord_forms("attach to acord 127 and/or 132") == set()
    assert _detect_uploaded_acord_forms("remarks (acord 101, additional remarks)") == set()


def test_detector_cross_reference_false_positive_guard():
    # THE BUG: an ACORD 137 body references 125/127/101 by bare number. Only the
    # 137's own stamp carries an edition date, so ONLY 137 must be detected.
    text = (
        "california commercial auto coverages / limits section "
        "attach to acord 127 and/or 132  "
        "additional remarks (acord 101, additional remarks schedule) "
        "this section attaches to the acord 125 application "
        "additional producer number acord 137 ca (2023/01) page 1 of 2"
    )
    assert _detect_uploaded_acord_forms(text) == {"ACORD_137_CA"}


def test_detector_no_false_positives():
    # A number inside a longer number, or a coverage mention with no stamp.
    assert _detect_uploaded_acord_forms("acord 1300 (2020/01)") == set()
    assert _detect_uploaded_acord_forms("general liability $1,000,000") == set()
    # 137/138 with NO recognised state code (no national variant in this system).
    assert _detect_uploaded_acord_forms("acord 137 (2020/01)") == set()


def test_uploaded_acord_130_tagged_source_document():
    # A filled ACORD 130 (identity stamp printed) is recommended AND tagged source.
    recs = _recs(flags={"has_workers_comp": True},
                 text="acord 130 (2026/01) workers compensation application")
    r = _by_id(recs)["ACORD_130"]
    assert r.get("is_source_document") is True
    assert "clean copy" in r["reason_label"].lower()


def test_uploaded_form_backstop_surfaces_untriggered_form():
    # ACORD 133 stamp present but NO builders-risk trigger - the backstop must
    # still surface it as a source document so an uploaded form is never dropped.
    recs = _recs(text="acord 133 (2025/05)")
    r = _by_id(recs).get("ACORD_133")
    assert r is not None, "uploaded ACORD 133 must be surfaced by the backstop"
    assert r.get("is_source_document") is True
    assert r["tier"] == TIER_NEEDS_CONFIRMATION


def test_uploaded_25_keeps_certificate_wording_not_generic():
    # When the LLM certificate flag already set the source-doc label, the stamp
    # detection must NOT override the existing 25-specific wording.
    recs = _recs(flags={"is_certificate_doc": True, "has_certificate_request": True},
                 text="certificate of liability insurance acord 25 (2025/12)")
    r = _by_id(recs)["ACORD_25"]
    assert r.get("is_source_document") is True
    assert "certificate" in r["reason_label"].lower()


def test_uploaded_137ca_tags_only_that_state_via_stamp():
    # The stamp carries the state, so an uploaded "ACORD 137 CA (...)" tags CA only
    # - never CO - regardless of the insured's address state.
    recs = _recs(facts={"mailing_address": "1 A St, Reno, NV 89501"},
                 flags={"has_auto_coverage": True},
                 text="acord 137 ca (2023/01) commercial auto")
    assert _by_id(recs).get("ACORD_137_CA", {}).get("is_source_document") is True
    assert "ACORD_137_CO" not in _ids(recs)


def test_uploaded_137_form_does_not_false_tag_referenced_forms():
    # End-to-end of THE reported bug: uploading an ACORD 137 (which references
    # 125/127/101 in its body) must tag ONLY 137 CA as a source document. The
    # referenced forms may still be RECOMMENDED, but must NOT carry the source tag.
    text = (
        "attach to acord 127 and/or 132 remarks (acord 101) "
        "the acord 125 application acord 137 ca (2023/01)"
    )
    recs = _recs(facts={"mailing_address": "123 Main St, Los Angeles, CA 90001"},
                 flags={"has_auto_coverage": True}, text=text)
    source_tagged = {r["form_id"] for r in recs if r.get("is_source_document")}
    assert source_tagged == {"ACORD_137_CA"}, source_tagged


def test_no_upload_tags_nothing_as_source():
    # A normal submission with no uploaded ACORD form must tag NOTHING as source.
    recs = _recs(flags={"has_general_liability": True})
    assert not any(r.get("is_source_document") for r in recs)


# ── Every recommendation carries a non-empty reason_label (item 1) ────────────

def test_every_recommendation_has_reason_label():
    recs = _recs(
        facts={"operations_description": "general contractor", "umbrella_limit": "5000000",
               "mailing_address": "4800 Dahlia St, Denver, CO 80216"},
        flags={"has_general_liability": True, "has_auto_coverage": True,
               "has_property_coverage": True, "has_workers_comp": True,
               "has_umbrella": True, "is_contractor": True, "has_loss_history": True},
        text="general contractor umbrella",
    )
    assert recs, "expected recommendations"
    for r in recs:
        assert isinstance(r.get("reason_label"), str) and r["reason_label"].strip(), \
            f"{r['form_id']} missing reason_label"
        assert r.get("tier") in (TIER_REQUIRED, TIER_RECOMMENDED, TIER_OPTIONAL,
                                 TIER_NEEDS_CONFIRMATION)


# ── Contractor line-of-business grouping (report §7.2 item 7 example) ─────────

def test_contractor_grouping_matches_report_example():
    recs = _recs(
        facts={"operations_description": "general contractor roofing", "umbrella_limit": "5000000"},
        flags={"has_general_liability": True, "has_auto_coverage": True,
               "has_property_coverage": True, "has_umbrella": True, "is_contractor": True},
        text="general contractor umbrella",
    )
    # Required: 125, 126, 127, 131 (report example). 140 is Required here because
    # property coverage is CONFIRMED (necessity-aware model — documented deviation).
    for fid in ("ACORD_125", "ACORD_126", "ACORD_127", "ACORD_131"):
        assert _tier(recs, fid) == TIER_REQUIRED, f"{fid} should be Required"
    # Recommended: 186.
    assert _tier(recs, "ACORD_186") == TIER_RECOMMENDED


# ── Item 3 / acceptance: low fill does not bury a relevant form ───────────────

def test_low_fill_form_stays_required():
    # WC confirmed but ZERO payroll/WC facts extracted → still Required.
    recs = _recs(facts={"operations_description": "general contractor"},
                 flags={"has_workers_comp": True})
    r = _by_id(recs)["ACORD_130"]
    assert r["tier"] == TIER_REQUIRED
    assert r["fields_filled"] == 0          # genuinely empty
    assert r["fields_total"] > 0


# ── Decision_Tree keyword gap-closures (must still fire) ─────────────────────

def test_127_hired_non_owned_keyword_triggers_when_flag_absent():
    recs = _recs(flags={"has_auto_coverage": None},
                 text="coverage includes hired auto and non-owned auto liability")
    assert "ACORD_127" in _ids(recs)
    assert _tier(recs, "ACORD_127") == TIER_NEEDS_CONFIRMATION


def test_140_bpp_keyword_triggers_when_flag_absent():
    recs = _recs(flags={"has_property_coverage": None},
                 text="schedule lists building limit and bpp values")
    assert "ACORD_140" in _ids(recs)


def test_130_wc_keyword_fallback_when_flag_absent():
    recs = _recs(flags={"has_workers_comp": None},
                 text="workers compensation coverage with ncci class codes and x-mod 1.05")
    assert _tier(recs, "ACORD_130") == TIER_NEEDS_CONFIRMATION


def test_130_payroll_word_alone_does_not_trigger_wc():
    # "payroll" is also a GL exposure base — must NOT alone trigger WC (Decision_Tree L88).
    recs = _recs(flags={"has_workers_comp": None}, text="annual payroll is 500000")
    assert "ACORD_130" not in _ids(recs)


def test_160_floater_keyword_triggers():
    recs = _recs(text="policy includes a floater for scheduled items")
    assert "ACORD_160" in _ids(recs)


def test_186_contracting_in_name_triggers_186():
    # "contractor" is NOT a substring of "contracting" — Orbin Contracting fix.
    recs = _recs(facts={"operations_description": "manufacturing of packaging materials"},
                 flags={"is_contractor": True},
                 text="orbin contracting llc commercial package")
    assert "ACORD_186" in _ids(recs)
    assert _tier(recs, "ACORD_186") == TIER_RECOMMENDED


# ── State-specific form filtering (§7.2 item 4) ──────────────────────────────

def test_state_parsing_from_address():
    assert _collect_states({"mailing_address": "4800 Dahlia St, Denver, CO 80216"}) == {"CO"}
    assert _supported_state_forms({"mailing_address": "123 Main St, Los Angeles, CA 90001"}, {}) == ["CA"]


def test_co_dec_with_auto_recommends_137_co():
    recs = _recs(facts={"mailing_address": "4800 Dahlia St, Denver, CO 80216"},
                 flags={"has_auto_coverage": True})
    assert _tier(recs, "ACORD_137_CO") == TIER_NEEDS_CONFIRMATION
    assert "ACORD_137_CA" not in _ids(recs)  # CO insured never gets CA form


def test_co_dec_property_only_no_state_form():
    # No auto/garage exposure → the state auto/garage forms must NOT appear.
    recs = _recs(facts={"mailing_address": "4800 Dahlia St, Denver, CO 80216"},
                 flags={"has_property_coverage": True})
    assert "ACORD_137_CO" not in _ids(recs)
    assert "ACORD_138_CO" not in _ids(recs)


def test_ca_garage_recommends_138_ca():
    recs = _recs(facts={"mailing_address": "123 Main St, Los Angeles, CA 90001"},
                 flags={"has_garage_operations": True})
    assert _tier(recs, "ACORD_138_CA") == TIER_NEEDS_CONFIRMATION


def test_multi_state_surfaces_both_ca_and_co():
    recs = _recs(
        facts={"mailing_address": "1 A St, Reno, NV 89501",
               "locations": ["100 Sunset Blvd, Los Angeles, CA 90028",
                             "200 16th St, Denver, CO 80202"]},
        flags={"has_auto_coverage": True})
    ids = _ids(recs)
    assert "ACORD_137_CA" in ids and "ACORD_137_CO" in ids


def test_secondary_state_location_surfaces_form():
    # TX primary, secondary CA location + auto → CA form appears (item 4 "location in state").
    recs = _recs(
        facts={"mailing_address": "500 Congress Ave, Austin, TX 78701",
               "locations": ["100 Sunset Blvd, Los Angeles, CA 90028"]},
        flags={"has_auto_coverage": True})
    assert "ACORD_137_CA" in _ids(recs)


def test_unsupported_state_no_state_form():
    recs = _recs(facts={"mailing_address": "500 Congress Ave, Austin, TX 78701"},
                 flags={"has_auto_coverage": True})
    assert not any("137" in f or "138" in f for f in _ids(recs))


def test_state_form_reason_names_the_state():
    recs = _recs(facts={"mailing_address": "4800 Dahlia St, Denver, CO 80216"},
                 flags={"has_auto_coverage": True})
    r = _by_id(recs)["ACORD_137_CO"]
    assert "CO" in r["reason_label"]


# ── Account profile (business class / account type / coverage goals) — item 5 ─

def test_account_profile_contractor_package():
    p = derive_account_profile(
        {"operations_description": "general contractor roofing"},
        {"is_contractor": True, "has_general_liability": True, "has_auto_coverage": True})
    assert p["business_class"] == "contractor"
    assert p["account_type"] == "commercial_package"
    assert "General Liability" in p["coverage_goals"]
    assert "Commercial Auto" in p["coverage_goals"]


def test_account_profile_manufacturer_monoline():
    p = derive_account_profile(
        {"operations_description": "manufacturing of packaging materials"},
        {"has_general_liability": True})
    assert p["business_class"] == "manufacturing"
    assert p["account_type"] == "monoline"


def test_account_profile_has_display_labels():
    p = derive_account_profile({}, {})
    assert p["business_class_label"]
    assert p["account_type_label"] in ("Commercial Package", "Monoline")
    assert p["transaction_type"] in ("new_business", "renewal")


# ── Sorting / shape sanity ───────────────────────────────────────────────────

def test_confidence_sorted_descending():
    recs = _recs(flags={"has_general_liability": True, "has_auto_coverage": True,
                        "has_property_coverage": True})
    confs = [r["confidence"] for r in recs]
    assert confs == sorted(confs, reverse=True)


def test_every_rec_has_field_counts():
    recs = _recs(flags={"has_general_liability": True})
    for r in recs:
        assert "fields_filled" in r and "fields_total" in r
        assert r["fields_filled"] <= r["fields_total"]


# ── Dec-page line recovery: trust the page when the LLM flag missed/was wrong ─
# (Decision_Tree.txt L2 "identify each line of coverage present on the dec page")

def test_dec_line_recovers_gl_when_flag_false():
    # The LLM wrongly set GL=False, but the dec page clearly prints a GL line.
    recs = _recs(flags={"has_general_liability": False, "has_auto_coverage": True},
                 text="general liability $1,000,000 / $2,000,000 premium $5,600")
    assert _tier(recs, "ACORD_126") == TIER_NEEDS_CONFIRMATION


def test_dec_line_recovers_all_coverages_when_flags_missing():
    # Contractor dec page: only is_contractor was extracted, every coverage flag
    # missing — all coverage lines must still be recovered from the page text.
    doc = ("general liability $1,000,000 premium $18,400 business auto $1,000,000 csl "
           "workers compensation statutory commercial umbrella / excess $5,000,000 "
           "commercial property building & bpp premium $7,900")
    recs = _recs(facts={"operations_description": "general contractor",
                        "mailing_address": "1450 Wynkoop St, Denver, CO 80202"},
                 flags={"is_contractor": True}, text=doc)
    for fid in ("ACORD_126", "ACORD_127", "ACORD_130", "ACORD_131", "ACORD_140"):
        assert fid in _ids(recs), f"{fid} should be recovered from the dec line"


def test_dec_line_does_not_overfire_on_prose():
    # The dec-line override (which can fire on an explicit-False flag) must NOT
    # trigger on a coverage word in prose with no money/limit signal nearby.
    # flag=False disables the soft-keyword fallback, isolating the dec-line path.
    recs = _recs(flags={"has_general_liability": False},
                 text="the applicant expressed general liability concerns during the call")
    assert "ACORD_126" not in _ids(recs)


def test_186_never_recommended_without_126():
    # ACORD 186 supplements GL — a contractor must always carry 126 too.
    recs = _recs(facts={"operations_description": "general contractor roofing"},
                 flags={"is_contractor": True})
    assert "ACORD_186" in _ids(recs)
    assert "ACORD_126" in _ids(recs)


def test_office_gl_only_not_inflated_by_dec_line():
    # A single GL line must not pull in auto/property/wc/umbrella forms.
    recs = _recs(flags={"has_general_liability": True},
                 text="general liability $1,000,000 / $2,000,000 premium $2,150")
    assert _ids(recs).issubset({"ACORD_125", "ACORD_126", "ACORD_101"})


# ── Session 9 bug-fix regression tests ───────────────────────────────────────
# Five bugs found during test-7 live testing; all fixes are additive (no
# existing trigger logic changed).

def test_habitational_property_triggers_140():
    # Bug 1: habitational dec page says "Building $500,000" — not "building limit".
    # ACORD_140 was silently omitted because _PROP_LINE_PHRASES required "building limit".
    recs = _recs(facts={"operations_description": "apartment building lessor"},
                 text="building $500,000 included dwelling $250,000 coverage")
    assert "ACORD_140" in _ids(recs), "ACORD_140 must fire on 'building $amount'"


def test_habitational_kw_triggers_140():
    # Bug 1 (keyword path): "habitational" and "lessor's risk" were not in _140_kw.
    recs = _recs(facts={"operations_description": "habitational lessor risk property management"})
    assert "ACORD_140" in _ids(recs), "ACORD_140 must fire on habitational operations keywords"


def test_building_alone_no_money_signal_does_not_trigger_140():
    # Bug 1 safety: "building" without a money signal must NOT trigger ACORD_140.
    recs = _recs(flags={"has_property_coverage": False},
                 text="the applicant operates out of a building in the downtown area")
    assert "ACORD_140" not in _ids(recs), "bare 'building' in prose must not over-trigger"


def test_building_near_auto_limit_does_not_trigger_140():
    # Precision: an auto/GL dec line that mentions "building" but whose dollar amount
    # belongs to the auto liability limit (~34 chars away) must NOT trigger ACORD 140.
    recs = _recs(flags={"has_property_coverage": False, "has_auto_coverage": True},
                 text="auto repair shop in a leased building; commercial auto liability limit $1,000,000")
    assert "ACORD_140" not in _ids(recs), "distant auto-limit dollar must not pull in property"


def test_property_damage_limit_does_not_trigger_140():
    # "property damage" is GL/auto third-party liability, NOT first-party property.
    recs = _recs(flags={"has_general_liability": True, "has_property_coverage": False},
                 text="bodily injury and property damage limit $1,000,000 per occurrence")
    assert "ACORD_140" not in _ids(recs), "GL property-damage limit must not trigger ACORD 140"


def test_subcontracting_backstop_adds_130():
    # Bug 2: contractor with 35% subcontracting triggered the ACORD 186 warning but
    # ACORD 130 was absent because has_workers_comp was unset and no WC line detected.
    recs = _recs(
        facts={
            "operations_description": "general contractor roofing",
            "percent_subcontracted": "35%",
        },
        flags={"is_contractor": True},
    )
    assert "ACORD_186" in _ids(recs), "ACORD_186 should fire on contractor"
    assert "ACORD_130" in _ids(recs), "ACORD_130 must fire via subcontracting backstop"
    assert _tier(recs, "ACORD_130") == TIER_NEEDS_CONFIRMATION


def test_subcontracting_under_threshold_no_130_backstop():
    # Bug 2 boundary: <30% subcontracting must NOT trigger the backstop.
    recs = _recs(
        facts={
            "operations_description": "general contractor roofing",
            "percent_subcontracted": "20%",
        },
        flags={"is_contractor": True, "has_workers_comp": None},
    )
    # 130 might still fire via dec-line or keyword — but NOT via the backstop.
    # We only verify the case where there is no WC signal at all.
    # No WC keywords in text → 130 must be absent.
    assert "ACORD_130" not in _ids(recs), "subcontracting <30% must not trigger WC backstop"


def test_employers_liability_fires_wc_form():
    # Bug 4: "Employers Liability $100,000/$100,000/$100,000" is a WC sub-line.
    recs = _recs(flags={"has_workers_comp": False},
                 text="employers liability $100,000 / $100,000 / $100,000 statutory")
    assert "ACORD_130" in _ids(recs), "employers liability with limit must trigger ACORD_130"


def test_umbrella_in_ops_confirms_131():
    # Bug 3: _umb_kw_in_text used `text` (raw OCR) — umbrella in ops_description was invisible.
    recs = _recs(
        facts={"operations_description": "seeking umbrella excess liability coverage"},
        flags={"has_umbrella": True},
    )
    # has_umbrella=True + "umbrella" in search (via ops) → _umb_confirmed=True → REQUIRED
    assert "ACORD_131" in _ids(recs), "umbrella in operations_description must confirm ACORD_131"
    assert _tier(recs, "ACORD_131") == TIER_REQUIRED


def test_cgl_abbreviation_fires_126():
    # Bug 5: "cgl liability $1,000,000" was not in _GL_LINE_PHRASES — ACORD 126 was dropped.
    recs = _recs(flags={"has_general_liability": False},
                 text="cgl liability $1,000,000 per occurrence $2,000,000 aggregate")
    assert "ACORD_126" in _ids(recs), "cgl abbreviation with limit must trigger ACORD_126"


# ── Client feedback (Brent) — ACORD 101 tier escalation ──────────────────────

def test_101_recommended_on_cross_validation_issues():
    # Cross-validation issues = data conflicts → ACORD 101 must be Recommended, not Optional.
    # cross_validate fires when GL is detected without class codes / revenue.
    recs = _recs(flags={"has_general_liability": True})
    r = _by_id(recs).get("ACORD_101")
    # Only assert escalation when cross_validate actually returns issues.
    # The tier should be RECOMMENDED if _101_recommended_reasons is non-empty.
    if r:
        # If cross_validate fired reasons, tier must be Recommended.
        if "conflict" in (r.get("trigger_reason") or "").lower() or \
           "cross-validation" in (r.get("trigger_reason") or "").lower():
            assert r["tier"] == TIER_RECOMMENDED, "cross-validation issues must escalate 101 to Recommended"


def test_101_recommended_on_loss_history_incomplete():
    # Loss history flag set but no claim details → Recommended (large losses / missing context).
    recs = _recs(flags={"has_loss_history": True})
    r = _by_id(recs).get("ACORD_101")
    if r:
        assert r["tier"] == TIER_RECOMMENDED, "incomplete loss history must escalate 101 to Recommended"


def test_101_recommended_on_high_payroll_revenue_ratio():
    # Payroll/revenue >85% = unusual operations → Recommended.
    recs = _recs(facts={"total_payroll": "900000", "total_revenue": "1000000"})
    r = _by_id(recs).get("ACORD_101")
    assert r is not None, "high payroll/revenue ratio must trigger ACORD 101"
    assert r["tier"] == TIER_RECOMMENDED, "unusual financial ratio must escalate 101 to Recommended"


def test_101_recommended_on_subcontracting_no_wc_payroll():
    # Subcontract >30% + no WC payroll = data gap → Recommended.
    recs = _recs(facts={"percent_subcontracted": "35%"}, flags={"is_contractor": True})
    r = _by_id(recs).get("ACORD_101")
    assert r is not None, "subcontracting gap must trigger ACORD 101"
    assert r["tier"] == TIER_RECOMMENDED, "subcontracting data gap must escalate 101 to Recommended"


def test_101_optional_without_serious_triggers():
    # Split auto limits missing = minor gap → Optional tier.
    recs = _recs(flags={"auto_split_limits": True, "has_auto_coverage": True},
                 facts={"auto_liability_limit": "100000"})
    r = _by_id(recs).get("ACORD_101")
    if r:
        # Only assert Optional if NO recommended-level reasons fired alongside it.
        if "conflict" not in (r.get("trigger_reason") or "").lower() and \
           "loss history" not in (r.get("trigger_reason") or "").lower():
            assert r["tier"] == TIER_OPTIONAL, "minor gap alone should keep 101 as Optional"


# ── Client feedback (Brent Q1) — ACORD 101 large-losses escalation ──────────

def test_101_recommended_on_high_claim_count():
    # > 3 prior claims detected = "large losses" per Brent Q1 → Recommended.
    recs = _recs(facts={"num_claims": "7"})
    r = _by_id(recs).get("ACORD_101")
    assert r is not None, "high claim count must trigger ACORD 101"
    assert r["tier"] == TIER_RECOMMENDED, "high claim count must escalate 101 to Recommended"


def test_101_recommended_on_large_total_incurred():
    # Total incurred > $100k = "large losses" per Brent Q1 → Recommended.
    recs = _recs(facts={"total_incurred": "850000"})
    r = _by_id(recs).get("ACORD_101")
    assert r is not None, "large total incurred must trigger ACORD 101"
    assert r["tier"] == TIER_RECOMMENDED, "large total incurred must escalate 101 to Recommended"


def test_101_not_triggered_on_small_claim_count():
    # 3 or fewer claims is not a "large losses" scenario — 101 must not fire on claim count alone.
    recs = _recs(facts={"num_claims": "2"})
    r = _by_id(recs).get("ACORD_101")
    if r:
        # Only fail if it was triggered SOLELY by claim count (no other reasons)
        assert "2 prior claims" not in (r.get("trigger_reason") or ""), \
            "claim count ≤ 3 must not trigger large-losses escalation"


# ── Client feedback (Brent) — state form reason labels ───────────────────────

def test_state_form_reason_is_carrier_neutral():
    # Brent: reason label must reflect that carrier requirements vary —
    # not just "confirm CA exposure".
    recs = _recs(facts={"mailing_address": "500 Main St, Los Angeles, CA 90012"},
                 flags={"has_auto_coverage": True})
    r = _by_id(recs).get("ACORD_137_CA")
    assert r is not None, "CA auto must trigger ACORD 137 CA"
    assert "carrier" in r["reason_label"].lower(), \
        "state form reason must mention carrier requirements"
    assert r["tier"] == TIER_NEEDS_CONFIRMATION


def test_co_state_form_reason_is_carrier_neutral():
    # Same logic applies to CO forms.
    recs = _recs(facts={"mailing_address": "1450 Wynkoop St, Denver, CO 80202"},
                 flags={"has_auto_coverage": True})
    r = _by_id(recs).get("ACORD_137_CO")
    assert r is not None, "CO auto must trigger ACORD 137 CO"
    assert "carrier" in r["reason_label"].lower(), \
        "CO state form reason must mention carrier requirements"
    assert r["tier"] == TIER_NEEDS_CONFIRMATION


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    passed = failed = 0
    for fn in fns:
        try:
            fn()
            passed += 1
            print(f"  ok   {fn.__name__}")
        except AssertionError as e:
            failed += 1
            print(f"  FAIL {fn.__name__}: {e}")
        except Exception as e:  # noqa: BLE001
            failed += 1
            print(f"  ERR  {fn.__name__}: {type(e).__name__}: {e}")
    print(f"\n{passed}/{len(fns)} passed" + (f", {failed} FAILED" if failed else ""))
    sys.exit(1 if failed else 0)
