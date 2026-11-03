/** Wire types mirroring the backend Pydantic schemas. */

export interface ApiEnvelope<T> {
  success: boolean;
  data: T;
  meta?: Record<string, unknown>;
}

export interface ApiErrorPayload {
  success: false;
  error: { code: string; message: string; details?: Record<string, unknown> };
  request_id?: string | null;
}

export interface PageMeta {
  page: number;
  page_size: number;
  total: number;
  total_pages: number;
  has_next: boolean;
  has_previous: boolean;
}

export interface Paginated<T> {
  items: T[];
  pagination: PageMeta;
}

export interface DateRange {
  start: string;
  end: string;
}

export interface PeriodInfo {
  current: DateRange;
  previous: DateRange;
  days: number;
  label: string;
}

export type MetricUnit = "currency" | "number" | "percent" | "minutes" | "ratio";
export type MetricDirection = "UP_IS_GOOD" | "DOWN_IS_GOOD" | "NEUTRAL";

export interface MetricDelta {
  key: string;
  label: string;
  value: number;
  previous_value: number | null;
  change_abs: number | null;
  change_pct: number | null;
  unit: MetricUnit;
  direction: MetricDirection;
  is_anomaly: boolean;
  sample_size: number | null;
}

export interface TrendPoint {
  date: string;
  value: number;
  label?: string | null;
  secondary_value?: number | null;
}

export interface EvidenceItem {
  metric: string;
  value: string;
  change?: string | null;
  source: string;
  detail?: string | null;
  reference?: string | null;
  confidence?: number | null;
}

export interface ProvenanceMeta {
  data_source: "SEEDED" | "LIVE" | "SIMULATED" | "PUBLIC_WEB";
  is_simulated: boolean;
  note: string;
}

// --------------------------------------------------------------------------- //
// Auth
// --------------------------------------------------------------------------- //
export type Role = "OWNER" | "ADMIN" | "ANALYST" | "STAFF" | "VIEWER";

export interface MerchantSummary {
  id: string;
  name: string;
  slug: string;
  category: string;
  city: string;
  currency: string;
  logo_url: string | null;
  is_demo: boolean;
  data_source: string;
}

export interface UserOut {
  id: string;
  email: string;
  full_name: string;
  phone: string | null;
  avatar_url: string | null;
  status: string;
  email_verified: boolean;
  last_login_at: string | null;
  created_at: string;
}

export interface MembershipOut {
  merchant: MerchantSummary;
  role: Role;
  status: string;
  is_default: boolean;
  joined_at: string | null;
}

export interface CurrentUser {
  user: UserOut;
  active_merchant: MerchantSummary | null;
  /** Built-in role name, or a merchant-defined one. */
  role: string | null;
  permissions: string[];
  memberships: MembershipOut[];
}

export interface TokenPair {
  access_token: string;
  token_type: "bearer";
  expires_in: number;
  expires_at: string;
  refresh_token?: string | null;
}

export interface AuthSession {
  tokens: TokenPair;
  user: CurrentUser;
}

// --------------------------------------------------------------------------- //
// Dashboard
// --------------------------------------------------------------------------- //
export interface SalesSummary {
  revenue: number;
  orders: number;
  aov: number;
  unique_customers: number;
  new_customers: number;
  repeat_customers: number;
  repeat_rate: number;
  gross_margin: number;
  gross_margin_pct: number;
  discount_total: number;
  avg_service_minutes: number | null;
}

export interface DaypartBreakdown {
  daypart: string;
  label: string;
  revenue: number;
  orders: number;
  aov: number;
  unique_customers: number;
  repeat_customers: number;
  revenue_share_pct: number;
  change_pct: number | null;
  repeat_customers_change_pct: number | null;
  avg_service_minutes: number | null;
  service_minutes_change_pct: number | null;
  negative_review_share_pct: number | null;
}

export interface ProductPerformance {
  product_id: string;
  name: string;
  sku: string;
  category: string;
  units_sold: number;
  revenue: number;
  gross_margin: number;
  margin_pct: number;
  revenue_share_pct: number;
  orders: number;
  attach_rate_pct: number;
  previous_revenue: number | null;
  change_pct: number | null;
  trend: "UP" | "DOWN" | "FLAT";
  price: number;
}

export interface CustomerCohort {
  key: string;
  label: string;
  customers: number;
  revenue: number;
  orders: number;
  aov: number;
  share_pct: number;
  change_pct: number | null;
}

export interface RetentionPoint {
  cohort_month: string;
  cohort_size: number;
  month_index: number;
  retained: number;
  retention_pct: number;
}

export interface CustomerMetrics {
  total_customers: number;
  active_customers: number;
  new_customers: number;
  repeat_customers: number;
  repeat_rate: number;
  retention_rate: number;
  churn_risk_customers: number;
  avg_orders_per_customer: number;
  avg_customer_value: number;
  cohorts: CustomerCohort[];
  by_daypart: DaypartBreakdown[];
  retention_curve: RetentionPoint[];
}

export interface Anomaly {
  metric: string;
  label: string;
  value: number;
  expected: number;
  deviation_pct: number;
  z_score: number | null;
  severity: "HIGH" | "MEDIUM" | "LOW";
  dimension: string;
  dimension_value: string;
  detected_on: string | null;
  description: string;
}

export interface DashboardOverview {
  merchant_id: string;
  merchant_name: string;
  period: PeriodInfo;
  kpis: MetricDelta[];
  summary: SalesSummary;
  previous_summary: SalesSummary;
  revenue_trend: TrendPoint[];
  orders_trend: TrendPoint[];
  daypart_breakdown: DaypartBreakdown[];
  top_products: ProductPerformance[];
  declining_products: ProductPerformance[];
  customer_metrics: CustomerMetrics;
  anomalies: Anomaly[];
  headline_insight: string;
  provenance: ProvenanceMeta;
  generated_at: string;
}

// --------------------------------------------------------------------------- //
// Growth graph
// --------------------------------------------------------------------------- //
export type NodeKind = "metric" | "segment" | "signal" | "evidence" | "hypothesis";
export type NodeSeverity = "CRITICAL" | "HIGH" | "MEDIUM" | "LOW" | "INFO";

export interface GraphNode {
  id: string;
  label: string;
  metric_key: string | null;
  value: number | null;
  formatted_value: string;
  change_pct: number | null;
  direction: "UP" | "DOWN" | "FLAT";
  severity: NodeSeverity;
  depth: number;
  node_kind: NodeKind;
  source: string;
  interpretation: string;
  evidence: EvidenceItem[];
  related_metrics: string[];
  reference: string | null;
}

export interface GraphEdge {
  source: string;
  target: string;
  relationship: "decomposes_into" | "correlates_with" | "evidenced_by";
  strength: number;
  label: string;
}

export interface GrowthGraph {
  root_id: string;
  nodes: GraphNode[];
  edges: GraphEdge[];
  period: PeriodInfo;
  caveat: string;
  generated_at: string;
}

// --------------------------------------------------------------------------- //
// Opportunities
// --------------------------------------------------------------------------- //
export type OpportunityStatus =
  | "DETECTED"
  | "INVESTIGATING"
  | "RECOMMENDED"
  | "APPROVAL_REQUIRED"
  | "RUNNING"
  | "MEASURING"
  | "SCALED"
  | "STOPPED"
  | "DISMISSED";

export interface Opportunity {
  id: string;
  key: string;
  title: string;
  summary: string;
  kind: string;
  estimated_value_monthly: number;
  confidence: number;
  impact: "HIGH" | "MEDIUM" | "LOW";
  effort: "HIGH" | "MEDIUM" | "LOW";
  priority_score: number;
  risk: string;
  status: OpportunityStatus;
  evidence: EvidenceItem[];
  hypothesis: string;
  recommended_action: string;
  reasoning: string;
  graph_path: string[];
  target_segment: Record<string, unknown>;
  tags: string[];
  requires_approval: boolean;
  detected_at: string | null;
  period_start: string | null;
  period_end: string | null;
  agent_run_id: string | null;
  campaign_id: string | null;
  experiment_id: string | null;
  created_at: string;
  updated_at: string;
}

export interface OpportunityRadar {
  opportunities: Opportunity[];
  total_detected: number;
  total_estimated_value_monthly: number;
  open_count: number;
  provenance: ProvenanceMeta;
  generated_at: string;
}

// --------------------------------------------------------------------------- //
// Dual-market growth intelligence (Growth Allocation Engine)
// --------------------------------------------------------------------------- //
export interface InterventionOption {
  surface: CampaignSurface;
  label: string;
  audience_label: string;
  audience_size: number;
  historical_conversion_pct: number | null;
  offer_type: string;
  offer_description: string;
  channel: string;
  budget: number;
  expected_customers: number;
  expected_incremental_revenue: number;
  provenance: string;
}

export interface DontDiscountFinding {
  high_propensity_pct: number;
  recommendation: string;
  reasoning: string;
}

export interface ArbitrageFinding {
  better_surface: CampaignSurface;
  worse_surface: CampaignSurface;
  better_roi: number;
  worse_roi: number;
  evidence_count: number;
  confidence: "low" | "medium" | "high";
  recommended_shift_pct: number;
}

export interface GrowthMission {
  opportunity_id: string | null;
  title: string;
  business_option: InterventionOption;
  paypal_option: InterventionOption;
  hybrid_option: InterventionOption;
  recommended_surface: CampaignSurface;
  recommendation_reason: string;
  allocation_basis: "historical" | "default";
  business_pct: number;
  paypal_pct: number;
  dont_discount: DontDiscountFinding | null;
  arbitrage: ArbitrageFinding | null;
}

export interface AllocationSnapshot {
  by_surface: Record<string, { spend: number; incremental_revenue: number; campaigns: number }>;
  business_pct: number;
  paypal_pct: number;
  hybrid_pct: number;
  total_spend: number;
  total_incremental_revenue: number;
  has_data: boolean;
}

// --------------------------------------------------------------------------- //
// Reviews / competitors / signals / inventory
// --------------------------------------------------------------------------- //
export interface Review {
  id: string;
  source: string;
  author_name: string;
  rating: number;
  title: string | null;
  body: string;
  sentiment: "POSITIVE" | "NEUTRAL" | "NEGATIVE";
  sentiment_score: number;
  primary_topic: string;
  topics: string[];
  daypart: string | null;
  review_date: string;
  reviewed_at: string;
  is_verified_purchase: boolean;
  is_simulated: boolean;
  product_id: string | null;
}

export interface TopicStat {
  topic: string;
  label: string;
  count: number;
  share_pct: number;
  avg_rating: number;
  negative_count: number;
  positive_count: number;
  negative_share_pct: number;
  previous_count: number;
  change_pct: number | null;
  trend: "UP" | "DOWN" | "FLAT";
  is_emerging_complaint: boolean;
  sample_review_ids: string[];
}

export interface SentimentBreakdown {
  positive: number;
  neutral: number;
  negative: number;
  positive_pct: number;
  neutral_pct: number;
  negative_pct: number;
  avg_rating: number;
  previous_avg_rating: number | null;
  avg_rating_change: number | null;
}

export interface ReviewIntelligence {
  total_reviews: number;
  period_reviews: number;
  sentiment: SentimentBreakdown;
  topics: TopicStat[];
  emerging_complaints: TopicStat[];
  positive_themes: TopicStat[];
  rating_trend: TrendPoint[];
  negative_topic_trend: TrendPoint[];
  by_daypart: TopicStat[];
  recent_reviews: Review[];
  provenance: ProvenanceMeta;
  generated_at: string;
}

export interface ReviewSearchHit {
  review: Review;
  similarity: number;
}

export interface Competitor {
  id: string;
  name: string;
  slug: string;
  category: string;
  distance_km: number;
  price_tier: string;
  avg_rating: number;
  review_count: number;
  perception_scores: Record<string, number>;
  strengths: string[];
  weaknesses: string[];
  data_source: string;
  notes: string;
}

export interface PerceptionComparison {
  dimension: string;
  label: string;
  merchant_score: number;
  competitor_avg_score: number;
  gap: number;
  leader: string;
  is_merchant_ahead: boolean;
}

export interface CompetitorIntelligence {
  merchant_name: string;
  merchant_scores: Record<string, number>;
  merchant_avg_rating: number;
  competitors: Competitor[];
  comparisons: PerceptionComparison[];
  biggest_gap: PerceptionComparison | null;
  topic_share: TopicStat[];
  summary: string;
  provenance: ProvenanceMeta;
  generated_at: string;
}

export interface Signal {
  id: string;
  title: string;
  summary: string;
  category: string;
  icon: string;
  relevance: "HIGH" | "MEDIUM" | "LOW";
  relevance_score: number;
  linked_category: string | null;
  linked_product_id: string | null;
  exposure_pct: number | null;
  exposure_note: string;
  potential_impact: string;
  recommended_action: string;
  direction: string;
  source_name: string;
  source_url: string | null;
  observed_on: string;
  is_simulated: boolean;
}

export interface SignalFeed {
  signals: Signal[];
  high_relevance_count: number;
  provenance: ProvenanceMeta;
  generated_at: string;
}

export interface InventoryItem {
  id: string;
  product_id: string;
  product_name: string;
  sku: string;
  unit: string;
  quantity_on_hand: number;
  reorder_point: number;
  reorder_quantity: number;
  lead_time_days: number;
  unit_cost: number;
  avg_daily_demand: number;
  days_of_cover: number | null;
  stockout_risk: number;
  revenue_at_risk: number;
  status: string;
  recommendation: string;
  supplier: string;
  last_restocked_at: string | null;
}

export interface InventoryOverview {
  items: InventoryItem[];
  total_items: number;
  at_risk_items: number;
  total_revenue_at_risk: number;
  total_stock_value: number;
  critical: InventoryItem[];
  provenance: ProvenanceMeta;
}

// --------------------------------------------------------------------------- //
// Campaigns / experiments
// --------------------------------------------------------------------------- //
export interface CampaignAudience {
  id: string;
  name: string;
  role: "TEST" | "CONTROL" | "FULL";
  size: number;
  definition: Record<string, unknown>;
}

export interface CampaignAction {
  id: string;
  action_type: string;
  description: string;
  actor_type: string;
  actor_label: string;
  is_simulated: boolean;
  payload: Record<string, unknown>;
  created_at: string;
}

export type CampaignSurface = "BUSINESS" | "PAYPAL" | "HYBRID";

export type CampaignObjectiveType =
  | ""
  | "RETENTION"
  | "REACTIVATION"
  | "ACQUISITION"
  | "CROSS_SELL"
  | "INVENTORY_CLEARANCE"
  | "CAPACITY_UTILIZATION"
  | "REVENUE_RECOVERY"
  | "PROFIT_OPTIMIZATION";

export interface Campaign {
  id: string;
  name: string;
  objective: string;
  status: string;
  offer_type: string;
  offer_value: number;
  offer_description: string;
  message: string;
  channel: string;
  start_date: string | null;
  end_date: string | null;
  budget: number;
  estimated_cost: number;
  actual_cost: number;
  estimated_impact: number;
  experiment_id: string | null;
  opportunity_id: string | null;
  agent_run_id: string | null;
  requires_approval: boolean;
  approved_at: string | null;
  launched_at: string | null;
  completed_at: string | null;
  rejected_reason: string | null;
  is_simulated: boolean;
  tags: string[];
  audiences: CampaignAudience[];
  // ---- dual-market growth intelligence ----
  surface: CampaignSurface;
  objective_type: CampaignObjectiveType;
  business_budget: number;
  paypal_budget: number;
  paypal_surface: string;
  expected_incremental_revenue: number | null;
  actual_incremental_revenue: number | null;
  incremental_roi: number | null;
  measurement_status: string;
  created_by_agent: string;
  created_at: string;
  updated_at: string;
}

export interface CampaignDetail extends Campaign {
  actions: CampaignAction[];
  provenance: ProvenanceMeta;
}

export interface ExperimentVariant {
  id: string;
  key: string;
  name: string;
  role: "CONTROL" | "TEST";
  description: string;
  offer_description: string;
  allocation_pct: number;
  audience_size: number;
  unit_cost: number;
}

export interface ExperimentResult {
  id: string;
  variant_id: string;
  variant_key: string;
  variant_role: "CONTROL" | "TEST";
  audience_size: number;
  converted_customers: number;
  conversion_rate: number;
  orders: number;
  revenue: number;
  gross_margin: number;
  avg_order_value: number;
  revenue_per_customer: number;
  cost: number;
  conversion_lift_pct: number | null;
  revenue_lift_pct: number | null;
  incremental_revenue: number | null;
  incremental_profit: number | null;
  roi: number | null;
  p_value: number | null;
  is_significant: boolean;
  measured_at: string | null;
  window_start: string | null;
  window_end: string | null;
}

export type ExperimentDecision = "SCALE" | "STOP" | "CONTINUE" | "WATCH" | "PENDING";

export interface Experiment {
  id: string;
  name: string;
  hypothesis: string;
  success_metric: string;
  success_threshold_pct: number;
  status: string;
  start_date: string | null;
  end_date: string | null;
  duration_days: number;
  campaign_id: string | null;
  opportunity_id: string | null;
  agent_run_id: string | null;
  requires_approval: boolean;
  approved_at: string | null;
  launched_at: string | null;
  completed_at: string | null;
  decision: ExperimentDecision;
  decision_rationale: string;
  learning: string;
  is_simulated: boolean;
  variants: ExperimentVariant[];
  results: ExperimentResult[];
  created_at: string;
  updated_at: string;
}

export interface ExperimentSummary {
  experiment_id: string;
  name: string;
  status: string;
  hypothesis: string;
  control_conversion_rate: number;
  test_conversion_rate: number;
  conversion_lift_pct: number;
  control_revenue: number;
  test_revenue: number;
  incremental_revenue: number;
  incremental_profit: number;
  roi: number;
  cost: number;
  p_value: number | null;
  is_significant: boolean;
  decision: ExperimentDecision;
  decision_rationale: string;
  learning: string;
  window_start: string | null;
  window_end: string | null;
  provenance: ProvenanceMeta;
}

// --------------------------------------------------------------------------- //
// Agents
// --------------------------------------------------------------------------- //
export interface GrowthRecommendation {
  opportunity: string;
  summary: string;
  evidence: EvidenceItem[];
  hypothesis: string;
  recommended_action: string;
  reasoning: string;
  estimated_impact: number;
  confidence: number;
  risk: "low" | "medium" | "high";
  requires_approval: boolean;
  action_key: string | null;
  alternatives_considered: string[];
}

export interface AgentStep {
  id: string;
  sequence: number;
  node: string;
  agent_name: string;
  agent_label: string;
  action: string;
  result: string;
  decision: string | null;
  status: string;
  evidence: EvidenceItem[];
  duration_ms: number | null;
  error: string | null;
}

export interface ToolCall {
  id: string;
  sequence: number;
  tool_name: string;
  agent_name: string;
  arguments: Record<string, unknown>;
  result_summary: string;
  status: string;
  duration_ms: number | null;
  error: string | null;
}

export interface AgentRunDetail {
  id: string;
  agent_name: string;
  agent_label: string;
  workflow: string;
  status: string;
  intent: string | null;
  channel: string;
  input_text: string;
  summary: string;
  output: Record<string, unknown>;
  decision: string | null;
  confidence: number | null;
  requires_approval: boolean;
  opportunity_id: string | null;
  campaign_id: string | null;
  experiment_id: string | null;
  trace_id: string | null;
  trace_url: string | null;
  model: string | null;
  used_fallback: boolean;
  duration_ms: number | null;
  total_tokens: number | null;
  error: string | null;
  started_at: string | null;
  finished_at: string | null;
  created_at: string;
  steps: AgentStep[];
  tool_calls: ToolCall[];
  tools_used: string[];
  recommendation: GrowthRecommendation | null;
  trace_disclaimer: string;
}

export interface AgentRunResponse {
  run: AgentRunDetail;
  answer: string;
  recommendation: GrowthRecommendation | null;
  opportunity_id: string | null;
  suggested_followups: string[];
  requires_approval: boolean;
}

export interface AgentActivityItem {
  run_id: string;
  agent_name: string;
  agent_label: string;
  workflow: string;
  status: string;
  title: string;
  /** "web" or "voice" — which surface the run came in on. */
  channel: string;
  decision: string | null;
  confidence: number | null;
  tools_used: string[];
  duration_ms: number | null;
  used_fallback: boolean;
  created_at: string;
}

export interface AgentActivityFeed {
  items: AgentActivityItem[];
  total_runs: number;
  completed_runs: number;
  failed_runs: number;
  avg_duration_ms: number | null;
  top_tools: { tool: string; calls: number }[];
}

export interface ApprovalOutcome {
  approved: boolean;
  opportunity_id: string | null;
  campaign_id: string | null;
  experiment_id: string | null;
  agent_run_id: string | null;
  status: string;
  message: string;
  steps: string[];
}

export interface VoiceSessionConfig {
  enabled: boolean;
  public_key: string | null;
  assistant_id: string | null;
  assistant_overrides: Record<string, unknown>;
  session_token: string | null;
  greeting: string;
  disabled_reason: string | null;
}

// --------------------------------------------------------------------------- //
// Admin
// --------------------------------------------------------------------------- //
export interface RoleOut {
  /** A built-in role name, or a merchant-defined one. */
  name: string;
  description: string;
  permissions: string[];
  is_custom?: boolean;
  id?: string | null;
}

export interface PermissionOut {
  code: string;
  resource: string;
  action: string;
  description: string;
}

export interface TeamMember {
  user: CurrentUser["user"];
  role: string;
}

export interface AuditLogEntry {
  id: string;
  action: string;
  actor_type: string;
  actor_label: string;
  resource: string;
  resource_id: string | null;
  description: string;
  status: string;
  metadata: Record<string, unknown>;
  created_at: string;
}

export interface IntegrationStatus {
  merchant: MerchantSummary;
  integrations: {
    llm: { configured: boolean; model: string | null; note: string };
    langfuse: { configured: boolean; host: string };
    vapi: { configured: boolean };
    email: { configured: boolean; transport: string; sender: string };
    embeddings: { provider: string; dimensions: number };
    logging: { backend: string; format: string };
  };
  environment: string;
}

// --------------------------------------------------------------------------- //
// Inventory automation
// --------------------------------------------------------------------------- //
export interface InventoryRow {
  id: string;
  sku: string;
  product_name: string;
  unit: string;
  quantity_on_hand: number;
  reserved_quantity: number;
  available_quantity: number;
  reorder_point: number;
  reorder_quantity: number;
  maximum_stock: number;
  reorder_strategy: string;
  automatic_ordering_enabled: boolean;
  expiry_tracking_enabled: boolean;
  status: string;
  supplier: string;
  default_vendor_id: string | null;
  days_of_cover: number | null;
  updated_at: string | null;
  /** Present only with `inventory:value_read`. */
  unit_cost?: number;
  stock_value?: number;
}

// --------------------------------------------------------------------------- //
// Bulk import
// --------------------------------------------------------------------------- //
export interface ImportColumn {
  header: string;
  inferred_type: "string" | "number" | "boolean";
  sample_values: string[];
}

export interface ImportFieldSpec {
  key: string;
  label: string;
  dtype: "string" | "number" | "boolean";
  description: string;
  required: boolean;
}

export type ImportRowAction = "create" | "update";

export interface ImportRowPreview {
  row_number: number;
  action: ImportRowAction;
  sku: string;
  values: Record<string, string | number | boolean>;
  errors: string[];
}

/** field key -> the column header mapped to it, or null if unmapped. */
export type ImportMapping = Record<string, string | null>;

export interface ImportPreview {
  filename: string;
  columns: ImportColumn[];
  fields: ImportFieldSpec[];
  mapping: ImportMapping;
  rows: ImportRowPreview[];
  total_rows: number;
  valid_rows: number;
  error_rows: number;
  to_create: number;
  to_update: number;
}

export interface ImportRowError {
  row_number: number;
  sku: string;
  message: string;
}

export interface ImportCommitResult {
  total_rows: number;
  created: number;
  updated: number;
  skipped: number;
  failed: number;
  row_errors: ImportRowError[];
}

export interface ReorderDecision {
  should_reorder: boolean;
  quantity: number;
  strategy: string;
  available: number;
  reorder_point: number;
  reason: string;
  blockers: string[];
}

export interface InventoryBatchRow {
  id: string;
  batch_code: string;
  quantity: number;
  status: string;
  expiry_date: string | null;
  received_at: string | null;
}

export interface InventoryDetail extends InventoryRow {
  decision: ReorderDecision;
  batches: InventoryBatchRow[];
}

export interface LedgerRow {
  id: string;
  inventory_item_id: string;
  movement_type: string;
  quantity: number;
  balance_before: number;
  balance_after: number;
  unit_cost: number;
  total_value: number;
  reference_type: string;
  reference_id: string;
  source: string;
  actor_type: string;
  correlation_id: string;
  note: string;
  created_at: string | null;
}

export interface StockBookRow {
  sku: string;
  product: string;
  opening: number;
  purchases: number;
  sales: number;
  returns: number;
  transfers: number;
  adjustments: number;
  wastage: number;
  expired: number;
  closing: number;
  status: string;
  movements: number;
  unit_cost?: number;
  value?: number;
}

export interface AutomationStep {
  at: string;
  step: string;
  detail: string;
  status: string;
}

export interface AutomationRunRow {
  id: string;
  workflow_name: string;
  status: string;
  correlation_id: string;
  n8n_execution_id: string;
  trigger_event_type: string;
  entity_type: string;
  entity_id: string | null;
  steps: AutomationStep[];
  error: string;
  is_dry_run: boolean;
  started_at: string | null;
  completed_at: string | null;
}

export interface AutomationTrace {
  correlation_id: string;
  events: {
    id: string;
    event_type: string;
    delivery_status: string;
    attempts: number;
    at: string | null;
    payload: Record<string, unknown>;
  }[];
  runs: {
    id: string;
    workflow_name: string;
    status: string;
    steps: AutomationStep[];
    n8n_execution_id: string;
  }[];
  movements: {
    id: string;
    movement_type: string;
    quantity: number;
    balance_after: number;
    at: string | null;
  }[];
  purchase_orders: PurchaseOrderRow[];
}

export interface VendorRow {
  id: string;
  name: string;
  contact_name: string;
  email: string;
  phone: string;
  ordering_method: string;
  lead_time_days: number;
  is_active: boolean;
  supplies: number;
}

export interface PurchaseOrderLineRow {
  line_id: string;
  sku: string;
  product_name: string;
  quantity_ordered: number;
  quantity_received: number;
  unit_price: number;
}

export interface PurchaseOrderRow {
  purchase_order_id: string;
  reference: string;
  status: string;
  vendor_id: string;
  vendor_name: string;
  total_value: number;
  requires_approval: boolean;
  is_dry_run: boolean;
  correlation_id: string | null;
  lines: PurchaseOrderLineRow[];
  source?: string;
  expected_at?: string | null;
  created_at?: string | null;
}

export interface ReplenishmentResult {
  status: string;
  reason: string;
  run_id: string | null;
  purchase_order_id: string | null;
  reference: string;
  quantity: number;
  vendor: string;
  requires_approval: boolean;
}

// --------------------------------------------------------------------------- //
// Agent memory
// --------------------------------------------------------------------------- //
export interface MemoryHit {
  text: string;
  source: string;
  kind: string;
  score: number | null;
}

export interface MemorySearchResult {
  query: string;
  hits: MemoryHit[];
  /** False when memory is switched off or unreachable - not "nothing found". */
  available: boolean;
}

export interface MemoryStatus {
  enabled: boolean;
  available: boolean;
  broken: boolean;
  embedding_provider: string;
  llm_model: string;
  storage: string;
  pending_writes: number;
  dataset?: string;
}
