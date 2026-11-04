"use client";

/**
 * AG Grid, themed to the PayPilot design system.
 *
 * Used where a dense, sortable, filterable table earns its place: transactions,
 * quote comparison, invoices, receipts, reconciliations. Follows light/dark mode
 * via next-themes, and renders the app's own empty / loading states.
 */

import {
  AllCommunityModule,
  type ColDef,
  colorSchemeDark,
  colorSchemeLight,
  type GetRowIdParams,
  ModuleRegistry,
  type RowClickedEvent,
  themeQuartz,
} from "ag-grid-community";
import { AgGridReact } from "ag-grid-react";
import { useTheme } from "next-themes";
import * as React from "react";

import { LoadingRows } from "@/components/common/states";
import { cn } from "@/lib/utils";

let registered = false;
function ensureModules() {
  if (!registered) {
    ModuleRegistry.registerModules([AllCommunityModule]);
    registered = true;
  }
}

const baseTheme = themeQuartz.withParams({
  fontFamily: "var(--font-sans), ui-sans-serif, system-ui, sans-serif",
  fontSize: 12.5,
  headerFontSize: 11.5,
  headerFontWeight: 600,
  borderRadius: 10,
  wrapperBorderRadius: 12,
  spacing: 6,
  rowBorder: true,
  columnBorder: false,
  accentColor: "hsl(211 100% 42%)",
});

const lightTheme = baseTheme.withPart(colorSchemeLight).withParams({
  backgroundColor: "hsl(0 0% 100%)",
  headerBackgroundColor: "hsl(214 32% 97%)",
  foregroundColor: "hsl(222 32% 12%)",
  borderColor: "hsl(214 28% 89%)",
  oddRowBackgroundColor: "hsl(214 32% 99%)",
});

const darkTheme = baseTheme.withPart(colorSchemeDark).withParams({
  backgroundColor: "hsl(222 30% 11%)",
  headerBackgroundColor: "hsl(222 26% 14%)",
  foregroundColor: "hsl(213 28% 93%)",
  borderColor: "hsl(222 22% 20%)",
  oddRowBackgroundColor: "hsl(222 28% 12%)",
  accentColor: "hsl(211 96% 58%)",
});

export interface DataGridProps<T> {
  rows: T[] | undefined;
  columns: ColDef<T>[];
  loading?: boolean;
  height?: number | "auto";
  getRowId?: (row: T) => string;
  onRowClick?: (row: T) => void;
  emptyMessage?: string;
  className?: string;
  quickFilter?: string;
  pagination?: boolean;
  pageSize?: number;
}

export function DataGrid<T>({
  rows,
  columns,
  loading,
  height = "auto",
  getRowId,
  onRowClick,
  emptyMessage = "Nothing to show yet.",
  className,
  quickFilter,
  pagination = false,
  pageSize = 25,
}: DataGridProps<T>) {
  ensureModules();
  const { resolvedTheme } = useTheme();
  const theme = resolvedTheme === "dark" ? darkTheme : lightTheme;

  const defaultColDef = React.useMemo<ColDef<T>>(
    () => ({ sortable: true, resizable: true, filter: true, minWidth: 90, flex: 1 }),
    [],
  );

  if (loading && !rows) return <LoadingRows rows={5} />;

  return (
    <div className={cn("w-full", className)} style={height === "auto" ? undefined : { height }}>
      <AgGridReact<T>
        theme={theme}
        rowData={rows ?? []}
        columnDefs={columns}
        defaultColDef={defaultColDef}
        domLayout={height === "auto" ? "autoHeight" : "normal"}
        animateRows
        quickFilterText={quickFilter}
        pagination={pagination}
        paginationPageSize={pageSize}
        paginationPageSizeSelector={pagination ? [10, 25, 50, 100] : false}
        getRowId={getRowId ? (params: GetRowIdParams<T>) => getRowId(params.data) : undefined}
        onRowClicked={onRowClick ? (event: RowClickedEvent<T>) => event.data && onRowClick(event.data) : undefined}
        rowClass={onRowClick ? "cursor-pointer" : undefined}
        overlayNoRowsTemplate={`<span class="text-sm text-muted-foreground">${emptyMessage}</span>`}
        suppressCellFocus
      />
    </div>
  );
}

export type { ColDef };
