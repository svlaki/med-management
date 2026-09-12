import {NODE_COLORS, NODE_LABELS } from "../theme";
import type { NodeType } from "../types";

const LEGEND_TYPES: NodeType[] = ["condition", "drug", "side_effect"];

export function Legend() {
  return (
    <div className="legend">
      <div className="legend__group">
        {LEGEND_TYPES.map((type) => (
          <div className="legend__item" key={type}>
            <span
              className="legend__dot"
              style={{ background: NODE_COLORS[type] }}
            />
            {NODE_LABELS[type]}
          </div>
        ))}
      </div>
    </div>
  );
}
