import { useEffect, useRef } from "react";
import type { ConditionInfo } from "../types";

interface Props {
  conditions: ConditionInfo[];
  selectedIds: string[];
  confirmedOnly: boolean;
  approvedOnly: boolean;
  perMed: number;
  drugClasses: string[];
  classFilter: string[];
  onSelectionChange: (ids: string[]) => void;
  onConfirmedChange: (value: boolean) => void;
  onApprovedChange: (value: boolean) => void;
  onPerMedChange: (value: number) => void;
  onClassFilterChange: (classes: string[]) => void;
}

export function Controls({
  conditions,
  selectedIds,
  confirmedOnly,
  approvedOnly,
  perMed,
  drugClasses,
  classFilter,
  onSelectionChange,
  onConfirmedChange,
  onApprovedChange,
  onPerMedChange,
  onClassFilterChange,
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

  function toggleClass(name: string) {
    onClassFilterChange(
      classFilter.includes(name)
        ? classFilter.filter((c) => c !== name)
        : [...classFilter, name],
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

      {drugClasses.length > 0 && (
        <fieldset className="control control--group">
          <legend>Drug class</legend>
          <label className="control control--row">
            <input
              type="checkbox"
              checked={classFilter.length === 0}
              onChange={() => onClassFilterChange([])}
            />
            <span>All classes</span>
          </label>
          {drugClasses.map((name) => (
            <label className="control control--row" key={name}>
              <input
                type="checkbox"
                checked={classFilter.includes(name)}
                onChange={() => toggleClass(name)}
              />
              <span>{name}</span>
            </label>
          ))}
        </fieldset>
      )}

      <label className="control control--row">
        <input
          type="checkbox"
          checked={approvedOnly}
          onChange={(e) => onApprovedChange(e.target.checked)}
        />
        <span>FDA-approved for the condition only</span>
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
