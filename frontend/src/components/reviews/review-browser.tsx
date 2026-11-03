"use client";

import { ChevronLeft, ChevronRight, Search, Star, X } from "lucide-react";
import * as React from "react";

import { EmptyState, ErrorState, LoadingRows } from "@/components/common/states";
import { ReviewRow } from "@/components/reviews/review-row";
import { Button } from "@/components/ui/button";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/overlays";
import {
  Card,
  CardContent,
  CardHeader,
  CardTitle,
  Input,
  Separator,
} from "@/components/ui/primitives";
import { useReviewList } from "@/hooks/use-api";
import { cn, formatNumber } from "@/lib/utils";
import type { TopicStat } from "@/types/api";

const PAGE_SIZE = 10;
const ALL = "all";

const SENTIMENTS = [
  { value: "POSITIVE", label: "Positive" },
  { value: "NEUTRAL", label: "Neutral" },
  { value: "NEGATIVE", label: "Negative" },
];

const DAYPARTS = [
  { value: "MORNING", label: "Morning" },
  { value: "AFTERNOON", label: "Afternoon" },
  { value: "EVENING", label: "Evening" },
  { value: "NIGHT", label: "Night" },
];

export function ReviewBrowser({ topics }: { topics: TopicStat[] }) {
  const [draft, setDraft] = React.useState("");
  const [query, setQuery] = React.useState("");
  const [rating, setRating] = React.useState<number | null>(null);
  const [sentiment, setSentiment] = React.useState<string>(ALL);
  const [topic, setTopic] = React.useState<string>(ALL);
  const [daypart, setDaypart] = React.useState<string>(ALL);
  const [page, setPage] = React.useState(1);

  // Debounce typing so every keystroke does not hit the API.
  React.useEffect(() => {
    const id = setTimeout(() => setQuery(draft.trim()), 300);
    return () => clearTimeout(id);
  }, [draft]);

  // Any filter change invalidates the current page number.
  React.useEffect(() => {
    setPage(1);
  }, [query, rating, sentiment, topic, daypart]);

  const { data, isLoading, isFetching, error, refetch } = useReviewList({
    page,
    page_size: PAGE_SIZE,
    q: query || undefined,
    rating: rating ?? undefined,
    sentiment: sentiment === ALL ? undefined : sentiment,
    topic: topic === ALL ? undefined : topic,
    daypart: daypart === ALL ? undefined : daypart,
  });

  const reviews = data?.data.items ?? [];
  const meta = data?.data.pagination;
  const facets = (data?.meta?.rating_counts ?? {}) as Record<string, number>;

  const hasFilters =
    query !== "" || rating !== null || sentiment !== ALL || topic !== ALL || daypart !== ALL;

  const reset = () => {
    setDraft("");
    setQuery("");
    setRating(null);
    setSentiment(ALL);
    setTopic(ALL);
    setDaypart(ALL);
  };

  return (
    <Card>
      <CardHeader>
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div>
            <CardTitle>Browse reviews</CardTitle>
            <p className="text-sm text-muted-foreground">
              {meta
                ? `${formatNumber(meta.total)} ${meta.total === 1 ? "review" : "reviews"} match${
                    hasFilters ? " these filters" : ""
                  }`
                : "Filter by text, rating, sentiment, topic or trading slot"}
            </p>
          </div>
          {hasFilters && (
            <Button variant="ghost" size="sm" onClick={reset} className="gap-1.5">
              <X className="h-3.5 w-3.5" />
              Clear filters
            </Button>
          )}
        </div>
      </CardHeader>

      <CardContent className="space-y-4">
        {/* Text search */}
        <div className="relative">
          <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
          <Input
            value={draft}
            onChange={(event) => setDraft(event.target.value)}
            placeholder="Search review text, title or author…"
            className="pl-9"
            aria-label="Search reviews"
          />
        </div>

        {/* Rating facets */}
        <div className="flex flex-wrap items-center gap-2">
          <RatingChip
            active={rating === null}
            onClick={() => setRating(null)}
            label="All ratings"
            count={Object.values(facets).reduce((sum, n) => sum + n, 0)}
          />
          {[5, 4, 3, 2, 1].map((star) => (
            <RatingChip
              key={star}
              active={rating === star}
              onClick={() => setRating(rating === star ? null : star)}
              count={facets[String(star)] ?? 0}
              star={star}
            />
          ))}
        </div>

        {/* Dropdown filters */}
        <div className="grid gap-2 sm:grid-cols-3">
          <FilterSelect
            value={sentiment}
            onChange={setSentiment}
            placeholder="All sentiment"
            options={SENTIMENTS}
          />
          <FilterSelect
            value={topic}
            onChange={setTopic}
            placeholder="All topics"
            options={topics.map((t) => ({ value: t.topic, label: t.label }))}
          />
          <FilterSelect
            value={daypart}
            onChange={setDaypart}
            placeholder="All slots"
            options={DAYPARTS}
          />
        </div>

        <Separator />

        {/* Results */}
        {isLoading && <LoadingRows rows={4} />}
        {error && <ErrorState error={error} onRetry={() => void refetch()} />}

        {!isLoading && !error && reviews.length === 0 && (
          <EmptyState
            title="No reviews match these filters"
            description="Try clearing a filter or widening the search."
          />
        )}

        {reviews.length > 0 && (
          <div className={cn("space-y-2 transition-opacity", isFetching && "opacity-60")}>
            {reviews.map((review) => (
              <ReviewRow key={review.id} review={review} />
            ))}
          </div>
        )}

        {/* Pagination */}
        {meta && meta.total_pages > 1 && (
          <div className="flex items-center justify-between gap-3 pt-1">
            <p className="text-2xs text-muted-foreground tnum">
              Page {meta.page} of {formatNumber(meta.total_pages)}
            </p>
            <div className="flex items-center gap-2">
              <Button
                variant="outline"
                size="sm"
                className="gap-1"
                disabled={!meta.has_previous || isFetching}
                onClick={() => setPage((p) => Math.max(1, p - 1))}
              >
                <ChevronLeft className="h-4 w-4" />
                Previous
              </Button>
              <Button
                variant="outline"
                size="sm"
                className="gap-1"
                disabled={!meta.has_next || isFetching}
                onClick={() => setPage((p) => p + 1)}
              >
                Next
                <ChevronRight className="h-4 w-4" />
              </Button>
            </div>
          </div>
        )}
      </CardContent>
    </Card>
  );
}

function RatingChip({
  active,
  onClick,
  count,
  star,
  label,
}: {
  active: boolean;
  onClick: () => void;
  count: number;
  star?: number;
  label?: string;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      aria-pressed={active}
      className={cn(
        "inline-flex items-center gap-1.5 rounded-lg border px-2.5 py-1.5 text-xs font-medium transition-colors focus-ring",
        active
          ? "border-primary bg-primary text-primary-foreground"
          : "border-border bg-card text-foreground hover:bg-muted",
        count === 0 && !active && "opacity-50",
      )}
    >
      {star != null ? (
        <>
          <span className="tnum">{star}</span>
          <Star className={cn("h-3 w-3", active ? "fill-current" : "fill-warning text-warning")} />
        </>
      ) : (
        label
      )}
      <span className={cn("tnum", active ? "opacity-80" : "text-muted-foreground")}>
        {formatNumber(count)}
      </span>
    </button>
  );
}

function FilterSelect({
  value,
  onChange,
  placeholder,
  options,
}: {
  value: string;
  onChange: (value: string) => void;
  placeholder: string;
  options: { value: string; label: string }[];
}) {
  return (
    <Select value={value} onValueChange={onChange}>
      <SelectTrigger>
        <SelectValue placeholder={placeholder} />
      </SelectTrigger>
      <SelectContent>
        <SelectItem value={ALL}>{placeholder}</SelectItem>
        {options.map((option) => (
          <SelectItem key={option.value} value={option.value}>
            {option.label}
          </SelectItem>
        ))}
      </SelectContent>
    </Select>
  );
}
