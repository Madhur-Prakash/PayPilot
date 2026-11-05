import { readFileSync } from "node:fs";
import { resolve } from "node:path";

import type { NextConfig } from "next";

/**
 * One environment file for the whole project.
 *
 * Next.js only reads `.env*` from the app directory, but this repo keeps a single
 * `.env` at the root that the FastAPI backend reads too. So we parse it here and
 * seed `process.env` before the build, which is early enough for Next to inline
 * the `NEXT_PUBLIC_*` values as it normally would.
 *
 * A real environment variable always wins, so CI, Docker and `vercel env` keep
 * working without touching the file.
 */
function loadRootEnv(): Record<string, string> {
  const values: Record<string, string> = {};
  let raw: string;
  try {
    raw = readFileSync(resolve(process.cwd(), "..", ".env"), "utf8");
  } catch {
    return values; // no root .env (CI, container) - real env vars carry it
  }

  for (const line of raw.split(/\r?\n/)) {
    const trimmed = line.trim();
    if (!trimmed || trimmed.startsWith("#")) continue;

    const eq = trimmed.indexOf("=");
    if (eq === -1) continue;

    const key = trimmed.slice(0, eq).trim();
    let value = trimmed.slice(eq + 1).trim();

    // Strip surrounding quotes, then a trailing `# comment` on unquoted values.
    const quoted = /^(['"])(.*)\1$/.exec(value);
    if (quoted) {
      value = quoted[2];
    } else {
      const hash = value.indexOf(" #");
      if (hash !== -1) value = value.slice(0, hash).trim();
    }

    values[key] = value;
    if (process.env[key] === undefined) process.env[key] = value;
  }
  return values;
}

const rootEnv = loadRootEnv();

/** Read from the real environment first, then the root file, then a default. */
const pick = (key: string, fallback = "") =>
  process.env[key] ?? rootEnv[key] ?? fallback;

const nextConfig: NextConfig = {
  reactStrictMode: true,
  poweredByHeader: false,
  eslint: { ignoreDuringBuilds: true },
  env: {
    NEXT_PUBLIC_API_URL: pick(
      "NEXT_PUBLIC_API_URL",
      "https://wordier-unconfiding-margrett.ngrok-free.dev/api/v1",
    ),
    NEXT_PUBLIC_APP_NAME: pick("NEXT_PUBLIC_APP_NAME", "PayPilot"),
    NEXT_PUBLIC_VAPI_PUBLIC_KEY: pick("NEXT_PUBLIC_VAPI_PUBLIC_KEY"),
    NEXT_PUBLIC_VAPI_ASSISTANT_ID: pick("NEXT_PUBLIC_VAPI_ASSISTANT_ID"),
    NEXT_PUBLIC_DEMO_EMAIL: pick("NEXT_PUBLIC_DEMO_EMAIL"),
    NEXT_PUBLIC_DEMO_PASSWORD: pick("NEXT_PUBLIC_DEMO_PASSWORD"),
    // Bryntum Gantt licence key. Shipped to the browser by design (Bryntum checks it
    // client-side); blank runs the Enterprise package as Bryntum's trial.
    NEXT_PUBLIC_BRYNTUM_LICENSE_KEY: pick("NEXT_PUBLIC_BRYNTUM_LICENSE_KEY"),
  },
};

export default nextConfig;
