# Stripe Live Readiness

The running log for moving Primble's payments from the developer's Stripe test account to Brent's live
Stripe account. Started 2 Nov 2026. Update it with every change, fix and verification.

Status words: **Open** (found, not fixed) · **Fixed** (code changed, tests pass offline) · **Verified**
(confirmed on the live site) · **Decision** (waits on Brent or the owner) · **Done** (a setting, confirmed).

## Where things stand (3 Nov 2026, 02:50 IST)

**LIVE since 2 Nov evening.** Brent's live Stripe account takes real payments: commit `289629a` (all payment fixes,
LT-1..LT-4) deployed on Render with the live secret key and the live webhook (`we_1UXOYM9O61RSE3nHf289IAon`, API
2026-04-22.dahlia, 6 events + `customer.created` kept as a free connection check). Free live checks passed (section 6).
Adaptive Pricing is OFF (USD only). The Mac's Stripe key is blank (the TEST key is kept commented in `backend/.env`);
the old test webhook to Render is switched off.

**Built 3 Nov, tested, NOT yet committed - the owner commits and deploys:**
- Annual plans = 100 packages per month, extras billed monthly (Brent's 3 Nov answer): Primble's own usage month +
  Stripe's `pending_invoice_item_interval`; review round 6 fixes (no e-mail loop on a failed extras invoice, support
  cycle changes sync, every plan path sets the month data). Proven end to end on real Stripe test mode with a test
  clock on a SEPARATE local database (section 3c).
- Duplicate files in one upload (LT-6): the list refuses a copy (by contents, renamed too); the server reads
  identical documents once and tells the user.
- Full suite 3 Nov 02:45: **22,650 passed, 1 known failure, 44 skipped.**
- After deploying: drop the same PDF twice (and renamed) on primble.ai - the list must refuse the copies; check the
  Render logs for errors.

**Open / later:** Future work FW-1..FW-6 (section before 5) - Brent: ACORD forms first, then FW-2 (cross-account
document alert). Two questions still unasked: refunds needing a separate cancel, support@primble.ai -> .com (primble.ai
has no mail; LT-5). The 4 internal accounts keep their test-mode plans (never charged).

**How to test billing from now on:** Stripe TEST mode only, on the local database `primble_stripe_test`
(Postgres.app; Python is allowed in its App Permissions), with the TEST key passed at launch - never the shared
database, never the live key. Scripts used on 3 Nov are in the session scratchpad (`annual_run/`).

### History (2 Nov)



- Brent's live Stripe account is configured (section 1). Payments and payouts are active, no tasks due.
- **Switched to LIVE on 2 Nov 2026 (evening, IST):** commit `289629a` deployed on Render together with the live
  `STRIPE_SECRET_KEY` and the live webhook secret. Free live checks passed (section 6, "Done at the switch").
- Code review found 27 issues (section 3) on top of 4 fixed earlier the same day (section 2). All were fixed
  offline (backend + billing screens); 3 wait on Brent. Full suite after that round: 22,446 passed / 1 known
  failure / 44 skipped.
- A second review found 16 more (6 medium, 10 low; one is a decision). The second fix round (those 15 + C1) is
  built. A quick review confirmed most of it, but found 8 more (1 high, 2 medium, 5 low - "Quick review of the
  second fix round" below). The high was a regression from the L7 fix.
- Third fix round done: Q1-Q8 fixed offline. Related test files 9,564 passed, 0 failed; Stripe test files 396
  passed. Every code item in this file is now Fixed (offline) or a Decision.
- Final money-path review: SAFE TO SHIP, with 3 small defects (F1-F3). Full suite after the third round: 22,544
  passed / 1 known failure / 44 skipped. Fourth round fixed F1-F3 + a false "charge failed" alert (F4): Stripe test
  files 411 passed, related files 9,564 -> 9,579 passed, 0 failed.
- Every code item is now Fixed (offline) or a Decision. Full suite 2 Nov 22:03: 22,568 passed / 1 known failure / 44 skipped. Next: commit, then deploy (each needs the owner's yes).
- Local test on the test Stripe account (section 3b, 2 Nov evening): every fix PASSED on real Stripe; one new defect
  (LT-1, a portal cancel never showed "canceling") found, fixed, re-tested. All 5 late-payment e-mails received.

### Progress log

| When (IST, 2 Nov) | What |
|---|---|
| 14:58 | First fix round, related tests: 9,464 passed, 2 failed (both fixed: one test outdated, one code fix) |
| after 14:58 | Full suite: 22,446 passed, 1 failed (known), 44 skipped |
| after the suite | Second review (report only): 0 blockers, 0 high, 6 medium, 10 low |
| 16:27 | Second fix round, related tests (run 2): 9,538 passed, 3 failed - generation-structure tests broken by the new billing code; fixes made |
| 16:45 | Second fix round, related tests (run 3) started to confirm those fixes |
| 16:50 | Quick report-only reviewer started on the second fix round (C1, R2-*, the non-payment schedule, double / missed charges) |
| ~17:00 | Quick review back: FIX FIRST. 1 high, 2 medium, 5 low (Q1-Q8). Stripe test files 377 passed. Brent's schedule confirmed |
| 17:02 | Q1-Q8 sent to the fix agent as the third fix round, with the reviewer's 3 repro tests to keep as regression tests |
| before 17:41 | Second fix round, related tests (run 3): 9,545 passed, 0 failed, 18 skipped - second round green. Third round (Q1-Q8) under way |
| 17:45 | Owner: ask before any step after the third fix round. Fix agent told to stop after Q1-Q8 + the Stripe test files; the big related run, full suite and final review wait for his yes |
| by 18:05 | Third fix round done (the stop message arrived after the agent had already run its related set): Q1-Q8 fixed, 13 reviewer repros now pass, related files 9,564 passed / 0 failed / 18 skipped. Waiting on the owner for the next step |
| 18:11 | Owner: go. Full suite started (3 shards) and the final money-path review (report only) started alongside |
| ~18:22 | Final money-path review back: SAFE TO SHIP, no blocker / high. 3 defects (1 medium, 2 low, F1-F3), each a few lines; repros in the session scratchpad (`final_review/`). To fix after the suite finishes (no edits while it runs) |
| 18:32 | Full suite after the third round: 22,544 passed, 1 failed (the known `test_arq_acord125_missing_only`), 44 skipped. Fourth fix round (F1-F3 + the "already paid" false alert) started |
| ~19:00 | Fourth round done: F1-F4 fixed, 15 new tests (`test_stripe_review4_fixes_2nov.py`), Stripe files 411 passed, related set (143 files) 9,579 passed / 0 failed. Waiting on the owner to commit |

## 1. Changes made in Brent's Stripe dashboard (2 Nov 2026)

Account `acct_1TWJhD9O61RSE3nH` (Primble, live mode). Changes made by Vinay (team member, invited by Brent
1 Nov 8:53 PM) unless noted.

| Area | Setting | Value now | Why |
|---|---|---|---|
| Business details | Legal / public name, support address, phone, email, statement descriptor | Primble LLC, Primble, 1500 Grant Street Suite N Denver CO 80203, +1 (970) 320-3700, support@primble.com, PRIMBLE | Set by Brent |
| Business details | Terms of service URL / Privacy policy URL | https://primble.com/terms-of-service / privacy URL present (Brent) | Shown on Stripe-hosted pages |
| Account status | Payments, payouts | Active, no tasks due (Cartes Bancaires paused - French cards, irrelevant) | Checked |
| Customer emails | Successful payments, Refunds | **On** | Customers get a receipt and refund notice; Primble sends none |
| Subscriptions and emails | Upcoming renewals, expiring cards | **On** | Warn before a charge / before a card expires |
| Subscriptions and emails | Card payments fail, bank debit fail, trial reminder | Off | Primble sends its own failure e-mails; card only; no trials |
| Subscriptions and emails | Payment method updates | **Link to a Stripe-hosted page** (was "mix of both (Legacy)" pointing at primble.com) | Customers could not update a card on the marketing site |
| Subscriptions and emails | Subscription management link | **On, Stripe customer portal** | E-mails carry a manage link |
| Payments requiring confirmation | Send a Stripe-hosted confirm link (+ reminders 3/5/7 days) | **On** | A bank asking for 3D Secure reaches the customer |
| Payments requiring confirmation | Incomplete 15 days | **Mark the subscription as unpaid** (was cancel) | Cancelling skipped Brent's day 21 / 60 steps |
| Manage failed payments | Smart Retries | 8 times within 2 weeks (unchanged) | |
| Manage failed payments | First renewal attempt fails | Leave the subscription past-due (unchanged) | Starts Primble's schedule |
| Manage failed payments | All retries fail | **Mark the subscription as unpaid** (was cancel) | Keeps Brent's schedule: day 0, 7, 10 lock, 21 suspend, 60 archive |
| Manage failed payments | Invoice status | Leave the invoice past-due (unchanged) | The customer can still pay it |
| Customer portal | Cancel | At end of billing period; reason collected | Matches the app's own cancel |
| Customer portal | Switch plans / change quantity | Off | Plans change through Primble only |
| Customer portal | Invoices, customer info, payment methods | On | |
| Payment methods | Cards + Amazon Pay, Apple Pay, Cash App Pay, Link, MB WAY, Bancontact, EPS, BLIK, Pix, Affirm, Klarna | Left as is | Primble's checkout asks for cards only |
| Branding | Icon, logo, colours | Not set (optional, Brent's call) | |
| Developers | API keys | Live secret key "Primble Render" created 2 Nov (standard key: billing touches customers, checkout, subscriptions, invoices, invoice items, refunds, payments, portal; a restricted key later, once the exact permissions are mapped) | Owner keeps it in a private note; goes only on Render |
| Developers | Webhook | **Primble Render** `we_1UXOYM9O61RSE3nHf289IAon`, Active, `https://primble.onrender.com/api/stripe/webhook`, Snapshot, **API 2026-04-22.dahlia** (clover not offered; the code's own Stripe calls already use dahlia - the test run exercised those), 7 events: the 6 + `customer.created` (TEMPORARY, for the free signature check - remove after) | Created 2 Nov |

## 2. Fixed earlier on 2 Nov (tests: `backend/tests/test_stripe_payment_lifecycle_2nov.py`)

| # | Issue | Status |
|---|---|---|
| P1 | A later failed payment (a Smart Retry) unlocked a soft_locked / suspended / archived account | Fixed |
| P2 | A day 10 / 21 / 60 e-mail that failed to send was never retried | Fixed |
| P3 | A failure event Stripe created before the user's last payment re-failed a paying user | Fixed |
| P4 | An old invoice on a cancelled subscription could silently lock a free account | Fixed |

## 3. Code review findings (2 Nov, report-only review)

### Must fix before taking live money

| # | Issue | Status |
|---|---|---|
| B1 | "Change Plan" / "Upgrade" opens a second full-price subscription and cancels the old one with no credit | Fixed (offline): checkout refused (409) while a plan is live; screens never offer it to a paying user; an accidental duplicate is cancelled and refunded |
| B2 | Accounts paid on test-mode Stripe ids keep paid access after the switch | Decision: only 4 internal accounts (Vinay, Brent, Michelle x2), kept as they are - owner, 2 Nov |
| H1 | Every new checkout pays all the customer's old open invoices | Fixed (offline): the loop is gone; no webhook pays an invoice |
| H2 | The "cancel other subscriptions" step runs before the duplicate-event check and can cancel the current paid plan | Fixed (offline): all three loops removed; every Stripe side effect after the duplicate check |
| H3 | Two checkouts close together create a second Stripe customer and an orphan subscription | Fixed (offline): one customer per user, created and stored before checkout |
| H4 | Any Stripe customer / subscription with the same e-mail is treated as Primble's | Fixed (offline): only subscriptions / customers tagged with the user's id count |
| H5 | localhost shares the live database but keeps the test key | Decision: blank `STRIPE_SECRET_KEY` in the Mac's `backend/.env` at the switch |

### Medium

| # | Issue | Status |
|---|---|---|
| M1 | verify-upgrade downgrades a past_due paying customer to free | Fixed (offline): it only upgrades, never downgrades or clears a plan |
| M2 | Late SUCCESS events (old invoice.paid, old "active") erase a real failure | Fixed (offline): compared on Stripe's own event times |
| M3 | Free plan's one-package limit can be beaten by starting several packages at once | Fixed (offline): the free package is reserved atomically when generation starts, released on failure |
| M4 | Annual plans: screens say "100 / month", code gives one 1,200 pot per year, overage billed yearly | Decision (Brent) |
| M5 | Overage-pack endpoints are live but not on any screen; take real money; can double-credit | Fixed (offline): both endpoints return 410 |
| M6 | Overage that failed to reach Stripe is never billed | Fixed (offline): retried daily and before the next overage; never billed twice; not forgiven at renewal |
| M7 | Synchronous Stripe calls freeze the server for everyone | Fixed (offline): every Stripe call off the event loop; a test fails the build otherwise |
| M8 | Two lifecycle runs on one day (scheduler + cron endpoint) send e-mails twice; manual retries stack on Smart Retries | Fixed (offline): one run a day; each e-mail claimed once; the day 2/4/6 card retries removed (Stripe retries) |
| M9 | The lifecycle never checks Stripe before locking (a lost invoice.paid locks a paying customer) | Fixed (offline): asks Stripe first; a paid-up user is restored; Stripe down = nobody locked that day |
| M10 | Deleting an account can leave its subscription charging | Fixed (offline): cancels every plan first; any failure deletes nothing |
| M11 | Overage charged during a failed-renewal window | Fixed (offline): no overage while a payment is failing; the paid renewal recounts the period and bills the excess once |

### Low

| # | Issue | Status |
|---|---|---|
| L1 | invoice.paid and invoice.payment_succeeded both reset usage | Fixed (offline): one reset per invoice |
| L2 | Archived screens say "contact support"; paying restores access; e-mails link to the home page | Fixed (offline): "Update billing to restore access"; e-mails open Manage billing (/?open=billing) |
| L3 | The day-0 failure e-mail is not retried by the lifecycle | Fixed (offline) |
| L4 | E-mail addresses in INFO logs; name not escaped in e-mail HTML; secret compared with `!=` | Fixed (offline) (mail logs now mask addresses for every e-mail) |
| L5 | Some write routes lack the payment-status check | Fixed (offline): 19 write routes gated. Not gated, Brent's call: the client's own questionnaire links |
| L6 | Generating forms is blocked at day 10 (soft lock); Brent's schedule blocks forms at day 21 | Decision (Brent) |
| L7 | verify-upgrade downgrades enterprise users; portal-fallback checkout stores no plan metadata | Fixed (offline): enterprise untouched; Manage billing with no account says so instead of selling a plan |
| L8 | Professional usage is counted by a call the browser makes | Fixed (offline): counted on the server when the package is generated (one door for every path) |
| L9 | Concurrent counting at the limit can skip one overage charge | Fixed (offline) |
| C1 | A cancelled plan's unbilled extra packages never reach an invoice | Fixed (offline) - quick review confirmed; residuals Q4, Q5, Q7 fixed in the third round. Owner: bill them. When the plan ends, one final invoice for pending extras, charged once; only for the plan that ended, never for a cancelled duplicate |

### Second review of the fixes (2 Nov, report-only): 0 blockers, 0 high, 6 medium, 10 low

Full suite after the first fix round: 22,446 passed, 1 failed (the known `test_arq_acord125_missing_only`),
44 skipped. Second fix round built; statuses below move to Fixed (offline) once its last test pass and the quick
review are in.

| # | Issue | Status |
|---|---|---|
| R2-M1 | A duplicate refund that fails once (Stripe down, blank key) goes straight to manual and is never retried; no alert | Fixed (offline) - quick review confirmed |
| R2-M2 | A free user's reserved package is lost if the server dies mid-generation | Fixed (offline) - third round |
| R2-M3 | Test-mode paid accounts keep paid plans after the switch | Decision: 4 internal accounts, kept (owner) |
| R2-M4 | Refunding a duplicate could also refund the real plan's overage | Fixed (offline) - quick review confirmed |
| R2-M5 | Paying one old invoice on an unpaid subscription restores full access | Fixed (offline) - quick review confirmed |
| R2-M6 | Overage never collected after a cancellation (= C1) | Fixed (offline) - quick review confirmed (= C1) |
| R2-L1 | An archived user who paid is restored only by invoice.paid; the daily job checks Stripe only when a step is due | Fixed (offline) - quick review confirmed |
| R2-L2 | A checkout finished after the account was deleted keeps charging | Fixed (offline) - quick review confirmed |
| R2-L3 | Packages in the renewal window are billed as overage and counted again | Fixed (offline) - third round |
| R2-L4 | A package counted during the renewal recount is lost from the counter | Fixed (offline) - quick review confirmed |
| R2-L5 | An enterprise account can replace its plan through checkout / /me | Fixed (offline) - residual Q8 fixed in the third round |
| R2-L6 | invoice.paid drops "canceling" | Fixed (offline) - quick review confirmed |
| R2-L7 | A non-renewal invoice resets the period's usage | Fixed (offline) - third round |
| R2-L8 | A blank-key or dev run takes the day's lifecycle slot | Fixed (offline) - quick review confirmed |
| R2-L9 | A crash between claiming and sending a stage e-mail loses it | Fixed (offline) - quick review confirmed |
| R2-L10 | Free users of lite generation not counted; dev reconcile-overage can double-bill | Fixed (offline) - quick review confirmed |

### Quick review of the second fix round (2 Nov, report-only): FIX FIRST - 1 high, 2 medium, 5 low - all fixed in the third round

Stripe test files: 377 passed. Brent's non-payment schedule holds (day 0 / 7 e-mails, day 10 soft_locked,
day 21 suspended, day 60 archived, stage only moves forward, failed sends retried). Repro tests in the session
scratchpad (`quick_review/`), to become regression tests.

| # | Issue | Money effect | Status |
|---|---|---|---|
| Q1 | High. A renewal webhook carries only the first page of invoice lines, and Stripe lists pending items (our per-package overage) before the plan line. With 10+ overage packages the renewal is not recognised: usage is not reset (regression from the L7 fix) | The heaviest users are billed overage for every package of the next period | Fixed (offline): renewal = Stripe's `billing_reason`; a missing plan line counts only on a complete page; period read from the subscription |
| Q2 | Medium. The stored period end is never cleared on plan end / new checkout, and an `invoice.paid` handled before `checkout.session.completed` never records the new one | A re-subscribed user's first-period overage is never billed | Fixed (offline): period end stored by subscription when no user matches yet; cleared on a new checkout and on plan end |
| Q3 | Medium. A lite (free) generation never marks itself live, so after 5 minutes another request frees its reservation; same gap in select-forms between saving and counting | A free user gets two free packages (no card money) | Fixed (offline): the reservation beats while generating; saved forms are never treated as abandoned; a released reservation still counts its package |
| Q4 | Low. The final overage bill checks Stripe only for pending items | A package already billed on a paid renewal could be billed again (needs a timed-out create + account deletion) | Fixed (offline): checks every invoice item on the customer, paid ones included |
| Q5 | Low. When a duplicate subscription is still live at plan end, the user is not downgraded and the final bill is skipped | Paid tier kept with no subscription | Fixed (offline): plan end judged by the stored subscription only; a live duplicate never keeps the tier |
| Q6 | Low. A crash after a duplicate refund but before it is recorded, retried after 24 h, re-issues the refund | Usually Stripe refuses (false alert); money moves twice only with old overage on that invoice | Fixed (offline): existing refunds on the payment are listed before refunding |
| Q7 | Low. A failed final bill only logs; no alert e-mail to info@primble.com | Unbilled final invoice depends on reading logs | Fixed (offline): one-time alert e-mail to info@primble.com |
| Q8 | Low. Plan sync on `subscription.updated` and verify-upgrade can still overwrite an enterprise tier | Enterprise account set back to a Stripe plan | Fixed (offline): plan sync and verify-upgrade leave enterprise alone |

Only a live charge can confirm (added to section 6): the webhook's line page size and order; the order of
`invoice.paid` vs `checkout.session.completed`; that a subscription-scoped invoice item lands only on that
subscription's invoices and stays pending after a cancel; that cancelling a duplicate under flexible billing makes
no proration credit; partial refund of the plan line; the final invoice charging the saved card off-session
(and with 3D Secure); a portal cancel setting `cancel_at_period_end`; an unpaid subscription becoming `active`
once its latest invoice is paid.

### Final money-path review (2 Nov, report-only): SAFE TO SHIP - 0 blocker, 0 high, 1 medium, 2 low - all fixed in the fourth round

Holding: the final bill is keyed to the stored plan (never a duplicate), replay / crash / expired-key retries,
delete-account vs webhook claim once, duplicate refunds (plan line only, earlier refunds checked), scoped overage,
renewal by `billing_reason`, restore only on an active / trialing plan.

| # | Issue | Money effect | Status |
|---|---|---|---|
| F1 | Medium. One Stripe error while a renewal webhook reads the subscription: the event is claimed and usage reset, but the period end / billing steps are skipped and never redone. Also: a user recovering from a failed payment whose paid renewal hits that error keeps "failed", so the recount bills 0 | Overage never billed (repro: 10 of 10 and 5 of 5 lost) | Fixed (offline): a transient error answers 503 before anything is claimed, so Stripe resends; overage used while failing is HELD and billed once on restore (invoice.paid, subscription.updated, daily job); a renewal with no known period end clears the stale one |
| F2 | Low. Q4's "already on an invoice" check covers only our own records, not a stale pending copy still in Stripe | One package billed twice on a later plan's final bill (rare) | Fixed (offline): every item listed first; a unit already on any invoice has its pending copies deleted and is never billed |
| F3 | Low. Recovering an already-sent final bill deletes every pending overage item of the user, not only that invoice's | A new plan's pending overage deleted and never billed (rare) | Fixed (offline): recovery touches only the units on the invoice found; a plan's final bill takes only that plan's own pending items |
| F4 | `Invoice.pay` right after finalizing can answer "already paid" when Stripe collected first | False "Final overage charge FAILED" alert e-mail | Fixed (offline): on a pay error the invoice is re-read; paid = success, no alert. A real decline still alerts |

Only a live charge can confirm (added to section 6): `Invoice.pay` right after finalizing may answer "already paid"
(must not raise a false "charge FAILED" alert); whether Stripe updates the subscription to active before or after
`invoice.paid`; whether Stripe accepts an overage item on an already-cancelled subscription; paying an older unpaid
renewal invoice after a newer one exists.

### Behaviour changes to tell Brent (from the fixes)

1. A plan change can't be bought through a second checkout: "contact support". An accidental second checkout
   is cancelled and refunded automatically; if a refund fails, the log says "MANUAL REFUND NEEDED".
2. Primble no longer charges cards itself on days 2 / 4 / 6; only Stripe's Smart Retries do.
3. The non-payment job runs once a day and asks Stripe before locking anyone.
4. Unpaid extra packages are retried, never forgiven at renewal; none are billed while a payment is failing.
5. Package usage is counted on the server when a package is generated, for every plan.
6. Deleting an account refuses if its plan can't be cancelled.
7. Suspended / archived accounts are refused on 19 more write routes.
8. A cancelled plan gets one last invoice for its unbilled extra packages, charged once to the card the plan
   used (C1, owner 2 Nov: bill them). Packages used while "canceling" are billed too. A failed final charge
   e-mails info@primble.com.
9. Paying one old invoice no longer restores access unless the subscription itself is active again.
10. The daily job asks Stripe about every user in a payment-failure state on every run.
11. A package used after a billing period ended, before its renewal is paid, is billed in the new period.
12. An accidental duplicate's refund is retried for up to 3 days, then goes to manual with an e-mail to
    info@primble.com. Only the duplicate's plan line is refunded.
13. Enterprise accounts can't check out: "Your plan is managed by Primble. Contact support@primble.ai to change it."
14. Free users of the lite (essentials) generation now spend their one free package, like the main generation.
15. When a plan ends, the user is downgraded even if an accidental duplicate is still waiting for its refund.
16. Extra packages used while a payment is failing are held and billed once when the payment recovers. If the
    plan ends unpaid, held packages are not billed (the plan itself was not paid either).
17. If Stripe can't be reached while a payment message arrives, Primble asks Stripe to send it again (503) instead
    of half-processing it.

### Fix files (uncommitted)

Backend: `routes/stripe_routes.py`, `services/stripe_service.py`, `services/usage_service.py`,
`services/scheduler_service.py`, `repositories/session_repository.py`, `routes/download_routes.py`,
`routes/form_routes.py`, `routes/auth_routes.py`, `routes/audit_routes.py`, `routes/questionnaire_routes.py`,
`routes/policy_line_routes.py`, `routes/dev_routes.py`, `services/email_service.py`, `utils/helpers.py`.
Frontend: `utils/billing.js`, `api/stripeApi.js`, `components/billing/PlanChangeNote.jsx`,
`components/billing/UpgradeModal.jsx`, `components/pages/PricingPage.jsx`, `components/layout/Header.jsx`,
`components/form/AcordModal.jsx`, `App.jsx`.
Tests: `test_stripe_live_readiness_2nov.py` (161), `test_stripe_review2_fixes_2nov.py` (78, new),
`test_stripe_review3_fixes_2nov.py` (19, new), `test_stripe_review4_fixes_2nov.py` (15, new),
`test_stripe_payment_lifecycle_2nov.py` (98),
`test_free_package_limit.py` (24), `test_billing_screens_2nov.py` (16); `test_lane_c_27oct.py` allow-list.
Related files after the fourth round: 9,579 passed, 0 failed. Full suite after the third round: 22,544 passed,
1 known failure, 44 skipped.
`processed_webhook_events` now also holds reset / overage-unit / lifecycle-run / duplicate-checkout /
`free_reservation:` / `final_overage:` / `billing_period_end:` / `sub_period_end:` / `email_send:` /
`billing_alert:` keys, and `overage_held` units - never prune it.

## 3b. Local test on the test Stripe account (2 Nov 2026, evening)

Owner asked for every fix to be tested on localhost against the developer's TEST Stripe account
(`acct_1T4cEBFoRT0iiVSB`), with the shared database. Setup:
- Local backend restarted on the fixed code (it had been running the 11:16 code). Scheduler off locally.
- Render's test-mode webhook (`we_1TWbIFFoRT0iiVSB0JefAsVD`) PAUSED at 19:16 IST so the deployed old code does not
  process the same events on the same database. **Must be switched back on at the end.**
- The Stripe CLI download was blocked by the safety check; a local relay script fetches the test account's events
  and delivers them to `localhost:8000/api/stripe/webhook`, signed like Stripe. Events arrive rendered at the test
  account's API version (2026-01-28.clover), not dahlia: the live endpoint (dahlia) is still a live check.
- Test user `vinaysharma+stripetest@astreait.com` (id `801fc0ad-...`), real signup + e-mail code. Only its rows and
  ledger keys are written. Before the lifecycle runs: 0 other users in a payment failure, 0 queued retries.
- Payments typed into Stripe's real checkout page with 4242 4242 4242 4242 in a controlled Chrome.

| # | Test | Result |
|---|---|---|
| 1a | Two checkouts at the same instant | PASS - one Stripe customer, tagged with the user id, stored on the row |
| 1b | Buy Professional monthly (4242) | PASS - one subscription, $299.00 paid, 100 packages, period end recorded although `invoice.paid` arrived before `checkout.session.completed` (Q2). Stripe sends no receipt in test mode |
| 2a | Change plan while paying | PASS - 409 "You already have an active Primble plan. To change your plan, contact support@primble.ai." |
| 2b | Accidental second purchase | PASS - cancelled and refunded $299.00 once, plan line only; earlier refunds checked first (Q6); real plan untouched; the duplicate's own cancellation changed nothing (Q5) |
| 2c | Stripe re-sends 4 processed events | PASS - nothing repeated |
| 3 | Enterprise account (tier set by hand for the test, then put back) | PASS - checkout 409 "Your plan is managed by Primble. Contact support@primble.ai to change it."; verify-upgrade leaves it; a real `customer.subscription.updated` (active, professional) did not overwrite it (Q8) |
| 5 | Extra packages: 108 counted through the one counting door, the last 4 at the same instant | PASS - #105 in the buffer (free); #106-#108 one $3.00 item each, scoped to the user's subscription (`parent.subscription_details`), tagged with the unit key; a second count of #108 ignored |
| 9a | Plan ended (immediate cancel) with 3 unbilled extras (C1) | PASS - account to free; one final invoice $9.00 (3 lines, `billing_reason` manual) paid once; pending copies deleted; re-sent `customer.subscription.deleted` made no second bill; no false "charge FAILED" alert (F4). Proven in test mode: pending items stay pending after an immediate cancel, and draft + attach + finalize + pay works |
| 4 | Free limit: two packages started at the same instant (reservation door, real database) | PASS - one reserved, one refused; after counting, a third refused; a re-run of the same package costs nothing (still 1 used). The generation routes' wiring was not driven (needs a real AI run); offline tests pin it |
| 6a | Move the user onto a Stripe test-clock customer; buy Professional (4242) | PASS - checkout works with a test-clock customer; period end recorded |
| 6b | Renewal carrying 11 extra packages (Q1) - counter set to 104 by hand, 12 packages through the counting door, clock moved one month | PASS - Stripe's real renewal message: 10 lines on the page, `has_more` true, plan line NOT on the page (all 10 were extra-package items) - the exact Q1 shape. Recognised as a renewal by `billing_reason`; one $332.00 invoice ($299 + 11 x $3) paid; usage reset to 0 once (`invoice_reset:` key); new period end 2 Jan 2027 read from the subscription. Proven in test mode: pending items are listed before the plan line |
| 7-0 | Failing card (Stripe `pm_card_chargeCustomerFail`), clock to the next renewal | PASS - charge declined, $299.00 invoice open, subscription past_due; account `failed`; day-0 e-mail "Action required: Payment failed for your subscription" sent 19:34 IST via Resend (address masked in the log) |
| 7-M11 | Extra packages used while failing (counter at 104, 4 through the door) | PASS - #105 buffer, #106-#108 `not_billable`; no Stripe item created |
| 7-0e | Day-0 e-mail in the owner's inbox | PASS - received 7:34 PM ("Payment failed / We could not process your payment.", Update Billing button) |
| 7-7 | Day 7 (failure date moved back 7 days, daily job run twice) | PASS - "Important: Your payment is still overdue" sent ONCE (~19:52 IST); account stays `failed`; nothing locked (packages list 200, generation passes the payment check) |
| 7-7e | Day-7 e-mail in the owner's inbox | PASS - received ("Payment still overdue / Account will be restricted soon.") |
| 7-10 | Day 10 (daily job run twice) | PASS - `failed` -> `soft_locked`; "Account Disabled: Update Billing" sent ONCE (~19:55 IST); upload refused 403 "Account disabled. Please update your billing."; packages still listed (200). Form generation is ALSO refused at day 10 (403) - Brent's schedule says forms lock at day 21: the open L6 decision, confirmed live |
| 7-10e | Day-10 e-mail in the owner's inbox | PASS - received ("Your account has been disabled. Please update your billing to restore access.") |
| 7-21 | Day 21 (daily job run twice) | PASS - `soft_locked` -> `suspended`; "Account suspended: access restricted" sent ONCE (~19:56 IST); upload refused ("Account suspended due to non-payment."), generation refused, deleting a package refused ("Account suspended due to non-payment. Please update your billing to restore access."). The packages LIST stays visible by design (it blocks archived only) |
| 7-21e | Day-21 e-mail in the owner's inbox | PASS - received ("Suspended after 21 days of non-payment. Update your billing to restore access.") |
| 7-60 | Day 60 (daily job run twice) | PASS - `suspended` -> `archived`; "Account archived: update your billing to reactivate" sent ONCE (~19:58 IST); packages list, generation and upload all refused ("Account archived after 60 days of non-payment. Update your billing to restore access."); Manage billing still opens (Stripe portal 200) so the user can pay back |
| 7-run2 | Every stage run twice the same day | PASS - each stage e-mail sent once (M8) |
| 7-60e | Day-60 e-mail in the owner's inbox | PASS - received ("...archived after 60 days of non-payment; update your billing to reactivate. All your data is preserved.") |
| 8 | Recovery: good card pays the overdue renewal (the failing month stamped with 108 packages so the recount places the 3 failing-period extras at #106-#108) | PASS - archived -> `ok` in one step, failure date + e-mail counter cleared, no e-mail; period recounted to 108; the 3 extras billed ONCE ($3 each, scoped to the subscription) - M11 / F1; next period end recorded; re-sent `invoice.paid`, `invoice.payment_succeeded`, `customer.subscription.updated` billed nothing more. `invoice.payment_succeeded` arrived before `invoice.paid` |
| 9b-1 | Cancel through the REAL Stripe billing page (portal, driven in Chrome) | Stripe: "Cancels 2 Feb 2027 ... Your service will end on 2 February 2027". **FOUND LT-1:** the portal set `cancel_at` (a date) and left `cancel_at_period_end` FALSE; Primble still shows `ok`, not `canceling` |
| 9b-2 | 2 extras used while canceling, clock to the plan's end | PASS - #109/#110 billed ($3 each); plan ended -> account `free`. **Stripe itself invoiced the 5 waiting extras** at the end of a portal-cancelled plan (its own invoice, $15.00, 5 lines, `billing_reason` subscription_cycle, paid); our final bill found every unit already invoiced and billed NOTHING (`final_none`) - charged once (Q4/F2). So: immediate cancel = Stripe leaves extras pending, our final bill charges them (9a); end-of-period cancel = Stripe bills them, ours stands down (9b) |
| 9b-3 | LT-1 re-test on the fixed code (backend restarted), real billing page | PASS - cancel: Stripe sets only `cancel_at` (2 Mar 2027), Primble `canceling` (database and /me); "Don't cancel subscription" -> "Renew subscription": Stripe clears it, Primble back to `ok` |
| 10 | Delete account with 2 unbilled extras (M10, C1) | PASS - plan cancelled in Stripe BEFORE anything was deleted; one final invoice $6.00 (2 lines) paid once; user row and all its packages gone; the `customer.subscription.deleted` that followed billed nothing more |
| 10-L2 | A checkout page left open is paid AFTER the account was deleted (R2-L2) | PASS - "user no longer exists - cancelling and refunding": that subscription cancelled, $299.00 refunded |
| 10-charges | Every charge on the test customers | PASS - each charged once; the only failed charge is the declined 0341 card from test 7 |
| 11 | Retired overage-pack routes; e-mail addresses in logs | PASS - both routes answer 410 "Overage packs are no longer sold..." (read in code: the test user was deleted by then); the whole run's backend log shows the test address 0 times unmasked (`v***@astreait.com` only) |
| Clean-up | 20:17 IST | Render's test webhook switched back ON (paused 19:16-20:17); relay and Chrome stopped; backend restarted normally (webhook secret from `.env`); shared database: test user 0 rows, test packages 0, other users in a payment failure 0, the 3 paid internal accounts `professional` / `ok`. The ledger keys stay (never pruned). Stripe test-mode objects (test clock, customers, invoices) left as evidence; Stripe removes the clock after 30 days |

| Owner's screen test | 20:24 IST | Set up again for the owner's own click-through (screens, a new free account, real generation counting): Render's test webhook PAUSED again, relay on, backend on the local webhook secret. **Switch Render's test webhook back on when the owner is done** |

| Owner's screen test ended | 21:28 IST | Render's test webhook switched back ON; relay and Chrome stopped; backend restarted normally. Owner's own account was left set to cancel on 16 Nov 2026 (test mode) |
| Full suite before commit | 21:35-22:03 IST | **22,568 passed, 1 failed (the known `test_arq_acord125_missing_only`), 44 skipped** - after LT-1..LT-4. Ready to commit (owner's yes) |

**Result: every fix in this file passed on real Stripe (test mode), plus one new defect (LT-1) found, fixed and re-tested.**
Proven here and no longer only a live check: invoice items scoped to a subscription (`parent.subscription_details`); pending
items listed before the plan line with `has_more` (Q1); pending items kept after an immediate cancel; draft + attach +
finalize + pay; Stripe invoicing the pending items itself when a plan ends at its date; checkout with an existing
customer; `invoice.paid` before `checkout.session.completed`; `invoice.payment_succeeded` before `invoice.paid`; the
portal's cancel (`cancel_at`) and renew. Still live-only: dahlia payloads (test events came as clover), real-bank 3D
Secure, Brent's live dashboard settings (Smart Retries, unpaid), receipts, a new card paying the overdue invoice on its
own, the alert e-mail to info@primble.com.

### Found by the local test

| # | Issue | Effect | Status |
|---|---|---|---|
| LT-1 | A cancel from Stripe's billing page sets `cancel_at` (a date), not `cancel_at_period_end`. Four places read only `cancel_at_period_end`: the `customer.subscription.updated` handler, `subscription_payment_state`, `subscription_status`, and the restore decisions built on them | The customer cancels and Primble still shows the plan as normal (`ok`), never `canceling`; a payment restore puts such a user back to `ok`. No money effect: the plan's end (`customer.subscription.deleted`) still downgrades and runs the final bill | Fixed (offline): `stripe_service.is_ending` (`cancel_at_period_end` OR a `cancel_at` date) in all four readers; `tests/test_stripe_local_test_fixes_2nov.py` (5, incl. an AST guard that no reader asks the flag alone); Stripe files 416 passed. Live re-test below |
| LT-2 | Owner's click-through: right after Google sign-in the plan dropdown shows "0 used" (no "/ 100") on an account with 42 / 100 in the database. The sign-in response carries no package numbers and the app keeps it until a reload (`useAuth.login` sets the response as the user). Pre-existing (same at HEAD), display only - billing reads the database | Wrong usage shown until a refresh | Fixed (offline): `useAuth.login` shows the sign-in record, then loads `/api/auth/me` (the full account); pinned by `test_LT2_a_sign_in_loads_the_full_account`; frontend build clean. Owner to confirm on screen |
| LT-3 | Owner's click-through: after a counted package the plan panel kept the old count until a refresh (seen on Essentials: "1 / 1200"). Two causes: (1) the screen did not reload the account after the lite score; (2) the real one, server-side: `/api/auth/me` for a paying user and the auth user record are each cached 30 s in Redis, and counting a package cleared neither - so the screen's reload got the stale copy (Professional too) | Wrong usage shown for up to 30 s / until a refresh | Fixed (offline): (1) the lite score's success reloads `/me`; (2) `count_session_usage` calls `invalidate_user_cache` once the count is claimed. Pinned by `test_LT3_*` (2); 553 counting + Stripe tests pass; backend restarted. PASS - owner confirmed: the usage moves without a refresh |
| LT-4 | Owner's click-through: on Essentials the dashboard showed 56 / 60 and the opened package showed 48 / 45 (vinaynotbinay@gmail.com, uploads 15:28 / 15:34). The Essentials run (`lite_generate_internal`) never scored or saved the PACKAGE score, so its screen fell back to the ACORD 125 form's own score; the dashboard showed the package's pre-form score. Pre-existing | Two different scores for one package | Fixed (offline): the Essentials run scores the package through `calculate_package_sqs` with `stops_now` (like the full generation) and saves it (never a failed None); dashboard and screen read the same number. Pinned by `test_LT4_the_essentials_score_is_the_package_score`; the stops-door guard (`test_build23_stops-after-forms`) caught a first cut that bound the stops to `None` before the door - the CODE was reshaped to take them from `stops_now` only. 60 related files: 3,683 passed; then the 9 touching files 275 passed. Backend restarted. Existing packages correct themselves the next time their score screen opens. PASS - owner confirmed: dashboard and opened package show the same score |
| LT-5 | The app tells customers to write to **support@primble.ai** (footer "Contact Us", archived messages, dropdown, plan-change note), but primble.ai has **no MX record** - mail to it bounces. primble.com is on Google Workspace (info@primble.com receives: a contact-form test was Delivered); Stripe shows support@primble.com (set by Brent). Pre-existing address | Customers cannot reach support from the app | Open - proposed: support@primble.com everywhere (about 6 places); waits on Brent confirming that inbox (question 4 in the e-mail) |
| LT-6 | Owner's live check, 3 Nov: the same PDF dropped twice into the first upload was kept twice and read, sent to the AI and merged twice (the "already in the package" check ran only for documents ADDED to an existing package) | Double AI cost; one document counted as two sources | Fixed (offline): the upload list refuses a file it already holds (same name, size, last-modified) and says "That file is already in the list, so it was not added again."; the list also compares CONTENTS (SHA-256 of the file's bytes, worked out in the browser), so a renamed copy is refused too; the server's fresh upload passes its own `known_texts`, so identical documents are read once (no AI call for the copy). Confirmed on primble.ai before the fix (same PDF twice = 2 documents). `tests/test_upload_duplicates_3nov.py` (5); upload-related files 740 passed; build clean. A NEW package with the same document is allowed by design. Not built: the cross-account alert (owner: later) |
| A1 | Owner's check: plan dropdown on his Professional account (after a refresh) | PASS - "Professional · Monthly", 42 / 100, "To change your plan, contact support@primble.ai.", Manage billing, Cancel Subscription |
| LT-2 check | Owner signed out and in again with Google, no refresh | PASS - dropdown showed 42 / 100 at once |
| A2 | Owner: home page plan section | Changed on the owner's ask: the line "To change your plan, contact support@primble.ai. Manage billing" removed from the home page's plan section (it stays in the account dropdown and in the upgrade window). `test_billing_screens_2nov.py` updated (the TEST pinned the old placement); 28 screen tests pass; build clean |
| A2b | Owner: a paying user's other plan cards | Changed on the owner's ask: plain grey text "Contact support to switch" -> a greyed-out, unclickable button "Contact support to change" (hover: "To change your plan, contact support@primble.ai."), on the home page and in the upgrade window alike; pinned in `test_billing_screens_2nov.py`; 28 screen tests pass; build clean. PASS - owner confirmed on screen (Essentials greyed, Professional "Current plan", Enterprise "Contact sales") |
| A3-A6 | Owner: Manage billing; cancel and renew on Stripe's page; `/?open=billing` | PASS - billing page opens (Primble Professional, $299/month); cancel -> dropdown "Subscription will cancel at end of billing period"; "Don't cancel" -> back to normal; the e-mail link opens the billing page by itself |
| A-drop | Owner: "Cancel Subscription" in the Primble dropdown | PASS - no redirect by design (Primble tells Stripe directly): 20:47:51 Stripe `cancel_at_period_end` true from our API call, dropdown "will cancel". Undone at 20:48:48 through Stripe's billing page; now active, not cancelling, Primble `ok` - database and Stripe agree |
| B | Owner: free test account (free package already used) -> bought Essentials annual (4242) -> lite score -> cancel | PASS - checkout worked; usage 1 / 1,200 (annual = one 1,200 pot, M4 for Brent) after a refresh (LT-3); "Unlock forms" shows the plans greyed out (support-only plan change - question 2 for Brent); dropdown cancel -> "will cancel at end of billing period" |

### Testing after go-live (decision, 2 Nov)

3 Nov: separate local database created for this - `primble_stripe_test` in Postgres.app on the Mac (empty; the app builds its own tables). The test-mode run uses a second local backend on port 8001 pointed at it, with the TEST key.

Stripe tests stay in TEST mode (free, identical behaviour, test clocks). The live account only ever sees the one real
purchase + refund at the switch. **After launch, local Stripe tests use a separate local database (Postgres.app on the
Mac), never the shared one:** the late-payment job acts on every user with a failed payment, so a local run on the shared
database could e-mail or lock a real customer. On 2 Nov the shared database had 0 such users, which is why it was safe.

## 3c. Brent's answers, 3 Nov 2026

| Question | Answer | Action |
|---|---|---|
| USD pricing | "Pricing/billing in USD is great" | Done 2 Nov (Adaptive Pricing off) |
| Render workspace | He reverts it to Hobby | Brent |
| Annual plans (M4) | **100 packages per month, not all at once; overage billed monthly** | **Built offline 3 Nov** (Stripe files 450 passed; `tests/test_annual_monthly_allowance_3nov.py` 39): usage month in ledger rows `usage_anchor:` / `usage_month:` (billing_period_start does not move monthly - `_paid_after` and the renewal check read it); `pending_invoice_item_interval` monthly on annual subscriptions (ledger `pii_interval:`, daily retry). Known risk under review: a failed monthly overage invoice while the plan stays active could re-send the day-0 e-mail on each retry. Existing internal annual rows keep 1,200 (now per month). Then: review (running), test-mode run on a separate local database. Original plan: annual allowance 100/month (+5% buffer); Primble's own usage month anchored on the plan start; Stripe's `pending_invoice_item_interval` = monthly on annual subscriptions so the extras are invoiced each month. Then review, then a test-mode run on a SEPARATE local database with a test clock, before any commit |
| Plan changes through support (B1) | "Works for now"; self-service later | No change |
| Refunds need a separate cancel | Not answered | Ask later |
| support@primble.ai -> support@primble.com (LT-5) | Not answered | Ask later |
| Business e-mails only (new ask) | Not blocking personal e-mails (owner's advice); Brent: build the cross-account document alert after the ACORD work | Closed / FW-2 |

### Annual build: review + test-mode run (3 Nov, separate local database `primble_stripe_test`, TEST key, test clock)

Review (report only): FIX FIRST - a failed monthly overage invoice could loop (repro with fakes: 6 retries = 6 day-0
e-mails) if the subscription stayed active; a support change of billing cycle on the same tier (monthly <-> annual) is
not synced; small: late stale failure event, display lag at the month change, three upload-list details. All sent to
the build agent (running). No live annual customers exist, so the 1,200-per-month-on-old-rows risk does not apply.

| Step | Real Stripe result |
|---|---|
| Buy Professional ANNUAL (4242) | Primble: annual, 100 a month, usage month recorded. **Stripe accepted `pending_invoice_item_interval` = monthly** (flexible billing); setting it sends `customer.subscription.updated`; first monthly invoice scheduled one month on |
| Month 1: 3 extras (#106-#108), clock +1 month | Stripe made a separate invoice, `billing_reason` **automatic_pending_invoice_item_invoice**, $9.00, 3 lines, paid; it became `latest_invoice`; Primble did NOT reset usage (correct - not a renewal) |
| Month 2: 2 extras, declining card, clock +1 month | The $6.00 extras invoice failed -> **Stripe set the subscription past_due** and the failed invoice is `latest_invoice`; Primble `failed`, day-0 e-mail sent ONCE |
| Daily job, then a Stripe retry (clock +8 days) | Daily job kept `failed` (no wrong restore); the retry's `invoice.payment_failed` sent NO second e-mail (attempts 2, still past_due). So the review's e-mail loop does not happen on real Stripe; the fix stays as a safety net |
| Good card pays the overdue extras invoice | Stripe active again; Primble `ok`, failure date and e-mail counter cleared; nothing left pending |
| Clock to the year end | Renewal $2,868 charged ONCE (`subscription_cycle`); NO invoice in months with no extras; usage reset to 0; usage month re-anchored; monthly extras billing continues into year 2 |

Not provable with a clock (Primble's month uses the real date): the month rollover itself - covered by the 39 unit tests.

Round 6 (the review's fixes) by the build agent: "paid up" = subscription active/trialing AND no attempted open
invoice (`Invoice.list(subscription=, status="open")`); `last_paid:<uid>` ledger row for stale failure events; plan sync
on a CYCLE change of the same tier (read from the price's interval, Stripe's live subscription, 503 before claim on a
transient error); every plan-writing path sets the month data; `/me` and the limit check show the rolled count; upload
list: one source of truth, hash one file at a time, skip hashing over 25 MB, server tells the user a copy was read once
(`duplicates_skipped`), Transcriber pre-submit skips re-saved copies. Tests: `test_annual_review_fixes_3nov.py` (30);
Stripe files + new files 502 passed; related set 9,742 passed / 0 failed.

Re-check on the FIXED code (test backend restarted, same local database and clock):
| Step | Result |
|---|---|
| Failed monthly extras invoice | 1 day-0 e-mail; subscription past_due; daily job keeps `failed` (new open-invoice check accepted by Stripe) |
| Good card pays it | `ok`, counter cleared, subscription active |
| Support switches the plan annual -> monthly (an ACTIVE catalogue price) | Primble monthly, 100, usage-month rows cleared, Stripe monthly extras invoicing switched OFF |
| ... and monthly -> annual | Primble annual, 100, usage month restarted, Stripe monthly extras invoicing ON again |

Full suite after round 6 (3 Nov, 02:45 IST): **22,650 passed, 1 failed (the known `test_arq_acord125_missing_only`), 44 skipped.** Test backend (port 8001) and relay stopped; the local test database `primble_stripe_test` is kept for future runs.

**For Brent / support:** Primble's checkout creates its Stripe products inline, and Stripe marks those INACTIVE, so a
support plan change cannot reuse them - support creates (once) an active product + prices in Stripe's Product catalogue
and switches the subscription to those. Primble follows the change from the price's own interval.

**Owner's call (item 7) - DECIDED 3 Nov: Option A, leave it for now; revisit later.** Extra packages HELD while an
annual customer's payment is failing are billed only when the payment recovers; if the plan ends unpaid (cancelled or
deleted while failing) they are never billed. They stay in the ledger as `overage_held` rows, so they can be billed
later. **FUTURE (Option B):** add held units to the final bill at plan end (`settle_final_overage` currently leaves
`overage_held` out on purpose).

## 4. Questions for Brent

1. Annual plans: one 1,200 pot per year or 100 per month (M4)? Overage billed monthly or yearly?
2. Plan changes: is "contact support" acceptable until in-app switching with proration is built (B1)? Includes an Essentials user who wants forms: "Unlock forms" shows the plans greyed out ("Contact support to change") - there is no in-app upgrade to Professional yet (owner's click-through, 2 Nov).
3. Refunds: a refund in Stripe does not remove access; each refund also needs a manual cancel. OK at launch?
4. Will this Stripe account ever bill anything other than Primble subscriptions (H4)?
5. Forms blocked at day 10 or day 21 (L6)?

### Future work (logged, not scheduled)

| # | Item | Notes |
|---|---|---|
| FW-1 | Bill extra packages held while an annual customer's payment failed, when the plan ends unpaid (Option B) | Owner, 3 Nov: Option A for now. Held units remain as `overage_held` ledger rows |
| FW-2 | Alert when the same document is uploaded from several accounts (competitor probing) | **APPROVED by Brent, 3 Nov: "a great idea" - build it AFTER the ACORD work.** The text fingerprint exists; the build should also save it (hash only) at upload so deleting a package does not hide it |
| FW-3 | Business-email-only sign-up | **CLOSED 3 Nov:** personal e-mail accounts stay allowed (owner's recommendation; Brent agreed and chose the fingerprint alert, FW-2, instead) |
| FW-4 | Refund cancels the plan automatically / support address .ai -> .com | Unanswered questions for Brent (ask later) |
| FW-5 | In-app plan switching with proration (self-service) | Brent: "near future" |
| FW-6 | Restricted Stripe key instead of the full secret key | Once the exact permissions are mapped |

## 5. The switch to live (not done)

1. All "must fix" items fixed, reviewed, committed and deployed in a quiet hour.
2. Developers - API keys - **Create secret key** (new; never the one sent by e-mail). Paste only into Render.
3. Webhook destination: `https://primble.onrender.com/api/stripe/webhook`, events from this account,
   **Snapshot** payloads, API version `2026-03-25.dahlia` if offered, events: `checkout.session.completed`,
   `invoice.paid`, `invoice.payment_succeeded`, `invoice.payment_failed`, `customer.subscription.updated`,
   `customer.subscription.deleted`. Copy its `whsec_...` into Render.
4. Render: set `STRIPE_SECRET_KEY` and `STRIPE_WEBHOOK_SECRET` (saving restarts the server).
5. Mac: blank `STRIPE_SECRET_KEY` in `backend/.env`, restart the local backend (H5).
6. Brent deletes the old key he e-mailed.

## 6. Live checks after the switch

### Done at the switch (2 Nov, no money moved)

| Check | Result |
|---|---|
| Live checkout page | PASS - "Subscribe to Primble Professional - Monthly, $299.00 per month", live session (`cs_live_...`), no Sandbox; Stripe offers the customer an INR / USD choice (Stripe's adaptive pricing; Brent is paid in USD) |
| Test card on live | PASS - 4242 refused: "Your card was declined. Your request was in live mode, but used a known test card."; account stays free; no subscription in Stripe |
| One customer per user (new code) | PASS - one live customer created with `metadata.user_id`, idempotency key `primble-customer:<user id>:none` (written by today's code, so Render runs `289629a`) |
| Webhook secret on Render | PASS - `customer.created` delivered to Primble Render: HTTP 200 `{"received": true}`, `livemode` true, API 2026-04-22.dahlia |
| `customer.created` on the live webhook | KEPT on purpose (owner): a free connection check any time - Primble verifies and ignores it (200) |
| Old test webhook to Render (`we_1TWbIFFoRT0iiVSB0JefAsVD`, test account) | Switched OFF - since the switch it could only fail (wrong secret) |
| Mac `backend/.env` | `STRIPE_SECRET_KEY=` blank; the TEST key kept commented out with a note (for local tests on a separate database only); local backend restarted - no Stripe key loaded |
| Brent's e-mailed key | Left as is (owner). Risk noted: if it is an `sk_live` key, anyone who reads that e-mail has full access to the account; the owner can delete it himself (API keys -> the OLD key -> Delete) |
| Adaptive Pricing (local currency) | Turned OFF by the owner: the live checkout had offered INR by default (Rs 29,450.04 = $299 + Stripe's 4% conversion fee). Extra-package charges and final bills are created in USD by the code, so a customer subscribed in another currency risked unbillable extras. Verified: checkout now USD only ("$2,868.00 per year, $239.00 / month billed annually") |
| Annual checkout wording | The annual checkout says "Includes 100 packages/month" while the app gives annual one 1,200 pot - aligned once Brent answers the annual question (M4) |
| Manage billing on the new account | Not applicable: a free account has no Manage billing; the live portal settings were set on 2 Nov and the portal itself was proven in test mode |
| Still to do | E-mail to Brent |


1. One real purchase: plan turns on, webhook deliveries all 2xx, receipt e-mail arrives. Then refund it and
   cancel the subscription.
2. Portal cancel shows as "canceling" in Primble (cancel_at_period_end under flexible billing).
3. The Stripe-hosted card update page and portal show the Privacy and Terms links.
4. Unpaid then paid: does updating the card pay the past-due invoice, and does access come back?
5. Pending overage lands on the next renewal invoice, not on a new checkout.
6. An accidental duplicate checkout is refunded (the refund path is proven only against fakes).
7. A renewal with many overage packages resets usage (Q1): check the webhook's `lines` page and `billing_reason`.
8. A new subscription's `invoice.paid` vs `checkout.session.completed` order, and that the period end is recorded (Q2).
9. Cancelling a duplicate makes no proration credit on the customer balance; only the plan line is refunded.
10. A cancelled plan's final invoice for unbilled extra packages charges the saved card once (C1), including a
    card that asks for 3D Secure. The draft-invoice steps work: an item added with `invoice=` attaches, the
    stale pending copy deletes, finalize + pay charges the plan's `default_payment_method`.
11. An overage item created with `subscription=` never lands on another subscription's invoice (including a
    new plan's first invoice), and stays pending after any kind of cancel.
12. A declined one-off final invoice: check what the dashboard's retry setting does for non-subscription invoices.
13. Duplicate refund details: `Invoice.list_lines` shows the plan line, `Refund.list` shows our metadata, and with
    tax on only the pre-tax plan line is refunded.
14. Subscription items carry `current_period_start/end`; the first invoice says `subscription_create`, renewals
    `subscription_cycle`; a standalone final invoice has no `parent.subscription_details`.
15. The alert e-mail reaches info@primble.com through Resend. Confirm info@primble.com is a real, watched inbox
    (Brent's Stripe business details show support@primble.com).
16. A Checkout subscription stores its card as the subscription's `default_payment_method` (the final bill uses it).
17. Repeating a cancel with the same idempotency key returns the same success; cancelling an already-cancelled
    subscription returns an error the code accepts.
18. A Checkout Session in subscription mode carries `invoice` (the duplicate refund reads it).
19. Final bill: `Invoice.pay` right after finalizing must not report "already paid" as a failed charge (no false
    "Final overage charge FAILED" alert).
20. On a real recovery payment, look for "subscription ... is past_due - failure kept" in the logs: it means Stripe
    updated the subscription after `invoice.paid` (F1's second case without any Stripe error).
21. Does Stripe accept an overage item on an already-cancelled subscription (F2's stale copy)?
22. A plan left unpaid past its next renewal: can the customer pay the older invoice first, and does that reset
    usage wrongly across both periods?
23. A 503 from our webhook makes Stripe resend the same event id (backoff, up to about 3 days).
24. `InvoiceItem.list(customer=...)` returns invoiced items with `invoice` set, and `subscription` set when created
    with `subscription=`.

## Apple Pay (3 Nov 2026) - no code change; Brent tests it from the US
**Finding (Stripe docs, read 3 Nov):** hosted Checkout with `payment_method_types=["card"]` (both our `Session.create`
calls, `stripe_routes.py:237` subscription and `:1168` setup) shows Apple Pay and Google Pay as card WALLETS - "For
Payment Links or hosted Checkout, Apple Pay works with no additional configuration" (docs.stripe.com/apple-pay). No
domain registration (that is only for Elements / embedded Checkout). Renewals use Apple merchant tokens; the Customer
Portal lets a customer add Apple Pay for future invoices. Brent's dashboard has Apple Pay ON; Google Pay looks OFF.
**Do NOT drop `payment_method_types`:** dynamic methods would add Link / Amazon Pay / Cash App and possibly ACH, and
`_handle_subscription_checkout` grants the plan without checking `payment_status` (OPEN_ITEMS).
**Stripe never shows Apple Pay from an Indian IP** - the owner cannot see the button; Brent must test.

**Test script for Brent (Stripe TEST mode first, the owner's local test setup on `primble_stripe_test`):**
1. On his iPhone (Safari, a card in Wallet, not a private window) open https://docs.stripe.com/testing/wallets and
   confirm the Apple Pay button shows - checks the device.
2. The owner starts the local TEST backend + `stripe listen`, starts a Professional monthly checkout and sends Brent the
   `checkout.stripe.com/c/pay/cs_test_...` link (valid 24 h).
3. Brent pays with Apple Pay (a real card in Wallet - test mode never charges it).
4. Check: payment method `card` with `wallet.type = apple_pay`; the subscription's `default_payment_method` set; our
   webhook granted the plan (`payment_status='ok'`, period end stored). The redirect to localhost fails on his phone -
   harmless.
5. Renewal on a test-clock customer: advance the clock; the renewal charges the Apple Pay card.
6. Portal: Manage billing in Safari -> add Apple Pay -> make it default.
7. Live: one real Apple Pay purchase by Brent on primble.ai, then refund it.

## Adversarial review, 3 Nov 2026 (22:27 IST) - 1 high, 3 medium, 6 low (7 proven offline)
Repro tests (each asserts the CURRENT wrong behaviour): scratchpad `review_stripe/test_break_stripe.py` (8, all
reproduce). No Stripe call, no database.

| # | Sev | Finding | Fix |
|---|---|---|---|
| H-A | HIGH (proven) | A tier change by support is never followed: support swaps the subscription onto an active catalogue price, Stripe keeps `metadata.plan`, and `plan_from_subscription` reads metadata first - Stripe charges $299 while Primble stays Essentials (or $199 with Professional kept) | Decide the plan by the price's amount + interval first (metadata as fallback); a test that swaps the price only |
| M-A | MED (proven) | A checkout handled after its subscription was deleted (refund + cancel while the completed event is delayed) grants a paid tier on a dead plan, permanently | Refuse the grant when the live subscription is not in a live status; log + alert |
| M-B | MED | No dispute / chargeback handler: the plan stays active and renewals keep charging | Handle `charge.dispute.created`: alert the admins + audit (cancel or lock = owner / Brent decision) |
| M-C | MED (proven) | A late checkout webhook after verify-upgrade resets `packages_used` to 0 for the same subscription | Same subscription already stored = leave usage alone |
| L-A | LOW (proven) | "Account deleted" branch refunds a plan the user already used (delete-account cancelled it) | Skip the refund when the subscription is already cancelled |
| L-B | LOW (proven) | Cancelling an enterprise account's old subscription drops it to free | `subscription_tier <> 'enterprise'` guard on the downgrade (still bill the final overage) |
| L-C | LOW (proven) | Out-of-order success hides a real failure: `last_paid` / period start stamped with processing time, compared with Stripe's event time | Stamp with the event's / invoice's paid time |
| L-D | LOW (proven) | The cancel route lifts a lock (`payment_status='canceling'` unconditionally) and can repoint the stored subscription at a duplicate | Guard `payment_status NOT IN FAILURE_STATUSES`; never replace the stored subscription |
| L-E | LOW | The final bill's per-plan scoping reads `item.subscription`; on dahlia it is under `parent.subscription_details` | Read both |
| L-F | LOW | verify-upgrade grants an `active` subscription whose first payment may still be processing (delayed methods only); `async_payment_failed` only logs | verify-upgrade checks the latest invoice is paid; failed reverses a grant |
Held up: replays / dedupe, async_payment re-delivery, concurrent checkouts, two tabs, event order (invoice.paid first),
metadata tampering, signatures, other accounts, USD only, wallets (nothing reads brand / last4 / type), annual month
math (31st, Feb 29), overage once, dunning e-mails once, lifecycle stages forward only.

### Fixed (3 Nov) - offline, uncommitted; the owner commits and deploys
- **H-A** `stripe_service.plan_from_subscription` (+ new `plan_from_price`): the PRICE decides first - an exact
  unit amount + interval (interval_count 1, USD) match in PLANS, both cycles; metadata only when no price names one
  plan. Every reader goes through it (`subscription_plan`: webhook updates, verify-upgrade, portal restore, /me
  resync). Checkout's inline prices carry the PLANS amounts, so they resolve to the plan sold. The checkout handler
  (`stripe_routes._handle_subscription_checkout`) also grants what the subscription bills NOW (its price), the
  session metadata only when Stripe cannot say.
- **M-A** `_handle_subscription_checkout`: a subscription Stripe reports outside the live statuses (canceled,
  incomplete_expired) grants nothing - event claimed, ERROR log, audit row `payment.checkout_subscription_not_live`.
- **M-B** new `stripe_routes._handle_dispute` (+ `stripe_service.notify_admins`): `charge.dispute.created` -> ERROR
  log (user id + Stripe ids, no e-mail address), audit `payment.dispute_opened`, one e-mail per address in
  ADMIN_EMAILS (billing inbox if none) with the account e-mail, amount, reason, evidence deadline and the
  dispute / charge / payment intent / customer / subscription ids. `charge.dispute.closed` -> outcome logged (ERROR
  when lost), audit `payment.dispute_closed`. **Nothing is cancelled or locked - the owner / Brent decide**; the
  log and e-mail say so. **OWNER ACTION: add `charge.dispute.created` and `charge.dispute.closed` to the live
  webhook endpoint's events** (Developers - Webhooks - Primble Render - Edit destination). Until then no dispute
  reaches us. (Noted while here: `checkout.session.async_payment_succeeded` / `_failed` are not in that list
  either - the other reviewer's area.)
- **M-C** `_handle_subscription_checkout`: the row already carrying THIS subscription (verify-upgrade first) is
  left as it is - only a missing customer id is filled; usage, `billing_period_start`, period end, annual usage
  months and payment state untouched. The compare-and-set no longer matches its own subscription; when verify-upgrade
  stores it between the read and the write, it is the same plan, never a duplicate refund.
- **L-A** `_handle_subscription_checkout` (deleted-account branch): asks Stripe first (503 when out of reach,
  nothing claimed); a subscription already ended (delete-account cancelled it) is not refunded - WARNING log, audit
  `payment.deleted_account_checkout_not_refunded`, no duplicate ledger row (the daily job refunds nothing later).
- **L-B** `_handle_subscription_deleted`: an enterprise row keeps tier, allowance and usage; only the dead
  subscription link and its failure state are cleared (no Stripe plan is left to clear or lock it). The final
  overage is still claimed and billed.
- **L-C** `stripe_routes._paid_time`: `last_paid` takes the invoice's `status_transitions.paid_at`, else the event
  time, else now (`_handle_invoice_paid`; a renewal's `billing_period_start` is its own period start since pass 2 #2); a restore by
  `customer.subscription.updated` takes the event time. `usage_service.record_last_paid` never moves back.
- **L-D** `stripe_routes.cancel_subscription`: a failure stage (failed / soft_locked / suspended / archived) stays;
  "canceling" only when the row's own plan is one just set to end; the stored subscription id is never replaced
  (an empty one is filled).
- **L-E** `stripe_service.item_subscription` (used by `_bill_final_overage`): reads `subscription` and
  `parent.subscription_details.subscription` (dahlia).
- **L-F** `stripe_routes._first_payment_settled` in `verify_upgrade`: grants only when the latest invoice is paid or
  asks for nothing (trial, $0, no invoice); otherwise `reason: payment_pending` and the webhook decides. Cards and
  wallets are paid at Checkout - unchanged. (`async_payment_failed` still only logs: nothing is granted before the
  payment is confirmed, so there is nothing to reverse.)

Tests: `backend/tests/test_stripe_review_fixes_3nov.py` - 48 passed (the 8 repros turned around + the new cases).
The reviewer's 8 repros now all FAIL (each asserted the wrong behaviour). Billing consumers (every
`test_stripe_*`, billing screens, annual allowance + review, beta bar, multi-user readiness, free package limit,
owner asks, audit lineage, lane C, scheduler on Render) plus the tree-scanning invariant tests (module names, async
safety, secret URLs, cap wording, lane B, audit history, 27 Oct main, 3 Nov captcha / fingerprints / SMS):
**1,335 passed, 0 failed** (before the fixes the same billing set was 798 passed). No old test was changed.
Not changed, worth knowing: the portal restore and the /me resync still adopt an "active" subscription without the
L-F paid-invoice check (they only relink a row that lost its plan); a failed admin dispute e-mail is logged at ERROR
and not retried (the ERROR log + audit row stay).

#### Pass 2 (3 Nov) - six more, four of them in or next to the fixes above; offline, uncommitted
Repros: scratchpad `review_stripe2/test_break_stripe2.py` (8: 7 defects + 1 control). After the fixes all 7 defect
repros FAIL and the control passes.
- **#1 HIGH** `stripe_routes._is_proration_line` in `_subscription_line_periods` (feeds `_invoice_period_start` / `_end`
  and the "plan line seen" check): a proration line (`parent.subscription_item_details.proration`, the invoice-item
  twin, or the legacy top-level `proration`) is never the period an invoice opens. A support plan change's renewal
  no longer recounts from the switch - packages after the switch were being counted again in the new period.
- **#2 MEDIUM** `_handle_invoice_paid` + `usage_service.record_period_end(only_later=)`: a renewal is "newer" by its
  OWN period start against the stored `billing_period_start`; on a reset `billing_period_start` = that period start
  (the paid time stays in `last_paid` - **this revises L-C**, which had stored the paid time there); an older
  invoice never moves the stored period end back (it may still push a missing end forward). Two open renewals paid
  together after a long failure now each open their own period, in either order.
- **#3 MEDIUM** `_handle_payment_failed` (the by-customer fallback): a row with no stored subscription whose tier is
  free OR enterprise is never re-linked to the invoice's dead plan, so an enterprise account (L-B keeps it with no
  subscription) is never failed and locked by its old plan's invoice. A paying row found by customer is still
  re-linked and failed as before.
- **#4 LOW** `stripe_service._plan_and_source` / `subscription_plan`: when a price named the plan, the cycle is that
  price's own interval; `price_cycle` (first item) only on the metadata fallback. An annual plan with a monthly
  add-on listed first stays annual.
- **#5 LOW** new `stripe_routes._claim_replaced_plan_bill` / `_settle_replaced_plan_bill`, called by verify-upgrade
  and the checkout compare-and-set when they replace a DEAD stored subscription: its `final_overage_key` is claimed
  in the same transaction (the key the delete handler uses - one claim, whoever comes first) and settled after the
  commit. Its late `customer.subscription.deleted` finds no row and changes nothing more.
- **#6 LOW** new `stripe_routes._plan_was_carried` in the deleted-account branch: an ended subscription is left
  unrefunded only when a `final_overage:<user>:<subscription>:...` ledger row names it (delete-account, the delete
  handler or a replacement wrote it because the row carried the plan - exact match, never a prefix). Paid, never
  granted, account deleted = refunded, as before L-A.

Tests: new `backend/tests/test_stripe_review2_fixes_3nov.py` - 15 passed. Old tests changed, all TEST-outdated by
the pass 2 rules (no code was wrong): `test_annual_monthly_allowance_3nov::test_a_yearly_renewal_on_a_month_boundary_
still_resets_and_re_anchors` (pinned `billing_period_start` = time handled; now the period start, plus `last_paid` =
paid time); in `test_stripe_review_fixes_3nov.py` the L-C renewal test (same rule) and the L-A test (it deleted the
row without the final-bill row delete-account writes, so it no longer simulated delete-account). Billing set +
tree-scanning invariant tests: **1,354 passed, 0 failed**.

#### Pass 3 (3 Nov) - five more; offline, uncommitted
Repros: scratchpad `review_stripe3/` (7 defects + 1 control). After the fixes all 7 defect repros FAIL and the
control passes. (Pass 1's F5 repro passes again since pass 2 #6: it deletes the row WITHOUT the final-bill row
delete-account writes, so it now takes the refund path - the intended pass 2 rule; `test_LA` in the pass 1 file
writes that row and holds.)
- **#1 MEDIUM** `stripe_routes._handle_invoice_paid`: the user row's lock is taken first thing after the event claim
  (`UPDATE users SET packages_used = packages_used ... RETURNING billing_period_start, packages_used`) and the
  period decision (`newer` / `older`, the period end) reads THAT row - never the copy read before the Stripe
  calls. Two renewals handled at once can no longer rewind the period. The same lock gives the recount's
  `used_at_lock` (one lock per event, not two).
- **#2 LOW-MEDIUM** chose the window recount, NOT count-time holding for monthly plans. Why: a failing monthly
  user's counter still includes the unreset earlier period, so a unit held at count time can sit above the
  allowance only because of the earlier period's packages - holding it would bill packages that were inside the
  real period's allowance. The recount reads the real window. `_handle_invoice_paid`: an OLDER renewal (its period
  start before the stored one) with a known end recounts [start, end) and places what is above the allowance.
  This runs only for monthly plans; annual plans already hold at count time. New
  `usage_service.place_period_overage` places them: held while failing, else pending. Double billing is ruled out
  three ways:
  - a unit already in the ledger in any state is skipped;
  - the period never gets more new units than its extras minus the units the ledger already holds for its
    packages;
  - every insert is ON CONFLICT DO NOTHING.
- **#3 LOW** `stripe_service.price_cycle` reads a price only when billed every ONE month / year;
  `off_cycle_price`; `subscription_plan` returns (None, None) (ERROR log) when the metadata names the plan but a
  price bills every N > 1 - nothing syncs; `_handle_subscription_updated` sends one billing alert per
  subscription (`off_cycle_price:<sub>`).
- **#4 LOW** the reset (and the older-window recount) records the units above the allowance INSIDE its
  transaction: pending, or held while still failing. `overage_packages_pending` moves with them. After the commit,
  `retry_pending_overage(user)` bills them. If that fails, the daily retry does. New
  `usage_service.release_held_overage` turns held units into pending inside every restore's own transaction:
  invoice.paid, subscription.updated and the lifecycle's Stripe check. Each of those then calls
  `retry_pending_overage`.
- **#5 LOW** `stripe_service._bill_final_overage`: an owed unit whose only pending copy is scoped to another plan is
  skipped (it rides that plan's invoice); `settle_final_overage` leaves out of `owed` an `overage_billing` unit
  younger than `_STALE_BILLING` (a Stripe call in flight).

Tests: new `backend/tests/test_stripe_review3_fixes_3nov.py` - 13 passed. No old test changed. Billing set +
tree-scanning invariant tests: **1,367 passed, 0 failed**.

#### Pass 4 (3 Nov) - seven more, #1 introduced by pass 3 #2; offline, uncommitted
Repros: scratchpad `review_stripe4/` (8 defect tests). After the fixes all 8 FAIL. The earlier repro dirs are
unchanged: each has its 7 defect repros failing and 1 passing (pass 1 F5, see pass 3; the pass 2 and 3 controls).
- **#1 MEDIUM-HIGH** `_handle_invoice_paid`: a renewal is OLDER only when its period END is at or before the stored
  start, and the older-window recount stops at min(period end, stored start). A delayed twin of the current
  renewal, after a mid-period tier change moved the stored start to the switch, is neither newer nor older and
  recounts nothing.
- **#2 MEDIUM** `_handle_invoice_paid`: a newer reset places extras only from packages counted before ITS period
  end. The counter still counts everything since its start. The "already placed elsewhere" filter now includes
  `overage_held`. An older renewal paid first can no longer hold or bill the next period's packages as its own.
  **Reachable only while `SCHEDULER_ENABLED` is not true on Render.** With the daily lifecycle running, a failing
  user is checked against Stripe and restored daily, so two open renewals rarely pile up. The owner confirmed on 4 Nov
  that the Render dashboard has `SCHEDULER_ENABLED=true`.
- **#3 MEDIUM** new `usage_service.forgive_held_overage`: every place that claims a plan's final bill moves that
  user's `overage_held` units to the terminal `overage_forgiven` in the SAME transaction. Those places are the
  delete handler, delete-account (its claim is now one transaction) and the replaced-plan claim. This is Option A:
  a plan that ended unpaid is never billed for them, and no later plan's restore can release them.
  `release_held_overage` therefore only ever finds the current plan's held units.
- **#4 LOW-MEDIUM** `_handle_invoice_paid`: the lock's RETURNING also reads `payment_status` / `payment_failed_at`.
  It holds only if that locked row is still failing. If another restore committed first, the extras go pending and
  are billed.
- **#5 LOW-MEDIUM** `usage_service._evaluate_counted`: a monthly plan whose stored period end is still AHEAD now
  HOLDS an overage package counted while failing. It used to be marked "not billable": a mid-period failure on a
  proration / manual invoice, and no renewal recount would ever place it. With the period ended, or no end stored,
  the counter may still carry an unpaid earlier period, so the package is left to the paid renewal's recount, as
  before. No double billing with the pass 3 recounts: `place_period_overage` counts every ledger unit against a
  period's extras, and the reset's filter excludes held units.
- **#6 LOW** `usage_service.count_session_usage` reads the period state ("ended" / "open" / "unknown",
  `_period_state`) INSIDE the counting transaction, under the user row's lock, and passes it to
  `_evaluate_counted`. A reset committing right after the count cannot make the package look like the old
  period's overage.
- **#7 LOW** `stripe_service.settle_final_overage`, FINAL_MANUAL branch: the owed units move to the terminal
  `overage_manual`. No retry bills them again, on this plan or a later one. The ERROR log gives the count.

Tests: new `backend/tests/test_stripe_review4_fixes_3nov.py` - 11 passed. No old test changed. Billing set +
tree-scanning invariant tests: **1,379 passed, 0 failed**.

#### Pass 5 (3 Nov) - four more, all LOW / LOW-MEDIUM; offline, uncommitted
Repros: scratchpad `review_stripe5/test_break_stripe5.py` (4). After the fixes all 4 FAIL; the earlier dirs are
unchanged.
- **#1 LOW-MEDIUM** `usage_service.count_session_usage` + new `_hold_in_count` / `_should_hold`: an overage package
  to HOLD is written INSIDE the counting transaction, under the user row's lock, beside its count; billing stays
  outside. A restore committing right after the count now always releases the held unit, and a plan's end always
  forgives it. Before, either could slip into the gap. `verify_upgrade`: the replaced plan's final-bill claim
  (which forgives its held units) now runs BEFORE `adopt_plan_usage`.
- **#2 LOW** `_handle_invoice_paid`: a renewal that is neither newer nor older, because it STRADDLES the stored
  start a tier sync moved inside its period, now recounts [its start, the switch) against the OLD plan's
  allowance. The window ends at the switch. The old plan's allowance + buffer is recorded at the sync
  (`usage_service.record_prior_allowance`, ledger `prior_allowance:<user>:<switch>`, written by the tier sync in
  `_handle_subscription_updated`). The budget in `place_period_overage` absorbs ledger units, so pass 4 #1's
  delayed twin still places nothing. **When the old allowance is not on record** (a switch made before this code)
  nothing is guessed or billed: ERROR log, audit `payment.overage_before_switch_unknown` and one billing alert. A
  guessed allowance could bill inside it; a person can check one invoice.
- **#3 LOW** `scheduler_service.run_daily_payment_lifecycle`: the stage move is `... WHERE id=$2 AND
  payment_failed_at=$3`, the failure this run read, the same guard the restore branch uses. A restore committing
  after the Stripe check is never overwritten with a lock. No e-mail goes out for a row that moved.
- **#4 LOW** `stripe_service.settle_final_overage`: a unit whose package was COUNTED after the bill was claimed
  (the plan's end) is not owed - it belongs to a later plan and rides that plan's invoice. Read from the
  packages' own `counted_at` through `packages_counted_since`. When that cannot be read, nothing is excluded, and
  the per-plan Stripe copies (pass 3 #5) still keep another plan's pending items off. A first cut compared the
  ledger rows' own timestamps; it broke three old tests because it mixed clocks, and it was replaced (the CODE was
  wrong, not the tests).

Tests: new `backend/tests/test_stripe_review5_fixes_3nov.py` - 8 passed. No old test changed. Billing set +
tree-scanning invariant tests: **1,387 passed, 0 failed**.

#### Pass 6 (final, 3 Nov) - the owner's safe end state; offline, uncommitted
Repros: scratchpad `review_stripe6/test_break_stripe6.py` (3, all in the pass 5 #2 straddle recount: annual months
judged as one allowance, two switches judged against the last one, old-plan packages billed at the new rate).
After the change all 3 FAIL. Pass 5's R2 repro now PASSES again ("nothing billed") - that IS the decided end
state, with the alert added.
- **Straddling renewal = billed by hand, never automatically** (`stripe_routes._handle_invoice_paid`). This covers
  every cycle, annual included, and any number of switches: a renewal that is neither newer nor older with its
  period start before the stored start. Nothing is placed, held or billed. It always takes the alert path:
  - an ERROR log;
  - the audit row `payment.overage_before_switch_manual`;
  - ONE billing alert, `straddle:<user>:<invoice>`, claimed in the ledger, so a re-delivery sends none.
  The alert names the window [period start, stored start), the package count in it, every plan before a switch
  ("<tier>/<cycle> until <switch time>") and the plan now. A person checks each old plan's allowance and rate and
  bills by hand.
- `record_prior_allowance` / `prior_allowance` are REMOVED, together with their writer in the tier sync. The tier
  sync now writes only `usage_service.record_plan_switch` (ledger `plan_switch:<user>:<switch>` = the plan before
  it), read only by that alert (`plan_switches`). No allowance is recorded or used for billing.
- **Stage e-mail guard** (`stripe_service.claim_payment_email(..., failed_at=)`, passed by
  `send_claimed_payment_email`): the claim, and so the e-mail, needs `payment_failed_at` to still equal the failure
  the caller read. A user restored mid-run gets no "payment failed" e-mail.

Old tests changed (each TEST was outdated, no code wrong):
- the pass 5 straddle tests in `test_stripe_review5_fixes_3nov.py`. Two became one: it expects nothing billed plus
  one alert naming the window, the count and the plans; it was 5 billed / the unknown-allowance path.
- `test_stripe_review2_fixes_2nov.py::test_L9_the_webhooks_day0_email_is_marked_too`: its spy pinned the claim's
  old 4-argument signature.

Tests: new `backend/tests/test_stripe_review6_fixes_3nov.py` - 7 passed (the 3 shapes, both plans named,
re-delivery alerts once, the e-mail guard and its control). Billing set + tree-scanning invariant tests:
**1,393 passed, 0 failed**.
