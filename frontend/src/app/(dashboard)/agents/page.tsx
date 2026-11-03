"use client";

import { useQuery } from "@tanstack/react-query";
import { AnimatePresence, motion } from "framer-motion";
import {
  ArrowRight,
  BarChart3,
  Bot,
  FlaskConical,
  Loader2,
  MessageSquare,
  Mic,
  Search,
  Send,
  Target,
  TrendingUp,
  Wrench,
  Zap,
} from "lucide-react";
import Link from "next/link";
import * as React from "react";

import { AgentTrace } from "@/components/agents/agent-trace";
import { ErrorState, LoadingRows } from "@/components/common/states";
import { RecommendationPanel } from "@/components/growth/recommendation-panel";
import { Button } from "@/components/ui/button";
import { FadeIn, Stagger, StaggerItem } from "@/components/ui/motion";
import {
  Badge,
  Card,
  CardContent,
  CardHeader,
  CardTitle,
  Input,
  Separator,
} from "@/components/ui/primitives";
import { useAgentRun, useAgentRuns, useAskAgent } from "@/hooks/use-api";
import { agentApi } from "@/lib/api/endpoints";
import { cn, formatDuration, formatRelativeTime } from "@/lib/utils";
import { useAuthStore } from "@/stores/auth";
import type { AgentRunResponse } from "@/types/api";

const SUGGESTIONS = [
  "Why did my revenue fall this month?",
  "What is my biggest growth opportunity?",
  "Which product is performing badly?",
  "What should I do today?",
];

const QUICK_ACTIONS = [
  {
    icon: TrendingUp,
    label: "Run Growth Analysis",
    href: "/growth",
    color: "bg-violet-500/10 text-violet-600 dark:text-violet-400",
  },
  {
    icon: Target,
    label: "Explore Opportunities",
    href: "/opportunities",
    color: "bg-blue-500/10 text-blue-600 dark:text-blue-400",
  },
  {
    icon: BarChart3,
    label: "Review Campaigns",
    href: "/campaigns",
    color: "bg-emerald-500/10 text-emerald-600 dark:text-emerald-400",
  },
  {
    icon: Search,
    label: "Analyze Competitors",
    href: "/competitors",
    color: "bg-amber-500/10 text-amber-600 dark:text-amber-400",
  },
  {
    icon: Zap,
    label: "Get AI Suggestions",
    href: "/agents",
    color: "bg-pink-500/10 text-pink-600 dark:text-pink-400",
    onClick: true,
  },
];

function greeting() {
  const hour = new Date().getHours();
  if (hour < 12) return "Good Morning";
  if (hour < 17) return "Good Afternoon";
  return "Good Evening";
}

export default function AgentsPage() {
  const { data, isLoading, error, refetch } = useAgentRuns({ limit: 25 });
  const tools = useQuery({ queryKey: ["agent-tools"], queryFn: agentApi.tools });
  const ask = useAskAgent();
  const canRun = useAuthStore((s) => s.can("agents:run"));
  const user = useAuthStore((s) => s.user);

  const [question, setQuestion] = React.useState("");
  const [answer, setAnswer] = React.useState<AgentRunResponse | null>(null);
  const [selectedRunId, setSelectedRunId] = React.useState<string | null>(null);
  const inputRef = React.useRef<HTMLInputElement>(null);

  const firstName = user?.user.full_name?.split(" ")[0] ?? "Merchant";

  async function submit(text: string) {
    if (!text.trim()) return;
    setAnswer(null);
    setSelectedRunId(null);
    const result = await ask.mutateAsync({ message: text.trim() });
    setAnswer(result);
    setQuestion("");
  }

  return (
    <div className="space-y-8">
      {/* ── Hero: Greeting ── */}
      <FadeIn>
        <div className="flex flex-col items-center gap-5 rounded-3xl border border-border/60 bg-gradient-to-br from-primary/5 via-background to-violet-500/5 px-6 py-10 text-center shadow-sm">
          {/* Orb avatar */}
          <div
            className="relative flex h-20 w-20 items-center justify-center rounded-full"
            style={{
              background:
                "radial-gradient(circle at 35% 35%, hsl(var(--primary)), hsl(260 80% 60%), hsl(200 90% 50%))",
              boxShadow:
                "0 0 40px hsl(var(--primary) / 0.35), 0 0 80px hsl(260 80% 60% / 0.15)",
            }}
          >
            <Bot className="h-8 w-8 text-white drop-shadow-lg" />
            {/* Pulse ring */}
            <span className="absolute inset-0 animate-ping rounded-full bg-primary/20 [animation-duration:2.5s]" />
          </div>

          <div>
            <p className="text-xs font-semibold uppercase tracking-widest text-muted-foreground">
              AI Assistant
            </p>
            <h1 className="mt-1 text-2xl font-bold tracking-tight">
              {greeting()}, {firstName}
            </h1>
            <p className="mt-1 text-sm text-muted-foreground">
              Let&apos;s grow your business today.
            </p>
            <p className="text-xs text-muted-foreground/60">
              Your AI Growth Scientist — ask anything, anytime.
            </p>
          </div>

          {/* Ask anything input */}
          {canRun && (
            <div className="w-full max-w-xl">
              <div className="relative">
                <form
                  onSubmit={(e) => {
                    e.preventDefault();
                    void submit(question);
                  }}
                  className="flex items-center gap-2 rounded-2xl border border-border/80 bg-card px-4 py-3 shadow-sm focus-within:border-primary/60 focus-within:ring-2 focus-within:ring-primary/15 transition-all"
                >
                  <FlaskConical className="h-4 w-4 shrink-0 text-muted-foreground" />
                  <input
                    ref={inputRef}
                    value={question}
                    onChange={(e) => setQuestion(e.target.value)}
                    placeholder="Ask anything…"
                    disabled={ask.isPending}
                    className="flex-1 bg-transparent text-sm outline-none placeholder:text-muted-foreground/60 disabled:opacity-60"
                  />
                  <Button
                    type="submit"
                    size="icon"
                    loading={ask.isPending}
                    className="h-8 w-8 shrink-0 rounded-xl"
                    disabled={!question.trim() || ask.isPending}
                    aria-label="Send"
                  >
                    <Send className="h-3.5 w-3.5" />
                  </Button>
                </form>
              </div>

              {/* Suggestion pills */}
              <div className="mt-3 flex flex-wrap justify-center gap-2">
                {SUGGESTIONS.map((s) => (
                  <button
                    key={s}
                    type="button"
                    onClick={() => void submit(s)}
                    disabled={ask.isPending}
                    className="rounded-full border border-border/70 bg-card px-3 py-1.5 text-xs text-muted-foreground transition-all hover:border-primary/50 hover:bg-primary/5 hover:text-foreground disabled:opacity-50"
                  >
                    {s}
                  </button>
                ))}
              </div>
            </div>
          )}
        </div>
      </FadeIn>

      {/* ── Answer panel ── */}
      <AnimatePresence>
        {answer && (
          <FadeIn className="space-y-4">
            <Card className="border-primary/30 bg-primary/3">
              <CardContent className="space-y-3 p-5">
                <div className="flex items-center gap-2">
                  <div className="flex h-7 w-7 items-center justify-center rounded-lg bg-primary text-primary-foreground">
                    <Bot className="h-4 w-4" />
                  </div>
                  <p className="text-sm font-semibold">Growth Scientist</p>
                </div>
                <p className="whitespace-pre-line text-sm leading-relaxed">{answer.answer}</p>
                {answer.suggested_followups.length > 0 && (
                  <div className="flex flex-wrap gap-1.5 pt-1">
                    {answer.suggested_followups.map((followup) => (
                      <button
                        key={followup}
                        type="button"
                        onClick={() => void submit(followup)}
                        className="rounded-full border border-border px-2.5 py-1 text-xs text-muted-foreground transition-colors hover:border-primary/40 hover:text-foreground"
                      >
                        {followup}
                      </button>
                    ))}
                  </div>
                )}
              </CardContent>
            </Card>

            {answer.recommendation && answer.recommendation.estimated_impact > 0 && (
              <RecommendationPanel
                recommendation={answer.recommendation}
                usedFallback={answer.run.used_fallback}
              />
            )}
            <AgentTrace run={answer.run} defaultOpen={false} />
          </FadeIn>
        )}
      </AnimatePresence>

      {/* ── Voice Agent Bridge ── */}
      <div className="flex items-center gap-4 rounded-2xl border border-primary/20 bg-gradient-to-r from-primary/5 via-violet-500/5 to-transparent p-4 shadow-xs">
        <div
          className="flex h-12 w-12 shrink-0 items-center justify-center rounded-2xl"
          style={{ background: "radial-gradient(circle at 35% 35%, hsl(var(--primary)), hsl(260 80% 55%))" }}
        >
          <Mic className="h-5 w-5 text-white" />
        </div>
        <div className="min-w-0 flex-1">
          <p className="font-semibold text-sm">Prefer to talk instead of type?</p>
          <p className="text-xs text-muted-foreground mt-0.5">
            Switch to the AI Voice Assistant — same intelligence, hands-free.
          </p>
        </div>
        <Button asChild size="sm" className="shrink-0 gap-2">
          <Link href="/voice">
            <Mic className="h-3.5 w-3.5" />
            Use Voice Agent
          </Link>
        </Button>
      </div>

      {/* ── Quick Actions ── */}
      <section className="space-y-3">
        <p className="text-xs font-bold uppercase tracking-widest text-muted-foreground">
          Quick Actions
        </p>
        <div className="flex flex-wrap gap-2">
          {QUICK_ACTIONS.map((action) => (
            <Link
              key={action.label}
              href={action.href}
              className="group flex items-center gap-2 rounded-full border border-border/70 bg-card px-4 py-2 text-sm font-medium text-foreground/80 shadow-xs transition-all hover:border-primary/40 hover:bg-primary/5 hover:text-foreground hover:shadow-sm"
            >
              <span className={cn("flex h-6 w-6 items-center justify-center rounded-full", action.color)}>
                <action.icon className="h-3.5 w-3.5" />
              </span>
              {action.label}
              <ArrowRight className="h-3 w-3 opacity-0 transition-all group-hover:opacity-100 group-hover:translate-x-0.5" />
            </Link>
          ))}
        </div>
      </section>

      {/* ── Performance Snapshot ── */}
      {data && data.items.length > 0 && (
        <section className="space-y-3">
          <p className="text-xs font-bold uppercase tracking-widest text-muted-foreground">
            Performance Snapshot
          </p>
          <div className="grid gap-4 sm:grid-cols-3">
            <SnapshotCard
              label="Tasks Run This Week"
              value={String(data.total_runs)}
              sub={`${data.completed_runs} completed`}
              color="from-violet-500/10 to-violet-500/5"
              icon={FlaskConical}
            />
            <SnapshotCard
              label="Agent Processing Time"
              value={formatDuration(data.avg_duration_ms)}
              sub="Average per run"
              color="from-amber-500/10 to-amber-500/5"
              icon={TrendingUp}
            />
            <SnapshotCard
              label="Active Investigations"
              value={String(
                data.items.filter((r) => r.status === "RUNNING" || r.status === "PENDING").length,
              )}
              sub="In progress now"
              color="from-emerald-500/10 to-emerald-500/5"
              icon={Zap}
            />
          </div>
        </section>
      )}

      <Separator />

      {/* ── Agent Activity + Tool Catalogue ── */}
      <div className="grid gap-6 lg:grid-cols-[minmax(0,1fr)_minmax(0,300px)]">
        {/* Feed */}
        <section className="space-y-3">
          <div className="flex items-center justify-between">
            <p className="text-xs font-bold uppercase tracking-widest text-muted-foreground">
              Agent Activity
            </p>
            <p className="text-xs text-muted-foreground">
              What the agents did, which tools they called, and what they decided
            </p>
          </div>

          {isLoading && <LoadingRows rows={4} />}
          {error && <ErrorState error={error} onRetry={() => void refetch()} />}

          {data && data.items.length > 0 && (
            <Stagger className="space-y-2">
              {data.items.map((item) => (
                <StaggerItem key={item.run_id}>
                  <button
                    type="button"
                    onClick={() =>
                      setSelectedRunId((c) => (c === item.run_id ? null : item.run_id))
                    }
                    className={cn(
                      "w-full rounded-xl border p-4 text-left transition-all focus-ring",
                      selectedRunId === item.run_id
                        ? "border-primary/50 bg-primary/5 shadow-sm"
                        : "border-border bg-card hover:border-primary/30 hover:shadow-xs",
                    )}
                  >
                    <div className="flex flex-wrap items-center gap-2">
                      <Badge variant="outline">{item.agent_label}</Badge>
                      <Badge
                        variant={
                          item.status === "COMPLETED"
                            ? "success"
                            : item.status === "FAILED"
                              ? "destructive"
                              : "warning"
                        }
                      >
                        {item.status.replace("_", " ").toLowerCase()}
                      </Badge>
                      {item.used_fallback && <Badge variant="muted">Deterministic</Badge>}
                      <span className="ml-auto text-xs text-muted-foreground">
                        {formatRelativeTime(item.created_at)}
                      </span>
                    </div>
                    <p className="mt-2 line-clamp-2 text-sm font-medium">{item.title}</p>
                    {item.decision && (
                      <p className="mt-1 line-clamp-1 text-xs text-primary">
                        Decision: {item.decision}
                      </p>
                    )}
                    {item.tools_used.length > 0 && (
                      <div className="mt-2 flex flex-wrap gap-1">
                        {item.tools_used.slice(0, 5).map((tool) => (
                          <span
                            key={tool}
                            className="rounded bg-muted px-1.5 py-0.5 font-mono text-xs text-muted-foreground"
                          >
                            {tool}
                          </span>
                        ))}
                        {item.tools_used.length > 5 && (
                          <span className="text-xs text-muted-foreground">
                            +{item.tools_used.length - 5}
                          </span>
                        )}
                      </div>
                    )}
                  </button>
                </StaggerItem>
              ))}
            </Stagger>
          )}

          {selectedRunId && <RunTrace runId={selectedRunId} />}
        </section>

        {/* Tool catalogue */}
        <Card className="h-fit lg:sticky lg:top-24">
          <CardHeader>
            <CardTitle className="flex items-center gap-2 text-base">
              <Wrench className="h-4 w-4" />
              Tool Catalogue
            </CardTitle>
            <p className="text-xs text-muted-foreground">
              Every capability the agents can reach
            </p>
          </CardHeader>
          <CardContent className="max-h-[32rem] space-y-1.5 overflow-y-auto">
            {tools.data?.map((tool) => (
              <div key={tool.name} className="rounded-lg border border-border p-2.5">
                <div className="flex items-start justify-between gap-2">
                  <p className="font-mono text-xs font-medium">{tool.name}</p>
                  {tool.requires_approval && <Badge variant="warning">gated</Badge>}
                </div>
                <p className="mt-0.5 line-clamp-2 text-xs leading-relaxed text-muted-foreground">
                  {tool.description}
                </p>
                {tool.permission && (
                  <p className="mt-1 font-mono text-xs text-primary">{tool.permission}</p>
                )}
              </div>
            ))}
          </CardContent>
        </Card>
      </div>
    </div>
  );
}

function RunTrace({ runId }: { runId: string }) {
  const { data, isLoading } = useAgentRun(runId);
  if (isLoading) return <LoadingRows rows={3} />;
  if (!data) return null;
  return (
    <FadeIn>
      <AgentTrace run={data} />
    </FadeIn>
  );
}

function SnapshotCard({
  label,
  value,
  sub,
  color,
  icon: Icon,
}: {
  label: string;
  value: string;
  sub: string;
  color: string;
  icon: typeof FlaskConical;
}) {
  return (
    <div
      className={cn(
        "relative overflow-hidden rounded-2xl border border-border/60 bg-gradient-to-br p-5",
        color,
      )}
    >
      <div className="flex items-start justify-between">
        <div>
          <p className="text-xs font-semibold text-muted-foreground">{label}</p>
          <p className="mt-1.5 text-3xl font-bold tracking-tight tabular-nums">{value}</p>
          <p className="mt-1 flex items-center gap-1 text-xs text-muted-foreground">
            <TrendingUp className="h-3 w-3 text-emerald-500" />
            {sub}
          </p>
        </div>
        <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-background/60 text-muted-foreground">
          <Icon className="h-5 w-5" />
        </div>
      </div>
    </div>
  );
}

function StatCard({
  label,
  value,
  tone,
}: {
  label: string;
  value: string;
  tone?: "success";
}) {
  return (
    <Card>
      <CardContent className="p-4">
        <p className="text-xs font-medium uppercase tracking-wide text-muted-foreground">{label}</p>
        <p className={cn("mt-0.5 text-xl font-semibold tabular-nums", tone === "success" && "text-success")}>
          {value}
        </p>
      </CardContent>
    </Card>
  );
}
