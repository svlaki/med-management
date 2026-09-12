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
  focusNodeId: string | null;
  focusKey: number;
}

type PositionedNode = GraphNode & { x?: number; y?: number; z?: number };

function edgeColor(edge: GraphEdge): string {
  return EDGE_COLORS[edge.kind] ?? "#999";
}

export function GraphView({
  graph,
  width,
  height,
  onSelectNode,
  focusNodeId,
  focusKey,
}: Props) {
  const fgRef = useRef<ForceGraphMethods | undefined>(undefined);

  const data = useMemo(
    () => ({
      nodes: graph.nodes.map((n) => ({ ...n })),
      links: graph.edges.map((e) => ({ ...e })),
    }),
    [graph],
  );

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
    d3Force("link")?.distance?.((link) =>
      link.kind === "has_side_effect" ? 30 : 55,
    );
  }, []);

  const handledFocusKeyRef = useRef(0);
  useEffect(() => {
    const isFocusRender = focusKey !== handledFocusKeyRef.current;
    handledFocusKeyRef.current = focusKey;
    if (isFocusRender) return;
    const timer = setTimeout(() => fgRef.current?.zoomToFit(800, 60), 1200);
    return () => clearTimeout(timer);
  }, [data, focusKey]);

  // The focus effect reads node positions ~300ms after a search pick. It must
  // see the current nodes, but must not re-run when `data` changes, or it would
  // move the camera while the zoomToFit effect above is doing the same thing.
  const dataRef = useRef(data);
  useEffect(() => {
    dataRef.current = data;
  }, [data]);

  useEffect(() => {
    if (!focusNodeId || focusKey === 0) return;
    const fg = fgRef.current;
    if (!fg) return;

    let cancelled = false;
    let attempts = 0;
    const focus = () => {
      if (cancelled) return;
      // The force simulation assigns x/y/z onto these node objects in place, so
      // the laid-out coordinates are read straight off the graph data we pass in.
      // (react-force-graph-3d's ref exposes no graphData() method.)
      const node = dataRef.current.nodes.find(
        (n) => n.id === focusNodeId,
      ) as PositionedNode | undefined;
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
        nodeColor={(node) => {
          const gn = node as GraphNode;
          return NODE_COLORS[gn.type] ?? "gray";
        }}
        nodeLabel={(node) => (node as GraphNode).label}
        nodeOpacity={0.95}
        linkColor={(link) => edgeColor(link as GraphEdge)}
        linkWidth={(link) => {
          const edge = link as GraphEdge;
          if (edge.kind === "may_treat") return 1.2;
          return 0.3;
        }}
        linkOpacity={0.5}
        onNodeClick={(node) => onSelectNode(node as GraphNode)}
      />

      <div className="graph-view__controls"></div>
    </div>
  );
}
