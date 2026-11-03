"use client";

import * as React from "react";
import Link from "next/link";
import { HoverLift } from "@/components/ui/motion";
import { Card, CardContent } from "@/components/ui/primitives";
import { cn, formatCompactCurrency, formatNumber } from "@/lib/utils";

interface FinxStatCardProps {
  title: string;
  subtitle?: string;
  mainValue: string | number;
  progressPct?: number;
  rightRows?: { label: string; value: string | number; dotColor?: string }[];
  href?: string;
  className?: string;
}

export function FinxStatCard({
  title,
  subtitle,
  mainValue,
  progressPct = 65,
  rightRows,
  href,
  className,
}: FinxStatCardProps) {
  const cardContent = (
    <Card className="border-border/70 bg-card hover:border-primary/50 transition-all shadow-sm hover:shadow-md cursor-pointer group">
      <CardContent className="p-4 sm:p-5 flex flex-col justify-between h-full space-y-4">
        {/* Header Row */}
        <div className="flex items-start justify-between gap-2">
          <div>
            <p className="text-xs font-semibold text-muted-foreground uppercase tracking-wider group-hover:text-primary transition-colors">
              {title}
            </p>
            {subtitle && <p className="text-xs font-medium text-foreground mt-0.5">{subtitle}</p>}
          </div>

          {rightRows && rightRows.length > 0 && (
            <div className="space-y-1 text-right shrink-0">
              {rightRows.map((r, i) => (
                <div key={i} className="flex items-center justify-end gap-2 text-xs">
                  {r.dotColor && (
                    <span className="h-2 w-2 rounded-full" style={{ backgroundColor: r.dotColor }} />
                  )}
                  <span className="text-muted-foreground">{r.label}</span>
                  <span className="font-semibold text-foreground tnum">
                    {typeof r.value === "number" ? formatCompactCurrency(r.value) : r.value}
                  </span>
                </div>
              ))}
            </div>
          )}
        </div>

        {/* Progress pill bar */}
        <div className="w-full bg-muted h-2 rounded-full overflow-hidden">
          <div
            className="bg-primary h-full rounded-full transition-all duration-500"
            style={{ width: `${Math.min(100, Math.max(8, progressPct))}%` }}
          />
        </div>

        {/* Bottom Primary Value */}
        <div className="flex items-baseline justify-between pt-1">
          <p className="text-xl sm:text-2xl font-bold tracking-tight text-foreground tnum group-hover:text-primary transition-colors">
            {typeof mainValue === "number" ? formatCompactCurrency(mainValue) : mainValue}
          </p>
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
