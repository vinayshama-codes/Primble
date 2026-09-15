"""11 Sep 2026: one person in BOTH contact blocks, from ONE document.

Live run 3, stored per-document facts, both packages:
  Run A narrative - contact_* and producer_contact_* both Michelle Smith (agent)
  Run B dec page  - contact_* and producer_contact_* both Dana Whitfield (agent)
The applicant's Tier 1 contact read as answered by the broker's own person.
"""
import copy

import pytest

import services.pdf_service as ps
from services.extraction_service import (
    contact_email_party, merge_facts, separate_contact_twins)

RUN_A_NARRATIVE = {
    "applicant_name": "Orbin Contracting LLC",
    "producer_name": "ThinkSmith Agency",
    "contact_name": "Michelle Smith",
    "contact_phone": "(303) 555-0142",
    "contact_email": "michelle.smith@thinksmith.example",
    "producer_contact_name": "Michelle Smith",
    "producer_contact_phone": "(303) 555-0142",
    "producer_contact_email": "michelle.smith@thinksmith.example",
}
RUN_B_DEC = {
    "producer_name": "Cascade Risk Partners",
    "contact_name": "Dana Whitfield",
    "contact_phone": "(720) 555-0188",
    "producer_contact_name": "Dana Whitfield",
    "producer_contact_phone": "(720) 555-0188",
    "dec_page_entries": [{"label": "AGENT", "owner": "producer",
                          "value": "Cascade Risk Partners | Dana Whitfield | (720) 555-0188",
                          "section": "COMMERCIAL POLICY DECLARATIONS"}],
}
CONTACT = ("contact_name", "contact_phone", "contact_email")
PRODUCER = ("producer_contact_name", "producer_contact_phone", "producer_contact_email")


class TestTheLiveShapes:
    def test_run_A_the_email_domain_names_the_agency(self):
        f = copy.deepcopy(RUN_A_NARRATIVE)
        removed = separate_contact_twins(f)
        assert sorted(removed) == sorted(CONTACT)
        assert not any(k in f for k in CONTACT)
        assert all(f[k] for k in PRODUCER)

    def test_run_B_the_owner_tag_names_the_agency(self):
        """No email on the dec page - the joined AGENT entry's owner decides."""
        f = copy.deepcopy(RUN_B_DEC)
        assert sorted(separate_contact_twins(f)) == ["contact_name", "contact_phone"]
        assert f["producer_contact_name"] == "Dana Whitfield"

    def test_the_value_envelope_shape(self):
        f = {k: {"value": v, "confidence": 0.9} if k != "dec_page_entries" else v
             for k, v in RUN_B_DEC.items()}
        assert "contact_name" in separate_contact_twins(f)


class TestNoEvidenceNoOpinion:
    def test_twins_with_no_email_and_no_entries(self):
        f = {k: v for k, v in RUN_B_DEC.items() if k != "dec_page_entries"}
        before = copy.deepcopy(f)
        assert separate_contact_twins(f) == [] and f == before

    def test_an_email_domain_matching_neither_party(self):
        f = dict(RUN_A_NARRATIVE, contact_email="m@gmail.com", producer_contact_email="m@gmail.com")
        assert separate_contact_twins(f) == []

    def test_domain_and_entry_disagree(self):
        f = dict(copy.deepcopy(RUN_B_DEC), applicant_name="Whitfield Holdings",
                 contact_email="dana@whitfield.example",
                 producer_contact_email="dana@whitfield.example")
        # domain -> applicant, owner tag -> producer: no opinion
        assert separate_contact_twins(f) == []

    def test_an_other_owner_is_not_evidence(self):
        f = copy.deepcopy(RUN_B_DEC)
        f["dec_page_entries"][0]["owner"] = "other"
        assert separate_contact_twins(f) == []


class TestTheApplicantDirection:
    def test_the_applicants_email_keeps_the_applicant_and_drops_the_copy(self):
        f = {"applicant_name": "Orbin Contracting LLC", "producer_name": "ThinkSmith Agency",
             "contact_name": "Erin Royal", "producer_contact_name": "Erin Royal",
             "contact_email": "erin@orbin.example", "producer_contact_email": "erin@orbin.example"}
        assert sorted(separate_contact_twins(f)) == ["producer_contact_email",
                                                     "producer_contact_name"]
        assert f["contact_name"] == "Erin Royal"


class TestOnlyTwinsAreTouched:
    def test_a_different_phone_is_kept(self):
        f = dict(copy.deepcopy(RUN_B_DEC), contact_phone="(720) 555-9999")
        assert separate_contact_twins(f) == ["contact_name"]
        assert f["contact_phone"] == "(720) 555-9999"

    def test_a_name_inside_a_longer_name_is_not_the_person(self):
        f = copy.deepcopy(RUN_B_DEC)
        f["dec_page_entries"][0]["value"] = "Cascade Risk Partners | Dana Whitfieldson"
        f["contact_phone"] = f["producer_contact_phone"] = None
        assert separate_contact_twins(f) == []

    @pytest.mark.parametrize("junk", [None, "", 5, [], {"contact_name": None},
                                      {"dec_page_entries": "x", "contact_name": "A",
                                       "producer_contact_name": "A"}])
    def test_junk_never_raises(self, junk):
        separate_contact_twins(junk)


class TestThroughTheMerge:
    def _doc(self, name, role, facts):
        return {"filename": name, "doc_type": role, "text": "", "facts": copy.deepcopy(facts),
                "flags": {}}

    def test_alone_the_agent_is_no_longer_the_applicant_contact(self):
        d = self._doc("control_dec.pdf", "dec_page", RUN_B_DEC)
        mf, _ = merge_facts([d], d)
        def _v(k):
            v = mf.get(k)
            return v.get("value") if isinstance(v, dict) else v
        assert not _v("contact_name")
        assert _v("producer_contact_name") == "Dana Whitfield"
        # and the per-document copy the picker compares is cleaned too
        assert "contact_name" not in d["facts"]

    def test_a_real_applicant_contact_elsewhere_now_wins(self):
        nar = self._doc("narrative.pdf", "narrative", RUN_A_NARRATIVE)
        app = self._doc("application.pdf", "application",
                        {"applicant_name": "Orbin Contracting LLC", "contact_name": "Erin Royal",
                         "contact_phone": "(303) 555-7777"})
        mf, _ = merge_facts([nar, app], app)
        def _v(k):
            v = mf.get(k)
            return v.get("value") if isinstance(v, dict) else v
        assert _v("contact_name") == "Erin Royal"
        assert _v("producer_contact_name") == "Michelle Smith"

    def test_idempotent_on_a_re_merge(self):
        d = self._doc("control_dec.pdf", "dec_page", RUN_B_DEC)
        merge_facts([d], d)
        snap = copy.deepcopy(d["facts"])
        merge_facts([d], d)
        assert d["facts"] == snap


class TestOneDoor:
    @pytest.mark.parametrize("facts", [
        RUN_A_NARRATIVE,
        {"contact_email": "erin@orbin.example", "applicant_name": "Orbin Contracting LLC",
         "producer_name": "ThinkSmith Agency"},
        {"contact_email": "x@both.example", "applicant_name": "Both LLC", "producer_name": "Both Agency"},
        {"contact_email": None},
        {},
    ])
    def test_the_form_resolver_reads_the_same_door(self, facts):
        assert ps._contact_email_party(facts) == contact_email_party(
            facts.get("contact_email"), facts.get("applicant_name"), facts.get("producer_name"))
