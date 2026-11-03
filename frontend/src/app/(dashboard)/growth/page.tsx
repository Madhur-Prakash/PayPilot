"use client";

import { GitBranch } from "lucide-react";
import * as React from "react";

import { ErrorState, LoadingRows } from "@/components/common/states";
import { RangePicker, useRangeDays } from "@/components/dashboard/range-picker";
import { GrowthGraphView } from "@/components/growth/growth-graph";
import { Card, CardContent } from "@/components/ui/primitives";
import { useGrowthGraph } from "@/hooks/use-api";

export default function GrowthPage() {
  const [days, setDays] = useRangeDays(30);
  const { data, isLoading, error, refetch } = useGrowthGraph(days);

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h2 className="text-xl font-semibold tracking-tight">Growth Graph</h2>
          <p className="text-sm text-muted-foreground">
            How the headline movement decomposes, and what moved alongside it
          </p>
        </div>
        <RangePicker days={days} onChange={setDays} period={data?.period} />
      </div>

      <Card>
        <CardContent className="flex items-start gap-3 p-4">
          <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-primary/10 text-primary">
            <GitBranch className="h-4 w-4" />
          </div>
          <div className="space-y-1">
            <p className="text-sm font-medium">Click any node to see its evidence</p>
            <p className="text-sm leading-relaxed text-muted-foreground">
              The top two levels are arithmetic — revenue really is orders multiplied by average
              order value. Below that, relationships are correlations observed over the same
              window. Independent evidence from a different data source is marked as such.
            </p>
          </div>
        </CardContent>
      </Card>

      {isLoading && <LoadingRows rows={5} />}
      {error && <ErrorState error={error} onRetry={() => void refetch()} />}
      {data && <GrowthGraphView graph={data} />}
    </div>
  );
}
