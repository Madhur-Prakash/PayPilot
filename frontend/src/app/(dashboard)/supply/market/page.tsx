"use client";

/**
 * Alternatives & market prices.
 *
 * * Product alternatives - pick one of your products; PayPilot finds its closest Channel3
 *   listing, then Channel3's similar products, with the price difference to *your* price.
 * * Market prices - your selling price against comparable live retail listings, kept only
 *   when they are the same kind of product. Retail prices are never your cost; your unit
 *   cost is shown separately and labelled.
 */

import { ArrowUpRight, Bookmark, Repeat, Scale, Tags } from "lucide-react";
import Link from "next/link";
import * as React from "react";

import { EmptyState, ErrorState, LoadingCard } from "@/components/common/states";
import { CompareTray } from "@/components/discovery/compare-tray";
import { ProductCard } from "@/components/discovery/product-card";
import { Channel3Setup, EstimateBadge, LiveBadge, ProductImage, StockBadge, formatPrice } from "@/components/discovery/shared";
import { PageHeader } from "@/components/supply/shared";
import { Button } from "@/components/ui/button";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/overlays";
import { Badge, Card, CardContent, CardHeader, CardTitle, Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/primitives";
import {
  isChannel3Unconfigured,
  useAlternatives,
  useCatalogProducts,
  useDiscoveryStatus,
  usePricing,
  useSaveAlternative,
} from "@/hooks/use-discovery";
import { cn, toNumber } from "@/lib/utils";
import { useAuthStore } from "@/stores/auth";

function Alternatives() {
  const catalog = useCatalogProducts();
  const alternatives = useAlternatives();
  const save = useSaveAlternative();
  const canSave = useAuthStore((s) => s.can("growth:recommend"));
  const [productId, setProductId] = React.useState<string>("");
  const data = alternatives.data;

  return (
    <div className="space-y-4">
      <Card>
        <CardContent className="flex flex-col gap-3 p-4 sm:flex-row sm:items-end">
          <div className="flex-1 space-y-1">
            <p className="text-xs font-medium">Your product</p>
            <Select value={productId} onValueChange={setProductId}>
              <SelectTrigger aria-label="Choose one of your products"><SelectValue placeholder={catalog.isLoading ? "Loading your catalog…" : "Choose a product"} /></SelectTrigger>
              <SelectContent>
                {catalog.data?.map((p) => (
                  <SelectItem key={p.id} value={p.id}>{p.name} · {formatPrice(p.price, "USD")}{p.source === "channel3" ? " · from Channel3" : ""}</SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
          <Button className="gap-1.5" disabled={!productId} loading={alternatives.isPending}
            onClick={() => alternatives.mutate({ productId, limit: 8 })}><Repeat className="h-4 w-4" /> Find alternatives</Button>
        </CardContent>
      </Card>
      {alternatives.error && (isChannel3Unconfigured(alternatives.error) ? <Channel3Setup compact /> : <ErrorState error={alternatives.error} />)}
      {alternatives.isPending && <LoadingCard lines={5} />}
      {data && (
        <>
          <div className="grid gap-3 md:grid-cols-2">
            <Card>
              <CardHeader className="pb-2"><CardTitle className="text-sm">Your product</CardTitle></CardHeader>
              <CardContent className="flex items-center gap-3">
                <ProductImage src={data.product.image_url} alt={data.product.name} className="h-16 w-16 rounded-lg" />
                <div className="text-sm">
                  <p className="font-semibold">{data.product.name}</p>
                  <p className="text-muted-foreground">Sells for {formatPrice(data.product.price, "USD")} · {data.product.sku}</p>
                </div>
              </CardContent>
            </Card>
            {data.equivalent ? (
              <Card>
                <CardHeader className="pb-2"><CardTitle className="text-sm">Closest Channel3 listing</CardTitle></CardHeader>
                <CardContent className="flex items-center gap-3">
                  <ProductImage src={data.equivalent.image_url} alt={data.equivalent.title} className="h-16 w-16 rounded-lg" />
                  <div className="min-w-0 text-sm">
                    <Link href={`/discovery/products/${encodeURIComponent(data.equivalent.id)}`} className="line-clamp-1 font-semibold hover:text-primary">{data.equivalent.title}</Link>
                    <p className="text-muted-foreground">{formatPrice(data.equivalent.price, data.equivalent.currency)} at {data.equivalent.retailer}</p>
                    <p className="text-2xs text-muted-foreground">{data.equivalent.match_note}</p>
                  </div>
                </CardContent>
              </Card>
            ) : <EmptyState title="No comparable listing" description={data.note} />}
          </div>
          {data.fallback_used && <p className="text-xs text-muted-foreground">Channel3 has not indexed that listing for similarity yet - these come from a title search.</p>}
          <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
            {data.alternatives.map((alt) => {
              const diff = toNumber(alt.vs_your_price.difference);
              return (
                <ProductCard key={alt.id} product={alt} compact footer={
                  <div className="space-y-1.5 border-t border-border pt-2">
                    <p className="text-2xs">vs your price:{" "}
                      <span className={cn("font-semibold", diff == null ? "" : diff < 0 ? "text-success" : "text-warning")}>
                        {diff == null ? "--" : `${diff > 0 ? "+" : ""}${formatPrice(diff, alt.currency)} (${alt.vs_your_price.difference_pct}%)`}
                      </span></p>
                    {canSave && (
                      <Button size="sm" variant="outline" className="h-7 w-full gap-1 text-2xs" loading={save.isPending && save.variables?.channel3Id === alt.id}
                        onClick={() => save.mutate({ productId: data.product.id, channel3Id: alt.id })}>
                        <Bookmark className="h-3 w-3" /> Save as recommendation
                      </Button>
                    )}
                  </div>
                } />
              );
            })}
          </div>
          <p className="text-2xs text-muted-foreground">{data.note}</p>
        </>
      )}
      {!data && !alternatives.isPending && !alternatives.error && (
        <EmptyState icon={Repeat} title="Pick a product to see alternatives" description="Useful when an item is unavailable, too expensive, or you want to widen a category." />
      )}
    </div>
  );
}

function MarketPrices() {
  const catalog = useCatalogProducts();
  const pricing = usePricing();
  const [selected, setSelected] = React.useState<string[]>([]);
  const retailFirst = React.useMemo(() => [...(catalog.data ?? [])].sort((a, b) =>
    Number(b.category === "retail" || b.source === "channel3") - Number(a.category === "retail" || a.source === "channel3")), [catalog.data]);

  return (
    <div className="space-y-4">
      <Card>
        <CardContent className="space-y-3 p-4">
          <p className="text-xs text-muted-foreground">
            Choose up to 5 products (each costs one Channel3 search). Leave empty to check your retail products automatically.
            Prepared items (a cafe drink) rarely have true retail equivalents - judge those comparables yourself.
          </p>
          <div className="flex flex-wrap gap-1.5">
            {retailFirst.map((p) => {
              const on = selected.includes(p.id);
              return (
                <button key={p.id} type="button" aria-pressed={on}
                  onClick={() => setSelected((s) => on ? s.filter((x) => x !== p.id) : s.length >= 5 ? s : [...s, p.id])}
                  className={cn("rounded-lg border px-2.5 py-1 text-xs", on ? "border-primary bg-primary/10 text-primary" : "border-border hover:bg-muted")}>
                  {p.name} <span className="text-muted-foreground">{formatPrice(p.price, "USD")}</span>
                  {(p.category === "retail" || p.source === "channel3") && <Badge variant="muted" className="ml-1 px-1 text-[9px]">retail</Badge>}
                </button>
              );
            })}
          </div>
          <Button className="gap-1.5" loading={pricing.isPending} onClick={() => pricing.mutate({ product_ids: selected, limit: Math.max(selected.length, 2) })}>
            <Scale className="h-4 w-4" /> Check market prices
          </Button>
        </CardContent>
      </Card>
      {pricing.error && (isChannel3Unconfigured(pricing.error) ? <Channel3Setup compact /> : <ErrorState error={pricing.error} />)}
      {pricing.isPending && <LoadingCard lines={6} />}
      {pricing.data && (
        <>
          <p className="rounded-xl border border-warning/30 bg-warning/5 p-3 text-xs text-muted-foreground">{pricing.data.disclaimer}</p>
          {pricing.data.products.length === 0 && <EmptyState title="No retail products to compare" description="Select products above to compare them explicitly." />}
          {pricing.data.products.map((row) => (
            <Card key={row.product_id}>
              <CardContent className="space-y-3 p-4">
                <div className="flex flex-wrap items-start gap-4">
                  <div className="min-w-0 flex-1">
                    <p className="text-sm font-semibold">{row.name}</p>
                    <p className="text-2xs text-muted-foreground">Searched “{row.query}” · {row.searched ?? 0} listings{row.comparable_category ? ` · compared within ${row.comparable_category.title}` : ""}</p>
                  </div>
                  <div className="grid grid-cols-2 gap-x-6 gap-y-1 text-xs sm:grid-cols-4">
                    <div><p className="text-muted-foreground">Your price</p><p className="text-base font-semibold tabular-nums">{formatPrice(row.merchant_price, row.currency)}</p></div>
                    <div><p className="text-muted-foreground">Your unit cost</p><p className="text-base font-semibold tabular-nums">{formatPrice(row.merchant_unit_cost, row.currency)}</p></div>
                    <div><p className="text-muted-foreground">Market median</p><p className="text-base font-semibold tabular-nums">{row.stats ? formatPrice(row.stats.median, row.currency) : "--"}</p></div>
                    <div><p className="text-muted-foreground">Gap</p><p className={cn("text-base font-semibold tabular-nums", row.position && Number(row.position.difference_pct) < 0 ? "text-success" : "")}>{row.position ? `${row.position.difference_pct}%` : "--"}</p></div>
                  </div>
                </div>
                {row.position && <p className="text-sm">Your price is <span className="font-semibold">{row.position.verdict}</span>{row.stats ? ` (range ${formatPrice(row.stats.min, row.currency)} – ${formatPrice(row.stats.max, row.currency)}, ${row.stats.count} listings).` : "."}</p>}
                {(row.note || row.error) && <p className="text-xs text-muted-foreground">{row.error ?? row.note}</p>}
                {row.opportunity && (
                  <div className="rounded-lg border border-primary/20 bg-primary/5 p-3 text-xs">
                    <div className="flex items-center gap-2"><Tags className="h-3.5 w-3.5 text-primary" />
                      <p className="font-semibold">{row.opportunity.type === "PRICE_TEST_UP" ? `Test ${formatPrice(row.opportunity.suggested_price, row.currency)}` : "Review the premium"}</p>
                      {row.opportunity.estimated_monthly_revenue_change && <span className="text-muted-foreground">≈ {formatPrice(row.opportunity.estimated_monthly_revenue_change, row.currency)}/month</span>}
                      <EstimateBadge />
                    </div>
                    <ul className="mt-1 space-y-0.5 text-muted-foreground">{row.opportunity.assumptions.map((a) => <li key={a}>• {a}</li>)}</ul>
                  </div>
                )}
                {row.comparables.length > 0 && (
                  <div className="grid gap-2 sm:grid-cols-2 lg:grid-cols-5">
                    {row.comparables.map((c) => (
                      <a key={c.id} href={c.url} target="_blank" rel="noopener noreferrer sponsored" className="group flex items-center gap-2 rounded-lg border border-border p-2 hover:border-primary/40">
                        <ProductImage src={c.image_url} alt={c.title} className="h-10 w-10 shrink-0 rounded" />
                        <div className="min-w-0 text-2xs">
                          <p className="line-clamp-2 font-medium leading-tight">{c.title}</p>
                          <p className="text-muted-foreground">{formatPrice(c.price, row.currency)} · {c.retailer} <ArrowUpRight className="inline h-3 w-3 opacity-0 group-hover:opacity-100" /></p>
                          <StockBadge inStock={c.in_stock} />
                        </div>
                      </a>
                    ))}
                  </div>
                )}
              </CardContent>
            </Card>
          ))}
        </>
      )}
    </div>
  );
}

export default function MarketPage() {
  const status = useDiscoveryStatus();
  return (
    <div className="space-y-5 pb-24">
      <PageHeader eyebrow="Supply Intelligence" title="Alternatives & market prices"
        description="Find alternatives to the products you sell, and see how your selling prices compare with live retail listings."
        actions={status.data?.configured ? <LiveBadge /> : undefined} />
      {status.data?.configured === false && <Channel3Setup />}
      <Tabs defaultValue="alternatives">
        <TabsList>
          <TabsTrigger value="alternatives">Product alternatives</TabsTrigger>
          <TabsTrigger value="pricing">Market prices</TabsTrigger>
        </TabsList>
        <TabsContent value="alternatives" className="mt-4"><Alternatives /></TabsContent>
        <TabsContent value="pricing" className="mt-4"><MarketPrices /></TabsContent>
      </Tabs>
      <CompareTray />
    </div>
  );
}
