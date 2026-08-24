# V1 C1 live test - what to upload, where to look, what to tell me

Regenerate the PDFs any time with:

```
py backend/scripts/make_v1_c1_test_pdfs.py
```

## Upload all four together, in one submission

| File | What it is | What it carries that matters |
|------|-----------|------------------------------|
| `1_dec_page.pdf` | Package declarations | **4 policies**, 2 carrier entities, address with ZIP+4, umbrella **$3,000,000**, two lines marked NO COVERAGE |
| `2_certificate.pdf` | Certificate of insurance | Same address **spelled out**, name with a comma, **fewer** lines, different terminology, umbrella **$1,000,000** |
| `3_application.pdf` | Application supplement | Address as **"Denver, Colorado"** only, insured name **truncated**, a **Professional Liability** policy |
| `4_loss_run.pdf` | Loss run | FEIN with **no dashes**, policy number with **spaces**, carrier under an **alias** |

Then generate forms - at least **ACORD 125, 126, 127, 131** - and open the review screen.

---

## The 10 checks

Work down the list. For each, write **PASS**, **FAIL**, or **NOT SURE** and paste
whatever you see.

### 1. Address - the client's original complaint
Three spellings of one address across the three documents.

**Look at:** the left panel, **Data Consistency** section.

- [ ] There is **no** "Mailing address differs across documents" row
- [ ] There is **no** warning card about the address
- [ ] The score is **not** capped at 85 because of an address

> **FAIL looks like:** a row listing all three address spellings, or a warning
> mentioning the address.

### 2. Four policies, four policy numbers
The dec page carries GL, Auto, Umbrella and Inland Marine.

**Look at:** **Data Consistency**.

- [ ] Either **no** policy-number conflict row at all, **or** a grey read-only row
      saying something like *"4 policies, 4 values - not a conflict"* with each
      number labelled by its line

> **FAIL looks like:** a pink row asking you to pick one policy number.

### 3. Two carriers on one package
EMC Property & Casualty writes the GL; Employers Mutual writes the rest.

**Look at:** **Data Consistency**.

- [ ] **Both** carriers are shown, each labelled with its own line
- [ ] You are **not** asked to choose between them

### 4. Truncated insured name - must NOT block
`ORBIN CONTRACTING LLC` / `Orbin Contracting, LLC` / `Orbin Contract`.

**Look at:** the score, and any red blocking card.

- [ ] **No** hard stop about the applicant name
- [ ] The score is **not** capped at 60

> This one used to cap the whole submission at 60.

### 5. THE GATE - the umbrella conflict must SURVIVE
Dec page says **$3,000,000**. Certificate says **$1,000,000**. That is a real
disagreement about a legal limit.

**Look at:** **Data Consistency**.

- [ ] A conflict row **is** shown for the umbrella limit
- [ ] Both `$3,000,000` and `$1,000,000` appear, each with its source document
- [ ] There is a short reason such as *"the documents state different amounts"*

> **This is the most important check.** If this row is missing, the fix went too
> far and that is worse than the original bug. Tell me immediately.

### 6. The umbrella box now has a value (Brent's decision)
Following Brent's ruling *"we should patch the suggested value"*.

**Look at:** the **ACORD 131** form - Excess/Umbrella Each Occurrence.

- [ ] The box is **filled**, not blank, even though the conflict above is open
- [ ] The conflict row from check 5 is **still** on screen

### 7. Loss run belongs to the insured
Different FEIN punctuation, spaced policy number, carrier alias.

**Look at:** the left panel, **Loss History** card.

- [ ] It does **not** say "Loss runs do not match insured"
- [ ] There is **no** note saying the carrier does not match
- [ ] If it shows "Matched on", it should list name plus fein and/or policy number

> The Auto policy number is `6E7-40-02---26` on the dec and `6E7 40 02 26` on the
> loss run. Same policy, different printing.

### 8. One premises, not three
Three spellings of one address again - this time on the form.

**Look at:** **ACORD 125**, the premises/location rows.

- [ ] There is **one** location row, not two or three
- [ ] City shows `Denver`, state shows `CO`

### 9. Professional Liability is not General Liability
The application names a Professional Liability policy with a different carrier.

**Look at:** **Data Consistency**, and ACORD 126 (the GL form).

- [ ] Hartford is **not** offered as a competing GL carrier
- [ ] The Professional Liability policy number is **not** on the GL form

### 10. Coverage marked NO COVERAGE stays off
The dec page marks Commercial Property and Crime as NO COVERAGE.

**Look at:** **ACORD 125**, the lines-of-business checkboxes.

- [ ] Commercial Property is **not** ticked
- [ ] Crime is **not** ticked

---

## Optional - the client-answer flow (check 11)

This one needs a questionnaire round trip.

1. Send the client questionnaire.
2. If it asks for **Number of Employees**, answer **25** (the documents say 18).
3. Submit, then reopen the submission as the producer.

**Look at:** the left panel, above the score history.

- [ ] A section titled **"Needs your decision"** appears
- [ ] It shows `Documents: 18` and `Client answered: 25`
- [ ] Two buttons: **Use client's 25** and **Keep 18**
- [ ] Clicking one updates the form **without** regenerating it

> If the questionnaire never asks for employees, that is **correct** - we only
> ask when the box is empty. Skip this check and tell me it did not fire.

---

## What to send me back

1. The 10 (or 11) results.
2. A screenshot of the **whole left panel** after generation.
3. A screenshot of the **Data Consistency** section, expanded.
4. Anything you see that looks wrong even if it is not on the list.
5. If something fails - the exact wording on screen, copied not summarised.

If the backend is running with logs visible, `grep` for these and paste any hits:

```
UNKNOWN_KEYS          - the model invented field names
withhold active       - a value was held back from a form
scope                 - values retained under their own policy
held for producer     - a client answer was held
```
