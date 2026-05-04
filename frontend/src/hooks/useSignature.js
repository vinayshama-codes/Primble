import { useState, useEffect } from "react";
import { getSignature } from "../api/authApi";

// Signature is kept in sessionStorage only — it is fetched fresh from the API on
// each login, so persistence across sessions provides no UX benefit and increases
// the XSS blast radius by leaving sensitive bitmap data on disk.
export function useSignature(token, user) {
  const [savedSignature, setSavedSignature] = useState(null);

  useEffect(() => {
    if (!user) return;
    const cached = sessionStorage.getItem("acordly_signature");
    if (cached) setSavedSignature(cached);
    getSignature(token)
      .then((data) => {
        if (data?.signature_data) {
          setSavedSignature(data.signature_data);
          sessionStorage.setItem("acordly_signature", data.signature_data);
        } else {
          setSavedSignature(null);
          sessionStorage.removeItem("acordly_signature");
        }
      })
      .catch(() => {});
  }, [user?.id]); // eslint-disable-line

  const updateSignature = (sig) => {
    setSavedSignature(sig);
    if (sig) sessionStorage.setItem("acordly_signature", sig);
    else sessionStorage.removeItem("acordly_signature");
  };

  return { savedSignature, updateSignature };
}