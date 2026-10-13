"""Undo a fix made through "Open to fix" (owner, 9 Oct 2026).

The owner: after reopening a hard stop or warning, "the score should go back to what it
should be - the points that were credited after resolving should be deducted". Reopen
only ever undid a TYPED value (field mode, by deleting the producer's fact): a fix made
through a table (the location table behind the COPE checks, the loss history, the WC
classes) or an ACORD 101 note was left in place, so the stop stayed cleared and its
points stayed on the score while the screen said it was open again.

So a fix records a RECEIPT of exactly what it changed in the session - every fact and
flag whose value moved, and every generated-form box it rewrote - each with its value
before and after (`capture`, called by `resolve-issue` around the write, before the
re-score). "Open again" (`reopen-issue`) puts the before-values back (`plan_undo` /
`undo_fix`), but ONLY while every one of them still holds its after-value. If anything
has touched them since - another fix, a typed edit, a client answer - nothing is undone
and the caller is told so: an undo must never erase work done after it.

What makes that promise hold (the adversarial review of 9 Oct, each one reproduced):
  * Only the FIX's own writes are recorded. A fact another writer set in the same moment
    (a client's questionnaire answer, a document value) carries that writer's source and
    is left out, so an undo cannot delete it.
  * A bookkeeping dict shared by several tables (`_human_schedules`, one fingerprint per
    table) is recorded per entry: saving another table later does not block the undo.
  * A second fix of the same issue is folded into its receipt only when it starts where
    the first one ended. If anything else changed those values in between, the receipt
    is BLOCKED - undoing it would erase that change.
  * The receipt remembers the document set. After a document is added, excluded or
    reclassified the merge has been re-run on different evidence, so an old before-value
    may come from a document that is no longer in the package: the receipt is refused.
  * A form generated after the fix never saw the fix's boxes; on undo it is re-stamped
    from the restored facts (`arq_service._restamp_changed_boxes`), boxes a person typed
    left alone.
The receipt holds fact values, so it is encrypted at rest like `facts`
(`issue_fix_receipts`, one encrypted blob on the session row). `add_form` is never
recorded: reopening never removes a generated form.
"""
from __future__ import annotations

import copy
import json
import logging
from typing import Tuple

logger = logging.getLogger(__name__)

RECEIPTS_KEY = "issue_fix_receipts"
# JSON-safe marker for "the key was not there" (None is a real fact value).
MISSING = {"__absent__": True}
# A fact written by one of these is another writer's, never the fix's own.
_FIX_SOURCES = {None, "producer", "derived"}


def _same(a, b) -> bool:
    return json.dumps(a, sort_keys=True, default=str) == json.dumps(b, sort_keys=True, default=str)


def _absent(v) -> bool:
    return isinstance(v, dict) and v.get("__absent__") is True and len(v) == 1


def _empty(v) -> bool:
    return v is None or _absent(v) or (isinstance(v, str) and not v.strip()) \
        or (isinstance(v, (list, dict)) and not v)


def _source(v):
    return v.get("source") if isinstance(v, dict) and not _absent(v) else None


def _boxes(form: dict) -> dict:
    form = form if isinstance(form, dict) else {}
    return form.get("field_state") or form.get("mapped") or {}


def _box_state(form: dict, box: str) -> dict:
    form = form if isinstance(form, dict) else {}
    return {
        "value": _boxes(form).get(box),
        "label": (form.get("confidence") or {}).get(box),
        "client": box in set(form.get("client_filled_fields") or []),
    }


def _bookkeeping(key: str, *values) -> bool:
    """An internal dict fact (leading "_") recorded entry by entry."""
    return key.startswith("_") and all(isinstance(v, dict) and not _absent(v) or _absent(v) for v in values) \
        and any(isinstance(v, dict) and not _absent(v) for v in values)


def docs_fingerprint(session: dict) -> str:
    """The package's document set: which documents, their type, excluded / supporting-only."""
    docs = (session or {}).get("docs") or []
    rows = []
    for d in docs if isinstance(docs, list) else []:
        if not isinstance(d, dict):
            continue
        rows.append([str(d.get("doc_id") or d.get("filename") or ""),
                     str(d.get("doc_type") or d.get("document_type") or ""),
                     bool(d.get("excluded")), bool(d.get("supporting_only"))])
    return json.dumps(sorted(rows))


# ── Capture ──────────────────────────────────────────────────────────────────
def capture(before: dict, after: dict) -> dict:
    """What one write changed, between two reads of the session taken around it: the
    facts and flags it set, the bookkeeping entries it moved, and the generated forms'
    boxes it rewrote - each with its before and after. {} when nothing moved."""
    before, after = before or {}, after or {}
    receipt: dict = {"facts": {}, "subfacts": {}, "flags": {}, "boxes": {}}
    b_facts = before.get("facts") if isinstance(before.get("facts"), dict) else {}
    a_facts = after.get("facts") if isinstance(after.get("facts"), dict) else {}
    for key in set(b_facts) | set(a_facts):
        b, a = b_facts.get(key, MISSING), a_facts.get(key, MISSING)
        if _same(b, a):
            continue
        if _bookkeeping(key, b, a):
            b_d = b if not _absent(b) else {}
            a_d = a if not _absent(a) else {}
            for sub in set(b_d) | set(a_d):
                sb, sa = b_d.get(sub, MISSING), a_d.get(sub, MISSING)
                if not _same(sb, sa):
                    receipt["subfacts"].setdefault(key, {})[sub] = {"before": sb, "after": sa}
            continue
        if _source(a) not in _FIX_SOURCES:
            continue                   # another writer's value (a client answer, a document)
        receipt["facts"][key] = {"before": b, "after": a}
    b_flags = before.get("flags") if isinstance(before.get("flags"), dict) else {}
    a_flags = after.get("flags") if isinstance(after.get("flags"), dict) else {}
    for key in set(b_flags) | set(a_flags):
        b, a = b_flags.get(key, MISSING), a_flags.get(key, MISSING)
        if not _same(b, a):
            receipt["flags"][key] = {"before": b, "after": a}
    b_forms = before.get("generated_forms") or {}
    a_forms = after.get("generated_forms") or {}
    for fid, a_form in a_forms.items():
        if not isinstance(a_form, dict):
            continue
        b_form = b_forms.get(fid) if isinstance(b_forms.get(fid), dict) else None
        if b_form is None:
            continue                       # a form the write created (add_form): never undone
        names = (set(_boxes(a_form)) | set(_boxes(b_form))
                 | set(a_form.get("confidence") or {}) | set(b_form.get("confidence") or {}))
        for box in names:
            b, a = _box_state(b_form, box), _box_state(a_form, box)
            if b == a:
                continue
            # The fix stamps its own boxes "producer" and the boxes that derive from
            # its value with the engine's "filled"; an AI fill or a client answer
            # landing in the same moment carries its own label and is not the fix's.
            if a["label"] not in (None, "producer", "filled"):
                continue
            receipt["boxes"].setdefault(fid, {})[box] = {"before": b, "after": a}
    if not (receipt["facts"] or receipt["subfacts"] or receipt["flags"] or receipt["boxes"]):
        return {}
    receipt["forms_seen"] = sorted(fid for fid, f in a_forms.items() if isinstance(f, dict))
    receipt["docs"] = docs_fingerprint(after)
    return receipt


def _fold(older: dict, newer: dict, blocked: list) -> dict:
    """{key: change} of two writes as one; a key whose second write did not start where
    the first ended is noted in `blocked`."""
    merged = {k: dict(v) for k, v in (older or {}).items()}
    for k, ch in (newer or {}).items():
        if k in merged:
            if not _same(merged[k]["after"], ch["before"]):
                blocked.append(k)
            merged[k] = {"before": merged[k]["before"], "after": ch["after"]}
        else:
            merged[k] = dict(ch)
    return {k: v for k, v in merged.items() if not _same(v["before"], v["after"])}


def compose(older: dict, newer: dict) -> dict:
    """Two fixes of one issue as one: each key's earliest before and latest after. When
    something else changed a key between them, or the documents changed, the result is
    BLOCKED - taking it back would erase that change."""
    older, newer = older or {}, newer or {}
    blocked: list = []
    out: dict = {
        "facts": _fold(older.get("facts"), newer.get("facts"), blocked),
        "flags": _fold(older.get("flags"), newer.get("flags"), blocked),
        "subfacts": {}, "boxes": {},
    }
    for section in ("subfacts", "boxes"):
        for name in set(older.get(section) or {}) | set(newer.get(section) or {}):
            folded = _fold((older.get(section) or {}).get(name), (newer.get(section) or {}).get(name), blocked)
            if folded:
                out[section][name] = folded
    if older.get("docs") and newer.get("docs") and older["docs"] != newer["docs"]:
        blocked.append("documents")
    if older.get("blocked") or newer.get("blocked") or blocked:
        out["blocked"] = True
    out["forms_seen"] = sorted(set(older.get("forms_seen") or []) | set(newer.get("forms_seen") or []))
    out["docs"] = newer.get("docs") or older.get("docs")
    if not (out["facts"] or out["flags"] or out["subfacts"] or out["boxes"]):
        return {}
    return out


# ── Storage (encrypted, like facts) ──────────────────────────────────────────
def load_receipts(session: dict) -> dict:
    raw = (session or {}).get(RECEIPTS_KEY)
    if not raw:
        return {}
    if isinstance(raw, dict):
        return raw
    try:
        from utils.crypto import decrypt_field
        data = json.loads(decrypt_field(raw))
        return data if isinstance(data, dict) else {}
    except Exception as exc:                                   # noqa: BLE001
        logger.warning("issue_fix_undo: receipts unreadable (%s) - treated as none", exc)
        return {}


def dump_receipts(receipts: dict) -> str:
    if not receipts:
        return ""
    from utils.crypto import encrypt_field
    return encrypt_field(json.dumps(receipts, default=str))


async def record_fix(session_id: str, issue_id: str, receipt: dict) -> None:
    """Keep what one fix changed, under the issue it fixed."""
    if not (issue_id and receipt):
        return
    from repositories.session_repository import get_processing_session, upd_processing_session
    session = await get_processing_session(session_id)
    receipts = load_receipts(session)
    folded = compose(receipts[issue_id], receipt) if issue_id in receipts else receipt
    if folded:
        receipts[issue_id] = folded
    else:
        receipts.pop(issue_id, None)
    await upd_processing_session(session_id, {RECEIPTS_KEY: dump_receipts(receipts)})


# ── Undo ─────────────────────────────────────────────────────────────────────
def plan_undo(session: dict, receipt: dict) -> Tuple[str, dict]:
    """("changed", {"changed": [...]}) when anything the fix wrote has moved since (or the
    receipt is blocked, or the documents changed); else ("ok", plan) - the facts to set and
    delete, the flags and the form boxes."""
    session = session or {}
    facts = session.get("facts") if isinstance(session.get("facts"), dict) else {}
    flags = session.get("flags") if isinstance(session.get("flags"), dict) else {}
    forms = session.get("generated_forms") or {}
    if receipt.get("blocked"):
        return "changed", {"changed": ["a later change"]}
    if receipt.get("docs") and receipt["docs"] != docs_fingerprint(session):
        return "changed", {"changed": ["documents"]}
    changed = []
    for key, ch in (receipt.get("facts") or {}).items():
        if not _same(facts.get(key, MISSING), ch["after"]):
            changed.append(key)
    for key, subs in (receipt.get("subfacts") or {}).items():
        now = facts.get(key) if isinstance(facts.get(key), dict) else {}
        for sub, ch in subs.items():
            if not _same(now.get(sub, MISSING), ch["after"]):
                changed.append(f"{key}.{sub}")
    for key, ch in (receipt.get("flags") or {}).items():
        if not _same(flags.get(key, MISSING), ch["after"]):
            changed.append(f"flag:{key}")
    for fid, bx in (receipt.get("boxes") or {}).items():
        form = forms.get(fid)
        if not isinstance(form, dict):
            changed.append(fid)
            continue
        for box, ch in bx.items():
            if _box_state(form, box) != ch["after"]:
                changed.append(f"{fid}:{box}")
    if changed:
        return "changed", {"changed": sorted(changed)}

    set_facts, delete_facts = {}, []
    for key, ch in (receipt.get("facts") or {}).items():
        if _empty(ch["before"]):
            delete_facts.append(key)          # the additive facts write cannot store "empty"
        else:
            set_facts[key] = ch["before"]
    for key, subs in (receipt.get("subfacts") or {}).items():
        now = dict(facts.get(key)) if isinstance(facts.get(key), dict) else {}
        for sub, ch in subs.items():
            if _absent(ch["before"]):
                now.pop(sub, None)
            else:
                now[sub] = ch["before"]
        if now:
            set_facts[key] = now
        else:
            delete_facts.append(key)
    new_flags = dict(flags)
    for key, ch in (receipt.get("flags") or {}).items():
        if _absent(ch["before"]):
            new_flags.pop(key, None)
        else:
            new_flags[key] = ch["before"]
    form_updates = {}
    for fid, bx in (receipt.get("boxes") or {}).items():
        form = forms[fid]
        state = dict(_boxes(form))
        conf = dict(form.get("confidence") or {})
        cff = list(form.get("client_filled_fields") or [])
        for box, ch in bx.items():
            b = ch["before"]
            if b["value"] is None:
                state.pop(box, None)
            else:
                state[box] = b["value"]
            if b["label"] is None:
                conf.pop(box, None)
            else:
                conf[box] = b["label"]
            if b["client"] and box not in cff:
                cff.append(box)
            elif not b["client"] and box in cff:
                cff.remove(box)
        form_updates[fid] = {"field_state": state, "confidence": conf, "client_filled_fields": cff,
                             "_pdf_cache_hash": "", "pdf_bytes": None}
    return "ok", {"set_facts": set_facts, "delete_facts": delete_facts,
                  "flags": new_flags if receipt.get("flags") else None, "forms": form_updates}


def _restamp_late_forms(session: dict, receipt: dict, plan: dict) -> None:
    """Forms generated AFTER the fix printed its values from the facts; re-stamp them from
    the restored facts (boxes a person typed stay) and add them to the plan."""
    forms = session.get("generated_forms") or {}
    seen = set(receipt.get("forms_seen") or [])
    late = {fid: copy.deepcopy(f) for fid, f in forms.items() if isinstance(f, dict) and fid not in seen}
    if not late:
        return
    try:
        from services.arq_service import _answer_provenance, _restamp_changed_boxes
        from services.form_service import package_form_ids
        facts = dict(session.get("facts") or {})
        flags = dict(session.get("flags") or {})
        restored = {**facts, **plan["set_facts"]}
        for key in plan["delete_facts"]:
            restored.pop(key, None)
        restored_flags = plan["flags"] if plan["flags"] is not None else flags
        try:
            pkg = package_form_ids(session) or list(forms.keys())
        except Exception:                                      # noqa: BLE001
            pkg = list(forms.keys())
        view_before = {**facts, **flags, "_package_form_ids": pkg}
        view_after = {**restored, **restored_flags, "_package_form_ids": pkg}
        # The fixed facts' OWN boxes move even though generation labelled them
        # "producer" (the fix was the producer's answer) - while they still print
        # the fix; a box a person changed after generation keeps their value.
        # Each restored box wears the label of whoever supplied its restored value
        # (a document's -> "filled", an earlier client answer -> "client_arq").
        groups: dict = {}
        for key in (receipt.get("facts") or {}):
            groups.setdefault(_answer_provenance(restored, key), set()).add(key)
        touched: set = set()
        for label, own in (sorted(groups.items()) or [("filled", set())]):
            touched.update(_restamp_changed_boxes(
                late, view_before, view_after, own_keys=own, own_value=None,
                provenance=label, scope=None, keep_edited_own=True) or [])
    except Exception as exc:                                   # noqa: BLE001
        logger.warning("issue_fix_undo: late forms not re-stamped (%s)", exc)
        return
    for fid in touched:
        form = late.get(fid)
        if isinstance(form, dict):
            form["_pdf_cache_hash"] = ""
            form["pdf_bytes"] = None
            plan["forms"][fid] = form


async def undo_fix(session_id: str, issue_id: str) -> Tuple[str, dict]:
    """Take back what the fixes of `issue_id` changed. Returns
    ("none", {}) - no receipt (a fix from before receipts existed, or a dismiss);
    ("changed", {"changed": [...]}) - something moved since, nothing undone;
    ("undone", {"receipt": receipt}) - every before-value is back."""
    if not issue_id:
        return "none", {}
    from repositories.session_repository import get_processing_session, upd_processing_session
    session = await get_processing_session(session_id)
    receipts = load_receipts(session)
    receipt = receipts.get(issue_id)
    if not receipt:
        return "none", {}
    state, plan = plan_undo(session, receipt)
    if state != "ok":
        return state, plan
    _restamp_late_forms(session, receipt, plan)
    receipts.pop(issue_id, None)
    updates: dict = {RECEIPTS_KEY: dump_receipts(receipts)}
    if plan["set_facts"]:
        updates["facts"] = plan["set_facts"]
    if plan["flags"] is not None:
        updates["flags"] = plan["flags"]
    if plan["forms"]:
        updates["generated_forms"] = plan["forms"]
    await upd_processing_session(session_id, updates, delete_facts=plan["delete_facts"] or None)
    logger.info("issue_fix_undo: undone issue=%s facts=%d flags=%d forms=%d session=%s",
                issue_id, len(receipt.get("facts") or {}), len(receipt.get("flags") or {}),
                len(plan["forms"]), session_id)
    return "undone", {"receipt": receipt}
