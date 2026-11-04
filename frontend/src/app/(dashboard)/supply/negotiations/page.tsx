"use client";

/** Live negotiations: every procurement request, with its round and outcome. */

import { Handshake } from "lucide-react";
import Link from "next/link";
import * as React from "react";

import { EmptyState, ErrorState, LoadingRows } from "@/components/common/states";
import { LifecycleStepper, PageHeader, StatusPill } from "@/components/supply/shared";
import { Card, CardContent } from "@/components/ui/primitives";
import { useProcurements } from "@/hooks/use-supply";
import { cn, formatMoney, formatRelativeTime, toNumber } from "@/lib/utils";

const FILTERS = [
  { key: "all", label: "All" },
  { key: "NEGOTIATING", label: "Negotiating" },
  { key: "AWAITING_APPROVAL", label: "Awaiting approval" },
  { key: "ORDERED", label: "Ordered" },
  { key: "RECONCILED", label: "Reconciled" },
];

export default function NegotiationsPage() {
  const [filter, setFilter] = React.useState("all");
  const { data, isLoading, error, refetch } = useProcurements({ page: 1, page_size: 50, status: filter === "all" ? undefined : filter });
  const items = data?.items ?? [];
  return (
    <div className="space-y-5">
      <PageHeader eyebrow="Supply" title="Live negotiations"
        description="Each card is one Buyer Agent negotiating with independent supplier agents. Open one to watch it live." />
      <div className="flex flex-wrap gap-1.5">
        {FILTERS.map((f) => (
          <button key={f.key} type="button" onClick={() => setFilter(f.key)} aria-pressed={filter === f.key}
            className={cn("rounded-lg border px-3 py-1 text-xs font-medium transition-colors focus-ring",
              filter === f.key ? "border-primary bg-primary text-primary-foreground" : "border-border bg-card hover:bg-muted")}>
            {f.label}
          </button>
        ))}
      </div>
      {error && <ErrorState error={error} onRetry={() => void refetch()} />}
      {isLoading && <LoadingRows rows={4} />}
      {!isLoading && !error && items.length === 0 && (
        <EmptyState icon={Handshake} title="No negotiations yet"
          description="Start one from Reorder Recommendations, or run the procurement autopilot from the Supply Command Center." />
      )}
      <div className="grid gap-3 lg:grid-cols-2">
        {items.map((r) => (
          <Link key={r.procurement_request_id} href={`/supply/negotiations/${r.procurement_request_id}`}>
            <Card className="h-full transition-shadow hover:shadow-md">
              <CardContent className="space-y-3 p-4">
                <div className="flex items-start justify-between gap-3">
                  <div className="min-w-0">
                    <p className="font-mono text-xs text-muted-foreground">{r.reference} · {r.rfq_reference}</p>
                    <p className="truncate font-semibold">{toNumber(r.quantity)} {r.unit} · {r.product_name}</p>
                  </div>
                  <StatusPill status={r.status} />
                </div>
                <div className="grid grid-cols-4 gap-2 text-center text-xs">
                  <Mini label="Suppliers" value={String(r.session_count ?? 0)} />
                  <Mini label="Rounds" value={String(r.max_round ?? 0)} />
                  <Mini label="Budget" value={formatMoney(r.policy.max_budget)} />
                  <Mini label="Savings" value={r.savings_amount ? formatMoney(r.savings_amount) : "--"} />
                </div>
                <LifecycleStepper status={r.status} className="text-[10px]" />
                <p className="text-2xs text-muted-foreground">
                  {r.recommendation?.winner ? `Recommended: ${r.recommendation.winner.supplier_name}. ` : ""}
                  Raised {formatRelativeTime(r.created_at)} by {r.source === "AGENT" ? "Inventory Intelligence" : "a user"}.
                </p>
              </CardContent>
            </Card>
          </Link>
        ))}
      </div>
    </div>
  );
}

function Mini({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-lg bg-muted/50 py-1.5">
      <p className="text-2xs uppercase text-muted-foreground">{label}</p>
      <p className="font-semibold tabular-nums">{value}</p>
    </div>
  );
}
