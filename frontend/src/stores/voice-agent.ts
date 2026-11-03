"use client";

/**
 * The one live voice call, shared by every page.
 *
 * Mirrors `stores/auth.ts`: a Zustand store for reactive state, plus a module-level
 * external handle (the Vapi call instance, and the router's `push`) installed once
 * by a bridge component - `VoiceNavBridge` - the same way `installUnauthorizedHandler`
 * wires the API client to the auth store without either importing the other.
 *
 * Why this needs to live above any one page: Next's dashboard layout persists
 * across route changes, but a page component does not. Putting call state here
 * (instead of in `/voice`'s local state) is what lets a call started from the
 * floating dock survive navigating to five other pages, and what lets `/voice`
 * itself just be a bigger view onto the same call.
 */

import { create } from "zustand";
import { toast } from "sonner";

import { voiceApi } from "@/lib/api/endpoints";
import { matchVoicePage, resolveVoicePage, voicePageForPath } from "@/lib/constants/voice-pages";
import type { VoicePage } from "@/lib/constants/voice-pages";
import { useAuthStore } from "@/stores/auth";
import type { VoiceSessionConfig } from "@/types/api";

export type VoiceCallState = "idle" | "connecting" | "live" | "ended";

export interface VoiceUtterance {
  role: "assistant" | "user";
  text: string;
  at: string;
}

/** Installed once by `VoiceNavBridge`. `null` before the dashboard layout mounts. */
let navigate: ((href: string) => void) | null = null;
export function installVoiceNavigator(push: (href: string) => void): void {
  navigate = push;
}

/** The live Vapi call object. Kept outside React state, like `vapiRef` was before. */
let vapiInstance: unknown = null;

interface VoiceAgentState {
  config: VoiceSessionConfig | null;
  configLoading: boolean;

  callState: VoiceCallState;
  muted: boolean;
  language: string;
  transcript: VoiceUtterance[];
  agentActions: string[];

  /** Current route, kept in sync by `VoiceNavBridge` so the store can feed context without a hook. */
  pathname: string;
  /** Free-text summaries pages register via `usePageVoiceContext`, keyed by pathname. */
  pageContext: Record<string, string>;
  /** Manually collapsed/expanded by the merchant; defaults to expanded whenever a call goes live. */
  dockExpanded: boolean;

  loadConfig: () => Promise<void>;
  startCall: () => Promise<void>;
  stopCall: () => void;
  toggleMute: () => void;
  setLanguage: (language: string) => void;
  pushTranscript: (line: VoiceUtterance) => void;
  pushAction: (action: string) => void;
  setPathname: (pathname: string) => void;
  setPageContext: (pathname: string, text: string | null) => void;
  setDockExpanded: (expanded: boolean) => void;
}

export const useVoiceAgentStore = create<VoiceAgentState>((set, get) => ({
  config: null,
  configLoading: false,

  callState: "idle",
  muted: false,
  language: "en-IN",
  transcript: [],
  agentActions: [],

  pathname: "/",
  pageContext: {},
  dockExpanded: false,

  loadConfig: async () => {
    if (get().config || get().configLoading) return;
    set({ configLoading: true });
    try {
      const config = await voiceApi.session();
      set({ config });
    } catch {
      // Voice is optional - a failed fetch just leaves the assistant unavailable.
    } finally {
      set({ configLoading: false });
    }
  },

  startCall: async () => {
    const { config, language } = get();
    if (!config?.enabled || !config.public_key || !config.assistant_id) return;
    set({ callState: "connecting", transcript: [], agentActions: [], dockExpanded: true });
    try {
      const { default: Vapi } = await import("@vapi-ai/web");
      const vapi = new Vapi(config.public_key);
      vapiInstance = vapi;

      vapi.on("call-start", () => set({ callState: "live" }));
      vapi.on("call-end", () => {
        set({ callState: "ended" });
        vapiInstance = null;
      });
      vapi.on("error", (error: unknown) => {
        console.error("vapi error", error);
        toast.error("The voice session ended unexpectedly.");
        set({ callState: "ended" });
        vapiInstance = null;
      });
      vapi.on("message", (message: Record<string, unknown>) => handleVapiMessage(message));

      const overrides = {
        ...(config.assistant_overrides as Record<string, unknown>),
        variableValues: {
          ...((config.assistant_overrides as { variableValues?: Record<string, unknown> })
            ?.variableValues ?? {}),
          language,
        },
      };
      await vapi.start(config.assistant_id, overrides as never);
      // The merchant might already be mid-page when the call connects - ground the
      // assistant in what's on screen immediately, not just on the next navigation.
      sendPageContext();
    } catch (error) {
      console.error(error);
      toast.error("Could not start the session. Check your microphone permissions.");
      set({ callState: "idle" });
      vapiInstance = null;
    }
  },

  stopCall: () => {
    const vapi = vapiInstance as { stop?: () => void } | null;
    try {
      vapi?.stop?.();
    } catch {
      /* the SDK may already have torn the call down */
    }
    vapiInstance = null;
    set({ callState: "ended" });
  },

  toggleMute: () => {
    const vapi = vapiInstance as { setMuted?: (muted: boolean) => void } | null;
    const next = !get().muted;
    vapi?.setMuted?.(next);
    set({ muted: next });
  },

  setLanguage: (language) => set({ language }),

  pushTranscript: (line) => set((state) => ({ transcript: [...state.transcript, line] })),
  pushAction: (action) => set((state) => ({ agentActions: [...state.agentActions, action] })),

  setPathname: (pathname) => {
    if (get().pathname === pathname) return;
    set({ pathname });
    sendPageContext();
  },

  setPageContext: (pathname, text) => {
    set((state) => {
      const next = { ...state.pageContext };
      if (text) next[pathname] = text;
      else delete next[pathname];
      return { pageContext: next };
    });
    if (get().pathname === pathname) sendPageContext();
  },

  setDockExpanded: (expanded) => set({ dockExpanded: expanded }),
}));

// --------------------------------------------------------------------------- //
// Message pipeline: transcript capture, tool-call side effects, page-context feed.
// --------------------------------------------------------------------------- //

interface ExtractedToolCall {
  id: string;
  name: string;
  arguments: Record<string, unknown>;
}

/** Normalises a Vapi `tool-calls` message. Mirrors the backend's `parse_tool_calls`. */
function extractToolCalls(message: Record<string, unknown>): ExtractedToolCall[] {
  if (message?.type !== "tool-calls" && message?.type !== "tool-call") return [];

  const raw =
    (message.toolCallList as unknown[]) ??
    (message.toolCalls as unknown[]) ??
    (message.toolCall ? [message.toolCall] : []);

  return raw
    .filter((entry): entry is Record<string, unknown> => typeof entry === "object" && entry !== null)
    .map((entry) => {
      const fn = (entry.function as Record<string, unknown>) ?? {};
      const name = String(entry.name ?? fn.name ?? "");
      const rawArgs = entry.arguments ?? entry.parameters ?? fn.arguments;
      let parsedArgs: Record<string, unknown> = {};
      if (typeof rawArgs === "string") {
        try {
          const parsed: unknown = JSON.parse(rawArgs);
          if (parsed && typeof parsed === "object") parsedArgs = parsed as Record<string, unknown>;
        } catch {
          /* not JSON - leave empty rather than throw mid-call */
        }
      } else if (rawArgs && typeof rawArgs === "object") {
        parsedArgs = rawArgs as Record<string, unknown>;
      }
      return { id: String(entry.id ?? ""), name, arguments: parsedArgs };
    });
}

/**
 * Moves the screen to `page`, if the role allows it and it isn't already there.
 * Shared by both navigation paths below - transcript matching is what actually
 * fires in practice; a `navigate_page` tool call (if the assistant has one
 * configured and chooses to use it) lands here too, so neither path has to
 * duplicate the permission check or the toast/log/context bookkeeping.
 */
function tryNavigateToPage(page: VoicePage, source: "speech" | "tool"): void {
  if (useVoiceAgentStore.getState().pathname === page.href) return; // already there

  const allowed = !page.permission || useAuthStore.getState().can(page.permission);
  if (!allowed) {
    toast.error(`Your role doesn't have access to ${page.label}.`);
    return;
  }
  if (!navigate) return; // the bridge hasn't mounted yet - nothing to navigate with

  navigate(page.href);
  toast.info(`Opening ${page.label}`);
  useVoiceAgentStore.getState().pushAction(
    source === "speech" ? `Heard "${page.label}" — navigated there` : `Navigated to ${page.label}`,
  );
  // `setPathname` (called by the bridge's own effect once the route lands) will
  // send the arrival context too, but that fires a render behind; ping it here
  // so the assistant already knows where it's headed while the page mounts.
  useVoiceAgentStore.setState({ pathname: page.href });
  sendPageContext();
}

function handleVapiMessage(message: Record<string, unknown>): void {
  const { pushTranscript, pushAction } = useVoiceAgentStore.getState();

  if (message?.type === "transcript" && message?.transcriptType === "final") {
    const text = String(message.transcript ?? "");
    const role = message.role === "assistant" ? "assistant" : "user";
    pushTranscript({ role, text, at: new Date().toISOString() });

    // The reliable path: match what the merchant actually said, the instant
    // Vapi finishes transcribing it. This does not wait on - or depend on -
    // the assistant deciding to call a tool, which is why it's the primary
    // mechanism rather than a fallback for the tool-call path below.
    if (role === "user") {
      const page = matchVoicePage(text);
      if (page) tryNavigateToPage(page, "speech");
    }
  }

  if (message?.type === "tool-call-result") {
    pushAction("Tool response received");
  }

  for (const call of extractToolCalls(message)) {
    pushAction(`Calling tool: ${call.name}`);
    if (call.name !== "navigate_page") continue;
    const page = resolveVoicePage(String(call.arguments.page ?? ""));
    if (page) tryNavigateToPage(page, "tool");
  }
}

let contextDebounce: ReturnType<typeof setTimeout> | null = null;

/** Feeds the assistant a line about what's on screen. Debounced: navigation and a
 *  page's own `usePageVoiceContext` effect can both fire in the same tick. */
function sendPageContext(): void {
  if (contextDebounce) clearTimeout(contextDebounce);
  contextDebounce = setTimeout(() => {
    const state = useVoiceAgentStore.getState();
    const vapi = vapiInstance as { send?: (msg: Record<string, unknown>) => void } | null;
    if (state.callState !== "live" || !vapi?.send) return;

    const page = voicePageForPath(state.pathname);
    const custom = state.pageContext[state.pathname];
    const text = custom
      ? `The merchant is on the ${page?.label ?? state.pathname} page. On screen: ${custom}`
      : page
        ? `The merchant just moved to the ${page.label} page — ${page.description}.`
        : `The merchant is on ${state.pathname}.`;

    try {
      vapi.send({ type: "add-message", message: { role: "system", content: text } });
    } catch {
      /* best effort - a context ping must never break the call */
    }
  }, 500);
}
