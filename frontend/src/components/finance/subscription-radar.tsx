"use client";

/**
 * Subscription revenue radar on Bryntum Scheduler (8.0, Enterprise tier).
 *
 * One row per PayPal subscriber, one bar per billing period: paid periods, the
 * period whose charge failed, PayPal's automatic retries, a suspension, a recovery
 * and the projected renewals ahead - with a "today" line between history and
 * forecast. Clicking a subscriber who needs it offers "Recover", which runs the real
 * subscription action and redraws the row.
 *
 * Read-only as a chart: drags, resizes and the event editor are off, because a bar
 * here is a fact PayPal reported (or a renewal it will attempt), never a plan to edit.
 *
 * CSS: the app also runs Bryntum Gantt, and Bryntum's rule is one structural sheet and
 * one theme from the highest product in use. `gantt.css` holds Scheduler's rules too,
 * so this component loads exactly the same two sheets as the procurement timeline.
 */

import "@bryntum/core-enterprise/fontawesome/css/fontawesome.css";
import "@bryntum/core-enterprise/fontawesome/css/solid.css";
import "@bryntum/gantt-enterprise/gantt.css";
import "@bryntum/gantt-enterprise/stockholm.css";
import "./subscription-radar.css";

import { BryntumScheduler } from "@bryntum/scheduler-react-enterprise";
import { Crosshair, LifeBuoy } from "lucide-react";
import * as React from "react";

import { Button } from "@/components/ui/button";
import { cn, formatMoney } from "@/lib/utils";
import type { RadarEvent, RadarEventKind, RadarResource, RadarRisk, SubscriptionRadar } from "@/types/supply";

const LICENSE_KEY = process.env.NEXT_PUBLIC_BRYNTUM_LICENSE_KEY;
if (LICENSE_KEY) globalThis.bryntum.licenseKey = LICENSE_KEY;

const ROW_HEIGHT = 48;
const HEADER_HEIGHT = 66;
const MIN_HEIGHT = 260;
const MAX_HEIGHT = 720;

type EventStyle = "tonal" | "filled" | "outlined" | "dashed";

/** Bryntum named colours + event styles: history is solid, the forecast is outlined. */
const LOOK: Record<RadarEventKind, { color: string; style: EventStyle; label: string }> = {
  paid: { color: "green", style: "tonal", label: "Paid" },
  failed: { color: "red", style: "filled", label: "Charge failed" },
  // Markers sit on top of the red failed bar, so they need a contrasting colour.
  retry: { color: "amber", style: "filled", label: "Retry failed" },
  suspended: { color: "black", style: "filled", label: "Suspended" },
  recovered: { color: "green", style: "filled", label: "Recovered" },
  cancelled: { color: "gray", style: "filled", label: "Cancelled" },
  scheduled: { color: "blue", style: "outlined", label: "Renewal" },
  at_risk: { color: "orange", style: "dashed", label: "Renewal at risk" },
  paused: { color: "gray", style: "dashed", label: "Paused" },
};

const LEGEND: RadarEventKind[] = ["paid", "failed", "retry", "suspended", "recovered", "scheduled", "at_risk", "paused"];

const RISK_LABEL: Record<RadarRisk, string> = {
  healthy: "Healthy",
  at_risk: "At risk",
  suspended: "Suspended",
  cancelled: "Cancelled",
};

type RecordLike = {
  get?: (field: string) => unknown;
  originalData?: Record<string, unknown>;
  startDate?: Date;
  endDate?: Date;
  name?: string;
  isMilestone?: boolean;
};

function field(record: RecordLike | undefined, name: string): string {
  if (!record) return "";
  const value = record.get?.(name) ?? record.originalData?.[name];
  return value == null ? "" : String(value);
}

function escapeHtml(value: string): string {
  return value.replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]!);
}

const DAY = new Intl.DateTimeFormat("en-US", { month: "short", day: "numeric" });

// Grid cells return DomConfig objects: `text` is set as textContent, never parsed as HTML.
const COLUMNS = [
  {
    field: "name",
    text: "Subscriber",
    flex: 1,
    minWidth: 190,
    renderer: ({ record }: { record: RecordLike }) => ({
      className: "pp-sub",
      children: [
        { tag: "div", className: "pp-sub-name", text: field(record, "name") },
        { tag: "div", className: "pp-sub-plan", text: field(record, "plan") },
      ],
    }),
  },
  {
    field: "risk",
    text: "Health",
    width: 112,
    renderer: ({ record }: { record: RecordLike }) => {
      const risk = (field(record, "risk") || "healthy") as RadarRisk;
      const failed = Number(field(record, "failed_payments") || 0);
      return {
        className: "pp-sub-health",
        children: [
          { tag: "span", className: `pp-risk pp-risk-${risk}`, text: RISK_LABEL[risk] ?? risk },
          failed > 0 ? { tag: "span", className: "pp-sub-failed", text: `${failed} failed` } : null,
        ].filter(Boolean),
      };
    },
  },
  {
    field: "amount",
    text: "MRR",
    width: 84,
    align: "end",
    renderer: ({ record }: { record: RecordLike }) => ({
      tag: "span",
      className: "pp-sub-amount",
      text: formatMoney(field(record, "amount")),
    }),
  },
];

function tooltip({ eventRecord, resourceRecord }: { eventRecord: RecordLike; resourceRecord?: RecordLike }): string {
  const kind = (field(eventRecord, "kind") || "paid") as RadarEventKind;
  const look = LOOK[kind] ?? LOOK.paid;
  const start = eventRecord.startDate ? DAY.format(eventRecord.startDate) : "";
  const end = eventRecord.endDate ? DAY.format(eventRecord.endDate) : "";
  const when = eventRecord.isMilestone || start === end ? start : `${start} - ${end}`;
  return `
    <div class="pp-tip">
      <div class="pp-tip-head">
        <span class="pp-kind pp-kind-${kind}">${escapeHtml(look.label)}</span>
        <span class="pp-tip-when">${escapeHtml(when)}</span>
      </div>
      <div class="pp-tip-name">${escapeHtml(field(resourceRecord, "name"))}</div>
      <div class="pp-tip-detail">${escapeHtml(field(eventRecord, "name"))}</div>
      <div class="pp-tip-detail">${escapeHtml(field(resourceRecord, "paypal_subscription_id"))}</div>
    </div>`;
}

function toScheduler(radar: SubscriptionRadar) {
  const events = radar.events.map((e: RadarEvent) => {
    const look = LOOK[e.kind] ?? LOOK.paid;
    return {
      ...e,
      // Milestones (retries, recovery) are zero-length on purpose.
      ...(e.startDate === e.endDate ? { duration: 0 } : {}),
      eventColor: look.color,
      eventStyle: look.style,
      cls: `pp-ev pp-ev-${e.kind}`,
      draggable: false,
      resizable: false,
    };
  });
  // Bryntum 8's EventModel typing still lists the pre-8 style names; the runtime (and its CSS)
  // accepts both, so the new names are passed through the wrapper's own prop type.
  return { resources: radar.resources, events: events as unknown as SchedulerProps["events"] };
}

type SchedulerProps = React.ComponentProps<typeof BryntumScheduler>;

export default function SubscriptionRadarChart({
  radar,
  onRecover,
  canManage,
  recovering,
}: {
  radar: SubscriptionRadar;
  onRecover: (resource: RadarResource) => void;
  canManage: boolean;
  recovering: boolean;
}) {
  const data = React.useMemo(() => toScheduler(radar), [radar]);
  const scheduler = React.useRef<BryntumScheduler>(null);
  const [selected, setSelected] = React.useState<RadarResource | null>(null);

  // Keep the selection's details fresh after a refetch (e.g. once it is recovered).
  React.useEffect(() => {
    setSelected((current) => (current ? radar.resources.find((r) => r.id === current.id) ?? null : null));
  }, [radar]);

  const height = Math.min(MAX_HEIGHT, Math.max(MIN_HEIGHT, HEADER_HEIGHT + data.resources.length * ROW_HEIGHT + 2));

  const today = () => {
    const instance = scheduler.current?.instance;
    if (instance) void instance.scrollToNow({ block: "center", animate: true });
  };

  // Open on "today" - history to the left, forecast to the right - instead of the window's
  // first day, where none of the failures or renewals would be on screen.
  React.useEffect(() => {
    const frame = requestAnimationFrame(() => {
      const instance = scheduler.current?.instance;
      if (instance && !instance.isDestroyed) void instance.scrollToNow({ block: "center" });
    });
    return () => cancelAnimationFrame(frame);
  }, [radar.window.start, radar.window.end]);

  const pick = React.useCallback(
    (record: RecordLike | undefined) => {
      const id = field(record, "id");
      setSelected(radar.resources.find((r) => r.id === id) ?? null);
    },
    [radar],
  );

  return (
    <div className="min-w-0 space-y-3">
      <div className="flex flex-wrap items-center gap-x-4 gap-y-2">
        <div className="flex flex-wrap items-center gap-x-4 gap-y-1 text-xs text-muted-foreground">
          {LEGEND.map((kind) => (
            <span key={kind} className="inline-flex items-center gap-1.5">
              <span className={cn("pp-swatch", `pp-swatch-${kind}`)} />
              {LOOK[kind].label}
            </span>
          ))}
          <span className="inline-flex items-center gap-1.5">
            <span className="h-3 w-0.5 rounded-full bg-warning" />
            Today
          </span>
        </div>
        <Button size="sm" variant="outline" className="ml-auto gap-1.5" onClick={today}>
          <Crosshair className="h-3.5 w-3.5" /> Today
        </Button>
      </div>

      {selected && (
        <div className="flex flex-wrap items-center gap-3 rounded-lg border border-border bg-muted/30 px-3 py-2 text-sm">
          <span className="font-medium">{selected.name}</span>
          <span className={cn("pp-risk", `pp-risk-${selected.risk}`)}>{RISK_LABEL[selected.risk]}</span>
          <span className="text-muted-foreground">
            {formatMoney(selected.amount)}/{selected.interval.toLowerCase()} · next charge{" "}
            {DAY.format(new Date(selected.next_billing_at))} · {selected.paypal_subscription_id}
          </span>
          {canManage && (selected.risk === "at_risk" || selected.risk === "suspended") && (
            <Button size="sm" className="ml-auto gap-1.5" loading={recovering} onClick={() => onRecover(selected)}>
              <LifeBuoy className="h-3.5 w-3.5" /> Recover payment
            </Button>
          )}
        </div>
      )}

      <div className="pp-radar-host" style={{ height }} data-testid="subscription-radar">
        <BryntumScheduler
          ref={scheduler}
          readOnly
          resources={data.resources}
          events={data.events}
          startDate={new Date(radar.window.start)}
          endDate={new Date(radar.window.end)}
          viewPreset="weekAndMonth"
          rowHeight={ROW_HEIGHT}
          barMargin={12}
          // Retries and recoveries sit on top of their billing period instead of
          // stacking into extra lanes, so every row keeps the same height.
          eventLayout="none"
          columns={COLUMNS}
          subGridConfigs={{ locked: { width: 400 } }}
          eventDragFeature={false}
          eventResizeFeature={false}
          eventEditFeature={false}
          eventDragCreateFeature={false}
          eventMenuFeature={false}
          scheduleMenuFeature={false}
          columnLinesFeature={false}
          timeRangesFeature={{ showCurrentTimeLine: { name: "Today" } }}
          eventTooltipFeature={{ template: tooltip }}
          eventRenderer={({ eventRecord }: { eventRecord: RecordLike }) =>
            eventRecord.isMilestone ? "" : field(eventRecord, "name")
          }
          onEventClick={({ resourceRecord }: { resourceRecord: RecordLike }) => pick(resourceRecord)}
          onCellClick={({ record }: { record: RecordLike }) => pick(record)}
        />
      </div>
      <p className="text-2xs text-muted-foreground">
        Click a subscriber for details. Bars to the left of today are charges PayPal reported; to the right, renewals it
        will attempt. Recovering a subscriber reactivates it through the PayPal Subscriptions API.
      </p>
    </div>
  );
}
