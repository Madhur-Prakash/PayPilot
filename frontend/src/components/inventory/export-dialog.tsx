"use client";

/**
 * Export the inventory book.
 *
 * Shaped to mirror the import dialog, because the two are the same job in
 * opposite directions and there is no reason for them to feel different: pick
 * what you want, see what you will get, then commit.
 *
 * The download itself goes through the authenticated API client. A plain
 * `<a href="/api/v1/...">` cannot work - the href resolves against the frontend
 * origin instead of the API, and carries no bearer token, so the browser saves
 * the resulting 404 or 401 page as "export.htm".
 */

import { CalendarRange, Check, Download, FileSpreadsheet, TriangleAlert } from "lucide-react";
import * as React from "react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/overlays";
import { Card, CardContent, Input, Label, Separator } from "@/components/ui/primitives";
import { inventoryApi } from "@/lib/api/endpoints";
import { useStockBook } from "@/hooks/use-api";
import { cn, formatNumber } from "@/lib/utils";
import { isoDaysAgo, todayIso } from "@/lib/utils/dates";

/** What each sheet in the workbook holds, so nobody has to open it to find out. */
const SHEETS = [
  { name: "About", detail: "Who exported it, when, and the period covered" },
  { name: "Inventory Summary", detail: "Current position per SKU" },
  { name: "Stock Ledger", detail: "Every movement in the period" },
  { name: "Purchase Orders", detail: "Orders raised, with their status" },
  { name: "PO Lines", detail: "Line detail per order" },
  { name: "Aging", detail: "Stock sitting too long, and expiry" },
  { name: "Vendors", detail: "Suppliers and what they supply" },
];

export function InventoryExportDialog({
  open,
  onClose,
  defaultStart,
  defaultEnd,
}: {
  open: boolean;
  onClose: () => void;
  defaultStart?: string;
  defaultEnd?: string;
}) {
  const [start, setStart] = React.useState(defaultStart ?? isoDaysAgo(30));
  const [end, setEnd] = React.useState(defaultEnd ?? todayIso());
  const [downloading, setDownloading] = React.useState(false);

  React.useEffect(() => {
    if (open) {
      setStart(defaultStart ?? isoDaysAgo(30));
      setEnd(defaultEnd ?? todayIso());
    }
  }, [open, defaultStart, defaultEnd]);

  // Same query the book page uses, so the count shown here is the count exported.
  const { data, isFetching } = useStockBook({ start, end });
  const rows = data?.data ?? [];

  const invalidRange = start > end;

  async function download() {
    setDownloading(true);
    try {
      const filename = await inventoryApi.exportBook({ start, end });
      toast.success("Workbook downloaded", { description: filename });
      onClose();
    } catch (error) {
      toast.error("Could not export the workbook", {
        description: error instanceof Error ? error.message : "Please try again.",
      });
    } finally {
      setDownloading(false);
    }
  }

  return (
    <Dialog open={open} onOpenChange={(next) => !next && onClose()}>
      <DialogContent
        className="max-w-lg"
        // Without this Radix focuses the first field on open and the browser
        // selects the day segment of the date input, which reads as though
        // something has already been chosen.
        onOpenAutoFocus={(event) => event.preventDefault()}
      >
        <DialogHeader>
          <DialogTitle>Export inventory</DialogTitle>
          <DialogDescription>
            Choose the period, check what you are about to get, then export.
          </DialogDescription>
        </DialogHeader>

        {/* Counts, laid out like the import dialog's summary tiles */}
        <div className="grid grid-cols-2 gap-3">
          <Card>
            <CardContent className="p-3 text-center">
              <p className="text-xl font-semibold leading-none tabular-nums">
                {isFetching ? "…" : formatNumber(rows.length)}
              </p>
              <p className="mt-1 text-2xs text-muted-foreground">SKUs in range</p>
            </CardContent>
          </Card>
          <Card>
            <CardContent className="p-3 text-center">
              <p className="text-xl font-semibold leading-none tabular-nums">{SHEETS.length}</p>
              <p className="mt-1 text-2xs text-muted-foreground">Sheets in the workbook</p>
            </CardContent>
          </Card>
        </div>

        <Separator />

        <div className="space-y-3">
          <p className="flex items-center gap-2 text-sm font-semibold">
            <CalendarRange className="h-4 w-4 text-muted-foreground" />
            Period
          </p>
          <div className="grid gap-3 sm:grid-cols-2">
            <div className="space-y-1.5">
              <Label htmlFor="export-start">From</Label>
              <Input
                id="export-start"
                type="date"
                value={start}
                max={end}
                onChange={(event) => setStart(event.target.value)}
                className={cn(invalidRange && "border-destructive")}
              />
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="export-end">To</Label>
              <Input
                id="export-end"
                type="date"
                value={end}
                min={start}
                onChange={(event) => setEnd(event.target.value)}
                className={cn(invalidRange && "border-destructive")}
              />
            </div>
          </div>
          {invalidRange && (
            <p className="flex items-center gap-1.5 text-2xs text-destructive">
              <TriangleAlert className="h-3.5 w-3.5" />
              The start date is after the end date, so the period is empty.
            </p>
          )}
        </div>

        <Separator />

        <div className="space-y-1.5">
          <p className="flex items-center gap-2 text-sm font-semibold">
            <FileSpreadsheet className="h-4 w-4 text-muted-foreground" />
            What you get
          </p>
          <ul className="space-y-1">
            {SHEETS.map((sheet) => (
              <li key={sheet.name} className="flex items-start gap-2 text-2xs">
                <Check className="mt-0.5 h-3 w-3 shrink-0 text-success" />
                <span>
                  <span className="font-medium">{sheet.name}</span>{" "}
                  <span className="text-muted-foreground">— {sheet.detail}</span>
                </span>
              </li>
            ))}
          </ul>
          <p className="pt-1 text-2xs text-muted-foreground">
            Values and costs appear only if your role can see them.
          </p>
        </div>

        <DialogFooter>
          <Button variant="ghost" onClick={onClose}>
            Cancel
          </Button>
          <Button
            className="gap-1.5"
            loading={downloading}
            disabled={invalidRange}
            onClick={() => void download()}
          >
            <Download className="h-4 w-4" />
            Export workbook
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
