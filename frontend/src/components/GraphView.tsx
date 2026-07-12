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
  focusNodeId: string | null;
  focusKey: number;
}

type PositionedNode = GraphNode & { x?: number; y?: number; z?: number };

function edgeColor(edge: GraphEdge): string {
  if (edge.kind === "treats") {
    return edge.fda_approved
      ? EDGE_COLORS.treatsApproved
      : EDGE_COLORS.treatsMayTreat;
  }
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
  focusNodeId,
  focusKey,
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

  // Frame the whole graph once the spread-out layout has settled — but NOT
  // when this render came with a search focus request, or the fit would yank
  // the camera away from the node the focus effect just centered on.
  const handledFocusKeyRef = useRef(0);
  useEffect(() => {
    const isFocusRender = focusKey !== handledFocusKeyRef.current;
    handledFocusKeyRef.current = focusKey;
    if (isFocusRender) return;
    const timer = setTimeout(() => fgRef.current?.zoomToFit(800, 60), 1200);
    return () => clearTimeout(timer);
  }, [data, focusKey]);

  // Fly the camera to a focused node (from search). The node may not have a
  // laid-out position yet if its condition was just added, so retry briefly.
  useEffect(() => {
    if (!focusNodeId || focusKey === 0) return;
    const fg = fgRef.current as
      | (ForceGraphMethods & {
          graphData(): { nodes: PositionedNode[] };
          cameraPosition(pos: object, lookAt: object, ms: number): void;
        })
      | undefined;
    if (!fg) return;

    let cancelled = false;
    let attempts = 0;
    const focus = () => {
      if (cancelled) return;
      const node = fg.graphData().nodes.find((n) => n.id === focusNodeId);
      if (node?.x != null && node.y != null && node.z != null) {
        const distance = 90;
        const hypot = Math.hypot(node.x, node.y, node.z) || 1;
        const ratio = 1 + distance / hypot;
        fg.cameraPosition(
          { x: node.x * ratio, y: node.y * ratio, z: node.z * ratio },
          { x: node.x, y: node.y, z: node.z },
          1200,
        );
      } else if (attempts++ < 25) {
        setTimeout(focus, 150);
      }
    };
    const timer = setTimeout(focus, 300);
    return () => {
      cancelled = true;
      clearTimeout(timer);
    };
  }, [focusKey, focusNodeId]);

  return (
    <div className="graph-view">
      <ForceGraph3D
        ref={fgRef}
        graphData={data}
        width={width}
        height={height}
        backgroundColor="white"
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
        linkWidth={(link) => {
          const edge = link as GraphEdge;
          if (edge.kind !== "treats") return 0.3;
          return edge.fda_approved ? 1.2 : 0.5; // approved edges stand out
        }}
        linkOpacity={0.5}
        onNodeClick={(node) => onSelectNode(node as GraphNode)}
      />

      <div className="graph-view__controls">
      </div>
      <p className="graph-view__hint">
        Drag to rotate || Scroll to zoom || Click a medication or side effect
      </p>
    </div>
  );
}
