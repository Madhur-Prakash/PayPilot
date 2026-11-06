"use client";

/** Procurement timeline - a Bryntum Gantt of every real stage, chained finish-to-start. */

import { CalendarRange, CheckCircle2, CircleDot, Clock3, OctagonAlert, Truck } from "lucide-react";
import dynamic from "next/dynamic";
import * as React from "react";

import { EmptyState, ErrorState, LoadingCard } from "@/components/common/states";
import { MetricTile, PageHeader } from "@/components/supply/shared";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/primitives";
import { useProcurementTimeline, useReportDeliveryDelay } from "@/hooks/use-integrations";
import { cn, formatDate, formatRelativeTime } from "@/lib/utils";
import { useAuthStore } from "@/stores/auth";
import type { TimelineDelivery, TimelineState, TimelineTask } from "@/types/integrations";

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
  const deliveries = React.useMemo(
    () =>
      (timeline.data?.tasks ?? [])
        .map((t) => (t.delivery ? { ...t.delivery, procurement: t.name } : null))
        .filter((d): d is TimelineDelivery & { procurement: string } => Boolean(d && (d.open || d.delay_days > 0))),
    [timeline.data],
  );
  const anyDelayed = deliveries.some((d) => d.delay_days > 0);

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

      {hasData && deliveries.length > 0 && <DeliveryControls deliveries={deliveries} />}

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
            <ProcurementGantt timeline={timeline.data!} autoPlan={anyDelayed} />
          </CardContent>
        </Card>
      )}
    </div>
  );
}

/**
 * Open deliveries, with the supplier's side of the protocol one click away: its agent
 * sends a signed DELIVERY_UPDATE (DELAYED), and the delivery bar and the PayPal payment
 * that waits on it move right and turn red, with the original plan drawn underneath.
 */
function DeliveryControls({ deliveries }: { deliveries: (TimelineDelivery & { procurement: string })[] }) {
  const delay = useReportDeliveryDelay();
  const canAct = useAuthStore((s) => s.can("procurement:negotiate"));
  const [days, setDays] = React.useState(3);

  return (
    <Card className="min-w-0">
      <CardContent className="space-y-3 p-4">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <div>
            <h2 className="text-sm font-semibold">Deliveries in flight</h2>
            <p className="text-xs text-muted-foreground">
              When a supplier agent reports a delay, the delivery and the PayPal payment that waits on it are rescheduled
              on the chart - in red, with the original plan underneath.
            </p>
          </div>
          {canAct && (
            <div role="group" aria-label="Delay length" className="inline-flex rounded-lg border border-border bg-muted/40 p-0.5">
              {[2, 3, 5].map((d) => (
                <button key={d} type="button" aria-pressed={days === d} onClick={() => setDays(d)}
                  className={cn(
                    "rounded-md px-2.5 py-1 text-xs font-medium transition-colors focus-ring",
                    days === d ? "bg-card text-foreground shadow-sm" : "text-muted-foreground hover:text-foreground",
                  )}>
                  +{d} days
                </button>
              ))}
            </div>
          )}
        </div>
        <div className="divide-y divide-border rounded-lg border border-border">
          {deliveries.map((d) => (
            <div key={d.purchase_order_id} className="flex flex-wrap items-center gap-x-4 gap-y-2 px-3 py-2.5 text-sm">
              <div className="min-w-0 flex-1">
                <div className="truncate font-medium">{d.reference} <span className="font-normal text-muted-foreground">· {d.procurement}</span></div>
                <div className="text-xs text-muted-foreground">
                  {d.open ? "Expected " : "Delivered - was expected "}
                  {d.expected_at ? formatDate(d.expected_at) : "--"}
                  {d.delay_days > 0 && d.original_expected_at && <> · originally {formatDate(d.original_expected_at)}</>}
                  {" · "}{d.received_percent}% received
                </div>
              </div>
              {d.delay_days > 0 && (
                <span className="inline-flex items-center gap-1 rounded-full bg-destructive/10 px-2 py-0.5 text-2xs font-semibold text-destructive">
                  <Clock3 className="h-3 w-3" /> Rescheduled +{d.delay_days}d
                </span>
              )}
              {canAct && d.open && (
                <Button size="sm" variant="outline" className="gap-1.5"
                  loading={delay.isPending && delay.variables?.orderId === d.purchase_order_id}
                  onClick={() => delay.mutate({ orderId: d.purchase_order_id, days })}>
                  <Truck className="h-3.5 w-3.5" /> Supplier reports delay
                </Button>
              )}
            </div>
          ))}
        </div>
      </CardContent>
    </Card>
  );
}
