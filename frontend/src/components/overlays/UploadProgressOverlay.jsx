import { useState, useEffect, useRef } from "react";
import ProcessStageOverlay from "./ProcessStageOverlay";

// Figure 1: polls the backend side-channel the extraction pipeline writes as it
// processes each file, and turns that into the SAME stage-list UI already used
// when forms are generated (ProcessStageOverlay) - just with real wording and a
// real active index instead of a timer. No extra UI beyond that component.

// Exact label set requested: Reading your documents, Parsed, Extracting text
// from each file, Normalized, Scored, Form-ready - and nothing else. "Reading
// your documents"/"Parsed" are package-level (not per file - they describe the
// first file's read/OCR pass, which is the natural lead-in before per-file
// extraction begins); "Extracting text from X" repeats once per file, since
// that is where the real per-file wait time is spent.
const PACKAGE_STAGES = ["Normalized", "Scored", "Form-ready"];
const PACKAGE_ORDER  = ["normalized", "scored", "form_ready"];

function buildStages(files) {
  return [
    "Reading your documents",
    "Parsed",
    ...files.map((f) => `Extracting text from ${f.name}`),
    ...PACKAGE_STAGES,
  ];
}

function computeActiveIndex(files, packagePhase) {
  if (!files.length) return 0;
  // "Reading your documents" - active until the first file's OCR finishes.
  if (files[0].phase === "uploaded") return 0;
  // The first file not yet fully extracted is the one currently in flight -
  // works for any number of files, in upload order.
  const activeFileIdx = files.findIndex((f) => f.phase !== "extracted");
  if (activeFileIdx === -1) {
    const pkgIdx = Math.max(0, PACKAGE_ORDER.indexOf(packagePhase || "normalized"));
    return 2 + files.length + pkgIdx;
  }
  // "Parsed" is a real, one-time beat: the very first file has cleared OCR
  // ("parsed") but fact-extraction on it hasn't started yet ("extracting").
  if (activeFileIdx === 0 && files[0].phase === "parsed") return 1;
  return 2 + activeFileIdx;
}

export default function UploadProgressOverlay({ token, apiBase, tagline, note, onDone, onMissing }) {
  const [state, setState] = useState(null);
  const doneFiredRef = useRef(false);
  const missRef = useRef(0);

  useEffect(() => {
    if (!token) return;
    let cancelled = false;
    let timer = null;
    const poll = async () => {
      try {
        const res = await fetch(`${apiBase}/api/upload-progress/${token}`, { credentials: "include" });
        if (res.ok) {
          const data = await res.json();
          if (!cancelled && data.found) {
            missRef.current = 0;
            setState(data);
            if (data.done && !doneFiredRef.current) {
              doneFiredRef.current = true;
              if (onDone) onDone(data);
            }
          } else if (!cancelled && !data.found) {
            // Token not (yet) present. A few consecutive misses on the resume path
            // means the record expired / the run never registered → give up so the
            // overlay never hangs. On the normal path onMissing is not supplied.
            missRef.current += 1;
            if (missRef.current >= 6 && !doneFiredRef.current) {
              doneFiredRef.current = true;
              if (onMissing) onMissing();
            }
          }
        }
      } catch { /* transient network blip - keep polling */ }
      if (!cancelled) timer = setTimeout(poll, 1200);
    };
    poll();
    return () => { cancelled = true; if (timer) clearTimeout(timer); };
  }, [token, apiBase, onDone, onMissing]);

  const files = state?.files || [];
  const stages = buildStages(files);
  const activeIndex = computeActiveIndex(files, state?.package_phase);

  return (
    <ProcessStageOverlay
      stages={stages}
      controlledIndex={activeIndex}
      windowSize={2}
      tagline={tagline}
      note={note}
    />
  );
}
