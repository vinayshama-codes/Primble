import { useEffect, useRef, useState } from "react";

// The signature pad: draw it, or upload a PNG / JPG of it. One pad for the
// producer's saved signature (SignatureModal) and the applicant's signature on
// the client's signing page (SignPage, Orbin item 14) - the owner's ask: "same
// functionality needs to be replicated there and we can upload image as well".
//
// `onChange(dataUrl | null)` reports the signature as it stands: a PNG data URL
// after each stroke, the uploaded file's data URL, or null once cleared.
//
// The canvas keeps a fixed 440 x 140 drawing surface; pointer positions are
// scaled to it, so strokes land under the finger on a phone too (the page
// shows the canvas narrower than 440px there).

const CANVAS_W = 440;
const CANVAS_H = 140;
const TYPES = ["image/png", "image/jpeg", "image/jpg"];
const UPLOAD_MAX_SIDE = 1600;

export default function SignaturePad({ onChange, maxBytes = 2_000_000, uploadLabel = "Upload Image" }) {
  const canvasRef = useRef(null);
  const drawingRef = useRef(false);
  const drewRef = useRef(false);
  const [mode, setMode] = useState("draw");
  const [hasDrawn, setHasDrawn] = useState(false);
  const [uploadPreview, setUploadPreview] = useState(null);
  const [uploadError, setUploadError] = useState("");

  useEffect(() => {
    if (mode !== "draw") return;
    const canvas = canvasRef.current;
    if (!canvas) return;
    const ctx = canvas.getContext("2d");
    ctx.fillStyle = "#fff";
    ctx.fillRect(0, 0, canvas.width, canvas.height);
    ctx.strokeStyle = "#0f172a";
    ctx.lineWidth = 2.5;
    ctx.lineCap = "round";
    ctx.lineJoin = "round";
  }, [mode]);

  const getPos = (e, canvas) => {
    const r = canvas.getBoundingClientRect();
    const src = e.touches ? e.touches[0] : e;
    const sx = r.width ? canvas.width / r.width : 1;
    const sy = r.height ? canvas.height / r.height : 1;
    return { x: (src.clientX - r.left) * sx, y: (src.clientY - r.top) * sy };
  };

  const startDraw = (e) => {
    e.preventDefault();
    const canvas = canvasRef.current;
    if (!canvas) return;
    const ctx = canvas.getContext("2d");
    const pos = getPos(e, canvas);
    ctx.beginPath();
    ctx.moveTo(pos.x, pos.y);
    drawingRef.current = true;
  };

  const draw = (e) => {
    e.preventDefault();
    if (!drawingRef.current) return;
    const canvas = canvasRef.current;
    if (!canvas) return;
    const ctx = canvas.getContext("2d");
    const pos = getPos(e, canvas);
    ctx.lineTo(pos.x, pos.y);
    ctx.stroke();
    drewRef.current = true;
  };

  const stopDraw = () => {
    if (!drawingRef.current) return;
    drawingRef.current = false;
    if (drewRef.current && canvasRef.current) {
      setHasDrawn(true);
      onChange?.(canvasRef.current.toDataURL("image/png"));
    }
  };

  const clearCanvas = () => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const ctx = canvas.getContext("2d");
    ctx.fillStyle = "#fff";
    ctx.fillRect(0, 0, canvas.width, canvas.height);
    drewRef.current = false;
    setHasDrawn(false);
    onChange?.(null);
  };

  const handleUpload = (e) => {
    const file = e.target.files?.[0];
    setUploadError("");
    if (!file) return;
    if (!TYPES.includes((file.type || "").toLowerCase())) {
      setUploadPreview(null); onChange?.(null);
      setUploadError("Only PNG or JPG pictures can be used.");
      return;
    }
    if (file.size > maxBytes) {
      setUploadPreview(null); onChange?.(null);
      setUploadError(`That picture is too large. Use one under ${Math.floor(maxBytes / 1_000_000)} MB.`);
      return;
    }
    const reader = new FileReader();
    reader.onload = (ev) => {
      // A phone photo (4032 x 3024) is scaled down here to what is stored
      // anyway (1600 px wide), so the server's 4000 px cap is never hit at Sign.
      const img = new Image();
      img.onload = () => {
        const scale = Math.min(1, UPLOAD_MAX_SIDE / Math.max(img.naturalWidth, img.naturalHeight));
        let url = ev.target.result;
        if (scale < 1) {
          const c = document.createElement("canvas");
          c.width = Math.max(1, Math.round(img.naturalWidth * scale));
          c.height = Math.max(1, Math.round(img.naturalHeight * scale));
          const ctx = c.getContext("2d");
          ctx.fillStyle = "#fff"; ctx.fillRect(0, 0, c.width, c.height);
          ctx.drawImage(img, 0, 0, c.width, c.height);
          url = c.toDataURL("image/png");
        }
        setUploadPreview(url); onChange?.(url);
      };
      img.onerror = () => setUploadError("That picture could not be read.");
      img.src = ev.target.result;
    };
    reader.onerror = () => setUploadError("That picture could not be read.");
    reader.readAsDataURL(file);
  };

  const switchMode = (m) => {
    if (m === mode) return;
    setMode(m); setUploadPreview(null); setUploadError("");
    drewRef.current = false; setHasDrawn(false);
    onChange?.(null);
  };

  return (
    <div>
      <div style={{ display: "flex", gap: 8, marginBottom: 16 }}>
        {["draw", "upload"].map((m) => (
          <button
            key={m}
            type="button"
            onClick={() => switchMode(m)}
            style={{
              flex: 1, padding: "8px", borderRadius: 8, border: "1.5px solid",
              borderColor: mode === m ? "#E61B84" : "#e2e8f0",
              background: mode === m ? "rgba(230,0,122,0.06)" : "#fff",
              color: mode === m ? "#E61B84" : "#64748b",
              fontWeight: mode === m ? 700 : 500, fontSize: 13, cursor: "pointer",
            }}
          >
            {m === "draw" ? "Draw" : uploadLabel}
          </button>
        ))}
      </div>
      {mode === "draw" && (
        <div>
          <div style={{ fontSize: 12, color: "#64748b", marginBottom: 8 }}>Draw your signature below:</div>
          <canvas
            ref={canvasRef} width={CANVAS_W} height={CANVAS_H}
            onMouseDown={startDraw} onMouseMove={draw} onMouseUp={stopDraw} onMouseLeave={stopDraw}
            onTouchStart={startDraw} onTouchMove={draw} onTouchEnd={stopDraw}
            aria-label="Signature drawing area"
            style={{ width: "100%", height: "auto", aspectRatio: `${CANVAS_W} / ${CANVAS_H}`, maxWidth: CANVAS_W * 1.5, display: "block", border: "1.5px solid #e2e8f0", borderRadius: 8, cursor: "crosshair", touchAction: "none", background: "#fff", boxShadow: "inset 0 1px 4px rgba(0,0,0,0.06)" }}
          />
          <button type="button" onClick={clearCanvas} disabled={!hasDrawn}
            style={{ marginTop: 6, fontSize: 12, color: "#94a3b8", background: "none", border: "none", cursor: "pointer", textDecoration: "underline" }}>
            Clear
          </button>
        </div>
      )}
      {mode === "upload" && (
        <div>
          <div style={{ fontSize: 12, color: "#64748b", marginBottom: 8 }}>Upload a PNG or JPG of your signature:</div>
          <input type="file" accept="image/png,image/jpeg,image/jpg" onChange={handleUpload} style={{ fontSize: 13, marginBottom: 12, maxWidth: "100%" }} />
          {uploadError && <div style={{ fontSize: 12, color: "#dc2626", marginBottom: 8 }}>{uploadError}</div>}
          {uploadPreview && (
            <div style={{ background: "#f8fafc", borderRadius: 8, padding: 12, border: "1px solid #e2e8f0", textAlign: "center" }}>
              <img src={uploadPreview} alt="Preview" style={{ maxHeight: 80, maxWidth: "100%", objectFit: "contain" }} />
            </div>
          )}
        </div>
      )}
    </div>
  );
}
