"use client";

/**
 * Where PayPal sends the customer back. Captures the approved order and shows the sale
 * landing: the receipt for the customer, and - because this is a demo of the whole loop -
 * what it just did inside PayPilot (the stock drop and the events it raised).
 */

import { CheckCircle2, Loader2, XCircle } from "lucide-react";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import * as React from "react";

import { Button } from "@/components/ui/button";
import { Badge, Card, CardContent } from "@/components/ui/primitives";
import { type ShopSale, SHOP_SLUG, shopApi } from "@/lib/api/shop";
import { formatMoney } from "@/lib/utils";

function ReturnInner() {
  const params = useSearchParams();
  const orderId = params.get("token") ?? "";
  const shop = params.get("shop") ?? SHOP_SLUG;

  const [sale, setSale] = React.useState<ShopSale | null>(null);
  const [error, setError] = React.useState<string | null>(null);
  const started = React.useRef(false);

  const capture = React.useCallback(async () => {
    setError(null);
    try {
      setSale(await shopApi.capture(shop, orderId));
    } catch (err) {
      setError(err instanceof Error ? err.message : "We could not confirm the payment.");
    }
  }, [shop, orderId]);

  React.useEffect(() => {
    if (started.current || !orderId) return; // React strict mode runs effects twice; capture once
    started.current = true;
    void capture();
  }, [capture, orderId]);

  if (!orderId) {
    return <Shell><p className="text-sm">This page is where PayPal sends you after you pay. <Link className="text-primary underline" href="/shop">Back to the shop</Link></p></Shell>;
  }
  if (error) {
    return (
      <Shell>
        <div className="flex items-start gap-3">
          <XCircle className="mt-0.5 h-5 w-5 text-destructive" />
          <div className="space-y-3">
            <p className="font-medium">We could not confirm your payment.</p>
            <p className="text-sm text-muted-foreground">{error}</p>
            <div className="flex gap-2">
              <Button size="sm" onClick={() => { started.current = true; void capture(); }}>Try again</Button>
              <Button size="sm" variant="outline" asChild><Link href="/shop">Back to the shop</Link></Button>
            </div>
          </div>
        </div>
      </Shell>
    );
  }
  if (!sale) {
    return <Shell><div className="flex items-center gap-2 text-sm text-muted-foreground"><Loader2 className="h-4 w-4 animate-spin" /> Confirming your PayPal payment…</div></Shell>;
  }

  const crossed = sale.stock.some((s) => s.crossed_reorder_point);
  return (
    <Shell>
      <div className="space-y-6">
        <div className="flex items-start gap-3">
          <CheckCircle2 className="mt-0.5 h-6 w-6 text-success" />
          <div>
            <h1 className="text-xl font-semibold">Thank you - payment received</h1>
            <p className="text-sm text-muted-foreground">
              {formatMoney(Number(sale.total))} paid with PayPal{sale.mode ? ` (${sale.mode.toLowerCase()})` : ""}.
            </p>
          </div>
        </div>

        <dl className="grid gap-x-6 gap-y-2 text-sm sm:grid-cols-2">
          {sale.items.map((i) => (
            <div key={i.name} className="flex justify-between sm:col-span-2">
              <dt>{i.quantity} × {i.name}</dt>
              <dd className="tabular-nums">{formatMoney(Number(i.unit_price) * i.quantity)}</dd>
            </div>
          ))}
          <div className="flex justify-between"><dt className="text-muted-foreground">Order</dt><dd className="font-mono text-xs">{sale.order_ref}</dd></div>
          <div className="flex justify-between"><dt className="text-muted-foreground">PayPal capture</dt><dd className="font-mono text-xs">{sale.capture_id ?? "-"}</dd></div>
        </dl>

        <div className="rounded-xl border bg-muted/40 p-4">
          <div className="mb-2 flex items-center gap-2">
            <p className="text-sm font-semibold">What just happened inside PayPilot</p>
            <Badge variant="outline">{sale.recorded_now ? "just now" : "already recorded"}</Badge>
          </div>
          <ul className="space-y-1.5 text-sm">
            <li>The sale was recorded as an online-store transaction from this PayPal capture.</li>
            {sale.stock.map((s) => (
              <li key={s.sku}>
                <strong>{s.name}</strong>: {s.on_hand_before} → <strong>{s.on_hand_after}</strong> in stock
                {s.oversold ? " (oversold - flagged for the merchant)" : ""}.
              </li>
            ))}
            {crossed && <li>That crossed the reorder point, so a <strong>low-stock event</strong> was raised.</li>}
            <li>The Command Center, the Reorder screen and the agents now see the lower stock.</li>
          </ul>
          <div className="mt-3 flex flex-wrap gap-2">
            <Button size="sm" asChild><Link href="/supply/reorder">Open the merchant&apos;s Reorder screen</Link></Button>
            <Button size="sm" variant="outline" asChild><Link href="/shop">Back to the shop</Link></Button>
          </div>
          <p className="mt-2 text-xs text-muted-foreground">The merchant screens ask you to sign in (owner@juniperoak.com).</p>
        </div>
      </div>
    </Shell>
  );
}

function Shell({ children }: { children: React.ReactNode }) {
  return (
    <main className="mx-auto flex min-h-screen max-w-2xl items-start px-4 py-12">
      <Card className="w-full"><CardContent className="p-6">{children}</CardContent></Card>
    </main>
  );
}

export default function ShopReturnPage() {
  return (
    <React.Suspense fallback={null}>
      <ReturnInner />
    </React.Suspense>
  );
}
