"use client";

/**
 * Gear shelf - complementary products from Channel3 for the merchant's best seller.
 *
 * Every product, price, retailer, image and buy link is live Channel3 data (or a
 * labelled offline reference without a key). The estimate shows its assumptions.
 * Nothing here places an order: the links go to the retailer.
 */

import { ExternalLink, PackageSearch, RefreshCw, ShoppingBag, Store, Users } from "lucide-react";
import * as React from "react";

import { EmptyState, ErrorState, LoadingCard } from "@/components/common/states";
import { PageHeader } from "@/components/supply/shared";
import { Button } from "@/components/ui/button";
import { Badge, Card, CardContent } from "@/components/ui/primitives";
import { useRefreshShelf, useShelf } from "@/hooks/use-shelf";
import { formatMoney, formatRelativeTime, toNumber } from "@/lib/utils";
import type { ShelfProduct } from "@/types/shelf";

function pct(fraction: string | null): string {
  const n = toNumber(fraction);
  return n == null ? "-" : `${(n * 100).toFixed(1)}%`;
}

function Stat({ icon: Icon, label, value, hint }: { icon: React.ElementType; label: string; value: string; hint?: string }) {
  return (
    <Card>
      <CardContent className="flex items-start gap-3 p-4">
        <span className="rounded-lg bg-primary/10 p-2 text-primary"><Icon className="h-4 w-4" /></span>
        <div className="min-w-0">
          <p className="text-2xs font-medium uppercase tracking-wide text-muted-foreground">{label}</p>
          <p className="truncate text-lg font-semibold">{value}</p>
          {hint && <p className="text-2xs text-muted-foreground">{hint}</p>}
        </div>
      </CardContent>
    </Card>
  );
}

function ProductCard({ product }: { product: ShelfProduct }) {
  const onSale = product.compare_at_price && toNumber(product.compare_at_price)! > toNumber(product.price)!;
  return (
    <Card className="flex h-full flex-col overflow-hidden">
      <div className="flex h-36 items-center justify-center bg-muted/30">
        {product.image_url ? (
          // Retailer images on Channel3's CDN; plain <img> keeps arbitrary hosts working.
          // eslint-disable-next-line @next/next/no-img-element
          <img src={product.image_url} alt={product.title} loading="lazy" className="h-full w-full object-contain p-2" />
        ) : (
          <PackageSearch className="h-8 w-8 text-muted-foreground" aria-hidden />
        )}
      </div>
      <CardContent className="flex flex-1 flex-col gap-2 p-3">
        <p className="line-clamp-2 text-sm font-medium leading-snug" title={product.title}>{product.title}</p>
        <div className="flex items-baseline gap-2">
          <span className="text-base font-semibold">{formatMoney(product.price)}</span>
          {onSale && <span className="text-xs text-muted-foreground line-through">{formatMoney(product.compare_at_price)}</span>}
        </div>
        <div className="flex flex-wrap gap-1 text-2xs text-muted-foreground">
          <span>{product.merchant || "retailer"}</span>
          {product.brand && <span>· {product.brand}</span>}
          {product.offers_count > 1 && <span>· {product.offers_count} offers</span>}
        </div>
        <div className="mt-auto flex items-center justify-between gap-2 pt-1">
          <Badge variant="outline" className="text-2xs" title="Affiliate commission on this offer">
            {pct(product.commission_rate)} commission
          </Badge>
          {product.url && (
            <a href={product.url} target="_blank" rel="noopener noreferrer sponsored"
              className="inline-flex items-center gap-1 text-xs font-medium text-primary hover:underline">
              View offer <ExternalLink className="h-3 w-3" />
            </a>
          )}
        </div>
      </CardContent>
    </Card>
  );
}

export default function ShelfPage() {
  const { data, isLoading, error, refetch } = useShelf();
  const { refresh, pending } = useRefreshShelf();
  const estimate = data?.estimate;

  return (
    <div className="space-y-5">
      <PageHeader eyebrow="Growth" title="Gear shelf"
        description="Your online customers buy beans - and the gear to brew them, which you don't stock. Channel3 finds those products across 25,000+ retailers, live. Recommend them next to your best seller and earn affiliate commission without holding inventory."
        actions={
          <Button size="sm" variant="outline" className="gap-1.5" loading={pending} onClick={() => void refresh()}>
            <RefreshCw className="h-3.5 w-3.5" /> Refresh prices
          </Button>
        } />

      {error && <ErrorState error={error} onRetry={() => void refetch()} />}
      {isLoading && <LoadingCard lines={6} />}
      {data && !data.anchor && <EmptyState icon={Store} title="No products yet" description={data.note} />}

      {data?.anchor && (
        <>
          <div className="flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
            <Badge variant="outline" className={data.mode === "LIVE" ? "border-success/40 text-success" : "border-warning/40 text-warning"}>
              {data.mode === "LIVE" ? "Channel3 · live" : "Simulated"}
            </Badge>
            <span>{data.mode === "LIVE" ? "Live from Channel3" : "Offline reference - set CHANNEL3_API_KEY for live products"}</span>
            {data.generated_at && <span>· refreshed {formatRelativeTime(data.generated_at)}{data.cached ? " (cached)" : ""}</span>}
          </div>

          <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
            <Stat icon={ShoppingBag} label="Built around" value={data.anchor.name} hint={`${data.anchor.sku} · ${formatMoney(data.anchor.price)}`} />
            <Stat icon={Users} label="Buyers, last 30 days" value={String(data.anchor.buyers)} hint={`${data.anchor.orders} orders (measured)`} />
            <Stat icon={Store} label="Est. shelf sales / month" value={formatMoney(estimate?.monthly_shelf_sales)}
              hint={`${pct(estimate?.attach_rate ?? null)} attach rate (assumed)`} />
            <Stat icon={ExternalLink} label="Est. commission / month" value={formatMoney(estimate?.monthly_commission)}
              hint={`typical ${pct(estimate?.typical_commission_rate ?? null)} on ${formatMoney(estimate?.typical_item_price)}`} />
          </div>

          {data.slots.map((slot) => (
            <section key={slot.key} className="space-y-2">
              <div className="flex items-baseline justify-between gap-2">
                <h2 className="text-sm font-semibold">{slot.label}</h2>
                <span className="font-mono text-2xs text-muted-foreground">category: {slot.category}</span>
              </div>
              {slot.error && <p className="text-xs text-destructive">{slot.error}</p>}
              {!slot.error && slot.products.length === 0 && (
                <p className="text-xs text-muted-foreground">No in-stock products in this category right now.</p>
              )}
              <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
                {slot.products.map((p) => <ProductCard key={`${slot.key}-${p.product_id || p.title}`} product={p} />)}
              </div>
            </section>
          ))}

          {estimate && (
            <Card>
              <CardContent className="space-y-1 p-4 text-xs text-muted-foreground">
                <p className="font-medium text-foreground">How the estimate is built</p>
                <ul className="list-disc space-y-0.5 pl-4">
                  {estimate.assumptions.map((a) => <li key={a}>{a}</li>)}
                </ul>
                <p className="pt-1">{data.note} {data.disclaimer}</p>
              </CardContent>
            </Card>
          )}
        </>
      )}
    </div>
  );
}
