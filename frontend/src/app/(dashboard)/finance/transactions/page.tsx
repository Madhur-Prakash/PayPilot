"use client";

/** PayPal transactions: incremental Transaction Search sync and deterministic transaction intelligence. */

import type { ColDef } from "ag-grid-community";
import { ArrowDownLeft, BadgeDollarSign, Percent, RefreshCw, Repeat, Undo2 } from "lucide-react";
import * as React from "react";
import { Area, AreaChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";

import { ErrorState } from "@/components/common/states";
import { DataGrid } from "@/components/data/data-grid";
import { MetricTile, ModeBadge, PageHeader, StatusPill } from "@/components/supply/shared";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle, Input } from "@/components/ui/primitives";
import { usePayPalIntelligence, usePayPalStatus, usePayPalSync, usePayPalTransactions } from "@/hooks/use-supply";
import { cn, formatCompactCurrency, formatDateTime, formatMoney, formatRelativeTime, toNumber } from "@/lib/utils";
import { useAuthStore } from "@/stores/auth";
import type { PayPalTransactionRow } from "@/types/supply";

const CATEGORIES = ["all", "PAYMENT", "REFUND", "FEE", "PAYOUT"];

export default function PayPalTransactionsPage() {
  const [category, setCategory] = React.useState("all");
  const [search, setSearch] = React.useState("");
  const status = usePayPalStatus();
  const intel = usePayPalIntelligence(30);
  const txns = usePayPalTransactions({ page: 1, page_size: 500, category: category === "all" ? undefined : category });
  const sync = usePayPalSync();
  const canSync = useAuthStore((s) => s.can("paypal:sync"));
  const usd = intel.data?.currencies.USD ?? Object.values(intel.data?.currencies ?? {})[0];

  const columns = React.useMemo<ColDef<PayPalTransactionRow>[]>(() => [
    { field: "initiated_at", headerName: "When", valueFormatter: (p) => formatDateTime(p.value as string), minWidth: 150 },
    { field: "paypal_transaction_id", headerName: "Transaction", cellClass: "font-mono text-2xs", minWidth: 200 },
    { field: "category", headerName: "Type", maxWidth: 110 },
    { field: "event_code", headerName: "Code", maxWidth: 90 },
    { headerName: "Gross", valueGetter: (p) => toNumber(p.data?.gross_amount), valueFormatter: (p) => formatMoney(p.value),
      cellClass: (p) => ((p.value ?? 0) < 0 ? "text-destructive" : "") },
    { headerName: "Fee", valueGetter: (p) => toNumber(p.data?.fee_amount), valueFormatter: (p) => formatMoney(p.value), maxWidth: 110 },
    { headerName: "Net", valueGetter: (p) => toNumber(p.data?.net_amount), valueFormatter: (p) => formatMoney(p.value) },
    { field: "currency", headerName: "Ccy", maxWidth: 80 },
    { field: "payer_name", headerName: "Payer" },
    { field: "status_code", headerName: "Status", maxWidth: 90 },
    { field: "mode", headerName: "Source", cellRenderer: (p: { value: string }) => <ModeBadge mode={p.value} />, maxWidth: 140 },
  ], []);

  return (
    <div className="space-y-5">
      <PageHeader eyebrow="Finance" title="PayPal transactions"
        description="Pulled from the PayPal Transaction Search API in <=31-day windows, resumed from a checkpoint, de-duplicated by transaction id. Analytics are computed from these rows, per currency."
        actions={
          <>
            {status.data && <ModeBadge mode={status.data.mode} />}
            <Button size="sm" className="gap-1.5" disabled={!canSync} loading={sync.isPending} onClick={() => sync.mutate(undefined)}>
              <RefreshCw className="h-3.5 w-3.5" /> Sync now
            </Button>
          </>
        } />

      {status.data && (
        <Card>
          <CardContent className="flex flex-wrap items-center gap-x-6 gap-y-2 p-4 text-xs">
            <span>{status.data.note}</span>
            {status.data.sync && (
              <>
                <span className="text-muted-foreground">last sync {formatRelativeTime(status.data.sync.last_run_at)}</span>
                <StatusPill status={status.data.sync.last_status === "OK" ? "SUCCESS" : status.data.sync.last_status} />
                <span className="text-muted-foreground">{status.data.sync.items_total} transactions stored</span>
                {status.data.sync.last_error && <span className="text-destructive">{status.data.sync.last_error}</span>}
              </>
            )}
          </CardContent>
        </Card>
      )}

      {usd && (
        <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-5">
          <MetricTile icon={BadgeDollarSign} tone="primary" label="Gross (30d)" value={formatCompactCurrency(usd.gross_revenue)}
            hint={usd.gross_change_pct ? `${usd.gross_change_pct}% vs prior 30 days` : undefined} />
          <MetricTile icon={ArrowDownLeft} tone="success" label="Net after fees & refunds" value={formatCompactCurrency(usd.net_revenue)}
            hint={`fees ${formatMoney(usd.fees)}`} />
          <MetricTile icon={Undo2} tone="warning" label="Refund rate" value={`${usd.refund_rate_pct}%`} hint={`${usd.refund_count} refunds · ${formatMoney(usd.refunded)}`} />
          <MetricTile icon={Repeat} label="Repeat payers" value={`${usd.repeat_payer_rate_pct}%`} hint={`${usd.repeat_payers} of ${usd.unique_payers} payers`} />
          <MetricTile icon={Percent} label="Avg order value" value={formatMoney(usd.average_order_value)} hint={`failure rate ${usd.payment_failure_rate_pct}%`} />
        </div>
      )}

      {usd && usd.daily.length > 1 && (
        <Card>
          <CardHeader className="pb-1">
            <CardTitle className="text-base">Daily gross</CardTitle>
            <CardDescription>{intel.data?.is_simulated ? "Simulated Transaction Search data - labelled as such." : "From PayPal Transaction Search."}</CardDescription>
          </CardHeader>
          <CardContent className="h-56 p-2">
            <ResponsiveContainer width="100%" height="100%">
              <AreaChart data={usd.daily.map((d) => ({ date: d.date.slice(5), gross: toNumber(d.gross) ?? 0 }))}>
                <defs>
                  <linearGradient id="ppGross" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="0%" stopColor="hsl(var(--primary))" stopOpacity={0.35} />
                    <stop offset="100%" stopColor="hsl(var(--primary))" stopOpacity={0} />
                  </linearGradient>
                </defs>
                <XAxis dataKey="date" tick={{ fontSize: 10 }} tickLine={false} axisLine={false} interval={4} />
                <YAxis tick={{ fontSize: 10 }} tickLine={false} axisLine={false} width={48} tickFormatter={(v: number) => `$${v}`} />
                <Tooltip formatter={(v: number) => formatMoney(v)} />
                <Area type="monotone" dataKey="gross" stroke="hsl(var(--primary))" fill="url(#ppGross)" strokeWidth={2} />
              </AreaChart>
            </ResponsiveContainer>
          </CardContent>
        </Card>
      )}

      <div className="flex flex-wrap items-center gap-1.5">
        {CATEGORIES.map((c) => (
          <button key={c} type="button" onClick={() => setCategory(c)} aria-pressed={category === c}
            className={cn("rounded-lg border px-3 py-1 text-xs font-medium focus-ring",
              category === c ? "border-primary bg-primary text-primary-foreground" : "border-border bg-card hover:bg-muted")}>
            {c === "all" ? "All" : c.toLowerCase()}
          </button>
        ))}
        <Input placeholder="Search…" value={search} onChange={(e) => setSearch(e.target.value)} className="ml-auto w-56" />
      </div>
      {txns.error && <ErrorState error={txns.error} onRetry={() => void txns.refetch()} />}
      <Card>
        <CardContent className="p-3">
          <DataGrid rows={txns.data?.items} columns={columns} loading={txns.isLoading} quickFilter={search}
            getRowId={(r) => r.id} pagination pageSize={50}
            emptyMessage="No transactions synced yet - press Sync now." />
        </CardContent>
      </Card>
    </div>
  );
}
