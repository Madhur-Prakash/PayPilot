"use client";

/**
 * Payouts: cashback rewards via PayPal Payouts.
 *
 * Payouts are used for rewards only - never to settle supplier invoices. Every
 * batch is an approval request first; nothing is sent until a person with
 * payment:approve approves it and someone with payment:execute sends it.
 */

import type { ColDef } from "ag-grid-community";
import { Gift, Plus, RefreshCw, Trash2 } from "lucide-react";
import * as React from "react";

import { ErrorState } from "@/components/common/states";
import { DataGrid } from "@/components/data/data-grid";
import { ModeBadge, PageHeader, StatusPill } from "@/components/supply/shared";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/overlays";
import { Card, CardContent, Input, Label, Textarea } from "@/components/ui/primitives";
import { usePayPalPayouts, useRequestCashback } from "@/hooks/use-supply";
import { paypalApi } from "@/lib/api/supply";
import { formatDateTime, formatMoney, toNumber } from "@/lib/utils";
import { useAuthStore } from "@/stores/auth";
import type { Execution } from "@/types/supply";

export default function PayoutsPage() {
  const { data, isLoading, error, refetch } = usePayPalPayouts();
  const canRequest = useAuthStore((s) => s.can("paypal:manage"));
  const [open, setOpen] = React.useState(false);
  const columns = React.useMemo<ColDef<Execution>[]>(() => [
    { field: "executed_at", headerName: "When", valueFormatter: (p) => formatDateTime(p.value as string) },
    { field: "paypal_payout_batch_id", headerName: "Batch", cellClass: "font-mono text-2xs", minWidth: 220 },
    { headerName: "Total", valueGetter: (p) => toNumber(p.data?.amount), valueFormatter: (p) => formatMoney(p.value) },
    { field: "status", headerName: "Status", cellRenderer: (p: { value: string }) => <StatusPill status={p.value} /> },
    { field: "mode", headerName: "Mode", cellRenderer: (p: { value: string }) => <ModeBadge mode={p.value} /> },
    { field: "idempotency_key", headerName: "sender_batch_id basis", cellClass: "font-mono text-2xs", minWidth: 220 },
    {
      headerName: "", maxWidth: 110, sortable: false, filter: false,
      cellRenderer: (p: { data?: Execution }) =>
        p.data && p.data.status !== "COMPLETED" ? (
          <button type="button" className="inline-flex items-center gap-1 text-2xs text-primary hover:underline"
            onClick={() => void paypalApi.refreshPayout(p.data!.execution_id).then(() => refetch())}>
            <RefreshCw className="h-3 w-3" /> refresh
          </button>
        ) : null,
    },
  ], [refetch]);
  return (
    <div className="space-y-5">
      <PageHeader eyebrow="Finance" title="Cashback payouts"
        description="Rewards for returning customers, sent through PayPal Payouts after a human approves the batch. Supplier invoices are paid through Orders v2, never through Payouts."
        actions={canRequest && <Button size="sm" className="gap-1.5" onClick={() => setOpen(true)}><Gift className="h-3.5 w-3.5" /> Request cashback batch</Button>} />
      {error && <ErrorState error={error} onRetry={() => void refetch()} />}
      <Card>
        <CardContent className="p-3">
          <DataGrid rows={data} columns={columns} loading={isLoading} getRowId={(r) => r.execution_id}
            emptyMessage="No payouts sent. Request a batch, approve it in the Approval Center, then send it." />
        </CardContent>
      </Card>
      <CashbackDialog open={open} onClose={() => setOpen(false)} />
    </div>
  );
}

function CashbackDialog({ open, onClose }: { open: boolean; onClose: () => void }) {
  const request = useRequestCashback();
  const [rows, setRows] = React.useState([{ email: "", amount: "5" }]);
  const [note, setNote] = React.useState("Thanks for coming back to Juniper & Oak!");
  React.useEffect(() => {
    if (open) setRows([{ email: "", amount: "5" }]);
  }, [open]);
  const valid = rows.filter((r) => r.email.includes("@") && Number(r.amount) > 0 && Number(r.amount) <= 100);
  const total = valid.reduce((s, r) => s + Number(r.amount), 0);
  return (
    <Dialog open={open} onOpenChange={(next) => !next && onClose()}>
      <DialogContent className="max-w-lg">
        <DialogHeader>
          <DialogTitle>Request a cashback batch</DialogTitle>
          <DialogDescription>Creates an approval request. Nothing is sent until it is approved and executed. Max $100 per reward.</DialogDescription>
        </DialogHeader>
        <div className="space-y-2">
          {rows.map((r, i) => (
            <div key={i} className="flex items-center gap-2">
              <Input placeholder="customer@example.com" value={r.email}
                onChange={(e) => setRows((all) => all.map((x, j) => (j === i ? { ...x, email: e.target.value } : x)))} />
              <Input type="number" className="w-24" value={r.amount}
                onChange={(e) => setRows((all) => all.map((x, j) => (j === i ? { ...x, amount: e.target.value } : x)))} />
              <Button variant="ghost" size="icon" aria-label="Remove" onClick={() => setRows((all) => all.filter((_, j) => j !== i))}>
                <Trash2 className="h-4 w-4" />
              </Button>
            </div>
          ))}
          <Button variant="outline" size="sm" className="gap-1.5" onClick={() => setRows((all) => [...all, { email: "", amount: "5" }])}>
            <Plus className="h-3.5 w-3.5" /> Add recipient
          </Button>
        </div>
        <div className="space-y-1.5">
          <Label htmlFor="cb-note">Message</Label>
          <Textarea id="cb-note" rows={2} value={note} onChange={(e) => setNote(e.target.value)} />
        </div>
        <DialogFooter>
          <span className="mr-auto text-sm font-semibold tabular-nums">{formatMoney(total)}</span>
          <Button variant="ghost" onClick={onClose}>Cancel</Button>
          <Button disabled={valid.length === 0} loading={request.isPending}
            onClick={() => request.mutate({ recipients: valid.map((r) => ({ email: r.email, amount: Number(r.amount) })), note },
              { onSuccess: onClose })}>
            Request approval
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
