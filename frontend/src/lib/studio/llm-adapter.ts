/**
 * AG Studio's LLM adapter, pointed at PayPilot's backend.
 *
 * AG Studio's AI assistant (its agent harness: lead, data, page, planning and widget
 * agents) never talks to a model provider itself - the host supplies an adapter with
 * one method, `executeTurn`. This one posts the turn to
 * `POST /integrations/studio/ai/turn`, where the backend runs it on Groq with the
 * same key and models as PayPilot's other agents. The key stays on the server.
 *
 * The backend answers with a complete response, so the "stream" replays its output
 * items as protocol events once they arrive. Studio reads tool calls from
 * `complete.output`, which is the authoritative list.
 *
 * The agents' tools run in the browser against the dashboard only: they add and
 * configure charts over datasets the backend already computed. They have no way
 * to read the database, call PayPal or change a record.
 */

import type {
  AgAiEvent,
  AgAiOutputItem,
  AgLlmAdapter,
  AgLlmExecuteTurnOptions,
  AgLlmRequest,
  AgLlmResponse,
  AgLlmResponseHandler,
} from "ag-studio";

export type TurnTransport = (body: Record<string, unknown>, signal?: AbortSignal) => Promise<Record<string, unknown>>;

/** Studio's request in the backend's (snake_case) shape. */
export function toTurnBody(request: AgLlmRequest): Record<string, unknown> {
  return {
    input: request.input,
    instructions: request.instructions ?? null,
    tools: request.tools ?? [],
    tool_choice: request.toolChoice ?? null,
    response_format: request.responseFormat,
    model: request.model ?? null,
  };
}

/** The protocol events that describe a finished turn's output items, in order. */
export function eventsFor(output: readonly AgAiOutputItem[]): AgAiEvent[] {
  const events: AgAiEvent[] = [];
  for (const item of output) {
    if (item.type === "reasoning") {
      const text = (item.content ?? []).map((c) => c.text).join("\n") || item.summary.map((s) => s.text).join("\n");
      if (!text) continue;
      events.push({ type: "REASONING_MESSAGE_START", messageId: item.id, role: "reasoning" });
      events.push({ type: "REASONING_MESSAGE_CONTENT", messageId: item.id, delta: text });
      events.push({ type: "REASONING_MESSAGE_END", messageId: item.id });
    } else if (item.type === "message") {
      const text = item.content.map((c) => (c.type === "text" ? c.text : c.refusal)).join("");
      events.push({ type: "TEXT_MESSAGE_START", messageId: item.id, role: "assistant" });
      if (text) events.push({ type: "TEXT_MESSAGE_CONTENT", messageId: item.id, delta: text });
      events.push({ type: "TEXT_MESSAGE_END", messageId: item.id });
    } else if (item.type === "function_call") {
      events.push({ type: "TOOL_CALL_START", toolCallId: item.callId, toolCallName: item.name });
      if (item.arguments) events.push({ type: "TOOL_CALL_ARGS", toolCallId: item.callId, delta: item.arguments });
      events.push({ type: "TOOL_CALL_END", toolCallId: item.callId });
    }
  }
  return events;
}

function failed(code: string, message: string): AgLlmResponse {
  return { id: `failed-${Date.now()}`, createdAt: Date.now(), status: "failed", output: [], error: { code, message } };
}

function describe(error: unknown): { code: string; message: string; cancelled: boolean } {
  const e = error as { name?: string; code?: string; message?: string; status?: number } | undefined;
  const cancelled = e?.name === "CanceledError" || e?.name === "AbortError" || e?.code === "ERR_CANCELED";
  return {
    code: cancelled ? "cancelled" : e?.code ?? "studio_ai_error",
    message: e?.message ?? "The assistant could not answer.",
    cancelled,
  };
}

export function createPayPilotLlmAdapter(transport: TurnTransport): AgLlmAdapter {
  return {
    executeTurn(request: AgLlmRequest, options?: AgLlmExecuteTurnOptions): AgLlmResponseHandler {
      // The turn never rejects: a failure resolves as a `failed` (or `cancelled`) response
      // so Studio can show it in the chat instead of an unhandled rejection.
      const complete: Promise<AgLlmResponse> = transport(toTurnBody(request), options?.signal).then(
        (data) => data as unknown as AgLlmResponse,
        (error: unknown) => {
          const { code, message, cancelled } = describe(error);
          return cancelled
            ? { ...failed(code, message), status: "cancelled" as const }
            : failed(code, message);
        },
      );
      return {
        complete,
        stream: {
          async *[Symbol.asyncIterator]() {
            const response = await complete;
            yield* eventsFor(response.output ?? []);
          },
        },
      };
    },
  };
}
