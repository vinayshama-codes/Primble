import React, { useState, useEffect, useRef } from 'react';
import './App.css';
import { GoogleOAuthProvider, GoogleLogin } from '@react-oauth/google';

const _style = document.createElement('style');
_style.textContent = `
  .global-loading-overlay {
    position: fixed; inset: 0; background: rgba(255,255,255,0.95);
    display: flex; flex-direction: column; align-items: center;
    justify-content: center; z-index: 9999;
  }
  .payment-failed-badge {
    display: flex; align-items: center; gap: 6px;
    background: #fef2f2; color: #991b1b; font-size: 13px;
    font-weight: 600; padding: 4px 10px; border-radius: 6px;
    border: 1px solid #fca5a5;
  }
  .upgrade-modal-wide { max-width: 860px !important; width: 92vw !important; }
  @keyframes spin { to { transform: rotate(360deg); } }
  .payment-status-banner { padding:10px 16px; border-radius:8px; font-size:13px; font-weight:500; margin-bottom:10px; }
  .payment-status-banner a { color:inherit; font-weight:700; text-decoration:underline; }
  .payment-status-failed   { background:#fef3c7; color:#92400e; border:1px solid #fcd34d; }
  .payment-status-locked   { background:#fef9c3; color:#713f12; border:1px solid #fde047; }
  .payment-status-suspended{ background:#fee2e2; color:#7f1d1d; border:1px solid #fca5a5; }
  .payment-status-archived { background:#f1f5f9; color:#334155; border:1px solid #cbd5e1; }
  .upload-area-blocked { opacity:0.45; pointer-events:none; filter:grayscale(60%); }
  .upload-blocked-msg { background:#fee2e2; color:#7f1d1d; border:1px solid #fca5a5; border-radius:8px; padding:12px 16px; font-size:13px; font-weight:500; margin-bottom:12px; text-align:center; }
  .upload-blocked-msg a { color:#7f1d1d; font-weight:700; }
  .billing-toggle {
    display: flex; gap: 4px; background: #f1f5f9; border-radius: 8px;
    padding: 4px; margin: 12px auto 20px; width: fit-content;
  }
  .billing-option {
    padding: 6px 18px; border-radius: 6px; border: none; cursor: pointer;
    font-size: 14px; font-weight: 500; color: #64748b; background: transparent;
    transition: all 0.2s;
  }
  .billing-option.billing-active {
    background: #fff; color: #1e293b; font-weight: 600;
    box-shadow: 0 1px 4px rgba(0,0,0,0.12);
  }
  .billing-save {
    font-size: 11px; color: #16a34a; font-weight: 700;
    background: #dcfce7; padding: 1px 5px; border-radius: 4px; margin-left: 4px;
  }
  .plan-cards {
    display: flex; gap: 16px; align-items: stretch; margin: 0 0 16px;
    flex-wrap: wrap; justify-content: center;
  }
  .plan-card {
    flex: 1; min-width: 200px; max-width: 240px; border: 1.5px solid #e2e8f0;
    border-radius: 12px; padding: 20px 16px; position: relative;
    display: flex; flex-direction: column; gap: 6px; background: #fff;
  }
  .plan-card-highlight {
    border-color: #2563eb; box-shadow: 0 0 0 2px #dbeafe;
  }
  .plan-popular {
    position: absolute; top: -12px; left: 50%; transform: translateX(-50%);
    background: #2563eb; color: #fff; font-size: 11px; font-weight: 700;
    padding: 2px 12px; border-radius: 20px; white-space: nowrap;
  }
  .plan-name { font-size: 16px; font-weight: 700; color: #1e293b; }
  .plan-price { display: flex; align-items: baseline; gap: 2px; margin-top: 4px; }
  .plan-price-amount { font-size: 32px; font-weight: 800; color: #1e293b; }
  .plan-price-period { font-size: 14px; color: #64748b; }
  .plan-price-custom { font-size: 24px; font-weight: 700; color: #1e293b; }
  .plan-billed-note { font-size: 11px; color: #64748b; margin-top: -2px; }
  .plan-price-sub { font-size: 11px; color: #94a3b8; margin-top: 2px; }
  .plan-packages { font-size: 13px; font-weight: 600; color: #2563eb; margin-top: 4px; }
  .plan-overage { font-size: 11px; color: #94a3b8; }
  .plan-features { list-style: none; padding: 0; margin: 10px 0; flex: 1; }
  .plan-features li { font-size: 12px; color: #475569; padding: 2px 0; }
  .upgrade-footer-note { font-size: 11px; color: #94a3b8; text-align: center; }

  /* Staged upgrade overlay */
  .upgrade-stage-overlay {
    position: fixed; inset: 0; background: rgba(255,255,255,0.97);
    display: flex; flex-direction: column; align-items: center;
    justify-content: center; z-index: 99999; gap: 24px;
  }
  .upgrade-stage-spinner {
    width: 56px; height: 56px;
    border: 4px solid #e2e8f0;
    border-top-color: #2563eb;
    border-radius: 50%;
    animation: spin 0.9s linear infinite;
  }
  .upgrade-stage-steps {
    display: flex; flex-direction: column; gap: 10px; align-items: center;
  }
  .upgrade-stage-step {
    font-size: 14px; font-weight: 500; color: #94a3b8;
    display: flex; align-items: center; gap: 8px; transition: all 0.4s;
  }
  .upgrade-stage-step.active { color: #1e293b; font-weight: 700; font-size: 16px; }
  .upgrade-stage-step.done { color: #10b981; }
  .upgrade-stage-dot {
    width: 8px; height: 8px; border-radius: 50%; background: #e2e8f0; flex-shrink: 0;
  }
  .upgrade-stage-step.active .upgrade-stage-dot { background: #2563eb; }
  .upgrade-stage-step.done .upgrade-stage-dot { background: #10b981; }

  /* Overage inline notice */
  .overage-inline-notice {
    background: #fefce8; border: 1px solid #fde047; border-radius: 8px;
    padding: 10px 14px; font-size: 12px; color: #713f12; margin-bottom: 10px;
    display: flex; align-items: center; gap: 8px;
  }
`;
if (!document.head.querySelector('#acordly-v12-styles')) {
  _style.id = 'acordly-v12-styles';
  document.head.appendChild(_style);
}

const GOOGLE_CLIENT_ID = "28797353517-dsovdm42dgsu776ug8ad2397amdlus9k.apps.googleusercontent.com";
const API_BASE = 'http://localhost:8000';
const STRIPE_PORTAL = 'https://billing.stripe.com/p/login/';

async function startStripeCheckout(token, onError) {
  try {
    const res  = await fetch(`${API_BASE}/api/stripe/create-checkout`, {
      method: 'POST', headers: { 'Authorization': `Bearer ${token}` }
    });
    const data = await res.json();
    if (data.checkout_url) {
      window.location.href = data.checkout_url;
    } else {
      onError('Failed to start checkout. Please try again.');
    }
  } catch {
    onError('Network error. Please try again.');
  }
}

function App() {
  return (
    <GoogleOAuthProvider clientId={GOOGLE_CLIENT_ID}>
      <AppContent />
    </GoogleOAuthProvider>
  );
}

// ─── OVERLAY COMPONENTS ──────────────────────────────────────────

function UpgradeStageOverlay() {
  const stages = ['Updating Billing', 'Activating Plan', 'Finalizing Account'];
  const [activeIdx, setActiveIdx] = useState(0);

  useEffect(() => {
    const timers = [
      setTimeout(() => setActiveIdx(1), 2000),
      setTimeout(() => setActiveIdx(2), 4500),
    ];
    return () => timers.forEach(clearTimeout);
  }, []);

  return (
    <div className="upgrade-stage-overlay">
      <div className="upgrade-stage-spinner" />
      <div className="upgrade-stage-steps">
        {stages.map((stage, i) => (
          <div
            key={stage}
            className={`upgrade-stage-step ${i === activeIdx ? 'active' : i < activeIdx ? 'done' : ''}`}
          >
            <div className="upgrade-stage-dot" />
            {i < activeIdx ? `✓ ${stage}` : stage}
          </div>
        ))}
      </div>
    </div>
  );
}

function SaveStageOverlay({ stage }) {
  const stages = ['Saving edits', 'Generating form'];
  const activeIdx = stage === 'saving' ? 0 : 1;
  return (
    <div className="upgrade-stage-overlay">
      <div className="upgrade-stage-spinner" />
      <div className="upgrade-stage-steps">
        {stages.map((s, i) => (
          <div key={s} className={`upgrade-stage-step ${i === activeIdx ? 'active' : i < activeIdx ? 'done' : ''}`}>
            <div className="upgrade-stage-dot" />
            {i < activeIdx ? `✓ ${s}` : s}
          </div>
        ))}
      </div>
    </div>
  );
}

// Generic auto-advancing 2-step overlay used for upload / generate / download
function ProcessStageOverlay({ stages, advanceAfter = 3000 }) {
  const [activeIdx, setActiveIdx] = useState(0);

  useEffect(() => {
    if (activeIdx >= stages.length - 1) return;
    const t = setTimeout(() => setActiveIdx(i => Math.min(i + 1, stages.length - 1)), advanceAfter);
    return () => clearTimeout(t);
  }, [activeIdx, stages.length, advanceAfter]);

  return (
    <div className="upgrade-stage-overlay">
      <div className="upgrade-stage-spinner" />
      <div className="upgrade-stage-steps">
        {stages.map((s, i) => (
          <div key={s} className={`upgrade-stage-step ${i === activeIdx ? 'active' : i < activeIdx ? 'done' : ''}`}>
            <div className="upgrade-stage-dot" />
            {i < activeIdx ? `✓ ${s}` : s}
          </div>
        ))}
      </div>
    </div>
  );
}

// ─── SIGNATURE MODAL ─────────────────────────────────────────────

function SignatureModal({ token, onClose, onSaved, existingSignature }) {
  const canvasRef   = useRef(null);
  const [mode, setMode]                   = useState('draw');
  const [drawing, setDrawing]             = useState(false);
  const [hasDrawn, setHasDrawn]           = useState(false);
  const [uploadPreview, setUploadPreview] = useState(null);
  const [saving, setSaving]               = useState(false);
  const [error, setError]                 = useState('');
  const [clearingSignature, setClearingSignature] = useState(false);

  useEffect(() => {
    if (mode !== 'draw') return;
    const canvas = canvasRef.current; if (!canvas) return;
    const ctx = canvas.getContext('2d');
    ctx.fillStyle = '#fff'; ctx.fillRect(0, 0, canvas.width, canvas.height);
    ctx.strokeStyle = '#0f172a'; ctx.lineWidth = 2.5;
    ctx.lineCap = 'round'; ctx.lineJoin = 'round';
  }, [mode]);

  const getPos = (e, canvas) => {
    const r = canvas.getBoundingClientRect();
    const src = e.touches ? e.touches[0] : e;
    return { x: src.clientX - r.left, y: src.clientY - r.top };
  };

  const startDraw = (e) => {
    e.preventDefault();
    const canvas = canvasRef.current; if (!canvas) return;
    const ctx = canvas.getContext('2d');
    const pos = getPos(e, canvas);
    ctx.beginPath(); ctx.moveTo(pos.x, pos.y);
    setDrawing(true);
  };

  const draw = (e) => {
    e.preventDefault();
    if (!drawing) return;
    const canvas = canvasRef.current; if (!canvas) return;
    const ctx = canvas.getContext('2d');
    const pos = getPos(e, canvas);
    ctx.lineTo(pos.x, pos.y); ctx.stroke();
    setHasDrawn(true);
  };

  const stopDraw = () => setDrawing(false);

  const clearCanvas = () => {
    const canvas = canvasRef.current; if (!canvas) return;
    const ctx = canvas.getContext('2d');
    ctx.fillStyle = '#fff'; ctx.fillRect(0, 0, canvas.width, canvas.height);
    setHasDrawn(false);
  };

  const handleUpload = (e) => {
    const file = e.target.files?.[0]; if (!file) return;
    const reader = new FileReader();
    reader.onload = (ev) => setUploadPreview(ev.target.result);
    reader.readAsDataURL(file);
  };

  const handleSave = async () => {
    setSaving(true); setError('');
    let base64 = null;
    if (mode === 'draw') {
      if (!hasDrawn) { setError('Please draw your signature first.'); setSaving(false); return; }
      base64 = canvasRef.current.toDataURL('image/png');
    } else {
      if (!uploadPreview) { setError('Please upload a signature image.'); setSaving(false); return; }
      base64 = uploadPreview;
    }
    try {
      const res  = await fetch(`${API_BASE}/api/auth/save-signature`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', 'Authorization': `Bearer ${token}` },
        body: JSON.stringify({ signature_data: base64 }),
      });
      const data = await res.json();
      if (res.ok && data.success) { onSaved(base64);  }
      else if (res.status === 401) {
        setError('Session expired — please sign out and sign back in, then try again.');
      } else { setError(data.detail || 'Failed to save signature.'); }
    } catch { setError('Network error. Please try again.'); }
    finally { setSaving(false); }
  };

const handleClear = async () => {
  setClearingSignature(true);
  try {
    const res = await fetch(`${API_BASE}/api/auth/save-signature`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', 'Authorization': `Bearer ${token}` },
      body: JSON.stringify({ signature_data: null }),
    });
    if (res.ok) {
      localStorage.removeItem('acordly_signature');
      onSaved(null);
      
    } else if (res.status === 401) {
      setError('Session expired — please sign out and sign back in.');
    } else {
      setError('Failed to remove signature.');
    }
  } catch {
    setError('Network error.');
  } finally {
    setClearingSignature(false);
  }
};

  return (
    <div className="modal-overlay">
      <div className="modal-content" style={{ maxWidth: 520 }} onClick={e => e.stopPropagation()}>
        <button className="modal-close" onClick={onClose}>✕</button>
        <div className="modal-inner">
          <h2 className="step-title" style={{ marginBottom: 6 }}>✍️ Your Signature</h2>
          <p className="step-subtitle" style={{ marginBottom: 20 }}>
            Saved once, auto-applied to ACORD forms when you choose to sign.
          </p>
          <div style={{ display:'flex', gap:8, marginBottom:16 }}>
            {['draw','upload'].map(m => (
              <button key={m} onClick={() => { setMode(m); setUploadPreview(null); }}
                style={{ flex:1, padding:'8px', borderRadius:8, border:'1.5px solid',
                  borderColor: mode===m ? '#e6007a' : '#e2e8f0',
                  background: mode===m ? 'rgba(230,0,122,0.06)' : '#fff',
                  color: mode===m ? '#e6007a' : '#64748b',
                  fontWeight: mode===m ? 700 : 500, fontSize:13, cursor:'pointer' }}>
                {m === 'draw' ? '✏️ Draw' : '📁 Upload Image'}
              </button>
            ))}
          </div>
          {existingSignature && (
            <div style={{ marginBottom:12, padding:'10px 12px', background:'#f8fafc', borderRadius:8, border:'1px solid #e2e8f0' }}>
              <div style={{ fontSize:11, color:'#94a3b8', marginBottom:6 }}>Current saved signature:</div>
              <img src={existingSignature} alt="Saved signature" style={{ maxHeight:50, maxWidth:'100%', objectFit:'contain' }} />
              <button
                 onClick={handleClear}
                 disabled={clearingSignature}
                 style={{ display:'flex', alignItems:'center', gap:5, marginTop:6, fontSize:11, color:'#ef4444', background:'none', border:'none', cursor: clearingSignature ? 'wait' : 'pointer', textDecoration:'underline', opacity: clearingSignature ? 0.7 : 1 }}
               >
                 {clearingSignature && (
                   <span style={{ width:10, height:10, border:'2px solid #ef4444', borderTopColor:'transparent', borderRadius:'50%', display:'inline-block', animation:'spin 0.7s linear infinite' }} />
                 )}
                 {clearingSignature ? 'Removing...' : 'Remove saved signature'}
              </button>
            </div>
          )}
          {mode === 'draw' && (
            <div>
              <div style={{ fontSize:12, color:'#64748b', marginBottom:8 }}>Draw your signature below:</div>
              <canvas ref={canvasRef} width={440} height={140}
                onMouseDown={startDraw} onMouseMove={draw} onMouseUp={stopDraw} onMouseLeave={stopDraw}
                onTouchStart={startDraw} onTouchMove={draw} onTouchEnd={stopDraw}
                style={{ width:'100%', height:140, border:'1.5px solid #e2e8f0', borderRadius:8,
                  cursor:'crosshair', touchAction:'none', background:'#fff',
                  boxShadow:'inset 0 1px 4px rgba(0,0,0,0.06)' }} />
              <button onClick={clearCanvas} style={{ marginTop:6, fontSize:12, color:'#94a3b8', background:'none', border:'none', cursor:'pointer', textDecoration:'underline' }}>
                Clear
              </button>
            </div>
          )}
          {mode === 'upload' && (
            <div>
              <div style={{ fontSize:12, color:'#64748b', marginBottom:8 }}>Upload a PNG or JPG of your signature:</div>
              <input type="file" accept="image/png,image/jpeg,image/jpg" onChange={handleUpload} style={{ fontSize:13, marginBottom:12 }} />
              {uploadPreview && (
                <div style={{ background:'#f8fafc', borderRadius:8, padding:12, border:'1px solid #e2e8f0', textAlign:'center' }}>
                  <img src={uploadPreview} alt="Preview" style={{ maxHeight:80, maxWidth:'100%', objectFit:'contain' }} />
                </div>
              )}
            </div>
          )}
          {error && <div className="alert alert-error" style={{ marginTop:12 }}><span>⚠️ {error}</span></div>}
          <div style={{ display:'flex', gap:10, marginTop:20 }}>
            <button className="btn btn-modal-primary" style={{ flex:1 }} onClick={handleSave} disabled={saving}>
              {saving ? (
                <span style={{ display:'flex', alignItems:'center', justifyContent:'center', gap:8 }}>
                  <span style={{ width:14, height:14, border:'2px solid currentColor', borderTopColor:'transparent', borderRadius:'50%', display:'inline-block', animation:'spin 0.7s linear infinite' }} />
                  Saving...
                </span>
              ) : '💾 Save Signature'}
            </button>
            <button className="btn btn-modal-secondary" onClick={onClose}>Cancel</button>
          </div>
        </div>
      </div>
    </div>
  );
}

function UseSignaturePrompt({ signature, onApply, onManage, onClose }) {
  return (
    <div className="modal-overlay">
      <div className="modal-content" style={{ maxWidth: 400 }} onClick={e => e.stopPropagation()}>
        <button className="modal-close" onClick={onClose}>✕</button>
        <div className="modal-inner" style={{ textAlign:'center' }}>
          <div style={{ fontSize:36, marginBottom:8 }}>✍️</div>
          <h2 className="step-title" style={{ marginBottom:8 }}>Apply Your Signature?</h2>
          <p style={{ fontSize:13, color:'#64748b', marginBottom:20 }}>
            Your saved signature will be applied to all signature fields in this form.
          </p>
          {signature && (
            <div style={{ background:'#f8fafc', borderRadius:8, padding:12, border:'1px solid #e2e8f0', marginBottom:20 }}>
              <img src={signature} alt="Your signature" style={{ maxHeight:60, maxWidth:'100%', objectFit:'contain' }} />
            </div>
          )}
          <div style={{ display:'flex', flexDirection:'column', gap:10 }}>
            <button className="btn btn-modal-primary btn-block" onClick={onApply}>✅ Yes, Apply Signature</button>
            <button className="btn btn-modal-secondary btn-block" onClick={onClose}>No, Skip</button>
            <button onClick={onManage} style={{ fontSize:12, color:'#94a3b8', background:'none', border:'none', cursor:'pointer', textDecoration:'underline', marginTop:4 }}>
              Manage / Update Signature
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}

function NoSignaturePrompt({ onSetup, onClose }) {
  return (
    <div className="modal-overlay">
      <div className="modal-content" style={{ maxWidth: 380 }} onClick={e => e.stopPropagation()}>
        <button className="modal-close" onClick={onClose}>✕</button>
        <div className="modal-inner" style={{ textAlign:'center' }}>
          <div style={{ fontSize:36, marginBottom:8 }}>✍️</div>
          <h2 className="step-title" style={{ marginBottom:8 }}>No Signature Saved</h2>
          <p style={{ fontSize:13, color:'#64748b', marginBottom:20 }}>
            Set up your signature once and it will be available to apply to all your ACORD forms.
          </p>
          <div style={{ display:'flex', flexDirection:'column', gap:10 }}>
            <button className="btn btn-modal-primary btn-block" onClick={onSetup}>✏️ Set Up Signature</button>
            <button className="btn btn-modal-secondary btn-block" onClick={onClose}>Maybe Later</button>
          </div>
        </div>
      </div>
    </div>
  );
}

// ─── APP CONTENT ─────────────────────────────────────────────────

function AppContent() {
  const [showModal, setShowModal]               = useState(false);
  const [showAuthModal, setShowAuthModal]       = useState(false);
  const [showCompleteProfile, setShowCompleteProfile] = useState(false);
  const [showUpgradeModal, setShowUpgradeModal] = useState(false);
  const [showSignatureModal, setShowSignatureModal] = useState(false);
  const [signingIn, setSigningIn]               = useState(false);
  const [openFaq, setOpenFaq]                   = useState(null);
  const [user, setUser]                         = useState(null);
  const [token, setToken]                       = useState(localStorage.getItem('acordly_token'));
  const [headerError, setHeaderError]           = useState('');
  const [authLoading, setAuthLoading]           = useState(!!localStorage.getItem('acordly_token'));
  const [resumeSessionId, setResumeSessionId]   = useState(null);
  const [savedSignature, setSavedSignature]     = useState(null);
  // FIX Issue 5: billing portal loading state
  const [billingPortalLoading, setBillingPortalLoading] = useState(false);
  const [billingPortalChecking, setBillingPortalChecking] = useState(false);

  const faqData = [
    { question: "What services do you offer?", answer: "AI-powered ACORD form automation. Upload any insurance document and we instantly extract, validate, and fill the right ACORD forms." },
    { question: "How do I get started?", answer: "Click 'Get Started for Free', create an account, upload your documents (multiple at once), and our AI handles extraction, form selection, and auto-fill automatically." },
    { question: "What makes you different?", answer: "Carrier-grade validation with hard stops, cross-form checks, and a 6-component SQS score. No more manual re-entry or underwriter back-and-forth." },
    { question: "What's your pricing model?", answer: "Free tier: 3 submission downloads. After that, upgrade to Pro for unlimited processing with priority support." },
  ];

  useEffect(() => {
    if (token) {
      setAuthLoading(true);
      fetch(`${API_BASE}/api/auth/me`, { headers: { 'Authorization': `Bearer ${token}` } })
        .then(res => res.ok ? res.json() : Promise.reject())
        .then(data => { setUser(data); })
        .catch(() => { localStorage.removeItem('acordly_token'); setToken(null); })
        .finally(() => setAuthLoading(false));
    }
  }, [token]);

  useEffect(() => {
    if (!token || !user) return;
    const cached = localStorage.getItem('acordly_signature');
    if (cached) setSavedSignature(cached);
    fetch(`${API_BASE}/api/auth/me`, { headers: { 'Authorization': `Bearer ${token}` } })
      .then(r => r.ok ? r.json() : Promise.reject('token_invalid'))
      .then(() => fetch(`${API_BASE}/api/auth/get-signature`, {
        headers: { 'Authorization': `Bearer ${token}` }
      }))
      .then(r => r.ok ? r.json() : null)
      .then(data => {
        if (data?.signature_data) {
          setSavedSignature(data.signature_data);
          localStorage.setItem('acordly_signature', data.signature_data);
        } else if (data !== null && data !== undefined && !data.signature_data) {
          setSavedSignature(null);
          localStorage.removeItem('acordly_signature');
        }
      })
      .catch(() => {});
  }, [user?.id]); // eslint-disable-line

  const [upgradeChecking, setUpgradeChecking] = useState(false);
  const [upgradeFailed,   setUpgradeFailed]   = useState(false);

  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    if (params.get('upgraded') !== 'true') return;
    window.history.replaceState({}, '', '/');
    if (!token) return;

    setUpgradeChecking(true);
    setUpgradeFailed(false);

    const MAX_POLL    = 8;
    const POLL_DELAY  = 2000;
    let   attempts    = 0;
    const isPaid = (tier) => tier && tier !== 'free';

    const pollMe = () => {
      attempts++;
      fetch(`${API_BASE}/api/auth/me`, { headers: { 'Authorization': `Bearer ${token}` } })
        .then(r => r.ok ? r.json() : null)
        .then(data => {
          if (!data) { tryVerifyFallback(); return; }
          setUser(data);
          if (isPaid(data.subscription_tier)) {
            setUpgradeChecking(false);
          } else if (attempts < MAX_POLL) {
            setTimeout(pollMe, POLL_DELAY);
          } else {
            tryVerifyFallback();
          }
        })
        .catch(() => { if (attempts < MAX_POLL) setTimeout(pollMe, POLL_DELAY); else tryVerifyFallback(); });
    };

    const tryVerifyFallback = () => {
      fetch(`${API_BASE}/api/stripe/verify-upgrade`, {
        method: 'POST', headers: { 'Authorization': `Bearer ${token}` }
      })
        .then(r => r.ok ? r.json() : null)
        .then(data => {
          if (data && isPaid(data.subscription_tier)) {
            fetch(`${API_BASE}/api/auth/me`, { headers: { 'Authorization': `Bearer ${token}` } })
              .then(r => r.ok ? r.json() : null)
              .then(me => { if (me) setUser(me); });
            setUpgradeChecking(false);
          } else {
            setUpgradeChecking(false);
            setUpgradeFailed(true);
          }
        })
        .catch(() => { setUpgradeChecking(false); setUpgradeFailed(true); });
    };

    pollMe();
  }, []);

  
useEffect(() => {
  const params = new URLSearchParams(window.location.search);
  if (params.get('billing_updated') !== 'true') return;
  if (!token) return;
  window.history.replaceState({}, '', '/');

  setUpgradeChecking(true);
  let attempts = 0;

  const poll = () => {
    attempts++;
    fetch(`${API_BASE}/api/auth/me`, { headers: { 'Authorization': `Bearer ${token}` } })
      .then(r => r.ok ? r.json() : null)
      .then(data => {
        if (data) setUser(data);
        setUpgradeChecking(false);
      })
      .catch(() => {
        if (attempts < 6) setTimeout(poll, 2000);
        else setUpgradeChecking(false);
      });
  };

  setTimeout(poll, 1000);
}, [token]);  // ← key change: depends on token, not []


  const [overageToast, setOverageToast] = useState(null);
  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    if (params.get('overage_paid') !== 'true') return;

    const qty             = params.get('qty') || '?';
    const stripeSessionId = params.get('stripe_session_id');
    const savedSid        = localStorage.getItem('acordly_overage_session');
    window.history.replaceState({}, '', '/');
    localStorage.removeItem('acordly_overage_session');
    localStorage.removeItem('acordly_prev_limit');

    if (!token || !stripeSessionId) return;

    fetch(`${API_BASE}/api/stripe/apply-overage`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', 'Authorization': `Bearer ${token}` },
      body: JSON.stringify({ stripe_session_id: stripeSessionId, qty: parseInt(qty) || 1 }),
    })
      .then(r => r.json())
      .then(data => {
        return fetch(`${API_BASE}/api/auth/me`, { headers: { 'Authorization': `Bearer ${token}` } })
          .then(r => r.ok ? r.json() : null)
          .then(me => {
            if (me) setUser(me);
            const applied = data.credited || data.already_applied;
            setOverageToast(
              applied
                ? `✅ ${qty} extra package${qty !== '1' ? 's' : ''} added! You can continue downloading.`
                : `⚠️ Could not verify payment. Please contact support if packages were not credited.`
            );
            setTimeout(() => setOverageToast(null), 8000);
            if (savedSid && applied) {
              setResumeSessionId(savedSid);
              setShowModal(true);
            }
          });
      })
      .catch(() => {
        setOverageToast(`⚠️ Payment received but could not auto-credit. Please refresh or contact support.`);
        setTimeout(() => setOverageToast(null), 8000);
        if (savedSid) { setResumeSessionId(savedSid); setShowModal(true); }
      });
  }, []);

  const openBillingPortal = async () => {
  setUpgradeChecking(true);  // shows full-screen overlay instantly
  try {
    const res = await fetch(`${API_BASE}/api/stripe/create-portal-session`, {
      method: 'POST', headers: { 'Authorization': `Bearer ${token}` }
    });
    const data = await res.json();
    if (data.url) {
      window.location.href = data.url;  // navigate away — overlay stays until page leaves
    } else {
      setUpgradeChecking(false);
      setHeaderError(data.detail || 'Could not open billing portal.');
    }
  } catch {
    setUpgradeChecking(false);
    setHeaderError('Network error. Please try again.');
  }
};

  // Shared spinner element for billing buttons
  const BillingSpinner = () => (
    <span style={{ width:12, height:12, border:'2px solid currentColor', borderTopColor:'transparent', borderRadius:'50%', display:'inline-block', animation:'spin 0.7s linear infinite', marginRight:4 }} />
  );

  const handleGetStarted = () => user ? setShowModal(true) : setShowAuthModal(true);

  const handleLogout = () => {
    fetch(`${API_BASE}/api/auth/logout`, { method: 'POST', headers: { 'Authorization': `Bearer ${token}` } })
      .finally(() => { localStorage.removeItem('acordly_token'); localStorage.removeItem('acordlysignature'); setToken(null); setUser(null); setSavedSignature(null); });
  };

  return (
    <div className="landing-container">
      {overageToast && (
        <div style={{
          position: 'fixed', bottom: 24, left: '50%', transform: 'translateX(-50%)',
          background: '#10b981', color: '#fff', padding: '12px 24px', borderRadius: 10,
          fontWeight: 600, fontSize: 14, zIndex: 9999, boxShadow: '0 4px 20px rgba(0,0,0,0.18)',
        }}>
          {overageToast}
        </div>
      )}

      {upgradeChecking && <UpgradeStageOverlay />}
      {billingPortalChecking && <UpgradeStageOverlay />}

      {signingIn && (
        <div style={{
          position: 'fixed', inset: 0, background: 'rgba(255,255,255,0.97)',
          display: 'flex', flexDirection: 'column', alignItems: 'center',
          justifyContent: 'center', zIndex: 9999,
        }}>
          <div className="loading-spinner" style={{ width: 40, height: 40, marginBottom: 16 }} />
          <p style={{ color: '#64748b', fontSize: '15px', fontWeight: 500 }}>Signing you in...</p>
        </div>
      )}

      <header className="landing-header">
        <div className="header-left">
          <div className="logo">acordly</div>
          <nav className="nav">
            <a href="#about">About</a><a href="#platform">Platform</a>
            <a href="#pricing">Pricing</a><a href="#acord">ACORD®</a>
          </nav>
        </div>

        {user ? (
          <div className="user-menu">
            <span className="user-email">{user.email}</span>

            <button
              className="btn-signature-header"
              onClick={() => setShowSignatureModal(true)}
              title={savedSignature ? 'Manage your saved signature' : 'Set up your signature'}
            >
              {savedSignature ? '✍️ Signature' : '✍️ Add Signature'}
            </button>

            {upgradeChecking ? (
              <span className="upgrade-checking">⏳ Activating plan...</span>
            ) : upgradeFailed ? (
              <span className="upgrade-failed" title="Payment received but activation pending. Click to retry.">
                ⚠️ Activation pending
                <button
                  className="btn-retry-upgrade"
                  onClick={() => {
                    setUpgradeFailed(false);
                    setUpgradeChecking(true);
                    fetch(`${API_BASE}/api/stripe/verify-upgrade`, {
                      method: 'POST', headers: { 'Authorization': `Bearer ${token}` }
                    })
                      .then(r => r.ok ? r.json() : null)
                      .then(data => {
                        if (data && data.subscription_tier && data.subscription_tier !== 'free') {
                          fetch(`${API_BASE}/api/auth/me`, { headers: { 'Authorization': `Bearer ${token}` } })
                            .then(r => r.ok ? r.json() : null)
                            .then(me => { if (me) setUser(me); });
                          setUpgradeChecking(false);
                        } else {
                          setUpgradeFailed(true);
                          setUpgradeChecking(false);
                        }
                      })
                      .catch(() => { setUpgradeFailed(true); setUpgradeChecking(false); });
                  }}
                >Retry</button>
                <a href="mailto:support@acordly.ai" className="upgrade-support-link">Contact support</a>
              </span>
            ) : user.payment_status === 'archived' ? (
              <span style={{ display:'flex', alignItems:'center', gap:6, background:'#f1f5f9', color:'#64748b', fontSize:13, fontWeight:600, padding:'4px 10px', borderRadius:6, border:'1px solid #cbd5e1' }}>
                🗄️ Account archived —&nbsp;<a href="mailto:support@acordly.ai" style={{ color:'#64748b', fontWeight:700 }}>Contact support</a>
              </span>
            ) : user.payment_status === 'suspended' ? (
              <span style={{ display:'flex', alignItems:'center', gap:6, background:'#7f1d1d', color:'#fca5a5', fontSize:13, fontWeight:600, padding:'4px 10px', borderRadius:6, border:'1px solid #991b1b' }}>
                🚫 Account suspended —&nbsp;
                <button
                  onClick={openBillingPortal}
                  disabled={billingPortalLoading}
                  style={{ color:'#fca5a5', fontWeight:700, background:'none', border:'none', cursor: billingPortalLoading ? 'wait' : 'pointer', padding:0, textDecoration:'underline', display:'flex', alignItems:'center', gap:4 }}
                >
                  {billingPortalLoading && <BillingSpinner />}
                  Restore billing
                </button>
              </span>
            ) : user.payment_status === 'soft_locked' ? (
              <span style={{ display:'flex', alignItems:'center', gap:6, background:'#78350f', color:'#fcd34d', fontSize:13, fontWeight:600, padding:'4px 10px', borderRadius:6, border:'1px solid #92400e' }}>
                🔒 Account Disabled —&nbsp;
                <button
                  onClick={openBillingPortal}
                  disabled={billingPortalLoading}
                  style={{ color:'#fcd34d', fontWeight:700, background:'none', border:'none', cursor: billingPortalLoading ? 'wait' : 'pointer', padding:0, textDecoration:'underline', display:'flex', alignItems:'center', gap:4 }}
                >
                  {billingPortalLoading && <BillingSpinner />}
                  Update Billing
                </button>
              </span>
            ) : user.payment_status === 'failed' ? (
              <span style={{ display:'flex', alignItems:'center', gap:6, background:'#fef2f2', color:'#991b1b', fontSize:13, fontWeight:600, padding:'4px 10px', borderRadius:6, border:'1px solid #fca5a5' }}>
                ⚠️ Payment overdue —&nbsp;
                <button
                  onClick={openBillingPortal}
                  disabled={billingPortalLoading}
                  style={{ color:'#991b1b', fontWeight:700, background:'none', border:'none', cursor: billingPortalLoading ? 'wait' : 'pointer', padding:0, textDecoration:'underline', display:'flex', alignItems:'center', gap:4 }}
                >
                  {billingPortalLoading && <BillingSpinner />}
                  Update billing
                </button>
              </span>
            ) : user.subscription_tier === 'free' ? (
              <button className="btn-upgrade-header" onClick={() => setShowUpgradeModal(true)}>
                ⭐ Upgrade
              </button>
            ) : (
              <span className="pro-badge">
                ✅ {user.subscription_tier === 'essentials' ? 'Essentials'
                   : user.subscription_tier === 'professional' ? 'Professional'
                   : user.subscription_tier === 'enterprise' ? 'Enterprise'
                   : 'Pro'}
              </span>
            )}
            <button className="btn-dark" onClick={handleLogout}>Sign Out</button>
          </div>
        ) : (
          <button className="btn-dark" onClick={() => setShowAuthModal(true)}>Sign In</button>
        )}
      </header>

      {headerError && (
        <div className="header-error-bar">
          ⚠️ {headerError}
          <button onClick={() => setHeaderError('')}>✕</button>
        </div>
      )}

      <section className="hero">
        <h1 className="hero-h1">ACORD® made easy</h1>
        <p className="hero-p">Commercial insurance, without the paperwork. Instantly convert any insurance documents into completed ACORD forms.</p>
        <button className="btn-primary" onClick={handleGetStarted}>
          {user ? 'UPLOAD DOCUMENTS' : 'GET STARTED FOR FREE'}
        </button>
        <a href="https://www.youtube.com/watch?v=dQw4w9WgXcQ" target="_blank" rel="noopener noreferrer" className="hero-link">See how it works →</a>
      </section>

      <section className="features">
        {[
          { img: "feature1.webp", title: "AI Infrastructure", desc: "Advanced AI processes your documents with 99% accuracy, reducing manual entry by 95%." },
          { img: "feature2.webp", title: "User Agnostic", desc: "Works for brokers, agents, and underwriters. No training required." },
          { img: "feature3.webp", title: "Transparent Pricing", desc: "3 free downloads. Clear pricing with no hidden fees after." },
        ].map((f, i) => (
          <div key={i} className="feature">
            <img src={f.img} alt={f.title} className="feature-image" />
            <h3 className="feature-h3">{f.title}</h3>
            <p className="feature-p">{f.desc}</p>
          </div>
        ))}
      </section>

      <section className="quote">
        <img src="quote-image.webp" alt="Quote" className="quote-image" />
        <blockquote className="blockquote">
          "Getting to underwriting shouldn't require retyping the same data five times in a row..."
          <span className="blockquote-span">— Michelle Smith, Co-Founder &amp; CIO</span>
        </blockquote>
      </section>

      <section className="banner">
        <h2 className="banner-h2">Innovation without compromise</h2>
        <img src="https://images.unsplash.com/photo-1451187580459-43490279c0fa?w=1200&h=500&fit=crop" alt="Innovation" className="banner-image" />
        <p className="banner-p">Cutting-edge technology that moves your business forward—securely, efficiently, and at scale.</p>
      </section>

      <section className="faq">
        <div>
          <h3 className="faq-h3">What is acordly.ai?</h3>
          <p className="faq-p">We bridge the gap between insurance documents and carrier-ready ACORD submissions.</p>
        </div>
        <div className="faq-list">
          {faqData.map((item, i) => (
            <div key={i} className="faq-item-wrapper">
              <div className="faq-item" onClick={() => setOpenFaq(openFaq === i ? null : i)}>
                <span>{item.question}</span>
                <span className={`faq-icon ${openFaq === i ? 'open' : ''}`}>+</span>
              </div>
              {openFaq === i && <div className="faq-answer">{item.answer}</div>}
            </div>
          ))}
        </div>
      </section>

      <footer className="footer">
        <div><h4 className="footer-h4">About Us</h4><p className="footer-p">123 Demo Street<br />New York, NY</p></div>
        <div><h4 className="footer-h4">Contact Us</h4><p className="footer-p">email@example.com<br />(555) 555-5555</p></div>
        <div>
          <h4 className="footer-h4">Follow Us</h4>
          <p className="footer-p">
            <a href="https://instagram.com" target="_blank" rel="noopener noreferrer">Instagram</a><br />
            <a href="https://twitter.com" target="_blank" rel="noopener noreferrer">Twitter</a><br />
            <a href="https://pinterest.com" target="_blank" rel="noopener noreferrer">Pinterest</a>
          </p>
        </div>
        <div>
          <h4 className="footer-h4">Newsletter</h4>
          <p className="footer-p">Join our mailing list for the latest insights and product updates.</p>
          <input className="footer-input" placeholder="Email Address" />
          <button className="footer-button">Sign Up</button>
        </div>
      </footer>

      {showAuthModal && (
        <AuthModal
          onClose={() => setShowAuthModal(false)}
          onSuccess={(tok, usr, profileIncomplete) => {
            setToken(tok); setUser(usr);
            localStorage.setItem('acordly_token', tok);
            setShowAuthModal(false);
            setSigningIn(true);
            setTimeout(() => {
              setSigningIn(false);
              if (profileIncomplete) {
                setShowCompleteProfile(true);
              } else {
                setShowModal(true);
              }
            }, 80);
          }}
        />
      )}

      {showCompleteProfile && user && (
        <CompleteProfileModal
          token={token}
          user={user}
          onComplete={(updatedUser) => {
            setUser(updatedUser);
            setShowCompleteProfile(false);
            setShowModal(true);
          }}
        />
      )}

    {showModal && user && (
        <AcordModal
          onClose={() => { setShowModal(false); setResumeSessionId(null); }}
          user={user} token={token} onUserUpdate={setUser}
          onShowUpgrade={() => setShowUpgradeModal(true)}
          resumeSessionId={resumeSessionId}
          savedSignature={savedSignature}
          onOpenSignatureModal={() => setShowSignatureModal(true)}
          onOpenBillingPortal={openBillingPortal}
          billingPortalLoading={billingPortalLoading}
        />
      )}

      {showUpgradeModal && (
        <UpgradeModal
          token={token}
          user={user}
          onClose={() => setShowUpgradeModal(false)}
          onError={(msg) => { setShowUpgradeModal(false); setHeaderError(msg); }}
        />
      )}

      {showSignatureModal && (
        <SignatureModal
          token={token}
          existingSignature={savedSignature}
          onClose={() => setShowSignatureModal(false)}
          onSaved={(sig) => {
            setSavedSignature(sig);
            if (sig) localStorage.setItem('acordly_signature', sig);
            else localStorage.removeItem('acordly_signature');
          }}
        />
      )}
    </div>
  );
}

// ─── AUTH MODAL ──────────────────────────────────────────────────
function AuthModal({ onClose, onSuccess }) {
  const [mode, setMode]                       = useState('signin');
  const [email, setEmail]                     = useState('');
  const [password, setPassword]               = useState('');
  const [fullName, setFullName]               = useState('');
  const [orgName, setOrgName]                 = useState('');
  const [disclaimerChecked, setDisclaimerChecked] = useState(false);
  const [needsVerify, setNeedsVerify]         = useState(false);
  const [verifyCode, setVerifyCode]           = useState('');
  const [error, setError]                     = useState('');
  const [loading, setLoading]                 = useState(false);
  const [transitioning, setTransitioning]     = useState(false);

  const [mode2, setMode2]         = useState('');
  const [resetCode, setResetCode] = useState('');
  const [newPass, setNewPass]     = useState('');
  const [resetMsg, setResetMsg]   = useState('');

  const PERSONAL_DOMAINS = ['gmail.com','yahoo.com','hotmail.com','outlook.com',
    'icloud.com','live.com','aol.com','msn.com','ymail.com','mail.com',
    'protonmail.com','proton.me','tutanota.com','zoho.com'];
  const isPersonalEmail = (e) => {
    const d = e.toLowerCase().split('@')[1] || '';
    return PERSONAL_DOMAINS.includes(d);
  };

  const handleEmailAuth = async (e) => {
    e.preventDefault(); setError(''); setLoading(true);
    if (mode === 'signup') {
      if (!disclaimerChecked) { setError('You must accept the ACORD disclaimer to create an account.'); setLoading(false); return; }
      if (!orgName.trim()) { setError('Organization or agency name is required.'); setLoading(false); return; }
      if (isPersonalEmail(email)) { setError('Please use a work email address. Personal email domains are not accepted.'); setLoading(false); return; }
    }
    const endpoint = mode === 'signup' ? '/api/auth/signup' : '/api/auth/login';
    const body     = mode === 'signup'
      ? { email, password, full_name: fullName, organization_name: orgName.trim(), acord_disclaimer_accepted: disclaimerChecked }
      : { email, password };
    try {
      const res  = await fetch(`${API_BASE}${endpoint}`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) });
      const data = await res.json();
      if (res.status === 202 && data.requires_verification) { setLoading(false); setNeedsVerify(true); }
      else if (res.ok && data.token) { setTransitioning(true); onSuccess(data.token, data.user); }
      else if (data.requires_verification) { setLoading(false); setNeedsVerify(true); }
      else { setLoading(false); setError(data.detail || data.message || 'Authentication failed'); }
    } catch { setLoading(false); setError('Network error. Please try again.'); }
  };

  const handleVerify = async (e) => {
    e.preventDefault(); setError(''); setLoading(true);
    try {
      const res  = await fetch(`${API_BASE}/api/auth/verify-email`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ email, code: verifyCode }) });
      const data = await res.json();
      if (res.ok && data.token) { setTransitioning(true); onSuccess(data.token, data.user); }
      else { setLoading(false); setError(data.detail || 'Invalid code'); }
    } catch { setLoading(false); setError('Network error.'); }
  };

  const handleForgotRequest = async (e) => {
    e.preventDefault(); setError(''); setResetMsg(''); setLoading(true);
    try {
      await fetch(`${API_BASE}/api/auth/forgot-password`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ email }) });
      setResetMsg('If that email is registered, a reset code has been sent.');
      setMode2('resetcode');
    } catch { setError('Network error. Please try again.'); }
    finally { setLoading(false); }
  };

  const handleResetPassword = async (e) => {
    e.preventDefault(); setError(''); setLoading(true);
    try {
      const res  = await fetch(`${API_BASE}/api/auth/reset-password`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ email, code: resetCode, new_password: newPass }) });
      const data = await res.json();
      if (res.ok) { setResetMsg('Password updated! You can now sign in.'); setMode2(''); setMode('signin'); setPassword(''); }
      else { setError(data.detail || 'Reset failed. Please try again.'); }
    } catch { setError('Network error.'); }
    finally { setLoading(false); }
  };

  const handleGoogleSuccess = async (credentialResponse) => {
    setLoading(true);
    try {
      const res  = await fetch(`${API_BASE}/api/auth/google`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ credential: credentialResponse.credential }) });
      const data = await res.json();
      if (res.ok && data.token) { setTransitioning(true); onSuccess(data.token, data.user, data.profile_incomplete === true); }
      else { setLoading(false); setError(data.detail || data.message || 'Google authentication failed'); }
    } catch { setLoading(false); setError('Network error. Please try again.'); }
  };

  if (needsVerify) {
    return (
      <div className="modal-overlay">
        <div className="modal-content auth-modal">
          <button className="modal-close" onClick={onClose}>✕</button>
          <div className="modal-inner">
            {transitioning ? (
              <div style={{ textAlign:'center', padding:'40px 0' }}>
                <div className="loading-spinner" style={{ margin:'0 auto 12px' }} />
                <p style={{ color:'#64748b', fontSize:'14px' }}>Signing you in...</p>
              </div>
            ) : (
              <>
                <h2 className="step-title">Verify Your Email</h2>
                <p className="step-subtitle">Enter the 6-digit code sent to {email}</p>
                {error && <div className="alert alert-error"><span>⚠️ {error}</span></div>}
                <form onSubmit={handleVerify} className="auth-form">
                  <div className="form-group">
                    <label>Verification Code</label>
                    <input type="text" value={verifyCode} onChange={e => setVerifyCode(e.target.value)} placeholder="123456" required className="form-input" maxLength={6} />
                  </div>
                  <button type="submit" className="btn btn-modal-primary btn-block" disabled={loading}>{loading ? 'Verifying...' : 'Verify Email'}</button>
                </form>
                <div className="auth-switch">
                  <button onClick={async () => { await fetch(`${API_BASE}/api/auth/resend-verification`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ email }) }); }}>Resend code</button>
                </div>
              </>
            )}
          </div>
        </div>
      </div>
    );
  }

  if (mode2 === 'forgot') {
    return (
      <div className="modal-overlay">
        <div className="modal-content auth-modal">
          <button className="modal-close" onClick={onClose}>✕</button>
          <div className="modal-inner">
            <h2 className="step-title">Reset Your Password</h2>
            <p className="step-subtitle">Enter your email and we'll send a reset code</p>
            {error    && <div className="alert alert-error"><span>⚠️ {error}</span></div>}
            {resetMsg && <div className="alert alert-success"><span>✅ {resetMsg}</span></div>}
            <form onSubmit={handleForgotRequest} className="auth-form">
              <div className="form-group">
                <label>Email Address</label>
                <input type="email" value={email} onChange={e => setEmail(e.target.value)} placeholder="you@youragency.com" required className="form-input" />
              </div>
              <button type="submit" className="btn btn-modal-primary btn-block" disabled={loading}>{loading ? 'Sending...' : 'Send Reset Code'}</button>
            </form>
            <div className="auth-switch"><button onClick={() => { setMode2(''); setError(''); }}>← Back to Sign In</button></div>
          </div>
        </div>
      </div>
    );
  }

  if (mode2 === 'resetcode') {
    return (
      <div className="modal-overlay">
        <div className="modal-content auth-modal">
          <button className="modal-close" onClick={onClose}>✕</button>
          <div className="modal-inner">
            <h2 className="step-title">Set New Password</h2>
            <p className="step-subtitle">Enter the code sent to {email} and your new password</p>
            {error    && <div className="alert alert-error"><span>⚠️ {error}</span></div>}
            {resetMsg && <div className="alert alert-success"><span>✅ {resetMsg}</span></div>}
            <form onSubmit={handleResetPassword} className="auth-form">
              <div className="form-group">
                <label>Reset Code</label>
                <input type="text" value={resetCode} onChange={e => setResetCode(e.target.value)} placeholder="123456" required className="form-input" maxLength={6} />
              </div>
              <div className="form-group">
                <label>New Password</label>
                <input type="password" value={newPass} onChange={e => setNewPass(e.target.value)} placeholder="Min 8 chars, 1 uppercase, 1 special" required className="form-input" />
              </div>
              <button type="submit" className="btn btn-modal-primary btn-block" disabled={loading}>{loading ? 'Updating...' : 'Set New Password'}</button>
            </form>
            <div className="auth-switch"><button onClick={() => { setMode2('forgot'); setError(''); }}>← Resend code</button></div>
          </div>
        </div>
      </div>
    );
  }

  if (transitioning) {
    return (
      <div className="modal-overlay">
        <div className="modal-content auth-modal" style={{ display:'flex', alignItems:'center', justifyContent:'center', minHeight:'200px' }}>
          <div style={{ textAlign:'center' }}>
            <div className="loading-spinner" style={{ margin:'0 auto 12px' }} />
            <p style={{ color:'#64748b', fontSize:'14px' }}>Signing you in...</p>
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className="modal-overlay">
      <div className="modal-content auth-modal">
        <button className="modal-close" onClick={onClose}>✕</button>
        <div className="modal-inner">
          <div className="auth-header">
            <h2 className="step-title">{mode === 'signin' ? 'Welcome Back' : 'Create Account'}</h2>
            <p className="step-subtitle">{mode === 'signin' ? 'Sign in to access your documents' : 'Get started with 3 free downloads'}</p>
          </div>
          {error && (<div className="alert alert-error"><span>⚠️ {error}</span><button className="alert-close" onClick={() => setError('')}>✕</button></div>)}
          {resetMsg && <div className="alert alert-success"><span>✅ {resetMsg}</span></div>}
          <div className="auth-google">
            <GoogleLogin onSuccess={handleGoogleSuccess} onError={() => setError('Google sign-in failed')} useOneTap size="large" text={mode === 'signin' ? 'signin_with' : 'signup_with'} shape="pill" logo_alignment="left" />
          </div>
          <div className="auth-divider"><span>or continue with email</span></div>
          <form onSubmit={handleEmailAuth} className="auth-form">
            {mode === 'signup' && (
              <>
                <div className="form-group">
                  <label>Full Name</label>
                  <input type="text" value={fullName} onChange={e => setFullName(e.target.value)} placeholder="Jane Smith" required className="form-input" />
                </div>
                <div className="form-group">
                  <label>Organization / Agency Name <span className="field-required">*</span></label>
                  <input type="text" value={orgName} onChange={e => setOrgName(e.target.value)} placeholder="Smith Insurance Agency LLC" required className="form-input" />
                </div>
              </>
            )}
            <div className="form-group">
              <label>Work Email <span className="field-required">*</span></label>
              <input type="email" value={email} onChange={e => setEmail(e.target.value)} placeholder="you@youragency.com" required className="form-input" />
              {mode === 'signup' && isPersonalEmail(email) && email.length > 4 && (
                <span className="field-warning">⚠ Please use a work email address</span>
              )}
            </div>
            <div className="form-group">
              <label>Password</label>
              <input type="password" value={password} onChange={e => setPassword(e.target.value)} placeholder={mode === 'signup' ? 'Min 8 chars, 1 uppercase, 1 special' : '••••••••'} required className="form-input" />
            </div>
            {mode === 'signup' && (
              <div className="acord-disclaimer-box">
                <label className="acord-disclaimer-label">
                  <input type="checkbox" checked={disclaimerChecked} onChange={e => setDisclaimerChecked(e.target.checked)} className="acord-disclaimer-checkbox" />
                  <span>By creating an account, you acknowledge that <strong>ACORD® Forms require a separate license from ACORD Corporation</strong> and agree to obtain any required license before exporting or distributing those forms.</span>
                </label>
              </div>
            )}
            <button type="submit" className="btn btn-modal-primary btn-block" disabled={loading || (mode === 'signup' && !disclaimerChecked)}>
              {loading ? 'Please wait...' : mode === 'signin' ? 'Sign In' : 'Create Account'}
            </button>
          </form>
          <div className="auth-switch">
            {mode === 'signin' ? (
              <>
                <p>Don't have an account? <button onClick={() => { setMode('signup'); setDisclaimerChecked(false); setResetMsg(''); }}>Sign up</button></p>
                <p style={{ marginTop: '6px' }}>
                  <button style={{ color: '#64748b', fontSize: '13px' }} onClick={() => { setMode2('forgot'); setError(''); setResetMsg(''); }}>Forgot your password?</button>
                </p>
              </>
            ) : (
              <p>Already have an account? <button onClick={() => setMode('signin')}>Sign in</button></p>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}

// ─── ACORD MODAL ─────────────────────────────────────────────────
function AcordModal({ onClose, user, token, onUserUpdate, onShowUpgrade, resumeSessionId, savedSignature, onOpenSignatureModal, onOpenBillingPortal, billingPortalLoading }) {
  const dropRef = useRef(null);

  const [files, setFiles]                     = useState([]);
  const [dragging, setDragging]               = useState(false);
  const [loading, setLoading]                 = useState(false);
  const [processingStage, setProcessingStage] = useState('');
  const [step, setStep]                       = useState(resumeSessionId ? 'resuming' : 'upload');
  const [error, setError]                     = useState(null);

  const [sessionId, setSessionId]             = useState(resumeSessionId || null);
  const [docSummary, setDocSummary]           = useState([]);
  const [flags, setFlags]                     = useState({});
  const [hardStops, setHardStops]             = useState([]);
  const [softStops, setSoftStops]             = useState([]);
  const [tier2Score, setTier2Score]           = useState(null);
  const [tier2Missing, setTier2Missing]       = useState([]);
  const [recommendations, setRecommendations] = useState([]);
  const [allAvailableForms, setAllAvailableForms] = useState([]);

  const [checkedFormIds, setCheckedFormIds] = useState(new Set());
  const [showAddForms, setShowAddForms]     = useState(false);

  const [generatedForms, setGeneratedForms] = useState({});
  const [activeFormId, setActiveFormId]     = useState(null);
  const [crossIssues, setCrossIssues]       = useState([]);

  const [pdfLoading, setPdfLoading] = useState({});
  const [pkgStatusMsg, setPkgStatusMsg]   = useState('');
  const [pkgStatusType, setPkgStatusType] = useState('');
  const [signedForms, setSignedForms] = useState(new Set());

  // Staged overlay states
  const [showUploadOverlay,   setShowUploadOverlay]   = useState(false);
  const [showGenerateOverlay, setShowGenerateOverlay] = useState(false);
  const [showDownloadOverlay, setShowDownloadOverlay] = useState(false);

  const [showAcordModal, setShowAcordModal]         = useState(false);
  const [acordModalAction, setAcordModalAction]     = useState(null);
  const [acordLicenseChecked, setAcordLicenseChecked] = useState(false);
  const [acordModalLoading, setAcordModalLoading]   = useState(false);

  const [epicLoading, setEpicLoading] = useState(false);
  const [epicSuccess, setEpicSuccess] = useState(false);

  const SQS_LABELS = {
    structural_completeness: 'Structural Completeness',
    exposure_consistency:    'Exposure Consistency',
    property_integrity:      'Property Integrity',
    loss_history_alignment:  'Loss History',
    umbrella_limit_adequacy: 'Umbrella Adequacy',
    narrative_quality:       'Narrative Quality',
  };
  const SQS_WEIGHTS = {
    structural_completeness: 25, exposure_consistency: 25,
    property_integrity: 15,      loss_history_alignment: 15,
    umbrella_limit_adequacy: 10, narrative_quality: 10,
  };

  useEffect(() => {
    const prev = document.body.style.overflow;
    document.body.style.overflow = 'hidden';
    return () => { document.body.style.overflow = prev; };
  }, []);

  useEffect(() => {
    if (!resumeSessionId) return;
    setLoading(true);
    setProcessingStage('Restoring your session...');
    fetch(`${API_BASE}/api/session/${resumeSessionId}`, { headers: { 'Authorization': `Bearer ${token}` } })
      .then(r => r.ok ? r.json() : null)
      .then(data => {
        if (data && data.generated_forms && Object.keys(data.generated_forms).length > 0) {
          const generated = data.generated_forms;
          setGeneratedForms(generated);
          setCrossIssues(data.cross_issues || []);
          const firstId = Object.keys(generated)[0];
          setActiveFormId(firstId);
          const readyMap = {};
          Object.keys(generated).forEach(fid => { readyMap[fid] = false; });
          setPdfLoading(readyMap);
          setStep('editor');
        } else {
          setStep('upload'); setSessionId(null);
        }
      })
      .catch(() => { setStep('upload'); setSessionId(null); })
      .finally(() => { setLoading(false); setProcessingStage(''); });
  }, [resumeSessionId]);

  useEffect(() => {
    const el = dropRef.current;
    if (!el) return;
    const over  = e => { e.preventDefault(); setDragging(true); };
    const leave = () => setDragging(false);
    const drop  = e => {
      e.preventDefault(); setDragging(false);
      const uploaded = Array.from(e.dataTransfer.files).filter(f =>
        f.type === 'application/pdf' || f.name.toLowerCase().endsWith('.zip') || f.type.startsWith('image/')
      );
      setFiles(prev => [...prev, ...uploaded]);
    };
    el.addEventListener('dragover', over);
    el.addEventListener('dragleave', leave);
    el.addEventListener('drop', drop);
    return () => { el.removeEventListener('dragover', over); el.removeEventListener('dragleave', leave); el.removeEventListener('drop', drop); };
  }, []);

  const reset = () => {
    setFiles([]); setSessionId(null); setStep('upload'); setError(null);
    setDocSummary([]); setFlags({}); setHardStops([]); setSoftStops([]);
    setTier2Score(null); setTier2Missing([]); setRecommendations([]);
    setAllAvailableForms([]); setCheckedFormIds(new Set());
    setGeneratedForms({}); setActiveFormId(null); setCrossIssues([]);
    setPdfLoading({}); setEpicLoading(false); setEpicSuccess(false);
    setSignedForms(new Set());
    setShowUploadOverlay(false); setShowGenerateOverlay(false); setShowDownloadOverlay(false);
  };

  const handleSendToEpic = async (formId) => {
    if (!formId || !sessionId) return;
    setEpicLoading(true); setEpicSuccess(false);
    try {
      const res  = await fetch(`${API_BASE}/api/send-to-epic/${sessionId}/${formId}`, { headers: { 'Authorization': `Bearer ${token}` } });
      const data = await res.json();
      if (res.ok && data.success) { setEpicSuccess(true); setTimeout(() => setEpicSuccess(false), 3500); }
      else { setError(data.detail || 'Failed to send to EPIC. Check backend terminal.'); }
    } catch (e) { setError('EPIC send failed: ' + e.message); }
    finally { setEpicLoading(false); }
  };

  const gradeColor = g => ({ A:'#10b981', B:'#14b8a6', C:'#f59e0b', D:'#ef4444', F:'#dc2626' }[g] || '#6b7280');
  const barColor   = v => v >= 80 ? '#10b981' : v >= 60 ? '#f59e0b' : '#ef4444';

  const gatedDownload = (action) => {
    setAcordLicenseChecked(false);
    setAcordModalAction(() => action);
    setShowAcordModal(true);
  };

  const handleAcordConfirm = async () => {
    if (!acordLicenseChecked) return;
    setAcordModalLoading(true);
    try {
      const res = await fetch(`${API_BASE}/api/acord/confirm-license`, { method: 'POST', headers: { 'Authorization': `Bearer ${token}` } });
      if (res.ok) {
        onUserUpdate({ ...user, acord_license_confirmed: true });
        setShowAcordModal(false);
        if (acordModalAction) acordModalAction();
      } else { setError('License confirmation failed. Please try again.'); }
    } catch { setError('Network error during license confirmation.'); }
    finally { setAcordModalLoading(false); }
  };

 const _doDownloadOne = async (formId) => {
    setLoading(true); setShowDownloadOverlay(true);
    try {
      const res = await fetch(`${API_BASE}/api/download-pdf/${sessionId}/${formId}`, { headers: { 'Authorization': `Bearer ${token}` } });
      if (res.status === 403) {
        const data = await res.json().catch(() => ({}));
        if (data.payment_locked) { setError('Account payment overdue. Please update your billing.'); return; }
        if (data.upgrade_required) { onShowUpgrade(); return; }
        setError(data.message || 'Download blocked'); return;
      }
      if (!res.ok) { setError('Download failed'); return; }
      const pkgStatus = res.headers.get('X-Package-Status') || '';
      const pkgMsg    = res.headers.get('X-Package-Message') || '';
      const blob = await res.blob();
      const url  = URL.createObjectURL(blob);
      const a    = document.createElement('a');
      a.href = url; a.download = `${formId}_Package.zip`;
      document.body.appendChild(a); a.click();
      document.body.removeChild(a); URL.revokeObjectURL(url);
      await refreshUser();
      if (pkgStatus) { setPkgStatusMsg(pkgMsg); setPkgStatusType(pkgStatus); setTimeout(() => setPkgStatusMsg(''), 12000); }
      setStep('success');
    } catch (err) { setError('Download failed: ' + err.message); }
    finally { setLoading(false); setShowDownloadOverlay(false); }
  };

  const handleDownloadOne = (formId) => gatedDownload(() => _doDownloadOne(formId));
  const handleDownloadAll = () => gatedDownload(() => _doDownloadAll());

 const _doDownloadAll = async () => {
    setLoading(true); setShowDownloadOverlay(true);
    try {
      const res = await fetch(`${API_BASE}/api/download-all/${sessionId}`, { headers: { 'Authorization': `Bearer ${token}` } });
      if (res.status === 403) {
        const data = await res.json().catch(() => ({}));
        if (data.payment_locked) { setError('Account payment overdue. Please update your billing.'); return; }
        if (data.upgrade_required) { onShowUpgrade(); return; }
        setError(data.message || 'Download blocked'); return;
      }
      if (!res.ok) { setError('Download failed'); return; }
      const pkgStatus = res.headers.get('X-Package-Status') || '';
      const pkgMsg    = res.headers.get('X-Package-Message') || '';
      const blob = await res.blob();
      const url  = URL.createObjectURL(blob);
      const a    = document.createElement('a');
      a.href = url; a.download = 'ACORD_Package_Acordly.zip';
      document.body.appendChild(a); a.click();
      document.body.removeChild(a); URL.revokeObjectURL(url);
      await refreshUser();
      if (pkgStatus) { setPkgStatusMsg(pkgMsg); setPkgStatusType(pkgStatus); setTimeout(() => setPkgStatusMsg(''), 12000); }
      setStep('success');
    } catch (err) { setError('Download failed: ' + err.message); }
    finally { setLoading(false); setShowDownloadOverlay(false); }
  };

  const refreshUser = async () => {
    const res = await fetch(`${API_BASE}/api/auth/me`, { headers: { 'Authorization': `Bearer ${token}` } });
    if (res.ok) { const data = await res.json(); onUserUpdate(data); }
  };

  const handleUpload = async () => {
    if (!files.length) { setError('Select at least one file'); return; }
    setLoading(true); setError(null); setShowUploadOverlay(true);
    const fd = new FormData();
    files.forEach(f => fd.append('files', f));
    try {
      const res  = await fetch(`${API_BASE}/api/upload-declaration`, { method: 'POST', headers: { 'Authorization': `Bearer ${token}` }, body: fd });
      const data = await res.json();
      if (res.status === 401) { setError('Session expired. Please sign in again.'); setTimeout(() => { localStorage.removeItem('acordly_token'); window.location.reload(); }, 2000); return; }
      if (res.status === 403) {
        const msg = data.detail || data.message || 'Access blocked.';
        if (msg.includes('suspended'))    setError('🚫 Your account is suspended due to non-payment. Please restore your billing to continue.');
        else if (msg.includes('archived')) setError('🗄️ Your account has been archived. Please contact support@acordly.ai to restore access.');
        else if (msg.includes('soft_locked') || msg.includes('soft-locked') || msg.includes('locked')) setError('🔒 Account Disabled — uploading is disabled. Please update your billing to restore access.');
        else setError(msg);
        return;
      }
      if (!data.success) {
        if (data.gate === 'tier1_fail') { setHardStops(data.missing_fields || []); setStep('stopped'); }
        else setError(data.message || 'Upload failed');
        return;
      }
      setSessionId(data.session_id);
      setDocSummary(data.doc_summary || []);
      setFlags(data.flags || {});
      setHardStops(data.hard_stops || []);
      setSoftStops(data.soft_stops || []);
      setTier2Score(data.tier2_score ?? null);
      setTier2Missing(data.tier2_missing || []);
      setRecommendations(data.recommendations || []);
      setAllAvailableForms(data.all_available_forms || []);
      const recIds = new Set((data.recommendations || []).map(r => r.form_id));
      setCheckedFormIds(recIds);
      setStep('recommendations');
    } catch (e) { setError('Upload failed: ' + e.message); }
    finally { setLoading(false); setShowUploadOverlay(false); }
  };

  const handleGenerateAll = async () => {
    const ids = Array.from(checkedFormIds);
    if (!ids.length) { setError('Select at least one form'); return; }
    setLoading(true); setError(null); setShowGenerateOverlay(true);
    try {
      const res  = await fetch(`${API_BASE}/api/select-forms-bulk`, {
        method: 'POST', headers: { 'Content-Type': 'application/json', 'Authorization': `Bearer ${token}` },
        body: JSON.stringify({ session_id: sessionId, form_ids: ids }),
      });
      const data = await res.json();
      if (res.status === 403) { setError('🔒 ' + (data.detail || data.message || 'Access blocked.') + ' Please update your billing to restore access.'); return; }
      if (!data.success) { setError('Form generation failed'); return; }
      setGeneratedForms(data.generated || {});
      setCrossIssues(data.cross_issues || []);
      const firstId = data.form_ids?.[0] || null;
      setActiveFormId(firstId);
      setStep('editor');
      const readyMap = {};
      (data.form_ids || []).forEach(fid => { readyMap[fid] = false; });
      setPdfLoading(readyMap);
    } catch (e) { setError('Generation failed: ' + e.message); }
    finally { setLoading(false); setShowGenerateOverlay(false); }
  };

  const formIdList = Object.keys(generatedForms);
  const activeIdx  = formIdList.indexOf(activeFormId);
  const goNext = () => { if (activeIdx < formIdList.length - 1) setActiveFormId(formIdList[activeIdx + 1]); };
  const goPrev = () => { if (activeIdx > 0) setActiveFormId(formIdList[activeIdx - 1]); };

  const toggleForm = (formId) => {
    setCheckedFormIds(prev => {
      const next = new Set(prev);
      if (next.has(formId)) next.delete(formId); else next.add(formId);
      return next;
    });
  };

  const recommendedIds = new Set(recommendations.map(r => r.form_id));
  const extraForms     = allAvailableForms.filter(f => !recommendedIds.has(f.form_id));
  const activeSqs      = activeFormId && generatedForms[activeFormId]?.sqs;

  // FIX Issue 4: compute soft buffer state for notification
  const pkgsUsed   = user?.packages_used  || 0;
  const pkgsLimit  = user?.packages_limit || 0;
  const softBuffer = user?.packages_soft_buffer || 0;
  const inSoftBuffer = user?.subscription_tier !== 'free' && pkgsLimit > 0 && pkgsUsed >= pkgsLimit && pkgsUsed < pkgsLimit + softBuffer;
  const inOverage    = user?.subscription_tier !== 'free' && pkgsLimit > 0 && pkgsUsed >= pkgsLimit + softBuffer;

  // Shared spinner for billing buttons in modal
  const BillingBtnSpinner = () => (
    <span style={{ width:11, height:11, border:'2px solid currentColor', borderTopColor:'transparent', borderRadius:'50%', display:'inline-block', animation:'spin 0.7s linear infinite', marginRight:4 }} />
  );

  return (
    <div className="modal-overlay">
      <div className="modal-content" onClick={e => e.stopPropagation()}>
        <button className="modal-close" onClick={onClose}>✕</button>
        <div className="modal-inner">

          {/* Staged overlays */}
          {showUploadOverlay   && <ProcessStageOverlay stages={['Reading your documents…', 'Extracting facts with AI…']} advanceAfter={3500} />}
          {showGenerateOverlay && <ProcessStageOverlay stages={[`Selecting ${checkedFormIds.size} form${checkedFormIds.size !== 1 ? 's' : ''}…`, 'Generating with AI…']} advanceAfter={3000} />}
          {showDownloadOverlay && <ProcessStageOverlay stages={['Preparing your form…', 'Packaging for download…']} advanceAfter={2000} />}

          {loading && !showUploadOverlay && !showGenerateOverlay && !showDownloadOverlay && (
            <div className="loading-overlay">
              <div className="loading-spinner" />
              <p className="loading-text">{processingStage || 'Processing...'}</p>
            </div>
          )}

          {user && user.subscription_tier === 'free' && step !== 'upload' && (
            <div className={`freemium-banner ${user.downloads_remaining === 0 ? 'freemium-depleted' : ''}`}>
              {user.downloads_remaining > 0 ? (
                <><span className="freemium-icon">🎉</span>
                  <span className="freemium-text">{user.downloads_remaining} free download{user.downloads_remaining > 1 ? 's' : ''} remaining</span></>
              ) : (
                <><span className="freemium-icon">🚀</span>
                  <span className="freemium-text">Free limit reached — upgrade to continue</span>
                  <button className="freemium-upgrade-btn" onClick={onShowUpgrade}>Upgrade Now</button></>
              )}
            </div>
          )}

    
          
          {inOverage && (
            <div style={{ background:'#fff7ed', border:'1px solid #fed7aa', borderRadius:8, padding:'9px 14px', fontSize:12, color:'#92400e', marginBottom:8, display:'flex', alignItems:'center', gap:8 }}>
              📋 <span>You're in overage territory — each additional download will be billed at your plan rate on your next invoice. No interruption to your service.</span>
            </div>
          )}

          {user && user.subscription_tier !== 'free' && (() => {
            const ps = user.payment_status;
            if (ps === 'archived')    return (
              <div className="payment-status-banner payment-status-archived">
                🗄️ Account archived — <a href="mailto:support@acordly.ai">Contact support</a> to restore.
              </div>
            );
            if (ps === 'suspended')   return (
              <div className="payment-status-banner payment-status-suspended">
                🚫 Account suspended — all form actions disabled.{' '}
                <button onClick={onOpenBillingPortal} disabled={billingPortalLoading} style={{ color:'inherit', fontWeight:700, textDecoration:'underline', background:'none', border:'none', cursor: billingPortalLoading ? 'wait' : 'pointer', padding:0, display:'inline-flex', alignItems:'center', gap:4 }}>
                  {billingPortalLoading && <BillingBtnSpinner />}Restore billing
                </button>
              </div>
            );
            if (ps === 'soft_locked') return (
              <div className="payment-status-banner payment-status-locked">
                🔒 Account Disabled — uploading &amp; generating is disabled. Please{' '}
                <button onClick={onOpenBillingPortal} disabled={billingPortalLoading} style={{ color:'inherit', fontWeight:700, textDecoration:'underline', background:'none', border:'none', cursor: billingPortalLoading ? 'wait' : 'pointer', padding:0, display:'inline-flex', alignItems:'center', gap:4 }}>
                  {billingPortalLoading && <BillingBtnSpinner />}update your billing
                </button>
                {' '}to restore access.
              </div>
            );
            if (ps === 'failed')      return (
              <div className="payment-status-banner payment-status-failed">
                ⚠️ Payment overdue — please{' '}
                <button onClick={onOpenBillingPortal} disabled={billingPortalLoading} style={{ color:'inherit', fontWeight:700, textDecoration:'underline', background:'none', border:'none', cursor: billingPortalLoading ? 'wait' : 'pointer', padding:0, display:'inline-flex', alignItems:'center', gap:4 }}>
                  {billingPortalLoading && <BillingBtnSpinner />}update your billing
                </button>
              </div>
            );
            return null;
          })()}

        {pkgStatusMsg && (
            <div className="overage-inline-notice" style={{
              background: pkgStatusType === 'overage' ? '#fefce8' : '#f0fdf4',
              borderColor: pkgStatusType === 'overage' ? '#fde047' : '#86efac',
              color: pkgStatusType === 'overage' ? '#713f12' : '#14532d',
            }}>
              <span>{pkgStatusType === 'overage' ? '💳' : '📦'}</span>
              <span>
                {pkgStatusMsg}
                {' '}<button onClick={() => setPkgStatusMsg('')} style={{ background:'none', border:'none', cursor:'pointer', color:'inherit', fontWeight:700, fontSize:12, textDecoration:'underline' }}>Dismiss</button>
              </span>
            </div>
          )}

          {error && (
            <div className="alert alert-error">
              <span>⚠️ {error}</span>
              <button className="alert-close" onClick={() => setError(null)}>✕</button>
            </div>
          )}

          {/* ── UPLOAD ── */}
          {step === 'upload' && (() => {
            const ps = user?.payment_status;
            const uploadBlocked = ps === 'soft_locked' || ps === 'suspended' || ps === 'archived';
            const blockMsg = ps === 'archived'    ? '🗄️ Account archived — contact support@acordly.ai to restore access.'
                           : ps === 'suspended'   ? '🚫 Account suspended — uploading is disabled. Restore billing to continue.'
                           : ps === 'soft_locked' ? '🔒 Account Disabled — uploading is disabled. Please update your billing to restore access.'
                           : null;
            return (
              <div className="modal-step">
                <div className="step-header">
                  <h2 className="step-title">Upload Documents</h2>
                  <p className="step-subtitle">Dec pages, loss runs, schedules, quotes — upload PDFs, images (JPG/PNG), or ZIP archives</p>
                </div>
                {uploadBlocked && <div className="upload-blocked-msg">{blockMsg}</div>}
                <div ref={dropRef} className={`upload-area ${dragging ? 'dragging' : ''} ${uploadBlocked ? 'upload-area-blocked' : ''}`}>
                  <div className="upload-icon">📁</div>
                  <input type="file" id="file-upload" accept=".pdf,.zip,.jpg,.jpeg,.png,.bmp,.tiff,.webp,application/pdf,application/zip,image/*" multiple disabled={uploadBlocked} onChange={e => setFiles(prev => [...prev, ...Array.from(e.target.files)])} className="file-input" />
                  <label htmlFor="file-upload" className="upload-label">Drag &amp; drop or <span className="upload-link">browse files</span></label>
                  <p className="upload-hint">PDFs, Images (JPG, PNG, BMP, TIFF) and ZIP archives supported</p>
                </div>
                {files.length > 0 && (
                  <div className="file-list">
                    {files.map((f, i) => (
                      <div key={i} className="file-chip">
                        <span className="file-icon">{f.name.endsWith('.zip') ? '📦' : f.type?.startsWith('image/') ? '🖼️' : '📄'}</span>
                        <span className="file-name">{f.name}</span>
                        <button className="file-remove" onClick={() => setFiles(prev => prev.filter((_,j) => j!==i))}>✕</button>
                      </div>
                    ))}
                  </div>
                )}
                <button className="btn btn-modal-primary btn-block" onClick={handleUpload} disabled={!files.length || loading || uploadBlocked}>
                  <span className="btn-icon">🚀</span>
                  {loading ? 'Analyzing...' : `Analyze ${files.length > 1 ? files.length + ' Files' : 'File'}`}
                </button>
              </div>
            );
          })()}

          {/* ── STOPPED ── */}
          {step === 'stopped' && (
            <div className="modal-step">
              <div className="stop-banner stop-hard">
                <div className="stop-icon">🚫</div>
                <h2 className="stop-title">Submission Blocked — Minimum Fields Missing</h2>
                <p className="stop-subtitle">ACORD 125 cannot be generated. Missing:</p>
              </div>
              <div className="stop-fields">
                {hardStops.map((f,i) => (<div key={i} className="stop-field-item"><span className="stop-field-icon">✗</span><span>{f}</span></div>))}
              </div>
              <p className="stop-advice">Upload documents that include these fields, then try again.</p>
              <button className="btn btn-modal-primary" onClick={reset}>← Upload New Documents</button>
            </div>
          )}

          {/* ── RECOMMENDATIONS ── */}
          {step === 'recommendations' && (
            <div className="modal-step modal-step-wide">
              <div className="step-header">
                <h2 className="step-title">Select Forms to Generate</h2>
                <p className="step-subtitle">All recommended forms are pre-selected. Uncheck any you don't need, then generate all at once.</p>
              </div>
              <div className="doc-summary">
                <div className="doc-summary-title">📂 Documents Processed</div>
                <div className="doc-chips">
                  {docSummary.map((d,i) => (
                    <div key={i} className={`doc-chip ${d.is_primary ? 'doc-primary' : ''}`}>
                      <span className="doc-type-badge">{d.doc_type.replace(/_/g,' ')}</span>
                      <span className="doc-filename">{d.filename}</span>
                      {d.is_primary && <span className="doc-primary-tag">Primary</span>}
                    </div>
                  ))}
                </div>
              </div>
              {hardStops.length > 0 && (
                <div className="stops-banner stops-hard">
                  <div className="stops-title">🚫 Hard Stops — Must Fix Before Submission</div>
                  {hardStops.map((s,i) => <div key={i} className="stop-item stop-item-hard">✗ {s}</div>)}
                </div>
              )}
              {softStops.length > 0 && (
                <div className="stops-banner stops-soft">
                  <div className="stops-title">⚠️ Warnings — Will Cap Your SQS Score</div>
                  {softStops.map((s,i) => <div key={i} className="stop-item stop-item-soft">⚠ {s}</div>)}
                </div>
              )}
              {tier2Score !== null && (
                <div className="tier2-bar">
                  <div className="tier2-header">
                    <span className="tier2-label">Underwriting Readiness</span>
                    <span className="tier2-score" style={{ color: barColor(tier2Score) }}>{tier2Score}%</span>
                  </div>
                  <div className="metric-bar"><div className="metric-fill" style={{ width:`${tier2Score}%`, background: barColor(tier2Score) }} /></div>
                  {tier2Missing.length > 0 && <div className="tier2-missing">Missing: {tier2Missing.join(' · ')}</div>}
                </div>
              )}
              <div className="form-selection-list">
                <div className="form-selection-header">
                  <span className="form-selection-title">Recommended Forms</span>
                  <span className="form-selection-hint">{checkedFormIds.size} selected</span>
                </div>
                {recommendations.map((rec, i) => (
                  <div key={rec.form_id} className={`form-select-row ${checkedFormIds.has(rec.form_id) ? 'form-row-checked' : ''}`}>
                    <label className="form-select-checkbox-label">
                      <input type="checkbox" checked={checkedFormIds.has(rec.form_id)} onChange={() => toggleForm(rec.form_id)} className="form-select-checkbox" />
                      <div className="form-select-info">
                        <div className="form-select-name"><span className="rec-rank">#{i+1}</span>{rec.form_name}</div>
                        <div className="form-select-meta">
                          <span className="confidence-badge">Match {((rec.confidence||0)*100).toFixed(0)}%</span>
                          <span className="form-select-reason">{rec.reason}</span>
                        </div>
                      </div>
                    </label>
                    <button className="btn-icon-only" title="Toggle" onClick={() => toggleForm(rec.form_id)}>{checkedFormIds.has(rec.form_id) ? '✓' : '+'}</button>
                  </div>
                ))}
              </div>
              {extraForms.length > 0 && (
                <div className="add-forms-section">
                  <button className="btn btn-modal-secondary btn-small" onClick={() => setShowAddForms(v => !v)}>
                    {showAddForms ? '▲ Hide' : '▼ Add more ACORD forms'} ({extraForms.length} available)
                  </button>
                  {showAddForms && (
                    <div className="extra-forms-list">
                      {extraForms.map(f => (
                        <div key={f.form_id} className={`form-select-row ${checkedFormIds.has(f.form_id) ? 'form-row-checked' : ''}`}>
                          <label className="form-select-checkbox-label">
                            <input type="checkbox" checked={checkedFormIds.has(f.form_id)} onChange={() => toggleForm(f.form_id)} className="form-select-checkbox" />
                            <div className="form-select-info">
                              <div className="form-select-name">{f.form_name}</div>
                              {f.description && <div className="form-select-reason">{f.description}</div>}
                            </div>
                          </label>
                        </div>
                      ))}
                    </div>
                  )}
                </div>
              )}
              <button className="btn btn-modal-primary btn-block btn-large" onClick={handleGenerateAll} disabled={loading || checkedFormIds.size === 0}>
                <span className="btn-icon">⚡</span>
                {loading ? 'Generating...' : `Generate ${checkedFormIds.size} Form${checkedFormIds.size !== 1 ? 's' : ''} Now`}
              </button>
              <button className="btn btn-modal-secondary" onClick={reset} style={{ marginBottom: '12px' }} > ← Start Over</button>
            </div>
          )}

          {/* ── EDITOR ── */}
          {step === 'editor' && (
            <div className="editor-layout">
              <div className="editor-sidebar" style={{ overflowY:'auto' }}>
                <div className="form-navigator">
                  <div className="form-nav-header">
                    <span className="form-nav-title">Generated Forms</span>
                    <span className="form-nav-count">{formIdList.length} form{formIdList.length !== 1 ? 's' : ''}</span>
                  </div>
                  <div className="form-nav-list">
                    {formIdList.map(fid => {
                      const fd = generatedForms[fid];
                      const sq = fd?.sqs;
                      return (
                        <div key={fid} className={`form-nav-item ${activeFormId === fid ? 'form-nav-active' : ''}`} onClick={() => setActiveFormId(fid)}>
                          <div className="form-nav-name">
                            {fd?.form_name || fid}
                            {signedForms.has(fid) && <span style={{ color:'#10b981', fontSize:11 }}> ✍</span>}
                            {pdfLoading[fid] && <span className="form-nav-loading"> ⏳</span>}
                            {!pdfLoading[fid] && <span className="form-nav-ready"> ✓</span>}
                          </div>
                          {sq && (
                            <div className="form-nav-meta">
                              <span className="form-nav-score" style={{ color: gradeColor(sq.grade) }}>{sq.sqs_score} {sq.grade}</span>
                              <span className={`form-nav-tier tier-${sq.tier_color}`}>{sq.tier}</span>
                            </div>
                          )}
                        </div>
                      );
                    })}
                  </div>
                  <div className="form-nav-arrows">
                    <button className="btn btn-modal-secondary btn-small" onClick={goPrev} disabled={activeIdx <= 0}>← Prev</button>
                    <span className="form-nav-pos">{activeIdx + 1} / {formIdList.length}</span>
                    <button className="btn btn-modal-secondary btn-small" onClick={goNext} disabled={activeIdx >= formIdList.length - 1}>Next →</button>
                  </div>
                </div>

                {activeSqs && (
                  <div className="sqs-display">
                    <div className="sqs-header">
                      <span className="sqs-label">SQS — {generatedForms[activeFormId]?.form_name}</span>
                      <div className="sqs-grade" style={{ background: gradeColor(activeSqs.grade) }}>{activeSqs.grade}</div>
                    </div>
                    <div className="sqs-score-row">
                      <span className="sqs-score-large" style={{ color: gradeColor(activeSqs.grade) }}>{activeSqs.sqs_score}</span>
                      <span className={`sqs-tier-badge tier-${activeSqs.tier_color}`}>{activeSqs.tier}</span>
                    </div>
                    {activeSqs.routing_decision && (
                      <div style={{
                        margin: '8px 0 12px 0', padding: '8px 12px', borderRadius: '6px',
                        fontSize: '12px', fontWeight: '600', textAlign: 'center',
                        background: { auto_quote:'#dcfce7', review:'#fef9c3', full_review:'#ffedd5', hold:'#fee2e2' }[activeSqs.routing_decision] || '#f1f5f9',
                        color: { auto_quote:'#166534', review:'#854d0e', full_review:'#9a3412', hold:'#991b1b' }[activeSqs.routing_decision] || '#374151',
                        border: `1px solid ${{ auto_quote:'#86efac', review:'#fde047', full_review:'#fdba74', hold:'#fca5a5' }[activeSqs.routing_decision] || '#e2e8f0'}`,
                      }}>
                        {{ auto_quote:'✅ Auto-Route to Quoting', review:'🔍 Low-Touch Underwriter Review', full_review:'📋 Full Underwriter Review Required', hold:'🚫 Hold — Remediation Required' }[activeSqs.routing_decision] || activeSqs.routing_decision}
                      </div>
                    )}
                    <div className="sqs-breakdown">
                      {Object.entries(activeSqs.breakdown || {}).map(([key, val]) => (
                        <div key={key} className="sqs-metric">
                          <div className="metric-header">
                            <span className="metric-name">{SQS_LABELS[key] || key}<span className="metric-weight"> ({SQS_WEIGHTS[key]||0}%)</span></span>
                            <span className="metric-value">{val}%</span>
                          </div>
                          <div className="metric-bar"><div className="metric-fill" style={{ width:`${val}%`, background: barColor(val) }} /></div>
                        </div>
                      ))}
                    </div>
                    {activeSqs.risk_drivers?.length > 0 && (
                      <div className="sqs-drivers">
                        <div className="drivers-title">⚡ Top Risk Drivers</div>
                        {activeSqs.risk_drivers.map((d,i) => (
                          <div key={i} className="driver-item">
                            <span className="driver-rank">#{i+1}</span>
                            <span className="driver-name">{d.component}</span>
                            <span className="driver-score" style={{ color: barColor(d.score) }}>{d.score}%</span>
                          </div>
                        ))}
                      </div>
                    )}
                    {activeSqs.issues?.length > 0 && (
                      <div className="sqs-alerts">
                        <div className="alerts-title">⚠️ Issues</div>
                        <ul className="alerts-list">{activeSqs.issues.map((s,i) => <li key={i}>{s}</li>)}</ul>
                      </div>
                    )}
                    {activeSqs.recommendations?.length > 0 && (
                      <div className="sqs-tips">
                        <div className="tips-title">💡 Remediation Steps</div>
                        <ul className="tips-list">{activeSqs.recommendations.map((s,i) => <li key={i}>{s}</li>)}</ul>
                      </div>
                    )}
                  </div>
                )}

                {crossIssues.length > 0 && (
                  <div className="cross-issues">
                    <div className="cross-title">🔗 Cross-Form Validation</div>
                    {crossIssues.map((iss,i) => (
                      <div key={i} className={`cross-item cross-${iss.type}`}>
                        {iss.type === 'hard_stop' ? '🚫' : '⚠️'} {iss.message}
                      </div>
                    ))}
                  </div>
                )}

                <div className="download-actions" style={{ paddingBottom: 16 }} >
                  <button
                    onClick={() => handleSendToEpic(activeFormId)}
                    disabled={!activeFormId || epicLoading}
                    style={{
                      display: 'flex', alignItems: 'center', justifyContent: 'center', gap: 6,
                      width: '100%', padding: '8px 14px', borderRadius: 9, marginBottom: 6,
                      border: epicSuccess ? '1px solid #22c55e' : '1px solid #2a3047',
                      background: epicSuccess ? 'rgba(34,197,94,0.08)' : '#0f172a',
                      color: epicSuccess ? '#22c55e' : '#94a3b8',
                      fontSize: 13, fontWeight: 600, cursor: epicLoading ? 'wait' : 'pointer',
                      fontFamily: 'inherit', transition: 'all 0.18s',
                      opacity: (!activeFormId || epicLoading) ? 0.55 : 1,
                    }}
                  >
                    {epicSuccess ? '✅ Sent to EPIC' : epicLoading
                      ? <><span style={{ width:12, height:12, border:'2px solid currentColor', borderTopColor:'transparent', borderRadius:'50%', display:'inline-block', animation:'spin 0.7s linear infinite' }} /> Sending...</>
                      : '🔗 Send to EPIC'}
                  </button>

                  <button className="btn btn-modal-primary btn-block" onClick={() => handleDownloadOne(activeFormId)} disabled={!activeFormId}>
                    ⬇ Download This Form
                  </button>

                  {formIdList.length > 1 && (
                    <button className="btn btn-modal-secondary btn-block" onClick={handleDownloadAll}>
                      📦 Download All Forms ({formIdList.length} forms)
                    </button>
                  )}

                  {/* FIX Issue 7: nudge Start Over up slightly */}
                  <button className="btn btn-modal-secondary btn-block" onClick={reset} style={{ marginBottom: 2 }}>
                    Start Over
                  </button>
                </div>
              </div>

              <div className="editor-main">
                <PDFJsViewer
                  key={activeFormId}
                  pdfUrl={`${API_BASE}/api/get-pdf/${sessionId}/${activeFormId}?token=${token}`}
                  formName={activeFormId ? (generatedForms[activeFormId]?.form_name || activeFormId) : ''}
                  onFormNav={{ goPrev, goNext, activeIdx, total: formIdList.length }}
                  sessionId={sessionId}
                  formId={activeFormId}
                  token={token}
                  savedSignature={savedSignature}
                  isSigned={signedForms.has(activeFormId)}
                  onSignApplied={(fid) => setSignedForms(prev => new Set([...prev, fid]))}
                  onOpenSignatureModal={onOpenSignatureModal}
                />
              </div>
            </div>
          )}

          {step === 'success' && (
            <div className="modal-step" style={{ textAlign:'center' }}>
              <div className="success-animation"><div className="success-icon">✓</div></div>
              <h2 className="success-title">Download Complete!</h2>
              <p className="success-message">Your filled ACORD forms have been downloaded.</p>
              {user && user.subscription_tier === 'free' && (
                <div className="success-remaining">
                  <p>You have <strong>{Math.max(0, user.downloads_remaining)}</strong> free download{user.downloads_remaining !== 1 ? 's' : ''} remaining</p>
                </div>
              )}
              <div className="success-actions">
                <button className="btn btn-modal-secondary" onClick={() => setStep('editor')}>← Go Back</button>
                <button className="btn btn-modal-primary" onClick={reset}>Upload Another Document</button>
              </div>
            </div>
          )}
        </div>
      </div>

      {showAcordModal && (
        <div className="modal-overlay">
          <div className="modal-content acord-license-modal" onClick={e => e.stopPropagation()}>
            <button className="modal-close" onClick={() => { setShowAcordModal(false); setAcordLicenseChecked(false); }}>✕</button>
            <div className="modal-inner">
              <div className="acord-license-icon">⚖️</div>
              <h2 className="acord-license-title">ACORD® License Confirmation</h2>
              <div className="acord-license-body">
                <p>ACORD® Forms are copyrighted material owned by ACORD Corporation and are licensed, not sold. By continuing, you confirm that you or your organization maintain a valid ACORD license permitting the use of these forms.</p>
                <p>If your organization does not currently have an ACORD license, you can obtain one{' '}
                  <a href="https://www.acord.org/forms-pages/forms-participation-programs/forms-end-user-licenses" target="_blank" rel="noopener noreferrer" className="acord-license-link">HERE</a>.
                </p>
              </div>
              <label
                className="acord-confirm-checkbox-label"
                style={{ display: 'flex', alignItems: 'center', gap: 10, cursor: 'pointer' }}
              >
                <input
                  type="checkbox"
                  checked={acordLicenseChecked}
                  onChange={e => setAcordLicenseChecked(e.target.checked)}
                  className="acord-confirm-checkbox"
                  style={{ flexShrink: 0, width: 16, height: 16, marginTop: 0, cursor: 'pointer' }}
                />
                <span>My organization holds a valid ACORD license.</span>
              </label>
              <button
                className="btn btn-modal-primary btn-block"
                onClick={handleAcordConfirm}
                disabled={!acordLicenseChecked || acordModalLoading}
              >
                {acordModalLoading ? (
                  <span style={{ display:'flex', alignItems:'center', justifyContent:'center', gap:8 }}>
                    <span style={{ width:14, height:14, border:'2px solid currentColor', borderTopColor:'transparent', borderRadius:'50%', display:'inline-block', animation:'spin 0.7s linear infinite' }} />
                    Confirming...
                  </span>
                ) : 'Confirm and Download'}
              </button>
              <div className="acord-stub-actions">
                <span className="acord-stub-label">Coming soon:</span>
                <button className="btn-stub" disabled title="Email — coming soon">✉ Email</button>
                <button className="btn-stub" disabled title="Share — coming soon">🔗 Share</button>
                <button className="btn-stub" disabled title="Fax — coming soon">📠 Fax</button>
              </div>
              <button className="btn btn-modal-secondary btn-block" onClick={() => { setShowAcordModal(false); setAcordLicenseChecked(false); }}>Cancel</button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

// ─── PDF.JS VIEWER ───────────────────────────────────────────────
const PDFJS_CDN    = 'https://cdnjs.cloudflare.com/ajax/libs/pdf.js/3.11.174/pdf.min.js';
const PDFJS_WORKER = 'https://cdnjs.cloudflare.com/ajax/libs/pdf.js/3.11.174/pdf.worker.min.js';

function PDFJsViewer({ pdfUrl, formName, onFormNav, sessionId, formId, token,
                       savedSignature, isSigned, onSignApplied, onOpenSignatureModal }) {

  const canvasRef              = useRef(null);
  const containerRef           = useRef(null);
  const renderTask             = useRef(null);
  const overlayRef             = useRef(null);
  const fieldValuesRef         = useRef({});
  const clearedSigFieldsRef    = useRef(new Set());
  const originalFieldValuesRef = useRef({});
  const pdfUrlRef              = useRef('');
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
  const [saveStatus,    setSaveStatus]    = useState('idle');
  const [fieldsLoaded,  setFieldsLoaded]  = useState(false);
  const [isSignedLocal, setIsSignedLocal] = useState(isSigned);

  const [showSignPrompt, setShowSignPrompt] = useState(null);
  const [applyingSign,   setApplyingSign]   = useState(false);
  const [applySigStage,  setApplySigStage]  = useState('idle');
  const [loadingStage,   setLoadingStage]   = useState('idle');

  const [clearingSignature, setClearingSignature] = useState(false);

  useEffect(() => { editModeRef.current = editMode; }, [editMode]);
  useEffect(() => { setIsSignedLocal(isSigned); }, [formId]); // eslint-disable-line

  useEffect(() => {
    if (window.pdfjsLib) { setPdfjsReady(true); return; }
    const s = document.createElement('script');
    s.src = PDFJS_CDN;
    s.onload = () => { window.pdfjsLib.GlobalWorkerOptions.workerSrc = PDFJS_WORKER; setPdfjsReady(true); };
    s.onerror = () => setLoadError(true);
    document.head.appendChild(s);
  }, []);

  useEffect(() => {
    setPageNum(1); setEditMode(false); setFields([]); setFieldValues({});
    fieldValuesRef.current         = {};
    originalFieldValuesRef.current = {};
    fieldsRef.current              = [];
    pageDimsRef.current            = [];
    editModeRef.current            = false;
    setPageDims([]); setFieldsLoaded(false);
    setSaveStatus('idle'); setPdfDoc(null); setTotalPages(0);
    setLoadError(false); setShowSignPrompt(null); setApplyingSign(false);
    setApplySigStage('idle'); setLoadingStage('idle');
    clearedSigFieldsRef.current    = new Set();
    manuallyRenderedRef.current    = { doc: null, pageNum: -1 };
  }, [formId]);

  useEffect(() => {
    if (!pdfjsReady || !pdfUrl) return;
    pdfUrlRef.current = pdfUrl;
    setLoadError(false);
    setLoadingStage('loading');
    const url = `${pdfUrl}&_r=${Date.now()}`;
    const loadingTask = window.pdfjsLib.getDocument(url);
    loadingTask.promise
      .then(doc => { setPdfDoc(doc); setTotalPages(doc.numPages); })
      .catch(err => {
        if (err?.name !== 'UnexpectedResponseException' && err?.message !== 'Worker was destroyed') {
          setLoadError(true); setLoadingStage('idle');
        }
      });
    return () => { try { loadingTask.destroy(); } catch (_) {} };
  }, [formId, pdfjsReady]); // eslint-disable-line

  useEffect(() => {
    if (!pdfDoc || !canvasRef.current) return;
    const mr = manuallyRenderedRef.current;
    if (mr.doc === pdfDoc && mr.pageNum === pageNum) {
      setLoadingStage('idle');
      return;
    }
    const render = async () => {
      setRendering(true);
      setLoadingStage(s => s === 'loading' ? 'rendering' : s);
      if (renderTask.current) { try { renderTask.current.cancel(); } catch (_) {} }
      try {
        const page      = await pdfDoc.getPage(pageNum);
        const canvas    = canvasRef.current; if (!canvas) return;
        const container = containerRef.current;
        const avail     = container ? container.clientWidth - 48 : 720;
        const baseVP    = page.getViewport({ scale: 1 });
        const scale     = Math.min(2.2, Math.max(1.0, avail / baseVP.width));
        const vp        = page.getViewport({ scale });
        canvas.width    = vp.width;
        canvas.height   = vp.height;
        const ctx = canvas.getContext('2d');
        ctx.fillStyle = '#fff';
        ctx.fillRect(0, 0, canvas.width, canvas.height);
        const task = page.render({ canvasContext: ctx, viewport: vp, renderInteractiveForms: false });
        renderTask.current = task;
        await task.promise;
        buildOverlay(scale, vp.width, vp.height, fieldValuesRef.current);
      } catch (e) {
        if (e?.name !== 'RenderingCancelledException') setLoadError(true);
      } finally {
        setRendering(false);
        setLoadingStage('idle');
      }
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
      .then(r => r.ok ? r.json() : null)
      .then(data => {
        if (!data?.success) return;
        const vals = {};
        (data.fields || []).forEach(f => { vals[f.name] = f.value || ''; });
        const fetchedFields   = data.fields    || [];
        const fetchedPageDims = data.page_dims || [];
        fieldsRef.current   = fetchedFields;
        pageDimsRef.current = fetchedPageDims;
        setFields(fetchedFields);
        setPageDims(fetchedPageDims);
        setFieldValues(vals);
        fieldValuesRef.current         = vals;
        originalFieldValuesRef.current = { ...vals };
        setFieldsLoaded(true);
      })
      .catch(err => {
        if (err?.name !== 'AbortError') console.error('Fields fetch error:', err);
      });
    return () => controller.abort();
  }, [sessionId, formId, token]); // eslint-disable-line

  const _isSigField = (name) => {
    const fn = (name || '').toLowerCase().replace(/[\s\-\.]/g, '_');
    const exclusions = ['date','designation','title','printed','print_name','name_of','countersign'];
    if (exclusions.some(ex => fn.includes(ex))) return false;
    const patterns = ['signature','producer_sig','insured_sig','authorized_sig',
      'applicant_sig','agent_sig','signedby','signed_by','sign_here',
      'producersig','agentsig','sig_producer','sig_insured','sig_agent'];
    return patterns.some(p => fn.includes(p));
  };

  const buildOverlay = (scale, canvasW, canvasH, liveValues) => {
    const overlay = overlayRef.current;
    if (!overlay) return;
    overlay.innerHTML = '';
    overlay.style.width  = canvasW + 'px';
    overlay.style.height = canvasH + 'px';
    const pd         = pageDimsRef.current[pageNum - 1];
    const pageHeight = pd ? pd.height : canvasH / scale;
    const pageFields = fieldsRef.current.filter(f => f.page === pageNum - 1);
    const currentEditMode = editModeRef.current;

    pageFields.forEach(field => {
      const { x, y, width, height } = field.rect;
      const cx = x * scale;
      const cy = (pageHeight - y - height) * scale;
      const cw = Math.max(width  * scale, 18);
      const ch = Math.max(height * scale, 14);
      const fs = Math.max(7, Math.min(ch * 0.58, 12));
      const val    = liveValues[field.name] ?? field.value ?? '';
      const isSigF = _isSigField(field.name);

      const wrap = document.createElement('div');
      wrap.style.cssText = `position:absolute;left:${cx}px;top:${cy}px;width:${cw}px;height:${ch}px;pointer-events:${currentEditMode ? 'all' : 'none'};`;

      if (field.type === 'checkbox') {
        const cb = document.createElement('input');
        cb.type    = 'checkbox';
        cb.checked = val === 'Yes' || val === 'true' || val === '1' || val === 'On';
        cb.disabled = !currentEditMode;
        cb.style.cssText = `position:absolute;top:50%;left:50%;transform:translate(-50%,-50%);width:${Math.min(ch*0.7,13)}px;height:${Math.min(ch*0.7,13)}px;margin:0;cursor:${currentEditMode?'pointer':'default'};accent-color:#4f7cff;opacity:${currentEditMode?1:0.7};`;
        cb.addEventListener('change', e => triggerSave(field.name, e.target.checked ? 'Yes' : 'Off'));
        wrap.appendChild(cb);

      } else if (isSigF) {
        const thisFieldCleared = clearedSigFieldsRef.current.has(field.name);
        const showClearBtn     = currentEditMode && isSignedLocal && !thisFieldCleared;
        const showTextInput    = currentEditMode && (!isSignedLocal || thisFieldCleared);

        if (showClearBtn) {
          // FIX Issue 6: simple ✕ in top-right corner instead of "Clear" text button
          const btn = document.createElement('button');
          btn.title = 'Remove stamped signature';
          btn.textContent = '✕';
          btn.style.cssText = `
            position:absolute;top:2px;right:2px;
            width:16px;height:16px;
            background:rgba(239,68,68,0.12);
            border:1px solid rgba(239,68,68,0.4);
            border-radius:50%;
            color:#ef4444;font-size:9px;font-weight:700;
            cursor:pointer;
            display:flex;align-items:center;justify-content:center;
            padding:0;line-height:1;font-family:inherit;
          `;
          btn.addEventListener('click', () => {
            triggerSave(field.name, '');
            clearedSigFieldsRef.current.add(field.name);
            wrap.innerHTML = '';
            const inp = document.createElement('input');
            inp.type = 'text'; inp.value = ''; inp.placeholder = 'Type name...';
            inp.style.cssText = `width:100%;height:100%;box-sizing:border-box;background:rgba(255,255,255,0.95);border:1px solid #ef4444;outline:none;border-radius:2px;font-size:${fs}px;font-family:Helvetica,Arial,sans-serif;color:#111;padding:1px 3px;cursor:text;`;
            inp.addEventListener('input', e => triggerSave(field.name, e.target.value));
            wrap.appendChild(inp);
            inp.focus();
          });
          wrap.appendChild(btn);
        } else if (showTextInput) {
          const inp = document.createElement('input');
          inp.type = 'text'; inp.value = val; inp.placeholder = 'Type name...';
          inp.style.cssText = `width:100%;height:100%;box-sizing:border-box;background:rgba(255,255,255,0.85);border:1px solid rgba(230,0,122,0.4);outline:none;border-radius:2px;font-size:${fs}px;font-family:Helvetica,Arial,sans-serif;color:#111;padding:1px 3px;cursor:text;`;
          inp.addEventListener('input', e => triggerSave(field.name, e.target.value));
          wrap.appendChild(inp);
        }

      } else if (currentEditMode) {
        const inp = document.createElement('input');
        inp.type        = 'text';
        inp.value       = val;
        inp.placeholder = '';
        inp.style.cssText = `width:100%;height:100%;box-sizing:border-box;background:rgba(255,255,255,0.95);border:none;outline:none;border-radius:2px;font-size:${fs}px;font-family:Helvetica,Arial,sans-serif;color:#111;padding:1px 3px;cursor:text;overflow:hidden;white-space:nowrap;`;
        inp.addEventListener('input', e => triggerSave(field.name, e.target.value));
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
    setApplySigStage('applying');
    try {
      const res = await fetch(`${API_BASE}/api/apply-signature/${sessionId}/${formId}`, {
        method: 'POST',
        headers: { 'Authorization': `Bearer ${token}` },
      });
      if (res.ok) {
        setApplySigStage('rendering');

        const freshUrl  = `${pdfUrlRef.current || pdfUrl}&_sig=${Date.now()}`;
        const newDoc    = await window.pdfjsLib.getDocument(freshUrl).promise;
        const page      = await newDoc.getPage(pageNum);
        const container = containerRef.current;
        const avail     = container ? container.clientWidth - 48 : 720;
        const baseVP    = page.getViewport({ scale: 1 });
        const scale     = Math.min(2.2, Math.max(1.0, avail / baseVP.width));
        const vp        = page.getViewport({ scale });

        const offscreen  = document.createElement('canvas');
        offscreen.width  = vp.width;
        offscreen.height = vp.height;
        const offCtx = offscreen.getContext('2d');
        offCtx.fillStyle = '#fff';
        offCtx.fillRect(0, 0, offscreen.width, offscreen.height);
        await page.render({ canvasContext: offCtx, viewport: vp, renderInteractiveForms: false }).promise;

        const canvas = canvasRef.current;
        if (canvas) {
          canvas.width  = offscreen.width;
          canvas.height = offscreen.height;
          canvas.getContext('2d').drawImage(offscreen, 0, 0);
        }

        manuallyRenderedRef.current = { doc: newDoc, pageNum };
        setPdfDoc(newDoc);
        setTotalPages(newDoc.numPages);
        setIsSignedLocal(true);
        clearedSigFieldsRef.current = new Set();
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
        console.error('Signature apply failed:', data.detail || 'Unknown error');
      }
    } catch(e) {
      console.error('Signature apply failed:', e);
    } finally {
      setApplyingSign(false);
      setApplySigStage('idle');
    }
  };

  const handleSignClick = () => {
    setShowSignPrompt(savedSignature ? 'use' : 'none');
  };

  const handleToggleEditMode = async () => {
    if (editMode) {
      if (window._saveTimer) { clearTimeout(window._saveTimer); }
      const allValues = fieldValuesRef.current;
      const hasActualChanges =
        Object.keys(allValues).some(k => allValues[k] !== (originalFieldValuesRef.current[k] ?? ''))
        || clearedSigFieldsRef.current.size > 0;

      if (hasActualChanges) {
        setSaveStatus('saving');
        try {
          const clearedSigFields = Array.from(clearedSigFieldsRef.current);
          const updates = {
            ...allValues,
            __form_id__: formId,
            __signed__: isSignedLocal ? '1' : '0',
            __cleared_sig_fields__: JSON.stringify(clearedSigFields),
          };
          const res = await fetch(`${API_BASE}/api/update-pdf`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json', 'Authorization': `Bearer ${token}` },
            body: JSON.stringify({ session_id: sessionId, field_updates: updates }),
          });
          if (res.ok) {
            setFieldValues({ ...allValues });
            originalFieldValuesRef.current = { ...allValues };
            clearedSigFieldsRef.current    = new Set();
            const allSigFields = fieldsRef.current.filter(f => _isSigField(f.name)).map(f => f.name);
            const allCleared   = allSigFields.length > 0 && allSigFields.every(n => clearedSigFields.includes(n));
            if (allCleared) setIsSignedLocal(false);
            setSaveStatus('generating');
            _loadPdfInBackground(allValues);
          } else {
            setSaveStatus('error');
          }
        } catch {
          setSaveStatus('error');
        }
      }
    }
    setEditMode(m => !m);
  };

  const _loadPdfInBackground = (currentValues) => {
    if (!pdfjsReady) return;
    const url = `${pdfUrlRef.current || pdfUrl}&_r=${Date.now()}`;
    window.pdfjsLib.getDocument(url).promise
      .then(async (newDoc) => {
        try {
          const page      = await newDoc.getPage(pageNum);
          const offscreen = document.createElement('canvas');
          const container = containerRef.current;
          const avail     = container ? container.clientWidth - 48 : 720;
          const baseVP    = page.getViewport({ scale: 1 });
          const scale     = Math.min(2.2, Math.max(1.0, avail / baseVP.width));
          const vp        = page.getViewport({ scale });
          offscreen.width  = vp.width;
          offscreen.height = vp.height;
          const ctx = offscreen.getContext('2d');
          await page.render({ canvasContext: ctx, viewport: vp, renderInteractiveForms: false }).promise;
          const visibleCanvas = canvasRef.current;
          if (visibleCanvas) {
            visibleCanvas.width  = offscreen.width;
            visibleCanvas.height = offscreen.height;
            visibleCanvas.getContext('2d').drawImage(offscreen, 0, 0);
          }
          manuallyRenderedRef.current = { doc: newDoc, pageNum };
          setPdfDoc(newDoc);
          setTotalPages(newDoc.numPages);
          const pd = pageDimsRef.current[pageNum - 1];
          if (pd) {
            const scale2 = Math.min(2.2, Math.max(1.0, (container ? container.clientWidth - 48 : 720) / pd.width));
            buildOverlay(scale2, offscreen.width, offscreen.height, currentValues);
          }
          setSaveStatus('saved');
          setTimeout(() => setSaveStatus('idle'), 2000);
        } catch (ex) {
          console.warn('Background render failed, falling back:', ex);
          setPdfDoc(newDoc);
          setTotalPages(newDoc.numPages);
          setSaveStatus('saved');
          setTimeout(() => setSaveStatus('idle'), 2000);
        }
      })
      .catch(() => { setSaveStatus('error'); });
  };

  const goPage = n => { if (n >= 1 && n <= totalPages) setPageNum(n); };
  const showSavedPill = saveStatus === 'saved';
  const showErrorPill = saveStatus === 'error';

  return (
    <div style={{ display:'flex', flexDirection:'column', height:'100%', background:'#181c27', borderRadius:8, overflow:'hidden' }}>

      {(saveStatus === 'saving' || saveStatus === 'generating') && (
        <SaveStageOverlay stage={saveStatus} />
      )}

      {applySigStage !== 'idle' && (
        <div className="upgrade-stage-overlay">
          <div className="upgrade-stage-spinner" />
          <div className="upgrade-stage-steps">
            <div className={`upgrade-stage-step ${applySigStage === 'applying' ? 'active' : 'done'}`}>
              <div className="upgrade-stage-dot" />
              {applySigStage === 'applying' ? 'Applying signature…' : '✓ Applying signature'}
            </div>
            <div className={`upgrade-stage-step ${applySigStage === 'rendering' ? 'active' : ''}`}>
              <div className="upgrade-stage-dot" />
              Generating signed form…
            </div>
          </div>
        </div>
      )}

      {loadingStage !== 'idle' && (
        <div className="upgrade-stage-overlay">
          <div className="upgrade-stage-spinner" />
          <div className="upgrade-stage-steps">
            <div className={`upgrade-stage-step ${loadingStage === 'loading' ? 'active' : 'done'}`}>
              <div className="upgrade-stage-dot" />
              {loadingStage === 'loading' ? 'Loading form…' : '✓ Loading form'}
            </div>
            <div className={`upgrade-stage-step ${loadingStage === 'rendering' ? 'active' : ''}`}>
              <div className="upgrade-stage-dot" />
              Rendering preview…
            </div>
          </div>
        </div>
      )}

      {showSignPrompt === 'use' && (
        <UseSignaturePrompt
          signature={savedSignature}
          onApply={handleApplySignature}
          onManage={() => { setShowSignPrompt(null); onOpenSignatureModal(); }}
          onClose={() => setShowSignPrompt(null)}
        />
      )}
      {showSignPrompt === 'none' && (
        <NoSignaturePrompt
          onSetup={() => { setShowSignPrompt(null); onOpenSignatureModal(); }}
          onClose={() => setShowSignPrompt(null)}
        />
      )}

      {/* ── Toolbar ── */}
      <div style={{ display:'flex', alignItems:'center', justifyContent:'space-between', padding:'8px 14px', background:'#1e2436', borderBottom:'1px solid #2a3047', flexShrink:0, gap:8, flexWrap:'wrap' }}>
        <span style={{ color:'#e8eaf2', fontSize:13, fontWeight:600, overflow:'hidden', textOverflow:'ellipsis', whiteSpace:'nowrap', maxWidth:'40%' }}>
          📄 {formName}
        </span>
        <div style={{ display:'flex', alignItems:'center', gap:6, flexWrap:'wrap' }}>

          {showSavedPill && (
            <span style={{ fontSize:11, fontWeight:700, color:'#22c55e' }}>✓ Saved</span>
          )}
          {showErrorPill && (
            <span style={{ fontSize:11, fontWeight:700, color:'#ef4444' }}>⚠ Save failed</span>
          )}

          <button
            onClick={handleToggleEditMode}
            disabled={saveStatus === 'saving' || saveStatus === 'generating'}
            style={{
              display:'flex', alignItems:'center', gap:4,
              padding:'4px 10px', borderRadius:6,
              border:`1px solid ${editMode ? '#4f7cff' : '#2a3047'}`,
              background: editMode ? 'rgba(79,124,255,0.15)' : '#252a3d',
              color: editMode ? '#4f7cff' : '#8b93b0',
              fontSize:12, fontWeight:600,
              cursor: (saveStatus === 'saving' || saveStatus === 'generating') ? 'wait' : 'pointer',
              fontFamily:'inherit',
              opacity: (saveStatus === 'saving' || saveStatus === 'generating') ? 0.7 : 1,
            }}
          >
            ✏️ {editMode ? 'Done Editing' : 'Edit'}
          </button>

          <button
            onClick={handleSignClick}
            disabled={applyingSign}
            title={isSignedLocal ? 'Signature applied' : savedSignature ? 'Apply your saved signature' : 'Set up a signature'}
            style={{
              display:'flex', alignItems:'center', gap:4,
              padding:'4px 10px', borderRadius:6,
              border:`1px solid ${isSignedLocal ? '#10b981' : 'rgba(230,0,122,0.4)'}`,
              background: isSignedLocal ? 'rgba(16,185,129,0.1)' : 'rgba(230,0,122,0.08)',
              color: isSignedLocal ? '#10b981' : '#e6007a',
              fontSize:12, fontWeight:600,
              cursor: applyingSign ? 'wait' : 'pointer',
              fontFamily:'inherit', transition:'all 0.2s',
              opacity: applyingSign ? 0.7 : 1,
            }}
          >
            {applyingSign
              ? <><span style={{ width:10, height:10, border:'2px solid currentColor', borderTopColor:'transparent', borderRadius:'50%', display:'inline-block', animation:'spin 0.7s linear infinite' }} /> Signing…</>
              : isSignedLocal ? '✓ Signed' : '✍ Sign'
            }
          </button>

          {rendering && <span style={{ color:'#4f7cff', fontSize:11 }}>Rendering…</span>}

          <div style={{ display:'flex', alignItems:'center', gap:4 }}>
            <button onClick={() => goPage(pageNum - 1)} disabled={pageNum <= 1 || rendering}
              style={{ width:28, height:28, borderRadius:6, border:'1px solid #2a3047', background:'#252a3d', color:'#e8eaf2', cursor:'pointer', fontSize:16, display:'flex', alignItems:'center', justifyContent:'center' }}>‹</button>
            <span style={{ color:'#e8eaf2', fontSize:12, fontWeight:700, minWidth:56, textAlign:'center', background:'#2a3047', padding:'3px 8px', borderRadius:5 }}>
              {totalPages ? `Page ${pageNum} / ${totalPages}` : '—'}
            </span>
            <button onClick={() => goPage(pageNum + 1)} disabled={pageNum >= totalPages || rendering}
              style={{ width:28, height:28, borderRadius:6, border:'1px solid #2a3047', background:'#252a3d', color:'#e8eaf2', cursor:'pointer', fontSize:16, display:'flex', alignItems:'center', justifyContent:'center' }}>›</button>
          </div>

          {onFormNav?.total > 1 && (<>
            <div style={{ width:1, height:18, background:'#2a3047', margin:'0 2px' }} />
            <button onClick={onFormNav.goPrev} disabled={onFormNav.activeIdx <= 0}
              style={{ width:28, height:28, borderRadius:6, border:'1px solid #2a3047', background:'#252a3d', color:'#e8eaf2', cursor:'pointer', fontSize:13, display:'flex', alignItems:'center', justifyContent:'center' }}>«</button>
            <span style={{ color:'#4f7cff', fontSize:11, fontWeight:600 }}>
              Form {onFormNav.activeIdx + 1}/{onFormNav.total}
            </span>
            <button onClick={onFormNav.goNext} disabled={onFormNav.activeIdx >= onFormNav.total - 1}
              style={{ width:28, height:28, borderRadius:6, border:'1px solid #2a3047', background:'#252a3d', color:'#e8eaf2', cursor:'pointer', fontSize:13, display:'flex', alignItems:'center', justifyContent:'center' }}>»</button>
          </>)}
        </div>
      </div>

      {editMode && (
        <div style={{ padding:'3px 14px', background:'rgba(79,124,255,0.08)', borderBottom:'1px solid rgba(79,124,255,0.15)', color:'#4f7cff', fontSize:11 }}>
          ✏️ Click any field to edit — click Done Editing to save
        </div>
      )}

      <div ref={containerRef} style={{ flex:1, overflow:'hidden', display:'flex', justifyContent:'center', alignItems:'flex-start', padding:24, background:'#252a3d', minHeight:0 }}>
        {loadError ? (
          <div style={{ color:'#6b7899', textAlign:'center', marginTop:60 }}>⚠️ Could not load PDF preview.</div>
        ) : !pdfDoc ? (
          <div style={{ color:'#6b7899', textAlign:'center', marginTop:60 }}>
            <div className="loading-spinner" style={{ margin:'0 auto 12px' }} />Loading…
          </div>
        ) : (
          <div style={{ position:'relative', display:'inline-block', lineHeight:0, boxShadow:'0 8px 40px rgba(0,0,0,0.6)', borderRadius:2 }}>
            <canvas ref={canvasRef} style={{ display:'block', maxWidth:'100%' }} />
            <div ref={overlayRef} style={{ position:'absolute', top:0, left:0, pointerEvents: editMode ? 'all' : 'none' }} />
          </div>
        )}
      </div>
    </div>
  );
}

// ─── UPGRADE MODAL ───────────────────────────────────────────────
function UpgradeModal({ token, user, onClose, onError }) {
  const [billing, setBilling]         = useState('annual');
  const [loadingPlan, setLoadingPlan] = useState(null);

  const plans = [
    {
      id: 'essentials',
      name: 'Essentials',
      monthly: 129, annual: 99,
      packages: 100,
      overage: '$1.50/package',
      features: [
        'All core ACORD forms',
        'SQS scoring & routing',
        'Cross-form validation',
        'Email support',
      ],
      cta: 'Get Essentials',
      highlight: false,
    },
    {
      id: 'professional',
      name: 'Professional',
      monthly: 449, annual: 399,
      packages: 400,
      overage: '$1.25/package',
      features: [
        'All Essentials features',
        'Priority support',
        'Advanced reporting & insights',
        'Team collaboration tools',
        'Dedicated onboarding',
      ],
      cta: 'Get Professional',
      highlight: true,
    },
    {
      id: 'enterprise',
      name: 'Enterprise',
      monthly: 1199, annual: 1199,
      packages: 'Custom',
      overage: 'Custom',
      features: [
        'All Professional features',
        'Dedicated account manager',
        'SLA guarantees',
        'On-premise deployment',
      ],
      cta: 'Contact Sales',
      highlight: false,
    },
  ];

  const handleSelect = async (planId) => {
    if (planId === 'enterprise') {
      window.location.href = 'mailto:sales@acordly.ai?subject=Enterprise Plan Inquiry';
      return;
    }
    setLoadingPlan(planId);
    try {
      const res  = await fetch(`${API_BASE}/api/stripe/create-checkout`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', 'Authorization': `Bearer ${token}` },
        body: JSON.stringify({ plan: planId, billing_cycle: billing }),
      });
      const data = await res.json();
      if (data.checkout_url) {
        window.location.href = data.checkout_url;
      } else {
        setLoadingPlan(null);
        onError(data.detail || 'Failed to start checkout. Please try again.');
      }
    } catch {
      setLoadingPlan(null);
      onError('Network error. Please try again.');
    }
  };

  return (
    <div className="modal-overlay">
      <div className="modal-content upgrade-modal upgrade-modal-wide" onClick={e => e.stopPropagation()}>
        <button className="modal-close" onClick={onClose} disabled={!!loadingPlan}>✕</button>
        <div className="modal-inner">
          <div className="upgrade-icon">🚀</div>
          <h2 className="upgrade-title">Choose Your Plan</h2>
          {user?.downloads_remaining <= 0 && (
            <p className="upgrade-message">You've used all 3 free downloads. Upgrade to continue.</p>
          )}

          <div className="billing-toggle">
            <button className={`billing-option ${billing === 'monthly' ? 'billing-active' : ''}`} onClick={() => setBilling('monthly')} disabled={!!loadingPlan}>Monthly</button>
            <button className={`billing-option ${billing === 'annual' ? 'billing-active' : ''}`} onClick={() => setBilling('annual')} disabled={!!loadingPlan}>Annual <span className="billing-save">Save ~23%</span></button>
          </div>

          <div className="plan-cards">
            {plans.map(plan => {
              const isThisLoading = loadingPlan === plan.id;
              const anyLoading    = !!loadingPlan;
              const isEnterprise  = plan.id === 'enterprise';

              return (
                <div key={plan.id} className={`plan-card ${plan.highlight ? 'plan-card-highlight' : ''}`}>
                  {plan.highlight && <div className="plan-popular">Most Popular</div>}
                  <div className="plan-name">{plan.name}</div>
                  <div className="plan-price">
                    {isEnterprise ? (
                      <span className="plan-price-custom">from $1,199<span style={{ fontSize:14, fontWeight:400, color:'#64748b' }}>/mo</span></span>
                    ) : (
                      <>
                        <span className="plan-price-amount">${billing === 'annual' ? plan.annual : plan.monthly}</span>
                        <span className="plan-price-period">/mo</span>
                      </>
                    )}
                  </div>
                  {isEnterprise ? (
                    <div className="plan-price-sub">Volume-based pricing, no per-user fees</div>
                  ) : billing === 'annual' ? (
                    <div className="plan-billed-note">(billed annually)</div>
                  ) : null}
                  <div className="plan-packages">{plan.packages} packages/mo</div>
                  <div className="plan-overage">Overage: {plan.overage}</div>
                  <ul className="plan-features">
                    {plan.features.map((f, i) => <li key={i}>✓ {f}</li>)}
                  </ul>
                  <button
                    className={`btn btn-block ${plan.highlight ? 'btn-modal-primary' : 'btn-modal-secondary'}`}
                    onClick={() => handleSelect(plan.id)}
                    disabled={anyLoading}
                    style={{ opacity: anyLoading && !isThisLoading ? 0.5 : 1 }}
                  >
                    {isThisLoading ? (
                      <span style={{ display:'flex', alignItems:'center', justifyContent:'center', gap:8 }}>
                        <span style={{ width:14, height:14, border:'2px solid currentColor', borderTopColor:'transparent', borderRadius:'50%', display:'inline-block', animation:'spin 0.7s linear infinite' }} />
                        Opening cart…
                      </span>
                    ) : plan.cta}
                  </button>
                </div>
              );
            })}
          </div>
        </div>
      </div>
    </div>
  );
}

// ─── COMPLETE PROFILE MODAL ──────────────────────────────────────
function CompleteProfileModal({ token, user, onComplete }) {
  const [orgName, setOrgName]                 = useState('');
  const [disclaimerChecked, setDisclaimerChecked] = useState(false);
  const [error, setError]                     = useState('');
  const [loading, setLoading]                 = useState(false);

  const handleSubmit = async (e) => {
    e.preventDefault(); setError(''); setLoading(true);
    if (!orgName.trim()) { setError('Organization or agency name is required.'); setLoading(false); return; }
    if (!disclaimerChecked) { setError('You must accept the ACORD disclaimer to continue.'); setLoading(false); return; }
    try {
      const res  = await fetch(`${API_BASE}/api/auth/complete-profile`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', 'Authorization': `Bearer ${token}` },
        body: JSON.stringify({ organization_name: orgName.trim(), acord_disclaimer_accepted: true })
      });
      const data = await res.json();
      if (res.ok && data.success) { onComplete({ ...user, organization_name: orgName.trim(), acord_disclaimer_accepted: true }); }
      else { setError(data.detail || data.message || 'Failed to save profile. Please try again.'); }
    } catch { setError('Network error. Please try again.'); }
    finally { setLoading(false); }
  };

  return (
    <div className="modal-overlay">
      <div className="modal-content auth-modal" onClick={e => e.stopPropagation()}>
        <div className="modal-inner">
          <div className="auth-header">
            <h2 className="step-title">Complete Your Profile</h2>
            <p className="step-subtitle">One more step before you get started. We need a couple of details to keep your account ACORD-compliant.</p>
          </div>
          {error && (<div className="alert alert-error"><span>⚠️ {error}</span><button className="alert-close" onClick={() => setError('')}>✕</button></div>)}
          <form onSubmit={handleSubmit} className="auth-form">
            <div className="form-group">
              <label>Organization / Agency Name <span className="field-required">*</span></label>
              <input type="text" value={orgName} onChange={e => setOrgName(e.target.value)} placeholder="Smith Insurance Agency LLC" required className="form-input" autoFocus />
              <span style={{ fontSize:'12px', color:'#64748b', marginTop:'4px', display:'block' }}>The legal name of the agency or organization that holds your ACORD license.</span>
            </div>
            <div className="acord-disclaimer-box">
              <label className="acord-disclaimer-label">
                <input type="checkbox" checked={disclaimerChecked} onChange={e => setDisclaimerChecked(e.target.checked)} className="acord-disclaimer-checkbox" />
                <span>By continuing, you acknowledge that <strong>ACORD® Forms require a separate license from ACORD Corporation</strong> and agree to obtain any required license before exporting or distributing those forms.</span>
              </label>
            </div>
            <button type="submit" className="btn btn-modal-primary btn-block" disabled={loading || !disclaimerChecked || !orgName.trim()}>
              {loading ? 'Saving...' : 'Save and Continue →'}
            </button>
          </form>
          <p style={{ fontSize:'11px', color:'#94a3b8', textAlign:'center', marginTop:'12px' }}>Signed in as {user?.email}</p>
        </div>
      </div>
    </div>
  );
}

export default App;