import { EDGE_COLORS, NODE_COLORS, NODE_LABELS } from "../theme";
import type { NodeType } from "../types";

const NODE_TYPES: NodeType[] = ["condition", "medication", "side_effect"];

export function Legend() {
  return (
    <div className="legend">
      <div className="legend__group">
        {NODE_TYPES.map((type) => (
          <div className="legend__item" key={type}>
            <span
              className="legend__dot"
              style={{ background: NODE_COLORS[type] }}
            />
            {NODE_LABELS[type]}
          </div>
        ))}
      </div>
      <div className="legend__group">
        <div className="legend__item">
          <span
            className="legend__line"
            style={{ background: EDGE_COLORS.causesConfirmed }}
          />
          Label-confirmed
        </div>
        <div className="legend__item">
          <span
            className="legend__line"
            style={{ background: EDGE_COLORS.causesUnconfirmed }}
          />
          FAERS-only
        </div>
      </div>
    </div>
  );
}
