"""
test_q2.py — Q2 field extraction completeness regression tests.

Run from the backend/ directory:
    pytest test_q2.py -v
"""

import sys
import types
from unittest.mock import MagicMock

# ---------------------------------------------------------------------------
# Stub heavy external dependencies BEFORE any service module is imported.
# This prevents real Groq / DB / Stripe initialisation during tests.
# ---------------------------------------------------------------------------
_settings = types.ModuleType("config.settings")
_settings.groq_client   = MagicMock()
_settings.FRONTEND_URL  = "http://localhost:5173"
_settings.FORMS_DB_DIR  = "/tmp"
_settings.TEMPLATE_DIR  = "/tmp"
_settings.FORMS_INDEX   = "/tmp/forms_index.json"
_settings.SOFT_BUFFER_PCT = 0.05
sys.modules.setdefault("config.settings", _settings)

_db = types.ModuleType("config.database")
_db.get_db = MagicMock()
sys.modules.setdefault("config.database", _db)

# stripe is imported at settings.py level via side-effect; stub it too
sys.modules.setdefault("stripe", MagicMock())
sys.modules.setdefault("groq",   MagicMock())

# ---------------------------------------------------------------------------
# Now safe to import service modules
# ---------------------------------------------------------------------------
import pytest

from services.extraction_service import _EXTRACT_SCHEMA, _EXTRACT_PROMPT_PREFIX
from services.arq_service import (
    generate_arq_questions,
    _FIELD_QUESTION_MAP,
    _FIELD_TO_FORMS,
)
from services.sqs_service import evaluate_stops


# ===========================================================================
# 1. Prompt schema field name checks
# ===========================================================================

class TestExtractSchema:
    """_EXTRACT_SCHEMA must contain the new field names and NOT the old ones."""

    NEW_NAMES = [
        "gl_class_codes_by_location",
        "additional_named_insureds",
        "wc_monopolistic_payroll",
        "building_ITV_percentage",
        "total_incurred",
        "wc_xmod_effective_date",
        "auto_covered_symbols",
    ]

    OLD_NAMES = [
        "gl_class_codes",        # replaced by gl_class_codes_by_location
        "additional_insured",    # replaced by additional_named_insureds
        "auto_coverage_symbols", # replaced by auto_covered_symbols
    ]

    @pytest.mark.parametrize("field", NEW_NAMES)
    def test_new_field_present(self, field):
        assert field in _EXTRACT_SCHEMA, (
            f"Expected new field '{field}' in _EXTRACT_SCHEMA but it was not found.\n"
            f"Schema excerpt: {_EXTRACT_SCHEMA[:500]}"
        )

    @pytest.mark.parametrize("field", OLD_NAMES)
    def test_old_field_absent(self, field):
        # The old bare name must not appear — check the full prompt prefix as well
        # to catch any leftover in the system message wrapper.
        combined = _EXTRACT_SCHEMA + _EXTRACT_PROMPT_PREFIX
        # Allow the old token only as a strict substring that is NOT part of the
        # new replacement name (e.g. "gl_class_codes" must not appear except
        # as the prefix of "gl_class_codes_by_location").
        import re
        # Build a negative-lookbehind pattern that rejects the name followed by
        # "_by_location", "d" (additional_named_insureds), or "s" alone.
        hits = [m.start() for m in re.finditer(re.escape(field), combined)]
        false_positives = {
            "gl_class_codes":     "gl_class_codes_by_location",
            "additional_insured": "additional_named_insureds",
        }
        bad_hits = []
        for pos in hits:
            snippet = combined[pos : pos + len(field) + 20]
            # If the hit is a prefix of the new name, it's acceptable
            replacement = false_positives.get(field)
            if replacement and combined[pos:].startswith(replacement):
                continue  # prefix of the new name — not a stale reference
            bad_hits.append(snippet)

        assert not bad_hits, (
            f"Old field name '{field}' found as a standalone reference in the schema/prompt.\n"
            f"Offending snippets: {bad_hits}"
        )

    def test_underlying_policies_has_schema(self):
        """underlying_policies must carry the structured object schema."""
        assert '"line"' in _EXTRACT_SCHEMA
        assert '"carrier"' in _EXTRACT_SCHEMA
        assert '"policy_no"' in _EXTRACT_SCHEMA

    def test_auto_covered_symbols_is_array(self):
        """auto_covered_symbols must be declared as an array of ints."""
        assert "auto_covered_symbols" in _EXTRACT_SCHEMA
        # The schema string must indicate an array (square bracket follows)
        idx = _EXTRACT_SCHEMA.index("auto_covered_symbols")
        snippet = _EXTRACT_SCHEMA[idx : idx + 30]
        assert "[" in snippet, f"Expected array notation near 'auto_covered_symbols', got: {snippet!r}"


# ===========================================================================
# 2. generate_arq_questions() surfaces null wc_xmod even with no PDF mapping
# ===========================================================================

def _make_generated_forms(*form_ids):
    """
    Return a minimal generated_forms dict.
    The confidence + mapped dicts are intentionally empty — simulating a form
    whose PDF fields do not include a field literally named 'wc_xmod'.
    The _FIELD_QUESTION_MAP sweep must still surface it.
    """
    return {
        fid: {
            "form_name":           f"ACORD {fid.replace('ACORD_', '')}",
            "confidence":          {},   # no PDF field named wc_xmod
            "mapped":              {},
            "field_state":         {},
            "schema":              {},
            "client_filled_fields": [],
        }
        for fid in form_ids
    }


class TestGenerateArqQuestions:

    def test_wc_xmod_surfaced_without_pdf_field(self):
        """
        wc_xmod is null in facts and ACORD_130 is generated, but the confidence
        dict has no 'wc_xmod' entry (no literal PDF field by that name).
        The _FIELD_QUESTION_MAP sweep must still produce a question for it.
        """
        facts  = {"wc_xmod": None}
        flags  = {"has_workers_comp": True}
        gen    = _make_generated_forms("ACORD_130")

        questions = generate_arq_questions(
            facts=facts,
            flags=flags,
            generated_forms=gen,
            hard_stops=[],
            soft_stops=[],
        )

        field_names = [q["field_name"] for q in questions]
        assert "wc_xmod" in field_names, (
            f"Expected 'wc_xmod' question but got: {field_names}"
        )

    def test_wc_xmod_absent_when_filled(self):
        """If wc_xmod is already populated, no question should be raised."""
        facts  = {"wc_xmod": "0.92"}
        flags  = {"has_workers_comp": True}
        gen    = _make_generated_forms("ACORD_130")

        questions = generate_arq_questions(
            facts=facts,
            flags=flags,
            generated_forms=gen,
            hard_stops=[],
            soft_stops=[],
        )

        field_names = [q["field_name"] for q in questions]
        assert "wc_xmod" not in field_names, (
            f"wc_xmod should be absent when it has a value, but found it in: {field_names}"
        )

    def test_wc_xmod_absent_when_form_not_selected(self):
        """
        wc_xmod is null but ACORD_130 is not in generated_forms.
        Since _FIELD_TO_FORMS['wc_xmod'] == {'ACORD_130'}, it must be gated out.
        """
        facts  = {"wc_xmod": None}
        flags  = {}
        gen    = _make_generated_forms("ACORD_125")  # GL only, no WC form

        questions = generate_arq_questions(
            facts=facts,
            flags=flags,
            generated_forms=gen,
            hard_stops=[],
            soft_stops=[],
        )

        field_names = [q["field_name"] for q in questions]
        assert "wc_xmod" not in field_names, (
            f"wc_xmod should be gated out when ACORD_130 is not generated, "
            f"but found it in: {field_names}"
        )

    def test_new_field_wc_monopolistic_payroll_surfaced(self):
        """wc_monopolistic_payroll (new Q2 field) surfaces when WC form is active."""
        facts  = {}  # entirely empty facts
        flags  = {"has_workers_comp": True}
        gen    = _make_generated_forms("ACORD_130")

        questions = generate_arq_questions(
            facts=facts,
            flags=flags,
            generated_forms=gen,
            hard_stops=[],
            soft_stops=[],
        )

        field_names = [q["field_name"] for q in questions]
        assert "wc_monopolistic_payroll" in field_names, (
            f"Expected 'wc_monopolistic_payroll' question; got: {field_names}"
        )

    def test_building_itv_surfaced_when_property_form_active(self):
        """building_ITV_percentage surfaces when ACORD_140 is generated."""
        facts  = {}
        flags  = {"has_property_coverage": True}
        gen    = _make_generated_forms("ACORD_140")

        questions = generate_arq_questions(
            facts=facts,
            flags=flags,
            generated_forms=gen,
            hard_stops=[],
            soft_stops=[],
        )

        field_names = [q["field_name"] for q in questions]
        assert "building_ITV_percentage" in field_names, (
            f"Expected 'building_ITV_percentage' question; got: {field_names}"
        )

    def test_no_duplicate_questions(self):
        """Each field_name appears at most once in the output."""
        facts  = {}
        flags  = {"has_workers_comp": True, "has_general_liability": True}
        gen    = _make_generated_forms("ACORD_125", "ACORD_126", "ACORD_130")

        questions = generate_arq_questions(
            facts=facts,
            flags=flags,
            generated_forms=gen,
            hard_stops=[],
            soft_stops=[],
        )

        field_names = [q["field_name"] for q in questions]
        assert len(field_names) == len(set(field_names)), (
            f"Duplicate questions found: "
            f"{[f for f in field_names if field_names.count(f) > 1]}"
        )


# ===========================================================================
# 3. Monopolistic WC validator fires a hard stop
# ===========================================================================

class TestMonopolisticWCValidator:

    def test_hard_stop_when_monopolistic_payroll_missing(self):
        """
        wc_has_monopolistic_state=True + empty wc_monopolistic_payroll
        must produce a hard stop.
        """
        facts = {
            "wc_payroll": "500000",
            # wc_monopolistic_payroll intentionally absent
        }
        flags = {
            "has_workers_comp":        True,
            "wc_has_monopolistic_state": True,
        }
        hard, soft = evaluate_stops(facts, flags)

        hard_lower = [s.lower() for s in hard]
        assert any("monopolistic" in s for s in hard_lower), (
            f"Expected a hard stop mentioning 'monopolistic' but got hard={hard}"
        )

    def test_hard_stop_when_monopolistic_payroll_empty_dict(self):
        """Empty dict is also treated as missing."""
        facts = {"wc_monopolistic_payroll": {}}
        flags = {
            "has_workers_comp":          True,
            "wc_has_monopolistic_state": True,
        }
        hard, soft = evaluate_stops(facts, flags)

        hard_lower = [s.lower() for s in hard]
        assert any("monopolistic" in s for s in hard_lower), (
            f"Expected hard stop for empty wc_monopolistic_payroll dict, got hard={hard}"
        )

    def test_no_hard_stop_when_monopolistic_payroll_present(self):
        """When wc_monopolistic_payroll is populated the hard stop must NOT fire."""
        facts = {
            "wc_payroll": "500000",
            "wc_monopolistic_payroll": {"OH": "120000", "WA": "80000"},
        }
        flags = {
            "has_workers_comp":          True,
            "wc_has_monopolistic_state": True,
        }
        hard, soft = evaluate_stops(facts, flags)

        hard_lower = [s.lower() for s in hard]
        assert not any(
            "monopolistic" in s and "missing" in s for s in hard_lower
        ), (
            f"Hard stop should NOT fire when payroll is present, but got hard={hard}"
        )

    def test_soft_stop_always_fires_for_monopolistic_state(self):
        """
        The soft advisory ('must use state fund') must always fire when
        wc_has_monopolistic_state is True, regardless of payroll presence.
        """
        for payroll in [None, {}, {"OH": "100000"}]:
            facts = {"wc_monopolistic_payroll": payroll} if payroll is not None else {}
            flags = {
                "has_workers_comp":          True,
                "wc_has_monopolistic_state": True,
            }
            _, soft = evaluate_stops(facts, flags)
            soft_lower = [s.lower() for s in soft]
            assert any("state fund" in s for s in soft_lower), (
                f"Soft advisory 'state fund' must always fire; payroll={payroll!r}, soft={soft}"
            )

    def test_no_monopolistic_stop_when_flag_false(self):
        """Neither hard nor soft monopolistic stop fires when the flag is off."""
        facts = {}
        flags = {"has_workers_comp": True, "wc_has_monopolistic_state": False}
        hard, soft = evaluate_stops(facts, flags)

        combined = [s.lower() for s in hard + soft]
        assert not any("monopolistic" in s for s in combined), (
            f"No monopolistic messages expected when flag=False; got hard={hard}, soft={soft}"
        )


# ===========================================================================
# 4. _FIELD_TO_FORMS integrity
# ===========================================================================

class TestFieldToForms:
    """Sanity-check that _FIELD_TO_FORMS covers all keys in _FIELD_QUESTION_MAP."""

    def test_field_to_forms_has_no_stale_old_names(self):
        old_names = {"gl_class_codes", "additional_insured", "auto_coverage_symbols"}
        stale = old_names & set(_FIELD_TO_FORMS.keys())
        assert not stale, f"Stale old field names found in _FIELD_TO_FORMS: {stale}"

    def test_new_q2_fields_in_field_to_forms(self):
        required = {
            "wc_monopolistic_payroll",
            "wc_xmod_effective_date",
            "building_ITV_percentage",
            "gl_class_codes_by_location",
            "additional_named_insureds",
        }
        missing = required - set(_FIELD_TO_FORMS.keys())
        assert not missing, f"New Q2 fields missing from _FIELD_TO_FORMS: {missing}"

    def test_all_field_to_forms_values_are_sets(self):
        for key, val in _FIELD_TO_FORMS.items():
            assert isinstance(val, set), (
                f"_FIELD_TO_FORMS['{key}'] should be a set, got {type(val)}"
            )
