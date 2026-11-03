"use client";

/**
 * AI Observability — Langfuse trace explorer.
 *
 * Shows every agent run with its Langfuse trace ID, token usage, latency,
 * step breakdown and a direct link to the full waterfall in Langfuse.
 *
 * Data comes from the existing /agents/runs + /agents/runs/:id endpoints
 * (which already return trace_id, trace_url, total_tokens, duration_ms).
 * The settings endpoint tells us whether Langfuse is configured so we can
 * show a helpful "not connected" state.
 */

import { AnimatePresence, motion } from "framer-motion";
import {
  Activity,
  AlertTriangle,
  Bot,
  CheckCircle2,
  ChevronRight,
  CircleDashed,
  Clock,
  ExternalLink,
  Eye,
  Filter,
  Loader2,
  RefreshCw,
  ScanSearch,
  Sparkles,
  Wrench,
  XCircle,
} from "lucide-react";
import * as React from "react";

import { AgentTrace } from "@/components/agents/agent-trace";
import { ErrorState, LoadingRows } from "@/components/common/states";
import { FadeIn, Stagger, StaggerItem } from "@/components/ui/motion";
import {
  Badge,
  Card,
  CardContent,
  CardHeader,
  CardTitle,
} from "@/components/ui/primitives";
import { useAgentRun, useAgentRuns, useSettings } from "@/hooks/use-api";
import { cn, formatDuration, formatRelativeTime } from "@/lib/utils";
import type { AgentActivityItem } from "@/types/api";

// --------------------------------------------------------------------------- //
// Helpers
// --------------------------------------------------------------------------- //
const STATUS_META: Record<
  string,
  { label: string; icon: React.ElementType; colour: string }
> = {
  COMPLETED: { label: "Completed", icon: CheckCircle2, colour: "text-emerald-500" },
  AWAITING_APPROVAL: { label: "Awaiting approval", icon: Eye, colour: "text-amber-500" },
  RUNNING: { label: "Running", icon: Loader2, colour: "text-blue-500" },
  FAILED: { label: "Failed", icon: XCircle, colour: "text-red-500" },
  PENDING: { label: "Pending", icon: CircleDashed, colour: "text-muted-foreground" },
  CANCELLED: { label: "Cancelled", icon: XCircle, colour: "text-muted-foreground" },
};

const WORKFLOW_COLOUR: Record<string, string> = {
  investigate: "bg-violet-500/15 text-violet-700 dark:text-violet-300",
  ask: "bg-blue-500/15 text-blue-700 dark:text-blue-300",
  execute: "bg-emerald-500/15 text-emerald-700 dark:text-emerald-300",
  measure: "bg-amber-500/15 text-amber-700 dark:text-amber-300",
};

function statusMeta(status: string) {
  return (
    STATUS_META[status] ?? {
      label: status,
      icon: CircleDashed,
      colour: "text-muted-foreground",
    }
  );
}

function workflowColour(wf: string) {
  return WORKFLOW_COLOUR[wf?.toLowerCase()] ?? "bg-muted text-muted-foreground";
}

// --------------------------------------------------------------------------- //
// Stat card
// --------------------------------------------------------------------------- //
function StatCard({
  icon: Icon,
  label,
  value,
  sub,
}: {
  icon: React.ElementType;
  label: string;
  value: string | number;
  sub?: string;
}) {
  return (
    <Card>
      <CardContent className="flex items-center gap-4 p-4">
        <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-primary/10">
          <Icon className="h-5 w-5 text-primary" />
        </div>
        <div className="min-w-0">
          <p className="text-2xs font-semibold uppercase tracking-widest text-muted-foreground">
            {label}
          </p>
          <p className="mt-0.5 text-xl font-bold leading-none">{value}</p>
          {sub && (
            <p className="mt-0.5 text-2xs text-muted-foreground">{sub}</p>
          )}
        </div>
      </CardContent>
    </Card>
  );
}

// --------------------------------------------------------------------------- //
// Langfuse status banner
// --------------------------------------------------------------------------- //
function LangfuseBanner({ host }: { host: string }) {
  return (
    <a
      href={host}
      target="_blank"
      rel="noreferrer"
      className="group flex items-center gap-3 rounded-xl border border-violet-500/30 bg-gradient-to-r from-violet-500/10 via-purple-500/5 to-transparent px-4 py-3 text-sm transition-all hover:border-violet-500/60 hover:from-violet-500/15"
    >
      <span className="flex h-7 w-7 shrink-0 items-center justify-center rounded-lg bg-violet-500/20">
        <ScanSearch className="h-4 w-4 text-violet-500" />
      </span>
      <div className="min-w-0 flex-1">
        <p className="font-semibold text-violet-700 dark:text-violet-300">
          Langfuse connected
        </p>
        <p className="truncate text-2xs text-muted-foreground">{host}</p>
      </div>
      <ExternalLink className="h-4 w-4 shrink-0 text-violet-400 transition-transform group-hover:translate-x-0.5" />
    </a>
  );
}

function LangfuseDisabledBanner() {
  return (
    <div className="flex items-center gap-3 rounded-xl border border-amber-500/30 bg-amber-500/5 px-4 py-3 text-sm">
      <AlertTriangle className="h-5 w-5 shrink-0 text-amber-500" />
      <div>
        <p className="font-semibold text-amber-700 dark:text-amber-300">
          Langfuse not configured
        </p>
        <p className="text-2xs text-muted-foreground">
          Add <code className="font-mono">LANGFUSE_PUBLIC_KEY</code>,{" "}
          <code className="font-mono">LANGFUSE_SECRET_KEY</code> and{" "}
          <code className="font-mono">LANGFUSE_BASE_URL</code> to your{" "}
          <code className="font-mono">.env</code> to enable trace forwarding.
        </p>
      </div>
    </div>
  );
}

// --------------------------------------------------------------------------- //
// Run row
// --------------------------------------------------------------------------- //
function RunRow({
  item,
  selected,
  onSelect,
}: {
  item: AgentActivityItem;
  selected: boolean;
  onSelect: () => void;
}) {
  const { icon: StatusIcon, colour } = statusMeta(item.status);

  return (
    <motion.button
      initial={{ opacity: 0, y: 6 }}
      animate={{ opacity: 1, y: 0 }}
      onClick={onSelect}
      className={cn(
        "group w-full rounded-xl border p-4 text-left transition-all hover:border-primary/40 hover:bg-muted/40",
        selected
          ? "rounded-b-none border-primary/60 bg-primary/5 ring-1 ring-primary/20"
          : "border-border bg-card",
      )}
    >
      <div className="flex items-start gap-3">
        {/* Status icon */}
        <div className="mt-0.5 flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-muted">
          <StatusIcon
            className={cn("h-4 w-4", colour, item.status === "RUNNING" && "animate-spin")}
          />
        </div>

        {/* Main content */}
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-2">
            <span
              className={cn(
                "inline-flex items-center gap-1 rounded-md px-1.5 py-0.5 text-2xs font-semibold",
                workflowColour(item.workflow),
              )}
            >
              {item.workflow}
            </span>
            <span className="text-2xs text-muted-foreground">{item.agent_label}</span>
            {item.channel === "voice" && (
              <Badge variant="outline" className="text-2xs">
                Voice
              </Badge>
            )}
            {item.used_fallback && (
              <Badge variant="muted" className="text-2xs">
                Deterministic
              </Badge>
            )}
          </div>
          <p className="mt-1 truncate text-sm font-medium leading-snug">
            {item.title}
          </p>
          <div className="mt-1.5 flex flex-wrap items-center gap-3 text-2xs text-muted-foreground">
            <span className="flex items-center gap-1">
              <Clock className="h-3 w-3" />
              {item.duration_ms != null ? formatDuration(item.duration_ms) : "—"}
            </span>
            {item.tools_used.length > 0 && (
              <span className="flex items-center gap-1">
                <Wrench className="h-3 w-3" />
                {item.tools_used.length} tools
              </span>
            )}
            {item.confidence != null && (
              <span className="flex items-center gap-1">
                <Sparkles className="h-3 w-3" />
                {Math.round(item.confidence * 100)}% conf.
              </span>
            )}
            <span>{formatRelativeTime(item.created_at)}</span>
          </div>
        </div>

        {/* Chevron */}
        <ChevronRight
          className={cn(
            "mt-1 h-4 w-4 shrink-0 text-muted-foreground transition-all",
            selected && "rotate-90 text-primary",
          )}
        />
      </div>
    </motion.button>
  );
}

// --------------------------------------------------------------------------- //
// Run detail panel
// --------------------------------------------------------------------------- //
function RunDetailPanel({ runId }: { runId: string }) {
  const { data, isLoading, error } = useAgentRun(runId);

  if (isLoading) {
    return (
      <div className="flex flex-col gap-4">
        <LoadingRows rows={4} />
      </div>
    );
  }
  if (error || !data) {
    return (
      <ErrorState error={error ?? new Error("Run not found.")} />
    );
  }

  return (
    <FadeIn>
      <div className="space-y-4">
        {/* Trace header */}
        <Card>
          <CardHeader className="pb-3">
            <CardTitle className="text-base">Langfuse trace</CardTitle>
          </CardHeader>
          <CardContent className="space-y-3">
            <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
              <div>
                <p className="text-2xs font-medium uppercase tracking-widest text-muted-foreground">
                  Trace ID
                </p>
                <p className="mt-0.5 font-mono text-xs text-foreground">
                  {data.trace_id ? (
                    <span>{data.trace_id.slice(0, 16)}…</span>
                  ) : (
                    <span className="text-muted-foreground">—</span>
                  )}
                </p>
              </div>
              <div>
                <p className="text-2xs font-medium uppercase tracking-widest text-muted-foreground">
                  Duration
                </p>
                <p className="mt-0.5 text-sm font-semibold">
                  {data.duration_ms != null ? formatDuration(data.duration_ms) : "—"}
                </p>
              </div>
              <div>
                <p className="text-2xs font-medium uppercase tracking-widest text-muted-foreground">
                  Tokens
                </p>
                <p className="mt-0.5 text-sm font-semibold">
                  {data.total_tokens != null
                    ? data.total_tokens.toLocaleString()
                    : data.used_fallback
                    ? "0 (deterministic)"
                    : "—"}
                </p>
              </div>
              <div>
                <p className="text-2xs font-medium uppercase tracking-widest text-muted-foreground">
                  Model
                </p>
                <p className="mt-0.5 font-mono text-xs">
                  {data.model ?? (data.used_fallback ? "heuristic" : "—")}
                </p>
              </div>
            </div>

            {data.trace_url ? (
              <a
                href={data.trace_url}
                target="_blank"
                rel="noreferrer"
                className="inline-flex items-center gap-2 rounded-lg border border-violet-500/40 bg-violet-500/10 px-3 py-2 text-sm font-medium text-violet-700 transition-colors hover:bg-violet-500/20 dark:text-violet-300"
              >
                <ScanSearch className="h-4 w-4" />
                Open in Langfuse
                <ExternalLink className="h-3.5 w-3.5" />
              </a>
            ) : (
              <p className="text-2xs text-muted-foreground">
                No Langfuse URL — either tracing is disabled or this run predates the
                integration.
              </p>
            )}
          </CardContent>
        </Card>

        {/* Step-level trace */}
        <AgentTrace run={data} defaultOpen />
      </div>
    </FadeIn>
  );
}

// --------------------------------------------------------------------------- //
// Main page
// --------------------------------------------------------------------------- //
const FILTERS = ["All", "investigate", "ask", "execute", "measure"] as const;
type ObsFilter = (typeof FILTERS)[number];

export default function ObservabilityPage() {
  const [filter, setFilter] = React.useState<ObsFilter>("All");
  const [selectedId, setSelectedId] = React.useState<string | null>(null);

  const { data, isLoading, error, refetch, isFetching } = useAgentRuns({
    limit: 50,
  });
  const settings = useSettings();

  // Derive integration status from settings
  const langfuseHost =
    settings.data?.integrations?.langfuse?.configured
      ? settings.data.integrations.langfuse.host
      : null;

  // Filter items
  const items = React.useMemo(() => {
    if (!data?.items) return [];
    if (filter === "All") return data.items;
    return data.items.filter(
      (i) => i.workflow?.toLowerCase() === filter.toLowerCase(),
    );
  }, [data, filter]);

  // Aggregate stats
  const stats = React.useMemo(() => {
    const all = data?.items ?? [];
    const completed = all.filter((i) => i.status === "COMPLETED").length;
    const failed = all.filter((i) => i.status === "FAILED").length;
    const withDuration = all.filter((i) => i.duration_ms != null);
    const avgMs =
      withDuration.length > 0
        ? withDuration.reduce((s, i) => s + (i.duration_ms ?? 0), 0) /
          withDuration.length
        : null;
    return { total: all.length, completed, failed, avgMs };
  }, [data]);

  // Deselect on filter change
  React.useEffect(() => setSelectedId(null), [filter]);


  return (
    <div className="space-y-6">
      {/* Page header */}
      <FadeIn>
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div className="flex items-center gap-2.5">
            <div className="flex h-9 w-9 items-center justify-center rounded-xl bg-primary/10">
              <ScanSearch className="h-5 w-5 text-primary" />
            </div>
            <div>
              <h1 className="text-xl font-bold leading-none">AI Observability</h1>
              <p className="mt-0.5 text-sm text-muted-foreground">
                Langfuse traces · token usage · latency · per-run steps
              </p>
            </div>
          </div>
          <button
            onClick={() => void refetch()}
            disabled={isFetching}
            className="inline-flex items-center gap-1.5 rounded-lg border border-border bg-card px-3 py-1.5 text-sm font-medium transition-colors hover:bg-muted disabled:opacity-50"
          >
            <RefreshCw className={cn("h-3.5 w-3.5", isFetching && "animate-spin")} />
            Refresh
          </button>
        </div>
      </FadeIn>

      {/* Langfuse connection status */}
      <FadeIn>
        {settings.isLoading ? null : langfuseHost ? (
          <LangfuseBanner host={langfuseHost} />
        ) : (
          <LangfuseDisabledBanner />
        )}
      </FadeIn>

      {/* Stats row */}
      <Stagger className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <StaggerItem>
          <StatCard
            icon={Activity}
            label="Total runs"
            value={stats.total}
            sub="across all workflows"
          />
        </StaggerItem>
        <StaggerItem>
          <StatCard
            icon={CheckCircle2}
            label="Completed"
            value={stats.completed}
            sub={`${stats.total > 0 ? Math.round((stats.completed / stats.total) * 100) : 0}% success rate`}
          />
        </StaggerItem>
        <StaggerItem>
          <StatCard
            icon={XCircle}
            label="Failed"
            value={stats.failed}
            sub={stats.failed > 0 ? "check traces for details" : "all good"}
          />
        </StaggerItem>
        <StaggerItem>
          <StatCard
            icon={Clock}
            label="Avg latency"
            value={stats.avgMs != null ? formatDuration(stats.avgMs) : "—"}
            sub="per agent run"
          />
        </StaggerItem>
      </Stagger>

      {/* Top tools */}
      {data?.top_tools && data.top_tools.length > 0 && (
        <FadeIn>
          <Card>
            <CardHeader className="pb-2">
              <CardTitle className="flex items-center gap-2 text-sm">
                <Wrench className="h-4 w-4 text-muted-foreground" />
                Most-called tools
              </CardTitle>
            </CardHeader>
            <CardContent>
              <div className="flex flex-wrap gap-2">
                {data.top_tools.map((t) => (
                  <div
                    key={t.tool}
                    className="flex items-center gap-1.5 rounded-lg border border-border bg-muted/50 px-2.5 py-1.5"
                  >
                    <span className="font-mono text-xs font-medium">{t.tool}</span>
                    <span className="rounded bg-primary/10 px-1 py-0.5 text-2xs font-semibold text-primary">
                      ×{t.calls}
                    </span>
                  </div>
                ))}
              </div>
            </CardContent>
          </Card>
        </FadeIn>
      )}

      {/* Filter tabs */}
      <FadeIn>
        <div className="flex items-center gap-2">
          <Filter className="h-4 w-4 shrink-0 text-muted-foreground" />
          <div className="flex flex-wrap gap-1.5">
            {FILTERS.map((f) => (
              <button
                key={f}
                id={`obs-filter-${f}`}
                onClick={() => setFilter(f)}
                className={cn(
                  "rounded-lg px-3 py-1.5 text-sm font-medium transition-colors",
                  filter === f
                    ? "bg-primary text-primary-foreground"
                    : "bg-muted text-muted-foreground hover:text-foreground",
                )}
              >
                {f.charAt(0).toUpperCase() + f.slice(1)}
              </button>
            ))}
          </div>
        </div>
      </FadeIn>

      {/* Run list - each row expands in place */}
      <div>
        <div className="space-y-2">
          {isLoading ? (
            <LoadingRows rows={6} />
          ) : error ? (
            <ErrorState error={error} onRetry={() => void refetch()} />
          ) : items.length === 0 ? (
            <div className="flex flex-col items-center gap-3 rounded-xl border border-dashed border-border py-16 text-center">
              <Bot className="h-10 w-10 text-muted-foreground/40" />
              <div>
                <p className="text-sm font-medium text-muted-foreground">No runs yet</p>
                <p className="text-2xs text-muted-foreground">
                  Run the Growth Scientist from the Agents page to see traces here.
                </p>
              </div>
            </div>
          ) : (
            items.map((item) => {
              const open = selectedId === item.run_id;
              return (
                <div key={item.run_id}>
                  <RunRow
                    item={item}
                    selected={open}
                    onSelect={() =>
                      setSelectedId((prev) => (prev === item.run_id ? null : item.run_id))
                    }
                  />

                  {/* The detail drops out of the row it belongs to. Animating
                      height needs overflow hidden, and `initial={false}` stops the
                      whole list playing an open animation on first paint. */}
                  <AnimatePresence initial={false}>
                    {open && (
                      <motion.div
                        initial={{ height: 0, opacity: 0 }}
                        animate={{ height: "auto", opacity: 1 }}
                        exit={{ height: 0, opacity: 0 }}
                        transition={{ duration: 0.22, ease: "easeOut" }}
                        className="overflow-hidden"
                      >
                        <div className="pt-2">
                          <RunDetailPanel runId={item.run_id} />
                        </div>
                      </motion.div>
                    )}
                  </AnimatePresence>
                </div>
              );
            })
          )}
        </div>

      </div>

      {/* Footer note */}
      <FadeIn>
        <p className="text-center text-2xs text-muted-foreground">
          Each row links to a Langfuse trace recording the full span tree — LLM generations,
          tool calls and token counts. Click a run then{" "}
          <strong className="text-foreground">Open in Langfuse</strong> to see the waterfall.
        </p>
      </FadeIn>
    </div>
  );
}
