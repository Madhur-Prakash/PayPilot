import { describe, expect, it } from "vitest";

import type { ProcurementTimeline, TimelineTask } from "@/types/integrations";

import { STATE_CLASS, toGantt, toGanttTask, visibleRange } from "./timeline";

const task = (over: Partial<TimelineTask> = {}): TimelineTask => ({
  id: "t1",
  name: "RFQ & negotiation",
  startDate: "2026-11-02T09:00:00+00:00",
  endDate: "2026-11-02T11:00:00+00:00",
  percentDone: 100,
  manuallyScheduled: true,
  state: "done",
  detail: "6 offers across 3 rounds",
  ...over,
});

describe("toGanttTask", () => {
  it("parses ISO dates, keeps the backend's numbers and maps state to a class", () => {
    const mapped = toGanttTask(task());
    expect(mapped.startDate).toBeInstanceOf(Date);
    expect(mapped.startDate.toISOString()).toBe("2026-11-02T09:00:00.000Z");
    expect(mapped.percentDone).toBe(100);
    expect(mapped.cls).toBe(STATE_CLASS.done);
    expect(mapped.note).toBe("6 offers across 3 rounds");
  });

  it("never lets Bryntum reschedule: every task stays manually scheduled", () => {
    expect(toGanttTask(task({ manuallyScheduled: false })).manuallyScheduled).toBe(true);
  });

  it("maps every state to a distinct class, and an unknown one to pending", () => {
    const classes = (["done", "active", "pending", "blocked"] as const).map((s) => STATE_CLASS[s]);
    expect(new Set(classes).size).toBe(4);
    expect(toGanttTask(task({ state: "weird" as never })).cls).toBe(STATE_CLASS.pending);
  });

  it("turns the backend's planned window into a single Bryntum baseline", () => {
    const planned = toGanttTask(task({ baseline: { startDate: "2026-11-02T09:00:00+00:00", endDate: "2026-11-03T17:00:00+00:00" } }));
    expect(planned.baselines).toHaveLength(1);
    expect(planned.baselines?.[0].endDate.toISOString()).toBe("2026-11-03T17:00:00.000Z");
    // No recorded plan, no baseline - nothing is invented.
    expect(toGanttTask(task({ baseline: null })).baselines).toBeUndefined();
    expect(toGanttTask(task()).baselines).toBeUndefined();
  });

  it("maps children recursively and keeps untrusted text as plain data", () => {
    const parent = task({ id: "p", children: [task({ id: "c", detail: "<img src=x onerror=alert(1)>" })] });
    const mapped = toGanttTask(parent);
    expect(mapped.children?.[0].id).toBe("c");
    // Passed through verbatim as a string: Bryntum encodes column values, and no renderer interprets it.
    expect(mapped.children?.[0].note).toBe("<img src=x onerror=alert(1)>");
  });
});

describe("visibleRange", () => {
  it("pads one day before and three after the real extent, including nested tasks", () => {
    const tree = [toGanttTask(task({ children: [task({ id: "late", endDate: "2026-11-10T00:00:00+00:00" })] }))];
    const { start, end } = visibleRange(tree);
    expect(start.toISOString()).toBe("2026-11-01T09:00:00.000Z");
    expect(end.toISOString()).toBe("2026-11-13T00:00:00.000Z");
  });

  it("falls back to a sensible window when there is nothing to show", () => {
    const { start, end } = visibleRange([]);
    expect(end.getTime()).toBeGreaterThan(start.getTime());
  });
});

describe("toGantt", () => {
  it("returns tasks, dependencies and a range together", () => {
    const timeline: ProcurementTimeline = {
      tasks: [task()],
      dependencies: [{ id: "d1", from: "a", to: "b", type: 2 }],
      generated_at: "2026-11-04T00:00:00+00:00",
      count: 1,
    };
    const out = toGantt(timeline);
    expect(out.tasks).toHaveLength(1);
    expect(out.dependencies).toEqual([{ id: "d1", from: "a", to: "b", type: 2 }]);
    expect(out.range.end.getTime()).toBeGreaterThan(out.range.start.getTime());
  });
});
