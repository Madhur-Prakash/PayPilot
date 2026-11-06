"use client";

/**
 * Shopping assistant - a multi-turn conversation with Channel3's shopping agent.
 *
 * Each message is one turn of Channel3's Conversations API: the agent asks clarifying
 * questions and runs real catalog searches; every product shown is a Channel3 result.
 * PayPilot remembers the constraints you state (budget, use, features, brands) across
 * turns, shows them, and pins the budget as a filter on later turns.
 */

import { Brain, MessageSquarePlus, Search, Send, Sparkles, User } from "lucide-react";
import Link from "next/link";
import * as React from "react";

import { ErrorState } from "@/components/common/states";
import { CompareTray } from "@/components/discovery/compare-tray";
import { ProductCard } from "@/components/discovery/product-card";
import { Channel3Setup, LiveBadge } from "@/components/discovery/shared";
import { PageHeader } from "@/components/supply/shared";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle, Skeleton, Textarea } from "@/components/ui/primitives";
import { isChannel3Unconfigured, useAssistantTurn, useConversation, useConversations, useDiscoveryStatus } from "@/hooks/use-discovery";
import { cn, formatRelativeTime } from "@/lib/utils";
import type { CatalogProduct, ConversationMessage } from "@/types/discovery";

const STARTERS = [
  "Find me a laptop under $900",
  "I need a gift for a coffee lover under $60",
  "Ergonomic office chair for long workdays",
  "Wireless earbuds for running",
];

function Message({ message }: { message: ConversationMessage }) {
  const isUser = message.role === "user";
  return (
    <div className={cn("flex gap-2", isUser && "flex-row-reverse")}>
      <span className={cn("flex h-7 w-7 shrink-0 items-center justify-center rounded-full",
        isUser ? "bg-secondary text-secondary-foreground" : "bg-primary/10 text-primary")}>
        {isUser ? <User className="h-3.5 w-3.5" /> : <Sparkles className="h-3.5 w-3.5" />}
      </span>
      <div className={cn("max-w-[85%] space-y-1 rounded-2xl px-3 py-2 text-sm",
        isUser ? "bg-primary text-primary-foreground" : "border border-border bg-card")}>
        <p className="whitespace-pre-wrap leading-relaxed">{message.text || (isUser ? "" : "Here is what I found.")}</p>
        {!isUser && (
          <p className="text-2xs text-muted-foreground">
            {message.source ?? "Channel3 shopping agent"}
            {message.products?.length ? ` · ${message.products.length} live products` : ""}
            {message.searches?.length ? ` · ${message.searches.length} catalog search${message.searches.length > 1 ? "es" : ""}` : ""}
          </p>
        )}
      </div>
    </div>
  );
}

export default function AssistantPage() {
  const status = useDiscoveryStatus();
  const conversations = useConversations();
  const [conversationId, setConversationId] = React.useState<string | null>(null);
  const conversation = useConversation(conversationId);
  const turn = useAssistantTurn();
  const [draft, setDraft] = React.useState("");
  const [pending, setPending] = React.useState<string | null>(null);
  const endRef = React.useRef<HTMLDivElement>(null);

  const messages = conversation.data?.messages ?? [];
  const lastAssistant = [...messages].reverse().find((m) => m.role === "assistant");
  const products: CatalogProduct[] = lastAssistant?.products ?? [];
  const unconfigured = status.data && !status.data.configured;

  React.useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: "smooth", block: "end" });
  }, [messages.length, pending]);

  const send = (text: string) => {
    const message = text.trim();
    if (!message || turn.isPending) return;
    setPending(message);
    setDraft("");
    turn.mutate({ message, conversationId }, {
      onSuccess: (result) => setConversationId(result.conversation.id),
      onSettled: () => setPending(null),
      onError: () => setDraft(message),
    });
  };

  return (
    <div className="space-y-5 pb-24">
      <PageHeader eyebrow="Product Discovery" title="Shopping assistant"
        description="A conversation with Channel3's shopping agent. It asks what matters, searches the live catalog for you, and remembers your constraints across turns."
        actions={<>
          {status.data?.configured && <LiveBadge />}
          <Button size="sm" variant="outline" className="gap-1.5" onClick={() => { setConversationId(null); setDraft(""); }}>
            <MessageSquarePlus className="h-3.5 w-3.5" /> New conversation
          </Button>
        </>} />
      {unconfigured && <Channel3Setup />}

      <div className="grid gap-5 xl:grid-cols-[minmax(0,420px)_1fr]">
        <Card className="flex h-[640px] flex-col">
          <CardContent className="flex-1 space-y-3 overflow-y-auto p-4">
            {messages.length === 0 && !pending && (
              <div className="space-y-3 py-6 text-center">
                <Sparkles className="mx-auto h-8 w-8 text-primary" />
                <p className="text-sm font-medium">What are you shopping for?</p>
                <div className="flex flex-wrap justify-center gap-1.5">
                  {STARTERS.map((s) => (
                    <button key={s} type="button" onClick={() => send(s)} disabled={Boolean(unconfigured)}
                      className="rounded-full border border-border px-3 py-1 text-xs text-muted-foreground hover:border-primary/40 hover:text-foreground disabled:opacity-50">{s}</button>
                  ))}
                </div>
              </div>
            )}
            {messages.map((m, i) => <Message key={`${m.at}-${i}`} message={m} />)}
            {pending && (
              <>
                <Message message={{ role: "user", text: pending, at: "" }} />
                <div className="flex items-center gap-2 text-xs text-muted-foreground"><Search className="h-3.5 w-3.5 animate-pulse text-primary" /> Searching Channel3's catalog…</div>
              </>
            )}
            {turn.error && !isChannel3Unconfigured(turn.error) && <ErrorState error={turn.error} />}
            {turn.error && isChannel3Unconfigured(turn.error) && <Channel3Setup compact />}
            <div ref={endRef} />
          </CardContent>
          {lastAssistant?.suggestions && lastAssistant.suggestions.length > 0 && !pending && (
            <div className="flex flex-wrap gap-1.5 border-t border-border px-4 py-2">
              {lastAssistant.suggestions.map((s) => (
                <button key={s} type="button" onClick={() => send(s)} className="rounded-full bg-primary/10 px-2.5 py-1 text-2xs font-medium text-primary hover:bg-primary/15">{s}</button>
              ))}
            </div>
          )}
          <form className="flex items-end gap-2 border-t border-border p-3" onSubmit={(e) => { e.preventDefault(); send(draft); }}>
            <Textarea rows={2} value={draft} onChange={(e) => setDraft(e.target.value)} placeholder="Ask or refine - e.g. “mainly for machine learning”"
              disabled={Boolean(unconfigured)} aria-label="Message the shopping assistant"
              onKeyDown={(e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); send(draft); } }} className="min-h-[44px] resize-none" />
            <Button type="submit" size="icon" loading={turn.isPending} disabled={!draft.trim() || Boolean(unconfigured)} aria-label="Send"><Send className="h-4 w-4" /></Button>
          </form>
        </Card>

        <div className="space-y-4">
          <div className="grid gap-4 md:grid-cols-2">
            <Card>
              <CardHeader className="pb-2"><CardTitle className="flex items-center gap-1.5 text-sm"><Brain className="h-4 w-4 text-primary" /> What I&apos;m keeping in mind</CardTitle></CardHeader>
              <CardContent>
                {conversation.data?.remembered?.length ? (
                  <ul className="space-y-1 text-sm">{conversation.data.remembered.map((r) => <li key={r} className="flex gap-2"><span className="text-primary">•</span>{r}</li>)}</ul>
                ) : <p className="text-xs text-muted-foreground">Budget, use, must-have features and brands you mention are remembered across turns.</p>}
                {conversation.data && (
                  <p className="mt-2 text-2xs text-muted-foreground">{conversation.data.turn_count} turn(s) · {conversation.data.credits_used} Channel3 credit(s)</p>
                )}
              </CardContent>
            </Card>
            <Card>
              <CardHeader className="pb-2"><CardTitle className="text-sm">Recent conversations</CardTitle></CardHeader>
              <CardContent className="space-y-1">
                {conversations.isLoading && <Skeleton className="h-16 w-full" />}
                {conversations.data?.length === 0 && <p className="text-xs text-muted-foreground">None yet.</p>}
                {conversations.data?.slice(0, 6).map((c) => (
                  <button key={c.id} type="button" onClick={() => setConversationId(c.id)}
                    className={cn("flex w-full items-center justify-between gap-2 rounded-lg p-1.5 text-left text-xs hover:bg-muted", c.id === conversationId && "bg-muted")}>
                    <span className="line-clamp-1">{c.title}</span>
                    <span className="shrink-0 text-2xs text-muted-foreground">{formatRelativeTime(c.last_turn_at)}</span>
                  </button>
                ))}
              </CardContent>
            </Card>
          </div>
          <div className="flex items-center justify-between">
            <h2 className="text-sm font-semibold">{products.length ? "Products from the latest answer" : "Products will appear here"}</h2>
            {products.length > 0 && <Link href="/discovery" className="text-xs text-primary hover:underline">Open full discovery</Link>}
          </div>
          {turn.isPending && <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">{Array.from({ length: 3 }).map((_, i) => <Skeleton key={i} className="h-72 w-full" />)}</div>}
          {!turn.isPending && (
            <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
              {products.map((p) => <ProductCard key={p.id} product={p} compact />)}
            </div>
          )}
        </div>
      </div>
      <CompareTray />
    </div>
  );
}
