"use client";

/**
 * The floating Growth Scientist — voice everywhere but `/voice` itself.
 *
 * Mounted once in the dashboard layout, so it survives every navigation. At
 * rest it's a small orb bottom-right. The instant a call connects it docks
 * into a compact panel pinned to the right edge of the screen, out of the way
 * of whatever page the merchant is actually looking at, and stays there while
 * they move between pages — the same call, the same transcript, the whole way.
 * On `/voice` itself this renders nothing; that page is the full-size view of
 * the identical call.
 */

import { AnimatePresence, motion } from "framer-motion";
import { ChevronRight, Loader2, Maximize2, Mic, MicOff, PhoneOff, X } from "lucide-react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import * as React from "react";

import { Badge } from "@/components/ui/primitives";
import { LivePulse } from "@/components/ui/motion";
import { VoiceWaveform } from "@/components/voice/voice-waveform";
import { cn } from "@/lib/utils";
import { useVoiceAgentStore } from "@/stores/voice-agent";

export function VoiceAgentDock() {
  const pathname = usePathname();
  const config = useVoiceAgentStore((s) => s.config);
  const callState = useVoiceAgentStore((s) => s.callState);
  const muted = useVoiceAgentStore((s) => s.muted);
  const transcript = useVoiceAgentStore((s) => s.transcript);
  const dockExpanded = useVoiceAgentStore((s) => s.dockExpanded);
  const pageContext = useVoiceAgentStore((s) => s.pageContext);
  const startCall = useVoiceAgentStore((s) => s.startCall);
  const stopCall = useVoiceAgentStore((s) => s.stopCall);
  const toggleMute = useVoiceAgentStore((s) => s.toggleMute);
  const setDockExpanded = useVoiceAgentStore((s) => s.setDockExpanded);

  // `/voice` is the full-size view onto this same call — don't render a second one.
  if (pathname === "/voice") return null;
  if (!config) return null;

  const expanded = dockExpanded && (callState === "connecting" || callState === "live");
  const listening = callState === "live";
  const hasContextForPage = Boolean(pageContext[pathname]);

  return (
    <>
      {/* Orb: always present when voice is configured, wherever the merchant is. */}
      <AnimatePresence>
        {!expanded && (
          <motion.button
            key="orb"
            type="button"
            initial={{ opacity: 0, scale: 0.7, y: 12 }}
            animate={{ opacity: 1, scale: 1, y: 0 }}
            exit={{ opacity: 0, scale: 0.7, y: 12 }}
            transition={{ type: "spring", stiffness: 380, damping: 28 }}
            onClick={() => (listening || callState === "connecting" ? setDockExpanded(true) : void startCall())}
            aria-label={listening ? "Open voice assistant" : "Talk to the Growth Scientist"}
            disabled={!config.enabled}
            className={cn(
              "fixed bottom-6 right-6 z-[45] flex h-14 w-14 items-center justify-center rounded-full shadow-lg transition-transform focus-ring hover:scale-105",
              "disabled:cursor-not-allowed disabled:opacity-50",
              listening
                ? "bg-primary text-primary-foreground"
                : "bg-card text-primary border border-border",
            )}
            style={
              listening
                ? { boxShadow: "0 0 0 8px hsl(var(--primary) / 0.14), 0 4px 20px hsl(var(--primary) / 0.3)" }
                : { boxShadow: "0 4px 16px hsl(var(--foreground) / 0.12)" }
            }
          >
            {callState === "connecting" ? (
              <Loader2 className="h-5 w-5 animate-spin" />
            ) : (
              <Mic className="h-5 w-5" />
            )}
            {listening && (
              <span className="absolute -top-1 -right-1">
                <LivePulse tone="success" />
              </span>
            )}
          </motion.button>
        )}
      </AnimatePresence>

      {/* Docked panel: right side of the screen, out of the merchant's way. */}
      <AnimatePresence>
        {expanded && (
          <motion.aside
            key="dock"
            initial={{ opacity: 0, x: 24 }}
            animate={{ opacity: 1, x: 0 }}
            exit={{ opacity: 0, x: 24 }}
            transition={{ type: "spring", stiffness: 340, damping: 32 }}
            className="fixed right-4 top-20 z-[45] flex w-80 max-w-[calc(100vw-2rem)] flex-col overflow-hidden rounded-2xl border border-border/60 bg-card shadow-xl"
            style={{ maxHeight: "calc(100vh - 6rem)" }}
          >
            {/* Header */}
            <div className="flex items-center justify-between gap-2 border-b border-border/50 px-3.5 py-2.5">
              <div className="flex items-center gap-2 min-w-0">
                <Badge variant={listening ? "success" : "muted"} className="gap-1.5 shrink-0">
                  {listening && <LivePulse tone="success" />}
                  {listening ? "Live" : "Connecting"}
                </Badge>
                <p className="truncate text-xs font-medium text-muted-foreground">
                  Growth Scientist
                </p>
              </div>
              <div className="flex items-center gap-1 shrink-0">
                <Link
                  href="/voice"
                  aria-label="Open full voice studio"
                  className="rounded-md p-1.5 text-muted-foreground hover:bg-muted hover:text-foreground focus-ring"
                >
                  <Maximize2 className="h-3.5 w-3.5" />
                </Link>
                <button
                  type="button"
                  onClick={() => setDockExpanded(false)}
                  aria-label="Collapse (call stays connected)"
                  className="rounded-md p-1.5 text-muted-foreground hover:bg-muted hover:text-foreground focus-ring"
                >
                  <X className="h-3.5 w-3.5" />
                </button>
              </div>
            </div>

            {/* Waveform + controls */}
            <div className="space-y-2.5 border-b border-border/50 px-3.5 py-3">
              <div
                className="flex items-center justify-center rounded-xl px-2 py-1.5"
                style={{
                  background: listening
                    ? "linear-gradient(135deg, hsl(var(--primary) / 0.08), hsl(260 80% 60% / 0.06))"
                    : "hsl(var(--muted) / 0.4)",
                }}
              >
                <VoiceWaveform live={listening && !muted} bars={36} className="h-12 w-full" />
              </div>
              <div className="flex items-center gap-2">
                <button
                  type="button"
                  onClick={toggleMute}
                  disabled={!listening}
                  className="flex flex-1 items-center justify-center gap-1.5 rounded-lg border border-border py-1.5 text-xs font-medium hover:bg-muted disabled:cursor-not-allowed disabled:opacity-50 focus-ring"
                >
                  {muted ? <MicOff className="h-3.5 w-3.5" /> : <Mic className="h-3.5 w-3.5" />}
                  {muted ? "Unmute" : "Mute"}
                </button>
                <button
                  type="button"
                  onClick={stopCall}
                  className="flex flex-1 items-center justify-center gap-1.5 rounded-lg bg-destructive py-1.5 text-xs font-medium text-destructive-foreground hover:opacity-90 focus-ring"
                >
                  <PhoneOff className="h-3.5 w-3.5" />
                  End
                </button>
              </div>
              {hasContextForPage && (
                <p className="text-2xs text-muted-foreground">
                  Feeding this page’s data to the assistant as you speak.
                </p>
              )}
            </div>

            {/* Mini transcript */}
            <div className="min-h-0 flex-1 space-y-2 overflow-y-auto px-3.5 py-3">
              {transcript.length === 0 && (
                <p className="py-6 text-center text-xs text-muted-foreground">
                  Try “show me inventory” or ask a question — I can answer and move the
                  screen for you.
                </p>
              )}
              {transcript.slice(-6).map((line, index) => (
                <div
                  key={`${line.at}-${index}`}
                  className={cn("flex", line.role === "user" ? "justify-end" : "justify-start")}
                >
                  <p
                    className={cn(
                      "max-w-[85%] rounded-xl px-2.5 py-1.5 text-xs leading-snug",
                      line.role === "user"
                        ? "rounded-br-sm bg-primary text-primary-foreground"
                        : "rounded-tl-sm border border-border bg-muted/40",
                    )}
                  >
                    {line.text}
                  </p>
                </div>
              ))}
            </div>

            <Link
              href="/voice"
              className="flex items-center justify-center gap-1 border-t border-border/50 py-2 text-2xs font-medium text-primary hover:underline"
            >
              Open Voice Studio
              <ChevronRight className="h-3 w-3" />
            </Link>
          </motion.aside>
        )}
      </AnimatePresence>
    </>
  );
}
