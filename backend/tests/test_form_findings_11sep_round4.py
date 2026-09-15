"""Live run 3 findings N1 + N2 - fixed 11 Sep 2026.

ONE rule, two faces:

    A box that asserts a RELATIONSHIP to a named party must agree with the role
    the package states for that party.

  N1  `Kestrel Terminal Authority` - an ADDITIONAL INSURED - was ticked LOSS
      PAYEE on ACORD 127's additional-interest row. The ROW was right (R5 had
      moved it there); the TICK was not.
  N2  the same party printed on ACORD 126 as the company the applicant LEASES
      EMPLOYEES TO. Not a scope failure - that box IS a party box. The role
      words are singular STEMS harvested from field names ("employee",
      "lease") and ACORD's prose is INFLECTED ("employees", "leased"), so
      exact matching found nothing and the box asserted no role at all.
"""
import os
import random
import re
import sys

import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import services.pdf_service as ps
from services.extraction_service import stated_party_roles, _identity_name_key

FACTS = {
    "loss_payee_name": "Wells Fargo Equipment Finance, Inc.",
    "mortgagee_name": "John A. Smith",
    "risk_transfer": {
        "loss_payee_name": "Wells Fargo Equipment Finance, Inc.",
        "mortgagee_name": "John A. Smith",
        "additional_insured_names": ["Kestrel Terminal Authority", "City of Aurora"],
    },
}


def _ticks(form_id):
    return [k for k in ps._all_form_schemas()[form_id] if ps._INTEREST_TICK_RE.match(k)]


def _set(form_id, **overrides):
    m = {k: None for k in _ticks(form_id)}
    m.update(overrides)
    return m


def _on(mapped):
    return sorted(k.split("_Interest_")[-1] for k in mapped
                  if ps._INTEREST_TICK_RE.match(k or "") and str(mapped.get(k) or "").strip())


# ═════════════════════════════════════════════════════════════════════════════
class TestN2TheRoleWordsAreStems:
    """The guard was in scope and still inert."""

    def setup_method(self):
        ps._set_schema_context(ps._all_form_schemas()["ACORD_126"])

    def teardown_method(self):
        ps._set_schema_context(None)

    def test_the_employee_lease_box_IS_a_party_box(self):
        """Which is why "widen the scope" was the wrong diagnosis."""
        assert ps._is_party_name_box("AdditionalInterest_FullName_B") is True

    def test_it_now_asserts_the_role_its_clause_names(self):
        """Clause: "this is the company to whom employees are leased". The
        roles are `employee` and `lease`; the prose is `employees` and
        `leased`. Exact matching returned nothing."""
        assert ps._roles_a_box_asserts("AdditionalInterest_FullName_B") == {"employee", "lease"}

    def test_the_reported_case(self):
        out = ps._party_in_the_wrong_role_box(
            {"AdditionalInterest_FullName_B": "Kestrel Terminal Authority"},
            dict(FACTS, _form_id="ACORD_126"))
        assert "AdditionalInterest_FullName_B" in out

    def test_a_generic_interest_row_still_asserts_nothing(self):
        assert ps._roles_a_box_asserts("AdditionalInterest_FullName_A") == set()

    def test_a_party_with_no_stated_role_keeps_the_lease_box(self):
        assert ps._party_in_the_wrong_role_box(
            {"AdditionalInterest_FullName_B": "Some Staffing Company LLC"},
            dict(FACTS, _form_id="ACORD_126")) == {}

    def test_CONTRACTOR_does_not_assert_ContractOfSale(self):
        """THE REASON THE SUFFIX LIST IS WHAT IT IS. "contractor" is
        "contract" + "or", and a fuzzy stem match would have made every
        contractor clause assert the ContractOfSale interest. `or` is absent
        from the inflection set by construction."""
        roles = set(ps._acord_interest_roles())
        assert "contract" in roles
        for word in ("contractor", "contractors", "contractual"):
            matched = {r for r in roles
                       if re.search(rf"\b{re.escape(r)}(?:s|es|d|ed|ing)?\b", word)}
            assert "contract" not in matched, word
        # HONEST LIMIT: "contracting" IS contract + ing and does match. No real
        # box hits it - the measured blast radius is 8 employee-leasing boxes
        # and nothing else - and dropping "ing" would also lose "leased",
        # which is the inflection this fix exists for.

    def test_the_change_is_measured_not_assumed(self):
        """8 of the 13 party boxes carrying an "As used here" clause changed,
        every one an employee-leasing box on ACORD 126 or 160 that previously
        asserted nothing. NO box lost a role it already had."""
        S = ps._all_form_schemas()
        gained = lost = 0
        for fid, sch in S.items():
            ps._set_schema_context(sch)
            for k in sch:
                if not ps._is_party_name_box(k):
                    continue
                tu = str((sch[k] or {}).get("tu") or "").lower()
                if ps._PARTY_ROW_MARKER not in tu:
                    continue
                clause = tu.split(ps._PARTY_ROW_MARKER, 1)[1]
                old = {r for r in ps._acord_interest_roles()
                       if r in set(re.findall(r"[a-z]+", clause))} - {"other"}
                new = ps._roles_a_box_asserts(k)
                gained += len(new - old) > 0
                lost += len(old - new) > 0
        assert lost == 0, "a box lost a role it used to assert"
        assert gained >= 8


# ═════════════════════════════════════════════════════════════════════════════
class TestN1TheTickMustAgreeWithItsRow:
    """The role is in ACORD's own field name, on every row."""

    def setup_method(self):
        ps._set_schema_context(ps._all_form_schemas()["ACORD_127"])

    def teardown_method(self):
        ps._set_schema_context(None)

    def test_the_reported_case(self):
        """Run 3: both interest rows ticked LOSS PAYEE. Row A is a real loss
        payee; row B is an additional insured."""
        m = _set("ACORD_127",
                 **{"AdditionalInterest_FullName_A": "Wells Fargo Equipment Finance, Inc.",
                    "AdditionalInterest_Interest_LossPayeeIndicator_A": "Yes",
                    "AdditionalInterest_FullName_B": "Kestrel Terminal Authority",
                    "AdditionalInterest_Interest_LossPayeeIndicator_B": "Yes"})
        ps._interest_tick_contradicts_its_party(m, dict(FACTS, _form_id="ACORD_127"))
        assert _on(m) == ["AdditionalInsuredIndicator_B", "LossPayeeIndicator_A"]

    def test_it_works_on_rows_past_A(self):
        """`_resolve_additional_interest_type` owns row A only, which is why
        row B inherited the tick above it."""
        assert not [k for k in _ticks("ACORD_127") if "Mortgagee" in k], (
            "ACORD 127 prints no mortgagee box - AdditionalInsured / "
            "EmployeeAsLessor / LendersLossPayable / Lienholder / LossPayee / "
            "Other / Owner / Registrant is the whole set")
        m = _set("ACORD_127",
                 **{"AdditionalInterest_FullName_B": "John A. Smith",
                    "AdditionalInterest_Interest_LossPayeeIndicator_B": "Yes"})
        ps._interest_tick_contradicts_its_party(m, dict(FACTS, _form_id="ACORD_127"))
        assert _on(m) == []

    def test_a_form_that_HAS_the_role_box_gets_it_ticked(self):
        """ACORD 125 does print a mortgagee box, so the same party is ticked
        there - which proves the row-B fix fills as well as deletes."""
        assert [k for k in _ticks("ACORD_125") if "Mortgagee" in k]
        ps._set_schema_context(ps._all_form_schemas()["ACORD_125"])
        m = _set("ACORD_125", **{"AdditionalInterest_FullName_A": "John A. Smith"})
        ps._interest_tick_contradicts_its_party(m, dict(FACTS, _form_id="ACORD_125"))
        assert _on(m) == ["MortgageeIndicator_A"]

    def test_a_correct_tick_is_never_removed(self):
        m = _set("ACORD_127",
                 **{"AdditionalInterest_FullName_A": "Wells Fargo Equipment Finance, Inc.",
                    "AdditionalInterest_Interest_LossPayeeIndicator_A": "Yes"})
        ps._interest_tick_contradicts_its_party(m, dict(FACTS, _form_id="ACORD_127"))
        assert _on(m) == ["LossPayeeIndicator_A"]

    def test_a_row_the_producer_already_marked_is_untouched(self):
        m = _set("ACORD_127",
                 **{"AdditionalInterest_FullName_B": "Kestrel Terminal Authority",
                    "AdditionalInterest_Interest_AdditionalInsuredIndicator_B": "Yes"})
        ps._interest_tick_contradicts_its_party(m, dict(FACTS, _form_id="ACORD_127"))
        assert _on(m) == ["AdditionalInsuredIndicator_B"]

    def test_a_row_marked_OTHER_is_a_CLAIMED_row(self):
        """FOUND BY THE FUZZ, 184 times. `Interest_OtherIndicator` resolves to
        {other}, which is stripped as a catch-all rather than a relationship -
        so a row the document had already marked OTHER was not counted as
        claimed and pass 2 added a SECOND tick beside it."""
        m = _set("ACORD_127",
                 **{"AdditionalInterest_FullName_A": "Kestrel Terminal Authority",
                    "AdditionalInterest_Interest_OtherIndicator_A": "Yes"})
        ps._interest_tick_contradicts_its_party(m, dict(FACTS, _form_id="ACORD_127"))
        assert _on(m) == ["OtherIndicator_A"]

    def test_a_party_with_no_stated_role_is_never_ticked(self):
        m = _set("ACORD_127",
                 **{"AdditionalInterest_FullName_A": "Some Company Nobody Mentioned LLC"})
        ps._interest_tick_contradicts_its_party(m, dict(FACTS, _form_id="ACORD_127"))
        assert _on(m) == []

    def test_TICKING_needs_containment_not_overlap(self):
        """MEASURED. A loss payee's roles are {loss, payee}.
        `LendersLossPayable` asserts {lenders, loss, payable} and shares
        "loss", so overlap alone ticked LENDER'S LOSS PAYABLE on Wells Fargo -
        a different interest type - purely because it sorts first."""
        m = _set("ACORD_127",
                 **{"AdditionalInterest_FullName_A": "Wells Fargo Equipment Finance, Inc."})
        ps._interest_tick_contradicts_its_party(m, dict(FACTS, _form_id="ACORD_127"))
        assert _on(m) == ["LossPayeeIndicator_A"]

    def test_blanking_is_LOOSER_than_ticking_and_that_is_deliberate(self):
        """Pass 1 withholds only on ZERO overlap - a tick the document merely
        does not contradict is left alone. `LendersLossPayable` on a loss payee
        is close enough to keep, and not close enough to assert."""
        m = _set("ACORD_127",
                 **{"AdditionalInterest_FullName_A": "Wells Fargo Equipment Finance, Inc.",
                    "AdditionalInterest_Interest_LendersLossPayableIndicator_A": "Yes"})
        ps._interest_tick_contradicts_its_party(m, dict(FACTS, _form_id="ACORD_127"))
        assert _on(m) == ["LendersLossPayableIndicator_A"]

    def test_it_is_ORDER_INDEPENDENT(self):
        """The first cut had ONE pass, so a tick was evaluated while the
        sibling contradicting it was still set: nothing was ever ticked, and
        the result depended on dict order."""
        seed = {"AdditionalInterest_FullName_A": "Wells Fargo Equipment Finance, Inc.",
                "AdditionalInterest_Interest_LossPayeeIndicator_A": "Yes",
                "AdditionalInterest_FullName_B": "Kestrel Terminal Authority",
                "AdditionalInterest_Interest_LossPayeeIndicator_B": "Yes"}
        expected = None
        rng = random.Random(7)
        for _ in range(12):
            keys = _ticks("ACORD_127")
            rng.shuffle(keys)
            m = {k: None for k in keys}
            m.update(seed)
            ps._interest_tick_contradicts_its_party(m, dict(FACTS, _form_id="ACORD_127"))
            got = _on(m)
            expected = got if expected is None else expected
            assert got == expected, got

    def test_no_row_ever_ends_with_two_ticks(self):
        m = _set("ACORD_127",
                 **{"AdditionalInterest_FullName_A": "Wells Fargo Equipment Finance, Inc.",
                    "AdditionalInterest_FullName_B": "Kestrel Terminal Authority"})
        ps._interest_tick_contradicts_its_party(m, dict(FACTS, _form_id="ACORD_127"))
        per_row = {}
        for k in m:
            mm = ps._INTEREST_TICK_RE.match(k or "")
            if mm and str(m.get(k) or "").strip():
                per_row[mm.group(3)] = per_row.get(mm.group(3), 0) + 1
        assert all(n == 1 for n in per_row.values()), per_row

    def test_it_never_raises(self):
        for facts in ({}, None, {"risk_transfer": "x"}, {"loss_payee_name": []},
                      {"dec_page_entries": 5}):
            ps._interest_tick_contradicts_its_party(
                _set("ACORD_127", **{"AdditionalInterest_FullName_A": "X LLC"}), facts)
        for mapped in ({}, {"AdditionalInterest_FullName_A": None},
                       {"AdditionalInterest_Interest_LossPayeeIndicator_A": 5}):
            ps._interest_tick_contradicts_its_party(dict(mapped), dict(FACTS))

    def test_the_roles_come_from_ACORDs_own_field_names(self):
        """ANTI-ROT, and the reason this is not a curated table:
        `_INTEREST_TYPE_FACTS` knew exactly two roles, which is why ADDITIONAL
        INSURED could never be ticked by anything."""
        roles = set(ps._acord_interest_roles())
        for expected in ("insured", "mortgagee", "lienholder", "payee", "trustee",
                         "registrant", "owner"):
            assert expected in roles, expected
        assert len(ps._INTEREST_TYPE_FACTS) == 2, (
            "if this grows, check whether the tick guard still needs to carry it")


# ═════════════════════════════════════════════════════════════════════════════
class TestTheFuzzInvariants:
    """A compact re-run of the 8,000-case adversarial sweep, so the invariants
    live in the build rather than in a scratch file."""

    ROLE_KEYS = ["loss_payee_name", "mortgagee_name", "certificate_holder",
                 "additional_insured_names", "lienholder_name", "trustee_name"]

    def test_invariants_hold_over_600_random_packages(self):
        rng = random.Random(31337)
        S = ps._all_form_schemas()
        forms = [f for f in S if any(ps._INTEREST_TICK_RE.match(k) for k in S[f])]
        known = set(ps._acord_interest_roles())
        for _ in range(600):
            fid = rng.choice(forms)
            ps._set_schema_context(S[fid])
            ticks = [k for k in S[fid] if ps._INTEREST_TICK_RE.match(k)]
            names = [k for k in S[fid] if ps._INTEREST_NAME_ROW_RE.match(k)]
            if not ticks or not names:
                continue
            who = f"Party {rng.randint(1, 40)} LLC"
            key = rng.choice(self.ROLE_KEYS)
            facts = {"_form_id": fid,
                     "risk_transfer": {key: [who] if key.endswith("names") else who}}
            m = {k: None for k in ticks}
            m[rng.choice(names)] = rng.choice([who, "Unrelated Co LLC", None])
            for t in ticks:
                if rng.random() < .25:
                    m[t] = "Yes"
            before = dict(m)
            ps._interest_tick_contradicts_its_party(m, facts)

            roles_by_party = stated_party_roles(facts)
            row_roles = {}
            for nf in names:
                mm = ps._INTEREST_NAME_ROW_RE.match(nf)
                v = str(m.get(nf) or "").strip()
                if v:
                    r = (roles_by_party.get(_identity_name_key(v)) or set()) & known
                    if r:
                        row_roles[mm.group(2)] = r
            per_row = {}
            for t in ticks:
                mm = ps._INTEREST_TICK_RE.match(t)
                row = mm.group(3)
                asserts = ({w.lower() for w in re.findall(r"[A-Z][a-z]+", mm.group(2))}
                           & known) - {"other"}
                b = bool(str(before.get(t) or "").strip())
                a = bool(str(m.get(t) or "").strip())
                if a:
                    per_row[row] = per_row.get(row, 0) + 1
                stated = row_roles.get(row)
                if b and not a:
                    assert stated and not (asserts & stated), f"{fid} {t} wrongly removed"
                if a and not b:
                    assert stated, f"{fid} {t} ticked with no stated role"
                    assert (asserts == stated or asserts <= stated
                            or stated <= asserts), f"{fid} {t} ticked on partial overlap"
            # Only a row this guard actually WROTE to must end with one tick.
            # The fuzz seeds several ticks on one row at random and the guard
            # leaves the ones it cannot judge alone - counting those was the
            # test being wrong, not the code.
            for row, n in per_row.items():
                wrote = any(str(m.get(t) or "").strip()
                            and not str(before.get(t) or "").strip()
                            and ps._INTEREST_TICK_RE.match(t).group(3) == row
                            for t in ticks)
                if wrote:
                    assert n == 1, f"{fid} row {row} ends with {n} ticks after a SET"
        ps._set_schema_context(None)
