"use client";

/**
 * The impact tree.
 *
 * Reads left to right: the initiatives you launched, the input metrics they move,
 * the north-star metric those compose into, and the outcome KPIs measured against
 * a held-out control.
 *
 * Edges carry the same three relationship types the Growth Graph uses, and no
 * others: `decomposes_into` is arithmetic, `correlates_with` moved over the same
 * window, `evidenced_by` is a second source showing the same thing. None of them
 * claims causation — that is what the experiment is for.
 */

import * as React from "react";

import { cn } from "@/lib/utils";

export type EdgeKind = "decomposes_into" | "correlates_with" | "evidenced_by";

export interface TreeCard {
  id: string;
  /** Column index, 0 = leftmost. */
  column: number;
  title: string;
  subtitle?: string;
  value?: string;
  changePct?: number | null;
  /** 0-100, renders a progress bar instead of a value. */
  progress?: number;
  status?: { label: string; tone: "success" | "warning" | "destructive" | "info" | "muted" };
  tone?: "default" | "northstar";
}

export interface TreeEdge {
  from: string;
  to: string;
  kind: EdgeKind;
}

const EDGE_STYLE: Record<EdgeKind, { stroke: string; label: string }> = {
  decomposes_into: { stroke: "hsl(var(--primary))", label: "decomposes into" },
  correlates_with: { stroke: "hsl(var(--warning))", label: "correlates with" },
  evidenced_by: { stroke: "hsl(var(--success))", label: "evidenced by" },
};

const STATUS_TONE: Record<string, string> = {
  success: "bg-success/10 text-success",
  warning: "bg-warning/10 text-warning",
  destructive: "bg-destructive/10 text-destructive",
  info: "bg-primary/10 text-primary",
  muted: "bg-muted text-muted-foreground",
};

export function ImpactTree({
  cards,
  edges,
  columnLabels,
  className,
}: {
  cards: TreeCard[];
  edges: TreeEdge[];
  columnLabels: string[];
  className?: string;
}) {
  const wrapRef = React.useRef<HTMLDivElement>(null);
  const cardRefs = React.useRef<Record<string, HTMLDivElement | null>>({});
  const [paths, setPaths] = React.useState<
    { d: string; kind: EdgeKind; midX: number; midY: number }[]
  >([]);

  // Connectors are measured from the rendered cards, so they stay attached
  // through resizes, wrapping and font loading.
  const measure = React.useCallback(() => {
    const wrap = wrapRef.current;
    if (!wrap) return;
    const base = wrap.getBoundingClientRect();

    const next = edges.flatMap((edge) => {
      const a = cardRefs.current[edge.from]?.getBoundingClientRect();
      const b = cardRefs.current[edge.to]?.getBoundingClientRect();
      if (!a || !b) return [];

      const x1 = a.right - base.left;
      const y1 = a.top - base.top + a.height / 2;
      const x2 = b.left - base.left;
      const y2 = b.top - base.top + b.height / 2;
      const dx = Math.max(24, (x2 - x1) / 2);

      return [
        {
          d: `M ${x1} ${y1} C ${x1 + dx} ${y1}, ${x2 - dx} ${y2}, ${x2} ${y2}`,
          kind: edge.kind,
          midX: (x1 + x2) / 2,
          midY: (y1 + y2) / 2,
        },
      ];
    });
    setPaths(next);
  }, [edges]);

  React.useLayoutEffect(() => {
    measure();
    const observer = new ResizeObserver(measure);
    if (wrapRef.current) observer.observe(wrapRef.current);
    window.addEventListener("resize", measure);
    return () => {
      observer.disconnect();
      window.removeEventListener("resize", measure);
    };
  }, [measure, cards]);

  const columns = React.useMemo(() => {
    const grouped: TreeCard[][] = columnLabels.map(() => []);
    for (const card of cards) (grouped[card.column] ??= []).push(card);
    return grouped;
  }, [cards, columnLabels]);

  return (
    <div className={cn("overflow-x-auto", className)}>
      <div ref={wrapRef} className="relative min-w-[1040px] p-1">
        {/* Connectors */}
        <svg className="pointer-events-none absolute inset-0 h-full w-full">
          {paths.map((path, index) => (
            <path
              key={index}
              d={path.d}
              fill="none"
              stroke={EDGE_STYLE[path.kind].stroke}
              strokeWidth="1.75"
              strokeDasharray="4 4"
              opacity="0.85"
            />
          ))}
        </svg>

        <div
          className="relative grid gap-x-8 gap-y-4"
          style={{ gridTemplateColumns: `repeat(${columnLabels.length}, minmax(0, 1fr))` }}
        >
          {columnLabels.map((label, index) => (
            <p
              key={label}
              className="text-2xs font-semibold uppercase tracking-widest text-muted-foreground"
              style={{ gridColumn: index + 1, gridRow: 1 }}
            >
              {label}
            </p>
          ))}

          {columns.map((group, columnIndex) => (
            <div
              key={columnIndex}
              className="flex flex-col justify-center gap-3"
              style={{ gridColumn: columnIndex + 1, gridRow: 2 }}
            >
              {group.map((card) => (
                <div
                  key={card.id}
                  ref={(node) => {
                    cardRefs.current[card.id] = node;
                  }}
                  className={cn(
                    "relative rounded-xl border bg-card p-3 shadow-subtle transition-shadow",
                    card.tone === "northstar"
                      ? "border-primary/50 ring-1 ring-primary/20"
                      : "border-border",
                  )}
                >
                  <div className="flex items-start justify-between gap-2">
                    <p className="text-sm font-semibold leading-tight">{card.title}</p>
                    {card.status && (
                      <span
                        className={cn(
                          "shrink-0 rounded px-1.5 py-0.5 text-2xs font-medium",
                          STATUS_TONE[card.status.tone],
                        )}
                      >
                        {card.status.label}
                      </span>
                    )}
                  </div>

                  {card.subtitle && (
                    <p className="mt-0.5 text-2xs text-muted-foreground">{card.subtitle}</p>
                  )}

                  {card.progress != null && (
                    <div className="mt-2 space-y-1">
                      <div className="h-1.5 overflow-hidden rounded-full bg-muted">
                        <div
                          className="h-full rounded-full bg-primary"
                          style={{ width: `${Math.min(100, Math.max(0, card.progress))}%` }}
                        />
                      </div>
                      <p className="text-2xs text-muted-foreground tabular-nums">
                        {Math.round(card.progress)}% complete
                      </p>
                    </div>
                  )}

                  {card.value != null && (
                    <div className="mt-2 flex items-baseline gap-2">
                      <span className="text-lg font-semibold tracking-tight tabular-nums">
                        {card.value}
                      </span>
                      {card.changePct != null && (
                        <span
                          className={cn(
                            "text-2xs font-semibold tabular-nums",
                            card.changePct >= 0 ? "text-success" : "text-destructive",
                          )}
                        >
                          {card.changePct >= 0 ? "▲" : "▼"}
                          {Math.abs(card.changePct).toFixed(1)}%
                        </span>
                      )}
                    </div>
                  )}
                </div>
              ))}
            </div>
          ))}
        </div>
      </div>

      {/* Legend: the only three relationships this product will draw */}
      <div className="mt-4 flex flex-wrap items-center gap-x-5 gap-y-2 px-1">
        {(Object.keys(EDGE_STYLE) as EdgeKind[]).map((kind) => (
          <span key={kind} className="flex items-center gap-1.5 text-2xs text-muted-foreground">
            <svg width="22" height="6" aria-hidden="true">
              <line
                x1="0"
                y1="3"
                x2="22"
                y2="3"
                stroke={EDGE_STYLE[kind].stroke}
                strokeWidth="1.5"
                strokeDasharray="4 4"
              />
            </svg>
            <code className="font-mono">{kind}</code>
            <span className="text-muted-foreground/70">— {EDGE_STYLE[kind].label}</span>
          </span>
        ))}
      </div>
    </div>
  );
}
