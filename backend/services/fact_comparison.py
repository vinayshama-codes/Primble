"""fact_comparison.py - THE ONE DOOR for "are these two values the same fact?"

V1 plan C1 (2026-08-21), decision D3. Before this module existed, five places
decided on their own whether two printings of a fact conflicted, and each
chose its own normalisation:

    underwriting_consistency  (the Data Consistency picker)   equivalence filter: yes
    sqs_service.check_doc_consistency                          3 of its 8 fields only
    extraction_service.detect_source_conflicts                 none
    sqs_service._check_loss_run_insured_match                  FEIN + policy compared raw
    extraction_service._consolidate_property_locations         its own address regex

The client's literal address trio was a non-conflict on one screen and an 85
cap on the next. The fix is structural, not per site: every comparison goes
through here, and ``tests/test_comparison_has_one_owner.py`` fails the build
if any other module imports the underlying comparators directly.

WHAT THIS MODULE IS
  * a thin, STABLE front door over ``fact_equivalence`` (the typed pairwise
    comparator) and ``normalization`` (the cheap string normalisers);
  * the only place that knows the two-step recipe: collapse identical
    normalised strings first, then ask the typed comparator about what is
    left, clique-aware (D7).

WHAT IT IS NOT
  * not a new comparator. Every equivalence rule still lives in
    ``fact_equivalence.same_fact`` and is swept there. Adding a rule here
    would recreate the divergence this module exists to end.
  * not a tolerance band. It never decides two different numbers are equal.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence

from services import fact_equivalence as _fe
from services.fact_equivalence import (          # re-exported on purpose
    SAME, DIFFERENT, INCOMPARABLE, PackageContext,
)
from services.normalization import (
    normalize_value, normalize_fein, normalize_carrier, strict_entity_key,
    entity_identity_conflict as _entity_identity_conflict,
)

logger = logging.getLogger(__name__)

__all__ = [
    "SAME", "DIFFERENT", "INCOMPARABLE", "PackageContext",
    "ComparisonResult", "compare", "conflict", "values_agree", "verdict",
    "identifiers_match", "feins_match", "carriers_same_family", "build_context",
    "document_witnesses", "entities_materially_differ",
]


def entities_materially_differ(raw_values: Sequence[Any]) -> bool:
    """True when two of ``raw_values`` name MATERIALLY different legal entities.

    Strict-key token subsets: equal sets, or one contained in the other
    (a truncation or a missing suffix), are one entity. Each side carrying a
    token the other lacks is a real disagreement.

    THIS IS A THIRD QUESTION, and it is deliberately not ``conflict()``.
    ``conflict`` asks *"do these printings disagree?"* over a whole value list
    with equivalence cliques, package context and scope. This one is the
    narrow **re-split** test the picker applies AFTER a merge has already
    collapsed a group: if the merge folded two real entities together, the
    group has to come apart again so the producer is asked. Keeping it here
    rather than in the caller is decision D3 - the sameness rule lives behind
    the door whatever shape the question takes.
    """
    return bool(_entity_identity_conflict(list(raw_values or [])))


@dataclass
class ComparisonResult:
    """What the door says about a list of printings of ONE fact key.

    ``groups``  - lists of input indices; each group is one real-world value.
    ``verdict`` - "empty" (nothing usable) | "single" (one value, one printing)
                  | "equivalent" (several printings, one value)
                  | "conflict" (two or more genuinely different values)
                  | "incomparable" (prose on every side - no question to ask).
    """
    groups: List[List[int]] = field(default_factory=list)
    verdict: str = "empty"
    # Representative input index per group (the printing to display).
    representatives: List[int] = field(default_factory=list)

    @property
    def distinct(self) -> int:
        return len(self.groups)

    @property
    def is_conflict(self) -> bool:
        return self.verdict == "conflict"


def build_context(merged_facts: Optional[dict] = None,
                  docs: Optional[List[dict]] = None) -> Optional[PackageContext]:
    """The package's verified contract index, or None if it cannot be built.

    Fail-open: a caller that cannot get a context compares without one, which
    is today's behaviour for a package with no dec index.
    """
    try:
        return PackageContext(merged_facts, docs)
    except Exception as exc:                                 # noqa: BLE001
        logger.warning("fact_comparison: package context unavailable - %s", exc)
        return None


def _usable(values: Sequence[Any]) -> List[int]:
    return [i for i, v in enumerate(values) if str(v or "").strip()]


def compare(fact_key: str, values: Sequence[Any],
            context: Optional[PackageContext] = None) -> ComparisonResult:
    """Group ``values`` into real-world values for ``fact_key``.

    Step 1 collapses printings whose NORMALISED string is identical (cheap,
    and what the picker always did). Step 2 hands one representative per
    group to the typed comparator, which merges cliques of SAME printings
    (C1-B FLAG 3: step 1 alone only works when two of three printings
    normalise byte-identically - step 2 is the real merge).

    Never raises. On an internal failure it returns every usable value as its
    own group - i.e. it reports a conflict rather than hiding one.
    """
    idx = _usable(values)
    if not idx:
        return ComparisonResult([], "empty", [])
    try:
        # Step 1 - identical normalised strings are one printing.
        #
        # ENTITY NAMES use the strict key, never the coarse one. normalize_name
        # / normalize_carrier are EQUIVALENCE tools for document clustering
        # and fold "EMC Property & Casualty" into "Employers Mutual Casualty"
        # (both -> "emc"). Grouping on that here would pronounce two real
        # carriers consistent before the typed comparator ever saw them -
        # Round 10 fix 46, reintroduced one layer up. The strict key folds
        # spelling only; truncations and suffixless forms are then merged by
        # step 2's subset rule, so nothing real is lost.
        entity = _fe.value_kind(fact_key) == _fe.KIND_NAME
        by_norm: Dict[str, List[int]] = {}
        order: List[str] = []
        for i in idx:
            if entity:
                key = strict_entity_key(values[i])
            else:
                key = normalize_value(fact_key, values[i])
            key = key or f"__raw__{str(values[i]).strip().lower()}"
            if key not in by_norm:
                by_norm[key] = []
                order.append(key)
            by_norm[key].append(i)
        groups: List[List[int]] = [by_norm[k] for k in order]
        if len(groups) == 1:
            verdict = "single" if len(groups[0]) == 1 else "equivalent"
            return ComparisonResult(groups, verdict, [groups[0][0]])

        # Step 2 - typed, clique-aware equivalence over one representative
        # per group.
        reps = [g[0] for g in groups]
        mapping = _fe.equivalent_index(fact_key, [values[r] for r in reps], context) or {}
        merged: Dict[int, List[int]] = {}
        for gi, g in enumerate(groups):
            target = mapping.get(gi, gi)
            # follow chains defensively (mapping is keeper-final by contract)
            seen = set()
            while target in mapping and target not in seen:
                seen.add(target)
                target = mapping[target]
            merged.setdefault(target, []).extend(g)
        out_groups = [merged[k] for k in sorted(merged)]
        if len(out_groups) == 1:
            # Either everything merged, or everything was prose.
            all_prose = all(_fe.is_prose(values[i]) for i in idx)
            verdict = "incomparable" if all_prose and len(idx) > 1 else "equivalent"
            return ComparisonResult(out_groups, verdict, [out_groups[0][0]])
        reps_out = [_best_printing(fact_key, values, g) for g in out_groups]
        return ComparisonResult(out_groups, "conflict", reps_out)
    except Exception as exc:                                 # noqa: BLE001
        logger.warning("fact_comparison: compare failed for %s - %s", fact_key, exc)
        return ComparisonResult([[i] for i in idx],
                                "conflict" if len(idx) > 1 else "single", idx)


def _best_printing(fact_key: str, values: Sequence[Any], group: List[int]) -> int:
    best = group[0]
    for i in group[1:]:
        if _fe._prefer(fact_key, values[i], values[best]):
            best = i
    return best


def conflict(fact_key: str, values: Sequence[Any],
             context: Optional[PackageContext] = None) -> bool:
    """True when ``values`` carry two or more genuinely different answers.

    The drop-in replacement for every ``len(distinct_normalized(...)) > 1``
    and every raw ``==`` across documents. Formatting, containment, code
    descriptions, prose and two printings of one contract are all NOT a
    conflict; two different amounts, dates, entities or identifiers ARE.
    """
    return compare(fact_key, values, context).is_conflict


def verdict(fact_key: str, a: Any, b: Any,
            context: Optional[PackageContext] = None) -> str:
    """SAME / DIFFERENT / INCOMPARABLE for two printings of one fact.

    Context-aware: two printings of one contract number are SAME.
    """
    res = compare(fact_key, [a, b], context)
    if res.verdict in ("equivalent", "single"):
        return SAME
    if res.verdict == "incomparable":
        return INCOMPARABLE
    if res.verdict == "empty":
        return INCOMPARABLE
    return DIFFERENT


def values_agree(fact_key: str, a: Any, b: Any,
                 context: Optional[PackageContext] = None) -> bool:
    """True only on a positive SAME. Empty, prose or different -> False."""
    if not str(a or "").strip() or not str(b or "").strip():
        return False
    return verdict(fact_key, a, b, context) == SAME


def identifiers_match(a: Any, b: Any,
                      context: Optional[PackageContext] = None,
                      min_len: int = 4) -> bool:
    """Policy / account / VIN style identifiers: punctuation- and space-blind.

    ``6E7-40-02---26`` == ``6E7 40 02 26`` == ``6e74002 26``. With a context,
    two printings the package's verified index elects to ONE contract also
    match (``6E7-40-02---26`` vs the stub ``6E74002``). Never matches on
    fewer than ``min_len`` alphanumerics - a two-character stub proves nothing.
    """
    na, nb = _fe._alnum(a).upper(), _fe._alnum(b).upper()
    if len(na) < min_len or len(nb) < min_len:
        return False
    if na == nb:
        return True
    if context is not None:
        try:
            return bool(context.same_contract_printing(a, b))
        except Exception:                                    # noqa: BLE001
            return False
    return False


# ── Document role (client 1.2: "carrier role", "insured/producer role") ──────
# A document's ROLE decides which facts it may witness. A loss run states the
# insured's identity and their CLAIMS; it does not state which policy the
# submission is for, who is writing it, or what the proposed term is:
#
#   policy_number   -> the policy the CLAIMS sat under (one of N on a package).
#                      Already consumed properly by services.loss_run_identity.
#   carrier_name    -> who ISSUED THE LOSS RUN (a reporting role), not the
#                      carrier of the policy being applied for.
#   effective_date  -> the loss run's "period covered", not a policy term. This
#   expiration_date    one is a landmine: a 5-year loss window compared against
#                      a 1-year policy term is a guaranteed false date conflict.
#
# Live run 2026-08-21 proved the first two: the picker asked the producer to
# choose between the certificate's GL policy number and the loss run's AUTO
# policy number, and between the dec's carrier and the loss run's carrier.
#
# FAIL-OPEN BY CONSTRUCTION: an unlisted doc_type witnesses everything, so an
# unknown or new document behaves exactly as it does today. This only ever
# REMOVES a comparison, so it cannot manufacture a conflict.
# `coverage_lines` / `lines_of_business` added 2026-08-23, on measured evidence
# rather than by analogy. A loss run's line list is the set of lines its CLAIMS
# sat under, paired with the policy the claim was filed against. On the live Run
# B session that is `{"line": "Business Auto", "policy_number": "6E7 40 02 26"}`
# AND `{"line": "General Liability", "policy_number": "6E7 40 02 26"}` - one
# number on two different canonical lines, which is the exact signature
# `_coverage_lines_are_self_contradictory` treats as a corrupt pairing. Letting
# those rows into the package's coverage schedule made the repair pass clear
# EVERY policy number on the package (measured: 4 cleared, 0 repaired). The loss
# run is not a witness to which policy covers which line; it is a witness to
# what was CLAIMED. It still owns loss history, and `loss_run_identity` still
# reads its policy numbers directly for matching.
_ROLE_BLIND_FACTS: Dict[str, frozenset] = {
    "loss_run": frozenset({
        "policy_number", "carrier_name", "carrier_naic", "insurer_name",
        "effective_date", "expiration_date",
        "policy_effective_date", "policy_expiration_date",
        "coverage_lines", "lines_of_business",
    }),
}


def document_witnesses(doc_type: Any, fact_key: str) -> bool:
    """May a document of this ROLE be read as stating ``fact_key``?

    Used by every cross-document comparison so a document is never asked to
    testify about something its role does not cover. Never raises; unknown
    roles witness everything.
    """
    try:
        blind = _ROLE_BLIND_FACTS.get(str(doc_type or "").strip().lower())
        return not (blind and fact_key in blind)
    except Exception:                                        # pragma: no cover
        return True


def feins_match(a: Any, b: Any) -> bool:
    """Two complete 9-digit FEINs, punctuation-blind. Incomplete -> False."""
    fa, fb = normalize_fein(a), normalize_fein(b)
    return bool(fa and fb and fa == fb)


def carriers_same_family(a: Any, b: Any) -> bool:
    """True when two carrier names belong to the same carrier GROUP.

    DELIBERATELY NOT the same question as ``values_agree("carrier_name", ...)``,
    and the difference is load-bearing - it is the two-comparator split
    ``fact_equivalence`` documents, applied on purpose:

      * **Conflict** ("do these two documents disagree about the carrier?") uses
        the STRICT key. ``EMC Property & Casualty`` and ``Employers Mutual
        Casualty`` are two real legal entities and MUST surface as a conflict -
        Round 10 fix 46 exists for exactly that.
      * **Corroboration** ("is this loss run from a carrier on this account?")
        is a CLUSTERING question. Those same two names are one carrier group,
        and treating them as strangers raised a false "carrier does not match"
        note on an ordinary EMC package.

    So this one consults ``normalize_carrier``'s curated alias map (client 1.8:
    *"known carrier-name variations"*), plus the strict key and token-subset
    truncation. Never used to decide a conflict.
    """
    sa, sb = str(a or "").strip(), str(b or "").strip()
    if not sa or not sb:
        return False
    ca, cb = normalize_carrier(sa), normalize_carrier(sb)
    if ca and cb and ca == cb:
        return True                       # curated alias family, or same trimmed name
    ka, kb = strict_entity_key(sa), strict_entity_key(sb)
    if ka and kb:
        ta, tb = set(ka.split()), set(kb.split())
        if ta == tb or ta <= tb or tb <= ta:
            return True                   # truncation / missing suffix
    return False
