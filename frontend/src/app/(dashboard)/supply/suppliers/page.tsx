"use client";

/** Supplier network: independent supplier agents, their public terms and performance. */

import { Building2, KeyRound, Plug, ShieldCheck } from "lucide-react";
import Link from "next/link";

import { EmptyState, ErrorState, LoadingRows } from "@/components/common/states";
import { PageHeader, PercentBar, pct, SimulatedTag, StatusPill } from "@/components/supply/shared";
import { Badge, Card, CardContent, CardHeader, CardTitle } from "@/components/ui/primitives";
import { useSuppliers } from "@/hooks/use-supply";
import { formatMoney, toNumber } from "@/lib/utils";

const STRATEGY: Record<string, string> = {
  PREMIUM_RELIABLE: "Premium & reliable",
  LOW_PRICE_LIMITED: "Low price, limited stock",
  FLEXIBLE_VOLUME: "Flexible negotiator",
};

export default function SupplierNetworkPage() {
  const { data, isLoading, error, refetch } = useSuppliers();
  return (
    <div className="space-y-5">
      <PageHeader eyebrow="Supply" title="Supplier network"
        description="Each supplier is an independent agent with its own private pricing policy. You see indicative terms and track record - never their floor prices, and they never see yours." />
      {error && <ErrorState error={error} onRetry={() => void refetch()} />}
      {isLoading && <LoadingRows rows={3} />}
      {!isLoading && (data ?? []).length === 0 && <EmptyState icon={Building2} title="No supplier agents" description="Seed the demo or connect a supplier agent." />}
      <div className="grid gap-4 lg:grid-cols-3">
        {(data ?? []).map((s) => (
          <Link key={s.supplier_agent_id} href={`/supply/suppliers/${s.supplier_agent_id}`}>
            <Card className="h-full transition-shadow hover:shadow-md">
              <CardHeader className="space-y-1.5 pb-2">
                <div className="flex items-start justify-between gap-2">
                  <CardTitle className="text-base">{s.display_name}</CardTitle>
                  <StatusPill status={s.status} />
                </div>
                <p className="text-xs text-muted-foreground">{s.tagline}</p>
                <div className="flex flex-wrap gap-1.5">
                  <Badge variant="secondary">{STRATEGY[s.strategy] ?? s.strategy}</Badge>
                  <Badge variant="outline">{s.region}</Badge>
                  <SimulatedTag show={s.is_simulated} />
                </div>
              </CardHeader>
              <CardContent className="space-y-3 text-xs">
                <div className="space-y-1">
                  <div className="flex justify-between"><span className="text-muted-foreground">Reliability</span><span className="font-semibold tabular-nums">{pct(s.reliability_score)}</span></div>
                  <PercentBar value={s.reliability_score} />
                </div>
                <div className="grid grid-cols-3 gap-2 text-center">
                  <Cell label="On time" value={pct(s.on_time_rate)} />
                  <Cell label="Quality" value={pct(s.quality_score)} />
                  <Cell label="Terms" value={s.payment_terms.replace("_", " ")} />
                </div>
                {s.catalog.slice(0, 2).map((c) => (
                  <div key={c.inventory_item_id} className="flex items-center justify-between rounded-lg bg-muted/40 px-2.5 py-1.5">
                    <span className="font-mono text-2xs">{c.vendor_sku}</span>
                    <span className="tabular-nums">{formatMoney(c.indicative_unit_price)} · MOQ {toNumber(c.minimum_order_quantity)}
                      {c.available_quantity != null && ` · ${toNumber(c.available_quantity)} in stock`}</span>
                  </div>
                ))}
                <div className="flex flex-wrap items-center gap-3 text-2xs text-muted-foreground">
                  <span className="inline-flex items-center gap-1"><Plug className="h-3 w-3" />{s.agent_key}</span>
                  <span className="inline-flex items-center gap-1"><KeyRound className="h-3 w-3" />{s.key_fingerprint.slice(0, 10)}…</span>
                  {s.paypal_payee_configured && <span className="inline-flex items-center gap-1 text-success"><ShieldCheck className="h-3 w-3" />PayPal payee</span>}
                </div>
              </CardContent>
            </Card>
          </Link>
        ))}
      </div>
    </div>
  );
}

function Cell({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-lg bg-muted/50 py-1.5">
      <p className="text-2xs uppercase text-muted-foreground">{label}</p>
      <p className="font-semibold">{value}</p>
    </div>
  );
}
