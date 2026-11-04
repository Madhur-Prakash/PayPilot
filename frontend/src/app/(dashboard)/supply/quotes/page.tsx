"use client";

/** Quote comparison across negotiations: landed cost, delivery, reliability, margin, policy compliance. */

import { Scale } from "lucide-react";
import Link from "next/link";
import * as React from "react";

import { EmptyState, ErrorState, LoadingRows } from "@/components/common/states";
import { QuoteComparison } from "@/components/supply/quote-comparison";
import { PageHeader, StatusPill } from "@/components/supply/shared";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/primitives";
import { useProcurements } from "@/hooks/use-supply";
import { cn, formatMoney, toNumber } from "@/lib/utils";

export default function QuoteComparisonPage() {
  const { data, isLoading, error, refetch } = useProcurements({ page: 1, page_size: 50 });
  const evaluated = (data?.items ?? []).filter((r) => (r.recommendation?.ranking?.length ?? 0) > 0 || (r.recommendation?.ineligible?.length ?? 0) > 0);
  const [selected, setSelected] = React.useState<string | null>(null);
  const current = evaluated.find((r) => r.procurement_request_id === selected) ?? evaluated[0];

  return (
    <div className="space-y-5">
      <PageHeader eyebrow="Supply" title="Quote comparison"
        description="Final offers scored on landed cost, delivery, reliability, quality, terms and availability - only offers inside the merchant's policy can win." />
      {error && <ErrorState error={error} onRetry={() => void refetch()} />}
      {isLoading && <LoadingRows rows={4} />}
      {!isLoading && evaluated.length === 0 && (
        <EmptyState icon={Scale} title="No evaluated negotiations" description="Quote comparisons appear once a negotiation reaches its recommendation." />
      )}
      {current && (
        <div className="grid gap-4 lg:grid-cols-[260px_1fr]">
          <div className="space-y-1.5">
            {evaluated.map((r) => (
              <button key={r.procurement_request_id} type="button" onClick={() => setSelected(r.procurement_request_id)}
                className={cn("w-full rounded-xl border p-3 text-left text-xs transition-colors focus-ring",
                  current.procurement_request_id === r.procurement_request_id ? "border-primary bg-primary/5" : "border-border bg-card hover:bg-muted")}>
                <div className="flex items-center justify-between"><span className="font-mono font-semibold">{r.reference}</span><StatusPill status={r.status} /></div>
                <p className="mt-0.5 truncate">{toNumber(r.quantity)} × {r.product_name}</p>
              </button>
            ))}
          </div>
          <Card>
            <CardHeader className="pb-2">
              <CardTitle className="text-base">{current.reference}: {current.product_name}</CardTitle>
              <CardDescription>
                Budget {formatMoney(current.policy.max_budget)} · max {formatMoney(current.policy.max_unit_cost)}/unit landed ·
                delivery within {current.policy.max_delivery_days} days ·{" "}
                <Link href={`/supply/negotiations/${current.procurement_request_id}`} className="text-primary hover:underline">open workspace</Link>
              </CardDescription>
            </CardHeader>
            <CardContent className="space-y-3">
              {current.recommendation?.explanation && <p className="text-sm">{current.recommendation.explanation}</p>}
              <QuoteComparison recommendation={current.recommendation} />
            </CardContent>
          </Card>
        </div>
      )}
    </div>
  );
}
