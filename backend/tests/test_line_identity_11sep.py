"""Line identity: grant evidence vs identity evidence vs line presence.

Client audit 2026-09-11 (Orbin), items 1 / 3 / 5. Three different questions were
being answered by one or two tests:

    "does this package HAVE this coverage?"   -> _line_entry_grants_coverage
    "which policy IS this coverage line?"     -> _line_entry_identifies_policy
    "is this form's line present at all?"     -> the `matched` list

Conflating the first two switched every per-line stamping resolver off on any
package whose declarations print ONE combined premium - and the extraction
prompt asks for exactly that. Conflating the second two (the first cut of the
fix) then blanked a number a single-policy package should inherit.

The tests are written as INVARIANTS over generated data, not as examples,
because the defect is triggered by data SHAPE and is identical for every value.
"""

import random

import pytest

from services.extraction_service import (
    _drop_form_numbers_from_policy_facts,
    _is_policy_number_fact,
    _line_entry_grants_coverage,
    _line_entry_identifies_policy,
    _looks_like_a_form_number,
)
from services.lob_canon import canon_line
from services.pdf_service import (
    _SCHED_SKIP,
    _SECTION_FORM_LINE_PHRASES,
    _deterministic_map,
    _is_policy_number_box,
    _resolve_section_policy_identity,
    _section_line_names_this_form,
    _lob_tokens,
)

GL = {"line": "General Liability", "carrier": "EMC Property & Casualty",
      "naic": "25186", "policy_number": "BBC7263 - 26"}
AUTO = {"line": "Business Auto", "carrier": "Employers Mutual Casualty",
        "naic": "21415", "policy_number": "6E7-40-02---26"}
IM = {"line": "Inland Marine", "carrier": "Employers Mutual Casualty",
      "naic": "21415", "policy_number": "6C7-40-02---26"}
UMB = {"line": "Commercial Liability Umbrella", "carrier": "Employers Mutual Casualty",
       "naic": "21415", "policy_number": "6J7-40-02---26"}


def _stamp(field, lines, form_id="ACORD_126", **scalars):
    facts = {"_form_id": form_id, "coverage_lines": lines}
    facts.update(scalars)
    return _deterministic_map(field, facts)


# ─────────────────────────────────────────────────────────────────────────────
# THE REPORTED DEFECT
# ─────────────────────────────────────────────────────────────────────────────
class TestPerfectDataWithNoPremium:
    """The client's package, reduced to its shape: everything correct except
    that no coverage line carries a premium."""

    LINES = [GL, AUTO, IM, UMB]

    def test_no_row_grants_but_every_row_identifies(self):
        assert [_line_entry_grants_coverage(e) for e in self.LINES] == [False] * 4
        assert [_line_entry_identifies_policy(e) for e in self.LINES] == [True] * 4

    def test_the_gl_form_gets_its_own_carrier_naic_and_number(self):
        scal = {"carrier_name": "Employers Mutual Casualty",
                "carrier_naic": "25186", "policy_number": "IM 7100 06 04"}
        assert _stamp("Insurer_FullName_A", self.LINES, **scal) == "EMC Property & Casualty"
        assert _stamp("Insurer_NAICCode_A", self.LINES, **scal) == "25186"
        assert _stamp("Policy_PolicyNumberIdentifier_A", self.LINES,
                      **scal) == "BBC7263 - 26"

    @pytest.mark.parametrize("form_id,expected", [
        ("ACORD_126", "BBC7263 - 26"),
        ("ACORD_127", "6E7-40-02---26"),
        ("ACORD_131", "6J7-40-02---26"),
    ])
    def test_each_section_form_gets_its_own_line(self, form_id, expected):
        assert _stamp("Policy_PolicyNumberIdentifier_A", self.LINES,
                      form_id=form_id) == expected


# ─────────────────────────────────────────────────────────────────────────────
# THE GRANT TEST MUST NOT HAVE MOVED
# ─────────────────────────────────────────────────────────────────────────────
class TestGrantTestUnchanged:
    """Coverage-flag downgrades and the ACORD 125 line-of-business checkboxes
    still demand money. Widening THAT would tick boxes for mentioned lines."""

    def test_money_is_still_required_for_a_grant(self):
        assert _line_entry_grants_coverage({"line": "Property", "premium": "$500"})
        assert not _line_entry_grants_coverage(
            {"line": "Property", "carrier": "X", "naic": "12345",
             "policy_number": "P1"})

    def test_a_denial_is_still_not_a_grant(self):
        assert not _line_entry_grants_coverage(
            {"line": "Crime", "premium": "No Coverage"})


# ─────────────────────────────────────────────────────────────────────────────
# IDENTITY EVIDENCE
# ─────────────────────────────────────────────────────────────────────────────
class TestIdentityEvidence:

    @pytest.mark.parametrize("entry,expected", [
        ({"line": "GL", "carrier": "Acme"}, True),
        ({"line": "GL", "naic": "25186"}, True),
        ({"line": "GL", "policy_number": "P1"}, True),
        ({"line": "GL"}, False),                       # a name alone is a mention
        ({"line": "GL", "premium": "$1"}, False),      # money is not identity
        ({"line": "GL", "policy_number": "IM 7100 06 04"}, False),   # form number
        ({"line": "Crime", "carrier": "No Coverage"}, False),
        ({"line": "Property", "carrier": "X", "premium": "No Coverage"}, False),
        ({"line": "GL", "carrier": "n/a", "policy_number": "P1"}, True),
        (None, False), ("junk", False), ({}, False), (42, False),
    ])
    def test_identity_predicate(self, entry, expected):
        assert _line_entry_identifies_policy(entry) is expected

    def test_a_carrier_block_mis_shaped_as_a_line_is_not_a_line(self):
        assert not _line_entry_identifies_policy(
            {"line": "EMC Property & Casualty Company", "carrier": "EMC P&C"})


# ─────────────────────────────────────────────────────────────────────────────
# CARRIER / NAIC PAIRING
# ─────────────────────────────────────────────────────────────────────────────
class TestCarrierPair:

    def test_a_form_never_borrows_another_lines_carrier(self):
        # ACORD 126 on a package that carries no GL line at all.
        assert _stamp("Insurer_FullName_A", [AUTO]) is None
        assert _stamp("Insurer_NAICCode_A", [AUTO]) is None

    def test_two_carriers_and_a_silent_line_is_blank_not_a_guess(self):
        lines = [dict(GL, carrier=None), AUTO]
        assert _stamp("Insurer_FullName_A", lines) is None

    def test_a_borrowed_pair_may_not_contradict_this_lines_own_naic(self):
        # GL row states NAIC 11111; the package carrier is attested with 22222.
        lines = [{"line": "General Liability", "naic": "11111"},
                 {"line": "Business Auto", "carrier": "Solo Ins", "naic": "22222"}]
        assert _stamp("Insurer_FullName_A", lines) is None

    def test_a_genuine_single_carrier_package_still_fills(self):
        lines = [{"line": "General Liability", "policy_number": "G1"},
                 {"line": "Business Auto", "carrier": "Solo Ins", "naic": "22222",
                  "policy_number": "A1"}]
        assert _stamp("Insurer_FullName_A", lines) == "Solo Ins"

    def test_one_carrier_printed_two_ways_is_one_carrier(self):
        lines = [{"line": "General Liability", "carrier": "Acme Ins Co",
                  "naic": "25186", "policy_number": "G1"},
                 {"line": "General Liability", "carrier": "ACME INSURANCE COMPANY",
                  "naic": "25186", "policy_number": "G1"}]
        assert _stamp("Insurer_FullName_A", lines) == "ACME INSURANCE COMPANY"

    def test_two_real_carriers_never_fold(self):
        lines = [{"line": "General Liability", "carrier": "EMC Property & Casualty",
                  "naic": "25186"},
                 {"line": "General Liability", "carrier": "Employers Mutual Casualty",
                  "naic": "21415"}]
        assert _stamp("Insurer_FullName_A", lines) is None


# ─────────────────────────────────────────────────────────────────────────────
# ONE LINE-IDENTITY DOOR
# ─────────────────────────────────────────────────────────────────────────────
class TestOneLineDoor:
    """`canon_line` and the section matcher disagreed on 4 of 14 real spellings,
    so the same wording resolved a policy number through the dec index and then
    failed to match the form that needed it."""

    @pytest.mark.parametrize("printed", [
        "General Liability", "COMMERCIAL GENERAL LIABILITY", "CGL", "GL",
        "Liability Coverage Part", "Premises/Operations Liability",
        "GENERAL LIABILITY COVERAGE FORM", "Commercial General Liability Coverage Part",
    ])
    def test_gl_spellings_all_reach_the_gl_form(self, printed):
        phrases = _SECTION_FORM_LINE_PHRASES["ACORD_126"]
        assert _section_line_names_this_form(
            printed, phrases, [_lob_tokens(p) for p in phrases])

    @pytest.mark.parametrize("printed", [
        "Commercial Liability Umbrella", "Employers Liability", "Liquor Liability",
        "Business Auto", "Inland Marine", "Crime",
    ])
    def test_other_lines_still_refused(self, printed):
        phrases = _SECTION_FORM_LINE_PHRASES["ACORD_126"]
        assert not _section_line_names_this_form(
            printed, phrases, [_lob_tokens(p) for p in phrases])

    def test_two_unplaceable_strings_are_not_the_same_line(self):
        # canon_line returns None for both; None must never equal None.
        phrases = ("no such line at all",)
        assert not _section_line_names_this_form(
            "???", phrases, [_lob_tokens(p) for p in phrases])


# ─────────────────────────────────────────────────────────────────────────────
# LINE PRESENCE IS ITS OWN QUESTION
# ─────────────────────────────────────────────────────────────────────────────
class TestLinePresence:

    def test_a_value_less_row_still_proves_its_line_exists(self):
        lines = [{"line": "Umbrella", "premium": "$3,418"},
                 {"line": "Commercial Package", "policy_number": "ONE-1"}]
        assert _stamp("Policy_PolicyNumberIdentifier_A", lines,
                      form_id="ACORD_131") == "ONE-1"

    def test_a_number_owned_by_another_line_is_never_inherited(self):
        lines = [{"line": "Umbrella", "premium": "$3,418"},
                 {"line": "Liability", "policy_number": "ONE-1"}]
        assert _stamp("Policy_PolicyNumberIdentifier_A", lines,
                      form_id="ACORD_131") is None
        assert _stamp("Policy_PolicyNumberIdentifier_A", lines,
                      form_id="ACORD_126") == "ONE-1"

    def test_a_denied_line_is_not_present(self):
        lines = [{"line": "Umbrella", "premium": "No Coverage"},
                 {"line": "Commercial Package", "policy_number": "ONE-1"}]
        assert _stamp("Policy_PolicyNumberIdentifier_A", lines,
                      form_id="ACORD_131") is None


# ─────────────────────────────────────────────────────────────────────────────
# A FORM NUMBER IS NOT A POLICY NUMBER - AT THE SOURCE AND AT THE BOX
# ─────────────────────────────────────────────────────────────────────────────
class TestFormNumbers:

    @pytest.mark.parametrize("key,expected", [
        ("policy_number", True), ("prior_policy_number", True),
        ("expiring_policy_number", True), ("umbrella_policy_no", True),
        ("carrier_name", False), ("policy_premium", False),
        ("num_employees", False), ("policy_number_of_record", False),
    ])
    def test_policy_number_fact_keys_are_derived(self, key, expected):
        assert _is_policy_number_fact(key) is expected

    @pytest.mark.parametrize("raw", ["IM 7100 06 04", "CG 00 01 04 13",
                                     "IL 00 17 11 98", "CA 99 10 03 06"])
    def test_a_form_number_never_survives_the_merge(self, raw):
        mf = {"policy_number": raw}
        assert _drop_form_numbers_from_policy_facts(mf)
        assert mf["policy_number"] == ""

    @pytest.mark.parametrize("raw", ["BBC7263 - 26", "6E7-40-02---26", "POL123",
                                     "6C7-40-02---26", "CPP1234567"])
    def test_a_real_policy_number_is_untouched(self, raw):
        mf = {"policy_number": raw}
        assert not _drop_form_numbers_from_policy_facts(mf)
        assert mf["policy_number"] == raw

    def test_the_fact_envelope_survives(self):
        mf = {"policy_number": {"value": "IM 7100 06 04",
                                "evidence_state": "verified", "source": "d.pdf"}}
        _drop_form_numbers_from_policy_facts(mf)
        assert mf["policy_number"]["value"] == ""
        assert mf["policy_number"]["evidence_state"] == "verified"
        assert mf["policy_number"]["source"] == "d.pdf"

    def test_non_string_values_are_left_alone(self):
        for v in (None, 12345, ["IM 7100 06 04"], {"a": 1}):
            mf = {"policy_number": v}
            _drop_form_numbers_from_policy_facts(mf)
            assert mf["policy_number"] == v

    def test_every_policy_number_box_on_every_form_is_recognised(self):
        import glob
        import json
        import os
        seen = 0
        for path in glob.glob(os.path.join(
                os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                "forms_schemas", "ACORD_*_schema.json")):
            for name in json.load(open(path, encoding="utf-8")):
                if "PolicyNumberIdentifier" in name:
                    assert _is_policy_number_box(name), name
                    seen += 1
                else:
                    assert not _is_policy_number_box(name), name
        assert seen > 40          # 46 across the 17 shipped schemas

    def test_gap_fill_cannot_put_a_form_number_back_into_a_policy_box(self):
        """Clearing the FACT hands the box to gap fill, which reads the raw
        document - where the form number is printed. Guarding only the source
        is how this defect returned the first time."""
        import glob
        import json
        import os
        from services.pdf_service import _enforce_post_fill_guards
        schema_path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            "forms_schemas", "ACORD_125_schema.json")
        schema = json.load(open(schema_path, encoding="utf-8"))
        for bad in ("IM 7100 06 04", "CG 00 01 04 13", "IL 00 17 11 98"):
            mapped = {"Policy_PolicyNumberIdentifier_A": bad,
                      "OtherPolicy_PolicyNumberIdentifier_A": bad}
            _enforce_post_fill_guards(mapped, schema, {},
                                      gpt_filled_set=set(mapped))
            assert mapped["Policy_PolicyNumberIdentifier_A"] is None, bad
            assert mapped["OtherPolicy_PolicyNumberIdentifier_A"] is None, bad
        for good in ("BBC7263 - 26", "6E7-40-02---26", "POL123"):
            mapped = {"Policy_PolicyNumberIdentifier_A": good}
            _enforce_post_fill_guards(mapped, schema, {},
                                      gpt_filled_set=set(mapped))
            assert mapped["Policy_PolicyNumberIdentifier_A"] == good

    def test_the_guard_is_scoped_to_policy_number_boxes_only(self):
        """A form-number-shaped value is legitimate in a form-edition box."""
        from services.pdf_service import _enforce_post_fill_guards
        mapped = {"Policy_FormEditionIdentifier_A": "CG 00 01 04 13"}
        _enforce_post_fill_guards(
            mapped, {"Policy_FormEditionIdentifier_A": {"ft": "/Tx", "tu": ""}},
            {}, gpt_filled_set=set(mapped))
        assert mapped["Policy_FormEditionIdentifier_A"] == "CG 00 01 04 13"

    def test_realistic_policy_numbers_are_not_mistaken_for_form_numbers(self):
        rnd = random.Random(9)
        upper = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
        wrong = []
        for _ in range(2000):
            v = rnd.choice([
                f"{rnd.choice(upper) * 3}{rnd.randint(1000, 9999)}-{rnd.randint(20, 30)}",
                f"CPP{rnd.randint(1000000, 9999999)}",
                f"{rnd.randint(10, 99)}-{rnd.randint(100000, 999999)}-{rnd.randint(10, 99)}",
                f"WC-{rnd.randint(1000, 9999)}-{rnd.randint(1000, 9999)}",
                f"BA {rnd.randint(1000, 9999)} {rnd.randint(1000, 9999)}",
                str(rnd.randint(100000000, 999999999)),
            ])
            if _looks_like_a_form_number(v):
                wrong.append(v)
        assert wrong == []


# ─────────────────────────────────────────────────────────────────────────────
# LEGACY SESSIONS
# ─────────────────────────────────────────────────────────────────────────────
class TestLegacyPreserved:

    @pytest.mark.parametrize("lines", [None, [], ["junk", None, 7], [{}]])
    def test_no_usable_per_line_data_keeps_the_scalar_path(self, lines):
        facts = {"_form_id": "ACORD_126", "coverage_lines": lines,
                 "carrier_name": "Legacy Co", "carrier_naic": "25186"}
        assert _resolve_section_policy_identity(
            "Insurer_FullName_A", facts) is _SCHED_SKIP


# ─────────────────────────────────────────────────────────────────────────────
# THE STANDING GUARD: invariants over generated packages
# ─────────────────────────────────────────────────────────────────────────────
class TestInvariantsOverGeneratedPackages:
    """Every stamped value must be traceable to a row that is allowed to supply
    it. Deterministic seed, so a failure is reproducible."""

    NAMES = ["EMC Property & Casualty", "Employers Mutual Casualty", "XYZ",
             "ACME MUT INS CO", "acme insurance company", "Travelers Indemnity Co.",
             "St. Paul Fire & Marine", "A" * 60, "Q", "  padded  ", None, ""]
    NAICS = ["25186", "21415", "11111", "0000", "999999", "4", "", "abc", None]
    POLS = ["BBC7263 - 26", "6E7-40-02---26", "IM 7100 06 04", "CG 00 01 04 13",
            "POL123", "POL12345", "'; DROP TABLE--", "", "  ", "A1", None, "6E74002"]
    LINES = ["General Liability", "CGL", "GL", "Business Auto", "Commercial Auto",
             "Umbrella", "Excess", "Inland Marine", "Crime", "Workers Compensation",
             "Property", "Cyber", "Contractors Equipment", "Liability Coverage Part",
             "gen liab", "Employers Liability", "Liquor Liability", "", None, "???"]

    def _packages(self, n, seed):
        rnd = random.Random(seed)
        for _ in range(n):
            rows = []
            for _i in range(rnd.choice([1, 1, 2, 3, 4, 5])):
                row = {"line": rnd.choice(self.LINES)}
                for key, pool in (("carrier", self.NAMES), ("naic", self.NAICS),
                                  ("policy_number", self.POLS)):
                    if rnd.random() < 0.75:
                        row[key] = rnd.choice(pool)
                if rnd.random() < 0.4:
                    row["premium"] = rnd.choice(
                        ["$1", "$2,991", None, "No Coverage", "NOT COVERED"])
                rows.append(row)
            if rnd.random() < 0.08:
                rows = rnd.choice([[], None, ["junk", None, 7], [{}]])
            yield rnd.choice(list(_SECTION_FORM_LINE_PHRASES)), rows

    def test_no_fabricated_pair_no_stolen_value_no_form_number(self):
        violations = []
        for form_id, rows in self._packages(1500, seed=11092026):
            facts = {"_form_id": form_id, "coverage_lines": rows,
                     "carrier_name": "PKG SCALAR CO", "carrier_naic": "25186",
                     "policy_number": "SCALARPOL1"}
            name = _resolve_section_policy_identity("Insurer_FullName_A", facts)
            naic = _resolve_section_policy_identity("Insurer_NAICCode_A", facts)
            pol = _resolve_section_policy_identity(
                "Policy_PolicyNumberIdentifier_A", facts)
            real = [r for r in (rows or []) if isinstance(r, dict)]

            if name not in (_SCHED_SKIP, None):
                if name == "PKG SCALAR CO":
                    violations.append(("package scalar leaked as carrier", form_id, rows))
                elif not any(str(r.get("carrier") or "").strip() == name for r in real):
                    violations.append(("carrier from no row", name, form_id, rows))
                if naic not in (_SCHED_SKIP, None) and not any(
                        str(r.get("carrier") or "").strip() == name
                        and str(r.get("naic") or "").strip() == naic for r in real):
                    violations.append(("fabricated pair", (name, naic), form_id, rows))

            if pol not in (_SCHED_SKIP, None):
                if pol == "SCALARPOL1":
                    violations.append(("package scalar leaked as policy", form_id, rows))
                if _looks_like_a_form_number(pol):
                    violations.append(("form number stamped", pol, form_id, rows))
                owners = [r for r in real
                          if str(r.get("policy_number") or "").strip() == pol]
                mine = {canon_line(p) for p in _SECTION_FORM_LINE_PHRASES[form_id]}
                mine.add(None)
                if owners and all(
                        canon_line(str(r.get("line") or "")) not in mine
                        for r in owners):
                    violations.append(("number from another line", pol, form_id, rows))
        assert violations == [], violations[:3]
