import { act, cleanup, render } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { GraphPayload } from "../types";

// The ref surface here deliberately mirrors react-force-graph-3d's real
// ForceGraphMethods interface, which has NO graphData() method — graphData is a
// prop. Reintroducing a fg.graphData() call therefore throws and fails these
// tests instead of only breaking at runtime in the browser.
const mocks = vi.hoisted(() => ({
  cameraPosition: vi.fn(),
  zoomToFit: vi.fn(),
  graphData: { current: null as { nodes: Record<string, unknown>[] } | null },
}));

vi.mock("react-force-graph-3d", async () => {
  const React = await import("react");
  const ForceGraph3DMock = React.forwardRef(function ForceGraph3DMock(
    props: { graphData: { nodes: Record<string, unknown>[] } },
    ref: React.Ref<unknown>,
  ) {
    mocks.graphData.current = props.graphData;
    React.useImperativeHandle(ref, () => ({
      cameraPosition: mocks.cameraPosition,
      zoomToFit: mocks.zoomToFit,
      d3Force: () => undefined,
      d3ReheatSimulation: () => undefined,
      refresh: () => undefined,
    }));
    return React.createElement("div", { "data-testid": "force-graph" });
  });
  return { default: ForceGraph3DMock };
});

const { GraphView } = await import("./GraphView");

const GRAPH: GraphPayload = {
  nodes: [
    { id: "condition:mdd", label: "MDD", type: "condition" },
    { id: "drug:36437", label: "sertraline", type: "drug", drug_class: "SSRI" },
  ],
  edges: [
    {
      source: "drug:36437",
      target: "condition:mdd",
      kind: "may_treat",
      report_count: null,
    },
  ],
};

/** Stand in for the force simulation, which writes x/y/z onto the node objects. */
function layout(id: string, x: number, y: number, z: number) {
  const node = mocks.graphData.current?.nodes.find((n) => n.id === id);
  if (node) Object.assign(node, { x, y, z });
}

function renderGraph(focusNodeId: string | null, focusKey: number) {
  return render(
    <GraphView
      graph={GRAPH}
      width={800}
      height={600}
      onSelectNode={vi.fn()}

      focusNodeId={focusNodeId}
      focusKey={focusKey}
    />,
  );
}

beforeEach(() => {
  vi.useFakeTimers();
  mocks.cameraPosition.mockClear();
  mocks.zoomToFit.mockClear();
  mocks.graphData.current = null;
});

afterEach(() => {
  cleanup();
  vi.useRealTimers();
});

describe("GraphView search focus", () => {
  it("moves the camera to the focused node's laid-out position", () => {
    const { rerender } = renderGraph(null, 0);
    // 3-4-12 gives a clean hypotenuse of 13
    layout("drug:36437", 3, 4, 12);

    rerender(
      <GraphView
        graph={GRAPH}
        width={800}
        height={600}
        onSelectNode={vi.fn()}
  
        focusNodeId="drug:36437"
        focusKey={1}
      />,
    );
    act(() => void vi.advanceTimersByTime(300));

    const ratio = 1 + 90 / 13;
    expect(mocks.cameraPosition).toHaveBeenCalledTimes(1);
    expect(mocks.cameraPosition).toHaveBeenCalledWith(
      { x: 3 * ratio, y: 4 * ratio, z: 12 * ratio },
      { x: 3, y: 4, z: 12 },
      1200,
    );
  });

  it("retries until the simulation has positioned the node", () => {
    const { rerender } = renderGraph(null, 0);
    rerender(
      <GraphView
        graph={GRAPH}
        width={800}
        height={600}
        onSelectNode={vi.fn()}
  
        focusNodeId="drug:36437"
        focusKey={1}
      />,
    );

    // No coordinates yet: the first attempt must not move the camera.
    act(() => void vi.advanceTimersByTime(300));
    expect(mocks.cameraPosition).not.toHaveBeenCalled();

    layout("drug:36437", 0, 0, 10);
    act(() => void vi.advanceTimersByTime(150));
    expect(mocks.cameraPosition).toHaveBeenCalledTimes(1);
  });

  it("gives up instead of looping forever on an unknown node", () => {
    const { rerender } = renderGraph(null, 0);
    rerender(
      <GraphView
        graph={GRAPH}
        width={800}
        height={600}
        onSelectNode={vi.fn()}
  
        focusNodeId="drug:does-not-exist"
        focusKey={1}
      />,
    );
    act(() => void vi.advanceTimersByTime(300 + 150 * 40));
    expect(mocks.cameraPosition).not.toHaveBeenCalled();
  });

  it("does not focus before the user has picked a search result", () => {
    renderGraph("drug:36437", 0);
    layout("drug:36437", 3, 4, 12);
    act(() => void vi.advanceTimersByTime(1000));
    expect(mocks.cameraPosition).not.toHaveBeenCalled();
  });

  it("zooms to fit on a graph change that is not a search pick", () => {
    renderGraph(null, 0);
    act(() => void vi.advanceTimersByTime(1200));
    expect(mocks.zoomToFit).toHaveBeenCalledWith(800, 60);
  });

  it("does not fight zoomToFit when the graph changes after a search pick", () => {
    const { rerender } = renderGraph(null, 0);
    layout("drug:36437", 3, 4, 12);
    rerender(
      <GraphView
        graph={GRAPH}
        width={800}
        height={600}
        onSelectNode={vi.fn()}
  
        focusNodeId="drug:36437"
        focusKey={1}
      />,
    );
    act(() => void vi.advanceTimersByTime(300));
    expect(mocks.cameraPosition).toHaveBeenCalledTimes(1);

    // A new graph arrives with the same focusKey: only zoomToFit should run.
    rerender(
      <GraphView
        graph={{ ...GRAPH, nodes: [...GRAPH.nodes] }}
        width={800}
        height={600}
        onSelectNode={vi.fn()}
  
        focusNodeId="drug:36437"
        focusKey={1}
      />,
    );
    act(() => void vi.advanceTimersByTime(1200));
    expect(mocks.cameraPosition).toHaveBeenCalledTimes(1);
    expect(mocks.zoomToFit).toHaveBeenCalled();
  });
});
