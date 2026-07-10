export interface ConditionInfo {
  id: string;
  name: string;
  icd10: string | null;
}

export type NodeType = "condition" | "medication" | "side_effect";

export interface GraphNode {
  id: string;
  label: string;
  type: NodeType;
  // populated by the force simulation at runtime
  x?: number;
  y?: number;
}

export interface GraphEdge {
  source: string | GraphNode;
  target: string | GraphNode;
  kind: "treats" | "causes";
  report_count: number | null;
  label_confirmed: boolean | null;
}

export interface GraphPayload {
  nodes: GraphNode[];
  edges: GraphEdge[];
}

export interface SideEffectReport {
  side_effect_id: string;
  name: string;
  source: string;
  report_count: number | null;
  label_confirmed: boolean | null;
}

export interface MedicationCause {
  rxcui: string;
  generic_name: string;
  report_count: number | null;
}

/** A normalized row rendered in the side panel, regardless of node type. */
export interface PanelRow {
  id: string;
  primary: string;
  // undefined hides the count cell entirely (e.g. condition rows)
  count?: number | null;
  // present for side-effect rows (label-confirmed state); absent otherwise
  badge?: boolean | null;
}

/** A titled group of rows in the side panel. */
export interface PanelSection {
  heading: string;
  rows: PanelRow[];
}

/** One searchable node across the whole snapshot. */
export interface SearchEntry {
  nodeId: string; // e.g. "medication:36437"
  label: string;
  type: NodeType;
  /** Conditions this entry appears under (itself, its treats, or its causes). */
  conditionIds: string[];
}

/** A condition's medication with how many side effects are recorded for it. */
export interface MedicationSummary {
  rxcui: string;
  generic_name: string;
  side_effect_count: number;
}
