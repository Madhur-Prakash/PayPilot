"use client";

/**
 * AI Recommendations - every Supply Intelligence recommendation with its evidence,
 * estimated impact, confidence and lifecycle (Detected -> Analyzed -> Recommended ->
 * Approved -> Executed -> Measured), and the controls to move it forward.
 */

import { ClipboardList, Sparkles } from "lucide-react";
import * as React from "react";

import { EmptyState, ErrorState, LoadingCard } from "@/components/common/states";
import { AutopilotPanel } from "@/components/discovery/autopilot-panel";
import { RecommendationCard } from "@/components/discovery/recommendation-card";
import { Channel3Setup } from "@/components/discovery/shared";
import { PageHeader } from "@/components/supply/shared";
import { Button } from "@/components/ui/button";
import { useDiscoveryStatus, useGenerateRecommendations, useRecommendations } from "@/hooks/use-discovery";
import { cn } from "@/lib/utils";

const FILTERS: { key: string; label: string; status?: string }[] = [
  { key: "all", label: "All" },
  { key: "RECOMMENDED", label: "Awaiting decision", status: "RECOMMENDED" },
  { key: "APPROVED", label: "Approved", status: "APPROVED" },
  { key: "EXECUTED", label: "Executed", status: "EXECUTED" },
  { key: "MEASURED", label: "Measured", status: "MEASURED" },
  { key: "REJECTED", label: "Rejected", status: "REJECTED" },
];

export default function RecommendationsPage() {
  const [filter, setFilter] = React.useState("all");
  const status = FILTERS.find((f) => f.key === filter)?.status;
  const { data, isLoading, error, refetch } = useRecommendations({ status });
  const discovery = useDiscoveryStatus();
  const generate = useGenerateRecommendations();
  const meta = (data?.meta ?? {}) as { status_counts?: Record<string, number>; can_decide?: boolean; can_generate?: boolean; can_request_purchase?: boolean };
  const counts = meta.status_counts ?? {};
  const items = data?.data ?? [];

  return (
    <div className="space-y-5">
      <PageHeader eyebrow="Supply Intelligence" title="AI Recommendations"
        description="Each recommendation says what was detected, the evidence from your sales and Channel3, the estimated impact (with its assumptions) and how confident the agents are. Nothing happens until a person approves it."
        actions={
          <Button size="sm" className="gap-1.5" loading={generate.isPending} disabled={!meta.can_generate || discovery.data?.configured === false}
            onClick={() => generate.mutate({ days: 30, max_recommendations: 4 })}>
            <Sparkles className="h-3.5 w-3.5" /> Generate recommendations
          </Button>
        } />
      {discovery.data?.configured === false && <Channel3Setup compact />}
      <AutopilotPanel />
      {generate.data?.notes && generate.data.notes.length > 0 && (
        <ul className="space-y-0.5 rounded-xl border border-border bg-muted/30 p-3 text-xs text-muted-foreground">
          {generate.data.notes.map((n) => <li key={n}>• {n}</li>)}
        </ul>
      )}

      <div className="flex flex-wrap gap-1.5" role="tablist" aria-label="Filter recommendations">
        {FILTERS.map((f) => {
          const count = f.status ? counts[f.status] ?? 0 : Object.entries(counts).filter(([k]) => k !== "SUPERSEDED").reduce((a, [, v]) => a + v, 0);
          return (
            <button key={f.key} type="button" role="tab" aria-selected={filter === f.key} onClick={() => setFilter(f.key)}
              className={cn("inline-flex items-center gap-1.5 rounded-lg border px-3 py-1 text-xs font-medium focus-ring",
                filter === f.key ? "border-primary bg-primary text-primary-foreground" : "border-border bg-card hover:bg-muted")}>
              {f.label}
              <span className={cn("rounded px-1 text-2xs tabular-nums", filter === f.key ? "bg-primary-foreground/20" : "bg-muted")}>{count}</span>
            </button>
          );
        })}
      </div>

      {error && <ErrorState error={error} onRetry={() => void refetch()} />}
      {isLoading && <><LoadingCard lines={6} /><LoadingCard lines={6} /></>}
      {!isLoading && items.length === 0 && (
        <EmptyState icon={ClipboardList} title={filter === "all" ? "No recommendations yet" : "Nothing in this state"}
          description={filter === "all" ? "Run the Growth Autopilot or generate recommendations. Each one is built from your sales data and live Channel3 products." : undefined} />
      )}
      <div className="space-y-4">
        {items.map((rec, i) => (
          <RecommendationCard key={rec.id} rec={rec} canDecide={Boolean(meta.can_decide)} canPay={meta.can_request_purchase !== false}
            defaultOpen={i === 0 && rec.status === "RECOMMENDED"} />
        ))}
      </div>
    </div>
  );
}
