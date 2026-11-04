import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { api, errorMessage } from "../api/client";
import type { CaseView } from "../api/types";
import { formatDateTime } from "../lib/format";
import { Dateline, Disclosure, Icon, ModeBadge, StatusPill } from "./ui";

interface Props {
  view: CaseView;
  onResumed: () => void;
  onStopped?: () => void;
}

/** Stop / resume buttons (and their confirmation) for the answer card's action row. Render inside a .btn-row. */
export function RunControls({ view, onResumed, onStopped }: Props) {
  const navigate = useNavigate();
  const [resuming, setResuming] = useState(false);
  const [resumeError, setResumeError] = useState<string | null>(null);
  const [confirmStop, setConfirmStop] = useState(false);
  const [stopping, setStopping] = useState(false);
  const [stopError, setStopError] = useState<string | null>(null);
  // Set once the stop request is accepted; cleared when the run actually ends.
  const [stopRequested, setStopRequested] = useState(false);
  useEffect(() => {
    if (!view.running) setStopRequested(false);
  }, [view.running]);

  const resume = async () => {
    setResuming(true);
    setResumeError(null);
    try {
      const res = await api.resumeCase(view.case_id);
      if (res.case_id && res.case_id !== view.case_id) {
        navigate(`/cases/${encodeURIComponent(res.case_id)}`);
      } else {
        onResumed();
      }
    } catch (e) {
      setResumeError(errorMessage(e));
    } finally {
      setResuming(false);
    }
  };

  const stop = async () => {
    setStopping(true);
    setStopError(null);
    try {
      await api.cancelCase(view.case_id);
      setConfirmStop(false);
      setStopRequested(true);
      (onStopped ?? onResumed)();
    } catch (e) {
      setStopError(errorMessage(e));
    } finally {
      setStopping(false);
    }
  };

  return (
    <>
      {view.running && stopRequested ? (
        <span className="muted" role="status">
          Stopping after the current step...
        </span>
      ) : null}
      {view.running && !confirmStop && !stopRequested ? (
        <button type="button" className="btn" onClick={() => setConfirmStop(true)}>
          <Icon name="x" size={14} />
          Stop
        </button>
      ) : null}
      {view.can_resume ? (
        <button type="button" className="btn" onClick={resume} disabled={resuming}>
          <Icon name="play" size={14} />
          {resuming ? "Resuming..." : "Resume"}
        </button>
      ) : null}
      {view.running && confirmStop ? (
        <div className="confirm-box" role="group" aria-label="Confirm stopping the investigation">
          <p>Stop after the current step? Evidence collected so far is kept and a partial memo is written.</p>
          <div className="btn-row">
            <button type="button" className="btn primary" onClick={stop} disabled={stopping}>
              {stopping ? "Stopping..." : "Yes, stop"}
            </button>
            <button type="button" className="btn" onClick={() => setConfirmStop(false)} disabled={stopping}>
              Keep going
            </button>
          </div>
        </div>
      ) : null}
      {stopError ? (
        <p className="error-text" role="alert">
          {stopError}
        </p>
      ) : null}
      {resumeError ? (
        <p className="error-text" role="alert">
          {resumeError}
        </p>
      ) : null}
    </>
  );
}

/** Report-level details shown inside "Full report": who was compared, when, deal thesis and the raw evidence download. */
export function CaseMeta({ view }: { view: CaseView }) {
  return (
    <div className="case-meta">
      <Dateline
        items={[
          <>Compared with {view.peers.length > 0 ? view.peers.join(", ") : "no competitors"}</>,
          <>Last {view.lookback_months} months</>,
          <>
            Updated <time dateTime={view.updated_at}>{formatDateTime(view.updated_at)}</time>
          </>,
          <ModeBadge mode={view.mode} />,
          <StatusPill tone={view.status_tone}>{view.status_label}</StatusPill>,
        ]}
      />
      {view.status_detail ? <p className="muted small case-status-detail">{view.status_detail}</p> : null}
      <Disclosure summary="What you asked us to check">
        <blockquote className="thesis" style={{ margin: 0 }}>
          {view.thesis}
        </blockquote>
      </Disclosure>
      {view.report_available ? (
        <p className="small">
          <a href={api.bundleUrl(view.case_id)} download>
            <Icon name="download" size={14} /> Download raw evidence (.json)
          </a>
        </p>
      ) : null}
    </div>
  );
}
