"""fact_comparison.py - THE ONE DOOR for "are these two values the same fact?"

V1 plan C1 (2026-08-21), decision D3. Before this module existed, five places
decided on their own whether two printings of a fact conflicted, and each
chose its own normalisation:

    underwriting_consistency  (the Data Consistency picker)   equivalence filter: yes
    sqs_service.check_doc_consistency                          3 of its 8 fields only
    extraction_service.detect_source_conflicts                 none (MIGRATED 2026-09-09)
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
import re
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
    "same_policy_contract", "policy_contract_groups",
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


def _usable(values: Sequence[Any], fact_key: str = "") -> List[int]:
    """Indices of values that are a usable answer for ``fact_key``.

    A RATING BUREAU IS NEVER THE CARRIER (2026-09-05). AAIS, ISO and NCCI reach
    a carrier fact because their names are printed on the policy as the AUTHOR
    of the coverage forms. On a carrier field that is not a rival value, it is
    not a value - so it is dropped here, before grouping, and the producer is
    never asked to choose between an insurer and a bureau.

    Dropped HERE rather than in ``normalize_value`` because ``compare`` groups
    NAME-kind fields on ``strict_entity_key``, which never consults the
    dispatcher - the first attempt at this fix was inert for exactly that
    reason, and every unit test still passed.
    """
    out: List[int] = []
    try:
        from services.normalization import is_carrier_field, is_insurance_bureau
        _carrier = is_carrier_field(fact_key)
    except Exception:                                        # pragma: no cover
        _carrier = False

        def is_insurance_bureau(_v):                         # type: ignore
            return False
    for i, v in enumerate(values):
        if not str(v or "").strip():
            continue
        if _carrier and is_insurance_bureau(v):
            logger.info("fact_comparison: %s - %r is a rating bureau, not an "
                        "insurer; not a candidate", fact_key, str(v)[:40])
            continue
        out.append(i)
    return out


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
    idx = _usable(values, fact_key)
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


# ── ONE POLICY PRINTED TWO WAYS IS STILL ONE POLICY (SYS-06, D-S) ───────────
# The rule itself is not new - it has lived in `pdf_service._same_policy_contract`
# since the 2026-08-17 ACORD 125 Q4 audit, where `6E74002` and `6E7-40-02---26`
# were counted as two policies and one contract displaced the umbrella off the
# form. What IS new is that it is now behind the door.
#
# Before SYS-06 there were THREE answers to "are these the same policy?":
#
#   pdf_service._same_policy_contract        term-marker rule, context-free
#   PackageContext.same_contract_printing    prefix election, needs the index
#   _coverage_line_dedup_keys                raw alnum equality  <- the weakest
#
# and the weakest one decided whether the Data Consistency picker saw one
# policy or two. On the client's own package `BBC7263 - 26` (dec page) and
# `BBC7263` (certificate) keyed differently, survived the merge as two rows on
# the General Liability line, and the picker reported *"two policies on the same
# coverage line"* on a package where nothing was wrong.
#
# WHY THE SEPARATED TAIL IS REQUIRED, and why this is not a loose prefix match:
# `POL123` and `POL12345` are two policies whose digits run together. The term
# marker is only a term marker when the document PRINTED it as one ("---26",
# " - 26"). That single condition is what keeps this from folding real
# contracts, and it is why `BBC7263-26` vs `GL-4471102-26` (two carriers' GL
# policies on one line - defect D-1) still separates.
_POLICY_TERM_TAIL_RE = re.compile(r"[\s\-]\s*\d{2}\s*$")
_POLICY_CONTRACT_MIN = 5


def same_policy_contract(a: Any, b: Any) -> bool:
    """Two printings of ONE policy contract, decided WITHOUT package context.

    True for ``6E74002`` / ``6E7-40-02---26`` and ``BBC7263`` / ``BBC7263 - 26``
    (the trailing 2-digit TERM marker, printed separated), and for a value that
    arrives carrying its own printed label ("Policy No. BBC7263").
    False for ``POL123`` / ``POL12345`` (digits run together, two policies) and
    for any pair that is not a prefix of the other.

    THE IMPLEMENTATION MOVED DOWN A LAYER ON 2026-09-05 and this is now a
    delegation. It had to: the Data Consistency picker merges through
    ``_merge_equivalent_value_groups`` -> ``fact_equivalence.equivalent_index``,
    which never reaches this module, so the rule was correct here and unread
    there. Keeping a second copy would be the one-rule-two-copies shape that
    let the Umbrella SIR and auto-symbol bugs each survive their first fix.

    Deliberately NOT folded into ``identifiers_match``: that function is the
    loss-run matcher's contract and widening it would loosen an unrelated
    comparison. Same question, two audiences, one implementation.
    """
    return _fe._same_policy_contract(a, b)


def policy_contract_groups(values: Sequence[Any]) -> List[List[int]]:
    """Group indices of ``values`` that name the SAME policy contract.

    Transitive closure of :func:`same_policy_contract`, so three printings of
    one number land in one group. Order-independent by construction (the
    closure is computed over every pair), which matters because the merge sees
    documents in upload order and must not produce a different answer for the
    same package uploaded the other way round.
    """
    n = len(values or [])
    adj: Dict[int, set] = {i: set() for i in range(n)}
    for i in range(n):
        for j in range(i + 1, n):
            if same_policy_contract(values[i], values[j]):
                adj[i].add(j)
                adj[j].add(i)
    seen: set = set()
    out: List[List[int]] = []
    for start in range(n):
        if start in seen:
            continue
        comp, stack = set(), [start]
        while stack:
            node = stack.pop()
            if node in comp:
                continue
            comp.add(node)
            stack.extend(adj[node] - comp)
        seen |= comp
        out.append(sorted(comp))
    return out


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
#
# `certificate` added 2026-09-03 on measured evidence, not by analogy. A
# certificate of insurance EVIDENCES coverage to a third party: it prints
# limits, policy numbers, carriers and dates, and by design prints nothing about
# the risk itself. SYS-05 live run 2 proved what happens when it is allowed to:
# the certificate's property row read "Property - Special Form  $4,200,000" and
# that LIMIT became the package's `property_building_value`, which then carried
# a `valuation_method` the document never stated into the "ACV on a building
# valued at $4,200,000" advisory. Run 1, the declarations page alone, correctly
# reported the building value as MISSING.
#
# A LIMIT IS NOT A VALUE. The building is worth what it is worth; the policy
# pays up to its limit. Reading one as the other overstates or understates the
# risk, and it silently satisfied a COPE completeness check that should have
# stayed open.
#
# Deliberately NOT blind to identity, policy numbers, carriers, dates or
# coverage lines - those are exactly what a certificate is FOR, and blinding
# them would break the multi-carrier roster the ACORD 25 work depends on.
_ROLE_BLIND_FACTS: Dict[str, frozenset] = {
    "loss_run": frozenset({
        "policy_number", "carrier_name", "carrier_naic", "insurer_name",
        "effective_date", "expiration_date",
        "policy_effective_date", "policy_expiration_date",
        "coverage_lines", "lines_of_business",
    }),
    "certificate": frozenset({
        # Values of the risk. A certificate states LIMITS only.
        "property_building_value", "property_bpp_value", "building_value",
        "business_personal_property_value",
        # How the property is valued, and the perils/deductibles behind it -
        # a certificate carries none of this.
        "valuation_method", "coinsurance_percentage", "deductible_basis",
        # COPE. Never printed on a certificate.
        "year_built", "roof_year", "construction_type", "occupancy_type",
        "sprinkler_system", "fire_protection_class", "square_footage",
        # Exposure basis. A certificate is not an application.
        "total_revenue", "total_payroll", "wc_payroll", "num_employees",
        "num_employees_full_time", "num_employees_part_time",
        "annual_gross_sales", "years_in_business",
        # SYS-09, 2026-09-05. The APPLICANT'S OWN CONTACT PERSON, on structural
        # evidence rather than analogy: ACORD 25 has exactly three contact
        # fields - Producer_ContactPerson_FullName / PhoneNumber / EmailAddress
        # - and its NamedInsured block carries a name and a mailing address and
        # nothing else. There is no box on a certificate in which an applicant's
        # contact person can be printed, so EVERY contact person a COI names is
        # the PRODUCER'S. Read as `contact_name` it put the brokerage's own
        # contact into the insured's contact box and then raised a Data
        # Consistency conflict against the real one taken from the submission.
        "contact_name", "contact_phone", "contact_email",
        # DELIBERATELY NOT blinded: producer_name / producer_address /
        # producer_contact_*. Naming the issuing agency is exactly what the
        # certificate's own Producer block is FOR (see the note above) - the
        # defect is the applicant's box being filled from it, not the producer's
        # box existing.
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


def is_declared_trade_name(value, docs, ctx=None) -> bool:
    """Is ``value`` a trade name the APPLICANT declared, rather than a rival
    identity?

    BRENT RULING 2026-08-24 (Q3a): a loss run issued to the insured's declared
    DBA belongs to that insured. The loss-run matcher honours it, but every
    OTHER site that compares applicant names must honour it too, or one package
    asserts both "Matched on: dba name" and "Applicant name differs across
    documents" - which is exactly what the S6 live run produced twice, from two
    different engines (2026-08-25).

    BOTH halves are required, and the second is what makes it safe:
      * some document declares ``value`` as its ``dba_name``, AND
      * that same document gives a DIFFERENT legal name.
    A DBA is very often a prefix of the legal name ("Orbin" for "Orbin
    Contracting LLC"), so matching the DBA alone would swallow the legal name
    itself and silence a genuine two-company conflict.

    ONE OWNER (decision D3): every caller asks here. Fail-open - an error means
    "not a trade name", i.e. today's behaviour.
    """
    try:
        v = str(value or "").strip()
        if not v:
            return False
        for d in (docs or []):
            f = (d or {}).get("facts") or {}
            dba = f.get("dba_name")
            legal = f.get("applicant_name")
            dba = dba.get("value") if isinstance(dba, dict) else dba
            legal = legal.get("value") if isinstance(legal, dict) else legal
            if not dba or not legal:
                continue
            if (values_agree("applicant_name", v, dba, ctx)
                    and not values_agree("applicant_name", v, legal, ctx)):
                return True
        return False
    except Exception:                                         # noqa: BLE001
        return False
