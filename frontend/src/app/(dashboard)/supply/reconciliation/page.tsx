"use client";

/** Reconciliation: closed procurements, and the inventory/margin change each one fed back to Growth. */

import type { ColDef } from "ag-grid-community";
import { TrendingUp } from "lucide-react";
import * as React from "react";

import { ErrorState } from "@/components/common/states";
import { DataGrid } from "@/components/data/data-grid";
import { MetricTile, PageHeader, StatusPill } from "@/components/supply/shared";
import { Card, CardContent } from "@/components/ui/primitives";
import { useReconciliations } from "@/hooks/use-supply";
import { formatDateTime, formatMoney, toNumber } from "@/lib/utils";
import type { Reconciliation } from "@/types/supply";
import { CheckCircle2, Scale } from "lucide-react";

export default function ReconciliationPage() {
  const { data, isLoading, error, refetch } = useReconciliations();
  const rows = data ?? [];
  const reconciled = rows.filter((r) => r.status === "RECONCILED").length;
  const latest = rows[0];
  const columns = React.useMemo<ColDef<Reconciliation>[]>(() => [
    { field: "purchase_order_reference", headerName: "PO", maxWidth: 120, cellClass: "font-mono" },
    { field: "status", headerName: "Status", cellRenderer: (p: { value: string }) => <StatusPill status={p.value} />, maxWidth: 140 },
    { headerName: "Invoice", valueGetter: (p) => toNumber(p.data?.invoice_total), valueFormatter: (p) => formatMoney(p.value) },
    { headerName: "Paid", valueGetter: (p) => toNumber(p.data?.paid_amount), valueFormatter: (p) => formatMoney(p.value) },
    { headerName: "Variance", valueGetter: (p) => toNumber(p.data?.variance_amount), valueFormatter: (p) => formatMoney(p.value), maxWidth: 120 },
    { field: "payment_reference", headerName: "PayPal reference", cellClass: "font-mono text-2xs", minWidth: 200 },
    { headerName: "Unit cost", valueGetter: (p) => `${formatMoney(p.data?.previous_unit_cost)} → ${formatMoney(p.data?.new_unit_cost)}`, minWidth: 160 },
    { headerName: "Margin", valueGetter: (p) => `${p.data?.previous_margin_pct ?? "--"}% → ${p.data?.new_margin_pct ?? "--"}%`, cellClass: "text-success font-medium" },
    { headerName: "When", field: "reconciled_at", valueFormatter: (p) => formatDateTime(p.value as string) },
  ], []);
  return (
    <div className="space-y-5">
      <PageHeader eyebrow="Supply · Finance" title="Reconciliation"
        description="Order, receipt, invoice and PayPal capture must agree to the cent. Each reconciliation revalues inventory and hands the new product margin to Growth Intelligence." />
      <div className="grid gap-3 sm:grid-cols-3">
        <MetricTile icon={CheckCircle2} tone="success" label="Reconciled" value={reconciled} />
        <MetricTile icon={Scale} label="Total paid" value={formatMoney(rows.reduce((s, r) => s + (toNumber(r.paid_amount) ?? 0), 0))} />
        <MetricTile icon={TrendingUp} tone="primary" label="Latest margin change"
          value={latest ? `${latest.previous_margin_pct}% → ${latest.new_margin_pct}%` : "--"} />
      </div>
      {error && <ErrorState error={error} onRetry={() => void refetch()} />}
      <Card>
        <CardContent className="p-3">
          <DataGrid rows={data} columns={columns} loading={isLoading} getRowId={(r) => r.reconciliation_id}
            emptyMessage="Nothing reconciled yet - it happens automatically once goods, invoice and payment agree." />
        </CardContent>
      </Card>
    </div>
  );
}
