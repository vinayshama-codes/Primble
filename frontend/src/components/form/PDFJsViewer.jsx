import { useState, useEffect, useRef } from "react";
import { API_BASE } from "../../config/constants";
import SaveStageOverlay from "../overlays/SaveStageOverlay";
import UseSignaturePrompt from "../signature/UseSignaturePrompt";
import NoSignaturePrompt from "../signature/NoSignaturePrompt";

const PDFJS_CDN    = "https://cdnjs.cloudflare.com/ajax/libs/pdf.js/3.11.174/pdf.min.js";
const PDFJS_WORKER = "https://cdnjs.cloudflare.com/ajax/libs/pdf.js/3.11.174/pdf.worker.min.js";

// Yellow only for these two fields on ACORD 126 when empty
const YELLOW_REQUIRED = new Set(["NamedInsured_Signature_A", "NamedInsured_SignatureDate_A"]);

export default function PDFJsViewer({
  pdfUrl, formName, onFormNav, sessionId, formId, token,
  savedSignature, isSigned, onSignApplied, onOpenSignatureModal,
  clientFilledFields = [],
  onRefreshFields,
}) {
  const canvasRef              = useRef(null);
  const containerRef           = useRef(null);
  const renderTask             = useRef(null);
  const overlayRef             = useRef(null);
  const fieldValuesRef         = useRef({});
  const fieldConfLabelRef      = useRef({}); // stores "filled"|"low_confidence"|"missing_required"
  const clearedSigFieldsRef    = useRef(new Set());
  const originalFieldValuesRef = useRef({});
  const pdfUrlRef              = useRef("");
  const fieldsRef              = useRef([]);
  const pageDimsRef            = useRef([]);
  const manuallyRenderedRef    = useRef({ doc: null, pageNum: -1 });
  const editModeRef            = useRef(false);
  const clientFilledRef        = useRef([]);

  const [pdfjsReady,    setPdfjsReady]    = useState(!!window.pdfjsLib);
  const [pdfDoc,        setPdfDoc]        = useState(null);
  const [pageNum,       setPageNum]       = useState(1);
  const [totalPages,    setTotalPages]    = useState(0);
  const [rendering,     setRendering]     = useState(false);
  const [loadError,     setLoadError]     = useState(false);
  const [editMode,      setEditMode]      = useState(false);
  const [fields,        setFields]        = useState([]);
  const [pageDims,      setPageDims]      = useState([]);
  const [fieldValues,   setFieldValues]   = useState({});
  const [saveStatus,    setSaveStatus]    = useState("idle");
  const [fieldsLoaded,  setFieldsLoaded]  = useState(false);
  const [isSignedLocal, setIsSignedLocal] = useState(isSigned);
  const [showSignPrompt,setShowSignPrompt]= useState(null);
  const [applyingSign,  setApplyingSign]  = useState(false);
  const [applySigStage, setApplySigStage] = useState("idle");
  const [loadingStage,  setLoadingStage]  = useState("idle");
  const [refreshing,    setRefreshing]    = useState(false);
  const [highlightCounts, setHighlightCounts] = useState({ pink: 0, yellow: 0, green: 0 });

  useEffect(() => { clientFilledRef.current = clientFilledFields; }, [clientFilledFields]);
  useEffect(() => { editModeRef.current = editMode; }, [editMode]);
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
    fieldConfLabelRef.current = {};
    fieldsRef.current = []; pageDimsRef.current = []; editModeRef.current = false;
    setPageDims([]); setFieldsLoaded(false); setSaveStatus("idle");
    setPdfDoc(null); setTotalPages(0); setLoadError(false);
    setShowSignPrompt(null); setApplyingSign(false);
    setApplySigStage("idle"); setLoadingStage("idle");
    clearedSigFieldsRef.current = new Set();
    manuallyRenderedRef.current = { doc: null, pageNum: -1 };
    setHighlightCounts({ pink: 0, yellow: 0, green: 0 });
  }, [formId]);

  // Load PDF
  useEffect(() => {
    if (!pdfjsReady || !pdfUrl) return;
    pdfUrlRef.current = pdfUrl;
    setLoadError(false); setLoadingStage("loading");
    const url  = `${pdfUrl}&_r=${Date.now()}`;
    const task = window.pdfjsLib.getDocument(url);
    task.promise
      .then(doc => { setPdfDoc(doc); setTotalPages(doc.numPages); })
      .catch(err => {
        if (err?.name !== "UnexpectedResponseException" && err?.message !== "Worker was destroyed") {
          setLoadError(true); setLoadingStage("idle");
        }
      });
    return () => { try { task.destroy(); } catch (_) {} };
  }, [formId, pdfjsReady]); // eslint-disable-line

  // Render page to canvas
  useEffect(() => {
    if (!pdfDoc || !canvasRef.current) return;
    const mr = manuallyRenderedRef.current;
    if (mr.doc === pdfDoc && mr.pageNum === pageNum) { setLoadingStage("idle"); return; }
    const doRender = async () => {
      setRendering(true);
      setLoadingStage(s => (s === "loading" ? "rendering" : s));
      if (renderTask.current) { try { renderTask.current.cancel(); } catch (_) {} }
      try {
        const page   = await pdfDoc.getPage(pageNum);
        const canvas = canvasRef.current; if (!canvas) return;
        const avail  = containerRef.current ? containerRef.current.clientWidth - 48 : 720;
        const scale  = Math.min(2.2, Math.max(1.0, avail / page.getViewport({ scale: 1 }).width));
        const vp     = page.getViewport({ scale });
        canvas.width = vp.width; canvas.height = vp.height;
        const ctx    = canvas.getContext("2d");
        ctx.fillStyle = "#fff"; ctx.fillRect(0, 0, canvas.width, canvas.height);
        const t = page.render({ canvasContext: ctx, viewport: vp, renderInteractiveForms: false });
        renderTask.current = t;
        await t.promise;
        buildOverlay(scale, vp.width, vp.height, fieldValuesRef.current);
      } catch (e) {
        if (e?.name !== "RenderingCancelledException") setLoadError(true);
      } finally { setRendering(false); setLoadingStage("idle"); }
    };
    doRender();
  }, [pdfDoc, pageNum]); // eslint-disable-line

  // Rebuild overlay when anything changes
  useEffect(() => {
    if (!canvasRef.current || !overlayRef.current || !fieldsLoaded) return;
    const canvas = canvasRef.current;
    const pd     = pageDimsRef.current[pageNum - 1];
    if (!pd || canvas.width === 0) return;
    const avail = containerRef.current ? containerRef.current.clientWidth - 48 : 720;
    const scale = Math.min(2.2, Math.max(1.0, avail / pd.width));
    buildOverlay(scale, canvas.width, canvas.height, fieldValuesRef.current);
  }, [pageNum, editMode, isSignedLocal, fields, fieldsLoaded, pageDims, clientFilledFields]); // eslint-disable-line

  // Fetch fields from backend
  const fetchFields = () =>
    fetch(`${API_BASE}/api/fields/${sessionId}/${formId}?token=${token}`)
      .then(r => r.ok ? r.json() : null)
      .then(data => {
        if (!data?.success) return;
        const vals = {}; const confLabels = {};
        (data.fields || []).forEach(f => {
          vals[f.name]       = f.value            || "";
          confLabels[f.name] = f.confidence_label || "";
          // f.client_filled comes from backend (patched above)
          if (f.client_filled) {
            clientFilledRef.current = [...new Set([...clientFilledRef.current, f.name])];
          }
        });
        fieldsRef.current          = data.fields    || [];
        pageDimsRef.current        = data.page_dims || [];
        fieldConfLabelRef.current  = confLabels;
        setFields(data.fields || []);
        setPageDims(data.page_dims || []);
        setFieldValues(vals);
        fieldValuesRef.current         = vals;
        originalFieldValuesRef.current = { ...vals };
        setFieldsLoaded(true);
        updateHighlightCounts(data.fields || [], confLabels, clientFilledRef.current, vals);
      });

  useEffect(() => {
    if (!sessionId || !formId || !token) return;
    const controller = new AbortController();
    fetch(`${API_BASE}/api/fields/${sessionId}/${formId}?token=${token}`, { signal: controller.signal })
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
        setFieldsLoaded(true);
        updateHighlightCounts(data.fields || [], confLabels, clientFilledRef.current, vals);
      })
      .catch(err => { if (err?.name !== "AbortError") console.error("Fields fetch error:", err); });
    return () => controller.abort();
  }, [sessionId, formId, token]); // eslint-disable-line

  const updateHighlightCounts = (fieldList, confLabels, clientFilled, vals) => {
    let pink = 0, yellow = 0, green = 0;
    fieldList.forEach(f => {
      const name = f.name;
      const val  = (vals[name] || f.value || "").toString().trim();
      if (clientFilled.includes(name)) { green++; return; }
      if (YELLOW_REQUIRED.has(name) && (!val || val === "null" || val === "None")) { yellow++; return; }
      const conf = confLabels[name];
      if (conf === "low_confidence" || conf === "missing_required") pink++;
    });
    setHighlightCounts({ pink, yellow, green });
  };

  // Issue 2 & 4: Refresh — re-fetches fields AND clientFilledFields, then redraws overlay
  // REPLACE handleRefresh:
const handleRefresh = async () => {
  if (!sessionId || !formId || !token) return;
  setRefreshing(true);
  try {
    // Step 1: get updated clientFilledFields from parent (ARQ answered fields)
    if (onRefreshFields) {
      const freshClientFilled = await onRefreshFields();
      if (Array.isArray(freshClientFilled)) {
        clientFilledRef.current = freshClientFilled;
      }
    }
    // Step 2: re-fetch fields with updated confidence + values
    await fetchFields();
    // Step 3: redraw
    const canvas = canvasRef.current;
    const pd     = pageDimsRef.current[pageNum - 1];
    if (canvas && pd && canvas.width > 0) {
      const avail = containerRef.current ? containerRef.current.clientWidth - 48 : 720;
      const scale = Math.min(2.2, Math.max(1.0, avail / pd.width));
      buildOverlay(scale, canvas.width, canvas.height, fieldValuesRef.current);
    }
  } finally { setRefreshing(false); }
};

  const _isSigField = (name) => {
    const fn = (name || "").toLowerCase().replace(/[\s\-.]/g, "_");
    if (["date","designation","title","printed","print_name","name_of","countersign"].some(ex => fn.includes(ex))) return false;
    return ["signature","producer_sig","insured_sig","authorized_sig","applicant_sig","agent_sig",
            "signedby","signed_by","sign_here","producersig","agentsig","sig_producer","sig_insured","sig_agent"]
           .some(p => fn.includes(p));
  };

  // Issue 1: Correct highlight logic
  // GREEN  = clientFilled (highest priority)
  // YELLOW = NamedInsured_Signature_A / NamedInsured_SignatureDate_A when empty
  // PINK   = confidence_label is "low_confidence" or "missing_required" (anything not "filled")
  // REPLACE _getHighlight entirely:
  const _getHighlight = (fieldName, val) => {
  // GREEN: client filled (highest priority)
  if (clientFilledRef.current.includes(fieldName)) return "green";
  const v    = (val || "").toString().trim();
  const conf = fieldConfLabelRef.current[fieldName];

  if (YELLOW_REQUIRED.has(fieldName)) {
    if (!v || v === "null" || v === "None") return "yellow";
    return null; // Issue 4: filled signature → no yellow
  }
  if (conf === "low_confidence" && v && v !== "null" && v !== "None") return "pink";
  return null;
};

  const buildOverlay = (scale, canvasW, canvasH, liveValues) => {
    const overlay = overlayRef.current;
    if (!overlay) return;
    overlay.innerHTML    = "";
    overlay.style.width  = canvasW + "px";
    overlay.style.height = canvasH + "px";
    const pd         = pageDimsRef.current[pageNum - 1];
    const pageHeight = pd ? pd.height : canvasH / scale;
    const pageFields = fieldsRef.current.filter(f => f.page === pageNum - 1);
    const curEdit    = editModeRef.current;

    pageFields.forEach(field => {
      const { x, y, width, height } = field.rect;
      const cx  = x * scale;
      const cy  = (pageHeight - y - height) * scale;
      const cw  = Math.max(width  * scale, 18);
      const ch  = Math.max(height * scale, 14);
      const fs  = Math.max(7, Math.min(ch * 0.58, 12));
      const val = liveValues[field.name] ?? field.value ?? "";
      const hl  = _getHighlight(field.name, val);

      let border = "0px solid transparent";
      let bg     = "transparent";
      if      (hl === "green")  { border = "2px solid #10b981"; bg = "rgba(16,185,129,0.13)"; }
      else if (hl === "yellow") { border = "2px solid #f59e0b"; bg = curEdit ? "rgba(245,158,11,0.22)" : "rgba(245,158,11,0.10)"; }
      else if (hl === "pink")   { border = "2px solid #e6007a"; bg = curEdit ? "rgba(230,0,122,0.12)" : "rgba(230,0,122,0.06)"; }
      else if (curEdit)         { border = "1px solid rgba(79,124,255,0.4)"; bg = "rgba(255,255,255,0.85)"; }

      const wrap = document.createElement("div");
      wrap.style.cssText = `position:absolute;left:${cx}px;top:${cy}px;width:${cw}px;height:${ch}px;pointer-events:${curEdit?"all":"none"};border:${border};border-radius:2px;background:${bg};box-sizing:border-box;transition:all 0.1s ease;`;

      const isSigF = _isSigField(field.name);

      if (field.type === "checkbox") {
        const cb = document.createElement("input");
        cb.type = "checkbox";
        cb.checked  = val === "Yes" || val === "true" || val === "1" || val === "On";
        cb.disabled = !curEdit;
        cb.style.cssText = `position:absolute;top:50%;left:50%;transform:translate(-50%,-50%);width:${Math.min(ch*0.7,13)}px;height:${Math.min(ch*0.7,13)}px;margin:0;cursor:${curEdit?"pointer":"default"};accent-color:#4f7cff;opacity:${curEdit?1:0.5};`;
        cb.addEventListener("change", e => triggerSave(field.name, e.target.checked ? "Yes" : "Off"));
        wrap.appendChild(cb);
      } else if (isSigF) {
        const thisCleared  = clearedSigFieldsRef.current.has(field.name);
        const showClearBtn = curEdit && isSignedLocal && !thisCleared;
        const showTextInp  = curEdit && (!isSignedLocal || thisCleared);
        if (showClearBtn) {
          const btn = document.createElement("button");
          btn.title = "Remove stamped signature"; btn.textContent = "✕";
          btn.style.cssText = `position:absolute;top:2px;right:2px;width:16px;height:16px;background:rgba(239,68,68,0.12);border:1px solid rgba(239,68,68,0.4);border-radius:50%;color:#ef4444;font-size:9px;font-weight:700;cursor:pointer;display:flex;align-items:center;justify-content:center;padding:0;line-height:1;font-family:inherit;`;
          btn.addEventListener("click", () => {
            triggerSave(field.name, ""); clearedSigFieldsRef.current.add(field.name); wrap.innerHTML = "";
            const inp = document.createElement("input"); inp.type = "text"; inp.value = ""; inp.placeholder = "Type name…";
            inp.style.cssText = `width:100%;height:100%;box-sizing:border-box;background:rgba(255,255,255,0.95);border:1px solid #ef4444;outline:none;border-radius:2px;font-size:${fs}px;font-family:Helvetica,Arial,sans-serif;color:#111;padding:1px 3px;cursor:text;`;
            inp.addEventListener("input", e => triggerSave(field.name, e.target.value));
            wrap.appendChild(inp); inp.focus();
          });
          wrap.appendChild(btn);
        } else if (showTextInp) {
          const inp = document.createElement("input"); inp.type = "text"; inp.value = val; inp.placeholder = "Type name…";
          inp.style.cssText = `width:100%;height:100%;box-sizing:border-box;background:rgba(255,255,255,0.85);border:1px solid rgba(230,0,122,0.4);outline:none;border-radius:2px;font-size:${fs}px;font-family:Helvetica,Arial,sans-serif;color:#111;padding:1px 3px;cursor:text;`;
          inp.addEventListener("input", e => triggerSave(field.name, e.target.value));
          wrap.appendChild(inp);
        }
      } else if (curEdit) {
        const inp = document.createElement("input"); inp.type = "text"; inp.value = val;
        inp.style.cssText = `width:100%;height:100%;box-sizing:border-box;background:rgba(255,255,255,0.95);border:none;outline:none;border-radius:2px;font-size:${fs}px;font-family:Helvetica,Arial,sans-serif;color:#111;padding:1px 3px;cursor:text;overflow:hidden;white-space:nowrap;`;
        inp.addEventListener("input", e => triggerSave(field.name, e.target.value));
        wrap.appendChild(inp);
      }
      overlay.appendChild(wrap);
    });
  };

  const triggerSave = (fn, v) => { fieldValuesRef.current = { ...fieldValuesRef.current, [fn]: v }; };

  const handleApplySignature = async () => {
    setShowSignPrompt(null); setApplyingSign(true); setApplySigStage("applying");
    try {
      const res = await fetch(`${API_BASE}/api/apply-signature/${sessionId}/${formId}`, { method: "POST", headers: { Authorization: `Bearer ${token}` } });
      if (res.ok) {
        setApplySigStage("rendering");
        const freshUrl = `${pdfUrlRef.current || pdfUrl}&_sig=${Date.now()}`;
        const newDoc   = await window.pdfjsLib.getDocument(freshUrl).promise;
        const page     = await newDoc.getPage(pageNum);
        const avail    = containerRef.current ? containerRef.current.clientWidth - 48 : 720;
        const scale    = Math.min(2.2, Math.max(1.0, avail / page.getViewport({ scale: 1 }).width));
        const vp       = page.getViewport({ scale });
        const off      = document.createElement("canvas"); off.width = vp.width; off.height = vp.height;
        const offCtx   = off.getContext("2d"); offCtx.fillStyle = "#fff"; offCtx.fillRect(0,0,off.width,off.height);
        await page.render({ canvasContext: offCtx, viewport: vp, renderInteractiveForms: false }).promise;
        const canvas = canvasRef.current;
        if (canvas) { canvas.width = off.width; canvas.height = off.height; canvas.getContext("2d").drawImage(off,0,0); }
        manuallyRenderedRef.current = { doc: newDoc, pageNum };
        setPdfDoc(newDoc); setTotalPages(newDoc.numPages);
        setIsSignedLocal(true); clearedSigFieldsRef.current = new Set();
        onSignApplied(formId);
        if (canvas) { const pd2 = pageDimsRef.current[pageNum - 1]; if (pd2) { const s2 = Math.min(2.2, Math.max(1.0, (containerRef.current ? containerRef.current.clientWidth - 48 : 720) / pd2.width)); buildOverlay(s2, canvas.width, canvas.height, fieldValuesRef.current); } }
      } else { const d = await res.json().catch(() => ({})); console.error("Sig apply failed:", d.detail); }
    } catch (e) { console.error("Sig apply failed:", e); }
    finally { setApplyingSign(false); setApplySigStage("idle"); }
  };

  const handleSignClick = () => setShowSignPrompt(savedSignature ? "use" : "none");

  const handleToggleEditMode = async () => {
    if (editMode) {
      const allValues = fieldValuesRef.current;
      const hasChanges = Object.keys(allValues).some(k => allValues[k] !== (originalFieldValuesRef.current[k] ?? "")) || clearedSigFieldsRef.current.size > 0;
      if (hasChanges) {
        setSaveStatus("saving");
        try {
          const clearedSigFields = Array.from(clearedSigFieldsRef.current);
          const res = await fetch(`${API_BASE}/api/update-pdf`, {
            method: "POST",
            headers: { "Content-Type": "application/json", Authorization: `Bearer ${token}` },
            body: JSON.stringify({ session_id: sessionId, field_updates: { ...allValues, __form_id__: formId, __signed__: isSignedLocal ? "1" : "0", __cleared_sig_fields__: JSON.stringify(clearedSigFields) } }),
          });
          if (res.ok) {
            setFieldValues({ ...allValues }); originalFieldValuesRef.current = { ...allValues }; clearedSigFieldsRef.current = new Set();
            const allSigF = fieldsRef.current.filter(f => _isSigField(f.name)).map(f => f.name);
            if (allSigF.length > 0 && allSigF.every(n => clearedSigFields.includes(n))) setIsSignedLocal(false);
            setSaveStatus("generating");
            _loadPdfInBackground(allValues);
          } else { setSaveStatus("error"); }
        } catch { setSaveStatus("error"); }
      }
    }
    setEditMode(m => !m);
  };

  const _loadPdfInBackground = (currentValues) => {
    if (!pdfjsReady) return;
    window.pdfjsLib.getDocument(`${pdfUrlRef.current || pdfUrl}&_r=${Date.now()}`).promise
      .then(async newDoc => {
        try {
          const page    = await newDoc.getPage(pageNum);
          const avail   = containerRef.current ? containerRef.current.clientWidth - 48 : 720;
          const scale   = Math.min(2.2, Math.max(1.0, avail / page.getViewport({ scale: 1 }).width));
          const vp      = page.getViewport({ scale });
          const off     = document.createElement("canvas"); off.width = vp.width; off.height = vp.height;
          await page.render({ canvasContext: off.getContext("2d"), viewport: vp, renderInteractiveForms: false }).promise;
          const vc = canvasRef.current;
          if (vc) { vc.width = off.width; vc.height = off.height; vc.getContext("2d").drawImage(off, 0, 0); }
          manuallyRenderedRef.current = { doc: newDoc, pageNum };
          setPdfDoc(newDoc); setTotalPages(newDoc.numPages);
          const pd = pageDimsRef.current[pageNum - 1];
          if (pd) { const s2 = Math.min(2.2, Math.max(1.0, (containerRef.current ? containerRef.current.clientWidth - 48 : 720) / pd.width)); buildOverlay(s2, off.width, off.height, currentValues); }
          setSaveStatus("saved"); setTimeout(() => setSaveStatus("idle"), 2000);
        } catch { setPdfDoc(newDoc); setTotalPages(newDoc.numPages); setSaveStatus("saved"); setTimeout(() => setSaveStatus("idle"), 2000); }
      })
      .catch(() => setSaveStatus("error"));
  };

  const goPage = n => { if (n >= 1 && n <= totalPages) setPageNum(n); };

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
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", padding: "8px 14px", background: "#1e2436", borderBottom: "1px solid #2a3047", flexShrink: 0, gap: 8, flexWrap: "wrap" }}>
        <div style={{ display: "flex", alignItems: "center", gap: 6, flexWrap: "wrap", minWidth: 0 }}>
          <span style={{ color: "#e8eaf2", fontSize: 13, fontWeight: 600, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap", maxWidth: 170 }}>📄 {formName}</span>
          {fieldsLoaded && (
            <>
              {highlightCounts.yellow > 0 && <span style={{ background: "rgba(245,158,11,0.15)", color: "#f59e0b", fontSize: 10, padding: "1px 7px", borderRadius: 10, border: "1px solid #f59e0b", fontWeight: 600 }}>🟡 {highlightCounts.yellow} required</span>}
              {highlightCounts.pink   > 0 && <span style={{ background: "rgba(230,0,122,0.12)",  color: "#e6007a", fontSize: 10, padding: "1px 7px", borderRadius: 10, border: "1px solid #e6007a", fontWeight: 600 }}>🩷 {highlightCounts.pink} review</span>}
              {highlightCounts.green  > 0 && <span style={{ background: "rgba(16,185,129,0.12)", color: "#10b981", fontSize: 10, padding: "1px 7px", borderRadius: 10, border: "1px solid #10b981", fontWeight: 600 }}>✅ {highlightCounts.green} client</span>}
            </>
          )}
        </div>

        <div style={{ display: "flex", alignItems: "center", gap: 5, flexWrap: "wrap" }}>
          {saveStatus === "saving" && <span style={{ display: "flex", alignItems: "center", gap: 3, color: "#f59e0b", fontSize: 11, fontWeight: 600 }}><span style={{ width: 10, height: 10, border: "2px solid #f59e0b", borderTopColor: "transparent", borderRadius: "50%", display: "inline-block", animation: "spin 0.7s linear infinite" }} />Saving…</span>}
          {saveStatus === "saved"   && <span style={{ color: "#22c55e", fontSize: 11, fontWeight: 600 }}>✓ Saved</span>}
          {saveStatus === "error"   && <span style={{ color: "#ef4444", fontSize: 11, fontWeight: 600 }}>⚠ Failed</span>}

          {/* Issue 2: Refresh button */}
          <button onClick={handleRefresh} disabled={refreshing}
            title="Refresh — picks up client-submitted answers and shows green highlights"
            style={{ display: "flex", alignItems: "center", gap: 3, padding: "4px 9px", borderRadius: 6, border: "1px solid #2a3047", background: "#252a3d", color: refreshing ? "#4f7cff" : "#8b93b0", fontSize: 11, fontWeight: 600, cursor: refreshing ? "wait" : "pointer", fontFamily: "inherit" }}>
            {refreshing
              ? <><span style={{ width: 10, height: 10, border: "2px solid #4f7cff", borderTopColor: "transparent", borderRadius: "50%", display: "inline-block", animation: "spin 0.7s linear infinite" }} />Refreshing…</>
              : "🔄 Refresh"}
          </button>

          <button onClick={handleToggleEditMode} disabled={saveStatus === "saving" || saveStatus === "generating"}
            style={{ display: "flex", alignItems: "center", gap: 4, padding: "4px 10px", borderRadius: 6, border: `1px solid ${editMode ? "#f59e0b" : "#2a3047"}`, background: editMode ? "rgba(245,158,11,0.15)" : "#252a3d", color: editMode ? "#f59e0b" : "#8b93b0", fontSize: 12, fontWeight: 600, cursor: (saveStatus === "saving" || saveStatus === "generating") ? "wait" : "pointer", fontFamily: "inherit", opacity: (saveStatus === "saving" || saveStatus === "generating") ? 0.7 : 1 }}>
            ✏️ {editMode ? "Done Editing" : "Edit Fields"}
          </button>

          <button onClick={handleSignClick} disabled={applyingSign}
            title={isSignedLocal ? "Signature applied — enter edit mode to remove" : savedSignature ? "Apply your saved signature" : "Set up a signature"}
            style={{ display: "flex", alignItems: "center", gap: 4, padding: "4px 10px", borderRadius: 6, border: `1px solid ${isSignedLocal ? "#10b981" : "rgba(230,0,122,0.4)"}`, background: isSignedLocal ? "rgba(16,185,129,0.1)" : "rgba(230,0,122,0.08)", color: isSignedLocal ? "#10b981" : "#e6007a", fontSize: 12, fontWeight: 600, cursor: applyingSign ? "wait" : "pointer", fontFamily: "inherit", opacity: applyingSign ? 0.7 : 1 }}>
            {applyingSign ? <><span style={{ width: 10, height: 10, border: "2px solid currentColor", borderTopColor: "transparent", borderRadius: "50%", display: "inline-block", animation: "spin 0.7s linear infinite" }} />Signing…</> : isSignedLocal ? "✓ Signed" : "✍ Sign"}
          </button>

          {rendering && <span style={{ color: "#4f7cff", fontSize: 11 }}>Rendering…</span>}

          <button onClick={() => goPage(pageNum - 1)} disabled={pageNum <= 1 || rendering} style={{ width: 28, height: 28, borderRadius: 6, border: "1px solid #2a3047", background: "#252a3d", color: "#e8eaf2", cursor: "pointer", fontSize: 16, display: "flex", alignItems: "center", justifyContent: "center" }}>‹</button>
          <span style={{ color: "#6b7899", fontSize: 12, minWidth: 44, textAlign: "center" }}>{totalPages ? `${pageNum}/${totalPages}` : "—"}</span>
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
        <div style={{ padding: "5px 14px", background: "rgba(245,158,11,0.06)", borderBottom: "1px solid rgba(245,158,11,0.15)", display: "flex", gap: 14, flexWrap: "wrap", alignItems: "center" }}>
          <span style={{ color: "#f59e0b", fontSize: 11 }}>✏️ Click any field to edit — "Done Editing" saves all changes</span>
          <span style={{ fontSize: 10, display: "flex", alignItems: "center", gap: 3 }}><span style={{ width: 11, height: 11, background: "rgba(245,158,11,0.3)", border: "2px solid #f59e0b", borderRadius: 2, display: "inline-block" }} /><span style={{ color: "#9aa4bf" }}>🟡 Signature required</span></span>
          <span style={{ fontSize: 10, display: "flex", alignItems: "center", gap: 3 }}><span style={{ width: 11, height: 11, background: "rgba(230,0,122,0.15)", border: "2px solid #e6007a", borderRadius: 2, display: "inline-block" }} /><span style={{ color: "#9aa4bf" }}>🩷 Low confidence</span></span>
          {highlightCounts.green > 0 && <span style={{ fontSize: 10, display: "flex", alignItems: "center", gap: 3 }}><span style={{ width: 11, height: 11, background: "rgba(16,185,129,0.18)", border: "2px solid #10b981", borderRadius: 2, display: "inline-block" }} /><span style={{ color: "#9aa4bf" }}>✅ Client-filled</span></span>}
        </div>
      )}

      {/* Issue 3: overflow:"auto" so pages are scrollable not jumbled */}
      <div ref={containerRef} style={{ flex: 1, overflow: "auto", display: "flex", justifyContent: "center", alignItems: "flex-start", padding: 24, background: "#252a3d", minHeight: 0 }}>
        {loadError ? (
          <div style={{ color: "#6b7899", textAlign: "center", marginTop: 60 }}>⚠️ Could not load PDF preview.</div>
        ) : !pdfDoc ? (
          <div style={{ color: "#6b7899", textAlign: "center", marginTop: 60 }}>
            <div className="loading-spinner" style={{ margin: "0 auto 12px" }} />Loading PDF…
          </div>
        ) : (
          <div style={{ position: "relative", display: "inline-block", lineHeight: 0, boxShadow: "0 8px 40px rgba(0,0,0,0.6)", borderRadius: 2 }}>
            <canvas ref={canvasRef} style={{ display: "block", maxWidth: "100%" }} />
            <div ref={overlayRef} style={{ position: "absolute", top: 0, left: 0, pointerEvents: editMode ? "all" : "none" }} />
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