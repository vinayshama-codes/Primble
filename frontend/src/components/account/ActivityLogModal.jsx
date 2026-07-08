import { useState, useEffect, useRef } from "react";
import { getActivityLog } from "../../api/activityApi";

// Event type -> display config. Dot colors stay within the app's palette.
const EVENT_META = {
  forms_generated:           { title: "Forms generated",        dot: "#64748b" },
  sqs_scored:                { title: "Submission scored",       dot: "#8b5cf6" },
  questionnaire_sent:        { title: "Questionnaire sent",      dot: "#4f7cff" },
  questionnaire_opened:      { title: "Questionnaire opened",    dot: "#4f7cff" },
  questionnaire_in_progress: { title: "Client answering",       dot: "#4f7cff" },
  questionnaire_submitted:   { title: "Questionnaire submitted", dot: "#16a34a" },
  answers_applied:           { title: "Answers applied to forms", dot: "#16a34a" },
  reminder_sent:             { title: "Reminder sent",           dot: "#d97706" },
  download:                  { title: "Package downloaded",      dot: "#0891b2" },
};

function detailFor(ev) {
  const d = ev.event_data || {};
  switch (ev.event_type) {
    case "forms_generated":
      return d.form_count ? `${d.form_count} form${d.form_count !== 1 ? "s" : ""} generated` : "";
    case "sqs_scored":
      return d.score != null ? `Score ${d.score}${d.tier ? ` (${d.tier})` : ""}` : "";
    case "questionnaire_sent":
      return `${d.client_first ? `Sent to ${d.client_first}` : "Sent to client"}${d.question_count ? ` - ${d.question_count} question${d.question_count !== 1 ? "s" : ""}` : ""}`;
    case "questionnaire_opened":
      return d.client_first ? `${d.client_first} opened the questionnaire` : "Client opened the questionnaire";
    case "questionnaire_in_progress":
      return d.client_first ? `${d.client_first} started answering` : "Client started answering";
    case "questionnaire_submitted":
      return `${d.client_first ? `${d.client_first} submitted` : "Client submitted"}${d.fields ? ` ${d.fields} answer${d.fields !== 1 ? "s" : ""}` : ""}`;
    case "answers_applied":
      return `${d.fields_updated || 0} field${(d.fields_updated || 0) !== 1 ? "s" : ""} updated${d.scores_updated ? ", scores refreshed" : ""}`;
    case "reminder_sent":
      return `${d.reminder_count ? `Reminder #${d.reminder_count}` : "Reminder"}${d.client_first ? ` to ${d.client_first}` : ""}`;
    case "download":
      return d.kind === "all"
        ? `${d.form_count || "All"} forms downloaded`
        : (d.form_name || d.form_id || "Form downloaded");
    default:
      return "";
  }
}

// Collapse consecutive events that are identical (same type + same detail text)
// into a single row with a count. Guards the display against any repeated
// autosave-style emissions so the log stays readable.
function collapseEvents(evs) {
  const out = [];
  for (const ev of evs) {
    const detail = detailFor(ev);
    const last = out[out.length - 1];
    if (last && last.ev.event_type === ev.event_type && last.detail === detail) {
      last.count += 1;
      last.ev = ev; // keep the most recent timestamp
    } else {
      out.push({ ev, detail, count: 1 });
    }
  }
  return out;
}

function fmt(iso) {
  if (!iso) return "";
  const dt = new Date(iso);
  if (isNaN(dt.getTime())) return "";
  return dt.toLocaleString("en-US", { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" });
}

export default function ActivityLogModal({ onClose }) {
  const [events, setEvents]   = useState([]);
  const [loading, setLoading] = useState(true);
  const firstLoad = useRef(true);

  useEffect(() => {
    let alive = true;
    const load = async () => {
      const { ok, events } = await getActivityLog();
      if (!alive) return;
      if (ok) setEvents(events);
      if (firstLoad.current) { setLoading(false); firstLoad.current = false; }
    };
    load();
    // Poll while open so the log keeps updating as activity happens.
    const t = setInterval(load, 20000);
    return () => { alive = false; clearInterval(t); };
  }, []);

  // Group by package (session_id), ordered by most recent activity. Events
  // within a package read chronologically (oldest first) like a timeline.
  const groups = (() => {
    const map = new Map();
    for (const ev of events) {
      const key = ev.session_id || `__no_session__${ev.id}`;
      if (!map.has(key)) map.set(key, { key, label: "", events: [] });
      const g = map.get(key);
      g.events.push(ev);
      if (!g.label && ev.package_label) g.label = ev.package_label;
    }
    const arr = Array.from(map.values());
    for (const g of arr) g.events.reverse(); // API is DESC; show ascending
    // arr preserves first-seen (newest) order because events is DESC.
    return arr;
  })();

  return (
    <div className="modal-overlay" onClick={(e) => { if (e.target === e.currentTarget) onClose(); }}>
      <div className="modal-content" style={{ maxWidth: 560 }} onClick={(e) => e.stopPropagation()}>
        <button className="modal-close" onClick={onClose}>✕</button>
        <div className="modal-inner">
          <h2 className="step-title" style={{ marginBottom: 6 }}>Activity Log</h2>
          <p className="step-subtitle" style={{ marginBottom: 20 }}>
            Recent activity across your packages. Updates automatically.
          </p>

          {loading ? (
            <div style={{ display: "flex", alignItems: "center", justifyContent: "center", padding: "40px 0", color: "#94a3b8", gap: 10 }}>
              <span style={{ width: 16, height: 16, border: "2px solid #cbd5e1", borderTopColor: "transparent", borderRadius: "50%", display: "inline-block", animation: "spin 0.7s linear infinite" }} />
              Loading activity…
            </div>
          ) : groups.length === 0 ? (
            <div style={{ textAlign: "center", padding: "40px 16px", color: "#94a3b8", fontSize: 14 }}>
              No activity yet. Generate forms or send a questionnaire to get started.
            </div>
          ) : (
            <div style={{ maxHeight: "62vh", overflowY: "auto", display: "flex", flexDirection: "column", gap: 16 }}>
              {groups.map((g) => (
                <div key={g.key} style={{ background: "#f8fafc", border: "1px solid #e2e8f0", borderRadius: 10, padding: "12px 14px" }}>
                  <div style={{ fontSize: 11, fontWeight: 700, color: "#94a3b8", letterSpacing: "0.05em", textTransform: "uppercase", marginBottom: 10 }}>
                    {g.label || "Package"}
                  </div>
                  <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
                    {collapseEvents(g.events).map(({ ev, detail, count }) => {
                      const meta = EVENT_META[ev.event_type] || { title: ev.event_type, dot: "#94a3b8" };
                      return (
                        <div key={ev.id} style={{ display: "flex", alignItems: "flex-start", gap: 10 }}>
                          <span style={{ width: 9, height: 9, borderRadius: "50%", background: meta.dot, marginTop: 4, flexShrink: 0 }} />
                          <div style={{ minWidth: 0, flex: 1 }}>
                            <div style={{ fontSize: 13, fontWeight: 600, color: "#1e293b" }}>
                              {meta.title}{count > 1 ? ` · ${count}×` : ""}
                            </div>
                            {detail && <div style={{ fontSize: 12, color: "#64748b", marginTop: 1 }}>{detail}</div>}
                          </div>
                          <span style={{ fontSize: 11, color: "#94a3b8", flexShrink: 0, whiteSpace: "nowrap" }}>{fmt(ev.created_at)}</span>
                        </div>
                      );
                    })}
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
