"use client";

import { cn } from "@/lib/utils";

/** One vocabulary for stock state, so every surface reads the same. */
export const STOCK_STATUS: Record<
  string,
  { label: string; dot: string; chip: string; rank: number }
> = {
  OUT_OF_STOCK: {
    label: "Out of stock",
    dot: "bg-destructive",
    chip: "bg-destructive/10 text-destructive",
    rank: 0,
  },
  CRITICAL: {
    label: "Critical",
    dot: "bg-destructive",
    chip: "bg-destructive/10 text-destructive",
    rank: 1,
  },
  REORDER_REQUIRED: {
    label: "Reorder required",
    dot: "bg-warning",
    chip: "bg-warning/10 text-warning",
    rank: 2,
  },
  EXPIRED: {
    label: "Expired",
    dot: "bg-destructive",
    chip: "bg-destructive/10 text-destructive",
    rank: 2,
  },
  EXPIRING_SOON: {
    label: "Expiring soon",
    dot: "bg-warning",
    chip: "bg-warning/10 text-warning",
    rank: 3,
  },
  AGING: { label: "Aging", dot: "bg-warning", chip: "bg-warning/10 text-warning", rank: 4 },
  LOW: { label: "Low", dot: "bg-warning", chip: "bg-warning/10 text-warning", rank: 4 },
  WATCH: { label: "Watch", dot: "bg-primary", chip: "bg-primary/10 text-primary", rank: 5 },
  OVERSTOCKED: {
    label: "Overstocked",
    dot: "bg-muted-foreground",
    chip: "bg-muted text-muted-foreground",
    rank: 6,
  },
  HEALTHY: { label: "Healthy", dot: "bg-success", chip: "bg-success/10 text-success", rank: 7 },
  DISCONTINUED: {
    label: "Discontinued",
    dot: "bg-muted-foreground",
    chip: "bg-muted text-muted-foreground",
    rank: 8,
  },
};

export function statusMeta(status: string) {
  return (
    STOCK_STATUS[status] ?? {
      label: status.toLowerCase().replace(/_/g, " "),
      dot: "bg-muted-foreground",
      chip: "bg-muted text-muted-foreground",
      rank: 9,
    }
  );
}

export function StatusChip({ status, className }: { status: string; className?: string }) {
  const meta = statusMeta(status);
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1.5 rounded-md px-2 py-0.5 text-2xs font-semibold",
        meta.chip,
        className,
      )}
    >
      <span className={cn("h-1.5 w-1.5 rounded-full", meta.dot)} />
      {meta.label}
    </span>
  );
}

/**
 * Stock against its reorder point.
 *
 * The marker is the reorder point, not a percentage of capacity - that is the
 * number the automation actually acts on, so it is the one worth drawing.
 */
export function StockBar({
  available,
  reorderPoint,
  maximum,
}: {
  available: number;
  reorderPoint: number;
  maximum: number;
}) {
  const ceiling = Math.max(maximum || 0, reorderPoint * 2, available, 1);
  const fill = Math.min((available / ceiling) * 100, 100);
  const marker = Math.min((reorderPoint / ceiling) * 100, 100);
  const below = available <= reorderPoint;

  return (
    <div className="relative h-1.5 w-full overflow-hidden rounded-full bg-muted">
      <div
        className={cn("h-full rounded-full", below ? "bg-warning" : "bg-success")}
        style={{ width: `${Math.max(fill, 2)}%` }}
      />
      {reorderPoint > 0 && (
        <span
          className="absolute top-0 h-full w-px bg-foreground/50"
          style={{ left: `${marker}%` }}
          title={`Reorder point: ${reorderPoint}`}
        />
      )}
    </div>
  );
}
