/** Calendar-date helpers for <input type="date">, in the viewer's own timezone. */

/**
 * Today as `YYYY-MM-DD`, local.
 *
 * Deliberately not `toISOString().slice(0, 10)`: that is UTC, so for a merchant
 * in IST it returns yesterday's date between midnight and 05:30.
 */
export function todayIso(): string {
  return toIso(new Date());
}

/** `YYYY-MM-DD` for a date `days` before today, local. */
export function isoDaysAgo(days: number): string {
  const date = new Date();
  date.setDate(date.getDate() - days);
  return toIso(date);
}

function toIso(date: Date): string {
  const month = String(date.getMonth() + 1).padStart(2, "0");
  const day = String(date.getDate()).padStart(2, "0");
  return `${date.getFullYear()}-${month}-${day}`;
}
