"use client";

import { ArrowDownRight, ArrowRight, ArrowUpRight, TriangleAlert } from "lucide-react";
import * as React from "react";

import { AnimatedNumber, HoverLift } from "@/components/ui/motion";
import { Badge, Card, CardContent, Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/primitives";
import { cn, formatMetricValue, isImprovement } from "@/lib/utils";
import type { MetricDelta } from "@/types/api";

/**
 * A KPI with its period-over-period delta.
 *
 * Colour follows *meaning*, not direction: `direction` says which way is good for
 * this metric, so a falling service time reads green and a falling repeat rate
 * reads red without the component knowing anything about either.
 */
export function KpiCard({
  metric,
  sparkline,
  className,
}: {
  metric: MetricDelta;
  sparkline?: number[];
  className?: string;
}) {
  const good = isImprovement(metric.change_pct, metric.direction);
  const DeltaIcon =
    metric.change_pct == null || Math.abs(metric.change_pct) < 0.05
      ? ArrowRight
      : metric.change_pct > 0
        ? ArrowUpRight
        : ArrowDownRight;

  const toneClass =
    good === null ? "text-muted-foreground" : good ? "text-success" : "text-destructive";

  return (
    <HoverLift className={className}>
      <Card className="relative overflow-hidden">
        {/* A hairline in the delta's colour: readable at a glance across a KPI row. */}
        <span
          aria-hidden
          className={cn(
            "absolute inset-x-0 top-0 h-0.5",
            good === null ? "bg-border" : good ? "bg-success/70" : "bg-destructive/70",
          )}
        />
        <CardContent className="space-y-3 p-5">
          <div className="flex items-start justify-between gap-2">
            <p className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
              {metric.label}
            </p>
            {metric.is_anomaly && (
              <Tooltip>
                <TooltipTrigger asChild>
                  <span>
                    <Badge variant="warning" className="gap-1">
                      <TriangleAlert className="h-3 w-3" />
                      Anomaly
                    </Badge>
                  </span>
                </TooltipTrigger>
                <TooltipContent>
                  This moved materially more than normal variation for this merchant.
                </TooltipContent>
              </Tooltip>
            )}
          </div>

          <p className="text-[1.75rem] font-semibold leading-none tracking-tight">
            <AnimatedNumber
              value={metric.value}
              format={(n) => formatMetricValue(n, metric.unit, true)}
            />
          </p>

          <div className="flex items-center justify-between gap-2">
            <span className={cn("flex items-center gap-1 text-sm font-medium tnum", toneClass)}>
              <DeltaIcon className="h-3.5 w-3.5" />
              {metric.change_pct == null
                ? "--"
                : `${metric.change_pct >= 0 ? "+" : ""}${metric.change_pct.toFixed(1)}%`}
            </span>
            {metric.previous_value != null && (
              <span className="text-2xs text-muted-foreground tnum">
                from {formatMetricValue(metric.previous_value, metric.unit, true)}
              </span>
            )}
          </div>

          {sparkline && sparkline.length > 1 && (
            <Sparkline values={sparkline} tone={good === false ? "destructive" : "success"} />
          )}
        </CardContent>
      </Card>
    </HoverLift>
  );
}

/** Pure-SVG trend line. No chart library needed for a 40px shape. */
function Sparkline({ values, tone }: { values: number[]; tone: "success" | "destructive" }) {
  const width = 100;
  const height = 26;
  const min = Math.min(...values);
  const max = Math.max(...values);
  const span = max - min || 1;

  const points = values
    .map((value, index) => {
      const x = (index / (values.length - 1)) * width;
      const y = height - ((value - min) / span) * height;
      return `${x.toFixed(2)},${y.toFixed(2)}`;
    })
    .join(" ");

  const stroke = tone === "success" ? "hsl(var(--success))" : "hsl(var(--destructive))";

  return (
    <svg
      viewBox={`0 0 ${width} ${height}`}
      className="h-6 w-full"
      preserveAspectRatio="none"
      aria-hidden
    >
      <polyline
        points={points}
        fill="none"
        stroke={stroke}
        strokeWidth={1.6}
        strokeLinecap="round"
        strokeLinejoin="round"
        vectorEffect="non-scaling-stroke"
        opacity={0.85}
      />
    </svg>
  );
}
