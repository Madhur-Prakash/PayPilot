"use client";

import { Info, MapPin, Minus, Star, TrendingDown, TrendingUp } from "lucide-react";
import * as React from "react";

import { PerceptionRadar } from "@/components/charts/charts";
import { ErrorState, LoadingRows } from "@/components/common/states";
import { FadeIn, Stagger, StaggerItem } from "@/components/ui/motion";
import {
  Badge,
  Card,
  CardContent,
  CardHeader,
  CardTitle,
  Progress,
  Separator,
} from "@/components/ui/primitives";
import { useCompetitors } from "@/hooks/use-api";
import { cn } from "@/lib/utils";

export default function CompetitorsPage() {
  const { data, isLoading, error, refetch } = useCompetitors(90);

  return (
    <div className="space-y-6">
      <div>
        <h2 className="text-xl font-semibold tracking-tight">Competitor Intelligence</h2>
        <p className="text-sm text-muted-foreground">
          How customers perceive you against nearby alternatives
        </p>
      </div>

      {/* Provenance is stated first, not buried in a footnote. */}
      <Card className="border-warning/30 bg-warning/5">
        <CardContent className="flex items-start gap-3 p-4">
          <Info className="mt-0.5 h-4 w-4 shrink-0 text-warning" />
          <div className="space-y-0.5">
            <p className="text-sm font-medium">Baseline competitor data</p>
            <p className="text-sm leading-relaxed text-muted-foreground">
              Competitor scores are representative benchmark data. No competitor platform is
              scraped or integrated yet. Your own scores are computed from your real review
              corpus, so the comparison is between a measured value and a benchmark.
            </p>
          </div>
        </CardContent>
      </Card>

      {isLoading && <LoadingRows rows={4} />}
      {error && <ErrorState error={error} onRetry={() => void refetch()} />}

      {data && (
        <>
          {data.biggest_gap && (
            <FadeIn>
              <Card className="border-destructive/30">
                <CardContent className="flex flex-wrap items-center justify-between gap-4 p-5">
                  <div className="flex items-start gap-3">
                    <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-destructive/10 text-destructive">
                      <TrendingDown className="h-5 w-5" />
                    </div>
                    <div>
                      <p className="text-2xs font-semibold uppercase tracking-widest text-destructive">
                        Largest perception gap
                      </p>
                      <p className="text-lg font-semibold leading-tight">
                        {data.biggest_gap.label}
                      </p>
                      <p className="mt-0.5 max-w-2xl text-sm leading-relaxed text-muted-foreground">
                        {data.summary}
                      </p>
                    </div>
                  </div>
                  <div className="flex gap-6 text-center">
                    <div>
                      <p className="text-2xs uppercase tracking-wide text-muted-foreground">You</p>
                      <p className="text-2xl font-semibold tnum">
                        {data.biggest_gap.merchant_score.toFixed(0)}
                      </p>
                    </div>
                    <div>
                      <p className="text-2xs uppercase tracking-wide text-muted-foreground">
                        Rivals
                      </p>
                      <p className="text-2xl font-semibold tnum text-muted-foreground">
                        {data.biggest_gap.competitor_avg_score.toFixed(0)}
                      </p>
                    </div>
                  </div>
                </CardContent>
              </Card>
            </FadeIn>
          )}

          <div className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_minmax(0,1fr)]">
            <Card>
              <CardHeader>
                <CardTitle>Perception profile</CardTitle>
                <p className="text-sm text-muted-foreground">
                  0–100, derived from review ratings per topic
                </p>
              </CardHeader>
              <CardContent>
                <PerceptionRadar
                  data={data.comparisons.map((row) => ({
                    label: row.label,
                    merchant_score: row.merchant_score,
                    competitor_avg_score: row.competitor_avg_score,
                  }))}
                  merchantName={data.merchant_name}
                />
              </CardContent>
            </Card>

            <Card>
              <CardHeader>
                <CardTitle>Dimension by dimension</CardTitle>
                <p className="text-sm text-muted-foreground">Sorted by where you trail most</p>
              </CardHeader>
              <CardContent className="space-y-3">
                {data.comparisons.map((row) => (
                  <div key={row.dimension} className="space-y-1.5">
                    <div className="flex items-center justify-between text-sm">
                      <span className="font-medium">{row.label}</span>
                      <span className="flex items-center gap-2">
                        <span className="tnum">{row.merchant_score.toFixed(0)}</span>
                        <span className="text-muted-foreground">
                          vs {row.competitor_avg_score.toFixed(0)}
                        </span>
                        <GapChip gap={row.gap} />
                      </span>
                    </div>
                    <div className="relative">
                      <Progress
                        value={row.merchant_score}
                        className="h-2"
                        indicatorClassName={
                          row.is_merchant_ahead ? "bg-success" : "bg-destructive"
                        }
                      />
                      {/* Benchmark marker on the same axis, so the gap is readable at a glance. */}
                      <span
                        className="absolute top-0 h-2 w-0.5 bg-foreground/50"
                        style={{ left: `${row.competitor_avg_score}%` }}
                        aria-hidden
                      />
                    </div>
                  </div>
                ))}
                <Separator />
                <p className="text-2xs text-muted-foreground">
                  The vertical marker is the competitor average.
                </p>
              </CardContent>
            </Card>
          </div>

          <Stagger className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
            {data.competitors.map((competitor) => (
              <StaggerItem key={competitor.id}>
                <Card className="h-full">
                  <CardContent className="space-y-3 p-5">
                    <div className="flex items-start justify-between gap-2">
                      <div className="min-w-0">
                        <p className="truncate text-sm font-semibold">{competitor.name}</p>
                        <p className="flex items-center gap-1 text-2xs text-muted-foreground">
                          <MapPin className="h-3 w-3" />
                          {competitor.distance_km.toFixed(1)} km · {competitor.price_tier}
                        </p>
                      </div>
                      <span className="flex shrink-0 items-center gap-0.5 text-sm font-semibold tnum">
                        <Star className="h-3.5 w-3.5 fill-warning text-warning" />
                        {competitor.avg_rating.toFixed(1)}
                      </span>
                    </div>

                    <div className="space-y-1.5">
                      <p className="text-2xs font-semibold uppercase tracking-wide text-success">
                        Strengths
                      </p>
                      <div className="flex flex-wrap gap-1">
                        {competitor.strengths.map((item) => (
                          <Badge key={item} variant="success" className="normal-case">
                            {item}
                          </Badge>
                        ))}
                      </div>
                    </div>

                    <div className="space-y-1.5">
                      <p className="text-2xs font-semibold uppercase tracking-wide text-muted-foreground">
                        Weaknesses
                      </p>
                      <div className="flex flex-wrap gap-1">
                        {competitor.weaknesses.map((item) => (
                          <Badge key={item} variant="outline" className="normal-case">
                            {item}
                          </Badge>
                        ))}
                      </div>
                    </div>

                    {competitor.notes && (
                      <p className="text-2xs leading-relaxed text-muted-foreground">
                        {competitor.notes}
                      </p>
                    )}
                    <Badge variant="muted">{competitor.data_source}</Badge>
                  </CardContent>
                </Card>
              </StaggerItem>
            ))}
          </Stagger>
        </>
      )}
    </div>
  );
}

function GapChip({ gap }: { gap: number }) {
  const flat = Math.abs(gap) < 2;
  const Icon = flat ? Minus : gap > 0 ? TrendingUp : TrendingDown;
  return (
    <span
      className={cn(
        "inline-flex items-center gap-0.5 text-xs font-medium tnum",
        flat ? "text-muted-foreground" : gap > 0 ? "text-success" : "text-destructive",
      )}
    >
      <Icon className="h-3 w-3" />
      {gap >= 0 ? "+" : ""}
      {gap.toFixed(0)}
    </span>
  );
}
