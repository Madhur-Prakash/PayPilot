"use client";

/** PayPal subscriptions: plans, lifecycle actions and failed-payment recovery. */

import type { ColDef } from "ag-grid-community";
import { AlertTriangle, Plus, Repeat, Wallet } from "lucide-react";
import * as React from "react";

import { ErrorState } from "@/components/common/states";
import { DataGrid } from "@/components/data/data-grid";
import { MetricTile, ModeBadge, PageHeader, StatusPill } from "@/components/supply/shared";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle, Input, Label } from "@/components/ui/primitives";
import { useCreatePlan, usePayPalPlans, usePayPalSubscriptions, useSubscriptionAction } from "@/hooks/use-supply";
import { formatDate, formatMoney, toNumber } from "@/lib/utils";
import { useAuthStore } from "@/stores/auth";
import type { PayPalSubscriptionRow } from "@/types/supply";

export default function SubscriptionsPage() {
  const { data, isLoading, error, refetch } = usePayPalSubscriptions();
  const plans = usePayPalPlans();
  const action = useSubscriptionAction();
  const createPlan = useCreatePlan();
  const canManage = useAuthStore((s) => s.can("paypal:manage"));
  const [planName, setPlanName] = React.useState("Bean Club - 1 bag monthly");
  const [planPrice, setPlanPrice] = React.useState("17.00");
  const meta = (data?.meta ?? {}) as Record<string, string | number>;

  const columns = React.useMemo<ColDef<PayPalSubscriptionRow>[]>(() => [
    { field: "subscriber_name", headerName: "Subscriber" },
    { field: "plan_name", headerName: "Plan", minWidth: 200 },
    { headerName: "Amount", valueGetter: (p) => toNumber(p.data?.amount), valueFormatter: (p) => `${formatMoney(p.value)}/mo`, maxWidth: 130 },
    { field: "status", headerName: "Status", cellRenderer: (p: { value: string }) => <StatusPill status={p.value} />, maxWidth: 130 },
    { field: "failed_payments", headerName: "Failed", maxWidth: 100,
      cellClass: (p) => ((p.value ?? 0) > 0 ? "text-destructive font-semibold" : "") },
    { field: "next_billing_at", headerName: "Next billing", valueFormatter: (p) => formatDate(p.value as string), maxWidth: 140 },
    { field: "mode", headerName: "Mode", cellRenderer: (p: { value: string }) => <ModeBadge mode={p.value} />, maxWidth: 150 },
    {
      headerName: "Actions", minWidth: 200, sortable: false, filter: false,
      cellRenderer: (p: { data?: PayPalSubscriptionRow }) => {
        const row = p.data;
        if (!row || !canManage) return null;
        return (
          <div className="flex items-center gap-2 text-2xs">
            {row.needs_recovery && (
              <button type="button" className="text-primary hover:underline"
                onClick={() => action.mutate({ id: row.subscription_record_id, action: "recover", reason: "Payment method updated" })}>recover</button>
            )}
            {row.status === "ACTIVE" && (
              <button type="button" className="text-warning hover:underline"
                onClick={() => action.mutate({ id: row.subscription_record_id, action: "suspend", reason: "Paused at subscriber request" })}>pause</button>
            )}
            {row.status !== "CANCELLED" && (
              <button type="button" className="text-destructive hover:underline"
                onClick={() => action.mutate({ id: row.subscription_record_id, action: "cancel", reason: "Cancelled by merchant" })}>cancel</button>
            )}
          </div>
        );
      },
    },
  ], [action, canManage]);

  return (
    <div className="space-y-5">
      <PageHeader eyebrow="Finance" title="Subscriptions"
        description="Recurring PayPal subscriptions. Failed payments arrive by webhook and surface here - and as a growth opportunity - for recovery." />
      <div className="grid gap-3 sm:grid-cols-3">
        <MetricTile icon={Repeat} tone="primary" label="Active subscriptions" value={meta.active ?? "--"} />
        <MetricTile icon={Wallet} tone="success" label="Monthly recurring revenue" value={formatMoney(String(meta.monthly_recurring_revenue ?? "0"))} />
        <MetricTile icon={AlertTriangle} tone="warning" label="At risk" value={meta.at_risk ?? 0} hint={`${formatMoney(String(meta.at_risk_revenue ?? "0"))}/month with failed payments`} />
      </div>
      {error && <ErrorState error={error} onRetry={() => void refetch()} />}
      <Card>
        <CardContent className="p-3">
          <DataGrid rows={data?.data} columns={columns} loading={isLoading} getRowId={(r) => r.subscription_record_id}
            emptyMessage="No subscriptions recorded yet." />
        </CardContent>
      </Card>
      <Card>
        <CardHeader className="pb-2"><CardTitle className="text-base">Plans</CardTitle></CardHeader>
        <CardContent className="space-y-3">
          <div className="flex flex-wrap gap-2">
            {(plans.data?.plans ?? []).map((plan) => (
              <span key={String(plan.id)} className="rounded-lg border border-border px-2.5 py-1 text-xs">
                {String(plan.name)} · {formatMoney(String(plan.amount))}/{String(plan.interval_unit).toLowerCase()}
              </span>
            ))}
            {(plans.data?.plans ?? []).length === 0 && <p className="text-sm text-muted-foreground">No plans created in this session yet.</p>}
          </div>
          {canManage && (
            <div className="flex flex-wrap items-end gap-2">
              <div className="space-y-1"><Label htmlFor="plan-name">Plan name</Label><Input id="plan-name" value={planName} onChange={(e) => setPlanName(e.target.value)} className="w-64" /></div>
              <div className="space-y-1"><Label htmlFor="plan-price">Monthly price</Label><Input id="plan-price" type="number" value={planPrice} onChange={(e) => setPlanPrice(e.target.value)} className="w-28" /></div>
              <Button size="sm" className="gap-1.5" loading={createPlan.isPending}
                onClick={() => createPlan.mutate({ name: planName, amount: Number(planPrice), interval_unit: "MONTH" })}>
                <Plus className="h-3.5 w-3.5" /> Create plan
              </Button>
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
