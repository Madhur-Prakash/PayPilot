"use client";

/** Procurement timeline - a Bryntum Gantt of every real stage, chained finish-to-start. */

import { CalendarRange, CheckCircle2, CircleDot, OctagonAlert, Truck } from "lucide-react";
import dynamic from "next/dynamic";
import * as React from "react";

import { EmptyState, ErrorState, LoadingCard } from "@/components/common/states";
import { MetricTile, PageHeader } from "@/components/supply/shared";
import { Card, CardContent } from "@/components/ui/primitives";
import { useProcurementTimeline } from "@/hooks/use-integrations";
import { formatRelativeTime } from "@/lib/utils";
import type { TimelineState, TimelineTask } from "@/types/integrations";

// Bryntum reads `window` at import time, so it must never render on the server.
const ProcurementGantt = dynamic(() => import("@/components/supply/procurement-gantt"), {
  ssr: false,
  loading: () => <LoadingCard lines={8} />,
});

const LEGEND: { state: TimelineState; label: string; colour: string }[] = [
  { state: "done", label: "Done", colour: "#1f9d55" },
  { state: "active", label: "In progress / waiting on a person", colour: "#0b6bcb" },
  { state: "blocked", label: "Blocked, rejected or overdue", colour: "#d64545" },
];

function flatten(tasks: TimelineTask[]): TimelineTask[] {
  return tasks.flatMap((t) => [t, ...(t.children ? flatten(t.children) : [])]);
}

export default function ProcurementTimelinePage() {
  const timeline = useProcurementTimeline(12);
  const all = React.useMemo(() => flatten(timeline.data?.tasks ?? []), [timeline.data]);
  const stages = all.filter((t) => !t.children);
  const count = (s: TimelineState) => stages.filter((t) => t.state === s).length;

  return (
    <div className="space-y-5">
      <PageHeader eyebrow="Supply" title="Procurement timeline"
        description="Every procurement as a chain of the stages that really happened - negotiation, human approval, purchase order and delivery, invoice, PayPal payment - with the dates the system recorded. Goods receipts are the diamonds; a partial delivery is a half-filled bar. Read-only: nothing here reschedules anything." />

      {timeline.error && <ErrorState error={timeline.error} onRetry={() => void timeline.refetch()} />}

      {timeline.data && timeline.data.count > 0 && (
        <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
          <MetricTile icon={Truck} tone="primary" label="Procurements shown" value={timeline.data.count} />
          <MetricTile icon={CheckCircle2} tone="success" label="Stages done" value={count("done")} />
          <MetricTile icon={CircleDot} label="Stages in progress" value={count("active")} />
          <MetricTile icon={OctagonAlert} tone={count("blocked") ? "destructive" : "default"} label="Blocked or overdue" value={count("blocked")} />
        </div>
      )}

      {timeline.isLoading && <LoadingCard lines={8} />}

      {timeline.data && timeline.data.count === 0 && (
        <EmptyState icon={CalendarRange} title="No procurements yet"
          description="Start one from Reorder Recommendations and its stages will appear here as they happen." />
      )}

      {timeline.data && timeline.data.count > 0 && (
        <Card>
          <CardContent className="space-y-3 p-3">
            <div className="flex flex-wrap items-center gap-x-5 gap-y-1 px-1 text-xs text-muted-foreground">
              {LEGEND.map((l) => (
                <span key={l.state} className="inline-flex items-center gap-1.5">
                  <span className="h-2.5 w-5 rounded-sm" style={{ background: l.colour }} />
                  {l.label}
                </span>
              ))}
              <span className="ml-auto">updated {formatRelativeTime(timeline.data.generated_at)} · Bryntum Gantt</span>
            </div>
            <ProcurementGantt timeline={timeline.data} />
          </CardContent>
        </Card>
      )}
    </div>
  );
}
