"""wc_premiums.py - what the Workers Compensation policy's own declarations
STATE about its premium, for ACORD 130 (7 Oct 2026, Choice Electric #7).

Brent: the ACORD 130 printed no premium although the WC information page states
"TOTAL ESTIMATED ANNUAL PREMIUM 29,278.00", "POLICY MINIMUM PREMIUM 465.00" and,
per class, an "Estimated Annual Premium" (37,600.00 / 597.00 / 180.00). Every
130 premium box is non-fillable (a premium is never a question for the gap-fill
model), and nothing owned them, so they were always blank.

THE RULE - transcribe, never compute:
  * TOTAL ESTIMATED ANNUAL PREMIUM (all states) = the WC policy's own premium:
    the ONE workers_comp line record's premium, printed only when the documents
    print that amount (verified here, at merge) or a person typed it.
  * MINIMUM / DEPOSIT PREMIUM = only a figure the documents STATE for the WC
    line: a verified declarations entry tagged with the WC line, or a labelled
    line on the WC policy's OWN declarations (a GL dec prints a minimum
    premium too). One value, else blank.
  * ESTIMATED ANNUAL MANUAL PREMIUM per class = only the class row's OWN stated
    premium. `wc_class_codes` rows carry none (code / rate / state / payroll /
    description / counts), so it is read off the SAME printed classification
    line - the class code, its payroll and its rate on one line, under a
    "premium" heading, the amount after the rate. One value per row, else
    blank. Never payroll x rate.
  * A single-state policy's rating sheet prints the same totals for its one
    state (the sheet's state label is printed under the same rule).
  * ACORD 125's page-one rule decides whether a current policy's premium is
    the submission's (`pdf_service._page_one_current_policy`): when the 125
    withholds the current premiums, so does the 130 - they never disagree.

Derived at merge into the private `_wc_premiums` fact (documents in hand);
read by `pdf_service` at stamping. Pure; never raises.
"""
from __future__ import annotations

import logging
import re
from typing import Any, Dict, List, Optional, Set

logger = logging.getLogger(__name__)

KEY = "_wc_premiums"

_AMOUNT_RE = re.compile(r"(?<![\w.])\$?\s?(\d{1,3}(?:,\d{3})+|\d+)(?:\.(\d{2}))?(?![\d,]*\.\d)(?!\w)")
_MINIMUM_RE = re.compile(r"\bminimum\s+premium\b", re.I)
_DEPOSIT_RE = re.compile(r"\bdeposit\s+premium\b", re.I)
_PREMIUM_HEADING_RE = re.compile(r"\bpremium\b", re.I)
_HEADING_WINDOW = 2500


def _fv(facts: Any, key: str):
    try:
        from services.extraction_service import _fv as _efv
        return _efv(facts or {}, key)
    except Exception:                                         # noqa: BLE001
        v = (facts or {}).get(key) if isinstance(facts, dict) else None
        return v.get("value") if isinstance(v, dict) and "value" in v else v


def _canon(text: Any) -> Optional[str]:
    try:
        from services.lob_canon import canon_line
        return canon_line(text)
    except Exception:                                         # noqa: BLE001
        return None


def dollars_key(value: Any) -> str:
    """Whole dollars as digits: "29,278.00" / "$29,278" / 29278.0 -> "29278";
    "" when the value is not one plain amount."""
    if isinstance(value, bool) or value is None:
        return ""
    if isinstance(value, (int, float)):
        return str(int(round(float(value)))) if float(value) > 0 else ""
    s = str(value).strip()
    m = re.fullmatch(r"\$?\s?(\d{1,3}(?:,\d{3})+|\d+)(?:\.(\d{1,2}))?", s)
    if not m:
        return ""
    whole = int(m.group(1).replace(",", ""))
    cents = int((m.group(2) or "0").ljust(2, "0"))
    total = whole + (1 if cents >= 50 else 0)
    return str(total) if total > 0 else ""


def money(value: Any) -> Optional[str]:
    """One amount as "$29,278" (cents kept when not .00)."""
    if value is None or isinstance(value, bool):
        return None
    try:
        from services.display_canonicalizer import canonicalize_currency
    except Exception:                                         # noqa: BLE001
        return None
    text = f"{float(value):.2f}" if isinstance(value, (int, float)) else str(value).strip()
    out = canonicalize_currency(text)
    return out if out and out.startswith("$") else None


def _rate_key(value: Any) -> str:
    try:
        rate = float(re.sub(r"[^\d.]", "", str(value or "")))
    except ValueError:
        return ""
    return f"{rate:.6g}" if rate > 0 else ""


def _amounts(text: str) -> List[re.Match]:
    return [m for m in _AMOUNT_RE.finditer(text or "")]


def _wc_documents(docs: Any) -> List[dict]:
    """The WC policy's OWN declarations: active documents whose own coverage
    rows name the workers compensation line and no other line (a declarations
    entry tag decides when a document carries no rows)."""
    out: List[dict] = []
    for d in docs if isinstance(docs, list) else []:
        if not isinstance(d, dict) or d.get("excluded"):
            continue
        facts = d.get("facts") or {}
        rows = _fv(facts, "coverage_lines")
        fams = {_canon((r or {}).get("line")) for r in rows if isinstance(r, dict)} \
            if isinstance(rows, list) else set()
        fams.discard(None)
        if not fams:
            entries = _fv(facts, "dec_page_entries")
            fams = {_canon((e or {}).get("line_of_business")) for e in entries
                    if isinstance(e, dict)} if isinstance(entries, list) else set()
            fams.discard(None)
        if fams == {"workers_comp"}:
            out.append(d)
    return out


def _labelled_amounts(label_re: "re.Pattern[str]", texts: List[str]) -> Set[str]:
    """Whole-dollar keys of the ONE amount printed after ``label_re`` on each
    line; a line printing two different amounts after the label says nothing."""
    found: Set[str] = set()
    for text in texts:
        for line in str(text or "").splitlines():
            m = label_re.search(line)
            if not m:
                continue
            keys = {dollars_key(a.group(0).replace(" ", "")) for a in _amounts(line[m.end():])}
            keys.discard("")
            if len(keys) == 1:
                found |= keys
    return found


def _entry_amounts(label_re: "re.Pattern[str]", entries: Any) -> Set[str]:
    found: Set[str] = set()
    for e in entries if isinstance(entries, list) else []:
        if not isinstance(e, dict):
            continue
        if _canon(e.get("line_of_business")) != "workers_comp":
            continue
        if not label_re.search(str(e.get("label") or "")):
            continue
        k = dollars_key(str(e.get("value") or "").strip())
        if k:
            found.add(k)
    return found


def _stated_once(label_re: "re.Pattern[str]", entries: Any, texts: List[str]) -> Optional[str]:
    keys = _entry_amounts(label_re, entries) | _labelled_amounts(label_re, texts)
    if len(keys) != 1:
        if len(keys) > 1:
            logger.info("wc_premiums: %s - %d different amounts stated, none printed",
                        label_re.pattern, len(keys))
        return None
    return money(int(next(iter(keys))))


def _class_line_premium(row: dict, texts: List[str]) -> Optional[str]:
    """The class row's own stated premium: on a line printing its code, its
    payroll and its rate, the ONE amount after the rate, under a "premium"
    heading. Several lines (a table printed twice) must agree."""
    code = re.sub(r"\D", "", str(row.get("code") or ""))
    payroll = dollars_key(str(row.get("payroll") or "").replace(" ", ""))
    rate = _rate_key(row.get("rate"))
    if not code or not payroll or not rate:
        return None
    code_re = re.compile(rf"(?<![\d.,]){re.escape(code)}(?![\d.,])")
    found: Set[str] = set()
    for text in texts:
        text = str(text or "")
        pos = 0
        for line in text.splitlines(keepends=True):
            start = pos
            pos += len(line)
            if not code_re.search(line):
                continue
            amounts = _amounts(line)
            pay_at = next((a for a in amounts
                           if dollars_key(a.group(0).replace(" ", "")) == payroll), None)
            if pay_at is None:
                continue
            rate_at = next((m for m in re.finditer(r"(?<![\d.,])\d+\.\d+(?![\d,])", line)
                            if m.start() >= pay_at.end() and _rate_key(m.group(0)) == rate), None)
            if rate_at is None:
                continue
            after = [a for a in amounts if a.start() >= rate_at.end()]
            keys = {dollars_key(a.group(0).replace(" ", "")) for a in after}
            keys.discard("")
            if len(keys) != 1:
                continue
            if not _PREMIUM_HEADING_RE.search(text[max(0, start - _HEADING_WINDOW):start]):
                continue
            found |= keys
    if len(found) != 1:
        return None
    return money(int(next(iter(found))))


def derive_wc_premiums(mf: Any, docs: Any) -> Optional[dict]:
    """Write ``mf["_wc_premiums"]`` from the documents (or drop it when they
    state nothing). Returns what was stored."""
    if not isinstance(mf, dict):
        return None
    mf.pop(KEY, None)
    try:
        active = [d for d in docs if isinstance(d, dict) and not d.get("excluded")] \
            if isinstance(docs, list) else []
        wc_texts = [str(d.get("text") or "") for d in _wc_documents(active)]
        all_texts = [str(d.get("text") or "") for d in active]
        entries = _fv(mf, "dec_page_entries")
        out: Dict[str, Any] = {}
        minimum = _stated_once(_MINIMUM_RE, entries, wc_texts)
        if minimum:
            out["minimum"] = minimum
        deposit = _stated_once(_DEPOSIT_RE, entries, wc_texts)
        if deposit:
            out["deposit"] = deposit
        # The WC line's own premium(s), as printed in the documents.
        totals: Set[str] = set()
        try:
            from services.pdf_service import _normalize_for_search, _value_in_raw_text
            hay = _normalize_for_search("\n".join(all_texts))
        except Exception:                                     # noqa: BLE001
            hay, _value_in_raw_text = "", None                # type: ignore
        rows = _fv(mf, "coverage_lines")
        for r in rows if isinstance(rows, list) else []:
            if not isinstance(r, dict) or r.get("_producer_added"):
                continue
            if _canon(r.get("line")) != "workers_comp":
                continue
            k = dollars_key(str(r.get("premium") or "").replace(" ", ""))
            if k and hay and _value_in_raw_text and _value_in_raw_text(str(r.get("premium")), hay):
                totals.add(k)
        if totals:
            out["totals"] = sorted(totals)
        classes: List[dict] = []
        wc_rows = _fv(mf, "wc_class_codes")
        for row in wc_rows if isinstance(wc_rows, list) else []:
            if not isinstance(row, dict):
                continue
            prem = _class_line_premium(row, all_texts)
            if prem:
                classes.append({
                    "code": re.sub(r"\D", "", str(row.get("code") or "")),
                    "state": str(row.get("state") or "").strip().upper()[:2],
                    "payroll": dollars_key(str(row.get("payroll") or "").replace(" ", "")),
                    "rate": _rate_key(row.get("rate")),
                    "premium": prem,
                })
        if classes:
            out["classes"] = classes
        if out:
            mf[KEY] = out
            logger.info("wc_premiums: stated WC premiums read - %s",
                        {k: (v if k != "classes" else len(v)) for k, v in out.items()})
            return out
    except Exception as exc:                                  # noqa: BLE001
        logger.warning("wc_premiums: derivation skipped - %s", exc)
    return None


# ── Stamping (pdf_service reads these) ────────────────────────────────────────

def premiums_withheld(facts: Any) -> bool:
    """ACORD 125's page-one premium rule, asked verbatim: the current policy's
    premium is not the submission's (`premium_is_current_policy`, unless a
    person entered a premium)."""
    # A declarations upload that renews its own programme prints the WC policy's
    # premiums on the 130 (Brent's item 7: "WC ($29,278) needs to go on form
    # 130"). Only ACORD 125's PAGE ONE leaves a renewal's expiring premiums out
    # (Brent, 8 Oct 2026), so that flag does not reach this form.
    if isinstance(facts, dict) and facts.get("renews_current_programme") is True:
        return False
    try:
        from services.pdf_service import _page_one_current_policy
        return bool(_page_one_current_policy({**(facts or {}), "_form_id": "ACORD_125"},
                                             "premium_is_current_policy", "total_policy_premium"))
    except Exception:                                         # noqa: BLE001
        return False


def _wc_records(facts: Any) -> List[dict]:
    try:
        from services.extraction_service import policy_line_records
    except Exception:                                         # noqa: BLE001
        return []
    held = (facts or {}).get("_line_records") if isinstance(facts, dict) else None
    return [r for r in policy_line_records(held if isinstance(held, list) else [])
            if r.get("line") == "workers_comp"]


def policy_premium(facts: Any) -> Optional[str]:
    """The WC policy's own premium, or None: exactly one WC policy, a premium
    on it, printed in the documents or stated by a person."""
    if not isinstance(facts, dict):
        return None
    held = facts.get(KEY)
    verified = set((held or {}).get("totals") or []) if isinstance(held, dict) else set()
    recs = _wc_records(facts)
    candidates: List[tuple] = []          # (amount, stated by a person)
    if recs:
        if len(recs) != 1:
            return None
        rec = recs[0]
        amt = rec.get("premium")
        if isinstance(amt, (int, float)) and not isinstance(amt, bool) and amt > 0:
            candidates.append((float(amt), "premium" in (rec.get("producer_fields") or [])
                               or bool(rec.get("producer_added"))))
    else:
        rows = _fv(facts, "coverage_lines")
        keys = set()
        for r in rows if isinstance(rows, list) else []:
            if isinstance(r, dict) and _canon(r.get("line")) == "workers_comp":
                k = dollars_key(str(r.get("premium") or "").replace(" ", ""))
                if k:
                    keys.add(k)
        if len(keys) == 1:
            candidates.append((float(next(iter(keys))), False))
    if len(candidates) != 1:
        return None
    amount, by_person = candidates[0]
    if not by_person and isinstance(held, dict) and dollars_key(amount) not in verified:
        return None                       # printed nowhere in the documents
    return money(amount)


def single_state(facts: Any) -> Optional[str]:
    """The policy's ONE state, from the class rows and the payroll-by-state,
    or None."""
    try:
        from services.coverage_evidence import wc_class_row_states
        states = set(wc_class_row_states(_fv(facts, "wc_class_codes")))
    except Exception:                                         # noqa: BLE001
        states = set()
    by_state = _fv(facts, "wc_payroll_by_state")
    if isinstance(by_state, dict):
        states |= {str(k).strip().upper()[:2] for k in by_state if str(k or "").strip()}
    states.discard("")
    return next(iter(states)) if len(states) == 1 else None


def box_value(kind: str, facts: Any) -> Optional[str]:
    """The value of one ACORD 130 premium box (``kind``: total / minimum /
    deposit, or state_* for the single-state rating sheet), or None."""
    if not isinstance(facts, dict) or premiums_withheld(facts):
        return None
    if kind.startswith("state_"):
        if not single_state(facts):
            return None
        kind = kind[len("state_"):]
    if kind == "total":
        return policy_premium(facts)
    held = facts.get(KEY)
    if not isinstance(held, dict):
        return None
    value = held.get(kind) if kind in ("minimum", "deposit") else None
    return value if isinstance(value, str) and value.strip() else None


def class_row_premium(row: Any, facts: Any) -> Optional[str]:
    """The class row's own stated premium, or None - only when the row still
    reads exactly as the documents print it (code, payroll, rate, state)."""
    if not isinstance(row, dict) or not isinstance(facts, dict) or premiums_withheld(facts):
        return None
    held = facts.get(KEY)
    classes = (held or {}).get("classes") if isinstance(held, dict) else None
    if not isinstance(classes, list) or not classes:
        return None
    code = re.sub(r"\D", "", str(row.get("code") or ""))
    payroll = dollars_key(str(row.get("payroll") or "").replace(" ", ""))
    rate = _rate_key(row.get("rate"))
    state = str(row.get("state") or "").strip().upper()[:2]
    if not code or not payroll or not rate:
        return None
    hits = {c.get("premium") for c in classes if isinstance(c, dict)
            and c.get("code") == code and c.get("payroll") == payroll and c.get("rate") == rate
            and (not state or not c.get("state") or c.get("state") == state)}
    hits.discard(None)
    return next(iter(hits)) if len(hits) == 1 else None
