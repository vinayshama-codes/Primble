# 25sepChanges - Orbin client feedback and our re-run

**Status: RECORDED ONLY. Nothing has been changed yet.** Written 29 Sep 2026, before any fix.

How this file works:
1. **Section 1** - the baseline: our fresh run of the client's own declarations, before any change.
2. **Section 2** - the client's test document (`Orbin_Testing_09_22_2026.pdf`), item by item, with
   what today's run shows for each one.
3. **Section 3** - other problems this run shows that the client did not list.
4. **Section 4** - what the client wants (to be added when the owner sends it).
5. **Section 5** - the fix plan (proposed; the decisions wait for the owner's yes).
6. **Section 6** - the fix log. One entry per item as we fix them, one at a time.

---

## 1. The baseline run (before any change)

| | |
|---|---|
| Session | `8992d874-2a2d-4144-89dc-a663fc62b1d7` (28 Sep 2026, 18:23 UTC / 23:53 IST) |
| Build | local, uncommitted work on top of `8b005ad` (FR125 round 2 fixes, extraction **v25**) |
| Document | `2526 Package Policy (Complete Copy) (4).pdf` - 271 pages, 699,844 characters of text. Classified **Dec Page, strong match** |
| Forms generated | ACORD 125 only |
| Login | Astrea IT Services / Vinay Sharma. The client's run used ThinkSmith Agency LLC / Michelle Smith |
| Re-grade it | `py backend/scripts/dump_a125_run.py 8992d874-2a2d-4144-89dc-a663fc62b1d7 > <scratch>.json` (real client data - keep the dump out of the repo) |

### 1.1 What the declarations actually print (checked in the text of all 271 pages)

This is the evidence every fix below has to be measured against.

| Topic | What the dec prints | Where |
|---|---|---|
| Named insured | ORBIN CONTRACTING LLC, 4800 DAHLIA ST # D13, DENVER CO 80216-3121 | page 1 |
| Producer (agency) | **COMMERCIAL RISK SOLUTIONS, INC.**, 9780 S MERIDIAN BLVD STE 400, ENGLEWOOD CO 80112-6072. AGENT NO. W6258-0001, **AGENT PHONE 303-996-7800** | page 1; again on page 3 ("AGENT: AW 6258", "DIRECT BILL AGENT PHONE") |
| Producer e-mail | **Not printed anywhere** (every "e-mail" in the text is policy wording) | - |
| Carriers | EMPLOYERS MUTUAL CASUALTY COMPANY (auto, inland marine, umbrella); EMC Property & Casualty Company (GL). **No NAIC printed** | section decs |
| Policies | Auto 6E7-40-02---26; GL BBC7263 - 26; Inland Marine 6C7-40-02---26; Umbrella 6J7-40-02---26 | section decs |
| Policy period | 07/15/2025 to 07/15/2026 on every policy | all section decs |
| Premiums | Property No Coverage; **Liability $3,954; Inland Marine $300; Automobile $2,991; Umbrella $3,418**; Crime and WC No Coverage; **Estimated Total $10,663** | page 1 "Coverages and Premium" |
| Billing | "DIRECT BILL" | page 3 |
| Audit | "Audit Period: Annual" (GL) | GL dec |
| GL class codes | **91580** Contractors - Executive Supervisors (payroll $39,300, premium $1,305); **91585** subcontracted work (total cost $350,000, premium $1,198 + $803) | page 211 |
| SIC / NAICS | **Not printed anywhere** (the only "NAICS" is a rating notice) | - |
| Business description | "INSURED IS: LLC BUSINESS DESC: COMMERCIAL GENERAL CONTRA" (cut off by the carrier's system) | page 3 |
| Premises | "Location of All Premises Owned, Rented or Occupied - Rated Locations: 4800 Dahlia St # D13, Location 1". **The words tenant / owner / city limits are never printed for this location** | page 212 |
| Property coverage | No Coverage (so no building is insured) | page 1 |
| Insured contact person, phone, e-mail | **None printed.** The only phone numbers are the agent's, EMC claims (888-362-2255) and EMC's servicing office (720-200-3700). ERIN ROYAL appears once, as the auto policy's Drive Other Car named individual | - |
| Loss history | None | - |

### 1.2 Pre-form review screen

- **Overview:** "Major Gaps", 5 of 12 key details in place.
  - In place: legal name, mailing address, lines of business, entity type, operations description.
  - Missing: proposed effective date, contact information, FEIN, annual revenue, number of employees,
    years in business, NAICS or SIC.
  - The card still says "Your Submission Quality Score is calculated after forms are generated."
- **Documents:** 1 document, Dec Page, strong match, all clear.
- **Submission Integrity:** verified.
- **Data Consistency:** nothing to confirm.
  - Policies table: 4 rows, NAIC "-" on each.
  - "Carrier: 4 policies, 2 values - not a conflict".
  - "Policy Number: 4 policies, 4 values - not a conflict".
- **Hard stops:** none.
- **Warnings (3):**
  1. ACORD 125 minimum field missing: Proposed effective date.
  2. ACORD 125 minimum field missing: Contact information.
  3. Driver schedule not provided.
- **"Important" block:** repeats two of those warnings. Its text is broken: "Fix: Provide this value manually, or upload a
  document that states it.) (+1 related" (the same broken text is in the client's screenshot, item 3).

### 1.3 SQS after generating ACORD 125

- **ACORD 125 form score: 57 (F, Not Ready).**

  | Pillar | Score |
  |---|---|
  | Structural | 60% |
  | Exposure | 40% |
  | Property | 100% |
  | Loss History | 25% |
  | Umbrella | 100% |
  | Narrative | 40% |

- **Package score: 64 / 100, "Major Gaps" (contractor).**

  | Pillar | Score | Categories |
  |---|---|---|
  | Structural | 54% | Form Fill Rate 100% |
  | Exposure | 72% | Operations 92%, Coverage 100%, Payroll/Employee 100%, Revenue/Sales 100%, Cross-Document 100%, Auto Completeness 80%, WC 100% |
  | Property | 100% | COPE and Location not applicable |
  | Loss History | 25% | Limited |
  | Umbrella | 100% | Complete, follow form confirmed |
  | Narrative | 40% | Limited |

- The stored cap reason is the missing proposed effective date.
- **Best solutions add up to 35.7 points:**
  - Structural +11.5 (proposed effective date).
  - Loss history +11.2.
  - Exposure +7 (auto completeness, operations description).
  - Narrative +6.

### 1.4 Pre-download "SQS Review" (8 items, verbatim in short)

1. Narrative is missing account overview, years in business, management experience, risk controls (+3 more). Up to +6.
2. No loss history provided. Up to +6.
3. "If this business is a new venture..., confirm New Venture status". Up to +6.
4. ACORD 125 missing: effective date. Up to +5.
5. ACORD 125 missing: contact info. Up to +5.
6. "ACORD 125: 19 fields left blank on purpose - a value was found for each but could not be true for that box ...
   (AdditionalInterest FullName, CancelNonRenew UnderwritingConditionCorrectedDescription, CommercialStructure
   InstallationRepairWorkOffPremisesPercent, +7 more)".
7. "ACORD 125: 4 high-impact questions were left blank by the AI (no value found in the documents):
   CommercialPolicy ApplicantOwnLeaseOperateDronesExplanation, AdditionalInterest Interest LeasebackOwnerIndicator,
   AdditionalInterest FullName, +1 more".
8. "Field QA: 12 required fields still empty and 152 optional fields not covered by the documents".

### 1.5 Client questionnaire as offered

- **Counts:** 21 client, 5 agency, 9 critical (3 agency), 10 optional, 2 duplicates merged, 11 selected.
- **Applicant (12):**
  - Critical: contact name, FEIN, contact phone, contact e-mail, annual revenue, employee count.
  - Suggested: annual gross payroll.
  - Optional: date business started, additional remarks, DBA, and two confirm items (legal name, mailing address).
- **Operations:** subcontracted % by type of work.
- **Property:** confirm the 1 location.
- **Auto:** garaging / return to yard.
- **Loss history:** no-known-losses attestation and the claims table.
- **Other:** urgency, plus three narrative questions (account overview, management, risk controls).
- **Schedules:** 1 vehicle, 1 location, 0 claims.

### 1.6 ACORD 125 output, box by box

- The stored form has 441 boxes, and **73 carry a value**. All 73 came from the deterministic passes.
- **321 are owned blanks** (a rule decided they stay empty).
- **154 were sent to the AI gap fill, and every one of the 154 came back empty.**

**Page 1**

| Box | Printed | Why |
|---|---|---|
| Date | 09/28/2026 | run date |
| Producer / contact / e-mail | Astrea It Services / Vinay Sharma / vinaysharma@astreait.com | the login (the dec's agency is Commercial Risk Solutions, Inc.) |
| Producer phone, fax, address, code, subcode, customer ID | blank | owned blank - the dec's agency is not the login's agency, so its phone and code are withheld |
| Carrier, NAIC, program, policy number, underwriter | blank | owned blank - page one is the policy being applied for, and the dec is the CURRENT policy (`carrier_is_current_policy: true`, rule of 15 Sep) |
| Status | QUOTE | |
| Lines of business | Business Auto, CGL, Commercial Inland Marine, Umbrella | correct |
| Line premiums | all blank | owned blank (`premium_is_current_policy: true`) |
| Attachments | Vehicle Schedule | kept on purpose (client's "do not regress") |
| Proposed eff / exp date | **blank, flagged required** | rejected: "the current policy's term ended on 2026-07-15; ... no document states when the new policy starts" |
| Billing plan | Direct | dec "DIRECT BILL" |
| Payment plan | blank | |
| Method of payment | "Direct bill" | a copy of the billing plan |
| Audit | "A" | dec "Audit Period: Annual", printed as the ACORD code (the client's 22 Sep run printed "Annual") |
| Deposit / minimum / policy premium | blank | owned blank |
| First named insured | Orbin Contracting LLC, 4800 Dahlia St, # D13, Denver CO 80216-3121 | correct |
| Legal entity | LLC | correct |
| No. of members and managers | blank, flagged required | not on the dec |
| GL code / SIC / NAICS / FEIN | blank | GL code went to the AI and came back empty, although the dec prints 91580 and 91585; SIC, NAICS and FEIN are not on the dec |
| Business phone, website | blank | not on the dec (EMC's own www.emcins.com was extracted and correctly not used) |

**Page 2**

| Box | Printed | Why |
|---|---|---|
| Contact information (both blocks) | blank | owned blank; the dec names no insured contact |
| Premises LOC 1 / BLD 001 | 4800 Dahlia St, # D13, Denver CO 80216-3121 | correct |
| City limits, interest (owner / tenant) | **blank, flagged required** | owned by the location schedule; today's extraction left `is_tenant` and the city-limits flags empty |
| Employees, annual revenues, building area | blank, flagged required | not on the dec |
| Premises description of operations | the two GL class descriptions joined by ";", at a tiny font | |
| Nature of business | Contractor | |
| Date business started | blank, flagged required | not on the dec |
| Description of primary operations | same two GL class descriptions | |

**Page 3**

| Box | Printed | Why |
|---|---|---|
| Additional interest | blank | |
| Questions 1-3 and 5-15 | blank | the dec does not answer them |
| Question 4 (other insurance with this company) | Y. Rows: Commercial General Liability BBC7263 - 26; Inland Marine 6C7-40-02---26; Commercial Auto 6E7-40-02---26; Umbrella 6J7-40-02---26 | owner decision of 24 Sep (Q4 restored) |

**Page 4**

| Box | Printed | Why |
|---|---|---|
| Remarks | blank | |
| Prior carrier, year 2025 | GL: EMC Property & Casualty Company, BBC7263 - 26, $3,954, 07/15/2025 to 07/15/2026. Auto: EMPLOYERS MUTUAL CASUALTY COMPANY (all caps, tiny font), 6E7-40-02---26, $2,991, same dates | Inland Marine and Umbrella have no column; OTHER is empty |
| Loss history, "Check if none" | blank, flagged required | nothing on the dec |

**Page 5:** producer's name Vinay Sharma. The applicant signature, date, licence number and NPN are blank.

---

## 2. The client's test document - `Orbin_Testing_09_22_2026.pdf`

- **Who, when, what:** Michelle, 22 Sep, on build `42a092a`. She tested 125, 126, 127, 131 and 186 on this same dec.
- **Contents:** 19 numbered items, 2 general comments and a questionnaire note.
- **Today column:** what our 28 Sep run (section 1) shows for the same thing.

**Type key:**
- **BUG** - we confirmed it is wrong today.
- **BUG?** - not re-checked today.
- **DECISION** - the client's ask conflicts with a rule we built on purpose, so the owner must choose.
- **UX** - screen or workflow change.

| # | Client says | Today (28 Sep run) | What we found | Type |
|---|---|---|---|---|
| 1 | Opening a package from the dashboard should land on the package profile, even after forms were started ("View Package Profile" / "Continue where you left off"); started forms in their own tab or under Key Details | not tested in this run | - | UX |
| 2 | Do not require forms to get the score; move towards "formless" (SQS on top of any system). Pre-score? Hide or change the "calculated after forms are generated" line? | Overview card still says the score is calculated after forms are generated | A stateless pre-form package score already exists (`sqs_service.current_package_sqs`, 27 Aug). The card shows only the tier by the owner's H2 call | DECISION + UX |
| 3 | Remove the "Important" section; the repeated items confuse | still there, same broken text | **Root cause of the broken text:** "(+N related)" is added AFTER the Fix text (`ReviewRailLayout.jsx:837`, `AcordModal.jsx:7570`). `IssueLine` (`AcordModal.jsx:845-857`) then strips the last ")" as if it closed "(Fix:", so it strips the one from "(+1 related)" | BUG + UX |
| 4 | Proposed effective date = the last date of the current term (the renewal date on the dec) | **blank + warning** | Our 15 Sep rule `_route_renewal_dates`: an ENDED term (07/15/2026 is past) is not the term being applied for, so the dates are asked. The client says: take the dec's expiration as the proposed effective date. In her own run she typed 07/15/2026 to 07/15/2027 | DECISION (client instruction) |
| 5 | "Contacts are in the dec" | warning "Contact information" still fires | **The dec prints no insured contact** (see 1.1). What it has is the AGENT's phone. 125's CONTACT INFORMATION is the applicant's inspection / accounting contact, and the client's own spec (3.3) says contact information is not waived on a dec-only package. We need to ask which contact she means | DECISION / clarify |
| 6 | Error when clicking "Open to fix" on "Driver schedule not provided" | **still reproduces** once forms are chosen without ACORD 127 | Fixed 24 Sep for the pre-form screen (nothing chosen yet). But `get_session_schedules(8992d874, only_key="auto_drivers")` returns `[]` on this run: the only chosen form is 125, and the endpoint serves only schedules of chosen forms, while the warning (gated on the auto LINE) still offers the table. Same BUG-05 class: a control the server will not serve | BUG |
| 7 | 125 carrier information not auto-filled ("it was at one point"); producer phone and e-mail are in the dec | carrier / NAIC / policy number / program / underwriter blank; producer phone blank | **Carrier:** blank by our 15 Sep page-one rule from Brent's key (page one = the policy being applied for). The package has 2 carriers and 4 policy numbers, and page one has one box each. **Producer:** the dec's agency is Commercial Risk Solutions, Inc. (phone 303-996-7800, no e-mail printed). The login's agency (ThinkSmith / Astrea) has a different name, and our 24 Sep rule withholds another agency's identifiers. When the dec's agency IS the login's agency (the normal real case), the merge records no expiring producer and the dec's phone counts as the submitter's own (`_producer_identifiers`) | DECISION |
| 8 | Lines identified but premiums did not attach, and no prompt to supply them | line premiums blank; no card or question asks for them | Blank by our page-one rule (`premium_is_current_policy`). The dec prints GL $3,954, IM $300, Auto $2,991, Umbrella $3,418, total $10,663. Nothing prompts for the blank premiums | DECISION + BUG (no prompt) |
| 9 | We know what is missing / required / to verify: show it in the side panel, or earlier, before form selection | the "14 Required / 1 Verify" list exists only inside the form viewer | - | UX |
| 10 | Make the Edit button far more obvious; allow double-click editing on the form | not tested | - | UX |
| 11 | Policy period is on the dec; premium missing with no prompt | same as 4 and 8 | - | see 4, 8 |
| 12 | The dec notes a tenant policy, not owner; as tenant, revenue should be "$0" by default | **TENANT and INSIDE CITY LIMITS both blank today** (her 22 Sep screenshot had both ticked; we cannot tell whether the AI or she ticked them). Annual revenues blank, flagged required | The dec never prints tenant / owner / city limits for the location. The only evidence is indirect: no property coverage, a suite number "# D13", and "Premises Owned, Rented or Occupied". Today's v25 extraction left them empty, so the schedule-owned boxes print blank. "$0 revenue for a tenant" is a client rule we have not built, and it conflicts with ACORD's own instruction for that box: "The annual revenue amount for this location" (the business's revenue there, not rent) | DECISION + regression vs 22 Sep |
| 13 | GL code, SIC and NAICS are all on the dec; FEIN may be client / producer filled | all blank | **GL code: BUG** - the dec's GL schedule prints 91580 and 91585, but the box went to the AI and came back empty (no deterministic binding from `gl_class_code_schedule`). ACORD's instruction asks for an ISO CLM code. The extracted schedule carries no per-class premium, so "the governing class" cannot be picked from facts. **SIC / NAICS: not printed anywhere in the dec** - they need a source (the Figure 20 suggester can offer candidates for confirmation, never fill them). FEIN is asked in the questionnaire | BUG (GL code) + clarify (SIC / NAICS) |
| 14 | Can the 125 go to the client through the questionnaire? How does the applicant (not the producer) sign? | applicant signature and date blank | No applicant-signature path exists | Feature |
| 15 | Loss runs still show 60% (max 85%) after "No Known Losses" was confirmed; it should not count against the score | not attested in this run (Loss History 25%) | This is by design today: an attested "no known losses" scores the pillar at 60 (`sqs_service` loss path C: attested 60, requested 50), and only loss runs raise it. The client wants it not to count. That is a scoring rule change, and scores go up (D6) | DECISION (score rule) |
| 16 | A resolved hard stop should tuck under "Reviewed" / "Recommendations", not stay in the red panel | no hard stops this run | - | UX |
| 17 | Green "Client" fields were filled by the PRODUCER, not the client - change the wording or verify | not tested | The viewer paints any field in `client_filled_fields` green as "Client" (`PDFJsViewer.jsx:277`, list served by `form_routes.py:1747-1781`). Next: find which producer path writes into that list | BUG |
| 18 | Yes / No questions on 126 and 127 cannot be edited (they can on 186) | 125 only this run | - | BUG? |
| 19 | The download "SQS Review" comes too late. Each item should say what needs attention, what to do, and the score effect, and whether the value is missing, withheld by the AI, or inferred and needing verification. The score should update as items are resolved. The Field QA summary does not say which form or question | same pattern today (section 1.4) | Today's review shows internal field names ("AdditionalInterest FullName"). "19 fields" counts boxes while the list counts 10 distinct names ("3 + 7 more"), from `field_qa.py:758-783`. **The same box, "AdditionalInterest FullName", appears both as "a value was found but removed" and "no value found".** "High-impact questions" includes explanation boxes and an Additional Interest checkbox, which are not questions | UX + BUG (messaging) |
| G1 | Client e-mail should say "Commercial Insurance **Submission** Platform" | - | - | copy |
| G2 | If there is a landlord, the client must give the landlord's full name and address for certificates | - | - | Feature |
| Q | The questionnaire summary said "21 of 25 answered", but 3 of the 25 were verification (confirm) questions | - | Confirm items are counted as questions | BUG (count) |

What she typed in the questionnaire (useful for re-testing):
- Answers:
  - lender / additional interest: none
  - outside contractors: 80%
  - contact: Erin Royal
  - DBA: no
  - revenue: $300,000
  - payroll: $0
  - additional named insureds: none
  - radius: 50 miles
  - vehicle use: "Other: used for both personal and to go to job sites"
  - hired or rented vehicles: no
  - employees' own vehicles: no
  - residential work: 0%
  - high-hazard operations: none
  - licence: a Colorado licence number
  - urgency: none
  - subcontracted work by type: 60% tenant improvement, 20% painting, 20% HVAC
  - garaging: "No - vehicles are garaged at drivers' homes or elsewhere"
  - drivers: 1 driver
- She also gave a phone, an e-mail and an FEIN. They are left out of this file on purpose.

---

## 3. Other problems this run shows (not in the client's list)

1. **AUDIT prints "A"; on 22 Sep it printed "Annual".** This changed with the FR125 round 2 tooltip-code work, and the
   client may read it as a regression. **But "A" is what ACORD asks for.** The box's own instruction reads "Enter code:
   ... A - annual, S - semi-annual, Q - Quarterly, M - Monthly, O - Other". Keep "A" and tell the client why.
2. **METHOD OF PAYMENT prints "Direct bill"**, the same words as the billing plan. The box's instruction is only "The method
   the policy will be paid", so this is defensible. It was the same on 22 Sep and the client did not flag it. Leave it.
3. **The premises operations description prints at a tiny font.** It is two GL class descriptions joined by ";". The 25 Sep
   one-line shortening works only on whole sentences. The dec also has its own "BUSINESS DESC: COMMERCIAL GENERAL
   CONTRA" (cut off).
4. **Prior carrier grid:**
   - Only GL and Auto appear.
   - Inland Marine and Umbrella have no column, and OTHER is empty.
   - The two carrier names print in different casing: EMPLOYERS MUTUAL CASUALTY COMPANY in capitals at a tiny font,
     against EMC Property & Casualty Company.
5. **Question 4 lists all four current policies** as "other insurance with this company" (owner decision, 24 Sep).
   - Page one's carrier box is blank, so "this company" is undefined on the form itself.
   - The line names are mixed: "Commercial General Liability" and "Commercial Auto" against "Inland Marine" and "Umbrella".
6. **The "New venture" recommendation is offered** on a package whose own documents show policies in force since 07/2025.
7. **The Exposure pillar shows "Revenue/Sales 100%" and "Payroll/Employee 100%"** while annual revenue and number of
   employees are listed as missing key details. The pillar measures agreement, not presence, but it reads as a
   contradiction.
8. **None of the 154 boxes sent to the AI came back with a value.** That is fine where the dec is silent. It is wrong for GL
   CODE (item 13).
9. The "Driver schedule not provided" warning is raised by the auto LINE, whatever forms are chosen (it drives item 6).

---

## 4. What the client wants

_To be added when the owner sends it._

---

## 5. Fix plan (proposed 29 Sep - the decisions wait for the owner's yes)

**Step 1 - clear bugs, no decision needed**

| # | Fix |
|---|---|
| 3 | Remove the "Important" block and its filter chip. Also make sure "(+N related)" can never again land after a Fix line (`ReviewRailLayout.jsx:837`, `AcordModal.jsx:7570`) |
| 6 | Serve a schedule when a chosen form uses it OR its line is carried - the same evidence the warning uses - so the warning and the table can never disagree |
| 13 | GL CODE stamped from the dec's GL class schedule, with no AI. Two classes print both ("91580, 91585"). SIC and NAICS stay blank; the suggester offers candidates to the producer |
| 17 | A value the producer typed is labelled as the producer's, never "Client" |
| Q | The questionnaire summary counts confirmations separately from questions |
| G1 | E-mail subtitle: "Commercial Insurance Submission Platform" |
| extras | One casing for carrier names; one naming style for Q4 lines; the one-line premises description breaks at ";"; no "new venture" card when the documents show an existing policy; Exposure categories say "Not provided" instead of 100% when there is nothing to compare |

**Step 2 - decisions (recommendation in bold)**

| # | Question | Recommendation |
|---|---|---|
| 4, 11 | Proposed dates from the dec? | **Yes.** Effective = the dec's expiration date; expiration = one term later. Ask only when that next term is itself already over (a stale dec). Reverses the 15 Sep "ended term - ask" rule |
| 7, 8 | Page-one carrier and premiums from the dec? | **Yes, as one rule.** If the documents name the carrier the submission goes to, use it (the FR125 case, which must stay 312 of 312). If they do not, a dec upload is a renewal with the same carrier: carrier and line premiums from the dec. NAIC stays blank (not printed). Policy number stays blank (four different numbers, all already in Q4 and the prior-carrier grid). Anything left blank gets a card that asks for it. Reverses the 15 Sep page-one rule - confirm once with Brent, because his key and Michelle's test disagree |
| 7 | Print the dec agency's phone? | **No change.** It is another agency's phone (Commercial Risk Solutions, not ThinkSmith). On a producer's own client's dec it already prints. The producer phone should come from the agency profile |
| 12 | Tick tenant, and put $0 revenue? | **Tenant: a one-click confirm showing the evidence (suite # D13, no building insured) - not a silent guess. Revenue: not $0.** ACORD's instruction is the location's revenue, so with one location copy the business's annual revenue into it. Ask for the landlord's name and address when the interest is tenant (G2) |
| 5 | Which contact does the dec have? | **Ask Michelle.** Meanwhile offer Erin Royal as a one-click suggestion for the contact name (the dec names her only as the Drive Other Car person). Phone and e-mail stay asked |
| 15 | Should an attested "no known losses" count in the score? | **Do what the client asks:** treat it as Not Applicable, like a confirmed new venture. Scores go up - tell Brent (D6) |
| 2 | Show a score number before forms? | **Yes.** It is already calculated (`current_package_sqs`); drop "calculated after forms are generated" and label the number as "so far", because it can still move at generation. Reverses the 27 Aug tier-only card |

**Step 3 - check, then fix:** 18 (Yes/No boxes not editable on 126 and 127).

**Step 4 - screens and workflow** (after the client's list arrives, because it may reshape these):
- **19 with 9:** one "needs attention" list.
  - Where it shows: pre-form for package items, and in the form viewer's side panel for form items, with click-to-jump.
  - Each row in plain words: the question as the form prints it, what to do, and the points.
  - Each row gets one tag: Missing / AI held back / Please verify.
  - The counts must be right. No contradictions: today the same box shows as both "value found" and "no value found".
  - The score updates as items are fixed.
- **1:** opening a package from the dashboard lands on the package profile, with "Continue where you left off".
- **10:** a bigger Edit button, and double-click to edit a box.
- **16:** a resolved hard stop moves to "Reviewed".
- **14:** applicant signature through the questionnaire. This needs Brent's call on e-signature.

## 6. Fix log

_Empty. One entry per item as we fix it: root cause, the class it belongs to, the change, what it could break, tests, and
the replay of session `8992d874` before and after._

Standing rules for every fix here:
- Replay the stored session (`8992d874`) before and after, and list every box that changed.
- Run the full suite with `py -m pytest -q -p no:randomly`. The only allowed failure is `test_arq_acord125_missing_only`.
- Any prompt change bumps PROMPT_VERSION and gets an `improving-ll.md` entry.
- Never edit `forms_schemas/`.
- Nothing is committed until the owner says so.
