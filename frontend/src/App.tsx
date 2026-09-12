import { useEffect, useRef, useState } from "react";
import { Controls } from "./components/Controls";
import { GraphView } from "./components/GraphView";
import { Legend } from "./components/Legend";
import { SearchBar } from "./components/SearchBar";
import { SidePanel } from "./components/SidePanel";
import {
  fetchConditionGraph,
  fetchConditions,
  fetchConditionsForDrug,
  fetchDrugClasses,
  fetchDrugDetail,
  fetchMedicationsForCondition,
  fetchMedicationsForSideEffect,
  fetchNeighborhood,
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
  const [perMed, setPerMed] = useState(6);
  const [searchIndex, setSearchIndex] = useState<SearchEntry[]>([]);
  const [drugClasses, setDrugClasses] = useState<string[]>([]);
  const [classFilter, setClassFilter] = useState<string[]>([]);

  const [baseGraph, setBaseGraph] = useState<GraphPayload | null>(null);
  const [neighborhoodGraph, setNeighborhoodGraph] = useState<GraphPayload | null>(null);
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
  const panelRequestRef = useRef(0);

  useEffect(() => {
    Promise.all([fetchConditions(), fetchSearchIndex(), fetchDrugClasses()])
      .then(([conditionList, index, classes]) => {
        setConditions(conditionList);
        setSearchIndex(index);
        setDrugClasses(classes);
      })
      .catch((err) => setGraphError(err.message));
  }, []);

  useEffect(() => {
    let active = true;
    setGraphError(null);
    fetchConditionGraph(selectedIds, perMed, classFilter)
      .then((g) => {
        if (active) setBaseGraph(g);
      })
      .catch((err) => {
        if (!active) return;
        setBaseGraph(null);
        setGraphError(err.message);
      });
    return () => {
      active = false;
    };
  }, [selectedIds, perMed, classFilter]);

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
    if (node.type === "drug") {
      const rxcui = stripPrefix(node.id, "drug:");
      const [detail, drugConds, effects] = await Promise.all([
        fetchDrugDetail(rxcui),
        fetchConditionsForDrug(rxcui),
        fetchSideEffects(rxcui),
      ]);
      const detailRows: PanelSection["rows"] = [
        { id: "class", label: "Class", value: detail?.drug_class },
        { id: "product_type", label: "Product type", value: detail?.product_type },
      ]
        .filter((row) => row.value)
        .map((row) => ({ id: row.id, label: row.label, primary: row.value as string }));

      const mayTreat = drugConds.filter((c) => c.rela === "may_treat");
      const mayPrevent = drugConds.filter((c) => c.rela === "may_prevent");

      const condSections: PanelSection[] = [];
      if (mayTreat.length > 0) {
        condSections.push({
          heading: "May treat",
          rows: mayTreat.map((c) => ({ id: c.condition_id, primary: c.name })),
        });
      }
      if (mayPrevent.length > 0) {
        condSections.push({
          heading: "May prevent",
          rows: mayPrevent.map((c) => ({ id: c.condition_id, primary: c.name })),
        });
      }

      return [
        ...(detailRows.length > 0 ? [{ heading: "Details", rows: detailRows }] : []),
        ...condSections,
        {
          heading: "Reported side effects",
          rows: effects.map((e) => ({
            id: e.side_effect_id,
            primary: e.name,
            count: e.report_count,
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
          heading: "Drugs reported to cause this",
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
        heading: "Drugs that treat this",
        rows: meds.map((m) => ({
          id: m.rxcui,
          primary: m.generic_name,
          count: m.side_effect_count,
          note: m.drug_class ?? undefined,
        })),
      },
    ];
  }

  const neighborhoodRequestRef = useRef(0);

  function selectNode(node: GraphNode) {
    const requestId = ++panelRequestRef.current;
    const neighborhoodId = ++neighborhoodRequestRef.current;
    const isCurrent = () => panelRequestRef.current === requestId;
    setSelected(node);
    setSections([]);
    setPanelLoading(true);
    setPanelError(null);

    const nodeId = stripPrefix(
      node.id,
      node.type === "drug" ? "drug:" : node.type === "side_effect" ? "side_effect:" : "condition:",
    );
    fetchNeighborhood(node.type, nodeId, perMed)
      .then((payload) => {
        if (neighborhoodRequestRef.current === neighborhoodId) {
          setNeighborhoodGraph(payload);
        }
      })
      .catch(() => {
        // neighborhood fetch failed — keep showing the current graph
      });

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

  // Re-fetch the neighborhood graph when perMed changes while a node is selected.
  useEffect(() => {
    if (!selected) return;
    const neighborhoodId = ++neighborhoodRequestRef.current;
    const nodeId = stripPrefix(
      selected.id,
      selected.type === "drug" ? "drug:" : selected.type === "side_effect" ? "side_effect:" : "condition:",
    );
    let active = true;
    fetchNeighborhood(selected.type, nodeId, perMed)
      .then((payload) => {
        if (active && neighborhoodRequestRef.current === neighborhoodId) {
          setNeighborhoodGraph(payload);
        }
      })
      .catch(() => {});
    return () => {
      active = false;
    };
  }, [perMed, selected]);

  function handleSearchPick(entry: SearchEntry) {
    selectNode({ id: entry.nodeId, label: entry.label, type: entry.type });
    setFocus((f) => ({ nodeId: entry.nodeId, key: f.key + 1 }));
  }

  function handleClosePanel() {
    setSelected(null);
    setNeighborhoodGraph(null);
  }

  const graph = neighborhoodGraph ?? baseGraph;
  const hasSelection = selectedIds.length > 0 || neighborhoodGraph !== null;

  return (
    <div className="app">
      <header className="app__header">
        <div className="app__titles">
          <h1>med-graph</h1>
        </div>
        <SearchBar entries={searchIndex} onPick={handleSearchPick} />
      </header>

      <div className="app__body">
        <div className="app__sidebar">
          <Controls
            conditions={conditions}
            selectedIds={selectedIds}
            perMed={perMed}
            drugClasses={drugClasses}
            classFilter={classFilter}
            onSelectionChange={setSelectedIds}
            onPerMedChange={setPerMed}
            onClassFilterChange={setClassFilter}
          />
          <Legend />
        </div>

        <div className="app__canvas" ref={canvasRef}>
          {graphError && <div className="app__error">{graphError}</div>}
          {!hasSelection && (
            <div className="app__empty">
              Select one or more disorders to build the graph.
            </div>
          )}
          {graph && hasSelection && (
            <GraphView
              graph={graph}
              width={size.width}
              height={size.height}
              onSelectNode={selectNode}
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
          onClose={handleClosePanel}
        />
      </div>
    </div>
  );
}
