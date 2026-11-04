"use client";

/** Reorder recommendations: Inventory Intelligence's demand scan, and the button that starts sourcing. */

import { Play, SlidersHorizontal, TrendingUp } from "lucide-react";
import { useRouter } from "next/navigation";
import * as React from "react";

import { EmptyState, ErrorState, LoadingRows } from "@/components/common/states";
import { PageHeader, RiskBadge } from "@/components/supply/shared";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/overlays";
import { Card, CardContent, Input, Label } from "@/components/ui/primitives";
import { useCreateProcurement, useDemand } from "@/hooks/use-supply";
import { cn, formatMoney, toNumber } from "@/lib/utils";
import { useAuthStore } from "@/stores/auth";
import type { DemandAssessment } from "@/types/supply";

export default function ReorderPage() {
  const router = useRouter();
  const { data, isLoading, error, refetch } = useDemand();
  const create = useCreateProcurement();
  const canCreate = useAuthStore((s) => s.can("procurement:create"));
  const canNegotiate = useAuthStore((s) => s.can("procurement:negotiate"));
  const [configuring, setConfiguring] = React.useState<DemandAssessment | null>(null);
  const items = data?.data ?? [];

  const start = (item: DemandAssessment, overrides: Record<string, number> = {}) =>
    create.mutate(
      { inventory_item_id: item.inventory_item_id, auto_negotiate: false, ...overrides },
      { onSuccess: (request) => router.push(`/supply/negotiations/${request.procurement_request_id}`) },
    );

  return (
    <div className="space-y-5">
      <PageHeader eyebrow="Supply" title="Reorder recommendations"
        description={String(data?.meta.method ?? "Velocity over the last 14 days vs the 14 before, days of cover and the quantity needed to restore cover.")} />
      {error && <ErrorState error={error} onRetry={() => void refetch()} />}
      {isLoading && <LoadingRows rows={5} />}
      {!isLoading && items.length === 0 && <EmptyState icon={TrendingUp} title="No tracked inventory" description="Add inventory items to see demand and cover." />}
      <div className="space-y-2">
        {items.map((item) => (
          <Card key={item.inventory_item_id} className={cn(item.stockout_risk && "border-destructive/40")}>
            <CardContent className="grid gap-4 p-4 md:grid-cols-[1.4fr_1fr_1fr_auto] md:items-center">
              <div className="min-w-0">
                <div className="flex flex-wrap items-center gap-2">
                  <p className="font-semibold">{item.product_name}</p>
                  <span className="font-mono text-2xs text-muted-foreground">{item.sku}</span>
                  <RiskBadge level={item.risk_level} />
                </div>
                <p className="mt-1 text-2xs leading-relaxed text-muted-foreground">{item.reason}</p>
              </div>
              <Sparkline points={item.daily_units.map((d) => toNumber(d.units) ?? 0)} />
              <div className="grid grid-cols-3 gap-2 text-center text-xs tabular-nums">
                <Stat label="Cover" value={item.days_of_cover ? `${item.days_of_cover}d` : "--"} />
                <Stat label="Δ demand" value={`${item.demand_change_pct}%`} />
                <Stat label="Suggest" value={String(toNumber(item.suggested_quantity))} />
              </div>
              <div className="flex flex-col items-stretch gap-1.5">
                {item.open_request_reference ? (
                  <span className="text-2xs font-medium text-primary">{item.open_request_reference} in progress</span>
                ) : (
                  <>
                    <Button size="sm" className="gap-1.5" disabled={!canCreate || !canNegotiate || toNumber(item.suggested_quantity) === 0}
                      loading={create.isPending && create.variables?.inventory_item_id === item.inventory_item_id}
                      onClick={() => start(item)}>
                      <Play className="h-3.5 w-3.5" /> Start RFQ
                    </Button>
                    <Button size="sm" variant="ghost" className="gap-1.5" disabled={!canCreate} onClick={() => setConfiguring(item)}>
                      <SlidersHorizontal className="h-3.5 w-3.5" /> Policy…
                    </Button>
                  </>
                )}
                <p className="text-center text-2xs text-muted-foreground">sells at {formatMoney(item.selling_price)}</p>
              </div>
            </CardContent>
          </Card>
        ))}
      </div>
      <PolicyDialog item={configuring} onClose={() => setConfiguring(null)}
        onStart={(overrides) => configuring && start(configuring, overrides)} pending={create.isPending} />
    </div>
  );
}

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-lg bg-muted/50 py-1.5">
      <p className="text-2xs uppercase text-muted-foreground">{label}</p>
      <p className="font-semibold">{value}</p>
    </div>
  );
}

function Sparkline({ points }: { points: number[] }) {
  if (points.length < 2) return <div />;
  const max = Math.max(...points, 1);
  const W = 180;
  const H = 40;
  const d = points.map((v, i) => `${i === 0 ? "M" : "L"}${((i / (points.length - 1)) * W).toFixed(1)},${(H - (v / max) * (H - 4) - 2).toFixed(1)}`).join(" ");
  const split = (points.length / 2 / (points.length - 1)) * W;
  return (
    <svg viewBox={`0 0 ${W} ${H}`} className="h-10 w-full" aria-label="Daily units, 28 days">
      <rect x={split} y={0} width={W - split} height={H} className="fill-primary/5" />
      <path d={d} className="fill-none stroke-primary" strokeWidth={1.6} />
    </svg>
  );
}

function PolicyDialog({ item, onClose, onStart, pending }: {
  item: DemandAssessment | null; onClose: () => void; onStart: (o: Record<string, number>) => void; pending: boolean;
}) {
  const [quantity, setQuantity] = React.useState("");
  const [margin, setMargin] = React.useState("40");
  const [days, setDays] = React.useState("");
  React.useEffect(() => {
    if (item) {
      setQuantity(String(toNumber(item.suggested_quantity) ?? ""));
      setDays(String(item.required_within_days ?? 7));
      setMargin("40");
    }
  }, [item]);
  if (!item) return null;
  const price = toNumber(item.selling_price) ?? 0;
  const maxUnit = price * (1 - (Number(margin) || 0) / 100);
  return (
    <Dialog open onOpenChange={(open) => !open && onClose()}>
      <DialogContent className="max-w-md">
        <DialogHeader>
          <DialogTitle>Purchase policy for {item.product_name}</DialogTitle>
          <DialogDescription>
            The backend computes the binding limits; this is a preview. Max landed cost per unit = selling price × (1 − margin).
          </DialogDescription>
        </DialogHeader>
        <div className="grid grid-cols-3 gap-3">
          <div className="space-y-1"><Label htmlFor="pq">Quantity</Label><Input id="pq" type="number" value={quantity} onChange={(e) => setQuantity(e.target.value)} /></div>
          <div className="space-y-1"><Label htmlFor="pm">Margin %</Label><Input id="pm" type="number" value={margin} onChange={(e) => setMargin(e.target.value)} /></div>
          <div className="space-y-1"><Label htmlFor="pd">Within days</Label><Input id="pd" type="number" value={days} onChange={(e) => setDays(e.target.value)} /></div>
        </div>
        <p className="rounded-lg bg-muted/50 p-2.5 text-xs tabular-nums">
          {formatMoney(price)} × (1 − {margin}%) = <span className="font-semibold">{formatMoney(maxUnit)}</span> max per unit ·
          budget ≈ <span className="font-semibold">{formatMoney(maxUnit * (Number(quantity) || 0))}</span>
        </p>
        <DialogFooter>
          <Button variant="ghost" onClick={onClose}>Cancel</Button>
          <Button loading={pending} onClick={() => {
            const overrides: Record<string, number> = {
              target_margin: (Number(margin) || 40) / 100,
              max_delivery_days: Number(days) || 7,
            };
            if (Number(quantity) > 0) overrides.quantity = Number(quantity);
            onStart(overrides);
          }}>Start RFQ</Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
