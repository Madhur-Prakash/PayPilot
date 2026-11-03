"use client";

import * as React from "react";
import {
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  Legend,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { TrendingUp, TrendingDown, Layers, Box, DollarSign } from "lucide-react";
import { cn, formatCompactCurrency, formatNumber } from "@/lib/utils";
import type { ProductPerformance } from "@/types/api";

interface ProductPerformanceViewProps {
  products: ProductPerformance[];
  height?: number;
}

export function ProductPerformanceMatrix({ products, height = 320 }: ProductPerformanceViewProps) {
  const [viewMode, setViewMode] = React.useState<"combined" | "revenue" | "units">("combined");

  const topItems = products.slice(0, 6);
  const totalRevenue = topItems.reduce((acc, p) => acc + p.revenue, 0);

  const chartData = topItems.map((p) => {
    const isUp = (p.change_pct ?? 0) >= 0;
    return {
      name: p.name,
      revenue: p.revenue,
      units: p.units_sold,
      margin: p.gross_margin,
      marginPct: p.margin_pct,
      changePct: p.change_pct ?? 0,
      sharePct: p.revenue_share_pct || (totalRevenue ? (p.revenue / totalRevenue) * 100 : 0),
      isUp,
    };
  });

  return (
    <div className="space-y-4">
      {/* Top View Filter Switcher & Metric Badges */}
      <div className="flex flex-wrap items-center justify-between gap-2 border-b border-border/50 pb-3">
        <div className="flex items-center gap-1.5 rounded-lg bg-muted p-1 text-2xs font-medium">
          <button
            type="button"
            onClick={() => setViewMode("combined")}
            className={cn(
              "flex items-center gap-1.5 px-2.5 py-1 rounded-md transition-all",
              viewMode === "combined"
                ? "bg-background text-foreground shadow-xs font-semibold"
                : "text-muted-foreground hover:text-foreground",
            )}
          >
            <Layers className="h-3 w-3" />
            Dual View
          </button>
          <button
            type="button"
            onClick={() => setViewMode("revenue")}
            className={cn(
              "flex items-center gap-1.5 px-2.5 py-1 rounded-md transition-all",
              viewMode === "revenue"
                ? "bg-background text-foreground shadow-xs font-semibold"
                : "text-muted-foreground hover:text-foreground",
            )}
          >
            <DollarSign className="h-3 w-3" />
            Revenue
          </button>
          <button
            type="button"
            onClick={() => setViewMode("units")}
            className={cn(
              "flex items-center gap-1.5 px-2.5 py-1 rounded-md transition-all",
              viewMode === "units"
                ? "bg-background text-foreground shadow-xs font-semibold"
                : "text-muted-foreground hover:text-foreground",
            )}
          >
            <Box className="h-3 w-3" />
            Units Sold
          </button>
        </div>

        <div className="flex items-center gap-3 text-2xs font-medium text-muted-foreground">
          <span className="flex items-center gap-1">
            <span className="h-2 w-2 rounded-full bg-blue-600 dark:bg-blue-500" />
            Revenue (₹)
          </span>
          <span className="flex items-center gap-1">
            <span className="h-2 w-2 rounded-full bg-amber-500" />
            Units Sold
          </span>
        </div>
      </div>

      {/* Main Dual-Axis Interactive Horizontal / Vertical Bar Chart */}
      <div className="w-full">
        <ResponsiveContainer width="100%" height={height}>
          <BarChart
            data={chartData}
            margin={{ top: 8, right: 12, bottom: 4, left: 4 }}
            barGap={4}
          >
            <defs>
              <linearGradient id="revenueBarGradient" x1="0" y1="0" x2="0" y2="1">
                <stop offset="0%" stopColor="#2563EB" stopOpacity={0.95} />
                <stop offset="100%" stopColor="#1D4ED8" stopOpacity={0.75} />
              </linearGradient>
              <linearGradient id="unitsBarGradient" x1="0" y1="0" x2="0" y2="1">
                <stop offset="0%" stopColor="#F59E0B" stopOpacity={0.95} />
                <stop offset="100%" stopColor="#D97706" stopOpacity={0.75} />
              </linearGradient>
            </defs>

            <CartesianGrid strokeDasharray="3 3" stroke="hsl(var(--border))" vertical={false} opacity={0.6} />

            <XAxis
              dataKey="name"
              stroke="hsl(var(--muted-foreground))"
              fontSize={11}
              tickLine={false}
              axisLine={false}
              interval={0}
              tickFormatter={(v) => (v.length > 12 ? `${v.slice(0, 11)}…` : v)}
            />

            <YAxis
              yAxisId="left"
              stroke="hsl(var(--muted-foreground))"
              fontSize={11}
              tickLine={false}
              axisLine={false}
              tickFormatter={(v) => formatCompactCurrency(v)}
              width={56}
              hide={viewMode === "units"}
            />

            <YAxis
              yAxisId="right"
              orientation="right"
              stroke="hsl(var(--muted-foreground))"
              fontSize={11}
              tickLine={false}
              axisLine={false}
              tickFormatter={(v) => formatNumber(v)}
              width={46}
              hide={viewMode === "revenue"}
            />

            <Tooltip
              cursor={{ fill: "hsl(var(--muted))", opacity: 0.35 }}
              content={({ active, payload }) => {
                if (!active || !payload?.length) return null;
                const d = payload[0].payload;
                return (
                  <div className="rounded-2xl border border-border/80 bg-popover/95 p-3.5 shadow-2xl backdrop-blur-xl min-w-[210px] space-y-2 text-xs">
                    <div className="flex items-center justify-between pb-1.5 border-b border-border/60">
                      <p className="font-bold text-foreground truncate max-w-[140px]">{d.name}</p>
                      <span
                        className={cn(
                          "flex items-center gap-0.5 text-2xs font-bold tnum px-1.5 py-0.5 rounded-md",
                          d.isUp
                            ? "bg-emerald-500/10 text-emerald-500"
                            : "bg-rose-500/10 text-rose-500",
                        )}
                      >
                        {d.isUp ? <TrendingUp className="h-3 w-3" /> : <TrendingDown className="h-3 w-3" />}
                        {d.changePct > 0 ? `+${d.changePct.toFixed(1)}%` : `${d.changePct.toFixed(1)}%`}
                      </span>
                    </div>

                    <div className="space-y-1.5 text-muted-foreground">
                      <div className="flex justify-between items-center">
                        <span className="flex items-center gap-1.5">
                          <span className="h-2 w-2 rounded-full bg-blue-600" />
                          Revenue:
                        </span>
                        <span className="font-semibold text-foreground tnum">
                          {formatCompactCurrency(d.revenue)}
                        </span>
                      </div>

                      <div className="flex justify-between items-center">
                        <span className="flex items-center gap-1.5">
                          <span className="h-2 w-2 rounded-full bg-amber-500" />
                          Volume Sold:
                        </span>
                        <span className="font-semibold text-foreground tnum">
                          {formatNumber(d.units)} units
                        </span>
                      </div>

                      <div className="flex justify-between items-center pt-1 border-t border-border/40 text-2xs">
                        <span>Margin Contribution:</span>
                        <span className="font-medium text-emerald-500">
                          {d.marginPct.toFixed(0)}% ({formatCompactCurrency(d.margin)})
                        </span>
                      </div>
                    </div>
                  </div>
                );
              }}
            />

            {(viewMode === "combined" || viewMode === "revenue") && (
              <Bar
                yAxisId="left"
                dataKey="revenue"
                name="Revenue"
                fill="url(#revenueBarGradient)"
                radius={[6, 6, 0, 0]}
                maxBarSize={38}
              />
            )}

            {(viewMode === "combined" || viewMode === "units") && (
              <Bar
                yAxisId={viewMode === "units" ? "right" : "right"}
                dataKey="units"
                name="Units Sold"
                fill="url(#unitsBarGradient)"
                radius={[6, 6, 0, 0]}
                maxBarSize={38}
              />
            )}
          </BarChart>
        </ResponsiveContainer>
      </div>

      {/* Mini Product Performance Rank Cards */}
      <div className="grid grid-cols-2 sm:grid-cols-3 gap-2.5 pt-1">
        {topItems.slice(0, 3).map((p, idx) => (
          <div
            key={p.product_id || p.name}
            className="rounded-xl border border-border/60 bg-muted/30 p-2.5 space-y-1 hover:border-primary/40 transition-colors"
          >
            <div className="flex items-center justify-between text-2xs text-muted-foreground">
              <span className="font-semibold uppercase tracking-wider text-primary">#{idx + 1} Best</span>
              <span
                className={cn(
                  "font-bold tnum",
                  (p.change_pct ?? 0) >= 0 ? "text-emerald-500" : "text-rose-500",
                )}
              >
                {(p.change_pct ?? 0) >= 0 ? "+" : ""}
                {(p.change_pct ?? 0).toFixed(1)}%
              </span>
            </div>
            <p className="text-xs font-semibold text-foreground truncate">{p.name}</p>
            <div className="flex items-baseline justify-between text-xs tnum">
              <span className="font-bold text-foreground">{formatCompactCurrency(p.revenue)}</span>
              <span className="text-2xs text-muted-foreground">{formatNumber(p.units_sold)} sold</span>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
