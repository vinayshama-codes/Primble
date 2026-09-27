"""Owner's second live run of orbin_retest_kit (24 Sep 2026, session 5ca5cff5).

Round 2's fixes held on the forms. Grading every printed value found five
more, and each cause was confirmed on the stored session before anything
changed. Every test reads the LIVE values from
`tests/fixtures/orbin_live_25sep.json` and pins the other direction too.

1. 127 USE printed OTHER = "PRIVATE PASSENGER" (the vehicle's TYPE) beside
   the cell "USE: NA". The description box had no owner, and the evidence
   gate's rescue then ticked OTHER past the resolver that owns it.
2. 125 "exposure to flammables?" = Y on the business description and 126
   "vendors coverage required?" = Y on the subcontractor sentence. The
   semantic judge rejects both whenever it is reached - it made ONE attempt
   straight behind the gap-fill burst, and a failed call left every Yes
   standing. 131 "subcontractors carry LESS than applicant?" = Y on the same
   sentence, which the old judge prompt accepted in small batches.
3. 186 "subcontractors without a certificate?" = N, under the form's own
   "* DO NOT ANSWER IF THIS FORM IS ATTACHED TO ACORD 126".
4. 125 / 131 one-line DESCRIPTION OF OPERATIONS boxes printed the whole
   paragraph at 3.5pt and still clipped it.

Offline: no database, no LLM (the judge is replaced wherever it would run).
"""
import copy
import json
import os
import re
import sys
import time

import pikepdf
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
os.environ.setdefault("OPENAI_API_KEY", "sk-offline-test")

import services.form_service as fs                           # noqa: E402
import services.pdf_service as ps                            # noqa: E402

BACKEND = os.path.join(os.path.dirname(__file__), "..")
with open(os.path.join(os.path.dirname(__file__), "fixtures", "orbin_live_25sep.json"),
          encoding="utf-8") as _fh:
    LIVE = json.load(_fh)
MF = LIVE["merged_facts"]
STORED = LIVE["stored"]
TEXT = LIVE["text"]
SUBS = " ".join(TEXT["subcontracting"][1:])            # the narrative's own sentence, as printed


def _schema(form_id):
    with open(os.path.join(BACKEND, "forms_schemas", f"{form_id}_schema.json"),
              encoding="utf-8") as fh:
        return json.load(fh)


def _before(form_id, field):
    return (STORED[form_id].get(field) or {}).get("value")


def _facts(form_id, **extra):
    f = copy.deepcopy(MF)
    f["_form_id"] = form_id
    f.update(extra)
    return f


# =============================================================================
# 1. ACORD 127 USE: OTHER "PRIVATE PASSENGER" beside "USE: NA"
# =============================================================================
class TestUseColumnOtherBox:

    def test_the_live_run_ticked_other_with_the_vehicle_type(self):
        assert _before("ACORD_127", "Vehicle_Use_OtherIndicator_A") == "Y"
        assert _before("ACORD_127", "Vehicle_Use_OtherDescription_A") == "PRIVATE PASSENGER"
        assert any("USE: NA" in ln for ln in TEXT["vehicle_block"])
        assert MF.get("auto_vehicle_use") in (None, "")   # round 2's reader cleared the AI "commercial"

    def test_the_description_is_an_owned_blank_when_no_use_is_stated(self):
        f = _facts("ACORD_127")
        assert ps._resolve_vehicle_use_other_description("Vehicle_Use_OtherDescription_A", f) is None
        assert ps._owned_blank_claim("Vehicle_Use_OtherDescription_A", f)
        assert ps._owned_blank_claim("Vehicle_Use_OtherIndicator_A", f)

    @pytest.mark.parametrize("use", ["NA", "N/A", "None", "-"])
    def test_a_non_answer_is_never_an_other_use(self, use):
        f = _facts("ACORD_127", auto_vehicle_use=use)
        assert ps._resolve_vehicle_use_other_description("Vehicle_Use_OtherDescription_A", f) is None
        assert ps._resolve_vehicle_use_indicator("Vehicle_Use_OtherIndicator_A", f) is None

    def test_a_stated_use_no_class_names_prints_beside_other(self):
        f = _facts("ACORD_127", auto_vehicle_use="Executive transport")
        assert ps._resolve_vehicle_use_indicator("Vehicle_Use_OtherIndicator_A", f) == "Yes"
        assert ps._resolve_vehicle_use_indicator("Vehicle_Use_CommercialIndicator_A", f) == "No"
        assert ps._resolve_vehicle_use_other_description(
            "Vehicle_Use_OtherDescription_A", f) == "Executive transport"

    def test_a_recognised_class_leaves_the_description_blank(self):
        f = _facts("ACORD_127", auto_vehicle_use="Commercial")
        assert ps._resolve_vehicle_use_indicator("Vehicle_Use_CommercialIndicator_A", f) == "Yes"
        assert ps._resolve_vehicle_use_indicator("Vehicle_Use_OtherIndicator_A", f) == "No"
        assert ps._resolve_vehicle_use_other_description("Vehicle_Use_OtherDescription_A", f) is None

    def test_a_row_with_no_vehicle_is_left_to_its_own_owner(self):
        f = _facts("ACORD_127", auto_vehicle_use="Executive transport")
        assert ps._resolve_vehicle_use_other_description(
            "Vehicle_Use_OtherDescription_B", f) is ps._SCHED_SKIP

    def test_the_radius_pair_is_not_claimed(self):
        f = _facts("ACORD_127")
        for field in ("Vehicle_Use_UnderFifteenMilesIndicator_A",
                      "Vehicle_Use_FifteenMilesOrOverIndicator_A"):
            assert ps._resolve_vehicle_use_other_description(field, f) is ps._SCHED_SKIP
            assert ps._resolve_vehicle_use_indicator(field, f) is ps._SCHED_SKIP

    def test_the_rescue_never_ticks_a_box_a_resolver_keeps_blank(self, monkeypatch):
        """THE CLASS, not the box: the evidence gate's "rescue a stranded Yes"
        promoted any blank /Btn beside a present description. Replay the live
        shape with the description UNOWNED (as it was), so only the rescue's
        own guard stands between the stray description and the tick."""
        monkeypatch.setattr(ps, "_EVIDENCE_JUDGE_ENABLED", False)
        monkeypatch.setattr(ps, "_resolve_vehicle_use_other_description",
                            lambda field_name, facts: ps._SCHED_SKIP)
        raw = "\n".join(TEXT["vehicle_block"])
        mapped, conf = ps.map_facts_to_form(
            _facts("ACORD_127"), _schema("ACORD_127"), form_id="ACORD_127", raw_text=raw,
            pre_filled_gpt={"filled_values": {"Vehicle_Use_OtherDescription_A": "PRIV PASSENGER"},
                            "raw_text_fields": set(), "question_grounding": {}})
        assert not str(mapped.get("Vehicle_Use_OtherIndicator_A") or "").strip()
        assert not str(mapped.get("Vehicle_Use_OtherDescription_A") or "").strip()

    def test_the_live_shape_now_prints_nothing_in_the_use_column(self, monkeypatch):
        monkeypatch.setattr(ps, "_EVIDENCE_JUDGE_ENABLED", False)
        raw = "\n".join(TEXT["vehicle_block"])
        mapped, _ = ps.map_facts_to_form(
            _facts("ACORD_127"), _schema("ACORD_127"), form_id="ACORD_127", raw_text=raw,
            pre_filled_gpt={"filled_values": {"Vehicle_Use_OtherDescription_A": "PRIVATE PASSENGER"},
                            "raw_text_fields": set(), "question_grounding": {}})
        for box in ("Other", "Pleasure", "Farm", "Commercial", "Retail", "Service", "ForHire"):
            assert not str(mapped.get(f"Vehicle_Use_{box}Indicator_A") or "").strip(), box
        assert not str(mapped.get("Vehicle_Use_OtherDescription_A") or "").strip()


# =============================================================================
# 2. The semantic judge: reached, retried, and a Yes it cannot confirm is blank
# =============================================================================
class _Resp:
    def __init__(self, verdicts):
        class _M:
            content = json.dumps({"verdicts": verdicts})

        class _C:
            message = _M()
        self.choices = [_C()]
        self.usage = None


class _StatusError(Exception):
    def __init__(self, status):
        super().__init__(f"HTTP {status}")
        self.status_code = status


def _client(script):
    """A fake client answering each call from `script` (an exception to raise
    or a list of verdicts to return), in order."""
    calls = []

    class _Client:
        class chat:
            class completions:
                @staticmethod
                def create(**kw):
                    step = script[min(len(calls), len(script) - 1)]
                    calls.append(kw)
                    if isinstance(step, Exception):
                        raise step
                    return _Resp(step)
    return _Client(), calls


_ITEMS = [{"id": "Q1", "question": "Vendors coverage required?", "answer": "Yes", "quote": SUBS},
          {"id": "Q2", "question": "Are subcontractors allowed to work without providing you "
                                   "with a certificate of insurance?", "answer": "No", "quote": SUBS}]


class TestJudgeIsReached:

    def test_the_prompt_carries_the_same_subject_rule(self):
        p = ps._JUDGE_SYSTEM_PROMPT
        assert "7. A quote about the same people or activity as the question does not" in p
        assert "LESS than the applicant's" in p
        assert "8. Judge every id you are given" in p
        # the rules the suite already pins are still there
        assert "SUPPORT, not topic overlap" in p and "return false" in p

    def test_a_rate_limit_is_waited_out_and_then_judged(self, monkeypatch):
        client, calls = _client([_StatusError(429), _StatusError(429),
                                 [{"id": "Q1", "supports": False}, {"id": "Q2", "supports": True}]])
        monkeypatch.setattr(ps, "_get_openai_form_fill_client_sync", lambda: client)
        waits = []
        monkeypatch.setattr(time, "sleep", lambda s: waits.append(s))
        unjudged = set()
        out = ps._judge_evidence_batch(_ITEMS, "ACORD_126", unjudged=unjudged)
        assert out == {"Q1": False, "Q2": True}
        assert unjudged == set()
        assert len(calls) == 3
        assert waits == [5.0, 15.0], "a 429 waits on the TPM schedule, not 1/2/4s"

    def test_a_batch_that_never_recovers_reports_its_ids(self, monkeypatch):
        client, calls = _client([_StatusError(429)])
        monkeypatch.setattr(ps, "_get_openai_form_fill_client_sync", lambda: client)
        monkeypatch.setattr(time, "sleep", lambda s: None)
        unjudged = set()
        assert ps._judge_evidence_batch(_ITEMS, "ACORD_126", unjudged=unjudged) == {}
        assert unjudged == {"Q1", "Q2"}
        assert len(calls) == ps._JUDGE_RETRIES + 1

    @pytest.mark.parametrize("status", [500, 502, 503, 504])
    def test_a_server_error_is_retried(self, monkeypatch, status):
        client, calls = _client([_StatusError(status), [{"id": "Q1", "supports": False},
                                                        {"id": "Q2", "supports": True}]])
        monkeypatch.setattr(ps, "_get_openai_form_fill_client_sync", lambda: client)
        monkeypatch.setattr(time, "sleep", lambda s: None)
        assert ps._judge_evidence_batch(_ITEMS, "ACORD_126") == {"Q1": False, "Q2": True}

    @pytest.mark.parametrize("status", [400, 401, 403, 404])
    def test_a_refused_request_is_the_judge_unavailable_not_unjudged(self, monkeypatch, status):
        """The offline suite runs on a placeholder key: a 401 must change
        nothing, or every kept Yes in the suite would be blanked."""
        client, calls = _client([_StatusError(status)])
        monkeypatch.setattr(ps, "_get_openai_form_fill_client_sync", lambda: client)
        monkeypatch.setattr(time, "sleep", lambda s: None)
        unjudged = set()
        assert ps._judge_evidence_batch(_ITEMS, "ACORD_126", unjudged=unjudged) == {}
        assert unjudged == set()
        assert len(calls) == 1

    def test_no_network_at_all_is_unavailable(self, monkeypatch):
        client, calls = _client([ConnectionError("no route to host")])
        monkeypatch.setattr(ps, "_get_openai_form_fill_client_sync", lambda: client)
        unjudged = set()
        assert ps._judge_evidence_batch(_ITEMS, "ACORD_126", unjudged=unjudged) == {}
        assert unjudged == set()

    def test_an_id_the_reply_leaves_out_is_unjudged(self, monkeypatch):
        client, _ = _client([[{"id": "Q2", "supports": True}]])
        monkeypatch.setattr(ps, "_get_openai_form_fill_client_sync", lambda: client)
        unjudged = set()
        assert ps._judge_evidence_batch(_ITEMS, "ACORD_126", unjudged=unjudged) == {"Q2": True}
        assert unjudged == {"Q1"}

    def test_an_unparseable_reply_is_retried_once(self, monkeypatch):
        class _Bad:
            choices = [type("C", (), {"message": type("M", (), {"content": "{not json"})()})()]
            usage = None
        seq = [_Bad(), _Resp([{"id": "Q1", "supports": False}, {"id": "Q2", "supports": True}])]

        class _Client:
            class chat:
                class completions:
                    @staticmethod
                    def create(**kw):
                        return seq.pop(0)
        monkeypatch.setattr(ps, "_get_openai_form_fill_client_sync", lambda: _Client())
        assert ps._judge_evidence_batch(_ITEMS, "ACORD_126") == {"Q1": False, "Q2": True}

    def test_batches_are_small_and_each_is_accounted_for(self, monkeypatch):
        """Batches of FIVE (measured: at 20 the judge let ~2% of wrong
        answers through). A batch that is rate-limited to the end reports
        its ids; a refused one reports none; the rest are judged."""
        assert ps._JUDGE_BATCH == 5
        items = [{"id": f"F{i:02d}", "question": "q", "answer": "Yes", "quote": "x"}
                 for i in range(12)]

        class _Client:
            class chat:
                class completions:
                    @staticmethod
                    def create(**kw):
                        ids = re.findall(r"id: (F\d\d)", kw["messages"][1]["content"])
                        if "F05" in ids:
                            raise _StatusError(429)       # the middle batch never recovers
                        if "F10" in ids:
                            raise _StatusError(401)       # the last one is refused
                        return _Resp([{"id": i, "supports": True} for i in ids])
        monkeypatch.setattr(ps, "_get_openai_form_fill_client_sync", lambda: _Client())
        monkeypatch.setattr(time, "sleep", lambda s: None)
        unjudged = set()
        out = ps._judge_evidence_batch(items, "ACORD_125", unjudged=unjudged)
        assert out == {f"F{i:02d}": True for i in range(5)}
        assert unjudged == {f"F{i:02d}" for i in range(5, 10)}

    def test_the_kill_switch_still_turns_it_off(self, monkeypatch):
        monkeypatch.setattr(ps, "_EVIDENCE_JUDGE_ENABLED", False)
        unjudged = set()
        assert ps._judge_evidence_batch(_ITEMS, "ACORD_126", unjudged=unjudged) == {}
        assert unjudged == set()


# The narrative's safety sentence: a real, unique, asserting quote the
# deterministic gate KEEPS - so the only thing deciding below is the judge.
_SAFETY = "We maintain a written safety manual and hold monthly safety meetings for all field staff."
_SAFETY_Q = "Contractors_Question_AAGCode_A"
# A "No" the deterministic gate keeps on its own (a real negation). The
# subcontractor sentence answers AAD "No" only by implication - the judge
# RESCUES that one, so silence rightly leaves it blank.
_NO_Q = "Contractors_Question_AAICode_A"
_NO_QUOTE = "The company performs no blasting and stores no explosive material."


def _gate(monkeypatch, verdicts, unjudged_ids=()):
    def _fake(items, form_id="", unjudged=None):
        if unjudged is not None:
            unjudged.update(i for i in unjudged_ids if i in {it["id"] for it in items})
        return {k: v for k, v in verdicts.items() if k in {it["id"] for it in items}}
    monkeypatch.setattr(ps, "_judge_evidence_batch", _fake)
    raw = _SAFETY + "\n" + _NO_QUOTE
    mapped, _ = ps.map_facts_to_form(
        _facts("ACORD_126"), _schema("ACORD_126"), form_id="ACORD_126", raw_text=raw,
        pre_filled_gpt={"filled_values": {_SAFETY_Q: "Y", _NO_Q: "N"},
                        "raw_text_fields": set(),
                        "question_grounding": {_SAFETY_Q: _SAFETY, _NO_Q: _NO_QUOTE}})
    return mapped


class TestUnconfirmedYes:

    def test_a_confirmed_yes_and_no_stand(self, monkeypatch):
        mapped = _gate(monkeypatch, {_SAFETY_Q: True, _NO_Q: True})
        assert mapped.get(_SAFETY_Q) == "Y"
        assert mapped.get(_NO_Q) == "N"

    def test_a_yes_the_reachable_judge_did_not_confirm_is_blanked(self, monkeypatch):
        mapped = _gate(monkeypatch, {}, unjudged_ids=(_SAFETY_Q, _NO_Q))
        assert not str(mapped.get(_SAFETY_Q) or "").strip()
        assert mapped.get(_NO_Q) == "N", "silence never decides a No"

    def test_an_unavailable_judge_changes_nothing(self, monkeypatch):
        mapped = _gate(monkeypatch, {})
        assert mapped.get(_SAFETY_Q) == "Y"
        assert mapped.get(_NO_Q) == "N"

    def test_a_rejected_yes_is_blanked_as_before(self, monkeypatch):
        mapped = _gate(monkeypatch, {_SAFETY_Q: False, _NO_Q: True})
        assert not str(mapped.get(_SAFETY_Q) or "").strip()
        assert mapped.get(_NO_Q) == "N"

    def test_an_implied_no_still_needs_the_judge_to_rescue_it(self, monkeypatch):
        """The live 126 AAD "No" (subcontractors must provide certificates)
        carries no negation word: the judge rescues it; silence leaves it
        blank - exactly as before this change."""
        def _fake(items, form_id="", unjudged=None):
            return {it["id"]: True for it in items if it["id"] == "Contractors_Question_AADCode_A"}
        monkeypatch.setattr(ps, "_judge_evidence_batch", _fake)
        q = "Contractors_Question_AADCode_A"
        mapped, _ = ps.map_facts_to_form(
            _facts("ACORD_126"), _schema("ACORD_126"), form_id="ACORD_126", raw_text=SUBS,
            pre_filled_gpt={"filled_values": {q: "N"}, "raw_text_fields": set(),
                            "question_grounding": {q: SUBS}})
        assert mapped.get(q) == "N"


class TestLiveYesAnswers:
    """What the forms printed, and the evidence each was kept on."""

    def test_the_live_run_printed_the_three_yes_answers(self):
        assert _before("ACORD_125", "CommercialPolicy_Question_ABCCode_A") == "Y"
        assert _before("ACORD_126", "GeneralLiabilityLineOfBusiness_Question_ABHCode_A") == "Y"
        assert _before("ACORD_131", "CommercialUmbrellaLineOfBusiness_Question_ABBCode_A") == "Y"

    def test_each_was_explained_by_a_sentence_about_something_else(self):
        ops = MF["operations_description"]["value"]
        flammables = _before("ACORD_125",
                             "CommercialPolicy_AnyExposureToFlammableExplosivesChemicalsExplanation_A")
        assert flammables.startswith("Commercial general contractor.")
        assert ops.startswith(flammables.rstrip("."))          # the business description, cut short
        for fid, box in (("ACORD_126", "GeneralLiabilityLineOfBusiness_VendorCoverageRequiredExplanation_A"),
                         ("ACORD_131", "CommercialUmbrellaLineOfBusiness_"
                                       "SubcontractorsCarryCoveragesLessThanApplicantExplanation_A")):
            assert _before(fid, box).startswith("Subcontractors are required to carry their own")

    def test_the_deterministic_gate_alone_cannot_see_it(self, monkeypatch):
        """Why the judge must be REACHED: the subcontractor sentence is real,
        unique to its question and asserts something - every structural check
        passes it. Only reading implication rejects it."""
        monkeypatch.setattr(ps, "_EVIDENCE_JUDGE_ENABLED", False)
        q = "GeneralLiabilityLineOfBusiness_Question_ABHCode_A"
        mapped, _ = ps.map_facts_to_form(
            _facts("ACORD_126"), _schema("ACORD_126"), form_id="ACORD_126", raw_text=SUBS,
            pre_filled_gpt={"filled_values": {q: "Y"}, "raw_text_fields": set(),
                            "question_grounding": {q: SUBS}})
        assert mapped.get(q) == "Y"


# =============================================================================
# 3. ACORD 186's starred questions beside an ACORD 126
# =============================================================================
def _starred_codes_from_the_template():
    """Read "?*" off the printed 186 and match each fragment to its schema
    question - the set is the FORM's, never a hand list."""
    import pdfplumber

    def _words(text):
        # the printed form says "OTHER EMPLOYERS", ACORD's tooltip "other employees"
        return [w.replace("employers", "employees") for w in re.findall(r"[a-z]+", text.lower())]

    def _shared_ending(question, frag):
        n = 0
        while n < min(len(question), len(frag)) and question[-1 - n] == frag[-1 - n]:
            n += 1
        return n

    sch = _schema("ACORD_186")
    questions = {}
    for k, meta in sch.items():
        m = re.match(r"^Contractors_Question_([A-Z]{3})Code_A$", k)
        tu = str((meta or {}).get("tu") or "")
        if m and "response to the question" in tu:
            questions[m.group(1)] = _words(tu.split("question,", 1)[-1])
    with pdfplumber.open(os.path.join(BACKEND, "templates", "ACORD_186.pdf")) as pdf:
        text = pdf.pages[0].extract_text() or ""
    assert "DO NOT ANSWER IF THIS FORM IS ATTACHED TO ACORD 126" in text
    found = set()
    for ln in text.splitlines():
        for frag in ln.split("?*")[:-1]:
            frag = re.sub(r"^.*\d+\.", "", frag)            # drop the other column's number
            words = _words(frag)
            if not words:
                continue
            # A fragment is the END of its question (a line break cut the
            # start off), so the question that ENDS with it wins; overlap
            # breaks the one printed paraphrase ("less than YOURS").
            best = max(questions, key=lambda c: (
                _shared_ending(questions[c], words),
                len(set(words) & set(questions[c])) / len(set(words))))
            assert (_shared_ending(questions[best], words) >= 1
                    or len(set(words) & set(questions[best])) / len(set(words)) >= 0.7), frag
            found.add(best)
    return found


class TestAcord186Starred:

    def test_the_live_run_answered_one(self):
        assert _before("ACORD_186", "Contractors_Question_AADCode_A") == "N"
        assert "ACORD_126" in LIVE["selected_form_ids"]

    def test_the_set_is_the_printed_forms(self):
        assert _starred_codes_from_the_template() == set(ps._ACORD186_NOT_WITH_126)

    def test_the_126_asks_every_one_of_them(self):
        """The instruction is only safe because the 126 carries each question.
        Two under their own codes - watercraft, and leased employees (AAC)."""
        q126 = {re.sub(r"[^a-z]", "", str(m.get("tu") or "").split("question,", 1)[-1].lower())
                for m in _schema("ACORD_126").values() if isinstance(m, dict)}
        norm = lambda s: re.sub(r"[^a-z]", "", s.lower()).replace("employees", "employers")  # noqa: E731
        q126 = {norm(q) for q in q126}
        sch186 = _schema("ACORD_186")
        watercraft = any("watercraftdocksfloats" in q for q in q126)
        for code in ps._ACORD186_NOT_WITH_126:
            tu = str(sch186[f"Contractors_Question_{code}Code_A"]["tu"]).split("question,", 1)[-1]
            if code == "KAE":
                assert watercraft
                continue
            assert norm(tu) in q126, code

    @pytest.mark.parametrize("code", sorted(ps._ACORD186_NOT_WITH_126))
    def test_beside_a_126_each_is_an_owned_blank(self, code):
        f = {"_form_id": "ACORD_186", "_package_form_ids": LIVE["selected_form_ids"]}
        field = f"Contractors_Question_{code}Code_A"
        assert ps._resolve_acord186_starred_question(field, f) is None
        assert ps._owned_blank_claim(field, f)

    def test_without_a_126_the_186_answers_them(self):
        f = {"_form_id": "ACORD_186", "_package_form_ids": ["ACORD_125", "ACORD_186"]}
        assert ps._resolve_acord186_starred_question("Contractors_Question_AADCode_A", f) is ps._SCHED_SKIP

    @pytest.mark.parametrize("code", ["KAC", "AAJ", "KAF", "KAG", "KAI", "KAQ"])
    def test_an_unstarred_question_is_untouched(self, code):
        f = {"_form_id": "ACORD_186", "_package_form_ids": LIVE["selected_form_ids"]}
        assert ps._resolve_acord186_starred_question(
            f"Contractors_Question_{code}Code_A", f) is ps._SCHED_SKIP

    def test_the_126_keeps_its_own_answer(self):
        f = {"_form_id": "ACORD_126", "_package_form_ids": LIVE["selected_form_ids"]}
        assert ps._resolve_acord186_starred_question("Contractors_Question_AADCode_A", f) is ps._SCHED_SKIP

    @staticmethod
    def _run_186(monkeypatch, package):
        """The live shape: the judge RESCUES the implied "No" (it did live), so
        only the package rule can be what removes it."""
        q = "Contractors_Question_AADCode_A"
        monkeypatch.setattr(ps, "_judge_evidence_batch",
                            lambda items, form_id="", unjudged=None:
                            {it["id"]: True for it in items if it["id"] == q})
        facts = _facts("ACORD_186", _package_form_ids=package)
        mapped, _ = ps.map_facts_to_form(
            facts, _schema("ACORD_186"), form_id="ACORD_186", raw_text=SUBS,
            pre_filled_gpt={"filled_values": {q: "N"}, "raw_text_fields": set(),
                            "question_grounding": {q: SUBS}})
        return mapped.get(q)

    def test_the_live_186_answer_is_dropped_beside_the_126(self, monkeypatch):
        assert not str(self._run_186(monkeypatch, LIVE["selected_form_ids"]) or "").strip()

    def test_the_same_answer_stands_on_a_186_without_a_126(self, monkeypatch):
        package = [f for f in LIVE["selected_form_ids"] if f != "ACORD_126"]
        assert self._run_186(monkeypatch, package) == "N"


class TestPackageList:

    def test_the_list_comes_from_the_selected_forms(self):
        s = {"selected_form_ids": LIVE["selected_form_ids"], "all_forms": [{"form_id": "ACORD_101"}]}
        assert fs.package_form_ids(s, "ACORD_186") == LIVE["selected_form_ids"]

    def test_dict_shapes_and_the_fallbacks(self):
        assert fs.package_form_ids({"selected_form_ids": [{"form_id": "ACORD_126"}, " "]}) == ["ACORD_126"]
        assert fs.package_form_ids({"generated_forms": {"ACORD_125": {}}}) == ["ACORD_125"]
        assert fs.package_form_ids({}, "ACORD_186") == ["ACORD_186"]
        assert fs.package_form_ids({}) == []

    def test_the_shared_gap_fill_sees_the_same_list(self, monkeypatch):
        seen = []
        monkeypatch.setattr(fs, "extract_form_schema", lambda tpl, form_id=None: {"F": {}})

        def _gaps(form_id, schema, facts):
            seen.append(facts.get("_package_form_ids"))
            return {}, {}, {}
        monkeypatch.setattr(ps, "compute_form_gaps", _gaps)
        session = {"facts": {}, "flags": {}, "selected_form_ids": LIVE["selected_form_ids"],
                   "all_forms": [{"form_id": "ACORD_186", "template_file": "ACORD_186.pdf"}]}
        fs.shared_gap_fill(session, ["ACORD_186"])
        assert seen == [LIVE["selected_form_ids"]]

    def test_routing_keys_never_reach_the_prompt(self):
        assert {"_package_form_ids", "_gl_deductible_scope", "dec_page_entries"} \
            <= set(ps._GAP_FILL_FACTS_EXCLUDE)


# =============================================================================
# 4. A paragraph in a one-line DESCRIPTION OF OPERATIONS box
# =============================================================================
def _widget(form_id, name):
    pdf = pikepdf.open(os.path.join(BACKEND, "templates", f"{form_id}.pdf"))
    stack = list(pdf.Root.AcroForm.Fields)
    while stack:
        n = stack.pop()
        if n.get("/T") is not None and str(n.get("/T")) == name:
            return pdf, n
        if "/Kids" in n:
            stack.extend(n.Kids)
    raise KeyError(name)


class TestOneLineDescription:

    OPS = MF["operations_description"]["value"]

    def test_the_live_value_is_the_whole_paragraph(self):
        assert _before("ACORD_125", "BuildingOccupancy_OperationsDescription_A") == self.OPS
        assert _before("ACORD_131", "BusinessInformation_OperationsDescription_A") == self.OPS
        assert len(self.OPS) > 200

    @pytest.mark.parametrize("form_id,name", [
        ("ACORD_125", "BuildingOccupancy_OperationsDescription_A"),
        ("ACORD_131", "BusinessInformation_OperationsDescription_A")])
    def test_a_one_line_box_prints_its_leading_sentence(self, form_id, name):
        _, w = _widget(form_id, name)
        assert ps._leading_sentences_that_fit(w, name, self.OPS) == "Commercial general contractor."

    def test_the_multi_line_box_keeps_the_paragraph(self):
        name = "CommercialPolicy_OperationsDescription_A"
        _, w = _widget("ACORD_125", name)
        assert ps._leading_sentences_that_fit(w, name, self.OPS) == self.OPS

    def test_a_value_that_fits_is_untouched(self):
        name = "BuildingOccupancy_OperationsDescription_A"
        _, w = _widget("ACORD_125", name)
        short = "Office and warehouse. Commercial electrical contracting."
        assert ps._leading_sentences_that_fit(w, name, short) == short

    def test_an_abbreviation_is_not_a_sentence_end(self):
        name = "BusinessInformation_OperationsDescription_A"
        _, w = _widget("ACORD_131", name)
        text = ("HVAC contractor in St. Louis. The company installs and services rooftop units, "
                "boilers and chillers for office buildings and schools across the metro area.")
        assert ps._leading_sentences_that_fit(w, name, text) == "HVAC contractor in St. Louis."

    def test_one_long_sentence_prints_as_before(self):
        name = "BusinessInformation_OperationsDescription_A"
        _, w = _widget("ACORD_131", name)
        text = ("General contractor managing tenant-finish, remodeling and light commercial "
                "construction for owners and property managers across the Denver metro area")
        assert ps._leading_sentences_that_fit(w, name, text) == text

    def test_other_boxes_are_never_shortened(self):
        name = "NamedInsured_FullName_A"
        _, w = _widget("ACORD_125", name)
        text = "Orbin Contracting LLC. Also trading as Orbin Construction Management of Colorado."
        assert ps._leading_sentences_that_fit(w, name, text) == text

    def test_the_downloaded_pdf_carries_the_sentence_and_the_editor_the_paragraph(self):
        data = {"BuildingOccupancy_OperationsDescription_A": self.OPS,
                "CommercialPolicy_OperationsDescription_A": self.OPS}
        out = ps.fill_pdf(os.path.join(BACKEND, "templates", "ACORD_125.pdf"), dict(data))
        pdf = pikepdf.open(__import__("io").BytesIO(out))
        vals = {}
        stack = list(pdf.Root.AcroForm.Fields)
        while stack:
            n = stack.pop()
            if n.get("/T") is not None and str(n.get("/T")) in data and "/V" in n:
                vals[str(n.get("/T"))] = str(n.get("/V"))
            if "/Kids" in n:
                stack.extend(n.Kids)
        assert vals["BuildingOccupancy_OperationsDescription_A"] == "Commercial general contractor."
        assert vals["CommercialPolicy_OperationsDescription_A"] == self.OPS
        assert data["BuildingOccupancy_OperationsDescription_A"] == self.OPS


# =============================================================================
# 5. Checked and NOT changed - pinned so nobody "fixes" them
# =============================================================================
class TestNotDefects:

    def test_the_125_vehicle_schedule_tick_is_the_clients_own(self):
        """`fix-form-stamping.md` lists VEHICLE SCHEDULE under "Correctly ticked
        on the same run, do not regress" on this one-Subaru package. The
        round-2 overflow rule belongs to the 127's "additional vehicles on the
        attached ACORD 129" box, not to this one."""
        assert _before("ACORD_125", "Policy_SectionAttached_VehicleScheduleIndicator_A") == "Yes"
        assert ps._INDICATOR_RULES["Policy_SectionAttached_VehicleScheduleIndicator"] == \
            ("auto_vin_schedule", "non-empty")

    def test_the_137_non_owned_employee_tick_has_its_evidence(self):
        assert _before("ACORD_137_CO", "Vehicle_NonOwnedGroup_EmployeeIndicator_A") == "Y"
        assert any("NUMBER OF EMPLOYEES" in ln for ln in TEXT["non_ownership"])
