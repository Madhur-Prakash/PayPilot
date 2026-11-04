"use client";

/** Supply Command Center: stock risk, live RFQs, deliveries, suppliers, savings. */

import {
  AlertTriangle,
  ArrowRight,
  Boxes,
  CircleDollarSign,
  Handshake,
  PackageCheck,
  PiggyBank,
  Receipt,
  Sparkles,
  Truck,
} from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";

import { EmptyState, ErrorState, LoadingKpis, LoadingRows } from "@/components/common/states";
import { MetricTile, PageHeader, PercentBar, pct, RiskBadge, SimulatedTag, StatusPill } from "@/components/supply/shared";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/primitives";
import { useProcurementAutopilot, useSupplyOverview } from "@/hooks/use-supply";
import { formatDate, formatMoney, formatRelativeTime, toNumber } from "@/lib/utils";
import { useAuthStore } from "@/stores/auth";

export default function SupplyCommandCenterPage() {
  const router = useRouter();
  const { data, isLoading, error, refetch } = useSupplyOverview();
  const autopilot = useProcurementAutopilot();
  const canStart = useAuthStore((s) => s.can("procurement:create") && s.can("procurement:negotiate"));

  return (
    <div className="space-y-6">
      <PageHeader
        eyebrow="Supply"
        title="Supply Command Center"
        description="Inventory Intelligence watches demand and cover; the Buyer Agent sources from independent supplier agents; nothing is bought without a human approval."
        actions={
          canStart && (
            <Button className="gap-1.5" loading={autopilot.isPending}
              onClick={() => autopilot.mutate({}, {
                onSuccess: ({ data: request }) => request && router.push(`/supply/negotiations/${request.procurement_request_id}`),
              })}>
              <Sparkles className="h-4 w-4" /> Run procurement autopilot
            </Button>
          )
        }
      />

      {error && <ErrorState error={error} onRetry={() => void refetch()} />}
      {isLoading && <LoadingKpis count={4} />}

      {data && (
        <>
          <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
            <MetricTile icon={AlertTriangle} tone={data.inventory.at_risk.length ? "destructive" : "success"} label="Stockout risks"
              value={data.inventory.at_risk.length} hint={`${data.inventory.tracked_items} items tracked`} />
            <MetricTile icon={Handshake} tone="primary" label="Active negotiations" value={data.procurement.active_negotiations}
              hint={`${data.procurement.active_requests.length} open requests`} />
            <MetricTile icon={PiggyBank} tone="success" label="Negotiated savings" value={formatMoney(data.procurement.savings)}
              hint={`on ${formatMoney(data.procurement.spend)} spend (30 days)`} />
            <MetricTile icon={Receipt} tone={data.procurement.outstanding_invoices ? "warning" : "default"} label="Outstanding invoices"
              value={formatMoney(data.procurement.outstanding_amount)} hint={`${data.procurement.outstanding_invoices} supplier invoice(s)`} />
          </div>

          <div className="grid gap-4 xl:grid-cols-3">
            <Card className="xl:col-span-2">
              <CardHeader className="flex-row items-center justify-between pb-3">
                <div>
                  <CardTitle className="text-base">Reorder requirements</CardTitle>
                  <CardDescription>Velocity, cover and suggested quantity - computed, not guessed.</CardDescription>
                </div>
                <Button asChild size="sm" variant="ghost" className="gap-1"><Link href="/supply/reorder">All items <ArrowRight className="h-3.5 w-3.5" /></Link></Button>
              </CardHeader>
              <CardContent className="space-y-2">
                {data.reorder.length === 0 && <EmptyState icon={Boxes} title="Every item has enough cover" description="Nothing needs sourcing right now." />}
                {data.reorder.slice(0, 6).map((item) => (
                  <div key={item.inventory_item_id} className="flex flex-wrap items-center justify-between gap-3 rounded-xl border border-border p-3">
                    <div className="min-w-0">
                      <div className="flex items-center gap-2">
                        <p className="truncate font-medium">{item.product_name}</p>
                        <RiskBadge level={item.risk_level} />
                        {item.demand_increased && <span className="text-2xs font-semibold text-primary">demand +{item.demand_change_pct}%</span>}
                      </div>
                      <p className="text-2xs text-muted-foreground tabular-nums">
                        {toNumber(item.available)} {item.unit} · {item.velocity_recent}/day · {item.days_of_cover ?? "--"} days cover · lead {item.lead_time_days}d
                      </p>
                    </div>
                    <div className="text-right">
                      <p className="text-sm font-semibold tabular-nums">{toNumber(item.suggested_quantity)} {item.unit}</p>
                      {item.open_request_reference ? (
                        <p className="text-2xs text-primary">{item.open_request_reference} in progress</p>
                      ) : (
                        <p className="text-2xs text-muted-foreground">needed within {item.required_within_days ?? "--"} days</p>
                      )}
                    </div>
                  </div>
                ))}
              </CardContent>
            </Card>

            <Card>
              <CardHeader className="pb-3">
                <CardTitle className="text-base">Active RFQs</CardTitle>
                <CardDescription>From requirement to reconciliation.</CardDescription>
              </CardHeader>
              <CardContent className="space-y-2">
                {data.procurement.active_requests.length === 0 && (
                  <p className="py-6 text-center text-sm text-muted-foreground">No open procurement. Run the autopilot or start an RFQ from Reorder.</p>
                )}
                {data.procurement.active_requests.map((r) => (
                  <Link key={r.procurement_request_id} href={`/supply/negotiations/${r.procurement_request_id}`}
                    className="block rounded-xl border border-border p-3 transition-colors hover:bg-muted/50">
                    <div className="flex items-center justify-between gap-2">
                      <span className="font-mono text-xs font-semibold">{r.reference}</span>
                      <StatusPill status={r.status} />
                    </div>
                    <p className="mt-0.5 truncate text-xs">{toNumber(r.quantity)} × {r.product_name}</p>
                    <p className="text-2xs text-muted-foreground tabular-nums">
                      budget {formatMoney(r.max_budget)}{r.final_landed_total && ` · recommended ${formatMoney(r.final_landed_total)}`}
                    </p>
                  </Link>
                ))}
              </CardContent>
            </Card>
          </div>

          <div className="grid gap-4 xl:grid-cols-3">
            <Card>
              <CardHeader className="pb-3">
                <CardTitle className="text-base">Supplier performance</CardTitle>
                <CardDescription>Updated from every reconciled order.</CardDescription>
              </CardHeader>
              <CardContent className="space-y-3">
                {data.suppliers.map((s) => (
                  <div key={s.supplier_agent_id} className="space-y-1">
                    <div className="flex items-center justify-between text-xs">
                      <Link href={`/supply/suppliers/${s.supplier_agent_id}`} className="font-medium hover:underline">{s.display_name}</Link>
                      <span className="tabular-nums">{pct(s.reliability_score)} reliable · {pct(s.on_time_rate)} on time</span>
                    </div>
                    <PercentBar value={s.reliability_score} />
                    <SimulatedTag show={s.is_simulated} />
                  </div>
                ))}
                {data.suppliers.length === 0 && <p className="text-sm text-muted-foreground">No supplier agents yet.</p>}
              </CardContent>
            </Card>

            <Card>
              <CardHeader className="pb-3">
                <CardTitle className="text-base">Upcoming deliveries</CardTitle>
                <CardDescription>Purchase orders in flight.</CardDescription>
              </CardHeader>
              <CardContent className="space-y-2">
                {data.procurement.upcoming_deliveries.length === 0 && <p className="text-sm text-muted-foreground">Nothing in transit.</p>}
                {data.procurement.upcoming_deliveries.map((o) => (
                  <div key={o.purchase_order_id} className="flex items-center justify-between rounded-lg border border-border p-2.5 text-xs">
                    <span className="flex items-center gap-2"><Truck className="h-3.5 w-3.5 text-muted-foreground" /><span className="font-mono">{o.reference}</span></span>
                    <span className="tabular-nums">{formatMoney(o.total_value)} · {formatDate(o.expected_at)}</span>
                  </div>
                ))}
                {data.recent_receipts.length > 0 && (
                  <div className="pt-2">
                    <p className="pb-1 text-2xs font-semibold uppercase tracking-wide text-muted-foreground">Recently received</p>
                    {data.recent_receipts.map((r) => (
                      <p key={r.goods_receipt_id} className="flex items-center gap-1.5 text-2xs text-muted-foreground">
                        <PackageCheck className="h-3 w-3 text-success" />{r.reference} · {toNumber(r.total_quantity)} units · {formatRelativeTime(r.received_at)}
                      </p>
                    ))}
                  </div>
                )}
              </CardContent>
            </Card>

            <Card>
              <CardHeader className="flex-row items-center justify-between pb-3">
                <div>
                  <CardTitle className="text-base">Awaiting approval</CardTitle>
                  <CardDescription>Money moves only after a human says yes.</CardDescription>
                </div>
                <Button asChild size="sm" variant="ghost"><Link href="/approvals">Inbox</Link></Button>
              </CardHeader>
              <CardContent className="space-y-2">
                {data.approvals.items.length === 0 && <p className="text-sm text-muted-foreground">Nothing waiting.</p>}
                {data.approvals.items.map((a) => (
                  <Link key={a.approval_id} href="/approvals" className="block rounded-lg border border-warning/40 bg-warning/5 p-2.5 text-xs hover:bg-warning/10">
                    <div className="flex items-center justify-between gap-2">
                      <span className="font-mono font-semibold">{a.reference}</span>
                      <span className="flex items-center gap-1 font-semibold tabular-nums"><CircleDollarSign className="h-3.5 w-3.5" />{formatMoney(a.amount)}</span>
                    </div>
                    <p className="mt-0.5 truncate">{a.title}</p>
                  </Link>
                ))}
              </CardContent>
            </Card>
          </div>

          {data.events.length > 0 && (
            <Card>
              <CardHeader className="pb-3">
                <CardTitle className="text-base">Supply & finance events</CardTitle>
              </CardHeader>
              <CardContent className="grid gap-1.5 sm:grid-cols-2">
                {data.events.slice(0, 10).map((e) => (
                  <div key={e.event_id} className="flex items-center justify-between gap-2 rounded-lg bg-muted/40 px-2.5 py-1.5 text-2xs">
                    <span className="font-medium">{e.label}</span>
                    <span className="text-muted-foreground">{formatRelativeTime(e.created_at)}</span>
                  </div>
                ))}
              </CardContent>
            </Card>
          )}
        </>
      )}
      {isLoading && <LoadingRows rows={4} />}
    </div>
  );
}
