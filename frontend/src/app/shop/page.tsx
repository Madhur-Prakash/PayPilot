"use client";

/**
 * The customer's view of Juniper & Oak's online store - public, no sign-in.
 *
 * This is where PayPilot's loop starts for real: a customer pays with PayPal, and that
 * sale (not a seeded dataset) is what drops the stock, raises the low-stock event and
 * puts the restock on the merchant's Reorder screen. The server prices the cart; the
 * browser only says which product and how many.
 */

import { useQuery } from "@tanstack/react-query";
import { Coffee, Loader2, Minus, Plus, ShieldCheck } from "lucide-react";
import { useRouter, useSearchParams } from "next/navigation";
import * as React from "react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import { Badge, Card, CardContent } from "@/components/ui/primitives";
import { SHOP_SLUG, shopApi } from "@/lib/api/shop";
import { formatMoney } from "@/lib/utils";

function newKey(): string {
  return `c-${Math.random().toString(36).slice(2, 10)}${Date.now().toString(36)}`;
}

function ShopInner() {
  const router = useRouter();
  const params = useSearchParams();
  const catalog = useQuery({ queryKey: ["shop", SHOP_SLUG], queryFn: () => shopApi.catalog(SHOP_SLUG), staleTime: 15_000 });

  const [qty, setQty] = React.useState(2);
  const [paying, setPaying] = React.useState(false);
  // One key per cart state: a double click returns the same PayPal order, not two.
  const clientKey = React.useRef(newKey());
  React.useEffect(() => { clientKey.current = newKey(); }, [qty]);

  const product = catalog.data?.products[0];
  const total = product ? Number(product.price) * qty : 0;
  const max = Math.max(1, Math.min(catalog.data?.max_quantity ?? 10, product?.available ?? 10));

  async function checkout() {
    if (!product) return;
    setPaying(true);
    try {
      const order = await shopApi.createOrder(SHOP_SLUG, [{ product_id: product.id, quantity: qty }], clientKey.current);
      if (order.needs_payer_approval && order.approve_url) {
        window.location.href = order.approve_url; // PayPal, then back to /shop/return
      } else {
        router.push(`/shop/return?shop=${SHOP_SLUG}&token=${encodeURIComponent(order.order_id)}`); // simulated payer
      }
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Could not start the PayPal checkout.");
      setPaying(false);
    }
  }

  return (
    <main className="mx-auto flex min-h-screen max-w-3xl flex-col gap-6 px-4 py-10">
      <header className="flex items-center gap-3">
        <div className="flex h-11 w-11 items-center justify-center rounded-xl bg-primary text-primary-foreground">
          <Coffee className="h-5 w-5" />
        </div>
        <div>
          <h1 className="text-xl font-semibold leading-tight">{catalog.data?.merchant.name ?? "Juniper & Oak Coffee"}</h1>
          <p className="text-sm text-muted-foreground">Online store{catalog.data?.merchant.city ? ` · ${catalog.data.merchant.city}` : ""}</p>
        </div>
        {catalog.data && (
          <Badge variant="outline" className="ml-auto gap-1">
            <ShieldCheck className="h-3 w-3" /> PayPal {catalog.data.mode.toLowerCase()}
          </Badge>
        )}
      </header>

      {params.get("cancelled") && (
        <div className="rounded-lg border border-warning/40 bg-warning/10 px-4 py-3 text-sm">
          Payment cancelled - nothing was charged.
        </div>
      )}

      {catalog.isLoading && (
        <div className="flex items-center gap-2 text-sm text-muted-foreground"><Loader2 className="h-4 w-4 animate-spin" /> Loading the shop…</div>
      )}
      {catalog.error && (
        <div className="rounded-lg border border-destructive/40 bg-destructive/10 px-4 py-3 text-sm">
          The shop is not available right now. If it was asleep, give it a moment and refresh.
        </div>
      )}

      {product && (
        <Card>
          <CardContent className="grid gap-6 p-6 sm:grid-cols-[160px_1fr]">
            <div className="flex h-40 items-center justify-center rounded-xl bg-muted">
              {product.image_url
                ? /* eslint-disable-next-line @next/next/no-img-element */ <img src={product.image_url} alt={product.name} className="h-full w-full rounded-xl object-cover" />
                : <Coffee className="h-14 w-14 text-muted-foreground" />}
            </div>
            <div className="flex flex-col gap-3">
              <div>
                <h2 className="text-lg font-semibold">{product.name}</h2>
                <p className="mt-1 text-sm text-muted-foreground">{product.description}</p>
              </div>
              <div className="flex items-baseline gap-3">
                <span className="text-2xl font-semibold">{formatMoney(Number(product.price))}</span>
                {product.available != null && (
                  <span className={product.available <= 10 ? "text-sm font-medium text-warning" : "text-sm text-muted-foreground"}>
                    {product.available > 0 ? `${product.available} in stock` : "Sold out"}
                  </span>
                )}
              </div>

              <div className="flex items-center gap-3">
                <span className="text-sm text-muted-foreground">Quantity</span>
                <div className="flex items-center rounded-lg border">
                  <Button variant="ghost" size="icon" aria-label="Fewer" disabled={qty <= 1 || paying} onClick={() => setQty((q) => Math.max(1, q - 1))}>
                    <Minus className="h-4 w-4" />
                  </Button>
                  <span className="w-8 text-center text-sm font-medium tabular-nums">{qty}</span>
                  <Button variant="ghost" size="icon" aria-label="More" disabled={qty >= max || paying} onClick={() => setQty((q) => Math.min(max, q + 1))}>
                    <Plus className="h-4 w-4" />
                  </Button>
                </div>
              </div>

              <div className="mt-1 flex flex-wrap items-center gap-3">
                <Button size="lg" loading={paying} disabled={!product.in_stock} onClick={() => void checkout()}>
                  Pay {formatMoney(total)} with PayPal
                </Button>
                <span className="text-xs text-muted-foreground">You approve the payment on PayPal, then come back here.</span>
              </div>
            </div>
          </CardContent>
        </Card>
      )}

      {catalog.data && <p className="text-xs text-muted-foreground">{catalog.data.note}</p>}
    </main>
  );
}

export default function ShopPage() {
  return (
    <React.Suspense fallback={null}>
      <ShopInner />
    </React.Suspense>
  );
}
