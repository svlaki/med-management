import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import {
  fetchConditionGraph,
  fetchConditions,
  fetchConditionsForDrug,
  fetchDrugClasses,
  fetchDrugDetail,
  fetchMedicationsForCondition,
  fetchMedicationsForSideEffect,
  fetchSearchIndex,
  fetchSideEffects,
} from "./api";
import type { GraphPayload } from "./types";

/** Records requested URLs and replies with `success: true` envelopes. */
function stubFetch(responder: (url: string) => unknown) {
  const calls: string[] = [];
  const fake = vi.fn(async (url: string) => {
    calls.push(url);
    return {
      ok: true,
      status: 200,
      json: async () => ({ success: true, data: responder(url) }),
    } as Response;
  });
  vi.stubGlobal("fetch", fake);
  return calls;
}

beforeEach(() => vi.unstubAllGlobals());
afterEach(() => vi.unstubAllGlobals());

describe("request envelope", () => {
  it("prefixes every path with /api", async () => {
    const calls = stubFetch(() => []);
    await fetchConditions();
    expect(calls).toEqual(["/api/conditions"]);
  });

  it("throws on a non-ok HTTP status", async () => {
    vi.stubGlobal("fetch", async () => ({ ok: false, status: 503 }) as Response);
    await expect(fetchConditions()).rejects.toThrow(/503/);
  });

  it("surfaces the server's error message when success is false", async () => {
    vi.stubGlobal("fetch", async () => ({
      ok: true,
      status: 200,
      json: async () => ({ success: false, error: "Unknown condition 'nope'" }),
    }) as Response);
    await expect(fetchConditions()).rejects.toThrow("Unknown condition 'nope'");
  });

  it("throws when the envelope carries no data", async () => {
    vi.stubGlobal("fetch", async () => ({
      ok: true,
      status: 200,
      json: async () => ({ success: true }),
    }) as Response);
    await expect(fetchConditions()).rejects.toThrow(/no data/);
  });

  it("percent-encodes path segments", async () => {
    const calls = stubFetch(() => []);
    await fetchMedicationsForSideEffect("weight gain/loss");
    expect(calls[0]).toBe("/api/side-effects/weight%20gain%2Floss/medications");
  });
});

const GRAPH_A: GraphPayload = {
  nodes: [
    { id: "condition:mdd", label: "MDD", type: "condition" },
    { id: "drug:36437", label: "sertraline", type: "drug", drug_class: "SSRI" },
    { id: "side_effect:nausea", label: "Nausea", type: "side_effect" },
  ],
  edges: [
    { source: "drug:36437", target: "condition:mdd", kind: "may_treat", report_count: null },
    { source: "drug:36437", target: "side_effect:nausea", kind: "has_side_effect", report_count: 100 },
  ],
};
const GRAPH_B: GraphPayload = {
  nodes: [
    { id: "condition:gad", label: "GAD", type: "condition" },
    // sertraline appears in both graphs and must not be duplicated
    { id: "drug:36437", label: "sertraline", type: "drug", drug_class: "SSRI" },
    { id: "drug:42347", label: "bupropion", type: "drug", drug_class: "NDRI" },
    { id: "side_effect:nausea", label: "Nausea", type: "side_effect" },
  ],
  edges: [
    { source: "drug:36437", target: "condition:gad", kind: "may_treat", report_count: null },
    { source: "drug:42347", target: "condition:gad", kind: "may_treat", report_count: null },
    // duplicate of an edge in GRAPH_A
    { source: "drug:36437", target: "side_effect:nausea", kind: "has_side_effect", report_count: 100 },
  ],
};

function stubGraphs() {
  return stubFetch((url) => (url.includes("/mdd/") ? GRAPH_A : GRAPH_B));
}

describe("fetchConditionGraph", () => {
  it("returns an empty graph without fetching when nothing is selected", async () => {
    const calls = stubFetch(() => GRAPH_A);
    const graph = await fetchConditionGraph([], 6);
    expect(graph).toEqual({ nodes: [], edges: [] });
    expect(calls).toEqual([]);
  });

  it("requests one graph per selected condition and passes per_med", async () => {
    const calls = stubGraphs();
    await fetchConditionGraph(["mdd", "gad"], 3);
    expect(calls).toEqual([
      "/api/conditions/mdd/graph?per_med=3",
      "/api/conditions/gad/graph?per_med=3",
    ]);
  });

  it("merges multiple conditions instead of dropping all but the first", async () => {
    stubGraphs();
    const graph = await fetchConditionGraph(["mdd", "gad"], 6);
    const ids = graph.nodes.map((n) => n.id);
    expect(ids).toContain("condition:mdd");
    expect(ids).toContain("condition:gad");
    expect(ids).toContain("drug:42347");
  });

  it("dedupes nodes and edges shared between conditions", async () => {
    stubGraphs();
    const graph = await fetchConditionGraph(["mdd", "gad"], 6);
    expect(graph.nodes.filter((n) => n.id === "drug:36437")).toHaveLength(1);
    const nausea = graph.edges.filter(
      (e) => e.source === "drug:36437" && e.target === "side_effect:nausea",
    );
    expect(nausea).toHaveLength(1);
  });

  it("keeps only drugs in the selected classes", async () => {
    stubGraphs();
    const graph = await fetchConditionGraph(["mdd", "gad"], 6, ["NDRI"]);
    const drugs = graph.nodes.filter((n) => n.type === "drug").map((n) => n.id);
    expect(drugs).toEqual(["drug:42347"]);
  });

  it("drops nodes orphaned by the class filter", async () => {
    stubGraphs();
    const graph = await fetchConditionGraph(["mdd", "gad"], 6, ["NDRI"]);
    const ids = graph.nodes.map((n) => n.id);
    // bupropion only links to gad, so mdd and nausea have no kept edges
    expect(ids).toContain("condition:gad");
    expect(ids).not.toContain("condition:mdd");
    expect(ids).not.toContain("side_effect:nausea");
  });

  it("an empty class filter keeps every drug", async () => {
    stubGraphs();
    const graph = await fetchConditionGraph(["mdd", "gad"], 6, []);
    const drugs = graph.nodes.filter((n) => n.type === "drug").map((n) => n.id).sort();
    expect(drugs).toEqual(["drug:36437", "drug:42347"]);
  });
});

describe("endpoint shapes", () => {
  it("fetchSideEffects caps the result set", async () => {
    const calls = stubFetch(() => []);
    await fetchSideEffects("36437");
    expect(calls[0]).toBe("/api/medications/36437/side-effects?limit=25");
  });

  it("fetchDrugClasses returns just the names", async () => {
    stubFetch(() => [
      { id: "ssri", name: "SSRI" },
      { id: "ndri", name: "NDRI" },
    ]);
    expect(await fetchDrugClasses()).toEqual(["SSRI", "NDRI"]);
  });

  it("fetchDrugDetail passes a null body through", async () => {
    stubFetch(() => null);
    expect(await fetchDrugDetail("00000")).toBeNull();
  });

  it("fetchConditionsForDrug requests the drug's conditions", async () => {
    const calls = stubFetch(() => []);
    await fetchConditionsForDrug("36437");
    expect(calls[0]).toBe("/api/drugs/36437/conditions");
  });

  it("fetchMedicationsForCondition requests the condition's drugs", async () => {
    const calls = stubFetch(() => []);
    await fetchMedicationsForCondition("mdd");
    expect(calls[0]).toBe("/api/conditions/mdd/medications");
  });

  it("fetchSearchIndex builds graph node ids from type and id", async () => {
    stubFetch(() => [
      { type: "drug", id: "36437", label: "sertraline" },
      { type: "condition", id: "mdd", label: "Major Depressive Disorder" },
      { type: "side_effect", id: "nausea", label: "Nausea" },
    ]);
    expect(await fetchSearchIndex()).toEqual([
      { nodeId: "drug:36437", label: "sertraline", type: "drug" },
      { nodeId: "condition:mdd", label: "Major Depressive Disorder", type: "condition" },
      { nodeId: "side_effect:nausea", label: "Nausea", type: "side_effect" },
    ]);
  });
});
