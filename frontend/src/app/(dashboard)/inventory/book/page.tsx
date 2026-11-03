"use client";

/**
 * The inventory book.
 *
 * Opening, everything that moved, closing — per SKU, derived from the ledger
 * rather than stored anywhere. That derivation is the point: the closing figure
 * on this page and the stock on the item page come from the same rows, so if
 * they ever disagree the ledger is the one telling the truth.
 *
 * It is also the page an accountant asks for, which is why the export produces a
 * workbook rather than a CSV.
 */

import { BookOpen, Download, Search } from "lucide-react";
import * as React from "react";

import { EmptyState, ErrorState, LoadingRows } from "@/components/common/states";
import { InventoryExportDialog } from "@/components/inventory/export-dialog";
import { StatusChip } from "@/components/inventory/stock-status";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardHeader,
  CardTitle,
  Input,
  Label,
} from "@/components/ui/primitives";
import { useStockBook } from "@/hooks/use-api";
import { useAuthStore } from "@/stores/auth";
import { cn, formatCompactCurrency, formatNumber } from "@/lib/utils";
import { isoDaysAgo, todayIso } from "@/lib/utils/dates";
import type { StockBookRow } from "@/types/api";

export default function InventoryBookPage() {
  const [start, setStart] = React.useState(isoDaysAgo(30));
  const [end, setEnd] = React.useState(todayIso());
  const [query, setQuery] = React.useState("");
  const [exporting, setExporting] = React.useState(false);

  const canExport = useAuthStore((s) => s.can("inventory:reports_export"));
  const { data, isLoading, isFetching, error, refetch } = useStockBook({ start, end });

  const rows = data?.data ?? [];
  const showsValue = rows.some((row) => row.value != null);

  const visible = React.useMemo(() => {
    const needle = query.trim().toLowerCase();
    if (!needle) return rows;
    return rows.filter(
      (row) =>
        row.sku.toLowerCase().includes(needle) || row.product.toLowerCase().includes(needle),
    );
  }, [rows, query]);

  const totals = React.useMemo(
    () =>
      visible.reduce(
        (acc, row) => ({
          sales: acc.sales + row.sales,
          purchases: acc.purchases + row.purchases,
          wastage: acc.wastage + row.wastage + row.expired,
          value: acc.value + (row.value ?? 0),
        }),
        { sales: 0, purchases: 0, wastage: 0, value: 0 },
      ),
    [visible],
  );

  const invalidRange = start > end;

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h2 className="text-xl font-semibold tracking-tight">Inventory book</h2>
          <p className="text-sm text-muted-foreground">
            Opening, movements and closing per SKU — derived from the ledger, not stored
          </p>
        </div>
        {canExport && (
          <Button
            variant="outline"
            size="sm"
            className="gap-1.5"
            onClick={() => setExporting(true)}
          >
            <Download className="h-3.5 w-3.5" />
            Export workbook
          </Button>
        )}
      </div>

      <Card>
        <CardContent className="grid gap-3 p-4 sm:grid-cols-3">
          <div className="space-y-1.5">
            <Label htmlFor="book-start">From</Label>
            <Input
              id="book-start"
              type="date"
              value={start}
              max={end}
              onChange={(event) => setStart(event.target.value)}
              className={cn(invalidRange && "border-destructive")}
            />
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="book-end">To</Label>
            <Input
              id="book-end"
              type="date"
              value={end}
              min={start}
              onChange={(event) => setEnd(event.target.value)}
              className={cn(invalidRange && "border-destructive")}
            />
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="book-search">Find a SKU</Label>
            <div className="relative">
              <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
              <Input
                id="book-search"
                value={query}
                onChange={(event) => setQuery(event.target.value)}
                placeholder="SKU or product…"
                className="pl-9"
              />
            </div>
          </div>
          {invalidRange && (
            <p className="text-2xs text-destructive sm:col-span-3">
              The start date is after the end date, so the period is empty.
            </p>
          )}
        </CardContent>
      </Card>

      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <Tile label="SKUs" value={formatNumber(visible.length)} />
        <Tile label="Sold" value={formatNumber(totals.sales)} tone="primary" />
        <Tile label="Received" value={formatNumber(totals.purchases)} tone="success" />
        <Tile
          label={showsValue ? "Closing value" : "Wastage and expiry"}
          value={showsValue ? formatCompactCurrency(totals.value) : formatNumber(totals.wastage)}
          tone={showsValue ? "default" : totals.wastage > 0 ? "warning" : "default"}
        />
      </div>

      <Card>
        <CardHeader className="pb-3">
          <CardTitle className="text-base">
            {data?.meta ? `${String(data.meta.start)} to ${String(data.meta.end)}` : "Period"}
          </CardTitle>
        </CardHeader>
        <CardContent>
          {isLoading && <LoadingRows rows={8} />}
          {error && <ErrorState error={error} onRetry={() => void refetch()} />}

          {!isLoading && !error && visible.length === 0 && (
            <EmptyState
              icon={BookOpen}
              title="Nothing in this period"
              description={
                query
                  ? "No SKU matches that search."
                  : "No stock moved between these dates."
              }
            />
          )}

          {visible.length > 0 && (
            <div className={cn("overflow-x-auto", isFetching && "opacity-60")}>
              <table className="w-full min-w-[820px] text-2xs tabular-nums">
                <thead>
                  <tr className="border-b border-border text-left text-muted-foreground">
                    <th className="pb-2 pr-3 font-medium">SKU</th>
                    <th className="pb-2 pr-3 font-medium">Product</th>
                    <th className="pb-2 pr-3 text-right font-medium">Opening</th>
                    <th className="pb-2 pr-3 text-right font-medium">In</th>
                    <th className="pb-2 pr-3 text-right font-medium">Out</th>
                    <th className="pb-2 pr-3 text-right font-medium">Lost</th>
                    <th className="pb-2 pr-3 text-right font-medium">Closing</th>
                    {showsValue && <th className="pb-2 pr-3 text-right font-medium">Value</th>}
                    <th className="pb-2 font-medium">Status</th>
                  </tr>
                </thead>
                <tbody>
                  {visible.map((row) => (
                    <BookRow key={row.sku} row={row} showsValue={showsValue} />
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </CardContent>
      </Card>

      <InventoryExportDialog
        open={exporting}
        onClose={() => setExporting(false)}
        defaultStart={start}
        defaultEnd={end}
      />
    </div>
  );
}

function BookRow({ row, showsValue }: { row: StockBookRow; showsValue: boolean }) {
  const incoming = row.purchases + row.returns + Math.max(row.transfers, 0);
  const lost = row.wastage + row.expired;
  // Opening plus everything in, minus everything out, should land on closing.
  // When it does not, the row is flagged rather than quietly shown - a book that
  // does not balance is the single most important thing on this page.
  const balances =
    Math.abs(
      row.opening + row.purchases + row.returns + row.transfers + row.adjustments -
        row.sales -
        lost -
        row.closing,
    ) < 0.01;

  return (
    <tr
      className={cn(
        "border-b border-border/60 last:border-0",
        !balances && "bg-destructive/5",
      )}
    >
      <td className="py-2 pr-3 font-mono">{row.sku}</td>
      <td className="py-2 pr-3">
        {row.product}
        {!balances && (
          <span
            className="ml-1.5 font-medium text-destructive"
            title="Opening plus movements does not equal closing"
          >
            does not balance
          </span>
        )}
      </td>
      <td className="py-2 pr-3 text-right">{formatNumber(row.opening)}</td>
      <td className="py-2 pr-3 text-right text-success">
        {incoming > 0 ? `+${formatNumber(incoming)}` : "—"}
      </td>
      <td className="py-2 pr-3 text-right text-primary">
        {row.sales > 0 ? `-${formatNumber(row.sales)}` : "—"}
      </td>
      <td className={cn("py-2 pr-3 text-right", lost > 0 && "text-destructive")}>
        {lost > 0 ? `-${formatNumber(lost)}` : "—"}
      </td>
      <td className="py-2 pr-3 text-right font-semibold">{formatNumber(row.closing)}</td>
      {showsValue && (
        <td className="py-2 pr-3 text-right">
          {row.value != null ? formatCompactCurrency(row.value) : "—"}
        </td>
      )}
      <td className="py-2">
        <StatusChip status={row.status} />
      </td>
    </tr>
  );
}

function Tile({
  label,
  value,
  tone = "default",
}: {
  label: string;
  value: string;
  tone?: "default" | "primary" | "success" | "warning";
}) {
  const toneClass =
    tone === "primary"
      ? "text-primary"
      : tone === "success"
        ? "text-success"
        : tone === "warning"
          ? "text-warning"
          : "";
  return (
    <Card>
      <CardContent className="p-4">
        <p className="text-2xs text-muted-foreground">{label}</p>
        <p className={cn("mt-1 text-lg font-semibold leading-none tabular-nums", toneClass)}>
          {value}
        </p>
      </CardContent>
    </Card>
  );
}
