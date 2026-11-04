"use client";

/** AG Studio - merchants build their own dashboards over PayPilot's computed datasets. */

import { LayoutDashboard, Pencil, RotateCcw, ScanEye } from "lucide-react";
import dynamic from "next/dynamic";
import * as React from "react";

import { EmptyState, ErrorState, LoadingCard } from "@/components/common/states";
import { resetStudioReport } from "@/components/studio/studio-canvas";
import { PageHeader } from "@/components/supply/shared";
import { Button } from "@/components/ui/button";
import { Badge, Card, CardContent } from "@/components/ui/primitives";
import { useStudioDatasets } from "@/hooks/use-integrations";
import { formatRelativeTime } from "@/lib/utils";

// AG Studio measures its parent and touches the DOM, so it renders on the client only.
const StudioCanvas = dynamic(() => import("@/components/studio/studio-canvas"), {
  ssr: false,
  loading: () => <LoadingCard lines={8} />,
});

export default function StudioPage() {
  const datasets = useStudioDatasets();
  const [mode, setMode] = React.useState<"edit" | "view">("edit");
  // Remounting is how a saved layout is dropped: Studio reads `initialState` once.
  const [generation, setGeneration] = React.useState(0);

  const usable = Object.fromEntries(Object.entries(datasets.data?.datasets ?? {}).filter(([, rows]) => rows.length > 0));
  const names = Object.keys(usable);

  return (
    <div className="space-y-5">
      <PageHeader eyebrow="Command" title="Dashboard studio"
        description="Build your own dashboards by dragging fields onto a canvas - revenue by day, savings by supplier, cover by product. The numbers are the ones PayPilot already computed; Studio only groups and charts them."
        actions={
          <>
            <Button size="sm" variant={mode === "edit" ? "default" : "outline"} className="gap-1.5" onClick={() => setMode("edit")}>
              <Pencil className="h-3.5 w-3.5" /> Edit
            </Button>
            <Button size="sm" variant={mode === "view" ? "default" : "outline"} className="gap-1.5" onClick={() => setMode("view")}>
              <ScanEye className="h-3.5 w-3.5" /> View
            </Button>
            <Button size="sm" variant="ghost" className="gap-1.5"
              onClick={() => { resetStudioReport(); setGeneration((g) => g + 1); }}>
              <RotateCcw className="h-3.5 w-3.5" /> Reset layout
            </Button>
          </>
        } />

      {datasets.error && <ErrorState error={datasets.error} onRetry={() => void datasets.refetch()} />}
      {datasets.isLoading && <LoadingCard lines={8} />}

      {datasets.data && names.length === 0 && (
        <EmptyState icon={LayoutDashboard} title="No data to chart yet"
          description="Sync PayPal transactions or start a procurement, then come back." />
      )}

      {datasets.data && names.length > 0 && (
        <>
          <div className="flex flex-wrap items-center gap-1.5 text-xs text-muted-foreground">
            <span>Data sources:</span>
            {names.map((n) => (
              <Badge key={n} variant="outline" className="text-2xs">
                {datasets.data!.labels[n] ?? n} · {usable[n].length}
              </Badge>
            ))}
            <span className="ml-auto">refreshed {formatRelativeTime(datasets.data.generated_at)} · layout saved in this browser</span>
          </div>
          <Card>
            <CardContent className="p-0">
              <div className="h-[calc(100vh-17rem)] min-h-[520px] overflow-hidden rounded-xl">
                <StudioCanvas key={generation} datasets={usable} mode={mode} />
              </div>
            </CardContent>
          </Card>
          <p className="text-2xs text-muted-foreground">{datasets.data.note}</p>
        </>
      )}
    </div>
  );
}
