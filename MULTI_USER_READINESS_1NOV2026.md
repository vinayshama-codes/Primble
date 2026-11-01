# Multi-User Readiness

The running log for making Primble safe with several users at once. Started 1 Nov 2026.
Update it with every step. Status of each fix is in the table below.

## Status, 1 Nov 2026 (offline, uncommitted; reviews done, suite 22,166 passed / 1 known failed / 44 skipped; live test next)

- Whole read of the 271-page file (reader + ACORD check): **about 1,500 MB -> 79-127 MB**, text identical.
- Whole pipeline on that file with a stub AI: **1,609 MB -> about 225 MB; three at once 329 MB** (Mac).
- Scores, form stamping, extracted text and route responses compared old vs new: identical (second review).
- **Found: both Redis slot limiters never held.** They wrote `time.monotonic()` as a Unix time, so `PEXPIREAT` set a
  date in 1970 and removed the key at once. Fixed with the wall clock, which turns the caps on for the first time:
  default 8 heavy slots (it was 3, Render sets none), uploads wait instead of "Server busy", slots renew while held.
- **AI slot wait is at least 600 s.** Waiting 90 s burned a gap-fill retry, and the third blanked a batch.
- **Lock order everywhere: package -> documents -> policy store.** The first review reproduced a permanent deadlock
  when the policies table took its lock first. `utils.concurrency.one_writer_per_package` is on the writers.
- **A recalculation writes only `sqs` into each form.** Writing whole forms back blanked a box a save had stamped.
- A form save takes no upload slot. Big files wait for memory BEFORE taking a slot, one at a time.
- Heavy work off the loop: scoring, stops, merge, re-stamps, consistency assessment, cover build, PDF render, the
  download gate, `clean_text`. Anti-rot: `test_no_route_scores_on_the_event_loop`.
- Logs to grep: `LOOP_BLOCKED`, `MEMORY_GUARD_HOLD` / `MEMORY_GUARD_RELEASE`, `MEMORY_GUARD active` / `inactive`.
- Text reuse between PDF passes was NOT done: clearing pages alone met the target with no risk to output.

**Limits to know.** The package lock is per process, so raising `WEB_CONCURRENCY` above 1 voids it. `select_forms_bulk`,
the essentials generators and `submit_arq`'s "before" read are outside the lock on purpose: holding it through a
long generation would hang saves on that package. Dashboard: `MAX_CONCURRENT_HEAVY_OPS` now really applies; a slot
waiter polls Redis up to every 0.5 s, so watch the Upstash command count.

## Reviews (four reviewers, all findings below fixed unless listed as open)

- Adversarial 1: permanent deadlock (lock order), a blanked box (recalculation wrote whole forms), stale `update_pdf`
  write-back, slot lapse, guard holding a slot, wrong "upload again" message.
- Correctness: text, stamping, scores and route responses identical to HEAD; remaining loop freezes; weak tests.
- Adversarial 2: nothing blocking. AI waiters starving the default pool when Redis is down, policy-line re-stamps on
  the loop, a StopIteration hang in `run_scoring`, two more writers outside the lock.
- End-to-end: 6 users on 6 packages 0 differences; double-clicks no hang and no lost value; reach-100 exact.

**Open, known and accepted.**
- Closing the tab mid-upload does not stop the upload, so a re-upload can make a duplicate package.
- A reload during a failing upload can leave the spinner up to 30 minutes (progress key TTL; read in code only).
- Any `ValueError` in the pipeline reads "No readable text found" (old behaviour).
- `select_forms_bulk`, the essentials generators and `submit_arq`'s "before" read are outside the lock on purpose.
- Vision OCR is not cached, so a re-upload of scanned pages pays again.
- Not verified offline: Render's 1 CPU, real Redis / Upstash, real AI, cgroup reading on Render. The live test decides.

## Why this exists

Brent wants real users. Marketing is due to start with an expected first 40-100 users, 5-6 at once.
On 1 Nov 2026, uploading a 271-page PDF on 3 accounts failed with "could not reach the server".

Render Events, 1 Nov 2026, 3:16 PM and 3:18 PM:
"Ran out of memory (used over 2GB) while running your code."

Production: Render Standard instance, 1 CPU, 2 GB, `WEB_CONCURRENCY=1`. All users share ONE process.
The workspace plan (Hobby) does not set server memory. Only the instance type on Compute does.

## What was measured (offline, on the Mac, no database)

| Measure | Before | After | Notes |
|---|---|---|---|
| Reader peak, real 271-page file | 1,292 MB | 63 MB | Clearing each finished page. First pass only. Text identical (same hash), 696,473 chars |
| Reader + ACORD check peak, same file | 1,474 MB | not yet measured | The whole upload must be re-measured |
| Reader time | 83 s | 69 s | |
| Freeze for other users during one page read | 3.17 s | 0.07 s | Synthetic package, scoring on a thread |
| Page read, one user | 2-7 s | | Synthetic. Choice Electric took 13.5 s earlier |
| 6 page reads at once | about 18 s for the slowest | | |
| 8 packages scored at once, 8 rounds | 64 runs: 0 differences, 0 other-package markers, 0 errors | | Timestamps normalised. Scoring only, generation NOT covered |

## Root causes

1. **Crash.** `ocr_service._pdfplumber_extract_pages_structured` never clears a finished page, so pdfplumber
   keeps every page's working data until the file ends. The upload opens the PDF several times (text reader,
   page recogniser, form-field reader, overlay, record check, Transcriber check), and the ACORD steps run twice
   for a document Transcriber reads.
2. **Freeze.** `form_routes._pre_form_status` calls `current_package_sqs` and `complete_screen_shares` directly
   on the event loop. Scoring has been there since Aug 2026. The page-wide plan (Oct 2026) made it take seconds.
3. **Why nothing caught it.** The suite runs one user at a time, and no load test existed.

## Decisions (owner, 1 Nov 2026)

- **We do not keep PDFs after reading.** Uploads are deleted when the request ends. Later steps use stored text
  and facts. Adding a document after forms takes the same path (`upload_intake.remove_files`).
- **No "restart from page N".** After an interrupted upload the user uploads again. It must be clear and cheap.
- **Same spinners only.** Never show "you're next" or any queue wording.
- **Small files never wait.** Big files hold back only when real memory is nearly full.
- **Document identity is a SHA-256 of the full text.** It replaces name + length + first 48 + last 48 chars.
- **Cache rule.** A result worked out from document text alone is keyed by the full-text fingerprint, and the same
  file from two users may share it. Anything holding answers, scores or package data must also key on that package.
- **Database.** Localhost stays on the shared database. Ask the owner before EVERY database read or write.

## Known risks to protect

- **Two saves on the same package overlapping.** The event loop accidentally runs scoring one at a time today.
  Background scoring removes that, so one save could overwrite another. Check this before moving scoring.
- **Shared memory.** `scoped_evidence._cache_key` can mix up lookalike documents (exists today, not caused by
  threads). `cross_form_validator._EXPIRING_PARTS_MEMO` and other unlocked caches can fail under threads.
- **AI slots.** Live log shows 12 slots and a 90 s wait. A call that gets no slot raises a timeout. Confirm it never
  silently leaves boxes blank when several users generate together.

## The plan

| # | Fix | Passes when | Status |
|---|---|---|---|
| 1 | Full-text fingerprint, thread-safe caches, audit every cache against the rule | Lookalike documents stay separate | Built, reviewed; live test next |
| 2 | Permanent isolation tests, scoring and generation | Results together match one-by-one, no other package's data | Built, reviewed; live test next |
| 3 | Clear pages on every PDF pass, reuse text where possible | Text identical, whole upload far below 2 GB | Built, reviewed; live test next |
| 4 | Interrupted uploads | Clear message, no partial data, re-upload does not pay twice | Built, reviewed; live test next |
| 5 | Scoring off the main loop | Others keep working while one user scores; same-package saves stay safe | Built, reviewed; live test next |
| 6 | Memory safety net | Holds big files only when memory is tight, normal spinners | Built, reviewed; live test next |
| 7 | AI slots under load | Waits and retries, no silent blanks | Built, reviewed; live test next |
| 8 | Remove connection URLs from logs | Guard test passes | Built, reviewed: `tests/test_no_secret_urls_in_logs_1nov.py` |

## What must not change

No score rule, price, cap or point. No AI prompt, batching or cost. No extracted text. No stamping, Transcriber
routing, Primble record, Stripe or email behaviour. Any change here is a defect in this work.
`improving-ll.md` needs an entry only if an LLM call changes, and none should.

## Proof before real users

1. Full suite from `backend/`, then an adversarial review of the shared-memory work.
2. Live on primble.ai: 3 uploads of the 271-page file at the same moment, then 5-6 accounts uploading, answering
   and generating. Use declarations and policies only, so no Transcriber pages are spent.
3. Passes if Events shows no "Ran out of memory", no "could not reach the server", progress bars keep moving,
   and each package shows only its own data.

## Dashboard checks (owner)

- Supabase: connection limit (our pools allow up to 20 each), backups on.
- Upstash: plan command limit.
- OpenAI: rate-limit tier.
- Render: `MAX_FILES_PER_UPLOAD` is 10, code default is 20.

## Launch notes

- Start with a small group, watch logs for a few days, then widen. Deploy only in quiet hours.
- A bigger instance on Compute is the quick lever if memory or speed gets tight. Decide after the live test.
- Fixes 1-3 can ship first if launch cannot wait. They cover data separation and the crash.
