/**
 * The dashboard a merchant sees the first time they open Dashboard Studio.
 *
 * Built from whichever datasets the backend returned, so every widget points at data
 * that exists - and a dataset too thin to chart (the sandbox may hold a single PayPal
 * transaction) is left out rather than drawn as one lonely dot. Fields are referenced
 * as `<dataset>.<column>`. The merchant can edit it, ask the AI assistant to change it,
 * or reset to it.
 */

type FieldRef = { id: string; aggregation?: "sum" | "avg" | "min" | "max" | "count" | "countd" };
type Layout = { xTrack: number; yTrack: number; xSpan: number; ySpan: number };
type Widget = { type: string; dataMapping: Record<string, FieldRef[]>; format?: Record<string, unknown> };

export const DEFAULT_PAGE_ID = "paypilot-overview";
const COLUMNS = 12;
/** Pixels per grid row; a 7-row chart is ~280px tall. */
const ROW_HEIGHT = 40;
/** Fewer rows than this and a dataset's charts are skipped. */
const MIN_ROWS: Record<string, number> = { paypal_transactions: 5, sales: 5 };

const f = (source: string, column: string, aggregation?: FieldRef["aggregation"]): FieldRef =>
  aggregation ? { id: `${source}.${column}`, aggregation } : { id: `${source}.${column}` };

const titled = (text: string, subtitle?: string) => ({
  title: { enabled: true, text },
  ...(subtitle ? { subtitle: { enabled: true, text: subtitle } } : {}),
});

/** A multi-KPI lays its measures out side by side, one column each, with dividers. */
const kpiRow = (count: number, text: string, subtitle?: string) => ({
  ...titled(text, subtitle),
  style: {
    columns: count,
    verticalAlign: "center",
    columnSeparator: { enabled: true },
    typography: { fontSize: 24, fontWeight: "bold" },
  },
});

/** Candidate widgets, in reading order. Each declares the dataset it needs and its size. */
const CANDIDATES: { source: string; id: string; width: number; height: number; widget: Widget }[] = [
  {
    source: "sales", id: "kpi-sales", width: 12, height: 4,
    widget: {
      type: "multi-kpi",
      dataMapping: {
        values: [f("sales", "revenue", "sum"), f("sales", "gross_profit", "sum"), f("sales", "orders", "sum"), f("sales", "units", "sum")],
      },
      format: kpiRow(4, "Store performance", "Last 120 days of completed sales"),
    },
  },
  {
    source: "sales", id: "area-revenue-day", width: 8, height: 7,
    widget: {
      type: "area-chart",
      dataMapping: { categoryKey: [f("sales", "date")], valueKey: [f("sales", "revenue", "sum")] },
      format: titled("Revenue by day", "Completed sales, all channels"),
    },
  },
  {
    source: "sales", id: "donut-revenue-daypart", width: 4, height: 7,
    widget: {
      type: "donut-chart",
      dataMapping: { categoryKey: [f("sales", "day_part")], valueKey: [f("sales", "revenue", "sum")] },
      format: titled("Revenue by day part"),
    },
  },
  {
    source: "sales", id: "bar-top-products", width: 6, height: 7,
    widget: {
      type: "bar-chart-grouped",
      dataMapping: { categoryKey: [f("sales", "product")], valueKey: [f("sales", "revenue", "sum")] },
      format: titled("Revenue by product"),
    },
  },
  {
    source: "inventory_cover", id: "bar-revenue-at-risk", width: 6, height: 7,
    widget: {
      type: "bar-chart-grouped",
      dataMapping: { categoryKey: [f("inventory_cover", "product")], valueKey: [f("inventory_cover", "revenue_at_risk", "sum")] },
      format: titled("Revenue at risk", "If an item runs out before stock arrives"),
    },
  },
  {
    source: "procurements", id: "kpi-procurement", width: 12, height: 4,
    widget: {
      type: "multi-kpi",
      dataMapping: { values: [f("procurements", "savings", "sum"), f("procurements", "final_landed_total", "sum"), f("procurements", "reference", "count")] },
      format: kpiRow(3, "Procurement outcomes", "Savings and spend negotiated by the supplier agents"),
    },
  },
  {
    source: "negotiation_offers", id: "line-offers-by-round", width: 6, height: 7,
    widget: {
      type: "line-chart",
      dataMapping: {
        categoryKey: [f("negotiation_offers", "round")],
        valueKey: [f("negotiation_offers", "landed_total", "min")],
        legendKey: [f("negotiation_offers", "supplier")],
      },
      format: titled("Landed total by negotiation round", "Lowest offer per supplier per round"),
    },
  },
  {
    source: "inventory_cover", id: "bar-days-of-cover", width: 6, height: 7,
    widget: {
      type: "bar-chart-grouped",
      dataMapping: { categoryKey: [f("inventory_cover", "product")], valueKey: [f("inventory_cover", "days_of_cover", "avg")] },
      format: titled("Days of cover by product", "Below the lead time is a stockout risk"),
    },
  },
  {
    source: "paypal_transactions", id: "line-paypal-gross", width: 8, height: 7,
    widget: {
      type: "line-chart",
      dataMapping: { categoryKey: [f("paypal_transactions", "date")], valueKey: [f("paypal_transactions", "gross", "sum")] },
      format: titled("PayPal gross by day", "Transaction Search, last 120 days"),
    },
  },
  {
    source: "paypal_transactions", id: "donut-paypal-category", width: 4, height: 7,
    widget: {
      type: "donut-chart",
      dataMapping: { categoryKey: [f("paypal_transactions", "category")], valueKey: [f("paypal_transactions", "gross", "sum")] },
      format: titled("PayPal gross by category"),
    },
  },
  {
    source: "suppliers", id: "grid-suppliers", width: 12, height: 6,
    widget: {
      type: "grid",
      dataMapping: {
        cols: [
          f("suppliers", "supplier"), f("suppliers", "strategy"), f("suppliers", "region"),
          f("suppliers", "reliability"), f("suppliers", "on_time_rate"), f("suppliers", "orders_completed"),
          f("suppliers", "total_savings"),
        ],
      },
      format: titled("Supplier agents", "Reliability updates after every delivery"),
    },
  },
];

/**
 * Flow-layout the widgets that have data: left to right, wrapping at the grid width.
 * `available` is either dataset names or a map of dataset -> row count; with counts,
 * thin datasets (see MIN_ROWS) are skipped.
 */
export function buildDefaultReport(
  available: readonly string[] | Record<string, number>,
): Record<string, unknown> | undefined {
  const counts: Record<string, number> = Array.isArray(available)
    ? Object.fromEntries((available as readonly string[]).map((name) => [name, Number.POSITIVE_INFINITY]))
    : (available as Record<string, number>);
  const usable = (source: string) => (counts[source] ?? 0) >= (MIN_ROWS[source] ?? 1);
  const chosen = CANDIDATES.filter((c) => usable(c.source));
  if (chosen.length === 0) return undefined;

  const widgets: Record<string, Widget> = {};
  const widgetLayout: Record<string, Layout> = {};
  let x = 0;
  let y = 0;
  let rowHeight = 0;
  for (const c of chosen) {
    if (x + c.width > COLUMNS) {
      x = 0;
      y += rowHeight;
      rowHeight = 0;
    }
    widgets[c.id] = c.widget;
    widgetLayout[c.id] = { xTrack: x, yTrack: y, xSpan: c.width, ySpan: c.height };
    x += c.width;
    rowHeight = Math.max(rowHeight, c.height);
  }
  return {
    pages: [{ id: DEFAULT_PAGE_ID, widgets, widgetLayout, layout: { columns: COLUMNS, rowHeight: ROW_HEIGHT } }],
    selectedPageId: DEFAULT_PAGE_ID,
    // Open on the dashboard itself, full width: every panel starts collapsed and is one
    // click away on the canvas edge (or via Edit). That includes the AI assistant.
    panels: {
      filters: { collapsed: true },
      edit: { collapsed: true },
      data: { collapsed: true },
      ai: { collapsed: true },
    },
  };
}
