export interface ConditionInfo {
  id: string;
  name: string;
}

/** The graph has exactly three kinds of node. `drug_class` is a property of a
 *  drug (it backs the class filter), never a node in its own right. */
export type NodeType = "condition" | "drug" | "side_effect";

export interface GraphNode {
  id: string;
  label: string;
  type: NodeType;
  drug_class?: string | null;
  // populated by the force simulation at runtime
  x?: number;
  y?: number;
}

export interface GraphEdge {
  source: string | GraphNode;
  target: string | GraphNode;
  kind: "may_treat" | "may_prevent" | "has_side_effect" | "belongs_to";
  report_count: number | null;
}

export interface GraphPayload {
  nodes: GraphNode[];
  edges: GraphEdge[];
}

export interface SideEffectReport {
  side_effect_id: string;
  name: string;
  report_count: number | null;
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
  count?: number | null;
  badge?: string;
  note?: string;
  label?: string;
}

/** A titled group of rows in the side panel. */
export interface PanelSection {
  heading: string;
  rows: PanelRow[];
}

/** One searchable node across the whole graph. */
export interface SearchEntry {
  nodeId: string;
  label: string;
  type: NodeType;
}

/** A condition's medication with how many side effects are recorded for it. */
export interface MedicationSummary {
  rxcui: string;
  generic_name: string;
  drug_class: string | null;
  side_effect_count: number;
}

/** A condition a drug relates to, with the relationship type. */
export interface DrugCondition {
  condition_id: string;
  name: string;
  rela: "may_treat" | "may_prevent";
}

/** A drug's detail from the backend. */
export interface DrugDetail {
  rxcui: string;
  generic_name: string;
  drug_class: string | null;
  has_label: boolean | null;
  product_type: string | null;
}
