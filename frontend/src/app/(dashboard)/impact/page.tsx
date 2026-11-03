"use client";

/**
 * Impact tree.
 *
 * What we launched → what it moved → the north star → what was measured.
 * Every figure here is read from the same endpoints the rest of the product
 * uses; nothing on this page is computed in the browser beyond formatting.
 */

import { ArrowLeft, Megaphone, TestTubeDiagonal } from "lucide-react";
import Link from "next/link";
import * as React from "react";

import { ErrorState, LoadingRows } from "@/components/common/states";
import { RangePicker, useRangeDays } from "@/components/dashboard/range-picker";
import { ImpactTree, type TreeCard, type TreeEdge } from "@/components/impact/impact-tree";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/primitives";
import { useCampaigns, useDashboard, useExperiments, useGrowthAllocation } from "@/hooks/use-api";
import { formatCompactCurrency, formatPercent } from "@/lib/utils";

const COLUMNS = ["Initiatives", "Input metrics", "North star", "Measured outcome"];

export default function ImpactPage() {
  const [days, setDays] = useRangeDays(30);
  const dashboard = useDashboard(days);
  const campaigns = useCampaigns({});
  const experiments = useExperiments({});
  const allocation = useGrowthAllocation();

  const isLoading = dashboard.isLoading || campaigns.isLoading || experiments.isLoading;
  const error = dashboard.error ?? campaigns.error ?? experiments.error;

  const { cards, edges } = React.useMemo(() => {
    const cards: TreeCard[] = [];
    const edges: TreeEdge[] = [];
    if (!dashboard.data) return { cards, edges };

    const kpi = (key: string) => dashboard.data.kpis.find((k) => k.key === key);

    // ---- column 0: the initiatives on record
    const campaignItems = campaigns.data?.items ?? [];
    const experimentItems = experiments.data?.items ?? [];

    for (const campaign of campaignItems.slice(0, 3)) {
      const id = `campaign-${campaign.id}`;
      cards.push({
        id,
        column: 0,
        title: campaign.name,
        subtitle: `Campaign · ${campaign.surface.toLowerCase()} · ${campaign.channel.replace("_", " ")}`,
        progress: progressForCampaign(campaign.status),
        status: statusChip(campaign.status),
      });
      edges.push({ from: id, to: "metric-orders", kind: "correlates_with" });
    }

    for (const experiment of experimentItems.slice(0, 3)) {
      const id = `experiment-${experiment.id}`;
      cards.push({
        id,
        column: 0,
        title: experiment.name,
        subtitle: `Experiment · ${experiment.duration_days} days`,
        progress: progressForExperiment(experiment.status),
        status: statusChip(experiment.status),
      });
      edges.push({ from: id, to: "metric-repeat", kind: "correlates_with" });
    }

    // ---- column 1: the input metrics revenue decomposes into
    const orders = kpi("orders");
    const aov = kpi("aov");
    const repeat = kpi("repeat_rate");

    cards.push({
      id: "metric-orders",
      column: 1,
      title: "Orders",
      subtitle: "Transactions in the window",
      value: orders ? orders.value.toLocaleString("en-IN") : "—",
      changePct: orders?.change_pct ?? null,
    });
    cards.push({
      id: "metric-aov",
      column: 1,
      title: "Average order value",
      subtitle: "Revenue per transaction",
      value: aov ? formatCompactCurrency(aov.value) : "—",
      changePct: aov?.change_pct ?? null,
    });
    cards.push({
      id: "metric-repeat",
      column: 1,
      title: "Repeat rate",
      subtitle: "Customers who came back",
      value: repeat ? formatPercent(repeat.value) : "—",
      changePct: repeat?.change_pct ?? null,
    });

    // Revenue is literally orders x AOV, so those two edges are arithmetic.
    edges.push({ from: "metric-orders", to: "northstar", kind: "decomposes_into" });
    edges.push({ from: "metric-aov", to: "northstar", kind: "decomposes_into" });
    edges.push({ from: "metric-repeat", to: "northstar", kind: "correlates_with" });

    // ---- column 2: the north star
    const revenue = kpi("revenue");
    cards.push({
      id: "northstar",
      column: 2,
      tone: "northstar",
      title: "Revenue",
      subtitle: `North star · ${dashboard.data.period.days} days`,
      value: revenue ? formatCompactCurrency(revenue.value) : "—",
      changePct: revenue?.change_pct ?? null,
    });

    // ---- column 3: what the experiments actually measured
    const measured = experimentItems.filter((e) => e.results.length > 0);
    const incremental = measured.reduce(
      (sum, e) => sum + (e.results.find((r) => r.variant_role === "TEST")?.incremental_revenue ?? 0),
      0,
    );
    const decided = measured.filter((e) => e.decision === "SCALE").length;

    cards.push({
      id: "outcome-incremental",
      column: 3,
      title: "Incremental revenue",
      subtitle: "Test minus held-out control",
      value: measured.length ? formatCompactCurrency(incremental) : "—",
    });
    cards.push({
      id: "outcome-decisions",
      column: 3,
      title: "Scale decisions",
      subtitle: `${measured.length} experiment${measured.length === 1 ? "" : "s"} measured`,
      value: measured.length ? `${decided} of ${measured.length}` : "—",
    });

    edges.push({ from: "northstar", to: "outcome-incremental", kind: "evidenced_by" });
    edges.push({ from: "northstar", to: "outcome-decisions", kind: "evidenced_by" });

    return { cards, edges };
  }, [dashboard.data, campaigns.data, experiments.data]);

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <div className="mb-1 flex items-center gap-2">
            <Button asChild variant="ghost" size="sm" className="-ml-2 gap-1.5">
              <Link href="/campaigns">
                <ArrowLeft className="h-3.5 w-3.5" />
                Campaigns
              </Link>
            </Button>
            <Button asChild variant="ghost" size="sm" className="gap-1.5">
              <Link href="/experiments">
                <TestTubeDiagonal className="h-3.5 w-3.5" />
                Experiments
              </Link>
            </Button>
          </div>
          <h2 className="text-xl font-semibold tracking-tight">Impact tree</h2>
          <p className="text-sm text-muted-foreground">
            What you launched, what it moved, and what the control group proved
          </p>
        </div>
        <RangePicker days={days} onChange={setDays} />
      </div>

      {isLoading && <LoadingRows rows={5} />}
      {error && (
        <ErrorState
          error={error}
          onRetry={() => {
            void dashboard.refetch();
            void campaigns.refetch();
            void experiments.refetch();
          }}
        />
      )}

      {!isLoading && !error && (
        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-base">Growth chain</CardTitle>
            <p className="text-sm text-muted-foreground">
              Edges are typed. Only an experiment establishes that acting on one of these moves
              another — the tree shows structure and co-movement, never cause.
            </p>
          </CardHeader>
          <CardContent>
            <ImpactTree cards={cards} edges={edges} columnLabels={COLUMNS} />
          </CardContent>
        </Card>
      )}

      {!isLoading && !error && (campaigns.data?.items.length ?? 0) === 0 && (
        <Card>
          <CardContent className="flex flex-wrap items-center justify-between gap-3 p-4">
            <p className="text-sm text-muted-foreground">
              No campaigns yet, so the left column is empty.
            </p>
            <Button asChild variant="outline" size="sm" className="gap-1.5">
              <Link href="/campaigns">
                <Megaphone className="h-3.5 w-3.5" />
                Create one
              </Link>
            </Button>
          </CardContent>
        </Card>
      )}
    </div>
  );
}

/** Campaign lifecycle expressed as rough completion, for the progress bar. */
function progressForCampaign(status: string): number {
  return (
    {
      DRAFT: 10,
      PENDING_APPROVAL: 25,
      APPROVED: 45,
      SCHEDULED: 55,
      RUNNING: 75,
      PAUSED: 60,
      COMPLETED: 100,
      REJECTED: 0,
      CANCELLED: 0,
    }[status] ?? 0
  );
}

function progressForExperiment(status: string): number {
  return (
    {
      DRAFT: 10,
      PENDING_APPROVAL: 25,
      RUNNING: 65,
      COMPLETED: 100,
      REJECTED: 0,
      CANCELLED: 0,
    }[status] ?? 0
  );
}

function statusChip(status: string): TreeCard["status"] {
  const label = status.toLowerCase().replace("_", " ");
  if (status === "COMPLETED") return { label, tone: "success" };
  if (status === "RUNNING") return { label, tone: "info" };
  if (status === "PENDING_APPROVAL") return { label, tone: "warning" };
  if (status === "REJECTED" || status === "CANCELLED") return { label, tone: "destructive" };
  return { label, tone: "muted" };
}
