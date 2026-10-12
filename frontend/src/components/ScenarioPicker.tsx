import type { Scenario } from "../api/types";

interface Props {
  scenarios: Scenario[];
  selectedId: string | null;
  onSelect: (s: Scenario) => void;
}

export function ScenarioPicker({ scenarios, selectedId, onSelect }: Props) {
  if (scenarios.length === 0) return null;
  return (
    <fieldset className="field">
      <legend className="label">Demo scenario</legend>
      <p className="help" style={{ marginTop: 0, marginBottom: 8 }}>
        Choose a fictional case. Selecting one fills in the form below.
      </p>
      <div className="choice-grid">
        {scenarios.map((s) => {
          const selected = s.id === selectedId;
          return (
            <label key={s.id} className={`choice${selected ? " selected" : ""}`}>
              <input
                type="radio"
                name="scenario"
                value={s.id}
                checked={selected}
                onChange={() => onSelect(s)}
              />
              <span className="choice-title">
                <span>{s.label}</span>
                <span className="choice-check" aria-hidden="true" />
              </span>
              <span className="choice-body" style={{ display: "block" }}>
                {s.description}
              </span>
            </label>
          );
        })}
      </div>
    </fieldset>
  );
}
