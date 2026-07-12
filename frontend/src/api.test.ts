import { beforeAll, describe, expect, it, vi } from "vitest";
import {
  fetchConditionGraph,
  fetchConditions,
  fetchConditionsForMedication,
  fetchMedicationsForCondition,
  fetchMedicationsForSideEffect,
  fetchSearchIndex,
  fetchSideEffects,
} from "./api";

// Two conditions; med "3" (shared) treats both — the dedup-critical case.
const SNAPSHOT = {
  generated_at: "2026-07-09T00:00:00Z",
  conditions: [
    { id: "mdd", name: "Major Depressive Disorder", icd10: "F33" },
    { id: "bipolar", name: "Bipolar Disorder", icd10: "F31" },
  ],
  graphs: {
    mdd: {
      medications: [
        {
          rxcui: "1",
          generic_name: "sertraline",
          drug_class: null,
          fda_approved: true, // approved for MDD
          side_effects: [
            { side_effect_id: "nausea", name: "Nausea", source: "faers",
              report_count: 100, label_confirmed: true },
            { side_effect_id: "insomnia", name: "Insomnia", source: "faers",
              report_count: 50, label_confirmed: false },
          ],
        },
        {
          rxcui: "3",
          generic_name: "quetiapine",
          drug_class: null,
          fda_approved: false, // "may treat" MDD only (off-label)
          side_effects: [
            { side_effect_id: "nausea", name: "Nausea", source: "faers",
              report_count: 80, label_confirmed: true },
          ],
        },
      ],
    },
    bipolar: {
      medications: [
        {
          rxcui: "2",
          generic_name: "lamotrigine",
          drug_class: null,
          fda_approved: true,
          side_effects: [
            { side_effect_id: "rash", name: "Rash", source: "faers",
              report_count: 70, label_confirmed: true },
          ],
        },
        {
          rxcui: "3",
          generic_name: "quetiapine",
          drug_class: null,
          fda_approved: true, // approved for bipolar
          side_effects: [
            { side_effect_id: "nausea", name: "Nausea", source: "faers",
              report_count: 80, label_confirmed: true },
          ],
        },
      ],
    },
  },
};

beforeAll(() => {
  // api.ts caches the snapshot promise module-wide; one stub serves all tests.
  vi.stubGlobal(
    "fetch",
    vi.fn(async () => ({ ok: true, json: async () => SNAPSHOT })),
  );
});

describe("fetchConditions", () => {
  it("returns the snapshot conditions unchanged", async () => {
    const conditions = await fetchConditions();
    expect(conditions.map((c) => c.id)).toEqual(["mdd", "bipolar"]);
  });
});

describe("fetchConditionGraph — multi-select", () => {
  it("returns an empty graph for an empty selection", async () => {
    const graph = await fetchConditionGraph([], false, 10);
    expect(graph.nodes).toHaveLength(0);
    expect(graph.edges).toHaveLength(0);
  });

  it("renders a single selected condition's subgraph", async () => {
    const graph = await fetchConditionGraph(["mdd"], false, 10);
    expect(graph.nodes.filter((n) => n.type === "condition")).toHaveLength(1);
    expect(graph.nodes.filter((n) => n.type === "medication")).toHaveLength(2);
  });

  it("labels condition nodes with the display name", async () => {
    const graph = await fetchConditionGraph(["mdd", "bipolar"], false, 10);
    const labels = graph.nodes
      .filter((n) => n.type === "condition")
      .map((n) => n.label);
    expect(new Set(labels)).toEqual(
      new Set(["Major Depressive Disorder", "Bipolar Disorder"]),
    );
  });

  it("dedupes shared medication nodes but keeps a treats edge per condition", async () => {
    const graph = await fetchConditionGraph(["mdd", "bipolar"], false, 10);
    expect(graph.nodes.filter((n) => n.type === "medication")).toHaveLength(3);
    const sharedTreats = graph.edges.filter(
      (e) => e.kind === "treats" && e.source === "medication:3",
    );
    expect(sharedTreats.map((e) => e.target).sort()).toEqual([
      "condition:bipolar",
      "condition:mdd",
    ]);
  });

  it("adds a shared med's causes edges exactly once", async () => {
    const graph = await fetchConditionGraph(["mdd", "bipolar"], false, 10);
    const sharedCauses = graph.edges.filter(
      (e) => e.kind === "causes" && e.source === "medication:3",
    );
    expect(sharedCauses).toHaveLength(1);
  });

  it("has no duplicate node ids", async () => {
    const graph = await fetchConditionGraph(["mdd", "bipolar"], false, 10);
    const ids = graph.nodes.map((n) => n.id);
    expect(new Set(ids).size).toBe(ids.length);
  });

  it("rejects an unknown condition", async () => {
    await expect(fetchConditionGraph(["gout"], false, 10)).rejects.toThrow("gout");
  });

  it("applies confirmed-only filtering and the per-med limit", async () => {
    const confirmed = await fetchConditionGraph(["mdd"], true, 10);
    const sertralineCauses = confirmed.edges.filter(
      (e) => e.kind === "causes" && e.source === "medication:1",
    );
    expect(sertralineCauses).toHaveLength(1); // insomnia (unconfirmed) dropped

    const limited = await fetchConditionGraph(["mdd"], false, 1);
    const limitedCauses = limited.edges.filter(
      (e) => e.kind === "causes" && e.source === "medication:1",
    );
    expect(limitedCauses).toHaveLength(1); // top-1 by report count
    expect(limitedCauses[0].target).toBe("side_effect:nausea");
  });

  it("tags treats edges with FDA approval", async () => {
    const graph = await fetchConditionGraph(["mdd"], false, 10);
    const treats = graph.edges.filter((e) => e.kind === "treats");
    const byMed = Object.fromEntries(treats.map((e) => [e.source, e.fda_approved]));
    expect(byMed["medication:1"]).toBe(true); // sertraline approved
    expect(byMed["medication:3"]).toBe(false); // quetiapine may-treat only
  });

  it("approved-only drops may-treat meds for that condition", async () => {
    const graph = await fetchConditionGraph(["mdd"], false, 10, true);
    const medNodes = graph.nodes.filter((n) => n.type === "medication");
    expect(medNodes.map((n) => n.id)).toEqual(["medication:1"]); // quetiapine gone
  });

  it("respects per-condition approval in a multi-select approved view", async () => {
    // quetiapine is approved for bipolar but not MDD; approved-only keeps its
    // bipolar treats edge and drops the MDD one.
    const graph = await fetchConditionGraph(["mdd", "bipolar"], false, 10, true);
    const quetTreats = graph.edges.filter(
      (e) => e.kind === "treats" && e.source === "medication:3",
    );
    expect(quetTreats.map((e) => e.target)).toEqual(["condition:bipolar"]);
  });
});

describe("panel lookups", () => {
  it("lists the conditions a medication treats, with per-condition approval", async () => {
    const treats = await fetchConditionsForMedication("3");
    expect(treats.map((c) => c.id).sort()).toEqual(["bipolar", "mdd"]);
    const approvalById = Object.fromEntries(treats.map((c) => [c.id, c.fda_approved]));
    expect(approvalById).toEqual({ mdd: false, bipolar: true });
    const single = await fetchConditionsForMedication("1");
    expect(single.map((c) => c.id)).toEqual(["mdd"]);
  });

  it("lists a condition's medications with counts and approval", async () => {
    const meds = await fetchMedicationsForCondition("mdd");
    expect(meds.map((m) => m.generic_name).sort()).toEqual([
      "quetiapine",
      "sertraline",
    ]);
    const sertraline = meds.find((m) => m.rxcui === "1");
    expect(sertraline?.side_effect_count).toBe(2);
    expect(sertraline?.fda_approved).toBe(true);
    expect(meds.find((m) => m.rxcui === "3")?.fda_approved).toBe(false);
  });

  it("lists a shared side effect's medications once each", async () => {
    const causes = await fetchMedicationsForSideEffect("nausea");
    const rxcuis = causes.map((c) => c.rxcui);
    expect(new Set(rxcuis).size).toBe(rxcuis.length);
    expect(rxcuis.sort()).toEqual(["1", "3"]);
  });

  it("finds side effects for a med regardless of which condition entry holds it", async () => {
    const effects = await fetchSideEffects("2", false);
    expect(effects.map((e) => e.side_effect_id)).toEqual(["rash"]);
  });
});

describe("fetchSearchIndex", () => {
  it("indexes conditions, deduped medications, and deduped side effects", async () => {
    const index = await fetchSearchIndex();
    const byType = (t: string) => index.filter((e) => e.type === t);
    expect(byType("condition").map((e) => e.nodeId).sort()).toEqual([
      "condition:bipolar",
      "condition:mdd",
    ]);
    expect(byType("medication")).toHaveLength(3); // shared med once
    // nausea, insomnia, rash — nausea appears under two meds but indexes once
    expect(byType("side_effect")).toHaveLength(3);
  });

  it("records which conditions each entry belongs to", async () => {
    const index = await fetchSearchIndex();
    const shared = index.find((e) => e.nodeId === "medication:3");
    expect(shared?.conditionIds.sort()).toEqual(["bipolar", "mdd"]);
    const rash = index.find((e) => e.nodeId === "side_effect:rash");
    expect(rash?.conditionIds).toEqual(["bipolar"]);
  });
});
