"use client";

import * as React from "react";
import Link from "next/link";
import { Area, AreaChart, ResponsiveContainer, Bar, BarChart } from "recharts";
import { ChevronRight, TrendingUp, TrendingDown } from "lucide-react";
import { HoverLift } from "@/components/ui/motion";
import { Card, CardContent } from "@/components/ui/primitives";
import { cn, formatCompactCurrency, formatNumber } from "@/lib/utils";

interface FinxMiniCardProps {
  title: string;
  value: string | number;
  changeText?: string;
  changeType?: "positive" | "negative" | "neutral";
  chartType?: "area" | "bar";
  chartData?: number[];
  colorTheme?: "emerald" | "rose" | "blue" | "amber";
  href?: string;
  className?: string;
}

export function FinxMiniCard({
  title,
  value,
  changeText,
  changeType = "positive",
  chartType = "area",
  chartData = [20, 35, 25, 45, 30, 60, 55, 75],
  colorTheme = "emerald",
  href,
  className,
}: FinxMiniCardProps) {
  const chartPoints = chartData.map((v, i) => ({ index: i, val: v }));

  const colorConfig = {
    emerald: {
      stroke: "#10B981",
      fill: "url(#emeraldGradient)",
      stop: "#10B981",
      text: "text-emerald-500 dark:text-emerald-400",
      bg: "bg-emerald-500/10",
      bar: "#10B981",
    },
    rose: {
      stroke: "#F43F5E",
      fill: "url(#roseGradient)",
      stop: "#F43F5E",
      text: "text-rose-500 dark:text-rose-400",
      bg: "bg-rose-500/10",
      bar: "#F43F5E",
    },
    blue: {
      stroke: "#3B82F6",
      fill: "url(#blueGradient)",
      stop: "#3B82F6",
      text: "text-blue-500 dark:text-blue-400",
      bg: "bg-blue-500/10",
      bar: "#3B82F6",
    },
    amber: {
      stroke: "#F59E0B",
      fill: "url(#amberGradient)",
      stop: "#F59E0B",
      text: "text-amber-500 dark:text-amber-400",
      bg: "bg-amber-500/10",
      bar: "#F59E0B",
    },
  }[colorTheme];

  const cardContent = (
    <Card className="relative overflow-hidden border-border/70 bg-card hover:border-primary/50 transition-all shadow-sm hover:shadow-md cursor-pointer group">
      <CardContent className="p-4 flex flex-col justify-between h-full">
        <div className="flex items-center justify-between gap-2">
          <span className="text-xs font-semibold text-muted-foreground uppercase tracking-wider truncate group-hover:text-primary transition-colors">
            {title}
          </span>
          <ChevronRight className="h-4 w-4 text-muted-foreground/50 shrink-0 group-hover:translate-x-0.5 group-hover:text-primary transition-all" />
        </div>

        <div className="mt-2 flex items-baseline justify-between gap-2">
          <div className="space-y-1 min-w-0">
            <p className="text-xl font-bold tracking-tight text-foreground tnum group-hover:text-primary transition-colors">
              {typeof value === "number" ? formatCompactCurrency(value) : value}
            </p>
            {changeText && (
              <div className="flex items-center gap-1">
                <span className={cn("text-xs font-semibold tnum", colorConfig.text)}>
                  {changeText}
                </span>
              </div>
            )}
          </div>

          {/* Micro Chart */}
          <div className="h-10 w-24 shrink-0">
            <ResponsiveContainer width="100%" height="100%">
              {chartType === "area" ? (
                <AreaChart data={chartPoints} margin={{ top: 2, right: 0, bottom: 0, left: 0 }}>
                  <defs>
                    <linearGradient id={`${colorTheme}Gradient`} x1="0" y1="0" x2="0" y2="1">
                      <stop offset="0%" stopColor={colorConfig.stop} stopOpacity={0.4} />
                      <stop offset="100%" stopColor={colorConfig.stop} stopOpacity={0.0} />
                    </linearGradient>
                  </defs>
                  <Area
                    type="monotone"
                    dataKey="val"
                    stroke={colorConfig.stroke}
                    strokeWidth={2}
                    fill={colorConfig.fill}
                    isAnimationActive={false}
                  />
                </AreaChart>
              ) : (
                <BarChart data={chartPoints} margin={{ top: 2, right: 0, bottom: 0, left: 0 }}>
                  <Bar
                    dataKey="val"
                    fill={colorConfig.bar}
                    radius={[2, 2, 0, 0]}
                    isAnimationActive={false}
                  />
                </BarChart>
              )}
            </ResponsiveContainer>
          </div>
        </div>
      </CardContent>
    </Card>
  );

  return (
    <HoverLift className={className}>
      {href ? (
        <Link href={href} className="block h-full">
          {cardContent}
        </Link>
      ) : (
        cardContent
      )}
    </HoverLift>
  );
}
