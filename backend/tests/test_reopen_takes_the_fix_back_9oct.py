"""Reopening a fixed hard stop / warning takes the fix - and its points - back (owner, 9 Oct 2026).

The owner: "after reopening a hard stop or warning, the score should go back to what it
should be - the points that were credited after resolving should be deducted."

Measured before the fix: `reopen-issue` undid only a TYPED value (field mode, by deleting
the producer's fact - not even restoring what it replaced). A fix through a table (the
location table behind the COPE checks, loss history, WC classes) or an ACORD 101 note
was left in place: the stop stayed cleared and its points stayed on the score while the
screen said "open" again.

Now every fix records what it changed (services/issue_fix_undo.py) and "Open again"
puts all of it back - unless something moved since, when nothing is undone and the
caller is told so. These tests drive the REAL resolve / reopen routes and the real
scorer against an in-memory session row that merges writes the way the real store does.
"""
from __future__ import annotations

import asyncio
import copy
import json
import os
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import patch

import pytest

os.environ.setdefault("FIELD_ENCRYPTION_KEY", "kZ0aQ7Yy3pR8mN2vB6xL9tJ4hG1sD5fW8cE0uI3oA7k=")

import repositories.session_repository as sr          # noqa: E402
import routes.audit_routes as ar                      # noqa: E402
import services.arq_service as arq                    # noqa: E402
import services.audit_service as au                   # noqa: E402
import services.issue_fix_undo as undo                # noqa: E402
from models.schemas import ReopenIssueRequest, ResolveIssueRequest   # noqa: E402

_SID = "sid-reopen-9oct"
_UID = "u-reopen-9oct"
_EXPIRED_CODE = "legacy_policy_term_expired"
_FRONT = Path(__file__).resolve().parents[2] / "frontend" / "src"


def _mdY(dt):
    return dt.strftime("%m/%d/%Y")


def _producer(value):
    return {"value": value, "source": "producer", "confidence": "filled"}


def _row(**over):
    """A package whose producer-typed term ended 90 days ago - a hard stop capping at 60."""
    exp = datetime.now() - timedelta(days=90)
    eff = exp - timedelta(days=365)
    base = {
        "user_id": _UID,
        "facts": {
            "producer_name": "Best Agency", "applicant_name": "Acme LLC",
            "mailing_address": "1 Main St, Denver, CO 80202",
            "lines_of_business": "General Liability", "entity_type": "LLC",
            "contact_phone": "303-555-0100", "contact_name": "Pat Doe",
            "fein": "12-3456789", "operations_description": "Electrical contracting",
            "total_revenue": "$1,200,000", "num_employees": "12",
            "years_in_business": "8", "naics_code": "238210",
            "effective_date": _producer(_mdY(eff)),
            "expiration_date": _producer(_mdY(exp)),
        },
        "flags": {"has_general_liability": True},
        "hard_stops": [], "soft_stops": [],
        "recommendations": [{"form_id": "ACORD_125"}],
        "cross_form_issues": [], "structured_issues": [], "docs": [], "integrity": {},
        "generated_forms": {"ACORD_125": {
            "mapped": {"NamedInsured_FullName_A": "Acme LLC"},
            "confidence": {"NamedInsured_FullName_A": "ai_high"},
            "schema": {"NamedInsured_FullName_A": {"ft": "/Tx", "tu": "Enter name"}},
        }},
        "selected_form_ids": ["ACORD_125"], "underwriting_consistency": {},
    }
    base.update(over)
    return base


class _Session:
    """The REAL routes and recalculation against an in-memory row that merges writes
    the way `upd_processing_session` does: facts additively (last write wins per key,
    empty values skipped), `delete_facts` after the merge, generated forms per form;
    every other key replaced."""

    def __init__(self, row):
        self.store = copy.deepcopy(row)
        self.statuses = []

    async def _get(self, _sid):
        return copy.deepcopy(self.store)

    async def _upd(self, _sid, payload, delete_facts=None):
        for k, v in (payload or {}).items():
            v = copy.deepcopy(v)
            if k == "facts" and isinstance(v, dict):
                merged = sr.resolve_facts_write(self.store, v, _sid)
                if merged is not None:
                    self.store["facts"] = merged
            elif k == "generated_forms" and isinstance(v, dict):
                gen = self.store.setdefault("generated_forms", {})
                for fid, data in v.items():
                    if fid in gen and isinstance(gen[fid], dict):
                        gen[fid].update(data)
                    else:
                        gen[fid] = data
            else:
                self.store[k] = v
        for k in (delete_facts or []):
            self.store.get("facts", {}).pop(k, None)
        return True

    def run(self, coro_fn, *args, **kwargs):
        async def _none(*_a, **_k):
            return None

        async def _empty(*_a, **_k):
            return []

        async def _status(**kw):
            self.statuses.append(kw)
            return True

        async def _no_credits(*_a, **_k):
            return 0, []

        with patch.object(sr, "get_processing_session", self._get), \
             patch.object(sr, "upd_processing_session", self._upd), \
             patch.object(ar, "get_processing_session", self._get), \
             patch.object(ar, "log_field_change", _none), \
             patch.object(ar, "set_issue_status", _status), \
             patch.object(au, "log_audit_event", _none), \
             patch.object(au, "log_sqs_snapshot_if_changed", _none), \
             patch.object(au, "get_open_recommendations", _empty), \
             patch.object(au, "mark_recommendation_resolved", _none), \
             patch.object(au, "sync_recommendation_cards", _none), \
             patch.object(au, "active_score_credits", _no_credits):
            return asyncio.run(coro_fn(*args, **kwargs))

    def recalc(self):
        return self.run(arq.recalculate_session_scores, _SID)

    def body(self, route, req):
        return json.loads(self.run(route, req, current_user={"id": _UID}).body)

    def score(self):
        return (self.store.get("package_sqs") or {}).get("package_sqs_score")

    def fix(self, issue_id, **req):
        return self.body(ar.resolve_issue, ResolveIssueRequest(session_id=_SID, issue_id=issue_id, **req))

    def reopen(self, issue_id, code=None, legacy_clear=False):
        return self.body(ar.reopen_issue, ReopenIssueRequest(session_id=_SID, issue_id=issue_id, code=code,
                                                             message="m", legacy_clear=legacy_clear))


def _fresh(**over):
    s = _Session(_row(**over))
    s.recalc()
    return s


def _uncapped_property_package():
    """A package whose term is current (no expired-term cap) and which carries property -
    so a location-table fix moves its score (measured: 47 -> 48)."""
    row = _row()
    row["facts"]["effective_date"] = _producer(_mdY(datetime.now() - timedelta(days=165)))
    row["facts"]["expiration_date"] = _producer(_mdY(datetime.now() + timedelta(days=200)))
    row["flags"]["has_property_coverage"] = True
    s = _Session(row)
    s.recalc()
    return s


_NEW_TERM = _mdY(datetime.now() + timedelta(days=300))
_ROWS = [{"address_line1": "100 Main St", "address_city": "Denver", "address_state": "CO",
          "address_zip": "80202", "year_built": "1999", "construction_type": "Frame",
          "building_value": "500000", "bpp_value": "100000", "roof_year": "2015",
          "protection_class": "3", "sprinkler": "Yes", "occupancy": "Office"}]


# ══ The owner's case: the points come off again ═══════════════════════════════
@pytest.mark.parametrize("over", [{}, {"generated_forms": {}, "selected_form_ids": []}],
                         ids=["editor", "pre-form"])
def test_reopening_a_typed_fix_puts_the_score_back_exactly(over):
    s = _fresh(**over)
    before_score, before_term = s.score(), copy.deepcopy(s.store["facts"]["expiration_date"])
    assert s.store["package_sqs"]["cap_applied"] == 60
    out = s.fix("iss-term", mode="field", field="expiration_date", value=_NEW_TERM, code=_EXPIRED_CODE)
    assert out["success"] is True and s.score() > before_score           # the fix earned points
    back = s.reopen("iss-term", code=_EXPIRED_CODE)
    assert back["cleared"] is True
    assert s.score() == before_score                                     # ...and they came off
    assert s.store["package_sqs"]["cap_applied"] == 60
    # The value it REPLACED is back - not a blank (the old reopen deleted the fact).
    assert s.store["facts"]["expiration_date"] == before_term
    assert undo.load_receipts(s.store) == {}                             # the receipt is used up


def test_a_fixed_form_box_comes_back_too():
    # The editor: the fix stamps its value into the form; the undo puts the box back.
    form = {"mapped": {"NamedInsured_FullName_A": "Acme LLC", "Policy_ExpirationDate_A": ""},
            "confidence": {"NamedInsured_FullName_A": "ai_high"},
            "schema": {"NamedInsured_FullName_A": {"ft": "/Tx", "tu": "Enter name"},
                       "Policy_ExpirationDate_A": {"ft": "/Tx", "tu": "Enter date: The policy expiration date."}}}
    s = _fresh(generated_forms={"ACORD_125": form})
    before_box = undo._box_state(s.store["generated_forms"]["ACORD_125"], "Policy_ExpirationDate_A")
    s.fix("iss-term", mode="field", field="expiration_date", value=_NEW_TERM, code=_EXPIRED_CODE)
    receipt = undo.load_receipts(s.store)["iss-term"]
    assert "Policy_ExpirationDate_A" in receipt["boxes"]["ACORD_125"]   # the fix stamped the box
    assert s.reopen("iss-term", code=_EXPIRED_CODE)["cleared"] is True
    assert undo._box_state(s.store["generated_forms"]["ACORD_125"], "Policy_ExpirationDate_A") == before_box


def test_reopening_a_table_fix_takes_its_rows_and_its_points_back():
    s = _uncapped_property_package()
    before_score = s.score()
    out = s.fix("iss-cope", mode="schedule", schedule_key="property_locations", rows=_ROWS)
    assert out["success"] is True and s.store["facts"].get("property_locations")
    assert s.score() > before_score                                      # the table earned a point
    receipt = undo.load_receipts(s.store)["iss-cope"]
    # what the table derived (the location list, the COPE facts) is in the receipt too
    assert {"property_locations", "locations", "year_built", "construction_type"} <= set(receipt["facts"])
    back = s.reopen("iss-cope")
    assert back["cleared"] is True
    for key in ("property_locations", "locations", "year_built", "construction_type"):
        assert key not in s.store["facts"], key                          # ...and taken back
    assert s.score() == before_score


def test_reopening_a_note_takes_the_note_back():
    # A note does not move this package's score (the score rule is proven by the typed
    # and table fixes above); what matters here is that the note itself comes off.
    s = _fresh()
    out = s.fix("iss-note", mode="narrative", text="The insured renewed early; the new term starts next month.")
    assert out["success"] is True and s.store["facts"].get("additional_remarks_text")
    back = s.reopen("iss-note")
    assert back["cleared"] is True
    assert "additional_remarks_text" not in s.store["facts"]


def test_two_fixes_of_one_issue_are_taken_back_together():
    s = _fresh()
    before_term = copy.deepcopy(s.store["facts"]["expiration_date"])
    s.fix("iss-term", mode="field", field="expiration_date", value=_NEW_TERM, code=_EXPIRED_CODE)
    later = _mdY(datetime.now() + timedelta(days=330))
    s.fix("iss-term", mode="field", field="expiration_date", value=later, code=_EXPIRED_CODE)
    assert len(undo.load_receipts(s.store)) == 1
    assert s.reopen("iss-term", code=_EXPIRED_CODE)["cleared"] is True
    assert s.store["facts"]["expiration_date"] == before_term


def test_a_value_changed_after_the_fix_is_never_erased_by_reopening_it():
    s = _fresh()
    original = copy.deepcopy(s.store["facts"]["expiration_date"])
    s.fix("iss-a", mode="field", field="expiration_date", value=_NEW_TERM, code=_EXPIRED_CODE)
    after_a = copy.deepcopy(s.store["facts"]["expiration_date"])
    later = _mdY(datetime.now() + timedelta(days=330))
    s.fix("iss-b", mode="field", field="expiration_date", value=later, code=_EXPIRED_CODE)
    after_b = copy.deepcopy(s.store["facts"]["expiration_date"])
    score_b = s.score()
    # A's value was overwritten by B: undoing A would erase B's work.
    refused = s.reopen("iss-a", code=_EXPIRED_CODE)
    assert refused["cleared"] is False and refused["changed_since"] is True
    assert s.store["facts"]["expiration_date"] == after_b and s.score() == score_b
    assert not s.statuses                                               # the status was left alone
    # Last in, first out: B comes off, then A can.
    assert s.reopen("iss-b", code=_EXPIRED_CODE)["cleared"] is True
    assert s.store["facts"]["expiration_date"] == after_a
    assert s.reopen("iss-a", code=_EXPIRED_CODE)["cleared"] is True
    assert s.store["facts"]["expiration_date"] == original


def test_a_second_fix_after_another_writer_never_erases_that_writer():
    # 9 Oct review: fix X, then Y on the same value, then X again. Folding X's two
    # fixes into one (before T0, after T3) took the value back past Y's change.
    s = _fresh()
    s.fix("iss-x", mode="field", field="expiration_date", value=_NEW_TERM, code=_EXPIRED_CODE)
    s.fix("iss-y", mode="field", field="expiration_date",
          value=_mdY(datetime.now() + timedelta(days=320)), code=_EXPIRED_CODE)
    s.fix("iss-x", mode="field", field="expiration_date",
          value=_mdY(datetime.now() + timedelta(days=340)), code=_EXPIRED_CODE)
    assert undo.load_receipts(s.store)["iss-x"].get("blocked") is True
    now = copy.deepcopy(s.store["facts"]["expiration_date"])
    refused = s.reopen("iss-x", code=_EXPIRED_CODE)
    assert refused["cleared"] is False and refused["changed_since"] is True
    assert s.store["facts"]["expiration_date"] == now


def test_saving_another_table_later_does_not_block_the_undo():
    # 9 Oct review: one bookkeeping dict (`_human_schedules`) holds a fingerprint per
    # table; it is recorded entry by entry, so a later WC table save leaves the
    # location table's undo free.
    s = _uncapped_property_package()
    before = copy.deepcopy(s.store["facts"])
    s.fix("iss-cope", mode="schedule", schedule_key="property_locations", rows=_ROWS)
    s.fix("iss-wc", mode="schedule", schedule_key="wc_class_codes",
          rows=[{"code": "5190", "description": "Electrical wiring", "state": "CO", "payroll": "400000"}])
    back = s.reopen("iss-cope")
    assert back["cleared"] is True                                      # not "changed since"
    assert "property_locations" not in s.store["facts"]
    assert s.store["facts"].get("wc_class_codes")                       # the WC table is untouched
    hs = s.store["facts"].get("_human_schedules") or {}
    assert "property_locations" not in hs and "wc_class_codes" in hs
    assert ("_human_schedules" in before) == bool(hs) or "wc_class_codes" in hs


def test_a_document_change_retires_the_undo():
    # 9 Oct review: after the documents change the merge ran on other evidence; an
    # old before-value may come from a document no longer in the package.
    s = _fresh(docs=[{"doc_id": "d1", "doc_type": "dec_page"}])
    s.fix("iss-term", mode="field", field="expiration_date", value=_NEW_TERM, code=_EXPIRED_CODE)
    s.store["docs"] = [{"doc_id": "d1", "doc_type": "dec_page", "excluded": True}]
    now = copy.deepcopy(s.store["facts"]["expiration_date"])
    refused = s.reopen("iss-term", code=_EXPIRED_CODE)
    assert refused["cleared"] is False and refused["changed_since"] is True
    assert s.store["facts"]["expiration_date"] == now


def _late_form(box_value, label):
    """The ACORD 125 a generation AFTER the fix produced: its term box as given."""
    return {"ACORD_125": {
        "mapped": {"Policy_ExpirationDate_A": box_value, "NamedInsured_FullName_A": "Acme LLC"},
        "field_state": {"Policy_ExpirationDate_A": box_value, "NamedInsured_FullName_A": "Acme LLC"},
        "confidence": {"Policy_ExpirationDate_A": label, "NamedInsured_FullName_A": "ai_high"},
        "schema": {"NamedInsured_FullName_A": {"ft": "/Tx", "tu": "Enter name"},
                   "Policy_ExpirationDate_A": {"ft": "/Tx", "tu": "Enter date: The policy expiration date."}}}}


# Generation labels a box printing a producer's answer "producer" - and the fix IS a
# producer's answer. The 9 Oct review reproduced that label keeping the fix on the
# form after "Open again" (S2): the restamp treated it as a person's own value.
@pytest.mark.parametrize("label", ["filled", "producer"])
def test_a_form_generated_after_the_fix_is_restamped_on_undo(label):
    # 9 Oct review: a pre-form fix, then generation printed its value; reopening
    # reverted the facts while the form kept printing the fix.
    s = _fresh(generated_forms={}, selected_form_ids=[])
    before = s.store["facts"]["expiration_date"]["value"]
    s.fix("iss-term", mode="field", field="expiration_date", value=_NEW_TERM, code=_EXPIRED_CODE)
    s.store["generated_forms"] = _late_form(_NEW_TERM, label)            # "generation"
    assert s.reopen("iss-term", code=_EXPIRED_CODE)["cleared"] is True
    form = s.store["generated_forms"]["ACORD_125"]
    assert form["field_state"]["Policy_ExpirationDate_A"] == before      # the value it replaced
    # labelled by who supplied the RESTORED value: here the producer's earlier term
    assert form["confidence"]["Policy_ExpirationDate_A"] == "producer"
    assert s.store["facts"]["expiration_date"]["value"] == before


def test_a_late_box_a_person_changed_after_generation_keeps_their_value_on_undo():
    s = _fresh(generated_forms={}, selected_form_ids=[])
    s.fix("iss-term", mode="field", field="expiration_date", value=_NEW_TERM, code=_EXPIRED_CODE)
    s.store["generated_forms"] = _late_form("12/31/2099", "producer")   # typed over afterwards
    assert s.reopen("iss-term", code=_EXPIRED_CODE)["cleared"] is True
    form = s.store["generated_forms"]["ACORD_125"]
    assert form["field_state"]["Policy_ExpirationDate_A"] == "12/31/2099"
    assert form["confidence"]["Policy_ExpirationDate_A"] == "producer"


def test_a_fix_from_before_receipts_reopens_the_old_way_only_where_asked():
    s = _fresh()
    s.fix("iss-old", mode="field", field="expiration_date", value=_NEW_TERM, code=_EXPIRED_CODE)
    s.store.pop(undo.RECEIPTS_KEY, None)                               # fixed before 9 Oct
    kept = copy.deepcopy(s.store["facts"]["expiration_date"])
    # The review screen never asks for the old clear: nothing is deleted.
    plain = s.reopen("iss-old", code=_EXPIRED_CODE)
    assert plain["cleared"] is False and s.store["facts"]["expiration_date"] == kept
    # The editor's Cross-Form panel does: the producer's value is cleared, as before.
    back = s.reopen("iss-old", code=_EXPIRED_CODE, legacy_clear=True)
    assert back["cleared"] is True and "expiration_date" not in s.store["facts"]


def test_nothing_undone_and_nothing_firing_keeps_the_stored_status():
    # 9 Oct review: a status-only reopen of an item that no longer fires stored
    # "open" while the screen put "resolved" back - the row vanished on reload.
    s = _fresh()
    out = s.reopen("iss-gone", code=None)
    assert out == {"success": True, "cleared": False, "still_live": False}
    assert not s.statuses


def test_the_receipt_is_encrypted_at_rest():
    s = _fresh()
    s.fix("iss-term", mode="field", field="expiration_date", value=_NEW_TERM, code=_EXPIRED_CODE)
    raw = s.store[undo.RECEIPTS_KEY]
    assert isinstance(raw, str) and raw.startswith("enc:")
    assert _NEW_TERM not in raw and "expiration_date" not in raw
    assert "expiration_date" in undo.load_receipts(s.store)["iss-term"]["facts"]


def test_adding_a_form_is_never_recorded_for_undo():
    src = Path(ar.__file__).read_text(encoding="utf-8")
    body = src[src.index("async def resolve_issue("):src.index("@router.post(\"/api/audit/reopen-issue\")")]
    assert 'if mode != "add_form" and req.issue_id and _pre_session is not None:' in body
    # recorded between the write and the re-score
    assert body.index("record_fix(req.session_id, req.issue_id, _receipt)") < \
        body.index("impact = await recalculate_session_scores(req.session_id)")


# ══ The rules, unit by unit ═══════════════════════════════════════════════════
def _sess(facts=None, flags=None, forms=None):
    return {"facts": facts or {}, "flags": flags or {}, "generated_forms": forms or {}}


def test_capture_records_only_what_the_fix_wrote():
    before = _sess({"a": "1", "gone": "x", "same": {"value": 1}, "client": {"value": "old", "source": "client_arq"},
                    "_human_schedules": {"property_locations": "fp1", "wc_class_codes": "fpw"}},
                   {"f": True},
                   {"F": {"field_state": {"b1": "", "b2": "keep", "ai": ""}, "confidence": {},
                          "client_filled_fields": []}})
    after = _sess({"a": {"value": "2", "source": "producer"}, "new": [1], "same": {"value": 1},
                   "client": {"value": "typed by the client", "source": "client_arq"},
                   "_human_schedules": {"property_locations": "fp2", "wc_class_codes": "fpw"}},
                  {"f": True, "g": False},
                  {"F": {"field_state": {"b1": "x", "b2": "keep", "ai": "guess"},
                         "confidence": {"b1": "producer", "ai": "ai_verified"}, "client_filled_fields": []},
                   "NEW": {"field_state": {"z": "1"}}})
    r = undo.capture(before, after)
    # another writer's value (a client answer landing in the same moment) is left out
    assert set(r["facts"]) == {"a", "gone", "new"}
    assert r["facts"]["gone"]["after"] == undo.MISSING and r["facts"]["new"]["before"] == undo.MISSING
    # a bookkeeping dict is recorded entry by entry
    assert r["subfacts"] == {"_human_schedules": {"property_locations": {"before": "fp1", "after": "fp2"}}}
    assert set(r["flags"]) == {"g"}
    # an AI-filled box is not the fix's; a form the write created is never recorded
    assert r["boxes"] == {"F": {"b1": {"before": {"value": "", "label": None, "client": False},
                                       "after": {"value": "x", "label": "producer", "client": False}}}}
    assert r["forms_seen"] == ["F", "NEW"] and "docs" in r
    assert undo.capture(before, copy.deepcopy(before)) == {}


def test_compose_folds_two_fixes_and_blocks_a_gap():
    def rec(facts):
        return {"facts": facts, "flags": {}, "subfacts": {}, "boxes": {}, "forms_seen": [], "docs": "d"}
    one = rec({"a": {"before": "0", "after": "1"}, "b": {"before": "x", "after": "y"}})
    two = rec({"a": {"before": "1", "after": "2"}, "b": {"before": "y", "after": "x"}})
    folded = undo.compose(one, two)
    assert folded["facts"] == {"a": {"before": "0", "after": "2"}} and not folded.get("blocked")
    back = rec({"a": {"before": "1", "after": "0"}, "b": {"before": "y", "after": "x"}})
    assert undo.compose(one, back) == {}                               # put back by hand: nothing left
    # something else changed "a" between the two fixes (1 -> 5): folding would erase it
    gap = rec({"a": {"before": "5", "after": "6"}})
    assert undo.compose(one, gap)["blocked"] is True
    # the documents changed between the two fixes
    assert undo.compose(one, {**two, "docs": "other"})["blocked"] is True


def test_plan_undo_restores_or_refuses():
    receipt = {"facts": {"a": {"before": {"value": "0"}, "after": {"value": "1"}},
                         "n": {"before": undo.MISSING, "after": ["row"]}},
               "subfacts": {"_hs": {"t1": {"before": undo.MISSING, "after": "fp"}}},
               "flags": {"f": {"before": undo.MISSING, "after": True}},
               "boxes": {"F": {"b": {"before": {"value": "", "label": None, "client": False},
                                     "after": {"value": "1", "label": "producer", "client": False}}}},
               "docs": undo.docs_fingerprint({})}
    now = _sess({"a": {"value": "1"}, "n": ["row"], "x": "y", "_hs": {"t1": "fp", "t2": "other"}},
                {"f": True, "k": 1},
                {"F": {"field_state": {"b": "1"}, "confidence": {"b": "producer"}}})
    state, plan = undo.plan_undo(now, receipt)
    assert state == "ok"
    assert plan["set_facts"] == {"a": {"value": "0"}, "_hs": {"t2": "other"}} and plan["delete_facts"] == ["n"]
    assert plan["flags"] == {"k": 1}
    assert plan["forms"]["F"]["field_state"] == {"b": ""} and plan["forms"]["F"]["confidence"] == {}
    assert plan["forms"]["F"]["pdf_bytes"] is None                     # the PDF is redrawn
    for moved in ({"facts": {**now["facts"], "a": {"value": "9"}}},
                  {"facts": {**now["facts"], "_hs": {"t1": "changed", "t2": "other"}}},
                  {"flags": {"k": 1}},
                  {"generated_forms": {"F": {"field_state": {"b": "typed later"}, "confidence": {"b": "producer"}}}},
                  {"generated_forms": {}},
                  {"docs": [{"doc_id": "added"}]}):
        state, info = undo.plan_undo({**now, **moved}, receipt)
        assert state == "changed" and info["changed"], moved
    assert undo.plan_undo(now, {**receipt, "blocked": True})[0] == "changed"


def test_an_unreadable_receipt_blob_is_treated_as_none():
    assert undo.load_receipts({undo.RECEIPTS_KEY: "enc:not-a-token"}) == {}
    assert undo.load_receipts({}) == {}
    assert undo.load_receipts({undo.RECEIPTS_KEY: undo.dump_receipts({"i": {"facts": {}}})}) == {"i": {"facts": {}}}


# ══ The screen ════════════════════════════════════════════════════════════════
def test_the_fix_window_files_the_fix_under_the_id_open_again_uses():
    modal = (_FRONT / "components" / "form" / "AcordModal.jsx").read_text(encoding="utf-8")
    assert "? { ...issOrCluster, issue_id: issueIdOf(issOrCluster) }" in modal
    reopen = modal[modal.index("const handleReopenIssue = async"):modal.index("const reopenFromResolved")]
    assert "data.changed_since" in reopen
    assert "Use Open to fix to change them." in reopen
    assert "—" not in reopen
