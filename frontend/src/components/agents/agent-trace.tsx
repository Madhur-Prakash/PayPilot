"use client";

/**
 * The human-readable agent trace.
 *
 * Spec section 41: show the action, the tools, the evidence, the result and the
 * decision. Never raw chain-of-thought - the backend does not record it, and this
 * component says so explicitly so nobody assumes it is being hidden.
 */

import { motion } from "framer-motion";
import {
  CheckCircle2,
  ChevronDown,
  CircleDashed,
  ExternalLink,
  EyeOff,
  Wrench,
  XCircle,
} from "lucide-react";
import * as React from "react";

import { EvidenceList } from "@/components/growth/evidence-list";
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
import { cn, formatDuration } from "@/lib/utils";
import type { AgentRunDetail } from "@/types/api";

export function AgentTrace({ run, defaultOpen = true }: { run: AgentRunDetail; defaultOpen?: boolean }) {
  const [open, setOpen] = React.useState(defaultOpen);

  return (
    <Card>
      <CardHeader className="flex-row items-start justify-between gap-3 space-y-0">
        <div className="min-w-0">
          <CardTitle className="text-base">Agent trace</CardTitle>
          <p className="mt-0.5 text-sm text-muted-foreground">
            {run.steps.length} steps · {run.tools_used.length} tools ·{" "}
            {formatDuration(run.duration_ms)}
          </p>
        </div>
        <div className="flex flex-wrap items-center justify-end gap-1.5">
          <StatusBadge status={run.status} />
          {run.used_fallback ? (
            <Tooltip>
              <TooltipTrigger asChild>
                <span>
                  <Badge variant="muted">Deterministic</Badge>
                </span>
              </TooltipTrigger>
              <TooltipContent>
                No LLM key is configured, so the deterministic path produced this result. The
                figures and the recommendation are identical either way — only the wording is
                simpler.
              </TooltipContent>
            </Tooltip>
          ) : (
            run.model && <Badge variant="outline">{run.model}</Badge>
          )}
          {run.trace_url && (
            <a
              href={run.trace_url}
              target="_blank"
              rel="noreferrer"
              className="inline-flex items-center gap-1 rounded-md border border-border px-2 py-0.5 text-2xs text-muted-foreground transition-colors hover:bg-muted focus-ring"
            >
              Langfuse
              <ExternalLink className="h-3 w-3" />
            </a>
          )}
        </div>
      </CardHeader>

      <CardContent className="space-y-4">
        {/* Tools used, in call order */}
        {run.tools_used.length > 0 && (
          <div className="space-y-1.5">
            <p className="text-2xs font-semibold uppercase tracking-widest text-muted-foreground">
              Tools called
            </p>
            <div className="flex flex-wrap gap-1.5">
              {run.tools_used.map((tool) => (
                <Badge key={tool} variant="secondary" className="gap-1 font-mono normal-case">
                  <Wrench className="h-3 w-3" />
                  {tool}
                </Badge>
              ))}
            </div>
          </div>
        )}

        <Separator />

        {/* Steps */}
        <ol className="relative space-y-0">
          {run.steps.map((step, index) => {
            const last = index === run.steps.length - 1;
            return (
              <motion.li
                key={step.id}
                initial={{ opacity: 0, x: -8 }}
                animate={{ opacity: 1, x: 0 }}
                transition={{ delay: index * 0.06, duration: 0.3 }}
                className="relative flex gap-3 pb-4 last:pb-0"
              >
                {/* Rail */}
                <div className="flex flex-col items-center">
                  <div
                    className={cn(
                      "flex h-6 w-6 shrink-0 items-center justify-center rounded-full border-2 bg-background",
                      step.status === "COMPLETED"
                        ? "border-primary text-primary"
                        : step.status === "FAILED"
                          ? "border-destructive text-destructive"
                          : "border-border text-muted-foreground",
                    )}
                  >
                    <span className="text-2xs font-semibold">{step.sequence}</span>
                  </div>
                  {!last && <div className="mt-1 w-px flex-1 bg-border" />}
                </div>

                <div className="min-w-0 flex-1 pt-0.5">
                  <div className="flex flex-wrap items-center gap-2">
                    <Badge variant="outline">{step.agent_label}</Badge>
                    {step.duration_ms != null && (
                      <span className="text-2xs text-muted-foreground tnum">
                        {formatDuration(step.duration_ms)}
                      </span>
                    )}
                  </div>
                  <p className="mt-1 text-sm font-medium leading-snug">{step.action}</p>
                  {step.result && (
                    <p className="mt-0.5 text-sm leading-relaxed text-muted-foreground">
                      {step.result}
                    </p>
                  )}
                  {step.decision && (
                    <p className="mt-1.5 inline-flex rounded-md bg-primary/8 px-2 py-1 text-2xs font-medium text-primary">
                      Decision: {step.decision}
                    </p>
                  )}
                  {step.evidence.length > 0 && (
                    <details className="group mt-2">
                      <summary className="flex cursor-pointer list-none items-center gap-1 text-2xs font-medium text-muted-foreground hover:text-foreground">
                        <ChevronDown className="h-3 w-3 transition-transform group-open:rotate-180" />
                        {step.evidence.length} evidence rows
                      </summary>
                      <div className="mt-2">
                        <EvidenceList evidence={step.evidence} dense />
                      </div>
                    </details>
                  )}
                  {step.error && (
                    <p className="mt-1 text-xs text-destructive">{step.error}</p>
                  )}
                </div>
              </motion.li>
            );
          })}
        </ol>

        {/* Tool call detail */}
        {run.tool_calls.length > 0 && (
          <details className="group rounded-lg border border-border">
            <summary
              className="flex cursor-pointer list-none items-center justify-between p-3 text-sm font-medium"
              onClick={() => setOpen((o) => !o)}
            >
              <span>Tool call detail ({run.tool_calls.length})</span>
              <ChevronDown className="h-4 w-4 text-muted-foreground transition-transform group-open:rotate-180" />
            </summary>
            <div className="space-y-1.5 border-t border-border p-3">
              {run.tool_calls.map((call) => (
                <div
                  key={call.id}
                  className="flex items-start gap-2 rounded-md bg-muted/40 px-2.5 py-2"
                >
                  {call.status === "COMPLETED" ? (
                    <CheckCircle2 className="mt-0.5 h-3.5 w-3.5 shrink-0 text-success" />
                  ) : call.status === "DENIED" ? (
                    <XCircle className="mt-0.5 h-3.5 w-3.5 shrink-0 text-destructive" />
                  ) : (
                    <CircleDashed className="mt-0.5 h-3.5 w-3.5 shrink-0 text-muted-foreground" />
                  )}
                  <div className="min-w-0 flex-1">
                    <p className="font-mono text-2xs font-medium">{call.tool_name}</p>
                    <p className="text-2xs leading-relaxed text-muted-foreground">
                      {call.result_summary || call.error || "—"}
                    </p>
                  </div>
                  {call.duration_ms != null && (
                    <span className="shrink-0 text-2xs text-muted-foreground tnum">
                      {formatDuration(call.duration_ms)}
                    </span>
                  )}
                </div>
              ))}
            </div>
          </details>
        )}

        <div className="flex items-start gap-2 rounded-lg border border-dashed border-border bg-muted/30 p-3">
          <EyeOff className="mt-0.5 h-3.5 w-3.5 shrink-0 text-muted-foreground" />
          <p className="text-2xs leading-relaxed text-muted-foreground">{run.trace_disclaimer}</p>
        </div>
      </CardContent>
    </Card>
  );
}

function StatusBadge({ status }: { status: string }) {
  const map: Record<string, { label: string; variant: "success" | "warning" | "destructive" | "info" | "muted" }> = {
    COMPLETED: { label: "Completed", variant: "success" },
    AWAITING_APPROVAL: { label: "Awaiting approval", variant: "warning" },
    RUNNING: { label: "Running", variant: "info" },
    FAILED: { label: "Failed", variant: "destructive" },
    PENDING: { label: "Pending", variant: "muted" },
    CANCELLED: { label: "Cancelled", variant: "muted" },
  };
  const meta = map[status] ?? { label: status, variant: "muted" as const };
  return <Badge variant={meta.variant}>{meta.label}</Badge>;
}
