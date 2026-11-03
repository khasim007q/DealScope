import type { Scenario } from "../api/types";

interface Props {
  scenarios: Scenario[];
  selectedId: string | null;
  onSelect: (s: Scenario) => void;
}

/** Compact ruled list of demo scenarios (radio group). Selecting one fills in the brief. */
export function ScenarioPicker({ scenarios, selectedId, onSelect }: Props) {
  if (scenarios.length === 0) return null;
  return (
    <fieldset className="field scenario-picker">
      <legend className="label">Demo scenario</legend>
      <p className="help scenario-help">Choose a fictional case. Selecting one fills in the brief below.</p>
      <ul className="scenario-list">
        {scenarios.map((s) => {
          const selected = s.id === selectedId;
          return (
            <li key={s.id}>
              <label className={`scenario-row${selected ? " selected" : ""}`}>
                <input type="radio" name="scenario" value={s.id} checked={selected} onChange={() => onSelect(s)} />
                <span className="mode-mark" aria-hidden="true" />
                <span className="scenario-text">
                  <span className="scenario-title">{s.label}</span>
                  <span className="scenario-desc">{s.description}</span>
                </span>
              </label>
            </li>
          );
        })}
      </ul>
    </fieldset>
  );
}
