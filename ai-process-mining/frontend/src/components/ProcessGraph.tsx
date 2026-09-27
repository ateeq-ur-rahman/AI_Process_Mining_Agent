import dagre from "@dagrejs/dagre";
import {
  Background, Controls, Handle, MarkerType, Position, ReactFlow, type Edge, type Node, type NodeProps,
} from "@xyflow/react";
import { memo, useMemo } from "react";
import { fmtHours, fmtInt } from "../services/format";
import type { GraphEdge, GraphNode, ProcessGraph as PG } from "../types/api";

const NODE_W = 210;
const NODE_H = 64;

// Edge colour by median transition time, fastest to slowest. Line width shows volume.
const HEAT = ["#8FA3BF", "#5C7AA8", "#E0A21B", "#D5641C", "#B3262E"];

export type Selection = { kind: "node"; node: GraphNode } | { kind: "edge"; edge: GraphEdge } | null;

type ActivityData = { node: GraphNode; maxCount: number; selfLoop?: GraphEdge; selected: boolean };

const ActivityNode = memo(({ data }: NodeProps<Node<ActivityData>>) => {
  const { node, maxCount, selfLoop, selected } = data;
  const share = Math.max(0.04, node.count / maxCount);
  return (
    <div className={`pg-node${selected ? " is-selected" : ""}${node.is_start && node.start_count > 0 ? " is-start" : ""}`}>
      <Handle type="target" position={Position.Top} />
      <div className="pg-node-name">{node.activity}</div>
      <div className="pg-node-meta">
        <span>{fmtInt(node.count)}×</span>
        <span>wait {fmtHours(node.median_duration_hours)}</span>
        {selfLoop && <span title="Repeats itself">↻ {fmtInt(selfLoop.frequency)}</span>}
      </div>
      <div className="pg-node-bar" style={{ width: `${share * 100}%` }} />
      <Handle type="source" position={Position.Bottom} />
    </div>
  );
});

const nodeTypes = { activity: ActivityNode };

function quantileThresholds(values: number[]): number[] {
  const v = [...values].sort((a, b) => a - b);
  if (!v.length) return [0, 0, 0, 0];
  return [0.4, 0.65, 0.85, 0.95].map((p) => v[Math.min(v.length - 1, Math.floor(p * v.length))]);
}

export function ProcessGraph({ graph, minCasePct, selection, onSelect }: {
  graph: PG; minCasePct: number; selection: Selection; onSelect: (s: Selection) => void;
}) {
  const { nodes, edges, hidden } = useMemo(() => {
    const kept = graph.edges.filter((e) => e.case_pct >= minCasePct);
    const selfLoops = new Map(kept.filter((e) => e.source === e.target).map((e) => [e.source, e]));
    const flowEdges = kept.filter((e) => e.source !== e.target);
    const keepIds = new Set(flowEdges.flatMap((e) => [e.source, e.target]));
    const nodesKept = graph.nodes.filter((n) => keepIds.has(n.id) || (kept.length === 0 && n.case_pct >= minCasePct));
    const maxCount = Math.max(1, ...nodesKept.map((n) => n.count));
    const maxFreq = Math.max(1, ...flowEdges.map((e) => e.frequency));
    const thresholds = quantileThresholds(flowEdges.map((e) => e.median_transition_hours ?? 0));
    const heat = (h: number | null) => HEAT[thresholds.filter((t) => (h ?? 0) > t).length];

    const g = new dagre.graphlib.Graph();
    g.setGraph({ rankdir: "TB", nodesep: 40, ranksep: 70, marginx: 20, marginy: 20 });
    g.setDefaultEdgeLabel(() => ({}));
    nodesKept.forEach((n) => g.setNode(n.id, { width: NODE_W, height: NODE_H }));
    // Layout uses only "forward" edges (by average position in cases), so rework/loop arrows
    // don't pull later steps above earlier ones. All edges are still drawn.
    const pos = new Map(nodesKept.map((n) => [n.id, n.avg_position ?? 0]));
    flowEdges
      .filter((e) => (pos.get(e.source) ?? 0) < (pos.get(e.target) ?? 0))
      .forEach((e) => g.setEdge(e.source, e.target, { weight: Math.max(1, Math.round(10 * e.frequency / maxFreq)) }));
    dagre.layout(g);

    const selNode = selection?.kind === "node" ? selection.node.id : null;
    const selEdge = selection?.kind === "edge" ? selection.edge.id : null;
    const rfNodes: Node<ActivityData>[] = nodesKept.map((n) => {
      const p = g.node(n.id);
      return {
        id: n.id, type: "activity", position: { x: p.x - NODE_W / 2, y: p.y - NODE_H / 2 },
        data: { node: n, maxCount, selfLoop: selfLoops.get(n.id), selected: selNode === n.id },
      };
    });
    const rfEdges: Edge[] = flowEdges.map((e) => {
      const color = heat(e.median_transition_hours);
      const width = 1 + 7 * Math.sqrt(e.frequency / maxFreq);
      const active = selEdge === e.id || selNode === e.source || selNode === e.target;
      return {
        id: e.id, source: e.source, target: e.target,
        style: { stroke: color, strokeWidth: active ? width + 1.5 : width, opacity: selection && !active ? 0.35 : 0.9 },
        // Marker size is multiplied by stroke width, so scale it down for thick lines.
        markerEnd: { type: MarkerType.ArrowClosed, color, width: Math.max(3, 14 / width), height: Math.max(3, 14 / width) },
        label: active ? `${fmtInt(e.frequency)} cases, ${fmtHours(e.median_transition_hours)}` : undefined,
        labelBgPadding: [4, 2] as [number, number],
        labelStyle: { fontSize: 11, fontWeight: 600 },
        data: { edge: e },
      };
    });
    return { nodes: rfNodes, edges: rfEdges, hidden: graph.edges.length - kept.length };
  }, [graph, minCasePct, selection]);

  return (
    <div className="pg-wrap">
      <ReactFlow
        nodes={nodes} edges={edges} nodeTypes={nodeTypes} fitView fitViewOptions={{ padding: 0.12 }} minZoom={0.1} maxZoom={2}
        nodesDraggable={false} nodesConnectable={false} proOptions={{ hideAttribution: true }}
        onNodeClick={(_, n) => onSelect({ kind: "node", node: (n.data as ActivityData).node })}
        onEdgeClick={(_, e) => onSelect({ kind: "edge", edge: (e.data as { edge: GraphEdge }).edge })}
        onPaneClick={() => onSelect(null)}
      >
        <Background gap={24} size={1} color="#CBD3DC" />
        <Controls showInteractive={false} />
      </ReactFlow>
      <div className="pg-legend" aria-hidden="true">
        <span>Transition time</span>
        {HEAT.map((c, i) => <i key={c} style={{ background: c }} title={["fastest", "", "", "", "slowest"][i]} />)}
        <span className="muted">Line width = volume{hidden > 0 ? `; ${hidden} rare transitions hidden` : ""}</span>
      </div>
    </div>
  );
}
