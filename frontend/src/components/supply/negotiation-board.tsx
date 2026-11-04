"use client";

/**
 * The negotiation board: one column per independent supplier agent, every move in
 * order. Buyer counters sit on the right, supplier offers on the left - and every
 * offer shows what the *backend* concluded about it (valid / outside policy), as
 * distinct from what an AI proposed.
 */

import { motion } from "framer-motion";
import { AlertTriangle, Bot, CheckCircle2, Crown, ShieldAlert, Sparkles, Truck } from "lucide-react";
import * as React from "react";

import { pct, SimulatedTag, StatusPill } from "@/components/supply/shared";
import {
  Badge,
  Card,
  CardContent,
  CardHeader,
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from "@/components/ui/primitives";
import { cn, formatMoney, toNumber } from "@/lib/utils";
import type { NegotiationSession, Offer } from "@/types/supply";

const STRATEGY_LABEL: Record<string, string> = {
  PREMIUM_RELIABLE: "Premium & reliable",
  LOW_PRICE_LIMITED: "Low price, limited stock",
  FLEXIBLE_VOLUME: "Flexible negotiator",
};

export function NegotiationBoard({
  sessions,
  maxUnitCost,
  targetUnitCost,
  recommendedSessionId,
}: {
  sessions: NegotiationSession[];
  maxUnitCost: string;
  targetUnitCost: string;
  recommendedSessionId: string | null;
}) {
  if (sessions.length === 0) {
    return (
      <Card>
        <CardContent className="p-6 text-center text-sm text-muted-foreground">
          The Buyer Agent has not invited any supplier agents yet. Advance the negotiation to send the RFQ.
        </CardContent>
      </Card>
    );
  }
  return (
    <div className={cn("grid gap-4", sessions.length >= 3 ? "lg:grid-cols-3" : sessions.length === 2 ? "lg:grid-cols-2" : "")}>
      {sessions.map((session) => (
        <SupplierColumn
          key={session.session_id}
          session={session}
          maxUnitCost={maxUnitCost}
          targetUnitCost={targetUnitCost}
          recommended={session.session_id === recommendedSessionId}
        />
      ))}
    </div>
  );
}

function SupplierColumn({
  session,
  maxUnitCost,
  targetUnitCost,
  recommended,
}: {
  session: NegotiationSession;
  maxUnitCost: string;
  targetUnitCost: string;
  recommended: boolean;
}) {
  const supplier = session.supplier;
  const latest = session.latest_offer;
  return (
    <Card className={cn("flex flex-col overflow-hidden", recommended && "ring-2 ring-success/60")}>
      <CardHeader className="space-y-2 border-b border-border bg-muted/30 pb-3">
        <div className="flex items-start justify-between gap-2">
          <div className="min-w-0">
            <div className="flex items-center gap-1.5">
              {recommended && <Crown className="h-4 w-4 text-success" />}
              <p className="truncate font-semibold">{supplier?.display_name ?? "Supplier"}</p>
            </div>
            <p className="truncate text-2xs text-muted-foreground">
              {STRATEGY_LABEL[supplier?.strategy ?? ""] ?? supplier?.strategy} · {supplier?.region}
            </p>
          </div>
          <StatusPill status={session.status} />
        </div>
        <div className="flex flex-wrap items-center gap-1.5 text-2xs">
          <Badge variant="outline">reliability {pct(supplier?.reliability_score)}</Badge>
          <Badge variant="outline">{supplier?.payment_terms?.replace("_", " ")}</Badge>
          <span className="font-mono text-muted-foreground" title="Agent identity on the protocol">
            {supplier?.agent_key}
          </span>
          <SimulatedTag show={session.is_simulated} />
        </div>
        <PriceTrajectory offers={session.offers} maxUnitCost={maxUnitCost} targetUnitCost={targetUnitCost} />
      </CardHeader>

      <CardContent className="flex-1 space-y-2 p-3">
        {session.offers.length === 0 && (
          <p className="py-6 text-center text-2xs text-muted-foreground">Waiting for a reply to the RFQ…</p>
        )}
        {session.offers.map((offer, i) => (
          <OfferBubble key={offer.offer_id} offer={offer} index={i} />
        ))}
        {session.outcome_reason && (
          <p className="rounded-lg bg-muted/60 px-2.5 py-1.5 text-2xs text-muted-foreground">{session.outcome_reason}</p>
        )}
      </CardContent>

      {latest && (
        <div className="grid grid-cols-3 gap-2 border-t border-border bg-muted/20 p-3 text-center">
          <Figure label="Unit" value={formatMoney(latest.unit_price)} />
          <Figure label="Landed" value={formatMoney(latest.landed_total)} />
          <Figure label="Delivery" value={`${latest.lead_time_days}d`} />
        </div>
      )}
    </Card>
  );
}

function Figure({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <p className="text-2xs uppercase tracking-wide text-muted-foreground">{label}</p>
      <p className="text-sm font-semibold tabular-nums">{value}</p>
    </div>
  );
}

function OfferBubble({ offer, index }: { offer: Offer; index: number }) {
  const buyer = offer.direction === "BUYER_TO_SUPPLIER";
  const ai = offer.ai_proposal as { accepted?: boolean; validation?: string; counter_unit_price?: number } | undefined;
  const aiTried = ai && Object.keys(ai).length > 0;
  return (
    <motion.div
      initial={{ opacity: 0, y: 6 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ delay: Math.min(index * 0.03, 0.3) }}
      className={cn("flex", buyer ? "justify-end" : "justify-start")}
    >
      <div
        className={cn(
          "max-w-[92%] rounded-xl border px-2.5 py-2 text-xs",
          buyer ? "border-primary/25 bg-primary/5" : "border-border bg-card",
        )}
      >
        <div className="mb-1 flex flex-wrap items-center gap-1.5 text-2xs">
          {buyer ? <Bot className="h-3 w-3 text-primary" /> : <Truck className="h-3 w-3 text-muted-foreground" />}
          <span className="font-semibold">{buyer ? "Buyer Agent" : "Supplier agent"}</span>
          <span className="text-muted-foreground">
            · round {offer.round} · {offer.kind.toLowerCase()}
          </span>
          {offer.proposed_by === "LLM" && (
            <Badge variant="default" className="gap-1 text-2xs">
              <Sparkles className="h-3 w-3" />
              AI-proposed · validated
            </Badge>
          )}
          {aiTried && ai?.accepted === false && (
            <Tooltip>
              <TooltipTrigger asChild>
                <span className="inline-flex items-center gap-1 rounded-md bg-warning/14 px-1.5 py-0.5 font-semibold text-warning">
                  <ShieldAlert className="h-3 w-3" />
                  AI proposal refused
                </span>
              </TooltipTrigger>
              <TooltipContent className="max-w-xs">
                The model proposed {String(ai?.counter_unit_price ?? "a price")}; the backend refused it: {ai?.validation}
              </TooltipContent>
            </Tooltip>
          )}
        </div>
        <div className="flex flex-wrap items-baseline gap-x-3 gap-y-0.5 tabular-nums">
          <span className="text-sm font-semibold">{formatMoney(offer.unit_price)}</span>
          <span className="text-muted-foreground">× {toNumber(offer.quantity)}</span>
          {!buyer && <span className="text-muted-foreground">ship {formatMoney(offer.shipping_cost)}</span>}
          {!buyer && <span className="text-muted-foreground">{offer.lead_time_days}d</span>}
        </div>
        {!buyer && (
          <p className="mt-0.5 text-2xs text-muted-foreground tabular-nums">
            Landed {formatMoney(offer.landed_total)} ({formatMoney(offer.landed_unit_cost)}/unit)
          </p>
        )}
        {offer.rationale && <p className="mt-1 text-2xs leading-relaxed text-foreground/80">{offer.rationale}</p>}
        {!buyer && (
          <div className="mt-1.5">
            {offer.within_policy ? (
              <span className="inline-flex items-center gap-1 text-2xs font-medium text-success">
                <CheckCircle2 className="h-3 w-3" /> Backend-validated: inside policy
              </span>
            ) : (
              <span className="inline-flex items-start gap-1 text-2xs font-medium text-warning">
                <AlertTriangle className="mt-px h-3 w-3 shrink-0" />
                {offer.validation_errors[0]?.message ?? "Outside policy"}
              </span>
            )}
          </div>
        )}
      </div>
    </motion.div>
  );
}

/** Supplier unit price per move, against the merchant's ceiling and target. */
function PriceTrajectory({
  offers,
  maxUnitCost,
  targetUnitCost,
}: {
  offers: Offer[];
  maxUnitCost: string;
  targetUnitCost: string;
}) {
  const supplierPoints = offers.filter((o) => o.direction === "SUPPLIER_TO_BUYER").map((o) => toNumber(o.landed_unit_cost) ?? 0);
  const buyerPoints = offers.filter((o) => o.direction === "BUYER_TO_SUPPLIER").map((o) => toNumber(o.unit_price) ?? 0);
  const ceiling = toNumber(maxUnitCost) ?? 0;
  const target = toNumber(targetUnitCost) ?? 0;
  const all = [...supplierPoints, ...buyerPoints, ceiling, target].filter((n) => n > 0);
  if (supplierPoints.length === 0 || all.length === 0) return null;
  const min = Math.min(...all) * 0.97;
  const max = Math.max(...all) * 1.03;
  const W = 260;
  const H = 54;
  const steps = Math.max(supplierPoints.length, buyerPoints.length + 1, 2);
  const x = (i: number) => (i / (steps - 1)) * (W - 8) + 4;
  const y = (v: number) => H - 4 - ((v - min) / (max - min || 1)) * (H - 8);
  const path = (points: number[], offset = 0) =>
    points.map((v, i) => `${i === 0 ? "M" : "L"}${x(i + offset).toFixed(1)},${y(v).toFixed(1)}`).join(" ");
  return (
    <div>
      <svg viewBox={`0 0 ${W} ${H}`} className="h-14 w-full" role="img" aria-label="Price trajectory">
        <line x1={0} x2={W} y1={y(ceiling)} y2={y(ceiling)} className="stroke-destructive/60" strokeDasharray="4 3" />
        <line x1={0} x2={W} y1={y(target)} y2={y(target)} className="stroke-success/60" strokeDasharray="2 3" />
        <path d={path(supplierPoints)} className="fill-none stroke-foreground/70" strokeWidth={1.8} />
        {buyerPoints.length > 0 && <path d={path(buyerPoints, 1)} className="fill-none stroke-primary" strokeWidth={1.6} />}
        {supplierPoints.map((v, i) => (
          <circle key={`s${i}`} cx={x(i)} cy={y(v)} r={2.4} className="fill-foreground/80" />
        ))}
        {buyerPoints.map((v, i) => (
          <circle key={`b${i}`} cx={x(i + 1)} cy={y(v)} r={2.2} className="fill-primary" />
        ))}
      </svg>
      <div className="flex flex-wrap gap-3 text-2xs text-muted-foreground">
        <span className="inline-flex items-center gap-1"><span className="h-0.5 w-3 bg-foreground/70" /> supplier landed/unit</span>
        <span className="inline-flex items-center gap-1"><span className="h-0.5 w-3 bg-primary" /> buyer counter</span>
        <span className="inline-flex items-center gap-1 text-destructive">ceiling {formatMoney(maxUnitCost)}</span>
        <span className="inline-flex items-center gap-1 text-success">target {formatMoney(targetUnitCost)}</span>
      </div>
    </div>
  );
}
