import { useState, useEffect, useRef } from "react";
import { API_BASE } from "../../config/constants";
import SaveStageOverlay from "../overlays/SaveStageOverlay";
import usePdfFieldFocus from "./usePdfFieldFocus";
import UseSignaturePrompt from "../signature/UseSignaturePrompt";
import NoSignaturePrompt from "../signature/NoSignaturePrompt";
import { boxPixelRect, hitTestBox, isBlankBoxValue, isClientValueBox, normalizeYesNoEntry } from "../../utils/viewerBoxes";
import "./PDFJsViewer.css";

const PDFJS_CDN    = "https://cdnjs.cloudflare.com/ajax/libs/pdf.js/3.11.174/pdf.min.js";
const PDFJS_WORKER = "https://cdnjs.cloudflare.com/ajax/libs/pdf.js/3.11.174/pdf.worker.min.js";

// pdf.js loads PDFs inside a Web Worker that does NOT inherit the main-thread
// fetch interceptor. On iOS Safari (ITP), the cross-site session cookie is
// blocked, so the worker's PDF fetch returns 401 and the preview silently
// stays in "Loading PDF…". Reading the bearer token here and passing it via
// httpHeaders gives the worker an auth channel that survives ITP.
const _readSessionToken = () => {
  try { return localStorage.getItem("acordly_tk") || sessionStorage.getItem("acordly_tk") || null; }
  catch { return null; }
};
const _pdfAuthHeaders = () => {
  const t = _readSessionToken();
  return t ? { Authorization: `Bearer ${t}` } : {};
};

const YELLOW_REQUIRED = new Set(["NamedInsured_Signature_A", "NamedInsured_SignatureDate_A"]);
// Orbin 22 Sep item 18 (owner, 1 Oct night): a Yes / No question box is
// highlighted ONLY when it holds an answer, in that answer's own colour -
// green the client's, pink AI-filled and found, orange verify. A blank one is
// plain, even when required (every blank lighting up was the complaint). All of
// them stay editable.
const CONTAINER_PADDING = 24;

const getMobileRenderWidth = (avail) => {
  const w = window.innerWidth;
  if (w <= 360) return Math.max(avail * 1.6, 480);  // fold phones: wider for readability
  if (w < 768)  return Math.max(avail * 1.8, 680);  // phones (up to but NOT including 768): h-scroll
  return avail;                                       // tablets (768+) and desktop: fill available width
};

export default function PDFJsViewer({
  pdfUrl, formName, onFormNav, sessionId, formId, token,
  savedSignature, isSigned, onSignApplied, onOpenSignatureModal,
  clientFilledFields = [],
  focusField = null,   // { field, nonce } - jump to and flash one box (needs-attention list)
  onRefreshFields,
  onSqsUpdate,
  onPendingEditsChange,
  // Item 10 (1 Oct 2026): a ref the parent reads to save typed edits before it
  // replaces this viewer - { hasUnsaved(), save() }. See `saveEdits`.
  editsRef = null,
}) {
  const canvasRef              = useRef(null);
  const containerRef           = useRef(null);
  const renderTask             = useRef(null);
  const overlayRef             = useRef(null);
  const fieldValuesRef         = useRef({});
  const fieldConfLabelRef      = useRef({});
  const clearedSigFieldsRef    = useRef(new Set());
  const originalFieldValuesRef = useRef({});
  const pdfUrlRef              = useRef("");
  const fieldsRef              = useRef([]);
  const pageDimsRef            = useRef([]);
  const manuallyRenderedRef    = useRef({ doc: null, pageNum: -1 });
  const editModeRef            = useRef(false);
  const isSignedLocalRef       = useRef(isSigned);
  const renderScaleRef         = useRef(1);
  // Item 10: the save in flight (one at a time), and the latest exit-save.
  const saveInFlightRef        = useRef(null);
  const exitSaveRef            = useRef(null);
  // Item 10: the box a view-mode double-click asked for, focused once edit mode draws it.
  const pendingFocusRef        = useRef(null);
  // THE PICTURE AND ITS BOXES SHOW ONE PAGE (owner, 30 Sep 2026: the toolbar
  // read 2/5, the canvas showed page 1 and page 2's yellow boxes sat on it).
  // `renderSeqRef` is a ticket: only the newest render may paint the canvas.
  // `shownPageRef` is the page the canvas REALLY shows - the only page the
  // overlay is ever built for. `pageNumRef` is the page the reader is on now,
  // for renders that finish after a page turn (the save and sign redraws).
  const renderSeqRef           = useRef(0);
  const shownPageRef           = useRef({ doc: null, page: 0 });
  const pageNumRef             = useRef(1);

  const [pdfjsReady,    setPdfjsReady]    = useState(!!window.pdfjsLib);
  const [pdfDoc,        setPdfDoc]        = useState(null);
  const [pageNum,       setPageNum]       = useState(1);
  pageNumRef.current = pageNum;
  const [totalPages,    setTotalPages]    = useState(0);
  const [rendering,     setRendering]     = useState(false);
  const [loadError,     setLoadError]     = useState(false);
  const [editMode,      setEditMode]      = useState(false);
  const [fields,        setFields]        = useState([]);
  const [pageDims,      setPageDims]      = useState([]);
  const [fieldValues,   setFieldValues]   = useState({});
  const [saveStatus,    setSaveStatus]    = useState("idle");
  const [,              setPendingEdits]  = useState(false);
  const [fieldsLoaded,  setFieldsLoaded]  = useState(false);
  const [isSignedLocal, setIsSignedLocal] = useState(isSigned);
  const [showSignPrompt,setShowSignPrompt]= useState(null);
  const [applyingSign,  setApplyingSign]  = useState(false);
  const [applySigStage, setApplySigStage] = useState("idle");
  const [loadingStage,  setLoadingStage]  = useState("idle");
  const [pdfRefreshKey, setPdfRefreshKey] = useState(0);
  const [highlightCounts, setHighlightCounts] = useState({ verified: 0, review: 0, yellow: 0, green: 0 });
  const [showLegend, setShowLegend] = useState(false);
  // Hover to open on devices that support hover (desktop); tap/click always works
  // (mobile/tablet). Gating hover on matchMedia stops a mobile tap from firing a
  // phantom mouseenter that would fight the click.
  const canHover = typeof window !== "undefined" && !!window.matchMedia && window.matchMedia("(hover: hover)").matches;

  useEffect(() => { editModeRef.current = editMode; }, [editMode]);
  useEffect(() => { isSignedLocalRef.current = isSignedLocal; }, [isSignedLocal]);
  useEffect(() => { setIsSignedLocal(isSigned); }, [formId]); // eslint-disable-line

  // Load PDF.js
  useEffect(() => {
    if (window.pdfjsLib) { setPdfjsReady(true); return; }
    const s  = document.createElement("script");
    s.src    = PDFJS_CDN;
    s.onload = () => { window.pdfjsLib.GlobalWorkerOptions.workerSrc = PDFJS_WORKER; setPdfjsReady(true); };
    s.onerror = () => setLoadError(true);
    document.head.appendChild(s);
  }, []);

  // Reset on form change
  useEffect(() => {
    setPageNum(1); setEditMode(false); setFields([]); setFieldValues({});
    fieldValuesRef.current = {}; originalFieldValuesRef.current = {};
    setPendingEdits(false);
    if (onPendingEditsChange) onPendingEditsChange(formId, false);
    fieldConfLabelRef.current = {};
    fieldsRef.current = []; pageDimsRef.current = []; editModeRef.current = false;
    setPageDims([]); setFieldsLoaded(false); setSaveStatus("idle");
    setPdfDoc(null); setTotalPages(0); setLoadError(false);
    setShowSignPrompt(null); setApplyingSign(false);
    setApplySigStage("idle"); setLoadingStage("idle");
    clearedSigFieldsRef.current = new Set();
    manuallyRenderedRef.current = { doc: null, pageNum: -1 };
    renderScaleRef.current = 1;
    pendingFocusRef.current = null;
    // A render of the previous form must never paint this one.
    renderSeqRef.current += 1;
    shownPageRef.current = { doc: null, page: 0 };
    if (renderTask.current) { try { renderTask.current.cancel(); } catch (_) {} renderTask.current = null; }
    setHighlightCounts({ verified: 0, review: 0, yellow: 0, green: 0 });
  }, [formId]);

  // Load PDF
  useEffect(() => {
    if (!pdfjsReady || !pdfUrl) return;
    pdfUrlRef.current = pdfUrl;
    setLoadError(false); setLoadingStage("loading");
    const url  = `${pdfUrl}?_r=${Date.now()}`;
    const task = window.pdfjsLib.getDocument({ url, withCredentials: true, httpHeaders: _pdfAuthHeaders() });
    task.promise
      .then(doc => { setPdfDoc(doc); setTotalPages(doc.numPages); })
      .catch(err => {
        if (err?.name !== "UnexpectedResponseException" && err?.message !== "Worker was destroyed") {
          setLoadError(true); setLoadingStage("idle");
        }
      });
    return () => { try { task.destroy(); } catch (_) {} };
  }, [formId, pdfjsReady, pdfRefreshKey]); // eslint-disable-line

  // The page-fit scale every render uses.
  const _fitScale = (page) => {
    const avail = containerRef.current ? containerRef.current.clientWidth - CONTAINER_PADDING : 720;
    return Math.min(2.2, Math.max(0.2, getMobileRenderWidth(avail) / page.getViewport({ scale: 1 }).width));
  };

  const _blankCanvas = (vp) => {
    const off = document.createElement("canvas");
    off.width = vp.width; off.height = vp.height;
    const ctx = off.getContext("2d");
    ctx.fillStyle = "#fff"; ctx.fillRect(0, 0, off.width, off.height);
    return off;
  };

  // Swap a finished off-screen page onto the visible canvas in ONE step, record
  // which page it is, and draw that page's boxes at once - so there is no frame
  // where the canvas shows one page and the overlay another.
  const _showRenderedPage = (off, doc, page) => {
    const canvas = canvasRef.current;
    if (!canvas) return false;
    canvas.width = off.width; canvas.height = off.height;
    canvas.getContext("2d").drawImage(off, 0, 0);
    shownPageRef.current = { doc, page };
    // Fields not loaded yet: the overlay effect draws them once they are.
    if (fieldsRef.current.length > 0) rebuildOverlay();
    return true;
  };

  // Render page to canvas.
  //
  // Two renders used to paint one canvas at once: the cancel ran BEFORE
  // `getPage`, so a render still waiting for its page was never cancelled and
  // whichever finished last won - while the overlay followed the toolbar's page
  // number. Now each render takes a ticket, paints OFF screen, and only the
  // newest ticket may swap its page in.
  useEffect(() => {
    if (!pdfDoc || !canvasRef.current) return;
    const mr = manuallyRenderedRef.current;
    const shown = shownPageRef.current;
    if (mr.doc === pdfDoc && mr.pageNum === pageNum && shown.doc === pdfDoc && shown.page === pageNum) {
      setRendering(false); setLoadingStage("idle"); return;
    }
    const seq = ++renderSeqRef.current;
    const doRender = async () => {
      setRendering(true);
      setLoadingStage(s => (s === "loading" ? "rendering" : s));
      if (renderTask.current) { try { renderTask.current.cancel(); } catch (_) {} renderTask.current = null; }
      try {
        const page = await pdfDoc.getPage(pageNum);
        if (seq !== renderSeqRef.current) return;        // a newer render owns the canvas
        const vp  = page.getViewport({ scale: _fitScale(page) });
        const off = _blankCanvas(vp);
        const t   = page.render({ canvasContext: off.getContext("2d"), viewport: vp, renderInteractiveForms: false });
        renderTask.current = t;
        await t.promise;
        if (renderTask.current === t) renderTask.current = null;
        if (seq !== renderSeqRef.current) return;
        _showRenderedPage(off, pdfDoc, pageNum);
      } catch (e) {
        if (e?.name !== "RenderingCancelledException" && seq === renderSeqRef.current) setLoadError(true);
      } finally {
        // Only the newest render clears the busy state: an abandoned one must
        // not report "done" while the page the reader asked for still draws.
        if (seq === renderSeqRef.current) { setRendering(false); setLoadingStage("idle"); }
      }
    };
    doRender();
  }, [pdfDoc, pageNum]); // eslint-disable-line

  // Rebuild overlay when state changes - for the page the canvas shows.
  useEffect(() => {
    if (!canvasRef.current || !overlayRef.current || !fieldsLoaded) return;
    rebuildOverlay(fieldValuesRef.current);
  }, [pageNum, editMode, isSignedLocal, fields, fieldsLoaded, pageDims, clientFilledFields]); // eslint-disable-line

  // ── fetchFields (used by handleRefresh) ────────────────────────────────
  const fetchFields = () =>
    fetch(`${API_BASE}/api/fields/${sessionId}/${formId}`, { credentials: "include" })
      .then(r => r.ok ? r.json() : null)
      .then(data => {
        if (!data?.success) return;
        const vals = {}; const confLabels = {};
        (data.fields || []).forEach(f => {
          vals[f.name]       = f.value            || "";
          confLabels[f.name] = f.confidence_label || "";
        });
        fieldsRef.current          = data.fields    || [];
        pageDimsRef.current        = data.page_dims || [];
        fieldConfLabelRef.current  = confLabels;
        setFields(data.fields || []);
        setPageDims(data.page_dims || []);
        setFieldValues(vals);
        fieldValuesRef.current         = vals;
        originalFieldValuesRef.current = { ...vals };
        // Both refs were just replaced from the server, so nothing is unsaved
        // any more. Without this the "Unsaved" marker and AcordModal's dimmed
        // pillar bars stayed on forever after a Refresh - the panel telling the
        // producer their score was stale when it was current. Found by review.
        clearedSigFieldsRef.current = new Set();
        _syncPending();
        setFieldsLoaded(true);
        updateHighlightCounts(data.fields || [], confLabels, vals);
        // If the canvas is already painted (e.g. refresh), rebuild the overlay immediately.
        // If not, the useEffect([..., fields, fieldsLoaded, ...]) fires once canvas is ready.
        requestAnimationFrame(() => rebuildOverlay(vals));
      });

  usePdfFieldFocus({ focusField, fieldsLoaded, fieldsRef, overlayRef, pageNum, setPageNum });

  // ── Initial fields fetch on mount ──────────────────────────────────────
  useEffect(() => {
    if (!sessionId || !formId) return;
    const controller = new AbortController();
    fetch(`${API_BASE}/api/fields/${sessionId}/${formId}`, { credentials: "include", signal: controller.signal })
      .then(r => r.ok ? r.json() : null)
      .then(data => {
        if (!data?.success) return;
        const vals = {}; const confLabels = {};
        (data.fields || []).forEach(f => {
          vals[f.name]       = f.value            || "";
          confLabels[f.name] = f.confidence_label || "";
        });
        fieldsRef.current         = data.fields    || [];
        pageDimsRef.current       = data.page_dims || [];
        fieldConfLabelRef.current = confLabels;
        setFields(data.fields || []);
        setPageDims(data.page_dims || []);
        setFieldValues(vals);
        fieldValuesRef.current         = vals;
        originalFieldValuesRef.current = { ...vals };
        // Both refs were just replaced from the server, so nothing is unsaved
        // any more. Without this the "Unsaved" marker and AcordModal's dimmed
        // pillar bars stayed on forever after a Refresh - the panel telling the
        // producer their score was stale when it was current. Found by review.
        clearedSigFieldsRef.current = new Set();
        _syncPending();
        setFieldsLoaded(true);
        updateHighlightCounts(data.fields || [], confLabels, vals);
        requestAnimationFrame(() => rebuildOverlay(vals));
      })
      .catch(err => { if (err?.name !== "AbortError") console.error("Fields fetch error:", err); });
    return () => controller.abort();
  }, [sessionId, formId]); // eslint-disable-line

  const updateHighlightCounts = (fieldList, confLabels, vals) => {
    let verified = 0, review = 0, yellow = 0, green = 0;
    fieldList.forEach(f => {
      const name = f.name;
      if (f.applicant_signed) return;            // the client signed it (Orbin item 14)
      // A blank Yes / No question is plain on the form, so it is not counted (item 18).
      if (f.yn_question && isBlankBoxValue(vals[name] ?? f.value)) return;
      const val  = (vals[name] || f.value || "").toString().trim();
      const conf = confLabels[name];
      // Item 17: the same rule as the box's own colour (`_getHighlight`).
      if (isClientValueBox(conf, vals[name] ?? f.value ?? "", originalFieldValuesRef.current[name])) { green++; return; }
      if (YELLOW_REQUIRED.has(name) && (!val || val === "null" || val === "None")) { yellow++; return; }
      if ((conf === "missing_required" || conf === "extraction_error") && (!val || val === "null" || val === "None")) { yellow++; return; }
      if (conf === "ai_verified" && val && val !== "null" && val !== "None") { verified++; return; }
      if (conf === "low_confidence" && val && val !== "null" && val !== "None") review++;
    });
    setHighlightCounts({ verified, review, yellow, green });
  };

  const handleRefresh = async () => {
    if (!sessionId || !formId) return;
    // Item 10 (1 Oct 2026): Refresh re-reads every box from the server, so typed
    // edits are saved first; if that save fails they stay in the boxes.
    if (hasUnsavedEdits() && !(await saveEdits({ redraw: false }))) return;
    setLoadingStage("loading");
    try {
      if (onRefreshFields) await onRefreshFields();
      await fetchFields();
      manuallyRenderedRef.current = { doc: null, pageNum: -1 };
      setPdfRefreshKey(k => k + 1);
    } finally { setLoadingStage("idle"); }
  };

  const _isSigField = (name) => {
    const fn = (name || "").toLowerCase().replace(/[\s\-.]/g, "_");
    if (["date","designation","title","printed","print_name","name_of","countersign"].some(ex => fn.includes(ex))) return false;
    return ["signature","producer_sig","insured_sig","authorized_sig","applicant_sig","agent_sig",
            "signedby","signed_by","sign_here","producersig","agentsig","sig_producer","sig_insured","sig_agent"]
           .some(p => fn.includes(p));
  };

  // Orbin item 14: boxes on a form the CLIENT signed (`applicant_signed` from
  // /api/fields). `painted` ones carry the signature or its date in the PDF
  // itself, so nothing is drawn over them; none of them is "still to sign".
  const applicantSignedRef = useRef({ list: null, names: new Set() });
  const _applicantSigned = (fieldName) => {
    const c = applicantSignedRef.current;
    if (c.list !== fieldsRef.current) {
      c.list = fieldsRef.current;
      c.names = new Set((fieldsRef.current || []).filter(f => f.applicant_signed).map(f => f.name));
    }
    return c.names.has(fieldName);
  };

  const _getHighlight = (fieldName, val) => {
    const conf = fieldConfLabelRef.current[fieldName];
    // Item 17 (1 Oct 2026): green only while the client's value is in the box,
    // read off the box's CURRENT label - never off the client-filled list,
    // which still named a box the producer had retyped.
    if (isClientValueBox(conf, val, originalFieldValuesRef.current[fieldName])) return "green";
    if (_applicantSigned(fieldName)) return null;
    const v    = (val || "").toString().trim();
    if (YELLOW_REQUIRED.has(fieldName)) {
      if (!v || v === "null" || v === "None") return "yellow";
      return null;
    }
    if (conf === "ai_verified" && v && v !== "null" && v !== "None") return "verified";
    if (conf === "low_confidence" && v && v !== "null" && v !== "None") return "review";
    if ((conf === "missing_required" || conf === "extraction_error") && (!v || v === "null" || v === "None")) return "yellow";
    return null;
  };

  const _highlightBg = (hl, curEdit) => {
    if (hl === "green") return "rgb(187,247,208)";
    if (hl === "yellow") return "rgb(254,243,199)";
    if (hl === "verified") return "rgb(254,226,226)";  // pink — AI-filled, found in docs
    if (hl === "review") return "rgb(254,215,170)";    // orange — AI-filled, verify
    return curEdit ? "rgba(255,255,255,0.97)" : "transparent";
  };

  // A box's background: its confidence highlight, nothing else (a Yes / No
  // question is no longer tinted - owner, 1 Oct night).
  const _boxBg = (field, val, curEdit) => {
    if (field.yn_question && isBlankBoxValue(val)) return _highlightBg(null, curEdit);
    return _highlightBg(_getHighlight(field.name, val), curEdit);
  };

  // One answer changes whether its whole question is answered - repaint every
  // box of that question on this page (a Yes / No checkbox pair is two boxes).
  const _repaintYesNoGroup = (field, curEdit) => {
    const overlay = overlayRef.current;
    if (!overlay || !field.yn_question) return;
    const group = field.yn_group || field.name;
    Array.from(overlay.children).forEach(el => {
      const f = el._ynField;
      if (f && (f.yn_group || f.name) === group) {
        el.style.background = _boxBg(f, fieldValuesRef.current[f.name] ?? f.value ?? "", curEdit);
      }
    });
  };

  // The ONE way the overlay is (re)built: for the page the canvas shows, at the
  // canvas's own scale - never for the page the toolbar is heading to.
  const rebuildOverlay = (liveValues = fieldValuesRef.current) => {
    const canvas = canvasRef.current;
    const page = shownPageRef.current.page;
    if (!canvas || !canvas.width || !page) return;
    const pd = pageDimsRef.current[page - 1];
    const sc = pd ? canvas.width / pd.width : renderScaleRef.current;
    renderScaleRef.current = sc;
    buildOverlay(sc, canvas.width, canvas.height, liveValues, page);
  };

  const buildOverlay = (scale, canvasW, canvasH, liveValues, page = shownPageRef.current.page) => {
    const overlay = overlayRef.current;
    if (!overlay) return;
    // Which box had the cursor before this rebuild (restored at the end).
    const _activeEl = typeof document !== "undefined" ? document.activeElement : null;
    const _keepFocusName = (_activeEl && overlay.contains(_activeEl) && _activeEl.closest)
      ? (_activeEl.closest("[data-field-name]")?.dataset?.fieldName || null) : null;
    // ...and where its cursor was, so a rebuild mid-typing never moves it.
    let _keepSel = null;
    try {
      if (_keepFocusName && _activeEl.type === "text") _keepSel = [_activeEl.selectionStart, _activeEl.selectionEnd];
    } catch { /* not a text box */ }
    overlay.innerHTML    = "";
    overlay.style.width  = canvasW + "px";
    overlay.style.height = canvasH + "px";
    if (!page) return;
    const pd         = pageDimsRef.current[page - 1];
    const pageHeight = pd ? pd.height : canvasH / scale;
    const pageFields = fieldsRef.current.filter(f => f.page === page - 1 && !f.painted);
    const curEdit    = editModeRef.current;
    const focusTargets = {};

    pageFields.forEach(field => {
      // One geometry for the overlay and the double-click hit test (viewerBoxes).
      const { left: cx, top: cy, width: cw, height: ch } = boxPixelRect(field.rect, scale, pageHeight);
      const fs  = Math.max(7, Math.min(ch * 0.58, 12));
      const val = liveValues[field.name] ?? field.value ?? "";
      const hl  = _getHighlight(field.name, val);

      // Highlighted fields use fully-opaque pastel fills so the PDF canvas text
      // underneath is completely hidden - preventing the double-text ghost effect.
      // Non-highlighted edit fields use a near-opaque white for the same reason.
      let bg = _boxBg(field, val, curEdit);

      const wrap = document.createElement("div");
      wrap.dataset.fieldName = field.name;   // usePdfFieldFocus finds the box by name
      // Inset by 1px on all sides so the highlight sits strictly inside the field
      // boundary - prevents sub-pixel bleed at the edges regardless of scale.
      wrap.style.cssText = `position:absolute;left:${cx+1}px;top:${cy+1}px;width:${Math.max(cw-2,4)}px;height:${Math.max(ch-2,4)}px;pointer-events:${curEdit?"all":"none"};border:none;border-radius:1px;background:${bg};box-sizing:border-box;overflow:hidden;`;
      wrap.dataset.field = field.name;
      if (field.yn_question) wrap._ynField = field;

      const isSigF = _isSigField(field.name);

      if (field.type === "checkbox") {
        const isChecked = val === "Yes" || val === "true" || val === "1" || val === "On";
        if (curEdit) {
          const cb = document.createElement("input");
          cb.type    = "checkbox";
          cb.checked = isChecked;
          cb.style.cssText = `position:absolute;top:50%;left:50%;transform:translate(-50%,-50%);width:${Math.min(ch*0.7,13)}px;height:${Math.min(ch*0.7,13)}px;margin:0;cursor:pointer;accent-color:#000;`;
          cb.addEventListener("change", e => {
            const nextVal = e.target.checked ? "Yes" : "Off";
            triggerSave(field.name, nextVal);
            // A Yes / No checkbox pair answers ONE question: ticking one box
            // clears its partner, so a question never carries both answers.
            if (e.target.checked && field.yn_group && field.yn_group !== field.name) {
              fieldsRef.current.forEach(g => {
                if (g === field || g.type !== "checkbox" || g.yn_group !== field.yn_group) return;
                if (isBlankBoxValue(fieldValuesRef.current[g.name])) return;
                triggerSave(g.name, "Off");
                const el = Array.from(overlay.children).find(c => c._ynField === g);
                const other = el && el.querySelector('input[type="checkbox"]');
                if (other) other.checked = false;
              });
            }
            wrap.style.background = _boxBg(field, nextVal, curEdit);
            _repaintYesNoGroup(field, curEdit);
            updateHighlightCounts(fieldsRef.current, fieldConfLabelRef.current, fieldValuesRef.current);
          });
          wrap.appendChild(cb);
          focusTargets[field.name] = cb;
        } else if (isChecked && hl) {
          // View mode with highlight (opaque background hides PDF canvas): draw a
          // tick so the checkmark is visible over the highlight colour.
          const mark = document.createElement("div");
          const markSize = Math.min(ch * 0.78, 12);
          mark.style.cssText = `position:absolute;top:50%;left:50%;transform:translate(-50%,-50%);font-size:${markSize}px;line-height:1;color:#000;font-weight:900;font-family:Arial,sans-serif;user-select:none;pointer-events:none;`;
          mark.textContent = "✓";
          wrap.appendChild(mark);
        }
      } else if (isSigF) {
        const thisCleared  = clearedSigFieldsRef.current.has(field.name);
        const showClearBtn = curEdit && isSignedLocalRef.current && !thisCleared;
        const showTextInp  = curEdit && (!isSignedLocalRef.current || thisCleared);
        if (showClearBtn) {
          const btn = document.createElement("button");
          btn.title = "Remove stamped signature"; btn.textContent = "✕";
          btn.style.cssText = `position:absolute;top:2px;right:2px;width:16px;height:16px;background:rgba(239,68,68,0.12);border:1px solid rgba(239,68,68,0.4);border-radius:50%;color:#ef4444;font-size:9px;font-weight:700;cursor:pointer;display:flex;align-items:center;justify-content:center;padding:0;line-height:1;font-family:inherit;`;
          btn.addEventListener("click", () => {
            triggerSave(field.name, ""); clearedSigFieldsRef.current.add(field.name); wrap.innerHTML = "";
            const inp = document.createElement("input"); inp.type = "text"; inp.value = ""; inp.placeholder = "Type name…";
            inp.style.cssText = `width:100%;height:100%;box-sizing:border-box;background:rgba(255,255,255,0.95);border:1px solid #ef4444;outline:none;border-radius:2px;font-size:${fs}px;font-family:Helvetica,Arial,sans-serif;color:#111;padding:1px 3px;cursor:text;`;
            inp.addEventListener("input", e => {
              triggerSave(field.name, e.target.value);
              wrap.style.background = _boxBg(field, e.target.value, curEdit);
              updateHighlightCounts(fieldsRef.current, fieldConfLabelRef.current, fieldValuesRef.current);
            });
            wrap.appendChild(inp); inp.focus();
          });
          wrap.appendChild(btn);
          focusTargets[field.name] = btn;
        } else if (showTextInp) {
          const inp = document.createElement("input"); inp.type = "text"; inp.value = val; inp.placeholder = "Type name…";
          inp.style.cssText = `width:100%;height:100%;box-sizing:border-box;background:rgba(255,255,255,0.85);border:1px solid rgba(230,0,122,0.4);outline:none;border-radius:2px;font-size:${fs}px;font-family:Helvetica,Arial,sans-serif;color:#111;padding:1px 3px;cursor:text;`;
          inp.addEventListener("input", e => {
            triggerSave(field.name, e.target.value);
            wrap.style.background = _boxBg(field, e.target.value, curEdit);
            updateHighlightCounts(fieldsRef.current, fieldConfLabelRef.current, fieldValuesRef.current);
          });
          wrap.appendChild(inp);
          focusTargets[field.name] = inp;
        }
      } else if (curEdit) {
        const inp = document.createElement("input"); inp.type = "text"; inp.value = val;
        // background:transparent lets the wrap's bg (highlight or white) show through;
        // no additional layer means no double-text artifact in edit mode.
        inp.style.cssText = `width:100%;height:100%;box-sizing:border-box;background:transparent;border:none;outline:none;font-size:${fs}px;font-family:Helvetica,Arial,sans-serif;color:#000;padding:1px 3px;cursor:text;`;
        // Item 18: a one-letter Y/N box takes Y or N ("yes" / "no" become the
        // letter, a stray key keeps the answer) and selects itself on focus so
        // typing replaces the answer.
        let lastYn = val;
        if (field.yes_no) {
          inp.title = "Type Y or N";
          inp.autocomplete = "off";
          inp.spellcheck = false;
          inp.style.textAlign = "center";
          inp.style.fontWeight = "700";
          inp.addEventListener("focus", () => { try { inp.select(); } catch { /* not selectable */ } });
        }
        inp.addEventListener("input", e => {
          let next = e.target.value;
          if (field.yes_no) {
            next = normalizeYesNoEntry(next, lastYn, e.target.selectionStart);
            if (e.target.value !== next) e.target.value = next;
            lastYn = next;
          }
          triggerSave(field.name, next);
          wrap.style.background = _boxBg(field, next, curEdit);
          _repaintYesNoGroup(field, curEdit);
          updateHighlightCounts(fieldsRef.current, fieldConfLabelRef.current, fieldValuesRef.current);
        });
        wrap.appendChild(inp);
        focusTargets[field.name] = inp;
      } else if (hl && val && val !== "null" && val !== "None") {
        // Render value as DOM text over the opaque highlight background.
        // The wrap's fully-opaque bg already hides the PDF canvas text beneath.
        const txt = document.createElement("div");
        txt.style.cssText = `width:100%;height:100%;box-sizing:border-box;overflow:hidden;white-space:nowrap;font-size:${fs}px;font-family:Helvetica,Arial,sans-serif;color:#000;font-weight:500;padding:1px 3px;display:flex;align-items:center;`;
        txt.textContent = val;
        wrap.appendChild(txt);
      }
      // Item 18: ACORD draws many Y/N boxes as a strip at the top of a taller
      // answer cell (126 / 127). A click anywhere in that printed cell edits
      // the box - the server sends the cell only where no other box is in it.
      // Appended BEFORE the box, so the box itself stays on top.
      if (curEdit && field.yes_no && field.answer_rect && focusTargets[field.name]) {
        const cell = boxPixelRect(field.answer_rect, scale, pageHeight);
        const target = focusTargets[field.name];
        const hit = document.createElement("div");
        hit.title = "Type Y or N";
        hit.style.cssText = `position:absolute;left:${cell.left}px;top:${cell.top}px;width:${cell.width}px;height:${cell.height}px;pointer-events:all;cursor:text;background:transparent;`;
        hit.addEventListener("mousedown", ev => {
          ev.preventDefault();
          try { target.focus(); if (target.select) target.select(); } catch { /* detached */ }
        });
        overlay.appendChild(hit);
      }
      overlay.appendChild(wrap);
    });
    // The overlay is rebuilt after every page draw; keep the cursor on the box
    // that had it (review, 30 Sep: a needs-attention jump to another page in
    // edit mode focused the box, then the final rebuild threw the input away).
    if (curEdit && _keepFocusName && !pendingFocusRef.current && focusTargets[_keepFocusName]) {
      const t = focusTargets[_keepFocusName];
      requestAnimationFrame(() => {
        try {
          t.focus({ preventScroll: true });
          if (_keepSel && t.type === "text" && typeof t.setSelectionRange === "function") t.setSelectionRange(_keepSel[0], _keepSel[1]);
        } catch { /* detached */ }
      });
    }
    // Item 10: a view-mode double-click asked for this box - focus it now that
    // edit mode has drawn it. Focus only: a checkbox is never toggled by it.
    // The cursor goes to the END of what the box holds with nothing selected
    // (owner, 30 Sep 2026): a selected value is replaced by the first stray key,
    // and one keystroke must never wipe a filled box. A one-letter Y/N box keeps
    // its own select-on-focus - there, typing is meant to replace the answer.
    const want = pendingFocusRef.current;
    if (curEdit && want) {
      pendingFocusRef.current = null;
      const target = focusTargets[want];
      const wantField = pageFields.find(f => f.name === want);
      if (target) {
        requestAnimationFrame(() => {
          try {
            target.focus();
            if (target.type === "text" && !(wantField && wantField.yes_no) && typeof target.setSelectionRange === "function") {
              const end = (target.value || "").length;
              target.setSelectionRange(end, end);
            }
          } catch { /* detached */ }
        });
      }
    }
  };

  // ── Unsaved-edit tracking ──────────────────────────────────────────────
  // A field edit repaints its own highlight IMMEDIATELY and locally, but the
  // SQS panel only moves when `handleToggleEditMode` posts and the backend
  // re-scores. Nothing said so, and the two indicators describe the SAME fact:
  // during a live test of the loss-history checkbox the highlight came back on
  // an untick while the Loss History pillar still read the ticked score, which
  // reads as a scoring bug and is not one. A score computed from a state the
  // user has already changed must not be presented as current.
  //
  // ONE DOOR: `hasUnsavedEdits()` is both the signal reported upward and the
  // gate `handleToggleEditMode` uses to decide whether to post - so the panel
  // can never call an edit pending that the save would then skip, or vice versa.
  const hasUnsavedEdits = () =>
    Object.keys(fieldValuesRef.current).some(
      k => fieldValuesRef.current[k] !== (originalFieldValuesRef.current[k] ?? "")
    ) || clearedSigFieldsRef.current.size > 0;

  const _syncPending = () => {
    const dirty = hasUnsavedEdits();
    setPendingEdits(prev => (prev === dirty ? prev : dirty));
    if (onPendingEditsChange) onPendingEditsChange(formId, dirty);
  };

  const triggerSave = (fn, v) => {
    fieldValuesRef.current = { ...fieldValuesRef.current, [fn]: v };
    _syncPending();
  };

  const handleApplySignature = async () => {
    setShowSignPrompt(null); setApplyingSign(true); setApplySigStage("applying");
    let signedOnServer = false;
    try {
      const res = await fetch(`${API_BASE}/api/apply-signature/${sessionId}/${formId}`, { method: "POST", credentials: "include" });
      if (res.ok) {
        signedOnServer = true;
        setApplySigStage("rendering");
        const freshUrl = `${pdfUrlRef.current || pdfUrl}?_sig=${Date.now()}`;
        const newDoc   = await window.pdfjsLib.getDocument({ url: freshUrl, withCredentials: true, httpHeaders: _pdfAuthHeaders() }).promise;
        // The page the reader is on NOW, and a ticket: a page turn while the
        // signed form was drawing must not be painted over by the old page.
        const seq      = ++renderSeqRef.current;
        const pg       = pageNumRef.current;
        const page     = await newDoc.getPage(pg);
        const vp       = page.getViewport({ scale: _fitScale(page) });
        const off      = _blankCanvas(vp);
        await page.render({ canvasContext: off.getContext("2d"), viewport: vp, renderInteractiveForms: false }).promise;
        setIsSignedLocal(true); isSignedLocalRef.current = true; clearedSigFieldsRef.current = new Set();
        if (seq === renderSeqRef.current && pg === pageNumRef.current && _showRenderedPage(off, newDoc, pg)) {
          manuallyRenderedRef.current = { doc: newDoc, pageNum: pg };
          setRendering(false);
        }
        // Otherwise the newer page is drawn from the signed form by the render
        // effect when the document swaps in below.
        setPdfDoc(newDoc); setTotalPages(newDoc.numPages);
        onSignApplied(formId);
      } else { const d = await res.json().catch(() => ({})); console.error("Sig apply failed:", d.detail); }
    } catch (e) {
      console.error("Sig apply failed:", e);
      if (signedOnServer) {
        // The form IS signed; only the redraw failed, possibly after it took the
        // render ticket. Reload the form so the current page is drawn and the
        // busy state clears - never a stale page with the page buttons disabled.
        setIsSignedLocal(true); isSignedLocalRef.current = true; clearedSigFieldsRef.current = new Set();
        manuallyRenderedRef.current = { doc: null, pageNum: -1 };
        setPdfRefreshKey(k => k + 1);
        onSignApplied(formId);
      }
    }
    finally { setApplyingSign(false); setApplySigStage("idle"); }
  };

  const handleSignClick = () => setShowSignPrompt(savedSignature ? "use" : "none");

  const handleToggleEditMode = async () => {
    // Item 10 (1 Oct 2026): a failed save keeps edit mode on and the typed
    // values in their boxes ("Failed" in the toolbar) - it used to leave edit
    // mode as if the edits had gone through.
    if (editMode && hasUnsavedEdits() && !(await saveEdits())) return;
    setEditMode(m => !m);
  };

  // The request body of the ONE save - the changed boxes, the signed flag and
  // the cleared signature boxes. Read off the refs at call time.
  const _editsPayload = () => {
    const allValues = fieldValuesRef.current;
    const clearedSigFields = Array.from(clearedSigFieldsRef.current);
    const changedValues = {};
    Object.keys(allValues).forEach(k => {
      if (allValues[k] !== (originalFieldValuesRef.current[k] ?? "")) changedValues[k] = allValues[k];
    });
    clearedSigFields.forEach(k => { changedValues[k] = ""; });
    const body = JSON.stringify({ session_id: sessionId, field_updates: { ...changedValues, __form_id__: formId, __signed__: isSignedLocal ? "1" : "0", __cleared_sig_fields__: JSON.stringify(clearedSigFields) } });
    return { allValues, clearedSigFields, body };
  };

  // THE save of typed edits (Orbin item 10, 1 Oct 2026). "Done editing - save"
  // and every path that would replace this viewer - a form switch, an "Open to
  // fix" re-stamp, a download, Refresh - go through it, so a typed edit is
  // never silently dropped. Resolves true when nothing is left unsaved; false
  // when the save failed, with the edits kept in their boxes. One save at a
  // time: a second caller waits for the one in flight. `redraw: false` skips
  // the background redraw when the caller reloads or replaces the viewer anyway.
  const saveEdits = ({ redraw = true } = {}) => {
    // A save already running carried the boxes as they were when it started;
    // anything typed since is saved straight after it, so "saved" always means
    // every edit on screen.
    if (saveInFlightRef.current) {
      return saveInFlightRef.current.then((ok) => (ok && hasUnsavedEdits() ? saveEdits({ redraw }) : ok));
    }
    if (!hasUnsavedEdits()) return Promise.resolve(true);
    const run = (async () => {
      setSaveStatus("saving");
      try {
        const { allValues, clearedSigFields, body } = _editsPayload();
        const res = await fetch(`${API_BASE}/api/update-pdf`, {
          method: "POST",
          credentials: "include",
          headers: { "Content-Type": "application/json" },
          body,
        });
        if (!res.ok) { setSaveStatus("error"); return false; }
        const data = await res.json();
        setFieldValues({ ...allValues }); originalFieldValuesRef.current = { ...allValues }; clearedSigFieldsRef.current = new Set();
        // The panel's score is current again as of this response. Cleared
        // only on OK - a failed save leaves the edits genuinely pending.
        _syncPending();
        const allSigF = fieldsRef.current.filter(f => _isSigField(f.name) && !f.painted).map(f => f.name);
        if (allSigF.length > 0 && allSigF.every(n => clearedSigFields.includes(n))) setIsSignedLocal(false);
        if (data?.sqs && onSqsUpdate) onSqsUpdate(formId, data.sqs, { packageSqs: data.package_sqs, crossIssues: data.cross_issues, groupedCrossIssues: data.grouped_cross_issues });
        // Sync confidence labels from backend so overlay reflects the post-save state
        // (e.g. user-edited fields become "filled", not "low_confidence").
        if (data?.confidence) {
          fieldConfLabelRef.current = { ...fieldConfLabelRef.current, ...data.confidence };
          updateHighlightCounts(fieldsRef.current, fieldConfLabelRef.current, allValues);
        }
        // Orbin item 14: a save can end the client's signature on this form;
        // re-read the boxes so a no-longer-painted line is drawn and counted.
        if (fieldsRef.current.some(f => f.applicant_signed)) fetchFields().catch(() => {});
        if (redraw) { setSaveStatus("generating"); _loadPdfInBackground(); }
        else { setSaveStatus("saved"); setTimeout(() => setSaveStatus("idle"), 2000); }
        return true;
      } catch { setSaveStatus("error"); return false; }
      finally { saveInFlightRef.current = null; }
    })();
    saveInFlightRef.current = run;
    return run;
  };

  // Last resort for a way out nothing could wait on - the page closing after
  // the browser's own "Leave site?" prompt, or the viewer unmounting on a path
  // that did not save first: the same request, sent so it outlives the page.
  const _saveOnExit = () => {
    if (saveInFlightRef.current || !hasUnsavedEdits() || !sessionId || !formId) return;
    try {
      fetch(`${API_BASE}/api/update-pdf`, {
        method: "POST", credentials: "include", keepalive: true,
        headers: { "Content-Type": "application/json" },
        body: _editsPayload().body,
      }).catch(() => {});
    } catch { /* the page is going away */ }
  };
  exitSaveRef.current = _saveOnExit;

  // The parent's handle (AcordModal saves before it replaces this viewer).
  useEffect(() => {
    if (!editsRef) return undefined;
    const handle = { hasUnsaved: () => hasUnsavedEdits() || !!saveInFlightRef.current, save: () => saveEdits() };
    editsRef.current = handle;
    return () => { if (editsRef.current === handle) editsRef.current = null; };
  });

  // Unsaved edits: the browser asks before the tab closes or reloads, and if
  // the producer leaves anyway - or this viewer unmounts with edits still in
  // its boxes - the exit save sends them.
  useEffect(() => {
    const onBeforeUnload = (e) => {
      if (!hasUnsavedEdits() && !saveInFlightRef.current) return undefined;
      e.preventDefault();
      e.returnValue = "";
      return "";
    };
    const onPageHide = () => { if (exitSaveRef.current) exitSaveRef.current(); };
    window.addEventListener("beforeunload", onBeforeUnload);
    window.addEventListener("pagehide", onPageHide);
    return () => {
      window.removeEventListener("beforeunload", onBeforeUnload);
      window.removeEventListener("pagehide", onPageHide);
      if (exitSaveRef.current) exitSaveRef.current();
    };
  }, []);

  const _loadPdfInBackground = () => {
    if (!pdfjsReady) return;
    window.pdfjsLib.getDocument({ url: `${pdfUrlRef.current || pdfUrl}?_r=${Date.now()}`, withCredentials: true, httpHeaders: _pdfAuthHeaders() }).promise
      .then(async newDoc => {
        // The saved form redraws the page the reader is on NOW - not the page
        // they were on when they clicked save (they can turn pages, or jump
        // from the needs-attention list, while the form regenerates).
        const seq = ++renderSeqRef.current;
        const pg  = pageNumRef.current;
        try {
          const page = await newDoc.getPage(pg);
          const vp   = page.getViewport({ scale: _fitScale(page) });
          const off  = _blankCanvas(vp);
          await page.render({ canvasContext: off.getContext("2d"), viewport: vp, renderInteractiveForms: false }).promise;
          if (seq === renderSeqRef.current && pg === pageNumRef.current && _showRenderedPage(off, newDoc, pg)) {
            manuallyRenderedRef.current = { doc: newDoc, pageNum: pg };
            setRendering(false);
          }
          // Otherwise a newer render or page turn owns the canvas; the swap
          // below makes the render effect draw the current page of the saved form.
          setPdfDoc(newDoc); setTotalPages(newDoc.numPages);
          setSaveStatus("saved"); setTimeout(() => setSaveStatus("idle"), 2000);
        } catch { setPdfDoc(newDoc); setTotalPages(newDoc.numPages); setSaveStatus("saved"); setTimeout(() => setSaveStatus("idle"), 2000); }
      })
      .catch(() => setSaveStatus("error"));
  };

  const goPage = n => { if (n >= 1 && n <= totalPages) setPageNum(n); };

  // Item 10 (client, 22 Sep): "producers will want to click directly on the
  // form to fix fields". In VIEW mode a double-click on a box turns edit mode on
  // and focuses that box. It never changes a value itself - a checkbox is only
  // focused, never ticked - and it waits whenever the Edit button would.
  const editBusy = saveStatus === "saving" || saveStatus === "generating";
  const handleCanvasDoubleClick = (e) => {
    if (editModeRef.current || editBusy || applyingSign || loadingStage !== "idle" || !fieldsLoaded) return;
    const canvas = canvasRef.current;
    if (!canvas || !canvas.width) return;
    const box = canvas.getBoundingClientRect();
    if (!box.width || !box.height) return;
    const px = (e.clientX - box.left) * (canvas.width / box.width);
    const py = (e.clientY - box.top) * (canvas.height / box.height);
    const scale = renderScaleRef.current;
    // Hit-test the page the canvas SHOWS - during a page turn the toolbar is
    // already on the next page while this one is still on screen.
    const shown = shownPageRef.current.page;
    if (!shown) return;
    const pd = pageDimsRef.current[shown - 1];
    const pageHeight = pd ? pd.height : canvas.height / scale;
    const hit = hitTestBox(fieldsRef.current.filter(f => !f.painted), shown - 1, px, py, scale, pageHeight);
    if (!hit) return;
    e.preventDefault();
    pendingFocusRef.current = hit.name;
    setEditMode(true);
  };

  return (
    <div style={{ display: "flex", flexDirection: "column", height: "100%", background: "#181c27", borderRadius: 8, overflow: "hidden" }}>
      {(saveStatus === "saving" || saveStatus === "generating") && <SaveStageOverlay stage={saveStatus} />}

      {applySigStage !== "idle" && (
        <div className="upgrade-stage-overlay">
          <div className="upgrade-stage-spinner" />
          <div className="upgrade-stage-steps">
            <div className={`upgrade-stage-step ${applySigStage === "applying" ? "active" : "done"}`}><div className="upgrade-stage-dot" />{applySigStage === "applying" ? "Applying signature…" : "✓ Applying signature"}</div>
            <div className={`upgrade-stage-step ${applySigStage === "rendering" ? "active" : ""}`}><div className="upgrade-stage-dot" />Generating signed form…</div>
          </div>
        </div>
      )}

      {loadingStage !== "idle" && (
        <div className="upgrade-stage-overlay">
          <div className="upgrade-stage-spinner" />
          <div className="upgrade-stage-steps">
            <div className={`upgrade-stage-step ${loadingStage === "loading" ? "active" : "done"}`}><div className="upgrade-stage-dot" />{loadingStage === "loading" ? "Loading form…" : "✓ Loading form"}</div>
            <div className={`upgrade-stage-step ${loadingStage === "rendering" ? "active" : ""}`}><div className="upgrade-stage-dot" />Rendering preview…</div>
          </div>
        </div>
      )}

      {showSignPrompt === "use" && <UseSignaturePrompt signature={savedSignature} onApply={handleApplySignature} onManage={() => { setShowSignPrompt(null); onOpenSignatureModal(); }} onClose={() => setShowSignPrompt(null)} />}
      {showSignPrompt === "none" && <NoSignaturePrompt onSetup={() => { setShowSignPrompt(null); onOpenSignatureModal(); }} onClose={() => setShowSignPrompt(null)} />}

      {/* Toolbar */}
      <div className="pdfviewer-toolbar-top" style={{ display: "flex", alignItems: "center", justifyContent: "space-between", padding: "8px 14px", background: "#1e2436", borderBottom: "1px solid #2a3047", flexShrink: 0, gap: 8, flexWrap: "wrap" }}>
        <div style={{ display: "flex", alignItems: "center", gap: 6, flexWrap: "wrap", minWidth: 0 }}>
          <span title={formName} style={{ color: "#e8eaf2", fontSize: 13, fontWeight: 600, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap", minWidth: 0, maxWidth: 420 }}>{formName}</span>
          {fieldsLoaded && (
            <>
              {highlightCounts.yellow  > 0 && <span title="Required fields that are still empty - fill before sending." style={{ background: "rgb(254,243,199)", color: "#92400e", fontSize: 10, padding: "1px 7px", borderRadius: 10, border: "none", fontWeight: 600 }}>{highlightCounts.yellow} Required</span>}
              {highlightCounts.review  > 0 && <span title="Filled by the AI or calculated by us, and not confirmed in your uploaded documents - verify before download." style={{ background: "rgb(254,215,170)", color: "#9a3412", fontSize: 10, padding: "1px 7px", borderRadius: 10, border: "none", fontWeight: 600 }}>{highlightCounts.review} Verify</span>}
              {highlightCounts.verified > 0 && <span title="AI-filled and confirmed present in your uploaded documents." style={{ background: "rgb(254,226,226)", color: "#991b1b", fontSize: 10, padding: "1px 7px", borderRadius: 10, border: "none", fontWeight: 600 }}>{highlightCounts.verified} AI-OK</span>}
              {highlightCounts.green   > 0 && <span title="Filled by your client via the questionnaire." style={{ background: "rgb(187,247,208)", color: "#166534", fontSize: 10, padding: "1px 7px", borderRadius: 10, border: "none", fontWeight: 600 }}>{highlightCounts.green} Client</span>}
              {(highlightCounts.yellow + highlightCounts.review + highlightCounts.verified + highlightCounts.green) > 0 && (
                <span
                  style={{ position: "relative", display: "inline-flex" }}
                  onMouseEnter={canHover ? () => setShowLegend(true) : undefined}
                  onMouseLeave={canHover ? () => setShowLegend(false) : undefined}
                >
                  <span
                    onClick={() => setShowLegend(v => !v)}
                    role="button"
                    aria-label="What do the highlight colors mean?"
                    style={{ cursor: "pointer", width: 15, height: 15, borderRadius: "50%", border: "1px solid #4a5578", color: "#9aa4bf", fontSize: 10, fontWeight: 700, display: "inline-flex", alignItems: "center", justifyContent: "center", userSelect: "none", lineHeight: 1 }}
                  >?</span>
                  {showLegend && (
                    <div style={{ position: "absolute", top: "calc(100% + 6px)", left: 0, zIndex: 60, background: "#1e2436", border: "1px solid #2a3047", borderRadius: 8, padding: "8px 10px", width: 236, boxShadow: "0 6px 20px rgba(0,0,0,0.35)" }} onClick={() => setShowLegend(false)}>
                      {[
                        ["rgb(254,243,199)", "Required", "Empty required field - fill it"],
                        ["rgb(254,215,170)", "Verify", "AI-filled, NOT found in your documents"],
                        ["rgb(254,226,226)", "AI-OK", "AI-filled and found in your documents"],
                        ["rgb(187,247,208)", "Client", "Filled by your client"],
                      ].map(([c, label, desc]) => (
                        <div key={label} style={{ display: "flex", alignItems: "flex-start", gap: 6, padding: "3px 0" }}>
                          <span style={{ width: 11, height: 11, borderRadius: 2, background: c, flexShrink: 0, marginTop: 2 }} />
                          <span style={{ fontSize: 10, lineHeight: 1.35 }}><b style={{ color: "#e8eaf2" }}>{label}</b> <span style={{ color: "#9aa4bf" }}>{desc}</span></span>
                        </div>
                      ))}
                    </div>
                  )}
                </span>
              )}
            </>
          )}
        </div>

        <div className="pdfviewer-toolbar-actions" style={{ display: "flex", alignItems: "center", gap: 5, flexWrap: "wrap" }}>
          {/* The toolbar's "Unsaved" marker was removed (owner, 30 Sep 2026: it
              wrapped the toolbar onto two lines). The side panel still says the
              score is from the last save while edits are pending (AcordModal). */}
          {saveStatus === "saving" && <span style={{ display: "flex", alignItems: "center", gap: 3, color: "#f59e0b", fontSize: 11, fontWeight: 600 }}><span style={{ width: 10, height: 10, border: "2px solid #f59e0b", borderTopColor: "transparent", borderRadius: "50%", display: "inline-block", animation: "spin 0.7s linear infinite" }} />Saving…</span>}
          {saveStatus === "saved"   && <span style={{ color: "#22c55e", fontSize: 11, fontWeight: 600 }}>✓ Saved</span>}
          {saveStatus === "error"   && <span title="Your edits are still in their boxes. Save again before leaving this form." style={{ color: "#ef4444", fontSize: 11, fontWeight: 600 }}>Save failed - edits kept</span>}

          <button onClick={handleRefresh} disabled={loadingStage !== "idle"}
            title="Refresh - picks up client-submitted answers and shows green highlights"
            style={{ display: "flex", alignItems: "center", gap: 3, padding: "4px 9px", borderRadius: 6, border: "1px solid #2a3047", background: "#252a3d", color: "#8b93b0", fontSize: 11, fontWeight: 600, cursor: loadingStage !== "idle" ? "wait" : "pointer", fontFamily: "inherit" }}>
            Refresh
          </button>

          {/* Item 10 (client, 22 Sep): "Make Edit button WAY more obvious". The
              one filled, primary-colour, largest button in the toolbar. Same
              handler, same disabled / wait states as before. */}
          <button onClick={handleToggleEditMode} disabled={editBusy}
            className={`pdfviewer-edit-btn${editMode ? " is-editing" : ""}`}
            aria-pressed={editMode}
            title={editMode ? "Save your edits and update the score" : "Edit the boxes on this form"}
            style={{ cursor: editBusy ? "wait" : "pointer", opacity: editBusy ? 0.7 : 1 }}>
            {editMode ? (
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="3" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><polyline points="20 6 9 17 4 12" /></svg>
            ) : (
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.4" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><path d="M12 20h9" /><path d="M16.5 3.5a2.12 2.12 0 0 1 3 3L7 19l-4 1 1-4Z" /></svg>
            )}
            {editMode ? "Done editing - save" : "Edit form"}
          </button>

          <button onClick={handleSignClick} disabled={applyingSign}
            title={isSignedLocal ? "Signature applied - enter edit mode to remove" : savedSignature ? "Apply your saved signature" : "Set up a signature"}
            style={{ display: "flex", alignItems: "center", gap: 4, padding: "4px 10px", borderRadius: 6, border: `1px solid ${isSignedLocal ? "#10b981" : "rgba(230,0,122,0.4)"}`, background: isSignedLocal ? "rgba(16,185,129,0.1)" : "rgba(230,0,122,0.08)", color: isSignedLocal ? "#10b981" : "#E61B84", fontSize: 12, fontWeight: 600, cursor: applyingSign ? "wait" : "pointer", fontFamily: "inherit", opacity: applyingSign ? 0.7 : 1 }}>
            {applyingSign ? <><span style={{ width: 10, height: 10, border: "2px solid currentColor", borderTopColor: "transparent", borderRadius: "50%", display: "inline-block", animation: "spin 0.7s linear infinite" }} />Signing…</> : isSignedLocal ? "Signed" : "Sign"}
          </button>

          {rendering && <span style={{ color: "#4f7cff", fontSize: 11 }}>Rendering…</span>}

          <button onClick={() => goPage(pageNum - 1)} disabled={pageNum <= 1 || rendering} style={{ width: 28, height: 28, borderRadius: 6, border: "1px solid #2a3047", background: "#252a3d", color: "#e8eaf2", cursor: "pointer", fontSize: 16, display: "flex", alignItems: "center", justifyContent: "center" }}>‹</button>
          <span style={{ color: "#6b7899", fontSize: 12, minWidth: 44, textAlign: "center" }}>{totalPages ? `${pageNum}/${totalPages}` : "-"}</span>
          <button onClick={() => goPage(pageNum + 1)} disabled={pageNum >= totalPages || rendering} style={{ width: 28, height: 28, borderRadius: 6, border: "1px solid #2a3047", background: "#252a3d", color: "#e8eaf2", cursor: "pointer", fontSize: 16, display: "flex", alignItems: "center", justifyContent: "center" }}>›</button>

          {onFormNav?.total > 1 && (<>
            <div style={{ width: 1, height: 18, background: "#2a3047", margin: "0 2px" }} />
            <button onClick={onFormNav.goPrev} disabled={onFormNav.activeIdx <= 0} style={{ width: 28, height: 28, borderRadius: 6, border: "1px solid #2a3047", background: "#252a3d", color: "#e8eaf2", cursor: "pointer", fontSize: 13, display: "flex", alignItems: "center", justifyContent: "center" }}>«</button>
            <span style={{ color: "#4f7cff", fontSize: 11, fontWeight: 600 }}>Form {onFormNav.activeIdx + 1}/{onFormNav.total}</span>
            <button onClick={onFormNav.goNext} disabled={onFormNav.activeIdx >= onFormNav.total - 1} style={{ width: 28, height: 28, borderRadius: 6, border: "1px solid #2a3047", background: "#252a3d", color: "#e8eaf2", cursor: "pointer", fontSize: 13, display: "flex", alignItems: "center", justifyContent: "center" }}>»</button>
          </>)}
        </div>
      </div>

      {editMode && (
        <div className="pdfviewer-edit-hint" style={{ padding: "5px 14px", background: "rgba(245,158,11,0.06)", borderBottom: "1px solid rgba(245,158,11,0.15)", display: "flex", gap: 14, flexWrap: "wrap", alignItems: "center" }}>
          <span style={{ color: "#f59e0b", fontSize: 11 }}>Click any box to edit - "Done editing - save" saves all changes</span>
          <span style={{ fontSize: 10, display: "flex", alignItems: "center", gap: 3 }}><span style={{ width: 11, height: 11, background: "rgb(254,243,199)", border: "none", borderRadius: 2, display: "inline-block" }} /><span style={{ color: "#9aa4bf" }}>Required field</span></span>
          <span style={{ fontSize: 10, display: "flex", alignItems: "center", gap: 3 }}><span style={{ width: 11, height: 11, background: "rgb(254,215,170)", border: "none", borderRadius: 2, display: "inline-block" }} /><span style={{ color: "#9aa4bf" }}>Verify (not found in docs)</span></span>
          <span style={{ fontSize: 10, display: "flex", alignItems: "center", gap: 3 }}><span style={{ width: 11, height: 11, background: "rgb(254,226,226)", border: "none", borderRadius: 2, display: "inline-block" }} /><span style={{ color: "#9aa4bf" }}>AI-OK (found in docs)</span></span>
          {highlightCounts.green > 0 && <span style={{ fontSize: 10, display: "flex", alignItems: "center", gap: 3 }}><span style={{ width: 11, height: 11, background: "rgb(187,247,208)", border: "none", borderRadius: 2, display: "inline-block" }} /><span style={{ color: "#9aa4bf" }}>Client-filled</span></span>}
        </div>
      )}

      {!editMode && fieldsLoaded && pdfDoc && !loadError && (
        <div className="pdfviewer-edit-hint pdfviewer-view-hint">
          <span>Double-click any box to edit it</span>
        </div>
      )}

      <div ref={containerRef} className="pdfviewer-canvas-container" style={{ flex: 1, overflowY: "auto", overflowX: "auto", display: "flex", justifyContent: "center", alignItems: "flex-start", padding: 12, background: "#252a3d", minHeight: 0 }}>
        {loadError ? (
          <div style={{ color: "#6b7899", textAlign: "center", marginTop: 60 }}>Could not load PDF preview.</div>
        ) : !pdfDoc ? (
          <div style={{ color: "#6b7899", textAlign: "center", marginTop: 60 }}>
            <div className="loading-spinner" style={{ margin: "0 auto 12px" }} />Loading PDF…
          </div>
        ) : (
          <div className="pdfviewer-canvas-wrapper" onDoubleClick={handleCanvasDoubleClick} style={{ position: "relative", display: "inline-block", lineHeight: 0, boxShadow: "0 8px 40px rgba(0,0,0,0.6)", borderRadius: 2 }}>
            <canvas ref={canvasRef} style={{ display: "block" }} />
            <div ref={overlayRef} style={{ position: "absolute", top: 0, left: 0, zIndex: 1, pointerEvents: editMode ? "all" : "none" }} />
            {saveStatus === "saving" && (
              <div style={{ position: "absolute", inset: 0, background: "rgba(15,23,42,0.65)", display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center", gap: 10, borderRadius: 2, backdropFilter: "blur(2px)", zIndex: 100 }}>
                <div style={{ width: 32, height: 32, border: "3px solid rgba(255,255,255,0.2)", borderTopColor: "#f59e0b", borderRadius: "50%", animation: "spin 0.8s linear infinite" }} />
                <span style={{ color: "#fff", fontSize: 13, fontWeight: 600 }}>Applying edits…</span>
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  );
}
