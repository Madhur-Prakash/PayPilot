"use client";

/**
 * The inventory-expansion opportunity Supply Intelligence detected in the merchant's own
 * sales - shown on the Command Center so the merchant sees it first. No Channel3 call.
 */

import { ArrowRight, Compass, Lightbulb } from "lucide-react";
import Link from "next/link";

import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/primitives";
import { useSupplyIntel } from "@/hooks/use-discovery";
import { useAuthStore } from "@/stores/auth";

function Banner() {
  const { data } = useSupplyIntel(30);
  const top = data?.top_opportunity;
  if (!top) return null;
  const growth = top.anchor.units_growth_pct;
  const open = data.kpis.open_recommendations;
  return (
    <Card className="overflow-hidden border-primary/30 bg-primary/[0.04]">
      <CardContent className="flex flex-wrap items-center gap-4 p-4">
        <span className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-primary text-primary-foreground"><Compass className="h-5 w-5" /></span>
        <div className="min-w-0 flex-1">
          <p className="text-2xs font-semibold uppercase tracking-widest text-primary">Supply Intelligence · expansion opportunity</p>
          <p className="text-sm font-semibold">
            {top.anchor.buyers} customers bought {top.anchor.name}{growth != null && growth > 0 ? ` (demand +${growth.toFixed(0)}%)` : ""} - they also need {top.slot.label.toLowerCase()}, which you don&apos;t stock.
          </p>
          <p className="text-xs text-muted-foreground">
            {open > 0 ? <><Lightbulb className="mr-1 inline h-3 w-3" />{open} recommendation(s) are waiting for your decision.</> : "Explore it with live Channel3 products, or let the Growth Autopilot prepare a recommendation."}
          </p>
        </div>
        <div className="flex flex-wrap gap-2">
          {open > 0 && <Button asChild size="sm" variant="outline"><Link href="/recommendations">Review</Link></Button>}
          <Button asChild size="sm" className="gap-1.5"><Link href="/supply/intelligence">Open Supply Intelligence <ArrowRight className="h-3.5 w-3.5" /></Link></Button>
        </div>
      </CardContent>
    </Card>
  );
}

export function SupplyOpportunityBanner() {
  const allowed = useAuthStore((s) => s.can("products:read"));
  return allowed ? <Banner /> : null;
}
