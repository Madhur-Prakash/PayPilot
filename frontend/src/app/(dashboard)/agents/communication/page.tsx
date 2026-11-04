"use client";

/** Agent communication: every protocol message across all negotiations, verified and typed. */

import { MessagesSquare, ShieldCheck } from "lucide-react";
import * as React from "react";

import { EmptyState, ErrorState, LoadingRows } from "@/components/common/states";
import { MessageTimeline } from "@/components/supply/message-timeline";
import { PageHeader } from "@/components/supply/shared";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/primitives";
import { useAgentMessages } from "@/hooks/use-supply";
import { cn } from "@/lib/utils";

export default function AgentCommunicationPage() {
  const [type, setType] = React.useState<string | undefined>(undefined);
  const { data, isLoading, error, refetch } = useAgentMessages({ message_type: type, limit: 200 });
  const counts = (data?.meta.type_counts ?? {}) as Record<string, number>;
  const messages = [...(data?.data ?? [])].reverse();
  return (
    <div className="space-y-5">
      <PageHeader eyebrow="Agents" title="Agent communication"
        description="The agent-to-agent protocol: typed messages, signed per agent with HMAC-SHA256, verified for tenant, identity, freshness, schema and replay before they are recorded." />
      <div className="grid gap-4 lg:grid-cols-[260px_1fr]">
        <Card className="h-fit">
          <CardHeader className="pb-2">
            <CardTitle className="text-sm">Message types</CardTitle>
            <CardDescription>Filter the log.</CardDescription>
          </CardHeader>
          <CardContent className="space-y-1">
            <button type="button" onClick={() => setType(undefined)}
              className={cn("flex w-full justify-between rounded-lg px-2 py-1 text-left text-xs", !type ? "bg-primary/10 text-primary" : "hover:bg-muted")}>
              <span>All</span><span className="tabular-nums">{Object.values(counts).reduce((a, b) => a + b, 0)}</span>
            </button>
            {Object.entries(counts).sort((a, b) => b[1] - a[1]).map(([k, v]) => (
              <button key={k} type="button" onClick={() => setType(k)}
                className={cn("flex w-full justify-between rounded-lg px-2 py-1 text-left font-mono text-2xs", type === k ? "bg-primary/10 text-primary" : "hover:bg-muted")}>
                <span>{k}</span><span className="tabular-nums">{v}</span>
              </button>
            ))}
            <p className="flex items-start gap-1.5 pt-2 text-2xs text-muted-foreground">
              <ShieldCheck className="mt-px h-3 w-3 shrink-0 text-success" />
              External agents deliver signed envelopes to POST /api/v1/agent-messages/inbound - the same verification boundary.
            </p>
          </CardContent>
        </Card>
        <Card>
          <CardContent className="max-h-[75vh] overflow-y-auto p-4">
            {error && <ErrorState error={error} onRetry={() => void refetch()} />}
            {isLoading && <LoadingRows rows={6} />}
            {!isLoading && messages.length === 0 && (
              <EmptyState icon={MessagesSquare} title="No agent messages yet" description="They appear as soon as a procurement request goes out to supplier agents." />
            )}
            <MessageTimeline messages={messages} />
          </CardContent>
        </Card>
      </div>
    </div>
  );
}
