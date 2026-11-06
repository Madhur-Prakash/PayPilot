"use client";

/** Subscription revenue radar - every PayPal subscriber's billing history and renewals on Bryntum Scheduler. */

import { AlertTriangle, CalendarClock, LifeBuoy, Radar, Repeat, Wallet } from "lucide-react";
import dynamic from "next/dynamic";
import Link from "next/link";
import * as React from "react";

import { EmptyState, ErrorState, LoadingCard } from "@/components/common/states";
import { MetricTile, PageHeader } from "@/components/supply/shared";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/primitives";
import { useSubscriptionAction, useSubscriptionRadar } from "@/hooks/use-supply";
import { cn, formatMoney } from "@/lib/utils";
import { useAuthStore } from "@/stores/auth";
import type { RadarResource } from "@/types/supply";

// Bryntum reads `window` at import time, so it must never render on the server.
const SubscriptionRadarChart = dynamic(() => import("@/components/finance/subscription-radar"), {
  ssr: false,
  loading: () => <LoadingCard lines={8} />,
});

const WINDOWS = [
  { label: "3 months", back: 90, ahead: 45 },
  { label: "6 months", back: 180, ahead: 60 },
  { label: "12 months", back: 365, ahead: 90 },
] as const;

export default function SubscriptionRadarPage() {
  const [windowIndex, setWindowIndex] = React.useState(0);
  const range = WINDOWS[windowIndex]!;
  const radar = useSubscriptionRadar(range.back, range.ahead);
  const action = useSubscriptionAction();
  const canManage = useAuthStore((s) => s.can("paypal:manage"));
  const summary = radar.data?.summary;

  const recover = (resource: RadarResource) =>
    action.mutate({ id: resource.id, action: "recover", reason: "Recovered from the revenue radar" });

  return (
    <div className="min-w-0 space-y-5">
      <PageHeader
        eyebrow="Finance"
        title="Subscription revenue radar"
        description="Every PayPal subscriber on one timeline: the charges PayPal collected, the ones that failed and its retries, and the renewals coming up. Spot revenue about to slip before it does."
        actions={
          <Button asChild size="sm" variant="outline" className="gap-1.5">
            <Link href="/finance/subscriptions"><Repeat className="h-3.5 w-3.5" /> Subscription list</Link>
          </Button>
        }
      />

      {radar.error && <ErrorState error={radar.error} onRetry={() => void radar.refetch()} />}

      {summary && summary.subscribers > 0 && (
        <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
          <MetricTile icon={Wallet} tone="success" label="Monthly recurring revenue"
            value={formatMoney(summary.monthly_recurring_revenue)} hint={`${summary.active} active subscribers`} />
          <MetricTile icon={CalendarClock} tone="primary" label="Renewing in 30 days"
            value={formatMoney(summary.projected_next_30_days)} hint={`${summary.renewals_next_7_days} renewals this week`} />
          <MetricTile icon={AlertTriangle} tone={summary.at_risk ? "warning" : "default"} label="Revenue at risk"
            value={formatMoney(summary.at_risk_revenue)} hint={`${summary.at_risk} subscribers with failed payments`} />
          <MetricTile icon={LifeBuoy} tone="success" label="Recovered"
            value={summary.recovered} hint={`${formatMoney(summary.collected_in_window)} collected in view`} />
        </div>
      )}

      {radar.isLoading && <LoadingCard lines={8} />}

      {radar.data && radar.data.summary.subscribers === 0 && (
        <EmptyState icon={Radar} title="No subscriptions yet"
          description="Subscriptions appear here once a customer subscribes to a PayPal plan." />
      )}

      {radar.data && radar.data.summary.subscribers > 0 && (
        <Card className="min-w-0 overflow-hidden">
          <CardContent className="min-w-0 space-y-3 p-4">
            <div className="flex flex-wrap items-center justify-between gap-2">
              <div>
                <h2 className="text-sm font-semibold">Billing timeline</h2>
                <p className="text-xs text-muted-foreground">
                  Sorted by risk: suspended first, then failed payments, then healthy renewals.
                </p>
              </div>
              <div role="group" aria-label="Window" className="inline-flex rounded-lg border border-border bg-muted/40 p-0.5">
                {WINDOWS.map((w, i) => (
                  <button key={w.label} type="button" aria-pressed={windowIndex === i} onClick={() => setWindowIndex(i)}
                    className={cn(
                      "rounded-md px-2.5 py-1 text-xs font-medium transition-colors focus-ring",
                      windowIndex === i ? "bg-card text-foreground shadow-sm" : "text-muted-foreground hover:text-foreground",
                    )}>
                    {w.label}
                  </button>
                ))}
              </div>
            </div>
            <SubscriptionRadarChart radar={radar.data} onRecover={recover} canManage={canManage}
              recovering={action.isPending} />
          </CardContent>
        </Card>
      )}
    </div>
  );
}
