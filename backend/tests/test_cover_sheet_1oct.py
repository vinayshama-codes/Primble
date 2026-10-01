"""The Submission Brief / cover page, fixed from the owner's own sheet (1 Oct 2026).

The owner's Submission Brief for session 8739a72a printed:
  * "77/100  B  Needs Work" - the package score with the FIRST FORM's grade (81 -> B);
    the app shows 77 as C;
  * "priority_review" - the scorer's routing CODE, in the table and in the AI summary;
  * "ANNUAL REVENUE 300000";
  * a summary saying the flags suggest no subcontractors, on a package whose GL rates
    subcontracted work (class 91585) - the model read `asserts_no_subcontractors:
    False` ("the documents do not say none") as "none";
  * a hidden carrier-AI (A2A) block WRITTEN BY THE MODEL, asked for a FEIN and a NAICS
    code it was never given.
"""
from __future__ import annotations

import asyncio
import inspect
import io
import json

import pytest

import routes.download_routes as dr
import services.cover_service as cs
from services.sqs_service import tier_for_score


_FACTS = {
    "applicant_name": {"value": "ORBIN CONTRACTING LLC", "source": "ai"},
    "total_revenue": {"value": "300000", "source": "client_arq"},
    "effective_date": {"value": "07/15/2026", "source": "derived"},
    "expiration_date": {"value": "07/15/2027", "source": "producer"},
    "entity_type": "LLC",
    "prior_carrier": {"value": "EMPLOYERS MUTUAL CASUALTY COMPANY / EMC Property & Casualty Company",
                      "source": "derived"},
    "coverage_lines": [
        {"line": "Liability", "carrier": "EMC Property & Casualty Company",
         "policy_number": "BBC7263 - 26", "premium": "$3,954.00"},
        {"line": "Automobile", "carrier": "EMPLOYERS MUTUAL CASUALTY COMPANY",
         "policy_number": "6E7-40-02---26", "premium": "$2,991.00"},
        {"line": "Commercial Liability Umbrella", "carrier": "Employers Mutual Casualty Company",
         "policy_number": "6J7-40-02---26", "premium": None},
    ],
    "gl_class_code_schedule": [
        {"class_code": "91580", "classification": "Contractors - Executive Supervisors or Executive Superintendents",
         "premium_basis": "Payroll", "exposure_amount": "$39,300"},
        {"class_code": "91585", "classification": "Contractors - subcontracted work - in connection with construction",
         "premium_basis": "Cost", "exposure_amount": "$350,000"},
    ],
    "fein": {"value": "84-0000000", "source": "client_arq"},
}
_FLAGS = {"is_contractor": True, "no_prior_losses": True, "asserts_no_subcontractors": False,
          "asserts_no_known_losses": False, "has_loss_history": False, "_internal": True}
_PKG_SQS = {"sqs_score": 77, "grade": "B", "tier": "Needs Work", "routing_decision": "priority_review"}


# ── the small doors ──────────────────────────────────────────────────────────

def test_routing_prints_in_words_never_a_code():
    assert cs.routing_label("priority_review") == "Priority review"
    assert cs.routing_label("standard_review") == "Standard review"
    assert cs.routing_label("auto_quote") == "Auto-quote"
    assert cs.routing_label("hold") == "Hold"
    assert cs.routing_label("some_new_code") == "Some new code"       # never raw
    assert cs.routing_label(None) == cs._COVER_UNKNOWN


def test_grade_and_tier_come_from_the_apps_ladder():
    for score in (0, 59, 60, 69, 70, 77, 79, 80, 89, 90, 100):
        g, t, _c = tier_for_score(score)
        assert cs.grade_and_tier(score) == (g, t)
    assert cs.grade_and_tier(77) == ("C", "Needs Work")


@pytest.mark.parametrize("raw,shown", [
    ("300000", "$300,000"), ("$1,200,000.00", "$1,200,000"), ("300000.5", "$300,000.50"),
    ("$ 3,954", "$3,954"), ("Included", "Included"), ("", ""),
])
def test_money_prints_like_the_forms(raw, shown):
    assert cs._money(raw) == shown


def test_companies_print_as_the_forms_spell_them():
    assert cs._as_the_forms_print(
        "EMPLOYERS MUTUAL CASUALTY COMPANY / EMC Property & Casualty Company", _FACTS) == \
        "Employers Mutual Casualty Company / EMC Property & Casualty Company"
    # a company the documents print only in capitals keeps its printing
    assert cs._as_the_forms_print("ACME CASUALTY", _FACTS) == "ACME CASUALTY"


def test_only_true_flags_reach_the_model():
    assert cs._true_flags(_FLAGS) == ["is_contractor", "no_prior_losses"]
    assert "91585 Contractors - subcontracted work" in cs._gl_classifications(_FACTS)


def test_the_info_table_formats_revenue_and_carriers():
    info = cs._cover_info_values(_FACTS, _FLAGS, {"full_name": "vinay sharma"}, "Astrea It services")
    assert info["revenue"] == "$300,000"
    assert info["prior_carrier"] == "Employers Mutual Casualty Company / EMC Property & Casualty Company"


# ── the two AI summaries: what the model is told, and the A2A block ─────────

class _Model:
    def __init__(self):
        self.prompts = []

    async def __call__(self, _model, messages, max_tokens=None):
        self.prompts.append(messages[0]["content"])
        # a model that still tries to write the A2A block - it must be ignored
        return json.dumps({"narrative": "N.", "sqs_reasoning": "R.",
                           "ai_block": {"fein": "12-3456789", "sqs_grade": "B"}})


@pytest.fixture
def model(monkeypatch):
    m = _Model()
    monkeypatch.setattr(cs, "groq_chat", m)

    async def _no_cache(_k):
        return None

    async def _set(_k, _v):
        return None
    monkeypatch.setattr(cs, "_cache_get", _no_cache)
    monkeypatch.setattr(cs, "_cache_set", _set)
    return m


def test_the_brief_tells_the_model_the_truth(model):
    out = asyncio.run(cs.generate_lite_cover_narrative(
        facts=_FACTS, flags=_FLAGS, sqs=_PKG_SQS, hard_stops=[],
        soft_stops=["Driver schedule not provided"], org_name="Astrea It services",
        user={"full_name": "vinay sharma"}))
    prompt = model.prompts[0]
    assert "SQS Score: 77/100 (Grade: C, Tier: Needs Work, Routing: Priority review)" in prompt
    assert "Revenue: $300,000" in prompt
    assert "91585 Contractors - subcontracted work" in prompt
    assert "asserts_no_subcontractors" not in prompt and "priority_review" not in prompt
    assert "ai_block" not in prompt and "exactly two keys" in prompt
    block = out["ai_block"]
    assert block["sqs_scores"] == [{"form": "Pre-Submission Analysis", "score": 77, "grade": "C",
                                    "tier": "Needs Work", "routing": "Priority review"}]
    assert "fein" not in block and "naics_code" not in block
    assert block["risk_flags"] == ["is_contractor", "no_prior_losses"]
    assert block["total_revenue"] == "$300,000" and block["report_type"] == "lite_pre_submission"
    assert out["narrative"] == "N." and out["sqs_reasoning"] == "R."


def test_the_package_cover_tells_the_model_the_truth(model):
    results = {"ACORD_125": {"sqs_score": 81, "grade": "B", "routing_decision": "priority_review",
                             "soft_stops": ["Driver schedule not provided"]},
               "ACORD_131": {"sqs_score": 85, "grade": "B", "routing_decision": "auto_quote"}}
    out = asyncio.run(cs.generate_ai_cover_narrative(
        facts=_FACTS, flags=_FLAGS, sqs_results=results, form_ids=["ACORD_125", "ACORD_131"],
        org_name="Astrea It services", user={"full_name": "vinay sharma"}, package_score=77))
    prompt = model.prompts[0]
    assert '"routing": "Priority review"' in prompt and "priority_review" not in prompt
    assert "Revenue: $300,000" in prompt
    assert "Prior Carrier: Employers Mutual Casualty Company / EMC Property & Casualty Company" in prompt
    assert "ai_block" not in prompt and "fein" not in prompt
    block = out["ai_block"]
    assert block["package_sqs"] == {"score": 77, "grade": "C", "tier": "Needs Work"}
    assert [s["grade"] for s in block["sqs_scores"]] == ["B", "B"]
    assert block["soft_stops"] == ["Driver schedule not provided"]
    assert "fein" not in block


def _pdf_text(pdf_bytes):
    import pypdfium2 as pdfium
    doc = pdfium.PdfDocument(io.BytesIO(pdf_bytes))
    return "\n".join(doc[i].get_textpage().get_text_range() for i in range(len(doc)))


def test_the_printed_cover_shows_the_ladder_grade_and_words():
    pdf = cs.build_cover_page_pdf(
        facts=_FACTS, flags=_FLAGS, sqs_results={"Pre-Submission Analysis": _PKG_SQS}, form_ids=[],
        org_name="Astrea It services", narrative="N.", ai_block={}, sqs_reasoning="R.",
        user={"full_name": "vinay sharma"}, hard_stops=[], soft_stops=[])
    text = _pdf_text(pdf)
    assert "Priority review" in text and "priority_review" not in text
    assert "$300,000" in text
    table = text[text.index("Pre-Submission Analysis"):][:80]
    assert "77/100" in table and "C" in table.split("77/100", 1)[1][:6]


def test_the_brief_route_carries_the_package_grade():
    src = inspect.getsource(dr.lite_cover_sheet)
    assert '"grade":         tier_for_score(_pkg["package_sqs_score"])[0],' in src


# ── The cover's score is exactly the SQS panel's (owner, 1 Oct 2026) ────────
# "score during download should be exactly same on the cover page of individual
# form or whole package as of the sqs section". The panel headlines the TOTAL
# PACKAGE SCORE; the cover printed only per-form rows and left the package score
# to the model's paragraph, and the E&O record logged an AVERAGE of the forms.

_PKG = {"package_sqs_score": 77, "tier": "Needs Work", "routing_decision": "priority_review"}


def test_every_cover_prints_the_total_package_score_row():
    pdf = cs.build_cover_page_pdf(
        facts=_FACTS, flags=_FLAGS, form_ids=["ACORD_127"], org_name="Astrea It services",
        sqs_results={"ACORD_127": {"sqs_score": 81, "routing_decision": "priority_review"}},
        narrative="N.", ai_block={}, sqs_reasoning="R.", user=None, package_sqs=_PKG)
    text = _pdf_text(pdf)
    assert "ACORD 127" in text and "81/100" in text
    row = text[text.index("Total Package Score"):][:80]
    assert "77/100" in row and "C" in row.split("77/100", 1)[1][:6]
    # no package score (a legacy session) - no row, nothing invented
    pdf = cs.build_cover_page_pdf(
        facts=_FACTS, flags=_FLAGS, form_ids=["ACORD_127"], org_name="X",
        sqs_results={"ACORD_127": {"sqs_score": 81}}, narrative="N.", ai_block={})
    assert "Total Package Score" not in _pdf_text(pdf)


def test_the_brief_never_prints_the_package_row_twice():
    pdf = cs.build_cover_page_pdf(
        facts=_FACTS, flags=_FLAGS, form_ids=[], org_name="X",
        sqs_results={"Total Package Score": {"sqs_score": 77, "routing_decision": "priority_review"}},
        narrative="N.", ai_block={}, package_sqs=_PKG)
    assert _pdf_text(pdf).count("Total Package Score") == 1


def test_the_package_score_comes_from_the_panels_door():
    stored = {"package_sqs_score": 77, "tier": "Needs Work"}
    session = {"generated_forms": {"ACORD_125": {"sqs": {"sqs_score": 81}}}, "package_sqs": stored}
    assert dr._package_score_now(session, "sid", "uid") == stored
    assert dr._package_score_now({"generated_forms": {"A": {}}}, "sid", "uid") == {}
    # a cached paragraph never quotes an older package score
    assert dr._cover_cache_key({}, ["ACORD_125"], {}, {}, 77) != dr._cover_cache_key({}, ["ACORD_125"], {}, {}, 78)


def test_every_download_route_prints_and_records_the_panels_score():
    one = inspect.getsource(dr.download_pdf)
    assert "_pkg_now = _package_score_now(proc_session, session_id, fresh[\"id\"])" in one
    assert "package_score=_pkg_score" in one and "package_sqs=_pkg_now" in one
    assert "_score_at_dl = (_pkg_score if _pkg_score is not None" in one
    allf = inspect.getsource(dr.download_all)
    assert "package_score=_pkg_score" in allf and "package_sqs=_pkg_now" in allf
    assert "_avg_score = (_pkg_score if _pkg_score is not None" in allf
    assert "_cover_cache_key(facts, list(generated.keys()), sqs_results, flags, _pkg_score)" in allf
    lite = inspect.getsource(dr.lite_cover_sheet)
    assert '_row_label = "Total Package Score"' in lite and "sqs_results = {_row_label: sqs}" in lite
