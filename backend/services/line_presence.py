"""ONE door for: **is this coverage line part of the submission?**

SYS-04 (1 Sep live test): *"Gate line-specific recommendations and loss
requirements on evidence that the line is actually active or intentionally
requested. If Workers' Compensation is not part of the submission, it should
not generate Workers' Comp loss requirements, warnings, or remediation
tasks."*

Every caller that wants to suppress a line-specific ask asks THIS, so the
answer cannot drift between the scorer, the questionnaire and the card - the
exact drift SYS-04 is: `arq_service` already refused to ASK a non-WC account
for its X-Mod while the scorer DEDUCTED for the same missing answer and the
recommendation card asked the producer for it. Principle 1.

THE THREE-VALUE ANSWER IS THE WHOLE DESIGN
------------------------------------------
`PRESENT` / `ABSENT` / `UNKNOWN`, and **UNKNOWN is not a failure**. A caller
must treat UNKNOWN as "keep asking" - Principle 3 (missing does not mean no)
and Principle 7 (unknown edge cases default to producer review). That is what
makes this safe against document shapes nobody has seen: an input we cannot
read returns UNKNOWN and the caller's behaviour is unchanged. This door can
only ever REMOVE an ask on positive evidence; it can never invent one.

WHY THE COVERAGE FLAG IS READ ONLY IN ONE DIRECTION
---------------------------------------------------
`flags["has_workers_comp"]` is set by `extraction_service`'s prompt on a mere
MENTION (*"true if document mentions workers compensation, WC, payroll by
class code, experience modification factor, employers liability, or WC class
codes"*), and every ACORD 25 certificate prints "WORKERS COMPENSATION AND
EMPLOYERS' LIABILITY" plus three E.L. limit labels as preprinted text whether
or not the row carries a policy. `apply_declared_absent_downgrades` only fires
on an explicit denial, so a BLANK row never turns it back off.

Its unreliability is **asymmetric**, and that is what makes it usable:

* ``True``  - weak. Could be a blank certificate heading. Never decisive here.
* ``False`` - strong. The model saw none of six different WC signals anywhere
  in the whole document set. That is real evidence of absence.

So a false flag is a decisive ABSENT signal and a true flag is no signal at
all. Read D-AN in `1stSep-liveTestFixes.md` before changing that.

WHAT THIS DELIBERATELY DOES NOT USE
-----------------------------------
* ``fact_state.lines_applied_for`` - it reads
  ``pdf_service._SECTION_FORM_LINE_PHRASES``, the header-IDENTITY table, which
  maps ACORD_133 to workers compensation (its template really is the WC
  Assigned Risk Section) while the rest of the repo sells 133 as Builders
  Risk. `lines_applied_for(["ACORD_133"]) == {"workers_comp"}`, so a
  builders-risk-only package would declare WC present - the exact false
  positive SYS-04 exists to kill. See D-AO / D-AP.
* ``fact_equivalence.fact_line`` - contaminated by the same mapping. All seven
  ``builders_risk_*`` facts answer ``workers_comp`` today. This module uses its
  own explicit fact key / prefix table instead, so it is immune.
* ``coverage_evidence.coverage_flag_supported`` - a DEMOTION guard ("may we
  keep a flag that is already true"), maximally permissive by design. It
  returns True on a bare ``total_payroll``. It is not a presence test. See the
  TRAP note in the SYS-04 diagnosis.
* ``pdf_service._producer_asserts_family`` - reads a fact's SOURCE, not its
  VALUE, so it returns True for a client who typed "None", "N/A" or "we have
  no workers comp coverage". This module reads the VALUE STATE instead.

NO LLM ANYWHERE IN THIS FILE, by the same ruling that governs
`answer_semantics` and `coverage_evidence` - determinism and latency.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, Iterable, Optional, Tuple

logger = logging.getLogger(__name__)

# ── The three-value answer ───────────────────────────────────────────────────
PRESENT = "present"
ABSENT = "absent"
UNKNOWN = "unknown"

ANSWERS = frozenset({PRESENT, ABSENT, UNKNOWN})


class LineProfile:
    """Everything this module needs to reason about one coverage line.

    Deliberately explicit rather than derived. Every derivation route into
    "which facts belong to this line" that already exists in the codebase runs
    through the ACORD 133 identity table and is contaminated (see the module
    docstring), so the table is written out and pinned by a test.
    """

    __slots__ = ("line", "phrases", "fact_prefixes", "fact_keys",
                 "application_forms", "flag")

    def __init__(self, line: str, phrases: Tuple[str, ...],
                 fact_prefixes: Tuple[str, ...], fact_keys: Tuple[str, ...],
                 application_forms: Tuple[str, ...], flag: str):
        self.line = line
        self.phrases = phrases
        self.fact_prefixes = fact_prefixes
        self.fact_keys = fact_keys
        self.application_forms = application_forms
        self.flag = flag


# Canonical line family (the `lob_canon.canon_line` vocabulary) -> profile.
#
# A line with NO entry here always answers UNKNOWN. That is the generic
# safety property: adding a narrative component or a recommendation for a line
# this table does not describe changes nothing until someone describes it.
#
# `application_forms` means "selecting this form IS applying for this line".
# Only forms whose identity is unambiguous in THIS repo may appear - notably
# NOT ACORD_133, whose template is the WC Assigned Risk Section while
# forms_database calls it Builders Risk (D-AP, unresolved).
_LINE_PROFILES: Dict[str, LineProfile] = {
    "workers_comp": LineProfile(
        line="workers_comp",
        # Matched through `_entry_matches_line_strict`, which canonicalises;
        # "employers liability" folds to workers_comp in `lob_canon._SPECIFIC`.
        phrases=("workers compensation", "employers liability"),
        fact_prefixes=("wc_",),
        fact_keys=("employers_liability_limits",),
        application_forms=("ACORD_130",),
        flag="has_workers_comp",
    ),
}


def line_profile(line: str) -> Optional[LineProfile]:
    """The profile for a canonical line family, or None when undescribed."""
    if not line or not isinstance(line, str):
        return None
    return _LINE_PROFILES.get(line.strip().lower())


def described_lines() -> frozenset:
    """The line families this module can answer for."""
    return frozenset(_LINE_PROFILES)


# ── Signal readers ───────────────────────────────────────────────────────────

def _line_fact_keys(prof: LineProfile, facts: Optional[dict]) -> Tuple[str, ...]:
    """Every fact key in `facts` that belongs to this line.

    Prefix match plus the explicit list. Never `fact_line` - see the module
    docstring for why that route is contaminated.
    """
    if not isinstance(facts, dict):
        return ()
    out = []
    for key in facts:
        if not isinstance(key, str) or key.startswith("_"):
            continue
        if key in prof.fact_keys or key.startswith(prof.fact_prefixes):
            out.append(key)
    return tuple(out)


def _value_states(prof: LineProfile, facts: Optional[dict]) -> Tuple[bool, bool]:
    """(any_stated_value, any_stated_absence) across this line's facts.

    Reads `fact_state.value_state_of`, the shipped owner of "what did this
    answer MEAN". It already resolves the whole fuzzy vocabulary a human or a
    document can produce - "None", "N/A", "not applicable", "unable to
    determine", a real value - so no text is interpreted here.

    A bare extracted `False` is `not_stated`, not `explicit_no` (fact_state's
    own rule), so a blank never reads as a denial.
    """
    keys = _line_fact_keys(prof, facts)
    if not keys:
        return (False, False)
    try:
        from services.fact_state import (
            value_state_of, PRESENT as _VS_PRESENT,
            EXPLICIT_NO as _VS_NO, NOT_APPLICABLE as _VS_NA,
        )
    except Exception:                                          # noqa: BLE001
        return (False, False)
    stated = absent = False
    for key in keys:
        try:
            state = value_state_of(facts, key)
        except Exception:                                      # noqa: BLE001
            continue
        if state == _VS_PRESENT:
            stated = True
        elif state in (_VS_NO, _VS_NA):
            absent = True
    return (stated, absent)


def _documents_grant(prof: LineProfile, facts: Optional[dict]) -> bool:
    """A `coverage_lines` entry that evidences a real POLICY on this line.

    `_line_entry_evidences_policy` is the stronger of the two grant doors:
    the entry must pass `_line_entry_grants_coverage` (a non-blank premium or
    limit that is not itself a denial) AND carry a premium or a policy number
    that is not form-number shaped. A requirement-shaped row - a carrier and
    $1M/$1M/$1M with no number, which is what an underlying-insurance schedule
    or a bare certificate heading produces - does not pass.
    """
    if not isinstance(facts, dict):
        return False
    try:
        from services.pdf_service import (
            _line_entry_evidences_policy as _evidences,
            _entry_matches_line_strict as _matches,
        )
    except Exception:                                          # noqa: BLE001
        return False
    lines = facts.get("coverage_lines")
    if isinstance(lines, dict):                     # fact envelope
        lines = lines.get("value")
    if not isinstance(lines, list):
        return False
    for entry in lines:
        if not isinstance(entry, dict):
            continue
        try:
            if not _matches(str(entry.get("line") or ""), prof.phrases):
                continue
            if _evidences(entry):
                return True
        except Exception:                                      # noqa: BLE001
            continue
    return False


def _documents_deny(prof: LineProfile, facts: Optional[dict]) -> bool:
    """The package's own coverage inventory says this line is not carried.

    `_line_absent_from_package` is positive evidence in two shapes: an
    explicit denial ("Workers Compensation - No Coverage", read from
    coverage_lines OR the verified dec entries), or a granted-line census of
    THREE or more lines in which this one never appears. Fewer than three is a
    thin inventory, not a census, and proves nothing.

    The census half is what answers the reported case: a certificate listing
    GL / Auto / Umbrella with policy numbers and a BLANK Workers Compensation
    row is a document enumerating its coverage and not naming WC.
    """
    if not isinstance(facts, dict):
        return False
    try:
        from services.pdf_service import _line_absent_from_package as _absent
    except Exception:                                          # noqa: BLE001
        return False
    try:
        return bool(_absent(facts, prof.phrases))
    except Exception:                                          # noqa: BLE001
        return False


def _applied_for(prof: LineProfile, form_ids: Optional[Iterable[Any]]) -> bool:
    """The producer selected this line's own application form.

    Applying for a coverage is the client's "intentionally requested" -
    stronger than any document evidence, because a line being applied for
    does not yet exist as a policy anywhere.

    Matched against an explicit per-line form list, never
    `fact_state.lines_applied_for` (D-AO).
    """
    if not form_ids or not prof.application_forms:
        return False
    try:
        seen = {str(f).strip().upper() for f in form_ids if f}
    except TypeError:                             # not iterable
        return False
    return any(f.upper() in seen for f in prof.application_forms)


def _flag_says_absent(prof: LineProfile, flags: Optional[dict]) -> bool:
    """The coverage flag is present AND explicitly false.

    A MISSING key is not a false one - a legacy session or a partial flags
    dict must not read as evidence of absence. See the module docstring for
    why only the False direction is trusted.
    """
    if not isinstance(flags, dict) or prof.flag not in flags:
        return False
    value = flags.get(prof.flag)
    if isinstance(value, dict):                   # envelope shape
        value = value.get("value")
    return value is False or value == 0 or value in ("false", "False")


# ── The door ─────────────────────────────────────────────────────────────────

def line_in_submission(line: str,
                       facts: Optional[dict] = None,
                       flags: Optional[dict] = None,
                       form_ids: Optional[Iterable[Any]] = None) -> str:
    """Is this coverage line part of the submission? PRESENT / ABSENT / UNKNOWN.

    Resolution order, and every branch is positive evidence:

    1. **Applied for** - the line's own application form is selected. Decisive
       PRESENT: you cannot be applying for a coverage that is not part of the
       submission, and no policy exists to evidence yet.
    2. **A stated value on one of the line's own facts**, or a document
       entry evidencing a real policy on it -> PRESENT.
    3. **A stated absence** on one of the line's own facts ("None", "N/A"),
       the document's own denial or granted-line census, or an explicitly
       false coverage flag -> ABSENT.
    4. **Both directions carry evidence** -> UNKNOWN. A genuine conflict is
       never silently resolved (Principle 4) and the caller keeps asking.
    5. **Neither** -> UNKNOWN.

    Never raises. Any unexpected input, any undescribed line, any failure to
    import a door: UNKNOWN.
    """
    prof = line_profile(line)
    if prof is None:
        return UNKNOWN

    try:
        if _applied_for(prof, form_ids):
            return PRESENT

        stated_value, stated_absence = _value_states(prof, facts)
        grants = _documents_grant(prof, facts)
        denies = _documents_deny(prof, facts)
        flag_absent = _flag_says_absent(prof, flags)

        evidence_present = bool(stated_value or grants)
        evidence_absent = bool(stated_absence or denies or flag_absent)

        if evidence_present and evidence_absent:
            # Principle 4 - do not silently resolve. The caller keeps asking.
            logger.debug(
                "line_presence: conflicting evidence for %s "
                "(value=%s grant=%s absence=%s deny=%s flag_false=%s)",
                prof.line, stated_value, grants, stated_absence, denies,
                flag_absent,
            )
            return UNKNOWN
        if evidence_present:
            return PRESENT
        if evidence_absent:
            return ABSENT
        return UNKNOWN
    except Exception as ex:                                    # noqa: BLE001
        # A presence door that raises would take a whole score down with it.
        logger.warning("line_presence: %s failed, answering UNKNOWN: %s",
                       line, ex)
        return UNKNOWN


def line_is_absent(line: str,
                   facts: Optional[dict] = None,
                   flags: Optional[dict] = None,
                   form_ids: Optional[Iterable[Any]] = None) -> bool:
    """Convenience: True ONLY on a decisive ABSENT.

    The asymmetry is the point - callers suppress on this, so UNKNOWN must
    read as "do not suppress". Never write ``not line_is_present(...)``.
    """
    return line_in_submission(line, facts, flags, form_ids) == ABSENT


def reconcile_line_flags(flags: Optional[dict],
                         facts: Optional[dict] = None,
                         form_ids: Optional[Iterable[Any]] = None) -> Dict[str, str]:
    """Bring the coverage FLAGS into line with the coverage EVIDENCE, in place.

    SYS-04, the half the narrative gate could not reach. `has_workers_comp` is
    set on a MENTION, so a blank certificate heading turns it on - and then
    every OTHER consumer of that flag charges a non-WC package for missing WC
    data: the Exposure pillar's WC block, the WC supplemental bucket, the WC
    questions, the umbrella Employers Liability warning. Measured on a
    GL+Property roofing contractor with no WC facts at all: package SQS
    **51 -> 47** and the Exposure pillar **92 -> 78** purely from the flag
    being wrong.

    Gating each consumer separately would be five copies of one rule - the
    defect SYS-04 already is. This fixes the flag ONCE, at the seam, so every
    downstream reader is correct without knowing this module exists.

    Both directions, and both need positive evidence:

    * **demote** a True flag when the line is decisively ABSENT. Note there is
      no circularity: `_flag_says_absent` only reads a FALSE flag, so a True
      flag contributes nothing to its own verdict - the denial, the census or a
      human answer has to carry it alone.
    * **restore** a False flag when the line is decisively PRESENT. Required
      because `form_routes.update_pdf` only ever demotes: without this, a flag
      dropped before the producer selected ACORD 130 would stay dropped and a
      genuine WC application would lose every WC deduction.

    UNKNOWN changes nothing. Returns ``{flag: "demoted"|"restored"}`` for the
    caller to log - the same contract as
    `extraction_service.apply_declared_absent_downgrades`. Never raises.
    """
    changed: Dict[str, str] = {}
    if not isinstance(flags, dict):
        return changed
    for line, prof in _LINE_PROFILES.items():
        try:
            verdict = line_in_submission(line, facts, flags, form_ids)
        except Exception:                                      # noqa: BLE001
            continue
        current = flags.get(prof.flag)
        if verdict == ABSENT and current not in (False, None):
            flags[prof.flag] = False
            changed[prof.flag] = "demoted"
        elif verdict == PRESENT and prof.flag in flags and current is False:
            flags[prof.flag] = True
            changed[prof.flag] = "restored"
    return changed
