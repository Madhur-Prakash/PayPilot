"use client";

/**
 * Payment Management - every PayPal money movement and the approval workflow behind it.
 *
 *   approval requested -> approved by a person -> PayPal order created (person)
 *   -> payer approves in PayPal -> captured (person) -> verified webhook confirms
 *
 * No agent can reach any of these buttons' endpoints. Every row shows its mode
 * (SANDBOX / LIVE / SIMULATED) so a test payment is never mistaken for a real one.
 */

import {
  ArrowUpRight,
  BadgeDollarSign,
  CircleAlert,
  ClipboardCheck,
  CreditCard,
  Eye,
  Hourglass,
  RefreshCw,
  ShieldCheck,
  Wallet,
  XCircle,
} from "lucide-react";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import * as React from "react";

import { EmptyState, ErrorState, LoadingCard, LoadingRows } from "@/components/common/states";
import { formatPrice } from "@/components/discovery/shared";
import { DecisionDialog, MetricTile, ModeBadge, PageHeader, StatusPill } from "@/components/supply/shared";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "@/components/ui/overlays";
import { Badge, Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/primitives";
import { useCaptureOrder, useCreatePaymentOrder, usePaymentHistory, usePaymentOrder } from "@/hooks/use-discovery";
import { useDecideApproval } from "@/hooks/use-supply";
import { cn, formatDateTime, formatRelativeTime } from "@/lib/utils";
import type { PaymentHistoryItem } from "@/types/discovery";
import type { Approval } from "@/types/supply";

const KINDS = [
  { key: "all", label: "All" },
  { key: "MERCHANT_PURCHASE", label: "Test-stock purchases" },
  { key: "SUPPLIER_SETTLEMENT", label: "Supplier payments" },
  { key: "CASHBACK_PAYOUT", label: "Cashback payouts" },
];

function newKey(): string {
  return typeof crypto !== "undefined" && "randomUUID" in crypto ? crypto.randomUUID() : `${Date.now()}-${Math.random()}`;
}

function ReturnBanner({ items }: { items: PaymentHistoryItem[] | undefined }) {
  const params = useSearchParams();
  const capture = useCaptureOrder();
  const executionId = params.get("execution");
  if (!executionId) return null;
  const cancelled = params.get("cancelled") === "1";
  const row = items?.find((i) => i.execution_id === executionId);
  const capturable = row && ["PAYER_ACTION_REQUIRED", "PENDING"].includes(row.status);
  return (
    <Card className={cn("border-2", cancelled ? "border-warning/40" : "border-primary/40")}>
      <CardContent className="flex flex-wrap items-center gap-3 p-4">
        {cancelled ? <XCircle className="h-5 w-5 text-warning" /> : <ShieldCheck className="h-5 w-5 text-primary" />}
        <div className="min-w-0 flex-1">
          <p className="text-sm font-semibold">{cancelled ? "Payment cancelled in PayPal - nothing was charged" : row?.status === "CAPTURED" ? "Payment captured" : "Back from PayPal - the payer approved"}</p>
          <p className="text-xs text-muted-foreground">
            {row ? `${row.title} · ${formatPrice(row.amount, row.currency)} to ${row.payee_email} · order ${row.paypal_order_id}` : "Loading the payment…"}
          </p>
        </div>
        {row && <StatusPill status={row.status} />}
        {row && <ModeBadge mode={row.mode} />}
        {!cancelled && capturable && row.kind === "MERCHANT_PURCHASE" && (
          <Button size="sm" className="gap-1.5" loading={capture.isPending} onClick={() => capture.mutate(row.execution_id)}>
            <CreditCard className="h-4 w-4" /> Capture payment
          </Button>
        )}
      </CardContent>
    </Card>
  );
}

function OrderDialog({ executionId, onClose }: { executionId: string | null; onClose: () => void }) {
  const { data, isLoading, error, refetch, isFetching } = usePaymentOrder(executionId);
  return (
    <Dialog open={Boolean(executionId)} onOpenChange={(open) => !open && onClose()}>
      <DialogContent className="max-w-xl">
        <DialogHeader>
          <DialogTitle>PayPal order</DialogTitle>
          <DialogDescription>Read live from PayPal (GET /v2/checkout/orders/{"{id}"}).</DialogDescription>
        </DialogHeader>
        {isLoading && <LoadingRows rows={4} />}
        {error && <ErrorState error={error} />}
        {data && (
          <div className="space-y-3 text-sm">
            <div className="flex flex-wrap items-center gap-2">
              <StatusPill status={data.execution.status} /><ModeBadge mode={data.execution.mode} />
              {data.paypal && <Badge variant="outline">PayPal: {data.paypal.status}</Badge>}
              <Button size="sm" variant="ghost" className="ml-auto gap-1" loading={isFetching} onClick={() => void refetch()}><RefreshCw className="h-3.5 w-3.5" /> Refresh</Button>
            </div>
            {data.paypal_error && <p className="text-xs text-destructive">{data.paypal_error}</p>}
            <dl className="grid grid-cols-[140px_1fr] gap-x-3 gap-y-1 text-xs">
              <dt className="text-muted-foreground">Order id</dt><dd className="font-mono">{data.execution.paypal_order_id || "--"}</dd>
              <dt className="text-muted-foreground">Amount</dt><dd className="font-semibold">{data.paypal?.amount ? `${data.paypal.amount.value} ${data.paypal.amount.currency_code}` : formatPrice(data.execution.amount, data.execution.currency)}</dd>
              <dt className="text-muted-foreground">Payee</dt><dd>{data.paypal?.payee_email || data.execution.payee_email}</dd>
              <dt className="text-muted-foreground">Capture</dt><dd className="font-mono">{data.paypal?.capture_ids?.join(", ") || data.execution.paypal_capture_id || "--"}</dd>
              <dt className="text-muted-foreground">Created</dt><dd>{data.paypal?.create_time ? formatDateTime(data.paypal.create_time) : formatDateTime(data.execution.executed_at)}</dd>
              <dt className="text-muted-foreground">Idempotency key</dt><dd className="break-all font-mono text-2xs">{data.execution.idempotency_key}</dd>
              <dt className="text-muted-foreground">Approval</dt><dd>{data.approval ? `${data.approval.reference} · ${data.approval.status.toLowerCase()} by ${data.approval.decided_by_label || "--"}` : "--"}</dd>
              {data.recommendation && (<><dt className="text-muted-foreground">Recommendation</dt><dd><Link className="text-primary hover:underline" href="/recommendations">{data.recommendation.reference} · {data.recommendation.title}</Link></dd></>)}
              {data.execution.debug_id && (<><dt className="text-muted-foreground">PayPal debug id</dt><dd className="font-mono text-2xs">{data.execution.debug_id}</dd></>)}
              {data.execution.error && (<><dt className="text-muted-foreground">Error</dt><dd className="text-destructive">{data.execution.error}</dd></>)}
            </dl>
            {data.paypal?.approve_url && data.execution.status === "PAYER_ACTION_REQUIRED" && (
              <Button asChild className="gap-1.5"><a href={data.paypal.approve_url} target="_blank" rel="noopener noreferrer">Approve in PayPal <ArrowUpRight className="h-4 w-4" /></a></Button>
            )}
          </div>
        )}
      </DialogContent>
    </Dialog>
  );
}

function ApprovalRow({ approval, canApprove, canExecute }: { approval: Approval; canApprove: boolean; canExecute: boolean }) {
  const decide = useDecideApproval();
  const create = useCreatePaymentOrder();
  const [deciding, setDeciding] = React.useState(false);
  // One key per approval for this page session: a retried click reuses it.
  const key = React.useRef(newKey());
  const isPurchase = approval.action === "MERCHANT_PURCHASE";
  const holdsPermission = approval.required_permission === "payment:approve" ? canApprove : Boolean(approval.can_decide);
  return (
    <div className="flex flex-wrap items-center gap-3 rounded-xl border border-border p-3">
      <span className={cn("flex h-9 w-9 items-center justify-center rounded-lg", approval.status === "PENDING" ? "bg-warning/14 text-warning" : "bg-success/12 text-success")}>
        {approval.status === "PENDING" ? <Hourglass className="h-4 w-4" /> : <ClipboardCheck className="h-4 w-4" />}
      </span>
      <div className="min-w-0 flex-1">
        <p className="text-sm font-medium">{approval.title}</p>
        <p className="text-2xs text-muted-foreground">
          {approval.reference} · {approval.action_label} · requested by {approval.requested_by_label} {formatRelativeTime(approval.created_at)}
          {approval.risk_flags.length > 0 && <span className="text-warning"> · {approval.risk_flags.length} risk flag(s)</span>}
        </p>
      </div>
      <span className="text-base font-semibold tabular-nums">{formatPrice(approval.amount, approval.currency)}</span>
      <StatusPill status={approval.status} />
      {approval.status === "PENDING" && (holdsPermission
        ? <Button size="sm" onClick={() => setDeciding(true)}>Review</Button>
        : <span className="text-2xs text-muted-foreground">needs {approval.required_permission}</span>)}
      {approval.status === "APPROVED" && isPurchase && (canExecute
        ? <Button size="sm" className="gap-1.5" loading={create.isPending}
            onClick={() => create.mutate({ approvalId: approval.approval_id, idempotencyKey: key.current })}>
            <BadgeDollarSign className="h-4 w-4" /> Create PayPal order
          </Button>
        : <span className="text-2xs text-muted-foreground">needs payment:execute</span>)}
      {!isPurchase && <Button asChild size="sm" variant="outline"><Link href="/approvals">Open in Approvals</Link></Button>}
      <DecisionDialog open={deciding} onClose={() => setDeciding(false)} title={approval.title} description={approval.summary}
        amount={approval.amount} currency={approval.currency} pending={decide.isPending}
        details={[
          ...Object.entries(approval.details).filter(([k]) => ["quantity", "unit_cost", "payee_email", "product_title", "recommendation_reference"].includes(k))
            .map(([k, v]) => ({ label: k.replace(/_/g, " "), value: String(v) })),
          { label: "terms hash", value: <span className="font-mono text-2xs">{approval.details_hash.slice(0, 16)}…</span> },
          ...approval.risk_flags.map((f) => ({ label: "risk", value: <span className="text-warning">{f}</span> })),
        ]}
        onDecide={(approve, note) => decide.mutate({ id: approval.approval_id, approve, note }, { onSuccess: () => setDeciding(false) })} />
    </div>
  );
}

function PaymentManagement() {
  const [kind, setKind] = React.useState("all");
  const { data, isLoading, error, refetch } = usePaymentHistory(kind === "all" ? undefined : kind);
  const capture = useCaptureOrder();
  const [detail, setDetail] = React.useState<string | null>(null);
  const can = data?.permissions ?? { can_approve: false, can_execute: false };

  return (
    <div className="space-y-5">
      <PageHeader eyebrow="Finance" title="Payment Management"
        description="PayPal orders for approved purchases, their status, and the human approvals behind them. Three people-only steps move money: approve, create the order, capture."
        actions={<>{data && <ModeBadge mode={data.mode} />}<Button size="sm" variant="outline" className="gap-1.5" onClick={() => void refetch()}><RefreshCw className="h-3.5 w-3.5" /> Refresh</Button></>} />

      {data?.mode === "SIMULATED" && (
        <Card className="border-warning/40"><CardContent className="flex items-start gap-3 p-4 text-sm">
          <CircleAlert className="mt-0.5 h-4 w-4 shrink-0 text-warning" />
          <p className="text-muted-foreground">PayPal is not configured, so orders run against PayPilot&apos;s labelled simulator (every id starts with <code>SIM-</code>).
            Add <code>PAYPAL_CLIENT_ID</code> and <code>PAYPAL_CLIENT_SECRET</code> from a PayPal sandbox app to <code>.env</code> to create real sandbox orders.</p>
        </CardContent></Card>
      )}
      <ReturnBanner items={data?.items} />
      {error && <ErrorState error={error} onRetry={() => void refetch()} />}
      {isLoading && <LoadingCard lines={6} />}

      {data && (
        <>
          <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
            <MetricTile icon={Wallet} label="Payments" value={data.stats.total} hint={`${Object.keys(data.stats.by_status).length} statuses`} />
            <MetricTile icon={Hourglass} tone="warning" label="Awaiting payer / capture" value={data.stats.awaiting_payer} hint="Approve in PayPal, then capture" />
            <MetricTile icon={BadgeDollarSign} tone="success" label="Settled"
              value={data.stats.settled.length ? data.stats.settled.map((s) => formatPrice(s.amount, s.currency)).join(" + ") : formatPrice(0, "USD")}
              hint={data.stats.settled.map((s) => s.mode.toLowerCase()).join(", ") || "nothing settled yet"} />
            <MetricTile icon={XCircle} tone={data.stats.failed ? "destructive" : "default"} label="Failed" value={data.stats.failed} hint="No money moved on a failure" />
          </div>

          <Card>
            <CardHeader className="pb-2"><CardTitle className="text-sm">Approval workflow</CardTitle>
              <CardDescription>Open requests to move money. Agents can request; only people decide and execute.</CardDescription></CardHeader>
            <CardContent className="space-y-2">
              {data.approvals.length === 0 && <EmptyState icon={ClipboardCheck} title="Nothing waiting" description="Request a test-stock purchase from an approved recommendation, or let the PayPal Transaction Agent request one." />}
              {data.approvals.map((a) => <ApprovalRow key={a.approval_id} approval={a} canApprove={can.can_approve} canExecute={can.can_execute} />)}
            </CardContent>
          </Card>

          <div className="flex flex-wrap gap-1.5">
            {KINDS.map((k) => (
              <button key={k.key} type="button" onClick={() => setKind(k.key)} aria-pressed={kind === k.key}
                className={cn("rounded-lg border px-3 py-1 text-xs font-medium focus-ring", kind === k.key ? "border-primary bg-primary text-primary-foreground" : "border-border bg-card hover:bg-muted")}>
                {k.label}
              </button>
            ))}
          </div>
          <Card>
            <CardContent className="overflow-x-auto p-0">
              {data.items.length === 0 ? (
                <EmptyState icon={Wallet} title="No payments yet" description="PayPal orders appear here once created from an approved request." />
              ) : (
                <table className="w-full min-w-[860px] text-sm">
                  <thead className="bg-muted/40 text-left text-2xs uppercase tracking-wide text-muted-foreground">
                    <tr><th className="p-3 font-medium">When</th><th className="p-3 font-medium">Payment</th><th className="p-3 font-medium">Amount</th><th className="p-3 font-medium">Status</th>
                      <th className="p-3 font-medium">Mode</th><th className="p-3 font-medium">PayPal reference</th><th className="p-3 font-medium">Approval</th><th className="p-3" /></tr>
                  </thead>
                  <tbody>
                    {data.items.map((row) => {
                      const purchase = row.kind === "MERCHANT_PURCHASE";
                      return (
                        <tr key={row.execution_id} className="border-t border-border align-middle">
                          <td className="p-3 text-xs text-muted-foreground">{formatDateTime(row.executed_at)}</td>
                          <td className="p-3"><p className="line-clamp-1 font-medium">{row.title}</p><p className="text-2xs text-muted-foreground">{row.kind.toLowerCase().replace(/_/g, " ")} · {row.method}</p></td>
                          <td className="p-3 font-semibold tabular-nums">{formatPrice(row.amount, row.currency)}</td>
                          <td className="p-3"><StatusPill status={row.status} />{row.error && <p className="mt-0.5 line-clamp-1 text-2xs text-destructive" title={row.error}>{row.error}</p>}</td>
                          <td className="p-3"><ModeBadge mode={row.mode} /></td>
                          <td className="p-3 font-mono text-2xs">{row.paypal_capture_id || row.paypal_order_id || row.paypal_payout_batch_id || "--"}</td>
                          <td className="p-3 text-xs">{row.approval_reference ?? "--"}</td>
                          <td className="p-3">
                            <div className="flex justify-end gap-1.5">
                              {row.status === "PAYER_ACTION_REQUIRED" && row.approve_url && (
                                <Button asChild size="sm" variant="outline" className="h-7 gap-1 text-2xs"><a href={row.approve_url} target="_blank" rel="noopener noreferrer">Approve in PayPal <ArrowUpRight className="h-3 w-3" /></a></Button>
                              )}
                              {purchase && ["PAYER_ACTION_REQUIRED", "PENDING"].includes(row.status) && can.can_execute && (
                                <Button size="sm" className="h-7 gap-1 text-2xs" loading={capture.isPending && capture.variables === row.execution_id}
                                  onClick={() => capture.mutate(row.execution_id)}><CreditCard className="h-3 w-3" /> Capture</Button>
                              )}
                              <Button size="sm" variant="ghost" className="h-7 gap-1 text-2xs" onClick={() => setDetail(row.execution_id)}><Eye className="h-3 w-3" /> Details</Button>
                            </div>
                          </td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              )}
            </CardContent>
          </Card>
          <p className="text-2xs text-muted-foreground">
            Capture re-reads the order from PayPal first and refuses unless PayPal reports it approved. PayPal&apos;s signature-verified
            PAYMENT.CAPTURE.COMPLETED webhook settles the same payment if it arrives first - both paths are idempotent.
            See also <Link href="/finance/webhooks" className="text-primary hover:underline">Webhooks</Link> and <Link href="/finance/transactions" className="text-primary hover:underline">PayPal transactions</Link>.
          </p>
        </>
      )}
      <OrderDialog executionId={detail} onClose={() => setDetail(null)} />
    </div>
  );
}

export default function PaymentManagementPage() {
  return (
    <React.Suspense fallback={<LoadingCard lines={6} />}>
      <PaymentManagement />
    </React.Suspense>
  );
}
