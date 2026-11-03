import { type ClassValue, clsx } from "clsx";
import { twMerge } from "tailwind-merge";

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}

// --------------------------------------------------------------------------- //
// Indian currency + number formatting
// --------------------------------------------------------------------------- //
const INR = new Intl.NumberFormat("en-IN", {
  style: "currency",
  currency: "INR",
  maximumFractionDigits: 0,
});

const INR_PRECISE = new Intl.NumberFormat("en-IN", {
  style: "currency",
  currency: "INR",
  maximumFractionDigits: 2,
});

const NUMBER = new Intl.NumberFormat("en-IN");

/** `₹1,23,456` - Indian digit grouping, which en-US would get wrong. */
export function formatCurrency(value: number | null | undefined, precise = false): string {
  if (value == null || Number.isNaN(value)) return "--";
  return precise ? INR_PRECISE.format(value) : INR.format(value);
}

/** `₹4.94L` / `₹1.2Cr` - the scale Indian merchants actually read. */
export function formatCompactCurrency(value: number | null | undefined): string {
  if (value == null || Number.isNaN(value)) return "--";
  const abs = Math.abs(value);
  if (abs >= 1_00_00_000) return `₹${(value / 1_00_00_000).toFixed(2)}Cr`;
  if (abs >= 1_00_000) return `₹${(value / 1_00_000).toFixed(2)}L`;
  if (abs >= 1_000) return `₹${(value / 1_000).toFixed(1)}K`;
  return INR.format(value);
}

export function formatNumber(value: number | null | undefined, decimals = 0): string {
  if (value == null || Number.isNaN(value)) return "--";
  return NUMBER.format(Number(value.toFixed(decimals)));
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
  return date.toLocaleDateString("en-IN", { day: "numeric", month: "short", year: "numeric" });
}

export function formatShortDate(value: string | Date | null | undefined): string {
  if (!value) return "--";
  const date = typeof value === "string" ? new Date(value) : value;
  return date.toLocaleDateString("en-IN", { day: "numeric", month: "short" });
}

export function formatDateTime(value: string | Date | null | undefined): string {
  if (!value) return "--";
  const date = typeof value === "string" ? new Date(value) : value;
  return date.toLocaleString("en-IN", {
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
