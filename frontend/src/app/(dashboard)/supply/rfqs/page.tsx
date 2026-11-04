"use client";

/** RFQ management: every request for quotation, its policy and its outcome, in one grid. */

import type { ColDef } from "ag-grid-community";
import { useRouter } from "next/navigation";
import * as React from "react";

import { ErrorState } from "@/components/common/states";
import { DataGrid } from "@/components/data/data-grid";
import { PageHeader, StatusPill } from "@/components/supply/shared";
import { Card, CardContent, Input } from "@/components/ui/primitives";
import { useProcurements } from "@/hooks/use-supply";
import { formatDate, formatMoney, toNumber } from "@/lib/utils";
import type { ProcurementRequest } from "@/types/supply";

export default function RfqManagementPage() {
  const router = useRouter();
  const [search, setSearch] = React.useState("");
  const { data, isLoading, error, refetch } = useProcurements({ page: 1, page_size: 100 });

  const columns = React.useMemo<ColDef<ProcurementRequest>[]>(() => [
    { field: "rfq_reference", headerName: "RFQ", maxWidth: 120, cellClass: "font-mono" },
    { field: "reference", headerName: "Request", maxWidth: 120, cellClass: "font-mono" },
    { field: "product_name", headerName: "Product", minWidth: 200 },
    { headerName: "Qty", valueGetter: (p) => toNumber(p.data?.quantity), maxWidth: 90 },
    { field: "trigger", headerName: "Trigger", valueFormatter: (p) => String(p.value ?? "").toLowerCase().replace(/_/g, " ") },
    { headerName: "Status", field: "status", cellRenderer: (p: { value: string }) => <StatusPill status={p.value} /> },
    { headerName: "Budget", valueGetter: (p) => toNumber(p.data?.policy.max_budget), valueFormatter: (p) => formatMoney(p.value) },
    { headerName: "Max / unit", valueGetter: (p) => toNumber(p.data?.policy.max_unit_cost), valueFormatter: (p) => formatMoney(p.value) },
    { headerName: "Suppliers", field: "session_count", maxWidth: 110 },
    { headerName: "Recommended", valueGetter: (p) => p.data?.recommendation?.winner?.supplier_name ?? "", minWidth: 180 },
    { headerName: "Landed", valueGetter: (p) => toNumber(p.data?.final_landed_total), valueFormatter: (p) => formatMoney(p.value) },
    { headerName: "Savings", valueGetter: (p) => toNumber(p.data?.savings_amount), valueFormatter: (p) => formatMoney(p.value),
      cellClass: "text-success font-medium" },
    { headerName: "Needed by", field: "required_by", valueFormatter: (p) => formatDate(p.value as string | null) },
  ], []);

  return (
    <div className="space-y-5">
      <PageHeader eyebrow="Supply" title="RFQ management"
        description="RFQs carry the product, quantity and date - never the merchant's budget or ceiling, which stay with the Buyer Agent."
        actions={<Input placeholder="Filter…" value={search} onChange={(e) => setSearch(e.target.value)} className="w-56" />} />
      {error && <ErrorState error={error} onRetry={() => void refetch()} />}
      <Card>
        <CardContent className="p-3">
          <DataGrid rows={data?.items} columns={columns} loading={isLoading} quickFilter={search}
            getRowId={(r) => r.procurement_request_id}
            onRowClick={(r) => router.push(`/supply/negotiations/${r.procurement_request_id}`)}
            emptyMessage="No RFQs yet." />
        </CardContent>
      </Card>
    </div>
  );
}
