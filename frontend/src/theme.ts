import type { NodeType } from "./types";

export const NODE_COLORS: Record<NodeType, string> = {
  condition: "red",
  drug: "blue",
  side_effect: "green",
};

export const NODE_LABELS: Record<NodeType, string> = {
  condition: "Disorder",
  drug: "Drug",
  side_effect: "Side effect",
};

export const NODE_RADIUS: Record<NodeType, number> = {
  condition: 10,
  drug: 6,
  side_effect: 4,
};

// Node "value" drives sphere size in the 3D force graph (volume-based).
export const NODE_VAL: Record<NodeType, number> = {
  condition: 40,
  drug: 8,
  side_effect: 3,
};

export const EDGE_COLORS: Record<string, string> = {
  may_treat: "#333333",
  may_prevent: "#4a90d9",
  has_side_effect: "#333333",
  belongs_to: "#c0c4cc",
};
