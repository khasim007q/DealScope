import { useEffect, useMemo, useRef, useState, type FormEvent, type KeyboardEvent } from "react";
import { Link, useNavigate } from "react-router-dom";
import { api, errorMessage } from "../api/client";
import type { CreateCaseRequest, IdentityResult, Scenario } from "../api/types";
import { ScenarioPicker } from "../components/ScenarioPicker";
import { Icon, Kicker } from "../components/ui";
import { formatCredits, formatRelative, isValidDomain, normalizeDomain, splitDomains, verdictWord } from "../lib/format";
import { useAsync, useDocumentTitle, useNow } from "../lib/hooks";

const MAX_PEERS = 5;
const DEFAULT_CAP = 40;
const DEFAULT_LOOKBACK = 12;
const MIN_LOOKBACK = 3;
const MAX_LOOKBACK = 36;
const EXAMPLES = ["linear.app", "notion.com", "stripe.com"];

interface Errors {
  target?: string;
  peers?: string;
  thesis?: string;
  lookback?: string;
  cap?: string;
}

/** Search-first home: one box, one button. Live searches check the company identity for free, then start straight away. */
export function Home() {
  useDocumentTitle("Search");
  const navigate = useNavigate();
  const status = useAsync(() => api.status());
  const scenarios = useAsync(() => api.scenarios());
  const faults = useAsync(() => api.faults());
  const cases = useAsync(() => api.listCases());
  const now = useNow();

  const [wantDemo, setWantDemo] = useState(false);
  const [scenarioId, setScenarioId] = useState<string | null>(null);
  const [faultId, setFaultId] = useState("none");
  const [target, setTarget] = useState("");
  const [peers, setPeers] = useState<string[]>([]);
  const [peerDraft, setPeerDraft] = useState("");
  const [thesis, setThesis] = useState("");
  const [lookback, setLookback] = useState(String(DEFAULT_LOOKBACK));
  const [cap, setCap] = useState(String(DEFAULT_CAP));
  const [refineOpen, setRefineOpen] = useState(false);

  const [busy, setBusy] = useState<"checking" | "starting" | null>(null);
  const [issues, setIssues] = useState<IdentityResult[]>([]);
  const [submitError, setSubmitError] = useState<string | null>(null);
  const [showErrors, setShowErrors] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);
  const busyRef = useRef(false); // synchronous guard: state updates lag behind rapid double clicks

  const st = status.data;
  const provider = st?.data_provider;
  const liveReady = !!st && (provider !== undefined || st.live_available);
  const demo = wantDemo || (!!st && !liveReady) || (!st && !!status.error);
  const maxCredits = st?.max_case_credits ?? DEFAULT_CAP;
  const isFree = provider === "free";

  // Keep the default credit cap within what the server allows.
  useEffect(() => {
    if (st) setCap((c) => (Number(c) > st.max_case_credits ? String(st.max_case_credits) : c));
  }, [st]);

  const applyScenario = (s: Scenario) => {
    setScenarioId(s.id);
    setTarget(s.target_domain);
    setPeers(s.competitor_domains.slice(0, MAX_PEERS));
    setThesis(s.deal_thesis);
    setIssues([]);
  };

  // Entering demo mode preselects the first scenario so the search box holds something valid.
  useEffect(() => {
    if (demo && !scenarioId && scenarios.data && scenarios.data.length > 0) applyScenario(scenarios.data[0] as Scenario);
  }, [demo, scenarioId, scenarios.data]);

  // Leaving demo clears the made-up .example values; entering demo prefills the first scenario via the effect above.
  const toggleDemo = () => {
    if (demo) {
      setTarget("");
      setPeers([]);
      setPeerDraft("");
      setThesis("");
      setScenarioId(null);
      setFaultId("none");
      setIssues([]);
      setShowErrors(false);
    }
    setWantDemo(!demo);
  };

  const targetDomain = normalizeDomain(target);

  const errors: Errors = useMemo(() => {
    const e: Errors = {};
    if (!targetDomain) e.target = "Enter a company website, for example linear.app.";
    else if (!isValidDomain(targetDomain)) e.target = "That does not look like a website. Try a format like linear.app.";
    const bad = peers.filter((p) => !isValidDomain(p));
    if (peers.length > MAX_PEERS) e.peers = `Use at most ${MAX_PEERS} competitors.`;
    else if (bad.length > 0) e.peers = `Not a valid website: ${bad.join(", ")}.`;
    else if (peers.includes(targetDomain)) e.peers = "The company cannot also be its own competitor.";
    if (thesis.trim().length > 0 && thesis.trim().length < 10) e.thesis = "Write at least a short sentence, or leave this empty.";
    const lb = Number(lookback);
    if (!Number.isInteger(lb) || lb < MIN_LOOKBACK || lb > MAX_LOOKBACK) e.lookback = `Enter a whole number of months from ${MIN_LOOKBACK} to ${MAX_LOOKBACK}.`;
    const cp = Number(cap);
    if (!Number.isFinite(cp) || cp < 1) e.cap = "Enter at least 1 credit.";
    else if (cp > maxCredits) e.cap = `At most ${formatCredits(maxCredits)} credits per search.`;
    else if (!demo && !isFree && st && cp > st.live_budget.remaining) e.cap = `Only ${formatCredits(st.live_budget.remaining)} credits remain.`;
    return e;
  }, [targetDomain, peers, thesis, lookback, cap, maxCredits, demo, isFree, st]);

  const addPeers = (text: string) => {
    const incoming = splitDomains(text);
    if (incoming.length === 0) return;
    setPeers((cur) => Array.from(new Set([...cur, ...incoming])).slice(0, MAX_PEERS));
    setPeerDraft("");
    setIssues([]);
  };
  const onPeerKey = (ev: KeyboardEvent<HTMLInputElement>) => {
    if (ev.key === "Enter" || ev.key === ",") {
      ev.preventDefault();
      addPeers(peerDraft);
    }
  };

  const setBusyState = (b: "checking" | "starting" | null) => {
    busyRef.current = b !== null;
    setBusy(b);
  };

  // Takes the domain and peers explicitly so callers that just changed them never read stale state.
  const start = async (domain: string, peerList: string[]) => {
    if (busyRef.current) return;
    setSubmitError(null);
    setIssues([]);
    // Live searches check the company first (free) so we never spend on the wrong business.
    if (!demo) {
      setBusyState("checking");
      try {
        const results = await api.identityCheck([domain, ...peerList]);
        const bad = results.filter((r) => !r.ok);
        if (bad.length > 0) {
          setIssues(bad);
          setBusyState(null);
          return;
        }
      } catch (e) {
        setSubmitError(errorMessage(e));
        setBusyState(null);
        return;
      }
    }
    setBusyState("starting");
    const req: CreateCaseRequest = { target_domain: domain, mode: demo ? "synthetic" : "live" };
    if (peerList.length > 0) req.competitor_domains = peerList;
    if (thesis.trim()) req.deal_thesis = thesis.trim();
    if (Number(lookback) !== DEFAULT_LOOKBACK) req.lookback_months = Number(lookback);
    if (!isFree && Number(cap) !== DEFAULT_CAP) req.max_case_credits = Number(cap);
    if (demo) {
      if (scenarioId) req.scenario_id = scenarioId;
      if (faultId !== "none") req.fault_id = faultId;
    }
    try {
      const res = await api.createCase(req);
      navigate(`/cases/${encodeURIComponent(res.case_id)}`);
    } catch (e) {
      setSubmitError(errorMessage(e));
      setBusyState(null);
    }
  };

  const onSubmit = (ev: FormEvent) => {
    ev.preventDefault();
    if (busyRef.current) return;
    setShowErrors(true);
    if (Object.keys(errors).length > 0) {
      if (!errors.target) setRefineOpen(true); // the problem is inside "Refine": show it
      else inputRef.current?.focus();
      return;
    }
    void start(targetDomain, peers);
  };

  // Fix an unmatched or ambiguous website from a suggestion chip, then carry on.
  const useCandidate = (from: string, to: string) => {
    if (busyRef.current) return;
    const nTo = normalizeDomain(to);
    if (from === targetDomain) {
      setTarget(nTo);
      void start(nTo, peers.filter((p) => p !== nTo));
    } else {
      const next = Array.from(new Set(peers.map((p) => (p === from ? nTo : p)))).filter((p) => p !== targetDomain);
      setPeers(next);
      void start(targetDomain, next);
    }
  };
  const skipPeer = (d: string) => {
    if (busyRef.current) return;
    const next = peers.filter((p) => p !== d);
    setPeers(next);
    void start(targetDomain, next);
  };

  const pickExample = (d: string) => {
    const sc = demo ? scenarios.data?.find((s) => s.target_domain === d) : undefined;
    if (sc) applyScenario(sc);
    else {
      setTarget(d);
      setIssues([]);
    }
    inputRef.current?.focus();
  };

  const examples = demo ? (scenarios.data ?? []).slice(0, 3).map((s) => s.target_domain) : EXAMPLES;
  const recent = cases.data ? [...cases.data].sort((a, b) => b.updated_at.localeCompare(a.updated_at)).slice(0, 5) : [];
  const shown = (k: keyof Errors) => (showErrors ? errors[k] : undefined);
  const costLine = demo
    ? "Demo data. No credits used."
    : isFree
      ? "Free data sources."
      : `Uses up to ${formatCredits(Number(cap) > 0 ? Number(cap) : DEFAULT_CAP)} credits.`;
  const faultList = faults.data ?? [];

  return (
    <div className="home">
      <header className="home-hero">
        <h1>Check a company&rsquo;s team before you invest</h1>
        <p className="dek">
          Enter a company website. We look at hiring, departures and growth in public data, then tell you what to ask
          before you commit.
        </p>
      </header>

      <form className="home-form" onSubmit={onSubmit} noValidate aria-label="Search for a company">
        <label htmlFor="target" className="sr-only">
          Company website
        </label>
        <div className="search-row">
          <input
            id="target"
            ref={inputRef}
            className="input search-input"
            type="text"
            inputMode="url"
            autoComplete="off"
            autoCapitalize="none"
            spellCheck={false}
            placeholder="Company website, e.g. linear.app"
            value={target}
            onChange={(e) => {
              setTarget(e.target.value);
              setIssues([]);
            }}
            aria-invalid={shown("target") ? true : undefined}
            aria-describedby={shown("target") ? "target-err" : "cost-line"}
          />
          <button type="submit" className="btn primary search-go" disabled={busy !== null}>
            {busy === "checking" ? "Checking..." : busy === "starting" ? "Starting..." : "Analyze"}
          </button>
        </div>
        {shown("target") ? (
          <p className="error-text" id="target-err">
            {errors.target}
          </p>
        ) : null}
        <p className="search-cost" id="cost-line">
          {status.loading ? "Checking data sources..." : costLine}
          {!st && status.error ? " Could not reach the server, so this will use demo data." : null}
        </p>

        <div aria-live="polite">
          {busy ? (
            <p className="search-busy">
              {busy === "checking" ? "Making sure we have the right company (free)..." : "Starting your analysis..."}
            </p>
          ) : null}
          {issues.length > 0 ? (
            <div className="home-issues">
              <p className="home-issues-title">
                We need you to confirm {issues.length === 1 ? "one website" : "a few websites"}.
              </p>
              <ul>
                {issues.map((r) => {
                  const isPeer = r.domain !== targetDomain;
                  const picks = r.candidates.filter((c) => c.primary_domain);
                  return (
                    <li key={r.domain}>
                      <p>
                        <strong>{r.domain}</strong>
                        {isPeer ? " (competitor)" : ""}: {r.message}
                      </p>
                      {picks.length > 0 || isPeer ? (
                        <ul className="chips chips-plain" aria-label={`Options for ${r.domain}`}>
                          {picks.map((c) => (
                            <li key={c.primary_domain}>
                              <button
                                type="button"
                                className="chip chip-btn"
                                onClick={() => useCandidate(r.domain, c.primary_domain as string)}
                                disabled={busy !== null}
                              >
                                {c.name ?? c.primary_domain}
                                <span className="muted"> {c.primary_domain}</span>
                                {c.employee_count_range ? <span className="muted"> · {c.employee_count_range} staff</span> : null}
                              </button>
                            </li>
                          ))}
                          {isPeer ? (
                            <li>
                              <button type="button" className="chip chip-btn" onClick={() => skipPeer(r.domain)} disabled={busy !== null}>
                                Skip this competitor
                              </button>
                            </li>
                          ) : null}
                        </ul>
                      ) : (
                        <p className="small muted">Check the spelling, or try the company&rsquo;s main website.</p>
                      )}
                    </li>
                  );
                })}
              </ul>
            </div>
          ) : null}
          {submitError ? (
            <p className="error-text">
              {submitError}
            </p>
          ) : null}
        </div>

        <details
          className="disclosure refine"
          open={refineOpen}
          onToggle={(e) => setRefineOpen((e.currentTarget as HTMLDetailsElement).open)}
        >
          <summary>Refine</summary>
          <div className="disc-body refine-body">
            <div className="field">
              <label htmlFor="peer-draft">Competitors (optional, up to {MAX_PEERS})</label>
              <div className="peer-add">
                <input
                  id="peer-draft"
                  className="input"
                  type="text"
                  autoComplete="off"
                  autoCapitalize="none"
                  spellCheck={false}
                  placeholder="competitor.com, then Enter"
                  value={peerDraft}
                  onChange={(e) => setPeerDraft(e.target.value)}
                  onKeyDown={onPeerKey}
                  onBlur={() => addPeers(peerDraft)}
                  disabled={peers.length >= MAX_PEERS}
                  aria-describedby={shown("peers") ? "peers-err" : "peers-help"}
                />
                <button
                  type="button"
                  className="btn small"
                  onClick={() => addPeers(peerDraft)}
                  disabled={peers.length >= MAX_PEERS || !peerDraft.trim()}
                >
                  Add
                </button>
              </div>
              {shown("peers") ? (
                <p className="error-text" id="peers-err">
                  {errors.peers}
                </p>
              ) : (
                <p className="help" id="peers-help">
                  We compare hiring and growth against these. Leave empty to skip the comparison.
                </p>
              )}
              {peers.length > 0 ? (
                <ul className="chips chips-plain" aria-label="Competitors">
                  {peers.map((p) => (
                    <li key={p} className="chip">
                      <span>{p}</span>
                      <button type="button" onClick={() => setPeers(peers.filter((x) => x !== p))} aria-label={`Remove ${p}`}>
                        <Icon name="x" size={12} />
                      </button>
                    </li>
                  ))}
                </ul>
              ) : null}
            </div>

            <div className="field">
              <label htmlFor="thesis">What do you want to check? (optional)</label>
              <textarea
                id="thesis"
                className="textarea"
                rows={3}
                placeholder="e.g. The engineering team can keep shipping after the deal."
                value={thesis}
                onChange={(e) => setThesis(e.target.value)}
                aria-invalid={shown("thesis") ? true : undefined}
                aria-describedby={shown("thesis") ? "thesis-err" : undefined}
              />
              {shown("thesis") ? (
                <p className="error-text" id="thesis-err">
                  {errors.thesis}
                </p>
              ) : null}
            </div>

            <div className="refine-nums">
              <div className="field">
                <label htmlFor="lookback">Look back (months)</label>
                <input
                  id="lookback"
                  className="input"
                  type="number"
                  inputMode="numeric"
                  min={MIN_LOOKBACK}
                  max={MAX_LOOKBACK}
                  value={lookback}
                  onChange={(e) => setLookback(e.target.value)}
                  aria-invalid={shown("lookback") ? true : undefined}
                  aria-describedby={shown("lookback") ? "lookback-err" : undefined}
                />
                {shown("lookback") ? (
                  <p className="error-text" id="lookback-err">
                    {errors.lookback}
                  </p>
                ) : null}
              </div>
              {isFree || demo ? null : (
                <div className="field">
                  <label htmlFor="cap">Credit limit</label>
                  <input
                    id="cap"
                    className="input"
                    type="number"
                    inputMode="numeric"
                    min={1}
                    max={maxCredits}
                    value={cap}
                    onChange={(e) => setCap(e.target.value)}
                    aria-invalid={shown("cap") ? true : undefined}
                    aria-describedby={shown("cap") ? "cap-err" : "cap-help"}
                  />
                  {shown("cap") ? (
                    <p className="error-text" id="cap-err">
                      {errors.cap}
                    </p>
                  ) : (
                    <p className="help" id="cap-help">
                      The search stops before spending more than this.
                    </p>
                  )}
                </div>
              )}
            </div>
          </div>
        </details>

        <div className="demo-switch">
          {st && !liveReady ? (
            <p className="small muted">Live company data is not connected on this server, so searches use demo data.</p>
          ) : (
            <button type="button" className="link-btn" aria-pressed={demo} onClick={toggleDemo}>
              {demo ? "Use live data instead" : "Try with demo data"}
            </button>
          )}
          {demo ? (
            <div className="demo-panel">
              <p className="small muted">Demo uses made-up companies. Nothing here describes a real business.</p>
              {scenarios.error ? (
                <p className="error-text" role="alert">
                  {scenarios.error}
                </p>
              ) : (
                <ScenarioPicker scenarios={scenarios.data ?? []} selectedId={scenarioId} onSelect={applyScenario} />
              )}
              {faultList.length > 0 ? (
                <div className="field">
                  <label htmlFor="fault">Simulated problem</label>
                  <select id="fault" className="select" value={faultId} onChange={(e) => setFaultId(e.target.value)}>
                    {faultList.map((f) => (
                      <option key={f.id} value={f.id}>
                        {f.label}
                      </option>
                    ))}
                  </select>
                  <p className="help">{faultList.find((f) => f.id === faultId)?.description}</p>
                </div>
              ) : null}
            </div>
          ) : null}
        </div>
      </form>

      <section className="home-chips" aria-label="Example searches">
        <Kicker>Try</Kicker>
        <ul className="chips chips-plain">
          {examples.map((d) => (
            <li key={d}>
              <button type="button" className="chip chip-btn" onClick={() => pickExample(d)}>
                {d}
              </button>
            </li>
          ))}
        </ul>
      </section>

      {recent.length > 0 ? (
        <section className="home-recent" aria-labelledby="recent-h">
          <div className="recent-head">
            <h2 id="recent-h">Recent</h2>
            <Link to="/cases" className="small">
              All history
            </Link>
          </div>
          <ul className="recent-list">
            {recent.map((c) => (
              <li key={c.case_id}>
                <Link className="case-link" to={`/cases/${encodeURIComponent(c.case_id)}`}>
                  {c.target}
                </Link>
                <span className={`recent-verdict tone-${c.tone}`}>
                  {c.status_label === "Complete" ? verdictWord(c.risk_label) : c.status_label}
                </span>
                <time className="muted small" dateTime={c.updated_at}>
                  {formatRelative(c.updated_at, now)}
                </time>
              </li>
            ))}
          </ul>
        </section>
      ) : null}
    </div>
  );
}
