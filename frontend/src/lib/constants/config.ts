/** Build-time configuration. Nothing secret ever lives here. */

/**
 * Default to the local backend, never to someone's tunnel.
 *
 * A hardcoded ngrok URL here means a fresh clone -- or this machine, whenever
 * the tunnel is down -- silently calls a dead host and reports "could not reach
 * the API". Point `NEXT_PUBLIC_API_URL` at a tunnel in `frontend/.env.local`
 * when you actually want one. Note that Next.js reads env files from
 * `frontend/`, not from the repo root.
 */
export const API_BASE_URL =
  process.env.NEXT_PUBLIC_API_URL?.replace(/\/$/, "") ?? "http://localhost:8000/api/v1";

export const APP_NAME = process.env.NEXT_PUBLIC_APP_NAME ?? "PayPilot";
export const APP_TAGLINE = "An AI Growth Scientist for every merchant.";

export const REQUEST_TIMEOUT_MS = 90_000;

/** Prefilled on the login screen so a reviewer can get in without hunting for credentials. */
export const SAMPLE_CREDENTIALS = {
  email: process.env.NEXT_PUBLIC_DEMO_EMAIL ?? "owner@sharmacafe.in",
  password: process.env.NEXT_PUBLIC_DEMO_PASSWORD ?? "Autopilot@2024",
};

export const VAPI = {
  publicKey: process.env.NEXT_PUBLIC_VAPI_PUBLIC_KEY ?? "",
  assistantId: process.env.NEXT_PUBLIC_VAPI_ASSISTANT_ID ?? "",
};

export const DATE_RANGES = [
  { label: "7 days", value: 7 },
  { label: "14 days", value: 14 },
  { label: "30 days", value: 30 },
  { label: "60 days", value: 60 },
  { label: "90 days", value: 90 },
] as const;

export const DEFAULT_RANGE_DAYS = 30;

export const QUERY_STALE_TIME_MS = 60_000;
