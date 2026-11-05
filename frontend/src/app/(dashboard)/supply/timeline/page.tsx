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

function flatten(tasks: TimelineTask[]): TimelineTask[] {
  return tasks.flatMap((t) => [t, ...(t.children ? flatten(t.children) : [])]);
}

export default function ProcurementTimelinePage() {
  const timeline = useProcurementTimeline(12);
  const all = React.useMemo(() => flatten(timeline.data?.tasks ?? []), [timeline.data]);
  const stages = all.filter((t) => !t.children);
  const count = (s: TimelineState) => stages.filter((t) => t.state === s).length;
  const hasData = Boolean(timeline.data && timeline.data.count > 0);

  return (
    <div className="min-w-0 space-y-5">
      <PageHeader eyebrow="Supply" title="Procurement timeline"
        description="Every procurement as the chain of stages that actually happened - negotiation, approval, purchase order and delivery, invoice and PayPal payment - on the dates PayPilot recorded." />

      {timeline.error && <ErrorState error={timeline.error} onRetry={() => void timeline.refetch()} />}

      {hasData && (
        <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
          <MetricTile icon={Truck} tone="primary" label="Procurements" value={timeline.data!.count} />
          <MetricTile icon={CheckCircle2} tone="success" label="Stages done" value={count("done")} />
          <MetricTile icon={CircleDot} label="In progress" value={count("active")} />
          <MetricTile icon={OctagonAlert} tone={count("blocked") ? "destructive" : "default"} label="Blocked or overdue"
            value={count("blocked")} />
        </div>
      )}

      {timeline.isLoading && <LoadingCard lines={8} />}

      {timeline.data && timeline.data.count === 0 && (
        <EmptyState icon={CalendarRange} title="No procurements yet"
          description="Start one from Reorder Recommendations and its stages will appear here as they happen." />
      )}

      {hasData && (
        <Card className="min-w-0 overflow-hidden">
          <CardContent className="min-w-0 space-y-3 p-4">
            <div className="flex flex-wrap items-baseline justify-between gap-2">
              <div>
                <h2 className="text-sm font-semibold">Stages</h2>
                <p className="text-xs text-muted-foreground">
                  A partial delivery is a partly filled bar; goods receipts are diamonds.
                </p>
              </div>
              <span className="text-2xs text-muted-foreground">
                updated {formatRelativeTime(timeline.data!.generated_at)} · Bryntum Gantt
              </span>
            </div>
            <ProcurementGantt timeline={timeline.data!} />
          </CardContent>
        </Card>
      )}
    </div>
  );
}
