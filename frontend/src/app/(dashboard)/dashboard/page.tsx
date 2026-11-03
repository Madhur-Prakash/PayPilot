"use client";

/**
 * The Growth Command Center.
 *
 * Laid out to answer the merchant's questions in the order they ask them:
 *   How am I doing?  ->  KPIs
 *   What changed?    ->  trend + segment breakdown
 *   Why?             ->  the growth-graph chain
 *   What do I do?    ->  the AI insight card and the Opportunity Radar
 *   Did it work?     ->  recent experiment results
 */

import { useQuery } from "@tanstack/react-query";
import {
  ArrowRight,
  Clock,
  Lightbulb,
  Loader2,
  TestTubeDiagonal,
  TrendingDown,
  TriangleAlert,
  Zap,
} from "lucide-react";
import Link from "next/link";
import * as React from "react";

import { DaypartChart, ProductBarChart, RevenueTrendChart } from "@/components/charts/charts";
import { FinxMultiAreaChart } from "@/components/charts/finx-multi-area-chart";
import { ProductPerformanceMatrix } from "@/components/charts/product-performance-matrix";
import { RevenueBreakdownDonut } from "@/components/charts/revenue-donut";
import { ErrorState, LoadingChart, LoadingKpis } from "@/components/common/states";
import { AiRecommendationSection } from "@/components/dashboard/ai-recommendations";
import { FinxMiniCard } from "@/components/dashboard/finx-mini-card";
import { FinxStatCard } from "@/components/dashboard/finx-stat-card";
import { GrowthAllocationWidget } from "@/components/dashboard/growth-allocation-widget";
import { KpiCard } from "@/components/dashboard/kpi-card";
import { RangePicker, useRangeDays } from "@/components/dashboard/range-picker";
import { GrowthGraphChain } from "@/components/growth/growth-graph";
import { OpportunityRow } from "@/components/opportunities/opportunity-card";
import { Button } from "@/components/ui/button";
import { FadeIn, LivePulse, Stagger, StaggerItem } from "@/components/ui/motion";
import {
  Badge,
  Card,
  CardContent,
  CardHeader,
  CardTitle,
  Separator,
} from "@/components/ui/primitives";
import { useDashboard, useGrowthGraph, useOpportunities } from "@/hooks/use-api";
import { usePageVoiceContext } from "@/hooks/use-page-voice-context";
import { experimentApi } from "@/lib/api/endpoints";
import { cn, formatCompactCurrency, formatNumber, formatPercent } from "@/lib/utils";
import { useAuthStore } from "@/stores/auth";

export default function DashboardPage() {
  const [days, setDays] = useRangeDays(30);
  const [timeView, setTimeView] = React.useState<"day" | "week" | "month">("month");
  const merchant = useAuthStore((s) => s.user?.active_merchant);

  const dashboard = useDashboard(days);
  const graph = useGrowthGraph(days);
  const opportunities = useOpportunities();
  const experiments = useQuery({
    queryKey: ["experiments", { page: 1 }],
    queryFn: () => experimentApi.list({ page_size: 5 }),
  });

  const topOpportunity = opportunities.data?.opportunities[0];
  const measuredExperiments =
    experiments.data?.items.filter((item) => item.results.length > 0) ?? [];

  const summary = dashboard.data?.summary;
  const prevSummary = dashboard.data?.previous_summary;

  usePageVoiceContext(
    summary
      ? `Revenue ${formatCompactCurrency(summary.revenue)} from ${formatNumber(summary.orders)} orders, average order value ${formatCompactCurrency(summary.aov)}, repeat rate ${summary.repeat_rate.toFixed(1)}%. ${
          opportunities.data
            ? `${opportunities.data.open_count} open opportunities worth ${formatCompactCurrency(opportunities.data.total_estimated_value_monthly)}/month.`
            : ""
        }`
      : null,
  );

  return (
    <div className="space-y-6">
      {/* Header & Quick Filter Banner */}
      <div className="flex flex-wrap items-center justify-between gap-4 border-b border-border/60 pb-4">
        <div>
          <div className="flex items-center gap-2.5">
            <h1 className="text-2xl font-bold tracking-tight text-foreground">
              {merchant?.name ?? "Growth Command Center"}
            </h1>
          </div>
          <p className="text-xs text-muted-foreground mt-0.5">
            {dashboard.data?.headline_insight ?? "Observe · Diagnose · Hypothesize · Act · Measure"}
          </p>
        </div>

        <div className="flex items-center gap-3">
          <RangePicker days={days} onChange={setDays} period={dashboard.data?.period} />
        </div>
      </div>

      {/* Top 4 FinxFlow Style Overview Cards with Progress Bars */}
      {dashboard.isLoading ? (
        <LoadingKpis />
      ) : dashboard.error ? (
        <ErrorState error={dashboard.error} onRetry={() => void dashboard.refetch()} />
      ) : summary ? (
        <Stagger className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
          <StaggerItem>
            <FinxStatCard
              title="Turnover"
              subtitle={`${formatNumber(summary.orders)} Transactions`}
              mainValue={summary.revenue}
              progressPct={78}
              href="/growth"
              rightRows={[
                {
                  label: "Gross Margin",
                  value: summary.gross_margin,
                  dotColor: "#10B981",
                },
                {
                  label: "Discount",
                  value: summary.discount_total,
                  dotColor: "#F43F5E",
                },
              ]}
            />
          </StaggerItem>

          <StaggerItem>
            <FinxStatCard
              title="Repeat Customers"
              subtitle={`${summary.repeat_rate.toFixed(1)}% Loyalty Rate`}
              mainValue={summary.repeat_customers}
              progressPct={summary.repeat_rate}
              href="/customers"
              rightRows={[
                {
                  label: "Unique Visitors",
                  value: formatNumber(summary.unique_customers),
                  dotColor: "#3B82F6",
                },
              ]}
            />
          </StaggerItem>

          <StaggerItem>
            <FinxStatCard
              title="Average Order Value"
              subtitle="Per Checkout Ticket"
              mainValue={summary.aov}
              progressPct={64}
              href="/products"
              rightRows={[
                {
                  label: "Margin %",
                  value: `${summary.gross_margin_pct.toFixed(0)}%`,
                  dotColor: "#8B5CF6",
                },
              ]}
            />
          </StaggerItem>

          <StaggerItem>
            <FinxStatCard
              title="Active Opportunities"
              subtitle={`${opportunities.data?.open_count ?? 0} High-Impact Leads`}
              mainValue={opportunities.data?.total_estimated_value_monthly ?? 0}
              progressPct={85}
              href="/opportunities"
              rightRows={[
                {
                  label: "Radar Items",
                  value: formatNumber(opportunities.data?.opportunities.length ?? 0),
                  dotColor: "#F59E0B",
                },
              ]}
            />
          </StaggerItem>
        </Stagger>
      ) : null}

      {/* AI Growth Scientist Recommendations Section (matching reference card layout) */}
      {topOpportunity && (
        <FadeIn delay={0.08}>
          <AiRecommendationSection
            topOpportunity={topOpportunity}
            allOpportunities={opportunities.data?.opportunities}
            opportunityScope={opportunityScope}
          />
        </FadeIn>
      )}

      {/* Section: Analytics Title */}
      <div className="pt-2 flex items-center justify-between">
        <h2 className="text-xl font-bold tracking-tight text-foreground">Analytics</h2>
        <span className="text-xs text-muted-foreground">Real-time Performance & Segmentation</span>
      </div>

      {/* Main Row: Requests & Flow Chart (Left) + Revenue Breakdown Donut (Right) */}
      <div className="grid gap-5 lg:grid-cols-[minmax(0,1.7fr)_minmax(0,1.1fr)]">
        {/* Wavy Flow Chart */}
        <Card className="border-border/70 shadow-sm">
          <CardHeader className="flex-row items-center justify-between space-y-0 pb-4">
            <div>
              <CardTitle className="text-base font-bold">Revenue Flow & Success Trends</CardTitle>
              <p className="text-xs text-muted-foreground mt-0.5">
                Multi-tier settlement and volume flow over time
              </p>
            </div>

            <div className="flex items-center gap-2">
              <div className="flex items-center rounded-lg bg-muted p-0.5 text-xs font-medium">
                {(["day", "week", "month"] as const).map((mode) => (
                  <button
                    key={mode}
                    type="button"
                    onClick={() => setTimeView(mode)}
                    className={cn(
                      "px-2.5 py-1 rounded-md capitalize transition-all",
                      timeView === mode
                        ? "bg-background text-foreground shadow-sm font-semibold"
                        : "text-muted-foreground hover:text-foreground",
                    )}
                  >
                    {mode}
                  </button>
                ))}
              </div>
            </div>
          </CardHeader>
          <CardContent>
            {dashboard.isLoading ? (
              <LoadingChart height={280} />
            ) : dashboard.data ? (
              <FinxMultiAreaChart data={dashboard.data.revenue_trend} height={280} />
            ) : null}
          </CardContent>
        </Card>

        {/* Donut Revenue Breakdown */}
        <Card className="border-border/70 shadow-sm">
          <CardHeader className="pb-3">
            <CardTitle className="text-base font-bold">Revenue Breakdown</CardTitle>
            <p className="text-xs text-muted-foreground mt-0.5">
              Distribution across trading periods & service channels
            </p>
          </CardHeader>
          <CardContent className="pt-2">
            {dashboard.isLoading ? (
              <LoadingChart height={240} />
            ) : dashboard.data ? (
              <RevenueBreakdownDonut
                data={dashboard.data.daypart_breakdown}
                totalRevenue={dashboard.data.summary.revenue}
                height={200}
              />
            ) : null}
          </CardContent>
        </Card>
      </div>

      {/* 4 Micro Analytics Cards (Approvals, Orders, Average Ticket, Repeat Rate) */}
      {summary && (
        <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
          <FinxMiniCard
            title="Approvals & Net Revenue"
            value={summary.revenue}
            changeText="+8.4% vs prev period"
            changeType="positive"
            chartType="area"
            colorTheme="emerald"
            href="/growth"
            chartData={dashboard.data?.revenue_trend.slice(-8).map((p) => p.value) ?? [30, 45, 60, 50, 70, 85, 90, 110]}
          />

          <FinxMiniCard
            title="Total Orders Processed"
            value={`${formatNumber(summary.orders)} Units`}
            changeText="+12% Since Last Week"
            changeType="positive"
            chartType="bar"
            colorTheme="blue"
            href="/growth"
            chartData={dashboard.data?.orders_trend.slice(-8).map((p) => p.value) ?? [12, 18, 14, 25, 20, 28, 35, 40]}
          />

          <FinxMiniCard
            title="Avg Transaction Amount"
            value={summary.aov}
            changeText="+4.2% Growth"
            changeType="positive"
            chartType="area"
            colorTheme="blue"
            href="/products"
            chartData={[140, 145, 142, 150, 148, 155, 158, 165]}
          />

          <FinxMiniCard
            title="Customer Retention / Churn"
            value={`${summary.repeat_rate.toFixed(1)}%`}
            changeText="-1.4% Inactive Risk"
            changeType="negative"
            chartType="area"
            colorTheme="rose"
            href="/customers"
            chartData={[25, 24, 26, 23, 22, 21, 20, 19]}
          />
        </div>
      )}

      {/* Why: the growth graph chain + trading slot analysis + growth allocation */}
      <div className="grid gap-5 lg:grid-cols-[minmax(0,1fr)_minmax(0,1fr)_minmax(0,0.8fr)]">
        <Card className="border-border/70 shadow-sm">
          <CardHeader className="flex-row items-center justify-between space-y-0">
            <div>
              <CardTitle className="text-base font-bold">Growth Graph Decomposition</CardTitle>
              <p className="text-xs text-muted-foreground">
                How movements connect across metric & segment layers
              </p>
            </div>
            <Button asChild variant="ghost" size="sm" className="gap-1 text-xs">
              <Link href="/growth">
                Explore Graph
                <ArrowRight className="h-3.5 w-3.5" />
              </Link>
            </Button>
          </CardHeader>
          <CardContent className="space-y-3">
            {graph.isLoading ? (
              <LoadingChart height={180} />
            ) : graph.data ? (
              <>
                <GrowthGraphChain graph={graph.data} />
                <Separator />
                <p className="text-2xs leading-relaxed text-muted-foreground">{graph.data.caveat}</p>
              </>
            ) : null}
          </CardContent>
        </Card>

        {/* Opportunity Radar & Active Pipeline */}
        <Card className="border-border/70 shadow-sm">
          <CardHeader className="flex-row items-center justify-between space-y-0">
            <div>
              <CardTitle className="text-base font-bold">Opportunity Radar</CardTitle>
              <p className="text-xs text-muted-foreground">
                {opportunities.data
                  ? `${opportunities.data.open_count} high-confidence opportunities · ${formatCompactCurrency(opportunities.data.total_estimated_value_monthly)}/mo`
                  : "Scanning signals…"}
              </p>
            </div>
            <Button asChild variant="ghost" size="sm" className="text-xs">
              <Link href="/opportunities">View All</Link>
            </Button>
          </CardHeader>
          <CardContent className="space-y-2">
            {opportunities.isLoading && (
              <div className="flex items-center justify-center py-10">
                <Loader2 className="h-5 w-5 animate-spin text-muted-foreground" />
              </div>
            )}
            {opportunities.data?.opportunities.slice(0, 4).map((opportunity) => (
              <Link key={opportunity.id} href={`/opportunities?focus=${opportunity.id}`}>
                <OpportunityRow opportunity={opportunity} />
              </Link>
            ))}
            {opportunities.data?.opportunities.length === 0 && (
              <p className="py-8 text-center text-sm text-muted-foreground">
                No opportunities above the value threshold right now.
              </p>
            )}
          </CardContent>
        </Card>

        <GrowthAllocationWidget />
      </div>

      {/* Product Performance + Anomalies */}
      <div className="grid gap-5 lg:grid-cols-[minmax(0,1.4fr)_minmax(0,1fr)]">
        <Card className="border-border/70 shadow-sm">
          <CardHeader className="flex-row items-center justify-between space-y-0">
            <div>
              <CardTitle className="text-base font-bold">Product Performance & Volume Contribution</CardTitle>
              <p className="text-xs text-muted-foreground">Revenue and volume contribution</p>
            </div>
            <Button asChild variant="ghost" size="sm" className="text-xs">
              <Link href="/products">All Products</Link>
            </Button>
          </CardHeader>
          <CardContent>
            {dashboard.isLoading ? (
              <LoadingChart height={300} />
            ) : dashboard.data?.top_products ? (
              <ProductPerformanceMatrix products={dashboard.data.top_products} height={260} />
            ) : null}
          </CardContent>
        </Card>

        {/* Anomalies */}
        <Card className="border-border/70 shadow-sm">
          <CardHeader>
            <CardTitle className="flex items-center gap-2 text-base font-bold">
              <TriangleAlert className="h-4 w-4 text-warning" />
              Signal Anomalies
            </CardTitle>
            <p className="text-xs text-muted-foreground">
              Movements exceeding standard deviation bounds
            </p>
          </CardHeader>
          <CardContent className="space-y-2.5">
            {dashboard.data?.anomalies.length === 0 && (
              <p className="py-6 text-center text-sm text-muted-foreground">
                Nothing unusual detected in this cycle.
              </p>
            )}
            {dashboard.data?.anomalies.slice(0, 4).map((anomaly) => (
              <div
                key={`${anomaly.metric}-${anomaly.dimension_value}`}
                className="rounded-xl border border-border/70 bg-card p-3 shadow-xs hover:border-primary/40 transition-colors"
              >
                <div className="flex items-start justify-between gap-2">
                  <p className="text-xs font-semibold text-foreground">{anomaly.label}</p>
                  <Badge variant={anomaly.severity === "HIGH" ? "destructive" : "warning"}>
                    {anomaly.severity}
                  </Badge>
                </div>
                <p className="mt-1 text-xs leading-relaxed text-muted-foreground">
                  {anomaly.description}
                </p>
              </div>
            ))}
          </CardContent>
        </Card>
      </div>

      {/* Controlled Experiment Results */}
      <Card className="border-border/70 shadow-sm">
        <CardHeader className="flex-row items-center justify-between space-y-0">
          <div>
            <CardTitle className="flex items-center gap-2 text-base font-bold">
              <TestTubeDiagonal className="h-4 w-4 text-primary" />
              Controlled Experiment Performance
            </CardTitle>
            <p className="text-xs text-muted-foreground">
              Empirically measured lift against held-out merchant cohorts
            </p>
          </div>
          <Button asChild variant="ghost" size="sm" className="text-xs">
            <Link href="/experiments">All Experiments</Link>
          </Button>
        </CardHeader>
        <CardContent>
          {measuredExperiments.length === 0 ? (
            <p className="py-6 text-center text-sm text-muted-foreground">
              No measured experiments yet. Launch a recommended action to begin test-and-learn.
            </p>
          ) : (
            <div className="grid gap-3 md:grid-cols-2">
              {measuredExperiments.slice(0, 4).map((experiment) => {
                const test = experiment.results.find((r) => r.variant_role === "TEST");
                const control = experiment.results.find((r) => r.variant_role === "CONTROL");
                if (!test || !control) return null;
                const lift = test.conversion_lift_pct ?? 0;
                return (
                  <Link
                    key={experiment.id}
                    href={`/experiments?focus=${experiment.id}`}
                    className="rounded-xl border border-border/70 bg-card p-4 transition-all hover:border-primary/50 shadow-xs hover:shadow-sm"
                  >
                    <div className="flex items-start justify-between gap-2">
                      <p className="truncate text-sm font-semibold text-foreground">{experiment.name}</p>
                      <DecisionBadge decision={experiment.decision} />
                    </div>
                    <div className="mt-3 grid grid-cols-3 gap-2 text-center bg-muted/40 p-2.5 rounded-lg">
                      <Stat label="Control" value={formatPercent(control.conversion_rate, 1)} />
                      <Stat label="Test" value={formatPercent(test.conversion_rate, 1)} accent />
                      <Stat
                        label="Lift"
                        value={`${lift >= 0 ? "+" : ""}${lift.toFixed(0)}%`}
                        tone={lift >= 0 ? "success" : "destructive"}
                      />
                    </div>
                    <div className="mt-3 flex items-center justify-between text-2xs text-muted-foreground">
                      <span>
                        Incremental {formatCompactCurrency(test.incremental_revenue ?? 0)}
                      </span>
                      <span className="font-medium text-foreground">ROI {(test.roi ?? 0).toFixed(1)}x</span>
                    </div>
                  </Link>
                );
              })}
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  );
}

function Stat({
  label,
  value,
  accent,
  tone,
}: {
  label: string;
  value: string;
  accent?: boolean;
  tone?: "success" | "destructive";
}) {
  return (
    <div>
      <p className="text-2xs uppercase tracking-wide text-muted-foreground">{label}</p>
      <p
        className={cn(
          "text-sm font-semibold tnum",
          accent && "text-primary",
          tone === "success" && "text-success",
          tone === "destructive" && "text-destructive",
        )}
      >
        {value}
      </p>
    </div>
  );
}

function DecisionBadge({ decision }: { decision: string }) {
  const map: Record<string, "success" | "destructive" | "info" | "warning" | "muted"> = {
    SCALE: "success",
    STOP: "destructive",
    CONTINUE: "info",
    WATCH: "warning",
    PENDING: "muted",
  };
  return <Badge variant={map[decision] ?? "muted"}>{decision}</Badge>;
}

/** Turns "Recover lost evening repeat customers" into "evening customer segment". */
function opportunityScope(title: string): string {
  const lower = title.toLowerCase();
  for (const slot of ["evening", "morning", "afternoon", "night"]) {
    if (lower.includes(slot)) return `${slot} customer segment`;
  }
  if (lower.includes("bundle")) return "product mix";
  return "business";
}
