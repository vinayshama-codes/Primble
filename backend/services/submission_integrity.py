"""submission_integrity.py

Package-level Submission Integrity Validation (Beta Report §4.1).

Runs AFTER extraction/classification and BEFORE any downstream workflow
(form recommendations, SQS scoring, cross-form validation, client
questionnaire generation, form generation, submission brief).

Goal: detect when an uploaded document package likely contains documents
belonging to MULTIPLE insureds (the Beta Test 1 case: Women's Bar
Association + Wake County + Company ABC) and pause the workflow for a
user-facing review instead of silently treating unrelated documents as
one clean submission.

Design notes
------------
* This module is PURE - it takes the already-extracted per-document facts
  and returns a verdict dict. No DB, no I/O, no network. Easy to unit-test.
* Identity comparison is NORMALIZATION-AWARE. We deliberately do not flag
  formatting differences (case, punctuation, entity-suffix, date format) as
  "different insureds" - that is the exact false-positive problem Workstream 2
  is separately solving. The LOW-confidence *pause* is driven only by strong
  identity signals (distinct normalized applicant-name clusters, or distinct
  FEINs). Softer divergences (entity type, address, operations, policy number)
  downgrade confidence to MEDIUM ("review recommended") but do NOT block.

Verdict statuses
----------------
* high   - documents appear to belong together (no pause).
* medium - review recommended; softer signals diverge (no pause).
* low    - documents may belong to MULTIPLE submissions (review_required=True).
"""

import logging
import re
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

# Shared normalization layer (Beta Report §5). The soft-divergence comparison
# below reuses these so formatting/synonym/alias-only differences do NOT surface
# as spurious "differs across documents" review notes.
from services.normalization import (
    normalize_address, normalize_carrier, normalize_entity_type, normalize_date,
)

logger = logging.getLogger(__name__)

INTEGRITY_MODEL_VERSION = "1.0.0"

STATUS_HIGH = "high"
STATUS_MEDIUM = "medium"
STATUS_LOW = "low"

# A LOW Submission Integrity verdict PAUSES the pipeline and routes the user to
# the "Submission Integrity Review Needed" screen (the original flow): the
# pipeline short-circuit, the route gate, the worker gate, and the frontend
# auto-route all key off `review_required`. HIGH / MEDIUM never pause and are
# surfaced as an advisory banner on the recommendations/SQS screen. Flip this to
# False to make LOW advisory (non-blocking) as well.
INTEGRITY_BLOCKING = True


# ── Value extraction (handles the {value, confidence} envelope) ───────────────

def _fv(facts: dict, key: str, default=None):
    """Extract a scalar fact, unwrapping the annotated {value, confidence} envelope."""
    if not isinstance(facts, dict):
        return default
    v = facts.get(key, default)
    if isinstance(v, dict) and "value" in v:
        v = v["value"]
    if v is None or (isinstance(v, str) and v.strip().lower() in ("", "null", "none")):
        return default
    return v


# ── Normalization (intentionally light - mirrors the WS2 intent) ──────────────

_ENTITY_SUFFIXES = (
    "incorporated", "corporation", "company", "limited liability company",
    "limited liability partnership", "limited partnership", "limited",
    "llc", "inc", "corp", "co", "ltd", "llp", "lp", "pllc", "pc", "pa",
    "dba",
)


def _normalize_name(value: Any) -> str:
    """Aggressively normalize an organization name for identity comparison.

    Lowercase, strip punctuation, collapse whitespace, and remove trailing
    entity-type suffixes (LLC / Inc / Corp / ...). Returns '' when there is no
    usable signal. This is comparison-only - raw values are preserved for display.
    """
    if value is None:
        return ""
    s = str(value).lower()
    s = re.sub(r"[^a-z0-9\s]+", " ", s)   # drop punctuation
    s = re.sub(r"\s+", " ", s).strip()
    if not s:
        return ""
    # Strip trailing entity suffixes repeatedly (handles "co inc", "llc").
    changed = True
    while changed:
        changed = False
        for suf in _ENTITY_SUFFIXES:
            if s == suf:
                return ""
            if s.endswith(" " + suf):
                s = s[: -(len(suf) + 1)].strip()
                changed = True
    return s


def _normalize_fein(value: Any) -> str:
    """Digits-only FEIN. Returns '' unless EXACTLY 9 digits (a complete US FEIN).

    INTENTIONAL DECISION (§4.1, mirrors services.normalization.normalize_fein):
    requiring exactly 9 digits means a partial/over-long OCR read normalizes to ''
    (treated as ABSENT, so identity falls back to the applicant name) rather than a
    distinct value that could manufacture a FALSE cross-document FEIN conflict and a
    spurious multi-insured pause. We deliberately do NOT loosen this to 8-digit /
    near-match: a near-FEIN cannot be compared reliably (a dropped middle digit
    makes the same insured look like two), so loosening would trade a rare missed
    detection - already covered by name clustering - for false blocks. Keep these
    two normalizers in lockstep.
    """
    if value is None:
        return ""
    digits = re.sub(r"\D", "", str(value))
    return digits if len(digits) == 9 else ""


def _normalize_text(value: Any) -> str:
    if value is None:
        return ""
    s = str(value).lower()
    s = re.sub(r"[^a-z0-9\s]+", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def _name_tokens(norm_name: str) -> frozenset:
    return frozenset(t for t in norm_name.split() if len(t) > 1)


def _names_match(a: str, b: str) -> bool:
    """Two normalized names refer to the same insured if equal, one is a
    substring of the other, or their significant tokens substantially overlap.
    """
    if not a or not b:
        return False
    if a == b or a in b or b in a:
        return True
    ta, tb = _name_tokens(a), _name_tokens(b)
    if not ta or not tb:
        return False
    overlap = len(ta & tb)
    smaller = min(len(ta), len(tb))
    # ≥ 2/3 of the smaller name's tokens shared → same insured.
    return smaller > 0 and (overlap / smaller) >= 0.67


# ── Per-document identity signature ───────────────────────────────────────────

_IDENTITY_NAME_KEYS = ("applicant_name", "named_insured", "insured_name", "loss_run_insured_name")
_POLICY_NUMBER_KEYS = ("policy_number", "policy_no", "policy_numbers")
_CARRIER_KEYS = ("carrier_name", "carrier", "prior_carrier", "insurer_name")


def _doc_identity(doc: dict) -> dict:
    """Extract the comparison signature for one document."""
    facts = doc.get("facts") or {}

    raw_name = None
    for k in _IDENTITY_NAME_KEYS:
        raw_name = _fv(facts, k)
        if raw_name:
            break

    raw_policy = None
    for k in _POLICY_NUMBER_KEYS:
        raw_policy = _fv(facts, k)
        if raw_policy:
            break
    if isinstance(raw_policy, list):
        raw_policy = raw_policy[0] if raw_policy else None

    raw_carrier = None
    for k in _CARRIER_KEYS:
        raw_carrier = _fv(facts, k)
        if raw_carrier:
            break

    return {
        "raw_name":       str(raw_name) if raw_name else "",
        "name_key":       _normalize_name(raw_name),
        "dba":            _normalize_name(_fv(facts, "dba_name")),
        "fein":           _normalize_fein(_fv(facts, "fein")),
        # Soft-divergence identity fields use the SHARED normalization layer so
        # formatting/synonym/alias-only differences (ST vs Street, LLC vs Limited
        # Liability Company, EMC vs Employers Mutual Casualty) do NOT produce a
        # spurious "differs across documents" review note (Beta Report §5).
        "entity_type":    normalize_entity_type(_fv(facts, "entity_type")),
        "mailing":        normalize_address(_fv(facts, "mailing_address")),
        "physical":       normalize_address(_fv(facts, "physical_address")),
        "operations":     _normalize_text(_fv(facts, "operations_description"))[:120],
        # Narrative-only: high-level account/executive summary (Beta Report §4.2 item #11).
        # Only populated for narrative docs; null for dec pages, applications, etc. — so
        # this only fires as a divergence signal when multiple narrative docs disagree.
        "account_desc":   _normalize_text(_fv(facts, "account_description"))[:200],
        "policy_number":  re.sub(r"[^a-z0-9]", "", str(raw_policy).lower()) if raw_policy else "",
        # Date-aware so 07/15/2025 == 7/15/25 don't read as a difference (WS2).
        "effective_date": normalize_date(_fv(facts, "effective_date")) or _normalize_text(_fv(facts, "effective_date")),
        "carrier":        normalize_carrier(raw_carrier),
    }


# ── Clustering ────────────────────────────────────────────────────────────────

def _cluster_by_insured(doc_sigs: List[dict]) -> List[dict]:
    """Group document signatures into likely-insured clusters.

    Primary key is the normalized applicant name; documents are merged into an
    existing cluster when the name matches (see _names_match) OR they share a
    9-digit FEIN. Documents with no name AND no FEIN are collected into a single
    'unidentified' cluster and never drive a multi-insured pause on their own.
    """
    clusters: List[dict] = []
    unidentified: List[dict] = []

    for sig in doc_sigs:
        if not sig["name_key"] and not sig["fein"]:
            unidentified.append(sig)
            continue

        placed = False
        for cluster in clusters:
            name_hit = sig["name_key"] and any(
                _names_match(sig["name_key"], n) for n in cluster["name_keys"]
            )
            fein_hit = sig["fein"] and sig["fein"] in cluster["feins"]
            if name_hit or fein_hit:
                cluster["members"].append(sig)
                if sig["name_key"]:
                    cluster["name_keys"].add(sig["name_key"])
                if sig["fein"]:
                    cluster["feins"].add(sig["fein"])
                if not cluster["label"] and sig["raw_name"]:
                    cluster["label"] = sig["raw_name"]
                placed = True
                break

        if not placed:
            clusters.append({
                "label":     sig["raw_name"] or (f"FEIN {sig['fein']}" if sig["fein"] else "Unidentified"),
                "name_keys": {sig["name_key"]} if sig["name_key"] else set(),
                "feins":     {sig["fein"]} if sig["fein"] else set(),
                "members":   [sig],
            })

    if unidentified:
        clusters.append({
            "label":     "Unidentified document(s)",
            "name_keys": set(),
            "feins":     set(),
            "members":   unidentified,
            "unidentified": True,
        })

    return clusters


# ── Public API ────────────────────────────────────────────────────────────────

def assess_submission_integrity(docs: List[dict]) -> dict:
    """Assess whether the uploaded documents belong to a single insured.

    Parameters
    ----------
    docs : list of processed-document dicts. Each must expose at least
           ``facts`` (the extracted fact dict) and ideally ``doc_id`` /
           ``filename`` for display + targeted removal.

    Returns
    -------
    A verdict dict (see module docstring). ``review_required`` is True ONLY for
    the LOW status, which is the package-level pause the report calls for.
    """
    now = datetime.now(timezone.utc).isoformat()
    docs = docs or []

    # Attach a stable id/filename to each signature for the UI + removal flow.
    doc_sigs: List[dict] = []
    for idx, d in enumerate(docs):
        sig = _doc_identity(d)
        sig["doc_id"] = str(d.get("doc_id") or idx)
        sig["filename"] = d.get("filename") or f"document_{idx + 1}"
        sig["doc_type"] = d.get("doc_type") or "unknown"
        doc_sigs.append(sig)

    # Single document (or none) can never be a multi-insured package.
    if len(doc_sigs) <= 1:
        return _verdict(
            status=STATUS_HIGH, confidence=1.0, clusters=[], doc_sigs=doc_sigs,
            reasons=[], signals={"document_count": len(doc_sigs)}, assessed_at=now,
        )

    clusters = _cluster_by_insured(doc_sigs)

    # "Real" insured clusters = those anchored by a name or FEIN (exclude the
    # catch-all unidentified bucket from the multi-insured count).
    insured_clusters = [c for c in clusters if not c.get("unidentified")]

    distinct_names = []
    for c in insured_clusters:
        if c["label"] and c["label"] not in distinct_names:
            distinct_names.append(c["label"])

    all_feins = set()
    for c in insured_clusters:
        all_feins |= c["feins"]

    # Independent identity anchors across the WHOLE package (incl. orphan docs).
    distinct_mailing = len({s["mailing"] for s in doc_sigs if s["mailing"]})
    distinct_carrier = len({s["carrier"] for s in doc_sigs if s["carrier"]})
    distinct_policy  = len({s["policy_number"] for s in doc_sigs if s["policy_number"]})
    has_orphan = any(not s["name_key"] and not s["fein"] for s in doc_sigs)

    signals = {
        "document_count":          len(doc_sigs),
        "insured_clusters":        len(insured_clusters),
        "distinct_applicant_names": len(distinct_names),
        "distinct_feins":          len(all_feins),
        "distinct_mailing":        distinct_mailing,
        "distinct_carrier":        distinct_carrier,
        "distinct_policy_numbers": distinct_policy,
        "has_unidentified_doc":    has_orphan,
    }

    reasons: List[str] = []

    # ── STRONG identity divergence → LOW (pause) ─────────────────────────────
    multi_insured = len(insured_clusters) >= 2 or len(all_feins) >= 2
    if multi_insured:
        if len(insured_clusters) >= 2:
            reasons.append(
                "Documents reference multiple distinct applicants/insureds: "
                + ", ".join(distinct_names)
            )
        if len(all_feins) >= 2:
            reasons.append(f"{len(all_feins)} distinct FEINs found across documents")
        return _verdict(
            status=STATUS_LOW, confidence=0.3, clusters=insured_clusters or clusters,
            doc_sigs=doc_sigs, reasons=reasons, signals=signals, assessed_at=now,
        )

    # ── ORPHAN-doc strong divergence → LOW (pause) ───────────────────────────
    # A document with NO applicant name AND NO FEIN is normally treated as a
    # benign supporting doc (loss run / narrative without letterhead). But when
    # the package ALSO carries two independent strong anchors that disagree -
    # ≥2 distinct mailing addresses AND ≥2 distinct carriers or policy numbers -
    # an orphan is far more likely a document from a DIFFERENT submission whose
    # name simply failed to extract (Beta case: Orbin CO dec page whose name did
    # not parse + an unrelated ACORD 125). A genuine supporting doc shares the
    # insured's address/carrier or carries neither, so this stays specific.
    if has_orphan and distinct_mailing >= 2 and (distinct_carrier >= 2 or distinct_policy >= 2):
        reasons.append(
            "A document could not be matched to the insured by name or FEIN and "
            "introduces a different mailing address and carrier/policy number - "
            "it may belong to a separate submission."
        )
        return _verdict(
            status=STATUS_LOW, confidence=0.4, clusters=insured_clusters or clusters,
            doc_sigs=doc_sigs, reasons=reasons, signals=signals, assessed_at=now,
        )

    # ── SOFTER divergence (names align) → MEDIUM (review recommended) ────────
    soft_reasons = _soft_divergence_reasons(doc_sigs)
    if soft_reasons:
        return _verdict(
            status=STATUS_MEDIUM, confidence=0.7, clusters=insured_clusters or clusters,
            doc_sigs=doc_sigs, reasons=soft_reasons, signals=signals, assessed_at=now,
        )

    return _verdict(
        status=STATUS_HIGH, confidence=0.95, clusters=insured_clusters or clusters,
        doc_sigs=doc_sigs, reasons=[], signals=signals, assessed_at=now,
    )


def _soft_divergence_reasons(doc_sigs: List[dict]) -> List[str]:
    """Non-blocking signals: same/compatible names but other identity fields differ.

    INTENTIONAL DECISION (§4.1 action item 2): when the applicant names align, a
    difference in DBA / address / entity type / operations / policy number /
    effective date / carrier / account description downgrades the verdict to MEDIUM
    (review recommended) but does NOT pause the workflow. These are normal for a
    single insured - multiple locations, a renewal onto a new carrier, several
    policies - so escalating them to a blocking LOW would generate false positives.
    Only distinct insured NAMES or distinct FEINs drive a blocking pause; this is a
    deliberate product choice, not a missing block.
    """
    reasons: List[str] = []

    def _distinct(field: str) -> List[str]:
        vals = [s[field] for s in doc_sigs if s.get(field)]
        return sorted(set(vals))

    if len(_distinct("dba")) > 1:
        reasons.append("DBA / trade name differs across documents")
    if len(_distinct("entity_type")) > 1:
        reasons.append("Entity type differs across documents")
    if len(_distinct("mailing")) > 1:
        reasons.append("Mailing address differs across documents")
    if len(_distinct("physical")) > 1:
        reasons.append("Location address differs across documents")
    if len(_distinct("policy_number")) > 1:
        reasons.append("Multiple distinct policy numbers found")
    if len(_distinct("effective_date")) > 1:
        reasons.append("Effective dates differ across documents")
    if len(_distinct("operations")) > 1:
        reasons.append("Operations descriptions differ across documents")
    if len(_distinct("account_desc")) > 1:
        reasons.append("Account descriptions differ across narrative documents")
    if len(_distinct("carrier")) > 1:
        reasons.append("Multiple carriers referenced across documents")
    return reasons


def _verdict(
    *, status: str, confidence: float, clusters: List[dict], doc_sigs: List[dict],
    reasons: List[str], signals: dict, assessed_at: str,
) -> dict:
    detected_entities = []
    for c in clusters:
        label = c.get("label")
        if label and not c.get("unidentified") and label not in detected_entities:
            detected_entities.append(label)

    cluster_out = []
    for i, c in enumerate(clusters):
        cluster_out.append({
            "cluster_id": i,
            "label":      c.get("label") or "Unidentified",
            "doc_ids":    [m["doc_id"] for m in c["members"]],
            "filenames":  [m["filename"] for m in c["members"]],
        })

    docs_out = [
        {
            "doc_id":     s["doc_id"],
            "filename":   s["filename"],
            "doc_type":   s["doc_type"],
            "applicant":  s["raw_name"] or "(no applicant name detected)",
            "fein":       s["fein"][-4:] if s["fein"] else None,  # last 4 only - PII
        }
        for s in doc_sigs
    ]

    if status == STATUS_LOW:
        message = (
            "Submission Integrity Review Needed\n"
            "Primble detected that the uploaded documents may not belong to the "
            "same submission.\n"
            + ("Detected entities: " + ", ".join(detected_entities) + ". "
               if detected_entities else "")
            + "These documents appear to reference multiple insureds. "
              "Please review the package before continuing."
        )
    elif status == STATUS_MEDIUM:
        message = (
            "Some submission details differ across the uploaded documents. "
            "Review is recommended, but you can continue."
        )
    else:
        message = "Documents appear to belong to the same submission."

    return {
        "status":           status,
        "review_required":  (status == STATUS_LOW) and INTEGRITY_BLOCKING,
        "confidence":       round(float(confidence), 3),
        "detected_entities": detected_entities,
        "clusters":         cluster_out,
        "documents":        docs_out,
        "reasons":          reasons,
        "signals":          signals,
        "message":          message,
        "overridden":       False,
        "override":         None,
        "assessed_at":      assessed_at,
        "model_version":    INTEGRITY_MODEL_VERSION,
    }


def cluster_documents(docs: List[dict]) -> List[dict]:
    """Group documents into likely-insured clusters for the 'Create separate
    submissions' split (Beta Report §4.1 action item 5).

    Returns a list of clusters, each ``{"label", "doc_ids", "unidentified"}``.
    Unlike the verdict's ``clusters`` (which omits the catch-all bucket), this
    PRESERVES the unidentified cluster so the caller can decide where nameless
    supporting documents (loss runs / narratives without letterhead) go and
    never drops them when splitting the package.
    """
    doc_sigs: List[dict] = []
    for idx, d in enumerate(docs or []):
        sig = _doc_identity(d)
        sig["doc_id"] = str(d.get("doc_id") or idx)
        doc_sigs.append(sig)
    out: List[dict] = []
    for c in _cluster_by_insured(doc_sigs):
        out.append({
            "label":        c.get("label") or "Submission",
            "doc_ids":      [m["doc_id"] for m in c["members"]],
            "unidentified": bool(c.get("unidentified")),
        })
    return out


def build_override_record(user_id: str, detected_entities: List[str]) -> dict:
    """Audit record stamped onto the verdict when the user chooses 'Continue anyway'."""
    return {
        "overridden_by":      str(user_id),
        "overridden_at":      datetime.now(timezone.utc).isoformat(),
        "acknowledged_entities": list(detected_entities or []),
        "action":             "continue_anyway",
    }
