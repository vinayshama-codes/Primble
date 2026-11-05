# Primble - OPEN ITEMS (the one living list)

**FRIDAY 6 NOV - THE TWO DELIVERABLES (owner, 4 Nov 11:49 IST):** (1) a user searches ANY ACORD form and fills it through
the same pipeline as our 17, behaving the same way; (2) a user sends ANY filled ACORD form in and gets its data
extracted back (Transcriber). Both checked again on primble.ai after Friday's deploy.

**TOP OF THE NEXT ACCURACY ROUND (owner, 4 Nov):** L-4 / L-5 - ACORD Solutions forms print another policy's values (a
D&O form printed the package's main insurer and a cyber policy's coverage part; design in `Accommodate800forms.md`
10.19). NOT before Friday - first item when ASG-form accuracy is improved.

**Security (section 0) - FIXED by the owner (4 Nov):** the Vision key and the tracked client files. Kept listed at the
top as a reminder; nothing open.

**AL3 next step (owner, 4 Nov):** after the localhost testing, e-mail Brent asking him to have ASG enable the Converter
on Primble's PROD account (he coordinates with ASG). Then: our package's eLabel XML -> Converter -> AL3 = the sample, and
the "Download AL3" button after that.

**INS forms - live test 12:22 IST:** 25 INS and 137 TX INS both came back as the PLAIN form even with the edition fix ->
ASG ignores our variant code for INS (it worked for 125 CIS). Likely a separate "form source" parameter. ASK ASG (via
Brent) for the exact parameter. **Update 14:26 IST:** neither form exists in ASG's download catalogue, so both left the
list in the rebuild. Six INS forms remain (36 / 84 / 139 / 141 / 163 / 829), none tried yet. If one comes back as the plain
form it is refused and marked unavailable for 30 days, so it costs one download at most. Owner to decide: leave the six
in the list (recommended), or hide them until ASG confirms.

**Full-feature review (13:57 IST) - 6 bugs fixed** (Transcriber now reads EVERY ACORD footer shape; 7 state insurance
cards are certificates; only forms with a fillable file listed - 1,116; plain request refuses a variant; no re-download
after generation; editions read only for our forms; the variant-edition guess withdrawn). Open: B6 certificate half
(after a future rebuild only), first ASG call from Render (IP allow-list), INS downloads unproven, L-4 / L-5. Tell Brent:
no ASG form after generation; outside-form boxes without a fact not carried. (The applicant e-signature on ASG forms
was BUILT 4 Nov 14:40 IST - off this list; see Done.)

**Search list REBUILT from ASG's catalogue (13:04 IST; cut to 1,116 at 13:57 - fillable forms only):** 1,140 forms (72 non-existent ones out, 38 missing ones in);
correction - the catalogue's download flag does NOT mean "not downloadable" (50 NY "0" downloaded fine), so the earlier
"308 not downloadable" was overstated; existence is what the catalogue proves. Re-capture monthly.

**ASG's real download catalogue captured (12:52 IST):** 308 forms in our search list are NOT downloadable (incl. all
50 INS - they do not exist as downloads), 35 downloadable ones are missing. Fix = rebuild the search list from
`ASG_DOCUMENTATION/Prod-forms-download-catalogue.json` - owner's GO 12:55 IST, in progress. Refresh the capture monthly (catch 3). For later: ASG has newer editions of 7 of OUR 17
forms (25 2025/12, 125 / 126 2025/03, 130 2026/08, 133 2025/05, 137 CA 2023/01, 131 2017/11) - ACORD licence = current
editions.

**Refused forms are never re-asked (built 12:29 IST):** 30 days in Redis; the search shows them unavailable. When ASG tells us
the INS parameter, clear the `asg:refused:*` keys so INS forms are offered again.

**25 INS fix - BUILT 11:49 IST, waiting on the owner's live test (no ASG call made by Claude):** a form with a variant code
now asks ASG for its own listed edition (`asg_forms.variant_edition`; 25 INS -> 2014/01) instead of "latest"; plain
forms and state versions unchanged. Tests 177 passed. The local backend runs it (restarted 11:49 IST). Owner tests 25 INS
or a similar INS form on localhost.

**Before real users - owner's decisions (4 Nov 11:55 IST), all OFF our list:** support@primble.com mailbox = Brent; one
real purchase + refund = Brent (or users report); billing alerts (disputes, plan-switch renewals, refused final bills)
= Brent / Michelle; Stripe keys = tidy, no issue; ASG production agreement = Brent confirmed production use is allowed;
load = checked by the owner on primble.ai: 3 x 271-page PDFs at once used ~400-500 MB of 2 GB, one CPU fully busy, no
crash -> about 10 users at once is fine; Brent targets 40-50 users by the new year. Every other open item stays listed
below and is fixed AFTER the Friday launch.

**Rules for this file (owner, 3 Nov 2026):**
- Keep it current: add an item the moment it is found, and remove or move it the moment it is done (move it to
  "Done" with its date).
- When asked for open items, read THIS file first, then CLAUDE.md and the day's logs, never only the current plan.

History: replaces the open lists in `client-checklist-25oct.md` (26 Oct, 27 Oct, 3 Nov) and memory
`open-items-26oct`. Built 3 Nov from three read-only sweeps; the 27 Oct items were checked against code and git.
HEAD = d81794b on 3 Nov.

**ASG PROD (4 Nov 02:41 IST): onboarding doc received - the owner fills it first thing on 5 Nov; a production download (ACORD 144) came with NO Sample watermark.**

**Brent, 4 Nov (10:38 IST):** setting up the captcha after his meetings today; no AL3 sample - "once we have our
updated Transcriber access, we should be able to use Converter to generate one from a complete submission"; the
support address is **support@primble.com** (he creates it today) - so every "support@primble.ai" in the app (10 files)
changes to support@primble.com (a code change; with the deploy, the owner's yes).
**ASG PROD credentials received 4 Nov** - no code change needed; `.env` / Render steps in `ASG_TRANSCRIBER.md`
("4 Nov ... PRODUCTION credentials"): `TRANSCRIBER_ENV=prod`, the four values, and the `.env` UAT token-URL override.

**ASG production verified (11:38 IST, 21 requests, 1 page read):** form downloads and filled-ACORD reading both work on
the production keys; production downloads arrive base64-encoded (fixed in code - ships with the deploy); 5 of the 6
forms are the right ones, ACORD 25 INS came back as plain 25 and was refused by the identity check -> ask ASG how to
request 25 INS. Details in `ASG_TRANSCRIBER.md`.
**25 INS - what it is and the likely cause (4 Nov):** our list has 65 variant forms (a code after the number); 50 are
"INS" (ACORD 2/25/27/28/101/125/126/127/130/131/137 TX INS ...). We ask ASG for the variant with `latestEdition=true`.
125 CIS came back right that way; 25 INS did not. Our list dates 25 INS at 2014/01 while plain 25 is 2016/03, so the
likely cause: for INS, "latest edition" picks the newest ACORD 25 of ANY variant = the plain one. Likely fix (small,
code): for a variant, ask for ITS edition from our list instead of "latest"; prove it with ONE call (25 INS). Customer
impact today: none wrong - the identity check refuses the plain form and names it; the user just cannot get that
INS form. Open until tested.

## DEPLOY-DAY CHECKLIST - remind the owner BEFORE the deploy (owner, 4 Nov 11:08 IST)
1. **Render -> acordly-api -> Environment** (Save restarts the service):
   - `TRANSCRIBER=1`, `TRANSCRIBER_ENV=prod`, `TRANSCRIBER_CLIENT_ID` (ASG "Access Key"), `TRANSCRIBER_CLIENT_SECRET`
     ("Secret Key"), `TRANSCRIBER_API_KEY` ("API Key"),
     `TRANSCRIBER_TOKEN_URL=https://prod-token-transcriber.acordsolutions.net/oauth2/token` (change any test value);
   - `ASG_FORMS=1`; leave `ASG_FORMS_ALLOWED_EMAILS` EMPTY (owner: open to every user, production keys);
   - `TRANSCRIBER_BASE_URL` / `TRANSCRIBER_UPLOAD_URL` must NOT exist;
   - `TRUSTED_PROXY_HOPS=1`; `TURNSTILE_SITE_KEY` + `TURNSTILE_SECRET_KEY` if Brent has sent them;
   - `ENVIRONMENT=production` present; `SCHEDULER_CLEANUP_JOBS` stays unset.
2. Before that: the verification calls on localhost (owner's yes), one full suite, the commit (owner's yes).
3. After: Render log `CLIENT_IP_SOURCE ... forwarded_entries=1`; one real upload + one generation on primble.ai.
- `backend/.env` already switched to production by the owner (4 Nov) - checked offline: prod token / API / upload
  hosts, all three keys set. Restart the local backend to use it.
- support@primble.ai -> **support@primble.com** in all 12 places of the app (Brent, 4 Nov) - done 11:08 IST, tests 429
  passed, build clean; ships with the deploy.
- ASG_DOCUMENTATION: the 10 superseded files deleted with the owner's yes (11:08 IST); the `Prod-` set is the reference.

## Commit / deploy decision (owner, 4 Nov 02:16 IST)
**UPDATE 4 Nov 22:43 IST: ASG production credentials work - commit + Render deploy the MORNING of 5 Nov IST (Brent
asleep), watching the log ~30 min; the checklist above first. Everything local was stopped for the night.**
**No commit yet - everything waits for ASG's PRODUCTION credentials**, so clients get real ACORD forms, never the
"Sample"-watermarked UAT ones. The whole uncommitted set (ASG forms, Brent's P&C + 15-form rules, captcha, document
alert, SMS, the safety guards and all 35 Stripe fixes) ships together then. Suite on that code: 22,977 / 1 / 46.
Risk named to the owner: until then primble.ai keeps running the billing code WITHOUT the 35 Stripe fixes (it takes
real payments); the ASG feature is dark by default (`ASG_FORMS=0`), so a deploy before PROD would not show sample forms.
**At that deploy (owner, 4 Nov - later, not now): set `TRUSTED_PROXY_HOPS=1` in Render.** Why: every per-IP limit
(login guessing, the client questionnaire page, its AI chat, the signing page) today counts ALL visitors as one address
- Render's proxy - so one busy client or attacker can fill the limit for everyone. 1 = Render's proxy alone (checked 4
Nov: the browser calls primble.onrender.com directly; Vercel only serves the pages). After the deploy, the Render log
line `CLIENT_IP_SOURCE trusted_hops=1 forwarded_entries=N` must show N = 1; send N if it differs. Safe either way.

## In progress - building today (3 Nov 2026, owner)
- **Login captcha (Cloudflare Turnstile) - BUILT 3 Nov, uncommitted.**
  - Covers sign-up, e-mail login, resend-verification and forgot-password. `services/captcha.py`; widget
    `frontend/src/components/auth/TurnstileWidget.jsx` in `AuthModal`; `GET /api/auth/captcha-config`.
  - Off until BOTH `TURNSTILE_SITE_KEY` and `TURNSTILE_SECRET_KEY` are set on the server (Render) - the owner to
    create them in Cloudflare (Turnstile -> Add site -> primble.ai).
  - A missing or rejected answer = 400; Cloudflare unreachable = allowed + logged `CAPTCHA_UNREACHABLE`.
  - Hard review pass 1 (22:46): fails closed on everything except a real outage (no connection, timeout, 5xx); a 4xx
    / 429 / non-JSON / non-200 reply is refused; an answer solved for another screen is refused (the widget's
    action names = the server's); a bad secret logs `CAPTCHA_MISCONFIGURED` at ERROR; forgot-password shows a 429.
  - Tests `tests/test_captcha_3nov.py` (22). Localhost runs with Cloudflare's always-pass TEST keys since 19:03.
- **Apple Pay - NO CODE NEEDED** (Stripe's docs: hosted Checkout with `payment_method_types=["card"]` shows Apple Pay
  and Google Pay as card wallets; no domain registration; renewals use Apple's merchant tokens; the Customer Portal
  can add it).
  - Brent's dashboard has Apple Pay ON.
  - **Owner, 4 Nov: the test-mode checkout link for Brent's iPhone test - next week, not now.**
  - **Stripe never shows Apple Pay from an Indian IP address**, so Brent (US) must test it. The script is in
    `STRIPE_LIVE_READINESS_2NOV2026.md` "Apple Pay (3 Nov)".
  - Optional: turn Google Pay on.
- **Cross-account document alert (Brent's FW-2) - BUILT 22:03 3 Nov, uncommitted. Table CREATED on the shared database
  (Brent's Supabase) 4 Nov 02:14 IST with the owner's yes** - `document_fingerprints` + its primary key and
  `idx_document_fingerprints_user`, 0 rows; only those two `IF NOT EXISTS` statements ran, nothing else touched. The
  alert starts recording once this code is running (localhost after a restart, primble.ai after the deploy).
  - `services/document_fingerprints.py`. At upload (`extraction_pipeline.extract_document` - fresh uploads and added
    documents), each document leaves keyed hashes (HMAC) of its read text and its file bytes, kept apart from the
    package, so a deleted package or account hides nothing.
  - An unrelated account uploading a document another account uploaded before triggers one e-mail to `ADMIN_EMAILS`
    + `FINGERPRINT_ALERT_EMAILS` (at most one an hour per account) and an audit row `document.cross_account_upload`.
  - Not counted: internal accounts (`ADMIN_EMAILS` + `FINGERPRINT_IGNORE`, default @astreait.com / @primble.ai /
    @primble.com) and colleagues on the same company e-mail domain.
  - Never blocks, never raises. `DOCUMENT_FINGERPRINTS=0` turns it off.
  - Hard review pass 1 (22:46): the e-mail names accounts only, never the file (its name carries the insured's); it is
    sent in the background; the quiet hour starts only when an e-mail really went; hashing runs off the event loop;
    the index is on (user_id, alerted_at) (the primary key already serves fingerprint lookups).
  - Tests `tests/test_document_fingerprints_3nov.py` (9).
  - Recipients (owner, 3 Nov): all the admins (`ADMIN_EMAILS`), nobody else. The owner's own testing never alerts:
    his account is internal, so his uploads (same file many times, or any file) are fingerprinted but never alert, and
    never count as "another account" for someone else's upload either.

- **Stripe adversarial review (22:27 3 Nov) - 1 high, 3 medium, 6 low - ALL FIXED (offline, uncommitted).** Table and
  the "Fixed (3 Nov)" block in `STRIPE_LIVE_READINESS_2NOV2026.md`. HIGH was a support price swap not followed
  (Stripe billed $299, Primble stayed Essentials) - the plan now comes from the subscription's PRICE. Tests
  `tests/test_stripe_review_fixes_3nov.py` (48); billing set 1,335 passed.
  - **Pass 2 (fresh reviewer) - 6 found, all fixed (23:27 IST).** HIGH: after a support plan change, the renewal invoice's
    proration lines restarted the period at the switch date, so packages already used counted again and extras inside
    the allowance were billed (proration lines are now skipped). Also: two renewals paid together broke the period
    (overcharge one way, lost revenue the other); an enterprise account could be re-linked to a dead plan and locked
    out; an annual plan with a monthly add-on synced as monthly; the old plan's final overage was lost on a quick
    re-subscribe; a payer who never got the plan and deleted the account was not refunded. Tests
    `tests/test_stripe_review2_fixes_3nov.py` (15); billing set 1,354 passed.
  - **Pass 3 - 5 found (none high), all fixed (4 Nov 00:08 IST).** Two renewals handled at the same moment could rewind
    the period (next period's extras never billed); an older renewal handled second never billed its period's extras;
    a price billed every N months was metered as monthly; extras counted between a period's end and its paid renewal
    were lost if one bill call failed; a replaced plan's final bill could charge a new-plan unit twice. Tests
    `tests/test_stripe_review3_fixes_3nov.py` (13); billing set 1,367 passed, no old test changed.
  - **Pass 4 - 7 found, all fixed (4 Nov 00:40 IST).** MEDIUM-HIGH (from the pass-3 fix): a late duplicate of the
    current renewal after a mid-period tier change re-billed the new plan's allowance. Also: an older renewal paid
    first billed the next period's packages; held extras of a plan that ended unpaid could be billed on a later plan
    (now `overage_forgiven` - Brent's Option A); extras held for good when two payments landed together; extras used
    while failing mid-period were lost; the first package of a new period billed as the old one's extra; a final bill
    flagged for manual billing could also be billed automatically (now `overage_manual`). Tests
    `tests/test_stripe_review4_fixes_3nov.py` (11); billing set 1,379 passed, no old test changed.
  - **Pass 5 - 4 found (all low), fixed.** A held extra written after the count's commit (now inside it); a renewal
    straddling a support plan change; the lifecycle stage move locking a just-paid user (now guarded); a final bill
    taking a later plan's units (now only packages counted before the plan's end). Tests (8); billing set 1,387.
  - **Pass 6 (FINAL, 4 Nov 01:26 IST) - 3 found, all in the straddle recount; END STATE chosen by the owner: a renewal
    that straddles a support plan change BILLS NOTHING automatically** - one "BILL BY HAND" alert (ERROR log, audit
    `payment.overage_before_switch_manual`, one e-mail per invoice) names the window, the package count, each earlier
    plan and the plan now. The allowance recorder was removed (only `plan_switch:` rows remain, for the alert). The
    day-0 payment e-mail now goes only if the failure it read is still the user's. Tests
    `tests/test_stripe_review6_fixes_3nov.py` (7); billing set **1,393 passed, 0 failed**. Two old tests updated (both
    pinned the overruled recount / an old signature - the TEST was outdated).
  - **Owner, in the Stripe dashboard:** add `charge.dispute.created`, `charge.dispute.closed`,
    `checkout.session.async_payment_succeeded` and `checkout.session.async_payment_failed` to the live webhook
    endpoint's events - without them the dispute alert and the delayed-payment grant never run.
  - **Webhook events added by the owner (3 Nov, 23:10 IST):** the live destination "Primble Render" now listens to 11
    events, incl. the two dispute and two async-payment events. They take effect with the next deploy.
  - **Disputes: alert only (owner, 3 Nov) - keep as is, revisit later.** A disputed account keeps its plan.
- **Hard review of the post-ASG changes - pass 1 found 17, all fixed (22:46).** Search: a state code beside words
  matched other states by prefix ("commercial auto al" found Alaska), small words as state filters ("137 in tx"),
  Virginia matched West Virginia, our forms ranked below ASG copies, "125 126" / "washington dc", "id card" read as
  Idaho. Form selection: the added-forms list came back after generation. Send: the "sent" step and the questionnaire
  page said "sent" when the e-mail failed; an extension was dialled into the SMS number; the page offered the on-file
  phone for a different recipient. IP: only the first X-Forwarded-For header was read, ports broke the address, the
  setup log fired on a health check. Plus the captcha and fingerprint items above.
- **Pass 2 (fresh reviewer, 23:23 IST) - 11 found, all fixed.** Search: a state code beside words still widened to every
  state in the "closest" fallback; "tx id card" filtered on Idaho; "125 tx" / "136 mo" listed other states' versions
  (now the general forms + "No Texas version found"); "texas tx" found nothing; "washington d.c." read as Washington
  state. Document alert: a 50 MB file was held twice in memory (now hashed 1 MB at a time); two uploads at once sent
  two e-mails (the hour is now claimed under a per-account database lock, given back if no e-mail went). Captcha: a
  failed config fetch (deploy / cold start) left sign-in with no widget and a 400 forever (now retried, and reloaded
  on a "security check" refusal). Redis limiter: retrying while blocked kept a user blocked past the hour (a refused
  attempt now leaves the window). IPv6: each address was its own bucket (now its /64; the exact address is still what
  `get_client_ip` returns, e.g. for signatures). SMS: "Text the link" now uses the name / phone of the SEND, not what is
  typed later. Also: the search runs off the event loop; "Back to review" waits for Done. One crash caught by the new
  tests before it shipped: the IPv6 bucket code raised on every IPv4 address (would have 500'd every login).
- **Pass 3 (fresh reviewer, 4 Nov 00:07 IST) - 7 found, all fixed.** Search: "130 in" / "or auto" read the state as
  nothing and listed other states' forms; "28 ny" showed only ACORD 283 NY and hid ACORD 28; "877 california" put the
  form "(except California)" first. Captcha: an answer with no action passed (now the exact action is required; the
  optional `TURNSTILE_HOSTNAMES` pins the site). A content blocker's empty Turnstile stand-in needed a page reload.
  Alert: the e-mail task now starts before the audit write, and shutdown waits for pending alerts before closing the
  pool. Proxy: `TRUSTED_PROXY_HOPS=2` is spoofable unless the Render service accepts only Cloudflare traffic -
  documented; use 1 for Render alone.
- **Pass 4 (fresh reviewer, 4 Nov 00:24 IST) - 6 found, all fixed.** HIGH: the 15-form cap was held only on two of
  the four add-form routes - the policies table's and an added document's "add form" could build a 16th form; the cap
  now lives in the one door all of them use (`form_addition.add_form_to_session`, outcome `package_full`). The P&C
  rule hid three P&C personal-lines supplements ("Extraordinary Life Circumstances", ACORD 66 / 66 OK / 67 IA) - now
  shown (166 hidden, not 169). An umbrella layer's copy now counts as a form on both server and screen (they
  disagreed). A form's title naming a state no longer pulls in ANOTHER state's version (ASG's 63 OK is titled Ohio). A
  search tick of ACORD 127 counts the state auto forms it brings. A refused life form is named in the message, and a
  saved pick list drops forms no longer offered. Open for Brent: ACORD 601 ("consent for incorporating a social
  objective") is shown as P&C - its wording reads like annuity best-interest; ask him.
- **Pass 5 (4 Nov 00:40 IST) - 3 found, all fixed.** Two Generate clicks at once could build up to 30 forms (the package
  is now claimed under its lock - re-read, "no run", the cap - before anything slow); after generation the full-package
  message said "remove some" (impossible then - now "contact support to upgrade"); a pick list saved before the P&C
  rule could bring a life form back (only picks marked P&C are restored). Related tests 1,262 passed.
- **Pass 6 (4 Nov 00:50 IST) - 2 found (both from the pass-5 claim), fixed.** A run with no ASG forms never cleared
  its "preparing" mark, so a failed run blocked a retry and every pre-form fix for 5 minutes; generation used the
  package as read BEFORE the lock (a save just before Generate missed the forms).
- **Pass 7 (4 Nov) - 1 found, fixed.** The policies table and the documents door checked "is a run starting?" before
  taking the package lock; both re-check under the lock now (409 "Forms are being prepared"). Related tests 1,498 passed.
- **FINAL pass 8 (4 Nov 01:22 IST) - CLEAN on code.** One config slip fixed: `.env.example` carried placeholder captcha
  keys, which would have switched the captcha on (and refused every login) for anyone copying it to `.env` - both are
  blank now. Checked: search (800 random queries), P&C (1,008 of 1,174 offered), downloads, select-forms-bulk claim,
  add-form cap, pre-form writers, captcha, rate limiter, document alert, SMS, repo hygiene (no em-dashes, no debug
  code, ruff clean). 37 related test files: 2,088 passed.

- **Brent, 4 Nov - BUILT 00:07 IST, uncommitted:**
  - **Search shows only P&C forms.** ASG's numbering puts Life, Annuity & Health at 650-799 and 950-999 (checked form
    by form), plus title words (life, annuity, health, disability income, long-term care, sickness, medical examiner,
    medical history, 1035). 166 of 1,174 forms leave the list (1,008 P&C remain); a life form id sent anyway is refused (400).
  - **A package holds at most 15 forms, ours and ASG's together** (`PACKAGE_FORMS_MAX`, default 15; a second umbrella
    layer's copy counts as one form). Held at generation (400), at add-form after generation, and on screen: Generate
    stays off with "A package can hold up to 15 forms - untick N, or contact support@primble.ai to upgrade your
    account", and the search refuses a 16th tick. The ASG-only limit (8) stays inside it.
  - ASG: Brent has written to them about the login / API / "Sample" watermark; waiting.

## After Friday 6 Nov (owner, 3 Nov)
- **SMS sharing - "Text the link" BUILT 3 Nov, uncommitted.**
  - The producer's own Messages app opens with the questionnaire link typed (`frontend/src/utils/smsShare.js`): on the
    questionnaire page after Send (the client's phone on file prefilled when the questionnaire goes to the contact on
    file; an extension or a trunk "(0)" is never dialled), and a new "Questions sent" step in the
    editor's Send to Client window (Copy link + Text the link + Done - the link was never shown there before).
  - No provider, no cost, no carrier registration. Tests `tests/test_sms_share_3nov.py`.
  - NOT built: texts sent FROM Primble - needs a provider account (e.g. Twilio, Brent pays), US 10DLC / toll-free
    registration (days), an `arq_sessions` phone column (database change - the owner's yes), a per-user daily cap.
- **AL3 / ACORD Converter (ASG) - SCOPED, NOT BUILT. Blocked on an AL3 sample file.**
  - **Brent's words (relayed by the owner, recorded 4 Nov 02:04 IST):** "5. AL3: Let's add this as a download file option to loop in ASG's Converter. Most producers and carriers are familiar with this file type, so It's important to offer, especially as more and more organizations start creating their own AMS. Which further highlights the importance of our system agnostic approach."
  - So AL3 is now a DOWNLOAD option first (AL3 OUT through ASG's Converter, beside the PDFs) - the "who imports the
    file" question below is answered: producers and carriers / any AMS. Still needs a sample AL3 and one live
    Converter call (the owner's yes) to see the real output before building.
  - "ACORD Converter" is a separate ASG product: brochure + a blank onboarding sheet (organisation, users, IP
    whitelist), no API spec.
  - The DOCUMENTED path is the Transcriber endpoint we already call, with the same keys: `inputFormat=AL3&
    outputFormat=USPNCXML` (AL3 in -> ACORD P&C XML out; async; polled). Also Population AL3 -> filled ACORD PDF.
  - No AL3 file exists anywhere locally (Brent promised samples on 5 Oct). Our reply parser does not read this reply
    shape yet.
  - Plan: AL3 IN (upload an .al3 -> facts as current-policy data) once a sample + ONE live call (the owner's yes)
    show the real output. AL3 OUT waits until Brent names who imports the file.

- **E-mail integration through Transcriber - NOT STARTED, lower priority than the forms.**
  - **Brent's words (relayed by the owner, recorded 4 Nov 02:04 IST):** "Email Integration: This is a lower priority than the forms, but Transcriber has the capability to integrate with user emails, we'll need to experiment with that sooner rather than later. Just wanted to put it on your radar for now."
  - Meaning: producers' e-mails (submissions with attachments) read by ASG's Transcriber (EML / MSG input) into a
    package. First step when the forms work is done: one experiment with a sample e-mail (the owner's yes for the
    call). Already on the V2 list as "e-mail extraction via Transcriber" (Brent, 14 Oct).

## Open list (first written 3 Nov 2026)
- **ASG forms - two decisions parked by the owner (4 Nov, "keep these so we can get back to these"), from review C:**
  1. **Hide forms that are not insured-submission documents?** (25) Agency / producer admin: 808 Agency Appointment,
     812 Agency Questionnaire, 817 / 818 / 819 Producer Appointment, 821 PIF, 876 Background Check Authorization, 877 and
     877 CA consumer-report disclosures; logs 26, 76, 154; 305 NFIP Credit Card Payment Form; 12 instruction sheets
     (e.g. 134 FL "Instructions for Completing ACORD 130 FL and ACORD 133 FL", 70 NY, 170 OH). Filling an agency
     appointment with an insured's data puts wrong data on a document. Recommendation: hide them.
  2. **Hide very old variants beside the current form under the same title?** 126 S (1993) beside our 126, 141 INS
     (2003) beside our 141, 75 N (1993) beside 75 (2016), 25 S (1995) beside our 25. The result row now shows the exact
     edition, which makes them distinguishable.
  Scripts and counts: scratchpad reviewC/ (a2_notforms.py, a2b_admin.py); Accommodate800forms.md 10.25.
- **ASG request / footer check - BUILT + PROVEN 4 Nov (17:20, 5 approved downloads):** 84 INS, 97 SC, 829 LOB came back
  right; 61 VA and 137 LA's code-less 2026/02 row were refused by ASG ("no acroform PDF" - their files are stored as
  "UXX", ASG's data gap). Builder now never chooses a code-only-in-the-name row. Two adversarial reviews (4 Nov):
  12 problems found (list / footer check 5, signatures / drawing 7), all fixed and pinned - Accommodate800forms.md.
  The "UXX" shape (59 forms) was proven in round 2 (84 SC, 60 US).
- **ASG rows with the state only in the NAME - SOLVED on our side 4 Nov (proof round 2, 4 calls):** asked WITH that
  state they download (61 VA, 137 LA 2026/02); 61 VA / 80 MS listed again, 8 forms at ASG's newest edition. The "UXX"
  file shape is proven too (84 SC, 60 US). Still out, unproven: 131 S, 140 S, 25 N, 350 / 360 / 370 WM (variant code
  only in the name). ASG is not asked (owner). Memory: asg-name-only-rows-gap.
- **INS forms - NOT ASG's fault (resolved 4 Nov):** ASG sent the right 84 INS; its footer prints no "INS" and our check
  refused it. Fixed with the check above; all INS forms stay listed.
- ~~137 TX accuracy: Symbol 1 ticked AND "1" printed in the Other-symbol box~~ - FIXED 4 Nov (a guard: the Other box
  never holds a symbol the grid prints; our 137 / 138 too).
- **ACORD 60 applicant signing** not yet done live (needs a second client e-mail).
- **Accuracy round (with L-4 / L-5), seen on the 4 Nov live package - not traced:** ACORD 137 TX for a Colorado insured
  printed a collision deductible "$7", a hired cost "$185" and "CO" in 18 non-owned / hired state cells; ACORD 25 GA
  printed "Fungi Or Bacteria Exclusion ($33)" as an other coverage. Check on the next live run.
- **Tell Brent:** the DRAFT watermark now shows across incomplete forms (it was a tiny mark in the corner - a bug).
- Minor: uvicorn logs a shutdown CancelledError traceback on every stop (every Render deploy too) - noise, not a failure.
Built from three read-only sweeps (V2 + Brent asks; the 27 Oct list checked against code and git; everything noted
since 28 Oct). HEAD = d81794b; the working tree holds only the uncommitted "any ACORD form" feature.

### Found 3 Nov while scoping the four builds - FIXED the same evening (see "Done"), owner actions left
- Stripe dashboard: add `checkout.session.async_payment_succeeded` and `checkout.session.async_payment_failed` to the
  webhook endpoint's events. Matters only if a delayed method (ACH) is ever enabled; cards / wallets are unaffected.
- Render: set `TRUSTED_PROXY_HOPS=1`, then read the one log line `CLIENT_IP_SOURCE trusted_hops=1
  forwarded_entries=N`. N=1 means correct; N=2 means Cloudflare sits in front, so set 2.
- `frontend/.env` still holds the old reCAPTCHA site key (`VITE_RECAPTCHA_SITE_KEY`) - unused, delete it.

### 0. Security - do first (owner)
1. The Google Vision API key is in git history on GitHub: commit 845e250 added backend/uvicorn_local.log (6 key
   matches) on origin/ready-for-deployment-V1, and the local backend/.env holds that same key. Rotate the key, then
   scrub the history.
2. backend/sess.json + backend/run.json (client PII) are still tracked - git rm --cached, add to .gitignore, scrub.
3. render.yaml sets SCHEDULER_ENABLED twice for acordly-api ("false" line 30, "true" line 77) - the dashboard decides. **Owner confirmed 4 Nov: the Render dashboard has SCHEDULER_ENABLED=true** (daily retries and the payment lifecycle run).

### 1. V2 roadmap - Brent's own order (14 Oct 2026; his words relayed again by the owner 4 Nov 02:06 IST)
**Brent:** "We've already discussed the importance of separating our SQS and ACORD e-labels from reliance on the actual
form generation. This, along with the overall combined accuracy of our systems, is by far the most critical focus area.
Followed closely by the shared and ongoing testing notes." Then, in his order of preference:

| # | Brent's item | Status (4 Nov) |
|---|---|---|
| - | SQS + e-labels independent of form generation ("by far the most critical") | DONE (Z35, 23 Oct); live looks owed |
| 1 | "Continue expanding E&O fact lineage (source, confidence, AI or human, timestamps, edited from/to, etc.)" | BUILT (Z44-C, committed 30 Oct); live look owed; "continue expanding" = ongoing |
| 2 | "SMS client sharing" | BUILT 3 Nov as "Text the link" (producer's own phone, no provider); texts sent BY Primble not built - ask Brent which he meant |
| 3 | "Login captcha" | BUILT 3 Nov (Turnstile); waiting on Brent's keys |
| 4 | "Apple Pay" | No code needed (Stripe Checkout wallets); untested - needs a US iPhone (test-mode link for Brent awaits the owner's yes) |
| 5 | "Email data extraction (via Transcriber)" - "can be moved up if the ASG partnership opportunity allows" | NOT STARTED (Brent 4 Nov: lower than the forms, experiment soon) |
| 6 | "ARQ Bot usage tracking" | BUILT as Form Assistant usage (Z44-C); live look owed |
| 7 | "Producer custom questions" | NOT BUILT |
| 8 | "Session archival / retention" | BUILT (Z44-C); live look owed |
| 9 | "Longer-term Integrations & MOAT expansion" - "maintain an ease-of-use / API-first mentality that can integrate with any system" | Ongoing; AL3 download via ASG's Converter (Brent 4 Nov) is the next concrete step |

Brent: "I am most concerned with #1-5 above; #6-9 are less pressing."
- Also NOT BUILT: simulated SQS (Q5, reply owed); vendor keys Yelp / Smarty / narrative enrichment (+ security
  review); carrier triage view; per-form scores (Q4 "TBD").
- Later / parked: NAICS suggestions (off), A+/A/A- grades, per-claim loss detail, refused AI values withheld,
  Stripe FW-1 / FW-5 / FW-6, dismiss-with-reason.

### 1b. The V2 spec document the owner shared with Brent (relayed 4 Nov 02:12 IST) - each item vs what is built
The document rates every item LOW (the e-mail of 14 Oct then ranked them; Brent: "most concerned with #1-5"). The
desired outcomes below are the document's own words; they are the acceptance test for each build.

1. **Apple Pay (LOW).** "Current payment methods are sufficient for launch ... Add Apple Pay when payment optimization
   justifies the development work." - **Met with no work:** Stripe Checkout already offers it as a card wallet; only a
   US iPhone test is left.
2. **SMS Client Sharing (LOW).** "Allow producers to share client links through SMS in addition to existing channels."
   - **Met (3 Nov, "Text the link"):** the producer's own Messages opens with the questionnaire link typed, beside
   e-mail and Copy link. Exactly the document's scope - no Primble-sent texts were asked for.
3. **Producer Custom Questions (LOW).** "Allow producer-added supplemental questions without confusing them with
   Primble-generated SQS/remediation questions. Producer-added questions should not automatically affect SQS unless a
   future explicit scoring rule says otherwise." - **NOT BUILT.** Rules for the build: shown apart from Primble's
   questions, labelled as the producer's, never scored.
4. **ARQ Bot Usage Tracking (LOW).** Track "user; frequency; use case/purpose", "to inform future priority." -
   **BUILT 27 Oct (`services/arq_assistant_usage.py`, Z44-C):** one row per use - the package / questionnaire (user),
   time (frequency), the question the client had open (use case), outcome, tokens, latency; never the client's words;
   admin summary + per-package counts. Live look owed.
5. **Session Archival / Retention (LOW).** "There is no current need to delete historical sessions simply for
   optimization. If storage economics justify it: archive sessions after 12 months of inactivity; do not delete them;
   notify users 30, 7, and 1 day before archival; allow export/download; later support tier-based retention periods."
   - **PARTLY BUILT 27 Oct (`services/package_archive.py`):** manual archive / unarchive, archived packages read-only
   and still downloadable; idle auto-archive exists but is OFF (`PACKAGE_AUTO_ARCHIVE_DAYS=0`; set 365 when turned on).
   **Gaps against the document:** (a) the 30 / 7 / 1-day notices are NOT built; (b) the code still DELETES - active
   packages untouched 180 days and archived ones after 730 days - but only when `SCHEDULER_CLEANUP_JOBS=true`.
   **Checked by the owner 4 Nov: Render has NO `SCHEDULER_CLEANUP_JOBS` key, so it is off (the code's default is
   false) - nothing is deleted.** Keep it unset; setting it to true would delete history the document says to keep. (c) tier-based retention: later, as the document says.
6. **Longer-Term Integrations & Moat Expansion (LOW / FUTURE).** Carrier appetite / eligibility checks; AMS
   integrations; underwriter-facing package review; SQS benchmarking across agencies / classes / carriers; learning from
   bound submissions and from carrier rejections. "Extend Primble from submission preparation into a broader submission
   intelligence layer once the SQS, fact model, provenance, and remediation foundation are mature." - **NOT STARTED**;
   nearest concrete step is the AL3 download via ASG's Converter (Brent, 4 Nov). The A2A block on the cover and the
   EPIC / Vertafore export are existing pieces.
7. **Login CAPTCHA (LOW).** "Add CAPTCHA protection when login abuse or bot activity justifies the additional friction."
   - **BUILT 3 Nov, OFF until Brent's keys** - Turnstile "Managed" mode is usually invisible (little friction); the free
   package makes fake sign-ups worth guarding before abuse shows up.

### 2. Ours - buildable now, no outside input
1. Captcha (Turnstile) - once the keys are in. 2. FW-2 cross-account document alert (Brent approved). 3. The
owner's calls never built: 22 "lines applied for" control; 23 a stated $0 premium prints; 24 "Add ACORD 186" on
the review page (31 Oct scoring rules put it in Package items instead - owner to confirm); 26 claim expense / date
first made from PDF loss runs (prompt bump); 27 a redacted mailing address stays blank + asked (X6).
4. refreshArqData overwrites the package score after a client submit (side panel can stop adding up). 5. Card
wording leftovers (monopolistic "(ND/OH/WA/WY)", raw "wc_monopolistic_payroll breakdown", date-mismatch card names no
dates). 6. Review page speed (13.5 s per read). 7. Carrier's address read as the insured's (guard). 8. Transcriber
table cells print as filled, not "Please verify"; primble_record._fact_backed returns True on any exception; two
documents' ACORD applications disagree -> first upload wins; record gaps (integrity resolutions, reclassifications).
9. Brent's six-core-forms "Check" list against his kit + the five planted cross-form checks. 10. Tidy-up (SCORING_RULES
"TO BE REPLACED", dead _share_group_releases). 11. Parked by the owner (his go): per-form side-panel points; extraction
cut-off "continue" + the false CUT OFF flag (seen again 3 Nov, 4 of 7 decs); FW-1; FW-5. 12. ASG forms before PROD:
L-4 / L-5 line identity; O-ASG-1; the full suite + commit.

### 3. Brent asks pushed back / deferred (who decided)
- "No automatic 60 cap" (19 Oct) - DECLINED by the owner (D72, caps restored), Brent told 20 Oct, no objection.
- WC rating-worksheet rows (R2b) and the EBL premium on the 126 - decided against by us (Z28; no honest box).
- Primble on AWS for Transcriber - deferred to after launch (29 Oct).
- ASG-form accuracy (L-4 / L-5) - deferred by the owner 3 Nov, must be fixed before PROD.
- Forms 152 / 834 / 827 (CE #7) - "leave for now" (now reachable through ASG forms).
- CE #17 "125 first", the stale-tab banner, Orbin #5 / #12 and the client half of #18 - declined by the owner
  (Michelle never told why: M1).
- Business-e-mail-only sign-up - replaced by the fingerprint alert (Brent agreed).

### 4. Waiting on Brent / ASG
**Brent's reply (relayed by the owner 4 Nov 02:24 IST):** USD pricing fine; he will revert the Render account; annual
= **100 packages per month** (not 1,200 at once - so overage bills monthly; already built 3 Nov); plan changes by e-mail
to support "for now", self-service later. **Not answered:** the support address (support@primble.com?) - asked
again; refunds and the billing-alert inbox are parked for later (below). **New ask:** "How difficult is it to require business emails
instead of any email for login?" (a competitor reusing the free trial with Gmail accounts) - the 3 Nov answer was the
cross-account document alert instead (built); options sent back to him: block free-mail domains for sign-up, or let
them sign up but give the free package only to business domains, or keep the alert + captcha. Also asked: an AL3
sample file (promised 5 Oct).

**Business e-mails only - CLOSED (owner told Brent, 4 Nov 11:13 IST): not needed; the cross-account document alert
reports misuse instead.**

**AL3 sample (4 Nov):** ASG's extraction overview lists `AL3` (with `al3Version` v2016 / v2022) as an allowed output
and `ELABELXML` / `USPNCXML` as inputs - but NO v2.0 spec documents an AL3 OUTPUT (the AL3 spec is AL3 -> USPNC XML
only). **The PROD portal offers only XML / JSON for an ACORD form (owner's screenshot, 11:23 IST)** - no AL3, and no
Converter menu (Dashboard, Extraction, Forms, WebForms only). Routes to an AL3 file: (1) ask ASG / Brent whether the
Converter is enabled on Primble's PROD account (Brent: "once we have our updated Transcriber access"); (2) one API
call later - the portal's eLabel XML in, `outputFormat=AL3&al3Version=v2016` out - undocumented, the owner's yes.

**Package form limits changed (owner, 4 Nov 11:23 IST):** (a) NO separate ACORD Solutions limit - the 15 total is the
only cap at form selection, ours and ASG's mixed any way (`asg_forms.max_per_package` = the total; `ASG_FORMS_MAX` can
still set a lower one); (b) NO 15 cap on add-form AFTER generation - those forms are only ever offered by Primble (a
hard stop / warning / cross-form check, a policy line, a new document) and are always our own forms, so a stop can
always be fixed (`form_addition.add_form_to_session`).

**ASG production quota:** not stated in any document we hold (the PROD onboarding sheet names none); the owner recalls
about 50,000. The pilot's rule was 1 transaction = 1 extractable page, 10,000 cap, hard stop. Confirm the number and
whether form DOWNLOADS count.

**Questions to ask Brent LATER (owner, 4 Nov - parked, not in the current e-mail):**
- **Older editions:** "ACORD Solutions offers every edition of a form; Primble offers the newest fillable one. Do agents
  ever need an older edition (a carrier or state that still requires it)? If yes, we can add an edition choice."
- **Refunds:** "a refund in Stripe returns the money but doesn't stop the subscription, so the customer would be
  charged again next month. After a refund, the subscription would also need cancelling in Stripe (one extra click).
  Is that fine for launch, or should a refund cancel the plan automatically?"
- **Billing alerts:** "in a few rare cases (a card dispute, or a late payment after a plan change), the system sends an
  alert asking for a quick manual check instead of charging automatically. These go to info@primble.com. Is that the
  right inbox, and who would you like to look after them?"

**Ask Brent now (4 Nov 01:22 IST) - these need a reply before the deploy:**
1. **support@primble.ai receives no mail** (primble.ai has no MX record) - yet the 15-form limit message, the billing
   messages and the "contact us to upgrade" text all send users there. Checked 4 Nov by DNS: primble.ai has NO MX;
   primble.com has Google mail. Set up support@primble.ai, or confirm we switch every message to an address that works.
2. ~~The 15-form upgrade~~ - **owner, 4 Nov: "contact support" for now; the offer is decided later.**
3. ~~16 Australian forms~~ - **owner, 4 Nov: keep them listed for now.**
4. ~~ACORD 601~~ - **owner, 4 Nov: keep it listed for now.**
5. **Manual billing alerts** (a renewal straddling a support plan change, a dispute, a final bill Stripe refuses) need a
   person to bill or decide. They go to the billing inbox **info@primble.com** - is it watched, and who handles them?
6. Turnstile keys - asked 4 Nov (message sent by the owner). ASG PROD credentials / "Sample" - he wrote to ASG.
Brent: PROD ASG credentials, scope, cap; Q4 per-form scores; ACORD 130 2026/08 edition; scores for generic forms;
the five planted checks; carriers accept the built-in signature?; merge-owner table, ACORD file format, files per
upload (Render still 10); AL3 samples; Stripe L6 (lock at day 10 or 21), refunds, support@ mailbox (primble.ai has no
MX), H4. ASG: ~~variant parameter name~~ (ANSWERED 4 Nov by the portal's own request: `geoCodeSuffix`, with the row's
`edition`), fillable coverage, suffix meanings, contradictory list entries, quota for downloads, the production
agreement (retention, AI-training clause 11.3.2), and **(owner, 4 Nov) an API or webhook for the forms list** - "is
there a way to get the full list of available forms through the API, or a webhook when a form or edition is added,
so our search list updates itself?" (today it is ASG's portal catalogue, captured by hand and rebuilt monthly).
Mail never sent (ours to send): B2 claims-file question, 16 loss-run PDFs, Q5 / form-base / API-key replies, the
Z30-D..Z36-D lists, the round-trip note, "extraction is not repeatable", the 28 Oct score-change list, Michelle M1.

### 5. Owner's own / ops
Multi-user proof on primble.ai (3 x 271-page uploads, then 5-6 accounts) + dashboards (Supabase connections,
Upstash, OpenAI tier, Render MAX_FILES_PER_UPLOAD 10, WEB_CONCURRENCY 1); ~~SCHEDULER_ENABLED on Render~~ (confirmed true, 4 Nov); one live
purchase + refund; delete the Stripe key Brent e-mailed; restricted Stripe key (FW-6); UNKNOWN_KEYS (1 Nov);
Transcriber on primble.ai - notes disagree (TRANSCRIBER=1 with UAT keys per the owner's Render list, 3 Nov, vs "off
until production terms", 29 Oct); Supabase "Project One"; CE #6; CH125 tracker; live looks owed (126 per-project,
130 period totals, archive / Form Assistant usage in the browser); watch live logs for INVARIANT_BROKEN /
SCORING_UNOWNED_DEDUCTION / SQS_NOT_SCORED / LOOP_BLOCKED / MEMORY_GUARD_HOLD.

## Done (moved here with the date)
- **4 Nov 2026, 22:37 IST (uncommitted) - ASG forms: two proof rounds (9 approved downloads), three adversarial reviews
  (A list / footer check, B signatures / drawing, C what would embarrass us), every finding fixed and pinned; full suite
  23,077 passed, 1 failed (the known), 46 skipped.** Detail: Accommodate800forms.md 10.25. Parked for the owner: hide
  non-submission forms, hide very old variants (Open list). Commit after the owner's own localhost check.
- **4 Nov 2026, 17:29 IST (uncommitted) - every fillable P&C form ASG lists can be searched and generated (owner's go
  after the deep check, Accommodate800forms.md 10.25).** Root cause: we guessed ASG's contract. Now (1) the list builder
  records, per form, EXACTLY what ASG's portal sends for its row (`request`: edition + geoCode only when the row has
  one + geoCodeSuffix) and picks the newest FILLABLE row whose request is unambiguous - including rows ASG filed with
  the code only in the name; (2) `_network_fetch` sends that request (125 CIS keeps its proven "latest"); (3) the footer
  check = number + edition asked for + no code we did not ask for (a variant that prints no code - ASG's INS forms - is
  proven by its edition); (4) the refusal memory is versioned (`asg:refused:v2:`), so forms refused by the old check get
  one fresh try. List: 1,116 -> **1,131** forms (+12 ASG non-state codes: 25 FR, 25 S, 126 S, 155 BM, 50 WM, 60 / 62 /
  64 / 66 US, 75 N, 829 CLAP, 829 LOB; +131 S, 140 S; +951 E, Life, hidden); 8 state forms moved to ASG's newest
  edition (137 LA / 138 LA 2026/02, 60 MA, 61 AZ, 65 MA, 65 PA, 80 CO, 852 TX); 0 ambiguous requests. Left out by the
  owner's call: 24 flat-only P&C forms (nothing to fill), older editions (newest only - ask Brent), Life / Health.
- **4 Nov 2026, 16:48 IST - full suite on the code after the live localhost test: 23,007 passed, 1 failed (the known
  `test_arq_acord125_missing_only`), 46 skipped.** Nothing committed - the owner checks on localhost tomorrow first.
- **4 Nov 2026, 15:28 IST (uncommitted) - live localhost test of the recent work, owner's go** (Accommodate800forms.md
  10.25; package `2f4ad0f4`; exactly 4 ASG downloads, 0 Transcriber calls). PASS: P&C-only search, 1,116 list, 15-form
  cap at Generate, production downloads (base64), footer identity check, 60's listed edition, refused-form memory (84
  INS refused, then "Not available" in search, retry generated with 0 calls), 25 GA certificate rules (current term, no
  Primble record), no ASG call after generation, producer Sign, Send to Client + applicant signing on an ASG form,
  signature drops on edit, Primble record in downloads. **Fixed on the way:** (1) signatures INVISIBLE on any page that
  starts with many highlighted boxes - the painter guessed the page's drawing scale from its first 500 bytes; ours too,
  live in production today; now `pdf_service._seal_page_content` (no guess), cached signed PDFs repaint
  (`SIGNATURE_SCOPE` "producer|sealed"); the DRAFT watermark had the same bug on every form (a 19-pt mark in the corner)
  - now across the page, **users will see it for the first time**; (2) ACORD 60's applicant line was never offered
  (label printed to its LEFT) - same-row left labels count for a stand-alone line; (3) 15 ASG titles with "?" for lost
  characters. Tests: `tests/test_asg_signatures_4nov.py` (18, built from the real page shape; they fail with the fix off).
- **4 Nov 2026, 14:40 IST (uncommitted) - the applicant's e-signature now works on ACORD Solutions forms** (owner's ask;
  was D-ASG-10). Send to Client offers the signature for any generated ASG form that has an applicant signature line; the
  lines are read off the printed form exactly as on our 17 (`signature_boxes.applicant_lines_for`, from the package's own
  stored copy - never an ASG call). The producer's saved signature still goes only on the producer's boxes. The editor's
  "not added - sign it by hand" sentence is gone (the "Sample" warning stays). Tests: `tests/test_asg_signatures_4nov.py`
  (10). Live check: owner, on localhost.
- **4 Nov 2026, 14:26 IST - full suite after the ASG production work: 22,989 passed, 1 failed (the known
  `test_arq_acord125_missing_only`), 46 skipped.** Covers the list rebuilt from ASG's download catalogue (1,116 fillable
  forms), production downloads arriving as base64, the refused-form memory (30 days), the footer identity check and the
  full-feature review's six fixes (B1-B6). Nothing committed - commit and deploy wait on the owner's yes.
- **4 Nov 2026, 02:12 IST - full suite on the final code: 22,977 passed, 1 failed (the known `test_arq_acord125_missing_only`),
  46 skipped.** Hard reviews closed: outside billing 8 passes (48 found, all fixed, the last clean on code); Stripe 6
  passes (35 found, all fixed; the rare plan-switch renewal now alerts a person instead of billing). Nothing committed -
  commit and deploy wait on the owner's yes.
- **3 Nov 2026 (21:52, uncommitted) - four guards found while scoping Apple Pay.** Tests `tests/test_stripe_guards_3nov.py`
  (18); 18 related files, 747 passed / 0 failed.
  - **Checkout gives only settled payments.** In the webhook, a `checkout.session.completed` whose `payment_status`
    is "unpaid" (a bank debit still settling) gives nothing. `checkout.session.async_payment_succeeded` gives it
    through the same branch; `..._failed` is logged. Covers subscriptions and overage packs; cards and wallets are
    unchanged (they are "paid" at completion). `/verify-upgrade` was already safe - it grants only active / trialing
    subscriptions.
  - **Stripe API change.** `CHECKOUT_PAYMENT_METHODS` is the one place for the Checkout payment-method parameter
    (both calls). A tripwire test fails the build when the SDK's API version reaches 2026-09-30 and names the
    replacement `allowed_payment_method_types`.
  - **Client IP behind Render's proxy.** `utils/rate_limiter.get_client_ip` reads `TRUSTED_PROXY_HOPS` (default 0 =
    unchanged). With N it takes the Nth X-Forwarded-For entry from the END (the address the trusted proxy saw);
    client-written entries further left are never used, and the value must be a valid IP. One count-only log line,
    `CLIENT_IP_SOURCE`.
  - **Questionnaire send + remind limited per producer.** `check_client_send_rate_limit`: 10 a minute and 60 an hour
    by default (`RATE_LIMIT_CLIENT_SENDS_PER_MINUTE` / `_PER_HOUR`). It sits in `send_questions_to_client` (both
    send buttons) and in the remind route. The limiter now takes a window length.
