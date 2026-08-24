"""V1 plan C1 - Data Consistency, Canonical Facts & Normalization (2026-08-21).

Every fixture below is a case that was REPRODUCED against the shipped code
before the fix (v1-20AUG.md, entries C1-A and C1-B), using the client's
literal values wherever the client supplied them. Each test names the defect
it pins (B1..B8) or the fix it proves (F1..F11).

THE GATES that must never move:
  * the umbrella $3,000,000 vs $1,000,000 conflict survives every rule;
  * a geo fragment that fits TWO street addresses is never merged;
  * two REAL carriers (EMC P&C vs Employers Mutual) still conflict when no
    package index scopes them.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("OPENAI_API_KEY", "sk-offline")

import pytest                                                     # noqa: E402

from services import fact_comparison as fc                        # noqa: E402
from services.fact_comparison import (                            # noqa: E402
    SAME, DIFFERENT, compare, conflict, values_agree, identifiers_match,
    feins_match, PackageContext,
)
from services.lob_canon import canon_line                         # noqa: E402
from services import fact_state as fs                             # noqa: E402

# ── The client's literal address trio (1.6) ──────────────────────────────────
ADDR_A = "4800 Dahlia St # D13, Denver, CO 80216-3121"
ADDR_B = "4800 Dahlia Street D13, Denver, CO 80216"
ADDR_C = "Denver, Colorado"

# Orbin's three real policies (1.2), as the verified dec index records them.
ORBIN_ENTRIES = [
    {"label": "Policy Number", "value": "BBC7263-26", "policy_number": "BBC7263-26",
     "line_of_business": "General Liability"},
    {"label": "Policy Number", "value": "6E7-40-02---26", "policy_number": "6E7-40-02---26",
     "line_of_business": "Commercial Auto"},
    {"label": "Policy Number", "value": "6J7-40-02---26", "policy_number": "6J7-40-02---26",
     "line_of_business": "Commercial Umbrella"},
    {"label": "Carrier", "value": "EMC Property & Casualty Company", "owner": "carrier",
     "policy_number": "BBC7263-26", "line_of_business": "General Liability"},
    {"label": "Carrier", "value": "Employers Mutual Casualty Company", "owner": "carrier",
     "policy_number": "6E7-40-02---26", "line_of_business": "Commercial Auto"},
]


def _doc(doc_type, facts, filename="x.pdf", doc_id=None):
    return {"doc_type": doc_type, "facts": facts, "filename": filename,
            "doc_id": doc_id or filename, "text": "x"}


# ═════════════════════════════════════════════════════════════════════════════
# F2a / B1 - three printings of ONE value are one value (the clique fix)
# ═════════════════════════════════════════════════════════════════════════════

class TestCliqueMerge:
    def test_the_clients_literal_address_trio_is_not_a_conflict(self):
        assert not conflict("mailing_address", [ADDR_A, ADDR_B, ADDR_C])

    def test_order_independent(self):
        import itertools
        for perm in itertools.permutations([ADDR_A, ADDR_B, ADDR_C]):
            assert not conflict("mailing_address", list(perm)), perm

    def test_a_hyphenated_unit_printing_still_folds(self):
        """C1-B FLAG 3: the picker only 'worked' when two printings normalised
        byte-identically. D-13 vs D13 must fold too."""
        assert not conflict("mailing_address",
                            [ADDR_A, "4800 Dahlia St D-13, Denver CO", ADDR_C])

    def test_four_printings_of_one_amount(self):
        assert not conflict("gl_aggregate", [
            "$2,000,000", "2000000", "$2,000,000 General Aggregate", "$ 2,000,000.00"])

    def test_GATE_a_fragment_fitting_two_hosts_is_never_merged(self):
        """The ambiguity guard the clique fix must NOT weaken (D4)."""
        assert conflict("mailing_address", [
            "4800 Dahlia St, Denver, CO 80216", "900 Elm St, Denver, CO 80202", ADDR_C])
        assert fc._fe.equivalent_index("physical_address", [
            "4800 Dahlia St, Denver, CO 80216", "900 Elm St, Denver, CO 80202",
            "Denver, Colorado"]) is None

    def test_GATE_umbrella_conflict_survives(self):
        assert conflict("umbrella_limit", ["$3,000,000", "$1,000,000"])
        assert conflict("umbrella_limit", ["$3,000,000", "$1,000,000", "$3M"])

    def test_a_clique_of_three_names_merges(self):
        assert not conflict("applicant_name", [
            "Orbin Contracting LLC", "ORBIN CONTRACTING, L.L.C.", "Orbin Contract"])

    def test_two_real_entities_plus_one_truncation_still_conflict(self):
        """Truncation joins ONE of the two entities; the other stays rival."""
        assert conflict("carrier_name", [
            "EMC Property & Casualty Company", "Employers Mutual Casualty Company",
            "EMC Property & Casualty"])


class TestAddressNormalizerOrdering:
    """Found 2026-08-21 probing my own C1-C change (v1-20AUG C1-E).

    The unit-join regex ran BEFORE the directional mapping, so "E 9 Mile Rd"
    glued to "e9 mile rd" while "East 9 Mile Rd" stayed "e 9 mile rd" - two
    printings of ONE address became a conflict, the exact defect class this
    item exists to remove. Order is now load-bearing and pinned here."""

    @pytest.mark.parametrize("a,b", [
        ("E 9 Mile Rd", "East 9 Mile Rd"),
        ("N 13th St, Denver CO", "North 13th St, Denver CO"),
        ("S 5th Ave", "South 5th Ave"),
        ("W 42nd St", "West 42nd St"),
        ("NE 5 Hwy", "Northeast 5 Hwy"),
        ("SW 7 Road", "Southwest 7 Road"),
        ("4800 Dahlia St D 13", "4800 Dahlia St D13"),
        ("4800 Dahlia St D-13", "4800 Dahlia St #D13"),
        ("100 Main St Apt 4", "100 Main St Apt4"),
        ("1 Elm St Ste 200", "1 Elm St Ste200"),
    ])
    def test_these_are_one_address(self, a, b):
        from services.normalization import normalize_address
        assert normalize_address(a) == normalize_address(b)
        assert not conflict("mailing_address", [a, b])

    @pytest.mark.parametrize("a,b", [
        ("E 9 Mile Rd", "W 9 Mile Rd"),
        ("N Main St", "S Main St"),
        ("4800 Dahlia St D13", "4800 Dahlia St B5"),
        ("1 Elm St Ste 200", "1 Elm St Ste 300"),
        ("100 Main St", "200 Main St"),
    ])
    def test_these_are_still_different_addresses(self, a, b):
        from services.normalization import normalize_address
        assert normalize_address(a) != normalize_address(b)


# ═════════════════════════════════════════════════════════════════════════════
# F1 - the door itself
# ═════════════════════════════════════════════════════════════════════════════

class TestTheDoor:
    def test_entity_names_group_on_the_strict_key_not_the_coarse_one(self):
        """The coarse carrier normaliser folds EMC P&C into Employers Mutual
        (both -> 'emc'). The door must not group on it."""
        assert conflict("carrier_name",
                        ["EMC Property & Casualty Company", "Employers Mutual Casualty Company"])

    def test_truncation_and_suffix_are_one_entity(self):
        assert values_agree("applicant_name", "Orbin Contracting LLC", "Orbin Contract")
        assert values_agree("carrier_name", "Travelers", "Travelers Indemnity Company")

    def test_llc_vs_inc_is_a_different_entity(self):
        assert conflict("applicant_name", ["Orbin Contracting LLC", "Orbin Contracting Inc"])

    def test_identifiers_are_punctuation_blind(self):
        assert identifiers_match("6E7-40-02---26", "6E7 40 02 26")
        assert identifiers_match("BBC7263-26", "bbc726326")
        assert not identifiers_match("BBC7263-26", "6E7-40-02---26")
        assert not identifiers_match("12", "12"), "a two-character stub proves nothing"

    def test_feins_are_punctuation_blind_and_must_be_complete(self):
        assert feins_match("84-2210987", "842210987")
        assert not feins_match("84-2210987", "12-3456789")
        assert not feins_match("842210", "842210")

    def test_prose_is_incomparable_not_a_conflict(self):
        a = " ".join(["word"] * 40) + " one"
        b = " ".join(["word"] * 40) + " two"
        assert compare("operations_description", [a, b]).verdict == "incomparable"
        assert not conflict("operations_description", [a, b])

    def test_compare_reports_groups_and_representatives(self):
        res = compare("gl_aggregate", ["$2,000,000 General Aggregate", "$2,000,000", "$1,000,000"])
        assert res.verdict == "conflict"
        assert res.distinct == 2
        # bare printing preferred as the representative for money
        assert "$2,000,000" == "$2,000,000 General Aggregate".split(" General")[0]

    def test_failure_is_reported_as_conflict_never_hidden(self, monkeypatch):
        monkeypatch.setattr(fc._fe, "equivalent_index",
                            lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom")))
        res = compare("mailing_address", [ADDR_A, ADDR_C])
        assert res.verdict == "conflict"


# ═════════════════════════════════════════════════════════════════════════════
# F3 / B3 - check_doc_consistency goes through the door on every field
# ═════════════════════════════════════════════════════════════════════════════

class TestCheckDocConsistency:
    def _issues(self, docs):
        from services.sqs_service import check_doc_consistency
        return [i for i in check_doc_consistency(docs, set()) if not i.startswith("[info]")]

    def test_the_clients_address_trio_is_clean_on_the_score_checker_too(self):
        docs = [
            _doc("policy", {"applicant_name": "ORBIN CONTRACTING LLC", "mailing_address": ADDR_A}, "dec.pdf"),
            _doc("coi", {"applicant_name": "Orbin Contracting, LLC", "mailing_address": ADDR_B}, "coi.pdf"),
            _doc("application", {"applicant_name": "Orbin Contract", "mailing_address": ADDR_C}, "app.pdf"),
        ]
        assert self._issues(docs) == []

    def test_a_truncated_applicant_name_is_not_a_hard_stop(self):
        docs = [_doc("policy", {"applicant_name": "Orbin Contracting LLC"}),
                _doc("coi", {"applicant_name": "Orbin Contract"}, "b.pdf")]
        assert not any("name_conflict" in i for i in self._issues(docs))

    def test_a_dba_suffix_is_not_a_hard_stop(self):
        docs = [_doc("policy", {"applicant_name": "Orbin Contracting LLC"}),
                _doc("coi", {"applicant_name": "Orbin Contracting LLC dba Orbin Roofing"}, "b.pdf")]
        assert not any("name_conflict" in i for i in self._issues(docs))

    def test_a_different_entity_IS_a_hard_stop(self):
        docs = [_doc("policy", {"applicant_name": "Orbin Contracting LLC"}),
                _doc("coi", {"applicant_name": "Smith Roofing Inc"}, "b.pdf")]
        assert any("name_conflict" in i for i in self._issues(docs))

    def test_fein_punctuation_is_clean_and_a_real_difference_is_not(self):
        clean = [_doc("policy", {"fein": "84-2210987"}), _doc("coi", {"fein": "842210987"}, "b.pdf")]
        real = [_doc("policy", {"fein": "84-2210987"}), _doc("coi", {"fein": "12-3456789"}, "b.pdf")]
        assert not any("fein_conflict" in i for i in self._issues(clean))
        assert any("fein_conflict" in i for i in self._issues(real))

    def test_picker_and_score_checker_agree(self):
        """C1-A root cause (A): the two surfaces disagreed on the same input."""
        from services.underwriting_consistency import assess_underwriting_consistency
        docs = [
            _doc("policy", {"mailing_address": ADDR_A}, "dec.pdf"),
            _doc("coi", {"mailing_address": ADDR_B}, "coi.pdf"),
            _doc("application", {"mailing_address": ADDR_C}, "app.pdf"),
        ]
        picker = assess_underwriting_consistency(docs, {"mailing_address": ADDR_A})
        assert picker["conflict_count"] == 0
        assert not any("mailing_address" in i for i in self._issues(docs))


# ═════════════════════════════════════════════════════════════════════════════
# F2b - scope BEFORE comparison
# ═════════════════════════════════════════════════════════════════════════════

class TestScopeBeforeCompare:
    def _assess(self, docs, merged):
        from services.underwriting_consistency import assess_underwriting_consistency
        return assess_underwriting_consistency(docs, merged)

    def test_three_policies_are_three_scopes_not_a_conflict(self):
        docs = [_doc("policy", {"policy_number": "BBC7263-26"}, "gl.pdf"),
                _doc("policy", {"policy_number": "6E7-40-02---26"}, "auto.pdf"),
                _doc("policy", {"policy_number": "6J7-40-02---26"}, "umb.pdf")]
        r = self._assess(docs, {"dec_page_entries": ORBIN_ENTRIES})
        assert r["conflict_count"] == 0

    def test_the_two_orbin_carriers_are_retained_under_their_own_policy(self):
        """The Orbin ground truth: EMC P&C issues GL, Employers Mutual issues
        Auto. Two legal entities, one package, NOT a conflict - and neither
        is silently merged into the other (client 1.5 'retain each')."""
        docs = [_doc("policy", {"carrier_name": "EMC Property & Casualty Company"}, "gl.pdf"),
                _doc("policy", {"carrier_name": "Employers Mutual Casualty Company"}, "auto.pdf")]
        r = self._assess(docs, {"dec_page_entries": ORBIN_ENTRIES})
        row = next(f for f in r["fields"] if f["fact_key"] == "carrier_name")
        assert row["status"] == "scoped"
        assert len(row["values"]) == 2
        assert all(v.get("scope") for v in row["values"])
        assert r["conflict_count"] == 0

    def test_GATE_the_umbrella_conflict_survives_a_REAL_package_index(self):
        """LIVE RUN FAILURE 2026-08-21 (v1-20AUG C1-H). The earlier gate test
        used an index where $1,000,000 had NO owner. On the real fixture the dec
        page prints $1,000,000 as the GL Each Occurrence limit, so the
        certificate's umbrella $1,000,000 inherited the GL POLICY'S ownership
        (owners are keyed by the value's own characters) - two disjoint owners,
        scoped, conflict SILENCED. The one conflict the client praised."""
        entries = [
            {"label": "GL Each Occurrence", "value": "$1,000,000",
             "policy_number": "BBC7263-26", "line_of_business": "Commercial General Liability"},
            {"label": "Umbrella Each Occurrence", "value": "$3,000,000",
             "policy_number": "6J7-40-02---26", "line_of_business": "Commercial Liability Umbrella"},
        ]
        docs = [_doc("policy", {"umbrella_limit": "$3,000,000"}, "dec.pdf"),
                _doc("certificate", {"umbrella_limit": "$1,000,000"}, "coi.pdf")]
        row = next(f for f in self._assess(docs, {"dec_page_entries": entries})["fields"]
                   if f["fact_key"] == "umbrella_limit")
        assert row["status"] == "conflict", row["status"]
        assert {v["display"] for v in row["values"]} == {"$3,000,000", "$1,000,000"}

    def test_a_fact_pinned_to_one_line_can_never_be_scoped(self):
        """umbrella_limit IS the umbrella's limit - it cannot have one value per
        policy. C1-C had this rule backwards."""
        from services.underwriting_consistency import (
            LINE_SCOPED_FACT_KEYS, _facts_pinned_to_one_line)
        assert "umbrella_limit" in _facts_pinned_to_one_line()
        assert not (LINE_SCOPED_FACT_KEYS & _facts_pinned_to_one_line())

    def test_no_money_fact_is_line_scoped(self):
        """Owners are keyed by the value's characters, so two facts sharing an
        AMOUNT share an owner. Identifiers/names/dates do not collide that way."""
        from services.underwriting_consistency import LINE_SCOPED_FACT_KEYS
        from services.fact_comparison import _fe as door
        money = {k for k in LINE_SCOPED_FACT_KEYS
                 if door.value_kind(k) == door.KIND_MONEY}
        assert money == set(), money

    def test_owner_split_is_refused_for_single_line_and_money(self):
        from services.fact_equivalence import _owner_split_allowed
        assert not _owner_split_allowed("umbrella_limit")
        assert not _owner_split_allowed("total_revenue")
        assert _owner_split_allowed("policy_number")
        assert _owner_split_allowed("carrier_name")

    def test_GATE_two_real_carriers_still_conflict_without_an_index(self):
        docs = [_doc("policy", {"carrier_name": "EMC Property & Casualty Company"}, "gl.pdf"),
                _doc("policy", {"carrier_name": "Employers Mutual Casualty Company"}, "auto.pdf")]
        r = self._assess(docs, {})
        row = next(f for f in r["fields"] if f["fact_key"] == "carrier_name")
        assert row["status"] == "conflict"

    def test_two_policies_on_the_same_line_are_a_conflict_with_a_reason(self):
        entries = [
            {"label": "Policy Number", "value": "GL-1001", "policy_number": "GL-1001",
             "line_of_business": "General Liability"},
            {"label": "Policy Number", "value": "GL-2002", "policy_number": "GL-2002",
             "line_of_business": "General Liability"},
        ]
        docs = [_doc("policy", {"policy_number": "GL-1001"}, "a.pdf"),
                _doc("policy", {"policy_number": "GL-2002"}, "b.pdf")]
        r = self._assess(docs, {"dec_page_entries": entries})
        row = next(f for f in r["fields"] if f["fact_key"] == "policy_number")
        assert row["status"] == "conflict"
        assert "same coverage line" in (row.get("conflict_reason") or "")

    def test_package_level_identity_is_never_scoped(self):
        """One insured however many policies: FEIN differences stay conflicts."""
        docs = [_doc("policy", {"fein": "84-2210987"}, "gl.pdf"),
                _doc("policy", {"fein": "12-3456789"}, "auto.pdf")]
        r = self._assess(docs, {"dec_page_entries": ORBIN_ENTRIES})
        row = next(f for f in r["fields"] if f["fact_key"] == "fein")
        assert row["status"] == "conflict"

    def test_context_records_contract_lines(self):
        ctx = PackageContext({"dec_page_entries": ORBIN_ENTRIES})
        assert ctx.lines_of_owner("bbc726326") == {"general_liab"}
        assert ctx.lines_of_owner("6e7400226") == {"auto"}
        assert ctx.different_owners("BBC7263-26", "6E7-40-02---26")

    def test_same_line_owners_are_not_proven_different(self):
        ctx = PackageContext({"dec_page_entries": [
            {"label": "Policy Number", "value": "GL-1001", "policy_number": "GL-1001",
             "line_of_business": "General Liability"},
            {"label": "Policy Number", "value": "GL-2002", "policy_number": "GL-2002",
             "line_of_business": "General Liability"},
        ]})
        assert not ctx.different_owners("GL-1001", "GL-2002")


# ═════════════════════════════════════════════════════════════════════════════
# L1 / L3 - DOCUMENT ROLE (client 1.2), from the 2026-08-21 live run
# ═════════════════════════════════════════════════════════════════════════════

class TestDocumentRole:
    """A loss run states the insured and their CLAIMS. Its policy number is the
    policy the claims sat under, its carrier is who ISSUED the run, and its
    dates are the period covered - none of which is the submission's policy."""

    @pytest.mark.parametrize("key,allowed", [
        ("policy_number", False), ("carrier_name", False),
        ("effective_date", False), ("expiration_date", False),
        ("applicant_name", True), ("fein", True), ("mailing_address", True),
    ])
    def test_what_a_loss_run_may_witness(self, key, allowed):
        from services.fact_comparison import document_witnesses
        assert document_witnesses("loss_run", key) is allowed

    @pytest.mark.parametrize("doc_type", ["dec_page", "certificate", "application",
                                          "some_future_type", None, ""])
    def test_every_other_role_witnesses_everything(self, doc_type):
        """FAIL-OPEN: an unknown or new document behaves exactly as today."""
        from services.fact_comparison import document_witnesses
        assert document_witnesses(doc_type, "policy_number") is True

    def test_the_live_run_policy_number_conflict_is_gone(self):
        from services.underwriting_consistency import assess_underwriting_consistency
        docs = [_doc("certificate", {"policy_number": "BBC7263-26"}, "2_certificate.pdf"),
                _doc("loss_run", {"policy_number": "6E7 40 02 26"}, "4_loss_run.pdf")]
        r = assess_underwriting_consistency(docs, {})
        assert not [f for f in r["fields"]
                    if f["fact_key"] == "policy_number" and f["status"] == "conflict"]

    def test_two_REAL_policy_documents_still_conflict(self):
        from services.underwriting_consistency import assess_underwriting_consistency
        docs = [_doc("dec_page", {"policy_number": "GL-1001"}, "a.pdf"),
                _doc("dec_page", {"policy_number": "GL-2002"}, "b.pdf")]
        row = next(f for f in assess_underwriting_consistency(docs, {})["fields"]
                   if f["fact_key"] == "policy_number")
        assert row["status"] == "conflict"


# ═════════════════════════════════════════════════════════════════════════════
# L2 - LOB conflict needs a DENIAL, not a different list (client 1.7)
# ═════════════════════════════════════════════════════════════════════════════

class TestLobNeedsADenial:
    def _warn(self, docs):
        from services.sqs_service import check_doc_consistency
        return [i for i in check_doc_consistency(docs, set())
                if "lines_of_business" in i and i.startswith("[warning]")]

    def test_an_extra_line_is_information_not_a_contradiction(self):
        """LIVE RUN 2026-08-21: the application named Professional Liability -
        a real policy with a different carrier - and the package was called
        inconsistent. Silence is not denial (Principle 3)."""
        docs = [_doc("dec_page", {"lines_of_business": [
                    "Commercial General Liability", "Commercial Automobile Liability",
                    "Commercial Liability Umbrella", "Commercial Inland Marine"]}, "1.pdf"),
                _doc("application", {"lines_of_business": ["Professional Liability"]}, "3.pdf")]
        assert self._warn(docs) == []

    def test_a_certificate_listing_fewer_lines_is_not_a_contradiction(self):
        docs = [_doc("dec_page", {"lines_of_business": [
                    "Commercial General Liability", "Commercial Automobile Liability"]}, "1.pdf"),
                _doc("certificate", {"lines_of_business": ["General Liability"]}, "2.pdf")]
        assert self._warn(docs) == []

    def test_a_DENIED_line_listed_as_active_elsewhere_IS_a_conflict(self):
        docs = [_doc("dec_page", {"lines_of_business": ["General Liability"],
                                  "coverage_lines": [{"line": "Commercial Property",
                                                      "premium": "NO COVERAGE"}]}, "1.pdf"),
                _doc("application", {"lines_of_business": ["General Liability",
                                                          "Commercial Property"]}, "3.pdf")]
        assert self._warn(docs) != []

    def test_a_CERTIFICATE_row_is_not_a_denial(self):
        """LIVE RUN 2026-08-21, third occurrence. A COI never prints premiums, so
        most COI rows fail `_line_entry_grants_coverage`. Reading that as a
        DENIAL is absence-of-evidence-as-evidence - Principle 3's forbidden move
        - and it manufactured this warning inside the fix meant to enforce
        Principle 3. Denial must be an EXPLICIT statement."""
        docs = [_doc("dec_page", {
                    "lines_of_business": ["Commercial General Liability",
                                          "Commercial Automobile Liability"],
                    "coverage_lines": [{"line": "Commercial General Liability",
                                        "premium": "$6,720"}]}, "1.pdf"),
                _doc("certificate", {
                    "lines_of_business": ["General Liability", "Automobile Liability"],
                    "coverage_lines": [
                        {"line": "General Liability", "policy_number": "BBC7263-26"},
                        {"line": "Automobile Liability", "policy_number": "6E7-40-02---26"}]},
                    "2.pdf")]
        assert self._warn(docs) == []

    def test_grants_and_denies_are_twins_not_negations(self):
        from services.extraction_service import (
            _line_entry_grants_coverage as grants,
            _line_entry_denies_coverage as denies,
        )
        silent = {"line": "General Liability", "policy_number": "BBC7263-26"}
        assert grants(silent) is False and denies(silent) is False   # SILENT
        granted = {"line": "General Liability", "premium": "$6,720"}
        assert grants(granted) is True and denies(granted) is False
        denied = {"line": "Commercial Property", "premium": "NO COVERAGE"}
        assert grants(denied) is False and denies(denied) is True

    def test_a_denial_nobody_contradicts_is_not_a_conflict(self):
        docs = [_doc("dec_page", {"lines_of_business": ["General Liability"],
                                  "coverage_lines": [{"line": "Commercial Property",
                                                      "premium": "NO COVERAGE"}]}, "1.pdf"),
                _doc("certificate", {"lines_of_business": ["General Liability"]}, "2.pdf")]
        assert self._warn(docs) == []


# ═════════════════════════════════════════════════════════════════════════════
# C1c - submission_integrity was the SIXTH comparison site (2026-08-21 live run)
# ═════════════════════════════════════════════════════════════════════════════

class TestSubmissionIntegrityUsesTheDoor:
    """It counted DISTINCT NORMALISED STRINGS and produced three false review
    notes on a clean package: a component address, a 4-policy package's four
    policy numbers, and two prose operations descriptions."""

    def _assess(self, docs):
        from services.submission_integrity import assess_submission_integrity
        return assess_submission_integrity(docs)

    def _d(self, fn, facts, dt="dec_page", text=""):
        return {"filename": fn, "doc_type": dt, "text": text,
                "doc_id": fn, "facts": facts}

    def test_a_component_address_is_not_a_divergence(self):
        r = self._assess([
            self._d("a.pdf", {"applicant_name": "Orbin Contracting LLC",
                              "physical_address": ADDR_A}),
            self._d("b.pdf", {"applicant_name": "Orbin Contracting LLC",
                              "physical_address": ADDR_C}, "application")])
        assert r["reasons"] == []

    def test_prose_operations_are_never_a_divergence(self):
        r = self._assess([
            self._d("a.pdf", {"applicant_name": "Orbin Contracting LLC",
                              "operations_description":
                              "Licensed electrical and roofing contractor performing "
                              "commercial installation and service work."}),
            self._d("b.pdf", {"applicant_name": "Orbin Contracting LLC",
                              "operations_description":
                              "Administrative office and contracting warehouse with "
                              "material storage at the Denver premises."}, "application")])
        assert r["reasons"] == []

    def test_a_multi_policy_package_is_not_multiple_policy_numbers(self):
        r = self._assess([
            self._d("a.pdf", {"applicant_name": "Orbin Contracting LLC",
                              "policy_number": "BBC7263-26",
                              "dec_page_entries": ORBIN_ENTRIES}),
            self._d("b.pdf", {"applicant_name": "Orbin Contracting LLC",
                              "policy_number": "6E7-40-02---26"}, "certificate")])
        assert not any("policy number" in x.lower() for x in r["reasons"])

    def test_a_loss_runs_policy_number_is_not_the_submissions(self):
        r = self._assess([
            self._d("a.pdf", {"applicant_name": "Orbin Contracting LLC",
                              "policy_number": "BBC7263-26"}),
            self._d("lr.pdf", {"applicant_name": "Orbin Contracting LLC",
                               "policy_number": "6E7 40 02 26"}, "loss_run")])
        assert not any("policy number" in x.lower() for x in r["reasons"])

    def test_carrier_uses_the_FAMILY_comparator_not_the_conflict_one(self):
        """Integrity asks "same submission?" - a clustering question. EMC P&C
        and Employers Mutual are one carrier group. The CONFLICT picker asks a
        different question about the same names and must still say different."""
        r = self._assess([
            self._d("a.pdf", {"applicant_name": "Orbin Contracting LLC",
                              "carrier_name": "EMC Property & Casualty Company"}),
            self._d("b.pdf", {"applicant_name": "Orbin Contracting LLC",
                              "carrier_name": "Employers Mutual Casualty Company"},
                    "application")])
        assert r["reasons"] == []
        assert conflict("carrier_name", ["EMC Property & Casualty Company",
                                         "Employers Mutual Casualty Company"])

    @pytest.mark.parametrize("field,a,b,needle", [
        ("physical_address", "100 Main St, Denver, CO 80216",
         "900 Elm Ave, Boulder, CO 80301", "address"),
        ("entity_type", "LLC", "Corporation", "Entity type"),
        ("carrier_name", "Travelers Indemnity", "Hartford Fire Insurance", "carrier"),
    ])
    def test_a_REAL_divergence_still_fires(self, field, a, b, needle):
        r = self._assess([
            self._d("a.pdf", {"applicant_name": "Orbin Contracting LLC", field: a}),
            self._d("b.pdf", {"applicant_name": "Orbin Contracting LLC", field: b},
                    "application")])
        assert any(needle in x for x in r["reasons"]), r["reasons"]

    def test_two_REAL_insureds_still_block(self):
        """The blocking path is name/FEIN clustering - untouched by C1c."""
        r = self._assess([
            self._d("a.pdf", {"applicant_name": "Orbin Contracting LLC", "fein": "84-2210987"}),
            self._d("b.pdf", {"applicant_name": "Smith Roofing Incorporated",
                              "fein": "12-3456789"}, "application")])
        assert r["review_required"] is True and r["status"] == "low"


# ═════════════════════════════════════════════════════════════════════════════
# F4 / B2 - loss-run identity through the door
# ═════════════════════════════════════════════════════════════════════════════

class TestLossRunIdentity:
    APPLICANT = "ORBIN CONTRACTING LLC"

    def _tier(self, docs, name=APPLICANT, merged=None):
        from services.sqs_service import _check_loss_run_insured_match
        return _check_loss_run_insured_match(docs, name, merged)

    def _detail(self, docs, name=APPLICANT):
        from services.sqs_service import _check_loss_run_insured_match_detail
        return _check_loss_run_insured_match_detail(docs, name)

    def test_fein_punctuation_is_strong(self):
        docs = [_doc("dec_page", {"applicant_name": self.APPLICANT, "fein": "84-2210987"}),
                _doc("loss_run", {"applicant_name": "Orbin Contracting, LLC", "fein": "842210987"}, "lr.pdf")]
        assert self._tier(docs) == "strong"

    def test_policy_spacing_is_strong(self):
        docs = [_doc("dec_page", {"applicant_name": self.APPLICANT, "policy_number": "6E7-40-02---26"}),
                _doc("loss_run", {"applicant_name": self.APPLICANT, "policy_number": "6E7 40 02 26"}, "lr.pdf")]
        assert self._tier(docs) == "strong"

    def test_an_address_fragment_is_moderate(self):
        docs = [_doc("dec_page", {"applicant_name": self.APPLICANT, "mailing_address": ADDR_A}),
                _doc("loss_run", {"applicant_name": self.APPLICANT, "mailing_address": ADDR_C}, "lr.pdf")]
        assert self._tier(docs) == "moderate"

    def test_multi_policy_package_matches_the_runs_own_policy(self):
        docs = [_doc("dec_page", {"applicant_name": self.APPLICANT, "policy_number": "BBC7263-26"}, "gl.pdf"),
                _doc("dec_page", {"applicant_name": self.APPLICANT, "policy_number": "6E7-40-02---26"}, "auto.pdf"),
                _doc("loss_run", {"applicant_name": self.APPLICANT, "policy_number": "6E7-40-02---26"}, "lr.pdf")]
        assert self._tier(docs) == "strong"

    def test_coverage_lines_are_a_policy_witness(self):
        docs = [_doc("dec_page", {"applicant_name": self.APPLICANT,
                                  "coverage_lines": [{"line": "Commercial Auto", "policy_number": "6E7-40-02---26"}]}),
                _doc("loss_run", {"applicant_name": self.APPLICANT, "policy_number": "6E74002 26"}, "lr.pdf")]
        assert self._tier(docs) == "strong"

    def test_dba_keeps_the_specs_tier_and_adds_a_note(self):
        """Q3a is open: engineering default is the spec's own verdict plus a
        producer-facing note, never an invented tier."""
        docs = [_doc("dec_page", {"applicant_name": self.APPLICANT, "dba_name": "Orbin Roofing", "fein": "84-2210987"}),
                _doc("loss_run", {"applicant_name": "Orbin Roofing", "fein": "84-2210987"}, "lr.pdf")]
        d = self._detail(docs)
        assert d["tier"] == "no_match"
        assert "dba_name" in d["matched_on"]
        assert any("trade name" in n for n in d["notes"])

    def test_fein_match_with_a_different_name_is_noted(self):
        docs = [_doc("dec_page", {"applicant_name": self.APPLICANT, "fein": "84-2210987"}),
                _doc("loss_run", {"applicant_name": "Totally Other Co", "fein": "84-2210987"}, "lr.pdf")]
        d = self._detail(docs)
        assert d["tier"] == "no_match"
        assert any("FEIN matches" in n for n in d["notes"])

    def test_a_genuinely_different_insured_is_no_match(self):
        docs = [_doc("dec_page", {"applicant_name": self.APPLICANT}),
                _doc("loss_run", {"applicant_name": "Smith Roofing Inc"}, "lr.pdf")]
        assert self._tier(docs) == "no_match"

    def test_loss_run_self_match_is_still_excluded(self):
        docs = [_doc("loss_run", {"applicant_name": "Orbin Contracting", "fein": "123456789"}, "lr.pdf")]
        assert self._tier(docs, "Orbin Contracting") == "possible"

    def test_detail_is_explainable(self):
        docs = [_doc("dec_page", {"applicant_name": self.APPLICANT, "fein": "84-2210987"}),
                _doc("loss_run", {"applicant_name": self.APPLICANT, "fein": "84-2210987"}, "lr.pdf")]
        d = self._detail(docs)
        assert d["tier"] == "strong"
        assert "name" in d["matched_on"] and "fein" in d["matched_on"]
        assert d["per_document"][0]["filename"] == "lr.pdf"

    def test_a_carrier_ALIAS_on_the_loss_run_raises_no_note(self):
        """Client 1.8 lists "known carrier-name variations". Found 2026-08-21:
        the carrier corroboration used values_agree, which uses the STRICT key -
        correct for conflicts, wrong here - so an ordinary EMC package got a
        false "carrier does not match" note."""
        docs = [_doc("dec_page", {"applicant_name": self.APPLICANT,
                                  "carrier_name": "EMC Insurance Companies",
                                  "policy_number": "BBC7263-26"}),
                _doc("loss_run", {"applicant_name": self.APPLICANT,
                                  "carrier_name": "Employers Mutual Casualty",
                                  "policy_number": "BBC7263-26"}, "lr.pdf")]
        assert self._detail(docs)["notes"] == []

    def test_a_genuinely_different_carrier_still_raises_the_note(self):
        docs = [_doc("dec_page", {"applicant_name": self.APPLICANT,
                                  "carrier_name": "Travelers Indemnity",
                                  "policy_number": "BBC7263-26"}),
                _doc("loss_run", {"applicant_name": self.APPLICANT,
                                  "carrier_name": "Hartford Fire Insurance",
                                  "policy_number": "BBC7263-26"}, "lr.pdf")]
        assert any("Carrier on the loss run" in n for n in self._detail(docs)["notes"])

    def test_GATE_the_family_check_never_leaks_into_conflict_detection(self):
        """carriers_same_family folds EMC P&C into Employers Mutual. If that
        ever reached the picker, the two REAL carriers would stop conflicting -
        Round 10 fix 46 undone. The two comparators must stay separate."""
        from services.fact_comparison import carriers_same_family
        assert carriers_same_family(
            "EMC Property & Casualty Company", "Employers Mutual Casualty Company")
        assert conflict("carrier_name", [
            "EMC Property & Casualty Company", "Employers Mutual Casualty Company"])

    @pytest.mark.parametrize("variant", [
        "Orbin Contracting", "ORBIN CONTRACTING, L.L.C.",
        "Orbin Contracting LLC.", "orbin contracting llc",
    ])
    def test_every_legal_name_variation_the_client_lists(self, variant):
        docs = [_doc("dec_page", {"applicant_name": self.APPLICANT, "fein": "84-2210987"}),
                _doc("loss_run", {"applicant_name": variant, "fein": "842210987"}, "lr.pdf")]
        assert self._tier(docs) == "strong"

    def test_a_different_entity_TYPE_is_not_a_name_variation(self):
        """LLC vs Company are different legal entities, not a formatting
        difference - consistent with test_llc_vs_inc_is_a_different_entity."""
        docs = [_doc("dec_page", {"applicant_name": self.APPLICANT, "fein": "84-2210987"}),
                _doc("loss_run", {"applicant_name": "Orbin Contracting Company",
                                  "fein": "84-2210987"}, "lr.pdf")]
        assert self._tier(docs) == "no_match"

    def test_calculate_sqs_exposes_the_detail(self):
        import inspect
        from services import sqs_service
        src = inspect.getsource(sqs_service.calculate_package_sqs)
        assert "loss_run_match_detail" in src


# ═════════════════════════════════════════════════════════════════════════════
# F8 / FLAG 4 - lines of business
# ═════════════════════════════════════════════════════════════════════════════

class TestLobCanon:
    @pytest.mark.parametrize("phrase,family", [
        ("Liability", "general_liab"), ("General Liability", "general_liab"),
        ("Commercial General Liability", "general_liab"), ("CGL", "general_liab"),
        ("Automobile", "auto"), ("Commercial Auto", "auto"),
        ("Commercial Automobile Liability", "auto"), ("Business Auto", "auto"),
        ("Umbrella", "umbrella"), ("Commercial Umbrella", "umbrella"),
        ("Umbrella Liability", "umbrella"), ("Commercial Liability Umbrella", "umbrella"),
        ("Contractors Equipment", "inland_marine"), ("Installation Floater", "inland_marine"),
        ("Computer Coverage", "inland_marine"), ("Commercial Inland Marine", "inland_marine"),
        ("Employers Liability", "workers_comp"),
    ])
    def test_every_family_the_client_listed(self, phrase, family):
        assert canon_line(phrase) == family

    @pytest.mark.parametrize("phrase", [
        "Professional Liability", "Employment Practices Liability", "Pollution Liability",
        "Directors and Officers Liability", "Employee Benefits Liability",
    ])
    def test_a_specialty_liability_line_is_never_general_liability(self, phrase):
        assert canon_line(phrase) != "general_liab"
        assert canon_line(phrase) is not None

    def test_unknown_terminology_is_unmapped(self):
        assert canon_line("Widget Liability") is None
        assert canon_line("Builders Risk") is None
        assert canon_line("") is None

    def test_a_professional_liability_value_is_foreign_to_a_gl_fact(self):
        from services.fact_equivalence import names_a_foreign_line, fact_line
        gl_key = next((k for k in ("gl_each_occurrence", "gl_aggregate") if fact_line(k) == "general_liab"), None)
        if gl_key is None:
            pytest.skip("no GL-scoped registry fact found")
        assert names_a_foreign_line(gl_key, "Professional Liability")

    def test_no_silent_fallback_remains(self):
        """B6: a circular-import blip must not silently disable canonicalisation."""
        import re, pathlib
        root = pathlib.Path(__file__).resolve().parents[1] / "services"
        hits = []
        for f in root.glob("*.py"):
            txt = f.read_text(encoding="utf-8")
            if re.search(r"_canon_line\s*=\s*lambda", txt) or re.search(r"def _canon_line\(_s\)", txt):
                hits.append(f.name)
        assert hits == [], hits


# ═════════════════════════════════════════════════════════════════════════════
# F9 / B7 - location consolidation uses the same address rule as the picker
# ═════════════════════════════════════════════════════════════════════════════

class TestLocationFragment:
    def test_the_clients_trio_is_one_premises_with_city_and_state(self):
        from services.extraction_service import _consolidate_property_locations
        f = {"locations": [ADDR_A, ADDR_B, ADDR_C]}
        _consolidate_property_locations(f)
        rows = f["property_locations"]
        assert len(rows) == 1
        assert rows[0]["address_city"] == "Denver"
        assert rows[0]["address_state"] == "CO"

    def test_GATE_a_fragment_fitting_two_premises_stays_its_own_row(self):
        from services.extraction_service import _consolidate_property_locations
        f = {"locations": ["100 Main St Denver CO 80216", "200 Oak Ave Denver CO 80216", ADDR_C]}
        _consolidate_property_locations(f)
        assert len(f["property_locations"]) == 3


# ═════════════════════════════════════════════════════════════════════════════
# LIVE RUN 2026-08-21 - two defects the pre-form screen exposed
# ═════════════════════════════════════════════════════════════════════════════

class TestCombinedCoverageLabel:
    """A dec page prints "Comprehensive and Collision  Symbol 07" - ONE label,
    TWO coverages. `normalize_coverage` returns only the first, so the collision
    symbol vanished and "no covered-auto symbol was found for: collision" fired
    on a policy that plainly shows one."""

    @pytest.mark.parametrize("label,expected", [
        ("Comprehensive and Collision", ["comprehensive", "collision"]),
        ("Comp/Coll", ["comprehensive", "collision"]),
        ("OTC & Collision", ["comprehensive", "collision"]),
        ("Physical Damage (Comprehensive and Collision)", ["comprehensive", "collision"]),
        ("Comprehensive", ["comprehensive"]),
        ("Collision", ["collision"]),
        ("Covered Autos Liability", ["liability"]),
        ("Widget Coverage", ["unspecified"]),
        (None, ["unspecified"]),
        ("", ["unspecified"]),
    ])
    def test_every_coverage_the_label_names(self, label, expected):
        from services.auto_symbols import normalize_coverages
        assert normalize_coverages(label) == expected

    def test_the_symbol_lands_on_both_coverages(self):
        from services.auto_symbols import parse_symbols
        assert parse_symbols([{"coverage": "Comprehensive and Collision",
                               "symbols": [7]}]) == {"comprehensive": [7],
                                                     "collision": [7]}

    def test_the_single_coverage_helper_still_returns_one(self):
        """Other callers rely on the scalar contract - it must not change."""
        from services.auto_symbols import normalize_coverage
        assert normalize_coverage("Comprehensive and Collision") == "comprehensive"


class TestYearsInBusinessIsDerived:
    """Client 1.4 "Derived". LIVE RUN: the dec page printed "Date Business
    Started: 06/15/2014" and the questionnaire still asked the insured how many
    years they had been open - a question the documents answer."""

    def _d(self, facts):
        from services.extraction_service import _derive_years_in_business
        _derive_years_in_business(facts)
        return facts

    def test_it_is_computed_from_the_start_date(self):
        f = self._d({"business_start_date": "06/15/2014"})
        assert int(f["years_in_business"]["value"]) >= 11

    def test_it_is_labelled_derived_not_source_verified(self):
        from services.fact_state import derive_evidence_state, DERIVED
        f = self._d({"business_start_date": "06/15/2014"})
        assert derive_evidence_state(f["years_in_business"])[0] == DERIVED

    def test_it_never_overwrites_an_existing_value(self):
        f = self._d({"business_start_date": "06/15/2014", "years_in_business": "20"})
        assert f["years_in_business"] == "20"

    @pytest.mark.parametrize("start", ["06/15/2099", "not a date", "", None])
    def test_it_refuses_anything_it_cannot_trust(self, start):
        assert "years_in_business" not in self._d({"business_start_date": start})

    def test_no_start_date_no_derivation(self):
        assert "years_in_business" not in self._d({})

    def test_it_runs_in_the_merge_tail(self):
        import inspect
        from services import extraction_service as es
        assert "_derive_years_in_business(mf)" in inspect.getsource(es.merge_facts)


# ═════════════════════════════════════════════════════════════════════════════
# F5 / B8 - value and evidence states
# ═════════════════════════════════════════════════════════════════════════════

class TestFactStates:
    def test_a_boolean_false_from_extraction_is_not_stated(self):
        st = fs.derive_states("has_subcontractors", {"value": False, "confidence": "ai_high", "source": "ai"})
        assert st["value_state"] == fs.NOT_STATED

    def test_a_boolean_false_from_a_human_is_an_explicit_no(self):
        st = fs.derive_states("has_subcontractors", {"value": False, "confidence": "client_arq", "source": "client_arq"})
        assert st["value_state"] == fs.EXPLICIT_NO
        assert st["evidence_state"] == fs.USER_CONFIRMED
        assert st["evidence_actor"] == "client"

    def test_booleans_never_enter_the_cross_document_comparison(self):
        from services.extraction_service import detect_source_conflicts
        docs = [{"doc_type": "policy", "facts": {"has_subcontractors": True}},
                {"doc_type": "application", "facts": {"has_subcontractors": False}}]
        assert detect_source_conflicts(docs) == []

    @pytest.mark.parametrize("env,evidence", [
        ({"value": "x", "confidence": "deterministic"}, fs.SOURCE_VERIFIED),
        ({"value": "x", "confidence": "ai_low", "source": "dec_entry"}, fs.SOURCE_VERIFIED),
        ({"value": "x", "confidence": "ai_high", "source": "ai"}, fs.SUGGESTED),
        ({"value": "x", "confidence": "low_confidence", "source": "derived"}, fs.DERIVED),
        ({"value": "x", "source": "user_confirmed"}, fs.USER_CONFIRMED),
        ({"value": "x", "source": "producer"}, fs.USER_CONFIRMED),
    ])
    def test_evidence_state_from_existing_signals(self, env, evidence):
        assert fs.derive_evidence_state(env)[0] == evidence

    def test_a_suggested_value_never_becomes_verified_without_a_signal(self):
        assert fs.derive_evidence_state({"value": "x", "confidence": "ai_high"})[0] == fs.SUGGESTED

    def test_conflicting_follows_the_withhold_list(self):
        f = {"umbrella_limit": {"value": "$3,000,000", "confidence": "ai_high"},
             "_uw_conflicted_keys": ["umbrella_limit"]}
        fs.annotate_fact_states(f)
        assert f["umbrella_limit"]["value_state"] == fs.CONFLICTING

    def test_assumed_is_unrepresentable(self):
        assert "assumed" not in fs.VALUE_STATES
        assert "assumed" not in fs.EVIDENCE_STATES

    @pytest.mark.parametrize("vs,es,shown", [
        (fs.PRESENT, fs.SOURCE_VERIFIED, "VERIFIED"),
        (fs.PRESENT, fs.DERIVED, "VERIFIED"),
        (fs.EXPLICIT_NO, fs.USER_CONFIRMED, "CONFIRMED"),
        (fs.NOT_APPLICABLE, fs.SUGGESTED, "NOT APPLICABLE"),
        (fs.PRESENT, fs.SUGGESTED, "UNRESOLVED"),
        (fs.NOT_STATED, fs.SUGGESTED, "UNRESOLVED"),
        (fs.CONFLICTING, fs.SOURCE_VERIFIED, "UNRESOLVED"),
    ])
    def test_the_125_docs_four_word_projection(self, vs, es, shown):
        assert fs.display_state(vs, es) == shown

    def test_annotation_is_additive_and_skips_bare_scalars(self):
        f = {"a": {"value": "1", "confidence": "deterministic"}, "b": "bare", "_private": {"value": 1}}
        fs.annotate_fact_states(f)
        assert f["a"]["value"] == "1" and f["a"]["value_state"] == fs.PRESENT
        assert f["b"] == "bare"
        assert "value_state" not in f["_private"]

    def test_derived_writers_label_themselves(self):
        import inspect
        from services import extraction_service as es
        assert "evidence_state" in inspect.getsource(es._backfill_empty_facts_from_entries)
        assert "evidence_state=\"derived\"" in inspect.getsource(es._reconcile_total_premium)
        assert 'source="derived"' in inspect.getsource(es._route_renewal_dates) or \
               '"derived"' in inspect.getsource(es._route_renewal_dates)


# ═════════════════════════════════════════════════════════════════════════════
# F7 / B4 - a client answer that disagrees with the source is held
# ═════════════════════════════════════════════════════════════════════════════

class TestClientAnswerGuard:
    def test_disagreement_is_held(self):
        from services.arq_service import _client_answer_conflicts_with_source as g
        assert g("num_employees", {"value": "18", "confidence": "ai_high"}, "18", "25")

    def test_agreement_applies(self):
        from services.arq_service import _client_answer_conflicts_with_source as g
        assert not g("num_employees", {"value": "18"}, "18", "18")
        assert not g("mailing_address", {"value": ADDR_A}, ADDR_A, ADDR_B)

    def test_a_blank_source_applies(self):
        from services.arq_service import _client_answer_conflicts_with_source as g
        assert not g("num_employees", None, None, "25")
        assert not g("num_employees", {"value": ""}, "", "25")

    def test_a_human_owned_source_is_not_second_guessed(self):
        from services.arq_service import _client_answer_conflicts_with_source as g
        assert not g("num_employees", {"value": "18", "source": "producer"}, "18", "25")

    def test_kill_switch(self, monkeypatch):
        from services import arq_service
        monkeypatch.setattr(arq_service, "ENABLE_CLIENT_ANSWER_CONFLICT_ROUTING", False)
        assert not arq_service._client_answer_conflicts_with_source(
            "num_employees", {"value": "18"}, "18", "25")

    def test_the_held_answer_reaches_the_picker_as_a_source(self):
        from services.underwriting_consistency import assess_underwriting_consistency
        docs = [_doc("policy", {"num_employees": "18"}, "dec.pdf")]
        r = assess_underwriting_consistency(docs, {
            "num_employees": "18",
            "_client_answer_conflicts": {"num_employees": {"client_value": "25", "source_value": "18"}},
        })
        row = next(f for f in r["fields"] if f["fact_key"] == "num_employees")
        assert row["status"] == "conflict"
        sources = {s["filename"] for v in row["values"] for s in v["sources"]}
        assert "Client questionnaire" in sources and "dec.pdf" in sources

    def test_confirming_releases_the_held_answer(self):
        from services.underwriting_consistency import apply_confirmations
        out = apply_confirmations(
            {"num_employees": "18",
             "_client_answer_conflicts": {"num_employees": {"client_value": "25"},
                                         "total_revenue": {"client_value": "1"}}},
            {"num_employees": "25"})
        assert "num_employees" not in out["_client_answer_conflicts"]
        assert "total_revenue" in out["_client_answer_conflicts"]
        assert out["num_employees"]["value"] == "25"

    def test_pipeline_carries_held_answers_through_a_rerun(self):
        import inspect
        from services import extraction_pipeline as ep
        src = inspect.getsource(ep._finalize_pipeline)
        assert "client_answer_conflicts" in src
        assert "client_answer_conflicts=session.get" in inspect.getsource(ep.confirm_underwriting_value)


# ═════════════════════════════════════════════════════════════════════════════
# F10 - producer resolution keeps the evidence
# ═════════════════════════════════════════════════════════════════════════════

class TestResolutionKeepsEvidence:
    def test_confirm_stashes_the_candidates_and_reason(self):
        import inspect
        from services import extraction_pipeline as ep
        src = inspect.getsource(ep.confirm_underwriting_value)
        assert "_pre_confirm_candidates" in src and "_pre_confirm_reason" in src

    def test_audit_writer_accepts_candidates(self):
        import inspect
        from services import audit_service
        sig = inspect.signature(audit_service.log_underwriting_confirmation)
        assert "candidates" in sig.parameters and "reason" in sig.parameters

    def test_schema_has_the_columns_on_both_paths(self):
        import pathlib
        root = pathlib.Path(__file__).resolve().parents[1]
        ddl = (root / "models" / "schemas.py").read_text(encoding="utf-8")
        db = (root / "config" / "database.py").read_text(encoding="utf-8")
        assert "candidates    JSONB" in ddl
        assert "underwriting_confirmation_audit ADD COLUMN IF NOT EXISTS candidates JSONB" in db

    def test_conflict_rows_carry_a_reason(self):
        from services.underwriting_consistency import assess_underwriting_consistency
        docs = [_doc("policy", {"total_revenue": "$1,000,000"}, "a.pdf"),
                _doc("application", {"total_revenue": "$1,200,000"}, "b.pdf")]
        r = assess_underwriting_consistency(docs, {})
        row = next(f for f in r["fields"] if f["fact_key"] == "total_revenue")
        assert row["status"] == "conflict"
        assert "different amounts" in row["conflict_reason"]


# ═════════════════════════════════════════════════════════════════════════════
# D7 - every "exactly one" guard counts equivalence classes
# ═════════════════════════════════════════════════════════════════════════════

class TestExactlyOneGuardsSeeCliques:
    def test_equivalent_index(self):
        assert fc._fe.equivalent_index("mailing_address", [ADDR_A, ADDR_B, ADDR_C]) is not None

    def test_location_consolidation(self):
        from services.extraction_service import _consolidate_property_locations
        f = {"locations": [ADDR_A, ADDR_B, ADDR_C]}
        _consolidate_property_locations(f)
        assert len(f["property_locations"]) == 1

    def test_contract_printing_election(self):
        ctx = PackageContext({"dec_page_entries": ORBIN_ENTRIES})
        assert ctx.same_contract_printing("6E7-40-02---26", "6E74002")
        assert ctx.same_contract_printing("6E7 40 02 26", "6E7-40-02---26")
