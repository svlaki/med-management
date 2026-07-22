import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { Controls } from "./Controls";
import type { ConditionInfo } from "../types";

const CONDITIONS: ConditionInfo[] = [
  { id: "mdd", name: "Major Depressive Disorder", icd10: "F33" },
  { id: "bipolar", name: "Bipolar Disorder", icd10: "F31" },
];

afterEach(cleanup);

function setup(selectedIds: string[], drugClasses: string[] = []) {
  const onSelectionChange = vi.fn();
  const onApprovedChange = vi.fn();
  const onClassFilterChange = vi.fn();
  render(
    <Controls
      conditions={CONDITIONS}
      selectedIds={selectedIds}
      confirmedOnly={false}
      approvedOnly={false}
      perMed={6}
      drugClasses={drugClasses}
      classFilter={[]}
      onSelectionChange={onSelectionChange}
      onConfirmedChange={vi.fn()}
      onApprovedChange={onApprovedChange}
      onPerMedChange={vi.fn()}
      onClassFilterChange={onClassFilterChange}
    />,
  );
  return { onSelectionChange, onApprovedChange, onClassFilterChange };
}

function box(name: RegExp) {
  return screen.getByRole("checkbox", { name }) as HTMLInputElement;
}

describe("Controls condition multi-select", () => {
  it("adds a condition when toggled on", () => {
    const { onSelectionChange } = setup([]);
    fireEvent.click(box(/Bipolar Disorder/));
    expect(onSelectionChange).toHaveBeenCalledWith(["bipolar"]);
  });

  it("removes a condition when toggled off", () => {
    const { onSelectionChange } = setup(["mdd", "bipolar"]);
    fireEvent.click(box(/Major Depressive Disorder/));
    expect(onSelectionChange).toHaveBeenCalledWith(["bipolar"]);
  });

  it("the master toggle selects every condition", () => {
    const { onSelectionChange } = setup([]);
    fireEvent.click(box(/All conditions/));
    expect(onSelectionChange).toHaveBeenCalledWith(["mdd", "bipolar"]);
  });

  it("the master toggle clears the selection when all are selected", () => {
    const { onSelectionChange } = setup(["mdd", "bipolar"]);
    fireEvent.click(box(/All conditions/));
    expect(onSelectionChange).toHaveBeenCalledWith([]);
  });

  it("shows the master as indeterminate on a partial selection", () => {
    setup(["mdd"]);
    const master = box(/All conditions/);
    expect(master.checked).toBe(false);
    expect(master.indeterminate).toBe(true);
  });

  it("shows the master as checked when all are selected", () => {
    setup(["mdd", "bipolar"]);
    const master = box(/All conditions/);
    expect(master.checked).toBe(true);
    expect(master.indeterminate).toBe(false);
  });

  it("toggles the FDA-approved-only filter", () => {
    const { onApprovedChange } = setup([]);
    fireEvent.click(box(/FDA-approved for the condition only/));
    expect(onApprovedChange).toHaveBeenCalledWith(true);
  });
});

describe("Controls drug-class filter", () => {
  it("hides the drug-class fieldset when no classes are known", () => {
    setup([]);
    expect(screen.queryByText("Drug class")).toBeNull();
  });

  it("selects a class when toggled on", () => {
    const { onClassFilterChange } = setup([], ["Antidepressant", "Antipsychotic"]);
    fireEvent.click(box(/Antidepressant/));
    expect(onClassFilterChange).toHaveBeenCalledWith(["Antidepressant"]);
  });

  it("the all-classes toggle clears the class filter", () => {
    const { onClassFilterChange } = setup([], ["Antidepressant"]);
    fireEvent.click(box(/All classes/));
    expect(onClassFilterChange).toHaveBeenCalledWith([]);
  });
});
