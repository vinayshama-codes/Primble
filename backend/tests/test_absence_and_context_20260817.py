"""The residue from the 2026-08-17 probe re-run: absence, endorsement dates,
page furniture, and a warning that fired on every submission.

Four defects, all visible on the owner's four probe uploads AFTER the
false-conflict work landed:

  F9  "Dec Page: No" on Additional Insured / Waiver of Subrogation / Primary
      Noncontributory, where the dec page says nothing at all. The client's
      item 3: "Absence of information should not become No."
  F11 `umbrella_effective_date` = 07/25/2025, lifted out of "...reduced from
      $3,000,000 to $1,000,000 effective 07/25/2025". That is the ENDORSEMENT
      date; the policy still incepted 07/15/2025.
  F10 `additional_remarks_text` = the PDF's own title block.
  F15 "The business description indicates potential employee dishonesty or
      cash-handling exposure" on a ROOFING CONTRACTOR - the rule fired on
      `num_employees > 10`, which is nearly every commercial account, and then
      asserted something the description never said.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("OPENAI_API_KEY", "sk-offline")

import pytest                                                     # noqa: E402

from services.cross_form_validator import (                       # noqa: E402
    _check_crime_silent_exposure,
)
from services.extraction_service import (                         # noqa: E402
    _drop_endorsement_dates_from_policy_facts, _drop_page_furniture_remarks,
    _drop_unstated_risk_transfer, detect_source_conflicts,
)

RT_KEYS = ("additional_insured_required", "waiver_of_subrogation_required",
           "primary_noncontributory_required")

DEC_TEXT = ("COMMERCIAL PACKAGE DECLARATIONS. Named Insured ORBIN CONTRACTING "
            "LLC. General Aggregate $2,000,000. Total Policy Premium $10,663.")

UMBRELLA_REMARK = ("The Commercial Umbrella limit under policy 6J7-40-02---26 "
                   "was reduced from $3,000,000 to $1,000,000 effective "
                   "07/25/2025.")


# ── F9: absence is not "No" ──────────────────────────────────────────────────

class TestAbsenceIsNotNo:

    def test_a_silent_dec_page_asserts_nothing(self):
        facts = {"risk_transfer": {k: False for k in RT_KEYS}}
        _drop_unstated_risk_transfer(facts, DEC_TEXT)
        assert facts["risk_transfer"] == {}

    @pytest.mark.parametrize("key,wording", [
        ("additional_insured_required",
         "The certificate holder is NOT required to be an additional insured."),
        ("waiver_of_subrogation_required",
         "No waiver of subrogation is required under this contract."),
        ("primary_noncontributory_required",
         "Coverage is not required to be primary and non-contributory."),
    ])
    def test_an_affirmative_no_is_kept(self, key, wording):
        """A "No" the document actually states is an ANSWER and must survive."""
        facts = {"risk_transfer": {key: False}}
        _drop_unstated_risk_transfer(facts, wording)
        assert facts["risk_transfer"] == {key: False}

    def test_a_yes_is_never_touched(self):
        facts = {"risk_transfer": {k: True for k in RT_KEYS}}
        _drop_unstated_risk_transfer(facts, "nothing relevant here")
        assert facts["risk_transfer"] == {k: True for k in RT_KEYS}

    def test_the_probe_run_conflict_disappears(self):
        """THE REPORTED SHAPE: a silent dec page against a certificate that
        genuinely requires all three."""
        dec = {"risk_transfer": {k: False for k in RT_KEYS}}
        _drop_unstated_risk_transfer(dec, DEC_TEXT)
        docs = [
            {"doc_type": "dec_page", "facts": dec},
            {"doc_type": "certificate",
             "facts": {"risk_transfer": {k: True for k in RT_KEYS}}},
        ]
        assert detect_source_conflicts(docs) == []

    def test_a_real_disagreement_still_conflicts(self):
        """Both documents address it and say opposite things - that IS a
        conflict and must survive."""
        dec = {"risk_transfer": {"additional_insured_required": False}}
        _drop_unstated_risk_transfer(
            dec, "Additional insured status is not required by this contract.")
        docs = [
            {"doc_type": "dec_page", "facts": dec},
            {"doc_type": "certificate",
             "facts": {"risk_transfer": {"additional_insured_required": True}}},
        ]
        assert len(detect_source_conflicts(docs)) == 1

    def test_the_schema_now_offers_a_third_state(self):
        """ANTI-ROT: the three assertion booleans must stay nullable. A bare
        `boolean` gives the model no way to say "not stated" and it answers
        false - which is the defect."""
        import services.extraction_service as es
        schema = "".join(
            v for v in vars(es).values() if isinstance(v, str) and "risk_transfer" in v
        ) or ""
        for key in RT_KEYS:
            assert f'"{key}": boolean or null' in schema, key

    def test_the_coverage_detection_flags_are_deliberately_unchanged(self):
        """`has_*` flags mean "not detected in this document", which is a
        finding, not a claim. Making them nullable would be a different and
        much larger change."""
        facts = {"risk_transfer": {"additional_insured_required": False},
                 "has_crime": False}
        _drop_unstated_risk_transfer(facts, DEC_TEXT)
        assert facts["has_crime"] is False


# ── F11: an endorsement date is not an inception date ────────────────────────

class TestEndorsementDates:

    ENTRIES = [
        {"label": "Policy Effective Date", "value": "07/15/2025",
         "policy_number": "6J7-40-02---26",
         "line_of_business": "Commercial Umbrella"},
        {"label": "Policy Number", "value": "6J7-40-02---26",
         "policy_number": "6J7-40-02---26",
         "line_of_business": "Commercial Umbrella"},
    ]

    def test_the_probe_run_b_defect(self):
        mf = {"umbrella_effective_date": "07/25/2025",
              "effective_date": "07/15/2025",
              "additional_remarks_text": UMBRELLA_REMARK,
              "dec_page_entries": self.ENTRIES}
        _drop_endorsement_dates_from_policy_facts(mf, [])
        assert "umbrella_effective_date" not in mf
        assert mf["effective_date"] == "07/15/2025", "the real term must survive"

    def test_a_date_the_dec_page_prints_is_kept(self):
        """A policy whose term genuinely starts the day an endorsement takes
        effect keeps its date - the declarations page witnesses it."""
        mf = {"umbrella_effective_date": "07/25/2025",
              "additional_remarks_text": UMBRELLA_REMARK,
              "dec_page_entries": self.ENTRIES + [
                  {"label": "Umbrella Effective Date", "value": "07/25/2025"}]}
        _drop_endorsement_dates_from_policy_facts(mf, [])
        assert mf["umbrella_effective_date"] == "07/25/2025"

    def test_no_amendment_means_no_action(self):
        mf = {"umbrella_effective_date": "07/25/2025",
              "additional_remarks_text": "Nothing was amended.",
              "dec_page_entries": self.ENTRIES}
        _drop_endorsement_dates_from_policy_facts(mf, [])
        assert mf["umbrella_effective_date"] == "07/25/2025"

    def test_it_never_raises_on_an_empty_session(self):
        mf = {}
        _drop_endorsement_dates_from_policy_facts(mf, [])
        assert mf == {}

    def test_no_dec_index_means_no_opinion(self):
        """REGRESSION GUARD for FIX_TRACKING Round 3 Fix 13.

        Without dec entries there is no way to ask whether a date is printed as
        a policy date, so every amendment date looks unwitnessed. If the
        amendment happens to take effect on the policy's OWN inception date,
        removing it deletes `effective_date` - and `_route_renewal_dates` then
        has nothing to route, so ACORD 125's PROPOSED EFF/EXP goes blank and
        Tier-1 demands a date the document already answers. That is exactly the
        regression Round 3 was written to undo.
        """
        remark = ("The Commercial Umbrella limit was reduced from $3,000,000 "
                  "to $1,000,000 effective 07/15/2025.")
        mf = {"effective_date": "07/15/2025", "expiration_date": "07/15/2026",
              "additional_remarks_text": remark}
        _drop_endorsement_dates_from_policy_facts(mf, [])
        assert mf["effective_date"] == "07/15/2025"
        assert mf["expiration_date"] == "07/15/2026"

    def test_the_renewal_routing_still_receives_its_input(self):
        """End to end with the machinery Fix 2 depends on: an amendment sharing
        the inception date must not strip the term the routing reads."""
        from services.extraction_service import _route_renewal_dates
        remark = ("Limit reduced from $3,000,000 to $1,000,000 effective "
                  "07/15/2025.")
        mf = {"effective_date": "07/15/2025", "expiration_date": "07/15/2026",
              "is_renewal": "yes", "additional_remarks_text": remark,
              "dec_page_entries": [
                  {"label": "Policy Effective Date", "value": "07/15/2025"},
                  {"label": "Policy Expiration Date", "value": "07/15/2026"}]}
        _drop_endorsement_dates_from_policy_facts(mf, [])
        assert mf.get("effective_date") == "07/15/2025", "routing input survives"
        _route_renewal_dates(mf)
        assert mf.get("prior_effective_date") or mf.get("effective_date"),             "the renewal machinery still has a term to work with"


# ── F10: a document's title is not a remark ──────────────────────────────────

class TestPageFurniture:

    TITLE = ("PROBE 2 - COMMERCIAL PACKAGE DECLARATIONS Upload together with "
             "PROBE 3. Full printing of every shared value.")
    REAL = ("Loss history: the insured reports two claims in the prior five "
            "years. A water damage claim dated 03/14/2023 was paid at $18,400 "
            "and is closed.")

    def _run(self, value, text):
        mf = {"additional_remarks_text": value}
        _drop_page_furniture_remarks(mf, [{"text": text}])
        return "additional_remarks_text" in mf

    def test_the_probe_run_b_title_is_dropped(self):
        assert not self._run(self.TITLE, self.TITLE + " COMMON POLICY DECLARATIONS")

    def test_a_short_form_heading_is_dropped(self):
        assert not self._run("COMMERCIAL PACKAGE DECLARATIONS",
                             "COMMERCIAL PACKAGE DECLARATIONS  Named Insured...")

    def test_a_real_remark_after_a_header_is_kept(self):
        """An ACORD 101 is mostly remarks and they start right after a one-line
        header. A first cut asked only "within the first 200 chars" and dropped
        this - "near the top" is not the signal, "IS the top" is."""
        assert self._run(self.REAL,
                         "ACORD 101 ADDITIONAL REMARKS SCHEDULE  " + self.REAL)

    def test_a_real_remark_that_opens_its_document_is_kept(self):
        """Too long to be a heading, so content wins even at position zero."""
        assert self._run(self.REAL, self.REAL + " more follows")

    def test_a_remark_buried_mid_document_is_kept(self):
        assert self._run(self.REAL, "x" * 400 + self.REAL)


# ── F15: the warning that fired on every submission ──────────────────────────

class TestCrimeSilentExposure:

    def test_a_roofing_contractor_gets_no_warning(self):
        """THE REPORTED CASE: it fired on all four probe runs. The trigger was
        `num_employees > 10`, which is below almost every commercial account -
        and the message then claimed the DESCRIPTION indicated cash handling,
        which it never did."""
        facts = {"operations_description":
                 "Commercial roofing contractor performing re-roofing and "
                 "repair on commercial structures",
                 "num_employees": "47"}
        assert _check_crime_silent_exposure(facts, {}, set()) == []

    def test_headcount_alone_never_triggers_it(self):
        for n in ("11", "47", "500", "5000"):
            assert _check_crime_silent_exposure(
                {"num_employees": n, "operations_description": "roofing"},
                {}, set()) == []

    @pytest.mark.parametrize("ops", [
        "Full service restaurant with bar, cash handling on premises",
        "Retail jewelry store",
        "Check cashing and money transfer services",
        "Armored car and vault services",
    ])
    def test_a_genuine_cash_exposure_still_fires(self, ops):
        issues = _check_crime_silent_exposure(
            {"operations_description": ops}, {}, set())
        assert len(issues) == 1
        assert issues[0]["code"] == "crime_silent_exposure"

    def test_the_message_names_the_evidence(self):
        """A producer must be able to check whether we read the document right,
        rather than being told what their own description "indicates"."""
        issues = _check_crime_silent_exposure(
            {"operations_description": "Retail jewelry store"}, {}, set())
        assert "'jewelry'" in issues[0]["message"]
        assert "retail" in issues[0]["message"]

    def test_existing_crime_coverage_still_silences_it(self):
        assert _check_crime_silent_exposure(
            {"operations_description": "Retail cash business"},
            {"has_crime": True}, set()) == []
        assert _check_crime_silent_exposure(
            {"operations_description": "Retail cash business",
             "crime_limit": "$50,000"}, {}, set()) == []

    def test_the_narrative_fields_are_read_too(self):
        """Detection was widened when the headcount trigger was removed, so a
        genuine exposure described elsewhere is not lost."""
        assert len(_check_crime_silent_exposure(
            {"account_description": "Operates a chain of pawn shops"},
            {}, set())) == 1
