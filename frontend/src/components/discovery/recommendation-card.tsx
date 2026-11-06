"use client";

/**
 * One AI recommendation: what was detected, the evidence, the estimated impact (labelled
 * as an estimate, with its assumptions), the confidence and why, the lifecycle it is in,
 * and the controls a human uses to move it on. Nothing here moves money: buying test
 * stock raises a separate payment approval, paid from Payment Management.
 */

import {
  BarChart3,
  Check,
  ChevronDown,
  CircleDashed,
  ClipboardCheck,
  CreditCard,
  ExternalLink,
  Gauge,
  PackagePlus,
  Rocket,
  ShieldCheck,
  Tag,
  X,
} from "lucide-react";
import Link from "next/link";
import * as React from "react";

import { AiBadge, EstimateBadge, ProductImage, SourceTag, formatPrice } from "@/components/discovery/shared";
import { StatusPill } from "@/components/supply/shared";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/overlays";
import { Badge, Card, CardContent, Input, Label, Textarea } from "@/components/ui/primitives";
import { useRecommendationAction, useRequestPurchase } from "@/hooks/use-discovery";
import { cn, formatRelativeTime, toNumber } from "@/lib/utils";
import type { Recommendation } from "@/types/discovery";

const STAGE_LABEL: Record<string, string> = {
  DETECTED: "Detected", ANALYZED: "Analyzed", RECOMMENDED: "Recommended", APPROVED: "Approved",
  EXECUTED: "Executed", MEASURED: "Measured",
};

const KIND_ICON = { ASSORTMENT_EXPANSION: PackagePlus, PRODUCT_ALTERNATIVE: Rocket, PRICING_OPPORTUNITY: Tag } as const;

export function LifecycleTrack({ rec }: { rec: Recommendation }) {
  const rejected = rec.status === "REJECTED";
  return (
    <ol className="flex flex-wrap items-center gap-1.5" aria-label="Recommendation lifecycle">
      {rec.stages.map((stage, i) => {
        const current = stage.status === rec.status;
        return (
          <li key={stage.status} className="flex items-center gap-1.5">
            <span title={stage.note ?? undefined}
              className={cn(
                "inline-flex items-center gap-1 rounded-full border px-2 py-0.5 text-2xs font-medium",
                stage.reached && !current && "border-success/30 bg-success/10 text-success",
                current && !rejected && "border-primary/40 bg-primary/10 text-primary",
                !stage.reached && "border-border text-muted-foreground",
              )}>
              {stage.reached ? <Check className="h-3 w-3" /> : <CircleDashed className="h-3 w-3" />}
              {STAGE_LABEL[stage.status]}
            </span>
            {i < rec.stages.length - 1 && <span className="h-px w-3 bg-border" />}
          </li>
        );
      })}
      {rejected && <StatusPill status="REJECTED" className="ml-1" />}
    </ol>
  );
}

function ConfidenceMeter({ value, reasons }: { value: number; reasons: string[] }) {
  const pctValue = Math.round(value * 100);
  const tone = pctValue >= 75 ? "bg-success" : pctValue >= 55 ? "bg-primary" : "bg-warning";
  return (
    <div className="space-y-1.5">
      <div className="flex items-center justify-between text-2xs">
        <span className="font-medium uppercase tracking-wide text-muted-foreground">Confidence</span>
        <span className="font-semibold tabular-nums">{pctValue}%</span>
      </div>
      <div className="h-1.5 overflow-hidden rounded-full bg-muted">
        <div className={cn("h-full rounded-full", tone)} style={{ width: `${pctValue}%` }} />
      </div>
      <ul className="space-y-0.5 text-2xs text-muted-foreground">
        {reasons.map((r) => <li key={r}>• {r}</li>)}
      </ul>
    </div>
  );
}

export function RecommendationCard({
  rec,
  canDecide,
  canPay,
  defaultOpen = false,
}: {
  rec: Recommendation;
  canDecide: boolean;
  canPay?: boolean;
  defaultOpen?: boolean;
}) {
  const [open, setOpen] = React.useState(defaultOpen);
  const [decision, setDecision] = React.useState<"approve" | "reject" | null>(null);
  const [executing, setExecuting] = React.useState(false);
  const [purchasing, setPurchasing] = React.useState(false);
  const action = useRecommendationAction();
  const Icon = KIND_ICON[rec.kind] ?? PackagePlus;
  const impact = rec.expected_impact ?? {};
  const isProduct = rec.kind !== "PRICING_OPPORTUNITY";
  const purchaseRef = rec.execution?.purchase_approval_reference;
  const busy = action.isPending && action.variables?.id === rec.id;

  return (
    <Card className={cn("overflow-hidden", rec.status === "RECOMMENDED" && "border-primary/30")}>
      <CardContent className="space-y-4 p-5">
        <div className="flex flex-wrap items-start gap-3">
          <span className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-primary/10 text-primary">
            <Icon className="h-5 w-5" />
          </span>
          <div className="min-w-0 flex-1 space-y-1">
            <div className="flex flex-wrap items-center gap-1.5">
              <Badge variant="muted" className="normal-case tracking-normal">{rec.kind_label}</Badge>
              <span className="font-mono text-2xs text-muted-foreground">{rec.reference}</span>
              <StatusPill status={rec.status} />
              {rec.narrative_source === "llm" && <AiBadge label="AI-written summary" />}
            </div>
            <h3 className="text-base font-semibold leading-snug">{rec.title}</h3>
            <p className="text-sm text-muted-foreground">{rec.description}</p>
          </div>
          <div className="w-full shrink-0 rounded-xl border border-border bg-muted/30 p-3 sm:w-56">
            <div className="flex items-center justify-between gap-2">
              <p className="text-2xs font-medium uppercase tracking-wide text-muted-foreground">Expected impact</p>
              {impact.is_estimate && <EstimateBadge />}
            </div>
            <p className="mt-1 text-xl font-semibold tabular-nums">
              {impact.value != null ? formatPrice(impact.value, impact.currency ?? rec.currency) : "Measured after launch"}
            </p>
            <p className="text-2xs text-muted-foreground">
              {impact.metric === "monthly_revenue_change" ? "revenue change / month" : impact.metric === "monthly_revenue" ? "revenue / month" : ""}
              {impact.units_per_month ? ` · ~${Number(impact.units_per_month).toFixed(1)} units` : ""}
            </p>
          </div>
        </div>

        <LifecycleTrack rec={rec} />

        <div className="rounded-xl border border-primary/20 bg-primary/5 p-3 text-sm">
          <p className="text-2xs font-semibold uppercase tracking-wide text-primary">Recommended action</p>
          <p className="mt-0.5">{rec.recommended_action}</p>
          {rec.suggested_test_quantity != null && (
            <p className="mt-1 text-2xs text-muted-foreground">
              Suggested test quantity: <span className="font-medium text-foreground">{rec.suggested_test_quantity} units</span> (estimate from your buyer count and an assumed attach rate)
            </p>
          )}
        </div>

        {rec.products.length > 0 && (
          <div className="grid gap-2 sm:grid-cols-3">
            {rec.products.slice(0, 3).map((p) => (
              <Link key={p.id} href={`/discovery/products/${encodeURIComponent(p.id)}`}
                className="flex items-center gap-2 rounded-lg border border-border p-2 transition-colors hover:border-primary/40 hover:bg-muted/40">
                <ProductImage src={p.image_url} alt={p.title} className="h-12 w-12 shrink-0 rounded-md" />
                <div className="min-w-0">
                  <p className="line-clamp-2 text-xs font-medium leading-tight">{p.title}</p>
                  <p className="text-2xs text-muted-foreground">{formatPrice(p.price, p.currency ?? rec.currency)}{p.retailer ? ` · ${p.retailer}` : ""}</p>
                </div>
              </Link>
            ))}
          </div>
        )}

        <button type="button" onClick={() => setOpen((o) => !o)} aria-expanded={open}
          className="flex items-center gap-1 text-xs font-medium text-primary hover:underline">
          <ChevronDown className={cn("h-3.5 w-3.5 transition-transform", open && "rotate-180")} />
          {open ? "Hide" : "Show"} evidence, assumptions and history
        </button>
        {open && (
          <div className="grid gap-4 lg:grid-cols-3">
            <div className="space-y-2 lg:col-span-1">
              <p className="flex items-center gap-1 text-2xs font-semibold uppercase tracking-wide text-muted-foreground"><BarChart3 className="h-3 w-3" /> Supporting evidence</p>
              <dl className="space-y-1.5 text-xs">
                {rec.evidence.map((e) => (
                  <div key={e.label} className="flex items-start justify-between gap-2 border-b border-border/60 pb-1">
                    <dt className="text-muted-foreground">{e.label}<br /><SourceTag source={e.source} /></dt>
                    <dd className="text-right font-medium tabular-nums">{String(e.value)}</dd>
                  </div>
                ))}
              </dl>
            </div>
            <div className="space-y-3">
              <ConfidenceMeter value={rec.confidence} reasons={rec.confidence_reasons} />
              {impact.assumptions && impact.assumptions.length > 0 && (
                <div className="space-y-1">
                  <p className="text-2xs font-semibold uppercase tracking-wide text-muted-foreground">How the estimate is built</p>
                  <ul className="space-y-0.5 text-2xs text-muted-foreground">{impact.assumptions.map((a) => <li key={a}>• {a}</li>)}</ul>
                </div>
              )}
            </div>
            <div className="space-y-1.5">
              <p className="flex items-center gap-1 text-2xs font-semibold uppercase tracking-wide text-muted-foreground"><Gauge className="h-3 w-3" /> Lifecycle log</p>
              <ol className="space-y-1.5 border-l border-border pl-3 text-2xs">
                {rec.lifecycle.map((entry, i) => (
                  <li key={`${entry.status}-${i}`}>
                    <span className="font-semibold">{STAGE_LABEL[entry.status] ?? entry.status}</span>{" "}
                    <span className="text-muted-foreground">· {entry.actor} · {formatRelativeTime(entry.at)}</span>
                    <p className="text-muted-foreground">{entry.note}</p>
                  </li>
                ))}
              </ol>
              {Object.keys(rec.measurement ?? {}).length > 0 && (
                <div className="mt-2 rounded-lg bg-muted/50 p-2 text-2xs">
                  <p className="font-semibold">Measurement</p>
                  <p className="text-muted-foreground">{String(rec.measurement.verdict ?? "")}</p>
                </div>
              )}
            </div>
          </div>
        )}

        <div className="flex flex-wrap items-center gap-2 border-t border-border pt-3">
          {rec.status === "RECOMMENDED" && (
            canDecide ? (
              <>
                <Button size="sm" className="gap-1.5" onClick={() => setDecision("approve")}><Check className="h-4 w-4" /> Approve</Button>
                <Button size="sm" variant="outline" className="gap-1.5" onClick={() => setDecision("reject")}><X className="h-4 w-4" /> Reject</Button>
              </>
            ) : (
              <span className="inline-flex items-center gap-1 text-xs text-muted-foreground"><ShieldCheck className="h-3.5 w-3.5" /> Waiting for someone with procurement approval</span>
            )
          )}
          {rec.status === "APPROVED" && canDecide && (
            <Button size="sm" className="gap-1.5" onClick={() => setExecuting(true)}>
              <Rocket className="h-4 w-4" /> {isProduct ? "Add to catalog" : "Apply price test"}
            </Button>
          )}
          {isProduct && ["APPROVED", "EXECUTED", "MEASURED"].includes(rec.status) && !purchaseRef && canPay !== false && (
            <Button size="sm" variant="outline" className="gap-1.5" onClick={() => setPurchasing(true)}>
              <CreditCard className="h-4 w-4" /> Buy test stock via PayPal
            </Button>
          )}
          {["EXECUTED", "MEASURED"].includes(rec.status) && (
            <Button size="sm" variant="outline" className="gap-1.5" loading={busy && action.variables?.action === "measure"}
              onClick={() => action.mutate({ id: rec.id, action: "measure" })}>
              <BarChart3 className="h-4 w-4" /> {rec.status === "MEASURED" ? "Re-measure" : "Measure results"}
            </Button>
          )}
          {purchaseRef && (
            <Link href="/finance/payment-management" className="inline-flex items-center gap-1 text-xs font-medium text-primary hover:underline">
              <ClipboardCheck className="h-3.5 w-3.5" /> Payment {purchaseRef}
              {rec.execution?.purchase_status ? ` · ${rec.execution.purchase_status.toLowerCase().replace(/_/g, " ")}` : ""}
              <ExternalLink className="h-3 w-3" />
            </Link>
          )}
          <span className="ml-auto text-2xs text-muted-foreground">
            {rec.decided_by ? `Decided by ${rec.decided_by.split(" <")[0]} ${formatRelativeTime(rec.decided_at)}` : `Updated ${formatRelativeTime(rec.updated_at)}`}
          </span>
        </div>
      </CardContent>

      <DecisionNoteDialog open={decision !== null} approve={decision === "approve"} title={rec.title} pending={busy}
        onClose={() => setDecision(null)}
        onConfirm={(note) => action.mutate({ id: rec.id, action: decision === "approve" ? "approve" : "reject", note },
          { onSuccess: () => setDecision(null) })} />
      <ExecuteDialog open={executing} rec={rec} pending={busy} onClose={() => setExecuting(false)}
        onConfirm={(price) => action.mutate({ id: rec.id, action: "execute", retailPrice: price }, { onSuccess: () => setExecuting(false) })} />
      <PurchaseDialog open={purchasing} rec={rec} onClose={() => setPurchasing(false)} />
    </Card>
  );
}

function DecisionNoteDialog({ open, approve, title, pending, onClose, onConfirm }: {
  open: boolean; approve: boolean; title: string; pending: boolean; onClose: () => void; onConfirm: (note: string) => void;
}) {
  const [note, setNote] = React.useState("");
  React.useEffect(() => { if (open) setNote(""); }, [open]);
  return (
    <Dialog open={open} onOpenChange={(next) => !next && onClose()}>
      <DialogContent className="max-w-md">
        <DialogHeader>
          <DialogTitle>{approve ? "Approve recommendation" : "Reject recommendation"}</DialogTitle>
          <DialogDescription>
            {title}. {approve ? "Approving lets you execute it. No money moves - buying stock needs its own payment approval."
              : "The agents will treat this as a signal and not re-propose it without new evidence."}
          </DialogDescription>
        </DialogHeader>
        <div className="space-y-1.5">
          <Label htmlFor="rec-note">Note (recorded in the audit trail)</Label>
          <Textarea id="rec-note" rows={3} value={note} onChange={(e) => setNote(e.target.value)} />
        </div>
        <DialogFooter>
          <Button variant="outline" onClick={onClose} disabled={pending}>Cancel</Button>
          <Button variant={approve ? "default" : "destructive"} loading={pending} onClick={() => onConfirm(note)}>
            {approve ? "Approve" : "Reject"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

function ExecuteDialog({ open, rec, pending, onClose, onConfirm }: {
  open: boolean; rec: Recommendation; pending: boolean; onClose: () => void; onConfirm: (price: number | null) => void;
}) {
  const [price, setPrice] = React.useState("");
  React.useEffect(() => { if (open) setPrice(rec.suggested_retail_price ?? ""); }, [open, rec.suggested_retail_price]);
  const isPricing = rec.kind === "PRICING_OPPORTUNITY";
  const value = toNumber(price);
  return (
    <Dialog open={open} onOpenChange={(next) => !next && onClose()}>
      <DialogContent className="max-w-md">
        <DialogHeader>
          <DialogTitle>{isPricing ? "Apply the price test" : "Add the product to your catalog"}</DialogTitle>
          <DialogDescription>
            {isPricing
              ? `Changes the selling price of ${rec.anchor_product.name}. Measure it after two weeks; you can change it back at any time.`
              : `Creates a catalog product from ${rec.products[0]?.title ?? "the recommended product"} so its sales can be measured. Nothing is purchased.`}
          </DialogDescription>
        </DialogHeader>
        <div className="space-y-1.5">
          <Label htmlFor="exec-price">{isPricing ? "New selling price" : "Your retail price"} ({rec.currency})</Label>
          <Input id="exec-price" inputMode="decimal" value={price} onChange={(e) => setPrice(e.target.value)} />
          {!isPricing && rec.suggested_retail_price && (
            <p className="text-2xs text-muted-foreground">Prefilled with the median retail price of the top Channel3 picks - set your own.</p>
          )}
        </div>
        <DialogFooter>
          <Button variant="outline" onClick={onClose} disabled={pending}>Cancel</Button>
          <Button loading={pending} disabled={!value || value <= 0} onClick={() => onConfirm(value)}>Confirm</Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

function PurchaseDialog({ open, rec, onClose }: { open: boolean; rec: Recommendation; onClose: () => void }) {
  const purchase = useRequestPurchase();
  const [quantity, setQuantity] = React.useState("");
  const [unitCost, setUnitCost] = React.useState("");
  const [payee, setPayee] = React.useState("");
  React.useEffect(() => {
    if (open) {
      setQuantity(String(rec.suggested_test_quantity ?? 6));
      setUnitCost("");
      setPayee("");
    }
  }, [open, rec.suggested_test_quantity]);
  const qty = toNumber(quantity) ?? 0;
  const cost = toNumber(unitCost) ?? 0;
  const total = qty * cost;
  const valid = qty >= 1 && cost > 0 && /.+@.+\..+/.test(payee);
  const product = rec.products[0];
  return (
    <Dialog open={open} onOpenChange={(next) => !next && onClose()}>
      <DialogContent className="max-w-lg">
        <DialogHeader>
          <DialogTitle>Request a test-stock purchase</DialogTitle>
          <DialogDescription>
            Creates a payment approval bound to these exact terms. After someone with payment approval says yes, you create
            the PayPal order, the payer approves it in PayPal, and you capture it - three human steps.
          </DialogDescription>
        </DialogHeader>
        <div className="grid gap-3 sm:grid-cols-2">
          <div className="space-y-1.5">
            <Label htmlFor="p-qty">Quantity</Label>
            <Input id="p-qty" inputMode="numeric" value={quantity} onChange={(e) => setQuantity(e.target.value)} />
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="p-cost">Supplier unit cost ({rec.currency})</Label>
            <Input id="p-cost" inputMode="decimal" placeholder="e.g. 9.50" value={unitCost} onChange={(e) => setUnitCost(e.target.value)} />
          </div>
          <div className="space-y-1.5 sm:col-span-2">
            <Label htmlFor="p-payee">Supplier PayPal email</Label>
            <Input id="p-payee" type="email" placeholder="supplier@business.example.com" value={payee} onChange={(e) => setPayee(e.target.value)} />
          </div>
        </div>
        <div className="rounded-xl border border-border bg-muted/40 p-3 text-xs">
          <p className="font-medium">{product?.title ?? rec.title}</p>
          <p className="text-muted-foreground">
            Retail reference {formatPrice(product?.price ?? rec.suggested_retail_price, rec.currency)} (Channel3) is what shoppers pay -
            enter your supplier&apos;s wholesale cost, not the retail price.
          </p>
          <p className="mt-2 text-base font-semibold tabular-nums">Total {formatPrice(total || null, rec.currency)}</p>
        </div>
        <DialogFooter>
          <Button variant="outline" onClick={onClose} disabled={purchase.isPending}>Cancel</Button>
          <Button loading={purchase.isPending} disabled={!valid}
            onClick={() => purchase.mutate({ id: rec.id, quantity: qty, unit_cost: cost, payee_email: payee.trim() }, { onSuccess: onClose })}>
            Send for payment approval
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
