"use client";

/**
 * Product details - fetched fresh from Channel3 (GET /v1/products/{id}, a free call), so
 * prices, stock and the short-lived retailer links are current. Similar products come
 * from Channel3's /v1/similar with why each is similar and the price difference.
 */

import { ArrowLeft, ArrowUpRight, Bookmark, BookmarkCheck, GitCompareArrows, Layers, RefreshCw, Store } from "lucide-react";
import Link from "next/link";
import { useParams } from "next/navigation";
import * as React from "react";
import { toast } from "sonner";

import { EmptyState, ErrorState, LoadingCard } from "@/components/common/states";
import { CompareTray } from "@/components/discovery/compare-tray";
import { ProductCard } from "@/components/discovery/product-card";
import { Channel3Setup, LiveBadge, ProductImage, Rating, StockBadge, formatPrice } from "@/components/discovery/shared";
import { Button } from "@/components/ui/button";
import { Badge, Card, CardContent, CardHeader, CardTitle } from "@/components/ui/primitives";
import { isChannel3Unconfigured, useProductDetail, useShortlist } from "@/hooks/use-discovery";
import { cn, formatRelativeTime, toNumber } from "@/lib/utils";
import { MAX_COMPARE, useCompareStore } from "@/stores/compare";

export default function ProductDetailPage() {
  const params = useParams<{ id: string }>();
  const id = decodeURIComponent(params?.id ?? "");
  const { data, isLoading, error, refetch, isFetching } = useProductDetail(id || null);
  const shortlist = useShortlist();
  const toggle = useCompareStore((s) => s.toggle);
  const inCompare = useCompareStore((s) => s.items.some((i) => i.id === id));
  const [imageIndex, setImageIndex] = React.useState(0);
  const product = data?.product;
  const shortlisted = shortlist.data?.is_shortlisted ?? data?.history?.is_shortlisted ?? false;

  if (isLoading) return <div className="space-y-4"><LoadingCard lines={8} /><LoadingCard lines={4} /></div>;
  if (error) return isChannel3Unconfigured(error) ? <Channel3Setup /> : <ErrorState error={error} onRetry={() => void refetch()} />;
  if (!product) return <EmptyState title="Product not found" />;

  const images = product.images.length ? product.images : [{ url: product.image_url, cleaned_url: null, alt: product.title, shot_type: null, is_main: true }];
  const current = images[Math.min(imageIndex, images.length - 1)];
  const attributes = Object.entries(product.structured_attributes);

  return (
    <div className="space-y-5 pb-24">
      <div className="flex flex-wrap items-center gap-2">
        <Button asChild variant="ghost" size="sm" className="gap-1"><Link href="/discovery"><ArrowLeft className="h-4 w-4" /> Discovery</Link></Button>
        <LiveBadge />
        <span className="text-2xs text-muted-foreground">Refreshed from Channel3 {formatRelativeTime(data.fetched_at)}</span>
        <Button size="sm" variant="ghost" className="ml-auto gap-1" loading={isFetching} onClick={() => void refetch()}><RefreshCw className="h-3.5 w-3.5" /> Refresh</Button>
      </div>

      <div className="grid gap-5 lg:grid-cols-[minmax(0,420px)_1fr]">
        <Card className="overflow-hidden">
          <div className="h-80 border-b border-border bg-white">
            <ProductImage src={current?.cleaned_url || current?.url} alt={current?.alt || product.title} className="h-80" />
          </div>
          {images.length > 1 && (
            <div className="flex gap-2 overflow-x-auto p-2">
              {images.map((img, i) => (
                <button key={img.url} type="button" onClick={() => setImageIndex(i)} aria-label={`Image ${i + 1}`}
                  className={cn("h-14 w-14 shrink-0 overflow-hidden rounded-md border", i === imageIndex ? "border-primary ring-1 ring-primary" : "border-border")}>
                  <ProductImage src={img.cleaned_url || img.url} alt={img.alt} className="h-14 w-14 p-1" />
                </button>
              ))}
            </div>
          )}
        </Card>

        <div className="space-y-4">
          <div className="space-y-2">
            <p className="text-2xs font-semibold uppercase tracking-widest text-primary">{product.brand || "Product"} · {product.category.path.join(" › ") || product.category.title}</p>
            <h1 className="text-2xl font-semibold leading-tight tracking-tight">{product.title}</h1>
            <div className="flex flex-wrap items-center gap-3">
              <span className="text-3xl font-semibold tabular-nums">{formatPrice(product.price, product.currency)}</span>
              {product.compare_at_price && <span className="text-sm text-muted-foreground line-through">{formatPrice(product.compare_at_price, product.currency)}</span>}
              {product.discount_pct && <Badge variant="success" className="normal-case tracking-normal">{product.discount_pct}% off</Badge>}
              {product.min_price && product.max_price && product.min_price !== product.max_price && (
                <span className="text-xs text-muted-foreground">{formatPrice(product.min_price, product.currency)} – {formatPrice(product.max_price, product.currency)} across {product.offers_count} offers</span>
              )}
            </div>
            <div className="flex flex-wrap items-center gap-3 text-xs">
              <StockBadge inStock={product.in_stock} />
              <Rating ratings={product.ratings} />
              <span className="text-muted-foreground">{product.retailers.length} retailer{product.retailers.length === 1 ? "" : "s"}</span>
            </div>
          </div>
          <div className="flex flex-wrap gap-2">
            {product.url && (
              <Button asChild className="gap-1.5"><a href={product.url} target="_blank" rel="noopener noreferrer sponsored">
                Buy at {product.retailer} <ArrowUpRight className="h-4 w-4" /></a></Button>
            )}
            <Button variant={inCompare ? "default" : "outline"} className="gap-1.5" onClick={() => {
              if (!toggle({ id: product.id, title: product.title, image_url: product.image_url, price: product.price, currency: product.currency }))
                toast.error(`Compare up to ${MAX_COMPARE} products`);
            }}><GitCompareArrows className="h-4 w-4" /> {inCompare ? "In comparison" : "Add to compare"}</Button>
            <Button variant="outline" className="gap-1.5" loading={shortlist.isPending}
              onClick={() => shortlist.mutate({ id: product.id, value: !shortlisted })}>
              {shortlisted ? <BookmarkCheck className="h-4 w-4" /> : <Bookmark className="h-4 w-4" />} {shortlisted ? "Shortlisted" : "Shortlist"}
            </Button>
          </div>
          {product.description && <p className="text-sm leading-relaxed text-muted-foreground">{product.description}</p>}
          {product.key_features.length > 0 && (
            <ul className="grid gap-1 text-sm sm:grid-cols-2">
              {product.key_features.map((f) => <li key={f} className="flex gap-2"><span className="text-primary">•</span>{f}</li>)}
            </ul>
          )}
          <p className="text-2xs text-muted-foreground">Channel3 provides discovery, not checkout: purchases happen on the retailer&apos;s site. Retailer links are affiliate-tracked.</p>
        </div>
      </div>

      <div className="grid gap-5 lg:grid-cols-2">
        <Card>
          <CardHeader className="pb-2"><CardTitle className="flex items-center gap-1.5 text-sm"><Store className="h-4 w-4" /> Offers by retailer</CardTitle></CardHeader>
          <CardContent className="space-y-1.5">
            {product.offers.length === 0 && <p className="text-xs text-muted-foreground">No retailer offers in this locale.</p>}
            {product.offers.map((o) => (
              <div key={`${o.domain}-${o.price}`} className="flex flex-wrap items-center gap-2 rounded-lg border border-border p-2 text-sm">
                <span className="font-medium">{o.domain}</span>
                <StockBadge inStock={o.in_stock} />
                {o.condition && o.condition !== "new" && <Badge variant="muted">{o.condition}</Badge>}
                <span className="ml-auto font-semibold tabular-nums">{formatPrice(o.price, o.currency)}</span>
                {o.compare_at_price && <span className="text-2xs text-muted-foreground line-through">{formatPrice(o.compare_at_price, o.currency)}</span>}
                {o.url && <a href={o.url} target="_blank" rel="noopener noreferrer sponsored" className="inline-flex items-center gap-0.5 text-xs font-medium text-primary hover:underline">Visit <ArrowUpRight className="h-3 w-3" /></a>}
              </div>
            ))}
          </CardContent>
        </Card>
        <Card>
          <CardHeader className="pb-2"><CardTitle className="text-sm">Specifications & variants</CardTitle></CardHeader>
          <CardContent className="space-y-3">
            {product.variants?.options.map((option) => (
              <div key={option.name} className="space-y-1">
                <p className="text-2xs font-semibold uppercase tracking-wide text-muted-foreground">{option.name}</p>
                <div className="flex flex-wrap gap-1.5">
                  {option.values.map((v) => {
                    const selected = product.variants?.selected.some((s) => s.name === option.name && s.label === v.label);
                    const href = v.product_id && v.product_id !== product.id ? `/discovery/products/${encodeURIComponent(v.product_id)}` : null;
                    const pill = (
                      <span className={cn("inline-flex items-center gap-1 rounded-md border px-2 py-0.5 text-xs",
                        selected ? "border-primary bg-primary/10 text-primary" : "border-border",
                        !v.exists && "opacity-50 line-through", v.available === "OutOfStock" && "text-muted-foreground")}>
                        {v.label}
                      </span>
                    );
                    return href ? <Link key={v.label} href={href}>{pill}</Link> : <span key={v.label}>{pill}</span>;
                  })}
                </div>
              </div>
            ))}
            {attributes.length === 0 && !product.variants && <p className="text-xs text-muted-foreground">The retailer did not list structured specifications.</p>}
            {attributes.length > 0 && (
              <dl className="grid grid-cols-[minmax(0,1fr)_minmax(0,1.4fr)] gap-x-3 gap-y-1 text-xs">
                {attributes.map(([key, values]) => (
                  <React.Fragment key={key}>
                    <dt className="capitalize text-muted-foreground">{key.replace(/-/g, " ")}</dt>
                    <dd className="font-medium">{values.join(", ")}</dd>
                  </React.Fragment>
                ))}
                {product.materials.length > 0 && (<><dt className="text-muted-foreground">Materials</dt><dd className="font-medium">{product.materials.join(", ")}</dd></>)}
              </dl>
            )}
          </CardContent>
        </Card>
      </div>

      <section className="space-y-3">
        <div className="flex items-center gap-2"><Layers className="h-4 w-4 text-primary" /><h2 className="text-sm font-semibold">Similar products</h2>
          <span className="text-2xs text-muted-foreground">from Channel3 /v1/similar - with price differences</span></div>
        {data.similar_error && <p className="text-xs text-muted-foreground">{data.similar_error}</p>}
        {data.similar.length === 0 && !data.similar_error && <p className="text-xs text-muted-foreground">No similar products returned.</p>}
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
          {data.similar.map((p) => <ProductCard key={p.id} product={p} />)}
        </div>
        {data.history && (
          <p className="text-2xs text-muted-foreground">
            First discovered {formatRelativeTime(data.history.first_seen_at)}, seen {data.history.times_seen} time(s)
            {data.history.previous_min_price && toNumber(data.history.previous_min_price) !== toNumber(product.min_price)
              ? ` · previously from ${formatPrice(data.history.previous_min_price, product.currency)}` : ""}.
          </p>
        )}
      </section>
      <CompareTray />
    </div>
  );
}
