import { useEffect, useRef, useState } from "react";
import { Controls } from "./components/Controls";
import { GraphView } from "./components/GraphView";
import { Legend } from "./components/Legend";
import { SearchBar } from "./components/SearchBar";
import { SidePanel } from "./components/SidePanel";
import {
  fetchConditionGraph,
  fetchConditions,
  fetchConditionsForMedication,
  fetchMedicationsForCondition,
  fetchMedicationsForSideEffect,
  fetchSearchIndex,
  fetchSideEffects,
} from "./api";
import { NODE_LABELS } from "./theme";
import type {
  ConditionInfo,
  GraphNode,
  GraphPayload,
  PanelSection,
  SearchEntry,
} from "./types";

function stripPrefix(id: string, prefix: string): string {
  return id.startsWith(prefix) ? id.slice(prefix.length) : id;
}

export default function App() {
  const [conditions, setConditions] = useState<ConditionInfo[]>([]);
  const [selectedIds, setSelectedIds] = useState<string[]>([]);
  const [confirmedOnly, setConfirmedOnly] = useState(false);
  const [perMed, setPerMed] = useState(6);
  const [searchIndex, setSearchIndex] = useState<SearchEntry[]>([]);

  const [graph, setGraph] = useState<GraphPayload | null>(null);
  const [graphError, setGraphError] = useState<string | null>(null);

  const [selected, setSelected] = useState<GraphNode | null>(null);
  const [sections, setSections] = useState<PanelSection[]>([]);
  const [panelLoading, setPanelLoading] = useState(false);
  const [panelError, setPanelError] = useState<string | null>(null);
  const [focus, setFocus] = useState<{ nodeId: string | null; key: number }>({
    nodeId: null,
    key: 0,
  });

  const canvasRef = useRef<HTMLDivElement>(null);
  const [size, setSize] = useState({ width: 800, height: 600 });
  // Monotonic id so a slow panel response for a previously-selected node can
  // never overwrite the panel for the node the user is now viewing.
  const panelRequestRef = useRef(0);

  useEffect(() => {
    Promise.all([fetchConditions(), fetchSearchIndex()])
      .then(([conditionList, index]) => {
        setConditions(conditionList);
        setSearchIndex(index);
      })
      .catch((err) => setGraphError(err.message));
  }, []);

  useEffect(() => {
    let active = true;
    setGraphError(null);
    fetchConditionGraph(selectedIds, confirmedOnly, perMed)
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
  }, [selectedIds, confirmedOnly, perMed]);

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

  async function buildSections(node: GraphNode): Promise<PanelSection[]> {
    if (node.type === "medication") {
      const rxcui = stripPrefix(node.id, "medication:");
      const [treats, effects] = await Promise.all([
        fetchConditionsForMedication(rxcui),
        fetchSideEffects(rxcui, confirmedOnly),
      ]);
      return [
        {
          heading: "Treats",
          rows: treats.map((c) => ({ id: c.id, primary: c.name })),
        },
        {
          heading: "Reported side effects",
          rows: effects.map((e) => ({
            id: e.side_effect_id,
            primary: e.name,
            count: e.report_count,
            badge: e.label_confirmed,
          })),
        },
      ];
    }
    if (node.type === "side_effect") {
      const causes = await fetchMedicationsForSideEffect(
        stripPrefix(node.id, "side_effect:"),
      );
      return [
        {
          heading: "Medications reported to cause this",
          rows: causes.map((c) => ({
            id: c.rxcui,
            primary: c.generic_name,
            count: c.report_count,
          })),
        },
      ];
    }
    // condition
    const meds = await fetchMedicationsForCondition(stripPrefix(node.id, "condition:"));
    return [
      {
        heading: "Medications",
        rows: meds.map((m) => ({
          id: m.rxcui,
          primary: m.generic_name,
          count: m.side_effect_count,
        })),
      },
    ];
  }

  function selectNode(node: GraphNode) {
    const requestId = ++panelRequestRef.current;
    const isCurrent = () => panelRequestRef.current === requestId;
    setSelected(node);
    setSections([]);
    setPanelLoading(true);
    setPanelError(null);
    buildSections(node)
      .then((built) => {
        if (isCurrent()) setSections(built);
      })
      .catch((err) => {
        if (isCurrent()) setPanelError(err.message);
      })
      .finally(() => {
        if (isCurrent()) setPanelLoading(false);
      });
  }

  // Keep an open medication panel in sync when the label-confirmed filter
  // changes (its side-effect list is built with that filter).
  useEffect(() => {
    if (selected) selectNode(selected);
    // selectNode reads the latest confirmedOnly; only re-run on that toggle.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [confirmedOnly]);

  function handleSearchPick(entry: SearchEntry) {
    // Ensure the node is on screen by selecting the conditions it belongs to.
    setSelectedIds((prev) => {
      const merged = new Set(prev);
      entry.conditionIds.forEach((id) => merged.add(id));
      return [...merged];
    });
    selectNode({ id: entry.nodeId, label: entry.label, type: entry.type });
    setFocus((f) => ({ nodeId: entry.nodeId, key: f.key + 1 }));
  }

  const hasSelection = selectedIds.length > 0;

  return (
    <div className="app">
      <header className="app__header">
        <div className="app__titles">
          <h1>med-graph</h1>
          <p className="app__disclaimer">
            Research prototype · data from openFDA &amp; RxClass · not medical advice
            or for clinical use
          </p>
        </div>
        <SearchBar entries={searchIndex} onPick={handleSearchPick} />
      </header>

      <div className="app__body">
        <div className="app__sidebar">
          <Controls
            conditions={conditions}
            selectedIds={selectedIds}
            confirmedOnly={confirmedOnly}
            perMed={perMed}
            onSelectionChange={setSelectedIds}
            onConfirmedChange={setConfirmedOnly}
            onPerMedChange={setPerMed}
          />
          <Legend />
          {graph && hasSelection && (
            <p className="app__count">
              {graph.nodes.length} nodes · {graph.edges.length} edges
            </p>
          )}
          <p className="app__hint">
            Click a condition, medication, or side effect for its details.
          </p>
        </div>

        <div className="app__canvas" ref={canvasRef}>
          {graphError && <div className="app__error">{graphError}</div>}
          {!hasSelection && (
            <div className="app__empty">
              Select one or more conditions to build the graph.
            </div>
          )}
          {graph && hasSelection && (
            <GraphView
              graph={graph}
              width={size.width}
              height={size.height}
              onSelectNode={selectNode}
              selectedId={selected?.id ?? null}
              focusNodeId={focus.nodeId}
              focusKey={focus.key}
            />
          )}
        </div>

        <SidePanel
          title={selected?.label ?? null}
          subtitle={selected ? NODE_LABELS[selected.type] : ""}
          sections={sections}
          loading={panelLoading}
          error={panelError}
          onClose={() => setSelected(null)}
        />
      </div>
    </div>
  );
}
