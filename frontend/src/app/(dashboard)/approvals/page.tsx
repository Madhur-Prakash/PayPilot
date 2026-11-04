"use client";

/**
 * Approval Center - the unified inbox for every money-moving decision.
 *
 * Each request shows the exact terms being authorised, the policy version and the
 * hash the approval binds to. Deciding dispatches to the owning service, which
 * re-derives the terms from live data and refuses if anything changed.
 */

import { AlertTriangle, CheckCircle2, ClipboardCheck, Fingerprint, Lock, Play, ShieldCheck, XCircle } from "lucide-react";
import Link from "next/link";
import * as React from "react";

import { EmptyState, ErrorState, LoadingRows } from "@/components/common/states";
import { DecisionDialog, PageHeader, StatusPill } from "@/components/supply/shared";
import { Button } from "@/components/ui/button";
import { Badge, Card, CardContent } from "@/components/ui/primitives";
import { useApprovals, useDecideApproval, useExecuteApproval } from "@/hooks/use-supply";
import { cn, formatDateTime, formatMoney, formatRelativeTime, titleCase } from "@/lib/utils";
import { useAuthStore } from "@/stores/auth";
import type { Approval } from "@/types/supply";

const FILTERS = ["PENDING", "APPROVED", "EXECUTED", "REJECTED", "INVALIDATED", "all"];

export default function ApprovalCenterPage() {
  const [filter, setFilter] = React.useState("PENDING");
  const { data, isLoading, error, refetch } = useApprovals(filter === "all" ? undefined : filter);
  const decide = useDecideApproval();
  const execute = useExecuteApproval();
  const canExecute = useAuthStore((s) => s.can("payment:execute"));
  const role = useAuthStore((s) => s.user?.role);
  const [active, setActive] = React.useState<Approval | null>(null);
  const items = data?.data ?? [];
  const counts = (data?.meta.status_counts ?? {}) as Record<string, number>;

  return (
    <div className="space-y-5">
      <PageHeader eyebrow="Governance" title="Approval Center"
        description="Agents can request; only people approve - Owners included. Every approval binds to a SHA-256 of the exact terms and is invalidated if they change." />
      <div className="flex flex-wrap gap-1.5">
        {FILTERS.map((f) => (
          <button key={f} type="button" onClick={() => setFilter(f)} aria-pressed={filter === f}
            className={cn("rounded-lg border px-3 py-1 text-xs font-medium focus-ring",
              filter === f ? "border-primary bg-primary text-primary-foreground" : "border-border bg-card hover:bg-muted")}>
            {f === "all" ? "All" : titleCase(f)}{f !== "all" && counts[f] ? ` (${counts[f]})` : ""}
          </button>
        ))}
      </div>
      {error && <ErrorState error={error} onRetry={() => void refetch()} />}
      {isLoading && <LoadingRows rows={4} />}
      {!isLoading && items.length === 0 && (
        <EmptyState icon={ClipboardCheck} title={filter === "PENDING" ? "Nothing waiting for you" : "No approvals here"}
          description="Purchases, supplier payments and cashback payouts appear here when an agent or a colleague requests them." />
      )}
      <div className="space-y-3">
        {items.map((a) => (
          <Card key={a.approval_id} className={cn(a.status === "PENDING" && "border-warning/50")}>
            <CardContent className="grid gap-4 p-4 lg:grid-cols-[1fr_auto]">
              <div className="min-w-0 space-y-2">
                <div className="flex flex-wrap items-center gap-2">
                  <span className="font-mono text-xs font-semibold">{a.reference}</span>
                  <Badge variant="secondary">{a.action_label}</Badge>
                  <StatusPill status={a.status} />
                  <span className="text-2xs text-muted-foreground">requested by {a.requested_by_label} · {formatRelativeTime(a.created_at)}</span>
                </div>
                <p className="font-semibold">{a.title}</p>
                {a.summary && <p className="text-xs text-muted-foreground line-clamp-2">{a.summary}</p>}
                <TermsGrid approval={a} />
                {a.risk_flags.length > 0 && (
                  <div className="flex flex-wrap gap-1.5">
                    {a.risk_flags.map((r) => (
                      <span key={r} className="inline-flex items-center gap-1 rounded-md bg-warning/14 px-1.5 py-0.5 text-2xs font-medium text-warning">
                        <AlertTriangle className="h-3 w-3" />{r}
                      </span>
                    ))}
                  </div>
                )}
                <div className="flex flex-wrap items-center gap-3 text-2xs text-muted-foreground">
                  <span className="inline-flex items-center gap-1"><Fingerprint className="h-3 w-3" />terms {a.details_hash.slice(0, 16)}…</span>
                  {a.policy_version && <span className="inline-flex items-center gap-1"><ShieldCheck className="h-3 w-3" />{a.policy_version}</span>}
                  <span className="inline-flex items-center gap-1"><Lock className="h-3 w-3" />requires <span className="font-mono">{a.required_permission}</span></span>
                  {a.decided_by_label && <span>decided by {a.decided_by_label} · {formatDateTime(a.decided_at)}</span>}
                  {a.invalidated_reason && <span className="text-destructive">{a.invalidated_reason}</span>}
                </div>
              </div>
              <div className="flex flex-col items-stretch justify-between gap-2 lg:w-56">
                <div className="text-right">
                  <p className="text-2xs uppercase tracking-wide text-muted-foreground">Amount</p>
                  <p className="text-2xl font-semibold tabular-nums">{formatMoney(a.amount)}</p>
                  <p className="text-2xs text-muted-foreground">{a.currency}</p>
                </div>
                {a.status === "PENDING" && (
                  <>
                    <Button className="gap-1.5" onClick={() => setActive(a)}>
                      <ClipboardCheck className="h-4 w-4" /> Review & decide
                    </Button>
                    {!a.can_decide && (
                      <p className="text-right text-2xs text-muted-foreground">
                        Your role{role ? ` (${role})` : ""} lacks this permission - the backend will refuse and log the attempt.
                      </p>
                    )}
                  </>
                )}
                {a.status === "APPROVED" && a.action === "CASHBACK_PAYOUT" && (
                  <Button variant="success" className="gap-1.5" disabled={!canExecute} loading={execute.isPending}
                    onClick={() => execute.mutate(a.approval_id)}>
                    <Play className="h-4 w-4" /> Send payouts
                  </Button>
                )}
                {a.procurement_request_id && (
                  <Button asChild size="sm" variant="ghost">
                    <Link href={`/supply/negotiations/${a.procurement_request_id}`}>Open negotiation</Link>
                  </Button>
                )}
                {a.status === "EXECUTED" && <p className="inline-flex items-center justify-end gap-1 text-2xs text-success"><CheckCircle2 className="h-3 w-3" />executed {formatRelativeTime(a.executed_at)}</p>}
                {a.status === "REJECTED" && <p className="inline-flex items-center justify-end gap-1 text-2xs text-destructive"><XCircle className="h-3 w-3" />rejected</p>}
              </div>
            </CardContent>
          </Card>
        ))}
      </div>
      <DecisionDialog
        open={Boolean(active)}
        onClose={() => setActive(null)}
        title={active?.title ?? ""}
        description={`${active?.action_label ?? ""} · ${active?.reference ?? ""}. This decision is recorded with your identity, the policy version and the terms hash.`}
        amount={active?.amount}
        currency={active?.currency}
        details={active ? termsList(active).slice(0, 8) : []}
        pending={decide.isPending}
        onDecide={(approve, note) => active && decide.mutate({ id: active.approval_id, approve, note }, { onSettled: () => setActive(null) })}
      />
    </div>
  );
}

function termsList(a: Approval): { label: string; value: React.ReactNode }[] {
  const d = a.details as Record<string, unknown>;
  const money = (k: string) => (d[k] != null ? formatMoney(String(d[k])) : null);
  const rows: { label: string; value: React.ReactNode }[] = [];
  const push = (label: string, value: React.ReactNode | null | undefined) => {
    if (value != null && value !== "") rows.push({ label, value });
  };
  push("Supplier", d.supplier_name as string);
  push("Product", d.product_name as string);
  push("Quantity", d.quantity as string);
  push("Unit price", money("unit_price"));
  push("Shipping", money("shipping"));
  push("Landed total", money("landed_total"));
  push("Delivery", d.lead_time_days != null ? `${String(d.lead_time_days)} days` : null);
  push("Budget", money("max_budget"));
  push("Invoice", d.invoice_number as string);
  push("Match", d.match_status as string);
  push("Payee", d.payee_email as string);
  push("Method", d.method as string);
  if (Array.isArray(d.recipients)) push("Recipients", String(d.recipients.length));
  push("Total", money("total"));
  return rows;
}

function TermsGrid({ approval }: { approval: Approval }) {
  const rows = termsList(approval);
  if (rows.length === 0) return null;
  return (
    <dl className="grid grid-cols-2 gap-x-4 gap-y-1 rounded-lg bg-muted/40 p-2.5 text-2xs sm:grid-cols-4">
      {rows.slice(0, 8).map((r) => (
        <div key={r.label} className="min-w-0">
          <dt className="text-muted-foreground">{r.label}</dt>
          <dd className="truncate font-medium tabular-nums">{r.value}</dd>
        </div>
      ))}
    </dl>
  );
}
