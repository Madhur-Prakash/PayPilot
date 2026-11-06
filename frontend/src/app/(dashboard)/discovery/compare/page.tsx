"use client";

/**
 * Product comparison - 2 to 4 products, fetched fresh from Channel3, side by side.
 *
 * Four verdicts (better value, more suitable specifications, fit for your customers,
 * best alternative) each show the evidence behind them. A specification a retailer did
 * not publish is shown as "Not listed" - never filled in.
 */

import { ArrowLeft, ArrowUpRight, Award, BadgeDollarSign, ListChecks, Repeat, Trophy, Users } from "lucide-react";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import * as React from "react";

import { EmptyState, ErrorState, LoadingCard } from "@/components/common/states";
import { AiBadge, Channel3Setup, LiveBadge, ProductImage, Rating, SourceTag, StockBadge, formatPrice } from "@/components/discovery/shared";
import { PageHeader } from "@/components/supply/shared";
import { Button } from "@/components/ui/button";
import { Badge, Card, CardContent, CardHeader, CardTitle } from "@/components/ui/primitives";
import { isChannel3Unconfigured, useComparison } from "@/hooks/use-discovery";
import { cn } from "@/lib/utils";
import { useCompareStore } from "@/stores/compare";
import type { ComparisonResult, Verdict } from "@/types/discovery";

const VERDICTS: { key: keyof ComparisonResult["verdicts"]; label: string; icon: React.ElementType }[] = [
  { key: "best_value", label: "Better value", icon: BadgeDollarSign },
  { key: "best_specifications", label: "More suitable specifications", icon: ListChecks },
  { key: "best_customer_fit", label: "Fits your customers", icon: Users },
  { key: "best_alternative", label: "Best alternative", icon: Repeat },
];

function VerdictCard({ label, icon: Icon, verdict }: { label: string; icon: React.ElementType; verdict: Verdict | null }) {
  return (
    <Card className="h-full">
      <CardContent className="space-y-2 p-4">
        <div className="flex items-center gap-2">
          <span className="flex h-8 w-8 items-center justify-center rounded-lg bg-primary/10 text-primary"><Icon className="h-4 w-4" /></span>
          <p className="text-2xs font-semibold uppercase tracking-wide text-muted-foreground">{label}</p>
        </div>
        {verdict?.title ? <p className="line-clamp-2 text-sm font-semibold">{verdict.title}</p> : <p className="text-sm text-muted-foreground">No clear winner</p>}
        {verdict?.reason && <p className="text-xs text-muted-foreground">{verdict.reason}</p>}
        {verdict && verdict.evidence.length > 0 && (
          <details className="text-2xs">
            <summary className="cursor-pointer text-primary">Evidence ({verdict.evidence.length})</summary>
            <ul className="mt-1 space-y-0.5">
              {verdict.evidence.map((e, i) => (
                <li key={`${e.label}-${i}`} className="flex justify-between gap-2"><span className="line-clamp-1 text-muted-foreground">{e.label}</span>
                  <span className="shrink-0 font-medium">{e.value} <SourceTag source={e.source} /></span></li>
              ))}
            </ul>
          </details>
        )}
      </CardContent>
    </Card>
  );
}

function CompareView() {
  const params = useSearchParams();
  const fromStore = useCompareStore((s) => s.items);
  const ids = React.useMemo(() => {
    const raw = params.get("ids");
    const list = raw ? raw.split(",").map((s) => decodeURIComponent(s)).filter(Boolean) : fromStore.map((i) => i.id);
    return Array.from(new Set(list)).slice(0, 4);
  }, [params, fromStore]);
  const { data, isLoading, error, refetch } = useComparison(ids);

  if (ids.length < 2) {
    return <EmptyState icon={ListChecks} title="Pick at least two products" description="Use “Compare” on product cards in Product Discovery, then open the comparison."
      action={<Button asChild size="sm"><Link href="/discovery">Go to Product Discovery</Link></Button>} />;
  }
  if (isLoading) return <div className="space-y-4"><LoadingCard lines={3} /><LoadingCard lines={10} /></div>;
  if (error) return isChannel3Unconfigured(error) ? <Channel3Setup /> : <ErrorState error={error} onRetry={() => void refetch()} />;
  if (!data) return null;

  const overallId = data.overall.product_id;
  const cols = data.products.length;
  return (
    <div className="space-y-5">
      <PageHeader eyebrow="Product Discovery" title="Product comparison"
        description="Fresh Channel3 data, side by side. Each verdict lists its evidence; anything a retailer did not publish stays “Not listed”."
        actions={<><LiveBadge /><Button asChild variant="ghost" size="sm" className="gap-1"><Link href="/discovery"><ArrowLeft className="h-4 w-4" /> Back</Link></Button></>} />

      <Card className="border-primary/20 bg-primary/[0.03]">
        <CardContent className="flex flex-wrap items-start gap-3 p-4">
          <Trophy className="mt-0.5 h-5 w-5 shrink-0 text-primary" />
          <div className="min-w-0 flex-1 space-y-1">
            <div className="flex flex-wrap items-center gap-2"><p className="text-sm font-semibold">Summary</p>{data.used_llm && <AiBadge label="AI-written from the verdicts" />}</div>
            <p className="text-sm text-muted-foreground">{data.narrative}</p>
            {data.merchant_context.average_order_value != null && (
              <p className="text-2xs text-muted-foreground">Your customers&apos; average order: {formatPrice(data.merchant_context.average_order_value, "USD")} · catalog median price {formatPrice(data.merchant_context.catalog_median_price, "USD")} ({data.merchant_context.window}).</p>
            )}
          </div>
        </CardContent>
      </Card>

      <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
        {VERDICTS.map((v) => <VerdictCard key={v.key} label={v.label} icon={v.icon} verdict={data.verdicts[v.key]} />)}
      </div>

      <Card>
        <CardHeader className="pb-2"><CardTitle className="text-sm">Side by side</CardTitle></CardHeader>
        <CardContent className="overflow-x-auto">
          <table className="w-full min-w-[640px] border-separate border-spacing-0 text-sm">
            <thead>
              <tr>
                <th className="w-44 p-2" />
                {data.products.map((p) => (
                  <th key={p.id} className={cn("p-2 align-top", p.id === overallId && "rounded-t-xl bg-primary/5")} style={{ width: `${(100 - 15) / cols}%` }}>
                    <div className="space-y-2 text-left font-normal">
                      {p.id === overallId && <Badge className="gap-1 normal-case tracking-normal"><Award className="h-3 w-3" /> Overall pick ({data.overall.wins[p.id]} wins)</Badge>}
                      <div className="h-28 rounded-lg border border-border bg-white"><ProductImage src={p.image_url} alt={p.title} className="h-28" /></div>
                      <Link href={`/discovery/products/${encodeURIComponent(p.id)}`} className="line-clamp-2 text-sm font-semibold hover:text-primary">{p.title}</Link>
                      <div className="flex flex-wrap items-center gap-2"><StockBadge inStock={p.in_stock} /><Rating ratings={p.ratings} /></div>
                      {p.url && <a href={p.url} target="_blank" rel="noopener noreferrer sponsored" className="inline-flex items-center gap-0.5 text-xs font-medium text-primary hover:underline">
                        View at {p.retailer} <ArrowUpRight className="h-3 w-3" /></a>}
                    </div>
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {data.matrix.rows.map((row) => (
                <tr key={row.key} className="align-top">
                  <th scope="row" className="border-t border-border p-2 text-left text-xs font-medium text-muted-foreground">{row.label}</th>
                  {row.values.map((value, i) => {
                    const p = data.products[i];
                    return (
                      <td key={`${row.key}-${p.id}`} className={cn("border-t border-border p-2 text-xs", p.id === overallId && "bg-primary/5")}>
                        {value == null || (Array.isArray(value) && value.length === 0) ? (
                          <span className="italic text-muted-foreground">Not listed</span>
                        ) : Array.isArray(value) ? (
                          <ul className="space-y-0.5">{value.map((v) => <li key={v}>• {v}</li>)}</ul>
                        ) : row.kind === "money" ? (
                          <span className="font-semibold tabular-nums">{formatPrice(value, p.currency)}</span>
                        ) : (
                          <span>{String(value)}</span>
                        )}
                      </td>
                    );
                  })}
                </tr>
              ))}
            </tbody>
          </table>
        </CardContent>
      </Card>
      <ul className="space-y-0.5 text-2xs text-muted-foreground">{data.notes.map((n) => <li key={n}>{n}</li>)}</ul>
    </div>
  );
}

export default function ComparePage() {
  return (
    <React.Suspense fallback={<LoadingCard lines={8} />}>
      <CompareView />
    </React.Suspense>
  );
}
