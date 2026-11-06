"use client";

/** Dashboard Studio - merchants build their own dashboards over PayPilot's computed datasets (AG Studio). */

import {
  Boxes,
  Building2,
  Handshake,
  Info,
  LayoutDashboard,
  type LucideIcon,
  PanelsTopLeft,
  Pencil,
  PiggyBank,
  RotateCcw,
  ScanEye,
  ShieldAlert,
  Sparkles,
  Store,
  TrendingUp,
  Truck,
  Wallet,
} from "lucide-react";
import dynamic from "next/dynamic";
import * as React from "react";

import { EmptyState, ErrorState, LoadingCard } from "@/components/common/states";
import { resetStudioReport } from "@/components/studio/studio-canvas";
import { MetricTile } from "@/components/supply/shared";
import { Button } from "@/components/ui/button";
import { useStudioDatasets } from "@/hooks/use-integrations";
import { cn, formatMoney, formatRelativeTime } from "@/lib/utils";
import type { StudioRow } from "@/types/integrations";

// AG Studio measures its parent and touches the DOM, so it renders on the client only.
const StudioCanvas = dynamic(() => import("@/components/studio/studio-canvas"), {
  ssr: false,
  loading: () => <LoadingCard lines={10} />,
});

const SOURCE_ICON: Record<string, LucideIcon> = {
  sales: Store,
  paypal_transactions: Wallet,
  procurements: Truck,
  negotiation_offers: Handshake,
  suppliers: Building2,
  inventory_cover: Boxes,
};

const sum = (rows: StudioRow[] | undefined, key: string) =>
  (rows ?? []).reduce((total, row) => total + (typeof row[key] === "number" ? (row[key] as number) : 0), 0);

export default function StudioPage() {
  const datasets = useStudioDatasets();
  const [mode, setMode] = React.useState<"edit" | "view">("view");
  // Remounting is how a saved layout is dropped: Studio reads `initialState` once.
  const [generation, setGeneration] = React.useState(0);

  const all = datasets.data?.datasets ?? {};
  const usable = Object.fromEntries(Object.entries(all).filter(([, rows]) => rows.length > 0));
  const names = Object.keys(usable);
  const ai = datasets.data?.ai;

  // Headline numbers - the same backend-computed rows the canvas charts.
  const revenue = sum(usable.sales, "revenue");
  const profit = sum(usable.sales, "gross_profit");
  const orders = sum(usable.sales, "orders");
  const savings = sum(usable.procurements, "savings");
  const atRisk = sum(usable.inventory_cover, "revenue_at_risk");
  const riskyItems = (usable.inventory_cover ?? []).filter((r) => Number(r.revenue_at_risk) > 0).length;

  return (
    <div className="min-w-0 space-y-5">
      {/* Header */}
      <section className="flex flex-wrap items-start justify-between gap-4">
        <div className="flex min-w-0 items-start gap-3">
          <span className="mt-0.5 flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-primary/10 text-primary">
            <PanelsTopLeft className="h-5 w-5" />
          </span>
          <div className="min-w-0">
            <div className="flex flex-wrap items-center gap-2">
              <h1 className="text-xl font-semibold tracking-tight">Dashboard Studio</h1>
              <span className="rounded-full border border-border bg-muted/50 px-2 py-0.5 text-2xs font-medium text-muted-foreground">
                AG Studio
              </span>
            </div>
            <p className="mt-0.5 max-w-2xl text-sm text-muted-foreground">
              Your business on one canvas. Switch to <span className="font-medium text-foreground">Edit</span> to drag
              fields into new charts - every number is one PayPilot already computed.
            </p>
          </div>
        </div>

        <div className="flex items-center gap-2">
          <div role="group" aria-label="Mode" className="inline-flex rounded-lg border border-border bg-muted/40 p-0.5">
            {([
              { id: "view", label: "View", icon: ScanEye },
              { id: "edit", label: "Edit", icon: Pencil },
            ] as const).map(({ id, label, icon: Icon }) => (
              <button key={id} type="button" aria-pressed={mode === id} onClick={() => setMode(id)}
                className={cn(
                  "inline-flex items-center gap-1.5 rounded-md px-3 py-1.5 text-xs font-medium transition-colors focus-ring",
                  mode === id ? "bg-card text-foreground shadow-sm" : "text-muted-foreground hover:text-foreground",
                )}>
                <Icon className="h-3.5 w-3.5" /> {label}
              </button>
            ))}
          </div>
          <Button size="sm" variant="ghost" className="gap-1.5 text-muted-foreground" title="Back to the default dashboard"
            onClick={() => { resetStudioReport(); setGeneration((g) => g + 1); }}>
            <RotateCcw className="h-3.5 w-3.5" /> Reset
          </Button>
        </div>
      </section>

      {datasets.error && <ErrorState error={datasets.error} onRetry={() => void datasets.refetch()} />}
      {datasets.isLoading && <LoadingCard lines={8} />}

      {datasets.data && names.length === 0 && (
        <EmptyState icon={LayoutDashboard} title="No data to chart yet"
          description="Sync PayPal transactions or start a procurement, then come back." />
      )}

      {datasets.data && names.length > 0 && (
        <>
          {/* Headline KPIs */}
          <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
            <MetricTile icon={TrendingUp} tone="primary" label="Revenue, last 120 days"
              value={formatMoney(String(revenue.toFixed(2)))} hint={`${orders.toLocaleString()} orders`} />
            <MetricTile icon={Wallet} tone="success" label="Gross profit"
              value={formatMoney(String(profit.toFixed(2)))}
              hint={revenue > 0 ? `${((profit / revenue) * 100).toFixed(1)}% gross margin` : undefined} />
            <MetricTile icon={PiggyBank} tone="success" label="Negotiated savings"
              value={formatMoney(String(savings.toFixed(2)))}
              hint={`${(usable.procurements ?? []).length} procurements by the supplier agents`} />
            <MetricTile icon={ShieldAlert} tone={atRisk > 0 ? "warning" : "default"} label="Revenue at risk"
              value={formatMoney(String(atRisk.toFixed(2)))}
              hint={riskyItems ? `${riskyItems} items could run out before stock arrives` : "No stockout risk"} />
          </div>

          {/* Sources */}
          <div className="flex flex-wrap items-center gap-2">
            <span className="text-xs font-medium text-muted-foreground">Live data</span>
            {names.map((name) => {
              const Icon = SOURCE_ICON[name] ?? LayoutDashboard;
              return (
                <span key={name}
                  className="inline-flex items-center gap-1.5 rounded-full border border-border bg-card px-2.5 py-1 text-xs">
                  <Icon className="h-3.5 w-3.5 text-muted-foreground" />
                  {datasets.data!.labels[name] ?? name}
                  <span className="tabular-nums text-muted-foreground">{usable[name]!.length.toLocaleString()}</span>
                </span>
              );
            })}
            <span title={ai?.note}
              className={cn(
                "inline-flex items-center gap-1.5 rounded-full border px-2.5 py-1 text-xs",
                ai?.available ? "border-primary/30 bg-primary/5 text-primary" : "border-border text-muted-foreground",
              )}>
              <Sparkles className="h-3.5 w-3.5" />
              {ai?.available ? "AI assistant ready" : "AI assistant off"}
            </span>
            <span className="ml-auto text-2xs text-muted-foreground">
              Refreshed {formatRelativeTime(datasets.data.generated_at)} · layout saved in this browser
            </span>
          </div>

          {/* Canvas */}
          <div className="h-[calc(100vh-7rem)] min-h-[640px] overflow-hidden rounded-2xl border border-border bg-card shadow-sm">
            <StudioCanvas key={`${generation}-${ai?.available ? "ai" : "plain"}`} datasets={usable} mode={mode}
              aiAvailable={Boolean(ai?.available)} />
          </div>

          <p className="flex items-start gap-1.5 text-2xs text-muted-foreground">
            <Info className="mt-px h-3 w-3 shrink-0" />
            <span>
              {datasets.data.note} In Edit, the panels on the canvas edge add fields, filters and the AI assistant.
            </span>
          </p>
        </>
      )}
    </div>
  );
}
