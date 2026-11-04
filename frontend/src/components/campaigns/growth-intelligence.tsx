"use client";

/**
 * Shared visual language for Dual-Market Growth Intelligence: the BUSINESS /
 * PAYPAL / HYBRID split that now runs through Campaigns, Experiments, the
 * Opportunity Radar, the Command Center and the Impact Tree.
 *
 * Kept deliberately small and reusable rather than duplicated per page - see
 * `growth-mission-card.tsx` for the larger, page-specific compositions built
 * from these pieces.
 */

import { Building2, Sparkles, Wallet } from "lucide-react";
import * as React from "react";

import { Badge } from "@/components/ui/primitives";
import { cn, formatCompactCurrency } from "@/lib/utils";
import type { CampaignSurface } from "@/types/api";

// --------------------------------------------------------------------------- //
// Surface badge
// --------------------------------------------------------------------------- //
const SURFACE_META: Record<
  CampaignSurface,
  { label: string; icon: typeof Building2; className: string }
> = {
  BUSINESS: {
    label: "Business",
    icon: Building2,
    className: "border-transparent bg-chart-3/14 text-chart-3",
  },
  PAYPAL: {
    label: "PayPal",
    icon: Wallet,
    className: "border-transparent bg-info/14 text-info",
  },
  HYBRID: {
    label: "Hybrid",
    icon: Sparkles,
    className: "border-transparent bg-primary/14 text-primary",
  },
};

export function CampaignSurfaceBadge({
  surface,
  className,
}: {
  surface: CampaignSurface;
  className?: string;
}) {
  const meta = SURFACE_META[surface] ?? SURFACE_META.BUSINESS;
  return (
    <Badge className={cn("gap-1", meta.className, className)}>
      <meta.icon className="h-3 w-3" />
      {meta.label}
    </Badge>
  );
}

// --------------------------------------------------------------------------- //
// Confidence badge - never a fabricated number, always tied to evidence count.
// --------------------------------------------------------------------------- //
export function ConfidenceBadge({
  confidence,
  evidenceCount,
}: {
  confidence: "low" | "medium" | "high";
  evidenceCount?: number;
}) {
  const tone =
    confidence === "high" ? "success" : confidence === "medium" ? "warning" : "muted";
  return (
    <Badge variant={tone} className="capitalize">
      {confidence} confidence
      {typeof evidenceCount === "number" && (
        <span className="ml-1 opacity-70">
          · {evidenceCount} experiment{evidenceCount === 1 ? "" : "s"}
        </span>
      )}
    </Badge>
  );
}

// --------------------------------------------------------------------------- //
// Budget allocation bar - a financial split, not a generic progress bar.
// --------------------------------------------------------------------------- //
export function BudgetAllocationBar({
  businessPct,
  paypalPct,
  businessAmount,
  paypalAmount,
  className,
}: {
  businessPct: number;
  paypalPct: number;
  businessAmount?: number;
  paypalAmount?: number;
  className?: string;
}) {
  return (
    <div className={cn("space-y-1.5", className)}>
      <div className="flex h-2.5 w-full overflow-hidden rounded-full bg-muted">
        <div
          className="h-full bg-chart-3 transition-[width] duration-500"
          style={{ width: `${Math.max(0, Math.min(100, businessPct))}%` }}
        />
        <div
          className="h-full bg-info transition-[width] duration-500"
          style={{ width: `${Math.max(0, Math.min(100, paypalPct))}%` }}
        />
      </div>
      <div className="flex items-center justify-between text-2xs text-muted-foreground">
        <span className="flex items-center gap-1.5">
          <span className="h-1.5 w-1.5 rounded-full bg-chart-3" />
          Business {businessPct.toFixed(0)}%
          {typeof businessAmount === "number" && (
            <span className="tabular-nums">· {formatCompactCurrency(businessAmount)}</span>
          )}
        </span>
        <span className="flex items-center gap-1.5">
          PayPal {paypalPct.toFixed(0)}%
          {typeof paypalAmount === "number" && (
            <span className="tabular-nums">· {formatCompactCurrency(paypalAmount)}</span>
          )}
          <span className="h-1.5 w-1.5 rounded-full bg-info" />
        </span>
      </div>
    </div>
  );
}

// --------------------------------------------------------------------------- //
// Campaign visual - a deterministic, category-aware gradient + icon, never a
// stock photo. Same campaign always renders the same visual, and it never
// depends on an external image host that could go dark mid-demo.
// --------------------------------------------------------------------------- //
const SURFACE_GRADIENT: Record<CampaignSurface, string> = {
  BUSINESS: "linear-gradient(135deg, hsl(var(--chart-3) / 0.85), hsl(var(--chart-3) / 0.45))",
  PAYPAL: "linear-gradient(135deg, hsl(var(--info) / 0.85), hsl(200 90% 45% / 0.55))",
  HYBRID:
    "linear-gradient(135deg, hsl(var(--chart-3) / 0.75) 0%, hsl(var(--primary) / 0.8) 50%, hsl(var(--info) / 0.75) 100%)",
};

export function CampaignVisual({
  surface,
  seed,
  className,
  children,
}: {
  surface: CampaignSurface;
  /** Any stable string (campaign id/name) - only used to place the icon glyph. */
  seed?: string;
  className?: string;
  children?: React.ReactNode;
}) {
  const meta = SURFACE_META[surface] ?? SURFACE_META.BUSINESS;
  return (
    <div
      className={cn("relative flex items-center justify-center overflow-hidden rounded-xl", className)}
      style={{ background: SURFACE_GRADIENT[surface] }}
    >
      <div className="pointer-events-none absolute inset-0 opacity-[0.12] [background-image:radial-gradient(circle_at_1px_1px,white_1px,transparent_0)] [background-size:14px_14px]" />
      <meta.icon className="h-9 w-9 text-white/90 drop-shadow-sm" strokeWidth={1.6} />
      {children}
    </div>
  );
}

// --------------------------------------------------------------------------- //
// "Don't discount" — the moment the AI recommends restraint, not a bigger offer.
// --------------------------------------------------------------------------- //
export function DontDiscountBanner({
  highPropensityPct,
  reasoning,
}: {
  highPropensityPct: number;
  reasoning: string;
}) {
  return (
    <div className="flex items-start gap-3 rounded-xl border border-success/30 bg-success/6 p-3.5">
      <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-success/15 text-success">
        <Sparkles className="h-4 w-4" />
      </div>
      <div className="min-w-0 space-y-1">
        <p className="text-sm font-semibold text-success">Don&apos;t discount this segment</p>
        <p className="text-xs leading-relaxed text-muted-foreground">{reasoning}</p>
        <p className="text-2xs text-muted-foreground/80">
          {highPropensityPct.toFixed(0)}% already order 3+ times without an incentive.
        </p>
      </div>
    </div>
  );
}
