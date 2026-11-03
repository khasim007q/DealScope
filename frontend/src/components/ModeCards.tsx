import type { RunMode, StatusResponse } from "../api/types";
import { formatCredits } from "../lib/format";

interface Props {
  mode: RunMode;
  onChange: (m: RunMode) => void;
  status: StatusResponse | null;
  statusError: string | null;
}

/** Two quiet selectable panels (radio group) for choosing live vs demo data. */
export function ModeCards({ mode, onChange, status, statusError }: Props) {
  const liveAvailable = status?.live_available ?? false;
  const budget = status?.live_budget;

  return (
    <fieldset>
      <legend className="sr-only">Data source</legend>
      <div className="mode-panels">
        <label className={`mode-panel${mode === "live" ? " selected" : ""}${liveAvailable ? "" : " disabled"}`}>
          <input
            type="radio"
            name="mode"
            value="live"
            checked={mode === "live"}
            disabled={!liveAvailable}
            onChange={() => onChange("live")}
            aria-describedby="mode-live-desc"
          />
          <span className="mode-head">
            <span className="mode-mark" aria-hidden="true" />
            <span className="mode-title">Live data (Crustdata)</span>
          </span>
          <span className="mode-body" id="mode-live-desc">
            Investigates the real companies you enter using public company, people-history and job-posting data.
            <strong className="mode-spend"> This spends real Crustdata credits.</strong>
            {budget ? (
              <span className="mode-budget">
                Live budget remaining: <strong>{formatCredits(budget.remaining)}</strong> of{" "}
                {formatCredits(budget.spendable)} credits. A reserve of {formatCredits(budget.reserve)} credits is
                always held back and never spent.
              </span>
            ) : null}
            {!liveAvailable ? (
              <span className="mode-budget mode-unavailable">
                {statusError
                  ? "Unavailable: the server status could not be loaded."
                  : "Unavailable: Crustdata is not connected on this server. Live runs are never simulated."}
              </span>
            ) : null}
          </span>
        </label>

        <label className={`mode-panel${mode === "synthetic" ? " selected" : ""}`}>
          <input
            type="radio"
            name="mode"
            value="synthetic"
            checked={mode === "synthetic"}
            onChange={() => onChange("synthetic")}
            aria-describedby="mode-demo-desc"
          />
          <span className="mode-head">
            <span className="mode-mark" aria-hidden="true" />
            <span className="mode-title">Demo data (synthetic)</span>
          </span>
          <span className="mode-body" id="mode-demo-desc">
            Runs the full agent on fictional companies. <strong>No credits are used</strong> and the results are not a
            real assessment of any company. Good for trying the product.
          </span>
        </label>
      </div>
    </fieldset>
  );
}
