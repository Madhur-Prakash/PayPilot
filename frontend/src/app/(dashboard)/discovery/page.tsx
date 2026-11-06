"use client";

/**
 * AI Product Discovery - describe what you want to stock, in your own words.
 *
 * The request is parsed (budget, currency, brands, use case, features), turned into a
 * live Channel3 search with real filters, and the results are ranked with the reasons
 * shown. Nothing is invented: without CHANNEL3_API_KEY this page shows setup steps.
 */

import {
  Clock,
  Filter,
  History,
  Layers,
  Link2,
  Loader2,
  MessagesSquare,
  Search,
  SearchX,
  Sparkles,
  Wand2,
  X,
} from "lucide-react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import * as React from "react";

import { EmptyState, ErrorState, LoadingCard } from "@/components/common/states";
import { CompareTray } from "@/components/discovery/compare-tray";
import { ProductCard } from "@/components/discovery/product-card";
import { AiBadge, Channel3Setup, LiveBadge, formatPrice } from "@/components/discovery/shared";
import { PageHeader } from "@/components/supply/shared";
import { Button } from "@/components/ui/button";
import { Badge, Card, CardContent, CardHeader, CardTitle, Input, Label, Skeleton } from "@/components/ui/primitives";
import { Switch } from "@/components/ui/overlays";
import {
  isChannel3Unconfigured,
  useDiscoveryStatus,
  useEnrich,
  useProductSearch,
  useSearchHistory,
  useSimilar,
} from "@/hooks/use-discovery";
import { formatRelativeTime } from "@/lib/utils";
import type { CatalogProduct, SearchRequest, SearchResult, SimilarResult } from "@/types/discovery";

const EXAMPLES = [
  "Wireless earbuds under ₹5,000",
  "Premium office chairs under ₹15,000",
  "Burr coffee grinder under $150 for home baristas",
  "Products suitable for a college student",
  "Compare Sony vs Bose noise cancelling headphones",
  "Insulated travel mug under $40",
];

interface Filters {
  min_price: string;
  max_price: string;
  brands: string;
  category: string;
  retailers: string;
  in_stock_only: boolean;
  on_sale: boolean;
  agentic: boolean;
}

const EMPTY_FILTERS: Filters = { min_price: "", max_price: "", brands: "", category: "", retailers: "", in_stock_only: true, on_sale: false, agentic: false };

function list(value: string): string[] {
  return value.split(",").map((v) => v.trim()).filter(Boolean);
}

function IntentPanel({ result }: { result: SearchResult }) {
  const i = result.intent;
  const chips: { label: string; value: string }[] = [{ label: "Searching for", value: result.channel3_query }];
  if (i.max_price != null || i.min_price != null) {
    const stated = i.min_price != null && i.max_price != null ? `${i.min_price.toLocaleString()}–${i.max_price.toLocaleString()}`
      : i.max_price != null ? `up to ${i.max_price.toLocaleString()}` : `from ${i.min_price?.toLocaleString()}`;
    chips.push({ label: "Budget", value: `${i.budget_currency} ${stated}` });
  }
  if (result.budget.converted && result.budget.max_price != null) chips.push({ label: "Price filter", value: `≤ ${formatPrice(result.budget.max_price, result.budget.currency)}` });
  if (result.category) chips.push({ label: "Category", value: result.category.title ?? result.category.slug });
  if (i.brands.length) chips.push({ label: "Brands", value: i.brands.join(", ") });
  if (i.exclude_brands.length) chips.push({ label: "Avoid", value: i.exclude_brands.join(", ") });
  if (i.use_case) chips.push({ label: "For", value: i.use_case });
  if (i.attributes.length) chips.push({ label: "Must have", value: i.attributes.join(", ") });
  if (i.retailers.length) chips.push({ label: "Retailers", value: i.retailers.join(", ") });
  if (i.on_sale) chips.push({ label: "Deals", value: "on sale only" });
  return (
    <Card className="border-primary/20 bg-primary/[0.03]">
      <CardContent className="space-y-2 p-4">
        <div className="flex flex-wrap items-center gap-2">
          <Wand2 className="h-4 w-4 text-primary" />
          <p className="text-sm font-semibold">What I understood</p>
          {result.used_llm && <AiBadge label="AI-assisted" />}
          <span className="ml-auto text-2xs text-muted-foreground">{result.products.length} products · {(result.duration_ms / 1000).toFixed(1)}s · Channel3 {result.mode.toLowerCase()}</span>
        </div>
        <div className="flex flex-wrap gap-1.5">
          {chips.map((c) => (
            <span key={c.label} className="inline-flex items-center gap-1 rounded-lg border border-border bg-card px-2 py-1 text-xs">
              <span className="text-muted-foreground">{c.label}:</span> <span className="font-medium">{c.value}</span>
            </span>
          ))}
        </div>
        {result.notes.map((n) => <p key={n} className="text-2xs text-muted-foreground">{n}</p>)}
        <p className="text-2xs text-muted-foreground">{result.ranking_note}</p>
      </CardContent>
    </Card>
  );
}

function DiscoveryWorkspace() {
  const router = useRouter();
  const params = useSearchParams();
  const status = useDiscoveryStatus();
  const search = useProductSearch();
  const history = useSearchHistory(12);
  const similar = useSimilar();
  const enrich = useEnrich();
  const [query, setQuery] = React.useState("");
  const [filters, setFilters] = React.useState<Filters>(EMPTY_FILTERS);
  const [showFilters, setShowFilters] = React.useState(false);
  const [result, setResult] = React.useState<SearchResult | null>(null);
  const [extra, setExtra] = React.useState<CatalogProduct[]>([]);
  const [similarFor, setSimilarFor] = React.useState<SimilarResult | null>(null);
  const [url, setUrl] = React.useState("");
  const ranInitial = React.useRef(false);

  const run = React.useCallback((text: string, pageToken?: string | null) => {
    const trimmed = text.trim();
    if (trimmed.length < 2) return;
    const body: SearchRequest = {
      query: trimmed,
      min_price: filters.min_price ? Number(filters.min_price) : null,
      max_price: filters.max_price ? Number(filters.max_price) : null,
      brands: list(filters.brands),
      category: filters.category.trim() || null,
      retailers: list(filters.retailers),
      include_out_of_stock: filters.in_stock_only ? null : true,
      on_sale: filters.on_sale ? true : null,
      mode: filters.agentic ? "agentic" : "default",
      limit: 12,
      page_token: pageToken ?? null,
    };
    search.mutate(body, {
      onSuccess: (data) => {
        if (pageToken) {
          setExtra((prev) => [...prev, ...data.products]);
          setResult((prev) => (prev ? { ...prev, next_page_token: data.next_page_token } : data));
        } else {
          setResult(data);
          setExtra([]);
          setSimilarFor(null);
        }
      },
    });
  }, [filters, search]);

  React.useEffect(() => {
    const q = params.get("q");
    if (q && !ranInitial.current && status.data?.configured) {
      ranInitial.current = true;
      setQuery(q);
      run(q);
    }
  }, [params, run, status.data?.configured]);

  const onSimilar = (product: CatalogProduct) => {
    similar.mutate({ product_id: product.id, limit: 8 }, {
      onSuccess: (data) => {
        setSimilarFor(data);
        requestAnimationFrame(() => document.getElementById("similar-panel")?.scrollIntoView({ behavior: "smooth", block: "start" }));
      },
    });
  };

  const unconfigured = status.data && !status.data.configured;
  const products = result ? [...result.products, ...extra] : [];

  return (
    <div className="space-y-5 pb-24">
      <PageHeader eyebrow="Supply Intelligence" title="AI Product Discovery"
        description="Describe what you want to sell - budget, brand, who it is for. The Product Discovery Agent turns it into a live Channel3 search across thousands of retailers and ranks what comes back, with the reasons."
        actions={<>
          {status.data?.configured && <LiveBadge />}
          <Button asChild size="sm" variant="outline" className="gap-1.5"><Link href="/discovery/assistant"><MessagesSquare className="h-3.5 w-3.5" /> Shopping assistant</Link></Button>
        </>} />

      {unconfigured && <Channel3Setup />}

      <Card>
        <CardContent className="space-y-3 p-4">
          <form className="flex flex-col gap-2 sm:flex-row" onSubmit={(e) => { e.preventDefault(); run(query); }}>
            <div className="relative flex-1">
              <Sparkles className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-primary" />
              <Input value={query} onChange={(e) => setQuery(e.target.value)} disabled={Boolean(unconfigured)}
                placeholder="e.g. premium office chairs under ₹15,000 with lumbar support" aria-label="Describe the products you want"
                className="h-11 pl-9 text-[0.9375rem]" />
            </div>
            <div className="flex gap-2">
              <Button type="button" variant="outline" className="h-11 gap-1.5" onClick={() => setShowFilters((s) => !s)} aria-expanded={showFilters}>
                <Filter className="h-4 w-4" /> Filters
              </Button>
              <Button type="submit" size="lg" className="gap-1.5" loading={search.isPending && !search.variables?.page_token}
                disabled={Boolean(unconfigured) || query.trim().length < 2}>
                <Search className="h-4 w-4" /> Discover
              </Button>
            </div>
          </form>
          {showFilters && (
            <div className="grid gap-3 rounded-xl border border-border bg-muted/30 p-3 sm:grid-cols-2 lg:grid-cols-4">
              <div className="space-y-1"><Label htmlFor="f-min">Min price ({status.data?.currency ?? "USD"})</Label>
                <Input id="f-min" inputMode="decimal" value={filters.min_price} onChange={(e) => setFilters({ ...filters, min_price: e.target.value })} /></div>
              <div className="space-y-1"><Label htmlFor="f-max">Max price ({status.data?.currency ?? "USD"})</Label>
                <Input id="f-max" inputMode="decimal" value={filters.max_price} onChange={(e) => setFilters({ ...filters, max_price: e.target.value })} /></div>
              <div className="space-y-1"><Label htmlFor="f-brands">Brands (comma separated)</Label>
                <Input id="f-brands" placeholder="Sony, JBL" value={filters.brands} onChange={(e) => setFilters({ ...filters, brands: e.target.value })} /></div>
              <div className="space-y-1"><Label htmlFor="f-retailers">Retailers (domains)</Label>
                <Input id="f-retailers" placeholder="bestbuy.com" value={filters.retailers} onChange={(e) => setFilters({ ...filters, retailers: e.target.value })} /></div>
              <div className="space-y-1"><Label htmlFor="f-cat">Channel3 category slug</Label>
                <Input id="f-cat" placeholder="office-chairs" value={filters.category} onChange={(e) => setFilters({ ...filters, category: e.target.value.toLowerCase().replace(/[^a-z0-9-]/g, "") })} /></div>
              <label className="flex items-center justify-between gap-2 rounded-lg border border-border bg-card px-3 text-sm">In stock only
                <Switch checked={filters.in_stock_only} onCheckedChange={(v) => setFilters({ ...filters, in_stock_only: v })} /></label>
              <label className="flex items-center justify-between gap-2 rounded-lg border border-border bg-card px-3 text-sm">On sale only
                <Switch checked={filters.on_sale} onCheckedChange={(v) => setFilters({ ...filters, on_sale: v })} /></label>
              <label className="flex items-center justify-between gap-2 rounded-lg border border-border bg-card px-3 text-sm" title="Channel3's agentic mode plans several sub-searches from a rich brief. Slower.">Deep search (agentic)
                <Switch checked={filters.agentic} onCheckedChange={(v) => setFilters({ ...filters, agentic: v })} /></label>
              <p className="text-2xs text-muted-foreground sm:col-span-2 lg:col-span-4">
                Filters here override what is parsed from your sentence. Budgets in other currencies (₹, ¥) are converted with the configured reference rate and labelled.
                <button type="button" className="ml-2 text-primary hover:underline" onClick={() => setFilters(EMPTY_FILTERS)}>Reset filters</button>
              </p>
            </div>
          )}
          <div className="flex flex-wrap gap-1.5">
            {EXAMPLES.map((ex) => (
              <button key={ex} type="button" disabled={Boolean(unconfigured)} onClick={() => { setQuery(ex); run(ex); }}
                className="rounded-full border border-border bg-card px-3 py-1 text-xs text-muted-foreground transition-colors hover:border-primary/40 hover:text-foreground disabled:opacity-50">
                {ex}
              </button>
            ))}
          </div>
        </CardContent>
      </Card>

      <div className="grid gap-5 xl:grid-cols-[1fr_300px]">
        <div className="min-w-0 space-y-4">
          {search.isPending && !search.variables?.page_token && (
            <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
              {Array.from({ length: 6 }).map((_, i) => <Card key={i}><Skeleton className="h-40 rounded-b-none" /><CardContent className="space-y-2 p-3"><Skeleton className="h-4 w-3/4" /><Skeleton className="h-3 w-1/2" /><Skeleton className="h-8 w-full" /></CardContent></Card>)}
            </div>
          )}
          {search.error && (isChannel3Unconfigured(search.error) ? <Channel3Setup compact /> : <ErrorState error={search.error} onRetry={() => run(query)} />)}
          {result && !search.isPending && <IntentPanel result={result} />}
          {result && products.length === 0 && !search.isPending && (
            <EmptyState icon={SearchX} title="No live products matched" description="Try widening the budget, removing a brand or category filter, or describing the product differently." />
          )}
          {products.length > 0 && (
            <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
              {products.map((p) => <ProductCard key={p.id} product={p} onSimilar={onSimilar} />)}
            </div>
          )}
          {result?.next_page_token && (
            <div className="flex justify-center">
              <Button variant="outline" loading={search.isPending && Boolean(search.variables?.page_token)} onClick={() => run(result.query, result.next_page_token)}>
                Load more results
              </Button>
            </div>
          )}
          {!result && !search.isPending && !unconfigured && (
            <EmptyState icon={Search} title="Start with a sentence" description="Try one of the examples above. Every product you see comes from Channel3's live catalog - with real images, prices and retailer links." />
          )}

          {(similar.isPending || similarFor) && (
            <section id="similar-panel" className="space-y-3 scroll-mt-20">
              <div className="flex items-center gap-2">
                <Layers className="h-4 w-4 text-primary" />
                <h3 className="text-sm font-semibold">{similarFor ? `Similar to ${similarFor.source.title}` : "Finding similar products…"}</h3>
                {similarFor && <button type="button" onClick={() => setSimilarFor(null)} className="ml-auto rounded p-1 text-muted-foreground hover:bg-muted" aria-label="Close similar products"><X className="h-4 w-4" /></button>}
              </div>
              {similar.isPending && <LoadingCard lines={3} />}
              {similarFor?.note && <p className="text-xs text-muted-foreground">{similarFor.note}</p>}
              {similarFor && (
                <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
                  {similarFor.products.map((p) => <ProductCard key={p.id} product={p} compact={false} />)}
                </div>
              )}
            </section>
          )}
        </div>

        <aside className="space-y-4">
          <Card>
            <CardHeader className="pb-2"><CardTitle className="flex items-center gap-1.5 text-sm"><Link2 className="h-4 w-4" /> Enrich a product URL</CardTitle></CardHeader>
            <CardContent className="space-y-2">
              <p className="text-2xs text-muted-foreground">Paste a retailer product page. Channel3 returns structured data: images, offers, specifications, variants.</p>
              <form className="flex gap-1.5" onSubmit={(e) => {
                e.preventDefault();
                enrich.mutate(url.trim(), { onSuccess: (data) => router.push(`/discovery/products/${encodeURIComponent(data.product.id)}`) });
              }}>
                <Input value={url} onChange={(e) => setUrl(e.target.value)} placeholder="https://…" aria-label="Product page URL" disabled={Boolean(unconfigured)} />
                <Button type="submit" size="sm" className="h-9" loading={enrich.isPending} disabled={Boolean(unconfigured) || url.trim().length < 10}>Go</Button>
              </form>
              {enrich.isPending && <p className="flex items-center gap-1 text-2xs text-muted-foreground"><Loader2 className="h-3 w-3 animate-spin" /> Reading the page (can take ~10s)…</p>}
            </CardContent>
          </Card>
          <Card>
            <CardHeader className="pb-2"><CardTitle className="flex items-center gap-1.5 text-sm"><History className="h-4 w-4" /> Search history</CardTitle></CardHeader>
            <CardContent className="space-y-1">
              {history.isLoading && <Skeleton className="h-24 w-full" />}
              {history.data?.length === 0 && <p className="text-2xs text-muted-foreground">Your searches appear here.</p>}
              {history.data?.map((h) => (
                <button key={h.id} type="button" disabled={Boolean(unconfigured) || h.source !== "discovery"}
                  onClick={() => { setQuery(h.query); run(h.query); }}
                  className="flex w-full items-start gap-2 rounded-lg p-1.5 text-left hover:bg-muted disabled:cursor-default disabled:hover:bg-transparent">
                  <Clock className="mt-0.5 h-3 w-3 shrink-0 text-muted-foreground" />
                  <span className="min-w-0 flex-1">
                    <span className="line-clamp-1 text-xs">{h.query.replace(/^similar:\S+\s/, "Similar: ")}</span>
                    <span className="text-2xs text-muted-foreground">
                      {h.error ? "failed" : `${h.result_count} results`} · {h.source} · {formatRelativeTime(h.created_at)}
                    </span>
                  </span>
                  {h.used_llm && <Badge variant="default" className="px-1 text-[9px]">AI</Badge>}
                </button>
              ))}
            </CardContent>
          </Card>
        </aside>
      </div>
      <CompareTray />
    </div>
  );
}

export default function DiscoveryPage() {
  return (
    <React.Suspense fallback={<LoadingCard lines={6} />}>
      <DiscoveryWorkspace />
    </React.Suspense>
  );
}
