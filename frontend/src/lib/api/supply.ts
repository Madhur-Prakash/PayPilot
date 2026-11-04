/**
 * API calls for Supply Agents, approvals, PayPal and unified intelligence.
 * Components never call these directly - use the hooks in `@/hooks/use-supply`.
 */

import { apiGet, apiGetWithMeta, apiPost, apiPostWithMeta } from "@/lib/api/client";
import type { Paginated } from "@/types/api";
import type {
  AgentMessage,
  Approval,
  BusinessEvent,
  CommandCenter,
  DemandAssessment,
  Execution,
  GoodsReceipt,
  InvoiceMatch,
  PayPalInvoiceRow,
  PayPalStatus,
  PayPalSubscriptionRow,
  PayPalTransactionRow,
  ProcurementDetail,
  ProcurementRequest,
  Reconciliation,
  SupplierAgent,
  SupplierInvoice,
  SupplyOverview,
  TransactionIntelligence,
  WebhookEventRow,
} from "@/types/supply";

export interface ProcurementCreate {
  inventory_item_id: string;
  quantity?: number;
  target_margin?: number;
  max_delivery_days?: number;
  min_reliability?: number;
  max_rounds?: number;
  budget_cap?: number;
  auto_negotiate?: boolean;
  note?: string;
}

export const intelligenceApi = {
  commandCenter: (days = 30) => apiGet<CommandCenter>("/command-center", { params: { days } }),
  events: (params?: { limit?: number; module?: string; correlation_id?: string }) =>
    apiGet<BusinessEvent[]>("/events", { params }),
  signals: () => apiGet<Record<string, unknown>>("/intelligence/signals"),
};

export const supplyApi = {
  overview: () => apiGet<SupplyOverview>("/supply/overview"),
  demand: () => apiGetWithMeta<DemandAssessment[]>("/supply/demand"),
  suppliers: () => apiGet<SupplierAgent[]>("/suppliers"),
  supplier: (id: string) => apiGet<SupplierAgent>(`/suppliers/${id}`),
  procurements: (params?: { page?: number; page_size?: number; status?: string }) =>
    apiGet<Paginated<ProcurementRequest>>("/procurement", { params }),
  procurement: (id: string) => apiGet<ProcurementDetail>(`/procurement/${id}`),
  createProcurement: (payload: ProcurementCreate) => apiPost<ProcurementDetail>("/procurement", payload),
  autopilot: (payload: { inventory_item_id?: string }) =>
    apiPostWithMeta<ProcurementDetail | null>("/procurement/autopilot", payload),
  advance: (id: string) => apiPostWithMeta<ProcurementDetail>(`/procurement/${id}/advance`),
  negotiate: (id: string) => apiPost<ProcurementDetail>(`/procurement/${id}/negotiate`),
  decide: (id: string, approve: boolean, note?: string) =>
    apiPost<ProcurementDetail>(`/procurement/${id}/approve`, { approve, note }),
  messages: (id: string) => apiGet<AgentMessage[]>(`/procurement/${id}/messages`),
  allMessages: (params?: { message_type?: string; limit?: number }) =>
    apiGetWithMeta<AgentMessage[]>("/agent-messages", { params }),
  receive: (orderId: string, lines: { line_id: string; quantity: number }[], notes?: string) =>
    apiPost<GoodsReceipt>(`/purchase-orders/${orderId}/goods-receipts`, { lines, notes }),
  receipts: () => apiGet<GoodsReceipt[]>("/goods-receipts"),
  invoices: (status?: string) => apiGet<SupplierInvoice[]>("/supplier-invoices", { params: { status } }),
  match: (invoiceId: string) => apiPost<InvoiceMatch>(`/supplier-invoices/${invoiceId}/match`),
  approvePayment: (invoiceId: string, approve: boolean, note?: string) =>
    apiPost<SupplierInvoice>(`/supplier-invoices/${invoiceId}/approve-payment`, { approve, note }),
  pay: (invoiceId: string) => apiPost<Execution>(`/supplier-invoices/${invoiceId}/pay`),
  capture: (executionId: string) => apiPost<Execution>(`/payments/${executionId}/capture`),
  reconciliations: () => apiGet<Reconciliation[]>("/reconciliations"),
  reconcile: (orderId: string) => apiPost<Reconciliation>(`/purchase-orders/${orderId}/reconcile`),
};

export const approvalsApi = {
  list: (status?: string) => apiGetWithMeta<Approval[]>("/approvals", { params: { status } }),
  get: (id: string) => apiGet<Approval>(`/approvals/${id}`),
  decide: (id: string, approve: boolean, note?: string) =>
    apiPost<Approval>(`/approvals/${id}/decide`, { approve, note }),
  execute: (id: string) => apiPost<Execution>(`/approvals/${id}/execute`),
  payments: (kind?: string) => apiGet<Execution[]>("/payments", { params: { kind } }),
};

export const paypalApi = {
  status: () => apiGet<PayPalStatus>("/paypal/status"),
  sync: (days?: number) => apiPost<Record<string, unknown>>("/paypal/sync", { days }),
  transactions: (params?: { page?: number; page_size?: number; category?: string }) =>
    apiGet<Paginated<PayPalTransactionRow>>("/paypal/transactions", { params }),
  intelligence: (days = 30) => apiGet<TransactionIntelligence>("/paypal/intelligence", { params: { days } }),
  webhooks: () => apiGet<WebhookEventRow[]>("/paypal/webhooks/events"),
  simulateWebhook: (payload: { event_type: string; execution_id?: string; subscription_record_id?: string }) =>
    apiPost<{ outcome: string; event: WebhookEventRow | null }>("/paypal/webhooks/simulate", payload),
  reprocessWebhook: (id: string) => apiPost<WebhookEventRow>(`/paypal/webhooks/${id}/reprocess`),
  invoices: () => apiGet<PayPalInvoiceRow[]>("/paypal/invoices"),
  createInvoice: (payload: {
    recipient_email: string;
    recipient_name?: string;
    items: { name: string; quantity: number; unit_amount: number; description?: string }[];
    note?: string;
    due_date?: string;
    send?: boolean;
  }) => apiPost<PayPalInvoiceRow>("/paypal/invoices", payload),
  invoiceAction: (id: string, action: "remind" | "cancel" | "refresh", note?: string) =>
    apiPost<PayPalInvoiceRow>(`/paypal/invoices/${id}/action`, { action, note }),
  requestCashback: (payload: { recipients: { email: string; amount: number }[]; note?: string; campaign_id?: string }) =>
    apiPost<Approval>("/paypal/payouts/cashback", payload),
  payouts: () => apiGet<Execution[]>("/paypal/payouts"),
  refreshPayout: (id: string) => apiPost<Execution>(`/paypal/payouts/${id}/refresh`),
  subscriptions: () => apiGetWithMeta<PayPalSubscriptionRow[]>("/paypal/subscriptions"),
  subscriptionAction: (id: string, action: "suspend" | "activate" | "cancel" | "recover", reason?: string) =>
    apiPost<PayPalSubscriptionRow>(`/paypal/subscriptions/${id}/action`, { action, reason }),
  plans: () => apiGet<{ plans: Record<string, unknown>[]; mode: string }>("/paypal/plans"),
  createPlan: (payload: { name: string; amount: number; interval_unit?: string; trial_days?: number }) =>
    apiPost<Record<string, unknown>>("/paypal/plans", payload),
};
