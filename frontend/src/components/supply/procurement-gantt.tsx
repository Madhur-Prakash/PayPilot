"use client";

/**
 * Procurement timeline on Bryntum Gantt.
 *
 * Loaded client-side only (see the page) because Bryntum touches `window`. The
 * chart is a read-only *view*: every task is `manuallyScheduled`, so Bryntum never
 * reschedules anything and no drag can imply a commitment the backend did not make.
 *
 * Bryntum is used through its trial package, aliased as `@bryntum/gantt`; the trial
 * build is for evaluation (see docs/SPONSORS.md).
 */

import "@bryntum/gantt/gantt.css";
import "@bryntum/gantt/fontawesome/css/fontawesome.css";
import "@bryntum/gantt/fontawesome/css/solid.css";
import "@bryntum/gantt/stockholm-light.css";
import "./procurement-gantt.css";

import { BryntumGantt } from "@bryntum/gantt-react";
import * as React from "react";

import { toGantt } from "@/lib/utils/timeline";
import type { ProcurementTimeline } from "@/types/integrations";

export default function ProcurementGantt({ timeline }: { timeline: ProcurementTimeline }) {
  // Rebuilt only when the data changes - a new `project` object would reload the chart.
  const data = React.useMemo(() => toGantt(timeline), [timeline]);
  const project = React.useMemo(
    () => ({ tasksData: data.tasks, dependenciesData: data.dependencies }),
    [data],
  );

  return (
    <div className="pp-gantt-host" data-testid="procurement-gantt">
      <BryntumGantt
        project={project}
        readOnly
        startDate={data.range.start}
        endDate={data.range.end}
        viewPreset="weekAndDay"
        rowHeight={38}
        barMargin={9}
        columns={[
          { type: "name", field: "name", text: "Stage", width: 270 },
          { type: "percentdone", text: "Done", width: 80 },
          { text: "Detail", field: "note", flex: 1, minWidth: 180 },
        ]}
      />
    </div>
  );
}
