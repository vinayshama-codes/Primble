"""Live run 2 (11 Sep 2026) - five root causes, one theme.

Every defect this round was the same sentence in a different place: **an empty
box beside a populated record gets filled from whatever is nearest, and nothing
asks whether that thing belongs there.**

  R1  a line-scoped GRID with no evidence for its own line was handed to gap
      fill, which filled the ACORD 126 schedule of hazards with an auto row
  R2  one vehicle described by two documents became two vehicles, because a row
      with no VIN has no natural identifier and is never merged
  R3  an interest holder's street address landed in the REFERENCE / LOAN # box
  R4  a fact carrying an amount AND its structure was compared against a box
      that holds only the amount
  R5  an ADDITIONAL INSURED printed as the NAME OF OTHER OWNER of a vehicle
"""
import os
import random
import string
import sys

import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import services.pdf_service as ps
from services.extraction_service import _dedupe_schedule_rows, stated_party_roles
from services.field_qa import run_field_qa

VIN_A = "4S4BRCGC9C3217772"
VIN_B = "1FT7W2BT5KEC12345"


# ═════════════════════════════════════════════════════════════════════════════
class TestR1AGridWithNoEvidenceForItsOwnLine:
    """The reversal of "no evidence -> hand it to gap fill", on measurement.

    That rule was a PREDICTION - that gap fill would recover a schedule
    extraction missed. Three live runs measured it and it recovered nothing;
    it printed another line's data every time.
    """

    # RUN B verbatim: General Liability and Business Auto on one package, an
    # auto schedule extracted, no GL classification anywhere.
    RUN_B = {"_form_id": "ACORD_126",
             "auto_vin_schedule": [{"vin": VIN_B, "make": "Ford", "year": "2019",
                                    "model": "F-250", "class_code": "7398"}],
             "auto_covered_symbols": [{"coverage": "liability", "symbols": "7"}]}
    RUN_A = {"_form_id": "ACORD_126",
             "gl_class_code_schedule": [
                 {"class_code": "91580", "classification": "Contractors - subcontracted work",
                  "premium_basis": "Cost", "exposure_amount": "$91,580", "location": "1"},
                 {"class_code": "91585", "classification": "Contractors - executive supervisors",
                  "premium_basis": "Payroll", "exposure_amount": "$350,000", "location": "1"}],
             "auto_vin_schedule": [{"vin": VIN_A, "class_code": "7383"}]}

    HAZARD = ("GeneralLiability_Hazard_ClassCode_A",
              "GeneralLiability_Hazard_Classification_A",
              "GeneralLiability_Hazard_PremiumBasisCode_A",
              "GeneralLiability_Hazard_Exposure_A",
              "GeneralLiability_Hazard_TerritoryCode_A")

    def test_the_whole_hazard_grid_is_blank_with_no_gl_evidence(self):
        """Run B printed `Symbol 07`, `CO`, `NO`, `F-250` and `2019` across
        three hazard rows of a GENERAL LIABILITY form. Not one of those is a GL
        classification; every one is a cell of the auto schedule."""
        for field in self.HAZARD:
            assert ps._resolve_gl_hazard_row(field, self.RUN_B) is None, field
            assert ps._is_authoritative_blank_field(field, self.RUN_B) is True, field

    def test_a_real_gl_schedule_is_untouched(self):
        assert ps._resolve_gl_hazard_row(self.HAZARD[0], self.RUN_A) == "91580"
        assert ps._resolve_gl_hazard_row(self.HAZARD[1], self.RUN_A) == \
            "Contractors - subcontracted work"
        assert ps._is_authoritative_blank_field(self.HAZARD[0], self.RUN_A) is False

    def test_the_coverages_and_limits_boxes_are_not_grid_cells(self):
        """The blanket must cover the GRID and nothing else. Run B's 126
        correctly printed $2,000,000 aggregate and $1,000,000 each occurrence
        with no GL schedule at all, and that must not change."""
        for field in ("GeneralLiability_EachOccurrenceLimit_A",
                      "GeneralLiability_GeneralAggregate_LimitAmount_A",
                      "GeneralLiability_ClaimsMade_ProposedRetroactiveDate_A"):
            assert ps._resolve_phantom_gl_hazard_row(field, self.RUN_B) is ps._SCHED_SKIP

    def test_gl_evidence_is_derived_from_the_fact_key_not_a_list(self):
        assert ps._gl_schedule_evidence({"gl_class_code_schedule": [{"class_code": "1"}]}) is True
        assert ps._gl_schedule_evidence({"gl_class_codes_by_location": [{"codes": "1"}]}) is True
        assert ps._gl_schedule_evidence({"auto_vin_schedule": [{"vin": VIN_A}]}) is False
        assert ps._gl_schedule_evidence({"gl_class_code_schedule": []}) is False
        assert ps._gl_schedule_evidence({}) is False
        assert ps._gl_schedule_evidence(None) is False

    # ── THE RULE DOES NOT GENERALISE, AND THAT IS THE FINDING ───────────────
    def test_the_vehicle_grid_is_deliberately_NOT_blanked(self):
        """I generalised this rule to every line-scoped grid and it was WRONG.
        Three existing tests caught it inside one suite run
        (`test_table_row_dedup` x3, `test_phantom_schedule_rows`,
        `test_raw_text_verification`).

        The two grids are not the same case:

          ACORD 126's hazard grid has NO alternative source. Its only input is
          the GL classification schedule, so with no such fact anything gap fill
          writes there came from another line's table. Measured three times.

          A VEHICLE grid DOES have one - the vehicles are in the uploaded
          document as text. Gap fill reading them is a plausible RECOVERY, and
          blanking the grid would delete a real fleet extraction merely missed:
          a bigger deletion than the defect being fixed.

        The measured 2026-08-13 defect was in row B, and
        `_unanchored_schedule_row_fields` already sweeps any row past the first
        whose identity columns are empty. That is the right-sized guard here.
        """
        assert ps._resolve_phantom_schedule_row(
            "Vehicle_RateClassCode_A", {"_form_id": "ACORD_127"}) is ps._SCHED_SKIP
        assert ps._resolve_phantom_schedule_row(
            "Vehicle_PhysicalAddress_CityName_A", {"_form_id": "ACORD_127"}) is ps._SCHED_SKIP

    def test_a_repeating_field_is_not_always_a_grid_cell(self):
        """The second, independent reason the generalisation failed. Nothing
        separated a grid CELL from a per-form field that merely repeats:
        `Vehicle_Question_ModifiedEquipmentDescription_A/B` is a General
        Information answer printed twice, and a "repeats across rows" test
        blanks it as a vehicle row. The same row-versus-singleton confusion
        the 2026-09-08 regression was."""
        schema = ps._all_form_schemas()["ACORD_127"]
        base = "Vehicle_Question_ModifiedEquipmentDescription"
        rows = [L for L in "ABCDEFGHIJKLMN" if f"{base}_{L}" in schema]
        assert len(rows) > 1, "the trap only exists because this field repeats"
        assert base not in ps._SCHEDULE_REGISTRY
        assert ps._resolve_phantom_schedule_row(
            f"{base}_A", {"_form_id": "ACORD_127"}) is ps._SCHED_SKIP

    def test_a_real_vehicle_schedule_still_suppresses_rows_past_its_end(self):
        """The half that must not move: positive evidence still bounds the grid."""
        facts = {"_form_id": "ACORD_127", "auto_vin_schedule": [{"vin": VIN_A}]}
        assert ps._resolve_phantom_schedule_row(
            "Vehicle_VINIdentifier_A", facts) is ps._SCHED_SKIP
        assert ps._resolve_phantom_schedule_row(
            "Vehicle_VINIdentifier_C", facts) is None

    def test_the_gl_rule_is_scoped_to_the_gl_hazard_grid(self):
        """R1 lives inside the two resolvers that already own that grid, so it
        cannot reach anything else by construction."""
        assert ps._resolve_phantom_gl_hazard_row(
            "Vehicle_RateClassCode_A", {"_form_id": "ACORD_127"}) is ps._SCHED_SKIP
        assert ps._resolve_phantom_gl_hazard_row(
            "LossHistory_AmountPaid_A", {"_form_id": "ACORD_126"}) is ps._SCHED_SKIP

    def test_gap_fill_is_not_asked_about_the_blanked_hazard_grid(self):
        """THE SEAM, not the function. Guarding the mapper and leaving the box
        open is how this class of defect has come back twice - the blank goes
        straight to gap fill, which refills it. Measured through
        `compute_form_gaps`, the contract gap fill actually consults."""
        schema = ps._all_form_schemas()["ACORD_126"]
        _m, unmatched, det = ps.compute_form_gaps("ACORD_126", schema, self.RUN_B)
        asked = [k for k in unmatched if k.startswith("GeneralLiability_Hazard_")]
        owned = [k for k in det if k.startswith("GeneralLiability_Hazard_")]
        assert asked == [], asked
        assert len(owned) >= 20, len(owned)
        # ...and with a real schedule a column the schedule CAN answer but did
        # not - an empty EXPOSURE - stays open. TERRITORY does not since 14 Sep
        # 2026: a GL row that prints none has none, and the only other
        # "TERRITORY" a package offers gap fill is another line's (Orbin: the
        # auto Drive Other Car "TERRITORY: 104 6679" on both hazard rows).
        import copy
        run_a = copy.deepcopy(self.RUN_A)
        run_a["gl_class_code_schedule"][1]["exposure_amount"] = None
        _m2, unmatched2, _d2 = ps.compute_form_gaps("ACORD_126", schema, run_a)
        assert "GeneralLiability_Hazard_Exposure_B" in unmatched2
        assert "GeneralLiability_Hazard_TerritoryCode_A" not in unmatched2


# ═════════════════════════════════════════════════════════════════════════════
class TestR2OneEntityTwoDocumentsOneRow:
    """A row that only DESCRIBES still describes something the package knows."""

    def _veh(self, rows):
        return _dedupe_schedule_rows("auto_vin_schedule", rows)

    def test_the_reported_phantom_subaru(self):
        """ACORD 127 printed a SECOND 2012 Subaru Outback with no VIN. Both
        rows were correct; only one vehicle exists."""
        out = self._veh([
            {"vin": VIN_A, "make": "Subaru", "year": "2012", "model": "Outback",
             "class_code": "7383"},
            {"make": "Subaru", "year": "2012", "model": "Outback"}])
        assert len(out) == 1
        assert out[0]["vin"] == VIN_A and out[0]["class_code"] == "7383"

    def test_a_genuine_second_vehicle_survives(self):
        assert len(self._veh([
            {"vin": VIN_A, "make": "Subaru", "year": "2012", "model": "Outback"},
            {"make": "Ford", "year": "2019", "model": "F-250"}])) == 2

    def test_one_disagreement_is_a_different_entity(self):
        assert len(self._veh([
            {"vin": VIN_A, "make": "Subaru", "year": "2012", "model": "Outback"},
            {"make": "Subaru", "year": "2019", "model": "Outback"}])) == 2

    def test_an_ambiguous_thin_row_is_kept_not_guessed(self):
        """Two 2012 Subarus with different VINs make a bare '2012 Subaru
        Outback' genuinely ambiguous. Folding it would be a coin flip."""
        assert len(self._veh([
            {"vin": VIN_A, "make": "Subaru", "year": "2012", "model": "Outback"},
            {"vin": VIN_B, "make": "Subaru", "year": "2012", "model": "Outback"},
            {"make": "Subaru", "year": "2012", "model": "Outback"}])) == 3

    def test_the_thin_row_contributes_what_it_knows(self):
        out = self._veh([
            {"vin": VIN_A, "make": "Subaru", "year": "2012", "model": "Outback"},
            {"make": "Subaru", "year": "2012", "body_type": "Wagon"}])
        assert len(out) == 1 and out[0]["body_type"] == "Wagon"

    def test_spelling_differences_still_agree(self):
        assert len(self._veh([
            {"vin": VIN_A, "make": "SUBARU", "year": "2012", "model": "Out-back"},
            {"make": "subaru", "year": "2012", "model": "Outback"}])) == 1

    def test_a_thin_row_matching_nothing_is_kept(self):
        assert len(self._veh([
            {"vin": VIN_A, "make": "Subaru", "year": "2012", "model": "Outback"},
            {"vin": VIN_B, "make": "Ford", "year": "2019", "model": "F-250"},
            {"make": "Tesla", "year": "2024", "model": "Model Y"}])) == 3

    def test_it_never_raises_on_junk(self):
        for rows in ([], [None], ["x"], [{}, {"make": "Ford"}], [{"vin": VIN_A}, {}]):
            _dedupe_schedule_rows("auto_vin_schedule", list(rows))


# ═════════════════════════════════════════════════════════════════════════════
class TestR3AnAddressIsNotAnIdentifier:
    """ACORD's REFERENCE / LOAN # box declares "Enter identifier:". It came back
    holding the interest holder's own street, on four forms across both runs."""

    LIVE_ADDRESSES = [
        "800 Walnut Street, Des Moines, IA 50309",
        "1600 Broadway, Boulder, CO 80302",
        "1450 Wynkoop Street, Denver, CO 80202",
        "900 Pearl St, Boulder, CO 80302",
        "15151 E Alameda Pkwy, Aurora, CO 80012",
        "1201 Port of Tacoma Rd, Tacoma, WA 98421",
        "77 Larimer Street, Denver, CO 80202",
    ]
    REAL_IDENTIFIERS = [
        "800 4471", "0482854", "BBC7263 - 26", "6E7-40-02---26", "GPC-GL-55210",
        "ACCT 1234, SUB 5", "LOAN 99-88-77", "4471-0002-8891", "12345678901234",
        "800-WALNUT-2024", "IM 7100 06 04", "2215 73 133 57140,4289",
        "3703 QMG 65305,/818", "98765, 43210", "POL 123, REF 456",
    ]

    @pytest.mark.parametrize("value", LIVE_ADDRESSES)
    def test_every_live_address_is_recognised(self, value):
        assert ps._looks_like_a_street_address(value) is True

    @pytest.mark.parametrize("value", REAL_IDENTIFIERS)
    def test_no_real_identifier_is_mistaken_for_one(self, value):
        assert ps._looks_like_a_street_address(value) is False

    def test_the_identifier_box_refuses_it(self):
        meta = {"tu": "Enter identifier: The loan number, account number or "
                      "other controlling number that identifies the interest."}
        why = ps._rejects_declared_type(
            "AdditionalInterest_AccountNumberIdentifier_A", meta,
            "800 Walnut Street, Des Moines, IA 50309")
        assert why and "street address" in why
        assert ps._rejects_declared_type(
            "AdditionalInterest_AccountNumberIdentifier_A", meta, "4471-0002-8891") is None

    def test_a_free_text_box_is_untouched(self):
        """The rule belongs to identifier and code boxes. An address in an
        ADDRESS box is the whole point of the form."""
        meta = {"tu": "Enter text: The mailing address of the interest."}
        assert ps._rejects_declared_type(
            "AdditionalInterest_MailingAddress_LineOne_A", meta,
            "800 Walnut Street, Des Moines, IA 50309") is None

    def test_generated_identifiers_do_not_trip_it(self):
        """4,000 generated loan / account / policy numbers. The first draft put
        25 through - a five-digit RUN anywhere read as a postcode - which is why
        the postcode is anchored to the end of the line and a street WORD is
        required."""
        random.seed(11)
        seps = ["", "-", " ", "/", ".", " - ", "--"]
        pre = ["", "POL", "ACCT", "LOAN", "REF", "GL", "BA", "CP", "IM", "WC", "BBC"]
        false_positives = []
        for _ in range(4000):
            parts = [random.choice(pre)] + [
                "".join(random.choice(string.digits) for _ in range(random.randint(2, 7)))
                for _ in range(random.randint(1, 4))]
            if random.random() < .3:
                parts.insert(random.randint(0, len(parts)), "".join(
                    random.choice(string.ascii_uppercase) for _ in range(random.randint(1, 3))))
            text = random.choice(seps).join(p for p in parts if p)
            if random.random() < .15:
                text += "," + random.choice(seps) + str(random.randint(1, 9999))
            if ps._looks_like_a_street_address(text):
                false_positives.append(text)
        assert len(false_positives) <= 2, false_positives[:8]


# ═════════════════════════════════════════════════════════════════════════════
class TestR4AnAmountBoxHoldsTheAmount:
    """The last value mismatch on the cover page, and both sides were right."""

    FIELD = "Vehicle_CombinedSingleLimit_EachAccidentAmount_A"

    def test_the_reported_mismatch_is_gone(self):
        facts = {"auto_liability_limit": "$1,000,000 Combined Single Limit"}
        gen = {"ACORD_131": {"mapped": {self.FIELD: "1,000,000"},
                             "confidence": {self.FIELD: "deterministic"},
                             "schema": {self.FIELD: {"ft": "/Tx"}}}}
        res = run_field_qa(gen, facts)
        assert [r for r in res["results"] if r["reason_code"] == "value_mismatch"] == []

    def test_a_genuinely_wrong_amount_still_fails(self):
        facts = {"auto_liability_limit": "$1,000,000 Combined Single Limit"}
        gen = {"ACORD_131": {"mapped": {self.FIELD: "500,000"},
                             "confidence": {self.FIELD: "deterministic"},
                             "schema": {self.FIELD: {"ft": "/Tx"}}}}
        fails = [r for r in run_field_qa(gen, facts)["results"]
                 if r["reason_code"] == "value_mismatch"]
        assert len(fails) == 1 and fails[0]["expected"] == "$1,000,000"

    def test_two_amounts_are_left_whole(self):
        """"$1,000,000 / $2,000,000" states two. Picking one would be a guess."""
        assert ps.expected_value_for_field(
            self.FIELD, "auto_liability_limit",
            "$1,000,000 / $2,000,000") == "$1,000,000 / $2,000,000"

    def test_a_non_amount_box_is_untouched(self):
        assert ps.expected_value_for_field(
            "NamedInsured_FullName_A", "applicant_name",
            "HALVORSEN STRUCTURAL LLC") == "HALVORSEN STRUCTURAL LLC"
        assert ps.expected_value_for_field(
            "Insurer_NAICCode_A", "carrier_naic", "25186") == "25186"


# ═════════════════════════════════════════════════════════════════════════════
class TestR5APartyStatedUnderOneRole:
    """`Kestrel Terminal Authority`, an ADDITIONAL INSURED, printed as the NAME
    OF OTHER OWNER of the applicant's Subaru."""

    # THE REAL SHAPE, and the first fixture got it wrong (D22, fourth time).
    # Extraction records one dec entry PER CELL, so a schedule of interests puts
    # the NAME and the INTEREST in SEPARATE entries - the role is never in the
    # name's own label. Reading label+section returned {name, organization,
    # schedule, additional} for every party in the table, which cannot tell an
    # additional insured from a legitimate owner.
    #
    # The FACT KEY carries the role reliably on every layout, so that is what
    # `stated_party_roles` reads. The entries below are the live kit's actual
    # shape and contribute nothing - which is the point.
    ENTRIES = {
        "loss_payee_name": "Wells Fargo Equipment Finance, Inc.",
        "mortgagee_name": "John A. Smith",
        "risk_transfer": {
            "loss_payee_name": "Wells Fargo Equipment Finance, Inc.",
            "mortgagee_name": "John A. Smith",
            "additional_insured_names": ["Kestrel Terminal Authority", "City of Aurora"],
        },
        "dec_page_entries": [
            {"label": "NAME OR ORGANIZATION", "section": "SCHEDULE OF ADDITIONAL INTERESTS",
             "value": "Kestrel Terminal Authority"},
            {"label": "INTEREST", "section": "SCHEDULE OF ADDITIONAL INTERESTS",
             "value": "Additional Insured"},
            {"label": "NAME OR ORGANIZATION", "section": "SCHEDULE OF ADDITIONAL INTERESTS",
             "value": "Rocky Mountain Leasing LLC"},
        ],
    }

    def setup_method(self):
        ps._set_schema_context(ps._all_form_schemas()["ACORD_127"])

    def teardown_method(self):
        ps._set_schema_context(None)

    def test_the_reported_case(self):
        out = ps._party_in_the_wrong_role_box(
            {"AdditionalInterest_FullName_C": "Kestrel Terminal Authority"}, self.ENTRIES)
        assert "AdditionalInterest_FullName_C" in out

    def test_a_party_with_no_stated_role_keeps_the_owner_row(self):
        """`Rocky Mountain Leasing LLC` appears only as a table NAME cell, so
        the package states no role for it. Silence is no opinion - and this is
        the case the first cut got wrong, blanking it because its column
        heading ("NAME OR ORGANIZATION") is not the word "owner"."""
        assert ps._party_in_the_wrong_role_box(
            {"AdditionalInterest_FullName_C": "Rocky Mountain Leasing LLC"},
            self.ENTRIES) == {}

    def test_every_party_with_a_DIFFERENT_stated_role_is_refused(self):
        """A loss payee and a mortgagee are no more the vehicle's owner than an
        additional insured is."""
        for who in ("Kestrel Terminal Authority", "City of Aurora",
                    "Wells Fargo Equipment Finance, Inc.", "John A. Smith"):
            assert ps._party_in_the_wrong_role_box(
                {"AdditionalInterest_FullName_C": who}, self.ENTRIES), who

    def test_only_an_ACORD_ROLE_WORD_counts_as_a_stated_role(self):
        """A column heading is not a relationship. "NAME OR ORGANIZATION"
        arrives as {name, organization} and must not read as a role."""
        from services.extraction_service import stated_party_roles
        roles = stated_party_roles(self.ENTRIES)
        assert roles["kestrel terminal authority"] >= {"additional", "insured"}
        assert roles["wells fargo equipment finance inc"] >= {"loss", "payee"}
        acord = set(ps._acord_interest_roles())
        assert not (roles["rocky mountain leasing llc"] & acord)

    def test_a_generic_interest_row_asserts_nothing_and_is_never_judged(self):
        """Row A's tooltip is "The additional interest's full name." with no
        "As used here" clause. An unasserted box is never judged, which is what
        leaves an ordinary loss payee alone."""
        assert ps._roles_a_box_asserts("AdditionalInterest_FullName_A") == set()
        assert ps._party_in_the_wrong_role_box(
            {"AdditionalInterest_FullName_A": "Kestrel Terminal Authority"},
            self.ENTRIES) == {}

    def test_silence_is_no_opinion(self):
        assert ps._party_in_the_wrong_role_box(
            {"AdditionalInterest_FullName_C": "Kestrel Terminal Authority"}, {}) == {}
        assert ps._party_in_the_wrong_role_box(
            {"AdditionalInterest_FullName_C": "A Company Nobody Mentioned LLC"},
            self.ENTRIES) == {}

    def test_the_roles_are_harvested_from_acords_own_schemas(self):
        """ANTI-ROT and the reason this is not a denylist: the role words come
        from `..._Interest_<Role>Indicator_*` across the 17 real schemas, so a
        form that gains an interest type is covered the day it ships."""
        roles = ps._acord_interest_roles()
        for expected in ("mortgagee", "lienholder", "owner", "payee", "trustee"):
            assert expected in roles, expected
        assert ps._roles_a_box_asserts("AdditionalInterest_FullName_C") == {"owner"}

    def test_stated_party_roles_never_raises(self):
        for entries in (None, "x", [], [None], [{"value": None}], [5],
                        [{"label": None, "section": None, "value": "Acme LLC"}]):
            stated_party_roles({"dec_page_entries": entries})
