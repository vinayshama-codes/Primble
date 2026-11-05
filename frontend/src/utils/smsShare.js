// smsShare.js - "Text the link" (3 Nov 2026, OPEN_ITEMS: SMS sharing). Opens the producer's own messaging app
// (iPhone, Android, Mac Messages) with the client's questionnaire link already typed. The text goes from the
// producer's own phone: no SMS provider, no cost, no US carrier (10DLC) registration. Sending texts FROM Primble
// (a provider such as Twilio) is a separate, later build - OPEN_ITEMS.md.

const digitsOf = (s) => String(s || "").replace(/\D+/g, "");

// The number Messages should open with: a US / Canada number as +1XXXXXXXXXX, a number typed with "+" as
// +digits, otherwise "" (the producer picks the recipient in Messages - never a guessed country code).
export function smsNumber(phone) {
  // An extension is never part of the number ("303-555-0142 ext 9", "x9", "#9"), nor a trunk "(0)" after the
  // country code ("+44 (0)20 ...") - hard review, 3 Nov 2026.
  const raw = String(phone || "").trim().split(/\s*(?:ext\.?|extension|x|#)\s*\d*\s*$/i)[0].replace(/\(0\)/g, "");
  const d = digitsOf(raw);
  if (raw.startsWith("+") && d.length >= 8 && d.length <= 15) return `+${d}`;
  if (d.length === 10 && !/^[01]/.test(d)) return `+1${d}`;
  if (d.length === 11 && d.startsWith("1") && !/^[01]/.test(d.slice(1))) return `+${d}`;
  return "";
}

// One short text (one SMS segment for a normal name): who it is for and the link.
export function smsMessage({ clientName, link }) {
  const first = String(clientName || "").trim().split(/\s+/)[0] || "";
  return `${first ? `Hi ${first}, please` : "Please"} answer your insurance questions here: ${link || ""}`;
}

// "sms:<number>?&body=<text>" opens Messages with the body typed on both iOS and Android.
export function smsHref(phone, body) {
  return `sms:${smsNumber(phone)}?&body=${encodeURIComponent(body || "")}`;
}
