/**
 * API calls for Product Discovery, Supply Intelligence, recommendations, the Merchant OS
 * agents and payment management. Components use the hooks in `@/hooks/use-discovery`.
 * The Channel3 key never reaches the browser - every call goes through the backend.
 */

import { apiGet, apiGetWithMeta, apiPost } from "@/lib/api/client";
import type { Approval, Execution } from "@/types/supply";
import type {
  ActivityFeed,
  AgentCatalogueEntry,
  AgentExecution,
  AgentKey,
  AlternativesResult,
  AssistantTurnResult,
  CatalogProductRow,
  ComparisonResult,
  DiscoveredProduct,
  DiscoveryStatus,
  PaymentHistory,
  PaymentOrderDetail,
  PricingResult,
  ProductDetail,
  Recommendation,
  SearchHistoryItem,
  SearchRequest,
  SearchResult,
  ShoppingConversation,
  SimilarResult,
  SupplyOverview,
} from "@/types/discovery";

export const discoveryApi = {
  status: () => apiGet<DiscoveryStatus>("/supply/discovery/status"),
  search: (body: SearchRequest) => apiPost<SearchResult>("/supply/search", body),
  compare: (product_ids: string[], features: string[] = []) =>
    apiPost<ComparisonResult>("/supply/compare", { product_ids, features }),
  similar: (body: { product_id: string; limit?: number; min_price?: number; max_price?: number; same_brand?: boolean | null }) =>
    apiPost<SimilarResult>("/supply/similar", body),
  enrich: (url: string) => apiPost<{ product: ProductDetail["product"]; source_url: string }>("/supply/enrich", { url }),
  product: (id: string, fresh = false) => apiGet<ProductDetail>(`/supply/products/${encodeURIComponent(id)}`, { params: { fresh } }),
  shortlist: (id: string, value: boolean) =>
    apiPost<DiscoveredProduct>(`/supply/products/${encodeURIComponent(id)}/shortlist`, { value }),
  history: (limit = 30) => apiGet<SearchHistoryItem[]>("/supply/searches", { params: { limit } }),
  discovered: (params: { limit?: number; shortlisted?: boolean } = {}) =>
    apiGet<DiscoveredProduct[]>("/supply/discovered", { params }),
  comparisons: () => apiGet<{ id: string; product_ids: string[]; titles: string[]; narrative: string; created_at: string | null }[]>(
    "/supply/comparisons"),
  assistantTurn: (message: string, conversation_id?: string | null) =>
    apiPost<AssistantTurnResult>("/supply/assistant", { message, conversation_id: conversation_id || null }),
  conversations: () => apiGet<ShoppingConversation[]>("/supply/assistant/conversations"),
  conversation: (id: string) => apiGet<ShoppingConversation>(`/supply/assistant/conversations/${id}`),
};

export const supplyIntelApi = {
  overview: (days = 30) => apiGet<SupplyOverview>("/supply/intelligence", { params: { days } }),
  pricing: (body: { product_ids?: string[]; limit?: number }) => apiPost<PricingResult>("/supply/pricing", body),
  catalogProducts: () => apiGet<CatalogProductRow[]>("/supply/catalog-products"),
  alternatives: (product_id: string, limit = 8) =>
    apiPost<AlternativesResult>("/supply/alternatives", { product_id, limit }),
  saveAlternative: (product_id: string, channel3_product_id: string, note = "") =>
    apiPost<Recommendation>("/supply/alternatives/save", { product_id, channel3_product_id, note }),
  recommendations: (params: { status?: string; kind?: string } = {}) =>
    apiGetWithMeta<Recommendation[]>("/supply/recommendations", { params }),
  recommendation: (id: string) => apiGet<Recommendation>(`/supply/recommendations/${id}`),
  generate: (body: { days?: number; max_recommendations?: number; include_pricing?: boolean } = {}) =>
    apiPost<{ recommendations: Recommendation[]; notes: string[] }>("/supply/recommendations/generate", body),
  approve: (id: string, note = "") => apiPost<Recommendation>(`/supply/recommendations/${id}/approve`, { note }),
  reject: (id: string, note = "") => apiPost<Recommendation>(`/supply/recommendations/${id}/reject`, { note }),
  execute: (id: string, retail_price?: number | null) =>
    apiPost<Recommendation>(`/supply/recommendations/${id}/execute`, { retail_price: retail_price ?? null }),
  purchase: (id: string, body: { quantity: number; unit_cost: number; payee_email: string; currency?: string }) =>
    apiPost<Approval>(`/supply/recommendations/${id}/purchase`, body),
  measure: (id: string) => apiPost<Recommendation>(`/supply/recommendations/${id}/measure`),
  runAutopilot: (body: { days?: number; max_recommendations?: number } = {}) =>
    apiPost<AgentExecution>("/growth/autopilot/run", body),
  autopilot: () =>
    apiGet<{ last_run: { run_id: string; status: string; summary: string; created_at: string | null; duration_ms: number | null } | null;
      pipeline: Record<string, number>; recommendations: Recommendation[] }>("/growth/autopilot"),
};

export const merchantAgentsApi = {
  execute: (message: string, agent?: AgentKey | null, params: Record<string, unknown> = {}) =>
    apiPost<AgentExecution>("/agents/execute", { message, agent: agent || null, params }),
  catalogue: () => apiGet<AgentCatalogueEntry[]>("/agents/catalogue"),
  activity: (params: { limit?: number; agent_name?: string; status?: string } = {}) =>
    apiGet<ActivityFeed>("/agents/activity", { params }),
};

export const paymentsApi = {
  history: (params: { kind?: string; limit?: number } = {}) => apiGet<PaymentHistory>("/payments/history", { params }),
  order: (executionId: string) => apiGet<PaymentOrderDetail>(`/payments/orders/${executionId}`),
  createOrder: (approvalId: string, idempotencyKey: string) =>
    apiPost<Execution>("/payments/orders", { approval_id: approvalId }, { headers: { "Idempotency-Key": idempotencyKey } }),
  capture: (executionId: string) => apiPost<Execution>("/payments/capture", { execution_id: executionId }),
};
