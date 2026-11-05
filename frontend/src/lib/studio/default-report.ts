/**
 * The dashboard a merchant sees the first time they open Dashboard Studio.
 *
 * Built from whichever datasets the backend returned (a fresh demo has no
 * procurements yet, and the sandbox may have few PayPal transactions), so every
 * widget points at data that exists. Fields are referenced as `<dataset>.<column>`.
 * The merchant can edit it, ask the AI assistant to change it, or reset to it.
 */

type FieldRef = { id: string; aggregation?: "sum" | "avg" | "min" | "max" | "count" | "countd" };
type Layout = { xTrack: number; yTrack: number; xSpan: number; ySpan: number };
type Widget = { type: string; dataMapping: Record<string, FieldRef[]>; format?: Record<string, unknown> };

export const DEFAULT_PAGE_ID = "paypilot-overview";
const COLUMNS = 12;
/** Pixels per grid row; a 7-row chart is ~280px tall. */
const ROW_HEIGHT = 40;

const f = (source: string, column: string, aggregation?: FieldRef["aggregation"]): FieldRef =>
  aggregation ? { id: `${source}.${column}`, aggregation } : { id: `${source}.${column}` };

const titled = (text: string, subtitle?: string) => ({
  title: { enabled: true, text },
  ...(subtitle ? { subtitle: { enabled: true, text: subtitle } } : {}),
});

/** Candidate widgets, in reading order. Each declares the dataset it needs and its height. */
const CANDIDATES: { source: string; id: string; width: number; height: number; widget: Widget }[] = [
  {
    source: "procurements", id: "kpi-procurement", width: 12, height: 3,
    widget: {
      type: "multi-kpi",
      dataMapping: { values: [f("procurements", "savings", "sum"), f("procurements", "final_landed_total", "sum"), f("procurements", "reference", "countd")] },
      format: titled("Procurement outcomes", "Savings and spend negotiated by the supplier agents"),
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
      format: titled("Gross by category"),
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
    source: "inventory_cover", id: "column-revenue-at-risk", width: 6, height: 7,
    widget: {
      type: "column-chart-grouped",
      dataMapping: { categoryKey: [f("inventory_cover", "product")], valueKey: [f("inventory_cover", "revenue_at_risk", "sum")] },
      format: titled("Revenue at risk", "If the item runs out before stock arrives"),
    },
  },
  {
    source: "procurements", id: "column-savings-supplier", width: 6, height: 7,
    widget: {
      type: "column-chart-grouped",
      dataMapping: { categoryKey: [f("procurements", "supplier")], valueKey: [f("procurements", "savings", "sum")] },
      format: titled("Savings by supplier"),
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

/** Flow-layout the widgets that have data: left to right, wrapping at the grid width. */
export function buildDefaultReport(
  available: readonly string[],
  options: { aiAvailable?: boolean } = {},
): Record<string, unknown> | undefined {
  const have = new Set(available);
  const chosen = CANDIDATES.filter((c) => have.has(c.source));
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
    // Open on the dashboard itself: the editing panels start collapsed (one click
    // reopens them); the AI assistant stays open only when it is available.
    panels: {
      filters: { collapsed: true },
      edit: { collapsed: true },
      data: { collapsed: true },
      ai: { collapsed: !options.aiAvailable },
    },
  };
}
