import type {
  ConditionInfo,
  DrugCondition,
  DrugDetail,
  GraphEdge,
  GraphNode,
  GraphPayload,
  MedicationCause,
  MedicationSummary,
  SearchEntry,
  SideEffectReport,
} from "./types";

// All data comes from the live FastAPI backend, proxied through Vite at /api.

interface ApiResponse<T> {
  success: boolean;
  data?: T;
  error?: string;
}

async function api<T>(path: string): Promise<T> {
  const response = await fetch(`/api${path}`);
  if (!response.ok) {
    throw new Error(`API error ${response.status}: ${path}`);
  }
  const body: ApiResponse<T> = await response.json();
  if (!body.success || body.data === undefined) {
    throw new Error(body.error ?? `API returned no data: ${path}`);
  }
  return body.data;
}

/** Edge endpoints arrive as ids but are replaced by node objects by the force simulation. */
function endpointId(end: string | GraphNode): string {
  return typeof end === "string" ? end : end.id;
}

/** Union of several condition subgraphs: nodes deduped by id, edges by endpoints+kind. */
function mergePayloads(payloads: GraphPayload[]): GraphPayload {
  const nodes = new Map<string, GraphNode>();
  const edges = new Map<string, GraphEdge>();
  for (const payload of payloads) {
    for (const node of payload.nodes) {
      if (!nodes.has(node.id)) nodes.set(node.id, node);
    }
    for (const edge of payload.edges) {
      const key = `${endpointId(edge.source)}|${endpointId(edge.target)}|${edge.kind}`;
      if (!edges.has(key)) edges.set(key, edge);
    }
  }
  return { nodes: [...nodes.values()], edges: [...edges.values()] };
}

/** Restrict the graph to drugs in the given classes, dropping now-orphaned nodes. */
function filterByDrugClass(payload: GraphPayload, classes: string[]): GraphPayload {
  if (classes.length === 0) return payload;
  const allowed = new Set(classes);
  const keptDrugIds = new Set(
    payload.nodes
      .filter((n) => n.type === "drug" && n.drug_class && allowed.has(n.drug_class))
      .map((n) => n.id),
  );
  const edges = payload.edges.filter(
    (e) => keptDrugIds.has(endpointId(e.source)) || keptDrugIds.has(endpointId(e.target)),
  );
  const referenced = new Set(
    edges.flatMap((e) => [endpointId(e.source), endpointId(e.target)]),
  );
  const nodes = payload.nodes.filter((n) =>
    n.type === "drug" ? keptDrugIds.has(n.id) : referenced.has(n.id),
  );
  return { nodes, edges };
}

export async function fetchConditions(): Promise<ConditionInfo[]> {
  return api<ConditionInfo[]>("/conditions");
}

export async function fetchConditionGraph(
  conditionIds: string[],
  perMed: number,
  classes: string[] = [],
): Promise<GraphPayload> {
  if (conditionIds.length === 0) {
    return { nodes: [], edges: [] };
  }
  const payloads = await Promise.all(
    conditionIds.map((id) =>
      api<GraphPayload>(
        `/conditions/${encodeURIComponent(id)}/graph?per_med=${perMed}`,
      ),
    ),
  );
  return filterByDrugClass(mergePayloads(payloads), classes);
}

export async function fetchSideEffects(rxcui: string): Promise<SideEffectReport[]> {
  return api<SideEffectReport[]>(
    `/medications/${encodeURIComponent(rxcui)}/side-effects?limit=25`,
  );
}

export async function fetchMedicationsForSideEffect(
  sideEffectId: string,
): Promise<MedicationCause[]> {
  return api<MedicationCause[]>(
    `/side-effects/${encodeURIComponent(sideEffectId)}/medications`,
  );
}

export async function fetchDrugDetail(rxcui: string): Promise<DrugDetail | null> {
  return api<DrugDetail | null>(`/drugs/${encodeURIComponent(rxcui)}/detail`);
}

export async function fetchDrugClasses(): Promise<string[]> {
  const classes = await api<{ id: string; name: string }[]>("/drug-classes");
  return classes.map((c) => c.name);
}

export async function fetchConditionsForDrug(
  rxcui: string,
): Promise<DrugCondition[]> {
  return api<DrugCondition[]>(`/drugs/${encodeURIComponent(rxcui)}/conditions`);
}

export async function fetchMedicationsForCondition(
  conditionId: string,
): Promise<MedicationSummary[]> {
  return api<MedicationSummary[]>(
    `/conditions/${encodeURIComponent(conditionId)}/medications`,
  );
}

export async function fetchNeighborhood(
  nodeType: string,
  nodeId: string,
  perMed: number = 10,
): Promise<GraphPayload> {
  return api<GraphPayload>(
    `/nodes/${encodeURIComponent(nodeType)}/${encodeURIComponent(nodeId)}/neighborhood?per_med=${perMed}`,
  );
}

export async function fetchSearchIndex(): Promise<SearchEntry[]> {
  const raw = await api<{ type: string; id: string; label: string }[]>("/search");
  return raw.map((entry) => ({
    nodeId: `${entry.type}:${entry.id}`,
    label: entry.label,
    type: entry.type as SearchEntry["type"],
  }));
}
