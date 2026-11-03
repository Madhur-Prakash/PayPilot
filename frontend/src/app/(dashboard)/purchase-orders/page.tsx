"use client";

/**
 * Purchase orders: the approval gate and goods receiving.
 *
 * Approving is the one place a human authorises money to move, so the order's
 * own reasoning - what triggered it, which strategy sized it, why this vendor -
 * is shown next to the button rather than buried in a detail view.
 */

import { Check, PackageCheck, ShoppingCart, Truck, X } from "lucide-react";
import * as React from "react";

import { EmptyState, ErrorState, LoadingRows } from "@/components/common/states";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/overlays";
import {
  Badge,
  Card,
  CardContent,
  CardHeader,
  CardTitle,
  Input,
  Label,
  Separator,
} from "@/components/ui/primitives";
import {
  useApprovePurchaseOrder,
  usePurchaseOrders,
  useReceivePurchaseOrder,
} from "@/hooks/use-api";
import { useInventoryStream } from "@/hooks/use-inventory-stream";
import { useAuthStore } from "@/stores/auth";
import { cn, formatCompactCurrency, formatNumber } from "@/lib/utils";
import type { PurchaseOrderRow } from "@/types/api";

const STATUS_TONE: Record<string, string> = {
  PENDING_APPROVAL: "bg-warning/10 text-warning",
  APPROVED: "bg-primary/10 text-primary",
  ORDERED: "bg-primary/10 text-primary",
  ACKNOWLEDGED: "bg-primary/10 text-primary",
  PARTIALLY_RECEIVED: "bg-warning/10 text-warning",
  RECEIVED: "bg-success/10 text-success",
  REJECTED: "bg-destructive/10 text-destructive",
  CANCELLED: "bg-muted text-muted-foreground",
  FAILED: "bg-destructive/10 text-destructive",
  DRAFT: "bg-muted text-muted-foreground",
};

const FILTERS = ["all", "PENDING_APPROVAL", "ORDERED", "PARTIALLY_RECEIVED", "RECEIVED"];

export default function PurchaseOrdersPage() {
  const [filter, setFilter] = React.useState("all");
  const [receiving, setReceiving] = React.useState<PurchaseOrderRow | null>(null);

  useInventoryStream({ notify: false });

  const canApprove = useAuthStore((s) => s.can("purchase_order:approve"));
  const canReceive = useAuthStore((s) => s.can("purchase_order:receive"));

  const approve = useApprovePurchaseOrder();
  const receive = useReceivePurchaseOrder();

  const { data, isLoading, isFetching, error, refetch } = usePurchaseOrders({
    page: 1,
    page_size: 50,
    status: filter === "all" ? undefined : filter,
  });

  const orders = data?.items ?? [];
  const awaiting = orders.filter((o) => o.status === "PENDING_APPROVAL").length;

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h2 className="text-xl font-semibold tracking-tight">Purchase orders</h2>
          <p className="text-sm text-muted-foreground">
            Raised by automation or by hand. Nothing reaches a vendor without passing the gate.
          </p>
        </div>
        {awaiting > 0 && (
          <Badge variant="warning" className="gap-1.5">
            {awaiting} awaiting approval
          </Badge>
        )}
      </div>

      <div className="flex flex-wrap gap-1.5">
        {FILTERS.map((value) => (
          <button
            key={value}
            type="button"
            onClick={() => setFilter(value)}
            aria-pressed={filter === value}
            className={cn(
              "rounded-lg border px-3 py-1 text-xs font-medium transition-colors focus-ring",
              filter === value
                ? "border-primary bg-primary text-primary-foreground"
                : "border-border bg-card hover:bg-muted",
            )}
          >
            {value === "all" ? "All" : value.toLowerCase().replace(/_/g, " ")}
          </button>
        ))}
      </div>

      <Card>
        <CardHeader className="pb-3">
          <CardTitle className="text-base">Orders</CardTitle>
        </CardHeader>
        <CardContent className="space-y-2">
          {isLoading && <LoadingRows rows={4} />}
          {error && <ErrorState error={error} onRetry={() => void refetch()} />}

          {!isLoading && !error && orders.length === 0 && (
            <EmptyState
              icon={ShoppingCart}
              title="No purchase orders"
              description="They appear here when stock crosses a reorder point, or when you raise one."
            />
          )}

          <div className={cn("space-y-2", isFetching && "opacity-60")}>
            {orders.map((order) => {
              const outstanding = order.lines.reduce(
                (sum, l) => sum + (l.quantity_ordered - l.quantity_received),
                0,
              );
              return (
                <div key={order.purchase_order_id} className="rounded-xl border border-border bg-card p-3">
                  <div className="flex flex-wrap items-start justify-between gap-3">
                    <div className="min-w-0 flex-1">
                      <div className="flex flex-wrap items-center gap-2">
                        <span className="font-mono text-sm font-semibold">{order.reference}</span>
                        <span
                          className={cn(
                            "rounded-md px-1.5 py-0.5 text-2xs font-semibold",
                            STATUS_TONE[order.status] ?? "bg-muted text-muted-foreground",
                          )}
                        >
                          {order.status.toLowerCase().replace(/_/g, " ")}
                        </span>
                        {order.source === "AUTOMATION" && (
                          <Badge variant="outline" className="text-2xs">
                            automated
                          </Badge>
                        )}
                        {order.is_dry_run && (
                          <Badge variant="warning" className="text-2xs">
                            dry run — nothing sent
                          </Badge>
                        )}
                      </div>

                      <p className="mt-1 text-2xs text-muted-foreground">
                        {order.vendor_name} · {formatCompactCurrency(order.total_value)}
                        {order.expected_at && ` · expected ${order.expected_at}`}
                      </p>

                      <div className="mt-2 space-y-1">
                        {order.lines.map((line) => (
                          <div
                            key={line.line_id}
                            className="flex flex-wrap items-center gap-2 text-2xs tabular-nums"
                          >
                            <span className="font-mono text-muted-foreground">{line.sku}</span>
                            <span>{line.product_name}</span>
                            <span className="text-muted-foreground">
                              {formatNumber(line.quantity_received)} /{" "}
                              {formatNumber(line.quantity_ordered)} received
                            </span>
                          </div>
                        ))}
                      </div>
                    </div>

                    <div className="flex flex-wrap items-center gap-2">
                      {canApprove && order.status === "PENDING_APPROVAL" && (
                        <>
                          <Button
                            size="sm"
                            className="gap-1.5"
                            loading={approve.isPending}
                            onClick={() =>
                              approve.mutate({ id: order.purchase_order_id, approve: true })
                            }
                          >
                            <Check className="h-3.5 w-3.5" />
                            Approve
                          </Button>
                          <Button
                            size="sm"
                            variant="outline"
                            className="gap-1.5"
                            disabled={approve.isPending}
                            onClick={() =>
                              approve.mutate({ id: order.purchase_order_id, approve: false })
                            }
                          >
                            <X className="h-3.5 w-3.5" />
                            Reject
                          </Button>
                        </>
                      )}

                      {canReceive && outstanding > 0 && order.status !== "PENDING_APPROVAL" && (
                        <Button
                          size="sm"
                          variant="outline"
                          className="gap-1.5"
                          onClick={() => setReceiving(order)}
                        >
                          <Truck className="h-3.5 w-3.5" />
                          Receive
                        </Button>
                      )}
                    </div>
                  </div>
                </div>
              );
            })}
          </div>
        </CardContent>
      </Card>

      <ReceiveDialog
        order={receiving}
        onClose={() => setReceiving(null)}
        pending={receive.isPending}
        onSubmit={(lines) => {
          if (!receiving) return;
          receive.mutate(
            { id: receiving.purchase_order_id, lines },
            { onSuccess: () => setReceiving(null) },
          );
        }}
      />
    </div>
  );
}

function ReceiveDialog({
  order,
  onClose,
  onSubmit,
  pending,
}: {
  order: PurchaseOrderRow | null;
  onClose: () => void;
  onSubmit: (lines: { line_id: string; quantity: number }[]) => void;
  pending: boolean;
}) {
  const [amounts, setAmounts] = React.useState<Record<string, string>>({});

  React.useEffect(() => {
    if (!order) return;
    // Default to the full outstanding amount - the common case is a complete
    // delivery, and a short one is a correction the receiver makes deliberately.
    setAmounts(
      Object.fromEntries(
        order.lines.map((l) => [
          l.line_id,
          String(Math.max(l.quantity_ordered - l.quantity_received, 0)),
        ]),
      ),
    );
  }, [order]);

  if (!order) return null;

  const lines = order.lines
    .map((l) => ({ line_id: l.line_id, quantity: Number(amounts[l.line_id] ?? 0) }))
    .filter((l) => l.quantity > 0);

  return (
    <Dialog open={Boolean(order)} onOpenChange={(next) => !next && onClose()}>
      <DialogContent className="max-w-lg">
        <DialogHeader>
          <DialogTitle>Receive {order.reference}</DialogTitle>
          <DialogDescription>
            Booking in stock writes a ledger row per line and updates availability
            immediately. Receiving less than ordered leaves the order partially received.
          </DialogDescription>
        </DialogHeader>

        <div className="space-y-3">
          {order.lines.map((line) => {
            const outstanding = line.quantity_ordered - line.quantity_received;
            return (
              <div key={line.line_id} className="space-y-1.5">
                <Label htmlFor={`recv-${line.line_id}`}>
                  {line.product_name}{" "}
                  <span className="font-mono text-2xs text-muted-foreground">{line.sku}</span>
                </Label>
                <div className="flex items-center gap-2">
                  <Input
                    id={`recv-${line.line_id}`}
                    type="number"
                    min={0}
                    max={outstanding}
                    value={amounts[line.line_id] ?? ""}
                    onChange={(event) =>
                      setAmounts((current) => ({
                        ...current,
                        [line.line_id]: event.target.value,
                      }))
                    }
                  />
                  <span className="whitespace-nowrap text-2xs text-muted-foreground tabular-nums">
                    of {formatNumber(outstanding)} outstanding
                  </span>
                </div>
              </div>
            );
          })}
        </div>

        <Separator />

        <DialogFooter>
          <Button variant="ghost" onClick={onClose}>
            Cancel
          </Button>
          <Button
            className="gap-1.5"
            loading={pending}
            disabled={lines.length === 0}
            onClick={() => onSubmit(lines)}
          >
            <PackageCheck className="h-4 w-4" />
            Record receipt
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
