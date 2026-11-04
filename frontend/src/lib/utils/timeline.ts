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
  /** Shown in the Detail column; Bryntum encodes it, so no HTML is ever interpreted. */
  note: string;
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

export function toGanttTask(task: TimelineTask): GanttTaskData {
  const mapped: GanttTaskData = {
    id: task.id,
    name: task.name,
    startDate: new Date(task.startDate),
    endDate: new Date(task.endDate),
    percentDone: task.percentDone,
    manuallyScheduled: true,
    cls: STATE_CLASS[task.state] ?? STATE_CLASS.pending,
    note: task.detail,
  };
  if (task.expanded !== undefined) mapped.expanded = task.expanded;
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

export function toGantt(timeline: ProcurementTimeline) {
  const tasks = timeline.tasks.map(toGanttTask);
  return { tasks, dependencies: toGanttDependencies(timeline.dependencies), range: visibleRange(tasks) };
}
