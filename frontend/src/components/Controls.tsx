import type { ConditionInfo } from "../types";

interface Props {
  conditions: ConditionInfo[];
  conditionId: string;
  confirmedOnly: boolean;
  perMed: number;
  onConditionChange: (id: string) => void;
  onConfirmedChange: (value: boolean) => void;
  onPerMedChange: (value: number) => void;
}

export function Controls({
  conditions,
  conditionId,
  confirmedOnly,
  perMed,
  onConditionChange,
  onConfirmedChange,
  onPerMedChange,
}: Props) {
  return (
    <div className="controls">
      <label className="control">
        <span>Condition</span>
        <select
          value={conditionId}
          onChange={(e) => onConditionChange(e.target.value)}
        >
          {conditions.map((c) => (
            <option key={c.id} value={c.id}>
              {c.name}
            </option>
          ))}
        </select>
      </label>

      <label className="control control--row">
        <input
          type="checkbox"
          checked={confirmedOnly}
          onChange={(e) => onConfirmedChange(e.target.checked)}
        />
        <span>Label-confirmed side effects only</span>
      </label>

      <label className="control">
        <span>Side effects per medication: {perMed}</span>
        <input
          type="range"
          min={1}
          max={20}
          value={perMed}
          onChange={(e) => onPerMedChange(Number(e.target.value))}
        />
      </label>
    </div>
  );
}
