"""Replay a stored ACORD 125 run through the CURRENT stamper (28 Sep 2026).

    python3 backend/scripts/replay_125_run.py <dump.json> <out.json>
    python3 backend/scripts/report_125_run.py --key <key> --dump <out.json> --compare <numbers.json>

Measures a code change on a run already graded, with no upload and no LLM cost.
The gap-fill answers are not stored, so the final stamped value of every box the
run sent to call 2 stands in for its answer; every other box is recomputed. The
merge-tail steps added on 28 Sep run on the stored merged facts first. A call-2
Yes/No the live evidence gate accepted is restored when the replay drops it for
lack of a stored grounding quote (printed as "restored"). A replay is not a live
run - gap fill is non-deterministic - so confirm with a real upload."""
import json, logging, os, sys
from pathlib import Path
_BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_BACKEND))
os.environ.setdefault("OPENAI_API_KEY", "sk-offline")
import services.pdf_service as ps
import services.extraction_service as es

src, out = sys.argv[1], sys.argv[2]
d = json.load(open(src))
logging.basicConfig(level=logging.INFO, format="%(message)s",
                    stream=open(out + ".log", "w"))
facts = {**d["merged_facts"], **(d.get("flags") or {})}
if isinstance(d.get("dec_page_entries"), list):
    facts["dec_page_entries"] = d["dec_page_entries"]
raw = d.get("raw_text") or ""
es._repair_emails_from_text(facts, raw)
es._prefer_submission_terms(facts, raw)
es._backfill_payment_method(facts, raw)
es._backfill_prior_coverage_from_entries(facts)
es._mark_submission_remark(facts, raw)
es._mark_stated_new_business(facts, raw)
docs = [dict(x, text="") for x in d.get("documents") or []]
es._mark_page_one_current_policy(facts, docs)
es._validate_submission_carrier(facts, raw)
es._reconcile_disclosure_conflicts(facts, raw)
es._derive_other_insurance_policies(facts, raw)
es._repair_location_units(facts, raw)
es._prefer_labelled_explanations(facts, raw)
facts["_package_form_ids"] = list(d.get("package_form_ids") or ["ACORD_125"])
facts["_form_id"] = "ACORD_125"
schema = json.load(open(_BACKEND / "forms_schemas" / "ACORD_125_schema.json"))
gpt = {f: v for f, v in (d.get("stamped") or {}).items()
       if (d.get("fates") or {}).get(f) == "call2" and v not in (None, "", [])}
mapped, _conf = ps.map_facts_to_form(facts, schema, "ACORD_125", raw_text=raw,
                                     pre_filled_gpt={"filled_values": gpt})
# The live run's call-2 Yes/No answers passed the evidence gate on quotes the
# dump does not keep; without them the gate drops them here. Restore those.
restored = []
import re as _re
_guarded = set(_re.findall(r"blanked=([A-Za-z0-9_]+)", open(out + ".log").read()))
_, _still_call2, _ = ps.compute_form_gaps("ACORD_125", schema, dict(facts))
for f, v in gpt.items():
    if not (mapped.get(f) or None) and f not in _guarded and f in _still_call2:
        mapped[f] = v; restored.append(f)
for dep, q in _re.findall(r"dependent_without_yes blanked=([A-Za-z0-9_]+) \(question=([A-Za-z0-9_]+)", open(out + ".log").read()):
    if q in restored and dep in gpt:
        mapped[dep] = gpt[dep]; restored.append(dep)
print("restored (no grounding quotes in a replay):", restored)
if restored:
    # the live run's guards judged these values; judge them again here
    with ps._schema_context(schema):
        ps._enforce_post_fill_guards(mapped, schema, facts)
d2 = dict(d, stamped={k: v for k, v in mapped.items()}, merged_facts=facts)
json.dump(d2, open(out, "w"), default=str)
changed = sorted(k for k in set(mapped) | set(d["stamped"])
                 if (mapped.get(k) or None) != (d["stamped"].get(k) or None))
print(len(changed), "boxes changed")
for k in changed:
    print(f"  {k}: {d['stamped'].get(k)!r} -> {mapped.get(k)!r}")
