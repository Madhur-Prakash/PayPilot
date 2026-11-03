"use client";

/**
 * The Opportunity Explorer canvas.
 *
 * Nodes and hubs are draggable. Positions are held as percentages of the canvas
 * so the layout survives a resize, and every edge is drawn from live positions
 * so the spokes follow whatever the user rearranges.
 *
 * The surface has its own light/dark switch, independent of the app theme: the
 * glow that carries the domain colour reads best on a dark ground, but a light
 * canvas prints and projects better. The choice is remembered per browser.
 */

import {
  Check,
  Moon,
  Move,
  Pencil,
  Plus,
  RotateCcw,
  Sun,
  type LucideIcon,
} from "lucide-react";
import * as React from "react";

import { cn, formatCompactCurrency } from "@/lib/utils";

export interface ConstellationNode {
  id: string;
  title: string;
  value: number;
  icon: LucideIcon;
  hubId: string;
  /** Default position, as a percentage of the canvas. */
  x: number;
  y: number;
  /** Domain accent, as a hex colour. */
  color: string;
  /** Added by a person rather than detected. Marked so it stays findable. */
  isManual?: boolean;
}

export interface ConstellationHub {
  id: string;
  label: string;
  sub: string;
  icon: LucideIcon;
  x: number;
  y: number;
}

type Point = { x: number; y: number };
type Dragging = { id: string; kind: "node" | "hub"; moved: boolean } | null;
type Surface = "dark" | "light";

const CLAMP = { minX: 6, maxX: 94, minY: 8, maxY: 92 };
const STORAGE_KEY = "pga:constellation-surface";

/** Every colour the canvas needs, per surface. */
const SKIN: Record<
  Surface,
  {
    shell: string;
    pools: string;
    gridLine: string;
    gridOpacity: string;
    vignette: string;
    edgeIdle: string;
    spine: string;
    halo: string;
    hubShell: string;
    hubGlow: string;
    hubIcon: string;
    hubLabel: string;
    hubSub: string;
    nodeFill: string;
    badgeRing: string;
    pillIdle: string;
    pillActive: string;
    chip: string;
    glowAlpha: { idle: string; active: string };
  }
> = {
  dark: {
    shell: "bg-[#050B18]",
    pools:
      "radial-gradient(60% 55% at 22% 38%, rgba(56,189,248,.16), transparent 70%)," +
      "radial-gradient(55% 50% at 78% 62%, rgba(129,140,248,.14), transparent 70%)",
    gridLine: "rgba(148,163,184,.45)",
    gridOpacity: "opacity-[0.13]",
    vignette: "inset 0 0 120px 40px rgba(2,6,23,.85)",
    edgeIdle: "rgba(203,213,225,.55)",
    spine: "rgba(203,213,225,.45)",
    halo: "rgba(203,213,225,.34)",
    hubShell: "border-white/20 bg-white/10",
    hubGlow: "0 0 24px rgba(148,163,184,.25)",
    hubIcon: "text-slate-200",
    hubLabel: "text-slate-200",
    hubSub: "text-slate-400",
    nodeFill: "linear-gradient(160deg, rgba(255,255,255,.14), rgba(255,255,255,.04))",
    badgeRing: "border-[#050B18]",
    pillIdle: "bg-black/55 text-slate-100",
    pillActive: "bg-white text-slate-900",
    chip: "border-white/10 bg-black/40 text-slate-300",
    glowAlpha: { idle: "44", active: "88" },
  },
  light: {
    shell: "bg-[#F6F9FE]",
    pools:
      "radial-gradient(60% 55% at 22% 38%, rgba(56,189,248,.14), transparent 70%)," +
      "radial-gradient(55% 50% at 78% 62%, rgba(129,140,248,.12), transparent 70%)",
    gridLine: "rgba(100,116,139,.38)",
    gridOpacity: "opacity-[0.09]",
    vignette: "inset 0 0 100px 30px rgba(148,163,184,.14)",
    edgeIdle: "rgba(71,85,105,.62)",
    spine: "rgba(71,85,105,.5)",
    halo: "rgba(71,85,105,.4)",
    hubShell: "border-slate-200 bg-white",
    hubGlow: "0 2px 10px rgba(15,23,42,.08)",
    hubIcon: "text-slate-600",
    hubLabel: "text-slate-700",
    hubSub: "text-slate-500",
    nodeFill: "linear-gradient(160deg, #ffffff, #f8fafc)",
    badgeRing: "border-white",
    pillIdle: "bg-white text-slate-700 border border-slate-200",
    pillActive: "bg-slate-900 text-white",
    chip: "border-slate-200 bg-white/85 text-slate-600",
    glowAlpha: { idle: "33", active: "66" },
  },
};

export function ConstellationCanvas({
  nodes,
  onAddNode,
  hubs,
  selectedId,
  onSelect,
  hoveredId,
  onHover,
  className,
}: {
  nodes: ConstellationNode[];
  /** Optional: shows an "Add node" control. The canvas itself stays
   *  domain-agnostic - the caller decides what adding one means. */
  onAddNode?: () => void;
  hubs: ConstellationHub[];
  selectedId?: string;
  onSelect: (id: string) => void;
  /** Hover driven from outside the canvas, e.g. the opportunity list. */
  hoveredId?: string | null;
  onHover?: (id: string | null) => void;
  className?: string;
}) {
  const surfaceRef = React.useRef<HTMLDivElement>(null);
  const [moved, setMoved] = React.useState<Record<string, Point>>({});
  const [dragging, setDragging] = React.useState<Dragging>(null);
  const [localHover, setLocalHover] = React.useState<string | null>(null);
  const [surface, setSurface] = React.useState<Surface>("dark");

  // Read the remembered choice after mount so server and client first paint match.
  React.useEffect(() => {
    try {
      const stored = window.localStorage.getItem(STORAGE_KEY);
      if (stored === "light" || stored === "dark") setSurface(stored);
    } catch {
      /* private mode or blocked storage - the default stands */
    }
  }, []);

  function toggleSurface() {
    setSurface((current) => {
      const next = current === "dark" ? "light" : "dark";
      try {
        window.localStorage.setItem(STORAGE_KEY, next);
      } catch {
        /* not worth failing the interaction over */
      }
      return next;
    });
  }

  const skin = SKIN[surface];

  // Either surface can drive the highlight; the canvas wins while the pointer is on it.
  const hovered = localHover ?? hoveredId ?? null;

  const setHovered = React.useCallback(
    (next: string | null | ((current: string | null) => string | null)) => {
      setLocalHover((current) => {
        const value = typeof next === "function" ? next(current) : next;
        onHover?.(value);
        return value;
      });
    },
    [onHover],
  );

  const positionOf = React.useCallback(
    (item: { id: string; x: number; y: number }) => moved[item.id] ?? { x: item.x, y: item.y },
    [moved],
  );

  const hubById = React.useMemo(() => {
    const map = new Map<string, ConstellationHub>();
    for (const hub of hubs) map.set(hub.id, hub);
    return map;
  }, [hubs]);

  function startDrag(event: React.PointerEvent, id: string, kind: "node" | "hub") {
    event.preventDefault();
    event.stopPropagation();
    (event.currentTarget as HTMLElement).setPointerCapture(event.pointerId);
    setDragging({ id, kind, moved: false });
  }

  function onDrag(event: React.PointerEvent) {
    if (!dragging || !surfaceRef.current) return;
    const rect = surfaceRef.current.getBoundingClientRect();
    const x = ((event.clientX - rect.left) / rect.width) * 100;
    const y = ((event.clientY - rect.top) / rect.height) * 100;
    setMoved((current) => ({
      ...current,
      [dragging.id]: {
        x: Math.max(CLAMP.minX, Math.min(CLAMP.maxX, x)),
        y: Math.max(CLAMP.minY, Math.min(CLAMP.maxY, y)),
      },
    }));
    if (!dragging.moved) setDragging({ ...dragging, moved: true });
  }

  function endDrag(event: React.PointerEvent, id: string) {
    if (!dragging) return;
    (event.currentTarget as HTMLElement).releasePointerCapture?.(event.pointerId);
    // A press that never moved is a click, not a drag.
    if (!dragging.moved && dragging.kind === "node") onSelect(id);
    setDragging(null);
  }

  const isRearranged = Object.keys(moved).length > 0;

  return (
    <div
      className={cn(
        "relative min-h-[460px] select-none overflow-hidden transition-colors duration-300",
        skin.shell,
        dragging && "cursor-grabbing",
        className,
      )}
    >
      {/* Depth: two coloured pools of light, a fine grid, and a vignette. */}
      <div className="pointer-events-none absolute inset-0" style={{ background: skin.pools }} />
      <div
        className={cn("pointer-events-none absolute inset-0", skin.gridOpacity)}
        style={{
          backgroundImage:
            `linear-gradient(${skin.gridLine} 1px, transparent 1px),` +
            `linear-gradient(90deg, ${skin.gridLine} 1px, transparent 1px)`,
          backgroundSize: "44px 44px",
        }}
      />
      <div
        className="pointer-events-none absolute inset-0"
        style={{ boxShadow: skin.vignette }}
      />

      {/* Drag surface */}
      <div
        ref={surfaceRef}
        className="absolute inset-0"
        onPointerMove={onDrag}
        onPointerUp={() => setDragging(null)}
        onPointerLeave={() => setDragging(null)}
      >
        {/* Edges, drawn from live positions */}
        <svg className="pointer-events-none absolute inset-0 h-full w-full">
          <defs>
            <filter id="edge-glow" x="-50%" y="-50%" width="200%" height="200%">
              <feGaussianBlur stdDeviation="2.5" result="blur" />
              <feMerge>
                <feMergeNode in="blur" />
                <feMergeNode in="SourceGraphic" />
              </feMerge>
            </filter>
          </defs>

          {/* Hub-to-hub spine */}
          {hubs.length > 1 &&
            hubs.map((hub, index) => {
              const next = hubs[(index + 1) % hubs.length];
              const a = positionOf(hub);
              const b = positionOf(next);
              return (
                <line
                  key={`spine-${hub.id}`}
                  x1={`${a.x}%`}
                  y1={`${a.y}%`}
                  x2={`${b.x}%`}
                  y2={`${b.y}%`}
                  stroke={skin.spine}
                  strokeWidth="1.3"
                  strokeDasharray="5 6"
                />
              );
            })}

          {/* Hub halo rings */}
          {hubs.map((hub) => {
            const p = positionOf(hub);
            return (
              <circle
                key={`halo-${hub.id}`}
                cx={`${p.x}%`}
                cy={`${p.y}%`}
                r="74"
                fill="none"
                stroke={skin.halo}
                strokeWidth="1.3"
                strokeDasharray="3 5"
              />
            );
          })}

          {/* Spokes */}
          {nodes.map((node) => {
            const hub = hubById.get(node.hubId);
            if (!hub) return null;
            const a = positionOf(hub);
            const b = positionOf(node);
            const active = selectedId === node.id || hovered === node.id;
            return (
              <line
                key={`spoke-${node.id}`}
                x1={`${a.x}%`}
                y1={`${a.y}%`}
                x2={`${b.x}%`}
                y2={`${b.y}%`}
                stroke={active ? node.color : skin.edgeIdle}
                strokeWidth={active ? 2.2 : 1.5}
                filter={active ? "url(#edge-glow)" : undefined}
                style={{ transition: "stroke .18s ease, stroke-width .18s ease" }}
              />
            );
          })}
        </svg>

        {/* Hubs */}
        {hubs.map((hub) => {
          const p = positionOf(hub);
          const HubIcon = hub.icon;
          const isDragging = dragging?.id === hub.id;
          return (
            <div
              key={hub.id}
              className="absolute z-10 -translate-x-1/2 -translate-y-1/2 touch-none"
              style={{ left: `${p.x}%`, top: `${p.y}%` }}
            >
              <button
                type="button"
                aria-label={`Move the ${hub.label}`}
                onPointerDown={(event) => startDrag(event, hub.id, "hub")}
                onPointerUp={(event) => endDrag(event, hub.id)}
                className={cn(
                  "flex h-11 w-11 items-center justify-center rounded-full border backdrop-blur-sm transition-transform",
                  skin.hubShell,
                  isDragging ? "scale-110 cursor-grabbing" : "cursor-grab hover:scale-105",
                )}
                style={{ boxShadow: skin.hubGlow }}
              >
                <HubIcon className={cn("h-5 w-5", skin.hubIcon)} />
              </button>
              <div className="pointer-events-none mt-1.5 whitespace-nowrap text-center">
                <p className={cn("text-[11px] font-semibold", skin.hubLabel)}>{hub.label}</p>
                <p className={cn("text-[10px]", skin.hubSub)}>{hub.sub}</p>
              </div>
            </div>
          );
        })}

        {/* Nodes */}
        {nodes.map((node) => {
          const p = positionOf(node);
          const NodeIcon = node.icon;
          const isSelected = selectedId === node.id;
          const isDragging = dragging?.id === node.id;
          const isHovered = hovered === node.id;
          const lit = isSelected || isHovered;
          return (
            <div
              key={node.id}
              className={cn(
                "absolute -translate-x-1/2 -translate-y-1/2 touch-none",
                isDragging || isSelected ? "z-30" : "z-20",
              )}
              style={{ left: `${p.x}%`, top: `${p.y}%` }}
              onPointerEnter={() => setHovered(node.id)}
              onPointerLeave={() => setHovered((current) => (current === node.id ? null : current))}
            >
              <button
                type="button"
                title={node.title}
                aria-label={node.title}
                aria-pressed={isSelected}
                onPointerDown={(event) => startDrag(event, node.id, "node")}
                onPointerUp={(event) => endDrag(event, node.id)}
                className={cn(
                  "relative flex h-12 w-12 items-center justify-center rounded-full border-2 transition-transform duration-150",
                  isDragging ? "scale-110 cursor-grabbing" : "cursor-grab hover:scale-110",
                )}
                style={{
                  borderColor: node.color,
                  background: skin.nodeFill,
                  backdropFilter: "blur(4px)",
                  boxShadow: `0 0 ${lit ? 30 : 16}px ${node.color}${
                    lit ? skin.glowAlpha.active : skin.glowAlpha.idle
                  }`,
                }}
              >
                <NodeIcon className="h-5 w-5" style={{ color: node.color }} />

                {isSelected && (
                  <span
                    className={cn(
                      "absolute -right-1 -top-1 flex h-4 w-4 items-center justify-center rounded-full border",
                      skin.badgeRing,
                    )}
                    style={{ background: node.color }}
                  >
                    <Check className="h-2.5 w-2.5 stroke-[3] text-white" />
                  </span>
                )}

                {node.isManual && (
                  <span
                    className={cn(
                      "absolute -left-1 -top-1 flex h-4 w-4 items-center justify-center rounded-full border",
                      skin.badgeRing,
                    )}
                    style={{ background: node.color }}
                    title="Added by hand"
                  >
                    <Pencil className="h-2 w-2 stroke-[3] text-white" />
                  </span>
                )}
              </button>

              <div className="pointer-events-none mt-1.5 flex justify-center">
                <span
                  className={cn(
                    "rounded-md px-1.5 py-0.5 text-[11px] font-semibold tabular-nums transition-colors",
                    lit ? skin.pillActive : skin.pillIdle,
                  )}
                >
                  +{formatCompactCurrency(node.value)}/mo
                </span>
              </div>

              {/* The title used to appear only on hover, so a node you had just
                  added was indistinguishable from any other. Shown under the
                  selected or hovered node instead. */}
              {lit && (
                <div className="pointer-events-none mt-1 flex justify-center">
                  <span
                    className={cn(
                      "max-w-[160px] truncate rounded-md px-1.5 py-0.5 text-[10px] font-medium",
                      skin.pillIdle,
                    )}
                  >
                    {node.title}
                  </span>
                </div>
              )}
            </div>
          );
        })}

        {/* Hovered node title, parked clear of the marks */}
        {hovered && !dragging && (
          <div className="pointer-events-none absolute bottom-3 left-1/2 z-40 -translate-x-1/2">
            <p
              className={cn(
                "max-w-[80vw] truncate rounded-lg border px-3 py-1.5 text-xs backdrop-blur-sm",
                skin.chip,
              )}
            >
              {nodes.find((node) => node.id === hovered)?.title}
            </p>
          </div>
        )}
      </div>

      {/* Affordance */}
      <span
        className={cn(
          "pointer-events-none absolute left-3 top-3 z-40 inline-flex items-center gap-1.5 rounded-lg border px-2 py-1 text-[11px] backdrop-blur-sm",
          skin.chip,
        )}
      >
        <Move className="h-3 w-3" />
        Drag any node to rearrange
      </span>

      {/* Controls */}
      <div className="absolute right-3 top-3 z-40 flex items-center gap-2">
        {isRearranged && (
          <button
            type="button"
            onClick={() => setMoved({})}
            className={cn(
              "inline-flex items-center gap-1.5 rounded-lg border px-2 py-1 text-[11px] backdrop-blur-sm transition-opacity hover:opacity-80 focus-ring",
              skin.chip,
            )}
          >
            <RotateCcw className="h-3 w-3" />
            Reset layout
          </button>
        )}
        {onAddNode && (
          <button
            type="button"
            onClick={onAddNode}
            className={cn(
              "inline-flex items-center gap-1.5 rounded-lg border px-2 py-1 text-[11px] backdrop-blur-sm transition-opacity hover:opacity-80 focus-ring",
              skin.chip,
            )}
          >
            <Plus className="h-3 w-3" />
            Add node
          </button>
        )}
        <button
          type="button"
          onClick={toggleSurface}
          aria-label={surface === "dark" ? "Switch to a light canvas" : "Switch to a dark canvas"}
          className={cn(
            "inline-flex items-center gap-1.5 rounded-lg border px-2 py-1 text-[11px] backdrop-blur-sm transition-opacity hover:opacity-80 focus-ring",
            skin.chip,
          )}
        >
          {surface === "dark" ? <Sun className="h-3 w-3" /> : <Moon className="h-3 w-3" />}
          {surface === "dark" ? "Light" : "Dark"}
        </button>
      </div>
    </div>
  );
}
