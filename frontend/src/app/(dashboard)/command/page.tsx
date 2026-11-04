"use client";

/**
 * Command Center - the merchant's whole operating picture in one place.
 *
 * Growth (revenue, profit, opportunities), Supply (stock risk, negotiations,
 * savings), Finance (PayPal activity) and Governance (approvals) - connected by
 * one event stream, so a cheaper negotiated purchase visibly becomes a better
 * product margin.
 */

import {
  ArrowRight,
  Bot,
  Boxes,
  CircleDollarSign,
  ClipboardCheck,
  Handshake,
  LineChart,
  PiggyBank,
  Sparkles,
  Target,
  TrendingUp,
  Wallet,
} from "lucide-react";
import Link from "next/link";

import { ErrorState, LoadingKpis, LoadingRows } from "@/components/common/states";
import { LifecycleStepper, MetricTile, ModeBadge, PageHeader, StatusPill } from "@/components/supply/shared";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/primitives";
import { useCommandCenter } from "@/hooks/use-supply";
import { cn, formatCompactCurrency, formatMoney, formatRelativeTime, toNumber } from "@/lib/utils";

const MODULE_TONE: Record<string, string> = {
  growth: "bg-primary/10 text-primary",
  supply: "bg-warning/14 text-warning",
  finance: "bg-success/12 text-success",
  governance: "bg-secondary text-secondary-foreground",
};

export default function CommandCenterPage() {
  const { data, isLoading, error, refetch } = useCommandCenter(30);

  return (
    <div className="space-y-6">
      <PageHeader
        eyebrow="Command"
        title="Command Center"
        description="One operating picture: what the business earned, what the agents are doing about it, and what is waiting for you."
        actions={data && <ModeBadge mode={data.paypal.mode} />}
      />
      {error && <ErrorState error={error} onRetry={() => void refetch()} />}
      {isLoading && <LoadingKpis count={8} />}
      {data && (
        <>
          <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
            <MetricTile icon={CircleDollarSign} tone="primary" label="Revenue (30d)" value={formatCompactCurrency(data.financials.revenue)}
              hint={kpiHint(data.kpis.find((k) => k.key === "revenue")?.change_pct)} />
            <MetricTile icon={Wallet} label="Net sales" value={formatCompactCurrency(data.financials.net_sales)}
              hint={`${data.financials.orders.toLocaleString("en-US")} orders`} />
            <MetricTile icon={TrendingUp} tone="success" label="Gross profit" value={formatCompactCurrency(data.financials.gross_profit)}
              hint={`${data.financials.gross_margin_pct}% gross margin`} />
            <MetricTile icon={Target} tone="primary" label="Growth opportunities" value={data.growth.open_opportunities}
              hint={`${formatMoney(data.growth.opportunity_value)}/month identified`} />
            <MetricTile icon={Boxes} tone={data.inventory.at_risk.length ? "destructive" : "success"} label="Inventory health"
              value={data.inventory.at_risk.length ? `${data.inventory.at_risk.length} at risk` : "Healthy"}
              hint={`${formatCompactCurrency(data.inventory.stock_value)} stock value`} />
            <MetricTile icon={PiggyBank} tone="success" label="Procurement savings" value={formatMoney(data.procurement.savings)}
              hint={`${formatMoney(data.procurement.spend)} procurement spend`} />
            <MetricTile icon={Handshake} tone="primary" label="Active negotiations" value={data.procurement.active_negotiations}
              hint={`${data.procurement.active_requests.length} open procurement request(s)`} />
            <MetricTile icon={ClipboardCheck} tone={data.approvals.pending ? "warning" : "default"} label="Pending approvals"
              value={data.approvals.pending} hint="Money moves only after a human says yes" />
          </div>

          {/* The connected story: demand -> stock -> negotiation -> PayPal -> margin */}
          <Card className="overflow-hidden">
            <CardHeader className="flex-row items-start justify-between gap-3 pb-3">
              <div>
                <CardTitle className="flex items-center gap-2 text-base"><Sparkles className="h-4 w-4 text-primary" /> Growth ↔ Supply, connected</CardTitle>
                <CardDescription>Rising demand creates a stockout risk; agents source and negotiate; you approve; PayPal pays; margin flows back to Growth.</CardDescription>
              </div>
              <Button asChild size="sm" variant="outline"><Link href="/supply">Supply Command Center</Link></Button>
            </CardHeader>
            <CardContent className="space-y-3">
              {data.procurement.active_requests.length === 0 && data.margins.length === 0 && (
                <p className="text-sm text-muted-foreground">
                  No procurement in flight. {data.inventory.at_risk.length > 0 ? "Inventory Intelligence has flagged items at risk - " : ""}
                  <Link href="/supply/reorder" className="text-primary hover:underline">review reorder recommendations</Link>.
                </p>
              )}
              {data.procurement.active_requests.slice(0, 3).map((r) => (
                <Link key={r.procurement_request_id} href={`/supply/negotiations/${r.procurement_request_id}`}
                  className="block rounded-xl border border-border p-3 transition-colors hover:bg-muted/40">
                  <div className="mb-2 flex flex-wrap items-center justify-between gap-2">
                    <p className="text-sm font-medium"><span className="font-mono text-xs text-muted-foreground">{r.reference}</span> · {toNumber(r.quantity)} × {r.product_name}</p>
                    <span className="text-xs tabular-nums text-muted-foreground">budget {formatMoney(r.max_budget)}
                      {r.final_landed_total && <> · <span className="font-semibold text-foreground">{formatMoney(r.final_landed_total)}</span> recommended</>}</span>
                  </div>
                  <LifecycleStepper status={r.status} />
                </Link>
              ))}
              {data.margins.slice(0, 2).map((m) => (
                <div key={m.purchase_order_id} className="flex flex-wrap items-center justify-between gap-2 rounded-xl border border-success/30 bg-success/5 p-3 text-xs">
                  <span className="flex items-center gap-2 font-medium"><TrendingUp className="h-4 w-4 text-success" />
                    Reconciled {String(m.summary.purchase_order ?? "")}: unit cost {formatMoney(m.previous_unit_cost)} → {formatMoney(m.new_unit_cost)}</span>
                  <span className="font-semibold text-success">margin {m.previous_margin_pct}% → {m.new_margin_pct}%</span>
                </div>
              ))}
            </CardContent>
          </Card>

          <div className="grid gap-4 xl:grid-cols-3">
            <Card className="xl:col-span-2">
              <CardHeader className="pb-3">
                <CardTitle className="text-base">Business events</CardTitle>
                <CardDescription>Cross-module, persisted, correlated - the spine that connects the agents.</CardDescription>
              </CardHeader>
              <CardContent className="space-y-1.5">
                {data.events.length === 0 && <p className="text-sm text-muted-foreground">No business events yet.</p>}
                {data.events.map((e) => (
                  <div key={e.event_id} className="flex flex-wrap items-center gap-2 rounded-lg px-2 py-1.5 text-xs hover:bg-muted/40">
                    <span className={cn("rounded-md px-1.5 py-0.5 text-2xs font-semibold capitalize", MODULE_TONE[e.module] ?? "bg-muted")}>{e.module}</span>
                    <span className="font-medium">{e.label}</span>
                    <span className="truncate text-muted-foreground">{eventDetail(e.payload)}</span>
                    <span className="ml-auto font-mono text-2xs text-muted-foreground" title="Correlation id">{e.correlation_id.slice(0, 18)}</span>
                    <span className="text-2xs text-muted-foreground">{formatRelativeTime(e.created_at)}</span>
                  </div>
                ))}
              </CardContent>
            </Card>

            <div className="space-y-4">
              <Card>
                <CardHeader className="flex-row items-center justify-between pb-2">
                  <CardTitle className="text-base">Awaiting you</CardTitle>
                  <Button asChild size="sm" variant="ghost" className="gap-1"><Link href="/approvals">Inbox <ArrowRight className="h-3.5 w-3.5" /></Link></Button>
                </CardHeader>
                <CardContent className="space-y-2">
                  {data.approvals.items.length === 0 && <p className="text-sm text-muted-foreground">Nothing to approve.</p>}
                  {data.approvals.items.map((a) => (
                    <Link key={a.approval_id} href="/approvals" className="block rounded-lg border border-warning/40 bg-warning/5 p-2.5 text-xs hover:bg-warning/10">
                      <div className="flex justify-between"><span className="font-mono font-semibold">{a.reference}</span><span className="font-semibold tabular-nums">{formatMoney(a.amount)}</span></div>
                      <p className="truncate">{a.title}</p>
                    </Link>
                  ))}
                </CardContent>
              </Card>
              <Card>
                <CardHeader className="flex-row items-center justify-between pb-2">
                  <CardTitle className="text-base">PayPal</CardTitle>
                  <ModeBadge mode={data.paypal.mode} />
                </CardHeader>
                <CardContent className="space-y-2 text-xs">
                  <PayPalSummary data={data.paypal.intelligence} />
                  {data.financial_events.map((f) => (
                    <div key={f.execution_id} className="flex items-center justify-between rounded-lg bg-muted/40 px-2.5 py-1.5">
                      <span className="flex items-center gap-1.5">{f.kind.toLowerCase().replace(/_/g, " ")} <StatusPill status={f.status} /></span>
                      <span className="font-semibold tabular-nums">{formatMoney(f.amount)}</span>
                    </div>
                  ))}
                  <Button asChild size="sm" variant="ghost" className="w-full"><Link href="/finance/transactions">Finance</Link></Button>
                </CardContent>
              </Card>
            </div>
          </div>

          <div className="grid gap-4 lg:grid-cols-2">
            <Card>
              <CardHeader className="flex-row items-center justify-between pb-2">
                <CardTitle className="flex items-center gap-2 text-base"><Bot className="h-4 w-4 text-primary" /> Agent activity</CardTitle>
                <Button asChild size="sm" variant="ghost"><Link href="/agents">All runs</Link></Button>
              </CardHeader>
              <CardContent className="space-y-1.5">
                {data.agents.map((r) => (
                  <div key={r.run_id} className="flex items-center justify-between gap-2 rounded-lg px-2 py-1.5 text-xs hover:bg-muted/40">
                    <span className="min-w-0 truncate"><span className="font-medium">{r.agent_name.replace(/_/g, " ")}</span>
                      <span className="text-muted-foreground"> · {r.summary || r.workflow}</span></span>
                    <span className="flex shrink-0 items-center gap-1.5"><StatusPill status={r.status} />
                      {r.used_fallback && <span className="text-2xs text-muted-foreground">deterministic</span>}</span>
                  </div>
                ))}
              </CardContent>
            </Card>
            <Card>
              <CardHeader className="flex-row items-center justify-between pb-2">
                <CardTitle className="flex items-center gap-2 text-base"><LineChart className="h-4 w-4 text-primary" /> Growth KPIs</CardTitle>
                <Button asChild size="sm" variant="ghost"><Link href="/dashboard">Business overview</Link></Button>
              </CardHeader>
              <CardContent className="grid grid-cols-2 gap-3">
                {data.kpis.map((k) => (
                  <div key={k.key} className="rounded-lg bg-muted/40 p-2.5">
                    <p className="text-2xs uppercase text-muted-foreground">{k.label}</p>
                    <p className="font-semibold tabular-nums">{k.unit === "currency" ? formatCompactCurrency(k.value) : k.unit === "percent" ? `${k.value.toFixed(1)}%` : k.value.toLocaleString("en-US")}</p>
                    <p className={cn("text-2xs", (k.change_pct ?? 0) >= 0 ? "text-success" : "text-destructive")}>{kpiHint(k.change_pct)}</p>
                  </div>
                ))}
              </CardContent>
            </Card>
          </div>
        </>
      )}
      {isLoading && <LoadingRows rows={4} />}
    </div>
  );
}

function kpiHint(change: number | null | undefined): string {
  if (change == null) return "vs previous period";
  return `${change >= 0 ? "+" : ""}${change.toFixed(1)}% vs previous 30 days`;
}

function eventDetail(payload: Record<string, unknown>): string {
  const pick = ["reference", "supplier", "sku", "invoice", "purchase_order", "product_name"];
  return pick.map((k) => payload[k]).filter(Boolean).slice(0, 2).join(" · ");
}

function PayPalSummary({ data }: { data: { has_data: boolean; currencies: Record<string, { gross_revenue: string; refund_rate_pct: string; repeat_payer_rate_pct: string; transactions: number }> } }) {
  if (!data.has_data) return <p className="text-muted-foreground">No transactions synced yet.</p>;
  const usd = data.currencies.USD ?? Object.values(data.currencies)[0];
  if (!usd) return null;
  return (
    <div className="grid grid-cols-3 gap-2 text-center">
      <div className="rounded-lg bg-muted/40 py-1.5"><p className="text-2xs text-muted-foreground">Gross</p><p className="font-semibold tabular-nums">{formatCompactCurrency(usd.gross_revenue)}</p></div>
      <div className="rounded-lg bg-muted/40 py-1.5"><p className="text-2xs text-muted-foreground">Refunds</p><p className="font-semibold tabular-nums">{usd.refund_rate_pct}%</p></div>
      <div className="rounded-lg bg-muted/40 py-1.5"><p className="text-2xs text-muted-foreground">Repeat</p><p className="font-semibold tabular-nums">{usd.repeat_payer_rate_pct}%</p></div>
    </div>
  );
}
