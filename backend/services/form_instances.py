"""Form INSTANCES - one ACORD form generated more than once in a package (7 Oct 2026).

Brent (Choice Electric #4): "When we have an umbrella base with excess on top of
it, each gets their own form 131." Until now a package held at most ONE copy of
each ACORD form, keyed by its form id ("ACORD_131") everywhere: the session's
`generated_forms`, `selected_form_ids`, `session_pdf_bytes`, the scorer, field QA,
downloads and the frontend.

THE RULE (one door, so no caller invents its own):
  * An INSTANCE id is "<base>__<key>", e.g. "ACORD_131__excess",
    "ACORD_131__excess-2". No base id contains "__" (checked against every
    schema / template file), so the split is unambiguous.
  * Everything that STORES or SHOWS a form uses the instance id (storage keys,
    selection, form order, labels, download file names).
  * Everything that LOADS A FILE or KEYS A RULE by form uses `base_form_id()`:
    schemas, templates, alias maps, edition ids, form-specific resolvers, the
    per-form scorer's rule set. Internals therefore keep seeing "ACORD_131".
  * What makes an instance different is its FACTS: `facts_for_form(facts, fid)`
    returns the facts an instance is stamped / scored / checked from (the excess
    layer's carrier, limits, premium and underlying for "ACORD_131__excess").
    A plain form id returns `facts` unchanged (same object), so every existing
    path is byte-identical - unless its provider narrows the plain copy too
    (ACORD 131 on a package with an umbrella AND an excess prints only the
    lowest layer); a provider returns the same object whenever nothing differs.
  * Two copies of one form share every FIELD NAME. A box that describes the
    copy's own subject (`is_private_field`) never takes another copy's answer:
    the shared gap fill asks it separately, on that copy's own facts and text.

Pure and dependency-free except the registered overlay providers
(`services.umbrella_layers` registers ACORD 131's).
"""
from __future__ import annotations

import re
from typing import Any, Callable, Dict, List, Optional, Tuple

SEPARATOR = "__"
_KEY_RE = re.compile(r"^[a-z][a-z0-9-]{0,31}$")

# key prefix -> human label word ("excess" -> "Excess", "excess-2" -> "Excess 2").
_LABEL_WORDS: Dict[str, str] = {"excess": "Excess"}

# base form id -> overlay provider(facts, instance_key) -> facts for that instance.
_OVERLAYS: Dict[str, Callable[[dict, str], dict]] = {}


def is_instance(form_id: Any) -> bool:
    """True for "<base>__<key>" with a well-formed key."""
    s = str(form_id or "")
    if SEPARATOR not in s:
        return False
    base, _, key = s.partition(SEPARATOR)
    return bool(base) and bool(_KEY_RE.match(key))


def base_form_id(form_id: Any) -> str:
    """The ACORD form an id renders: "ACORD_131__excess" -> "ACORD_131".
    A plain id (or anything that is not a well-formed instance) is returned
    as-is, so callers can apply it unconditionally."""
    s = str(form_id or "")
    return s.partition(SEPARATOR)[0] if is_instance(s) else s


def instance_key(form_id: Any) -> Optional[str]:
    """"ACORD_131__excess" -> "excess"; a plain id -> None."""
    s = str(form_id or "")
    return s.partition(SEPARATOR)[2] if is_instance(s) else None


def make_instance_id(base: str, key: str) -> str:
    """Build an instance id; raises ValueError on a malformed key or a base
    that already is an instance (no nesting)."""
    if not base or SEPARATOR in base:
        raise ValueError(f"not a base form id: {base!r}")
    if not _KEY_RE.match(str(key or "")):
        raise ValueError(f"not an instance key: {key!r}")
    return f"{base}{SEPARATOR}{key}"


def instance_label(form_id: Any) -> str:
    """Display label: "ACORD_131" -> "ACORD 131"; "ACORD_131__excess" ->
    "ACORD 131 (Excess)"; "ACORD_131__excess-2" -> "ACORD 131 (Excess 2)"."""
    base = base_form_id(form_id).replace("_", " ").strip()
    key = instance_key(form_id)
    if not key:
        return base
    stem, _, num = key.partition("-")
    word = _LABEL_WORDS.get(stem, stem.replace("-", " ").title())
    return f"{base} ({word}{' ' + num if num else ''})"


def file_stem(form_id: Any) -> str:
    """A download file stem: "ACORD_131__excess" -> "ACORD_131_Excess"."""
    key = instance_key(form_id)
    base = base_form_id(form_id)
    if not key:
        return base
    stem, _, num = key.partition("-")
    word = _LABEL_WORDS.get(stem, stem.title())
    return f"{base}_{word}{num}"


def register_overlay(base: str, provider: Callable[[dict, str], dict], *,
                     instances: Optional[Callable[[dict], List[str]]] = None,
                     private_field: Optional[Callable[[str], bool]] = None,
                     text_scope: Optional[Callable[[Any, dict, str], Optional[str]]] = None,
                     binder: Optional[Callable[[dict, List[str]], Optional[dict]]] = None,
                     binding_keys: Tuple[str, ...] = (),
                     ) -> None:
    """Register the facts overlay for instances of `base` (one per base).

    `provider(facts, key)` -> the facts the form is stamped from. It is asked
    for the PLAIN id too (key ""), and must return `facts` itself (the same
    object) whenever nothing differs - that is what keeps every package
    without instances byte-identical. A view it returns is a COPY, never
    persisted, and final: asked again about a view it returns the view.
    Optional (7 Oct 2026, LAYERS):
      instances(facts)       -> the instance KEYS this package really has, in order;
      private_field(field)   -> True for a box that describes THIS copy's own
                                subject (its policy), never shared with another copy;
      text_scope(docs, facts, form_id) -> the document text that copy's private
                                questions may read (None = the whole package).
    Optional (7 Oct 2026, round 2 - a generated copy keeps its subject):
      binder(facts, form_ids) -> {private fact: value} binding each copy in
                                `form_ids` to the subject it was generated for,
                                or None; written with the generated forms
                                (`binding_update`) and carried across re-merges
                                (`carry_bindings`);
      binding_keys            -> the private fact keys the binder writes."""
    _OVERLAYS[base] = provider
    if instances is not None:
        _INSTANCE_LISTERS[base] = instances
    if private_field is not None:
        _PRIVATE_FIELDS[base] = private_field
    if text_scope is not None:
        _TEXT_SCOPES[base] = text_scope
    if binder is not None:
        _BINDERS[base] = binder
    if binding_keys:
        _BINDING_KEYS[base] = tuple(str(k) for k in binding_keys)


# base -> facts -> [instance keys]; base -> field -> private?; base -> text scope;
# base -> binder; base -> the private fact keys its binder writes.
_INSTANCE_LISTERS: Dict[str, Callable[[dict], List[str]]] = {}
_PRIVATE_FIELDS: Dict[str, Callable[[str], bool]] = {}
_TEXT_SCOPES: Dict[str, Callable[[Any, dict, str], Optional[str]]] = {}
_BINDERS: Dict[str, Callable[[dict, List[str]], Optional[dict]]] = {}
_BINDING_KEYS: Dict[str, Tuple[str, ...]] = {}

# The modules that register overlays, imported on first use so no caller depends
# on import order (a route that never imported them still gets the views).
_PROVIDER_MODULES = ("services.umbrella_layers",)
_PROVIDERS_LOADED = False


def _ensure_providers() -> None:
    global _PROVIDERS_LOADED
    if _PROVIDERS_LOADED:
        return
    _PROVIDERS_LOADED = True
    import importlib
    for name in _PROVIDER_MODULES:
        try:
            importlib.import_module(name)
        except Exception:                                     # noqa: BLE001
            pass


def facts_for_form(facts: Any, form_id: Any) -> Any:
    """The facts a form id is stamped / scored / checked from.

    Plain form id -> `facts` itself (same object; nothing changes for every
    existing path) - unless the form's registered provider has a view of the
    plain copy too (ACORD 131 of a package with an umbrella AND an excess
    layer prints only the lowest layer). Instance id -> the registered
    overlay's result for its key; an unknown base or a provider error returns
    `facts` unchanged rather than inventing an instance (callers never get
    None)."""
    if not isinstance(facts, dict):
        return facts
    _ensure_providers()
    provider = _OVERLAYS.get(base_form_id(form_id))
    if provider is None:
        return facts
    try:
        out = provider(facts, instance_key(form_id) or "")
    except Exception:                                         # noqa: BLE001
        return facts
    return out if isinstance(out, dict) else facts


def has_own_view(facts: Any, form_id: Any) -> bool:
    """True when this form is stamped from facts other than the package's
    (an instance, or a plain copy its provider narrows)."""
    return isinstance(facts, dict) and facts_for_form(facts, form_id) is not facts


def base_form_ids(form_ids: Any) -> List[str]:
    """The base forms of a list of ids, de-duplicated, order kept - for every
    rule keyed by form ("is ACORD 131 in this package?")."""
    out: List[str] = []
    if isinstance(form_ids, (str, bytes)) or form_ids is None:
        form_ids = [form_ids] if form_ids else []
    for f in form_ids:
        if isinstance(f, dict):
            f = f.get("form_id")
        b = base_form_id(f)
        if b and b not in out:
            out.append(b)
    return out


def instance_ids(facts: Any, base: Optional[str] = None) -> List[str]:
    """The instance ids this package really has (all bases, or one), in the
    provider's order. A package with none returns []."""
    _ensure_providers()
    out: List[str] = []
    if not isinstance(facts, dict):
        return out
    for b, lister in list(_INSTANCE_LISTERS.items()):
        if base and b != base_form_id(base):
            continue
        try:
            keys = lister(facts) or []
        except Exception:                                     # noqa: BLE001
            keys = []
        for k in keys:
            try:
                out.append(make_instance_id(b, k))
            except ValueError:
                continue
    return out


def is_valid_form_id(facts: Any, form_id: Any) -> bool:
    """A plain id is always valid; an instance only while its package still has
    it (a stale tab can send an instance whose layer has since gone)."""
    if not is_instance(form_id):
        return bool(str(form_id or "").strip())
    return str(form_id) in instance_ids(facts, base_form_id(form_id))


def is_private_field(form_id: Any, field: Any) -> bool:
    """True when `field` on this form describes the copy's own subject and must
    never take another copy's answer (see `register_overlay`)."""
    _ensure_providers()
    pred = _PRIVATE_FIELDS.get(base_form_id(form_id))
    if pred is None:
        return False
    try:
        return bool(pred(str(field or "")))
    except Exception:                                         # noqa: BLE001
        return True                     # cannot tell: never share


def scoped_text(docs: Any, facts: Any, form_id: Any) -> Optional[str]:
    """The text a copy's private questions read, or None (the whole package)."""
    _ensure_providers()
    fn = _TEXT_SCOPES.get(base_form_id(form_id))
    if fn is None or not isinstance(facts, dict):
        return None
    try:
        return fn(docs, facts, str(form_id or ""))
    except Exception:                                         # noqa: BLE001
        return None


def instance_form_name(base_name: Any, form_id: Any) -> str:
    """"ACORD 131 - Umbrella ..." for "ACORD_131__excess" ->
    "ACORD 131 (Excess) - Umbrella ..."; a plain id keeps its name."""
    name = str(base_name or "").strip()
    if not is_instance(form_id):
        return name
    base_label = instance_label(base_form_id(form_id))
    label = instance_label(form_id)
    if name.startswith(base_label):
        return label + name[len(base_label):]
    return f"{label} - {name}" if name else label


def form_meta_for(all_forms: Any, form_id: Any, facts: Any = None) -> Optional[dict]:
    """The metadata row a form id is generated from.

    Plain id -> its own row from `all_forms` (the same object, as every
    generation path always read it). Instance id -> a COPY of its base's row
    carrying the instance id and name (the template, schema and rules stay the
    base's); None when the base is unknown or - `facts` given - the package no
    longer has that instance."""
    fid = str(form_id or "").strip()
    if not fid:
        return None
    base = base_form_id(fid)
    row = next((f for f in (all_forms or [])
                if isinstance(f, dict) and f.get("form_id") == base), None)
    if row is None or not is_instance(fid):
        return row
    if facts is not None and not is_valid_form_id(facts, fid):
        return None
    out = dict(row)
    out["form_id"] = fid
    out["form_name"] = instance_form_name(row.get("form_name") or base, fid)
    out["base_form_id"] = base
    out["instance_key"] = instance_key(fid)
    return out


def session_for_form(session: Any, form_id: Any) -> Any:
    """The session as a session-reading door should see it for this form: the
    session itself, or a shallow copy whose `facts` is the form's own view."""
    if not isinstance(session, dict):
        return session
    facts = session.get("facts")
    view = facts_for_form(facts, form_id)
    return session if view is facts else {**session, "facts": view}


# ── A generated copy keeps its subject (7 Oct 2026, round 2) ──────────────────
# An instance id is a key into the package's CURRENT subjects (the umbrella
# tower's layers). Without a binding a subject arriving later (a lower excess
# layer uploaded after generation) re-orders them and re-points an existing
# copy - with its person-typed boxes - at another policy. Every write that
# STORES generated copies binds them in the same write (`binding_update`); every
# re-merge carries the binding (`carry_bindings`); the provider honours it.

def bind_copies(facts: Any, form_ids: Any) -> dict:
    """{private fact: value} binding each copy in `form_ids` to the subject it
    is generated for ({} when nothing new binds). Applied to `facts` in place,
    so the rest of the request reads the same binding the write stores."""
    _ensure_providers()
    if not isinstance(facts, dict):
        return {}
    ids: List[str] = []
    for f in (form_ids or []):
        f = str((f.get("form_id") if isinstance(f, dict) else f) or "").strip()
        if f and f not in ids:
            ids.append(f)
    out: dict = {}
    for base, binder in list(_BINDERS.items()):
        mine = [f for f in ids if base_form_id(f) == base]
        if not mine:
            continue
        try:
            got = binder(facts, mine) or {}
        except Exception:                                     # noqa: BLE001
            got = {}
        for k, v in got.items():
            facts[k] = v
            out[k] = v
    return out


def binding_update(facts: Any, form_ids: Any) -> dict:
    """The session-update fragment that stores `bind_copies` beside the
    generated forms: {"facts": {...}} (an additive facts write), or {}."""
    got = bind_copies(facts, form_ids)
    return {"facts": got} if got else {}


def carry_bindings(merged: Any, prior: Any) -> List[str]:
    """Carry every stored binding into freshly merged facts (no document states
    one). Returns the keys carried. A binding already in `merged` is kept."""
    _ensure_providers()
    if not isinstance(merged, dict) or not isinstance(prior, dict):
        return []
    carried: List[str] = []
    for keys in list(_BINDING_KEYS.values()):
        for k in keys:
            if k in prior and k not in merged and prior.get(k):
                merged[k] = prior[k]
                carried.append(k)
    return carried
