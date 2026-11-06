/**
 * Field definitions for Studio's data sources, derived from the rows themselves.
 *
 * Left to infer, Studio shows `gross_profit` as a bare number in the reader's locale
 * (122582.65, or 1,22,582.65 on an Indian machine). Declaring each field gives it a
 * readable name and the right format: money as US dollars (whole dollars for totals,
 * cents for unit prices), counts as integers, ISO dates as dates.
 */

import type { AgFieldDefinition } from "ag-studio";

import type { StudioRow } from "@/types/integrations";

/** Totals: shown in whole dollars. */
const MONEY_TOTAL = new Set([
  "revenue", "gross_profit", "gross", "fee", "net", "max_budget", "baseline_landed_total",
  "final_landed_total", "savings", "landed_total", "total_savings", "revenue_at_risk",
]);
/** Unit prices: shown with cents. */
const MONEY_UNIT = new Set(["unit_price", "unit_cost", "selling_price"]);

const USD_WHOLE = new Intl.NumberFormat("en-US", { style: "currency", currency: "USD", maximumFractionDigits: 0 });
const USD = new Intl.NumberFormat("en-US", { style: "currency", currency: "USD", minimumFractionDigits: 2 });
const INTEGER = new Intl.NumberFormat("en-US", { maximumFractionDigits: 0 });
const DECIMAL = new Intl.NumberFormat("en-US", { maximumFractionDigits: 2 });
const SHORT_DATE = new Intl.DateTimeFormat("en-US", { month: "short", day: "numeric", year: "numeric" });

const ISO_DATE = /^\d{4}-\d{2}-\d{2}$/;

/** Columns whose plain name would read oddly in a chart or KPI. */
const NAMES: Record<string, string> = {
  reference: "Procurements",
  final_landed_total: "Spend (landed)",
  baseline_landed_total: "Opening quote (landed)",
};

/** `gross_profit` -> `Gross profit`; `on_time_rate` -> `On time rate`. */
export function humanize(key: string): string {
  if (NAMES[key]) return NAMES[key];
  const text = key.replace(/_/g, " ").trim();
  return text.charAt(0).toUpperCase() + text.slice(1);
}

type FieldDefinition = {
  id: string;
  name: string;
  format: string;
  formatOptions?: { format: Intl.NumberFormat | Intl.DateTimeFormat };
  accessor?: (row: StudioRow) => unknown;
};

/** One definition per column seen in the rows (first non-null value decides the type). */
export function inferFields(rows: StudioRow[]): AgFieldDefinition[] {
  return infer(rows) as unknown as AgFieldDefinition[];
}

function infer(rows: StudioRow[]): FieldDefinition[] {
  const keys = new Set<string>();
  for (const row of rows.slice(0, 50)) Object.keys(row).forEach((k) => keys.add(k));
  return [...keys].map((id) => {
    const sample = rows.find((r) => r[id] !== null && r[id] !== undefined)?.[id];
    const name = humanize(id);
    if (typeof sample === "number") {
      if (MONEY_TOTAL.has(id)) return { id, name, format: "currencyFormat", formatOptions: { format: USD_WHOLE } };
      if (MONEY_UNIT.has(id)) return { id, name, format: "currencyFormat", formatOptions: { format: USD } };
      const whole = rows.every((r) => r[id] === null || r[id] === undefined || Number.isInteger(r[id]));
      return whole
        ? { id, name, format: "integerFormat", formatOptions: { format: INTEGER } }
        : { id, name, format: "decimalFormat", formatOptions: { format: DECIMAL } };
    }
    if (typeof sample === "boolean") return { id, name, format: "booleanFormat" };
    if (typeof sample === "string" && ISO_DATE.test(sample)) {
      return {
        id, name, format: "dateFormat", formatOptions: { format: SHORT_DATE },
        // Midday local time, so no timezone ever shifts the calendar day.
        accessor: (row: StudioRow) => (typeof row[id] === "string" ? new Date(`${row[id]}T12:00:00`) : null),
      };
    }
    return { id, name, format: "textFormat" };
  });
}
