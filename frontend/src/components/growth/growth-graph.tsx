"use client";

/**
 * The Growth Graph.
 *
 * A depth-ordered tree: the headline metric at the top, its arithmetic components
 * below, then the segment those concentrate in, then the independent evidence
 * that moved alongside it.
 *
 * Edge wording is deliberate and shown to the user (spec section 18):
 *   decomposes_into  - arithmetic, revenue really is orders x AOV
 *   correlates_with  - moved over the same window, nothing more
 *   evidenced_by     - a different source agrees
 * Nothing here says "caused". Only the experiment can settle that.
 */

import { AnimatePresence, motion } from "framer-motion";
import {
  ArrowDownRight,
  ArrowRight,
  ArrowUpRight,
  Info,
  Minus,
  MoveRight,
  X,
} from "lucide-react";
import * as React from "react";

import { EvidenceList } from "@/components/growth/evidence-list";
import { Button } from "@/components/ui/button";
import {
  Badge,
  Card,
  CardContent,
  Separator,
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from "@/components/ui/primitives";
import { cn } from "@/lib/utils";
import type { GraphEdge, GraphNode, GrowthGraph } from "@/types/api";

const SEVERITY_STYLES = {
  CRITICAL: {
    ring: "border-destructive/60 bg-destructive/8",
    dot: "bg-destructive",
    text: "text-destructive",
  },
  HIGH: { ring: "border-destructive/40 bg-destructive/5", dot: "bg-destructive/80", text: "text-destructive" },
  MEDIUM: { ring: "border-warning/45 bg-warning/6", dot: "bg-warning", text: "text-warning" },
  LOW: { ring: "border-border bg-card", dot: "bg-muted-foreground", text: "text-muted-foreground" },
  INFO: { ring: "border-border bg-card", dot: "bg-muted-foreground", text: "text-muted-foreground" },
} as const;

const KIND_LABEL: Record<GraphNode["node_kind"], string> = {
  metric: "Metric",
  segment: "Segment",
  signal: "Operational signal",
  evidence: "Independent evidence",
  hypothesis: "Hypothesis",
};

const RELATIONSHIP_COPY: Record<GraphEdge["relationship"], { label: string; detail: string }> = {
  decomposes_into: {
    label: "decomposes into",
    detail: "Arithmetic: the parent is exactly made up of these components.",
  },
  correlates_with: {
    label: "correlates with",
    detail: "These moved over the same window. That is a correlation, not a cause.",
  },
  evidenced_by: {
    label: "evidenced by",
    detail: "A different data source shows the same pattern independently.",
  },
};

export function GrowthGraphView({ graph }: { graph: GrowthGraph }) {
  const [selectedId, setSelectedId] = React.useState<string | null>(graph.root_id);

  const byDepth = React.useMemo(() => {
    const map = new Map<number, GraphNode[]>();
    for (const node of graph.nodes) {
      const list = map.get(node.depth) ?? [];
      list.push(node);
      map.set(node.depth, list);
    }
    return Array.from(map.entries()).sort(([a], [b]) => a - b);
  }, [graph.nodes]);

  const selected = graph.nodes.find((node) => node.id === selectedId) ?? null;

  // Lineage: the chain from root down to the selected node, so the user can see
  // exactly which path through the decomposition they are looking at.
  const lineage = React.useMemo(() => {
    if (!selected) return [];
    const parents = new Map(graph.edges.map((edge) => [edge.target, edge.source]));
    const chain: string[] = [selected.id];
    let cursor = selected.id;
    while (parents.has(cursor)) {
      cursor = parents.get(cursor)!;
      chain.unshift(cursor);
      if (chain.length > 8) break;
    }
    return chain;
  }, [selected, graph.edges]);

  const incomingEdge = selected
    ? graph.edges.find((edge) => edge.target === selected.id)
    : undefined;

  return (
    <div className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_340px]">
      <Card>
        <CardContent className="space-y-5 p-5">
          {byDepth.map(([depth, nodes], levelIndex) => (
            <div key={depth} className="space-y-2">
              {levelIndex > 0 && (
                <div className="flex justify-center">
                  <MoveRight className="h-3.5 w-3.5 rotate-90 text-muted-foreground/50" />
                </div>
              )}
              <div
                className={cn(
                  "grid gap-2",
                  nodes.length === 1
                    ? "grid-cols-1"
                    : nodes.length === 2
                      ? "sm:grid-cols-2"
                      : "sm:grid-cols-2 lg:grid-cols-4",
                )}
              >
                {nodes.map((node) => (
                  <GraphNodeCard
                    key={node.id}
                    node={node}
                    active={node.id === selectedId}
                    onLineage={lineage.includes(node.id)}
                    onSelect={() => setSelectedId(node.id)}
                  />
                ))}
              </div>
            </div>
          ))}

          <div className="flex items-start gap-2 rounded-lg border border-dashed border-border bg-muted/40 p-3">
            <Info className="mt-0.5 h-3.5 w-3.5 shrink-0 text-muted-foreground" />
            <p className="text-2xs leading-relaxed text-muted-foreground">{graph.caveat}</p>
          </div>
        </CardContent>
      </Card>

      {/* Detail panel */}
      <AnimatePresence mode="wait">
        {selected && (
          <motion.div
            key={selected.id}
            initial={{ opacity: 0, x: 12 }}
            animate={{ opacity: 1, x: 0 }}
            exit={{ opacity: 0, x: -8 }}
            transition={{ duration: 0.22 }}
          >
            <Card className="lg:sticky lg:top-24">
              <CardContent className="space-y-4 p-5">
                <div className="flex items-start justify-between gap-2">
                  <div className="min-w-0">
                    <Badge variant="outline" className="mb-1.5">
                      {KIND_LABEL[selected.node_kind]}
                    </Badge>
                    <h3 className="text-base font-semibold leading-tight">{selected.label}</h3>
                  </div>
                  <Button
                    variant="ghost"
                    size="icon-sm"
                    onClick={() => setSelectedId(null)}
                    aria-label="Close details"
                    className="lg:hidden"
                  >
                    <X className="h-4 w-4" />
                  </Button>
                </div>

                <div className="flex items-baseline gap-2">
                  <span className="text-2xl font-semibold tracking-tight tnum">
                    {selected.formatted_value}
                  </span>
                  {selected.change_pct != null && (
                    <ChangeChip value={selected.change_pct} kind={selected.node_kind} />
                  )}
                </div>

                {incomingEdge && (
                  <div className="rounded-lg border border-border bg-muted/40 p-2.5">
                    <p className="text-2xs font-semibold uppercase tracking-wide text-muted-foreground">
                      Relationship to parent
                    </p>
                    <p className="mt-0.5 text-sm font-medium">
                      {RELATIONSHIP_COPY[incomingEdge.relationship].label}
                    </p>
                    <p className="mt-0.5 text-2xs leading-relaxed text-muted-foreground">
                      {RELATIONSHIP_COPY[incomingEdge.relationship].detail}
                    </p>
                  </div>
                )}

                {selected.interpretation && (
                  <div className="space-y-1.5">
                    <p className="text-2xs font-semibold uppercase tracking-widest text-muted-foreground">
                      What this means
                    </p>
                    <p className="text-sm leading-relaxed text-muted-foreground">
                      {selected.interpretation}
                    </p>
                  </div>
                )}

                {selected.evidence.length > 0 && (
                  <>
                    <Separator />
                    <div className="space-y-2">
                      <p className="text-2xs font-semibold uppercase tracking-widest text-muted-foreground">
                        Supporting data
                      </p>
                      <EvidenceList evidence={selected.evidence} dense />
                    </div>
                  </>
                )}

                <div className="flex items-center gap-1.5 pt-1 text-2xs text-muted-foreground">
                  <span>Source:</span>
                  <Badge variant="muted">{selected.source}</Badge>
                </div>
              </CardContent>
            </Card>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}

function GraphNodeCard({
  node,
  active,
  onLineage,
  onSelect,
}: {
  node: GraphNode;
  active: boolean;
  onLineage: boolean;
  onSelect: () => void;
}) {
  const style = SEVERITY_STYLES[node.severity] ?? SEVERITY_STYLES.INFO;

  return (
    <motion.button
      type="button"
      onClick={onSelect}
      whileHover={{ y: -2 }}
      transition={{ duration: 0.18 }}
      className={cn(
        "group relative w-full rounded-xl border px-3.5 py-3 text-left transition-all focus-ring",
        style.ring,
        active && "ring-2 ring-primary ring-offset-2 ring-offset-background",
        !active && onLineage && "border-primary/45",
      )}
    >
      <div className="flex items-start justify-between gap-2">
        <span className="flex min-w-0 items-center gap-1.5">
          <span className={cn("h-1.5 w-1.5 shrink-0 rounded-full", style.dot)} />
          <span className="truncate text-xs font-medium text-muted-foreground">{node.label}</span>
        </span>
        {node.node_kind === "evidence" && (
          <Tooltip>
            <TooltipTrigger asChild>
              <span>
                <Badge variant="outline" className="shrink-0">
                  indep.
                </Badge>
              </span>
            </TooltipTrigger>
            <TooltipContent>
              From a different data source than the transaction ledger, which is what makes it
              corroboration.
            </TooltipContent>
          </Tooltip>
        )}
      </div>

      <p className="mt-1.5 text-base font-semibold leading-none tracking-tight tnum">
        {node.formatted_value}
      </p>

      {node.change_pct != null && (
        <div className="mt-1.5">
          <ChangeChip value={node.change_pct} kind={node.node_kind} compact />
        </div>
      )}
    </motion.button>
  );
}

function ChangeChip({
  value,
  kind,
  compact,
}: {
  value: number;
  kind: GraphNode["node_kind"];
  compact?: boolean;
}) {
  // For a signal or evidence node, *rising* is the bad news (longer waits, more
  // complaints). For a metric, falling is. Colour follows meaning either way.
  const badWhenUp = kind === "signal" || kind === "evidence";
  const flat = Math.abs(value) < 1.5;
  const bad = flat ? false : badWhenUp ? value > 0 : value < 0;
  const Icon = flat ? Minus : value > 0 ? ArrowUpRight : ArrowDownRight;

  return (
    <span
      className={cn(
        "inline-flex items-center gap-0.5 font-medium tnum",
        compact ? "text-xs" : "text-sm",
        flat ? "text-muted-foreground" : bad ? "text-destructive" : "text-success",
      )}
    >
      <Icon className={compact ? "h-3 w-3" : "h-3.5 w-3.5"} />
      {value >= 0 ? "+" : ""}
      {value.toFixed(1)}%
    </span>
  );
}

/** Condensed chain view used on the dashboard. */
export function GrowthGraphChain({ graph }: { graph: GrowthGraph }) {
  const parents = new Map(graph.edges.map((edge) => [edge.target, edge.source]));
  const deepest = graph.nodes.reduce(
    (best, node) => (node.depth > best.depth ? node : best),
    graph.nodes[0],
  );

  const chain: GraphNode[] = [];
  let cursor: string | undefined = deepest?.id;
  while (cursor) {
    const node = graph.nodes.find((n) => n.id === cursor);
    if (!node) break;
    chain.unshift(node);
    cursor = parents.get(cursor);
    if (chain.length > 6) break;
  }

  return (
    <div className="space-y-1.5">
      {chain.map((node, index) => (
        <div key={node.id} className="flex items-center gap-2">
          <div
            className="shrink-0"
            style={{ width: `${index * 14}px` }}
            aria-hidden
          />
          {index > 0 && <ArrowRight className="h-3 w-3 shrink-0 text-muted-foreground/60" />}
          <span className="min-w-0 flex-1 truncate text-sm">{node.label}</span>
          <span className="shrink-0 text-sm font-medium tnum">{node.formatted_value}</span>
          {node.change_pct != null && (
            <span className="w-16 shrink-0 text-right">
              <ChangeChip value={node.change_pct} kind={node.node_kind} compact />
            </span>
          )}
        </div>
      ))}
    </div>
  );
}
