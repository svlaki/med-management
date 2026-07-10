import { useEffect, useRef } from "react";
import type { ConditionInfo } from "../types";

interface Props {
  conditions: ConditionInfo[];
  selectedIds: string[];
  confirmedOnly: boolean;
  perMed: number;
  onSelectionChange: (ids: string[]) => void;
  onConfirmedChange: (value: boolean) => void;
  onPerMedChange: (value: number) => void;
}

export function Controls({
  conditions,
  selectedIds,
  confirmedOnly,
  perMed,
  onSelectionChange,
  onConfirmedChange,
  onPerMedChange,
}: Props) {
  const allSelected =
    conditions.length > 0 && selectedIds.length === conditions.length;
  const masterRef = useRef<HTMLInputElement>(null);

  // React has no `indeterminate` prop; set it on the DOM node directly.
  useEffect(() => {
    if (masterRef.current) {
      masterRef.current.indeterminate = selectedIds.length > 0 && !allSelected;
    }
  }, [selectedIds.length, allSelected]);

  function toggle(id: string) {
    onSelectionChange(
      selectedIds.includes(id)
        ? selectedIds.filter((s) => s !== id)
        : [...selectedIds, id],
    );
  }

  return (
    <div className="controls">
      <fieldset className="control control--group">
        <legend>Conditions</legend>
        <label className="control control--row">
          <input
            ref={masterRef}
            type="checkbox"
            checked={allSelected}
            onChange={(e) =>
              onSelectionChange(e.target.checked ? conditions.map((c) => c.id) : [])
            }
          />
          <span>All conditions</span>
        </label>
        {conditions.map((condition) => (
          <label className="control control--row" key={condition.id}>
            <input
              type="checkbox"
              checked={selectedIds.includes(condition.id)}
              onChange={() => toggle(condition.id)}
            />
            <span>{condition.name}</span>
          </label>
        ))}
      </fieldset>

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
