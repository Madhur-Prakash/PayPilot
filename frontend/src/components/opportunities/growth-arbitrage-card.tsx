"use client";

/**
 * "Growth Arbitrage": the same incentive dollar producing a different measured
 * return depending on which surface it runs through. Only ever renders a claim
 * once both surfaces have at least one measured campaign - see
 * `GrowthAllocationEngine.growth_arbitrage()`, which returns `null` otherwise.
 * That's why this component has an honest empty state instead of hiding.
 */

import { ArrowRight, Scale, Sparkles } from "lucide-react";
import * as React from "react";

import { CampaignSurfaceBadge, ConfidenceBadge } from "@/components/campaigns/growth-intelligence";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/primitives";
import { useGrowthArbitrage } from "@/hooks/use-api";

export function GrowthArbitrageCard() {
  const { data, isLoading } = useGrowthArbitrage();

  if (isLoading) return null;

  return (
    <Card className="border-info/25 bg-info/[0.03]">
      <CardHeader className="flex-row items-center justify-between space-y-0 pb-2">
        <CardTitle className="flex items-center gap-2 text-base font-semibold">
          <Scale className="h-4 w-4 text-info" />
          Growth Arbitrage
        </CardTitle>
        {data && <ConfidenceBadge confidence={data.confidence} evidenceCount={data.evidence_count} />}
      </CardHeader>
      <CardContent>
        {!data ? (
          <p className="text-sm leading-relaxed text-muted-foreground">
            Not enough measured campaigns yet on both the business and PayPal surfaces to compare
            returns. Once at least one of each has been measured, this will show which surface is
            producing more incremental revenue per dollar spent — and by how much.
          </p>
        ) : (
          <div className="space-y-3">
            <p className="text-sm leading-relaxed">
              <span className="font-medium">
                {data.better_surface === "PAYPAL" ? "PayPal-powered offers" : "Business-side reactivation"}
              </span>{" "}
              is currently producing higher incremental revenue per dollar of incentive than{" "}
              {data.worse_surface === "PAYPAL" ? "PayPal-powered offers" : "business-side reactivation"}.
            </p>
            <div className="grid grid-cols-2 gap-3">
              <SurfaceStat surface={data.better_surface} roi={data.better_roi} best />
              <SurfaceStat surface={data.worse_surface} roi={data.worse_roi} />
            </div>
            <div className="flex items-center gap-2 rounded-lg border border-border/60 bg-card p-2.5 text-xs">
              <Sparkles className="h-3.5 w-3.5 shrink-0 text-primary" />
              <span>
                Shift the next mission&apos;s budget toward{" "}
                <span className="font-medium">{data.recommended_shift_pct.toFixed(0)}%</span>{" "}
                {data.better_surface.toLowerCase()}
              </span>
              <ArrowRight className="ml-auto h-3.5 w-3.5 shrink-0 text-muted-foreground" />
            </div>
          </div>
        )}
      </CardContent>
    </Card>
  );
}

function SurfaceStat({
  surface,
  roi,
  best,
}: {
  surface: "BUSINESS" | "PAYPAL" | "HYBRID";
  roi: number;
  best?: boolean;
}) {
  return (
    <div className="rounded-lg border border-border/60 bg-card p-2.5">
      <CampaignSurfaceBadge surface={surface} className="px-1.5 py-0 text-2xs" />
      <p className={`mt-1.5 text-lg font-bold tabular-nums ${best ? "text-success" : ""}`}>
        {roi.toFixed(1)}x
      </p>
      <p className="text-2xs text-muted-foreground">incremental ROI</p>
    </div>
  );
}
