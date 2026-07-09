import { useEffect, useMemo, useRef } from "react";
import ForceGraph3D from "react-force-graph-3d";
import type { ForceGraphMethods } from "react-force-graph-3d";
import type { GraphEdge, GraphNode, GraphPayload } from "../types";
import { EDGE_COLORS, NODE_COLORS, NODE_VAL } from "../theme";

interface Props {
  graph: GraphPayload;
  width: number;
  height: number;
  onSelectNode: (node: GraphNode) => void;
  selectedId: string | null;
}

function edgeColor(edge: GraphEdge): string {
  if (edge.kind === "treats") return EDGE_COLORS.treats;
  return edge.label_confirmed
    ? EDGE_COLORS.causesConfirmed
    : EDGE_COLORS.causesUnconfirmed;
}

export function GraphView({
  graph,
  width,
  height,
  onSelectNode,
  selectedId,
}: Props) {
  const fgRef = useRef<ForceGraphMethods | undefined>(undefined);

  // react-force-graph mutates node/link objects, so clone per payload.
  const data = useMemo(
    () => ({
      nodes: graph.nodes.map((n) => ({ ...n })),
      links: graph.edges.map((e) => ({ ...e })),
    }),
    [graph],
  );

  // Spread the layout out for readability: stronger node repulsion and longer
  // links than the d3 defaults, so densely-connected medications don't clump
  // (which also makes every node easy to click without occlusion).
  //
  // Configure the forces ONCE on mount. These setters only touch the always-
  // present d3 force layout; the library re-heats the simulation itself when
  // graphData loads, so we must NOT call d3ReheatSimulation here — doing so
  // races ahead of the library's own layout setup and crashes its tick loop.
  useEffect(() => {
    const fg = fgRef.current;
    if (!fg) return;
    const d3Force = (fg as unknown as {
      d3Force(name: string):
        | {
            strength?: (v: number) => unknown;
            distance?: (fn: (link: GraphEdge) => number) => unknown;
          }
        | undefined;
    }).d3Force;
    d3Force("charge")?.strength?.(-160);
    d3Force("link")?.distance?.((link) => (link.kind === "treats" ? 55 : 30));
  }, []);

  // Frame the whole graph once the spread-out layout has settled.
  useEffect(() => {
    const timer = setTimeout(() => fgRef.current?.zoomToFit(800, 60), 1200);
    return () => clearTimeout(timer);
  }, [data]);

  return (
    <div className="graph-view">
      <ForceGraph3D
        ref={fgRef}
        graphData={data}
        width={width}
        height={height}
        backgroundColor="#0f172a"
        showNavInfo={false}
        rendererConfig={{ antialias: true }}
        nodeRelSize={5}
        nodeVal={(node) => NODE_VAL[(node as GraphNode).type]}
        nodeColor={(node) =>
          (node as GraphNode).id === selectedId
            ? "#ffffff"
            : NODE_COLORS[(node as GraphNode).type]
        }
        nodeLabel={(node) => (node as GraphNode).label}
        nodeOpacity={0.95}
        linkColor={(link) => edgeColor(link as GraphEdge)}
        linkWidth={(link) => ((link as GraphEdge).kind === "treats" ? 0.6 : 0.3)}
        linkOpacity={0.5}
        onNodeClick={(node) => onSelectNode(node as GraphNode)}
      />

      <div className="graph-view__controls">
        <button
          type="button"
          onClick={() => fgRef.current?.zoomToFit(600, 50)}
        >
          Reset view
        </button>
      </div>
      <p className="graph-view__hint">
        Drag to rotate · scroll to zoom · click a medication or side effect
      </p>
    </div>
  );
}
