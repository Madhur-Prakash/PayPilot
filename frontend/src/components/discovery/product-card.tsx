"use client";

/**
 * A Channel3 product as a card: real image, price in its own currency, retailer, stock,
 * rating only when Channel3 returned one, and - for ranked results - the score with the
 * reasons behind it. Every action on the card works: details, similar, compare, retailer link.
 */

import { ArrowUpRight, Check, GitCompareArrows, Layers, Plus } from "lucide-react";
import Link from "next/link";
import { toast } from "sonner";

import { ProductImage, Rating, ScoreRing, StockBadge, formatPrice } from "@/components/discovery/shared";
import { Button } from "@/components/ui/button";
import { Badge, Card, CardContent } from "@/components/ui/primitives";
import { cn, toNumber } from "@/lib/utils";
import { MAX_COMPARE, useCompareStore } from "@/stores/compare";
import type { CatalogProduct } from "@/types/discovery";

export function ProductCard({
  product,
  onSimilar,
  compact = false,
  footer,
}: {
  product: CatalogProduct;
  onSimilar?: (product: CatalogProduct) => void;
  compact?: boolean;
  footer?: React.ReactNode;
}) {
  const selected = useCompareStore((s) => s.items.some((i) => i.id === product.id));
  const toggle = useCompareStore((s) => s.toggle);
  const ranking = product.ranking;
  const similarity = product.similarity;
  const onSale = product.compare_at_price && (toNumber(product.compare_at_price) ?? 0) > (toNumber(product.price) ?? 0);
  const reasons = ranking?.reasons ?? similarity?.reasons ?? [];

  const onCompare = () => {
    const ok = toggle({ id: product.id, title: product.title, image_url: product.image_url, price: product.price, currency: product.currency });
    if (!ok) toast.error(`Compare up to ${MAX_COMPARE} products at a time`);
  };

  return (
    <Card className={cn("group flex h-full flex-col overflow-hidden transition-shadow hover:shadow-md", selected && "ring-2 ring-primary")}>
      <Link href={`/discovery/products/${encodeURIComponent(product.id)}`} className="relative block h-40 border-b border-border bg-white focus-ring">
        <ProductImage src={product.image_url} alt={product.title} className="h-40" />
        {ranking?.label && (
          <Badge variant="default" className="absolute left-2 top-2 bg-primary text-primary-foreground normal-case tracking-normal">{ranking.label}</Badge>
        )}
        {product.discount_pct && (
          <Badge variant="success" className="absolute right-2 top-2 normal-case tracking-normal">-{Math.round(Number(product.discount_pct))}%</Badge>
        )}
      </Link>
      <CardContent className="flex flex-1 flex-col gap-2 p-3">
        <div className="flex items-start gap-2">
          <div className="min-w-0 flex-1">
            <p className="text-2xs font-medium uppercase tracking-wide text-muted-foreground">{product.brand || product.category?.title || "Product"}</p>
            <Link href={`/discovery/products/${encodeURIComponent(product.id)}`} className="line-clamp-2 text-sm font-medium leading-snug hover:text-primary" title={product.title}>
              {product.title}
            </Link>
          </div>
          {ranking && <ScoreRing score={ranking.score} size={36} />}
        </div>
        <div className="flex flex-wrap items-baseline gap-x-2">
          <span className="text-base font-semibold tabular-nums">{formatPrice(product.price, product.currency)}</span>
          {onSale && <span className="text-xs text-muted-foreground line-through">{formatPrice(product.compare_at_price, product.currency)}</span>}
          {similarity?.price_difference && toNumber(similarity.price_difference) !== 0 && (
            <span className={cn("text-2xs font-medium", (toNumber(similarity.price_difference) ?? 0) < 0 ? "text-success" : "text-warning")}>
              {(toNumber(similarity.price_difference) ?? 0) < 0 ? "" : "+"}{formatPrice(similarity.price_difference, product.currency)}
            </span>
          )}
        </div>
        <div className="flex flex-wrap items-center gap-x-2 gap-y-1 text-2xs text-muted-foreground">
          <span className="font-medium text-foreground">{product.retailer || "retailer"}</span>
          {product.offers_count > 1 && <span>+{product.offers_count - 1} more offer{product.offers_count > 2 ? "s" : ""}</span>}
          <StockBadge inStock={product.in_stock} />
          <Rating ratings={product.ratings} />
        </div>
        {!compact && reasons.length > 0 && (
          <ul className="space-y-0.5 text-2xs text-muted-foreground">
            {reasons.slice(0, 3).map((r) => (
              <li key={r} className="flex gap-1"><span className="text-primary">•</span><span className="line-clamp-1" title={r}>{r}</span></li>
            ))}
          </ul>
        )}
        <div className="mt-auto flex flex-wrap items-center gap-1.5 pt-1">
          <Button size="sm" variant={selected ? "default" : "outline"} className="h-7 gap-1 px-2 text-2xs" onClick={onCompare}
            aria-pressed={selected}>
            {selected ? <Check className="h-3 w-3" /> : <Plus className="h-3 w-3" />} Compare
          </Button>
          {onSimilar && (
            <Button size="sm" variant="ghost" className="h-7 gap-1 px-2 text-2xs" onClick={() => onSimilar(product)}>
              <Layers className="h-3 w-3" /> Similar
            </Button>
          )}
          {product.url ? (
            <a href={product.url} target="_blank" rel="noopener noreferrer sponsored"
              className="ml-auto inline-flex items-center gap-0.5 text-2xs font-medium text-primary hover:underline">
              {product.retailer ? `View at ${product.retailer}` : "View offer"} <ArrowUpRight className="h-3 w-3" />
            </a>
          ) : (
            <Link href={`/discovery/products/${encodeURIComponent(product.id)}`} className="ml-auto inline-flex items-center gap-0.5 text-2xs font-medium text-primary hover:underline">
              Details <ArrowUpRight className="h-3 w-3" />
            </Link>
          )}
        </div>
        {footer}
      </CardContent>
    </Card>
  );
}

export function CompareIcon() {
  return <GitCompareArrows className="h-4 w-4" />;
}
