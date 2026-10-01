"""
audit_125_rules.py - check a generated ACORD 125 against every rule we hold,
on ANY package, with NO answer key.

    python3 backend/scripts/audit_125_rules.py run.json            # a dump
    python3 backend/scripts/audit_125_rules.py run.json --json-out audit.json
    python3 backend/scripts/audit_125_rules.py --pdf filled.pdf --text doc.txt

`run.json` is what `dump_a125_run.py <session_id>` writes: the stamped boxes,
the merged facts, the uploaded text and which pass wrote each box.

WHY THIS EXISTS
---------------
An answer key only exists for a package we built. A client's package has none,
and that is exactly where a rule we wrote for one fixture can quietly stop
holding. So every rule here is stated WITHOUT knowing the right answers -
it checks the form against the documents and against itself:

  CLIENT rules    from the client's own answer key (125_reference/, 8-19-26)
  STANDING rules  contracts this codebase already enforces (right-or-blank,
                  placeholders, authorship, shapes, grounding)

EVERY RULE SAYS WHETHER IT WAS EXERCISED
----------------------------------------
"Still applicable?" has two halves. A rule can PASS or FAIL - or the package
may simply never trigger it (no losses, so the loss-total rule has nothing to
check). A rule that was not exercised proved nothing, and the report says so
instead of counting it as a pass.

The rule logic that the stamper already owns is IMPORTED, never re-typed: the
"a No leaves its block empty" check reads `pdf_service`'s own dependent blocks
and explanation pairs, so this audit cannot disagree with the product about
which boxes belong to which question.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import os
import re
import sys
from datetime import date, timedelta
from pathlib import Path
from typing import Callable, Dict, List, Optional, Tuple

HERE = Path(__file__).resolve()
BACKEND = HERE.parents[1]
sys.path.insert(0, str(BACKEND))
os.environ.setdefault("OPENAI_API_KEY", "sk-offline")

FORM = "ACORD_125"


def _load_scorer():
    spec = importlib.util.spec_from_file_location("_sff", str(HERE.parent / "score_form_fill.py"))
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


SFF = _load_scorer()
same, blank, norm, as_date = SFF.same, SFF.blank, SFF.norm, SFF._as_date
plain = SFF.plain          # Y / N / codes: NEVER `norm` (it reads "N" as "north")

TICK = {"y", "yes", "on", "x", "true", "1", "checked", "/yes", "/on"}


def ticked(v) -> bool:
    return str(v if v is not None else "").strip().lower() in TICK


def filled(v) -> bool:
    return not blank(v)


def q(code: str) -> str:
    return f"CommercialPolicy_Question_{code}Code_A"


# ═════════════════════════════════════════════════════════════════════════════
# The document, as something a value can be grounded in
# ═════════════════════════════════════════════════════════════════════════════
_MONTHS = "(?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*"


def _numbers(text: str) -> set:
    out = set()
    for n in re.findall(r"\d[\d,]*(?:\.\d+)?", text):
        n = n.replace(",", "")
        if "." in n:
            n = n.rstrip("0").rstrip(".")
        out.add(n.lstrip("0") or "0")
    return out


class Hay:
    def __init__(self, raw: str):
        self.raw = raw or ""
        low = self.raw.lower()
        self.alnum = re.sub(r"[^a-z0-9]", "", low)
        self.tokens = set(SFF._expand_abbreviations(" ".join(re.findall(r"[a-z0-9]+", low))).split())
        self.numbers = _numbers(low)
        self.dates = set()
        for m in re.finditer(r"\b\d{1,2}/\d{1,2}/\d{2,4}\b|\b\d{4}-\d{2}-\d{2}\b|"
                             rf"\b{_MONTHS}\.? \d{{1,2}},? \d{{4}}\b", low):
            d = as_date(m.group(0).replace(".", "").title())
            if d:
                self.dates.add(d)

    def grounded(self, value, narrative: bool = False) -> Tuple[Optional[bool], str]:
        v = str(value if value is not None else "").strip()
        a = re.sub(r"[^a-z0-9]", "", v.lower())
        if len(a) <= 2:
            return None, "too short to judge"
        d = as_date(v)
        if d is not None:
            if d in self.dates:
                return True, "date printed"
            try:
                prev = d.replace(year=d.year - 1)
            except ValueError:
                prev = d - timedelta(days=365)
            if prev in self.dates:
                return True, "derived: the term after a printed date"
            return False, "date printed nowhere"
        if re.fullmatch(r"[\$\s]*-?[\d,]+(\.\d+)?\s*%?", v):
            return (True, "number printed") if _numbers(v) <= self.numbers \
                else (False, "number printed nowhere")
        if a in self.alnum:
            return True, "verbatim"
        words = SFF._expand_abbreviations(" ".join(re.findall(r"[a-z0-9]+", v.lower()))).split()
        words = [w for w in words if len(w) > 2 or w.isdigit()]
        if not words:
            return None, "too short to judge"
        if not (_numbers(v) <= self.numbers):
            return False, "contains a number printed nowhere"
        if narrative:
            # content words only - a paraphrase keeps the facts, not the "was / and"
            words = [w for w in words if w not in SFF._STOP] or words
        missing = [w for w in words if w not in self.tokens]
        if len(missing) > (len(words) * 0.2 if narrative else 0):
            return False, f"words printed nowhere: {missing[:4]}"
        # LOCAL, not anywhere. In a 500,000-character package every common word
        # is printed SOMEWHERE, so "each word exists" grounds any invented
        # sentence (28 Sep: "water damage to warehouse from a burst pipe" passed).
        # The words must stand together - within one passage.
        share = self.local_share(words)
        need = 0.8 if narrative else 1.0
        if share >= need:
            return True, f"{share:.0%} of its words printed together"
        return False, f"its words are printed, but never together ({share:.0%} in any one passage)"

    def local_share(self, words, reach: int = 450) -> float:
        low = self.raw.lower()
        uniq = list(dict.fromkeys(words))
        counts = {w: low.count(w) for w in uniq}
        anchor = min((w for w in uniq if counts[w]), key=lambda w: counts[w], default=None)
        if anchor is None:
            return 0.0
        best, start, seen = 0.0, 0, 0
        while seen < 300:
            pos = low.find(anchor, start)
            if pos < 0:
                break
            window = low[max(0, pos - reach):pos + reach]
            best = max(best, sum(1 for w in uniq if w in window) / len(uniq))
            if best >= 1.0:
                break
            start, seen = pos + 1, seen + 1
        return best


# ═════════════════════════════════════════════════════════════════════════════
# Context
# ═════════════════════════════════════════════════════════════════════════════
class Ctx:
    def __init__(self, stamped: dict, facts: dict, raw: str, fates: dict,
                 package: Optional[List[str]] = None):
        self.package = [str(f) for f in (package or []) if f]
        self.v = {k: ("" if v is None else str(v)) for k, v in (stamped or {}).items()}
        self.facts = facts or {}
        self.hay = Hay(raw)
        self.has_text = bool((raw or "").strip())
        self.fates = fates if isinstance(fates, dict) else {}
        self.schema = SFF._schema(FORM)
        import services.pdf_service as ps
        self.ps = ps

    def get(self, f: str) -> str:
        return self.v.get(f, "")

    def fate(self, f: str) -> str:
        return {"pass1": "deterministic (Pass 1 / 1.5)", "call2": "AI gap fill (call 2)",
                "owned_blank": "an owned blank"}.get(self.fates.get(f, ""), "unknown pass")

    def is_btn(self, f: str) -> bool:
        return (self.schema.get(f) or {}).get("ft") == "/Btn"

    def narrative(self, f: str) -> bool:
        meta = self.schema.get(f) or {}
        return (meta.get("ft") == "/Tx"
                and str(meta.get("tu") or "").strip().lower().startswith("enter text")
                and bool(re.search(r"Description|Explanation|RemarkText|Operations|"
                                   r"Relationship", f)))

    def current_policies(self) -> Dict[str, set]:
        """Carriers / policy numbers / premiums of the CURRENT or PRIOR policies:
        from the prior-carrier grid as stamped, and from the extracted lines."""
        out = {"carrier": set(), "policy": set(), "premium": set(), "effective": set()}
        for f, val in self.v.items():
            if not f.startswith("PriorCoverage_") or not filled(val):
                continue
            for k, pat in (("carrier", "InsurerFullName"), ("policy", "PolicyNumberIdentifier"),
                           ("premium", "TotalPremiumAmount"), ("effective", "EffectiveDate")):
                if pat in f:
                    out[k].add(val)
        # Key names from the extraction schema: `coverage_lines` (policy_number,
        # effective_date), `prior_coverage_by_line` (policy_no, effective) and
        # the retired-predecessor list `prior_coverage_lines`.
        for key in ("coverage_lines", "prior_coverage_by_line", "prior_coverage_lines"):
            rows = self.facts.get(key)
            if isinstance(rows, dict):
                rows = rows.get("value")
            for row in rows or []:
                if not isinstance(row, dict):
                    continue
                # An EXISTING policy has a number. A line the cover letter only
                # requests has none - and its carrier is the RECEIVING one.
                if not (row.get("policy_number") or row.get("policy_no")):
                    continue
                for k, v in row.items():
                    if not v or isinstance(v, (list, dict)):
                        continue
                    k = k.lower()
                    if k == "carrier":
                        out["carrier"].add(str(v))
                    elif k in ("policy_number", "policy_no"):
                        out["policy"].add(str(v))
                    elif k == "premium":
                        out["premium"].add(str(v))
                    elif k in ("effective_date", "effective"):
                        out["effective"].add(str(v))
        tp = self.facts.get("total_policy_premium")
        tp = tp.get("value") if isinstance(tp, dict) else tp
        if tp:
            out["premium"].add(str(tp))
        return out

    def question_blocks(self) -> Dict[str, Tuple[str, ...]]:
        """question -> the boxes that answer "tell us more". The product's own
        dependent blocks and explanation pairs, plus the ACORD 125 blocks that
        sit in other sections of the form."""
        ps = self.ps
        blocks: Dict[str, List[str]] = {}
        for qf, deps in dict(ps._NONADJACENT_DEPENDENT_FIELDS).items():
            if qf in self.schema:
                blocks.setdefault(qf, []).extend(deps)
        for qf, deps in ps._question_dependent_block(self.schema).items():
            blocks.setdefault(qf, []).extend(deps)
        for qf, expl in ps._question_explanation_pairs(self.schema).items():
            if "_Question_" in qf:
                blocks.setdefault(qf, []).append(expl)
        for code, deps in _FAR_BLOCKS.items():
            blocks.setdefault(q(code), []).extend(deps)
        return {k: tuple(dict.fromkeys(v)) for k, v in blocks.items()}


# The ACORD 125 blocks a question owns that sit in ANOTHER section of the form,
# so no layout rule can find them. Field names read from the schema.
_FAR_BLOCKS = {
    "AAI": ("BusinessInformation_ParentOrganizationName_A",
            "Subsidiary_ParentSubsidiaryRelationshipDescription_A",
            "Subsidiary_ParentOwnershipPercent_A"),
    "AAJ": ("Subsidiary_OrganizationName_A",
            "Subsidiary_ParentSubsidiaryRelationshipDescription_B",
            "Subsidiary_ParentOwnershipPercent_B"),
    "AAH": tuple(f"OtherPolicy_{k}_{r}" for r in "ABCD"
                 for k in ("LineOfBusinessCode", "PolicyNumberIdentifier")),
    # Question 11's NAME OF TRUST. ACORD reuses an interest field for it and
    # says so in the tooltip ("As used here, this is the name of the trust").
    "ABB": ("AdditionalInterest_FullName_B",),
    "KAA": ("CommercialPolicy_FormalSafetyProgram_SafetyManualIndicator_A",
            "CommercialPolicy_FormalSafetyProgram_SafetyPositionIndicator_B",
            "CommercialPolicy_FormalSafetyProgram_MonthlyMeetingsIndicator_B",
            "CommercialPolicy_FormalSafetyProgram_OSHAIndicator_B",
            "CommercialPolicy_FormalSafetyProgram_OtherIndicator_B",
            "CommercialPolicy_FormalSafetyProgram_OtherDescription_B"),
}


# ═════════════════════════════════════════════════════════════════════════════
# Rules
# ═════════════════════════════════════════════════════════════════════════════
RULES: List[Tuple[str, str, str, Callable]] = []


def rule(rid: str, source: str, title: str):
    def deco(fn):
        RULES.append((rid, source, title, fn))
        return fn
    return deco


def R(applies: bool, fail=(), review=(), note: str = "") -> dict:
    return {"applies": applies, "fail": list(fail), "review": list(review), "note": note}


CLIENT = "client 8-19-26"
STANDING = "standing contract"


@rule("C1", CLIENT, "Status is QUOTE, and only QUOTE")
def _status(c: Ctx):
    boxes = [f for f in c.schema if f.startswith("Policy_Status_")
             and f.endswith("Indicator_A") and "EffectiveTime" not in f]
    on = [f for f in boxes if ticked(c.get(f))]
    fail = [(f, c.get(f), "a status other than QUOTE is ticked") for f in on
            if f != "Policy_Status_QuoteIndicator_A"]
    if "Policy_Status_QuoteIndicator_A" not in on:
        fail.append(("Policy_Status_QuoteIndicator_A", "", "QUOTE is not ticked"))
    return R(True, fail)


def _renews_programme(c) -> bool:
    """The merge's verdict that this upload renews the current programme
    (extraction_service._renews_current_programme). Absent -> False."""
    return (c.facts or {}).get("renews_current_programme") is True


@rule("C2", CLIENT, "Page-one carrier is the carrier RECEIVING the submission")
def _carrier(c: Ctx):
    ins = c.get("Insurer_FullName_A")
    cur = c.current_policies()["carrier"]
    if not filled(ins) or not cur:
        return R(False, note="no page-one carrier, or no current carrier to confuse it with")
    if ticked(c.get("Policy_Status_RenewIndicator_A")):
        return R(False, note="a renewal may name the current carrier")
    hit = [x for x in cur if same(x, ins)]
    if not hit:
        return R(True)
    row = ("Insurer_FullName_A", ins, f"is the CURRENT carrier ({hit[0]})")
    # A declarations upload that renews its programme prints the one company
    # that writes it (29 Sep 2026, Orbin items 7 / 8): the merge records the
    # verdict as `renews_current_programme`.
    if _renews_programme(c):
        return R(True)
    # A one-carrier renewal legitimately prints the incumbent (CLAUDE.md, "ACORD
    # 125 Page 1"). Without facts the audit cannot tell, so it asks instead.
    renewal = c.facts.get("is_renewal")
    renewal = renewal.get("value") if isinstance(renewal, dict) else renewal
    if not c.facts or str(renewal).strip().lower() in ("true", "yes", "y", "1"):
        return R(True, review=[(*row[:2], row[2] + " - right only if this is a "
                                "renewal with the incumbent")])
    return R(True, [row])


@rule("C3", CLIENT, "NAIC only if verified for THAT carrier")
def _naic(c: Ctx):
    naic, ins = c.get("Insurer_NAICCode_A"), c.get("Insurer_FullName_A")
    if not filled(naic):
        return R(False, note="NAIC box blank")
    if not c.has_text:
        return R(True, review=[("Insurer_NAICCode_A", naic, "no document text to verify")])
    digits = re.sub(r"\D", "", naic)
    spots = [m.start() for m in re.finditer(rf"(?<!\d){digits}(?!\d)", c.hay.raw)]
    if not spots:
        return R(True, [("Insurer_NAICCode_A", naic, "printed nowhere in the documents")])
    # The NAIC belongs to the NEAREST carrier name, not to any carrier within
    # reach: "TO: <receiving carrier>" two lines above "Company: <current
    # carrier>  NAIC 27413" put both names in a 300-character window.
    low = c.hay.raw.lower()
    carriers = [ins] + [x for x in c.current_policies()["carrier"] if not same(x, ins)]
    where = {}
    for name in carriers:
        k = norm(name)[:18]
        if k and filled(name):
            where[name] = [m.start() for m in re.finditer(re.escape(k), low)]
    owners = set()
    for sp in spots:
        best = min(((abs(p - sp), n) for n, ps in where.items() for p in ps),
                   default=(None, None))
        if best[1] is not None and best[0] <= 400:
            owners.add(best[1])
    if ins in owners:
        return R(True)
    if owners:
        return R(True, [("Insurer_NAICCode_A", naic,
                         f"it is {sorted(owners)[0]}'s NAIC, not {ins}'s")])
    return R(True, review=[("Insurer_NAICCode_A", naic,
                            "printed, but beside no carrier name - cannot verify")])


@rule("C4", CLIENT, "Policy number blank on a new-business quote")
def _policy_no(c: Ctx):
    pn = c.get("Policy_PolicyNumberIdentifier_A")
    if not ticked(c.get("Policy_Status_QuoteIndicator_A")) or not filled(pn):
        return R(ticked(c.get("Policy_Status_QuoteIndicator_A")))
    cur = c.current_policies()["policy"]
    if any(same(x, pn) for x in cur):
        return R(True, [("Policy_PolicyNumberIdentifier_A", pn,
                         "an EXISTING policy's number on a quote")])
    return R(True, review=[("Policy_PolicyNumberIdentifier_A", pn,
                            "a quote normally has no number - confirm it applies")])


_PREMIUM_BOXES = ("Policy_Payment_EstimatedTotalAmount_A", "Policy_Payment_DepositAmount_A",
                  "Policy_Payment_MinimumPremiumAmount_A",
                  "GeneralLiabilityLineOfBusiness_TotalPremiumAmount_A")


@rule("C5", CLIENT, "Premium blank at submission stage unless known")
def _premium(c: Ctx):
    if not ticked(c.get("Policy_Status_QuoteIndicator_A")):
        return R(False, note="not a quote")
    if _renews_programme(c):
        # 29 Sep 2026 (Orbin items 7 / 8): a declarations upload that renews its
        # programme prints the dec's premiums as the renewal's - known, not a
        # current figure leaking onto a quote.
        return R(True)
    boxes = list(_PREMIUM_BOXES) + [f for f in c.schema
                                    if f.endswith("LineOfBusiness_PremiumAmount_A")]
    cur = c.current_policies()["premium"]
    fail, review = [], []
    for f in boxes:
        val = c.get(f)
        if not filled(val):
            continue
        if any(same(x, val) for x in cur):
            fail.append((f, val, "the CURRENT policy's premium on a quote"))
        else:
            review.append((f, val, "a premium on a quote - is it genuinely known?"))
    return R(True, fail, review)


@rule("C6", CLIENT, "Proposed dates are the NEXT term, not the current one")
def _term(c: Ctx):
    eff, exp = c.get("Policy_EffectiveDate_A"), c.get("Policy_ExpirationDate_A")
    if not filled(eff):
        return R(False, note="no proposed effective date")
    fail = []
    cur = c.current_policies()["effective"]
    if any(same(x, eff) for x in cur):
        fail.append(("Policy_EffectiveDate_A", eff, "is the CURRENT term's start"))
    de, dx = as_date(eff), as_date(exp)
    if de and dx and dx <= de:
        fail.append(("Policy_ExpirationDate_A", exp, "is not after the effective date"))
    return R(True, fail)


@rule("C7", CLIENT, "Prior carrier: only what the documents substantiate")
def _prior(c: Ctx):
    cells = [(f, v) for f, v in c.v.items() if f.startswith("PriorCoverage_") and filled(v)
             and "PolicyYear" not in f]
    if not cells:
        return R(False, note="prior-carrier grid empty")
    fail, review = [], []
    for f, v in cells:
        ok, why = c.hay.grounded(v)
        if ok is False:
            fail.append((f, v, f"not in the documents ({why}); written by {c.fate(f)}"))
    for r in "ABC":
        yr = c.get(f"PriorCoverage_PolicyYear_{r}")
        if filled(yr) and not any(f.endswith(f"_{r}") for f, _v in cells):
            review.append((f"PriorCoverage_PolicyYear_{r}", yr,
                           "a policy year with no carrier history beside it"))
    return R(True, fail, review)


def _loss_rows(c: Ctx) -> List[str]:
    return [r for r in "ABC" if any(filled(c.get(f"LossHistory_{k}_{r}")) for k in
            ("OccurrenceDate", "OccurrenceDescription", "PaidAmount", "ReservedAmount"))]


@rule("C8", CLIENT, "'No known losses' is never converted into loss history")
def _no_losses(c: Ctx):
    nl = ticked(c.get("LossHistory_NoPriorLossesIndicator_A"))
    rows = _loss_rows(c)
    summary = [f for f in ("LossHistory_TotalAmount_A", "LossHistory_InformationYearCount_A")
               if filled(c.get(f))]
    if not nl and not rows and summary:
        # The Orbin run, 28 Sep: "FOR THE LAST 5 YEARS / TOTAL LOSSES $0" off a
        # narrative's "no losses in the past 5 years", with "none" unticked. A
        # loss summary with no rows and no attestation IS a converted narrative
        # (client 8-19-26: "should not convert a narrative phrase such as 'no
        # known losses' into a verified five-year loss history").
        return R(True, [(f, c.get(f), "a loss summary with no loss rows and no "
                         "'none' attestation - a narrative converted into verified "
                         f"history; written by {c.fate(f)}") for f in summary])
    if not nl and not rows:
        return R(False, note="neither losses nor 'no losses' stated")
    fail = []
    if nl and rows:
        fail.append(("LossHistory_NoPriorLossesIndicator_A", "ticked",
                     f"'no prior losses' AND loss rows {rows}"))
    tot = c.get("LossHistory_TotalAmount_A")
    if nl and filled(tot) and _numbers(tot) - {"0"}:
        fail.append(("LossHistory_TotalAmount_A", tot, "a loss total beside 'no losses'"))
    return R(True, fail)


@rule("C9", CLIENT, "Loss total is the PAID amount of the losses (ACORD tooltip)")
def _loss_total(c: Ctx):
    rows, tot = _loss_rows(c), c.get("LossHistory_TotalAmount_A")
    if not rows or not filled(tot):
        return R(False, note="no loss rows, or no total")

    def amt(v):
        n = re.sub(r"[^\d.]", "", str(v))
        return float(n) if n else 0.0
    paid = sum(amt(c.get(f"LossHistory_PaidAmount_{r}")) for r in rows)
    res = sum(amt(c.get(f"LossHistory_ReservedAmount_{r}")) for r in rows)
    overflow = c.ps._LOSS_OVERFLOW_MARKER.lower() in c.get("CommercialPolicy_RemarkText_A").lower()
    t = amt(tot)
    if overflow:
        return R(True, [] if t >= paid else [("LossHistory_TotalAmount_A", tot,
                 f"smaller than the paid shown ({paid:,.0f}) although losses overflowed")])
    if abs(t - paid) < 0.5:
        return R(True)
    why = (f"equals paid + reserved ({paid + res:,.0f}) - that is INCURRED"
           if abs(t - (paid + res)) < 0.5 else f"paid on the rows is {paid:,.0f}")
    return R(True, [("LossHistory_TotalAmount_A", tot, why)])


@rule("C10", CLIENT, "Blank is not No - unanswered questions stay UNRESOLVED")
def _unresolved(c: Ctx):
    qs = [f for f in c.schema if f.startswith("CommercialPolicy_Question_") and f.endswith("Code_A")]
    blank_qs = [f for f in qs if not filled(c.get(f))]
    stray = [(f, c.get(f), "a Yes/No box holding something that is not Y or N")
             for f in qs if filled(c.get(f)) and plain(c.get(f)) not in ("y", "n", "yes", "no")]
    return R(True, stray, [(f, "", "UNRESOLVED - ask the client") for f in blank_qs],
             note=f"{len(qs) - len(blank_qs)} of {len(qs)} questions answered")


@rule("C11", CLIENT, "A Yes carries its explanation / detail")
def _yes_detail(c: Ctx):
    blocks = c.question_blocks()
    yes = [qf for qf in blocks if plain(c.get(qf)) in ("y", "yes")]
    if not yes:
        return R(False, note="no question answered Yes")
    fail = [(qf, "Y", f"Yes with every detail box empty ({len(blocks[qf])} boxes)")
            for qf in yes if not any(filled(c.get(d)) for d in blocks[qf])]
    return R(True, fail)


@rule("C12", CLIENT, "A No (or blank) leaves its whole block empty")
def _no_block(c: Ctx):
    blocks = c.question_blocks()
    notyes = [qf for qf in blocks if plain(c.get(qf)) not in ("y", "yes")]
    fail = []
    for qf in notyes:
        for d in blocks[qf]:
            if filled(c.get(d)):
                fail.append((d, c.get(d), f"filled while {qf.split('_')[2]} is "
                                          f"{c.get(qf) or 'blank'}"))
    return R(bool(notyes), fail)


@rule("C13", CLIENT, "Other named insureds only if the documents support them")
def _other_insureds(c: Ctx):
    rows = [(r, c.get(f"NamedInsured_FullName_{r}")) for r in "BC"
            if filled(c.get(f"NamedInsured_FullName_{r}"))]
    if not rows:
        return R(False, note="rows B and C empty")
    others = [c.get("NamedInsured_FullName_A"), c.get("Insurer_FullName_A"),
              c.get("Producer_FullName_A")] + list(c.current_policies()["carrier"]) + \
             [c.get(f"AdditionalInterest_FullName_{r}") for r in "AB"]
    fail, review = [], []
    for r, name in rows:
        f = f"NamedInsured_FullName_{r}"
        hit = [o for o in others if filled(o) and same(o, name)]
        if hit:
            fail.append((f, name, f"is another party on this form ({hit[0]})"))
            continue
        ok, why = c.hay.grounded(name)
        if ok is False:
            fail.append((f, name, f"not in the documents ({why})"))
            continue
        if not _stated_in_role(c.hay.raw, name, _INSURED_ROLE):
            fail.append((f, name, "printed, but never stated to be an insured "
                                  "(a landlord, a customer, a certificate holder?)"))
    return R(True, fail, review)


_NEGATION = re.compile(r"\b(no|not|none|never|neither|nor|without)\b|n't\b")


def _lines(raw: str) -> List[str]:
    """Printed lines, with a sentence wrapped over two lines joined back into
    one: "It does not" / "require the landlord to be named as an additional
    insured" must keep its negation. A line that ends mid-sentence joins the
    next when that one starts in lower case - read on the ORIGINAL text, where
    case still means something."""
    merged: List[str] = []
    for ln in raw.split("\n"):
        if merged and merged[-1] and not re.search(r"[.;:!?]\s*$", merged[-1]) \
                and re.match(r"\s*[a-z]", ln):
            merged[-1] += " " + ln
        else:
            merged.append(ln)
    return merged


def _affirms(line: str, words) -> bool:
    low = line.lower()
    return any(w in low for w in words) and not _NEGATION.search(low)


_LABEL_WITH_VALUE = re.compile(r":\s*\S")
_RECORD_START = re.compile(r"^\s*(name|full legal name|interest \d+|entity \d+|"
                           r"insured \d+)\b", re.I)


def _stated_in_role(raw: str, name: str, words, reach: int = 8) -> bool:
    """Does the document STATE `name` in one of these roles?

    Structural, because a character radius cannot tell whose role a word is:
      * SAME LINE     "Named insured: X" - the role is X's, and only X's
      * HEADING ABOVE "SCHEDULE OF NAMED INSUREDS" covers the rows under it,
                      until another party's "label: value" line intervenes
      * RECORD BELOW  "Name X" / "Type of interest Mortgagee" - the role
                      belongs to the record, until the next record starts
    A line carrying a negation never states a role ("No holder is an
    additional insured, loss payee or other interest").
    """
    key = norm(name)[:18]
    if not key:
        return False
    lines = _lines(raw)
    for i, line in enumerate(lines):
        if key not in norm(line):
            continue
        if _affirms(line, words):
            return True
        # "Landlord: X" - the document gives X a DIFFERENT role on X's own line
        own = re.match(r"\s*([A-Za-z][A-Za-z /()&-]{1,40}?)\s*(?:\.{2,}|:)\s*\S", line)
        if own and not any(w in own.group(1).lower() for w in words):
            continue
        for j in range(i - 1, max(-1, i - reach - 1), -1):
            above = lines[j]
            if not above.strip():
                break                      # a blank line ends the heading's block
            if _affirms(above, words):
                if _LABEL_WITH_VALUE.search(above):
                    break                  # "Named insured: Y" owns Y, not us
                return True
            if _LABEL_WITH_VALUE.search(above) and any(w in above.lower() for w in words):
                break
        for j in range(i + 1, min(len(lines), i + reach + 1)):
            below = lines[j]
            if _RECORD_START.match(below):
                break                      # the next record has started
            if _affirms(below, words):
                return True
    return False


# A ROLE is a label, not an adjective: "Named Insured:" states one, "insured
# vehicle rear-ended a third party" does not.
_INSURED_ROLE = ("named insured", "additional insured", "insured:", "insureds",
                 "also insured", "other insured")


_INTEREST_WORDS = ("mortgagee", "loss payee", "lienholder", "lien holder",
                   "additional insured", "lender", "lessor", "loss payable",
                   "additional interest", "trustee")


@rule("C14", CLIENT, "Additional interest only if actually documented as one")
def _interests(c: Ctx):
    # A box whose own tooltip makes it question 11's NAME OF TRUST is not an
    # interest - C12 judges it as that question's block, S4 its grounding.
    names = [(f"AdditionalInterest_FullName_{r}", c.get(f"AdditionalInterest_FullName_{r}"))
             for r in "AB" if filled(c.get(f"AdditionalInterest_FullName_{r}"))
             and "name of the trust" not in str(
                 (c.schema.get(f"AdditionalInterest_FullName_{r}") or {}).get("tu") or "").lower()]
    if not names:
        return R(False, note="no additional interest stamped")
    fail, review = [], []
    for f, name in names:
        ok, why = c.hay.grounded(name)
        if ok is False:
            fail.append((f, name, f"not in the documents ({why})"))
            continue
        if not _stated_in_role(c.hay.raw, name, _INTEREST_WORDS):
            fail.append((f, name, "printed, but never AS a mortgagee / payee / lienholder "
                                  "/ additional insured (a certificate holder or landlord?)"))
    return R(True, fail, review)


@rule("C15", CLIENT, "Form edition is the current one (2025/03)")
def _edition(c: Ctx):
    ed = c.get("Form_EditionIdentifier_A")
    if not filled(ed):
        return R(True, review=[("Form_EditionIdentifier_A", "", "edition not printed on the form")])
    return R(True, [] if "2025/03" in ed else [("Form_EditionIdentifier_A", ed,
                                                 "not the 2025/03 edition")])


@rule("C16", CLIENT, "Every Yes / No answer has its own sentence in the documents")
def _answers_grounded(c: Ctx):
    """The historical #1 defect class: a question the document is silent on,
    answered anyway (the 'false N flood', and a Yes borrowed from another
    subject). Extraction v22 records each answer WITH the sentence that states
    it (`disclosure_answers[].evidence_quote`), so a stamped answer can be
    traced to a sentence without an answer key.

    Needs a session dump - a bare PDF carries no facts, and the rule then says
    so instead of passing."""
    rows = c.facts.get("disclosure_answers")
    if not isinstance(rows, list):
        return R(False, note="no disclosure_answers in the facts - either a bare PDF, "
                             "or extraction recorded no statements for this package")
    items = tuple((k, str((v or {}).get("tu") or "")) for k, v in c.schema.items())
    topic_of = {f: t for f, (t, role) in c.ps._disclosure_field_map(items).items()
                if role == "answer"}
    by_topic = {str(r.get("topic")): r for r in rows if isinstance(r, dict)}
    fail, review = [], []
    for f, topic in topic_of.items():
        got = plain(c.get(f))
        if got not in ("y", "n", "yes", "no"):
            continue
        row = by_topic.get(topic)
        if topic == "other_insurance_with_carrier" and any(
                filled(c.get(f"OtherPolicy_PolicyNumberIdentifier_{r}")) for r in "ABCD"):
            continue       # Q4 is answered by its own policy list (owner, 24 Sep)
        # Q1a / Q1b follow the relationship the form prints beside them
        # (28 Sep): a YES whose parent / subsidiary block is filled from the
        # document's relationship is answered by that block - C12 and S4 judge
        # the block itself.
        if got.startswith("y") and topic in ("subsidiary_of_another", "has_subsidiaries"):
            _block = ("BusinessInformation_ParentOrganizationName_A"
                      if topic == "subsidiary_of_another" else "Subsidiary_OrganizationName_A")
            if filled(c.get(_block)):
                continue
        if not row or plain(row.get("answer")) not in ("y", "n"):
            (fail if c.fates.get(f) != "call2" else review).append(
                (f, c.get(f), "answered, but extraction found NO statement on this "
                              "topic" + (" - the AI gap fill answered it; check its quote"
                                         if c.fates.get(f) == "call2" else "")))
            continue
        if plain(row["answer"])[0] != got[0]:
            fail.append((f, c.get(f), f"the documents say {row['answer']}"))
            continue
        quote = str(row.get("evidence_quote") or "")
        if c.has_text and quote and c.hay.grounded(quote, narrative=True)[0] is False:
            fail.append((f, c.get(f), f"its evidence is not in the documents: {quote[:70]!r}"))
    return R(True, fail, review)


@rule("C17", CLIENT, "An ATTACHMENTS tick names a form this package contains")
def _attachments(c: Ctx):
    """ACORD 125's ATTACHMENTS block lists what accompanies THIS application.
    The Orbin run of 28 Sep generated ACORD 125 alone and ticked CONTRACTORS
    SUPPLEMENT (= ACORD 186), because generation read the RECOMMENDED forms as
    the package. The box-to-form map is the product's own."""
    if not c.package:
        return R(False, note="the dump does not say which forms were generated")
    fail = []
    for base, form in c.ps._ATTACHMENT_FROM_FORM.items():
        f = f"{base}_A"
        if ticked(c.get(f)) and form not in c.package:
            fail.append((f, c.get(f), f"{form} is not in this package {c.package}"))
    return R(True, fail)


@rule("S1", STANDING, "No placeholder ever reaches a box ('N/A', '--', 'none', 'TBD')")
def _placeholders(c: Ctx):
    from services.answer_semantics import is_placeholder_text
    fail = [(f, v, "a placeholder printed as a value") for f, v in c.v.items()
            if filled(v) and not c.is_btn(f) and is_placeholder_text(v)]
    return R(True, fail)


@rule("S2", STANDING, "Authorship: nothing signs or attests for a person")
def _authorship(c: Ctx):
    boxes = [f for f in c.schema if re.search(r"Signature|_Initials_|InformationPracticesNotice", f)]
    return R(True, [(f, c.get(f), "a machine signed / attested") for f in boxes if filled(c.get(f))])


_SHAPES = [(r"_TaxIdentifier_", r"^\d{2}-?\d{7}$", "a FEIN is nine digits"),
           (r"_NAICSCode_", r"^\d{6}$", "NAICS is six digits"),
           (r"_SICCode_", r"^\d{4}$", "SIC is four digits"),
           (r"_PostalCode_", r"^\d{5}(-\d{4})?$", "a US ZIP"),
           (r"StateOrProvinceCode", r"^[A-Za-z]{2}$", "two letters")]


@rule("S3", STANDING, "Every code box holds the shape its ACORD tooltip declares")
def _shapes(c: Ctx):
    fail = []
    for f, v in c.v.items():
        if not filled(v) or c.is_btn(f):
            continue
        for pat, rx, why in _SHAPES:
            if re.search(pat, f) and not re.match(rx, v.strip()):
                fail.append((f, v, why))
        table = SFF.tooltip_codes(FORM, f)
        if table and plain(v) not in table and plain(v) not in table.values():
            fail.append((f, v, f"ACORD's codes are {sorted(table)}"))
    return R(True, fail)


# Boxes whose value is DERIVED or comes from the account by design, never from
# the upload - grounding them in the document text would be the wrong test.
_DERIVED = re.compile(r"^(Form_|Producer_|PriorCoverage_PolicyYear_|"
                      r"LossHistory_InformationYearCount_|LossHistory_TotalAmount_|"
                      r"CommercialStructure_(Location|Building)_ProducerIdentifier_)")


@rule("S4", STANDING, "Every printed value is found in the documents (made-up detector)")
def _grounding(c: Ctx):
    if not c.has_text:
        return R(False, note="the dump carries no document text")
    fail, review = [], []
    marker = c.ps._LOSS_OVERFLOW_MARKER
    for f, v in sorted(c.v.items()):
        if not filled(v) or c.is_btn(f) or _DERIVED.match(f):
            continue
        val = v.split(marker)[0] if marker in v else v
        ok, why = c.hay.grounded(val, narrative=c.narrative(f))
        if ok is False:
            (fail if c.fates.get(f) == "call2" or not c.fates else review).append(
                (f, v, f"{why}; written by {c.fate(f)}"))
    return R(True, fail, review,
             note="FAIL = the AI gap fill wrote it; REVIEW = a deterministic pass wrote "
                  "it (usually a reformat or an extraction value)")


@rule("S5", STANDING, "No entity printed twice in one table")
def _dupes(c: Ctx):
    fail = []
    groups = {
        "loss": [(r, (norm(c.get(f"LossHistory_OccurrenceDate_{r}")),
                      norm(c.get(f"LossHistory_OccurrenceDescription_{r}"))[:40])) for r in "ABC"],
        "premises": [(r, norm(c.get(f"CommercialStructure_PhysicalAddress_LineOne_{r}")))
                     for r in "ABCD"],
        "named insured": [(r, norm(c.get(f"NamedInsured_FullName_{r}"))) for r in "ABC"],
    }
    applies = False
    for name, rows in groups.items():
        seen: Dict = {}
        for r, k in rows:
            if not k or k == ("", ""):
                continue
            applies = True
            if k in seen:
                fail.append((f"{name} row {r}", str(k), f"repeats row {seen[k]}"))
            seen.setdefault(k, r)
    return R(applies, fail)


@rule("S6", STANDING, "Premises areas add up: public <= occupied <= building")
def _areas(c: Ctx):
    def n(v):
        d = re.sub(r"[^\d.]", "", str(v))
        return float(d) if d else None
    fail, applies = [], False
    for r in "ABCD":
        occ = n(c.get(f"BuildingOccupancy_OccupiedArea_{r}"))
        pub = n(c.get(f"BuildingOccupancy_OpenToPublicArea_{r}"))
        tot = n(c.get(f"Construction_BuildingArea_{r}"))
        if occ is None:
            continue
        applies = True
        if pub is not None and pub > occ:
            fail.append((f"BuildingOccupancy_OpenToPublicArea_{r}", pub, "larger than occupied"))
        if tot is not None and occ > tot:
            fail.append((f"BuildingOccupancy_OccupiedArea_{r}", occ, "larger than the building"))
    return R(applies, fail)


@rule("S7", STANDING, "Dates are possible")
def _dates(c: Ctx):
    today = date.today()
    fail = []
    bs = as_date(c.get("NamedInsured_BusinessStartDate_A"))
    if bs and bs > today:
        fail.append(("NamedInsured_BusinessStartDate_A", str(bs), "in the future"))
    for r in "ABC":
        d = as_date(c.get(f"LossHistory_OccurrenceDate_{r}"))
        if d and d > today:
            fail.append((f"LossHistory_OccurrenceDate_{r}", str(d), "a loss in the future"))
        cd = as_date(c.get(f"LossHistory_ClaimDate_{r}"))
        if d and cd and cd < d:
            fail.append((f"LossHistory_ClaimDate_{r}", str(cd), "claimed before it occurred"))
    return R(True, fail)


# ═════════════════════════════════════════════════════════════════════════════
def audit(stamped: dict, facts: dict, raw: str, fates: dict,
          package: Optional[List[str]] = None) -> List[dict]:
    c = Ctx(stamped, facts, raw, fates, package)
    out = []
    for rid, source, title, fn in RULES:
        try:
            res = fn(c)
        except Exception as exc:                               # noqa: BLE001
            res = R(True, [("(rule crashed)", "", f"{type(exc).__name__}: {exc}")])
        status = ("NOT EXERCISED" if not res["applies"] else
                  "FAIL" if res["fail"] else "REVIEW" if res["review"] else "PASS")
        out.append({"id": rid, "source": source, "title": title, "status": status, **res})
    return out


def print_report(results: List[dict], max_rows: int = 12) -> None:
    w = 78
    print("=" * w)
    print("  ACORD 125 RULES AUDIT  (no answer key - the form against the documents)")
    print("=" * w)
    for r in results:
        extra = f"  [{len(r['fail'])} fail]" if r["fail"] else \
                f"  [{len(r['review'])} to review]" if r["review"] else ""
        print(f"  {r['id']:<4} {r['status']:<14} {r['title']}{extra}")
        if r.get("note") and r["status"] != "PASS":
            print(f"       {'':<14} ({r['note']})")
    counts = {s: sum(1 for r in results if r["status"] == s)
              for s in ("PASS", "FAIL", "REVIEW", "NOT EXERCISED")}
    print("-" * w)
    print(f"  {len(results)} rules: {counts['PASS']} pass, {counts['FAIL']} fail, "
          f"{counts['REVIEW']} to review, {counts['NOT EXERCISED']} not exercised "
          f"by this package")
    for r in results:
        for kind in ("fail", "review"):
            rows = r[kind]
            if not rows or (kind == "review" and r["id"] == "C10"):
                continue
            print(f"\n  {r['id']} {kind.upper()} ({len(rows)}) - {r['title']}")
            for f, v, why in rows[:max_rows]:
                print(f"    {f}")
                if str(v).strip():
                    print(f"      value  {str(v)[:110]!r}")
                print(f"      why    {why}")
            if len(rows) > max_rows:
                print(f"    ... and {len(rows) - max_rows} more")
    unresolved = next((r["review"] for r in results if r["id"] == "C10"), [])
    if unresolved:
        print(f"\n  UNRESOLVED questions ({len(unresolved)}): "
              + ", ".join(f.split("_")[2].replace("Code", "") for f, *_ in unresolved))
    print("=" * w)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("dump", nargs="?", help="JSON written by dump_a125_run.py")
    ap.add_argument("--pdf", help="a filled ACORD 125 PDF, instead of a dump")
    ap.add_argument("--text", help="the uploaded document's text (with --pdf)")
    ap.add_argument("--json-out")
    ap.add_argument("--max-rows", type=int, default=12)
    a = ap.parse_args()
    if a.dump:
        d = json.loads(Path(a.dump).read_text(encoding="utf-8"))
        stamped, facts = d.get("stamped") or {}, {**(d.get("merged_facts") or {}),
                                                 **(d.get("flags") or {})}
        raw, fates = d.get("raw_text") or "", d.get("fates") or {}
        package = d.get("package_form_ids") or []
    elif a.pdf:
        stamped, facts, fates, package = SFF.read_acroform(Path(a.pdf)), {}, {}, []
        raw = Path(a.text).read_text(encoding="utf-8") if a.text else ""
    else:
        ap.error("give a dump, or --pdf")
    results = audit(stamped, facts, raw, fates, package)
    print_report(results, a.max_rows)
    if a.json_out:
        Path(a.json_out).write_text(json.dumps(results, indent=1, default=str), encoding="utf-8")
        print(f"  wrote {a.json_out}")
    return 1 if any(r["status"] == "FAIL" for r in results) else 0


if __name__ == "__main__":
    raise SystemExit(main())
