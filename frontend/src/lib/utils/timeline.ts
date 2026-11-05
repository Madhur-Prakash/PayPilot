/**
 * Maps the backend's procurement timeline to Bryntum Gantt task/dependency data.
 *
 * Pure and framework-free so it is unit-tested. The backend computes every date
 * and percentage; this only renames fields, parses ISO strings, and turns the
 * stage state into a CSS class.
 */

import type { ProcurementTimeline, TimelineDependency, TimelineState, TimelineTask } from "@/types/integrations";

export interface GanttTaskData {
  id: string;
  name: string;
  startDate: Date;
  endDate: Date;
  percentDone: number;
  manuallyScheduled: boolean;
  expanded?: boolean;
  cls: string;
  /** The stage's state, for the status pill (the bar colour comes from `cls`). */
  state: TimelineState;
  /** Shown under the stage name and in the tooltip; always rendered as text, never HTML. */
  note: string;
  /** Bryntum's baselines: the planned window, drawn as a thin bar under the actual one. */
  baselines?: { startDate: Date; endDate: Date }[];
  children?: GanttTaskData[];
}

export interface GanttDependencyData {
  id: string;
  from: string;
  to: string;
  type: number;
}

export const STATE_CLASS: Record<TimelineState, string> = {
  done: "pp-task-done",
  active: "pp-task-active",
  pending: "pp-task-pending",
  blocked: "pp-task-blocked",
};

export const STATE_LABEL: Record<TimelineState, string> = {
  done: "Done",
  active: "In progress",
  pending: "Pending",
  blocked: "Blocked",
};

export function toGanttTask(task: TimelineTask): GanttTaskData {
  const state: TimelineState = task.state in STATE_CLASS ? task.state : "pending";
  const mapped: GanttTaskData = {
    id: task.id,
    name: task.name,
    startDate: new Date(task.startDate),
    endDate: new Date(task.endDate),
    percentDone: task.percentDone,
    manuallyScheduled: true,
    cls: STATE_CLASS[state],
    state,
    note: task.detail,
  };
  if (task.expanded !== undefined) mapped.expanded = task.expanded;
  if (task.baseline) {
    mapped.baselines = [{ startDate: new Date(task.baseline.startDate), endDate: new Date(task.baseline.endDate) }];
  }
  if (task.children?.length) mapped.children = task.children.map(toGanttTask);
  return mapped;
}

export function toGanttDependencies(deps: TimelineDependency[]): GanttDependencyData[] {
  return deps.map((d) => ({ id: d.id, from: d.from, to: d.to, type: d.type }));
}

/** A padded visible range covering every task (a day before, three days after). */
export function visibleRange(tasks: GanttTaskData[]): { start: Date; end: Date } {
  const stamps: number[] = [];
  const walk = (list: GanttTaskData[]) => {
    for (const t of list) {
      stamps.push(t.startDate.getTime(), t.endDate.getTime());
      if (t.children) walk(t.children);
    }
  };
  walk(tasks);
  const day = 86_400_000;
  if (!stamps.length) {
    const now = Date.now();
    return { start: new Date(now - 2 * day), end: new Date(now + 14 * day) };
  }
  return { start: new Date(Math.min(...stamps) - day), end: new Date(Math.max(...stamps) + 3 * day) };
}

/** Rows the grid shows with every procurement expanded - sizes the chart to its content. */
export function countRows(tasks: GanttTaskData[]): number {
  return tasks.reduce((n, t) => n + 1 + (t.children && t.expanded !== false ? countRows(t.children) : 0), 0);
}

export function toGantt(timeline: Pick<ProcurementTimeline, "tasks" | "dependencies">) {
  const tasks = timeline.tasks.map(toGanttTask);
  return { tasks, dependencies: toGanttDependencies(timeline.dependencies), range: visibleRange(tasks) };
}
