"use client";

/** Building blocks shared by the Product Discovery and Supply Intelligence screens. */

import { CheckCircle2, Copy, KeyRound, PackageSearch, Sparkles, Star, XCircle } from "lucide-react";
import * as React from "react";
import { toast } from "sonner";

import { Badge, Card, CardContent } from "@/components/ui/primitives";
import { cn, toNumber } from "@/lib/utils";

const FORMATTERS = new Map<string, Intl.NumberFormat>();

/** A price in whatever currency Channel3 returned (never assumes USD). */
export function formatPrice(value: string | number | null | undefined, currency = "USD"): string {
  const n = toNumber(value);
  if (n == null) return "--";
  const code = (currency || "USD").toUpperCase();
  let fmt = FORMATTERS.get(code);
  if (!fmt) {
    try {
      fmt = new Intl.NumberFormat("en-US", { style: "currency", currency: code, minimumFractionDigits: 2, maximumFractionDigits: 2 });
    } catch {
      fmt = new Intl.NumberFormat("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
    }
    FORMATTERS.set(code, fmt);
  }
  return fmt.format(n);
}

/** Marks content written or ranked by a model, so it is never mistaken for a measured fact. */
export function AiBadge({ label = "AI-generated", className }: { label?: string; className?: string }) {
  return (
    <span className={cn("inline-flex items-center gap-1 rounded-md bg-primary/10 px-1.5 py-0.5 text-2xs font-semibold text-primary", className)}
      title="Written or ranked by PayPilot's AI from the facts shown. Figures come from your data or Channel3.">
      <Sparkles className="h-3 w-3" aria-hidden />
      {label}
    </span>
  );
}

export function LiveBadge({ className }: { className?: string }) {
  return (
    <Badge variant="success" className={cn("normal-case tracking-normal", className)}>
      <span className="h-1.5 w-1.5 rounded-full bg-success" aria-hidden /> Live Channel3 data
    </Badge>
  );
}

export function EstimateBadge() {
  return <Badge variant="warning" className="normal-case tracking-normal">Estimate</Badge>;
}

export function StockBadge({ inStock }: { inStock: boolean | null | undefined }) {
  if (inStock == null) return <span className="text-2xs text-muted-foreground">Stock not reported</span>;
  return inStock ? (
    <span className="inline-flex items-center gap-1 text-2xs font-medium text-success"><CheckCircle2 className="h-3 w-3" />In stock</span>
  ) : (
    <span className="inline-flex items-center gap-1 text-2xs font-medium text-destructive"><XCircle className="h-3 w-3" />Out of stock</span>
  );
}

export function Rating({ ratings }: { ratings: { value: number; count: number } | null | undefined }) {
  if (!ratings) return null;
  return (
    <span className="inline-flex items-center gap-1 text-2xs text-muted-foreground" title="Rating reported by Channel3">
      <Star className="h-3 w-3 fill-warning text-warning" aria-hidden />
      <span className="font-medium text-foreground">{ratings.value.toFixed(1)}</span>
      ({ratings.count.toLocaleString("en-US")})
    </span>
  );
}

export function ScoreRing({ score, size = 40 }: { score: number; size?: number }) {
  const r = (size - 6) / 2;
  const circumference = 2 * Math.PI * r;
  const tone = score >= 80 ? "text-success" : score >= 60 ? "text-primary" : "text-warning";
  return (
    <div className="relative shrink-0" style={{ width: size, height: size }} title={`Match score ${score}/100`}>
      <svg width={size} height={size} className="-rotate-90">
        <circle cx={size / 2} cy={size / 2} r={r} className="stroke-muted" strokeWidth={4} fill="none" />
        <circle cx={size / 2} cy={size / 2} r={r} className={cn("stroke-current transition-all", tone)} strokeWidth={4} fill="none"
          strokeDasharray={circumference} strokeDashoffset={circumference * (1 - Math.min(score, 100) / 100)} strokeLinecap="round" />
      </svg>
      <span className="absolute inset-0 flex items-center justify-center text-2xs font-semibold tabular-nums">{Math.round(score)}</span>
    </div>
  );
}

export function ProductImage({ src, alt, className }: { src?: string | null; alt: string; className?: string }) {
  const [failed, setFailed] = React.useState(false);
  if (!src || failed) {
    return (
      <div className={cn("flex items-center justify-center bg-muted/40", className)}>
        <PackageSearch className="h-8 w-8 text-muted-foreground" aria-hidden />
      </div>
    );
  }
  return (
    // Retailer images on Channel3's CDN; a plain <img> keeps arbitrary hosts working.
    // eslint-disable-next-line @next/next/no-img-element
    <img src={src} alt={alt} loading="lazy" onError={() => setFailed(true)}
      className={cn("h-full w-full bg-white object-contain p-2", className)} />
  );
}

/** Shown instead of an error when CHANNEL3_API_KEY is missing - discovery never fakes products. */
export function Channel3Setup({ compact = false }: { compact?: boolean }) {
  const copy = (text: string) => {
    void navigator.clipboard?.writeText(text).then(() => toast.success("Copied"), () => undefined);
  };
  return (
    <Card className="border-warning/40">
      <CardContent className={cn("flex gap-4", compact ? "p-4" : "p-6")}>
        <span className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-warning/14 text-warning">
          <KeyRound className="h-5 w-5" />
        </span>
        <div className="min-w-0 space-y-2 text-sm">
          <p className="font-semibold">Connect Channel3 to discover live products</p>
          <p className="text-muted-foreground">
            Product Discovery and Supply Intelligence search Channel3&apos;s live catalog of products from thousands of
            retailers. PayPilot never shows invented products, so these features stay off until a key is configured.
          </p>
          {!compact && (
            <ol className="list-decimal space-y-1 pl-5 text-muted-foreground">
              <li>Create a free API key at <a className="font-medium text-primary hover:underline" href="https://trychannel3.com/developers" target="_blank" rel="noreferrer">trychannel3.com/developers</a>.</li>
              <li>
                Add it to <code className="rounded bg-muted px-1">.env</code>:{" "}
                <button type="button" onClick={() => copy("CHANNEL3_API_KEY=")} className="inline-flex items-center gap-1 rounded bg-muted px-1.5 font-mono text-xs hover:bg-muted/70">
                  CHANNEL3_API_KEY=… <Copy className="h-3 w-3" />
                </button>
              </li>
              <li>Restart the backend (<code className="rounded bg-muted px-1">make backend</code>). The key stays on the server.</li>
            </ol>
          )}
        </div>
      </CardContent>
    </Card>
  );
}

export function SourceTag({ source }: { source: string }) {
  const tone = source === "Channel3" ? "text-primary" : source.startsWith("Your") ? "text-success" : "text-muted-foreground";
  return <span className={cn("text-2xs font-medium", tone)}>{source}</span>;
}
