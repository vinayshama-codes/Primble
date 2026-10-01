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
# 30 Sep 2026: what a fresh upload now does before stamping - each dec entry's
# policy-number tag is checked against the pages (`_verify_dec_entries`), the
# coverage lines are repaired from the entries, and the per-policy records are
# rebuilt from the repaired lines (Orbin live run 17351800: the Common
# Declarations page tagged the GL premium with the inland marine number).
if isinstance(facts.get("dec_page_entries"), list) and raw:
    facts["dec_page_entries"] = es._verify_dec_entries(facts["dec_page_entries"], raw)
    _cl = facts.get("coverage_lines")
    _lines = _cl["value"] if isinstance(_cl, dict) and "value" in _cl else _cl
    if isinstance(_lines, list):
        _tmp = {k: (v.get("value") if isinstance(v, dict) and "value" in v else v)
                for k, v in facts.items()}
        _tmp["coverage_lines"] = _lines
        es._repair_coverage_lines_from_entries(_tmp)
        es._build_scoped_fact_store(_tmp, [dict(x, text="") for x in d.get("documents") or []])
        if _tmp.get(es.LINE_RECORDS_KEY):
            facts[es.LINE_RECORDS_KEY] = _tmp[es.LINE_RECORDS_KEY]
es._repair_emails_from_text(facts, raw)
es._prefer_submission_terms(facts, raw)
es._backfill_payment_method(facts, raw)
es._backfill_prior_coverage_from_entries(facts)
es._mark_submission_remark(facts, raw)
es._mark_stated_new_business(facts, raw)
docs = [dict(x, text="") for x in d.get("documents") or []]
# Re-run the date routing (29 Sep): undo a stored routing of the current term and
# route it again, so a change to `_route_renewal_dates` is measured. Skipped when
# a person supplied the proposed dates (the live merge restores those anyway).
_px = facts.get("prior_expiration_date")
if (isinstance(_px, dict) and _px.get("routed_from") == "current_term"
        and not any(isinstance(facts.get(k), dict)
                    and str(facts[k].get("source") or "") not in ("", "derived", "ai")
                    for k in ("effective_date", "expiration_date"))):
    for _prior, _cur in (("prior_effective_date", "effective_date"),
                         ("prior_expiration_date", "expiration_date")):
        _env = facts.pop(_prior, None)
        facts[_cur] = ({k: v for k, v in _env.items() if k != "routed_from"}
                       if isinstance(_env, dict) else _env)
    for _k in ("renewal_dates_routed", "renewal_lines_expiring"):
        facts.pop(_k, None)
    _rej = facts.get(es.REJECTED_FACTS_KEY)
    if isinstance(_rej, dict):
        for _k in ("effective_date", "expiration_date"):
            _rej.pop(_k, None)
    es._route_renewal_dates(facts, docs)
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
# A value a GUARD blanked is a verdict, not a missing quote: never restore it.
# Guards log it two ways - "blanked=<field>" and "DROP_<REASON>: field=<field>"
# (the ungrounded code / identifier guards). Reading only the first put an
# invented FEIN straight back into the 29 Sep replay.
_log = open(out + ".log").read()
_guarded = set(_re.findall(r"blanked=([A-Za-z0-9_]+)", _log))
_guarded |= set(_re.findall(r"DROP_[A-Z_]+: field=([A-Za-z0-9_]+)", _log))
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
