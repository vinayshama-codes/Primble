"""Build the ACORD box -> fact map by PROBING our own stamper (27 Oct 2026).

Why probe instead of reversing the fill rules: the rule tables map only a small
share of each form (ACORD 125: 24 rule boxes + 119 table cells of 548) - most
boxes are filled by resolver functions, which cannot be reversed by reading
them. So every fact gets a unique MARKER value of its own shape, the forms are
stamped with no model call (`form_dry_run._pass1_value`, the documented mirror
of the stamper's deterministic passes), and each box that prints a marker is
mapped back to the fact, part or table cell the marker came from. Yes / No and
choice facts tick a box rather than print a value, so they are found by
stamping each option against a baseline and seeing which box turns on.

A box no fact prints (Y/N questions, form-only details) gets no entry: an
uploaded value there is carried box-to-box (see services/acord_intake).

Output: backend/forms_reverse/acord_reverse_map.json, keyed by form, each with
its schema hash. Re-run whenever the stamper or a schema changes; the test
`test_acord_intake` fails when a stored hash no longer matches its schema.

    cd backend && .venv/bin/python scripts/build_acord_reverse_map.py [FORM_ID ...]
"""
import datetime
import hashlib
import json
import logging
import os
import re
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
logging.disable(logging.WARNING)

from services import form_dry_run as dr                    # noqa: E402
from services import pdf_service as ps                     # noqa: E402
from services.acord_intake.reverse_map import MAP_PATH, MAP_VERSION, schema_hash  # noqa: E402
from services.answer_options import OTHER, options_for     # noqa: E402
from services.answer_semantics import _declared_kind       # noqa: E402
from services.fact_registry import FACT_REGISTRY           # noqa: E402

BACKEND = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STATES = ["AL", "AK", "AZ", "AR", "CT", "DE", "FL", "GA", "HI", "ID", "IL", "IN", "IA", "KS", "KY", "LA",
          "ME", "MD", "MA", "MI", "MN", "MS", "MO", "MT", "NE", "NV", "NH", "NJ", "NM", "NY", "NC", "ND"]
# The per-line record families a section form reads its header from.
LINE_NAMES = ["Commercial General Liability", "Business Auto", "Workers Compensation and Employers Liability",
              "Commercial Umbrella", "Commercial Property", "Inland Marine", "Crime", "Cyber Liability",
              "Employment Practices Liability"]
LINE_COLS = ["carrier", "naic", "policy_number", "effective_date", "expiration_date", "premium", "limit"]
DATE_COLS = {"date", "claim_date", "dob", "hire_date", "effective", "expiration", "effective_date",
             "expiration_date", "first_made_date"}
MONEY_COLS = {"paid", "reserved_amount", "amount", "payroll", "premium", "remuneration", "building_value",
              "bpp_value", "annual_revenue", "exposure_amount", "limit", "value", "expense", "incurred",
              "cost_new", "stated_amount"}
NUM_COLS = {"full_time_employees", "part_time_employees", "experience_years", "total_building_area",
            "occupied_area", "open_to_public_area", "gvw", "ownership_pct", "vehicle_use_percent"}
YEAR_COLS = {"year", "year_built", "roof_year"}
SKIP_COLS = {None, "None", "_wc_never", "_wc_sheet_state", "_wc_stated_premium", "include", "exclude",
             "is_inside_city_limits", "is_other_city_limits", "is_outside_city_limits", "is_owner",
             "is_tenant", "is_other_interest", "open", "address"}


class Markers:
    """Unique, shape-correct marker values and the reader that finds them again."""

    def __init__(self):
        self.text = {}      # token -> target
        self.digits = {}    # digit string -> target
        self.dates = {}     # iso -> target
        self.n = 0

    def _next(self):
        self.n += 1
        return self.n

    def for_scalar(self, key, kind):
        i = self._next()
        low = key.lower()
        tgt = {"t": "fact", "fact": key, "part": "whole"}
        if kind == "date":
            d = datetime.date(2031, 1, 1) + datetime.timedelta(days=3 * i)
            self.dates[d.isoformat()] = tgt
            return d.strftime("%m/%d/%Y")
        if kind in ("currency", "amount_or_percent"):
            v = 7100000 + 1013 * i
            self.digits[str(v)] = tgt
            return f"${v:,}"
        if kind == "integer":
            v = 4000 + 7 * i
            self.digits[str(v)] = tgt
            return str(v)
        if kind == "percent":
            return None                          # 1-100: too few markers to be unique; mapped by ticks/routes
        if "address" in low:
            st = STATES[i % len(STATES)]
            self.text[f"qza{i}x"] = {**tgt, "part": "line1"}
            self.text[f"qzc{i}x"] = {**tgt, "part": "city"}
            self.digits[str(60000 + i)] = {**tgt, "part": "zip"}
            return f"{100 + i} Qza{i}x Street, Qzc{i}x, {st} {60000 + i}"
        if "email" in low:
            self.text[f"qz{i}x@probe.io"] = tgt
            return f"qz{i}x@probe.io"
        if "phone" in low or "fax" in low:
            v = f"720555{1000 + i:04d}"
            self.digits[v] = tgt
            return f"720-555-{1000 + i:04d}"
        if "website" in low:
            self.text[f"qz{i}x"] = tgt
            return f"www.qz{i}x.com"
        if "naics" in low:
            v = f"23{8000 + i}"[:6]
            self.digits[v] = tgt
            return v
        if low.endswith("fein") or low == "fein" or "tax_id" in low:
            v = f"{10 + i % 80:02d}{7000000 + i:07d}"
            self.digits[v] = tgt
            return f"{v[:2]}-{v[2:]}"
        if "naic" in low:
            v = f"9{i:04d}"
            self.digits[v] = tgt
            return v
        if "policy_number" in low or low.endswith("_policy_no"):
            self.text[f"qzp{i}x"] = tgt
            return f"QZP{i}X-{i:04d}"
        if kind == "code":
            self.text[f"q{i}c"] = tgt
            return f"Q{i}C"
        self.text[f"qzt{i}x"] = tgt
        return f"Qzt{i}x Probe"

    def for_cell(self, list_key, row, col, extra=None):
        i = self._next()
        tgt = {"t": "cell", "list": list_key, "row": row, "col": col, **(extra or {})}
        if col in DATE_COLS:
            d = datetime.date(2001, 1, 1) + datetime.timedelta(days=5 * i)
            self.dates[d.isoformat()] = tgt
            return d.strftime("%m/%d/%Y")
        if col in YEAR_COLS:
            return None                          # years collide (1900-2030); routes cover them
        if col in MONEY_COLS:
            v = 5300000 + 1009 * i
            self.digits[str(v)] = tgt
            return f"${v:,}"
        if col in NUM_COLS:
            v = 3000 + 11 * i
            self.digits[str(v)] = tgt
            return str(v)
        if col in ("state", "license_state", "address_state", "garaging_state"):
            return STATES[i % len(STATES)]       # not uniquely readable; routes / ticks cover it
        if col in ("vin",):
            v = f"1QZ{i:05d}ABC{i:06d}"[:17]
            self.text[v.lower()] = tgt
            return v
        if col in ("address_zip", "garaging_zip", "zip"):
            v = str(50000 + i)
            self.digits[v] = tgt
            return v
        if col in ("naic",):
            v = f"8{i:04d}"
            self.digits[v] = tgt
            return v
        self.text[f"qzl{i}x"] = tgt
        return f"Qzl{i}x Cell"

    def read(self, value):
        """Every target whose marker the printed value carries."""
        s = str(value or "")
        low = s.lower()
        digits = re.sub(r"\D", "", s)
        hits = []
        for tok, tgt in self.text.items():
            if tok in low:
                hits.append(tgt)
        for d, tgt in self.digits.items():
            if d and re.search(rf"(?<!\d){d}(?!\d)", digits if len(d) > 6 else re.sub(r"[,$]", "", s)):
                hits.append(tgt)
        if not hits:
            try:
                from services.normalization import normalize_date
                iso = normalize_date(s)
                if iso and iso in self.dates:
                    hits.append(self.dates[iso])
            except Exception:
                pass
        out = []
        for h in hits:
            if h not in out:
                out.append(h)
        return out


def probe_context():
    """Facts + flags shaped like a full real package, every value a marker."""
    mk = Markers()
    facts = {}
    for key, entry in FACT_REGISTRY.items():
        try:
            kind = _declared_kind(key, entry)
        except Exception:
            kind = None
        if options_for(key):
            continue                              # ticks: probed separately
        v = mk.for_scalar(key, kind)
        if v is not None:
            facts[key] = v
    cols = {}
    for base, d in ps._SCHEDULE_REGISTRY.items():
        cols.setdefault(d.list_key, set()).add(d.sub_key)
    try:
        from services.schedule_capture import SCHEDULE_DEFS
        for lk, spec in SCHEDULE_DEFS.items():
            for c in spec.get("columns") or []:
                cols.setdefault(lk, set()).add(c.get("key"))
    except Exception:
        pass
    for lk, cset in cols.items():
        if lk in ("auto_garaging_addresses", "additional_named_insureds"):
            facts[lk] = [mk.for_scalar(f"{lk}#{r}", None) for r in range(3)]
            continue
        rows = []
        for r in range(4):
            row = {}
            for c in sorted(x for x in cset if x not in SKIP_COLS):
                v = mk.for_cell(lk, r, c)
                if v is not None:
                    row[c] = v
            if lk == "loss_history":
                row.setdefault("line_of_business", "Workers Compensation")
            rows.append(row)
        facts[lk] = rows
    lines = []
    for name in LINE_NAMES:
        row = {"line": name}
        for c in LINE_COLS:
            v = mk.for_cell("coverage_lines", None, c, {"line": name})
            if v is not None:
                row[c] = v
        lines.append(row)
    facts["coverage_lines"] = lines
    flags = {k: True for k in ("has_general_liability", "has_auto_coverage", "has_commercial_auto",
                               "has_auto_liability", "has_workers_comp", "has_umbrella",
                               "has_property_coverage", "has_inland_marine", "has_crime", "has_cyber",
                               "has_loss_history", "has_multiple_locations", "is_contractor")}
    return facts, flags, mk


def _on(v):
    """A tick that is ON. A fillable ACORD prints "No" in the boxes it leaves
    unticked, so "No" / "Off" / blank are all off."""
    if isinstance(v, bool):
        return v
    return str(v or "").strip().lower() in ("yes", "y", "on", "x", "1", "true", "ticked")


def build_form(fid, facts, flags, mk):
    from config.settings import TEMPLATE_DIR
    schema = ps.extract_form_schema(os.path.join(TEMPLATE_DIR, f"{fid}.pdf"), fid)
    stamp = {**facts, **flags, "_package_form_ids": [fid]}
    boxes = {}
    for f in schema:
        try:
            v = dr._pass1_value(fid, schema, f, stamp)
        except Exception:
            v = None
        if v in (None, "", "Off"):
            continue
        hits = mk.read(v)
        if hits:
            boxes[f] = hits
    # Ticks: a choice fact's option turns a box on.
    btn = [f for f, meta in schema.items() if (meta or {}).get("ft") == "/Btn"]
    if btn:
        base_on = {}
        for f in btn:
            try:
                base_on[f] = dr._pass1_value(fid, schema, f, stamp)
            except Exception:
                base_on[f] = None
        for key in FACT_REGISTRY:
            opts = [o for o in (options_for(key) or []) if o and o != OTHER]
            for o in opts[:16]:
                probe = {**stamp, key: [o] if key == "lines_of_business" else o}
                for f in btn:
                    try:
                        v = dr._pass1_value(fid, schema, f, probe)
                    except Exception:
                        v = None
                    if _on(v) and not _on(base_on.get(f)):
                        tgt = {"t": "tick", "fact": key, "value": o}
                        boxes.setdefault(f, [])
                        if tgt not in boxes[f]:
                            boxes[f].append(tgt)
    return {"schema_sha": schema_hash(schema), "boxes": boxes}


def main(argv):
    forms = argv or sorted(fn[:-4] for fn in os.listdir(os.path.join(BACKEND, "templates")) if fn.endswith(".pdf"))
    facts, flags, mk = probe_context()
    try:
        out = json.load(open(MAP_PATH))
    except Exception:
        out = {}
    if out.get("version") != MAP_VERSION:
        out = {"version": MAP_VERSION, "forms": {}}
    for fid in forms:
        t = time.time()
        out["forms"][fid] = build_form(fid, facts, flags, mk)
        print(f"{fid}: {len(out['forms'][fid]['boxes'])} boxes mapped ({time.time() - t:.1f}s)", flush=True)
    os.makedirs(os.path.dirname(MAP_PATH), exist_ok=True)
    with open(MAP_PATH, "w") as fh:
        json.dump(out, fh, indent=0, sort_keys=True)
    print("wrote", MAP_PATH)


if __name__ == "__main__":
    main(sys.argv[1:])
