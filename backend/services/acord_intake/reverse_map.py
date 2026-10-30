"""ACORD box -> fact map, LEARNED from our own stamper (see
scripts/build_acord_reverse_map.py for how and why).

A box's targets, as the builder records them:
  {"t": "fact", "fact": key, "part": "whole" | "line1" | "city" | "zip"}
  {"t": "cell", "list": key, "row": n, "col": column}            a table cell
  {"t": "cell", "list": "coverage_lines", "row": None, "col": c, "line": name}   a per-line record
  {"t": "tick", "fact": key, "value": option}                     a ticked box means fact = option
A box with no entry has no fact behind it: its value is carried box-to-box.
"""
import hashlib
import json
import logging
import os
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)

MAP_VERSION = 1
MAP_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
                        "forms_reverse", "acord_reverse_map.json")
_CACHE: Optional[dict] = None


def schema_hash(schema: dict) -> str:
    """A stable hash of a form's box set - the map is stale when it moves."""
    return hashlib.sha256("\n".join(sorted(schema or {})).encode()).hexdigest()[:16]


def _load() -> dict:
    global _CACHE
    if _CACHE is None:
        try:
            with open(MAP_PATH) as fh:
                data = json.load(fh)
            _CACHE = data if data.get("version") == MAP_VERSION else {"forms": {}}
        except Exception as ex:                                # noqa: BLE001
            logger.warning("acord reverse map unavailable: %s", ex)
            _CACHE = {"forms": {}}
    return _CACHE


def targets(form_id: str, box: str) -> List[dict]:
    """What a box on `form_id` means, [] when no fact is behind it."""
    return list(((_load().get("forms") or {}).get(form_id) or {}).get("boxes", {}).get(box) or [])


def mapped_boxes(form_id: str) -> Dict[str, List[dict]]:
    return dict(((_load().get("forms") or {}).get(form_id) or {}).get("boxes") or {})


def reset_cache() -> None:
    global _CACHE
    _CACHE = None
    _SHARED.clear()
    _SHARED_BUILT["done"] = False


# ── STRUCTURAL RULES - ACORD's own naming convention, the same on every form ──
# What the probe cannot see: values the stamper DERIVES from several facts (the
# prior-carrier grid, line-of-business ticks, per-line premiums, the status
# ticks) and two-letter state codes, which cannot carry a unique marker. Read off
# the box NAME, so a form added later is covered the day its template arrives.
import re as _re

# Box-name line tokens -> the line names the rest of the system uses
# (`answer_options` lines_of_business / `lob_canon`).
LINE_TOKENS = {
    "GeneralLiability": "General Liability", "CommercialGeneralLiability": "General Liability",
    "Automobile": "Business Auto", "BusinessAuto": "Business Auto", "CommercialVehicle": "Business Auto",
    "Property": "Commercial Property", "CommercialProperty": "Commercial Property",
    "Umbrella": "Umbrella or Excess Liability", "CommercialUmbrella": "Umbrella or Excess Liability",
    "CommercialInlandMarine": "Inland Marine", "Crime": "Crime", "CyberAndPrivacy": "Cyber Liability",
    "LiquorLiability": "Liquor Liability", "BusinessOwners": "Business Owners",
    "BoilerAndMachinery": "Boiler and Machinery", "GarageAndDealers": "Garage and Dealers",
    "Truckers": "Truckers", "MotorCarrier": "Motor Carrier", "Yacht": "Yacht",
    "Fiduciary": "Fiduciary Liability", "FiduciaryLiability": "Fiduciary Liability",
    "WorkersCompensation": "Workers Compensation",
}
_PRIOR_ATTRS = {"InsurerFullName": "carrier", "PolicyNumberIdentifier": "policy_no",
                "TotalPremiumAmount": "premium", "EffectiveDate": "effective",
                "ExpirationDate": "expiration", "LineOfBusinessCode": "line"}
_PRIOR_RE = _re.compile(r"^PriorCoverage_(?P<line>[A-Za-z]+)_(?P<attr>[A-Za-z]+)_(?P<row>[A-N])$")
_LOB_TICK_RE = _re.compile(r"^Policy_LineOfBusiness_(?P<tok>[A-Za-z]+?)(?:Indicator)?_(?P<row>[A-N])$")
_LOB_OTHER_RE = _re.compile(r"^Policy_LineOfBusiness_OtherLineOfBusinessDescription_(?P<row>[A-N])$")
_LINE_PREMIUM_RE = _re.compile(r"^(?P<tok>[A-Za-z]+?)LineOfBusiness_(?:Total)?PremiumAmount_A$")
_PART_SIBLINGS = {"StateOrProvinceCode": "state", "CountyName": "county", "LineTwo": "line2"}


_SYMBOL_RE = _re.compile(r"^Vehicle_(?:BusinessAuto|Truckers|MotorCarrier|GarageAndDealers)Symbol_"
                         r"(?P<num>[A-Za-z]+?)Indicator_A$")
_UNITS = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8, "nine": 9}
_TENS = {"twenty": 20, "thirty": 30, "forty": 40, "fifty": 50, "sixty": 60, "seventy": 70}


def _number_words(word: str) -> Optional[int]:
    """"Seven" -> 7, "TwentyOne" -> 21, "SeventyOne" -> 71; None for "OtherSymbol"."""
    parts = [p.lower() for p in _re.findall(r"[A-Z][a-z]*", word or "")]
    total = 0
    for p in parts:
        if p in _TENS:
            total += _TENS[p]
        elif p in _UNITS:
            total += _UNITS[p]
        else:
            return None
    return total or None


def structural_targets(box: str) -> List[dict]:
    """Targets a box's ACORD name gives it, [] when the name says nothing."""
    m = _PRIOR_RE.match(box or "")
    if m and m.group("attr") in _PRIOR_ATTRS:
        line = LINE_TOKENS.get(m.group("line"), "") if m.group("line") != "OtherLine" else ""
        return [{"t": "prior", "row": m.group("row"), "line_token": m.group("line"),
                 "line": line, "col": _PRIOR_ATTRS[m.group("attr")]}]
    if _re.match(r"^PriorCoverage_PolicyYear_[A-N]$", box or ""):
        return [{"t": "prior", "row": box[-1], "line_token": "*", "line": "", "col": "year"}]
    m = _LOB_OTHER_RE.match(box or "")
    if m:
        return [{"t": "lob_other", "row": m.group("row")}]
    m = _LOB_TICK_RE.match(box or "")
    if m:
        tok = m.group("tok")
        if tok == "Other":
            return [{"t": "lob_other_tick", "row": m.group("row")}]
        if tok in LINE_TOKENS:
            return [{"t": "tick", "fact": "lines_of_business", "value": LINE_TOKENS[tok]}]
    # A per-line PREMIUM box is never mapped: on ACORD 125 page one it is the
    # PROPOSED premium, on a section form either the proposed or the expiring
    # one - it must never overwrite a dec's current premium. Carried instead.
    if _LINE_PREMIUM_RE.match(box or ""):
        return [{"t": "carry"}]
    # The premises coverage grid's coded columns (ACORD 140 / 160): one package
    # value each, read off the first row that states it. ValuationCode letters are
    # the stamper's own table inverted (`pdf_service._VALUATION_METHOD_TO_ACORD_CODE`).
    if _re.match(r"^CommercialProperty_Premises_CoinsurancePercent_[A-Z]$", box or ""):
        return [{"t": "fact", "fact": "coinsurance_percentage", "part": "whole", "from_rows": True}]
    if _re.match(r"^CommercialProperty_Premises_ValuationCode_[A-Z]$", box or ""):
        return [{"t": "code", "fact": "valuation_method", "table": "valuation", "from_rows": True}]
    # The covered-auto symbol grid: ROW A is the liability row (the only row
    # offering symbols 1 and 9 - `auto_symbols.py`); rows B-H cannot be told
    # apart from the schema, so they are carried, never read as a coverage.
    m = _SYMBOL_RE.match(box or "")
    if m:
        n = _number_words(m.group("num"))
        return [{"t": "symbol", "coverage": "liability", "symbol": n}] if n else []
    if box == "Policy_Status_RenewIndicator_A":
        return [{"t": "tick", "fact": "is_renewal", "value": "Yes"}]
    # ACORD's application REMARKS boxes (the 101's Additional Remarks Schedule,
    # the 125's Remarks / Processing Instructions) hold the remarks. The probe
    # saw OTHER facts composed into them too - Primble's own continuation blocks
    # (a 4th loss row, the approved narrative) - which a reader must never take
    # back as those facts: a loss row whose claim number was the whole remark,
    # a narrative that printed twice (review, 27 Oct 2026). `read.py` cuts our
    # own blocks out of the text (`own_blocks_removed`).
    # Which forms are ATTACHED is this package's own fact (the engine ticks
    # these from the package) - never read, never carried from an upload.
    if "_Attachment_" in (box or ""):
        return [{"t": "package"}]
    if _REMARKS_RE.match(box or ""):
        return [{"t": "fact", "fact": "additional_remarks_text", "part": "whole", "prose": True}]
    return []


_REMARKS_RE = _re.compile(r"^(?:AdditionalRemark|CommercialPolicy)_RemarkText_[A-Z]$")
# The header of an application form names the policy APPLIED FOR: ACORD 125
# (SCOPE_OVERRIDES), and every section form - the editor's write-back reads the
# header dates as the PROPOSED term (`pdf_service.proposed_term_fact`). The
# probe learned the stamper's current-policy identity there (Brent: section
# forms print the current policy per line), which an outside agency's form does
# not hold; read back as a current line record it merged the proposed date into
# the dec's GL policy (effective 01/01/2027, expiration 01/01/2026), and on ACORD
# 160 / 138 it invented a Cyber / Inland Marine policy. So the header's dates
# are the proposed term; its carrier, NAIC and number are the form's OWN line's
# current policy (`_header_line_targets`) or carried. Certificates (25 / 28)
# document the EXISTING policy and keep their learned reading.
_HEADER_RE = _re.compile(r"^(?:Insurer_(?:FullName|NAICCode)|Policy_PolicyNumberIdentifier)_A$")
CERTIFICATE_FORMS = frozenset({"ACORD_25", "ACORD_28"})
# The lines each section form applies for, from each template's OWN printed
# title (ACORD 141 = CRIME SECTION, 160 = BUSINESS OWNERS SECTION, 138 = GARAGE
# AND DEALERS SECTION - CLAUDE.md "Supported ACORD Forms").
FORM_FAMILIES = {
    "ACORD_126": ("general_liab",), "ACORD_127": ("auto",), "ACORD_137_CA": ("auto",),
    "ACORD_137_CO": ("auto",), "ACORD_138_CA": ("auto",), "ACORD_138_CO": ("auto",),
    "ACORD_130": ("workers_comp",), "ACORD_133": ("workers_comp",), "ACORD_131": ("umbrella",),
    "ACORD_140": ("property",), "ACORD_141": ("crime",), "ACORD_160": ("property", "general_liab"),
    "ACORD_186": ("general_liab",),
}


def _header_line_targets(form_id: str, box: str) -> List[dict]:
    """A section form's header CARRIER / NAIC / POLICY NUMBER: the current
    policy of the form's OWN line (Brent: section forms keep the current
    policy's identity per line - the stamper prints exactly that, and the
    excess 131's header is the only place its layer's carrier is printed). A
    learned line the form's title does not name is the stamper's quirk, never a
    policy: ACORD 160 (Business Owners) read as a CYBER policy, 138 (Garage and
    Dealers) as INLAND MARINE (review, 27 Oct 2026). Never the date - that is
    the proposed term (`proposal_targets`)."""
    fams = FORM_FAMILIES.get(_base(form_id))
    if not fams:
        return []
    try:
        from services.lob_canon import canon_line
    except Exception:                                          # noqa: BLE001
        return []
    out = [t for t in targets(form_id, box)
           if t.get("t") == "cell" and t.get("list") == "coverage_lines" and t.get("line")
           and t.get("col") in ("carrier", "naic", "policy_number")
           and canon_line(str(t["line"])) in fams]
    return out


def _base(form_id: str) -> str:
    try:
        from services.form_instances import base_form_id
        return base_form_id(form_id)
    except Exception:                                          # noqa: BLE001
        return str(form_id or "").split("__")[0]


def proposal_targets(form_id: str, box: str) -> List[dict]:
    """An application header box: carried, or the proposed term."""
    if _base(form_id) in CERTIFICATE_FORMS:
        return []
    if _HEADER_RE.match(box or ""):
        return _header_line_targets(form_id, box) or [{"t": "carry"}]
    if not is_known_form(form_id):
        # A form outside our 17 (ACORD 807 D&O, a cyber or EPL application) dates
        # ITS OWN line's policy - never the package's proposed term: the 807's
        # requested 01/15/2027 D&O term replaced the dec renewal's 12/01/2026 on
        # the 125's page one (expert review, 29 Oct 2026). The shared dictionary
        # already judges these boxes scope-sensitive; this layer ran first.
        return []
    try:
        from services.pdf_service import proposed_term_fact
        fact = proposed_term_fact(form_id, box)
    except Exception:                                          # noqa: BLE001
        fact = None
    return [{"t": "fact", "fact": fact, "part": "whole"}] if fact else []


# ACORD 25's "INSURER(S) AFFORDING COVERAGE" is a ROSTER - letters A..F - joined
# to each coverage row by its INSR LTR box. The probe gave each letter the line
# it happened to sit beside in the probe (B = Business Auto), so a certificate
# whose auto is written by insurer A and WC by insurer B read the WC insurer as
# the auto carrier (review, 27 Oct 2026). Read by the join, as the stamper
# writes it (`pdf_service._resolve_certificate_insurer_letter`). Any form whose
# schema carries INSR LTR boxes is a roster form.
_ROSTER_RE = _re.compile(r"^Insurer_(?P<col>FullName|NAICCode)_(?P<letter>[A-F])$")
_LETTER_RE = _re.compile(r"^(?P<sec>[A-Za-z]+)_InsurerLetterCode_A$")
_ROSTER_FORMS: Dict[str, bool] = {}


def _is_roster_form(form_id: str) -> bool:
    fid = _base(form_id)
    if fid not in _ROSTER_FORMS:
        try:
            from services.acord_intake.recognize import schema_names
            _ROSTER_FORMS[fid] = any("_InsurerLetterCode_" in n for n in schema_names().get(fid, ()))
        except Exception:                                      # noqa: BLE001
            _ROSTER_FORMS[fid] = False
    return _ROSTER_FORMS[fid]


def roster_targets(form_id: str, box: str) -> List[dict]:
    if not _is_roster_form(form_id):
        return []
    m = _ROSTER_RE.match(box or "")
    if m:
        return [{"t": "roster", "letter": m.group("letter"),
                 "col": "carrier" if m.group("col") == "FullName" else "naic"}]
    m = _LETTER_RE.match(box or "")
    if not m:
        return []
    try:
        from services.pdf_service import _CERT_SECTION_POLICY_COLUMN
        column = _CERT_SECTION_POLICY_COLUMN.get(m.group("sec"))
    except Exception:                                          # noqa: BLE001
        column = None
    if not column:
        return [{"t": "carry"}]
    for t in targets(form_id, f"Policy_{column}_PolicyNumberIdentifier_A"):
        if t.get("t") == "cell" and t.get("list") == "coverage_lines" and t.get("line"):
            return [{"t": "roster_ref", "line": t["line"]}]
    return [{"t": "carry"}]


def sound_targets(box: str, learned: List[dict]) -> List[dict]:
    """The learned targets a reader can trust, [{"t": "carry"}] when none.
      * a box on row B..N is another entity's row (a subsidiary on ACORD 131, a
        2nd vehicle): it never writes a package SCALAR (`pdf_service.
        scalar_rules_reach`, the stamper's and the questionnaire's own rule);
      * a prose box (it prints a whole fact) never fills a table cell - a cell
        seen there was a row the stamper composed into the prose;
      * a box printing two different whole facts is composed: no one of them."""
    if not learned:
        return []
    out = list(learned)
    try:
        from services.pdf_service import scalar_rules_reach
        if not scalar_rules_reach(box):
            out = [t for t in out if not (t.get("t") == "fact" and "#" not in str(t.get("fact")))]
    except Exception:                                          # noqa: BLE001
        pass
    wholes = {t.get("fact") for t in out if t.get("t") == "fact" and t.get("part") == "whole"}
    if wholes:
        out = [t for t in out if t.get("t") != "cell"]
    if len(wholes) > 1:
        return [{"t": "carry"}]
    return out or [{"t": "carry"}]


def sibling_targets(form_id: str, box: str) -> List[dict]:
    """A state / county / second address line takes its part from the address its
    row siblings map to ("NamedInsured_MailingAddress_StateOrProvinceCode_A" ->
    the fact `..._CityName_A` maps to)."""
    m = _re.match(r"^(?P<pre>.+)_(?P<part>StateOrProvinceCode|CountyName|LineTwo)_(?P<row>[A-N])$", box or "")
    if not m:
        return []
    for sib in ("CityName", "LineOne", "PostalCode"):
        sib_box = f"{m.group('pre')}_{sib}_{m.group('row')}"
        for t in sound_targets(sib_box, learned_targets(form_id, sib_box)):
            part = _PART_SIBLINGS[m.group("part")]
            if t.get("t") == "fact" and t.get("part") in ("line1", "city", "zip"):
                return [{**t, "part": part}]
            if t.get("t") == "cell" and str(t.get("col") or "").startswith("address_"):
                return [{**t, "col": f"address_{part}"}]
    return []


# SCOPE: ACORD 125 page one is the policy APPLIED FOR (Brent's 125 answer key):
# its CARRIER is the carrier receiving the submission, never the current carrier
# the decs print; its NAIC and POLICY NUMBER belong to that proposal and are
# carried, never read as the current policy's.
SCOPE_OVERRIDES: Dict[tuple, List[dict]] = {
    ("ACORD_125", "Insurer_FullName_A"): [{"t": "fact", "fact": "submission_carrier_name", "part": "whole"}],
    ("ACORD_125", "Insurer_NAICCode_A"): [{"t": "carry"}],
    ("ACORD_125", "Policy_PolicyNumberIdentifier_A"): [{"t": "carry"}],
    # A certificate's description describes the certificate's operations /
    # vehicles / locations, the registry's own fact for it - not the insured's
    # operations description.
    ("ACORD_25", "CertificateOfLiabilityInsurance_ACORDForm_RemarkText_A"):
        [{"t": "fact", "fact": "certificate_description_of_operations", "part": "whole"}],
}


# An amount box whose MEANING its row's ticks decide. ACORD 137's liability row
# prints one amount and two ticks: "the limit shown is for combined single
# limit" / "... is the bodily injury each person limit" (ACORD's own tooltips).
# The probe saw the stamper print the CSL there with the CSL tick on, so it
# learned "always the CSL" - an outside 137 with SPLIT limits would have read a
# $250,000 per-person limit as a $250,000 CSL (review, 27 Oct 2026). The split
# fact is the stamper's own rule for the box (`_ACORD_FIELD_RULES`).
_PER_PERSON_RE = _re.compile(r"^(?P<p>.+)_BodilyInjury_PerPersonLimitAmount_(?P<r>[A-N])$")


# A party NAME whose row offers interest-type ticks (ACORD 125 / 126 / 28's
# ADDITIONAL INTEREST: additional insured, mortgagee, lienholder, loss payee,
# other ...). The probe learned the role the stamper prints there (the loss
# payee); our own 125 prints the LANDLORD in that box (Brent, 8 Oct, ticked
# "Other: Landlord"), so a re-read made the landlord the loss payee (review,
# 27 Oct 2026). The name is that role's only when that role's tick is on.
_PARTY_NAME_RE = _re.compile(r"^(?P<p>.+)_FullName_(?P<r>[A-N])$")


def _role_scoped(names, box: str, learned: List[dict]) -> Optional[List[dict]]:
    m = _PARTY_NAME_RE.match(box or "")
    fact = next((t["fact"] for t in learned if t.get("t") == "fact" and t.get("part") == "whole"), None)
    if not m or not fact:
        return None
    pre, row = m.group("p"), m.group("r")
    ticks = [n for n in names if n.startswith(f"{pre}_Interest_") and n.endswith(f"Indicator_{row}")]
    if not ticks:
        return None
    role = "".join(w.capitalize() for w in _re.sub(r"_name$", "", fact).split("_"))
    tick = f"{pre}_Interest_{role}Indicator_{row}"
    if tick not in names:
        return [{"t": "carry"}]
    return [{"t": "by_tick", "csl_box": tick, "each_box": None, "csl_fact": fact, "each_fact": None}]


def tick_scoped_targets(form_id: str, box: str, learned: List[dict]) -> List[dict]:
    try:
        from services.acord_intake.recognize import schema_names
        names = schema_names().get(_base(form_id), set())
    except Exception:                                          # noqa: BLE001
        return learned
    scoped = _role_scoped(names, box, learned)
    if scoped is not None:
        return scoped
    m = _PER_PERSON_RE.match(box or "")
    if not m:
        return learned
    csl = f"{m.group('p')}_CombinedSingleLimit_LimitIndicator_{m.group('r')}"
    each = f"{m.group('p')}_BodilyInjury_EachPersonLimitIndicator_{m.group('r')}"
    if csl not in names or each not in names:
        return learned
    try:
        from services.pdf_service import _ACORD_FIELD_RULES
        split = next((k for pat, k in _ACORD_FIELD_RULES if k and not str(k).startswith("_") and pat in box), None)
    except Exception:                                          # noqa: BLE001
        split = None
    csl_fact = next((t["fact"] for t in learned if t.get("t") == "fact" and t.get("part") == "whole"), None)
    if csl_fact == split:
        csl_fact = None
    return [{"t": "by_tick", "csl_box": csl, "each_box": each, "csl_fact": csl_fact, "each_fact": split}]


def box_targets(form_id: str, box: str) -> List[dict]:
    """The one lookup: a scope override, then ACORD's structural naming (it knows
    which LINE a prior-carrier or line-of-business box is), then the learned
    map (for a form we hold no map for: ACORD's shared field dictionary,
    `shared_targets`), then a state / county / line-two sibling.
    [{"t": "carry"}] = carry."""
    if (form_id, box) in SCOPE_OVERRIDES:
        return list(SCOPE_OVERRIDES[(form_id, box)])
    tg = _box_targets(form_id, box)
    if tg and not is_known_form(form_id):
        tg = [t for t in tg if _fact_base(t) not in OUTSIDE_LINE_SCOPED_FACTS]
    return tg


# The SUBMISSION's own terms, which a form outside our 17 states only for ITS
# line: an ACORD 807 D&O renewal tick is not the package's renewal (it routed a
# new-business package's proposed term into prior_*), its payment plan / audit
# is the D&O policy's, and its remarks are about that line - never the
# package's ACORD 101 remarks (Michelle review, 30 Oct 2026). The structural
# layer reads these boxes by name on every form, so the scope is applied here,
# after every layer. The box stays "read from the form".
OUTSIDE_LINE_SCOPED_FACTS = frozenset({
    "is_renewal", "submission_is_new_business", "billing_plan", "payment_plan", "audit_period",
    "additional_remarks_text", "effective_date", "expiration_date", "submission_carrier_name",
    "additional_named_insureds",
})


def _box_targets(form_id: str, box: str) -> List[dict]:
    return (structural_targets(box) or applicant_row_a_targets(box) or roster_targets(form_id, box)
            or proposal_targets(form_id, box)
            or registry_targets(box) or garaging_targets(box)
            or tick_scoped_targets(form_id, box, sound_targets(box, learned_targets(form_id, box)))
            or sibling_targets(form_id, box))


# ── ACORD'S SHARED FIELD DICTIONARY (29 Oct 2026, ASG_TRANSCRIBER.md "Keep
# everything") ─────────────────────────────────────────────────────────────────
# Transcriber reads every box of ANY ACORD form (800+), named by ACORD's eLabel -
# ONE data dictionary shared by every form. The learned map knows only our 17
# forms, so a form outside them (ACORD 807 D&O) mapped only what the structural
# layers know. For such a form, a box name is looked up across our 17: when every
# known form that prints the name gives it the SAME meaning, that meaning is used;
# when they disagree, or the meaning is scope-sensitive (a policy-line record, a
# certificate's insurer roster, a tick-scoped amount, one form's own schedule),
# nothing is guessed - the box stays "read from the form" (kept, shown, never
# a fact). Our 17 forms never use this layer.
_SCOPE_SENSITIVE_KINDS = frozenset({"carry", "roster", "roster_ref", "by_tick", "package", "prior",
                                    "lob_other", "lob_other_tick", "symbol", "cell_all"})
_SHARED: Dict[str, dict] = {}


def is_known_form(form_id: str) -> bool:
    """One of our 17 forms (a schema and a learned map)."""
    try:
        from services.acord_intake.recognize import schema_names
        return _base(form_id) in schema_names()
    except Exception:                                          # noqa: BLE001
        return False


def _scope_sensitive(fid: str, box: str, tg: List[dict]) -> bool:
    if (fid, box) in SCOPE_OVERRIDES:
        return True                       # a form-specific reading (125's proposed carrier ...)
    for t in tg:
        if t.get("t") in _SCOPE_SENSITIVE_KINDS:
            return True
        if t.get("line") or (t.get("t") == "cell" and t.get("list") == "coverage_lines"):
            return True                   # one policy line's record
    return False


def _entry_for(box: str, names: Dict[str, set]) -> dict:
    """One eLabel's verdict from every known form printing it."""
    votes: Dict[str, List[dict]] = {}
    forms: List[str] = []
    status = "unknown"
    for fid in sorted(names):
        if box not in names[fid]:
            continue
        tg = box_targets(fid, box)
        if not tg:
            continue                      # no meaning on that form: it abstains
        forms.append(fid)
        if _scope_sensitive(fid, box, tg):
            status = "scope"
            break
        votes[json.dumps(sorted(tg, key=lambda t: json.dumps(t, sort_keys=True)), sort_keys=True)] = tg
    entry: dict = {"targets": [], "status": status, "forms": forms}
    if status != "scope" and votes:
        if len(votes) > 1:
            entry["status"] = "disagree"
        else:
            tg = next(iter(votes.values()))
            if any(t.get("t") == "cell" for t in tg) and len(forms) < 2:
                entry["status"] = "single_form_schedule"   # that form's own schedule rows
            else:
                entry.update(status="agreed", targets=[dict(t) for t in tg])
    return entry


import threading as _threading
_SHARED_LOCK = _threading.Lock()
_SHARED_BUILT = {"done": False}


def build_shared_dictionary() -> int:
    """Every eLabel of our 17 schemas judged ONCE per process (about 3 s) - warmed
    off the request path at startup (`main.startup`), so an upload never pays it
    inline. The same verdicts the per-name lookup gives. Returns the names built."""
    with _SHARED_LOCK:
        if _SHARED_BUILT["done"]:
            return len(_SHARED)
        try:
            from services.acord_intake.recognize import schema_names
            names = schema_names()
        except Exception:                                      # noqa: BLE001
            names = {}
        for box in sorted(set().union(*names.values()) if names else ()):
            if box not in _SHARED:
                _SHARED[box] = _entry_for(box, names)
        _SHARED_BUILT["done"] = True
        return len(_SHARED)


def shared_entry(box: str) -> dict:
    """{"targets": [...], "status": agreed | disagree | scope | single_form_schedule
    | unknown, "forms": [...]} for one eLabel, from every known form printing it
    (`box_targets` of that form - its full, reviewed reading)."""
    if box in _SHARED:
        return _SHARED[box]
    if not _SHARED_BUILT["done"]:
        build_shared_dictionary()
        if box in _SHARED:
            return _SHARED[box]
    return {"targets": [], "status": "unknown", "forms": []}   # no known form prints it


# Facts a form OUTSIDE our 17 never feeds even when our forms agree on the box:
# who the line's insureds are. ACORD 807 prints the signer in NamedInsured_FullName_B
# (with NamedInsured_Title_A), and a D&O / EPL "insured" list is that line's own
# (directors, subsidiaries) - never the package's additional named insureds
# (expert review, 29 Oct 2026). The box stays "read from the form".
_SHARED_LINE_SCOPED_FACTS = frozenset({"additional_named_insureds"})


def _fact_base(t: dict) -> str:
    return str(t.get("fact") or t.get("list") or "").split("#", 1)[0]


def shared_targets(box: str) -> List[dict]:
    """The agreed meaning of `box` across our 17 forms, [] when none."""
    tg = [dict(t) for t in shared_entry(box)["targets"]]
    if any(_fact_base(t) in _SHARED_LINE_SCOPED_FACTS for t in tg):
        return []
    return tg


def learned_targets(form_id: str, box: str) -> List[dict]:
    """The learned map for our forms; ACORD's shared dictionary for any other."""
    if is_known_form(form_id):
        return targets(form_id, box)
    return shared_targets(box)


def applicant_row_a_targets(box: str) -> List[dict]:
    """The applicant's BUSINESS PHONE # box (row A) -> `applicant_business_phone`,
    by the stamper's own table (`pdf_service._APPLICANT_ROW_A_FACTS`, printed by
    a resolver the probe does not see). Without it an outside ACORD 125's
    business phone was only carried box-to-box, and no Data Consistency
    comparison read it (item 8, 29 Oct 2026). Only the phone: the table's other
    boxes (GL CODE, member count, installation %) keep the reading they have -
    their facts have their own doors (`_applicant_gl_codes_from_schedule`)."""
    try:
        from services.pdf_service import _APPLICANT_ROW_A_FACTS
    except Exception:                                          # noqa: BLE001
        return []
    fact = _APPLICANT_ROW_A_FACTS.get(box or "")
    return [{"t": "fact", "fact": fact, "part": "whole"}] if fact == "applicant_business_phone" else []


def garaging_targets(box: str) -> List[dict]:
    """An ACORD 127 vehicle row's garaging city / state / ZIP (and its cost new
    / stated amount) -> that vehicle row's own column - the stamper's own table
    (`pdf_service.VEHICLE_GARAGING_ROW_COLS`; the probe never marks these
    columns, which no extraction schema lists)."""
    try:
        from services.pdf_service import _VEHICLE_GARAGING_RE, VEHICLE_GARAGING_ROW_COLS, _ROW_LETTER_TO_IDX
    except Exception:                                          # noqa: BLE001
        return []
    m = _VEHICLE_GARAGING_RE.match(box or "")
    col = VEHICLE_GARAGING_ROW_COLS.get(m.group(1)) if m else None
    letter = m.group(2) if m else None
    if not col:
        # The row's own COST NEW / AGREED-STATED AMOUNT, by the stamper's own
        # box patterns (`_resolve_vehicle_cost_new` / `_stated_amount`): the
        # probe marks no `cost_new` cell either, and the round trip's 127 came
        # back with no vehicle cost (27 Oct 2026).
        try:
            from services.pdf_service import _VEHICLE_COST_NEW_RE, _VEHICLE_STATED_AMOUNT_RE
        except Exception:                                      # noqa: BLE001
            return []
        for rx, c in ((_VEHICLE_COST_NEW_RE, "cost_new"), (_VEHICLE_STATED_AMOUNT_RE, "stated_amount")):
            mm = rx.match(box or "")
            if mm:
                col, letter = c, mm.group(1)
                break
    if not col or letter not in _ROW_LETTER_TO_IDX:
        return []
    return [{"t": "cell", "list": "auto_vin_schedule", "row": _ROW_LETTER_TO_IDX[letter], "col": col}]


def registry_targets(box: str) -> List[dict]:
    """A table cell the stamper's own name binding gives the box
    (`pdf_service._SCHEDULE_REGISTRY`: "Vehicle_VINIdentifier_B" -> vehicle row 2's
    VIN). Exact by construction - the probe cannot mark a VIN the stamper's VIN
    check refuses, nor a year. A driver's given name / surname are halves of one
    name; columns the stamper derives (other "_" sentinels) are not read back."""
    m = _re.match(r"^(?P<base>.+)_(?P<row>[A-N])$", box or "")
    if not m:
        return []
    try:
        from services.pdf_service import _SCHEDULE_REGISTRY, _ROW_LETTER_TO_IDX
    except Exception:                                          # noqa: BLE001
        return []
    d = _SCHEDULE_REGISTRY.get(m.group("base"))
    if d is None or not d.sub_key:
        return []
    row = _ROW_LETTER_TO_IDX.get(m.group("row"), -1) - (d.row_offset or 0)
    if row < 0:
        return []
    col = d.sub_key
    if col == "_wc_sheet_state":
        # The rating sheet's ONE state, printed only when every class row shares
        # it - read back onto every class row that names none.
        return [{"t": "cell_all", "list": d.list_key, "col": "state"}]
    if col == "_name_given":
        return [{"t": "cell", "list": d.list_key, "row": row, "col": "_given"}]
    if col == "_name_surname":
        return [{"t": "cell", "list": d.list_key, "row": row, "col": "_surname"}]
    if col.startswith("_"):
        return []
    return [{"t": "cell", "list": d.list_key, "row": row, "col": col}]


def decode(table: str, code: str) -> Optional[str]:
    """A one-letter ACORD code back to the value the stamper coded it from."""
    if table == "valuation":
        try:
            from services.pdf_service import _VALUATION_METHOD_TO_ACORD_CODE as _t
            inv = {}
            for method, letter in _t.items():
                inv.setdefault(str(letter).upper(), method)
            return inv.get(str(code or "").strip().upper())
        except Exception:                                      # noqa: BLE001
            return None
    return None
