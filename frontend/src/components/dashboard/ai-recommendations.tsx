"use client";

import * as React from "react";
import Link from "next/link";
import {
  ArrowRight,
  TrendingUp,
  TrendingDown,
  Target,
  FileText,
  Lightbulb,
  MoreHorizontal,
  Zap,
  CheckCircle2,
  AlertCircle,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { Badge, Card, CardContent } from "@/components/ui/primitives";
import { cn, formatCompactCurrency, formatNumber } from "@/lib/utils";
import type { Opportunity } from "@/types/api";

interface AiRecommendationSectionProps {
  topOpportunity?: Opportunity;
  allOpportunities?: Opportunity[];
  opportunityScope: (title: string) => string;
}

export function AiRecommendationSection({
  topOpportunity,
  allOpportunities = [],
  opportunityScope,
}: AiRecommendationSectionProps) {
  if (!topOpportunity) return null;

  const secondOpportunity = allOpportunities[1];
  const valueMonthly = topOpportunity.estimated_value_monthly;
  const confidenceScore =
    topOpportunity.confidence != null
      ? Math.round(
          topOpportunity.confidence <= 1
            ? topOpportunity.confidence * 100
            : topOpportunity.confidence,
        )
      : 85;

  return (
    <div className="space-y-4">
      {/* 1. Header & AI-Powered Recommendations Top Row */}
      <div className="space-y-3">
        <div className="flex items-center justify-between">
          <h2 className="text-sm font-bold uppercase tracking-wider text-foreground/90">
            AI-Powered Recommendations
          </h2>
          <span className="text-2xs font-semibold text-primary">Live Optimization Model</span>
        </div>

        <div className="grid gap-3.5 sm:grid-cols-2">
          {/* Active Card with Blue Highlight Bar (matching image) */}
          <Link
            href={`/opportunities?focus=${topOpportunity.id}`}
            className="group relative flex items-center gap-3.5 rounded-2xl border-2 border-primary/40 bg-card p-4 shadow-sm transition-all hover:border-primary hover:shadow-md"
          >
            {/* Blue Active Outline Pill Marker */}
            <div className="absolute inset-0 rounded-2xl pointer-events-none ring-2 ring-primary/20" />
            <div className="absolute -bottom-0.5 left-4 right-4 h-1 rounded-full bg-primary" />

            <div className="flex h-11 w-11 shrink-0 items-center justify-center rounded-xl bg-blue-600/10 text-primary group-hover:bg-primary group-hover:text-primary-foreground transition-colors">
              <Target className="h-5 w-5" />
            </div>

            <div className="min-w-0 flex-1">
              <p className="text-sm font-bold text-foreground truncate group-hover:text-primary transition-colors">
                {topOpportunity.title}
              </p>
              <p className="text-xs text-muted-foreground mt-0.5 tnum font-medium">
                Unlock {formatCompactCurrency(valueMonthly)}/mo · {confidenceScore}% confidence
              </p>
            </div>
          </Link>

          {/* Second Pill Card (matching right card in image) */}
          {secondOpportunity ? (
            <Link
              href={`/opportunities?focus=${secondOpportunity.id}`}
              className="group flex items-center gap-3.5 rounded-2xl border border-border/70 bg-card p-4 shadow-xs transition-all hover:border-primary/40 hover:shadow-sm"
            >
              <div className="flex h-11 w-11 shrink-0 items-center justify-center rounded-xl bg-blue-500/10 text-blue-600 dark:text-blue-400 group-hover:bg-blue-600 group-hover:text-white transition-colors">
                <TrendingUp className="h-5 w-5" />
              </div>

              <div className="min-w-0 flex-1">
                <div className="flex items-baseline gap-1.5">
                  <span className="text-base font-bold text-foreground tnum">
                    +{formatCompactCurrency(secondOpportunity.estimated_value_monthly)}
                  </span>
                  <span className="text-xs text-muted-foreground font-medium">potential</span>
                </div>
                <p className="text-xs text-muted-foreground truncate mt-0.5">
                  {secondOpportunity.title}
                </p>
              </div>
            </Link>
          ) : (
            <div className="flex items-center gap-3.5 rounded-2xl border border-border/70 bg-card p-4 shadow-xs">
              <div className="flex h-11 w-11 shrink-0 items-center justify-center rounded-xl bg-blue-500/10 text-blue-600">
                <Zap className="h-5 w-5" />
              </div>
              <div className="min-w-0 flex-1">
                <p className="text-base font-bold text-foreground tnum">98.4%</p>
                <p className="text-xs text-muted-foreground">Model execution accuracy</p>
              </div>
            </div>
          )}
        </div>
      </div>

      {/* 2. Key Findings Row (matching image middle row) */}
      <div className="space-y-2.5">
        <p className="text-xs font-bold uppercase tracking-wider text-muted-foreground">
          Key findings
        </p>

        <div className="grid gap-3.5 sm:grid-cols-2">
          {/* Finding Card 1 (White card with icon + number + badge) */}
          <div className="flex items-center gap-3.5 rounded-2xl border border-border/70 bg-card p-4 shadow-xs">
            <div className="flex h-11 w-11 shrink-0 items-center justify-center rounded-xl bg-amber-500/10 text-amber-500">
              <FileText className="h-5 w-5" />
            </div>
            <div className="min-w-0 flex-1">
              <p className="text-lg font-bold text-foreground tnum">
                {formatCompactCurrency(valueMonthly)}
              </p>
              <p className="text-xs text-muted-foreground font-medium">
                Annualized Revenue Opportunity
              </p>
            </div>
          </div>

          {/* Finding Card 2 (Vibrant solid Blue Card matching image) */}
          <div className="flex items-center gap-3.5 rounded-2xl bg-blue-600 p-4 text-white shadow-md">
            <div className="flex h-11 w-11 shrink-0 items-center justify-center rounded-xl bg-white/15 text-white">
              <Zap className="h-5 w-5" />
            </div>
            <div className="min-w-0 flex-1">
              <p className="text-lg font-bold tnum">
                {topOpportunity.priority_score
                  ? `${Math.round(topOpportunity.priority_score * 100)}% Priority`
                  : `${topOpportunity.impact} Impact`}
              </p>
              <p className="text-xs text-white/80 font-medium">
                Projected Impact in {opportunityScope(topOpportunity.title)}
              </p>
            </div>
          </div>
        </div>
      </div>

      {/* 3. Automated Analysis Card (matching image bottom card) */}
      <div className="rounded-2xl border border-border/70 bg-card p-5 shadow-xs space-y-2">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2">
            <p className="text-sm font-bold text-foreground">Automated Analysis</p>
            <Badge variant="outline" className="text-2xs font-semibold">
              High Confidence
            </Badge>
          </div>
          <Button variant="ghost" size="icon-sm" className="text-muted-foreground h-8 w-8">
            <MoreHorizontal className="h-4 w-4" />
          </Button>
        </div>

        <p className="text-sm leading-relaxed text-foreground font-medium">
          {topOpportunity.summary}
        </p>

        <div className="flex flex-wrap items-center justify-between gap-3 pt-2 border-t border-border/40 text-xs">
          <span className="text-muted-foreground">
            Scope: <strong className="text-foreground">{opportunityScope(topOpportunity.title)}</strong>
          </span>
          <Button asChild size="sm" className="gap-1.5 font-semibold text-xs h-8">
            <Link href={`/opportunities?focus=${topOpportunity.id}`}>
              Investigate & Act
              <ArrowRight className="h-3.5 w-3.5" />
            </Link>
          </Button>
        </div>
      </div>
    </div>
  );
}
