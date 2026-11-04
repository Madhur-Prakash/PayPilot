/**
 * API calls for the sponsor integrations. Components never call these directly -
 * use the hooks in `@/hooks/use-integrations`.
 */

import { apiDelete, apiGet, apiPost } from "@/lib/api/client";
import type {
  EvidenceSearch,
  IntegrationStatus,
  MarketBenchmark,
  McpResult,
  McpTools,
  PortalSession,
  ProcurementTimeline,
  StudioDatasets,
  ZapierState,
} from "@/types/integrations";

export const integrationsApi = {
  status: () => apiGet<IntegrationStatus>("/integrations/status"),
  benchmark: (payload: { query: string; expected_price?: number }) =>
    apiPost<MarketBenchmark>("/integrations/market/benchmark", payload),
  benchmarkProcurement: (id: string) => apiGet<MarketBenchmark>(`/integrations/market/procurement/${id}`),
  search: (params: { q: string; kinds?: string; size?: number }) =>
    apiGet<EvidenceSearch>("/integrations/search", { params }),
  reindex: () => apiPost<Record<string, unknown>>("/integrations/search/reindex"),
  openPortal: (payload: { url: string; supplier_name?: string }) =>
    apiPost<PortalSession>("/integrations/kernel/sessions", payload),
  closePortal: (sessionId: string) =>
    apiDelete<{ session_id: string; closed: boolean }>(`/integrations/kernel/sessions/${encodeURIComponent(sessionId)}`),
  zapier: () => apiGet<ZapierState>("/integrations/zapier"),
  zapierTest: () => apiPost<{ sent: boolean; mode: string; note?: string; http_status?: number }>("/integrations/zapier/test"),
  mcpTools: () => apiGet<McpTools>("/integrations/paypal-mcp/tools"),
  mcpCall: (tool: string, args: Record<string, unknown> = {}) =>
    apiPost<McpResult>("/integrations/paypal-mcp/call", { tool, arguments: args }),
  timeline: (limit = 12) => apiGet<ProcurementTimeline>("/supply/timeline", { params: { limit } }),
  studioDatasets: () => apiGet<StudioDatasets>("/integrations/studio/datasets"),
};
