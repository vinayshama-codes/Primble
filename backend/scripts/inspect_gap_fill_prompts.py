#!/usr/bin/env python
"""Offline inspector for the gap-fill prompt prefix. Makes ZERO OpenAI calls.

WHY THIS EXISTS
---------------
Prefix caching is the single largest cost lever in this pipeline (see
`improving-ll.md`), and whether it engages is decided entirely by the BYTES of
the prompt: OpenAI matches a cached prefix from the very first token, so any
per-call variation before the field list throws the whole prompt back to full
price. That is a deterministic, offline property. It does not need real model
calls to verify, and verifying it against real model calls is actively worse -
the pipeline is non-deterministic (see improving-ll.md rule 5), so run-to-run
jitter would mask exactly the regression you are looking for.

This script runs the REAL `combined_gap_fill` against REAL form schemas with the
OpenAI client swapped for a recorder, captures every (system, user) message pair
the pipeline would have sent, and reports:

  * whether the system prompt is byte-identical across every call
    (it must be - a per-batch system message is improving-ll.md C2)
  * the longest common prefix shared by all calls of each stage
    (this is what OpenAI can actually cache)
  * the share of total input that prefix represents, i.e. the ceiling on savings
  * how many calls the run would make, and their sizes

USAGE
    py scripts/inspect_gap_fill_prompts.py
    py scripts/inspect_gap_fill_prompts.py --forms ACORD_125 ACORD_126
    py scripts/inspect_gap_fill_prompts.py --dump before/     # then git stash,
    py scripts/inspect_gap_fill_prompts.py --dump after/      # rerun, and diff

EXIT CODE
    0 = prefix is stable and above OpenAI's 1024-token cache floor
    1 = a regression: the system prompt varies, or the shared prefix collapsed
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import threading
from pathlib import Path
from typing import Dict, List, Tuple

# Keep the run cheap and deterministic before importing the service module.
os.environ.setdefault("COMBINED_BATCH_PAUSE_S", "0")
os.environ.setdefault("OPENAI_API_KEY", "sk-offline-inspector-not-a-real-key")

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import services.pdf_service as ps  # noqa: E402

# OpenAI's automatic cache only engages at or above this prefix length, and
# matches in 128-token increments below the total.
_CACHE_FLOOR_TOKENS = 1024
_CHARS_PER_TOKEN = 4.0          # standard rough estimate; see _tok()


def _tok(chars: int) -> int:
    return int(chars / _CHARS_PER_TOKEN)


# ── A representative submission ──────────────────────────────────────────────
# Deliberately synthetic and small. The property under test is the SHAPE of the
# prompt, which does not depend on document content; a small document also keeps
# the run to one chunk so batch-to-batch prefix stability is isolated cleanly.
_FACTS = {
    "applicant_name": "Ridgeline Roofing & Sheet Metal LLC",
    "dba_name": "Ridgeline Roofing",
    "mailing_address": "4820 Prospect Ave, Suite 210, Kansas City, MO 64130",
    "producer_name": "Heartland Commercial Brokers",
    "policy_number": "CPP-4471902-03",
    "policy_effective_date": "2026-03-01",
    "policy_expiration_date": "2027-03-01",
    "carrier_name": "Midwest Mutual Casualty",
    "naics_code": "238160",
    "sic_code": "1761",
    "fein": "84-2210987",
    "years_in_business": "12",
    "annual_revenue": "$4,850,000",
    "operations_description": (
        "Residential and light-commercial roof replacement and repair. No work "
        "performed above three stories. No blasting, demolition charges, or "
        "explosive materials are used. Subcontractors are required to provide a "
        "certificate of insurance before starting work."
    ),
    "general_liability_each_occurrence": "$1,000,000",
    "general_liability_aggregate": "$2,000,000",
    "has_general_liability": True,
    "is_contractor": True,
    "has_auto_coverage": True,
}

_RAW_TEXT = (
    "COMMERCIAL INSURANCE APPLICATION\n\n"
    "Named Insured: Ridgeline Roofing & Sheet Metal LLC (DBA Ridgeline Roofing)\n"
    "Mailing Address: 4820 Prospect Ave, Suite 210, Kansas City, MO 64130\n"
    "Producer: Heartland Commercial Brokers\n"
    "Carrier: Midwest Mutual Casualty      Policy No: CPP-4471902-03\n"
    "Policy Period: 03/01/2026 to 03/01/2027\n"
    "FEIN: 84-2210987      NAICS: 238160      SIC: 1761\n"
    "Legal Entity: Limited Liability Company      Years in Business: 12\n"
    "Annual Gross Revenue: $4,850,000\n\n"
    "DESCRIPTION OF OPERATIONS\n"
    "Residential and light-commercial roof replacement and repair. No work is\n"
    "performed above three stories. No blasting, demolition charges, or explosive\n"
    "materials are used. Subcontractors are required to provide a certificate of\n"
    "insurance before starting work. Scrap shingles and used sealant are stored on\n"
    "site in a covered bin and removed monthly by a licensed waste hauler.\n\n"
    "COVERAGE REQUESTED\n"
    "General Liability - Each Occurrence: $1,000,000   Aggregate: $2,000,000\n"
    "Products/Completed Operations Aggregate: $2,000,000\n"
    "Loss History: No known losses in the past five years.\n"
) * 3


class _Recorder:
    """Stands in for the OpenAI sync client. Records, never calls out."""

    def __init__(self) -> None:
        self.calls: List[Tuple[str, str, str]] = []   # (stage, system, user)
        self._lock = threading.Lock()
        self.chat = self
        self.completions = self

    def create(self, **kwargs):                       # noqa: D102
        msgs = kwargs.get("messages") or []
        system = next((m["content"] for m in msgs if m["role"] == "system"), "")
        user = next((m["content"] for m in msgs if m["role"] == "user"), "")
        # The stage is carried by prompt_cache_key ("gap_fill:<hash>"); fall back
        # to sniffing the system prompt so the tool still works if that changes.
        key = kwargs.get("prompt_cache_key") or ""
        stage = key.split(":")[0] if ":" in key else (
            "compliance" if "underwriting questions" in system else "gap_fill"
        )
        with self._lock:
            self.calls.append((stage, system, user))
        return _canned_response()


def _canned_response():
    class _Msg:
        content = '{"values": {}, "raw_text_sourced": [], "question_grounding": {}}'

    class _Choice:
        message = _Msg()

    class _Resp:
        choices = [_Choice()]
        usage = None                                   # skips _log_llm_spend

    return _Resp()


def _common_prefix(strings: List[str]) -> str:
    if not strings:
        return ""
    head = strings[0]
    for s in strings[1:]:
        n = min(len(head), len(s))
        i = 0
        while i < n and head[i] == s[i]:
            i += 1
        head = head[:i]
        if not head:
            break
    return head


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--forms", nargs="+", default=["ACORD_125", "ACORD_25"],
                    help="form ids to run through combined_gap_fill")
    ap.add_argument("--dump", metavar="DIR",
                    help="write every captured prompt to DIR for a before/after diff")
    ap.add_argument("--text-file", metavar="PATH",
                    help="use the real extracted text of a document instead of the "
                         "built-in fixture (pair with the OCR output of a test PDF)")
    args = ap.parse_args()

    global _RAW_TEXT
    if args.text_file:
        _RAW_TEXT = Path(args.text_file).read_text(encoding="utf-8")
        print(f"Using document text from {args.text_file} ({len(_RAW_TEXT):,} chars)\n")

    rec = _Recorder()
    ps._get_openai_form_fill_client_sync = lambda: rec        # type: ignore[assignment]

    forms_to_unmatched: Dict[str, dict] = {}
    for form_id in args.forms:
        path = Path(ps.FORMS_SCHEMAS_DIR) / f"{form_id}_schema.json"
        if not path.exists():
            print(f"ERROR: no schema for {form_id} at {path}")
            return 1
        schema = json.loads(path.read_text(encoding="utf-8"))
        _mapped, unmatched, _ = ps.compute_form_gaps(form_id, schema, _FACTS)
        forms_to_unmatched[form_id] = unmatched
        print(f"  {form_id}: {len(unmatched)} unmatched fields")

    print(f"\nRunning combined_gap_fill over {len(forms_to_unmatched)} form(s), "
          f"raw_text={len(_RAW_TEXT)} chars ...\n")
    ps.combined_gap_fill(forms_to_unmatched, _FACTS, _RAW_TEXT)

    if not rec.calls:
        print("ERROR: no LLM calls were captured - nothing to inspect.")
        return 1

    if args.dump:
        out = Path(args.dump)
        out.mkdir(parents=True, exist_ok=True)
        for i, (stage, system, user) in enumerate(rec.calls):
            (out / f"{i:03d}_{stage}.txt").write_text(
                f"===== SYSTEM =====\n{system}\n===== USER =====\n{user}",
                encoding="utf-8",
            )
        print(f"Wrote {len(rec.calls)} prompts to {out}/\n")

    ok = True
    total_chars = sum(len(s) + len(u) for _, s, u in rec.calls)
    print(f"{'=' * 78}\nTOTAL: {len(rec.calls)} calls, "
          f"{total_chars:,} input chars (~{_tok(total_chars):,} tokens)\n{'=' * 78}")

    for stage in sorted({c[0] for c in rec.calls}):
        calls = [(s, u) for st, s, u in rec.calls if st == stage]
        systems = {s for s, _ in calls}
        sys_chars = len(calls[0][0])
        shared_user = _common_prefix([u for _, u in calls])
        stage_chars = sum(len(s) + len(u) for s, u in calls)

        print(f"\n--- stage={stage}  calls={len(calls)} ---")
        if len(systems) == 1:
            print(f"  system prompt : IDENTICAL across all calls ({sys_chars:,} chars)")
        else:
            ok = False
            print(f"  system prompt : *** {len(systems)} DIFFERENT VARIANTS - "
                  f"caching is dead (improving-ll.md C2) ***")

        prefix_chars = (sys_chars + len(shared_user)) if len(systems) == 1 else 0
        prefix_tokens = _tok(prefix_chars)
        print(f"  shared user prefix : {len(shared_user):,} chars")
        print(f"  CACHEABLE PREFIX   : {prefix_chars:,} chars (~{prefix_tokens:,} tokens)")

        if len(calls) > 1:
            # First call always pays full price; the rest can hit the cache.
            cacheable = prefix_chars * (len(calls) - 1)
            pct = (100.0 * cacheable / stage_chars) if stage_chars else 0.0
            print(f"  ceiling on cached input : {pct:.0f}% of this stage's input chars")

        if prefix_tokens < _CACHE_FLOOR_TOKENS:
            ok = False
            print(f"  *** BELOW OpenAI's {_CACHE_FLOOR_TOKENS}-token cache floor - "
                  f"nothing will cache ***")
        else:
            print(f"  above the {_CACHE_FLOOR_TOKENS}-token cache floor: OK")

        tail = shared_user[-90:].replace("\n", "\\n") if shared_user else ""
        print(f"  prefix ends at ...{tail!r}")

    # ── Cost projection ──────────────────────────────────────────────────────
    # gpt-5.4-mini list pricing. Cached input bills at ~10% of input.
    _IN, _OUT, _CACHE_MULT = 0.75e-6, 4.50e-6, 0.10
    print(f"\n{'=' * 78}\nCOST PROJECTION (gap fill only - excludes extraction and download)\n{'=' * 78}")

    uncached_tok = cached_tok = 0
    for stage in sorted({c[0] for c in rec.calls}):
        calls = [(s, u) for st, s, u in rec.calls if st == stage]
        systems = {s for s, _ in calls}
        prefix = (len(calls[0][0]) + len(_common_prefix([u for _, u in calls]))) \
            if len(systems) == 1 else 0
        for i, (s, u) in enumerate(calls):
            total = _tok(len(s) + len(u))
            hit = _tok(prefix) if i > 0 else 0     # first call always pays full
            cached_tok += hit
            uncached_tok += total - hit

    # Output is capped at _FORM_FILL_MAX_TOKENS but real replies are far smaller;
    # ~700 tok/call is what a mostly-omitting reply actually costs.
    out_tok = 700 * len(rec.calls)
    cost_in = uncached_tok * _IN + cached_tok * _IN * _CACHE_MULT
    cost_out = out_tok * _OUT
    print(f"  input  uncached : {uncached_tok:>9,} tok  ${uncached_tok * _IN:.4f}")
    print(f"  input  cached   : {cached_tok:>9,} tok  ${cached_tok * _IN * _CACHE_MULT:.4f}  "
          f"(billed at {_CACHE_MULT:.0%})")
    print(f"  output (est)    : {out_tok:>9,} tok  ${cost_out:.4f}")
    print(f"  {'-' * 52}")
    print(f"  GAP FILL TOTAL  : ${cost_in + cost_out:.4f}")
    print(f"  (same run with NO caching would be "
          f"${(uncached_tok + cached_tok) * _IN + cost_out:.4f})")

    print(f"\n{'=' * 78}")
    print("PASS - prefix is stable and cacheable." if ok else
          "FAIL - see the *** lines above.")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
