"""11 Sep 2026: the producer picker suggested the agency being REPLACED.

Live, three runs: the Data Consistency card for Producer Name badged
`Commercial Risk Solutions` (from the EXPIRING dec page) as Suggested over
`ThinkSmith Agency` (from the submission narrative). Both came from one
document each, so the name-like tiebreak fell to raw string length. The role
is on every source already (`doc_type`); the picker now reads it.
"""
import pytest

from services.extraction_service import (
    _EXPIRING_PROGRAMME_ROLES, _PRODUCER_IDENTITY_KEYS, _SUBMISSION_ROLES)
from services.underwriting_consistency import (
    _producer_role_separates, _submission_backed, _suggest_for_field)


def grp(display, doc_type, doc_id="d1", method="llm", extra_docs=()):
    srcs = [{"doc_id": doc_id, "doc_type": doc_type, "raw": display,
             "source_method": method}]
    for i, dt in enumerate(extra_docs):
        srcs.append({"doc_id": f"{doc_id}x{i}", "doc_type": dt, "raw": display,
                     "source_method": "llm"})
    return {"display": display, "normalized": display.lower(), "sources": srcs}


LIVE = [grp("ThinkSmith Agency", "narrative", "d1"),
        grp("Commercial Risk Solutions", "dec_page", "d2")]


class TestTheLiveCase:
    def test_the_submitting_agency_is_suggested(self):
        res = _suggest_for_field("producer_name", "identity", list(LIVE))
        assert res["value"] == "ThinkSmith Agency"
        assert res["confidence"] == "high"

    def test_either_order(self):
        res = _suggest_for_field("producer_name", "identity", list(reversed(LIVE)))
        assert res["value"] == "ThinkSmith Agency"

    @pytest.mark.parametrize("key", sorted(_PRODUCER_IDENTITY_KEYS))
    def test_every_producer_identity_key(self, key):
        vals = [grp("Michelle Smith", "application", "d1"),
                grp("Terri Wroblewski Longer", "policy", "d2")]
        assert _suggest_for_field(key, "identity", vals)["value"] == "Michelle Smith"


class TestTheRoleOnlyDecidesWhenItSeparates:
    def test_both_submission_backed_falls_back_to_the_old_ranking(self):
        vals = [grp("ThinkSmith Agency", "narrative", "d1"),
                grp("Commercial Risk Solutions", "application", "d2")]
        assert not _producer_role_separates(vals)

    def test_neither_submission_backed_falls_back(self):
        vals = [grp("ThinkSmith Agency", "dec_page", "d1"),
                grp("Commercial Risk Solutions", "certificate", "d2")]
        assert not _producer_role_separates(vals)

    def test_an_incumbent_in_both_roles_ties_as_before(self):
        """The same agency on the expiring dec AND the new application is
        submission-backed, and so is nothing else: it wins on the role."""
        vals = [grp("ThinkSmith Agency", "dec_page", "d1", extra_docs=["application"]),
                grp("Other Agency", "dec_page", "d2")]
        assert _producer_role_separates(vals)
        assert _suggest_for_field("producer_name", "identity", vals)["value"] == "ThinkSmith Agency"

    @pytest.mark.parametrize("key", ["applicant_name", "carrier_name", "mailing_address",
                                     "fein", "dba_name"])
    def test_a_non_producer_field_never_reads_the_role(self, key):
        """The applicant IS named by the expiring dec - the role says nothing."""
        vals = [grp("Orbin", "narrative", "d1"),
                grp("Orbin Contracting LLC", "dec_page", "d2")]
        res = _suggest_for_field(key, "identity", vals)
        # Old ranking: equal doc counts, longer (more complete) name wins.
        if res:
            assert res["value"] != "Orbin" or res.get("confidence") != "high"

    def test_a_text_scan_only_value_is_still_demoted(self):
        """The pre-existing safety-net demotion is not overridden."""
        vals = [grp("ThinkSmith Agency", "narrative", "d1", method="text_scan"),
                grp("Commercial Risk Solutions", "dec_page", "d2")]
        res = _suggest_for_field("producer_name", "identity", vals)
        assert res["value"] == "ThinkSmith Agency"
        assert res["confidence"] != "high"


class TestTheRoleSetsAreTheMergesOwn:
    def test_roles_are_disjoint(self):
        assert not (_SUBMISSION_ROLES & _EXPIRING_PROGRAMME_ROLES)

    @pytest.mark.parametrize("dt", ["  NARRATIVE ", "Application", "quote"])
    def test_role_is_read_case_and_space_insensitively(self, dt):
        assert _submission_backed(grp("X", dt))

    @pytest.mark.parametrize("junk", [None, "", 5, "unknown"])
    def test_junk_doc_type_is_not_submission(self, junk):
        g = {"display": "X", "sources": [{"doc_type": junk}]}
        assert not _submission_backed(g)

    @pytest.mark.parametrize("junk", [{}, {"sources": None}, {"sources": "x"},
                                      {"sources": [None]}])
    def test_malformed_groups_never_raise(self, junk):
        assert _submission_backed(junk) is False
