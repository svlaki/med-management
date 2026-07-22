import type {
  ConditionInfo,
  GraphEdge,
  GraphNode,
  GraphPayload,
  MedicationCause,
  MedicationPharmacology,
  MedicationSummary,
  MedicationTreats,
  SearchEntry,
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
  atc_codes: string | null;
  mechanism: string | null;
  neurotransmitters: string | null;
  // whether an FDA label names THIS condition (per-condition in the snapshot)
  fda_approved: boolean;
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

/** Every medication across all conditions, deduped by rxcui (a med treating
 * two conditions appears once per condition in the snapshot). */
function dedupedMedications(snapshot: Snapshot): SnapshotMedication[] {
  const byRxcui = new Map<string, SnapshotMedication>();
  for (const graph of Object.values(snapshot.graphs)) {
    for (const med of graph.medications) {
      if (!byRxcui.has(med.rxcui)) byRxcui.set(med.rxcui, med);
    }
  }
  return [...byRxcui.values()];
}

export async function fetchConditions(): Promise<ConditionInfo[]> {
  return (await loadSnapshot()).conditions;
}

/** Build the graph for any set of selected conditions (empty set = empty graph).
 * An empty `classes` list means "all drug classes"; otherwise only medications
 * whose `drug_class` is in the list are included. */
export async function fetchConditionGraph(
  conditionIds: string[],
  confirmedOnly: boolean,
  perMed: number,
  approvedOnly: boolean = false,
  classes: string[] = [],
): Promise<GraphPayload> {
  const snapshot = await loadSnapshot();
  const unknown = conditionIds.filter((id) => !snapshot.graphs[id]);
  if (unknown.length > 0) {
    throw new Error(`Unknown condition '${unknown.join(", ")}'`);
  }

  const nodes = new Map<string, GraphNode>();
  const edges: GraphEdge[] = [];
  // A med treating several conditions gets a treats edge per condition, but
  // its side-effect edges must be added only once. First occurrence wins,
  // which is safe because the snapshot exporter queries side effects per
  // medication (not per condition), so every occurrence of an rxcui carries
  // an identical side_effects array within one export.
  const processedRxcuis = new Set<string>();
  const conditionNames = new Map(
    snapshot.conditions.map((c) => [c.id, c.name]),
  );

  for (const id of conditionIds) {
    const conditionNodeId = `condition:${id}`;
    nodes.set(conditionNodeId, {
      id: conditionNodeId,
      label: conditionNames.get(id) ?? id.toUpperCase(),
      type: "condition",
    });

    for (const med of snapshot.graphs[id].medications) {
      // approved-only hides meds that are only RxClass "may treat" for this
      // condition (no FDA label naming it).
      if (approvedOnly && !med.fda_approved) continue;
      // class filter: keep only medications in the selected drug classes.
      if (classes.length > 0 && (med.drug_class === null || !classes.includes(med.drug_class)))
        continue;

      const medNodeId = `medication:${med.rxcui}`;
      nodes.set(medNodeId, {
        id: medNodeId,
        label: med.generic_name,
        type: "medication",
        drug_class: med.drug_class,
      });
      edges.push({
        source: medNodeId,
        target: conditionNodeId,
        kind: "treats",
        report_count: null,
        label_confirmed: null,
        fda_approved: med.fda_approved,
      });

      if (processedRxcuis.has(med.rxcui)) continue;
      processedRxcuis.add(med.rxcui);

      for (const effect of keptEffects(med.side_effects, confirmedOnly).slice(0, perMed)) {
        const effectNodeId = `side_effect:${effect.side_effect_id}`;
        nodes.set(effectNodeId, {
          id: effectNodeId,
          label: effect.name,
          type: "side_effect",
        });
        edges.push({
          source: medNodeId,
          target: effectNodeId,
          kind: "causes",
          report_count: effect.report_count,
          label_confirmed: effect.label_confirmed,
        });
      }
    }
  }

  return { nodes: [...nodes.values()], edges };
}

export async function fetchSideEffects(
  rxcui: string,
  confirmedOnly: boolean,
): Promise<SideEffectReport[]> {
  const snapshot = await loadSnapshot();
  const med = dedupedMedications(snapshot).find((m) => m.rxcui === rxcui);
  if (!med) return [];
  return keptEffects(med.side_effects, confirmedOnly).slice(0, SIDE_EFFECT_LIMIT);
}

export async function fetchMedicationsForSideEffect(
  sideEffectId: string,
): Promise<MedicationCause[]> {
  const snapshot = await loadSnapshot();
  const causes: MedicationCause[] = [];
  for (const med of dedupedMedications(snapshot)) {
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

/** A medication's pharmacology columns (class, mechanism, neurotransmitters, ATC). */
export async function fetchMedicationPharmacology(
  rxcui: string,
): Promise<MedicationPharmacology | null> {
  const snapshot = await loadSnapshot();
  const med = dedupedMedications(snapshot).find((m) => m.rxcui === rxcui);
  if (!med) return null;
  return {
    drug_class: med.drug_class,
    atc_codes: med.atc_codes,
    mechanism: med.mechanism,
    neurotransmitters: med.neurotransmitters,
  };
}

/** Distinct drug classes across all medications, sorted, for the class filter. */
export async function fetchDrugClasses(): Promise<string[]> {
  const snapshot = await loadSnapshot();
  const classes = new Set<string>();
  for (const med of dedupedMedications(snapshot)) {
    if (med.drug_class) classes.add(med.drug_class);
  }
  return [...classes].sort();
}

/** The conditions a medication treats, with FDA-approval per condition. */
export async function fetchConditionsForMedication(
  rxcui: string,
): Promise<MedicationTreats[]> {
  const snapshot = await loadSnapshot();
  const treats: MedicationTreats[] = [];
  for (const condition of snapshot.conditions) {
    const med = snapshot.graphs[condition.id]?.medications.find(
      (m) => m.rxcui === rxcui,
    );
    if (med) {
      treats.push({
        id: condition.id,
        name: condition.name,
        fda_approved: med.fda_approved,
      });
    }
  }
  return treats;
}

/** A condition's medications with their side-effect counts and approval flag. */
export async function fetchMedicationsForCondition(
  conditionId: string,
): Promise<MedicationSummary[]> {
  const snapshot = await loadSnapshot();
  const graph = snapshot.graphs[conditionId];
  if (!graph) return [];
  return [...graph.medications]
    .map((med) => ({
      rxcui: med.rxcui,
      generic_name: med.generic_name,
      side_effect_count: med.side_effects.length,
      fda_approved: med.fda_approved,
    }))
    .sort((a, b) => a.generic_name.localeCompare(b.generic_name));
}

/** Every searchable node (conditions, deduped meds, deduped side effects). */
export async function fetchSearchIndex(): Promise<SearchEntry[]> {
  const snapshot = await loadSnapshot();
  const entries: SearchEntry[] = snapshot.conditions.map((condition) => ({
    nodeId: `condition:${condition.id}`,
    label: condition.name,
    type: "condition",
    conditionIds: [condition.id],
  }));

  const medConditions = new Map<string, { label: string; conditionIds: Set<string>; aliases: Set<string> }>();
  const effectConditions = new Map<string, { label: string; conditionIds: Set<string> }>();
  for (const condition of snapshot.conditions) {
    for (const med of snapshot.graphs[condition.id]?.medications ?? []) {
      const medEntry = medConditions.get(med.rxcui) ?? {
        label: med.generic_name,
        conditionIds: new Set<string>(),
        aliases: new Set<string>(),
      };
      medEntry.conditionIds.add(condition.id);
      if (med.drug_class) medEntry.aliases.add(med.drug_class);
      if (med.mechanism) {
        for (const term of med.mechanism.split(";")) {
          const t = term.trim();
          if (t) medEntry.aliases.add(t);
        }
      }
      if (med.neurotransmitters) {
        for (const term of med.neurotransmitters.split(";")) {
          const t = term.trim();
          if (t) medEntry.aliases.add(t);
        }
      }
      medConditions.set(med.rxcui, medEntry);

      for (const effect of med.side_effects) {
        const effectEntry = effectConditions.get(effect.side_effect_id) ?? {
          label: effect.name,
          conditionIds: new Set<string>(),
        };
        effectEntry.conditionIds.add(condition.id);
        effectConditions.set(effect.side_effect_id, effectEntry);
      }
    }
  }

  for (const [rxcui, med] of medConditions) {
    entries.push({
      nodeId: `medication:${rxcui}`,
      label: med.label,
      type: "medication",
      conditionIds: [...med.conditionIds],
      aliases: [...med.aliases],
    });
  }
  for (const [effectId, effect] of effectConditions) {
    entries.push({
      nodeId: `side_effect:${effectId}`,
      label: effect.label,
      type: "side_effect",
      conditionIds: [...effect.conditionIds],
    });
  }
  return entries;
}
