"use client";

/**
 * One automation chain, end to end.
 *
 * A correlation id is stamped on everything a single triggering event causes.
 * This renders that chain in causal order — the event that started it, the runs
 * that reacted, the stock that moved, the orders that were raised — because the
 * question being asked is never "what is the state?" but "why did this happen?".
 */

import {
  ArrowRight,
  CircleCheck,
  CircleX,
  ExternalLink,
  PackageCheck,
  Radio,
  ShoppingCart,
  Workflow,
} from "lucide-react";
import Link from "next/link";

import { ErrorState, LoadingRows } from "@/components/common/states";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/overlays";
import { Badge, Separator } from "@/components/ui/primitives";
import { useAutomationTrace } from "@/hooks/use-api";
import { n8nExecutionUrl } from "@/lib/n8n";
import { cn, formatCompactCurrency, formatNumber, formatRelativeTime } from "@/lib/utils";

const DELIVERY_TONE: Record<string, string> = {
  DELIVERED: "text-success",
  PENDING: "text-warning",
  FAILED: "text-destructive",
  SKIPPED: "text-muted-foreground",
};

export function AutomationTraceDialog({
  correlationId,
  onClose,
  n8nBase = "",
}: {
  correlationId: string | null;
  onClose: () => void;
  n8nBase?: string;
}) {
  const { data, isLoading, error, refetch } = useAutomationTrace(correlationId);

  return (
    <Dialog open={Boolean(correlationId)} onOpenChange={(next) => !next && onClose()}>
      <DialogContent className="max-h-[85vh] max-w-2xl overflow-y-auto">
        <DialogHeader>
          <DialogTitle>Why this happened</DialogTitle>
          <DialogDescription>
            Everything caused by one triggering event, in order.{" "}
            <span className="font-mono text-2xs">{correlationId}</span>
          </DialogDescription>
        </DialogHeader>

        {isLoading && <LoadingRows rows={5} />}
        {error && <ErrorState error={error} onRetry={() => void refetch()} />}

        {data && (
          <div className="space-y-5">
            <Section
              icon={Radio}
              title="Events emitted"
              count={data.events.length}
              empty="No events were recorded for this chain."
            >
              {data.events.map((event) => (
                <div key={event.id} className="rounded-lg border border-border bg-card p-2.5">
                  <div className="flex flex-wrap items-center justify-between gap-2">
                    <span className="font-mono text-2xs font-medium">{event.event_type}</span>
                    <span
                      className={cn(
                        "text-2xs font-semibold",
                        DELIVERY_TONE[event.delivery_status] ?? "text-muted-foreground",
                      )}
                    >
                      {event.delivery_status.toLowerCase()}
                      {event.attempts > 1 && ` · ${event.attempts} attempts`}
                    </span>
                  </div>
                  <p className="mt-0.5 text-2xs text-muted-foreground">
                    {formatRelativeTime(event.at ?? "")}
                  </p>
                </div>
              ))}
            </Section>

            <Section
              icon={Workflow}
              title="Automation runs"
              count={data.runs.length}
              empty="Nothing reacted to this event."
            >
              {data.runs.map((run) => (
                <div key={run.id} className="rounded-lg border border-border bg-card p-2.5">
                  <div className="flex flex-wrap items-center justify-between gap-2">
                    <span className="font-mono text-2xs font-medium">{run.workflow_name}</span>
                    <Badge variant="outline" className="text-2xs">
                      {run.status.toLowerCase().replace(/_/g, " ")}
                    </Badge>
                  </div>
                  <ol className="mt-2 space-y-1">
                    {run.steps.map((step, index) => (
                      <li key={`${step.at}-${index}`} className="flex items-start gap-1.5">
                        {step.status === "error" ? (
                          <CircleX className="mt-0.5 h-3 w-3 shrink-0 text-destructive" />
                        ) : (
                          <CircleCheck
                            className={cn(
                              "mt-0.5 h-3 w-3 shrink-0",
                              step.status === "pending" ? "text-warning" : "text-success",
                            )}
                          />
                        )}
                        <span className="text-2xs leading-relaxed">
                          <span className="font-medium">{step.step}</span>{" "}
                          <span className="text-muted-foreground">{step.detail}</span>
                        </span>
                      </li>
                    ))}
                  </ol>
                  {run.n8n_execution_id && n8nBase && (
                    <a
                      href={n8nExecutionUrl(n8nBase, run.workflow_name, run.n8n_execution_id)}
                      target="_blank"
                      rel="noreferrer"
                      className="mt-2 inline-flex items-center gap-1 text-2xs font-medium text-primary hover:underline"
                    >
                      <ExternalLink className="h-3 w-3" />
                      Execution {run.n8n_execution_id} in n8n
                    </a>
                  )}
                </div>
              ))}
            </Section>

            <Section
              icon={PackageCheck}
              title="Stock that moved"
              count={data.movements.length}
              empty="No stock changed as a result."
            >
              {data.movements.map((movement) => (
                <div
                  key={movement.id}
                  className="flex flex-wrap items-center justify-between gap-2 rounded-lg border border-border bg-card px-2.5 py-2 text-2xs tabular-nums"
                >
                  <span className="font-medium">
                    {movement.movement_type.toLowerCase().replace(/_/g, " ")}
                  </span>
                  <span className="flex items-center gap-1.5 text-muted-foreground">
                    {formatNumber(movement.quantity)}
                    <ArrowRight className="h-3 w-3" />
                    <span className="font-semibold text-foreground">
                      {formatNumber(movement.balance_after)}
                    </span>
                  </span>
                </div>
              ))}
            </Section>

            <Section
              icon={ShoppingCart}
              title="Orders raised"
              count={data.purchase_orders.length}
              empty="No purchase order came out of this chain."
            >
              {data.purchase_orders.map((order) => (
                <Link
                  key={order.purchase_order_id}
                  href="/purchase-orders"
                  className="block rounded-lg border border-border bg-card p-2.5 transition-colors hover:border-primary/40"
                >
                  <div className="flex flex-wrap items-center justify-between gap-2">
                    <span className="font-mono text-2xs font-semibold">{order.reference}</span>
                    <span className="text-2xs text-muted-foreground">
                      {order.vendor_name} · {formatCompactCurrency(order.total_value)}
                    </span>
                  </div>
                  <p className="mt-0.5 text-2xs text-muted-foreground">
                    {order.status.toLowerCase().replace(/_/g, " ")}
                  </p>
                </Link>
              ))}
            </Section>
          </div>
        )}
      </DialogContent>
    </Dialog>
  );
}

function Section({
  icon: Icon,
  title,
  count,
  empty,
  children,
}: {
  icon: typeof Radio;
  title: string;
  count: number;
  empty: string;
  children: React.ReactNode;
}) {
  return (
    <div className="space-y-2">
      <div className="flex items-center gap-2">
        <Icon className="h-3.5 w-3.5 text-muted-foreground" />
        <h4 className="text-xs font-semibold">{title}</h4>
        <span className="text-2xs text-muted-foreground tabular-nums">{count}</span>
      </div>
      <Separator />
      {count === 0 ? <p className="text-2xs text-muted-foreground">{empty}</p> : children}
    </div>
  );
}
