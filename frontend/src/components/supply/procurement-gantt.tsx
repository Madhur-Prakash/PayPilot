"use client";

/**
 * Procurement timeline on Bryntum Gantt (8.0, Enterprise tier).
 *
 * Loaded client-side only (see the page) because Bryntum touches `window`. The
 * chart is a read-only *view*: every task is `manuallyScheduled`, so Bryntum never
 * reschedules anything and no drag can imply a commitment the backend did not make.
 *
 * Licensing: `NEXT_PUBLIC_BRYNTUM_LICENSE_KEY` is registered below, before the first
 * Gantt is created. Without a key the Enterprise package runs as Bryntum's trial
 * (a Trial badge, then masked once the trial ends) - see docs/SPONSORS.md.
 */

// Order matters: icons, then the structural sheet, then exactly one theme, then ours.
import "@bryntum/core-enterprise/fontawesome/css/fontawesome.css";
import "@bryntum/core-enterprise/fontawesome/css/solid.css";
import "@bryntum/gantt-enterprise/gantt.css";
import "@bryntum/gantt-enterprise/stockholm-light.css";
import "./procurement-gantt.css";

import { BryntumGantt, BryntumGanttProjectModel } from "@bryntum/gantt-react-enterprise";
import * as React from "react";

import { toGantt } from "@/lib/utils/timeline";
import type { ProcurementTimeline } from "@/types/integrations";

// The App Router has no client entry file, so this module - the only one that loads
// Bryntum - registers the key. The wrapper import above has already created the
// `bryntum` global, and this runs once per page load, before any Gantt is created.
const LICENSE_KEY = process.env.NEXT_PUBLIC_BRYNTUM_LICENSE_KEY;
if (LICENSE_KEY) globalThis.bryntum.licenseKey = LICENSE_KEY;

export default function ProcurementGantt({ timeline }: { timeline: ProcurementTimeline }) {
  const data = React.useMemo(() => toGantt(timeline), [timeline]);
  // Data lives on the project component, not inside a `project` prop object. A refetch
  // then syncs the task store by id, keeping expanded rows and scroll position.
  const project = React.useRef<BryntumGanttProjectModel>(null);

  return (
    <div className="pp-gantt-host" data-testid="procurement-gantt">
      <BryntumGanttProjectModel ref={project} tasks={data.tasks} dependencies={data.dependencies} />
      <BryntumGantt
        project={project}
        readOnly
        // Bryntum's default "Project start" line would mislabel a history chart.
        projectLinesFeature={false}
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
