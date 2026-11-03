"use client";

/**
 * The stock ledger.
 *
 * Append-only and the system's account of itself: if stock is wrong, the answer
 * is here. Filters exist for the two questions actually asked of it — "what
 * happened to this SKU?" and "what did this automation run touch?" — the second
 * of which arrives as a correlation id from somewhere else in the product.
 */

import { Filter, ScrollText, X } from "lucide-react";
import { useSearchParams } from "next/navigation";
import * as React from "react";

import { EmptyState, ErrorState, LoadingRows } from "@/components/common/states";
import { MovementRow } from "@/components/inventory/movement-row";
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
import { useInventoryLedger } from "@/hooks/use-api";
import { cn, formatNumber } from "@/lib/utils";

const MOVEMENT_TYPES = [
  "SALE",
  "PURCHASE_RECEIPT",
  "CUSTOMER_RETURN",
  "ADJUSTMENT",
  "DAMAGE",
  "EXPIRY",
  "TRANSFER_IN",
  "TRANSFER_OUT",
];

export default function LedgerPage() {
  const search = useSearchParams();

  const [itemId, setItemId] = React.useState(search?.get("item") ?? "");
  const [correlation, setCorrelation] = React.useState(search?.get("correlation") ?? "");
  const [movementType, setMovementType] = React.useState("all");
  const [page, setPage] = React.useState(1);

  React.useEffect(() => setPage(1), [itemId, correlation, movementType]);

  const { data, isLoading, isFetching, error, refetch } = useInventoryLedger({
    page,
    page_size: 40,
    inventory_item_id: itemId || undefined,
    correlation_id: correlation || undefined,
    movement_type: movementType === "all" ? undefined : movementType,
  });

  const rows = data?.items ?? [];
  const meta = data?.pagination;
  const filtered = Boolean(itemId || correlation || movementType !== "all");

  return (
    <div className="space-y-6">
      <div>
        <h2 className="text-xl font-semibold tracking-tight">Stock ledger</h2>
        <p className="text-sm text-muted-foreground">
          Every movement, in order, with the balance it left behind. Nothing here is ever edited.
        </p>
      </div>

      <Card>
        <CardHeader className="pb-3">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <CardTitle className="flex items-center gap-2 text-base">
              <Filter className="h-4 w-4 text-muted-foreground" />
              Filters
            </CardTitle>
            {filtered && (
              <Button
                variant="ghost"
                size="sm"
                className="gap-1.5"
                onClick={() => {
                  setItemId("");
                  setCorrelation("");
                  setMovementType("all");
                }}
              >
                <X className="h-3.5 w-3.5" />
                Clear
              </Button>
            )}
          </div>
        </CardHeader>
        <CardContent>
          <div className="grid gap-3 sm:grid-cols-3">
            <Input
              value={itemId}
              onChange={(event) => setItemId(event.target.value)}
              placeholder="Inventory item id"
              aria-label="Filter by inventory item"
              className="font-mono text-2xs"
            />
            <Input
              value={correlation}
              onChange={(event) => setCorrelation(event.target.value)}
              placeholder="Correlation id"
              aria-label="Filter by correlation id"
              className="font-mono text-2xs"
            />
            <Select value={movementType} onValueChange={setMovementType}>
              <SelectTrigger aria-label="Filter by movement type">
                <SelectValue placeholder="All movements" />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="all">All movements</SelectItem>
                {MOVEMENT_TYPES.map((type) => (
                  <SelectItem key={type} value={type}>
                    {type.toLowerCase().replace(/_/g, " ")}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>

          {correlation && (
            <p className="mt-3 text-2xs text-muted-foreground">
              Showing one automation chain. Every row below was caused by the same triggering
              event.
            </p>
          )}
        </CardContent>
      </Card>

      <Card>
        <CardHeader className="pb-3">
          <CardTitle className="text-base">
            {meta ? `${formatNumber(meta.total)} movements` : "Movements"}
          </CardTitle>
        </CardHeader>
        <CardContent className="space-y-2">
          {isLoading && <LoadingRows rows={8} />}
          {error && <ErrorState error={error} onRetry={() => void refetch()} />}

          {!isLoading && !error && rows.length === 0 && (
            <EmptyState
              icon={ScrollText}
              title="No movements match"
              description={
                filtered
                  ? "Try clearing a filter — the ids are exact matches, not searches."
                  : "Sales, receipts and corrections all appear here as they happen."
              }
            />
          )}

          <div className={cn("space-y-2", isFetching && "opacity-60")}>
            {rows.map((row) => (
              <MovementRow key={row.id} row={row} showItem={!itemId} />
            ))}
          </div>

          {meta && meta.total_pages > 1 && (
            <>
              <Separator />
              <div className="flex items-center justify-between gap-3 pt-1">
                <p className="text-2xs text-muted-foreground tabular-nums">
                  Page {meta.page} of {formatNumber(meta.total_pages)}
                </p>
                <div className="flex gap-2">
                  <Button
                    variant="outline"
                    size="sm"
                    disabled={!meta.has_previous || isFetching}
                    onClick={() => setPage((p) => Math.max(1, p - 1))}
                  >
                    Previous
                  </Button>
                  <Button
                    variant="outline"
                    size="sm"
                    disabled={!meta.has_next || isFetching}
                    onClick={() => setPage((p) => p + 1)}
                  >
                    Next
                  </Button>
                </div>
              </div>
            </>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
