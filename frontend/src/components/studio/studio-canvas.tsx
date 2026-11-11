"use client";

/**
 * AG Studio: drag-and-drop dashboards over PayPilot's computed datasets, with
 * Studio's AI assistant running on PayPilot's own LLM.
 *
 * Studio only groups, filters and charts the rows the backend already computed -
 * it derives no financial figure of its own. A merchant's report layout is kept in
 * this browser (a per-viewer convenience); the data itself always comes fresh from
 * the API and is permission-filtered server-side.
 *
 * First open shows a pre-built dashboard (`buildDefaultReport`) instead of a blank
 * canvas. When the backend reports the assistant available, Studio's agent harness
 * (lead, data, page, planning and widget agents) is attached through an
 * `AgLlmAdapter` that relays each turn to the backend - the model key never reaches
 * the browser, and the agents' tools only touch the dashboard.
 *
 * AG Studio is a commercial product. Without a licence key it runs in evaluation
 * mode (watermark and console warnings); see docs/INTEGRATIONS.md.
 */

import { AgStudioAiModule, AgStudioLicenseManager, createAiHarness } from "ag-studio";
import type { AgAiHarnessSetup, AgStudioApi } from "ag-studio";
import { AgStudio } from "ag-studio-react";
import * as React from "react";

import { integrationsApi } from "@/lib/api/integrations";
import { buildDefaultReport } from "@/lib/studio/default-report";
import { createPayPilotLlmAdapter } from "@/lib/studio/llm-adapter";
import { inferFields } from "@/lib/studio/fields";
import { buildStudioTheme, readTokens } from "@/lib/studio/theme";
import type { StudioRow } from "@/types/integrations";

// v5: the redesigned default dashboard (sales first, AI panel closed). Bumping the key lets
// browsers that saved the old layout open on the new one.
const STORAGE_KEY = "paypilot.studio.report.v5";
const LICENSE_KEY = process.env.NEXT_PUBLIC_AG_STUDIO_LICENSE_KEY;

if (LICENSE_KEY) AgStudioLicenseManager.setLicenseKey(LICENSE_KEY);

const AI_MODULES = [AgStudioAiModule];
const NO_MODULES: (typeof AgStudioAiModule)[] = [];

const PROMPT_STARTERS = [
  { label: "Stockout risk", prompt: "Add a chart of revenue at risk by product, highest first, and a KPI for total revenue at risk." },
  { label: "Supplier scorecard", prompt: "Build a supplier scorecard: reliability and on-time rate by supplier, plus total savings." },
  { label: "Negotiation story", prompt: "Show how each supplier's landed total changed across negotiation rounds." },
  { label: "PayPal trend", prompt: "Chart PayPal gross and net by week and add a KPI row with total gross, fees and net." },
];

function loadState(): unknown {
  try {
    const raw = window.localStorage.getItem(STORAGE_KEY);
    return raw ? JSON.parse(raw) : undefined;
  } catch {
    return undefined; // private mode, blocked storage, or a corrupt value - start fresh
  }
}

function saveState(state: unknown): void {
  try {
    window.localStorage.setItem(STORAGE_KEY, JSON.stringify(state));
  } catch {
    /* storage is a convenience, never a dependency */
  }
}

export function resetStudioReport(): void {
  try {
    window.localStorage.removeItem(STORAGE_KEY);
  } catch {
    /* ignore */
  }
}

/** Studio theme from the app's live tokens; rebuilt when the app toggles light/dark. */
function useStudioTheme() {
  const [dark, setDark] = React.useState(() => document.documentElement.classList.contains("dark"));
  React.useEffect(() => {
    const root = document.documentElement;
    const observer = new MutationObserver(() => setDark(root.classList.contains("dark")));
    observer.observe(root, { attributes: true, attributeFilter: ["class"] });
    return () => observer.disconnect();
  }, []);
  // eslint-disable-next-line react-hooks/exhaustive-deps
  const theme = React.useMemo(() => buildStudioTheme(readTokens()), [dark]);
  return { theme, dark };
}

export default function StudioCanvas({
  datasets,
  mode,
  aiAvailable,
}: {
  datasets: Record<string, StudioRow[]>;
  mode: "edit" | "view";
  aiAvailable: boolean;
}) {
  const { theme, dark } = useStudioTheme();
  const data = React.useMemo(
    () => ({
      sources: Object.entries(datasets)
        .filter(([, rows]) => rows.length > 0)
        .map(([id, rows]) => ({ id, data: rows, fields: inferFields(rows) })),
    }),
    [datasets],
  );
  // `initialState` only seeds a mount. Studio remounts when the app switches light/dark, so
  // read the latest saved layout each time rather than the one from the first mount.
  const initialState = React.useMemo(() => {
    const counts = Object.fromEntries(data.sources.map((s) => [s.id, s.data.length]));
    return loadState() ?? buildDefaultReport(counts) ?? undefined;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [dark]);
  const ai = React.useMemo<AgAiHarnessSetup | undefined>(() => {
    if (!aiAvailable) return undefined;
    const adapter = createPayPilotLlmAdapter(integrationsApi.studioAiTurn);
    // The setup params type `api` as Studio's core API; at runtime it is the full AgStudioApi.
    return ({ api }) =>
      createAiHarness(api as unknown as AgStudioApi, { adapter, primary: "lead", promptStarters: PROMPT_STARTERS });
  }, [aiAvailable]);

  return (
    <div style={{ height: "100%", width: "100%" }} data-testid="ag-studio">
      <AgStudio
        key={dark ? "dark" : "light"}
        // Without an explicit size Studio falls back to its 600px minimum height.
        style={{ height: "100%", width: "100%" }}
        theme={theme}
        data={data}
        mode={mode}
        modules={aiAvailable ? AI_MODULES : NO_MODULES}
        ai={ai}
        // eslint-disable-next-line @typescript-eslint/no-explicit-any
        initialState={initialState as any}
        onStateUpdated={(event) => {
          if (event.durable) saveState(event.state);
        }}
      />
    </div>
  );
}
