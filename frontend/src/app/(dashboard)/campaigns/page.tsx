"use client";

import {
  Ban,
  Check,
  Clock,
  IndianRupee,
  Info,
  Megaphone,
  Play,
  Send,
  Sparkles,
  TestTubeDiagonal,
  TrendingUp,
  Users,
  Workflow,
} from "lucide-react";
import Link from "next/link";
import * as React from "react";

import { EmptyState, ErrorState, LoadingRows } from "@/components/common/states";
import { Button } from "@/components/ui/button";
import { FadeIn, Stagger, StaggerItem } from "@/components/ui/motion";
import {
  Badge,
  Card,
  CardContent,
  CardHeader,
  CardTitle,
  Separator,
} from "@/components/ui/primitives";
import {
  useCampaign,
  useCampaignApproval,
  useCampaigns,
  useExecuteCampaign,
  useExperiments,
  useOpportunities,
} from "@/hooks/use-api";
import { cn, formatCompactCurrency, formatDate, formatDateTime, formatNumber } from "@/lib/utils";
import { CampaignCreateDialog } from "@/components/campaigns/campaign-create-dialog";
import { BudgetAllocationBar, CampaignSurfaceBadge } from "@/components/campaigns/growth-intelligence";
import { GrowthMissionCard } from "@/components/campaigns/growth-mission-card";
import { useAuthStore } from "@/stores/auth";
import type { Campaign } from "@/types/api";

const STATUS_META: Record<
  string,
  { label: string; variant: "default" | "success" | "warning" | "destructive" | "info" | "muted" }
> = {
  DRAFT: { label: "Draft", variant: "muted" },
  PENDING_APPROVAL: { label: "Needs approval", variant: "warning" },
  APPROVED: { label: "Approved", variant: "info" },
  SCHEDULED: { label: "Scheduled", variant: "info" },
  RUNNING: { label: "Running", variant: "default" },
  PAUSED: { label: "Paused", variant: "muted" },
  COMPLETED: { label: "Completed", variant: "success" },
  REJECTED: { label: "Rejected", variant: "destructive" },
  CANCELLED: { label: "Cancelled", variant: "muted" },
};

export default function CampaignsPage() {
  const { data, isLoading, error, refetch } = useCampaigns({});
  const experiments = useExperiments({});
  const opportunities = useOpportunities();
  const [selectedId, setSelectedId] = React.useState<string | null>(null);
  const canCreate = useAuthStore((s) => s.can("campaign:create"));

  React.useEffect(() => {
    if (data?.items.length) setSelectedId((current) => current ?? data.items[0].id);
  }, [data]);

  const campaignItems = data?.items ?? [];
  const activeCampaigns = campaignItems.filter(
    (c) => c.status === "RUNNING" || c.status === "SCHEDULED",
  ).length;
  const totalSpend = campaignItems.reduce((sum, c) => sum + (c.budget || 0), 0);
  const measuredCampaigns = campaignItems.filter((c) => c.actual_incremental_revenue !== null);
  const totalIncrementalRevenue = measuredCampaigns.reduce(
    (sum, c) => sum + (c.actual_incremental_revenue || 0),
    0,
  );
  const roiCampaigns = campaignItems.filter((c) => c.incremental_roi !== null);
  const avgIncrementalRoi = roiCampaigns.length
    ? roiCampaigns.reduce((sum, c) => sum + (c.incremental_roi || 0), 0) / roiCampaigns.length
    : null;
  const experimentsRunning = (experiments.data?.items ?? []).filter(
    (e) => e.status === "RUNNING" || e.status === "MEASURING",
  ).length;

  const missionOpportunities = (opportunities.data?.opportunities ?? [])
    .filter((o) => !["SCALED", "STOPPED", "DISMISSED"].includes(o.status))
    .slice(0, 3);

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h2 className="text-xl font-semibold tracking-tight">Campaigns</h2>
          <p className="text-sm text-muted-foreground">
            Turn growth opportunities into measurable experiments
          </p>
        </div>
        <div className="flex items-center gap-2">
          <Button asChild variant="outline" className="gap-2">
            <Link href="/impact">
              <Workflow className="h-4 w-4" />
              Impact tree
            </Link>
          </Button>
          {canCreate && <CampaignCreateDialog />}
        </div>
      </div>

      {/* Top-level metrics */}
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-5">
        <MetricTile icon={Megaphone} label="Active campaigns" value={formatNumber(activeCampaigns)} />
        <MetricTile icon={IndianRupee} label="Campaign spend" value={formatCompactCurrency(totalSpend)} />
        <MetricTile
          icon={TrendingUp}
          label="Incremental revenue"
          value={formatCompactCurrency(totalIncrementalRevenue)}
        />
        <MetricTile
          icon={Sparkles}
          label="Incremental ROI"
          value={avgIncrementalRoi !== null ? `${avgIncrementalRoi.toFixed(1)}x` : "n/a"}
        />
        <MetricTile
          icon={TestTubeDiagonal}
          label="Experiments running"
          value={formatNumber(experimentsRunning)}
        />
      </div>

      {/* Growth Missions - the Growth Allocation Engine's candidate interventions */}
      {missionOpportunities.length > 0 && (
        <div className="space-y-3">
          <div>
            <h3 className="text-base font-semibold tracking-tight">Growth Missions</h3>
            <p className="text-xs text-muted-foreground">
              Where the next rupee of growth budget should go, compared across business and Paypal
            </p>
          </div>
          <div className="grid gap-3 md:grid-cols-2 lg:grid-cols-3">
            {missionOpportunities.map((opportunity) => (
              <GrowthMissionCard key={opportunity.id} opportunity={opportunity} />
            ))}
          </div>
        </div>
      )}

      <Card className="border-warning/30 bg-warning/5">
        <CardContent className="flex items-start gap-3 p-4">
          <Info className="mt-0.5 h-4 w-4 shrink-0 text-warning" />
          <p className="text-sm leading-relaxed text-muted-foreground">
            <span className="font-medium text-foreground">No messaging provider is connected yet.</span>{" "}
            No message is sent to a real customer and no funds move. Execution is still gated on a
            recorded human approval, so the control flow is exactly what it would be in production.
          </p>
        </CardContent>
      </Card>

      {isLoading && <LoadingRows rows={3} />}
      {error && <ErrorState error={error} onRetry={() => void refetch()} />}

      {data && data.items.length === 0 && (
        <EmptyState
          icon={Megaphone}
          title="No campaigns yet"
          description="Approve an opportunity and the Action Agent will build the segment and create a campaign for you."
        />
      )}

      {data && data.items.length > 0 && (
        <div className="grid gap-4 lg:grid-cols-[minmax(0,340px)_minmax(0,1fr)]">
          <Stagger className="space-y-2">
            {data.items.map((campaign) => (
              <StaggerItem key={campaign.id}>
                <CampaignListItem
                  campaign={campaign}
                  active={campaign.id === selectedId}
                  onSelect={() => setSelectedId(campaign.id)}
                />
              </StaggerItem>
            ))}
          </Stagger>

          {selectedId && <CampaignDetail campaignId={selectedId} />}
        </div>
      )}
    </div>
  );
}

function CampaignListItem({
  campaign,
  active,
  onSelect,
}: {
  campaign: Campaign;
  active: boolean;
  onSelect: () => void;
}) {
  const status = STATUS_META[campaign.status] ?? STATUS_META.DRAFT;
  const audience = campaign.audiences[0];

  return (
    <button
      type="button"
      onClick={onSelect}
      className={cn(
        "w-full rounded-xl border p-3.5 text-left transition-colors focus-ring",
        active
          ? "border-primary/50 bg-primary/5"
          : "border-border bg-card hover:border-primary/30 hover:bg-muted/40",
      )}
    >
      <div className="flex items-start justify-between gap-2">
        <p className="min-w-0 truncate text-sm font-medium">{campaign.name}</p>
        <Badge variant={status.variant}>{status.label}</Badge>
      </div>
      <div className="mt-1 flex flex-wrap items-center gap-2 text-2xs text-muted-foreground">
        <CampaignSurfaceBadge surface={campaign.surface} className="px-1.5 py-0 text-2xs" />
        <span className="flex items-center gap-1">
          <Users className="h-3 w-3" />
          {formatNumber(audience?.size ?? 0)} customers
        </span>
        <span className="text-muted-foreground/50">·</span>
        {campaign.channel.replace("_", " ")}
      </div>
    </button>
  );
}

function CampaignDetail({ campaignId }: { campaignId: string }) {
  const { data: campaign, isLoading, error, refetch } = useCampaign(campaignId);
  const approval = useCampaignApproval();
  const execute = useExecuteCampaign();

  const canApprove = useAuthStore((s) => s.can("campaign:approve"));
  const canExecute = useAuthStore((s) => s.can("campaign:execute"));

  if (isLoading) return <LoadingRows rows={4} />;
  if (error) return <ErrorState error={error} onRetry={() => void refetch()} />;
  if (!campaign) return null;

  const status = STATUS_META[campaign.status] ?? STATUS_META.DRAFT;
  const audience = campaign.audiences[0];
  const needsApproval = campaign.status === "PENDING_APPROVAL" || campaign.status === "DRAFT";
  const readyToLaunch = campaign.status === "APPROVED" || campaign.status === "SCHEDULED";

  return (
    <FadeIn key={campaign.id}>
      <Card>
        <CardHeader className="flex-row flex-wrap items-start justify-between gap-3 space-y-0">
          <div className="min-w-0">
            <div className="mb-1 flex flex-wrap items-center gap-2">
              <Badge variant={status.variant}>{status.label}</Badge>
              <CampaignSurfaceBadge surface={campaign.surface} />
              {campaign.is_simulated && <Badge variant="outline">Preview</Badge>}
            </div>
            <CardTitle className="text-lg">{campaign.name}</CardTitle>
            <p className="mt-1 max-w-2xl text-sm leading-relaxed text-muted-foreground">
              {campaign.objective}
            </p>
          </div>
        </CardHeader>

        <CardContent className="space-y-5">
          <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
            <Tile label="Audience" value={formatNumber(audience?.size ?? 0)} icon={Users} />
            <Tile label="Channel" value={campaign.channel.replace("_", " ")} icon={Send} />
            <Tile
              label={campaign.actual_incremental_revenue !== null ? "Incremental revenue" : "Estimated impact"}
              value={formatCompactCurrency(
                campaign.actual_incremental_revenue ?? campaign.estimated_impact,
              )}
              icon={Megaphone}
            />
            <Tile
              label="Window"
              value={
                campaign.start_date
                  ? `${formatDate(campaign.start_date)} – ${formatDate(campaign.end_date)}`
                  : "Not scheduled"
              }
              icon={Clock}
            />
          </div>

          {/* Two-sided execution - only a hybrid mission has two legs to show */}
          {campaign.surface === "HYBRID" && (
            <div className="space-y-3 rounded-lg border border-border bg-card p-3.5">
              <p className="text-2xs font-semibold uppercase tracking-widest text-muted-foreground">
                Two-sided execution
              </p>
              <BudgetAllocationBar
                businessPct={
                  campaign.budget
                    ? (campaign.business_budget / campaign.budget) * 100
                    : 50
                }
                paypalPct={
                  campaign.budget ? (campaign.paypal_budget / campaign.budget) * 100 : 50
                }
                businessAmount={campaign.business_budget}
                paypalAmount={campaign.paypal_budget}
              />
              {campaign.incremental_roi !== null && (
                <p className="text-2xs text-muted-foreground">
                  Measured incremental ROI: {campaign.incremental_roi.toFixed(1)}x
                </p>
              )}
            </div>
          )}

          {campaign.offer_description && (
            <div className="rounded-lg border border-primary/25 bg-primary/5 p-3.5">
              <p className="text-2xs font-semibold uppercase tracking-widest text-primary">Offer</p>
              <p className="mt-1 text-sm leading-relaxed">{campaign.offer_description}</p>
              {campaign.message && (
                <p className="mt-2 rounded-md bg-card p-2.5 text-sm italic text-muted-foreground">
                  “{campaign.message}”
                </p>
              )}
            </div>
          )}

          {/* Approval gate */}
          {(needsApproval || readyToLaunch) && (
            <div className="space-y-3 rounded-lg border border-warning/25 bg-warning/5 p-4">
              <p className="text-sm font-medium">
                {needsApproval ? "Waiting for approval" : "Approved — ready to launch"}
              </p>
              <p className="text-xs leading-relaxed text-muted-foreground">
                {needsApproval
                  ? "The agent created this campaign but cannot approve it. A user with the campaign:approve permission must decide."
                  : "Execution is unlocked because an approval is on record. No messaging provider is connected yet, so delivery is a preview."}
              </p>
              <div className="flex flex-wrap gap-2">
                {needsApproval && canApprove && (
                  <>
                    <Button
                      size="sm"
                      onClick={() =>
                        approval.mutate({ id: campaign.id, approve: true, note: "Approved from UI" })
                      }
                      loading={approval.isPending}
                    >
                      <Check className="h-4 w-4" />
                      Approve
                    </Button>
                    <Button
                      size="sm"
                      variant="outline"
                      onClick={() => approval.mutate({ id: campaign.id, approve: false })}
                      loading={approval.isPending}
                    >
                      <Ban className="h-4 w-4" />
                      Reject
                    </Button>
                  </>
                )}
                {readyToLaunch && canExecute && (
                  <Button
                    size="sm"
                    onClick={() => execute.mutate(campaign.id)}
                    loading={execute.isPending}
                  >
                    <Play className="h-4 w-4" />
                    Launch (simulated)
                  </Button>
                )}
                {((needsApproval && !canApprove) || (readyToLaunch && !canExecute)) && (
                  <p className="text-xs text-muted-foreground">
                    Your role cannot perform this action. The backend enforces this regardless of
                    what the interface shows.
                  </p>
                )}
              </div>
            </div>
          )}

          <Separator />

          {/* Action log */}
          <div className="space-y-2">
            <p className="text-2xs font-semibold uppercase tracking-widest text-muted-foreground">
              Activity
            </p>
            <ol className="space-y-2">
              {campaign.actions.map((action) => (
                <li key={action.id} className="flex gap-3">
                  <div className="mt-1 h-1.5 w-1.5 shrink-0 rounded-full bg-primary" />
                  <div className="min-w-0 flex-1">
                    <div className="flex flex-wrap items-center gap-2">
                      <span className="text-sm font-medium">
                        {action.action_type.replace(/_/g, " ").toLowerCase()}
                      </span>
                      <Badge variant="outline">{action.actor_type}</Badge>
                      {action.actor_label && (
                        <span className="text-2xs text-muted-foreground">{action.actor_label}</span>
                      )}
                    </div>
                    <p className="text-sm leading-relaxed text-muted-foreground">
                      {action.description}
                    </p>
                    <p className="text-2xs text-muted-foreground">
                      {formatDateTime(action.created_at)}
                    </p>
                  </div>
                </li>
              ))}
            </ol>
          </div>

          <p className="text-2xs leading-relaxed text-muted-foreground">
            {campaign.provenance.note}
          </p>
        </CardContent>
      </Card>
    </FadeIn>
  );
}

function Tile({
  label,
  value,
  icon: Icon,
}: {
  label: string;
  value: string;
  icon: typeof Users;
}) {
  return (
    <div className="rounded-lg border border-border bg-card p-3">
      <p className="flex items-center gap-1.5 text-2xs font-medium uppercase tracking-wide text-muted-foreground">
        <Icon className="h-3 w-3" />
        {label}
      </p>
      <p className="mt-1 truncate text-sm font-semibold capitalize">{value}</p>
    </div>
  );
}

function MetricTile({
  label,
  value,
  icon: Icon,
}: {
  label: string;
  value: string;
  icon: typeof Users;
}) {
  return (
    <Card className="border-border/70 shadow-sm">
      <CardContent className="flex items-center gap-3 p-3.5">
        <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-xl bg-primary/10 text-primary">
          <Icon className="h-4 w-4" />
        </span>
        <div className="min-w-0">
          <p className="truncate text-lg font-bold leading-none tabular-nums">{value}</p>
          <p className="mt-1 truncate text-2xs text-muted-foreground">{label}</p>
        </div>
      </CardContent>
    </Card>
  );
}
