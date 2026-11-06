"use client";

/**
 * Automation Center.
 *
 * Shows business state, not machine state: "reorder calculated, vendor selected,
 * order raised, waiting for approval" rather than "workflow 3 finished". Every
 * run carries the correlation id that ties it to the event that started it and
 * the ledger rows it produced.
 */

import {
  AlertTriangle,
  Check,
  ChevronRight,
  Clock,
  ExternalLink,
  Loader2,
  Pause,
  RefreshCw,
  GitBranch,
  Workflow,
} from "lucide-react";
import * as React from "react";

import { EmptyState, ErrorState, LoadingRows } from "@/components/common/states";
import { AutomationTraceDialog } from "@/components/inventory/automation-trace";
import { Button } from "@/components/ui/button";
import { Badge, Card, CardContent, CardHeader, CardTitle } from "@/components/ui/primitives";
import { useAutomationRuns } from "@/hooks/use-api";
import { useInventoryStream } from "@/hooks/use-inventory-stream";
import { inventoryApi } from "@/lib/api/endpoints";
import { n8nExecutionUrl } from "@/lib/n8n";
import { cn, formatRelativeTime } from "@/lib/utils";
import { useSearchParams } from "next/navigation";
import type { AutomationRunRow } from "@/types/api";
import { toast } from "sonner";

const FILTERS = [
  { value: "all", label: "All" },
  { value: "RUNNING", label: "Running" },
  { value: "COMPLETED", label: "Completed" },
  { value: "AWAITING_APPROVAL", label: "Awaiting approval" },
  { value: "SKIPPED", label: "Skipped" },
  { value: "FAILED", label: "Failed" },
];

const RUN_STATUS: Record<string, { chip: string; icon: typeof Check; label: string }> = {
  COMPLETED: { chip: "bg-success/10 text-success", icon: Check, label: "Completed" },
  RUNNING: { chip: "bg-primary/10 text-primary", icon: Loader2, label: "Running" },
  AWAITING_APPROVAL: {
    chip: "bg-warning/10 text-warning",
    icon: Clock,
    label: "Awaiting approval",
  },
  SKIPPED: { chip: "bg-muted text-muted-foreground", icon: Pause, label: "Skipped" },
  FAILED: { chip: "bg-destructive/10 text-destructive", icon: AlertTriangle, label: "Failed" },
};

const STEP_TONE: Record<string, string> = {
  ok: "border-success/40 bg-success/5",
  pending: "border-warning/40 bg-warning/5",
  warning: "border-warning/40 bg-warning/5",
  error: "border-destructive/40 bg-destructive/5",
  skipped: "border-border bg-muted/30",
};

export default function AutomationCenterPage() {
  const search = useSearchParams();
  const [filter, setFilter] = React.useState("all");
  const [openId, setOpenId] = React.useState<string | null>(null);
  const [dispatching, setDispatching] = React.useState(false);
  const [tracing, setTracing] = React.useState<string | null>(
    search?.get("correlation") ?? null,
  );

  useInventoryStream({ notify: false });

  const { data, isLoading, isFetching, error, refetch } = useAutomationRuns({
    page: 1,
    status: filter === "all" ? undefined : filter,
  });

  const runs = data?.data.items ?? [];
  const n8nBase = (data?.meta?.n8n_base_url as string | undefined) ?? "";

  async function flushOutbox() {
    setDispatching(true);
    try {
      const result = await inventoryApi.dispatch();
      toast.success("Outbox flushed", {
        description: `${result.delivered} delivered, ${result.failed} failed, ${result.skipped} skipped.`,
      });
      void refetch();
    } catch {
      toast.error("Could not flush the event outbox");
    } finally {
      setDispatching(false);
    }
  }

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h2 className="text-xl font-semibold tracking-tight">Automation Center</h2>
          <p className="text-sm text-muted-foreground">
            Every automated decision, the reason behind it, and what it produced
          </p>
        </div>
        <Button
          variant="outline"
          size="sm"
          className="gap-1.5"
          loading={dispatching}
          onClick={() => void flushOutbox()}
        >
          <RefreshCw className="h-3.5 w-3.5" />
          Flush event outbox
        </Button>
      </div>

      <div className="flex flex-wrap gap-1.5">
        {FILTERS.map((option) => (
          <button
            key={option.value}
            type="button"
            onClick={() => setFilter(option.value)}
            aria-pressed={filter === option.value}
            className={cn(
              "rounded-lg border px-3 py-1 text-xs font-medium transition-colors focus-ring",
              filter === option.value
                ? "border-primary bg-primary text-primary-foreground"
                : "border-border bg-card hover:bg-muted",
            )}
          >
            {option.label}
          </button>
        ))}
      </div>

      <Card>
        <CardHeader className="pb-3">
          <CardTitle className="text-base">Runs</CardTitle>
          <p className="text-sm text-muted-foreground">
            Recorded by the backend, so this works under your own permissions rather than
            n8n&apos;s.
          </p>
        </CardHeader>
        <CardContent className="space-y-2">
          {isLoading && <LoadingRows rows={4} />}
          {error && <ErrorState error={error} onRetry={() => void refetch()} />}

          {!isLoading && !error && runs.length === 0 && (
            <EmptyState
              icon={Workflow}
              title="No automation runs yet"
              description="Sell an item below its reorder point, or press Reorder on the inventory page."
            />
          )}

          <div className={cn("space-y-2", isFetching && "opacity-60")}>
            {runs.map((run) => (
              <RunCard
                key={run.id}
                run={run}
                open={openId === run.id}
                n8nBase={n8nBase}
                onToggle={() => setOpenId((current) => (current === run.id ? null : run.id))}
                onTrace={() => setTracing(run.correlation_id)}
              />
            ))}
          </div>
        </CardContent>
      </Card>

      <AutomationTraceDialog
        correlationId={tracing}
        n8nBase={n8nBase}
        onClose={() => setTracing(null)}
      />
    </div>
  );
}

function RunCard({
  run,
  open,
  n8nBase,
  onToggle,
  onTrace,
}: {
  run: AutomationRunRow;
  open: boolean;
  n8nBase: string;
  onToggle: () => void;
  onTrace: () => void;
}) {
  const meta = RUN_STATUS[run.status] ?? {
    chip: "bg-muted text-muted-foreground",
    icon: Workflow,
    label: run.status,
  };
  const Icon = meta.icon;

  return (
    <div className="rounded-xl border border-border bg-card">
      <button
        type="button"
        onClick={onToggle}
        className="flex w-full items-start gap-3 p-3 text-left transition-colors hover:bg-muted/40 focus-ring"
      >
        <span
          className={cn(
            "mt-0.5 flex h-8 w-8 shrink-0 items-center justify-center rounded-lg",
            meta.chip,
          )}
        >
          <Icon className={cn("h-4 w-4", run.status === "RUNNING" && "animate-spin")} />
        </span>

        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-2">
            <span className="font-mono text-sm font-medium">{run.workflow_name}</span>
            <span
              className={cn("rounded-md px-1.5 py-0.5 text-2xs font-semibold", meta.chip)}
            >
              {meta.label}
            </span>
            {run.is_dry_run && (
              <Badge variant="warning" className="text-2xs">
                dry run
              </Badge>
            )}
          </div>
          <p className="mt-1 text-2xs text-muted-foreground">
            {run.steps.length} steps · started {formatRelativeTime(run.started_at ?? "")}
            {run.correlation_id && (
              <>
                {" · "}
                <span className="font-mono">{run.correlation_id}</span>
              </>
            )}
          </p>
          {run.error && (
            <p className="mt-1 text-2xs text-destructive">{run.error}</p>
          )}
        </div>

        <ChevronRight
          className={cn(
            "mt-1 h-4 w-4 shrink-0 text-muted-foreground transition-transform",
            open && "rotate-90 text-primary",
          )}
        />
      </button>

      {open && (
        <div className="space-y-2 border-t border-border p-3">
          {run.steps.length === 0 && (
            <p className="text-2xs text-muted-foreground">No steps recorded.</p>
          )}

          <ol className="space-y-1.5">
            {run.steps.map((step, index) => (
              <li
                key={`${step.at}-${index}`}
                className={cn(
                  "rounded-lg border px-3 py-2",
                  STEP_TONE[step.status] ?? "border-border bg-muted/30",
                )}
              >
                <div className="flex flex-wrap items-baseline justify-between gap-2">
                  <span className="text-xs font-semibold">
                    {index + 1}. {step.step}
                  </span>
                  <span className="text-2xs text-muted-foreground tabular-nums">
                    {new Date(step.at).toLocaleTimeString()}
                  </span>
                </div>
                <p className="mt-0.5 text-2xs leading-relaxed text-muted-foreground">
                  {step.detail}
                </p>
              </li>
            ))}
          </ol>

          {run.correlation_id && (
            <button
              type="button"
              onClick={onTrace}
              className="inline-flex items-center gap-1.5 text-2xs font-medium text-primary hover:underline focus-ring"
            >
              <GitBranch className="h-3 w-3" />
              See the whole chain this belongs to
            </button>
          )}

          {run.n8n_execution_id && n8nBase && (
            <a
              href={n8nExecutionUrl(n8nBase, run.workflow_name, run.n8n_execution_id)}
              target="_blank"
              rel="noreferrer"
              className="inline-flex items-center gap-1.5 text-2xs font-medium text-primary hover:underline"
            >
              <ExternalLink className="h-3 w-3" />
              Open execution {run.n8n_execution_id} in n8n
            </a>
          )}
        </div>
      )}
    </div>
  );
}
