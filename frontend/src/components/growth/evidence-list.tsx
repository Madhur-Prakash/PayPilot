"use client";

import { BarChart3, ExternalLink, MessageSquareQuote, Swords, Globe } from "lucide-react";
import Link from "next/link";
import * as React from "react";

import { Badge } from "@/components/ui/primitives";
import { cn } from "@/lib/utils";
import type { EvidenceItem } from "@/types/api";

const SOURCE_META: Record<
  string,
  { icon: typeof BarChart3; label: string; className: string; href?: string }
> = {
  analytics: {
    icon: BarChart3,
    label: "Transactions",
    className: "text-chart-1",
    href: "/dashboard",
  },
  reviews: {
    icon: MessageSquareQuote,
    label: "Reviews",
    className: "text-chart-3",
    href: "/reviews",
  },
  competitors: { icon: Swords, label: "Competitors", className: "text-chart-4", href: "/competitors" },
  experiments: { icon: BarChart3, label: "Experiments", className: "text-chart-2", href: "/experiments" },
  signals: { icon: Globe, label: "Market", className: "text-chart-5" },
};

/**
 * Evidence rows.
 *
 * Each row names its source, because the strength of a hypothesis here comes from
 * *independent* corroboration: a transaction metric and a review metric moving
 * together mean far more than two views of the same number.
 */
export function EvidenceList({
  evidence,
  className,
  dense = false,
}: {
  evidence: EvidenceItem[];
  className?: string;
  dense?: boolean;
}) {
  if (!evidence.length) {
    return (
      <p className={cn("text-sm text-muted-foreground", className)}>
        No supporting evidence was recorded for this item.
      </p>
    );
  }

  const sources = new Set(evidence.map((item) => item.source));

  return (
    <div className={cn("space-y-2", className)}>
      {evidence.map((item, index) => {
        const meta = SOURCE_META[item.source] ?? {
          icon: BarChart3,
          label: item.source,
          className: "text-muted-foreground",
        };
        const Icon = meta.icon;
        const negative = item.change?.startsWith("-");

        return (
          <div
            key={index}
            className={cn(
              "flex items-start gap-3 rounded-lg border border-border bg-card",
              dense ? "px-3 py-2" : "p-3",
            )}
          >
            <Icon className={cn("mt-0.5 h-4 w-4 shrink-0", meta.className)} />
            <div className="min-w-0 flex-1">
              <div className="flex flex-wrap items-baseline gap-x-2 gap-y-0.5">
                <span className="text-sm font-medium">{item.metric}</span>
                <span className="text-sm tnum">{item.value}</span>
                {item.change && (
                  <span
                    className={cn(
                      "text-xs font-medium tnum",
                      negative ? "text-destructive" : "text-success",
                    )}
                  >
                    {item.change}
                  </span>
                )}
              </div>
              {item.detail && !dense && (
                <p className="mt-0.5 text-xs leading-relaxed text-muted-foreground">
                  {item.detail}
                </p>
              )}
            </div>
            {item.reference && meta.href && (
              <Link
                href={`/${item.reference.split("?")[0]}`}
                className="mt-0.5 shrink-0 rounded p-1 text-muted-foreground transition-colors hover:bg-muted hover:text-foreground focus-ring"
                aria-label={`Open ${meta.label}`}
              >
                <ExternalLink className="h-3.5 w-3.5" />
              </Link>
            )}
          </div>
        );
      })}

      {sources.size > 1 && (
        <p className="pt-1 text-2xs leading-relaxed text-muted-foreground">
          Evidence comes from {sources.size} independent sources. Corroboration across sources is
          what raises confidence — a single metric viewed twice would not.
        </p>
      )}
    </div>
  );
}

export function SourceBadges({ evidence }: { evidence: EvidenceItem[] }) {
  const sources = Array.from(new Set(evidence.map((item) => item.source)));
  return (
    <div className="flex flex-wrap gap-1.5">
      {sources.map((source) => {
        const meta = SOURCE_META[source];
        return (
          <Badge key={source} variant="outline" className="gap-1">
            {meta && <meta.icon className="h-3 w-3" />}
            {meta?.label ?? source}
          </Badge>
        );
      })}
    </div>
  );
}
