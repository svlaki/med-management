import type {
  ConditionInfo,
  GraphEdge,
  GraphNode,
  GraphPayload,
  MedicationCause,
  SideEffectReport,
} from "./types";

// The app is a static snapshot: it loads one pre-exported JSON file and does
// all filtering / lookups in the browser, so no backend or database is needed.

interface SnapshotSideEffect {
  side_effect_id: string;
  name: string;
  source: string;
  report_count: number | null;
  label_confirmed: boolean | null;
}

interface SnapshotMedication {
  rxcui: string;
  generic_name: string;
  drug_class: string | null;
  side_effects: SnapshotSideEffect[];
}

interface Snapshot {
  generated_at: string;
  conditions: ConditionInfo[];
  graphs: Record<string, { medications: SnapshotMedication[] }>;
}

const SIDE_EFFECT_LIMIT = 25;

let snapshotPromise: Promise<Snapshot> | null = null;

function loadSnapshot(): Promise<Snapshot> {
  if (snapshotPromise === null) {
    const url = `${import.meta.env.BASE_URL}snapshot.json`;
    snapshotPromise = fetch(url).then((response) => {
      if (!response.ok) throw new Error(`Could not load data (${response.status})`);
      return response.json() as Promise<Snapshot>;
    });
  }
  return snapshotPromise;
}

function byReportCountDesc(
  a: { report_count: number | null; name: string },
  b: { report_count: number | null; name: string },
): number {
  const diff = (b.report_count ?? 0) - (a.report_count ?? 0);
  return diff !== 0 ? diff : a.name.localeCompare(b.name);
}

function keptEffects(
  effects: SnapshotSideEffect[],
  confirmedOnly: boolean,
): SnapshotSideEffect[] {
  const filtered = confirmedOnly
    ? effects.filter((e) => e.label_confirmed === true)
    : effects;
  return [...filtered].sort(byReportCountDesc);
}

function allMedications(snapshot: Snapshot): SnapshotMedication[] {
  return Object.values(snapshot.graphs).flatMap((g) => g.medications);
}

export async function fetchConditions(): Promise<ConditionInfo[]> {
  return (await loadSnapshot()).conditions;
}

export async function fetchConditionGraph(
  conditionId: string,
  confirmedOnly: boolean,
  perMed: number,
): Promise<GraphPayload> {
  const snapshot = await loadSnapshot();
  const graph = snapshot.graphs[conditionId];
  if (!graph) throw new Error(`Unknown condition '${conditionId}'`);

  const conditionNodeId = `condition:${conditionId}`;
  const nodes = new Map<string, GraphNode>([
    [conditionNodeId, { id: conditionNodeId, label: conditionId.toUpperCase(), type: "condition" }],
  ]);
  const edges: GraphEdge[] = [];

  for (const med of graph.medications) {
    const medNodeId = `medication:${med.rxcui}`;
    nodes.set(medNodeId, { id: medNodeId, label: med.generic_name, type: "medication" });
    edges.push({
      source: medNodeId,
      target: conditionNodeId,
      kind: "treats",
      report_count: null,
      label_confirmed: null,
    });

    for (const effect of keptEffects(med.side_effects, confirmedOnly).slice(0, perMed)) {
      const effectNodeId = `side_effect:${effect.side_effect_id}`;
      nodes.set(effectNodeId, { id: effectNodeId, label: effect.name, type: "side_effect" });
      edges.push({
        source: medNodeId,
        target: effectNodeId,
        kind: "causes",
        report_count: effect.report_count,
        label_confirmed: effect.label_confirmed,
      });
    }
  }

  return { nodes: [...nodes.values()], edges };
}

export async function fetchSideEffects(
  rxcui: string,
  confirmedOnly: boolean,
): Promise<SideEffectReport[]> {
  const snapshot = await loadSnapshot();
  const med = allMedications(snapshot).find((m) => m.rxcui === rxcui);
  if (!med) return [];
  return keptEffects(med.side_effects, confirmedOnly).slice(0, SIDE_EFFECT_LIMIT);
}

export async function fetchMedicationsForSideEffect(
  sideEffectId: string,
): Promise<MedicationCause[]> {
  const snapshot = await loadSnapshot();
  const causes: MedicationCause[] = [];
  for (const med of allMedications(snapshot)) {
    const match = med.side_effects.find((e) => e.side_effect_id === sideEffectId);
    if (match) {
      causes.push({
        rxcui: med.rxcui,
        generic_name: med.generic_name,
        report_count: match.report_count,
      });
    }
  }
  return causes.sort((a, b) => {
    const diff = (b.report_count ?? 0) - (a.report_count ?? 0);
    return diff !== 0 ? diff : a.generic_name.localeCompare(b.generic_name);
  });
}
