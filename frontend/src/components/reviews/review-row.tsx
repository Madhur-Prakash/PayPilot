"use client";

import { Star } from "lucide-react";

import { Badge } from "@/components/ui/primitives";
import { cn, formatDate } from "@/lib/utils";
import type { Review } from "@/types/api";

/** One review, shared by the browser list and the semantic search results. */
export function ReviewRow({ review, similarity }: { review: Review; similarity?: number }) {
  const tone =
    review.sentiment === "POSITIVE"
      ? "text-success"
      : review.sentiment === "NEGATIVE"
        ? "text-destructive"
        : "text-muted-foreground";

  return (
    <div className="rounded-lg border border-border bg-card p-3">
      <div className="flex flex-wrap items-center gap-2">
        <span className={cn("flex items-center gap-0.5 text-sm font-semibold tnum", tone)}>
          <Star className="h-3.5 w-3.5 fill-current" />
          {review.rating}
        </span>
        <Badge variant="outline">{review.primary_topic.replace("_", " ")}</Badge>
        {review.daypart && <Badge variant="muted">{review.daypart.toLowerCase()}</Badge>}
        <span className="ml-auto text-2xs text-muted-foreground">
          {formatDate(review.review_date)}
          {similarity != null && ` · ${(similarity * 100).toFixed(0)}% match`}
        </span>
      </div>
      <p className="mt-1.5 text-sm leading-relaxed">{review.body}</p>
      <p className="mt-1 text-2xs text-muted-foreground">
        {review.author_name} · via {review.source}
      </p>
    </div>
  );
}
