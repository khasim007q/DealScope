import type { RunMode, StatusResponse } from "../api/types";
import { formatCredits } from "../lib/format";

interface Props {
  mode: RunMode;
  onChange: (m: RunMode) => void;
  status: StatusResponse | null;
  statusError: string | null;
}

export function ModeCards({ mode, onChange, status, statusError }: Props) {
  const liveAvailable = status?.live_available ?? false;
  const budget = status?.live_budget;

  return (
    <fieldset>
      <legend className="label">Data source</legend>
      <div className="choice-grid">
        <label className={`choice${mode === "live" ? " selected" : ""}${liveAvailable ? "" : " disabled"}`}>
          <input
            type="radio"
            name="mode"
            value="live"
            checked={mode === "live"}
            disabled={!liveAvailable}
            onChange={() => onChange("live")}
            aria-describedby="mode-live-desc"
          />
          <span className="choice-title">
            <span>Live data (Crustdata)</span>
            <span className="choice-check" aria-hidden="true" />
          </span>
          <span className="choice-body" id="mode-live-desc" style={{ display: "block" }}>
            Investigates the real companies you enter using public company, people-history and job-posting data.
            <strong> This spends real Crustdata credits.</strong>
            {budget ? (
              <span style={{ display: "block", marginTop: 6 }}>
                Live budget remaining: <strong>{formatCredits(budget.remaining)}</strong> of{" "}
                {formatCredits(budget.spendable)} credits. A reserve of {formatCredits(budget.reserve)} credits is
                always held back and never spent.
              </span>
            ) : null}
            {!liveAvailable ? (
              <span style={{ display: "block", marginTop: 6, fontWeight: 600 }}>
                {statusError
                  ? "Unavailable: the server status could not be loaded."
                  : "Unavailable: Crustdata is not connected on this server. Live runs are never simulated."}
              </span>
            ) : null}
          </span>
        </label>

        <label className={`choice${mode === "synthetic" ? " selected" : ""}`}>
          <input
            type="radio"
            name="mode"
            value="synthetic"
            checked={mode === "synthetic"}
            onChange={() => onChange("synthetic")}
            aria-describedby="mode-demo-desc"
          />
          <span className="choice-title">
            <span>Demo data (synthetic)</span>
            <span className="choice-check" aria-hidden="true" />
          </span>
          <span className="choice-body" id="mode-demo-desc" style={{ display: "block" }}>
            Runs the full agent on fictional companies. <strong>No credits are used</strong> and the results are not
            a real assessment of any company. Good for trying the product.
          </span>
        </label>
      </div>
    </fieldset>
  );
}
