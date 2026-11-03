"use client";

import { Link2, Package, TrendingDown, TrendingUp } from "lucide-react";
import * as React from "react";

import { ProductBarChart } from "@/components/charts/charts";
import { ErrorState, LoadingRows } from "@/components/common/states";
import { RangePicker, useRangeDays } from "@/components/dashboard/range-picker";
import { Stagger, StaggerItem } from "@/components/ui/motion";
import {
  Badge,
  Card,
  CardContent,
  CardHeader,
  CardTitle,
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from "@/components/ui/primitives";
import { useProductAnalytics } from "@/hooks/use-api";
import { cn, formatCompactCurrency, formatNumber, formatPercent } from "@/lib/utils";

export default function ProductsPage() {
  const [days, setDays] = useRangeDays(30);
  const { data, isLoading, error, refetch } = useProductAnalytics(days);

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h2 className="text-xl font-semibold tracking-tight">Products</h2>
          <p className="text-sm text-muted-foreground">
            Performance, margin and what sells together
          </p>
        </div>
        <RangePicker days={days} onChange={setDays} period={data?.period} />
      </div>

      {isLoading && <LoadingRows rows={4} />}
      {error && <ErrorState error={error} onRetry={() => void refetch()} />}

      {data && (
        <>
          <div className="grid gap-4 lg:grid-cols-[minmax(0,1.3fr)_minmax(0,1fr)]">
            <Card>
              <CardHeader>
                <CardTitle>Revenue by product</CardTitle>
              </CardHeader>
              <CardContent>
                <ProductBarChart
                  data={data.products.map((product) => ({
                    name: product.name,
                    revenue: product.revenue,
                    change_pct: product.change_pct,
                  }))}
                  height={Math.max(260, data.products.length * 34)}
                />
              </CardContent>
            </Card>

            <div className="space-y-4">
              <MoversCard
                title="Growing"
                icon={TrendingUp}
                tone="success"
                products={data.growing}
              />
              <MoversCard
                title="Declining"
                icon={TrendingDown}
                tone="destructive"
                products={data.declining}
              />
            </div>
          </div>

          {/* Market basket */}
          {data.product_mix.length > 0 && (
            <Card>
              <CardHeader>
                <CardTitle className="flex items-center gap-2">
                  <Link2 className="h-4 w-4 text-primary" />
                  Bought together
                </CardTitle>
                <p className="text-sm text-muted-foreground">
                  Pairs appearing together more often than their individual rates predict. Lift
                  above 1.0 means the pairing is real, not coincidence.
                </p>
              </CardHeader>
              <CardContent>
                <Stagger className="grid gap-3 md:grid-cols-2 xl:grid-cols-3">
                  {data.product_mix.map((pair) => (
                    <StaggerItem key={`${pair.product_a_id}-${pair.product_b_id}`}>
                      <div className="h-full rounded-xl border border-border bg-card p-4">
                        <p className="text-sm font-medium leading-snug">
                          {pair.product_a_name}
                          <span className="mx-1.5 text-muted-foreground">+</span>
                          {pair.product_b_name}
                        </p>
                        <div className="mt-3 grid grid-cols-3 gap-2 text-center">
                          <Metric
                            label="Lift"
                            value={`${pair.lift.toFixed(2)}x`}
                            tone={pair.lift > 1.2 ? "success" : undefined}
                            tooltip="How much more often they appear together than chance would predict."
                          />
                          <Metric
                            label="Orders"
                            value={formatNumber(pair.co_occurrences)}
                          />
                          <Metric
                            label="Attach"
                            value={formatPercent(pair.confidence_pct, 0)}
                            tooltip="Share of the first product's orders that also contain the second."
                          />
                        </div>
                        {pair.estimated_bundle_uplift > 0 && (
                          <p className="mt-3 rounded-md bg-primary/8 px-2 py-1.5 text-2xs text-primary">
                            Bundle upside ≈{" "}
                            {formatCompactCurrency(pair.estimated_bundle_uplift)}/period
                          </p>
                        )}
                      </div>
                    </StaggerItem>
                  ))}
                </Stagger>
              </CardContent>
            </Card>
          )}

          {/* Table */}
          <Card>
            <CardHeader>
              <CardTitle>All products</CardTitle>
            </CardHeader>
            <CardContent className="overflow-x-auto">
              <table className="w-full min-w-[720px] text-sm">
                <thead>
                  <tr className="border-b border-border text-left text-2xs uppercase tracking-wide text-muted-foreground">
                    <th className="pb-2 font-medium">Product</th>
                    <th className="pb-2 text-right font-medium">Revenue</th>
                    <th className="pb-2 text-right font-medium">Change</th>
                    <th className="pb-2 text-right font-medium">Units</th>
                    <th className="pb-2 text-right font-medium">Margin</th>
                    <th className="pb-2 text-right font-medium">Attach</th>
                    <th className="pb-2 text-right font-medium">Share</th>
                  </tr>
                </thead>
                <tbody>
                  {data.products.map((product) => (
                    <tr key={product.product_id} className="border-b border-border/60 last:border-0">
                      <td className="py-2.5">
                        <p className="font-medium">{product.name}</p>
                        <p className="text-2xs text-muted-foreground">{product.category}</p>
                      </td>
                      <td className="py-2.5 text-right tnum">
                        {formatCompactCurrency(product.revenue)}
                      </td>
                      <td
                        className={cn(
                          "py-2.5 text-right font-medium tnum",
                          (product.change_pct ?? 0) < 0 ? "text-destructive" : "text-success",
                        )}
                      >
                        {product.change_pct == null
                          ? "--"
                          : `${product.change_pct >= 0 ? "+" : ""}${product.change_pct.toFixed(1)}%`}
                      </td>
                      <td className="py-2.5 text-right tnum">
                        {formatNumber(product.units_sold)}
                      </td>
                      <td className="py-2.5 text-right tnum">
                        {formatPercent(product.margin_pct, 0)}
                      </td>
                      <td className="py-2.5 text-right tnum">
                        {formatPercent(product.attach_rate_pct, 0)}
                      </td>
                      <td className="py-2.5 text-right tnum text-muted-foreground">
                        {formatPercent(product.revenue_share_pct, 0)}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </CardContent>
          </Card>
        </>
      )}
    </div>
  );
}

function MoversCard({
  title,
  icon: Icon,
  tone,
  products,
}: {
  title: string;
  icon: typeof Package;
  tone: "success" | "destructive";
  products: { product_id: string; name: string; revenue: number; change_pct: number | null }[];
}) {
  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2 text-base">
          <Icon className={cn("h-4 w-4", tone === "success" ? "text-success" : "text-destructive")} />
          {title}
        </CardTitle>
      </CardHeader>
      <CardContent className="space-y-1.5">
        {products.length === 0 && (
          <p className="py-3 text-center text-sm text-muted-foreground">Nothing here.</p>
        )}
        {products.map((product) => (
          <div
            key={product.product_id}
            className="flex items-center justify-between rounded-lg border border-border px-3 py-2"
          >
            <span className="min-w-0 truncate text-sm">{product.name}</span>
            <span
              className={cn(
                "shrink-0 text-sm font-medium tnum",
                tone === "success" ? "text-success" : "text-destructive",
              )}
            >
              {product.change_pct == null
                ? "--"
                : `${product.change_pct >= 0 ? "+" : ""}${product.change_pct.toFixed(1)}%`}
            </span>
          </div>
        ))}
      </CardContent>
    </Card>
  );
}

function Metric({
  label,
  value,
  tone,
  tooltip,
}: {
  label: string;
  value: string;
  tone?: "success";
  tooltip?: string;
}) {
  const body = (
    <div className={tooltip ? "cursor-help" : undefined}>
      <p className="text-2xs uppercase tracking-wide text-muted-foreground">{label}</p>
      <p className={cn("text-sm font-semibold tnum", tone === "success" && "text-success")}>
        {value}
      </p>
    </div>
  );
  if (!tooltip) return body;
  return (
    <Tooltip>
      <TooltipTrigger asChild>{body}</TooltipTrigger>
      <TooltipContent>{tooltip}</TooltipContent>
    </Tooltip>
  );
}
