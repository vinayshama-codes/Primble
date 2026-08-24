"""ANTI-ROT: there is exactly ONE door for "are these two values the same?"

V1 plan C1, decision D3. Five modules each owned a private comparison and
they disagreed on the client's literal inputs. This test fails the build the
moment a sixth appears - the same device as
``test_no_check_reads_a_fact_nothing_writes`` (2026-08-07) and
``test_every_reconcilable_field_has_a_resolved_scan_shape`` (2026-08-08).

Three rules:
  1. Only ``services/fact_comparison.py`` may import the pairwise comparators
     from ``fact_equivalence`` or the conflict helpers from ``normalization``.
     Type lookups (``value_kind``, ``KIND_*``, ``money_amounts``) are not
     comparisons and stay free.
  2. No module under services/ or routes/ may compare two ``_fv(...)`` reads
     with ``==`` / ``!=`` on the same line - that is a raw cross-document
     comparison, the shape that produced defect B2.
  3. The private ``fact_comparison._fe`` back channel has a PINNED set of
     users, so a new bypass has to be a decision rather than an accident.

Rule 1 is enforced by parsing the module, not by matching text. The regex it
replaced could not see an indented import inside a function body, and a real
breach lived behind that blind spot (2026-08-23).
"""
import ast
import os
import re
import pathlib

ROOT = pathlib.Path(__file__).resolve().parents[1]
OWNER = "fact_comparison.py"

# Functions that DECIDE sameness. Importing any of these outside the owner is
# a second opinion.
_FORBIDDEN_FE = ("same_fact", "equivalent_index", "merge_equivalent_groups",
                 "names_a_foreign_line")
_FORBIDDEN_NORM = ("values_conflict", "distinct_normalized", "entity_identity_conflict")

def _scan_files():
    for sub in ("services", "routes", "utils"):
        for f in (ROOT / sub).glob("*.py"):
            yield f


def test_only_the_door_imports_the_comparators():
    """AST, NOT a regex - the regex version was blind and a breach was live.

    The old patterns required an import to end at column 0 or a blank line, so
    an INDENTED one inside a function body never matched. `underwriting_
    consistency.py` had been importing `entity_identity_conflict` that way for
    weeks with this test green (found 2026-08-23; the import now goes through
    `fact_comparison.entities_materially_differ`). Parsing the module is the
    only way to see every import regardless of indentation, line wrapping,
    aliasing or placement.
    """
    offenders = []
    for f in _scan_files():
        if f.name == OWNER:
            continue
        try:
            tree = ast.parse(f.read_text(encoding="utf-8"))
        except SyntaxError:                                  # pragma: no cover
            continue
        for node in ast.walk(tree):
            if not isinstance(node, ast.ImportFrom):
                continue
            forbidden = {
                "services.fact_equivalence": _FORBIDDEN_FE,
                "services.normalization": _FORBIDDEN_NORM,
            }.get(node.module or "")
            if not forbidden:
                continue
            # `alias.name` is the ORIGINAL name, so `import same_fact as x`
            # is caught too.
            bad = sorted({a.name for a in node.names} & set(forbidden))
            if bad:
                offenders.append((f.name, node.lineno, bad))
    assert offenders == [], (
        "A module other than fact_comparison.py imports a comparator. Route the "
        f"decision through services.fact_comparison instead: {offenders}")


def test_the_guard_can_actually_see_an_indented_import():
    """C25 self-check: the previous version of the test above passed while a
    real breach sat in the tree. An anti-rot test that cannot fail is worse
    than no test, so prove this one bites on the exact shape it used to miss."""
    src = (
        "def f():\n"
        "    try:\n"
        "        from services.normalization import (\n"
        "            entity_identity_conflict, strict_entity_key,\n"
        "        )\n"
        "    except Exception:\n"
        "        pass\n"
    )
    found = []
    for node in ast.walk(ast.parse(src)):
        if isinstance(node, ast.ImportFrom) and node.module == "services.normalization":
            found += sorted({a.name for a in node.names} & set(_FORBIDDEN_NORM))
    assert found == ["entity_identity_conflict"], (
        "the AST scan cannot see an indented, parenthesised import - it would "
        "be as blind as the regex it replaced")


# The door re-exports the comparator module privately as `_fe` so a caller can
# reach a rule that has no front-door function yet. That is a legitimate escape
# hatch and NOT a second opinion - every rule still lives in fact_equivalence -
# but it bypasses the front door's two-step recipe, so the set of users is
# pinned. A NEW one fails the build and has to justify itself or get a real
# door function (which is what `entities_materially_differ` became).
_BACK_CHANNEL_ALLOWED = {"fact_state.py", "underwriting_consistency.py"}


def test_the_private_back_channel_has_a_known_set_of_users():
    users = set()
    for f in _scan_files():
        if f.name == OWNER:
            continue
        txt = f.read_text(encoding="utf-8")
        if re.search(r"from\s+services\.fact_comparison\s+import\s+_fe\b", txt):
            users.add(f.name)
    assert users <= _BACK_CHANNEL_ALLOWED, (
        "a new module reaches the comparators through fact_comparison._fe, "
        f"bypassing the front door: {sorted(users - _BACK_CHANNEL_ALLOWED)}. "
        "Add a real function to fact_comparison instead.")


def test_no_raw_cross_document_equality_on_facts():
    """`_fv(a, key) == _fv(b, key)` is the exact shape of defect B2."""
    pat = re.compile(r"_fv\([^)]*\)\s*(==|!=)\s*_fv\(")
    offenders = []
    for f in _scan_files():
        for i, line in enumerate(f.read_text(encoding="utf-8").splitlines(), 1):
            if pat.search(line):
                offenders.append(f"{f.name}:{i}")
    assert offenders == [], offenders


def test_the_door_exists_and_exposes_the_contract():
    from services import fact_comparison as fc
    for name in ("compare", "conflict", "values_agree", "verdict",
                 "identifiers_match", "feins_match", "build_context"):
        assert callable(getattr(fc, name)), name


def test_lob_canonicalisation_has_one_home():
    """B6: `_canon_line` tables must not be re-created anywhere."""
    offenders = []
    for f in _scan_files():
        txt = f.read_text(encoding="utf-8")
        if f.name != "lob_canon.py" and re.search(r"_LOB_CANON_(SPECIFIC|GENERIC)\s*[:=]", txt):
            offenders.append(f.name)
    assert offenders == []
