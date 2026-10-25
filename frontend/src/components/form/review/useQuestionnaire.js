// The review's Questionnaire page data (owner, 23 Oct 2026):
// GET /api/questionnaire/{session_id}, held by AcordModal so the rail badge,
// the page and the narrative cards' deep link read one copy. Re-read whenever
// `refreshKey` changes (AcordModal: on entering the review, on opening the
// page). `model` is null until it loads; `error` is true when it could not.

import { useCallback, useEffect, useState } from "react";
import { API_BASE } from "../../../config/constants";
import { withQuestion } from "../../../utils/questionnaire";

export default function useQuestionnaire(sessionId, enabled, refreshKey = "") {
  const [state, setState] = useState({ sessionId: null, model: null, error: false });
  const [tick, setTick] = useState(0);

  useEffect(() => {
    if (!enabled || !sessionId) return undefined;
    const ctl = typeof AbortController !== "undefined" ? new AbortController() : null;
    let alive = true;
    (async () => {
      try {
        const res = await fetch(`${API_BASE}/api/questionnaire/${sessionId}`, {
          credentials: "include", signal: ctl?.signal,
        });
        const data = res.ok ? await res.json() : null;
        if (!alive) return;
        if (data && typeof data === "object" && Array.isArray(data.sections)) {
          setState({ sessionId, model: data, error: false });
        } else {
          // Keep a copy already on screen for this session; say only that it failed.
          setState((s) => (s.sessionId === sessionId && s.model ? s : { sessionId, model: null, error: true }));
        }
      } catch (e) {
        if (!alive || e?.name === "AbortError") return;
        setState((s) => (s.sessionId === sessionId && s.model ? s : { sessionId, model: null, error: true }));
      }
    })();
    return () => { alive = false; ctl?.abort(); };
  }, [enabled, sessionId, refreshKey, tick]);

  const reload = useCallback(() => setTick((t) => t + 1), []);

  // One saved answer: the question and the counts the reply carries.
  const applyQuestion = useCallback((question, counts) => {
    setState((s) => (s.model ? { ...s, model: withQuestion(s.model, question, counts) } : s));
  }, []);

  // The approved (or drafted) narrative the reply carries.
  const applyNarrative = useCallback((narrative) => {
    setState((s) => (s.model && narrative ? { ...s, model: { ...s.model, narrative } } : s));
  }, []);

  const own = state.sessionId === sessionId;
  return {
    model: own ? state.model : null,
    error: own ? state.error : false,
    reload, applyQuestion, applyNarrative,
  };
}
