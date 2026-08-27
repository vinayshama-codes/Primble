# Questions for Brent - 24 Aug 2026

Brent - five judgment calls that belong to you, not to us. I've laid out each one as the
real-world situation, what the choices mean, and where we lean. After that, the things
we've assumed - only reply on those if you disagree.

---

## 1. A loss run under the company's trade name

The insured on the application is Orbin Contracting LLC. On that same application they
list their DBA as Orbin Roofing. The loss run from the prior carrier is issued to Orbin
Roofing, and the tax ID on it matches Orbin Contracting's.

The Loss History score depends on how sure we are that those loss runs are really this
insured's. Your spec says the strongest proof is name plus tax ID or policy number. Here
the tax ID matches but the legal name doesn't - it's the trade name instead. Read
literally, that's "no name match," which treats the runs as if they might belong to some
other business and drops Loss History to the floor.

**The choices:** treat a trade name the applicant themselves declared as a real name match
(full credit when the tax ID also matches); give partial credit; or keep treating it as no
match.

**We lean:** full credit. The insured told us that's their name, and the carrier's
document confirms it - two independent sources.

## 2. The tax ID matches, but the name on the loss run is one we've never seen

Same idea, harder case. The tax ID on the loss run matches the applicant, but the insured
name on it is neither the legal name nor any trade name in the package. In practice that's
usually a company that changed its name or merged - but occasionally it's genuinely a
different business.

The honest limitation: from the paperwork alone, Primble cannot tell "a trade name we
never saw" from "a different company." They look identical. So this needs one rule for
both.

**The choices:** full credit, partial, or none.

**We lean:** partial. A tax ID belongs to exactly one legal entity and survives a name
change, so the match is real evidence - but with nothing backing the name, it shouldn't
count as fully proven.

## 3. Filling in "prior carrier" from the expiring policy on a renewal

On a renewal, the broker usually uploads the policy that's about to expire. The carrier's
name is right there. If we read it off the page, that's one less question the client has
to answer.

The danger: sometimes what gets uploaded is a quote or proposal from the new carrier
they're moving to. If we grabbed the carrier off that, we'd print the incoming carrier as
the prior carrier - on a signed application.

**The rule we'd use:** only read the carrier off a policy whose term has already ended
(that's the expiring one). If the term is still ahead, it's a quote, and we ask the client
instead. And we'd do it per line - GL, Auto and Umbrella can each have a different prior
carrier.

**What we need from you:** is that safe for how your brokers actually work? For example,
would anyone ever upload a policy from two terms back, or a mid-term rewrite, that would
fool a date check? If so, we keep asking the client and skip the shortcut.

## 4. AI confidence weights

Your spec asks for a confidence-weighted fill rate but never sets the weights, so they
have always been ours: document-read or human-entered values 1.00; AI-placed values we
verified word-for-word on the page 0.85; AI guesses we could not find on the page 0.50.

One correction to know about: the verified-AI row was accidentally counting as zero - a
field we had proven against the document scored worse than a guess. Fixed; Structural
Completeness rises on submissions with AI-filled fields the next time they open. I've
kept 0.85 / 0.50 so that is the only movement.

**What we need from you:** if you want different numbers - or want Suggested values pushed
further below verified ones - say so, and tell me whether the change applies to existing
submissions or new ones only.

---

## 5. How long the E&O audit record must be kept

The audit record now traces every value back to its document and page, keeps every
override with who changed it and when, and preserves what was open at each download.
That evidence lives in our database, and databases have cleanup jobs.

Today the operational audit tables are cleaned up after one year, and the raw uploaded
document data for free and essentials accounts is cleared after 30 and 180 days. An E&O
claim can surface years after a submission - if a producer needs this record in year
three, a one-year cleanup makes it partly blank by then.

**What we've set for now:** six months, everywhere the record reads from. Nothing in the
audit record is deleted before six months on any tier.

**What we need from you:** if your producers' E&O practice needs longer - many shops keep
E&O files for years - give us the number and we change one setting. Until you do, six
months stands.

---

## Things I've assumed - only reply if you disagree

1. When the insured tells us no loss runs exist, that alone scores the same as providing
   nothing (25). If they also attest to no known losses, the attestation earns the credit
   (60). "There's no paperwork" isn't evidence about losses.
2. When a loss run's years are readable but the claim statuses and amounts aren't, we
   don't deduct anything extra for that. Adding it would mean reading claim-by-claim
   details from every carrier's layout - separate work if you want it.
3. A business that has operated for years and never carried insurance still gets the
   missing-prior-carrier deduction. Only genuine new ventures are exempt. No coverage on an
   operating business is exactly the gap an underwriter wants to see flagged.
4. **Commercial auto with nothing saying owned or hired/non-owned.** Your section 6.3 says
   the new vehicle / driver / garaging / radius / use deductions apply only to accounts with
   owned vehicles, and that a genuinely hired/non-owned-only account must not be penalised
   for having no vehicle list. When the package requests auto but nothing tells us either
   way - no vehicle list, no covered-auto symbols, no comp/collision - we treat it as
   owned and apply the deductions. Our reasoning: an HNOA-only account normally says so
   (symbols 8/9, or "hired and non-owned" as the line), so silence is usually an owned
   fleet nobody listed - which is exactly the submission you want caught. If you would
   rather we ask the producer first and deduct nothing until they answer, say so.
5. **"Owners or officers known to exist."** We only count people who are actually named -
   on the application's officer table, or by the producer. We do not assume every
   corporation or LLC has officers by law. The broader reading would fire the deduction on
   nearly every WC account and turn a real check into noise.
6. **"Clearly annual" payroll.** Dec pages and applications print "Estimated Annual
   Payroll", "Annual Remuneration", "per year" and the like, and a class-code schedule
   states annual remuneration by definition. We read those as clearly annual - by meaning,
   not one exact spelling. The 3-point deduction fires only for a payroll figure that has
   no period wording anywhere: a bare number in a narrative, a payroll report with no
   basis, and so on.

---

## Section 9 - Core Submission Information

7. **Physical address: should it count against a submission that does not need one?**
   Your section 9 says the physical address applies "when the exposure requires it" and
   tells us not to require it universally. The warning already works that way - it only
   fires on property, multi-location or auto accounts that have not given us an operating
   address. But the ACORD 125 completeness count still lists the physical address as a
   field the submission owes, on every account. So a single-location general liability
   risk, whose mailing address is its premises, is measured as missing something it does
   not need.

   We have not changed it, because taking it out of that count raises the score on those
   accounts and that is your call, not ours. Two options:
   (a) leave it - every submission owes the same list, which is simple to explain;
   (b) count it only when the exposure requires it - the same test the warning already
       uses - so an account that genuinely does not need a separate premises address is
       not marked down for it.

   Which do you want?

8. **Workers comp: we ask for the payroll breakdown twice.**
   Since section 8 shipped, the client fills in an employee-group table - group, duties,
   headcount, annual payroll, state - and the producer owns the class code beside it.
   That table IS the payroll breakdown. But we still separately ask the producer to
   "provide your WC payroll breakdown by class code", and we ask for the experience
   modifier twice as well (once as its own question, once inside a narrative question).

   We can drop the duplicates. The reason we have not is that the second question is
   currently what credits the submission for having explained its payroll and its mod -
   so removing it, on its own, would cost a WC account a few points of narrative quality
   for information it has actually supplied. Fixing that properly means crediting it from
   the table instead.

   Do you want us to do that - one question per thing, credited from the table? We think
   yes, but it changes scores on WC accounts and we would rather you knew first.

9. **A declarations page's OLD dates are landing in the NEW policy's date box.**
   When a broker uploads their current declarations page alongside a new application - the
   most ordinary submission there is - Primble takes the dates from the declarations page,
   because a declarations page is normally the more reliable document. For dates it is the
   wrong one: those are the dates of the policy that is ENDING, and the application is
   proposing the new term. So ACORD 125's "proposed effective date" box can come out
   showing last year's date.

   Primble does currently flag it - the two documents disagree, the difference is shown in
   Data Consistency with both dates and which file each came from, and the producer can
   pick the right one in a click. What we have not done is make the right one the default.

   We can fix that: when one document is a bound policy (declarations page, policy,
   certificate, binder) and another is proposing a term (application, quote), the proposed
   term wins the date boxes and the bound one is filed as the prior policy's term. We would
   rather flag it to you first, because it changes which date lands on generated forms for
   any submission that includes a current declarations page.

   Do you want that changed, or is the producer picking it in Data Consistency the right
   place for that decision to be made?
