"use client";

/** Supplier invoices: three-way match status, payment approval and PayPal settlement. */

import type { ColDef } from "ag-grid-community";
import { useRouter } from "next/navigation";
import * as React from "react";

import { ErrorState } from "@/components/common/states";
import { DataGrid } from "@/components/data/data-grid";
import { ModeBadge, PageHeader, StatusPill } from "@/components/supply/shared";
import { Card, CardContent } from "@/components/ui/primitives";
import { useSupplierInvoices } from "@/hooks/use-supply";
import { cn, formatDate, formatMoney, toNumber } from "@/lib/utils";
import type { SupplierInvoice } from "@/types/supply";

const FILTERS = ["all", "DISCREPANCY", "PAYMENT_APPROVAL_PENDING", "PAYMENT_PENDING", "PAID"];

export default function SupplierInvoicesPage() {
  const router = useRouter();
  const [filter, setFilter] = React.useState("all");
  const { data, isLoading, error, refetch } = useSupplierInvoices(filter === "all" ? undefined : filter);
  const columns = React.useMemo<ColDef<SupplierInvoice>[]>(() => [
    { field: "invoice_number", headerName: "Invoice", cellClass: "font-mono", minWidth: 160 },
    { field: "supplier_name", headerName: "Supplier", minWidth: 180 },
    { field: "purchase_order_reference", headerName: "PO", maxWidth: 120, cellClass: "font-mono" },
    { headerName: "Total", valueGetter: (p) => toNumber(p.data?.total), valueFormatter: (p) => formatMoney(p.value) },
    { headerName: "Status", field: "status", cellRenderer: (p: { value: string }) => <StatusPill status={p.value} /> },
    { headerName: "Match", valueGetter: (p) => p.data?.match?.status ?? "", cellRenderer: (p: { value: string }) => <StatusPill status={p.value} /> },
    { headerName: "Discrepancy", valueGetter: (p) => p.data?.match?.discrepancies[0]?.message ?? "", minWidth: 220 },
    { headerName: "Payment", valueGetter: (p) => p.data?.execution?.mode ?? "",
      cellRenderer: (p: { value: string }) => (p.value ? <ModeBadge mode={p.value} /> : null) },
    { headerName: "Capture", valueGetter: (p) => p.data?.execution?.paypal_capture_id ?? "", cellClass: "font-mono text-2xs" },
    { headerName: "Due", field: "due_date", valueFormatter: (p) => formatDate(p.value as string), maxWidth: 130 },
  ], []);
  return (
    <div className="space-y-5">
      <PageHeader eyebrow="Supply" title="Supplier invoices"
        description="An invoice is payable only when the purchase order, the goods received and the invoice agree. Payment needs its own human approval." />
      <div className="flex flex-wrap gap-1.5">
        {FILTERS.map((f) => (
          <button key={f} type="button" onClick={() => setFilter(f)} aria-pressed={filter === f}
            className={cn("rounded-lg border px-3 py-1 text-xs font-medium focus-ring",
              filter === f ? "border-primary bg-primary text-primary-foreground" : "border-border bg-card hover:bg-muted")}>
            {f === "all" ? "All" : f.toLowerCase().replace(/_/g, " ")}
          </button>
        ))}
      </div>
      {error && <ErrorState error={error} onRetry={() => void refetch()} />}
      <Card>
        <CardContent className="p-3">
          <DataGrid rows={data} columns={columns} loading={isLoading} getRowId={(r) => r.supplier_invoice_id}
            onRowClick={(r) => r.procurement_request_id && router.push(`/supply/negotiations/${r.procurement_request_id}`)}
            emptyMessage="No supplier invoices yet." />
        </CardContent>
      </Card>
    </div>
  );
}
