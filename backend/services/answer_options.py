"""answer_options.py - every answer we can enumerate, offered as a choice.

Owner's instruction 2026-08-24: *"Look for every answer that we are expecting,
we need to give all possible option that a user can think of answering"* -
modelled on the dismiss-reason dropdown, which lists every realistic reason and
ends with **Other**. Free typing stays for the things nobody can enumerate:
names, addresses, phones, emails, amounts, dates, codes and percentages.

WHY THIS EXISTS
---------------
A free-text box on a closed question is where answers go to die. Measured
2026-08-24: a producer typing "None" into the No-Known-Losses card moved
nothing, because the reader expected a curated sentence. `answer_semantics`
now understands the phrasings, but understanding prose will always be a
rearguard action - the real fix is not to ask for prose when the answer set is
knowable. This module is that fix; `answer_semantics` stays underneath as the
safety net for "Other", for legacy stored answers, and for extraction.

THREE RULES EVERY LIST FOLLOWS
------------------------------
1. **The option TEXT is the stored value.** No hidden codes, no mapping table
   to drift - the same contract `_NO_LOSS_OPTIONS` has proven since 2026-08-17.
   Every option below is verified to survive the normalizer its fact already
   uses (see tests/test_answer_options.py).
2. **Every list ends with "Other".** A producer with an unusual answer must
   never be trapped; "Other" drops to free text, which `answer_semantics`
   interprets exactly as it does today.
3. **Options are phrased as the ANSWER a person would give**, not as a schema
   token - "Yes - fully sprinklered", not "SPRINKLERED_FULL".

WHERE A DROPDOWN WOULD BE WRONG, AND IS DELIBERATELY NOT OFFERED
---------------------------------------------------------------
Carrier names, class codes and NAICS/SIC have universes in the thousands and
change constantly. Forcing a list there makes "Other" the usual answer, which
is worse than typing. Those keep free text (NAICS already has the Figure 20
suggester chips - suggest, never constrain). `prior_carrier` is the one hybrid:
free text, but the questionnaire offers the "none" answer explicitly because
"previously uninsured" is a real state a producer cannot express by typing a
carrier name.
"""

from __future__ import annotations

import logging
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

OTHER = "Other"


def _with_other(*options: str) -> List[str]:
    return list(options) + [OTHER]


# ── Business identity ────────────────────────────────────────────────────────
ENTITY_TYPE_OPTIONS = _with_other(
    "Sole Proprietorship",
    "Partnership",
    "Limited Partnership",
    "Limited Liability Partnership",
    "Limited Liability Company",
    "Corporation",
    "S Corporation",
    "Non-Profit Corporation",
    "Joint Venture",
    "Trust",
    "Association",
    "Municipality or Government Entity",
)

# The client's own 1.7 families, phrased as coverages a person asks for.
LINES_OF_BUSINESS_OPTIONS = _with_other(
    "General Liability",
    "Commercial Property",
    "Business Auto",
    "Workers Compensation",
    "Umbrella or Excess Liability",
    "Inland Marine",
    "Crime",
    "Cyber Liability",
    "Professional Liability",
    "Employment Practices Liability",
    "Builders Risk",
    "Liquor Liability",
    "Pollution Liability",
    "Directors and Officers Liability",
)

# ── Property / COPE ─────────────────────────────────────────────────────────
# ISO's six construction classes, in the wording an insured would recognise.
CONSTRUCTION_TYPE_OPTIONS = _with_other(
    "Frame - wood construction",
    "Joisted Masonry - masonry walls with a combustible roof or floor",
    "Non-Combustible - metal walls and roof",
    "Masonry Non-Combustible - masonry walls, non-combustible roof",
    "Modified Fire Resistive",
    "Fire Resistive - concrete or protected steel",
)

OCCUPANCY_TYPE_OPTIONS = _with_other(
    "Office",
    "Retail store",
    "Restaurant or food service",
    "Warehouse or storage",
    "Light manufacturing",
    "Heavy manufacturing",
    "Apartment or residential rental",
    "Mixed use - retail with residential above",
    "Contractor shop or yard",
    "Auto service or repair",
    "Medical or dental office",
    "School or daycare",
    "Church or place of worship",
    "Hotel or motel",
    "Self-storage",
    "Vacant building",
)

# ONLY the two methods the fact can hold. `valuation_method`'s contract is
# stated in two places that already agree: FACT_REGISTRY's validator accepts
# {"RCV", "ACV"} and extraction_service's schema line is literally
# `"valuation_method": "RCV"|"ACV"|null`. Offering a third and fourth method
# here produced a dropdown whose choice was then refused by the fact's own
# validator - a card the producer could not resolve at all (2026-09-08).
#
# KNOWN GAP, deliberately not closed here: ACORD 140's own ValuationCode
# tooltip lists four methods (A Actual Cash Value / R Replacement Cost /
# V Agreed Amount / M Market Value), so an agreed-value or market-value policy
# has no canonical fact to land in. Widening it means changing the extraction
# schema, the validator and the stamping map together - an owner decision, not
# a side effect of a bug fix. Until then those policies go through Other, and
# the producer is told plainly why rather than being handed a dead choice.
VALUATION_METHOD_OPTIONS = _with_other(
    "Replacement Cost",
    "Actual Cash Value",
)

SPRINKLER_OPTIONS = _with_other(
    "Yes - fully sprinklered",
    "Yes - partially sprinklered",
    "No - not sprinklered",
)

# ISO Public Protection Classification: 1 (best) to 10 (unprotected).
FIRE_PROTECTION_CLASS_OPTIONS = _with_other(
    *[f"Protection Class {n}" for n in range(1, 10)],
    "Protection Class 10 - unprotected",
)

PERIOD_OF_RESTORATION_OPTIONS = _with_other(
    "3 months", "6 months", "9 months", "12 months", "18 months", "24 months",
)

AGREED_VALUE_OPTIONS = _with_other(
    "Yes - agreed value endorsement applies",
    "No - coinsurance applies",
)

# ── Coverage terms ──────────────────────────────────────────────────────────
GL_FORM_TYPE_OPTIONS = _with_other(
    "Occurrence",
    "Claims-made",
)

UMBRELLA_FOLLOW_FORM_OPTIONS = _with_other(
    "Follows form - explicitly stated in the submitted documents",
    "Does not follow form - the umbrella has its own terms",
    "Not stated - underwriter review recommended",
)

# ── Auto ────────────────────────────────────────────────────────────────────
VEHICLES_RETURN_OPTIONS = _with_other(
    "Yes - all vehicles return to the premises nightly",
    "Most vehicles return to the premises nightly",
    "No - vehicles are garaged at drivers' homes or elsewhere",
    "Mixed - it varies by vehicle",
)

# ADDED 2026-08-26 (V1 H1 6.3). The ACORD 127 USE column, as the form prints
# it - Pleasure / Farm / Commercial / Retail / Service / For Hire / Other.
# One answer for the fleet; the stamper inherits it into every real row.
VEHICLE_USE_OPTIONS = _with_other(
    "Service - technicians or crews driving to job sites",
    "Retail - deliveries to customers",
    "Commercial - general business use, hauling own goods",
    "For hire - carrying goods or passengers for a fee",
    "Farm - agricultural use",
    "Pleasure - personal use only, driving to and from work",
)

# ── Workers Compensation ────────────────────────────────────────────────────
# ADDED 2026-08-26 (V1 H1 6.4). The producer states what period the payroll
# figure covers; "Other" still lets a free-text period through, and
# `coverage_evidence.payroll_period_meaning` reads whichever is typed.
WC_PAYROLL_PERIOD_OPTIONS = _with_other(
    "Annual - the figure covers a full year",
    "Quarterly",
    "Monthly",
    "Year to date",
)

# SYS-04. The X-Mod box was the one WC field most likely to be answered with a
# free-text sentence, and a sentence is where meaning gets lost: measured,
# `fact_state.value_state_of` reads "Not applicable - we do not carry workers
# compensation" as a VALUE (present) while the bare "Not applicable" reads as
# not_applicable. So the escape hatch is offered as an OPTION whose text the
# state reader already understands, instead of hoping the client types it.
#
# Each option maps to the state it should:
#   "Not applicable"                    -> not_applicable -> the line is ABSENT
#   "No experience modifier ..."        -> present        -> WC exists, no mod
#   a typed mod value via Other         -> present
WC_XMOD_OPTIONS = _with_other(
    "Not applicable",
    "No experience modifier has been assigned",
    "1.00 - neither a credit nor a debit mod",
)

WC_OFFICER_EXCLUSION_OPTIONS = _with_other(
    "No - all owners and officers are included",
    "Yes - some owners or officers are excluded",
    "Yes - all owners and officers are excluded",
    "There are no owners or officers to consider",
)

# ── Additional interests ────────────────────────────────────────────────────
ADDITIONAL_INSURED_OPTIONS = _with_other(
    "No - no additional insureds are required",
    "Yes - a landlord or property owner",
    "Yes - a client or customer required by contract",
    "Yes - a general contractor or project owner",
    "Yes - a lender, lessor or finance company",
    "Yes - a franchisor or parent company",
)


def _auto_symbol_options() -> List[str]:
    """ACORD's own covered-auto symbol wording, read from `services.
    auto_symbols` - the table built in the 2026-08-07 auto-symbols work
    straight out of the ACORD 137/138 tooltips. Reusing it means this dropdown
    can never drift from the definitions the validators reason over.
    """
    try:
        from services import auto_symbols as _as
        table = None
        for name in ("BUSINESS_AUTO_SYMBOLS", "SYMBOL_DESCRIPTIONS", "SYMBOLS"):
            table = getattr(_as, name, None)
            if isinstance(table, dict) and table:
                break
        if isinstance(table, dict) and table:
            out = []
            for code in sorted(table, key=lambda c: (len(str(c)), str(c))):
                desc = table[code]
                desc = desc if isinstance(desc, str) else getattr(desc, "description", "")
                if not desc:
                    continue
                short = str(desc).split(".")[0].strip()
                out.append(f"Symbol {code} - {short}" if short else f"Symbol {code}")
                if len(out) >= 24:
                    break
            if out:
                return out + [OTHER]
    except Exception as exc:                                  # noqa: BLE001
        logger.debug("auto symbol options unavailable: %s", exc)
    # Fallback: the eight business-auto symbols ACORD actually prints on the
    # grid (5 and 19 are real but live in the "other symbol" box - see the
    # 2026-08-07 entry, which is why they are absent here too).
    return _with_other(
        "Symbol 1 - Any auto",
        "Symbol 2 - Owned autos only",
        "Symbol 3 - Owned private passenger autos only",
        "Symbol 4 - Owned autos other than private passenger",
        "Symbol 6 - Owned autos subject to no-fault",
        "Symbol 7 - Specifically described autos",
        "Symbol 8 - Hired autos only",
        "Symbol 9 - Non-owned autos only",
    )


# ── The catalogue ────────────────────────────────────────────────────────────
# fact_key -> (options, multi_select). Everything absent from this table keeps
# free text, which is the correct control for names, addresses, phones, emails,
# amounts, dates, codes and percentages.
_CATALOGUE: Dict[str, Tuple[List[str], bool]] = {
    "entity_type":                 (ENTITY_TYPE_OPTIONS, False),
    "lines_of_business":           (LINES_OF_BUSINESS_OPTIONS, True),
    "construction_type":           (CONSTRUCTION_TYPE_OPTIONS, False),
    "occupancy_type":              (OCCUPANCY_TYPE_OPTIONS, False),
    "valuation_method":            (VALUATION_METHOD_OPTIONS, False),
    "sprinkler_system":            (SPRINKLER_OPTIONS, False),
    "fire_protection_class":       (FIRE_PROTECTION_CLASS_OPTIONS, False),
    "period_of_restoration":       (PERIOD_OF_RESTORATION_OPTIONS, False),
    "agreed_value_endorsement":    (AGREED_VALUE_OPTIONS, False),
    "gl_form_type":                (GL_FORM_TYPE_OPTIONS, False),
    # The umbrella's OWN trigger (extraction v21) - one basis vocabulary, so
    # the tick door can read the ACORD 131 umbrella Occurrence / Claims-Made boxes.
    "umbrella_form_type":          (GL_FORM_TYPE_OPTIONS, False),
    "umbrella_follow_form":        (UMBRELLA_FOLLOW_FORM_OPTIONS, False),
    "vehicles_return_to_premises": (VEHICLES_RETURN_OPTIONS, False),
    "auto_vehicle_use":            (VEHICLE_USE_OPTIONS, False),
    "wc_xmod":                     (WC_XMOD_OPTIONS, False),
    "wc_officer_exclusions":       (WC_OFFICER_EXCLUSION_OPTIONS, False),
    "wc_payroll_period":           (WC_PAYROLL_PERIOD_OPTIONS, False),
    "additional_insured":          (ADDITIONAL_INSURED_OPTIONS, True),
    "additional_named_insureds":   (ADDITIONAL_INSURED_OPTIONS, True),
}


def _lazy_catalogue() -> Dict[str, Tuple[List[str], bool]]:
    """The catalogue plus the sets that live in their own modules, so each
    option list has exactly ONE owner and this table never becomes a second
    copy that drifts."""
    out = dict(_CATALOGUE)
    out["auto_covered_symbols"] = (_auto_symbol_options(), True)
    try:
        from services.arq_service import (
            _CARRIER_MARKETING_OPTIONS, _NO_LOSS_OPTIONS,
        )
        out["carrier_marketing_reason"] = (list(_CARRIER_MARKETING_OPTIONS), False)
        out["loss_history_no_prior_losses_indicator"] = (list(_NO_LOSS_OPTIONS), False)
    except Exception:                                         # noqa: BLE001
        pass
    try:
        from services.loss_history_state import (
            LOSS_RUN_STATUS_OPTIONS, NEW_VENTURE_OPTIONS,
        )
        out["loss_run_status"] = (list(LOSS_RUN_STATUS_OPTIONS) + [OTHER], False)
        out["new_venture_indicator"] = (list(NEW_VENTURE_OPTIONS), False)
    except Exception:                                         # noqa: BLE001
        pass
    return out


def options_for(fact_key: str) -> Optional[List[str]]:
    """The answer choices for this fact, or None when it should stay free text."""
    entry = _lazy_catalogue().get(fact_key)
    return list(entry[0]) if entry else None


# A document names an option in its OWN printing, and the commonest one is the
# checkbox caption: ACORD 25 heads the GL basis column "CLAIMS-MADE | OCCUR".
# An exact-match reading judged the certificate's correct "OCCUR" illegal for
# `gl_form_type`, so the Data Consistency card could not drop the declarations
# page's form number "CG 00 01 04 13" and asked the producer to pick between
# them (Orbin 5037f1a6, client 11 Sep 2026). A printing names an option when it
# IS the option, or an UNAMBIGUOUS truncation of it: at least this many letters
# and digits, and the start of exactly one option. "OCC" names nothing, and
# "Limited" names three entity types, so it names none of them.
_OPTION_CAPTION_MIN = 4


def option_named_by(fact_key: str, text) -> Optional[str]:
    """The option label ``text`` names for this fact, or None.

    Never "Other" - that is the escape hatch, not an answer. Never a guess:
    anything that is not an option or an unambiguous truncation of one returns
    None, and a fact with no closed list always returns None.
    """
    import re
    key = re.sub(r"[^a-z0-9]", "", str(text or "").lower())
    if not key:
        return None
    labels: Dict[str, str] = {}
    for opt in options_for(fact_key) or []:
        k = re.sub(r"[^a-z0-9]", "", str(opt).lower())
        if k and opt != OTHER:
            labels[k] = opt
    if key in labels:
        return labels[key]
    if len(key) >= _OPTION_CAPTION_MIN:
        hits = [label for k, label in labels.items() if k.startswith(key)]
        if len(hits) == 1:
            return hits[0]
    return None


def is_multi_select(fact_key: str) -> bool:
    """True when a person can legitimately choose more than one (lines of
    business, covered-auto symbols, additional insureds)."""
    entry = _lazy_catalogue().get(fact_key)
    return bool(entry and entry[1])


def control_for(fact_key: str) -> str:
    """The control this fact should render: "select" / "multiselect" / a typed
    input / "text".

    Derived, never a second hand-kept list: the option catalogue answers first,
    then the field's OWN declared type (`answer_semantics._declared_kind`, which
    itself reads `arq_service._FIELD_INPUT_TYPE` and the registry's format
    hint). So the control and the interpretation can never disagree about what
    a field wants.
    """
    if options_for(fact_key):
        return "multiselect" if is_multi_select(fact_key) else "select"
    try:
        from services.answer_semantics import _declared_kind, _registry_entry
        kind = _declared_kind(fact_key, _registry_entry(fact_key))
    except Exception:                                         # noqa: BLE001
        kind = None
    return {"currency": "currency", "date": "date", "code": "code",
            "integer": "number", "percent": "percent"}.get(kind or "", "text")


def catalogued_facts() -> List[str]:
    """Every fact that offers choices - used by the guard tests."""
    return sorted(_lazy_catalogue())


def attach_answer_controls(items, field_key: str = "field") -> int:
    """Stamp `answer_options` / `answer_control` onto recommendation, hard-stop
    and warning cards so the producer gets the same choices the questionnaire
    offers instead of a bare text box.

    In place and additive: a card whose fact is not catalogued simply gets its
    typed control ("currency", "date", "number", "code") or "text", so the
    renderer always knows what to draw. Returns how many cards gained choices.
    """
    n = 0
    for it in (items or []):
        if not isinstance(it, dict):
            continue
        fact = it.get(field_key)
        if not fact or it.get("answer_control"):
            continue
        try:
            opts = options_for(fact)
            it["answer_control"] = control_for(fact)
            if opts:
                it["answer_options"] = opts
                it["answer_multi"] = is_multi_select(fact)
                n += 1
        except Exception:                                     # noqa: BLE001
            continue
    return n
