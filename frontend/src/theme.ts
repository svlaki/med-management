import type { NodeType } from "./types";

export const NODE_COLORS: Record<NodeType, string> = {
  condition: "red",
  medication: "blue",
  side_effect: "green"
};

/** Per-drug-class colors for medication nodes. Null/unknown falls back to NODE_COLORS.medication. */
export const DRUG_CLASS_COLORS: Record<string, string> = {
  "Antidepressant": "#4a90d9",
  "Antipsychotic": "#e06c75",
  "Anxiolytic": "#61afef",
  "Mood stabilizer": "#e5c07b",
  "Stimulant": "#c678dd",
  "Sedative-Hypnotic": "#56b6c2",
  "Other": "#98c379",
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
  treatsApproved: "black", // FDA-approved for this condition
  treatsMayTreat: "#c0c4cc", // RxClass "may treat" only (often off-label)
  causesConfirmed: "teal",
  causesUnconfirmed: "pink",
};
