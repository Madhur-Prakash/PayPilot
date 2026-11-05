"use client";

/** Payments: every PayPal money movement, the approval that authorised it, and its idempotency key. */

import type { ColDef } from "ag-grid-community";
import { CreditCard } from "lucide-react";
import * as React from "react";

import { ErrorState } from "@/components/common/states";
import { DataGrid } from "@/components/data/data-grid";
import { ModeBadge, PageHeader, StatusPill } from "@/components/supply/shared";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/primitives";
import { useCapturePayment, usePayments } from "@/hooks/use-supply";
import { cn, formatDateTime, formatMoney, toNumber } from "@/lib/utils";
import type { Execution } from "@/types/supply";

const KINDS = ["all", "SUPPLIER_SETTLEMENT", "CASHBACK_PAYOUT"];

/**
 * PayPal sends the payer back here after they approve (or cancel) a supplier payment:
 * `?execution=<id>` and, on cancel, `&cancelled=1`. Capturing is still an explicit
 * click - the human approval was recorded earlier; this settles the approved order.
 */
function ReturnFromPayPal({ executions }: { executions: Execution[] | undefined }) {
  const [params, setParams] = React.useState<URLSearchParams | null>(null);
  React.useEffect(() => setParams(new URLSearchParams(window.location.search)), []);
  const capture = useCapturePayment();
  const executionId = params?.get("execution");
  if (!executionId) return null;
  const cancelled = params?.get("cancelled") === "1";
  const execution = executions?.find((e) => e.execution_id === executionId);
  const settled = execution && execution.status !== "PAYER_ACTION_REQUIRED";

  return (
    <Card className={cn("border-2", cancelled ? "border-warning/40" : "border-primary/40")}>
      <CardContent className="flex flex-wrap items-center gap-3 p-4">
        <div className="min-w-0 flex-1 space-y-0.5">
          <p className="text-sm font-semibold">
            {cancelled ? "Payment cancelled in PayPal" : settled ? "Payment settled" : "Back from PayPal - approval received"}
          </p>
          <p className="text-xs text-muted-foreground">
            {cancelled
              ? "Nothing was charged. Pay the invoice again from the purchase order when you are ready."
              : execution
                ? `${formatMoney(toNumber(execution.amount))} to ${execution.payee_email ?? "the supplier"} - PayPal order ${execution.paypal_order_id}`
                : "Loading the payment…"}
          </p>
        </div>
        {execution && <StatusPill status={execution.status} />}
        {execution && <ModeBadge mode={execution.mode} />}
        {!cancelled && execution?.status === "PAYER_ACTION_REQUIRED" && (
          <Button size="sm" className="gap-1.5" loading={capture.isPending}
            onClick={() => capture.mutate(execution.execution_id)}>
            <CreditCard className="h-3.5 w-3.5" /> Capture payment
          </Button>
        )}
      </CardContent>
    </Card>
  );
}

export default function PaymentsPage() {
  const [kind, setKind] = React.useState("all");
  const { data, isLoading, error, refetch } = usePayments(kind === "all" ? undefined : kind);
  const columns = React.useMemo<ColDef<Execution>[]>(() => [
    { field: "executed_at", headerName: "When", valueFormatter: (p) => formatDateTime(p.value as string), minWidth: 150 },
    { field: "kind", headerName: "Kind", valueFormatter: (p) => String(p.value ?? "").toLowerCase().replace(/_/g, " ") },
    { field: "method", headerName: "PayPal API", minWidth: 160 },
    { headerName: "Amount", valueGetter: (p) => toNumber(p.data?.amount), valueFormatter: (p) => formatMoney(p.value) },
    { field: "status", headerName: "Status", cellRenderer: (p: { value: string }) => <StatusPill status={p.value} /> },
    { field: "mode", headerName: "Mode", cellRenderer: (p: { value: string }) => <ModeBadge mode={p.value} /> },
    { headerName: "PayPal reference", valueGetter: (p) => p.data?.paypal_capture_id || p.data?.paypal_order_id || p.data?.paypal_payout_batch_id,
      cellClass: "font-mono text-2xs", minWidth: 210 },
    { field: "payee_email", headerName: "Payee" },
    { field: "idempotency_key", headerName: "Idempotency key", cellClass: "font-mono text-2xs", minWidth: 240 },
    { field: "debug_id", headerName: "Debug id", cellClass: "font-mono text-2xs", maxWidth: 140 },
  ], []);
  return (
    <div className="space-y-5">
      <PageHeader eyebrow="Finance" title="Payments"
        description="Each row is one PayPal money movement, executed once against one human approval. The idempotency key is what PayPal receives as PayPal-Request-Id / sender_batch_id." />
      <ReturnFromPayPal executions={data} />
      <div className="flex flex-wrap gap-1.5">
        {KINDS.map((k) => (
          <button key={k} type="button" onClick={() => setKind(k)} aria-pressed={kind === k}
            className={cn("rounded-lg border px-3 py-1 text-xs font-medium focus-ring",
              kind === k ? "border-primary bg-primary text-primary-foreground" : "border-border bg-card hover:bg-muted")}>
            {k === "all" ? "All" : k.toLowerCase().replace(/_/g, " ")}
          </button>
        ))}
      </div>
      {error && <ErrorState error={error} onRetry={() => void refetch()} />}
      <Card>
        <CardContent className="p-3">
          <DataGrid rows={data} columns={columns} loading={isLoading} getRowId={(r) => r.execution_id}
            emptyMessage="No payments yet - supplier payments and cashback payouts appear here once executed." />
        </CardContent>
      </Card>
    </div>
  );
}
