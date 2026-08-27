"""
audit_history.py - THE ONE EVENT / HISTORY MODEL (client section 12, V1 H7).

The pure, database-free half of the E&O event spine. Everything here is a
constant or a total function so the shape of an event can be tested without a
pool, and so no call site has to remember what an event "should" look like.

WHY THIS MODULE EXISTS (read before adding a second one)
--------------------------------------------------------
Before H7 the codebase had NINE audit stores and an exporter that visited eight
of them. Only one of the client's eight material events reached an append-only
table; dismissal, issue resolution, conflict resolution, producer override and
the generated-value override were recorded - when they were recorded at all -
as MUTABLE current state, so re-answering, reopening or a routine field-QA
refresh silently overwrote what had happened. The record was assembled at the
end from whatever survived.

D49 is the rule that fixes the class, and this module is its vocabulary:

    the workflow tables hold STATE,
    `audit_events` holds HISTORY,
    and the event is emitted by the writer the action already goes through -
    never by the exporter.

The mutable tables (`sqs_recommendation_audit`, `submission_issue_status`,
`marketing_reason_audit`, ...) are deliberately UNCHANGED: dismiss-credit, the
download gate, the issue rail and reopen all read them as current state and
must keep doing so. Every material act now ALSO appends one immutable envelope
to the spine.

ONE MODEL, FOUR CONSUMERS (D50, owner ruling 2026-08-27)
--------------------------------------------------------
The client asked for "one underlying event/history model that can serve:
product history; debugging; source lineage; E&O Audit Record". One STORE, one
ENVELOPE, one WRITE PATH - not one event name for four different things. The
`visibility` marker is what lets the navbar Activity Log and the E&O record
read the same rows without showing each other's noise.

`activity_service.record_event` is an adapter over this spine; its event-type
strings are preserved verbatim so the Activity Log UI needs no change and
cannot regress.
"""
from typing import Optional

# ── Roles (D51) ───────────────────────────────────────────────────────────────
# The WORKFLOW role - who acted and in what capacity on THIS submission - not
# agency RBAC. There is no role column on `users` to read (`admin_users` is an
# email allow-list), and CSR / principal hierarchies are explicitly out of V1.
ROLE_PRODUCER = "producer"
ROLE_CLIENT   = "client"
ROLE_SYSTEM   = "system"

_ROLES = (ROLE_PRODUCER, ROLE_CLIENT, ROLE_SYSTEM)

ROLE_LABELS = {
    ROLE_PRODUCER: "Producer",
    ROLE_CLIENT:   "Client",
    ROLE_SYSTEM:   "System",
}

# ── Visibility (D50) ──────────────────────────────────────────────────────────
VISIBILITY_PRODUCT = "product"   # navbar Activity Log + the E&O record
VISIBILITY_AUDIT   = "audit"     # E&O record / debugging only

# ── Event vocabulary ──────────────────────────────────────────────────────────
# Pre-H7 spine events (C5-A). Names are LOAD-BEARING: `sqs_snapshot` is read
# back by `log_sqs_snapshot_if_changed` to dedupe on the 5.12 signature, and
# the frontend EVENT LOG renders per type.
EVENT_DOCUMENTS_UPLOADED      = "documents_uploaded"
EVENT_CLIENT_ANSWERS_APPLIED  = "client_answers_applied"
EVENT_RECOMMENDATION_REOPENED = "recommendation_reopened"
EVENT_ISSUE_REOPENED          = "issue_reopened"
EVENT_SQS_SNAPSHOT            = "sqs_snapshot"

# H7: the client's eight material events, each now emitted by the writer the
# action goes through. `field_changed` covers four of the eight - producer
# edit, form edit, client answer and generated-value override - which are the
# same act on the same fact differing only in WHO and in what the value was
# BEFORE. `change_kind()` below separates them from stored data, so they can
# never drift apart the way four hand-maintained event names would.
EVENT_FIELD_CHANGED            = "field_changed"
EVENT_RECOMMENDATION_DISMISSED = "recommendation_dismissed"
EVENT_RECOMMENDATION_ANSWERED  = "recommendation_answered"
EVENT_ISSUE_STATUS_CHANGED     = "issue_status_changed"
EVENT_CONFLICT_RESOLVED        = "conflict_resolved"
EVENT_PRODUCER_OVERRIDE        = "producer_override"
EVENT_PACKAGE_DOWNLOADED       = "package_downloaded"

# Product-history events (previously `activity_events`, D50). The STRINGS are
# unchanged from activity_service so the Activity Log renders them exactly as
# it always has.
EVENT_FORMS_GENERATED       = "forms_generated"
EVENT_SQS_SCORED            = "sqs_scored"
EVENT_ARQ_SENT              = "questionnaire_sent"
EVENT_ARQ_OPENED            = "questionnaire_opened"
EVENT_ARQ_IN_PROGRESS       = "questionnaire_in_progress"
EVENT_ARQ_SUBMITTED         = "questionnaire_submitted"
EVENT_ANSWERS_APPLIED       = "answers_applied"
EVENT_REMINDER_SENT         = "reminder_sent"
EVENT_DOWNLOAD              = "download"

# Exactly the nine types the navbar Activity Log has always shown. A new event
# is E&O-only unless it is added here deliberately - the Activity Log is a
# producer-facing feed, not a firehose.
PRODUCT_VISIBLE_EVENTS = frozenset({
    EVENT_FORMS_GENERATED, EVENT_SQS_SCORED, EVENT_ARQ_SENT, EVENT_ARQ_OPENED,
    EVENT_ARQ_IN_PROGRESS, EVENT_ARQ_SUBMITTED, EVENT_ANSWERS_APPLIED,
    EVENT_REMINDER_SENT, EVENT_DOWNLOAD,
})

# The client's section 12 list, for the anti-rot test. Every one of these must
# have a writer that reaches the spine.
MATERIAL_CHANGE_EVENTS = frozenset({
    EVENT_FIELD_CHANGED, EVENT_RECOMMENDATION_DISMISSED,
    EVENT_RECOMMENDATION_ANSWERED, EVENT_ISSUE_STATUS_CHANGED,
    EVENT_CONFLICT_RESOLVED, EVENT_PRODUCER_OVERRIDE,
    EVENT_CLIENT_ANSWERS_APPLIED, EVENT_PACKAGE_DOWNLOADED,
})

# ── Actions (the client's "reason/action when relevant") ──────────────────────
ACTION_EDITED     = "edited"
ACTION_ANSWERED   = "answered"
ACTION_DISMISSED  = "dismissed"
ACTION_RESOLVED   = "resolved"
ACTION_REOPENED   = "reopened"
ACTION_CONFIRMED  = "confirmed"
ACTION_OVERRIDDEN = "overridden"
ACTION_RETRACTED  = "retracted"
ACTION_APPLIED    = "applied"
ACTION_DOWNLOADED = "downloaded"

# ── Change kinds (the client's 8th event, DERIVED not declared) ───────────────
# A producer edit and a "generated-value override" are the same keystroke; what
# separates them is what the value WAS. `previous_source` carries the prior
# confidence, which `form_routes.update_pdf` already has in hand before the
# edit applies - so this costs one argument, not a new code path.
KIND_FILL       = "fill"                      # a blank gained a value
KIND_CORRECTION = "correction"                # a human value was changed
KIND_OVERRIDE   = "generated_value_override"  # an AI-generated value was replaced
KIND_RETRACTION = "retraction"                # a value was removed

CHANGE_KIND_LABELS = {
    KIND_FILL:       "filled a blank field",
    KIND_CORRECTION: "corrected an existing entry",
    KIND_OVERRIDE:   "overrode an AI-generated value",
    KIND_RETRACTION: "removed a value",
}

# The prior-confidence values that mean "this value came from the model".
#
# There are TWO confidence vocabularies in this codebase and a caller may hold
# either, so both are listed here rather than asking every call site to
# translate (translating at the call sites is how the two drifted apart in the
# first place):
#   * the FACT envelope's, written by extraction_service and pinned by
#     `field_source_audit.confidence`'s CHECK - deterministic / filled /
#     ai_high / ai_low.
#   * the FORM FIELD highlight vocabulary, written by pdf_service and carried on
#     `generated_forms[form].confidence` - filled / low_confidence /
#     missing_required / missing_required_gate / ai_verified / conflicted /
#     explicit_no / not_applicable / client_arq.
# `low_confidence` and `ai_verified` are the highlight vocabulary's way of
# saying "the model produced this"; `filled` means deterministic or human in
# BOTH, which is why it is absent here.
#
# NOTE: do not reach for `_load_fieldmap`'s `ai_set` as a better signal - it is
# a stub returning an empty set (pdf_service.py, "cache layer removed"), so the
# `ai_set` membership test in form_routes.update_pdf is dead code.
_AI_SOURCES = ("ai_high", "ai_low", "ai", "low_confidence", "ai_verified")

# Match `field_source_audit`'s own call-site clamp exactly. The spine and the
# change log carry the SAME values; clipping them differently would make one
# record contradict the other in the E&O export.
VALUE_MAX = 2000


def _clip(value, limit: int = VALUE_MAX) -> Optional[str]:
    """Normalise any value to a bounded string, or None for a real absence.

    An empty string and None both mean "no value" here - the record renders
    "(blank)" either way, and storing both spellings would make two identical
    edits look different.
    """
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    return text[:limit]


def derive_role(source: Optional[str] = None,
                user_id: Optional[str] = None,
                role: Optional[str] = None) -> str:
    """Who acted, in workflow terms (D51).

    `source` is checked FIRST and that ordering is load-bearing: a client
    questionnaire answer is applied under the SESSION OWNER's user id
    (arq_service passes the producer's id, because the client has no account),
    so deciding on "is there a user_id" would file every client answer as a
    producer action - which is precisely the attribution error section 12 is
    about.
    """
    if role in _ROLES:
        return role
    src = (source or "").strip().lower()
    if src in ("client_arq", "client"):
        return ROLE_CLIENT
    if src in ("ai", "system"):
        return ROLE_SYSTEM
    return ROLE_PRODUCER if str(user_id or "").strip() else ROLE_SYSTEM


def change_kind(previous_source: Optional[str],
                previous_value=None,
                new_value=None) -> str:
    """Classify a field change without asking the caller to label it.

    The order is load-bearing. "Was there a value at all?" is settled BEFORE
    "who produced it", because a field that was empty cannot have been
    overridden however its highlight label was spelled - a blank required box
    carries an AI-ish label on plenty of forms, and calling that an override
    would put "the producer overrode an AI-generated value" in an E&O record
    against a box the AI never filled.
    """
    prev = _clip(previous_value)
    new  = _clip(new_value)
    if new is None and prev is not None:
        return KIND_RETRACTION
    if prev is None:
        return KIND_FILL
    if (previous_source or "").strip().lower() in _AI_SOURCES:
        return KIND_OVERRIDE
    return KIND_CORRECTION


def visibility_for(event_type: str) -> str:
    """Product-history feed, or E&O record only (D50)."""
    return (VISIBILITY_PRODUCT if event_type in PRODUCT_VISIBLE_EVENTS
            else VISIBILITY_AUDIT)


def build_change_envelope(
    *,
    event_type: str,
    action: Optional[str] = None,
    fact_key: Optional[str] = None,
    field_name: Optional[str] = None,
    form_id: Optional[str] = None,
    previous_value=None,
    new_value=None,
    previous_source: Optional[str] = None,
    source: Optional[str] = None,
    user_id: Optional[str] = None,
    role: Optional[str] = None,
    reason: Optional[str] = None,
    detail: Optional[dict] = None,
) -> dict:
    """The client's seven attributes, in one fixed shape, for every event.

    affected fact/field -> fact_key + field_name
    original value      -> previous_value
    new value           -> new_value
    actor               -> actor_id  (resolved to a name at READ time; the id is
                                      the immutable anchor and a rename must not
                                      rewrite history)
    role                -> role      (derived, D51)
    timestamp           -> the row's own created_at, written by the spine
    reason / action     -> reason + action

    `detail` carries whatever is specific to one event type (rec_id, issue_id,
    doc_id, candidates, ...). It is deliberately the ONLY free-form part: the
    seven attributes above are never allowed to hide inside it, which is how
    they went missing in the first place.
    """
    resolved_role = derive_role(source=source, user_id=user_id, role=role)
    envelope = {
        "schema":          1,
        "event_type":      event_type,
        "action":          action,
        "fact_key":        fact_key or None,
        "field_name":      field_name or None,
        "form_id":         form_id or None,
        "previous_value":  _clip(previous_value),
        "new_value":       _clip(new_value),
        "previous_source": (previous_source or None),
        "source":          (source or None),
        "actor_id":        str(user_id) if user_id else None,
        "role":            resolved_role,
        "reason":          _clip(reason),
        "visibility":      visibility_for(event_type),
    }
    if event_type == EVENT_FIELD_CHANGED:
        envelope["change_kind"] = change_kind(previous_source,
                                              previous_value, new_value)
    if detail:
        envelope["detail"] = detail
    return envelope


# ── Reading the spine ─────────────────────────────────────────────────────────

def normalize_event(row: dict, actors: Optional[dict] = None) -> dict:
    """One spine row -> one history entry, whatever shape it was written in.

    Two shapes exist and both must render:
      * H7 envelopes (`event_data.schema == 1`) - the seven attributes are
        already in fixed positions.
      * Pre-H7 events (C5-A: documents_uploaded, client_answers_applied, the
        two reopens, sqs_snapshot) - free-form `event_data`, no role, no actor
        beyond the row's own `user_id`. They are REAL history and must not be
        dropped just because they predate the envelope, so the missing
        attributes are filled from the row and the payload is kept as `detail`.

    `actors` is the map from `audit_service.resolve_actors`, resolved once per
    export. An unknown id still renders - as the id - because an E&O record
    that silently omits an actor is worse than one showing a raw identifier.
    """
    data = row.get("event_data")
    if not isinstance(data, dict):
        data = {}
    event_type = row.get("event_type") or data.get("event_type") or ""
    is_envelope = data.get("schema") == 1

    actor_id = data.get("actor_id") if is_envelope else None
    actor_id = actor_id or (str(row.get("user_id")) if row.get("user_id") else None)

    resolved = (actors or {}).get(str(actor_id or ""), None)
    if resolved:
        actor_name  = resolved.get("name") or resolved.get("email") or str(actor_id)
        actor_email = resolved.get("email") or ""
    else:
        actor_name  = str(actor_id) if actor_id else ""
        actor_email = ""

    if is_envelope:
        role = data.get("role") or derive_role(source=data.get("source"),
                                               user_id=actor_id)
        detail = data.get("detail") or {}
    else:
        role = derive_role(user_id=actor_id)
        detail = {k: v for k, v in data.items() if k != "schema"}

    return {
        "event_type":      event_type,
        "action":          data.get("action") if is_envelope else None,
        "fact_key":        data.get("fact_key") if is_envelope else None,
        "field_name":      data.get("field_name") if is_envelope else None,
        "form_id":         data.get("form_id") if is_envelope else None,
        "previous_value":  data.get("previous_value") if is_envelope else None,
        "new_value":       data.get("new_value") if is_envelope else None,
        "previous_source": data.get("previous_source") if is_envelope else None,
        "change_kind":     data.get("change_kind") if is_envelope else None,
        "source":          data.get("source") if is_envelope else None,
        "reason":          data.get("reason") if is_envelope else None,
        "actor_id":        actor_id,
        "actor_name":      actor_name,
        "actor_email":     actor_email,
        "role":            role,
        "role_label":      ROLE_LABELS.get(role, role),
        "occurred_at":     row.get("created_at") or "",
        "detail":          detail,
        "legacy":          not is_envelope,
    }


def actor_ids_in(rows) -> set:
    """Every distinct user id referenced by a batch of spine rows.

    Reads BOTH the envelope's `actor_id` and the row's own `user_id`: a pre-H7
    event has only the latter, and an envelope written by a system path has
    only the former.
    """
    ids = set()
    for row in rows or []:
        if not isinstance(row, dict):
            continue
        if row.get("user_id"):
            ids.add(str(row["user_id"]))
        data = row.get("event_data")
        if isinstance(data, dict) and data.get("actor_id"):
            ids.add(str(data["actor_id"]))
    return ids
