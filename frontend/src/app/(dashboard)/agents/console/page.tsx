"use client";

/**
 * Agent Console - the Merchant OS.
 *
 * Ask anything; the Orchestrator Agent routes it to one of six specialists (Business
 * Intelligence, Product Discovery, Supply Intelligence, Pricing Intelligence, Growth
 * Strategy, PayPal Transaction). Every step and tool call is shown, and Agent Activity
 * lists every run: agent, task, trigger, tools, status, result and errors.
 */

import {
  ArrowRight,
  Bot,
  Check,
  CircleAlert,
  GitBranch,
  Lock,
  Route,
  Send,
  Workflow,
  XCircle,
} from "lucide-react";
import Link from "next/link";
import * as React from "react";

import { EmptyState, ErrorState, LoadingRows } from "@/components/common/states";
import { CompareTray } from "@/components/discovery/compare-tray";
import { AiBadge, ProductImage, formatPrice } from "@/components/discovery/shared";
import { PageHeader, StatusPill } from "@/components/supply/shared";
import { Button } from "@/components/ui/button";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/overlays";
import { Badge, Card, CardContent, CardDescription, CardHeader, CardTitle, Textarea } from "@/components/ui/primitives";
import { useAgentActivity, useAgentCatalogue, useExecuteAgents } from "@/hooks/use-discovery";
import { cn, formatDuration, formatRelativeTime } from "@/lib/utils";
import { useAuthStore } from "@/stores/auth";
import type { AgentKey } from "@/types/discovery";

const PROMPTS = [
  { text: "What new products should I sell next to my best seller?", agent: "Supply Intelligence" },
  { text: "Find wireless earbuds under ₹5,000", agent: "Product Discovery" },
  { text: "Are my retail prices competitive?", agent: "Pricing Intelligence" },
  { text: "Run the growth autopilot", agent: "Growth Strategy" },
  { text: "How are my sales this month?", agent: "Business Intelligence" },
  { text: "Show my PayPal payments and anything awaiting approval", agent: "PayPal Transaction" },
];

export default function AgentConsolePage() {
  const catalogue = useAgentCatalogue();
  const [agentFilter, setAgentFilter] = React.useState<string>("all");
  const activity = useAgentActivity({ limit: 30, agent_name: agentFilter === "all" ? undefined : agentFilter });
  const execute = useExecuteAgents();
  const canRun = useAuthStore((s) => s.can("agents:run"));
  const [message, setMessage] = React.useState("");
  const [agent, setAgent] = React.useState<string>("auto");
  const result = execute.data;

  const ask = (text: string) => {
    if (text.trim().length < 2) return;
    setMessage(text);
    execute.mutate({ message: text.trim(), agent: agent === "auto" ? null : (agent as AgentKey) });
  };

  return (
    <div className="space-y-5 pb-24">
      <PageHeader eyebrow="Command" title="Agent Console"
        description="One request, the right specialist. The Orchestrator routes your question to an agent, which calls PayPilot's tools - every call permission-checked, traced and recorded. No agent can approve, buy or pay."
        actions={<Button asChild size="sm" variant="outline" className="gap-1.5"><Link href="/agents"><Workflow className="h-3.5 w-3.5" /> Growth agent traces</Link></Button>} />

      <div className="grid gap-5 xl:grid-cols-[1fr_340px]">
        <div className="min-w-0 space-y-4">
          <Card>
            <CardContent className="space-y-3 p-4">
              <form className="space-y-2" onSubmit={(e) => { e.preventDefault(); ask(message); }}>
                <Textarea rows={2} value={message} onChange={(e) => setMessage(e.target.value)} disabled={!canRun}
                  placeholder="Ask the agents - e.g. “Find premium office chairs under ₹15,000 and compare the top three”" aria-label="Ask the agents"
                  onKeyDown={(e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); ask(message); } }} />
                <div className="flex flex-wrap items-center gap-2">
                  <Select value={agent} onValueChange={setAgent}>
                    <SelectTrigger className="h-9 w-56" aria-label="Choose an agent"><SelectValue /></SelectTrigger>
                    <SelectContent>
                      <SelectItem value="auto">Auto - let the Orchestrator decide</SelectItem>
                      {catalogue.data?.filter((a) => a.key !== "orchestrator").map((a) => <SelectItem key={a.key} value={a.key}>{a.label}</SelectItem>)}
                    </SelectContent>
                  </Select>
                  <Button type="submit" className="ml-auto gap-1.5" loading={execute.isPending} disabled={!canRun || message.trim().length < 2}>
                    <Send className="h-4 w-4" /> Run agents
                  </Button>
                </div>
              </form>
              {!canRun && <p className="flex items-center gap-1 text-xs text-muted-foreground"><Lock className="h-3.5 w-3.5" /> Your role can view agent activity but not start runs.</p>}
              <div className="flex flex-wrap gap-1.5">
                {PROMPTS.map((p) => (
                  <button key={p.text} type="button" disabled={!canRun || execute.isPending} onClick={() => ask(p.text)}
                    className="rounded-full border border-border px-3 py-1 text-xs text-muted-foreground hover:border-primary/40 hover:text-foreground disabled:opacity-50">
                    {p.text} <span className="text-2xs text-primary">· {p.agent}</span>
                  </button>
                ))}
              </div>
            </CardContent>
          </Card>

          {execute.isPending && (
            <Card><CardContent className="space-y-2 p-4"><p className="flex items-center gap-2 text-sm"><Bot className="h-4 w-4 animate-pulse text-primary" /> The agents are working - routing, calling tools, checking evidence…</p><LoadingRows rows={3} /></CardContent></Card>
          )}
          {execute.error && <ErrorState error={execute.error} />}

          {result && !execute.isPending && (
            <Card className="overflow-hidden">
              <CardContent className="space-y-4 p-5">
                <div className="flex flex-wrap items-center gap-2">
                  <span className="flex items-center gap-1.5 rounded-lg bg-muted px-2 py-1 text-xs"><Route className="h-3.5 w-3.5" /> Orchestrator <ArrowRight className="h-3 w-3" /> <span className="font-semibold">{result.agent_label}</span></span>
                  <Badge variant="muted" className="normal-case tracking-normal">routed by {result.route.source}</Badge>
                  <StatusPill status={result.status} />
                  {result.used_llm && <AiBadge label="AI-written answer" />}
                  <span className="ml-auto text-2xs text-muted-foreground">{formatDuration(result.duration_ms)}</span>
                </div>
                <p className="text-2xs text-muted-foreground">Why this agent: {result.route.reason}</p>
                <p className="whitespace-pre-wrap text-sm leading-relaxed">{result.answer}</p>
                {result.requires_approval && (
                  <div className="flex flex-wrap items-center gap-2 rounded-xl border border-warning/40 bg-warning/5 p-3 text-xs">
                    <CircleAlert className="h-4 w-4 text-warning" />
                    <span>Stopped at the approval gate - {result.recommendations.filter((r) => r.status === "RECOMMENDED").length} recommendation(s) and {result.approvals.length} payment approval(s) wait for you.</span>
                    <Button asChild size="sm" variant="outline" className="ml-auto"><Link href={result.approvals.length ? "/finance/payment-management" : "/recommendations"}>Review</Link></Button>
                  </div>
                )}
                {result.products.length > 0 && (
                  <div className="grid gap-2 sm:grid-cols-2 lg:grid-cols-3">
                    {result.products.slice(0, 6).map((p) => (
                      <Link key={p.id} href={`/discovery/products/${encodeURIComponent(p.id)}`} className="flex items-center gap-2 rounded-lg border border-border p-2 hover:border-primary/40">
                        <ProductImage src={p.image_url} alt={p.title} className="h-12 w-12 shrink-0 rounded" />
                        <div className="min-w-0 text-xs">
                          <p className="line-clamp-2 font-medium leading-tight">{p.title}</p>
                          <p className="text-muted-foreground">{formatPrice(p.price ?? null, p.currency ?? "USD")} · {p.retailer}{p.score != null ? ` · score ${Math.round(p.score)}` : ""}</p>
                        </div>
                      </Link>
                    ))}
                  </div>
                )}
                {result.recommendations.length > 0 && (
                  <ul className="space-y-1">
                    {result.recommendations.map((r) => (
                      <li key={r.id}><Link href="/recommendations" className="flex items-center gap-2 text-xs hover:text-primary">
                        <StatusPill status={r.status} /> <span className="font-mono text-2xs text-muted-foreground">{r.reference}</span> {r.title}
                        {r.expected_impact && <span className="text-muted-foreground">· est. {formatPrice(r.expected_impact, "USD")}/mo</span>}
                      </Link></li>
                    ))}
                  </ul>
                )}
                <div className="grid gap-4 lg:grid-cols-2">
                  <div className="space-y-1.5">
                    <p className="flex items-center gap-1 text-2xs font-semibold uppercase tracking-wide text-muted-foreground"><GitBranch className="h-3 w-3" /> Execution trace</p>
                    <ol className="space-y-2 border-l border-border pl-3">
                      {result.steps.map((s, i) => (
                        <li key={`${s.node}-${i}`} className="text-xs">
                          <p className="font-medium">{s.action}</p>
                          <p className="text-2xs text-muted-foreground">{s.node.replace(/_/g, " ")}{s.decision ? ` · ${s.decision}` : ""}</p>
                          {s.error && <p className="text-2xs text-destructive">{s.error}</p>}
                        </li>
                      ))}
                    </ol>
                  </div>
                  <div className="space-y-1.5">
                    <p className="text-2xs font-semibold uppercase tracking-wide text-muted-foreground">Tools invoked</p>
                    <ul className="space-y-1.5">
                      {result.tool_calls.map((t, i) => (
                        <li key={`${t.tool}-${i}`} className="flex items-start gap-2 text-xs">
                          {t.ok ? <Check className="mt-0.5 h-3.5 w-3.5 shrink-0 text-success" /> : <XCircle className="mt-0.5 h-3.5 w-3.5 shrink-0 text-destructive" />}
                          <div className="min-w-0"><p className="font-mono text-2xs">{t.tool}{t.attempts > 1 ? ` (${t.attempts} attempts)` : ""}</p>
                            <p className="line-clamp-2 text-2xs text-muted-foreground">{t.ok ? t.summary : t.error}</p></div>
                        </li>
                      ))}
                    </ul>
                  </div>
                </div>
              </CardContent>
            </Card>
          )}

          <Card>
            <CardHeader className="flex-row flex-wrap items-center justify-between gap-2 pb-2">
              <div><CardTitle className="text-sm">Agent activity</CardTitle><CardDescription>Every run: agent, task, trigger, tools, status, result and errors</CardDescription></div>
              <Select value={agentFilter} onValueChange={setAgentFilter}>
                <SelectTrigger className="h-8 w-56" aria-label="Filter by agent"><SelectValue /></SelectTrigger>
                <SelectContent>
                  <SelectItem value="all">All agents</SelectItem>
                  <SelectItem value="merchant_orchestrator">Orchestrator Agent (Merchant OS)</SelectItem>
                  <SelectItem value="growth_orchestrator">Growth Orchestrator</SelectItem>
                  <SelectItem value="procurement_orchestrator">Procurement Orchestrator</SelectItem>
                  <SelectItem value="action_agent">Action Agent</SelectItem>
                  <SelectItem value="measurement_agent">Measurement Agent</SelectItem>
                </SelectContent>
              </Select>
            </CardHeader>
            <CardContent className="space-y-2">
              {activity.isLoading && <LoadingRows rows={4} />}
              {activity.error && <ErrorState error={activity.error} />}
              {activity.data?.items.length === 0 && <EmptyState icon={Bot} title="No agent runs yet" description="Ask a question above - each run appears here." />}
              {activity.data?.items.map((item) => (
                <details key={item.run_id} className="group rounded-lg border border-border p-3 open:bg-muted/20">
                  <summary className="flex cursor-pointer list-none flex-wrap items-center gap-2 text-sm">
                    <span className="font-medium">{item.specialists[0] ?? item.agent_label}</span>
                    <span className="line-clamp-1 min-w-0 flex-1 text-xs text-muted-foreground">{item.task}</span>
                    <StatusPill status={item.status} />
                    <span className="text-2xs text-muted-foreground">{formatRelativeTime(item.created_at)}</span>
                  </summary>
                  <div className="mt-2 space-y-2 text-xs">
                    <p className="text-muted-foreground">Trigger: <span className="text-foreground">{item.trigger}</span> · {item.agent_label}{item.specialists.length ? ` → ${item.specialists.join(", ")}` : ""} · {formatDuration(item.duration_ms)}{item.used_fallback ? " · deterministic mode" : ""}</p>
                    {item.result && <p>{item.result}</p>}
                    {item.error && <p className="text-destructive">Error: {item.error}</p>}
                    <div className="flex flex-wrap gap-1.5">
                      {item.tools.map((t, i) => (
                        <span key={`${t.tool}-${i}`} title={t.error ?? t.summary}
                          className={cn("rounded-md border px-1.5 py-0.5 font-mono text-2xs", t.status === "COMPLETED" ? "border-success/30 text-success" : "border-destructive/30 text-destructive")}>
                          {t.tool}{t.duration_ms != null ? ` ${t.duration_ms}ms` : ""}
                        </span>
                      ))}
                      {item.tools.length === 0 && <span className="text-2xs text-muted-foreground">No tool calls recorded</span>}
                    </div>
                  </div>
                </details>
              ))}
            </CardContent>
          </Card>
        </div>

        <aside className="space-y-3">
          <p className="text-2xs font-semibold uppercase tracking-wide text-muted-foreground">The agents</p>
          {catalogue.isLoading && <LoadingRows rows={4} />}
          {catalogue.data?.map((a) => {
            const stats = activity.data?.agents.find((s) => s.agent_name === a.name);
            return (
              <Card key={a.key}>
                <CardContent className="space-y-1.5 p-3">
                  <div className="flex items-center gap-2">
                    <span className="flex h-7 w-7 items-center justify-center rounded-lg bg-primary/10 text-primary"><Bot className="h-3.5 w-3.5" /></span>
                    <p className="text-sm font-semibold">{a.label}</p>
                    {stats && <span className="ml-auto text-2xs text-muted-foreground">{stats.runs} run(s)</span>}
                  </div>
                  <p className="text-2xs text-muted-foreground">{a.purpose}</p>
                  {a.tools.length > 0 && (
                    <div className="flex flex-wrap gap-1">
                      {a.tools.map((t) => (
                        <span key={t.name} className={cn("rounded px-1 font-mono text-[10px]", t.requires_approval ? "bg-warning/14 text-warning" : "bg-muted text-muted-foreground")}
                          title={t.requires_approval ? "Only creates an approval request" : undefined}>{t.name}</span>
                      ))}
                    </div>
                  )}
                  <p className="flex items-center gap-1 text-[10px] text-muted-foreground"><Lock className="h-3 w-3" /> Cannot approve, pay or capture</p>
                </CardContent>
              </Card>
            );
          })}
        </aside>
      </div>
      <CompareTray />
    </div>
  );
}
