/**
 * Types for Supply Agents, approvals, PayPal and unified intelligence.
 *
 * Money arrives from the API as decimal strings (the backend never uses floats
 * for money); format with `formatMoney` / `formatCurrency`, which accept strings.
 */

export type Money = string;
export type PayPalMode = "LIVE" | "SANDBOX" | "SIMULATED";

// --------------------------------------------------------------------------- //
// Inventory intelligence
// --------------------------------------------------------------------------- //
export interface DemandAssessment {
  inventory_item_id: string;
  product_id: string;
  sku: string;
  product_name: string;
  unit: string;
  on_hand: string;
  available: string;
  on_order: string;
  velocity_recent: string;
  velocity_prior: string;
  demand_change_pct: string;
  days_of_cover: string | null;
  lead_time_days: number;
  stockout_risk: boolean;
  risk_level: "CRITICAL" | "HIGH" | "WATCH" | "HEALTHY" | "NONE";
  demand_increased: boolean;
  overstocked: boolean;
  suggested_quantity: string;
  required_within_days: number | null;
  required_by: string | null;
  target_cover_days: number;
  unit_cost: Money;
  selling_price: Money;
  revenue_at_risk: Money;
  reason: string;
  daily_units: { date: string; units: string }[];
  open_request_reference: string | null;
}

// --------------------------------------------------------------------------- //
// Supplier network
// --------------------------------------------------------------------------- //
export interface SupplierCatalogEntry {
  inventory_item_id: string;
  vendor_sku: string;
  indicative_unit_price: Money | null;
  minimum_order_quantity: string | null;
  available_quantity: string | null;
  lead_time_days: string | null;
  volume_breaks: { min_quantity: string; discount_pct: string }[];
}

export interface SupplierAgent {
  supplier_agent_id: string;
  vendor_id: string;
  agent_key: string;
  display_name: string;
  tagline: string;
  strategy: "PREMIUM_RELIABLE" | "LOW_PRICE_LIMITED" | "FLEXIBLE_VOLUME" | string;
  status: string;
  is_simulated: boolean;
  region: string;
  reliability_score: string;
  quality_score: string;
  on_time_rate: string;
  payment_terms: string;
  currency: string;
  shipping_flat: Money;
  shipping_per_unit: Money;
  free_shipping_threshold: Money;
  tax_rate: string;
  expedite_available: boolean;
  paypal_payee_configured: boolean;
  key_fingerprint: string;
  performance: {
    orders_completed: number;
    orders_on_time: number;
    units_ordered: string;
    units_received: string;
    invoices_received: number;
    invoice_discrepancies: number;
    negotiations_won: number;
    negotiations_total: number;
    total_savings: Money;
    last_performance_at: string | null;
  };
  catalog: SupplierCatalogEntry[];
  negotiation_history?: {
    session_id: string;
    status: string;
    rounds: number;
    procurement_reference: string;
    product_name: string;
    outcome_reason: string;
    created_at: string | null;
  }[];
}

// --------------------------------------------------------------------------- //
// Negotiation
// --------------------------------------------------------------------------- //
export interface ValidationIssue {
  code: string;
  message: string;
}

export interface Offer {
  offer_id: string;
  session_id: string;
  supplier_agent_id: string;
  round: number;
  sequence: number;
  direction: "SUPPLIER_TO_BUYER" | "BUYER_TO_SUPPLIER";
  kind: "QUOTE" | "COUNTER" | "FINAL" | "ACCEPT" | "REJECT" | "DECLINE";
  currency: string;
  unit_price: Money;
  quantity: string;
  subtotal: Money;
  shipping_cost: Money;
  tax_amount: Money;
  landed_total: Money;
  landed_unit_cost: Money;
  lead_time_days: number;
  payment_terms: string;
  valid_until: string | null;
  validation_status: "VALID" | "OUT_OF_POLICY" | "INVALID";
  validation_errors: ValidationIssue[];
  within_policy: boolean;
  proposed_by: "SUPPLIER_POLICY" | "BUYER_STRATEGY" | "LLM" | string;
  ai_proposal: Record<string, unknown>;
  rationale: string;
  score: Record<string, unknown>;
  terms_hash: string;
  created_at: string | null;
}

export interface NegotiationSession {
  session_id: string;
  status: string;
  current_round: number;
  max_rounds: number;
  outcome_reason: string;
  expires_at: string | null;
  is_simulated: boolean;
  supplier: SupplierAgent | null;
  opening_offer: Offer | null;
  latest_offer: Offer | null;
  best_offer_id: string | null;
  offers: Offer[];
}

export interface RankingRow {
  rank: number;
  session_id: string;
  offer_id: string;
  supplier_agent_id: string;
  agent_key: string;
  supplier_name: string;
  score: string;
  criteria: Record<string, string>;
  unit_price: Money;
  quantity: string;
  shipping: Money;
  tax: Money;
  landed_total: Money;
  landed_unit_cost: Money;
  lead_time_days: number;
  payment_terms: string;
  reliability: string;
  quality: string;
  budget_utilisation_pct: string;
  expected_margin_pct: string;
}

export interface Recommendation {
  winner: (Partial<RankingRow> & { supplier_name: string; supplier_agent_id: string }) | null;
  ranking: RankingRow[];
  ineligible: { session_id: string; supplier_name: string; agent_key: string; landed_total: Money;
    lead_time_days: number; violations: string[] }[];
  explanation: string;
  reasons: string[];
  weights: Record<string, string>;
}

export interface ProcurementPolicy {
  expected_selling_price: Money;
  target_margin: string;
  max_unit_cost: Money;
  target_unit_cost: Money;
  max_budget: Money;
  min_reliability: string;
  max_rounds: number;
  max_delivery_days: number;
  policy_version: string;
  notes: string[];
}

export interface Approval {
  approval_id: string;
  reference: string;
  action: "PROCUREMENT_PURCHASE" | "SUPPLIER_PAYMENT" | "CASHBACK_PAYOUT" | "CUSTOMER_INVOICE" | string;
  action_label: string;
  resource_type: string;
  resource_id: string;
  title: string;
  summary: string;
  amount: Money;
  currency: string;
  details: Record<string, unknown>;
  details_hash: string;
  policy_version: string;
  required_permission: string;
  risk_flags: string[];
  status: "PENDING" | "APPROVED" | "REJECTED" | "INVALIDATED" | "EXPIRED" | "EXECUTED";
  requested_by_type: string;
  requested_by_label: string;
  decided_by_label: string;
  decided_at: string | null;
  decision_note: string;
  expires_at: string | null;
  invalidated_reason: string;
  executed_at: string | null;
  correlation_id: string;
  procurement_request_id: string | null;
  created_at: string | null;
  can_decide?: boolean;
  executions?: Execution[];
}

export interface Execution {
  execution_id: string;
  approval_request_id: string;
  kind: string;
  resource_type: string;
  resource_id: string;
  amount: Money;
  currency: string;
  provider: string;
  mode: PayPalMode;
  method: string;
  status: string;
  idempotency_key: string;
  payee_email: string;
  paypal_order_id: string;
  paypal_authorization_id: string;
  paypal_capture_id: string;
  paypal_payout_batch_id: string;
  approve_url: string;
  debug_id: string;
  error: string;
  executed_at: string | null;
  completed_at: string | null;
  reconciled_at: string | null;
  correlation_id: string;
}

export interface InvoiceMatch {
  match_id: string;
  status: "MATCHED" | "WITHIN_TOLERANCE" | "DISCREPANCY";
  line_results: {
    line_id: string; sku: string; ordered: string; received: string; invoiced: string;
    po_unit_price: Money; invoice_unit_price: Money; verdict: string;
  }[];
  discrepancies: { code: string; sku: string; message: string; amount: Money }[];
  po_total: Money;
  received_value: Money;
  invoice_total: Money;
  variance_amount: Money;
  tolerance: Record<string, string>;
  matched_at: string | null;
}

export interface SupplierInvoice {
  supplier_invoice_id: string;
  invoice_number: string;
  status: string;
  purchase_order_id: string;
  purchase_order_reference: string;
  procurement_request_id: string | null;
  supplier_agent_id: string | null;
  supplier_name: string;
  currency: string;
  subtotal: Money;
  shipping_amount: Money;
  tax_amount: Money;
  total: Money;
  issued_at: string | null;
  due_date: string | null;
  payment_terms: string;
  lines: { sku: string; description: string; quantity: string; unit_price: Money; line_total: Money }[];
  paypal_invoice_id: string;
  is_simulated: boolean;
  approval_request_id: string | null;
  paid_amount: Money | null;
  paid_at: string | null;
  match: InvoiceMatch | null;
  execution: Execution | null;
}

export interface GoodsReceipt {
  goods_receipt_id: string;
  reference: string;
  purchase_order_id: string;
  purchase_order_reference?: string;
  procurement_request_id: string | null;
  received_at: string | null;
  lines: { line_id: string; sku: string; quantity_received: string; quantity_rejected: string; unit_price: Money }[];
  total_quantity: string;
  received_value: Money;
  is_partial: boolean;
  on_time: boolean | null;
  notes: string;
}

export interface Reconciliation {
  reconciliation_id: string;
  status: string;
  procurement_request_id: string | null;
  purchase_order_id: string;
  purchase_order_reference?: string;
  supplier_invoice_id: string;
  execution_id: string | null;
  po_total: Money;
  received_value: Money;
  invoice_total: Money;
  paid_amount: Money;
  variance_amount: Money;
  payment_reference: string;
  previous_unit_cost: Money | null;
  new_unit_cost: Money | null;
  previous_margin_pct: string | null;
  new_margin_pct: string | null;
  summary: Record<string, unknown>;
  reconciled_at: string | null;
}

export interface OrderBrief {
  purchase_order_id: string;
  reference: string;
  status: string;
  total_value: Money;
  currency: string;
  shipping_amount: Money;
  tax_amount: Money;
  payment_terms: string;
  expected_at: string | null;
  sent_at: string | null;
  received_at: string | null;
  lines: { line_id: string; sku: string; product_name: string; quantity_ordered: string;
    quantity_received: string; unit_price: Money; line_total: Money }[];
}

export interface ProcurementRequest {
  procurement_request_id: string;
  reference: string;
  rfq_reference: string;
  inventory_item_id: string;
  product_id: string | null;
  sku: string;
  product_name: string;
  unit: string;
  quantity: string;
  required_by: string | null;
  max_delivery_days: number;
  trigger: string;
  status: string;
  source: string;
  currency: string;
  correlation_id: string;
  conversation_id: string;
  policy: ProcurementPolicy;
  demand: Partial<DemandAssessment>;
  recommendation: Partial<Recommendation>;
  recommended_session_id: string | null;
  recommended_offer_id: string | null;
  selected_supplier_agent_id: string | null;
  approval_request_id: string | null;
  purchase_order_id: string | null;
  agent_run_id: string | null;
  baseline_landed_total: Money | null;
  final_landed_total: Money | null;
  savings_amount: Money | null;
  rfq_issued_at: string | null;
  rfq_deadline: string | null;
  closed_at: string | null;
  failure_reason: string;
  created_at: string | null;
  updated_at: string | null;
  session_count?: number;
  max_round?: number;
}

export interface ProcurementDetail extends ProcurementRequest {
  sessions: NegotiationSession[];
  message_count: number;
  purchase_order: OrderBrief | null;
  receipts: GoodsReceipt[];
  invoices: SupplierInvoice[];
  reconciliation: Reconciliation | null;
  readiness?: { ready: boolean; checks: { check: string; ok: boolean }[] };
  approval: Approval | null;
  can: {
    negotiate: boolean;
    approve: boolean;
    receive: boolean;
    match: boolean;
    approve_payment: boolean;
    execute_payment: boolean;
  };
}

export interface AgentMessage {
  message_id: string;
  conversation_id: string;
  correlation_id: string;
  sender: string;
  sender_kind: "BUYER" | "SUPPLIER" | "SYSTEM";
  recipient: string;
  recipient_kind: "BUYER" | "SUPPLIER" | "SYSTEM";
  message_type: string;
  schema_version: string;
  payload: Record<string, unknown>;
  summary: string;
  sent_at: string | null;
  verified: boolean;
  key_id: string;
  signature_preview: string;
  transport: string;
  is_simulated: boolean;
  procurement_request_id: string | null;
  session_id: string | null;
}

// --------------------------------------------------------------------------- //
// Unified intelligence
// --------------------------------------------------------------------------- //
export interface BusinessEvent {
  event_id: string;
  event_type: string;
  label: string;
  module: "growth" | "supply" | "finance" | "governance" | string;
  entity_type: string;
  entity_id: string | null;
  correlation_id: string;
  payload: Record<string, unknown>;
  delivery_status: string;
  created_at: string | null;
}

export interface PayPalStatus {
  mode: PayPalMode;
  environment: string;
  configured: boolean;
  webhook_configured: boolean;
  simulation_enabled: boolean;
  base_url: string;
  currency: string;
  client_id_hint: string;
  note: string;
  sync?: {
    synced_until: string | null;
    last_run_at: string | null;
    last_status: string;
    last_error: string;
    items_total: number;
    mode: string;
  };
  apis?: { name: string; path: string }[];
}

export interface TransactionIntelligenceCurrency {
  transactions: number;
  gross_revenue: Money;
  net_revenue: Money;
  fees: Money;
  refunded: Money;
  refund_count: number;
  refund_rate_pct: string;
  payment_failure_rate_pct: string;
  average_order_value: Money;
  unique_payers: number;
  repeat_payers: number;
  repeat_payer_rate_pct: string;
  gross_change_pct: string | null;
  previous_gross_revenue: Money;
  daily: { date: string; gross: Money }[];
}

export interface TransactionIntelligence {
  has_data: boolean;
  days: number;
  period_start?: string;
  period_end?: string;
  modes?: string[];
  is_simulated?: boolean;
  currencies: Record<string, TransactionIntelligenceCurrency>;
}

export interface CommandCenter {
  period: { days: number; start: string; end: string };
  currency: string;
  kpis: { key: string; label: string; value: number; previous_value: number | null; change_pct: number | null;
    unit: string; direction: "UP_IS_GOOD" | "DOWN_IS_GOOD" | "NEUTRAL"; is_anomaly: boolean }[];
  financials: { revenue: Money; net_sales: Money; gross_profit: Money; gross_margin_pct: string; orders: number; discounts: Money };
  growth: { open_opportunities: number; opportunity_value: Money };
  inventory: { status_counts: Record<string, number>; stock_value: Money; at_risk: DemandAssessment[]; tracked_items: number };
  procurement: {
    requests_by_status: Record<string, number>;
    active_negotiations: number;
    spend: Money;
    savings: Money;
    outstanding_invoices: number;
    outstanding_amount: Money;
    active_requests: { procurement_request_id: string; reference: string; status: string; product_name: string;
      quantity: string; max_budget: Money; final_landed_total: Money | null }[];
    upcoming_deliveries: { purchase_order_id: string; reference: string; status: string; expected_at: string | null; total_value: Money }[];
  };
  suppliers: { supplier_agent_id: string; display_name: string; reliability_score: string; on_time_rate: string; status: string; is_simulated: boolean }[];
  approvals: { pending: number; items: Approval[] };
  agents: { run_id: string; agent_name: string; workflow: string; status: string; summary: string; used_fallback: boolean; created_at: string | null }[];
  financial_events: { execution_id: string; kind: string; status: string; mode: PayPalMode; method: string; amount: Money; currency: string; reference: string; created_at: string | null }[];
  events: BusinessEvent[];
  paypal: PayPalStatus & { intelligence: TransactionIntelligence };
  margins: { purchase_order_id: string; previous_unit_cost: Money; new_unit_cost: Money; previous_margin_pct: string;
    new_margin_pct: string; reconciled_at: string | null; summary: Record<string, unknown> }[];
}

export interface SupplyOverview {
  inventory: CommandCenter["inventory"];
  procurement: CommandCenter["procurement"];
  suppliers: CommandCenter["suppliers"];
  approvals: CommandCenter["approvals"];
  events: BusinessEvent[];
  reorder: DemandAssessment[];
  recent_receipts: GoodsReceipt[];
  currency: string;
}

export interface PayPalTransactionRow {
  id: string;
  paypal_transaction_id: string;
  event_code: string;
  status_code: string;
  category: string;
  currency: string;
  gross_amount: Money;
  fee_amount: Money;
  net_amount: Money;
  initiated_at: string | null;
  invoice_id: string;
  payer_name: string;
  repeat_key: string;
  item_count: number;
  mode: PayPalMode;
}

export interface PayPalInvoiceRow {
  invoice_record_id: string;
  paypal_invoice_id: string;
  invoice_number: string;
  status: string;
  recipient_email: string;
  recipient_name: string;
  currency: string;
  amount: Money;
  due_date: string | null;
  payer_view_url: string;
  note: string;
  mode: PayPalMode;
  campaign_id: string | null;
  sent_at: string | null;
  paid_at: string | null;
  created_at: string | null;
}

export interface PayPalSubscriptionRow {
  subscription_record_id: string;
  paypal_subscription_id: string;
  plan_id: string;
  plan_name: string;
  status: string;
  subscriber_name: string;
  currency: string;
  amount: Money;
  interval: string;
  failed_payments: number;
  last_payment_at: string | null;
  next_billing_at: string | null;
  started_at: string | null;
  mode: PayPalMode;
  needs_recovery: boolean;
}

/** Subscription revenue radar - one Bryntum Scheduler row per PayPal subscriber. */
export type RadarRisk = "healthy" | "at_risk" | "suspended" | "cancelled";
export type RadarEventKind =
  | "paid" | "failed" | "retry" | "suspended" | "recovered" | "cancelled" | "scheduled" | "at_risk" | "paused";

export interface RadarResource {
  id: string;
  name: string;
  plan: string;
  status: string;
  risk: RadarRisk;
  amount: Money;
  currency: string;
  interval: string;
  failed_payments: number;
  next_billing_at: string;
  paypal_subscription_id: string;
  mode: PayPalMode;
}

export interface RadarEvent {
  id: string;
  resourceId: string;
  startDate: string;
  endDate: string;
  name: string;
  kind: RadarEventKind;
  amount: Money;
}

export interface SubscriptionRadar {
  window: { start: string; end: string; now: string };
  resources: RadarResource[];
  events: RadarEvent[];
  summary: {
    subscribers: number;
    active: number;
    monthly_recurring_revenue: Money;
    at_risk_revenue: Money;
    at_risk: number;
    collected_in_window: Money;
    projected_next_30_days: Money;
    at_risk_next_30_days: Money;
    renewals_next_7_days: number;
    recovered: number;
    currency: string;
  };
}

export interface WebhookEventRow {
  webhook_event_id: string;
  event_id: string;
  event_type: string;
  resource_type: string;
  resource_id: string;
  summary: string;
  verification_status: string;
  processing_status: string;
  attempts: number;
  error: string;
  mode: PayPalMode;
  received_at: string | null;
  processed_at: string | null;
}
