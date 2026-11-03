import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { api, errorMessage } from "../api/client";
import type { CaseView } from "../api/types";
import { formatDateTime } from "../lib/format";
import { Banner, Dateline, Disclosure, Icon, Kicker, ModeBadge, StatusPill } from "./ui";

interface Props {
  view: CaseView;
  onResumed: () => void;
  onStopped?: () => void;
}

export function CaseHeader({ view, onResumed, onStopped }: Props) {
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
    <header className="case-head">
      {view.synthetic ? (
        <Banner tone="caution" className="banner-demo" title="Demo data - not a real company assessment">
          The companies, people and job postings below are fictional. Do not use these results to judge a real business.
        </Banner>
      ) : null}

      <Kicker accent>Organizational diligence · {view.mode === "synthetic" ? "Synthetic demo" : "Live data"}</Kicker>
      <h1>{view.target}</h1>
      <Dateline
        items={[
          <>Compared with {view.peers.length > 0 ? view.peers.join(", ") : "no peers listed"}</>,
          <>Last {view.lookback_months} months</>,
          <>
            Updated <time dateTime={view.updated_at}>{formatDateTime(view.updated_at)}</time>
          </>,
          <ModeBadge mode={view.mode} />,
          <StatusPill tone={view.status_tone}>{view.status_label}</StatusPill>,
        ]}
      />

      {view.status_detail ? <p className="muted small case-status-detail">{view.status_detail}</p> : null}

      <Disclosure summary="Deal thesis">
        <blockquote className="thesis" style={{ margin: 0 }}>
          {view.thesis}
        </blockquote>
      </Disclosure>

      <div className="btn-row case-actions">
        {view.running && stopRequested ? (
          <span className="muted" role="status">
            Stopping after the current step...
          </span>
        ) : null}
        {view.running && !confirmStop && !stopRequested ? (
          <button type="button" className="btn" onClick={() => setConfirmStop(true)}>
            <Icon name="x" size={14} />
            Stop investigation
          </button>
        ) : null}
        {view.can_resume ? (
          <button type="button" className="btn primary" onClick={resume} disabled={resuming}>
            <Icon name="play" size={14} />
            {resuming ? "Resuming..." : "Resume investigation"}
          </button>
        ) : null}
        {view.report_available ? (
          <>
            <a className="btn" href={api.reportUrl(view.case_id)} download>
              <Icon name="download" size={16} />
              Memo (.md)
            </a>
            <a className="btn" href={api.bundleUrl(view.case_id)} download>
              <Icon name="download" size={16} />
              Evidence (.json)
            </a>
          </>
        ) : null}
      </div>
      {view.running && confirmStop ? (
        <div className="confirm-box" role="group" aria-label="Confirm stopping the investigation">
          <p>Stop after the current step? Collected evidence is kept and a partial memo is written.</p>
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
    </header>
  );
}
