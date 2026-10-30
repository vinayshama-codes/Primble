# ASG TRANSCRIBER - integration log (started 29 Oct 2026)

Every decision, finding and build step for ACORD Solutions Group's Transcriber (and, later, its
Population / AL3 services) lives here. Read it before touching anything that sends a document to
ASG or reads a Transcriber result. Keep it current: one dated entry per step.

## 1. Why (Brent, 29 Oct 2026)

- **By Fri 30 Oct:** Primble must extract data from ANY ACORD form inside an uploaded package
  (not only the 17 forms Primble generates). Brent wants that extraction / e-labelling offloaded
  to Transcriber to save build time.
- The main cases are NOT our own forms coming back: (a) a producer double-checking a package
  completed in another system; (b) a carrier underwriter scoring a received package for triage.
- **By Fri 6 Nov:** users can search / select, generate and download ANY ACORD form, filled
  70-90% from the 125 + core forms through ACORD's e-labels (the missing 10-30% can wait).
  Brent wants templates pulled through ASG, not downloaded from ACORD (owner to investigate -
  Transcriber's "Forms" / "Population" modules are the first place to look).
- Long term Brent wants Primble on AWS "for that link so we don't burn through our Transcriber
  API usage". **Decision (owner + Claude, 29 Oct): no AWS move before launch.** Call the API
  from Render, keep usage low by design (section 4). Revisit after launch with real usage numbers.
- Email integration through Transcriber: later, on the radar only.

## 2. What we have (29 Oct)

- **Platform access (UAT):** `https://uat-transcriber.acordsolutions.net/transcriber/` - the
  owner's login works. Modules seen: Dashboard, **Extraction** (ACORD Form / Custom Form / AL3 /
  ACORD P&C XML), **Population**, **Forms**, **WebForms**, "Download Postman Collection".
  Recent Extractions already hold test runs from 30 Sep (`ACORD_125_FILLED.pdf`, Harborline dec
  package) and 6 Oct (`ASG_Policy_Dec 2.pdf`) - every one "Success".
- **Support portal:** `https://support.acordsolutions.com/hc/en-us/categories/115000377492-ACORD-Transcriber`
  - API Specifications: Overview, Extraction, Population, Download, Webforms,
    Encryption & Authentication (+ 2 more under "See all 8"). Release notes up to v3.3.3.
- **Documents in `~/Downloads` (NOT read yet - owner's instruction):**
  `Transcriber_API_Usage_Guide - ACORD Extraction.pdf`, `... - AL3 API Document.pdf`,
  `... - NER extraction.pdf`, `Transcriber_Onboarding_AccountSetup_PRIMBLE_UAT.pdf`,
  `transcriber.extraction.postman_collection.json`.
- **Repo:** `asg_dec_test_data/` (ASG's sample dec package from the pilot; see memory
  `asg-partnership-pilot`: Transcriber ~95% on filled ACORDs, ASG's dec model ~25%).
- **Credentials:** the owner holds the client credentials. They go in `backend/.env` ONLY
  (`TRANSCRIBER_*` keys, section 5) - never in the repo, a test, a log line or this file.

## 3. What Primble already does without Transcriber (ACORD_INTAKE.md)

- Recognises filled ACORD pages (box names; else the printed footer), reads fillable and
  flattened copies of the 17 supported forms with no model call, maps boxes to facts through
  one reverse map, merges by the owner table (ACORD = applicant + submission; declarations =
  current policies; a person beats both; another insured's ACORD owns nothing).
- Primble's OWN downloads carry an encrypted record (answers, tables, picks, which boxes were
  AI) - re-upload restores everything and the score equals the pre-download score (live 28 Oct:
  Orbin and CH125, forms + decs and cover + decs = 100). **Transcriber must never be used for
  these** - it cannot see the record, and reading them as outside documents is exactly what
  produced Brent's 97 -> 60.
- Gap Transcriber fills: scans / photos, forms outside the 17, editions we have no template
  for, handwriting. Today those fall to the general document reading, "Needs Verification".

## 4. Design (agreed 29 Oct, to build once the API shape is known)

1. **Routing.** Per page: Primble's own form (record present) -> in-house reader. A fillable or
   flattened copy of one of the 17 -> in-house reader. Any other ACORD page -> Transcriber.
   Decs, loss runs, narratives, spreadsheets -> never Transcriber (today's extraction).
2. **Usage discipline.** Send only the ACORD pages, never the whole package; cache every
   result against the file hash so a re-process / re-score / re-upload of the same file never
   calls again; a per-package page cap; `TRANSCRIBER=0` switches it off; any failure falls back
   to today's reading (never a blocked upload).
3. **Mapping.** Transcriber returns ACORD e-labels (ACORD's standard field names). Our reverse
   map (`acord_intake/reverse_map.box_targets`) already keys on ACORD field names, so a
   result should flow through the same door as our own reader. Anything it returns that is
   not an e-label gets a translation table - measured on the sample response first.
4. **Trust.** A Transcriber value = "found, please verify" (the AI weight, 0.85) until measured;
   never exact. It goes through the same merge rules and Data Consistency as any document.
   A person's answer and our record's restored answers stay exact.
5. **Security.** Client PII leaves our server: log the request id and page count only, never
   values; confirm ASG's retention before the first production call; keys from `.env`.
6. **Tests.** A stub client answering from a saved sample response, so the whole path runs in
   the suite with no network; one gated live test against UAT (skipped without credentials).

## 5. Environment (planned names - fix once the auth model is read)

```
TRANSCRIBER=1                          # 0 = off (in-house readers only)
TRANSCRIBER_BASE_URL=https://uat-transcriber.acordsolutions.net/...   # UAT first, prod later
TRANSCRIBER_CLIENT_ID=...              # or TRANSCRIBER_API_KEY - whatever the auth spec says
TRANSCRIBER_CLIENT_SECRET=...
TRANSCRIBER_MAX_PAGES_PER_PACKAGE=40
TRANSCRIBER_TIMEOUT_SECONDS=120
```

## 6. Open questions

- Auth: API key, or OAuth2 client-credentials token? Token lifetime? ("Encryption &
  Authentication" article - does the payload itself need encrypting?)
- Request flow: synchronous, or submit -> poll status -> fetch result? (the UI shows Request ID
  + ASG Trace ID + Status, which suggests asynchronous)
- Result format: JSON keyed by e-label, ACORD P&C XML, or both? Per-box confidence? Page refs?
- Multi-form PDFs: does one request take a whole package and split it (the 125 run shows
  "125,125,125,..." so a file with several forms is accepted)?
- Usage: quota / cost per page on UAT and production; rate limits.
- Retention: how long ASG keeps uploaded files and results.
- Forms / Population modules: can we pull fillable templates for any ACORD form (Brent's 6 Nov
  ask), and can Population fill a form from our data?
- Production vs UAT: when do we get production credentials, and is the API identical?

## 7. What the documentation says (read 29 Oct; the files are in `ASG_DOCUMENTATION/`, marked
ASG CONFIDENTIAL - do not commit them to GitHub; keep the folder git-ignored)

### 7.1 Authentication - what we need in hand
- Two choices: **OAuth 2.0 client-credentials (recommended)** or AWS Signature v4. We use OAuth.
- Token: `POST https://nonprod-token-transcriber.acordsolutions.net/oauth2/token` (UAT; the older
  article names the Cognito host `asg-transcriber-nonprod.auth.us-east-1.amazoncognito.com/oauth2/token`
  - try the new one first). PROD: `https://prod-token-transcriber.acordsolutions.net/oauth2/token`.
  Grant `client_credentials` with **client ID + client secret**. A Cognito `scope` may be required
  (not documented - test). Token lifetime not stated (Cognito default 1 h) - cache it until expiry.
- Every API call carries TWO things: `Authorization: <access token>` (the docs write the bare
  token; try bare, then `Bearer`) AND `x-api-key: <API key>` ("provided as part of onboarding").
  **So the credential set is THREE secrets: client id, client secret, x-api-key.** If the onboarding
  PDF gives only two, the third must come from ASG support before any call works (403 "Forbidden"
  is the missing-API-key signature - Error Handling article).
- UAT and PROD are separate hosts AND separate credential sets. Go-live needs the PROD set.
- `.env` names (final): `TRANSCRIBER=1`, `TRANSCRIBER_ENV=uat|prod`, `TRANSCRIBER_CLIENT_ID`,
  `TRANSCRIBER_CLIENT_SECRET`, `TRANSCRIBER_API_KEY`, optional `TRANSCRIBER_TOKEN_URL` /
  `TRANSCRIBER_SCOPE` overrides. Never in the repo, a test, a log line or this file.

### 7.2 ACORD form extraction (the Friday service) - the exact contract
- `POST https://{uat|prod}-api-v1-transcriber.acordsolutions.net/oauth/forms/extract?inpFormat=PDF&outFormat=ELABEL&latestEdition=true&sort=true&confidenceScore=true&returnCoordinates=true`
  Body = **base64 of the PDF**, `Content-Type: text/plain`. Optional `x-extraction-traceid` (our own
  UUID - send one per request so ASG support can trace a problem). Also accepts IMAGE / TIFF / PNG /
  DOCX / XLS inputs. Form number is auto-recognised ("formName not required for ACORD forms").
- Reply **202** `{"status":"accepted","requestId":..., "callbackUrl":".../oauth/forms/extract/<id>"}`.
  It is ASYNCHRONOUS: `GET` the callbackUrl (same two headers; `Accept: application/json` optional)
  until the body stops saying `status="PROCESSING"` ("Time since request submission: 12 seconds").
  A webhook is available instead of polling (needs a public endpoint registered with ASG) - later.
- Result: `{"responseBody": "<ACORD><ACORD accuracyPercent=\"100\" documentPageNum=\"1\"
  edition=\"2016/03\" formName=\"ACORD 25 2016/03\" formNumber=\"25\" formPageNum=\"1\" geoCode=..
  status=\"Success\" LOB=..><CertificateHolder_FullName_A pageNo=\"1\" physicalDocumentPageNo=\"1\"
  confidence_score=\"100\" tlx tly brx bry>value</...>...</ACORD></ACORD>", "ruleExceptionList": []}`
  - an XML string inside JSON; **one `<ACORD>` element per physical page**, children named by
  **eLabel = the ACORD field name** (`CertificateHolder_FullName_A` is exactly our schemas' box name,
  because our schemas were read off ACORD's fillable PDFs). Per-box confidence and coordinates
  (page + box rectangle) come with the flags above. An unrecognised page is
  `formNumber="UNKNOWN" status="Rejected"`; a page under ASG's accuracy bar is `status="Rejected"
  accuracyPercent="0"`; a critical-rule failure is HTTP 200 with `<ACORD>Failed due to Exception
  occurred for critical rule</ACORD>`; a model timeout is 500 "Extraction not completed
  successfully" (retry once). `latestEdition=true` maps an older edition's boxes onto the latest
  edition's eLabels, which is what our reverse map knows.
- Limits: body over ~5-6 MB (base64; a PDF over ~4 MB) -> **413**, use the large-file flow
  (multipart `POST https://{uat-|}transcriber.acordsolutions.net/Iforms-webforms-app/v2/iforms/extract/uploadfile`
  with the token -> encrypted `contentLocation` -> the same extract POST with `contentLocation=` and
  an empty body). A result over 5 MB comes gzip+base64 (`X-asg-body-compression-enabled: Y`) or as a
  download link (`X-asg-large-response-enabled: Y`). **429** = rate limit (number not published).
  Alternative to base64 bodies: header `x-asg-extraction-with-presigned-s3-url: true` + an S3
  presigned URL in the body - THIS is Brent's "AWS for that link": a bucket of ours, not a migration.
- Not in the docs, must be measured on a real response: whether `Accept: application/json` returns
  JSON eLabels (Population's own JSON shape `{"ACORD":{"ACORD":[{"edition":..,"formNumber":..,
  "<eLabel>":{"content":..}}]}}` suggests it does), how a ticked box comes back (the 25 sample shows
  an empty element for an unticked code box; Population examples send "Y" / "N C"), how a
  multi-page form is grouped (one element per page with the same formNumber and formPageNum 1..n),
  turnaround per page, what `ruleExceptionList` carries (ACORD business rules - possibly useful to
  the score later).

### 7.3 The other services (not Friday, but they decide the next two weeks)
- **Download (form templates)**: `GET https://{uat|prod}-api-transcriber.acordsolutions.net/v2/forms/download?formNumber=125&edition=YYYY/MM[&geoCode=CO]`
  with `x-api-key` and `Accept: application/pdf` -> the fillable (acroform) PDF of ANY ACORD form
  ("This form has no acroform PDF for download" for the few that have none). **This is Brent's
  "pull forms through ASG instead of ACORD" - it exists.** Caveat: the documented host is the
  AWS-signature host, not the `/oauth/` one; test with OAuth first, else ask ASG for an OAuth
  download route or AWS keys. A downloaded template is enough for OUR pipeline to support the form
  (schema read off the template, alias map generated, generic stamping, our editor / QA / record).
- **Population**: `POST .../oauth/forms/populate?inputFormat=ELABEL&outputFormat=PDF&forms=125[&geoCode=..&latestEdition=true&locked=false&multiForm=true]`
  with eLabel JSON/XML -> base64 of the filled PDF (any form, state variants, several forms in one
  PDF, async optional). An alternative route to "generate any form" that costs API usage per
  generation and bypasses our stamping guards / editor / Field QA / Primble record. Keep as the
  fallback for forms whose template we cannot get; not the main road.
- **AL3**: extraction takes `inputFormat=AL3 -> USPNCXML`; the allowed `outputFormat` list includes
  `AL3` / `AL3JSON` with `al3Version=v2016|v2022`, and "Custom Extraction" shows
  `inputFormat=ELABELXML&outFormat=USPNCXML&formNumber=25` - so **eLabel XML -> AL3 is most likely the
  same endpoint** (Brent's "ASG Converter"). Not spelled out; one test call settles it. Our
  generated forms' field values keyed by field name ARE an eLabel document, so a facts -> eLabel
  exporter is the one piece that unlocks both AL3 download and Population.
- **AI/ML generic models** (`insuranceModelName=asg-insurance-extract`, `asg-lossrun-generic`,
  `asg-sov-generic`; inputs include EML / MSG): non-ACORD documents. The pilot measured the dec
  model at ~25%; our own extraction stays. `asg-lossrun-generic` is worth one test later. The
  response structure is "provided by ASG support as a separate document" - we do not have it.
  EML/MSG input is the hook for Brent's e-mail integration.
- **WebForms**: ASG's Angular / JS component for a human to correct low-confidence extractions
  side by side with the PDF. We have our own review screens; not needed. **NER**: not needed.

### 7.4 Verdict and design, updated
- **Yes, we can integrate it, and nothing in the contract blocks Friday.** The client is small:
  token -> POST base64 -> poll GET -> parse XML -> boxes keyed by eLabel -> the SAME door our own
  reader uses (`reverse_map.box_targets(form_id, box)`, whose structural / registry / garaging /
  sibling layers are form-agnostic and need no schema; the learned map is per form and simply
  misses on a form outside the 17). Unmapped eLabels are kept with the document as e-labelled
  evidence (shown, not scored) - which is the honest framing for "any ACORD form" on Friday.
- Routing (decision for the owner / Brent): Primble's own forms (record) -> in-house, never sent;
  a FILLABLE ACORD of any number -> in-house too (box name = eLabel, exact, free); flattened,
  printed, scanned or photographed ACORD pages of any number -> Transcriber. A switch can send
  every outside ACORD page to Transcriber if Brent wants the partnership story over the usage.
  Decs, loss runs, narratives, spreadsheets -> never Transcriber (today's extraction).
- Send ONE small PDF per detected ACORD form group (pikepdf page subset; flattened pages lose
  nothing), never the whole package: smaller bodies (no large-file flow in the normal case), one
  result per form, and a cache key per form. Submit all groups right after upload, poll at the
  end of today's pipeline so the wait overlaps OCR + extraction; pool of 4; back off on 429; retry
  a 500 once; any failure -> today's reading, never a blocked upload.
- Cache: `sha256(sent bytes + params)` -> result (encrypted at rest, `init_db` pattern) so a
  re-upload of the same file in any package never calls again (Brent's re-upload scenario).
- Trust: a Transcriber value is labelled its own source (`acord_form`, confidence label
  `acord_transcriber`, weight 0.85 = found, please verify; `test_confidence_score_covers_every_label`
  must learn the label); per-box `confidence_score` kept on the envelope; page + rectangle feed
  `fact_lineage`. It goes through the owner table and Data Consistency like any document; a
  person's answer and the record's restored answers stay exact.
- XML parsing: the response is third-party XML; `defusedxml` is NOT installed - add it (or parse
  with `xml.etree` under a size cap and no entity expansion). Log request id, trace id, form
  number, page count and timing only - never a value.
- Security / retention: client PII goes to ASG (us-east-1). Brent signed the agreement; get the
  retention terms in writing before the first PROD call.

### 7.5 What is still needed, from whom
| Need | From | Blocks |
|---|---|---|
| Client ID + client secret + **x-api-key** (UAT) into `backend/.env` | owner (onboarding PDF) | the first live call |
| Confirmation the set includes the API key; PROD credentials + when | Brent / ASG support | go-live |
| Usage quota: per page or per request; is UAT metered; rate limit | Brent / ASG | routing choice |
| Retention of uploaded documents at ASG | Brent / ASG | PROD |
| The "Supported ACORD forms" list the docs link to | portal (owner) | expectations for "any form" |
| Download route: OAuth or AWS keys; list of forms with no acroform | test, then ASG | 6 Nov |
| eLabel XML -> AL3 confirmation (outputFormat=AL3) | one test call / ASG | AL3 download |
| AI/ML model response-structure document | ASG support | only if we try the loss-run model |
| A real multi-page response: run our CH125 `ACORD_125.pdf` (+126, 127) through the UAT UI, download the result JSON/XML into `asg_dec_test_data/transcriber_probe/` | owner, no code | mapping + tick convention + accuracy measure |
| Decision: send every outside ACORD page, or only non-fillable ones | owner / Brent | usage |

## 7.6 Hardening (owner, 29 Oct: "make it bullet proof") - what removes each risk
Guarantees we CAN give: never a wrong fact (every value labelled, one witness per document, unmapped
labels kept aside, never written), never a broken or blocked upload (fallback, breaker, time caps),
never a spend past caps we set. What we cannot guarantee: ASG's accuracy / uptime and the mapping
coverage on forms never seen - those are measured and logged, not promised.
1. One document, one reading (pinned by test): a fillable outside form's exact box read is the
   document's value; Transcriber's reading attaches to the SAME document record (confidence only,
   fills only empty boxes). Data Consistency reads documents, never readings. The in-house overlay
   reader of the 17 is a fallback for non-fillable pages, never a second witness.
2. Edition: the probe measures label coverage; `TRANSCRIBER_UNMAPPED` log + per-form coverage counter;
   `latestEdition` switchable per env. Unmapped = evidence shown on the document, never a fact.
3. Unknown forms: generic layers + coverage log; each of Brent's priority forms moves to full support
   (Download API template -> our pipeline) one by one; UI shows "read from the form, not yet scored".
4. Record-less Primble forms: print a small Primble mark (short session hash) in the margin of every
   generated form; when the mark is seen without a record, rebuild the record from the session row
   (server side) or at least downgrade the form's AI boxes. Not Friday; a half-day build.
5. Size: large-file flow + per-form splitting + base64 size pre-check, day one; stub simulates 413.
6. Spend: pool of 2-4, backoff on 429, per-package page cap, per-day page cap with a usage counter
   (`transcriber_usage`), circuit breaker after N failures, cache by hash, stored request ids so a
   crash mid-poll resumes instead of resubmitting.
7. Environment: production refuses to start with `TRANSCRIBER_ENV=uat` unless explicitly allowed;
   PROD credentials + retention terms from ASG before go-live.
8. Missed footers: optional second detector (ACORD wordmark + "Page n of m"); default off (quota).
Also: `TRANSCRIBER=0` kill switch; poll time cap per request; defusedxml; secrets never logged;
results encrypted at rest and under session retention; every real response saved so mapping work
is replayed OFFLINE with zero further calls; contract tests for every documented reply shape
(PROCESSING, Rejected, UNKNOWN, critical rule, gzip, large link, 413, 429, 500).

## 7.7 The ASG pilot agreement (read 29 Oct; "SaaS Pilot Agreement v250923", Primble LLC x ACORD
Solutions Group, signed by Michelle Smith; 3-month term from the Service Start Date)
- **Quota: 10,000 transactions, $0, hard stop** ("transactions beyond 10,000 will be prohibited and
  prevented"). **One transaction = one extractable PAGE** of a PDF / DOCX (a 4-page 125 = 4). Pages of a
  document type not enabled for Primble or not supported are "unextractable" and free - until the
  total pages processed in the year pass 2x the limit, after which each one counts. Pages where
  Transcriber returns no result are never counted. Excel: every worksheet is at least 1 transaction
  (1 per 2,000 rows); **tables found inside PDFs and converted to Excel count too** (the insurance-
  document path). Which document types are enabled for Primble is in the onboarding document.
- **Production use is PROHIBITED under this agreement** (2.2: evaluation only, "shall not use the
  Service for purposes of transacting business, or otherwise in a production environment"; 6.4: no
  Primble customer may be given access to or use of the Service). Brent's 29 Oct mail says Primble
  "secured additional licensing ... into a full production suite": that is a DIFFERENT agreement we
  have not seen. **Until its terms and PROD credentials are in hand, Transcriber stays OFF on
  primble.ai (`TRANSCRIBER=0`) and the in-house readers carry the launch.**
- **Retention / data use:** ASG deletes Client Data on its own schedule, no later than 30 days after the
  Term ends (11.3.1). Personal Information is Confidential Information, used only to provide the
  Service (8.4). **11.3.2: ASG may use Client Data for algorithm training** (other clients never see
  it). For real client documents this needs Brent's eye on the production agreement and possibly a
  line in Primble's own terms.
- **ACORD forms licence (Warning Notice):** Primble must hold a written licence directly with ACORD
  Corporation to use ACORD forms (Brent: signed), and is solely responsible for using the CURRENT
  editions - another reason to take templates from the Download API, never a cached old edition.
- Credentials: one API credential per environment, never shared; "ASG may limit access to the
  Service to white-listed IP addresses" - Render's outbound IPs are not fixed unless a static
  outbound IP is enabled; ask ASG whether UAT / PROD whitelist.
- Primble builds and maintains the API interface at its own cost and must implement API Updates when
  ASG requires them (6.2 iv). No benchmarking "for competitive purposes" (2.4 vii): our accuracy
  measurement is integration quality control, never published or used to build a rival reader.
- ASG does not warrant OCR / extraction accuracy (6.5) - which is exactly why a Transcriber value is
  "found, please verify" and never exact. Liability cap: fees due, else US$10,000 (9).
- The supported-forms list: https://support.acordsolutions.com/hc/en-us/articles/8040911707149-Supported-ACORD-forms
- Inputs the contract names: .MSG e-mails and .ZIP files are unpacked by the Service (Brent's e-mail
  integration), PDF text or image, DOCX, XLSX; AWS AI services sit behind it ("AI Tools").
- Design consequences: per-page accounting makes "only ACORD pages, never the whole package" a
  cost rule, not a nicety; the cache by hash and a running page counter against the quota are
  mandatory; the probe costs 4 transactions; every fillable outside page sent to Transcriber costs
  1 transaction that the in-house reader would read for free (owner's call stands: every outside
  ACORD page goes; revisit against the production quota).

## 7.8 The UAT probe (29 Oct 2026, run by the owner: our flattened CH125 ACORD 125, 5 pages = 5 transactions)
Files: `asg_dec_test_data/transcriber_probe/` (the PDF, the 253-value answer key, the JSON and XML replies).
- **Shape:** JSON eLabels `{"ACORD":{"ACORD":[{...}]}}` - ONE element per FORM (not per page); every box
  object carries `pageNo`, `physicalDocumentPageNo`, `confidence_score`, `tlx/tly/brx/bry` and `content`
  (absent when the box is empty). Form attributes: accuracyPercent 99, edition 2025/03, status Success.
  The parser read it unchanged; the form's page list now comes from its boxes' pages (fix in `_group_pages`).
- **Ticks:** `1` = ticked, `0` = unticked, on every indicator box (129 zeros, 32 ones). Codes stay letters.
- **Names:** 513 of 522 returned names are in our 125 schema; the other 9 are the same boxes under the newest
  edition's row letters (`latestEdition=true`). So an outside 125 maps through the reverse map like our own.
- **Accuracy vs the answer key:** text boxes 184 / 219 exact or contained, 2 differ by OCR punctuation only,
  33 missed (the additional-interest block on page 3 - printed, not read - and the loss-history Y/N status
  codes); ticks 30 / 34 read, the 4 "missed" returned under the newer names, so 34 / 34. **False values: 0.**
  Confidence median 99, six boxes under 80. Through our mapping: 222 values -> 22 facts (+ 4 locations,
  3 claims, 11 prior policies, 5 lines) + 82 boxes carried.
- **Two things the probe changed in the code:** (1) the newest 125 prints ONE name-and-address box, so no
  `NamedInsured_FullName_A` comes back and the insured's name sits as the first line of
  `NamedInsured_MailingAddress_LineOne_A` - `transcriber_intake._split_names_from_address_blocks` gives
  the name its own box (first line, unless it reads like an address line) and the block keeps the address;
  (2) tick boxes are recognised by our schema's field type (`/Btn`), not by "Indicator" in the name
  (`Policy_LineOfBusiness_CyberAndPrivacy_A` came back `0`); a `0` on a tick box is unticked and dropped,
  a `0` in a count or amount box is a value and kept.
- Fixture `tests/fixtures/transcriber_stub/real_125_probe.json` (producer block scrubbed) pins it.

## 8. Log

- **29 Oct 2026** - Brent's deadlines received (section 1). Owner logged into UAT; API docs
  and onboarding PDFs found in `~/Downloads` (unread). This file created. Next: read the API
  Specifications (Overview, Encryption & Authentication, Extraction, Download), put the
  credentials in `.env`, download one sample JSON result from Recent Extractions
  (`ACORD_125_FILLED.pdf`) into `asg_dec_test_data/transcriber_sample_125.json`, then build
  section 4 with the stub client.
- **29 Oct 2026, later** - all 11 API documents + 2 Postman collections read (section 7). Verdict: integrable; three secrets needed (client id, secret, x-api-key); Download API = Brent's template feed; AL3 likely via outputFormat=AL3; no AWS migration (presigned S3 is an option). Next: credentials in `.env`, a UAT probe with our CH125 forms, then the build.
- **29 Oct 2026, owner's standing rule:** NO live call to any ASG endpoint without the owner's explicit yes for that call; the owner makes the calls himself where possible. Tests use the stub only. Credentials are now in `backend/.env` (OAuth: 26-char Cognito client id). No code started yet.
- **29 Oct 2026, contract read** (section 7.7): 10,000-page free pilot, hard stop; production use prohibited under the pilot - PROD needs the separate production agreement Brent mentioned; data may be used for ASG training; IP whitelisting possible.
- **29 Oct 2026, BUILD (first pass, offline, uncommitted):**
  - `services/asg_transcriber.py` - the client: config from env (section 5 names are final:
    `TRANSCRIBER`, `TRANSCRIBER_ENV`, `TRANSCRIBER_TOKEN_URL`, `TRANSCRIBER_CLIENT_ID`,
    `TRANSCRIBER_CLIENT_SECRET`, `TRANSCRIBER_API_KEY`, optional `TRANSCRIBER_SCOPE`,
    `TRANSCRIBER_BEARER`, `TRANSCRIBER_SEND_FILLABLE` (default 1 - owner), `TRANSCRIBER_MAX_PAGES_PER_PACKAGE`
    (40), `TRANSCRIBER_DAILY_PAGE_CAP` (500), `TRANSCRIBER_WAIT_SECONDS` (150), `TRANSCRIBER_POLL_SECONDS` (3),
    `TRANSCRIBER_STUB_DIR`, `TRANSCRIBER_ALLOW_UAT_IN_PROD`); OAuth token cached to expiry (Basic auth, then
    body credentials); submit (base64, trace id) / large-file upload over 5 MB / poll / parse of every
    documented reply shape (XML-in-JSON, JSON eLabels, PROCESSING, RETRYING, Rejected, UNKNOWN, critical
    rule, gzip, download link, every HTTP status); usage hook refuses past the daily cap BEFORE sending;
    stub mode answers from disk; production + UAT guard; no value or secret in any log line.
  - `repositories/transcriber_repository.py` + `config/database.init_db`: `transcriber_results`
    (hash -> encrypted result) and `transcriber_usage` (per UTC day, per env).
  - `services/acord_intake/transcriber_intake.py`: `plan` (never a Primble record - checked on the raw
    docinfo too, `primble_record.carries_record`; flattened / scanned always, fillable per switch, images
    by OCR footer, page cap -> not sent), one sub-PDF per document (AcroForm copied), `fetch` (cache first,
    never raises), `copies_from` (reply -> reader copies; ticked indicators -> "check"; rejected pages ->
    none; unknown numbers -> `ACORD_<n>[_<geo>]`), `record_entry` (doc["acord"]["transcriber"]).
  - `read.merge_transcriber_copies` (one document, one reading: fillable wins and takes scores; overlay
    folds into the Transcriber copy; renumbered in page order) and `read.relabel_transcriber_facts`
    (confidence `acord_transcriber` + `confidence_score`, source stays `acord_form`).
  - `intake.read_for_document(path, text, transcriber=)`: PDF or image; `record["transcriber"]`,
    classification `reader`; the pipeline (`extraction_pipeline.extract_document`) reads in-house first,
    then Transcriber, then re-reads with both.
  - Labels: `pdf_service.apply_transcriber_labels` (a box printing a Transcriber value is `ai_verified`,
    0.85, Please verify + Confirm; also on the add-document re-stamp), `needs_attention._transcriber_reason`
    ("Read from an uploaded ACORD form by ACORD Transcriber (96% confidence). Confirm it before sending.").
  - UI: Documents list tag "Read by ACORD Transcriber - 96%" (`form_routes._reader_fields`, AcordModal).
  - Suite: `tests/conftest.py` forces `TRANSCRIBER=0` + the stub dir; `tests/fixtures/transcriber_stub/`;
    `tests/test_asg_transcriber_29oct.py` (21). Still owed: the probe-driven tick / label check, the pipeline
    end-to-end test, the admin usage view, the related-suite run, docs in CLAUDE.md.
- **29 Oct 2026, hardening pass (self-review):** a submitted request is remembered in the cache as
  `pending` and RESUMED on the next attempt instead of resubmitted (`PENDING_MAX_AGE` 1 h) - a timeout or
  crash mid-poll never pays twice; the Authorization style (bare token vs Bearer) flips once after a 401 and
  stays flipped for the process; Transcriber-read keys are NOT lifted out of the merge's guards
  (`intake.read_keys` lists exact box reads only - an OCR'd label can be refused like any model reading);
  `GET /api/admin/transcriber-usage` (pages per day / env + the caps). Tests: 26 in
  `tests/test_asg_transcriber_29oct.py` (incl. the pipeline door end to end on the stub and "a file with our
  record, decryptable or not, is never sent").
- **29 Oct 2026, LIVE on localhost (owner's uploads, UAT):** run 1 - submitted and accepted, but the 202
  reply carried the request id in a shape the manual did not show; the client fell back to today's reading
  (score 36, the general reader on a flattened 125) and logged `TRANSCRIBER_FALLBACK`. Fixed:
  `asg_transcriber.request_id_from_submit_reply` finds the id under any `*Id` key, any
  `/forms/extract/<id>` URL at any depth, a bare id or a Location header, and logs the envelope's KEYS
  (`TRANSCRIBER_SUBMIT_SHAPE`) when it still cannot. Run 2 - the whole path: token, submit (5 pages,
  153 KB), poll, done in 26 s, `forms=['125x5']`, cached by hash, document typed application and tagged
  Transcriber, 18 scalar facts + 4 locations / 3 claims / 11 prior policies / 5 lines, the insured's name
  split out of the combined block, "please verify" labels on the dry-run forms (131: 5, 126: 3, 127: 3,
  140: 3). **API result == website result: 351 of 351 values identical, 522 of 522 confidence scores
  identical.** Usage counter: 10 pages, 2 requests (ASG accepted run 1's pages too). Session 614c3211.
  Webhook: not built - polling inside the synchronous upload is enough; revisit if generation moves to
  the background on Render.
- **29 Oct 2026, Download API verified (one permitted call):** `GET {uat-api-v1}/oauth/forms/download?formNumber=36&latestEdition=true`
  with the OAuth token + x-api-key answered 200 `application/pdf` first try: ACORD 36 (2007/01), 1 page, a
  fillable AcroForm with 63 fields (`asg_dec_test_data/transcriber_probe/ACORD_36_template_from_asg.pdf`).
  So Brent's "pull forms through ASG" is one call per form; the template is exactly what our pipeline
  needs to support a form (schema off the fields, alias map, generic fill). The review Documents page now
  shows the "Read by ACORD Transcriber - 99%" tag too (it printed only in the editor's list before).
- **29 Oct 2026, hostile review (30 min, stub only) - 5 fixed, tests 33:** (1) HIGH list facts and
  tick-derived facts from Transcriber copies (locations, claims, prior policies, lines, entity type) escaped
  the label and the `read_keys` guard - now `intake._transcriber_keys` + box-less envelopes relabelled;
  (2) a "done" reply with zero forms was cached for ever - now a fallback, never cached; (3) no backoff -
  poll errors back off 5/15/30 s, a submit 429 waits once; (4) pages were never refunded on a failed submit
  or a cap refusal - `_refund` (negative usage, no request counted); (5) unrecognised terminal replies
  escaped as ValueError / ParseError - now `failed` / retryable "unreadable reply".
  **Open (decide / build):** the Transcriber wait is inline and sequential per document (20 outside
  PDFs = up to 20 x 150 s in one upload) - submit all first, then gather; table cells from Transcriber
  print `filled` (1.00), not "please verify"; `doc.acord.transcriber.elabels` duplicates values in
  plaintext on the session row - drop or encrypt; a fillable overlap drops the Transcriber copy's boxes on
  pages the fillable copy does not cover, and an overlap of DIFFERENT form ids folds the wrong form's
  boxes - filter overlaps by form_id; a second copy of one form in a file needs ASG's `formPageNum` (two-
  copy probe); the `x-amzn-requestid` header fallback could poll a gateway id - drop it; a presigned S3
  download link must be fetched WITHOUT our Authorization header; flip the auth style only on a real 401
  from extract, and re-token on a 401 from fetch; the name split can take "Rural Route 2" / a two-line
  company name as a name (narrow to the insured's block, require letters); IMAGE mime by extension;
  `_subset_pdf` may ship a fillable subset without its AcroForm.
- **29 Oct 2026, second pass (owner: "do all these"):** the review's open list, closed -
  PRE-SUBMIT (`transcriber_intake.presubmit_package`, called at the start of the upload and of
  add-documents): every PDF whose ACORD pages its own text shows is submitted at once (pool of 4), its
  request id cached as `pending`; `extract_document` later collects through the existing resume path -
  ASG reads all forms side by side while our OCR runs (a scan still waits for its turn: its footer needs
  OCR). `client.submit_only` / `_paid_submit` (accounting + refund shared with `extract`). Auth style
  flips only on a real 401 from the extract call; a 401 on a poll re-tokens once. A download link is
  fetched WITHOUT our Authorization header (pre-signed). No request id from the `x-amzn-requestid`
  header. Image mime from the file's bytes. A subset of a fillable file has its values painted into the
  pages before the cut. The document record keeps no eLabel values (plaintext on the session row) -
  form, pages, count only. The name split is the INSURED's block only, never an address-like first line
  ("Rural Route 2", "Highway 70 East", "Building C", c/o, attn) and needs 3+ letters. An overlap where
  ASG and our reader name DIFFERENT forms is not folded (our read stands); a fillable overlap now keeps
  Transcriber's boxes on pages the fillable copy does not cover. Tests: 42.
- **29 Oct 2026, production review (offline, stub only; `tests/test_production_review_29oct.py`).**
  Verdict: safe to ship DARK (`TRANSCRIBER` defaults 0; production refuses `TRANSCRIBER_ENV=uat`;
  presubmit and the pipeline door are no-ops when not live), NOT ready to switch on for live users
  (the pilot forbids production use - 7.7). Fixed: the in-house reader the Transcriber door wraps ran
  inline on the event loop (8-22 s CPU per flattened 125 / 59-page package, twice with Transcriber on) -
  now `asyncio.to_thread` (`extraction_pipeline.extract_document`); `carries_record` said yes to any
  `/PrimbleRecord` key, so an outside PDF carrying a stray integer / dictionary was never sent - now only a string value (ours, sealed with any key).
  Open, before switching it on: (1) `TRANSCRIBER_MAX_PAGES_PER_PACKAGE` is checked per DOCUMENT in
  `plan`, never summed over the package - a 20-file upload of 30-page forms sends 600 pages (only the
  daily cap stops it); sum in `presubmit_package` + a per-session counter. (2) `add_usage` returns the
  request's own pages when the DB write fails, so the daily cap never trips with the DB down - fail
  closed (refuse) instead. (3) `transcriber_results` has no retention purge (values off the insured's
  forms, encrypted, kept for ever) - add it to `run_retention_cleanup` at the session TTL. (4) An
  httpx transport error (connect / read timeout) on submit is not a `TranscriberError`, so the pages
  counted are not refunded. (5) A pending mark whose request ASG has forgotten is re-polled (and
  fails) for an hour before a fresh submit. (6) The presubmit reads every PDF a second time (CPU,
  only when live). (7) A non-ACORD page printing "ACORD 125 (2016/03)" in its bottom band is
  recognised as a flattened 125 and would be sent (one wasted transaction per page; ASG rejects it).
- **29 Oct 2026 night, production review closed:** one page budget per PACKAGE (`_PACKAGE_BUDGET`, opened by
  the pre-submit, spent by every send); the usage counter fails CLOSED (no counter = nothing sent); a
  transport error on submit is refunded; `transcriber_results` purged with the session retention
  (`scheduler_service.run_retention_cleanup`); a record sealed with another server's key reads quietly
  (`decrypt_field_soft`). Still open: a record is bound to the insured's NAME, not the account (another
  agency uploading the same company's Primble form gets the first agency's answers) - owner decision;
  a scoped Data Consistency pick could retire a stop while a rival sits on an unpicked line (suspected,
  not reproduced); pre-submit reads each PDF twice; a non-ACORD page printing an ACORD footer is sent.
  Full suite 21,421 / 1 (the known one) / 43.
- **29 Oct 2026 night, last open items closed:** a page is sent only with a SECOND ACORD signal beside its
  footer - the ACORD copyright (page 1) or "Page n of m" (`transcriber_intake.looks_like_acord_page`; all
  63 pages of our 17 templates and ASG's ACORD 36 carry one; fillable pages are proven by box names); the
  pre-submit plans from page recognition only (`recognize`), the full box read happens once.

### Bug hunt, 29 Oct 2026 (late) - pre-submit fixes (`transcriber_intake.py`, `tests/test_bughunt_29oct.py`)
- **A PDF with a page that has no text layer is no longer pre-submitted.** The pre-submit recognises pages
  without OCR; `extract_document` recognises them WITH it. A printed ACORD page beside a scanned one was
  pre-submitted as page 1 alone and later planned as pages 1-2 - a different sub-PDF and hash: page 1 paid
  twice, the pending request never collected, and the package budget spent twice. Such a file now waits for its
  turn. Text-only PDFs: the pre-submit hash equals the read-time hash (pinned).
- **The same bytes twice in one upload are sent once** (the parallel pre-submits both missed the cache).
- **Every package opens a FRESH page budget** - the worker runs all jobs in one task, so the first package's
  budget was spent by every later one.
- `plan` runs off the event loop in both doors (pdfplumber + pikepdf cut).
- `looks_like_acord_page` tolerates OCR spacing / 1-as-l slips ("Page 2 of4", "ACORDCORPORATION") and the
  "registered marks of ACORD" line; a carrier page citing "ACORD 125 (2016/03)" is still refused.
- Open: a file the package already holds (add-documents duplicate) is pre-submitted before the duplicate
  check; a failed usage write followed by a successful refund subtracts real usage.
- **29 Oct 2026 night, after the bug hunt:** a failed usage write is never refunded (it counted nothing -
  `USAGE_UNAVAILABLE`); the add-documents route no longer pre-submits (its duplicate check needs OCR first,
  a pre-submit would pay for a file already in the package). Left as designed: another account's Primble
  form still has its AI boxes kept AI and its text withheld (protective), only its answers are refused.
  Not changed (not proven): a pick value printed on a disputed AND an undisputed line keeps the conflict.
- **29 Oct 2026, production fuzz (offline, stub shapes; ACORD_INTAKE.md "Production fuzz"):** a tick Transcriber read
  in a mixed document (beside a fillable copy) is labelled Transcriber, not exact; boxes a Transcriber copy carries print
  "Please verify" (`carried_transcriber`); a second Transcriber copy naming another insured is set aside like any copy
  (`read._one_insured`) and two Transcriber copies that disagree give no reading. Still open: Transcriber table cells
  print `filled`.

### Keep everything (29 Oct 2026, owner: "never throw anything away; use everything we can")
Problem: Transcriber reads every box of ANY ACORD form, but on a form outside our 17 (ACORD 807 D&O) only the
boxes the structural layers knew became facts; the rest were dropped (the plaintext eLabel copy had been removed
from `doc.acord.transcriber` for privacy). Built (offline, stub only, uncommitted):
1. **Kept, encrypted.** `transcriber_intake.record_entry` stores EVERY box of every form element Transcriber
   returned - name, value, confidence, page of the uploaded file, form number / geo / edition / status, rejected
   pages and empty / unticked boxes too - as `doc["acord"]["transcriber"]["elabels_enc"]`
   (`utils.crypto.encrypt_field`, `elabel_payload` / `seal_elabels`). No key = nothing kept (never plaintext,
   `TRANSCRIBER_ELABELS_NOT_KEPT`). `read_elabels(doc)` decrypts (soft: another server's key reads as none).
   Our 17 forms are kept the same way.
2. **Used more: ACORD's shared field dictionary** (`reverse_map.shared_entry` / `shared_targets` /
   `learned_targets`). For a form we hold no map for, the learned-map slot of `box_targets` asks every one of our
   17 forms printing the same eLabel (`box_targets` of that form - its full reviewed reading): one meaning
   everywhere = used; two meanings (`disagree`), a scope-sensitive meaning (a policy-line record, a certificate's
   coverage row or insurer roster, a 125 scope override, a tick-scoped amount, prior grid / symbol / package
   targets - `scope`), or a table cell only ONE form prints (`single_form_schedule` - that form's own schedule)
   = not guessed. The structural / registry / garaging / applicant-row / sibling layers stay. Our 17 forms never
   consult it (pinned). Values mapped this way are Transcriber readings like any other: `acord_transcriber`
   (please verify), the merge's guards, owner table, Data Consistency and the other-insured rule.
3. **The rest is shown, never scored.** `GET /api/session/{id}/documents/{doc_id}/form-values` (owner only,
   `session_documents_routes.document_form_values` -> `transcriber_intake.form_values`): `used` (box, readable
   label, value, page, confidence, what it feeds, `via` form_map / shared_dictionary / acord_naming) and `read`
   (read from the form, kept); unticked boxes counted. The Documents list (review rail + editor) shows "View values
   read from the form" when `reader_values` (`form_routes._reader_fields`) - `review/FormValuesLink.jsx`.
**Measured on the real probe read as an unknown form number** (`real_125_probe.json`, 225 boxes with a value):
before 8 facts (the structural layers: dates, lines, loss rows, locations, prior grid, remarks, phone), 99 boxes
unused; after 24 facts, 81 unused (the true 125 gives 25 / 81 - only its header's per-line policy record is
missing, scope-sensitive by design). Leave-one-out (the 125 itself not voting, so only the other 16 forms speak):
21 facts, 84 unused. Across all 4,571 eLabels of our 17 schemas: 241 agreed, 216 scope, 488 single-form schedule,
0 disagree, the rest printed by no form with a meaning. Closed the same day: a form outside our 17 writes NO
plaintext under `acord.carried` (`intake._regenerable_only` - carried is only for forms we regenerate; its boxes
live in `elabels_enc`); the dictionary is built once per process for every name (`reverse_map.
build_shared_dictionary`, ~3 s, warmed on a background thread at `main.startup`), so an upload never pays it
inline - verdicts identical to the per-name lookup (pinned). Tests: `tests/test_transcriber_keep_everything_29oct.py`.

### 30 Oct 2026 - live test kit run 5
`test_kit_29oct/run5/` (README): one upload of a new dec + a Primble-downloaded ACORD 126 (record route, never sent) +
the flattened ACORD 807 (Transcriber, ~3 pages) + two loss runs, to prove the three routes side by side
(`TRANSCRIBER_SUBMIT ... label=807` once; none for the Primble form). Outside forms feed only package-scoped facts
(the 807: the insured name); `form_values` marks "used" only what the merge kept.
