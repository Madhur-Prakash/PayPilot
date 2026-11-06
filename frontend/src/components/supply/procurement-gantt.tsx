"use client";

/**
 * Procurement timeline on Bryntum Gantt (8.0, Enterprise tier).
 *
 * Loaded client-side only (see the page) because Bryntum touches `window`. The chart
 * is a read-only *view*: every task is `manuallyScheduled`, so Bryntum never
 * reschedules anything and no drag can imply a commitment the backend did not make.
 *
 * Layout: the grid shows each stage with its detail underneath, a status pill and a
 * progress bar; the timeline shows only bars, dependencies and a "today" line, so no
 * text ever overlaps a bar. "Fit" zooms the axis so every stage is on screen; Day /
 * Week / Month switch to a fixed scale. Planned windows (baselines) are opt-in.
 *
 * Theme: `stockholm.css` resolves its colours with CSS `light-dark()`, and
 * procurement-gantt.css maps Bryntum's variables onto PayPilot's tokens - so the chart
 * follows the app's light/dark mode and palette. The host has `contain: inline-size`,
 * so however wide the timeline is, it scrolls inside the card and never widens the page.
 *
 * Licensing: `NEXT_PUBLIC_BRYNTUM_LICENSE_KEY` is registered below, before the first
 * Gantt is created. Without a key the Enterprise package runs as Bryntum's trial.
 */

// Order matters: icons, then the structural sheet, then exactly one theme, then ours.
import "@bryntum/core-enterprise/fontawesome/css/fontawesome.css";
import "@bryntum/core-enterprise/fontawesome/css/solid.css";
import "@bryntum/gantt-enterprise/gantt.css";
import "@bryntum/gantt-enterprise/stockholm.css";
import "./procurement-gantt.css";

import { BryntumGantt, BryntumGanttProjectModel } from "@bryntum/gantt-react-enterprise";
// Registers Scheduler's features in Gantt - `timeRanges` (the "today" line) belongs to
// Scheduler, and without this import Gantt fails with `Invalid type name "timeRanges"`.
import "@bryntum/scheduler-enterprise";
import { CalendarClock, Crosshair, Layers } from "lucide-react";
import * as React from "react";

import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";
import { countRows, STATE_LABEL, toGantt } from "@/lib/utils/timeline";
import type { ProcurementTimeline, TimelineState } from "@/types/integrations";

// The App Router has no client entry file, so this module - the only one that loads
// Bryntum - registers the key, once per page load, before any Gantt is created.
const LICENSE_KEY = process.env.NEXT_PUBLIC_BRYNTUM_LICENSE_KEY;
if (LICENSE_KEY) globalThis.bryntum.licenseKey = LICENSE_KEY;

type Zoom = "fit" | "day" | "week" | "month";

const ZOOMS: { id: Zoom; label: string }[] = [
  { id: "fit", label: "Fit" },
  { id: "day", label: "Day" },
  { id: "week", label: "Week" },
  { id: "month", label: "Month" },
];

const PRESET: Record<Zoom, string> = {
  fit: "weekAndDayLetter", // the starting point zoomToFit adjusts from
  day: "weekAndDayLetter",
  week: "weekAndMonth",
  month: "monthAndYear",
};

const ROW_HEIGHT = 56;
const HEADER_HEIGHT = 66;
const MIN_HEIGHT = 240;
const MAX_HEIGHT = 680;

const LEGEND: { state: TimelineState; label: string }[] = [
  { state: "done", label: "Done" },
  { state: "active", label: "In progress" },
  { state: "blocked", label: "Blocked or overdue" },
];

// --------------------------------------------------------------------------- //
// Cell and tooltip rendering. Grid cells use Bryntum DomConfig objects, whose `text`
// is set as textContent, so names, suppliers and emails are never parsed as HTML.
// The tooltip template returns an HTML string, so every value is escaped first.
// --------------------------------------------------------------------------- //
type RecordLike = {
  get?: (field: string) => unknown;
  originalData?: Record<string, unknown>;
  percentDone?: number;
  startDate?: Date;
  endDate?: Date;
  name?: string;
  isMilestone?: boolean;
};

function field(record: RecordLike, name: string): string {
  const value = record.get?.(name) ?? record.originalData?.[name];
  return value == null ? "" : String(value);
}

function escapeHtml(value: string): string {
  return value.replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]!);
}

const DAY = new Intl.DateTimeFormat("en-US", { month: "short", day: "numeric" });

function stateOf(record: RecordLike): TimelineState {
  const s = field(record, "state") as TimelineState;
  return s in STATE_LABEL ? s : "pending";
}

const COLUMNS = [
  {
    type: "name",
    field: "name",
    text: "Stage",
    flex: 1,
    minWidth: 260,
    renderer: ({ record, value }: { record: RecordLike; value: unknown }) => {
      const detail = field(record, "note");
      return {
        className: "pp-stage",
        children: [
          { tag: "div", className: "pp-stage-name", text: String(value ?? ""), title: String(value ?? "") },
          detail ? { tag: "div", className: "pp-stage-detail", text: detail, title: detail } : null,
        ].filter(Boolean),
      };
    },
  },
  {
    field: "state",
    text: "Status",
    width: 116,
    renderer: ({ record }: { record: RecordLike }) => {
      const state = stateOf(record);
      return { tag: "span", className: `pp-pill pp-pill-${state}`, text: STATE_LABEL[state] };
    },
  },
  {
    field: "percentDone",
    text: "Progress",
    width: 128,
    renderer: ({ record }: { record: RecordLike }) => {
      const pct = Math.max(0, Math.min(100, Math.round(Number(record.percentDone ?? 0))));
      const state = stateOf(record);
      return {
        className: "pp-progress",
        children: [
          { className: "pp-progress-track", children: [
            { className: `pp-progress-fill pp-progress-${state}`, style: { width: `${pct}%` } },
          ] },
          { tag: "span", className: "pp-progress-label", text: `${pct}%` },
        ],
      };
    },
  },
];

function tooltip({ taskRecord }: { taskRecord: RecordLike }): string {
  const state = stateOf(taskRecord);
  const start = taskRecord.startDate ? DAY.format(taskRecord.startDate) : "";
  const end = taskRecord.endDate ? DAY.format(taskRecord.endDate) : "";
  const when = taskRecord.isMilestone || start === end ? start : `${start} - ${end}`;
  const detail = field(taskRecord, "note");
  return `
    <div class="pp-tip">
      <div class="pp-tip-head">
        <span class="pp-pill pp-pill-${state}">${escapeHtml(STATE_LABEL[state])}</span>
        <span class="pp-tip-when">${escapeHtml(when)}</span>
      </div>
      <div class="pp-tip-name">${escapeHtml(field(taskRecord, "name") || taskRecord.name || "")}</div>
      ${detail ? `<div class="pp-tip-detail">${escapeHtml(detail)}</div>` : ""}
      <div class="pp-tip-pct">${Math.round(Number(taskRecord.percentDone ?? 0))}% complete</div>
    </div>`;
}

// --------------------------------------------------------------------------- //

export default function ProcurementGantt({
  timeline,
  autoPlan = false,
}: {
  timeline: ProcurementTimeline;
  /** Turn "Plan vs actual" on by itself - set when a supplier delay moved a stage off its plan. */
  autoPlan?: boolean;
}) {
  const { tasks, dependencies } = timeline;
  // Keyed on the arrays, not the response: React Query keeps them referentially equal when a
  // refetch brings nothing new (only `generated_at` moves), so an idle poll touches nothing.
  const data = React.useMemo(() => toGantt({ tasks, dependencies }), [tasks, dependencies]);
  const project = React.useRef<BryntumGanttProjectModel>(null);
  const gantt = React.useRef<BryntumGantt>(null);
  const host = React.useRef<HTMLDivElement>(null);
  const [zoom, setZoom] = React.useState<Zoom>("fit");
  const [showPlan, setShowPlan] = React.useState(false);

  const height = Math.min(MAX_HEIGHT, Math.max(MIN_HEIGHT, HEADER_HEIGHT + countRows(data.tasks) * ROW_HEIGHT + 2));
  const hasPlan = React.useMemo(() => {
    const walk = (list: typeof data.tasks): boolean =>
      list.some((t) => Boolean(t.baselines?.length) || (t.children ? walk(t.children) : false));
    return walk(data.tasks);
  }, [data]);

  const fit = React.useCallback(() => {
    const instance = gantt.current?.instance;
    if (instance && !instance.isDestroyed) void instance.zoomToFit({ leftMargin: 40, rightMargin: 80 });
  }, []);

  // Fit after the first paint, after new data, and whenever the card is resized.
  React.useEffect(() => {
    if (zoom !== "fit") return;
    const frame = requestAnimationFrame(fit);
    return () => cancelAnimationFrame(frame);
  }, [zoom, data, fit]);

  React.useEffect(() => {
    if (zoom !== "fit" || !host.current || typeof ResizeObserver === "undefined") return;
    let timer: ReturnType<typeof setTimeout> | undefined;
    const observer = new ResizeObserver(() => {
      clearTimeout(timer);
      timer = setTimeout(fit, 150);
    });
    observer.observe(host.current);
    return () => {
      clearTimeout(timer);
      observer.disconnect();
    };
  }, [zoom, fit]);

  React.useEffect(() => {
    if (autoPlan) setShowPlan(true);
  }, [autoPlan]);

  React.useEffect(() => {
    const baselines = gantt.current?.instance?.features?.baselines;
    if (baselines) baselines.disabled = !showPlan;
  }, [showPlan]);

  const choose = (next: Zoom) => {
    setZoom(next);
    const instance = gantt.current?.instance;
    if (instance && next !== "fit") instance.viewPreset = PRESET[next];
  };

  const today = () => {
    const instance = gantt.current?.instance;
    if (instance) void instance.scrollToNow({ block: "center", animate: true });
  };

  return (
    <div className="min-w-0 space-y-3">
      <div className="flex flex-wrap items-center gap-x-4 gap-y-2">
        <div className="flex flex-wrap items-center gap-x-4 gap-y-1 text-xs text-muted-foreground">
          {LEGEND.map((l) => (
            <span key={l.state} className="inline-flex items-center gap-1.5">
              <span className={cn("h-2.5 w-2.5 rounded-full", `pp-dot-${l.state}`)} />
              {l.label}
            </span>
          ))}
          <span className="inline-flex items-center gap-1.5">
            <span className="h-3 w-0.5 rounded-full bg-warning" />
            Today
          </span>
          {showPlan && (
            <span className="inline-flex items-center gap-1.5">
              <span className="h-1 w-4 rounded-full bg-muted-foreground/40" />
              Planned window
            </span>
          )}
        </div>

        <div className="ml-auto flex flex-wrap items-center gap-2">
          <div role="group" aria-label="Zoom" className="inline-flex rounded-lg border border-border bg-muted/40 p-0.5">
            {ZOOMS.map((z) => (
              <button key={z.id} type="button" aria-pressed={zoom === z.id} onClick={() => choose(z.id)}
                className={cn(
                  "rounded-md px-2.5 py-1 text-xs font-medium transition-colors focus-ring",
                  zoom === z.id ? "bg-card text-foreground shadow-sm" : "text-muted-foreground hover:text-foreground",
                )}>
                {z.label}
              </button>
            ))}
          </div>
          {hasPlan && (
            <Button size="sm" variant={showPlan ? "default" : "outline"} className="gap-1.5" aria-pressed={showPlan}
              onClick={() => setShowPlan((v) => !v)} title="Show each stage's planned window under its actual bar">
              <Layers className="h-3.5 w-3.5" /> Plan vs actual
            </Button>
          )}
          <Button size="sm" variant="outline" className="gap-1.5" onClick={today}>
            <Crosshair className="h-3.5 w-3.5" /> Today
          </Button>
        </div>
      </div>

      <div ref={host} className="pp-gantt-host" style={{ height }} data-testid="procurement-gantt">
        <BryntumGanttProjectModel ref={project} tasks={data.tasks} dependencies={data.dependencies} />
        <BryntumGantt
          ref={gantt}
          project={project}
          readOnly
          // Bryntum's default "Project start" line would mislabel a history chart.
          projectLinesFeature={false}
          baselinesFeature={{ disabled: true }}
          timeRangesFeature={{ showCurrentTimeLine: { name: "Today" } }}
          taskTooltipFeature={{ template: tooltip }}
          columnLinesFeature={false}
          startDate={data.range.start}
          endDate={data.range.end}
          viewPreset={PRESET.fit}
          rowHeight={ROW_HEIGHT}
          barMargin={17}
          // Wide enough for every column at its minimum, so none hides behind the splitter.
          subGridConfigs={{ locked: { width: 560 } }}
          columns={COLUMNS}
        />
      </div>
      <p className="flex items-center gap-1.5 text-2xs text-muted-foreground">
        <CalendarClock className="h-3 w-3" />
        Hover a bar for its dates and detail. Read-only: nothing here reschedules anything.
      </p>
    </div>
  );
}
