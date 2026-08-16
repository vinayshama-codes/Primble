# Extraction JSON salvage + non-fatal chunk failure (live incident 2026-08-15).
#
# The client's 271-page Orbin upload returned HTTP 500:
#   RuntimeError: _safe_json_parse: could not parse valid JSON after 3 attempts
# ONE chunk's reply was unparseable (truncation at the 16,000-token output cap)
# and `_one`'s `except RuntimeError: raise` blew past every degradation path the
# extractor has - per-chunk retries, the smaller-chunk document retry, the
# PARTIAL-coverage report - and aborted the whole upload.
#
# Three fixes, pinned here:
#   1. deterministic salvage of the completed portion (utils.json_salvage),
#      shared with the gap-fill stage instead of a second copy;
#   2. a JSON/schema failure retries and then degrades to `chunk_failed`;
#   3. the output cap is raised so truncation is rarer in the first place.

import asyncio
import json

import pytest

from utils.json_salvage import salvage_truncated_json
from services import extraction_service as es


class TestSalvageParser:

    def test_recovers_a_reply_cut_mid_object(self):
        truncated = (
            '{"facts": {"applicant_name": "ORBIN CONTRACTING LLC", '
            '"policy_number": "6J7-40-02---26", '
            '"dec_page_entries": [{"label": "Premium", "value": "$3,418"}, '
            '{"label": "Each Occurrence", "val'
        )
        got = salvage_truncated_json(truncated)
        assert got is not None
        assert got["facts"]["applicant_name"] == "ORBIN CONTRACTING LLC"
        assert got["facts"]["policy_number"] == "6J7-40-02---26"
        # The completed entry survives; the half-written one is dropped.
        assert got["facts"]["dec_page_entries"] == [
            {"label": "Premium", "value": "$3,418"}]

    def test_a_brace_or_comma_inside_a_string_is_not_structure(self):
        truncated = (
            '{"facts": {"mailing_address": "123 Main St, Suite {3}, Fargo, ND", '
            '"applicant_name": "ACME'
        )
        got = salvage_truncated_json(truncated)
        assert got is not None
        assert got["facts"]["mailing_address"] == "123 Main St, Suite {3}, Fargo, ND"

    def test_escaped_quotes_survive(self):
        truncated = (
            '{"facts": {"operations_description": "Installs 3\\" pipe, welds", '
            '"fein": "84-221'
        )
        got = salvage_truncated_json(truncated)
        assert got is not None
        assert got["facts"]["operations_description"] == 'Installs 3" pipe, welds'

    def test_a_partial_row_is_dropped_whole_never_half_written(self):
        # A vehicle with a VIN and no make is the broken half-relationship the
        # client reported at the form level - salvage must not manufacture one.
        truncated = (
            '{"facts": {"auto_vin_schedule": ['
            '{"vin": "4S4BRCGC9C3217772", "make": "SUBARU", "model": "OUTBACK"}, '
            '{"vin": "1FTFW1ET5DFA12345", "ma'
        )
        got = salvage_truncated_json(truncated)
        assert got is not None
        rows = got["facts"]["auto_vin_schedule"]
        assert len(rows) == 1 and rows[0]["make"] == "SUBARU"

    def test_gap_fill_shape_keeps_its_finished_pairs(self):
        # The innermost container IS the payload here - every completed
        # key/value pair must survive (the behaviour gap fill has relied on).
        truncated = '{"values": {"Field_A": "X", "Field_B": "Y", "Field_C'
        got = salvage_truncated_json(truncated)
        assert got == {"values": {"Field_A": "X", "Field_B": "Y"}}

    def test_valid_json_is_unaffected_by_the_salvage_path(self):
        # Salvage is only consulted when json.loads already failed, but it must
        # never corrupt a complete object if it ever is.
        whole = '{"facts": {"a": "1", "b": "2"}, "flags": {}}'
        got = salvage_truncated_json(whole)
        assert got is None or got["facts"]["a"] == "1"

    def test_unsalvageable_input_returns_none_and_never_raises(self):
        for junk in ("", "not json at all", "```", "{", '{"a"', None):
            assert salvage_truncated_json(junk) is None

    def test_gap_fill_entry_point_delegates_to_the_same_parser(self):
        # One implementation, two callers - a second copy is how they drift.
        from services.pdf_service import _salvage_truncated_json
        truncated = '{"values": {"Field_A": "X", "Field_B": "Y"}, "quotes": {"Fi'
        assert _salvage_truncated_json(truncated) == salvage_truncated_json(truncated)


class TestSafeJsonParseUsesSalvage:

    def test_truncated_extraction_reply_parses_without_an_llm_repair_call(self, monkeypatch):
        # If salvage works, no repair call may be made: re-billing a whole
        # prompt to get the same truncation back is the behaviour this replaces.
        calls = []

        async def _no_repair(*a, **k):
            calls.append(a)
            return "{}"

        monkeypatch.setattr(es, "groq_chat", _no_repair)
        truncated = (
            '{"facts": {"applicant_name": "ORBIN CONTRACTING LLC", '
            '"total_payroll": "$39,300", "locations": ["Fargo, ND"], '
            '"policy_number": "6J7-40'
        )
        result = asyncio.run(es._safe_json_parse(truncated, context="key=test"))
        assert result["facts"]["applicant_name"] == "ORBIN CONTRACTING LLC"
        assert result["facts"]["total_payroll"] == "$39,300"
        assert calls == [], "salvage succeeded but an LLM repair was still called"

    def test_a_complete_reply_still_parses_normally(self):
        whole = json.dumps({
            "facts": {"applicant_name": "ORBIN CONTRACTING LLC"},
            "flags": {"has_umbrella": True},
        })
        result = asyncio.run(es._safe_json_parse(whole, context="key=test"))
        assert result["facts"]["applicant_name"] == "ORBIN CONTRACTING LLC"
        assert result["flags"]["has_umbrella"] is True

    def test_genuinely_unparseable_output_still_raises(self, monkeypatch):
        # The contract is unchanged for real garbage - it must not return empty
        # silently. The CALLER decides how to degrade.
        async def _bad_repair(*a, **k):
            return "I am afraid I cannot help with that."

        monkeypatch.setattr(es, "groq_chat", _bad_repair)
        with pytest.raises(RuntimeError):
            asyncio.run(es._safe_json_parse("total garbage", context="key=test"))


class TestChunkFailureIsNotFatal:

    def test_a_json_failure_degrades_to_a_failed_chunk(self, monkeypatch):
        # The literal incident: one chunk unparseable. The upload must survive
        # with a reported partial, not 500.
        async def _always_bad(*a, **k):
            raise RuntimeError("_safe_json_parse: could not parse valid JSON after 3 attempts")

        monkeypatch.setattr(es, "extract_facts_async", _always_bad)
        monkeypatch.setenv("CHUNK_MAX_RETRIES", "1")
        chunks = [("chunk one text", 0, 14, ""), ("chunk two text", 14, 28, "")]
        results = asyncio.run(es._gather_chunks_async(chunks, [], "dec_page"))
        assert len(results) == 2
        assert all(r.get("chunk_failed") for r in results)
        assert all("could not parse" in r.get("chunk_error", "") for r in results)

    def test_a_healthy_chunk_still_succeeds_alongside_a_failed_one(self, monkeypatch):
        async def _one_bad(text, *a, **k):
            if "bad" in text:
                raise RuntimeError("_safe_json_parse: could not parse valid JSON")
            return {"facts": {"applicant_name": "ORBIN CONTRACTING LLC"}, "flags": {}}

        monkeypatch.setattr(es, "extract_facts_async", _one_bad)
        monkeypatch.setenv("CHUNK_MAX_RETRIES", "1")
        chunks = [("good text", 0, 9, ""), ("bad text", 9, 17, "")]
        results = asyncio.run(es._gather_chunks_async(chunks, [], "dec_page"))
        ok = [r for r in results if not r.get("chunk_failed")]
        bad = [r for r in results if r.get("chunk_failed")]
        assert len(ok) == 1 and len(bad) == 1
        assert ok[0]["facts"]["applicant_name"] == "ORBIN CONTRACTING LLC"

    def test_a_permanent_sdk_error_still_fails_fast(self, monkeypatch):
        # Unchanged: retrying a TypeError/400 can never succeed.
        async def _sdk_break(*a, **k):
            raise TypeError("unexpected keyword argument")

        monkeypatch.setattr(es, "extract_facts_async", _sdk_break)
        with pytest.raises(TypeError):
            asyncio.run(es._gather_chunks_async([("t", 0, 1, "")], [], "dec_page"))


def test_extraction_output_cap_has_headroom_over_the_old_16k():
    # C51: 16,000 was being hit on dense declarations chunks, which is what
    # produced the unparseable reply.
    assert es._EXTRACT_MAX_OUTPUT_TOKENS >= 32000
