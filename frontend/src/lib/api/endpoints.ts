/**
 * Every backend call the app makes, in one typed module.
 *
 * Components never build URLs. Hooks call these; these call the shared Axios
 * client. Adding a screen means adding a function here, not a `fetch` somewhere.
 */

import {
  apiDelete,
  apiDownload,
  apiGet,
  apiGetWithMeta,
  apiPatch,
  apiPost,
  apiPostWithMeta,
  apiUpload,
} from "@/lib/api/client";
import type {
  AgentActivityFeed,
  AgentRunDetail,
  AgentRunResponse,
  AllocationSnapshot,
  ApprovalOutcome,
  ArbitrageFinding,
  AuditLogEntry,
  AuthSession,
  Campaign,
  CampaignDetail,
  CompetitorIntelligence,
  CurrentUser,
  CustomerMetrics,
  DashboardOverview,
  Experiment,
  ExperimentSummary,
  GrowthGraph,
  GrowthMission,
  ImportCommitResult,
  ImportMapping,
  ImportPreview,
  IntegrationStatus,
  InventoryItem,
  InventoryOverview,
  Opportunity,
  OpportunityRadar,
  Paginated,
  ReplenishmentResult,
  PurchaseOrderRow,
  VendorRow,
  AutomationTrace,
  AutomationRunRow,
  StockBookRow,
  LedgerRow,
  InventoryDetail,
  InventoryRow,
  TeamMember,
  PermissionOut,
  ProductPerformance,
  Review,
  ReviewIntelligence,
  ReviewSearchHit,
  RoleOut,
  SignalFeed,
  VoiceSessionConfig,
  MemorySearchResult,
  MemoryStatus,
} from "@/types/api";

// --------------------------------------------------------------------------- //
// Auth
// --------------------------------------------------------------------------- //
export const authApi = {
  login: (email: string, password: string) =>
    apiPost<AuthSession>("/auth/login", { email, password }),

  register: (payload: {
    email: string;
    password: string;
    full_name: string;
    merchant_name?: string;
  }) => apiPost<AuthSession>("/auth/register", payload),

  refresh: () => apiPost<AuthSession>("/auth/refresh", {}),

  logout: () => apiPost<{ ok: boolean; message: string }>("/auth/logout", {}),

  me: () => apiGet<CurrentUser>("/auth/me"),

  updateProfile: (payload: { full_name?: string; phone?: string }) =>
    apiPatch<CurrentUser["user"]>("/auth/me", payload),

  changePassword: (current_password: string, new_password: string) =>
    apiPost<{ ok: boolean; message: string }>("/auth/change-password", {
      current_password,
      new_password,
    }),

  forgotPassword: (email: string) =>
    apiPost<{ ok: boolean; message: string; resource_id?: string | null }>(
      "/auth/forgot-password",
      { email },
    ),

  resetPassword: (token: string, new_password: string) =>
    apiPost<{ ok: boolean; message: string }>("/auth/reset-password", {
      token,
      new_password,
    }),
};

// --------------------------------------------------------------------------- //
// Dashboard & analytics
// --------------------------------------------------------------------------- //
export const dashboardApi = {
  overview: (days: number) =>
    apiGet<DashboardOverview>("/dashboard/overview", { params: { days } }),

  growthGraph: (days: number) => apiGet<GrowthGraph>("/growth/graph", { params: { days } }),

  customerMetrics: (days: number) =>
    apiGet<CustomerMetrics>("/customers/metrics", { params: { days } }),

  customers: (params: { page?: number; page_size?: number; segment?: string; daypart?: string }) =>
    apiGet<Paginated<Record<string, unknown>>>("/customers", { params }),

  products: (days: number) =>
    apiGet<{
      period: DashboardOverview["period"];
      products: ProductPerformance[];
      top_by_revenue: ProductPerformance[];
      top_by_margin: ProductPerformance[];
      declining: ProductPerformance[];
      growing: ProductPerformance[];
      product_mix: {
        product_a_id: string;
        product_a_name: string;
        product_b_id: string;
        product_b_name: string;
        co_occurrences: number;
        support_pct: number;
        confidence_pct: number;
        lift: number;
        combined_revenue: number;
        estimated_bundle_uplift: number;
      }[];
      category_breakdown: { key: string; label: string; revenue: number; share_pct: number }[];
    }>("/products/analytics", { params: { days } }),
};

// --------------------------------------------------------------------------- //
// Growth
// --------------------------------------------------------------------------- //
export const growthApi = {
  opportunities: (params?: { status?: string; limit?: number }) =>
    apiGet<OpportunityRadar>("/opportunities", { params }),

  opportunity: (id: string) => apiGet<Opportunity>(`/opportunities/${id}`),

  detect: (days = 30) => apiPost<OpportunityRadar>("/opportunities/detect", { days }),

  /** Compares a business-side, Paypal-side and hybrid intervention for this
   * opportunity. Read-only - nothing is created until the merchant picks one. */
  missions: (opportunityId: string) =>
    apiGet<GrowthMission>(`/opportunities/${opportunityId}/missions`),

  /** Measured ROI edge between the business and Paypal surfaces, or `null` until
   * both have at least one measured campaign. */
  arbitrage: () => apiGet<ArbitrageFinding | null>("/growth/arbitrage"),

  /** Where the growth budget has actually gone, by surface. */
  allocation: () => apiGet<AllocationSnapshot>("/growth/allocation"),

  setStatus: (id: string, status: string, note = "") =>
    apiPatch<Opportunity>(`/opportunities/${id}/status`, { status, note }),

  reviews: (days: number) =>
    apiGet<ReviewIntelligence>("/reviews/intelligence", { params: { days } }),

  reviewList: (params: {
    page?: number;
    page_size?: number;
    topic?: string;
    sentiment?: string;
    daypart?: string;
    rating?: number;
    q?: string;
  }) =>
    apiGetWithMeta<Paginated<Review>>("/reviews", {
      // Drop empty filters so the query key and the URL stay stable.
      params: Object.fromEntries(
        Object.entries(params).filter(([, v]) => v !== undefined && v !== "" && v !== null),
      ),
    }),

  reviewSearch: (query: string, topic?: string, limit = 10) =>
    apiPost<ReviewSearchHit[]>("/reviews/search", { query, topic, limit }),

  competitors: (days = 90) =>
    apiGet<CompetitorIntelligence>("/competitors/intelligence", { params: { days } }),

  /** An opportunity a person spotted, which the detector cannot see. */
  createOpportunity: (payload: {
    title: string;
    summary?: string;
    kind?: string;
    estimated_value_monthly?: number;
    confidence?: number;
    effort?: "LOW" | "MEDIUM" | "HIGH";
    impact?: "LOW" | "MEDIUM" | "HIGH";
    recommended_action?: string;
  }) =>
    apiPost<{ id: string; key: string; title: string; status: string }>(
      "/opportunities",
      payload,
    ),

  signals: (days = 30) => apiGet<SignalFeed>("/signals", { params: { days } }),

  dismissSignal: (id: string) =>
    apiPost<{ ok: boolean; message: string }>(`/signals/${id}/dismiss`, {}),

  inventory: () => apiGet<InventoryOverview>("/inventory"),

  inventoryAction: (
    itemId: string,
    payload: { action: string; quantity?: number; note?: string },
  ) => apiPost<InventoryItem>(`/inventory/${itemId}/action`, payload),
};

// --------------------------------------------------------------------------- //
// Campaigns & experiments
// --------------------------------------------------------------------------- //
export const campaignApi = {
  list: (params?: { page?: number; page_size?: number; status?: string }) =>
    apiGet<Paginated<Campaign>>("/campaigns", { params }),

  get: (id: string) => apiGet<CampaignDetail>(`/campaigns/${id}`),

  create: (payload: Record<string, unknown>) => apiPost<CampaignDetail>("/campaigns", payload),

  approve: (id: string, approve: boolean, note = "") =>
    apiPost<CampaignDetail>(`/campaigns/${id}/approve`, { approve, note }),

  execute: (id: string) => apiPost<CampaignDetail>(`/campaigns/${id}/execute`, {}),
};

export const experimentApi = {
  list: (params?: { page?: number; page_size?: number; status?: string }) =>
    apiGet<Paginated<Experiment>>("/experiments", { params }),

  get: (id: string) => apiGet<Experiment>(`/experiments/${id}`),

  create: (payload: Record<string, unknown>) => apiPost<Experiment>("/experiments", payload),

  approve: (id: string, approve: boolean, note = "") =>
    apiPost<Experiment>(`/experiments/${id}/approve`, { approve, note }),

  measure: (id: string) => apiPost<ExperimentSummary>(`/experiments/${id}/measure`, {}),

  summary: (id: string) => apiGet<ExperimentSummary>(`/experiments/${id}/summary`),
};

// --------------------------------------------------------------------------- //
// Agents
// --------------------------------------------------------------------------- //
export const agentApi = {
  ask: (message: string, opportunityId?: string) =>
    apiPost<AgentRunResponse>("/agents/ask", {
      message,
      opportunity_id: opportunityId,
      channel: "web",
    }),

  investigate: (payload: { question?: string; opportunity_id?: string; days?: number }) =>
    apiPost<AgentRunResponse>("/agents/investigate", payload),

  approve: (
    opportunityId: string,
    payload: { approve: boolean; note?: string; execute_now?: boolean },
  ) => apiPost<ApprovalOutcome>(`/agents/opportunities/${opportunityId}/approve`, payload),

  measure: (experimentId: string) =>
    apiPost<ExperimentSummary>(`/agents/experiments/${experimentId}/measure`, {}),

  runs: (params?: {
    limit?: number;
    offset?: number;
    agent_name?: string;
    channel?: "web" | "voice";
  }) =>
    apiGet<AgentActivityFeed>("/agents/runs", { params }),

  run: (id: string) => apiGet<AgentRunDetail>(`/agents/runs/${id}`),

  tools: () =>
    apiGet<
      { name: string; description: string; permission: string | null; requires_approval: boolean }[]
    >("/agents/tools"),
};

// --------------------------------------------------------------------------- //
// Voice
// --------------------------------------------------------------------------- //
export const voiceApi = {
  session: () => apiGet<VoiceSessionConfig>("/voice/session"),
};

// --------------------------------------------------------------------------- //
// Admin
// --------------------------------------------------------------------------- //
export const adminApi = {
  currentMerchant: () => apiGet<CurrentUser["active_merchant"]>("/merchants/current"),
  roles: () => apiGet<RoleOut[]>("/roles"),
  permissions: () => apiGet<PermissionOut[]>("/permissions"),
  users: () => apiGet<TeamMember[]>("/users"),
  inviteUser: (payload: {
    email: string;
    full_name: string;
    role: string;
    temporary_password: string;
  }) => apiPostWithMeta<CurrentUser["user"]>("/users/invite", payload),
  changeRole: (payload: { user_id: string; role: string }) =>
    apiPost<{ message: string }>("/users/role", payload),
  createRole: (payload: { name: string; description: string; permissions: string[] }) =>
    apiPost<RoleOut>("/roles", payload),
  deleteRole: (id: string) => apiDelete<{ message: string }>(`/roles/${id}`),
  sendTestEmail: () => apiPost<{ message: string }>("/settings/email/test", {}),
  auditLogs: (params?: { page?: number; page_size?: number; action?: string }) =>
    apiGet<Paginated<AuditLogEntry>>("/audit-logs", { params }),
  settings: () => apiGet<IntegrationStatus>("/settings"),
  health: () =>
    apiGet<{
      status: string;
      version: string;
      environment: string;
      checks: Record<string, string>;
      note: string;
    }>("/health"),
};

// --------------------------------------------------------------------------- //
// Inventory & procurement
// --------------------------------------------------------------------------- //
export const inventoryApi = {
  items: (params?: { page?: number; page_size?: number; status?: string; q?: string }) =>
    apiGetWithMeta<Paginated<InventoryRow>>("/inventory/items", { params }),

  item: (id: string) => apiGet<InventoryDetail>(`/inventory/items/${id}`),

  adjust: (
    id: string,
    payload: { movement_type: string; quantity: number; note?: string },
  ) => apiPost<Record<string, unknown>>(`/inventory/items/${id}/adjust`, payload),

  setPolicy: (id: string, payload: Record<string, unknown>) =>
    apiPatch<InventoryRow>(`/inventory/items/${id}/policy`, payload),

  reorder: (id: string) =>
    apiPost<ReplenishmentResult>(`/inventory/items/${id}/reorder`, {}),

  /** `mapping` omitted (or `undefined`) asks the backend to auto-suggest one. */
  importPreview: (file: File, mapping?: ImportMapping) => {
    const form = new FormData();
    form.append("file", file);
    if (mapping) form.append("mapping", JSON.stringify(mapping));
    return apiUpload<ImportPreview>("/inventory/import/preview", form);
  },

  importCommit: (file: File, mapping: ImportMapping) => {
    const form = new FormData();
    form.append("file", file);
    form.append("mapping", JSON.stringify(mapping));
    return apiUpload<ImportCommitResult>("/inventory/import/commit", form);
  },

  ledger: (params?: {
    page?: number;
    page_size?: number;
    inventory_item_id?: string;
    movement_type?: string;
    correlation_id?: string;
  }) => apiGet<Paginated<LedgerRow>>("/inventory/ledger", { params }),

  book: (params?: { start?: string; end?: string }) =>
    apiGetWithMeta<StockBookRow[]>("/inventory/book", { params }),

  /** Streams an .xlsx workbook. Must go through the client - see apiDownload. */
  exportBook: (params: { start?: string; end?: string } = {}) =>
    apiDownload(
      "/inventory/book/export",
      `inventory-book-${params.start ?? "start"}-to-${params.end ?? "today"}.xlsx`,
      { params },
    ),

  automation: (params?: { page?: number; status?: string; correlation_id?: string }) =>
    apiGetWithMeta<Paginated<AutomationRunRow>>("/inventory/automation", { params }),

  trace: (correlationId: string) =>
    apiGet<AutomationTrace>(`/inventory/trace/${correlationId}`),

  dispatch: () =>
    apiPost<{ delivered: number; failed: number; skipped: number }>(
      "/inventory/automation/dispatch",
      {},
    ),

  vendors: () => apiGet<VendorRow[]>("/vendors"),

  createVendor: (payload: Record<string, unknown>) =>
    apiPost<{ id: string; name: string }>("/vendors", payload),

  purchaseOrders: (params?: { page?: number; page_size?: number; status?: string }) =>
    apiGet<Paginated<PurchaseOrderRow>>("/purchase-orders", { params }),

  approveOrder: (id: string, approve: boolean, note?: string) =>
    apiPost<PurchaseOrderRow>(`/purchase-orders/${id}/approve`, { approve, note }),

  receiveOrder: (id: string, lines: { line_id: string; quantity: number }[]) =>
    apiPost<PurchaseOrderRow>(`/purchase-orders/${id}/receive`, { lines }),
};

// --------------------------------------------------------------------------- //
// Agent memory
// --------------------------------------------------------------------------- //
export const memoryApi = {
  status: () => apiGet<MemoryStatus>("/memory/status"),

  search: (params: { q: string; limit?: number; kind?: string }) =>
    apiGet<MemorySearchResult>("/memory/search", { params }),

  remember: (payload: { text: string; kind?: string; tags?: string[] }) =>
    apiPost<{ queued: boolean; kind: string }>("/memory/remember", payload),

  // Irreversible, and the backend refuses the call without the confirmation.
  forget: () => apiDelete<{ erased: boolean }>("/memory", { data: { confirm: true } }),
};
