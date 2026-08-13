"""Run 8 of 2026-08-13: the survivors were all ONE thing, and the silence was another.

THE Y/N SURVIVORS - one cause, not three. The uploaded package is a POLICY:
~271 pages of contract wording, endorsements and definitions, of which ~30 are
declarations. The form asks about the RISK. So the only text available to
ground most Y/N answers is the contract talking about ITSELF, and every gate we
had verified that a quote EXISTS, never that it is a STATEMENT OF FACT ABOUT
THIS APPLICANT.

    Q8 "any hold harmless agreements?"        = Y  <- the blanket-AI / waiver-of-
                                                     subrogation ENDORSEMENT
    Q9 "any vehicles used by family members?" = Y  <- the Colorado Changes
                                                     endorsement's DEFINITIONS clause
    Q14 "any drivers with convictions?"       = Y  <- substantiated by a table
                                                     holding a cross-reference and
                                                     one borrowed digit
    FACTOR = "LIAB-I"                              <- ACORD declares "Enter rate:"
                                                     on 44 fields; the 13th declared
                                                     type, never read

THE SILENCE. `evaluate_stops` validates FACTS; every guard here validates
STAMPED VALUES. Nothing carried the second set anywhere a human could see it,
so four consecutive runs reported "no warnings" on forms where a dozen
fabricated values had been caught and removed.
"""
import json
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("OPENAI_API_KEY", "sk-offline")

import services.pdf_service as ps                                 # noqa: E402
import services.field_qa as fq                                    # noqa: E402

BACKEND = os.path.join(os.path.dirname(__file__), "..")


def _schema(form):
    with open(os.path.join(BACKEND, "forms_schemas", f"{form}_schema.json"),
              encoding="utf-8") as fh:
        return json.load(fh)


# ── 1. Policy wording is not a statement about the applicant ─────────────────

_Q8 = ("Additional insured for ongoing and completed operations; insurance is "
       "primary and will not seek contribution; waiver of transfer of rights "
       "of recovery against others to us when agreed in writing.")
_Q9 = ("Family member means a person related to you by blood, adoption, "
       "marriage or civil union recognized under Colorado law, who is a "
       "resident of your household, including a ward or foster child.")


@pytest.mark.parametrize("quote", [_Q8, _Q9])
def test_the_two_literal_run_8_quotes_are_rejected(quote):
    """MUST NEVER FAIL - these are the client's verbatim values."""
    assert ps._is_contract_wording(quote)


def test_neither_was_reachable_by_the_checks_that_already_existed():
    """The reason this needed a new test, not a widened old one: both quotes
    walk past every prior gate. Pinning that keeps a future 'simplification'
    from deleting this guard as redundant."""
    for quote in (_Q8, _Q9):
        assert ps._quote_asserts_something(quote), "grammatical sentence"
        assert not ps._POLICY_SELF_SUBJECT_RE.search(quote), \
            "does not open with 'this/such <policy noun>'"
        assert not ps._QUOTE_CTA_RE.match(quote), "not an instruction"


@pytest.mark.parametrize("genuine", [
    "The applicant transports hazardous materials to job sites weekly.",
    "The applicant does not have any subsidiaries.",
    "Subcontractors are required to carry coverage.",
    "Custom ladder rack mounted on roof.",
    "This policy was cancelled for non-payment of premium.",
    "Over 50% of employees use their personal autos in the business.",
    "INSURED IS: LLC",
    "Date of Issue: 07/16/2025",
    "The applicant stores acetylene and oxygen cylinders in a locked cage.",
    "Erin Royal drives a company vehicle and holds a valid CO license.",
])
def test_real_applicant_statements_survive(genuine):
    """The other direction, and the one that matters more: a register test that
    ate genuine answers would be worse than the defect. Third-person statements
    about the applicant are untouched, including one that mentions the policy."""
    assert not ps._is_contract_wording(genuine), genuine


def test_the_gate_rejects_contract_wording_in_both_directions():
    """A definition concludes nothing, so it grounds neither a Y nor an N. The
    owner's rule is symmetric: 'if we have conclusive evidence of EITHER...'."""
    tu = ('Enter Y for a "Yes" response. Input N for "No" response. Indicates '
          'the response to the question, "Any vehicles used by family members?"')
    fields = {"CommercialVehicleLineOfBusiness_Question_AAKCode_A":
              {"tu": tu, "ft": "/Tx"}}
    q = "CommercialVehicleLineOfBusiness_Question_AAKCode_A"
    for answer in ("Y", "N"):
        mapped, _ = ps.map_facts_to_form(
            {}, fields, "ACORD_127", raw_text=_Q9,
            pre_filled_gpt={"filled_values": {q: answer},
                            "raw_text_fields": set(),
                            "question_grounding": {q: _Q9}})
        assert mapped.get(q) is None, answer


# ── 2. A cross-reference is not a fact ───────────────────────────────────────

@pytest.mark.parametrize("text", [
    "SEE ITEM FOUR FOR HIRED OR BORROWED AUTOS",      # run 8, conviction TYPE
    "SEE SCHEDULE FOR DED .",                          # run 8, auto collision ded
    "Refer to the attached schedule",
    "As shown in the Declarations",
    "Per the endorsement attached hereto",
])
def test_a_cross_reference_is_an_instruction_not_evidence(text):
    assert ps._QUOTE_CTA_RE.match(text), text


@pytest.mark.parametrize("text", [
    "Seeing eye dogs are kept on premises.",   # 'see' must not eat 'seeing'
    "Personal property of others is stored on site.",
])
def test_the_widened_cross_reference_rule_does_not_overreach(text):
    assert not ps._QUOTE_CTA_RE.match(text), text


# ── 3. A borrowed digit does not substantiate a Yes ──────────────────────────

_YN_TU = ('Enter Y for a "Yes" response. Input N for "No" response. '
          'Indicates the response to the question, "{}"')


def test_q14_falls_when_its_table_holds_only_a_cross_reference_and_a_digit():
    """Run 8 verbatim: Q14 = Y, its conviction row holding TYPE = 'SEE ITEM
    FOUR FOR HIRED OR BORROWED AUTOS' and '#YRS REV' = 3, everything else
    empty."""
    q = "CommercialVehicleLineOfBusiness_Question_AAICode_A"
    fields = {
        q: {"tu": _YN_TU.format(
            "Any drivers with convictions for moving traffic violations?"),
            "ft": "/Tx"},
        "AccidentConviction_DriverNumber_A": {"tu": "Enter number", "ft": "/Tx"},
        "AccidentConviction_IncidentDate_A": {"tu": "Enter date", "ft": "/Tx"},
        "AccidentConviction_IncidentType_A": {"tu": "Enter text", "ft": "/Tx"},
        "AccidentConviction_PlaceOfIncident_A": {"tu": "Enter text", "ft": "/Tx"},
        "AccidentConviction_YearsRevokedCount_A": {"tu": "Enter number", "ft": "/Tx"},
        "CommercialVehicleLineOfBusiness_Question_KAGCode_A":
            {"tu": _YN_TU.format("Are all vehicles part of a fleet?"), "ft": "/Tx"},
    }
    doc = ("BUSINESS AUTO DECLARATIONS\nSEE ITEM FOUR FOR HIRED OR BORROWED "
           "AUTOS\n3\nDrivers have had convictions.\n")
    pre = {"filled_values": {
               q: "Y",
               "AccidentConviction_IncidentType_A":
                   "SEE ITEM FOUR FOR HIRED OR BORROWED AUTOS",
               "AccidentConviction_YearsRevokedCount_A": "3"},
           "raw_text_fields": set(),
           "question_grounding": {q: "Drivers have had convictions."}}
    mapped, _ = ps.map_facts_to_form({}, fields, "ACORD_127",
                                     raw_text=doc, pre_filled_gpt=pre)
    assert mapped.get("AccidentConviction_IncidentType_A") is None
    assert mapped.get("AccidentConviction_YearsRevokedCount_A") is None
    assert mapped.get(q) is None


def test_a_complete_numeric_dependent_row_is_never_second_guessed():
    """The bare-number rule is gated on the section being INCOMPLETE. A table
    ACORD genuinely designed as all-numeric, fully filled, must survive - this
    is the guard on the guard."""
    q = "CommercialVehicleLineOfBusiness_Question_AAJCode_A"
    fields = {
        q: {"tu": _YN_TU.format("Are any vehicles not solely owned?"),
            "ft": "/Tx"},
        "OtherOwner_VehicleNumber_A": {"tu": "Enter number", "ft": "/Tx"},
        "OtherOwner_ItemNumber_A": {"tu": "Enter number", "ft": "/Tx"},
        "CommercialVehicleLineOfBusiness_Question_KAGCode_A":
            {"tu": _YN_TU.format("Fleet?"), "ft": "/Tx"},
    }
    doc = ("The applicant leases vehicle 1 from a third party under item 2.\n")
    pre = {"filled_values": {q: "Y",
                             "OtherOwner_VehicleNumber_A": "1",
                             "OtherOwner_ItemNumber_A": "2"},
           "raw_text_fields": set(),
           "question_grounding": {
               q: "The applicant leases vehicle 1 from a third party "
                  "under item 2."}}
    mapped, _ = ps.map_facts_to_form({}, fields, "ACORD_127",
                                     raw_text=doc, pre_filled_gpt=pre)
    assert mapped.get("OtherOwner_VehicleNumber_A") == "1"
    assert mapped.get(q) == "Y"


def test_a_dependent_cell_substantiates_nothing_whatever_produced_it():
    """THE FOURTH-DOOR RULE, applied one level down. 'Is this an artifact?' is a
    question about the VALUE, so the check may not ask who wrote it."""
    src = open(os.path.join(BACKEND, "services", "pdf_service.py"),
               encoding="utf-8").read()
    idx = src.index("DEP_IS_COVERAGE_ARTIFACT")
    window = src[idx - 900:idx]
    assert "_d in gpt_filled_set" not in window, (
        "the dependent artifact check is scoped to gap fill again - an "
        "alias-stamped or deterministically-routed cell can now substantiate "
        "a Yes with junk the model would have been refused for")


# ── 4. ACORD's 13th declared type ────────────────────────────────────────────

def test_a_rating_factor_box_rejects_a_coverage_code():
    """Run 8: FACTOR = 'LIAB-I' on the vehicle row."""
    schema = _schema("ACORD_127")
    f = "Vehicle_PrimaryLiabilityRatingFactor_A"
    assert ps._tooltip_declared_type(schema[f]) == "rate"
    assert ps._rejects_declared_type(f, schema[f], "LIAB-I")


@pytest.mark.parametrize("rate", ["1.25", ".85", "0.80", "80%", "1", "1.05 CR",
                                  "1.15 debit", "0", "2.5"])
def test_every_plausible_rate_notation_survives(rate):
    """The bar is 'contains a digit' precisely so no carrier's notation can be
    blanked. Swept across all 44 rate-typed fields by the test below."""
    schema = _schema("ACORD_127")
    f = "Vehicle_NetRatingFactor_A"
    assert not ps._rejects_declared_type(f, schema[f], rate), rate


def test_the_rate_rule_swept_across_every_schema_has_no_false_positive():
    """The sweep IS the test, same standard C22 set. 44 rate-typed fields x 9
    legitimate notations; zero may be rejected."""
    import glob
    fields = []
    for path in glob.glob(os.path.join(BACKEND, "forms_schemas", "*_schema.json")):
        with open(path, encoding="utf-8") as fh:
            for name, meta in json.load(fh).items():
                if ps._tooltip_declared_type(meta) == "rate":
                    fields.append((name, meta))
    assert len(fields) >= 40, f"only {len(fields)} rate-typed fields - re-measure"
    for name, meta in fields:
        # The word conventions are the half the FIRST cut of this rule broke -
        # "a rate with no digit is not a rate" blanked "Included" on all 44,
        # and test_no_legitimate_value_is_ever_blanked caught it. They are
        # pinned here so the wider rule cannot come back.
        for good in ("1.25", ".85", "0.80", "80%", "1", "1.05 CR", "0",
                     "Included", "Statutory", "Excluded", "Waived",
                     "See schedule", "N/A"):
            assert not ps._rejects_declared_type(name, meta, good), (name, good)
        for junk in ("LIAB-I", "COMP/OTC"):
            assert ps._rejects_declared_type(name, meta, junk), (name, junk)


# ── 5. The silence: guard blanks now reach a human ───────────────────────────

def test_map_facts_to_form_reports_what_a_guard_removed():
    """The producer could not tell an empty box we never found a value for from
    an empty box we REFUSED a value for. Now they can."""
    schema = _schema("ACORD_127")
    # A REAL question field off the real schema - a name that does not exist is
    # never absorbed, so a hand-written one would make this pass vacuously.
    q = next(f for f in schema if ps._QUESTION_CODE_FIELD_RE.search(f))
    report: list = []
    mapped, _ = ps.map_facts_to_form(
        {}, schema, "ACORD_127", raw_text=_Q9,
        pre_filled_gpt={"filled_values": {q: "Y"}, "raw_text_fields": set(),
                        "question_grounding": {q: _Q9}},
        guard_report=report)
    assert mapped.get(q) is None, "the ungrounded Yes should have been blanked"
    assert report, "a value was blanked and nothing was reported"
    assert q in {e["field"] for e in report}
    entry = next(e for e in report if e["field"] == q)
    assert set(entry) == {"form_id", "field", "removed_value"}
    assert entry["form_id"] == "ACORD_127"
    assert entry["removed_value"] == "Y"


def test_the_report_is_opt_in_so_no_existing_caller_changes():
    """Every call site and every test that does not ask for the report must
    behave exactly as before - the parameter defaults to None."""
    mapped, conf = ps.map_facts_to_form(
        {"applicant_name": "ORBIN CONTRACTING LLC"}, _schema("ACORD_125"),
        "ACORD_125", raw_text="ORBIN CONTRACTING LLC",
        pre_filled_gpt={"filled_values": {}, "raw_text_fields": set(),
                        "question_grounding": {}})
    assert isinstance(mapped, dict) and isinstance(conf, dict)


def test_guard_blanks_render_as_one_advisory_row_per_form():
    """One row per FORM, not per field: a bad run can blank twenty boxes and
    twenty near-identical rows is the exact flood the client already
    complained about (2026-08-12, 'repeated values are there a lot')."""
    qa = fq.run_field_qa({
        "ACORD_127": {
            "mapped": {}, "confidence": {}, "schema": {},
            "guard_blanks": [
                {"form_id": "ACORD_127", "field": "Producer_FaxNumber_A",
                 "removed_value": "303-996-7800"},
                {"form_id": "ACORD_127",
                 "field": "CommercialVehicleLineOfBusiness_Question_AAKCode_A",
                 "removed_value": "Y"},
                {"form_id": "ACORD_127",
                 "field": "Vehicle_PrimaryLiabilityRatingFactor_A",
                 "removed_value": "LIAB-I"},
                {"form_id": "ACORD_127", "field": "AccidentConviction_IncidentType_A",
                 "removed_value": "SEE ITEM FOUR FOR HIRED OR BORROWED AUTOS"},
            ],
        },
    }, merged_facts={}, confirmations={})
    assert qa["review_count"] >= 4
    rows = fq.to_recommendation_rows(qa)
    guard_rows = [r for r in rows if "left blank on purpose" in (r["message"] or "")]
    assert len(guard_rows) == 1, [r["message"] for r in guard_rows]
    msg = guard_rows[0]["message"]
    assert "ACORD 127" in msg and "4 fields" in msg and "+1 more" in msg
    # Advisory, never a blocker: same soft type every field-QA row uses.
    assert guard_rows[0]["type"] == "suggestion"


def test_a_clean_form_produces_no_guard_row():
    """The row must mean something. A form nothing was refused on stays silent -
    otherwise it is noise and gets ignored, which is how the real one gets
    missed."""
    qa = fq.run_field_qa(
        {"ACORD_127": {"mapped": {}, "confidence": {}, "schema": {},
                       "guard_blanks": []}},
        merged_facts={}, confirmations={})
    rows = fq.to_recommendation_rows(qa)
    assert not [r for r in rows if "left blank on purpose" in (r["message"] or "")]


def test_process_single_form_carries_the_report_to_field_qa():
    """ANTI-ROT for the wiring, which is the half that silently breaks: the key
    field QA reads must be the key form_service writes."""
    src = open(os.path.join(BACKEND, "services", "form_service.py"),
               encoding="utf-8").read()
    assert "guard_report=guard_blanks" in src
    assert '"guard_blanks": guard_blanks' in src
    qa_src = open(os.path.join(BACKEND, "services", "field_qa.py"),
                  encoding="utf-8").read()
    assert '.get("guard_blanks")' in qa_src
