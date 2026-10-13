"""form_dry_run.py - "Before you generate": the download review's form checks,
run BEFORE the forms exist (7 Oct 2026, Choice Electric #27).

Brent: *"[the download review] is still showing up when we attempt to download
all forms. We have already asked for these items to be addressed at the start
of the packaging and not keep it at the end ... 176 items flagged is a lot ...
these are hard stops. This should all be brought up sooner. Please get these
earlier in the workflow and ensure they are accurate requests to complete."*

The form checks - field QA's download hard blocks (ACORD 140's per-building
COPE gate, placeholder values), the required-but-empty boxes, the needs-
attention "Missing" list - read STAMPED forms, so they could only appear once
the forms were generated: at the download. This module stamps the forms that
will be generated BEFORE generation and runs the same checks on them.

ONE DOOR, NOT A SECOND COPY
---------------------------
* The stamp is the real `pdf_service.map_facts_to_form` - Pass 1 / 1.5, every
  resolver, every post-fill guard, the completeness gates - with the gap fill
  treated as having answered nothing and `allow_llm=False`. No model call, no
  network.
* The checks are the download review's own functions:
  `field_qa.run_field_qa` (which the download gate's `check_hard_block` reads)
  and `needs_attention.needs_attention_for_session` (the review's live list).
  So a promise made here is the review's verdict on the same facts.

ACCURATE REQUESTS ONLY (the accuracy rule - see CHANGES.md "DESIGN")
--------------------------------------------------------------------
Every finding is classified once, first matching reason wins. Dropped: the
applicant's signature steps, values to verify, values a guard held back,
questions the documents are read for at generation (`left_to_documents`).
Every other finding is a CANDIDATE - a hard block, a required empty box, a
schedule row's required cell - and is kept only when a person can supply it
HERE: it needs a fix route (a capture-table cell, a typed fact the
questionnaire's own box -> fact door names, or the ACORD 101 remarks) that is
PROVEN to fill the box by the stamper's own Pass 1 (`_pass1_value` below,
pinned against `compute_form_gaps` by the tests); the route's fact / cell must
be empty (otherwise a rule decided the blank); no verified declarations entry
may name it (gap fill can still read it); and the same fix must not already be
a "Key details missing" item on the page. Counts of every dropped reason are
reported, and a dropped download hard block is named (`dropped_blocking`), so a
blocker a person cannot fix before generation is never silently lost.

COST
----
A seven-form package stamps in ~10 s (ACORD 125's prior-coverage grid is most
of it). Results are cached per (session, facts, flags, form set, documents),
computed on a small thread pool off the event loop, and a caller waits at most
`DRY_RUN_WAIT_SECONDS` before getting a `pending` payload; the run finishes
into the cache for the next request. Never raises.
"""

from __future__ import annotations

import asyncio
import concurrent.futures
import copy
import hashlib
import json
import logging
import os
import re
import threading
import time
from collections import OrderedDict
from typing import Any, Dict, Iterable, List, Optional, Tuple

logger = logging.getLogger(__name__)

DRY_RUN_MODEL_VERSION = "1.1.0"

WAIT_SECONDS = float(os.getenv("DRY_RUN_WAIT_SECONDS", "3") or 3)
MAX_SECONDS = float(os.getenv("DRY_RUN_MAX_SECONDS", "120") or 120)
_WORKERS = max(1, int(os.getenv("DRY_RUN_WORKERS", "2") or 2))
_CACHE_MAX = 64

STATUS_READY = "ready"
STATUS_PENDING = "pending"
STATUS_SKIPPED = "skipped"

# ── Why a finding is not an item (first match wins, in this order) ───────────
R_APPLICANT = "applicant_signature"
R_SIGNATURE = "signature_step"
R_VERIFY = "verify_only"
R_HELD = "held_back"
R_DOCS_FIRST = "left_to_documents"
R_OWNED = "owned_blank"
R_NO_ROUTE = "no_fix_route"
R_DECIDED = "decided_by_rule"
R_DOCS = "documents_state_it"
R_KEY_DETAILS = "listed_in_key_details"

REASON_TEXT: Dict[str, str] = {
    R_APPLICANT: "The applicant's signature, date or initials - asked when the form is signed.",
    R_SIGNATURE: "Your signature - added with Sign after the forms are generated.",
    R_VERIFY: "A value to check, not a value to supply.",
    R_HELD: "A value was found and refused for its box.",
    R_DOCS_FIRST: "Generation reads your documents for it first.",
    R_OWNED: "Left blank on purpose by a form rule.",
    R_NO_ROUTE: "Can only be filled on the form after generation.",
    R_DECIDED: "The value is on file; a form rule decides this box.",
    R_DOCS: "Your documents state it; generation reads it from them.",
    R_KEY_DETAILS: "Already listed under Key details.",
}

# The forms checked when the producer has ticked none: the recommender's core
# ("Required") forms - the ones every package of this shape generates. A
# "Recommended" / "Optional" form is checked once the producer ticks it; listing
# its boxes before then would ask for answers to a form that may never exist.
_DEFAULT_TIERS = ("required",)
_FALLBACK_TIERS = ("recommended",)

_ROW_RE = re.compile(r"^(?P<base>.+)_(?P<row>[A-N])$")
_TOKEN_RE = re.compile(r"[a-z0-9]+")


class _OutOfTime(Exception):
    pass


# ── Small readers ────────────────────────────────────────────────────────────

def _value(raw: Any) -> Any:
    return raw.get("value") if isinstance(raw, dict) and "value" in raw else raw


def _filled(value: Any) -> bool:
    if value is None or isinstance(value, (list, dict)):
        return False
    text = str(value).strip()
    return bool(text) and text not in ("UNMATCHED",) and text.lower() not in ("null", "none")


def _form_label(form_id: str) -> str:
    try:
        from services.form_instances import instance_label
        return instance_label(form_id)
    except Exception:                                          # pragma: no cover
        return str(form_id or "").replace("_", " ")


def _generated_forms_exist(session: Any) -> bool:
    return bool(isinstance(session, dict) and session.get("generated_forms"))


# ── 1. Which forms ───────────────────────────────────────────────────────────

def _form_metas(session: dict) -> Dict[str, dict]:
    metas: Dict[str, dict] = {}
    for m in (session.get("all_forms") or []) if isinstance(session, dict) else []:
        if isinstance(m, dict) and m.get("form_id") and m.get("template_file"):
            metas[str(m["form_id"])] = m
    if not metas:
        try:
            from services.form_service import load_all_forms
            for m in load_all_forms():
                if isinstance(m, dict) and m.get("form_id") and m.get("template_file"):
                    metas[str(m["form_id"])] = m
        except Exception as exc:                               # noqa: BLE001
            logger.warning("form_dry_run: form catalogue unavailable: %s", exc)
    return metas


def dry_run_form_ids(session: dict, form_ids: Optional[Iterable[Any]] = None) -> Tuple[List[str], str]:
    """(form ids, source): the producer's ticks when given, else the session's
    selected forms, else the recommended set - its `required` tier (then its
    `recommended` tier, then every recommendation, when a tier is empty), never
    an uploaded source document. Instance ids pass through; unknown forms are
    dropped."""
    from services.form_instances import base_form_id
    known = set(_form_metas(session or {}))

    def _clean(raw: Any) -> List[str]:
        out: List[str] = []
        for item in raw or []:
            fid = str(item.get("form_id") if isinstance(item, dict) else item or "").strip()
            if fid and base_form_id(fid) in known and fid not in out:
                out.append(fid)
        return out

    explicit = _clean(form_ids)
    if explicit:
        return explicit, "selected"
    selected = _clean((session or {}).get("selected_form_ids"))
    if selected:
        return selected, "selected"
    recs = [r for r in ((session or {}).get("recommendations") or []) if isinstance(r, dict)
            and not r.get("is_source_document")]
    for tiers in (_DEFAULT_TIERS, _FALLBACK_TIERS):
        picked = _clean([r for r in recs if str(r.get("tier") or "recommended") in tiers])
        if picked:
            return picked, "recommended"
    return _clean(recs), "recommended"


# ── 2. The deterministic stamp ───────────────────────────────────────────────

def stamp_forms(session: dict, form_ids: List[str], facts: dict, flags: dict,
                deadline: Optional[float] = None) -> Tuple[Dict[str, dict], List[dict]]:
    """{form id: generated-form-shaped dict} stamped by `map_facts_to_form`
    with NO gap fill and NO model call, plus the forms that could not be
    stamped (each with a reason)."""
    from config.settings import TEMPLATE_DIR
    from services.form_instances import base_form_id
    from services.form_service import active_document_text
    from services.pdf_service import extract_form_schema, map_facts_to_form

    metas = _form_metas(session)
    raw_text = active_document_text(session or {})
    generated: Dict[str, dict] = {}
    problems: List[dict] = []
    for fid in form_ids:
        if deadline is not None and time.monotonic() > deadline:
            raise _OutOfTime()
        base = base_form_id(fid)
        meta = metas.get(base)
        if not meta:
            problems.append({"form_id": fid, "reason": "unknown form"})
            continue
        tpl = os.path.join(TEMPLATE_DIR, os.path.basename(str(meta.get("template_file") or "")))
        try:
            schema = extract_form_schema(tpl, base)
        except Exception as exc:                               # noqa: BLE001
            schema = {}
            logger.warning("form_dry_run: schema unavailable for %s: %s", fid, exc)
        if not schema:
            problems.append({"form_id": fid, "reason": "no schema"})
            continue
        stamp_facts = {**(facts or {}), **(flags or {}), "_package_form_ids": list(form_ids)}
        guard_blanks: List[dict] = []
        try:
            mapped, confidence = map_facts_to_form(
                stamp_facts, schema, form_id=fid, raw_text=raw_text,
                pre_filled_gpt={"filled_values": {}}, guard_report=guard_blanks,
                allow_llm=False,
            )
        except Exception as exc:                               # noqa: BLE001
            logger.warning("form_dry_run: %s could not be stamped: %s", fid, exc, exc_info=True)
            problems.append({"form_id": fid, "reason": "stamp failed"})
            continue
        generated[fid] = {
            "form_id": fid, "form_name": meta.get("form_name"), "form": meta,
            "schema": schema, "mapped": mapped, "confidence": confidence,
            "guard_blanks": guard_blanks,
        }
    return generated, problems


def review_findings(generated: Dict[str, dict], facts: dict, flags: dict,
                    docs: Any = None) -> Tuple[dict, dict]:
    """The download review's two checks on the stamped forms - the SAME
    functions (see the module note). The two field-QA branches whose rows this
    module never keeps are switched off (`run_field_qa` docstring)."""
    from services.field_qa import run_field_qa
    from services.needs_attention import needs_attention_for_session
    qa = run_field_qa(generated, merged_facts=facts or {}, confirmations=None,
                      flags=flags or {}, unanswered=False, mismatches=False)
    attention = needs_attention_for_session(generated, facts or {}, flags=flags or {}, docs=docs)
    return qa, attention


# ── 3. Fix routes, proven by the stamper ─────────────────────────────────────

def _copy_context(stamp_facts: dict, form_id: str) -> Tuple[dict, str]:
    """(facts, base form id) a form id is stamped with - the stamper's own
    `_form_copy_context` (a form's second copy reads its own view)."""
    from services import pdf_service as ps
    fn = getattr(ps, "_form_copy_context", None)
    if callable(fn):
        return fn(stamp_facts, form_id)
    from services.form_instances import base_form_id, facts_for_form
    return facts_for_form(stamp_facts, form_id), base_form_id(form_id)


def _pass1_value(form_id: str, schema: dict, field: str, stamp_facts: dict) -> Any:
    """What the stamper's deterministic passes print in ONE box for these
    facts - `compute_form_gaps`' per-field order (the documented mirror of
    `map_facts_to_form`'s Pass 1 / 1.5): the non-fillable schedule exception,
    the schedule row (owned blanks win), the single-row scalar fallback,
    `_deterministic_map`, the authoritative blank, then the alias map. Run
    under the FULL form schema. Pinned against `compute_form_gaps` on real
    forms by tests/test_choice_electric_dryrun_7oct.py, so it cannot drift
    silently."""
    from services import pdf_service as ps
    with ps._schema_context(schema):
        facts, base = _copy_context(stamp_facts, form_id)
        facts = {**(facts or {}), "_form_id": base}
        if ps._FORM_EDITION_FIELD_RE.match(field):
            return ps._form_edition_identifier(base)        # system metadata
        if ps._is_nonfillable_field(field):
            bound = ps._resolve_schedule_row(field, facts)
            if (bound is not ps._SCHED_SKIP and bound is not None
                    and not ps._is_empty_llm_value(bound)
                    and not ps._owned_blank_claim(field, facts)):
                return bound
            return None
        sched = ps._resolve_schedule_row(field, facts)
        sched = ps._unless_owned_blank(field, sched, facts)
        if sched is not ps._SCHED_SKIP:
            if sched is not None and not ps._is_empty_llm_value(sched):
                return sched
            if field.endswith("_A") and ps._single_row_schedule(field, facts):
                fb = ps._deterministic_map(field, facts)
                if fb != "UNMATCHED" and not ps._is_empty_llm_value(fb):
                    return fb
            return None
        result = ps._deterministic_map(field, facts)
        if result != "UNMATCHED" and not ps._is_empty_llm_value(result):
            return result
        # Pass 1.5 fills an unmatched box unless a resolver owns it as a blank.
        # The alias map is asked FIRST only because the ownership test is the
        # expensive one (ACORD 125's prior-coverage grid) and almost never
        # needed: an owned blank and an unmatched box both print nothing.
        try:
            from config.settings import ENABLE_ALIAS_STAMPING
            if ENABLE_ALIAS_STAMPING:
                from services.alias_stamper import stamp_form_fields
                alias = (stamp_form_fields(base, facts, [field]) or {}).get(field)
                if (alias is not None and not ps._is_empty_llm_value(alias)
                        and not ps._is_authoritative_blank_field(field, facts)):
                    return alias
        except Exception:                                      # noqa: BLE001
            pass
        return None


def _schedule_route(field: str) -> Optional[dict]:
    """The capture-table cell an EXACT registry binding gives this box."""
    from services import pdf_service as ps
    from services.schedule_capture import SCHEDULE_DEFS
    m = _ROW_RE.match(field or "")
    if not m:
        return None
    defn = ps._SCHEDULE_REGISTRY.get(m.group("base"))
    if defn is None or defn.list_key not in SCHEDULE_DEFS or not defn.sub_key:
        return None
    columns = {c.get("key") for c in SCHEDULE_DEFS[defn.list_key].get("columns") or []}
    if defn.sub_key not in columns:
        return None
    row = ps._ROW_LETTER_TO_IDX.get(m.group("row"), -1) - (defn.row_offset or 0)
    if row < 0:
        return None
    return {"mode": "schedule", "schedule_key": defn.list_key, "column": defn.sub_key, "row": row}


def _field_routes(field: str, facts: dict) -> List[dict]:
    """Typed / narrative routes for a box, in order: the questionnaire's own
    box -> fact door, then the NamedInsured address pseudo-keys' source facts
    (the map `pdf_service.fact_to_form_fields` uses)."""
    from services.answer_routing import answer_mode, MODE_FIELD, MODE_NARRATIVE
    out: List[dict] = []
    try:
        routed = answer_mode(field, facts) or {}
    except Exception:                                          # noqa: BLE001
        routed = {}
    if routed.get("mode") == MODE_FIELD and routed.get("fact"):
        out.append({"mode": "field", "facts": [str(routed["fact"])]})
    elif routed.get("mode") == MODE_NARRATIVE and routed.get("fact") == "additional_remarks_text":
        out.append({"mode": "narrative", "facts": ["additional_remarks_text"]})
    try:
        from services.pdf_service import _first_rule_fact
        pseudo = _first_rule_fact(field) or ""
    except Exception:                                          # noqa: BLE001
        pseudo = ""
    source = None
    if pseudo.startswith("_addr_") and field.startswith("NamedInsured_"):
        source = "mailing_address"
    elif pseudo.startswith("_loc_"):
        source = "physical_address"
    if source and not any(source in (r.get("facts") or []) for r in out):
        try:
            if (answer_mode(source, facts) or {}).get("mode") == MODE_FIELD:
                out.append({"mode": "field", "facts": [source]})
        except Exception:                                      # noqa: BLE001
            pass
    # A ONE-premises box that prints the business's own answer (ACORD 125's
    # interest ticks from `premises_interest`, 13 Oct 2026) - the stamper's
    # twin, proven like every route.
    try:
        from services.pdf_service import premises_twin_key
        twin = premises_twin_key(field)
    except Exception:                                          # noqa: BLE001
        twin = None
    if twin and not any(twin in (r.get("facts") or []) for r in out):
        try:
            if (answer_mode(twin, facts) or {}).get("mode") == MODE_FIELD:
                out.append({"mode": "field", "facts": [twin]})
        except Exception:                                      # noqa: BLE001
            pass
    return out


_SHAPE_PROBES = (
    ("address", "100 Probe Street, Denver, CO 80202"),
    ("phone", "303-555-0100"),
    ("fax", "303-555-0101"),
    ("email", "probe@example.com"),
    ("website", "www.example.com"),
    ("date", "01/15/2027"),
    ("year", "1999"),
    ("state", "CO"),
)
_GENERIC_PROBES = ("1999", "$123,456", "12", "Probe value")


def _probe_values(route: dict) -> List[str]:
    """A few plausible values for a route - the route works when ANY of them
    makes the box print (a type gate refusing a probe never invents a route)."""
    out: List[str] = []
    if route.get("mode") == "schedule":
        from services.schedule_capture import SCHEDULE_DEFS
        col = next((c for c in (SCHEDULE_DEFS.get(route["schedule_key"], {}).get("columns") or [])
                    if c.get("key") == route.get("column")), {}) or {}
        opts = [o for o in (col.get("options") or []) if o and o != "Other"]
        out.extend(opts[:1])
        out.extend({"year": ["1999"], "currency": ["$123,456"], "percent": ["100"],
                    "number": ["12"], "state": ["CO"], "date": ["01/15/2001"],
                    "vin": ["1FTFW1ET5DFC10312"]}.get(col.get("type") or "text", []))
        out.append("Probe value")
    else:
        fact = str((route.get("facts") or [""])[0])
        try:
            from services.answer_options import options_for, OTHER
            opts = [o for o in (options_for(fact) or []) if o and o != OTHER]
        except Exception:                                      # noqa: BLE001
            opts = []
        out.extend(opts[:1])
        low = fact.lower()
        out.extend(v for k, v in _SHAPE_PROBES if k in low)
        out.extend(_GENERIC_PROBES)
    seen: List[str] = []
    for v in out:
        if v not in seen:
            seen.append(v)
    return seen[:5]


def _with_probe(stamp_facts: dict, route: dict, value: str) -> dict:
    probe = dict(stamp_facts)
    if route.get("mode") == "schedule":
        key = route["schedule_key"]
        rows = copy.deepcopy(_value(probe.get(key)))
        rows = [r for r in rows] if isinstance(rows, list) else []
        while len(rows) <= int(route.get("row") or 0):
            rows.append({})
        if not isinstance(rows[route["row"]], dict):
            rows[route["row"]] = {}
        rows[route["row"]][route["column"]] = value
        probe[key] = rows
    else:
        for fact in route.get("facts") or []:
            probe[fact] = value
    return probe


def route_fills(form_id: str, schema: dict, fields: List[str], stamp_facts: dict,
                route: dict) -> bool:
    """True when writing through `route` makes the stamper print one of
    `fields` (a tick group passes on any member)."""
    for value in _probe_values(route):
        probe = _with_probe(stamp_facts, route, value)
        for field in fields:
            try:
                if _filled(_pass1_value(form_id, schema, field, probe)):
                    return True
            except Exception as exc:                           # noqa: BLE001
                logger.debug("form_dry_run: probe failed for %s/%s: %s", form_id, field, exc)
    return False


def find_route(form_id: str, schema: dict, field: str, stamp_facts: dict, facts: dict,
               members: Optional[List[str]] = None) -> Optional[dict]:
    """The first fix route whose write PROVABLY prints the box (or, for a
    collapsed tick group, any of its members). None: nothing a person can type
    here fills it."""
    fields = list(dict.fromkeys([field] + list(members or [])))
    candidates: List[dict] = []
    for f in fields:
        sched = _schedule_route(f)
        if sched and sched not in candidates:
            candidates.append(sched)
        for r in _field_routes(f, facts):
            if r not in candidates:
                candidates.append(r)
    for route in candidates:
        if route_fills(form_id, schema, fields, stamp_facts, route):
            return route
    return None


# ── 4. Is the answer already somewhere? ──────────────────────────────────────

def _route_target_value(facts: dict, route: dict) -> Any:
    if route.get("mode") == "schedule":
        rows = _value((facts or {}).get(route["schedule_key"]))
        row = int(route.get("row") or 0)
        if isinstance(rows, list) and row < len(rows) and isinstance(rows[row], dict):
            return rows[row].get(route.get("column"))
        return None
    vals = [_value((facts or {}).get(f)) for f in (route.get("facts") or [])]
    return next((v for v in vals if _filled(v)), None)


def _target_token_sets(route: dict) -> List[List[str]]:
    """The names a declarations entry would print this route's answer under:
    the fact key (or the column key and the package fact it summarises) plus
    the registry's own printed names (`dec_labels`)."""
    keys: List[str] = []
    if route.get("mode") == "schedule":
        keys.append(str(route.get("column") or ""))
        try:
            from services.premises_cope import PER_BUILDING_COPE
            keys.extend(f for f, c in PER_BUILDING_COPE.items() if c == route.get("column")
                        and route.get("schedule_key") == "property_locations")
        except Exception:                                      # noqa: BLE001
            pass
    else:
        keys.extend(str(f) for f in (route.get("facts") or []))
    sets: List[List[str]] = []
    try:
        from services.fact_registry import FACT_REGISTRY
    except Exception:                                          # noqa: BLE001
        FACT_REGISTRY = {}
    for key in keys:
        toks = _TOKEN_RE.findall(key.lower())
        if toks:
            sets.append(toks)
        for name in ((FACT_REGISTRY.get(key) or {}).get("dec_labels") or ()):
            toks = [t for t in _TOKEN_RE.findall(str(name).lower()) if len(t) >= 3]
            if toks:
                sets.append(toks)
    return sets


def documents_name_it(facts: dict, route: dict) -> bool:
    """A VERIFIED declarations entry names this route's fact / column - the
    test the merge's own backfill applies (`extraction_service.
    _dec_entry_label_matches_key`). The documents state something for it, so
    generation's document reading can still fill the box."""
    entries = _value((facts or {}).get("dec_page_entries"))
    if not isinstance(entries, list) or not entries:
        return False
    try:
        from services.extraction_service import _dec_entry_label_matches_key
    except Exception:                                          # noqa: BLE001
        return False
    token_sets = _target_token_sets(route)
    for e in entries:
        label = str((e or {}).get("label") or "") if isinstance(e, dict) else ""
        if not label or not _filled((e or {}).get("value")):
            continue
        if any(_dec_entry_label_matches_key(label, toks) for toks in token_sets):
            return True
    return False


def _key_detail_fixes(facts: dict, flags: dict) -> Tuple[set, set]:
    """(facts, schedule keys) the page's "Key details missing" list already
    offers to fix (`sqs_service.key_details`, the same call the page makes)."""
    try:
        from services.sqs_service import key_details
        kd = key_details(facts or {}, flags or {}) or {}
    except Exception:                                          # noqa: BLE001
        return set(), set()
    kd_facts, kd_schedules = set(), set()
    for item in kd.get("missing_items") or []:
        res = (item or {}).get("resolution") or {}
        if res.get("mode") == "field":
            kd_facts.update(str(f) for f in (res.get("facts") or []))
        elif res.get("mode") == "schedule" and res.get("schedule_key"):
            kd_schedules.add(str(res["schedule_key"]))
    return kd_facts, kd_schedules


# ── 5. Classify ──────────────────────────────────────────────────────────────

def _tick_group_members(form_id: str, field: str, schema: dict) -> List[str]:
    """Every box of a collapsed "tick one of these" group (`needs_attention`'s
    ACORD 125 groups), so its route is proven on any member."""
    try:
        from services.form_instances import base_form_id
        from services.needs_attention import _ACORD125_TICK_GROUPS
        import services.pdf_service as _ps
    except Exception:                                          # noqa: BLE001
        return []
    if base_form_id(form_id) != "ACORD_125":
        return []
    for set_name, _label, _what in _ACORD125_TICK_GROUPS:
        members = getattr(_ps, set_name, None) or ()
        if field in members:
            return [f for f in members if f in (schema or {})]
    return []


def _row_label(rows: Any, idx: int, singular: str) -> str:
    noun = (singular or "row").strip().capitalize()
    base = f"{noun} {idx + 1}"
    if not isinstance(rows, list) or idx >= len(rows) or not isinstance(rows[idx], dict):
        return f"{base} (new row)"
    row = rows[idx]
    parts = []
    if _filled(row.get("location_number")):
        parts.append(f"LOC {str(row['location_number']).strip()}")
    if _filled(row.get("building_number")):
        parts.append(f"BLDG {str(row['building_number']).strip()}")
    if parts:
        return f"{base} ({' / '.join(parts)})"
    street = row.get("address_line1") or row.get("address")
    return f"{base} ({str(street).strip()})" if _filled(street) else base


def _column_labels(schedule_key: str) -> Dict[str, str]:
    from services.schedule_capture import SCHEDULE_DEFS
    return {c.get("key"): c.get("label") for c in
            (SCHEDULE_DEFS.get(schedule_key, {}).get("columns") or [])}


def _fact_label(fact: str) -> str:
    try:
        from services.needs_attention import _humanize_fact
        text = _humanize_fact(fact)
    except Exception:                                          # noqa: BLE001
        text = str(fact).replace("_", " ")
    return text[:1].upper() + text[1:] if text else str(fact)


def _hard_codes() -> frozenset:
    try:
        from services.field_qa import _HARD_BLOCK_REASON_CODES
        return frozenset(_HARD_BLOCK_REASON_CODES)
    except Exception:                                          # noqa: BLE001
        return frozenset({"placeholder_value", "missing_required_gate"})


def classify(generated: Dict[str, dict], qa: dict, attention: dict, facts: dict,
             flags: dict) -> dict:
    """Turn the review's raw findings into the items a person must supply
    before generating, plus the dropped counts (see the module note)."""
    hard_codes = _hard_codes()
    dropped_keys: Dict[str, set] = {}
    dropped_blocking: List[dict] = []
    boxes: "OrderedDict[Tuple[str, str], dict]" = OrderedDict()
    applicant: set = set()

    def _drop(reason: str, form_id: str, field: str, label: str, blocks: bool) -> None:
        # One count per BOX: field QA and the needs-attention list often report
        # the same box (a required empty box is in both).
        dropped_keys.setdefault(reason, set()).add((form_id, field))
        if blocks:
            dropped_blocking.append({"form_id": form_id, "form_label": _form_label(form_id),
                                     "field": field, "label": label, "reason": reason,
                                     "reason_text": REASON_TEXT.get(reason, "")})

    def _candidate(form_id: str, field: str, label: str, blocks: bool,
                   page: Any = None, members: Optional[List[str]] = None,
                   schedule_row: Optional[dict] = None) -> None:
        key = (form_id, field)
        if key in applicant:
            return                              # the applicant's own step
        box = boxes.get(key)
        if box is None:
            boxes[key] = {"form_id": form_id, "field": field, "label": label,
                          "blocks_download": bool(blocks), "page": page,
                          "members": list(members or []), "schedule_row": schedule_row}
        else:
            box["blocks_download"] = box["blocks_download"] or bool(blocks)
            box["label"] = box["label"] or label
            box["page"] = box["page"] or page

    # The signing steps first, so no other door can turn one into a request:
    # the needs-attention list's applicant rows, and any signature / date /
    # initials box ACORD's own tooltip names (`signature_boxes`).
    from services.needs_attention import STATUS_HELD_BACK, STATUS_MISSING, STATUS_VERIFY
    for form in (attention or {}).get("forms") or []:
        fid = str((form or {}).get("form_id") or "")
        for row in (form or {}).get("rows") or []:
            if row.get("status") == STATUS_MISSING and row.get("applicant_step"):
                applicant.add((fid, str(row.get("field") or "")))

    def _signature_step(form_id: str, field: str) -> Optional[str]:
        schema = (generated.get(form_id) or {}).get("schema") or {}
        meta = schema.get(field) if isinstance(schema.get(field), dict) else {}
        try:
            from services.signature_boxes import is_applicant_step, signature_box
            tip = str((meta or {}).get("tu") or "")
            if is_applicant_step(field, tip):
                return R_APPLICANT
            if signature_box(field, tip):
                return R_SIGNATURE
        except Exception:                                      # noqa: BLE001
            return None
        return None

    # Field QA: the download gate's own findings.
    for r in (qa or {}).get("results") or []:
        if not isinstance(r, dict):
            continue
        code = r.get("reason_code")
        fid, field = str(r.get("form_id") or ""), str(r.get("field") or "")
        label = str(r.get("field_label") or field)
        if code in hard_codes or code == "missing_required":
            sig = R_APPLICANT if (fid, field) in applicant else _signature_step(fid, field)
            if sig:
                _drop(sig, fid, field, label, code in hard_codes)
            else:
                _candidate(fid, field, label, code in hard_codes)
        elif code == "schedule_row_missing":
            m = re.match(r"^(?P<lk>[a-z0-9_]+)\[(?P<i>\d+)\]\.(?P<col>[a-z0-9_]+)$", field)
            _candidate(fid, field, label, False,
                       schedule_row=({"schedule_key": m.group("lk"), "row": int(m.group("i")),
                                      "column": m.group("col")} if m else None))
        elif code in ("schedule_row_invalid", "low_confidence", "value_mismatch"):
            _drop(R_VERIFY, fid, field, label, False)
        elif code == "guard_removed_value":
            _drop(R_HELD, fid, field, label, False)
        elif code == "not_answered":
            _drop(R_DOCS_FIRST, fid, field, label, False)

    # Needs attention: the review's live list.
    for form in (attention or {}).get("forms") or []:
        fid = str((form or {}).get("form_id") or "")
        for row in (form or {}).get("rows") or []:
            field, label = str(row.get("field") or ""), str(row.get("label") or "")
            status = row.get("status")
            if status == STATUS_VERIFY:
                _drop(R_VERIFY, fid, field, label, False)
            elif status == STATUS_HELD_BACK:
                _drop(R_HELD, fid, field, label, False)
            elif status == STATUS_MISSING and (fid, field) in applicant:
                _drop(R_APPLICANT, fid, field, label, False)
            elif status == STATUS_MISSING and not row.get("required") and not row.get("producer_todo"):
                # An underwriting question the documents do not answer yet -
                # generation's document reading is asked it first.
                _drop(R_DOCS_FIRST, fid, field, label, False)
            elif status == STATUS_MISSING:
                sig = _signature_step(fid, field)
                if sig:
                    _drop(sig, fid, field, label, False)
                    continue
                schema = (generated.get(fid) or {}).get("schema") or {}
                members = (_tick_group_members(fid, field, schema)
                           if int(row.get("box_count") or 1) > 1 else [])
                _candidate(fid, field, label, False, page=row.get("page"), members=members)

    # Prove a route for each candidate, then ask whether it is really theirs.
    kd_facts, kd_schedules = _key_detail_fixes(facts, flags)
    stamp_base = {**(facts or {}), **(flags or {})}
    kept: List[dict] = []
    stamp_facts = {**stamp_base, "_package_form_ids": list(generated)}
    for (fid, field), box in boxes.items():
        gen = generated.get(fid) or {}
        schema = gen.get("schema") or {}
        sr = box.get("schedule_row")
        if sr:
            from services.schedule_capture import SCHEDULE_DEFS
            cols = {c.get("key") for c in (SCHEDULE_DEFS.get(sr["schedule_key"], {}).get("columns") or [])}
            route = ({"mode": "schedule", "schedule_key": sr["schedule_key"],
                      "column": sr["column"], "row": sr["row"]}
                     if sr["column"] in cols else None)
        else:
            route = find_route(fid, schema, field, stamp_facts, facts or {}, box.get("members"))
        if route is None:
            owned = False
            if not sr and schema:
                try:
                    from services import pdf_service as ps
                    with ps._schema_context(schema):
                        _f, _b = _copy_context(stamp_facts, fid)
                        owned = bool(ps._owned_blank_claim(field, {**(_f or {}), "_form_id": _b}))
                except Exception:                              # noqa: BLE001
                    owned = False
            _drop(R_OWNED if owned else R_NO_ROUTE, fid, field, box["label"], box["blocks_download"])
            continue
        if _filled(_route_target_value(facts or {}, route)):
            _drop(R_DECIDED, fid, field, box["label"], box["blocks_download"])
            continue
        if documents_name_it(facts or {}, route):
            _drop(R_DOCS, fid, field, box["label"], box["blocks_download"])
            continue
        if ((route["mode"] == "field" and set(route.get("facts") or []) <= kd_facts)
                or (route["mode"] == "schedule" and route["schedule_key"] in kd_schedules)):
            _drop(R_KEY_DETAILS, fid, field, box["label"], box["blocks_download"])
            continue
        kept.append({**box, "route": route})

    # A box counts once, under the first reason it was dropped for.
    counted: set = set()
    dropped: Dict[str, int] = {}
    for reason in REASON_TEXT:
        mine = dropped_keys.get(reason, set()) - counted
        if mine:
            dropped[reason] = len(mine)
            counted |= mine
    seen_blocking: set = set()
    blocking: List[dict] = []
    for b in dropped_blocking:
        k = (b["form_id"], b["field"])
        if k not in seen_blocking:
            seen_blocking.add(k)
            blocking.append(b)
    return {"kept": kept, "dropped": dropped, "dropped_blocking": blocking}


# ── 6. Items, grouped by form ────────────────────────────────────────────────

def _resolution_for(route: dict) -> dict:
    if route.get("mode") == "schedule":
        return {"mode": "schedule", "schedule_key": route["schedule_key"]}
    if route.get("mode") == "narrative":
        return {"mode": "narrative"}
    try:
        from services.issue_registry import field_resolution
        return field_resolution(*(route.get("facts") or []))
    except Exception:                                          # noqa: BLE001
        return {"mode": "field", "facts": list(route.get("facts") or [])}


_TWIN_LABELS: Dict[str, str] = {
    "premises_interest": "Owner or tenant of the premises",
    "total_revenue": "Annual revenue",
    "num_employees_full_time": "Full-time employees",
    "num_employees_part_time": "Part-time employees",
}


def _twin_of(field: str) -> Optional[str]:
    try:
        from services.pdf_service import premises_twin_key
        return premises_twin_key(field)
    except Exception:                                          # noqa: BLE001
        return None


def build_items(kept: List[dict], facts: dict, form_order: List[str]) -> List[dict]:
    """One item per (form, fix target): a table row, or a fact."""
    from services.schedule_capture import SCHEDULE_DEFS
    groups: "OrderedDict[tuple, List[dict]]" = OrderedDict()
    for box in kept:
        r = box["route"]
        if r["mode"] == "schedule":
            key = (box["form_id"], "schedule", r["schedule_key"], int(r.get("row") or 0))
        else:
            key = (box["form_id"], r["mode"], tuple(r.get("facts") or []))
        groups.setdefault(key, []).append(box)

    items: List[dict] = []
    for key, members in groups.items():
        fid = key[0]
        route = dict(members[0]["route"])
        blocks = any(m["blocks_download"] for m in members)
        if route["mode"] == "schedule":
            sk, row = key[2], key[3]
            defn = SCHEDULE_DEFS.get(sk) or {}
            col_labels = _column_labels(sk)
            col_order = {c: i for i, c in enumerate(col_labels)}
            cols: List[str] = []
            for m in members:
                c = m["route"].get("column")
                if c and c not in cols:
                    cols.append(c)
            cols.sort(key=lambda c: col_order.get(c, 999))     # the table's own order
            rows = _value((facts or {}).get(sk))
            label = (f"{_row_label(rows, row, defn.get('singular') or 'row')}: "
                     + ", ".join(col_labels.get(c) or c for c in cols))
            what = (f"Fill {'it' if len(cols) == 1 else 'them'} in row {row + 1} of the "
                    f"{str(defn.get('label') or 'schedule').lower()}.")
            route = {"mode": "schedule", "schedule_key": sk, "row": row, "columns": cols}
            resolution = {"mode": "schedule", "schedule_key": sk, "columns": cols, "rows": [row]}
        else:
            facts_ = list(route.get("facts") or [])
            labels = list(dict.fromkeys(m["label"] for m in members if m.get("label")))
            label = labels[0] if len(labels) == 1 else (
                _fact_label(facts_[0]) if facts_ else (labels[0] if labels else ""))
            # A premises box answered by the business's own fact names that
            # fact ("Owner or tenant of the premises"), never one tick box's
            # tooltip ("...interest in the building is as its owner").
            if facts_ and facts_[0] in _TWIN_LABELS and all(
                    _twin_of(m["field"]) == facts_[0] for m in members):
                label = _TWIN_LABELS[facts_[0]]
            what = ("Add it to the ACORD 101 remarks." if route["mode"] == "narrative"
                    else "Enter it here before you generate.")
            resolution = _resolution_for(route)
        items.append({
            "id": re.sub(r"[^A-Za-z0-9]+", "_", "_".join(str(k) for k in key)).strip("_"),
            "form_id": fid,
            "form_label": _form_label(fid),
            "label": label,
            "blocks_download": blocks,
            "reason": ("Blocks a clean download - the form requires it."
                       if blocks else "Required on this form and still empty."),
            "what_to_do": what,
            "boxes": [{"field": m["field"], "label": m["label"], "page": m.get("page"),
                       "blocks_download": m["blocks_download"]}
                      for m in sorted(members, key=lambda m: m["field"])],
            "route": route,
            "resolution": resolution,
        })
    order = {f: i for i, f in enumerate(form_order)}
    # Per form: what blocks a clean download first, then table rows in row
    # order, then typed facts by label - a stable order run to run.
    items.sort(key=lambda it: (order.get(it["form_id"], 999), not it["blocks_download"],
                               it["route"].get("mode") != "schedule",
                               int(it["route"].get("row") or 0), it["label"]))
    return items


# ── 6b. The forms' own checklist cards ───────────────────────────────────────

def _answered(facts: dict, fact: str) -> bool:
    """A person or a document answered it - an explicit "none" counts."""
    try:
        from services.answer_semantics import fact_answered
        return bool(fact_answered((facts or {}).get(fact)))
    except Exception:                                          # noqa: BLE001
        return _filled(_value((facts or {}).get(fact)))


def form_card_items(generated: Dict[str, dict], facts: dict, flags: dict,
                    form_ids: List[str], items: List[dict]) -> List[dict]:
    """A form's own checklist cards, before the form exists (13 Oct 2026,
    Choice Electric #22).

    ACORD 125's "carrier receiving this submission", ACORD 126's GL form type
    and ACORD 130's officer exclusions are raised by the form's scorer
    (`sqs_service.calculate_sqs`), which ran only at generation - so run
    `ba7c709d` listed them only after forms. The same scorer reads the stamped
    forms here. A card is kept only when a person can answer it HERE: a typed
    fact the server's answer door accepts, still unanswered, not named by a
    verified declarations entry, not already one of this run's items and not a
    "Key details missing" item (the page also hides one a Hard Stop or Warning
    already asks for)."""
    from services.answer_routing import MODE_FIELD, answer_mode
    from services.sqs_service import calculate_sqs
    taken = {f for it in items for f in ((it.get("route") or {}).get("facts") or [])}
    taken |= _key_detail_fixes(facts, flags)[0]
    out: List[dict] = []
    for fid in form_ids:
        gen = generated.get(fid)
        if not gen:
            continue
        try:
            sqs = calculate_sqs(facts or {}, flags or {}, gen.get("mapped") or {},
                                gen.get("schema") or {}, [fid], [], [], 0, form_id=fid,
                                confidence_dict=gen.get("confidence") or {})
        except Exception as exc:                               # noqa: BLE001
            logger.debug("form_dry_run: %s cards unavailable: %s", fid, exc)
            continue
        for rec in (sqs or {}).get("recommendations") or []:
            if not isinstance(rec, dict) or rec.get("type") != "missing_field":
                continue
            fact = str(rec.get("field") or "").strip()
            if not fact or fact in taken or _answered(facts, fact):
                continue
            try:
                if (answer_mode(fact, facts) or {}).get("mode") != MODE_FIELD:
                    continue
            except Exception:                                  # noqa: BLE001
                continue
            route = {"mode": "field", "facts": [fact]}
            if documents_name_it(facts or {}, route):
                continue
            taken.add(fact)
            out.append({
                "id": re.sub(r"[^A-Za-z0-9]+", "_", f"{fid}_card_{rec.get('rec_id') or fact}").strip("_"),
                "form_id": fid,
                "form_label": _form_label(fid),
                "label": str(rec.get("message") or _fact_label(fact)).strip(),
                "blocks_download": False,
                "reason": "This form asks for it.",
                "what_to_do": "Answer it here before you generate.",
                "boxes": [],
                "route": route,
                "resolution": _resolution_for(route),
            })
    return out


# ── 7. The whole run ─────────────────────────────────────────────────────────

def _snapshot_json(facts: Any, flags: Any) -> str:
    return json.dumps({"facts": facts or {}, "flags": flags or {}}, sort_keys=True, default=str)


def fingerprint(session_id: str, facts_json: str, form_ids: List[str], session: dict) -> str:
    docs = [(str(d.get("doc_id") or d.get("filename") or i), bool(d.get("excluded")),
             str(d.get("doc_type") or ""), len(str(d.get("text") or "")))
            for i, d in enumerate((session or {}).get("docs") or []) if isinstance(d, dict)]
    blob = json.dumps({"s": str(session_id or ""), "f": facts_json, "ids": list(form_ids),
                       "docs": docs, "v": DRY_RUN_MODEL_VERSION}, sort_keys=True, default=str)
    return hashlib.sha256(blob.encode("utf-8", "replace")).hexdigest()


def _base_payload(status: str, form_ids: List[str], source: str, key: str) -> dict:
    return {
        "status": status,
        "model_version": DRY_RUN_MODEL_VERSION,
        "fingerprint": key[:16],
        "form_source": source,
        "checked_forms": [{"form_id": f, "form_label": _form_label(f)} for f in form_ids],
        "forms": [],
        "count": 0,
        "box_count": 0,
        "blocking_count": 0,
        "dropped": {},
        "dropped_blocking": [],
        "reason_text": dict(REASON_TEXT),
    }


def run_dry_run(session: dict, facts: Optional[dict] = None, flags: Optional[dict] = None,
                form_ids: Optional[Iterable[Any]] = None, *, session_id: str = "",
                budget_seconds: Optional[float] = None,
                _resolved: Optional[Tuple[List[str], str]] = None,
                _key: str = "") -> dict:
    """The whole dry run, synchronously. Never raises: a failure is a
    `skipped` payload that says so."""
    started = time.monotonic()
    session = session if isinstance(session, dict) else {}
    facts = facts if isinstance(facts, dict) else (session.get("facts") or {})
    flags = flags if isinstance(flags, dict) else (session.get("flags") or {})
    ids, source = _resolved or dry_run_form_ids(session, form_ids)
    key = _key or fingerprint(session_id, _snapshot_json(facts, flags), ids, session)
    payload = _base_payload(STATUS_READY, ids, source, key)
    budget = MAX_SECONDS if budget_seconds is None else float(budget_seconds)
    deadline = started + budget if budget > 0 else None
    try:
        generated, problems = stamp_forms(session, ids, facts, flags, deadline=deadline)
        if deadline is not None and time.monotonic() > deadline:
            raise _OutOfTime()
        qa, attention = review_findings(generated, facts, flags, session.get("docs"))
        result = classify(generated, qa, attention, facts, flags)
        items = build_items(result["kept"], facts, ids)
        items = items + form_card_items(generated, facts, flags, ids, items)
        forms: List[dict] = []
        for fid in ids:
            mine = [it for it in items if it["form_id"] == fid]
            if mine:
                forms.append({"form_id": fid, "form_label": _form_label(fid), "items": mine,
                              "count": len(mine),
                              "blocking": sum(1 for it in mine if it["blocks_download"])})
        payload.update({
            "forms": forms,
            "count": len(items),
            "box_count": sum(len(it["boxes"]) for it in items),
            "blocking_count": sum(1 for it in items if it["blocks_download"]),
            "dropped": dict(sorted(result["dropped"].items())),
            "dropped_blocking": result["dropped_blocking"],
            "skipped_forms": problems,
        })
    except _OutOfTime:
        payload = _base_payload(STATUS_SKIPPED, ids, source, key)
        payload["reason"] = ("The forms took too long to check. They are still checked "
                             "when they are generated.")
        logger.warning("form_dry_run: over budget (%.0fs) session=%s forms=%s",
                       budget, session_id, ids)
    except Exception as exc:                                   # noqa: BLE001
        payload = _base_payload(STATUS_SKIPPED, ids, source, key)
        payload["reason"] = ("The forms could not be checked before generation. They are "
                             "still checked when they are generated.")
        logger.error("form_dry_run: failed session=%s forms=%s: %s", session_id, ids, exc,
                     exc_info=True)
    payload["elapsed_ms"] = int((time.monotonic() - started) * 1000)
    if payload["status"] == STATUS_READY:
        logger.info("form_dry_run: session=%s forms=%s items=%d (boxes %d, blocking %d) "
                    "dropped=%s in %dms", session_id, ids, payload["count"],
                    payload["box_count"], payload["blocking_count"], payload["dropped"],
                    payload["elapsed_ms"])
    return payload


# ── 8. Cache, off the event loop, time-bounded ───────────────────────────────

_LOCK = threading.Lock()
_CACHE: "OrderedDict[str, Tuple[dict, float]]" = OrderedDict()
_INFLIGHT: Dict[str, concurrent.futures.Future] = {}
# At most `_WORKERS` runs at once, process-wide (each is CPU work).
_SLOTS = threading.BoundedSemaphore(_WORKERS)
# A `skipped` result (over budget, a failure) is remembered briefly - so a poll
# does not start the same doomed run again at once - and then retried.
_SKIPPED_TTL_SECONDS = 60.0


def _spawn(fn) -> "concurrent.futures.Future[dict]":
    """Run `fn` on a DAEMON thread, at most `_WORKERS` at a time. A daemon, so
    a run in progress never holds up a server shutdown or a code reload (a
    ThreadPoolExecutor's workers are joined at interpreter exit)."""
    fut: "concurrent.futures.Future[dict]" = concurrent.futures.Future()

    def _runner() -> None:
        with _SLOTS:
            if not fut.set_running_or_notify_cancel():
                return
            try:
                fut.set_result(fn())
            except BaseException as exc:                       # noqa: BLE001
                fut.set_exception(exc)

    threading.Thread(target=_runner, name="form-dry-run", daemon=True).start()
    return fut


def _remember(key: str, payload: dict) -> None:
    with _LOCK:
        _CACHE[key] = (payload, time.monotonic())
        _CACHE.move_to_end(key)
        while len(_CACHE) > _CACHE_MAX:
            _CACHE.popitem(last=False)
        _INFLIGHT.pop(key, None)


def cached(key: str) -> Optional[dict]:
    with _LOCK:
        hit = _CACHE.get(key)
        if hit is None:
            return None
        payload, at = hit
        if (payload.get("status") != STATUS_READY
                and time.monotonic() - at > _SKIPPED_TTL_SECONDS):
            _CACHE.pop(key, None)
            return None
        _CACHE.move_to_end(key)
        return payload


def clear_cache() -> None:
    """Tests and a deploy-time reset."""
    with _LOCK:
        _CACHE.clear()
        _INFLIGHT.clear()


def submit(session: dict, facts: Optional[dict] = None, flags: Optional[dict] = None,
           form_ids: Optional[Iterable[Any]] = None, *, session_id: str = ""
           ) -> Tuple[str, "concurrent.futures.Future[dict]", Tuple[List[str], str]]:
    """Start (or join) the dry run for this exact state. Returns the cache key,
    a future of the payload and the resolved (form ids, source)."""
    session = session if isinstance(session, dict) else {}
    facts = facts if isinstance(facts, dict) else (session.get("facts") or {})
    flags = flags if isinstance(flags, dict) else (session.get("flags") or {})
    resolved = dry_run_form_ids(session, form_ids)
    facts_json = _snapshot_json(facts, flags)
    key = fingerprint(session_id, facts_json, resolved[0], session)
    hit = cached(key)
    if hit is not None:
        done: "concurrent.futures.Future[dict]" = concurrent.futures.Future()
        done.set_result(hit)
        return key, done, resolved
    with _LOCK:
        running = _INFLIGHT.get(key)
        if running is not None:
            return key, running, resolved
    # A private copy: the caller may go on mutating its dicts after we return.
    snap = json.loads(facts_json)
    snap_session = {k: session.get(k) for k in
                    ("docs", "all_forms", "recommendations", "selected_form_ids")}

    def _work() -> dict:
        try:
            out = run_dry_run(snap_session, snap["facts"], snap["flags"],
                              session_id=session_id, _resolved=resolved, _key=key)
        except Exception as exc:                               # noqa: BLE001 - never escapes
            out = _base_payload(STATUS_SKIPPED, resolved[0], resolved[1], key)
            out["reason"] = "The forms could not be checked before generation."
            logger.error("form_dry_run: worker failed session=%s: %s", session_id, exc)
        _remember(key, out)
        return out

    with _LOCK:
        running = _INFLIGHT.get(key)
        if running is not None:                 # another request got here first
            return key, running, resolved
        fut = _spawn(_work)
        _INFLIGHT[key] = fut
    return key, fut, resolved


async def dry_run_payload(session: dict, facts: Optional[dict] = None,
                          flags: Optional[dict] = None,
                          form_ids: Optional[Iterable[Any]] = None, *,
                          session_id: str = "",
                          wait: Optional[float] = None) -> Optional[dict]:
    """The "Before you generate" payload for a pre-form response. None once
    forms exist (the download review is then the live list). Waits at most
    `wait` seconds (default `DRY_RUN_WAIT_SECONDS`); a run still going returns
    a `pending` payload and finishes into the cache. Never raises."""
    try:
        if not isinstance(session, dict) or _generated_forms_exist(session):
            return None
        key, fut, resolved = submit(session, facts, flags, form_ids, session_id=session_id)
        if fut.done():
            return fut.result()
        timeout = WAIT_SECONDS if wait is None else max(0.0, float(wait))
        try:
            return await asyncio.wait_for(asyncio.shield(asyncio.wrap_future(fut)),
                                          timeout=timeout)
        except asyncio.TimeoutError:
            pending = _base_payload(STATUS_PENDING, resolved[0], resolved[1], key)
            pending["reason"] = "Checking the forms you will generate - this takes a few seconds."
            return pending
    except Exception as exc:                                   # noqa: BLE001
        logger.error("form_dry_run: payload unavailable session=%s: %s", session_id, exc,
                     exc_info=True)
        return {"status": STATUS_SKIPPED, "model_version": DRY_RUN_MODEL_VERSION,
                "reason": "The forms could not be checked before generation.",
                "forms": [], "count": 0, "box_count": 0, "blocking_count": 0,
                "dropped": {}, "dropped_blocking": [], "checked_forms": []}
