# Stripe Live Readiness

The running log for moving Primble's payments from the developer's Stripe test account to Brent's live
Stripe account. Started 2 Nov 2026. Update it with every change, fix and verification.

Status words: **Open** (found, not fixed) · **Fixed** (code changed, tests pass offline) · **Verified**
(confirmed on the live site) · **Decision** (waits on Brent or the owner) · **Done** (a setting, confirmed).

## Where things stand

- Brent's live Stripe account is configured (section 1). Payments and payouts are active, no tasks due.
- Production still runs on the **test key** (`sk_test_...`). The switch to live has NOT happened.
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
- Nothing in this file is committed or deployed yet.

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
| Developers | API keys / webhooks | No live key created yet; no webhook yet | Created at the switch |

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
| A1 | Owner's check: plan dropdown on his Professional account (after a refresh) | PASS - "Professional · Monthly", 42 / 100, "To change your plan, contact support@primble.ai.", Manage billing, Cancel Subscription |
| LT-2 check | Owner signed out and in again with Google, no refresh | PASS - dropdown showed 42 / 100 at once |
| A2 | Owner: home page plan section | Changed on the owner's ask: the line "To change your plan, contact support@primble.ai. Manage billing" removed from the home page's plan section (it stays in the account dropdown and in the upgrade window). `test_billing_screens_2nov.py` updated (the TEST pinned the old placement); 28 screen tests pass; build clean |
| A2b | Owner: a paying user's other plan cards | Changed on the owner's ask: plain grey text "Contact support to switch" -> a greyed-out, unclickable button "Contact support to change" (hover: "To change your plan, contact support@primble.ai."), on the home page and in the upgrade window alike; pinned in `test_billing_screens_2nov.py`; 28 screen tests pass; build clean. PASS - owner confirmed on screen (Essentials greyed, Professional "Current plan", Enterprise "Contact sales") |
| A3-A6 | Owner: Manage billing; cancel and renew on Stripe's page; `/?open=billing` | PASS - billing page opens (Primble Professional, $299/month); cancel -> dropdown "Subscription will cancel at end of billing period"; "Don't cancel" -> back to normal; the e-mail link opens the billing page by itself |
| A-drop | Owner: "Cancel Subscription" in the Primble dropdown | PASS - no redirect by design (Primble tells Stripe directly): 20:47:51 Stripe `cancel_at_period_end` true from our API call, dropdown "will cancel". Undone at 20:48:48 through Stripe's billing page; now active, not cancelling, Primble `ok` - database and Stripe agree |
| B | Owner: free test account (free package already used) -> bought Essentials annual (4242) -> lite score -> cancel | PASS - checkout worked; usage 1 / 1,200 (annual = one 1,200 pot, M4 for Brent) after a refresh (LT-3); "Unlock forms" shows the plans greyed out (support-only plan change - question 2 for Brent); dropdown cancel -> "will cancel at end of billing period" |

### Testing after go-live (decision, 2 Nov)

Stripe tests stay in TEST mode (free, identical behaviour, test clocks). The live account only ever sees the one real
purchase + refund at the switch. **After launch, local Stripe tests use a separate local database (Postgres.app on the
Mac), never the shared one:** the late-payment job acts on every user with a failed payment, so a local run on the shared
database could e-mail or lock a real customer. On 2 Nov the shared database had 0 such users, which is why it was safe.

## 4. Questions for Brent

1. Annual plans: one 1,200 pot per year or 100 per month (M4)? Overage billed monthly or yearly?
2. Plan changes: is "contact support" acceptable until in-app switching with proration is built (B1)? Includes an Essentials user who wants forms: "Unlock forms" shows the plans greyed out ("Contact support to change") - there is no in-app upgrade to Professional yet (owner's click-through, 2 Nov).
3. Refunds: a refund in Stripe does not remove access; each refund also needs a manual cancel. OK at launch?
4. Will this Stripe account ever bill anything other than Primble subscriptions (H4)?
5. Forms blocked at day 10 or day 21 (L6)?

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
