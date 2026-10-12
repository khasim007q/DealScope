import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { api, errorMessage } from "../api/client";
import type { CaseView } from "../api/types";
import { formatDateTime } from "../lib/format";
import { Banner, Disclosure, Icon, ModeBadge, StatusPill } from "./ui";

interface Props {
  view: CaseView;
  onResumed: () => void;
}

export function CaseHeader({ view, onResumed }: Props) {
  const navigate = useNavigate();
  const [resuming, setResuming] = useState(false);
  const [resumeError, setResumeError] = useState<string | null>(null);

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

  return (
    <header className="card case-head">
      {view.synthetic ? (
        <Banner tone="caution" className="banner-demo" title="Demo data - not a real company assessment">
          The companies, people and job postings below are fictional. Do not use these results to judge a real business.
        </Banner>
      ) : null}

      <div className="case-meta">
        <ModeBadge mode={view.mode} />
        <StatusPill tone={view.status_tone}>{view.status_label}</StatusPill>
        <span className="muted small">
          Updated <time dateTime={view.updated_at}>{formatDateTime(view.updated_at)}</time>
        </span>
      </div>

      <h1>{view.target}</h1>
      <p className="peer-list">
        <strong>Compared with:</strong> {view.peers.length > 0 ? view.peers.join(", ") : "no peers listed"}
        <span className="muted"> - last {view.lookback_months} months</span>
      </p>

      {view.status_detail ? <p className="muted" style={{ marginBottom: 8 }}>{view.status_detail}</p> : null}

      <Disclosure summary="Deal thesis">
        <blockquote className="thesis" style={{ margin: 0 }}>
          {view.thesis}
        </blockquote>
      </Disclosure>

      <div className="btn-row" style={{ marginTop: 14 }}>
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
      {resumeError ? (
        <p className="error-text" role="alert">
          {resumeError}
        </p>
      ) : null}
    </header>
  );
}
