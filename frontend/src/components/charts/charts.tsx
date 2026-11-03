"use client";

/**
 * Chart set.
 *
 * Shared conventions so every chart in the product reads the same way:
 *  - one categorical palette from the CSS variables (works in both themes),
 *  - Indian-format currency/number ticks,
 *  - a single tooltip component,
 *  - light grids and no chart junk; the data carries the meaning.
 */

import * as React from "react";
import {
  Area,
  AreaChart,
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  Legend,
  Line,
  LineChart,
  PolarAngleAxis,
  PolarGrid,
  PolarRadiusAxis,
  Radar,
  RadarChart,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

import { cn, formatCompactCurrency, formatNumber, formatShortDate } from "@/lib/utils";

export const CHART_COLORS = [
  "hsl(var(--chart-1))",
  "hsl(var(--chart-2))",
  "hsl(var(--chart-3))",
  "hsl(var(--chart-4))",
  "hsl(var(--chart-5))",
  "hsl(var(--chart-6))",
];

const AXIS_PROPS = {
  stroke: "hsl(var(--muted-foreground))",
  fontSize: 11,
  tickLine: false,
  axisLine: false,
} as const;

function ChartTooltip({
  active,
  payload,
  label,
  valueFormatter,
  labelFormatter,
}: {
  active?: boolean;
  payload?: { name?: string; value?: number; color?: string; dataKey?: string }[];
  label?: string | number;
  valueFormatter?: (value: number, key?: string) => string;
  labelFormatter?: (label: string | number) => string;
}) {
  if (!active || !payload?.length) return null;
  return (
    <div className="rounded-lg border border-border bg-popover px-3 py-2 shadow-lifted">
      {label !== undefined && (
        <p className="mb-1 text-2xs font-medium uppercase tracking-wide text-muted-foreground">
          {labelFormatter ? labelFormatter(label) : label}
        </p>
      )}
      <div className="space-y-0.5">
        {payload.map((entry, index) => (
          <div key={index} className="flex items-center gap-2 text-xs">
            <span
              className="h-2 w-2 shrink-0 rounded-full"
              style={{ backgroundColor: entry.color }}
            />
            <span className="text-muted-foreground">{entry.name}</span>
            <span className="ml-auto font-medium tnum">
              {valueFormatter
                ? valueFormatter(entry.value ?? 0, entry.dataKey)
                : formatNumber(entry.value ?? 0)}
            </span>
          </div>
        ))}
      </div>
    </div>
  );
}

// --------------------------------------------------------------------------- //
// Revenue trend
// --------------------------------------------------------------------------- //
export function RevenueTrendChart({
  data,
  height = 280,
  showOrders = true,
}: {
  data: { date: string; value: number; secondary_value?: number | null }[];
  height?: number;
  showOrders?: boolean;
}) {
  const series = data.map((point) => ({
    date: point.date,
    revenue: point.value,
    orders: point.secondary_value ?? 0,
  }));

  return (
    <ResponsiveContainer width="100%" height={height}>
      <AreaChart data={series} margin={{ top: 8, right: 8, bottom: 0, left: 0 }}>
        <defs>
          <linearGradient id="revenueFill" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor="hsl(var(--chart-1))" stopOpacity={0.28} />
            <stop offset="100%" stopColor="hsl(var(--chart-1))" stopOpacity={0.02} />
          </linearGradient>
        </defs>
        <CartesianGrid strokeDasharray="3 3" stroke="hsl(var(--border))" vertical={false} />
        <XAxis
          dataKey="date"
          {...AXIS_PROPS}
          tickFormatter={(value) => formatShortDate(value)}
          minTickGap={28}
        />
        <YAxis {...AXIS_PROPS} tickFormatter={(value) => formatCompactCurrency(value)} width={62} />
        <Tooltip
          content={
            <ChartTooltip
              labelFormatter={(value) => formatShortDate(String(value))}
              valueFormatter={(value, key) =>
                key === "orders" ? formatNumber(value) : formatCompactCurrency(value)
              }
            />
          }
        />
        <Area
          type="monotone"
          dataKey="revenue"
          name="Revenue"
          stroke="hsl(var(--chart-1))"
          strokeWidth={2}
          fill="url(#revenueFill)"
        />
        {showOrders && (
          <Line
            type="monotone"
            dataKey="orders"
            name="Orders"
            stroke="hsl(var(--chart-2))"
            strokeWidth={1.5}
            dot={false}
            strokeDasharray="4 3"
            yAxisId={0}
          />
        )}
      </AreaChart>
    </ResponsiveContainer>
  );
}

// --------------------------------------------------------------------------- //
// Daypart comparison
// --------------------------------------------------------------------------- //
export function DaypartChart({
  data,
  height = 240,
}: {
  data: { label: string; revenue: number; change_pct: number | null }[];
  height?: number;
}) {
  const series = data.map((row) => ({
    name: row.label.split(" (")[0],
    revenue: row.revenue,
    change: row.change_pct ?? 0,
  }));

  return (
    <ResponsiveContainer width="100%" height={height}>
      <BarChart data={series} margin={{ top: 8, right: 8, bottom: 0, left: 0 }}>
        <CartesianGrid strokeDasharray="3 3" stroke="hsl(var(--border))" vertical={false} />
        <XAxis dataKey="name" {...AXIS_PROPS} />
        <YAxis {...AXIS_PROPS} tickFormatter={(value) => formatCompactCurrency(value)} width={62} />
        <Tooltip
          cursor={{ fill: "hsl(var(--muted))", opacity: 0.5 }}
          content={<ChartTooltip valueFormatter={(value) => formatCompactCurrency(value)} />}
        />
        <Bar dataKey="revenue" name="Revenue" radius={[6, 6, 0, 0]}>
          {/* Colour by whether the slot grew or shrank - the point of this chart. */}
          {series.map((row, index) => (
            <Cell
              key={index}
              fill={row.change < -10 ? "hsl(var(--destructive))" : "hsl(var(--chart-1))"}
              opacity={row.change < -10 ? 0.9 : 0.82}
            />
          ))}
        </Bar>
      </BarChart>
    </ResponsiveContainer>
  );
}

// --------------------------------------------------------------------------- //
// Horizontal product bars
// --------------------------------------------------------------------------- //
export function ProductBarChart({
  data,
  height = 280,
}: {
  data: { name: string; revenue: number; change_pct: number | null }[];
  height?: number;
}) {
  const grown = useGrowOnMount();
  const max = Math.max(...data.map((row) => row.revenue), 1);
  const total = data.reduce((sum, row) => sum + row.revenue, 0) || 1;

  if (data.length === 0) {
    return <p className="py-8 text-center text-sm text-muted-foreground">No product sales yet.</p>;
  }

  return (
    <div className="space-y-3.5" style={{ minHeight: height }}>
      {data.map((row) => {
        const share = (row.revenue / total) * 100;
        const falling = (row.change_pct ?? 0) < -10;
        return (
          <div key={row.name} className="group space-y-1.5">
            <div className="flex items-baseline justify-between gap-3">
              <span className="truncate text-sm font-medium">{row.name}</span>
              <span className="flex shrink-0 items-baseline gap-2">
                <span className="text-sm font-semibold tabular-nums">
                  {formatCompactCurrency(row.revenue)}
                </span>
                <ChangeChip value={row.change_pct} />
              </span>
            </div>

            <div
              className="relative h-2.5 overflow-hidden rounded-full bg-muted"
              title={`${row.name} — ${formatCompactCurrency(row.revenue)}, ${share.toFixed(1)}% of product revenue`}
            >
              <div
                className={cn(
                  "h-full rounded-full transition-[width] duration-700 ease-out",
                  falling
                    ? "bg-gradient-to-r from-destructive/70 to-destructive"
                    : "bg-gradient-to-r from-[hsl(var(--chart-1))] to-[hsl(var(--chart-5))]",
                )}
                style={{ width: grown ? `${Math.max((row.revenue / max) * 100, 2)}%` : "0%" }}
              />
            </div>

            <p className="text-2xs text-muted-foreground tabular-nums opacity-0 transition-opacity group-hover:opacity-100">
              {share.toFixed(1)}% of product revenue
            </p>
          </div>
        );
      })}

      <p className="flex items-center gap-1.5 pt-1 text-2xs text-muted-foreground">
        <span className="inline-block h-2 w-2 rounded-full bg-destructive" />
        Bar turns red when revenue fell more than 10% versus the previous period
      </p>
    </div>
  );
}

/** Direct label for a period-on-period change, so direction is never colour alone. */
function ChangeChip({ value }: { value: number | null }) {
  if (value == null) {
    return <span className="text-2xs text-muted-foreground">new</span>;
  }
  const up = value >= 0;
  return (
    <span
      className={cn(
        "inline-flex items-center gap-0.5 rounded-md px-1.5 py-0.5 text-2xs font-semibold tabular-nums",
        up ? "bg-success/10 text-success" : "bg-destructive/10 text-destructive",
      )}
    >
      {up ? "▲" : "▼"}
      {Math.abs(value).toFixed(1)}%
    </span>
  );
}

/** Bars grow from zero once, on mount. */
function useGrowOnMount() {
  const [grown, setGrown] = React.useState(false);
  React.useEffect(() => {
    const id = requestAnimationFrame(() => setGrown(true));
    return () => cancelAnimationFrame(id);
  }, []);
  return grown;
}

// --------------------------------------------------------------------------- //
// Topic distribution
// --------------------------------------------------------------------------- //
export function TopicBarChart({
  data,
  height = 300,
}: {
  data: { label: string; count: number; negative_count: number }[];
  height?: number;
}) {
  return (
    <ResponsiveContainer width="100%" height={height}>
      <BarChart data={data} layout="vertical" margin={{ top: 4, right: 16, bottom: 4, left: 4 }}>
        <CartesianGrid strokeDasharray="3 3" stroke="hsl(var(--border))" horizontal={false} />
        <XAxis type="number" {...AXIS_PROPS} />
        <YAxis type="category" dataKey="label" {...AXIS_PROPS} width={104} />
        <Tooltip
          cursor={{ fill: "hsl(var(--muted))", opacity: 0.5 }}
          content={<ChartTooltip valueFormatter={(value) => `${formatNumber(value)} reviews`} />}
        />
        <Legend
          wrapperStyle={{ fontSize: 11 }}
          formatter={(value) => <span className="text-muted-foreground">{value}</span>}
        />
        <Bar
          dataKey="count"
          name="All reviews"
          stackId="a"
          fill="hsl(var(--chart-1))"
          opacity={0.28}
          radius={[0, 0, 0, 0]}
        />
        <Bar
          dataKey="negative_count"
          name="Negative"
          stackId="b"
          fill="hsl(var(--destructive))"
          opacity={0.85}
          radius={[0, 6, 6, 0]}
        />
      </BarChart>
    </ResponsiveContainer>
  );
}

// --------------------------------------------------------------------------- //
// Competitor radar
// --------------------------------------------------------------------------- //
export function PerceptionRadar({
  data,
  merchantName,
  height = 320,
}: {
  data: { label: string; merchant_score: number; competitor_avg_score: number }[];
  merchantName: string;
  height?: number;
}) {
  return (
    <ResponsiveContainer width="100%" height={height}>
      <RadarChart data={data} outerRadius="72%">
        <PolarGrid stroke="hsl(var(--border))" />
        <PolarAngleAxis dataKey="label" tick={{ fontSize: 11, fill: "hsl(var(--muted-foreground))" }} />
        <PolarRadiusAxis
          angle={90}
          domain={[0, 100]}
          tick={{ fontSize: 10, fill: "hsl(var(--muted-foreground))" }}
          axisLine={false}
        />
        <Tooltip content={<ChartTooltip valueFormatter={(value) => `${value.toFixed(0)}/100`} />} />
        <Legend
          wrapperStyle={{ fontSize: 11 }}
          formatter={(value) => <span className="text-muted-foreground">{value}</span>}
        />
        <Radar
          name={merchantName}
          dataKey="merchant_score"
          stroke="hsl(var(--chart-1))"
          fill="hsl(var(--chart-1))"
          fillOpacity={0.22}
          strokeWidth={2}
        />
        <Radar
          name="Competitor average (baseline)"
          dataKey="competitor_avg_score"
          stroke="hsl(var(--chart-4))"
          fill="hsl(var(--chart-4))"
          fillOpacity={0.12}
          strokeWidth={2}
          strokeDasharray="4 3"
        />
      </RadarChart>
    </ResponsiveContainer>
  );
}

// --------------------------------------------------------------------------- //
// Rating trend
// --------------------------------------------------------------------------- //
export function RatingTrendChart({
  data,
  height = 220,
}: {
  data: { date: string; value: number }[];
  height?: number;
}) {
  return (
    <ResponsiveContainer width="100%" height={height}>
      <LineChart data={data} margin={{ top: 8, right: 8, bottom: 0, left: 0 }}>
        <CartesianGrid strokeDasharray="3 3" stroke="hsl(var(--border))" vertical={false} />
        <XAxis
          dataKey="date"
          {...AXIS_PROPS}
          tickFormatter={(value) => formatShortDate(value)}
          minTickGap={28}
        />
        <YAxis {...AXIS_PROPS} domain={[1, 5]} width={28} />
        <ReferenceLine y={4} stroke="hsl(var(--success))" strokeDasharray="3 3" opacity={0.45} />
        <Tooltip
          content={
            <ChartTooltip
              labelFormatter={(value) => formatShortDate(String(value))}
              valueFormatter={(value) => value.toFixed(2)}
            />
          }
        />
        <Line
          type="monotone"
          dataKey="value"
          name="Average rating"
          stroke="hsl(var(--chart-2))"
          strokeWidth={2}
          dot={false}
        />
      </LineChart>
    </ResponsiveContainer>
  );
}

// --------------------------------------------------------------------------- //
// Conversion comparison (experiments)
// --------------------------------------------------------------------------- //
export function ConversionCompareChart({
  control,
  test,
  height = 200,
}: {
  control: number;
  test: number;
  height?: number;
}) {
  const grown = useGrowOnMount();
  const max = Math.max(control, test, 0.0001);
  const lift = control > 0 ? ((test - control) / control) * 100 : 0;
  const better = test >= control;

  const rows = [
    { label: "Control", value: control, held: true },
    { label: "Test", value: test, held: false },
  ];

  return (
    <div className="flex flex-col justify-center gap-4" style={{ minHeight: height }}>
      {rows.map((row) => (
        <div key={row.label} className="space-y-1.5">
          <div className="flex items-baseline justify-between gap-3">
            <span className="flex items-center gap-1.5 text-sm font-medium">
              <span
                className={cn(
                  "inline-block h-2 w-2 rounded-full",
                  row.held ? "bg-muted-foreground" : "bg-[hsl(var(--chart-1))]",
                )}
              />
              {row.label}
            </span>
            <span className="text-sm font-semibold tabular-nums">{row.value.toFixed(2)}%</span>
          </div>
          <div className="h-3 overflow-hidden rounded-full bg-muted">
            <div
              className={cn(
                "h-full rounded-full transition-[width] duration-700 ease-out",
                row.held
                  ? "bg-muted-foreground/60"
                  : "bg-gradient-to-r from-[hsl(var(--chart-1))] to-[hsl(var(--chart-5))]",
              )}
              style={{ width: grown ? `${Math.max((row.value / max) * 100, 2)}%` : "0%" }}
            />
          </div>
        </div>
      ))}

      <div className="flex items-center gap-2 rounded-lg border border-border bg-muted/40 px-3 py-2">
        <span
          className={cn(
            "inline-flex items-center gap-0.5 rounded-md px-1.5 py-0.5 text-2xs font-semibold tabular-nums",
            better ? "bg-success/10 text-success" : "bg-destructive/10 text-destructive",
          )}
        >
          {better ? "▲" : "▼"}
          {Math.abs(lift).toFixed(1)}%
        </span>
        <span className="text-2xs leading-snug text-muted-foreground">
          {better ? "Test converted better than" : "Test converted worse than"} the held-out control
        </span>
      </div>
    </div>
  );
}

export function ChartFrame({
  children,
  className,
}: {
  children: React.ReactNode;
  className?: string;
}) {
  return <div className={cn("w-full", className)}>{children}</div>;
}
