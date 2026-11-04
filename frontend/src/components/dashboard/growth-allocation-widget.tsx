"use client";

/**
 * "Where is your growth budget working?" - the Command Center's compact view
 * onto the Growth Allocation Engine. Real spend and measured incremental
 * revenue, split by surface - see `GrowthAllocationEngine.allocation_snapshot()`.
 */

import { ArrowRight, Wallet } from "lucide-react";
import Link from "next/link";
import * as React from "react";

import { BudgetAllocationBar } from "@/components/campaigns/growth-intelligence";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/primitives";
import { useGrowthAllocation } from "@/hooks/use-api";
import { formatCompactCurrency } from "@/lib/utils";

export function GrowthAllocationWidget() {
  const { data, isLoading } = useGrowthAllocation();

  return (
    <Card className="border-border/70 shadow-sm">
      <CardHeader className="flex-row items-center justify-between space-y-0 pb-2">
        <CardTitle className="flex items-center gap-2 text-base font-bold">
          <Wallet className="h-4 w-4 text-primary" />
          Growth Allocation
        </CardTitle>
        <Link
          href="/campaigns"
          className="flex items-center gap-1 text-2xs font-medium text-primary hover:underline"
        >
          Growth Missions
          <ArrowRight className="h-3 w-3" />
        </Link>
      </CardHeader>
      <CardContent className="space-y-3">
        <p className="text-xs text-muted-foreground">Where your growth budget is working</p>

        {isLoading ? (
          <div className="h-16 animate-pulse rounded-lg bg-muted/50" />
        ) : !data || !data.has_data ? (
          <p className="py-4 text-center text-sm text-muted-foreground">
            No campaigns have launched yet. Once one runs, this shows the real split between
            business and PayPal spend.
          </p>
        ) : (
          <>
            <BudgetAllocationBar
              businessPct={data.business_pct}
              paypalPct={data.paypal_pct}
              businessAmount={data.by_surface.BUSINESS?.spend}
              paypalAmount={data.by_surface.PAYPAL?.spend}
            />
            <div className="grid grid-cols-2 gap-3 pt-1 text-center">
              <div>
                <p className="text-lg font-bold tabular-nums">
                  {formatCompactCurrency(data.total_spend)}
                </p>
                <p className="text-2xs text-muted-foreground">Total committed</p>
              </div>
              <div>
                <p className="text-lg font-bold tabular-nums text-success">
                  {formatCompactCurrency(data.total_incremental_revenue)}
                </p>
                <p className="text-2xs text-muted-foreground">Incremental revenue</p>
              </div>
            </div>
          </>
        )}
      </CardContent>
    </Card>
  );
}
