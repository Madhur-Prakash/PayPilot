"use client";

/**
 * Supply Intelligence - where the merchant's own sales meet Channel3's live catalog.
 *
 * Loading this page spends no Channel3 credits: it shows what the sales data says
 * (categories, growth, basket pairs, inventory turnover, expansion opportunities) and
 * what PayPilot has already discovered and recommended. Searching and generating are
 * explicit actions.
 */

import {
  ArrowRight,
  Boxes,
  ClipboardCheck,
  Compass,
  PackageSearch,
  Rocket,
  Search,
  ShoppingBasket,
  Sparkles,
  Tags,
  TrendingUp,
} from "lucide-react";
import Link from "next/link";

import { ErrorState, LoadingCard, LoadingKpis } from "@/components/common/states";
import { AutopilotPanel } from "@/components/discovery/autopilot-panel";
import { Channel3Setup, EstimateBadge, LiveBadge, ProductImage, SourceTag, formatPrice } from "@/components/discovery/shared";
import { MetricTile, PageHeader, StatusPill } from "@/components/supply/shared";
import { Button } from "@/components/ui/button";
import { Badge, Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/primitives";
import { useGenerateRecommendations, useSupplyIntel } from "@/hooks/use-discovery";
import { cn, formatCompactCurrency, formatNumber, formatRelativeTime, titleCase } from "@/lib/utils";
import { useAuthStore } from "@/stores/auth";

function Growth({ value }: { value: number | null }) {
  if (value == null) return <span className="text-muted-foreground">new</span>;
  return <span className={cn("font-medium tabular-nums", value >= 0 ? "text-success" : "text-destructive")}>{value >= 0 ? "+" : ""}{value.toFixed(1)}%</span>;
}

export default function SupplyIntelligencePage() {
  const { data, isLoading, error, refetch } = useSupplyIntel(30);
  const generate = useGenerateRecommendations();
  const canGenerate = useAuthStore((s) => s.can("growth:recommend"));
  const configured = data?.status.configured;
  const top = data?.top_opportunity;

  return (
    <div className="space-y-6">
      <PageHeader eyebrow="Supply Intelligence" title="Supply Intelligence"
        description="Your sales and inventory, connected to Channel3's live product catalog: what is growing, what your customers need that you don't stock, and how your prices compare."
        actions={<>
          {configured && <LiveBadge />}
          <Button asChild size="sm" variant="outline" className="gap-1.5"><Link href="/discovery"><Search className="h-3.5 w-3.5" /> Discover products</Link></Button>
          <Button size="sm" className="gap-1.5" loading={generate.isPending} disabled={!configured || !canGenerate}
            onClick={() => generate.mutate({ days: 30, max_recommendations: 4 })}>
            <Sparkles className="h-3.5 w-3.5" /> Generate recommendations
          </Button>
        </>} />

      {data && !configured && <Channel3Setup />}
      {error && <ErrorState error={error} onRetry={() => void refetch()} />}
      {isLoading && <><LoadingKpis count={4} /><LoadingCard lines={6} /></>}

      {data && (
        <>
          {top && (
            <Card className="overflow-hidden border-primary/30">
              <div className="grid gap-0 lg:grid-cols-[1fr_320px]">
                <CardContent className="space-y-3 p-5">
                  <div className="flex flex-wrap items-center gap-2">
                    <Badge className="gap-1 normal-case tracking-normal"><Compass className="h-3 w-3" /> Inventory expansion opportunity</Badge>
                    <span className="text-2xs text-muted-foreground">Detected from your sales · {data.window?.start} → {data.window?.end}</span>
                  </div>
                  <h2 className="text-lg font-semibold leading-snug">Add {top.slot.label.toLowerCase()} next to {top.anchor.name}</h2>
                  <p className="text-sm text-muted-foreground">{top.rationale}</p>
                  <div className="flex flex-wrap gap-2">
                    <Button asChild className="gap-1.5"><Link href={`/discovery?q=${encodeURIComponent(top.slot.query + (top.slot.max_price ? ` under $${top.slot.max_price}` : ""))}`}>
                      <PackageSearch className="h-4 w-4" /> Find {top.slot.label.toLowerCase()} on Channel3</Link></Button>
                    <Button asChild variant="outline" className="gap-1.5"><Link href="/recommendations"><ClipboardCheck className="h-4 w-4" /> Review recommendations</Link></Button>
                  </div>
                </CardContent>
                <div className="border-t border-border bg-muted/30 p-5 lg:border-l lg:border-t-0">
                  <p className="mb-2 text-2xs font-semibold uppercase tracking-wide text-muted-foreground">Why now</p>
                  <dl className="space-y-1.5 text-xs">
                    {top.signals.map((s) => (
                      <div key={s.label} className="flex items-start justify-between gap-2">
                        <dt className="text-muted-foreground">{s.label}<br /><SourceTag source={s.source} /></dt>
                        <dd className="text-right font-semibold tabular-nums">{String(s.value)}</dd>
                      </div>
                    ))}
                  </dl>
                </div>
              </div>
            </Card>
          )}

          <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
            <MetricTile icon={ClipboardCheck} tone="warning" label="Awaiting your decision" value={data.kpis.open_recommendations}
              hint={`${data.kpis.approved} approved · ${data.kpis.executed} executed`} />
            <MetricTile icon={TrendingUp} tone="primary" label="Open recommendations impact"
              value={formatCompactCurrency(data.kpis.estimated_open_monthly_impact)} hint={<span className="inline-flex items-center gap-1">per month <EstimateBadge /></span>} />
            <MetricTile icon={PackageSearch} tone="success" label="Products discovered" value={formatNumber(data.kpis.products_discovered)}
              hint={`${data.kpis.searches} Channel3 searches so far`} />
            <MetricTile icon={ShoppingBasket} label="Orders analysed" value={formatNumber(data.summary?.orders ?? 0)}
              hint={data.data_quality?.note ?? `${data.summary?.products_sold ?? 0} products sold in ${data.window?.days ?? 30} days`} />
          </div>

          <AutopilotPanel />

          <div className="grid gap-5 xl:grid-cols-2">
            <Card>
              <CardHeader className="flex-row items-center justify-between pb-2">
                <div><CardTitle className="text-sm">Product recommendations</CardTitle><CardDescription>Evidence-backed, waiting for a human</CardDescription></div>
                <Button asChild size="sm" variant="ghost" className="gap-1"><Link href="/recommendations">All <ArrowRight className="h-3.5 w-3.5" /></Link></Button>
              </CardHeader>
              <CardContent className="space-y-2">
                {data.recommendations.length === 0 && (
                  <p className="text-xs text-muted-foreground">No recommendations yet. Run the autopilot or generate recommendations - they appear here with their evidence.</p>
                )}
                {data.recommendations.slice(0, 5).map((r) => (
                  <Link key={r.id} href="/recommendations" className="flex items-center gap-3 rounded-lg border border-border p-2.5 transition-colors hover:border-primary/40 hover:bg-muted/30">
                    <ProductImage src={r.products[0]?.image_url} alt={r.title} className="h-11 w-11 shrink-0 rounded-md" />
                    <div className="min-w-0 flex-1">
                      <p className="line-clamp-1 text-sm font-medium">{r.title}</p>
                      <p className="text-2xs text-muted-foreground">{r.kind_label} · {Math.round(r.confidence * 100)}% confidence ·{" "}
                        {r.expected_impact.value ? `${formatPrice(r.expected_impact.value, r.currency)}/mo est.` : "impact measured later"}</p>
                    </div>
                    <StatusPill status={r.status} />
                  </Link>
                ))}
              </CardContent>
            </Card>

            <Card>
              <CardHeader className="pb-2"><CardTitle className="text-sm">Assortment opportunities</CardTitle><CardDescription>Complementary products your buyers need</CardDescription></CardHeader>
              <CardContent className="space-y-2">
                {data.expansion_candidates.length === 0 && <p className="text-xs text-muted-foreground">No expansion candidates - PayPilot needs a growing or online-sold product to build around.</p>}
                {data.expansion_candidates.map((c) => (
                  <div key={c.key} className="flex items-center gap-3 rounded-lg border border-border p-2.5">
                    <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg bg-primary/10 text-primary"><Boxes className="h-4 w-4" /></span>
                    <div className="min-w-0 flex-1">
                      <p className="text-sm font-medium">{c.slot.label} <span className="font-normal text-muted-foreground">next to {c.anchor.name}</span></p>
                      <p className="text-2xs text-muted-foreground">{c.anchor.buyers} buyers · <Growth value={c.anchor.units_growth_pct} /> demand{c.slot.max_price ? ` · up to $${c.slot.max_price}` : ""}</p>
                    </div>
                    <Button asChild size="sm" variant="outline" disabled={!configured}>
                      <Link href={`/discovery?q=${encodeURIComponent(c.slot.query + (c.slot.max_price ? ` under $${c.slot.max_price}` : ""))}`}>Discover</Link>
                    </Button>
                  </div>
                ))}
              </CardContent>
            </Card>
          </div>

          <div className="grid gap-5 xl:grid-cols-3">
            <Card className="xl:col-span-2">
              <CardHeader className="pb-2"><CardTitle className="text-sm">Category performance</CardTitle><CardDescription>Last {data.window?.days ?? 30} days vs the {data.window?.days ?? 30} before</CardDescription></CardHeader>
              <CardContent className="overflow-x-auto">
                <table className="w-full min-w-[480px] text-sm">
                  <thead><tr className="text-left text-2xs uppercase tracking-wide text-muted-foreground">
                    <th className="pb-2 font-medium">Category</th><th className="pb-2 font-medium">Revenue</th><th className="pb-2 font-medium">Share</th><th className="pb-2 font-medium">Growth</th><th className="pb-2 font-medium">Units</th>
                  </tr></thead>
                  <tbody>
                    {data.categories.map((c) => (
                      <tr key={c.category} className="border-t border-border">
                        <td className="py-2 font-medium">{titleCase(c.category)}</td>
                        <td className="py-2 tabular-nums">{formatCompactCurrency(c.revenue)}</td>
                        <td className="py-2"><div className="flex items-center gap-2"><div className="h-1.5 w-20 overflow-hidden rounded-full bg-muted"><div className="h-full rounded-full bg-primary" style={{ width: `${c.share_pct}%` }} /></div><span className="text-xs tabular-nums">{c.share_pct}%</span></div></td>
                        <td className="py-2"><Growth value={c.growth_pct} /></td>
                        <td className="py-2 tabular-nums">{formatNumber(c.units)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </CardContent>
            </Card>
            <Card>
              <CardHeader className="pb-2"><CardTitle className="text-sm">Inventory turnover</CardTitle><CardDescription>Units sold ÷ on hand</CardDescription></CardHeader>
              <CardContent className="space-y-1.5">
                {data.inventory.length === 0 && <p className="text-xs text-muted-foreground">No tracked inventory.</p>}
                {data.inventory.map((i) => (
                  <div key={i.inventory_item_id} className="flex items-center gap-2 text-xs">
                    <span className="line-clamp-1 flex-1">{i.name}</span>
                    <span className="tabular-nums text-muted-foreground">{i.days_of_cover != null ? `${i.days_of_cover}d cover` : "--"}</span>
                    <span className="w-12 text-right font-medium tabular-nums">{i.turnover != null ? `${i.turnover}×` : "--"}</span>
                    <StatusPill status={i.status} />
                  </div>
                ))}
              </CardContent>
            </Card>
          </div>

          <div className="grid gap-5 xl:grid-cols-3">
            <Card className="xl:col-span-2">
              <CardHeader className="flex-row items-center justify-between pb-2">
                <div><CardTitle className="text-sm">Recently discovered products</CardTitle><CardDescription>Prices are snapshots - opening a product refreshes it from Channel3</CardDescription></div>
                <Button asChild size="sm" variant="ghost" className="gap-1"><Link href="/discovery">Discover <ArrowRight className="h-3.5 w-3.5" /></Link></Button>
              </CardHeader>
              <CardContent>
                {data.recently_discovered.length === 0 && <p className="text-xs text-muted-foreground">Products you or the agents find on Channel3 appear here.</p>}
                <div className="grid gap-2 sm:grid-cols-2 lg:grid-cols-4">
                  {data.recently_discovered.slice(0, 8).map((p) => (
                    <Link key={p.id} href={`/discovery/products/${encodeURIComponent(p.id)}`}
                      className="group overflow-hidden rounded-lg border border-border transition-colors hover:border-primary/40">
                      <div className="h-24 bg-white"><ProductImage src={p.image_url} alt={p.title} className="h-24" /></div>
                      <div className="space-y-0.5 p-2">
                        <p className="line-clamp-2 text-xs font-medium leading-tight group-hover:text-primary">{p.title}</p>
                        <p className="text-2xs text-muted-foreground">{formatPrice(p.min_price, p.currency)} · {p.retailer || "retailer"}</p>
                        <p className="text-[10px] text-muted-foreground">via {p.last_source} · {formatRelativeTime(p.last_seen_at)}</p>
                      </div>
                    </Link>
                  ))}
                </div>
              </CardContent>
            </Card>
            <Card>
              <CardHeader className="flex-row items-center justify-between pb-2">
                <div><CardTitle className="text-sm">Market price comparisons</CardTitle><CardDescription>Retail listings, not your cost</CardDescription></div>
                <Button asChild size="sm" variant="ghost" className="gap-1"><Link href="/supply/market"><Tags className="h-3.5 w-3.5" /> Check</Link></Button>
              </CardHeader>
              <CardContent className="space-y-2">
                {data.pricing.length === 0 && <p className="text-xs text-muted-foreground">Run a market price check to compare your retail prices with live listings.</p>}
                {data.pricing.map((r) => (
                  <Link key={r.id} href="/recommendations" className="block rounded-lg border border-border p-2 text-xs hover:border-primary/40">
                    <p className="font-medium">{r.title}</p>
                    <p className="text-muted-foreground">{r.evidence.slice(0, 2).map((e) => `${e.label}: ${e.value}`).join(" · ")}</p>
                  </Link>
                ))}
                {data.growing_products.length > 0 && (
                  <div className="space-y-1 border-t border-border pt-2">
                    <p className="text-2xs font-semibold uppercase tracking-wide text-muted-foreground">Fastest growing</p>
                    {data.growing_products.map((g) => (
                      <div key={g.product_id} className="flex justify-between text-xs"><span>{g.name}</span><Growth value={g.units_growth_pct} /></div>
                    ))}
                  </div>
                )}
              </CardContent>
            </Card>
          </div>

          {data.recent_searches.length > 0 && (
            <Card>
              <CardHeader className="pb-2"><CardTitle className="flex items-center gap-1.5 text-sm"><Rocket className="h-4 w-4" /> Recent Channel3 activity</CardTitle></CardHeader>
              <CardContent className="flex flex-wrap gap-2">
                {data.recent_searches.map((s) => (
                  <span key={s.id} className={cn("rounded-lg border px-2 py-1 text-2xs", s.error ? "border-destructive/30 text-destructive" : "border-border text-muted-foreground")}>
                    <span className="font-medium text-foreground">{s.source}</span> · {s.query.replace(/^similar:\S+\s/, "similar to ").slice(0, 60)} · {s.error ? "failed" : `${s.result_count} results`}
                  </span>
                ))}
              </CardContent>
            </Card>
          )}
        </>
      )}
    </div>
  );
}
