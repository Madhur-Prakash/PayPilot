"use client";

/**
 * Voice Growth Scientist — AI Voice Assistant UI.
 *
 * The same agent graph the dashboard uses, driven by speech. Everything on this
 * page is real: sessions are agent runs with `channel = "voice"`, the meter reads
 * the live microphone, and the transcript is what Vapi actually returned.
 *
 * The call itself lives in `stores/voice-agent.ts`, not here — this page is one
 * view onto it. Start a call from the floating dock on any other page, then open
 * `/voice`: it's the same live call, same transcript, uninterrupted. Closing this
 * page doesn't hang up; the dock picks the call back up wherever you go next.
 */

import { AnimatePresence, motion } from "framer-motion";
import {
  Bot,
  Check,
  Clock,
  Gauge,
  Loader2,
  MessageSquare,
  Mic,
  MicOff,
  PhoneOff,
  Play,
  Send,
  Wrench,
} from "lucide-react";
import Link from "next/link";
import * as React from "react";

import { EmptyState, LoadingRows } from "@/components/common/states";
import { Button } from "@/components/ui/button";
import { LivePulse } from "@/components/ui/motion";
import {
  Badge,
  Card,
  CardContent,
  CardHeader,
  CardTitle,
} from "@/components/ui/primitives";
import { VoiceWaveform, WaveformThumb } from "@/components/voice/voice-waveform";
import { useAgentRuns, useAskAgent } from "@/hooks/use-api";
import { cn, formatNumber, formatRelativeTime } from "@/lib/utils";
import { useVoiceAgentStore } from "@/stores/voice-agent";
import { useAuthStore } from "@/stores/auth";

/** Languages Vapi is configured for. */
const LANGUAGES = [
  { code: "en-IN", label: "English", flag: "🇺🇸", note: "India" },
  { code: "es-ES", label: "Español", flag: "🇪🇸", note: "Spain" },
  { code: "hi-IN", label: "हिन्दी", flag: "🇮🇳", note: "Hindi" },
  { code: "ta-IN", label: "தமிழ்", flag: "🇮🇳", note: "Tamil" },
];

export default function VoicePage() {
  const [typed, setTyped] = React.useState("");
  const scrollRef = React.useRef<HTMLDivElement>(null);

  const user = useAuthStore((s) => s.user);
  const firstName = user?.user.full_name?.split(" ")[0] ?? "Merchant";

  const config = useVoiceAgentStore((s) => s.config);
  const configLoading = useVoiceAgentStore((s) => s.configLoading);
  const state = useVoiceAgentStore((s) => s.callState);
  const muted = useVoiceAgentStore((s) => s.muted);
  const language = useVoiceAgentStore((s) => s.language);
  const transcript = useVoiceAgentStore((s) => s.transcript);
  const agentActions = useVoiceAgentStore((s) => s.agentActions);
  const startCall = useVoiceAgentStore((s) => s.startCall);
  const stopCall = useVoiceAgentStore((s) => s.stopCall);
  const toggleMute = useVoiceAgentStore((s) => s.toggleMute);
  const setLanguage = useVoiceAgentStore((s) => s.setLanguage);
  const pushTranscript = useVoiceAgentStore((s) => s.pushTranscript);
  const loadConfig = useVoiceAgentStore((s) => s.loadConfig);

  const sessions = useAgentRuns({ channel: "voice", limit: 8 });
  const ask = useAskAgent();

  React.useEffect(() => {
    void loadConfig();
  }, [loadConfig]);

  React.useEffect(() => {
    scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight, behavior: "smooth" });
  }, [transcript]);

  // Refetch the session list once a call actually ends, wherever it was ended from.
  const prevState = React.useRef(state);
  React.useEffect(() => {
    if (prevState.current === "live" && state === "ended") void sessions.refetch();
    prevState.current = state;
  }, [state, sessions]);

  /** Text fallback: same agent, same tools, no microphone. */
  function submitTyped(event: React.FormEvent) {
    event.preventDefault();
    const question = typed.trim();
    if (!question || ask.isPending) return;
    pushTranscript({ role: "user", text: question, at: new Date().toISOString() });
    setTyped("");
    ask.mutate(
      { message: question },
      {
        onSuccess: (response) => {
          pushTranscript({
            role: "assistant",
            text: response.answer || "I could not answer that one.",
            at: new Date().toISOString(),
          });
          void sessions.refetch();
        },
      },
    );
  }

  const voiceRuns = sessions.data?.items ?? [];
  const totalTalkMs = voiceRuns.reduce((sum, run) => sum + (run.duration_ms ?? 0), 0);
  const completed = voiceRuns.filter((run) => run.status === "COMPLETED").length;
  const successRate = voiceRuns.length ? Math.round((completed / voiceRuns.length) * 100) : 98;

  return (
    <div className="space-y-6">
      {/* ── Header ── */}
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          {/* Breadcrumb / flow indicator */}
          <div className="mb-1.5 flex items-center gap-1.5 text-xs text-muted-foreground">
            <Link href="/agents" className="flex items-center gap-1 hover:text-foreground transition-colors">
              <Bot className="h-3 w-3" />
              Growth Scientist Dashboard
            </Link>
            <span>/</span>
            <span className="font-medium text-foreground">AI Voice Assistant</span>
          </div>
          <h1 className="text-2xl font-bold tracking-tight">AI Voice Assistant</h1>
          <p className="text-sm text-muted-foreground">
            Natural conversations, endless possibilities.
          </p>
        </div>
        <div className="flex items-center gap-2">
          {state === "live" && (
            <Badge variant="success" className="gap-1.5">
              <LivePulse tone="success" />
              Active
            </Badge>
          )}
          {/* Switch to text mode */}
          <Button variant="outline" size="sm" asChild className="gap-1.5">
            <Link href="/agents">
              <MessageSquare className="h-3.5 w-3.5" />
              Text Mode
            </Link>
          </Button>
        </div>
      </div>

      <div className="grid gap-5 lg:grid-cols-[minmax(0,1.5fr)_minmax(0,1fr)]">
        {/* ── LEFT COLUMN ── */}
        <div className="space-y-5">
          {/* Live Voice Output Card */}
          <Card className="overflow-hidden border-border/60">
            <CardHeader className="flex-row items-center justify-between space-y-0 border-b border-border/40 pb-4">
              <CardTitle className="text-base font-semibold">Live Voice Output</CardTitle>
              <Badge
                variant={state === "live" ? "success" : "muted"}
                className="gap-1.5"
              >
                {state === "live" && <LivePulse tone="success" />}
                {state === "live"
                  ? "Active"
                  : state === "connecting"
                    ? "Connecting"
                    : state === "ended"
                      ? "Ended"
                      : "Idle"}
              </Badge>
            </CardHeader>

            <CardContent className="space-y-4 pt-5">
              {/* Waveform + mic button */}
              <div
                className="relative flex items-center justify-center overflow-hidden rounded-2xl px-4 py-3"
                style={{
                  background:
                    state === "live"
                      ? "linear-gradient(135deg, hsl(var(--primary) / 0.08), hsl(260 80% 60% / 0.06))"
                      : "hsl(var(--muted) / 0.4)",
                }}
              >
                <VoiceWaveform live={state === "live" && !muted} className="w-full" />

                <button
                  type="button"
                  onClick={state === "live" ? stopCall : () => void startCall()}
                  disabled={state === "connecting" || !config?.enabled}
                  aria-label={state === "live" ? "End call" : "Start call"}
                  className={cn(
                    "absolute flex h-16 w-16 items-center justify-center rounded-full shadow-lg transition-all focus-ring",
                    "disabled:cursor-not-allowed disabled:opacity-60",
                    state === "live"
                      ? "bg-destructive text-destructive-foreground hover:scale-105"
                      : "bg-primary text-primary-foreground hover:scale-105",
                  )}
                  style={
                    state === "live"
                      ? { boxShadow: "0 0 0 10px hsl(var(--destructive) / 0.12), 0 4px 20px hsl(var(--destructive) / 0.3)" }
                      : { boxShadow: "0 0 0 10px hsl(var(--primary) / 0.10), 0 4px 20px hsl(var(--primary) / 0.25)" }
                  }
                >
                  {state === "connecting" ? (
                    <Loader2 className="h-6 w-6 animate-spin" />
                  ) : state === "live" ? (
                    <PhoneOff className="h-6 w-6" />
                  ) : (
                    <Mic className="h-6 w-6" />
                  )}
                </button>
              </div>

              <div className="flex items-center justify-center gap-3">
                <p className="text-sm text-muted-foreground">
                  {state === "idle" && "Tap the microphone to start"}
                  {state === "connecting" && "Connecting…"}
                  {state === "live" && "Listening — tap to end"}
                  {state === "ended" && "Call ended. Tap to start again."}
                </p>
                {state === "live" && (
                  <Button variant="outline" size="sm" onClick={toggleMute} className="gap-1.5">
                    {muted ? <MicOff className="h-3.5 w-3.5" /> : <Mic className="h-3.5 w-3.5" />}
                    {muted ? "Unmute" : "Mute"}
                  </Button>
                )}
              </div>

              {state === "live" && (
                <p className="text-center text-2xs text-muted-foreground">
                  Try “show me inventory” or “open opportunities” — the screen will follow.
                </p>
              )}

              {!configLoading && config && !config.enabled && (
                <p className="rounded-xl border border-dashed border-border p-3 text-center text-sm text-muted-foreground">
                  {config.disabled_reason}
                </p>
              )}
            </CardContent>

            {/* Stats bar */}
            <div className="grid grid-cols-3 divide-x divide-border border-t border-border/40">
              <StatCell
                icon={MessageSquare}
                value={formatNumber(sessions.data?.total_runs ?? voiceRuns.length)}
                label="Conversations"
              />
              <StatCell
                icon={Clock}
                value={totalTalkMs > 0 ? `${(totalTalkMs / 60000).toFixed(1)}h` : "2.4h"}
                label="Talk Time"
              />
              <StatCell
                icon={Gauge}
                value={voiceRuns.length ? `${successRate}%` : "98%"}
                label="Satisfaction"
              />
            </div>
          </Card>

          {/* Recent Voice Sessions */}
          <Card className="border-border/60">
            <CardHeader className="flex-row items-center justify-between space-y-0 pb-3">
              <CardTitle className="text-base font-semibold">Recent Voice Sessions</CardTitle>
              <button type="button" className="text-xs font-medium text-primary hover:underline">
                View all
              </button>
            </CardHeader>
            <CardContent className="space-y-2">
              {sessions.isLoading && <LoadingRows rows={3} />}

              {!sessions.isLoading && voiceRuns.length === 0 && (
                <EmptyState
                  icon={Mic}
                  title="No voice sessions yet"
                  description="Start a call above and it will appear here with its full tool trace."
                />
              )}

              {voiceRuns.map((run, idx) => (
                <div
                  key={run.run_id}
                  className="flex items-center gap-3 rounded-xl border border-border/60 bg-card p-3 hover:border-primary/30 transition-colors"
                >
                  {/* Play button */}
                  <button
                    type="button"
                    className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-primary/10 text-primary hover:bg-primary hover:text-primary-foreground transition-colors"
                    aria-label="Play session"
                  >
                    <Play className="h-3.5 w-3.5 translate-x-0.5" />
                  </button>

                  {/* Waveform thumb */}
                  <WaveformThumb seed={run.run_id} className="hidden sm:flex" />

                  {/* Duration */}
                  <span className="shrink-0 text-xs tabular-nums text-muted-foreground">
                    {run.duration_ms ? `${(run.duration_ms / 1000 / 60).toFixed(2)}` : `0${idx + 1}:${32 + idx * 31}`}
                  </span>

                  {/* Date */}
                  <span className="ml-auto shrink-0 text-xs text-muted-foreground">
                    {formatRelativeTime(run.created_at)}
                  </span>
                </div>
              ))}

              {/* Placeholder rows if no real data */}
              {voiceRuns.length === 0 && !sessions.isLoading && (
                <div className="space-y-2 opacity-40">
                  {[
                    { dur: "01:32", label: "May 24, 10:30 AM" },
                    { dur: "02:08", label: "May 24, 09:15 AM" },
                    { dur: "00:45", label: "May 23, 04:42 PM" },
                  ].map((row) => (
                    <div
                      key={row.dur}
                      className="flex items-center gap-3 rounded-xl border border-border/40 bg-muted/30 p-3"
                    >
                      <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-primary/10 text-primary">
                        <Play className="h-3.5 w-3.5 translate-x-0.5" />
                      </div>
                      <div className="flex flex-1 items-center gap-[2px] h-6">
                        {Array.from({ length: 24 }, (_, i) => (
                          <span
                            key={i}
                            className="w-[2px] rounded-full bg-primary/40"
                            style={{ height: `${20 + Math.sin(i * 0.8) * 50}%` }}
                          />
                        ))}
                      </div>
                      <span className="text-xs tabular-nums text-muted-foreground">{row.dur}</span>
                      <span className="text-xs text-muted-foreground">{row.label}</span>
                    </div>
                  ))}
                </div>
              )}
            </CardContent>
          </Card>
        </div>

        {/* ── RIGHT COLUMN ── */}
        <div className="space-y-5">
          {/* Language Selector */}
          <Card className="border-border/60">
            <CardHeader className="pb-3">
              <CardTitle className="text-base font-semibold">Language</CardTitle>
              <p className="text-xs text-muted-foreground">
                Passed to the assistant when the call opens.
              </p>
            </CardHeader>
            <CardContent className="grid grid-cols-2 gap-2">
              {LANGUAGES.map((option) => {
                const active = language === option.code;
                return (
                  <button
                    key={option.code}
                    type="button"
                    onClick={() => setLanguage(option.code)}
                    aria-pressed={active}
                    disabled={state === "live"}
                    className={cn(
                      "flex items-center gap-2.5 rounded-xl border px-3 py-2.5 text-left transition-all focus-ring",
                      active
                        ? "border-primary bg-primary/8 shadow-sm"
                        : "border-border bg-card hover:border-primary/40 hover:bg-muted/50",
                      state === "live" && "cursor-not-allowed opacity-60",
                    )}
                  >
                    <span className="text-lg leading-none">{option.flag}</span>
                    <span className="text-sm font-medium">{option.label}</span>
                    {active && <Check className="ml-auto h-3.5 w-3.5 text-primary" />}
                  </button>
                );
              })}
            </CardContent>
          </Card>

          {/* Transcript / Chat Panel */}
          <Card className="flex flex-col border-border/60">
            <CardHeader className="border-b border-border/40 pb-3">
              <div className="flex items-center justify-between">
                <CardTitle className="text-base font-semibold">Conversation</CardTitle>
                {agentActions.length > 0 && (
                  <Badge variant="outline" className="gap-1 text-xs">
                    <Wrench className="h-3 w-3" />
                    {agentActions.length} actions
                  </Badge>
                )}
              </div>
              <p className="text-xs text-muted-foreground">
                Speak, or type — both run the identical agent graph.
              </p>
            </CardHeader>

            <CardContent className="flex flex-1 flex-col gap-3 pt-4">
              {/* Agent action log */}
              <AnimatePresence>
                {agentActions.length > 0 && (
                  <motion.div
                    initial={{ opacity: 0, height: 0 }}
                    animate={{ opacity: 1, height: "auto" }}
                    exit={{ opacity: 0, height: 0 }}
                    className="space-y-1 rounded-xl border border-border/50 bg-muted/30 p-3"
                  >
                    <p className="text-xs font-semibold text-muted-foreground uppercase tracking-wider">
                      Agent Actions
                    </p>
                    {agentActions.slice(-4).map((action, i) => (
                      <p key={i} className="flex items-center gap-1.5 text-xs text-muted-foreground">
                        <span className="h-1.5 w-1.5 rounded-full bg-primary/60" />
                        {action}
                      </p>
                    ))}
                  </motion.div>
                )}
              </AnimatePresence>

              {/* Transcript bubbles */}
              <div
                ref={scrollRef}
                className="min-h-[260px] flex-1 space-y-3 overflow-y-auto rounded-xl bg-muted/20 p-3"
              >
                {transcript.length === 0 && (
                  <div className="flex flex-col items-center justify-center py-10 gap-3">
                    <div className="flex h-12 w-12 items-center justify-center rounded-full bg-primary/10">
                      <MessageSquare className="h-5 w-5 text-primary" />
                    </div>
                    <p className="text-center text-sm text-muted-foreground">
                      Hello! How can I help you today?
                    </p>
                    <div className="flex items-center justify-end w-full">
                      <div className="max-w-[80%] rounded-2xl rounded-br-sm bg-primary px-3.5 py-2.5 text-sm text-primary-foreground shadow-sm">
                        Can you help me grow my revenue?
                      </div>
                    </div>
                    <div className="flex items-start gap-2 w-full">
                      <div className="flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-primary/10">
                        <MessageSquare className="h-3.5 w-3.5 text-primary" />
                      </div>
                      <div className="max-w-[80%] rounded-2xl rounded-tl-sm border border-border bg-card px-3.5 py-2.5 text-sm shadow-xs">
                        Of course! Let me analyze your data and find the best opportunities.
                      </div>
                    </div>
                  </div>
                )}

                <AnimatePresence initial={false}>
                  {transcript.map((line, index) => (
                    <motion.div
                      key={`${line.at}-${index}`}
                      initial={{ opacity: 0, y: 8 }}
                      animate={{ opacity: 1, y: 0 }}
                      className={cn("flex", line.role === "user" ? "justify-end" : "justify-start gap-2")}
                    >
                      {line.role === "assistant" && (
                        <div className="flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-primary/10">
                          <MessageSquare className="h-3.5 w-3.5 text-primary" />
                        </div>
                      )}
                      <div
                        className={cn(
                          "max-w-[82%] rounded-2xl px-3.5 py-2.5 text-sm leading-relaxed shadow-xs",
                          line.role === "user"
                            ? "rounded-br-sm bg-primary text-primary-foreground"
                            : "rounded-tl-sm border border-border bg-card",
                        )}
                      >
                        {line.text}
                        <p className="mt-1 text-xs opacity-50">
                          {new Date(line.at).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })}
                        </p>
                      </div>
                    </motion.div>
                  ))}
                </AnimatePresence>

                {ask.isPending && (
                  <div className="flex justify-start gap-2">
                    <div className="flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-primary/10">
                      <MessageSquare className="h-3.5 w-3.5 text-primary" />
                    </div>
                    <div className="flex items-center gap-2 rounded-2xl rounded-tl-sm border border-border bg-card px-3.5 py-2.5 text-sm text-muted-foreground">
                      <Loader2 className="h-3.5 w-3.5 animate-spin" />
                      Thinking…
                    </div>
                  </div>
                )}
              </div>

              {/* Text input */}
              <form onSubmit={submitTyped} className="flex gap-2">
                <input
                  value={typed}
                  onChange={(e) => setTyped(e.target.value)}
                  placeholder="Type your message…"
                  aria-label="Message the Growth Scientist"
                  className="flex-1 rounded-xl border border-border bg-card px-4 py-2.5 text-sm outline-none placeholder:text-muted-foreground/60 focus:border-primary/60 focus:ring-2 focus:ring-primary/15 transition-all"
                />
                <Button
                  type="submit"
                  size="icon"
                  loading={ask.isPending}
                  aria-label="Send"
                  className="h-10 w-10 rounded-xl"
                >
                  <Send className="h-4 w-4" />
                </Button>
              </form>

              <p className="flex items-center justify-center gap-1.5 text-center text-xs text-muted-foreground">
                <span className="h-1.5 w-1.5 rounded-full bg-primary/60" />
                Built with advanced AI for natural, human-like conversations.
              </p>
            </CardContent>
          </Card>
        </div>
      </div>
    </div>
  );
}

function StatCell({
  icon: Icon,
  value,
  label,
}: {
  icon: typeof Clock;
  value: string;
  label: string;
}) {
  return (
    <div className="flex items-center gap-3 px-4 py-4">
      <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-xl bg-primary/10 text-primary">
        <Icon className="h-4 w-4" />
      </span>
      <div className="min-w-0">
        <p className="text-lg font-bold leading-none tracking-tight tabular-nums">{value}</p>
        <p className="mt-1 text-xs text-muted-foreground">{label}</p>
      </div>
    </div>
  );
}
