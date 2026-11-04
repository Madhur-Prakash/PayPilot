"use client";

/** Payments: every PayPal money movement, the approval that authorised it, and its idempotency key. */

import type { ColDef } from "ag-grid-community";
import * as React from "react";

import { ErrorState } from "@/components/common/states";
import { DataGrid } from "@/components/data/data-grid";
import { ModeBadge, PageHeader, StatusPill } from "@/components/supply/shared";
import { Card, CardContent } from "@/components/ui/primitives";
import { usePayments } from "@/hooks/use-supply";
import { cn, formatDateTime, formatMoney, toNumber } from "@/lib/utils";
import type { Execution } from "@/types/supply";

const KINDS = ["all", "SUPPLIER_SETTLEMENT", "CASHBACK_PAYOUT"];

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
