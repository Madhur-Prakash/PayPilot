"use client";

import { PieChart, Pie, Cell, ResponsiveContainer, Tooltip } from "recharts";
import { formatCompactCurrency, formatNumber, cn } from "@/lib/utils";

interface SegmentItem {
  name: string;
  value: number;
  orders?: number;
  percentage?: number;
  color: string;
}

interface RevenueDonutProps {
  data: { label: string; revenue: number; orders: number; revenue_share_pct: number }[];
  totalRevenue: number;
  height?: number;
}

const PALETTE = [
  "#2563EB", // Vibrant Blue
  "#0284C7", // Sky Blue
  "#F59E0B", // Amber / Orange
  "#10B981", // Emerald
  "#8B5CF6", // Purple
  "#EC4899", // Rose / Pink
];

export function RevenueBreakdownDonut({ data, totalRevenue, height = 220 }: RevenueDonutProps) {
  const segments: SegmentItem[] = data.map((d, i) => ({
    name: d.label.split(" (")[0],
    value: d.revenue,
    orders: d.orders,
    percentage: d.revenue_share_pct || (totalRevenue ? (d.revenue / totalRevenue) * 100 : 0),
    color: PALETTE[i % PALETTE.length],
  }));

  const primarySegment = segments[0];

  return (
    <div className="flex flex-col sm:flex-row items-center gap-6">
      {/* Donut Chart with Center KPI */}
      <div className="relative flex items-center justify-center shrink-0" style={{ width: height, height }}>
        <ResponsiveContainer width="100%" height="100%">
          <PieChart>
            <Pie
              data={segments}
              cx="50%"
              cy="50%"
              innerRadius="64%"
              outerRadius="92%"
              paddingAngle={3}
              dataKey="value"
              stroke="none"
            >
              {segments.map((entry, index) => (
                <Cell key={`cell-${index}`} fill={entry.color} />
              ))}
            </Pie>
            <Tooltip
              content={({ active, payload }) => {
                if (!active || !payload?.length) return null;
                const item = payload[0].payload as SegmentItem;
                return (
                  <div className="rounded-xl border border-border/60 bg-popover/95 p-2.5 shadow-xl backdrop-blur-md text-xs">
                    <div className="flex items-center gap-2 font-medium">
                      <span className="h-2 w-2 rounded-full" style={{ backgroundColor: item.color }} />
                      <span>{item.name}</span>
                    </div>
                    <div className="mt-1 flex items-baseline justify-between gap-3 text-muted-foreground">
                      <span>{formatCompactCurrency(item.value)}</span>
                      <span className="font-semibold text-foreground">
                        {item.percentage?.toFixed(1)}%
                      </span>
                    </div>
                  </div>
                );
              }}
            />
          </PieChart>
        </ResponsiveContainer>

        {/* Center Label */}
        <div className="absolute inset-0 flex flex-col items-center justify-center pointer-events-none text-center">
          <span className="text-xl font-bold tracking-tight text-foreground tnum">
            {primarySegment ? `${primarySegment.percentage?.toFixed(1)}%` : "100%"}
          </span>
          <span className="text-[11px] font-medium text-muted-foreground uppercase tracking-wider">
            {primarySegment ? primarySegment.name : "Total"}
          </span>
        </div>
      </div>

      {/* Legend & Breakdown Bars */}
      <div className="flex-1 w-full space-y-2.5">
        {segments.map((item) => (
          <div key={item.name} className="flex items-center justify-between gap-3 text-xs">
            <div className="flex items-center gap-2 min-w-0">
              <span
                className="h-2.5 w-2.5 rounded-full shrink-0"
                style={{ backgroundColor: item.color }}
              />
              <span className="truncate font-medium text-foreground">{item.name}</span>
            </div>

            <div className="flex items-center gap-3 shrink-0">
              {/* Mini progress bar matching reference screenshot */}
              <div className="w-20 h-1.5 bg-muted rounded-full overflow-hidden hidden sm:block">
                <div
                  className="h-full rounded-full transition-all duration-500"
                  style={{
                    width: `${Math.min(100, Math.max(5, item.percentage || 0))}%`,
                    backgroundColor: item.color,
                  }}
                />
              </div>
              <span className="w-14 text-right font-semibold tnum text-foreground">
                {formatCompactCurrency(item.value)}
              </span>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
