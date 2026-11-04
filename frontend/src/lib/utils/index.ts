import { type ClassValue, clsx } from "clsx";
import { twMerge } from "tailwind-merge";

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}

// --------------------------------------------------------------------------- //
// US dollar + number formatting
// --------------------------------------------------------------------------- //
const USD = new Intl.NumberFormat("en-US", {
  style: "currency",
  currency: "USD",
  maximumFractionDigits: 0,
});

const USD_PRECISE = new Intl.NumberFormat("en-US", {
  style: "currency",
  currency: "USD",
  minimumFractionDigits: 2,
  maximumFractionDigits: 2,
});

const NUMBER = new Intl.NumberFormat("en-US");

/** Accepts numbers or the decimal strings the API sends for money. */
export function toNumber(value: number | string | null | undefined): number | null {
  if (value == null || value === "") return null;
  const n = typeof value === "number" ? value : Number(value);
  return Number.isNaN(n) ? null : n;
}

/** `$1,234` (or `$1,234.56` when precise). */
export function formatCurrency(value: number | string | null | undefined, precise = false): string {
  const n = toNumber(value);
  if (n == null) return "--";
  return precise ? USD_PRECISE.format(n) : USD.format(n);
}

/** Always two decimals - for invoices, offers and payments. */
export function formatMoney(value: number | string | null | undefined): string {
  return formatCurrency(value, true);
}

/** `$24.7K` / `$1.20M` - for dense dashboards. */
export function formatCompactCurrency(value: number | string | null | undefined): string {
  const n = toNumber(value);
  if (n == null) return "--";
  const abs = Math.abs(n);
  if (abs >= 1_000_000) return `$${(n / 1_000_000).toFixed(2)}M`;
  if (abs >= 10_000) return `$${(n / 1_000).toFixed(1)}K`;
  return USD.format(n);
}

export function formatNumber(value: number | string | null | undefined, decimals = 0): string {
  const n = toNumber(value);
  if (n == null) return "--";
  return NUMBER.format(Number(n.toFixed(decimals)));
}

export function formatPercent(value: number | null | undefined, decimals = 1): string {
  if (value == null || Number.isNaN(value)) return "--";
  return `${value.toFixed(decimals)}%`;
}

/** Always signed - a delta without its sign is ambiguous. */
export function formatDelta(value: number | null | undefined, decimals = 1): string {
  if (value == null || Number.isNaN(value)) return "--";
  return `${value >= 0 ? "+" : ""}${value.toFixed(decimals)}%`;
}

export function formatMetricValue(
  value: number | null | undefined,
  unit: string,
  compact = false,
): string {
  if (value == null) return "--";
  switch (unit) {
    case "currency":
      return compact ? formatCompactCurrency(value) : formatCurrency(value);
    case "percent":
      return formatPercent(value);
    case "minutes":
      return `${value.toFixed(1)} min`;
    case "ratio":
      return `${value.toFixed(2)}x`;
    default:
      return formatNumber(value);
  }
}

export function formatDuration(ms: number | null | undefined): string {
  if (ms == null) return "--";
  if (ms < 1000) return `${Math.round(ms)}ms`;
  if (ms < 60_000) return `${(ms / 1000).toFixed(1)}s`;
  return `${Math.floor(ms / 60_000)}m ${Math.round((ms % 60_000) / 1000)}s`;
}

// --------------------------------------------------------------------------- //
// Dates
// --------------------------------------------------------------------------- //
export function formatDate(value: string | Date | null | undefined): string {
  if (!value) return "--";
  const date = typeof value === "string" ? new Date(value) : value;
  return date.toLocaleDateString("en-US", { day: "numeric", month: "short", year: "numeric" });
}

export function formatShortDate(value: string | Date | null | undefined): string {
  if (!value) return "--";
  const date = typeof value === "string" ? new Date(value) : value;
  return date.toLocaleDateString("en-US", { day: "numeric", month: "short" });
}

export function formatDateTime(value: string | Date | null | undefined): string {
  if (!value) return "--";
  const date = typeof value === "string" ? new Date(value) : value;
  return date.toLocaleString("en-US", {
    day: "numeric",
    month: "short",
    hour: "2-digit",
    minute: "2-digit",
  });
}

export function formatRelativeTime(value: string | Date | null | undefined): string {
  if (!value) return "--";
  const date = typeof value === "string" ? new Date(value) : value;
  const seconds = Math.floor((Date.now() - date.getTime()) / 1000);
  if (seconds < 60) return "just now";
  if (seconds < 3600) return `${Math.floor(seconds / 60)}m ago`;
  if (seconds < 86_400) return `${Math.floor(seconds / 3600)}h ago`;
  if (seconds < 604_800) return `${Math.floor(seconds / 86_400)}d ago`;
  return formatShortDate(date);
}

// --------------------------------------------------------------------------- //
// Semantics
// --------------------------------------------------------------------------- //
/**
 * Whether a movement is good news, given which direction is good for that metric.
 * Never assume "up = green": service time and complaint volume go the other way.
 */
export function isImprovement(
  changePct: number | null | undefined,
  direction: "UP_IS_GOOD" | "DOWN_IS_GOOD" | "NEUTRAL" = "UP_IS_GOOD",
): boolean | null {
  if (changePct == null || direction === "NEUTRAL") return null;
  if (Math.abs(changePct) < 0.05) return null;
  return direction === "UP_IS_GOOD" ? changePct > 0 : changePct < 0;
}

export function deltaToneClass(
  changePct: number | null | undefined,
  direction: "UP_IS_GOOD" | "DOWN_IS_GOOD" | "NEUTRAL" = "UP_IS_GOOD",
): string {
  const good = isImprovement(changePct, direction);
  if (good === null) return "text-muted-foreground";
  return good ? "text-success" : "text-destructive";
}

export function titleCase(value: string): string {
  return value
    .replace(/[_-]+/g, " ")
    .toLowerCase()
    .replace(/\b\w/g, (c) => c.toUpperCase());
}

export function initials(name: string): string {
  return name
    .split(/\s+/)
    .slice(0, 2)
    .map((part) => part[0]?.toUpperCase() ?? "")
    .join("");
}

export function truncate(value: string, max = 120): string {
  return value.length <= max ? value : `${value.slice(0, max - 1)}…`;
}

export function clamp(value: number, min: number, max: number): number {
  return Math.min(Math.max(value, min), max);
}
export * from "./dates";
