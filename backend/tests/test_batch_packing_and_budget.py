"""Guards for the 2026-07-30 cost work (C27, C28, C29, C30) and its invariants.

Every test here exists because the change it covers could reduce cost in a way
that quietly breaks correctness. The standing rule is that a cost change must
leave fill quality the same or better, so each one pins the invariant, not just
the saving.

Measured effect of the whole set on a realistic 680,000-char, 5-form package
(offline, zero API cost - see scripts/inspect_gap_fill_prompts.py):
    64 -> 46 LLM calls, ~$1.30 -> ~$0.98.
"""
import json
import os
import threading

import pytest

import services.pdf_service as ps


# ── C29: table groups packed WITH ordinary fields, never split ───────────────
@pytest.fixture
def real_table_union():
    """The real cross-form union - the only fixture that reflects production
    table detection, which needs >=3 co-occurring columns over the same rows."""
    facts = {"applicant_name": "Test Co"}
    union = {}
    for fid in ("ACORD_125", "ACORD_126", "ACORD_127", "ACORD_140", "ACORD_25"):
        path = os.path.join(ps.FORMS_SCHEMAS_DIR, f"{fid}_schema.json")
        with open(path, encoding="utf-8") as fh:
            schema = json.load(fh)
        _m, unm, _ = ps.compute_form_gaps(fid, schema, facts)
        for k, v in unm.items():
            union.setdefault(k, v)
    return union


def _run_and_capture(monkeypatch, unmatched, **flags):
    calls = []
    lock = threading.Lock()

    class _Rec:
        def __init__(self):
            self.chat = self
            self.completions = self

        def create(self, **kw):
            msgs = kw.get("messages") or []
            sysm = next((m["content"] for m in msgs if m["role"] == "system"), "")
            user = next((m["content"] for m in msgs if m["role"] == "user"), "")
            stage = "compliance" if sysm is ps._COMPLIANCE_SYSTEM_PROMPT else "gap_fill"
            import re
            names = re.findall(r"^\s+-\s+([A-Za-z0-9_]+)",
                               user.split("Fields to fill (")[-1], re.M)
            with lock:
                calls.append((stage, names))

            class _R:
                choices = [type("C", (), {"message": type(
                    "M", (), {"content": '{"values":{},"answers":{},"quotes":{}}'})()})()]
                usage = None
            return _R()

    monkeypatch.setattr(ps, "_get_openai_form_fill_client_sync", lambda: _Rec())
    for k, v in flags.items():
        monkeypatch.setattr(ps, k, v)
    ps._fill_unmatched_with_gpt(
        unmatched, {"applicant_name": "Test Co"}, "TEST",
        raw_text="DECLARATIONS PAGE each occurrence $1,000,000\n" * 20)
    return [names for stage, names in calls if stage == "gap_fill"]


def _production_groups(union):
    """Multi-slot repeating groups exactly as production defines them.

    Grouping is by `repeating_group_key` = (base, TOOLTIP), not by base name, and
    that distinction is load-bearing. ACORD 25's insurer tooltips end with "As used
    here, this is Insurer B." / "...Insurer C." — a per-row suffix — so
    `Insurer_FullName_B..F` are six SEPATE one-slot groups, not one six-slot group.
    That is correct: each field's own description tells the model which slot it is,
    so there is no cross-slot reasoning to preserve and no reason to keep them in
    one call. An earlier version of this test grouped by base name, flagged those
    six as a violation, and was wrong.
    """
    out = {}
    for f, m in union.items():
        gk = ps.repeating_group_key(f, (m or {}).get("tu"))
        if gk:
            out.setdefault(gk, []).append(f)
    return {k: v for k, v in out.items() if len(v) > 1}


def test_no_repeating_group_is_ever_split_across_calls(monkeypatch, real_table_union):
    """THE invariant (C19), now enforced for EVERY repeating group rather than only
    detected tables.

    A group is rendered as "find up to N separate real values ... 1st in _A, 2nd in
    _B ... NEVER copy the same value into more than one slot". A call that sees _A
    and _B but not _C cannot honour that, and the call that gets _C does not know
    _A/_B are taken. Before this change only >=3-column TABLE buckets were kept
    whole; measured on the real 5-form union with the ORIGINAL packing, **27
    production-defined repeating groups were being split** by plain 40-field
    slicing. It is now 0.

    (27, not 92 - counting by base name instead of `repeating_group_key` inflates it
    and wrongly flags ACORD 25's per-row insurer tooltips. See `_production_groups`.)
    """
    batches = _run_and_capture(monkeypatch, dict(real_table_union))
    assert batches, "no gap_fill calls were made"

    where = {}
    for bi, names in enumerate(batches):
        for n in names:
            where.setdefault(n, set()).add(bi)

    split = {}
    for gk, members in _production_groups(real_table_union).items():
        seen = set()
        for f in members:
            seen |= where.get(f, set())
        if len(seen) > 1:
            split[gk[0]] = sorted(seen)
    assert not split, (
        f"{len(split)} repeating group(s) were split across separate LLM calls, "
        f"e.g. {list(split.items())[:3]}. Separate calls cannot stay row-aligned - "
        f"this is the C19 defect that shipped Vehicle_CostNewAmount_D = vehicle "
        f"1's cost."
    )


def test_group_atomicity_is_unconditional_not_flag_gated(monkeypatch, real_table_union):
    """The revert flag may change COST, never CORRECTNESS.

    `FIELD_BATCH_PACK_TABLES=0` exists to undo the cost optimisation (tables get
    their own call again) if an accuracy baseline ever demands it. It must NOT also
    undo the row-alignment fix - somebody reaching for the kill switch to restore
    old batch sizes must not silently reintroduce split repeating groups.
    """
    for flag in (True, False):
        batches = _run_and_capture(monkeypatch, dict(real_table_union),
                                   _PACK_TABLES_WITH_FIELDS=flag)
        where = {}
        for bi, names in enumerate(batches):
            for n in names:
                where.setdefault(n, set()).add(bi)
        split = [
            gk[0] for gk, members in _production_groups(real_table_union).items()
            if len({b for f in members for b in where.get(f, set())}) > 1
        ]
        assert not split, (
            f"with FIELD_BATCH_PACK_TABLES={flag}, {len(split)} repeating group(s) "
            f"were split across calls (e.g. {split[:3]}). Group atomicity must hold "
            f"on BOTH paths - the flag is a cost switch, not a correctness switch."
        )


def test_packing_tables_with_fields_reduces_call_count(monkeypatch, real_table_union):
    """The saving itself. Measured on the real union: 46 -> 34 gap-fill calls,
    because 34 of the 46 were runts carrying 3-5 fields."""
    packed = _run_and_capture(monkeypatch, dict(real_table_union),
                              _PACK_TABLES_WITH_FIELDS=True)
    legacy = _run_and_capture(monkeypatch, dict(real_table_union),
                              _PACK_TABLES_WITH_FIELDS=False)
    assert len(packed) < len(legacy), (
        f"packing tables with ordinary fields did not reduce calls "
        f"({len(packed)} vs legacy {len(legacy)}) - the runt batches are back"
    )
    # Both must carry the SAME fields - a cost change may not drop a field.
    assert sorted(f for b in packed for f in b) == sorted(f for b in legacy for f in b), (
        "the two packings do not ask about the same fields - packing is dropping "
        "or duplicating work"
    )


def test_no_batch_exceeds_the_frozen_field_limit_unless_one_table_does(
        monkeypatch, real_table_union):
    """`_FIELD_FILL_BATCH`=40 is frozen by accuracy work. Packing may not quietly
    raise it. The single documented exception is a table group that alone exceeds
    the cap - splitting that would break row alignment."""
    batches = _run_and_capture(monkeypatch, dict(real_table_union))
    import re
    for names in batches:
        if len(names) <= ps._FIELD_FILL_BATCH:
            continue
        fams = {re.sub(r"_([A-N])$", "", n) for n in names}
        assert len(fams) == 1, (
            f"a batch of {len(names)} fields exceeds FIELD_FILL_BATCH="
            f"{ps._FIELD_FILL_BATCH} and is NOT a single oversized table group "
            f"({len(fams)} families) - packing has raised the effective batch size"
        )


# ── C30: compliance and general streams partitioned before outer batching ────

def test_compliance_and_general_fields_are_partitioned_before_outer_batching():
    """Slicing the mixed union cut BOTH streams at arbitrary points, leaving runt
    batches on each side (measured: compliance batches of 4, 1, 4, 2, 4, 5).
    Partitioning first makes every batch full except the last of each stream."""
    facts = {"applicant_name": "Test Co"}
    union = {}
    for fid in ("ACORD_125", "ACORD_126", "ACORD_127", "ACORD_140", "ACORD_25"):
        path = os.path.join(ps.FORMS_SCHEMAS_DIR, f"{fid}_schema.json")
        with open(path, encoding="utf-8") as fh:
            schema = json.load(fh)
        _m, unm, _ = ps.compute_form_gaps(fid, schema, facts)
        for k, v in unm.items():
            union.setdefault(k, v)

    items = list(union.items())
    comp = [(n, m) for n, m in items if ps.is_compliance_question(n, m)]
    gen = [(n, m) for n, m in items if not ps.is_compliance_question(n, m)]
    assert comp and gen, "fixture must contain both kinds of field"
    assert len(comp) + len(gen) == len(items), "the partition must be total"

    # No outer batch may mix the two streams.
    batches = []
    if gen:
        batches += [dict(b) for b in ps._pack_schedule_aware_batches(gen)]
    for i in range(0, len(comp), ps._COMBINED_FIELD_BATCH):
        batches.append(dict(comp[i:i + ps._COMBINED_FIELD_BATCH]))
    for b in batches:
        kinds = {ps.is_compliance_question(n, m) for n, m in b.items()}
        assert len(kinds) == 1, (
            "an outer batch mixes compliance questions with general fields, so "
            "both inner streams get cut at that boundary again"
        )


def test_outer_compliance_group_divides_into_full_inner_batches():
    """The partition only pays off if the outer group size is a multiple of the
    inner one - otherwise every outer group still ends in a runt."""
    assert ps._COMBINED_FIELD_BATCH % ps._COMPLIANCE_BATCH == 0, (
        f"COMBINED_FIELD_BATCH={ps._COMBINED_FIELD_BATCH} is not a multiple of "
        f"COMPLIANCE_BATCH={ps._COMPLIANCE_BATCH}, so each outer compliance group "
        f"ends in a partial call"
    )


def test_module_level_and_closure_compliance_predicates_agree(real_table_union):
    """Two levels of batching now classify fields, and they MUST agree. A drift
    here would send a Yes/No question down the general path, which is the exact
    false-'N' flood the dedicated pass exists to prevent."""
    import inspect
    src = inspect.getsource(ps._fill_unmatched_with_gpt)
    assert "is_compliance_question(f, eligible_fields.get(f))" in src, (
        "the closure inside _fill_unmatched_with_gpt no longer delegates to the "
        "module-level is_compliance_question - the two can now drift, and a Yes/No "
        "question classified differently at the two levels loses its dedicated pass"
    )


# ── C28: overflow is per-call, and the budget resets per submission ──────────

def test_context_overflow_flag_is_per_thread():
    """One batch's context rejection must not make sibling batches discard their
    completed work. The flag is thread-local precisely so it cannot."""
    ps._consume_context_overflow()          # clear this thread
    seen = {}

    def _worker():
        seen["before"] = ps._consume_context_overflow()

    ps._note_context_overflow()
    t = threading.Thread(target=_worker)
    t.start()
    t.join()
    assert seen["before"] is False, (
        "a sibling thread saw THIS thread's overflow flag - one overflow will "
        "again make every in-flight batch redo every chunk (C28)"
    )
    assert ps._consume_context_overflow() is True, "our own flag was lost"
    assert ps._consume_context_overflow() is False, "the flag must clear on read"


def test_budget_reset_restores_the_configured_value():
    """`_shrink_budget_after_overflow` only ever decreases, process-wide. Without
    a reset, one pathological document doubles the chunk count and cost of every
    later submission on that worker until restart."""
    original = ps._GPT_CALL_BUDGET_CHARS
    try:
        ps._effective_budget_chars = original // 4
        assert ps.reset_call_budget() == original
        assert ps._effective_budget_chars == original
    finally:
        ps._effective_budget_chars = original


# ── C27: warm-up is once per prefix, not once per outer batch ────────────────

def test_warmup_is_claimed_once_per_stage_and_prefix():
    """Warming populates a cold cache. Once warm, an extra serialized wave buys
    nothing and costs a full round trip of user-visible latency - which an
    8-outer-batch run was paying up to 16 times."""
    ps.reset_prefix_warmup()
    assert ps._claim_warmup("gap_fill", "abc") is True
    assert ps._claim_warmup("gap_fill", "abc") is False, (
        "the same (stage, prefix) was warmed twice - C27 is back"
    )
    # Different stage is a different cache family (different system prompt).
    assert ps._claim_warmup("compliance", "abc") is True
    # A different submission must still warm.
    assert ps._claim_warmup("gap_fill", "xyz") is True
    ps.reset_prefix_warmup()
    assert ps._claim_warmup("gap_fill", "abc") is True, (
        "reset_prefix_warmup did not clear - a new document would never warm"
    )


# ── End-to-end: the cost work may not lose or leak a single field ────────────
# Promoted from an adversarial pass. Every optimisation in this file changes WHICH
# call a field travels in; none of them may change WHETHER it travels, or which
# form receives the answer. These two properties are what make the whole set safe.

def test_combined_gap_fill_asks_every_eligible_field_and_leaks_none(monkeypatch):
    """Two invariants in one run over three real forms:

      1. every eligible union field is actually asked of the model somewhere
      2. no form receives a value for a field it did not ask for

    The field-name extraction here has to understand ALL THREE prompt renderings.
    An earlier version of this check missed the table shape and reported 377 of 895
    fields as "never asked" when they were being asked perfectly well - see
    `_asked_field_names` in test_full_document_coverage.py for why that shape is a
    trap.
    """
    from tests.test_full_document_coverage import _asked_field_names

    facts = {"applicant_name": "Ridgeline LLC"}
    f2u = {}
    for fid in ("ACORD_125", "ACORD_127", "ACORD_25"):
        path = os.path.join(ps.FORMS_SCHEMAS_DIR, f"{fid}_schema.json")
        with open(path, encoding="utf-8") as fh:
            schema = json.load(fh)
        _m, unm, _ = ps.compute_form_gaps(fid, schema, facts)
        f2u[fid] = unm

    asked = set()
    lock = threading.Lock()

    class _Rec:
        def __init__(self):
            self.chat = self
            self.completions = self

        def create(self, **kw):
            msgs = kw.get("messages") or []
            sysm = next((m["content"] for m in msgs if m["role"] == "system"), "")
            user = next((m["content"] for m in msgs if m["role"] == "user"), "")
            import re
            if sysm is ps._COMPLIANCE_SYSTEM_PROMPT:
                names = set(re.findall(r"^-\s+([A-Za-z0-9_]+):",
                                       user.split("QUESTIONS")[-1], re.M))
            else:
                names = _asked_field_names(user)
            with lock:
                asked.update(names)
            payload = json.dumps({
                "values": {f: "X" for f in names},
                "answers": {f: "N" for f in names},
                "quotes": {f: f"no {f} exposure" for f in names},
            })

            class _R:
                choices = [type("C", (), {"message": type("M", (), {"content": payload})()})()]
                usage = None
            return _R()

    monkeypatch.setattr(ps, "_get_openai_form_fill_client_sync", lambda: _Rec())
    monkeypatch.setattr(ps, "_COMBINED_BATCH_PAUSE_S", 0.0)
    out = ps.combined_gap_fill(
        f2u, facts, "DECLARATIONS each occurrence $1,000,000\n" * 30)

    for fid, res in out.items():
        stray = set(res["filled_values"]) - set(f2u[fid])
        assert not stray, (
            f"{fid} received {len(stray)} field(s) it never asked for "
            f"(e.g. {sorted(stray)[:3]}) - results are bleeding between forms"
        )

    union = {}
    for u in f2u.values():
        for k, v in u.items():
            union.setdefault(k, v)
    eligible = {
        f for f, m in union.items()
        if not ps._is_schedule_field(f)
        and (ps._GL_HAZARD_FILLABLE_RE.match(f)
             or not any(p in f for p in ps._RAW_TEXT_SKIP_PATTERNS))
    }
    never = eligible - asked
    assert not never, (
        f"{len(never)} of {len(eligible)} eligible fields were NEVER asked of the "
        f"model (e.g. {sorted(never)[:4]}). A batching change has dropped work - "
        f"those fields come back blank and look like a legitimate omission."
    )
