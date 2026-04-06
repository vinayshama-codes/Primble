import { useState, useEffect, useRef } from "react";
import { API_BASE } from "../../config/constants";
import SaveStageOverlay from "../overlays/SaveStageOverlay";
import UseSignaturePrompt from "../signature/UseSignaturePrompt";
import NoSignaturePrompt from "../signature/NoSignaturePrompt";

const PDFJS_CDN    = "https://cdnjs.cloudflare.com/ajax/libs/pdf.js/3.11.174/pdf.min.js";
const PDFJS_WORKER = "https://cdnjs.cloudflare.com/ajax/libs/pdf.js/3.11.174/pdf.worker.min.js";

export default function PDFJsViewer({
  pdfUrl, formName, onFormNav, sessionId, formId, token,
  savedSignature, isSigned, onSignApplied, onOpenSignatureModal,
}) {
  const canvasRef              = useRef(null);
  const containerRef           = useRef(null);
  const renderTask             = useRef(null);
  const overlayRef             = useRef(null);
  const fieldValuesRef         = useRef({});
  const clearedSigFieldsRef    = useRef(new Set());
  const originalFieldValuesRef = useRef({});
  const pdfUrlRef              = useRef("");
  const fieldsRef              = useRef([]);
  const pageDimsRef            = useRef([]);
  const manuallyRenderedRef    = useRef({ doc: null, pageNum: -1 });
  const editModeRef            = useRef(false);

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
  const [showSignPrompt, setShowSignPrompt] = useState(null);
  const [applyingSign,   setApplyingSign]   = useState(false);
  const [applySigStage,  setApplySigStage]  = useState("idle");
  const [loadingStage,   setLoadingStage]   = useState("idle");

  useEffect(() => { editModeRef.current = editMode; }, [editMode]);
  useEffect(() => { setIsSignedLocal(isSigned); }, [formId]); // eslint-disable-line

  useEffect(() => {
    if (window.pdfjsLib) { setPdfjsReady(true); return; }
    const s    = document.createElement("script");
    s.src      = PDFJS_CDN;
    s.onload   = () => { window.pdfjsLib.GlobalWorkerOptions.workerSrc = PDFJS_WORKER; setPdfjsReady(true); };
    s.onerror  = () => setLoadError(true);
    document.head.appendChild(s);
  }, []);

  useEffect(() => {
    setPageNum(1); setEditMode(false); setFields([]); setFieldValues({});
    fieldValuesRef.current = {}; originalFieldValuesRef.current = {};
    fieldsRef.current = []; pageDimsRef.current = []; editModeRef.current = false;
    setPageDims([]); setFieldsLoaded(false); setSaveStatus("idle");
    setPdfDoc(null); setTotalPages(0); setLoadError(false);
    setShowSignPrompt(null); setApplyingSign(false);
    setApplySigStage("idle"); setLoadingStage("idle");
    clearedSigFieldsRef.current = new Set();
    manuallyRenderedRef.current = { doc: null, pageNum: -1 };
  }, [formId]);

  useEffect(() => {
    if (!pdfjsReady || !pdfUrl) return;
    pdfUrlRef.current = pdfUrl;
    setLoadError(false);
    setLoadingStage("loading");
    const url         = `${pdfUrl}&_r=${Date.now()}`;
    const loadingTask = window.pdfjsLib.getDocument(url);
    loadingTask.promise
      .then((doc) => { setPdfDoc(doc); setTotalPages(doc.numPages); })
      .catch((err) => {
        if (err?.name !== "UnexpectedResponseException" && err?.message !== "Worker was destroyed") {
          setLoadError(true); setLoadingStage("idle");
        }
      });
    return () => { try { loadingTask.destroy(); } catch (_) {} };
  }, [formId, pdfjsReady]); // eslint-disable-line

  useEffect(() => {
    if (!pdfDoc || !canvasRef.current) return;
    const mr = manuallyRenderedRef.current;
    if (mr.doc === pdfDoc && mr.pageNum === pageNum) { setLoadingStage("idle"); return; }
    const render = async () => {
      setRendering(true);
      setLoadingStage((s) => (s === "loading" ? "rendering" : s));
      if (renderTask.current) { try { renderTask.current.cancel(); } catch (_) {} }
      try {
        const page      = await pdfDoc.getPage(pageNum);
        const canvas    = canvasRef.current; if (!canvas) return;
        const container = containerRef.current;
        const avail     = container ? container.clientWidth - 48 : 720;
        const baseVP    = page.getViewport({ scale: 1 });
        const scale     = Math.min(2.2, Math.max(1.0, avail / baseVP.width));
        const vp        = page.getViewport({ scale });
        canvas.width    = vp.width; canvas.height = vp.height;
        const ctx       = canvas.getContext("2d");
        ctx.fillStyle   = "#fff"; ctx.fillRect(0, 0, canvas.width, canvas.height);
        const task      = page.render({ canvasContext: ctx, viewport: vp, renderInteractiveForms: false });
        renderTask.current = task;
        await task.promise;
        buildOverlay(scale, vp.width, vp.height, fieldValuesRef.current);
      } catch (e) {
        if (e?.name !== "RenderingCancelledException") setLoadError(true);
      } finally { setRendering(false); setLoadingStage("idle"); }
    };
    render();
  }, [pdfDoc, pageNum]); // eslint-disable-line

  useEffect(() => {
    if (!canvasRef.current || !overlayRef.current || !fieldsLoaded) return;
    const canvas = canvasRef.current;
    const pd     = pageDimsRef.current[pageNum - 1];
    if (!pd || canvas.width === 0) return;
    const avail = containerRef.current ? containerRef.current.clientWidth - 48 : 720;
    const scale = Math.min(2.2, Math.max(1.0, avail / pd.width));
    buildOverlay(scale, canvas.width, canvas.height, fieldValuesRef.current);
  }, [pageNum, editMode, isSignedLocal, fields, fieldsLoaded, pageDims]);

  useEffect(() => {
    if (!sessionId || !formId || !token || fieldsLoaded) return;
    const controller = new AbortController();
    fetch(`${API_BASE}/api/fields/${sessionId}/${formId}?token=${token}`, { signal: controller.signal })
      .then((r) => (r.ok ? r.json() : null))
      .then((data) => {
        if (!data?.success) return;
        const vals = {};
        (data.fields || []).forEach((f) => { vals[f.name] = f.value || ""; });
        fieldsRef.current   = data.fields    || [];
        pageDimsRef.current = data.page_dims || [];
        setFields(data.fields || []);
        setPageDims(data.page_dims || []);
        setFieldValues(vals);
        fieldValuesRef.current         = vals;
        originalFieldValuesRef.current = { ...vals };
        setFieldsLoaded(true);
      })
      .catch((err) => { if (err?.name !== "AbortError") console.error("Fields fetch error:", err); });
    return () => controller.abort();
  }, [sessionId, formId, token]); // eslint-disable-line

  const _isSigField = (name) => {
    const fn         = (name || "").toLowerCase().replace(/[\s\-.]/g, "_");
    const exclusions = ["date","designation","title","printed","print_name","name_of","countersign"];
    if (exclusions.some((ex) => fn.includes(ex))) return false;
    const patterns = ["signature","producer_sig","insured_sig","authorized_sig","applicant_sig","agent_sig","signedby","signed_by","sign_here","producersig","agentsig","sig_producer","sig_insured","sig_agent"];
    return patterns.some((p) => fn.includes(p));
  };

  const buildOverlay = (scale, canvasW, canvasH, liveValues) => {
    const overlay = overlayRef.current;
    if (!overlay) return;
    overlay.innerHTML    = "";
    overlay.style.width  = canvasW + "px";
    overlay.style.height = canvasH + "px";
    const pd              = pageDimsRef.current[pageNum - 1];
    const pageHeight      = pd ? pd.height : canvasH / scale;
    const pageFields      = fieldsRef.current.filter((f) => f.page === pageNum - 1);
    const currentEditMode = editModeRef.current;

    pageFields.forEach((field) => {
      const { x, y, width, height } = field.rect;
      const cx  = x * scale;
      const cy  = (pageHeight - y - height) * scale;
      const cw  = Math.max(width  * scale, 18);
      const ch  = Math.max(height * scale, 14);
      const fs  = Math.max(7, Math.min(ch * 0.58, 12));
      const val = liveValues[field.name] ?? field.value ?? "";
      const isSigF = _isSigField(field.name);

      const wrap = document.createElement("div");
      wrap.style.cssText = `position:absolute;left:${cx}px;top:${cy}px;width:${cw}px;height:${ch}px;pointer-events:${currentEditMode ? "all" : "none"};`;

      if (field.type === "checkbox") {
        const cb       = document.createElement("input");
        cb.type        = "checkbox";
        cb.checked     = val === "Yes" || val === "true" || val === "1" || val === "On";
        cb.disabled    = !currentEditMode;
        cb.style.cssText = `position:absolute;top:50%;left:50%;transform:translate(-50%,-50%);width:${Math.min(ch*0.7,13)}px;height:${Math.min(ch*0.7,13)}px;margin:0;cursor:${currentEditMode?"pointer":"default"};accent-color:#4f7cff;opacity:${currentEditMode?1:0.7};`;
        cb.addEventListener("change", (e) => triggerSave(field.name, e.target.checked ? "Yes" : "Off"));
        wrap.appendChild(cb);
      } else if (isSigF) {
        const thisFieldCleared = clearedSigFieldsRef.current.has(field.name);
        const showClearBtn     = currentEditMode && isSignedLocal && !thisFieldCleared;
        const showTextInput    = currentEditMode && (!isSignedLocal || thisFieldCleared);
        if (showClearBtn) {
          const btn          = document.createElement("button");
          btn.title          = "Remove stamped signature";
          btn.textContent    = "✕";
          btn.style.cssText  = `position:absolute;top:2px;right:2px;width:16px;height:16px;background:rgba(239,68,68,0.12);border:1px solid rgba(239,68,68,0.4);border-radius:50%;color:#ef4444;font-size:9px;font-weight:700;cursor:pointer;display:flex;align-items:center;justify-content:center;padding:0;line-height:1;font-family:inherit;`;
          btn.addEventListener("click", () => {
            triggerSave(field.name, "");
            clearedSigFieldsRef.current.add(field.name);
            wrap.innerHTML = "";
            const inp       = document.createElement("input");
            inp.type        = "text"; inp.value = ""; inp.placeholder = "Type name...";
            inp.style.cssText = `width:100%;height:100%;box-sizing:border-box;background:rgba(255,255,255,0.95);border:1px solid #ef4444;outline:none;border-radius:2px;font-size:${fs}px;font-family:Helvetica,Arial,sans-serif;color:#111;padding:1px 3px;cursor:text;`;
            inp.addEventListener("input", (e) => triggerSave(field.name, e.target.value));
            wrap.appendChild(inp); inp.focus();
          });
          wrap.appendChild(btn);
        } else if (showTextInput) {
          const inp       = document.createElement("input");
          inp.type        = "text"; inp.value = val; inp.placeholder = "Type name...";
          inp.style.cssText = `width:100%;height:100%;box-sizing:border-box;background:rgba(255,255,255,0.85);border:1px solid rgba(230,0,122,0.4);outline:none;border-radius:2px;font-size:${fs}px;font-family:Helvetica,Arial,sans-serif;color:#111;padding:1px 3px;cursor:text;`;
          inp.addEventListener("input", (e) => triggerSave(field.name, e.target.value));
          wrap.appendChild(inp);
        }
      } else if (currentEditMode) {
        const inp       = document.createElement("input");
        inp.type        = "text"; inp.value = val; inp.placeholder = "";
        inp.style.cssText = `width:100%;height:100%;box-sizing:border-box;background:rgba(255,255,255,0.95);border:none;outline:none;border-radius:2px;font-size:${fs}px;font-family:Helvetica,Arial,sans-serif;color:#111;padding:1px 3px;cursor:text;overflow:hidden;white-space:nowrap;`;
        inp.addEventListener("input", (e) => triggerSave(field.name, e.target.value));
        wrap.appendChild(inp);
      }
      overlay.appendChild(wrap);
    });
  };

  const triggerSave = (fieldName, newVal) => {
    fieldValuesRef.current = { ...fieldValuesRef.current, [fieldName]: newVal };
  };

  const handleApplySignature = async () => {
    setShowSignPrompt(null);
    setApplyingSign(true);
    setApplySigStage("applying");
    try {
      const res = await fetch(`${API_BASE}/api/apply-signature/${sessionId}/${formId}`, {
        method: "POST",
        headers: { Authorization: `Bearer ${token}` },
      });
      if (res.ok) {
        setApplySigStage("rendering");
        const freshUrl  = `${pdfUrlRef.current || pdfUrl}&_sig=${Date.now()}`;
        const newDoc    = await window.pdfjsLib.getDocument(freshUrl).promise;
        const page      = await newDoc.getPage(pageNum);
        const container = containerRef.current;
        const avail     = container ? container.clientWidth - 48 : 720;
        const baseVP    = page.getViewport({ scale: 1 });
        const scale     = Math.min(2.2, Math.max(1.0, avail / baseVP.width));
        const vp        = page.getViewport({ scale });
        const offscreen = document.createElement("canvas");
        offscreen.width = vp.width; offscreen.height = vp.height;
        const offCtx    = offscreen.getContext("2d");
        offCtx.fillStyle = "#fff"; offCtx.fillRect(0, 0, offscreen.width, offscreen.height);
        await page.render({ canvasContext: offCtx, viewport: vp, renderInteractiveForms: false }).promise;
        const canvas = canvasRef.current;
        if (canvas) {
          canvas.width  = offscreen.width; canvas.height = offscreen.height;
          canvas.getContext("2d").drawImage(offscreen, 0, 0);
        }
        manuallyRenderedRef.current = { doc: newDoc, pageNum };
        setPdfDoc(newDoc); setTotalPages(newDoc.numPages);
        setIsSignedLocal(true); clearedSigFieldsRef.current = new Set();
        onSignApplied(formId);
        if (canvas) {
          const pd2 = pageDimsRef.current[pageNum - 1];
          if (pd2) {
            const avail2 = container ? container.clientWidth - 48 : 720;
            const scale2 = Math.min(2.2, Math.max(1.0, avail2 / pd2.width));
            buildOverlay(scale2, canvas.width, canvas.height, fieldValuesRef.current);
          }
        }
      } else {
        const data = await res.json().catch(() => ({}));
        console.error("Signature apply failed:", data.detail || "Unknown error");
      }
    } catch (e) { console.error("Signature apply failed:", e); }
    finally { setApplyingSign(false); setApplySigStage("idle"); }
  };

  const handleSignClick = () => { setShowSignPrompt(savedSignature ? "use" : "none"); };

  const handleToggleEditMode = async () => {
    if (editMode) {
      if (window._saveTimer) clearTimeout(window._saveTimer);
      const allValues        = fieldValuesRef.current;
      const hasActualChanges =
        Object.keys(allValues).some((k) => allValues[k] !== (originalFieldValuesRef.current[k] ?? ""))
        || clearedSigFieldsRef.current.size > 0;
      if (hasActualChanges) {
        setSaveStatus("saving");
        try {
          const clearedSigFields = Array.from(clearedSigFieldsRef.current);
          const updates = {
            ...allValues,
            __form_id__:             formId,
            __signed__:              isSignedLocal ? "1" : "0",
            __cleared_sig_fields__:  JSON.stringify(clearedSigFields),
          };
          const res = await fetch(`${API_BASE}/api/update-pdf`, {
            method: "POST",
            headers: { "Content-Type": "application/json", Authorization: `Bearer ${token}` },
            body: JSON.stringify({ session_id: sessionId, field_updates: updates }),
          });
          if (res.ok) {
            setFieldValues({ ...allValues });
            originalFieldValuesRef.current = { ...allValues };
            clearedSigFieldsRef.current    = new Set();
            const allSigFields = fieldsRef.current.filter((f) => _isSigField(f.name)).map((f) => f.name);
            const allCleared   = allSigFields.length > 0 && allSigFields.every((n) => clearedSigFields.includes(n));
            if (allCleared) setIsSignedLocal(false);
            setSaveStatus("generating");
            _loadPdfInBackground(allValues);
          } else { setSaveStatus("error"); }
        } catch { setSaveStatus("error"); }
      }
    }
    setEditMode((m) => !m);
  };

  const _loadPdfInBackground = (currentValues) => {
    if (!pdfjsReady) return;
    const url = `${pdfUrlRef.current || pdfUrl}&_r=${Date.now()}`;
    window.pdfjsLib.getDocument(url).promise
      .then(async (newDoc) => {
        try {
          const page      = await newDoc.getPage(pageNum);
          const offscreen = document.createElement("canvas");
          const container = containerRef.current;
          const avail     = container ? container.clientWidth - 48 : 720;
          const baseVP    = page.getViewport({ scale: 1 });
          const scale     = Math.min(2.2, Math.max(1.0, avail / baseVP.width));
          const vp        = page.getViewport({ scale });
          offscreen.width = vp.width; offscreen.height = vp.height;
          const ctx = offscreen.getContext("2d");
          await page.render({ canvasContext: ctx, viewport: vp, renderInteractiveForms: false }).promise;
          const visibleCanvas = canvasRef.current;
          if (visibleCanvas) {
            visibleCanvas.width  = offscreen.width; visibleCanvas.height = offscreen.height;
            visibleCanvas.getContext("2d").drawImage(offscreen, 0, 0);
          }
          manuallyRenderedRef.current = { doc: newDoc, pageNum };
          setPdfDoc(newDoc); setTotalPages(newDoc.numPages);
          const pd = pageDimsRef.current[pageNum - 1];
          if (pd) {
            const scale2 = Math.min(2.2, Math.max(1.0, (container ? container.clientWidth - 48 : 720) / pd.width));
            buildOverlay(scale2, offscreen.width, offscreen.height, currentValues);
          }
          setSaveStatus("saved"); setTimeout(() => setSaveStatus("idle"), 2000);
        } catch (ex) {
          console.warn("Background render failed:", ex);
          setPdfDoc(newDoc); setTotalPages(newDoc.numPages);
          setSaveStatus("saved"); setTimeout(() => setSaveStatus("idle"), 2000);
        }
      })
      .catch(() => { setSaveStatus("error"); });
  };

  const goPage        = (n) => { if (n >= 1 && n <= totalPages) setPageNum(n); };
  const showSavedPill = saveStatus === "saved";
  const showErrorPill = saveStatus === "error";

  return (
    <div style={{ display: "flex", flexDirection: "column", height: "100%", background: "#181c27", borderRadius: 8, overflow: "hidden" }}>
      {(saveStatus === "saving" || saveStatus === "generating") && <SaveStageOverlay stage={saveStatus} />}

      {applySigStage !== "idle" && (
        <div className="upgrade-stage-overlay">
          <div className="upgrade-stage-spinner" />
          <div className="upgrade-stage-steps">
            <div className={`upgrade-stage-step ${applySigStage === "applying" ? "active" : "done"}`}>
              <div className="upgrade-stage-dot" />
              {applySigStage === "applying" ? "Applying signature…" : "✓ Applying signature"}
            </div>
            <div className={`upgrade-stage-step ${applySigStage === "rendering" ? "active" : ""}`}>
              <div className="upgrade-stage-dot" />
              Generating signed form…
            </div>
          </div>
        </div>
      )}

      {loadingStage !== "idle" && (
        <div className="upgrade-stage-overlay">
          <div className="upgrade-stage-spinner" />
          <div className="upgrade-stage-steps">
            <div className={`upgrade-stage-step ${loadingStage === "loading" ? "active" : "done"}`}>
              <div className="upgrade-stage-dot" />
              {loadingStage === "loading" ? "Loading form…" : "✓ Loading form"}
            </div>
            <div className={`upgrade-stage-step ${loadingStage === "rendering" ? "active" : ""}`}>
              <div className="upgrade-stage-dot" />
              Rendering preview…
            </div>
          </div>
        </div>
      )}

      {showSignPrompt === "use" && (
        <UseSignaturePrompt
          signature={savedSignature}
          onApply={handleApplySignature}
          onManage={() => { setShowSignPrompt(null); onOpenSignatureModal(); }}
          onClose={() => setShowSignPrompt(null)}
        />
      )}
      {showSignPrompt === "none" && (
        <NoSignaturePrompt
          onSetup={() => { setShowSignPrompt(null); onOpenSignatureModal(); }}
          onClose={() => setShowSignPrompt(null)}
        />
      )}

      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", padding: "8px 14px", background: "#1e2436", borderBottom: "1px solid #2a3047", flexShrink: 0, gap: 8, flexWrap: "wrap" }}>
        <span style={{ color: "#e8eaf2", fontSize: 13, fontWeight: 600, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap", maxWidth: "40%" }}>
          📄 {formName}
        </span>
        <div style={{ display: "flex", alignItems: "center", gap: 6, flexWrap: "wrap" }}>
          {showSavedPill && <span style={{ fontSize: 11, fontWeight: 700, color: "#22c55e" }}>✓ Saved</span>}
          {showErrorPill && <span style={{ fontSize: 11, fontWeight: 700, color: "#ef4444" }}>⚠ Save failed</span>}
          <button
            onClick={handleToggleEditMode}
            disabled={saveStatus === "saving" || saveStatus === "generating"}
            style={{ display: "flex", alignItems: "center", gap: 4, padding: "4px 10px", borderRadius: 6, border: `1px solid ${editMode ? "#4f7cff" : "#2a3047"}`, background: editMode ? "rgba(79,124,255,0.15)" : "#252a3d", color: editMode ? "#4f7cff" : "#8b93b0", fontSize: 12, fontWeight: 600, cursor: (saveStatus === "saving" || saveStatus === "generating") ? "wait" : "pointer", fontFamily: "inherit", opacity: (saveStatus === "saving" || saveStatus === "generating") ? 0.7 : 1 }}
          >
            ✏️ {editMode ? "Done Editing" : "Edit"}
          </button>
          <button
            onClick={handleSignClick}
            disabled={applyingSign}
            title={isSignedLocal ? "Signature applied" : savedSignature ? "Apply your saved signature" : "Set up a signature"}
            style={{ display: "flex", alignItems: "center", gap: 4, padding: "4px 10px", borderRadius: 6, border: `1px solid ${isSignedLocal ? "#10b981" : "rgba(230,0,122,0.4)"}`, background: isSignedLocal ? "rgba(16,185,129,0.1)" : "rgba(230,0,122,0.08)", color: isSignedLocal ? "#10b981" : "#e6007a", fontSize: 12, fontWeight: 600, cursor: applyingSign ? "wait" : "pointer", fontFamily: "inherit", transition: "all 0.2s", opacity: applyingSign ? 0.7 : 1 }}
          >
            {applyingSign
              ? <><span style={{ width: 10, height: 10, border: "2px solid currentColor", borderTopColor: "transparent", borderRadius: "50%", display: "inline-block", animation: "spin 0.7s linear infinite" }} /> Signing…</>
              : isSignedLocal ? "✓ Signed" : "✍ Sign"}
          </button>
          {rendering && <span style={{ color: "#4f7cff", fontSize: 11 }}>Rendering…</span>}
          <div style={{ display: "flex", alignItems: "center", gap: 4 }}>
            <button onClick={() => goPage(pageNum - 1)} disabled={pageNum <= 1 || rendering} style={{ width: 28, height: 28, borderRadius: 6, border: "1px solid #2a3047", background: "#252a3d", color: "#e8eaf2", cursor: "pointer", fontSize: 16, display: "flex", alignItems: "center", justifyContent: "center" }}>‹</button>
            <span style={{ color: "#e8eaf2", fontSize: 12, fontWeight: 700, minWidth: 56, textAlign: "center", background: "#2a3047", padding: "3px 8px", borderRadius: 5 }}>
              {totalPages ? `Page ${pageNum} / ${totalPages}` : "—"}
            </span>
            <button onClick={() => goPage(pageNum + 1)} disabled={pageNum >= totalPages || rendering} style={{ width: 28, height: 28, borderRadius: 6, border: "1px solid #2a3047", background: "#252a3d", color: "#e8eaf2", cursor: "pointer", fontSize: 16, display: "flex", alignItems: "center", justifyContent: "center" }}>›</button>
          </div>
          {onFormNav?.total > 1 && (
            <>
              <div style={{ width: 1, height: 18, background: "#2a3047", margin: "0 2px" }} />
              <button onClick={onFormNav.goPrev} disabled={onFormNav.activeIdx <= 0} style={{ width: 28, height: 28, borderRadius: 6, border: "1px solid #2a3047", background: "#252a3d", color: "#e8eaf2", cursor: "pointer", fontSize: 13, display: "flex", alignItems: "center", justifyContent: "center" }}>«</button>
              <span style={{ color: "#4f7cff", fontSize: 11, fontWeight: 600 }}>Form {onFormNav.activeIdx + 1}/{onFormNav.total}</span>
              <button onClick={onFormNav.goNext} disabled={onFormNav.activeIdx >= onFormNav.total - 1} style={{ width: 28, height: 28, borderRadius: 6, border: "1px solid #2a3047", background: "#252a3d", color: "#e8eaf2", cursor: "pointer", fontSize: 13, display: "flex", alignItems: "center", justifyContent: "center" }}>»</button>
            </>
          )}
        </div>
      </div>

      {editMode && (
        <div style={{ padding: "3px 14px", background: "rgba(79,124,255,0.08)", borderBottom: "1px solid rgba(79,124,255,0.15)", color: "#4f7cff", fontSize: 11 }}>
          ✏️ Click any field to edit — click Done Editing to save
        </div>
      )}

      <div ref={containerRef} style={{ flex: 1, overflow: "hidden", display: "flex", justifyContent: "center", alignItems: "flex-start", padding: 24, background: "#252a3d", minHeight: 0 }}>
        {loadError ? (
          <div style={{ color: "#6b7899", textAlign: "center", marginTop: 60 }}>⚠️ Could not load PDF preview.</div>
        ) : !pdfDoc ? (
          <div style={{ color: "#6b7899", textAlign: "center", marginTop: 60 }}>
            <div className="loading-spinner" style={{ margin: "0 auto 12px" }} />Loading…
          </div>
        ) : (
          <div style={{ position: "relative", display: "inline-block", lineHeight: 0, boxShadow: "0 8px 40px rgba(0,0,0,0.6)", borderRadius: 2 }}>
            <canvas ref={canvasRef} style={{ display: "block", maxWidth: "100%" }} />
            <div ref={overlayRef} style={{ position: "absolute", top: 0, left: 0, pointerEvents: editMode ? "all" : "none" }} />
          </div>
        )}
      </div>
    </div>
  );
}