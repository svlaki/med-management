import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
import { Legend } from "./Legend";
import { NODE_COLORS, NODE_LABELS } from "../theme";

afterEach(cleanup);

describe("Legend", () => {
  it("names exactly the three kinds of node in the graph", () => {
    render(<Legend />);
    expect(screen.getByText("Disorder")).toBeTruthy();
    expect(screen.getByText("Drug")).toBeTruthy();
    expect(screen.getByText("Side effect")).toBeTruthy();
  });

  it("does not advertise drug classes as nodes", () => {
    // DrugClass exists in the database only to back the class filter; it is
    // never drawn, so it must not appear in the legend.
    render(<Legend />);
    expect(screen.queryByText(/Drug class/i)).toBeNull();
  });

  it("the theme defines a colour and label for each node type and no more", () => {
    expect(Object.keys(NODE_LABELS).sort()).toEqual([
      "condition",
      "drug",
      "side_effect",
    ]);
    expect(Object.keys(NODE_COLORS).sort()).toEqual([
      "condition",
      "drug",
      "side_effect",
    ]);
  });

  it("labels condition nodes as disorders", () => {
    // The graph is scoped to psychiatric disorders, so the generic term
    // "Condition" would overstate what a red node represents.
    expect(NODE_LABELS.condition).toBe("Disorder");
  });
});
