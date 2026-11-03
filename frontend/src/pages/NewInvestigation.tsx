import { useEffect, useMemo, useRef, useState, type FormEvent } from "react";
import { useNavigate } from "react-router-dom";
import { api, errorMessage } from "../api/client";
import type { CreateCaseRequest, IdentityResult, RunMode, Scenario } from "../api/types";
import { FeaturedCases } from "../components/FeaturedCases";
import { IdentityTable } from "../components/IdentityTable";
import { ModeCards } from "../components/ModeCards";
import { ScenarioPicker } from "../components/ScenarioPicker";
import { Banner, Disclosure, ErrorBox, Icon, Kicker, PageHeader, Rule } from "../components/ui";
import { formatCredits, isValidDomain, normalizeDomain, splitDomains } from "../lib/format";
import { useAsync, useDocumentTitle } from "../lib/hooks";

interface FieldErrors {
  target?: string;
  competitors?: string;
  thesis?: string;
  lookback?: string;
  cap?: string;
  scenario?: string;
}

const MIN_PEERS = 2;
const MAX_PEERS = 5;

export function NewInvestigation() {
  useDocumentTitle("New investigation");
  const navigate = useNavigate();
  const status = useAsync(() => api.status());
  const scenarios = useAsync(() => api.scenarios());
  const faults = useAsync(() => api.faults());

  const [mode, setMode] = useState<RunMode>("synthetic");
  const [scenarioId, setScenarioId] = useState<string | null>(null);
  const [faultId, setFaultId] = useState("none");
  const [target, setTarget] = useState("");
  const [peersText, setPeersText] = useState("");
  const [thesis, setThesis] = useState("");
  const [lookback, setLookback] = useState("12");
  const [cap, setCap] = useState("");
  const [capTouched, setCapTouched] = useState(false);

  const [identity, setIdentity] = useState<IdentityResult[] | null>(null);
  const [identityKey, setIdentityKey] = useState<string>("");
  const [checking, setChecking] = useState(false);
  const [checkError, setCheckError] = useState<string | null>(null);
  const [confirmed, setConfirmed] = useState(false);

  const [submitting, setSubmitting] = useState(false);
  const [submitError, setSubmitError] = useState<string | null>(null);
  const [showErrors, setShowErrors] = useState(false);
  const seededRef = useRef(false);

  const st = status.data;
  const maxCredits = st?.max_case_credits ?? 40;
  const liveAvailable = st?.live_available ?? false;

  // Default the credit cap to min(40, max_case_credits) once status arrives.
  useEffect(() => {
    if (st && !capTouched) setCap(String(Math.min(40, st.max_case_credits)));
  }, [st, capTouched]);

  // If live is unavailable, make sure we are not stuck in live mode.
  useEffect(() => {
    if (st && !st.live_available && mode === "live") setMode("synthetic");
  }, [st, mode]);

  const applyScenario = (s: Scenario) => {
    setScenarioId(s.id);
    setTarget(s.target_domain);
    setPeersText(s.competitor_domains.join("\n"));
    setThesis(s.deal_thesis);
    setIdentity(null);
    setConfirmed(false);
  };

  // Preselect the first scenario once loaded, in synthetic mode only.
  useEffect(() => {
    if (!seededRef.current && scenarios.data && scenarios.data.length > 0) {
      seededRef.current = true;
      applyScenario(scenarios.data[0]);
    }
  }, [scenarios.data]);

  const targetDomain = normalizeDomain(target);
  const peers = useMemo(() => Array.from(new Set(splitDomains(peersText))), [peersText]);
  const allDomains = useMemo(
    () => (targetDomain ? [targetDomain, ...peers.filter((p) => p !== targetDomain)] : peers),
    [targetDomain, peers],
  );
  const domainsKey = allDomains.join("|");

  // Any change to the set of domains invalidates a previous identity check and the confirmation.
  useEffect(() => {
    if (identity && identityKey !== domainsKey) {
      setIdentity(null);
      setConfirmed(false);
    }
  }, [domainsKey, identity, identityKey]);

  const errors: FieldErrors = useMemo(() => {
    const e: FieldErrors = {};
    if (!targetDomain) e.target = "Enter the target company's domain, for example example.com.";
    else if (!isValidDomain(targetDomain)) e.target = "That does not look like a domain. Use a format like example.com.";
    const bad = peers.filter((p) => !isValidDomain(p));
    if (peers.length < MIN_PEERS) e.competitors = `Add at least ${MIN_PEERS} competitor domains (one per line).`;
    else if (peers.length > MAX_PEERS) e.competitors = `Use at most ${MAX_PEERS} competitor domains. You entered ${peers.length}.`;
    else if (bad.length > 0) e.competitors = `Not a valid domain: ${bad.join(", ")}.`;
    else if (peers.includes(targetDomain)) e.competitors = "The target company cannot also be listed as a competitor.";
    if (thesis.trim().length < 10) e.thesis = "Describe the deal thesis in at least a sentence so the agent knows what to test.";
    const lb = Number(lookback);
    if (!Number.isInteger(lb) || lb < 1 || lb > 60) e.lookback = "Enter a whole number of months between 1 and 60.";
    const cp = Number(cap);
    if (!Number.isFinite(cp) || cp < 1) e.cap = "Enter a credit cap of at least 1.";
    else if (cp > maxCredits) e.cap = `The credit cap cannot exceed ${formatCredits(maxCredits)} credits per case.`;
    else if (mode === "live" && st && cp > st.live_budget.remaining)
      e.cap = `Only ${formatCredits(st.live_budget.remaining)} live credits remain. Lower the cap.`;
    if (mode === "synthetic" && !scenarioId) e.scenario = "Choose a demo scenario.";
    return e;
  }, [targetDomain, peers, thesis, lookback, cap, maxCredits, mode, st, scenarioId]);

  const hasErrors = Object.keys(errors).length > 0;
  const shown = (k: keyof FieldErrors) => (showErrors ? errors[k] : undefined);

  const identityFresh = identity !== null && identityKey === domainsKey;
  const identityAllOk = identityFresh && identity.every((r) => r.ok);
  const identityBlocked = identityFresh && identity.some((r) => !r.ok);

  const runCheck = async (domains: string[]) => {
    setChecking(true);
    setCheckError(null);
    setConfirmed(false);
    try {
      const res = await api.identityCheck(domains);
      setIdentity(res);
      setIdentityKey(domains.join("|"));
    } catch (e) {
      setIdentity(null);
      setCheckError(errorMessage(e));
    } finally {
      setChecking(false);
    }
  };

  const onCheck = () => {
    setShowErrors(true);
    if (hasErrors) return;
    void runCheck(allDomains);
  };

  const useDomain = (from: string, to: string) => {
    const nTo = normalizeDomain(to);
    if (from === targetDomain) {
      setTarget(nTo);
      void runCheck([nTo, ...peers.filter((p) => p !== nTo)]);
      return;
    }
    const nextPeers = Array.from(new Set(peers.map((p) => (p === from ? nTo : p))));
    setPeersText(nextPeers.join("\n"));
    void runCheck([targetDomain, ...nextPeers.filter((p) => p !== targetDomain)]);
  };

  const removePeer = (d: string) => setPeersText(peers.filter((p) => p !== d).join("\n"));

  const onSubmit = async (ev: FormEvent) => {
    ev.preventDefault();
    setShowErrors(true);
    setSubmitError(null);
    if (hasErrors) return;
    if (mode === "live" && !(identityAllOk && confirmed)) return;
    const req: CreateCaseRequest = {
      target_domain: targetDomain,
      competitor_domains: peers,
      deal_thesis: thesis.trim(),
      lookback_months: Number(lookback),
      max_case_credits: Number(cap),
      mode,
    };
    if (mode === "synthetic") {
      if (scenarioId) req.scenario_id = scenarioId;
      if (faultId !== "none") req.fault_id = faultId;
    }
    setSubmitting(true);
    try {
      const res = await api.createCase(req);
      navigate(`/cases/${encodeURIComponent(res.case_id)}`);
    } catch (e) {
      setSubmitError(errorMessage(e));
      setSubmitting(false);
    }
  };

  const faultList = faults.data ?? [];
  const selectedFault = faultList.find((f) => f.id === faultId);
  const isLive = mode === "live";

  const liveBlocked = isLive && !(identityAllOk && confirmed);
  const budget = st?.live_budget;
  const capNum = Number(cap);
  const capOk = Number.isFinite(capNum) && capNum > 0;

  return (
    <>
      <PageHeader
        kicker="New investigation"
        title="Brief the analyst"
        dek="Name a target, a few competitors and your deal thesis. DealScope investigates public company, people-history and job-posting data, scores five organizational risk signals, and writes a memo in which every claim cites evidence."
      />

      <div className="brief">
        <form className="brief-form" onSubmit={onSubmit} noValidate aria-label="New investigation">
          {status.error ? (
            <div className="step-note">
              <ErrorBox title="Could not load server status" message={status.error} onRetry={status.reload} />
            </div>
          ) : null}

          <section className="step" aria-labelledby="step-source">
            <header className="step-head">
              <span className="step-no" aria-hidden="true">1</span>
              <div>
                <Kicker>Data source</Kicker>
                <h2 id="step-source">Where should the evidence come from?</h2>
              </div>
            </header>
            <ModeCards
              mode={mode}
              onChange={(m) => {
                setMode(m);
                setConfirmed(false);
              }}
              status={st}
              statusError={status.error}
            />
            {mode === "synthetic" ? (
              <>
                <Banner tone="caution" title="Demo data - not a real company assessment">
                  This run uses fictional companies and simulated credit accounting. Nothing here describes a real
                  business.
                </Banner>
                {scenarios.error ? (
                  <ErrorBox title="Could not load demo scenarios" message={scenarios.error} onRetry={scenarios.reload} />
                ) : scenarios.loading ? (
                  <p className="muted">Loading demo scenarios...</p>
                ) : (
                  <>
                    <ScenarioPicker scenarios={scenarios.data ?? []} selectedId={scenarioId} onSelect={applyScenario} />
                    {shown("scenario") ? <p className="error-text">{errors.scenario}</p> : null}
                  </>
                )}
              </>
            ) : (
              <Banner tone="caution" title="Live run: this spends real credits">
                {budget ? `${formatCredits(budget.remaining)} live credits remain. ` : ""}
                You will check the companies for free first, then confirm the credit cap before anything is spent.
              </Banner>
            )}
          </section>

          <section className="step" aria-labelledby="step-target">
            <header className="step-head">
              <span className="step-no" aria-hidden="true">2</span>
              <div>
                <Kicker>Target and peers</Kicker>
                <h2 id="step-target">Who is being evaluated, and against whom?</h2>
              </div>
            </header>

            <div className="field">
              <label htmlFor="target">Target company domain</label>
              <input
                id="target"
                className="input"
                type="text"
                inputMode="url"
                autoComplete="off"
                spellCheck={false}
                placeholder="example.com"
                value={target}
                onChange={(e) => setTarget(e.target.value)}
                aria-invalid={shown("target") ? true : undefined}
                aria-describedby={shown("target") ? "target-err" : "target-help"}
              />
              {shown("target") ? (
                <p className="error-text" id="target-err">
                  {errors.target}
                </p>
              ) : (
                <p className="help" id="target-help">
                  The company being evaluated. Just the domain, no https:// or paths.
                </p>
              )}
            </div>

            <div className="field">
              <label htmlFor="peers">Competitor domains</label>
              <textarea
                id="peers"
                className="textarea peers-input"
                spellCheck={false}
                placeholder={"competitor-one.com\ncompetitor-two.com"}
                value={peersText}
                onChange={(e) => setPeersText(e.target.value)}
                aria-invalid={shown("competitors") ? true : undefined}
                aria-describedby={shown("competitors") ? "peers-err" : "peers-help"}
              />
              {shown("competitors") ? (
                <p className="error-text" id="peers-err">
                  {errors.competitors}
                </p>
              ) : (
                <p className="help" id="peers-help">
                  {MIN_PEERS} to {MAX_PEERS} peers, one per line. The agent compares the target against these.
                </p>
              )}
              {peers.length > 0 ? (
                <ul className="chips chips-plain" aria-label="Parsed competitor domains">
                  {peers.map((p) => (
                    <li key={p} className="chip">
                      <span>{p}</span>
                      <button type="button" onClick={() => removePeer(p)} aria-label={`Remove ${p}`}>
                        <Icon name="x" size={12} />
                      </button>
                    </li>
                  ))}
                </ul>
              ) : null}
            </div>
          </section>

          <section className="step" aria-labelledby="step-thesis">
            <header className="step-head">
              <span className="step-no" aria-hidden="true">3</span>
              <div>
                <Kicker>Thesis</Kicker>
                <h2 id="step-thesis">What do you believe about this deal?</h2>
              </div>
            </header>
            <div className="field">
              <label htmlFor="thesis">Deal thesis</label>
              <textarea
                id="thesis"
                className="textarea"
                value={thesis}
                onChange={(e) => setThesis(e.target.value)}
                aria-invalid={shown("thesis") ? true : undefined}
                aria-describedby={shown("thesis") ? "thesis-err" : "thesis-help"}
              />
              {shown("thesis") ? (
                <p className="error-text" id="thesis-err">
                  {errors.thesis}
                </p>
              ) : (
                <p className="help" id="thesis-help">
                  What you believe about this deal and what would worry you. For example: "We expect the engineering
                  team to keep pace with growth after the acquisition."
                </p>
              )}
            </div>
          </section>

          <section className="step" aria-labelledby="step-budget">
            <header className="step-head">
              <span className="step-no" aria-hidden="true">4</span>
              <div>
                <Kicker>Scope and budget</Kicker>
                <h2 id="step-budget">How far back, and how much to spend?</h2>
              </div>
            </header>
            <div className="grid-2">
              <div className="field">
                <label htmlFor="lookback">Lookback (months)</label>
                <input
                  id="lookback"
                  className="input"
                  type="number"
                  min={1}
                  max={60}
                  step={1}
                  value={lookback}
                  onChange={(e) => setLookback(e.target.value)}
                  aria-invalid={shown("lookback") ? true : undefined}
                  aria-describedby={shown("lookback") ? "lookback-err" : "lookback-help"}
                />
                {shown("lookback") ? (
                  <p className="error-text" id="lookback-err">
                    {errors.lookback}
                  </p>
                ) : (
                  <p className="help" id="lookback-help">
                    How far back to look for departures and hiring changes.
                  </p>
                )}
              </div>
              <div className="field">
                <label htmlFor="cap">Credit cap</label>
                <input
                  id="cap"
                  className="input"
                  type="number"
                  min={1}
                  max={maxCredits}
                  step={1}
                  value={cap}
                  onChange={(e) => {
                    setCap(e.target.value);
                    setCapTouched(true);
                  }}
                  aria-invalid={shown("cap") ? true : undefined}
                  aria-describedby={shown("cap") ? "cap-err" : "cap-help"}
                />
                {shown("cap") ? (
                  <p className="error-text" id="cap-err">
                    {errors.cap}
                  </p>
                ) : (
                  <p className="help" id="cap-help">
                    {isLive
                      ? `The most this investigation may spend. Maximum per case: ${formatCredits(maxCredits)}.`
                      : `Demo runs only simulate credit use. Maximum per case: ${formatCredits(maxCredits)}.`}
                  </p>
                )}
              </div>
            </div>

            {mode === "synthetic" ? (
              <Disclosure summary="Simulate a failure (optional)">
                <div className="field">
                  <label htmlFor="fault">Failure to simulate</label>
                  <select
                    id="fault"
                    className="select"
                    value={faultId}
                    onChange={(e) => setFaultId(e.target.value)}
                    aria-describedby="fault-help"
                  >
                    <option value="none">None - run normally</option>
                    {faultList
                      .filter((f) => f.id !== "none")
                      .map((f) => (
                        <option key={f.id} value={f.id}>
                          {f.label}
                        </option>
                      ))}
                  </select>
                  <p className="help" id="fault-help">
                    {selectedFault && selectedFault.id !== "none"
                      ? selectedFault.description
                      : "Show how the agent copes when a data source misbehaves. Leave on None for a normal run."}
                  </p>
                </div>
              </Disclosure>
            ) : null}
          </section>

          {isLive ? (
            <section className="step" aria-labelledby="identity-h">
              <header className="step-head">
                <span className="step-no" aria-hidden="true">5</span>
                <div>
                  <Kicker>Verification</Kicker>
                  <h2 id="identity-h">Check the companies (free)</h2>
                </div>
              </header>
              <p className="help step-lede">
                Confirms each domain points to the company you mean, before any credits are spent.
              </p>
              <div className="btn-row">
                <button type="button" className="btn" onClick={onCheck} disabled={checking}>
                  {checking ? "Checking..." : identityFresh ? "Re-check companies" : "Check companies"}
                </button>
                {checking ? <span className="spinner" role="status" aria-label="Checking companies" /> : null}
              </div>
              {checkError ? (
                <div className="step-note">
                  <ErrorBox title="The company check failed" message={checkError} />
                </div>
              ) : null}
              {identityFresh && identity ? (
                <div className="step-note">
                  <IdentityTable results={identity} onUseDomain={useDomain} disabled={checking} />
                  <div className="step-note">
                    {identityBlocked ? (
                      <Banner tone="bad" title="Not ready to start">
                        One or more domains did not resolve to a single clear company. Fix them above (use a suggested
                        domain or edit the form), then check again. No credits have been spent.
                      </Banner>
                    ) : (
                      <Banner tone="good" title="All companies matched">
                        Every domain resolved to a company. Review the names above before you continue.
                      </Banner>
                    )}
                  </div>
                </div>
              ) : null}

              {identityAllOk ? (
                <div className="step-note">
                  <label className="check">
                    <input type="checkbox" checked={confirmed} onChange={(e) => setConfirmed(e.target.checked)} />
                    <span>
                      I confirm these companies and the credit cap
                      {capOk ? ` (up to ${formatCredits(capNum)} credits)` : ""}.
                    </span>
                  </label>
                </div>
              ) : null}
            </section>
          ) : null}

          <div className="brief-submit">
            {submitError ? (
              <div className="step-note">
                <ErrorBox title="Could not start the investigation" message={submitError} />
              </div>
            ) : null}
            {showErrors && hasErrors ? (
              <p className="error-text" role="alert">
                Please fix the highlighted fields above.
              </p>
            ) : null}
            <div className="btn-row">
              <button type="submit" className="btn primary brief-go" disabled={submitting || liveBlocked}>
                <Icon name="play" size={14} />
                {submitting ? "Starting..." : isLive ? "Start live investigation" : "Start demo investigation"}
              </button>
              {liveBlocked ? (
                <span className="small muted">
                  {!identityFresh
                    ? "Check the companies first."
                    : identityBlocked
                      ? "Resolve the company issues first."
                      : "Tick the confirmation to enable."}
                </span>
              ) : null}
              {!liveAvailable && !status.loading ? (
                <span className="small muted">Live data is not available on this server.</span>
              ) : null}
            </div>
          </div>
        </form>

        <aside className="brief-aside" aria-label="About this run">
          <Kicker>What this run does</Kicker>
          <ol className="aside-steps">
            <li>Resolves each domain to a company profile.</li>
            <li>Pulls people-history and job-posting data for the target and peers.</li>
            <li>Scores five organizational risk signals against your thesis.</li>
            <li>Writes a memo; every claim links to its evidence.</li>
          </ol>
          <Rule />
          <Kicker>Cost</Kicker>
          {isLive ? (
            <>
              <p className="aside-figure num">
                {capOk ? formatCredits(capNum) : "-"}
                <small> credits, at most</small>
              </p>
              <p className="aside-note">
                Real Crustdata credits.{" "}
                {budget
                  ? `${formatCredits(budget.remaining)} of ${formatCredits(budget.spendable)} remain in the live budget.`
                  : ""}
              </p>
            </>
          ) : (
            <>
              <p className="aside-figure num">
                0<small> credits</small>
              </p>
              <p className="aside-note">Demo runs simulate credit use and spend nothing.</p>
            </>
          )}
        </aside>
      </div>

      <FeaturedCases />
    </>
  );
}
