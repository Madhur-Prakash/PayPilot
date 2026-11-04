"use client";

/**
 * AG Studio: drag-and-drop dashboards over PayPilot's computed datasets.
 *
 * Studio only groups, filters and charts the rows the backend already computed -
 * it derives no financial figure of its own. A merchant's report layout is kept in
 * this browser (a per-viewer convenience); the data itself always comes fresh from
 * the API and is permission-filtered server-side.
 *
 * AG Studio is a commercial product. Without a licence key it runs in evaluation
 * mode (watermark and console warnings); see docs/SPONSORS.md.
 */

import { AgStudio } from "ag-studio-react";
import * as React from "react";

import type { StudioRow } from "@/types/integrations";

const STORAGE_KEY = "paypilot.studio.report.v1";

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

export default function StudioCanvas({
  datasets,
  mode,
}: {
  datasets: Record<string, StudioRow[]>;
  mode: "edit" | "view";
}) {
  const data = React.useMemo(
    () => ({
      sources: Object.entries(datasets)
        .filter(([, rows]) => rows.length > 0)
        .map(([id, rows]) => ({ id, data: rows })),
    }),
    [datasets],
  );
  // Read once: `initialState` only seeds the first render.
  const initialState = React.useRef<unknown>(undefined);
  if (initialState.current === undefined) initialState.current = loadState() ?? null;

  return (
    <div style={{ height: "100%", width: "100%" }} data-testid="ag-studio">
      <AgStudio
        data={data}
        mode={mode}
        // eslint-disable-next-line @typescript-eslint/no-explicit-any
        initialState={(initialState.current ?? undefined) as any}
        onStateUpdated={(event) => {
          if (event.durable) saveState(event.state);
        }}
      />
    </div>
  );
}
