"use client";

/** Goods receiving: deliveries in flight, and every receipt booked against them. */

import type { ColDef } from "ag-grid-community";
import { PackageCheck, Truck } from "lucide-react";
import Link from "next/link";
import * as React from "react";

import { ErrorState } from "@/components/common/states";
import { DataGrid } from "@/components/data/data-grid";
import { PageHeader, StatusPill } from "@/components/supply/shared";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/primitives";
import { useGoodsReceipts, useSupplyOverview } from "@/hooks/use-supply";
import { formatDate, formatDateTime, formatMoney, toNumber } from "@/lib/utils";
import type { GoodsReceipt } from "@/types/supply";

export default function GoodsReceivingPage() {
  const receipts = useGoodsReceipts();
  const overview = useSupplyOverview();
  const columns = React.useMemo<ColDef<GoodsReceipt>[]>(() => [
    { field: "reference", headerName: "Receipt", maxWidth: 130, cellClass: "font-mono" },
    { field: "purchase_order_reference", headerName: "Purchase order", maxWidth: 150, cellClass: "font-mono" },
    { headerName: "Received", field: "received_at", valueFormatter: (p) => formatDateTime(p.value as string) },
    { headerName: "Quantity", valueGetter: (p) => toNumber(p.data?.total_quantity), maxWidth: 120 },
    { headerName: "Value", valueGetter: (p) => toNumber(p.data?.received_value), valueFormatter: (p) => formatMoney(p.value) },
    { headerName: "Delivery", valueGetter: (p) => (p.data?.is_partial ? "Partial" : "Complete"),
      cellRenderer: (p: { value: string }) => <StatusPill status={p.value === "Partial" ? "PARTIALLY_RECEIVED" : "RECEIVED"} /> },
    { headerName: "On time", valueGetter: (p) => (p.data?.on_time == null ? "--" : p.data.on_time ? "Yes" : "Late"), maxWidth: 110 },
    { field: "notes", headerName: "Notes" },
  ], []);
  return (
    <div className="space-y-5">
      <PageHeader eyebrow="Supply" title="Goods receiving"
        description="Partial deliveries are normal. Every receipt writes stock, updates the order and re-runs the three-way match against the supplier's invoice." />
      <Card>
        <CardHeader className="pb-2">
          <CardTitle className="flex items-center gap-2 text-base"><Truck className="h-4 w-4 text-primary" /> Awaiting delivery</CardTitle>
          <CardDescription>Receive from the procurement workspace, where the invoice match is shown alongside.</CardDescription>
        </CardHeader>
        <CardContent className="grid gap-2 sm:grid-cols-2 lg:grid-cols-3">
          {(overview.data?.procurement.upcoming_deliveries ?? []).length === 0 && <p className="text-sm text-muted-foreground">Nothing in transit.</p>}
          {(overview.data?.procurement.upcoming_deliveries ?? []).map((o) => (
            <Link key={o.purchase_order_id} href={`/purchase-orders`} className="rounded-xl border border-border p-3 text-xs hover:bg-muted/50">
              <div className="flex items-center justify-between"><span className="font-mono font-semibold">{o.reference}</span><StatusPill status={o.status} /></div>
              <p className="mt-0.5 text-muted-foreground tabular-nums">{formatMoney(o.total_value)} · expected {formatDate(o.expected_at)}</p>
            </Link>
          ))}
        </CardContent>
      </Card>
      {receipts.error && <ErrorState error={receipts.error} onRetry={() => void receipts.refetch()} />}
      <Card>
        <CardHeader className="pb-2"><CardTitle className="flex items-center gap-2 text-base"><PackageCheck className="h-4 w-4 text-success" /> Receipts</CardTitle></CardHeader>
        <CardContent className="p-3">
          <DataGrid rows={receipts.data} columns={columns} loading={receipts.isLoading} getRowId={(r) => r.goods_receipt_id}
            emptyMessage="No goods received yet." pagination />
        </CardContent>
      </Card>
    </div>
  );
}
