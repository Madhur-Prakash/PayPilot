"use client";

import {
  ArrowRight,
  CircleDot,
  Gauge,
  Lightbulb,
  Target,
  TrendingUp,
  X,
} from "lucide-react";
import Link from "next/link";

import { useDismissOpportunity } from "@/hooks/use-api";
import * as React from "react";

import { Button } from "@/components/ui/button";
import { HoverLift } from "@/components/ui/motion";
import {
  Badge,
  Card,
  CardContent,
  Progress,
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from "@/components/ui/primitives";
import { cn, formatCompactCurrency } from "@/lib/utils";
import type { Opportunity, OpportunityStatus } from "@/types/api";

/** Status is the growth loop made visible, so each one gets a distinct read. */
export const STATUS_META: Record<
  OpportunityStatus,
  { label: string; variant: "default" | "secondary" | "success" | "warning" | "info" | "muted" | "destructive" }
> = {
  DETECTED: { label: "Detected", variant: "info" },
  INVESTIGATING: { label: "Investigating", variant: "info" },
  RECOMMENDED: { label: "Recommended", variant: "default" },
  APPROVAL_REQUIRED: { label: "Needs approval", variant: "warning" },
  RUNNING: { label: "Running", variant: "default" },
  MEASURING: { label: "Measuring", variant: "info" },
  SCALED: { label: "Scaled", variant: "success" },
  STOPPED: { label: "Stopped", variant: "destructive" },
  DISMISSED: { label: "Dismissed", variant: "muted" },
};

const IMPACT_META = {
  HIGH: { label: "High impact", className: "text-destructive" },
  MEDIUM: { label: "Medium impact", className: "text-warning" },
  LOW: { label: "Low impact", className: "text-muted-foreground" },
} as const;

export function OpportunityCard({
  opportunity,
  rank,
  compact = false,
}: {
  opportunity: Opportunity;
  rank?: number;
  compact?: boolean;
}) {
  const dismiss = useDismissOpportunity();
  const status = STATUS_META[opportunity.status] ?? STATUS_META.DETECTED;
  const impact = IMPACT_META[opportunity.impact] ?? IMPACT_META.MEDIUM;

  return (
    <HoverLift>
      <Card className="group h-full transition-colors hover:border-primary/40">
        <CardContent className="flex h-full flex-col gap-3.5 p-5">
          <div className="flex items-start justify-between gap-3">
            <div className="flex min-w-0 items-start gap-2.5">
              {rank !== undefined && (
                <span className="mt-0.5 flex h-5 w-5 shrink-0 items-center justify-center rounded-md bg-muted text-2xs font-semibold text-muted-foreground">
                  {rank}
                </span>
              )}
              <div className="min-w-0">
                <p className="truncate text-sm font-semibold leading-snug">{opportunity.title}</p>
                <p className={cn("text-2xs font-medium uppercase tracking-wide", impact.className)}>
                  {impact.label}
                </p>
              </div>
            </div>
            <Badge variant={status.variant}>{status.label}</Badge>
          </div>

          {/* The number the merchant cares about, given the most weight on the card. */}
          <div className="flex items-end gap-2">
            <span className="text-2xl font-semibold leading-none tracking-tight tnum">
              {formatCompactCurrency(opportunity.estimated_value_monthly)}
            </span>
            <span className="pb-0.5 text-xs text-muted-foreground">/month</span>
          </div>

          {!compact && (
            <p className="line-clamp-2 text-sm leading-relaxed text-muted-foreground">
              {opportunity.summary}
            </p>
          )}

          <div className="mt-auto space-y-3">
            <div className="space-y-1.5">
              <div className="flex items-center justify-between text-2xs text-muted-foreground">
                <Tooltip>
                  <TooltipTrigger asChild>
                    <span className="flex cursor-help items-center gap-1">
                      <Gauge className="h-3 w-3" />
                      Confidence
                    </span>
                  </TooltipTrigger>
                  <TooltipContent>
                    Computed from the strength of the movement and how many independent sources
                    corroborate it. Not a model score.
                  </TooltipContent>
                </Tooltip>
                <span className="font-medium tnum">
                  {Math.round(opportunity.confidence * 100)}%
                </span>
              </div>
              <Progress
                value={opportunity.confidence * 100}
                className="h-1"
                indicatorClassName={
                  opportunity.confidence >= 0.8
                    ? "bg-success"
                    : opportunity.confidence >= 0.6
                      ? "bg-primary"
                      : "bg-warning"
                }
              />
            </div>

            <div className="flex items-center justify-between gap-2">
              <div className="flex items-center gap-3 text-2xs text-muted-foreground">
                <span className="flex items-center gap-1">
                  <CircleDot className="h-3 w-3" />
                  {opportunity.evidence.length} evidence
                </span>
                <span className="flex items-center gap-1">
                  <Target className="h-3 w-3" />
                  {opportunity.effort.toLowerCase()} effort
                </span>
              </div>
              <div className="flex items-center gap-0.5">
                {/* Only while it is still just a suggestion - once approved or
                    running, removing it from the board would hide work in
                    flight rather than tidy anything up. */}
                {opportunity.status === "DETECTED" && (
                  <Button
                    variant="ghost"
                    size="sm"
                    className="gap-1 text-muted-foreground hover:text-destructive"
                    loading={dismiss.isPending}
                    title="Take this off the board"
                    onClick={() => dismiss.mutate({ id: opportunity.id })}
                  >
                    <X className="h-3.5 w-3.5" />
                    Dismiss
                  </Button>
                )}
                <Button asChild variant="ghost" size="sm" className="-mr-2 gap-1 text-primary">
                  <Link href={`/opportunities?focus=${opportunity.id}`}>
                    Investigate
                    <ArrowRight className="h-3.5 w-3.5 transition-transform group-hover:translate-x-0.5" />
                  </Link>
                </Button>
              </div>
            </div>
          </div>
        </CardContent>
      </Card>
    </HoverLift>
  );
}

/** Compact row used inside the dashboard radar. */
export function OpportunityRow({
  opportunity,
  onSelect,
  selected,
}: {
  opportunity: Opportunity;
  onSelect?: () => void;
  selected?: boolean;
}) {
  const status = STATUS_META[opportunity.status] ?? STATUS_META.DETECTED;
  return (
    <button
      type="button"
      onClick={onSelect}
      className={cn(
        "flex w-full items-center gap-3 rounded-lg border px-3 py-2.5 text-left transition-colors focus-ring",
        selected
          ? "border-primary/50 bg-primary/5"
          : "border-border bg-card hover:border-primary/30 hover:bg-muted/50",
      )}
    >
      <Lightbulb
        className={cn(
          "h-4 w-4 shrink-0",
          opportunity.impact === "HIGH" ? "text-warning" : "text-muted-foreground",
        )}
      />
      <span className="min-w-0 flex-1">
        <span className="block truncate text-sm font-medium">{opportunity.title}</span>
        <span className="block text-2xs text-muted-foreground">
          {Math.round(opportunity.confidence * 100)}% confidence · {opportunity.evidence.length}{" "}
          evidence rows
        </span>
      </span>
      <span className="shrink-0 text-right">
        <span className="block text-sm font-semibold tnum">
          {formatCompactCurrency(opportunity.estimated_value_monthly)}
        </span>
        <Badge variant={status.variant} className="mt-0.5">
          {status.label}
        </Badge>
      </span>
    </button>
  );
}

export function OpportunityRadarSummary({
  count,
  totalValue,
}: {
  count: number;
  totalValue: number;
}) {
  return (
    <div className="flex items-center gap-2 text-sm">
      <TrendingUp className="h-4 w-4 text-primary" />
      <span className="font-medium">{count} opportunities detected</span>
      <span className="text-muted-foreground">
        worth {formatCompactCurrency(totalValue)}/month
      </span>
    </div>
  );
}
