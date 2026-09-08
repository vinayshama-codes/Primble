/**
 * One reading of a questionnaire's state (BUG-03, 2026-09-08).
 *
 * The producer workspace showed "Send to Client (2)" on a session that had sent
 * ZERO questionnaires. The badge was fed by `/api/arq/notifications`, which
 * counts unread rows written when a client SUBMITS - a different object type,
 * pointing the opposite way to the button it sat on - and that query filters by
 * user only, with no session at all, so it carried in submissions from every
 * other package the producer had ever run.
 *
 * The number the producer actually wants is "requests currently out with the
 * client", and that comes from the per-session ARQ list the panel below the
 * button already renders. This module is that reading, written once: the status
 * panel and the badge cannot disagree about what "open" means.
 *
 * Status vocabulary (see `arq_sessions.status`): 'pending' on send, 'submitted'
 * once answers are accepted. There is no stored 'expired' - it is DERIVED from
 * `expires_at`, which is why it has to live in a shared function rather than
 * being re-derived at each call site.
 */

/**
 * Has the link run out? A submitted questionnaire is never expired - the client
 * beat the clock, and the answers are in.
 */
export function isExpiredArq(arq, now = new Date()) {
  if (!arq || arq.status === 'submitted') return false;
  const expires = new Date(arq.expires_at);
  if (Number.isNaN(expires.getTime())) return false;   // unparseable: not expired
  return now > expires;
}

/** What the status chip should say: the stored status, or the derived 'expired'. */
export function arqDisplayStatus(arq, now = new Date()) {
  if (!arq) return 'pending';
  return isExpiredArq(arq, now) ? 'expired' : arq.status;
}

/**
 * Is this request still out with the client - sent, not answered, not lapsed?
 *
 * This is the badge's whole definition. Everything it must react to falls out of
 * it rather than needing its own rule: answered flips the status and it drops
 * out, the link lapsing drops it out, and sending again adds a new row.
 */
export function isOpenArq(arq, now = new Date()) {
  return !!arq && arq.status === 'pending' && !isExpiredArq(arq, now);
}

/** How many requests are currently out with the client for THIS session. */
export function openArqCount(arqSessions, now = new Date()) {
  return (arqSessions || []).filter((a) => isOpenArq(a, now)).length;
}

/**
 * What the "Send to Client" badge means, in words.
 *
 * The tester's question on seeing it: "does that mean the number of
 * questionnaires SENT, or still active?" It means still active, and a bare
 * number cannot say so - so the answer ships with it.
 *
 * Written as a plain statement about the client, NOT as "N still open (not the
 * number sent)". That first draft was rejected on sight and rightly: it defines
 * the number by what it is not, so the reader has to hold a wrong idea in mind
 * before they can correct it. "Your client hasn't answered 2 questionnaires
 * yet" needs no such step, and rules out "sent" by simply not saying it.
 *
 * One function, read by both the badge and the button behind it, because a
 * badge and its own button disagreeing about what a number means is the exact
 * confusion this bug was.
 */
export function openArqTooltip(count, total = 0) {
  if (!count) {
    return total > 0
      ? 'Your client has answered everything you sent.'
      : 'Send a questionnaire to your client.';
  }
  return `Your client hasn't answered ${count} `
       + `questionnaire${count === 1 ? '' : 's'} yet.`;
}
