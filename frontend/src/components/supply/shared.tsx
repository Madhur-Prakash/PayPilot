"use client";

/** Shared building blocks for the Supply, Finance and Governance screens. */

import { Check, CircleDashed, FlaskConical, Loader2, type LucideIcon, ShieldCheck, X } from "lucide-react";
import * as React from "react";

import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/overlays";
import { Badge, Card, CardContent, Label, Textarea } from "@/components/ui/primitives";
import { cn, formatMoney, titleCase, toNumber } from "@/lib/utils";
import type { PayPalMode } from "@/types/supply";

// --------------------------------------------------------------------------- //
// Page header
// --------------------------------------------------------------------------- //
export function PageHeader({
  title,
  description,
  actions,
  eyebrow,
}: {
  title: string;
  description?: React.ReactNode;
  actions?: React.ReactNode;
  eyebrow?: string;
}) {
  return (
    <div className="flex flex-wrap items-start justify-between gap-3">
      <div className="min-w-0">
        {eyebrow && (
          <p className="text-2xs font-semibold uppercase tracking-widest text-primary">{eyebrow}</p>
        )}
        <h2 className="text-xl font-semibold tracking-tight">{title}</h2>
        {description && <p className="mt-0.5 max-w-3xl text-sm text-muted-foreground">{description}</p>}
      </div>
      {actions && <div className="flex flex-wrap items-center gap-2">{actions}</div>}
    </div>
  );
}

// --------------------------------------------------------------------------- //
// Honest labelling
// --------------------------------------------------------------------------- //
export function ModeBadge({ mode, className }: { mode: PayPalMode | string | undefined; className?: string }) {
  if (!mode) return null;
  const tone =
    mode === "LIVE"
      ? "bg-success/12 text-success"
      : mode === "SANDBOX"
        ? "bg-primary/10 text-primary"
        : "bg-warning/14 text-warning";
  const Icon = mode === "SIMULATED" ? FlaskConical : ShieldCheck;
  return (
    <span className={cn("inline-flex items-center gap-1 rounded-md px-1.5 py-0.5 text-2xs font-semibold", tone, className)}>
      <Icon className="h-3 w-3" />
      {mode === "SIMULATED" ? "Simulated" : mode === "SANDBOX" ? "PayPal sandbox" : "PayPal live"}
    </span>
  );
}

export function SimulatedTag({ show = true, label = "simulated agent" }: { show?: boolean; label?: string }) {
  if (!show) return null;
  return (
    <Badge variant="outline" className="gap-1 text-2xs">
      <FlaskConical className="h-3 w-3" />
      {label}
    </Badge>
  );
}

// --------------------------------------------------------------------------- //
// Status
// --------------------------------------------------------------------------- //
const TONES: Record<string, string> = {
  // positive
  RECONCILED: "bg-success/12 text-success",
  PAID: "bg-success/12 text-success",
  MATCHED: "bg-success/12 text-success",
  WITHIN_TOLERANCE: "bg-success/12 text-success",
  APPROVED: "bg-success/12 text-success",
  EXECUTED: "bg-success/12 text-success",
  ACCEPTED: "bg-success/12 text-success",
  CAPTURED: "bg-success/12 text-success",
  COMPLETED: "bg-success/12 text-success",
  RECEIVED: "bg-success/12 text-success",
  VALID: "bg-success/12 text-success",
  ACTIVE: "bg-success/12 text-success",
  ONLINE: "bg-success/12 text-success",
  PROCESSED: "bg-success/12 text-success",
  VERIFIED: "bg-success/12 text-success",
  SIMULATED_VERIFIED: "bg-success/12 text-success",
  SUCCESS: "bg-success/12 text-success",
  // waiting on a person
  AWAITING_APPROVAL: "bg-warning/14 text-warning",
  PENDING: "bg-warning/14 text-warning",
  PAYMENT_APPROVAL_PENDING: "bg-warning/14 text-warning",
  PAYMENT_PENDING: "bg-warning/14 text-warning",
  PAYER_ACTION_REQUIRED: "bg-warning/14 text-warning",
  PARTIALLY_RECEIVED: "bg-warning/14 text-warning",
  RECOMMENDED: "bg-warning/14 text-warning",
  DISCREPANCY: "bg-destructive/12 text-destructive",
  OUT_OF_POLICY: "bg-warning/14 text-warning",
  SUSPENDED: "bg-warning/14 text-warning",
  // in motion
  SOURCING: "bg-primary/10 text-primary",
  NEGOTIATING: "bg-primary/10 text-primary",
  QUOTED: "bg-primary/10 text-primary",
  COUNTERED: "bg-primary/10 text-primary",
  FINAL_OFFER: "bg-primary/10 text-primary",
  ORDERED: "bg-primary/10 text-primary",
  INVITED: "bg-muted text-muted-foreground",
  RECEIVED_INVOICE: "bg-primary/10 text-primary",
  // negative
  REJECTED: "bg-destructive/12 text-destructive",
  DECLINED: "bg-muted text-muted-foreground",
  EXPIRED: "bg-muted text-muted-foreground",
  INVALIDATED: "bg-destructive/12 text-destructive",
  FAILED: "bg-destructive/12 text-destructive",
  INVALID: "bg-destructive/12 text-destructive",
  NO_ELIGIBLE_OFFER: "bg-destructive/12 text-destructive",
  CANCELLED: "bg-muted text-muted-foreground",
  REJECTED_SIG: "bg-destructive/12 text-destructive",
}

export function StatusPill({ status, className }: { status: string | null | undefined; className?: string }) {
  if (!status) return null;
  return (
    <span
      className={cn(
        "inline-flex items-center rounded-md px-1.5 py-0.5 text-2xs font-semibold capitalize",
        TONES[status] ?? (status === "REJECTED" ? TONES.REJECTED : "bg-muted text-muted-foreground"),
        className,
      )}
    >
      {status.toLowerCase().replace(/_/g, " ")}
    </span>
  );
}

export function RiskBadge({ level }: { level: string }) {
  const variant = level === "CRITICAL" ? "destructive" : level === "HIGH" ? "warning" : level === "WATCH" ? "secondary" : "success";
  return <Badge variant={variant as "destructive" | "warning" | "secondary" | "success"}>{titleCase(level)}</Badge>;
}

// --------------------------------------------------------------------------- //
// Metrics
// --------------------------------------------------------------------------- //
export function MetricTile({
  icon: Icon,
  label,
  value,
  hint,
  tone = "default",
}: {
  icon: LucideIcon;
  label: string;
  value: React.ReactNode;
  hint?: React.ReactNode;
  tone?: "default" | "success" | "warning" | "destructive" | "primary";
}) {
  const ring = {
    default: "bg-muted text-muted-foreground",
    success: "bg-success/12 text-success",
    warning: "bg-warning/14 text-warning",
    destructive: "bg-destructive/12 text-destructive",
    primary: "bg-primary/10 text-primary",
  }[tone];
  return (
    <Card>
      <CardContent className="flex items-start gap-3 p-4">
        <div className={cn("flex h-9 w-9 shrink-0 items-center justify-center rounded-lg", ring)}>
          <Icon className="h-4 w-4" />
        </div>
        <div className="min-w-0">
          <p className="text-2xs font-medium uppercase tracking-wide text-muted-foreground">{label}</p>
          <p className="mt-0.5 truncate text-lg font-semibold tabular-nums">{value}</p>
          {hint && <p className="mt-0.5 text-2xs text-muted-foreground">{hint}</p>}
        </div>
      </CardContent>
    </Card>
  );
}

export function PercentBar({ value, max = 1, className }: { value: string | number | null; max?: number; className?: string }) {
  const n = Math.max(0, Math.min((toNumber(value) ?? 0) / max, 1));
  const tone = n >= 0.9 ? "bg-success" : n >= 0.8 ? "bg-primary" : "bg-warning";
  return (
    <div className={cn("h-1.5 w-full overflow-hidden rounded-full bg-muted", className)}>
      <div className={cn("h-full rounded-full transition-all", tone)} style={{ width: `${n * 100}%` }} />
    </div>
  );
}

export function pct(value: string | number | null | undefined, decimals = 0): string {
  const n = toNumber(value);
  return n == null ? "--" : `${(n * 100).toFixed(decimals)}%`;
}

// --------------------------------------------------------------------------- //
// Lifecycle
// --------------------------------------------------------------------------- //
export const LIFECYCLE: { key: string; label: string; statuses: string[] }[] = [
  { key: "rfq", label: "RFQ", statuses: ["SOURCING"] },
  { key: "negotiation", label: "Negotiation", statuses: ["NEGOTIATING", "RECOMMENDED"] },
  { key: "approval", label: "Approval", statuses: ["AWAITING_APPROVAL"] },
  { key: "po", label: "Purchase order", statuses: ["APPROVED", "ORDERED"] },
  { key: "delivery", label: "Delivery", statuses: ["PARTIALLY_RECEIVED"] },
  { key: "receiving", label: "Receiving", statuses: ["RECEIVED"] },
  { key: "payment", label: "Payment", statuses: ["PAYMENT_PENDING", "PAID"] },
  { key: "reconciliation", label: "Reconciled", statuses: ["RECONCILED"] },
];

export function LifecycleStepper({ status, className }: { status: string; className?: string }) {
  const terminalFailure = ["REJECTED", "CANCELLED", "NO_ELIGIBLE_OFFER"].includes(status);
  const current = LIFECYCLE.findIndex((s) => s.statuses.includes(status));
  const index = status === "RECONCILED" ? LIFECYCLE.length : current;
  return (
    <ol className={cn("flex flex-wrap items-center gap-1.5", className)}>
      {LIFECYCLE.map((step, i) => {
        const done = index > i || status === "RECONCILED";
        const active = index === i && !terminalFailure;
        return (
          <li key={step.key} className="flex items-center gap-1.5">
            <span
              className={cn(
                "inline-flex items-center gap-1 rounded-full border px-2 py-0.5 text-2xs font-medium",
                done && "border-success/30 bg-success/10 text-success",
                active && "border-primary/40 bg-primary/10 text-primary",
                !done && !active && "border-border text-muted-foreground",
              )}
            >
              {done ? <Check className="h-3 w-3" /> : active ? <Loader2 className="h-3 w-3 animate-spin" /> : <CircleDashed className="h-3 w-3" />}
              {step.label}
            </span>
            {i < LIFECYCLE.length - 1 && <span className="h-px w-3 bg-border" />}
          </li>
        );
      })}
      {terminalFailure && <StatusPill status={status} className="ml-1" />}
    </ol>
  );
}

// --------------------------------------------------------------------------- //
// Decision dialog (approve / reject with a note)
// --------------------------------------------------------------------------- //
export function DecisionDialog({
  open,
  onClose,
  title,
  description,
  amount,
  currency = "USD",
  details,
  pending,
  onDecide,
}: {
  open: boolean;
  onClose: () => void;
  title: string;
  description?: React.ReactNode;
  amount?: string | null;
  currency?: string;
  details?: { label: string; value: React.ReactNode }[];
  pending?: boolean;
  onDecide: (approve: boolean, note: string) => void;
}) {
  const [note, setNote] = React.useState("");
  React.useEffect(() => {
    if (open) setNote("");
  }, [open]);
  return (
    <Dialog open={open} onOpenChange={(next) => !next && onClose()}>
      <DialogContent className="max-w-lg">
        <DialogHeader>
          <DialogTitle>{title}</DialogTitle>
          {description && <DialogDescription>{description}</DialogDescription>}
        </DialogHeader>
        {amount && (
          <div className="rounded-xl border border-border bg-muted/40 p-3">
            <p className="text-2xs uppercase tracking-wide text-muted-foreground">Amount being authorised</p>
            <p className="text-2xl font-semibold tabular-nums">
              {formatMoney(amount)} <span className="text-sm font-normal text-muted-foreground">{currency}</span>
            </p>
          </div>
        )}
        {details && details.length > 0 && (
          <dl className="grid grid-cols-2 gap-x-4 gap-y-1.5 text-xs">
            {details.map((d) => (
              <React.Fragment key={d.label}>
                <dt className="text-muted-foreground">{d.label}</dt>
                <dd className="text-right font-medium tabular-nums">{d.value}</dd>
              </React.Fragment>
            ))}
          </dl>
        )}
        <div className="space-y-1.5">
          <Label htmlFor="decision-note">Note (recorded in the audit trail)</Label>
          <Textarea id="decision-note" rows={2} value={note} onChange={(e) => setNote(e.target.value)} />
        </div>
        <DialogFooter>
          <Button variant="outline" className="gap-1.5" disabled={pending} onClick={() => onDecide(false, note)}>
            <X className="h-4 w-4" />
            Reject
          </Button>
          <Button className="gap-1.5" loading={pending} onClick={() => onDecide(true, note)}>
            <Check className="h-4 w-4" />
            Approve
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
