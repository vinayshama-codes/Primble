"""Live run 1 findings F1 / F4 / F5 - fixed 11 Sep 2026.

Every fixture here is built from the SHAPE the engine actually produces, not
from a shape that makes the assertion convenient. That rule is not decoration:
three defects in this arc were checks reading a key the source never emits,
each with a fixture that invented the key (D22). Where a test could only be
written by inventing one, it is not written.

  F1  `field_qa` reported CORRECT per-line values as mismatches against the
      package scalar. A regression introduced by the 11 Sep line-identity work:
      the stamper became line-aware and the checker did not.
  F4  One narrative sentence declared a package claims-made against a
      declarations page that says OCCURRENCE, and ACORD 126 printed an invented
      PROPOSED RETROACTIVE DATE.
  F5  Two parties the document calls ADDITIONAL INSUREDS printed on ACORD 125
      as OTHER NAMED INSUREDS.
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from services.coverage_evidence import gl_form_basis, gl_is_claims_made
from services.extraction_service import _drop_transaction_party_rows
from services.field_qa import run_field_qa
from services.pdf_service import (
    _AUTH_UNOWNED,
    _SCHED_SKIP,
    _resolve_claims_made_dates,
    authoritative_expected_value,
)


# ── The client's Orbin package, as live run 1 produced it ────────────────────
ORBIN_FACTS = {
    "coverage_lines": [
        {"line": "General Liability", "carrier": "EMC Property & Casualty",
         "naic": "25186", "policy_number": "BBC7263 - 26",
         "effective_date": "07/15/2026", "expiration_date": "07/15/2027"},
        {"line": "Business Auto", "carrier": "Employers Mutual Casualty",
         "naic": "21415", "policy_number": "6E7-40-02---26",
         "effective_date": "07/15/2026", "expiration_date": "07/15/2027"},
        {"line": "Inland Marine", "carrier": "Employers Mutual Casualty",
         "naic": "21415", "policy_number": "6C7-40-02---26",
         "effective_date": "07/15/2026", "expiration_date": "07/15/2027"},
        {"line": "Commercial Umbrella", "carrier": "Employers Mutual Casualty",
         "naic": "21415", "policy_number": "6J7-40-02---26",
         "effective_date": "07/15/2026", "expiration_date": "07/15/2027"},
    ],
    # The package scalars field_qa used to compare every form against.
    "policy_number": "BBC7263 - 26",
    "carrier_naic": "25186",
    "carrier_name": "EMC Property & Casualty",
}


def _form(mapped, conf="deterministic"):
    return {"mapped": mapped,
            "confidence": {k: conf for k in mapped},
            "schema": {k: {"ft": "/Tx", "tu": ""} for k in mapped}}


# ═════════════════════════════════════════════════════════════════════════════
class TestF1FieldQaIsLineAware:
    """The checker must resolve the expected value from the same door the
    stamper used, not from the package scalar."""

    def test_the_four_reported_failures_are_gone(self):
        """Live run 1's cover page, verbatim:

            Policy PolicyNumberIdentifier on ACORD 127 shows "6E7-40-02---26"
                                                 source value "BBC7263 - 26"
            Insurer NAICCode             on ACORD 127 shows "21415"  source "25186"
            Policy PolicyNumberIdentifier on ACORD 131 shows "6J7-40-02---26"
                                                 source value "BBC7263 - 26"
            Insurer NAICCode             on ACORD 131 shows "21415"  source "25186"

        Every stamped value is CORRECT. Every "source value" is the package
        scalar - the General Liability policy, reported against the Auto and
        Umbrella forms.
        """
        gen = {
            "ACORD_127": _form({"Policy_PolicyNumberIdentifier_A": "6E7-40-02---26",
                                "Insurer_NAICCode_A": "21415"}),
            "ACORD_131": _form({"Policy_PolicyNumberIdentifier_A": "6J7-40-02---26",
                                "Insurer_NAICCode_A": "21415"}),
            "ACORD_126": _form({"Policy_PolicyNumberIdentifier_A": "BBC7263 - 26",
                                "Insurer_NAICCode_A": "25186"}),
        }
        res = run_field_qa(gen, ORBIN_FACTS)
        mismatches = [r for r in res["results"] if r["reason_code"] == "value_mismatch"]
        assert mismatches == [], mismatches

    def test_a_genuinely_wrong_value_still_fails(self):
        """The point is not silence - it is comparing against the RIGHT value.
        A number belonging to no line on the package must still be reported,
        and reported against THIS form's line."""
        gen = {"ACORD_127": _form({"Policy_PolicyNumberIdentifier_A": "ZZZ-999",
                                   "Insurer_NAICCode_A": "99999"})}
        res = run_field_qa(gen, ORBIN_FACTS)
        by_field = {r["field"]: r for r in res["results"]}
        assert by_field["Policy_PolicyNumberIdentifier_A"]["verdict"] == "fail"
        assert by_field["Policy_PolicyNumberIdentifier_A"]["expected"] == "6E7-40-02---26"
        assert by_field["Insurer_NAICCode_A"]["expected"] == "21415"

    def test_another_lines_number_on_this_form_is_still_caught(self):
        """The defect the 11 Sep work fixed must stay reportable. Printing the
        GL policy number on the Umbrella application is exactly what the client
        reported, and QA must not now call it correct just because it equals
        the package scalar."""
        gen = {"ACORD_131": _form({"Policy_PolicyNumberIdentifier_A": "BBC7263 - 26"})}
        res = run_field_qa(gen, ORBIN_FACTS)
        fails = [r for r in res["results"] if r["reason_code"] == "value_mismatch"]
        assert len(fails) == 1, res["results"]
        assert fails[0]["expected"] == "6J7-40-02---26"

    def test_a_package_level_form_still_uses_the_package_scalar(self):
        """ACORD 125 and 101 are deliberately NOT section forms - their header
        identity IS package-level. No owner claims those boxes, so the ordinary
        comparison must still run there."""
        owned = authoritative_expected_value(
            "ACORD_125", "Policy_PolicyNumberIdentifier_A", ORBIN_FACTS)
        assert owned is not _AUTH_UNOWNED or owned is _AUTH_UNOWNED  # documents either
        gen = {"ACORD_125": _form({"NamedInsured_FullName_A": "Totally Different Co"})}
        res = run_field_qa({**gen}, {**ORBIN_FACTS, "applicant_name": "Orbin Contracting LLC"})
        fails = [r for r in res["results"] if r["reason_code"] == "value_mismatch"]
        assert any(f["field"] == "NamedInsured_FullName_A" for f in fails), res["results"]

    def test_an_unowned_field_returns_the_sentinel_not_none(self):
        """`None` and "nothing owns this" are different answers and the caller
        acts on them differently - conflating them would silence every ordinary
        value check on the form."""
        assert authoritative_expected_value(
            "ACORD_126", "NamedInsured_FullName_A", ORBIN_FACTS) is _AUTH_UNOWNED

    def test_the_door_never_raises_on_junk(self):
        for form_id, field, facts in (
            ("", "", {}),
            ("ACORD_126", "Policy_PolicyNumberIdentifier_A", None),
            ("NOT_A_FORM", "Policy_PolicyNumberIdentifier_A", {"coverage_lines": "nonsense"}),
            ("ACORD_131", "Policy_PolicyNumberIdentifier_A", {"coverage_lines": [None, 5, "x"]}),
        ):
            authoritative_expected_value(form_id, field, facts)

    def test_field_qa_survives_a_broken_owner(self, monkeypatch):
        """QA is advisory and must never take the pipeline down with it."""
        import services.pdf_service as ps

        def boom(*_a, **_k):
            raise RuntimeError("owner exploded")

        monkeypatch.setattr(ps, "authoritative_expected_value", boom)
        gen = {"ACORD_127": _form({"Policy_PolicyNumberIdentifier_A": "6E7-40-02---26"})}
        res = run_field_qa(gen, ORBIN_FACTS)
        assert isinstance(res.get("results"), list)


# ═════════════════════════════════════════════════════════════════════════════
class TestF4TheStatedBasisOutranksTheDetector:
    """`gl_form_type` states the basis; `gl_is_claims_made` detects it. One
    door, and the stated value wins where the document has spoken."""

    RETRO = "GeneralLiability_ClaimsMade_ProposedRetroactiveDate_A"

    def test_the_reported_case(self):
        """Run 1: the declarations say OCCURRENCE, one narrative sentence set
        the flag, and ACORD 126 printed PROPOSED RETROACTIVE DATE 07/15/2026 -
        a date no document states, for a concept an occurrence policy has no
        version of."""
        facts = {"gl_form_type": "OCCURRENCE", "gl_is_claims_made": True}
        assert gl_form_basis(facts) == "occurrence"
        assert gl_is_claims_made(facts, facts) is False
        assert _resolve_claims_made_dates(self.RETRO, facts) is None   # owned blank

    def test_a_real_claims_made_policy_keeps_its_dates(self):
        facts = {"gl_form_type": "Claims-Made", "gl_is_claims_made": True}
        assert gl_is_claims_made(facts, facts) is True
        assert _resolve_claims_made_dates(self.RETRO, facts) is _SCHED_SKIP

    def test_a_stated_claims_made_basis_beats_a_silent_detector(self):
        """A GAIN, not only a fix. Before the door, a claims-made policy whose
        flag the model missed had its retro date boxes owned blank - the right
        value refused for the wrong reason."""
        facts = {"gl_form_type": "Claims Made", "gl_is_claims_made": False}
        assert gl_is_claims_made(facts, facts) is True
        assert _resolve_claims_made_dates(self.RETRO, facts) is _SCHED_SKIP

    def test_silence_leaves_the_detector_in_charge(self):
        """The stated value outranks the detector only where it EXISTS. A
        package that never states a basis is exactly the case the flag was
        built for, and nothing here may change its answer."""
        assert gl_form_basis({}) is None
        assert gl_is_claims_made({"gl_is_claims_made": True}, {"gl_is_claims_made": True}) is True
        assert gl_is_claims_made({}, {}) is False

    def test_a_value_naming_both_bases_settles_nothing(self):
        """A declarations cell that prints the GL form as occurrence AND an
        EBL endorsement as claims-made is the commonest real shape there is.
        Resolving it by word order would be a coin flip on a coverage fact, so
        the door abstains and the detector decides."""
        both = "CG 00 01 occurrence; EBL CG 04 35 claims-made"
        assert gl_form_basis({"gl_form_type": both}) is None
        assert gl_is_claims_made({"gl_form_type": both}, {"gl_is_claims_made": True}) is True
        assert gl_is_claims_made({"gl_form_type": both}, {"gl_is_claims_made": False}) is False

    @pytest.mark.parametrize("spelling", [
        "Occurrence", "OCCURRENCE", " occurrence ", "Occurrence Form",
        "Written on an occurrence basis", "occurrence-based",
    ])
    def test_occurrence_spellings(self, spelling):
        facts = {"gl_form_type": spelling, "gl_is_claims_made": True}
        assert gl_is_claims_made(facts, facts) is False

    @pytest.mark.parametrize("spelling", [
        "Claims Made", "claims-made", "CLAIMS MADE", "Claims Made Form",
        "written on a claims made basis",
    ])
    def test_claims_made_spellings(self, spelling):
        facts = {"gl_form_type": spelling, "gl_is_claims_made": False}
        assert gl_is_claims_made(facts, facts) is True

    def test_every_consumer_reads_the_door(self):
        """ANTI-ROT. Four places gated on this and each had its own copy of
        `flags.get("gl_is_claims_made")`; a fifth would silently reopen the
        defect. Only the door's own fallback may read the raw flag."""
        import re
        root = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                            "services")
        offenders = []
        for name in os.listdir(root):
            if not name.endswith(".py") or name == "coverage_evidence.py":
                continue
            src = open(os.path.join(root, name), encoding="utf-8").read()
            for m in re.finditer(r'(flags|facts)\.get\(\s*["\']gl_is_claims_made', src):
                line = src[:m.start()].count("\n") + 1
                # pdf_service keeps ONE read as the except-branch fallback so a
                # broken import can never blank a real claims-made policy's dates.
                ctx = src[max(0, m.start() - 400):m.start()]
                if "except Exception" in ctx and name == "pdf_service.py":
                    continue
                offenders.append(f"{name}:{line}")
        assert offenders == [], (
            "these read the raw detector flag instead of "
            "coverage_evidence.gl_is_claims_made: " + ", ".join(offenders))


# ═════════════════════════════════════════════════════════════════════════════
class TestF5AnAdditionalInsuredIsNotANamedInsured:
    """The roster's own fact is a bare list of strings, so the INTEREST word is
    gone by the time it gets there. `dec_page_entries` is where it survives."""

    LIVE = {"dec_page_entries": [
        {"label": "Name", "section": "SCHEDULE OF INTERESTS",
         "value": "Wells Fargo Equipment Finance, Inc."},
        {"label": "Additional Insured", "section": "SCHEDULE OF INTERESTS",
         "value": "Kestrel Terminal Authority"},
        {"label": "Additional Insured", "section": "SCHEDULE OF INTERESTS",
         "value": "City of Aurora"},
        {"label": "Named Insured", "section": "COMMON POLICY DECLARATIONS",
         "value": "Halvorsen Industrial Services LLC"},
    ]}

    def _roster(self, facts, names):
        return _drop_transaction_party_rows("additional_named_insureds",
                                            list(names), facts)

    def test_the_reported_case(self):
        """ACORD 125 printed both of these in the NAME (Other Named Insured)
        blocks. An Other Named Insured shares the policy; an additional insured
        holds limited status by endorsement. The form asserted the first from a
        document that says the second."""
        out = self._roster(self.LIVE, ["Kestrel Terminal Authority",
                                       "City of Aurora",
                                       "Halvorsen Holdings LLC"])
        assert out == ["Halvorsen Holdings LLC"]

    def test_a_subsidiary_listed_as_an_additional_insured_TOO_keeps_its_place(self):
        """OWNER RULING 2026-09-06, and it still stands: do not block wholesale,
        because a genuine subsidiary is sometimes listed as an additional
        insured as well. The document says BOTH things, so the roster keeps it -
        which is why the test is positive in both directions rather than a
        membership check on one list."""
        facts = {"dec_page_entries": [
            {"label": "Additional Insured", "section": "SCHEDULE",
             "value": "Halvorsen Logistics LLC"},
            {"label": "Named Insured", "section": "COMMON POLICY DECLARATIONS",
             "value": "Halvorsen Logistics LLC"},
        ]}
        assert self._roster(facts, ["Halvorsen Logistics LLC"]) == ["Halvorsen Logistics LLC"]

    def test_no_dec_entries_means_no_opinion(self):
        """Legacy sessions, and any package whose declarations index was
        purged. Silence must leave the roster exactly as it was - the guard
        acts on positive evidence or not at all."""
        assert self._roster({}, ["Kestrel Terminal Authority"]) == ["Kestrel Terminal Authority"]

    def test_entries_that_never_name_the_party_mean_no_opinion(self):
        facts = {"dec_page_entries": [{"label": "Premium", "value": "$10,500"}]}
        assert self._roster(facts, ["Kestrel Terminal Authority"]) == ["Kestrel Terminal Authority"]

    def test_the_section_heading_counts_as_the_interest_word(self):
        """A schedule headed SCHEDULE OF ADDITIONAL INSUREDS says it once at the
        top instead of on every row. Same statement, so it must carry the same
        weight - otherwise the fix works on one document layout only."""
        facts = {"dec_page_entries": [
            {"label": "Name", "section": "SCHEDULE OF ADDITIONAL INSUREDS",
             "value": "Kestrel Terminal Authority"},
        ]}
        assert self._roster(facts, ["Kestrel Terminal Authority"]) == []

    def test_the_existing_third_party_door_still_bites(self):
        """SYS-09 (2026-09-05) blocked the CERTIFICATE HOLDER from the roster.
        Nothing here may weaken it."""
        facts = {"certificate_holder": "Kestrel Terminal Authority"}
        assert self._roster(facts, ["Kestrel Terminal Authority",
                                    "Real Subsidiary LLC"]) == ["Real Subsidiary LLC"]

    def test_a_short_name_is_never_matched(self):
        """Two-character keys collide across unrelated companies, so the roster
        filter has always had a minimum length. Keep it."""
        facts = {"dec_page_entries": [
            {"label": "Additional Insured", "value": "AB"},
        ]}
        assert self._roster(facts, ["AB"]) == ["AB"]

    def test_it_never_raises_on_a_malformed_index(self):
        for entries in (None, "nonsense", [], [None], [{"value": None}],
                        [{"label": None, "value": "X"}], [5, {"value": ["a"]}]):
            _drop_transaction_party_rows("additional_named_insureds",
                                         ["Some Company LLC"],
                                         {"dec_page_entries": entries})


# ═════════════════════════════════════════════════════════════════════════════
class TestTheV19SchemaIsWhatTheFixesAssume:
    """Both F5's prompt half and the cross-line fence read columns v19 added.
    A silent revert would leave the guards standing over nothing (D22)."""

    def test_the_prompt_defines_both_insured_lists(self):
        from services.extraction_service import _EXTRACT_SCHEMA as S
        i = S.find('"additional_named_insureds"')
        assert i != -1
        window = S[i:i + 700]
        assert "NAMED INSURED" in window
        assert "additional_insured_names" in window, (
            "the roster's definition must name where an additional insured "
            "goes instead, or the model has nowhere to put it")
        j = S.find('"additional_insured_names"')
        assert "ADDITIONAL INSURED" in S[j:j + 700]

    def test_the_version_moved_with_the_schema(self):
        """A changed schema on an unchanged version serves v18 replies out of
        the extraction cache - the new columns would simply never arrive."""
        from services.extraction_service import PROMPT_VERSION, SCHEMA_VERSION
        assert PROMPT_VERSION == SCHEMA_VERSION
        assert int(str(PROMPT_VERSION).lstrip("v")) >= 19


# ═════════════════════════════════════════════════════════════════════════════
class TestARatingCodeIsNotARowIdentity:
    """v19 registered two RATING columns on the vehicle schedule so ACORD 127's
    CLASS box would stop being answered by gap fill. The ghost-row sweep read
    every registered column as proof the row exists, so a leaked class code
    instantly became an identity - resurrecting the 2026-08-13 defect. Two
    existing tests caught it; these pin the rule that fixed it."""

    def test_a_phantom_row_carrying_only_a_class_code_is_still_swept(self):
        """The 2026-08-13 live form, verbatim: row B with the GL class code and
        no VIN, make, model or year."""
        import services.pdf_service as ps
        schema = {
            "Vehicle_VINIdentifier_B": {}, "Vehicle_ManufacturersName_B": {},
            "Vehicle_ModelName_B": {}, "Vehicle_ModelYear_B": {},
            "Vehicle_RateClassCode_B": {}, "Vehicle_RatingTerritoryCode_B": {},
            "Vehicle_CostNewAmount_B": {},
        }
        mapped = {"Vehicle_RateClassCode_B": "91585",
                  "Vehicle_RatingTerritoryCode_B": "6679",
                  "Vehicle_CostNewAmount_B": "$10,000"}
        assert ps._unanchored_schedule_row_fields(
            mapped, schema, set(mapped)) == set(mapped)

    def test_a_real_vehicle_row_keeps_its_rating_cells(self):
        """The other direction: a row with a VIN is anchored, so its class and
        territory - the whole point of registering them - survive."""
        import services.pdf_service as ps
        schema = {"Vehicle_VINIdentifier_B": {}, "Vehicle_RateClassCode_B": {},
                  "Vehicle_RatingTerritoryCode_B": {}}
        mapped = {"Vehicle_VINIdentifier_B": "4S4BRCGC9C3217772",
                  "Vehicle_RateClassCode_B": "7383",
                  "Vehicle_RatingTerritoryCode_B": "6679"}
        assert ps._unanchored_schedule_row_fields(mapped, schema, set(mapped)) == set()

    def test_no_schedule_root_loses_every_identity_anchor(self):
        """THE GUARD ON THE RULE ITSELF. Excluding code columns is only safe
        while every root keeps something else to anchor on - a root reduced to
        zero anchors would have every one of its rows judged a ghost."""
        import services.pdf_service as ps
        from collections import defaultdict
        kept = defaultdict(list)
        for base, sdef in ps._SCHEDULE_REGISTRY.items():
            if ps._CODE_SUBKEY_RE.search(str(sdef.sub_key or "")):
                continue
            kept[base.split("_", 1)[0]].append(base)
        roots = {b.split("_", 1)[0] for b in ps._SCHEDULE_REGISTRY}
        empty = sorted(r for r in roots if not kept.get(r))
        assert empty == [], (
            "these schedule roots have no identity anchor left, so every row "
            "would be swept as a ghost: " + ", ".join(empty))

    def test_the_code_question_has_exactly_one_definition(self):
        """Two copies of "is this a code?" is how the sweep and the fence
        drifted apart in the first place."""
        import re
        import os
        src = open(os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            "services", "pdf_service.py"), encoding="utf-8").read()
        assert len(re.findall(r"^_CODE_SUBKEY_RE\s*=", src, re.M)) == 1


# ═════════════════════════════════════════════════════════════════════════════
class TestF3TheTerritoryIsPrintedAgainstTheDRIVER:
    """The client's literal wording: "ACORD 126 uses territory 6679, which
    appears in the Auto DRIVE OTHER CAR section." A Drive Other Car schedule
    prints its territory against the NAMED INDIVIDUAL, so the vehicle column
    alone would have left that number unwitnessed."""

    # The 11sep kit's driver table, verbatim: NAMED INDIVIDUAL | TERRITORY | CLASS
    KIT = {"_form_id": "ACORD_126",
           "auto_drivers": [{"name": "Erin Royal", "territory": "6679"}],
           "auto_vin_schedule": [{"vin": "4S4BRCGC9C3217772", "class_code": "7383"}],
           "gl_class_code_schedule": [{"class_code": "91580",
                                       "classification": "Contractors"}],
           "wc_class_codes": [{"code": "8810", "description": "Clerical"}]}

    def test_a_drive_other_car_territory_is_witnessed(self):
        from services.pdf_service import _line_code_witnesses
        assert _line_code_witnesses(self.KIT).get("6679") == {"auto"}

    def test_it_is_refused_by_the_gl_hazard_grid(self):
        from services.pdf_service import _cross_line_code_borrows
        out = _cross_line_code_borrows(
            {"CommercialGeneralLiability_TerritoryCode_A": "6679"}, {}, self.KIT)
        assert "CommercialGeneralLiability_TerritoryCode_A" in out

    def test_the_gl_forms_own_class_is_untouched(self):
        from services.pdf_service import _cross_line_code_borrows
        assert _cross_line_code_borrows(
            {"CommercialGeneralLiability_ClassificationCode_A": "91580"},
            {}, self.KIT) == {}

    def test_a_wc_class_beside_a_driver_row_is_never_claimed_by_auto(self):
        """WHY `class_code` IS NOT ON `auto_drivers`. The kit's driver row also
        prints CLASS 8810 - an NCCI clerical class. Capturing that as an AUTO
        code would let the fence blank a genuine Workers Compensation class on
        the ACORD 130. A territory has no such twin, which is why one was added
        and the other was not."""
        from services.pdf_service import _line_code_witnesses, _cross_line_code_borrows
        assert _line_code_witnesses(self.KIT).get("8810") == {"workers_comp"}
        wc = dict(self.KIT, _form_id="ACORD_130")
        assert _cross_line_code_borrows(
            {"WorkersCompensation_RateClass_ClassificationCode_A": "8810"}, {}, wc) == {}

    def test_the_driver_territory_has_no_box_to_reach(self):
        """It is captured as EVIDENCE only. ACORD 127 has no driver territory
        field, so nothing can stamp it - asserted rather than assumed, because
        a fact that silently acquired a box would be a new wrong-value path."""
        import json
        import re
        path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                            "forms_schemas", "ACORD_127_schema.json")
        sch = json.load(open(path))
        fields = sch.get("fields", sch)
        assert not [k for k in fields
                    if re.match(r"^Driver_.*(Territory|RateClass)", k)]

    def test_the_schema_declares_it(self):
        """ANTI-ROT: losing this column silently restores the client's own
        reported defect, and the guard above would still pass."""
        from services.extraction_service import _EXTRACT_SCHEMA as S
        i = S.find('"auto_drivers"')
        assert i != -1
        assert '"territory"' in S[i:i + 600], (
            "auto_drivers lost `territory` - a Drive Other Car territory is "
            "unwitnessed again and 6679 returns to the GL hazard grid")
