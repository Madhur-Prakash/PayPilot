"use client";

/**
 * "CREATE GROWTH MISSION" - the demo's centrepiece.
 *
 * `GrowthMissionCard` sits in the Campaigns page's Growth Missions rail: one
 * opportunity, the Growth Allocation Engine's recommended split, and a button
 * that opens `GrowthMissionDialog` - the business-vs-PayPal-vs-hybrid comparison,
 * the don't-discount call (if the data supports it), and the growth-arbitrage
 * note (if there's measured history yet). Choosing an option creates a real
 * campaign through the existing `POST /campaigns` flow - nothing here bypasses
 * approval; a mission is a *draft*, exactly like any other campaign.
 */

import { ArrowRight, Loader2, Sparkles, TrendingDown, Users } from "lucide-react";
import * as React from "react";

import {
  BudgetAllocationBar,
  CampaignSurfaceBadge,
  DontDiscountBanner,
} from "@/components/campaigns/growth-intelligence";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/overlays";
import { Badge, Card, CardContent, CardHeader, CardTitle, Separator } from "@/components/ui/primitives";
import { useCreateCampaign, useCreateExperiment, useGrowthMission } from "@/hooks/use-api";
import { cn, formatCompactCurrency, formatNumber, formatPercent } from "@/lib/utils";
import type { CampaignSurface, InterventionOption, Opportunity } from "@/types/api";

// --------------------------------------------------------------------------- //
// The rail card
// --------------------------------------------------------------------------- //
export function GrowthMissionCard({ opportunity }: { opportunity: Opportunity }) {
  const mission = useGrowthMission(opportunity.id);
  const [open, setOpen] = React.useState(false);

  return (
    <>
      <Card className="border-border/70 shadow-sm transition-colors hover:border-primary/30">
        <CardHeader className="flex-row items-start justify-between space-y-0 pb-2">
          <div className="min-w-0">
            <div className="mb-1 flex flex-wrap items-center gap-1.5">
              <Badge variant={opportunity.confidence >= 0.7 ? "success" : "warning"}>
                {opportunity.confidence >= 0.7 ? "High confidence" : "Growth opportunity"}
              </Badge>
            </div>
            <CardTitle className="text-base leading-tight">{opportunity.title}</CardTitle>
          </div>
          <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-primary/10 text-primary">
            <Sparkles className="h-4 w-4" />
          </div>
        </CardHeader>
        <CardContent className="space-y-3">
          <div className="flex items-center gap-4 text-xs text-muted-foreground">
            <span className="flex items-center gap-1">
              <TrendingDown className="h-3.5 w-3.5" />
              {formatCompactCurrency(opportunity.estimated_value_monthly)}/month
            </span>
            {mission.data && (
              <span className="flex items-center gap-1">
                <Users className="h-3.5 w-3.5" />
                {formatNumber(mission.data.business_option.audience_size)} customers
              </span>
            )}
          </div>

          {mission.isLoading && (
            <div className="flex items-center gap-2 py-2 text-xs text-muted-foreground">
              <Loader2 className="h-3.5 w-3.5 animate-spin" />
              Comparing business vs PayPal vs hybrid…
            </div>
          )}

          {mission.data && (
            <>
              <div className="flex items-center justify-between">
                <span className="text-2xs font-medium uppercase tracking-wide text-muted-foreground">
                  Recommended
                </span>
                <CampaignSurfaceBadge surface={mission.data.recommended_surface} />
              </div>
              <BudgetAllocationBar
                businessPct={mission.data.business_pct}
                paypalPct={mission.data.paypal_pct}
                businessAmount={mission.data.business_option.budget}
                paypalAmount={mission.data.paypal_option.budget}
              />
            </>
          )}

          <Button size="sm" className="w-full gap-1.5" onClick={() => setOpen(true)}>
            Review mission
            <ArrowRight className="h-3.5 w-3.5" />
          </Button>
        </CardContent>
      </Card>

      {open && (
        <GrowthMissionDialog
          opportunity={opportunity}
          open={open}
          onOpenChange={setOpen}
        />
      )}
    </>
  );
}

// --------------------------------------------------------------------------- //
// The review dialog
// --------------------------------------------------------------------------- //
function GrowthMissionDialog({
  opportunity,
  open,
  onOpenChange,
}: {
  opportunity: Opportunity;
  open: boolean;
  onOpenChange: (open: boolean) => void;
}) {
  const mission = useGrowthMission(opportunity.id);
  const [chosen, setChosen] = React.useState<CampaignSurface | null>(null);
  const createCampaign = useCreateCampaign();
  const createExperiment = useCreateExperiment();
  const [launching, setLaunching] = React.useState(false);

  React.useEffect(() => {
    if (mission.data && !chosen) setChosen(mission.data.recommended_surface);
  }, [mission.data, chosen]);

  if (!mission.data) {
    return (
      <Dialog open={open} onOpenChange={onOpenChange}>
        <DialogContent className="max-w-lg">
          <DialogHeader>
            <DialogTitle>Loading the growth mission…</DialogTitle>
          </DialogHeader>
          <div className="flex items-center justify-center py-10">
            <Loader2 className="h-6 w-6 animate-spin text-muted-foreground" />
          </div>
        </DialogContent>
      </Dialog>
    );
  }

  const data = mission.data;
  const options: { surface: CampaignSurface; option: InterventionOption }[] = [
    { surface: "BUSINESS", option: data.business_option },
    { surface: "PAYPAL", option: data.paypal_option },
    { surface: "HYBRID", option: data.hybrid_option },
  ];
  const active = options.find((o) => o.surface === chosen)?.option ?? data.business_option;

  async function launch() {
    if (!chosen) return;
    setLaunching(true);
    try {
      const isHybrid = chosen === "HYBRID";
      const audience = { name: `${opportunity.title} audience`, ...opportunity.target_segment };

      const campaign = await createCampaign.mutateAsync({
        name: `${opportunity.title} — ${active.label}`.slice(0, 200),
        objective: opportunity.summary || opportunity.title,
        objective_type: "REVENUE_RECOVERY",
        surface: chosen,
        business_budget: isHybrid ? data.business_option.budget : chosen === "BUSINESS" ? active.budget : 0,
        paypal_budget: isHybrid ? data.paypal_option.budget : chosen === "PAYPAL" ? active.budget : 0,
        budget: active.budget,
        offer_type: active.offer_type,
        offer_description: active.offer_description,
        message: active.offer_description,
        channel: active.channel.includes("paypal") ? "paypal_app" : "whatsapp",
        opportunity_id: opportunity.id,
        estimated_impact: active.expected_incremental_revenue,
        ...(chosen !== "PAYPAL" ? { audience } : {}),
      });

      // A hybrid mission is exactly the case the multi-arm extension exists for:
      // one experiment, three arms, each measured against the same control.
      if (isHybrid) {
        await createExperiment.mutateAsync({
          name: `${opportunity.title} — growth experiment`.slice(0, 200),
          hypothesis:
            "Business-side win-back and PayPal-powered offers both beat doing nothing, " +
            "and one of them beats the other.",
          campaign_id: campaign.id,
          opportunity_id: opportunity.id,
          control_split_pct: 25,
          audience,
          extra_arms: [
            {
              key: "business",
              name: "Business win-back",
              description: data.business_option.label,
              offer_description: data.business_option.offer_description,
              allocation_pct: 25,
              unit_cost: data.business_option.audience_size
                ? Math.round((data.business_option.budget / data.business_option.audience_size) * 100) / 100
                : 0,
            },
            {
              key: "paypal",
              name: "PayPal-powered offers",
              description: data.paypal_option.label,
              offer_description: data.paypal_option.offer_description,
              allocation_pct: 25,
              unit_cost: data.paypal_option.audience_size
                ? Math.round((data.paypal_option.budget / data.paypal_option.audience_size) * 100) / 100
                : 0,
            },
            {
              key: "hybrid",
              name: "Hybrid (both)",
              description: data.hybrid_option.label,
              offer_description: data.hybrid_option.offer_description,
              allocation_pct: 25,
              unit_cost: 0,
            },
          ],
        });
      }
      onOpenChange(false);
    } finally {
      setLaunching(false);
    }
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-h-[90vh] max-w-3xl overflow-y-auto">
        <DialogHeader>
          <DialogTitle>Growth Mission</DialogTitle>
          <DialogDescription>{opportunity.title}</DialogDescription>
        </DialogHeader>

        <div className="space-y-4">
          <p className="rounded-lg border border-border/60 bg-muted/30 p-3 text-sm leading-relaxed">
            {data.recommendation_reason}
          </p>

          {data.dont_discount && (
            <DontDiscountBanner
              highPropensityPct={data.dont_discount.high_propensity_pct}
              reasoning={data.dont_discount.reasoning}
            />
          )}

          {data.arbitrage && (
            <div className="flex items-start gap-2 rounded-lg border border-info/25 bg-info/6 p-3 text-xs leading-relaxed text-muted-foreground">
              <Sparkles className="mt-0.5 h-3.5 w-3.5 shrink-0 text-info" />
              <span>
                <span className="font-medium text-foreground">Growth arbitrage detected — </span>
                {data.arbitrage.better_surface.toLowerCase()} is producing{" "}
                {data.arbitrage.better_roi.toFixed(1)}x ROI vs{" "}
                {data.arbitrage.worse_roi.toFixed(1)}x on {data.arbitrage.worse_surface.toLowerCase()},
                from {data.arbitrage.evidence_count} measured campaigns ({data.arbitrage.confidence}{" "}
                confidence).
              </span>
            </div>
          )}

          <div>
            <p className="mb-2 text-sm font-semibold">Where should this run?</p>
            <div className="grid gap-3 sm:grid-cols-3">
              {options.map(({ surface, option }) => (
                <InterventionOptionCard
                  key={surface}
                  option={option}
                  selected={chosen === surface}
                  onSelect={() => setChosen(surface)}
                />
              ))}
            </div>
          </div>

          {chosen === "HYBRID" && (
            <div>
              <p className="mb-1.5 text-2xs font-semibold uppercase tracking-wide text-muted-foreground">
                Budget allocation
              </p>
              <BudgetAllocationBar
                businessPct={data.business_pct}
                paypalPct={data.paypal_pct}
                businessAmount={data.business_option.budget}
                paypalAmount={data.paypal_option.budget}
              />
              <p className="mt-1.5 text-2xs text-muted-foreground">
                {data.allocation_basis === "historical"
                  ? "Split from this merchant's own measured campaign history."
                  : "No measured history for both surfaces yet — split evenly by default."}
              </p>
            </div>
          )}

          <Separator />

          <div className="rounded-lg border border-border bg-card p-3.5 text-sm">
            <p className="mb-2 text-2xs font-semibold uppercase tracking-wide text-muted-foreground">
              This mission will create
            </p>
            <dl className="grid grid-cols-2 gap-x-4 gap-y-1.5 text-xs">
              <dt className="text-muted-foreground">Audience</dt>
              <dd className="text-right font-medium">{active.audience_label}</dd>
              <dt className="text-muted-foreground">Offer</dt>
              <dd className="text-right font-medium">{active.offer_description}</dd>
              <dt className="text-muted-foreground">Budget</dt>
              <dd className="text-right font-medium">{formatCompactCurrency(active.budget)}</dd>
              <dt className="text-muted-foreground">Expected incremental revenue</dt>
              <dd className="text-right font-medium">
                {formatCompactCurrency(active.expected_incremental_revenue)}
              </dd>
              {chosen === "HYBRID" && (
                <>
                  <dt className="text-muted-foreground">Experiment</dt>
                  <dd className="text-right font-medium">Control + Business + PayPal + Hybrid</dd>
                </>
              )}
            </dl>
          </div>
        </div>

        <DialogFooter>
          <Button variant="ghost" onClick={() => onOpenChange(false)}>
            Cancel
          </Button>
          <Button
            onClick={() => void launch()}
            loading={launching}
            disabled={!chosen || active.audience_size === 0}
            className="gap-1.5"
          >
            Create draft — needs approval
            <ArrowRight className="h-3.5 w-3.5" />
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

// --------------------------------------------------------------------------- //
// One option in the comparison
// --------------------------------------------------------------------------- //
function InterventionOptionCard({
  option,
  selected,
  onSelect,
}: {
  option: InterventionOption;
  selected: boolean;
  onSelect: () => void;
}) {
  return (
    <button
      type="button"
      onClick={onSelect}
      className={cn(
        "flex flex-col gap-2 rounded-xl border p-3 text-left transition-colors focus-ring",
        selected ? "border-primary bg-primary/5 shadow-sm" : "border-border hover:border-primary/30",
      )}
    >
      <div className="flex items-center justify-between">
        <CampaignSurfaceBadge surface={option.surface} />
        {selected && <Badge variant="default">Selected</Badge>}
      </div>
      <p className="text-sm font-medium leading-snug">{option.label}</p>
      <p className="text-2xs leading-relaxed text-muted-foreground">{option.audience_label}</p>
      <dl className="mt-1 space-y-1 text-2xs">
        <div className="flex justify-between">
          <dt className="text-muted-foreground">Budget</dt>
          <dd className="font-medium tabular-nums">{formatCompactCurrency(option.budget)}</dd>
        </div>
        <div className="flex justify-between">
          <dt className="text-muted-foreground">Est. conversion</dt>
          <dd className="font-medium tabular-nums">
            {option.historical_conversion_pct !== null
              ? formatPercent(option.historical_conversion_pct)
              : "n/a"}
          </dd>
        </div>
        <div className="flex justify-between">
          <dt className="text-muted-foreground">Expected revenue</dt>
          <dd className="font-medium tabular-nums">
            {formatCompactCurrency(option.expected_incremental_revenue)}
          </dd>
        </div>
      </dl>
    </button>
  );
}

export { InterventionOptionCard };
