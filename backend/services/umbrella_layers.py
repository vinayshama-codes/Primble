"""services/umbrella_layers.py - one ACORD 131 per umbrella-family LAYER (7 Oct 2026).

Brent (Choice Electric #4): "When we have an umbrella base with excess on top of
it, each gets their own form 131. Layer 1 is Umbrella, with an underlying
schedule focus to GL, Auto, and WC. Layer 2 is Excess, which gets mapped to the
underlying umbrella policy."

WHAT A LAYER IS. The merge already builds one line record per umbrella-family
policy and tells the umbrella LAYER from the EXCESS layer
(`extraction_service._build_line_records`, `lob_canon.umbrella_layer`, 6 Oct).
A TOWER is a package whose umbrella family holds more than one layer: an
umbrella with an excess above it, or excess policies stacked on each other.
Every umbrella-layer record is ONE slot (two umbrella policies on one line is
the existing "two policies on one line" question the picker owns, not a
tower); every excess record is its own slot above it.

ATTACHMENT ORDER (deterministic, upload order never decides):
  1. the umbrella slot sits lowest - an excess attaches above the umbrella;
  2. excess slots: a stated attachment point (`umbrella_attachment_point`, read
     from the layer's own documents) orders them, lowest first; a slot with no
     stated attachment sorts after every slot that has one;
  3. then the smaller own limit first (a following-form layer usually sits on
     the smaller layer below it);
  4. then the record id (stable across runs).
With no umbrella slot the lowest excess is the base.

ONE 131 PER SLOT. Before any copy is generated, slot 0 keeps the plain id
"ACORD_131"; slot 1 is "ACORD_131__excess", slot k >= 2 "ACORD_131__excess-k"
(`form_instances.make_instance_id`). One slot -> no instance, every package
without a tower exactly as before.

A GENERATED COPY STAYS ON ITS LAYER (7 Oct 2026, round 2). Positional keys
re-pointed an existing copy - with its person-typed boxes - at another policy
when a lower layer arrived after generation (an excess dec uploaded later, a
layer the producer added). Every generation / add-form write therefore binds
each 131 copy it stores to its layer's IDENTITY (`bind_layers`, in
`facts[BINDINGS_KEY]`): the layer's own documents, a producer-added layer's
`producer_added` id, its contract numbers and record ids. From then on a bound
copy keeps its layer wherever it sorts, a NEW layer takes the next free key
("excess-2", or "umbrella" for an umbrella arriving under a single excess),
a bound key is never reused, and a copy whose layer left the package gets an
empty view. Packages with no bindings (everything before generation, legacy
sessions) keep the positional keys.

WHERE A LAYER'S VALUES COME FROM.
  * Identity (carrier, NAIC, number, dates, premium, printed line): the LIVE
    record, so a Data Consistency confirmation or a producer's line edit flows
    in.
  * Limits, SIR, follow form, coverage trigger, attachment, the umbrella's own
    UM / UIM / med pay, its schedule of underlying: the layer's OWN documents,
    recorded at merge (`record_layer_evidence`) in `facts[DOCS_KEY]` - only on
    a tower, so every other package's facts are byte-identical. A value the
    layer's documents do not state is BLANK (the excess states no SIR - no SIR
    prints), never inherited from another layer.
  * The plain ACORD 131 of a tower prints ONLY its own layer (the lowest,
    unless a binding says otherwise): a value only another layer's own
    documents print is removed from its view.
  * A layer the PRODUCER added has no documents: its limits and SIR are the
    ones the producer stated on it (`limit_each_occurrence`, `limit_aggregate`,
    `sir` - `policy_lines.UMBRELLA_LIMIT_FIELDS`), blank when not stated.
  * A person's answer to a package-level question (questionnaire, Data
    Consistency) is the PLAIN 131's - the copy every such question answered.

Registered with `form_instances.register_overlay("ACORD_131", ...)`; every
per-form path reaches it through `form_instances.facts_for_form`.
"""
from __future__ import annotations

import copy
import logging
import re
from typing import Any, Dict, Iterable, List, Optional, Set, Tuple

from services import form_instances as fi

logger = logging.getLogger(__name__)

BASE = "ACORD_131"
UMBRELLA_LINE = "umbrella"
UMBRELLA_LAYER = "umbrella"
EXCESS_LAYER = "excess"
INSTANCE_STEM = "excess"

# The private keys this module writes. Both are skipped by every fact loop
# (leading "_") and left out of the gap-fill facts block.
DOCS_KEY = "_umbrella_layer_docs"     # {document: {layer fact: value}} on a tower
MARKER_KEY = "_umbrella_layer"        # on a VIEW only - never persisted
BINDINGS_KEY = "_umbrella_layer_bindings"   # {copy key: its layer's identity}, at generation

# A layer the PRODUCER added states its own limits on its record (POLICIES,
# `policy_lines.UMBRELLA_LIMIT_FIELDS`, copied by
# `extraction_service._producer_line_record`): layer fact <- record field.
_PRODUCER_LIMIT_FIELDS: Dict[str, str] = {"umbrella_limit": "limit_each_occurrence",
                                          "umbrella_sir": "sir"}
_PRODUCER_AGGREGATE_FIELD = "limit_aggregate"

# The facts ONE layer states about itself (fact registry + extraction schema).
LAYER_FACTS: Tuple[str, ...] = (
    "umbrella_limit", "umbrella_sir", "umbrella_attachment_point",
    "umbrella_follow_form", "umbrella_form_type", "umbrella_effective_date",
    "umbrella_expiration_date", "umbrella_um_limit", "umbrella_uim_limit",
    "umbrella_medical_payments_limit", "schedule_of_underlying_insurance",
)
LAYER_LIST_FACTS: Tuple[str, ...] = ("underlying_policies",)

# A person's answer or a picker confirmation is never taken off a view.
_PERSON_SOURCES = frozenset({"producer", "client_arq", "user", "human", "client",
                             "user_confirmed", "cross_form_conflict"})


# ── small readers ─────────────────────────────────────────────────────────────

def _val(held: Any) -> Any:
    return held.get("value") if isinstance(held, dict) and "value" in held else held


def _has(v: Any) -> bool:
    if v is None:
        return False
    if isinstance(v, str):
        return bool(v.strip()) and v.strip().lower() not in ("null", "none")
    if isinstance(v, (list, dict, tuple, set)):
        return bool(v)
    return True


def _person_sourced(held: Any) -> bool:
    return isinstance(held, dict) and str(held.get("source") or "").lower() in _PERSON_SOURCES


def _amount(v: Any) -> Optional[float]:
    """A money printing as a number ("$4,000,000" -> 4000000.0), or None."""
    v = _val(v)
    if v is None:
        return None
    if isinstance(v, (int, float)) and not isinstance(v, bool):
        return float(v)
    try:
        from services.sqs_service import _to_float
        got = _to_float(v)
        if isinstance(got, (int, float)):
            return float(got)
    except Exception:                                         # noqa: BLE001
        pass
    digits = re.sub(r"[^\d.]", "", str(v))
    if not digits or digits.count(".") > 1:
        return None
    try:
        return float(digits)
    except ValueError:
        return None


def _norm(key: str, v: Any) -> str:
    """Comparison key for two printings of one layer fact."""
    v = _val(v)
    if v is None:
        return ""
    s = str(v).strip()
    if not s:
        return ""
    if "date" in key:
        try:
            from services.normalization import normalize_date
            d = normalize_date(s)
            if d:
                return str(d)
        except Exception:                                     # noqa: BLE001
            pass
    if key in ("umbrella_limit", "umbrella_sir", "umbrella_attachment_point",
               "umbrella_um_limit", "umbrella_uim_limit", "umbrella_medical_payments_limit"):
        a = _amount(s)
        if a is not None:
            return f"{a:.2f}"
    return re.sub(r"\s+", " ", s.lower())


def _doc_name(d: Any) -> str:
    return str((d or {}).get("filename") or (d or {}).get("doc_id") or "").strip() \
        if isinstance(d, dict) else ""


# ── the layers of a package ───────────────────────────────────────────────────

def _umbrella_records(facts: Any) -> List[dict]:
    """The umbrella-family policy records, read the way every reader reads them."""
    if not isinstance(facts, dict):
        return []
    raw = _val(facts.get("_line_records"))
    if not isinstance(raw, list):
        return []
    try:
        from services.extraction_service import policy_line_records
        recs = policy_line_records(raw)
    except Exception:                                         # noqa: BLE001
        recs = [r for r in raw if isinstance(r, dict)]
    return [r for r in recs if isinstance(r, dict) and r.get("line") == UMBRELLA_LINE]


def record_layer(rec: dict) -> str:
    """"excess" or "umbrella" - the record's own `layer`, else what its printed
    line name says (records built before 6 Oct carry no layer)."""
    lay = str((rec or {}).get("layer") or "").strip().lower()
    if lay in (UMBRELLA_LAYER, EXCESS_LAYER):
        return lay
    try:
        from services.lob_canon import umbrella_layer
        return umbrella_layer((rec or {}).get("line_printed")) or UMBRELLA_LAYER
    except Exception:                                         # noqa: BLE001
        return UMBRELLA_LAYER


def _doc_store(facts: Any) -> Dict[str, dict]:
    held = (facts or {}).get(DOCS_KEY) if isinstance(facts, dict) else None
    held = _val(held)
    return held if isinstance(held, dict) else {}


def _agreed(values: List[Any], key: str) -> Tuple[Any, bool]:
    """(the one value several printings agree on, conflicted?)."""
    vals = [v for v in values if _has(_val(v))]
    if not vals:
        return None, False
    keys = {_norm(key, v) for v in vals}
    keys.discard("")
    if len(keys) > 1:
        return None, True
    return vals[0], False


def _slot_sources(slot: dict) -> Set[str]:
    out: Set[str] = set()
    for rec in slot.get("records") or []:
        for name in rec.get("sources") or []:
            if str(name or "").strip():
                out.add(str(name).strip())
    return out


def _evidence(facts: Any, docs: Iterable[str], key: str) -> Tuple[Any, bool]:
    store = _doc_store(facts)
    return _agreed([(store.get(d) or {}).get(key) for d in docs], key)


def _producer_text(rec: Any, field: str) -> str:
    return str((rec or {}).get(field) or "").strip() if isinstance(rec, dict) else ""


def _all_slots(facts: Any) -> List[dict]:
    """Every umbrella-family LAYER of the package in attachment order, lowest
    first - ONE slot for a package with one layer (or with rival umbrella
    policies, the picker's question), [] with none.

    Each slot: {"layer", "records", "record" (the one record, or None when the
    umbrella slot holds two rival policies)}."""
    recs = _umbrella_records(facts)
    if not recs:
        return []
    umb = [r for r in recs if record_layer(r) == UMBRELLA_LAYER]
    exc = [r for r in recs if record_layer(r) == EXCESS_LAYER]
    slots: List[dict] = []
    if umb:
        umb = sorted(umb, key=lambda r: str(r.get("id") or ""))
        slots.append({"layer": UMBRELLA_LAYER, "records": umb,
                      "record": umb[0] if len(umb) == 1 else None})

    def _key(rec: dict):
        srcs = {str(n).strip() for n in (rec.get("sources") or []) if str(n or "").strip()}
        att, _c = _evidence(facts, srcs, "umbrella_attachment_point")
        lim, _c2 = _evidence(facts, srcs, "umbrella_limit")
        if lim is None and not srcs and rec.get("producer_added"):
            lim = _producer_text(rec, _PRODUCER_LIMIT_FIELDS["umbrella_limit"]) or None
        att_n = _amount(att)
        lim_n = _amount(lim)
        return (0 if att_n is not None else 1, att_n or 0.0,
                0 if lim_n is not None else 1, lim_n or 0.0, str(rec.get("id") or ""))

    for rec in sorted(exc, key=_key):
        slots.append({"layer": EXCESS_LAYER, "records": [rec], "record": rec})
    return slots


def ordered_layers(facts: Any) -> List[dict]:
    """The package's umbrella-family LAYERS in attachment order, lowest first,
    when it has a TOWER (two or more layers); [] otherwise - callers treat it
    as "no layers" (`_all_slots` has the single layer)."""
    slots = _all_slots(facts)
    return slots if len(slots) >= 2 else []


def instance_key_for(index: int) -> str:
    """The POSITIONAL key (no binding yet): slot 1 -> "excess", k >= 2 -> "excess-k"."""
    return INSTANCE_STEM if index == 1 else f"{INSTANCE_STEM}-{index}"


def form_id_for_slot(index: int) -> str:
    """The positional form id of slot `index` (no binding yet)."""
    return BASE if index == 0 else fi.make_instance_id(BASE, instance_key_for(index))


# ── which copy holds which layer (bindings) ──────────────────────────────────

def _producer_record(slot: dict) -> Optional[dict]:
    """The record of a layer the PRODUCER added ("Policies in this submission":
    `producer_added`, no source document), else None."""
    rec = slot.get("record")
    if not isinstance(rec, dict) or not str(rec.get("producer_added") or "").strip():
        return None
    return None if _slot_sources(slot) else rec


def _policy_numbers(recs: Iterable[dict]) -> List[str]:
    out: List[str] = []
    for r in recs:
        for p in [r.get("policy_number")] + list((r.get("printings") or {}).get("policy_number") or []):
            s = str(p or "").strip()
            if s and s not in out:
                out.append(s)
    return out


def layer_identity(slots: List[dict], index: int) -> dict:
    """What a copy generated for layer `index` is bound to: the layer's kind,
    its source documents (and those only it prints), the producer's id for a
    layer they added, its contract numbers and record ids. Documents are the
    primary identity - record ids and numbers change after confirmations."""
    slot = slots[index]
    recs = [r for r in (slot.get("records") or []) if isinstance(r, dict)]
    return {
        "layer": slot["layer"],
        "documents": sorted(_slot_sources(slot)),
        "own_documents": sorted(_exclusive_docs(slots, index)),
        "producer_added": sorted({str(r.get("producer_added")).strip() for r in recs
                                  if str(r.get("producer_added") or "").strip()}),
        "policy_numbers": sorted(_policy_numbers(recs)),
        "records": sorted({str(r.get("id")) for r in recs if r.get("id")}),
    }


def _same_contract(a: Any, b: Any) -> bool:
    try:
        from services.fact_comparison import same_policy_contract
        return bool(same_policy_contract(a, b))
    except Exception:                                         # noqa: BLE001
        ka = re.sub(r"[^A-Za-z0-9]", "", str(a or "")).upper()
        return bool(ka) and ka == re.sub(r"[^A-Za-z0-9]", "", str(b or "")).upper()


def _match(binding: Any, ident: dict) -> Optional[Tuple[int, ...]]:
    """How strongly a stored binding names this layer (higher is stronger), or
    None when it does not name it at all.

    * A binding of a layer the producer added (no documents) names only the
      layer carrying that `producer_added` id.
    * A document layer's binding names a layer of the same kind (or one
      sharing a producer id) that its exclusive documents print - ALL of them
      when the contract numbers disagree (a producer's corrected number keeps
      the record's documents) - or that a shared document prints with no
      disagreeing number, or with the same contract number, or the same
      record id."""
    if not isinstance(binding, dict):
        return None
    b_prod = {str(p) for p in binding.get("producer_added") or ()}
    b_docs = {str(d) for d in binding.get("documents") or ()}
    s_docs = set(ident["documents"])
    prod = 1 if b_prod & set(ident["producer_added"]) else 0
    if b_prod and not b_docs:
        return (1, 0, 0, 0, 0, 0) if prod else None
    if not prod and binding.get("layer") != ident["layer"]:
        return None
    b_own = {str(d) for d in binding.get("own_documents") or ()}
    b_nos, s_nos = list(binding.get("policy_numbers") or ()), ident["policy_numbers"]
    agree = bool(b_nos and s_nos and any(_same_contract(a, b) for a in b_nos for b in s_nos))
    disagree = bool(b_nos and s_nos) and not agree
    own = len(b_own & s_docs) if (b_own <= s_docs or not disagree) else 0
    shared = len(b_docs & s_docs) if not disagree else 0
    rec = 1 if {str(r) for r in binding.get("records") or ()} & set(ident["records"]) else 0
    if not (prod or own or agree or rec or shared):
        return None
    return (prod, 1 if own else 0, own, 1 if agree else 0, shared, rec)


def _valid_key(key: Any) -> bool:
    key = str(key if key is not None else "")
    return key == "" or fi.is_instance(f"{BASE}{fi.SEPARATOR}{key}")


def read_bindings(facts: Any) -> Dict[str, dict]:
    """{copy key: layer identity} recorded at generation / add-form ({} none)."""
    held = _val(facts.get(BINDINGS_KEY)) if isinstance(facts, dict) else None
    if not isinstance(held, dict):
        return {}
    return {str(k): v for k, v in held.items() if isinstance(v, dict) and _valid_key(k)}


def _key_rank(key: str) -> Tuple[int, str, int]:
    if not key:
        return (0, "", 0)
    stem, _, num = key.partition("-")
    return (1, stem, int(num) if num.isdigit() else 1)


def _next_free_key(taken: Set[str], layer: str) -> str:
    """The key a layer no copy holds yet gets: the plain 131's if nobody holds
    it, else the first free "excess" / "excess-2" ... ("umbrella" ... for an
    umbrella-kind layer). A bound key is never reused."""
    if "" not in taken:
        return ""
    stem = UMBRELLA_LAYER if layer == UMBRELLA_LAYER else INSTANCE_STEM
    n = 1
    while True:
        key = stem if n == 1 else f"{stem}-{n}"
        if key not in taken:
            return key
        n += 1


def _assign(facts: Any) -> Tuple[List[dict], Dict[str, Optional[int]]]:
    """(the layers in attachment order, {copy key: layer index, or None for a
    bound copy whose layer left the package}).

    No bindings: POSITIONAL (the plain 131 = the lowest layer, then "excess",
    "excess-2", ...), and a package with one layer has only the plain 131.
    With bindings: each bound copy keeps the layer its identity names (best
    match first, one copy per layer); every other layer, in attachment order,
    takes the next free key."""
    slots = _all_slots(facts)
    bindings = read_bindings(facts)
    if not bindings:
        if len(slots) < 2:
            return slots, ({"": 0} if slots else {})
        return slots, {("" if i == 0 else instance_key_for(i)): i for i in range(len(slots))}
    idents = [layer_identity(slots, i) for i in range(len(slots))]
    pairs = []
    for key, binding in bindings.items():
        for i, ident in enumerate(idents):
            score = _match(binding, ident)
            if score is not None:
                pairs.append((score, key, i))
    pairs.sort(key=lambda p: (tuple(-x for x in p[0]), _key_rank(p[1]), p[2]))
    assign: Dict[str, Optional[int]] = {k: None for k in bindings}
    held: Set[int] = set()
    for _score, key, i in pairs:
        if assign[key] is None and i not in held:
            assign[key] = i
            held.add(i)
    taken = set(bindings)
    for i in range(len(slots)):
        if i not in held:
            key = _next_free_key(taken, slots[i]["layer"])
            assign[key] = i
            taken.add(key)
    return slots, assign


def _keys_by_index(assign: Dict[str, Optional[int]]) -> Dict[int, str]:
    return {i: k for k, i in assign.items() if i is not None}


def instance_keys(facts: Any) -> List[str]:
    """The instance keys the package has now ("excess", "excess-2", ...), in
    attachment order; [] with no tower and no copy bound off the plain id. A
    bound copy whose layer left is not listed (it is never generated again)."""
    _slots, assign = _assign(facts)
    return [k for i, k in sorted(_keys_by_index(assign).items()) if k]


def bind_layers(facts: Any, form_ids: Iterable[Any]) -> Optional[dict]:
    """Bind every ACORD 131 copy in `form_ids` (just generated or added) to the
    layer it was generated for. Returns {BINDINGS_KEY: every binding} when one
    was added (the caller writes it with the forms), else None. A copy already
    bound keeps its binding; a copy the package does not assign is not bound."""
    if not isinstance(facts, dict):
        return None
    slots, assign = _assign(facts)
    if not slots:
        return None
    bindings = {k: dict(v) for k, v in read_bindings(facts).items()}
    added = False
    for fid in form_ids or []:
        fid = str((fid.get("form_id") if isinstance(fid, dict) else fid) or "")
        if fi.base_form_id(fid) != BASE:
            continue
        key = fi.instance_key(fid) or ""
        if key in bindings:
            continue
        idx = assign.get(key)
        if idx is None:
            continue
        bindings[key] = layer_identity(slots, idx)
        added = True
    return {BINDINGS_KEY: bindings} if added else None


# ── which documents belong to which layer ────────────────────────────────────

def _doc_slots(slots: List[dict]) -> Dict[str, Set[int]]:
    out: Dict[str, Set[int]] = {}
    for i, slot in enumerate(slots):
        for name in _slot_sources(slot):
            out.setdefault(name, set()).add(i)
    return out


def _exclusive_docs(slots: List[dict], index: int) -> Set[str]:
    return {n for n, s in _doc_slots(slots).items() if s == {index}}


def _slot_value(facts: dict, slots: List[dict], index: int, key: str) -> Tuple[Any, bool]:
    """A layer fact as the layer's OWN documents print it: (value, conflicted)."""
    docs = _exclusive_docs(slots, index) or _slot_sources(slots[index])
    return _evidence(facts, docs, key)


def _clean_envelope(held: Any) -> Any:
    """A layer document's own printing as a fact envelope for a view: its value
    and provenance, never the per-document `value_state` the merge computed
    for a cross-document comparison (it is this layer's value, present)."""
    if not isinstance(held, dict) or "value" not in held:
        return copy.deepcopy(held)
    out = {k: copy.deepcopy(held[k]) for k in
           ("value", "source", "confidence", "verified_in_text", "derivation") if k in held}
    out["value_state"] = "present"
    if held.get("evidence_state") in ("source_verified", "suggested"):
        out["evidence_state"] = held["evidence_state"]
    return out


def _base_value(facts: dict, slots: List[dict], key: str, person_ok: bool = True) -> Any:
    """The lowest layer's value of `key`, or None to blank it. `person_ok`:
    the lowest layer's copy is the plain 131, so a person's package-level
    answer is its own (False: that answer belongs to another copy)."""
    held = facts.get(key)
    person = _person_sourced(held)
    if person and person_ok:
        return held
    own, conflicted = _evidence(facts, _exclusive_docs(slots, 0), key)
    if own is not None:
        if not person and _norm(key, held) == _norm(key, own):
            return held                 # the merge already holds this layer's value
        return _clean_envelope(own)     # it came from elsewhere: the layer's own wins
    if person:
        return None                     # another copy's answer; its documents state none
    if conflicted:
        return held                     # its own documents disagree: the picker's business
    if not _has(_val(held)):
        return held
    upper = set()
    for i in range(1, len(slots)):
        upper |= _exclusive_docs(slots, i)
    store = _doc_store(facts)
    mine = _norm(key, held)
    if mine and any(_norm(key, (store.get(d) or {}).get(key)) == mine for d in upper):
        return None                     # only an upper layer prints this value
    return held


# ── which coverage rows belong to which layer ────────────────────────────────

def _row_layer(row: dict) -> Optional[str]:
    try:
        from services.lob_canon import canon_line, umbrella_layer
        if canon_line(row.get("line")) != UMBRELLA_LINE:
            return None
        return umbrella_layer(row.get("line")) or UMBRELLA_LAYER
    except Exception:                                         # noqa: BLE001
        return None


def _row_number(row: dict) -> str:
    pol = str(row.get("policy_number") or "").strip()
    if not pol:
        return ""
    try:
        from services.extraction_service import _not_a_contract_number
        if _not_a_contract_number(pol):
            return ""
    except Exception:                                         # noqa: BLE001
        pass
    return pol


def _row_belongs(row: dict, rec: dict) -> Optional[bool]:
    """Does this umbrella-family row print THIS record? None = cannot tell."""
    try:
        from services.fact_comparison import same_policy_contract, values_agree
    except Exception:                                         # noqa: BLE001
        return None
    pol = _row_number(row)
    rno = str(rec.get("policy_number") or "").strip()
    if pol and rno:
        try:
            return bool(same_policy_contract(pol, rno))
        except Exception:                                     # noqa: BLE001
            return None
    carrier = str(row.get("carrier") or "").strip()
    rec_carriers = [str(c) for c in ([rec.get("carrier_name")]
                                     + list((rec.get("printings") or {}).get("carrier_name") or []))
                    if str(c or "").strip()]
    if carrier and rec_carriers:
        try:
            return any(bool(values_agree("carrier_name", carrier, c)) for c in rec_carriers)
        except Exception:                                     # noqa: BLE001
            return None
    if pol and not rno:
        return False                     # a numbered row is not an unnumbered record
    return None


def _row_slot(row: dict, slots: List[dict]) -> Optional[int]:
    """The slot an umbrella-family row prints, or None (another company's
    mention, or a row that cannot be placed)."""
    lay = _row_layer(row)
    if lay is None:
        return None
    cands = [i for i, s in enumerate(slots) if s["layer"] == lay]
    if not cands and lay == UMBRELLA_LAYER:
        return None
    hits, unknown = [], []
    for i in cands:
        verdicts = [_row_belongs(row, rec) for rec in slots[i]["records"]]
        if any(v is True for v in verdicts):
            hits.append(i)
        elif all(v is None for v in verdicts):
            unknown.append(i)
    if len(hits) == 1:
        return hits[0]
    if not hits and len(cands) == 1 and unknown == cands:
        return cands[0]                  # a bare row, one slot it can be
    return None


# ── the view ─────────────────────────────────────────────────────────────────

def _record_summary(slot: dict, limit: Any) -> dict:
    rec = slot.get("record") or {}
    return {
        "layer": slot["layer"],
        "record": rec.get("id"),
        "line_printed": rec.get("line_printed"),
        "carrier": rec.get("carrier_name"),
        "naic": rec.get("carrier_naic"),
        "policy_number": rec.get("policy_number"),
        "effective_date": rec.get("effective_date"),
        "expiration_date": rec.get("expiration_date"),
        "premium": rec.get("premium"),
        "limit": _val(limit) if _has(_val(limit)) else None,
    }


def _filter_rows(held: Any, keep) -> Any:
    rows = _val(held)
    if not isinstance(rows, list):
        return held
    kept = [r for r in rows if keep(r)]
    if isinstance(held, dict) and "value" in held:
        return {**held, "value": kept}
    return kept


def _producer_envelope(key: str, text: str) -> Any:
    """A producer's stated amount as a fact envelope (None when it is not a
    value - "none", "n/a")."""
    try:
        from services.answer_semantics import build_fact_envelope, interpret_answer
        interp = interpret_answer(key, text)
        if not _has(interp.value):
            return None
        return build_fact_envelope(key, interp, "producer", "filled")
    except Exception:                                         # noqa: BLE001
        return {"value": text, "confidence": "filled", "source": "producer"}


def _producer_value(slot: dict, key: str) -> Any:
    """A producer-added layer's own statement of layer fact `key`, or None."""
    rec = _producer_record(slot)
    field = _PRODUCER_LIMIT_FIELDS.get(key)
    text = _producer_text(rec, field) if rec is not None and field else ""
    return _producer_envelope(key, text) if text else None


def _producer_marker(slot: dict) -> dict:
    """What the copy of a producer-added layer prints beyond its facts: the
    aggregate it stated (both 131 limit boxes otherwise read one fact)."""
    rec = _producer_record(slot)
    if rec is None:
        return {}
    agg = _producer_envelope("umbrella_limit", _producer_text(rec, _PRODUCER_AGGREGATE_FIELD)) \
        if _producer_text(rec, _PRODUCER_AGGREGATE_FIELD) else None
    return {"producer_layer": True, "aggregate": _val(agg) if agg else None}


def _producer_states_limits(slot: dict) -> bool:
    rec = _producer_record(slot)
    return rec is not None and any(
        _producer_text(rec, f) for f in (*_PRODUCER_LIMIT_FIELDS.values(), _PRODUCER_AGGREGATE_FIELD))


def _layer_value(facts: dict, slots: List[dict], index: int, key: str, fact: str) -> Any:
    """Layer fact `fact` as the copy `key` of layer `index` prints it, or None
    (blank). A person's package-level answer is the plain 131's; a layer the
    producer added prints what they stated on it; the lowest layer reads the
    package without what only an upper layer prints; an upper layer reads its
    own documents."""
    held = facts.get(fact)
    plain = key == ""
    if plain and _person_sourced(held):
        return held
    stated = _producer_value(slots[index], fact)
    if stated is not None:
        return stated
    if index == 0:
        return _base_value(facts, slots, fact, person_ok=plain)
    own, _conflicted = _slot_value(facts, slots, index, fact)
    return None if own is None else _clean_envelope(own)


def _slot_limit(facts: dict, slots: List[dict], index: int, key: str) -> Any:
    return _layer_value(facts, slots, index, key, "umbrella_limit")


def _empty_view(facts: dict, key: str) -> dict:
    """An instance the package no longer has: every layer value blank, so the
    form can never print another layer's policy as its own."""
    out = dict(facts)
    for k in LAYER_FACTS:
        out.pop(k, None)
    if "underlying_policies" in facts:
        out["underlying_policies"] = []
    if "coverage_lines" in facts:
        out["coverage_lines"] = _filter_rows(facts.get("coverage_lines"),
                                             lambda r: not (isinstance(r, dict) and _row_layer(r)))
    recs = _val(facts.get("_line_records"))
    if isinstance(recs, list):
        out["_line_records"] = [r for r in recs
                                if not (isinstance(r, dict) and r.get("line") == UMBRELLA_LINE)]
    out[MARKER_KEY] = {"key": key, "index": None, "count": 0, "missing": True}
    return out


def layer_view(facts: Any, key: str = "") -> Any:
    """The ACORD 131 overlay: the facts the copy for instance `key` ("" = the
    plain 131) is stamped, scored and checked from.

    `facts` itself whenever the package has one layer and the plain 131 holds
    it (the plain 131 then behaves exactly as before), when it has no
    umbrella-family policy at all, and for a view already made (a view is
    final). A copy the package does not assign a layer - a bound copy whose
    layer left, a stale id - gets the empty view.
    """
    if not isinstance(facts, dict) or MARKER_KEY in facts:
        return facts
    key = str(key or "")
    slots, assign = _assign(facts)
    if not slots:
        return facts if key == "" else _empty_view(facts, key)
    idx = assign.get(key)
    if idx is None:
        return _empty_view(facts, key)
    if len(slots) == 1:
        return _single_layer_view(facts, slots, key)
    return _tower_view(facts, slots, assign, idx, key)


def _single_layer_view(facts: dict, slots: List[dict], key: str) -> dict:
    """The copy of the package's ONLY umbrella-family layer. The plain 131 is
    the package facts themselves - unless the layer is one the producer added
    with limits stated on it, which no document carries into the facts. A copy
    held under another key (its plain sibling's layer left) reads the same
    package values: there is no other layer they could belong to."""
    slot = slots[0]
    producer = _producer_record(slot) is not None
    if key == "" and not _producer_states_limits(slot):
        return facts
    out = dict(facts)
    if producer:
        for k in LAYER_FACTS:
            v = _layer_value(facts, slots, 0, key, k)
            if v is None:
                out.pop(k, None)
            else:
                out[k] = v
    limit = _layer_value(facts, slots, 0, key, "umbrella_limit") if producer else facts.get("umbrella_limit")
    out[MARKER_KEY] = {
        "key": key,
        "index": 0,
        "count": 1,
        **_record_summary(slot, limit),
        "below": None,
        "own_documents": sorted(_slot_sources(slot)),
        "other_layer_documents": [],
        **_producer_marker(slot),
    }
    return out


def _tower_view(facts: dict, slots: List[dict], assign: Dict[str, Optional[int]],
                idx: int, key: str) -> dict:
    """The copy `key` of layer `idx` of a tower (two or more layers)."""
    keys = _keys_by_index(assign)
    slot = slots[idx]
    own_ids = {r.get("id") for r in slot["records"]}
    all_ids = {r.get("id") for s in slots for r in s["records"]}
    other_ids = all_ids - own_ids

    out = dict(facts)
    # Policy identity: only this layer's rows, records and scoped values.
    out["coverage_lines"] = _filter_rows(
        facts.get("coverage_lines"),
        lambda r: not (isinstance(r, dict) and _row_layer(r))
        or _row_slot(r, slots) == idx)
    recs = _val(facts.get("_line_records"))
    if isinstance(recs, list):
        out["_line_records"] = [r for r in recs if not (
            isinstance(r, dict) and r.get("line") == UMBRELLA_LINE and r.get("id") in other_ids)]
    scoped = _val(facts.get("_scoped"))
    if isinstance(scoped, dict):
        out["_scoped"] = {
            k: [e for e in (v or []) if not (
                isinstance(e, dict) and (e.get("scope") or {}).get("line") == UMBRELLA_LINE
                and (e.get("scope") or {}).get("record") in other_ids)]
            for k, v in scoped.items()}

    # The layer's own values.
    for k in LAYER_FACTS:
        v = _layer_value(facts, slots, idx, key, k)
        if v is None:
            out.pop(k, None)
        else:
            out[k] = v
    if idx == 0:
        upper_docs: Set[str] = set()
        for i in range(1, len(slots)):
            upper_docs |= _exclusive_docs(slots, i)
        upper_rows = [r for d in upper_docs
                      for r in (_val((_doc_store(facts).get(d) or {}).get("underlying_policies")) or [])
                      if isinstance(r, dict)]
        low_rows = [r for d in _exclusive_docs(slots, 0)
                    for r in (_val((_doc_store(facts).get(d) or {}).get("underlying_policies")) or [])
                    if isinstance(r, dict)]
        if upper_rows:
            out["underlying_policies"] = _filter_rows(
                facts.get("underlying_policies"),
                lambda r: not (r in upper_rows and r not in low_rows))
    else:
        # Its underlying is the layer below, printed from that layer's record
        # (OTHER POLICY row A) - and, Brent 23 Oct 2026 (Z34-1 #3), "list the
        # applicable underlying coverages - but do not automatically require
        # all three": the lines the lowest layer sits over
        # (`applicable_underlying_lines`, on the marker), printed in their own
        # rows by `pdf_service._resolve_upper_layer_box`. The layer's own
        # schedule stays its own (empty): no score reads another layer's.
        out["underlying_policies"] = []
        base_view = _tower_view(facts, slots, assign, 0, keys.get(0, ""))
        underlying_lines = applicable_underlying_lines(base_view)
        base_rows = _val(base_view.get("underlying_policies"))
        base_rows = [r for r in base_rows if isinstance(r, dict)] if isinstance(base_rows, list) else []

    # Declarations index (present only before the post-generation purge): an
    # entry tagged with another layer's contract number is that layer's; an
    # untagged umbrella-family entry cannot be placed on an upper layer.
    ents = _val(facts.get("dec_page_entries"))
    if isinstance(ents, list):
        own_nos = [str(r.get("policy_number") or "").strip() for r in slot["records"]
                   if str(r.get("policy_number") or "").strip()]
        other_nos = [str(r.get("policy_number") or "").strip()
                     for s in slots for r in s["records"]
                     if r.get("id") in other_ids and str(r.get("policy_number") or "").strip()]

        def _keep_entry(e: Any) -> bool:
            if not isinstance(e, dict):
                return True
            try:
                from services.lob_canon import canon_line
                fam = canon_line(e.get("line_of_business")) or canon_line(e.get("section"))
            except Exception:                                 # noqa: BLE001
                fam = None
            if fam != UMBRELLA_LINE:
                return True
            no = str(e.get("policy_number") or "").strip()
            try:
                from services.fact_comparison import same_policy_contract as _same
            except Exception:                                 # noqa: BLE001
                def _same(a, b):                              # type: ignore
                    return re.sub(r"\W", "", str(a)).upper() == re.sub(r"\W", "", str(b)).upper()
            if no and any(_same(no, o) for o in other_nos):
                return False
            if idx > 0 and not (no and any(_same(no, o) for o in own_nos)):
                return False
            return True
        out["dec_page_entries"] = _filter_rows(facts.get("dec_page_entries"), _keep_entry)

    # The prior umbrella-family policy rows: an excess-worded one is not the
    # umbrella's expiring policy; an upper layer reads no prior row at all.
    prior = _val(facts.get("prior_coverage_by_line"))
    if isinstance(prior, list):
        def _keep_prior(r: Any) -> bool:
            if not isinstance(r, dict):
                return True
            lay = _row_layer({"line": r.get("line") or r.get("line_of_business")})
            if lay is None:
                return True
            return idx == 0 and lay == UMBRELLA_LAYER
        out["prior_coverage_by_line"] = _filter_rows(facts.get("prior_coverage_by_line"), _keep_prior)

    below = None
    if idx > 0:
        below_limit = _slot_limit(facts, slots, idx - 1, keys.get(idx - 1, ""))
        if idx - 1 == 0 and "umbrella_limit" in (facts.get("_uw_conflicted_keys") or ()):
            below_limit = None          # the picker still owns the lower layer's limit
        below = _record_summary(slots[idx - 1], below_limit)
        # The package's withheld keys are the LOWEST layer's questions; this
        # layer's own values come from its own documents and agree there.
        for ck in ("_uw_conflicted_keys", "_uw_conflict_keys"):
            held = facts.get(ck)
            if isinstance(held, (list, tuple, set)):
                out[ck] = [k for k in held
                           if k not in LAYER_FACTS and k not in LAYER_LIST_FACTS]
    me = _record_summary(slot, _slot_limit(facts, slots, idx, key))
    other_docs: Set[str] = set()
    for i in range(len(slots)):
        if i != idx:
            other_docs |= _exclusive_docs(slots, i)
    out[MARKER_KEY] = {
        "key": key,
        "index": idx,
        "count": len(slots),
        **me,
        "below": below,
        # The declarations this layer's own questions may read (`layer_text`).
        "own_documents": sorted(_exclusive_docs(slots, idx) or _slot_sources(slot)),
        "other_layer_documents": sorted(other_docs),
        **_producer_marker(slot),
        **({"underlying_lines": underlying_lines,
            "base_underlying_policies": base_rows} if idx > 0 else {}),
    }
    return out


def applicable_underlying_lines(view: Any) -> List[str]:
    """The underlying lines an umbrella-family layer sits over - general
    liability, auto, employers liability - in that order: the ones
    `sqs_service.umbrella_underlying` calls applicable on `view` (the lowest
    layer's own schedule lists it, or the package carries it and the schedule
    does not exclude it; the stamping facts carry the flags). Brent, 23 Oct
    2026: "list the applicable underlying coverages - but do not automatically
    require all three". [] when the door cannot be read - nothing is listed."""
    if not isinstance(view, dict):
        return []
    try:
        from services.sqs_service import UMB_UNDERLYING_LINES, umbrella_underlying
        lines = umbrella_underlying(view, view)["lines"]
    except Exception as exc:                                  # noqa: BLE001
        logger.warning("umbrella_layers: applicable underlying lines unread - %s", exc)
        return []
    return [fam for fam, _label in UMB_UNDERLYING_LINES if (lines.get(fam) or {}).get("applicable")]


# ── the boxes a copy answers for itself (gap fill) ───────────────────────────
# ACORD 131 boxes that describe THE POLICY being applied for or ITS UNDERLYING
# schedule - each copy answers them from its own layer. Everything else on the
# form describes the INSURED (who they are, where they operate, exposures,
# losses, fleet, the underwriting questions) and is the same question on every
# copy, so it is asked once. Read off the form's own sections; a test walks the
# real schema so a field matching no rule fails the build.
_PRIVATE_PREFIXES: Tuple[str, ...] = (
    "Policy_", "Insurer_", "PriorCoverage_",
    "UnderlyingPolicy_", "UnderlyingCoverage_",
    "GeneralLiability_", "WorkersCompensationEmployersLiability_",
    "Vehicle_CombinedSingleLimit_", "Vehicle_BodilyInjury_", "Vehicle_PropertyDamage_",
    "ExcessUmbrella_OccurrenceIndicator", "ExcessUmbrella_ClaimsMadeIndicator",
    "ExcessUmbrella_VoluntaryIndicator", "ExcessUmbrella_Transactiontype_",
    "ExcessUmbrella_ProposedRetroactiveDate", "ExcessUmbrella_CurrentRetroactiveDate",
    "ExcessUmbrella_Umbrella_", "ExcessUmbrella_OtherCoverage",
    "ExcessUmbrella_FirstDollarDefenceCode", "ExcessUmbrella_EmployeeBenefits_",
    "ExcessUmbrella_UninsuredMotorists_", "ExcessUmbrella_UnderinsuredMotorists_",
    "ExcessUmbrella_MedicalPayments_", "ExcessUmbrella_InsurerLetterCode",
    # Defense costs within / separate from / unlimited by the limits: a term of
    # the policy, not a fact about the insured.
    "CommercialUmbrellaLineOfBusiness_Question_ACB",
    "CommercialUmbrellaLineOfBusiness_Question_ACC",
    "CommercialUmbrellaLineOfBusiness_Question_ACD",
)
_SHARED_PREFIXES: Tuple[str, ...] = (
    "Form_", "Producer_", "NamedInsured_", "CommercialStructure_", "BusinessInformation_",
    "LossHistory_", "CareCustodyAndControl_", "VehicleFleet_", "AdvertisersLiability_",
    "Contractors_", "Watercraft_", "CommercialUmbrellaLineOfBusiness_",
    "ExcessUmbrella_EmployersLiability_", "ExcessUmbrella_MalpracticeLiability_",
    "ExcessUmbrella_PollutionLiability_", "ExcessUmbrella_ProductLiability_",
    "ExcessUmbrella_ProtectiveLiability_", "ExcessUmbrella_PropertyRating_",
)


# The UNDERLYING lines' own blocks (Brent, 23 Oct 2026, Z34-1 #3: "list the
# applicable underlying coverages"): the General Liability, Automobile and
# Employers Liability policies every layer of a tower sits over. Each copy
# prints them the way the plain 131 does (`pdf_service._upper_layer_
# underlying_line_box`), so they are SHARED boxes - one gap-fill answer for
# every copy, never one per layer's own documents. The OTHER POLICY rows, the
# rest of the checklist and the expiring-policy box stay private.
UNDERLYING_LINE_BLOCKS: Tuple[Tuple["re.Pattern", str], ...] = (
    (re.compile(r"^(?:UnderlyingPolicy_GeneralLiability_|GeneralLiability_|"
                r"UnderlyingCoverage_Coverage_GeneralLiability)"), "general_liab"),
    (re.compile(r"^(?:UnderlyingPolicy_Automobile_|"
                r"Vehicle_(?:CombinedSingleLimit|BodilyInjury|PropertyDamage)_|"
                r"UnderlyingCoverage_Coverage_AnyAutoIndicator_)"), "auto"),
    (re.compile(r"^(?:UnderlyingPolicy_EmployersLiability_|"
                r"WorkersCompensationEmployersLiability_)"), "workers_comp"),
)


def underlying_line_family(field: Any) -> Optional[str]:
    """"general_liab" / "auto" / "workers_comp" for a box of that underlying
    line's own 131 block, else None."""
    f = str(field or "")
    for rx, fam in UNDERLYING_LINE_BLOCKS:
        if rx.match(f):
            return fam
    return None


def field_rule(field: str) -> Optional[str]:
    """"private" / "shared" by the declared tables, or None (no rule)."""
    f = str(field or "")
    if underlying_line_family(f):
        return "shared"
    if any(f.startswith(p) for p in _PRIVATE_PREFIXES):
        return "private"
    if any(f.startswith(p) for p in _SHARED_PREFIXES):
        return "shared"
    return None


def is_private_field(field: str) -> bool:
    """True for a 131 box only its own layer may answer; an unknown box is
    private (never share an answer that cannot be vouched for)."""
    return field_rule(field) != "shared"


# ── the text a copy's own questions read ──────────────────────────────────────

def layer_text(docs: Any, facts: dict, form_id: str) -> Optional[str]:
    """The lowest layer reads the package without the upper layers' own
    declarations; an upper layer reads only its own declarations ("" when it
    has none - its private boxes then stay blank). None when there is no tower.
    `facts`: the package facts or the copy's own view (its marker carries the
    documents, so both give one answer)."""
    if not isinstance(facts, dict):
        return None
    m = facts.get(MARKER_KEY)
    if not isinstance(m, dict):
        view = layer_view(facts, fi.instance_key(form_id) or "")
        if view is facts:
            return None
        m = view.get(MARKER_KEY) or {}
    if m.get("missing") or m.get("index") is None:
        return ""
    active = [d for d in (docs or []) if isinstance(d, dict) and not d.get("excluded")] \
        or [d for d in (docs or []) if isinstance(d, dict)]
    if m.get("index") == 0:
        upper = set(m.get("other_layer_documents") or ())
        return " ".join(str(d.get("text") or "") for d in active if _doc_name(d) not in upper)
    own = set(m.get("own_documents") or ())
    return " ".join(str(d.get("text") or "") for d in active if _doc_name(d) in own)


# ── follow form belongs to the layer whose own document states it (Z37 B) ──

def upper_layer_documents(facts: Any) -> Set[str]:
    """The documents that belong ONLY to a layer above the umbrella, on a tower
    whose lowest layer is the umbrella; empty otherwise. "Follow Form Excess
    Liability Policy" on such a document describes the excess layer, never
    the umbrella (Choice Electric X4)."""
    try:
        slots = _all_slots(facts)
        if len(slots) < 2 or slots[0]["layer"] != UMBRELLA_LAYER:
            return set()
        out: Set[str] = set()
        for i in range(1, len(slots)):
            out |= _exclusive_docs(slots, i)
        return out - _slot_sources(slots[0])
    except Exception as exc:                                  # noqa: BLE001
        logger.warning("umbrella_layers: upper layer documents unread: %s", exc)
        return set()


def settle_umbrella_follow_form(mf: dict) -> bool:
    """On a tower whose lowest layer is the umbrella, the package's
    `umbrella_follow_form` is the umbrella's OWN documents' value: a value
    only an upper (excess) layer's document prints is dropped (it stays in
    that layer's `facts[DOCS_KEY]` entry for its own 131). A person's answer
    is never touched. Returns True when it changed the fact. Never raises."""
    key = "umbrella_follow_form"
    try:
        if not isinstance(mf, dict) or not upper_layer_documents(mf):
            return False
        held = mf.get(key)
        if not _has(_val(held)) or _person_sourced(held):
            return False
        settled = _base_value(mf, _all_slots(mf), key, person_ok=True)
        if settled is held:
            return False
        if settled is None or not _has(_val(settled)):
            mf.pop(key, None)
        else:
            mf[key] = settled
        return True
    except Exception as exc:                                  # noqa: BLE001
        logger.warning("umbrella_layers: follow form not settled: %s", exc)
        return False


# ── merge time: each layer document's own values ─────────────────────────────

def record_layer_evidence(mf: dict, docs: Any) -> List[str]:
    """Record, on a tower only, the layer facts each umbrella-family document
    prints (`facts[DOCS_KEY]`). Called at the merge tail, after the line
    records exist. Returns the documents recorded. Never raises."""
    try:
        if not isinstance(mf, dict):
            return []
        if len(ordered_layers(mf)) < 2:
            mf.pop(DOCS_KEY, None)
            return []
        wanted: Set[str] = set()
        for rec in _umbrella_records(mf):
            wanted |= {str(n).strip() for n in (rec.get("sources") or []) if str(n or "").strip()}
        store: Dict[str, dict] = {}
        for d in docs or []:
            name = _doc_name(d)
            if not name:
                continue
            dfacts = d.get("facts") or {}
            rows = _val(dfacts.get("coverage_lines"))
            prints_family = isinstance(rows, list) and any(
                isinstance(r, dict) and _row_layer(r) for r in rows)
            if name not in wanted and not prints_family:
                continue
            got = {}
            for k in LAYER_FACTS + LAYER_LIST_FACTS:
                held = dfacts.get(k)
                if _has(_val(held)):
                    got[k] = copy.deepcopy(held)
            store[name] = got
        if store:
            mf[DOCS_KEY] = store
        else:
            mf.pop(DOCS_KEY, None)
        return sorted(store)
    except Exception as exc:                                  # noqa: BLE001
        logger.warning("umbrella_layers: layer evidence not recorded: %s", exc)
        return []


# ── the recommendation ───────────────────────────────────────────────────────

def _layer_name(slots: List[dict], index: int) -> str:
    """"umbrella", "excess layer", "excess layer 2", ... (lower case)."""
    if slots[index]["layer"] == UMBRELLA_LAYER:
        return "umbrella"
    nth = sum(1 for s in slots[:index + 1] if s["layer"] == EXCESS_LAYER)
    return "excess layer" if nth == 1 else f"excess layer {nth}"


def recommendation_layers(facts: Any) -> List[dict]:
    """One entry per layer, in attachment order: the form id its copy is (or
    will be) generated as - a bound copy's own id, a new layer's next free one
    - and the plain words a producer is shown. [] when the package has one
    layer held by the plain 131 (or none): the one recommendation as before."""
    slots, assign = _assign(facts)
    keys = _keys_by_index(assign)
    if not slots or (len(slots) < 2 and keys.get(0) == ""):
        return []
    out: List[dict] = []
    for i, slot in enumerate(slots):
        key = keys.get(i)
        if key is None:
            continue
        rec = slot.get("record") or {}
        carrier = str(rec.get("carrier_name") or "").strip()
        name = _layer_name(slots, i)
        word = "Umbrella layer" if name == "umbrella" else name[:1].upper() + name[1:]
        if i > 0:
            word = f"{word} above the {_layer_name(slots, i - 1)}"
        out.append({
            "form_id": BASE if key == "" else fi.make_instance_id(BASE, key),
            "key": key,
            "index": i,
            "layer": slot["layer"],
            "carrier": carrier or None,
            "reason": f"{word} - {carrier}" if carrier else word,
        })
    return out


# ── registration ─────────────────────────────────────────────────────────────

fi.register_overlay(
    BASE, layer_view,
    instances=instance_keys,
    private_field=is_private_field,
    text_scope=layer_text,
    binder=bind_layers,
    binding_keys=(BINDINGS_KEY,),
)
