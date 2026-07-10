import type { NodeType } from "./types";

export const NODE_COLORS: Record<NodeType, string> = {
  condition: "red", 
  medication: "blue",
  side_effect: "green"
};

export const NODE_LABELS: Record<NodeType, string> = {
  condition: "Condition",
  medication: "Medication",
  side_effect: "Side effect",
};

export const NODE_RADIUS: Record<NodeType, number> = {
  condition: 10,
  medication: 6,
  side_effect: 4,
};

// Node "value" drives sphere size in the 3D force graph (volume-based).
export const NODE_VAL: Record<NodeType, number> = {
  condition: 40,
  medication: 8,
  side_effect: 3,
};

export const EDGE_COLORS = {
  treats: "black", // slate
  causesConfirmed: "teal",
  causesUnconfirmed: "pink",
};
