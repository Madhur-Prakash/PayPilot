import type { AgAiOutputItem, AgLlmRequest } from "ag-studio";
import { describe, expect, it } from "vitest";

import { buildDefaultReport, DEFAULT_PAGE_ID } from "./default-report";
import { createPayPilotLlmAdapter, eventsFor, toTurnBody } from "./llm-adapter";

const request: AgLlmRequest = {
  input: [{ id: "u", kind: "input", type: "message", role: "user", status: "completed", content: [{ type: "text", text: "hi" }] }],
  instructions: "Build dashboards.",
  tools: [{ name: "add_widget", description: "Add", parameters: { type: "object" } }],
  toolChoice: "auto",
  responseFormat: { type: "text" },
};

const output: AgAiOutputItem[] = [
  { id: "r1", kind: "output", type: "reasoning", summary: [], content: [{ type: "text", text: "thinking" }] },
  { id: "m1", kind: "output", type: "message", role: "assistant", status: "completed", content: [{ type: "text", text: "Done.", annotations: [] }] },
  { id: "f1", kind: "output", type: "function_call", callId: "call_1", name: "add_widget", arguments: '{"a":1}' },
];

describe("Studio LLM adapter", () => {
  it("sends the turn in the backend's snake_case shape", () => {
    expect(toTurnBody(request)).toEqual({
      input: request.input,
      instructions: "Build dashboards.",
      tools: request.tools,
      tool_choice: "auto",
      response_format: { type: "text" },
      model: null,
    });
  });

  it("replays output items as protocol events, in order", () => {
    expect(eventsFor(output).map((e) => e.type)).toEqual([
      "REASONING_MESSAGE_START", "REASONING_MESSAGE_CONTENT", "REASONING_MESSAGE_END",
      "TEXT_MESSAGE_START", "TEXT_MESSAGE_CONTENT", "TEXT_MESSAGE_END",
      "TOOL_CALL_START", "TOOL_CALL_ARGS", "TOOL_CALL_END",
    ]);
  });

  it("resolves the backend response as `complete` and streams its events", async () => {
    const adapter = createPayPilotLlmAdapter(async () => ({ id: "x", createdAt: 1, status: "completed", output }));
    const handler = adapter.executeTurn(request);
    const types: string[] = [];
    for await (const event of handler.stream) types.push(event.type);
    const done = await handler.complete;
    expect(done.status).toBe("completed");
    expect(done.output).toHaveLength(3);
    expect(types).toContain("TOOL_CALL_START");
  });

  it("turns a transport failure into a failed response instead of a rejection", async () => {
    const adapter = createPayPilotLlmAdapter(async () => {
      throw Object.assign(new Error("rate limited"), { code: "RATE_LIMITED" });
    });
    const done = await adapter.executeTurn(request).complete;
    expect(done.status).toBe("failed");
    expect(done.error).toEqual({ code: "RATE_LIMITED", message: "rate limited" });
  });

  it("reports a cancelled turn as cancelled", async () => {
    const adapter = createPayPilotLlmAdapter(async () => {
      throw Object.assign(new Error("canceled"), { name: "CanceledError" });
    });
    expect((await adapter.executeTurn(request).complete).status).toBe("cancelled");
  });
});

describe("default Studio report", () => {
  it("is empty when there is no data", () => {
    expect(buildDefaultReport([])).toBeUndefined();
  });

  it("only charts datasets that exist, with dataset-qualified field ids", () => {
    const report = buildDefaultReport(["inventory_cover", "suppliers"]) as {
      pages: { id: string; widgets: Record<string, { dataMapping: Record<string, { id: string }[]> }> }[];
      selectedPageId: string;
    };
    expect(report.selectedPageId).toBe(DEFAULT_PAGE_ID);
    const widgets = report.pages[0].widgets;
    const ids = Object.values(widgets).flatMap((w) => Object.values(w.dataMapping).flat().map((f) => f.id));
    expect(ids.length).toBeGreaterThan(0);
    expect(ids.every((id) => id.startsWith("inventory_cover.") || id.startsWith("suppliers."))).toBe(true);
  });

  it("lays widgets out inside a 12-column grid without overlaps", () => {
    const report = buildDefaultReport(["paypal_transactions", "procurements", "negotiation_offers", "suppliers", "inventory_cover"]) as {
      pages: { widgetLayout: Record<string, { xTrack: number; yTrack: number; xSpan: number; ySpan: number }> }[];
    };
    const boxes = Object.values(report.pages[0].widgetLayout);
    for (const b of boxes) expect(b.xTrack + b.xSpan).toBeLessThanOrEqual(12);
    for (let i = 0; i < boxes.length; i++) {
      for (let j = i + 1; j < boxes.length; j++) {
        const a = boxes[i];
        const b = boxes[j];
        const overlap = a.xTrack < b.xTrack + b.xSpan && a.xTrack + a.xSpan > b.xTrack && a.yTrack < b.yTrack + b.ySpan && a.yTrack + a.ySpan > b.yTrack;
        expect(overlap).toBe(false);
      }
    }
  });

  it("opens the AI panel only when the assistant is available", () => {
    const on = buildDefaultReport(["suppliers"], { aiAvailable: true }) as { panels: Record<string, { collapsed: boolean }> };
    const off = buildDefaultReport(["suppliers"]) as { panels: Record<string, { collapsed: boolean }> };
    expect(on.panels.ai.collapsed).toBe(false);
    expect(off.panels.ai.collapsed).toBe(true);
  });
});
