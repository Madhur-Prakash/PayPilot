"use client";

/**
 * The agent-to-agent conversation, as verified protocol messages - not chat.
 * Each row shows the typed message, who signed it, and whether it verified.
 */

import { AnimatePresence, motion } from "framer-motion";
import { ArrowRight, Bot, Building2, ChevronDown, Cpu, ShieldCheck, Truck } from "lucide-react";
import * as React from "react";

import { cn, formatDateTime } from "@/lib/utils";
import type { AgentMessage } from "@/types/supply";

const KIND_ICON = { BUYER: Bot, SUPPLIER: Truck, SYSTEM: Cpu } as const;

const TYPE_TONE: Record<string, string> = {
  PROCUREMENT_REQUEST: "bg-primary/10 text-primary",
  SUPPLIER_DISCOVERY: "bg-primary/10 text-primary",
  RFQ_CREATED: "bg-primary/10 text-primary",
  QUOTE_SUBMITTED: "bg-secondary text-secondary-foreground",
  COUNTEROFFER: "bg-warning/14 text-warning",
  OFFER_ACCEPTED: "bg-success/12 text-success",
  OFFER_REJECTED: "bg-muted text-muted-foreground",
  NEGOTIATION_EXPIRED: "bg-muted text-muted-foreground",
  RFQ_RESPONSE: "bg-muted text-muted-foreground",
  PURCHASE_ORDER_CREATED: "bg-success/12 text-success",
  INVOICE_ISSUED: "bg-secondary text-secondary-foreground",
  DELIVERY_UPDATE: "bg-secondary text-secondary-foreground",
  GOODS_RECEIVED: "bg-success/12 text-success",
  INVOICE_MATCHED: "bg-primary/10 text-primary",
  PAYMENT_REQUESTED: "bg-warning/14 text-warning",
  PAYMENT_APPROVED: "bg-success/12 text-success",
  PAYMENT_COMPLETED: "bg-success/12 text-success",
  PAYMENT_FAILED: "bg-destructive/12 text-destructive",
  PROCUREMENT_CLOSED: "bg-success/12 text-success",
};

export function MessageTimeline({
  messages,
  compact = false,
  emptyText = "No messages yet.",
}: {
  messages: AgentMessage[];
  compact?: boolean;
  emptyText?: string;
}) {
  const [open, setOpen] = React.useState<string | null>(null);
  if (messages.length === 0) {
    return <p className="py-6 text-center text-sm text-muted-foreground">{emptyText}</p>;
  }
  return (
    <ol className="relative space-y-2 before:absolute before:bottom-2 before:left-[13px] before:top-2 before:w-px before:bg-border">
      <AnimatePresence initial={false}>
        {messages.map((m) => {
          const Icon = KIND_ICON[m.sender_kind] ?? Building2;
          const expanded = open === m.message_id;
          return (
            <motion.li
              key={m.message_id}
              layout
              initial={{ opacity: 0, x: -6 }}
              animate={{ opacity: 1, x: 0 }}
              className="relative pl-9"
            >
              <span
                className={cn(
                  "absolute left-0 top-1 flex h-7 w-7 items-center justify-center rounded-full border bg-card",
                  m.sender_kind === "BUYER" && "border-primary/40 text-primary",
                  m.sender_kind === "SUPPLIER" && "border-border text-muted-foreground",
                  m.sender_kind === "SYSTEM" && "border-success/40 text-success",
                )}
              >
                <Icon className="h-3.5 w-3.5" />
              </span>
              <button
                type="button"
                onClick={() => setOpen(expanded ? null : m.message_id)}
                className="w-full rounded-xl border border-border bg-card px-3 py-2 text-left transition-colors hover:bg-muted/40 focus-ring"
              >
                <div className="flex flex-wrap items-center gap-1.5 text-2xs">
                  <span className={cn("rounded-md px-1.5 py-0.5 font-mono font-semibold", TYPE_TONE[m.message_type] ?? "bg-muted")}>
                    {m.message_type}
                  </span>
                  <span className="font-mono text-muted-foreground">{m.sender}</span>
                  <ArrowRight className="h-3 w-3 text-muted-foreground" />
                  <span className="font-mono text-muted-foreground">{m.recipient}</span>
                  {m.verified && (
                    <span className="inline-flex items-center gap-0.5 text-success" title={`Signed ${m.key_id}`}>
                      <ShieldCheck className="h-3 w-3" /> verified
                    </span>
                  )}
                  <span className="ml-auto text-muted-foreground">{formatDateTime(m.sent_at)}</span>
                  {!compact && <ChevronDown className={cn("h-3 w-3 transition-transform", expanded && "rotate-180")} />}
                </div>
                <p className="mt-1 text-xs leading-relaxed">{m.summary || m.message_type}</p>
              </button>
              {expanded && !compact && (
                <div className="mt-1 space-y-1 rounded-xl border border-dashed border-border bg-muted/30 p-2.5 text-2xs">
                  <p className="text-muted-foreground">
                    schema v{m.schema_version} · transport {m.transport} · key{" "}
                    <span className="font-mono">{m.key_id}</span> · signature{" "}
                    <span className="font-mono">{m.signature_preview}</span>
                  </p>
                  <pre className="max-h-56 overflow-auto rounded-lg bg-card p-2 font-mono text-[11px] leading-relaxed">
                    {JSON.stringify(m.payload, null, 2)}
                  </pre>
                </div>
              )}
            </motion.li>
          );
        })}
      </AnimatePresence>
    </ol>
  );
}
