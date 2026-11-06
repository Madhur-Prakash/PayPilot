/** Types for the sponsor integrations, the evidence search, the Gantt timeline and AG Studio datasets. */

export type IntegrationMode =
  | "LIVE"
  | "SANDBOX"
  | "SIMULATED"
  | "DISABLED"
  | "NOT_USED"
  | "BLUEPRINT"
  | "COLLECTION"
  | "SPEC_EXPORT";

export interface IntegrationRow {
  key: string;
  name: string;
  category: "core" | "sponsor";
  mode: IntegrationMode;
  used_for: string;
  where: string;
}

export interface IntegrationStatus {
  integrations: IntegrationRow[];
  elastic: { configured: boolean; reachable: boolean | null; index: string; cluster?: string; version?: string; error?: string };
  zapier: ZapierState;
}

export interface ZapierState {
  configured: boolean;
  event_types: string[];
  pending: number;
  delivered: number;
  failed: number;
  last_delivered_at: string | null;
}

export interface MarketOffer {
  title: string;
  price: string;
  currency: string;
  brand: string;
  merchant: string;
  url: string;
  in_stock: boolean | null;
}

export interface MarketBenchmark {
  mode: "LIVE" | "SIMULATED";
  query: string;
  currency: string;
  offers: MarketOffer[];
  excluded_other_currency: number;
  unparseable_results: number;
  note: string;
  disclaimer: string;
  stats: { min: string; median: string; max: string } | null;
  position: { expected_selling_price: string; difference_pct: string; verdict: string } | null;
  procurement?: { id: string; reference: string; product_name: string };
  negotiated_landed_unit_cost?: string;
}

export interface EvidenceHit {
  kind: string;
  ref: string;
  title: string;
  snippet: string;
  actor: string;
  occurred_at: string | null;
  correlation_id: string;
  link: string;
  score: number | null;
}

export interface EvidenceSearch {
  query: string;
  kinds: string[];
  kind_labels: Record<string, string>;
  engine: "elasticsearch" | "keyword-fallback" | "none";
  mode: string;
  results: EvidenceHit[];
  note: string;
}

export interface PortalSession {
  mode: "LIVE" | "SIMULATED";
  session_id: string;
  url: string;
  live_view_url: string;
  cdp_ws_url_available: boolean;
  timeout_seconds: number;
  closed: boolean;
  note: string;
}

export interface McpTool {
  name: string;
  description: string;
  read_only: boolean;
}

export interface McpTools {
  mode: string;
  endpoint: string | null;
  tools: McpTool[];
  policy: string;
}

export interface McpResult {
  mode: string;
  tool: string;
  data: unknown;
  source: string;
}

export type TimelineState = "done" | "active" | "pending" | "blocked";

export interface TimelineTask {
  id: string;
  name: string;
  startDate: string;
  endDate: string;
  percentDone: number;
  milestone?: boolean;
  manuallyScheduled: boolean;
  expanded?: boolean;
  state: TimelineState;
  detail: string;
  /** Planned window from a date recorded up front (RFQ deadline, approval expiry, expected delivery). */
  baseline?: { startDate: string; endDate: string } | null;
  /** On a procurement (parent) row: its purchase order's delivery, for supplier-delay controls. */
  delivery?: TimelineDelivery | null;
  children?: TimelineTask[];
}

export interface TimelineDelivery {
  purchase_order_id: string;
  reference: string;
  expected_at: string | null;
  original_expected_at: string | null;
  delay_days: number;
  received_percent: number;
  open: boolean;
}

export interface DeliveryDelayResult {
  purchase_order_id: string;
  purchase_order_reference: string;
  previous_expected_at: string;
  expected_at: string;
  original_expected_at: string;
  days: number;
  total_delay_days: number;
  reason: string;
  supplier: string;
  message_id: string;
}

export interface TimelineDependency {
  id: string;
  from: string;
  to: string;
  type: number;
}

export interface ProcurementTimeline {
  tasks: TimelineTask[];
  dependencies: TimelineDependency[];
  generated_at: string;
  count: number;
}

export type StudioRow = Record<string, string | number | boolean | null>;

export interface StudioAiStatus {
  available: boolean;
  provider: string | null;
  model: string | null;
  note: string;
}

export interface StudioDatasets {
  datasets: Record<string, StudioRow[]>;
  labels: Record<string, string>;
  note: string;
  generated_at: string;
  ai?: StudioAiStatus;
}
