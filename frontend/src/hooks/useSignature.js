import { useState, useEffect } from "react";
import { getSignature } from "../api/authApi";

export function useSignature(token, user) {
  const [savedSignature, setSavedSignature] = useState(null);

  useEffect(() => {
    if (!token || !user) return;
    const cached = localStorage.getItem("acordly_signature");
    if (cached) setSavedSignature(cached);
    getSignature(token)
      .then((data) => {
        if (data?.signature_data) {
          setSavedSignature(data.signature_data);
          localStorage.setItem("acordly_signature", data.signature_data);
        } else {
          setSavedSignature(null);
          localStorage.removeItem("acordly_signature");
        }
      })
      .catch(() => {});
  }, [user?.id]); // eslint-disable-line

  const updateSignature = (sig) => {
    setSavedSignature(sig);
    if (sig) localStorage.setItem("acordly_signature", sig);
    else localStorage.removeItem("acordly_signature");
  };

  return { savedSignature, updateSignature };
}