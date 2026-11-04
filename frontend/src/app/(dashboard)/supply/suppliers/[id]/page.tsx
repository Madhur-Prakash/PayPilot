"use client";

/** Supplier profile: public terms, catalog, track record and negotiation history. */

import { ArrowLeft, KeyRound } from "lucide-react";
import Link from "next/link";
import { useParams } from "next/navigation";

import { ErrorState, LoadingCard } from "@/components/common/states";
import { MetricTile, PageHeader, pct, SimulatedTag, StatusPill } from "@/components/supply/shared";
import { Badge, Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/primitives";
import { useSupplier } from "@/hooks/use-supply";
import { formatMoney, formatRelativeTime, toNumber } from "@/lib/utils";
import { BadgeCheck, Clock, PiggyBank, Trophy } from "lucide-react";

export default function SupplierProfilePage() {
  const { id } = useParams<{ id: string }>();
  const { data, isLoading, error, refetch } = useSupplier(id);
  if (isLoading) return <LoadingCard lines={6} />;
  if (error || !data) return <ErrorState error={error} onRetry={() => void refetch()} />;
  const perf = data.performance;
  return (
    <div className="space-y-5">
      <Link href="/supply/suppliers" className="inline-flex items-center gap-1 text-xs text-muted-foreground hover:text-foreground">
        <ArrowLeft className="h-3.5 w-3.5" /> Supplier network
      </Link>
      <PageHeader eyebrow={data.agent_key} title={data.display_name} description={data.tagline}
        actions={<><StatusPill status={data.status} /><SimulatedTag show={data.is_simulated} /></>} />
      <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
        <MetricTile icon={BadgeCheck} tone="success" label="Reliability" value={pct(data.reliability_score)}
          hint="0.5 on-time + 0.3 fill rate + 0.2 invoice accuracy" />
        <MetricTile icon={Clock} tone="primary" label="On time" value={pct(data.on_time_rate)} hint={`${perf.orders_on_time} of ${perf.orders_completed} orders`} />
        <MetricTile icon={Trophy} label="Negotiations won" value={`${perf.negotiations_won} / ${perf.negotiations_total}`} />
        <MetricTile icon={PiggyBank} tone="success" label="Savings delivered" value={formatMoney(perf.total_savings)} />
      </div>
      <div className="grid gap-4 lg:grid-cols-2">
        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-sm">Public commercial terms</CardTitle>
            <CardDescription>What the Buyer Agent can see. Floors and concession policy stay private to the supplier agent.</CardDescription>
          </CardHeader>
          <CardContent>
            <dl className="grid grid-cols-2 gap-x-4 gap-y-2 text-xs">
              <dt className="text-muted-foreground">Payment terms</dt><dd className="text-right">{data.payment_terms.replace("_", " ")}</dd>
              <dt className="text-muted-foreground">Shipping</dt>
              <dd className="text-right tabular-nums">{formatMoney(data.shipping_flat)} + {formatMoney(data.shipping_per_unit)}/unit</dd>
              <dt className="text-muted-foreground">Free shipping over</dt>
              <dd className="text-right tabular-nums">{toNumber(data.free_shipping_threshold) ? formatMoney(data.free_shipping_threshold) : "never"}</dd>
              <dt className="text-muted-foreground">Expediting</dt><dd className="text-right">{data.expedite_available ? "available" : "not offered"}</dd>
              <dt className="text-muted-foreground">PayPal payee</dt><dd className="text-right">{data.paypal_payee_configured ? "configured" : "missing"}</dd>
              <dt className="text-muted-foreground">Invoices / discrepancies</dt><dd className="text-right">{perf.invoices_received} / {perf.invoice_discrepancies}</dd>
              <dt className="text-muted-foreground">Fill rate</dt>
              <dd className="text-right tabular-nums">{toNumber(perf.units_ordered) ? `${(((toNumber(perf.units_received) ?? 0) / (toNumber(perf.units_ordered) ?? 1)) * 100).toFixed(1)}%` : "--"}</dd>
            </dl>
            <p className="mt-3 inline-flex items-center gap-1 text-2xs text-muted-foreground">
              <KeyRound className="h-3 w-3" /> Protocol key fingerprint <span className="font-mono">{data.key_fingerprint}</span>
            </p>
          </CardContent>
        </Card>
        <Card>
          <CardHeader className="pb-2"><CardTitle className="text-sm">Catalog</CardTitle></CardHeader>
          <CardContent className="space-y-2 text-xs">
            {data.catalog.map((c) => (
              <div key={c.inventory_item_id} className="rounded-lg border border-border p-2.5">
                <div className="flex justify-between"><span className="font-mono">{c.vendor_sku}</span><span className="font-semibold tabular-nums">{formatMoney(c.indicative_unit_price)}</span></div>
                <p className="text-2xs text-muted-foreground">
                  MOQ {toNumber(c.minimum_order_quantity)} · lead {toNumber(c.lead_time_days)}d
                  {c.available_quantity != null ? ` · ${toNumber(c.available_quantity)} in stock` : " · stock not limited"}
                </p>
                {c.volume_breaks.length > 0 && (
                  <div className="mt-1 flex flex-wrap gap-1">
                    {c.volume_breaks.map((b) => (
                      <Badge key={b.min_quantity} variant="outline" className="text-2xs">{(Number(b.discount_pct) * 100).toFixed(0)}% off at {b.min_quantity}+</Badge>
                    ))}
                  </div>
                )}
              </div>
            ))}
          </CardContent>
        </Card>
      </div>
      <Card>
        <CardHeader className="pb-2"><CardTitle className="text-sm">Negotiation history</CardTitle></CardHeader>
        <CardContent className="space-y-1.5">
          {(data.negotiation_history ?? []).length === 0 && <p className="text-sm text-muted-foreground">No negotiations with this agent yet.</p>}
          {(data.negotiation_history ?? []).map((h) => (
            <div key={h.session_id} className="flex flex-wrap items-center justify-between gap-2 rounded-lg bg-muted/40 px-3 py-2 text-xs">
              <span><span className="font-mono">{h.procurement_reference}</span> · {h.product_name} · {h.rounds} round(s)</span>
              <span className="flex items-center gap-2"><StatusPill status={h.status} /><span className="text-muted-foreground">{formatRelativeTime(h.created_at)}</span></span>
            </div>
          ))}
        </CardContent>
      </Card>
    </div>
  );
}
