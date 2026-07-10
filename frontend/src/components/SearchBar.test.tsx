import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { SearchBar } from "./SearchBar";
import type { SearchEntry } from "../types";

const ENTRIES: SearchEntry[] = [
  { nodeId: "condition:mdd", label: "Major Depressive Disorder", type: "condition", conditionIds: ["mdd"] },
  { nodeId: "medication:1", label: "sertraline", type: "medication", conditionIds: ["mdd"] },
  { nodeId: "medication:2", label: "sertraline hydrochloride", type: "medication", conditionIds: ["mdd"] },
  { nodeId: "side_effect:nausea", label: "Nausea", type: "side_effect", conditionIds: ["mdd"] },
];

afterEach(cleanup);

function setup() {
  const onPick = vi.fn();
  render(<SearchBar entries={ENTRIES} onPick={onPick} />);
  const input = screen.getByRole("searchbox");
  return { onPick, input };
}

describe("SearchBar", () => {
  it("shows no results for an empty query", () => {
    const { input } = setup();
    fireEvent.focus(input);
    expect(screen.queryByRole("button")).toBeNull();
  });

  it("filters case-insensitively by substring", () => {
    const { input } = setup();
    fireEvent.change(input, { target: { value: "naus" } });
    const results = screen.getAllByRole("button");
    expect(results).toHaveLength(1);
    expect(results[0].textContent).toContain("Nausea");
  });

  it("orders prefix matches before mid-string matches", () => {
    const { input } = setup();
    fireEvent.change(input, { target: { value: "sertraline" } });
    const labels = screen.getAllByRole("button").map((b) => b.textContent);
    // both start with "sertraline"; shorter label first
    expect(labels[0]).toContain("sertraline");
    expect(labels[0]).not.toContain("hydrochloride");
  });

  it("picks a result on click and clears the query", () => {
    const { input, onPick } = setup();
    fireEvent.change(input, { target: { value: "sertra" } });
    fireEvent.click(screen.getAllByRole("button")[0]);
    expect(onPick).toHaveBeenCalledWith(
      expect.objectContaining({ nodeId: "medication:1" }),
    );
    expect((input as HTMLInputElement).value).toBe("");
  });

  it("Enter picks the first result", () => {
    const { input, onPick } = setup();
    fireEvent.change(input, { target: { value: "major" } });
    fireEvent.keyDown(input, { key: "Enter" });
    expect(onPick).toHaveBeenCalledWith(
      expect.objectContaining({ nodeId: "condition:mdd" }),
    );
  });

  it("Escape closes the results list", () => {
    const { input } = setup();
    fireEvent.change(input, { target: { value: "naus" } });
    expect(screen.getAllByRole("button")).toHaveLength(1);
    fireEvent.keyDown(input, { key: "Escape" });
    expect(screen.queryByRole("button")).toBeNull();
  });
});
