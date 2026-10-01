import SignaturePad from '../signature/SignaturePad';

// The applicant's signature as one questionnaire question (Orbin item 14).
// Owner, 1 Oct night: just the signature - draw it or upload a picture of it,
// with the same pad the producer uses. Nothing is sent from here: the
// questionnaire's Submit sends the signature first (its own endpoint - an image
// cannot ride an answer), then the answers.
//
// onChange(draft | null): {signature_data} once something is drawn or
// uploaded, null when cleared.
export default function SignatureQuestion({ onChange }) {
  return (
    <div>
      <SignaturePad onChange={(img) => onChange?.(img ? { signature_data: img } : null)} maxBytes={2_000_000} />
      <p style={{ fontSize: 11.5, color: '#94a3b8', marginTop: 8 }}>
        Your signature goes on the applicant&apos;s signature line of your application when you submit.
      </p>
    </div>
  );
}
