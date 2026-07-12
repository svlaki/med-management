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
            style={{ background: EDGE_COLORS.treatsApproved, height: "3px" }}
          />
          Treats · FDA-approved
        </div>
        <div className="legend__item">
          <span
            className="legend__line"
            style={{ background: EDGE_COLORS.treatsMayTreat }}
          />
          Treats · may treat (off-label)
        </div>
        <div className="legend__item">
          <span
            className="legend__line"
            style={{ background: EDGE_COLORS.causesConfirmed }}
          />
          Causes · label-confirmed
        </div>
        <div className="legend__item">
          <span
            className="legend__line"
            style={{ background: EDGE_COLORS.causesUnconfirmed }}
          />
          Causes · FAERS-only
        </div>
      </div>
    </div>
  );
}
