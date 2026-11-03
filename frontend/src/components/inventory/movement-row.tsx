"use client";

/**
 * One row of the stock ledger.
 *
 * The ledger is append-only and is the system's account of itself, so the row
 * leads with the balance it left behind rather than the quantity that moved -
 * "what was true afterwards" is the question an auditor is actually asking.
 */

import {
  ArrowDownLeft,
  ArrowUpRight,
  CircleDot,
  PackageCheck,
  RotateCcw,
  ShoppingBag,
  Trash2,
  TriangleAlert,
  type LucideIcon,
} from "lucide-react";
import Link from "next/link";

import { cn, formatNumber, formatRelativeTime } from "@/lib/utils";
import type { LedgerRow } from "@/types/api";

/** Icon and tone per movement type; the fallback keeps unknown types readable. */
const MOVEMENT: Record<string, { icon: LucideIcon; tone: string; label: string }> = {
  SALE: { icon: ShoppingBag, tone: "text-primary", label: "Sale" },
  PURCHASE_RECEIPT: { icon: PackageCheck, tone: "text-success", label: "Goods received" },
  CUSTOMER_RETURN: { icon: RotateCcw, tone: "text-success", label: "Customer return" },
  TRANSFER_IN: { icon: ArrowDownLeft, tone: "text-success", label: "Transfer in" },
  TRANSFER_OUT: { icon: ArrowUpRight, tone: "text-warning", label: "Transfer out" },
  ADJUSTMENT: { icon: CircleDot, tone: "text-muted-foreground", label: "Correction" },
  DAMAGE: { icon: TriangleAlert, tone: "text-destructive", label: "Damaged" },
  EXPIRY: { icon: Trash2, tone: "text-destructive", label: "Expired" },
  RESERVATION: { icon: CircleDot, tone: "text-muted-foreground", label: "Reserved" },
  RELEASE: { icon: CircleDot, tone: "text-muted-foreground", label: "Reservation released" },
};

export function MovementRow({
  row,
  unit = "",
  showItem = false,
}: {
  row: LedgerRow;
  unit?: string;
  /** The ledger page lists many SKUs, so it needs the item named. */
  showItem?: boolean;
}) {
  const meta = MOVEMENT[row.movement_type] ?? {
    icon: CircleDot,
    tone: "text-muted-foreground",
    label: row.movement_type.toLowerCase().replace(/_/g, " "),
  };
  const Icon = meta.icon;
  const delta = row.balance_after - row.balance_before;
  const automated = row.actor_type !== "USER";

  return (
    <div className="flex items-start gap-3 rounded-lg border border-border bg-card p-3">
      <span className={cn("mt-0.5 flex h-7 w-7 shrink-0 items-center justify-center", meta.tone)}>
        <Icon className="h-4 w-4" />
      </span>

      <div className="min-w-0 flex-1">
        <div className="flex flex-wrap items-baseline gap-x-2 gap-y-0.5">
          <span className="text-xs font-medium">{meta.label}</span>
          <span
            className={cn(
              "font-mono text-xs font-semibold tabular-nums",
              delta > 0 ? "text-success" : delta < 0 ? "text-destructive" : "text-muted-foreground",
            )}
          >
            {delta > 0 ? "+" : ""}
            {formatNumber(delta)}
            {unit && ` ${unit}`}
          </span>
          <span className="text-2xs text-muted-foreground tabular-nums">
            {formatNumber(row.balance_before)} → {formatNumber(row.balance_after)}
          </span>
        </div>

        {showItem && (
          <Link
            href={`/inventory/${row.inventory_item_id}`}
            className="mt-0.5 block font-mono text-2xs text-primary hover:underline"
          >
            {row.inventory_item_id.slice(0, 8)}
          </Link>
        )}

        {row.note && <p className="mt-0.5 text-2xs text-muted-foreground">{row.note}</p>}

        <div className="mt-1 flex flex-wrap items-center gap-x-3 gap-y-0.5 text-2xs text-muted-foreground/80">
          <span>{formatRelativeTime(row.created_at ?? "")}</span>
          <span>{automated ? "by automation" : "by a person"}</span>
          {row.reference_type && (
            <span className="font-mono">
              {row.reference_type}
              {row.reference_id && ` ${row.reference_id}`}
            </span>
          )}
          {row.correlation_id && (
            <Link
              href={`/inventory/automation?correlation=${encodeURIComponent(row.correlation_id)}`}
              className="font-mono text-primary hover:underline"
              title="Open the full chain this movement belongs to"
            >
              {row.correlation_id}
            </Link>
          )}
        </div>
      </div>
    </div>
  );
}
