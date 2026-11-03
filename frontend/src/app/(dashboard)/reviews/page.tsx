"use client";

import {
  Frown,
  Meh,
  Search,
  Smile,
  Star,
  TrendingDown,
  TrendingUp,
} from "lucide-react";
import * as React from "react";

import { RatingTrendChart, TopicBarChart } from "@/components/charts/charts";
import { EmptyState, ErrorState, LoadingChart, LoadingRows } from "@/components/common/states";
import { RangePicker, useRangeDays } from "@/components/dashboard/range-picker";
import { ReviewBrowser } from "@/components/reviews/review-browser";
import { ReviewRow } from "@/components/reviews/review-row";
import { Button } from "@/components/ui/button";
import { FadeIn, Stagger, StaggerItem } from "@/components/ui/motion";
import {
  Badge,
  Card,
  CardContent,
  CardHeader,
  CardTitle,
  Input,
  Progress,
  Separator,
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from "@/components/ui/primitives";
import { useReviewIntelligence, useReviewSearch } from "@/hooks/use-api";
import { cn, formatDate, formatNumber, formatPercent } from "@/lib/utils";
import type { Review, TopicStat } from "@/types/api";

export default function ReviewsPage() {
  const [days, setDays] = useRangeDays(30);
  const { data, isLoading, error, refetch } = useReviewIntelligence(days);
  const search = useReviewSearch();
  const [query, setQuery] = React.useState("");

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h2 className="text-xl font-semibold tracking-tight">Review Intelligence</h2>
          <p className="text-sm text-muted-foreground">
            {data
              ? `${formatNumber(data.period_reviews)} reviews this period of ${formatNumber(data.total_reviews)} total`
              : "What customers are actually saying"}
          </p>
        </div>
        <RangePicker days={days} onChange={setDays} />
      </div>

      {isLoading && <LoadingRows rows={4} />}
      {error && <ErrorState error={error} onRetry={() => void refetch()} />}

      {data && (
        <>
          {/* Sentiment */}
          <Stagger className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
            <StaggerItem>
              <SentimentTile
                icon={Star}
                label="Average rating"
                value={data.sentiment.avg_rating.toFixed(2)}
                delta={data.sentiment.avg_rating_change}
                deltaFormat={(n) => `${n >= 0 ? "+" : ""}${n.toFixed(2)}`}
              />
            </StaggerItem>
            <StaggerItem>
              <SentimentTile
                icon={Smile}
                label="Positive"
                value={formatPercent(data.sentiment.positive_pct)}
                sub={`${formatNumber(data.sentiment.positive)} reviews`}
                tone="success"
              />
            </StaggerItem>
            <StaggerItem>
              <SentimentTile
                icon={Meh}
                label="Neutral"
                value={formatPercent(data.sentiment.neutral_pct)}
                sub={`${formatNumber(data.sentiment.neutral)} reviews`}
              />
            </StaggerItem>
            <StaggerItem>
              <SentimentTile
                icon={Frown}
                label="Negative"
                value={formatPercent(data.sentiment.negative_pct)}
                sub={`${formatNumber(data.sentiment.negative)} reviews`}
                tone="destructive"
              />
            </StaggerItem>
          </Stagger>

          {/* Emerging complaints - the signal the Growth Scientist uses */}
          {data.emerging_complaints.length > 0 && (
            <FadeIn>
              <Card className="border-warning/30">
                <CardHeader>
                  <CardTitle className="flex items-center gap-2">
                    <TrendingUp className="h-4 w-4 text-warning" />
                    Emerging complaints
                  </CardTitle>
                  <p className="text-sm text-muted-foreground">
                    Measured per 100 orders, so a shrinking segment cannot hide a worsening
                    experience.
                  </p>
                </CardHeader>
                <CardContent className="space-y-3">
                  {data.emerging_complaints.map((topic) => (
                    <TopicRow key={topic.topic} topic={topic} highlight />
                  ))}
                </CardContent>
              </Card>
            </FadeIn>
          )}

          <div className="grid gap-4 lg:grid-cols-2">
            {/* Topics */}
            <Card>
              <CardHeader>
                <CardTitle>Topic distribution</CardTitle>
                <p className="text-sm text-muted-foreground">
                  All reviews, with the negative share highlighted
                </p>
              </CardHeader>
              <CardContent>
                <TopicBarChart
                  data={data.topics.slice(0, 8).map((topic) => ({
                    label: topic.label,
                    count: topic.count,
                    negative_count: topic.negative_count,
                  }))}
                />
              </CardContent>
            </Card>

            {/* By slot */}
            <Card>
              <CardHeader>
                <CardTitle>Negative share by trading slot</CardTitle>
                <p className="text-sm text-muted-foreground">
                  Where the experience is degrading fastest
                </p>
              </CardHeader>
              <CardContent className="space-y-3">
                {data.by_daypart.map((slot) => (
                  <div key={slot.topic} className="space-y-1.5">
                    <div className="flex items-center justify-between text-sm">
                      <span className="font-medium">{slot.label}</span>
                      <span className="flex items-center gap-2">
                        <span className="tnum">{formatPercent(slot.negative_share_pct)}</span>
                        {slot.change_pct != null && (
                          <span
                            className={cn(
                              "text-xs font-medium tnum",
                              slot.change_pct > 0 ? "text-destructive" : "text-success",
                            )}
                          >
                            {slot.change_pct >= 0 ? "+" : ""}
                            {slot.change_pct.toFixed(0)}%
                          </span>
                        )}
                      </span>
                    </div>
                    <Progress
                      value={Math.min(slot.negative_share_pct * 3, 100)}
                      className="h-1.5"
                      indicatorClassName={
                        slot.negative_share_pct > 15
                          ? "bg-destructive"
                          : slot.negative_share_pct > 8
                            ? "bg-warning"
                            : "bg-success"
                      }
                    />
                    <p className="text-2xs text-muted-foreground">
                      {formatNumber(slot.negative_count)} negative of {formatNumber(slot.count)}{" "}
                      reviews · avg {slot.avg_rating.toFixed(1)}
                    </p>
                  </div>
                ))}
              </CardContent>
            </Card>
          </div>

          <div className="grid gap-4 lg:grid-cols-[minmax(0,1.4fr)_minmax(0,1fr)]">
            <Card>
              <CardHeader>
                <CardTitle>Rating trend</CardTitle>
                <p className="text-sm text-muted-foreground">Daily average</p>
              </CardHeader>
              <CardContent>
                <RatingTrendChart data={data.rating_trend} />
              </CardContent>
            </Card>

            <Card>
              <CardHeader>
                <CardTitle className="flex items-center gap-2">
                  <TrendingDown className="h-4 w-4 text-success" />
                  Positive themes
                </CardTitle>
                <p className="text-sm text-muted-foreground">What is working</p>
              </CardHeader>
              <CardContent className="space-y-2.5">
                {data.positive_themes.length === 0 && (
                  <p className="py-4 text-center text-sm text-muted-foreground">
                    No durable positive themes this period.
                  </p>
                )}
                {data.positive_themes.map((topic) => (
                  <div
                    key={topic.topic}
                    className="flex items-center justify-between rounded-lg border border-border bg-card px-3 py-2"
                  >
                    <span className="text-sm font-medium">{topic.label}</span>
                    <span className="flex items-center gap-2 text-2xs text-muted-foreground">
                      <span className="tnum">{formatNumber(topic.positive_count)} positive</span>
                      <Badge variant="success">{topic.avg_rating.toFixed(1)}</Badge>
                    </span>
                  </div>
                ))}
              </CardContent>
            </Card>
          </div>

          {/* Semantic search */}
          <Card>
            <CardHeader>
              <CardTitle>Search the review corpus</CardTitle>
              <p className="text-sm text-muted-foreground">
                Vector similarity over review embeddings stored in pgvector
              </p>
            </CardHeader>
            <CardContent className="space-y-3">
              <form
                onSubmit={(event) => {
                  event.preventDefault();
                  if (query.trim().length > 1) search.mutate({ query: query.trim() });
                }}
                className="flex gap-2"
              >
                <Input
                  value={query}
                  onChange={(event) => setQuery(event.target.value)}
                  placeholder="e.g. long wait in the evening"
                  className="flex-1"
                />
                <Button type="submit" loading={search.isPending} className="gap-2">
                  <Search className="h-4 w-4" />
                  Search
                </Button>
              </form>

              {search.data && search.data.length > 0 && (
                <div className="space-y-2">
                  {search.data.map((hit) => (
                    <ReviewRow key={hit.review.id} review={hit.review} similarity={hit.similarity} />
                  ))}
                </div>
              )}
              {search.data && search.data.length === 0 && (
                <EmptyState title="No matching reviews" />
              )}
            </CardContent>
          </Card>

          {/* Full corpus: filters + pagination */}
          <ReviewBrowser topics={data.topics} />
        </>
      )}
    </div>
  );
}

function SentimentTile({
  icon: Icon,
  label,
  value,
  sub,
  delta,
  deltaFormat,
  tone,
}: {
  icon: typeof Star;
  label: string;
  value: string;
  sub?: string;
  delta?: number | null;
  deltaFormat?: (n: number) => string;
  tone?: "success" | "destructive";
}) {
  return (
    <Card>
      <CardContent className="space-y-2 p-5">
        <div className="flex items-center gap-2">
          <Icon
            className={cn(
              "h-4 w-4",
              tone === "success"
                ? "text-success"
                : tone === "destructive"
                  ? "text-destructive"
                  : "text-muted-foreground",
            )}
          />
          <p className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
            {label}
          </p>
        </div>
        <p className="text-2xl font-semibold leading-none tracking-tight tnum">{value}</p>
        <div className="flex items-center gap-2 text-2xs">
          {sub && <span className="text-muted-foreground">{sub}</span>}
          {delta != null && deltaFormat && (
            <span
              className={cn("font-medium tnum", delta >= 0 ? "text-success" : "text-destructive")}
            >
              {deltaFormat(delta)}
            </span>
          )}
        </div>
      </CardContent>
    </Card>
  );
}

function TopicRow({ topic, highlight }: { topic: TopicStat; highlight?: boolean }) {
  return (
    <div
      className={cn(
        "rounded-lg border p-3",
        highlight ? "border-warning/30 bg-warning/5" : "border-border bg-card",
      )}
    >
      <div className="flex items-center justify-between gap-2">
        <span className="flex items-center gap-2">
          <span className="text-sm font-medium">{topic.label}</span>
          {topic.is_emerging_complaint && <Badge variant="warning">Emerging</Badge>}
        </span>
        <span className="flex items-center gap-2 text-sm">
          <span className="tnum">{formatNumber(topic.negative_count)} negative</span>
          {topic.change_pct != null && (
            <Tooltip>
              <TooltipTrigger asChild>
                <span
                  className={cn(
                    "cursor-help font-semibold tnum",
                    topic.change_pct > 0 ? "text-destructive" : "text-success",
                  )}
                >
                  {topic.change_pct >= 0 ? "+" : ""}
                  {topic.change_pct.toFixed(0)}%
                </span>
              </TooltipTrigger>
              <TooltipContent>
                Change in complaints per 100 orders versus the previous period, not raw volume.
              </TooltipContent>
            </Tooltip>
          )}
        </span>
      </div>
      <Progress
        value={Math.min(topic.negative_share_pct, 100)}
        className="mt-2 h-1"
        indicatorClassName="bg-warning"
      />
    </div>
  );
}

