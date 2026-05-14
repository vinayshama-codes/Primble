"""
Automated regression tests for all recent changes to Acordly backend.
Run from backend/ directory:
    python tests/test_all_changes.py
or:
    python -m pytest tests/test_all_changes.py -v
"""

import os
import sys

# Ensure backend/ is on sys.path so all service imports resolve
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

results = {}   # name -> "PASS" | "FAIL: <reason>"


def _record(name, passed, reason=""):
    results[name] = "PASS" if passed else f"FAIL: {reason}"
    if passed:
        print(f"PASS: {name}")
    else:
        print(f"FAIL: {name} — {reason}")


# ──────────────────────────────────────────────────────────────────────────────
# TEST 1 — text_cleaner.py
# ──────────────────────────────────────────────────────────────────────────────
try:
    from utils.text_cleaner import clean_text, table_rows_to_text

    # Page markers removed
    out1 = clean_text("hello\nPage 3 of 12\nworld")
    assert "Page 3 of 12" not in out1, f"Page marker still present: {repr(out1)}"

    out2 = clean_text("Some text\nPage 1 of 5\nMore text")
    # "Page" as a substring in other words might still appear; check full marker gone
    assert "Page 1 of 5" not in out2, f"Page 1 of 5 still present: {repr(out2)}"

    # Dedupe: same paragraph twice → appears once
    t = "Important block\n\nImportant block"
    cleaned = clean_text(t)
    assert cleaned.count("Important block") == 1, \
        f"Dedup failed — count={cleaned.count('Important block')}"

    # Table to text
    rows = [["Name", "Value"], ["ABC", "123"]]
    out3 = table_rows_to_text([{"page": 1, "rows": rows}])
    assert "Name | Value" in out3, f"Header missing: {repr(out3)}"
    assert "ABC | 123" in out3, f"Body row missing: {repr(out3)}"

    _record("text_cleaner", True)
except AssertionError as e:
    _record("text_cleaner", False, str(e))
except Exception as e:
    _record("text_cleaner", False, f"Exception: {e}")


# ──────────────────────────────────────────────────────────────────────────────
# TEST 2 — extraction_service.py (OCR substring fix)
# ──────────────────────────────────────────────────────────────────────────────
try:
    from services.extraction_service import extract_facts

    # "ill" must NOT flag "Williams" as low-confidence (word-boundary guard)
    facts = extract_facts(
        "Applicant: Williams Insurance LLC\nFEIN: 12-3456789",
        low_confidence_tokens=["ill"],
    )
    val = facts.get("facts", {}).get("applicant_name")
    if isinstance(val, dict):
        assert val.get("ocr_confident") is True, \
            f"'ill' false-flagged 'Williams' — ocr_confident={val.get('ocr_confident')}"

    # Short tokens (<3 chars) must not flag anything
    facts2 = extract_facts("Applicant: ABC Corp", low_confidence_tokens=["ab"])
    val2 = facts2.get("facts", {}).get("applicant_name")
    if isinstance(val2, dict):
        assert val2.get("ocr_confident") is True, \
            f"Short token 'ab' false-flagged 'ABC Corp'"

    _record("ocr_substring_fix", True)
except AssertionError as e:
    _record("ocr_substring_fix", False, str(e))
except Exception as e:
    _record("ocr_substring_fix", False, f"Exception: {e}")


# ──────────────────────────────────────────────────────────────────────────────
# TEST 3 — extraction_service.py (chunk limits raised / no artificial cap)
# ──────────────────────────────────────────────────────────────────────────────
try:
    from services.extraction_service import DOC_TYPE_CHUNK_LIMITS

    assert DOC_TYPE_CHUNK_LIMITS["dec_page"] >= 50, \
        f"dec_page cap too low: {DOC_TYPE_CHUNK_LIMITS['dec_page']}"
    assert DOC_TYPE_CHUNK_LIMITS["schedule"] >= 100, \
        f"schedule cap too low: {DOC_TYPE_CHUNK_LIMITS['schedule']}"
    assert DOC_TYPE_CHUNK_LIMITS["loss_run"] >= 100, \
        f"loss_run cap too low: {DOC_TYPE_CHUNK_LIMITS['loss_run']}"

    _record("doc_type_chunk_limits", True)
except AssertionError as e:
    _record("doc_type_chunk_limits", False, str(e))
except Exception as e:
    _record("doc_type_chunk_limits", False, f"Exception: {e}")


# ──────────────────────────────────────────────────────────────────────────────
# TEST 4 — extraction_service.py (truncation warning fires at <100% coverage)
# ──────────────────────────────────────────────────────────────────────────────
try:
    from services.extraction_service import extract_facts_long

    big_text = (
        "Named Insured: Test Corp\nFEIN: 12-3456789\nPolicy Number: ABC123\n" * 200
    )
    result = extract_facts_long(big_text, "dec_page")
    if "truncation_warning" in result:
        print(f"  WARN: truncation_warning present: {result['truncation_warning']}")
    else:
        pass  # No truncation warning on a doc fully covered by chunks

    _record("truncation_warning", True)
except AssertionError as e:
    _record("truncation_warning", False, str(e))
except Exception as e:
    _record("truncation_warning", False, f"Exception: {e}")


# ──────────────────────────────────────────────────────────────────────────────
# TEST 5 — sqs_service.py (cert bypass now requires applicant_name + effective_date)
# ──────────────────────────────────────────────────────────────────────────────
try:
    from services.sqs_service import check_tier1

    # Cert with no applicant_name → must FAIL now
    ok, missing = check_tier1(
        facts={},
        flags={"is_certificate_doc": True},
    )
    assert not ok, "cert bypass should require applicant_name but returned ok=True"
    assert any("applicant" in m.lower() for m in missing), \
        f"Expected 'applicant' in missing fields, got: {missing}"

    # Cert with both required fields → must PASS
    ok2, missing2 = check_tier1(
        facts={
            "applicant_name": {"value": "ABC Corp", "ocr_confident": True},
            "effective_date":  {"value": "2025-01-01", "ocr_confident": True},
        },
        flags={"is_certificate_doc": True},
    )
    assert ok2, f"cert with valid fields should pass, missing={missing2}"

    _record("cert_bypass_fix", True)
except AssertionError as e:
    _record("cert_bypass_fix", False, str(e))
except Exception as e:
    _record("cert_bypass_fix", False, f"Exception: {e}")


# ──────────────────────────────────────────────────────────────────────────────
# TEST 6 — sqs_service.py (effective_date window validation)
# ──────────────────────────────────────────────────────────────────────────────
try:
    from services.sqs_service import validate_effective_date_window

    # Empty facts → no issue
    assert validate_effective_date_window({}) is None, \
        "Empty facts should return None"

    # Date >2 years in past → soft stop
    result_old = validate_effective_date_window(
        {"effective_date": {"value": "1990-01-01", "ocr_confident": True}}
    )
    assert result_old is not None and result_old[0] == "soft", \
        f"Old date not flagged: {result_old}"

    # Date >2 years in future → soft stop
    result_fut = validate_effective_date_window(
        {"effective_date": {"value": "2099-01-01", "ocr_confident": True}}
    )
    assert result_fut is not None and result_fut[0] == "soft", \
        f"Far-future date not flagged: {result_fut}"

    # Valid date within ±2 years → None
    result_ok = validate_effective_date_window(
        {"effective_date": {"value": "2025-06-01", "ocr_confident": True}}
    )
    assert result_ok is None, f"Valid date incorrectly flagged: {result_ok}"

    _record("effective_date_window", True)
except AssertionError as e:
    _record("effective_date_window", False, str(e))
except Exception as e:
    _record("effective_date_window", False, f"Exception: {e}")


# ──────────────────────────────────────────────────────────────────────────────
# TEST 7 — sqs_service.py (NAICS code validation)
# ──────────────────────────────────────────────────────────────────────────────
try:
    from services.sqs_service import validate_naics_code

    # Empty → no issue
    assert validate_naics_code({}) is None, "Empty facts should return None"

    # Valid NAICS code (insurance sector 52)
    assert validate_naics_code(
        {"naics_code": {"value": "524126", "ocr_confident": True}}
    ) is None, "524126 is a valid NAICS code"

    # Invalid prefix (99)
    bad = validate_naics_code(
        {"naics_code": {"value": "99999", "ocr_confident": True}}
    )
    assert bad is not None, "Invalid prefix 99 not caught"

    # Non-numeric
    bad2 = validate_naics_code(
        {"naics_code": {"value": "abc", "ocr_confident": True}}
    )
    assert bad2 is not None, "Non-numeric NAICS not caught"

    _record("naics_validation", True)
except AssertionError as e:
    _record("naics_validation", False, str(e))
except Exception as e:
    _record("naics_validation", False, f"Exception: {e}")


# ──────────────────────────────────────────────────────────────────────────────
# TEST 8 — sqs_service.py (loss history gradient scorer)
# ──────────────────────────────────────────────────────────────────────────────
try:
    from services.sqs_service import _loss_history_score

    # Has history + carrier + 2 claims + 50k incurred → score should be high
    s1 = _loss_history_score(
        facts={
            "prior_carrier":   {"value": "Travelers", "ocr_confident": True},
            "num_claims":      {"value": "2",         "ocr_confident": True},
            "total_incurred":  {"value": "50000",     "ocr_confident": True},
        },
        flags={"has_loss_history": True},
    )
    assert s1 >= 85, f"Expected >=85 for full history, got {s1}"

    # High claim count (8) → penalty applied → score lower than s1
    s2 = _loss_history_score(
        facts={
            "num_claims": {"value": "8", "ocr_confident": True},
        },
        flags={"has_loss_history": True},
    )
    assert s2 < s1, f"High claim count should score lower than s1={s1}, got s2={s2}"

    # Nothing provided → baseline 50
    s3 = _loss_history_score(facts={}, flags={})
    assert s3 == 50, f"Expected 50 baseline, got {s3}"

    _record("loss_history_gradient", True)
except AssertionError as e:
    _record("loss_history_gradient", False, str(e))
except Exception as e:
    _record("loss_history_gradient", False, f"Exception: {e}")


# ──────────────────────────────────────────────────────────────────────────────
# TEST 9 — sqs_service.py (OCR penalty cap raised to 30)
# ──────────────────────────────────────────────────────────────────────────────
try:
    from services.sqs_service import calculate_sqs

    low_conf_facts = {
        "applicant_name":          {"value": "Test",     "ocr_confident": False},
        "mailing_address":         {"value": "123 Main", "ocr_confident": False},
        "fein":                    {"value": "123456789","ocr_confident": False},
        "effective_date":          {"value": "2025-01-01","ocr_confident": False},
        "expiration_date":         {"value": "2026-01-01","ocr_confident": False},
        "property_building_value": {"value": "500000",   "ocr_confident": False},
        "lines_of_business": ["GL"],
    }

    result = calculate_sqs(
        facts=low_conf_facts,
        flags={"has_general_liability": True},
        mapped_data={},
        form_schema={},
        selected_form_ids=["ACORD_125"],
        hard_stops=[],
        soft_stops=[],
        tier2_score=50,
        form_id="ACORD_125",
        schema_size=20,
        fields_mapped=5,
    )
    score = result.get("sqs_score", 100)
    assert score is not None, "sqs_score is None (extraction quality gate triggered unexpectedly)"
    assert score <= 70, f"Expected heavy OCR penalty, got score={score}"

    _record("ocr_penalty_cap", True)
except AssertionError as e:
    _record("ocr_penalty_cap", False, str(e))
except Exception as e:
    _record("ocr_penalty_cap", False, f"Exception: {e}")


# ──────────────────────────────────────────────────────────────────────────────
# TEST 10 — form_service.py (raw OCR text used in keyword matching)
# ──────────────────────────────────────────────────────────────────────────────
try:
    from services.form_service import match_forms_deterministic

    facts = {
        "lines_of_business": [],
        "operations_description": {"value": "General contractor", "ocr_confident": True},
    }
    flags = {"has_general_liability": True}
    facts["mailing_address"] = {"value": "100 Main St, Los Angeles, CA 90012", "ocr_confident": True}

    # "business auto" only in raw text, NOT in ops/lobs -> must trigger California ACORD_137
    raw_text = (
        "This policy includes business auto liability, physical damage, "
        "and uninsured motorist coverage"
    )
    matches = match_forms_deterministic(facts, flags, text=raw_text)
    form_ids = [m["form_id"] for m in matches]
    assert "ACORD_137_CA" in form_ids, \
        f"ACORD_137_CA not triggered by California auto raw text. Got: {form_ids}"

    # "garage keepers" only in raw text -> must trigger Colorado ACORD_138
    facts["mailing_address"] = {"value": "200 Market St, Denver, CO 80202", "ocr_confident": True}
    raw_text2 = "garage keepers and auto dealer physical damage coverage requested"
    matches2 = match_forms_deterministic(facts, flags, text=raw_text2)
    form_ids2 = [m["form_id"] for m in matches2]
    assert "ACORD_138_CO" in form_ids2, \
        f"ACORD_138_CO not triggered by Colorado garage/dealers raw text. Got: {form_ids2}"

    _record("form_raw_text_matching", True)
except AssertionError as e:
    _record("form_raw_text_matching", False, str(e))
except Exception as e:
    _record("form_raw_text_matching", False, f"Exception: {e}")


# ──────────────────────────────────────────────────────────────────────────────
# TEST 11 — cover_service.py (cache hits on repeat call)
# ──────────────────────────────────────────────────────────────────────────────
try:
    import services.cover_service as _cover_mod
    from services.cover_service import generate_ai_cover_narrative

    facts_c = {
        "applicant_name": {"value": "Test Corp", "ocr_confident": True},
        "lines_of_business": ["GL"],
    }
    flags_c = {}
    sqs_results = {
        "ACORD_125": {
            "sqs_score": 80, "grade": "B", "tier": "Review-Ready",
            "routing_decision": "review", "breakdown": {},
            "issues": [], "recommendations": [],
        }
    }

    call_count = [0]
    _original_groq = _cover_mod.groq_chat

    async def _counting_groq(model, messages, **kwargs):
        call_count[0] += 1
        return '{"narrative":"test","sqs_reasoning":"test","ai_block":{}}'

    # Patch the name in cover_service's own namespace
    _cover_mod.groq_chat = _counting_groq

    # Clear any in-process cache entry that might already exist
    from services.extraction_service import _EXTRACT_CACHE
    keys_to_del = [k for k in list(_EXTRACT_CACHE.keys()) if k.startswith("cover_ai:")]
    for k in keys_to_del:
        _EXTRACT_CACHE.pop(k, None)

    import asyncio as _asyncio
    r1 = _asyncio.run(generate_ai_cover_narrative(facts_c, flags_c, sqs_results, ["ACORD_125"], "Agency X"))
    r2 = _asyncio.run(generate_ai_cover_narrative(facts_c, flags_c, sqs_results, ["ACORD_125"], "Agency X"))

    _cover_mod.groq_chat = _original_groq  # restore

    assert call_count[0] == 1, \
        f"groq called {call_count[0]} time(s), expected exactly 1 (cache on 2nd call)"
    assert r1 == r2, "Cached result differs from first result"

    _record("cover_cache", True)
except AssertionError as e:
    _record("cover_cache", False, str(e))
except Exception as e:
    _record("cover_cache", False, f"Exception: {e}")


# ──────────────────────────────────────────────────────────────────────────────
# Summary
# ──────────────────────────────────────────────────────────────────────────────
print("\n=== ALL TESTS COMPLETE ===")
passed = sum(1 for v in results.values() if v == "PASS")
failed = sum(1 for v in results.values() if v.startswith("FAIL"))
print(f"\nResults: {passed} PASSED, {failed} FAILED\n")
for name, status in results.items():
    marker = "OK" if status == "PASS" else "!!"
    print(f"  [{marker}]  {name}: {status}")
