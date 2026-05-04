import { Component } from "react";

export default class ErrorBoundary extends Component {
  constructor(props) { super(props); this.state = { error: null }; }
  static getDerivedStateFromError(error) { return { error }; }
  render() {
    if (this.state.error) {
      return (
        <div style={{ maxWidth: 480, margin: "80px auto", padding: "32px 24px", textAlign: "center", fontFamily: "sans-serif" }}>
          <div style={{ fontSize: 48, marginBottom: 16 }}>⚠️</div>
          <h2 style={{ fontSize: 20, fontWeight: 700, color: "#dc2626", marginBottom: 12 }}>Something went wrong</h2>
          <p style={{ fontSize: 14, color: "#64748b", marginBottom: 24 }}>{this.state.error?.message || "An unexpected error occurred."}</p>
          <button onClick={() => { this.setState({ error: null }); window.location.reload(); }}
            style={{ padding: "10px 24px", background: "#e6007a", color: "#fff", border: "none", borderRadius: 8, fontSize: 14, fontWeight: 600, cursor: "pointer" }}>
            Reload Page
          </button>
        </div>
      );
    }
    return this.props.children;
  }
}
