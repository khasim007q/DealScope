import { useEffect, useRef, useState } from "react";
import { api } from "../api/client";
import { useAsync } from "../lib/hooks";

export function SystemsIndicator() {
  const { data, error, loading } = useAsync(() => api.status());
  const [open, setOpen] = useState(false);
  const wrapRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    const onDown = (e: MouseEvent) => {
      if (wrapRef.current && !wrapRef.current.contains(e.target as Node)) setOpen(false);
    };
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") setOpen(false);
    };
    document.addEventListener("mousedown", onDown);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", onDown);
      document.removeEventListener("keydown", onKey);
    };
  }, [open]);

  const connected = data ? data.providers.filter((p) => p.connected).length : 0;
  const total = data ? data.providers.length : 0;
  const summary = loading
    ? "Checking systems"
    : error || !data
      ? "Systems unavailable"
      : `Systems: ${connected} of ${total} connected`;

  return (
    <div className="systems" ref={wrapRef}>
      <button
        type="button"
        className="systems-btn"
        aria-expanded={open}
        aria-controls="systems-panel"
        onClick={() => setOpen((o) => !o)}
      >
        <span className="dots" aria-hidden="true">
          {data?.providers.map((p) => (
            <span key={p.key} className={`dot ${p.connected ? "on" : "off"}`} />
          ))}
        </span>
        <span>{summary}</span>
      </button>
      {open ? (
        <div className="systems-panel" id="systems-panel" role="region" aria-label="System status">
          <h2>Connected systems</h2>
          {error ? <p className="error-text">{error}</p> : null}
          {data?.providers.map((p) => (
            <div className="system-row" key={p.key}>
              <span className={`dot ${p.connected ? "on" : "off"}`} aria-hidden="true" />
              <div>
                <div className="system-label">
                  {p.label} <span className="sr-only">:</span>
                  <span className="muted small"> - {p.connected ? "Connected" : "Not connected"}</span>
                </div>
                <div className="system-detail">{p.detail}</div>
              </div>
            </div>
          ))}
          {data ? (
            <p className="small muted" style={{ marginTop: 10, marginBottom: 0 }}>
              {data.live_available
                ? "Live investigations are available."
                : "Live investigations are unavailable until company data is connected. Demo data still works."}
            </p>
          ) : null}
        </div>
      ) : null}
    </div>
  );
}
