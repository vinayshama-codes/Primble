"""Build of 21 Oct 2026, lane B, item b-identity-verified-only (25sepChanges.md Z30).

Brent's Choice Electric test of 17 Oct, item 4, and his 20 Oct rule "only trigger
a hard stop when Primble has enough VERIFIED information to know the condition is
true; otherwise flag it for confirmation instead of assuming".

The stored 17 Oct session (ecab28dd, Z29-6): a handwritten narrative JPEG reads
"I met with Eric / Berger owner of Choice Electric"; extraction took
"Berger Owner of Choice Electric" as the narrative's applicant name; the
comparison door rightly says that is not CHOICE ELECTRIC LLC, and the Data
Consistency name conflict became a HARD STOP (60).

Two fixes, two sections:

  A. A person in a role is not the insured - `normalization.is_person_in_a_role`,
     read through the insured-name door `is_not_a_party_name` by every reader of a
     document's own insured name (the per-document drop, the merge vote, the
     merged floor, the identity checks, Submission Integrity, insured_scope, the
     Documents list).
  B. Verified sources only - ONE definition, `document_tags.is_verified_source`,
     read by the identity hard stop (`sqs_service.check_doc_consistency`), the
     Data Consistency picker's blocking decision (`stops_now.
     underwriting_conflict_stops`) and Submission Integrity's "different insured"
     verdict. A disagreement only an unverified source raises is a warning to
     confirm (85), never a hard stop (60).

The adversarial cases come first in each section: the rule must not over-reach.
"""
import ast
import copy
import logging
import os
import pathlib
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("OPENAI_API_KEY", "sk-offline")

from services import document_tags as DT                              # noqa: E402
from services import extraction_service as ES                         # noqa: E402
from services import normalization as NZ                              # noqa: E402
from services import stops_now as SN                                  # noqa: E402
from services.issue_registry import _display_severity                 # noqa: E402
from services.sqs_service import (                                    # noqa: E402
    check_doc_consistency, doc_consistency_stops, one_blocker_per_conflict,
    split_doc_consistency_issues,
)
from services.submission_integrity import assess_submission_integrity  # noqa: E402
from services.underwriting_consistency import (                       # noqa: E402
    assess_underwriting_consistency,
)

BACKEND = pathlib.Path(__file__).resolve().parent.parent
logging.getLogger().setLevel(logging.CRITICAL)


def _env(value, conf="ai_high", source="ai"):
    """A fact as extraction stores it on a document."""
    return {"value": value, "confidence": conf, "source": source}


def _v(raw):
    return raw.get("value") if isinstance(raw, dict) and "value" in raw else raw


_DEC_TEXT = ("DECLARATIONS\nNAMED INSURED: {name}\n" + "COMMERCIAL POLICY COVERAGE PART " * 60)


def _doc(doc_id, filename, doc_type="dec_page", name=None, fein=None, *, conf="high",
         supporting=False, overridden=False, name_conf="ai_high", fein_conf="ai_high",
         text=None, low_tokens=(), manual=()):
    """One stored document, shaped like `extraction_pipeline.extract_document`'s."""
    facts = {}
    if name is not None:
        facts["applicant_name"] = _env(name, name_conf)
    if fein is not None:
        facts["fein"] = _env(fein, fein_conf)
    d = {
        "doc_id": doc_id, "filename": filename, "doc_type": doc_type,
        "doc_type_confidence": conf,
        "doc_type_source": "manual" if overridden else "content",
        "doc_type_overridden": overridden,
        "classification": {"doc_type": doc_type, "confidence": conf,
                           "source": "manual" if overridden else "content"},
        "text": text if text is not None else _DEC_TEXT.format(name=name or ""),
        "facts": facts, "flags": {},
        "low_confidence_tokens": list(low_tokens),
        "manual_confirmation_required": list(manual),
    }
    if supporting:
        d["supporting_only"] = True
    return d


def _narrative(name="Berger Owner of Choice Electric", **kw):
    """The 17 Oct handwritten narrative as stored: typed narrative at LOW confidence,
    kept as supporting only, OCR unsure of 19 of its 62 words."""
    kw.setdefault("conf", "low")
    kw.setdefault("supporting", True)
    kw.setdefault("low_tokens", ["MET", ".", "1M", "ERIC", "WAS", "HAS", "THE", "AND", "FOR",
                                 "OWNS", "TRUCKS", "YEARS", "CREW", "SHOP", "JOBS", "BID",
                                 "WORK", "LOCAL", "BOTH"])
    kw.setdefault("text", "I met with Eric\nBerger owner of Choice Electric\n"
                          + "he runs the crews and bids the local jobs " * 6)
    return _doc("narr", "Choice Electric Narrative .jpeg", "narrative", name, **kw)


# ══ A. A person in a role is not the insured ═════════════════════════════════

# ── A1. Adversarial FIRST: real names that look like a role must stay names ──
_STAY_NAMES = [
    # The orchestrator's list (21 Oct).
    "Owner Operator Trucking LLC", "Partners of Michigan Inc", "President Homes LLC",
    "The Members of X Association", "Principal Financial Group", "Director Supply Co",
    # A plural names a GROUP; an organisation name with "of" carries no person.
    "Bank of America", "University of Michigan", "Knights of Columbus", "Friends of the Library",
    "Sisters of Mercy Health System", "Mercy Health Partners of Michigan",
    "Smith & Partners of Boston LLC", "Owners of Choice Electric",
    "Board of Directors of Riverside Condominium Association", "Office of the President",
    # A role phrase with no PERSON in front of it (a title, or a company named so).
    "Property Manager of Detroit LLC", "Home Owner of America Inc", "Vice President of Sales",
    "Owner of Choice Electric", "General Manager of Choice Electric",
    # A fiduciary capacity IS how a trust or an estate is named on a policy.
    "John Smith Trustee of the Smith Family Trust",
    "Jane Doe, Executor of the Estate of John Doe",
    "Jane Doe Attorney at Law",
    # A sole proprietor is named by his trade name, and a managing agent for an owner.
    "Eric Berger dba Choice Electric",
    "Acme Property Management LLC as agent for Riverside Apartments LLC",
    # A role word without "of / at / for" after it.
    "Agent Orange Pest Control LLC", "Eric Berger, Owner", "Eric Berger Owner Choice Electric",
    # Ordinary names, a heading, a role label, prose.
    "CHOICE ELECTRIC LLC", "J. Smith", "AT&T", "U.S. Steel",
    "Choice Electric LLC is owned by Eric Berger owner of the company",
    "I met with Eric Berger owner of Choice Electric",
    # Review of 21 Oct: a company NAMED "<word> <role> of <words> <legal form>",
    # or with a one-word object, run together with no punctuation.
    "Sterling Operator of Cranes LLC", "Lord Agent of Change LLC", "Grace Manager of Homes LLC",
    "Hope Director of Care Inc", "Pioneer Operator of Wells Inc", "Family Partner of Choice Inc",
    "Eagle Owner of the Year Inc", "Hope Agent of Mercy Foundation",
    "Fellowship Member of Christ Church", "Michigan Secretary of State",
    "Morgan Stanley Principal for Hire", "Liberty Agent for Change", "Kevin Member of the Board",
]


@pytest.mark.parametrize("value", _STAY_NAMES)
def test_a_real_name_is_never_read_as_a_person_in_a_role(value):
    assert NZ.is_person_in_a_role(value) is False


@pytest.mark.parametrize("value", [
    "Owner Operator Trucking LLC", "Partners of Michigan Inc", "President Homes LLC",
    "The Members of X Association", "Principal Financial Group", "Director Supply Co",
    "John Smith Trustee of the Smith Family Trust", "Bank of America",
    "CHOICE ELECTRIC LLC", "Eric Berger dba Choice Electric",
])
def test_the_insured_name_door_keeps_them_names(value):
    assert NZ.is_not_a_party_name(value) is False


# ── A2. The class: a person, his job title, and the organisation he serves ───
_PEOPLE_IN_ROLES = [
    "Berger Owner of Choice Electric",                     # the 17 Oct value, verbatim
    "Eric Berger Owner of Choice Electric",
    "Eric Berger, Owner of Choice Electric LLC",
    "ERIC BERGER - OWNER OF CHOICE ELECTRIC",
    "Eric Berger \u2014 Owner of Choice Electric",
    "Eric Berger \u2013 President at Choice Electric",
    "berger owner of choice electric",
    "Mr. Eric Berger, President of Choice Electric",
    "Eric J. Berger Vice President of Choice Electric",
    "Eric Berger CEO of Choice Electric",
    "Eric Berger, Managing Member of Choice Electric LLC",
    "Eric Berger owner and president of Choice Electric",
    "Eric Berger Owner/Operator at Choice Electric",
    "Eric Berger Co-Owner of Choice Electric",
    "Eric Berger (Owner) of Choice Electric",
    "Jane Smith Office Manager for Choice Electric",
    "Pat Lee, Chief Executive Officer of Acme Inc",
    "Sam Ortiz, Partner at Ortiz & Lane LLP",
    "Eric Berger - Owner of Choice Electric LLC",
    "Dana Kim, General Partner of Kim Holdings LP",
    "Terri Wroblewski Agent for Commercial Risk Solutions",
]


@pytest.mark.parametrize("value", _PEOPLE_IN_ROLES)
def test_a_person_in_a_role_is_not_the_insured(value):
    assert NZ.is_person_in_a_role(value) is True
    assert NZ.is_not_a_party_name(value) is True


@pytest.mark.parametrize("value", [None, "", "   ", 5, 3.2, ["Berger Owner of Choice Electric"],
                                   {"value": "Berger Owner of Choice Electric"}, "of", "Owner of",
                                   "Berger Owner of", "Berger Owner at ,;",
                                   "Al Bo Cy Di Ed Owner of Choice Electric",
                                   " ".join(["word"] * 40) + " owner of Choice Electric"])
def test_malformed_or_edge_values_never_match(value):
    assert NZ.is_person_in_a_role(value) is False


def test_the_door_still_holds_the_older_two_rules():
    for value in ("Certificate Holder", "S.B. MO.", "ACCT. EFF.", "owner", "Co-Owner"):
        assert NZ.is_not_a_party_name(value) is True


# ── A3. The readers: the per-document drop, the merge, the floor ─────────────
def test_the_per_document_drop_removes_the_person_and_nothing_else():
    facts = {"applicant_name": _env("Berger Owner of Choice Electric"),
             "total_revenue": _env("3200000"), "operations_description": _env("Electrical contractor")}
    cleared = ES.drop_non_party_names(facts)
    assert "applicant_name" not in facts
    assert cleared == ["applicant_name='Berger Owner of Choice Electric'"]
    assert _v(facts["total_revenue"]) == "3200000"
    assert _v(facts["operations_description"]) == "Electrical contractor"


@pytest.mark.parametrize("name", ["CHOICE ELECTRIC LLC", "Owner Operator Trucking LLC",
                                  "John Smith Trustee of the Smith Family Trust"])
def test_the_per_document_drop_keeps_a_real_insured(name):
    facts = {"applicant_name": _env(name)}
    assert ES.drop_non_party_names(facts) == []
    assert _v(facts["applicant_name"]) == name


def test_the_merge_keeps_the_other_documents_insured():
    docs = [_doc("auto", "25-26 Business Auto Policy.pdf", name="CHOICE ELECTRIC LLC"),
            _narrative()]
    for primary in (docs[0], docs[1]):
        ds = copy.deepcopy(docs)
        mf, _flags = ES.merge_facts(ds, ds[0] if primary is docs[0] else ds[1])
        assert _v(mf.get("applicant_name")) == "CHOICE ELECTRIC LLC"
        assert "applicant_name" not in ds[1]["facts"], "the per-document copy is cleaned"


def test_the_merge_never_invents_the_insured():
    ds = [_narrative()]
    mf, _flags = ES.merge_facts(ds, ds[0])
    assert not _v(mf.get("applicant_name"))


def test_the_merged_floor_drops_a_person_in_a_role():
    mf = {"applicant_name": _env("Eric Berger, Owner of Choice Electric LLC"),
          "named_insured": "Kevin Lee, Member of the Board", "dba_name": _env("Choice Electric")}
    ES._strip_non_value_facts(mf)
    assert "applicant_name" not in mf and "named_insured" not in mf
    assert _v(mf["dba_name"]) == "Choice Electric"


def test_the_merge_vote_skips_a_person_in_a_role():
    """Inside one document's chunk partials the real name wins the vote, instead of
    a person-in-a-role being elected and then blanked."""
    src = (BACKEND / "services" / "extraction_service.py").read_text(encoding="utf-8")
    body = src[src.index("def _merge_list_fields("):]
    body = body[:body.index("\ndef ", 10)]
    assert "k in _INSURED_KEYS and _not_insured(sval)" in body


# ── A4. A stored document still holding the person (stored before this fix) ──
def test_a_stored_person_in_a_role_raises_no_identity_conflict():
    docs = [_doc("auto", "auto.pdf", name="CHOICE ELECTRIC LLC"),
            _narrative(supporting=False, conf="high", low_tokens=())]
    docs[1]["doc_type"] = "dec_page"          # even a "verified" document's misread
    issues = check_doc_consistency(docs)
    assert not any("name_conflict" in i for i in issues)
    uw = assess_underwriting_consistency(docs, {"applicant_name": _env("CHOICE ELECTRIC LLC")}, {}, flags={})
    field = next((f for f in uw["fields"] if f["fact_key"] == "applicant_name"), None)
    assert field is None or field["status"] != "conflict"
    r = assess_submission_integrity(docs)
    assert r["status"] != "low"
    assert (r.get("signals") or {}).get("distinct_applicant_names") == 1


# ══ B. Verified sources only ═════════════════════════════════════════════════

# ── B1. The ONE definition ────────────────────────────────────────────────────
@pytest.mark.parametrize("doc_type", sorted(DT.VERIFIED_SOURCE_TYPES))
def test_formal_paperwork_typed_with_confidence_is_verified(doc_type):
    assert DT.is_verified_source(_doc("d", "d.pdf", doc_type, "ACME LLC")) is True
    assert DT.unverified_reasons(_doc("d", "d.pdf", doc_type, "ACME LLC")) == []


def test_the_verified_types_are_placement_paperwork_and_issued_records():
    """The cut line already in the code - the types `select_primary_truth` prefers,
    ahead of the first schedule / supporting type - plus the two records a carrier
    or a rating bureau issues about its insured. A new primary type, or a new
    document type at all, fails here until someone decides which side it is on."""
    from services.extraction_service import _DOC_TYPE_PRIORITY, ALLOWED_DOC_TYPES
    head = _DOC_TYPE_PRIORITY[:_DOC_TYPE_PRIORITY.index("sov")]
    assert set(head) | {"loss_run", "emod_worksheet"} == set(DT.VERIFIED_SOURCE_TYPES)
    decided = set(DT.VERIFIED_SOURCE_TYPES) | {
        "narrative", "unknown", "schedule", "sov", "vehicle_schedule", "driver_schedule",
        "equipment_schedule", "location_schedule", "payroll_report", "financial_statement",
        "handbook", "safety_manual", "cope_report", "gross_sales_report"}
    assert set(ALLOWED_DOC_TYPES) == decided


@pytest.mark.parametrize("doc_type", ["narrative", "unknown", "schedule", "sov",
                                      "vehicle_schedule", "driver_schedule", "payroll_report",
                                      "financial_statement", "handbook", "safety_manual",
                                      "cope_report", "gross_sales_report"])
def test_supporting_paper_is_not_verified(doc_type):
    d = _doc("d", "d.pdf", doc_type, "ACME LLC")
    assert DT.is_verified_source(d) is False
    assert DT.UNVERIFIED_TYPE in DT.unverified_reasons(d)


@pytest.mark.parametrize("conf,word", [("medium", "Needs Verification"), ("low", "Unable to Classify")])
def test_an_unsure_type_is_not_verified(conf, word):
    d = _doc("d", "wc.pdf", "dec_page", "ACME LLC", conf=conf)
    assert DT.unverified_reasons(d) == [DT.UNVERIFIED_TYPE_CONFIDENCE]
    assert word in DT.describe_unverified(d)


def test_a_type_the_producer_set_is_verified():
    d = _doc("d", "wc.pdf", "dec_page", "ACME LLC", conf="medium", overridden=True)
    assert DT.is_verified_source(d) is True
    # ...but setting a narrative's type to "narrative" does not make it paperwork
    n = _doc("n", "n.pdf", "narrative", "ACME LLC", overridden=True)
    assert DT.unverified_reasons(n) == [DT.UNVERIFIED_TYPE]


def test_supporting_only_is_not_verified():
    d = _doc("d", "d.pdf", "dec_page", "ACME LLC", supporting=True)
    assert DT.unverified_reasons(d) == [DT.UNVERIFIED_SUPPORTING]


def test_a_low_ocr_reading_is_unverified_for_that_fact_only():
    d = _doc("d", "d.png", "dec_page", "ACME LLC", fein="84-2210987", name_conf="ai_low")
    assert DT.unverified_reasons(d, "applicant_name") == [DT.UNVERIFIED_OCR]
    assert DT.is_verified_source(d, "fein") is True
    assert DT.is_verified_source(d) is True
    m = _doc("m", "m.png", "dec_page", "ACME LLC", fein="84-2210987", manual=["fein"])
    assert DT.unverified_reasons(m, "fein") == [DT.UNVERIFIED_OCR]
    assert DT.is_verified_source(m, "applicant_name") is True


def test_a_poorly_read_image_is_unverified_for_every_fact():
    words = "certificate of liability insurance acme llc producer " * 10       # 70 words
    shaky = _doc("s", "coi.png", "certificate", "ACME LLC", text=words,
                 low_tokens=["ACME", "INSURED", "OF"])                         # 3 / 70 > 2%
    assert DT.unverified_reasons(shaky, "applicant_name") == [DT.UNVERIFIED_OCR]
    sure = _doc("t", "coi.png", "certificate", "ACME LLC", text=words, low_tokens=["OF"])  # 1.4%
    assert DT.is_verified_source(sure, "applicant_name") is True
    flagged = _doc("u", "coi.png", "certificate", "ACME LLC", text=words * 50,
                   low_tokens=["needs_manual_review"])
    assert DT.unverified_reasons(flagged) == [DT.UNVERIFIED_OCR]


def test_a_pdf_with_a_few_shaky_tokens_stays_verified():
    """Measured 21 Oct: every stored PDF sits at or under 0.2% low-confidence words."""
    d = _doc("d", "auto.pdf", "dec_page", "CHOICE ELECTRIC LLC",
             text="BUSINESS AUTO DECLARATIONS " * 1300, low_tokens=[".", "81", "MR"])
    assert DT.is_verified_source(d, "applicant_name") is True


def test_the_17_oct_narrative_is_unverified_four_ways():
    reasons = DT.unverified_reasons(_narrative(), "applicant_name")
    assert reasons == [DT.UNVERIFIED_TYPE, DT.UNVERIFIED_TYPE_CONFIDENCE,
                       DT.UNVERIFIED_SUPPORTING, DT.UNVERIFIED_OCR]
    assert DT.describe_unverified(_narrative(), "applicant_name") == (
        "Choice Electric Narrative .jpeg (Underwriting Narrative, Unable to Classify, "
        "supporting document, low OCR confidence)")


@pytest.mark.parametrize("doc", [None, "x", 5, [], {}, {"doc_type": None}, {"doc_type": ""},
                                 {"doc_type": "dec_page", "doc_type_confidence": None},
                                 {"doc_type": "coi"}, {"doc_type": "declarations",
                                                       "doc_type_confidence": "high"},
                                 {"doc_type": "dec_page", "facts": "junk", "text": None,
                                  "low_confidence_tokens": "junk"}])
def test_a_record_without_signals_is_judged_on_what_it_carries(doc):
    """Absence is not evidence: an older record (no confidence, no type) is not
    called unverified for what it never recorded."""
    assert DT.unverified_reasons(doc, "applicant_name") == []
    assert DT.is_verified_source(doc, "applicant_name") is True


# ── B2. The identity hard stop (check_doc_consistency) ───────────────────────
_HARD_NAME = ("[hard_stop] code=name_conflict Applicant name differs across documents: "
              "CHOICE ELECTRIC LLC, HARBORLINE PLUMBING LLC (Source: a_dec.pdf, b_dec.pdf. "
              "Fix: Confirm the correct value in the Data Consistency section below.)")
_HARD_FEIN = ("[hard_stop] code=fein_conflict FEIN differs across uploaded documents. "
              "Submission Quality Score (SQS) is capped at 60 until this is confirmed. "
              "(Source: a_dec.pdf, b_dec.pdf. Fix: Confirm the correct value in the Data "
              "Consistency section below.)")


def _two(b_kwargs=None):
    a = _doc("a", "a_dec.pdf", name="CHOICE ELECTRIC LLC", fein="84-2210987")
    b = _doc("b", "b_dec.pdf", name="HARBORLINE PLUMBING LLC", fein="91-4478123", **(b_kwargs or {}))
    return [a, b]


def test_two_verified_documents_naming_different_companies_stay_a_hard_stop():
    issues = check_doc_consistency(_two())
    assert _HARD_NAME in issues and _HARD_FEIN in issues     # byte-identical to before


@pytest.mark.parametrize("b_kwargs", [
    {"doc_type": "narrative"}, {"conf": "medium"}, {"conf": "low"}, {"supporting": True},
    {"name_conf": "ai_low", "fein_conf": "ai_low"}, {"manual": ["applicant_name", "fein"]},
])
def test_an_unverified_side_makes_it_a_warning_to_confirm(b_kwargs):
    issues = check_doc_consistency(_two(b_kwargs))
    name = [i for i in issues if "code=name_conflict" in i]
    fein = [i for i in issues if "code=fein_conflict" in i]
    assert len(name) == 1 and len(fein) == 1
    assert name[0].startswith("[warning] code=name_conflict ")
    assert fein[0].startswith("[warning] code=fein_conflict ")
    # The hard sentence, then the note - so a card stored as a hard stop renders as
    # the warning the fresh run says it is (`issue_registry._listed_in`).
    assert name[0][len("[warning] code=name_conflict "):].startswith(
        _HARD_NAME[len("[hard_stop] code=name_conflict "):] + " Unverified source: b_dec.pdf (")
    assert fein[0][len("[warning] code=fein_conflict "):].startswith(
        _HARD_FEIN[len("[hard_stop] code=fein_conflict "):] + " Unverified source: b_dec.pdf (")
    assert "91-4478123" not in fein[0], "a FEIN is never printed in this sentence"


def test_two_verified_agreeing_and_one_unverified_differing_is_a_warning():
    docs = _two()
    docs[1]["facts"]["applicant_name"] = _env("CHOICE ELECTRIC LLC")
    docs[1]["facts"]["fein"] = _env("84-2210987")
    docs.append(_doc("c", "Narrative.jpeg", "narrative", "HARBORLINE PLUMBING LLC", fein="91-4478123"))
    issues = check_doc_consistency(docs)
    name = next(i for i in issues if "code=name_conflict" in i)
    assert name.startswith("[warning]")
    assert name.endswith(" Unverified source: Narrative.jpeg (Underwriting Narrative).")


def test_two_verified_disagreeing_stay_hard_whatever_else_is_uploaded():
    docs = _two() + [_narrative(name="CHOICE ELECTRIC LLC")]
    assert any(i.startswith("[hard_stop] code=name_conflict") for i in check_doc_consistency(docs))


def test_only_unverified_documents_disagreeing_is_a_warning():
    docs = [_doc("x", "x.jpeg", "narrative", "CHOICE ELECTRIC LLC"),
            _doc("y", "y.pdf", "financial_statement", "HARBORLINE PLUMBING LLC")]
    name = next(i for i in check_doc_consistency(docs) if "code=name_conflict" in i)
    assert name.startswith("[warning]")
    assert name.endswith(" Unverified sources: x.jpeg (Underwriting Narrative); "
                         "y.pdf (Financial Statements).")


def test_a_carriers_loss_run_naming_another_company_stays_a_hard_stop():
    docs = [_doc("a", "a_dec.pdf", name="CHOICE ELECTRIC LLC"),
            _doc("l", "loss_run.pdf", "loss_run", "RIVERSIDE LANDSCAPING INC")]
    assert any(i.startswith("[hard_stop] code=name_conflict") for i in check_doc_consistency(docs))
    assert assess_submission_integrity(docs)["status"] == "low"


def _beta_test_1_kit():
    """Beta Test 1 (the package Submission Integrity was built for), as stored."""
    return [_doc("wba", "WBA_DecPage.pdf", name="Women's Bar Association", fein="56-1234567"),
            _doc("wake", "WakeCounty_Narrative.pdf", "narrative", "Wake County"),
            _doc("abc", "CompanyABC_LossRun.pdf", "loss_run", "Company ABC", fein="20-7654321")]


def test_the_beta_test_1_kit_still_pauses_and_still_hard_stops():
    docs = _beta_test_1_kit()
    r = assess_submission_integrity(docs)
    assert r["status"] == "low" and r["review_required"] is True
    assert r["reasons"][0] == ("Documents reference multiple distinct applicants/insureds: "
                               "Women's Bar Association, Wake County, Company ABC")
    issues = check_doc_consistency(docs)
    assert any(i.startswith("[hard_stop] code=name_conflict") for i in issues)
    assert any(i.startswith("[hard_stop] code=fein_conflict") for i in issues)


def test_a_confirmed_name_is_settled_either_way():
    assert not any("name_conflict" in i for i in check_doc_consistency(_two(), {"applicant_name"}))
    assert not any("name_conflict" in i for i in check_doc_consistency(
        _two({"doc_type": "narrative"}), {"applicant_name"}))


def test_the_warning_splits_into_the_soft_list_with_its_code():
    hard, soft, _info, conflicts = split_doc_consistency_issues(
        check_doc_consistency(_two({"doc_type": "narrative"})))
    assert not hard
    assert {c["code"] for c in conflicts} == {"name_conflict", "fein_conflict"}
    assert not any(c["hard_stop"] for c in conflicts)
    assert len(soft) == 2


# ── B3. The Data Consistency picker's blocking decision ──────────────────────
def _uw(docs):
    return assess_underwriting_consistency(
        docs, {"applicant_name": _env("CHOICE ELECTRIC LLC"), "fein": _env("84-2210987")}, {}, flags={})


def test_the_picker_blocks_on_two_verified_documents():
    docs = _two()
    rows = {k: (m, b) for k, m, b in SN.underwriting_conflict_stops(_uw(docs), {}, docs)}
    assert rows["applicant_name"] == (
        "Applicant / Named Insured: documents disagree (CHOICE ELECTRIC LLC, HARBORLINE "
        "PLUMBING LLC). Fix: Confirm the correct value to apply it across forms.", True)
    assert rows["fein"][1] is True


def test_the_picker_does_not_block_on_an_unverified_source():
    docs = _two({"doc_type": "narrative", "conf": "low", "supporting": True})
    rows = {k: (m, b) for k, m, b in SN.underwriting_conflict_stops(_uw(docs), {}, docs)}
    msg, blocking = rows["applicant_name"]
    assert blocking is False
    assert msg == ("Applicant / Named Insured: documents disagree (CHOICE ELECTRIC LLC, HARBORLINE "
                   "PLUMBING LLC). Fix: Confirm the correct value to apply it across forms. "
                   "Unverified source: b_dec.pdf (Underwriting Narrative, Unable to Classify, "
                   "supporting document).")
    assert rows["fein"][1] is False


def test_without_documents_the_picker_keeps_todays_answer():
    docs = _two({"doc_type": "narrative"})
    rows = {k: b for k, _m, b in SN.underwriting_conflict_stops(_uw(docs), {})}
    assert rows["applicant_name"] is True


def test_a_clients_typed_name_is_verified_information():
    uw = {"review_required": True, "fields": [{
        "fact_key": "applicant_name", "label": "Applicant / Named Insured", "review_required": True,
        "values": [
            {"display": "CHOICE ELECTRIC LLC", "sources": [{"doc_id": "a", "source_method": "llm"}]},
            {"display": "CHOICE ELECTRIC INC", "sources": [{"doc_id": "client_questionnaire",
                                                           "source_method": "client_answer"}]}]}]}
    (_k, _m, blocking), = SN.underwriting_conflict_stops(uw, {}, _two())
    assert blocking is True


def test_an_unknown_source_document_is_not_called_unverified():
    uw = {"review_required": True, "fields": [{
        "fact_key": "applicant_name", "label": "Applicant / Named Insured", "review_required": True,
        "values": [{"display": "A LLC", "sources": [{"doc_id": "gone1"}]},
                   {"display": "B LLC", "sources": [{"doc_id": "gone2"}]}]}]}
    (_k, _m, blocking), = SN.underwriting_conflict_stops(uw, {}, _two())
    assert blocking is True


def test_a_non_identity_field_is_untouched():
    uw = {"review_required": True, "fields": [{
        "fact_key": "total_revenue", "label": "Gross Sales", "review_required": True,
        "values": [{"display": "$1", "sources": [{"doc_id": "a"}]},
                   {"display": "$2", "sources": [{"doc_id": "b"}]}]}]}
    (_k, msg, blocking), = SN.underwriting_conflict_stops(uw, {}, _two({"doc_type": "narrative"}))
    assert blocking is False and "Unverified" not in msg


# ── B4. The stops door, the blockers, the cards ──────────────────────────────
def _session(docs):
    return {"docs": docs, "facts": {"applicant_name": _env("CHOICE ELECTRIC LLC")}, "flags": {},
            "underwriting_consistency": _uw(docs), "underwriting_confirmations": {},
            "recommendations": []}


def _identity(msgs):
    """The identity-conflict sentences (both engines), nothing else a sparse fixture raises."""
    return [m for m in msgs if ("Applicant" in m or "FEIN" in m)
            and ("differs across" in m or "documents disagree" in m)]


def test_stops_now_hard_on_verified_soft_on_unverified():
    verified = SN.stops_now(_session(_two()), pre_form=True)
    assert len(_identity(verified["hard"])) == 4 and not _identity(verified["soft"])
    unverified = SN.stops_now(_session(_two({"doc_type": "narrative"})), pre_form=True)
    assert not _identity(unverified["hard"])
    assert len(_identity(unverified["soft"])) == 4
    assert not _identity(unverified["form_hard"])


def test_an_unverified_conflict_never_blocks_submission_ready():
    s = _session(_two({"doc_type": "narrative"}))
    blockers, _cards = one_blocker_per_conflict(SN.stops_now(s, pre_form=True)["hard"], s)
    assert not _identity(blockers)


def test_the_cards_follow_the_stops():
    s = _session(_two({"doc_type": "narrative"}))
    cards = SN.conflict_stop_issues(s)
    codes = {c["code"] for c in cards}
    assert "doc_conflict_warn_name_conflict" in codes and "doc_conflict_hard_name_conflict" not in codes
    picker = next(c for c in cards if c["code"] == "underwriting_reconciliation_applicant_name")
    assert picker["message"].endswith("(Underwriting Narrative).")
    hard, soft = doc_consistency_stops(s)
    assert not _identity(hard) and len(_identity(soft)) == 2


def test_a_card_stored_as_a_hard_stop_renders_as_the_warning():
    """A session stored before this build keeps its hard-stop card copies; the
    fresh sentence carries the old one as its prefix, so the row draws at the
    severity the stops door now gives it - no stale red row, no re-run needed."""
    s = _session(_two({"doc_type": "narrative"}))
    soft = SN.stops_now(s, pre_form=True)["soft"]
    old_doc_card = {"code": "doc_conflict_hard_name_conflict", "type": "hard_stop",
                    "message": _HARD_NAME[len("[hard_stop] code=name_conflict "):]}
    old_picker_card = {"code": "underwriting_reconciliation_applicant_name", "type": "hard_stop",
                       "message": "Applicant / Named Insured: documents disagree (CHOICE ELECTRIC LLC, "
                                  "HARBORLINE PLUMBING LLC). Fix: Confirm the correct value to apply "
                                  "it across forms."}
    assert _display_severity(old_doc_card, [], soft) == "soft_warning"
    assert _display_severity(old_picker_card, [], soft) == "soft_warning"


# ── B5. Submission Integrity's "different insured" ───────────────────────────
def test_two_verified_insureds_still_pause_the_package():
    r = assess_submission_integrity(_two())
    assert r["status"] == "low" and r["review_required"] is True
    assert r["reasons"] == ["Documents reference multiple distinct applicants/insureds: "
                            "CHOICE ELECTRIC LLC, HARBORLINE PLUMBING LLC",
                            "2 distinct FEINs found across documents"]


def test_an_unverified_different_insured_is_a_review_note_not_a_pause():
    r = assess_submission_integrity(_two({"doc_type": "narrative"}))
    assert r["status"] == "medium" and r["review_required"] is False
    assert any(x.startswith("Only an unverified source names a different insured: HARBORLINE "
                            "PLUMBING LLC - b_dec.pdf (Underwriting Narrative)")
               for x in r["reasons"])
    assert any(x.startswith("Only an unverified source gives a different FEIN - b_dec.pdf")
               for x in r["reasons"])
    # The documents list still sees whose document it is (the tag stays).
    assert len(r["clusters"]) == 2
    flags = {e["doc_id"]: e["identity_verified"] for e in r["documents"]}
    assert flags == {"a": True, "b": False}


def test_only_unverified_documents_naming_two_insureds_is_a_review_note():
    docs = [_doc("x", "x.jpeg", "narrative", "CHOICE ELECTRIC LLC"),
            _doc("y", "y.pdf", "financial_statement", "HARBORLINE PLUMBING LLC")]
    r = assess_submission_integrity(docs)
    assert r["status"] == "medium" and not r["review_required"]
    assert r["reasons"][0] == (
        "Unverified sources name more than one insured: CHOICE ELECTRIC LLC - x.jpeg "
        "(Underwriting Narrative); HARBORLINE PLUMBING LLC - y.pdf (Financial Statements). "
        "Confirm which insured this submission is for.")


def test_a_verified_cluster_beside_an_unverified_one_of_the_same_name_is_one_insured():
    docs = [_doc("a", "a.pdf", name="CHOICE ELECTRIC LLC"),
            _doc("n", "n.jpeg", "narrative", "Choice Electric LLC")]
    r = assess_submission_integrity(docs)
    assert r["status"] != "low" and r["signals"]["distinct_applicant_names"] == 1


def test_the_17_oct_package_has_no_identity_stop_at_all():
    """Seven declarations (as stored: six Highly Confident, the WC dec Needs
    Verification) and the handwritten narrative."""
    names = {"auto": "CHOICE ELECTRIC LLC", "umb": "CHOICE ELECTRIC LLC"}
    docs = [_doc(k, f"25-26 {t}.pdf", name=names.get(k), conf=("medium" if k == "wc" else "high"))
            for k, t in (("auto", "Business Auto Policy"), ("cyber", "Cyber Policy"),
                         ("epl", "Employment Practices Liability Policy"),
                         ("exc", "Excess Umbrella Policy"), ("pkg", "Package Policy"),
                         ("umb", "Umbrella Policy"), ("wc", "Workers Compensation Policy"))]
    docs.append(_narrative())
    assert not any("name_conflict" in i for i in check_doc_consistency(copy.deepcopy(docs)))
    s = _session(copy.deepcopy(docs))
    assert not _identity(SN.stops_now(s, pre_form=True)["hard"])
    assert assess_submission_integrity(copy.deepcopy(docs))["status"] != "low"
    # Had the narrative named a genuinely different company: a warning, never 60.
    docs[-1]["facts"]["applicant_name"] = _env("HARBORLINE PLUMBING LLC")
    s = _session(copy.deepcopy(docs))
    out = SN.stops_now(s, pre_form=True)
    assert not _identity(out["hard"]) and _identity(out["soft"])


# ── B6. The Documents list's applicant: verified documents decide ────────────
def _integrity_record(entries, clusters):
    return {"documents": entries, "clusters": clusters}


def test_a_verified_group_outranks_a_larger_unverified_group():
    rec = _integrity_record(
        [{"doc_id": "a", "applicant": "CHOICE ELECTRIC LLC", "identity_verified": True},
         {"doc_id": "x", "applicant": "HARBORLINE PLUMBING LLC", "identity_verified": False},
         {"doc_id": "y", "applicant": "HARBORLINE PLUMBING LLC", "identity_verified": False}],
        [{"label": "CHOICE ELECTRIC LLC", "doc_ids": ["a"]},
         {"label": "HARBORLINE PLUMBING LLC", "doc_ids": ["x", "y"]}])
    assert DT.package_applicant(rec)["name"] == "CHOICE ELECTRIC LLC"
    st = DT.document_insured_statuses(rec)
    assert st["a"]["state"] == "same" and st["x"]["state"] == "different"


def test_an_older_record_without_the_mark_ranks_as_before():
    rec = _integrity_record(
        [{"doc_id": "a", "applicant": "CHOICE ELECTRIC LLC"},
         {"doc_id": "x", "applicant": "HARBORLINE PLUMBING LLC"},
         {"doc_id": "y", "applicant": "HARBORLINE PLUMBING LLC"}],
        [{"label": "CHOICE ELECTRIC LLC", "doc_ids": ["a"]},
         {"label": "HARBORLINE PLUMBING LLC", "doc_ids": ["x", "y"]}])
    assert DT.package_applicant(rec)["name"] == "HARBORLINE PLUMBING LLC"


def test_a_confirmed_applicant_still_wins():
    rec = _integrity_record(
        [{"doc_id": "a", "applicant": "CHOICE ELECTRIC LLC", "identity_verified": True},
         {"doc_id": "x", "applicant": "HARBORLINE PLUMBING LLC", "identity_verified": False}],
        [{"label": "CHOICE ELECTRIC LLC", "doc_ids": ["a"]},
         {"label": "HARBORLINE PLUMBING LLC", "doc_ids": ["x"]}])
    got = DT.package_applicant(rec, {"applicant_name": "HARBORLINE PLUMBING LLC"})
    assert got["name"] == "HARBORLINE PLUMBING LLC" and got["source"] == "confirmed"


def test_the_live_integrity_record_carries_the_mark():
    """The narrative uploaded FIRST: today's tie-break (the earliest document) would
    make its insured the package's; the verified declarations decide instead."""
    r = assess_submission_integrity(_two({"doc_type": "narrative"})[::-1])
    assert DT.package_applicant(r)["name"] == "CHOICE ELECTRIC LLC"


# ── B7. ONE definition: every identity stop reads the same door ──────────────
@pytest.mark.parametrize("module,func", [
    ("sqs_service", "check_doc_consistency"),
    ("stops_now", "underwriting_conflict_stops"),
    ("submission_integrity", "_doc_identity"),
])
def test_every_identity_stop_reads_the_one_definition(module, func):
    src = (BACKEND / "services" / f"{module}.py").read_text(encoding="utf-8")
    tree = ast.parse(src)
    node = next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == func)
    body = ast.get_source_segment(src, node)
    assert "document_tags import" in body and "verified" in body


def test_no_second_list_of_verified_types():
    for path in (BACKEND / "services").glob("*.py"):
        if path.name == "document_tags.py":
            continue
        text = path.read_text(encoding="utf-8")
        assert "VERIFIED_SOURCE_TYPES = " not in text, path.name


@pytest.mark.parametrize("module", ["extraction_pipeline", "stops_now"])
def test_every_production_caller_passes_its_documents_to_the_picker_stops(module):
    """Without the documents the picker's stop cannot judge its sources and keeps
    today's answer - so no production caller may leave them out."""
    src = (BACKEND / "services" / f"{module}.py").read_text(encoding="utf-8")
    calls = [n for n in ast.walk(ast.parse(src)) if isinstance(n, ast.Call)
             and getattr(n.func, "id", getattr(n.func, "attr", None)) == "underwriting_conflict_stops"]
    assert calls, module
    for call in calls:
        assert len(call.args) + len(call.keywords) == 3, ast.get_source_segment(src, call)


# ── B8. After forms: an UNVERIFIED other-insured document still only suggests ─
def test_an_unverified_other_insured_document_added_after_forms_writes_nothing():
    """It no longer pauses (MEDIUM), but the integrity record the documents door
    persists still carries its entry, so the Documents list calls it another
    insured's and its AI reading writes no box - suggestions only."""
    from services import session_documents as SDM
    narr = _doc("new", "harborline_narrative.pdf", "narrative", "HARBORLINE PLUMBING LLC")
    docs = [_doc("a", "auto.pdf", name="CHOICE ELECTRIC LLC"),
            _doc("u", "umb.pdf", name="CHOICE ELECTRIC LLC"), narr]
    verdict = assess_submission_integrity(docs)
    assert verdict["status"] == "medium" and not verdict["review_required"]
    plan = SDM.integrity_plan({}, docs, confirm_same_insured=False, user_id="u1")
    assert plan["review_needed"] is False
    session = {"docs": docs, "integrity": plan["verdict"]}
    another = SDM.names_another_insured(session, [narr])
    assert another and another["name"] == "HARBORLINE PLUMBING LLC"
    fill = SDM.plan_form_fill("ACORD_125", {}, {"NamedInsured_FullName_A": "HARBORLINE PLUMBING LLC"},
                              {"NamedInsured_FullName_A": "ai_verified"}, {},
                              other_insured=another["name"])
    assert fill["fills"] == {}
