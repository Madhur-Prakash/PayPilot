"use client";

import * as React from "react";
import {
  Area,
  AreaChart,
  CartesianGrid,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { formatCompactCurrency, formatNumber, formatShortDate } from "@/lib/utils";

interface FinxAreaChartProps {
  data: { date: string; value: number; secondary_value?: number | null }[];
  height?: number;
}

export function FinxMultiAreaChart({ data, height = 300 }: FinxAreaChartProps) {
  // Transform data into multiple wavy continuous flow series
  const series = data.map((point) => {
    const revenue = point.value;
    const approved = Math.round(revenue * 0.72);
    const declined = Math.round(revenue * 0.2);
    const filtered = Math.round(revenue * 0.08);

    return {
      date: point.date,
      revenue,
      approved,
      declined,
      filtered,
      orders: point.secondary_value ?? 0,
    };
  });

  return (
    <div className="w-full">
      <ResponsiveContainer width="100%" height={height}>
        <AreaChart data={series} margin={{ top: 12, right: 12, bottom: 0, left: 0 }}>
          <defs>
            {/* Emerald/Teal Layer */}
            <linearGradient id="approvedFlow" x1="0" y1="0" x2="0" y2="1">
              <stop offset="0%" stopColor="#10B981" stopOpacity={0.45} />
              <stop offset="100%" stopColor="#10B981" stopOpacity={0.02} />
            </linearGradient>

            {/* Coral/Rose Layer */}
            <linearGradient id="declinedFlow" x1="0" y1="0" x2="0" y2="1">
              <stop offset="0%" stopColor="#F43F5E" stopOpacity={0.4} />
              <stop offset="100%" stopColor="#F43F5E" stopOpacity={0.02} />
            </linearGradient>

            {/* Amber/Orange Layer */}
            <linearGradient id="filteredFlow" x1="0" y1="0" x2="0" y2="1">
              <stop offset="0%" stopColor="#F59E0B" stopOpacity={0.35} />
              <stop offset="100%" stopColor="#F59E0B" stopOpacity={0.02} />
            </linearGradient>
          </defs>

          <CartesianGrid strokeDasharray="3 3" stroke="hsl(var(--border))" vertical={false} opacity={0.6} />

          <XAxis
            dataKey="date"
            stroke="hsl(var(--muted-foreground))"
            fontSize={11}
            tickLine={false}
            axisLine={false}
            tickFormatter={(value) => formatShortDate(value)}
            minTickGap={28}
          />
          <YAxis
            stroke="hsl(var(--muted-foreground))"
            fontSize={11}
            tickLine={false}
            axisLine={false}
            tickFormatter={(value) => formatCompactCurrency(value)}
            width={62}
          />

          <Tooltip
            content={({ active, payload, label }) => {
              if (!active || !payload?.length) return null;
              return (
                <div className="rounded-2xl border border-border/80 bg-popover/95 p-3.5 shadow-2xl backdrop-blur-xl min-w-[190px]">
                  <p className="text-2xs font-bold uppercase tracking-wider text-muted-foreground pb-2 border-b border-border/50">
                    {formatShortDate(String(label))}
                  </p>
                  <div className="space-y-1.5 pt-2">
                    <div className="flex items-center justify-between text-xs">
                      <span className="flex items-center gap-1.5 text-muted-foreground">
                        <span className="h-2 w-2 rounded-full bg-emerald-500" />
                        Approved
                      </span>
                      <span className="font-semibold text-foreground tnum">
                        {formatCompactCurrency(payload[0]?.value as number)}
                      </span>
                    </div>

                    <div className="flex items-center justify-between text-xs">
                      <span className="flex items-center gap-1.5 text-muted-foreground">
                        <span className="h-2 w-2 rounded-full bg-rose-500" />
                        Declined
                      </span>
                      <span className="font-semibold text-foreground tnum">
                        {formatCompactCurrency(payload[1]?.value as number)}
                      </span>
                    </div>

                    <div className="flex items-center justify-between text-xs">
                      <span className="flex items-center gap-1.5 text-muted-foreground">
                        <span className="h-2 w-2 rounded-full bg-amber-500" />
                        Filtered
                      </span>
                      <span className="font-semibold text-foreground tnum">
                        {formatCompactCurrency(payload[2]?.value as number)}
                      </span>
                    </div>
                  </div>
                </div>
              );
            }}
          />

          <Area
            type="natural"
            dataKey="approved"
            name="Approved"
            stroke="#10B981"
            strokeWidth={2.2}
            fill="url(#approvedFlow)"
          />
          <Area
            type="natural"
            dataKey="declined"
            name="Declined"
            stroke="#F43F5E"
            strokeWidth={2}
            fill="url(#declinedFlow)"
          />
          <Area
            type="natural"
            dataKey="filtered"
            name="Filtered"
            stroke="#F59E0B"
            strokeWidth={1.8}
            fill="url(#filteredFlow)"
          />
        </AreaChart>
      </ResponsiveContainer>
    </div>
  );
}
