"use client";

/**
 * Experiments: control vs test, lift, incremental revenue, ROI, significance and
 * the decision.
 *
 * Every figure on this page was recomputed from the transaction ledger by the
 * measurement service. The page never derives a number of its own.
 */

import {
  Activity,
  ArrowRight,
  BadgeCheck,
  Ban,
  BarChart3,
  Beaker,
  BookOpen,
  Check,
  Loader2,
  Play,
  ShieldQuestion,
  Users,
  Workflow,
} from "lucide-react";
import { useSearchParams } from "next/navigation";
import Link from "next/link";
import * as React from "react";

import { ConversionCompareChart } from "@/components/charts/charts";
import { EmptyState, ErrorState, LoadingRows } from "@/components/common/states";
import { Button } from "@/components/ui/button";
import { AnimatedNumber, FadeIn, Stagger, StaggerItem } from "@/components/ui/motion";
import {
  Badge,
  Card,
  CardContent,
  CardHeader,
  CardTitle,
  Separator,
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from "@/components/ui/primitives";
import {
  useExperimentApproval,
  useExperiments,
  useMeasureExperiment,
} from "@/hooks/use-api";
import {
  cn,
  formatCompactCurrency,
  formatDate,
  formatNumber,
  formatPercent,
} from "@/lib/utils";
import { ExperimentCreateDialog } from "@/components/experiments/experiment-create-dialog";
import { useAuthStore } from "@/stores/auth";
import type { Experiment } from "@/types/api";

const DECISION_META: Record<
  string,
  { label: string; variant: "success" | "destructive" | "info" | "warning" | "muted"; copy: string }
> = {
  SCALE: {
    label: "Scale",
    variant: "success",
    copy: "The lift cleared the threshold and is statistically significant. Roll it out.",
  },
  STOP: {
    label: "Stop",
    variant: "destructive",
    copy: "The test arm underperformed control. Keep the current experience.",
  },
  CONTINUE: {
    label: "Continue",
    variant: "info",
    copy: "Promising, but not yet separable from noise. Keep running to accumulate sample.",
  },
  WATCH: {
    label: "Watch",
    variant: "warning",
    copy: "Below the success threshold and not clearly different from control.",
  },
  PENDING: { label: "Pending", variant: "muted", copy: "Not measured yet." },
};

export default function ExperimentsPage() {
  const params = useSearchParams();
  const focusId = params.get("focus");

  const { data, isLoading, error, refetch } = useExperiments({});
  const measure = useMeasureExperiment();
  const approval = useExperimentApproval();
  const canMeasure = useAuthStore((s) => s.can("experiment:measure"));
  const canCreate = useAuthStore((s) => s.can("experiment:create"));
  const canApprove = useAuthStore((s) => s.can("experiment:approve"));

  const [selectedId, setSelectedId] = React.useState<string | null>(focusId);

  React.useEffect(() => {
    if (!data?.items.length) return;
    setSelectedId((current) => current ?? data.items[0].id);
  }, [data]);

  const selected = data?.items.find((item) => item.id === selectedId) ?? null;

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h2 className="text-xl font-semibold tracking-tight">Experiments</h2>
          <p className="text-sm text-muted-foreground">
            Interventions measured against a held-out control group
          </p>
        </div>
        <div className="flex items-center gap-2">
          <Button asChild variant="outline" className="gap-2">
            <Link href="/impact">
              <Workflow className="h-4 w-4" />
              Impact tree
            </Link>
          </Button>
          {canCreate && <ExperimentCreateDialog />}
        </div>
      </div>

      {isLoading && <LoadingRows rows={3} />}
      {error && <ErrorState error={error} onRetry={() => void refetch()} />}

      {data && data.items.length === 0 && (
        <EmptyState
          icon={Beaker}
          title="No experiments yet"
          description="Create one here, or approve an opportunity on the Opportunity Radar and the Experiment Agent will build it with a control and test group."
        />
      )}

      {data && data.items.length > 0 && (
        <div className="grid gap-4 lg:grid-cols-[minmax(0,320px)_minmax(0,1fr)]">
          {/* List */}
          <Stagger className="space-y-2">
            {data.items.map((experiment) => (
              <StaggerItem key={experiment.id}>
                <ExperimentListItem
                  experiment={experiment}
                  active={experiment.id === selectedId}
                  onSelect={() => setSelectedId(experiment.id)}
                />
              </StaggerItem>
            ))}
          </Stagger>

          {/* Detail */}
          {selected && (
            <FadeIn key={selected.id}>
              <ExperimentDetail
                experiment={selected}
                canMeasure={canMeasure}
                measuring={measure.isPending}
                onMeasure={() => measure.mutate(selected.id)}
                canApprove={canApprove}
                approving={approval.isPending}
                onApprove={(approve) => approval.mutate({ id: selected.id, approve })}
              />
            </FadeIn>
          )}
        </div>
      )}
    </div>
  );
}

function ExperimentListItem({
  experiment,
  active,
  onSelect,
}: {
  experiment: Experiment;
  active: boolean;
  onSelect: () => void;
}) {
  const decision = DECISION_META[experiment.decision] ?? DECISION_META.PENDING;
  const test = experiment.results.find((r) => r.variant_role === "TEST");

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
        <p className="min-w-0 truncate text-sm font-medium">{experiment.name}</p>
        <Badge variant={decision.variant}>{decision.label}</Badge>
      </div>
      <p className="mt-1 text-2xs text-muted-foreground">
        {experiment.status.toLowerCase().replace("_", " ")} ·{" "}
        {experiment.start_date ? formatDate(experiment.start_date) : "not scheduled"}
      </p>
      {test?.conversion_lift_pct != null && (
        <p
          className={cn(
            "mt-1.5 text-sm font-semibold tnum",
            test.conversion_lift_pct >= 0 ? "text-success" : "text-destructive",
          )}
        >
          {test.conversion_lift_pct >= 0 ? "+" : ""}
          {test.conversion_lift_pct.toFixed(1)}% lift
        </p>
      )}
    </button>
  );
}

function ExperimentDetail({
  experiment,
  canMeasure,
  measuring,
  onMeasure,
  canApprove,
  approving,
  onApprove,
}: {
  experiment: Experiment;
  canMeasure: boolean;
  measuring: boolean;
  onMeasure: () => void;
  canApprove: boolean;
  approving: boolean;
  onApprove: (approve: boolean) => void;
}) {
  const control = experiment.results.find((r) => r.variant_role === "CONTROL");
  const treatmentResults = experiment.results.filter((r) => r.variant_role === "TEST");
  // A plain A/B test has exactly one of these, so `test` is unchanged from
  // before. A multi-arm growth experiment (business/paypal/hybrid) has several -
  // the headline chart/tiles below follow whichever one is actually winning,
  // same as the backend's own `ExperimentSummary`; every arm's own numbers are
  // still shown in the per-arm breakdown further down.
  const test = treatmentResults.reduce<typeof treatmentResults[number] | undefined>(
    (best, row) =>
      !best || (row.incremental_revenue ?? -Infinity) > (best.incremental_revenue ?? -Infinity)
        ? row
        : best,
    undefined,
  );
  const isMultiArm = treatmentResults.length > 1 || experiment.variants.filter((v) => v.role === "TEST").length > 1;
  const decision = DECISION_META[experiment.decision] ?? DECISION_META.PENDING;
  const needsApproval = experiment.status === "DRAFT" || experiment.status === "PENDING_APPROVAL";
  const hasRun = !needsApproval && experiment.status !== "REJECTED";
  const controlVariant = experiment.variants.find((v) => v.role === "CONTROL");
  const testVariants = experiment.variants.filter((v) => v.role === "TEST");
  const testVariant = testVariants.find((v) => v.key === test?.variant_key) ?? testVariants[0];

  return (
    <Card>
      <CardHeader className="flex-row flex-wrap items-start justify-between gap-3 space-y-0">
        <div className="min-w-0">
          <div className="mb-1 flex flex-wrap items-center gap-2">
            <Badge variant={decision.variant}>{decision.label}</Badge>
            <Badge variant="outline">{experiment.status.toLowerCase().replace("_", " ")}</Badge>
            {experiment.is_simulated && <Badge variant="outline">Preview</Badge>}
          </div>
          <CardTitle className="text-lg">{experiment.name}</CardTitle>
        </div>
        <div className="flex flex-wrap items-center gap-2">
        {canApprove && needsApproval && (
          <>
            <Button
              onClick={() => onApprove(true)}
              loading={approving}
              className="gap-2"
            >
              <Check className="h-4 w-4" />
              Approve &amp; launch
            </Button>
            <Button
              variant="outline"
              onClick={() => onApprove(false)}
              disabled={approving}
              className="gap-2"
            >
              <Ban className="h-4 w-4" />
              Reject
            </Button>
          </>
        )}
        {canMeasure && hasRun && (
          <Button variant="outline" onClick={onMeasure} loading={measuring} className="gap-2">
            {measuring ? (
              <>
                <Loader2 className="h-4 w-4 animate-spin" />
                Measuring…
              </>
            ) : (
              <>
                <Activity className="h-4 w-4" />
                {experiment.results.length ? "Re-measure" : "Measure"}
              </>
            )}
          </Button>
        )}
        </div>
      </CardHeader>

      <CardContent className="space-y-5">
        {/* Hypothesis */}
        <div className="rounded-lg border border-info/25 bg-info/5 p-3.5">
          <p className="flex items-center gap-1.5 text-2xs font-semibold uppercase tracking-widest text-info">
            <ShieldQuestion className="h-3.5 w-3.5" />
            Hypothesis
          </p>
          <p className="mt-1 text-sm leading-relaxed">{experiment.hypothesis}</p>
        </div>

        {/* Arms */}
        <div className={cn("grid gap-3", isMultiArm ? "sm:grid-cols-2 lg:grid-cols-4" : "sm:grid-cols-2")}>
          <ArmCard
            title="Control"
            subtitle={controlVariant?.description || "No change. Baseline for comparison."}
            size={controlVariant?.audience_size ?? 0}
            conversion={control?.conversion_rate}
            revenue={control?.revenue}
          />
          {isMultiArm ? (
            testVariants.map((variant) => {
              const result = experiment.results.find((r) => r.variant_key === variant.key);
              return (
                <ArmCard
                  key={variant.key}
                  title={variant.name}
                  subtitle={variant.offer_description || variant.description || "The intervention"}
                  size={variant.audience_size}
                  conversion={result?.conversion_rate}
                  revenue={result?.revenue}
                  incrementalRevenue={result?.incremental_revenue}
                  accent={variant.key === test?.variant_key}
                />
              );
            })
          ) : (
            <ArmCard
              title="Test"
              subtitle={testVariant?.offer_description || testVariant?.description || "The intervention"}
              size={testVariant?.audience_size ?? 0}
              conversion={test?.conversion_rate}
              revenue={test?.revenue}
              accent
            />
          )}
        </div>

        {isMultiArm && test && (
          <p className="text-2xs text-muted-foreground">
            The chart and headline numbers below follow{" "}
            <span className="font-medium text-foreground">{testVariant?.name ?? "the leading arm"}</span> -
            the arm with the highest incremental revenue.
          </p>
        )}

        {!experiment.results.length ? (
          <EmptyState
            icon={Play}
            title="Not measured yet"
            description={
              experiment.status === "PENDING_APPROVAL"
                ? "This experiment is waiting for approval before it can run."
                : "Run measurement to compute conversion, lift, incremental revenue and ROI from the transaction ledger."
            }
          />
        ) : (
          <>
            <Separator />

            {/* Results */}
            <div className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_minmax(0,1.1fr)]">
              <div>
                <p className="mb-2 text-2xs font-semibold uppercase tracking-widest text-muted-foreground">
                  Conversion rate
                </p>
                <ConversionCompareChart
                  control={control?.conversion_rate ?? 0}
                  test={test?.conversion_rate ?? 0}
                  height={190}
                />
              </div>

              <div className="grid grid-cols-2 gap-3 self-center">
                <ResultTile
                  label="Conversion lift"
                  value={test?.conversion_lift_pct ?? 0}
                  format={(n) => `${n >= 0 ? "+" : ""}${n.toFixed(1)}%`}
                  tone={(test?.conversion_lift_pct ?? 0) >= 0 ? "success" : "destructive"}
                  emphasis
                />
                <ResultTile
                  label="Incremental revenue"
                  value={test?.incremental_revenue ?? 0}
                  format={(n) => formatCompactCurrency(n)}
                  tone={(test?.incremental_revenue ?? 0) >= 0 ? "success" : "destructive"}
                  emphasis
                />
                <ResultTile
                  label="Incremental profit"
                  value={test?.incremental_profit ?? 0}
                  format={(n) => formatCompactCurrency(n)}
                  tone={(test?.incremental_profit ?? 0) >= 0 ? "success" : "destructive"}
                />
                <ResultTile
                  label="ROI"
                  value={test?.roi ?? 0}
                  format={(n) => `${n.toFixed(2)}x`}
                  tone={(test?.roi ?? 0) >= 1 ? "success" : "destructive"}
                />
              </div>
            </div>

            {/* Significance */}
            <div
              className={cn(
                "flex flex-wrap items-center gap-3 rounded-lg border p-3",
                test?.is_significant
                  ? "border-success/25 bg-success/6"
                  : "border-warning/25 bg-warning/6",
              )}
            >
              <BarChart3
                className={cn(
                  "h-4 w-4 shrink-0",
                  test?.is_significant ? "text-success" : "text-warning",
                )}
              />
              <div className="min-w-0 flex-1">
                <p className="text-sm font-medium">
                  {test?.is_significant
                    ? "Statistically significant"
                    : "Not statistically significant"}
                </p>
                <p className="text-2xs leading-relaxed text-muted-foreground">
                  Two-proportion z-test on conversion.{" "}
                  {test?.p_value != null
                    ? `p = ${test.p_value.toFixed(4)} against a 0.05 threshold.`
                    : "Sample too small for the test to mean anything."}{" "}
                  Significance says the difference is unlikely to be noise — it does not by itself
                  establish why.
                </p>
              </div>
            </div>

            {/* Decision */}
            <div className="rounded-xl border border-border bg-muted/30 p-4">
              <div className="flex flex-wrap items-center gap-2">
                <BadgeCheck className="h-4 w-4 text-primary" />
                <p className="text-2xs font-semibold uppercase tracking-widest text-muted-foreground">
                  Decision
                </p>
                <Badge variant={decision.variant}>{decision.label}</Badge>
              </div>
              <p className="mt-2 text-sm leading-relaxed">
                {experiment.decision_rationale || decision.copy}
              </p>
              {experiment.learning && (
                <>
                  <Separator className="my-3" />
                  <p className="flex items-center gap-1.5 text-2xs font-semibold uppercase tracking-widest text-muted-foreground">
                    <BookOpen className="h-3.5 w-3.5" />
                    What the business learned
                  </p>
                  <p className="mt-1 text-sm leading-relaxed text-muted-foreground">
                    {experiment.learning}
                  </p>
                </>
              )}
            </div>

            {test?.window_start && (
              <p className="text-2xs text-muted-foreground">
                Measured over {formatDate(test.window_start)} – {formatDate(test.window_end)} ·
                cost {formatCompactCurrency(test.cost)} ({formatNumber(test.converted_customers)}{" "}
                offers redeemed)
              </p>
            )}
          </>
        )}
      </CardContent>
    </Card>
  );
}

function ArmCard({
  title,
  subtitle,
  size,
  conversion,
  revenue,
  incrementalRevenue,
  accent,
}: {
  title: string;
  subtitle: string;
  size: number;
  conversion?: number;
  revenue?: number;
  incrementalRevenue?: number | null;
  accent?: boolean;
}) {
  return (
    <div
      className={cn(
        "rounded-xl border p-4",
        accent ? "border-primary/30 bg-primary/5" : "border-border bg-card",
      )}
    >
      <div className="flex items-center justify-between">
        <p className={cn("truncate text-sm font-semibold", accent && "text-primary")}>{title}</p>
        <span className="flex shrink-0 items-center gap-1 text-2xs text-muted-foreground">
          <Users className="h-3 w-3" />
          {formatNumber(size)}
        </span>
      </div>
      <p className="mt-0.5 line-clamp-2 text-xs leading-relaxed text-muted-foreground">
        {subtitle}
      </p>
      {conversion != null && (
        <div className="mt-3 flex items-baseline gap-2">
          <span className="text-xl font-semibold tnum">{formatPercent(conversion, 2)}</span>
          <span className="text-2xs text-muted-foreground">conversion</span>
        </div>
      )}
      {revenue != null && (
        <p className="mt-0.5 text-2xs text-muted-foreground tnum">
          {formatCompactCurrency(revenue)} revenue
        </p>
      )}
      {incrementalRevenue != null && (
        <p
          className={cn(
            "mt-0.5 text-2xs font-medium tnum",
            incrementalRevenue >= 0 ? "text-success" : "text-destructive",
          )}
        >
          {incrementalRevenue >= 0 ? "+" : ""}
          {formatCompactCurrency(incrementalRevenue)} incremental
        </p>
      )}
    </div>
  );
}

function ResultTile({
  label,
  value,
  format,
  tone,
  emphasis,
}: {
  label: string;
  value: number;
  format: (n: number) => string;
  tone: "success" | "destructive";
  emphasis?: boolean;
}) {
  return (
    <div
      className={cn(
        "rounded-lg border p-3",
        emphasis ? "border-border bg-card" : "border-transparent bg-muted/40",
      )}
    >
      <p className="text-2xs font-medium uppercase tracking-wide text-muted-foreground">{label}</p>
      <p
        className={cn(
          "mt-0.5 font-semibold leading-none",
          emphasis ? "text-xl" : "text-base",
          tone === "success" ? "text-success" : "text-destructive",
        )}
      >
        <AnimatedNumber value={value} format={format} />
      </p>
    </div>
  );
}
