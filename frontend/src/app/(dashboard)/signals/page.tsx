"use client";

/**
 * External signals.
 *
 * Deliberately not a news feed. Every signal here has been scored against this
 * merchant's actual revenue exposure, so the page leads with that exposure
 * rather than with the headline — a coffee price story matters to a café with
 * 38% of revenue in coffee and not at all to one with 2%.
 *
 * Anything a merchant judges irrelevant can be dismissed, which is the only way
 * a feed like this stays worth reading.
 */

import {
  ArrowDownRight,
  ArrowUpRight,
  ExternalLink,
  Minus,
  Radar,
  Sparkle,
  X,
} from "lucide-react";
import * as React from "react";

import { EmptyState, ErrorState, LoadingRows } from "@/components/common/states";
import { Button } from "@/components/ui/button";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/overlays";
import { Badge, Card, CardContent, CardHeader, CardTitle } from "@/components/ui/primitives";
import { useDismissSignal, useSignals } from "@/hooks/use-api";
import { cn, formatDate, formatNumber, formatPercent } from "@/lib/utils";
import type { Signal } from "@/types/api";

const RELEVANCE = {
  HIGH: {
    chip: "bg-destructive/10 text-destructive",
    border: "border-destructive/40",
    label: "High exposure",
  },
  MEDIUM: {
    chip: "bg-warning/10 text-warning",
    border: "border-warning/40",
    label: "Some exposure",
  },
  LOW: {
    chip: "bg-muted text-muted-foreground",
    border: "border-border",
    label: "Low exposure",
  },
} as const;

const WINDOWS = [
  { value: "14", label: "Last 14 days" },
  { value: "30", label: "Last 30 days" },
  { value: "90", label: "Last 90 days" },
];

export default function SignalsPage() {
  const [days, setDays] = React.useState("30");
  const [onlyRelevant, setOnlyRelevant] = React.useState(false);

  const { data, isLoading, isFetching, error, refetch } = useSignals(Number(days));
  const dismiss = useDismissSignal();

  const signals = data?.signals ?? [];
  const visible = onlyRelevant ? signals.filter((s) => s.relevance === "HIGH") : signals;
  const exposed = signals.filter((s) => (s.exposure_pct ?? 0) > 0);

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h2 className="text-xl font-semibold tracking-tight">External signals</h2>
          <p className="text-sm text-muted-foreground">
            Market events scored against what this merchant actually sells
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <Select value={days} onValueChange={setDays}>
            <SelectTrigger className="w-[160px]" aria-label="Time window">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {WINDOWS.map((option) => (
                <SelectItem key={option.value} value={option.value}>
                  {option.label}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
          <Button
            variant={onlyRelevant ? "default" : "outline"}
            size="sm"
            onClick={() => setOnlyRelevant((current) => !current)}
          >
            High exposure only
          </Button>
        </div>
      </div>

      <div className="grid gap-4 sm:grid-cols-3">
        <Tile
          value={formatNumber(data?.high_relevance_count ?? 0)}
          label="Need attention"
          hint="scored high against your revenue"
          tone={(data?.high_relevance_count ?? 0) > 0 ? "warning" : "default"}
        />
        <Tile
          value={formatNumber(exposed.length)}
          label="Touch your catalogue"
          hint="mapped to a category you sell"
        />
        <Tile
          value={formatNumber(signals.length)}
          label="Tracked"
          hint={`in the last ${days} days`}
        />
      </div>

      <Card>
        <CardHeader className="pb-3">
          <CardTitle className="text-base">
            {onlyRelevant ? "High exposure" : "All signals"}
          </CardTitle>
          <p className="text-sm text-muted-foreground">
            Ranked by how much of your revenue sits in the affected category, not by how big
            the news is.
          </p>
        </CardHeader>
        <CardContent className="space-y-2">
          {isLoading && <LoadingRows rows={4} />}
          {error && <ErrorState error={error} onRetry={() => void refetch()} />}

          {!isLoading && !error && visible.length === 0 && (
            <EmptyState
              icon={Radar}
              title={onlyRelevant ? "Nothing high-exposure right now" : "No signals in this window"}
              description={
                onlyRelevant
                  ? "Clear the filter to see everything being tracked."
                  : "Signals appear when a market event maps onto something you sell."
              }
            />
          )}

          <div className={cn("space-y-2", isFetching && "opacity-60")}>
            {visible.map((signal) => (
              <SignalCard
                key={signal.id}
                signal={signal}
                onDismiss={() => dismiss.mutate(signal.id)}
                dismissing={dismiss.isPending && dismiss.variables === signal.id}
              />
            ))}
          </div>
        </CardContent>
      </Card>

      {data?.provenance && (
        <p className="text-2xs text-muted-foreground">
          {signals.some((s) => s.is_simulated)
            ? "Some signals are baseline examples and are labelled as such."
            : "Signals are drawn from the configured external search provider."}
        </p>
      )}
    </div>
  );
}

function SignalCard({
  signal,
  onDismiss,
  dismissing,
}: {
  signal: Signal;
  onDismiss: () => void;
  dismissing: boolean;
}) {
  const tone = RELEVANCE[signal.relevance] ?? RELEVANCE.LOW;
  const Direction =
    signal.direction === "UP" ? ArrowUpRight : signal.direction === "DOWN" ? ArrowDownRight : Minus;

  return (
    <div className={cn("rounded-xl border bg-card p-3", tone.border)}>
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-2">
            <span className="text-sm font-semibold">{signal.title}</span>
            <span className={cn("rounded-md px-1.5 py-0.5 text-2xs font-semibold", tone.chip)}>
              {tone.label}
            </span>
            <Badge variant="outline" className="text-2xs">
              {signal.category}
            </Badge>
            {signal.is_simulated && (
              <Badge variant="outline" className="gap-1 text-2xs text-muted-foreground">
                <Sparkle className="h-3 w-3" />
                baseline
              </Badge>
            )}
          </div>

          <p className="mt-1 text-2xs leading-relaxed text-muted-foreground">{signal.summary}</p>

          {/* Exposure is the whole point - it is what makes this not a news feed. */}
          {(signal.exposure_pct != null || signal.exposure_note) && (
            <div className="mt-2 flex flex-wrap items-center gap-2 rounded-lg bg-muted/40 px-2.5 py-1.5">
              <Direction
                className={cn(
                  "h-3.5 w-3.5 shrink-0",
                  signal.direction === "UP"
                    ? "text-destructive"
                    : signal.direction === "DOWN"
                      ? "text-success"
                      : "text-muted-foreground",
                )}
              />
              <span className="text-2xs tabular-nums">
                {signal.exposure_pct != null && (
                  <strong>{formatPercent(signal.exposure_pct / 100)} of revenue</strong>
                )}
                {signal.exposure_note && (
                  <span className="text-muted-foreground">
                    {signal.exposure_pct != null ? " · " : ""}
                    {signal.exposure_note}
                  </span>
                )}
              </span>
            </div>
          )}

          {signal.potential_impact && (
            <p className="mt-1.5 text-2xs">
              <span className="text-muted-foreground">If it holds: </span>
              {signal.potential_impact}
            </p>
          )}

          {signal.recommended_action && (
            <p className="mt-1 text-2xs">
              <span className="text-muted-foreground">Suggested: </span>
              <span className="font-medium">{signal.recommended_action}</span>
            </p>
          )}

          <div className="mt-2 flex flex-wrap items-center gap-x-3 gap-y-1 text-2xs text-muted-foreground/80">
            <span>{formatDate(signal.observed_on)}</span>
            {signal.source_url ? (
              <a
                href={signal.source_url}
                target="_blank"
                rel="noreferrer"
                className="inline-flex items-center gap-1 text-primary hover:underline"
              >
                <ExternalLink className="h-3 w-3" />
                {signal.source_name}
              </a>
            ) : (
              <span>{signal.source_name}</span>
            )}
          </div>
        </div>

        <Button
          variant="ghost"
          size="sm"
          className="gap-1.5 text-muted-foreground"
          loading={dismissing}
          onClick={onDismiss}
          title="Stop raising this signal for this merchant"
        >
          <X className="h-3.5 w-3.5" />
          Dismiss
        </Button>
      </div>
    </div>
  );
}

function Tile({
  value,
  label,
  hint,
  tone = "default",
}: {
  value: string;
  label: string;
  hint: string;
  tone?: "default" | "warning";
}) {
  return (
    <Card>
      <CardContent className="p-4">
        <p
          className={cn(
            "text-lg font-semibold leading-none tabular-nums",
            tone === "warning" && "text-warning",
          )}
        >
          {value}
        </p>
        <p className="mt-1 text-2xs text-muted-foreground">
          {label} · {hint}
        </p>
      </CardContent>
    </Card>
  );
}
