"use client";

/**
 * The AI recommendation, and the human approval gate in front of it.
 *
 * Spec section 37: an agent may recommend a financially consequential action, but
 * only a permitted human can approve it. That is enforced in the backend; this
 * panel makes the gate *visible* - impact, risk, evidence and the alternative
 * that was considered and rejected are all shown before the Approve button.
 */

import {
  AlertTriangle,
  BadgeCheck,
  Ban,
  Beaker,
  Brain,
  Check,
  Lightbulb,
  Loader2,
  Lock,
  ShieldQuestion,
} from "lucide-react";
import * as React from "react";

import { EvidenceList, SourceBadges } from "@/components/growth/evidence-list";
import { Button } from "@/components/ui/button";
import { FadeIn } from "@/components/ui/motion";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/overlays";
import {
  Badge,
  Card,
  CardContent,
  Separator,
  Textarea,
} from "@/components/ui/primitives";
import { useApproveOpportunity } from "@/hooks/use-api";
import { cn, formatCompactCurrency } from "@/lib/utils";
import { useAuthStore } from "@/stores/auth";
import type { GrowthRecommendation, Opportunity } from "@/types/api";

const RISK_META = {
  low: { label: "Low risk", variant: "success" as const },
  medium: { label: "Medium risk", variant: "warning" as const },
  high: { label: "High risk", variant: "destructive" as const },
};

export function RecommendationPanel({
  recommendation,
  opportunity,
  usedFallback,
  onApproved,
}: {
  recommendation: GrowthRecommendation;
  opportunity?: Opportunity | null;
  usedFallback?: boolean;
  onApproved?: () => void;
}) {
  const [confirmOpen, setConfirmOpen] = React.useState(false);
  const [rejectOpen, setRejectOpen] = React.useState(false);
  const [note, setNote] = React.useState("");

  const approve = useApproveOpportunity();
  const canApprove = useAuthStore((s) => s.can("campaign:execute") && s.can("experiment:approve"));
  const role = useAuthStore((s) => s.user?.role ?? null);

  const risk = RISK_META[recommendation.risk] ?? RISK_META.medium;
  const opportunityId = opportunity?.id;
  const alreadyActioned =
    opportunity?.status === "RUNNING" ||
    opportunity?.status === "MEASURING" ||
    opportunity?.status === "SCALED" ||
    opportunity?.status === "STOPPED";

  async function handleDecision(approved: boolean) {
    if (!opportunityId) return;
    await approve.mutateAsync({ id: opportunityId, approve: approved, note, executeNow: true });
    setConfirmOpen(false);
    setRejectOpen(false);
    setNote("");
    onApproved?.();
  }

  return (
    <FadeIn>
      <Card className="surface-aurora overflow-hidden border-primary/25">
        <CardContent className="space-y-5 p-6">
          {/* Header */}
          <div className="flex flex-wrap items-start justify-between gap-3">
            <div className="flex items-start gap-3">
              <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg bg-primary text-primary-foreground">
                <Lightbulb className="h-4.5 w-4.5" />
              </div>
              <div>
                <p className="text-2xs font-semibold uppercase tracking-widest text-primary">
                  AI Recommendation
                </p>
                <h3 className="text-lg font-semibold leading-tight tracking-tight">
                  {recommendation.opportunity}
                </h3>
              </div>
            </div>
            <div className="flex flex-wrap items-center gap-1.5">
              <Badge variant={risk.variant}>{risk.label}</Badge>
              {usedFallback && (
                <Badge variant="muted" title="No LLM key configured - the deterministic path produced this">
                  Deterministic mode
                </Badge>
              )}
            </div>
          </div>

          {/* Headline numbers */}
          <div className="grid gap-3 sm:grid-cols-3">
            <Metric
              label="Estimated impact"
              value={`${formatCompactCurrency(recommendation.estimated_impact)}/mo`}
              accent
            />
            <Metric
              label="Confidence"
              value={`${Math.round(recommendation.confidence * 100)}%`}
            />
            <Metric
              label="Approval"
              value={recommendation.requires_approval ? "Required" : "Not needed"}
            />
          </div>

          <p className="text-sm leading-relaxed">{recommendation.summary}</p>

          {/* Hypothesis - explicitly labelled as a hypothesis */}
          {recommendation.hypothesis && (
            <Section icon={ShieldQuestion} title="Hypothesis" tone="info">
              <p className="text-sm leading-relaxed text-muted-foreground">
                {recommendation.hypothesis}
              </p>
            </Section>
          )}

          {/* Evidence */}
          {recommendation.evidence.length > 0 && (
            <Section icon={Brain} title="Evidence">
              <div className="mb-2">
                <SourceBadges evidence={recommendation.evidence} />
              </div>
              <EvidenceList evidence={recommendation.evidence} dense />
            </Section>
          )}

          {/* Recommended action */}
          {recommendation.recommended_action && (
            <Section icon={Beaker} title="Recommended intervention" tone="primary">
              <p className="text-sm leading-relaxed">{recommendation.recommended_action}</p>
              {recommendation.reasoning && (
                <p className="mt-2 text-xs leading-relaxed text-muted-foreground">
                  {recommendation.reasoning}
                </p>
              )}
              {recommendation.alternatives_considered.length > 0 && (
                <div className="mt-3 space-y-1">
                  <p className="text-2xs font-semibold uppercase tracking-wide text-muted-foreground">
                    Considered and not chosen
                  </p>
                  <ul className="space-y-0.5">
                    {recommendation.alternatives_considered.map((alt) => (
                      <li
                        key={alt}
                        className="flex items-start gap-1.5 text-xs text-muted-foreground"
                      >
                        <Ban className="mt-0.5 h-3 w-3 shrink-0" />
                        {alt}
                      </li>
                    ))}
                  </ul>
                </div>
              )}
            </Section>
          )}

          <Separator />

          {/* Approval gate */}
          {alreadyActioned ? (
            <div className="flex items-center gap-2 rounded-lg border border-success/25 bg-success/8 p-3 text-sm text-success">
              <BadgeCheck className="h-4 w-4 shrink-0" />
              This recommendation has already been approved and acted on.
            </div>
          ) : !opportunityId ? (
            <p className="text-xs text-muted-foreground">
              This analysis is not linked to a stored opportunity, so there is nothing to approve.
            </p>
          ) : !canApprove ? (
            <div className="flex items-start gap-2 rounded-lg border border-border bg-muted/50 p-3 text-sm">
              <Lock className="mt-0.5 h-4 w-4 shrink-0 text-muted-foreground" />
              <div>
                <p className="font-medium">Approval needs a different role</p>
                <p className="text-xs text-muted-foreground">
                  You are signed in as {role}. Executing a campaign and launching an experiment
                  require the Admin or Owner role. The backend enforces this regardless of what the
                  interface shows.
                </p>
              </div>
            </div>
          ) : (
            <div className="space-y-3">
              <div className="flex items-start gap-2 rounded-lg border border-warning/25 bg-warning/8 p-3">
                <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0 text-warning" />
                <p className="text-xs leading-relaxed text-muted-foreground">
                  Approving builds the target segment, creates the campaign and a controlled
                  experiment with a held-out control group, and launches it.{" "}
                  <span className="font-medium text-foreground">
                    No messaging provider is connected yet
                  </span>{" "}
                  — no real messages are sent and no funds move.
                </p>
              </div>
              <div className="flex flex-wrap gap-2">
                <Button
                  onClick={() => setConfirmOpen(true)}
                  loading={approve.isPending && approve.variables?.approve === true}
                  className="gap-2"
                >
                  <Check className="h-4 w-4" />
                  Approve and run
                </Button>
                <Button variant="outline" onClick={() => setRejectOpen(true)}>
                  <Ban className="h-4 w-4" />
                  Reject
                </Button>
              </div>
            </div>
          )}
        </CardContent>
      </Card>

      {/* Approve confirmation */}
      <Dialog open={confirmOpen} onOpenChange={setConfirmOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Approve this intervention?</DialogTitle>
            <DialogDescription>
              You are approving a financially consequential action. Your decision is recorded in the
              audit log with your name against it.
            </DialogDescription>
          </DialogHeader>

          <div className="space-y-3 rounded-lg border border-border bg-muted/40 p-3 text-sm">
            <Row label="Intervention" value={recommendation.opportunity} />
            <Row
              label="Estimated impact"
              value={`${formatCompactCurrency(recommendation.estimated_impact)}/month`}
            />
            <Row label="Confidence" value={`${Math.round(recommendation.confidence * 100)}%`} />
            <Row label="Risk" value={risk.label} />
            <Row label="Delivery" value="Preview (no provider connected)" />
          </div>

          <div className="space-y-1.5">
            <label htmlFor="approve-note" className="text-sm font-medium">
              Note (optional)
            </label>
            <Textarea
              id="approve-note"
              value={note}
              onChange={(event) => setNote(event.target.value)}
              placeholder="Why you are approving this…"
              rows={2}
            />
          </div>

          <DialogFooter>
            <Button variant="outline" onClick={() => setConfirmOpen(false)}>
              Cancel
            </Button>
            <Button onClick={() => handleDecision(true)} loading={approve.isPending}>
              {approve.isPending ? (
                <>
                  <Loader2 className="h-4 w-4 animate-spin" />
                  Running the growth loop…
                </>
              ) : (
                <>
                  <Check className="h-4 w-4" />
                  Approve and run
                </>
              )}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* Reject */}
      <Dialog open={rejectOpen} onOpenChange={setRejectOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Reject this recommendation?</DialogTitle>
            <DialogDescription>
              Nothing will be created or executed. The opportunity is marked dismissed.
            </DialogDescription>
          </DialogHeader>
          <Textarea
            value={note}
            onChange={(event) => setNote(event.target.value)}
            placeholder="Why are you rejecting it? (optional)"
            rows={2}
          />
          <DialogFooter>
            <Button variant="outline" onClick={() => setRejectOpen(false)}>
              Cancel
            </Button>
            <Button
              variant="destructive"
              onClick={() => handleDecision(false)}
              loading={approve.isPending}
            >
              Reject
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </FadeIn>
  );
}

function Metric({ label, value, accent }: { label: string; value: string; accent?: boolean }) {
  return (
    <div
      className={cn(
        "rounded-lg border p-3",
        accent ? "border-primary/25 bg-primary/5" : "border-border bg-card",
      )}
    >
      <p className="text-2xs font-medium uppercase tracking-wide text-muted-foreground">{label}</p>
      <p
        className={cn(
          "mt-0.5 text-lg font-semibold leading-none tnum",
          accent && "text-primary",
        )}
      >
        {value}
      </p>
    </div>
  );
}

function Section({
  icon: Icon,
  title,
  tone = "muted",
  children,
}: {
  icon: typeof Lightbulb;
  title: string;
  tone?: "muted" | "info" | "primary";
  children: React.ReactNode;
}) {
  const toneClass = {
    muted: "text-muted-foreground",
    info: "text-info",
    primary: "text-primary",
  }[tone];
  return (
    <div className="space-y-2">
      <p className={cn("flex items-center gap-1.5 text-2xs font-semibold uppercase tracking-widest", toneClass)}>
        <Icon className="h-3.5 w-3.5" />
        {title}
      </p>
      {children}
    </div>
  );
}

function Row({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex items-start justify-between gap-4">
      <span className="text-muted-foreground">{label}</span>
      <span className="text-right font-medium">{value}</span>
    </div>
  );
}
