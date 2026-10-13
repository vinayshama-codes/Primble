// The editor's needs-attention list for EVERY generated form, read by the
// package page's Recommendations section once forms exist (Choice Electric
// #22, 7 Oct 2026). Same route and rows as the editor's side panel
// (GET /api/needs-attention, services/needs_attention.py) - never a second
// engine. `undefined` while it has not loaded, `null` when it could not be.

import { useEffect, useState } from "react";
import { fetchNeedsAttention } from "../../../utils/needsAttention";

export default function useAttentionList(sessionId, enabled, refreshKey = "") {
  const [state, setState] = useState({ key: null, data: undefined });
  const key = enabled && sessionId ? `${sessionId}|${refreshKey}` : null;

  useEffect(() => {
    if (!key) return undefined;
    const ctl = typeof AbortController !== "undefined" ? new AbortController() : null;
    let alive = true;
    (async () => {
      let data = null;
      try {
        data = await fetchNeedsAttention(sessionId, null, ctl?.signal);
      } catch {
        data = null;
      }
      if (alive) setState({ key, data });
    })();
    return () => { alive = false; ctl?.abort(); };
  }, [key]);  // eslint-disable-line react-hooks/exhaustive-deps

  if (!key) return undefined;
  // Keep the last list on screen while a refresh for the same session loads.
  if (state.key === key) return state.data;
  return state.key && state.key.startsWith(`${sessionId}|`) ? state.data : undefined;
}
