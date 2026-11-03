"use client";

/**
 * The Opportunity Radar, and the investigation that turns one into a decision.
 *
 * This page is the product's spine: pick an opportunity, run the Growth Scientist,
 * read the evidence it gathered, then approve - which hands off to the Action and
 * Experiment agents. Every step is visible while it happens.
 */

import { AnimatePresence, motion } from "framer-motion";
import {
  Bot,
  Lightbulb,
  Loader2,
  Microscope,
  RefreshCw,
  Search,
} from "lucide-react";
import { useSearchParams } from "next/navigation";
import * as React from "react";

import { AgentTrace } from "@/components/agents/agent-trace";
import { EmptyState, ErrorState, LoadingRows } from "@/components/common/states";
import { EvidenceList } from "@/components/growth/evidence-list";
import { RecommendationPanel } from "@/components/growth/recommendation-panel";
import { GrowthArbitrageCard } from "@/components/opportunities/growth-arbitrage-card";
import { OpportunityExplorerGraph } from "@/components/opportunities/opportunity-explorer-graph";
import { OpportunityCard, STATUS_META } from "@/components/opportunities/opportunity-card";
import { Button } from "@/components/ui/button";
import { FadeIn, Stagger, StaggerItem } from "@/components/ui/motion";
import {
  Badge,
  Card,
  CardContent,
  CardHeader,
  CardTitle,
  Separator,
  Tabs,
  TabsContent,
  TabsList,
  TabsTrigger,
} from "@/components/ui/primitives";
import { useDetectOpportunities, useInvestigate, useOpportunities } from "@/hooks/use-api";
import { usePageVoiceContext } from "@/hooks/use-page-voice-context";
import { formatCompactCurrency } from "@/lib/utils";
import { useAuthStore } from "@/stores/auth";
import type { AgentRunResponse, Opportunity } from "@/types/api";

export default function OpportunitiesPage() {
  const params = useSearchParams();
  const focusId = params.get("focus");

  const { data, isLoading, error, refetch } = useOpportunities();
  const detect = useDetectOpportunities();
  const investigate = useInvestigate();
  const canRunAgents = useAuthStore((s) => s.can("growth:recommend"));

  const [selected, setSelected] = React.useState<Opportunity | null>(null);
  const [run, setRun] = React.useState<AgentRunResponse | null>(null);

  // Deep link from the dashboard: /opportunities?focus=<id>
  React.useEffect(() => {
    if (!data?.opportunities.length) return;
    const target = focusId
      ? data.opportunities.find((item) => item.id === focusId)
      : data.opportunities[0];
    if (target) setSelected((current) => current ?? target);
  }, [data, focusId]);

  usePageVoiceContext(
    data
      ? `${data.open_count} open opportunities worth ${formatCompactCurrency(data.total_estimated_value_monthly)} a month combined. Top one: "${data.opportunities[0]?.title ?? "none"}", estimated ${data.opportunities[0] ? formatCompactCurrency(data.opportunities[0].estimated_value_monthly) : "-"} a month.`
      : null,
  );

  async function handleInvestigate(opportunity: Opportunity) {
    setSelected(opportunity);
    setRun(null);
    const result = await investigate.mutateAsync({
      opportunity_id: opportunity.id,
      question: `Investigate: ${opportunity.title}. What is the evidence, and what should I do?`,
    });
    setRun(result);
  }

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h2 className="text-xl font-semibold tracking-tight">Opportunity Radar</h2>
          <p className="text-sm text-muted-foreground">
            {data
              ? `${data.open_count} open opportunities worth ${formatCompactCurrency(data.total_estimated_value_monthly)}/month`
              : "Quantified, evidence-backed growth opportunities"}
          </p>
        </div>
        <Button
          variant="outline"
          onClick={() => detect.mutate(30)}
          loading={detect.isPending}
          className="gap-2"
        >
          <RefreshCw className="h-4 w-4" />
          Re-run detection
        </Button>
      </div>

      <GrowthArbitrageCard />

      {isLoading && <LoadingRows rows={3} />}
      {error && <ErrorState error={error} onRetry={() => void refetch()} />}

      {data && data.opportunities.length === 0 && (
        <EmptyState
          icon={Lightbulb}
          title="No opportunities detected"
          description="Nothing in this period is moving far enough from normal to be worth acting on. Run detection again after the next trading week."
          action={
            <Button onClick={() => detect.mutate(30)} loading={detect.isPending}>
              Run detection
            </Button>
          }
        />
      )}

      {data && data.opportunities.length > 0 && (
        <>
          <OpportunityExplorerGraph
            opportunities={data.opportunities}
            selectedId={selected?.id}
            onSelect={(opp) => {
              setSelected(opp);
              setRun(null);
            }}
          />

          <div className="pt-2">
            <h3 className="text-sm font-bold uppercase tracking-wider text-muted-foreground mb-3">
              Opportunity Detail Cards
            </h3>
            <Stagger className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
            {data.opportunities.map((opportunity, index) => (
              <StaggerItem key={opportunity.id}>
                <button
                  type="button"
                  onClick={() => {
                    setSelected(opportunity);
                    setRun(null);
                  }}
                  className="w-full text-left focus-ring rounded-xl"
                >
                  <OpportunityCard opportunity={opportunity} rank={index + 1} />
                </button>
              </StaggerItem>
            ))}
            </Stagger>
          </div>

          {selected && (
            <FadeIn key={selected.id}>
              <Card>
                <CardHeader className="flex-row flex-wrap items-start justify-between gap-3 space-y-0">
                  <div className="min-w-0">
                    <div className="mb-1 flex flex-wrap items-center gap-2">
                      <Badge variant={STATUS_META[selected.status]?.variant ?? "muted"}>
                        {STATUS_META[selected.status]?.label ?? selected.status}
                      </Badge>
                      <Badge variant="outline">{selected.kind.toLowerCase()}</Badge>
                      {selected.tags.slice(0, 2).map((tag) => (
                        <Badge key={tag} variant="muted">
                          {tag}
                        </Badge>
                      ))}
                    </div>
                    <CardTitle className="text-lg">{selected.title}</CardTitle>
                    <p className="mt-1 max-w-3xl text-sm leading-relaxed text-muted-foreground">
                      {selected.summary}
                    </p>
                  </div>
                  <div className="text-right">
                    <p className="text-2xl font-semibold tracking-tight tnum">
                      {formatCompactCurrency(selected.estimated_value_monthly)}
                    </p>
                    <p className="text-2xs text-muted-foreground">
                      per month · {Math.round(selected.confidence * 100)}% confidence
                    </p>
                  </div>
                </CardHeader>

                <CardContent>
                  <Tabs defaultValue="evidence">
                    <TabsList>
                      <TabsTrigger value="evidence">
                        Evidence ({selected.evidence.length})
                      </TabsTrigger>
                      <TabsTrigger value="hypothesis">Hypothesis</TabsTrigger>
                      <TabsTrigger value="investigate">
                        <Bot className="h-3.5 w-3.5" />
                        Growth Scientist
                      </TabsTrigger>
                    </TabsList>

                    <TabsContent value="evidence">
                      <EvidenceList evidence={selected.evidence} />
                    </TabsContent>

                    <TabsContent value="hypothesis" className="space-y-4">
                      <Section title="Hypothesis">
                        {selected.hypothesis || "No hypothesis has been recorded yet."}
                      </Section>
                      <Separator />
                      <Section title="Recommended intervention">
                        {selected.recommended_action || "Run the Growth Scientist to generate one."}
                      </Section>
                      {selected.reasoning && (
                        <>
                          <Separator />
                          <Section title="Why this rather than the obvious alternative">
                            {selected.reasoning}
                          </Section>
                        </>
                      )}
                    </TabsContent>

                    <TabsContent value="investigate" className="space-y-4">
                      {!canRunAgents && (
                        <p className="rounded-lg border border-border bg-muted/50 p-3 text-sm text-muted-foreground">
                          Running an investigation requires the Analyst, Admin or Owner role.
                        </p>
                      )}

                      {canRunAgents && !run && (
                        <div className="flex flex-col items-center gap-3 rounded-xl border border-dashed border-border px-6 py-10 text-center">
                          <div className="flex h-11 w-11 items-center justify-center rounded-full bg-primary/10 text-primary">
                            <Microscope className="h-5 w-5" />
                          </div>
                          <div className="space-y-1">
                            <p className="text-sm font-semibold">Run the full investigation</p>
                            <p className="mx-auto max-w-md text-sm text-muted-foreground">
                              The Growth Scientist will compute the metrics, fan out to review and
                              market intelligence, synthesise the evidence and produce a
                              recommendation with an approval gate.
                            </p>
                          </div>
                          <Button
                            onClick={() => handleInvestigate(selected)}
                            loading={investigate.isPending}
                            className="gap-2"
                          >
                            {investigate.isPending ? (
                              <>
                                <Loader2 className="h-4 w-4 animate-spin" />
                                Investigating…
                              </>
                            ) : (
                              <>
                                <Microscope className="h-4 w-4" />
                                Investigate
                              </>
                            )}
                          </Button>
                        </div>
                      )}

                      <AnimatePresence>
                        {run && (
                          <motion.div
                            initial={{ opacity: 0, y: 10 }}
                            animate={{ opacity: 1, y: 0 }}
                            className="space-y-4"
                          >
                            {run.recommendation && (
                              <RecommendationPanel
                                recommendation={run.recommendation}
                                opportunity={selected}
                                usedFallback={run.run.used_fallback}
                                onApproved={() => void refetch()}
                              />
                            )}
                            <AgentTrace run={run.run} />
                            <div className="flex justify-center">
                              <Button
                                variant="ghost"
                                size="sm"
                                onClick={() => handleInvestigate(selected)}
                                loading={investigate.isPending}
                              >
                                <RefreshCw className="h-3.5 w-3.5" />
                                Run again
                              </Button>
                            </div>
                          </motion.div>
                        )}
                      </AnimatePresence>
                    </TabsContent>
                  </Tabs>
                </CardContent>
              </Card>
            </FadeIn>
          )}
        </>
      )}
    </div>
  );
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div className="space-y-1.5">
      <p className="text-2xs font-semibold uppercase tracking-widest text-muted-foreground">
        {title}
      </p>
      <p className="max-w-3xl text-sm leading-relaxed">{children}</p>
    </div>
  );
}
