"use client";

/**
 * Negotiation Workspace - the signature screen.
 *
 * Three independent supplier agents negotiate with the Buyer Agent, live. The
 * merchant's limits come from the deterministic engine (never from AI), every
 * offer shows the backend's verdict, the conversation is a log of signed protocol
 * messages, and nothing is bought until a person approves the exact terms.
 */

import {
  ArrowDown,
  ArrowLeft,
  BadgeDollarSign,
  CheckCircle2,
  ClipboardCheck,
  CreditCard,
  ExternalLink,
  FastForward,
  Gauge,
  Pause,
  Play,
  Receipt,
  Scale,
  ShieldCheck,
  StepForward,
  Truck,
} from "lucide-react";
import Link from "next/link";
import { useParams } from "next/navigation";
import * as React from "react";

import { ErrorState, LoadingCard } from "@/components/common/states";
import { MessageTimeline } from "@/components/supply/message-timeline";
import { NegotiationBoard } from "@/components/supply/negotiation-board";
import { QuoteComparison } from "@/components/supply/quote-comparison";
import {
  DecisionDialog,
  LifecycleStepper,
  ModeBadge,
  PageHeader,
  pct,
  StatusPill,
} from "@/components/supply/shared";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/overlays";
import {
  Badge,
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
  Input,
  Label,
  Tabs,
  TabsContent,
  TabsList,
  TabsTrigger,
} from "@/components/ui/primitives";
import {
  useAdvanceNegotiation,
  useApproval,
  useApprovePayment,
  useCapturePayment,
  useDecideProcurement,
  useMatchInvoice,
  usePayInvoice,
  useProcurement,
  useProcurementMessages,
  useReceiveGoods,
  useReconcile,
} from "@/hooks/use-supply";
import { cn, formatDate, formatMoney, toNumber } from "@/lib/utils";
import type { OrderBrief, ProcurementDetail, SupplierInvoice } from "@/types/supply";

const LIVE = ["SOURCING", "NEGOTIATING"];

export default function NegotiationWorkspacePage() {
  const { id } = useParams<{ id: string }>();
  const { data, isLoading, error, refetch } = useProcurement(id);
  const live = data ? LIVE.includes(data.status) : false;
  const messages = useProcurementMessages(id, live);
  const advance = useAdvanceNegotiation(id);
  const [autoplay, setAutoplay] = React.useState(false);
  const [deciding, setDeciding] = React.useState(false);
  const [tab, setTab] = React.useState<string | null>(null);
  const tabsRef = React.useRef<HTMLDivElement>(null);
  const decide = useDecideProcurement(id);

  // Auto-play: advance one stage at a time so the room can watch the agents talk.
  React.useEffect(() => {
    if (!autoplay || !data) return;
    if (!LIVE.includes(data.status)) {
      setAutoplay(false);
      return;
    }
    if (advance.isPending) return;
    const timer = window.setTimeout(() => advance.mutate(), 1400);
    return () => window.clearTimeout(timer);
  }, [autoplay, data, advance]);

  if (isLoading) return <LoadingCard lines={8} />;
  if (error || !data) return <ErrorState error={error} onRetry={() => void refetch()} />;

  const rec = data.recommendation;
  const winner = rec?.winner;
  const policy = data.policy;
  const activeTab = tab ?? (data.purchase_order ? "lifecycle" : "conversation");

  // Once the purchase is approved the work moves to the PO lifecycle below the fold
  // (receive goods, match the invoice, pay with PayPal) - one click takes you there.
  const goToLifecycle = () => {
    setTab("lifecycle");
    requestAnimationFrame(() => tabsRef.current?.scrollIntoView({ behavior: "smooth", block: "start" }));
  };

  return (
    <div className="space-y-5">
      <Link href="/supply/negotiations" className="inline-flex items-center gap-1 text-xs text-muted-foreground hover:text-foreground">
        <ArrowLeft className="h-3.5 w-3.5" /> All negotiations
      </Link>

      <PageHeader
        eyebrow={`${data.reference} · ${data.rfq_reference}`}
        title={`Procure ${toNumber(data.quantity)} ${data.unit} of ${data.product_name}`}
        description={
          <span>
            Trigger: <span className="font-medium">{data.trigger.toLowerCase().replace(/_/g, " ")}</span> · needed by{" "}
            {formatDate(data.required_by)} · conversation <span className="font-mono text-2xs">{data.conversation_id}</span>
          </span>
        }
        actions={
          <>
            <StatusPill status={data.status} />
            {data.purchase_order && (
              <Button size="sm" className="gap-1.5" onClick={goToLifecycle}>
                <ArrowDown className="h-3.5 w-3.5" /> Next step: purchase order lifecycle
              </Button>
            )}
            {live && data.can.negotiate && (
              <>
                <Button size="sm" variant="outline" className="gap-1.5" loading={advance.isPending && !autoplay}
                  onClick={() => advance.mutate()}>
                  <StepForward className="h-3.5 w-3.5" /> Next step
                </Button>
                <Button size="sm" className="gap-1.5" onClick={() => setAutoplay((a) => !a)}>
                  {autoplay ? <Pause className="h-3.5 w-3.5" /> : <Play className="h-3.5 w-3.5" />}
                  {autoplay ? "Pause" : "Watch live"}
                </Button>
              </>
            )}
          </>
        }
      />

      <Card>
        <CardContent className="p-4">
          <LifecycleStepper status={data.status} />
        </CardContent>
      </Card>

      <div className="grid gap-4 lg:grid-cols-3">
        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="flex items-center gap-2 text-sm"><Gauge className="h-4 w-4 text-primary" /> Why we are buying</CardTitle>
            <CardDescription>Inventory Intelligence - computed from sales and stock.</CardDescription>
          </CardHeader>
          <CardContent className="grid grid-cols-2 gap-3 text-sm">
            <Fact label="Sales velocity" value={`${data.demand.velocity_recent ?? "--"}/day`} hint={`was ${data.demand.velocity_prior ?? "--"}/day`} />
            <Fact label="Demand change" value={`${data.demand.demand_change_pct ?? "--"}%`} tone="primary" />
            <Fact label="Days of cover" value={String(data.demand.days_of_cover ?? "--")} tone="warning" hint={`lead time ${data.demand.lead_time_days ?? "--"}d`} />
            <Fact label="Suggested order" value={`${data.demand.suggested_quantity ?? data.quantity} ${data.unit}`} />
          </CardContent>
        </Card>

        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="flex items-center gap-2 text-sm"><Scale className="h-4 w-4 text-primary" /> Merchant policy</CardTitle>
            <CardDescription>Deterministic engine · {policy.policy_version} · never set by AI.</CardDescription>
          </CardHeader>
          <CardContent className="grid grid-cols-2 gap-3 text-sm">
            <Fact label="Selling price" value={formatMoney(policy.expected_selling_price)} />
            <Fact label="Target margin" value={pct(policy.target_margin)} />
            <Fact label="Max landed / unit" value={formatMoney(policy.max_unit_cost)} tone="destructive"
              hint={`${formatMoney(policy.expected_selling_price)} × (1 − ${pct(policy.target_margin)})`} />
            <Fact label="Maximum budget" value={formatMoney(policy.max_budget)} tone="destructive" />
            <Fact label="Target / unit" value={formatMoney(policy.target_unit_cost)} tone="success" />
            <Fact label="Delivery · rounds" value={`${policy.max_delivery_days}d · ${policy.max_rounds}`} hint={`min reliability ${pct(policy.min_reliability)}`} />
          </CardContent>
        </Card>

        <RecommendationCard data={data} onDecide={() => setDeciding(true)} />
      </div>

      <NegotiationBoard
        sessions={data.sessions}
        maxUnitCost={policy.max_unit_cost}
        targetUnitCost={policy.target_unit_cost}
        recommendedSessionId={data.recommended_session_id}
      />

      <div ref={tabsRef} className="scroll-mt-20">
      <Tabs value={activeTab} onValueChange={setTab}>
        <TabsList>
          <TabsTrigger value="conversation">Agent conversation ({messages.data?.length ?? data.message_count})</TabsTrigger>
          <TabsTrigger value="comparison">Quote comparison</TabsTrigger>
          <TabsTrigger value="lifecycle">Purchase order lifecycle</TabsTrigger>
        </TabsList>
        <TabsContent value="conversation">
          <Card>
            <CardContent className="max-h-[560px] overflow-y-auto p-4">
              <MessageTimeline messages={messages.data ?? []} emptyText="The conversation starts when the RFQ goes out." />
            </CardContent>
          </Card>
        </TabsContent>
        <TabsContent value="comparison">
          <Card>
            <CardContent className="space-y-3 p-4">
              {rec?.explanation && <p className="text-sm">{rec.explanation}</p>}
              <QuoteComparison recommendation={rec} />
            </CardContent>
          </Card>
        </TabsContent>
        <TabsContent value="lifecycle">
          <Lifecycle data={data} />
        </TabsContent>
      </Tabs>
      </div>

      <DecisionDialog
        open={deciding}
        onClose={() => setDeciding(false)}
        title={data.approval?.title ?? "Approve purchase"}
        description="Approval binds to these exact terms. If anything material changes, it is invalidated and must be re-approved."
        amount={data.approval?.amount}
        currency={data.currency}
        details={[
          { label: "Supplier", value: String(data.approval?.details.supplier_name ?? winner?.supplier_name ?? "") },
          { label: "Unit price", value: formatMoney(String(data.approval?.details.unit_price ?? "")) },
          { label: "Quantity", value: String(data.approval?.details.quantity ?? data.quantity) },
          { label: "Delivery", value: `${String(data.approval?.details.lead_time_days ?? "")} days` },
          { label: "Policy", value: <span className="font-mono text-2xs">{data.policy.policy_version}</span> },
          { label: "Terms hash", value: <span className="font-mono text-2xs">{data.approval?.details_hash.slice(0, 12)}…</span> },
        ]}
        pending={decide.isPending}
        onDecide={(approve, note) => decide.mutate({ approve, note }, { onSettled: () => setDeciding(false) })}
      />
    </div>
  );
}

function Fact({ label, value, hint, tone }: { label: string; value: React.ReactNode; hint?: string;
  tone?: "primary" | "success" | "warning" | "destructive" }) {
  return (
    <div>
      <p className="text-2xs uppercase tracking-wide text-muted-foreground">{label}</p>
      <p className={cn("font-semibold tabular-nums", tone === "primary" && "text-primary", tone === "success" && "text-success",
        tone === "warning" && "text-warning", tone === "destructive" && "text-destructive")}>{value}</p>
      {hint && <p className="text-2xs text-muted-foreground">{hint}</p>}
    </div>
  );
}

function RecommendationCard({ data, onDecide }: { data: ProcurementDetail; onDecide: () => void }) {
  const winner = data.recommendation?.winner;
  const awaiting = data.status === "AWAITING_APPROVAL";
  return (
    <Card className={cn(awaiting && "border-warning/50")}>
      <CardHeader className="pb-2">
        <CardTitle className="flex items-center gap-2 text-sm"><ShieldCheck className="h-4 w-4 text-primary" /> Recommendation</CardTitle>
        <CardDescription>Procurement Evaluation · deterministic scoring.</CardDescription>
      </CardHeader>
      <CardContent className="space-y-3 text-sm">
        {!winner && <p className="text-muted-foreground">{data.failure_reason || "Appears once the final offers are in."}</p>}
        {winner && (
          <>
            <div>
              <p className="text-lg font-semibold">{winner.supplier_name}</p>
              <p className="text-2xs text-muted-foreground">
                Landed {formatMoney(data.final_landed_total)} · saved{" "}
                <span className="font-semibold text-success">{formatMoney(data.savings_amount)}</span> vs the best opening quote
              </p>
            </div>
            <ul className="space-y-1 text-2xs text-muted-foreground">
              {(data.recommendation?.reasons ?? []).slice(0, 4).map((r) => (
                <li key={r} className="flex gap-1.5"><CheckCircle2 className="mt-px h-3 w-3 shrink-0 text-success" />{r}</li>
              ))}
            </ul>
          </>
        )}
        {data.approval && (
          <div className="flex flex-wrap items-center gap-2 text-2xs">
            <span className="font-mono">{data.approval.reference}</span>
            <StatusPill status={data.approval.status} />
            {data.approval.decided_by_label && <span className="text-muted-foreground">by {data.approval.decided_by_label}</span>}
          </div>
        )}
        {awaiting && (
          <div className="space-y-1.5">
            <Button className="w-full gap-1.5" onClick={onDecide}>
              <ClipboardCheck className="h-4 w-4" /> Review & approve purchase
            </Button>
            {!data.can.approve && (
              <p className="text-2xs text-muted-foreground">
                Your role lacks <span className="font-mono">procurement:approve</span> - the backend will refuse, and log the attempt.
              </p>
            )}
          </div>
        )}
      </CardContent>
    </Card>
  );
}

// --------------------------------------------------------------------------- //
// Lifecycle: PO -> invoice -> receiving -> match -> payment -> reconciliation
// --------------------------------------------------------------------------- //
function Lifecycle({ data }: { data: ProcurementDetail }) {
  const [receiving, setReceiving] = React.useState<OrderBrief | null>(null);
  const reconcile = useReconcile();
  const order = data.purchase_order;
  if (!order) {
    return (
      <Card>
        <CardContent className="p-6 text-center text-sm text-muted-foreground">
          No purchase order yet - it is created only when a person approves the recommended offer.
        </CardContent>
      </Card>
    );
  }
  const outstanding = order.lines.reduce((s, l) => s + ((toNumber(l.quantity_ordered) ?? 0) - (toNumber(l.quantity_received) ?? 0)), 0);
  return (
    <div className="grid gap-4 lg:grid-cols-2">
      <Card>
        <CardHeader className="pb-2">
          <CardTitle className="flex items-center gap-2 text-sm"><Truck className="h-4 w-4 text-primary" /> {order.reference}</CardTitle>
          <CardDescription>
            {formatMoney(order.total_value)} · {order.payment_terms.replace("_", " ")} · expected {formatDate(order.expected_at)}
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-3">
          {order.lines.map((l) => (
            <div key={l.line_id} className="flex items-center justify-between text-xs tabular-nums">
              <span>{l.product_name} <span className="font-mono text-muted-foreground">{l.sku}</span></span>
              <span>{toNumber(l.quantity_received)} / {toNumber(l.quantity_ordered)} received @ {formatMoney(l.unit_price)}</span>
            </div>
          ))}
          <div className="space-y-1.5">
            {data.receipts.map((r) => (
              <div key={r.goods_receipt_id} className="flex items-center justify-between rounded-lg bg-muted/50 px-2.5 py-1.5 text-2xs">
                <span className="font-mono">{r.reference}</span>
                <span>{toNumber(r.total_quantity)} received · {r.is_partial ? "partial" : "complete"} · {r.on_time ? "on time" : "late"}</span>
              </div>
            ))}
          </div>
          {outstanding > 0 && data.can.receive && (
            <Button size="sm" variant="outline" className="gap-1.5" onClick={() => setReceiving(order)}>
              <Truck className="h-3.5 w-3.5" /> Receive goods ({outstanding} outstanding)
            </Button>
          )}
        </CardContent>
      </Card>

      {data.invoices.map((invoice) => (
        <InvoiceCard key={invoice.supplier_invoice_id} invoice={invoice} can={data.can} />
      ))}

      <Card className="lg:col-span-2">
        <CardHeader className="pb-2">
          <CardTitle className="flex items-center gap-2 text-sm"><Scale className="h-4 w-4 text-primary" /> Reconciliation</CardTitle>
          <CardDescription>PO × goods receipt × invoice × PayPal capture must all agree.</CardDescription>
        </CardHeader>
        <CardContent className="space-y-3">
          <div className="flex flex-wrap gap-2">
            {(data.readiness?.checks ?? []).map((c) => (
              <Badge key={c.check} variant={c.ok ? "success" : "outline"} className="gap-1">
                {c.ok ? <CheckCircle2 className="h-3 w-3" /> : null}{c.check}
              </Badge>
            ))}
          </div>
          {data.reconciliation ? (
            <div className="grid gap-3 sm:grid-cols-4">
              <Fact label="Paid" value={formatMoney(data.reconciliation.paid_amount)} hint={`= invoice ${formatMoney(data.reconciliation.invoice_total)}`} />
              <Fact label="PayPal reference" value={<span className="font-mono text-xs">{data.reconciliation.payment_reference}</span>} />
              <Fact label="Unit cost" value={`${formatMoney(data.reconciliation.previous_unit_cost)} → ${formatMoney(data.reconciliation.new_unit_cost)}`} tone="success" />
              <Fact label="Gross margin" value={`${data.reconciliation.previous_margin_pct}% → ${data.reconciliation.new_margin_pct}%`} tone="success" hint="fed back to Growth Intelligence" />
            </div>
          ) : (
            data.readiness?.ready && data.can.match && (
              <Button size="sm" className="gap-1.5" loading={reconcile.isPending} onClick={() => reconcile.mutate(order.purchase_order_id)}>
                <Scale className="h-3.5 w-3.5" /> Reconcile
              </Button>
            )
          )}
        </CardContent>
      </Card>

      <ReceiveDialog order={receiving} onClose={() => setReceiving(null)} />
    </div>
  );
}

function InvoiceCard({ invoice, can }: { invoice: SupplierInvoice; can: ProcurementDetail["can"] }) {
  const match = useMatchInvoice();
  const approvePayment = useApprovePayment();
  const pay = usePayInvoice();
  const capture = useCapturePayment();
  const approval = useApproval(invoice.approval_request_id);
  const [deciding, setDeciding] = React.useState(false);
  const exec = invoice.execution;
  const approvalStatus = approval.data?.status;
  return (
    <Card>
      <CardHeader className="pb-2">
        <CardTitle className="flex items-center justify-between gap-2 text-sm">
          <span className="flex items-center gap-2"><Receipt className="h-4 w-4 text-primary" /> Invoice {invoice.invoice_number}</span>
          <StatusPill status={invoice.status} />
        </CardTitle>
        <CardDescription>
          {invoice.supplier_name} · {formatMoney(invoice.total)} · due {formatDate(invoice.due_date)}
          {invoice.is_simulated && " · issued by a simulated supplier agent"}
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-3 text-xs">
        {invoice.match && (
          <div className="rounded-lg border border-border p-2.5">
            <div className="flex items-center justify-between">
              <span className="font-medium">Three-way match</span>
              <StatusPill status={invoice.match.status} />
            </div>
            {invoice.match.discrepancies.map((d) => (
              <p key={`${d.code}-${d.sku}`} className="mt-1 text-2xs text-destructive">{d.message} ({formatMoney(d.amount)})</p>
            ))}
            {invoice.match.discrepancies.length === 0 && (
              <p className="mt-1 text-2xs text-muted-foreground">Ordered, received and invoiced quantities and prices agree.</p>
            )}
          </div>
        )}
        <div className="flex flex-wrap gap-2">
          {can.match && invoice.status !== "PAID" && (
            <Button size="sm" variant="outline" loading={match.isPending} onClick={() => match.mutate(invoice.supplier_invoice_id)}>
              Re-run match
            </Button>
          )}
          {approvalStatus === "PENDING" && (
            <Button size="sm" className="gap-1.5" onClick={() => setDeciding(true)}>
              <BadgeDollarSign className="h-3.5 w-3.5" /> Approve payment
            </Button>
          )}
          {approvalStatus === "APPROVED" && !exec && (
            <Button size="sm" className="gap-1.5" disabled={!can.execute_payment} loading={pay.isPending}
              onClick={() => pay.mutate(invoice.supplier_invoice_id)}>
              <CreditCard className="h-3.5 w-3.5" /> Pay with PayPal
            </Button>
          )}
        </div>
        {exec && (
          <div className="space-y-1 rounded-lg bg-muted/40 p-2.5">
            <div className="flex items-center gap-2">
              <span className="font-medium">PayPal Orders v2</span>
              <ModeBadge mode={exec.mode} />
              <StatusPill status={exec.status} />
            </div>
            <p className="font-mono text-2xs text-muted-foreground">order {exec.paypal_order_id}{exec.paypal_capture_id && ` · capture ${exec.paypal_capture_id}`}</p>
            <p className="font-mono text-2xs text-muted-foreground">idempotency {exec.idempotency_key}</p>
            {exec.status === "PAYER_ACTION_REQUIRED" && (
              <div className="flex flex-wrap gap-2 pt-1">
                {exec.approve_url && (
                  <a href={exec.approve_url} target="_blank" rel="noreferrer" className="inline-flex items-center gap-1 text-primary hover:underline">
                    Approve in PayPal <ExternalLink className="h-3 w-3" />
                  </a>
                )}
                <Button size="sm" variant="outline" className="gap-1.5" loading={capture.isPending} onClick={() => capture.mutate(exec.execution_id)}>
                  <FastForward className="h-3.5 w-3.5" /> Capture
                </Button>
              </div>
            )}
            {exec.error && <p className="text-2xs text-destructive">{exec.error}</p>}
          </div>
        )}
      </CardContent>
      <DecisionDialog
        open={deciding}
        onClose={() => setDeciding(false)}
        title={`Pay ${invoice.supplier_name} - ${invoice.invoice_number}`}
        description="Payment goes through PayPal Orders v2 with the supplier as payee. Approval binds to this exact amount, payee and match."
        amount={invoice.total}
        currency={invoice.currency}
        details={[
          { label: "Match", value: invoice.match?.status ?? "--" },
          { label: "Payee", value: String(approval.data?.details.payee_email ?? "") },
          { label: "Purchase order", value: invoice.purchase_order_reference },
        ]}
        pending={approvePayment.isPending}
        onDecide={(approve, note) =>
          approvePayment.mutate({ invoiceId: invoice.supplier_invoice_id, approve, note }, { onSettled: () => setDeciding(false) })
        }
      />
    </Card>
  );
}

function ReceiveDialog({ order, onClose }: { order: OrderBrief | null; onClose: () => void }) {
  const receive = useReceiveGoods();
  const [amounts, setAmounts] = React.useState<Record<string, string>>({});
  React.useEffect(() => {
    if (!order) return;
    setAmounts(Object.fromEntries(order.lines.map((l) => [l.line_id,
      String(Math.max((toNumber(l.quantity_ordered) ?? 0) - (toNumber(l.quantity_received) ?? 0), 0))])));
  }, [order]);
  if (!order) return null;
  const lines = order.lines.map((l) => ({ line_id: l.line_id, quantity: Number(amounts[l.line_id] ?? 0) })).filter((l) => l.quantity > 0);
  return (
    <Dialog open={Boolean(order)} onOpenChange={(next) => !next && onClose()}>
      <DialogContent className="max-w-md">
        <DialogHeader>
          <DialogTitle>Receive {order.reference}</DialogTitle>
          <DialogDescription>Partial deliveries are normal - each receipt books stock and re-runs the three-way match.</DialogDescription>
        </DialogHeader>
        {order.lines.map((l) => {
          const outstanding = (toNumber(l.quantity_ordered) ?? 0) - (toNumber(l.quantity_received) ?? 0);
          return (
            <div key={l.line_id} className="space-y-1.5">
              <Label htmlFor={`rcv-${l.line_id}`}>{l.product_name}</Label>
              <div className="flex items-center gap-2">
                <Input id={`rcv-${l.line_id}`} type="number" min={0} max={outstanding} value={amounts[l.line_id] ?? ""}
                  onChange={(e) => setAmounts((a) => ({ ...a, [l.line_id]: e.target.value }))} />
                <span className="whitespace-nowrap text-2xs text-muted-foreground">of {outstanding}</span>
              </div>
            </div>
          );
        })}
        <DialogFooter>
          <Button variant="ghost" onClick={onClose}>Cancel</Button>
          <Button loading={receive.isPending} disabled={lines.length === 0}
            onClick={() => receive.mutate({ orderId: order.purchase_order_id, lines }, { onSuccess: onClose })}>
            Record receipt
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
