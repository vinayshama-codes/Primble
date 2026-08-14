import concurrent.futures
import difflib
import io
import json
import logging
import os
import re
import threading
from functools import lru_cache
from typing import Any, Dict, List, Optional, Tuple

import httpx
import pikepdf
from PIL import Image
from fastapi import HTTPException

from config.settings import TEMPLATE_DIR, FORMS_DB_DIR, FORMS_SCHEMAS_DIR, groq_chat
from utils.helpers import _parse_address
from typing import NamedTuple
from services.extraction_service import _fv, ACTIVE_MODEL, _COVERAGE_DENIAL_RE
from services.fact_registry import FACT_REGISTRY
from services.normalization import detect_no_loss_assertion

logger = logging.getLogger(__name__)

# ── GPT model config — env-driven so any OpenAI model is selectable with zero code changes ──
GPT_MODEL       = os.getenv("GPT_MODEL",       "gpt-4.1-nano")
GPT_BATCH_SIZE  = int(os.getenv("GPT_BATCH_SIZE",  "80"))
GPT_TEMPERATURE = float(os.getenv("GPT_TEMPERATURE", "0.0"))

# ── Dedicated OpenAI client for form-fill GPT pass (lazy-initialised) ────────
# Client is created on first use so Pass 1 deterministic fills work without
# OPENAI_API_KEY being present.
try:
    from openai import AsyncOpenAI as _AsyncOpenAI, OpenAI as _SyncOpenAI
    _HAS_OPENAI = True
except ImportError:
    _HAS_OPENAI = False
    logger.warning("openai package not installed — GPT form fill pass disabled")

_openai_form_fill_client = None
_openai_form_fill_client_sync = None


def _get_openai_form_fill_client():
    global _openai_form_fill_client
    if _openai_form_fill_client is None:
        if not _HAS_OPENAI:
            raise RuntimeError("openai package not installed — install it with: pip install openai")
        api_key = os.getenv("OPENAI_API_KEY", "")
        if not api_key:
            raise RuntimeError(
                "OPENAI_API_KEY not set — GPT form-fill pass unavailable. "
                "Set OPENAI_API_KEY in your .env file."
            )
        _openai_form_fill_client = _AsyncOpenAI(
            api_key=api_key,
            http_client=httpx.AsyncClient(
                timeout=float(os.getenv("LLM_REQUEST_TIMEOUT", "120")),
            ),
        )
    return _openai_form_fill_client


def _get_openai_form_fill_client_sync():
    """SYNCHRONOUS form-fill client, for the ThreadPoolExecutor gap-fill path.

    Why a separate client (deadlock fix): an `httpx.AsyncClient` binds its
    connection pool AND its timeout timers to the event loop that created them.
    The gap-fill pass runs its calls on worker threads that each did
    `asyncio.run()` — a NEW event loop per call — while sharing the single
    module-level AsyncOpenAI client above. When a worker picked up a pooled
    connection created on another thread's now-closed loop, the await parked on
    a dead loop: it never completed, and the timeout never fired because that
    timer lived on the dead loop too. No exception, no log line — the thread
    simply blocked forever, and `concurrent.futures.as_completed()` waited on it
    forever, hanging the whole request. (Observed live: 4 compliance batches
    dispatched, 3 returned HTTP 200, the 4th vanished and all logging stopped.)

    `httpx.Client` is thread-safe and loop-free, so one shared sync client is
    both correct and connection-pool efficient across all worker threads.
    """
    global _openai_form_fill_client_sync
    if _openai_form_fill_client_sync is None:
        if not _HAS_OPENAI:
            raise RuntimeError("openai package not installed — install it with: pip install openai")
        api_key = os.getenv("OPENAI_API_KEY", "")
        if not api_key:
            raise RuntimeError(
                "OPENAI_API_KEY not set — GPT form-fill pass unavailable. "
                "Set OPENAI_API_KEY in your .env file."
            )
        _openai_form_fill_client_sync = _SyncOpenAI(
            api_key=api_key,
            http_client=httpx.Client(
                timeout=float(os.getenv("LLM_REQUEST_TIMEOUT", "120")),
            ),
        )
    return _openai_form_fill_client_sync

# ── PII fields excluded from LLM prompts (SOC2 / data minimisation) ──────────
# These fields are handled deterministically by Pass 1 (_ACORD_FIELD_RULES +
# _resolve_special) and must never be forwarded to external LLM providers.
# mailing_address / physical_address are decomposed by _resolve_special() into
# line1/line2/city/state/zip — GPT has no need for the raw concatenated string.
_PII_EXCLUDE_KEYS: frozenset = frozenset({
    "fein",              # federal tax ID — highest-sensitivity financial identifier
    "contact_phone",     # personal phone number
    "contact_email",     # personal email address
    "mailing_address",   # full street address — decomposed by Pass 1
    "physical_address",  # full street address — decomposed by Pass 1
})

# ── Facts that must NEVER enter the gap-fill FACTS BLOCK ─────────────────────
# `dec_page_entries` is the source-driven dec-page recording added 2026-08-12
# (see extraction_service). This exclusion STANDS, and it is not vestigial: the
# facts block is a JSON dump of ~170 extracted keys labelled "unverified hints",
# and dropping 1,200 verified dec entries into it would (a) mislabel verbatim
# document content as an unverified hint and (b) inflate the cached prefix by
# ~80k chars on every single call.
#
# The entries DO reach LLM call 2 as of 2026-08-13 - as their own rendered
# section, read before the raw document (`_render_dec_index`, Stage A, see
# CALL2_RETRIEVAL_REDESIGN D11). Different vehicle, deliberately.
_GAP_FILL_FACTS_EXCLUDE: frozenset = frozenset({"dec_page_entries"})

# ── The declarations index (Stage A) ─────────────────────────────────────────
# 0 restores the exact pre-2026-08-13 behaviour: no index section, no Stage A,
# every field walks the raw document. That is the kill switch, and it is a plain
# early return in `_render_dec_index` so there is one place to look.
_DEC_INDEX_ENABLED = os.getenv(
    "GAP_FILL_DEC_INDEX", "1").strip().lower() not in ("0", "false", "no")

# How much bigger than one raw-document chunk the index is allowed to be before
# it splits. 2 is not a tuning knob to be nudged - it is sized so the index NEVER
# splits at `_DEC_ENTRY_MAX`, because splitting it destroys the co-visibility
# that is the whole point (see `_dec_index_chunks`). The raw-chunk limit it
# multiplies is a QUALITY limit measured on noisy document text, ~89% of which is
# boilerplate on a real package; the index is verified label:value lines with no
# boilerplate at all, so the same character count carries an order of magnitude
# more answerable content. Raise `DEC_ENTRY_MAX` and this must rise with it.
_DEC_INDEX_BUDGET_MULT = int(os.getenv("GAP_FILL_DEC_INDEX_BUDGET_MULT", "2"))

_DEC_INDEX_HEADER = (
    "\n\n=== DECLARATIONS INDEX (AUTHORITATIVE) ===\n"
    "Every label:value pair this policy PRINTS on a declarations, coverage-summary\n"
    "or schedule page, copied verbatim and mechanically verified to appear in the\n"
    "uploaded document. Grouped by the section heading printed on the page it came\n"
    "from - the SAME label carries different amounts under different headings, so\n"
    "read the heading before using a value. [owner] marks whose value it is.\n"
    "This index does not contain policy wording or endorsement legal text.\n\n"
)
_DEC_INDEX_FOOTER = "\n=== END DECLARATIONS INDEX ===\n"
_DEC_INDEX_NO_SECTION = "(no section heading printed)"


def _render_dec_index(entries: Any) -> str:
    """The verified dec-page entries, grouped by section, as prompt text.

    WHY THIS EXISTS. Measured on the real 271-page ORBIN package: 30 declarations
    and schedule pages, 241 pages of ISO/AAIS standard wording - 11% signal. Every
    documented wrong-value defect in this codebase (C22 ERIN ROYAL, C23 umbrella
    limits, C46 phantom vehicle rows) has its source in the other 89%, which the
    gap-fill model was reading in full on every call to find one address.

    This renders the signal alone, at roughly 3% of the document's size, with the
    one piece of structure a flat character stream destroys: which coverage part's
    page a figure was printed on. That is the C23 discriminator - the umbrella's
    $3,000,000 and the GL's $1,000,000 are sixty-two pages apart under identical
    labels, and here they sit under different headings, in one prompt, co-visible.

    It is an INDEX, never a replacement. Fields it cannot answer walk the whole
    raw document exactly as before (Stage B). Returns "" on anything unusable, so
    every failure mode lands on the old behaviour rather than on a blank form.
    """
    if not _DEC_INDEX_ENABLED or not isinstance(entries, list) or not entries:
        return ""
    # Preserve first-appearance order of sections AND of entries within them:
    # the extraction pass walks the document in order, so this reads like the
    # package reads. Sorting would scatter one dec page across the index.
    sections: Dict[str, List[str]] = {}
    seen: set = set()
    for item in entries:
        if not isinstance(item, dict):
            continue
        label = str(item.get("label") or "").strip()
        value = str(item.get("value") or "").strip()
        if not label or not value:
            continue
        section = str(item.get("section") or "").strip() or _DEC_INDEX_NO_SECTION
        owner = str(item.get("owner") or "").strip().lower()
        key = (section.lower(), label.lower(), value.lower())
        if key in seen:
            continue
        seen.add(key)
        # `owner` is the guard against the classic wrong-box defect - the
        # producer's phone in the applicant's phone box. "other" carries no
        # information, so it is not printed rather than printed as noise.
        suffix = f"  [{owner}]" if owner and owner != "other" else ""
        sections.setdefault(section, []).append(f"  {label}: {value}{suffix}")
    if not sections:
        return ""
    body = "\n\n".join(
        f"[{section}]\n" + "\n".join(lines) for section, lines in sections.items()
    )
    return _DEC_INDEX_HEADER + body + _DEC_INDEX_FOOTER


def dec_index_coverage(entries: Any, stamped_values: Any) -> dict:
    """Which declarations values reached a form, and which went nowhere.

    THE QUESTION THIS ANSWERS, verbatim from the owner: "what about the data that
    was present in the declaration page and it didn't get stamped on the form".

    Until Stage A there was no way to answer it except by reading the generated
    PDF next to the source package by eye, which is how it has been answered so
    far - unreliably, and only for the boxes someone thought to look at. The
    index changed that: every entry is a value the declarations pages actually
    printed, mechanically verified. So the answer is a SUBTRACTION, not a
    judgement, and it costs nothing - no LLM, no document scan.

        recorded - stamped = the gap, itemised

    Grouped by section, because "the GL SCHEDULE page contributed 4 of its 31
    values" is an actionable sentence and "440 values were unused" is not.

    DELIBERATELY NOT A GUARD. It changes no form and blocks nothing. Several
    unused entries are unused for good reasons - a dec page prints plenty that no
    ACORD field asks for (audit basis, program code, servicing contacts), and an
    ACORD 125 legitimately ignores everything an ACORD 127 wants. Treating this
    number as a defect count would be wrong; treating a section with ZERO
    consumed values as worth a look is the point.
    """
    if not isinstance(entries, list) or not entries:
        return {"recorded": 0, "stamped": 0, "sections": {}, "unused": []}
    stamped = {
        _normalize_for_search(str(v))
        for v in (stamped_values or [])
        if v not in (None, "") and str(v).strip()
    }
    stamped.discard("")
    sections: Dict[str, Dict[str, int]] = {}
    unused: List[dict] = []
    seen: set = set()
    n_recorded = n_stamped = 0
    for item in entries:
        if not isinstance(item, dict):
            continue
        label = str(item.get("label") or "").strip()
        value = str(item.get("value") or "").strip()
        if not label or not value:
            continue
        key = (label.lower(), value.lower())
        if key in seen:
            continue
        seen.add(key)
        section = str(item.get("section") or "").strip() or _DEC_INDEX_NO_SECTION
        bucket = sections.setdefault(section, {"recorded": 0, "stamped": 0})
        n_recorded += 1
        bucket["recorded"] += 1
        # A value "reached the form" if it was stamped anywhere, in any field.
        # Attribution to a SPECIFIC field is deliberately not attempted: a value
        # can legitimately land in several boxes, and guessing which box owns it
        # is the open-vocabulary matching this codebase keeps refusing to build.
        if _normalize_for_search(value) in stamped:
            n_stamped += 1
            bucket["stamped"] += 1
        else:
            unused.append({"section": section, "label": label, "value": value,
                           "owner": item.get("owner") or "other"})
    return {"recorded": n_recorded, "stamped": n_stamped,
            "sections": sections, "unused": unused}


def log_dec_index_coverage(entries: Any, stamped_values: Any,
                           label: str = "package") -> dict:
    """`dec_index_coverage` plus a readable log line per section. Never raises -
    a reporting failure must not cost a generated package."""
    try:
        report = dec_index_coverage(entries, stamped_values)
    except Exception as ex:                                    # noqa: BLE001
        logger.warning("dec_index_coverage failed (%s)", ex)
        return {"recorded": 0, "stamped": 0, "sections": {}, "unused": []}
    if not report["recorded"]:
        return report
    pct = 100.0 * report["stamped"] / max(1, report["recorded"])
    logger.info(
        "DEC_INDEX_COVERAGE %s: %d of %d recorded declarations values reached a "
        "form (%.0f%%). %d unused.",
        label, report["stamped"], report["recorded"], pct, len(report["unused"]),
    )
    for section, counts in sorted(
            report["sections"].items(), key=lambda kv: kv[1]["stamped"] - kv[1]["recorded"]):
        flag = "  <-- nothing from this page reached a form" if not counts["stamped"] else ""
        logger.info("  DEC_INDEX_COVERAGE   %-46s %3d/%-3d%s",
                    section[:46], counts["stamped"], counts["recorded"], flag)
    return report


def _dec_index_chunks(entries: Any, budget: int) -> List[str]:
    """The index as prompt-ready pieces, each independently wrapped.

    THE INDEX SHOULD NEVER SPLIT, and the caller's budget is sized so it does
    not: `_DEC_ENTRY_MAX` (1200) entries render to ~66k chars against a budget of
    2 x `_GAP_FILL_DOC_CHARS_PER_CALL` (112k). That is not a coincidence to be
    tuned away - splitting the index destroys the one property it exists for.
    Co-visibility is the C23 fix: the umbrella's $3,000,000 and the GL's
    $1,000,000 must be in the SAME call for the model to tell them apart. Two
    index pieces put them back in different calls resolved by majority vote,
    which is precisely the failure the raw-document walk already has.

    Splitting is therefore the degradation path, not the design, and it is safe
    rather than correct: every field the index leaves blank walks the whole raw
    document in Stage B regardless. Kept so a pathological package cannot build a
    single unbounded call.
    """
    text = _render_dec_index(entries)
    if not text:
        return []
    inner_budget = max(2_000, int(budget) - len(_DEC_INDEX_HEADER) - len(_DEC_INDEX_FOOTER))
    body = text[len(_DEC_INDEX_HEADER):len(text) - len(_DEC_INDEX_FOOTER)]
    if len(body) <= inner_budget:
        return [text]
    parts = _split_text_on_boundaries(body, inner_budget)
    logger.warning(
        "dec_index: %d chars exceeds the %d-char single-call budget and was split "
        "into %d pieces. Values printed under different section headings are no "
        "longer co-visible in one call (see this function's docstring). Fields the "
        "index cannot answer still walk the full document in Stage B.",
        len(body), inner_budget, len(parts),
    )
    return [_DEC_INDEX_HEADER + p + _DEC_INDEX_FOOTER for p in parts]

# Per-row PII sub-keys stripped from schedule list facts (e.g. auto_drivers)
# before they reach an LLM prompt, rather than excluding the whole list. DOB
# and license number are the sensitive identifiers; they are already
# deterministically stamped onto the form by _resolve_schedule_row (Pass 1),
# so gap-fill never needs to see them. Other row fields (name, hire_date,
# experience_years, vehicle_use_percent) are left in case a legitimate
# narrative gap-fill question needs them (e.g. "describe the driver
# experience program").
_SCHEDULE_ROW_PII_SUBKEYS: Dict[str, frozenset] = {
    "auto_drivers": frozenset({"dob", "license_number"}),
}


def _redact_schedule_rows(list_key: str, rows: Any) -> Any:
    """Strip _SCHEDULE_ROW_PII_SUBKEYS[list_key] from every row dict. Returns
    ``rows`` unchanged if list_key has no registered PII sub-keys or rows
    isn't a list."""
    subkeys = _SCHEDULE_ROW_PII_SUBKEYS.get(list_key)
    if not subkeys or not isinstance(rows, list):
        return rows
    return [
        {k: v for k, v in row.items() if k not in subkeys} if isinstance(row, dict) else row
        for row in rows
    ]

# ── Canonical valid fact-key set (full registry, not just current document) ───
# Used to validate GPT-returned new_mappings keys and reject hallucinations.
# A key absent from the CURRENT document's facts is still a valid structural
# mapping (e.g. wc_payroll is valid even in a GL-only submission).
_FULL_REGISTRY_KEYS: frozenset = frozenset(FACT_REGISTRY.keys()) | frozenset({
    "_addr_line1", "_addr_line2", "_addr_city", "_addr_state", "_addr_zip",
    "_loc_line1",  "_loc_line2",  "_loc_city",  "_loc_state",  "_loc_zip",
})

# ── Schedule row expansion ────────────────────────────────────────────────────
# Maps AcroForm field base-name prefixes to the list fact that backs them.
# Fields with row suffix _A/_B/..._N are resolved to list[idx] automatically.

_ROW_LETTER_TO_IDX: Dict[str, int] = {chr(ord("A") + i): i for i in range(14)}

_SCHED_SKIP = object()  # sentinel: not a schedule field → fall through to regular rules


class _ScheduleDef(NamedTuple):
    list_key: str            # fact dict key that holds the list
    sub_key: Optional[str]   # dict sub-key to extract; None = use item directly
    row_offset: int = 0      # subtract from letter-index before list lookup


_SCHEDULE_REGISTRY: Dict[str, "_ScheduleDef"] = {
    # ── Vehicles (ACORD 127) ────────────────────────────────────────────────
    # NOTE (2026-07-21): the four `Vehicle_*Identifier`/`*Name`/`BodyCode` entries
    # below are the names ACORD 127 ACTUALLY uses. Audited against all 17 real
    # schemas: of the vehicle entries only `Vehicle_ModelYear` and
    # `Vehicle_GrossVehicleWeight` matched a real field, so VIN / make / model /
    # body type were extracted by `extraction_service` into `auto_vin_schedule`
    # and then had nowhere to land - the identity columns of the vehicle schedule
    # could never be stamped, and those boxes fell through to a gap-fill guess.
    # The generic aliases are retained (harmless, and other ACORD editions may
    # use them); these additions are what make the binding live.
    "Vehicle_ModelYear":             _ScheduleDef("auto_vin_schedule", "year"),
    "Vehicle_Year":                  _ScheduleDef("auto_vin_schedule", "year"),
    "Vehicle_ManufacturersName":     _ScheduleDef("auto_vin_schedule", "make"),
    "Vehicle_Make":                  _ScheduleDef("auto_vin_schedule", "make"),
    "Vehicle_ModelName":             _ScheduleDef("auto_vin_schedule", "model"),
    "Vehicle_Model":                 _ScheduleDef("auto_vin_schedule", "model"),
    "Vehicle_VINIdentifier":         _ScheduleDef("auto_vin_schedule", "vin"),
    "Vehicle_VINNumber":             _ScheduleDef("auto_vin_schedule", "vin"),
    "Vehicle_VIN":                   _ScheduleDef("auto_vin_schedule", "vin"),
    "Vehicle_BodyCode":              _ScheduleDef("auto_vin_schedule", "body_type"),
    "Vehicle_BodyStyle":             _ScheduleDef("auto_vin_schedule", "body_type"),
    "Vehicle_BodyType":              _ScheduleDef("auto_vin_schedule", "body_type"),
    "Vehicle_GrossVehicleWeight":    _ScheduleDef("auto_vin_schedule", "gvw"),
    "Vehicle_GVW":                   _ScheduleDef("auto_vin_schedule", "gvw"),
    "Vehicle_GaragingAddress":       _ScheduleDef("auto_garaging_addresses", None),
    # Per-vehicle covered-auto symbol codes (2026-08-07). These three ARE real
    # ACORD 127 fields (rows A-D) and were the only symbol boxes on the form -
    # every one of them blank on every submission we have ever produced, because
    # no fact was bound to them. A row that states its own symbol wins; a row
    # that does not inherits the policy-level symbol for that coverage via
    # `_resolve_vehicle_symbol` below (a dec page normally prints ONE
    # "Comprehensive 07" that applies to every scheduled vehicle).
    "Vehicle_ComprehensiveSymbolCode": _ScheduleDef("auto_vin_schedule", "comp_symbol"),
    "Vehicle_CollisionSymbolCode":     _ScheduleDef("auto_vin_schedule", "coll_symbol"),
    "Vehicle_SymbolCode":              _ScheduleDef("auto_vin_schedule", "symbol"),

    # ── Drivers (ACORD 127) ─────────────────────────────────────────────────
    # NOTE: "Driver_FullName" is a DIFFERENT real schema field used by ACORD 133
    # (Driver_FullName_A/B/C) — kept as-is, do not repoint it. ACORD 127 itself
    # has no "Driver_FullName" field; it splits the name into GivenName/Surname,
    # so those two resolve via the "_name_given"/"_name_surname" sentinel
    # sub-keys (see _resolve_schedule_row) instead of both taking the raw
    # "name" string. LicenseNumber/LicenseStateOrProvince below were pointed at
    # base names that don't exist in ACORD_127_schema.json (the real fields are
    # *Identifier/*Code) and so silently never stamped; fixed to the real names.
    "Driver_FullName":                    _ScheduleDef("auto_drivers", "name"),
    "Driver_GivenName":                   _ScheduleDef("auto_drivers", "_name_given"),
    "Driver_Surname":                     _ScheduleDef("auto_drivers", "_name_surname"),
    "Driver_BirthDate":                   _ScheduleDef("auto_drivers", "dob"),
    "Driver_LicenseNumberIdentifier":     _ScheduleDef("auto_drivers", "license_number"),
    "Driver_LicensedStateOrProvinceCode": _ScheduleDef("auto_drivers", "license_state"),
    "Driver_HiredDate":                   _ScheduleDef("auto_drivers", "hire_date"),
    "Driver_ExperienceYearCount":         _ScheduleDef("auto_drivers", "experience_years"),
    "Driver_Vehicle_UsePercent":          _ScheduleDef("auto_drivers", "vehicle_use_percent"),

    # ── WC Class Codes (ACORD 130) ──────────────────────────────────────────
    "WorkersCompensation_ClassCode":        _ScheduleDef("wc_class_codes", "code"),
    "WorkersCompensation_ClassDescription": _ScheduleDef("wc_class_codes", "description"),
    "WorkersCompensation_ClassPayroll":     _ScheduleDef("wc_class_codes", "payroll"),
    "WorkersCompensation_ClassState":       _ScheduleDef("wc_class_codes", "state"),
    "WorkersCompensation_ClassRate":        _ScheduleDef("wc_class_codes", "rate"),

    # ── WC Officers / Owners (ACORD 130) ───────────────────────────────────
    "Officer_FullName":              _ScheduleDef("wc_officers", "name"),
    "Officer_Title":                 _ScheduleDef("wc_officers", "title"),
    "Officer_OwnershipPercent":      _ScheduleDef("wc_officers", "ownership_pct"),
    "Officer_IncludeIndicator":      _ScheduleDef("wc_officers", "include"),
    "Officer_ExcludeIndicator":      _ScheduleDef("wc_officers", "exclude"),
    "Owner_FullName":                _ScheduleDef("wc_officers", "name"),
    "Owner_Title":                   _ScheduleDef("wc_officers", "title"),
    "Owner_OwnershipPercent":        _ScheduleDef("wc_officers", "ownership_pct"),

    # ── Additional Named Insureds (ACORD 125) ────────────────────────────────
    # row_offset=1: _A is the primary insured scalar, _B onward are additional
    "AdditionalInsured_FullName":    _ScheduleDef("additional_named_insureds", None),
    # ACORD 125's OTHER-named-insured name boxes are NamedInsured_FullName_B/_C
    # (row A is the primary applicant, resolved by the scalar rule via the
    # row_offset guard). Graded test run: a second named insured stated plainly
    # in the document never reached the form — no binding existed and the
    # gap-fill model missed it. Bound to the extraction fact so a captured
    # second insured stamps deterministically.
    "NamedInsured_FullName":         _ScheduleDef("additional_named_insureds", None, row_offset=1),

    # ── Underlying Policies (ACORD 131) ─────────────────────────────────────
    "UnderlyingPolicy_TypeOfInsurance":  _ScheduleDef("underlying_policies", "line"),
    "UnderlyingPolicy_Line":             _ScheduleDef("underlying_policies", "line"),
    "UnderlyingPolicy_LimitAmount":      _ScheduleDef("underlying_policies", "limit"),
    "UnderlyingPolicy_Limit":            _ScheduleDef("underlying_policies", "limit"),
    "UnderlyingPolicy_InsuranceCarrier": _ScheduleDef("underlying_policies", "carrier"),
    "UnderlyingPolicy_Carrier":          _ScheduleDef("underlying_policies", "carrier"),
    "UnderlyingPolicy_PolicyNumber":     _ScheduleDef("underlying_policies", "policy_no"),

    # ── Loss History (ACORD 125) ─────────────────────────────────────────────
    "LossHistory_OccurrenceDate":             _ScheduleDef("loss_history", "date"),
    "LossHistory_ClaimDate":                  _ScheduleDef("loss_history", "claim_date"),
    "LossHistory_LossDescription":            _ScheduleDef("loss_history", "description"),
    "LossHistory_Description":                _ScheduleDef("loss_history", "description"),
    "LossHistory_OccurrenceDescription":      _ScheduleDef("loss_history", "description"),
    "LossHistory_TotalIncurred":              _ScheduleDef("loss_history", "amount"),
    "LossHistory_AmountPaid":                 _ScheduleDef("loss_history", "paid"),
    "LossHistory_PaidAmount":                 _ScheduleDef("loss_history", "paid"),
    "LossHistory_ReservedAmount":             _ScheduleDef("loss_history", "reserved_amount"),
    "LossHistory_ClaimNumber":                _ScheduleDef("loss_history", "claim_number"),
    "LossHistory_LineOfBusiness":             _ScheduleDef("loss_history", "line_of_business"),
    "LossHistory_OpenIndicator":              _ScheduleDef("loss_history", "open"),
    "LossHistory_ClaimStatus_OpenCode":       _ScheduleDef("loss_history", "open_code"),
    "LossHistory_ClaimStatus_SubrogationCode":_ScheduleDef("loss_history", "subrogation_code"),

    # ── Prior Coverage by Line ───────────────────────────────────────────────
    # DEAD ENTRIES - kept only so nobody "restores" them. Verified 2026-08-09
    # against all 17 schemas: these six base names match ZERO real fields, so
    # this schedule has never stamped anything. The real grid is 2-D
    # (line x term) - `PriorCoverage_GeneralLiability_PolicyNumberIdentifier_A`
    # and friends - which a row-indexed _ScheduleDef cannot address at all.
    # `_resolve_prior_coverage_cell` owns it now. Do not wire per-line prior
    # coverage through here.
    "PriorCoverage_TypeOfInsurance": _ScheduleDef("prior_coverage_by_line", "line"),
    "PriorCoverage_InsuranceCarrier":_ScheduleDef("prior_coverage_by_line", "carrier"),
    "PriorCoverage_PolicyNumber":    _ScheduleDef("prior_coverage_by_line", "policy_no"),
    "PriorCoverage_EffectiveDate":   _ScheduleDef("prior_coverage_by_line", "effective"),
    "PriorCoverage_ExpirationDate":  _ScheduleDef("prior_coverage_by_line", "expiration"),
    "PriorCoverage_Premium":         _ScheduleDef("prior_coverage_by_line", "premium"),

    # ── Property Locations (ACORD 140) ──────────────────────────────────────
    "PropertyLocation_StreetAddress":    _ScheduleDef("property_locations", "address"),
    "PropertyLocation_BuildingValue":    _ScheduleDef("property_locations", "building_value"),
    "PropertyLocation_BPPValue":         _ScheduleDef("property_locations", "bpp_value"),
    "PropertyLocation_ConstructionType": _ScheduleDef("property_locations", "construction_type"),
    "PropertyLocation_YearBuilt":        _ScheduleDef("property_locations", "year_built"),

    # ── Premises / Location Schedule (Beta Report Figure 27) ─────────────────
    # These are ACORD's own shared field concepts — the SAME base field names
    # (CommercialStructure_*/BusinessInformation_*/BuildingOccupancy_*) appear
    # on ACORD 125, 131, 140, 160 and 186 to mean the same thing: "location A's
    # / B's / ... address, ownership, and occupancy detail." Registering them
    # once here (mirroring the LossHistory_*/PriorCoverage_* pattern above)
    # binds every one of those forms' A/B/C/D premises rows to the SAME
    # canonical, deduplicated `property_locations` list instead of each row
    # falling through to an ungrounded per-field GPT guess.
    # "LOC #" - tooltip: "The location number for the premises." Was already
    # in the required-field set (pre-existing) but never had a data source,
    # so it stayed blank/yellow on every row. Sourced from the consolidated
    # list's own position, matching the row it's actually stamped into.
    "CommercialStructure_Location_ProducerIdentifier":        _ScheduleDef("property_locations", "location_number"),
    "CommercialStructure_PhysicalAddress_LineOne":            _ScheduleDef("property_locations", "address_line1"),
    # Line-two was NOT bound, so it fell to gap fill, which re-wrote the unit
    # number already present at the end of line1 ("# D13" printed twice on the
    # client's live form). Bound to the parsed line2: a real suite (4-part
    # address) still stamps; an address with no separate line2 leaves the box
    # an authoritative blank instead of an LLM guess.
    "CommercialStructure_PhysicalAddress_LineTwo":            _ScheduleDef("property_locations", "address_line2"),
    "CommercialStructure_PhysicalAddress_CityName":           _ScheduleDef("property_locations", "address_city"),
    # County was the ONE premises column with no binding, so it alone kept
    # reaching the model as a distinct-values group — three live runs filled
    # empty rows' county cells with address fragments ("Denve", "4800 D").
    # Bound to the per-location county captured at extraction; a location
    # without a stated county leaves the box an owned blank.
    "CommercialStructure_PhysicalAddress_CountyName":         _ScheduleDef("property_locations", "address_county"),
    "CommercialStructure_PhysicalAddress_StateOrProvinceCode":_ScheduleDef("property_locations", "address_state"),
    "CommercialStructure_PhysicalAddress_PostalCode":         _ScheduleDef("property_locations", "address_zip"),
    "CommercialStructure_RiskLocation_InsideCityLimitsIndicator":  _ScheduleDef("property_locations", "is_inside_city_limits"),
    "CommercialStructure_RiskLocation_OutsideCityLimitsIndicator": _ScheduleDef("property_locations", "is_outside_city_limits"),
    # The CITY LIMITS "Other" box (ACORD's own tooltip: "neither inside nor
    # outside city limits, e.g. unincorporated"). It had no binding, so it
    # rode gap fill and a live run ticked it with the insured's STREET
    # ADDRESS as its description. Bound to sub-keys the consolidation never
    # sets, so the pair is an owned blank unless a future derivation fills
    # them - a Denver street address is inside city limits, never "other".
    "CommercialStructure_RiskLocation_OtherIndicator":             _ScheduleDef("property_locations", "is_other_city_limits"),
    "CommercialStructure_RiskLocation_OtherDescription":           _ScheduleDef("property_locations", "other_city_limits_description"),
    "CommercialStructure_InsuredInterest_OwnerIndicator":     _ScheduleDef("property_locations", "is_owner"),
    "CommercialStructure_InsuredInterest_TenantIndicator":    _ScheduleDef("property_locations", "is_tenant"),
    "CommercialStructure_AnnualRevenueAmount":                _ScheduleDef("property_locations", "annual_revenue"),
    "BusinessInformation_FullTimeEmployeeCount":              _ScheduleDef("property_locations", "full_time_employees"),
    "BusinessInformation_PartTimeEmployeeCount":              _ScheduleDef("property_locations", "part_time_employees"),
    "BuildingOccupancy_OccupiedArea":                         _ScheduleDef("property_locations", "occupied_area"),
    "BuildingOccupancy_OpenToPublicArea":                     _ScheduleDef("property_locations", "open_to_public_area"),
    "BuildingOccupancy_OperationsDescription":                _ScheduleDef("property_locations", "operations_description"),
    # "Total Building Area" (whole building's sq ft) - a DISTINCT field from
    # occupied_area (the space the insured occupies). Missed on the first
    # pass; caught during manual re-verification because it was left
    # unregistered, fell to ungated GPT gap-fill, and got silently filled
    # with a copy of occupied_area instead of staying blank.
    "Construction_BuildingArea":                              _ScheduleDef("property_locations", "total_building_area"),
    # Owner/Tenant/Other are mutually exclusive. Registering "Other" too
    # (sourced from the SAME deterministic ownership derivation as Owner/
    # Tenant) stops it from being independently, ungated-ly re-guessed by
    # GPT and contradicting an already-resolved Owner/Tenant answer.
    "CommercialStructure_InsuredInterest_OtherIndicator":     _ScheduleDef("property_locations", "is_other_interest"),
    "CommercialStructure_InsuredInterest_OtherDescription":   _ScheduleDef("property_locations", "other_interest_description"),

    # ── GL Class Codes (ACORD 126 schedule of hazards) ───────────────────────
    # NOTE: the real ACORD 126 field names are `GeneralLiability_Hazard_*_A/_B/_C`
    # (see ACORD_126_schema.json). The former "GL_ClassCode" / "GL_Location" keys
    # matched no real field and were dead. Structured filling now lives in
    # `_resolve_gl_hazard_row`, which is checked at the top of `_deterministic_map`
    # so an absent schedule falls through to gap-fill instead of being blanked.

    # ── Inland Marine Items (ACORD 160) ─────────────────────────────────────
    "InlandMarine_ItemDescription":  _ScheduleDef("inland_marine_items", "description"),
    "InlandMarine_ItemValue":        _ScheduleDef("inland_marine_items", "value"),
    "InlandMarine_SerialNumber":     _ScheduleDef("inland_marine_items", "serial_number"),
}

_SCHED_ROW_RE = re.compile(r"^(.+)_([A-N])$")


def repeating_group_key(field_name: str, tooltip: Optional[str]):
    """Repeating-group identity for a gap-fill slot field: ``(base, tooltip)``.

    Two ``_A/_B/...`` siblings belong to the SAME repeating group only when they
    share BOTH the base name AND the tooltip. ACORD reuses one base for genuinely
    DIFFERENT roles distinguished only by the "As used here..." tooltip note - on
    ACORD 127, ``AdditionalInterest_FullName_A/B`` are the additional-interest
    (lienholder) schedule while ``_C/_D`` are "the name of the other owner of the
    vehicle". Keying on the base alone merged all four into one ordinal
    "find N distinct values" block, so the gap-fill LLM filled the first role and
    left the owner boxes (_C/_D) empty. Splitting by tooltip gives each role its
    own block. Returns ``None`` when the field has no row suffix (not a slot).
    Module-level + pure so the grouping is unit-testable against the real schemas.
    """
    m = _SCHED_ROW_RE.match(field_name or "")
    if not m:
        return None
    return (m.group(1), (tooltip or "").strip())


# Sentinel sub_keys handled specially by _resolve_schedule_row: the "name"
# sub-key holds one full-name string per driver, but ACORD 127 splits that
# into separate GivenName/Surname boxes. Last whitespace token = surname;
# everything before it = given name. A single-token name has no surname.
_NAME_GIVEN_KEY = "_name_given"
_NAME_SURNAME_KEY = "_name_surname"


def _split_driver_name(full: Optional[str]):
    if not full or not str(full).strip():
        return None, None
    parts = str(full).strip().split()
    if len(parts) == 1:
        return parts[0], None
    return " ".join(parts[:-1]), parts[-1]


# Vehicle-schedule columns that hold a covered-auto symbol. A declarations page
# normally prints ONE symbol per coverage line that applies to every scheduled
# vehicle ("Comprehensive 07"), and only rarely varies it per row - so an empty
# row cell inherits the policy-level symbol rather than falling through to a
# gap-fill guess. Inheritance is the documented carrier convention, not an
# inference: symbol 7 means "the autos specifically described in the
# declarations", i.e. all of them.
_VEHICLE_SYMBOL_SUBKEYS = frozenset({"comp_symbol", "coll_symbol", "symbol"})

# Which coverage lines each column may draw its policy-level symbol from, in
# priority order.
_VEHICLE_SYMBOL_COVERAGES: Dict[str, tuple] = {
    "comp_symbol": ("comprehensive", "physical_damage"),
    "coll_symbol": ("collision", "physical_damage"),
    "symbol":      ("physical_damage", "comprehensive", "collision"),
}


def _policy_level_vehicle_symbol(sub_key: str, facts: dict) -> Optional[str]:
    """The policy-level covered-auto symbol for this column, or None.

    Returns a value ONLY when exactly one symbol is designated for the relevant
    coverage. Two competing numbers means the schedule genuinely varies by row
    and we must not pick one - blank, and let the producer supply it.
    """
    try:
        from services import auto_symbols as _sym
    except Exception:            # pragma: no cover - import-failure fallback
        return None
    nums = _sym.symbols_for(facts, *_VEHICLE_SYMBOL_COVERAGES.get(sub_key, ()))
    return str(nums[0]) if len(nums) == 1 else None


def _resolve_schedule_row(field_name: str, facts: dict):
    """Resolve a repeating-row field (e.g. Vehicle_Year_B) to its list-indexed value.

    Returns _SCHED_SKIP  — not a schedule field; caller falls through to regular rules.
    Returns None         — schedule field but list is shorter than row index (leave blank).
    Returns str          — resolved value for this row.
    """
    m = _SCHED_ROW_RE.match(field_name)
    if not m:
        return _SCHED_SKIP

    base   = m.group(1)
    letter = m.group(2)
    idx    = _ROW_LETTER_TO_IDX[letter]

    # Exact base match first, then longest-prefix match in registry
    defn = _SCHEDULE_REGISTRY.get(base)
    if defn is None:
        for prefix, d in _SCHEDULE_REGISTRY.items():
            if base == prefix or base.startswith(prefix + "_") or base.endswith("_" + prefix):
                defn = d
                break

    if defn is None:
        return _SCHED_SKIP

    list_idx = idx - defn.row_offset
    if list_idx < 0:
        return _SCHED_SKIP  # this letter belongs to scalar rules (row_offset guard)

    items = _fv(facts, defn.list_key)
    # ── A NAME-ONLY RECORD IS NOT A SCHEDULE ROW ─────────────────────────────
    # Run 9 printed a DRIVER row on the ACORD 127 - "Erin R Royal, Denver CO
    # 80216-3121" - for a package the ground truth says has no driver schedule
    # at all. ERIN ROYAL is the named individual on a CA 99 10 DRIVE OTHER CAR
    # endorsement (page 92), the only personal name in 180 pages.
    #
    # `_schedule_has_substance` ALREADY ruled this record "not a schedule" and
    # logged it - the attachment box and the evidence gate both honour that -
    # but the row resolver never asked, so the name stamped anyway and dragged
    # the APPLICANT'S address in beside it. A DRIVER row carrying nothing but a
    # name asserts that a driver exists and that we know who they are; we know
    # neither, and every rating column the form prints beside the name (licence,
    # DOB, years experience, hire date) is empty.
    #
    # SCOPED TO DRIVERS, and the test suite is why: a name-only ADDITIONAL
    # NAMED INSURED or additional interest is a SUPPORTED shape - the record
    # legitimately IS just a name - and blanking those was tried, broke five
    # tests, and was reverted once already. Do not widen this without checking
    # `test_form_fill_ownership_20260810_runf` first.
    if defn.list_key in _NAME_ONLY_INVALID_SCHEDULES and isinstance(items, list) \
            and items and not _schedule_has_substance(defn.list_key, items):
        return None
    if not isinstance(items, list) or list_idx >= len(items):
        logger.debug(
            f"schedule_row: field={field_name!r} list={defn.list_key!r} "
            f"idx={list_idx} list_len={len(items) if isinstance(items, list) else 0} — blank"
        )
        return None  # list shorter than requested row → leave blank

    item = items[list_idx]
    if defn.sub_key is None:
        return str(item) if item is not None else None
    if isinstance(item, dict):
        if defn.sub_key in (_NAME_GIVEN_KEY, _NAME_SURNAME_KEY):
            given, surname = _split_driver_name(item.get("name"))
            val = given if defn.sub_key == _NAME_GIVEN_KEY else surname
        else:
            val = item.get(defn.sub_key)
        if val in (None, "") and defn.sub_key in _VEHICLE_SYMBOL_SUBKEYS:
            val = _policy_level_vehicle_symbol(defn.sub_key, facts)
        if isinstance(val, bool):
            return "Yes" if val else "No"
        return str(val) if val is not None else None
    if defn.sub_key in _VEHICLE_SYMBOL_SUBKEYS:
        return _policy_level_vehicle_symbol(defn.sub_key, facts)
    return str(item) if item is not None else None


@lru_cache(maxsize=1)
def _schedule_family_list_keys() -> Dict[str, str]:
    """{leading name segment -> fact list key} for every UNAMBIGUOUS schedule
    family in the registry. A segment is dropped when its registered bases
    disagree on the list key (Vehicle: auto_vin_schedule vs
    auto_garaging_addresses) or use a row offset (AdditionalInsured: row B is
    item 0), because the plain idx-vs-len test below would be wrong there."""
    fams: Dict[str, set] = {}
    offsets: Dict[str, set] = {}
    for base, defn in _SCHEDULE_REGISTRY.items():
        seg = base.split("_", 1)[0]
        fams.setdefault(seg, set()).add(defn.list_key)
        offsets.setdefault(seg, set()).add(defn.row_offset)
    return {
        seg: next(iter(keys))
        for seg, keys in fams.items()
        if len(keys) == 1 and offsets[seg] == {0}
    }


def _resolve_schedule_family_row(field_name: str, facts: dict):
    """Rows beyond the KNOWN length of a schedule are blank for the WHOLE
    field family, not just the schedule-bound columns.

    Why: on ACORD 125's premises block every column is bound to
    `property_locations` EXCEPT CountyName — so with one real location, rows
    B-D of every bound column were authoritative blanks while County_B/C/D
    still went to the model as a "find 4 distinct values" group. Three live
    runs filled them with address fragments ("Denve", "4800 D") — the SAME
    symptom the client first reported as broken ZIP cells, which were shape-
    guarded, moving the garbage to the one unguarded column. The row COUNT is
    schedule knowledge, and it governs every column of the family.

    Conservative in both directions: an empty/missing list means the count is
    UNKNOWN (extraction may simply have missed the schedule) and the resolver
    steps aside; a row within the known count also steps aside so bound
    columns resolve their values and unbound row-A columns keep LLM coverage."""
    m = _SCHED_ROW_RE.match(field_name)
    if not m:
        return _SCHED_SKIP
    seg = m.group(1).split("_", 1)[0]
    list_key = _schedule_family_list_keys().get(seg)
    if not list_key:
        return _SCHED_SKIP
    items = _fv(facts, list_key)
    if not isinstance(items, list) or not items:
        return _SCHED_SKIP                 # unknown row count — keep coverage
    if _ROW_LETTER_TO_IDX[m.group(2)] < len(items):
        return _SCHED_SKIP                 # a real row — normal paths resolve it
    return None                            # beyond the schedule: owned blank


def _is_schedule_field(field_name: str) -> bool:
    """Return True if this field belongs to _resolve_schedule_row() — not GPT.

    Reuses the exact same detection logic as Pass 1 so the two stays in sync.
    With empty facts the schedule resolver returns _SCHED_SKIP (not a schedule
    field) or None (out-of-range row) — either way, _SCHED_SKIP means GPT-eligible.
    """
    result = _resolve_schedule_row(field_name, {})
    return result is not _SCHED_SKIP


# `valuation_method` is normalized to "RCV"/"ACV" at extraction time (the
# common industry shorthand), but the real ACORD 140/141 ValuationCode
# field's own tooltip documents a single-letter code convention (A/R/V/M).
# See the call site (_deterministic_map) for the full story.
_VALUATION_METHOD_TO_ACORD_CODE = {"rcv": "R", "acv": "A"}

_ACORD_FIELD_RULES = [
    # ── Producer ────────────────────────────────────────────────────────────
    ("Producer_FullName",                                  "producer_name"),
    ("Producer_CustomerIdentifier",                        None),            # agency-assigned account ID — not in extraction schema; must not receive producer_name
    # These read the PRODUCER-scoped facts, not `contact_*`. `contact_*` is the
    # APPLICANT's contact person - that is what `fact_registry` asks for ("the best
    # phone number to reach YOU") and what `arq_service` puts to the insured. Until
    # 2026-08-09 all three pointed at `contact_*`, so ONE phone/email/name was
    # stamped onto the Producer block AND the Named Insured block of every form:
    # the client-reported "mixture of client and carrier information". If the
    # producer fact is absent the field falls through to gap fill, which reads the
    # correctly-labelled value out of the producer's own block - the same reasoning
    # the `_addr_*` guard below already uses.
    ("Producer_ContactPerson_FullName",                    "producer_contact_name"),
    ("Producer_ContactPerson_Phone",                       "producer_contact_phone"),
    ("Producer_ContactPerson_Email",                       "producer_contact_email"),
    ("Producer_MailingAddress_LineOne",                    "_addr_line1"),
    ("Producer_MailingAddress_LineTwo",                    "_addr_line2"),
    ("Producer_MailingAddress_CityName",                   "_addr_city"),
    ("Producer_MailingAddress_StateOrProv",                "_addr_state"),
    ("Producer_MailingAddress_PostalCode",                 "_addr_zip"),
    # A fax is only a fax if the document labels it one. Previously unmapped, which
    # left it to gap fill, which copied the producer's PHONE into it (client #1).
    ("Producer_FaxNumber",                                 "producer_fax"),
    ("Producer_AuthorizedRepresentative",                  "producer_contact_name"),

    # ── Named insured ───────────────────────────────────────────────────────
    ("NamedInsured_FullName",                              "applicant_name"),
    ("NamedInsured_DBAName",                               "dba_name"),
    ("NamedInsured_TradeName",                             "dba_name"),
    ("NamedInsured_FEIN",                                  "fein"),
    ("NamedInsured_TaxIdentifier",                         "fein"),
    # The APPLICANT's website. Present on ACORD 125 (rows A-C) and 130. Without
    # this rule the fact existed, the questionnaire asked for it, and the answer
    # had nowhere to land - `_canonical_key` resolves through _ACORD_FIELD_RULES,
    # so an unmapped box can never receive a client-confirmed value. Found by
    # test_the_repointed_box_reads_its_new_fact on its first run.
    ("NamedInsured_Primary_WebsiteAddress",                "applicant_website"),
    ("NamedInsured_EntityType",                            "entity_type"),
    ("NamedInsured_BusinessEntity",                        "entity_type"),
    ("NamedInsured_YearsInBusiness",                       "years_in_business"),
    ("NamedInsured_BusinessDescription",                   "operations_description"),
    ("NamedInsured_OperationsDescription",                 "operations_description"),
    ("NamedInsured_SICCode",                               "sic_code"),
    ("NamedInsured_NAICSCode",                             "naics_code"),
    ("NamedInsured_MailingAddress_LineOne",                "_addr_line1"),
    ("NamedInsured_MailingAddress_LineTwo",                "_addr_line2"),
    ("NamedInsured_MailingAddress_CityName",               "_addr_city"),
    ("NamedInsured_MailingAddress_StateOrProv",            "_addr_state"),
    ("NamedInsured_MailingAddress_PostalCode",             "_addr_zip"),
    ("NamedInsured_PhysicalAddress_LineOne",               "_loc_line1"),
    ("NamedInsured_PhysicalAddress_LineTwo",               "_loc_line2"),
    ("NamedInsured_PhysicalAddress_CityName",              "_loc_city"),
    ("NamedInsured_PhysicalAddress_StateOrProv",           "_loc_state"),
    ("NamedInsured_PhysicalAddress_PostalCode",            "_loc_zip"),
    ("NamedInsured_PhoneNumber",                           "contact_phone"),
    ("NamedInsured_Primary_PhoneNumber",                   "contact_phone"),
    ("NamedInsured_EmailAddress",                          "contact_email"),
    ("NamedInsured_WebsiteAddress",                        None),   # not in extraction schema
    # A DATE field ("Enter date: The date the applicant began in business"), so it
    # takes the date fact - not `years_in_business`, whose own registry validator is
    # "positive integer <= 500". A duration was being written into a date box, and on
    # ACORD 125 that was the ONLY field `years_in_business` reached (the form has no
    # NamedInsured_YearsInBusiness box), so the duration had nowhere correct to land.
    ("NamedInsured_BusinessStartDate",                     "business_start_date"),
    # Named insured contact sub-fields (ACORD 125 contact section)
    ("NamedInsured_Contact_FullName",                      "contact_name"),
    ("NamedInsured_Contact_PrimaryPhoneNumber",            "contact_phone"),
    ("NamedInsured_Contact_PrimaryEmailAddress",           "contact_email"),
    ("NamedInsured_NumberOfEmployees",                     "num_employees"),
    ("NamedInsured_AnnualRevenue",                         "total_revenue"),
    ("NamedInsured_AnnualPayroll",                         "total_payroll"),

    # The additional-interest NAME box, seeded from the loss-payee fact when
    # extraction captured one. Graded test run: the gap-fill model assembled
    # the interest row from TWO different entities (the 2nd insured's name
    # over the lender's address). A deterministic anchor keeps the row's
    # identity fixed; when no loss payee is stated the rule resolves empty and
    # gap fill proceeds as before. Known limitation: row A carries the loss
    # payee when both a loss payee and a mortgagee exist — ACORD 45 handles
    # additional interests beyond row A.
    ("AdditionalInterest_FullName",                        "loss_payee_name"),

    # ── Prior / previous coverage — MUST map to prior_* keys, NOT current policy keys ──
    ("PriorCarrier_FullName",                              "prior_carrier"),
    ("PriorCoverage_InsuranceCarrierName",                 "prior_carrier"),
    ("PriorCoverage_PolicyNumberIdentifier",               "prior_policy_number"),
    ("PriorCoverage_EffectiveDate",                        "prior_effective_date"),
    ("PriorCoverage_ExpirationDate",                       "prior_expiration_date"),
    ("PriorCoverage_NAICCode",                             "prior_carrier_naic"),
    ("PreviousCarrier_FullName",                           "prior_carrier"),
    ("PreviousPolicy_PolicyNumber",                        "prior_policy_number"),
    ("PreviousPolicy_EffectiveDate",                       "prior_effective_date"),
    ("PreviousPolicy_ExpirationDate",                      "prior_expiration_date"),
    # Per-line prior coverage rows (ACORD 125 prior coverage section).
    #
    # DELETED 2026-08-09. These sixteen rows mapped FOUR scalars onto SIXTEEN
    # boxes: one `prior_policy_number` filled the General Liability, Automobile,
    # Property AND Other columns at once, and prior_carrier /
    # prior_effective_date / prior_expiration_date did the same. The client
    # reported the output verbatim - "BBC7263 under GL, Property and Other ...
    # Do not put GL or Auto numbers in the Property column."
    #
    # A single scalar cannot say WHICH line a policy covered, which is the whole
    # point of that grid. `_resolve_prior_coverage_cell` now owns every one of
    # these cells and reads the per-line `prior_coverage_by_line` fact, filling
    # the carrier and premium columns no scalar ever reached. It runs FIRST in
    # `_deterministic_map` and returns None for an owned-but-empty cell, so
    # nothing can fall back through to a scalar. Do not re-add rows here.

    # ── Business information ─────────────────────────────────────────────────
    ("BusinessInformation_NAICSCode",                      "naics_code"),
    ("BusinessInformation_SICCode",                        "sic_code"),
    ("BusinessInformation_YearsInBusiness",                "years_in_business"),
    ("BusinessInformation_NumberOfEmployees",              "num_employees"),
    # Prefer the real full-time figure; fall back to the overall total via
    # _FACT_FALLBACKS. The fallback is deliberate and must stay: a client answered
    # "How many people does your business employ?" and the PDF box did not change,
    # which is what test_employee_count_falls_back_to_the_scalar_total... locks in.
    ("BusinessInformation_FullTimeEmployeeCount",          "num_employees_full_time"),
    # NO fallback to the total here. Writing the total into BOTH the full-time and
    # the part-time box stamps one number twice, which is only correct when one of
    # them is zero - and the client reported exactly that ("0 full time, 0 part
    # time ... not supported by the policy"). Identical reasoning to
    # Contractors_PartTimeEmployeeCount further down, which was fixed and never
    # generalised to here. Blank beats repeating the full-time number.
    ("BusinessInformation_PartTimeEmployeeCount",          "num_employees_part_time"),
    ("BusinessInformation_AnnualRevenue",                  "total_revenue"),
    ("CommercialPolicy_OperationsDescription",             "operations_description"),
    ("CommercialPolicy_AuditPeriod",                       "audit_period"),
    ("CommercialPolicy_BillingPlan",                       "billing_plan"),
    ("Policy_AuditPeriod",                                 "audit_period"),
    ("Policy_BillingPlan",                                 "billing_plan"),
    # METHOD OF PAYMENT is the billing method in prose - "DIRECT BILL" is a
    # complete, correct method description. Unmapped, this box fell to gap
    # fill, which stamped the umbrella's audit note into it (live 2026-08-14:
    # "PREMIUM NOT SUBJECT TO AUDIT" as a method of payment). Pass 1 filling
    # it from the fact takes the box off the model's plate entirely.
    ("Policy_PaymentMethod_MethodDescription",             "billing_plan"),

    # ── Policy / form header ─────────────────────────────────────────────────
    ("Policy_PolicyNumberIdentifier",                      "policy_number"),
    ("Policy_EffectiveDate",                               "effective_date"),
    ("Policy_ExpirationDate",                              "expiration_date"),
    # Most-specific FIRST: UnderlyingPolicy_GeneralLiability_PolicyNumberIdentifier
    # (ACORD 131's underlying-schedule GL row - tooltip: "The policy number of
    # the underlying general liability policy") is a substring match for the
    # generic Policy_GeneralLiability_PolicyNumberIdentifier rule right below,
    # which silently stamped the UMBRELLA'S OWN policy number into the
    # underlying GL row on a real ACORD 131 (confirmed live). No per-line
    # underlying-GL-policy-number fact exists in this codebase, so this maps
    # to None -> gap-fill, which already correctly reads the real underlying
    # GL policy number from raw text (same mechanism already proven for
    # UnderlyingPolicy_GeneralLiability_PolicyEffectiveDate_A).
    ("UnderlyingPolicy_GeneralLiability_PolicyNumberIdentifier", None),
    ("Policy_GeneralLiability_PolicyNumberIdentifier",     "policy_number"),
    ("Policy_GeneralLiability_EffectiveDate",              "effective_date"),
    ("Policy_GeneralLiability_ExpirationDate",             "expiration_date"),
    ("Policy_AutomobileLiability_PolicyNumberIdentifier",  "policy_number"),
    ("Policy_AutomobileLiability_EffectiveDate",           "effective_date"),
    ("Policy_AutomobileLiability_ExpirationDate",          "expiration_date"),
    # ACORD 25's certificate header has no per-line "excess policy number"
    # fact - only the generic policy_number (the GL/primary row's own
    # number, per every other rule in this block). Stamping that same number
    # onto the Excess row silently duplicated the GL policy number there on a
    # real certificate (confirmed live: same 'GL-4471029-25' on both rows).
    # Maps to None -> gap-fill, which already correctly distinguishes the
    # excess/umbrella coverage line's own values from the GL row's elsewhere
    # on this exact form (see Policy_ExcessLiability_EffectiveDate_A's
    # dedicated override above, and the underlying-schedule rows on 131).
    ("Policy_ExcessLiability_PolicyNumberIdentifier",      None),
    ("Policy_ExcessLiability_EffectiveDate",               "effective_date"),
    ("Policy_ExcessLiability_ExpirationDate",              "expiration_date"),
    # NOT a bare "Policy_WorkersCompensation" prefix: that substring also
    # matched Policy_WorkersCompensationAndEmployersLiability_EffectiveDate_A /
    # _ExpirationDate_A (ACORD 25), silently stamping the GL policy NUMBER
    # STRING into both WC DATE fields on the real certificate (confirmed live -
    # "GL-4471029-25" printed where a date belongs). The exact, fully-qualified
    # name below matches ONLY the real policy-number field; the WC date fields
    # now correctly fall through to UNMATCHED -> gap-fill, which already reads
    # them correctly from raw text (same mechanism proven for the underlying
    # GL/Auto/EL dates on ACORD 131 - see UnderlyingPolicy_*_PolicyEffectiveDate).
    ("Policy_WorkersCompensationAndEmployersLiability_PolicyNumberIdentifier", "policy_number"),
    ("OtherPolicy_PolicyNumberIdentifier",                 "policy_number"),
    ("OtherPolicy_PolicyEffectiveDate",                    "effective_date"),
    ("OtherPolicy_PolicyExpirationDate",                   "expiration_date"),
    # The date the APPLICATION is completed — that is the day WE generate the
    # form, not the policy's effective date. The old mapping to effective_date
    # made every application look like it was written on inception day
    # (client issue #2, verbatim: "The application date appears copied from
    # the policy effective date").
    ("Form_CompletionDate",                                "_today_date"),
    ("Form_EditionIdentifier",                             None),
    ("CertificateOfInsurance_CertificateNumberIdentifier", "policy_number"),
    ("CertificateOfInsurance_RevisionNumber",              None),

    # ── Insurer ──────────────────────────────────────────────────────────────
    ("Insurer_FullName",                                   "carrier_name"),
    ("Insurer_NAICCode",                                   "carrier_naic"),
    ("_InsurerLetterCode",                                 None),

    # ── General liability — most-specific rules FIRST to prevent prefix shadowing ──
    ("GeneralLiability_FireDamageRentedPremises_EachOccurrenceLimitAmount", "gl_fire_damage_limit"),
    ("GeneralLiability_ProductsAndCompletedOperations_AggregateLimitAmount", "gl_products_aggregate"),
    ("GeneralLiability_PersonalAndAdvertisingInjury_LimitAmount", "gl_personal_advertising_injury"),
    ("GeneralLiability_MedicalExpense_EachPersonLimitAmount",     "gl_medical_expense"),
    ("GeneralLiability_EachOccurrence_LimitAmount",        "gl_each_occurrence"),
    ("GeneralLiability_EachOccurrence",                    "gl_each_occurrence"),
    # NOTE: the bare "EachOccurrence" catch-all (for ACORD 160's
    # GeneralLiability_BodilyInjury_EachOccurrenceLimitAmount_A, which has no
    # more-specific rule) is placed AFTER the umbrella section below, not
    # here. Listed here it silently beat the umbrella section's own more-
    # specific ExcessUmbrella_Umbrella_EachOccurrenceAmount rule (200 lines
    # down) for any field containing "EachOccurrence" ANYWHERE in its name -
    # including the umbrella's own each-occurrence limit field, which
    # confirmed-live stamped the GL each-occurrence limit onto ACORD 131's
    # umbrella limit field instead of the umbrella's real, distinct amount.
    ("GeneralLiability_GeneralAggregate_LimitAmount",      "gl_aggregate"),
    ("GeneralLiability_GeneralAggregate",                  "gl_aggregate"),
    ("GeneralLiability_Aggregate",                         "gl_aggregate"),
    ("GeneralAggregate",                                   "gl_aggregate"),
    ("GeneralLiability_OtherCoverageLimitAmount",          "gl_deductible"),
    ("GeneralLiability_PropertyDamage_DeductibleAmount",   "gl_deductible"),
    ("GeneralLiability_BodilyInjury_DeductibleAmount",     "gl_deductible"),
    ("GeneralLiability_OtherDeductibleAmount",             "gl_deductible"),
    ("GeneralLiability_ClaimsMadeIndicator",               "gl_form_type"),
    ("GeneralLiability_OccurrenceIndicator",               "gl_form_type"),
    ("GeneralLiability_ClaimsMade_ProposedRetroactiveDate","retro_date"),
    ("GeneralLiability_ClaimsMade_UninterruptedCoverageEntryDate", "retro_date"),
    ("GeneralLiability_RetroactiveDate",                   "retro_date"),
    ("GeneralLiability_EmployeeBenefits_EmployeeCount",    "num_employees"),
    # GL indicators / admin checkboxes → null
    ("GeneralLiability_CoverageIndicator",                 None),
    ("GeneralLiability_OwnersAndContractors",              None),
    ("GeneralLiability_OtherCoverageIndicator",            None),
    ("GeneralLiability_OtherCoverageDescription",          None),
    ("GeneralLiability_DeductiblePerClaim",                None),
    ("GeneralLiability_DeductiblePerOccurrence",           None),
    ("GeneralLiability_UninsuredUnderinsured",             None),
    ("GeneralLiability_MedicalPayments_Coverage",          None),
    ("GeneralLiabilityLineOfBusiness_Question_",           None),
    ("GeneralLiabilityLineOfBusiness_Attachment_",         None),
    ("GeneralLiabilityLineOfBusiness_Total",               None),
    ("GeneralLiabilityLineOfBusiness_RemarkText",          None),
    ("GeneralLiabilityLineOfBusiness_TypeOfWork",          None),
    ("GeneralLiability_Hazard_Location",                   None),
    ("GeneralLiability_Hazard_Hazard",                     None),
    ("GeneralLiability_Hazard_PremiumBasis",               None),
    ("GeneralLiability_Hazard_Territory",                  None),
    ("GeneralLiability_Hazard_PremisesOperationsRate",     None),
    ("GeneralLiability_Hazard_ProductsRate",               None),
    ("GeneralLiability_Hazard_PremisesOperationsPremium",  None),
    ("GeneralLiability_Hazard_ProductsPremium",            None),
    ("GeneralLiability_Hazard_Exposure",                   None),
    ("GeneralLiability_Hazard_ClassCode",                  None),
    ("GeneralLiability_Hazard_Classification",             None),
    ("GeneralLiability_PremisesOperations_Premium",        None),
    ("GeneralLiability_Products_Premium",                  None),
    ("GeneralLiability_OtherCoveragePremium",              None),
    ("GeneralLiability_PropertyDamage_DeductibleIndicator",None),
    ("GeneralLiability_BodilyInjury_DeductibleIndicator",  None),
    ("GeneralLiability_OtherDeductibleIndicator",          None),
    ("GeneralLiability_GeneralAggregate_LimitApplies",     None),
    ("GeneralLiability_UninsuredUnderinsuredMotorists",    None),
    ("GeneralLiability_EmployeeBenefits_PerClaim",         None),
    ("GeneralLiability_EmployeeBenefits_EmployeeCovered",  None),
    ("GeneralLiability_EmployeeBenefits_Retroactive",      None),
    ("GeneralLiability_EmployeeBenefits_LimitAmount",      None),
    ("GeneralLiability_Otherlodging",                      None),

    # ── Commercial property / structure ─────────────────────────────────────
    ("CommercialProperty_Premises_LimitAmount",            "property_building_value"),
    ("CommercialProperty_Premises_CoinsurancePercent",     "coinsurance_percentage"),
    ("CommercialProperty_Premises_ValuationCode",          "valuation_method"),
    ("CommercialProperty_Premises_DeductibleAmount",       "property_deductible_aop"),
    ("CommercialProperty_Premises_DeductibleTypeCode",     None),
    ("CommercialProperty_Premises_SubjectOfInsuranceCode", None),
    ("CommercialProperty_Premises_CauseOfLossCode",        None),
    ("CommercialProperty_Premises_InflationGuardPercent",  None),
    ("CommercialProperty_Premises_BlanketNumber",          None),
    ("CommercialProperty_Premises_FormsAndConditions",     None),
    ("CommercialProperty_Premises_RemarkText",             None),
    ("CommercialProperty_Premises_Breakdown",              None),
    ("CommercialProperty_Premises_PowerOutage",            None),
    ("CommercialProperty_Premises_SellingPrice",           None),
    ("CommercialProperty_Premises_OtherIndicator",         None),
    ("CommercialProperty_Premises_OptionsDescription",     None),
    ("CommercialProperty_Summary_BlanketNumber",           None),
    ("CommercialProperty_Summary_BlanketLimit",            None),
    ("CommercialCoverage_Summary_BlanketType",             None),
    ("CommercialProperty_Spoilage_",                       None),
    ("CommercialProperty_Attachment_",                     None),
    ("CommercialPropertyCoverage_SinkHole",                None),
    ("CommercialPropertyCoverage_MineSubsidence",          None),
    ("CommercialStructure_BuiltYear",                      "year_built"),
    ("CommercialStructure_YearBuilt",                      "year_built"),
    ("CommercialStructure_Roof_Year",                      "roof_year"),
    ("CommercialStructure_Construction_TypeCode",          "construction_type"),
    ("CommercialStructure_Occupancy",                      "occupancy_type"),
    ("CommercialStructure_PhysicalAddress_LineOne",        "_loc_line1"),
    ("CommercialStructure_PhysicalAddress_LineTwo",        "_loc_line2"),
    ("CommercialStructure_PhysicalAddress_CityName",       "_loc_city"),
    ("CommercialStructure_PhysicalAddress_StateOrProv",    "_loc_state"),
    ("CommercialStructure_PhysicalAddress_PostalCode",     "_loc_zip"),
    ("CommercialStructure_Location_ProducerIdentifier",    None),
    ("CommercialStructure_Building_ProducerIdentifier",    None),
    ("CommercialStructure_Building_Sublocation",           None),
    ("CommercialStructure_TaxCode",                        None),
    ("CommercialStructure_WindClass_",                     None),
    ("CommercialStructure_PrimaryHeat_",                   None),
    ("CommercialStructure_SecondaryHeat_",                 None),
    ("CommercialStructure_HeatingBoiler",                  None),
    ("Construction_ConstructionCode",                      "construction_type"),
    ("Construction_OpenSidesCount",                        None),
    ("Construction_StoreyCount",                           None),
    ("Construction_BasementCount",                         None),
    ("Construction_BuildingArea",                          None),
    ("Construction_BuildingCodeEffectiveness",             None),
    ("Construction_RoofMaterialCode",                      None),

    # ── Building features / protection ──────────────────────────────────────
    ("BuildingFireProtection_HydrantDistanceFeetCount",    "distance_to_hydrant"),
    ("BuildingFireProtection_FireStationDistanceMile",     None),
    ("BuildingFireProtection_FireDistrictName",            None),
    ("BuildingFireProtection_FireDistrictCode",            None),
    ("BuildingFireProtection_ProtectionClassCode",         "fire_protection_class"),
    ("BuildingFireProtection_Alarm_SprinklerPercent",      "sprinkler_system"),
    ("BuildingFireProtection_Alarm_ManufacturerName",      None),
    ("BuildingFireProtection_Alarm_CentralStation",        None),
    ("BuildingFireProtection_Alarm_LocalGong",             None),
    ("BuildingFireProtection_Alarm_ProtectionDescription", None),
    ("BuildingImprovement_WiringYear",                     None),
    ("BuildingImprovement_WiringIndicator",                None),
    ("BuildingImprovement_RoofingYear",                    "roof_year"),
    ("BuildingImprovement_RoofingIndicator",               None),
    ("BuildingImprovement_PlumbingYear",                   None),
    ("BuildingImprovement_PlumbingIndicator",              None),
    ("BuildingImprovement_HeatingYear",                    None),
    ("BuildingImprovement_HeatingIndicator",               None),
    ("BuildingImprovement_OtherYear",                      None),
    ("BuildingImprovement_OtherIndicator",                 None),
    ("BuildingImprovement_OtherDescription",               None),
    ("BuildingFeatures_HistoricalProperty",                None),
    ("BuildingFeatures_SolidFuel",                         None),
    ("BuildingOccupancy_OtherOccupancies",                 None),
    ("BuildingOccupancy_Apartment",                        None),
    # The per-location DESCRIPTION OF OPERATIONS box (ACORD 125 page 2). It is
    # schedule-backed (property_locations.operations_description), but the
    # extractor's location dicts rarely carry a per-location narrative, so the
    # box fell through to gap fill - which stamped the dec page's TRUNCATED
    # carrier shorthand "COMMERCIAL GENERAL CONTRA" (client PART 19 item 16:
    # "not a usable underwriting description"). Registering the FULL
    # `operations_description` fact here lets the existing row-A fallback in
    # `_deterministic_map` fill it deterministically; rows B+ stay
    # schedule-scoped exactly as before.
    ("BuildingOccupancy_OperationsDescription",            "operations_description"),
    ("BuildingExposure_",                                  None),
    ("BuildingSecurity_",                                  None),

    # ── Additional interest / mortgagee ──────────────────────────────────────
    ("AdditionalInterest_FullName",                        "additional_named_insureds"),
    ("AdditionalInterest_MailingAddress_LineOne",          "_addr_line1"),
    ("AdditionalInterest_MailingAddress_LineTwo",          "_addr_line2"),
    ("AdditionalInterest_MailingAddress_CityName",         "_addr_city"),
    ("AdditionalInterest_MailingAddress_StateOrProv",      "_addr_state"),
    ("AdditionalInterest_MailingAddress_PostalCode",       "_addr_zip"),
    ("AdditionalInterest_MailingAddress_CountryCode",      None),
    ("AdditionalInterest_AccountNumber",                   None),
    ("AdditionalInterest_Interest_Mortgagee",              None),
    ("AdditionalInterest_Interest_LossPayee",              None),
    ("AdditionalInterest_Interest_LendersLoss",            None),
    ("AdditionalInterest_Interest_AdditionalInsured",      None),
    ("AdditionalInterest_Interest_Lienholder",             None),
    ("AdditionalInterest_Interest_Employee",               None),
    ("AdditionalInterest_Interest_Other",                  None),
    ("AdditionalInterest_InterestRank",                    None),
    ("AdditionalInterest_CertificateRequired",             None),
    ("AdditionalInterest_Item_",                           None),
    ("AdditionalInterest_ItemDescription",                 None),
    ("Mortgagee_FullName",                                 "mortgagee_name"),
    ("Mortgagee_Name",                                     "mortgagee_name"),

    # ── Certificate holder ──────────────────────────────────────────────────
    ("CertificateHolder_FullName",                         "certificate_holder"),
    ("CertificateHolder_MailingAddress_LineOne",           "_addr_line1"),
    ("CertificateHolder_MailingAddress_LineTwo",           "_addr_line2"),
    ("CertificateHolder_MailingAddress_CityName",          "_addr_city"),
    ("CertificateHolder_MailingAddress_StateOrProv",       "_addr_state"),
    ("CertificateHolder_MailingAddress_PostalCode",        "_addr_zip"),

    # ── Auto ─────────────────────────────────────────────────────────────────
    ("Vehicle_LiabilityAutoOnly_PerAccidentLimitAmount",          "garage_liability_limit"),
    ("Vehicle_LiabilityOtherThanAutoOnly_PerAccidentLimitAmount", "garage_liability_limit"),
    ("Vehicle_LiabilityOtherThanAutoOnly_AggregateLimitAmount",   "garage_liability_limit"),
    ("GarageAndDealers_GarageKeepersComprehensive_LimitAmount",   "garagekeeper_liability_limit"),
    ("GarageAndDealers_GarageKeepersCollision_LimitAmount",       "garagekeeper_liability_limit"),
    ("GarageAndDealers_GarageKeepersComprehensive_PerAutoDeductibleAmount", "garagekeeper_comp_deductible"),
    ("GarageAndDealers_GarageKeepersCollision_PerAutoDeductibleAmount", "garagekeeper_coll_deductible"),
    ("GarageAndDealers_PhysicalDamageComprehensive_LimitAmount",  "auto_dealers_inventory_value"),
    ("GarageAndDealers_PhysicalDamageCollision_LimitAmount",      "auto_dealers_inventory_value"),
    ("Vehicle_CombinedSingleLimit_LimitIndicator",         "auto_liability_structure"),
    ("AutoLiability_CombinedSingleLimit",                  "auto_liability_limit"),
    ("Vehicle_CombinedSingleLimit",                        "auto_liability_limit"),
    ("Vehicle_BodilyInjury_PerPerson",                     "auto_liability_limit"),
    ("Vehicle_BodilyInjury_PerAccident",                   "auto_liability_limit"),
    ("Vehicle_PropertyDamage_PerAccident",                 "auto_liability_limit"),
    ("Vehicle_OtherCoverage_CoverageDescription",          None),
    ("Vehicle_OtherCoverage_LimitAmount",                  None),
    ("Vehicle_OtherCoveredAutoDescription",                None),
    ("Vehicle_InsurerLetterCode",                          None),

    # ── Workers comp ─────────────────────────────────────────────────────────
    ("WorkersCompensation_Payroll",                        "wc_payroll"),
    ("WorkersCompensation_ExperienceModification",         "wc_xmod"),
    ("WorkersCompensation_ExperienceMod",                  "wc_xmod"),
    # Most-specific patterns first — DiseaseEachEmployee before Disease alone
    ("WorkersCompensationEmployersLiability_EmployersLiability_EachAccident",           "wc_el_each_accident"),
    ("WorkersCompensationEmployersLiability_EmployersLiability_DiseaseEachEmployee",    "wc_el_disease_each_employee"),
    ("WorkersCompensationEmployersLiability_EmployersLiability_Disease",                "wc_el_disease_policy_limit"),
    ("WorkersCompensationEmployersLiability_EmployersLiability_EachEmployee",           "wc_el_disease_each_employee"),
    ("WorkersCompensation_EmployersLiability_EachAccident",                             "wc_el_each_accident"),
    ("WorkersCompensation_EmployersLiability_DiseaseEachEmployee",                      "wc_el_disease_each_employee"),
    ("WorkersCompensation_EmployersLiability_EachEmployee",                             "wc_el_disease_each_employee"),
    ("WorkersCompensation_EmployersLiability_PolicyLimit",                              "wc_el_disease_policy_limit"),
    ("EmployersLiability_EachAccident",                                                 "wc_el_each_accident"),
    ("EmployersLiability_Disease_EachEmployee",                                         "wc_el_disease_each_employee"),
    ("EmployersLiability_Disease_PolicyLimit",                                          "wc_el_disease_policy_limit"),
    ("WorkersCompensationEmployersLiability_OtherCoverage",                   None),
    ("WorkersCompensationEmployersLiability_InsurerLetterCode",               None),

    # ── Umbrella / excess ────────────────────────────────────────────────────
    ("Umbrella_EachOccurrence",                            "umbrella_limit"),
    ("Umbrella_Aggregate",                                 "umbrella_limit"),
    ("Umbrella_SelfInsuredRetention",                      "umbrella_sir"),
    ("ExcessUmbrella_Umbrella_EachOccurrenceAmount",       "umbrella_limit"),
    ("ExcessUmbrella_Umbrella_AggregateAmount",            "umbrella_limit"),
    ("ExcessUmbrella_Umbrella_DeductibleOrRetentionAmount","umbrella_sir"),
    # Bare "EachOccurrence" catch-all, relocated from the GL section above (see
    # the NOTE there): only needed for ACORD 160's GeneralLiability_
    # BodilyInjury_EachOccurrenceLimitAmount_A, which has no more-specific GL
    # rule. Placed AFTER every umbrella-specific rule so the umbrella's own
    # each-occurrence field (immediately above) is never shadowed by this
    # generic substring.
    ("EachOccurrence",                                     "gl_each_occurrence"),
    ("ExcessUmbrella_OtherCoverageDescription",            None),
    ("ExcessUmbrella_OtherCoverageLimitAmount",            None),
    ("ExcessUmbrella_InsurerLetterCode",                   None),

    # ── Contractors ──────────────────────────────────────────────────────────
    ("Contractors_WorkSubcontractedPercent",               "percent_subcontracted"),
    # NOT total_revenue - this field is "dollar amount paid TO subcontractors",
    # a distinct (usually much smaller) figure than annual gross revenue.
    # No dedicated extraction fact exists for it, so leave unmatched -> gap-fill
    # LLM reads the real number from raw text if the document states it;
    # otherwise it stays blank instead of silently showing total revenue.
    ("Contractors_SubcontractorsPaidAmount",               None),
    ("Contractors_FullTimeEmployeeCount",                  "num_employees"),
    # NOT num_employees - that would duplicate the full-time count into this
    # field verbatim (no dedicated part-time extraction fact exists). Leave
    # unmatched -> gap-fill LLM reads the real part-time figure from raw text
    # when the document states one distinctly; otherwise stays blank instead
    # of silently repeating the full-time number.
    ("Contractors_PartTimeEmployeeCount",                  None),
    ("Contractors_Question_",                              None),
    ("ProductAndCompletedOperations_AnnualGrossSalesAmount","total_revenue"),
    ("ProductAndCompletedOperations_UnitCount",            None),
    ("ProductAndCompletedOperations_InMarketMonth",        None),
    ("ProductAndCompletedOperations_ExpectedLife",         None),
    ("ProductAndCompletedOperations_IntendedUse",          None),
    ("ProductAndCompletedOperations_PrincipalComponents",  None),
    ("ProductAndCompletedOperations_ProductName",          None),

    # ── Alarm, security, exposure, miscellaneous null fields ─────────────────
    ("Alarm_Burglar_",                                     None),
    ("Burglar_LocalGong",                                  None),
    ("SwimmingPool_",                                      None),
    ("AthleticTeam_",                                      None),
    ("GeneralLiabilityLineOfBusiness_",                    None),
    ("CommercialInlandMarineProperty_",                    None),
    ("PropertyItem_ItemDetail_",                           None),
    ("OtherPolicy_InsurerLetterCode",                      None),
    ("OtherPolicy_OtherPolicyDescription",                 None),
    ("OtherPolicy_SubrogationWaived",                      None),
    ("OtherPolicy_CoverageCode",                           None),
    ("OtherPolicy_CoverageLimitAmount",                    None),
    ("CertificateOfLiabilityInsurance_",                   None),
    ("_RemarkText",                                        None),
    ("_Explanation",                                       None),

    # ── ACORD 126 fields not covered above — eliminates all LLM fallback calls ─
    # Signature / admin fields
    ("NamedInsured_Signature",                             None),   # wet-ink signature widget
    ("NamedInsured_SignatureDate",                         None),   # date below signature
    ("Producer_NationalIdentifier",                        None),   # NPN — not in extraction schema
    ("Producer_StateLicenseIdentifier",                    None),   # state license # — not extracted
    # GL claims-made continuous coverage entry date (not same as retro_date)
    ("GeneralLiability_ClaimsMade_UninterruptedCoverageEntryDate", "retro_date"),
    # GL limit description and deductible description free-text boxes
    ("GeneralLiability_OtherCoverageLimitDescription",     None),
    ("GeneralLiability_OtherDeductibleDescription",        None),
    # Additional interest WC certificate checkbox codes
    ("AdditionalInterest_WorkersCompensationCarriedCode",  None),
]


# ── Entity ownership of facts ────────────────────────────────────────────────
# A submission names several parties and ACORD puts the party in the FIELD NAME
# (verified across all 17 schemas: NamedInsured 212 fields, AdditionalInterest
# 182, Producer 131, Insurer 57, CertificateHolder 6, Driver 269). A fact that
# describes one party must never be stamped into another party's box.
#
# This is the general form of a rule the file already applied narrowly twice -
# the `_addr_*` guard below ("silently stamped the WRONG entity's address"), and
# Contractors_PartTimeEmployeeCount's "that would duplicate the full-time count".
# Both were correct and neither was generalised, so the same defect kept
# reappearing in new fields. A blocked field returns UNMATCHED rather than blank,
# so gap fill can still read that party's OWN value out of the document - the fix
# is not allowed to cost fill, only to stop borrowing.
#
# Only facts whose owner is unambiguous are listed. An unlisted fact is
# unconstrained, so adding an entry can only ever tighten, never loosen.
_FACT_ENTITY: Dict[str, str] = {
    "producer_name":          "Producer",
    "producer_address":       "Producer",
    "producer_contact_name":  "Producer",
    "producer_contact_phone": "Producer",
    "producer_contact_email": "Producer",
    "producer_fax":           "Producer",

    "carrier_name":           "Insurer",
    "carrier_naic":           "Insurer",
    "carrier_website":        "Insurer",

    "applicant_name":         "NamedInsured",
    "dba_name":               "NamedInsured",
    "fein":                   "NamedInsured",
    "applicant_website":      "NamedInsured",
    # The applicant's own contact person - see fact_registry ("the best phone
    # number to reach YOU") and arq_service, which puts these questions to the
    # insured. They are not the agency's details.
    "contact_name":           "NamedInsured",
    "contact_phone":          "NamedInsured",
    "contact_email":          "NamedInsured",
}

# Leading field-name segments that name a party. Anything not starting with one
# of these (BusinessInformation_*, CommercialPolicy_*, Policy_*, ...) has no
# owning party and is therefore never blocked.
# Every entry is verified against the real schemas by
# test_entity_prefixes_are_real_acord_prefixes - which caught "ParentCompany"
# here on its first run (parent-company data lives under Subsidiary_* and
# BusinessInformation_*, there is no ParentCompany_* field on any of the 17
# forms). A prefix that matches nothing silently disables the guard for it.
_FIELD_ENTITY_PREFIXES: Tuple[str, ...] = (
    "NamedInsured", "Producer", "Insurer", "AdditionalInterest",
    "CertificateHolder", "Driver", "Subsidiary",
)


# ── Line-of-business premium boxes ───────────────────────────────────────────
# ACORD 125 pairs every line-of-business checkbox with its own premium box (15
# pairs). Every one of them was blank on the client's form while the dec page
# printed four premiums, because "Premium" is in _NONFILLABLE_SUBSTRINGS and
# map_facts_to_form blanks those BEFORE any deterministic resolution runs - so no
# fact could ever have reached them.
#
# Which box belongs to which line is read from ACORD's OWN TOOLTIPS, never a
# hand-written synonym table: the checkbox says "Indicates that Business Auto
# line of business is being selected" and the premium says "The premium amount
# for the Commercial Vehicle (Business Auto) line of business". Parsing those
# gives 15/15 pairs on ACORD 125 and updates itself if a schema is regenerated.
_LOB_STOPWORDS = frozenset({
    "commercial", "line", "of", "business", "coverage", "and", "the", "a",
    "section", "insurance", "policy", "total",
})
_LOB_PHRASE_RE = re.compile(
    r"(?:indicates that|premium amount for)\s+(?:the\s+)?(.*?)\s+line of business",
    re.I,
)
_LOB_PARENTHETICAL_RE = re.compile(r"^(.*?)\s*\((.*?)\)\s*$")


def _lob_tokens(text: str) -> frozenset:
    """Distinctive words of a line-of-business name, stopwords removed, so that
    "Commercial Auto" and "Business Auto" both reduce to {auto}."""
    lowered = (text or "").lower().replace("&", " and ")
    return frozenset(
        t for t in re.split(r"[^a-z0-9]+", lowered)
        if t and t not in _LOB_STOPWORDS
    )


def _lob_phrase_variants(tooltip: Optional[str]) -> List[str]:
    """The line name(s) an ACORD tooltip states. ACORD writes the synonym inline
    as a parenthetical - "Commercial Vehicle (Business Auto)" - so both spellings
    are returned and either may match the document's wording."""
    m = _LOB_PHRASE_RE.search(tooltip or "")
    if not m:
        return []
    raw = m.group(1).strip()
    paren = _LOB_PARENTHETICAL_RE.match(raw)
    if paren:
        return [paren.group(1).strip(), paren.group(2).strip()]
    return [raw]


@lru_cache(maxsize=1)
def _lob_premium_index() -> Dict[str, Tuple[frozenset, ...]]:
    """{premium_field_name: (token_set_per_accepted_spelling, ...)} across all
    schemas. Cached; pure derivation from the shipped schemas."""
    index: Dict[str, Tuple[frozenset, ...]] = {}
    try:
        schemas = _all_form_schemas()
    except Exception as exc:                              # noqa: BLE001
        logger.warning("lob-premium: cannot load schemas — %s", exc)
        return index
    for schema in schemas.values():
        for field, meta in schema.items():
            if "PremiumAmount" not in field:
                continue
            tooltip = (meta or {}).get("tu") or ""
            # A MINIMUM premium is not the line's premium - it is the floor the
            # carrier will charge. ACORD 160 carries both for Business Owners
            # ("the minimum premium amount for..." and "the total estimated
            # premium amount for..."), and both tooltips name the same line, so
            # leaving the minimum in this index did two kinds of damage: it
            # risked stamping the line premium into the minimum box, and - worse,
            # because it was silent - the two boxes matched each other, tripped
            # the ambiguity refusal, and made the LEGITIMATE Business Owners
            # premium box on ACORD 160 permanently unfillable.
            # Read from ACORD's own wording, not the field name.
            if "minimum premium" in tooltip.lower():
                continue
            variants = _lob_phrase_variants(tooltip)
            token_sets = tuple(
                ts for ts in (_lob_tokens(v) for v in variants) if ts
            )
            if token_sets:
                index[field] = token_sets
    return index


def _is_lob_premium_field(field_name: str) -> bool:
    return field_name in _lob_premium_index()


def _is_currency_value(text: str) -> bool:
    """A money figure, using the registry's own currency validator."""
    try:
        from services.fact_registry import _is_currency
        return _is_currency(text)
    except Exception:                                     # noqa: BLE001
        return bool(re.search(r"\d", text or ""))


# ── Stamp-time shape checking ────────────────────────────────────────────────
# `fact_registry` has carried a correct `_is_fein` ("9 digits, with or without
# hyphen") since long before the client reported `0482854` - a 7-digit EMC
# ACCOUNT number - sitting in the FEIN box. It never ran, because `pdf_service`
# imports `FACT_REGISTRY` for its KEYS only. The registry's validators are the
# single source of truth for a value's shape; this wires them to the form.
#
# ONLY these four are enforced, on purpose. C22's ~49,000-pair sweep established
# the rule: an amount box legitimately holds "Statutory", "Included" or "See
# schedule", so a currency validator must never police a form field. A FEIN, an
# email address, a phone number and a URL have no legitimate prose alternative.
# Adding a validator here is a deliberate one-line opt-in, never automatic.
#
# The action is DEMOTE, never blank: the value stays on the form and its trust
# label drops so the highlight layer paints it "Verify". Same treatment, and the
# same reasoning, as the owner/insured contamination override.
_HARD_SHAPE_VALIDATORS = None          # built lazily - see _hard_shape_validators()


_US_ZIP_RE = re.compile(r"^\d{5}(?:-?\d{4})?$")
_CA_ZIP_RE = re.compile(r"^[A-Z]\d[A-Z]\s?\d[A-Z]\d$", re.I)


def _is_postal_code(value: Any) -> bool:
    s = str(value or "").strip()
    return bool(_US_ZIP_RE.match(s) or _CA_ZIP_RE.match(s))


def _is_single_count(value: Any) -> bool:
    """One number, however it is written. Two numbers is a range, not a count."""
    return len(re.findall(r"\d+", str(value or "").replace(",", ""))) == 1

# Field-name tokens whose shape is unambiguous whatever fact (if any) feeds them.
# Catches gap-filled boxes that no `_ACORD_FIELD_RULES` entry claims - which is
# how "Claim Reporting: (888) 362-2255" ended up in a PRIMARY E-MAIL box
# (client #11).
_NAME_SHAPE_TOKENS: Tuple[Tuple[str, str], ...] = (
    ("EmailAddress", "email"),
    ("WebsiteAddress", "url"),
    # A POSTAL CODE box holds a postal code. Live run: address fragments -
    # "4800 D", "Denve" - were stamped into the ZIP cells of three empty
    # premises rows, sliced out of the street line above them.
    ("PostalCode", "zip"),
    # A COUNT box holds one integer. Live run: "0 - 25" in NO. OF MEMBERS AND
    # MANAGERS, and on another run the word "LLC". A range is not a count, and
    # ACORD's own declared "number" type accepts prose-free ranges (C22 keeps it
    # that way on purpose for year ranges), so the count case needs its own rule.
    ("MemberManagerCount", "count"),
    ("EmployeeCount", "count"),
    # An NAIC company code is NUMERIC (3-6 digits, leading zeros legal). Live
    # run: the CARRIER'S NAME ("EMC Prope...") stamped into the NAIC CODE box;
    # the run before that, the literal string "not present". A name can never
    # be an NAIC code, and no legitimate NAIC value contains letters.
    ("NAICCode", "naic"),
)


def _is_naic_code(value: Any) -> bool:
    s = str(value or "").strip()
    return bool(re.fullmatch(r"\d{3,6}", re.sub(r"[\s-]", "", s)))


def _hard_shape_validators() -> dict:
    global _HARD_SHAPE_VALIDATORS
    if _HARD_SHAPE_VALIDATORS is None:
        try:
            from services.fact_registry import _is_email, _is_fein, _is_phone, _is_url
            _HARD_SHAPE_VALIDATORS = {
                "email": _is_email, "url": _is_url,
                "fein": _is_fein, "phone": _is_phone,
                # US 5 or 5+4, or a Canadian "A1A 1A1". ACORD's own tooltip
                # says only "postal code", and two of these boxes belong to an
                # ADDITIONAL INTEREST, which has a CountryCode field beside it -
                # so a non-US code is legitimate here and must not be blanked.
                "zip": _is_postal_code,
                # A count box holds ONE number. Deliberately not `^\d+$`: a real
                # count is written "1,200" as often as "1200", and a qualifier
                # ("approx. 25") is imprecise, not impossible. The defect is TWO
                # numbers ("0 - 25", the live run) or NONE ("LLC").
                "count": _is_single_count,
                "naic": _is_naic_code,
            }
        except Exception as exc:                          # noqa: BLE001
            logger.warning("shape-check: validators unavailable — %s", exc)
            _HARD_SHAPE_VALIDATORS = {}
    return _HARD_SHAPE_VALIDATORS


# ── Single-choice checkbox families ──────────────────────────────────────────
# ACORD marks these itself. Three boxes on ACORD 125 share one tooltip phrase -
# "the RESPONSE EXPECTED FROM THE COMPANY is a quote / an issued policy / a
# renewed policy" - and you can only expect one response, so ticking two is a
# contradiction. Present on 125 (3 boxes), 130 (3), 131 (2), 133 (1).
#
# READ THIS BEFORE EXTENDING IT. Client report #4 says "Both Issue Policy and
# Bound are populated ... Select the appropriate status", but ACORD's own
# wording shows those two are NOT the same family:
#     IssueIndicator - "the response expected from the company is an issued policy"
#     BoundIndicator - "Indicates the coverage HAS BEEN BOUND"
# One is a request, the other is a state of the coverage, and "bound, please
# issue the policy" is the ordinary broker workflow. Treating them as exclusive
# would blank a legitimate tick. The family is derived from ACORD's phrase for
# exactly that reason - so the boundary is ACORD's, not a guess.
_SINGLE_CHOICE_TOOLTIP_MARKERS: Tuple[str, ...] = (
    "response expected from the company is",
)


@lru_cache(maxsize=32)
def _single_choice_groups(schema_keys: Tuple[str, ...],
                          tooltips: Tuple[str, ...]) -> Tuple[Tuple[str, ...], ...]:
    """Groups of checkboxes of which at most one may be ticked."""
    groups: Dict[str, List[str]] = {}
    for field, tooltip in zip(schema_keys, tooltips):
        low = (tooltip or "").lower()
        for marker in _SINGLE_CHOICE_TOOLTIP_MARKERS:
            if marker in low:
                groups.setdefault(marker, []).append(field)
    return tuple(tuple(v) for v in groups.values() if len(v) > 1)


def _contradictory_single_choice_fields(mapped: dict, schema: dict) -> set:
    """Every member of a single-choice family that has more than one tick.

    Returns fields to DEMOTE, never to blank. Which of two contradictory ticks
    is the right one is genuinely unknowable here, and choosing would be a guess
    that silently discards a correct answer. Turning both orange puts the
    contradiction in front of the broker, who does know.
    """
    keys = tuple(schema.keys())
    tips = tuple((schema.get(k) or {}).get("tu") or "" for k in keys)
    flagged: set = set()
    for group in _single_choice_groups(keys, tips):
        ticked = [
            f for f in group
            if str(mapped.get(f) or "").strip().lower() in _AFFIRMATIVE_VALUES
        ]
        if len(ticked) > 1:
            flagged.update(ticked)
    return flagged


# ── Auto liability: combined single limit vs split limits ────────────────────
# An auto policy states its liability EITHER as one combined single limit (CSL)
# OR as three split figures (100/300/50 = $100,000 bodily injury per person /
# $300,000 per accident / $50,000 property damage). Never both.
#
# `auto_liability_limit` was mapped into ALL FOUR boxes, so a single $1,000,000
# CSL was stamped as $1M combined AND $1M per person AND $1M per accident AND
# $1M property damage - reading as $1M for every part. On ACORD 25, which is a
# certificate relied on by a third party, that is a material misstatement of
# coverage. 26 boxes across ACORD 25, 131, 137_CA and 137_CO.
#
# Found by the cross-form sweep, not by a client report.
_CSL_FIELD_TOKEN = "CombinedSingleLimit"
_SPLIT_FIELD_FACTS: Tuple[Tuple[str, str], ...] = (
    ("BodilyInjury_PerPerson",     "auto_bi_per_person"),
    ("BodilyInjury_PerAccident",   "auto_bi_per_accident"),
    ("PropertyDamage_PerAccident", "auto_pd_per_accident"),
)


def _resolve_auto_liability_limit_cell(field_name: str, facts: dict):
    """The CSL box or a split box, never both, or _SCHED_SKIP when neither.

    Which structure applies is read from the `auto_split_limits` flag the
    extraction prompt already produces. When it is absent the policy is treated
    as combined-single-limit, which is both the common case and the existing
    behaviour for that box - so this can only ever REMOVE the three duplicate
    stamps, never the real one.
    """
    is_csl_box = _CSL_FIELD_TOKEN in field_name and "Indicator" not in field_name
    split_fact = next(
        (fact for token, fact in _SPLIT_FIELD_FACTS if token in field_name), None
    )
    if not is_csl_box and split_fact is None:
        return _SCHED_SKIP

    raw_split = _fv(facts, "auto_split_limits")
    is_split = raw_split is True or str(raw_split).strip().lower() in {"true", "yes", "1"}

    if is_csl_box:
        # A split-limit policy has no combined single limit to state.
        return None if is_split else (_fv(facts, "auto_liability_limit") or None)

    # A split box on a CSL policy stays empty - the combined limit is NOT the
    # per-person, per-accident or property-damage figure.
    if not is_split:
        return None
    return _fv(facts, split_fact) or None


# ── THE FORM'S OWN EDITION ───────────────────────────────────────────────────
# Client, 2026-08-12, on the agency-question panel: "Form edition identifier:
# The edition/version date of the ACORD form being generated. This should
# normally be populated automatically by the system from the selected form
# version, not asked of the client." They classified it "Auto-populate".
#
# They are right, and it is the one item on that panel nobody should ever be
# asked for: we CHOSE the template, so we already know its edition. Before this
# it was an empty box on 16 of the 17 forms, surfaced as a question to the
# producer, and reachable by gap fill (which can only guess).
#
# Read from the template's own printed footer ("ACORD 125 (2025/03)"), so it can
# never disagree with the PDF we are actually stamping - and it is genuinely
# per-form: verified 125 = 2025/03 but 127 = 2015/12. Hardcoding one edition, or
# copying 125's onto every form, would put a false edition on a legal document.
_FORM_EDITION_FIELD_RE = re.compile(r"^Form_EditionIdentifier_[A-N]$")
_ACORD_EDITION_RE = re.compile(r"ACORD\s+(\d+[A-Z]*)\s*\((\d{4}/\d{2})\)")


@lru_cache(maxsize=64)
def _form_edition_identifier(form_id: str) -> Optional[str]:
    """`"ACORD 125 (2025/03)"` for a form, or None when it cannot be read.

    Cached per form: this opens a PDF, and it is called once per schema field.
    Failure is always None - an unreadable template must never break a
    generation, it just leaves the box empty as it is today.
    """
    if not form_id:
        return None
    try:
        import glob as _glob
        candidates = [os.path.join(TEMPLATE_DIR, f"{form_id}.pdf")]
        candidates += sorted(_glob.glob(os.path.join(TEMPLATE_DIR, f"{form_id}*.pdf")))
        for path in candidates:
            if not os.path.exists(path):
                continue
            import pdfplumber
            with pdfplumber.open(path) as pdf:
                text = pdf.pages[0].extract_text() or ""
            m = _ACORD_EDITION_RE.search(text)
            if m:
                return f"ACORD {m.group(1)} ({m.group(2)})"
    except Exception as exc:                              # noqa: BLE001
        logger.warning("form_edition: could not read edition for %s: %s", form_id, exc)
    return None


# ── PHANTOM SCHEDULE ROWS ────────────────────────────────────────────────────
# A repeating row for an entity the document does not contain.
#
# THE DEFECT, measured on the client's live ACORD 127 (2026-08-12): the document
# describes ONE vehicle - a 2012 Subaru Outback - and the generated form came
# back with rows 2 and 3 carrying the GENERAL LIABILITY class codes 91580/91585
# and the GL exposures ($39,300 payroll, $350,000 subcontract cost) stamped as
# vehicle COST NEW, plus a duplicate of the Subaru.
#
# Root cause is NOT cross-form batch confusion, which was the first theory and
# was wrong. `_SCHEDULE_REGISTRY` binds only the 19 IDENTITY columns of the
# vehicle schedule (VIN, make, model, body). `_resolve_schedule_row` already
# holds the correct contract for those - "if the row is out of range, mark as
# authoritative blank, do NOT send to GPT, we know the row doesn't exist" - but
# the other ~50 columns per row (cost new, rate class, territory, symbols, the
# coverage indicators) are unbound, so they fell through to gap fill for EVERY
# row letter the form prints. Measured: **164 questions about vehicles B-D that
# do not exist**, against 56 for the one real vehicle. Asked "what is vehicle
# B's cost new?" with no vehicle B to describe, the model does the only thing it
# can and borrows a plausible figure from the document.
#
# This applies the SAME rule `_resolve_schedule_row` already enforces, to the
# whole row rather than to the registered columns of it. Generic across all 16
# schedule roots and all 17 forms - no vehicle-specific, carrier-specific or
# form-specific logic.
#
# IT ACTS ONLY ON POSITIVE EVIDENCE. An absent or empty schedule list means we
# know nothing about how many rows exist, so nothing is suppressed and the
# behaviour is exactly as before. Capacity is `len(list) + row_offset` because
# some roots do not draw their first row from the list at all - NamedInsured_A
# is the applicant, with the list supplying row B onward (row_offset=1). Using
# len() alone there would blank a real named insured.
_ROW_LETTERS = "ABCDEFGHIJKLMN"


@lru_cache(maxsize=1)
def _schedule_root_bindings() -> Dict[str, Tuple[Tuple[str, int], ...]]:
    """root name -> ((fact list key, row_offset), ...), from _SCHEDULE_REGISTRY.

    Derived, never hand-listed: a new schedule registered above is covered here
    automatically, which is what stops the two from drifting apart.
    """
    roots: Dict[str, set] = {}
    for base, defn in _SCHEDULE_REGISTRY.items():
        roots.setdefault(base.split("_", 1)[0], set()).add(
            (defn.list_key, defn.row_offset))
    return {root: tuple(sorted(v)) for root, v in roots.items()}


# ── A SCHEDULE ROW WITH NO IDENTITY IS NOT A ROW ─────────────────────────────
# The other half of the phantom-row defence, and the half that does not depend
# on extraction. `_resolve_phantom_schedule_row` below suppresses rows beyond a
# KNOWN schedule length - it acts only on positive evidence, so on a run where
# extraction misses `auto_vin_schedule` entirely (measured live 2026-08-13:
# extraction jitters run to run) it stands down, gap fill owns all 220 vehicle
# questions, and row 2 of the printed form came back carrying the GENERAL
# LIABILITY class code 91585 as its rate class, $10,000 as COST NEW and the UM
# deductible - C46's literal defect, reborn through a different door.
#
# This rule needs no schedule fact at all: a row whose IDENTITY columns are all
# empty has no subject, so the detail stamped into it describes nobody. A
# vehicle with no VIN, no make, no model and no year is not a vehicle; a driver
# with no name is not a driver. Identity columns are the ones already registered
# in `_SCHEDULE_REGISTRY` - derived, never hand-listed, so a new schedule is
# covered the day it is registered.
#
# Bounded the same way `_unanchored_entity_row_fields` is:
#   * only GAP-FILL values are cleared - a resolver-stamped detail implies the
#     backing record exists, which implies the row is anchored anyway;
#   * rows below a root's minimum row_offset are exempt (NamedInsured_A is the
#     applicant, not a list row, and must never be judged here);
#   * a root whose registered identity columns do not exist on this schema has
#     nothing to anchor on and is skipped, not cleared.
def _unanchored_schedule_row_fields(mapped: dict, schema: dict,
                                    gpt_filled_set: set) -> set:
    """Gap-fill values sitting in a schedule row whose identity is empty."""
    identity_bases: Dict[str, set] = {}
    for base in _SCHEDULE_REGISTRY:
        identity_bases.setdefault(base.split("_", 1)[0], set()).add(base)
    min_offset: Dict[str, int] = {}
    for root, bindings in _schedule_root_bindings().items():
        min_offset[root] = min(off for _k, off in bindings)

    out: set = set()
    by_row: Dict[Tuple[str, str], list] = {}
    for field in schema:
        name = field or ""
        if len(name) < 3 or name[-2] != "_" or name[-1] not in _ROW_LETTERS:
            continue
        root = name.split("_", 1)[0]
        if root not in identity_bases:
            continue
        by_row.setdefault((root, name[-1]), []).append(field)

    for (root, letter), fields in by_row.items():
        # STRICTLY BEYOND THE FIRST LIST ROW. Row A of a schedule root also
        # carries per-form singletons that merely share the prefix -
        # `Vehicle_Question_ModifiedEquipmentDescription_A` is a General
        # Information answer, not a schedule cell, and judging row A cleared a
        # genuine equipment description in the test corpus the moment this
        # guard was first wired. Rows beyond the first are where the live
        # defect actually lives (the leaked GL class codes sat in row B), and a
        # detail in row C of a schedule whose row C has no identity is
        # indefensible whatever kind of field it is.
        if _ROW_LETTERS.find(letter) <= min_offset.get(root, 0):
            continue
        anchors = [f"{base}_{letter}" for base in identity_bases[root]
                   if f"{base}_{letter}" in schema]
        if not anchors:
            continue                       # nothing to anchor on -> not judged
        if any(str(mapped.get(a) or "").strip() for a in anchors):
            continue                       # the row has an identity -> real
        for f in fields:
            if f in gpt_filled_set and str(mapped.get(f) or "").strip():
                out.add(f)
    return out


def _resolve_phantom_schedule_row(field_name: str, facts: dict):
    """`None` (authoritative blank) for a row beyond what the document supports.

    `_SCHED_SKIP` means "not my business" - not a row field, not a known
    schedule root, no row-count evidence, or a row that really exists.
    """
    name = field_name or ""
    if len(name) < 3 or name[-2] != "_":
        return _SCHED_SKIP
    idx = _ROW_LETTERS.find(name[-1])
    if idx < 0:
        return _SCHED_SKIP
    bindings = _schedule_root_bindings().get(name.split("_", 1)[0])
    if not bindings:
        return _SCHED_SKIP

    # MAX across a root's bindings: Vehicle_* draws from both auto_vin_schedule
    # and auto_garaging_addresses, and a row supported by EITHER is real. Erring
    # high can only ever leave today's behaviour in place.
    capacity = 0
    for list_key, row_offset in bindings:
        rows = (facts or {}).get(list_key)
        if isinstance(rows, list) and rows:
            capacity = max(capacity, len(rows) + (row_offset or 0))
    if capacity <= 0:
        return _SCHED_SKIP            # no evidence -> change nothing
    if idx < capacity:
        return _SCHED_SKIP            # a real row -> normal handling
    return None                       # beyond the schedule -> must stay blank


# Resolvers that OWN a field outright: when they decline to produce a value the
# box must stay EMPTY, not fall through to the gap-fill LLM.
#
# This is the same "authoritative blank" contract `_resolve_schedule_row` already
# has ("If the row is out of range, mark as authoritative blank - do NOT send to
# GPT, we know the row doesn't exist"), and it was missing here. `None` out of
# `_deterministic_map` lands in `map_facts_to_form`'s
#
#     if result == "UNMATCHED" or _is_empty_llm_value(result): unmatched[field] = ...
#
# branch, which means "ask the model". So every deliberate blank these resolvers
# produced was being handed straight to gap fill, which happily refilled it from
# raw text. Observed on a real run: the prior-coverage grid still showed one
# policy number sprayed across the General Liability, Property and Other columns
# even though `_resolve_prior_coverage_cell` had correctly returned None for all
# three. Unit tests missed it because they called `_deterministic_map` directly
# and never exercised the routing above it.
_AUTHORITATIVE_BLANK_RESOLVERS = (
    "_resolve_prior_coverage_cell",
    "_resolve_current_policy_line_cell",
    "_resolve_auto_liability_limit_cell",
    "_resolve_other_policy_cell",
    "_resolve_other_lob_row",
    "_resolve_policy_status",
    "_resolve_additional_interest_type",
    "_resolve_address_line_two",
    "_resolve_producer_mailing",
    "_resolve_applicant_contact",
    "_resolve_estimated_total",
    "_resolve_payment_schedule",
    "_resolve_schedule_family_row",
    "_resolve_producer_printed_name",
    "_resolve_applicant_website",
    "_resolve_section_attached_indicator",
    # REMARKS / PROCESSING INSTRUCTIONS - about OUR submission, so no model may
    # read it off the carrier's policy. See _resolve_remark_text.
    "_resolve_remark_text",
    # A fax number stamps from the party's own fax fact or not at all - three
    # runs of the producer's PHONE in the FAX box. See _resolve_party_fax.
    "_resolve_party_fax",
    # The deposit box stamps from a deposit fact or not at all - two runs of
    # borrowed figures (the package total, then the terrorism premium).
    "_resolve_payment_deposit",
    # Extends _resolve_schedule_row's out-of-range contract from the registered
    # identity columns to the WHOLE row. See _resolve_phantom_schedule_row.
    "_resolve_phantom_schedule_row",
    # Claims-made dates exist only on a claims-made policy; the occurrence-form
    # package got its effective date stamped as a retroactive date (run 9).
    "_resolve_claims_made_dates",
    # MAXIMUM DOLLAR VALUE SUBJECT TO LOSS is the vehicle schedule's arithmetic,
    # not the liability limit that landed there on run 9.
    "_resolve_max_vehicle_exposure",
    # Employee counts drive rating; run 9 invented "1 full-time / 0 part-time"
    # on the 126 while the 125's identical boxes were correctly blank.
    "_resolve_exposure_count",
    # $0 TOTAL LOSSES is a clean-history attestation - same client rule as the
    # no-loss checkbox below, applied to the summary amounts (run 9).
    "_resolve_loss_history_summary",
    # "Check if none" on the loss-history table. 52-page trap run (2026-08-12):
    # the deterministic resolver found no no-loss assertion, returned
    # "UNMATCHED", and gap fill then ticked the box quoting "Prior Term Loss
    # Experience: NOT ON FILE" - which means UNKNOWN, not "no losses". Attesting
    # a clean loss history is the one checkbox the client explicitly said must
    # never be inferred ("require client confirmation and preferably currently
    # valued loss runs"), so when the deterministic signals say nothing, the
    # box stays EMPTY and the ARQ asks - the model never gets to guess it.
    "_resolve_no_loss_checkbox_owned",
)


def _is_authoritative_blank_field(field_name: str, facts: dict) -> bool:
    """True when an owning resolver claims this field but produced no value, so
    the box must be left empty rather than guessed."""
    for name in _AUTHORITATIVE_BLANK_RESOLVERS:
        try:
            if globals()[name](field_name, facts) is not _SCHED_SKIP:
                return True
        except Exception:                                 # noqa: BLE001
            continue
    return False


# Entity blocks that are OPTIONAL - unlike the Named Insured, whose row A always
# exists because the form is about them, an additional interest or certificate
# holder may simply not be there. So row A is subject to the name-anchor rule
# too. Client, on the live form: "An insurance carrier would not normally be
# added as an additional insured on the policy it services. The entire
# Additional Interest entry should be removed."
_OPTIONAL_ENTITY_PREFIXES: Tuple[str, ...] = (
    "AdditionalInterest", "CertificateHolder",
)

# Detail boxes whose subject is named by a DIFFERENT field family, so the
# row-and-prefix grouping below cannot pair them. Explicit and hand-verified,
# the same pattern as `_NONADJACENT_DEPENDENT_FIELDS`.
#
# Client, on the live form: "Nothing in the declarations identifies a parent
# company or says that Orbin Contracting is 50% owned by another entity... The
# 'parent company' wording and 50% ownership figure should be removed." And on
# the subsidiary half: "An endorsement covering subsidiaries does not prove that
# subsidiaries exist."
_ANCHORED_DETAIL_GROUPS: Tuple[Tuple[str, Tuple[str, ...]], ...] = (
    ("BusinessInformation_ParentOrganizationName_A", (
        "Subsidiary_ParentSubsidiaryRelationshipDescription_A",
        "Subsidiary_ParentOwnershipPercent_A",
    )),
    ("Subsidiary_OrganizationName_A", (
        "Subsidiary_ParentSubsidiaryRelationshipDescription_B",
        "Subsidiary_ParentOwnershipPercent_B",
    )),
    # DELIBERATELY NOT HERE: ("NamedInsured_FullName_B",
    #                         ("CommercialPolicy_OperationsDescription_B",)).
    # Tried 2026-08-13 for the "COMMERCIAL GENERAL CONTRA" defect and reverted -
    # it broke `test_a_genuinely_different_row_b_narrative_survives`, which is a
    # deliberate prior contract: extraction can legitimately find a second
    # insured's operations while missing their NAME, and blanking a real
    # narrative to punish a missing name loses more than it saves. The actual
    # defect there is that the value is a TRUNCATED COPY, not that its subject is
    # unnamed - see `_is_truncated_copy_of_a_held_value`.
    # Q8/Q9/Q10 incident rows: a date without the incident's own explanation is
    # not a record. Graded test run: a CLAIM date (05/22/2025) surfaced as a
    # judgment/lien RESOLVE DATE while the explanation and the question's own
    # Y/N stayed empty. Anchoring each row's dates on its explanation clears
    # the orphan; a genuine incident (explanation present) keeps its dates.
    ("CommercialPolicy_UncorrectedFireCodeViolationExplanation_A", (
        "CommercialPolicy_UncorrectedFireCodeViolation_OccurrenceDate_A",
        "CommercialPolicy_UncorrectedFireCodeViolation_ResolutionDate_A",
        "CommercialPolicy_UncorrectedFireCodeViolation_ResolutionDescription_A",
    )),
    ("CommercialPolicy_UncorrectedFireCodeViolationExplanation_B", (
        "CommercialPolicy_UncorrectedFireCodeViolation_OccurrenceDate_B",
        "CommercialPolicy_UncorrectedFireCodeViolation_ResolutionDate_B",
        "CommercialPolicy_UncorrectedFireCodeViolation_ResolutionDescription_B",
    )),
    ("CommercialPolicy_ForeclosureRepossessionBankruptcyExplanation_A", (
        "CommercialPolicy_ForeclosureRepossessionBankruptcy_OccurrenceDate_A",
        "CommercialPolicy_ForeclosureRepossessionBankruptcy_ResolutionDate_A",
        "CommercialPolicy_ForeclosureRepossessionBankruptcy_ResolutionDescription_A",
    )),
    ("CommercialPolicy_ForeclosureRepossessionBankruptcyExplanation_B", (
        "CommercialPolicy_ForeclosureRepossessionBankruptcy_OccurrenceDate_B",
        "CommercialPolicy_ForeclosureRepossessionBankruptcy_ResolutionDate_B",
        "CommercialPolicy_ForeclosureRepossessionBankruptcy_ResolutionDescription_B",
    )),
    ("CommercialPolicy_JudgementOrLienExplanation_A", (
        "CommercialPolicy_JudgementOrLien_OccurrenceDate_A",
        "CommercialPolicy_JudgementOrLien_ResolutionDate_A",
        "CommercialPolicy_JudgementOrLien_ResolutionDescription_A",
    )),
    ("CommercialPolicy_JudgementOrLienExplanation_B", (
        "CommercialPolicy_JudgementOrLien_OccurrenceDate_B",
        "CommercialPolicy_JudgementOrLien_ResolutionDate_B",
        "CommercialPolicy_JudgementOrLien_ResolutionDescription_B",
    )),
)


# ── Q4 "other insurance with this company" ───────────────────────────────────
# The line and the policy number are two boxes on one row, and gap fill filled
# them independently - so on the live form the General Liability row carried the
# AUTO policy number and the Commercial Auto row carried the GL number. Swapped.
# Stamping the pair TOGETHER from one `coverage_lines` entry makes a mismatch
# structurally impossible; a row is only written when that entry has BOTH.
_OTHER_POLICY_LINE_RE = re.compile(
    r"^OtherPolicy_(LineOfBusinessCode|PolicyNumberIdentifier)_([A-N])$")


# ── A FORM number is not a POLICY number ─────────────────────────────────────
# Live run 2026-08-13. Q4 "other insurance with this company" came back:
#     (blank)  IM 7100 06 04       <- AAIS Installation Floater FORM
#     Computer Coverage  IM 7201 10 02   <- AAIS Computer Coverage FORM
# and the two real policy numbers it displaced - the umbrella's 6J7-40-02---26
# and the GL's BBC7263 - dropped off the form entirely. Visible upstream in the
# extraction log:
#     merge coverage_lines FINAL: ... ('Installation Floater', 'None',
#         'IM 7100 06 04'), ('Computer Coverage', 'None', 'IM 7201 10 02')
#
# A form number identifies the COVERAGE WORDING an insurer attached; a policy
# number identifies THIS CONTRACT. Confusing them puts a public ISO/AAIS document
# reference on a legal application in the box that says which policy the
# applicant holds.
#
# The shape is an industry convention, not a guess: two letters, a 2-to-4 digit
# form number, then 2-digit groups ending in an edition month and year.
# `text_selection._ISO_FORM_CODE_RE` already recognises the ISO variant for the
# standard-form page filter; this is the same convention widened to AAIS's
# 4-digit form numbers, kept local because the two callers want different
# anchoring (that one scans mid-page, this one must match the WHOLE value).
_FORM_NUMBER_RE = re.compile(
    r"^[A-Z]{2}[ -]?\d{2,4}(?:[ -]\d{2}){2,3}$", re.I)


def _looks_like_a_form_number(value: Any) -> bool:
    """True for `IM 7100 06 04`, `CG 00 01 04 13`, `IL 00 17 11 98`.

    False for every real policy number in the client's package - `6E7-40-02---26`
    and `6C7-40-02---26` (lead with a digit), `BBC7263 - 26` (three letters, no
    separator before the digits). Anchored end to end so a policy number that
    merely CONTAINS such a run is untouched.
    """
    return bool(_FORM_NUMBER_RE.match(str(value or "").strip()))


def _resolve_other_policy_cell(field_name: str, facts: dict):
    m = _OTHER_POLICY_LINE_RE.match(field_name)
    if not m:
        return _SCHED_SKIP
    attr, letter = m.group(1), m.group(2)
    lines = _fv(facts, "coverage_lines")
    if not isinstance(lines, list) or not lines:
        return _SCHED_SKIP                 # no per-line data - legacy path
    # Only lines that actually state their own policy number can fill a row, so
    # the two columns always advance together.
    rows = []
    for e in lines:
        if not isinstance(e, dict):
            continue
        if not (str(e.get("policy_number") or "").strip()
                and str(e.get("line") or "").strip()):
            continue
        # A form number in the policy-number slot disqualifies the ROW, not just
        # the cell: the paired line name came from the same entry, so keeping it
        # would print a coverage line with no policy number beside it, and the
        # row it occupies would displace a real policy from the four printed
        # slots - which is exactly what happened live.
        if _looks_like_a_form_number(e.get("policy_number")):
            logger.info(
                "other_policy: row dropped - %r is a form number, not a policy "
                "number (line=%r)", e.get("policy_number"), e.get("line"),
            )
            continue
        rows.append(e)
    # One row per DISTINCT policy number. A live run stamped the same number on
    # every Q4 row because extraction attached one number to several lines —
    # visibly wrong on the form, and a duplicate row carries no information.
    seen_numbers: set = set()
    unique_rows = []
    for e in rows:
        pn_key = re.sub(r"[^a-z0-9]", "", str(e.get("policy_number")).lower())
        if pn_key in seen_numbers:
            continue
        seen_numbers.add(pn_key)
        unique_rows.append(e)
    rows = unique_rows
    idx = _ROW_LETTER_TO_IDX[letter]
    if idx >= len(rows):
        return None
    entry = rows[idx]
    key = "line" if attr == "LineOfBusinessCode" else "policy_number"
    value = str(entry[key]).strip()
    if key == "line":
        # Label sanity: extraction attached the line name "Property" to the
        # INLAND MARINE policy number on two consecutive live runs — on a
        # package whose dec page prints "PROPERTY — NO COVERAGE" (the
        # declared-absent downgrade had already set has_property_coverage
        # False). A row must not claim a line the document denies: the policy
        # NUMBER still stamps (it is real); only the wrong label is withheld.
        try:
            from services.extraction_service import _FLAG_LINE_WORDS
            _v_low = value.lower()
            for _flag, _words in _FLAG_LINE_WORDS.items():
                if facts.get(_flag) is False and any(w in _v_low for w in _words):
                    return None
        except Exception:                                 # noqa: BLE001
            pass
    return value


# ── Estimated total policy cost ──────────────────────────────────────────────
# ACORD 125's printed "POLICY PREMIUM" box. Its field name carries no "Premium"
# token, so it escaped the non-fillable premium guard and went to the model —
# which flip-flopped across live runs: $3,954 (the GL line premium alone), then
# the correct $10,663, then $3,954 again. A package total is ARITHMETIC over
# figures we already extracted, not a judgement call: when every granted
# coverage line carries a parseable premium, the total is their sum; otherwise
# the box is an owned blank (a partial sum understates a legal figure). The
# model is never asked.
_ESTIMATED_TOTAL_RE = re.compile(r"^Policy_Payment_EstimatedTotalAmount_[A-N]$")


def _resolve_estimated_total(field_name: str, facts: dict):
    if not _ESTIMATED_TOTAL_RE.match(field_name):
        return _SCHED_SKIP
    # A total the DOCUMENT states beats one we compute. Measured on the real
    # 271-page package: summing per-line premiums produced $9,438 because one
    # line's premium was missed at extraction, while the dec page prints the
    # true $10,663 total outright. The sum below remains the fallback for
    # documents that print no overall total.
    #
    # ...BUT ONLY IF IT IS ARITHMETICALLY A TOTAL. Live run 2026-08-12 stamped
    # $2,991 - the Commercial Auto LINE premium - because that figure appeared
    # twice in the package and `_merge_list_fields` ranks on
    # `log1p(freq) + confidence`, so two sightings of a line premium beat one
    # sighting of the real $10,663 total. The extraction prompt already says
    # "never a single coverage part's premium"; the model got it wrong anyway,
    # so the check has to be here.
    #
    # The test below is a VALIDITY constraint, not a preference: a total cannot
    # be smaller than any SINGLE one of the lines it totals. That distinction is
    # the whole lesson of C23, where "the bigger figure wins" was a preference
    # dressed as a rule and put umbrella limits in GL boxes. Nothing here ever
    # PICKS a larger number - it refuses one that is arithmetically impossible.
    #
    # THE FLOOR IS THE LARGEST SINGLE LINE, NEVER THE SUM. Using the sum was
    # tried on 2026-08-12 and REGRESSED a correct value on the client's own
    # package: the dec page states $10,663, `coverage_lines` carried a duplicate
    # line (page 4 of that run prints the same policy numbers across the GL,
    # Property AND Other columns), the sum came to $12,822, and the guard
    # replaced a CORRECT stated total with an inflated one - a figure the client
    # had explicitly listed among the things the pipeline got right.
    #
    # A sum is only as trustworthy as the line list, and this line list is
    # measurably not trustworthy enough to overrule a printed figure. A single
    # line premium is different in kind: whatever else is wrong with the list, a
    # real total cannot be smaller than one real component of it. That is the
    # only comparison here that survives a duplicated or mis-parsed line, so it
    # is the only one used.
    stated = _fv(facts, "total_policy_premium")
    _stated_txt = str(stated).strip() if stated is not None else ""
    if _stated_txt and _is_currency_value(_stated_txt):
        _stated_amt = _currency_to_int(_stated_txt)
        _largest_line = _largest_line_premium(facts)
        # EQUALITY is impossible too, once the package has two or more priced
        # lines. Live run fr1 (2026-08-12): the box stamped $3,954 - the GL
        # LINE premium, byte-equal to the largest line - because the floor
        # only rejected values strictly BELOW it. A one-line package's total
        # legitimately equals its only line, so equality stays valid there.
        _impossible = bool(_stated_amt and _largest_line) and (
            _stated_amt < _largest_line
            or (_stated_amt == _largest_line
                and _positive_granted_line_count(facts) >= 2)
        )
        if _impossible:
            # The stated figure is arithmetically not a total. Fall back to the
            # sum ONLY if the line list is trustworthy enough to build one -
            # see _sum_of_coverage_line_premiums. When it is not, the honest
            # answer is an empty box, not a second wrong number.
            _computed = _sum_of_coverage_line_premiums(facts)
            if _computed and _computed[0] > 0:
                logger.info(
                    "estimated_total: stated %s is smaller than a SINGLE "
                    "coverage line (%s) - arithmetically that is not a package "
                    "total, using the computed sum (%s) instead",
                    _stated_txt, f"${_largest_line:,}", f"${_computed[0]:,}",
                )
                return f"${_computed[0]:,}"
            logger.warning(
                "estimated_total: stated %s is smaller than a single coverage "
                "line (%s) AND the line list cannot produce a trustworthy sum "
                "- leaving the POLICY PREMIUM box empty rather than stamping a "
                "second wrong figure",
                _stated_txt, f"${_largest_line:,}",
            )
            return None
        return _stated_txt
    lines = _fv(facts, "coverage_lines")
    if not isinstance(lines, list) or not lines:
        return _SCHED_SKIP                 # no per-line data — legacy path
    _computed = _sum_of_coverage_line_premiums(facts)
    if _computed is None:
        return None                        # incomplete — blank beats a partial sum
    _total, _ = _computed
    return f"${_total:,}" if _total > 0 else None


def _currency_to_int(text: Any) -> int:
    """Whole dollars from a currency string; 0 when there is no figure."""
    digits = re.sub(r"[^\d]", "", str(text or "").split(".")[0])
    return int(digits) if digits else 0


def _positive_granted_line_count(facts: dict) -> int:
    """How many granted coverage lines carry a premium above zero. Two or more
    means the true total strictly exceeds any single line."""
    lines = _fv(facts, "coverage_lines")
    if not isinstance(lines, list):
        return 0
    try:
        from services.extraction_service import _line_entry_grants_coverage as _grants
    except Exception:                                     # noqa: BLE001
        def _grants(_e):                                  # type: ignore
            return True
    return sum(
        1 for e in lines
        if isinstance(e, dict) and _grants(e) and _currency_to_int(e.get("premium")) > 0
    )


def _largest_line_premium(facts: dict) -> int:
    """The biggest single coverage-line premium, 0 when there is none.

    Deliberately independent of the summing logic below: it needs no
    de-duplication, so it stays usable as the sanity floor even on a line list
    too corrupted to add up. That separation is the point - the floor must
    survive exactly the conditions that make the sum untrustworthy.
    """
    lines = _fv(facts, "coverage_lines")
    if not isinstance(lines, list):
        return 0
    try:
        from services.extraction_service import _line_entry_grants_coverage as _grants
    except Exception:                                     # noqa: BLE001
        def _grants(_e):                                  # type: ignore
            return True
    return max(
        (_currency_to_int(e.get("premium"))
         for e in lines if isinstance(e, dict) and _grants(e)),
        default=0,
    )


def _canonical_lob_for(name: str) -> Optional[str]:
    """Which STANDARD line of business this `coverage_lines` name belongs to.

    THE FIX for a false positive I shipped on 2026-08-12. The trustworthiness
    check below counted distinct line NAMES per policy number, and a declarations
    page names each coverage PART separately under its line:

        Covered Autos Liability   $1,496   pol 6E7-40-02---26
        Auto Medical Payments        $35   pol 6E7-40-02---26

    Both are parts of ONE Business Auto policy (the client's dec page lists them
    under "ITEM TWO - SCHEDULE OF COVERAGES AND COVERED AUTOS"), and both share
    that policy's number correctly. Counting them as two lines made the check
    declare the list corrupt and blank the POLICY PREMIUM box on a package whose
    premium we could compute perfectly well.

    Canonicalising first is what makes the check mean what it says: two entries
    are only a contradiction when they belong to DIFFERENT lines of business.
    """
    tokens = _lob_tokens(name)
    if not tokens:
        return None
    for key, token_sets in _lob_indicator_index().items():
        if any(_tokens_describe_same_line(tokens, ts) for ts in token_sets):
            return key
    return None


def _entry_names_a_real_line(name: str) -> bool:
    """True when this `coverage_lines` name is a LINE OF BUSINESS rather than a
    coverage PART of one (UM/UIM, Comprehensive, Collision, Medical Payments...).

    Lifted verbatim out of the summing loop so the trustworthiness check and the
    sum apply the SAME definition. They diverged for one commit and it showed
    immediately: the check flagged "Business Auto" + "Uninsured Motorists"
    sharing a policy number as corruption, when a coverage part sharing its
    line's policy number is the normal, correct shape.
    """
    doc_tokens = _lob_tokens(name)
    fits_standard = bool(doc_tokens) and any(
        _tokens_describe_same_line(doc_tokens, ts)
        for token_sets in _lob_indicator_index().values() for ts in token_sets
    )
    if fits_standard:
        return True
    toks = [w for w in re.findall(r"[a-z0-9]+", (name or "").lower())
            if len(w) >= 3 and w not in _COVERAGE_PART_GENERIC]
    return not (toks and all(t in _coverage_part_vocab() for t in toks))


def _line_list_is_trustworthy(lines: List[dict]) -> bool:
    """False when the extracted line list cannot be summed safely.

    THE SIGNAL, taken from the client's real session (2026-08-12) rather than
    invented. Extraction attached ONE policy number - "6 C 7 - 4 0 - 0 2---26",
    the inland-marine policy, spaced out by OCR - to FOUR different lines:

        Liability      $3,954   pol 6C7...      <- actually the GL policy
        Inland Marine    $300   pol 6C7...
        Automobile     $2,991   pol 6C7...      <- actually the auto policy
        Umbrella       $3,418   pol 6C7...      <- actually the umbrella policy

    The sum de-duplicates by policy number, so three real lines were discarded
    as "already counted", a coverage PART ($1,496 Covered Autos Liability under
    the auto policy) was counted as a line instead, and General Liability was
    counted TWICE - once as "Liability" here and again as "General Liability"
    under BBC7263. Result: $12,822 against a true package total of $10,663.

    A policy number carrying several DIFFERENT line names is self-evidently not
    identifying a policy, which makes it useless as a de-duplication key - and
    without a working key the sum is arbitrary. One number per line name is the
    normal, healthy shape, so this fires only on the broken one.
    """
    by_number: Dict[str, set] = {}
    for entry in lines:
        if not isinstance(entry, dict):
            continue
        raw_name = str(entry.get("line") or "").strip()
        # A coverage PART legitimately shares its line's policy number, so only
        # real lines of business are counted here (see _entry_names_a_real_line).
        if not raw_name or not _entry_names_a_real_line(raw_name):
            continue
        # ...and canonicalise, because a part is often NAMED after its own line
        # ("Covered Autos Liability", "Auto Medical Payments" are both Business
        # Auto). Comparing raw names counted those as two lines and blanked a
        # perfectly computable premium - see _canonical_lob_for.
        canonical = _canonical_lob_for(raw_name)
        if not canonical:
            continue
        number = re.sub(r"[^a-z0-9]", "", str(entry.get("policy_number") or "").lower())
        if number:
            by_number.setdefault(number, set()).add(canonical)
    for number, canon in by_number.items():
        if len(canon) > 1:
            logger.warning(
                "coverage_lines: policy number %r is attached to %d different "
                "LINES OF BUSINESS (%s) - it cannot identify a policy, so the "
                "per-line premiums cannot be de-duplicated or summed safely",
                number, len(canon), sorted(canon)[:5],
            )
            return False
    return True


def _sum_of_coverage_line_premiums(facts: dict) -> Optional[Tuple[int, int]]:
    """`(sum, largest single line)` over the REAL coverage lines, or None.

    None means "cannot produce a trustworthy sum" - no per-line data, some line
    carries no figure, or the list fails `_line_list_is_trustworthy`. A wrong
    sum is worse than nothing on a legal document.

    Extracted from `_resolve_estimated_total` so the stated-total check and the
    fallback sum are computed by ONE piece of code. Two copies of this selection
    logic - which entries are lines, which are coverage PARTS, which policy
    numbers are already counted - would drift, and the drift would be invisible.
    """
    lines = _fv(facts, "coverage_lines")
    if not isinstance(lines, list) or not lines:
        return None
    if not _line_list_is_trustworthy(lines):
        return None
    try:
        from services.extraction_service import _line_entry_grants_coverage as _grants
    except Exception:                                     # noqa: BLE001
        def _grants(_e):                                  # type: ignore
            return True
    # Extraction sometimes emits coverage PARTS (UM/UIM, Comprehensive,
    # Collision — each printed with its own charge inside the auto line) as
    # extra entries. Summing those on top of the Business Auto line premium
    # would overstate the package. Ordering matters and mirrors the Other-LOB
    # resolver: an entry matching a STANDARD line-of-business checkbox is a
    # real line and always counts; only NON-standard entries face the
    # coverage-part vocabulary test. A policy number already counted is never
    # counted twice (parts ride their line's own number).
    index = _lob_indicator_index()
    vocab = _coverage_part_vocab()
    total = 0
    counted = 0
    largest = 0
    seen_numbers: set = set()
    for entry in lines:
        if not isinstance(entry, dict) or not _grants(entry):
            continue
        name = str(entry.get("line") or "").strip()
        doc_tokens = _lob_tokens(name)
        fits_standard = bool(doc_tokens) and any(
            _tokens_describe_same_line(doc_tokens, ts)
            for token_sets in index.values() for ts in token_sets
        )
        if not fits_standard:
            toks = [w for w in re.findall(r"[a-z0-9]+", name.lower())
                    if len(w) >= 3 and w not in _COVERAGE_PART_GENERIC]
            if toks and all(t in vocab for t in toks):
                continue                   # a coverage part, not a line
        pn = re.sub(r"[^a-z0-9]", "", str(entry.get("policy_number") or "").lower())
        if pn:
            if pn in seen_numbers:
                continue                   # same policy already counted
            seen_numbers.add(pn)
        counted += 1
        amount = _currency_to_int(entry.get("premium"))
        if not amount:
            return None                    # a line without a figure — blank beats a partial sum
        total += amount
        largest = max(largest, amount)
    if counted == 0 or total <= 0:
        return None
    return total, largest


# ── Additional-interest TYPE ticks ───────────────────────────────────────────
# ACORD prints thirteen interest-type boxes (Additional Insured, Loss Payee,
# Mortgagee, Owner, Trustee, ...) and a party holds ONE of them. Live run on
# the graded fixture: a document naming exactly one Loss Payee produced three
# ticks - Additional Insured, Loss Payee AND Owner - because each box was an
# independent gap-fill guess with no notion of the others.
#
# When extraction captured which interest this is, the family is owned: that
# box ticks and its twelve siblings are authoritative blanks. No such fact and
# the resolver steps aside, so a document with an interest type we do not model
# keeps its existing coverage. Scoped to row A, the row the `loss_payee_name`
# rule seeds; ACORD 45 carries further interests.
_ADDL_INTEREST_TYPE_RE = re.compile(
    r"^AdditionalInterest_Interest_(\w+)Indicator_([A-N])$")
_INTEREST_TYPE_FACTS: Tuple[Tuple[str, str], ...] = (
    ("loss_payee_name", "LossPayee"),
    ("mortgagee_name",  "Mortgagee"),
)


def _resolve_additional_interest_type(field_name: str, facts: dict):
    m = _ADDL_INTEREST_TYPE_RE.match(field_name)
    if not m or m.group(2) != "A":
        return _SCHED_SKIP
    known: Optional[str] = None
    for fact_key, token in _INTEREST_TYPE_FACTS:
        val = _fv(facts, fact_key)
        if val is not None and str(val).strip():
            known = token
            break
    if known is None:
        return _SCHED_SKIP
    return "Yes" if m.group(1) == known else None


# ── Status of transaction (Policy_Status_* family) ───────────────────────────
# On a live run BOTH "Issue Policy" and "Renew" were ticked, plus a stray
# "12:01 A.M." in the status TIME box — the model reading policy-inception
# boilerplate into transaction-status fields. The dec page states the one fact
# that decides this family: it is a RENEWAL ("RENEWAL OF NUMBER ..."), captured
# as `is_renewal`. When that fact is affirmative the family is owned: Renew is
# ticked and every sibling (Quote/Issue/Bound/Change/Cancel/New/AssignedRisk,
# their date/time/AM/PM boxes) is an authoritative blank. When is_renewal is
# not affirmatively known the resolver steps aside and the legacy path runs.
_POLICY_STATUS_RE = re.compile(r"^Policy_Status_\w+_[A-N]$")


def _resolve_policy_status(field_name: str, facts: dict):
    if not _POLICY_STATUS_RE.match(field_name):
        return _SCHED_SKIP
    # The transaction TIME boxes are owned unconditionally. The only time a
    # declarations page prints is the POLICY's inception hour ("12:01 A.M.
    # Standard Time at the mailing address of the Named Insured") - a
    # different concept from "the time this transaction takes effect", and
    # observed being lifted verbatim into these boxes on two live runs, AM
    # tick included. No document can state a transaction time we have not
    # transacted yet.
    if "EffectiveTime" in field_name:
        return None
    is_ren = str(_fv(facts, "is_renewal") or "").strip().lower()
    if "RenewIndicator" in field_name:
        return "Yes" if is_ren in ("yes", "true", "y", "renewal") else None
    # ── THE WHOLE FAMILY IS OURS, and non-determinism is what proved it ──────
    # The owner ran the SAME declarations package through TWO accounts: ISSUE
    # POLICY came back ticked on one and blank on the other. A document cannot
    # produce two answers; a model asked an unanswerable question can.
    #
    # STATUS OF TRANSACTION says what THIS SUBMISSION is - a quote request, an
    # issue-policy request, a renewal, a change, a cancellation - and that is a
    # decision the producer makes when they send it. A bound policy's
    # declarations page has no opinion on it, so every box here is
    # unanswerable from the document and every value in one is a guess.
    # Same category as "section attached" and REMARKS / PROCESSING
    # INSTRUCTIONS, and closed the same way: silence means EMPTY, and the
    # producer ticks the box.
    #
    # Previously this returned _SCHED_SKIP for a non-renewal, which left the
    # family unowned and handed it straight back to gap fill.
    return None


# ── Address line-two: owned by the parsed address fact ──────────────────────
# LineOne carries the full parsed street (unit included). LineTwo had no owner,
# fell to gap fill, and the model re-wrote the unit number already sitting at
# the end of LineOne — "# D13" printed twice on two separate live runs (once in
# the premises block, once in the Named Insured block). When the party's own
# address fact exists, LineTwo is owned: the parsed line2 when the address has
# a separate unit segment, an authoritative blank otherwise. No address fact ->
# resolver steps aside and gap fill keeps its coverage.
_ADDRESS_LINE_TWO_RE = re.compile(
    r"^NamedInsured_(MailingAddress|PhysicalAddress)_LineTwo_A$")


def _resolve_address_line_two(field_name: str, facts: dict):
    m = _ADDRESS_LINE_TWO_RE.match(field_name)
    if not m:
        return _SCHED_SKIP
    kind = m.group(1)
    if kind == "PhysicalAddress":
        fact = _fv(facts, "physical_address") or _fv(facts, "mailing_address")
    else:
        fact = _fv(facts, "mailing_address")
    if fact is None or not str(fact).strip():
        return _SCHED_SKIP
    from utils.helpers import _parse_address
    parsed = _parse_address(str(fact))
    if not (parsed.get("line1") or "").strip():
        return _SCHED_SKIP
    line2 = (parsed.get("line2") or "").strip()
    return line2 or None


# ── Producer mailing block: owned by the producer_address fact ──────────────
# The producer's street boxes had no deterministic source (`_addr_*` is scoped
# to the Named Insured), so the whole block rode gap fill. Graded test run:
# LineOne came back as street + suite in one string while the parsed suite
# ALSO landed on line two — "Ste 210" printed twice. When the producer_address
# fact exists, the block is owned by its parse: each component stamps from the
# same decomposition, so a duplicate is structurally impossible. No fact — the
# resolver steps aside and gap fill keeps its coverage.
_PRODUCER_MAILING_RE = re.compile(
    r"^Producer_MailingAddress_(LineOne|LineTwo|CityName|StateOrProvinceCode|PostalCode)_A$")
_PRODUCER_MAILING_PART = {
    "LineOne": "line1", "LineTwo": "line2", "CityName": "city",
    "StateOrProvinceCode": "state", "PostalCode": "zip",
}


def _resolve_producer_mailing(field_name: str, facts: dict):
    m = _PRODUCER_MAILING_RE.match(field_name)
    if not m:
        return _SCHED_SKIP
    fact = _fv(facts, "producer_address")
    if fact is None or not str(fact).strip():
        return _SCHED_SKIP
    from utils.helpers import _parse_address
    parsed = _parse_address(str(fact))
    if not (parsed.get("line1") or "").strip():
        return _SCHED_SKIP
    val = (parsed.get(_PRODUCER_MAILING_PART[m.group(1)]) or "").strip()
    return val or None


# ── Applicant contact block: owned by the applicant's own contact facts ──────
# The extraction pass reads the WHOLE document under entity discipline
# (RULE 15) and captures the applicant's contact person when one is stated. If
# that full-context pass found NO applicant contact, the only contacts a
# field-level gap fill can find are OTHER parties' — and that is exactly what
# every live run produced: the producer's name/phones, "Claim Reporting:
# (888) 362-2255" and "Servicing Carrier: (720) 200-3700" in the applicant's
# contact block, then contact type "Producer" / "Agent Phone" with the claims
# number in a phone box on the two runs after the prompt-side rule. A prompt
# asks; this resolver decides: no applicant contact fact -> the whole family is
# an authoritative blank, routed to the client questionnaire.
_APPLICANT_CONTACT_RE = re.compile(r"^NamedInsured_Contact_\w+_[A-N]$")


def _resolve_applicant_contact(field_name: str, facts: dict):
    if not _APPLICANT_CONTACT_RE.match(field_name):
        return _SCHED_SKIP
    for key in ("contact_name", "contact_phone", "contact_email"):
        val = _fv(facts, key)
        if val is not None and str(val).strip():
            return _SCHED_SKIP        # a real applicant contact exists — normal paths run
    return None


# ── "Other" line-of-business rows (ACORD 125 LOB grid) ──────────────────────
# The free-text "Other" rows exist for coverage lines that have NO standard
# checkbox on the form. Left to gap fill, the model filled them with lines that
# (a) DO have a standard checkbox ("Commercial Auto", "Commercial Liability
# Umbrella" — duplicating the ticked Business Auto / Umbrella boxes) and
# (b) lines the dec page explicitly declares NOT covered ("Property", "Crime
# and Fidelity", "Workers' Compensation" from a page printing "NO COVERAGE"
# beside them) — both reported by the client on the same live form.
#
# This resolver OWNS the family whenever per-line data exists: row i is filled
# from the i-th `coverage_lines` entry that both GRANTS coverage
# (`_line_entry_grants_coverage` — a premium or limit, the same evidence bar
# the declared-absent downgrade uses) and matches NO standard LOB checkbox
# across the 17 schemas (`_lob_indicator_index` token sets — the same wording
# source `_standard_lob_box_for` reads). Everything else is an authoritative
# blank: a line with its own checkbox belongs in that checkbox, and a line
# without grant evidence belongs nowhere. When no `coverage_lines` fact exists
# at all the resolver steps aside (_SCHED_SKIP) so legacy behaviour — and its
# coverage — is unchanged.
_OTHER_LOB_RE = re.compile(
    r"^Policy_LineOfBusiness_Other(Indicator|LineOfBusinessDescription)_([A-N])$")


# Words too generic to distinguish a coverage part from a line of business.
_COVERAGE_PART_GENERIC = frozenset({
    "coverage", "deductible", "limit", "amount", "code", "indicator", "each",
    "per", "policy", "form", "line", "business", "the", "and", "for", "date",
    "description", "identifier", "number", "total", "liability", "insurance",
    "commercial", "other", "symbol",
})


@lru_cache(maxsize=1)
def _coverage_part_vocab() -> frozenset:
    """Vocabulary of COVERAGE-PART words, derived from ACORD's own schemas.

    A declarations page prints a premium beside coverage FEATURES inside a line
    (Uninsured Motorists, Underinsured Motorists, Comprehensive, Collision,
    Medical Payments, Hired/Non-Owned, ...). Extraction sometimes emits those
    as `coverage_lines` entries, and on a live run they were then stamped into
    ACORD 125's "Other line of business" rows — coverage parts of the Business
    Auto line presented as four extra lines of business. The words that name
    such parts are exactly the words ACORD uses in its own coverage / limit /
    deductible / symbol FIELD NAMES across the 17 schemas, so the vocabulary is
    derived from there — no hand-kept list, and it grows with the schemas."""
    vocab: set = set()
    try:
        schemas = _all_form_schemas()
    except Exception:                                     # noqa: BLE001
        return frozenset()
    camel = re.compile(r"[A-Z]+(?=[A-Z][a-z])|[A-Z]?[a-z]+|[A-Z]+|\d+")
    for schema in schemas.values():
        for fname in schema:
            if not any(k in fname for k in ("Coverage", "Deductible", "Limit", "Symbol")):
                continue
            for word in camel.findall(fname):
                w = word.lower()
                if len(w) >= 3 and w not in _COVERAGE_PART_GENERIC:
                    vocab.add(w)
    return frozenset(vocab)


def _other_lob_row_names(facts: dict) -> Optional[List[str]]:
    """Names of granted coverage lines that fit no standard LOB checkbox, in
    document order; None when there is no per-line data to reason from."""
    lines = _fv(facts, "coverage_lines")
    if not isinstance(lines, list) or not lines:
        return None
    try:
        # Lazy: lives in the extraction layer; same evidence bar as the
        # declared-absent downgrade. If unavailable, treat every named line as
        # granted rather than silently blanking the family.
        from services.extraction_service import _line_entry_grants_coverage
    except Exception:                                     # noqa: BLE001
        def _line_entry_grants_coverage(_e):              # type: ignore
            return True
    index = _lob_indicator_index()

    def _norm_pn(entry: dict) -> str:
        return re.sub(r"[^a-z0-9]", "", str(entry.get("policy_number") or "").lower())

    def _fits_standard(name: str) -> bool:
        doc = _lob_tokens(name)
        return bool(doc) and any(
            _tokens_describe_same_line(doc, ts)
            for token_sets in index.values()
            for ts in token_sets
        )

    # Pass 1: policy numbers of granted STANDARD lines. A coverage part
    # printed against a line shares that line's policy number — a distinct
    # line of business has its own.
    standard_numbers: set = set()
    for entry in lines:
        if isinstance(entry, dict) and _line_entry_grants_coverage(entry):
            name = str(entry.get("line") or "").strip()
            if name and _fits_standard(name):
                pn = _norm_pn(entry)
                if pn:
                    standard_numbers.add(pn)

    vocab = _coverage_part_vocab()
    rows: List[str] = []
    for entry in lines:
        if not isinstance(entry, dict):
            continue
        name = str(entry.get("line") or "").strip()
        if not name or not _line_entry_grants_coverage(entry):
            continue
        doc = _lob_tokens(name)
        if not doc:
            continue
        if _fits_standard(name):
            continue
        # A coverage PART, not a line: every significant word of its name is
        # coverage-feature vocabulary ("Uninsured Motorists", "Comprehensive",
        # "Collision", "Medical Payments"), or it rides a standard line's own
        # policy number. Either signal excludes it; a genuine odd line
        # ("Employment Practices Liability") carries words of its own.
        toks = [w for w in re.findall(r"[a-z0-9]+", name.lower())
                if len(w) >= 3 and w not in _COVERAGE_PART_GENERIC]
        if toks and all(t in vocab for t in toks):
            continue
        pn = _norm_pn(entry)
        if pn and pn in standard_numbers:
            continue
        if name not in rows:
            rows.append(name)
    return rows


def _resolve_other_lob_row(field_name: str, facts: dict):
    m = _OTHER_LOB_RE.match(field_name)
    if not m:
        return _SCHED_SKIP
    rows = _other_lob_row_names(facts)
    if rows is None:
        return _SCHED_SKIP                 # no per-line data — legacy path
    attr, letter = m.group(1), m.group(2)
    idx = _ROW_LETTER_TO_IDX[letter]
    if idx >= len(rows):
        return None                        # authoritative blank
    return "Yes" if attr == "Indicator" else rows[idx]


# ── "… Section is attached to this application" ──────────────────────────────
# Every `Policy_SectionAttached_*Indicator` box asserts something about the
# SUBMISSION WE ARE PRODUCING, not about the carrier's declarations page. Four
# of the eight have an  entry (builders risk, open cargo,
# vehicle schedule, driver schedule). The other four - Electronic Data
# Processing, Glass and Sign, Dealers, Accounts Receivable / Valuable Papers -
# had no rule, so they fell through to gap fill, where the model saw "Electronic
# Data Processing" printed on an inland-marine schedule and ticked the box. That
# is exactly the mention-versus-grant error one level up: a coverage being
# mentioned is not an ACORD supplemental section being attached to our package.
#
# No model can know what we attached. Unmapped members of the family resolve to
# an authoritative blank; mapped ones defer to their rule, so wiring a new
# section later needs nothing here.
_SECTION_ATTACHED_RE = re.compile(r"^Policy_SectionAttached_\w+Indicator_[A-N]$")


def _resolve_section_attached_indicator(field_name: str, facts: dict):
    if not _SECTION_ATTACHED_RE.match(field_name):
        return _SCHED_SKIP
    base = field_name.rsplit("_", 1)[0]
    if base in _INDICATOR_RULES:
        return _SCHED_SKIP                 # a deterministic rule owns this box
    return None


# ── A schedule row LABEL is not the name of a party ──────────────────────────
# Live 2026-08-13. ACORD 125's ADDITIONAL INTEREST block, on a policy that has no
# additional interest, came back as five boxes from four different documents:
#
#   NAME AND ADDRESS      Location 000
#                         Denver    CO 80216-3121 US     <- the INSURED's own city
#   ITEM CLASS            Limited
#   ITEM DESCRIPTION      2012 SUBARU OUTBACK SEDAN VII  <- the insured's own car
#   REASON FOR INTEREST   Location 000: Limited Pollution Coverage - Work Sites
#
# WHY THE EXISTING GUARDS MISSED IT, checked rather than guessed.
# `_drop_third_party_address_bleed` compares the insured's address to a third
# party's on the STREET LINE ONLY - deliberately, because a real mortgagee can
# share the insured's city, state and ZIP. Here the street box is empty and only
# the city and postcode are filled, so it had nothing to match. Widening it to
# city/ZIP would start deleting genuine lenders, which is a worse trade.
#
# So the NAME is the signal. "Location 000" is a schedule row key - the label a
# dec page prints above a block, e.g. "Location 001: Contractors - Executive
# Supervisors". It is not, and cannot be, the legal name of a party with an
# interest in the risk.
#
# ANCHORED END TO END, which is the whole safety case. It matches a bare label
# plus an ordinal and nothing else: "Building 19 Holdings LLC" does not match,
# "Location Services Inc" does not match, "Item 4 Trust" does not match. To be
# wrong it would have to blank a company whose entire registered name is
# "Location 000".
#
# Blanking the NAME is enough on its own: the row becomes unanchored and the
# existing orphan sweep (`_unanchored_entity_row_fields`) clears the address,
# item class and reason with it, so the block empties together instead of leaving
# debris behind a deleted name.
_ROW_LABEL_NAME_RE = re.compile(
    r"^(?:location|loc|item|building|bldg|premises|prem|vehicle|veh|unit|"
    r"schedule|line|row|class)\s*#?\s*\d{1,4}$", re.I)

# A driver's personal identity/licensing columns, harvested from the real
# ACORD 127 schema (GenderCode, MaritalStatusCode, BirthDate, LicensedYear,
# LicenseNumberIdentifier, TaxIdentifier, LicensedStateOrProvinceCode,
# HiredDate, ExperienceYearCount). Coverage columns (Driver_Coverage_*) are
# deliberately NOT here - the DOC code is legitimately derived from the
# endorsement that names the driver.
_DRIVER_PERSONAL_COLUMN_RE = re.compile(
    r"^Driver_(?:GenderCode|MaritalStatusCode|BirthDate|LicensedYear|"
    r"LicenseNumberIdentifier|TaxIdentifier|LicensedStateOrProvinceCode|"
    r"HiredDate|ExperienceYearCount)_[A-N]$")
# NOT an authoritative-blank resolver, and that distinction matters: an
# additional interest with a real name is perfectly legitimate, so this box must
# stay reachable by gap fill. It is a POST-FILL guard, which is the only point
# where the produced VALUE exists to be judged.
_INTEREST_NAME_RE = re.compile(r"^AdditionalInterest\w*_FullName_[A-N]$")


# ── A value that is the truncated head of one we already hold ────────────────
# Live 2026-08-13: DESCRIPTION OF OPERATIONS OF OTHER NAMED INSUREDS came back
# "COMMERCIAL GENERAL CONTRA" - the carrier's own field is too narrow and prints
# the business description cut off mid-word on every dec page. Extraction had
# ALREADY judged it, verbatim from the merge log:
#
#   narrative partition: chose 'Contractors - executive supervisors...'
#   (a complete statement) over 'COMMERCIAL GENERAL CONTRA' (a 25-char fragment
#   seen 4 time(s)) - repetition of a truncated header is not quality
#
# That judgement is not persisted anywhere gap fill can see it, so the fragment
# came back through a different door and landed in a different box.
#
# THE RULE IS PREFIX CONTAINMENT, not "unnamed subject". The first attempt
# anchored this on the other named insured being unnamed, and that was too broad:
# a genuinely different row-B narrative survives by prior decision even when the
# name is missing, because extraction can find operations and miss a name. What
# is actually wrong with this value is that it is the truncated HEAD of a value
# we already hold in full - `contractor_type` is "COMMERCIAL GENERAL CONTRACTOR".
#
# Bounded three ways, because a short prefix coincidence is real:
#   * narrative/description fields only - never a code, an amount or a name;
#   * >= 20 characters, so "Roofing" ⊂ "Roofing and siding" is out of scope;
#   * the longer value must exceed it by >= 3 characters, so a formatting
#     difference of one trailing character is not read as truncation.
_TRUNCATED_COPY_MIN_CHARS = 20
_NARRATIVE_FIELD_TOKENS = ("Description", "Remark", "Narrative", "Explanation")


def _is_truncated_copy_of_a_held_value(
    field_name: str, value: Any, mapped: dict, facts: dict,
) -> Optional[str]:
    """The fuller value this one is a truncated head of, or None."""
    if not any(tok in (field_name or "") for tok in _NARRATIVE_FIELD_TOKENS):
        return None
    text = str(value or "").strip()
    if len(text) < _TRUNCATED_COPY_MIN_CHARS:
        return None
    needle = _normalize_for_search(text)
    if not needle:
        return None
    candidates = [v for k, v in (mapped or {}).items() if k != field_name]
    for _k, _v in (facts or {}).items():
        if isinstance(_v, dict) and "value" in _v:
            _v = _v.get("value")
        if isinstance(_v, str):
            candidates.append(_v)
    for other in candidates:
        hay = _normalize_for_search(str(other or ""))
        if len(hay) >= len(needle) + 3 and hay.startswith(needle):
            return str(other)
    return None


def _is_row_label_not_a_name(field_name: str, value: Any) -> bool:
    """True when an entity NAME box holds a schedule row label."""
    if not _INTEREST_NAME_RE.match(field_name or ""):
        return False
    return bool(_ROW_LABEL_NAME_RE.match(str(value or "").strip()))


# ── A FAX NUMBER nobody printed ──────────────────────────────────────────────
# Three consecutive live runs stamped the producer's PHONE (303-996-7800) into
# the FAX box. The duplicate guard could not settle it (both boxes gap-filled ->
# nobody to blame), and the walk semantics made it inevitable: the batch's last
# remaining field was the fax, so the loop hunted chunk after chunk until the
# model produced the only phone-shaped thing the package prints. A dec package
# that states a fax states it labelled "Fax"; extraction captures that as
# `producer_fax`. When no such fact exists there is NO document source for this
# box - the same reasoning, and the same solution shape, as
# `_resolve_applicant_website` (five runs of carrier/government URLs) one
# resolver up.
_PARTY_FAX_RE = re.compile(r"^\w+_FaxNumber_[A-N]$")


def _resolve_party_fax(field_name: str, facts: dict):
    if not _PARTY_FAX_RE.match(field_name or ""):
        return _SCHED_SKIP
    if field_name.startswith("Producer"):
        fax = _fv(facts, "producer_fax")
        if not fax:
            return None
        # THE FOURTH ROUND OF THIS DEFECT, and the door it came through this
        # time: extraction itself. Making the box resolver-owned stopped gap
        # fill, and the next run printed the phone AGAIN - because call 1 had
        # filed "Agent Phone: 303-996-7800" under `producer_fax`, and this
        # resolver trusted the fact. A "fax" that is digit-identical to the
        # party's PHONE is a mislabel, whoever produced it: nobody's fax IS
        # their voice line on a dec page that prints only one number.
        fax_digits = re.sub(r"\D", "", str(fax))
        if not fax_digits:
            return None
        # Compare against EVERY phone-bearing fact, not a hand-list of two.
        # Run 6 nearly re-taught the same lesson: if the specific phone key
        # this checked happened not to be captured that run, the mislabelled
        # fax sailed through on a technicality.
        for key, val in (facts or {}).items():
            if "phone" not in str(key).lower():
                continue
            if isinstance(val, dict) and "value" in val:
                val = val.get("value")
            if val and re.sub(r"\D", "", str(val)) == fax_digits:
                logger.info(
                    "party_fax: rejected %r - digit-identical to %s; a fax that "
                    "is the phone is a mislabel", str(fax)[:20], key,
                )
                return None
        return fax
    # Other parties' fax numbers come only from their own records (schedule
    # rows, producer/ARQ input), which stamp via their own resolvers upstream.
    return None


# ── The DEPOSIT box, same disease ────────────────────────────────────────────
# Run 3 stamped the package TOTAL ($10,663) as the deposit; run 5 stamped $31 -
# the TERRORISM PREMIUM, the only other small money figure in the index. The
# walk hunts until the last empty field in a batch finds a money-shaped value,
# and this package states no deposit anywhere. Resolver-owned: stamps from a
# deposit fact when extraction genuinely captures one, blank otherwise.
_PAYMENT_DEPOSIT_RE = re.compile(r"^\w+_Payment_DepositAmount_[A-N]$")


def _resolve_payment_deposit(field_name: str, facts: dict):
    if not _PAYMENT_DEPOSIT_RE.match(field_name or ""):
        return _SCHED_SKIP
    for key in ("deposit_amount", "premium_deposit"):
        val = _fv(facts, key)
        if val and str(val).strip():
            return str(val).strip()
    return None


# ── The PAYMENT PLAN box, same disease a third time ──────────────────────────
# Every 2026-08-14 run stamped "AN" - a code the model derives from "Audit
# Period: Annual", which is the GL's AUDIT term, not a payment plan. This
# package prints no payment plan anywhere, and an installment plan can never
# be inferred from a dec page that does not state one; no verbatim check can
# catch the invention either, because a CODE is an abbreviation of a printed
# word ("Annual" is genuinely printed - about the audit). Fact-or-blank, like
# the deposit and fax: `payment_plan` (asked for by extraction since
# 2026-08-14) stamps when a document genuinely prints one ("Payment Plan:
# Monthly"); otherwise the box stays EMPTY for the producer.
_PAYMENT_SCHEDULE_RE = re.compile(
    r"^\w+_Payment_(?:PaymentScheduleCode|PaymentPlanCode)_[A-N]$")


def _resolve_payment_schedule(field_name: str, facts: dict):
    if not _PAYMENT_SCHEDULE_RE.match(field_name or ""):
        return _SCHED_SKIP
    for key in ("payment_plan", "payment_schedule"):
        val = _fv(facts, key)
        if val and str(val).strip():
            return str(val).strip()
    return None


# ── MAXIMUM DOLLAR VALUE SUBJECT TO LOSS is arithmetic, not a limit ──────────
# Run 9's ACORD 127 printed $1,000,000 - the Auto LIABILITY limit. ACORD's own
# tooltip: "the highest value that the insurer would be subject to if a major
# automobile loss occurred". That is a property-damage EXPOSURE: the value of
# the vehicles that could burn in one garage, not what the liability policy
# pays a third party. The package's one vehicle is worth $26,680.
#
# Derived, never guessed: the sum of the scheduled vehicles' cost-new figures.
# No vehicle schedule, or no cost figures in it, means the box stays EMPTY and
# the producer supplies it - the same shape as the deposit and fax resolvers.
_MAX_VEHICLE_EXPOSURE_RE = re.compile(
    r"^CommercialVehicleLineOfBusiness_MaximumExposureAllVehiclesAmount_[A-N]$")


def _resolve_max_vehicle_exposure(field_name: str, facts: dict):
    if not _MAX_VEHICLE_EXPOSURE_RE.match(field_name or ""):
        return _SCHED_SKIP
    rows = _fv(facts, "auto_vin_schedule")
    if not isinstance(rows, list) or not rows:
        return None
    total = 0.0
    seen = False
    for row in rows:
        if not isinstance(row, dict):
            continue
        for key in ("cost_new", "cost_new_amount", "value"):
            raw = row.get(key)
            if raw is None or not str(raw).strip():
                continue
            digits = re.sub(r"[^\d.]", "", str(raw))
            if digits:
                try:
                    total += float(digits)
                    seen = True
                except ValueError:                            # pragma: no cover
                    pass
            break
    if not seen or total <= 0:
        return None
    return f"${total:,.0f}"


# ── EXPOSURE COUNTS come from an exposure fact or not at all ─────────────────
# Run 9's ACORD 126 printed "# FULL-TIME STAFF 1 / # PART-TIME STAFF 0" on a
# package whose ground truth carries no employee data anywhere - while the
# ACORD 125's equivalent boxes were correctly blank, which is the tell: two
# boxes asking the identical question, one honest and one invented, because
# only one of them had an owning resolver. An employee count drives rating; a
# fabricated one is a misrepresentation, and "0 part-time staff" reads as a
# positive assertion rather than an absence.
# SCOPED TO `Contractors_*` ON PURPOSE, and the test suite is why. The first
# cut matched every *EmployeeCount field and broke three pinned behaviours on
# ACORD 125's `BusinessInformation_*` boxes: the `num_employees_part_time`
# fact, the per-location schedule breakdown that must beat the scalar, and the
# rule that row B stays blank when the schedule is short. Those boxes were
# already correct on run 9 - blank, honestly - because they have working
# schedule logic. ACORD 126's Contractors staff boxes are the ones with no
# owner, and they are the ones that invented "1 full-time / 0 part-time".
_EXPOSURE_COUNT_FIELDS = {
    "FullTimeEmployeeCount": ("full_time_employees", "num_employees_full_time"),
    "PartTimeEmployeeCount": ("part_time_employees", "num_employees_part_time"),
}
_EXPOSURE_COUNT_RE = re.compile(
    r"^Contractors_(FullTimeEmployeeCount|PartTimeEmployeeCount)_[A-N]$")


def _resolve_exposure_count(field_name: str, facts: dict):
    m = _EXPOSURE_COUNT_RE.match(field_name or "")
    if not m:
        return _SCHED_SKIP
    for key in _EXPOSURE_COUNT_FIELDS[m.group(1)]:
        val = _fv(facts, key)
        if val is not None and str(val).strip():
            return str(val).strip()
    return None


# ── CLAIMS-MADE dates on an OCCURRENCE policy ────────────────────────────────
# Run 9, ACORD 126: PROPOSED RETROACTIVE DATE and ENTRY DATE INTO UNINTERRUPTED
# CLAIMS MADE COVERAGE both stamped 07/15/2025 - the policy EFFECTIVE date -
# on a package whose GL is the occurrence form (CG 00 01). A retroactive date
# is a claims-made concept; an occurrence policy does not have one, so any
# value in these boxes is fabricated by construction. This is also the
# client's standing rule made structural: "a policy effective date must never
# be repurposed as an occurrence, loss, violation or incident date."
#
# Keyed on the extraction flag, not the value: `gl_is_claims_made` truthy means
# the section is real and the normal flow (gap fill included) may fill it;
# anything else means the boxes stay EMPTY and the producer asks. Scoped to
# GeneralLiability_* so an umbrella written claims-made keeps its own dates.
_CLAIMS_MADE_DATE_RE = re.compile(
    r"^GeneralLiability\w*_(?:\w+_)?(?:ProposedRetroactiveDate|"
    r"UninterruptedCoverageEntryDate|RetroactiveDate)_[A-N]$")


def _resolve_claims_made_dates(field_name: str, facts: dict):
    if not _CLAIMS_MADE_DATE_RE.match(field_name or ""):
        return _SCHED_SKIP
    if facts.get("gl_is_claims_made"):
        return _SCHED_SKIP                     # real claims-made: normal flow
    return None


# ── LOSS-HISTORY SUMMARY: never attested without evidence ────────────────────
# Run 9, ACORD 125: TOTAL LOSSES = $0 with "Check if none" unchecked, on a
# package with no loss runs and no no-loss assertion. The client's rule for
# the checkbox (2026-08-12, _resolve_no_loss_checkbox_owned) applies to the
# whole summary row for the same reason: "$0 total losses" IS a clean-history
# attestation, and "require client confirmation and preferably currently
# valued loss runs" covers the number as much as the tick. With a real signal
# (the document asserts no losses, or actual loss entries exist) the normal
# flow fills; with silence the boxes stay empty and the ARQ asks.
_LOSS_SUMMARY_FIELD_RE = re.compile(
    r"^LossHistory_(?:TotalAmount|InformationYearCount)_[A-N]$")


def _resolve_loss_history_summary(field_name: str, facts: dict):
    if not _LOSS_SUMMARY_FIELD_RE.match(field_name or ""):
        return _SCHED_SKIP
    if facts.get("asserts_no_known_losses"):
        return _SCHED_SKIP
    hist = _fv(facts, "loss_history")
    if isinstance(hist, list) and any(hist):
        return _SCHED_SKIP
    return None


# ── REMARKS / PROCESSING INSTRUCTIONS is about OUR submission ────────────────
# Same reasoning as the "Section attached" boxes above, and the same live source:
# nobody can read this off the carrier's policy, because it is not about the
# carrier's policy. ACORD prints it as "REMARKS / PROCESSING INSTRUCTIONS" - what
# the producer wants the underwriter to DO with this application.
#
# Two live runs, two different kinds of wrong text, same box:
#   2026-08-13a  "YOU MAY HAVE THE OPTION TO REJECT THIS TERRORISM COVERAGE"
#                (the IL8384A disclosure notice)
#   2026-08-13b  "Policy: BBC7263 - 26; ... Forms Applicable: CG0001(04/13),
#                CG0069(12/23), ... " - 36 form codes, a forms schedule
# The second is not even wrong in an interesting way: it is a faithful
# transcription of the dec page into a box that does not ask for one.
#
# A DENSITY RULE WAS CONSIDERED AND REJECTED - "a narrative dominated by form
# codes is a forms schedule". It would have caught this run and left the next
# phrasing open, and worse, a genuine remark referencing endorsements ("CG 20 10
# additional insured attached per contract") is ordinary broker practice, so any
# threshold trades real remarks for boilerplate. The box has no legitimate source
# in a bound policy at all, which is a stronger and simpler statement.
#
# NOT AN ACORD 101 REGRESSION, checked rather than assumed: the overflow feature
# (`_compose_acord101_remarks`) reads the FACTS `acord101_remarks` and
# `additional_remarks_text`, never this field, so 101's Additional Remarks rows
# are unaffected. And this is gap-fill scope only - a producer or ARQ answer that
# genuinely writes remarks still stamps, because those arrive as facts.
_REMARK_TEXT_RE = re.compile(r"^\w*_?RemarkText_[A-N]$")


def _resolve_remark_text(field_name: str, facts: dict):
    """Authoritative blank for the general REMARKS box - unless we hold a remark
    fact of our own, which is the only legitimate source."""
    if not _REMARK_TEXT_RE.match(field_name):
        return _SCHED_SKIP
    # ACORD 101 IS the additional-remarks form; its rows are stamped by
    # `_stamp_acord101_remarks` from the composed blocks and must not be
    # intercepted here.
    if field_name.startswith("AdditionalRemark_"):
        return _SCHED_SKIP
    for key in ("acord101_remarks", "additional_remarks_text"):
        val = _fv(facts, key)
        if isinstance(val, str) and val.strip() and _is_our_own_remark(val):
            return val.strip()
    return None


# A remark WE hold can still be the dec page read back to us - that is exactly
# how `additional_remarks_text` was filled on the 2026-08-13 run. So the fact is
# not trusted blind: a value that is mostly ISO/AAIS form codes is the carrier's
# forms schedule, not a processing instruction, whoever put it in the fact.
_FORM_CODE_ANYWHERE_RE = re.compile(r"\b[A-Z]{2}\s?\d{2,4}(?:[\s(-]\d{2}[)\s-]?){1,3}")
_REMARK_MAX_FORM_CODES = int(os.getenv("REMARK_MAX_FORM_CODES", "3"))


def _is_our_own_remark(text: str) -> bool:
    codes = _FORM_CODE_ANYWHERE_RE.findall(text or "")
    if len(codes) > _REMARK_MAX_FORM_CODES:
        logger.info(
            "remark_text: rejected a %d-char value carrying %d form codes - that "
            "is a forms schedule, not a processing instruction", len(text), len(codes),
        )
        return False
    return True


# ── The producer's printed name on the signature block ───────────────────────
# `PRODUCER'S NAME (Please Print)` sits beside the producer's signature, which is
# already non-fillable. It reads `producer_contact_name`, and when that fact is
# absent the field fell through to gap fill - where the only personal names in a
# declarations package belong to the CARRIER. Live runs produced "Scott R. Jean"
# and then "Todd A. Strother" from the same document: EMC executives named in
# policy boilerplate, and a different one each run.
#
# A signature block identifies the person signing. If we do not know who the
# producer contact is, no model may nominate one.
_PRODUCER_PRINTED_NAME_RE = re.compile(
    r"^Producer_AuthorizedRepresentative_FullName_[A-N]$")


def _resolve_producer_printed_name(field_name: str, facts: dict):
    if not _PRODUCER_PRINTED_NAME_RE.match(field_name):
        return _SCHED_SKIP
    return _fv(facts, "producer_contact_name") or None


# ── The applicant's website ──────────────────────────────────────────────────
# Five consecutive live runs put a URL in this box that has nothing to do with
# the applicant: first the CARRIER'S site, then "Http://go.cms.gov/mirnghp" - a
# US government Medicare-reporting address printed in policy boilerplate. Both
# are perfectly valid URLs, so no shape check can help, and neither matches any
# party value we hold, so the ownership guards cannot either.
#
# A declarations package almost never states the INSURED'S website. Every URL in
# it belongs to the carrier, a regulator or a form vendor. So this box reads the
# `applicant_website` fact - which RULE 15 scopes to the applicant - or stays
# empty. Blank routes it to the client questionnaire, which is the only place the
# real answer exists.
_APPLICANT_WEBSITE_RE = re.compile(r"^NamedInsured_Primary_WebsiteAddress_[A-N]$")


def _resolve_applicant_website(field_name: str, facts: dict):
    if not _APPLICANT_WEBSITE_RE.match(field_name):
        return _SCHED_SKIP
    return _fv(facts, "applicant_website") or None


def _unanchored_detail_fields(mapped: dict, schema: dict) -> set:
    """Detail boxes filled while the entity that would give them meaning is
    unnamed. A 50% ownership stake in nobody is not a fact."""
    out: set = set()
    for anchor, dependents in _ANCHORED_DETAIL_GROUPS:
        if anchor not in schema:
            continue
        if str(mapped.get(anchor) or "").strip():
            continue                       # the entity is named - keep its detail
        for field in dependents:
            if str(mapped.get(field) or "").strip():
                out.add(field)
    return out


def _unanchored_entity_row_fields(mapped: dict, schema: dict) -> set:
    """Fields sitting in a NON-PRIMARY entity row whose name box is empty.

    Client report #10: the form carried a second Named Insured with a partial
    FEIN ("84-"), an LLC tick, a member count and an address - and **no name**.
    "These are not usable records." A second insured with a tax identifier and
    no legal name is not an entity; the row is an artefact of the repeating-slot
    prompt being asked to find an Nth value that does not exist.

    Scoped deliberately:
      * ONLY rows B..N. Row A is the primary record and is never questioned.
      * ONLY the verified entity prefixes (`_FIELD_ENTITY_PREFIXES`). Grouping by
        raw name prefix instead would sweep in `CommercialStructure_*`, where a
        building row legitimately has an address and no "name".
      * ONLY when the row HAS a name box in the schema and every one of them is
        empty. A row with no name box has no anchor to test.
    Measured across all 17 schemas: 27 rows on 9 forms.

    Returns fields to DEMOTE, not to blank - the value stays on the form and
    turns orange so a broker can see and judge it.
    """
    by_row: Dict[Tuple[str, str], list] = {}
    anchors: Dict[Tuple[str, str], list] = {}
    for field in schema:
        m = _SCHED_ROW_RE.match(field)
        if not m:
            continue
        base, row = m.group(1), m.group(2)
        entity = _field_entity(base)
        if not entity:
            continue
        # Row A is the primary record for a MANDATORY entity (the Named Insured
        # always exists - the form is about them) and is never questioned there.
        # An OPTIONAL block has no such guarantee: an additional interest that
        # nobody named is not an additional interest, whatever else its row
        # carries.
        if row == "A" and entity not in _OPTIONAL_ENTITY_PREFIXES:
            continue
        by_row.setdefault((entity, row), []).append(field)
        if base.endswith("FullName"):
            anchors.setdefault((entity, row), []).append(field)

    # ── TRIED AND REVERTED 2026-08-13: clearing a NAME-ONLY optional row ──────
    # The mirror of the rule below looked obviously right and is wrong. ACORD 125
    # Q11 shipped `NAME OF TRUST: Emcasco Insurance Company` - the carrier's own
    # group company in a third-party box - inside an ADDITIONAL INTEREST block
    # that was otherwise entirely empty, so "a name with no other detail is not a
    # record" seemed to be the same structural rule that fixed the driver
    # schedule (`_schedule_has_substance`).
    #
    # It broke 5 tests, and every one of them was right. A name-only additional
    # interest is a SUPPORTED shape here: the vehicle-ownership question answers
    # itself by naming the owner in `AdditionalInterest_FullName_C` and nothing
    # else ("Meridian Fleet Leasing, LLC"), and a mortgagee named with no address
    # yet is an ordinary partial. Row shape does not separate the carrier's own
    # name from a real lender's - only IDENTITY does, and that belongs in the
    # carrier/producer ownership guard, which missed this because it matches its
    # family token `emc` by exact key and `emcasco` is a prefix, not a match.
    #
    # Do not reintroduce the row-shape version. Fixing this means deciding
    # whether a 3-character carrier family token may match by prefix - a real
    # question, with "EMCOR Group" (a genuine construction firm) as the case
    # against - and that decision needs its own evidence.
    unanchored: set = set()
    for key, fields in by_row.items():
        anchor_fields = anchors.get(key)
        if not anchor_fields:
            continue                       # no name box - nothing to anchor on
        if any(str(mapped.get(a) or "").strip() for a in anchor_fields):
            continue                       # the row is named; it is a real entity
        for f in fields:
            if str(mapped.get(f) or "").strip():
                unanchored.add(f)
    return unanchored


def _shape_violation(field_name: str, value: Any) -> Optional[str]:
    """A short reason when `value` cannot be a valid instance of this field's
    declared shape, else None. Never raises."""
    s = str(value or "").strip()
    if not s:
        return None
    validators = _hard_shape_validators()
    if not validators:
        return None
    try:
        # 1. The field's own name, where the shape is unambiguous.
        #    The token must END a name segment - it is the field's own TYPE
        #    word, so `FullTimeEmployeeCount` and `PrimaryEmailAddress` count
        #    while a token merely mentioned mid-segment does not. ACORD 133's
        #    `Policy_NoPreviousCoverage_EmployeeCountIndicator_A` is a CHECKBOX
        #    that merely mentions an employee count, and a substring match would
        #    have run the count validator over "/Yes" and blanked the tick.
        segments = field_name.split("_")
        for token, kind in _NAME_SHAPE_TOKENS:
            if any(seg.endswith(token) for seg in segments) and not validators[kind](s):
                return f"not a valid {kind}: {s[:40]!r}"
        # 2. The registry validator behind the fact this field is filled from.
        fact_key = _first_rule_fact(field_name)
        if fact_key:
            registry_validate = (FACT_REGISTRY.get(fact_key) or {}).get("validate")
            for kind, fn in validators.items():
                if registry_validate is fn and not fn(s):
                    return f"not a valid {kind} for {fact_key}: {s[:40]!r}"
    except Exception:                                     # noqa: BLE001
        return None
    return None


@lru_cache(maxsize=1)
def _lob_indicator_index() -> Dict[str, Tuple[frozenset, ...]]:
    """{line_of_business_checkbox: (token_set_per_accepted_spelling, ...)}.

    The checkbox twin of `_lob_premium_index`, read from the same ACORD tooltip
    wording ("Indicates that Business Auto line of business is being selected").
    """
    index: Dict[str, Tuple[frozenset, ...]] = {}
    try:
        schemas = _all_form_schemas()
    except Exception as exc:                              # noqa: BLE001
        logger.warning("lob-indicator: cannot load schemas — %s", exc)
        return index
    for schema in schemas.values():
        for field, meta in schema.items():
            if not isinstance(meta, dict) or meta.get("ft") != "/Btn":
                continue
            token_sets = tuple(
                ts for ts in
                (_lob_tokens(v) for v in _lob_phrase_variants(meta.get("tu")))
                if ts
            )
            if token_sets:
                index[field] = token_sets
    return index


def _standard_lob_box_for(line_text: str, schema: dict) -> Optional[str]:
    """The enumerated line-of-business checkbox this free-text line names, or
    None when it names none of them (a genuine "other" line) or is too vague to
    place."""
    doc = _lob_tokens(line_text)
    if not doc:
        return None
    index = _lob_indicator_index()
    hits = [
        field for field, token_sets in index.items()
        if field in schema
        and any(_tokens_describe_same_line(doc, ts) for ts in token_sets)
    ]
    return hits[0] if len(hits) == 1 else None


def _resolve_lob_premium(field_name: str, facts: dict) -> Optional[str]:
    """This line-of-business box's own premium from the `coverage_lines` fact.

    Refuses to guess, deliberately, in both directions:
      * a document line whose wording matches SEVERAL boxes (a bare "Liability"
        fits General Liability, Fiduciary Liability and Liquor Liability) is
        skipped rather than assigned to one of them;
      * two document lines matching the SAME box cannot be told apart, so the
        box is left blank rather than showing whichever came first.
    A premium is a figure on a signed application - blank beats plausible.
    """
    token_sets = _lob_premium_index().get(field_name)
    if not token_sets:
        return None
    lines = _fv(facts, "coverage_lines")
    if not isinstance(lines, list) or not lines:
        return None

    index = _lob_premium_index()
    matches: List[Tuple[str, bool]] = []          # (premium, exact-line-name?)
    for entry in lines:
        if not isinstance(entry, dict):
            continue
        premium = entry.get("premium")
        if premium is None or not str(premium).strip():
            continue
        # A premium box holds MONEY. Observed on a real run: extraction returned
        # `{"line": "Commercial Property", "premium": "No Coverage"}` and the
        # words "No Coverage" were stamped into the premium column. That is a
        # coverage statement wearing a premium's clothes - and unlike a limit
        # box, which legitimately holds "Statutory" or "Included" (C22), a
        # premium is always a figure.
        if not _is_currency_value(str(premium)):
            logger.info(
                "lob-premium: %s rejected non-currency premium %r for line %r",
                field_name, str(premium)[:30], str(entry.get("line"))[:30],
            )
            continue
        doc_tokens = _lob_tokens(str(entry.get("line") or ""))
        if not doc_tokens:
            continue
        # Which boxes does this document line fit? Matching uses the SAME
        # predicate the indicator and prior-coverage logic already use
        # (`_tokens_describe_same_line`: stems + ACORD-corroborated synonyms),
        # so "Automobile" reaches the Business Auto premium box exactly as it
        # reaches the Business Auto checkbox. The old raw subset test could
        # not see that ("automobile" != "auto" as bare tokens), which is half
        # of how a $35 coverage part became the only candidate for a $2,991
        # line. More than one fit still means too vague to attribute.
        fits = [
            f for f, tss in index.items()
            if any(_tokens_describe_same_line(doc_tokens, ts) for ts in tss)
        ]
        if len(fits) != 1 or fits[0] != field_name:
            continue
        # A coverage PART of the line must never fill the line's own premium
        # box. Live 2026-08-12: "Auto Medical Payments $35" was the only entry
        # whose tokens fit the Business Auto box, so $35 - the medical-payments
        # PART premium - stamped as the whole line's premium on a package whose
        # Business Auto line is $2,991. The tell is structural: once the line
        # name's own tokens are accounted for, everything left over is
        # coverage-feature vocabulary ("medical", "payments", "collision"...).
        # A real line name leaves nothing over ("Business Auto") or only
        # generic words ("Commercial Liability Umbrella" leaves "liability"),
        # so only a NON-generic part word rejects - legitimate lines all pass.
        matched_ts = [ts for ts in index[field_name]
                      if _tokens_describe_same_line(doc_tokens, ts)]
        covered_toks = {
            d for d in doc_tokens
            if any(any(_line_words_match(d, c) for c in ts) for ts in matched_ts)
        }
        leftover = doc_tokens - covered_toks
        part_words = leftover & _coverage_part_vocab()
        if part_words and leftover <= (_coverage_part_vocab() | _COVERAGE_PART_GENERIC):
            logger.info(
                "lob-premium: %s rejected %r (%s) - a coverage PART of this "
                "line (part words: %s), never the line's own premium",
                field_name, str(entry.get("line"))[:40],
                str(premium)[:15], sorted(part_words)[:4],
            )
            continue
        # An entry named EXACTLY as the line ("Business Auto", "Automobile",
        # "Commercial Liability Umbrella" - leftovers empty or generic) versus
        # one carrying qualifiers of its own ("COVERED Autos Liability"). The
        # qualified one is a sub-coverage stated per part; where both shapes
        # are present, the exact name is the line and its premium is the
        # line's premium. Qualified entries still fill the box when they are
        # ALL the document offers - a dec that only itemises parts is not
        # made blanker by this.
        exact_name = leftover <= _COVERAGE_PART_GENERIC
        matches.append((str(premium).strip(), exact_name))

    # Exact line names outrank qualified ones (see exact_name above): when any
    # exact-name entry matched, only exact-name entries vote. This is what
    # stamps $2,991 ("Automobile") instead of refusing over $1,496 ("Covered
    # Autos Liability") when a dec page prints the line AND its parts.
    if any(exact for _m, exact in matches):
        matches = [(m, exact) for m, exact in matches if exact]

    # Ambiguity means two DIFFERENT AMOUNTS, never two spellings of one.
    # Live 25-page run: every line-of-business premium box came back BLANK on
    # a dec page that prints all four plainly, because the cross-chunk union
    # held the same figure as "$ 3,954.00" and "$3,954.00" - counted as two
    # rivals, declared ambiguous, and suppressed. Same disease as the merge
    # vote-splitting (C43), in a second function; comparing on digits is the
    # same cure.
    by_amount: Dict[str, str] = {}
    for m, _exact in matches:
        by_amount.setdefault(re.sub(r"\D", "", m.split(".")[0]) or m, m)
    if len(by_amount) != 1:
        if len(by_amount) > 1:
            logger.warning(
                "lob-premium: %s matched %d different amounts %s — left blank",
                field_name, len(by_amount), sorted(by_amount.values()),
            )
        return None
    return next(iter(by_amount.values()))


# ── Prior-coverage grid (ACORD 125) ──────────────────────────────────────────
# A 2-D grid: COLUMNS are lines of business, ROWS are policy terms. 64 fields.
# `_resolve_schedule_row` cannot express it - that resolver is row-indexed only.
#
# Before this existed, FOUR scalars fed SIXTEEN boxes: `prior_policy_number`
# alone fed the General Liability, Automobile, Property AND Other columns, and
# `prior_carrier` / `prior_effective_date` / `prior_expiration_date` did the
# same. The client reported the result verbatim - "BBC7263 under GL, Property
# and Other" - and noted that the carrier and premium columns, which no scalar
# fed at all, were simply empty.
#
# The `prior_coverage_by_line` fact has held exactly the right shape all along.
# It never stamped anything because 4 of its 5 `_SCHEDULE_REGISTRY` bindings
# name fields that exist on no form (PriorCoverage_InsuranceCarrier,
# PriorCoverage_TypeOfInsurance, PriorCoverage_EffectiveDate,
# PriorCoverage_Premium - all 0 real matches across the 17 schemas).
#
# NEVER feed this grid from `coverage_lines`. That fact describes the CURRENT
# policy; presenting it as coverage history is the misstatement being fixed.
_PRIOR_COVERAGE_RE = re.compile(r"^PriorCoverage_(.+?)_(.+)_([A-C])$")
_PRIOR_COVERAGE_YEAR_RE = re.compile(r"^PriorCoverage_PolicyYear_([A-C])$")

# Field-name attribute -> `prior_coverage_by_line` sub-key.
_PRIOR_COVERAGE_ATTRS: Dict[str, str] = {
    "InsurerFullName":        "carrier",
    "PolicyNumberIdentifier": "policy_no",
    "TotalPremiumAmount":     "premium",
    "EffectiveDate":          "effective",
    "ExpirationDate":         "expiration",
    # The "Other" column has a box for naming WHICH line it is - the client
    # asked for exactly this ("Add line-of-business descriptions beside
    # legitimate companion policies"). Nothing mapped it before.
    "LineOfBusinessCode":     "line",
}

# ACORD's own four columns, taken from the field names. "OtherLine" is ACORD's
# catch-all and is never matched directly - it receives whatever fits none of
# the three named columns.
_PRIOR_COVERAGE_COLUMNS = ("GeneralLiability", "Automobile", "Property")
_PRIOR_COVERAGE_OTHER = "OtherLine"


def _stem_match(a: str, b: str, min_len: int = 4) -> bool:
    """Two words mean the same line when one is a prefix of the other.

    Needed because ACORD uses different vocabularies in different sections of
    the same form: the prior-coverage column is "Automobile" while the lines-of-
    business grid and every real document say "Auto" or "Vehicle". Requiring 4
    characters keeps it from collapsing short unrelated words, and callers
    demand that EVERY token match, so "Liquor Liability" does not fall into the
    "General Liability" column on the shared word alone.
    """
    if a == b:
        return True
    return (
        len(a) >= min_len and len(b) >= min_len
        and (a.startswith(b) or b.startswith(a))
    )


# Line words ACORD itself treats as the same coverage. Deliberately tiny, and
# every pair is CORROBORATED BY A REAL TOOLTIP - see
# test_line_synonyms_are_corroborated_by_acord_tooltips, which fails the build if
# a pair is added that ACORD's own text does not support. This is domain
# vocabulary the schemas disagree with themselves about, not a value table:
# ACORD 25's certificate column is `Policy_ExcessLiability_*` while the same
# form's `ExcessUmbrella_*` tooltips read "excess or umbrella liability policy",
# and ACORD 125 calls the identical coverage "Umbrella".
_LINE_SYNONYMS: Tuple[frozenset, ...] = (
    frozenset({"excess", "umbrella"}),
)


def _line_words_match(a: str, b: str) -> bool:
    """One line word means the same as another: identical, a stem of it, or in
    the same ACORD-corroborated synonym group."""
    if _stem_match(a, b):
        return True
    return any(a in group and b in group for group in _LINE_SYNONYMS)


def _tokens_describe_same_line(doc: frozenset, col: frozenset) -> bool:
    """Every word on one side finds a partner on the other.

    Requiring ALL of them is the safety property: "Liquor Liability" shares
    "liability" with the General Liability column but not "general", so it does
    not qualify. A single shared word is never enough.
    """
    if not doc or not col:
        return False
    return (
        all(any(_line_words_match(d, c) for c in col) for d in doc)
        or all(any(_line_words_match(c, d) for d in doc) for c in col)
    )


def _prior_coverage_column(line_text: str) -> str:
    """Which of ACORD's four prior-coverage columns a document line belongs to."""
    doc = _lob_tokens(line_text)
    if not doc:
        return _PRIOR_COVERAGE_OTHER
    hits = [
        col for col in _PRIOR_COVERAGE_COLUMNS
        if _tokens_describe_same_line(
            doc, _lob_tokens(re.sub(r"(?<!^)(?=[A-Z])", " ", col)))
    ]
    # Two named columns fitting one line means the wording cannot place it.
    return hits[0] if len(hits) == 1 else _PRIOR_COVERAGE_OTHER


# ── Certificate / current-policy per-line columns (ACORD 25) ─────────────────
# A CERTIFICATE OF INSURANCE is issued to a third party who relies on it, which
# makes this the most damaging place in the product for a borrowed value - and
# it had the same defect the client reported on the ACORD 125 application, worse.
# ONE `policy_number` scalar filled the Automobile Liability, General Liability
# AND Workers Compensation rows; `effective_date` / `expiration_date` filled
# three rows each. Telling a certificate holder that WC coverage sits under the
# auto policy number is a misstatement to someone acting on it.
#
# Found by sweeping every rule against every schema field on all 17 forms, not
# by a client report. See fix-form-stamping.md "CROSS-FORM SWEEP".
_CURRENT_POLICY_LINE_RE = re.compile(
    r"^Policy_(.+?)_(PolicyNumberIdentifier|EffectiveDate|ExpirationDate)_A$"
)
_CURRENT_POLICY_ATTRS: Dict[str, str] = {
    "PolicyNumberIdentifier": "policy_number",
    "EffectiveDate":          "effective_date",
    "ExpirationDate":         "expiration_date",
}
# The scalar each attribute falls back to when the package has exactly ONE line.
_CURRENT_POLICY_SCALARS: Dict[str, str] = {
    "PolicyNumberIdentifier": "policy_number",
    "EffectiveDate":          "effective_date",
    "ExpirationDate":         "expiration_date",
}


def _resolve_current_policy_line_cell(field_name: str, facts: dict):
    """One per-line policy cell (ACORD 25's certificate rows), or _SCHED_SKIP.

    Attribution rules, in order:
      1. `coverage_lines` names this line and carries the value  -> use it.
      2. `coverage_lines` describes exactly ONE line and it is this column -> the
         package-level scalar unambiguously belongs to it, so use that.
      3. `coverage_lines` describes SEVERAL lines but not this value -> blank.
         One policy number cannot be shown against three coverages.
      4. `coverage_lines` is absent entirely -> _SCHED_SKIP, leaving the existing
         scalar rule untouched. Deliberate: a session with no per-line data would
         otherwise LOSE a value that is very often right (single-line
         submissions), and this change is only allowed to remove borrowing, never
         fill. RULE 16 makes extraction populate the fact going forward.
    """
    m = _CURRENT_POLICY_LINE_RE.match(field_name)
    if not m:
        return _SCHED_SKIP
    column, attr = m.group(1), m.group(2)
    sub_key = _CURRENT_POLICY_ATTRS.get(attr)
    if sub_key is None:
        return _SCHED_SKIP

    lines = _fv(facts, "coverage_lines")
    if not isinstance(lines, list) or not lines:
        return _SCHED_SKIP                      # rule 4 - legacy path preserved

    col_tokens = _lob_tokens(re.sub(r"(?<!^)(?=[A-Z])", " ", column))
    matched = [
        e for e in lines
        if isinstance(e, dict)
        and _tokens_describe_same_line(_lob_tokens(str(e.get("line") or "")), col_tokens)
    ]

    values = {
        str(e[sub_key]).strip() for e in matched
        if e.get(sub_key) is not None and str(e.get(sub_key)).strip()
    }
    if len(values) == 1:
        return values.pop()                     # rule 1
    if len(values) > 1:
        logger.warning(
            "current-policy: %s matched %d different values %s — left blank",
            field_name, len(values), sorted(values),
        )
        return None                             # cannot choose

    if len(lines) == 1 and matched:
        return _fv(facts, _CURRENT_POLICY_SCALARS[attr]) or None   # rule 2
    return None                                 # rule 3


def _prior_coverage_grid(facts: dict) -> Tuple[Dict[Tuple[str, int], dict], List[str]]:
    """Lay `prior_coverage_by_line` out as {(column, row_index): entry} plus the
    year label for each row.

    Rows are policy TERMS, shared across all four columns - that is what the
    single PolicyYear box per row means. So rows are keyed by year whenever
    every entry states one; otherwise they fall back to per-column document
    order and the year labels stay empty rather than asserting a term the
    document never gave.
    """
    entries = _fv(facts, "prior_coverage_by_line")
    if not isinstance(entries, list) or not entries:
        return {}, []

    # THE CURRENT POLICY IS NOT PRIOR COVERAGE.
    #
    # Live 25-page run: this grid came out holding the four policies being
    # APPLIED FOR - EMC Property & Casualty / BBC7263 / $3,954 and Employers
    # Mutual / 6E7-40-02---26 / $2,991, both dated 07/15/2025-07/15/2026, the
    # proposed term printed at the top of the same form. The document's only
    # prior reference is "RENEWAL OF: 6E7-40-02---25" - a number, with no
    # carrier, premium or dates. Extraction cannot always tell the two apart
    # because a renewal dec describes both in the same words; the form CAN,
    # because it already knows the current policy's identity.
    #
    # An entry is discarded when it carries the CURRENT policy number or the
    # CURRENT effective date. Both are equality tests against facts we hold -
    # no guessing, and a genuine prior policy (different number, earlier term)
    # is untouched. A misfiled current policy in this grid is a misstatement
    # of coverage history on a signed application.
    def _pn(v) -> str:
        return re.sub(r"[^a-z0-9]", "", str(v or "").lower())

    current_numbers = {_pn(_fv(facts, "policy_number"))}
    lines_fact = _fv(facts, "coverage_lines")
    if isinstance(lines_fact, list):
        for _e in lines_fact:
            if isinstance(_e, dict):
                current_numbers.add(_pn(_e.get("policy_number")))
    current_numbers.discard("")
    current_dates = {
        _normalized_date_key(_fv(facts, k))
        for k in ("effective_date", "expiration_date")
    }
    current_dates.discard(None)

    kept = []
    for e in entries:
        if not isinstance(e, dict):
            continue
        if _pn(e.get("policy_no")) and _pn(e.get("policy_no")) in current_numbers:
            logger.info("prior-coverage: dropped CURRENT policy %r from the prior grid",
                        str(e.get("policy_no"))[:30])
            continue
        if _normalized_date_key(e.get("effective")) in current_dates:
            logger.info("prior-coverage: dropped entry dated as the CURRENT term (%r)",
                        str(e.get("effective"))[:20])
            continue
        kept.append(e)
    entries = kept
    if not entries:
        return {}, []

    parsed: List[Tuple[str, Optional[str], dict]] = []
    for e in entries:
        if not isinstance(e, dict):
            continue
        col = _prior_coverage_column(str(e.get("line") or ""))
        year = None
        m = re.search(r"\b(19|20)\d{2}\b", str(e.get("effective") or ""))
        if m:
            year = m.group(0)
        parsed.append((col, year, e))
    if not parsed:
        return {}, []

    grid: Dict[Tuple[str, int], dict] = {}
    if all(y for _, y, _ in parsed):
        years = sorted({y for _, y, _ in parsed}, reverse=True)[:3]
        for col, year, e in parsed:
            if year in years:
                grid[(col, years.index(year))] = e
        return grid, years

    per_col: Dict[str, int] = {}
    for col, _year, e in parsed:
        idx = per_col.get(col, 0)
        if idx < 3:
            grid[(col, idx)] = e
            per_col[col] = idx + 1
    return grid, []


def _resolve_prior_coverage_cell(field_name: str, facts: dict):
    """One cell of the prior-coverage grid, or _SCHED_SKIP when not a grid field.

    Returns None (blank) rather than _SCHED_SKIP for a real grid field with no
    data, so the field can never fall through to the scalar rules that used to
    spray one policy number across every column.
    """
    year_m = _PRIOR_COVERAGE_YEAR_RE.match(field_name)
    if year_m:
        _grid, years = _prior_coverage_grid(facts)
        idx = _ROW_LETTER_TO_IDX[year_m.group(1)]
        return years[idx] if idx < len(years) else None

    m = _PRIOR_COVERAGE_RE.match(field_name)
    if not m:
        return _SCHED_SKIP
    column, attr, letter = m.group(1), m.group(2), m.group(3)
    sub_key = _PRIOR_COVERAGE_ATTRS.get(attr)
    if sub_key is None:
        return _SCHED_SKIP          # an attribute this resolver does not own

    grid, _years = _prior_coverage_grid(facts)
    entry = grid.get((column, _ROW_LETTER_TO_IDX[letter]))
    if not entry:
        return None
    val = entry.get(sub_key)
    return str(val).strip() if val is not None and str(val).strip() else None


# Specific fact -> more general fact to try when the specific one is absent.
# Only add a pair when the general value is genuinely acceptable in that box: the
# overall headcount is a defensible stand-in for "full time employees" on a
# document that states only one number, but it is NOT a stand-in for "part time
# employees", because using it for both writes the same figure twice.
_FACT_FALLBACKS: Dict[str, str] = {
    "num_employees_full_time": "num_employees",
}


def _fact_with_fallback(facts: dict, fact_key: str):
    """`_fv` plus one documented fallback hop (see _FACT_FALLBACKS)."""
    val = _fv(facts, fact_key)
    if _is_blank_value(val):
        alt = _FACT_FALLBACKS.get(fact_key)
        if alt:
            return _fv(facts, alt)
    return val


def _is_blank_value(val) -> bool:
    return val is None or (isinstance(val, str) and not val.strip())


def _field_entity(field_name: str) -> Optional[str]:
    """The party a form field belongs to, from its own ACORD name, or None."""
    for prefix in _FIELD_ENTITY_PREFIXES:
        if field_name.startswith(prefix):
            return prefix
    return None


def _entity_mismatch(field_name: str, fact_key: str) -> bool:
    """True when `fact_key` describes a DIFFERENT party than `field_name` belongs
    to. Both sides must be known for this to fire, so it is silent on every field
    and fact it has no opinion about."""
    owner = _FACT_ENTITY.get(fact_key)
    if not owner:
        return False
    target = _field_entity(field_name)
    return target is not None and target != owner


_SIGNATURE_FIELD_PATTERNS = [
    "signature","producer_sig","insured_sig","authorized_sig","applicant_sig",
    "agent_sig","signedby","signed_by","sign_here","producersig","agentsig",
    "sig_producer","sig_insured","sig_agent",
]

_SIGNATURE_FIELD_EXCLUSIONS = [
    "signing_date","signdate","sign_date","datesigned","date_signed","date_of_sign",
    "signaturedate","signature_date","designation","title","printed","print_name",
    "name_of","countersign_date","countersignature_date",
]


def _is_signature_field(field_name: str, field_type: str = "") -> bool:
    if field_type and "/Sig" in str(field_type):
        return True
    fn = field_name.lower().replace(" ", "_").replace("-", "_").replace(".", "_")
    if "date" in fn:
        return False
    if any(excl in fn for excl in _SIGNATURE_FIELD_EXCLUSIONS):
        return False
    return any(pat in fn for pat in _SIGNATURE_FIELD_PATTERNS)


def _collect_fields_pikepdf(arr, results: dict):
    for item in arr:
        try:
            t    = item.get("/T", None)
            kids = item.get("/Kids", None)
            ft   = str(item.get("/FT", ""))
            # Store the FULL tooltip (/TU). This was previously truncated to 80
            # chars, which — for Yes/No "Question" fields whose /TU is
            # "Enter Y for a Yes response. Input N for No response. The response
            # to the question, "<actual question>"?" — cut off BEFORE the actual
            # question text ever began (~85 chars of boilerplate precede it). The
            # gap-fill LLM was therefore answering compliance questions it could
            # not read (root cause of ACORD 126/140/25 coming back blank/wrong).
            # The /TU is the authoritative question text from the ACORD template
            # itself; capped only to guard against a pathological value.
            tu   = str(item.get("/TU", ""))[:_SCHEMA_TOOLTIP_MAX]
            ff   = int(item.get("/Ff", 0) or 0)
            if t:
                results[str(t)] = {"ft": ft, "tu": tu, "required": bool(ff & 2)}
            if kids:
                _collect_fields_pikepdf(kids, results)
        except Exception:
            pass


def extract_form_schema(path: str, form_id: str = "") -> dict:
    """Extract AcroForm field schema from a PDF template.

    When *form_id* is supplied the function checks
    ``forms_schemas/{form_id}_schema.json`` first and returns immediately on a
    cache hit.  On a cache miss the PDF is parsed with pikepdf and the result
    is saved to disk so subsequent calls never touch pikepdf again.
    """
    if form_id:
        schema_path = os.path.join(FORMS_SCHEMAS_DIR, f"{form_id}_schema.json")
        if os.path.exists(schema_path):
            try:
                with open(schema_path) as f:
                    return json.load(f)
            except Exception as ex:
                logger.warning(f"extract_form_schema: failed to load cached schema for {form_id}: {ex}")

    if not os.path.exists(path):
        return {}
    try:
        pdf = pikepdf.open(path)
        if "/AcroForm" not in pdf.Root:
            pdf.close()
            if form_id:
                try:
                    with open(os.path.join(FORMS_SCHEMAS_DIR, f"{form_id}_schema.json"), "w") as f:
                        json.dump({}, f)
                except Exception:
                    pass
            return {}
        schema = {}
        _collect_fields_pikepdf(pdf.Root["/AcroForm"]["/Fields"], schema)
        pdf.close()
        if form_id:
            try:
                with open(os.path.join(FORMS_SCHEMAS_DIR, f"{form_id}_schema.json"), "w") as f:
                    json.dump(schema, f, indent=2)
                logger.info(f"extract_form_schema: saved schema for {form_id} ({len(schema)} fields)")
            except Exception as ex:
                logger.warning(f"extract_form_schema: could not save schema for {form_id}: {ex}")
        return schema
    except Exception as ex:
        logger.error(f"extract_form_schema error: {ex}")
        return {}



def _get_checkbox_on_state(item) -> str:
    """Return the non-Off appearance state name for a /Btn widget (usually '/Yes').

    Reads the widget's /AP /N dictionary and returns the first key that is not
    '/Off'.  Falls back to '/Yes' if the appearance dict is absent or has no
    non-Off entry.
    """
    try:
        ap = item.get("/AP")
        if ap is not None:
            n = ap.get("/N")
            if n is not None:
                for k in n.keys():
                    k_str = str(k)
                    if k_str.lstrip("/") not in ("Off", "off", "OFF"):
                        return k_str if k_str.startswith("/") else f"/{k_str}"
    except Exception:
        pass
    return "/Yes"


def _checkmark_stream_content(w: float, h: float) -> bytes:
    """Return PDF content-stream bytes that draw a bold ✔ scaled to w×h."""
    # Checkmark path: start at left ~20% across, mid height;
    # drop to bottom ~35% across; rise to top-right corner.
    # Coordinates are in the widget's local space (origin = bottom-left).
    margin_x = w * 0.10
    margin_y = h * 0.10
    # tip of the short left stroke (bottom-left of the tick)
    x0 = margin_x + w * 0.08
    y0 = h * 0.42
    # valley of the tick
    x1 = margin_x + w * 0.30
    y1 = margin_y
    # top-right end of the tick
    x2 = w - margin_x
    y2 = h - margin_y
    lw = max(0.9, min(w, h) * 0.11)   # line weight proportional to box size
    content = (
        f"q\n"
        f"{lw:.2f} w\n"          # line width
        f"1 J\n"                  # round line caps
        f"1 j\n"                  # round line joins
        f"{x0:.2f} {y0:.2f} m\n"
        f"{x1:.2f} {y1:.2f} l\n"
        f"{x2:.2f} {y2:.2f} l\n"
        f"S\n"
        f"Q\n"
    )
    return content.encode("latin-1")


def _set_checkbox_checkmark_ap(pdf: pikepdf.Pdf, item, on_state_key: str):
    """Overwrite the on-state appearance stream in-place with a ✔ path."""
    try:
        ap = item.get("/AP")
        if ap is None:
            return

        n = ap.get("/N")
        if n is None:
            return

        key = on_state_key.lstrip("/")
        stream_obj = None
        for k in n.keys():
            if str(k).lstrip("/") == key:
                stream_obj = n[k]
                break
        if stream_obj is None:
            for k in n.keys():
                if str(k).lstrip("/") not in ("Off", "off", "OFF"):
                    stream_obj = n[k]
                    break
        if stream_obj is None:
            return

        # Read BBox from existing stream
        bb = stream_obj.get("/BBox")
        if bb is not None:
            bx0, by0, bx1, by1 = float(bb[0]), float(bb[1]), float(bb[2]), float(bb[3])
        else:
            rect = item.get("/Rect")
            if rect:
                rx1, ry1, rx2, ry2 = float(rect[0]), float(rect[1]), float(rect[2]), float(rect[3])
                bx0, by0, bx1, by1 = 0.0, 0.0, abs(rx2 - rx1), abs(ry2 - ry1)
            else:
                bx0, by0, bx1, by1 = 0.0, 0.0, 14.4, 12.0

        w = bx1 - bx0
        h = by1 - by0
        if w <= 0 or h <= 0:
            w, h = 14.4, 12.0

        stream_bytes = _checkmark_stream_content(w, h)

        # Write new content directly into the existing stream object in-place.
        # This works even when the stream is an indirect object, because we are
        # mutating the object that pikepdf already has a reference to.
        stream_obj.write(stream_bytes)

        # Remove /Filter so pikepdf doesn't try to decompress our raw bytes
        if "/Filter" in stream_obj:
            del stream_obj["/Filter"]
        if "/DecodeParms" in stream_obj:
            del stream_obj["/DecodeParms"]

    except Exception:
        pass


def _fill_and_highlight(arr, data: dict, confidence: dict, counter: list, pdf: pikepdf.Pdf = None):
    for item in arr:
        try:
            t    = item.get("/T", None)
            kids = item.get("/Kids", None)
            if t:
                name  = str(t)
                val   = data.get(name)
                if val is not None and str(val).strip() not in ("", "null", "None"):
                    ft = str(item.get("/FT", ""))
                    if "/Btn" in ft:
                        val_str    = str(val).strip()
                        is_checked = val_str.lower() in ("yes", "true", "1", "on", "x")
                        if is_checked:
                            on_state = _get_checkbox_on_state(item)
                            item["/V"]  = pikepdf.Name(on_state)
                            item["/AS"] = pikepdf.Name(on_state)
                            # Replace the on-state AP stream with a proper ✔ glyph
                            if pdf is not None:
                                _set_checkbox_checkmark_ap(pdf, item, on_state)
                        else:
                            item["/V"]  = pikepdf.Name("/Off")
                            item["/AS"] = pikepdf.Name("/Off")
                        counter[0] += 1
                    else:
                        item["/V"] = pikepdf.String(str(val))
                        if "/AP" in item:
                            del item["/AP"]
                        counter[0] += 1
            if kids:
                _fill_and_highlight(kids, data, confidence, counter, pdf)
        except Exception:
            pass


def _collect_field_rects_for_highlight(pdf: pikepdf.Pdf, confidence: dict, data: dict) -> dict:
    """Return {page_idx: [(x1,y1,x2,y2, color_rgb), ...]} for fields needing highlights."""
    # color tuples: pink=low_confidence+has_value, yellow=missing_required, green=client_arq_filled
    # Two AI tiers, deliberately distinct colors:
    #   PINK   = AI-filled AND confirmed present in the uploaded documents (AI-OK)
    #   ORANGE = AI-filled but NOT confirmed (verify) — never reads as the yellow
    #            "Required" highlight.
    COLOR_PINK   = (1.00, 0.89, 0.89)   # rgba(254,226,226) — light pink (AI-OK, verified)
    COLOR_ORANGE = (1.00, 0.84, 0.67)   # rgba(254,215,170) — light orange (Verify)
    COLOR_YELLOW = (1.00, 0.95, 0.78)   # rgba(254,243,199) — very light yellow (Required)
    COLOR_GREEN  = (0.73, 0.97, 0.82)   # rgba(187,247,208) — very light green (Client)
    page_rects: dict = {}
    for page_idx, page in enumerate(pdf.pages):
        raw_annots = page.get("/Annots")
        if raw_annots is None:
            continue
        try:
            annot_list = list(raw_annots)
        except Exception:
            continue
        for annot_ref in annot_list:
            try:
                annot = annot_ref
                if "/Widget" not in str(annot.get("/Subtype", "")):
                    continue
                t = annot.get("/T")
                if t is None:
                    parent = annot.get("/Parent")
                    if parent:
                        t = parent.get("/T")
                if t is None:
                    continue
                name = str(t)
                rect = annot.get("/Rect")
                if rect is None:
                    continue
                x1, y1, x2, y2 = float(rect[0]), float(rect[1]), float(rect[2]), float(rect[3])
                if x1 > x2: x1, x2 = x2, x1
                if y1 > y2: y1, y2 = y2, y1
                conf = confidence.get(name, "low_confidence")
                val  = data.get(name)
                has_val = val is not None and str(val).strip() not in ("", "null", "None")
                if conf == "filled":
                    color = None
                elif conf == "client_arq":
                    color = COLOR_GREEN
                elif conf == "missing_required":
                    color = COLOR_YELLOW
                elif conf == "missing_required_gate":
                    color = COLOR_YELLOW
                elif conf == "ai_verified" and has_val:
                    color = COLOR_PINK
                elif conf == "low_confidence" and has_val:
                    color = COLOR_ORANGE
                else:
                    color = None
                if color:
                    page_rects.setdefault(page_idx, []).append((x1, y1, x2, y2, color))
            except Exception:
                pass
    return page_rects


def _draw_highlight_rects(pdf: pikepdf.Pdf, page_rects: dict) -> None:
    """Paint semi-transparent filled rectangles on each page's content stream."""
    for page_idx, rects in page_rects.items():
        if not rects:
            continue
        page = pdf.pages[page_idx]
        lines = ["q"]  # save graphics state
        for (x1, y1, x2, y2, rgb) in rects:
            r, g, b = rgb
            w = x2 - x1
            h = y2 - y1
            if w <= 0 or h <= 0:
                continue
            lines.append(f"{r:.3f} {g:.3f} {b:.3f} rg")   # fill color
            lines.append(f"{x1:.2f} {y1:.2f} {w:.2f} {h:.2f} re f")  # rect + fill
        lines.append("Q")  # restore graphics state
        overlay_bytes = ("\n".join(lines) + "\n").encode("latin-1")
        overlay_stream = pikepdf.Stream(pdf, overlay_bytes)
        existing = page.get("/Contents")
        if existing is None:
            page["/Contents"] = overlay_stream
        elif isinstance(existing, pikepdf.Array):
            # Already an array — prepend our overlay
            page["/Contents"] = pikepdf.Array([overlay_stream] + list(existing))
        else:
            # Single stream — wrap both in an array (overlay drawn first, page content on top)
            page["/Contents"] = pikepdf.Array([overlay_stream, existing])


def fill_pdf(template_path: str, data: dict, confidence: Optional[dict] = None) -> bytes:
    try:
        pdf = pikepdf.open(template_path)
        if "/AcroForm" in pdf.Root:
            acro = pdf.Root["/AcroForm"]
            acro["/NeedAppearances"] = pikepdf.Boolean(True)
            counter = [0]
            _fill_and_highlight(acro.get("/Fields", []), data, confidence or {}, counter, pdf)
            logger.info(f"fill_pdf: wrote {counter[0]} field values")
        if confidence:
            page_rects = _collect_field_rects_for_highlight(pdf, confidence, data or {})
            if page_rects:
                _draw_highlight_rects(pdf, page_rects)
                total_hl = sum(len(v) for v in page_rects.values())
                logger.info(f"fill_pdf: drew {total_hl} highlight rects across {len(page_rects)} pages")
        buf = io.BytesIO()
        pdf.save(buf)
        pdf.close()
        buf.seek(0)
        return buf.getvalue()
    except Exception as ex:
        logger.error(f"fill_pdf error: {ex}")
        with open(template_path, "rb") as f:
            return f.read()


def apply_draft_watermark(pdf_bytes: bytes, label: str = "DRAFT - INCOMPLETE") -> bytes:
    """Stamp a diagonal, gray watermark across every page of a generated PDF.

    Used EXCLUSIVELY by the download-gate override path (routes/download_routes.py):
    when a producer explicitly chooses "Generate Draft Anyway" despite unresolved
    placeholder values or required COPE fields (services.field_qa.check_hard_block),
    the resulting PDF must never look identical to a clean, complete download - this
    is what makes that visually unmistakable. A clean download (the gate found
    nothing to block) never calls this function and is byte-for-byte unaffected.

    Uses the same raw pikepdf content-stream-injection technique as
    _draw_highlight_rects (this codebase's established pattern for PDF overlays)
    rather than introducing a new PDF-manipulation dependency (e.g. reportlab
    page-merging, not used anywhere else in this file). Standard Helvetica-Bold
    (one of the 14 base PDF fonts) needs no embedding, so this adds no new binary
    asset. The overlay is appended AFTER each page's existing content stream so it
    paints on top - visible over the stamped form content, not hidden behind it.
    """
    try:
        pdf = pikepdf.open(io.BytesIO(pdf_bytes))
        font_dict = pdf.make_indirect(pikepdf.Dictionary(
            Type=pikepdf.Name.Font,
            Subtype=pikepdf.Name.Type1,
            BaseFont=pikepdf.Name("/Helvetica-Bold"),
            Encoding=pikepdf.Name.WinAnsiEncoding,
        ))
        safe_label = label.replace("\\", r"\\").replace("(", r"\(").replace(")", r"\)")
        font_size = 46
        # Rough average glyph width for Helvetica-Bold uppercase text - used only to
        # approximately horizontally center the label, not a real font-metrics lookup.
        approx_half_width = len(label) * font_size * 0.31
        cos45 = sin45 = 0.70710678

        for page in pdf.pages:
            mb = page.mediabox
            width  = float(mb[2]) - float(mb[0])
            height = float(mb[3]) - float(mb[1])
            cx, cy = width / 2.0, height / 2.0

            resources = page.get("/Resources")
            if resources is None:
                resources = pikepdf.Dictionary()
                page["/Resources"] = resources
            fonts = resources.get("/Font")
            if fonts is None:
                fonts = pikepdf.Dictionary()
                resources["/Font"] = fonts
            fonts["/PrimbleDraftWM"] = font_dict

            lines = [
                "q",
                "0.55 0.55 0.55 rg",
                f"1 0 0 1 {cx:.2f} {cy:.2f} cm",
                f"{cos45:.6f} {sin45:.6f} {-sin45:.6f} {cos45:.6f} 0 0 cm",
                "BT",
                f"/PrimbleDraftWM {font_size} Tf",
                f"{-approx_half_width:.2f} 0 Td",
                f"({safe_label}) Tj",
                "ET",
                "Q",
            ]
            overlay_bytes = ("\n".join(lines) + "\n").encode("latin-1")
            overlay_stream = pikepdf.Stream(pdf, overlay_bytes)
            existing = page.get("/Contents")
            if existing is None:
                page["/Contents"] = overlay_stream
            elif isinstance(existing, pikepdf.Array):
                page["/Contents"] = pikepdf.Array(list(existing) + [overlay_stream])
            else:
                page["/Contents"] = pikepdf.Array([existing, overlay_stream])

        buf = io.BytesIO()
        pdf.save(buf)
        pdf.close()
        buf.seek(0)
        return buf.getvalue()
    except Exception as ex:
        logger.error(f"apply_draft_watermark error: {ex}")
        return pdf_bytes


# ── Fieldmap cache layer REMOVED ─────────────────────────────────────────────
# The persisted {field → fact_key} JSON cache was removed because >92% of its
# entries were null and the ambiguous null semantics caused dozens of fillable
# fields to be re-queried against GPT on every run. All form filling now flows
# through: (1) deterministic Pass 1 rules in this module and (2) the GPT call
# with the form schema + complete extracted raw text. Archived fieldmap JSONs
# live in backend/forms_database/deprecated/ for reference.
#
# The stubs below preserve the external API surface so callers in main.py and
# routes/form_routes.py keep working without modification.

def _load_fieldmap(form_id: str) -> tuple:
    """No-op stub. Cache layer removed — always returns empty fieldmap + ai set."""
    return {}, set()


def _save_fieldmap(form_id: str, fieldmap: dict, ai_set: set = None):
    """No-op stub. Cache layer removed — fills are recomputed from schema + raw text."""
    return


def migrate_fieldmaps_to_v5() -> None:
    """No-op stub. Cache layer removed — nothing to migrate."""
    return


def purge_stale_null_fieldmap_entries() -> None:
    """No-op stub. Cache layer removed — nothing to purge."""
    return


def _resolve_special(key: str, facts: dict, prefix: str) -> str:
    if prefix == "_addr":
        raw = _fv(facts, "mailing_address", "")
    elif prefix == "_loc":
        # Physical / premises address: prefer physical_address, fall back to
        # first entry in locations list, then mailing_address.
        raw = _fv(facts, "physical_address", "")
        if not raw:
            locs = facts.get("locations", [])
            raw  = locs[0] if isinstance(locs, list) and locs else ""
        if not raw:
            raw = _fv(facts, "mailing_address", "")
    else:
        raw = _fv(facts, "mailing_address", "")
    parsed = _parse_address(raw or "")
    suffix = key.split("_")[-1]
    return parsed.get(suffix, "") or ""


_SPECIAL_PREFIXES = {"_addr", "_loc"}


_INDICATOR_RULES: Dict[str, Tuple[str, str]] = {
    # field_substring: (fact_key, truthy_value_to_match)
    # GL form type
    "GeneralLiability_OccurrenceIndicator":    ("gl_form_type", "occurrence"),
    "GeneralLiability_ClaimsMadeIndicator":    ("gl_form_type", "claims"),
    # Named insured entity type — longer/more-specific substrings first
    "NamedInsured_LegalEntity_LimitedLiabilityCorporationIndicator": ("entity_type", "llc"),
    "NamedInsured_LegalEntity_SubchapterSCorporationIndicator": ("entity_type", "s-corp"),
    "NamedInsured_LegalEntity_CorporationIndicator": ("entity_type", "corporation"),
    "NamedInsured_LegalEntity_PartnershipIndicator": ("entity_type", "partnership"),
    "NamedInsured_LegalEntity_IndividualIndicator":  ("entity_type", "individual"),
    "NamedInsured_LegalEntity_NotForProfitIndicator": ("entity_type", "non-profit"),
    "NamedInsured_LegalEntity_TrustIndicator": ("entity_type", "trust"),
    "NamedInsured_LegalEntity_JointVentureIndicator": ("entity_type", "joint venture"),
    "NamedInsured_LegalEntity_OtherIndicator": ("entity_type", "other"),
    # Lines of business — primary: flags booleans (has_*) from extraction; fallback: lines_of_business list
    "Policy_LineOfBusiness_BusinessAutoIndicator":          ("has_auto_coverage",      "yes"),
    "Policy_LineOfBusiness_CommercialGeneralLiability":     ("has_general_liability",  "yes"),
    "Policy_LineOfBusiness_CommercialProperty":             ("has_property_coverage",  "yes"),
    "Policy_LineOfBusiness_UmbrellaIndicator":              ("has_umbrella",           "yes"),
    "Policy_LineOfBusiness_WorkersCompensation":            ("has_workers_comp",       "yes"),
    "Policy_LineOfBusiness_BusinessOwnersIndicator":        ("lines_of_business",      "bop"),
    "Policy_LineOfBusiness_CrimeIndicator":                 ("has_crime",              "yes"),
    "Policy_LineOfBusiness_GarageAndDealersIndicator":      ("lines_of_business",      "garage"),
    "Policy_LineOfBusiness_CommercialInlandMarineIndicator":("has_inland_marine",      "yes"),
    "Policy_LineOfBusiness_MotorCarrierIndicator":          ("lines_of_business",      "motor carrier"),
    "Policy_LineOfBusiness_TruckersIndicator":              ("lines_of_business",      "truckers"),
    "Policy_LineOfBusiness_FiduciaryLiabilityIndicator":    ("lines_of_business",      "fiduciary"),
    "Policy_LineOfBusiness_LiquorLiabilityIndicator":       ("lines_of_business",      "liquor"),
    "Policy_LineOfBusiness_CyberAndPrivacy":                ("has_cyber",              "yes"),
    "Policy_LineOfBusiness_YachtIndicator":                 ("lines_of_business",      "yacht"),
    "Policy_LineOfBusiness_BoilerAndMachineryIndicator":    ("lines_of_business",      "boiler"),
    # Business type indicators — ACORD 125 BusinessInformation section
    "BusinessInformation_BusinessType_ContractorIndicator":    ("is_contractor",          "yes"),
    "BusinessInformation_BusinessType_ManufacturingIndicator": ("operations_description", "manufactur"),
    "BusinessInformation_BusinessType_RestaurantIndicator":    ("operations_description", "restaurant"),
    "BusinessInformation_BusinessType_RetailIndicator":        ("operations_description", "retail"),
    "BusinessInformation_BusinessType_ServiceIndicator":       ("operations_description", "service"),
    "BusinessInformation_BusinessType_WholesaleIndicator":     ("operations_description", "wholesale"),
    "BusinessInformation_BusinessType_OfficeIndicator":        ("operations_description", "office"),
    "BusinessInformation_BusinessType_ApartmentsIndicator":    ("operations_description", "apartment"),
    "BusinessInformation_BusinessType_CondominiumsIndicator":  ("operations_description", "condominium"),
    "BusinessInformation_BusinessType_InstitutionalIndicator": ("operations_description", "institutional"),
    # Policy status — new/renewal
    "CommercialPolicy_NewBusinessIndicator": ("is_renewal", "no"),
    "CommercialPolicy_RenewalIndicator":     ("is_renewal", "yes"),
    # Billing method
    "Policy_Payment_DirectBillIndicator":   ("billing_plan", "direct"),
    "Policy_Payment_ProducerBillIndicator": ("billing_plan", "agency"),
    # Hired/non-owned auto
    "Vehicle_HiredIndicator":         ("hired_auto_indicator", "yes"),
    "Vehicle_HiredAutosIndicator":    ("hired_auto_indicator", "yes"),
    "Vehicle_NonOwnedIndicator":      ("non_owned_auto_indicator", "yes"),
    "Vehicle_NonOwnedAutosIndicator": ("non_owned_auto_indicator", "yes"),
    # Property valuation
    "ValuationCode_ReplacementCostIndicator": ("valuation_method", "rcv"),
    "ValuationCode_ActualCashValueIndicator": ("valuation_method", "acv"),
    # Loss history — handled by _derive_no_prior_losses_indicator (evidence-driven,
    # multi-input); intentionally NOT a generic single-key substring rule.
    # Umbrella form type
    "ExcessUmbrella_OccurrenceIndicator": ("gl_form_type", "occurrence"),
    "ExcessUmbrella_ClaimsMadeIndicator": ("gl_form_type", "claims"),
    # WC statutory limits indicator
    "WorkersCompensationEmployersLiability_WorkersCompensationStatutoryLimitIndicator": ("wc_el_each_accident", "statutory"),
    # Builders risk
    "Policy_SectionAttached_InstallationBuildersRiskIndicator": ("has_builders_risk", "true"),
    # Open Cargo is OCEAN marine - goods shipped by sea. It is NOT inland marine.
    # This rule read `has_inland_marine`, so the box ticked on EVERY inland-marine
    # submission we have ever produced; the client reported it on a policy whose
    # inland marine is a contractors-equipment floater, an installation floater
    # and an EDP section, with a $5,000 transit extension that is explicitly not
    # open cargo. Deleting the rule would NOT have fixed it - an unmapped field
    # falls through to gap fill, which would tick it anyway. It needs a fact of
    # its own that is false by default, so the box resolves to an explicit "No".
    "Policy_SectionAttached_OpenCargoIndicator": ("has_open_cargo", "true"),
    # NOT HERE, DELIBERATELY: ElectronicDataProcessing. The client asked for that
    # box to stay ticked because the inland-marine declarations grant EDP
    # coverage - but the box does not ask whether the POLICY has EDP coverage,
    # it asks whether an ACORD EDP SECTION is attached to the application WE are
    # producing, and we do not produce one. Adding a `has_edp` coverage flag to
    # drive it was tried on 2026-08-12 and reverted: it answers a different
    # question from the one the box asks. See the run-5 docstring in
    # tests/test_run5_authorship_and_attachment.py, and note the client's own
    # opposite instruction for the Driver Information Schedule box - "it should
    # only be checked when Primble actually creates and attaches a completed
    # driver-information schedule" - which is the ACORD reading of all of them.
    # Driver/vehicle schedule attachments
    "Policy_SectionAttached_DriverInformationScheduleIndicator": ("auto_drivers", "non-empty"),
    "Policy_SectionAttached_VehicleScheduleIndicator":           ("auto_vin_schedule", "non-empty"),
    # Contractors supplement. Reads the DERIVED flag, not `contractor_type`:
    # the flag is what already ticks NATURE OF BUSINESS = CONTRACTOR, so keying
    # both off it makes the two agree by construction. Live run 2026-08-12
    # printed "Contractor" as the nature of business while leaving this
    # attachment blank, because `contractor_type` (a free-text fact the dec page
    # rarely states) was null - an internally inconsistent form.
    "CommercialPolicy_Attachment_ContractorsSupplementIndicator": ("is_contractor", "true"),
}


# ── A schedule row that is only a NAME is not a schedule ─────────────────────
# Live 2026-08-13: the DRIVER INFORMATION SCHEDULE attachment box was ticked on a
# package that has no driver schedule. The tick is honest about its input - it
# fires on `auto_drivers` being non-empty - so the defect is one layer up:
# extraction had put ERIN ROYAL in `auto_drivers`, read off page 92's
# `CA 99 10 A DRIVE OTHER CAR COVERAGE - NAMES OF INDIVIDUALS`. That is the C22
# decoy, and it is the only personal name in 271 pages.
#
# Drive Other Car names an individual granted coverage while driving somebody
# else's car. It is not a driver schedule, and the extraction prompt has no way
# to know that from "one entry per driver in auto_drivers" - the shapes are
# identical on the page.
#
# THE STRUCTURAL DIFFERENCE IS WHAT THE SCHEDULE IS FOR. An ACORD driver schedule
# exists to carry licence number, date of birth, hire date and experience; those
# columns ARE the schedule. An endorsement naming individuals prints names and
# nothing else. So the attachment box asks for one row with something in it
# besides a name, rather than for a row.
#
# NON-DESTRUCTIVE ON PURPOSE. The rows stay in the facts, so `Driver_FullName_A`
# can still be filled if a downstream rule genuinely wants it, the questionnaire
# can still ask about them, and nothing is deleted on the strength of a heuristic.
# Only the claim "we are attaching a completed driver schedule" is withdrawn.
_SCHEDULE_IDENTITY_ONLY_KEYS = frozenset({"name", "full_name", "driver_name"})

# Schedules where a row carrying NOTHING BUT A NAME is not a record at all, so
# the row must not stamp. Drivers only, and deliberately so: an additional
# named insured or an additional interest legitimately IS just a name, and
# blanking those broke five tests when it was tried. See the call site in
# `_resolve_schedule_row` for the run-9 defect this exists to stop (ERIN ROYAL,
# a Drive Other Car named individual, printed as the sole ACORD 127 driver).
_NAME_ONLY_INVALID_SCHEDULES = frozenset({"auto_drivers", "drivers"})


def _schedule_has_substance(fact_key: str, rows: list) -> bool:
    """True when at least one row carries more than the entity's own name.

    Applies to every `non-empty` schedule rule, not just drivers: a vehicle list
    of bare names, a location list of bare names, would be the same mistake.
    Non-dict rows (a plain list of strings) are treated as name-only, which is
    what they are.
    """
    if not rows:
        return False
    for row in rows:
        if not isinstance(row, dict):
            continue
        for key, val in row.items():
            if key in _SCHEDULE_IDENTITY_ONLY_KEYS:
                continue
            if val not in (None, "", [], {}) and str(val).strip():
                return True
    logger.info(
        "schedule_no_substance: %s has %d row(s) carrying nothing but a name — "
        "treating as NOT a schedule (see _schedule_has_substance)",
        fact_key, len(rows),
    )
    return False


def _resolve_bool_indicator(val) -> str:
    """Convert any fact value to 'Yes' or 'No' for /Btn checkbox fields."""
    if isinstance(val, bool):
        return "Yes" if val else "No"
    s = str(val).strip().lower()
    return "Yes" if s in {"yes", "y", "true", "1", "on"} else "No"


def _int_or_none(val) -> Optional[int]:
    """First signed integer in `val`, else None. Booleans and bare text → None."""
    if val is None or isinstance(val, bool):
        return None
    if isinstance(val, int):
        return val
    if isinstance(val, float):
        return int(val)
    m = re.search(r"-?\d+", str(val).replace(",", ""))
    return int(m.group()) if m else None


def _money_positive(val) -> bool:
    """True if `val` parses to a number greater than zero (e.g. '$12,500')."""
    if val is None or isinstance(val, bool):
        return False
    m = re.search(r"-?\d+(?:\.\d+)?", str(val).replace(",", ""))
    try:
        return bool(m) and float(m.group()) > 0
    except (TypeError, ValueError):
        return False


def _attests_no_loss(val) -> bool:
    """True when `val` affirmatively states 'no prior/known losses'.

    Accepts booleans, truthy tokens, and free-text no-loss phrasing. A stored
    "No"/"false"/"0" is NOT an attestation (mirrors sqs_service._attested_true so
    the form indicator and the P4 loss score can never disagree on the evidence).
    """
    if val is None or val is False:
        return False
    if val is True:
        return True
    s = str(val).strip().lower()
    if s in {"yes", "y", "true", "1", "on"}:
        return True
    return ("no " in s or s.startswith("no")) and ("loss" in s or "claim" in s)


def _derive_no_prior_losses_indicator(facts: dict) -> Optional[str]:
    """Resolve the ACORD 125 'No Prior Losses' checkbox from the SAME evidence the
    SQS loss-history state rests on, so the printed form and the score agree.

      • Actual claims / incurred present            → "No"  (losses DO exist)
      • Attested no-loss (user, narrative, or a real 0 claim count) → "Yes"
      • Nothing extracted either way                → None  (leave BLANK so the
        questionnaire asks for loss runs / a no-known-loss confirmation instead
        of a blank box silently reading as "no losses").

    Replaces the previous num_claims=="0" SUBSTRING rule, which mis-fired for any
    claim count containing the digit 0 (e.g. 10 → "0" in "10" → wrongly "Yes").
    """
    claims = _int_or_none(_fv(facts, "num_claims"))
    if (claims is not None and claims > 0) or _money_positive(_fv(facts, "total_incurred")):
        return "No"
    attested = (
        _attests_no_loss(_fv(facts, "no_prior_losses"))
        or _attests_no_loss(_fv(facts, "narrative_states_no_losses"))
        or _attests_no_loss(_fv(facts, "loss_history_no_prior_losses_indicator"))
        or claims == 0
    )
    return "Yes" if attested else None


_SYMBOL_INDICATOR_RE = re.compile(
    r"^Vehicle_(BusinessAuto|Truckers|MotorCarrier|GarageAndDealers)Symbol_"
    r"(?P<word>[A-Za-z]+)Indicator_(?P<row>[A-Z]{1,2})$"
)

# ACORD 137/138 do not print ONE symbol grid - they print one grid PER COVERAGE
# LINE, stacked as rows A, B, C, E, F, G, H, and each row offers only the
# symbols that are legal for that coverage. Verified against the real schemas:
#
#   row A -> symbols 1,2,3,4,7,8,9   (the only row offering 1 and 9 - liability)
#   row C -> adds symbol 6           ("owned autos subject to a compulsory
#                                      uninsured motorists law" - so, UM)
#   rows B,E,F,G,H -> {2,3,4,7,8} or {3,7}, i.e. INDISTINGUISHABLE from each
#                     other by their symbol offerings alone.
#
# So only row A can be identified from the schema without guessing, and a guess
# here would stamp the liability symbol into a physical-damage row - a wrong
# value on a form, which is the one outcome that is not negotiable. Row A is
# stamped deterministically; every other row is left to gap fill exactly as it
# was before. Mapping the remaining rows means reading the printed form layout,
# not inferring it.
_SYMBOL_GRID_LIABILITY_ROW = "A"

# Symbol 1 expressed as a checkbox. Both are real fields, verified against the
# schemas: ACORD 25's certificate ANY AUTO box, and ACORD 131's underlying-
# coverage box whose ACORD tooltip reads "...covers any automobile (symbol 1)".
_ANY_AUTO_INDICATOR_FIELDS = frozenset({
    "Vehicle_AnyAutoIndicator_A",
    "UnderlyingCoverage_Coverage_AnyAutoIndicator_A",
})


def _derive_symbol_indicator(field_name: str, facts: dict) -> Optional[str]:
    """Tick the covered-auto symbol checkboxes on ACORD 137/138/160 from the
    symbols the document actually carries.

    ADDED 2026-08-07. These 37 checkboxes (8 business auto, 9 truckers, 10 motor
    carrier, 10 garage) carry ACORD's own symbol definitions in their tooltips,
    and until now nothing in Python read either the tooltips or the extracted
    `auto_covered_symbols` - so a coverage designation with legal effect was
    left entirely to a gap-fill guess. It is deterministic data; it is now
    stamped deterministically.

    Returns None (→ untouched, still gap-fill eligible) when no symbols were
    captured at all, so a document we could not read is not silently declared
    to have no coverage. Once we DO have symbols for the family, every box in
    that family is answered - "Yes" for the designated ones, "No" for the rest,
    which is what makes the grid readable to a carrier.
    """
    m = _SYMBOL_INDICATOR_RE.match(field_name)
    is_any_auto = field_name in _ANY_AUTO_INDICATOR_FIELDS
    if not m and not is_any_auto:
        return None
    try:
        from services import auto_symbols as _sym
    except Exception:            # pragma: no cover - import-failure fallback
        return None

    numbers = _sym.all_numbers(facts)
    if not numbers:
        return None

    if is_any_auto:
        # ACORD 25's ANY AUTO box and ACORD 131's underlying any-auto box are
        # Symbol 1 in checkbox form. A certificate that leaves ANY AUTO blank on
        # a Symbol 1 policy UNDERSTATES the insured's coverage to whoever relies
        # on it - so this is stamped, not guessed.
        liability = _sym.liability_symbols(facts) or numbers
        return "Yes" if any(n in _sym.ANY_AUTO_NUMBERS for n in liability) else "No"

    # Only the liability row can be identified from the schema - see the
    # _SYMBOL_GRID_LIABILITY_ROW note above. Everything else falls through.
    if m.group("row") != _SYMBOL_GRID_LIABILITY_ROW:
        return None

    family = {
        "BusinessAuto":     _sym.BUSINESS_AUTO,
        "Truckers":         _sym.TRUCKERS,
        "MotorCarrier":     _sym.MOTOR_CARRIER,
        "GarageAndDealers": _sym.GARAGE,
    }[m.group(1)]

    # Only speak for the family this policy is actually written on. A business
    # auto policy must not have "No" stamped across the truckers grid.
    if _sym.family_for(facts) != family:
        return None

    liability = _sym.liability_symbols(facts)
    if not liability:
        return None

    word = m.group("word")
    if word == "OtherSymbol":
        # Ticked only when the policy carries a symbol ACORD does not print on
        # the grid (ISO 5/19, or a company-unique symbol) - the exact case the
        # box exists for.
        return "Yes" if _sym.unrecognised(liability) else "No"

    designated = {
        n for n in liability
        if n in _sym.BY_NUMBER and _sym.BY_NUMBER[n].family == family
    }
    match = next(
        (s for s in _sym.BY_FAMILY[family].values() if s.word == word), None
    )
    if match is None:
        return None
    return "Yes" if match.number in designated else "No"


def _derive_indicator(field_name: str, facts: dict,
                      allow_scalar_rules: bool = True) -> Optional[str]:
    """Return 'Yes'/'No' for indicator/checkbox fields based on extracted facts.

    Covers both fields with 'Indicator' in the name and LOB checkboxes like
    Policy_LineOfBusiness_CommercialGeneralLiability_A (no 'Indicator' suffix).

    ``allow_scalar_rules=False`` skips the generic ``_INDICATOR_RULES`` loop.
    Those rules read POLICY-LEVEL scalar/list facts (entity_type,
    operations_description, hired_auto_indicator, ...) with no row awareness,
    so a substring rule that matches a ``_B``/``_C`` field answers a
    NON-PRIMARY row from the PRIMARY record's fact — measured across all 17
    real schemas: 22 such fields, e.g. the first insured's entity_type ticking
    LLC on the empty 2nd and 3rd Named Insured rows of ACORD 125. The
    row-variant guard in ``_deterministic_map`` passes False so those rows
    fall through to gap fill (evidence-gated) instead of inheriting row A's
    answer. The row-scoped resolvers (symbol grid, no-prior-losses) still run.
    """
    # Covered-auto symbol grids (ACORD 137/138/160) - resolved from the symbol
    # table before the generic substring rules, which cannot express "which of
    # 37 mutually-exclusive boxes".
    sym_ind = _derive_symbol_indicator(field_name, facts)
    if sym_ind is not None:
        return sym_ind

    fn_lower = field_name.lower()
    # Loss-history "No Prior Losses" is evidence-driven and multi-input — resolve
    # it deterministically before the generic single-key substring rules below.
    if "nopriorlosses" in fn_lower.replace("_", ""):
        return _derive_no_prior_losses_indicator(facts)
    if not allow_scalar_rules:
        return None
    # NATURE OF BUSINESS is about what the APPLICANT is, and the substring
    # rules read `operations_description` — where a contractor's narrative
    # routinely names its CLIENTS' spaces ("renovation of occupied retail and
    # office space"). Graded test run: Retail, Office and Service all ticked
    # beside Contractor for a general contractor. When the applicant is
    # affirmatively a contractor, the other business-type boxes resolve "No"
    # instead of pattern-matching the prose.
    if ("BusinessInformation_BusinessType_" in field_name
            and "ContractorIndicator" not in field_name
            and "Indicator" in field_name):
        _is_con = _fv(facts, "is_contractor")
        if _is_con is True or str(_is_con).strip().lower() in ("true", "yes", "1"):
            return "No"
    for substr, (fact_key, match_val) in _INDICATOR_RULES.items():
        if substr.lower() in fn_lower:
            raw = _fv(facts, fact_key)
            # Special case: match_val=="non-empty" means check whether a list is populated
            if match_val == "non-empty":
                if raw is None:
                    return "No"
                if isinstance(raw, list):
                    return "Yes" if _schedule_has_substance(fact_key, raw) else "No"
                return "Yes" if str(raw).strip() else "No"
            if raw is None:
                return None
            if isinstance(raw, bool):
                # Direct boolean fact: treat match_val=="yes"/"true" as "truthy expected"
                expected_true = match_val.lower() in {"yes", "true", "1"}
                return "Yes" if (raw == expected_true) else "No"
            if isinstance(raw, list):
                # List fact (e.g. lines_of_business): check if match_val appears in any element
                hit = any(match_val.lower() in str(item).lower() for item in raw)
                # `lines_of_business` is a MENTION list — the extraction prompt
                # gives it no no-coverage discipline, so a dec page's own
                # "BOILER & MACHINERY — NO COVERAGE" row can put "boiler" in it
                # and tick the checkbox (live run 2026-08-10). When per-line
                # grant data exists, a tick additionally requires a granting
                # `coverage_lines` entry naming that line — the same evidence
                # bar every other coverage decision now uses. No per-line data
                # at all -> legacy behaviour, coverage unchanged.
                if hit and fact_key == "lines_of_business":
                    _cov_lines = _fv(facts, "coverage_lines")
                    if isinstance(_cov_lines, list) and _cov_lines:
                        try:
                            from services.extraction_service import (
                                _line_entry_grants_coverage as _grants,
                            )
                        except Exception:                  # noqa: BLE001
                            def _grants(_e):               # type: ignore
                                return True
                        corroborated = any(
                            isinstance(_e, dict) and _grants(_e)
                            and match_val.lower() in str(_e.get("line") or "").lower()
                            for _e in _cov_lines
                        )
                        if not corroborated:
                            return "No"
                return "Yes" if hit else "No"
            # For entity_type, normalize common phrase variants before substring
            # matching so "Limited Liability Company" and "Limited Liability
            # Corporation" both resolve to "llc" rather than falling through to
            # gap fill and letting the LLM mark multiple checkboxes.
            if fact_key == "entity_type":
                val_lower = str(raw).lower()
                for _llc_phrase in (
                    "limited liability corporation",
                    "limited liability company",
                    "limited liability corp",
                    # Abbreviated forms: "LLC Corp", "LLC Corporation"
                    # (full-phrase variants above don't match these)
                    "llc corp",
                    "llc corporation",
                ):
                    if _llc_phrase in val_lower:
                        val_lower = "llc"
                        break
                val_str = val_lower
            else:
                val_str = str(raw).lower()
            if match_val.lower() in val_str:
                return "Yes"
            return "No"
    return None


# ── Gap-fill field-spec clarifications ────────────────────────────────────────
# Bug fix (found via GL test suite): the gap-fill LLM answered
# Contractors_SubcontractorsPaidAmount_A ($15) from a document that only ever
# stated "15% of work is subcontracted" - it reused the percentage's digits as
# a dollar figure for an adjacent, easily-confused field instead of returning
# null. Rule 4 in the prompt ("Dollar amounts: include $ and commas as found")
# combined with this field's own tooltip ("total dollar amount... paid to
# subcontractors") pushed it to force an answer rather than admit absence.
# Keyed by field name so this only adds prompt text when the field is actually
# being asked about, and is a plain dict so more confusable-field pairs can be
# added later without growing the global prompt skeleton.
_FIELD_SPEC_CLARIFICATIONS = {
    "Contractors_SubcontractorsPaidAmount_A": (
        " CAUTION: this is a DOLLAR AMOUNT paid to subcontractors, NOT the "
        "subcontracted-work PERCENTAGE (that is the separate field "
        "Contractors_WorkSubcontractedPercent_A). Only fill this if the "
        "document states an explicit dollar figure for this. Never derive a "
        "dollar amount from a percentage - if only a percentage is stated, "
        "return null for this field."
    ),
}


# ── GL schedule-of-hazards structured fill (ACORD 126) ───────────────────────
# Maps each broker-fillable hazard column to its key inside a row of the
# `gl_class_code_schedule` fact (list of dicts). Kept separate from the generic
# _SCHEDULE_REGISTRY so an ABSENT schedule falls through to gap-fill (returns
# "UNMATCHED") instead of being marked an authoritative blank — the client
# requires missing class/hazard data to remain a visible high-priority gap.
_GL_HAZARD_COL_TO_KEY = {
    "ClassCode":        "class_code",
    "Classification":   "classification",
    "PremiumBasisCode": "premium_basis",
    "Exposure":         "exposure_amount",
    "TerritoryCode":    "territory",
}
_GL_HAZARD_ROW_RE = re.compile(
    r"^GeneralLiability_Hazard_"
    r"(ClassCode|Classification|PremiumBasisCode|Exposure|TerritoryCode)_([A-N])$"
)


# ── A PERCENTAGE IS EXPOSURE DATA. IT IS NEVER ON A DECLARATIONS PAGE ────────
# THE GENERIC FIX for a defect that kept arriving one box at a time. Live
# 2026-08-14 ACORD 125: "INSTALLATION, SERVICE OR REPAIR WORK 100%" and "OFF
# PREMISES ... 100%", neither supported by anything in 271 pages. Earlier runs
# produced "RETAIL 100%", "% of vehicles monitored", "% owned 50%".
#
# Measured before writing the rule, across all 17 schemas: ACORD declares
# "Enter percentage:" on **74 fields over 8 forms**, and **ZERO of them can be
# filled by any fact today**. So every percentage on every form we produce is
# either blank or a gap-fill guess - and a percentage is a share of the
# applicant's OWN business (sales split, work subcontracted, ownership,
# fleet monitored). A carrier's declarations page states what it insures, never
# how the insured's revenue divides. There is nothing to read it off.
#
# This is the deposit/fax/staff-count rule stated ONCE by TYPE instead of
# seventy-four times by name, which is the whole point: the fact route stays
# open, so a producer or client ARQ answer still stamps, and silence is a blank
# rather than an invitation to guess a round number.
# Matched on the NAME, not the tooltip, because the name is available to a
# resolver and is provably equivalent here: swept across all 17 schemas, 63 of
# the 68 percentage-typed fields carry "Percent" in their name and **no field
# named *Percent* is anything other than a percentage** - zero false positives,
# so this cannot blank a box of another kind. The 5 typed fields the name misses
# are `PriorCoverage_ModificationFactor_*`, already owned by
# `_resolve_prior_coverage_cell`.
_PERCENT_FIELD_RE = re.compile(r"Percent(?:age)?(?:_[A-N])?$")


# A number is a PERCENTAGE in the document only when it is printed as one.
# "100" appearing as a radius of use, a territory code or a page number is not
# evidence that 100% of the work is off-premises.
_PCT_IN_TEXT_RE = "(?:%|\\s*percent)"


def _percentage_is_stated(value: Any, raw_text: str) -> bool:
    digits = re.sub(r"[^\d.]", "", str(value or ""))
    if not digits or not raw_text:
        return False
    return re.search(re.escape(digits) + r"\s*" + _PCT_IN_TEXT_RE,
                     raw_text, re.I) is not None


def _drop_unstated_percentages(mapped: dict, raw_text: str,
                               gpt_filled_set: set,
                               grounding: Optional[dict] = None) -> List[str]:
    """Blank an AI-authored percentage that cannot cite its own sentence.

    FIRST CUT WAS AN AUTHORITATIVE BLANK AND THE SUITE REJECTED IT, correctly:
    `test_a_percentage_the_document_states_survives` plants "15%" that the
    document really does state, and closing the box outright threw it away. The
    measurement behind the rule ("74 percentage fields, zero fillable from any
    fact") was right about FACTS and forgot the other legitimate source - a
    narrative or supplement that states the split in words.

    SECOND CUT WAS DOCUMENT-WIDE AND A LIVE RUN DEFEATED IT (2026-08-14): the
    guard asked only "is `100%` printed ANYWHERE in the document", and on a
    271-page package some unrelated endorsement always prints one - so the
    invented INSTALLATION 100% shipped while its invented 0% sibling (a figure
    the package happens never to print) was blanked. Anywhere-in-271-pages is
    not evidence about THIS box.

    So the bar is now the same one the Yes/No evidence gate uses - the model
    must CITE, and the citation is verified mechanically, never interpreted:
      1. the field's own "question_grounding" quote exists (rule 8d asks for
         it on every percentage field),
      2. the quote is verbatim in the uploaded document (normalized
         containment - a quote the document never printed proves nothing), and
      3. the quote itself contains this number AS A PERCENTAGE.
    No topic matching anywhere - quote presence and number presence only, per
    the standing evidence-gate design. A percentage without its sentence is a
    guess, and guessing an exposure split misrepresents the risk. Pass 1 /
    fact-supplied percentages are untouched.

    Scoped to `gpt_filled_set` deliberately - "did the model invent this?" is a
    question about MODEL BEHAVIOUR, so the fourth-door rule does not apply.
    """
    dropped: List[str] = []
    n_doc = _normalize_for_search(raw_text or "")
    for field in list(gpt_filled_set):
        if not _PERCENT_FIELD_RE.search(field):
            continue
        val = mapped.get(field)
        if val is None or not str(val).strip():
            continue
        quote = str((grounding or {}).get(field) or "").strip()
        quote_ok = (
            bool(quote)
            and _normalize_for_search(quote) in n_doc
            and _percentage_is_stated(val, quote)
        )
        if quote_ok:
            continue
        logger.info(
            "guard UNSTATED_PERCENTAGE field=%s value=%r - no verbatim grounding "
            "quote states this number as a percentage (quote=%r)",
            field, str(val)[:24], quote[:60],
        )
        mapped[field] = None
        dropped.append(field)
    return dropped


# ── A PARTY ASSEMBLED FROM OTHER PARTIES' DETAILS ────────────────────────────
# Live 2026-08-14 ACORD 125: the Additional Interest block shipped half-built -
# FullName "Blanket Additional Insureds" (the TITLE of a GL endorsement on the
# forms schedule, not a party), city/zip/phone all the PRODUCER's, email the
# carrier's claims address, account number the GL policy number. Other guards
# had blanked 22 of the row's fields (every indicator, the street line) and
# left these, which is worse than leaving all of them: a half-fabricated
# interest reads like a real one with sparse data.
#
# The mechanism is BORROWING, so the rule tests borrowing, not topics: an
# Additional Interest is a THIRD party, and a third party's identifying details
# are never the producer's or the carrier's. Sharing the APPLICANT's details is
# deliberately NOT a signal - a landlord or loss payee at the insured premises
# legitimately shares that address.
_AI_ROW_RE = re.compile(r"^AdditionalInterest_(.+)_([A-Z])$")
# Component SUFFIXES that identify a party (suffix match, because ACORD names
# them "MailingAddress_LineOne", "Primary_PhoneNumber", "Primary_EmailAddress",
# ...). Deliberately excludes state/country codes ("CO", "US" match everything
# in a one-state submission) and indicators.
_AI_IDENTITY_PARTS = (
    "LineOne", "LineTwo", "CityName", "PostalCode",
    "PhoneNumber", "EmailAddress",
)


def _drop_fabricated_interest_rows(mapped: dict, gpt_filled_set: set,
                                   facts: Optional[dict] = None) -> List[str]:
    """Blank a model-authored AdditionalInterest row that is a borrowed assembly.

    A row dies WHOLE (atomicity, same principle as the party-row and schedule
    guards) when either:
      - it has no FullName - an interest without a name is not an interest; or
      - any of its identifying details (address line, city, zip, phone, email)
        is byte-equal, normalized, to a PRODUCER or CARRIER value - stamped
        elsewhere on this form, OR recorded in the verified dec index under
        those owners. The index half closed the second live case (2026-08-14
        run 2): the fabricated row's phone was the SERVICING CARRIER's number,
        which no ACORD 125 field ever stamps, so the form-side pool was blind
        to it - but the index records it with owner=carrier.

    TRIED AND REMOVED the same day: requiring the FullName itself to appear in
    the dec index ("a real interest is a scheduled party"). The suite caught
    it immediately - the 2026-08-13 evidence-gate contract protects a third
    party NAMED IN DOCUMENT PROSE ("Meridian Fleet Leasing, LLC" as the named
    owner behind a Yes answer), and prose parties are exactly what the index
    never records. Both live fabrications die on the borrow rules; a name-only
    fabrication with zero borrowed details remains the accepted residual
    rather than a reason to blank legitimate named parties.

    Only fields the model authored (`gpt_filled_set`) are blanked, so a
    fact-driven or producer-entered interest is untouchable by this guard.
    """
    dropped: List[str] = []
    other_party_pool: set = set()
    for f, v in mapped.items():
        if v in (None, "") or not str(v).strip():
            continue
        if f.startswith(("Producer_", "Insurer_", "Carrier_")):
            n = _normalize_for_search(str(v))
            if len(n) > 4:                 # "co", "inc" prove nothing
                other_party_pool.add(n)
    entries = (facts or {}).get("dec_page_entries")
    entries = [e for e in entries if isinstance(e, dict)] \
        if isinstance(entries, list) else []
    for e in entries:
        if str(e.get("owner") or "").strip().lower() in ("producer", "carrier"):
            v_n = _normalize_for_search(str(e.get("value") or ""))
            if len(v_n) > 4:
                other_party_pool.add(v_n)
    rows: Dict[str, Dict[str, str]] = {}
    for f, v in mapped.items():
        m = _AI_ROW_RE.match(f)
        if m and v not in (None, "") and str(v).strip():
            rows.setdefault(m.group(2), {})[m.group(1)] = f
    for letter, comps in rows.items():
        name = str(mapped.get(comps.get("FullName", "")) or "").strip()
        borrowed = [
            f for comp, f in comps.items()
            if comp.endswith(_AI_IDENTITY_PARTS)
            and _normalize_for_search(str(mapped[f])) in other_party_pool
        ]
        if name and not borrowed:
            continue
        reason = ("no FullName - an interest without a name is not an interest"
                  if not name else
                  f"identity details borrowed from another party: {borrowed}")
        for comp, f in comps.items():
            if f not in gpt_filled_set:
                continue
            logger.info(
                "guard FABRICATED_INTEREST_ROW field=%s value=%r - row %s: %s",
                f, str(mapped[f])[:50], letter, reason,
            )
            mapped[f] = None
            dropped.append(f)
    return dropped


# ── ONE PREMISES STAMPED AS SEVERAL LOCATION ROWS ────────────────────────────
# Live 2026-08-14 ACORD 125: one address, printed comma-free in three shapes
# through the package ("4800 DAHLIA ST # D13 DENVER", "4800 Dahlia St D13
# Denver", a bare "Denver / CO / 80216-3121"), stamped as THREE premises rows.
# The 2026-08-12 fix (`_consolidate_property_locations`) folds these in the
# FACTS list - but these rows were authored by gap fill, which never passes
# through it. Same defect, one layer later, so the same folding rules apply at
# stamp time: prefix-with-same-street (the C48 rule) and geo-only fragments.
#
# SCOPED TO THE PREMISES FAMILY BY NAME, deliberately not generic: the
# obvious generalization ("dedupe any repeating address family") is exactly
# the C18 disaster - three trucks garaged in one city legitimately print
# identical Vehicle_PhysicalAddress city/state/zip rows, and deleting those
# was the worst regression this pipeline has had. Schedule-backed address
# families must never route through this guard.
_PREMISES_ADDR_ROOT = "CommercialStructure_PhysicalAddress"
_PREMISES_ROW_PREFIX = "CommercialStructure_"


def _dedupe_stamped_premises_rows(mapped: dict, gpt_filled_set: set) -> List[str]:
    """Fold model-authored duplicate premises rows into the first occurrence.

    A later row folds when:
      - its street line, normalized (case/punctuation/'#' stripped), is equal
        to or a prefix-extension of a kept row's street (the C48 rule), with
        no zip disagreement; or
      - it has NO street line at all and its zip matches a kept row - a
        geo-only fragment. A premises row without a street is not a premises.
    A folded row dies WHOLE: every CommercialStructure_*_<row> field goes with
    it, so no orphan city/zip/description remnants survive (the live run
    shipped exactly that orphan after a street-only blank). Rows with a
    genuinely different street (two suites, two buildings) never fold -
    normalized inequality keeps them.

    SOURCE-AGNOSTIC since the second 2026-08-14 run, deliberately: the first
    cut blanked only model-authored fields, and the very next run shipped the
    SAME tripled premises through Pass 1 (the facts consolidator had a
    three-variant deadlock, since fixed). A duplicate premises row is provably
    wrong whichever door stamped it, and `_enforce_post_fill_guards`' own
    charter is "corrects values from any source (Pass 1, alias, GPT)".
    """
    addr = re.compile(
        rf"^{_PREMISES_ADDR_ROOT}_(LineOne|LineTwo|CityName|PostalCode)_([A-Z])$")
    rows: Dict[str, Dict[str, str]] = {}
    for f, v in mapped.items():
        m = addr.match(f)
        if m and v not in (None, "") and str(v).strip():
            rows.setdefault(m.group(2), {})[m.group(1)] = f
    if len(rows) < 2:
        return []

    def _street_key(comps: Dict[str, str]) -> str:
        parts = [str(mapped[comps[c]]) for c in ("LineOne", "LineTwo") if c in comps]
        return re.sub(r"[^a-z0-9]+", "", " ".join(parts).lower())

    def _zip_key(comps: Dict[str, str]) -> str:
        return re.sub(r"[^0-9]", "", str(mapped[comps["PostalCode"]])) \
            if "PostalCode" in comps else ""

    dropped: List[str] = []
    kept: List[Tuple[str, str]] = []       # (street_key, zip_key)
    for letter in sorted(rows):
        comps = rows[letter]
        s, z = _street_key(comps), _zip_key(comps)
        if s:
            duplicate = any(
                ks and (s == ks or s.startswith(ks) or ks.startswith(s))
                and (not z or not kz or z == kz)
                for ks, kz in kept
            )
        else:
            duplicate = bool(z) and any(z == kz for _, kz in kept)
        if not duplicate:
            kept.append((s, z))
            continue
        row_suffix = f"_{letter}"
        for f in list(mapped.keys()):
            if (f.startswith(_PREMISES_ROW_PREFIX) and f.endswith(row_suffix)
                    and mapped.get(f) not in (None, "")):
                logger.info(
                    "guard DUPLICATE_PREMISES_ROW field=%s value=%r - row %s "
                    "repeats an earlier premises row", f, str(mapped[f])[:50], letter,
                )
                mapped[f] = None
                dropped.append(f)
    return dropped


def _drop_unanchored_party_rows(mapped: dict, schema: dict) -> List[str]:
    """Blank a row-B..N box ACORD scopes to a named insured who does not exist.

    Live 2026-08-14 ACORD 125: "DESCRIPTION OF OPERATIONS OF OTHER NAMED
    INSUREDS" held "COMMERCIAL GENERAL CONTRA" on a package with ONE insured.
    ACORD's own tooltip says what row B means - "As used here, this is the
    description of operations for other named insureds" - so the anchor is
    `NamedInsured_FullName_B`, a DIFFERENT field family, which is why the
    existing unanchored-row sweep (same-family only) cannot see it.

    A GUARD rather than a resolver, because the anchor is the STAMPED name, not
    a fact: the first cut checked an `additional_named_insureds` fact and blanked
    a genuinely different row-B narrative whose second insured had reached the
    form by another route (`test_a_genuinely_different_row_b_narrative_survives`).
    Whatever filled the name, if the name is there the row stands.
    """
    dropped: List[str] = []
    for field, value in list(mapped.items()):
        if value is None or not str(value).strip():
            continue
        m = re.search(r"_([B-N])$", field)
        if not m or field.startswith("NamedInsured_"):
            continue
        meta = schema.get(field) if isinstance(schema, dict) else None
        tu = str((meta or {}).get("tu") or "").lower()
        if _PARTY_ROW_MARKER not in tu or "insured" not in tu:
            continue
        anchor = f"NamedInsured_FullName_{m.group(1)}"
        if anchor not in (schema or {}):
            continue
        if str(mapped.get(anchor) or "").strip():
            continue                       # that insured exists - row stands
        logger.info(
            "guard PARTY_ROW_WITHOUT_A_PARTY field=%s value=%r - %s is empty, "
            "so there is no such named insured", field, str(value)[:60], anchor,
        )
        mapped[field] = None
        dropped.append(field)
    return dropped


# ── A BOX ABOUT A PARTY WHO DOES NOT EXIST ───────────────────────────────────
# Live 2026-08-14 ACORD 125: "DESCRIPTION OF OPERATIONS OF OTHER NAMED
# INSUREDS" came back holding "COMMERCIAL GENERAL CONTRA" on a package with ONE
# named insured. The box is `CommercialPolicy_OperationsDescription_B`, and
# ACORD's own tooltip says what row B means: "As used here, this is the
# description of operations for OTHER NAMED INSUREDS."
#
# So the anchor is not in this field's own family - it is
# `NamedInsured_FullName_B`, and that box is empty because there is no second
# insured. The existing unanchored-row sweep looks for a name INSIDE the same
# prefix family and therefore cannot see this.
#
# The rule is ACORD's marker, not ours: a row-lettered field whose tooltip
# carries the "As used here ... insured" party convention belongs to the
# named insured at that row letter, and is blank when that insured has no name.
# Swept across all 17 schemas: it identifies exactly one field today, which is
# the honest count - it is a RULE rather than a special case, so a form edition
# that adds another party-scoped row is covered without another patch.
# The resolver signature is (field, facts) - no schema - so the tooltip reaches
# it through a THREAD-LOCAL set by whichever form builder is running. Forms are
# generated concurrently on `_FORM_EXECUTOR`, so a plain module global would
# race and hand one form another form's tooltips.
_SCHEMA_CTX = threading.local()


def _set_schema_context(schema: Optional[dict]) -> None:
    _SCHEMA_CTX.schema = schema if isinstance(schema, dict) else None


def _field_meta(field_name: str) -> dict:
    schema = getattr(_SCHEMA_CTX, "schema", None)
    meta = (schema or {}).get(field_name)
    return meta if isinstance(meta, dict) else {}


_PARTY_ROW_MARKER = "as used here"


def _resolve_party_scoped_row(field_name: str, facts: dict):
    m = re.search(r"_([B-N])$", field_name or "")
    if not m or (field_name or "").startswith("NamedInsured_"):
        return _SCHED_SKIP
    tu = str(_field_meta(field_name).get("tu") or "").lower()
    if _PARTY_ROW_MARKER not in tu or "insured" not in tu:
        return _SCHED_SKIP
    roster = _fv(facts, "additional_named_insureds")
    idx = _ROW_LETTER_TO_IDX[m.group(1)] - 1        # row B is the FIRST extra
    if isinstance(roster, list) and 0 <= idx < len(roster) and roster[idx]:
        return _SCHED_SKIP                          # that insured exists
    return None


def _single_row_schedule(field_name: str, facts: dict) -> bool:
    """True when this field's schedule holds AT MOST ONE row.

    THE GUARD ON THE ROW-A SCALAR FALLBACK, added 2026-08-14 after the fallback
    shipped a real defect the day it landed. The fallback exists so a
    package-level fact can fill row A of a schedule that has no value for that
    column - "one premises, and the operations description lives on the policy
    rather than the location". That reasoning holds for ONE row and collapses
    for two: with a second location, row A's empty street is not an invitation
    to stamp the HEAD OFFICE address into it.

    Reproduced before this guard existed: two locations, row 1 carrying a city
    ("Aurora") but no street, and `CommercialStructure_PhysicalAddress_LineOne_A`
    came back "4800 DAHLIA ST # D13" - the Denver mailing address, printed as
    the street of a building the document places in another town. Two different
    premises merged into one row is worse than a blank street.

    One row means the package-level fact and location 1 are the same thing.
    Two or more, and blank is the correct answer.
    """
    m = _SCHED_ROW_RE.match(field_name or "")
    if not m:
        return True                       # not schedule-backed; nothing to gate
    base = m.group(1)
    defn = _SCHEDULE_REGISTRY.get(base)
    if defn is None:
        for prefix, d in _SCHEDULE_REGISTRY.items():
            if base == prefix or base.startswith(prefix + "_") or base.endswith("_" + prefix):
                defn = d
                break
    if defn is None:
        return True
    items = _fv(facts, defn.list_key)
    return not isinstance(items, list) or len(items) <= 1


def _resolve_gl_hazard_row(field_name: str, facts: dict):
    """Resolve an ACORD 126 schedule-of-hazards data cell from the structured
    `gl_class_code_schedule` fact.

    Returns
    -------
    _SCHED_SKIP  — not a GL hazard data field; caller continues normally.
    str          — the structured value for this row/column.
    "UNMATCHED"  — GL hazard field with no structured value → send to gap-fill
                   so the LLM can still read it from raw text (never a silent blank).
    """
    m = _GL_HAZARD_ROW_RE.match(field_name)
    if not m:
        return _SCHED_SKIP
    col, letter = m.group(1), m.group(2)
    idx = _ROW_LETTER_TO_IDX[letter]
    rows = _fv(facts, "gl_class_code_schedule")
    if not isinstance(rows, list) or not rows:
        rows = _fv(facts, "gl_class_codes")
    if isinstance(rows, list) and idx < len(rows):
        row = rows[idx]
        if isinstance(row, dict):
            val = row.get(_GL_HAZARD_COL_TO_KEY[col])
            if val is not None and str(val).strip():
                return str(val).strip()
        return "UNMATCHED"           # row exists, this column is genuinely empty
    # ── PHANTOM HAZARD ROW ───────────────────────────────────────────────────
    # C46's phantom-vehicle-row rule, one form over. Run 9's ACORD 126 printed
    # THREE hazard rows against a package with exactly TWO class codes: row 3
    # was row 1's code, basis and exposure with an invented territory ("CO").
    # It happened because a row past the end of the schedule returned
    # "UNMATCHED", which hands the whole row to gap fill - and gap fill, asked
    # about a classification that does not exist, copies the nearest one.
    #
    # Acts only on POSITIVE evidence, exactly like the vehicle version: a known,
    # non-empty schedule shorter than this row letter means the row is not
    # there. No schedule at all still returns "UNMATCHED", because suppressing
    # on no evidence would delete a schedule the extractor merely missed.
    if isinstance(rows, list) and rows and idx >= len(rows):
        return None
    return "UNMATCHED"


_SUBJECT_OF_INSURANCE_RE = re.compile(
    r"^CommercialProperty_Premises_(SubjectOfInsuranceCode|LimitAmount)_([A-Z])$"
)
# Guard 2 (repeating-row dedup) exemption - deliberately narrower than
# _SUBJECT_OF_INSURANCE_RE above: SubjectOfInsuranceCode legitimately repeats
# ("Building" is a perfectly normal subject at 2 different locations), but
# LimitAmount duplicating row A's EXACT dollar figure is a real bug, not a
# coincidence - a live test confirmed this exact failure: a 2nd location's
# row came back with row A's amount duplicated into it, and Guard 2 never
# caught it because LimitAmount was exempted here right alongside
# SubjectOfInsuranceCode. LimitAmount now goes through the same row-A
# comparison as any other free-text value field.
_SUBJECT_OF_INSURANCE_CODE_ONLY_RE = re.compile(
    r"^CommercialProperty_Premises_SubjectOfInsuranceCode_([A-Z])$"
)
# Building = subject slot 0, BPP = subject slot 1, within each premises's own
# 6-letter block (see _resolve_subject_of_insurance_row). Slots 2-4 (e.g.
# Business Income) have no structured source in the current fact model.
_SUBJECT_OF_INSURANCE_SLOTS = (
    ("Building", "building_value"),
    ("Business Personal Property", "bpp_value"),
)


def _resolve_subject_of_insurance_row(field_name: str, facts: dict):
    """Resolve a per-premises Subject-of-Insurance data cell (the Building /
    BPP amount grid on ACORD 140/141) from the canonical `property_locations`
    list.

    This grid's row-lettering is NOT the simple "letter = premises index"
    scheme used elsewhere on the same form (address, revenue, employee
    count, ...). Confirmed directly against ACORD_140_schema.json:
    CommercialStructure_PhysicalAddress_LineOne_A is premises 1's address and
    _B is premises 2's - but CommercialProperty_Premises_LimitAmount jumps
    from _E straight to _G for premises 2's first subject row, skipping _F.
    Each premises gets its OWN 6-letter block (5 real subject rows + 1 unused
    spacer): premises 1 = A-F, premises 2 = G-L, premises 3 = M-R, etc.

    Without this, these fields were entirely unregistered and fell to
    ungated GPT gap-fill with no per-premises grounding, which mixed dollar
    figures from DIFFERENT locations into a single premises block's grid.

    Returns
    -------
    _SCHED_SKIP  — not a subject-of-insurance field; caller continues normally.
    None         — this premises doesn't exist (fewer real locations than
                   letter-blocks) - an authoritative blank, not sent to GPT.
    "UNMATCHED"  — a real premises, but no structured value for this subject
                   slot yet → gap-fill may still try from raw text.
    str          — the resolved value.
    """
    m = _SUBJECT_OF_INSURANCE_RE.match(field_name)
    if m is None:
        return _SCHED_SKIP
    col, letter = m.group(1), m.group(2)
    letter_idx = _ROW_LETTER_TO_IDX.get(letter)
    if letter_idx is None:
        return _SCHED_SKIP
    loc_idx, slot_idx = divmod(letter_idx, 6)
    if slot_idx == 5:
        return _SCHED_SKIP  # the unused spacer letter (F, L, R, ...) - not a real row

    locations = _fv(facts, "property_locations")
    if not isinstance(locations, list) or loc_idx >= len(locations):
        return None
    loc = locations[loc_idx]
    if not isinstance(loc, dict) or slot_idx >= len(_SUBJECT_OF_INSURANCE_SLOTS):
        return "UNMATCHED"

    label, value_key = _SUBJECT_OF_INSURANCE_SLOTS[slot_idx]
    value = loc.get(value_key)
    if value is None or (isinstance(value, str) and not value.strip()):
        return "UNMATCHED"
    return label if col == "SubjectOfInsuranceCode" else str(value)


_NO_LOSS_INDICATOR_FIELDS = {"LossHistory_NoPriorLossesIndicator_A"}


def _resolve_no_loss_indicator(field_name: str, facts: dict, raw_text: str = ""):
    """Deterministically resolve the ACORD 'Check if none' loss-history
    checkbox from the SAME signal the SQS scorer uses, instead of an
    independent per-field GPT judgment call.

    Previously the checkbox was decided purely by a Pass-2 GPT per-field
    guess, disconnected from the facts/flags the SQS panel scores against. A
    submission could come back with the checkbox CHECKED ("Yes" - reads to a
    broker as confirmed/done) while the SQS panel simultaneously scored the
    identical submission as only a narrative assertion, "weaker than an
    attestation, please confirm" - the PDF and the report contradicting each
    other about the same finding.

    Every real caller (process_single_form, compute_form_gaps) already merges
    session flags into the facts dict it passes in (`facts_with_flags = {
    **session["facts"], **session["flags"]}` - see form_service.py), the same
    pattern already relied on for other checkboxes like has_general_liability.
    So `narrative_states_no_losses` / `no_prior_losses` here are the EXACT
    flag values calculate_p4_loss_history() and _get_loss_history_state() in
    sqs_service.py read - not a re-derived approximation, the same booleans.
    That makes the checkbox and the SQS state impossible to disagree by
    construction. A raw-text scan (detect_no_loss_assertion) is kept only as
    a defensive fallback for a caller that didn't merge flags in.

    Returns
    -------
    _SCHED_SKIP  — not this field; caller continues normally.
    "No"         — real claim data is present. Never attest "none" above a
                   populated claims table on the same form - that would be
                   its own internal contradiction.
    "Yes"        — a no-loss assertion was found with no contradicting claims.
    "UNMATCHED"  — neither signal fired → gap-fill may still try from raw text.
    """
    if field_name not in _NO_LOSS_INDICATOR_FIELDS:
        return _SCHED_SKIP

    def _has_positive_amount(key: str) -> bool:
        v = _fv(facts, key)
        if v is None:
            return False
        try:
            return float(re.sub(r"[^\d.]", "", str(v)) or 0) > 0
        except Exception:
            return False

    if _has_positive_amount("num_claims") or _has_positive_amount("total_incurred"):
        return "No"
    if bool(_fv(facts, "narrative_states_no_losses")) or bool(_fv(facts, "no_prior_losses")):
        return "Yes"
    npl = _fv(facts, "loss_history_no_prior_losses_indicator")
    if str(npl or "").strip().lower() in ("yes", "y", "true", "1"):
        return "Yes"
    if detect_no_loss_assertion(raw_text or ""):
        return "Yes"
    return "UNMATCHED"


def _resolve_no_loss_checkbox_owned(field_name: str, facts: dict):
    """The _AUTHORITATIVE_BLANK_RESOLVERS face of _resolve_no_loss_indicator:
    same flag/fact signals, but silence means an EMPTY box, never a gap-fill
    guess. See the registration comment for the live defect this closes."""
    if field_name not in _NO_LOSS_INDICATOR_FIELDS:
        return _SCHED_SKIP
    verdict = _resolve_no_loss_indicator(field_name, facts)
    return None if verdict == "UNMATCHED" else verdict


def _resolve_via_field_rules(field_name: str, facts: dict):
    """The plain `_ACORD_FIELD_RULES` substring lookup, factored out so it can
    also serve as a fallback for row A of a schedule-shadowed field (see the
    call site in `_deterministic_map`) without duplicating this logic."""
    for pattern, fact_key in _ACORD_FIELD_RULES:
        if pattern in field_name:
            if fact_key is None:
                return None
            # This party's box, another party's fact -> hand it to gap fill so it
            # can read THIS party's own value from the document (see _FACT_ENTITY).
            if _entity_mismatch(field_name, fact_key):
                return "UNMATCHED"
            if fact_key.startswith("_"):
                if fact_key.startswith("_addr_") and not field_name.startswith("NamedInsured_"):
                    return "UNMATCHED"
                return _resolve_special(fact_key, facts, "_" + fact_key.split("_")[1]) or None
            val = _fact_with_fallback(facts, fact_key)
            if fact_key == "valuation_method" and isinstance(val, str):
                val = _VALUATION_METHOD_TO_ACORD_CODE.get(val.strip().lower(), val)
            if isinstance(val, list):
                if "Indicator" in field_name and isinstance(val, list):
                    return _derive_indicator(field_name, facts)
                return str(val[0]) if val else None
            return str(val) if val is not None else None
    return None


def _deterministic_map(field_name: str, facts: dict):
    # ── Prior-coverage grid (line x term) ───────────────────────────────────
    # FIRST, deliberately. It owns every PriorCoverage_<LINE>_* cell including
    # rows B and C, which the row-variant guard further down would otherwise
    # divert to gap fill before this could ever see them. Returning None for an
    # owned-but-empty cell is what stops the old scalar spray.
    prior_cell = _resolve_prior_coverage_cell(field_name, facts)
    if prior_cell is not _SCHED_SKIP:
        return prior_cell

    # ── Certificate / current-policy per-line columns (ACORD 25) ────────────
    cur_cell = _resolve_current_policy_line_cell(field_name, facts)
    if cur_cell is not _SCHED_SKIP:
        return cur_cell

    # ── Auto liability: combined single limit XOR split limits ──────────────
    auto_limit_cell = _resolve_auto_liability_limit_cell(field_name, facts)
    if auto_limit_cell is not _SCHED_SKIP:
        return auto_limit_cell

    # ── Q4 "other insurance": line and number stamped as one pair ───────────
    other_policy_cell = _resolve_other_policy_cell(field_name, facts)
    if other_policy_cell is not _SCHED_SKIP:
        return other_policy_cell

    # ── "Other" LOB rows: only granted lines with no standard checkbox ──────
    # Owns rows A-F (must run BEFORE the row-variant guard below, which would
    # otherwise divert _B.._F to gap fill).
    other_lob = _resolve_other_lob_row(field_name, facts)
    if other_lob is not _SCHED_SKIP:
        return other_lob

    # ── Status of transaction: fact-driven when the document states it ──────
    status_cell = _resolve_policy_status(field_name, facts)
    if status_cell is not _SCHED_SKIP:
        return status_cell

    # ── Additional-interest type: exactly one box, from the captured fact ───
    interest_type = _resolve_additional_interest_type(field_name, facts)
    if interest_type is not _SCHED_SKIP:
        return interest_type

    # ── Address line-two: parsed from the party's own address fact ──────────
    line_two = _resolve_address_line_two(field_name, facts)
    if line_two is not _SCHED_SKIP:
        return line_two

    # ── Producer mailing block: one parse feeds every component ─────────────
    producer_mailing = _resolve_producer_mailing(field_name, facts)
    if producer_mailing is not _SCHED_SKIP:
        return producer_mailing

    # ── Applicant contact block: blank when no applicant contact fact ───────
    applicant_contact = _resolve_applicant_contact(field_name, facts)
    if applicant_contact is not _SCHED_SKIP:
        return applicant_contact

    # ── Estimated total policy cost: arithmetic over granted line premiums ──
    est_total = _resolve_estimated_total(field_name, facts)
    if est_total is not _SCHED_SKIP:
        return est_total

    # ── Producer's printed name beside the signature ────────────────────────
    printed_name = _resolve_producer_printed_name(field_name, facts)
    if printed_name is not _SCHED_SKIP:
        return printed_name

    # ── "Section attached" is a claim about our own package ─────────────────
    section_attached = _resolve_section_attached_indicator(field_name, facts)
    if section_attached is not _SCHED_SKIP:
        return section_attached

    # ── Fax and deposit: resolver-owned, and it MUST happen here ─────────────
    # Being in _AUTHORITATIVE_BLANK_RESOLVERS only closes the GAP-FILL door.
    # Run 6 printed the phone in the FAX box anyway, through the third door:
    # the generic Pass-1 substring rule ("Producer_FaxNumber" -> producer_fax)
    # stamped the mislabelled fact RAW, further down this function, without
    # ever consulting the resolver. An owning resolver that is not consulted
    # where values are PRODUCED owns nothing - it has to intercept before the
    # rules loop, exactly like every other resolver in this block.
    party_fax = _resolve_party_fax(field_name, facts)
    if party_fax is not _SCHED_SKIP:
        return party_fax
    payment_deposit = _resolve_payment_deposit(field_name, facts)
    if payment_deposit is not _SCHED_SKIP:
        return payment_deposit
    claims_made = _resolve_claims_made_dates(field_name, facts)
    if claims_made is not _SCHED_SKIP:
        return claims_made
    max_exposure = _resolve_max_vehicle_exposure(field_name, facts)
    if max_exposure is not _SCHED_SKIP:
        return max_exposure
    payment_schedule = _resolve_payment_schedule(field_name, facts)
    if payment_schedule is not _SCHED_SKIP:
        return payment_schedule
    exposure_count = _resolve_exposure_count(field_name, facts)
    if exposure_count is not _SCHED_SKIP:
        return exposure_count
    loss_summary = _resolve_loss_history_summary(field_name, facts)
    if loss_summary is not _SCHED_SKIP:
        return loss_summary

    # ── The applicant's own website, or nothing ─────────────────────────────
    applicant_site = _resolve_applicant_website(field_name, facts)
    if applicant_site is not _SCHED_SKIP:
        return applicant_site

    # ── Loss-history no-loss checkbox (single source of truth with SQS) ─────
    no_loss = _resolve_no_loss_indicator(field_name, facts)
    if no_loss is not _SCHED_SKIP:
        return no_loss  # "Yes"/"No", or "UNMATCHED" → gap-fill from raw text

    # ── GL schedule-of-hazards structured cells (highest priority) ───────────
    gl_haz = _resolve_gl_hazard_row(field_name, facts)
    if gl_haz is not _SCHED_SKIP:
        return gl_haz  # value string, or "UNMATCHED" → gap-fill from raw text

    # ── Subject-of-Insurance per-premises structured cells ───────────────────
    soi = _resolve_subject_of_insurance_row(field_name, facts)
    if soi is not _SCHED_SKIP:
        return soi  # value string, None (no such premises), or "UNMATCHED"

    # ── Schedule row resolution (highest priority) ───────────────────────────
    sched = _resolve_schedule_row(field_name, facts)
    if sched is not _SCHED_SKIP:
        # A handful of `_ACORD_FIELD_RULES` entries share their EXACT base name
        # with a `_SCHEDULE_REGISTRY` entry (e.g. BusinessInformation_
        # FullTimeEmployeeCount is both "the num_employees rule" AND "column
        # full_time_employees of the property_locations schedule") - swept
        # across the full registry (2026-07): 4 such pairs exist. The schedule
        # check runs first and unconditionally wins, which is correct WHEN a
        # genuine structured breakdown exists (a real per-location employee
        # split, a real per-line prior-coverage schedule) - but when NO such
        # breakdown was ever captured (the common case: a document just states
        # one overall total), it silently shadows the simple scalar fact
        # forever, even after a client explicitly confirms it via ARQ.
        #
        # Live finding: a client answered "How many people does your business
        # employ?" - `facts['num_employees']` updated and SQS moved, but the
        # actual PDF box never changed, because this exact interception
        # returned None (property_locations has no entries) before the plain
        # num_employees rule was ever reached.
        #
        # Scoped narrowly to row A only: `_resolve_schedule_row` returns None
        # at row A (list index 0) if and only if the schedule's list is
        # COMPLETELY EMPTY - never as "too short for this particular row",
        # since index 0 always exists whenever the list has at least one real
        # entry. So this fallback can never override or hide genuine partial
        # schedule data, and rows B/C/D+ are untouched - a document with real
        # per-location or per-line data still uses it, exactly as before.
        if sched is None and field_name.endswith("_A") \
                and _single_row_schedule(field_name, facts):
            fallback = _resolve_via_field_rules(field_name, facts)
            if fallback is not None and fallback != "UNMATCHED":
                return fallback
        return sched  # None means blank; any string is the resolved value

    # ── Family row bound: rows beyond a KNOWN schedule length are blank for
    # every column of the family, bound or not (the County-fragment fix).
    fam_row = _resolve_schedule_family_row(field_name, facts)
    if fam_row is not _SCHED_SKIP:
        return fam_row

    # Layer: Location\d+_SubField  →  facts["locations"][N-1] or sub-key lookup
    loc_m = re.match(r"Location(\d+)[_]?(.*)", field_name)
    if loc_m:
        idx      = int(loc_m.group(1)) - 1
        sub      = loc_m.group(2).lower()
        locs     = facts.get("locations", []) or []
        if idx < len(locs):
            entry = locs[idx]
            if isinstance(entry, dict):
                val = entry.get(sub) or entry.get("address") or str(entry)
            else:
                val = str(entry)
            return val if val else None
        return None

    # ── Row-variant guard ────────────────────────────────────────────────────
    # Fields whose names end with a row suffix (_B, _C … _N) but were NOT
    # resolved by _resolve_schedule_row above represent additional-entity
    # slots (2nd named insured, 2nd building location, …).
    # _ACORD_FIELD_RULES uses substring matching and would blindly stamp the
    # PRIMARY scalar fact into every _B/_C/_D variant, causing duplicated
    # values (e.g. Named Insured × 4 on ACORD 101, same premises address in
    # every CommercialStructure row on ACORD 125).
    #
    # By routing these non-primary rows directly through _derive_indicator:
    #   • Checkbox/indicator fields get correct "Yes"/"No" from facts.
    #   • All other fields return None → treated as UNMATCHED by the caller
    #     → gap-fill LLM fills them only if a second entity exists in the doc.
    # The _A slot (idx=0) is the primary slot and always passes through below.
    _row_guard = _SCHED_ROW_RE.match(field_name)
    if _row_guard and _ROW_LETTER_TO_IDX[_row_guard.group(2)] >= 1:
        # allow_scalar_rules=False: a _B/_C row must never inherit the PRIMARY
        # record's scalar facts (entity_type, operations_description, ...) —
        # that stamped the 1st insured's LLC tick onto empty 2nd/3rd insured
        # rows. Row-scoped resolvers (symbol grid) still apply; everything else
        # returns None -> gap fill, where the evidence gate governs the answer.
        return _derive_indicator(field_name, facts, allow_scalar_rules=False)

    for pattern, fact_key in _ACORD_FIELD_RULES:
        if pattern in field_name:
            if fact_key is None:
                return None
            # The general form of the `_addr_*` rule immediately below: this
            # party's box must not be filled from another party's fact. See
            # _FACT_ENTITY. Returns UNMATCHED, never blank, so gap fill can still
            # supply this party's own value.
            if _entity_mismatch(field_name, fact_key):
                return "UNMATCHED"
            if fact_key == "_today_date":
                from datetime import datetime as _dt
                return _dt.now().strftime("%m/%d/%Y")
            if fact_key.startswith("_"):
                # "_addr_*" (mailing_address) is only a real fact for the NAMED
                # INSURED - extraction never captures a separate Producer /
                # AdditionalInterest / CertificateHolder address. Reusing the
                # insured's mailing_address for those (previous behavior)
                # silently stamped the WRONG entity's address onto the form -
                # a direct "producer details must be exact" violation. Only
                # resolve _addr_* for NamedInsured_* fields; everything else
                # falls through to gap-fill, which reads the correctly-labelled
                # address for that entity directly from the raw document text.
                # "_loc_*" (physical_address) is unaffected - both its users
                # (NamedInsured_PhysicalAddress_* and CommercialStructure_
                # PhysicalAddress_*) legitimately mean the insured's own premises.
                if fact_key.startswith("_addr_") and not field_name.startswith("NamedInsured_"):
                    return "UNMATCHED"
                return _resolve_special(fact_key, facts, "_" + fact_key.split("_")[1]) or None
            val = _fact_with_fallback(facts, fact_key)   # unwrap envelope + _FACT_FALLBACKS
            if fact_key == "valuation_method" and isinstance(val, str):
                # `valuation_method` is normalized to the 3-letter industry term
                # ("RCV"/"ACV") at extraction time, but the real ACORD 140/141
                # ValuationCode field documents a SINGLE-LETTER code in its own
                # tooltip (A/R/V/M - Actual Cash Value/Replacement Cost/Agreed
                # Amount/Market Value). A live test surfaced the mismatch this
                # caused directly: the deterministically-filled row showed "RCV"
                # while a gap-filled row (which reads the tooltip itself) showed
                # "R" for the exact same concept - same field, two different
                # conventions. Translate to the schema's own convention here so
                # every row is consistent regardless of which pass filled it.
                val = _VALUATION_METHOD_TO_ACORD_CODE.get(val.strip().lower(), val)
            if isinstance(val, list):
                # For indicator fields, check if the relevant value exists in the list
                if "Indicator" in field_name and isinstance(val, list):
                    ind = _derive_indicator(field_name, facts)
                    return ind
                return str(val[0]) if val else None
            return str(val) if val is not None else None

    # Try indicator derivation — also handles LOB checkboxes without "Indicator"
    # in the field name (e.g. Policy_LineOfBusiness_CommercialGeneralLiability_A).
    ind = _derive_indicator(field_name, facts)
    if ind is not None:
        return ind

    return "UNMATCHED"


def _apply_fact_key(fact_key: str, facts: dict):
    """Resolve a cached/LLM-returned fact_key to a scalar string value."""
    if fact_key is None:
        return None
    if fact_key.startswith("_"):
        return _resolve_special(fact_key, facts, "_" + fact_key.split("_")[1]) or None
    val = _fv(facts, fact_key)
    if isinstance(val, bool):
        return _resolve_bool_indicator(val)
    if isinstance(val, list):
        return str(val[0]) if val else None
    return str(val) if val is not None else None


_ACORD125_REQUIRED_ALWAYS = {
    "Producer_FullName_A",
    "NamedInsured_FullName_A",
    "NamedInsured_MailingAddress_LineOne_A",
    "NamedInsured_MailingAddress_CityName_A",
    "NamedInsured_MailingAddress_StateOrProvinceCode_A",
    "NamedInsured_MailingAddress_PostalCode_A",
    "Policy_EffectiveDate_A",
    "Policy_ExpirationDate_A",
    "CommercialPolicy_OperationsDescription_A",
    "NamedInsured_BusinessStartDate_A",
}

_ACORD125_CONTACT_FIELDS = {
    "Producer_ContactPerson_FullName_A",
    "Producer_ContactPerson_PhoneNumber_A",
    "Producer_ContactPerson_EmailAddress_A",
    "NamedInsured_Primary_PhoneNumber_A",
}

_ACORD125_LOB_FIELDS = {
    "Policy_LineOfBusiness_BoilerAndMachineryIndicator_A",
    "Policy_LineOfBusiness_BusinessAutoIndicator_A",
    "Policy_LineOfBusiness_BusinessOwnersIndicator_A",
    "Policy_LineOfBusiness_CommercialGeneralLiability_A",
    "Policy_LineOfBusiness_CommercialInlandMarineIndicator_A",
    "Policy_LineOfBusiness_CommercialProperty_A",
    "Policy_LineOfBusiness_CrimeIndicator_A",
    "Policy_LineOfBusiness_CyberAndPrivacy_A",
    "Policy_LineOfBusiness_FiduciaryLiabilityIndicator_A",
    "Policy_LineOfBusiness_GarageAndDealersIndicator_A",
    "Policy_LineOfBusiness_LiquorLiabilityIndicator_A",
    "Policy_LineOfBusiness_MotorCarrierIndicator_A",
    "Policy_LineOfBusiness_TruckersIndicator_A",
    "Policy_LineOfBusiness_UmbrellaIndicator_A",
    "Policy_LineOfBusiness_YachtIndicator_A",
    "Policy_LineOfBusiness_OtherIndicator_A",
    "Policy_LineOfBusiness_OtherIndicator_B",
    "Policy_LineOfBusiness_OtherIndicator_C",
    "Policy_LineOfBusiness_OtherIndicator_D",
    "Policy_LineOfBusiness_OtherIndicator_E",
    "Policy_LineOfBusiness_OtherIndicator_F",
}

_ACORD125_BUSINESS_TYPE_FIELDS = {
    "BusinessInformation_BusinessType_ApartmentsIndicator_A",
    "BusinessInformation_BusinessType_CondominiumsIndicator_A",
    "BusinessInformation_BusinessType_ContractorIndicator_A",
    "BusinessInformation_BusinessType_InstitutionalIndicator_A",
    "BusinessInformation_BusinessType_ManufacturingIndicator_A",
    "BusinessInformation_BusinessType_OfficeIndicator_A",
    "BusinessInformation_BusinessType_RestaurantIndicator_A",
    "BusinessInformation_BusinessType_RetailIndicator_A",
    "BusinessInformation_BusinessType_ServiceIndicator_A",
    "BusinessInformation_BusinessType_WholesaleIndicator_A",
    "BusinessInformation_BusinessType_OtherIndicator_A",
}

_ACORD125_ENTITY_FIELDS = {
    "NamedInsured_LegalEntity_CorporationIndicator_A",
    "NamedInsured_LegalEntity_IndividualIndicator_A",
    "NamedInsured_LegalEntity_JointVentureIndicator_A",
    "NamedInsured_LegalEntity_LimitedLiabilityCorporationIndicator_A",
    "NamedInsured_LegalEntity_NotForProfitIndicator_A",
    "NamedInsured_LegalEntity_PartnershipIndicator_A",
    "NamedInsured_LegalEntity_SubchapterSCorporationIndicator_A",
    "NamedInsured_LegalEntity_TrustIndicator_A",
    "NamedInsured_LegalEntity_OtherIndicator_A",
}

_ACORD125_LOSS_ROW_FIELDS = (
    "LossHistory_OccurrenceDate_{row}",
    "LossHistory_LineOfBusiness_{row}",
    "LossHistory_OccurrenceDescription_{row}",
    "LossHistory_ClaimDate_{row}",
    "LossHistory_PaidAmount_{row}",
    "LossHistory_ReservedAmount_{row}",
    "LossHistory_ClaimStatus_OpenCode_{row}",
)


def _acord125_has_value(data: dict, field: str) -> bool:
    val = data.get(field)
    return val is not None and str(val).strip() not in ("", "null", "None", "Off", "No", "false", "0")


def _acord125_is_yes(data: dict, field: str) -> bool:
    return str(data.get(field) or "").strip().lower() in {"yes", "y", "true", "1", "on"}


def _acord125_any(data: dict, fields: set) -> bool:
    return any(_acord125_has_value(data, field) for field in fields)


def _acord125_row_started(data: dict, prefix: str, row: str) -> bool:
    needle = f"{prefix}_"
    suffix = f"_{row}"
    return any(k.startswith(needle) and k.endswith(suffix) and _acord125_has_value(data, k) for k in data)


def apply_acord125_missing_field_highlights(
    form_id: str,
    facts: dict,
    field_state: dict,
    confidence: dict,
) -> dict:
    """
    ACORD 125-only visual completeness layer.

    This does not change validation, scoring, mappings, or API shape. It only
    reuses the existing `missing_required` confidence label so the current PDF
    viewer/PDF renderer can paint empty required/triggered fields yellow.
    """
    if form_id != "ACORD_125":
        return confidence

    required_now = set(_ACORD125_REQUIRED_ALWAYS)
    managed = set(_ACORD125_REQUIRED_ALWAYS)

    managed.update(_ACORD125_CONTACT_FIELDS)
    if not _acord125_any(field_state, _ACORD125_CONTACT_FIELDS):
        required_now.update(_ACORD125_CONTACT_FIELDS)

    managed.update(_ACORD125_LOB_FIELDS)
    if not _acord125_any(field_state, _ACORD125_LOB_FIELDS):
        required_now.update(_ACORD125_LOB_FIELDS)

    managed.update(_ACORD125_BUSINESS_TYPE_FIELDS)
    if not _acord125_any(field_state, _ACORD125_BUSINESS_TYPE_FIELDS):
        required_now.update(_ACORD125_BUSINESS_TYPE_FIELDS)

    managed.update(_ACORD125_ENTITY_FIELDS)
    if not _acord125_any(field_state, _ACORD125_ENTITY_FIELDS):
        required_now.update(_ACORD125_ENTITY_FIELDS)

    for row in ("A", "B", "C", "D", "E", "F"):
        other = f"Policy_LineOfBusiness_OtherIndicator_{row}"
        desc = f"Policy_LineOfBusiness_OtherLineOfBusinessDescription_{row}"
        managed.add(desc)
        if _acord125_is_yes(field_state, other):
            required_now.add(desc)

        attachment_other = f"CommercialPolicy_Attachment_OtherIndicator_{row}"
        attachment_desc = f"CommercialPolicy_Attachment_OtherDescription_{row}"
        managed.add(attachment_desc)
        if _acord125_is_yes(field_state, attachment_other):
            required_now.add(attachment_desc)

    for row in ("B", "C"):
        row_fields = {
            f"NamedInsured_FullName_{row}",
            f"NamedInsured_MailingAddress_LineOne_{row}",
            f"NamedInsured_MailingAddress_CityName_{row}",
            f"NamedInsured_MailingAddress_StateOrProvinceCode_{row}",
            f"NamedInsured_MailingAddress_PostalCode_{row}",
        }
        managed.update(row_fields)
        if _acord125_row_started(field_state, "NamedInsured", row):
            required_now.update(row_fields)

    for row in ("A", "B", "C", "D"):
        location_fields = {
            f"CommercialStructure_Location_ProducerIdentifier_{row}",
            f"CommercialStructure_PhysicalAddress_LineOne_{row}",
            f"CommercialStructure_PhysicalAddress_CityName_{row}",
            f"CommercialStructure_PhysicalAddress_StateOrProvinceCode_{row}",
            f"CommercialStructure_PhysicalAddress_PostalCode_{row}",
            f"CommercialStructure_AnnualRevenueAmount_{row}",
            f"BusinessInformation_FullTimeEmployeeCount_{row}",
            f"BusinessInformation_PartTimeEmployeeCount_{row}",
            f"BuildingOccupancy_OperationsDescription_{row}",
            f"Construction_BuildingArea_{row}",
        }
        managed.update(location_fields)
        row_started = (
            _acord125_row_started(field_state, "CommercialStructure", row)
            or _acord125_row_started(field_state, "BuildingOccupancy", row)
        )
        if row_started:
            required_now.update(location_fields)

        # Beta Report Figure 27: "clarify owned vs tenant" + "require
        # occupancy/COPE details before property forms are considered
        # complete." Owner/Tenant and Inside/Outside-City-Limits are
        # COMPLEMENTARY checkbox pairs — exactly one is "Yes", the other is a
        # deliberate, correct "No" (not a gap). _acord125_has_value() treats
        # "No" as "no value" (the right behavior for the single yes/no
        # QUESTIONS checked elsewhere in this function), which would wrongly
        # flag the correctly-"No" half of a resolved pair as missing. So
        # these two pairs are checked separately: require only that AT LEAST
        # ONE half of each pair has an actual "Yes" answer, and flag only
        # ONE field per pair — never both halves of an already-resolved
        # answer.
        owner_field  = f"CommercialStructure_InsuredInterest_OwnerIndicator_{row}"
        tenant_field = f"CommercialStructure_InsuredInterest_TenantIndicator_{row}"
        other_interest_field = f"CommercialStructure_InsuredInterest_OtherIndicator_{row}"
        inside_field  = f"CommercialStructure_RiskLocation_InsideCityLimitsIndicator_{row}"
        outside_field = f"CommercialStructure_RiskLocation_OutsideCityLimitsIndicator_{row}"
        other_city_field = f"CommercialStructure_RiskLocation_OtherIndicator_{row}"
        managed.update({owner_field, tenant_field, other_interest_field, inside_field, outside_field})
        if row_started:
            # "Other" is now ALSO a deterministic resolution (see the
            # InsuredInterest_OtherIndicator registration above), so it must
            # count as "resolved" here too - otherwise a genuine Other answer
            # would leave Owner sitting at missing_required forever.
            if not (
                _acord125_is_yes(field_state, owner_field)
                or _acord125_is_yes(field_state, tenant_field)
                or _acord125_is_yes(field_state, other_interest_field)
            ):
                required_now.add(owner_field)
            # City-limits "Other" (unincorporated) stays GPT-eligible - there is
            # no deterministic "unincorporated" signal in the extracted facts -
            # but it must still count as a resolution so a GPT-filled "Other"
            # doesn't leave Inside/Outside falsely flagged missing.
            if not (
                _acord125_is_yes(field_state, inside_field)
                or _acord125_is_yes(field_state, outside_field)
                or _acord125_is_yes(field_state, other_city_field)
            ):
                required_now.add(inside_field)

        for trigger, dependent in (
            (f"CommercialStructure_RiskLocation_OtherIndicator_{row}", f"CommercialStructure_RiskLocation_OtherDescription_{row}"),
            (f"CommercialStructure_InsuredInterest_OtherIndicator_{row}", f"CommercialStructure_InsuredInterest_OtherDescription_{row}"),
        ):
            managed.add(dependent)
            if _acord125_is_yes(field_state, trigger):
                required_now.add(dependent)

    if _acord125_is_yes(field_state, "NamedInsured_LegalEntity_OtherIndicator_A"):
        required_now.add("NamedInsured_LegalEntity_OtherDescription_A")
    managed.add("NamedInsured_LegalEntity_OtherDescription_A")

    if _acord125_is_yes(field_state, "NamedInsured_LegalEntity_LimitedLiabilityCorporationIndicator_A"):
        required_now.add("NamedInsured_LegalEntity_MemberManagerCount_A")
    managed.add("NamedInsured_LegalEntity_MemberManagerCount_A")

    conditional_pairs = {
        "BusinessInformation_BusinessType_OtherIndicator_A": ["BusinessInformation_BusinessType_OtherDescription_A"],
        "CommercialPolicy_Question_AAICode_A": ["BusinessInformation_ParentOrganizationName_A", "Subsidiary_ParentSubsidiaryRelationshipDescription_A", "Subsidiary_ParentOwnershipPercent_A"],
        "CommercialPolicy_Question_AAJCode_A": ["Subsidiary_OrganizationName_A", "Subsidiary_ParentSubsidiaryRelationshipDescription_B", "Subsidiary_ParentOwnershipPercent_B"],
        "CommercialPolicy_Question_ABCCode_A": ["CommercialPolicy_AnyExposureToFlammableExplosivesChemicalsExplanation_A"],
        "CommercialPolicy_Question_AADCode_A": ["CommercialPolicy_PastLossesClaimsRelatingSexualAbuseDiscriminationNegligentHiringExplanation_A"],
        "CommercialPolicy_Question_KABCode_A": ["CommercialPolicy_PastFiveYearsAnyApplicantIndictedOrConvictedFraudBriberyArsonExplanation_A"],
        "CommercialPolicy_Question_KAMCode_A": ["CommercialPolicy_ApplicantOtherBusinessVenturesCoverageNotRequestedExplanation_A"],
        "CommercialPolicy_Question_KANCode_A": ["CommercialPolicy_ApplicantOwnLeaseOperateDronesExplanation_A"],
        "CommercialPolicy_Question_KAOCode_A": ["CommercialPolicy_ApplicantHireOthersOperateDronesExplanation_A"],
    }
    for trigger, dependents in conditional_pairs.items():
        managed.update(dependents)
        if _acord125_is_yes(field_state, trigger):
            required_now.update(dependents)

    # NOTE (deliberate, per product decision): the page-3 General Information
    # Yes/No questions (CommercialPolicy_Question_*Code_*) are intentionally NOT
    # forced to missing_required / yellow. They are not treated as required
    # fields on the form. When the AI leaves one blank it is still surfaced for
    # the broker via field_qa's "not_answered" review item (the pre-download
    # modal) — just without a yellow highlight on the PDF itself. Do not
    # re-add a loop that marks these codes required; that was tried and
    # reverted because 16 yellow compliance boxes made a form read as alarmingly
    # incomplete when most are edge-case questions.

    managed.update({"LossHistory_NoPriorLossesIndicator_A", "LossHistory_InformationYearCount_A"})
    loss_rows_started = any(_acord125_row_started(field_state, "LossHistory", row) for row in ("A", "B", "C"))
    if not _acord125_is_yes(field_state, "LossHistory_NoPriorLossesIndicator_A") and not loss_rows_started:
        required_now.update({"LossHistory_NoPriorLossesIndicator_A", "LossHistory_InformationYearCount_A"})
    for row in ("A", "B", "C"):
        row_fields = {tmpl.format(row=row) for tmpl in _ACORD125_LOSS_ROW_FIELDS}
        managed.update(row_fields)
        if _acord125_row_started(field_state, "LossHistory", row):
            required_now.update(row_fields)

    for field in managed:
        if field not in field_state and field not in confidence:
            continue
        if field in required_now and not _acord125_has_value(field_state, field):
            confidence[field] = "missing_required"
        elif confidence.get(field) == "missing_required":
            confidence[field] = "filled" if _acord125_has_value(field_state, field) else "low_confidence"

    return confidence


# GL schedule-of-hazards columns (ACORD 126), mirrored from _GL_HAZARD_COL_TO_KEY
# above so this stays in lockstep with the extraction-side mapping by
# construction rather than duplicating the row-letter regex.
_ACORD126_HAZARD_COLS = ("ClassCode", "Classification", "PremiumBasisCode", "Exposure", "TerritoryCode")
_ACORD126_HAZARD_ROWS = tuple("ABCDEFGHIJKLMN")


def apply_acord126_missing_field_highlights(
    form_id: str,
    facts: dict,
    field_state: dict,
    confidence: dict,
) -> dict:
    """
    ACORD 126-only visual completeness layer for the GL schedule of hazards.

    Every hazard column (`GeneralLiability_Hazard_*_A..N`) is marked
    "required": false in the raw schema, so the generic confidence pass at the
    bottom of map_facts_to_form never paints a blank cell yellow - a row with
    ClassCode and Exposure filled but TerritoryCode left blank looks IDENTICAL
    to an untouched row. That silently defeats the client's own requirement
    that missing hazard/class data stay a visible high-priority gap: the data
    pipeline (_resolve_gl_hazard_row) is careful never to fabricate a cell, but
    nothing then flags the resulting gap on the rendered PDF. Mirrors
    apply_acord125_missing_field_highlights: once a row has ANY hazard data
    (i.e. the broker/extraction started that class-code row), every other
    hazard column in that same row is forced missing_required (yellow) until
    it has a value too.
    """
    if form_id != "ACORD_126":
        return confidence

    for row in _ACORD126_HAZARD_ROWS:
        row_fields = [f"GeneralLiability_Hazard_{col}_{row}" for col in _ACORD126_HAZARD_COLS]
        if not any(f in field_state or f in confidence for f in row_fields):
            continue
        if not any(_acord125_has_value(field_state, f) for f in row_fields):
            continue  # row never started - an empty row is not a gap, just unused
        for f in row_fields:
            if not _acord125_has_value(field_state, f):
                confidence[f] = "missing_required"
            elif confidence.get(f) == "missing_required":
                confidence[f] = "filled" if _acord125_has_value(field_state, f) else "low_confidence"

    return confidence


# ACORD 140 Premises/Subject-of-Insurance schedule row letters. Note the raw
# schema skips "F" (verified against the real schema - not a bug here).
_ACORD140_PREMISES_ROWS = ("A", "B", "C", "D", "E", "G", "H", "I", "J", "K")

# Per-building COPE characteristics only exist for 2 building slots (A/B) in
# the raw schema, independent of the 10-row premises/value schedule above.
_ACORD140_BUILDING_ROWS = ("A", "B")

# Building-characteristic fields (Construction, Occupancy, Protection,
# Exposure) the client named explicitly (Figure 35): once a building slot has
# been started (see trigger below), these become required for THAT slot.
_ACORD140_BUILDING_CHAR_FIELDS = (
    "Construction_ConstructionCode",     # construction type
    "CommercialStructure_BuiltYear",     # year built
    "Construction_RoofMaterialCode",     # roof
    "BuildingFireProtection_ProtectionClassCode",  # protection class
)


def apply_acord140_missing_field_highlights(
    form_id: str,
    facts: dict,
    field_state: dict,
    confidence: dict,
) -> dict:
    """
    ACORD 140-only visual completeness layer for the COPE (Construction,
    Occupancy, Protection, Exposure) data the client flagged as silently
    incomplete (Figure 35): a premises row can show a placeholder-riddled or
    half-filled schedule - e.g. a Subject of Insurance row with an amount but
    no construction/year/roof/protection data for that building - and nothing
    previously marked the gap on the rendered PDF, because every ACORD 140
    field is "required": false in the raw schema (verified: 0 of 356 fields
    marked required there).

    Mirrors apply_acord125/126_missing_field_highlights' "started row" pattern
    exactly (a row/slot with ANY data in it makes its sibling fields required
    too), but writes a SEPARATE confidence label ("missing_required_gate"
    rather than "missing_required") so this is purely ADDITIVE: it cannot
    change behavior for any field that isn't part of the two groups below, and
    it never touches the pre-existing 125/126 highlight behavior.

    Two independent row groups, each gated on its own "started" signal:
      1. Premises/value schedule (10 slots): once a row has a Subject of
         Insurance code or a Limit Amount, that row's Limit Amount is
         required - this is the "building value / BPP value" the client
         named, keyed by whichever subject-of-insurance the row represents.
      2. Building characteristics (2 slots): once a building's premises row
         has started, its Construction Code, Built Year, Roof Material Code,
         and Protection Class Code become required.

    Deliberately NOT covered here (see CLAUDE.md audit notes): "occupancy"
    has no dedicated fillable field on the ACORD 140 schema itself (it lives
    on ACORD 125's operations description), and "business income" is only a
    Yes/No attachment indicator on this form - forcing a Yes/No box to a
    required value would fight the established evidence-gate "blank over
    wrong" rule for checkbox fields elsewhere in this codebase. Both remain
    real requirements, just satisfied by other existing mechanisms rather than
    fabricated here.
    """
    if form_id != "ACORD_140":
        return confidence

    def _mark_required(field: str) -> None:
        if field not in field_state and field not in confidence:
            return  # not part of this rendered schema instance
        if not _acord125_has_value(field_state, field):
            confidence[field] = "missing_required_gate"
        elif confidence.get(field) == "missing_required_gate":
            confidence[field] = "filled" if _acord125_has_value(field_state, field) else "low_confidence"

    for row in _ACORD140_PREMISES_ROWS:
        code_field   = f"CommercialProperty_Premises_SubjectOfInsuranceCode_{row}"
        amount_field = f"CommercialProperty_Premises_LimitAmount_{row}"
        if not (_acord125_has_value(field_state, code_field) or _acord125_has_value(field_state, amount_field)):
            continue  # row never started - an empty schedule row is not a gap
        _mark_required(amount_field)

    # Confirmed via a live multi-location test (2026-07-17): the Premises/value
    # schedule's row lettering and the building-characteristics fields' row
    # lettering are NOT the same axis. CommercialStructure_BuiltYear_A/B,
    # Construction_ConstructionCode_A/B etc. use SIMPLE addressing (_A =
    # building/premises 1, _B = building/premises 2 - confirmed against the
    # real schema's own CommercialStructure_PhysicalAddress_LineOne_A/B). But
    # the Premises schedule's SubjectOfInsuranceCode/LimitAmount fields use a
    # DIFFERENT 6-letter-block-per-premises scheme (see
    # _resolve_subject_of_insurance_row) - so a 2nd location's dollar amount
    # can legitimately land in row B, G, or anywhere else the gap-fill model
    # placed it, NOT necessarily row B. Gating building B's COPE requirement
    # on "did premises row B start" alone was confirmed WRONG: it only
    # happened to work when the 2nd location's data landed in row B by
    # chance, and silently missed the gap whenever it landed elsewhere.
    #
    # Fix: trigger primarily on the actual fact source - `property_locations`
    # genuinely having a 2nd (i.e. Nth) entry means building B/C/... COPE data
    # is required, independent of where the Premises schedule happened to put
    # the dollar amount. The premises-row check is kept as an OR fallback so a
    # session whose facts lack a clean property_locations list (but whose
    # schedule genuinely got real per-row data some other way) is still
    # covered - this only ever ADDS trigger coverage, never removes it.
    _locations = facts.get("property_locations") if isinstance(facts, dict) else None
    _location_count = len(_locations) if isinstance(_locations, list) else 0

    for _idx, row in enumerate(_ACORD140_BUILDING_ROWS):
        code_field   = f"CommercialProperty_Premises_SubjectOfInsuranceCode_{row}"
        amount_field = f"CommercialProperty_Premises_LimitAmount_{row}"
        premises_row_started = (
            _acord125_has_value(field_state, code_field) or _acord125_has_value(field_state, amount_field)
        )
        building_exists_in_facts = _idx < _location_count
        if not (premises_row_started or building_exists_in_facts):
            continue  # neither signal says this building/premises exists - not a gap
        for base in _ACORD140_BUILDING_CHAR_FIELDS:
            _mark_required(f"{base}_{row}")

    return confidence


# Fields that should NEVER be sent to GPT:
#  - Signature / approval fields (legal, must not be synthesised)
#  - Pure carrier-computed fields (Premium, Rate, Revision — underwriter fills these)
#  - Admin / form-metadata fields
# NOTE: "Indicator" is intentionally NOT here.  Business-logic checkbox/indicator
# fields (LOB, entity type, GL occurrence, WC statutory, etc.) ARE GPT-eligible so
# that Layer 2 can tick the right boxes from the raw document text.
_RAW_TEXT_SKIP_PATTERNS = [
    "Signature", "_Sig", "InsurerLetterCode",
    "Attachment_", "Hazard_", "Premium", "Rate_", "Revision",
    "EditionIdentifier", "NeedAppearances",
    "Underwriter", "CarrierCode", "PolicyNumber_Carrier",
]


def _run_coro_sync(coro):
    """Run an async coroutine from a synchronous executor thread.

    This is always called from run_in_executor() worker threads, which have no
    running event loop of their own. asyncio.run() is safe here — it creates a
    fresh loop for the thread and cleans it up on exit.
    """
    import asyncio as _asyncio
    return _asyncio.run(coro)


def _fill_empty_from_raw_text(
    mapped: dict,
    schema: dict,
    raw_text: str,
    form_id: str,
    filled_set: set,
) -> None:
    """DEPRECATED: replaced by _fill_unmatched_with_gpt(). Kept for rollback only. Do NOT call this function.

    Full-document LLM fill for fields still empty after fact-key mapping.

    Sends the COMPLETE OCR text (every word from every uploaded document) plus
    detailed field metadata from the form schema to the LLM.  The LLM reads the
    entire document and extracts exact values for each empty field.

    Designed for GPT-4o / Claude (large context windows).  Results are never
    cached in the fieldmap — they are document-specific values, not structural
    mappings.  Fields filled here are added to *filled_set* so the UI shows
    pink highlights for broker review.
    """
    empty_fields = [
        f for f in schema
        if _is_empty_llm_value(mapped.get(f))
    ]
    if not empty_fields:
        return

    text_fields = [
        f for f in empty_fields
        if not any(p in f for p in _RAW_TEXT_SKIP_PATTERNS)
    ]
    if not text_fields:
        return

    # Always send the FULL extracted text — the system is designed for GPT/Claude.
    # On Groq the call may fail if context is too long; that's caught below and
    # logged — partial filling is acceptable until the provider is upgraded.
    doc_text = raw_text  # no truncation

    # Batch size: GPT-4o / Claude handle 40+ fields per call comfortably.
    # Groq will likely fail on large docs — but that's acceptable at this stage.
    BATCH = 40

    # Pick the model name based on provider
    if ACTIVE_MODEL == "claude":
        llm_model = "claude-haiku-4-5-20251001"   # fast + large context
    else:
        llm_model = GPT_MODEL

    for start in range(0, len(text_fields), BATCH):
        batch = text_fields[start : start + BATCH]

        # Build rich field descriptions using form schema metadata
        field_specs = []
        for f in batch:
            info = schema.get(f, {})
            if isinstance(info, dict):
                tu   = info.get("tu", "")[:120]   # PDF tooltip / field label
                ft   = info.get("ft", "")          # field type (/Tx text, /Btn checkbox, /Ch dropdown)
                req  = " [REQUIRED]" if info.get("required") else ""
                desc = f"  - {f}{req}"
                if tu:
                    desc += f": {tu}"
                if "/Ch" in ft:
                    desc += " (dropdown)"
            else:
                desc = f"  - {f}"
            field_specs.append(desc)

        fields_block = "\n".join(field_specs)

        prompt = (
            f"You are an insurance form completion expert filling ACORD form {form_id}.\n"
            "Your task: read the COMPLETE insurance document text below and extract the exact "
            "value for each listed form field.\n\n"
            "Rules:\n"
            "  1. Read the ENTIRE document — values appear anywhere across all pages.\n"
            "  2. Extract the EXACT value as written in the document. Do not paraphrase.\n"
            "  3. Use JSON null (the unquoted literal null) for any field whose value is genuinely "
            "absent. You MUST NOT return the strings \"null\", \"None\", \"N/A\", \"NA\", "
            "\"Not Provided\", \"Not Specified\", \"Not Available\", \"Not Applicable\", \"Unknown\", "
            "\"TBD\", \"Undefined\", or \"\" — these will be discarded. Omitting the field from the "
            "JSON object is also acceptable and equivalent to null.\n"
            "  4. Return short scalar values only: names, dates, dollar amounts, addresses, codes.\n"
            "  5. Do NOT invent, estimate, or carry over values from other fields.\n"
            "  6. For date fields: use the format as found in the document (MM/DD/YYYY or similar).\n"
            "  7. For dollar amounts: include the $ sign and commas as found (e.g. $1,000,000).\n\n"
            "Return ONLY a single JSON object: {\"FieldName\": <string value> OR JSON null}\n\n"
            f"=== FORM FIELDS TO FILL ({form_id}) ===\n{fields_block}\n\n"
            f"=== COMPLETE INSURANCE DOCUMENT TEXT ===\n{doc_text}\n\n"
            "JSON Output:"
        )
        try:
            _coro    = groq_chat(llm_model, [{"role": "user", "content": prompt}], max_tokens=16000)
            raw_resp = _run_coro_sync(_coro)
            if raw_resp.startswith("```"):
                raw_resp = raw_resp.replace("```json", "").replace("```", "").strip()
            s, e = raw_resp.find("{"), raw_resp.rfind("}")
            if s != -1 and e != -1:
                result = json.loads(raw_resp[s : e + 1])
                batch_filled    = 0
                batch_rejected  = 0
                batch_rej_sample: List[str] = []
                for field, value in result.items():
                    if _is_empty_llm_value(value):
                        batch_rejected += 1
                        if len(batch_rej_sample) < 6:
                            batch_rej_sample.append(f"{field}={value!r}")
                        continue
                    mapped[field] = str(value).strip()
                    filled_set.add(field)
                    batch_filled += 1
                logger.info(
                    f"raw_text_fill form={form_id} batch_start={start} "
                    f"fields_sent={len(batch)} batch_filled={batch_filled} "
                    f"batch_rejected={batch_rejected} total_filled={len(filled_set)}"
                )
                if batch_rej_sample:
                    logger.info(
                        f"raw_text_fill REJECT_SAMPLE form={form_id} batch_start={start}: "
                        + "; ".join(batch_rej_sample)
                    )
        except Exception as ex:
            logger.warning(f"Raw-text fill batch failed (form={form_id}, start={start}): {ex}")


# ── Form-fill LLM budget constants ───────────────────────────────────────────
# gpt-4o-mini: 128k token context (~512k chars). We target 80k tokens per call
# so there is comfortable headroom for the system prompt, facts block, fields
# block, and the model's JSON reply.
#
# PROMPT BREAKDOWN (approximate):
#   fixed skeleton + rules  ~  1 500 chars
#   facts block             ~  5 000 chars  (varies by submission)
#   fields block            ~    100 chars per field
#   raw text section        = raw_chunk chars
#   reply headroom          ~ 30 000 chars  (JSON with ~350 fields)
#
# We budget: total_prompt_chars ≤ _GPT_CALL_BUDGET_CHARS per call.
# Raw-text chunks are sized so that (fixed_overhead + fields_block + chunk) ≤ budget.

# Max retries per individual LLM call
_FORM_FILL_BATCH_RETRIES = int(os.getenv("FORM_FILL_BATCH_RETRIES", "3"))
# Cap output tokens so one call can't burn the full TPM budget. The model itself
# allows far more (gpt-5.4-mini: 128k output); this cap is a cost/rate guard, not
# a model limit, and is deliberately kept small.
_FORM_FILL_MAX_TOKENS    = int(os.getenv("FORM_FILL_MAX_TOKENS",    "16000"))

# ── Call sizing, derived from the real model spec ────────────────────────────
# gpt-5.4-mini: 400,000-token context window, 128,000-token max output.
# `_MODEL_CONTEXT_TOKENS` is the window shared by input AND output, so the input
# budget must leave room for the reply.
#
# Measured on a real 271-page insurance package with the GPT-5 tokenizer
# (o200k_base): **4.01 chars/token**, so the historical 4:1 assumption is sound
# for this content. `_CHARS_PER_TOKEN_FLOOR` is deliberately pessimistic (3.5)
# because dense material — VIN blocks, class-code tables, money columns —
# tokenizes worse than prose, and under-estimating here is what produces a
# context-length rejection.
#
# WHY THIS MATTERS MORE THAN IT LOOKS: every extra document chunk multiplies the
# call count by the number of field sub-batches. The old 380,000-char budget used
# only ~24% of the window and split a 671,654-char submission into 3 chunks —
# 172 calls where 63 suffice. Sizing this correctly is the single biggest cost
# and latency lever in the pipeline (improving-ll.md C20).
_MODEL_CONTEXT_TOKENS   = int(os.getenv("MODEL_CONTEXT_TOKENS", "400000"))
_CHARS_PER_TOKEN_FLOOR  = float(os.getenv("CHARS_PER_TOKEN_FLOOR", "3.5"))
# Fraction of the window we are willing to occupy. The remainder absorbs
# tokenizer variance and the reply. 0.75 leaves ~100k tokens of headroom.
_CONTEXT_UTILISATION    = float(os.getenv("CONTEXT_UTILISATION", "0.75"))

# Reply headroom must match what we actually allow the model to emit, or a full
# 16k-token reply overruns the window we sized for. 16,000 tokens is ~64,000
# chars — the previous 30,000-char default under-reserved by more than half.
_GPT_REPLY_RESERVE_CHARS = int(os.getenv(
    "GPT_REPLY_RESERVE_CHARS",
    str(max(30_000, int(_FORM_FILL_MAX_TOKENS * 4))),
))

_CONTEXT_SAFE_BUDGET_CHARS = int(
    (_MODEL_CONTEXT_TOKENS * _CONTEXT_UTILISATION - _FORM_FILL_MAX_TOKENS)
    * _CHARS_PER_TOKEN_FLOOR
)
_GPT_CALL_BUDGET_CHARS = int(os.getenv(
    "GPT_CALL_BUDGET_CHARS", str(_CONTEXT_SAFE_BUDGET_CHARS)))
if _GPT_CALL_BUDGET_CHARS > _CONTEXT_SAFE_BUDGET_CHARS:
    # An explicit override above what the window can hold would make EVERY call
    # fail on context length. The self-tuning shrink would recover it, but only
    # after burning a wasted call per batch — clamp instead and say so.
    logger.warning(
        "gpt_fill: GPT_CALL_BUDGET_CHARS=%d exceeds what a %d-token window can "
        "hold at %.1f chars/token with a %d-token reply — clamping to %d.",
        _GPT_CALL_BUDGET_CHARS, _MODEL_CONTEXT_TOKENS, _CHARS_PER_TOKEN_FLOOR,
        _FORM_FILL_MAX_TOKENS, _CONTEXT_SAFE_BUDGET_CHARS,
    )
    _GPT_CALL_BUDGET_CHARS = _CONTEXT_SAFE_BUDGET_CHARS
# ── Document per call: QUALITY budget, not capacity (CALL2_RETRIEVAL_REDESIGN D1) ──
# THE ROOT CAUSE OF THE WRONG-VALUES BUG, and the single most important number in
# this file. Everything above derives how much the context window can HOLD.
# This derives how much the model can actually READ.
#
# Those are not the same number and the codebase already knew it. LLM call 1
# (`extraction_service._effective_chunk_size`) caps itself at 14,000 tokens of
# document per call and says why, in its own docstring:
#
#     "quality - how much document the model still reads carefully per call ...
#      **This is the one that binds.** ... Capacity is ~23x larger than quality
#      here. That gap is not waste to be reclaimed - it is the measured
#      difference between a stage that works and one that invents field names."
#
# Call 2 reclaimed exactly that gap. Measured on a 700,261-char package: the raw
# text allowance came out at 917,000 chars, so the document NEVER split, and every
# one of 43 calls carried ~175,000 tokens of document to ask about 40 fields - the
# field list was 1.4% of the prompt. Call 1 chunks the same document into 13 and
# works; call 2 sent it whole and filled ~26%.
#
# Same constant, same reasoning, applied to the stage that was not using it.
#
# RAISED 14,000 -> 28,000 ON 2026-08-13, BY OWNER DECISION. Be honest about what
# that is: 14,000 was call 1's chunk size, borrowed because it was the one figure
# this codebase had already proved a model reads carefully. It was never measured
# FOR call 2. 28,000 has not been measured either. What is known:
#
#   * Cost. A 716k package went 13 chunks -> 7, and gap fill 80 -> 49 calls,
#     because every field batch must walk every chunk. The owner ran one form for
#     $3+ against $1.50 for five forms before the cap existed. See C54/§3b.
#   * Distance from the known cliff. The measured quality collapse - the model
#     abandoning the ACORD field names and inventing its own, a VIN landing in a
#     tax-ID box - was at ~170,000 tokens per call (C21). 28,000 is 6x below it,
#     where 917,000 (the pre-D1 behaviour) was 5x above.
#   * The jobs differ. Call 1 asks ~170 open questions of a chunk; call 2 asks 40
#     named fields with their ACORD tooltips in front of it. Nothing proves the
#     harder job's limit is the right limit for the easier one - but nothing
#     proves it is not, either, and that is the whole risk in one sentence.
#
# `_CALL2_BUDGET_RATIO_MAX` below is the guard rail that survived the change, and
# `test_call2_document_budget_stays_a_small_multiple_of_call_1` enforces it.
#
# Setting this high enough restores the old single-chunk behaviour exactly (the
# document stops splitting), which is still the kill switch. The env var still
# wins, so an incident does not need a deploy.
_GAP_FILL_DOC_TOKENS_PER_CALL = int(
    os.getenv("GAP_FILL_DOC_TOKENS_PER_CALL", "28000"))
_GAP_FILL_DOC_CHARS_PER_CALL = int(
    _GAP_FILL_DOC_TOKENS_PER_CALL * 4)          # 4.01 chars/tok measured, o200k_base

# THE INVARIANT THAT REPLACED "call 2 <= call 1".
#
# The original defect was not that call 2 carried more than call 1. It was that
# call 2 derived its budget from the CONTEXT WINDOW and carried 917,000 chars -
# **16x** call 1, one chunk for a 271-page package, 26% fill. The bound that
# actually matters is that call 2 stays a small multiple of the proven quality
# budget rather than escaping to capacity, and 2 is a small multiple where 16 is
# a different pipeline.
#
# Raising THIS is the change that needs evidence. Raising the token count within
# it is a cost/quality dial the owner may turn.
_CALL2_BUDGET_RATIO_MAX = 2

# combined_gap_fill: max fields per LLM batch — 200 cuts batch count ~50% vs 100,
# halving how many times the raw document is re-shipped to OpenAI per session.
_COMBINED_FIELD_BATCH    = int(os.getenv("COMBINED_FIELD_BATCH",    "200"))
# combined_gap_fill: seconds to sleep between batches so the OpenAI TPM bucket
# refills — eliminates the 429-storm we observed in production logs.
_COMBINED_BATCH_PAUSE_S  = float(os.getenv("COMBINED_BATCH_PAUSE_S", "2.0"))

# Legacy constant — kept so existing env-var overrides still work but no longer
# used as the primary chunk size (it's derived dynamically from the budget above).
_FORM_FILL_RAW_CHUNK_CHARS = int(os.getenv("FORM_FILL_RAW_CHUNK_CHARS", str(40_000)))

# Tooltip (/TU) length caps. `_SCHEMA_TOOLTIP_MAX` bounds what schema extraction
# stores per field (the authoritative ACORD template question text — the real
# ACORD /TU values top out ~800 chars). `_PROMPT_TOOLTIP_MAX` bounds what the
# gap-fill prompt shows the model per field; it MUST be large enough to include
# the full compliance-question text that follows the ~85-char "Enter Y for a
# Yes response..." boilerplate, or the model answers questions it cannot read.
# Both replace a former hard 80-char cut that severed every question mid-preamble.
_SCHEMA_TOOLTIP_MAX = int(os.getenv("SCHEMA_TOOLTIP_MAX", "1000"))
_PROMPT_TOOLTIP_MAX = int(os.getenv("PROMPT_TOOLTIP_MAX", "500"))

# Fields per gap-fill LLM call. A single call carrying 200+ heterogeneous fields
# makes the model answer only a fraction of them (measured ~27% at 205 fields) —
# it silently drops questions it CAN answer from the document. Sub-batching the
# field list into focused groups of this size restores near-full completion so
# ALL data present in the dec pages actually lands on the form. `_FIELD_BATCH_POOL`
# bounds how many sub-batches run concurrently (the llm_limiter adaptive semaphore
# is the final TPM backstop).
_FIELD_FILL_BATCH = int(os.getenv("FIELD_FILL_BATCH", "40"))
_FIELD_BATCH_POOL = int(os.getenv("FIELD_BATCH_POOL", "4"))
# Pack table groups alongside ordinary fields (keeping each table WHOLE) instead
# of giving every table its own call. See `_pack_field_batches` for the measured
# waste this removes and the one quality risk it carries. Set 0 to revert.
_PACK_TABLES_WITH_FIELDS = os.getenv(
    "FIELD_BATCH_PACK_TABLES", "1").strip().lower() not in ("0", "false", "no")

# Partition field batches by ACORD family so one LLM call asks about one topic
# (CALL2_RETRIEVAL_REDESIGN D4). `0` restores dictionary-order packing.
_GROUP_BATCHES_BY_FAMILY = os.getenv(
    "FIELD_BATCH_GROUP_BY_FAMILY", "1").strip().lower() not in ("0", "false", "no")

# After every field batch has finished, sweep any document chunk that no batch
# ever sent (invariant I2). `0` disables the sweep - do not set in production.
_SWEEP_UNREAD_CHUNKS = os.getenv(
    "GAP_FILL_SWEEP_UNREAD", "1").strip().lower() not in ("0", "false", "no")

# Opt-in cost reduction: with chunk ranking on, stop walking a batch's chunks as
# soon as every field in it has an answer.
#
# DEFAULT OFF, and that is a deliberate reversal (D10). It is where most of the
# saving in this redesign lives - measured 650 -> 283 calls on a 700k / 5-form
# run - but it trades away the standing guarantee that every word of the document
# reaches the model even when the model answers
# (`test_an_answering_model_still_gets_the_whole_document`), which exists because
# production was measured dropping 46% of a document in exactly this way. The
# owner's stated requirement is full coverage; cost is the thing that gives.
_ROUTED_EARLY_STOP = os.getenv(
    "GAP_FILL_ROUTED_EARLY_STOP", "0").strip().lower() in ("1", "true", "yes")


# Sentinel marking a batch boundary in the packing stream (see _pack_field_batches).
_FAMILY_FLUSH = object()


def _field_family(field_name: str) -> str:
    """Leading ACORD name segment - the field's topical family. See D4.

    Delegates to `chunk_router.family_of` so the batcher and the router agree on
    what a family IS. Two definitions of that would put a group in one batch and
    rank it as another, which is the C12 duplication failure in a new place.
    """
    try:
        from services.chunk_router import family_of
        return family_of(field_name)
    except Exception:                                          # noqa: BLE001
        return (field_name or "").split("_", 1)[0]

# Constant worst-case size of the rendered fields block, used by _raw_budget so
# every sub-batch derives the SAME document chunk boundaries (see _raw_budget).
# ~250 chars/field is the measured worst case for a spec line carrying a full
# 500-char-capped tooltip; typical is ~193. Raising _FIELD_FILL_BATCH without
# raising this just means more batches fall back to their true size.
_MAX_FIELDS_BLOCK_CHARS = int(os.getenv("MAX_FIELDS_BLOCK_CHARS", str(_FIELD_FILL_BATCH * 250)))
# Absolute floor on the raw-text slice, only to guarantee the chunk loop makes
# progress. Deliberately SMALL: a large floor silently overrides the call-budget
# guard and lets the prompt overflow. Hitting it is a misconfiguration and is
# logged at ERROR.
_MIN_RAW_CHUNK_CHARS = int(os.getenv("MIN_RAW_CHUNK_CHARS", "2000"))

# Re-ask every field against every document chunk, instead of stopping once a
# batch's fields are all answered.
#
# The default is AUTO, and auto is the only defensible setting. Reasoning:
#
#   * On a SINGLE-chunk document there is nothing to re-scan, so rescanning and
#     not rescanning are byte-identical. The flag is irrelevant. That is the
#     common case today (the derived budget makes anything under ~890k chars one
#     chunk), which is why an OFF default looked free.
#   * On a MULTI-chunk document, OFF means a batch whose fields all get answered
#     from chunk 1 never sends chunks 2..N. That text reaches the model only if
#     some OTHER batch happens to still have unanswered fields — which is luck,
#     not a property. Measured: one 40-field batch against a 2-chunk document
#     shipped 1 call and skipped 46% of the document.
#
# So "OFF by default because it costs nothing on one chunk" quietly relied on the
# document staying under the line. Fixing `clean_text` (C24) removed ~0-25% of
# deletion from every document, which pushes a large package TOWARD the line —
# i.e. the shredder fix ARMED this hole. Coupling the decision to the actual
# chunk count removes the trap: zero cost when there is one chunk, correct
# behaviour the moment there are two, and no human has to notice a log line.
#
#   auto (default) — rescan iff the document actually split into >1 chunk
#   1 / true       — always rescan (forces the multi-chunk path for testing)
#   0 / false      — never rescan (legacy first-answer-wins; keeps the old,
#                    measured-lossy behaviour and is retained only as a kill
#                    switch if full rescan ever proves too expensive)
_GAP_FILL_RESCAN_MODE = os.getenv("GAP_FILL_FULL_RESCAN", "auto").strip().lower()


def _split_text_on_boundaries(text: str, budget: int) -> List[str]:
    """Cut `text` into <=`budget`-char pieces at paragraph/line boundaries.

    **The single source of truth for document chunking on the gap-fill side.**
    Every LLM pass that carries the uploaded document must route through this,
    for the reason C12 exists: three hand-rolled copies of the same loop is how
    one of them silently ends up truncating instead of chunking. It did — the
    umbrella probe used `raw_text[:60_000]` for months (C14).

    Guarantees, in this order of importance:
      1. **Concatenating the result reproduces every non-whitespace character of
         the input.** Only newlines at a cut point are dropped. Nothing is ever
         discarded, at any budget, for any input.
      2. Cuts land on a blank line, else a line break, else — only if the piece
         contains neither — mid-line at exactly `budget`.
      3. Always terminates: a cut at offset 0 can only happen when the text
         starts with the separator, and `lstrip` then removes it, so the same
         cut cannot recur. An empty piece is never emitted — the previous
         hand-rolled copies appended one, which cost a whole LLM call carrying
         an empty document.
    """
    budget = max(1, int(budget))
    chunks: List[str] = []
    rest = text or ""
    while rest:
        if len(rest) <= budget:
            chunks.append(rest)
            break
        cut = rest.rfind("\n\n", 0, budget)
        if cut == -1:
            cut = rest.rfind("\n", 0, budget)
        if cut == -1:
            cut = budget
        piece = rest[:cut]
        # A piece with no non-whitespace content is a whole LLM call carrying an
        # empty document. Skipping it cannot lose anything — losslessness here is
        # defined on non-whitespace characters, exactly as `clean_text`'s loss
        # metric is, and for the same reason (C24).
        if piece.strip():
            chunks.append(piece)
        rest = rest[cut:].lstrip("\n")
    return chunks or [text or ""]


def _rescan_enabled(n_chunks: int) -> bool:
    """Whether to re-ask every field against every chunk, for a `n_chunks` split."""
    if _GAP_FILL_RESCAN_MODE in ("1", "true", "yes"):
        return True
    if _GAP_FILL_RESCAN_MODE in ("0", "false", "no"):
        return False
    return n_chunks > 1                                   # auto


# Retained for callers/tests that referenced the old boolean. Under `auto` this
# is False, which is correct for the single-chunk case it is used to describe.
_GAP_FILL_FULL_RESCAN = _GAP_FILL_RESCAN_MODE in ("1", "true", "yes")

# Yes/No compliance questions per focused LLM call (see the dedicated compliance
# pass). Small groups keep per-question diligence high — one call with all ~40
# questions makes the model rush and borrow a plausible sentence for questions it
# should omit; a handful per call it reads each carefully against the document.
_COMPLIANCE_BATCH = int(os.getenv("COMPLIANCE_BATCH", "10"))
# Constant worst-case size of the rendered questions block (see the compliance
# batch builder). Same purpose as _MAX_FIELDS_BLOCK_CHARS: keep the document
# chunk boundaries — i.e. the cached prefix — identical across every batch.
_MAX_COMPLIANCE_BLOCK_CHARS = int(
    os.getenv("MAX_COMPLIANCE_BLOCK_CHARS", str(_COMPLIANCE_BATCH * 800))
)

# OpenAI populates a cached prefix only when a request COMPLETES. Firing every
# sub-batch concurrently therefore makes ALL of the first _FIELD_BATCH_POOL
# calls cache MISSES — on a 6-batch run that caps the hit rate near 33%. Running
# ONE call to completion first, then fanning out the rest, turns those into hits
# (~83% on the same run).
#
# It is NOT free, and it is not unconditionally right. Warming always adds one
# extra serialized wave: with N batches and pool P, waves go from ceil(N/P) to
# 1 + ceil((N-1)/P), while cache hits go from max(0, N-P) to N-1. That trade is
# clearly good when the prefix is large — a 75k-token document costs ~$0.15 in
# repeated prefills across one wave, and a cached prefill is also much faster to
# process, so the added wave is largely paid back. It is clearly BAD for a tiny
# prefix: on a 3 KB document, warming buys about half a cent and costs a whole
# round trip of wall-clock time the user is sitting through.
#
# So warming is gated on the prefix actually being worth caching. Below the
# threshold the run is short anyway and latency wins; above it, cost wins.
# LLM_PREFIX_WARMUP=0 disables warming entirely.
_PREFIX_WARMUP = os.getenv("LLM_PREFIX_WARMUP", "1").strip().lower() not in ("0", "false", "no")
_PREFIX_WARMUP_MIN_CHARS = int(os.getenv("LLM_PREFIX_WARMUP_MIN_CHARS", "40000"))

# Prefixes already warmed in this process, keyed by (stage, prefix hash).
#
# WHY (improving-ll.md C27): warming is worth one serialized wave to POPULATE a
# cold cache. It is worth nothing once that cache is warm. `_warmup_enabled` was
# local to `_fill_unmatched_with_gpt`, which `combined_gap_fill` invokes once per
# OUTER batch — so an 8-batch run warmed the same prefix up to 16 times (8 general
# + 8 compliance), and batches 2..8 each paid a full extra round trip of
# user-visible latency to warm a cache batch 1 had already filled. The prefix is
# identical across outer batches by construction (same system prompt, same facts,
# same document — that is the whole point of the C1 reordering), so one warm-up
# per (stage, prefix) is exactly right.
_warmed_prefixes: set = set()
_warmup_lock = threading.Lock()


def _claim_warmup(stage: str, prefix_key: str) -> bool:
    """True for the FIRST caller of a given (stage, prefix); False afterwards."""
    key = f"{stage}:{prefix_key}"
    with _warmup_lock:
        if key in _warmed_prefixes:
            return False
        _warmed_prefixes.add(key)
        return True


def reset_prefix_warmup() -> None:
    """Forget warmed prefixes. Called once per submission alongside the budget
    reset — a new document has a new prefix, and leaving stale keys in a
    long-lived worker would only grow the set forever."""
    with _warmup_lock:
        _warmed_prefixes.clear()

# ── Post-fill slot-value dedup — DEFAULT OFF since 2026-07-29 ────────────────
# This cleared any repeating-slot field (_A/_B/_C) whose value had already
# appeared in an earlier sibling. It was built as a safety net for the model
# copying one value into several slots of a "find N DISTINCT values" group.
#
# It is off because it was measured DESTROYING CORRECT DATA on a real ACORD 127
# run: a 3-vehicle fleet returned complete and correct, and the dedup deleted
# 40+ cells — garaging city/county/state/postal code, radius of use, rating
# territory, rate class, collision and comprehensive deductibles, and most
# coverage indicators — for rows B and C, because a fleet garaged at one address
# legitimately repeats those values down the column. Row A survived complete;
# rows B and C came out near-empty.
#
# It cannot be made correct here. A gap-fill call only ever sees a SUBSET of a
# schedule's columns (Pass 1/1.5 resolves some, `_COMBINED_FIELD_BATCH` splits
# others across outer batches), so "the model copied a value" and "the document
# really does say the same thing for every row" are indistinguishable from
# inside this function. Row-level comparison was tried and fails for the same
# reason — see the note at the dedup site.
#
# The asymmetry decides it: a wrongly REPEATED value is visible on the form and
# the broker fixes it; a wrongly DELETED value is invisible and reads exactly
# like "the document didn't say". Silent loss of verified document data is the
# worse failure, and the prompts now carry the constraint directly (the slot
# block says never copy a value across slots; the table block plus
# `already_filled` handle row identity).
#
# Set SLOT_VALUE_DEDUP=1 to restore it. When on, detected tables and any group
# under a detected schedule root are still exempt.
_ENABLE_SLOT_VALUE_DEDUP = os.getenv("SLOT_VALUE_DEDUP", "0").strip().lower() in ("1", "true", "yes")

# Retry backoff for a failed gap-fill call. The dominant failure is an OpenAI
# TPM (tokens-per-minute) 429 — the whole pipeline ships the document on every
# call, so a multi-form run can drain a 200k TPM budget. A TPM bucket refills
# over tens of seconds, so the old 1/2/4s backoff just re-hit the same 429 and
# burned all three attempts, after which the call returned {} and its fields
# went silently BLANK.
_LLM_RETRY_BACKOFF_BASE_S = float(os.getenv("LLM_RETRY_BACKOFF_BASE_S", "5"))
_LLM_RETRY_BACKOFF_MAX_S  = float(os.getenv("LLM_RETRY_BACKOFF_MAX_S", "45"))

# Evidence gate: max distinct Yes/No fields that may cite the same (near-duplicate)
# grounding quote before ALL of them are treated as boilerplate reuse and blanked.
# This existed to catch a false-"No" flood the model produced when it was BLIND to
# the question text (an 80-char tooltip truncation, fixed 2026-07-16, that severed
# every compliance question — see _SCHEMA_TOOLTIP_MAX). With the question text now
# actually reaching the model, moderate legitimate reuse is EXPECTED and correct:
# a single broad negation ("owns no boats, docks or floating structures; all
# operations are land-based") genuinely answers several distinct schedule/exposure
# questions "No", and for a narrow-operations applicant most facility/exposure
# questions truly ARE "No". A low cap here was blanking those correct answers
# (field-batching compounds it: related questions land in different sub-batches so
# the model cannot self-dedup its citations across them). Kept only as a
# defence-in-depth backstop against a pathological one-quote-for-everything
# regression, so the default is generous.
_EVIDENCE_QUOTE_REUSE_MAX = int(os.getenv("EVIDENCE_QUOTE_REUSE_MAX", "12"))

# Tighter reuse cap for AFFIRMATIVE ("Yes") answers. A genuine "Yes" exposure has
# its OWN specific description in the document (install work, a warranty clause, a
# hazmat-disposal sentence — each unique). A "Yes" whose grounding quote is SHARED
# with another question is almost always a borrow: the model reused a sentence
# meant for a different question (e.g. citing "manufactures to customer
# specifications" as proof of "foreign products used as components", or a
# subcontractor-COI sentence as proof of "vendors coverage required"). Those
# borrowed quotes are typically shared with a NEGATIVE answer, so a Yes-only cap
# blanks the false "Yes" without touching the legitimate "No" that shares the
# sentence. Default 1 = a "Yes" must cite evidence unique to it.
_EVIDENCE_YES_QUOTE_REUSE_MAX = int(os.getenv("EVIDENCE_YES_QUOTE_REUSE_MAX", "1"))

# ── Dedicated compliance Yes/No question pass ────────────────────────────────
# The general field-fill prompt buries ~40 Yes/No underwriting questions among
# 200 heterogeneous fields spread across separate sub-batches. In that setting
# the model reliably (a) defaults unanswered questions to "N" and (b) borrows a
# real negative sentence about one subject as fake "proof" for an unrelated
# question — the exact false-"N" flood seen on real ACORD 126 submissions. This
# pass instead sends ONLY the Yes/No questions, together, with their full text,
# under a prompt whose entire job is to answer them correctly OR leave them
# blank. Measured far fewer false "N"s and correct YES-by-meaning detection
# (e.g. hazardous-material disposal) than the general prompt produced.
_COMPLIANCE_SYSTEM_PROMPT = (
    "You are an expert commercial-insurance underwriter. You are given the full text of an "
    "insurance application / declarations document and a list of YES/NO underwriting questions "
    "from an ACORD form. Answer each question STRICTLY and ONLY from the document.\n\n"
    "For each question, choose exactly one:\n"
    "  \"Y\"  — the document contains SPECIFIC evidence the answer is YES (the applicant actually "
    "does the thing / has the exposure / the condition the question asks about).\n"
    "  \"N\"  — the document SPECIFICALLY discusses this question's subject and states it does NOT "
    "apply (no / none / not / never — about THAT subject).\n"
    "  omit — leave the field out entirely when the document does not specifically address this "
    "question's subject. On a typical submission this is the correct choice for MOST questions.\n\n"
    "HARD RULES — follow exactly:\n"
    "  1. SILENCE IS NOT \"N\". If the document does not specifically address a question's subject, "
    "OMIT that field. Never answer \"N\" merely because the subject is not mentioned. On a typical "
    "submission you will OMIT the majority of these questions — that is expected and correct.\n"
    "  2. NEVER BORROW EVIDENCE. A statement about subject A is not proof for a question about a "
    "different subject B, even if it is a negative statement. Before answering, check that the "
    "quote you would cite is SPECIFICALLY about the exact subject THIS question names; if it is "
    "about a different subject, you are borrowing — OMIT the question. Example: \"No blasting, "
    "demolition charges, or explosive materials\" answers ONLY a blasting/explosives question — it "
    "is NOT evidence about excavation, tunneling, planned demolition, joint ventures, or anything "
    "else; omit those unless separately stated.\n"
    "  3. EVERY \"Y\" or \"N\" REQUIRES a grounding quote: a verbatim span copied from the document "
    "that is SPECIFICALLY about THIS question's subject. If you cannot copy such a specific span, "
    "OMIT the field. A quote that merely happens to be negative is not enough — it must be about "
    "THIS question's subject.\n"
    "  4. NEVER reuse the same quote (or sentence) for two different questions. If you want to cite "
    "one sentence for a second question, that second question is almost certainly one to OMIT.\n"
    "  5. DETECT YES BY MEANING, not keywords. If the document describes the applicant actually "
    "doing or having what the question asks, answer \"Y\" even if the word \"yes\" never appears. "
    "Example: for 'do operations involve storing, disposing, or transporting hazardous material?', "
    "a document saying scrap and used cutting fluid are stored on site and removed by a licensed "
    "hazardous-waste hauler IS such an operation → \"Y\" (with that sentence as the quote).\n"
    "  6. Read the polarity of each question carefully. Some are phrased negatively (e.g. 'are "
    "subcontractors allowed to work WITHOUT providing a certificate of insurance?'). A document "
    "stating every subcontractor is REQUIRED to provide one means the answer is \"N\" — quote that "
    "requirement.\n"
    "  7. When genuinely unsure, OMIT. A blank the broker completes is always better than a guess.\n\n"
    "Return JSON with exactly two keys:\n"
    "  \"answers\": {\"<FieldName>\": \"Y\" or \"N\"}   — include ONLY questions you are answering.\n"
    "  \"quotes\":  {\"<FieldName>\": \"<verbatim quote from the document>\"}  — one for every answer.\n"
    "Every field in \"answers\" MUST have a matching entry in \"quotes\". Omit every other field."
)

_COMPLIANCE_RESPONSE_FORMAT = {
    "type": "json_schema",
    "json_schema": {
        "name": "compliance_answers",
        "schema": {
            "type": "object",
            "properties": {
                "answers": {"type": "object", "additionalProperties": {"type": "string"}},
                "quotes":  {"type": "object", "additionalProperties": {"type": "string"}},
            },
            "required": ["answers"],
            "additionalProperties": False,
        },
    },
}


# ── Token accounting ─────────────────────────────────────────────────────────
# Nothing in this codebase read `resp.usage` before 2026-07-29, so no cost or
# cache-hit claim could be verified. Every LLM call site now emits one LLM_SPEND
# line. `cache_pct` is the number that matters: it is the share of the input
# tokens OpenAI served from its automatic prefix cache (billed at ~10%). A run
# whose gap-fill calls sit near 0% means the prompt prefix is diverging between
# calls — see improving-ll.md §3 (C1/C2/C3).
# Wrapped in a blanket except: telemetry must NEVER be able to break a fill.
def _log_llm_spend(stage: str, form: str, resp: Any) -> None:
    try:
        u = getattr(resp, "usage", None)
        if u is None:
            return
        pt     = int(getattr(u, "prompt_tokens", 0) or 0)
        ct     = int(getattr(u, "completion_tokens", 0) or 0)
        cached = int(getattr(getattr(u, "prompt_tokens_details", None), "cached_tokens", 0) or 0)
        logger.info(
            "LLM_SPEND stage=%s form=%s in=%d cached=%d out=%d cache_pct=%d",
            stage, form, pt, cached, ct, (100 * cached // pt) if pt else 0,
        )
    except Exception:                                      # pragma: no cover
        pass


# ── Prefix-cache routing key ─────────────────────────────────────────────────
# `prompt_cache_key` is a ROUTING HINT, not a requirement. OpenAI's automatic
# prefix caching works without it — measured 99% cache_pct on a live 682k-char
# run with this disabled — so it is a marginal optimisation at best.
#
# It is therefore detected, never assumed. It was previously assumed supported
# and only disabled after the API rejected it, which cost one wasted full-size
# call per process: the deployed venv runs `openai==1.54.4`, which predates the
# parameter, and the check that "confirmed" support had been run against a
# different interpreter (system Python, `openai==2.30.0`). Inspect the SDK that
# will actually make the call, at import, and send nothing it cannot accept.
def _detect_prompt_cache_key_support() -> bool:
    if os.getenv("PROMPT_CACHE_KEY", "").strip().lower() in ("0", "false", "no"):
        return False
    try:
        import inspect as _inspect
        from openai.resources.chat.completions import Completions as _C
        params = _inspect.signature(_C.create).parameters
        return "prompt_cache_key" in params
    except Exception:                                      # pragma: no cover
        return False


_PROMPT_CACHE_KEY_SUPPORTED = _detect_prompt_cache_key_support()
logger.info(
    "gpt_fill: prompt_cache_key %s (routing hint only — automatic prefix caching "
    "works regardless)",
    "enabled" if _PROMPT_CACHE_KEY_SUPPORTED else "not supported by the installed openai SDK",
)


# ── Self-tuning call budget ──────────────────────────────────────────────────
# `_GPT_CALL_BUDGET_CHARS` is a GUESS about the model's usable input window. Set
# it too low and a large document is split into needless chunks — each extra
# chunk multiplies the call count by the number of field sub-batches, which is
# the dominant cost and latency term on a big package (measured: a 671k-char,
# 271-page submission made 172 calls at a 380k budget versus 63 at 760k).
# Set it too HIGH and every call 400s on context length, all three retries burn,
# `_chat_json` returns {} and whole batches ship BLANK — silently.
#
# So the budget shrinks itself. The first context-length rejection halves it
# process-wide and the affected batch is re-split and retried, instead of the
# run losing those fields. That makes raising GPT_CALL_BUDGET_CHARS safe to
# experiment with: guess high, and a wrong guess costs one wasted call rather
# than a form full of holes.
_effective_budget_chars = _GPT_CALL_BUDGET_CHARS
_budget_lock = threading.Lock()

# Per-thread "my own last call overflowed" flag.
#
# WHY THIS IS NOT JUST A BUDGET COMPARISON (improving-ll.md C28). The re-split
# loop used to detect overflow by testing whether the process-global
# `_effective_budget_chars` had dropped since the batch started. Sub-batches run
# concurrently on a thread pool, so ONE thread's context rejection made EVERY
# other in-flight batch conclude that IT had overflowed: each discarded the
# answers it had already collected and re-ran every chunk from scratch. One
# genuine overflow therefore cost up to `_FIELD_BATCH_POOL` batches' worth of
# duplicated LLM calls — wasted spend and wasted latency, for a condition that
# did not apply to them. Overflow is a property of a specific call, so it is
# tracked per thread.
_overflow_state = threading.local()


def _note_context_overflow() -> None:
    _overflow_state.hit = True


def _consume_context_overflow() -> bool:
    """True if THIS thread saw a context-length rejection since the last check."""
    hit = getattr(_overflow_state, "hit", False)
    _overflow_state.hit = False
    return hit


def reset_call_budget() -> int:
    """Restore the call budget to its configured value. Call once per submission.

    `_shrink_budget_after_overflow` only ever DECREASES the budget, and it is
    process-global, so before this existed a single pathological document halved
    the budget for every later submission handled by the same worker — quietly
    doubling their chunk count, call count and cost until the process restarted.
    Nothing ever put it back.

    Resetting per submission keeps the useful part of the behaviour (a document
    that overflows teaches the rest of ITS OWN run to use smaller chunks, across
    all outer batches) and drops the harmful part (that lesson leaking into
    unrelated submissions). The cost of being wrong is one wasted call on the
    next genuinely oversized document, which is exactly what the shrink-and-retry
    path is built to absorb.
    """
    global _effective_budget_chars
    with _budget_lock:
        if _effective_budget_chars != _GPT_CALL_BUDGET_CHARS:
            logger.info(
                "gpt_fill: restoring call budget %d -> %d chars for a new submission "
                "(a previous document had shrunk it; that must not be inherited)",
                _effective_budget_chars, _GPT_CALL_BUDGET_CHARS,
            )
        _effective_budget_chars = _GPT_CALL_BUDGET_CHARS
        return _effective_budget_chars
# How many halvings one batch may ride out. 5 spans a 32x over-estimate; the
# shrink floors at 40k chars so the loop always terminates.
_CONTEXT_SHRINK_ATTEMPTS = int(os.getenv("CONTEXT_SHRINK_ATTEMPTS", "5"))

_CONTEXT_ERROR_MARKERS = (
    "context length", "context_length", "maximum context",
    "too many tokens", "reduce the length", "string too long",
)


def _is_context_length_error(err: Exception) -> bool:
    status = getattr(err, "status_code", None) or getattr(
        getattr(err, "response", None), "status_code", None
    )
    if status not in (400, 413):
        return False
    msg = str(err).lower()
    return any(m in msg for m in _CONTEXT_ERROR_MARKERS)


def _shrink_budget_after_overflow(err: Exception) -> int:
    """Halve the call budget process-wide. Returns the new budget."""
    global _effective_budget_chars
    with _budget_lock:
        new = max(40_000, _effective_budget_chars // 2)
        if new < _effective_budget_chars:
            logger.error(
                "gpt_fill: model rejected the prompt on CONTEXT LENGTH — halving the call "
                "budget %d -> %d chars for the rest of this process and re-splitting the "
                "affected batch. GPT_CALL_BUDGET_CHARS is set too high for this model; "
                "lower it in the environment so future runs do not pay for this. err=%s",
                _effective_budget_chars, new, str(err)[:200],
            )
            _effective_budget_chars = new
        return _effective_budget_chars


def _is_response_format_rejection(err: Exception) -> bool:
    """True only when `err` means 'this model/SDK will not accept that
    response_format' — i.e. retrying with json_object is worth a second call.

    Deliberately narrow. The previous code fell back on ANY exception, so a
    timeout or a 429 (where OpenAI had already processed and BILLED the first
    request) immediately fired a second full-prompt call. A context-length 400
    likewise re-billed a call that could not possibly succeed. See
    improving-ll.md C7.
    """
    status = getattr(err, "status_code", None) or getattr(
        getattr(err, "response", None), "status_code", None
    )
    if status is None and isinstance(err, (TypeError, ValueError)):
        return True          # SDK rejected the kwarg locally; no request was sent
    if status != 400:
        return False
    msg = str(err).lower()
    return any(m in msg for m in ("response_format", "json_schema", "additionalproperties"))


def _salvage_truncated_json(text: str) -> Optional[dict]:
    """Best-effort recovery of a JSON object cut off by the output-token cap.

    A reply truncated mid-object raises JSONDecodeError. Re-sending the whole
    prompt (the old behaviour) re-bills every input token to get the SAME
    truncation at temperature 0, after the wasted output was already paid for.
    Instead, rewind to the last completed element and close the open brackets:
    the answers the model DID finish are perfectly good.

    Returns the salvaged dict, or None when nothing complete can be recovered.
    Never raises.
    """
    try:
        s = (text or "").strip()
        start = s.find("{")
        if start == -1:
            return None
        s = s[start:]
        stack: List[str] = []
        in_str = esc = False
        cut = -1
        cut_stack: List[str] = []
        for i, ch in enumerate(s):
            if in_str:
                if esc:
                    esc = False
                elif ch == "\\":
                    esc = True
                elif ch == '"':
                    in_str = False
                continue
            if ch == '"':
                in_str = True
            elif ch == "{":
                stack.append("}")
            elif ch == "[":
                stack.append("]")
            elif ch in "}]":
                if stack:
                    stack.pop()
            elif ch == "," and stack:
                # Everything before this comma is a complete element at this depth.
                cut, cut_stack = i, list(stack)
        if cut == -1:
            return None
        candidate = s[:cut] + "".join(reversed(cut_stack))
        parsed = json.loads(candidate)
        return parsed if isinstance(parsed, dict) and parsed else None
    except Exception:                                      # pragma: no cover
        return None


# ── General field-fill system prompt ─────────────────────────────────────────
# MODULE-LEVEL AND FORM-AGNOSTIC ON PURPOSE — do not reintroduce an f-string.
# This is sent as the `system` message of every gap-fill call. It used to be
# built inside _fill_unmatched_with_gpt with the form id interpolated into line
# one, which caused two separate defects (improving-ll.md C2):
#   1. combined_gap_fill passes a BATCH LABEL as form_id, so the model was
#      literally told "You are filling ACORD form COMBINED_B1of2" — it never
#      learned which ACORD form it was actually filling.
#   2. A per-batch system message means the cached prefix diverges at the first
#      few tokens of every call, so NOTHING cached.
# The real form identity is now supplied by the user message (see
# _build_user_prompt), where it is constant within a run and therefore still
# lands inside the cacheable prefix.
#
# ABSENCE CONVENTION: this prompt states OMISSION, and only omission, as the way
# to say "no value". It previously said "return JSON null" ~12 times against a
# single "omit" block, so the model emitted explicit nulls that _absorb threw
# away on arrival — pure waste at 6x the input price (improving-ll.md C5).
# Omitted and null are already treated identically by the caller
# (_is_empty_llm_value), so this is a cost change, not a behaviour change.
_PROMPT_SKELETON = (
    "You are filling an ACORD insurance form for an insurance submission.\n"
    "You have two sources to fill fields from:\n"
    "  1. EXTRACTED FACTS — structured key/value pairs a previous automated pass pulled\n"
    "     from the document. They are UNVERIFIED hints, not established truth: when a\n"
    "     fact conflicts with the RAW DOCUMENT TEXT, the document text wins. Use a fact\n"
    "     value when the field meaning matches the fact key and the document does not\n"
    "     contradict it. Boolean facts (has_general_liability, is_contractor, etc.) may\n"
    "     support a Yes/No checkbox answer, but every such answer still needs its own\n"
    "     grounding quote from the document (rule 8).\n"
    "  2. RAW DOCUMENT TEXT — the authoritative source: the uploaded document itself.\n"
    "     Use it for any field not answered by EXTRACTED FACTS, and to confirm any fact\n"
    "     you do use.\n\n"
    "PRIMARY RULE: Fill EVERY field you can from either source. "
    "Copy values verbatim. Do not invent or paraphrase — if a value is not present in\n"
    "either source, OMIT that field entirely.\n\n"
    "Return exactly three keys:\n"
    '  "values":            {FieldName: <string value>}   (include ONLY fields you filled)\n'
    '  "raw_text_sourced":  [FieldName, ...]  (list only fields whose value came from raw text)\n'
    '  "question_grounding":{FieldName: <short verbatim quote>}  (every Question-code field\n'
    '                        and every checkbox — Yes/No field — see rule 8)\n\n'
    "ABSENCE PROTOCOL — read carefully:\n"
    "  When a field's value is not present in the document text, you MUST leave that field "
    "OUT of the \"values\" object entirely. You MUST NOT return any of the following strings as a "
    "stand-in: \"null\", \"None\", \"N/A\", \"NA\", \"Not Provided\", \"Not Specified\", "
    "\"Not Available\", \"Not Applicable\", \"Unknown\", \"TBD\", \"Undefined\", \"\". "
    "These strings will be discarded as if you had returned no value at all — which makes "
    "the response useless. If the value is missing, omit the key. If the value "
    "is present but extremely short (e.g., a single digit, a single letter, a single word), "
    "return that exact string — short is fine, sentinel strings are not.\n\n"
    "OMIT-WHEN-UNKNOWN PROTOCOL (REQUIRED — affects response size):\n"
    "  When you have no value for a field you MUST omit it from the \"values\" object. "
    "Do NOT emit explicit JSON nulls for absent fields — omission is the required form. "
    "An omitted field is treated identically to null by the caller. "
    "This rule is mandatory: a response that lists every field with null will exceed the "
    "output-token cap and lose answers at the end. Only include fields you actually filled. "
    "Do NOT include a field in \"raw_text_sourced\" unless you actually copied its value "
    "from the document text.\n\n"
    "Rules:\n"
    "  1. EXACT values only — copy verbatim from the document text. Do not paraphrase or invent.\n"
    "  2. Omit the field entirely when the value is genuinely absent. Never emit an explicit\n"
    "     JSON null, and never the string \"null\".\n"
    "  3. Checkbox/indicator fields (marked 'checkbox — Yes/No'): return \"Yes\" or \"No\" ONLY.\n"
    "     If the document does not say one way or the other, OMIT the field — do NOT default to \"No\".\n"
    "     Every Yes/No you give here also needs a grounding quote in \"question_grounding\" — see rule 8.\n"
    "     Examples of how to fill checkboxes:\n"
    "     - Policy_Status_BoundIndicator: \"Yes\" if the document is a bound policy, else \"No\"\n"
    "     - Policy_Status_QuoteIndicator: \"Yes\" if document is a quote/application, else \"No\"\n"
    "     - Policy_LineOfBusiness_CommercialGeneralLiability: \"Yes\" if GL coverage is requested\n"
    "     - NamedInsured_LegalEntity_CorporationIndicator: \"Yes\" if entity type is Corporation\n"
    "     - BusinessInformation_BusinessType_ContractorIndicator: \"Yes\" if business is a contractor\n"
    "     - LossHistory_NoPriorLossesIndicator: \"Yes\" only if the document clearly indicates the insured has no prior/known losses (by meaning - e.g. \"no known losses\", \"loss-free\", \"clean loss history\"); NEVER infer \"Yes\" from losses simply being unmentioned. If it does not clearly say so, omit the field.\n"
    "  4. Dollar amounts: include $ and commas as found (e.g. $1,000,000).\n"
    "  5. Do NOT fill premium/rate/underwriter-computed fields — omit them.\n"
    "  6. List ALL fields you fill in raw_text_sourced. Do NOT list fields you omitted.\n"
    "  7. REPEATING GROUP fields (shown as '── REPEATING GROUP … ──' blocks in the field list):\n"
    "     These are sibling fields sharing the same base name but different _A/_B/_C suffixes.\n"
    "     They represent separate sequential entries — not repeated copies of one value.\n"
    "       a) Find each separate real value of that type in the document, in the order they appear.\n"
    "       b) Put the 1st one you find in slot _A, the 2nd in slot _B, the 3rd in slot _C, and so on.\n"
    "       c) NEVER copy the same value into multiple slots — that is always wrong.\n"
    "       d) If the document has fewer values than slots, leave the extra slots out entirely.\n"
    "       e) A slot's value must be copied verbatim from the document (a name, amount, date, …).\n"
    "          NEVER write text that describes the slot itself (e.g. never output the words\n"
    "          'first value', '2nd distinct value', or any ordinal/counting phrase as if it were\n"
    "          the answer — that describes what to do, it is not a value).\n"
    "     Example: 3 slots for Insurer_FullName but only 2 insurer names found →\n"
    "       _A = \"Acme Insurance\", _B = \"Beta Insurance\", and _C left out entirely.\n\n"
    "  8. EVERY Yes/No answer needs a grounding quote. This covers THREE field shapes:\n"
    "     - Question-code fields (name contains \"_Question_<code>Code_\"; the form's\n"
    "       compliance Yes/No questions, e.g. \"...any exposure to radioactive materials\").\n"
    "     - EVERY checkbox field marked 'checkbox — Yes/No' in the field list, whatever it is\n"
    "       named - auto ownership, building features, coverage accept/reject, entity type, line\n"
    "       of business, anything else. One additionally marked [HIGH-IMPACT] is a field the\n"
    "       client specifically flagged (auto ownership / hired-non-owned / leasing /\n"
    "       hazardous-materials / maintenance) and deserves particular care, but this rule\n"
    "       applies equally to every checkbox, labeled or not.\n"
    "     - Any other field whose own description says \"Enter Y for a Yes response... Input\n"
    "       N for a No response\" (a plain text Yes/No field that is neither a checkbox nor a\n"
    "       Question-code field, e.g. a spoilage or refrigeration-maintenance Y/N field).\n"
    "       a) Answer \"Y\"/\"Yes\" or \"N\"/\"No\" ONLY when the document explicitly addresses\n"
    "          that exact question. If the document never mentions the topic, OMIT the field\n"
    "          - do NOT answer from silence and do NOT default to \"N\"/\"No\".\n"
    "       b) For EVERY such answer you give, add an entry to \"question_grounding\":\n"
    "          {FieldName: quote}, where quote is a short VERBATIM excerpt copied from the\n"
    "          document that is your specific basis for THAT answer.\n"
    "          - When the document poses the question and states the answer beside it\n"
    "            (e.g. \"Are any vehicles leased to others? No\" or \"Is there a vehicle\n"
    "            maintenance program in operation? Yes\"), cite the WHOLE question-and-answer\n"
    "            together, and you MUST INCLUDE the \"Yes\"/\"No\"/\"Y\"/\"N\" answer word itself\n"
    "            inside the quote - the quote is not valid proof without it.\n"
    "          - Otherwise, for a \"N\", the quote MUST be the sentence where the document\n"
    "            denies the topic (e.g. \"has no prior cancellations\"); never cite an\n"
    "            unrelated sentence just to have a quote.\n"
    "          Do not reuse the same quote for more than one question.\n"
    "       c) Whenever you answer \"Y\" and the form has a matching \"...Explanation\" or\n"
    "          \"...OtherDescription\" field for that question, ALSO fill that field with the\n"
    "          specific detail from the document (the same content as your grounding quote\n"
    "          is fine).\n"
    "       d) A PERCENTAGE field (an exposure share or split - '% of total sales',\n"
    "          installation/service/repair work %, subcontracted %) follows the same\n"
    "          discipline: fill it ONLY when the document states that percentage, and add\n"
    "          its \"question_grounding\" entry - the VERBATIM sentence containing the\n"
    "          number WITH its % sign. A percentage answer without that quote is\n"
    "          discarded, so an unquoted percentage is a wasted answer.\n\n"
    "  9. ENTITY DISCIPLINE - a submission names several DIFFERENT parties: the APPLICANT\n"
    "     (the named insured the form is about), the PRODUCER/AGENCY submitting it, and\n"
    "     the CARRIER/INSURER issuing the policy (including its claims and servicing\n"
    "     departments). Fill a party's field ONLY from a value the document labels as\n"
    "     belonging to THAT party.\n"
    "       - Applicant/NamedInsured contact, phone, email and website fields hold the\n"
    "         APPLICANT'S OWN details only. A phone or email labeled 'Claim Reporting',\n"
    "         'Servicing Carrier', or printed inside the producer's or carrier's block is\n"
    "         NEVER the applicant's - OMIT the field instead of borrowing it.\n"
    "       - Never reuse one party's value to fill another party's empty field. A blank\n"
    "         box is correct when that party's own value is not stated.\n"
    "       - An identifier keeps its own label: a number the document labels 'Agent\n"
    "         Number' or 'Account Number' is NOT a state producer license number, NOT a\n"
    "         FEIN, and NOT an NPN. A phone number is never an email address. If the\n"
    "         document does not state the specifically-labeled identifier a field asks\n"
    "         for, omit that field.\n\n"
)
_SKELETON_CHARS = len(_PROMPT_SKELETON)


def _compliance_question_text(tooltip: str) -> str:
    """Extract the human-readable question from an ACORD Yes/No field tooltip.

    Three real shapes (verified against the schemas):
      * '...The response to the question, "<Q>"?.'  (Question-code TEXT fields)
      * '...Indicates a "Yes"/"No" response to the question, "<Q>"?. As used
        here, ...'  (checkbox-PAIR form of the same convention — ACORD
        125/126/127/130/131/133/141/160/186 — often followed by trailing
        instructional text after the question mark that must NOT be included)
      * 'Enter Y ... Input N ... response. <description>.'  (…YesNoCode_ text
        fields on ACORD 140/25, which have no "the question," clause)
    Falls back to the whole tooltip if none is found."""
    tu = (tooltip or "").strip()
    if not tu:
        return ""
    low = tu.lower()
    marker = "the question,"
    idx = low.find(marker)
    if idx != -1:
        q = tu[idx + len(marker):].strip().strip('."“” ').strip()
        # Stop at the question's own "?" — anything after (e.g. "As used here,
        # if there was no prior coverage, indicate why...") is instructional
        # text about OTHER fields, not part of this question.
        qmark = q.find("?")
        if qmark != -1:
            q = q[: qmark + 1]
        return q or tu
    # No "the question," clause — drop the two "Enter Y…response." / "Input N…
    # response." preamble sentences and keep the trailing description.
    parts = tu.split("response.")
    if len(parts) >= 3:
        tail = "response.".join(parts[2:]).strip()
        return tail.strip('."“” ').strip() or tu
    return tu


# Tokens the LLM commonly returns to signal "not found" — all should be treated
# as empty/null regardless of casing. Kept here so the prompt and the post-filter
# stay in sync; update both sides together if you add new sentinels.
# A supporting text for a "YES" answer that LEADS with a denial (see the
# evidence gate's affirmative branch). Kept deliberately narrow.
_YES_NEGATIVE_LEAD_RE = re.compile(r"^\s*(?:no|none|not|never|neither)\b")

# A NAME box holding a negation SENTENCE instead of a name. Graded test run:
# PARENT COMPANY NAME came back "The Named Insured Has No Parent Company And
# Has No Subsidiaries." — evidence text title-cased into an organization-name
# field. Scoped hard: organization/full-name fields only, six words or more,
# containing a whole-word negation, ending like a sentence. "First Bank of
# Denver" (4 words, no negation) and every real company name tested pass.
_NAME_FIELD_RE = re.compile(r"(?:FullName|OrganizationName)_[A-N]$")
_NEGATION_SENTENCE_RE = re.compile(r"\b(?:no|not|none|never)\b", re.I)


# A row-B+ NARRATIVE that merely repeats row A's. Graded fixture: ACORD 125's
# "DESCRIPTION OF OPERATIONS OF OTHER NAMED INSUREDS"
# (CommercialPolicy_OperationsDescription_B) came back holding a verbatim copy
# of the PRIMARY insured's operations. ACORD's own tooltips make the two boxes
# different subjects, so a duplicate is a copy, not a record.
#
# NOT the banned slot dedup (C18): that one deleted correct fleet CELLS, where
# three trucks in one city legitimately repeat a value. This fires only on
# GAP-FILL values, only on rows B+, only on free text of at least
# _NARRATIVE_DUP_MIN_CHARS, and schedule-bound rows never reach it because they
# resolve deterministically and are absent from `gpt_filled_set`.
_NARRATIVE_DUP_MIN_CHARS = 40


def _duplicates_primary_row_narrative(field_name: str, value, mapped: dict) -> bool:
    m = _SCHED_ROW_RE.match(field_name)
    if not m or m.group(2) == "A":
        return False
    text = str(value or "").strip()
    if len(text) < _NARRATIVE_DUP_MIN_CHARS:
        return False
    primary = mapped.get(f"{m.group(1)}_A")
    if primary is None or not str(primary).strip():
        return False
    return _is_near_duplicate_text(_sim_tokens(text), _sim_tokens(str(primary)))


def _duplicates_primary_sibling(field_name: str, value, mapped: dict) -> bool:
    """A SECONDARY box holding exactly what its PRIMARY twin holds.

    ACORD pairs Primary/Secondary contact phones and e-mails so a broker can
    record TWO ways to reach someone. Live run: both secondary boxes came back
    carrying the primary's own phone and e-mail - one contact detail printed
    twice, which tells a carrier nothing and reads as a second contact that
    does not exist. Pure name-pair derivation: no field list, works on any
    form that uses ACORD's Primary/Secondary convention."""
    if "Secondary" not in field_name:
        return False
    text = str(value or "").strip()
    if not text:
        return False
    primary = mapped.get(field_name.replace("Secondary", "Primary"))
    if primary is None or not str(primary).strip():
        return False
    return _normalize_for_search(text) == _normalize_for_search(str(primary))


def _is_negation_sentence_in_name_field(field_name: str, value) -> bool:
    if not _NAME_FIELD_RE.search(field_name):
        return False
    s = str(value or "").strip()
    return (len(s.split()) >= 6
            and s.endswith(".")
            and bool(_NEGATION_SENTENCE_RE.search(s)))


_LLM_EMPTY_SENTINELS = frozenset({
    "", "null", "none", "nil", "n/a", "na", "n.a.",
    "not provided", "not specified", "not available", "not applicable",
    "unknown", "tbd", "to be determined", "undefined", "blank",
    # Live run 2026-08-10: the literal string "not present" was STAMPED into
    # the ACORD 125 NAIC CODE box — the model's absence phrasing was not in
    # this set, so it survived _is_empty_llm_value and reached the PDF.
    "not present", "not stated", "not shown", "not found", "not listed",
    "not mentioned", "not in document", "not on file", "not identified",
    "not indicated", "none found", "missing",
    # A declarations page states absence in its OWN vocabulary, and those
    # phrases were being stamped as if they were values. Live 25-page run:
    # the ADDITIONAL INTEREST block came back with name/address/city =
    # "None Scheduled" and the STATE and COUNTRY code boxes = "NONE
    # SCHEDULED", read straight off "ADDITIONAL INTERESTS - NONE SCHEDULED.
    # No mortgageholder, loss payee, lienholder..." The same document says
    # NOT PURCHASED, NOT ATTACHED, NOT INCLUDED, NOT RATED, NO COVERAGE and
    # NOT REPORTED dozens of times. Every one of them means the box is empty.
    "none scheduled", "not scheduled", "not reported", "not purchased",
    "not attached", "not included", "not rated", "no coverage",
    "not in force", "not covered", "not required", "not written",
})


def _norm_field_key(name: str) -> str:
    """Case/punctuation-insensitive form of a field name for reply matching."""
    return re.sub(r"[^a-z0-9]", "", str(name).lower())


def _recover_sent_field(returned_key: str, sent_by_norm: Dict[str, List[str]]) -> Optional[str]:
    """Map a model-returned key that is NOT verbatim in the sent field list back
    to the sent field it unambiguously names, or None.

    Why: on long documents the model stops copying field names exactly — it
    drops the ``_A`` row suffix, changes case, or swaps underscores (measured
    live: a call that sent 39 fields got 60 answers under invented names and 57
    were discarded; the DATA was right, the KEYS were not). Recovering the
    unambiguous subset converts paid-for answers into filled boxes at zero cost.

    Deliberately conservative — a wrong remap stamps a value into the wrong
    box, which is worse than the discard:
      * normalized-exact match, accepted only when exactly ONE sent field
        normalizes to the same string;
      * missing row suffix (``Producer_FullName`` for ``Producer_FullName_A``),
        accepted only when exactly ONE sent field is that name plus a single
        row letter.
    Anything ambiguous stays unmatched and is counted/logged as before."""
    n = _norm_field_key(returned_key)
    if not n:
        return None
    exact = sent_by_norm.get(n)
    if exact and len(exact) == 1:
        return exact[0]
    if not exact:
        suffixed = [
            f for letter in "abcdefghijklmn"
            for f in sent_by_norm.get(n + letter, ())
        ]
        if len(suffixed) == 1:
            return suffixed[0]
    return None


def _is_empty_llm_value(value) -> bool:
    """Return True if `value` is a JSON null, any string the LLM uses to mean 'not
    found', or a leaked-instruction / template placeholder that must never be
    stamped onto a form.

    This catches true JSON nulls, the literal strings ("null", "None", "N/A",
    "Not Provided", etc.) that GPT-4o-mini frequently emits in JSON mode when the
    instruction is "use null when not found", AND placeholder text like "1st
    distinct value" that a confused model occasionally echoes back from the
    repeating-group prompt instructions instead of a real value (see
    services/placeholder_detector.py). Comparison is case-insensitive and trims
    surrounding whitespace.
    """
    if value is None:
        return True
    if isinstance(value, str):
        if value.strip().lower() in _LLM_EMPTY_SENTINELS:
            return True
        try:
            from services.placeholder_detector import is_placeholder_value
            is_ph, _reason = is_placeholder_value(value)
            if is_ph:
                return True
        except Exception:                                  # pragma: no cover
            pass
        return False
    if isinstance(value, (list, dict)):
        return len(value) == 0
    return False


def _fill_unmatched_with_gpt(
    unmatched_fields: dict,
    facts: dict,
    form_id: str,
    model: str = None,
    raw_text: str = "",
    already_filled: Optional[dict] = None,
    form_label: Optional[str] = None,
) -> dict:
    """GPT form-fill: fills unmatched fields from structured facts + full raw document text.

    ``form_id`` is a LOGGING/telemetry label only. ``combined_gap_fill`` passes a
    batch label ("COMBINED_B1of2") for it, which is useful in logs and useless to
    the model. ``form_label`` is what the MODEL is told it is filling — pass the
    real ACORD form name(s) (e.g. "ACORD_125, ACORD_25"). Defaults to ``form_id``
    so every existing caller keeps its current behaviour.

    Strategy — single-pass chunking:
      Everything (facts + fields + raw text) goes into one prompt per chunk.
      The raw text is the only thing that needs chunking; facts and fields are
      small enough to repeat in every call.

      Chunk sizing is automatic:
        chunk_chars = _GPT_CALL_BUDGET_CHARS - reply_reserve - fixed_overhead - fields_block
      where fixed_overhead = prompt skeleton + facts block (measured, not guessed).

      For a short doc (< budget): exactly 1 LLM call.
      For a large doc (500k tokens): N calls, each carrying ALL still-empty fields
      + one slice of the raw text.  Fields resolved in earlier chunks are dropped
      from later chunks, shrinking the fields block and leaving more budget for text.

      Conflict resolution: if multiple chunks return different values for the same
      field, the most-frequent candidate wins (majority vote across chunks).
      Structured-facts values always beat raw-text values.

    ``already_filled`` (optional): {field_name: value} for SIBLING fields already
    resolved deterministically by Pass 1/1.5 (e.g. compute_form_gaps' ``mapped``
    return) - NOT sent to the model as fields to fill, but used to tell it which
    rows of a multi-column TABLE (see _table_group_block) are already spoken for,
    so it doesn't re-discover the same real-world entry and duplicate it into a
    different row. Without this, a table whose row A was already resolved by
    Pass 1 (so row A never reaches this function at all) has no way to know row
    A "used up" the first entry the raw text describes - live testing showed
    that produces exactly the failure you'd expect: the model treats whatever
    row IS in its field list as the first slot, re-finds the SAME entry Pass 1
    already captured, and duplicates it there instead of finding the next one.
    """
    already_filled = already_filled or {}
    # What the MODEL is told it is filling. Never the batch label — see docstring.
    form_label = form_label or form_id
    if not unmatched_fields:
        return {"filled_values": {}, "new_mappings": {}, "raw_text_fields": set(), "question_grounding": {}, "model_used": model or GPT_MODEL}

    try:
        # Gap fill dispatches its LLM calls onto worker threads, so it uses the
        # SYNC client — sharing the async one across per-call event loops is what
        # caused the generation-hang deadlock (see the factory's docstring).
        _sync_client = _get_openai_form_fill_client_sync()
    except RuntimeError as _e:
        logger.warning("gpt_fill: %s — skipping GPT form fill pass", _e)
        return {"filled_values": {}, "new_mappings": {}, "raw_text_fields": set(), "question_grounding": {}, "model_used": model or GPT_MODEL}

    llm_model = model or GPT_MODEL

    # ── Filter out schedule/admin fields ─────────────────────────────────────
    # GL schedule-of-hazards DATA columns are exempted from the skip patterns:
    # they contain "Hazard_" (and PremiumBasisCode contains "Premium") but ARE
    # broker-fillable, so when structured extraction missed them the gap-fill LLM
    # must still get a chance to read them from raw text (client Figure 29).
    eligible_fields = {
        f: meta
        for f, meta in unmatched_fields.items()
        if not _is_schedule_field(f)
        and (
            _GL_HAZARD_FILLABLE_RE.match(f)
            or not any(p in f for p in _RAW_TEXT_SKIP_PATTERNS)
        )
    }
    if not eligible_fields:
        return {"filled_values": {}, "new_mappings": {}, "raw_text_fields": set(), "question_grounding": {}, "model_used": llm_model}

    field_list = list(eligible_fields.keys())
    raw_text_used = bool(raw_text and raw_text.strip())

    # ── Shared accumulators ───────────────────────────────────────────────────
    # candidate_counts[field][value] = number of chunks that returned that value.
    # Majority vote across chunks resolves conflicts between chunks.
    candidate_counts: Dict[str, Dict[str, int]] = {f: {} for f in field_list}
    all_raw_fields:   set                       = set()
    all_question_grounding: Dict[str, str]      = {}
    # grounding_by_value[field][value] = the quote the model gave FOR THAT VALUE.
    # The vote picks the value; this hands the winner its own citation instead of
    # whichever chunk replied last (see _absorb).
    grounding_by_value: Dict[str, Dict[str, str]] = {}
    # Permanently-failed LLM calls in this pass. A failed call returns {}, which
    # downstream looks identical to "the model answered nothing" — so without
    # this the fields simply come back blank and nobody knows a call died.
    _llm_call_failures: List[str]               = []

    # ── Partition eligible fields into singles and slot-groups ────────────────
    # Slot-groups: fields sharing the same base name with _A/_B/…/_N suffixes.
    # Singles:     everything else (no repeating siblings).
    _ROW_SUFFIX_RE = re.compile(r"^(.+)_([A-N])$")

    def _group_key(field: str):
        """Repeating-group identity for ``field`` - delegates to the module-level
        :func:`repeating_group_key` (pure + unit-tested) using this field's
        schema tooltip. See that function for why grouping is (base, tooltip)."""
        info = eligible_fields.get(field) or {}
        tu = info.get("tu") if isinstance(info, dict) else None
        return repeating_group_key(field, tu)

    _base_to_slots: Dict[tuple, List[str]] = {}
    for _f in field_list:
        _gk = _group_key(_f)
        if _gk:
            _base_to_slots.setdefault(_gk, []).append(_f)
    for _gk in _base_to_slots:
        _base_to_slots[_gk].sort()            # _A, _B, _C, … always in order
    _grouped_fields_set = {f for slots in _base_to_slots.values() for f in slots}

    # ── Table-group detection ───────────────────────────────────────────────
    # Multiple DIFFERENT repeating-group columns that share the identical
    # row-letter set AND a common 2-token prefix are columns of ONE real
    # multi-column schedule (e.g. ACORD 140's Premises Information table:
    # SubjectOfInsuranceCode/LimitAmount/CoinsurancePercent/.../
    # FormsAndConditions all repeat over the SAME 10 rows). Filling each
    # column as an INDEPENDENT "find N distinct values" search (the prior
    # behavior) has no way to know that column X's 2nd distinct value and
    # column Y's 2nd distinct value must describe the SAME real-world row - a
    # live multi-location property test surfaced exactly this failure: a
    # genuine 2nd distinct LimitAmount bled into the unrelated
    # DeductibleAmount column instead of staying null, and an unrelated
    # document sentence landed in a free-text "FormsAndConditions" column,
    # because each column searched the WHOLE document blind to what its
    # sibling columns had already claimed for that row.
    #
    # Fix: bucket these columns' group_keys together so (a) the batcher below
    # never splits them across separate LLM calls (columns in different calls
    # can't possibly stay row-aligned), and (b) the prompt renders ONE
    # row-oriented TABLE block (_table_group_block) instead of N independent
    # column blocks - explicitly telling the model a ROW is one real entry
    # and its columns move together, including "leave this cell null" being
    # the normal, expected outcome for most columns of most rows.
    #
    # Only real multi-column tables (>=3 co-occurring columns) are treated as
    # atomic - a coincidental PAIR sharing a prefix is far more likely to be
    # two unrelated small groups (there are many on a typical ACORD schema)
    # than a genuine table, so pairs fall through to the existing
    # independent-column behavior, completely unchanged.
    #
    # Bucketed by PREFIX ONLY - NOT also by row-letter set. A live production
    # run surfaced why that matters: different columns of the SAME real table
    # very often have DIFFERENT row-letter sets active at gap-fill time,
    # because different Pass 1 mechanisms resolve different columns (e.g.
    # SubjectOfInsuranceCode/LimitAmount via the property_locations-aware
    # resolver, CoinsurancePercent/ValuationCode via a plain scalar-fact
    # rule that only ever fills row A). Requiring an EXACT row-letter match
    # to bucket columns together fragmented one real table into 3-4 separate
    # buckets too small to trigger table treatment at all - so the columns
    # that actually caused the duplication (SubjectOfInsuranceCode,
    # LimitAmount, ...) never got the row-oriented framing in the first
    # place. Each column's OWN active row-letter set is still tracked
    # separately (see active_col_fields in _build_user_prompt) - grouping by
    # prefix only widens WHICH columns are considered part of the same table,
    # it does not pretend every column shares identical rows.
    def _table_prefix(base: str) -> str:
        return "_".join(base.split("_")[:2])

    _table_buckets: Dict[str, List[tuple]] = {}
    for _gk, _slots in _base_to_slots.items():
        _row_letters = tuple(sorted(
            m.group(2) for m in (_ROW_SUFFIX_RE.match(s) for s in _slots) if m
        ))
        if len(_row_letters) < 2:
            continue
        _table_buckets.setdefault(_table_prefix(_gk[0]), []).append(_gk)

    _table_group_keys: set = set()                   # group_keys that are table columns
    _table_group_membership: Dict[tuple, str] = {}    # group_key -> table prefix
    for _prefix, _gks in _table_buckets.items():
        if len(_gks) >= 3:
            for _gk in _gks:
                _table_group_keys.add(_gk)
                _table_group_membership[_gk] = _prefix

    if _table_buckets:
        for _prefix, _gks in _table_buckets.items():
            _is_table = len(_gks) >= 3
            _cols = {g[0] for g in _gks}
            _already_hits = sum(
                1 for _k in already_filled
                if (_m := _ROW_SUFFIX_RE.match(_k)) and _m.group(1) in _cols
            )
            _row_union = sorted({
                _ROW_SUFFIX_RE.match(f).group(2)
                for g in _gks for f in _base_to_slots.get(g, [])
                if _ROW_SUFFIX_RE.match(f)
            })
            logger.info(
                "gpt_fill TABLE_DETECT: form=%s prefix=%s columns=%s row_union=%s treated_as_table=%s "
                "already_filled_hits=%d",
                form_id, _prefix, sorted(_cols), ",".join(_row_union), _is_table, _already_hits,
            )

    _ORDINALS = ["1st", "2nd", "3rd", "4th", "5th", "6th", "7th",
                 "8th", "9th", "10th", "11th", "12th", "13th", "14th"]

    def _field_spec(f: str) -> str:
        """Spec line for a single (non-grouped) field."""
        info = eligible_fields.get(f) or {}
        info = info if isinstance(info, dict) else {}
        full_tu = info.get("tu", "") or ""
        tu   = full_tu[:_PROMPT_TOOLTIP_MAX]   # was [:80] — cut off question text
        ft   = info.get("ft", "")
        req  = " [REQUIRED]" if info.get("required") else ""
        spec = f"  - {f}{req}"
        if tu:
            spec += f": {tu}"
        if "/Ch" in ft:
            spec += " (dropdown)"
        elif "/Btn" in ft:
            spec += " (checkbox — Yes/No)"
            if _is_high_impact_checkbox_field(f, full_tu, ft):
                spec += " [HIGH-IMPACT — see rule 8]"
        clarification = _FIELD_SPEC_CLARIFICATIONS.get(f)
        if clarification:
            spec += clarification
        return spec

    def _slot_group_block(group_key, active_slots: List[str]) -> str:
        """Visual block for repeating-row siblings (_A/_B/_C …).

        Rendering all siblings in one block forces the LLM to reason about
        the full slot set before assigning values, preventing duplication
        caused by identical per-field descriptions.

        ``group_key`` is (base, tooltip) - all slots in it share the same
        meaning by construction (see _group_key), so a single shared
        description is accurate.
        """
        base        = group_key[0] if isinstance(group_key, tuple) else group_key
        all_slots   = _base_to_slots.get(group_key, active_slots)
        n_total     = len(all_slots)
        info_a      = eligible_fields.get(active_slots[0]) or {}
        info_a      = info_a if isinstance(info_a, dict) else {}
        full_tu     = info_a.get("tu", "") or ""
        tu          = full_tu[:_PROMPT_TOOLTIP_MAX]   # was [:80] — cut off question text
        ft          = info_a.get("ft", "")
        # Real row letters of THIS group (e.g. "_C/_D" for the split owner group),
        # not a positional _A/_B/... which would mislabel a split-off group.
        slot_labels = "/".join(
            "_" + (_ROW_SUFFIX_RE.match(s).group(2) if _ROW_SUFFIX_RE.match(s) else "?")
            for s in all_slots
        )

        lines = [f"\n  ── REPEATING GROUP '{base}' ({n_total} slots: {slot_labels}) ──"]
        if tu:
            lines.append(f"  Description (same for all slots): {tu}")
        if "/Ch" in ft:
            lines.append("  Type: dropdown")
        elif "/Btn" in ft:
            lines.append(
                "  Type: checkbox — return Yes/No for each slot; see rule 8: cite a "
                "grounding quote in \"question_grounding\" keyed by that slot's exact "
                "field name for each slot you answer Yes/No"
            )
            if _is_high_impact_checkbox_field(active_slots[0], full_tu, ft):
                lines.append("  [HIGH-IMPACT — see rule 8]")
        lines.append(
            f"  RULE: Find up to {n_total} separate real values in the document, in the order\n"
            f"  they appear. Put the 1st one you find in slot _A, the 2nd in slot _B, and so on.\n"
            f"  NEVER copy the same value into more than one slot.\n"
            f"  If fewer than {n_total} values exist, leave the remaining slots OUT of your\n"
            f"  response entirely — never invent a value to fill a slot.\n"
            f"  CRITICAL: a slot's value must be an ACTUAL value copied from the document\n"
            f"  (e.g. a name, an amount, a date) - NEVER the words describing which slot it is\n"
            f"  (never write things like 'first value', '2nd distinct value', or any text\n"
            f"  about counting/ordering - that is an instruction to you, not a value)."
        )
        for i, slot_field in enumerate(active_slots):
            ordinal = _ORDINALS[i] if i < len(_ORDINALS) else f"{i + 1}th"
            req     = " [REQUIRED]" if (eligible_fields.get(slot_field) or {}).get("required") else ""
            lines.append(f"  - {slot_field}{req} → slot {i + 1} of {n_total} (omit if fewer values exist)")
        lines.append("  ──────────────────────────────────────────")
        return "\n".join(lines)

    def _table_group_block(table_prefix: str, active_col_fields: Dict[str, List[str]]) -> str:
        """Visual block for a genuine multi-column repeating TABLE - several
        DIFFERENT columns that share a common prefix (see the table-group
        detection above). Rendered as ONE combined row-oriented block instead
        of N independent per-column "find N distinct values" blocks, so the
        model reasons about a ROW as one real entry and keeps its columns
        aligned - each column's cell for that row is either grounded in data
        specific to that entry, or null.

        ``active_col_fields`` maps each column's base name to the list of its
        OWN field names actually being asked about in THIS call. Columns are
        deliberately NOT assumed to share an identical row-letter set - a live
        run showed they usually don't (different Pass 1 mechanisms resolve
        different columns for different rows), so each column's real,
        possibly-different row list is used as-is rather than forcing a single
        shared row range that would silently ask for cells that don't exist.
        """
        col_bases = sorted(active_col_fields.keys())
        row_union = sorted({
            _ROW_SUFFIX_RE.match(f).group(2)
            for _fields in active_col_fields.values() for f in _fields
            if _ROW_SUFFIX_RE.match(f)
        })
        n_total = len(row_union)
        slot_labels = "/".join(f"_{r}" for r in row_union)

        # Sibling rows of THIS table already resolved by Pass 1/1.5 (so they
        # never reached this function's field list at all) - without surfacing
        # them, the model has no way to know an earlier real-world entry was
        # already captured elsewhere, and re-discovers it as if it were the
        # first entry, duplicating it into whatever row IS in front of it.
        _col_base_set = set(col_bases)
        _already_rows: Dict[str, Dict[str, str]] = {}
        for _key, _val in already_filled.items():
            if _is_empty_llm_value(_val):
                continue
            _m = _ROW_SUFFIX_RE.match(_key)
            if not _m or _m.group(1) not in _col_base_set:
                continue
            _col_name = _m.group(1).rsplit("_", 1)[-1] if "_" in _m.group(1) else _m.group(1)
            _already_rows.setdefault(_m.group(2), {})[_col_name] = _val

        lines = [
            f"\n  ── TABLE '{table_prefix}' ({n_total} rows: {slot_labels}, "
            f"{len(col_bases)} columns) ──",
            "  Each row is ONE DISTINCT real-world entry (e.g. one coverage item for one\n"
            "  location). ALL columns in the SAME row must describe THAT SAME entry.",
        ]
        if _already_rows:
            lines.append(
                "  Some rows of this SAME table are ALREADY CAPTURED elsewhere and are NOT\n"
                "  part of this request (shown below ONLY so you recognize their entry and\n"
                "  skip past it - do NOT include these rows in your response, do NOT re-find\n"
                "  the same real-world entry, and do NOT restart counting from 1):"
            )
            for _row in sorted(_already_rows.keys()):
                _summary = ", ".join(f"{k}={v}" for k, v in _already_rows[_row].items())
                lines.append(f"    _{_row} (already filled): {_summary}")
        lines.append("  Columns:")
        for base in col_bases:
            sample_field = active_col_fields[base][0]
            info = eligible_fields.get(sample_field) or {}
            tooltip = info.get("tu", "") if isinstance(info, dict) else ""
            col_name = base.rsplit("_", 1)[-1] if "_" in base else base
            short_tu = (tooltip or "")[:_PROMPT_TOOLTIP_MAX]
            line = f"    - {col_name}"
            if short_tu:
                line += f": {short_tu}"
            lines.append(line)
        _first_row = row_union[0] if row_union else "?"
        _second_row = row_union[1] if n_total > 1 else _first_row
        lines.append(
            "  RULE: Find each distinct real entry in the document that is NOT already\n"
            "  captured above, in the order they appear. Fill ONE COMPLETE ROW per entry:\n"
            f"  the 1st such entry → row _{_first_row}, the 2nd → row _{_second_row}, and so on.\n"
            "    a) A cell must ONLY use information that specifically describes THAT\n"
            "       row's entry — never reuse or borrow a value that belongs to a\n"
            "       different entry, a different row, or an unrelated part of the document.\n"
            "    b) If a column's data is not stated for an entry you ARE filling (e.g. no\n"
            "       deductible was given for that item), OMIT THAT CELL's field entirely — do\n"
            "       not guess, and do not reuse a nearby number or sentence from elsewhere.\n"
            "    c) If there are fewer distinct entries than rows, OMIT the REMAINING\n"
            "       ROWS entirely (every column of them) — never invent an entry.\n"
            "    d) NEVER split one entry's data across two rows, and NEVER duplicate one\n"
            "       entry's data into two rows.\n"
            "    e) A column with no field name listed below for a given row is not part\n"
            "       of this request for that row (it was already resolved separately) -\n"
            "       fill ONLY the exact field names listed for each row, nothing else."
        )
        lines.append("  Exact field names per row:")
        for r in row_union:
            row_fields = [f"{base}_{r}" for base in col_bases if f"{base}_{r}" in active_col_fields[base]]
            if row_fields:
                lines.append(f"    _{r}: {', '.join(row_fields)}")
        lines.append("  ──────────────────────────────────────────")
        return "\n".join(lines)

    # ── Prompt builder ───────────────────────────────────────────────────────
    # _PROMPT_SKELETON / _SKELETON_CHARS are now MODULE-LEVEL constants (see the
    # definition above _compliance_question_text). They used to be rebuilt here per
    # call with the form id interpolated, which broke prefix caching and fed the
    # model a batch label instead of a real ACORD form name. The form identity now
    # travels in the user message as `form_label`.

    # ── Build a clean, PII-stripped JSON facts block once per call ───────────
    # Strips PII keys, unwraps {value, confidence} envelopes, drops null/empty
    # values. Booleans (flags merged via process_single_form) are preserved so
    # GPT can correctly answer Yes/No checkbox fields that fell through Pass 1.
    def _build_facts_block(_facts: dict) -> str:
        clean: dict = {}
        for _k, _v in (_facts or {}).items():
            if _k in _PII_EXCLUDE_KEYS or _k in _GAP_FILL_FACTS_EXCLUDE:
                continue
            # Unwrap annotated envelope from extraction_service._annotate_facts
            if isinstance(_v, dict) and "value" in _v:
                _v = _v.get("value")
            if _v is None:
                continue
            if _k in _SCHEDULE_ROW_PII_SUBKEYS:
                _v = _redact_schedule_rows(_k, _v)
            if isinstance(_v, str):
                if not _v.strip():
                    continue
                _v = _v.strip()
            elif isinstance(_v, list) and len(_v) == 0:
                continue
            elif isinstance(_v, dict) and len(_v) == 0:
                continue
            clean[_k] = _v
        try:
            return json.dumps(clean, indent=2, ensure_ascii=False, default=str)
        except Exception:
            return "{}"

    _facts_block_text = _build_facts_block(facts)
    _facts_block_present = bool(_facts_block_text) and _facts_block_text != "{}"
    # Single source of truth for the facts-section wrapper: the budget measure
    # below and _build_user_prompt's rendering both use these SAME constants,
    # so the two can never drift (the C3 failure mode — re-estimating what
    # another function renders).
    #
    # Label honesty (2026-08-10): this header previously called the facts block
    # the PRIMARY SOURCE and claimed it was verified by a document analyzer. No
    # such verification exists anywhere in the pipeline — extraction output is
    # never checked against the document — so the prompt asserted a guarantee
    # the system does not provide. Guarded by
    # test_gap_fill_prompt_never_claims_facts_are_verified.
    _FACTS_HEADER = (
        "\n\n=== EXTRACTED FACTS (unverified hints from a previous pass — "
        "the RAW DOCUMENT TEXT below is authoritative) ===\n"
    )
    _FACTS_FOOTER = "\n=== END EXTRACTED FACTS ===\n"
    _FACTS_BLOCK_CHARS = (
        len(_facts_block_text) + len(_FACTS_HEADER) + len(_FACTS_FOOTER)
        if _facts_block_present else 0
    )

    # Fixed overhead per call: skeleton + form-label line + fields header + the
    # "CRITICAL - JSON KEYS" block + JSON-return footer + facts block.
    # 1200 is a deliberate over-estimate of those wrapper strings (~750 actual,
    # plus the form label twice) so the raw-text budget can never be computed too
    # large. **Raise this whenever text is added around the field list** — it was
    # 400, and adding the JSON-keys block silently pushed prompts past the call
    # budget until `tests/test_full_document_coverage.py` caught it. That is the
    # same defect class as C12: the budget must know about every byte the prompt
    # builder emits.
    _FIXED_OVERHEAD = _SKELETON_CHARS + 1200 + _FACTS_BLOCK_CHARS

    # Cache-routing key for this submission. Every call made by this invocation
    # shares the same (facts + document) prefix, so they must share one key —
    # that is what tells OpenAI's router to send them to the same cache. It is
    # derived from the CONTENT, so two different submissions never collide and a
    # re-run of the same submission reuses a still-warm cache.
    import hashlib as _hashlib
    _prefix_cache_key = _hashlib.md5(
        (_facts_block_text + "\x00" + raw_text).encode("utf-8", "ignore"),
        usedforsecurity=False,
    ).hexdigest()[:24]

    # Roughly how much constant text every call in this invocation will repeat.
    # Warming only pays for itself once this is substantial — see _PREFIX_WARMUP.
    _est_prefix_chars = _FIXED_OVERHEAD + len(raw_text)
    _warmup_worthwhile = _PREFIX_WARMUP and _est_prefix_chars >= _PREFIX_WARMUP_MIN_CHARS

    def _should_warm(stage: str) -> bool:
        """Warm only if the prefix is big enough to be worth a serialized wave AND
        nobody in this process has already warmed it (C27)."""
        if not _warmup_worthwhile:
            return False
        return _claim_warmup(stage, _prefix_cache_key)
    logger.info(
        "gpt_fill: form=%s prefix~%d chars warmup_worthwhile=%s (threshold %d)",
        form_id, _est_prefix_chars, _warmup_worthwhile, _PREFIX_WARMUP_MIN_CHARS,
    )

    def _build_user_prompt(active_fields: List[str], raw_chunk: str, chunk_idx: int,
                           total_chunks: int, index_text: str = "") -> str:
        """Build the user message: form identity + facts + document text + fields.

        ORDER IS LOAD-BEARING — do not rearrange without reading this.

        OpenAI's automatic prefix cache matches from the very FIRST token of the
        request and bills a hit at ~10%. Everything that is constant for a run
        must therefore come BEFORE anything that varies per call:

            [system: _PROMPT_SKELETON]   constant  (module-level, form-agnostic)
            form label                   constant within a run
            EXTRACTED FACTS              constant within a run
            RAW DOCUMENT TEXT            constant within a run (see _raw_budget)
            ---------------------------- cache boundary ----------------------
            Fields to fill               VARIES per sub-batch
            JSON return instruction

        This function previously emitted the field list FIRST, so the prefix
        diverged within a few hundred tokens of every call and nothing ever
        cached — the single largest line item in this pipeline's bill
        (improving-ll.md C1). A real 2-form run re-shipped ~23.8k identical
        chars on each of ~17 calls.

        Facts stay AHEAD of the raw text, exactly as before. That relative order
        is deliberate: the skeleton labels facts the PRIMARY source and raw text
        the SECONDARY one, and models weight position as well as labels. Putting
        the raw text first would have been equally cacheable but would have
        physically demoted the primary source — an avoidable quality risk, so it
        was not done. Only the field list moved.

        Grouped repeating-slot fields are rendered as visual GROUP blocks so
        the LLM can reason about all siblings at once before assigning values.

        `index_text` (Stage A) REPLACES the raw document section with the
        declarations index. It never accompanies it: the whole point of Stage A
        is a call that carries 3% of the package instead of all of it, and
        appending the index to the raw text would cost more than the old
        behaviour rather than less. It occupies the same position in the prompt
        so both stages share the [system + form label + facts] cached prefix.
        """
        fields_block = _render_fields_block(active_fields)
        # The facts block KEEPS its position (ahead of the raw text, constant
        # within a run) so the cacheable-prefix structure is untouched; the
        # header/footer text comes from the shared _FACTS_HEADER/_FACTS_FOOTER
        # constants the budget measure also uses — see their definition above.
        facts_section = (
            _FACTS_HEADER + _facts_block_text + _FACTS_FOOTER
        ) if _facts_block_present else ""
        if index_text:
            raw_section = index_text
        elif raw_chunk:
            raw_section = (
                f"\n\n=== RAW DOCUMENT TEXT (AUTHORITATIVE SOURCE — chunk "
                f"{chunk_idx + 1}/{total_chunks}) ===\n{raw_chunk}"
            )
        else:
            raw_section = ""
        return (
            f"ACORD form(s) being filled: {form_label}"
            + facts_section
            + raw_section
            + f"\n\nFields to fill ({form_label}):\n{fields_block}"
            # Last thing the model reads, and it earns its place. On a very long
            # document (a 682k-char package is ~170k tokens) the model starts
            # IGNORING the field list and answering under invented keys of its
            # own devising - observed live 2026-07-29: a call that sent 39 fields
            # got back 60 answers named "Producer_Name", "Applicant_Name",
            # "GL_Limit_EachOccurrence"... none of which exist in any ACORD
            # schema. The data was right; the keys were made up, so 57 of 60
            # answers were discarded and the batch filled 3 fields. Restating the
            # constraint at the very end is the cheapest lever against that, and
            # it sits after the field list so the cached prefix is unaffected.
            + "\n\nCRITICAL - JSON KEYS: every key in \"values\" MUST be copied "
              "CHARACTER-FOR-CHARACTER from the field list above, including its "
              "_A/_B/_C row suffix. Do NOT invent, shorten, prettify or translate "
              "a field name. Any key that is not in that list is DISCARDED and "
              "its answer is lost. If you found a value but cannot match it to a "
              "listed field name, omit it rather than filing it under a new name."
            + '\n\nReturn ONLY valid JSON: {"values": {...}, "raw_text_sourced": [...], "question_grounding": {...}}'
        )

    def _render_fields_block(active_fields: List[str]) -> str:
        """Render the fields section exactly as it will be sent.

        SINGLE SOURCE OF TRUTH, and it must stay that way. `_raw_budget` sizes
        the document chunk by subtracting this block's length from the call
        budget, so if the two ever disagree the budget is wrong. They DID
        disagree: `_raw_budget` used to estimate with `_field_spec()` (one short
        line per field) while this rendering routes multi-slot and table fields
        through `_slot_group_block()` / `_table_group_block()`, which are several
        times longer. On a group-heavy batch the estimate under-counted, too much
        raw text was packed in, and the assembled prompt ran ~16% past the call
        budget - measured at 69,879 chars against a 60,000 budget on ACORD 140.
        In production that lands as a context-length 400 → three dead retries →
        `_chat_json` returns {} → the whole batch silently BLANK, which is
        indistinguishable from the model having nothing to say.
        See tests/test_full_document_coverage.py.
        """
        # Separate active_fields into singles and per-base slot groups.
        # Bug fix: ACORD's row-letter suffix convention means nearly every field
        # ends in _A..._N even when it has no siblings (e.g. Contractors_
        # SubcontractorsPaidAmount_A has no _B). Routing a true 1-slot field
        # through _slot_group_block() renders it as a fake "REPEATING GROUP"
        # ("find up to 1 distinct value...") instead of the plain field-spec
        # line, which both bloats the prompt for no reason and skips any
        # per-field clarification hook _field_spec() carries. Only real
        # multi-row groups (>1 slot) need group-block treatment.
        active_groups: Dict[tuple, List[str]] = {}
        active_singles: List[str] = []
        # bucket (table prefix) -> column base -> its own active field names.
        active_table_buckets: Dict[str, Dict[str, List[str]]] = {}
        for f in active_fields:
            _gk = _group_key(f)
            if _gk in _table_group_keys:
                _bucket = _table_group_membership[_gk]
                active_table_buckets.setdefault(_bucket, {}).setdefault(_gk[0], []).append(f)
            elif _gk and len(_base_to_slots.get(_gk, [])) > 1:
                active_groups.setdefault(_gk, []).append(f)
            else:
                active_singles.append(f)
        for _gk in active_groups:
            active_groups[_gk].sort()
        for _bucket in active_table_buckets:
            for _base in active_table_buckets[_bucket]:
                active_table_buckets[_bucket][_base].sort()

        parts: List[str] = [_field_spec(f) for f in active_singles]
        for _gk, _slots in sorted(active_groups.items()):
            parts.append(_slot_group_block(_gk, _slots))
        for _bucket, _col_fields in sorted(active_table_buckets.items()):
            parts.append(_table_group_block(_bucket, _col_fields))
        return "\n".join(parts)

    # Kept under the old name for any external callers; new code should use
    # _build_user_prompt + _PROMPT_SKELETON as a system message.
    def _build_prompt(active_fields: List[str], raw_chunk: str, chunk_idx: int,
                      total_chunks: int, index_text: str = "") -> str:
        return _PROMPT_SKELETON + _build_user_prompt(
            active_fields, raw_chunk, chunk_idx, total_chunks, index_text)

    # ── LLM caller with retry (reusable for any system+user+schema) ───────────
    def _chat_json(system_msg: str, user_msg: str, response_format: dict,
                   stage: str = "gap_fill") -> dict:
        # Runs on ThreadPoolExecutor worker threads. This is DELIBERATELY fully
        # synchronous: the previous implementation wrapped an async call in
        # asyncio.run(), creating a fresh event loop per call while sharing one
        # module-level AsyncOpenAI client. That let a worker await a pooled
        # connection owned by another thread's already-closed loop, which hung
        # forever with the timeout timer stranded on the dead loop — see
        # _get_openai_form_fill_client_sync() for the full analysis.
        from utils.llm_limiter import llm_slot_sync

        def _create(rf: dict) -> str:
            global _PROMPT_CACHE_KEY_SUPPORTED
            kwargs = dict(
                model=llm_model,
                messages=[
                    {"role": "system", "content": system_msg},
                    {"role": "user",   "content": user_msg},
                ],
                temperature=GPT_TEMPERATURE,
                response_format=rf,
                max_completion_tokens=_FORM_FILL_MAX_TOKENS,
            )
            if _PROMPT_CACHE_KEY_SUPPORTED:
                kwargs["prompt_cache_key"] = f"{stage}:{_prefix_cache_key}"
            with llm_slot_sync():
                try:
                    resp = _sync_client.chat.completions.create(**kwargs)
                except Exception as _ex:
                    # Never let an unsupported cache-routing hint fail a real fill.
                    # Gate on THIS call's kwargs, not the module flag: sub-batches
                    # run concurrently, so a sibling thread can flip the flag to
                    # False between our kwargs being built and this handler
                    # running. Reading the flag here would then send us down the
                    # `raise` branch and burn a full retry-with-backoff on a call
                    # we could have fixed in place.
                    if "prompt_cache_key" in kwargs and "prompt_cache_key" in str(_ex).lower():
                        _PROMPT_CACHE_KEY_SUPPORTED = False
                        logger.warning(
                            "gpt_fill: API rejected prompt_cache_key (%s) — disabling it for "
                            "this process and retrying without it", _ex,
                        )
                        kwargs.pop("prompt_cache_key", None)
                        resp = _sync_client.chat.completions.create(**kwargs)
                    else:
                        raise
            _log_llm_spend(stage, form_id, resp)
            return resp.choices[0].message.content or ""

        def _inner() -> str:
            try:
                return _create(response_format)
            except Exception as _schema_err:
                # Fall back to json_object ONLY for a genuine response_format
                # rejection. Falling back on ANY exception (the old behaviour)
                # meant a timeout or 429 — where OpenAI had already processed and
                # BILLED the first request — immediately fired a second identical
                # full-prompt call, and a context-length 400 re-billed a call that
                # could not succeed either way. See improving-ll.md C7.
                if not _is_response_format_rejection(_schema_err):
                    raise
                logger.warning(
                    "gpt_fill: json_schema response_format rejected (%s) — "
                    "falling back to json_object for this call", _schema_err,
                )
                return _create({"type": "json_object"})

        import time as _time
        # Transport failures and PARSE failures are handled separately
        # (improving-ll.md C6). Re-sending the whole prompt because the reply
        # would not parse re-bills every input token only to get the same
        # truncation back at temperature 0, so a parse failure now tries
        # `_salvage_truncated_json` FIRST and returns the completed answers at
        # zero extra cost — which is the outcome in essentially every real case,
        # since truncation at the output cap is what produces these.
        # A reply that is not merely truncated but genuinely malformed is a
        # different animal (transient model garbage), so those still retry, but
        # WITHOUT the long 429-oriented backoff — that backoff exists to let a
        # TPM bucket refill and buys nothing here.
        for attempt in range(_FORM_FILL_BATCH_RETRIES):
            try:
                content = _inner()
            except Exception as ex:
                if _is_context_length_error(ex):
                    # Not retryable at this size, and retrying identically would
                    # burn all three attempts and ship the batch BLANK. Shrink
                    # the budget so the caller can re-split against a size the
                    # model will actually accept, and flag THIS thread so only
                    # the batch that actually overflowed re-splits (C28).
                    _shrink_budget_after_overflow(ex)
                    _note_context_overflow()
                    _llm_call_failures.append(f"context_overflow: {str(ex)[:150]}")
                    return {}
                if attempt < _FORM_FILL_BATCH_RETRIES - 1:
                    # Backoff is deliberately longer than plain 1/2/4s: the common
                    # failure here is an OpenAI TPM (tokens-per-minute) 429, and a
                    # TPM bucket needs tens of seconds to refill — a 4s retry just
                    # burns an attempt and lands on the same 429. The SDK's own
                    # Retry-After handling covers the polite case; this covers the
                    # case where we exhausted the minute budget ourselves.
                    wait = min(_LLM_RETRY_BACKOFF_BASE_S * (2 ** attempt), _LLM_RETRY_BACKOFF_MAX_S)
                    logger.warning("gpt_fill: call failed attempt=%d/%d retrying in %ds — %s",
                                   attempt + 1, _FORM_FILL_BATCH_RETRIES, wait, ex)
                    _time.sleep(wait)
                    continue
                _llm_call_failures.append(str(ex)[:200])
                logger.error(
                    "gpt_fill: call PERMANENTLY FAILED after %d attempts — the fields in "
                    "this batch will be BLANK and that is a FAILURE, not a model omission. "
                    "form=%s err=%s",
                    _FORM_FILL_BATCH_RETRIES, form_id, ex,
                )
                return {}

            try:
                return json.loads(content)
            except Exception as parse_err:
                salvaged = _salvage_truncated_json(content)
                if salvaged is not None:
                    logger.warning(
                        "gpt_fill: reply was not valid JSON (almost always truncation at the "
                        "%d-token output cap) — salvaged %d completed key(s) instead of "
                        "re-billing the whole prompt. form=%s stage=%s",
                        _FORM_FILL_MAX_TOKENS, len(salvaged), form_id, stage,
                    )
                    return salvaged
                if attempt < _FORM_FILL_BATCH_RETRIES - 1:
                    logger.warning(
                        "gpt_fill: reply unparseable and unsalvageable (%d chars) — one retry. "
                        "form=%s err=%s", len(content or ""), form_id, parse_err,
                    )
                    continue
                # A permanently-failed call returns {} — indistinguishable
                # downstream from "the model legitimately answered nothing".
                # That silence is how a rate-limited run turns into a form
                # full of unexplained BLANK Yes/No answers. Count it and log
                # at ERROR so the failure is visible instead of looking like
                # a correct omission.
                _llm_call_failures.append(str(parse_err)[:200])
                logger.error(
                    "gpt_fill: call PERMANENTLY FAILED after %d attempts (unparseable reply) "
                    "— the fields in this batch will be BLANK and that is a FAILURE, not a "
                    "model omission. form=%s err=%s",
                    _FORM_FILL_BATCH_RETRIES, form_id, parse_err,
                )
                return {}
        return {}

    # JSON-schema response format for the general field-fill call: typing `values`
    # as a map of string→string (no null permitted) forces the model to OMIT
    # absent fields rather than emit explicit nulls — cuts output tokens ~10× on
    # null-heavy batches. Falls back to json_object inside _chat_json if rejected.
    _FORM_FILL_RESPONSE_FORMAT = {
        "type": "json_schema",
        "json_schema": {
            "name": "form_fill_response",
            "schema": {
                "type": "object",
                "properties": {
                    "values":             {"type": "object", "additionalProperties": {"type": "string"}},
                    "raw_text_sourced":   {"type": "array",  "items": {"type": "string"}},
                    "question_grounding": {"type": "object", "additionalProperties": {"type": "string"}},
                },
                "required": ["values"],
                "additionalProperties": False,
            },
        },
    }

    def _call_llm_sync(prompt: str) -> dict:
        # Split the historical single-prompt format back into (system, user) so
        # OpenAI's automatic prefix caching can reuse the skeleton.
        user_msg = prompt[_SKELETON_CHARS:] if prompt.startswith(_PROMPT_SKELETON) else prompt
        return _chat_json(_PROMPT_SKELETON, user_msg, _FORM_FILL_RESPONSE_FORMAT)

    # ── Result absorber ───────────────────────────────────────────────────────
    # Writes into caller-provided accumulators (counts/raw_fields/grounding_out)
    # rather than closure state, so each field sub-batch can absorb into its own
    # LOCAL dicts on a worker thread with zero shared mutation, and results merge
    # cleanly afterward (field sub-batches are disjoint by construction).
    def _absorb(result: dict, sent: List[str], counts: Dict[str, Dict[str, int]],
                raw_fields: set, grounding_out: Dict[str, str],
                chunk_label: str = "1/1",
                grounding_by_value: Optional[Dict[str, Dict[str, str]]] = None) -> None:
        values      = result.get("values",          {}) or {}
        raw_sourced = set(result.get("raw_text_sourced", []) or [])
        grounding   = result.get("question_grounding", {}) or {}

        # DIAGNOSTIC. At INFO this logged up to 2000 chars of real applicant VALUES
        # — names, addresses, FEINs, driver licence numbers — on every call, which
        # contradicts this codebase's own handling of the same data (field-level
        # encryption in utils/crypto.py) and CLAUDE.md's classification of it as
        # sensitive (improving-ll.md C16). The field NAMES and the response SIZE are
        # what makes this diagnostic useful for debugging a bad fill; the values are
        # not. So INFO now carries names and lengths only, and the values are
        # available at DEBUG for someone who has deliberately turned it on.
        logger.info(
            "gpt_fill DIAG_RESPONSE: form=%s chunk=%s total_returned=%d keys=%s",
            form_id, chunk_label, len(values),
            ",".join(list(values)[:30])[:1500],
        )
        if logger.isEnabledFor(logging.DEBUG):
            _diag_sample = {k: v for i, (k, v) in enumerate(values.items()) if i < 30}
            logger.debug(
                "gpt_fill DIAG_RESPONSE_VALUES: form=%s chunk=%s sample=%s",
                form_id, chunk_label, json.dumps(_diag_sample, default=str)[:2000],
            )

        filled_count    = 0
        rejected_count  = 0
        recovered_count = 0
        rejected_sample: List[str] = []
        non_null_rejected: List[str] = []
        unknown_keys: List[str] = []
        _sent_by_norm: Dict[str, List[str]] = {}
        for _s in sent:
            _sent_by_norm.setdefault(_norm_field_key(_s), []).append(_s)
        for field, value in values.items():
            if field not in sent:
                # The model answered under a key we never asked for. First try
                # to recover it: on long documents the model drops row suffixes
                # or reformats names while the VALUE is right (measured live:
                # 57 of 60 answers discarded this way). Only an UNAMBIGUOUS
                # match is accepted — see _recover_sent_field.
                _recovered = _recover_sent_field(field, _sent_by_norm)
                if _recovered is not None and _recovered not in values:
                    logger.info(
                        "gpt_fill KEY_RECOVERED: form=%s chunk=%s %r -> %s",
                        form_id, chunk_label, str(field)[:60], _recovered,
                    )
                    field = _recovered
                    recovered_count += 1
                else:
                    # Silently skipping these hid a serious failure mode for a
                    # long time: a batch can return 60 answers, have 57 thrown
                    # away here, and report a low fill rate with no explanation
                    # anywhere. Count them and say so.
                    if len(unknown_keys) < 12:
                        unknown_keys.append(str(field))
                    rejected_count += 1
                    continue
            if _is_empty_llm_value(value):
                rejected_count += 1
                if len(rejected_sample) < 8:
                    rejected_sample.append(f"{field}={value!r}")
                # Log non-null rejections separately — these are actual values being filtered
                if value is not None and len(non_null_rejected) < 20:
                    non_null_rejected.append(f"{field}={value!r}")
                logger.debug(
                    "gpt_fill REJECT: form=%s chunk=%s field=%s value=%r",
                    form_id, chunk_label, field, value,
                )
                continue
            vstr = str(value).strip()
            counts.setdefault(field, {})
            counts[field][vstr] = counts[field].get(vstr, 0) + 1
            if field in raw_sourced:
                raw_fields.add(field)
            _quote = grounding.get(field)
            if _quote and str(_quote).strip():
                grounding_out[field] = str(_quote).strip()
                # ── ANSWER AND EVIDENCE, BOUND TOGETHER (2026-08-14) ──────────
                # `counts` decides the value by MAJORITY VOTE across chunks;
                # `grounding_out` was last-write-wins. On a 7-chunk package
                # (683k chars / 112k per call, with rescan auto-on) that means a
                # "Yes" can win the vote and inherit the quote from the chunk
                # that answered "No" - and the gate then judges, and the form
                # then PRINTS, a citation belonging to a different answer.
                # Keyed by (field, value) here so the winner can collect its
                # OWN evidence at selection time. The outward contract
                # (`question_grounding: {field: quote}`) is unchanged.
                if grounding_by_value is not None:
                    grounding_by_value.setdefault(field, {})[vstr] = str(_quote).strip()
            filled_count += 1

        logger.info(
            "gpt_fill: chunk=%s form=%s sent=%d filled=%d raw_sourced=%d rejected=%d recovered=%d",
            chunk_label,
            form_id, len(sent), filled_count, len(raw_sourced), rejected_count,
            recovered_count,
        )
        if rejected_sample:
            logger.info(
                "gpt_fill REJECT_SAMPLE: form=%s chunk=%s (%d shown of %d) %s",
                form_id, chunk_label, len(rejected_sample), rejected_count,
                "; ".join(rejected_sample),
            )
        if non_null_rejected:
            logger.info(
                "gpt_fill NON_NULL_REJECTED: form=%s chunk=%s (non-null values being filtered) %s",
                form_id, chunk_label, "; ".join(non_null_rejected),
            )
        if unknown_keys:
            _unknown_total = sum(1 for f in values if f not in sent)
            logger.warning(
                "gpt_fill UNKNOWN_KEYS: form=%s chunk=%s — the model answered %d of %d "
                "keys under names that were NOT in the field list, so those answers are "
                "DISCARDED. This is the long-context failure mode: it stops copying the "
                "ACORD field names and invents its own. If this is a large fraction of the "
                "reply, lower CONTEXT_UTILISATION so each call carries less document. "
                "Examples: %s",
                form_id, chunk_label, _unknown_total, len(values), "; ".join(unknown_keys),
            )

    # ── Chunk sizing ──────────────────────────────────────────────────────────
    # Budget per call: model context minus reply headroom minus fixed overhead
    # minus fields block chars for the fields active in this call.
    def _raw_budget(active_fields: List[str]) -> int:
        """Chars of raw document text this call may carry.

        The allowance for the fields block is a CONSTANT worst case, not the
        batch's own size. Subtracting the real per-batch size (the old
        behaviour) gave a 40-field batch and a 4-field batch different budgets,
        hence different document chunk BOUNDARIES, hence different prefix text —
        a guaranteed cache miss even after the reordering above
        (improving-ll.md C3).

        Never allowed to UNDER-reserve, though. `_pack_field_batches` emits an
        entire table-group bucket as ONE atomic batch of unbounded size, and
        group/table blocks are several times longer per field than a plain spec
        line. A flat constant under-reserves for those, packs in too much raw
        text, and pushes the prompt past _GPT_CALL_BUDGET_CHARS → context-length
        400 → 3 dead retries → the whole batch silently BLANK.

        So: measure the block with the SAME renderer that builds it
        (`_render_fields_block` - never re-estimate, that is what broke before),
        then round the allowance UP to a multiple of _MAX_FIELDS_BLOCK_CHARS.
        Rounding is what keeps caching alive: batches of similar size land in
        the same bucket, get the same budget, and therefore slice the document
        at the same offsets. An outsized batch just steps up to the next bucket
        instead of computing a bespoke budget nobody else shares.
        """
        fields_chars = len(_render_fields_block(active_fields))
        step = max(1, _MAX_FIELDS_BLOCK_CHARS)
        allowance = max(step, -(-fields_chars // step) * step)   # ceil to `step`
        avail = _effective_budget_chars - _GPT_REPLY_RESERVE_CHARS - _FIXED_OVERHEAD - allowance
        if avail < _MIN_RAW_CHUNK_CHARS:
            # The fields block alone nearly fills the call. A generous floor here
            # DEFEATS the whole guard: it hands back more raw text than the budget
            # can hold and the prompt overflows anyway — measured at 60,363 chars
            # against a 60,000 budget on an oversized ACORD 140 table batch, which
            # in production is a context-length 400 and a silently blank batch.
            # Clamp to the small floor and say loudly that the configuration, not
            # the document, is the problem.
            logger.error(
                "gpt_fill: field batch of %d fields renders to %d chars, leaving only %d "
                "chars for the document inside a %d-char call budget. Raw text is being "
                "clamped to %d chars for this batch — values that appear later in the "
                "document CANNOT be found. Raise GPT_CALL_BUDGET_CHARS / "
                "CONTEXT_UTILISATION, or lower FIELD_FILL_BATCH.",
                len(active_fields), fields_chars, avail,
                _effective_budget_chars, _MIN_RAW_CHUNK_CHARS,
            )
            return _MIN_RAW_CHUNK_CHARS
        # QUALITY CAP (CALL2_RETRIEVAL_REDESIGN D1). `avail` above is the CAPACITY
        # answer - what the window can physically hold. It is ~917,000 chars, which
        # is 12.5x what LLM call 1 will put in one request, and it is why the
        # document never split and the fill rate sat at ~26%. Take the smaller of
        # the two: the model may never be handed more document than it can read
        # carefully, however much room the window happens to have.
        #
        # This makes the document SPLIT. It does not make anything unreachable -
        # `_run_field_batch` walks the chunks until every field is answered or
        # every chunk has been seen, and `_sweep_unread_chunks` catches any chunk
        # that early-stopping skipped. See the module docstring of
        # services/chunk_router.py for why ordering is not filtering.
        return min(avail, max(_MIN_RAW_CHUNK_CHARS, _GAP_FILL_DOC_CHARS_PER_CALL))

    if not raw_text_used:
        # No raw text available — skip GPT fill entirely
        logger.warning("gpt_fill: form=%s no raw_text provided — skipping GPT fill", form_id)
        return {"filled_values": {}, "new_mappings": {}, "raw_text_fields": set(), "question_grounding": {}, "model_used": llm_model}

    # ── Split raw text into chunks sized for a given field sub-batch ───────────
    def _split_raw_text(active_fields: List[str]) -> List[str]:
        # Chunking itself lives in `_split_text_on_boundaries` (module level) so
        # this pass, the compliance pass and the umbrella probe cannot drift
        # apart. Only the BUDGET is local — that part genuinely differs per pass.
        return _split_text_on_boundaries(raw_text, _raw_budget(active_fields))

    # ── Chunk routing state (CALL2_RETRIEVAL_REDESIGN §3) ─────────────────────
    # ONE index for the whole invocation. Building it is O(document); building it
    # per field batch would be O(document x batches) — 33 pointless passes over
    # 700k chars on a realistic run.
    #
    # The index is built from the CANONICAL split (the quality cap, no batch's
    # own fields block), which is the split every ordinary batch gets, since
    # `_raw_budget` is now dominated by `_GAP_FILL_DOC_CHARS_PER_CALL`. A batch
    # whose fields block is so large that it splits differently simply falls back
    # to document order — ranking is an optimisation, never a correctness input.
    _canonical_chunks = _split_text_on_boundaries(
        raw_text, max(_MIN_RAW_CHUNK_CHARS, _GAP_FILL_DOC_CHARS_PER_CALL))
    _chunk_index = None
    _rank_chunks = None
    _router_vocab = None
    if len(_canonical_chunks) > 1:
        try:
            from services.chunk_router import (
                build_index,
                rank_chunks as _rank_chunks,
                group_vocabulary as _router_vocab,
            )
            _chunk_index = build_index(_canonical_chunks, facts, label=form_id)
        except Exception as _ri_ex:                            # noqa: BLE001
            logger.warning("gpt_fill: chunk routing unavailable (%s) — using "
                           "document order", _ri_ex)
            _chunk_index = None

    # Which canonical chunks any batch actually sent to the model. Feeds the I2
    # sweep below. Mutated from worker threads, hence the lock.
    _chunks_seen: set = set()
    _chunks_seen_lock = threading.Lock()

    def _chunk_order(chunks: List[str], batch_fields: List[str],
                     label: str) -> List[int]:
        """Indices of `chunks`, best-evidenced first.

        ALWAYS a permutation of every index — never a subset. The caller stops
        walking when its fields are answered; returning a subset here would cap
        coverage silently instead. See services/chunk_router.py.
        """
        if _chunk_index is None or len(chunks) != _chunk_index.n:
            return list(range(len(chunks)))
        try:
            return _rank_chunks(_chunk_index, batch_fields, eligible_fields, label)
        except Exception:                                      # noqa: BLE001
            return list(range(len(chunks)))

    # ── Run ONE field sub-batch through the raw-text chunk loop ────────────────
    # The field list is split into focused sub-batches (see _FIELD_FILL_BATCH):
    # a single call carrying 200+ heterogeneous fields makes the model answer
    # only ~27% of them, silently dropping questions it CAN answer from the
    # document. Each sub-batch runs its raw-text chunks SEQUENTIALLY (so
    # progressive narrowing still trims later chunks) into its OWN local
    # accumulators, so sub-batches can run on parallel worker threads with zero
    # shared mutation and merge cleanly afterward (sub-batches are disjoint).
    def _run_field_batch(batch_fields: List[str], batch_label: str):
        # Outer loop exists ONLY for the context-overflow path: if the model
        # rejects a chunk as too long, `_chat_json` halves the process budget and
        # returns {}. Re-splitting against the smaller budget recovers the batch
        # instead of leaving those fields silently blank.
        # The attempt count must cover a badly wrong guess, not just a near miss:
        # halving from 400k to a model that only accepts ~120k takes THREE steps
        # (400 -> 200 -> 100), and stopping at two left the batch blank — which is
        # exactly the failure this exists to prevent. 5 attempts spans a 32x
        # over-estimate, and `_shrink_budget_after_overflow` floors at 40k, so
        # this always terminates.
        local_counts: Dict[str, Dict[str, int]] = {}
        local_raw: set = set()
        local_grounding: Dict[str, str] = {}
        local_gbv: Dict[str, Dict[str, str]] = {}
        _consume_context_overflow()        # start clean; ignore another batch's flag
        for _attempt in range(max(1, _CONTEXT_SHRINK_ATTEMPTS)):
            budget_before = _effective_budget_chars
            local_counts = {}
            local_raw = set()
            local_grounding = {}
            local_gbv = {}
            chunks = _split_raw_text(batch_fields)
            # THE ESCALATION LADDER (CALL2_RETRIEVAL_REDESIGN §3). `_order` is a
            # PERMUTATION of every chunk index, best-evidenced first — not a
            # selection. The walk below stops when this batch has no blank fields
            # left, so a field is only ever denied a chunk once it already has an
            # answer. That is invariant I1: every field is answered, or it has
            # seen every chunk.
            _order = _chunk_order(chunks, batch_fields, batch_label)
            _routed = _chunk_index is not None and len(chunks) == _chunk_index.n
            # RESCAN SEMANTICS ARE DELIBERATELY UNCHANGED (see D10).
            #
            # An earlier cut of this work made routing imply early-stopping - walk
            # the ranked chunks, stop as soon as the batch has no blanks - because
            # that is where the cost saving lives. It also broke
            # `test_an_answering_model_still_gets_the_whole_document`, which is
            # THE standing guarantee that every word of the document reaches the
            # model even when the model answers, and which exists because
            # production was measured dropping 46% of a document exactly that way.
            #
            # Ranking still earns its place with rescan ON: the best-evidenced
            # chunk is seen FIRST, which decides first-answer-wins in the
            # compliance pass and orders the votes the general fill resolves. What
            # it must not do is silently buy speed with coverage.
            #
            # `GAP_FILL_ROUTED_EARLY_STOP=1` opts into the cheaper, lossier walk.
            _rescan = _rescan_enabled(len(chunks)) and not (
                _ROUTED_EARLY_STOP and _routed and not _GAP_FILL_FULL_RESCAN)
            _chunks_sent = 0
            _overflowed = False
            for _rank, chunk_idx in enumerate(_order):
                raw_chunk = chunks[chunk_idx]
                active_fields = [f for f in batch_fields if f not in local_counts]
                if not active_fields and not _rescan:
                    # Every field in this batch already has an answer, and this is
                    # a SINGLE-chunk document (see `_rescan_enabled`), so there is
                    # no remaining text to skip. Reached on a multi-chunk document
                    # only when GAP_FILL_FULL_RESCAN=0 explicitly forces the legacy
                    # first-answer-wins behaviour — which measurably drops document
                    # text, so it is logged loudly rather than assumed away.
                    #
                    # NO CONDITION ON THIS LOG. We break BEFORE sending
                    # chunks[chunk_idx], and `chunk_idx < len(chunks)` always holds
                    # inside the loop, so reaching here ALWAYS means at least one
                    # chunk is being skipped. An earlier `chunk_idx < len(chunks)-1`
                    # guard here suppressed exactly the two-chunk case — the most
                    # common one — and a test caught it. (Contrast the compliance
                    # pass, which breaks AFTER processing its chunk and therefore
                    # does need the -1.)
                    if _ROUTED_EARLY_STOP and _routed:
                        # OPTED IN (GAP_FILL_ROUTED_EARLY_STOP=1), so this is the
                        # requested behaviour rather than a defect: every field in
                        # this batch has an answer and the operator has chosen not
                        # to pay for re-reading the rest. Any chunk no batch read
                        # is still accounted for by the I2 sweep below.
                        logger.info(
                            "gpt_fill ROUTED_EARLY_STOP: batch=%s form=%s answered all "
                            "%d fields in %d of %d chunks (ranked order) — %d chunk(s) "
                            "not needed by this batch.",
                            batch_label, form_id, len(batch_fields), _chunks_sent,
                            len(chunks), len(_order) - _rank,
                        )
                    else:
                        logger.warning(
                            "gpt_fill COVERAGE_PARTIAL: batch=%s form=%s stopped after "
                            "%d of %d document chunks — all %d fields answered early. "
                            "Values are first-answer-wins and were NOT checked against "
                            "the remaining %d chunk(s). This only happens with "
                            "GAP_FILL_FULL_RESCAN=0; unset it to restore automatic "
                            "full-document rescanning on multi-chunk documents.",
                            batch_label, form_id, _chunks_sent, len(chunks),
                            len(batch_fields), len(_order) - _rank,
                        )
                    break
                if not active_fields:
                    # Full-rescan mode: re-ask every field against this chunk so a
                    # later endorsement can supersede an earlier value and the
                    # majority-vote resolver actually receives more than one vote.
                    active_fields = list(batch_fields)
                _chunks_sent += 1
                if _routed:
                    # Only recorded when this batch's split matches the canonical
                    # one, so `_chunks_seen` is always in canonical index space.
                    # An unrouted batch read the document under its own split and
                    # is not comparable; the sweep may then re-read a chunk, which
                    # is safe (a duplicate read) rather than wrong (a missed one).
                    with _chunks_seen_lock:
                        _chunks_seen.add(chunk_idx)
                prompt = _build_prompt(active_fields, raw_chunk, chunk_idx, len(chunks))
                logger.info(
                    "gpt_fill: batch=%s chunk %d/%d (rank %d) form=%s active_fields=%d "
                    "prompt_chars=%d rescan=%s routed=%s",
                    batch_label, chunk_idx + 1, len(chunks), _rank + 1, form_id,
                    len(active_fields), len(prompt), _rescan, _routed,
                )
                result = _call_llm_sync(prompt)
                _absorb(result, active_fields, local_counts, local_raw, local_grounding,
                        chunk_label=f"{batch_label}:{chunk_idx + 1}/{len(chunks)}",
                        grounding_by_value=local_gbv)
                if _consume_context_overflow():
                    # OUR OWN call overflowed (not a sibling thread's — see
                    # `_overflow_state`). Re-split against the reduced budget.
                    _overflowed = True
                    break
            if not _overflowed:
                # Either every chunk was sent, or the batch answered everything
                # early on a single-chunk document. Both are success — an explicit
                # flag is required here because BOTH of those exits and the
                # overflow exit use `break`, so a `for/else` cannot tell them
                # apart and would re-run a batch that had already succeeded.
                return local_counts, local_raw, local_grounding, local_gbv
            logger.warning(
                "gpt_fill: batch=%s re-splitting against the reduced budget (%d -> %d chars)",
                batch_label, budget_before, _effective_budget_chars,
            )
        return local_counts, local_raw, local_grounding, local_gbv

    def _merge(local_counts, local_raw, local_grounding, local_gbv=None):
        # Runs on the main thread only (from the as_completed / direct path), so
        # no lock is needed. Sub-batches are disjoint, so this is effectively a
        # plain fill of pre-initialised candidate_counts buckets.
        for f, cmap in local_counts.items():
            candidate_counts.setdefault(f, {})
            for v, c in cmap.items():
                candidate_counts[f][v] = candidate_counts[f].get(v, 0) + c
        all_raw_fields.update(local_raw)
        all_question_grounding.update(local_grounding)
        for f, vmap in (local_gbv or {}).items():
            grounding_by_value.setdefault(f, {}).update(vmap)

    # ── Dedicated compliance Yes/No question pass ─────────────────────────────
    # Yes/No underwriting questions are pulled OUT of the general field-fill and
    # answered together by a focused prompt (see _COMPLIANCE_SYSTEM_PROMPT). In
    # the general 200-field prompt the model defaulted these to "N" and borrowed
    # unrelated negative sentences as fake proof — the false-"N" flood reported
    # on real submissions.
    #
    # Three field shapes route here — deliberately NOT every /Btn checkbox:
    #   1. Tooltip begins with the ACORD "Enter Y for a Yes response…"
    #      convention (Question-code TEXT fields + …YesNoCode_ fields on 140/25).
    #   2. Tooltip contains "response to the question," — the CHECKBOX-PAIR
    #      form of the exact same convention ("Check the box (if applicable):
    #      Indicates a "Yes"/"No" response to the question, "<Q>""), used on
    #      ACORD 125/126/127/130/131/133/141/160/186. Found in audit: ACORD 133
    #      has ZERO shape-1 fields and 38 shape-2 fields (previous workers comp
    #      coverage, unpaid premium disputes, ...) that were reaching the
    #      general fill completely unprotected before this fix — same false-N
    #      risk as shape 1, just missed because it's a checkbox, not text.
    #   3. A genuine disclosure-style checkbox not caught by shape 2's tooltip
    #      wording (_is_high_impact_checkbox_field — hired/non-owned auto,
    #      leasing, hazardous materials, maintenance program on 137/138).
    # Generic /Btn coverage-SELECTION checkboxes ("which auto symbol applies",
    # per-row limit-type flags) are deliberately excluded: auditing a real
    # checkbox-heavy form (ACORD 137_CA) found 192 /Btn fields reach gap-fill,
    # of which only 46 are genuine disclosure questions — routing all 192 would
    # both waste ~14 extra LLM calls per form on fields with no false-N risk and
    # dilute this pass's focus away from what it exists to protect.
    def _is_compliance_question(f: str) -> bool:
        # Delegates to the module-level predicate so `combined_gap_fill` can make
        # the SAME partition one level up, before outer batching. The two must
        # never drift — see `is_compliance_question`.
        return is_compliance_question(f, eligible_fields.get(f))

    compliance_fields = [f for f in field_list if _is_compliance_question(f)]
    other_fields      = [f for f in field_list if not _is_compliance_question(f)]

    def _run_one_compliance_batch(q_fields: List[str]) -> Tuple[dict, dict]:
        """Answer one small, focused group of Yes/No questions. Returns
        (answers, quotes). Small groups keep the model's per-question diligence
        high — a single call with all ~40 questions makes it rush and borrow a
        plausible sentence for questions it should omit; ~10 per call it reads
        each carefully. Cross-group quote reuse is still caught downstream by
        the evidence gate's near-duplicate reuse cap.

        The DOCUMENT IS PLACED FIRST, before the question list. Two reasons:
        (1) it makes (system prompt + document) an identical PREFIX across every
        compliance batch for this submission, which OpenAI's automatic prefix
        caching can reuse — without it each call re-billed and re-processed the
        whole document from scratch (the dominant cost of this pipeline: a real
        8-form run issues ~70 calls, each previously shipping the full document);
        (2) "context first, task last" is the stronger ordering for grounded
        extraction.

        The document is also CHUNKED against the call budget. Previously the
        full raw_text was concatenated with no guard at all (unlike the general
        fill, which uses _split_raw_text): on a large multi-document submission
        that pushed the prompt past the budget, the call errored, the retry
        layer exhausted, _chat_json returned {} — and every Yes/No question in
        that batch came back BLANK with nothing surfaced to the user. Chunking
        keeps each call inside budget; a question is answered from whichever
        chunk actually contains its evidence, and "first non-empty answer wins"
        on merge (the model omits questions it cannot ground, so chunks that
        lack the evidence simply return nothing for them)."""
        lines = []
        for f in q_fields:
            info  = eligible_fields.get(f) or {}
            qtext = _compliance_question_text(info.get("tu") if isinstance(info, dict) else "")
            lines.append(f"- {f}: {qtext}")
        questions_block = (
            "\n\nQUESTIONS — answer using ONLY the document above. Follow every HARD RULE. "
            "Omit any question the document does not specifically address; most of the time "
            f"that is the correct choice. (ACORD form {form_label}.)\n" + "\n".join(lines)
        )
        # Budget the document so (system + document + questions + reply headroom)
        # stays inside one call. The questions allowance is a CONSTANT worst case
        # for the same reason _raw_budget's is: deriving it from THIS batch's own
        # question text would give each batch different document chunk
        # boundaries, and the document is the cached prefix here. max() keeps the
        # overflow guard for an unusually long batch.
        _overhead = (
            len(_COMPLIANCE_SYSTEM_PROMPT)
            + max(_MAX_COMPLIANCE_BLOCK_CHARS, len(questions_block))
            + 2_000
        )
        # QUALITY CAP, same as `_raw_budget` (CALL2_RETRIEVAL_REDESIGN D1). The
        # capacity expression alone came out near 917,000 chars, so the compliance
        # pass ALSO sent the entire package in one call — the identical root-cause
        # bug, in the second of the two passes, and easy to miss because this
        # budget is computed independently. Found by
        # `test_a_large_document_actually_splits`, which asserts on what the model
        # was actually sent rather than on either budget expression.
        #
        # It matters at least as much here as in the general fill: these are the
        # Yes/No underwriting questions, and answering one from silence buried in
        # 175k tokens is exactly how the false-"N" flood happens.
        _doc_budget = min(
            max(10_000, _effective_budget_chars - _GPT_REPLY_RESERVE_CHARS - _overhead),
            max(_MIN_RAW_CHUNK_CHARS, _GAP_FILL_DOC_CHARS_PER_CALL),
        )
        _doc_chunks = _split_text_on_boundaries(raw_text, _doc_budget)
        if len(_doc_chunks) > 1:
            logger.info("gpt_fill COMPLIANCE: form=%s document split into %d chunks (%d chars)",
                        form_id, len(_doc_chunks), len(raw_text))

        answers: dict = {}
        quotes:  dict = {}
        for _ci, _chunk in enumerate(_doc_chunks):
            user_msg = f"=== DOCUMENT TEXT ===\n{_chunk}" + questions_block
            result = _chat_json(_COMPLIANCE_SYSTEM_PROMPT, user_msg,
                                _COMPLIANCE_RESPONSE_FORMAT, stage="compliance")
            _a = (result.get("answers") or {}) if isinstance(result, dict) else {}
            _q = (result.get("quotes")  or {}) if isinstance(result, dict) else {}
            for _f, _v in _a.items():
                if _f not in answers:            # first chunk that grounds it wins
                    answers[_f] = _v
                    if _q.get(_f):
                        quotes[_f] = _q[_f]
            if len(answers) >= len(q_fields):
                # DELIBERATELY NOT given the general fill's auto-rescan treatment.
                # This absorber is strictly FIRST-WINS (`if _f not in answers`), so
                # once every question in the batch has a grounded answer, sending
                # the remaining chunks cannot change a single one of them — it is
                # pure spend. The general fill differs: in rescan mode it re-asks
                # and majority-votes, so extra chunks there can actually move a
                # value.
                #
                # The residual risk is real and is NOT fixed here: a question
                # answered "N" from chunk 1 is never revisited against a chunk-3
                # endorsement that makes it "Y". Fixing that means changing this
                # pass's merge semantics (majority or latest-wins), and this pass
                # is the one that was carefully tuned to stop a false-"N" flood
                # (see _COMPLIANCE_SYSTEM_PROMPT). Changing its merge rule to buy
                # a rare supersession, at the cost of possibly reopening that
                # flood, is a bad trade to make blind. Logged so it is visible.
                if _ci < len(_doc_chunks) - 1:
                    logger.warning(
                        "gpt_fill COMPLIANCE_PARTIAL: form=%s all %d question(s) "
                        "answered by chunk %d of %d — remaining %d chunk(s) not sent "
                        "for these questions. Answers are first-answer-wins and were "
                        "NOT rechecked against later pages.",
                        form_id, len(q_fields), _ci + 1, len(_doc_chunks),
                        len(_doc_chunks) - _ci - 1,
                    )
                break
        return answers, quotes

    def _run_compliance_pass(q_fields: List[str]) -> None:
        if not q_fields:
            return
        batches = [q_fields[i : i + _COMPLIANCE_BATCH]
                   for i in range(0, len(q_fields), _COMPLIANCE_BATCH)]
        logger.info("gpt_fill COMPLIANCE: form=%s questions=%d batches=%d",
                    form_id, len(q_fields), len(batches))
        qset, kept = set(q_fields), 0

        def _absorb_compliance(answers: dict, quotes: dict) -> None:
            nonlocal kept
            for fld, val in (answers or {}).items():
                if fld not in qset or _is_empty_llm_value(val):
                    continue
                vstr = str(val).strip()
                candidate_counts.setdefault(fld, {})
                candidate_counts[fld][vstr] = candidate_counts[fld].get(vstr, 0) + 1
                q = (quotes or {}).get(fld)
                if q and str(q).strip():
                    all_question_grounding[fld] = str(q).strip()
                    # Bound to THIS answer, same reason as _absorb's copy: the
                    # compliance pass also runs in batches whose answers merge.
                    grounding_by_value.setdefault(fld, {})[vstr] = str(q).strip()
                kept += 1

        if len(batches) <= 1:
            _absorb_compliance(*_run_one_compliance_batch(q_fields))
        else:
            # Warm the shared (system + document) prefix with one completed call
            # before fanning out — but only ONCE per process for this prefix, not
            # once per outer batch (see _claim_warmup / C27).
            _rest = batches
            if _should_warm("compliance"):
                _absorb_compliance(*_run_one_compliance_batch(batches[0]))
                _rest = batches[1:]
            if _rest:
                with concurrent.futures.ThreadPoolExecutor(
                    max_workers=min(_FIELD_BATCH_POOL, len(_rest)),
                    thread_name_prefix="gpt-fill-compliance",
                ) as _pool:
                    _futs = [_pool.submit(_run_one_compliance_batch, b) for b in _rest]
                    for _fut in concurrent.futures.as_completed(_futs):
                        _absorb_compliance(*_fut.result())
        logger.info("gpt_fill COMPLIANCE_DONE: form=%s answered=%d/%d", form_id, kept, len(q_fields))

    _run_compliance_pass(compliance_fields)

    # ── Field sub-batch dispatch for everything else (bounded parallel) ───────
    # Flat 40-field slicing (unchanged for ordinary fields) would happily split
    # a table-group's columns across separate batches - i.e. separate LLM
    # calls that never see each other's data at all, making row-alignment
    # impossible no matter how the prompt is worded. Each table-group (see
    # detection above) is therefore packed as ONE atomic batch of its own;
    # everything else is bin-packed into ordinary _FIELD_FILL_BATCH-sized
    # batches exactly as before.
    def _pack_field_batches(fields: List[str], batch_size: int) -> List[List[str]]:
        """Bin-pack fields into sub-batches, keeping every table group WHOLE.

        The row-alignment invariant (improving-ll.md C19) is that all columns of a
        table must be visible to ONE call — otherwise the call filling row D cannot
        see what rows A-C already claimed, and it borrows values. That invariant
        says a table must not be SPLIT. It does not say a table must be ALONE.

        This function used to emit each table group as its own dedicated batch,
        which is a much stronger condition than the invariant requires, and it was
        expensive. Measured on the real 5-form union: **46 gap-fill calls, 34 of
        them partial, many carrying only 3-5 fields** — each paying a full call's
        fixed prompt overhead and a round trip to ask about four cells. 820 fields
        went out in 46 calls where 21 would hold them.

        So table groups are now packed as INDIVISIBLE UNITS into the same bins as
        ordinary fields: a group either fits in the current batch or starts a new
        one, but it is never cut. Every column of every table still lands in
        exactly one call. The prompt is unchanged — `_render_fields_block` renders
        each group as its own `_table_group_block`, so two tables in one call are
        still presented as two distinct tables.

        A single table group LARGER than `batch_size` still gets its own batch and
        still exceeds the size cap, exactly as before — splitting it would break
        the invariant, and that trade was already made.

        `FIELD_BATCH_PACK_TABLES=0` restores the old one-table-per-call behaviour.
        It is here because `_FIELD_FILL_BATCH=40` was tuned by accuracy work, and
        while this change never puts more than 40 fields in a batch, it does make a
        40-field batch denser (table blocks are longer per field than a plain spec
        line). That is the one plausible quality risk, so it stays revertible until
        an accuracy baseline confirms it.
        """
        # Collect indivisible UNITS in first-appearance order. A unit is either a
        # detected table bucket, a multi-slot repeating group, or a lone field.
        #
        # SLOT GROUPS ARE UNITS TOO, and that is a fix, not a side effect. A slot
        # group is rendered with "find up to N separate real values ... put the 1st
        # in _A, the 2nd in _B ... NEVER copy the same value into more than one
        # slot". A call that can see _A and _B but not _C cannot honour that: it
        # has no idea _C exists, and the call that gets _C has no idea _A and _B
        # were already claimed. That is the C19 failure mode one level down, and it
        # was already happening — measured on the real 5-form union, **27
        # repeating groups were split across separate calls** by plain 40-field
        # slicing, before any change in this work. Only detected TABLE buckets
        # (>=3 co-occurring columns) were ever protected.
        #
        # "Group" means `repeating_group_key` = (base, TOOLTIP), never base alone.
        # ACORD 25's insurer tooltips end "As used here, this is Insurer B." — a
        # per-row suffix — so Insurer_FullName_B..F are six separate one-slot
        # groups that need no joint reasoning. Counting by base name instead
        # inflates the figure above to 92 and flags those as violations; it is the
        # wrong denominator.
        buckets: Dict[Any, List[str]] = {}
        order: List[Any] = []
        seen: set = set()
        for f in fields:
            _gk = _group_key(f)
            _key = None
            if _gk:
                _tb = _table_group_membership.get(_gk)
                if _tb is not None:
                    _key = ("table", _tb)
                elif len(_base_to_slots.get(_gk, [])) > 1:
                    _key = ("slots", _gk)
            if _key is None:
                order.append(f)
                continue
            buckets.setdefault(_key, []).append(f)
            if _key not in seen:
                seen.add(_key)
                order.append(_key)

        if not _PACK_TABLES_WITH_FIELDS:
            # Legacy: every table group is its own call; slot groups unprotected.
            batches: List[List[str]] = []
            current: List[str] = []
            for item in order:
                if isinstance(item, tuple) and item[0] == "table":
                    batches.append(buckets[item])
                    continue
                unit = buckets[item] if item in buckets else [item]
                current.extend(unit)
                if len(current) >= batch_size:
                    batches.append(current)
                    current = []
            if current:
                batches.append(current)
            return batches

        # ── Partition by FAMILY before packing (CALL2_RETRIEVAL_REDESIGN D4) ──
        # A batch is one LLM call. Packing in dictionary order put a VIN, a GL
        # aggregate limit, a producer phone and a roof year in the SAME call - four
        # unrelated retrieval problems over one document, and the model has to run
        # four separate searches to answer 40 questions.
        #
        # The family is already in the ACORD field name: its leading underscore
        # segment. Measured on the real 125+126+127 union, 834 fields resolve to
        # 25 families (Vehicle 220, Driver 130, GeneralLiabilityLineOfBusiness 71,
        # AdditionalInterest 60, NamedInsured 56, ...). Free structure, no
        # hand-labelling, no new data.
        #
        # Packing WITHIN a family means one call is one topic ("read me the vehicle
        # schedule"), which is also what makes chunk routing meaningful - a
        # single-topic group has a chunk ranking; a mixed bag does not.
        #
        # Table and slot atomicity (C19/C29) is untouched: a unit is still
        # indivisible, and every unit's fields share a family by construction
        # (they share a base name, and the family is a prefix of the base).
        # FIELD_BATCH_GROUP_BY_FAMILY=0 reverts to the previous ordering.
        def _unit_fields(item) -> List[str]:
            return buckets[item] if item in buckets else [item]

        def _unit_family(item) -> str:
            # A detected TABLE bucket is one coherent schedule ("AdditionalInterest",
            # "Vehicle") whose COLUMNS legitimately carry different leading
            # segments - AdditionalInterest's table includes CityName_*,
            # PostalCode_*, StateOrProvinceCode_*. The unit is indivisible (C19),
            # so its family is the BUCKET's prefix; taking the first column's
            # would file the whole schedule under "CityName" and scatter related
            # tables apart.
            if isinstance(item, tuple) and item and item[0] == "table":
                return _field_family(str(item[1]))
            return _field_family(_unit_fields(item)[0])

        if _GROUP_BATCHES_BY_FAMILY:
            _by_family: Dict[str, List[Any]] = {}
            _family_order: List[str] = []
            for item in order:
                _fam = _unit_family(item)
                if _fam not in _by_family:
                    _by_family[_fam] = []
                    _family_order.append(_fam)
                _by_family[_fam].append(item)
            # ── Big families pure, small families share ──────────────────────
            # MEASURED CORRECTION. The first version gave every family its own
            # batch (one pass each). That is topically ideal and economically
            # absurd: the union has 25-56 families, each family's batches are
            # then walked against up to 13 chunks, and the FAMILY COUNT becomes
            # the floor on the call count. Measured on the 700k / 5-form run:
            # 897 calls, and raising the batch size 40 -> 160 barely moved it
            # (897 -> 611) because a 9-field family is one batch at any cap.
            #
            # A family below half a batch cannot fill a call on its own, and a
            # call carrying "Producer (9) + CancelNonRenew (8) + ..." is still 2-3
            # searches rather than the 15 unrelated ones the old dictionary-order
            # packing produced. So: families are laid out CONTIGUOUSLY and packed
            # continuously, with a flush only when the next family is big enough
            # to deserve a clean start. Vehicle (220) and Driver (130) - which are
            # most of the field count - still get pure calls.
            _big = max(2, batch_size // 2)
            _pass_items: List[Any] = []
            for _fi, _fam in enumerate(_family_order):
                _items = _by_family[_fam]
                _n_fields = sum(len(_unit_fields(i)) for i in _items)
                if _fi and _n_fields >= _big:
                    _pass_items.append(_FAMILY_FLUSH)
                _pass_items.extend(_items)
            _passes = [_pass_items]
        else:
            _passes = [order]

        batches: List[List[str]] = []
        for _pass_items in _passes:
            current: List[str] = []
            for item in _pass_items:
                if item is _FAMILY_FLUSH:
                    # A family large enough to fill calls of its own starts on a
                    # clean batch, so its topic is not diluted by the tail of the
                    # previous family.
                    if current:
                        batches.append(current)
                        current = []
                    continue
                unit = _unit_fields(item)
                if len(unit) > batch_size:
                    # A single group larger than the cap: its own batch, over the cap by
                    # necessity. Splitting it would break the alignment invariant, and
                    # that trade was already made for tables. (Slot groups top out at 14
                    # slots — ACORD's row letters are A-N — so only tables reach here.)
                    if current:
                        batches.append(current)
                        current = []
                    batches.append(unit)
                    continue
                if current and len(current) + len(unit) > batch_size:
                    batches.append(current)
                    current = []
                current.extend(unit)
            if current:
                batches.append(current)
        return batches

    # ── STAGE A: the declarations index ───────────────────────────────────────
    # Ask the whole field list against 3% of the package before asking any of it
    # against 100%. See `_render_dec_index` for what the index is and D11 in
    # CALL2_RETRIEVAL_REDESIGN for why this stage exists at all.
    #
    # WHAT IT COSTS, and what it does NOT cost:
    #   - Stage A itself is one small call per field batch. On the ORBIN package
    #     that is a ~17k-char prompt against Stage B's ~70k.
    #   - Fields it answers do not walk the raw document. That IS the saving, and
    #     it is a real trade: an endorsement later in the package can no longer
    #     supersede a dec-page value for those fields. The trade is defensible in
    #     the one direction that matters - an endorsement that CHANGES a
    #     declarations figure prints its own schedule, which is a schedule page,
    #     which the recorder captures, so the superseding value is in the index
    #     too, under its own heading, CO-VISIBLE with the value it supersedes.
    #     The 13-chunk walk never achieves that; it sees the two forty pages and
    #     several calls apart and settles it by majority vote.
    #   - Fields it does NOT answer are re-packed and walk the entire document
    #     exactly as before. No field loses coverage; batches lose passengers.
    #
    # NOT APPLIED TO THE COMPLIANCE PASS, deliberately. Yes/No disclosure
    # questions are answered from policy wording and endorsements - the exact
    # content the recorder is instructed never to record - so an index pass there
    # would be a call that can only ever return nothing. That pass is untouched.
    _dec_index_parts: List[str] = []
    if other_fields:
        try:
            _dec_index_parts = _dec_index_chunks(
                (facts or {}).get("dec_page_entries"),
                max(_MIN_RAW_CHUNK_CHARS, _GAP_FILL_DOC_CHARS_PER_CALL
                    * _DEC_INDEX_BUDGET_MULT),
            )
        except Exception as _dx:                                   # noqa: BLE001
            # An index failure must never cost a form its gap fill. Stage B is
            # the entire pre-2026-08-13 pipeline and is still ahead of us.
            logger.warning("gpt_fill: declarations index unavailable (%s) — "
                           "every field walks the raw document", _dx)
            _dec_index_parts = []

    def _run_index_batch(batch_fields: List[str], batch_label: str):
        """One field batch against the index. Same shape as `_run_field_batch`:
        LOCAL accumulators only, merged on the main thread, so batches are
        thread-safe by construction rather than by lock."""
        local_counts: Dict[str, Dict[str, int]] = {}
        local_raw: set = set()
        local_grounding: Dict[str, str] = {}
        local_gbv: Dict[str, Dict[str, str]] = {}
        for _pi, _part in enumerate(_dec_index_parts):
            active = [f for f in batch_fields if f not in local_counts]
            if not active:
                break
            prompt = _build_prompt(active, "", 0, 1, index_text=_part)
            logger.info(
                "gpt_fill STAGE_A: batch=%s form=%s index_part=%d/%d active_fields=%d "
                "prompt_chars=%d",
                batch_label, form_id, _pi + 1, len(_dec_index_parts), len(active),
                len(prompt),
            )
            _absorb(_call_llm_sync(prompt), active, local_counts, local_raw,
                    local_grounding,
                    chunk_label=f"{batch_label}:INDEX{_pi + 1}/{len(_dec_index_parts)}",
                    grounding_by_value=local_gbv)
        return local_counts, local_raw, local_grounding, local_gbv

    if _dec_index_parts:
        _a_batches = _pack_field_batches(other_fields, _FIELD_FILL_BATCH)
        _an = len(_a_batches)
        _a_start = 0
        # Stage A runs FIRST, so it is the natural place to warm the shared
        # [system + form label + facts] prefix that Stage B also repeats. Claiming
        # it here rather than in Stage B means the warming call is the small one.
        if _an > 1 and _should_warm("gap_fill"):
            _merge(*_run_index_batch(_a_batches[0], f"A1/{_an}"))
            _a_start = 1
        if _a_start < _an:
            with concurrent.futures.ThreadPoolExecutor(
                max_workers=min(_FIELD_BATCH_POOL, _an - _a_start),
                thread_name_prefix="gpt-fill-index",
            ) as _apool:
                _afuts = [
                    _apool.submit(_run_index_batch, _a_batches[bi], f"A{bi + 1}/{_an}")
                    for bi in range(_a_start, _an)
                ]
                for _afut in concurrent.futures.as_completed(_afuts):
                    _merge(*_afut.result())
        _answered_by_index = [f for f in other_fields if candidate_counts.get(f)]
        other_fields = [f for f in other_fields if not candidate_counts.get(f)]
        logger.info(
            "gpt_fill STAGE_A done: form=%s index_chars=%d calls=%d answered=%d "
            "remaining_for_raw_walk=%d",
            form_id, sum(len(p) for p in _dec_index_parts), _an,
            len(_answered_by_index), len(other_fields),
        )

    # ── STAGE B: the raw document walk (unchanged) ────────────────────────────
    # Re-packing here is where the call saving actually lands. Stage A typically
    # empties most batches; without a re-pack those batches would still exist,
    # still be dispatched, and still walk every chunk to ask about their two
    # survivors. Packing the survivors together turns 7 batches x 13 chunks into
    # 2 x 13. `_pack_field_batches` keeps every table group and slot group whole
    # on this path exactly as it does on the first, so C19/C29 row alignment is
    # unaffected by the re-pack.
    field_batches = _pack_field_batches(other_fields, _FIELD_FILL_BATCH)
    logger.info(
        "gpt_fill: form=%s total_fields=%d compliance=%d other=%d field_batches=%d batch_size=%d "
        "table_groups=%d raw_text_chars=%d",
        form_id, len(field_list), len(compliance_fields), len(other_fields),
        len(field_batches), _FIELD_FILL_BATCH, len(_table_buckets), len(raw_text),
    )

    if len(field_batches) <= 1:
        if field_batches:
            _merge(*_run_field_batch(other_fields, "1/1"))
    else:
        _n = len(field_batches)
        _start = 0
        # Warm the shared (system + facts + document) prefix with one completed
        # call before fanning out — but only ONCE per process for this prefix, not
        # once per outer batch (see _claim_warmup / C27).
        if _should_warm("gap_fill"):
            _merge(*_run_field_batch(field_batches[0], f"1/{_n}"))
            _start = 1
        if _start < _n:
            with concurrent.futures.ThreadPoolExecutor(
                max_workers=min(_FIELD_BATCH_POOL, _n - _start),
                thread_name_prefix="gpt-fill-fbatch",
            ) as _pool:
                _futs = [
                    _pool.submit(_run_field_batch, field_batches[bi], f"{bi + 1}/{_n}")
                    for bi in range(_start, _n)
                ]
                for _fut in concurrent.futures.as_completed(_futs):
                    _merge(*_fut.result())

    # ── Invariant I2: no chunk goes unread ────────────────────────────────────
    # Early-stopping (the ladder above) means a batch can answer everything before
    # reaching the end of its ranked chunk list, which could leave a chunk nobody
    # ever sent — a page the model never saw.
    #
    # PRECISE STATEMENT, because the loose version would be a lie:
    #   every chunk is read, UNLESS every field already has an answer.
    #
    # AND THIS IS A TRIPWIRE, NOT A WORKER — be honest about which. Under the
    # current walk semantics its sweep branch is UNREACHABLE, and provably so:
    #
    #   a batch stops only when ALL of its fields are answered
    #     => a batch holding one blank field walks EVERY chunk
    #     => any blank field anywhere means no chunk is unread
    #     => unread chunks exist ONLY IF every field is answered
    #
    # STAGE A DOES NOT BREAK THAT, and it was checked rather than assumed. Stage
    # A removes answered fields from `other_fields` BEFORE Stage B packs, so every
    # Stage B batch begins entirely blank and still walks every chunk. The one new
    # shape is Stage A answering EVERYTHING: then `other_fields` is empty, no chunk
    # is read at all, `still_blank` is empty, and this exits at I2_SKIP — which is
    # the invariant's own "unless every field already has an answer" clause,
    # satisfied by a cheaper route. The precise statement above is unchanged.
    #
    # So the honest reading is: this cannot find work to do today, and that is
    # the invariant holding, not the code being useless. It is kept because it
    # costs one set comparison and it FAILS LOUDLY the day someone adds a cap to
    # the walk (a max-chunks-per-group knob is the obvious future optimisation),
    # which is exactly when coverage would start being lost silently. If
    # I2_SWEEP ever appears in a log, the walk semantics changed and this is the
    # only thing standing between that change and a blank form.
    #
    # `GAP_FILL_FULL_RESCAN=1` is the absolute version for anyone who wants every
    # field re-checked against every chunk regardless of cost.
    def _sweep_unread_chunks() -> None:
        if not (_SWEEP_UNREAD_CHUNKS and _chunk_index is not None):
            return
        unread = [ci for ci in range(_chunk_index.n) if ci not in _chunks_seen]
        if not unread:
            logger.info("gpt_fill I2_OK: form=%s all %d chunk(s) were read.",
                        form_id, _chunk_index.n)
            return
        # `candidate_counts` is PRE-SEEDED with an empty dict for every field
        # (see its initialisation), so `f not in candidate_counts` is never true
        # and would silently make this whole branch dead for the wrong reason.
        # Blank means "no candidate values", not "key absent".
        still_blank = [f for f in other_fields if not candidate_counts.get(f)]
        if not still_blank:
            logger.info(
                "gpt_fill I2_SKIP: form=%s %d of %d chunk(s) unread, but every field "
                "already has an answer — nothing to ask them. Set "
                "GAP_FILL_FULL_RESCAN=1 to re-check answered fields against every "
                "chunk anyway.",
                form_id, len(unread), _chunk_index.n,
            )
            return
        logger.warning(
            "gpt_fill I2_SWEEP: form=%s %d of %d chunk(s) were never sent and %d "
            "field(s) are still blank — sweeping those chunks now.",
            form_id, len(unread), _chunk_index.n, len(still_blank),
        )
        for ci in unread:
            active = [f for f in other_fields if not candidate_counts.get(f)]
            if not active:
                break
            # Send the still-blank fields this chunk is most likely to answer,
            # highest-ranked first, capped at one ordinary batch.
            try:
                active = sorted(
                    active,
                    key=lambda f: -_chunk_index.score(
                        _router_vocab([f], eligible_fields), ci),
                )
            except Exception:                                  # noqa: BLE001
                pass
            active = active[:_FIELD_FILL_BATCH]
            prompt = _build_prompt(active, _canonical_chunks[ci], ci, _chunk_index.n)
            logger.info(
                "gpt_fill I2_SWEEP call: form=%s chunk %d/%d fields=%d prompt_chars=%d",
                form_id, ci + 1, _chunk_index.n, len(active), len(prompt),
            )
            _absorb(_call_llm_sync(prompt), active, candidate_counts,
                    all_raw_fields, all_question_grounding,
                    chunk_label=f"I2:{ci + 1}/{_chunk_index.n}",
                    grounding_by_value=grounding_by_value)

    try:
        _sweep_unread_chunks()
    except Exception as _sw_ex:                                # noqa: BLE001
        # A sweep failure must never lose the values the main passes already found.
        logger.warning("gpt_fill: I2 sweep failed (%s) — keeping main-pass results",
                       _sw_ex)

    # ── Conflict resolution ───────────────────────────────────────────────────
    # Among candidates from multiple chunks, the most-frequent value wins (majority vote).
    all_filled: dict = {}
    _rebound = 0
    for field, candidates in candidate_counts.items():
        if not candidates:
            continue
        # Majority vote across chunks — raw text is the ground truth
        _winner = max(candidates, key=lambda v: candidates[v])
        all_filled[field] = _winner
        # THE WINNER COLLECTS ITS OWN CITATION. Without this the quote is
        # whichever chunk answered LAST, which on a multi-chunk package can be
        # the chunk that gave the opposite answer - and that quote is what the
        # evidence gate judges and what the Explanation box prints.
        _own = (grounding_by_value.get(field) or {}).get(_winner)
        if _own and all_question_grounding.get(field) != _own:
            all_question_grounding[field] = _own
            _rebound += 1
    if _rebound:
        logger.info(
            "gpt_fill EVIDENCE_REBOUND form=%s fields=%d - the majority-vote "
            "winner carried another answer's citation; each now carries its own",
            form_id, _rebound,
        )

    # ── Deduplication: remove values duplicated across repeating-slot siblings ─
    # Safety net for when the LLM assigns the same value to multiple _A/_B/_C
    # slots despite the GROUP block instructions. Walk each group in slot order
    # (_A first) and clear any slot whose value has already appeared in an
    # earlier sibling.  Comparison is case-insensitive and whitespace-normalised.
    # Groups are keyed by (base, tooltip), so different roles that share a base
    # (e.g. lienholder rows vs vehicle-owner rows) are NOT cross-deduped.
    #
    # TABLE groups are EXCLUDED and handled row-wise below. Applying per-value
    # dedup to a table column destroys correct data: a fleet of three trucks
    # garaged in the same city legitimately has City_A = City_B = City_C =
    # "Denver", and the same is true of deductible, radius, territory, rate
    # class and every coverage indicator. Observed live on a real ACORD 127 run
    # (2026-07-29): 40+ correct cells were deleted in a single generation,
    # leaving row A complete and rows B/C almost entirely blank. The two prompts
    # are asking for different things and the safety nets must match — a slot
    # group is told "find N DISTINCT values, never repeat one", while a table is
    # told "fill one COMPLETE ROW per real entry", where repetition across rows
    # is expected and correct.
    # Schedule roots: the leading token of every prefix that WAS detected as a
    # real table on this form (e.g. "Vehicle" from Vehicle_PhysicalAddress,
    # "CommercialProperty" from CommercialProperty_Premises). Any group under
    # such a root is a per-ROW column of that schedule, so repetition down the
    # column is expected — even when the group itself has only ONE column and
    # therefore never qualified as a "table" on its own. That single-column case
    # is what made the first version of this fix insufficient:
    # Vehicle_RadiusOfUse_A/B/C is one column, is rendered as a "find N distinct
    # values" slot group, and had its correct 50/50/50 deleted down to just row
    # A. Groups outside every detected schedule root (Insurer_FullName,
    # additional-insured name lists, …) keep the original per-value dedup, which
    # is correct for them — those really are lists of distinct entities.
    _schedule_roots = {
        _p.split("_", 1)[0] for _p, _gks in _table_buckets.items()
        if any(g in _table_group_keys for g in _gks)
    }
    if _schedule_roots:
        logger.info("gpt_fill: dedup exempting schedule roots %s (per-row columns)",
                    sorted(_schedule_roots))

    def _under_schedule_root(base: str) -> bool:
        return any(base.startswith(r + "_") for r in _schedule_roots)

    for _gk, _slots in (_base_to_slots.items() if _ENABLE_SLOT_VALUE_DEDUP else []):
        if _gk in _table_group_keys:
            continue
        if _under_schedule_root(_gk[0] if isinstance(_gk, tuple) else str(_gk)):
            continue
        _seen: Dict[str, str] = {}  # normalised_value -> first slot that claimed it
        for _slot_field in _slots:  # already sorted _A, _B, _C, …
            _val = all_filled.get(_slot_field)
            if _val is None:
                continue
            _key = str(_val).strip().lower()
            if _key in _seen:
                logger.info(
                    "gpt_fill: dedup cleared duplicate '%s' from %s (same as %s)",
                    _val, _slot_field, _seen[_key],
                )
                del all_filled[_slot_field]
            else:
                _seen[_key] = _slot_field

    # NO row-level dedup for tables. This was tried and DELIBERATELY REMOVED —
    # do not reintroduce it. The idea was to catch the one real table failure
    # (the model writing the SAME entry into two rows) by clearing a row whose
    # filled cells are identical to an earlier row's. It cannot work, because a
    # call only ever sees a SUBSET of a table's columns: Pass 1/1.5 resolves
    # some, `_COMBINED_FIELD_BATCH` splits others across outer batches. Ask
    # about City/State/PostalCode alone and three trucks genuinely garaged in
    # one city produce three byte-identical rows — real data that the check
    # would delete. "Same entry twice" and "two entries that match on the
    # columns we happened to ask about" are indistinguishable from here.
    # The table prompt already forbids duplicating an entry, and `already_filled`
    # tells the model which rows Pass 1 spoke for; those are the right places to
    # prevent it. Deleting verified document data to guard a hypothetical is the
    # wrong trade.

    # ── Audit log ─────────────────────────────────────────────────────────────
    for field, value in all_filled.items():
        logger.info(
            "FIELD_SOURCE_AUDIT field=%s source=ai model=%s form_id=%s "
            "raw_text_sourced=%s chunks_agreed=%s",
            field, llm_model, form_id,
            str(field in all_raw_fields).lower(),
            candidate_counts.get(field, {}).get(value, 1),
        )

    logger.info(
        "gpt_fill DONE: form=%s fields_filled=%d/%d field_batches=%d model=%s",
        form_id, len(all_filled), len(eligible_fields), len(field_batches), llm_model,
    )
    if _llm_call_failures:
        # Loud, explicit: some fields are blank because a call DIED, not because
        # the document lacked an answer. Without this the two are identical from
        # the outside and a rate-limited run looks like a correct sparse fill.
        logger.error(
            "gpt_fill INCOMPLETE: form=%s — %d LLM call(s) permanently failed; some fields are "
            "BLANK due to call failure, NOT because the document lacked an answer. Causes: %s",
            form_id, len(_llm_call_failures), "; ".join(_llm_call_failures[:3]),
        )
    return {
        "filled_values":       all_filled,
        "new_mappings":        {},
        "raw_text_fields":     all_raw_fields,
        "question_grounding":  {f: q for f, q in all_question_grounding.items() if f in all_filled},
        "model_used":          llm_model,
        "llm_call_failures":   len(_llm_call_failures),
    }


# GL schedule-of-hazards DATA columns (ACORD 126) that the broker fills from a
# class-code / payroll / gross-sales schedule. They must be treated as fillable
# even though the broad "Hazard_" and "Premium" substrings below would otherwise
# blanket-block the entire hazard block — which force-blanked class codes,
# exposure basis, exposure amount, territory and classification and hid the
# high-priority gap the client flagged (Figure 29). The Rate / PremiumAmount
# columns are deliberately NOT here: those are underwriter-computed and stay
# blocked by the "Rate_" / "Premium" substrings.
_GL_HAZARD_FILLABLE_RE = re.compile(
    r"^GeneralLiability_Hazard_"
    r"(ClassCode|PremiumBasisCode|Exposure|TerritoryCode|Classification)_[A-N]$"
)


def _is_nonfillable_field(field: str) -> bool:
    """Return True when a field is carrier-computed or administrative and should
    never be retried via GPT even when its cached fact_key is None.

    These match _RAW_TEXT_SKIP_PATTERNS but are checked by name so we can keep
    Indicator fields OUT of this list (they ARE fillable business fields).
    """
    # Explicit allow (wins over the broad substrings): GL hazard data columns.
    # PremiumBasisCode in particular contains the substring "Premium", so this
    # override is required, not just a matter of dropping "Hazard_".
    if _GL_HAZARD_FILLABLE_RE.match(field):
        return False
    # Explicit allow: CommercialStructure_Location_ProducerIdentifier_{row} is
    # a naming false-positive caught by the "ProducerIdentifier" substring
    # below. Despite the name, its own schema tooltip is "the location number
    # for the premises" (the visible "LOC #" box) - a plain sequential number
    # derived from the canonical location list, not an agency-assigned code.
    # The broad "ProducerIdentifier" block below stays as-is for the fields it
    # was actually added for (Producer_CustomerIdentifier and similar).
    if field.startswith("CommercialStructure_Location_ProducerIdentifier_"):
        return False
    _NONFILLABLE_SUBSTRINGS = (
        # An ATTESTATION, not a fact. "Copy of the Notice of Information
        # Practices (Privacy) has been given to the applicant" is a statement
        # that the AGENCY DID something; no document can evidence it and no
        # model may assert it on the agency's behalf. Client report #19: "Retain
        # it only if the agency actually provided the required notice."
        # Present on ACORD 125 and 130 (verified across all 17 schemas).
        "InformationPracticesNotice",
        # INITIALS are a signature. `NamedInsured_Initials_A`'s own tooltip
        # reads "Initial here:" - it is the insured personally acknowledging a
        # statement, and the live run put a stray text fragment in it. Matched
        # with the leading underscore so `Driver_OtherGivenNameInitial_A`, a
        # legitimate NAME field, is untouched.
        "_Initials",
        "Signature", "_Sig", "InsurerLetterCode",
        "Attachment_", "Hazard_", "Premium", "Rate_", "Revision",
        "EditionIdentifier", "NeedAppearances",
        "Underwriter", "CarrierCode", "PolicyNumber_Carrier",
        # Agency-profile / carrier-filing identifiers. None of these appears
        # correctly on a declarations page, so anything the model finds is a
        # misread: a live run stamped the dec page's "Agent Number" as the
        # STATE PRODUCER LICENSE, and a carrier form title + form number
        # ("... COVERAGE FORM" / "CU0001") as the program name/code. The
        # client's own classification (Orbin report, part 15): producer
        # license / NPN come from the agency profile or AMS — never from the
        # uploaded documents and never from the client.
        "StateLicense", "Producer_NationalIdentifier", "Insurer_Product",
        # CustomerIdentifier / ProducerIdentifier are carrier- or agency-assigned
        # internal codes not present in policy document text. The gap-fill LLM
        # cannot infer them and hallucinated the producer name instead
        # (e.g. "RSG Specialty Atlanta Binding"). Blocking the entire
        # *Identifier suffix family closes all 116 exposed fields in one shot.
        "CustomerIdentifier",
        "ProducerIdentifier",
    )
    return any(s in field for s in _NONFILLABLE_SUBSTRINGS)


# ── Fact → form-field derivation (Beta Report §4.3) ───────────────────────────
# Used by the Core Underwriting Data reconciler to (a) name the true, complete
# set of forms a confirmed value flows into ("applied to N forms" badge) and
# (b) drive the post-generation cross-form consistency assertion. Pure derivation
# from static config + form schemas; cached.

@lru_cache(maxsize=1)
def _all_form_schemas() -> Dict[str, dict]:
    """Load every ``forms_schemas/ACORD_*_schema.json`` once (the field-name
    source of truth for fact→form derivation). Cached; pure disk read."""
    out: Dict[str, dict] = {}
    try:
        for name in sorted(os.listdir(FORMS_SCHEMAS_DIR)):
            if name.startswith("ACORD_") and name.endswith("_schema.json"):
                form_id = name[: -len("_schema.json")]
                try:
                    with open(os.path.join(FORMS_SCHEMAS_DIR, name), encoding="utf-8") as fh:
                        out[form_id] = json.load(fh)
                except Exception as exc:                  # noqa: BLE001 — skip & continue
                    logger.warning("fact-map: failed to load schema %s — %s", name, exc)
    except Exception as exc:                              # noqa: BLE001
        logger.warning("fact-map: cannot list schemas dir %s — %s", FORMS_SCHEMAS_DIR, exc)
    return out


def _first_rule_fact(field_name: str) -> Optional[str]:
    """The fact key the FIRST matching ``_ACORD_FIELD_RULES`` pattern assigns to
    ``field_name`` — mirrors the substring loop in ``_deterministic_map`` so rule
    shadowing is respected. None when no rule matches.

    Also mirrors the entity guard: a field the resolver refuses to fill from this
    fact must not be REPORTED as fed by it either, or field QA would compare a
    stamped value against an expectation that can never be met and raise a
    mismatch on every run."""
    for pattern, fact_key in _ACORD_FIELD_RULES:
        if pattern in field_name:
            if fact_key is not None and _entity_mismatch(field_name, fact_key):
                return None
            return fact_key
    return None


def _is_secondary_row(field_name: str) -> bool:
    """True when ``field_name`` is a non-primary repeating row (_B, _C, ... - a
    SECOND/additional named insured, premises, interest, etc.), False for a
    primary (_A) or non-row field.

    A secondary row is architecturally a DIFFERENT entity, not a repeat of the
    primary row's value - this is the same principle _enforce_post_fill_guards'
    row-dedup guard already relies on ("NamedInsured_FullName_B ... must not
    echo the row-A value"). A scalar fact (e.g. mailing_address) has exactly one
    value, so it can only ever be the SOURCE for the primary row; matching it to
    a secondary row too - as a plain substring match does - manufactures a false
    "value disagrees with source" report whenever that secondary row legitimately
    holds a different (or independently gap-filled) value.
    """
    m = _SCHED_ROW_RE.match(field_name)
    return bool(m and _ROW_LETTER_TO_IDX[m.group(2)] >= 1)


@lru_cache(maxsize=64)
def fact_to_form_fields(fact_key: str) -> Dict[str, Tuple[str, ...]]:
    """Map an extraction fact key to the ACORD form fields that DETERMINISTICALLY
    receive its value, grouped by form id.

    Mirrors the two deterministic stamping paths used by ``map_facts_to_form``:
      * Pass 1   — ``_ACORD_FIELD_RULES`` substring rules (first matching rule wins).
      * Pass 1.5 — per-form alias maps + the ``CANONICAL_TO_EXTRACTION`` bridge.

    Pass 2 (GPT gap fill) is intentionally excluded: it sources from raw document
    text rather than from the merged/confirmed fact, so it does not propagate a
    confirmed value. The result therefore reflects exactly the forms/fields a
    confirmed underwriting value flows into.

    Returns ``{form_id: (field_name, ...)}`` (field names sorted for stability).
    Pure derivation from static config + form schemas; cached.
    """
    result: Dict[str, set] = {}

    # ── Pass 1.5 alias path ──────────────────────────────────────────────────
    try:
        from services.alias_stamper import (
            _ALIAS_MAPS, CANONICAL_TO_EXTRACTION, _load_all_alias_maps,
        )
        _load_all_alias_maps()
        canon_keys = {c for c, k in CANONICAL_TO_EXTRACTION.items() if k == fact_key}
        if canon_keys:
            for form_id, alias_map in _ALIAS_MAPS.items():
                for field, canonical in alias_map.items():
                    if canonical not in canon_keys or _is_nonfillable_field(field):
                        continue
                    if _is_secondary_row(field):
                        continue
                    # Skip fields a Pass-1 rule deterministically claims for a
                    # DIFFERENT fact (alias only runs on Pass-1 leftovers).
                    rf = _first_rule_fact(field)
                    if rf not in (None, fact_key):
                        continue
                    result.setdefault(form_id, set()).add(field)
    except Exception as exc:                              # noqa: BLE001 — never block
        logger.warning("fact-map: alias path failed for %s — %s", fact_key, exc)

    # ── Pass 1 deterministic-rule path ───────────────────────────────────────
    if any(fk == fact_key for _, fk in _ACORD_FIELD_RULES):
        for form_id, schema in _all_form_schemas().items():
            for field in schema:
                if _is_nonfillable_field(field) or _is_secondary_row(field):
                    continue
                if _first_rule_fact(field) == fact_key:
                    result.setdefault(form_id, set()).add(field)

    # ── Pass 1 fallback path (_FACT_FALLBACKS) ───────────────────────────────
    # A field whose rule names a SPECIFIC fact is also fed by that fact's general
    # fallback, and this reverse index has to agree with the forward resolver or
    # the two drift. Concretely: BusinessInformation_FullTimeEmployeeCount reads
    # `num_employees_full_time` and falls back to `num_employees`, so a client
    # confirming `num_employees` through the questionnaire must still see that box
    # restamped. Without this the answer updates `facts`, moves SQS, and never
    # reaches the PDF - the exact live bug
    # test_apply_arq_answers_actually_stamps_a_canonical_only_question_end_to_end
    # was written to catch, which it duly caught again here.
    _specific_for_this_fact = {
        _specific for _specific, _general in _FACT_FALLBACKS.items()
        if _general == fact_key
    }
    if _specific_for_this_fact:
        for form_id, schema in _all_form_schemas().items():
            for field in schema:
                if _is_nonfillable_field(field) or _is_secondary_row(field):
                    continue
                if _first_rule_fact(field) in _specific_for_this_fact:
                    result.setdefault(form_id, set()).add(field)

    # ── Pass 1 special-prefix address path ───────────────────────────────────
    # NamedInsured mailing-address sub-fields (LineOne/City/State/Zip) don't map
    # to "mailing_address" directly - _resolve_special() derives them from it at
    # fill-time via the "_addr_*" pseudo-key (see _resolve_special above), and
    # "_loc_*" derives from "physical_address" the same way. Without this, a
    # caller asking fact_to_form_fields("mailing_address") - e.g. field_qa's
    # value-vs-source check - would see NO address fields at all, leaving the
    # single most safety-critical field family (client feedback: "address...
    # must be exact") unchecked. Map the pseudo-key family back to its real
    # source fact so those fields are included like any other.
    #
    # "_addr_*" is scoped to NamedInsured_* fields only, mirroring the same
    # restriction in _deterministic_map: Producer / AdditionalInterest /
    # CertificateHolder addresses are NOT captured as a "mailing_address" fact
    # (they're a different entity's address) and are gap-filled from raw text
    # instead - including them here would compare their correct, independently-
    # sourced value against the NAMED INSURED's address and manufacture a false
    # mismatch. "_loc_*" has no such restriction: both its users
    # (NamedInsured_PhysicalAddress_* and CommercialStructure_PhysicalAddress_*)
    # legitimately mean the insured's own premises.
    for _prefix, _source_fact in (("_addr", "mailing_address"), ("_loc", "physical_address")):
        if fact_key != _source_fact:
            continue
        for form_id, schema in _all_form_schemas().items():
            for field in schema:
                if _is_nonfillable_field(field) or _is_secondary_row(field):
                    continue
                if _prefix == "_addr" and not field.startswith("NamedInsured_"):
                    continue
                rf = _first_rule_fact(field)
                if rf and rf.startswith(_prefix + "_"):
                    result.setdefault(form_id, set()).add(field)

    return {fid: tuple(sorted(fields)) for fid, fields in result.items()}


def expected_value_for_field(field_name: str, fact_key: str, source_value: Any) -> Any:
    """The piece of ``source_value`` a QA/consistency check should compare
    ``field_name`` against, given the source fact it was included in
    ``fact_to_form_fields(fact_key)`` for.

    For an ordinary (non-address) field this is ``source_value`` unchanged. For
    an address sub-field (LineOne/City/State/Zip, routed through the "_addr_*"
    / "_loc_*" special-prefix mechanism - see ``_resolve_special``) the field
    only ever receives ONE piece of the full address, so comparing it against
    the WHOLE address string would manufacture a false mismatch on every
    address field (e.g. stamped "Aurora" vs full "7740 Foundry Ln, Aurora, CO
    80011" would never match as address text). Parses ``source_value`` the same
    way ``_resolve_special`` does and returns the matching piece so a value
    check compares like-for-like.
    """
    rf = _first_rule_fact(field_name)
    if not rf or not any(rf.startswith(p + "_") for p in _SPECIAL_PREFIXES):
        return source_value
    suffix = rf.split("_")[-1]
    return _parse_address(str(source_value or "")).get(suffix, "")


def forms_consuming_fact(fact_key: str) -> List[str]:
    """Sorted list of ACORD form ids a confirmed value for ``fact_key`` flows
    into deterministically. Thin wrapper over :func:`fact_to_form_fields`."""
    return sorted(fact_to_form_fields(fact_key).keys())


def compute_form_gaps(form_id: str, schema: dict, facts: dict) -> Tuple[dict, dict, set]:
    """
    Run Pass 1 (deterministic rules) and Pass 1.5 (alias stamping) ONLY.
    NO LLM call. Pure dictionary lookup.

    Used by the combined cross-form gap-fill orchestrator (Stage 4) to determine
    each form's gap list before running a single shared Pass 2 across all forms.

    Returns
    -------
    mapped : dict
        {field_name: value} for fields filled by Pass 1 + Pass 1.5
        (plus authoritative blanks for non-fillable and out-of-range schedule rows).
    unmatched : dict
        {field_name: schema_meta} for fields that need GPT in Pass 2.
    deterministic_filled : set
        Field names treated as authoritative (no highlight) — superset of `mapped`
        keys that includes deterministic blanks.

    Mirrors the Pass 1 + Pass 1.5 logic at the top of `map_facts_to_form`
    exactly. Kept as a standalone function so the orchestrator can preview gaps
    cheaply without paying for Pass 2.
    """
    if not schema:
        return {}, {}, set()

    # Tooltip-driven resolvers read the schema through this thread-local.
    _set_schema_context(schema)
    mapped: dict = {}
    unmatched: dict = {}
    deterministic_filled: set = set()

    for field in schema.keys():
        # The form's own edition - system metadata, never a question for anyone.
        # See _form_edition_identifier.
        if _FORM_EDITION_FIELD_RE.match(field):
            _ed = _form_edition_identifier(form_id)
            if _ed:
                mapped[field] = _ed
            deterministic_filled.add(field)
            continue

        # Non-fillable fields (signatures, premiums, rates, underwriter codes)
        # are never sent to GPT.
        if _is_nonfillable_field(field):
            # Mirror of map_facts_to_form's prior-coverage premium exception,
            # so the combined path's already-filled context sees the same grid.
            if "TotalPremiumAmount" in field and _PRIOR_COVERAGE_RE.match(field):
                _pc_amt = _resolve_prior_coverage_cell(field, facts)
                _pc_amt = None if _pc_amt is _SCHED_SKIP else _pc_amt
                if _pc_amt:
                    mapped[field] = _pc_amt
                    deterministic_filled.add(field)
                    continue
            mapped[field] = None
            deterministic_filled.add(field)
            continue

        # Schedule rows resolved against facts["..."] lists.
        sched = _resolve_schedule_row(field, facts)
        if sched is not _SCHED_SKIP:
            if sched is not None and not _is_empty_llm_value(sched):
                mapped[field] = sched
            elif field.endswith("_A") and _single_row_schedule(field, facts):
                # MIRROR `_deterministic_map`'s row-A scalar fallback. Without
                # this, the schedule branch short-circuits and Pass 1 is never
                # consulted - so an `_ACORD_FIELD_RULES` entry for a field that
                # is ALSO schedule-backed silently does nothing here while
                # working perfectly in `_deterministic_map`.
                #
                # Live proof (2026-08-14): ACORD 125's per-premises DESCRIPTION
                # OF OPERATIONS shipped BLANK after the rule that fills it from
                # `operations_description` was added. `_deterministic_map`
                # returned the full description; this function returned None,
                # because `_resolve_schedule_row` answers None for row A both
                # when the list is empty AND when row 1 simply has no value for
                # that column - and the second case never reached Pass 1.
                #
                # Deliberately does NOT add to `unmatched`: an empty schedule
                # cell with no scalar rule stays a deterministic blank exactly
                # as before, so this costs no extra gap-fill questions.
                _fb = _deterministic_map(field, facts)
                if _fb != "UNMATCHED" and not _is_empty_llm_value(_fb):
                    mapped[field] = _fb
            deterministic_filled.add(field)
            continue

        # Pass 1: _ACORD_FIELD_RULES + address decomposition + indicator derivation.
        result = _deterministic_map(field, facts)
        if result == "UNMATCHED" or _is_empty_llm_value(result):
            # An OWNING resolver that produced no value means the box must stay
            # empty — the same authoritative-blank contract map_facts_to_form
            # applies. This branch was MISSING here (found 2026-08-10): the
            # docstring claimed this function "mirrors exactly", but every
            # owner-resolved blank (prior-coverage grid, Q4 other-policy rows,
            # producer printed name, ...) was put in `unmatched` and shipped to
            # the LLM as a question — whose answer map_facts_to_form then
            # silently discarded, since its own unmatched set excluded the
            # field. Pure token waste plus prompt noise; stamped output is
            # unchanged by fixing it.
            if _is_authoritative_blank_field(field, facts):
                deterministic_filled.add(field)
                continue
            unmatched[field] = schema[field]
        else:
            mapped[field] = result
            deterministic_filled.add(field)

    # Pass 1.5: alias-based deterministic stamping (opt-in via flag).
    if unmatched and form_id:
        try:
            from config.settings import ENABLE_ALIAS_STAMPING
            if ENABLE_ALIAS_STAMPING:
                from services.alias_stamper import stamp_form_fields
                alias_filled = stamp_form_fields(form_id, facts, list(unmatched.keys()))
                for field, value in alias_filled.items():
                    if value is not None and not _is_empty_llm_value(value):
                        # THE FOURTH DOOR, and the one nothing was watching.
                        # Pass 1.5 writes `mapped[field]` DIRECTLY - it never
                        # routes through `_deterministic_map`, so every
                        # authoritative-blank resolver was invisible to it, and
                        # it never touches `gpt_filled_set`, so every guard
                        # scoped to gap fill was invisible too. Measured across
                        # all 17 alias maps: **137 fields that a resolver owns**
                        # were being overridden here - the FAX box (six live
                        # runs), the deposit, REMARKS, the applicant website,
                        # the no-loss attestation, all 64 prior-coverage cells.
                        # Each of those resolvers exists because a box has NO
                        # legitimate document source; an alias map cannot know
                        # that, because it is a pure name->fact dictionary.
                        if _is_authoritative_blank_field(field, facts):
                            logger.info(
                                "alias_stamp SKIPPED %s - a resolver owns this "
                                "box; alias maps cannot override an "
                                "authoritative blank", field,
                            )
                            continue
                        mapped[field] = value
                        deterministic_filled.add(field)
                        unmatched.pop(field, None)
        except Exception as exc:                # noqa: BLE001 — never block the pipeline
            logger.warning("compute_form_gaps ALIAS form=%s | error: %s", form_id, exc)

    return mapped, unmatched, deterministic_filled


_SCHEDULE_ROW_RE = re.compile(r"^(.+?)_([A-N])$")
# Hard ceiling on a schedule-aware outer batch. A schedule is kept whole even
# when that overshoots _COMBINED_FIELD_BATCH, but not without limit — beyond
# this it is split and the row-alignment risk is accepted rather than building
# one enormous call.
_COMBINED_BATCH_HARD_MAX = int(os.getenv("COMBINED_BATCH_HARD_MAX", "600"))


def _pack_schedule_aware_batches(field_items: List[tuple]) -> List[List[tuple]]:
    """Split the cross-form union into outer batches WITHOUT cutting a schedule.

    Why this is not a plain slice (improving-ll.md C19): the naive
    `field_items[i:i+200]` put ACORD 127's vehicle rows A-C in one outer batch
    and row D in the next. Each outer batch is a separate
    `_fill_unmatched_with_gpt` invocation, so the call filling row D could not
    see rows A-C and had no way to know which real vehicle was still unclaimed.
    Measured live 2026-07-29, and it put WRONG values on the form:
    `Vehicle_CostNewAmount_D = $58,900` (vehicle 1's cost; vehicle 4 is $41,800)
    and `Vehicle_RateClassCode_D = 91560` / `Vehicle_SpecialIndustryClassCode_D
    = 92478` — the two General Liability class codes, borrowed from a different
    page entirely. `_pack_field_batches` already keeps a table atomic one level
    down; this applies the same rule at the level that was breaking it.

    A "schedule" is any leading name segment (Vehicle, Driver,
    CommercialProperty, …) that appears with MORE THAN ONE row letter across the
    union — i.e. something that really does have multiple rows to align. Fields
    with no row suffix, and roots that only ever appear as a single row, are
    packed normally.
    """
    root_rows: Dict[str, set] = {}
    for name, _meta in field_items:
        m = _SCHEDULE_ROW_RE.match(name)
        if m:
            root_rows.setdefault(name.split("_", 1)[0], set()).add(m.group(2))
    schedule_roots = {r for r, rows in root_rows.items() if len(rows) > 1}

    # Preserve first-appearance order so batch contents stay readable in logs.
    groups: List[List[tuple]] = []
    index_of: Dict[str, int] = {}
    for name, meta in field_items:
        m = _SCHEDULE_ROW_RE.match(name)
        root = name.split("_", 1)[0] if m else None
        if root in schedule_roots:
            if root not in index_of:
                index_of[root] = len(groups)
                groups.append([])
            groups[index_of[root]].append((name, meta))
        else:
            groups.append([(name, meta)])

    batches: List[List[tuple]] = []
    current: List[tuple] = []
    for g in groups:
        if len(g) > _COMBINED_BATCH_HARD_MAX:
            # Pathologically large schedule: flush, then split it on its own.
            if current:
                batches.append(current)
                current = []
            for i in range(0, len(g), _COMBINED_BATCH_HARD_MAX):
                batches.append(g[i : i + _COMBINED_BATCH_HARD_MAX])
            continue
        if current and len(current) + len(g) > _COMBINED_FIELD_BATCH:
            batches.append(current)
            current = []
        current.extend(g)
    if current:
        batches.append(current)

    if schedule_roots:
        logger.info(
            "combined_gap_fill: schedule-aware batching kept %d schedule(s) whole: %s",
            len(schedule_roots), sorted(schedule_roots),
        )
    return batches or [field_items]


def combined_gap_fill(
    forms_to_unmatched: Dict[str, dict],
    facts: dict,
    raw_text: str,
    model: str = None,
    forms_to_mapped: Optional[Dict[str, dict]] = None,
) -> Dict[str, dict]:
    """
    Run ONE shared GPT pass to fill the deduplicated union of gap fields across
    all selected forms (Stage 5 of the extraction architecture).

    Parameters
    ----------
    forms_to_unmatched : Dict[form_id, Dict[field_name, schema_meta]]
        Per-form gap lists (typically produced by `compute_form_gaps`).
    facts : dict
        The shared extraction facts (same dict passed to per-form maps).
    raw_text : str
        Full extracted document text. Chunked internally by `_fill_unmatched_with_gpt`.
    model : str, optional
        Override model id. Default: GPT_MODEL.
    forms_to_mapped : Dict[form_id, Dict[field_name, value]], optional
        Each form's Pass 1/1.5 `mapped` dict (the OTHER return value of
        `compute_form_gaps`, alongside `unmatched`). Passed through to
        `_fill_unmatched_with_gpt` as `already_filled` so a multi-column TABLE
        (e.g. ACORD 140's Premises Information) whose row A was already
        resolved deterministically - and so never appears in `forms_to_
        unmatched` at all - doesn't get silently re-discovered and duplicated
        into row B by a gap-fill call with no visibility into what Pass 1
        already found. Field names are unique enough across forms in practice
        that a single merged dict is used for every batch; harmless even where
        it isn't, since it only ever SUPPRESSES an already-known row instead
        of asking for one.

    Returns
    -------
    Dict[form_id, {"filled_values": dict, "raw_text_fields": set, "question_grounding": dict, "model_used": str}]
        Per-form fill results, distributed from the shared LLM output. Each form
        only receives values for fields *it* asked for.

    Design notes
    ------------
    Fields are deduplicated by exact ACORD name (e.g. `Producer_FullName_A`).
    Across our 17 schemas, ~858 of 4571 unique field names appear in 2+ forms;
    those de-dupe automatically. Form-unique fields are passed through unchanged.

    Same chunking, retries, prompt skeleton, and majority-vote conflict
    resolution as the existing per-form Pass 2 — implemented by delegating to
    `_fill_unmatched_with_gpt` with the unioned input.
    """
    # Default empty results per form so callers can iterate safely.
    empty_result_for = lambda: {                      # noqa: E731
        "filled_values": {},
        "raw_text_fields": set(),
        "question_grounding": {},
        "model_used": model or GPT_MODEL,
    }
    per_form: Dict[str, dict] = {fid: empty_result_for() for fid in forms_to_unmatched}

    if not forms_to_unmatched:
        return per_form

    # Per-SUBMISSION state resets. Both of these are process-global caches whose
    # whole purpose is to be shared across the outer batches of ONE run, and both
    # were previously left to leak into the next run on the same worker:
    #   * the call budget only ever shrank, so one oversized document doubled the
    #     chunk count and cost of every later submission until restart (C28);
    #   * the warm-up set would grow without bound and, worse, suppress the
    #     warm-up a genuinely new prefix needs (C27).
    reset_call_budget()
    reset_prefix_warmup()

    # ── What the MODEL reads (see RETRIEVAL_CHANGES.md) ──────────────────────
    # Measured on the client's real package: the whole 683,601-char document went
    # into all 44 calls, the field list was ~1% of a 724k-char prompt, and the
    # model answered 42 of 159 fields (26%). It was not failing to read - it was
    # being asked 40 unrelated questions inside a 174k-token haystack that is
    # mostly standard policy wording, and that wording contains a plausible wrong
    # answer to almost every ACORD 125 General Information question.
    #
    # ONE filtered document for the whole run, so OpenAI's prefix cache (measured
    # at 98-99% here) keeps working and the call count is unchanged. Cost falls in
    # proportion to the document.
    #
    # `raw_text` ITSELF IS NOT REASSIGNED, and that is load-bearing. Everything
    # downstream of the model - the evidence gate, `_value_in_raw_text`, the NAIC
    # and classification-code guards - VERIFIES the model's output against the
    # COMPLETE document. Point verification at the filtered copy and any answer
    # grounded in a dropped region gets wrongly blanked, i.e. the change starts
    # deleting correct data. Only the PROMPT is filtered.
    #
    # `GAP_FILL_TEXT_SELECTION=0` restores the previous behaviour exactly.
    try:
        from services.text_selection import select_gap_fill_text
        _prompt_text, _sel_stats = select_gap_fill_text(
            raw_text, facts, label=",".join(sorted(forms_to_unmatched)) or "gap_fill",
        )
    except Exception as _sel_ex:                       # noqa: BLE001
        logger.warning("combined_gap_fill: text selection unavailable (%s) - "
                       "using the full document", _sel_ex)
        _prompt_text, _sel_stats = raw_text, {"applied": False}

    # Merge every form's Pass 1/1.5 results into one already_filled dict (see
    # docstring above) - passed through unchanged to every batch below.
    merged_already_filled: dict = {}
    for _fid_map in (forms_to_mapped or {}).values():
        if _fid_map:
            merged_already_filled.update(_fid_map)

    # Build union (dedup by ACORD field name) + form-ownership index.
    union_unmatched: dict = {}
    field_to_forms: Dict[str, list] = {}
    for form_id, fields_meta in forms_to_unmatched.items():
        if not fields_meta:
            continue
        for field_name, meta in fields_meta.items():
            if field_name not in union_unmatched:
                union_unmatched[field_name] = meta
            field_to_forms.setdefault(field_name, []).append(form_id)

    if not union_unmatched:
        return per_form

    total_asks   = sum(len(v or {}) for v in forms_to_unmatched.values())
    dedup_count  = len(union_unmatched)
    saved_pct    = 0 if total_asks == 0 else round(100 * (1 - dedup_count / total_asks))
    logger.info(
        "combined_gap_fill: forms=%d union_fields=%d total_asks=%d savings=%d%%",
        len(forms_to_unmatched), dedup_count, total_asks, saved_pct,
    )

    # GPT pass: batch fields into groups of _COMBINED_FIELD_BATCH (default 100).
    # With 1531 fields the fields block alone is ~612k chars, leaving almost no
    # budget for raw text inside _fill_unmatched_with_gpt. Batching keeps each
    # fields block ~40k chars so _fill_unmatched_with_gpt gets ~309k chars of
    # raw text budget per chunk (3 chunks for a 671k doc) — the full document
    # is still scanned; we do NOT truncate the document here.
    field_items = list(union_unmatched.items())

    # ── Split compliance questions from general fields BEFORE outer batching ──
    # Each outer batch is a separate `_fill_unmatched_with_gpt` invocation, and
    # each invocation re-partitions ITS OWN slice into compliance questions
    # (answered in groups of `_COMPLIANCE_BATCH`) and general fields (groups of
    # `_FIELD_FILL_BATCH`). Slicing the mixed union first therefore cut BOTH
    # streams at arbitrary points, and every cut leaves a runt batch that pays a
    # full call's fixed overhead for a handful of fields.
    #
    # Measured on the real 5-form union (1,359 fields, 133 of them compliance):
    #   before — compliance 18 calls with sizes [4, 10, 10, 9, 1, 10, ... 4, 2, 4, 5]
    #            and ~36 general calls
    #   ideal  — compliance 14, general 31
    # i.e. 9 of 63 calls (14%) existed only because of where the slice landed.
    #
    # Partitioning first makes every batch full except the last of each stream.
    # It changes NOTHING the model sees: the compliance pass is already a separate
    # call with a different system prompt, so a compliance field never shared a
    # call with a general field anyway. Batch sizes (40 / 10) are untouched — they
    # are frozen by prior accuracy work.
    _compliance_items = [(n, m) for n, m in field_items if is_compliance_question(n, m)]
    _general_items    = [(n, m) for n, m in field_items if not is_compliance_question(n, m)]

    batches: List[dict] = []
    # General fields keep schedule-aware packing (a schedule must stay whole — C19).
    if _general_items:
        batches += [dict(b) for b in _pack_schedule_aware_batches(_general_items)]
    # Compliance questions have no rows to align, so plain chunking is correct.
    # `_COMBINED_FIELD_BATCH` is a multiple of `_COMPLIANCE_BATCH`, so each outer
    # group divides into full inner batches.
    for _i in range(0, len(_compliance_items), _COMBINED_FIELD_BATCH):
        batches.append(dict(_compliance_items[_i : _i + _COMBINED_FIELD_BATCH]))
    if not batches:
        batches = [dict(field_items)]
    logger.info(
        "combined_gap_fill: field_batches=%d batch_size=%d total_fields=%d "
        "(general=%d compliance=%d, partitioned so neither stream is cut mid-batch)",
        len(batches), _COMBINED_FIELD_BATCH, len(field_items),
        len(_general_items), len(_compliance_items),
    )

    all_filled_values: dict = {}
    all_raw_text_fields: set = set()
    all_question_grounding: dict = {}
    used_model = model or GPT_MODEL

    # What the MODEL is told it is filling. `batch_id` below is a LOGGING label;
    # it used to be passed as `form_id` and interpolated straight into the system
    # prompt, so every combined run told the model "You are filling ACORD form
    # COMBINED_B1of2" — it could not tell a Workers Comp form from a Commercial
    # Auto one, and the per-batch system message killed prefix caching outright
    # (improving-ll.md C2). This label is constant across batches, so it also
    # stays inside the cacheable prefix.
    form_label = ", ".join(sorted(forms_to_unmatched.keys()))

    import time as _time
    for batch_idx, batch_fields in enumerate(batches):
        batch_id = f"COMBINED_B{batch_idx + 1}of{len(batches)}"
        # Pause between batches so the OpenAI TPM bucket refills. Without this
        # back-to-back batches each consumed ~60k input tokens and the first
        # chunk of every batch hit 429 → ~10s automatic backoff (see prod logs).
        # The 2s pause costs ~12s total but saves ~120s of cumulative 429 waits.
        if batch_idx > 0 and _COMBINED_BATCH_PAUSE_S > 0:
            _time.sleep(_COMBINED_BATCH_PAUSE_S)
        try:
            gpt_result = _fill_unmatched_with_gpt(
                # The FILTERED copy - see the block at the top of this function.
                # Verification downstream still reads the complete document.
                batch_fields, facts, batch_id, model=model, raw_text=_prompt_text,
                already_filled=merged_already_filled, form_label=form_label,
            )
        except Exception as exc:                      # noqa: BLE001
            logger.warning("combined_gap_fill: batch %s failed — %s", batch_id, exc)
            continue
        all_filled_values.update(gpt_result.get("filled_values", {}) or {})
        all_raw_text_fields.update(gpt_result.get("raw_text_fields", set()) or set())
        all_question_grounding.update(gpt_result.get("question_grounding", {}) or {})
        used_model = gpt_result.get("model_used", used_model)

    filled_values   = all_filled_values
    raw_text_fields = all_raw_text_fields

    # Distribute results back to each requesting form. A value flows to every
    # form that asked for that field name; it does NOT bleed into forms that
    # did not request it.
    for field_name, value in filled_values.items():
        for form_id in field_to_forms.get(field_name, []):
            per_form[form_id]["filled_values"][field_name] = value

    for field_name in raw_text_fields:
        for form_id in field_to_forms.get(field_name, []):
            per_form[form_id]["raw_text_fields"].add(field_name)

    for field_name, quote in all_question_grounding.items():
        for form_id in field_to_forms.get(field_name, []):
            per_form[form_id]["question_grounding"][field_name] = quote

    for form_id in per_form:
        per_form[form_id]["model_used"] = used_model

    return per_form


# Legal-entity indicator types in mutual-exclusion priority order. When a row
# has more than one entity-type box marked "Yes" (e.g. the LLM checked both
# Corporation and LLC), only the highest-priority surviving box is kept. LLC is
# first because the reported failure was exactly "Corporation AND LLC both
# checked" for a Limited Liability Company.
_LEGAL_ENTITY_INDICATOR_PRIORITY = (
    "LimitedLiabilityCorporationIndicator",
    "CorporationIndicator",
    "SubchapterSCorporationIndicator",
    "PartnershipIndicator",
    "JointVentureIndicator",
    "TrustIndicator",
    "NotForProfitIndicator",
    "IndividualIndicator",
    "OtherIndicator",
)

_ENTITY_BASE_RE = re.compile(r"^(.*LegalEntity_)(\w+Indicator)_([A-N])$")

# ── Post-fill guard helpers (Guards 3 & 4) ───────────────────────────────────
_CHECKBOX_VALID_VALUES = frozenset({
    "yes", "no", "y", "n", "true", "false", "1", "0", "on", "off", "x", "checked",
})

# Tokens that mark a field as PROSE-expecting — such fields are never treated as
# numeric/date even if a numeric hint also appears in the name (e.g.
# "AnyExposure...Explanation", "Hazard_Classification").
_PROSE_FIELD_TOKENS = (
    "Explanation", "Description", "Remark", "Comment", "Operations",
    "Classification", "Narrative", "FullName", "Address", "Name",
)
# Field-name hints that a value must be numeric / a code / a date — never prose.
# Deliberately tight: "Number" is excluded (policy numbers are alphanumeric).
_NUMERIC_DATE_FIELD_HINTS = (
    "_Amount", "Deductible", "Count", "Percent", "PostalCode", "ZipCode",
    "Hazard_Exposure", "YearBuilt", "ModelYear", "OwnershipPercent", "Date",
)


def _is_numeric_or_date_field(field: str) -> bool:
    if any(t in field for t in _PROSE_FIELD_TOKENS):
        return False
    return any(h in field for h in _NUMERIC_DATE_FIELD_HINTS)


def _looks_like_number_or_date(s: str) -> bool:
    """True when the string is only digits/punctuation/currency/space — a number,
    code, money or date carrying no prose words."""
    return bool(re.fullmatch(r"[\s\d.,/$%()\-:+#]+", s or ""))


# A live test surfaced a real gap-fill hallucination `_is_numeric_or_date_field`
# above deliberately does NOT catch: `CommercialProperty_Summary_
# BlanketNumberIdentifier` (tooltip "Enter number: The identifying number for
# the blanket.") came back filled with "Location 1"/"Location 2" - a real
# value, just the wrong ENTITY's label, not the blanket grouping number
# nothing in the document actually states. `_NUMERIC_DATE_FIELD_HINTS`
# deliberately excludes "Number" (policy numbers are legitimately
# alphanumeric, e.g. "POL-2026-004471"), so that name-based guard correctly
# leaves it alone - the gap is field-name-blind, so it's covered here instead
# via the field's own SCHEMA TOOLTIP, which is authoritative regardless of
# what the field happens to be named.
_TOOLTIP_NUMBER_PREFIX = "enter number:"


def _tooltip_declares_number(meta: Any) -> bool:
    tu = (meta.get("tu") or "") if isinstance(meta, dict) else ""
    return tu.strip().lower().startswith(_TOOLTIP_NUMBER_PREFIX)


def _looks_like_declared_number_value(s: str) -> bool:
    """A value acceptable for a tooltip-declared 'Enter number:' field. A real
    blanket/identifier number is short and has no multi-letter prose word in
    it (e.g. "1", "2", "B-1", "#12") - a location name, address, or any other
    entity label always contains a run of 4+ letters and is rejected."""
    return not re.search(r"[A-Za-z]{4,}", s or "")


# ── Tooltip-declared field types (Guard 3b) ──────────────────────────────────
# ACORD states the expected type of a field IN THE FIELD'S OWN TOOLTIP: "Enter
# code:", "Enter year:", "Enter identifier:", "Enter amount:", ... Measured across
# all 17 schemas: **3,888 of 5,852 fields (66%) declare a type this way.** Until
# now the code read exactly ONE of the twelve (`_tooltip_declares_number`, 607
# fields), so the other 3,281 had no type check at all.
#
# That gap is what let a real ACORD 127 run ship:
#     Driver_TaxIdentifier_A = "4S4BRCGC9C3217772"   (a VIN)
#     Driver_TaxIdentifier_I = "ERIN ROYAL"          (a person's name)
#     Driver_GenderCode_A    = "ERIN ROYAL"
#     Driver_LicensedYear_A  = "2012"                (the vehicle's model year)
# None of those fields is caught by `_is_numeric_or_date_field`: its hints list
# `YearBuilt`/`ModelYear` but not plain `Year`, and `_PROSE_FIELD_TOKENS` contains
# "Name", so `Driver_OtherGivenNameInitial_A` is classified as PROSE and a full
# first name passes straight through (improving-ll.md C22).
#
# DESIGN RULE, and the reason this is safe to run on every field: each check may
# only reject what CANNOT POSSIBLY be right for that declared type. It is not a
# format validator and must never become one. Insurance amount fields legitimately
# hold "Statutory", "Included", "Excluded"; code fields legitimately hold short
# words; identifier fields legitimately hold alphanumeric soup. So the checks key
# off two narrow, high-confidence shapes — a personal NAME and a VIN — plus a real
# range check for years. Anything unrecognised is left alone.
#
# Zero LLM cost, deterministic, and it cannot be argued with by a model.
_TOOLTIP_TYPE_RE = re.compile(r"^\s*enter\s+([a-z]+)\s*:", re.I)

# A VIN: exactly 17 chars, alphanumeric, no I/O/Q (excluded by the VIN standard
# precisely so they cannot be confused with 1/0), and mixing letters and digits.
_VIN_RE = re.compile(r"^[A-HJ-NPR-Z0-9]{17}$", re.I)
# 2-4 purely alphabetic words (hyphens/apostrophes allowed inside a word), each at
# least two letters. "ERIN ROYAL", "Mary-Jane O'Neill". Requires NO digits, so an
# alphanumeric identifier or a coded value can never match.
#
# UNICODE-AWARE ON PURPOSE. An ASCII `[A-Za-z]` class was tried first and an
# adversarial pass caught it: "JOSÉ GARCÍA" contains no ASCII-only word and so
# bypassed the check entirely, meaning a Hispanic driver's name would still land in
# a gender-code box. US commercial-lines submissions are full of accented names, so
# an ASCII-only name detector fails exactly the people it most needs to catch.
# `[^\W\d_]` is Python's unicode "letter" class: not a non-word char, not a digit,
# not an underscore.
# One name word: a unicode letter, then letters/apostrophes/hyphens. The
# apostrophe and hyphen must be ALTERNATED IN, not added to the negated class —
# `[^\W\d_'\-]` would EXCLUDE them and break "O'Neill" and "Mary-Jane", which a
# test caught immediately after the unicode change.
_NAME_WORD = r"[^\W\d_](?:[^\W\d_]|['\-])+"
_PERSON_NAME_RE = re.compile(
    r"^%s(?:\s+%s){1,3}$" % (_NAME_WORD, _NAME_WORD), re.UNICODE
)
# The shape above alone is NOT enough, and a self-test caught why: "See schedule"
# is two alphabetic words with no digits, so it matched — and it is a completely
# legitimate value in an ACORD limit box. Blanking it would be exactly the
# "deleted the broker's real data" failure this guard exists to avoid.
#
# A personal name never contains one of these words. Any value that does is not
# treated as a name, whatever its shape. Extend this list rather than loosening
# the regex, and prefer a missed catch over a false one.
_NOT_A_NAME_WORDS = frozenset({
    "see", "per", "not", "no", "none", "nil", "all", "any", "each", "and", "or",
    "of", "the", "to", "for", "as", "at", "by", "in", "on", "with", "if",
    "included", "excluded", "exclude", "include", "waived", "waiver", "statutory",
    "schedule", "scheduled", "policy", "coverage", "coverages", "covered",
    "limit", "limits", "form", "forms", "endorsement", "endorsements",
    "attached", "applicable", "above", "below", "same", "various", "refer",
    "declined", "rejected", "accepted", "pending", "unknown", "other",
    "blanket", "aggregate", "occurrence", "deductible", "premium", "amount",
    "annual", "total", "subject", "review", "quote", "bound", "renewal",
    "primary", "excess", "umbrella", "liability", "property", "auto", "insured",
})
_MONTH_WORDS = (
    "jan", "feb", "mar", "apr", "may", "jun",
    "jul", "aug", "sep", "oct", "nov", "dec",
)


def _tooltip_declared_type(meta: Any) -> Optional[str]:
    """The type ACORD declares in this field's tooltip, e.g. "code", "year"."""
    tu = (meta.get("tu") or "") if isinstance(meta, dict) else ""
    m = _TOOLTIP_TYPE_RE.match(tu)
    return m.group(1).lower() if m else None


def _looks_like_vin(s: str) -> bool:
    t = re.sub(r"[\s-]", "", s or "")
    if not _VIN_RE.match(t):
        return False
    return bool(re.search(r"\d", t)) and bool(re.search(r"[A-Za-z]", t))


def _looks_like_person_name(s: str) -> bool:
    t = (s or "").strip()
    if len(t) > 40 or re.search(r"\d", t):
        return False
    if not _PERSON_NAME_RE.match(t):
        return False
    # A single insurance/English function word disqualifies it. See
    # _NOT_A_NAME_WORDS for the self-test that made this necessary.
    return not any(
        w.strip("'-").lower() in _NOT_A_NAME_WORDS for w in t.split()
    )


def _is_vin_field(field: str) -> bool:
    """A field that legitimately holds a VIN, so the VIN check must not fire."""
    f = field.lower()
    return "vin" in f or "serial" in f or "identificationnumber" in f


def _rejects_declared_type(field: str, meta: Any, value: str) -> Optional[str]:
    """Reason string if `value` cannot possibly be valid for this field's
    ACORD-declared type; None to accept.

    Conservative by construction — see the block comment above. Returning None
    for an unrecognised type is deliberate: a missing check costs nothing, a
    wrong check blanks a broker's real data.
    """
    dtype = _tooltip_declared_type(meta)
    if not dtype:
        return None
    s = (value or "").strip()
    if not s:
        return None

    vin_ok = _is_vin_field(field)
    is_vin = (not vin_ok) and _looks_like_vin(s)
    is_name = _looks_like_person_name(s)

    if dtype == "year":
        # A year is a year. This is the one place a real format check is safe:
        # all 43 year-typed fields across the 17 schemas were checked by hand and
        # every one is a single-year field ("The year for which you are providing
        # information", "The original year in which a driver's license was
        # issued"). A YEAR RANGE is still accepted — a broker writing "2024-2025"
        # in PriorCoverage_PolicyYear is being reasonable, and blanking that would
        # be wrong-over-blank, which is just as bad as the reverse.
        t = re.sub(r"\s", "", s).strip(".")
        parts = re.split(r"[-/]", t)
        if not parts or len(parts) > 2 or not all(re.fullmatch(r"\d{2}|\d{4}", p) for p in parts):
            return f"declared 'year' but value is not a year or year range: {s[:40]!r}"
        for p in parts:
            if len(p) == 4 and not (1900 <= int(p) <= 2100):
                return f"declared 'year' but {p} is outside 1900-2100"
        return None

    if dtype == "number":
        # Pre-existing rule, kept verbatim so behaviour does not change for the
        # 607 fields it already covered.
        if not _looks_like_declared_number_value(s):
            return f"declared 'number' but value contains prose: {s[:40]!r}"
        return None

    if dtype == "rate":
        # ACORD declares "Enter rate:" on 8 fields across the 17 schemas and
        # this code never read one of them - the 13th declared type, missed
        # when C22 wired up the other twelve. Run 8's ACORD 127 put "LIAB-I"
        # (a COVERAGE code) in Vehicle_PrimaryLiabilityRatingFactor_A, whose
        # tooltip reads "the primary liability rating factor contains the
        # NUMBER which is used, along with the secondary rating factor...".
        #
        # FIRST CUT WAS WRONG AND THE CORPUS CAUGHT IT, which is the whole
        # point of keeping that corpus. "a rate with no digit is not a rate"
        # blanked "Included" on all 44 fields - and a broker writing "Included"
        # in a premises/operations rate box is a real convention, listed in
        # `_LEGIT_BY_TYPE["rate"]` since C22. Rates are NOT the exception to
        # C22's word-convention rule; I assumed they were.
        #
        # So the rule is the shape that actually separates the live defect from
        # the convention: an ABBREVIATED CODE, not an English word. Digitless,
        # longer than a 3-char abbreviation like "N/A", and joining uppercase
        # alphabetic runs with a slash or hyphen - "LIAB-I", "COMP/OTC". Words
        # ("Included", "Statutory", "Excluded", "Waived", "See schedule") have
        # no such joiner and are untouched.
        if not re.search(r"\d", s) and len(s) > 3 and \
                re.search(r"[A-Za-z]{2,}\s*[/-]\s*[A-Za-z]", s):
            return f"declared 'rate' but value is a coverage code: {s[:40]!r}"
        return None

    if dtype in ("code", "identifier"):
        if is_name:
            return f"declared '{dtype}' but value looks like a person's name: {s[:40]!r}"
        if is_vin:
            return f"declared '{dtype}' but value is a 17-character VIN: {s[:40]!r}"
        if dtype == "code" and len(s) > 64:
            return f"declared 'code' but value is {len(s)} chars of prose"
        return None

    if dtype == "date":
        if is_name:
            return f"declared 'date' but value looks like a person's name: {s[:40]!r}"
        if is_vin:
            return f"declared 'date' but value is a 17-character VIN: {s[:40]!r}"
        if not re.search(r"\d", s) and not any(w in s.lower() for w in _MONTH_WORDS):
            return f"declared 'date' but value has no digits and no month: {s[:40]!r}"
        return None

    if dtype in ("amount", "limit", "deductible", "percentage", "rate"):
        # Deliberately minimal. "Statutory", "Included", "Excluded", "Waived" and
        # "See schedule" are all REAL values in these boxes on real ACORD forms,
        # so requiring a digit here would blank correct data. Only a name or a VIN
        # is impossible.
        if is_name:
            return f"declared '{dtype}' but value looks like a person's name: {s[:40]!r}"
        if is_vin:
            return f"declared '{dtype}' but value is a 17-character VIN: {s[:40]!r}"
        return None

    # "text", "time", and anything else: no check.
    return None


# ── Guard 4 similarity helpers (paraphrased-boilerplate detection) ──────────
_BOILERPLATE_SIMILARITY_THRESHOLD = 0.75
_BOILERPLATE_MIN_SHARED_TOKENS = 4


def _sim_tokens(s: str) -> frozenset:
    """Lowercased word-tokens (len >= 3) used for near-duplicate comparison —
    order-insensitive, so a reworded/reordered sentence still matches."""
    return frozenset(t for t in re.findall(r"[a-z0-9]+", s.lower()) if len(t) >= 3)


def _is_near_duplicate_text(a: frozenset, b: frozenset) -> bool:
    """True when two token sets are similar enough to be the same boilerplate
    idea paraphrased, not merely two answers that happen to share a few common
    words. Requires both a minimum absolute token overlap and a high Jaccard
    ratio, so two short, topically-adjacent-but-distinct answers don't collide."""
    if len(a) < _BOILERPLATE_MIN_SHARED_TOKENS or len(b) < _BOILERPLATE_MIN_SHARED_TOKENS:
        return False
    inter = a & b
    if len(inter) < _BOILERPLATE_MIN_SHARED_TOKENS:
        return False
    union = a | b
    return (len(inter) / len(union)) >= _BOILERPLATE_SIMILARITY_THRESHOLD


_AFFIRMATIVE_VALUES = frozenset({"yes", "y", "true", "1", "on"})
_NEGATIVE_VALUES    = frozenset({"no", "n", "false", "0", "off"})

# Narrative answers that justify/explain a prior Yes/No or "Other" selection.
# "…Explanation" is the dominant ACORD naming convention (117 fields across the
# 17 schemas), but "…OtherDescription" ("Other" box checked -> please specify,
# 62 fields) and "…ResolutionDescription" (a compliance follow-up: foreclosure /
# lien / fire-code violation -> how was it resolved) are the same shape of
# field under a different suffix. Deliberately NOT "Description" alone - most
# Description fields (OperationsDescription, ItemDescription, AlarmDescription,
# ...) are core required content, not a Yes/No justification, and evidence-
# gating those would wrongly blank legitimate broker-needed data.
_EVIDENCE_REQUIRED_TOKENS = ("Explanation", "OtherDescription", "ResolutionDescription")

# Tokens recognized ONLY for PAIRING a Question-code field to its dependent
# detail field (_question_explanation_pairs below) - deliberately NOT added to
# _EVIDENCE_REQUIRED_TOKENS itself, which _is_evidence_required_field uses to
# decide Pass B eligibility for ANY field, paired or not (bare "Description"/
# "Cost" stays excluded there - most such fields, e.g. ItemDescription,
# AlarmDescription, OperationsDescription, are core content with no Yes/No
# tie at all, and evidence-gating those globally would wrongly blank
# legitimate data - see _EVIDENCE_REQUIRED_TOKENS's own note above). Scoped
# to PAIRING only, and only when the field genuinely sits immediately after
# an otherwise-unpaired Question-code (found in audit, live tests
# 2026-07-15/16: ACORD 186's hazardous-material-abatement question came back
# "Yes" with no gate at all on its dependent "...ExposureDescription" field,
# same bug class as ACORD 127's modified-equipment question).
_PAIRING_ONLY_TOKENS = ("Description", "CostAmount", "Cost")

# Confirmed-coincidental adjacencies to exclude, same rigor as the two
# Explanation-pairing exclusions documented in _question_explanation_pairs:
# audited by hand against the real question text, not assumed. ACORD 141's
# "is physical access to the computer room restricted?" has nothing to do
# with "the complete description of the property including merchandise and
# stock" - the two fields are simply adjacent in the schema by coincidence.
_PAIRING_EXCLUDED = frozenset({
    ("CrimeLineOfBusiness_Question_KBJCode_A", "CrimeInformation_PropertyDescription_A"),
})

# Matches the Yes/No "…Question_<code>Code_<row>" convention used for compliance
# questions across ACORD 125/126/127/130/131/141/160/186 (e.g.
# "WorkersCompensationLineOfBusiness_Question_ABFCode_A").
_QUESTION_CODE_RE = re.compile(r"_Question_[A-Za-z0-9]+Code_[A-N]$")

# The ACORD schema's own boilerplate for a Yes/No TEXT field that does NOT use
# the "_Question_<code>Code_" name convention at all - verified byte-identical
# on every "_Question_<code>Code_" field AND on plain Y/N fields that don't
# follow that naming (e.g. ACORD 140's CommercialProperty_Spoilage_YesNoCode_A /
# …RefrigeratorMaintenanceCode_A, ACORD 25's equivalents). This is the schema
# itself TELLING us the field is Yes/No, independent of what it's named.
_YES_NO_TOOLTIP_PREFIX = "Enter Y for a “Yes” response."


def _is_yes_no_field(field: str, schema: dict) -> bool:
    """True when `field` is structurally a Yes/No answer - covering every ACORD
    naming convention for one across all 17 forms, not just the compliance
    "_Question_<code>Code_" family (client requirement: "in all the forms...
    certain fields where Y/N/Yes/No to be filled"). Three independent,
    schema-driven signals - any one is sufficient:
      1. The "_Question_<code>Code_<row>" name pattern (compliance questions).
      2. ft == "/Btn" - a checkbox is structurally boolean by PDF form design,
         whatever it's named: coverage accept/reject (sink hole, mine
         subsidence), building features, LOB selection, entity type, auto
         ownership/HNOA, ...
      3. The field's own tooltip carries the ACORD "Enter Y for a Yes
         response..." boilerplate - the same Yes/No convention on a plain
         /Tx field that uses neither of the above.
    Deliberately structural (field type / tooltip metadata already in the
    schema), never a guess from the field's semantic name - matching the
    project's standing rule against topic/keyword-overlap heuristics (see
    _question_explanation_pairs and the evidence-gate design notes).
    """
    if _QUESTION_CODE_RE.search(field):
        return True
    meta = schema.get(field)
    if not isinstance(meta, dict):
        return False
    if meta.get("ft") == "/Btn":
        return True
    tu = meta.get("tu")
    return bool(tu) and str(tu).startswith(_YES_NO_TOOLTIP_PREFIX)


def _is_high_impact_checkbox_field(field: str, tooltip: Optional[str], ft: Optional[str]) -> bool:
    """True for a checkbox (``/Btn``) field that is high-impact (Figure 33: auto
    ownership / HNOA / leasing / hazardous-materials / maintenance) but does NOT
    already follow the ``_Question_<code>Code_`` naming convention the evidence
    gate recognizes by field name alone.

    Found in audit: ACORD 137_CA/137_CO/138_CA/138_CO express their HNOA-
    equivalent question as a checkbox pair (``Vehicle_HiredBorrowed_YesIndicator_A``
    / ``_NoIndicator_A``, ``Vehicle_TruckersHiredBorrowed_*``) or an opaque numeric
    symbol box (``Vehicle_GarageAndDealersSymbol_TwentyEightIndicator_A`` = hired
    auto). None of these match ``_QUESTION_CODE_RE``, so — before this — a
    hallucinated "Yes" on one of them was never blanked by the evidence gate,
    only soft-flagged for review via ``is_high_impact_field`` + low_confidence.
    That is weaker than the "never inferred loosely" the client asked for.

    SHARED by the gap-fill prompt builder (``_fill_unmatched_with_gpt``, which
    marks the field so the model must cite a grounding quote) and
    ``map_facts_to_form``'s evidence gate (which enforces it) so the two can
    never silently drift apart — same pattern as ``is_value_contaminated`` /
    ``detect_field_mapping_contamination`` sharing ``_classify_value``.
    """
    if "/Btn" not in (ft or ""):
        return False
    if _QUESTION_CODE_RE.search(field or ""):
        return False  # already covered by the name-shape rule
    try:
        from services.field_mapping_integrity import is_high_impact_field
    except Exception:                              # noqa: BLE001
        return False
    return is_high_impact_field(field, tooltip)


_DISCLOSURE_QUESTION_MARKER = "response to the question,"


def is_compliance_question(field: str, meta: Any) -> bool:
    """True if `field` is a Yes/No underwriting question for the dedicated
    compliance pass. Module-level and pure, so both levels of batching classify a
    field identically.

    Three field shapes route here — deliberately NOT every /Btn checkbox:
      1. Tooltip begins with the ACORD "Enter Y for a Yes response…" convention
         (Question-code TEXT fields + …YesNoCode_ fields on ACORD 140/25).
      2. Tooltip contains "response to the question," — the CHECKBOX-PAIR form of
         the same convention, used on 125/126/127/130/131/133/141/160/186. ACORD
         133 has ZERO shape-1 fields and 38 shape-2 ones, which reached the
         general fill unprotected until this was added.
      3. A genuine disclosure checkbox missing that wording
         (`_is_high_impact_checkbox_field` — hired/non-owned auto, leasing,
         hazardous materials, maintenance program on 137/138).

    Generic /Btn coverage-SELECTION checkboxes ("which auto symbol applies") are
    excluded on purpose: on ACORD 137_CA only 46 of 192 /Btn fields reaching
    gap-fill are real disclosure questions, so routing all of them would waste
    ~14 calls per form and dilute this pass's focus.
    """
    info = meta if isinstance(meta, dict) else {}
    tu = info.get("tu")
    tu_str = str(tu or "")
    if tu_str.startswith(_YES_NO_TOOLTIP_PREFIX):
        return True
    if _DISCLOSURE_QUESTION_MARKER in tu_str:
        return True
    return _is_high_impact_checkbox_field(field, tu, info.get("ft"))


def _is_evidence_required_field(field: str) -> bool:
    """Narrative answers to Yes/No application questions (the "…Explanation" /
    "…OtherDescription" / "…ResolutionDescription" fields — e.g. ACORD 126
    claims-made / employee-benefits sections). Under ENABLE_EVIDENCE_GATED_FILL
    these are stamped only when the gap-fill LLM copied them from the document,
    never when inferred (client Figure 30)."""
    return any(token in field for token in _EVIDENCE_REQUIRED_TOKENS)


def _question_explanation_pairs(schema: dict) -> Dict[str, str]:
    """Map each Yes/No field to its own paired "…Explanation"/"…OtherDescription"/
    "…ResolutionDescription" field, using the ACORD layout convention that the
    question immediately precedes its own explanation in the form (and
    therefore in the schema, whose key order mirrors the source PDF). A pair
    is accepted ONLY when the very next schema field actually contains one of
    those tokens - never inferred from position alone - so an unrelated
    neighboring field (another question, a table header, a producer-
    identifier column) is never mistaken for this answer's justification.
    Confirmed against ACORD_130/127/160: most Question codes pair this way;
    the ones that don't (no adjacent Explanation) are simply excluded, which
    is the safe default.

    Eligible LEFT-side fields are "_Question_<code>Code_" text fields OR any
    /Btn checkbox (audited across all 17 schemas: this is exactly the shape of
    the extremely common "…OtherIndicator_<row>" checkbox -> "…OtherDescription
    _<row>" text pair - "Other" is checked, please specify - present on 10+
    forms and previously invisible to this function entirely). Deliberately
    NOT the broader _is_yes_no_field tooltip-convention signal here: auditing
    all 17 schemas found two cases where a plain Y/N /Tx field happens to sit
    directly before an unrelated Explanation field from a different section
    (ACORD 126 PropertyItem_ItemDetail_InstructionGivenCode_A ->
    ...MachineryOrEquipmentLoanedRentedOthersExplanation_B; ACORD 141
    BuildingProtection_DoubleCylinderDoorLockCode_A -> CrimeInformation_
    OtherDescription_A) - real coincidental adjacency, not a real pair. A
    checkbox's own PDF layout position is a stronger structural signal than an
    arbitrarily-ordered Y/N text field, so pairing trusts /Btn but not the
    tooltip-only signal; _is_yes_no_field is still used for gating the
    checkbox/text field's OWN answer regardless of whether it pairs.

    FALLBACK (found in audit, live tests 2026-07-15/16): when a Question-code
    field has NO adjacent Explanation-shaped field, it may still have a
    genuine dependent detail field immediately next, just named
    "...Description"/"...Cost"/"...CostAmount" instead (_PAIRING_ONLY_TOKENS -
    e.g. ACORD 186's hazardous-material-abatement question ->
    "...ExposureDescription"; ACORD 141's "is a physical inventory made?" ->
    "...FrequencyDescription"). Scoped to Question-code left fields only (not
    /Btn - no evidence yet that checkboxes need this fallback) and to STRICT
    immediate adjacency, same as the primary check - auditing every real
    occurrence across all 17 schemas at this fallback found 6 genuine matches
    and 1 confirmed coincidental adjacency (_PAIRING_EXCLUDED), same rigor as
    the two exclusions above."""
    keys = list(schema.keys())
    pairs: Dict[str, str] = {}
    for i, k in enumerate(keys):
        if i + 1 >= len(keys):
            continue
        nxt = keys[i + 1]
        meta = schema.get(k)
        is_pairable = _QUESTION_CODE_RE.search(k) or (isinstance(meta, dict) and meta.get("ft") == "/Btn")
        if not is_pairable:
            continue
        if any(t in nxt for t in _EVIDENCE_REQUIRED_TOKENS):
            pairs[k] = nxt
        elif (_QUESTION_CODE_RE.search(k)
              and any(re.search(rf"{t}(_[A-Z]{{1,2}})?$", nxt) for t in _PAIRING_ONLY_TOKENS)
              and (k, nxt) not in _PAIRING_EXCLUDED):
            pairs[k] = nxt

    # THIRD fallback: the question's own DEPENDENT BLOCK (see
    # _question_dependent_block). Strict adjacency misses ACORD 125's Questions
    # 8, 9 and 10 by ONE position - an OccurrenceDate box sits between the
    # question and its Explanation - so those three were permanently unpaired and
    # Guard 5 never blanked their boilerplate. The client reported all three.
    for q, deps in _question_dependent_block(schema).items():
        if q in pairs:
            continue
        exp = next(
            (f for f in deps if any(t in f for t in _EVIDENCE_REQUIRED_TOKENS)), None
        )
        if exp:
            pairs[q] = exp
    return pairs


@lru_cache(maxsize=32)
def _dependent_block_for(schema_keys: Tuple[str, ...]) -> Dict[str, Tuple[str, ...]]:
    """{question_field: (dependent_field, ...)} from consecutive same-stem runs.

    ACORD lays a compliance question out followed by a contiguous block of its
    own detail boxes, and every box in that block shares one name stem:

        CommercialPolicy_Question_KALCode_A            <- the question
        CommercialPolicy_JudgementOrLien_OccurrenceDate_A
        CommercialPolicy_JudgementOrLienExplanation_A
        CommercialPolicy_JudgementOrLien_ResolutionDescription_A
        CommercialPolicy_JudgementOrLien_ResolutionDate_A

    Requiring TWO OR MORE consecutive fields to share a stem is what makes this
    safe. Single-field adjacency has real coincidences (this module documents
    two, in `_PAIRING_EXCLUDED`); several consecutive unrelated fields sharing
    one stem does not happen. Measured across all 17 schemas: exactly THREE
    questions qualify, all on ACORD 125, and all three are client-reported
    defects - Q8 uncorrected fire code, Q9 bankruptcy, Q10 judgment or lien.

    ACORD's own naming is inconsistent about the separator
    (`JudgementOrLien_OccurrenceDate` but `JudgementOrLienExplanation`), so the
    suffix is stripped with or without it. An earlier version missed all three
    for exactly that reason and produced two unrelated pairs instead.
    """
    block: Dict[str, Tuple[str, ...]] = {}
    keys = list(schema_keys)
    for i, k in enumerate(keys):
        if not _QUESTION_CODE_RE.search(k):
            continue
        run: List[str] = []
        stem0: Optional[str] = None
        for j in range(i + 1, min(i + 1 + _DEPENDENT_BLOCK_MAX, len(keys))):
            stem = _dependent_stem(keys[j])
            if not stem:
                break
            if stem0 is None:
                stem0 = stem
            elif stem != stem0:
                break
            run.append(keys[j])
        if len(run) >= 2:
            block[k] = tuple(run)
    return block


def _question_dependent_block(schema: dict) -> Dict[str, Tuple[str, ...]]:
    return _dependent_block_for(tuple(schema.keys()))


# How far after a question a dependent block may reach. ACORD's longest real
# block is 4 boxes (occurrence date, explanation, resolution description,
# resolution date) x rows; 6 covers it without letting a run wander into the
# next section.
_DEPENDENT_BLOCK_MAX = 6
_DEPENDENT_SUFFIXES = (
    "ResolutionDescription", "OtherDescription", "Explanation",
    "OccurrenceDate", "ResolutionDate", "Description",
)


def _dependent_stem(field: str) -> str:
    """A field's name with its row letter and dependent-role suffix removed, so
    every box in one question's block reduces to the same string."""
    base = re.sub(r"_[A-N]$", "", field)
    for suffix in _DEPENDENT_SUFFIXES:
        if base.endswith("_" + suffix):
            return base[: -len(suffix) - 1].rstrip("_")
        if base.endswith(suffix):
            return base[: -len(suffix)].rstrip("_")
    return ""            # not a dependent-shaped field - ends the run


# ── Non-adjacent companion fields (Figure 33 audit finding, live test 2026-07-15) ─
# ACORD 127's vehicle-ownership question is "explained" not by a single adjacent
# free-text field (the _question_explanation_pairs convention above) but by the
# "Name of Other Owner" schedule (AdditionalInterest_FullName_C/_D - see
# repeating_group_key's own note on why these are a SEPARATE role from _A/_B's
# lienholder schedule). A Vehicle_ProducerIdentifier_AA field sits between the
# question and the first owner-name slot in the real schema, so the adjacency
# check above never finds it - the question was permanently treated as
# "unpaired" (no Explanation field at all), relying solely on its own
# grounding quote even when the owner-name box was independently, correctly
# filled with a real name. Explicit and narrow by design (same pattern as
# _INDICATOR_RULES / _FIELD_SPEC_CLARIFICATIONS elsewhere in this file) rather
# than a generalized non-adjacent-pairing mechanism, since this specific
# mismatch was checked by hand against the real schema, not inferred.
_NONADJACENT_QUESTION_COMPANIONS: Dict[str, tuple] = {
    "CommercialVehicleLineOfBusiness_Question_AAJCode_A": (
        "AdditionalInterest_FullName_C", "AdditionalInterest_FullName_D",
    ),
}


# ── Non-adjacent DEPENDENT fields (Figure 33 audit finding, live test 2026-07-15) ─
# The inverse relationship from _NONADJACENT_QUESTION_COMPANIONS above: ACORD
# 127's "any car modified / special equipment?" question (AAGCode) has its own
# per-vehicle DESCRIPTION/COST sub-fields (Vehicle_Question_
# ModifiedEquipmentDescription_A/_B, ...CostAmount_A/_B) - plain free-text
# fields with no "Explanation"/"OtherDescription" suffix, so they are neither
# gated by the evidence gate nor covered by Guard 5's adjacent-Explanation
# check (_enforce_post_fill_guards). Found in audit: the gap-fill LLM filled
# DESCRIPTION with a sentence lifted from a DIFFERENT vehicle's ownership note
# even though the question itself correctly stayed blank/ungrounded - these
# dependent fields must never carry a value when their own parent question
# isn't a genuine "Yes" (enforced by Guard 6).
_NONADJACENT_DEPENDENT_FIELDS: Dict[str, tuple] = {
    "CommercialVehicleLineOfBusiness_Question_AAGCode_A": (
        "Vehicle_Question_ModifiedEquipmentDescription_A", "Vehicle_Question_ModifiedEquipmentCostAmount_A",
        "Vehicle_Question_ModifiedEquipmentDescription_B", "Vehicle_Question_ModifiedEquipmentCostAmount_B",
    ),
    # ── ACORD 125 Question 5: prior declined / cancelled / non-renewed ───────
    # The REASON boxes and their two narratives are meaningless unless the
    # question itself is a genuine "Yes" - they answer "why", and there is no
    # "why" until there is a "that happened".
    #
    # Reported twice on the client's live runs, with DIFFERENT boilerplate each
    # time, which is why this is anchored structurally instead of by wording:
    #   2026-08-08  NON-PAYMENT ticked, narrative "The description of how the
    #               underwriting condition that caused the policy not to be
    #               written..."  - ACORD's own field instructions, echoed back.
    #   2026-08-12  NON-RENEWAL ticked, narrative "The policyholder is a member
    #               of the Company and shall participate in the distribution of
    #               dividends..." - mutual-insurer membership language.
    # Neither says anything about THIS applicant's history. The second slipped
    # every existing guard: verified `_is_policy_contract_language` returns
    # False on it, and chasing a third phrasing would be the third patch of a
    # whack-a-mole (see the Data Consistency entry in CLAUDE.md for how that
    # ends).
    #
    # The client's instruction was exactly this rule: "Do not select
    # Non-payment, Non-renewal, Underwriting or another reason. Ask the client
    # for the Yes/No response. Only complete 'Condition corrected' when the
    # client reports an actual event."
    "CommercialPolicy_Question_AACCode_A": (
        "CancelNonRenew_NonPaymentIndicator_A",
        "CancelNonRenew_NonRenewalIndicator_A",
        "CancelNonRenew_UnderwritingIndicator_A",
        "CancelNonRenew_AgentNoLongerWritesForInsurerIndicator_A",
        "CancelNonRenew_OtherIndicator_A",
        "CancelNonRenew_OtherDescription_A",
        "CancelNonRenew_UnderwritingConditionCorrectedIndicator_A",
        "CancelNonRenew_UnderwritingConditionCorrectedDescription_A",
    ),
}


# ── ACORD 101 overflow routing (Figure 29) ───────────────────────────────────
# A single ACORD /Tx field holds far less than a full operations/classification
# narrative. When such text exceeds this budget it is routed IN FULL to the
# ACORD 101 "Additional Remarks" section — losslessly (the originating form's
# field is never truncated). Gated by ENABLE_ACORD101_OVERFLOW.
_OVERFLOW_CHAR_THRESHOLD = 300
_ACORD101_REMARK_ROWS = ("A", "B", "C", "D", "E", "F")


def _compose_acord101_remarks(facts: dict) -> List[str]:
    """Ordered, de-duplicated remark blocks destined for ACORD 101."""
    blocks: List[str] = []
    # 1. Explicit remarks fact (conflict explanations, client answers via ARQ).
    for key in ("acord101_remarks", "additional_remarks_text"):
        v = _fv(facts, key)
        if not v:
            continue
        if isinstance(v, list):
            blocks.extend(str(x).strip() for x in v if str(x).strip())
        elif str(v).strip():
            blocks.append(str(v).strip())
    # 2. Oversized operations narrative that will not fit its form field.
    ops = _fv(facts, "operations_description")
    if ops and len(str(ops).strip()) > _OVERFLOW_CHAR_THRESHOLD:
        blocks.append("Operations (continued): " + str(ops).strip())
    seen: set = set()
    out: List[str] = []
    for b in blocks:
        k = b.lower()
        if k and k not in seen:
            seen.add(k)
            out.append(b)
    return out


def _apply_acord101_overflow(mapped: dict, schema: dict, facts: dict,
                             deterministic_filled: set) -> None:
    """Stamp ACORD 101 RemarkText rows from the composed remark blocks. Remarks
    are authoritative for ACORD 101, so this overrides any gap-fill guess. Any
    surplus beyond the last available row is concatenated into it (never dropped)."""
    blocks = _compose_acord101_remarks(facts)
    if not blocks:
        return
    rows = [
        f"AdditionalRemark_RemarkText_{r}"
        for r in _ACORD101_REMARK_ROWS
        if f"AdditionalRemark_RemarkText_{r}" in schema
    ]
    if not rows:
        return
    if len(blocks) > len(rows):
        values = blocks[: len(rows) - 1] + ["\n\n".join(blocks[len(rows) - 1:])]
    else:
        values = blocks
    for field, text in zip(rows, values):
        mapped[field] = text
        deterministic_filled.add(field)
    logger.info("acord101_overflow: filled %d remark row(s) from %d block(s)",
                len(values), len(blocks))


def _enforce_post_fill_guards(mapped: dict, schema: dict, facts: dict,
                              gpt_filled_set: Optional[set] = None) -> None:
    """Deterministic safety nets applied to `mapped` in place AFTER all fill
    passes (Pass 1, alias, GPT). These do NOT depend on how a value was filled,
    so they catch LLM mistakes the prompt could not guarantee against.

    Guard 1 - Legal-entity mutual exclusion: an entity is exactly one legal
              type. If multiple LegalEntity_*Indicator boxes in the same row
              are "Yes", keep only the highest-priority one and blank the rest.

    Guard 2 - Repeating-row de-duplication: non-schedule repeating rows
              (NamedInsured_FullName_B, premises rows, etc.) must not echo the
              row-A value. Schedule / GL-hazard / subject-of-insurance fields
              are exempt - two vehicles can share a model year, and two
              different locations can both have a "Building" subject at
              genuinely different dollar amounts. Only collapses an exact
              duplicate of row A.

    Guard 3 - Wrong-type value rejection: prose dropped into a checkbox or a
              numeric/date cell (e.g. a contractor description in a per-claim
              deductible box) is always wrong — blank it (Figure 30).

    Guard 4 - Cross-field boilerplate bleed: the same generic sentence pasted
              into 3+ unrelated field families is boilerplate, not data. Keep
              only the field(s) whose own deterministic rule produces that value
              and blank the rest (Figure 30).

    Guard 5 - Explanation without a "Yes": every ACORD Question/Explanation
              pair's own field text reads "an explanation IF [X]" - the
              explanation only applies when the paired question is Yes. A
              filled Explanation whose paired Question is anything else (No,
              or any other non-affirmative answer) is answering a question
              that was never asked - blank it. This is a structural check,
              independent of ENABLE_EVIDENCE_GATED_FILL: even a verbatim,
              document-grounded sentence is wrong here if it's attached to a
              "No".

    Guard 6 - Non-adjacent dependent field without a "Yes": the same
              invariant as Guard 5, for a dependent field the adjacency-based
              pairing can't find (see _NONADJACENT_DEPENDENT_FIELDS - e.g. a
              plain "...Description"/"...CostAmount" sub-field, not
              "...Explanation"-suffixed). Also fires on a BLANK question, not
              just an explicit "No".
    """
    # ── Guard 1: legal-entity mutual exclusion ───────────────────────────────
    # Group entity indicator fields present in this schema by their row letter.
    rows: Dict[str, Dict[str, str]] = {}
    for field in schema:
        m = _ENTITY_BASE_RE.match(field)
        if not m:
            continue
        _prefix, indicator_type, row = m.group(1), m.group(2), m.group(3)
        if indicator_type in _LEGAL_ENTITY_INDICATOR_PRIORITY:
            rows.setdefault(row, {})[indicator_type] = field

    # Derive the ground-truth entity type from extracted facts once so each row
    # can prefer the box that matches the fact over the hardcoded priority order.
    _raw_entity = str(_fv(facts, "entity_type") or "").lower()
    _fact_entity_indicator: Optional[str] = None
    if _raw_entity:
        for _llc_phrase in ("limited liability corporation", "limited liability company",
                            "limited liability corp", "llc corp", "llc corporation", "llc"):
            if _llc_phrase in _raw_entity:
                _fact_entity_indicator = "LimitedLiabilityCorporationIndicator"
                break
        if _fact_entity_indicator is None:
            for _ind, _phrases in (
                ("SubchapterSCorporationIndicator", ("s-corp", "s corp", "subchapter s")),
                ("CorporationIndicator",            ("corporation", "corp", "inc", "incorporated")),
                ("PartnershipIndicator",            ("partnership", "llp", "lp")),
                ("JointVentureIndicator",           ("joint venture",)),
                ("TrustIndicator",                  ("trust",)),
                ("NotForProfitIndicator",           ("non-profit", "nonprofit", "not for profit", "not-for-profit")),
                ("IndividualIndicator",             ("individual", "sole prop")),
            ):
                if any(p in _raw_entity for p in _phrases):
                    _fact_entity_indicator = _ind
                    break

    for row, type_to_field in rows.items():
        marked = [
            t for t, f in type_to_field.items()
            if str(mapped.get(f) or "").strip().lower() in ("yes", "true", "1")
        ]
        if len(marked) <= 1:
            continue
        # Multiple boxes checked → prefer the one matching the extracted entity_type
        # fact (ground truth); fall back to hardcoded priority order when no fact.
        if _fact_entity_indicator and _fact_entity_indicator in marked:
            keep = _fact_entity_indicator
        else:
            keep = next(
                (t for t in _LEGAL_ENTITY_INDICATOR_PRIORITY if t in marked),
                marked[0],
            )
        for t in marked:
            if t != keep:
                mapped[type_to_field[t]] = "No"
        logger.info(
            "post_fill_guard entity_exclusion row=%s kept=%s blanked=%s",
            row, keep, [t for t in marked if t != keep],
        )

    # ── Guard 2: repeating-row de-duplication ────────────────────────────────
    for field in schema:
        m = _SCHED_ROW_RE.match(field)
        if not m:
            continue
        base, letter = m.group(1), m.group(2)
        if _ROW_LETTER_TO_IDX[letter] < 1:
            continue  # row A is the canonical row — never blanked
        if _is_schedule_field(field) or _GL_HAZARD_ROW_RE.match(field) or _SUBJECT_OF_INSURANCE_CODE_ONLY_RE.match(field):
            continue  # schedule / GL hazard / subject-of-insurance CODE rows may legitimately repeat values
            # (LimitAmount is deliberately NOT exempted here - see _SUBJECT_OF_INSURANCE_CODE_ONLY_RE above)
        # Checkbox/indicator rows legitimately share Yes/No across distinct entities
        # (two LLCs both have LLC=Yes; two locations can both be "inside city limits").
        # De-duplication must only collapse free-text VALUE rows (names, addresses).
        val = mapped.get(field)
        if val is None:
            continue
        if "Indicator" in field or str(val).strip().lower() in ("yes", "no", "true", "false"):
            continue
        # A LimitAmount genuinely GROUNDED in a real per-location fact
        # (_resolve_subject_of_insurance_row, backed by property_locations) is
        # trustworthy even if it coincidentally equals row A's amount - two
        # real, distinct locations CAN legitimately share the exact same
        # building value. Only an UNGROUNDED value (gap-filled guess, no
        # property_locations backing) gets the stricter duplicate check below;
        # this is what a live test's genuine 2nd-location duplication slipped
        # through as, and what a dedicated regression test (test_location_
        # consolidation.py) confirms must NOT be blanked for the grounded case.
        if _SUBJECT_OF_INSURANCE_RE.match(field):
            soi = _resolve_subject_of_insurance_row(field, facts)
            if isinstance(soi, str) and soi.strip() == str(val).strip():
                continue
        row_a = f"{base}_A"
        a_val = mapped.get(row_a)
        if a_val is not None and str(val).strip() and str(val).strip() == str(a_val).strip():
            mapped[field] = None
            logger.info("post_fill_guard row_dedup blanked=%s (== %s)", field, row_a)

    # ── Guard 3: wrong-type value rejection ──────────────────────────────────
    # An LLM sometimes drops a prose description into a field that structurally
    # cannot hold prose (a checkbox, or a numeric/date cell) — e.g. the reported
    # "COMMERCIAL GENERAL CONTRACTOR" landing in a per-claim DEDUCTIBLE box
    # (Figure 30). These are always wrong, so blank them deterministically.
    for field, val in list(mapped.items()):
        if val is None or not isinstance(val, str):
            continue
        s = val.strip()
        if not s:
            continue
        meta = schema.get(field) or {}
        is_checkbox = isinstance(meta, dict) and meta.get("ft") == "/Btn"
        prose_like = bool(re.search(r"[A-Za-z]{3,}\s+[A-Za-z]{3,}", s))
        if is_checkbox and s.lower() not in _CHECKBOX_VALID_VALUES:
            mapped[field] = None
            logger.info("post_fill_guard type_reject blanked=%s (checkbox got %r)", field, s[:40])
        elif prose_like and _is_numeric_or_date_field(field):
            mapped[field] = None
            logger.info("post_fill_guard type_reject blanked=%s (numeric/date got prose %r)", field, s[:40])
        else:
            # ── Guard 3b: ACORD's own declared type ──────────────────────────
            # Field-name-based hints (_is_numeric_or_date_field) deliberately
            # exclude "Number" (policy numbers are legitimately alphanumeric).
            # This catches the same class of error via the field's own SCHEMA
            # TOOLTIP, which is authoritative regardless of naming — and covers
            # all twelve declared types, not just "Enter number:" (C22). See
            # `_rejects_declared_type` for why it only ever rejects a personal
            # name, a VIN, or an out-of-range year.
            _reason = _rejects_declared_type(field, meta, s)
            if _reason:
                mapped[field] = None
                logger.warning(
                    "post_fill_guard type_reject blanked=%s — %s", field, _reason,
                )

    # ── Guard 4: cross-field boilerplate bleed ───────────────────────────────
    # The same generic sentence pasted into several UNRELATED fields is boilerplate
    # bleed, not real data (Figure 30). Group non-trivial free-text values; when one
    # value spans 2+ distinct field families ("multiple unrelated fields" per the
    # requirement), keep only the field(s) whose own deterministic rule legitimately
    # produces that value (e.g. the real operations description field) and blank
    # the rest.
    #
    # Grouping is exact-match FIRST (identical strings always cluster, regardless
    # of length) and near-duplicate SECOND: the more common LLM failure mode is
    # not verbatim copy-paste but the same idea paraphrased into several fields, so
    # values are also clustered by token-Jaccard similarity against the first
    # member of each cluster. A cluster's representative tokens are fixed at its
    # first member deliberately — cheap, and sufficient to catch the paraphrase-
    # bleed pattern without O(n^2) pairwise recomputation.
    candidates: List[Tuple[str, str]] = []
    for field, val in mapped.items():
        if not isinstance(val, str):
            continue
        s = val.strip()
        if len(s) < 20 or " " not in s or _looks_like_number_or_date(s):
            continue
        candidates.append((field, s))

    clusters: List[List[Tuple[str, str]]] = []
    cluster_tokens: List[frozenset] = []
    for field, s in candidates:
        s_l = s.lower()
        toks = _sim_tokens(s)
        for ci, rep_tokens in enumerate(cluster_tokens):
            if s_l == clusters[ci][0][1].lower() or _is_near_duplicate_text(toks, rep_tokens):
                clusters[ci].append((field, s))
                break
        else:
            clusters.append([(field, s)])
            cluster_tokens.append(toks)

    # An explanation currently paired to a kept (affirmative) Question-code
    # answer already went through the evidence gate's own grounding check
    # (Figure 30 Pass A - see map_facts_to_form) — it is a CONFIRMED answer,
    # not a guess. Without this exemption, Guard 4 silently undoes that
    # verification whenever the model reused the same real citation as its
    # (wrong) grounding for OTHER unrelated Yes/No questions in the same
    # batch: every field sharing that text gets blanked here, INCLUDING the
    # one it was actually true for, which reintroduces a bare "Yes" with no
    # explanation - exactly the failure Pass A exists to prevent. Found via
    # live test 2026-07-13 (MVR question kept "Y", explanation wiped).
    _exp_to_kept_q = {exp: q for q, exp in _question_explanation_pairs(schema).items()}

    for cluster in clusters:
        fields = [f for f, _ in cluster]
        families = {
            (_SCHED_ROW_RE.match(f).group(1) if _SCHED_ROW_RE.match(f) else f)
            for f in fields
        }
        if len(families) < 2:
            continue  # not a broad enough spread to be confident it's bleed
        for f, s in cluster:
            det = _deterministic_map(f, facts)
            legit_owner = isinstance(det, str) and det.strip().lower() == s.lower()
            paired_q = _exp_to_kept_q.get(f)
            is_confirmed_yes_explanation = (
                paired_q is not None
                and str(mapped.get(paired_q) or "").strip().lower() in _AFFIRMATIVE_VALUES
            )
            if not legit_owner and not is_confirmed_yes_explanation:
                mapped[f] = None
                logger.info("post_fill_guard boilerplate_bleed blanked=%s", f)

    # ── Guard 5: explanation without a "Yes" ──────────────────────────────────
    for q_field, exp_field in _question_explanation_pairs(schema).items():
        exp_val = mapped.get(exp_field)
        if not (isinstance(exp_val, str) and exp_val.strip()):
            continue
        q_val = str(mapped.get(q_field) or "").strip().lower()
        if q_val and q_val not in _AFFIRMATIVE_VALUES:
            mapped[exp_field] = None
            logger.info(
                "post_fill_guard explanation_without_yes blanked=%s (question=%s answer=%r)",
                exp_field, q_field, q_val,
            )

    # ── Guard 6: non-adjacent dependent field without a "Yes" ─────────────────
    # See _NONADJACENT_DEPENDENT_FIELDS - the same "no Yes, no supporting
    # content" invariant as Guard 5, for dependent fields the adjacency-based
    # _question_explanation_pairs can't find (a plain "...Description"/
    # "...CostAmount" field, not "...Explanation"-suffixed). Unlike Guard 5,
    # this also fires when the question is BLANK (not just an explicit "No") -
    # a dependent description/cost has no legitimate standalone meaning
    # without its own parent question being a genuine "Yes".
    # The hand-listed pairs PLUS every question's derived dependent block. The
    # derived half is what covers ACORD 125's Questions 8, 9 and 10, whose
    # occurrence dates, explanations and resolution boxes were all unreachable
    # from either guard because the Explanation sits one position too far away.
    # The client reported every one of them: "Delete the fire-code occurrence
    # date", "Delete both bankruptcy boilerplate explanations", "Delete
    # 'judgment or lien'".
    _dependents: Dict[str, tuple] = dict(_NONADJACENT_DEPENDENT_FIELDS)
    for _q, _deps in _question_dependent_block(schema).items():
        _dependents[_q] = tuple(_dependents.get(_q, ())) + tuple(_deps)

    for q_field, dep_fields in _dependents.items():
        if q_field not in schema:
            continue
        q_val = str(mapped.get(q_field) or "").strip().lower()
        if q_val in _AFFIRMATIVE_VALUES:
            continue
        for dep_field in dep_fields:
            if mapped.get(dep_field) is not None:
                mapped[dep_field] = None
                logger.info(
                    "post_fill_guard dependent_without_yes blanked=%s (question=%s answer=%r)",
                    dep_field, q_field, q_val,
                )

    # ── Guard 11: a repeating row that is row A reformatted ──────────────────
    # Guard 2 collapses an EXACT duplicate of row A. The live form showed a
    # second premises row reading "4800 Dahlia St D13 Denver CO. 80216-3121"
    # against a row A of "4800 Dahlia St # D13" - the same location rewritten
    # with the city and ZIP folded in, so exact matching missed it entirely.
    #
    # Compared on alphanumerics with row A's value required to be CONTAINED in
    # the later row, and only for address lines of 10+ characters. A genuinely
    # different location does not contain the first one's full street line.
    _addr_row_a: Dict[str, str] = {}
    for field, val in list(mapped.items()):
        m_row = _SCHED_ROW_RE.match(field)
        if not m_row or "Address_LineOne" not in field:
            continue
        base, row = m_row.group(1), m_row.group(2)
        key = re.sub(r"[^a-z0-9]", "", str(val or "").lower())
        if row == "A":
            if len(key) >= 10:
                _addr_row_a[base] = key
            continue
        row_a_key = _addr_row_a.get(base)
        if not row_a_key or len(key) < 10:
            continue
        if row_a_key in key or key in row_a_key:
            mapped[field] = None
            logger.info(
                "post_fill_guard reformatted_row_duplicate blanked=%s (%r repeats row A)",
                field, str(val)[:44],
            )

    # ── Guard 10: the same policy listed twice in "other insurance" ──────────
    # Client: "These two entries are the same policy: 6E7-40-02---26 and
    # 6E74002. The full Commercial Auto declarations number is 6E7-40-02---26.
    # The shortened version appears elsewhere in the policy as a compact internal
    # format. Keep only 6E7-40-02---26."
    #
    # Compared on ALPHANUMERICS ONLY, then by PREFIX - because that is exactly
    # how the two spellings differ. "6E7-40-02---26" reduces to "6E7400226" and
    # the compact internal form "6E74002" is its prefix; likewise "BBC7263" is a
    # prefix of "BBC726326". A plain equality test misses both.
    #
    # The LONGER spelling wins: the client asked for "the consistent
    # declarations-page format", and the fuller number is the one printed there.
    # A 6-character floor on the shorter key keeps a genuinely different policy
    # that merely starts with the same characters from being swallowed.
    _MIN_POLICY_KEY = 6
    _seen_policy_keys: Dict[str, str] = {}
    for field in sorted(mapped):
        if "OtherPolicy_PolicyNumberIdentifier" not in field:
            continue
        val = str(mapped.get(field) or "").strip()
        if not val:
            continue
        key = re.sub(r"[^A-Za-z0-9]", "", val).upper()
        if len(key) < _MIN_POLICY_KEY:
            continue
        twin = next(
            (
                (k, f) for k, f in _seen_policy_keys.items()
                if k.startswith(key) or key.startswith(k)
            ),
            None,
        )
        if twin is None:
            _seen_policy_keys[key] = field
            continue
        prior_key, prior_field = twin
        # Keep whichever spelling is longer; clear the other row entirely.
        keep, drop, keep_key = (
            (prior_field, field, prior_key)
            if len(prior_key) >= len(key)
            else (field, prior_field, key)
        )
        _seen_policy_keys.pop(prior_key, None)
        _seen_policy_keys[keep_key] = keep
        mapped[drop] = None
        _lob_twin = drop.replace(
            "OtherPolicy_PolicyNumberIdentifier", "OtherPolicy_LineOfBusinessCode")
        if _lob_twin in mapped:
            mapped[_lob_twin] = None
        logger.info(
            "post_fill_guard duplicate_other_policy blanked=%s (same policy as %s)",
            drop, keep,
        )

    # ── Guard 9: a policy date wearing an event date's clothes ───────────────
    # Client: "The occurrence date 07/15/2025 is incorrect. That is the policy's
    # effective date, not the date of a fire or safety-code violation."
    for field, val in list(mapped.items()):
        if val is None or not str(val).strip():
            continue
        if _event_date_is_really_a_policy_date(field, val, facts):
            mapped[field] = None
            logger.info(
                "post_fill_guard policy_date_as_event blanked=%s (%r is a policy "
                "metadata date, not an occurrence date)", field, str(val)[:20],
            )

    # ── Guard 8: the field's own description, read back as its answer ────────
    # Live run: AdditionalInterest_FullName_B came back "The Additional
    # Interest's Full Name. As Used Here, This Is The Name Of The Trust." - its
    # own tooltip, title-cased. A value that is its own question carries zero
    # information and reads on the form as though a real trust were named.
    #
    # The client's ACORD 125 showed the same defect three more times, in the
    # SHORT form the 30-char floor could not see: "parent company" in the
    # parent/subsidiary relationship box, "judgment or lien" in the judgment
    # explanation box, and a reworded copy of the cancel/non-renew tooltip. The
    # short path that catches those is restricted to values THIS RUN'S GAP-FILL
    # MODEL authored - a Pass 1 or alias value came from an extracted fact and
    # is never re-litigated here. See _is_tooltip_echo for the measurements.
    _ai_authored = gpt_filled_set or set()
    # Owner-reported 2026-08-12: a "Y" standing WITHOUT its explanation. One
    # candidate mechanism is right here - the evidence gate keeps a grounded
    # Yes and writes its quote into the paired explanation, then THIS guard
    # blanks that explanation as a tooltip echo, leaving the Yes naked.
    # DIAGNOSTIC ONLY (zero behaviour change): when the field being blanked is
    # the explanation half of a Y/N pair whose question currently holds an
    # affirmative, say so loudly, so the next report can be pinned to a
    # mechanism instead of guessed at.
    try:
        _exp_to_question = {exp: q for q, exp
                            in _question_explanation_pairs(schema).items()}
    except Exception:                                     # noqa: BLE001
        _exp_to_question = {}
    for field, val in list(mapped.items()):
        if val is None or not str(val).strip():
            continue
        if _is_tooltip_echo(val, schema.get(field), field,
                            allow_short=field in _ai_authored):
            mapped[field] = None
            logger.info(
                "post_fill_guard tooltip_echo blanked=%s ai_authored=%s (%r)",
                field, field in _ai_authored, str(val)[:60],
            )
            _q = _exp_to_question.get(field)
            if _q and str(mapped.get(_q) or "").strip().upper() in ("Y", "YES"):
                logger.warning(
                    "post_fill_guard NAKED_YES question=%s kept an affirmative "
                    "but its paired explanation %s was just blanked as a "
                    "tooltip echo (%r) - if a live report shows a Y with no "
                    "explanation, this is the mechanism to check first",
                    _q, field, str(val)[:60],
                )

    # ── Guard 7: an "Other line of business" that is not other ───────────────
    # The lines-of-business grid ends with blank "Other" rows for lines ACORD
    # gives no box to. The client's form used two of them for "Commercial Auto"
    # and "Commercial Liability Umbrella" - both already ticked as standard
    # boxes two rows above: "The two 'Other' descriptions merely duplicate the
    # standard Business Auto and Umbrella selections."
    #
    # This removes a DUPLICATE, never information: the line is still declared,
    # by the enumerated checkbox that owns it. Blanks only when that checkbox is
    # actually ticked, so a genuine other line ("Professional Liability", or an
    # auto line on a form whose Auto box is NOT selected) is untouched. Matching
    # is the same tooltip-derived line vocabulary the premium boxes use, and it
    # declines to act on wording that fits several boxes.
    for field, val in list(mapped.items()):
        if "OtherLineOfBusinessDescription" not in field or not str(val or "").strip():
            continue
        standard_box = _standard_lob_box_for(str(val), schema)
        if not standard_box:
            continue
        if str(mapped.get(standard_box) or "").strip().lower() not in _AFFIRMATIVE_VALUES:
            continue
        mapped[field] = None
        # Its own "Other" tick goes with it - an empty description beside a
        # ticked Other box claims a line nobody named.
        paired_indicator = field.replace(
            "OtherLineOfBusinessDescription", "OtherIndicator")
        if paired_indicator in mapped:
            mapped[paired_indicator] = None
        logger.info(
            "post_fill_guard other_line_duplicate blanked=%s (%r already ticked at %s)",
            field, str(val)[:40], standard_box,
        )

    # ── Guard 9: a "Yes" may not stand without its explanation ──────────────
    # Owner-reported twice on live dec packages (2026-08-12): a Y stamped with
    # the adjacent explanation box EMPTY. The client's own rule is explicit -
    # "if yes, add explanation in the adjacent field" - and ACORD prints
    # EXPLAIN ALL "YES" RESPONSES on the form itself, so an unexplained Yes is
    # an incomplete answer on a legal document.
    #
    # The evidence gate already blanks an ungrounded Yes at fill time, but the
    # guards ABOVE run after it and can blank the explanation it wrote (the
    # tooltip-echo guard was caught doing exactly that by the NAKED_YES
    # diagnostic). This runs LAST, on the final state: whatever ate the
    # explanation, an affirmative whose paired explanation ends up empty is
    # blanked with it and the question goes to the ARQ instead. Only fields
    # ACORD itself pairs with an explanation are touched
    # (_question_explanation_pairs - never inferred from position alone).
    try:
        _yn_pairs = _question_explanation_pairs(schema)
    except Exception:                                     # noqa: BLE001
        _yn_pairs = {}
    for _q_field, _exp_field in _yn_pairs.items():
        _q_val = str(mapped.get(_q_field) or "").strip().lower()
        if _q_val not in _AFFIRMATIVE_VALUES:
            continue
        if str(mapped.get(_exp_field) or "").strip():
            continue
        mapped[_q_field] = None
        logger.warning(
            "post_fill_guard NAKED_YES_BLANKED question=%s explanation=%s - an "
            "affirmative whose paired explanation ended up empty cannot stand; "
            "blanked for the ARQ to ask",
            _q_field, _exp_field,
        )


# Values the AI can produce that are never literally present in the document
# text (they are reasoned out, not copied) — a presence check is meaningless for
# them, so they are treated as "not verifiable" rather than falsely flagged.
_VERIFY_SKIP_TOKENS = {
    "yes", "no", "y", "n", "true", "false", "on", "off", "x",
    "null", "none", "n/a", "na",
}


def _normalize_for_search(text: str) -> str:
    """Fold text to a punctuation/case/whitespace-insensitive form for literal
    presence checks. Any run of non-alphanumerics becomes a single space, so
    "$6,150,000" → "6 150 000", "4/1/2026" → "4 1 2026", and OCR line breaks
    collapse. Both the document text and the value are folded the SAME way, so
    formatting differences never break a match."""
    return re.sub(r"[^a-z0-9]+", " ", (text or "").lower()).strip()


def _value_in_raw_text(value: str, haystack_norm: str) -> bool:
    """True when `value` (as the AI produced it) actually appears in the uploaded
    document text (already normalized via `_normalize_for_search`).

    Deliberately conservative — biased AWAY from false "not found" flags: a
    word-subset fallback treats a lightly reworded value (dropped suffix,
    reordered tokens) as present. Yes/No answers and very short values are not
    meaningfully verifiable by presence and return False (they are handled by the
    existing confidence logic, not painted "verified")."""
    raw = (value or "").strip()
    if not raw or raw.lower() in _VERIFY_SKIP_TOKENS:
        return False
    needle = _normalize_for_search(raw)
    if len(needle.replace(" ", "")) < 4:
        return False
    if needle and needle in haystack_norm:
        return True
    # Word-subset fallback: every significant token (len >= 3) present.
    tokens = [t for t in needle.split(" ") if len(t) >= 3]
    return bool(tokens) and all(t in haystack_norm for t in tokens)


# ── Guard: fabricated industry-classification codes ─────────────────────────
# Live finding (2026-07-20, two independent submissions, different industries):
# ACORD 125's GL CODE / SIC / NAICS boxes came back filled with REAL, correct
# codes for the applicant's industry that appear NOWHERE in the uploaded
# document - 236220 + 5403 for a commercial GC, then 561730 + 0782 for a
# landscaper. The gap-fill model recognised the industry from the operations
# narrative and supplied the code from its own world knowledge. A classification
# code is a regulated identifier that drives rating and eligibility: an
# authoritative-looking wrong code on a submitted ACORD is worse than a blank
# box, and a producer has no way to tell the invented ones apart.
#
# The check is deterministic and purely structural - no LLM, no topic matching
# (see evidence-gate-design memory). A code is kept ONLY when the document
# both (a) mentions that code SYSTEM by name and (b) contains the value itself.
# Requiring the system name is what catches cross-family bleed: the GC document
# did contain "5403", but only as a WORKERS COMP class code, and it never says
# "SIC" anywhere - so 5403 cannot be a grounded SIC code.
#
# Deterministic (Pass 1 / alias) and client-supplied values are never touched -
# only values this run's gap-fill LLM authored.
#
# The label match is WHOLE-WORD, not substring. "sic" is three characters and
# `"sic" in raw_text.lower()` is satisfied by basic / classic / physician /
# intrinsic - words that appear on essentially every commercial policy - so the
# SIC half of this guard was permanently open and passed anything the model
# produced. Measured on a real run: an EMC rate/class code reached the SIC box
# and survived, because the document "mentioned SIC" only inside the word
# "basic". NAICS (5 chars) and the GL phrases were never exposed to this, but
# they go through the same matcher so the rule is uniform rather than special-
# cased for the one that broke.
_CLASSIFICATION_CODE_LABELS: List[Tuple[str, Tuple[str, ...]]] = [
    ("SICCode",              ("sic",)),
    ("NAICSCode",            ("naics",)),
    ("GeneralLiabilityCode", ("gl code", "gl class", "general liability code",
                              "general liability class")),
]

# Cache one compiled whole-word pattern per label phrase. `\b` on both ends
# keeps "SIC:", "S.I.C.", "sic code" and "(sic)" matching while rejecting the
# accidental substrings above. Multi-word phrases keep their internal spacing
# flexible so "GL  Code" and "GL Code" behave the same.
@lru_cache(maxsize=64)
def _label_word_re(phrase: str) -> "re.Pattern":
    return re.compile(
        r"\b" + r"\s+".join(re.escape(p) for p in phrase.split()) + r"\b",
        re.IGNORECASE,
    )


def _drop_ungrounded_classification_codes(
    mapped: dict, raw_text: str, gpt_filled_set: set,
) -> List[str]:
    """Blank any AI-filled SIC / NAICS / GL classification code that the source
    document does not actually support. Returns the list of blanked fields."""
    if not raw_text or not gpt_filled_set:
        return []
    hay_norm = _normalize_for_search(raw_text)
    hay_low  = raw_text.lower()
    dropped: List[str] = []

    for field in list(mapped.keys()):
        if field not in gpt_filled_set:
            continue
        val = mapped.get(field)
        if val is None or not str(val).strip():
            continue
        for token, labels in _CLASSIFICATION_CODE_LABELS:
            if token not in field:
                continue
            # The label must sit NEAR an occurrence of the value, not merely
            # anywhere in the package. On a live 271-page run the GL CLASS code
            # 91580 landed in the NAICS box and survived because "naics"
            # appeared SOMEWHERE in the document while 91580 appeared beside
            # "GL CLASS" 200 pages away — the exact cross-family bleed this
            # guard exists to stop. A genuinely labelled code ("NAICS: 238160")
            # always has its label within a line of the value.
            value_present = _value_in_raw_text(str(val), hay_norm)
            label_near = False
            if value_present:
                _needles = {str(val).strip().lower()}
                _digits = re.sub(r"\D", "", str(val))
                if len(_digits) >= 3:
                    _needles.add(_digits)
                for _needle in _needles:
                    if label_near or not _needle:
                        continue
                    for _m in re.finditer(re.escape(_needle), hay_low):
                        _win = hay_low[max(0, _m.start() - 120):_m.end() + 120]
                        if any(_label_word_re(lbl).search(_win) for lbl in labels):
                            label_near = True
                            break
            if not (label_near and value_present):
                logger.info(
                    "gpt_fill DROP_UNGROUNDED_CODE: field=%s value=%r "
                    "label_near_value=%s value_in_doc=%s",
                    field, val, label_near, value_present,
                )
                mapped[field] = None
                dropped.append(field)
            break
    return dropped


# ── Guard: another PARTY's value stamped into an applicant-owned box ─────────
# Live regression (2026-08-09, real run): `BusinessInformation_ParentOrganizationName_A`
# came back "Emc Insurance Companies" - the CARRIER - so a signed ACORD 125
# asserted that the applicant is a subsidiary of its own insurer. The same run
# put the producer's phone and the carrier's claim line into the applicant's
# SECONDARY PHONE boxes.
#
# Why the existing layers all missed it, and why this one is needed:
#   * `_FACT_ENTITY` / `_entity_mismatch` guard the DETERMINISTIC path only.
#     Gap fill reads raw document text and never consults them.
#   * `field_mapping_integrity` checks every source but only DEMOTES, and its
#     own docstring records that parent/subsidiary organization names were
#     "deliberately excluded" - a judgement made when the risk was theoretical
#     and now falsified by a real form.
#   * The raw-text check passes: the carrier's name IS in the document.
#
# This is a value-IDENTITY check against facts we already hold for a DIFFERENT
# party - the same shape as `_drop_third_party_address_bleed`, not a heuristic
# and not topic matching. It cannot fire when we have no carrier/producer fact.
#
# Applicant-side blocks, swept across all 17 real schemas rather than assumed:
#   NamedInsured_*        - the applicant, by definition
#   BusinessInformation_* - all 23 field families are the applicant's own
#                           business (payroll, employee counts, gross receipts,
#                           business type, operations, parent organization).
#                           None can legitimately hold a carrier/producer value.
#   Subsidiary_*          - the applicant's corporate family
#   Driver_*              - the insured's drivers. Added on evidence, not on
#                           theory: improving-ll.md C22 records a real ACORD 127
#                           run with `Driver_TaxIdentifier_I = "ERIN ROYAL"` and
#                           `Driver_GenderCode_A = "ERIN ROYAL"` - the PRODUCER's
#                           name. C22 caught the tax-ID case by declared TYPE and
#                           noted the others were invisible to a type check;
#                           ownership sees all of them. Swept 269 Driver_* fields
#                           x 15 driver-appropriate values = 4,035 pairs, zero
#                           false positives.
#
# Third-party blocks are deliberately OUT of scope and must STAY out - a carrier
# name is the CORRECT value in several of them:
#   Producer_*, Insurer_*, AdditionalInterest_*, CertificateHolder_*, Auditor_*,
#   PriorCoverage_*, UnderlyingPolicy_* (ACORD 131 - the underlying carrier),
#   OtherInsurance_* (ACORD 160 - another carrier by definition).
# Adding either of the last two would blank a legitimate carrier name; the
# sweep that found them is recorded in fix-form-stamping.md.
_APPLICANT_OWNED_PREFIXES: Tuple[str, ...] = (
    "NamedInsured_", "BusinessInformation_", "Subsidiary_", "Driver_",
)

# Parties whose values must never appear in an applicant-owned box. Read from
# the shipped `_FACT_ENTITY` table so there is exactly one definition of who
# owns which fact.
_FOREIGN_PARTIES: Tuple[str, ...] = ("Producer", "Insurer")


def _identity_token(value: Any) -> str:
    """Comparison token for a value-identity match: alphanumeric only, folded.

    Deliberately format-blind, so the client's own regression - the producer
    phone `303-996-7800` reappearing as `(303)996-7800` in the applicant's
    secondary-phone box - compares equal. Too short a token can coincide, so
    callers require a minimum length.
    """
    return re.sub(r"[^a-z0-9]+", "", str(value or "").lower())


_MIN_IDENTITY_TOKEN = 6


# An INSURANCE CARRIER'S NAME, by shape rather than by matching a value we
# already hold. `_foreign_party_values` below can only catch a carrier we have
# extracted; the live form put "Emcasco Insurance Company" - a member of the
# carrier's GROUP, never named as the carrier itself - into the applicant's
# SUBSIDIARY box, off the back of an endorsement listing group companies. No
# comparison against `carrier_name` could ever have caught it.
#
# Anchored on insurer-specific NOUN PHRASES, never a bare word: "insurance
# company" and "risk retention group" qualify, "insurance" alone does not.
# Measured against real applicant names: "Summit Insurance Agency, Inc.",
# "Denver Mutual Water Company", "Front Range Underwriting Services LLC" and
# "Casualty Restoration Services LLC" all survive - 8 carriers rejected, 0 false
# rejections across 9 genuine names.
_INSURER_NAME_SHAPE_RE = re.compile(
    r"\b(?:insurance\s+(?:company|co\.?|corporation|group|companies)|"
    r"casualty\s+(?:company|co\.?|insurance)|assurance\s+(?:company|co\.?)|"
    r"indemnity\s+(?:company|co\.?|insurance)|underwriters?\s+(?:inc|llc|ltd|group|of)|"
    r"risk\s+retention\s+group|reciprocal\s+exchange|surplus\s+lines)\b", re.I
)


def _looks_like_an_insurance_carrier(value: Any) -> bool:
    return bool(_INSURER_NAME_SHAPE_RE.search(str(value or "")))


def _foreign_party_values(facts: dict) -> Dict[str, Tuple[str, str]]:
    """{comparison token -> (party, fact_key)} for every Producer/Insurer fact
    we actually hold. Carrier names additionally register their normalized
    carrier-family token, because a document writes one carrier several ways
    ("Emc Insurance Companies" vs "Employers Mutual Casualty Company") and a
    literal comparison would miss exactly the case that was reported."""
    out: Dict[str, Tuple[str, str]] = {}
    for key, party in _FACT_ENTITY.items():
        if party not in _FOREIGN_PARTIES:
            continue
        raw = _fv(facts, key)
        if raw is None or not str(raw).strip():
            continue
        tok = _identity_token(raw)
        if len(tok) >= _MIN_IDENTITY_TOKEN:
            out.setdefault(tok, (party, key))
        if key.endswith("_name") or key.endswith("name"):
            try:
                from services.normalization import normalize_carrier
                fam = _identity_token(normalize_carrier(raw))
                if len(fam) >= 3:
                    out.setdefault(fam, (party, key))
            except Exception:                    # noqa: BLE001 - advisory only
                pass
    return out


def _drop_foreign_entity_values(
    mapped: dict, facts: dict, gpt_filled_set: set,
) -> List[str]:
    """Blank a gap-fill value in an applicant-owned box when it is provably
    another party's value. Returns the list of blanked fields.

    Refuses to guess in both directions: it never touches a deterministic,
    alias or client value, and it leaves the box alone when the same value is
    ALSO one of the applicant's own facts (a captive agency, or an extraction
    that mixed the two) - ambiguity fails toward keeping the fill.
    """
    if not gpt_filled_set:
        return []
    foreign = _foreign_party_values(facts)
    if not foreign:
        return []

    own: set = set()
    for key, party in _FACT_ENTITY.items():
        if party in _FOREIGN_PARTIES:
            continue
        raw = _fv(facts, key)
        if raw is not None and str(raw).strip():
            own.add(_identity_token(raw))

    dropped: List[str] = []
    for field in list(mapped.keys()):
        if field not in gpt_filled_set:
            continue
        if not field.startswith(_APPLICANT_OWNED_PREFIXES):
            continue
        val = mapped.get(field)
        if val is None or not str(val).strip():
            continue
        # A carrier by SHAPE, even one we never extracted. The live form put
        # "Emcasco Insurance Company" - a member of the carrier's group, never
        # named as the carrier itself - into the applicant's subsidiary box, so
        # no comparison against a value we hold could have caught it.
        if _looks_like_an_insurance_carrier(val) and not _looks_like_an_insurance_carrier(
                _fv(facts, "applicant_name") or ""):
            mapped[field] = None
            dropped.append(field)
            logger.info(
                "foreign_entity blanked=%s (%r is shaped like an insurance "
                "carrier, in an applicant-owned box)", field, str(val)[:50],
            )
            continue
        tok = _identity_token(val)
        if len(tok) < _MIN_IDENTITY_TOKEN:
            continue
        hit = foreign.get(tok)
        if hit is None:
            try:
                from services.normalization import normalize_carrier
                hit = foreign.get(_identity_token(normalize_carrier(val)))
            except Exception:                    # noqa: BLE001
                hit = None
        if hit is None:
            continue
        if tok in own:
            continue                             # ambiguous - keep the fill
        party, fact_key = hit
        logger.info(
            "gpt_fill DROP_FOREIGN_ENTITY: field=%s value=%r belongs_to=%s fact=%s",
            field, val, party, fact_key,
        )
        mapped[field] = None
        dropped.append(field)
    return dropped


# ── Guard: the insured's own address bleeding into a THIRD PARTY's block ─────
# Live finding (2026-07-20): ACORD 125's PRODUCER block showed the applicant's
# street address. The deterministic rule for this was already fixed (see
# _deterministic_map: `_addr_*` resolves for NamedInsured_* only, everything
# else returns UNMATCHED) - so the field correctly fell through to gap-fill,
# and gap-fill then supplied the applicant's address because it was the only
# address in the document. Blanking the deterministic path alone was therefore
# not enough; the same wrong value simply arrived one pass later.
#
# A producer / certificate holder / mortgagee is by definition a DIFFERENT
# entity from the insured, so its street address matching the insured's own is
# a fill error, never a coincidence. Matching is done on the STREET line only -
# a third party genuinely can share the insured's city, state or ZIP - and when
# it matches, the whole address block for that entity is cleared so a stray
# city/ZIP is not left behind orphaned next to a blanked street.
#
# This is a value-IDENTITY check against one known fact with a different
# purpose (the same shape as _is_generic_boilerplate_reuse), not a keyword or
# topic heuristic.
# Swept across all 17 schemas for entity blocks that own an address: the ones
# below are the THIRD PARTIES (a different legal entity from the insured).
# Deliberately EXCLUDED, because the insured's own address is legitimate there:
#   NamedInsured / CommercialStructure / Location  - the insured's own premises
#   Vehicle                                        - garaging is often the yard
#   EmployeeBenefitPlan                            - a small employer really can
#                                                    administer its own plan
_THIRD_PARTY_ADDRESS_BLOCKS: Tuple[str, ...] = (
    "Producer_MailingAddress",
    "AdditionalInterest_MailingAddress",
    "CertificateHolder_MailingAddress",
    "Auditor_MailingAddress",
    "Auditor_Address",
)


def _drop_third_party_address_bleed(
    mapped: dict, facts: dict, gpt_filled_set: set,
) -> List[str]:
    """Clear a third party's address block when its street line is really the
    insured's own address. Returns the list of blanked fields."""
    if not gpt_filled_set:
        return []
    insured_addr = _fv(facts, "mailing_address")
    if not insured_addr or not str(insured_addr).strip():
        return []
    insured_norm = _normalize_for_search(str(insured_addr))
    if not insured_norm:
        return []

    dropped: List[str] = []
    for block in _THIRD_PARTY_ADDRESS_BLOCKS:
        # Find this block's street line(s) and test them against the insured's.
        bleed_rows: set = set()
        for field, val in mapped.items():
            if not field.startswith(block) or "LineOne" not in field:
                continue
            if field not in gpt_filled_set:
                continue
            if val is None or len(str(val).strip()) < 5:
                continue
            if _normalize_for_search(str(val)) in insured_norm:
                # Row suffix (_A/_B/…) so only the offending row is cleared.
                _m = re.search(r"_([A-N])$", field)
                bleed_rows.add(_m.group(1) if _m else "")

        if not bleed_rows:
            continue
        for field in list(mapped.keys()):
            if not field.startswith(block):
                continue
            _m = re.search(r"_([A-N])$", field)
            if (_m.group(1) if _m else "") not in bleed_rows:
                continue
            if mapped.get(field) is None or not str(mapped.get(field)).strip():
                continue
            if field not in gpt_filled_set:
                continue  # never touch a deterministic / client value
            logger.info(
                "gpt_fill DROP_ADDRESS_BLEED: field=%s value=%r "
                "(matches the insured's own mailing address)",
                field, mapped.get(field),
            )
            mapped[field] = None
            dropped.append(field)
    return dropped


# ── Guard: a NAIC number labelled for one entity, stamped for another ────────
# Live finding (2026-07-20): ACORD 125's CARRIER NAIC CODE box (Insurer_NAICCode
# - the CARRIER's own NAIC number) showed the PRODUCER's NAIC number instead.
# The document states "Producer NAIC Number: 41982" and never states a NAIC
# number for the carrier (Pinnacle Mutual Insurance) at all. There is no
# structured `producer_naic` fact anywhere in the extraction schema for this
# guard to compare against (unlike the address guard above, which has
# `facts['mailing_address']`) - "producer NAIC number" simply has no home, so
# gap-fill reached for the only NAIC-shaped number anywhere in the document.
#
# This is a DIFFERENT mechanism from both guards above: the value is not
# fabricated (5-digit codes like a WC class code, above) and it is not a known
# fact belonging to a different entity (the address guard, above) - it is a
# real number in the document whose OWN label names a different entity than
# the field being filled. So the check is text-proximity: does this number, at
# the point it actually appears in the document, sit next to language for the
# RIGHT entity (carrier/insurer) rather than a different one (producer/agency)?
#
# Every occurrence of the value is checked (a document can repeat a number);
# the value is kept if ANY occurrence is carrier/insurer-labelled. It is only
# dropped when EVERY occurrence is labelled for a different role - so a
# genuinely stated carrier NAIC number is never at risk even if the SAME
# digits happen to also appear elsewhere for an unrelated reason.
_NAIC_FIELD_TOKENS: Tuple[str, ...] = ("Insurer_NAICCode", "PriorCoverage_NAICCode")
_NAIC_OWN_ROLE_WORDS   = ("insurer", "carrier", "insurance company", "underwriter", "company")
_NAIC_OTHER_ROLE_WORDS = ("producer", "agency", "agent", "broker")
_NAIC_CONTEXT_WINDOW   = 45  # chars of context immediately before the number


def _drop_mislabeled_naic_codes(
    mapped: dict, raw_text: str, gpt_filled_set: set,
) -> List[str]:
    """Blank an AI-filled Insurer/PriorCoverage NAIC code whose only grounding
    in the document is labelled for a DIFFERENT entity (producer/agency, not
    carrier/insurer). Returns the list of blanked fields."""
    if not raw_text or not gpt_filled_set:
        return []
    hay_low = raw_text.lower()
    dropped: List[str] = []

    for field in list(mapped.keys()):
        if field not in gpt_filled_set:
            continue
        if not any(tok in field for tok in _NAIC_FIELD_TOKENS):
            continue
        val = mapped.get(field)
        if val is None or not str(val).strip():
            continue
        digits = re.sub(r"\D", "", str(val))
        if len(digits) < 4:
            continue  # too short to search for meaningfully

        any_own_role   = False
        any_other_only = False
        start = 0
        while True:
            idx = hay_low.find(digits, start)
            if idx == -1:
                break
            window = hay_low[max(0, idx - _NAIC_CONTEXT_WINDOW): idx]
            has_own   = any(w in window for w in _NAIC_OWN_ROLE_WORDS)
            has_other = any(w in window for w in _NAIC_OTHER_ROLE_WORDS)
            if has_own:
                any_own_role = True
            elif has_other:
                any_other_only = True
            start = idx + len(digits)

        # ── FABRICATED, not merely mislabelled ───────────────────────────────
        # THE HOLE THIS GUARD HAD FROM DAY ONE: it asked "is this number
        # labelled for the wrong entity?" and never "is this number in the
        # document at all?". A value that appears NOWHERE sets neither flag and
        # sailed through.
        #
        # The owner ran one declarations package through TWO accounts and got
        # NAIC 25321 on one and a blank box on the other - and an earlier run
        # of the same document produced 26247. Three answers from one document
        # is the definition of a value that was never read off it. A NAIC code
        # is a copied identifier that the pipeline never reformats (it is in
        # `_GROUNDING_MUST_APPEAR` for exactly that reason), so literal absence
        # is proof, not a heuristic.
        if not any_own_role and not any_other_only and digits not in \
                re.sub(r"\D", "", hay_low):
            logger.info(
                "gpt_fill DROP_UNGROUNDED_NAIC: field=%s value=%r - this number "
                "does not appear anywhere in the uploaded document",
                field, val,
            )
            mapped[field] = None
            dropped.append(field)
            continue

        if not any_own_role and any_other_only:
            logger.info(
                "gpt_fill DROP_MISLABELED_NAIC: field=%s value=%r "
                "(only labelled for a different entity in the document)",
                field, val,
            )
            mapped[field] = None
            dropped.append(field)
    return dropped


# ── SHADOW MODE: is this AI-authored value actually in the document? ─────────
# `_value_in_raw_text` has existed for a long time and is wired into exactly TWO
# guards - industry-classification codes and NAIC codes. Every OTHER value the
# gap-fill model authors is stamped onto a legal document with nothing ever
# checking that it came from the document, even though the prompt's first rule is
# "copy values verbatim".
#
# This REPORTS ONLY. It never blanks, never mutates, never blocks. The point is
# to produce the evidence needed to decide whether enforcing it is safe, on real
# submissions, before a single real value is at risk. Read the log lines, then
# decide. Set FIELD_GROUNDING_SHADOW=0 to silence it.
#
# The three-way split is NOT a new table - it is derived from ACORD's own
# declared type (`_TOOLTIP_TYPE_RE`, "Enter code:", "Enter date:", ...), which
# covers 3,888 of 5,852 fields. That matters because presence is meaningless for
# a value the pipeline legitimately REFORMATS: a date read as "March 1, 2026" is
# stamped "03/01/2026" and would look fabricated to a literal search. Flagging
# those would drown the real signal and is exactly how a check like this gets
# switched off and forgotten.
_FIELD_GROUNDING_SHADOW = os.getenv(
    "FIELD_GROUNDING_SHADOW", "1").strip().lower() not in ("0", "false", "no")

# Declared types whose stamped form is DERIVED, not copied - never verifiable by
# literal presence.
_GROUNDING_SKIP_TYPES = frozenset({"date", "year", "percentage", "percent"})
# Declared types that must appear in the document character-for-character. These
# are copied identifiers and figures; a "close enough" match is not evidence.
_GROUNDING_STRICT_TYPES = frozenset({
    "code", "identifier", "number", "amount", "limit", "deductible",
})


def _grounding_mode_for(field: str, meta: Any, value: str) -> str:
    """'strict' | 'lenient' | 'skip' - derived from ACORD's own declared type."""
    info = meta if isinstance(meta, dict) else {}
    if "/Btn" in (info.get("ft") or ""):
        return "skip"                       # a tick is not a quotable string
    raw = (value or "").strip()
    if raw.lower() in _VERIFY_SKIP_TOKENS:
        return "skip"
    if len(_normalize_for_search(raw).replace(" ", "")) < 4:
        return "skip"                       # too short to search for meaningfully
    if _is_yes_no_field(field, {field: info}):
        return "skip"
    m = _TOOLTIP_TYPE_RE.match(info.get("tu") or "")
    declared = (m.group(1).lower() if m else "")
    if declared in _GROUNDING_SKIP_TYPES:
        return "skip"
    if declared in _GROUNDING_STRICT_TYPES:
        return "strict"
    return "lenient"


def _report_ungrounded_ai_values(
    mapped: dict, schema: dict, raw_text: str, gpt_filled_set: set, form_id: str,
) -> None:
    """Log every AI-authored value that is NOT present in the uploaded text.

    READ-ONLY. If this ever gains the power to blank a field, the decision must
    be backed by a measured run, not by this function looking reasonable.
    """
    if not _FIELD_GROUNDING_SHADOW or not raw_text or not gpt_filled_set:
        return
    try:
        hay = _normalize_for_search(raw_text)
        checked = skipped = 0
        missing: List[str] = []
        for field in sorted(gpt_filled_set):
            value = mapped.get(field)
            if value is None or not str(value).strip():
                continue
            mode = _grounding_mode_for(field, schema.get(field), str(value))
            if mode == "skip":
                skipped += 1
                continue
            checked += 1
            needle = _normalize_for_search(str(value))
            found = (needle in hay) if mode == "strict" else _value_in_raw_text(str(value), hay)
            if not found:
                missing.append(f"{field}[{mode}]={str(value)[:60]!r}")
        logger.info(
            "GROUNDING_SHADOW form=%s checked=%d skipped=%d not_in_document=%d",
            form_id or "unknown", checked, skipped, len(missing),
        )
        for item in missing:
            logger.info("GROUNDING_SHADOW form=%s WOULD_BLANK %s", form_id or "unknown", item)
    except Exception as exc:                              # noqa: BLE001
        # A diagnostic must never be able to break a fill.
        logger.warning("GROUNDING_SHADOW skipped (form=%s): %s", form_id, exc)


# ── Stricter verification for LLM-authored "grounding quotes" ───────────────
# _value_in_raw_text's word-subset fallback exists to forgive a lightly
# REWORDED real value (dropped suffix, reordered tokens on an address/name).
# It is too permissive for a "grounding quote" the LLM writes freely (Figure
# 30 Question-code proof, see question_grounding): with only common short
# words required to each appear SOMEWHERE in the document independently, a
# model can pass a sentence it invented outright, so long as its individual
# words happen to be scattered across an unrelated business document (bug
# found 2026-07-12, live ACORD 126 test: fabricated "products under label of
# others: N" and "products of others sold: N" both survived on quotes whose
# words matched this way despite the document never mentioning either topic).
# A quote is proof only when the model's claimed excerpt actually occurs as
# a contiguous phrase, OR (found in live audit testing 2026-07-15: a genuine,
# clearly-documented "Yes" on ACORD 127's vehicle-maintenance question was
# wiped, along with its explanation, because the model's own paraphrase of the
# real sentence wasn't a byte-for-byte match) most of the quote's own words are
# covered by ONE specific real sentence in the document. The fallback is
# scoped per-SENTENCE and measured as COVERAGE OF THE QUOTE (not a symmetric
# Jaccard ratio against the whole sentence) - Guard 4's symmetric ratio under-
# counts here because a real sentence is often a long run-on containing lots
# of unrelated content around the part actually being quoted (e.g. a company-
# description clause bundled into the same sentence as the maintenance detail),
# which dilutes a symmetric ratio even for a faithful paraphrase.
#
# This does NOT reopen the 2026-07-12 bug this strictness was built to close:
# that bug worked by scattering common words ACROSS THE WHOLE DOCUMENT, in
# unrelated sentences, with no requirement that they co-occur anywhere. Here,
# the matching words must cluster inside ONE bounded, real sentence - a
# fabricated quote about an undiscussed topic would need to coincidentally
# share most of its words with some single real sentence to pass, which is a
# materially higher bar.
_QUOTE_COVERAGE_THRESHOLD = 0.75
_QUOTE_MIN_SHARED_TOKENS = 3


def _quote_covered_by_sentence(quote_tokens: frozenset, sentence_tokens: frozenset) -> bool:
    """True when `sentence_tokens` covers most of `quote_tokens` - directional
    (relative to the QUOTE only), unlike _is_near_duplicate_text's symmetric
    Jaccard ratio. See _quote_grounds_claim for why direction matters here."""
    if len(quote_tokens) < _QUOTE_MIN_SHARED_TOKENS:
        return False
    shared = quote_tokens & sentence_tokens
    if len(shared) < _QUOTE_MIN_SHARED_TOKENS:
        return False
    return (len(shared) / len(quote_tokens)) >= _QUOTE_COVERAGE_THRESHOLD


def _quote_grounds_claim(quote: str, haystack_norm: str, sentences: Optional[List[str]] = None) -> bool:
    raw = (quote or "").strip()
    if not raw:
        return False
    needle = _normalize_for_search(raw)
    # LOWERED 12 -> 6 on 2026-08-14. The floor exists so a two-letter fragment
    # cannot match trivially, but 12 was measured to be above real evidence:
    # "Direct Bill" normalizes to 10 characters, so the phrase this package
    # prints on all four section dec pages could NEVER ground anything - and
    # the box duly shipped "No" against four printed DIRECT BILLs. 6 keeps the
    # anti-fragment purpose (nothing under two short words qualifies) without
    # excluding short printed VALUES, which are exactly what a dec page states.
    if len(needle.replace(" ", "")) < 6:
        return False
    if needle in haystack_norm:
        return True
    if not sentences:
        return False
    q_tokens = _sim_tokens(raw)
    return any(_quote_covered_by_sentence(q_tokens, _sim_tokens(s)) for s in sentences)


# ── Explanation must be genuine per-question content, not reused boilerplate ─
# (found in audit, live test 2026-07-15): "operations_description" answers a
# BROAD question - "what does the business do" - and is core content meant for
# its own dedicated field(s) (see _EVIDENCE_REQUIRED_TOKENS's design note:
# "OperationsDescription... core required content, not a Yes/No
# justification"). The gap-fill LLM, unable to find real content for a
# specific compliance question (e.g. "do operations involve transporting
# hazardous material?"), grabbed this same generic sentence and reused it
# verbatim as the "explanation" - _present() saw it was genuinely IN the
# document and accepted it, with no check that it actually ANSWERS this
# question rather than a different one entirely.
#
# This is the single-occurrence counterpart to Guard 4's cross-field
# boilerplate-bleed detection (_enforce_post_fill_guards), which only fires
# when the SAME text repeats across 2+ MAPPED fields - it never saw this
# case because the sentence appeared in exactly one field on this form. This
# check compares against the FACT itself (a known, single, well-defined value
# with an established DIFFERENT purpose), so it is a value-IDENTITY check,
# not a keyword or topic-overlap heuristic - it does not revisit the standing
# rule against those (see _is_yes_no_field's design note; also
# evidence-gate-design memory: "do NOT reintroduce topic-keyword matching").
#
# "additional_remarks_text" (audit finding 2026-07-16) carries the identical
# risk profile: a broad, catch-all narrative fact ("any additional remarks,
# explanations, or narrative... e.g. claims context, operations detail,
# conflict resolution" - fact_registry.py) that could equally get recycled as
# an unrelated question's "explanation". Safe to add: its only legitimate
# destination (ACORD 101's AdditionalRemark_RemarkText_* rows, via
# _apply_acord101_overflow) runs strictly AFTER this evidence-gate block and
# unconditionally overwrites whatever it decided, so there is no collision
# with a genuine placement to guard against here.
_BOILERPLATE_FACT_KEYS = ("operations_description", "additional_remarks_text")


def _is_generic_boilerplate_reuse(
    field: Optional[str], text: str, facts: dict,
    reserved_values: Optional[Dict[str, str]] = None,
) -> bool:
    """True when `text` is the applicant's generic operations_description fact
    (verbatim or a near-duplicate paraphrase of it), UNLESS `field` is itself
    the field that legitimately holds that fact deterministically (mirrors
    Guard 4's own "legit_owner" exemption - the same fact is always allowed to
    sit in the ONE field it actually belongs to).

    `reserved_values` (optional): {other_field: its_value} for values ALREADY
    assigned as the specific, correct companion answer to a DIFFERENT question
    on this same form (see _NONADJACENT_QUESTION_COMPANIONS). A candidate
    explanation that CONTAINS one of these reserved values verbatim is the
    same document fact being double-counted for two different, unrelated
    questions - found in audit (live test 2026-07-15): ACORD 127's "leased to
    others" question came back "Yes", explained by the same vehicle-lease
    paragraph that correctly names the OTHER owner for the SEPARATE ownership
    question. A value-CONTAINMENT check against a KNOWN reserved value, not a
    keyword/topic heuristic."""
    if not field or not text or not str(text).strip():
        return False
    s = str(text).strip()
    s_lower = s.lower()
    s_tokens = _sim_tokens(s)
    for fact_key in _BOILERPLATE_FACT_KEYS:
        fact_val = _fv(facts, fact_key)
        if not fact_val or not str(fact_val).strip():
            continue
        f_tokens = _sim_tokens(str(fact_val))
        if s_lower != str(fact_val).strip().lower() and not _is_near_duplicate_text(s_tokens, f_tokens):
            continue
        det = _deterministic_map(field, facts)
        if isinstance(det, str) and det.strip().lower() == s_lower:
            return False   # this field IS the legitimate home for the fact
        return True
    for other_field, other_val in (reserved_values or {}).items():
        if other_field == field or not other_val:
            continue
        ov = str(other_val).strip()
        if len(ov) >= 8 and ov.lower() in s_lower:
            return True
    return False


# ── "Proof of No" verification (bug found 2026-07-12, live ACORD 125 test) ───
# _quote_grounds_claim confirms a grounding quote is genuinely PRESENT in the
# document, but not that it actually PROVES a NEGATIVE answer. The model,
# required to cite a quote for every Question-code answer, would grab any real
# sentence from the document (e.g. "Ironclad Fabrication & Welding LLC is a
# metal fabrication and welding contractor") as "proof" that the applicant is
# NOT a subsidiary / has NO fire-code violations / etc. A presence-only check
# kept the bogus "No" - the exact symptom the client reported (every General
# Information Y/N stamped "No" from a document that never addresses any of
# those questions). The distinguishing property of a genuine proof-of-No is
# simple and reliable: it EXPRESSES a negative (contains a negation cue). A
# positive descriptive sentence does not, so requiring one on the negative
# branch drops the bogus "No" while keeping a documented explicit "No" (e.g.
# "no prior cancellations"). Its failure mode is safe - a real "No" phrased
# without any negation word is rare and merely left blank for ARQ.
#
# TWO CORRECTIONS, 2026-08-14, both measured rather than reasoned about:
#
# 1. "no" IS THE ABBREVIATION FOR "NUMBER", and every declarations page prints
#    it - "Policy No. BBC7263", "FEIN No. 84-2210987", "AGENT NO. W6258". The
#    bare `\bno\b` therefore licensed almost ANY borrowed dec line as proof of
#    a "No": 4 of 4 junk strings admitted in the reproduction. The code already
#    knew this - `_COVERAGE_DENIAL_RE`'s comment says "'no' is also the
#    abbreviation for number" and keeps the broad cue off the Yes side - the
#    knowledge simply was never applied here. `_strip_number_abbreviations`
#    removes those occurrences BEFORE the cue test, so "no prior cancellations"
#    still reads as a negation and "Policy No. BBC7263" no longer does.
#
# 2. `free|clear|clean` are not negation cues in insurance prose. "toll free",
#    "free-standing masonry", "clearance" - all admitted. Bare `free` is gone;
#    `-free` (asbestos-free) stays, because a hyphenated compound genuinely
#    negates. Removing a cue can only make the "No" side STRICTER, i.e. fail
#    toward blank, which is the standing preference.
#
# What this does NOT fix is the other half: a genuine implied "No" carries no
# negation word at all ("All vehicles are owned by the applicant"), and no word
# list can see that. That is implication, and it is the evidence JUDGE's job
# (`_judge_evidence_batch`) - this regex is now only the cheap pre-filter.
# TWO SHAPES, both requiring positive evidence that this "no" is an identifier
# label rather than a denial. The first cut was `\bno[.:]?\s*(?=[#A-Z0-9])` with
# re.I - and re.I makes [A-Z] match lowercase, so it stripped the "no" out of
# "no prior cancellations" and blanked a legitimate No. The suite caught it
# immediately. Both shapes below are unreachable by a genuine negation:
#   1. "No." / "No:" followed by a token CONTAINING A DIGIT - "Policy No.
#      BBC7263", "FEIN No. 84-2210987". A denial is never punctuated that way.
#   2. A known identifier label directly before it - "POLICY NO 6E7-40-02",
#      "AGENT NO W6258" - which is how dec pages print it without a period.
# An all-caps document ("THE APPLICANT HAS NO PRIOR CANCELLATIONS") is safe on
# both: no period, no digit, no label word.
_NUMBER_ABBREV_RE = re.compile(
    r"\bno[.:]\s*(?=\S*\d)"
    r"|\b(?:policy|agent|account|item|form|fein|tax|serial|vin|claim"
    r"|certificate|licen[cs]e|id)\s+no\b\.?\s*",
    re.I,
)

# Boxes that ask whether a COVERAGE EXISTS on this policy, as opposed to
# whether an EXPOSURE exists at the applicant. For these - and only these - a
# printed declarations coverage line is the correct evidence rather than a
# disqualifying artifact. See the exemption in `_evidence_supports`.
_COVERAGE_EXISTENCE_FIELD_RE = re.compile(r"Policy_LineOfBusiness_")


def _strip_number_abbreviations(text: str) -> str:
    """Remove "No." used as the abbreviation for NUMBER, so the negation cue
    below cannot read an identifier label as a denial. Only strips when what
    follows looks like an identifier (a digit, a '#', or an uppercase code
    character) - "no claims" and "no subsidiaries" are untouched because a
    lowercase word follows."""
    return _NUMBER_ABBREV_RE.sub(" ", str(text or ""))


_NEGATION_CUE_RE = re.compile(
    r"\b(no|not|none|never|without|nor|neither|nil|cannot|lack|absence)\b"
    r"|n't\b|-free\b"
)


# A quote that is nothing but a policy EXCLUSION TITLE ("BROAD ABUSE OR
# MOLESTATION EXCLUSION"). An exclusion is the policy declining to cover a thing
# and is never evidence the thing happened. Anchored to the WHOLE quote ending in
# "exclusion(s)" so a real event that merely mentions one still counts.
_EXCLUSION_TITLE_RE = re.compile(
    r"^[\s\W]*(?:[A-Z0-9][\w\-/ ]{0,60}\s)?exclusions?[\s\W]*$", re.I
)

# An exclusion CLAUSE, as opposed to a form title. Live run 2026-08-09: ACORD
# 125 Question 3 ("any exposure to flammables, explosives, chemicals?") came
# back "Y" grounded on "This insurance does not apply to: Asbestos" - a policy
# exclusion read as proof the exposure exists. The policy saying it will not
# cover a thing is not the applicant saying they do it.
#
# Y-GATE ONLY. Deliberately NOT added to `_COVERAGE_DENIAL_RE`, which the
# declared-absent scan shares: "this insurance does not apply to flood" sitting
# near the word Property would wrongly downgrade the whole property line, and
# that scan already refuses "excluded" for exactly this reason.
# Measured: 4 real exclusion clauses rejected, 0 false rejections across 8
# genuine affirmative quotes.
_EXCLUSION_CLAUSE_RE = re.compile(
    r"\b(?:this insurance does not apply|does not apply to|shall not apply to|"
    r"we will not pay for|is excluded under|are excluded under)\b", re.I
)

# POLICY CONTRACT LANGUAGE - the policy describing how IT operates, as opposed
# to a statement about the applicant. Client, on the live output:
#
#   "That clause describes how coverage operates after bankruptcy. It does not
#    say that Orbin Contracting filed for bankruptcy."
#   "Never convert generic policy terminology into applicant-history facts."
#
# The ACORD 125 General Information questions ask about the APPLICANT'S HISTORY.
# A bankruptcy CONDITION, a judgment provision or an inspection right is the
# contract talking about itself and answers none of them - in either direction.
# Applied to BOTH Y and N: "Bankruptcy or insolvency of the insured will not
# relieve us of our obligations" reads as a negation and was keeping a false "N".
#
# Anchored on the INSURER speaking as a party ("relieve us", "our obligations",
# "under this policy") rather than on any topic word, so an applicant writing
# "We have had no claims in the past five years" is untouched - verified, that
# exact sentence passes. Measured: 5 contract quotes rejected, 0 false
# rejections across 7 genuine applicant statements.
# Below this length a match is a coincidence, not a clause. Measured against a
# corpus of legitimate ACORD narrative values (operations descriptions, loss
# descriptions, additional-interest wording): 0 false positives at 40.
_CONTRACT_LANGUAGE_MIN_CHARS = 40

_POLICY_CONTRACT_LANGUAGE_RE = re.compile(
    r"\b(?:relieve us|our obligations?|our duty|we will (?:not )?pay|"
    r"under this policy|this insurance (?:does not|will not|shall)|"
    r"this policy (?:does not|will not|shall)|"
    r"the insurer(?:'s)? (?:right|obligation|duty)|"
    # Statutory fraud-warning language from the policy jacket. Live run
    # 2026-08-10: "A false statement knowingly made by the insured on the
    # application..." was stamped into Q5's CONDITION CORRECTED narrative —
    # a fraud-warning clause presented as the applicant's own history.
    r"false statement|knowingly (?:made|provides?|presents?)|"
    r"intent to defraud|misleading information|fraudulent claim|"
    # Cancellation / non-renewal CONDITIONS. The policy describing what the
    # insurer may do is not the applicant's history. Live 271-page run: Q5
    # ("any policy declined, cancelled or non-renewed?") came back "Y" off
    # this boilerplate, and a NON-RENEWAL reason box ticked on another run.
    r"we may cancel|we may not renew|if we cancel|"
    r"notice of (?:cancellation|nonrenewal|non-renewal)|"
    r"cancellation of this policy|"
    # SELECTED CONDITIONS headings, verbatim from the client's own dec. Each
    # of these opens a clause about how the CONTRACT operates, and each was
    # sitting in the document as quotable "evidence" for an applicant-history
    # question. "No person or organization has a right ... to sue us" even
    # reads as a negation, which is how a false "N" survived the gate.
    r"legal action against us|no person or organization|"
    r"no one may (?:bring|sue)|may bring a legal action|"
    r"concealment, misrepresentation|by accepting this policy|"
    r"maintenance of underlying insurance|at our option we may|"
    r"exclusions? (?:are|is) deleted|this coverage part is void|"
    r"we will pay for|our payment for loss|"
    r"coverage (?:is|shall be) (?:provided|afforded))\b", re.I
)

# A DEFINITION from the policy's own glossary. Live 271-page run: ACORD 125
# Q3 ("any exposure to flammables, explosives, chemicals?") came back "Y"
# explained by:
#     "pollutants" means any solid, liquid, gaseous or thermal irritant or
#     contaminant, including smoke, vapor, soot, fumes, acids, alkalis,
#     chemicals and waste.
# The word "chemicals" is in there, so presence checks pass and the evidence
# gate sees a real, quotable sentence. But a definition tells you what a WORD
# means in the contract - it can never be a statement about this applicant.
# Structural, not topical: a quoted term followed by "means", or the standard
# "as used in this policy" opener.
_POLICY_DEFINITION_RE = re.compile(
    r"(?:[\"“'][^\"“”']{1,60}[\"”']\s+means\b)"
    r"|(?:\bas used in this (?:policy|coverage part|endorsement)\b)"
    r"|(?:\bthe (?:following|words?|terms?)\s+[^.]{0,40}\bmeans?\b)"
    # 52-page trap run (2026-08-12): Q3 FLAMMABLES came back "Y" quoting the
    # POLLUTION EXCLUSION ("this insurance does not apply to ... chemicals")
    # and the XCU grant ("XCU exclusions are deleted. Coverage ... is
    # included"). What a policy COVERS or EXCLUDES is contract language, never
    # evidence of the APPLICANT's exposure - the client's own rule ("never
    # convert policy boilerplate into applicant-history answers"). These three
    # shapes are the exclusion/grant clauses themselves, not topic words.
    r"|(?:\bthis insurance does not apply\b)"
    r"|(?:\bexclusions? (?:are|is) deleted\b)"
    r"|(?:\bcoverage for [^.]{0,80}\bis (?:included|excluded|deleted)\b)"
    # Second 52p run (2026-08-13): Q2 SAFETY PROGRAM came back "Y" grounded on
    # the carrier's loss-control OFFER ("sample written safety manuals ... may
    # be requested ... does not obligate the policyholder"). An insurer
    # offering materials is contract machinery, not a statement that the
    # applicant operates anything.
    r"|(?:\bmay be requested\b)"
    r"|(?:\bdoes not obligate\b)"
    r"|(?:\bavailable to policyholders\b)",
    re.I,
)


def _quote_cites_contract_machinery(quote: Any) -> bool:
    """True when a grounding quote is the POLICY's own machinery rather than a
    statement about the applicant.

    Two signals: the definition/exclusion/offer clauses above, and - second
    52p run, 2026-08-13 - the word "exclusion(s)" ANYWHERE in the quote. Q3
    FLAMMABLES kept a "Y" on the quote '"POLLUTION EXCLUSION - FLAMMABLES,
    EXPLOSIVES AND CHEMICALS"' - the exclusion's own section HEADING, a bare
    noun phrase that dodges every clause pattern. An exclusion names what the
    policy does NOT cover; it can never evidence the applicant's exposure, in
    either direction. Real applicant statements do not contain the word.
    """
    text = str(quote or "")
    if _POLICY_DEFINITION_RE.search(text):
        return True
    return bool(re.search(r"\bexclusions?\b", text, re.I))


# ── THE POLICY AS THE SUBJECT OF ITS OWN SENTENCE ────────────────────────────
# STOP ADDING PHRASES TO THE THREE PATTERNS ABOVE. This is the fourth incident of
# one defect and the third attempted fix by enumeration:
#
#   2026-08-10  Q5 CONDITION CORRECTED  <- a fraud-warning clause
#   2026-08-12  Q3 FLAMMABLES           <- "this insurance does not apply to..."
#   2026-08-12  Q3 FLAMMABLES           <- '"pollutants" means ... chemicals'
#   2026-08-13  Q3 FLAMMABLES           <- "This exclusion applies even if the
#                                           claims against any insured allege
#                                           negligence or other wrongdoing in:"
#
# The last one walked around every pattern for one reason: it is phrased
# POSITIVELY ("this exclusion applies") and the whole list is phrased negatively
# ("does not apply", "will not pay", "is excluded under"). Adding a fifth
# alternative would close that sentence and leave the next phrasing open, which
# is the same whack-a-mole the 2026-08-08 `underwriting_consistency` arc had to
# abandon after three rounds. This one is a RULE instead.
#
# THE RULE: contract language is the CONTRACT acting as the grammatical subject.
# A demonstrative pointing at the document ("this exclusion", "these conditions")
# followed by an operative verb is the policy describing its own machinery,
# whatever the topic and whichever polarity it is written in.
#
# THE VERB LIST IS THE SAFETY, not the noun list. "This policy was cancelled for
# non-payment" is a legitimate Q5 answer about the applicant's history and MUST
# survive: the subject matches, but "was cancelled" is a past event, not an
# operative verb, so it does not match. Operative verbs are present-tense
# statements of how the contract works; event verbs are what happened to it.
_POLICY_SELF_SUBJECT_RE = re.compile(
    # "the following" joined the determiner set on run 9's live value: "The
    # following forms may be newly introduced to the policy: BROADENINGS OF
    # COVERAGE" - a forms-revision notice offered as proof of hold-harmless
    # agreements. Same grammatical role as "this/these": the policy pointing
    # at its own contents.
    r"^\W*(?:this|these|those|such|the\s+following)\s+"
    r"(?:\w+\s+){0,2}?"
    r"(?:polic(?:y|ies)|insurance|coverages?|coverage\s+part|exclusions?|"
    r"endorsements?|conditions?|provisions?|clauses?|forms?|agreements?|"
    r"limits?|deductibles?|sections?|paragraphs?|amendments?)\b"
    r"[^.]{0,60}?\b(?:applies|apply|does\s+not|do\s+not|shall|will\s+\w+|"
    r"means?|covers?|excludes?|extends?|includes?|provides?|"
    # Completing the VERB CLASS is not the enumeration this comment warns about.
    # These are present-tense contract-operation verbs, the same grammatical
    # category as the ones above; the banned habit is adding a past INCIDENT's
    # exact wording. "This endorsement changes the policy" was the one shape the
    # first cut missed, and it missed it for want of a verb, not a phrase.
    r"changes?|modif(?:y|ies)|amends?|replaces?|restricts?|adds?|"
    # "may be <introduced/attached/added>" - the forms-revision advisory voice
    # (run 9). Still contract OPERATION, not incident: it describes what the
    # contract may do to itself, never what happened to the applicant.
    r"may\s+be\s+\w+|"
    r"(?:is|are)\s+(?:amended|deleted|replaced|added|void|subject|changed))\b",
    re.I,
)


def _is_dangling_clause(text: str) -> bool:
    """A sentence cut off at a colon that introduces a list which is not there.

    Independent of vocabulary, and it is what the 2026-08-13 value actually looks
    like: `"...allege negligence or other wrongdoing in:"`. A clause that ends by
    promising a list and delivers nothing answered no question - the model copied
    a fragment out of a policy form's indented sub-clause. A genuine answer that
    happens to use a colon ("Safety program includes: manual, meetings") has text
    after it, and a complete sentence has a full stop somewhere.
    """
    t = (text or "").strip()
    return t.endswith(":") and "." not in t


_ROW_SUFFIX_STRIP_RE = re.compile(r"_[A-N]$")

# Counts whose subject is asserted to EXIST by the very box they sit in, so zero
# is not a quantity - it is the model's way of writing "the document doesn't say".
# An LLC has members by definition; that is what the letters stand for. Kept as a
# named tuple of (leaf pattern, why) rather than a bare regex so the next entry
# has to justify itself: a count that CAN legitimately be zero (losses, claims,
# vehicles) must never be added here.
_NONZERO_COUNT_FIELDS = (
    (re.compile(r"MemberManagerCount$"),
     "a limited liability company cannot have zero members or managers"),
    # Live 2026-08-13: ACORD 125 LOSS HISTORY printed "FOR THE LAST 0 YEARS".
    # ACORD's own tooltip is "the number of years of loss information required by
    # the insurer" - a REQUEST for a period, and zero years is not a period.
    #
    # `LossHistory_TotalLossAmount` is DELIBERATELY NOT HERE and must never be
    # added: zero losses is a real, common, correct answer, and this package's
    # own ground truth says "no known losses in the past five years". Deleting a
    # true $0 would be the opposite of what these guards are for. That
    # distinction is why this table has two entries and a test forbidding
    # careless additions.
    (re.compile(r"LossHistory_InformationYearCount$"),
     "a loss-history period of zero years is a request for nothing"),
)


def _rejects_impossible_count(field_name: str, value: Any) -> bool:
    """True when a count field came back zero and zero cannot be true."""
    text = str(value if value is not None else "").strip()
    if not text:
        return False
    try:
        if float(text.replace(",", "")) != 0:
            return False
    except (TypeError, ValueError):
        return False
    base = _ROW_SUFFIX_STRIP_RE.sub("", field_name)
    return any(pat.search(base) for pat, _why in _NONZERO_COUNT_FIELDS)


def _second_claim_on_a_single_printed_value(
    field_name: str,
    mapped: dict,
    gpt_filled_set: set,
    dec_entries: Any,
) -> Optional[str]:
    """The field this one COPIED from, or None.

    THE DEFECT, twice on one form (2026-08-13 live run):
        Producer_PhoneNumber_A          303-996-7800   <- correct, Pass 1
        Producer_FaxNumber_A            303-996-7800   <- copied; no fax exists
        Policy_Payment_EstimatedTotalAmount_A  $10,663 <- correct, resolver
        Policy_Payment_DepositAmount_A         $10,663 <- copied; no deposit stated
    Both boxes have NO source anywhere in 271 pages, so gap fill reached for the
    nearest number of the right shape and filed it twice.

    WHY THIS IS NOT "same parent, different leaf, equal value". That rule was
    written first and thrown away: swept against all 17 real schemas it puts
    `GeneralLiability_BodilyInjury_EachOccurrenceLimitAmount` and
    `...AggregateLimitAmount` in scope, and those legitimately coincide (a $1M/$1M
    policy is ordinary). Same for `LossHistory_ClaimDate` / `_OccurrenceDate`,
    routinely the same day. 149 of 528 parents carry more than one amount/date
    leaf. That rule deletes real values.

    WHAT ACTUALLY SEPARATES THEM IS THE DOCUMENT, and Stage A's index is the first
    thing in this pipeline that can say so. A value the declarations pages print
    under exactly ONE label is one fact, and it cannot be the answer to two
    differently-named boxes. A $1,000,000 that is printed under BOTH "Each
    Occurrence Limit" and "Personal & Advertising Injury Limit" is two facts that
    happen to be equal, this returns None, and both stamps stand.

    No vocabulary, no topic matching, no opinion about what a fax is.

    Deliberately conservative in three further ways:
      * only a GAP-FILL value is ever blamed - if the other holder is also from
        gap fill we cannot say which one copied, so nothing moves;
      * identical LEAF names are exempt (`NamedInsured_FullName` and
        `Insured_FullName` are asking the same question in two sections and are
        supposed to agree);
      * no index, no entries, no ruling. Degrades to today's behaviour.
    """
    if field_name not in gpt_filled_set or not isinstance(dec_entries, list):
        return None
    value = _normalize_for_search(str(mapped.get(field_name) or ""))
    if not value:
        return None
    # How many DISTINCT labels did the declarations pages print this value under?
    labels = set()
    for item in dec_entries:
        if not isinstance(item, dict):
            continue
        if _normalize_for_search(str(item.get("value") or "")) == value:
            labels.add(_normalize_for_search(str(item.get("label") or "")))
    leaf = _ROW_SUFFIX_STRIP_RE.sub("", field_name).rsplit("_", 1)[-1]
    holder = None
    for other, other_val in mapped.items():
        if other == field_name or other in gpt_filled_set:
            continue
        if _normalize_for_search(str(other_val or "")) != value:
            continue
        if _ROW_SUFFIX_STRIP_RE.sub("", other).rsplit("_", 1)[-1] == leaf:
            continue                       # same question asked twice: allowed
        holder = other
        break
    if holder is None:
        return None
    if len(labels) != 1:
        # DECLINED, and it says why. Live 2026-08-13: the producer's phone was
        # still stamped in the FAX box and this guard passed on it silently, so
        # there was no way to tell a correct abstention from a missed catch
        # without the entries in hand. The interesting case is exactly this one -
        # a duplicate EXISTS and only the label test stopped us.
        #
        # `len(labels) == 0` means the declarations never printed the value, so
        # this guard has no standing. `> 1` means it is printed under several
        # labels, which is either label VARIANTS of one fact (the fax case, if
        # the dec pages say "Agent Phone" on one and "Producer Phone" on another)
        # or genuinely two facts that agree (a $1M/$1M GL policy). Those are not
        # separable without vocabulary, so it abstains - and now logs enough to
        # decide from real data whether the rule should be relaxed.
        logger.info(
            "single_printed_value DECLINED field=%s holder=%s value=%r - the "
            "declarations print this value under %d distinct label(s): %s",
            field_name, holder, str(mapped.get(field_name))[:40],
            len(labels), sorted(labels)[:4],
        )
        return None
    return holder


def _is_policy_contract_language(field_name: str, value: Any) -> bool:
    """True when a value is the POLICY describing how it operates, in a box that
    asks about the APPLICANT. Remarks fields are exempt - ACORD 101's overflow
    rows carry policy text by design."""
    if "Remark" in field_name:
        return False
    text = str(value or "").strip()
    if len(text) < _CONTRACT_LANGUAGE_MIN_CHARS:
        return False                       # too short to be a clause
    return bool(_POLICY_CONTRACT_LANGUAGE_RE.search(text)
                or _EXCLUSION_CLAUSE_RE.search(text)
                or _POLICY_DEFINITION_RE.search(text)
                or _POLICY_SELF_SUBJECT_RE.search(text)
                or _is_dangling_clause(text))


# ── Tooltip echo ─────────────────────────────────────────────────────────────
# The model answering a field by reading its own description back. Live run
# 2026-08-09: AdditionalInterest_FullName_B, whose tooltip is "The additional
# interest's full name. As used here, this is the name of the trust.", came back
# stamped "The Additional Interest's Full Name. As Used Here, This Is The Name Of
# The Trust." - our own prompt text, title-cased.
#
# THE THRESHOLD IS THE WHOLE SAFETY ARGUMENT. A 103,464-pair sweep (realistic
# values x every free-text field on all 17 forms) measured false positives at
# each length: 86 at 16 chars, 16 at 20, 14 at 25, and ZERO at 30. Below 30 this
# blanks legitimate answers like "Business Personal Property" and "Contractors
# equipment" that happen to appear in their own tooltip. Do not lower it.
_TOOLTIP_ECHO_MIN_CHARS = 30
_TOOLTIP_PREFIX_RE = re.compile(
    r"^\s*(?:enter|input|check|sign|select)\s+[a-z /()-]{0,24}:\s*", re.I)

# ── An ACORD tooltip has TWO halves, and only one of them is the question ────
# Measured 2026-08-12 against the client's ACORD 125, and it is the reason the
# check above both missed real echoes and deleted real answers:
#
#   "The subject(s) of insurance covered by this blanket.  Examples include
#    Building, Contents, or Combined Building and Contents."
#
# Everything before "Examples include" DEFINES the field - a value made of those
# words is the model restating the question. Everything after it NAMES VALID
# ANSWERS on ACORD's own authority - and the shipped substring check was
# blanking "Combined Building and Contents" on all four rows of ACORD 140's
# blanket summary for exactly that reason. Verified live: 4 real deletions today,
# 0 after this split.
#
# `if not` / `other than those` are the same shape without the word "example":
# an `..._OtherDescription` field's tooltip recites the enumerated boxes it is
# NOT for ("the risk location if not inside nor outside the city limits"), so
# "Inside" is an answer, not an echo.
_TOOLTIP_EXAMPLE_CUT_RE = re.compile(
    r"\b(?:examples?\s+(?:include|are|of)|e\.?g\.?|i\.?e\.?|such\s+as|for\s+example"
    r"|including|includes|other\s+than\s+those|if\s+not\b|when\s+it\s+is\s+other)\b",
    re.I,
)

# Leaf names that mean "tell me about THIS applicant, in your own words". A
# generic phrase from the question is never a real answer to one of these.
# Matched on the LEAF segment only: `AdditionalRemark_FormIdentifier_A` contains
# "Remark" but asks for a form NUMBER, and must not be treated as narrative.
_NARRATIVE_LEAF_TOKENS = ("description", "explanation", "narrative", "remark", "comment")

# The short path needs at least this many significant tokens. Every false
# positive the short path produced in testing was a SINGLE word ("Building" in
# `CommercialStructure_Building_SublocationDescription_A`, "Owner" in a
# BusinessOwners remark) - 19 of them, all one token. Requiring two removes every
# one. The cost is one of the client's four echoes ("subsidiary", one word), and
# that trade is deliberate: a missed echo is one stray word a broker deletes, a
# false positive is a real value silently deleted. Blank-over-wrong cuts BOTH
# ways and this is the side that protects the document.
_ECHO_SHORT_MIN_SIG_TOKENS = 2

# Per-token near-match, for spelling variants ONLY. ACORD writes "judgement";
# the model wrote "judgment", and exact matching let the echo through. The
# same-first-letter and length-delta prefilters keep this from matching
# genuinely different words (and make the sweep tractable).
_ECHO_FUZZ_MIN_LEN = 5
_ECHO_FUZZ_RATIO = 0.85

_ECHO_STOPWORDS = frozenset({
    "a", "an", "the", "of", "for", "to", "in", "on", "by", "or", "and", "is",
    "as", "this", "that", "with", "any", "which", "has", "have", "been", "be",
    "was", "from", "at", "it", "its", "if", "are", "were", "other", "others",
    "not", "nor", "than", "those",
})


def _echo_tokens(text: str) -> Tuple[str, ...]:
    return tuple(
        t for t in re.sub(r"[^a-z0-9]+", " ", (text or "").lower()).split() if t
    )


@lru_cache(maxsize=4096)
def _echo_definition_tokens(tooltip: str) -> Tuple[str, ...]:
    """Tokens of the tooltip's DEFINITION half - examples stripped."""
    body = _TOOLTIP_PREFIX_RE.sub("", tooltip or "")
    cut = _TOOLTIP_EXAMPLE_CUT_RE.search(body)
    if cut:
        body = body[: cut.start()]
    return _echo_tokens(body)


@lru_cache(maxsize=8192)
def _echo_field_name_tokens(field_name: str) -> Tuple[str, ...]:
    """Significant words of the field's own name (CamelCase split, row dropped)."""
    stem = _SCHED_ROW_RE.sub(r"\1", field_name or "") if field_name else ""
    stem = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", " ", stem).replace("_", " ")
    return tuple(t for t in _echo_tokens(stem) if t not in _ECHO_STOPWORDS)


@lru_cache(maxsize=8192)
def _echo_is_narrative_field(field_name: str) -> bool:
    leaf = _SCHED_ROW_RE.sub(r"\1", field_name or "").rsplit("_", 1)[-1].lower()
    return any(tok in leaf for tok in _NARRATIVE_LEAF_TOKENS)


@lru_cache(maxsize=8192)
def _echo_is_other_field(field_name: str) -> bool:
    """`..._OtherDescription` asks for the thing the enumerated boxes MISSED, so
    its tooltip necessarily recites those boxes. Never run the short path here."""
    leaf = _SCHED_ROW_RE.sub(r"\1", field_name or "").rsplit("_", 1)[-1].lower()
    return leaf.startswith("other")


@lru_cache(maxsize=1 << 16)
def _echo_near(a: str, b: str) -> bool:
    if a == b:
        return True
    if len(a) < _ECHO_FUZZ_MIN_LEN or len(b) < _ECHO_FUZZ_MIN_LEN:
        return False
    if abs(len(a) - len(b)) > 2 or a[0] != b[0]:
        return False
    return difflib.SequenceMatcher(None, a, b).ratio() >= _ECHO_FUZZ_RATIO


def _echo_significant(tokens: Tuple[str, ...]) -> List[str]:
    return [t for t in tokens if t not in _ECHO_STOPWORDS]


def _echo_all_tokens_present(value_toks, hay_toks) -> bool:
    """Every significant value token appears SOMEWHERE in the definition text.
    Order-free on purpose: the client's live echo transposed two words ("caused
    the policy NOT TO be written" vs ACORD's "TO NOT be written") and an
    exact-substring check missed it entirely."""
    sig = _echo_significant(value_toks)
    return bool(sig) and all(
        any(_echo_near(s, h) for h in hay_toks) for s in sig
    )


def _echo_contiguous_span(value_toks, hay_toks) -> bool:
    """Value appears as a contiguous run of the definition text."""
    n = len(value_toks)
    if not n or n > len(hay_toks):
        return False
    return any(
        all(_echo_near(value_toks[j], hay_toks[i + j]) for j in range(n))
        for i in range(len(hay_toks) - n + 1)
    )


# ── A policy date is not an event date ───────────────────────────────────────
# Client, on the live output: "The occurrence date 07/15/2025 is incorrect. That
# is the policy's effective date, not the date of a fire or safety-code
# violation." Their rule, verbatim:
#
#   "A policy effective date must never be repurposed as an occurrence, loss,
#    violation or incident date."
#
# 25 event-date fields across ACORD 125 (18), 131 (6) and 127 (1). The check is
# an EQUALITY test against the policy's own metadata dates - no topic matching,
# no guessing what the real date should be. A genuine violation that happened to
# occur exactly on the policy inception is vanishingly rare, and blank routes the
# question to the client, which is what the client asked for.
_EVENT_DATE_FIELD_RE = re.compile(
    r"(?:Occurrence|Loss|Violation|Incident|Claim|Resolve|Resolution|Indicted|"
    r"Convicted)Date|Date_?Of_?(?:Occurrence|Loss|Claim)", re.I
)
_POLICY_METADATA_DATE_FACTS = (
    "effective_date", "expiration_date",
    "umbrella_effective_date", "umbrella_expiration_date",
    "prior_effective_date", "prior_expiration_date",
)


def _is_event_date_field(field_name: str) -> bool:
    return bool(_EVENT_DATE_FIELD_RE.search(field_name))


def _normalized_date_key(value: Any) -> Optional[str]:
    """One comparable form for a date however it is written.

    Uses the shared `normalize_date` so "07/15/2025", "2025-07-15" and
    "July 15, 2025" all compare equal - a digits-only comparison is ORDER
    sensitive and would let an ISO-format copy of the policy date through.
    """
    raw = str(value or "").strip()
    if not raw:
        return None
    try:
        from services.normalization import normalize_date
        iso = normalize_date(raw)
        if iso:
            return str(iso)
    except Exception:                                     # noqa: BLE001
        pass
    digits = re.sub(r"[^0-9]", "", raw)
    return digits or None


def _policy_metadata_dates(facts: dict) -> set:
    """The policy's own dates, normalised, for equality comparison only."""
    out: set = set()
    for key in _POLICY_METADATA_DATE_FACTS:
        key_val = _normalized_date_key(_fv(facts, key))
        if key_val:
            out.add(key_val)
    return out


def _event_date_is_really_a_policy_date(field_name: str, value: Any, facts: dict) -> bool:
    """True when an event-date box holds one of the policy's own metadata dates."""
    if not _is_event_date_field(field_name):
        return False
    key = _normalized_date_key(value)
    return bool(key) and key in _policy_metadata_dates(facts)


def _is_tooltip_echo(value: Any, meta: Any, field_name: str = "",
                     allow_short: bool = False) -> bool:
    """True when a value is really this field's own description read back.

    TWO PATHS, and the split is what makes the aggressive one safe.

    PATH 1 (any field, any source, value >= _TOOLTIP_ECHO_MIN_CHARS):
        every significant word of the value already appears in the field's own
        DEFINITION text. Order-free, with per-token spelling tolerance. This
        replaces an exact-substring test that a two-word transposition defeated:
        the client's live ACORD 125 carried "...caused the policy NOT TO be
        written" against ACORD's "...caused the policy TO NOT be written", and
        the shipped check saw no match at all.

    PATH 2 (``allow_short``, narrative fields only, no length floor):
        the value is a contiguous phrase lifted from the definition text AND at
        least one of its words is in the field's OWN NAME. Catches the short
        label-echoes the 30-char floor was blind to - "parent company",
        "judgment or lien" - which is most of what the client actually saw.

    ``allow_short`` MUST be passed only for values this run's gap-fill model
    authored. A Pass 1 / alias value came from an extracted fact, and the short
    path is aggressive enough that letting it near a deterministically-resolved
    box would risk deleting real document data. Default off, so every existing
    caller keeps the conservative behaviour.

    Measured 2026-08-12 on the real schemas: catches 4 of the client's 5 live
    echoes (up from 1), with ZERO false positives across 428 answers ACORD
    itself names as valid in its own tooltips, 362,124 cross-applied
    field/answer pairs, and every value the pre-existing test suite pins. It
    also STOPS 4 real deletions the shipped check performs today (see
    _TOOLTIP_EXAMPLE_CUT_RE).
    """
    tooltip = (meta or {}).get("tu") if isinstance(meta, dict) else None
    if not tooltip:
        return False
    raw = re.sub(r"\s+", " ", str(value or "").strip()).strip(" .,:;")
    if not raw:
        return False
    value_toks = _echo_tokens(raw)
    def_toks = _echo_definition_tokens(tooltip)
    if not value_toks or not def_toks:
        return False

    if len(raw) >= _TOOLTIP_ECHO_MIN_CHARS and _echo_all_tokens_present(value_toks, def_toks):
        return True

    if (
        allow_short
        and _echo_is_narrative_field(field_name)
        and not _echo_is_other_field(field_name)
        and len(_echo_significant(value_toks)) >= _ECHO_SHORT_MIN_SIG_TOKENS
        and _echo_contiguous_span(value_toks, def_toks)
    ):
        name_toks = _echo_field_name_tokens(field_name)
        if any(any(_echo_near(v, n) for n in name_toks)
               for v in _echo_significant(value_toks)):
            return True
    return False


# ── A LABEL IS NOT A STATEMENT ───────────────────────────────────────────────
# The discriminator `_quote_restates_the_question` needs, and the reason its
# first implementation was destroying real answers.
#
# That check asked "are all the quote's significant words already in the
# question?". It cannot work alone, because a direct answer to a yes/no question
# is BY DEFINITION mostly the question's own words - and the one word that
# carries the whole meaning, "not", is a stopword and is discarded before the
# comparison. Measured 2026-08-12 against the real schemas: 39 of 256 genuine
# compliance questions (15%; ACORD 125 40%, ACORD 126 27%) had their canonical
# document evidence rejected, e.g. "The applicant does not have any
# subsidiaries." and "Subcontractors are required to carry coverage."
#
# A rejected "No" has NO fallback - `_evidence_supports` failing on a negative
# blanks the field outright, where a "Yes" can still survive on a paired
# explanation. So the damage landed on the majority case with no safety net.
#
# The real axis is STRUCTURAL. Both live culprits ("for non-payment of premium",
# "additional insured") are bare noun phrases: no subject, no finite verb, no
# assertion. Legitimate evidence is a complete predication. Verified 15/15
# separation across both populations - see test_quote_label_vs_statement.py.
#
# Deliberately no insurance vocabulary, so it holds for a carrier whose wording
# we have never seen (same rule as _window_authority).
_QUOTE_INTERROGATIVE_RE = re.compile(
    r"^\s*(?:does|do|did|is|are|was|were|has|have|had|will|would|can|could|"
    r"shall|should|may|might|must|any|who|what|when|where|why|how|which)\b",
    re.I,
)
# Finite-verb markers: explicit auxiliaries, plus the -s/-es/-ed inflections that
# make an English content word a predicate.
_QUOTE_AUX_RE = re.compile(
    r"\b(?:is|are|was|were|has|have|had|does|do|did|will|would|can|could|shall|"
    r"should|may|might|must|been|being)\b",
    re.I,
)
# Below this, there is not enough sentence to be an assertion about anybody.
_QUOTE_MIN_PREDICATION_TOKENS = 4
# An s/es-suffixed token hanging off one of these, or dangling at the end of
# the text, is a PLURAL NOUN in a title, not a verb. See the run-9 note below.
_NOT_A_VERB_NEIGHBOURS = frozenset({"of", "and", "or"})


def _quote_asserts_something(quote: Any) -> bool:
    """True when the quote is a STATEMENT, not a label lifted from the question.

    Three ways to fail, in order of how they actually occur:
      1. it IS the question - trailing "?" or opening auxiliary/wh-word;
      2. too few words to predicate anything;
      3. no finite verb at all - a bare noun phrase like "additional insured".

    TIGHTENED 2026-08-13 (run 9): the old fallback treated ANY >=3-letter word
    ending in ed/es/s as a predicate, so every plural noun was a fake verb and
    printed TITLES sailed through as "statements" - live, on one run:
        "WAIVER OF TRANSFER OF RIGHTS OF RECOVERY"   (rightS)   -> Q8 = Y
        "J. BLANKET ADDITIONAL INSUREDS"             (insuredS) -> Q9 = Y
        "NAMES OF INDIVIDUALS ERIN ROYAL"            (nameS)    -> Q9/Q10 = Y
    The separation that holds on real data is POSITION, not vocabulary: an
    English finite verb sits between its subject and its object ("the applicant
    TRANSPORTS hazardous materials"), while the title-noun hangs off an
    "of/and/or" chain or dangles at the very end. So a suffix-derived candidate
    only counts when it is not adjacent to of/and/or and not the final token.
    Explicit auxiliaries are untouched - a sentence with "is/are/does/..." is a
    sentence whatever else it contains.
    """
    text = str(quote or "").strip().strip('"“”‘’ ')
    if not text:
        return False
    if text.rstrip().endswith("?") or _QUOTE_INTERROGATIVE_RE.match(text):
        return False
    if len(re.findall(r"[A-Za-z]+", text)) < _QUOTE_MIN_PREDICATION_TOKENS:
        return False
    if _QUOTE_AUX_RE.search(text):
        return True
    tokens = [t.lower() for t in re.findall(r"[A-Za-z][\w'\-]*", text)]
    for i, tok in enumerate(tokens):
        if len(tok) < 3 or not re.search(r"(?:ed|es|s)$", tok):
            continue
        prev_tok = tokens[i - 1] if i else ""
        next_tok = tokens[i + 1] if i + 1 < len(tokens) else ""
        if prev_tok in _NOT_A_VERB_NEIGHBOURS or next_tok in ("of",):
            continue
        if i == len(tokens) - 1:
            continue
        return True
    return False


# ── A YES WHOSE DEPENDENT TABLE IS EMPTY ─────────────────────────────────────
# The owner's rule, verbatim (2026-08-13): "whenever there is a Y, there should
# be an explanation mandatory." The gate already guarantees that for the ~10
# questions per form paired with an `..._Explanation` field - a kept Yes gets
# the grounding quote written into the explanation. The hole was the UNPAIRED
# questions, whose explanation is a TABLE: on the live ACORD 127, the six
# unpaired questions were EXACTLY the six wrong Ys (not-solely-owned, >50%
# employees, modified equipment, ICC filings, convictions, fleet) - Y ticked,
# owner/conviction tables empty.
#
# THE PAIRING IS DERIVED, NOT HAND-LISTED, and the schema itself encodes
# ACORD's own convention: a question printed with "(no explanation needed)" is
# followed IMMEDIATELY by the next question in the schema (ABA, AAE, KAG -> 0
# dependents); a question that demands substantiation has its table sitting
# between itself and the next question (AAJ -> the VEH#/owner-name columns,
# AAG -> the equipment description/cost table, AAI -> the AccidentConviction_*
# columns). Verified against the real 127 schema before wiring.
#
# A Yes on a question with dependents, none of them filled, is the model
# asserting an exposure while its own form section says nothing about it -
# blank per the standing rule. A question with NO dependents is exempt: the
# form itself says no explanation is needed, and the hardened quote checks are
# the only bar it must clear.
# 20, not 14: ACORD 126's athletic-sponsorship block (Q13) runs to ~16 fields
# between its question and Q14, and the cap was silently excluding it from the
# orphan-dependent sweep - run 9 shipped "SEE ATTACHED SCHEDULE FOR LIMITS..."
# in EXTENT OF SPONSORSHIP under a blank Q13. The cap still guards a
# pathological schema; AAG's run is 6, the largest real section is ~16.
_YES_DEPS_MAX = 20
_QUESTION_CODE_FIELD_RE = re.compile(r"_Question_\w+Code_[A-N]$")


def _unpaired_question_deps(schema: dict, paired: dict,
                            include_paired: bool = False) -> Dict[str, tuple]:
    """{question field: dependent fields between it and the next question}.

    `include_paired=True` (the LATE orphan sweep only) also returns a PAIRED
    question's section, minus its explanation field. The default skip exists
    because the pairing owns the Yes-substantiation direction - but it never
    owned the ORPHAN direction, and run 9 proved the hole: ACORD 126 Q5's
    equipment table carried "840 CONTR. EQUIP. - LEASED OR RENTED FROM OTHERS"
    (a rating class line) with Q5 itself blank, unjudged, because Q5 has a
    paired explanation and was therefore invisible to the sweep.
    """
    names = list(schema)
    q_positions = [(i, n) for i, n in enumerate(names)
                   if _QUESTION_CODE_FIELD_RE.search(n)]
    out: Dict[str, tuple] = {}
    for pos, (i, q) in enumerate(q_positions):
        exclude = ()
        if q in paired:
            if not include_paired:
                continue               # the explanation pairing already owns it
            exclude = (paired[q],)     # Guard 5 owns the explanation itself
        if pos + 1 >= len(q_positions):
            continue                       # last question: unbounded, never judged
        j = q_positions[pos + 1][0]
        deps = tuple(n for n in names[i + 1:j]
                     if not _QUESTION_CODE_FIELD_RE.search(n)
                     and n not in exclude)
        if not deps or len(deps) > _YES_DEPS_MAX:
            continue
        # A run of NOTHING BUT /Btn checkboxes is a QUALIFIER set ("check all
        # that apply" - safety manual / meetings / OSHA), an optional
        # refinement whose coherence the qualifier machinery already owns. A
        # Yes does not owe it anything - the test corpus caught the first cut
        # blanking a genuinely-quoted safety-program Yes for having no
        # qualifier ticked. An explanation SECTION is a run that asks for at
        # least one text answer (an owner's name, a violation date).
        def _ft(n):
            meta = schema.get(n)
            return meta.get("ft") if isinstance(meta, dict) else None
        if all(_ft(n) == "/Btn" for n in deps):
            continue
        out[q] = deps
    return out


# ── A COVERAGE LINE off the declarations, offered as evidence ────────────────
# THE ROOT CAUSE BEHIND THE 2026-08-13 ACORD 127 Y/N FLOOD, named once instead
# of six times: the source document is a POLICY and the form asks about the
# RISK, so nearly every 127 box is a gap-fill guess whose only available
# "evidence" is coverage artifacts - and the gate verified that a quote EXISTS,
# never that it is a statement ABOUT THE APPLICANT rather than the policy
# describing its own coverage. Measured on the live form:
#
#   Q5 "any car modified?"        = Y  <- "Auto Elite Extension $250"
#   Q3 "exposure to chemicals?"   = Y  <- "Limited Pollution Coverage - Work
#                                          Sites $150"
#   Q9 "vehicles used by family?" = Y  <- "ERIN ROYAL" (a DOC endorsement name)
#
# An endorsement title with a premium is the carrier GRANTING coverage; it is
# never the applicant REPORTING a fact. Same principle as
# `_is_policy_contract_language`, extended from stamped VALUES to the EVIDENCE
# offered for Y/N answers - and per the standing evidence-gate rule it judges
# only the quote's OWN NATURE, never its topic against the question's.
#
# Two complementary tests, because one is not enough:
#   * `_quote_asserts_something` (above, C47) kills short titles - but its verb
#     heuristic reads "LimitED" as a predicate, so "Limited Pollution Coverage -
#     Work Sites" walks straight past it.
#   * THIS test is exact membership in the verified dec-page index: a text that
#     IS a recorded `label` (or `label value`) is the carrier's own printed
#     coverage line, whatever its grammar. Deterministic, zero vocabulary, and
#     the index already survived the verbatim gate so it cannot be hallucinated.
#
# Entry VALUES alone are deliberately NOT matched: "ORBIN CONTRACTING LLC" is an
# entry value, and a bare name is the legitimate answer format for questions
# like Q9's "if so, identify" - matching values would blank real answers.
def _dec_coverage_line_set(facts: dict) -> frozenset:
    """Normalized dec lines. Bare labels carry a marker prefix so the matcher
    can hold them to a DIFFERENT standard: a text that IS exactly a printed
    label ("Limited Pollution Coverage - Work Sites") is a field-name echo and
    needs no money tail - run 6's Q3 explanation was precisely that, the label
    with the $150 dropped. A label+value line still needs the money tail, which
    is what keeps "INSURED IS: LLC" and "Date of Issue: 07/16/2025" alive as
    legitimate evidence."""
    entries = (facts or {}).get("dec_page_entries")
    out: set = set()
    if isinstance(entries, list):
        for e in entries:
            if not isinstance(e, dict):
                continue
            lab = _normalize_for_search(str(e.get("label") or ""))
            val = _normalize_for_search(str(e.get("value") or ""))
            if lab:
                out.add(f"L\x00{lab}")
            if lab and val:
                out.add(f"{lab} {val}")
    out.discard("")
    out.discard("L\x00")
    return frozenset(out)


# A coverage line grants at a price; a fact line does not. "Auto Elite
# Extension $250" ends in money; "INSURED IS: LLC" and "Date of Issue:
# 07/16/2025" do not - and both of those are LEGITIMATE Yes evidence, pinned by
# test_a_quote_carrying_real_data_still_grounds_a_yes. The money tail is what
# keeps this check on the coverage-artifact side of that line.
_MONEY_TAIL_RE = re.compile(r"\$\s?[\d,]+(?:\.\d{2})?\s*$")

# A quote with no verb can still carry a DATA PAYLOAD - a digit or a
# label:value colon - and a payload is evidence even when nothing is
# grammatically predicated. "ERIN ROYAL" has neither.
_DATA_PAYLOAD_RE = re.compile(r"\d|:\s*\S")


# A row label glued onto the front of a coverage line ("Location 000: Limited
# Pollution Coverage - Work Sites $150") defeated exact membership on the run
# after the check shipped - predicted as the known partial coverage, now closed.
# The prefix vocabulary is `_ROW_LABEL_NAME_RE`'s, already tested.
_ROW_LABEL_PREFIX_RE = re.compile(
    r"^(?:location|loc|item|building|bldg|premises|prem|vehicle|veh|unit|"
    r"schedule|line|row|class)\s*#?\s*\d{1,4}\s*[:\-–]\s*", re.I)


def _is_dec_coverage_line(text: Any, dec_lines: frozenset) -> bool:
    """True when `text` IS a printed declarations COVERAGE line.

    Two standards, per _dec_coverage_line_set: an exact bare-LABEL echo needs
    nothing more (a label asserts nothing whatever its topic); a label+value
    line must carry the money tail that separates a coverage grant from a
    legitimate fact line like "INSURED IS: LLC".
    """
    if not dec_lines:
        return False
    raw = _ROW_LABEL_PREFIX_RE.sub("", str(text or "").strip())
    t = _normalize_for_search(_MONEY_TAIL_RE.sub("", raw).strip())
    if len(t) >= 8 and f"L\x00{t}" in dec_lines:
        return True
    if not _MONEY_TAIL_RE.search(raw):
        return False
    t = _normalize_for_search(raw)
    return len(t) >= 8 and t in dec_lines


# ── A SCHEDULED ITEM's name, offered as an applicant's answer ────────────────
# Q5 "any car modified / special equipment?" = Y, "explained" by CONTRACTORS
# EQUIPMENT $300 / $10,000 - the INLAND MARINE schedule's item name and limit,
# on two consecutive runs. The dec-line check could not see it because the
# entry itself was dropped at verification (the carrier truncates the item
# name differently per page). But the ITEM lives in the facts as a schedule
# row, and a value that IS a scheduled item's name is the policy's property
# list echoed back, never a statement about vehicle modifications. Equality on
# normalized names, against schedule rows we already hold - no vocabulary.
_ITEM_SCHEDULE_FACT_KEYS = ("inland_marine_items", "contractor_equipment")


def _is_item_schedule_echo(text: Any, facts: dict) -> bool:
    t = _ROW_LABEL_PREFIX_RE.sub("", str(text or "").strip())
    t = _MONEY_TAIL_RE.sub("", t).strip()          # "NAME $300" -> "NAME"
    norm = _normalize_for_search(t)
    if len(norm) < 8:
        return False
    for key in _ITEM_SCHEDULE_FACT_KEYS:
        rows = (facts or {}).get(key)
        if isinstance(rows, dict) and "value" in rows:
            rows = rows.get("value")
        if not isinstance(rows, list):
            continue
        for row in rows:
            name = row.get("name") or row.get("item") or row.get("description") \
                if isinstance(row, dict) else row
            if name and _normalize_for_search(str(name)) == norm:
                return True
    return False


# An IMPERATIVE addressed to the reader ("Please contact your agent to discuss
# any questions.") is an instruction, not a fact about anybody - it carries
# verbs, so the assertion test passes it, and it is prose, so nothing else
# catches it. Live Q8: hold-harmless = Y on exactly that sentence. Structural:
# the sentence's opening token is a request/directive, which no statement of an
# applicant's own operations ever leads with.
_QUOTE_CTA_RE = re.compile(
    r"^\s*(?:please\b|contact\b|call\b|refer\s+to\b|see\b|"
    r"visit\b|for\s+(?:questions|more\s+information|assistance)\b|"
    r"as\s+(?:shown|described|stated|listed|indicated|provided|set\s+forth)\b|"
    r"per\s+(?:the|item|form|schedule|endorsement)\b)", re.I)
# WIDENED 2026-08-13 from `see (your|the)` to a bare `see`. Run 8's ACORD 127
# stamped "SEE ITEM FOUR FOR HIRED OR BORROWED AUTOS" as the conviction TYPE
# under a fabricated Q14 "Y", and extraction put "SEE SCHEDULE FOR DED ." in
# `auto_deductible_collision`. Both are the same shape and neither was caught,
# because the two words after "see" happened not to be "your" or "the".
# A cross-reference tells the reader where to look; it is never itself a fact.


# ── POLICY WORDING OFFERED AS EVIDENCE ───────────────────────────────────────
# THE ROOT CAUSE BEHIND RUN 8's SURVIVING ACORD 127 YESES, and it is one cause,
# not three. The uploaded package is a POLICY: ~271 pages of contract wording,
# endorsements and definitions, of which ~30 are declarations. The form asks
# about the RISK. So the only text available to ground most Y/N answers is the
# contract talking about ITSELF - and every gate we had verified that a quote
# EXISTS, never that it is a STATEMENT OF FACT ABOUT THIS APPLICANT.
#
#   Q8 "any hold harmless agreements?"  = Y
#       <- "Additional insured for ongoing and completed operations; insurance
#          is primary and will not seek contribution; waiver of transfer of
#          rights of recovery against others TO US when agreed in writing."
#          - the blanket-AI/waiver ENDORSEMENT, i.e. what the carrier promises.
#   Q9 "any vehicles used by family members?" = Y
#       <- "Family member MEANS a person related TO YOU by blood, adoption,
#          marriage or civil union recognized under Colorado law..."
#          - the Colorado Changes endorsement's DEFINITIONS clause, verbatim.
#
# Neither was reachable by anything we had. `_POLICY_SELF_SUBJECT_RE` needs the
# sentence to OPEN with "this/these/such <policy noun>"; both of these open with
# their own subject. `_quote_asserts_something` passes them - they have finite
# verbs, they are grammatical sentences. `_is_dec_coverage_line` misses them -
# they are body wording, not a printed dec label. They are not artifacts, not
# echoes, not fragments. They are well-formed English sentences that simply are
# not about the applicant.
#
# TWO REGISTER TESTS, and register is the right axis because it is what actually
# separates the two documents that got merged into one text blob. Neither test
# looks at the quote's TOPIC against the question's - that heuristic has been
# tried and reverted three times in this codebase and is still banned.
#
# 1. A DEFINITION defines a word. It can never report that something happened.
#    "<term> means ...", "as used in this policy", "is defined as", "for the
#    purposes of this endorsement". Anchored near the START so an ordinary
#    sentence that merely contains "means" ("the applicant means to expand
#    next year") is not swept up.
#
# 2. CONTRACT-PARTY VOICE. A policy is written in the second person: the
#    insured is "you", the carrier is "we/us/our". A statement about the
#    applicant - on a dec page, an application, a broker narrative, an ACORD
#    form - is written in the THIRD person ("the applicant", "the insured",
#    the company's own name). Requiring the pronoun to sit in a contractual
#    frame ("to us", "we will", "you must", "your household") keeps this off
#    the one shape that could collide: a producer note using a casual "your".
#
# Applied to Y AND N alike, next to the two checks that already are, because
# the owner's rule is symmetric: "if we have conclusive evidence of either that
# says yes or no, only then stamp... if no conclusion, leave it blank."
# Contract wording concludes nothing in either direction.
_DEFINITION_CLAUSE_RE = re.compile(
    r"^\W*(?:[\"“]?[A-Za-z][\w'\-]*(?:\s+[\w'\-]+){0,4}[\"”]?\s+"
    r"(?:means|shall\s+mean|is\s+defined\s+as|are\s+defined\s+as|includes?\s+"
    r"but\s+is\s+not\s+limited\s+to)\b"
    r"|as\s+used\s+(?:in|throughout)\s+(?:this|the)\b"
    r"|for\s+(?:the\s+)?purposes?\s+of\s+(?:this|the)\b"
    r"|wherever\s+used\s+in\s+(?:this|the)\b)",
    re.I,
)
_CONTRACT_PARTY_VOICE_RE = re.compile(
    # The carrier speaking as "we/us/our"...
    r"\b(?:to|by|against|with|from|upon|owed\s+to|payable\s+to)\s+us\b"
    r"|\b(?:we|us|our)\s+(?:will|shall|do\s+not|does\s+not|agree|agrees|"
    r"pay|pays|cover|covers|insure|insures|have\s+no|may)\b"
    r"|\bour\s+(?:liability|obligation|option|behalf|consent|written)\b"
    # ...or addressing the insured as "you/your" in a contractual frame.
    r"|\byou\s+(?:must|shall|agree|agreed|are\s+(?:an?\s+)?insured|"
    r"will\s+be|may\s+not|must\s+not)\b"
    r"|\brelated\s+to\s+you\b"
    r"|\byour\s+(?:household|behalf|written\s+(?:request|consent)|"
    r"legal\s+(?:liability|obligation))\b",
    re.I,
)


# ISO forms print their defined terms IN QUOTATION MARKS - `"We" do not cover
# property that "you" lease or rent to others.` is how the policy itself
# renders on the page, and run 9 delivered exactly that as a Q4 "explanation".
# The quoted pronoun is practically a SIGNATURE of contract wording: no
# applicant, producer or broker writes "you" in quotes.
_QUOTED_PARTY_TERM_RE = re.compile(
    r'["“”]\s*(?:we|you|your|us|our|insured|named\s+insured)\s*["“”]', re.I)


def _is_contract_wording(text: Any) -> bool:
    """True when the text is the POLICY talking, not the applicant reporting.

    A definition clause, a sentence written in contract-party voice, a quoted
    defined term, or the policy as its own subject. All are properties of the
    sentence itself - no topic, no question, no keyword list about coverage
    subjects. See the block comment above for why this is the axis and why the
    alternatives were rejected.
    """
    s = str(text or "").strip().strip('"“”‘’ ')
    if not s:
        return False
    if _QUOTED_PARTY_TERM_RE.search(s):
        return True
    # The quote characters themselves defeat \b matching ('"We" do not' never
    # matches r"\bwe\s+do\b" with the closing quote in between), so the two
    # register regexes run on a de-quoted copy.
    bare = re.sub(r'["“”‘’]', "", s)
    return bool(_DEFINITION_CLAUSE_RE.match(bare)
                or _CONTRACT_PARTY_VOICE_RE.search(bare)
                or _POLICY_SELF_SUBJECT_RE.search(bare))


# A bare name lifted from a NAME-ONLY driver record. `_schedule_has_substance`
# already ruled that record "not a schedule" for the attachment box - a Drive
# Other Car individual, not a driver (C22, ERIN ROYAL). Run 6 spent the same
# name as the explanation for TWO Yeses: Q9 family use (debatable) and Q10 "does
# the applicant obtain MVR verifications?" (a name answers a PRACTICE question
# not at all). The record's own emptiness is the evidence standard: a name the
# document attaches nothing to can substantiate nothing.
def _is_name_only_record_echo(text: Any, facts: dict) -> bool:
    norm = _normalize_for_search(str(text or ""))
    if len(norm) < 6:
        return False
    rows = (facts or {}).get("auto_drivers")
    if isinstance(rows, dict) and "value" in rows:
        rows = rows.get("value")
    if not isinstance(rows, list):
        return False
    for row in rows:
        if not isinstance(row, dict):
            continue
        name = row.get("name")
        if not name or _normalize_for_search(str(name)) != norm:
            continue
        has_substance = any(
            k not in _SCHEDULE_IDENTITY_ONLY_KEYS
            and v not in (None, "", [], {}) and str(v).strip()
            for k, v in row.items()
        )
        if not has_substance:
            return True
    return False


# ── A PRICED LINE ITEM, recognised WITHOUT the dec index ─────────────────────
# THE SAME DEFECT, FIFTH APPEARANCE, and the reason is now clear. "Limited
# Pollution Coverage - Work Sites $150" has been caught before - but only by
# `_is_dec_coverage_line`, which is EXACT MEMBERSHIP in the verified dec-page
# index. That index captured 250 of an estimated 750 entries on the client's
# package, so whether this guard fires depends on whether extraction happened
# to record that particular line. On the run that produced ACORD 125 Q3
# ("ANY EXPOSURE TO FLAMMABLES, EXPLOSIVES, CHEMICALS?" = Y, explained by
# "Limited Pollution Coverage - Work Sites $150.") it had not, so the check was
# blind and the answer shipped.
#
# A guard that works only when an upstream sampling step got lucky is not a
# guard. This one reads the SHAPE instead, so it holds with no index at all:
#
#   a short noun phrase, terminated by a bare money amount, with no verb.
#
# That is what a priced schedule line looks like on every carrier's dec page -
# "Limited Pollution Coverage - Work Sites $150", "Auto Elite Extension $250",
# "General Liability Elite Extension $500" - and it is not what a statement
# about an applicant looks like. The carrier GRANTING a coverage is never the
# applicant REPORTING an exposure; that conflation is the oldest bug in this
# file (see the form-stamping-mention-vs-grant note).
#
# Guarded three ways so a real sentence cannot match: an auxiliary verb
# anywhere disqualifies it, more than `_PRICED_LINE_MAX_WORDS` words
# disqualifies it, and the amount must be the LAST thing on the line.
_PRICED_LINE_MAX_WORDS = 12
_PRICED_LINE_RE = re.compile(
    r"^[^.!?]{3,120}?\s\$\s?[\d,]+(?:\.\d{2})?\s*\.?$")


def _is_priced_coverage_line(text: Any) -> bool:
    s = str(text or "").strip().strip('"“”‘’ ')
    if not s or not _PRICED_LINE_RE.match(s):
        return False
    if len(re.findall(r"[A-Za-z]+", s)) > _PRICED_LINE_MAX_WORDS:
        return False
    # An auxiliary means somebody is asserting something ("the deductible IS
    # $1,000"), which is a sentence, not a printed line item.
    return not _QUOTE_AUX_RE.search(s)


def _is_coverage_artifact_text(text: Any, dec_lines: frozenset, facts: dict) -> bool:
    """The union: a printed coverage line, a scheduled item echo, a CTA, a
    name-only record's name, the policy's own contract wording, or the
    applicant's own address echoed back.

    `_is_line_of_business_name` is deliberately NOT in this union: Q4's
    other-insurance table is a DEPENDENT of Q4, and its line-of-business labels
    ("Commercial General Liability") are values the client explicitly asked
    for - the union is applied to dependent cells, so including the LOB test
    here would delete them. LOB names are enforced by the field-aware guard in
    the guard region instead, where the legitimate homes are allow-listed."""
    if (_is_dec_coverage_line(text, dec_lines)
            or _is_priced_coverage_line(text)
            or _is_item_schedule_echo(text, facts)
            or bool(_QUOTE_CTA_RE.match(str(text or "")))
            or _is_name_only_record_echo(text, facts)
            or _is_contract_wording(text)
            or _is_identity_address_echo(text, facts)
            or _is_applicant_attribute_echo(text, facts)):
        return True
    # ── THE COLON ESCAPE ─────────────────────────────────────────────────────
    # `_DATA_PAYLOAD_RE` exempts anything shaped "LABEL: value" from the
    # assertion test, because "INSURED IS: LLC" and "Date of Issue: 07/16/2025"
    # are legitimate evidence - they carry a real payload. Run 9 drove a truck
    # through it: ACORD 127 Q7 "do operations involve transporting hazardous
    # material?" = Y, evidenced by **"BUSINESS DESC: COMMERCIAL GENERAL
    # CONTRA"** - the truncated business description off the dec page, wearing
    # a label so it read as data.
    #
    # The label is not the evidence; the VALUE is. So strip a short leading
    # label and judge what is actually being offered. If the remainder is
    # itself an artifact - a printed coverage line, a scheduled item, an
    # identity echo, contract wording - the whole line is too.
    _s = str(text or "").strip()
    _m = re.match(r"^[^:]{1,40}:\s*(\S.*)$", _s, re.S)
    if _m:
        _tail = _m.group(1).strip()
        if _tail and _tail != _s and (
                _is_dec_coverage_line(_tail, dec_lines)
                or _is_item_schedule_echo(_tail, facts)
                or _is_name_only_record_echo(_tail, facts)
                or _is_contract_wording(_tail)
                or _is_identity_address_echo(_tail, facts)
                or _is_line_of_business_name(_tail)
                or _is_labelled_fact_echo(_tail, facts)
                or _is_applicant_attribute_echo(_tail, facts)):
            return True
    return False


# Scalar facts that DESCRIBE the applicant rather than report an event. A
# labelled line restating one of these ("BUSINESS DESC: COMMERCIAL GENERAL
# CONTRA") is the document repeating an attribute we already hold - it answers
# "who is this?", never "does this exposure exist?". Deliberately reached ONLY
# from the colon path above: a bare fact value can be a legitimate answer
# elsewhere (an owner's name, an address in an identify-the-party box), and
# blanking those would be the over-reach this codebase keeps having to revert.
_LABELLED_ECHO_FACT_KEYS = (
    "contractor_type", "operations_description", "applicant_name", "dba_name",
    "carrier_name", "producer_name", "entity_type", "state_of_operations",
    "policy_number", "premises_description", "gl_form_type",
)


def _is_labelled_fact_echo(text: Any, facts: dict) -> bool:
    needle = re.sub(r"[^a-z0-9]+", " ", str(text or "").lower()).strip()
    if not needle:
        return False
    for key in _LABELLED_ECHO_FACT_KEYS:
        val = _fv(facts, key)
        if not val or not isinstance(val, str):
            continue
        if re.sub(r"[^a-z0-9]+", " ", val.lower()).strip() == needle:
            return True
    return False


# ── The applicant's OWN ADDRESS offered as evidence ──────────────────────────
# Run 9, ACORD 126 Q7 "any parking facilities owned/rented?" = Y, explained by
# "4800 DAHLIA STREET D13, DENVER CO. 80216-3121" - the applicant's own
# premises address, verbatim off the dec page. An address locates the insured;
# it asserts nothing about parking, or anything else. It slipped every check
# because the digit payload exempted it from the assertion test.
#
# Format variants defeat string equality (the dec prints "STREET", the fact
# holds "ST #"), so the identity test is the DIGIT SKELETON: a verbless text
# whose every number (street number, unit, zip) appears in one of the
# applicant's own address facts IS that address, however the words are spelled.
# A real sentence that merely contains the address keeps its verb and passes.
_IDENTITY_ADDRESS_FACT_KEYS = (
    "physical_address", "mailing_address", "premises_address",
)


def _is_identity_address_echo(text: Any, facts: dict) -> bool:
    s = str(text or "").strip()
    if not s:
        return False
    digit_runs = re.findall(r"\d+", s)
    if len(digit_runs) < 2:
        return False
    if _quote_asserts_something(s):
        return False
    for key in _IDENTITY_ADDRESS_FACT_KEYS:
        val = _fv(facts, key)
        if not val:
            continue
        fact_digits = set(re.findall(r"\d+", str(val)))
        if fact_digits and all(d in fact_digits for d in digit_runs):
            return True
    return False


# ── The applicant's NAMEPLATE offered as evidence ────────────────────────────
# Live 2026-08-14 run 4, and the same string had already driven the colon
# escape once: ACORD 125 Q3 "any exposure to flammables?" = Y and Q6 "any past
# losses relating to abuse or molestation?" = Y, both carried by "BUSINESS
# DESC: COMMERCIAL GENERAL CONTRA" - the dec page's truncated business
# description - riding the EXPLANATION path (a Yes survives on a paired
# explanation, and the colon escape's tail checks knew coverage lines,
# schedule items, names and contract wording, but not THIS: the applicant's
# own attribute value). Who the applicant IS can never evidence what HAPPENED
# to them - the same reasoning as the address echo above, one attribute over.
#
# Equality-only against three identity facts, with a length floor of 8:
# "LLC" (entity type) stays legitimate evidence - short codes ARE answers
# (test_a_quote_carrying_real_data_still_grounds_a_yes) - while multi-word
# nameplates ("COMMERCIAL GENERAL CONTRA", "ORBIN CONTRACTING LLC") are
# caught. operations_description is deliberately EXCLUDED: the full
# classification text legitimately grounds subcontractor-related answers, and
# judging that would be the banned topic matching.
_IDENTITY_ATTRIBUTE_FACT_KEYS = ("applicant_name", "dba_name", "contractor_type")


def _is_applicant_attribute_echo(text: Any, facts: dict) -> bool:
    n = _normalize_for_search(str(text or ""))
    if len(n) < 8:
        return False
    for key in _IDENTITY_ATTRIBUTE_FACT_KEYS:
        v = _normalize_for_search(str(_fv(facts, key) or ""))
        if len(v) >= 8 and n == v:
            return True
    # The FACT keys jitter run-to-run (contractor_type has three competing
    # candidates on the live package, and the run that shipped this defect had
    # merged a different one, which is exactly how the labelled-fact echo went
    # blind). The verified INDEX does not jitter the same way: an entry the
    # extraction attributed to the APPLICANT is an identity attribute from the
    # dec header - who they are, where they sit, what they call themselves -
    # and can never evidence that an event happened. Same equality + length
    # floor, so "LLC" stays a legitimate short answer.
    entries = (facts or {}).get("dec_page_entries")
    if isinstance(entries, list):
        for e in entries:
            if not isinstance(e, dict):
                continue
            if str(e.get("owner") or "").strip().lower() != "applicant":
                continue
            v = _normalize_for_search(str(e.get("value") or ""))
            if len(v) >= 8 and n == v:
                return True
    return False


# ── A LINE-OF-BUSINESS NAME standing where a fact should be ──────────────────
# Run 9, ACORD 126 Products/Completed Operations table: PRODUCT = "Commercial
# Auto Liability", PRODUCT = "Commercial Inland Marine" - coverage LINES
# stamped as products the applicant supposedly manufactures, with the policy
# effective date as "time in market". A contractor with no products got a
# products schedule made of its own policy's coverage parts.
#
# This is a CLOSED, ENUMERABLE vocabulary - the standard commercial lines -
# exactly like the auto-symbols table: not topic matching, a fixed list. An
# LOB name is never a product, never a party, never equipment, never evidence.
# It IS legitimate in fields that ask for a line of business by name (the Q4
# other-insurance rows, loss-history LOB, prior-coverage columns) - those are
# allow-listed by field-name marker where this is enforced on stamped values.
_LOB_NAMES = frozenset({
    "commercial general liability", "general liability",
    "business auto", "commercial auto", "commercial auto liability",
    "commercial automobile", "automobile", "covered autos liability",
    "business owners", "businessowners",
    "commercial property", "property",
    "commercial inland marine", "inland marine",
    "umbrella", "commercial umbrella", "commercial liability umbrella",
    "excess liability", "umbrella excess liability",
    "workers compensation", "workers comp",
    "crime", "crime and fidelity", "commercial crime",
    "cyber and privacy", "cyber liability", "cyber",
    "boiler and machinery", "equipment breakdown",
    "garage and dealers", "liquor liability", "motor carrier", "truckers",
    "yacht", "fiduciary liability", "employee benefits liability",
    "professional liability", "errors and omissions", "garagekeepers",
})
_LOB_TRAILING_NOISE_RE = re.compile(
    r"\s+(?:coverage(?:\s+part)?|line|section|policy|declarations?)$")
# Boxes that legitimately hold a line-of-business NAME, by field-name marker.
# Swept against all 17 schemas in tests/test_run_20260813h.py: every field
# whose tooltip asks for a line of business matches one of these markers.
_LOB_FIELD_ALLOWED_RE = re.compile(
    r"LineOfBusiness|PriorCoverage|Underlying|OtherPolicy|PolicyType|"
    r"Category|CoverageDescription|CoverageCode|InsuranceType|"
    # ACORD 125's "COMPANY POLICY OR PROGRAM NAME" - the tooltip literally asks
    # for "the line of business or program name of the insurer". Found by the
    # all-schema sweep in test_run_20260813h, not by hand.
    r"Insurer_ProductDescription", re.I)
# A value that is nothing but a dollar amount.
_BARE_MONEY_VALUE_RE = re.compile(r"^\$?\s*\d[\d,]*(?:\.\d+)?$")


def _is_line_of_business_name(text: Any) -> bool:
    s = re.sub(r"[^a-z0-9 ]+", " ", str(text or "").lower())
    s = re.sub(r"\s+", " ", s).strip()
    if not s:
        return False
    s = _LOB_TRAILING_NOISE_RE.sub("", s)
    return s in _LOB_NAMES


# ── A question's QUALIFIER checkboxes ────────────────────────────────────────
# ACORD prints some Yes/No questions with a row of checkboxes that QUALIFY the
# Yes: Q2 "IS A FORMAL SAFETY PROGRAM IN OPERATION?" -> SAFETY MANUAL / SAFETY
# POSITION / MONTHLY MEETINGS / OSHA; Q5's cancellation reasons; ACORD 126/160's
# pool-features row. A qualifier ticked under a question that is NOT answered
# "Yes" is incoherent on its face - the 52-page trap run produced exactly that
# (SAFETY MANUAL ticked off "sample written safety manuals ... may be
# requested", with Q2 itself blank).
#
# The structural rule: the run of CONSECUTIVE /Btn fields immediately after a
# `_Question_<code>Code_` field, sharing one first name segment among
# themselves, is that question's qualifier set. AUDITED against all 17 real
# schemas (2026-08-12): the harvest finds exactly six runs - five genuine
# (125 safety program, 125 cancellation reasons, 126/160 pool features, 141
# audit-performed-by) and ONE false positive, ACORD 125's NATURE OF BUSINESS
# grid (`BusinessType_*` happens to follow a question). That grid is an
# independent section whose boxes Pass 1 derives from the is_contractor flag,
# so it is excluded BY NAME below - remove that exclusion and the Contractor
# checkbox gets blanked whenever the preceding unrelated question is blank.
# (The grid's fields are `BusinessInformation_BusinessType_*`; "BusinessType"
# is kept in the set as belt-and-braces for a schema that drops the prefix.)
_QUALIFIER_EXCLUDED_FIRST_SEGMENTS = frozenset({"BusinessInformation", "BusinessType"})


def _question_qualifier_indicators(schema: dict) -> Dict[str, List[str]]:
    """{question field -> [its qualifier /Btn fields]}, per the audited rule."""
    keys = list(schema)
    out: Dict[str, List[str]] = {}
    for i, k in enumerate(keys):
        if not _QUESTION_CODE_RE.search(k):
            continue
        run: List[str] = []
        for nxt in keys[i + 1:]:
            meta = schema.get(nxt)
            if isinstance(meta, dict) and meta.get("ft") == "/Btn":
                run.append(nxt)
            else:
                break
        if len(run) < 2:
            continue
        first_segments = {f.split("_", 1)[0] for f in run}
        if len(first_segments) != 1:
            continue
        if first_segments & _QUALIFIER_EXCLUDED_FIRST_SEGMENTS:
            continue
        out[k] = run
    return out


def _final_yn_coherence(mapped: dict, schema: dict, form_id: str,
                        gpt_filled_set: set) -> None:
    """THE LAST word on Yes/No coherence - runs after EVERY other guard.

    Two invariants, both owner-reported from live PDFs:

    1. NO NAKED YES. Guard 9 enforces this inside _enforce_post_fill_guards,
       but LATER guards (measured: the policy-contract-language guard at the
       end of map_facts_to_form) can blank the explanation the evidence gate
       wrote, recreating the naked Yes AFTER Guard 9 already passed. Whatever
       ate the explanation, an affirmative whose ACORD-paired explanation ends
       up empty cannot stand.

    2. NO ORPHAN QUALIFIER. A qualifier checkbox (see
       _question_qualifier_indicators) may only stand when its parent question
       is affirmative. Scoped to AI-AUTHORED ticks: a deterministic Pass-1
       value (the flag-derived business-type boxes, an alias-stamped
       indicator) is never touched here.

    Mutates `mapped`; never raises - a coherence sweep must not break a fill.
    """
    try:
        pairs = _question_explanation_pairs(schema)
        for q_field, exp_field in pairs.items():
            if str(mapped.get(q_field) or "").strip().lower() not in _AFFIRMATIVE_VALUES:
                continue
            if str(mapped.get(exp_field) or "").strip():
                continue
            mapped[q_field] = None
            gpt_filled_set.discard(q_field)
            logger.warning(
                "final_yn_coherence NAKED_YES_BLANKED question=%s explanation=%s "
                "form=%s - a later guard emptied the explanation after Guard 9 "
                "passed; the affirmative cannot stand alone",
                q_field, exp_field, form_id or "unknown",
            )
        for q_field, indicators in _question_qualifier_indicators(schema).items():
            if str(mapped.get(q_field) or "").strip().lower() in _AFFIRMATIVE_VALUES:
                continue
            for ind in indicators:
                if ind not in gpt_filled_set:
                    continue                   # deterministic ticks are not ours
                if str(mapped.get(ind) or "").strip().lower() not in _AFFIRMATIVE_VALUES:
                    continue
                mapped[ind] = None
                gpt_filled_set.discard(ind)
                logger.warning(
                    "final_yn_coherence ORPHAN_QUALIFIER_BLANKED indicator=%s "
                    "question=%s form=%s - a qualifier cannot stand under a "
                    "question that is not answered Yes",
                    ind, q_field, form_id or "unknown",
                )
                # Its paired description goes with it (an OtherDescription
                # beside an unticked Other box claims a program nobody named).
                _desc = pairs.get(ind)
                if _desc and mapped.get(_desc):
                    mapped[_desc] = None
                    gpt_filled_set.discard(_desc)
    except Exception as exc:                              # noqa: BLE001
        logger.warning("final_yn_coherence skipped (form=%s): %s", form_id, exc)


def _quote_expresses_negative(quote: str) -> bool:
    """True when the quote contains an explicit negation cue - the hallmark of
    a real 'the document says NO' statement, as opposed to a positive
    descriptive sentence the model grabbed at random.

    Identifier labels ("Policy No. BBC7263") are stripped first: "No." there is
    the abbreviation for NUMBER, not a denial. See `_NUMBER_ABBREV_RE`."""
    return bool(_NEGATION_CUE_RE.search(
        _strip_number_abbreviations(quote or "").lower()))


# ── Dedicated umbrella-period pass (ACORD 131 only) ───────────────────────────
# See the call site in map_facts_to_form for why this exists: the main
# extraction prompt asks for umbrella_effective_date/umbrella_expiration_date
# but has been observed to drop them under real-document load even with an
# explicit instruction, while correctly reading the same dates into a
# neighboring field. One small, standalone question — not a Yes/No, so it does
# not reuse the compliance pass's evidence-quote machinery — mirrors that
# pass's core idea instead: pull the one thing the crowded prompt keeps
# missing OUT of the crowd and ask it alone.
# Document chars per umbrella-probe CALL. This is a chunk size, NOT a ceiling on
# how much of the document the probe reads — it reads all of it (C14).
#
# It used to be `raw_text[:60_000]`, i.e. a hard truncation, and that was the
# worst possible place for one. This probe is a FALLBACK: it fires only when the
# main extraction pass already failed to find the umbrella's period. Truncating
# it to the first 60,000 chars pointed the backup at the opening ~9% of the
# package — the part we already know did not yield the dates — so on any document
# larger than that the backup read strictly less than the thing it was backing
# up, and umbrella dates came back blank on ACORD 125/131/25.
#
# Sized to extraction's measured-good regime (~14k tokens/call), not to the
# gap-fill call budget. A two-key question does not need 170k tokens of context,
# and improving-ll.md C21 measured instruction-following degrading up there.
# Chunks are scanned in order and the loop stops as soon as both dates are found,
# so the overwhelmingly common case — dates on a declarations page near the front
# — still costs exactly ONE call, the same as before.
_UMBRELLA_PERIOD_CHUNK_CHARS = int(os.getenv("UMBRELLA_PERIOD_CHUNK_CHARS", "56000"))

_UMBRELLA_PERIOD_SYSTEM_PROMPT = (
    "You are an expert commercial-insurance underwriter reading an insurance application or "
    "declarations document. The document may describe an UMBRELLA or EXCESS LIABILITY policy "
    "that sits above (attaches over) the applicant's other policies (General Liability, Auto, "
    "Workers Compensation). That umbrella/excess policy commonly has ITS OWN effective and "
    "expiration date, separate from the underlying GL/Auto/WC policy period — sometimes the same "
    "dates, often different.\n\n"
    "Find the umbrella/excess policy's OWN stated effective date and expiration date, if the "
    "document states them. Do NOT use the underlying GL/Auto/WC policy's dates unless the "
    "document explicitly says the umbrella shares that exact period. Do NOT use a retroactive "
    "date (a claims-made trigger date) as the effective date — those are a different concept. "
    "If the document does not clearly state the umbrella's own period, return null for that field "
    "rather than guessing.\n\n"
    "Return JSON with exactly two keys: \"umbrella_effective_date\" and "
    "\"umbrella_expiration_date\", each a date string (e.g. \"07/15/2025\") or null."
)

_UMBRELLA_PERIOD_RESPONSE_FORMAT = {
    "type": "json_schema",
    "json_schema": {
        "name": "umbrella_period",
        "schema": {
            "type": "object",
            "properties": {
                "umbrella_effective_date":  {"type": ["string", "null"]},
                "umbrella_expiration_date": {"type": ["string", "null"]},
            },
            "required": ["umbrella_effective_date", "umbrella_expiration_date"],
            "additionalProperties": False,
        },
    },
}


def _fetch_umbrella_period_sync(raw_text: str) -> Optional[dict]:
    """Synchronous implementation of the umbrella-period probe.

    This is the single source of truth for the call. It is fully synchronous and
    uses the SYNC OpenAI client so it is safe to invoke directly from a
    ThreadPoolExecutor worker — the previous code reached this logic via
    `_run_coro_sync(...)`, i.e. `asyncio.run()` on a worker thread sharing the
    module-level AsyncOpenAI client, which is the same cross-event-loop deadlock
    documented on `_get_openai_form_fill_client_sync()`.

    The WHOLE document is scanned, chunked against
    `_UMBRELLA_PERIOD_CHUNK_CHARS` — see the note on that constant for why the
    previous `raw_text[:60_000]` was the worst possible place for a truncation.
    Chunks are read in order and the scan stops the moment both dates are known,
    so a normal submission with its umbrella dec page near the front still costs
    exactly one call. A chunk that fails is skipped, not fatal: the remaining
    chunks may still hold the answer, and a partial answer beats none.

    Returns {"umbrella_effective_date": ..., "umbrella_expiration_date": ...}
    (either value may be None) or None on any failure — advisory only, never
    raises past this function so a call-site failure can't block form generation.
    """
    try:
        _client = _get_openai_form_fill_client_sync()
    except RuntimeError as exc:
        logger.warning("gpt_fill UMBRELLA_PERIOD: %s — skipping", exc)
        return None

    chunks = _split_text_on_boundaries(raw_text or "", _UMBRELLA_PERIOD_CHUNK_CHARS)
    if len(chunks) > 1:
        logger.info(
            "gpt_fill UMBRELLA_PERIOD: document split into %d chunk(s) (%d chars) — "
            "scanning in order until both dates are found",
            len(chunks), len(raw_text or ""),
        )

    found: Dict[str, Optional[str]] = {
        "umbrella_effective_date":  None,
        "umbrella_expiration_date": None,
    }
    any_call_succeeded = False

    for _ci, _chunk in enumerate(chunks):
        user_msg = f"=== DOCUMENT TEXT ===\n{_chunk}"
        try:
            from utils.llm_limiter import llm_slot_sync
            with llm_slot_sync():
                resp = _client.chat.completions.create(
                    model=GPT_MODEL,
                    messages=[
                        {"role": "system", "content": _UMBRELLA_PERIOD_SYSTEM_PROMPT},
                        {"role": "user",   "content": user_msg},
                    ],
                    temperature=GPT_TEMPERATURE,
                    response_format=_UMBRELLA_PERIOD_RESPONSE_FORMAT,
                    max_completion_tokens=500,
                )
            _log_llm_spend("umbrella", "-", resp)
            content = resp.choices[0].message.content or ""
            result = json.loads(content)
        except Exception as exc:                          # noqa: BLE001 — advisory only
            # One bad chunk must not abandon the rest of the document. That is
            # the difference between "the answer is on page 200 and we stopped
            # at page 40" and "the answer is on page 200 and we found it".
            logger.warning(
                "gpt_fill UMBRELLA_PERIOD: chunk %d/%d failed — %s",
                _ci + 1, len(chunks), exc,
            )
            continue

        if not isinstance(result, dict):
            continue
        any_call_succeeded = True
        # First chunk that states a date wins it. The two dates are resolved
        # independently: a package can state the umbrella's effective date on its
        # dec page and its expiration only in a later endorsement.
        for _k in found:
            if found[_k] is None and (result.get(_k) or None):
                found[_k] = result[_k]
        if all(found.values()):
            break

    if not any_call_succeeded:
        return None
    return dict(found)


# ── THE EVIDENCE JUDGE ───────────────────────────────────────────────────────
# WHY THIS EXISTS, and why it is an LLM call in a codebase that prefers
# deterministic rules everywhere else.
#
# The owner's rule for every Yes/No box is: "if we have conclusive evidence of
# either that says yes or no, only then stamp; if no conclusion, leave it
# blank." That is a question about IMPLICATION - does this sentence support
# this answer to this question - and implication is not a property of
# vocabulary. Sixteen stacked regexes were approximating it, and the measured
# result was that each fix relocated the failure rather than closing it:
#
#   * `_NEGATION_CUE_RE` admitted 4 of 4 dec-page identifier lines as proof of
#     "No" (`Policy No. BBC7263`) and rejected 3 of 3 genuine implied "No"s
#     ("All vehicles are owned by the applicant" answering "any vehicles NOT
#     solely owned?"). The word-list fix above closes the first half; no word
#     list can close the second.
#   * `_quote_asserts_something` + `_DATA_PAYLOAD_RE` make "contains a digit or
#     a colon" the operative definition of a statement, so "Symbol 07" counts
#     as evidence and "Roofing, gutter and siding installation on residential
#     structures" does not.
#
# So the deterministic layer keeps doing the ONE thing it is genuinely good at
# - proving a quote is really in the document, and recognising the structural
# artifacts (coverage lines, contract wording, nameplates) that are never
# applicant facts - and this judges the one thing it cannot.
#
# THREE PROPERTIES THAT MAKE THIS SAFE TO ADD:
#   1. FAIL-SAFE. Any failure - no API key, a timeout, a malformed reply, an
#      unparseable verdict - returns "no opinion" for that field and the
#      deterministic decision stands unchanged. Offline (every test, every CI
#      run) it is a no-op by construction, which is why the suite's existing
#      expectations are untouched.
#   2. BOUNDED. Only fields that already carry an answer AND a quote are
#      judged, batched `_JUDGE_BATCH` at a time: ~100-300 fields on a real
#      package, so ~10-15 small calls. It reads no document text.
#   3. SYMMETRIC. It can reject a kept answer OR rescue a blanked one, so it
#      corrects in both directions instead of only tightening.
#
# Set EVIDENCE_JUDGE=0 to disable and keep the pure-deterministic gate.
_EVIDENCE_JUDGE_ENABLED = os.getenv(
    "EVIDENCE_JUDGE", "1").strip().lower() not in ("0", "false", "no")
_JUDGE_BATCH = int(os.getenv("EVIDENCE_JUDGE_BATCH", "20"))
_JUDGE_MAX_FIELDS = int(os.getenv("EVIDENCE_JUDGE_MAX_FIELDS", "400"))

_JUDGE_SYSTEM_PROMPT = (
    "You verify insurance form answers against their cited evidence. You judge "
    "ONE thing: does the quoted sentence, read plainly, support that answer to "
    "that question?\n\n"
    "Return JSON: {\"verdicts\": [{\"id\": string, \"supports\": true|false}]}\n\n"
    "RULES\n"
    "1. Judge SUPPORT, not topic overlap. A quote may use none of the "
    "question's words and still answer it: \"All vehicles are owned by the "
    "applicant\" SUPPORTS \"No\" to \"are any vehicles not solely owned by the "
    "applicant?\". That is the whole reason you are here.\n"
    "2. A quote about a DIFFERENT subject does not support the answer, however "
    "well it matches in tone. \"No roofing is performed\" does not answer a "
    "question about hazardous materials.\n"
    "3. The POLICY describing its own coverage, exclusions, definitions or "
    "premiums is never evidence about the applicant's operations or history. A "
    "printed coverage line, a limit, an endorsement title or a premium is what "
    "the insurer promises, not what the applicant does or has experienced.\n"
    "4. An identifier, label or nameplate (a policy number, an address, the "
    "business description, a person's name) states who or what something is. It "
    "can never establish that an event happened or an exposure exists.\n"
    "5. For a coverage-existence question (\"is this line of business on the "
    "policy?\"), a printed declarations line granting that coverage DOES "
    "support \"Yes\" - that is exactly the right evidence for that question.\n"
    "6. When the quote leaves the answer genuinely undecided, return false. "
    "Blank is the correct outcome of insufficient evidence; a wrong answer on "
    "an insurance application is not.\n"
    "7. Judge every id you are given, and return no ids you were not given."
)

_JUDGE_RESPONSE_FORMAT = {
    "type": "json_schema",
    "json_schema": {
        "name": "evidence_verdicts",
        "schema": {
            "type": "object",
            "properties": {
                "verdicts": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "id": {"type": "string"},
                            "supports": {"type": "boolean"},
                        },
                        "required": ["id", "supports"],
                        "additionalProperties": False,
                    },
                },
            },
            "required": ["verdicts"],
            "additionalProperties": False,
        },
        "strict": True,
    },
}


def _judge_evidence_batch(items: List[dict], form_id: str = "") -> Dict[str, bool]:
    """Ask whether each quote supports its answer. Never raises.

    `items`: [{"id", "question", "answer", "quote"}]. Returns {id: bool} for
    the ids the model actually judged - an id absent from the result means NO
    OPINION, and every caller must leave the deterministic decision alone for
    those. That asymmetry is deliberate: silence must never be read as a
    verdict, or a failed call would blank a form.
    """
    if not _EVIDENCE_JUDGE_ENABLED or not items:
        return {}
    items = items[:_JUDGE_MAX_FIELDS]
    try:
        _client = _get_openai_form_fill_client_sync()
    except Exception as exc:                               # noqa: BLE001
        logger.info("evidence_judge: unavailable (%s) - deterministic gate stands", exc)
        return {}
    out: Dict[str, bool] = {}
    from utils.llm_limiter import llm_slot_sync
    for _start in range(0, len(items), max(1, _JUDGE_BATCH)):
        _slice = items[_start:_start + max(1, _JUDGE_BATCH)]
        lines = []
        for it in _slice:
            lines.append(
                f"- id: {it['id']}\n"
                f"  question: {str(it.get('question') or '')[:300]}\n"
                f"  answer: {str(it.get('answer') or '')[:20]}\n"
                f"  quote: {str(it.get('quote') or '')[:400]}"
            )
        user_msg = "Judge each item.\n\n" + "\n".join(lines)
        try:
            with llm_slot_sync():
                resp = _client.chat.completions.create(
                    model=GPT_MODEL,
                    messages=[
                        {"role": "system", "content": _JUDGE_SYSTEM_PROMPT},
                        {"role": "user",   "content": user_msg},
                    ],
                    temperature=GPT_TEMPERATURE,
                    response_format=_JUDGE_RESPONSE_FORMAT,
                    max_completion_tokens=2000,
                )
            _log_llm_spend("evidence_judge", form_id or "-", resp)
            parsed = json.loads(resp.choices[0].message.content or "{}")
        except Exception as exc:                           # noqa: BLE001
            logger.warning("evidence_judge: batch failed (%s) - those fields keep "
                           "their deterministic decision", exc)
            continue
        _ids = {it["id"] for it in _slice}
        for v in (parsed.get("verdicts") or []):
            if isinstance(v, dict) and v.get("id") in _ids \
                    and isinstance(v.get("supports"), bool):
                out[str(v["id"])] = bool(v["supports"])
    return out


async def _fetch_umbrella_period(raw_text: str) -> Optional[dict]:
    """Async wrapper kept for the awaiting caller (extraction_pipeline).

    Delegates to the sync implementation on a worker thread, so there is exactly
    ONE request code path and no AsyncOpenAI client is ever shared across event
    loops. Offloading also keeps the blocking semaphore acquire off the loop.
    """
    import asyncio as _asyncio
    return await _asyncio.get_event_loop().run_in_executor(
        None, _fetch_umbrella_period_sync, raw_text,
    )


def map_facts_to_form(
    facts: dict,
    schema: dict,
    form_id: str = "",
    raw_text: str = "",
    pre_filled_gpt: Optional[Dict[str, Any]] = None,
    guard_report: Optional[list] = None,
) -> Tuple[dict, dict]:
    """Two-stage form fill — cache-free.

    Pass 1 (deterministic, no LLM): schedule row routing, address decomposition,
    indicator derivation from flags, and direct fact-key mappings via
    `_ACORD_FIELD_RULES`. Non-fillable fields (signatures, premiums, carrier-
    computed codes) are skipped entirely.

    Pass 2 (LLM Call 2): every remaining field is sent to GPT together with the
    complete extracted raw document text and the form schema (field name +
    tooltip + type + required flag). Chunked automatically when the prompt
    exceeds the per-call character budget.

    Confidence labels feed the highlight layer:
      - "filled"           → no highlight (deterministic OR GPT verbatim from raw text)
      - "low_confidence"   → pink (GPT inferred — not copied verbatim from doc)
      - "missing_required" → yellow (required + empty + fillable)
      - "missing_required_gate" → yellow (form-specific completeness gate, e.g. ACORD 140
        COPE fields via apply_acord140_missing_field_highlights — also feeds the download
        hard-block in field_qa.py, unlike plain "missing_required")
    """
    _set_schema_context(schema)
    if not schema:
        return {}, {}

    mapped     = {}
    unmatched  = {}
    confidence = {}

    # Fields filled by Pass 1 (deterministic rules) — always treated as "filled"
    # in the highlight pass. Schedule rows that resolved to N/A are also marked
    # here as authoritative blanks so they don't waste GPT prompt budget.
    _deterministic_filled: set = set()

    cnt_deterministic = 0
    cnt_nonfillable   = 0
    cnt_blank_sched   = 0

    # Lazily-built normalized haystack for the LOB-premium presence backstop in
    # the loop below. One-element list so the loop body can fill it on first
    # use; normalizing the full document costs one pass and only happens when a
    # form actually has a resolvable LOB premium.
    _lob_premium_hay: list = [None]

    # ── ACORD 131 / 25 dedicated umbrella-period pass ─────────────────────────
    # umbrella_effective_date / umbrella_expiration_date are asked for in the
    # main extraction prompt (extraction_service.py _EXTRACT_SCHEMA + RULE 1),
    # but that prompt carries ~150 other fields and has been observed TWICE on
    # real documents to correctly read the umbrella's stated period into an
    # adjacent field (ExcessUmbrella_*RetroactiveDate_A) while never populating
    # these two facts at all — a crowded-prompt miss, not a missing instruction.
    # The gap-fill stage's small, focused per-field batches DO reliably read
    # ACORD-131-shaped dates from the same document (same observed runs), so
    # this pass mirrors that success: one small, standalone question asked only
    # when facts are silent on the umbrella's own period — never overrides a
    # genuine extraction hit, never fires on any other form, never blocks
    # generation if it fails (falls through to the existing GL-date fallback
    # in the per-form overrides below).
    #
    # ACORD 25 (Certificate of Liability Insurance) ALSO has a genuinely
    # distinct Policy_ExcessLiability_EffectiveDate_A/ExpirationDate_A pair —
    # confirmed against its real schema tooltip ("the effective date of the
    # EXCESS LIABILITY policy"), same underlying concept as 131's umbrella
    # period, just a different form/field name for the same real-world date.
    # Reuses the SAME two facts (no new extraction work) and the same pass —
    # asking once here also means ACORD 131 and ACORD 25 never disagree with
    # each other on the umbrella's own period within a single generation run.
    if form_id in ("ACORD_131", "ACORD_25") and raw_text and raw_text.strip():
        _has_umb_eff = not _is_empty_llm_value(_fv(facts, "umbrella_effective_date"))
        _has_umb_exp = not _is_empty_llm_value(_fv(facts, "umbrella_expiration_date"))
        if not (_has_umb_eff and _has_umb_exp):
            try:
                # Direct sync call — map_facts_to_form runs on a worker thread,
                # so wrapping this in asyncio.run() risked the cross-loop hang.
                _umb_dates = _fetch_umbrella_period_sync(raw_text)
            except Exception as exc:                      # noqa: BLE001 — advisory only
                logger.warning("map_facts UMBRELLA_PERIOD form=%s | error: %s", form_id, exc)
                _umb_dates = None
            if _umb_dates:
                if not _has_umb_eff and _umb_dates.get("umbrella_effective_date"):
                    facts = {**facts, "umbrella_effective_date": _umb_dates["umbrella_effective_date"]}
                if not _has_umb_exp and _umb_dates.get("umbrella_expiration_date"):
                    facts = {**facts, "umbrella_expiration_date": _umb_dates["umbrella_expiration_date"]}
                logger.info(
                    "map_facts UMBRELLA_PERIOD form=%s | effective=%s expiration=%s",
                    form_id, _umb_dates.get("umbrella_effective_date"), _umb_dates.get("umbrella_expiration_date"),
                )

    for field in schema.keys():
        # Non-fillable fields (signatures, premiums, rates, underwriter codes)
        # are never sent to GPT. Leave them blank.
        #
        # EXCEPTION - line-of-business premium boxes. "Premium" is in
        # _NONFILLABLE_SUBSTRINGS, and this guard runs BEFORE any deterministic
        # resolution, so the whole LOB premium column was blanked unconditionally
        # even though the dec page prints those figures right next to the lines
        # we tick. That is a copy, not a carrier computation. They resolve HERE
        # from `coverage_lines` and are then marked deterministic-filled, so they
        # never enter the gap-fill set - compute_form_gaps still treats them as
        # non-fillable, so the LLM is never asked to produce a premium. The block
        # was doing two jobs; only the "GPT must not invent one" half was right.
        # The form's own edition - system metadata, never a question for anyone.
        # Mirrors compute_form_gaps so the two paths cannot disagree about it.
        if _FORM_EDITION_FIELD_RE.match(field):
            _ed = _form_edition_identifier(form_id)
            if _ed:
                mapped[field] = _ed
            _deterministic_filled.add(field)
            continue

        if _is_nonfillable_field(field):
            # Prior-coverage PREMIUM cells: the "Premium" substring blanket-
            # blocked them before the grid resolver could run, so the grid
            # filled carrier/number/dates but never its premium column
            # (verified on the graded test run). These are COPIES from the
            # per-line prior_coverage_by_line fact, not carrier computations —
            # same reasoning as the LOB premium exception below.
            if "TotalPremiumAmount" in field and _PRIOR_COVERAGE_RE.match(field):
                _pc_amt = _resolve_prior_coverage_cell(field, facts)
                _pc_amt = None if _pc_amt is _SCHED_SKIP else _pc_amt
                mapped[field] = _pc_amt or None
                _deterministic_filled.add(field)
                if _pc_amt:
                    cnt_deterministic += 1
                else:
                    cnt_nonfillable += 1
                continue
            if _is_lob_premium_field(field):
                _lob_amt = _resolve_lob_premium(field, facts)
                # Presence backstop (2026-08-10): a line premium is stamped from
                # the `coverage_lines` fact, which is unverified LLM extraction
                # output - the ONLY deterministic money path with no document
                # check of any kind (the raw-text verification pass below runs
                # over gpt_filled_set only). An amount that appears NOWHERE in
                # the uploaded text is fabricated and must not stamp; blank
                # beats a wrong figure on a signed application. Deliberately
                # narrow: amounts under 4 digits are skipped (below
                # _value_in_raw_text's reliable-match floor - fail-open, never
                # costs a legitimate short premium), and a misattributed amount
                # that IS on the page (the C35 $35 case) is out of scope here -
                # that is RULE 16's job at extraction time.
                if _lob_amt and raw_text:
                    _amt_digits = re.sub(r"\D", "", _lob_amt)
                    if len(_amt_digits) >= 4:
                        if _lob_premium_hay[0] is None:
                            _lob_premium_hay[0] = _normalize_for_search(raw_text)
                        if not _value_in_raw_text(_lob_amt, _lob_premium_hay[0]):
                            logger.info(
                                "lob-premium: %s amount %r not found in document text — not stamped",
                                field, _lob_amt,
                            )
                            _lob_amt = None
                mapped[field] = _lob_amt or None
                _deterministic_filled.add(field)
                if _lob_amt:
                    cnt_deterministic += 1
                else:
                    cnt_nonfillable += 1
                continue
            mapped[field] = None
            _deterministic_filled.add(field)
            cnt_nonfillable += 1
            continue

        # Schedule fields: row index → list[idx] lookup against facts.
        # If the row is out of range, mark as authoritative blank (do NOT send
        # to GPT — we know the row doesn't exist).
        sched = _resolve_schedule_row(field, facts)
        if sched is not _SCHED_SKIP:
            if sched is None and field.endswith("_A")                     and _single_row_schedule(field, facts):
                # Same mirror as `compute_form_gaps` - see the long note there.
                # Row A answering None means "the list is empty" OR "row 1 has
                # nothing in this column"; the second case must still get Pass
                # 1's scalar fallback, and short-circuiting here is what left
                # the per-premises DESCRIPTION OF OPERATIONS blank on the live
                # 2026-08-14 ACORD 125.
                _fb = _deterministic_map(field, facts)
                if _fb != "UNMATCHED" and not _is_empty_llm_value(_fb):
                    sched = _fb
            if sched is not None and not _is_empty_llm_value(sched):
                mapped[field] = sched
                _deterministic_filled.add(field)
                cnt_deterministic += 1
            else:
                _deterministic_filled.add(field)
                cnt_blank_sched += 1
            continue

        # General deterministic path: _ACORD_FIELD_RULES, address decomposition,
        # indicator derivation.
        result = _deterministic_map(field, facts)

        # ACORD 131 override: the form-header Policy_EffectiveDate_A /
        # Policy_ExpirationDate_A fields are handled by the generic
        # _ACORD_FIELD_RULES substring rule shared by every form
        # ("Policy_EffectiveDate" -> effective_date), which is correct
        # everywhere else (that header IS the GL/primary policy's date on
        # every other form) but WRONG here: per the real ACORD 131 template
        # tooltip, this header is "the effective date of the policy [being
        # applied for]" - the UMBRELLA policy itself, which commonly runs its
        # own separate period from the underlying GL/Auto/WC policies it
        # attaches over (that's the whole point of the umbrella period-
        # alignment cross-form check - it needs the umbrella's OWN date here,
        # not a copy of the GL date, or every umbrella policy would trivially
        # "align" with itself). Prefer the umbrella-specific fact when present;
        # fall through to the generic effective_date/expiration_date result
        # _deterministic_map already computed when the document never states a
        # distinct umbrella date (the common case) - never regresses below
        # today's behavior, only improves on it.
        if form_id == "ACORD_131" and field in ("Policy_EffectiveDate_A", "Policy_ExpirationDate_A"):
            _umb_key = "umbrella_effective_date" if field == "Policy_EffectiveDate_A" else "umbrella_expiration_date"
            _umb_val = _fv(facts, _umb_key)
            if not _is_empty_llm_value(_umb_val):
                result = str(_umb_val)

        # ACORD 25 override: same bug, different field name. Policy_
        # ExcessLiability_EffectiveDate_A/ExpirationDate_A are matched by a
        # DEDICATED _ACORD_FIELD_RULES entry (not a generic fallback) that maps
        # them straight to effective_date/expiration_date. Per the real ACORD 25
        # template tooltip ("the effective date of the EXCESS LIABILITY
        # policy"), this is the certificate's excess/umbrella coverage-line row,
        # genuinely distinct from the GL row directly above it on the same
        # certificate (Policy_GeneralLiability_EffectiveDate_A, left untouched -
        # that row correctly IS the GL/primary policy's own date). Same fix,
        # same fact keys, same safety guarantee as the ACORD 131 override above:
        # prefer the umbrella-specific fact when present, fall through to the
        # generic result when the document states no distinct excess period.
        if form_id == "ACORD_25" and field in ("Policy_ExcessLiability_EffectiveDate_A", "Policy_ExcessLiability_ExpirationDate_A"):
            _umb_key = "umbrella_effective_date" if field == "Policy_ExcessLiability_EffectiveDate_A" else "umbrella_expiration_date"
            _umb_val = _fv(facts, _umb_key)
            if not _is_empty_llm_value(_umb_val):
                result = str(_umb_val)

        if result == "UNMATCHED" or _is_empty_llm_value(result):
            # An OWNING resolver that produced no value means the box must stay
            # empty - the same authoritative-blank contract the schedule path
            # above already has. Without this, a deliberate blank is handed to
            # gap fill, which refills it from raw text: measured on a real run,
            # the prior-coverage grid still showed one policy number across the
            # GL, Property and Other columns despite the resolver correctly
            # blanking all three.
            if _is_authoritative_blank_field(field, facts):
                mapped[field] = None
                _deterministic_filled.add(field)
                cnt_blank_sched += 1
                continue
            # No rule matched, or rule produced empty value — let GPT try the
            # raw text. This keeps coverage on fields like _addr_line2 that
            # decompose to empty when the source address is a single line.
            unmatched[field] = schema[field]
        else:
            mapped[field] = result
            _deterministic_filled.add(field)
            cnt_deterministic += 1

    logger.info(
        "map_facts PIPELINE form=%s | schema=%d det=%d nonfill=%d blank_sched=%d gpt_fields=%d",
        form_id or "unknown",
        len(schema), cnt_deterministic, cnt_nonfillable, cnt_blank_sched, len(unmatched),
    )

    # ── Pass 1.5: alias-based deterministic stamping (opt-in) ───────────────
    # Fills fields Pass 1 missed by looking up each field's canonical name in
    # forms_aliases/<form_id>_alias.json and resolving it via the extraction-
    # key bridge in alias_stamper. Pure dictionary lookup — no LLM. When the
    # ENABLE_ALIAS_STAMPING flag is off, this block is a no-op and behavior
    # is identical to the prior pipeline.
    cnt_alias_filled = 0
    if unmatched and form_id:
        try:
            from config.settings import ENABLE_ALIAS_STAMPING
            if ENABLE_ALIAS_STAMPING:
                from services.alias_stamper import stamp_form_fields
                alias_filled = stamp_form_fields(form_id, facts, list(unmatched.keys()))
                for field, value in alias_filled.items():
                    if value is not None and not _is_empty_llm_value(value):
                        # THE FOURTH DOOR, and the one nothing was watching.
                        # Pass 1.5 writes `mapped[field]` DIRECTLY - it never
                        # routes through `_deterministic_map`, so every
                        # authoritative-blank resolver was invisible to it, and
                        # it never touches `gpt_filled_set`, so every guard
                        # scoped to gap fill was invisible too. Measured across
                        # all 17 alias maps: **137 fields that a resolver owns**
                        # were being overridden here - the FAX box (six live
                        # runs), the deposit, REMARKS, the applicant website,
                        # the no-loss attestation, all 64 prior-coverage cells.
                        # Each of those resolvers exists because a box has NO
                        # legitimate document source; an alias map cannot know
                        # that, because it is a pure name->fact dictionary.
                        if _is_authoritative_blank_field(field, facts):
                            logger.info(
                                "alias_stamp SKIPPED %s - a resolver owns this "
                                "box; alias maps cannot override an "
                                "authoritative blank", field,
                            )
                            continue
                        mapped[field] = value
                        _deterministic_filled.add(field)
                        unmatched.pop(field, None)
                        cnt_alias_filled += 1
                if cnt_alias_filled:
                    logger.info(
                        "map_facts ALIAS form=%s | alias_filled=%d remaining_gpt=%d",
                        form_id, cnt_alias_filled, len(unmatched),
                    )
        except Exception as exc:                # noqa: BLE001 — never block the pipeline
            logger.warning("map_facts ALIAS form=%s | error: %s", form_id, exc)

    gpt_raw_fields: set = set()
    gpt_filled_set: set = set()
    gpt_question_grounding: Dict[str, str] = {}

    if unmatched and pre_filled_gpt is not None:
        # Combined gap-fill path: consume pre-computed values from the cross-form
        # GPT pass instead of issuing a per-form call. The shared pass already
        # ran over the union of unmatched fields across all selected forms.
        gpt_values     = pre_filled_gpt.get("filled_values", {}) or {}
        gpt_raw_fields = pre_filled_gpt.get("raw_text_fields", set()) or set()
        gpt_question_grounding = pre_filled_gpt.get("question_grounding", {}) or {}
        gpt_filled_set = {f for f in unmatched if f in gpt_values}

        for field in unmatched:
            if field in gpt_values:
                mapped[field] = gpt_values[field]
            else:
                mapped.setdefault(field, None)

        logger.info(
            "map_facts COMBINED form=%s | pre_filled=%d/%d raw_text_sourced=%d",
            form_id or "unknown", len(gpt_filled_set), len(unmatched), len(gpt_raw_fields),
        )
    elif unmatched:
        logger.info(
            "map_facts GPT_ELIGIBLE form=%s | fields=%d raw_text_chars=%d",
            form_id or "unknown", len(unmatched), len(raw_text),
        )
        gpt_result     = _fill_unmatched_with_gpt(unmatched, facts, form_id, raw_text=raw_text, already_filled=mapped)
        gpt_values     = gpt_result["filled_values"]
        gpt_raw_fields = gpt_result.get("raw_text_fields", set())
        gpt_question_grounding = gpt_result.get("question_grounding", {}) or {}
        gpt_filled_set = set(gpt_values.keys())

        for field in unmatched:
            if field in gpt_values:
                mapped[field] = gpt_values[field]
            else:
                mapped.setdefault(field, None)

        logger.info(
            "map_facts GPT_DONE form=%s | gpt_filled=%d/%d raw_text_sourced=%d",
            form_id or "unknown", len(gpt_filled_set), len(unmatched), len(gpt_raw_fields),
        )

    # ── THE GUARD REGION BEGINS HERE, and this is where we start watching ────
    # THE MISSING FEEDBACK LOOP (2026-08-13, asked four times: "why no hard
    # stops or warnings"). `evaluate_stops` validates FACTS. Everything from
    # this line down validates STAMPED VALUES. The two never spoke, so a form
    # on which fifteen fabricated values were caught and removed was
    # indistinguishable on screen from a form that was right the first time -
    # same silence, same empty boxes, and nothing anywhere telling the producer
    # that a box is blank BECAUSE WE REFUSED A VALUE rather than because the
    # document was quiet.
    #
    # Snapshotted as a DIFF, not per-guard plumbing, deliberately: there are
    # ~30 guards below and a hand-maintained list of "which ones report" would
    # be stale within a week - the same rot that let the fourth door stay open.
    # Non-empty here and empty at `return` means a guard took it, whichever one
    # did, including guards written after this comment.
    _pre_guard_values = {
        _k: _v for _k, _v in mapped.items()
        if _v is not None and str(_v).strip() not in ("", "null", "None")
    }
    # CASCADE, not judgement. When a party's NAME is refused the whole row goes
    # with it - address, phone, account number, reference - and on the client's
    # ACORD 125 that turned 3 real decisions into a 131-field advisory row
    # reading "a value was found for each but could not be true for that box".
    # Only the FIRST clause was true of the cascade, and 131 rows of it buries
    # the handful that need a human. These fields are still blanked and still
    # logged; they are just not reported as independent findings.
    _cascade_blanked: set = set()

    # ── Evidence-gated fill (opt-in, Figure 30 + Figure 33, generalized) ─────
    # The verified dec-page coverage lines, computed ONCE for this gate: both
    # the quote check and the explanation check below consult it. Empty when
    # the index is absent, and every consumer degrades to the old behaviour.
    _dec_lines = _dec_coverage_line_set(facts)
    # A single, uniform rule for EVERY Yes/No field on EVERY ACORD form (client
    # requirement: "in all the forms... certain fields where Y/N/Yes/No to be
    # filled... only fill if we found concrete evidence") - not just the
    # compliance "_Question_<code>Code_" text-field family this gate started
    # with, and not just the high-impact auto/ownership checkbox subset added
    # afterward. See _is_yes_no_field for the full field-shape coverage: name
    # pattern, /Btn checkbox type, or tooltip Y/N convention. The gap-fill
    # model answers the field and cites its evidence (question_grounding); we
    # KEEP the answer only when that evidence is genuinely present in the
    # uploaded document. We do NOT second-guess the model's polarity or
    # re-derive the topic with keyword matching — earlier attempts at that
    # blanked legitimate documented answers ("not a subsidiary" -> wrongly
    # dropped) and manufactured false ones (a "no claims" explanation ->
    # wrongly flipped to "Yes"). The model reads the document and decides; our
    # only job is to catch a hallucination, i.e. an answer whose cited evidence
    # is not actually in the document.
    #
    #   * YES  - kept when its paired explanation OR its evidence quote is
    #            present in the document. A kept "Yes" is always given an
    #            explanation (backfilled from the evidence quote if the model
    #            left the box empty), so a broker never sees a bare "Yes".
    #   * NO   - kept when its evidence quote is present AND actually expresses a
    #            negative (so a random positive sentence grabbed from the
    #            document cannot masquerade as proof of a "No"). A "No" carries
    #            no explanation.
    #   * else - ungrounded answer -> blanked -> left for ARQ / manual entry.
    #
    # The gap-fill LLM's own "raw_text_sourced" self-report is NOT trusted (bug
    # 2026-07-11: a model that fabricates content can falsely flag it verbatim).
    # Deterministic (Pass 1 / alias) values never enter gpt_filled_set, so they
    # are untouched here - a checkbox Pass 1 (or alias stamping) already filled
    # from a real extracted fact is never re-litigated by this gate.
    # THE HAYSTACK INCLUDES THE INDEX, and that is not a relaxation (2026-08-14).
    # Stage A shows the model the rendered declarations index and asks it to cite
    # its evidence; the index renders as "Label: value  [owner]" lines that exist
    # in OUR prompt, not verbatim in the document. So a model that correctly
    # quoted what it was given failed the gate and its answer was blanked - and
    # because Stage A removes answered fields from Stage B, there was no second
    # chance. Every index entry has ALREADY passed `_verify_dec_entries`' literal
    # -presence check against this document, so accepting index text admits
    # nothing the document does not print; it just admits it in the shape the
    # model was handed. Fields answered from the raw walk are unaffected.
    _evidence_hay = _normalize_for_search(raw_text) if raw_text else ""
    try:
        _index_text = _render_dec_index((facts or {}).get("dec_page_entries"))
    except Exception:                                      # noqa: BLE001
        _index_text = ""
    if _index_text:
        _evidence_hay = (_evidence_hay + " " + _normalize_for_search(_index_text)).strip()
    # Per-sentence split for _quote_grounds_claim's paraphrase fallback - kept
    # as ORIGINAL (unnormalized) text so _sim_tokens can tokenize each sentence
    # independently. Split is intentionally simple (sentence-ending punctuation
    # or a newline); a slightly-too-long or too-short "sentence" only affects
    # the fallback's precision, never the exact-match path above it.
    _evidence_sentences = (
        [s for s in re.split(r"[.!?\n]+", raw_text) if s and s.strip()] if raw_text else []
    )
    try:
        from config.settings import ENABLE_EVIDENCE_GATED_FILL
    except Exception:                              # noqa: BLE001
        ENABLE_EVIDENCE_GATED_FILL = False
    if ENABLE_EVIDENCE_GATED_FILL:
        _gated = 0
        _q_to_exp = _question_explanation_pairs(schema)
        # Unpaired questions' dependent tables - the owner's "a Y carries its
        # explanation" rule for the questions the explanation pairing cannot
        # reach. See _unpaired_question_deps.
        try:
            _q_deps = _unpaired_question_deps(schema, _q_to_exp)
        except Exception:                                      # noqa: BLE001
            _q_deps = {}
        _exp_to_q = {exp: q for q, exp in _q_to_exp.items()}

        # Values already assigned as the specific companion answer for a
        # DIFFERENT question (see _NONADJACENT_QUESTION_COMPANIONS) - reserved
        # so they can't ALSO be accepted as generic "explanation" content for
        # an unrelated question (see _is_generic_boilerplate_reuse). Computed
        # once here since companion fields are plain gap-fill text, already
        # settled in `mapped` before this evidence-gate block runs.
        _reserved_companion_values: Dict[str, str] = {
            _c: mapped.get(_c)
            for _companions in _NONADJACENT_QUESTION_COMPANIONS.values()
            for _c in _companions
            if isinstance(mapped.get(_c), str) and mapped.get(_c).strip()
        }

        def _is_gated_field(f: str) -> bool:
            """Every ACORD Yes/No convention across all 17 forms - not just the
            compliance-question naming pattern (Figure 30) or the high-impact
            auto/ownership checkbox subset (Figure 33 audit finding: ACORD
            137/138's HNOA-equivalent checkboxes have no "_Question_Code_"
            name, so they were never reaching this gate). Delegates to
            _is_yes_no_field, which is a strict superset: every high-impact
            checkbox is a /Btn field, so nothing here regresses - it just also
            now covers every OTHER checkbox (sink hole, mine subsidence,
            building features, entity type, LOB selection, ...) and the plain
            Y/N text-field convention (e.g. ACORD 140/25's "…YesNoCode_")."""
            return _is_yes_no_field(f, schema)

        # Count how many DISTINCT Yes/No fields cite each (near-duplicate)
        # grounding quote, so _evidence_supports can blank a quote reused beyond
        # _EVIDENCE_QUOTE_REUSE_MAX times (pathological one-quote-for-everything
        # boilerplate). Clustered by NEAR-DUPLICATE similarity, not exact string
        # match (same token-Jaccard technique Guard 4 uses for cross-field
        # boilerplate bleed on VALUES, here applied to grounding QUOTES): the
        # model can reword the same sentence slightly per field, which exact-
        # string counting would miss. Clustering compares quote-to-QUOTE, never
        # quote-to-QUESTION topic (that heuristic is the standing forbidden one).
        #
        # History: this cap was introduced when a broken 80-char tooltip
        # truncation left the model BLIND to question text, so it answered ~20
        # of 22 questions "No" citing one or two real sentences over and over.
        # With that truncation fixed (2026-07-16, see _SCHEMA_TOOLTIP_MAX) the
        # model reads each real question and moderate reuse is now LEGITIMATE
        # (a broad negation genuinely answers several exposure questions "No").
        # A tight cap therefore began blanking CORRECT answers, so the threshold
        # is now generous and env-tunable — see _EVIDENCE_QUOTE_REUSE_MAX.
        _quote_cluster_tokens: List[frozenset] = []
        _quote_cluster_texts: List[List[str]] = []
        for _f in gpt_filled_set:
            if not _is_gated_field(_f):
                continue
            _q = gpt_question_grounding.get(_f)
            if not _q or not str(_q).strip():
                continue
            _qn = _normalize_for_search(str(_q))
            if not _qn:
                continue
            _q_toks = _sim_tokens(str(_q))
            for _ci, _rep_toks in enumerate(_quote_cluster_tokens):
                if _qn in _quote_cluster_texts[_ci] or _is_near_duplicate_text(_q_toks, _rep_toks):
                    _quote_cluster_texts[_ci].append(_qn)
                    break
            else:
                _quote_cluster_tokens.append(_q_toks)
                _quote_cluster_texts.append([_qn])
        _quote_use_count: Dict[str, int] = {
            _qn: len(_texts) for _texts in _quote_cluster_texts for _qn in _texts
        }

        def _present(text, field: Optional[str] = None) -> bool:
            """True when `text` is grounded in the uploaded document (independent
            search; punctuation/case/whitespace-insensitive with a word-subset
            fallback). With no document text to check against, nothing is
            grounded - self-report is deliberately not trusted.

            `field`: when given, also rejects `text` that is really the
            generic operations_description fact, or another question's own
            reserved companion value, reused as this field's explanation (see
            _is_generic_boilerplate_reuse) - presence alone proves the text is
            real, not that it answers THIS question."""
            if text is None or not str(text).strip():
                return False
            if not (bool(_evidence_hay) and _value_in_raw_text(str(text), _evidence_hay)):
                return False
            return not _is_generic_boilerplate_reuse(field, text, facts, _reserved_companion_values)

        def _quote_restates_the_question(quote, field: str) -> bool:
            """True when the 'evidence' is just the question's own words.

            LIVE RUN 2026-08-12, from `evidence_gate KEPT_YES`:

                CancelNonRenew_NonPaymentIndicator_A
                  tooltip: "...the policy is being cancelled due to
                            NON-PAYMENT OF PREMIUM."
                  quote:   "for non-payment of premium"

                AdditionalInterest_Interest_AdditionalInsuredIndicator_A
                  tooltip: "...the additional interest type is an
                            ADDITIONAL INSURED."
                  quote:   "additional insured"

            Both ticked a box on the client's form. Neither says anything about
            THIS applicant - they are the question, echoed back. The gate already
            rejects exclusion clauses, contract language and glossary
            definitions; it had no answer for a quote that is simply the label.

            Same primitive as Guard 8, but deliberately NOT `_is_tooltip_echo`:
            that is scoped to VALUES on narrative fields and carries a 30-char
            floor, and both live cases slip under it (26 and 18 chars, on
            checkbox fields). A quote is evidence by nature - restating the
            question IS the failure mode, so there is no length floor here.

            Verified on the four literal quotes from that run plus genuine
            affirmative evidence: the two label-echoes are rejected, and
            "Date of Issue: 07/16/2025", "INSURED IS: LLC" and real event
            sentences are all kept, because each carries a token the question
            does not.

            CORRECTED 2026-08-12 - token overlap ALONE was destroying real
            answers. A direct answer to a yes/no question necessarily reuses the
            question's vocabulary, and "not" is a stopword, so "The applicant
            does not have any subsidiaries." looked identical to a bare label.
            Measured: 39 of 256 real compliance questions across 9 forms lost
            their canonical evidence (ACORD 125 40%, ACORD 126 27%), and a
            rejected "No" is blanked with no fallback. Overlap is now necessary
            but NOT sufficient - the quote must also fail to assert anything.
            See _quote_asserts_something.
            """
            meta = schema.get(field) if isinstance(schema, dict) else None
            tooltip = (meta or {}).get("tu") if isinstance(meta, dict) else None
            if not tooltip:
                return False
            text = str(quote or "").strip().strip('"“”‘’ ')
            q_toks = _echo_tokens(text)
            d_toks = _echo_definition_tokens(tooltip)
            if not q_toks or not d_toks:
                return False
            if not _echo_all_tokens_present(q_toks, d_toks):
                return False
            # Shares the question's whole vocabulary - but a STATEMENT that does
            # so is the document answering, not the model echoing. Only a bare
            # label (no subject, no finite verb, or the question itself) is
            # evidence of nothing.
            return not _quote_asserts_something(text)

        def _evidence_supports(quote, *, negative: bool, allow_paraphrase: bool,
                               field: str = "") -> bool:
            """The model's cited evidence really backs its answer: a contiguous
            phrase actually in the document, not reused as boilerplate, and -
            for a NEGATIVE answer - one that actually states a denial rather
            than an unrelated positive sentence.

            `allow_paraphrase`: the per-sentence paraphrase fallback (see
            _quote_grounds_claim) is enabled ONLY when this question has a real
            paired Explanation field in the schema - i.e. the model had a
            SECOND, independent place to demonstrate its answer and simply
            didn't use it, which is a materially lower-risk gap to forgive than
            a question with NO Explanation slot at all, where the quote is the
            ONLY signal that exists. Found in audit (live test 2026-07-15):
            without this restriction, a fabricated quote for an unpaired
            question (ACORD 127's ICC/PUC filings question, "no explanation
            needed" per the form itself) passed by reusing real words from an
            UNRELATED sentence elsewhere in the document - exactly the
            2026-07-12 bug class this file's strictness exists to prevent.
            Unpaired questions keep the original exact-match-only bar."""
            if not quote or not _evidence_hay or not _quote_grounds_claim(
                quote, _evidence_hay, _evidence_sentences if allow_paraphrase else None
            ):
                return False
            # A "Yes" must cite evidence unique to it (borrowed Yeses assert a
            # false exposure); a "No" may share a broad negation across several
            # exposure questions, so it uses the generous cap.
            _reuse_cap = _EVIDENCE_QUOTE_REUSE_MAX if negative else _EVIDENCE_YES_QUOTE_REUSE_MAX
            if _quote_use_count.get(_normalize_for_search(str(quote)), 0) > _reuse_cap:
                return False
            if negative and not _quote_expresses_negative(quote):
                return False
            # A "Yes" whose own evidence says the thing is NOT covered.
            #
            # This closes the asymmetry that let `Crime and Fidelity - No
            # Coverage` justify TICKING the Crime box: a "No" has always had to
            # cite a quote that actually denies something, while a "Yes" only had
            # to cite a quote that EXISTS. A denial is not proof of the opposite.
            #
            # It uses the NARROW `_COVERAGE_DENIAL_RE` ("no coverage" / "not
            # covered" / "coverage not provided"), never the broad
            # `_NEGATION_CUE_RE` used on the "No" side. Measured on realistic
            # grounding quotes: the broad cue rejects 7 of 10 legitimate
            # affirmative quotes - "Crime Coverage Policy No. BBC7263" and
            # "free-standing masonry structure" both trip it, because "no" is
            # also the abbreviation for "number" and "free" is an ordinary
            # adjective. The narrow pattern rejects 0 of 10 and still catches
            # every real denial. The two sides are deliberately NOT symmetric:
            # the "No" side can afford a broad cue because its failure mode is a
            # blank, while over-firing here would delete correct Yes answers.
            if not negative and _COVERAGE_DENIAL_RE.search(str(quote).lower()):
                return False
            # A "Yes" whose evidence is a POLICY EXCLUSION TITLE.
            #
            # Observed on a real run: ACORD 125 Question 6 ("any past losses or
            # claims relating to sexual abuse or molestation allegations,
            # discrimination or negligent hiring?") came back "Y", grounded on
            # "BROAD ABUSE OR MOLESTATION EXCLUSION" - a form title lifted off the
            # policy. An exclusion is the policy declining to cover a thing; it is
            # never evidence the thing HAPPENED. Same exposure-versus-coverage
            # conflation that ticked the Cyber box, here on the compliance pass.
            #
            # Scoped to a quote that IS a title - i.e. the whole quote ends in
            # "exclusion(s)". Deliberately not "contains exclusion anywhere":
            # "the applicant had a molestation claim in 2023; an exclusion was
            # added at renewal" is a REAL Yes that merely mentions one. Measured
            # on 5 real form titles and 6 genuine-event quotes: 5 rejected, 0
            # false rejections.
            if not negative and _EXCLUSION_TITLE_RE.match(str(quote)):
                return False
            # ...and an exclusion CLAUSE, not just a form title. "This insurance
            # does not apply to: Asbestos" is the policy declining to cover a
            # thing, never the applicant confirming they do it.
            if not negative and _EXCLUSION_CLAUSE_RE.search(str(quote)):
                return False
            # Policy CONTRACT language answers neither direction. These questions
            # ask about the APPLICANT'S HISTORY; a bankruptcy condition or a
            # judgment provision is the contract describing itself. Applied to Y
            # AND N - "bankruptcy ... will not relieve us of our obligations"
            # reads as a negation and was keeping a false "N" on the live form.
            if _POLICY_CONTRACT_LANGUAGE_RE.search(str(quote)):
                return False
            # ...and a DEFINITION from the policy's glossary. A 271-page
            # package is mostly coverage forms, so for any Yes/No question
            # some clause contains the question's own noun - the pollution
            # definition contains "chemicals" and was accepted as proof of a
            # chemicals exposure. A definition defines a word; it never
            # reports a fact about this applicant.
            if _quote_cites_contract_machinery(quote):
                logger.info(
                    "evidence_gate QUOTE_IS_CONTRACT_MACHINERY form=%s quote=%r "
                    "- an exclusion/offer/definition can never evidence a fact "
                    "about the applicant",
                    form_id or "unknown", str(quote)[:100],
                )
                return False
            # ...and a quote that is simply the QUESTION, echoed back. Applied
            # to Y AND N: a label restatement establishes neither direction.
            if field and _quote_restates_the_question(quote, field):
                logger.info(
                    "evidence_gate QUOTE_RESTATES_QUESTION form=%s field=%s quote=%r "
                    "- the 'evidence' is the question's own words, not a statement "
                    "about this applicant",
                    form_id or "unknown", field, str(quote)[:120],
                )
                return False
            # The policy as the subject of its own sentence ("This exclusion
            # applies...", "This endorsement changes..."). Same rule already
            # applied to stamped narrative values; a quote is not exempt.
            if _POLICY_SELF_SUBJECT_RE.search(str(quote)):
                logger.info(
                    "evidence_gate QUOTE_IS_POLICY_SUBJECT form=%s field=%s quote=%r",
                    form_id or "unknown", field, str(quote)[:120],
                )
                return False
            # The policy DEFINING a term, or written in contract-party voice
            # ("...related to you...", "...against others to us..."). Applied
            # to Y and N alike: a definition concludes nothing in either
            # direction. See _is_contract_wording for the two live cases.
            if _is_contract_wording(quote):
                logger.info(
                    "evidence_gate QUOTE_IS_CONTRACT_WORDING form=%s field=%s "
                    "quote=%r - a definition or contract-party sentence is the "
                    "policy describing itself, never the applicant reporting a "
                    "fact", form_id or "unknown", field, str(quote)[:120],
                )
                return False
            # A "Yes" needs evidence that ASSERTS something OR carries a data
            # payload. "ERIN ROYAL" does neither - a bare name predicates
            # nothing and proves nothing happened. "INSURED IS: LLC" and "Date
            # of Issue: 07/16/2025" have no verb either, but they CARRY data
            # (a colon value, a digit) and are pinned as legitimate evidence by
            # test_a_quote_carrying_real_data_still_grounds_a_yes - the payload
            # exemption is what keeps them alive. The "No" side keeps its own
            # rules: a broad negation is prose and passes trivially.
            if not negative and not _quote_asserts_something(quote) \
                    and not _DATA_PAYLOAD_RE.search(str(quote)):
                logger.info(
                    "evidence_gate QUOTE_ASSERTS_NOTHING form=%s field=%s quote=%r "
                    "- a bare label/title cannot evidence a Yes",
                    form_id or "unknown", field, str(quote)[:120],
                )
                return False
            # ...and evidence that IS a coverage artifact - a printed dec line
            # (row-label prefix stripped), a scheduled item's name echoed back,
            # or an instruction addressed to the reader - grants or describes
            # coverage; it never reports an applicant fact. THE 2026-08-13
            # ACORD 127 root cause - see _is_coverage_artifact_text.
            #
            # ONE EXEMPTION, and it is the question's own subject matter that
            # earns it (2026-08-14): a COVERAGE-EXISTENCE box asks "is this line
            # of business on the policy?", and a printed declarations line
            # granting that coverage is not merely admissible evidence - it is
            # the ONLY evidence that can exist. Rejecting artifacts here made
            # those boxes unevidenceable by construction: nothing the model
            # could ever cite would be accepted. Scoped by field NAME to the
            # `Policy_LineOfBusiness_*` family, so every exposure question
            # ("do you transport hazmat?") keeps the full artifact rule - that
            # is the mention-versus-grant distinction, and it stays intact.
            # `_COVERAGE_DENIAL_RE` above still blocks the inverse: a line that
            # reads "Property - No Coverage" can never tick the Property box.
            if (not negative and not _COVERAGE_EXISTENCE_FIELD_RE.search(field or "")
                    and _is_coverage_artifact_text(quote, _dec_lines, facts)):
                logger.info(
                    "evidence_gate QUOTE_IS_COVERAGE_ARTIFACT form=%s field=%s "
                    "quote=%r", form_id or "unknown", field, str(quote)[:120],
                )
                return False
            return True

        # Decisions the semantic judge may revisit - see _judge_evidence_batch.
        # Populated during Pass A, resolved in one batched call afterwards so a
        # per-field call is never made.
        _judge_review: List[dict] = []

        # ── Pass A: validate each answered Yes/No field (see _is_gated_field) ──
        for q_field in list(gpt_filled_set):
            if not _is_gated_field(q_field):
                continue
            v = str(mapped.get(q_field) or "").strip().lower()
            if not v:
                continue
            exp_field = _q_to_exp.get(q_field)
            exp_val   = mapped.get(exp_field) if exp_field else None
            quote     = gpt_question_grounding.get(q_field)

            # A paired EXPLANATION that is itself a printed coverage line lets a
            # Yes bypass every quote check above - `exp_present` alone keeps it.
            # Live ACORD 127 Q5: "any car modified?" = Y, "explained" by the
            # endorsement titles "Auto Elite Extension $250" and "CONTRACTORS'
            # EQUIPMENT $10,000" sitting in the description/cost table. Blank
            # the artifact BEFORE presence is computed, so the Yes must stand on
            # real evidence or fall.
            if exp_field and exp_val and _is_coverage_artifact_text(
                    exp_val, _dec_lines, facts):
                logger.info(
                    "evidence_gate EXPLANATION_IS_COVERAGE_ARTIFACT form=%s field=%s "
                    "value=%r", form_id or "unknown", exp_field, str(exp_val)[:80],
                )
                mapped[exp_field] = None
                exp_val = None

            if v in _AFFIRMATIVE_VALUES:
                exp_present   = _present(exp_val, exp_field)
                quote_present = _evidence_supports(quote, negative=False,
                                                   allow_paraphrase=exp_field is not None,
                                                   field=q_field)
                if not (exp_present or quote_present):
                    mapped[q_field] = None            # ungrounded "Yes" -> blank
                    if exp_field:
                        mapped[exp_field] = None
                    _gated += 1
                    continue
                # A "Yes" on a question whose form section demands
                # substantiation - a dependent TABLE between it and the next
                # question - while that whole section is empty. The owner's
                # rule: a Y carries its explanation or it does not stand. The
                # dependents count whatever their source: a deterministic
                # stamp, a client answer or a gap-fill cell all substantiate.
                # A dependent cell holding a COVERAGE ARTIFACT substantiates
                # nothing - live Q5 run 5: the deps were "populated" with the
                # inland-marine item name and its limit, so the emptiness test
                # passed and the Yes stood. Artifact cells are blanked here and
                # do not count toward substantiation.
                _deps = _q_deps.get(q_field)
                if _deps:
                    for _d in _deps:
                        _dv = mapped.get(_d)
                        # SOURCE-AGNOSTIC, per the fourth-door rule (see
                        # tests/test_value_source_contract.py): "is this text an
                        # artifact?" is a question about the VALUE, so scoping it
                        # to `gpt_filled_set` let an alias-stamped or
                        # deterministically-routed cell substantiate a Yes with
                        # the same junk the model would have been refused for.
                        if _dv and _is_coverage_artifact_text(
                                _dv, _dec_lines, facts):
                            logger.info(
                                "evidence_gate DEP_IS_COVERAGE_ARTIFACT form=%s "
                                "field=%s value=%r", form_id or "unknown", _d,
                                str(_dv)[:80],
                            )
                            mapped[_d] = None
                # A dependent section that is PARTLY filled, and whose only
                # surviving cells carry no letters at all, is not an
                # explanation - it is a borrowed digit sitting in a table.
                # Run 8's Q14, verbatim: "any drivers with convictions?" = Y,
                # its conviction row holding TYPE = "SEE ITEM FOUR FOR HIRED OR
                # BORROWED AUTOS" (blanked just above as a cross-reference) and
                # "#YRS REV" = 3, with driver number, date and place all empty.
                # A single number answers nothing.
                #
                # Gated on the section being INCOMPLETE on purpose: when every
                # dependent is filled the section is a finished record and we do
                # not second-guess its shape, so an all-numeric table that ACORD
                # genuinely designed that way is never touched.
                if _deps and any(str(mapped.get(_d) or "").strip() for _d in _deps) \
                        and not all(str(mapped.get(_d) or "").strip() for _d in _deps) \
                        and not any(
                            re.search(r"[A-Za-z]", str(mapped.get(_d) or ""))
                            for _d in _deps):
                    logger.info(
                        "evidence_gate DEPS_ARE_A_BARE_NUMBER form=%s field=%s "
                        "- the only substantiation offered is %r in an otherwise "
                        "empty section", form_id or "unknown", q_field,
                        next((str(mapped.get(_d)) for _d in _deps
                              if str(mapped.get(_d) or "").strip()), ""),
                    )
                    for _d in _deps:
                        mapped[_d] = None
                if _deps and not any(
                        str(mapped.get(_d) or "").strip() for _d in _deps):
                    logger.info(
                        "evidence_gate YES_WITHOUT_SUBSTANTIATION form=%s field=%s "
                        "- %d dependent field(s) all empty (e.g. %s); a Yes must "
                        "carry its explanation", form_id or "unknown", q_field,
                        len(_deps), _deps[0],
                    )
                    mapped[q_field] = None
                    _gated += 1
                    continue
                # A Yes claiming something is NOT on this form, "explained" by
                # an entity the form itself schedules. Live Q13: "any vehicles
                # owned but not scheduled?" = Y, explained by "2012 SUBARU
                # OUTBACK SEDAN: ID NO 4S4BRCGC9C3217772" - the VIN stamped in
                # vehicle row 1 of the SAME form. The form contradicts the
                # answer; no topic matching needed, just the VIN.
                _support = str(exp_val or quote or "")
                # The same-form contradiction one column over: a Yes whose
                # support IS a rating classification stamped on this very form
                # (run 9, ACORD 126 Q4: "do your subcontractors carry limits
                # less than yours?" = Y, "explained" by the class description
                # "Contrctrs-sub work-in connection w/constrctn..." - the
                # identical string sitting in the Schedule of Hazards two
                # sections up). A class description types the risk for rating;
                # it can never report an underwriting fact. Value identity
                # against this form's own classification cells and the
                # class-label facts - no topic, no vocabulary.
                _sup_norm = re.sub(r"[^a-z0-9]+", " ",
                                   re.sub(r"^[^:]{0,40}:", "", _support)
                                   .lower()).strip()
                if _sup_norm:
                    _class_vals = {
                        re.sub(r"[^a-z0-9]+", " ", str(v).lower()).strip()
                        for f2, v in mapped.items()
                        if v and f2 != q_field
                        and ("ClassificationDescription" in f2
                             or "RateClassCode" in f2)
                    }
                    for _ck in ("contractor_type",):
                        _cv = _fv(facts, _ck)
                        if _cv:
                            _class_vals.add(re.sub(r"[^a-z0-9]+", " ",
                                                   str(_cv).lower()).strip())
                    # The FACT copies too: the stamped classification cell can
                    # be gone by now (the boilerplate-bleed dedup clears one of
                    # two identical cells), but the class-code fact remembers.
                    _codes = _fv(facts, "gl_class_codes")
                    if isinstance(_codes, list):
                        for _row in _codes:
                            if isinstance(_row, dict) and _row.get("description"):
                                _class_vals.add(re.sub(
                                    r"[^a-z0-9]+", " ",
                                    str(_row["description"]).lower()).strip())
                    if _sup_norm in _class_vals:
                        logger.info(
                            "evidence_gate SUPPORT_IS_A_CLASSIFICATION form=%s "
                            "field=%s support=%r - a rating class description "
                            "cannot answer an underwriting question",
                            form_id or "unknown", q_field, _support[:80],
                        )
                        mapped[q_field] = None
                        if exp_field:
                            mapped[exp_field] = None
                        _gated += 1
                        continue
                _vins = re.findall(r"\b[A-HJ-NPR-Z0-9]{17}\b", _support.upper())
                if _vins:
                    _scheduled = {
                        str(v).strip().upper() for f2, v in mapped.items()
                        if f2 != q_field and v and "VINIdentifier" in f2
                    }
                    if any(v in _scheduled for v in _vins):
                        logger.info(
                            "evidence_gate YES_CONTRADICTS_SCHEDULE form=%s "
                            "field=%s - the supporting VIN is already scheduled "
                            "on this form", form_id or "unknown", q_field,
                        )
                        mapped[q_field] = None
                        if exp_field:
                            mapped[exp_field] = None
                        _gated += 1
                        continue
                # A "Yes" whose supporting text LEADS with a denial is
                # incoherent — graded test run: the flammables question came
                # back "Y" explained by "No roofing, no demolition, no exterior
                # work above three stories." (a real sentence, about a
                # different topic, that ASSERTS ABSENCE). Deliberately narrower
                # than the broad negation cue (which rejects 7 of 10 legitimate
                # affirmative quotes): only a LEADING no/none/not/never/neither
                # trips it, which a genuine affirmative explanation essentially
                # never starts with.
                _support_text = str(exp_val if exp_present else (quote or "")).strip()
                if _YES_NEGATIVE_LEAD_RE.match(_support_text.lower()):
                    mapped[q_field] = None
                    if exp_field:
                        mapped[exp_field] = None
                    _gated += 1
                    continue
                # Keep the "Yes"; guarantee it carries a grounded explanation.
                if exp_field and not exp_present:
                    mapped[exp_field] = str(quote).strip() if quote_present else None
                # WHY IT SURVIVED. Every rejection path above logs nothing, and
                # neither did this one - so a Yes that got through was invisible
                # and undiagnosable. Live 271-page run 2026-08-12: ACORD 125
                # Question 5's NON-PAYMENT reason box came back ticked and there
                # was no way to tell whether it cleared the gate on a quote or on
                # a paired explanation, let alone WHICH sentence did it. Guessing
                # at a new rejection pattern without that is how a guard starts
                # deleting correct answers. This is the line that makes the next
                # run answer the question.
                logger.info(
                    "evidence_gate KEPT_YES form=%s field=%s via=%s quote=%r",
                    form_id or "unknown", q_field,
                    "explanation" if exp_present else "quote",
                    str(quote or "")[:200],
                )
                _judge_review.append({
                    "id": q_field, "answer": "Yes", "exp_field": exp_field,
                    "quote": str(exp_val if exp_present else (quote or "")).strip(),
                    "kept": True, "value": mapped.get(q_field),
                })
            elif v in _NEGATIVE_VALUES:
                if _evidence_supports(quote, negative=True,
                                      allow_paraphrase=exp_field is not None,
                                      field=q_field):
                    if exp_field:
                        mapped[exp_field] = None       # a "No" needs no explanation
                    _judge_review.append({
                        "id": q_field, "answer": "No", "exp_field": exp_field,
                        "quote": str(quote or "").strip(), "kept": True,
                        "value": mapped.get(q_field),
                    })
                else:
                    # THE RESCUE CASE (2026-08-14). A "No" is blanked here for two
                    # very different reasons and only one of them is a real
                    # rejection: either the quote is not in the document (a
                    # fabrication - stays blanked, no appeal), or the quote IS in
                    # the document but carries no negation WORD. The second is the
                    # measured false negative: "All vehicles are owned by the
                    # applicant" answers "any vehicles NOT solely owned?" with a
                    # plain No and contains no cue. Queue those - and only those -
                    # for the judge, which reads implication instead of vocabulary.
                    _rescuable = bool(
                        quote and _evidence_hay
                        and _quote_grounds_claim(quote, _evidence_hay,
                                                 _evidence_sentences if exp_field else None)
                        and not _quote_expresses_negative(quote)
                    )
                    _prev_val, _prev_exp = mapped.get(q_field), (
                        mapped.get(exp_field) if exp_field else None)
                    mapped[q_field] = None             # ungrounded "No" -> blank
                    if exp_field:
                        mapped[exp_field] = None
                    _gated += 1
                    if _rescuable:
                        _judge_review.append({
                            "id": q_field, "answer": "No", "exp_field": exp_field,
                            "quote": str(quote or "").strip(), "kept": False,
                            "value": _prev_val, "exp_value": _prev_exp,
                        })
            else:
                mapped[q_field] = None                 # not a valid Y/N token
                if exp_field:
                    mapped[exp_field] = None
                _gated += 1

        # ── Pass A2: the semantic judge ───────────────────────────────────────
        # One batched call decides what no word list can: does this quote
        # actually support this answer to this question? It reviews BOTH
        # directions - rejecting a kept answer whose evidence does not support
        # it, and restoring a "No" that was blanked only because its genuine
        # implied denial contained no negation word.
        #
        # SILENCE IS NOT A VERDICT. A field the judge does not return keeps its
        # deterministic decision, so a failed call, a missing API key or an
        # offline test run changes nothing at all.
        if _judge_review:
            try:
                _j_items = []
                for _it in _judge_review:
                    if not str(_it.get("quote") or "").strip():
                        continue
                    _tu = str((schema.get(_it["id"]) or {}).get("tu") or "")
                    _j_items.append({
                        "id": _it["id"], "answer": _it["answer"],
                        "quote": _it["quote"],
                        "question": _compliance_question_text(_tu) or _tu,
                    })
                _verdicts = _judge_evidence_batch(_j_items, form_id or "")
                _j_rejected = _j_rescued = 0
                for _it in _judge_review:
                    _v = _verdicts.get(_it["id"])
                    if _v is None:
                        continue                       # no opinion -> stand pat
                    if _it["kept"] and _v is False:
                        mapped[_it["id"]] = None
                        if _it.get("exp_field"):
                            mapped[_it["exp_field"]] = None
                        _gated += 1
                        _j_rejected += 1
                        logger.info(
                            "evidence_judge REJECTED form=%s field=%s answer=%s "
                            "quote=%r - the cited sentence does not support this "
                            "answer", form_id or "unknown", _it["id"],
                            _it["answer"], str(_it["quote"])[:120],
                        )
                    elif not _it["kept"] and _v is True:
                        mapped[_it["id"]] = _it.get("value")
                        if _it.get("exp_field") and _it.get("exp_value"):
                            mapped[_it["exp_field"]] = _it["exp_value"]
                        _gated = max(0, _gated - 1)
                        _j_rescued += 1
                        logger.info(
                            "evidence_judge RESCUED form=%s field=%s answer=%s "
                            "quote=%r - a genuine implied answer the negation-cue "
                            "test could not see", form_id or "unknown", _it["id"],
                            _it["answer"], str(_it["quote"])[:120],
                        )
                if _verdicts:
                    logger.info(
                        "evidence_judge form=%s reviewed=%d judged=%d rejected=%d "
                        "rescued=%d", form_id or "unknown", len(_j_items),
                        len(_verdicts), _j_rejected, _j_rescued,
                    )
            except Exception as _je:                       # noqa: BLE001
                logger.warning("evidence_judge skipped (form=%s): %s",
                               form_id or "unknown", _je)

        # ── Pass C: promote via non-adjacent companion fields ─────────────────
        # Mirrors Pass B's "rescue a stranded grounded Yes" but for the
        # _NONADJACENT_QUESTION_COMPANIONS pattern instead of the adjacent-
        # Explanation pattern - covers BOTH (a) the model never attempted the
        # question's own Y/N at all, and (b) it did, but Pass A above gated it
        # to blank for lack of its own quote. Either way, a companion field
        # (e.g. the "Name of Other Owner" box) that is independently, genuinely
        # present in the document is real, on-topic proof the answer is "Y" -
        # never overrides an explicit, already-kept "Yes" or gate-approved "No".
        for _q_field, _companions in _NONADJACENT_QUESTION_COMPANIONS.items():
            if _q_field not in schema:
                continue
            current = str(mapped.get(_q_field) or "").strip().lower()
            if current in _AFFIRMATIVE_VALUES or current in _NEGATIVE_VALUES:
                continue
            for _companion in _companions:
                if _present(mapped.get(_companion), _companion):
                    mapped[_q_field] = "Y"
                    break

        # ── Pass B: narrative fields not owned by a kept "Yes" above ──────────
        # An "…Explanation"/"…OtherDescription"/"…ResolutionDescription" value
        # must be grounded in the document or it is AI-invented prose.
        #   * Unpaired (standalone "Other, please specify") -> keep iff present.
        #   * Paired to a Question code that is a kept "Yes" -> already handled.
        #   * Paired but the question is blank -> if the explanation is a real,
        #     document-present, AFFIRMATIVE statement, promote the question to
        #     "Y" so genuine grounded info is not stranded; if it expresses a
        #     negative (evidence for "No", not "Yes") or is ungrounded, blank it
        #     - never manufacture a "Yes" from a negative (the live ACORD 125
        #     "sexual-abuse claims = Y" bug).
        for exp_field in list(gpt_filled_set):
            # In scope for Pass B when EITHER the field's own name is
            # Explanation-shaped, OR it was recognized as a dependent target
            # via the pairing fallback (_PAIRING_ONLY_TOKENS) - a "...
            # Description"/"...Cost" field with no name-shape signal of its
            # own still needs the same grounding/rescue treatment once
            # position has confirmed it's genuinely dependent on a question.
            if not (_is_evidence_required_field(exp_field) or exp_field in _exp_to_q):
                continue
            val = mapped.get(exp_field)
            if val is None or not str(val).strip():
                continue
            q_field = _exp_to_q.get(exp_field)
            if q_field is None:
                if not _present(val, exp_field):
                    mapped[exp_field] = None
                    _gated += 1
                continue
            if str(mapped.get(q_field) or "").strip().lower() in _AFFIRMATIVE_VALUES:
                continue                               # owned by a kept "Yes"
            q_blank = not str(mapped.get(q_field) or "").strip()
            # The dedicated compliance pass is AUTHORITATIVE for a Yes/No question
            # whose tooltip is the ACORD "Enter Y…" convention: it saw the same
            # document and deliberately left this question blank (no Yes evidence).
            # Do NOT let a stray explanation the GENERAL field-fill happened to
            # write promote it to "Y" — that manufactured false "Yes" answers
            # (e.g. "products of others repackaged under applicant label = Y" with
            # a borrowed COI sentence). Blank the stray explanation instead. The
            # promotion path remains for non-compliance fields (the OtherIndicator
            # / companion patterns Pass B/C were originally built for).
            _q_tu = str((schema.get(q_field) or {}).get("tu", "") or "")
            _q_is_compliance = _q_tu.startswith(_YES_NO_TOOLTIP_PREFIX)
            if q_blank and not _q_is_compliance and _present(val, exp_field) \
                    and not _quote_expresses_negative(val) and not _is_nonfillable_field(q_field):
                mapped[q_field] = "Y"                  # rescue a stranded grounded Yes
            else:
                mapped[exp_field] = None
                _gated += 1

        if _gated:
            logger.info("map_facts EVIDENCE_GATE form=%s | dropped_ungrounded=%d",
                        form_id or "unknown", _gated)

    # ── ACORD 101 overflow routing (opt-in, Figure 29) ───────────────────────
    # Oversized operations/classification narrative and accumulated remarks are
    # routed IN FULL to this form's Additional Remarks rows. Only ACORD 101 owns
    # these fields, so this is self-contained and lossless for every other form.
    if form_id == "ACORD_101":
        try:
            from config.settings import ENABLE_ACORD101_OVERFLOW
        except Exception:                          # noqa: BLE001
            ENABLE_ACORD101_OVERFLOW = False
        if ENABLE_ACORD101_OVERFLOW:
            _apply_acord101_overflow(mapped, schema, facts, _deterministic_filled)

    # ── Post-fill deterministic guards ───────────────────────────────────────
    # Enforce invariants the gap-fill prompt can only request, not guarantee:
    # legal-entity mutual exclusion and repeating-row de-duplication. Runs on the
    # merged result so it corrects values from any source (Pass 1, alias, GPT).
    _enforce_post_fill_guards(mapped, schema, facts, gpt_filled_set)

    # ── Guard: ungrounded industry-classification codes ───────────────────────
    # Runs BEFORE the trust-labelling pass below so a dropped value can never be
    # painted "ai_verified" on its way out.
    _dropped_codes = _drop_ungrounded_classification_codes(mapped, raw_text, gpt_filled_set)

    # ── Guard: insured's own address bleeding into a third party's block ──────
    _dropped_addr = _drop_third_party_address_bleed(mapped, facts, gpt_filled_set)

    # ── Guard: a NAIC number labelled for one entity, stamped for another ─────
    _dropped_naic = _drop_mislabeled_naic_codes(mapped, raw_text, gpt_filled_set)

    # ── Guard: a percentage nothing states, and a row about a party who is
    # not on the form. Both were live 2026-08-14 ACORD 125 defects, and both
    # are stated once by RULE rather than per-box: 74 percentage fields across
    # 8 forms, and ACORD's own "As used here ... insured" row convention.
    try:
        _dropped_pct = _drop_unstated_percentages(mapped, raw_text, gpt_filled_set,
                                                  gpt_question_grounding)
        for _f in _dropped_pct:
            gpt_filled_set.discard(_f)
    except Exception as _pct_ex:                          # noqa: BLE001
        logger.warning("percentage guard skipped (form=%s): %s", form_id, _pct_ex)
        _dropped_pct = []
    try:
        _dropped_party = _drop_unanchored_party_rows(mapped, schema)
        for _f in _dropped_party:
            gpt_filled_set.discard(_f)
    except Exception as _pr_ex:                           # noqa: BLE001
        logger.warning("party-row guard skipped (form=%s): %s", form_id, _pr_ex)
        _dropped_party = []

    # ── Guard: an Additional Interest assembled from other parties' details,
    # and one premises stamped as several location rows. Both live 2026-08-14
    # ACORD 125 defects; both row-ATOMIC, because the run also proved that
    # blanking one field of a fabricated row leaves an orphan that reads like
    # sparse real data.
    try:
        _dropped_ai = _drop_fabricated_interest_rows(mapped, gpt_filled_set, facts)
        for _f in _dropped_ai:
            gpt_filled_set.discard(_f)
    except Exception as _ai_ex:                           # noqa: BLE001
        logger.warning("interest-row guard skipped (form=%s): %s", form_id, _ai_ex)
        _dropped_ai = []
    try:
        _dropped_loc = _dedupe_stamped_premises_rows(mapped, gpt_filled_set)
        for _f in _dropped_loc:
            gpt_filled_set.discard(_f)
    except Exception as _loc_ex:                          # noqa: BLE001
        logger.warning("premises-row guard skipped (form=%s): %s", form_id, _loc_ex)
        _dropped_loc = []

    # ── DELIBERATELY NOT GUARDED: one printed value in two row columns ───────
    # Run 9's ACORD 127 duplicated three values across vehicle columns -
    # CLASS 7383 -> SIC 7383, TERR 111 -> FARTHEST ZONE 111, SYM 07 -> NET VEH
    # DR/CR 07 - and a "two columns must not share a value" guard was built,
    # tested and REMOVED before shipping. It cannot be made safe by field name:
    # `Vehicle_ComprehensiveSymbolCode` and `Vehicle_CollisionSymbolCode` are
    # BOTH legitimately "07" on this very package (the ground-truth fixture
    # confirms both), and they are structurally indistinguishable from
    # `RateClassCode` vs `SpecialIndustryClassCode`, which are two different
    # taxonomies that must never agree.
    #
    # Neither side is deterministic here either - no `_SCHEDULE_REGISTRY` entry
    # binds these columns - so there is no trustworthy witness to keep and no
    # honest way to choose which duplicate dies. Blanking a covered-auto symbol
    # is a COVERAGE MISSTATEMENT; a wrong industry class in a rating box is a
    # figure the underwriter re-rates anyway. Trading the second for the first
    # is the wrong direction, so this stays open and visible rather than
    # half-fixed. Closing it properly needs the dec index to say which column
    # the document actually printed - see CALL2_RETRIEVAL_REDESIGN.

    # ── Guard: a coverage LINE standing where a fact should be ───────────────
    # Run 9, ACORD 126: the Products/Completed Operations schedule came back
    # with "Commercial Auto Liability" and "Commercial Inland Marine" as
    # products the applicant manufactures, dated with the policy effective
    # date. An LOB name is a closed vocabulary (see _LOB_NAMES); it is
    # legitimate ONLY in boxes that ask for a line of business by name - Q4's
    # other-insurance rows, loss-history LOB, prior-coverage columns - which
    # the marker regex allow-lists by field name. Source-agnostic per the
    # fourth-door rule. Blanking a product NAME unanchors its row, so the late
    # unanchored sweep clears the borrowed dates and amounts that rode along.
    try:
        for _f in list(mapped.keys()):
            _v = mapped.get(_f)
            if not _v or not isinstance(_v, str):
                continue
            if _LOB_FIELD_ALLOWED_RE.search(_f):
                continue
            if _is_line_of_business_name(_v):
                logger.info(
                    "guard LOB_NAME_OUT_OF_PLACE form=%s field=%s value=%r - a "
                    "line of business is not a product, party or description",
                    form_id or "unknown", _f, str(_v)[:60],
                )
                mapped[_f] = None
                gpt_filled_set.discard(_f)
            # ...and a bare dollar amount in a *Description box: run 9 put
            # "$2,000,000" in the LIMIT APPLIES PER "OTHER:" description. A
            # description that is nothing but money describes nothing.
            elif "Description" in _f and _BARE_MONEY_VALUE_RE.match(_v.strip()):
                logger.info(
                    "guard MONEY_IN_DESCRIPTION_BOX form=%s field=%s value=%r",
                    form_id or "unknown", _f, _v.strip()[:40],
                )
                mapped[_f] = None
                gpt_filled_set.discard(_f)
    except Exception as _lob_ex:                          # noqa: BLE001
        logger.warning("LOB-name guard skipped (form=%s): %s", form_id, _lob_ex)

    # ── SHADOW ONLY: which AI values are not in the document at all? ─────────
    # Reports, never blanks. Runs AFTER the guards above so it does not report
    # values they already removed. See _report_ungrounded_ai_values.
    _report_ungrounded_ai_values(mapped, schema, raw_text, gpt_filled_set, form_id)

    # ── Guard: another party's value in an applicant-owned box ───────────────
    # The gap-fill counterpart to the deterministic `_entity_mismatch` guard.
    # Never raises: an ownership fault must not break generation.
    try:
        _dropped_entity = _drop_foreign_entity_values(mapped, facts, gpt_filled_set)
    except Exception as _ent_ex:                          # noqa: BLE001
        logger.warning("foreign-entity check skipped (form=%s): %s", form_id, _ent_ex)
        _dropped_entity = []

    # ── Guard: a gap-fill value that is IMPOSSIBLE for its field ─────────────
    # Demoting was not enough. `0482854` - the carrier's ACCOUNT number - kept
    # landing in the FEIN box across four consecutive live runs. It turned orange
    # each time, so we stopped CLAIMING it was verified, but a 7-digit string in
    # a 9-digit federal tax ID box is not "uncertain", it is impossible.
    #
    # The distinction that keeps this consistent with "stamp it and highlight
    # it": that rule is for values we are UNSURE about. A value the field's own
    # registry validator rejects outright is not one of those, and a wrong tax ID
    # on a submitted ACORD is a compliance problem. Scoped to the FOUR hard
    # shapes only (FEIN, email, phone, URL - see `_shape_violation`) and to
    # GAP-FILL values, so a deterministic or client-supplied value is never
    # touched. Everything else still demotes rather than blanks.
    for _f in list(gpt_filled_set):
        _why = _shape_violation(_f, mapped.get(_f))
        if _why:
            mapped[_f] = None
            _dropped_entity.append(_f)
            logger.info("impossible_value blanked=%s — %s", _f, _why)

    # ── Guard: the CARRIER or PRODUCER named as an additional interest ───────
    # Live run: "Emc Property & Casualty Company" as the ADDITIONAL INSURED —
    # the carrier added as an additional insured on the policy it issues. The
    # orphan-row sweep below only clears NAMELESS rows, so a wrongly-NAMED row
    # survived it. Value-identity against the carrier/producer facts we already
    # hold (same shape as _drop_foreign_entity_values, including the
    # carrier-family token so "EMC P&C" matches "Employers Mutual Casualty");
    # blanking the name here makes the row unanchored, and the orphan sweep
    # then clears its row-mates. A genuine third-party interest (a bank, a
    # lessor) matches no held fact and is untouched.
    try:
        _foreign_map = _foreign_party_values(facts)
        # The INSURED's own identity is equally impossible as an additional
        # interest: an entity cannot be a third-party interest on its own
        # policy. Graded test run: the SECOND NAMED INSURED's name landed in
        # the interest NAME box over the lender's address.
        _insured_tokens: set = set()
        for _k in ("applicant_name", "dba_name"):
            _iv = _fv(facts, _k)
            if _iv and str(_iv).strip():
                _insured_tokens.add(_identity_token(_iv))
        _ani = _fv(facts, "additional_named_insureds")
        if isinstance(_ani, list):
            for _iv in _ani:
                if _iv and str(_iv).strip():
                    _insured_tokens.add(_identity_token(_iv))
        _insured_tokens.discard("")
        if _foreign_map or _insured_tokens:
            # Scoped to AdditionalInterest ONLY: CertificateHolder keeps its
            # deliberate demote-not-blank contract (its fact-driven value is
            # flagged for review, never deleted — guarded by
            # test_deterministically_filled_owner_field_still_gets_flagged).
            _interest_name_re = re.compile(
                r"^AdditionalInterest_\w*FullName_[A-N]$")
            for _f in list(mapped.keys()):
                _v = mapped.get(_f)
                if _v is None or not _interest_name_re.match(_f):
                    continue
                # A deterministically-seeded loss-payee name is never blanked.
                if _f in _deterministic_filled:
                    continue
                _tok = _identity_token(_v)
                _hit = _tok in _foreign_map or _tok in _insured_tokens
                if not _hit:
                    try:
                        from services.normalization import normalize_carrier
                        _fam = _identity_token(normalize_carrier(str(_v)))
                        _hit = len(_fam) >= 3 and _fam in _foreign_map
                    except Exception:                     # noqa: BLE001
                        pass
                if _hit:
                    logger.info("foreign_interest blanked=%s value=%r", _f, str(_v)[:60])
                    mapped[_f] = None
                    gpt_filled_set.discard(_f)
    except Exception as _fi_ex:                           # noqa: BLE001
        logger.warning("foreign-interest check skipped (form=%s): %s", form_id, _fi_ex)

    # ── Guard: a PERCENTAGE nobody wrote down ────────────────────────────────
    # ACORD declares these fields itself ("Enter percentage:"). A percentage
    # is either printed in the document or it is unknown - it can never be
    # inferred from coverage text. Live runs produced 0%/0% on one pass and
    # 100%/100% on the next for the SAME dec page, which states no percentage
    # at all. Kept only when the document actually prints that figure as a
    # percentage; the client questionnaire owns the rest.
    try:
        for _f in list(gpt_filled_set):
            _v = mapped.get(_f)
            if _v is None or not str(_v).strip():
                continue
            _meta = schema.get(_f)
            _tip = (_meta or {}).get("tu", "") if isinstance(_meta, dict) else ""
            if not str(_tip).lower().startswith("enter percentage"):
                continue
            _digits = re.sub(r"\D", "", str(_v))
            if not _digits:
                continue
            if not re.search(rf"\b{re.escape(_digits)}\s*(?:%|percent)", raw_text or "", re.I):
                logger.info("percent_not_in_document blanked=%s value=%r", _f, str(_v)[:20])
                mapped[_f] = None
                gpt_filled_set.discard(_f)
    except Exception as _pct_ex:                          # noqa: BLE001
        logger.warning("percent check skipped (form=%s): %s", form_id, _pct_ex)

    # ── Guard: a policy date repurposed as the business start date ───────────
    # Client rule, verbatim: "Do not treat the policy inception date as the
    # business inception date." Same equality-only mechanism as the event-date
    # guard — no topic matching. Covers every fill source: extraction has
    # stamped the policy effective date into the business_start_date fact
    # itself on consecutive live runs.
    try:
        _policy_dates = _policy_metadata_dates(facts)
        if _policy_dates:
            for _f in list(mapped.keys()):
                if "BusinessStartDate" not in _f or mapped.get(_f) is None:
                    continue
                _dk = _normalized_date_key(mapped[_f])
                if _dk and _dk in _policy_dates:
                    logger.info(
                        "policy_date_echo blanked=%s value=%r", _f, str(mapped[_f])[:20])
                    mapped[_f] = None
                    gpt_filled_set.discard(_f)
    except Exception as _bd_ex:                           # noqa: BLE001
        logger.warning("start-date echo check skipped (form=%s): %s", form_id, _bd_ex)

    # ── Guard: the POLICY talking about itself, in a box about the APPLICANT ──
    # `Subsidiary_ParentSubsidiaryRelationshipDescription_A` came back holding
    # endorsement wording. The client had already named the rule for the Y/N
    # gate: "Never convert generic policy terminology into applicant-history
    # facts." It is the same error in a narrative box, and the gate never saw it
    # because the gate only runs on Yes/No fields.
    #
    # Same two patterns, same anchors - the INSURER speaking as a party
    # ("relieve us", "under this policy") or an exclusion clause. Remarks fields
    # are exempt: ACORD 101's overflow rows carry policy text by design. Scoped
    # to GAP-FILL narrative, so nothing deterministic or client-supplied moves.
    for _f in list(gpt_filled_set):
        if _is_policy_contract_language(_f, mapped.get(_f)):
            logger.info("policy_language blanked=%s — %s", _f, str(mapped[_f])[:80])
            mapped[_f] = None
            _dropped_entity.append(_f)
        elif _is_negation_sentence_in_name_field(_f, mapped.get(_f)):
            logger.info("negation_in_name blanked=%s — %s", _f, str(mapped[_f])[:80])
            mapped[_f] = None
            _dropped_entity.append(_f)
        elif _duplicates_primary_row_narrative(_f, mapped.get(_f), mapped):
            logger.info("row_narrative_copy blanked=%s — %s", _f, str(mapped[_f])[:80])
            mapped[_f] = None
            _dropped_entity.append(_f)
        elif _duplicates_primary_sibling(_f, mapped.get(_f), mapped):
            logger.info("secondary_copy blanked=%s — %s", _f, str(mapped[_f])[:60])
            mapped[_f] = None
            _dropped_entity.append(_f)

    # ── Guard: a second box claiming a value the document printed once ────────
    # Live 2026-08-13: the producer's PHONE stamped into the FAX box, and the
    # total premium stamped into the DEPOSIT box, on a package that prints
    # neither a fax number nor a deposit. Adjudicated against the declarations
    # index, never against field names - see the function for why the obvious
    # "same parent, equal value" rule was measured and thrown away.
    try:
        _entries = (facts or {}).get("dec_page_entries")
        if isinstance(_entries, list) and _entries:
            for _f in list(gpt_filled_set):
                _src = _second_claim_on_a_single_printed_value(
                    _f, mapped, gpt_filled_set, _entries)
                if _src:
                    logger.info(
                        "single_printed_value blanked=%s — %r is already stamped "
                        "in %s and the declarations print it under one label only",
                        _f, str(mapped[_f])[:40], _src,
                    )
                    mapped[_f] = None
                    _dropped_entity.append(_f)
    except Exception as _sp_ex:                               # noqa: BLE001
        logger.warning("single-printed-value check skipped (form=%s): %s",
                       form_id, _sp_ex)

    # ── Guard: a count that counts something which must exist ─────────────────
    # Live 2026-08-13: NO. OF MEMBERS AND MANAGERS = 0 with the LLC box ticked.
    # A limited liability company with zero members is not a company; the model
    # returned 0 where it meant "the document does not say", and 0 is the one
    # answer that reads as a fact rather than as an absence. Blank routes it to
    # the client questionnaire, which is where the real number lives.
    for _f in list(gpt_filled_set):
        if _rejects_impossible_count(_f, mapped.get(_f)):
            logger.info("impossible_count blanked=%s value=%r",
                        _f, str(mapped[_f])[:20])
            mapped[_f] = None
            _dropped_entity.append(_f)

    # ── Guard: a schedule row with no identity carries no detail ──────────────
    # Runs BEFORE the row-label guard so its clears are visible to nothing that
    # matters, and independent of it. See _unanchored_schedule_row_fields for
    # the live ACORD 127 row-2 case (GL class code 91585 as a vehicle's rate
    # class on a run where extraction missed the vehicle schedule).
    try:
        _ghost_rows = _unanchored_schedule_row_fields(mapped, schema, gpt_filled_set)
        if _ghost_rows:
            logger.info(
                "unanchored_schedule_row cleared=%d field(s) — rows with no "
                "identity: %s", len(_ghost_rows), sorted(_ghost_rows)[:6],
            )
            for _f in _ghost_rows:
                mapped[_f] = None
                _dropped_entity.append(_f)
                gpt_filled_set.discard(_f)
    except Exception as _gr_ex:                               # noqa: BLE001
        logger.warning("unanchored-schedule-row check skipped (form=%s): %s",
                       form_id, _gr_ex)

    # ── Guard: a driver's PERSONAL data may only come from the driver record ──
    # Live ACORD 127: the driver row printed SEX F (inferred from the first
    # name), MAR STAT U (invented outright) and YEAR LIC 2012 - the VEHICLE'S
    # model year - for a person the package names once, in a Drive Other Car
    # endorsement. Type checks cannot catch these: "F" is a valid gender code
    # and 2012 a valid year. What is wrong is ATTRIBUTION - a sex code or a
    # licence year found loose in 271 pages of policy text cannot be pinned to a
    # specific scheduled driver by list position. Only the driver RECORD can
    # say, and record-backed values arrive through `_resolve_schedule_row`, not
    # gap fill - so clearing the gap-fill channel loses nothing that was ever
    # attributable.
    # SOURCE-AGNOSTIC, and that distinction is the lesson of six runs. A guard
    # that judges MODEL BEHAVIOUR (a hallucinated key, an ungrounded quote)
    # belongs scoped to `gpt_filled_set`. A guard that judges whether a value is
    # POSSIBLE FOR ITS BOX does not: a sex code inferred from a first name and a
    # licence year borrowed from a vehicle are wrong whichever pass stamped
    # them, and scoping them to gap fill just meant Pass 1.5 delivered the same
    # values through a door the guard could not see.
    for _f in list(mapped.keys()):
        if _DRIVER_PERSONAL_COLUMN_RE.match(_f) and str(mapped.get(_f) or "").strip():
            logger.info("driver_personal_unattributable blanked=%s value=%r",
                        _f, str(mapped[_f])[:24])
            mapped[_f] = None
            _dropped_entity.append(_f)
            gpt_filled_set.discard(_f)

    # ── Guard: a schedule row LABEL in a party's NAME box ─────────────────────
    # "Location 000" as an ADDITIONAL INTEREST. Must run BEFORE the unanchored-row
    # sweep below, which is what then clears the address, item class and reason
    # that were sitting in the same row - blanking the name alone would leave the
    # debris behind. See _is_row_label_not_a_name for why the existing
    # address-bleed guard could not catch this one.
    # Source-agnostic for the same reason: "Location 000" is not the legal name
    # of a party whichever pass wrote it there.
    for _f in list(mapped.keys()):
        if _is_row_label_not_a_name(_f, mapped.get(_f)):
            logger.info("row_label_as_name blanked=%s value=%r — a schedule row "
                        "label is not a party", _f, str(mapped[_f])[:40])
            mapped[_f] = None
            _dropped_entity.append(_f)
            gpt_filled_set.discard(_f)
            continue

    # The truncated-copy check runs over EVERY narrative field, not just
    # gap-fill. Run 6: "COMMERCIAL GENERAL CONTRA" - the carrier's own cut-off
    # header, already twice rejected by the merge - reached the premises
    # DESCRIPTION OF OPERATIONS box through a deterministic fact path this
    # time. Inside this function every value is document-derived (client and
    # producer answers arrive later, through ARQ), so no provenance is being
    # overridden: a cut-off head of a value we hold in full is wrong from any
    # source.
    for _f in list(mapped.keys()):
        if not mapped.get(_f):
            continue
        _fuller = _is_truncated_copy_of_a_held_value(
            _f, mapped.get(_f), mapped, facts)
        if _fuller:
            logger.info(
                "truncated_copy blanked=%s value=%r — it is the cut-off head of "
                "%r, which we hold in full", _f, str(mapped[_f])[:40], _fuller[:60],
            )
            mapped[_f] = None
            _dropped_entity.append(_f)
            gpt_filled_set.discard(_f)

    # Values that were just blanked are no longer AI-filled - drop them from the
    # fill set so downstream confidence/QA passes don't reason about a dead value.
    for _df in (_dropped_codes + _dropped_addr + _dropped_naic + _dropped_entity):
        gpt_filled_set.discard(_df)

    # ── WHY THE SCREEN SHOWS NO WARNINGS WHILE THE FORM HAD DEFECTS ──────────
    # Owner asked three times running: "no hard stops/warnings - investigate."
    # The stops engine is NOT broken. It validates the extracted FACTS
    # (`evaluate_stops(facts, flags)`), and on this package the facts are clean,
    # so it correctly returns hard=0 soft=0 - proven by the `evaluate_stops:`
    # line in extraction_pipeline and by the one run where extraction genuinely
    # missed payroll and the GL-exposure warning DID appear on screen.
    #
    # THE GAP IS ELSEWHERE, and it is real: the guards in this function fix
    # STAMPED VALUES, and nothing they do reaches the user. A form where fifteen
    # fabricated values were caught and blanked is indistinguishable, on screen,
    # from a form that was right the first time - same silence, same empty
    # boxes. That is the missing feedback loop, not a missing validator.
    #
    # The full accounting is taken as a diff against `_pre_guard_values` just
    # before `return`, so a guard added later is reported without anyone having
    # to remember to register it. See "THE GUARD REGION BEGINS HERE".

    # ── A dec-page LABEL standing as a party's NAME ───────────────────────────
    # Run 6, ACORD 127: the ADDITIONAL INTEREST block came back with "Blanket
    # Additional Insured Status For Persons Or Organizations On A Primar..." as
    # the party NAME - an endorsement TITLE - plus the PRODUCER'S address and
    # the carrier's account number for a loan reference. The row-label guard
    # ("Location 000") cannot see it: this name has no ordinal. But it IS a
    # printed dec line, and a coverage line in a party name box is the same
    # artifact wherever it lands. Blanking the name unanchors the row; the late
    # unanchored sweep below then clears the address and reference with it.
    try:
        _dec_lines_late = _dec_coverage_line_set(facts)
        for _f in list(gpt_filled_set):
            if _INTEREST_NAME_RE.match(_f) and mapped.get(_f) and \
                    _is_coverage_artifact_text(mapped[_f], _dec_lines_late, facts):
                logger.info(
                    "interest_name_is_coverage_artifact blanked=%s value=%r",
                    _f, str(mapped[_f])[:60],
                )
                mapped[_f] = None
                gpt_filled_set.discard(_f)
    except Exception as _in_ex:                               # noqa: BLE001
        logger.warning("interest-name artifact check skipped (form=%s): %s",
                       form_id, _in_ex)

    # ── Unanchored schedule rows, SECOND pass ─────────────────────────────────
    # The first pass (with the other entity guards above) runs BEFORE the
    # duplicate-identity guards - Guard 11 (a repeating row that is row A
    # reformatted) and the sibling dedup. Live run 5: gap fill copied enough of
    # the Subaru's identity into vehicle row B that the row looked ANCHORED at
    # first-pass time; the duplicate guards then stripped the copied identity
    # and left the GL class code, the borrowed $10,000 and the county sitting
    # in a row that no longer had a subject. Judging anchor state is only sound
    # AFTER everything that can remove an anchor has run, so the sweep runs
    # again here - idempotent, cheap, and a no-op when the first pass was right.
    try:
        _ghost2 = _unanchored_schedule_row_fields(mapped, schema, gpt_filled_set)
        if _ghost2:
            logger.info(
                "unanchored_schedule_row (late pass) cleared=%d field(s): %s",
                len(_ghost2), sorted(_ghost2)[:6],
            )
            for _f in _ghost2:
                mapped[_f] = None
                gpt_filled_set.discard(_f)
    except Exception as _gr2_ex:                              # noqa: BLE001
        logger.warning("late unanchored-row sweep skipped (form=%s): %s",
                       form_id, _gr2_ex)

    # ── Yes-substantiation, SECOND pass - same ordering disease ──────────────
    # The gate checks a Yes's dependent section while the junk that "populated"
    # it is still standing; the artifact and entity guards then clear those
    # cells, and the Yes survives orphaned. Live run 5, Q1: Y over an owner
    # table whose cells were filled at gate time and empty on the printed form.
    # A Yes owes its substantiation at the END of the pipeline, not the middle.
    try:
        _pairs2 = _question_explanation_pairs(schema)
        # include_paired: the orphan direction below must also judge a PAIRED
        # question's sibling table (run 9, 126 Q5's equipment rows standing
        # under a blank question). The Yes-substantiation direction further
        # down keys off the same dict; for a paired question a filled
        # explanation ALSO substantiates, which _present/_final_yn_coherence
        # already guarantee, so widening the dict cannot blank a paired Yes
        # that carries its explanation - its deps only matter when the
        # question is NOT Yes.
        _deps2 = _unpaired_question_deps(schema, _pairs2, include_paired=True)
        for _q, _dep_fields in _deps2.items():
            _qv = str(mapped.get(_q) or "").strip().lower()
            if _qv not in _AFFIRMATIVE_VALUES:
                # THE MIRROR: dependents standing under a question that is NOT
                # Yes. Run 6, Q14: the question itself was blank while its
                # conviction table carried the insured's own city as PLACE and
                # a borrowed "1" as YEARS REVOKED - details of an incident the
                # form does not assert. Same principle as Guard 5 ("an
                # explanation without a Yes"), extended to table dependents.
                # Gap-fill cells only; a client's or resolver's row is not ours
                # to delete.
                for _d in _dep_fields:
                    if _d in gpt_filled_set and str(mapped.get(_d) or "").strip():
                        logger.info(
                            "evidence_gate DEP_WITHOUT_YES (late) form=%s "
                            "question=%s cleared=%s value=%r",
                            form_id, _q, _d, str(mapped[_d])[:40],
                        )
                        mapped[_d] = None
                        gpt_filled_set.discard(_d)
                continue
            # A PAIRED question's Yes stands on its explanation - its sibling
            # table is optional refinement, so its emptiness proves nothing.
            # Only the widened DEP_WITHOUT_YES direction above may touch
            # paired questions; this direction keeps its original unpaired
            # scope (paired naked-Yes is _final_yn_coherence's invariant 1).
            if _q in _pairs2:
                continue
            if not any(str(mapped.get(_d) or "").strip() for _d in _dep_fields):
                logger.info(
                    "evidence_gate YES_WITHOUT_SUBSTANTIATION (late) form=%s "
                    "field=%s - its dependent section emptied out downstream",
                    form_id, _q,
                )
                mapped[_q] = None
                gpt_filled_set.discard(_q)
    except Exception as _ys_ex:                               # noqa: BLE001
        logger.warning("late Yes-substantiation sweep skipped (form=%s): %s",
                       form_id, _ys_ex)

    # ── FINAL Yes/No coherence sweep - must stay the LAST mutation ───────────
    # The policy-contract-language guard directly above blanks explanations
    # holding contract wording - which is exactly what the evidence gate wrote
    # there for a Yes it kept on an exclusion quote. Guard 9 ran before that
    # and could not see it. Anything that mutates `mapped` must be inserted
    # ABOVE this call, never below it.
    _final_yn_coherence(mapped, schema, form_id, gpt_filled_set)

    # ── Raw-text verification (Figure 26 trust check — no LLM) ────────────────
    # Confirm every value the AI filled actually appears in the uploaded document
    # text. Runs on the PRE-canonicalization value so our own display formatting
    # can never break the match. A value found in the documents is trusted (→
    # "ai_verified", painted pink); a value the AI produced that is NOT present —
    # a guess, or a "copied" claim we cannot locate — stays "low_confidence"
    # (painted orange) for review. Deterministic (fact) and client values are
    # never checked. Yes/No answers are skipped inside _value_in_raw_text.
    _ai_verified_fields: set = set()
    if raw_text and gpt_filled_set:
        _hay = _normalize_for_search(raw_text)
        for _f in gpt_filled_set:
            _v = mapped.get(_f)
            if _v is not None and _value_in_raw_text(str(_v), _hay):
                _ai_verified_fields.add(_f)

    # ── Owner/insured field contamination override (Figure 33 client feedback)
    # An owner/insured NAME field must never be silently trusted just because
    # it was filled by a deterministic rule, or because its value passed the
    # generic raw-text check above - neither proves the value belongs in THIS
    # field's ROLE. Values that look like carrier/policy data in an owner/
    # insured slot are forced to low_confidence (reviewable, never blanked -
    # values are never deleted here, only their trust label changes).
    #
    # Checks EVERY owner/insured field with a value, regardless of fill source
    # (deterministic rule, alias stamp, or GPT). Originally scoped to GPT-
    # filled fields only, on the theory that a deterministic rule is "trusted
    # by construction" - reconsidered after a live test showed the gap
    # concretely: CertificateHolder_FullName has its OWN deterministic rule
    # (-> the "certificate_holder" fact, a different key from "carrier_name"),
    # so when a document's extracted certificate_holder happens to equal its
    # carrier, the field was filled deterministically and stayed fully
    # trusted (no highlight) - correctly caught by the separate post-
    # generation warning either way, but confusingly inconsistent with the
    # orange highlight a GPT-filled equivalent would have gotten. Checking
    # every source uniformly removes that inconsistency; the check itself
    # (is_value_contaminated) is unchanged.
    #
    # No underwriting_confirmations here (not available at this call depth) -
    # uses whichever carrier/applicant facts are already in `facts`. Never
    # raises: a detector fault must never break generation.
    _owner_field_contamination: set = set()
    try:
        from services.field_mapping_integrity import is_insured_owner_field, is_value_contaminated
        for _f, _v in mapped.items():
            if _v is None or not is_insured_owner_field(_f):
                continue
            if is_value_contaminated(_f, _v, facts):
                _owner_field_contamination.add(_f)
    except Exception as _cont_ex:
        logger.warning("owner-field contamination check skipped (form=%s): %s", form_id, _cont_ex)

    # ── Stamp-time shape failures (client #8, #11) ───────────────────────────
    # A value that cannot possibly be a valid instance of its field must never be
    # labelled `ai_verified` - that label means "confirmed present in the
    # uploaded documents", and the client's form showed a 7-digit EMC account
    # number in the FEIN box painted PINK on exactly that claim. Asserting
    # verified on an unverifiable value is worse than the value.
    #
    # DEMOTE, never blank: the value stays visible and turns orange ("Verify"),
    # which is the agreed behaviour for anything we are not sure of.
    _shape_failures: set = set()
    for _f, _v in mapped.items():
        _why = _shape_violation(_f, _v)
        if _why:
            _shape_failures.add(_f)
            logger.info("shape_check demoted=%s — %s", _f, _why)

    # ── Unanchored entity rows (client #10) ──────────────────────────────────
    # A second Named Insured with a tax ID, an LLC tick and no NAME is not a
    # record. These were originally DEMOTED to an orange highlight "so the
    # broker sees what was found" — and the client re-reported the same rows on
    # the next run, verbatim: "These are not usable records ... The entire
    # Additional Interest entry should be removed", and for the anchored
    # detail boxes: "The 'parent company' wording and 50% ownership figure
    # should be removed." An entity row without a name, and a detail without
    # its subject, are not information — they are artefacts. CLEARED, per the
    # standing blank-over-wrong rule; the client asks the applicant instead.
    try:
        _orphan_row_fields = _unanchored_entity_row_fields(mapped, schema)
        _orphan_row_fields |= _unanchored_detail_fields(mapped, schema)
        if _orphan_row_fields:
            for _f in _orphan_row_fields:
                mapped[_f] = None
                gpt_filled_set.discard(_f)
                _ai_verified_fields.discard(_f)
                _cascade_blanked.add(_f)
            logger.info(
                "unanchored_entity_row cleared=%d field(s) — %s",
                len(_orphan_row_fields), sorted(_orphan_row_fields)[:6],
            )
    except Exception as _orph_ex:                         # noqa: BLE001
        logger.warning("unanchored-row check skipped (form=%s): %s", form_id, _orph_ex)

    # ── Contradictory single-choice ticks (client #4) ────────────────────────
    # Two boxes ticked in a family where ACORD's own tooltip says only one
    # response is expected (live: ISSUE POLICY + BOUND, then ISSUE POLICY +
    # RENEW on the next run). When EVERY tick in the conflict came from the
    # gap-fill model, the contradiction is the model's own invention and
    # choosing between its two guesses is impossible — ALL are cleared
    # (blank-over-wrong; the client picks the status). If any tick is
    # deterministic (fact-driven), the family is only demoted as before, so a
    # real extracted answer is never deleted over a model's stray second tick.
    try:
        _sc_keys = tuple(schema.keys())
        _sc_tips = tuple((schema.get(k) or {}).get("tu") or "" for k in _sc_keys)
        for _group in _single_choice_groups(_sc_keys, _sc_tips):
            _ticked = [
                f for f in _group
                if str(mapped.get(f) or "").strip().lower() in _AFFIRMATIVE_VALUES
            ]
            if len(_ticked) <= 1:
                continue
            if all(f in gpt_filled_set for f in _ticked):
                for _f in _ticked:
                    mapped[_f] = None
                    gpt_filled_set.discard(_f)
                    _ai_verified_fields.discard(_f)
                logger.info("single_choice_conflict cleared=%s", sorted(_ticked))
            else:
                _shape_failures.update(_ticked)
                logger.info("single_choice_conflict demoted=%s", sorted(_ticked))
    except Exception as _sc_ex:                           # noqa: BLE001
        logger.warning("single-choice check skipped (form=%s): %s", form_id, _sc_ex)

    # ── Display canonicalization (Beta feedback: stamp clean, standardized
    # values, not raw OCR strings) ───────────────────────────────────────────
    # NON-destructive: standardizes date / currency / address / name / state
    # formatting while PRESERVING all content (entity suffix, unit number,
    # ZIP+4). The raw value stays in the fact envelope for verification. This is
    # distinct from services/normalization.py, whose stripped comparison key must
    # never be stamped. Gated OFF by default so behavior is identical to the
    # prior pipeline unless ENABLE_DISPLAY_CANONICALIZATION is set.
    try:
        from config.settings import ENABLE_DISPLAY_CANONICALIZATION
    except Exception:
        ENABLE_DISPLAY_CANONICALIZATION = False
    if ENABLE_DISPLAY_CANONICALIZATION:
        try:
            from services.display_canonicalizer import canonicalize_for_field
            for _field in list(mapped.keys()):
                _val = mapped.get(_field)
                if _val is None:
                    continue
                _clean = canonicalize_for_field(_field, _val)
                if _clean is not None and _clean != _val:
                    mapped[_field] = _clean
        except Exception as _cex:
            logger.warning("display canonicalization skipped (form=%s): %s", form_id, _cex)

    # ── Confidence / highlight assignment ────────────────────────────────────
    # Deterministic (Pass 1 / alias, from facts) values are trusted with no
    # highlight. AI-filled values are split by the raw-text verification above:
    #   found in the documents   → "ai_verified"  → pink  (AI-OK)
    #   NOT found (guess, or a
    #   "copied" claim we can't
    #   locate)                  → "low_confidence" → orange (verify)
    # An owner/insured field flagged as contamination-shaped (checked just
    # above) always forces low_confidence, even if it passed the generic
    # raw-text check - a carrier name really is present in the document, just
    # never in this field's role (Figure 33).
    for field, meta in schema.items():
        val       = mapped.get(field)
        has_value = val is not None and str(val).strip() not in ("", "null", "None")
        is_req    = meta.get("required", False) if isinstance(meta, dict) else False

        if has_value:
            # A shape failure outranks EVERY other label, including "filled"
            # (which paints no highlight at all) and "ai_verified" (pink -
            # "confirmed present in your documents"). Those two are precisely
            # the labels that hid the client's bad FEIN.
            if field in _shape_failures:
                confidence[field] = "low_confidence"
            elif field in _owner_field_contamination:
                confidence[field] = "low_confidence"
            elif field in _deterministic_filled:
                confidence[field] = "filled"
            elif field in _ai_verified_fields:
                confidence[field] = "ai_verified"
            else:
                confidence[field] = "low_confidence"
        elif is_req and not _is_nonfillable_field(field):
            # Paint yellow only for genuinely fillable required fields.
            confidence[field] = "missing_required"
        else:
            confidence[field] = "low_confidence"

    confidence = apply_acord125_missing_field_highlights(form_id, facts, mapped, confidence)
    confidence = apply_acord126_missing_field_highlights(form_id, facts, mapped, confidence)
    confidence = apply_acord140_missing_field_highlights(form_id, facts, mapped, confidence)

    # Fill-rate denominator excludes non-fillable fields (signatures, premiums,
    # rate codes) so the reported coverage is meaningful.
    fillable_count = sum(1 for f in schema if not _is_nonfillable_field(f))
    total_filled   = sum(1 for v in mapped.values() if v is not None and str(v).strip() not in ("", "null", "None"))
    logger.info(f"Mapped {total_filled}/{fillable_count} fields (form_id={form_id or 'unknown'})")

    # ── WHAT THE GUARDS TOOK, said out loud ──────────────────────────────────
    # Every box that held a value when the guard region began and is empty now.
    # Reported two ways: a greppable WARNING for us, and - when the caller asks
    # for it by passing a list - a structured row per field so the pre-download
    # review can say "this box is blank because we refused a value", which is
    # the thing the producer could not tell from an empty box.
    try:
        _blanked = sorted(
            _f for _f, _v in _pre_guard_values.items()
            if _f not in _cascade_blanked
            and (mapped.get(_f) is None
                 or str(mapped.get(_f)).strip() in ("", "null", "None"))
        )
        if _cascade_blanked:
            logger.info(
                "guard cascade=%d field(s) cleared with their row - not "
                "reported individually (form=%s)",
                len(_cascade_blanked), form_id or "unknown",
            )
        if _blanked:
            logger.warning(
                "GUARD_BLANKS form=%s count=%d - values a guard removed because "
                "they were not possible for their box. The stops engine cannot "
                "see these: it validates FACTS, these are stamped VALUES. "
                "Fields: %s",
                form_id or "unknown", len(_blanked), ", ".join(_blanked[:20]),
            )
        if guard_report is not None:
            for _f in _blanked:
                guard_report.append({
                    "form_id": form_id or "",
                    "field": _f,
                    # The refused value is carried so the reviewer can judge it.
                    # Truncated: some are whole paragraphs of policy wording.
                    "removed_value": str(_pre_guard_values[_f])[:160],
                })
    except Exception as _gr_ex:                                   # noqa: BLE001
        # Advisory reporting must never break a fill.
        logger.warning("guard-blank report skipped (form=%s): %s", form_id, _gr_ex)

    return mapped, confidence


def extract_form_fields_with_positions(path: str) -> List[dict]:
    fields: List[dict] = []
    if not os.path.exists(path):
        return fields
    try:
        pdf = pikepdf.open(path)
        for page_idx, page in enumerate(pdf.pages):
            raw_annots = page.get("/Annots", None)
            if raw_annots is None:
                continue
            try:
                annot_list = list(raw_annots)
            except Exception:
                continue
            for annot_ref in annot_list:
                try:
                    annot = annot_ref
                    if "/Widget" not in str(annot.get("/Subtype", "")):
                        continue
                    t = annot.get("/T")
                    if t is None:
                        parent = annot.get("/Parent")
                        if parent:
                            t = parent.get("/T")
                    if t is None:
                        continue
                    name = str(t)
                    rect = annot.get("/Rect")
                    if rect is None:
                        continue
                    x1, y1, x2, y2 = float(rect[0]), float(rect[1]), float(rect[2]), float(rect[3])
                    if x1 > x2: x1, x2 = x2, x1
                    if y1 > y2: y1, y2 = y2, y1
                    ft_raw = annot.get("/FT")
                    if ft_raw is None:
                        parent = annot.get("/Parent")
                        if parent:
                            ft_raw = parent.get("/FT")
                    ft_str     = str(ft_raw) if ft_raw else "/Tx"
                    field_type = "checkbox" if "/Btn" in ft_str else "dropdown" if "/Ch" in ft_str else "text"
                    v = annot.get("/V")
                    if v is None:
                        parent = annot.get("/Parent")
                        if parent:
                            v = parent.get("/V")
                    val = ""
                    if v is not None:
                        sv = str(v)
                        if sv.startswith("/"):
                            sv = sv[1:]
                        val = sv if sv not in ("Off", "null", "None") else ""
                    fields.append({
                        "name": name, "page": page_idx,
                        "rect": {"x": round(x1, 2), "y": round(y1, 2),
                                 "width": round(x2 - x1, 2), "height": round(y2 - y1, 2)},
                        "type": field_type, "value": val,
                    })
                except Exception:
                    pass
        pdf.close()
    except Exception as ex:
        logger.error(f"extract_form_fields_with_positions error: {ex}")
    return fields


def get_page_dims_pikepdf(path: str) -> List[dict]:
    dims = []
    try:
        pdf = pikepdf.open(path)
        for page in pdf.pages:
            mb = page.get("/MediaBox", None)
            if mb:
                dims.append({"width": float(mb[2]) - float(mb[0]), "height": float(mb[3]) - float(mb[1])})
            else:
                dims.append({"width": 612.0, "height": 792.0})
        pdf.close()
    except Exception as ex:
        logger.error(f"get_page_dims_pikepdf error: {ex}")
    return dims


def regenerate_pdf_for_form(
    proc_session: dict,
    form_id: str,
    force: bool = False,
    user_signature: str = None,
) -> bytes:
    generated = proc_session.get("generated_forms", {})
    if form_id not in generated:
        raise HTTPException(404, f"Form {form_id} not generated")
    r          = generated[form_id]
    tpl        = os.path.join(TEMPLATE_DIR, r["form"]["template_file"])
    field_data = r.get("field_state") or r.get("mapped", {})
    confidence = r.get("confidence", {})

    if not force:
        # Only serve the cached signed PDF when the cache is still valid (non-empty hash).
        # An empty _pdf_cache_hash means client answers were applied after signing — must regen.
        if r.get("signature_applied") and r.get("pdf_bytes") and r.get("_pdf_cache_hash"):
            cached = r["pdf_bytes"]
            return cached if isinstance(cached, bytes) else bytes(cached)
        import hashlib
        state_hash  = hashlib.md5(json.dumps(field_data, sort_keys=True).encode()).hexdigest()
        cached_hash = r.get("_pdf_cache_hash")
        cached_bytes = r.get("pdf_bytes")
        if cached_bytes and cached_hash == state_hash:
            return cached_bytes if isinstance(cached_bytes, bytes) else bytes(cached_bytes)

    # Resolve which signature to use: prefer stored signature_b64, then fall back to
    # the caller-supplied user_signature (covers legacy sessions missing signature_b64).
    sig_b64 = None
    if r.get("signature_applied"):
        sig_b64 = r.get("signature_b64") or user_signature

    if sig_b64:
        # Regenerate with latest field values and re-stamp signature
        pdf_bytes = inject_signature_into_pdf(tpl, field_data, confidence, sig_b64)
    else:
        pdf_bytes = fill_pdf(tpl, field_data, confidence)

    import hashlib
    state_hash = hashlib.md5(json.dumps(field_data, sort_keys=True).encode()).hexdigest()
    generated[form_id]["pdf_bytes"]       = pdf_bytes
    generated[form_id]["_pdf_cache_hash"] = state_hash
    return pdf_bytes


def _get_page_content_scale(page) -> float:
    """Return the uniform scale factor applied by the first 'cm' operator in the
    page content stream, or 1.0 if none is found.

    Many ACORD templates open their content stream with a line like:
        0.12 0 0 0.12 0 0 cm
    which maps widget /Rect coordinates (in PDF user space) to a scaled internal
    coordinate system. When we append new content we must use the internal space,
    so all user-space coordinates need to be divided by this scale.

    Only handles the simple uniform-scale case (a == d, b == 0, c == 0, e == 0,
    f == 0). Returns 1.0 for any other transform so painting degrades gracefully.
    """
    import re as _re
    try:
        contents = page.get("/Contents")
        if contents is None:
            return 1.0
        if isinstance(contents, pikepdf.Array):
            raw = b"".join(bytes(s.read_bytes()) for s in contents)
        else:
            raw = bytes(contents.read_bytes())
        text = raw[:500].decode("latin-1", errors="replace")
        # Match "sx 0[.0] 0[.0] sy tx ty cm" — the zero components may be 0.00
        m = _re.search(
            r"([\d\.]+)\s+([\d\.]+)\s+([\d\.]+)\s+([\d\.]+)\s+([\d\.\-]+)\s+([\d\.\-]+)\s+cm",
            text,
        )
        if m:
            sx  = float(m.group(1))
            shx = float(m.group(2))
            shy = float(m.group(3))
            sy  = float(m.group(4))
            tx  = float(m.group(5))
            ty  = float(m.group(6))
            # Only trust as a pure uniform scale (no shear, no translation)
            if (abs(shx) < 0.001 and abs(shy) < 0.001
                    and abs(sx - sy) < 0.001
                    and abs(tx) < 0.001 and abs(ty) < 0.001
                    and sx > 0):
                return sx
    except Exception:
        pass
    return 1.0


def inject_signature_into_pdf(
    template_path: str,
    field_data: dict,
    confidence: dict,
    signature_b64: str,
    existing_pdf_bytes: bytes = None,
) -> bytes:
    """Fill the PDF then paint the signature image directly into the page content
    stream at every signature-field rectangle.

    Painting into the content stream (not just adding an annotation) ensures the
    signature renders in every PDF viewer, including print dialogs and flattened
    exports that ignore annotations.
    """
    import base64
    # Use pre-filled bytes when available so no field values are lost on re-generation
    filled_bytes = existing_pdf_bytes if existing_pdf_bytes is not None else fill_pdf(template_path, field_data, confidence)
    try:
        b64_data = signature_b64
        if "," in b64_data:
            b64_data = b64_data.split(",", 1)[1]
        sig_raw = base64.b64decode(b64_data)
        sig_img = Image.open(io.BytesIO(sig_raw)).convert("RGBA")
    except Exception as ex:
        logger.error(f"Signature image decode failed: {ex}")
        return filled_bytes
    try:
        pdf = pikepdf.open(io.BytesIO(filled_bytes))
    except Exception as ex:
        logger.error(f"Cannot open filled PDF for signature injection: {ex}")
        return filled_bytes

    injected = 0
    try:
        for page_idx, page in enumerate(pdf.pages):
            raw_annots = page.get("/Annots")
            if raw_annots is None:
                continue
            try:
                annot_list = list(raw_annots)
            except Exception:
                continue

            # Collect signature field rects on this page, then remove the widget
            # annotations so the empty field boxes don't show through the image.
            sig_rects: List[tuple] = []   # (x1, y1, draw_w, draw_h, jpeg_bytes, px_w, px_h)
            annots_to_keep = []

            for annot_ref in annot_list:
                field_name = "?"
                try:
                    annot  = annot_ref
                    subtyp = str(annot.get("/Subtype", ""))
                    if "/Widget" not in subtyp:
                        annots_to_keep.append(annot_ref)
                        continue
                    ft_raw = annot.get("/FT")
                    if ft_raw is None:
                        try:
                            p = annot.get("/Parent")
                            if p is not None:
                                ft_raw = p.get("/FT")
                        except Exception:
                            pass
                    ft_str = str(ft_raw) if ft_raw is not None else ""
                    t = annot.get("/T")
                    if t is None:
                        try:
                            p = annot.get("/Parent")
                            if p is not None:
                                t = p.get("/T")
                        except Exception:
                            pass
                    field_name = str(t) if t is not None else ""
                    if not _is_signature_field(field_name, ft_str):
                        annots_to_keep.append(annot_ref)
                        continue
                    rect = annot.get("/Rect")
                    if rect is None:
                        annots_to_keep.append(annot_ref)
                        continue
                    x1, y1, x2, y2 = float(rect[0]), float(rect[1]), float(rect[2]), float(rect[3])
                    if x1 > x2: x1, x2 = x2, x1
                    if y1 > y2: y1, y2 = y2, y1
                    field_w = max(x2 - x1, 1.0)
                    field_h = max(y2 - y1, 1.0)

                    # Scale signature to fit inside the field, preserving aspect ratio
                    img_w, img_h = sig_img.size
                    img_ratio    = img_w / max(img_h, 1)
                    field_ratio  = field_w / max(field_h, 1)
                    if img_ratio >= field_ratio:
                        draw_w = field_w
                        draw_h = field_w / img_ratio
                    else:
                        draw_h = field_h
                        draw_w = field_h * img_ratio
                    draw_w = min(draw_w, field_w)
                    draw_h = min(draw_h, field_h)
                    # Centre inside the field
                    draw_x = x1 + (field_w - draw_w) / 2.0
                    draw_y = y1 + (field_h - draw_h) / 2.0

                    # Rasterise at 4× the point size for crisp output
                    px_w = max(int(draw_w * 4), 4)
                    px_h = max(int(draw_h * 4), 4)
                    sig_resized = sig_img.resize((px_w, px_h), Image.LANCZOS)
                    bg = Image.new("RGB", (px_w, px_h), (255, 255, 255))
                    if sig_resized.mode == "RGBA":
                        bg.paste(sig_resized, mask=sig_resized.split()[3])
                    else:
                        bg.paste(sig_resized.convert("RGB"))
                    jpeg_buf = io.BytesIO()
                    bg.save(jpeg_buf, format="JPEG", quality=92)
                    sig_rects.append((draw_x, draw_y, draw_w, draw_h,
                                      jpeg_buf.getvalue(), px_w, px_h))
                    # Drop the widget annotation — the image replaces it
                    injected += 1
                except Exception as field_ex:
                    logger.warning(f"Sig field error page={page_idx} field={field_name!r}: {field_ex}")
                    annots_to_keep.append(annot_ref)

            page["/Annots"] = pikepdf.Array(annots_to_keep)

            if not sig_rects:
                continue

            # Detect the page's global CTM scale so we can paint in the correct
            # coordinate space.  Many ACORD templates open their content stream
            # with "sx 0 0 sy 0 0 cm" which scales all internal coordinates.
            # Widget /Rect values are always in PDF user-space (post-transform),
            # but when we append new content the current graphics state already
            # has that scale applied — so we must invert it.
            page_scale = _get_page_content_scale(page)  # e.g. 0.12 for ACORD 125

            # Paint each signature image directly into the page content stream
            for draw_x, draw_y, draw_w, draw_h, jpeg_bytes, px_w, px_h in sig_rects:
                try:
                    # Register the image XObject on this page's /Resources
                    img_xobj = pikepdf.Stream(pdf, jpeg_bytes)
                    img_xobj["/Type"]             = pikepdf.Name("/XObject")
                    img_xobj["/Subtype"]          = pikepdf.Name("/Image")
                    img_xobj["/Width"]            = px_w
                    img_xobj["/Height"]           = px_h
                    img_xobj["/ColorSpace"]       = pikepdf.Name("/DeviceRGB")
                    img_xobj["/BitsPerComponent"] = 8
                    img_xobj["/Filter"]           = pikepdf.Name("/DCTDecode")
                    indirect_img = pdf.make_indirect(img_xobj)

                    # Find a unique XObject name for this page
                    if "/Resources" not in page:
                        page["/Resources"] = pikepdf.Dictionary()
                    res = page["/Resources"]
                    if "/XObject" not in res:
                        res["/XObject"] = pikepdf.Dictionary()
                    xobj_name = "/SigImg"
                    counter = 0
                    while pikepdf.Name(xobj_name) in res["/XObject"]:
                        counter += 1
                        xobj_name = f"/SigImg{counter}"
                    res["/XObject"][pikepdf.Name(xobj_name)] = indirect_img

                    # Convert user-space coordinates to the page's internal space.
                    # Widget rects are in user space; the content stream may have a
                    # global scale (e.g. 0.12) already applied, so we divide by it.
                    if page_scale and page_scale != 1.0:
                        ix = draw_x / page_scale
                        iy = draw_y / page_scale
                        iw = draw_w / page_scale
                        ih = draw_h / page_scale
                    else:
                        ix, iy, iw, ih = draw_x, draw_y, draw_w, draw_h

                    # q ... cm Image Do Q — save/restore graphics state so we
                    # don't disturb any transforms that follow in the stream.
                    paint_ops = (
                        f"q "
                        f"{iw:.4f} 0 0 {ih:.4f} {ix:.4f} {iy:.4f} cm "
                        f"{xobj_name} Do "
                        f"Q\n"
                    ).encode("latin-1")

                    # Append paint ops after the existing page content
                    existing = page.get("/Contents")
                    paint_stream = pikepdf.Stream(pdf, paint_ops)
                    if existing is None:
                        page["/Contents"] = pdf.make_indirect(paint_stream)
                    elif isinstance(existing, pikepdf.Array):
                        existing.append(pdf.make_indirect(paint_stream))
                        page["/Contents"] = existing
                    else:
                        page["/Contents"] = pikepdf.Array([
                            existing if existing.is_indirect else pdf.make_indirect(existing),
                            pdf.make_indirect(paint_stream),
                        ])
                except Exception as paint_ex:
                    logger.warning(f"Sig paint error page={page_idx}: {paint_ex}")

        # Clean up AcroForm: remove signature field entries so readers don't
        # show an empty signature widget on top of the painted image.
        if injected > 0 and "/AcroForm" in pdf.Root:
            acro = pdf.Root["/AcroForm"]
            # NeedAppearances=false since we've painted directly
            acro["/NeedAppearances"] = pikepdf.Boolean(False)
            fields_arr = acro.get("/Fields")
            if fields_arr is not None:
                def _remove_sig_fields(arr):
                    kept = []
                    for item in arr:
                        try:
                            t     = item.get("/T")
                            ft_r  = item.get("/FT")
                            name  = str(t) if t is not None else ""
                            ft_s  = str(ft_r) if ft_r is not None else ""
                            if _is_signature_field(name, ft_s):
                                continue
                            kids = item.get("/Kids")
                            if kids:
                                item["/Kids"] = pikepdf.Array(_remove_sig_fields(list(kids)))
                            kept.append(item)
                        except Exception:
                            kept.append(item)
                    return kept
                acro["/Fields"] = pikepdf.Array(_remove_sig_fields(list(fields_arr)))

        out_buf = io.BytesIO()
        pdf.save(out_buf)
        pdf.close()
        out_buf.seek(0)
        logger.info(f"Signature injection: {injected} field(s) painted into content stream")
        return out_buf.getvalue()
    except Exception as ex:
        logger.error(f"Signature injection failed: {ex}", exc_info=True)
        try:
            pdf.close()
        except Exception:
            pass
        return filled_bytes
