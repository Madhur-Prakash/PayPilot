"use client";

/**
 * Merchant Growth Autopilot - analyse -> identify -> discover -> recommend -> estimate ->
 * present -> request approval. The run stops at the approval gate; execution and
 * measurement continue only from a human's click.
 */

import { Bot, Check, CircleDashed, Loader2, Rocket, ShieldCheck, XCircle } from "lucide-react";
import Link from "next/link";

import { AiBadge } from "@/components/discovery/shared";
import { StatusPill } from "@/components/supply/shared";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/primitives";
import { useAutopilot, useRunAutopilot } from "@/hooks/use-discovery";
import { cn, formatDuration, formatRelativeTime } from "@/lib/utils";
import { useAuthStore } from "@/stores/auth";

const STAGES = [
  "Analyze performance", "Identify opportunities", "Discover products (Channel3)", "Generate recommendations",
  "Estimate impact", "Present actions", "Request approval", "Execute (you)", "Track results",
];

export function AutopilotPanel() {
  const state = useAutopilot();
  const run = useRunAutopilot();
  const canRun = useAuthStore((s) => s.can("growth:recommend") && s.can("agents:run"));
  const result = run.data;
  const pipeline = state.data?.pipeline ?? {};
  const reached = result ? (result.requires_approval ? 7 : result.status === "FAILED" ? 0 : 6)
    : (pipeline.MEASURED ? 9 : pipeline.EXECUTED ? 8 : pipeline.RECOMMENDED || pipeline.APPROVED ? 7 : 0);

  return (
    <Card className="overflow-hidden">
      <CardContent className="space-y-4 p-5">
        <div className="flex flex-wrap items-start gap-3">
          <span className="flex h-10 w-10 items-center justify-center rounded-xl bg-primary text-primary-foreground"><Rocket className="h-5 w-5" /></span>
          <div className="min-w-0 flex-1">
            <p className="text-sm font-semibold">Merchant Growth Autopilot</p>
            <p className="text-xs text-muted-foreground">
              The Growth Strategy Agent analyses your sales, finds products on Channel3 and prepares recommendations.
              It stops at your approval - no agent can execute, buy or pay.
            </p>
            {state.data?.last_run && !result && (
              <p className="mt-1 text-2xs text-muted-foreground">Last run {formatRelativeTime(state.data.last_run.created_at)} · <StatusPill status={state.data.last_run.status} /></p>
            )}
          </div>
          <Button className="gap-1.5" loading={run.isPending} disabled={!canRun} onClick={() => run.mutate({ days: 30, max_recommendations: 4 })}
            title={canRun ? undefined : "Needs growth:recommend and agents:run"}>
            <Bot className="h-4 w-4" /> {run.isPending ? "Running agents…" : "Run autopilot"}
          </Button>
        </div>

        <ol className="grid gap-1.5 sm:grid-cols-3 lg:grid-cols-9">
          {STAGES.map((label, i) => {
            const done = i < reached;
            const active = run.isPending && i === 2;
            const gate = i === 6;
            return (
              <li key={label} className={cn("flex items-center gap-1.5 rounded-lg border px-2 py-1.5 text-2xs font-medium",
                done ? "border-success/30 bg-success/10 text-success" : active ? "border-primary/40 bg-primary/10 text-primary" : "border-border text-muted-foreground",
                gate && "border-dashed")}>
                {done ? <Check className="h-3 w-3 shrink-0" /> : active ? <Loader2 className="h-3 w-3 shrink-0 animate-spin" /> : gate ? <ShieldCheck className="h-3 w-3 shrink-0" /> : <CircleDashed className="h-3 w-3 shrink-0" />}
                <span className="leading-tight">{i + 1}. {label}</span>
              </li>
            );
          })}
        </ol>

        {result && (
          <div className="space-y-3 rounded-xl border border-border bg-muted/30 p-4">
            <div className="flex flex-wrap items-center gap-2">
              <StatusPill status={result.status} />
              {result.used_llm && <AiBadge label="AI-written summary" />}
              <span className="text-2xs text-muted-foreground">{formatDuration(result.duration_ms)} · {result.tool_calls.length} tool calls</span>
              <Link href="/agents/console" className="ml-auto text-xs text-primary hover:underline">Open trace</Link>
            </div>
            <p className="text-sm">{result.answer}</p>
            <ul className="space-y-1">
              {result.tool_calls.map((t, i) => (
                <li key={`${t.tool}-${i}`} className="flex items-start gap-2 text-2xs">
                  {t.ok ? <Check className="mt-0.5 h-3 w-3 shrink-0 text-success" /> : <XCircle className="mt-0.5 h-3 w-3 shrink-0 text-destructive" />}
                  <span className="font-mono text-muted-foreground">{t.tool}</span>
                  <span className="line-clamp-2">{t.ok ? t.summary : t.error}</span>
                </li>
              ))}
            </ul>
            {result.recommendations.length > 0 && (
              <Button asChild size="sm" variant="outline"><Link href="/recommendations">Review {result.recommendations.length} recommendation(s)</Link></Button>
            )}
          </div>
        )}
      </CardContent>
    </Card>
  );
}
