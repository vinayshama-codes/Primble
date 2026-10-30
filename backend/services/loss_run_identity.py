"""loss_run_identity.py - do the uploaded loss runs belong to THIS insured?

V1 plan C1 F4 (client 1.8). The previous matcher (``sqs_service.
_check_loss_run_insured_match``) was a sixth private comparison site: it
normalised the name and the address, then compared FEIN and policy number as
RAW STRINGS (``"84-2210987" != "842210987"``) and took "the first policy number
from any other document" on a three-policy account. Every row of the client's
1.8 list was a symptom of that. Measured cost per row: 8 to 35 Loss History
points for a formatting difference.

THE RULE: this module decides nothing about sameness itself. Every identifier
goes through ``services.fact_comparison`` - the one door - so the eight
normalisations the client lists (legal-name variations, LLC / L.L.C., case,
punctuation, address formatting, ZIP / ZIP+4, policy-number punctuation and
spacing, carrier-name variations) are the comparator's normalisations and can
never drift from the Data Consistency picker's.

THE TIERS are the client's, verbatim, and nothing else:

    strong      name matches AND (FEIN matches OR policy number matches)
    moderate    name matches AND address matches (containment counts)
    possible    name matches only - or ownership cannot be verified at all
                (a producer's "Yes" to `loss_run_ownership_confirmed` lifts a
                name-matched possible / moderate run to strong, 23 Oct 2026)
    no_match    the insured name on the run is a different entity
    no_loss_run no loss-run document in the package

Two cases the client's spec did not cover were RULED ON by Brent 2026-08-24
(Q3a / Q3b closed - see v1-20AUG.md C2-E):

    DBA match          a name matching a DBA THE APPLICANT DECLARED is a name
                       match; the ordinary tiers then apply (with a tax ID or
                       policy number that is a verified `strong`)
    FEIN, name unknown  `moderate` - "a probable match", plus a note asking the
                       producer to confirm the prior name / entity relationship

Scope (client 1.2): the run's policy number is matched against EVERY policy
number the package evidences - each document's scalar AND every
``coverage_lines`` row - not the first one found. A Business Auto loss run
matches the auto policy on a GL+Auto+Umbrella package.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from services.fact_comparison import (
    build_context, carriers_same_family, feins_match, identifiers_match,
    values_agree,
)

logger = logging.getLogger(__name__)

STRONG = "strong"
MODERATE = "moderate"
POSSIBLE = "possible"
NO_MATCH = "no_match"
NO_LOSS_RUN = "no_loss_run"

_RANK = {STRONG: 4, MODERATE: 3, POSSIBLE: 2, NO_MATCH: 1}

NOTE_DBA = ("Loss run appears to be filed under the insured's trade name (DBA) - "
            "confirm it belongs to this applicant.")
NOTE_FEIN_NAME_DIFFERS = ("Loss run tax ID matches the applicant but the insured name on "
                          "it differs - probable match. Confirm the prior name or the "
                          "entity relationship (name change, merger or affiliate).")
NOTE_NO_NAME = "Loss run does not state an insured name - ownership cannot be verified."
NOTE_CARRIER_DIFFERS = ("Carrier on the loss run does not match any carrier on the "
                        "package - confirm the run is for this account's policies.")


def _fv(facts: Any, key: str) -> Any:
    if not isinstance(facts, dict):
        return None
    raw = facts.get(key)
    if isinstance(raw, dict) and "value" in raw:
        return raw["value"]
    return raw


def _text(v: Any) -> str:
    return str(v).strip() if v is not None else ""


def _rows(value: Any) -> list:
    """A row list as stored, else none (strict review, 29 Oct 2026: a string or
    a dict in `coverage_lines` raised here and took the loss-run verdict with
    it - iterating a dict's keys or a string's letters is no row)."""
    return value if isinstance(value, list) else []


def _package_identity(docs: List[dict], merged_facts: Optional[dict]) -> Dict[str, list]:
    """Every identity value the NON-loss-run documents evidence.

    Loss runs are excluded on purpose: a package whose only FEIN carrier is the
    loss run itself would otherwise self-verify (M3, 2026).
    """
    out: Dict[str, list] = {
        "dba": [], "fein": [], "policy": [], "address": [], "carrier": [],
    }
    sources = [d.get("facts") if isinstance(d.get("facts"), dict) else {}
               for d in (docs if isinstance(docs, list) else [])
               if isinstance(d, dict)
               and not d.get("excluded") and d.get("doc_type") != "loss_run"]
    for f in sources:
        # prior_carrier / wc_prior_carrier belong in the carrier bucket (C2-C,
        # found live 2026-08-24): a loss run is normally ISSUED BY the prior
        # carrier, and the package's own documents name that carrier - flagging
        # it as "not this account's carrier" was a false note on the ordinary
        # renewal shape.
        for key, bucket in (("dba_name", "dba"), ("fein", "fein"),
                            ("policy_number", "policy"), ("carrier_name", "carrier"),
                            ("prior_carrier", "carrier"), ("wc_prior_carrier", "carrier")):
            if isinstance(f.get(key), dict) and f[key].get("echo_of") == "loss_run":
                continue                  # the loss runs' own value printed back on our form (M3)
            v = _text(_fv(f, key))
            if v and v not in out[bucket]:
                out[bucket].append(v)
        for key in ("mailing_address", "physical_address"):
            if isinstance(f.get(key), dict) and f[key].get("echo_of") == "loss_run":
                continue
            v = _text(_fv(f, key))
            if v and v not in out["address"]:
                out["address"].append(v)
        for ln in _rows(_fv(f, "coverage_lines")):
            if isinstance(ln, dict):
                for key, bucket in (("policy_number", "policy"), ("carrier", "carrier")):
                    v = _text(ln.get(key))
                    if v and v not in out[bucket]:
                        out[bucket].append(v)
    # The merged package facts are a second witness for the line-scoped
    # structures (they are repaired upstream from the verified dec entries).
    if isinstance(merged_facts, dict):
        for _pc_key in ("prior_carrier", "wc_prior_carrier"):
            v = _text(_fv(merged_facts, _pc_key))
            if v and v not in out["carrier"]:
                out["carrier"].append(v)
        for ln in _rows(_fv(merged_facts, "coverage_lines")):
            if isinstance(ln, dict):
                for key, bucket in (("policy_number", "policy"), ("carrier", "carrier")):
                    v = _text(ln.get(key))
                    if v and v not in out[bucket]:
                        out[bucket].append(v)
        # The insured's FEIN as a PERSON entered it (24 Oct 2026): a producer's
        # typed FEIN witnesses "this insured's FEIN" as an application printing
        # it does, so complete loss runs that show it match on it. Only a typed
        # value - the merge's FEIN may be the loss run's own (no self-verify).
        # ...or CONFIRMED (live bcfd175b, 25 Oct: confirming 84-1234567 in Data
        # Consistency after forms stored it as `user_confirmed`, and the
        # loss runs printing that very FEIN dropped from strong to possible).
        try:
            from services.fact_state import confirmed_by_person
            v = _text(_fv(merged_facts, "fein"))
            if v and confirmed_by_person(merged_facts.get("fein")) and v not in out["fein"]:
                out["fein"].append(v)
        except Exception:                                       # noqa: BLE001
            pass
    return out


def match_loss_run_identity(
    docs: List[dict],
    applicant_name: Optional[str],
    merged_facts: Optional[dict] = None,
) -> dict:
    """Full, explainable verdict. ``tier`` is the client's tier string; the
    rest is provenance for the review screen and the audit record.

    Returns::

        {"tier": str, "matched_on": [...], "failed_on": [...], "notes": [...],
         "per_document": [{"filename", "tier", "matched_on", "failed_on",
                            "notes"}, ...]}
    """
    loss_docs = [d for d in (docs or [])
                 if d.get("doc_type") == "loss_run" and not d.get("excluded")]
    if not loss_docs:
        return {"tier": NO_LOSS_RUN, "matched_on": [], "failed_on": [],
                "notes": [], "per_document": []}

    applicant = _text(applicant_name)
    if not applicant:
        # Loss runs exist but the package has no applicant name to verify
        # against - never full credit (today's behaviour, kept).
        return {"tier": POSSIBLE, "matched_on": [], "failed_on": ["name"],
                "notes": ["Applicant name unknown - loss-run ownership cannot be verified."],
                "per_document": []}

    ctx = build_context(merged_facts, docs)
    pkg = _package_identity(docs, merged_facts)
    from services.loss_history_state import loss_run_ownership_answer, ownership_answer_covers
    ownership_confirmed = loss_run_ownership_answer(merged_facts) is True

    per_doc: List[dict] = []
    best: Optional[dict] = None
    for d in loss_docs:
        f = d.get("facts") or {}
        doc_name = _text(_fv(f, "applicant_name"))
        doc_fein = _text(_fv(f, "fein"))
        doc_pol = _text(_fv(f, "policy_number"))
        doc_addr = _text(_fv(f, "mailing_address") or _fv(f, "physical_address"))
        doc_carrier = _text(_fv(f, "carrier_name"))
        matched: List[str] = []
        failed: List[str] = []
        notes: List[str] = []

        fein_ok = bool(doc_fein) and any(feins_match(doc_fein, p) for p in pkg["fein"])
        pol_ok = bool(doc_pol) and any(identifiers_match(doc_pol, p, ctx) for p in pkg["policy"])
        addr_ok = bool(doc_addr) and any(
            values_agree("mailing_address", doc_addr, p, ctx) for p in pkg["address"])
        # CARRIER FAMILY, not carrier identity (client 1.8 "known carrier-name
        # variations"). `values_agree` uses the strict key, which correctly
        # refuses to merge EMC Property & Casualty with Employers Mutual
        # Casualty for CONFLICT purposes - but they are one carrier group, and
        # asking "is this run from our carrier?" with the conflict comparator
        # raised a false note on an ordinary EMC package. Verified 2026-08-21.
        carrier_ok = (not doc_carrier) or (not pkg["carrier"]) or any(
            carriers_same_family(doc_carrier, p) for p in pkg["carrier"])
        (matched if fein_ok else failed).append("fein")
        (matched if pol_ok else failed).append("policy_number")
        (matched if addr_ok else failed).append("address")
        if doc_carrier and pkg["carrier"] and not carrier_ok:
            notes.append(NOTE_CARRIER_DIFFERS)

        if not doc_name:
            tier = POSSIBLE
            failed.insert(0, "name")
            notes.append(NOTE_NO_NAME)
        else:
            name_ok = values_agree("applicant_name", doc_name, applicant, ctx)
            dba_ok = (not name_ok) and any(
                values_agree("applicant_name", doc_name, dba, ctx) for dba in pkg["dba"])
            if name_ok:
                matched.insert(0, "name")
                tier = STRONG if (fein_ok or pol_ok) else (MODERATE if addr_ok else POSSIBLE)
            elif dba_ok:
                # BRENT RULING 2026-08-24 (Q3a CLOSED): "Treat it as a verified
                # match if the DBA is listed by the applicant and the EIN
                # matches. That is enough to confirm the loss runs belong to
                # the insured." So a name matching a DBA THE APPLICANT
                # DECLARED is a name match, and the ordinary tiers apply from
                # there. `pkg["dba"]` only ever holds DBAs the package's own
                # non-loss-run documents state, so this can never promote a
                # trade name that appears solely on the loss run.
                matched.insert(0, "dba_name")
                tier = STRONG if (fein_ok or pol_ok) else (MODERATE if addr_ok else POSSIBLE)
                if tier != STRONG:
                    # Confirmed only by a trade name - the agent should still see it.
                    notes.append(NOTE_DBA)
            else:
                failed.insert(0, "name")
                if fein_ok:
                    # BRENT RULING 2026-08-24 (Q3b CLOSED): "Treat it as a
                    # probable match and ask for confirmation of the prior name
                    # or entity relationship. The EIN match is strong evidence,
                    # but the unexplained name should still be verified."
                    # MODERATE (not STRONG): the identifier is proven, the name
                    # is not - and the note carries the confirmation ask.
                    tier = MODERATE
                    notes.append(NOTE_FEIN_NAME_DIFFERS)
                else:
                    tier = NO_MATCH

        # THE PRODUCER'S CONFIRMATION (23 Oct 2026, package fc04c74f): a run
        # whose insured name (or a declared DBA) matches, or whose tax ID
        # matches under a different name, is the producer's to confirm. A "Yes"
        # makes it a person-confirmed strong match; a "No" changes nothing. A
        # run naming no insured, or another company, is never promoted.
        if tier in (MODERATE, POSSIBLE) and ownership_confirmed and ownership_answer_covers(merged_facts, d) and (
                "name" in matched or "dba_name" in matched or fein_ok):
            tier = STRONG
            matched.append("person_confirmed")
            notes = [n for n in notes if n not in (NOTE_DBA, NOTE_FEIN_NAME_DIFFERS)]

        row = {"filename": d.get("filename") or "loss run", "tier": tier,
               "matched_on": matched, "failed_on": failed, "notes": notes}
        per_doc.append(row)
        if best is None or _RANK[tier] > _RANK[best["tier"]]:
            best = row
        # No early stop at the first STRONG run (live ff2ba3e5, 25 Oct): every
        # loss run gets its own verdict, so a later run naming another company
        # still shows on the review screen.

    if best is None:                                        # pragma: no cover
        return {"tier": NO_LOSS_RUN, "matched_on": [], "failed_on": [],
                "notes": [], "per_document": per_doc}
    all_notes: List[str] = []
    for row in per_doc:
        for n in row["notes"]:
            if n not in all_notes:
                all_notes.append(n)
    return {"tier": best["tier"], "matched_on": list(best["matched_on"]),
            "failed_on": list(best["failed_on"]), "notes": all_notes,
            "per_document": per_doc}


def loss_run_match_tier(docs: List[dict], applicant_name: Optional[str],
                        merged_facts: Optional[dict] = None) -> str:
    """The tier string alone - the historical contract every scorer consumes."""
    return match_loss_run_identity(docs, applicant_name, merged_facts)["tier"]
