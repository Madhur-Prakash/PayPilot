"use client";

/** PayPal invoices: merchant -> customer invoices through PayPal Invoicing v2. */

import type { ColDef } from "ag-grid-community";
import { BellRing, ExternalLink, FilePlus2, RefreshCw, XCircle } from "lucide-react";
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
import { useCreatePayPalInvoice, usePayPalInvoiceAction, usePayPalInvoices } from "@/hooks/use-supply";
import { formatDate, formatMoney, toNumber } from "@/lib/utils";
import { useAuthStore } from "@/stores/auth";
import type { PayPalInvoiceRow } from "@/types/supply";

export default function PayPalInvoicesPage() {
  const { data, isLoading, error, refetch } = usePayPalInvoices();
  const action = usePayPalInvoiceAction();
  const canManage = useAuthStore((s) => s.can("paypal:manage"));
  const [open, setOpen] = React.useState(false);
  const columns = React.useMemo<ColDef<PayPalInvoiceRow>[]>(() => [
    { field: "invoice_number", headerName: "Number", cellClass: "font-mono", maxWidth: 140 },
    { field: "recipient_name", headerName: "Customer" },
    { field: "recipient_email", headerName: "Email" },
    { headerName: "Amount", valueGetter: (p) => toNumber(p.data?.amount), valueFormatter: (p) => formatMoney(p.value), maxWidth: 130 },
    { field: "status", headerName: "Status", cellRenderer: (p: { value: string }) => <StatusPill status={p.value} />, maxWidth: 130 },
    { field: "due_date", headerName: "Due", valueFormatter: (p) => formatDate(p.value as string), maxWidth: 130 },
    { field: "mode", headerName: "Mode", cellRenderer: (p: { value: string }) => <ModeBadge mode={p.value} />, maxWidth: 150 },
    {
      headerName: "Actions", minWidth: 220, sortable: false, filter: false,
      cellRenderer: (p: { data?: PayPalInvoiceRow }) => {
        const row = p.data;
        if (!row) return null;
        return (
          <div className="flex items-center gap-2 text-2xs">
            {row.payer_view_url && !row.payer_view_url.startsWith("simulated") && (
              <a href={row.payer_view_url} target="_blank" rel="noreferrer" className="inline-flex items-center gap-0.5 text-primary hover:underline">
                view <ExternalLink className="h-3 w-3" />
              </a>
            )}
            {canManage && ["SENT", "UNPAID", "PARTIALLY_PAID"].includes(row.status) && (
              <button type="button" className="inline-flex items-center gap-0.5 text-primary hover:underline"
                onClick={() => action.mutate({ id: row.invoice_record_id, action: "remind" })}><BellRing className="h-3 w-3" />remind</button>
            )}
            {canManage && !["PAID", "CANCELLED"].includes(row.status) && (
              <button type="button" className="inline-flex items-center gap-0.5 text-destructive hover:underline"
                onClick={() => action.mutate({ id: row.invoice_record_id, action: "cancel" })}><XCircle className="h-3 w-3" />cancel</button>
            )}
            <button type="button" className="inline-flex items-center gap-0.5 text-muted-foreground hover:underline"
              onClick={() => action.mutate({ id: row.invoice_record_id, action: "refresh" })}><RefreshCw className="h-3 w-3" />refresh</button>
          </div>
        );
      },
    },
  ], [action, canManage]);
  return (
    <div className="space-y-5">
      <PageHeader eyebrow="Finance" title="PayPal invoices"
        description="Invoices the merchant sends to customers - e.g. a win-back offer or a wholesale order - through PayPal Invoicing v2, with reminders and cancellation."
        actions={canManage && <Button size="sm" className="gap-1.5" onClick={() => setOpen(true)}><FilePlus2 className="h-3.5 w-3.5" /> New invoice</Button>} />
      {error && <ErrorState error={error} onRetry={() => void refetch()} />}
      <Card>
        <CardContent className="p-3">
          <DataGrid rows={data} columns={columns} loading={isLoading} getRowId={(r) => r.invoice_record_id}
            emptyMessage="No invoices sent yet." />
        </CardContent>
      </Card>
      <InvoiceDialog open={open} onClose={() => setOpen(false)} />
    </div>
  );
}

function InvoiceDialog({ open, onClose }: { open: boolean; onClose: () => void }) {
  const create = useCreatePayPalInvoice();
  const [email, setEmail] = React.useState("");
  const [name, setName] = React.useState("");
  const [item, setItem] = React.useState("Premium Coffee Beans (12 oz) - wholesale");
  const [qty, setQty] = React.useState("10");
  const [price, setPrice] = React.useState("15.00");
  const [note, setNote] = React.useState("Thank you for your order!");
  const total = (Number(qty) || 0) * (Number(price) || 0);
  return (
    <Dialog open={open} onOpenChange={(next) => !next && onClose()}>
      <DialogContent className="max-w-lg">
        <DialogHeader>
          <DialogTitle>New PayPal invoice</DialogTitle>
          <DialogDescription>Created and sent through PayPal Invoicing v2 (or the simulator, labelled, without credentials).</DialogDescription>
        </DialogHeader>
        <div className="grid grid-cols-2 gap-3">
          <div className="space-y-1"><Label htmlFor="inv-email">Customer email</Label><Input id="inv-email" value={email} onChange={(e) => setEmail(e.target.value)} /></div>
          <div className="space-y-1"><Label htmlFor="inv-name">Customer name</Label><Input id="inv-name" value={name} onChange={(e) => setName(e.target.value)} /></div>
          <div className="col-span-2 space-y-1"><Label htmlFor="inv-item">Item</Label><Input id="inv-item" value={item} onChange={(e) => setItem(e.target.value)} /></div>
          <div className="space-y-1"><Label htmlFor="inv-qty">Quantity</Label><Input id="inv-qty" type="number" value={qty} onChange={(e) => setQty(e.target.value)} /></div>
          <div className="space-y-1"><Label htmlFor="inv-price">Unit price ($)</Label><Input id="inv-price" type="number" value={price} onChange={(e) => setPrice(e.target.value)} /></div>
          <div className="col-span-2 space-y-1"><Label htmlFor="inv-note">Note</Label><Textarea id="inv-note" rows={2} value={note} onChange={(e) => setNote(e.target.value)} /></div>
        </div>
        <DialogFooter>
          <span className="mr-auto text-sm font-semibold tabular-nums">{formatMoney(total)}</span>
          <Button variant="ghost" onClick={onClose}>Cancel</Button>
          <Button disabled={!email.includes("@") || total <= 0} loading={create.isPending}
            onClick={() => create.mutate({ recipient_email: email, recipient_name: name,
              items: [{ name: item, quantity: Number(qty), unit_amount: Number(price) }], note, send: true }, { onSuccess: onClose })}>
            Create & send
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
