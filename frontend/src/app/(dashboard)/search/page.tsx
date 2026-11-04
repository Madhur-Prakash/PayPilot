"use client";

/** Evidence search - one ranked search over the audit log, agent messages, offers, invoices, events and reviews. */

import { DatabaseZap, FileSearch, Search } from "lucide-react";
import Link from "next/link";
import * as React from "react";

import { EmptyState, ErrorState, LoadingCard } from "@/components/common/states";
import { PageHeader } from "@/components/supply/shared";
import { Button } from "@/components/ui/button";
import { Badge, Card, CardContent, Input } from "@/components/ui/primitives";
import { useEvidenceSearch, useReindex } from "@/hooks/use-integrations";
import { cn, formatRelativeTime } from "@/lib/utils";
import { useAuthStore } from "@/stores/auth";

/**
 * Elasticsearch highlights hits with <mark>. The text around them is untrusted
 * (audit descriptions, review bodies), so it is never injected as HTML: the snippet
 * is split on the mark tags and rendered as React text nodes.
 */
function Highlighted({ text }: { text: string }) {
  const parts = text.split(/(<mark>.*?<\/mark>)/gs);
  return (
    <>
      {parts.map((part, i) => {
        const match = /^<mark>(.*)<\/mark>$/s.exec(part);
        return match ? (
          <mark key={i} className="rounded bg-warning/25 px-0.5 text-foreground">{match[1]}</mark>
        ) : (
          <React.Fragment key={i}>{part}</React.Fragment>
        );
      })}
    </>
  );
}

export default function EvidenceSearchPage() {
  const [input, setInput] = React.useState("");
  const [query, setQuery] = React.useState("");
  const [kinds, setKinds] = React.useState<string[]>([]);
  const search = useEvidenceSearch(query, kinds);
  const reindex = useReindex();
  const canIndex = useAuthStore((s) => s.can("settings:manage"));
  const data = search.data;

  return (
    <div className="space-y-5">
      <PageHeader eyebrow="Governance" title="Evidence search"
        description="Why was this supplier chosen? What did the agents say to each other? Search the audit log, signed agent messages, negotiation offers, invoices, business events and reviews in one place. You only see sources your role may read."
        actions={canIndex && (
          <Button size="sm" variant="outline" className="gap-1.5" loading={reindex.isPending} onClick={() => reindex.mutate()}>
            <DatabaseZap className="h-3.5 w-3.5" /> Re-index Elasticsearch
          </Button>
        )} />

      <form className="flex gap-2" onSubmit={(e) => { e.preventDefault(); setQuery(input); }}>
        <div className="relative flex-1">
          <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
          <Input value={input} onChange={(e) => setInput(e.target.value)} className="pl-9"
            placeholder="e.g. Cascadia counter-offer, unit price, payment reconciled, refund…" aria-label="Search evidence" />
        </div>
        <Button type="submit" disabled={input.trim().length < 2}>Search</Button>
      </form>

      {data && (
        <div className="flex flex-wrap items-center gap-1.5 text-xs">
          {Object.entries(data.kind_labels).filter(([k]) => data.kinds.includes(k) || kinds.includes(k)).map(([k, label]) => {
            const on = kinds.includes(k);
            return (
              <button key={k} type="button" aria-pressed={on}
                onClick={() => setKinds((cur) => (cur.includes(k) ? cur.filter((x) => x !== k) : [...cur, k]))}
                className={cn("rounded-lg border px-2.5 py-1 font-medium focus-ring",
                  on ? "border-primary bg-primary text-primary-foreground" : "border-border bg-card hover:bg-muted")}>
                {label}
              </button>
            );
          })}
          <span className="ml-auto flex items-center gap-2 text-muted-foreground">
            <Badge variant={data.engine === "elasticsearch" ? "success" : "outline"} className="text-2xs">
              {data.engine === "elasticsearch" ? "Elasticsearch" : "Keyword fallback"}
            </Badge>
            {data.results.length} result{data.results.length === 1 ? "" : "s"}
          </span>
        </div>
      )}
      {data?.note && <p className="text-xs text-muted-foreground">{data.note}</p>}

      {search.error && <ErrorState error={search.error} onRetry={() => void search.refetch()} />}
      {search.isFetching && !data && <LoadingCard lines={5} />}

      {!query && <EmptyState icon={FileSearch} title="Search the evidence" description="Type at least two characters." />}
      {data && data.results.length === 0 && !search.isFetching && (
        <EmptyState icon={FileSearch} title="No matching evidence" description="Try fewer or different words, or widen the sources." />
      )}

      <div className="space-y-2">
        {data?.results.map((hit) => (
          <Card key={`${hit.kind}:${hit.ref}`}>
            <CardContent className="space-y-1 p-4">
              <div className="flex flex-wrap items-center gap-2">
                <Badge variant="secondary" className="text-2xs">{data.kind_labels[hit.kind] ?? hit.kind}</Badge>
                <Link href={hit.link || "#"} className="text-sm font-semibold hover:underline">{hit.title}</Link>
                <span className="ml-auto text-2xs text-muted-foreground">
                  {hit.actor && <>{hit.actor} · </>}{hit.occurred_at ? formatRelativeTime(hit.occurred_at) : ""}
                </span>
              </div>
              <p className="text-sm text-muted-foreground"><Highlighted text={hit.snippet} /></p>
              {hit.correlation_id && <p className="font-mono text-2xs text-muted-foreground/70">{hit.correlation_id}</p>}
            </CardContent>
          </Card>
        ))}
      </div>
    </div>
  );
}
