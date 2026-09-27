"""Owner's rules, 27 Sep 2026.

1. A policy is removed from a package only when it CONFLICTS or has EXPIRED,
   and a genuine conflict belongs in Data Consistency. Measured on six package
   shapes through the real merge and stamper: five were right; a renewal
   package (last year's GL declarations beside this year's) turned the expired
   policy into a "two policies on the same line" conflict, blanked the 126
   header and the 131 underlying GL row, and listed the expired policy as
   current "other insurance" on the 125. The client's own item 10: compare only
   within the same line AND the applicable time period.
2. The post-generation re-fill wrote nothing but an empty result off - the fill
   engine's "UNMATCHED" marker would have been printed in the box.
3. render.yaml must say what production runs. It said async and easyocr while
   the dashboard ran synchronously on Google Vision.

Offline: no database, no LLM.
"""
import copy
import io
import contextlib
import os
import pathlib
import sys

import pytest
import yaml

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
os.environ.setdefault("OPENAI_API_KEY", "sk-offline-test")

import services.extraction_service as es                      # noqa: E402
import services.pdf_service as ps                             # noqa: E402
from services import arq_service as arq                       # noqa: E402
from services.underwriting_consistency import assess_underwriting_consistency  # noqa: E402

ROOT = pathlib.Path(__file__).resolve().parents[2]

CUR = {"effective_date": "01/01/2026", "expiration_date": "01/01/2027"}
OLD = {"effective_date": "01/01/2025", "expiration_date": "01/01/2026"}
TODAY = "2026-09-27"
TRAV = ("Travelers Property Casualty Company of America", "25674")
PROG = ("Progressive Casualty Insurance Company", "24260")


def _pol(line, who, number, term=CUR, premium="$1,000", **kw):
    row = {"line": line, "carrier": who[0], "naic": who[1], "policy_number": number, **term}
    if premium:
        row["premium"] = premium
    row.update(kw)
    return row


def _doc(name, dt, rows):
    return {"doc_id": name, "filename": name, "doc_type": dt, "text": "",
            "facts": {"coverage_lines": rows, "applicant_name": "ACME BUILDERS LLC"}}


def _merge(docs):
    with contextlib.redirect_stdout(io.StringIO()):
        mf, flags = es.merge_facts(copy.deepcopy(docs), es.select_primary_truth(docs))
        uw = assess_underwriting_consistency(docs, mf, {}, flags=flags)
    return mf, flags, uw


def _status(uw, key):
    return next((f["status"] for f in uw.get("fields") or [] if f["fact_key"] == key), None)


def _header(mf, flags, form_id):
    return ps._deterministic_map("Policy_PolicyNumberIdentifier_A", {**mf, **flags, "_form_id": form_id})


# =============================================================================
# 1a. The rule, called DIRECTLY - the merge's safety net must not hide it
# =============================================================================
class TestRetirePredecessor:

    def _mf(self, *rows):
        return {"coverage_lines": [dict(r) for r in rows]}

    def test_an_expired_policy_beside_its_renewal_becomes_history(self):
        mf = self._mf(_pol("Commercial General Liability", TRAV, "GL-100-25", OLD),
                      _pol("Commercial General Liability", TRAV, "GL-100-26"))
        notes = es._retire_predecessor_policies(mf, today=TODAY)
        assert len(notes) == 1 and "GL-100-25" in notes[0]
        assert [r["policy_number"] for r in mf["coverage_lines"]] == ["GL-100-26"]
        assert [r["policy_number"] for r in mf[es.RETIRED_COVERAGE_LINES_KEY]] == ["GL-100-25"]

    def test_three_terms_leave_only_the_newest(self):
        y24 = {"effective_date": "01/01/2024", "expiration_date": "01/01/2025"}
        mf = self._mf(_pol("GL", TRAV, "GL-24", y24), _pol("GL", TRAV, "GL-25", OLD), _pol("GL", TRAV, "GL-26"))
        es._retire_predecessor_policies(mf, today=TODAY)
        assert [r["policy_number"] for r in mf["coverage_lines"]] == ["GL-26"]
        assert len(mf[es.RETIRED_COVERAGE_LINES_KEY]) == 2

    def test_a_policy_that_has_not_expired_yet_stays(self):
        """Current policy + next year's policy: nothing has expired, so nothing
        is removed - that stays the question it always was."""
        nxt = {"effective_date": "01/01/2027", "expiration_date": "01/01/2028"}
        mf = self._mf(_pol("GL", TRAV, "GL-26"), _pol("GL", TRAV, "GL-27", nxt))
        assert es._retire_predecessor_policies(mf, today=TODAY) == []
        assert len(mf["coverage_lines"]) == 2

    def test_overlapping_terms_are_two_live_policies(self):
        mid = {"effective_date": "06/01/2026", "expiration_date": "06/01/2027"}
        mf = self._mf(_pol("GL", TRAV, "GL-A"), _pol("GL", PROG, "GL-B", mid))
        assert es._retire_predecessor_policies(mf, today="2027-09-01") == []

    @pytest.mark.parametrize("missing", ["effective_date", "expiration_date"])
    def test_a_missing_date_decides_nothing(self, missing):
        old = _pol("GL", TRAV, "GL-100-25", OLD)
        old.pop(missing)
        mf = self._mf(old, _pol("GL", TRAV, "GL-100-26"))
        assert es._retire_predecessor_policies(mf, today=TODAY) == []

    def test_a_successor_without_a_policy_number_is_not_a_policy_yet(self):
        mf = self._mf(_pol("GL", TRAV, "GL-100-25", OLD), _pol("GL", TRAV, None))
        assert es._retire_predecessor_policies(mf, today=TODAY) == []

    def test_different_lines_never_retire_each_other(self):
        mf = self._mf(_pol("Commercial General Liability", TRAV, "GL-100-25", OLD),
                      _pol("Commercial Auto", PROG, "CA-200-26"))
        assert es._retire_predecessor_policies(mf, today=TODAY) == []

    def test_a_denied_line_is_not_a_policy_either_way(self):
        mf = self._mf({"line": "Commercial Property", "premium": "No Coverage", **OLD},
                      _pol("Commercial Property", TRAV, "CP-600-26"))
        assert es._retire_predecessor_policies(mf, today=TODAY) == []

    def test_a_renewal_that_kept_its_number_is_never_treated_as_history(self):
        """The retired row and the current row share the number - the
        prior-term filter must not condemn the CURRENT policy with it."""
        mf = self._mf(_pol("GL", TRAV, "BBC7263", OLD), _pol("GL", TRAV, "BBC7263"))
        es._retire_predecessor_policies(mf, today=TODAY)
        assert len(mf["coverage_lines"]) == 1
        assert "BBC7263" not in {n.upper() for n in es.prior_term_policy_numbers(mf)}

    def test_a_retired_number_is_prior_term_for_every_reader(self):
        mf = self._mf(_pol("GL", TRAV, "GL-100-25", OLD), _pol("GL", TRAV, "GL-100-26"))
        es._retire_predecessor_policies(mf, today=TODAY)
        prior = es.prior_term_policy_numbers(mf)
        assert es._norm_policy_number("GL-100-25") in prior
        assert es._norm_policy_number("GL-100-26") not in prior

    def test_the_ai_never_reads_an_expired_policy_as_a_hint(self):
        assert es.RETIRED_COVERAGE_LINES_KEY in ps._GAP_FILL_FACTS_EXCLUDE


# =============================================================================
# 1b. The six shapes, through the real merge, Data Consistency and stamper
# =============================================================================
SIX = [_pol("Commercial General Liability", TRAV, "GL-100-26"),
       _pol("Commercial Auto", PROG, "CA-200-26"),
       _pol("Commercial Umbrella", TRAV, "UMB-300-26"),
       _pol("Commercial Inland Marine", ("Hartford Fire Insurance Company", "19682"), "IM-400-26"),
       _pol("Workers Compensation", ("Pinnacol Assurance", "41190"), "WC-500-26"),
       _pol("Commercial Property", TRAV, "CP-600-26")]


class TestNoPolicyIsDroppedWithoutCause:

    def test_six_current_policies_all_reach_every_form(self):
        mf, flags, uw = _merge([_doc("dec.pdf", "dec_page", SIX)])
        assert not mf.get(es.RETIRED_COVERAGE_LINES_KEY)
        assert _status(uw, "policy_number") == "scoped"
        rows = ps._other_policy_rows({**mf, **flags, "_form_id": "ACORD_125"})
        assert [r["policy_number"] for r in rows] == [r["policy_number"] for r in SIX]
        for form_id, number in (("ACORD_126", "GL-100-26"), ("ACORD_127", "CA-200-26"),
                                ("ACORD_131", "UMB-300-26"), ("ACORD_130", "WC-500-26"),
                                ("ACORD_140", "CP-600-26")):
            assert _header(mf, flags, form_id) == number, form_id

    def test_a_policy_only_the_certificate_lists_is_kept(self):
        dec = _doc("dec.pdf", "dec_page", SIX[:2])
        coi = _doc("coi.pdf", "certificate",
                   [_pol("Workers Compensation and Employers Liability", ("Pinnacol Assurance", "41190"),
                         "WC-500-26", premium=None)])
        mf, flags, _ = _merge([dec, coi])
        assert _header(mf, flags, "ACORD_130") == "WC-500-26"

    def test_two_live_policies_on_one_line_are_still_a_conflict(self):
        mf, flags, uw = _merge([_doc("dec.pdf", "dec_page", [
            SIX[0], _pol("Commercial General Liability", ("Hartford Fire Insurance Company", "19682"), "GL-999-26"),
            SIX[1]])])
        assert not mf.get(es.RETIRED_COVERAGE_LINES_KEY)
        assert _status(uw, "policy_number") == "conflict"
        assert _header(mf, flags, "ACORD_126") is None       # waits for the producer

    def test_the_renewal_package_keeps_the_current_policy_everywhere(self):
        mf, flags, uw = _merge([
            _doc("dec_2025.pdf", "dec_page", [_pol("Commercial General Liability", TRAV, "GL-100-25", OLD)]),
            _doc("dec_2026.pdf", "dec_page", SIX[:2])])
        assert [r["policy_number"] for r in mf[es.RETIRED_COVERAGE_LINES_KEY]] == ["GL-100-25"]
        for key in ("policy_number", "effective_date", "expiration_date"):
            assert _status(uw, key) != "conflict", key
        assert _header(mf, flags, "ACORD_126") == "GL-100-26"
        assert ps._deterministic_map("UnderlyingPolicy_GeneralLiability_PolicyNumberIdentifier_A",
                                     {**mf, **flags, "_form_id": "ACORD_131"}) == "GL-100-26"
        rows = ps._other_policy_rows({**mf, **flags, "_form_id": "ACORD_125"})
        assert [r["policy_number"] for r in rows] == ["GL-100-26", "CA-200-26"]


# =============================================================================
# 2. A re-fill after generation never writes the fill engine's marker
# =============================================================================
class TestRefillNeverWritesTheMarker:

    @pytest.mark.parametrize("value,writes", [("UNMATCHED", False), (" UNMATCHED ", False), (None, False),
                                              ("", False), ("   ", False), ("GL-100-26", True), ("0", True)])
    def test_what_counts_as_something_to_write(self, value, writes):
        assert arq._refill_value(value) is writes

    def _forms(self):
        schema = {"NamedInsured_FullName_A": {"ft": "/Tx", "tu": "Enter text: The named insured."}}
        return {"ACORD_125": {"schema": schema, "mapped": {"NamedInsured_FullName_A": ""},
                              "field_state": {"NamedInsured_FullName_A": ""}, "confidence": {}}}

    @pytest.mark.parametrize("fn", ["present", "restamp"])
    def test_both_refill_paths_skip_the_marker(self, monkeypatch, fn):
        monkeypatch.setattr(ps, "_deterministic_map", lambda field, facts: "UNMATCHED")
        forms = self._forms()
        if fn == "present":
            arq._backfill_and_resolve_present(forms, {"applicant_name": "ACME BUILDERS LLC"})
        else:
            arq._restamp_canonical_into_forms(forms, "applicant_name", {"applicant_name": "ACME BUILDERS LLC"})
        state = forms["ACORD_125"].get("field_state") or forms["ACORD_125"]["mapped"]
        assert state["NamedInsured_FullName_A"] != "UNMATCHED"

    def test_a_real_value_is_still_written(self, monkeypatch):
        monkeypatch.setattr(ps, "_deterministic_map", lambda field, facts: "ACME BUILDERS LLC")
        forms = self._forms()
        arq._restamp_canonical_into_forms(forms, "applicant_name", {"applicant_name": "ACME BUILDERS LLC"})
        assert forms["ACORD_125"]["field_state"]["NamedInsured_FullName_A"] == "ACME BUILDERS LLC"


# =============================================================================
# 3. render.yaml says what production runs
# =============================================================================
def _render_env():
    doc = yaml.safe_load((ROOT / "render.yaml").read_text())
    return {svc["name"]: {e["key"]: e.get("value") for e in svc.get("envVars", [])}
            for svc in doc["services"]}


class TestRenderMatchesProduction:

    def test_generation_runs_in_the_web_service_as_on_localhost(self):
        assert _render_env()["acordly-api"]["ENABLE_ASYNC_PROCESSING"] == "false"

    def test_the_settings_that_change_results_are_pinned(self):
        web = _render_env()["acordly-api"]
        assert web["GPT_MODEL"] == web["LLM_MODEL"] == "gpt-5.4-mini"
        assert web["OCR_PROVIDER"] == "google" and "GOOGLE_VISION_API_KEY" in web
        # Owner, 27 Sep 2026: the code default (120 s) on Render - so NOT set.
        assert "LLM_REQUEST_TIMEOUT" not in web
        assert web["PURGE_DEC_INDEX_AFTER_GENERATION"] == "0"
        assert web["PYTHON_VERSION"] == "3.11.9"

    def test_the_worker_would_run_with_the_same_settings(self):
        env = _render_env()
        for key in ("GPT_MODEL", "LLM_MODEL", "OCR_PROVIDER", "LLM_REQUEST_TIMEOUT",
                    "PURGE_DEC_INDEX_AFTER_GENERATION"):
            assert env["acordly-worker"].get(key) == env["acordly-api"].get(key), key
