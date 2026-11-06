/** Product Discovery, Supply Intelligence, recommendations, Merchant OS agents and payments. */

import type { Approval, Execution } from "@/types/supply";

export interface ProductImage {
  url: string;
  cleaned_url: string | null;
  alt: string;
  shot_type: string | null;
  is_main: boolean;
}

export interface ProductOffer {
  domain: string;
  /** Affiliate-tracked and short-lived - always use the one from the latest response. */
  url: string;
  price: string;
  currency: string;
  compare_at_price: string | null;
  discount_pct: string | null;
  availability: string | null;
  in_stock: boolean | null;
  condition: string | null;
  commission_rate: string | null;
  dimensions: Record<string, { number: number; unit: string } | null> | null;
}

export interface VariantValue {
  label: string;
  exists: boolean;
  available: "InStock" | "OutOfStock" | null;
  thumbnail_url: string | null;
  product_id: string | null;
}

export interface Variants {
  options: { name: string; values: VariantValue[] }[];
  selected: { name: string; label: string }[];
}

export interface Ranking {
  score: number;
  components: Record<string, number>;
  weights_used: Record<string, number>;
  reasons: string[];
  rank: number;
  label: string | null;
}

export interface Similarity {
  reasons: string[];
  shared_attributes: string[];
  price_difference: string | null;
  price_difference_pct: string | null;
  same_brand: boolean;
  same_category: boolean;
}

export interface CatalogProduct {
  id: string;
  title: string;
  description: string;
  brand: string;
  brand_id: string;
  image_url: string;
  images: ProductImage[];
  category: { slug: string; title: string; path: string[] };
  gender: string | null;
  age: string | null;
  materials: string[];
  key_features: string[];
  structured_attributes: Record<string, string[]>;
  variants: Variants | null;
  /** Only present when Channel3 returns ratings - never invented. */
  ratings: { value: number; count: number } | null;
  price: string | null;
  compare_at_price: string | null;
  discount_pct: string | null;
  currency: string;
  min_price: string | null;
  max_price: string | null;
  in_stock: boolean | null;
  retailer: string;
  url: string;
  retailers: string[];
  offers_count: number;
  offers: ProductOffer[];
  commission_rate: string | null;
  ranking?: Ranking;
  similarity?: Similarity;
}

export interface SearchIntent {
  raw: string;
  query: string;
  category: string | null;
  min_price: number | null;
  max_price: number | null;
  budget_currency: string;
  brands: string[];
  exclude_brands: string[];
  attributes: string[];
  use_case: string | null;
  retailers: string[];
  on_sale: boolean;
  include_out_of_stock: boolean;
  compare_brands: boolean;
  alternatives_to: string | null;
}

export interface SearchResult {
  search_id: string;
  query: string;
  intent: SearchIntent;
  budget: {
    min_price: number | null;
    max_price: number | null;
    currency: string;
    budget_currency: string;
    converted: boolean;
    rate: string | null;
    note: string | null;
  };
  applied_filters: Record<string, unknown>;
  channel3_query: string;
  category: { slug: string; title: string | null } | null;
  products: CatalogProduct[];
  next_page_token: string | null;
  notes: string[];
  mode: string;
  used_llm: boolean;
  duration_ms: number;
  ranking_note: string;
}

export interface SearchRequest {
  query: string;
  min_price?: number | null;
  max_price?: number | null;
  brands?: string[];
  category?: string | null;
  retailers?: string[];
  include_out_of_stock?: boolean | null;
  on_sale?: boolean | null;
  limit?: number;
  page_token?: string | null;
  mode?: "default" | "agentic";
}

export interface DiscoveryStatus {
  configured: boolean;
  mode: string;
  currency: string;
  country: string;
  fx_reference_rates: Record<string, number>;
  setup: string | null;
}

export interface SearchHistoryItem {
  id: string;
  query: string;
  source: string;
  result_count: number;
  intent: Partial<SearchIntent> & Record<string, unknown>;
  filters: Record<string, unknown>;
  mode: string;
  used_llm: boolean;
  duration_ms: number | null;
  error: string | null;
  created_at: string | null;
}

export interface DiscoveredProduct {
  id: string;
  title: string;
  brand: string;
  category: { slug: string; title: string };
  image_url: string;
  currency: string;
  min_price: string | null;
  max_price: string | null;
  offers_count: number;
  retailer: string;
  in_stock: boolean | null;
  times_seen: number;
  is_shortlisted: boolean;
  last_source: string;
  first_seen_at: string | null;
  last_seen_at: string | null;
  price_is_snapshot: boolean;
}

export interface ProductDetail {
  product: CatalogProduct;
  fetched_at: string;
  similar: CatalogProduct[];
  similar_error: string | null;
  history?: { first_seen_at: string; times_seen: number; is_shortlisted: boolean; previous_min_price: string | null };
}

export interface SimilarResult {
  source: CatalogProduct;
  products: CatalogProduct[];
  fallback_used: boolean;
  note: string | null;
}

export interface Verdict {
  product_id: string | null;
  title: string | null;
  reason: string;
  basis?: string;
  evidence: { label: string; value: string; source: string }[];
  price_difference?: string | null;
  price_difference_pct?: string | null;
  within_customer_band?: string[];
}

export interface ComparisonRow {
  key: string;
  label: string;
  kind: "text" | "money" | "number" | "list";
  values: (string | number | string[] | null)[];
}

export interface ComparisonResult {
  comparison_id: string;
  products: CatalogProduct[];
  matrix: { rows: ComparisonRow[]; attribute_keys: string[] };
  verdicts: {
    best_value: Verdict | null;
    best_specifications: Verdict | null;
    best_customer_fit: Verdict | null;
    best_alternative: Verdict | null;
  };
  overall: { product_id: string | null; wins: Record<string, number> };
  not_listed: Record<string, string[]>;
  merchant_context: {
    catalog_median_price: number | null;
    catalog_p75_price: number | null;
    catalog_products: number;
    average_order_value: number | null;
    window: string;
  };
  notes: string[];
  narrative: string;
  used_llm: boolean;
}

export interface ConversationMessage {
  role: "user" | "assistant";
  text: string;
  at: string;
  products?: CatalogProduct[];
  suggestions?: string[];
  searches?: { tool: string; input: Record<string, unknown>; results: number }[];
  source?: string;
}

export interface ShoppingConversation {
  id: string;
  title: string;
  channel3_conversation_id: string;
  constraints: Record<string, unknown>;
  remembered: string[];
  turn_count: number;
  credits_used: number;
  last_turn_at: string | null;
  created_at: string | null;
  messages?: ConversationMessage[];
}

export interface AssistantTurnResult {
  conversation: ShoppingConversation;
  reply: { text: string; products: CatalogProduct[]; suggestions: string[]; searches: unknown[]; usage: Record<string, number> };
  pinned_filters: Record<string, unknown>;
}

// --------------------------------------------------------------------------- //
// Supply intelligence
// --------------------------------------------------------------------------- //
export interface EvidenceItem {
  label: string;
  value: string | number;
  source: string;
}

export interface ExpansionCandidate {
  key: string;
  anchor: {
    product_id: string;
    name: string;
    sku: string;
    category: string;
    price: number;
    buyers: number;
    units: number;
    units_growth_pct: number | null;
    daily_units: number;
    orders: number;
  };
  slot: { key: string; label: string; query: string; category: string | null; max_price: string | null };
  rationale: string;
  signals: EvidenceItem[];
  score: number;
}

export interface CategoryRow {
  category: string;
  revenue: number;
  units: number;
  previous_revenue: number;
  products: number;
  orders: number;
  share_pct: number;
  growth_pct: number | null;
}

export interface ProductRow {
  product_id: string;
  name: string;
  sku: string;
  category: string;
  price: number;
  units: number;
  revenue: number;
  orders: number;
  buyers: number;
  units_growth_pct: number | null;
  revenue_share_pct?: number;
}

export interface InventoryRow {
  inventory_item_id: string;
  product_id: string;
  name: string;
  sku: string;
  unit: string;
  on_hand: number;
  avg_daily_demand: number;
  days_of_cover: number | null;
  status: string;
  units_sold: number;
  turnover: number | null;
}

export type RecommendationStatus =
  | "DETECTED" | "ANALYZED" | "RECOMMENDED" | "APPROVED" | "REJECTED" | "EXECUTED" | "MEASURED" | "SUPERSEDED";

export interface RecommendationStage {
  status: RecommendationStatus;
  reached: boolean;
  at: string | null;
  actor: string | null;
  note: string | null;
}

export interface RecommendationProduct {
  id: string;
  title: string;
  brand?: string;
  image_url?: string;
  price?: string | null;
  currency?: string;
  retailer?: string;
  retailers?: string[];
  in_stock?: boolean | null;
  url?: string;
  ratings?: { value: number; count: number } | null;
  ranking?: Ranking;
}

export interface Recommendation {
  id: string;
  reference: string;
  kind: "ASSORTMENT_EXPANSION" | "PRODUCT_ALTERNATIVE" | "PRICING_OPPORTUNITY";
  kind_label: string;
  title: string;
  description: string;
  evidence: EvidenceItem[];
  recommended_action: string;
  expected_impact: {
    metric?: string;
    value?: string | null;
    currency?: string;
    period?: string;
    is_estimate?: boolean;
    units_per_month?: string;
    assumptions?: string[];
  };
  confidence: number;
  confidence_reasons: string[];
  requires_approval: boolean;
  status: RecommendationStatus;
  stages: RecommendationStage[];
  lifecycle: { status: string; at: string; actor: string; note: string }[];
  anchor_product: { id: string | null; name: string };
  category: string;
  products: RecommendationProduct[];
  suggested_test_quantity: number | null;
  suggested_retail_price: string | null;
  currency: string;
  narrative_source: "llm" | "deterministic";
  agent_run_id: string | null;
  decided_by: string | null;
  decided_at: string | null;
  decision_note: string;
  executed_at: string | null;
  execution: Record<string, string | undefined>;
  measured_at: string | null;
  measurement: Record<string, unknown>;
  created_at: string | null;
  updated_at: string | null;
}

export interface SupplyOverview {
  status: DiscoveryStatus;
  window: { start: string; end: string; days: number } | null;
  summary: { revenue: number; orders: number; units: number; products_sold: number; catalog_products: number } | null;
  data_quality: { orders: number; sufficient: boolean; note: string | null } | null;
  categories: CategoryRow[];
  growing_products: ProductRow[];
  inventory: InventoryRow[];
  pairs: { product_a_name: string; product_b_name: string; co_occurrences: number; lift: number; confidence_pct: number }[];
  expansion_candidates: ExpansionCandidate[];
  top_opportunity: ExpansionCandidate | null;
  recommendations: Recommendation[];
  pricing: Recommendation[];
  recently_discovered: DiscoveredProduct[];
  recent_searches: SearchHistoryItem[];
  kpis: {
    open_recommendations: number;
    approved: number;
    executed: number;
    estimated_open_monthly_impact: number;
    products_discovered: number;
    searches: number;
  };
}

export interface PricingRow {
  product_id: string;
  name: string;
  sku: string;
  category: string;
  merchant_price: string;
  merchant_unit_cost: string | null;
  merchant_margin_pct: string | null;
  currency: string;
  query?: string;
  searched?: number;
  comparable_category: { slug: string; title: string } | null;
  comparables: { id: string; title: string; brand: string; image_url: string; retailer: string; price: string; url: string; in_stock: boolean | null }[];
  stats: { min: string; median: string; max: string; count: number } | null;
  position: { difference_pct: string; difference: string; verdict: string } | null;
  opportunity: { type: string; suggested_price: string | null; step_pct?: string; estimated_monthly_revenue_change?: string | null; assumptions: string[] } | null;
  note?: string;
  error: string | null;
}

export interface PricingResult {
  mode: string;
  currency: string;
  products: PricingRow[];
  disclaimer: string;
}

export interface CatalogProductRow {
  id: string;
  name: string;
  sku: string;
  category: string;
  price: string;
  is_active: boolean;
  image_url: string | null;
  source: string | null;
}

export interface AlternativesResult {
  product: { id: string; name: string; sku: string; category: string; price: string; cost_price: string; image_url: string | null };
  equivalent: (CatalogProduct & { match_note: string }) | null;
  alternatives: (CatalogProduct & { vs_your_price: { difference: string | null; difference_pct: string | null } })[];
  fallback_used?: boolean;
  note: string;
}

// --------------------------------------------------------------------------- //
// Merchant OS agents
// --------------------------------------------------------------------------- //
export type AgentKey =
  | "business_intelligence" | "product_discovery" | "supply_intelligence" | "pricing_intelligence"
  | "growth_strategy" | "paypal_transaction";

export interface AgentStepView {
  node: string;
  agent_name: string;
  action: string;
  result: string;
  decision: string | null;
  status: string;
  error: string | null;
}

export interface AgentExecution {
  run_id: string;
  status: string;
  agent: AgentKey;
  agent_name: string;
  agent_label: string;
  route: { agent: AgentKey; source: "explicit" | "llm" | "keywords"; reason: string };
  answer: string;
  products: (Partial<CatalogProduct> & { id: string; title: string; score?: number; reasons?: string[] })[];
  recommendations: { id: string; reference: string; title: string; status: string; kind: string; expected_impact: string | null; confidence: number }[];
  approvals: { approval_id: string; reference: string; status: string; amount: string; currency: string }[];
  comparison: Record<string, unknown> | null;
  suggestions: string[];
  tool_calls: { agent: string; tool: string; ok: boolean; summary: string; error: string | null; attempts: number }[];
  steps: AgentStepView[];
  requires_approval: boolean;
  used_llm: boolean;
  duration_ms: number | null;
}

export interface AgentCatalogueEntry {
  key: string;
  name: string;
  label: string;
  purpose: string;
  tools: { name: string; requires_approval: boolean }[];
  can_move_money: boolean;
}

export interface ActivityItem {
  run_id: string;
  agent_name: string;
  agent_label: string;
  specialists: string[];
  task: string;
  trigger: string;
  workflow: string;
  status: string;
  tools: { tool: string; agent: string; status: string; duration_ms: number | null; summary: string; error: string | null }[];
  result: string;
  error: string | null;
  requires_approval: boolean;
  used_fallback: boolean;
  duration_ms: number | null;
  created_at: string | null;
}

export interface ActivityFeed {
  items: ActivityItem[];
  agents: { agent_name: string; label: string; runs: number; failed: number; tool_calls: number }[];
}

// --------------------------------------------------------------------------- //
// Payments
// --------------------------------------------------------------------------- //
export interface PaymentHistoryItem extends Execution {
  approval_reference: string | null;
  title: string;
}

export interface PaymentHistory {
  items: PaymentHistoryItem[];
  stats: {
    total: number;
    by_status: Record<string, number>;
    settled: { currency: string; mode: string; amount: string }[];
    awaiting_payer: number;
    failed: number;
  };
  approvals: Approval[];
  mode: string;
  permissions: { can_approve: boolean; can_execute: boolean };
}

export interface PaymentOrderDetail {
  execution: Execution;
  paypal: {
    id: string;
    status: string;
    intent: string;
    amount: { currency_code: string; value: string } | null;
    payee_email: string;
    capture_ids: string[];
    approve_url: string;
    payer: Record<string, unknown> | null;
    create_time: string | null;
    update_time: string | null;
  } | null;
  paypal_error: string | null;
  approval: Approval | null;
  recommendation?: { id: string; reference: string; title: string; status: string } | null;
}
