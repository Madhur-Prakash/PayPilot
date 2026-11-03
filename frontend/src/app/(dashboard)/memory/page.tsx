"use client";

/**
 * What the agents remember.
 *
 * The value of agent memory is entirely in whether a human can check it. An
 * agent that quietly carries a wrong conclusion forward is worse than one that
 * carries nothing, so this page exists to make the memory legible: search it,
 * add to it, and — when it is wrong — erase it.
 */

import {
  AlertTriangle,
  Brain,
  BrainCircuit,
  FlaskConical,
  Lightbulb,
  MessageSquareQuote,
  Package,
  Search,
  ThumbsUp,
  Trash2,
  type LucideIcon,
} from "lucide-react";
import * as React from "react";

import { EmptyState, ErrorState, LoadingRows } from "@/components/common/states";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/overlays";
import {
  Badge,
  Card,
  CardContent,
  CardHeader,
  CardTitle,
  Input,
  Label,
  Separator,
  Textarea,
} from "@/components/ui/primitives";
import {
  useForgetMemory,
  useMemorySearch,
  useMemoryStatus,
  useRememberNote,
} from "@/hooks/use-api";
import { useAuthStore } from "@/stores/auth";
import { cn } from "@/lib/utils";

const KINDS: { value: string; label: string; icon: LucideIcon; hint: string }[] = [
  {
    value: "recommendation",
    label: "Recommendation",
    icon: Lightbulb,
    hint: "Something the agent proposed",
  },
  { value: "outcome", label: "Outcome", icon: ThumbsUp, hint: "What a human decided" },
  {
    value: "experiment",
    label: "Experiment",
    icon: FlaskConical,
    hint: "What a test actually proved",
  },
  { value: "review", label: "Review", icon: MessageSquareQuote, hint: "What customers said" },
  { value: "inventory", label: "Inventory", icon: Package, hint: "Stock and supply" },
  { value: "note", label: "Note", icon: Brain, hint: "Something you taught it" },
];

const SUGGESTIONS = [
  "What have we learned about evening sales?",
  "Which experiments failed, and why?",
  "What did we decide about discounting?",
  "What do customers say about service?",
];

export default function MemoryPage() {
  const [draft, setDraft] = React.useState("");
  const [query, setQuery] = React.useState("");
  const [kind, setKind] = React.useState("");
  const [teaching, setTeaching] = React.useState(false);
  const [erasing, setErasing] = React.useState(false);

  const canWrite = useAuthStore((s) => s.can("memory:write"));
  const canErase = useAuthStore((s) => s.can("memory:admin"));

  const status = useMemoryStatus();
  const results = useMemorySearch(query, kind);

  // Debounced so a query does not fire on every keystroke.
  React.useEffect(() => {
    const id = setTimeout(() => setQuery(draft.trim()), 350);
    return () => clearTimeout(id);
  }, [draft]);

  const enabled = status.data?.enabled ?? false;
  const available = status.data?.available ?? false;
  const hits = results.data?.hits ?? [];

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h2 className="text-xl font-semibold tracking-tight">Agent memory</h2>
          <p className="text-sm text-muted-foreground">
            What the agents carry forward between runs — and what you can correct
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          {canWrite && enabled && (
            <Button variant="outline" size="sm" className="gap-1.5" onClick={() => setTeaching(true)}>
              <BrainCircuit className="h-3.5 w-3.5" />
              Teach the agents
            </Button>
          )}
          {canErase && enabled && (
            <Button
              variant="outline"
              size="sm"
              className="gap-1.5 text-destructive hover:text-destructive"
              onClick={() => setErasing(true)}
            >
              <Trash2 className="h-3.5 w-3.5" />
              Erase
            </Button>
          )}
        </div>
      </div>

      {/* Off / broken banners. A search that returns nothing because memory is
          disabled must not look like a search that found nothing. */}
      {status.data && !enabled && (
        <div className="rounded-xl border border-border bg-muted/40 p-4">
          <p className="text-sm font-medium">Memory is switched off</p>
          <p className="mt-1 text-2xs leading-relaxed text-muted-foreground">
            The agents still work — they just start every run from scratch. Set{" "}
            <code className="rounded bg-muted px-1 py-0.5 font-mono">MEMORY_ENABLED=true</code> to
            turn it on. It needs no extra credentials: it reuses the Groq key and embeds locally.
          </p>
        </div>
      )}

      {enabled && !available && (
        <div className="flex items-start gap-3 rounded-xl border border-destructive/40 bg-destructive/5 p-4">
          <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0 text-destructive" />
          <div>
            <p className="text-sm font-medium text-destructive">Memory is on but unreachable</p>
            <p className="mt-1 text-2xs leading-relaxed text-muted-foreground">
              cognee could not be initialised, so recall returns nothing and writes are dropped.
              The agents keep working without it. Check the backend logs for{" "}
              <code className="rounded bg-muted px-1 py-0.5 font-mono">cognee_unavailable</code>.
            </p>
          </div>
        </div>
      )}

      {/* Search */}
      <Card>
        <CardHeader className="pb-3">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <CardTitle className="text-base">Search</CardTitle>
            <Select value={kind || "all"} onValueChange={(v) => setKind(v === "all" ? "" : v)}>
              <SelectTrigger className="w-[190px]" aria-label="Filter by kind">
                <SelectValue placeholder="All kinds" />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="all">All kinds</SelectItem>
                {KINDS.map((option) => (
                  <SelectItem key={option.value} value={option.value}>
                    {option.label}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
        </CardHeader>
        <CardContent className="space-y-3">
          <div className="relative">
            <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
            <Input
              value={draft}
              onChange={(event) => setDraft(event.target.value)}
              placeholder="Ask in plain language…"
              className="pl-9"
              disabled={!enabled}
              aria-label="Search agent memory"
            />
          </div>

          {!draft && (
            <div className="flex flex-wrap gap-1.5">
              {SUGGESTIONS.map((suggestion) => (
                <button
                  key={suggestion}
                  type="button"
                  disabled={!enabled}
                  onClick={() => setDraft(suggestion)}
                  className="rounded-lg border border-border bg-card px-2.5 py-1 text-2xs transition-colors hover:bg-muted disabled:opacity-50 focus-ring"
                >
                  {suggestion}
                </button>
              ))}
            </div>
          )}
        </CardContent>
      </Card>

      {/* Results */}
      {query.length >= 2 && (
        <Card>
          <CardHeader className="pb-3">
            <CardTitle className="text-base">
              {results.isFetching ? "Searching…" : `${hits.length} recalled`}
            </CardTitle>
          </CardHeader>
          <CardContent className="space-y-2">
            {results.isLoading && <LoadingRows rows={3} />}
            {results.error && (
              <ErrorState error={results.error} onRetry={() => void results.refetch()} />
            )}

            {!results.isLoading && !results.error && hits.length === 0 && (
              <EmptyState
                icon={Brain}
                title="Nothing recalled"
                description={
                  results.data?.available === false
                    ? "Memory is not available, so there is nothing to search yet."
                    : "The agents have not concluded anything about this yet. Memory fills up as runs complete."
                }
              />
            )}

            {hits.map((hit, index) => {
              const meta = KINDS.find((k) => k.value === hit.kind);
              const Icon = meta?.icon ?? Brain;
              return (
                <div
                  key={`${hit.source}-${index}`}
                  className="flex items-start gap-3 rounded-xl border border-border bg-card p-3"
                >
                  <span className="mt-0.5 flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-primary/10 text-primary">
                    <Icon className="h-4 w-4" />
                  </span>
                  <div className="min-w-0 flex-1">
                    <p className="whitespace-pre-wrap text-xs leading-relaxed">{hit.text}</p>
                    <div className="mt-1.5 flex flex-wrap items-center gap-2">
                      {meta && (
                        <Badge variant="outline" className="text-2xs">
                          {meta.label}
                        </Badge>
                      )}
                      <span className="text-2xs text-muted-foreground">from {hit.source}</span>
                    </div>
                  </div>
                </div>
              );
            })}
          </CardContent>
        </Card>
      )}

      {/* How it works */}
      <Card>
        <CardHeader className="pb-3">
          <CardTitle className="text-base">What gets remembered</CardTitle>
          <p className="text-sm text-muted-foreground">
            Written automatically as runs complete — nobody has to remember to record anything.
          </p>
        </CardHeader>
        <CardContent className="grid gap-3 sm:grid-cols-3">
          <Explainer
            icon={Lightbulb}
            title="Recommendations"
            body="The question asked, the opportunity found, the action proposed and the evidence behind it."
          />
          <Explainer
            icon={ThumbsUp}
            title="Approvals"
            body="Whether a human agreed. A rejection tells the agent not to propose the same thing again."
          />
          <Explainer
            icon={FlaskConical}
            title="Measurements"
            body="What an experiment actually proved — the only memory grounded in a result, not a forecast."
          />
        </CardContent>
      </Card>

      {status.data && enabled && (
        <p className="text-2xs text-muted-foreground">
          Embeddings run locally via{" "}
          <span className="font-mono">{status.data.embedding_provider}</span>; the knowledge graph
          is built with <span className="font-mono">{status.data.llm_model}</span>.
          {status.data.pending_writes > 0 &&
            ` ${status.data.pending_writes} memory write${
              status.data.pending_writes === 1 ? "" : "s"
            } still in flight.`}
        </p>
      )}

      <TeachDialog open={teaching} onClose={() => setTeaching(false)} />
      <EraseDialog open={erasing} onClose={() => setErasing(false)} />
    </div>
  );
}

function Explainer({
  icon: Icon,
  title,
  body,
}: {
  icon: LucideIcon;
  title: string;
  body: string;
}) {
  return (
    <div className="rounded-xl border border-border bg-muted/30 p-3">
      <span className="flex h-7 w-7 items-center justify-center rounded-lg bg-primary/10 text-primary">
        <Icon className="h-3.5 w-3.5" />
      </span>
      <p className="mt-2 text-xs font-medium">{title}</p>
      <p className="mt-0.5 text-2xs leading-relaxed text-muted-foreground">{body}</p>
    </div>
  );
}

function TeachDialog({ open, onClose }: { open: boolean; onClose: () => void }) {
  const remember = useRememberNote();
  const [text, setText] = React.useState("");
  const [kind, setKind] = React.useState("note");

  React.useEffect(() => {
    if (open) {
      setText("");
      setKind("note");
    }
  }, [open]);

  const valid = text.trim().length >= 10;

  return (
    <Dialog open={open} onOpenChange={(next) => !next && onClose()}>
      <DialogContent className="max-w-lg">
        <DialogHeader>
          <DialogTitle>Teach the agents</DialogTitle>
          <DialogDescription>
            Write it as though the reader knows nothing about today. A memory that needs its
            original context to make sense will never be recalled usefully.
          </DialogDescription>
        </DialogHeader>

        <div className="space-y-3">
          <div className="space-y-1.5">
            <Label htmlFor="memory-kind">Kind</Label>
            <Select value={kind} onValueChange={setKind}>
              <SelectTrigger id="memory-kind">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {KINDS.map((option) => (
                  <SelectItem key={option.value} value={option.value}>
                    {option.label}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
            <p className="text-2xs text-muted-foreground">
              {KINDS.find((k) => k.value === kind)?.hint}
            </p>
          </div>

          <div className="space-y-1.5">
            <Label htmlFor="memory-text">What should they remember?</Label>
            <Textarea
              id="memory-text"
              rows={5}
              value={text}
              onChange={(event) => setText(event.target.value)}
              placeholder="Our evening rush is 6 to 8pm and the kitchen cannot take on extra prep then, so evening bundles have to use items that are already made."
            />
            <p className="text-2xs text-muted-foreground">
              {text.trim().length < 10
                ? "A little more detail — at least ten characters."
                : "Queued once saved; the knowledge graph takes a few seconds to build."}
            </p>
          </div>
        </div>

        <DialogFooter>
          <Button variant="ghost" onClick={onClose}>
            Cancel
          </Button>
          <Button
            loading={remember.isPending}
            disabled={!valid}
            onClick={() =>
              remember.mutate({ text: text.trim(), kind }, { onSuccess: onClose })
            }
          >
            Save to memory
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

function EraseDialog({ open, onClose }: { open: boolean; onClose: () => void }) {
  const forget = useForgetMemory();
  const [confirmation, setConfirmation] = React.useState("");

  React.useEffect(() => {
    if (open) setConfirmation("");
  }, [open]);

  // Typing the word is deliberate friction: this cannot be undone, and there is
  // no backup of a knowledge graph.
  const confirmed = confirmation.trim().toUpperCase() === "ERASE";

  return (
    <Dialog open={open} onOpenChange={(next) => !next && onClose()}>
      <DialogContent className="max-w-md">
        <DialogHeader>
          <DialogTitle>Erase this merchant&apos;s memory</DialogTitle>
          <DialogDescription>
            Every recommendation, approval and experiment learning is deleted. This cannot be
            undone, and the agents will start from scratch on the next run.
          </DialogDescription>
        </DialogHeader>

        <Separator />

        <div className="space-y-1.5">
          <Label htmlFor="erase-confirm">
            Type <span className="font-mono font-semibold">ERASE</span> to confirm
          </Label>
          <Input
            id="erase-confirm"
            value={confirmation}
            onChange={(event) => setConfirmation(event.target.value)}
            autoComplete="off"
            className={cn(
              confirmation && !confirmed && "border-destructive",
            )}
          />
        </div>

        <DialogFooter>
          <Button variant="ghost" onClick={onClose}>
            Cancel
          </Button>
          <Button
            variant="destructive"
            loading={forget.isPending}
            disabled={!confirmed}
            onClick={() => forget.mutate(undefined, { onSuccess: onClose })}
          >
            Erase everything
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
