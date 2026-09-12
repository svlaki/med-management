import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { Controls } from "./Controls";
import type { ConditionInfo } from "../types";

const CONDITIONS: ConditionInfo[] = [
  { id: "mdd", name: "Major Depressive Disorder" },
  { id: "bipolar", name: "Bipolar Disorder" },
];

afterEach(cleanup);

function setup(selectedIds: string[], drugClasses: string[] = []) {
  const onSelectionChange = vi.fn();
  const onClassFilterChange = vi.fn();
  render(
    <Controls
      conditions={CONDITIONS}
      selectedIds={selectedIds}
      perMed={6}
      drugClasses={drugClasses}
      classFilter={[]}
      onSelectionChange={onSelectionChange}
      onPerMedChange={vi.fn()}
      onClassFilterChange={onClassFilterChange}
    />,
  );
  return { onSelectionChange, onClassFilterChange };
}

function box(name: RegExp) {
  return screen.getByRole("checkbox", { name }) as HTMLInputElement;
}

describe("Controls disorder multi-select", () => {
  it("adds a disorder when toggled on", () => {
    const { onSelectionChange } = setup([]);
    fireEvent.click(box(/Bipolar Disorder/));
    expect(onSelectionChange).toHaveBeenCalledWith(["bipolar"]);
  });

  it("removes a disorder when toggled off", () => {
    const { onSelectionChange } = setup(["mdd", "bipolar"]);
    fireEvent.click(box(/Major Depressive Disorder/));
    expect(onSelectionChange).toHaveBeenCalledWith(["bipolar"]);
  });

  it("the master toggle selects every disorder", () => {
    const { onSelectionChange } = setup([]);
    fireEvent.click(box(/All disorders/));
    expect(onSelectionChange).toHaveBeenCalledWith(["mdd", "bipolar"]);
  });

  it("the master toggle clears the selection when all are selected", () => {
    const { onSelectionChange } = setup(["mdd", "bipolar"]);
    fireEvent.click(box(/All disorders/));
    expect(onSelectionChange).toHaveBeenCalledWith([]);
  });

  it("shows the master as indeterminate on a partial selection", () => {
    setup(["mdd"]);
    const master = box(/All disorders/);
    expect(master.checked).toBe(false);
    expect(master.indeterminate).toBe(true);
  });

  it("shows the master as checked when all are selected", () => {
    setup(["mdd", "bipolar"]);
    const master = box(/All disorders/);
    expect(master.checked).toBe(true);
    expect(master.indeterminate).toBe(false);
  });

  it("offers no filter that the backend cannot honour", () => {
    // label_confirmed / fda_approved are not on the graph, so those toggles
    // were removed rather than left silently inert.
    setup([]);
    expect(screen.queryByText(/FDA-approved for the condition only/)).toBeNull();
    expect(screen.queryByText(/Label-confirmed side effects only/)).toBeNull();
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
