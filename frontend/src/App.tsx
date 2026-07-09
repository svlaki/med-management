import { useEffect, useRef, useState } from "react";
import { Controls } from "./components/Controls";
import { GraphView } from "./components/GraphView";
import { Legend } from "./components/Legend";
import { SidePanel } from "./components/SidePanel";
import {
  fetchConditionGraph,
  fetchConditions,
  fetchMedicationsForSideEffect,
  fetchSideEffects,
} from "./api";
import type {
  ConditionInfo,
  GraphNode,
  GraphPayload,
  PanelRow,
} from "./types";

function stripPrefix(id: string, prefix: string): string {
  return id.startsWith(prefix) ? id.slice(prefix.length) : id;
}

const SUBTITLES: Record<string, string> = {
  medication: "Reported side effects",
  side_effect: "Medications reported to cause this",
};

export default function App() {
  const [conditions, setConditions] = useState<ConditionInfo[]>([]);
  const [conditionId, setConditionId] = useState<string>("");
  const [confirmedOnly, setConfirmedOnly] = useState(false);
  const [perMed, setPerMed] = useState(6);

  const [graph, setGraph] = useState<GraphPayload | null>(null);
  const [graphError, setGraphError] = useState<string | null>(null);

  const [selected, setSelected] = useState<GraphNode | null>(null);
  const [rows, setRows] = useState<PanelRow[]>([]);
  const [panelLoading, setPanelLoading] = useState(false);
  const [panelError, setPanelError] = useState<string | null>(null);

  const canvasRef = useRef<HTMLDivElement>(null);
  const [size, setSize] = useState({ width: 800, height: 600 });

  useEffect(() => {
    fetchConditions()
      .then((list) => {
        setConditions(list);
        if (list.length > 0) setConditionId(list[0].id);
      })
      .catch((err) => setGraphError(err.message));
  }, []);

  useEffect(() => {
    if (!conditionId) return;
    let active = true;
    setGraphError(null);
    fetchConditionGraph(conditionId, confirmedOnly, perMed)
      .then((g) => {
        if (active) setGraph(g);
      })
      .catch((err) => {
        if (!active) return;
        setGraph(null);
        setGraphError(err.message);
      });
    return () => {
      active = false;
    };
  }, [conditionId, confirmedOnly, perMed]);

  useEffect(() => {
    const element = canvasRef.current;
    if (!element) return;
    const observer = new ResizeObserver((entries) => {
      const rect = entries[0].contentRect;
      setSize({ width: rect.width, height: rect.height });
    });
    observer.observe(element);
    return () => observer.disconnect();
  }, []);

  function selectNode(node: GraphNode) {
    // The condition is the anchor of the graph; clicking it clears the panel.
    if (node.type === "condition") {
      setSelected(null);
      return;
    }
    setSelected(node);
    setRows([]);
    setPanelLoading(true);
    setPanelError(null);

    const request =
      node.type === "medication"
        ? fetchSideEffects(stripPrefix(node.id, "medication:"), confirmedOnly).then(
            (data): PanelRow[] =>
              data.map((r) => ({
                id: r.side_effect_id,
                primary: r.name,
                count: r.report_count,
                badge: r.label_confirmed,
              })),
          )
        : fetchMedicationsForSideEffect(stripPrefix(node.id, "side_effect:")).then(
            (data): PanelRow[] =>
              data.map((c) => ({
                id: c.rxcui,
                primary: c.generic_name,
                count: c.report_count,
              })),
          );

    request
      .then((panelRows) => {
        // ignore a stale response if the user has since clicked another node
        setSelected((current) => {
          if (current?.id === node.id) setRows(panelRows);
          return current;
        });
      })
      .catch((err) => setPanelError(err.message))
      .finally(() => setPanelLoading(false));
  }

  return (
    <div className="app">
      <header className="app__header">
        <h1>med-graph</h1>
      </header>

      <div className="app__body">
        <div className="app__sidebar">
          <Controls
            conditions={conditions}
            conditionId={conditionId}
            confirmedOnly={confirmedOnly}
            perMed={perMed}
            onConditionChange={setConditionId}
            onConfirmedChange={setConfirmedOnly}
            onPerMedChange={setPerMed}
          />
          <Legend />
          {graph && (
            <p className="app__count">
              {graph.nodes.length} nodes · {graph.edges.length} edges
            </p>
          )}
          <p className="app__hint">
            Click a medication for its side effects, or a side effect for the
            medications that cause it.
          </p>
        </div>

        <div className="app__canvas" ref={canvasRef}>
          {graphError && <div className="app__error">{graphError}</div>}
          {graph && (
            <GraphView
              graph={graph}
              width={size.width}
              height={size.height}
              onSelectNode={selectNode}
              selectedId={selected?.id ?? null}
            />
          )}
        </div>

        <SidePanel
          title={selected?.label ?? null}
          subtitle={selected ? SUBTITLES[selected.type] ?? "" : ""}
          rows={rows}
          loading={panelLoading}
          error={panelError}
          onClose={() => setSelected(null)}
        />
      </div>
    </div>
  );
}
