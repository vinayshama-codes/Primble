"""
Generate alias maps: form field name -> canonical fact name
One file per form: forms_schemas/ACORD_xxx_alias.json
Master list:        forms_schemas/_canonical_facts.json
"""

import json
import re
from collections import defaultdict
from pathlib import Path

SCHEMAS_DIR = Path(__file__).parent.parent / "forms_schemas"
OUTPUT_DIR  = Path(__file__).parent.parent / "forms_aliases"
OUTPUT_DIR.mkdir(exist_ok=True)


# ── Canonical name derivation ─────────────────────────────────────────────────

def pascal_to_snake(segment: str) -> str:
    """
    Convert a PascalCase or ALLCAPS segment to snake_case.
      NAICCode        -> naic_code
      FullName        -> full_name
      LineOfBusiness  -> line_of_business
      FEIN            -> fein
    """
    s = segment
    # Step 1: ALLCAPS run before Cap+lower  =>  insert _
    #   "NAICCode" -> "NAIC_Code"
    s = re.sub(r'([A-Z]+)([A-Z][a-z])', r'\1_\2', s)
    # Step 2: lower/digit before uppercase  =>  insert _
    #   "FullName" -> "Full_Name"
    s = re.sub(r'([a-z0-9])([A-Z])', r'\1_\2', s)
    return s.lower()


def field_to_canonical(field_name: str) -> str:
    """
    Convert an ACORD field name to a canonical snake_case fact key.

      Producer_FullName_A                      -> producer_full_name
      NamedInsured_FullName_B                  -> named_insured_full_name_b
      Policy_PolicyNumberIdentifier_A          -> policy_number_identifier
      Insurer_NAICCode_A                       -> insurer_naic_code
      Policy_LineOfBusiness_OtherIndicator_C   -> policy_line_of_business_other_indicator_c
      Construction_ConstructionCode_A          -> construction_code
    """
    # Detect trailing slot letter: single uppercase A-Z at the very end
    m = re.match(r'^(.+)_([A-Z])$', field_name)
    if m:
        base, slot = m.group(1), m.group(2)
        # Primary slot (_A) -> strip; secondary/tertiary -> append lowercase
        name = base if slot == 'A' else (base + '_' + slot.lower())
    else:
        name = field_name

    # Convert each underscore-delimited segment from PascalCase to snake_case
    parts     = name.split('_')
    converted = [pascal_to_snake(p) for p in parts if p]
    canonical = '_'.join(converted)

    # Remove any double underscores introduced during conversion
    canonical = re.sub(r'_+', '_', canonical).strip('_')

    # Remove immediate duplicate leading word
    #   policy_policy_number_identifier  -> policy_number_identifier
    #   construction_construction_code   -> construction_code
    sub = canonical.split('_')
    if len(sub) >= 2 and sub[0] == sub[1]:
        canonical = '_'.join(sub[1:])

    return canonical


# ── Load all schemas ──────────────────────────────────────────────────────────

schemas: dict = {}
for path in sorted(SCHEMAS_DIR.glob("*_schema.json")):
    if 'dummy' in path.name:
        continue
    form_id = path.stem.replace('_schema', '')
    schemas[form_id] = json.loads(path.read_text(encoding='utf-8'))

print(f"Loaded {len(schemas)} schemas")


# ── Build global canonical map ────────────────────────────────────────────────
# Same ACORD field name always maps to exactly one canonical across all forms.

global_canonical: dict = {}         # field_name  -> canonical_name
canonical_desc:   dict = {}         # canonical   -> best tu description
canonical_forms:  dict = defaultdict(list)  # canonical -> [form_ids]

for form_id, fields in schemas.items():
    for fname, meta in fields.items():
        if fname not in global_canonical:
            global_canonical[fname] = field_to_canonical(fname)

        canonical = global_canonical[fname]
        tu        = meta.get('tu', '').strip()
        canonical_forms[canonical].append(form_id)

        # Keep the longest / most descriptive tooltip
        if len(tu) > len(canonical_desc.get(canonical, '')):
            canonical_desc[canonical] = tu

print(f"Unique canonical fact names: {len(canonical_desc)}")


# ── Spot-check sample mappings ────────────────────────────────────────────────
EXPECTED = {
    'Producer_FullName_A':                       'producer_full_name',
    'NamedInsured_FullName_B':                   'named_insured_full_name_b',
    'Policy_PolicyNumberIdentifier_A':           'policy_number_identifier',
    'Policy_LineOfBusiness_OtherIndicator_C':    'policy_line_of_business_other_indicator_c',
    'Insurer_NAICCode_A':                        'insurer_naic_code',
    'Form_CompletionDate_A':                     'form_completion_date',
}

print("\nSample canonical mappings:")
for field, expected in EXPECTED.items():
    got    = global_canonical.get(field, '(not in any schema)')
    status = 'OK' if got == expected else 'MISMATCH'
    flag   = '' if got == expected else f'  expected: {expected}'
    print(f"  {status:<8}  {field:<55} -> {got}{flag}")

# Also verify the double-prefix fix
if 'Policy_PolicyNumberIdentifier_A' in global_canonical:
    val = global_canonical['Policy_PolicyNumberIdentifier_A']
    assert not val.startswith('policy_policy_'), f"Double prefix not fixed: {val}"


# ── Write one alias file per form ─────────────────────────────────────────────
print()
for form_id, fields in schemas.items():
    alias    = {fname: global_canonical[fname] for fname in fields}
    out_path = OUTPUT_DIR / f"{form_id}_alias.json"
    out_path.write_text(json.dumps(alias, indent=2), encoding='utf-8')
    print(f"  Wrote {out_path.name:<35}  ({len(alias)} fields)")


# ── Write master canonical facts list ─────────────────────────────────────────
master = {
    canonical: {
        "description": canonical_desc[canonical],
        "used_by_forms": sorted(set(canonical_forms[canonical]))
    }
    for canonical in sorted(canonical_desc)
}

master_path = OUTPUT_DIR / "_canonical_facts.json"
master_path.write_text(json.dumps(master, indent=2), encoding='utf-8')
print(f"\nWrote _canonical_facts.json  ({len(master)} canonical facts)")


# ── Sanity checks ─────────────────────────────────────────────────────────────
print("\nRunning sanity checks...")

# 1. Every field in every schema has a canonical mapping
total_fields = sum(len(v) for v in schemas.values())
total_mapped  = sum(
    len(json.loads((OUTPUT_DIR / f"{fid}_alias.json").read_text()))
    for fid in schemas
)
assert total_fields == total_mapped, \
    f"MISMATCH: {total_fields} fields but only {total_mapped} mapped"

# 2. No empty canonical names
empties = [f for f, c in global_canonical.items() if not c.strip()]
assert not empties, f"Empty canonicals for fields: {empties[:5]}"

# 3. No canonical starting or ending with underscore
bad_edge = [c for c in canonical_desc if c.startswith('_') or c.endswith('_')]
assert not bad_edge, f"Edge-underscore canonicals: {bad_edge[:5]}"

# 4. No double underscores in any canonical
dbl = [c for c in canonical_desc if '__' in c]
assert not dbl, f"Double underscores in canonicals: {dbl[:5]}"

# 5. No remaining double-prefix duplications
double_pfx = [
    c for c in canonical_desc
    if len(c.split('_')) >= 2 and c.split('_')[0] == c.split('_')[1]
]
assert not double_pfx, f"Double-prefix canonicals still present: {double_pfx[:5]}"

# 6. Same field name always maps to same canonical across all forms
field_to_canon_vals = defaultdict(set)
for form_id, fields in schemas.items():
    for fname in fields:
        field_to_canon_vals[fname].add(global_canonical[fname])

inconsistent = {
    fname: vals
    for fname, vals in field_to_canon_vals.items()
    if len(vals) > 1
}
assert not inconsistent, \
    f"Inconsistent canonicals: {list(inconsistent.items())[:3]}"

print(f"  Total fields across all forms  : {total_fields}")
print(f"  Total mapped                   : {total_mapped}")
print(f"  Unique canonical fact names    : {len(canonical_desc)}")
print(f"  Canonicals shared by 2+ forms  : "
      f"{sum(1 for c in canonical_forms if len(set(canonical_forms[c])) > 1)}")
print()
print("All sanity checks passed.")
