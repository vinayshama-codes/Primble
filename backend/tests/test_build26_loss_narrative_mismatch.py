"""THE NARRATIVE AND THE CLAIMS ANSWER MUST AGREE (owner, 24 Oct 2026, package 73284179).

Measured that day on an in-memory copy of the package:
  * narrative "Loss history shows 12 claims in the past five years, 4 still
    open, $322,650 incurred" + answer "No claims" -> 100, Submission Ready, no
    card;
  * narrative "no claims or losses in the past five years" + answer "Yes - we
    have had claims" -> 87, and ACORD 101 still printing "no claims".

One reader (`loss_history_state.narrative_claims_stance`, person-typed text
only), the answer's stance (`claims_answer_stance`), and ONE warning through the
legacy engine (`legacy_loss_narrative_mismatch`) when both are known and differ.
"""
from __future__ import annotations

import copy
import importlib.util
import os
from datetime import date

import pytest

from services import issue_registry as IR
from services import sqs_service as S
from services.loss_history_state import (
    claims_answer_for_narrative, claims_answer_stance, claims_question_answers,
    narrative_answer_mismatch, narrative_claims_stance, person_narrative_texts,
)

NO_CLAIMS, HAD_CLAIMS = claims_question_answers()
INDICATOR = "loss_history_no_prior_losses_indicator"
CODE = "legacy_loss_narrative_mismatch"
MSG = "Loss History: your narrative says"
TODAY = date(2026, 10, 24)

CLAIMS_TEXT = ("Loss History Discussion: Loss history shows 12 claims in the past five years, "
               "4 still open, $322,650 incurred.")
NO_CLAIMS_TEXT = ("Loss History Discussion: the applicant reports no claims or losses in the past "
                  "five years.")

_spec = importlib.util.spec_from_file_location(
    "_journeys", os.path.join(os.path.dirname(__file__), "test_build26_loss_plan_journeys.py"))
J = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(J)


def _env(v, source="producer"):
    return {"value": v, "source": source, "confidence": "producer"}


def _facts(text, source="producer", answer=None, answer_source="producer"):
    f = {"applicant_name": _env("Choice Electric LLC"), "additional_remarks_text": _env(text, source)}
    if answer is not None:
        f[INDICATOR] = _env(answer, answer_source)
    return f


# ── The reader ───────────────────────────────────────────────────────────────
@pytest.mark.parametrize("text, stance", [
    (CLAIMS_TEXT, "claims"),
    (NO_CLAIMS_TEXT, "no_claims"),
    ("", None),
    ("N/A", None),
    ("Losses: none reported", "no_claims"),
    ("Claims: 3", "claims"),
    ("No claims except one in 2022.", "claims"),
    ("Zero claims in the last five years.", "no_claims"),
    ("0 claims", "no_claims"),
    ("The insured has not had any claims.", "no_claims"),
    ("The company has never had a claim.", "no_claims"),
    ("We have had claims.", "claims"),
    ("There were 2 losses last year.", "claims"),
    # A term-scoped no-loss statement beside claims is not "no claims".
    ("No losses in 2023. 2 claims in 2021.", "claims"),
    ("No losses in 2023.", None),
    # Line-scoped or shorter than the question's five years: no stance.
    ("No GL claims in the past five years.", None),
    ("No prior losses in the last 3 years.", None),
    # Another company's losses are not this insured's.
    ("Harborline Plumbing LLC had 3 claims last year.", None),
    # Carrier / policy boilerplate.
    ("The insurer will not pay claims exceeding the limit.", None),
    ("No losses exceeding $10,000.", None),
    ("Claims-made policy form; each claim limit $1,000,000.", None),
    # Claims wholly before the five-year window, or over a longer period.
    ("3 claims in 2012.", None),
    ("12 claims in the past ten years.", None),
    # A five-year period is not a count of five claims.
    ("Experienced over the past five years with no losses.", "no_claims"),
    ("Clean loss history apart from a $40,000 fire in 2023.", "claims"),
    # States both: ambiguous.
    (NO_CLAIMS_TEXT + " Update: 2 claims were filed in 2025.", None),
])
def test_reader(text, stance):
    assert narrative_claims_stance(_facts(text), TODAY) == stance


@pytest.mark.parametrize("source", ["ai", "dec_entry", "policy_doc_text", "derived", "user_confirmed"])
def test_text_no_person_typed_never_counts(source):
    assert narrative_claims_stance(_facts(CLAIMS_TEXT, source), TODAY) is None
    assert narrative_answer_mismatch(_facts(CLAIMS_TEXT, source, NO_CLAIMS), TODAY) is None


def test_bare_legacy_value_never_counts():
    f = {"additional_remarks_text": CLAIMS_TEXT, INDICATOR: _env(NO_CLAIMS)}
    assert narrative_claims_stance(f, TODAY) is None


def test_client_typed_and_questionnaire_loss_answers_count():
    assert narrative_claims_stance(_facts(CLAIMS_TEXT, "client_arq"), TODAY) == "claims"
    f = {"qn_loss_run_gaps": _env("We had 2 claims in 2024, both closed.")}
    assert person_narrative_texts(f) and narrative_claims_stance(f, TODAY) == "claims"


def test_answer_stance_is_the_persons_answer_only():
    assert claims_answer_stance(_facts("", answer=NO_CLAIMS)) == "no_claims"
    assert claims_answer_stance(_facts("", answer=HAD_CLAIMS)) == "claims"
    assert claims_answer_stance(_facts("", answer=NO_CLAIMS, answer_source="ai")) is None
    assert claims_answer_stance(_facts("")) is None
    assert claims_answer_stance(_facts("", answer="No")) is None      # an untick, not an answer


def test_the_answer_that_agrees_with_the_narrative():
    assert claims_answer_for_narrative(_facts(CLAIMS_TEXT), TODAY) == HAD_CLAIMS
    assert claims_answer_for_narrative(_facts(NO_CLAIMS_TEXT), TODAY) == NO_CLAIMS
    assert claims_answer_for_narrative(_facts("Account overview only."), TODAY) is None


# ── The warning, all four combinations ───────────────────────────────────────
@pytest.mark.parametrize("text, answer, fires", [
    (CLAIMS_TEXT, NO_CLAIMS, "claims"),
    (CLAIMS_TEXT, HAD_CLAIMS, None),
    (NO_CLAIMS_TEXT, NO_CLAIMS, None),
    (NO_CLAIMS_TEXT, HAD_CLAIMS, "no_claims"),
])
def test_evaluate_stops_four_combinations(text, answer, fires):
    hard, soft = S.evaluate_stops(_facts(text, answer=answer), {})
    ours = [m for m in soft if m.startswith("Loss History: your narrative says")]
    assert not any(m.startswith("Loss History: your narrative says") for m in hard)
    if fires is None:
        assert ours == []
    else:
        assert len(ours) == 1
        assert ("there were claims" if fires == "claims" else "there were no claims") in ours[0]
        assert "—" not in ours[0]


def test_the_row_offers_the_claims_question_and_a_note():
    _hard, soft = S.evaluate_stops(_facts(CLAIMS_TEXT, answer=NO_CLAIMS), {})
    msg = next(m for m in soft if m.startswith("Loss History: your narrative says"))
    code, _cluster, _tier = IR.classify_legacy(msg, "soft_warning")
    assert code == CODE
    res = IR.resolution_for(CODE)
    assert res["mode"] == "field" and res["facts"] == [INDICATOR]
    assert "Narrative questionnaire" in res["note"] and "—" not in res["note"]


# ── The package, as the review page reads it ─────────────────────────────────
def _row(text, answer, source="producer"):
    row = J._row(age=15)
    row["facts"]["additional_remarks_text"] = _env(text, source)
    if answer is not None:
        J._answer(row, INDICATOR, answer)
    return row


def _cards(pkg_row):
    st = __import__("services.stops_now", fromlist=["stops_now"]).stops_now(pkg_row, pre_form=True)
    return [m for m in st["soft"] if m.startswith("Loss History: your narrative says")]


def test_a_contradicting_pair_is_held_at_85():
    for text, answer in ((CLAIMS_TEXT, NO_CLAIMS), (NO_CLAIMS_TEXT, HAD_CLAIMS)):
        row = _row(text, answer)
        pkg = J._page(row)
        assert J._score(pkg) <= 85, (text, answer)
        assert _cards(row), (text, answer)
        assert not pkg.get("open_hard_stops")


def test_ai_written_remarks_never_raise_it():
    row = _row(CLAIMS_TEXT, NO_CLAIMS, source="ai")
    assert not _cards(row)


def test_a_truthful_pair_never_lowers_the_score():
    for text, answer in ((CLAIMS_TEXT, HAD_CLAIMS), (NO_CLAIMS_TEXT, NO_CLAIMS)):
        silent = J._score(J._page(_row(J.NARRATIVE, answer)))
        said = J._score(J._page(_row(J.NARRATIVE + " " + text, answer)))
        assert not _cards(_row(J.NARRATIVE + " " + text, answer))
        assert said >= silent, (text, answer, silent, said)


def test_page_numbers_add_up_and_the_truthful_answer_reaches_100():
    row = _row(J.NARRATIVE + " " + CLAIMS_TEXT, NO_CLAIMS)
    pkg = J._page(row)
    plan = pkg["review_plan"]
    assert sum(i["points"] for i in plan["items"]) + int(plan.get("left") or 0) \
        == 100 - int(plan.get("real", J._score(pkg)))  # R5 / P2 (owner, 30 Oct 2026; TEST updated): 100 - the REAL score - a cap holds the number, never gives points.
    # By its sentence: on a row whose stored cards were not re-synced the view's
    # safety net draws it (code `uncovered_soft_stop`, the same resolution).
    card = next(i for i in plan["items"] if str(i.get("label")).startswith(MSG))
    assert card["points"] >= 0      # what the answer moves here; the page sum holds
    # The card's own fix: the answer the narrative gives.
    assert S.loss_plan_probes(pkg.get("loss_plan")).get(INDICATOR) == HAD_CLAIMS
    J._answer(row, INDICATOR, HAD_CLAIMS)
    pkg2 = J._page(row)
    assert not _cards(row)
    # R5 (owner, 30 Oct 2026; TEST updated): a number is what the answer moves
    # the REAL score - a cap may hold the shown one.
    _real = lambda p: int(p["review_plan"].get("real", J._score(p)))
    assert abs(_real(pkg2) - (_real(pkg) + card["points"])) <= 1
    assert J._score(pkg2) >= J._score(pkg)          # the truthful answer never lowers it
    steps = [i for i in pkg2["review_plan"]["items"] if i["points"] > 0]
    assert any(i.get("step") == "upload" for i in steps)
    plan2 = pkg2["review_plan"]
    assert sum(i["points"] for i in plan2["items"]) + int(plan2.get("left") or 0) == 100 - _real(pkg2)
    J._upload(row, J._required_years(row))
    if any(i.get("field") == "loss_run_status" for i in steps):
        J._answer(row, "loss_run_status", J.REQUESTED)
    assert J._score(J._page(row)) == 100


@pytest.mark.parametrize("fix", ["answer", "replace", "append"])
def test_either_fix_clears_it(fix):
    row = _row(NO_CLAIMS_TEXT, HAD_CLAIMS)
    assert _cards(row)
    if fix == "answer":
        J._answer(row, INDICATOR, NO_CLAIMS)
    elif fix == "replace":
        row["facts"]["additional_remarks_text"] = _env(
            "Loss History Discussion: 2 claims in 2025, both closed.")
    else:      # narrative mode appends: the text now states both -> no stance
        row["facts"]["additional_remarks_text"] = _env(
            NO_CLAIMS_TEXT + "\nCorrection: 2 claims were filed in 2025.")
    assert not _cards(row)


def test_after_forms_the_same_warning_holds():
    from services.stops_now import stops_now
    row = _row(CLAIMS_TEXT, NO_CLAIMS)
    row["generated_forms"] = {"ACORD_125": {"fields": {}}}
    st = stops_now(row, ["ACORD_125"], pre_form=False)
    assert any(m.startswith("Loss History: your narrative says there were claims") for m in st["soft"])


def test_a_persons_had_claims_still_settles_the_document_conflict():
    row = J._row(age=15, sheet=True, attested=True)
    assert S._loss_history_conflict(row["facts"], row["flags"], False)
    J._answer(row, INDICATOR, HAD_CLAIMS)
    assert not S._loss_history_conflict(row["facts"], row["flags"], False)


def test_the_preview_warns_when_no_claims_is_picked_on_a_claims_narrative():
    from services.answer_preview import preview_follow_ups
    row = _row(CLAIMS_TEXT, HAD_CLAIMS)
    out = preview_follow_ups(row, "s", "u", [(INDICATOR, NO_CLAIMS)], [INDICATOR])
    warn = [f for f in out if f["kind"] == "warning"]
    assert len(warn) == 1 and warn[0]["label"].startswith(MSG)
    assert "there were claims" in warn[0]["label"]
    # The truthful pick raises nothing of the kind.
    out2 = preview_follow_ups(_row(CLAIMS_TEXT, NO_CLAIMS), "s", "u", [(INDICATOR, HAD_CLAIMS)],
                              [INDICATOR])
    assert not [f for f in out2 if f["kind"] == "warning"]


def test_the_contradicting_pair_never_outscores_the_truthful_one():
    text = J.NARRATIVE + " " + CLAIMS_TEXT
    lie = J._score(J._page(_row(text, NO_CLAIMS)))
    truth = J._score(J._page(_row(text, HAD_CLAIMS)))
    assert lie <= 85 and lie <= truth


# ── The narrative reader's stance: paraphrases (24 Oct 2026) ─────────────────
from services import narrative_reader as NR  # noqa: E402


def _read(text, stance, quote, version=NR.READER_VERSION):
    """Facts holding `text` as a producer's remarks and the reading a stubbed
    model reply leaves (through the real gate)."""
    from services.extraction_service import _narrative_remarks_text
    f = _facts(text)
    items = NR.gate_reply({"items": {}, "loss": {"stance": stance, "quote": quote}}, text)
    f[NR.READING_KEY] = {"text_hash": NR.text_hash(_narrative_remarks_text(f)), "items": items,
                         "version": version}
    return f


SPOTLESS = "Account overview: a Denver electrician. Our loss experience has been spotless."
WATER = "Account overview: a Denver electrician. We had a couple of small water claims."
# A paraphrase the rules do not read (no claim or loss word at all).
LEAKS = "Account overview: a Denver electrician. Two water leaks led to insurance payouts last spring."


def test_ai_paraphrase_no_claims():
    f = _read(SPOTLESS, "no_claims", "Our loss experience has been spotless")
    assert narrative_claims_stance(f, TODAY) == "no_claims"
    f[INDICATOR] = _env(HAD_CLAIMS)
    assert narrative_answer_mismatch(f, TODAY) == "no_claims"


def test_ai_paraphrase_claims():
    assert narrative_claims_stance(_facts(WATER), TODAY) == "claims"      # the rules read this one
    assert narrative_claims_stance(_facts(LEAKS), TODAY) is None          # ... not this one
    f = _read(LEAKS, "claims", "Two water leaks led to insurance payouts")
    assert narrative_claims_stance(f, TODAY) == "claims"
    f[INDICATOR] = _env(NO_CLAIMS)
    _hard, soft = S.evaluate_stops(f, {})
    assert any(m.startswith(MSG + " there were claims") for m in soft)


def test_ai_quote_not_in_the_text_is_ignored():
    f = _read(SPOTLESS, "no_claims", "the insured has never had a claim")
    assert narrative_claims_stance(f, TODAY) is None


def test_ai_mixed_or_not_stated_raises_nothing():
    for stance in ("mixed", "not_stated"):
        f = _read(LEAKS, stance, "Two water leaks led to insurance payouts")
        f[INDICATOR] = _env(NO_CLAIMS)
        assert narrative_answer_mismatch(f, TODAY) is None
        assert not [m for m in S.evaluate_stops(f, {})[1] if m.startswith(MSG)]


def test_ai_reading_of_another_text_or_an_old_reading_is_ignored():
    f = _read(LEAKS, "claims", "Two water leaks led to insurance payouts")
    f["additional_remarks_text"] = _env(LEAKS + " Edited.")
    assert narrative_claims_stance(f, TODAY) is None
    assert narrative_claims_stance(_read(LEAKS, "claims", "Two water leaks led to insurance payouts",
                                         version=1), TODAY) is None


def test_ai_on_remarks_no_person_typed_is_ignored():
    f = _read(LEAKS, "claims", "Two water leaks led to insurance payouts")
    f["additional_remarks_text"]["source"] = "ai"
    assert narrative_claims_stance(f, TODAY) is None


def test_rules_and_ai_disagree_means_no_stance():
    text = "Account overview. We have had claims."
    f = _read(text, "no_claims", "Account overview")
    assert narrative_claims_stance(f, TODAY) is None
    f2 = _read(text, "claims", "We have had claims")
    assert narrative_claims_stance(f2, TODAY) == "claims"


def test_reader_off_means_rules_only(monkeypatch):
    import asyncio
    monkeypatch.setenv("NARRATIVE_READER", "0")
    assert asyncio.run(NR.read_narrative(SPOTLESS)) is None     # no reading stored
    assert narrative_claims_stance(_facts(SPOTLESS), TODAY) is None
    assert narrative_claims_stance(_facts(CLAIMS_TEXT), TODAY) == "claims"


# ── Adversarial review fixes (24 Oct 2026) ───────────────────────────────────
@pytest.mark.parametrize("text", [
    "We have had excellent loss experience with our carrier.",       # a record, not a loss
    "We have had a great loss history.",
    "We have 2 claims-made policies with the carrier.",              # coverage wording
    "Paid $12,000 in premium, no losses.",                           # a premium is not a loss paid
    "Two loss payees are listed on the auto policy.",
    "2 loss runs attached.",
])
def test_review_no_false_claims_stance(text):
    from services.loss_history_state import text_claims_stance
    assert text_claims_stance(text, TODAY) != "claims"
    f = _facts(text, answer=NO_CLAIMS)
    assert narrative_answer_mismatch(f, TODAY) is None


def test_review_in_the_last_five_years_is_the_window_not_a_term():
    f = _facts("There were no claims in the last 5 years.", answer=HAD_CLAIMS)
    assert narrative_claims_stance(f, TODAY) == "no_claims"
    assert narrative_answer_mismatch(f, TODAY) == "no_claims"


def test_review_a_shorter_period_takes_no_stance():
    f = _facts("No claims for 3 years.", answer=HAD_CLAIMS)
    assert narrative_claims_stance(f, TODAY) is None


def test_review_ai_stance_reads_the_key_the_reader_read():
    """acord101_remarks (a document's) is the text `_narrative_remarks_text`
    reads first; a typed additional_remarks_text must not vouch for it."""
    from services.narrative_reader import READER_VERSION, READING_KEY, text_hash
    doc_text = "Remarks from the uploaded application about operations."
    f = {"applicant_name": _env("Choice Electric LLC"),
         "acord101_remarks": _env(doc_text, "document_text"),
         "additional_remarks_text": _env("We install commercial wiring.", "producer"),
         INDICATOR: _env(NO_CLAIMS),
         READING_KEY: {"text_hash": text_hash(doc_text), "version": READER_VERSION,
                       "items": {"loss:claims": "about operations"}}}
    assert narrative_claims_stance(f, TODAY) is None
