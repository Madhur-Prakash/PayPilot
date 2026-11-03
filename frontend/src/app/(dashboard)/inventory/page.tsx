"use client";

/**
 * Live inventory.
 *
 * The table does no arithmetic of its own: status, availability and the reorder
 * decision all come from the backend, so what is shown here is exactly what the
 * automation acts on. Updates arrive over the websocket - no polling, and no
 * manual refresh.
 */

import {
  Boxes,
  Download,
  PackageSearch,
  RefreshCw,
  Search,
  ShoppingCart,
  Wifi,
  WifiOff,
} from "lucide-react";
import Link from "next/link";
import * as React from "react";

import { EmptyState, ErrorState, LoadingRows } from "@/components/common/states";
import { BulkImportDialog } from "@/components/inventory/bulk-import-dialog";
import { InventoryExportDialog } from "@/components/inventory/export-dialog";
import { StatusChip, StockBar, statusMeta } from "@/components/inventory/stock-status";
import { Button } from "@/components/ui/button";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/overlays";
import {
  Badge,
  Card,
  CardContent,
  CardHeader,
  CardTitle,
  Input,
  Separator,
} from "@/components/ui/primitives";
import { useForceReorder, useInventoryItems } from "@/hooks/use-api";
import { useInventoryStream } from "@/hooks/use-inventory-stream";
import { usePageVoiceContext } from "@/hooks/use-page-voice-context";
import { useAuthStore } from "@/stores/auth";
import { cn, formatCompactCurrency, formatNumber, formatRelativeTime } from "@/lib/utils";

const STATUSES = [
  "OUT_OF_STOCK",
  "CRITICAL",
  "REORDER_REQUIRED",
  "WATCH",
  "HEALTHY",
  "OVERSTOCKED",
];

export default function InventoryPage() {
  const [draft, setDraft] = React.useState("");
  const [q, setQ] = React.useState("");
  const [status, setStatus] = React.useState("all");
  const [page, setPage] = React.useState(1);
  const [exporting, setExporting] = React.useState(false);

  const { status: streamStatus, lastEvent } = useInventoryStream();
  const canReorder = useAuthStore((s) => s.can("purchase_order:create"));
  const canExport = useAuthStore((s) => s.can("inventory:reports_export"));
  const reorder = useForceReorder();

  React.useEffect(() => {
    const id = setTimeout(() => setQ(draft.trim()), 300);
    return () => clearTimeout(id);
  }, [draft]);

  React.useEffect(() => setPage(1), [q, status]);

  const { data, isLoading, isFetching, error, refetch } = useInventoryItems({
    page,
    page_size: 25,
    q: q || undefined,
    status: status === "all" ? undefined : status,
  });

  const rows = data?.data.items ?? [];
  const meta = data?.data.pagination;
  const showsValue = Boolean(data?.meta?.shows_value);

  // Counts come from the rows on screen; the headline totals below are honest
  // about being page-scoped rather than implying a full-catalogue aggregate.
  const needsAttention = rows.filter((r) => statusMeta(r.status).rank <= 2).length;
  const automated = rows.filter((r) => r.automatic_ordering_enabled).length;
  const pageValue = rows.reduce((sum, r) => sum + (r.stock_value ?? 0), 0);

  // Feeds the voice assistant what's actually on screen - not a second fetch,
  // just a sentence built from the rows already rendered below.
  usePageVoiceContext(
    meta
      ? `${formatNumber(meta.total)} inventory items. ${needsAttention} need attention right now (critical or reorder-required). ${automated} have automatic ordering on.`
      : null,
  );

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h2 className="text-xl font-semibold tracking-tight">Inventory</h2>
          <p className="text-sm text-muted-foreground">
            Live stock, reorder policy and the automation that acts on it
          </p>
        </div>
        <div className="flex items-center gap-2">
          <span
            className={cn(
              "inline-flex items-center gap-1.5 rounded-lg border px-2 py-1 text-2xs font-medium",
              streamStatus === "live"
                ? "border-success/30 bg-success/10 text-success"
                : streamStatus === "connecting"
                  ? "border-border bg-muted text-muted-foreground"
                  : "border-destructive/30 bg-destructive/10 text-destructive",
            )}
            title={
              streamStatus === "live"
                ? "Updates arrive over a websocket"
                : "Reconnecting - the table still reads correctly, just not live"
            }
          >
            {streamStatus === "live" ? (
              <Wifi className="h-3 w-3" />
            ) : (
              <WifiOff className="h-3 w-3" />
            )}
            {streamStatus === "live" ? "Live" : streamStatus}
          </span>

          <Button asChild variant="outline" size="sm" className="gap-1.5">
            <Link href="/inventory/automation">
              <RefreshCw className="h-3.5 w-3.5" />
              Automation
            </Link>
          </Button>
          <Button asChild variant="outline" size="sm" className="gap-1.5">
            <Link href="/purchase-orders">
              <ShoppingCart className="h-3.5 w-3.5" />
              Orders
            </Link>
          </Button>
          <BulkImportDialog />
          {canExport && (
            <Button
              variant="outline"
              size="sm"
              className="gap-1.5"
              onClick={() => setExporting(true)}
            >
              <Download className="h-3.5 w-3.5" />
              Export
            </Button>
          )}
        </div>
      </div>

      {/* Tiles */}
      <div className="grid gap-4 sm:grid-cols-3">
        <Tile
          icon={PackageSearch}
          value={formatNumber(meta?.total ?? 0)}
          label="Tracked SKUs"
          hint="across this merchant"
        />
        <Tile
          icon={Boxes}
          value={formatNumber(needsAttention)}
          label="Need attention"
          hint="on this page"
          tone={needsAttention > 0 ? "warning" : "default"}
        />
        {showsValue ? (
          <Tile
            icon={ShoppingCart}
            value={formatCompactCurrency(pageValue)}
            label="Stock value"
            hint="on this page"
          />
        ) : (
          <Tile
            icon={RefreshCw}
            value={`${automated}/${rows.length || 0}`}
            label="Auto-ordering on"
            hint="on this page"
          />
        )}
      </div>

      {lastEvent && (
        <p className="text-2xs text-muted-foreground">
          Last update: <span className="font-mono">{lastEvent.event}</span>{" "}
          {formatRelativeTime(lastEvent.at)}
        </p>
      )}

      {/* Table */}
      <Card>
        <CardHeader className="pb-3">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <CardTitle className="text-base">Stock</CardTitle>
            <div className="flex flex-wrap items-center gap-2">
              <div className="relative">
                <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
                <Input
                  value={draft}
                  onChange={(event) => setDraft(event.target.value)}
                  placeholder="SKU or product…"
                  className="w-56 pl-9"
                  aria-label="Search inventory"
                />
              </div>
              <Select value={status} onValueChange={setStatus}>
                <SelectTrigger className="w-[180px]">
                  <SelectValue placeholder="All statuses" />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="all">All statuses</SelectItem>
                  {STATUSES.map((value) => (
                    <SelectItem key={value} value={value}>
                      {statusMeta(value).label}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
          </div>
        </CardHeader>

        <CardContent className="space-y-2">
          {isLoading && <LoadingRows rows={6} />}
          {error && <ErrorState error={error} onRetry={() => void refetch()} />}

          {!isLoading && !error && rows.length === 0 && (
            <EmptyState
              icon={PackageSearch}
              title="No stock matches"
              description="Try clearing the search or the status filter."
            />
          )}

          {rows.length > 0 && (
            <div className={cn("space-y-2 transition-opacity", isFetching && "opacity-60")}>
              {rows.map((row) => {
                const belowPoint = row.available_quantity <= row.reorder_point;
                return (
                  <div
                    key={row.id}
                    className="rounded-lg border border-border bg-card p-3 transition-colors hover:border-primary/40"
                  >
                    <div className="flex flex-wrap items-start justify-between gap-3">
                      <div className="min-w-0 flex-1">
                        <div className="flex flex-wrap items-center gap-2">
                          <Link
                            href={`/inventory/${row.id}`}
                            className="text-sm font-semibold hover:underline"
                          >
                            {row.product_name}
                          </Link>
                          <span className="font-mono text-2xs text-muted-foreground">
                            {row.sku}
                          </span>
                          <StatusChip status={row.status} />
                          {row.automatic_ordering_enabled && (
                            <Badge variant="outline" className="text-2xs">
                              auto
                            </Badge>
                          )}
                        </div>

                        <div className="mt-2 flex flex-wrap items-center gap-x-5 gap-y-1 text-2xs text-muted-foreground tabular-nums">
                          <span>
                            On hand{" "}
                            <strong className="text-foreground">
                              {formatNumber(row.quantity_on_hand)}
                            </strong>
                          </span>
                          <span>
                            Reserved{" "}
                            <strong className="text-foreground">
                              {formatNumber(row.reserved_quantity)}
                            </strong>
                          </span>
                          <span>
                            Available{" "}
                            <strong
                              className={cn(
                                belowPoint ? "text-warning" : "text-foreground",
                              )}
                            >
                              {formatNumber(row.available_quantity)}
                            </strong>
                          </span>
                          <span>
                            Reorder at{" "}
                            <strong className="text-foreground">
                              {formatNumber(row.reorder_point)}
                            </strong>
                          </span>
                          {row.stock_value != null && (
                            <span>
                              Value{" "}
                              <strong className="text-foreground">
                                {formatCompactCurrency(row.stock_value)}
                              </strong>
                            </span>
                          )}
                          <span className="text-muted-foreground/70">{row.supplier}</span>
                        </div>

                        <div className="mt-2 max-w-md">
                          <StockBar
                            available={row.available_quantity}
                            reorderPoint={row.reorder_point}
                            maximum={row.maximum_stock}
                          />
                        </div>
                      </div>

                      {canReorder && belowPoint && (
                        <Button
                          size="sm"
                          variant="outline"
                          className="gap-1.5"
                          loading={reorder.isPending && reorder.variables === row.id}
                          onClick={() => reorder.mutate(row.id)}
                        >
                          <ShoppingCart className="h-3.5 w-3.5" />
                          Reorder
                        </Button>
                      )}
                    </div>
                  </div>
                );
              })}
            </div>
          )}

          {meta && meta.total_pages > 1 && (
            <>
              <Separator />
              <div className="flex items-center justify-between gap-3 pt-1">
                <p className="text-2xs text-muted-foreground tabular-nums">
                  Page {meta.page} of {formatNumber(meta.total_pages)} ·{" "}
                  {formatNumber(meta.total)} items
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

      <InventoryExportDialog open={exporting} onClose={() => setExporting(false)} />
    </div>
  );
}

function Tile({
  icon: Icon,
  value,
  label,
  hint,
  tone = "default",
}: {
  icon: typeof Boxes;
  value: string;
  label: string;
  hint: string;
  tone?: "default" | "warning";
}) {
  return (
    <Card>
      <CardContent className="flex items-center gap-3 p-4">
        <span
          className={cn(
            "flex h-9 w-9 shrink-0 items-center justify-center rounded-lg",
            tone === "warning" ? "bg-warning/10 text-warning" : "bg-primary/10 text-primary",
          )}
        >
          <Icon className="h-4 w-4" />
        </span>
        <div className="min-w-0">
          <p className="text-lg font-semibold leading-none tracking-tight tabular-nums">
            {value}
          </p>
          <p className="mt-1 text-2xs text-muted-foreground">
            {label} · {hint}
          </p>
        </div>
      </CardContent>
    </Card>
  );
}
