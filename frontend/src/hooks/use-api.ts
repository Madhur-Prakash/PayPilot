"use client";

/** Typed React Query hooks. Components never call the API modules directly. */

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";

import { ApiError } from "@/lib/api/client";
import {
  adminApi,
  agentApi,
  campaignApi,
  inventoryApi,
  memoryApi,
  dashboardApi,
  experimentApi,
  growthApi,
} from "@/lib/api/endpoints";
import type { ImportMapping } from "@/types/api";

export const queryKeys = {
  dashboard: (days: number) => ["dashboard", days] as const,
  growthGraph: (days: number) => ["growth-graph", days] as const,
  opportunities: () => ["opportunities"] as const,
  opportunity: (id: string) => ["opportunity", id] as const,
  reviews: (days: number) => ["reviews", days] as const,
  reviewList: (params: unknown) => ["review-list", params] as const,
  competitors: (days: number) => ["competitors", days] as const,
  signals: (days: number) => ["signals", days] as const,
  inventory: () => ["inventory"] as const,
  customers: (days: number) => ["customer-metrics", days] as const,
  products: (days: number) => ["products", days] as const,
  campaigns: (params: unknown) => ["campaigns", params] as const,
  campaign: (id: string) => ["campaign", id] as const,
  experiments: (params: unknown) => ["experiments", params] as const,
  experiment: (id: string) => ["experiment", id] as const,
  agentRuns: (params: unknown) => ["agent-runs", params] as const,
  agentRun: (id: string) => ["agent-run", id] as const,
  auditLogs: (params: unknown) => ["audit-logs", params] as const,
  settings: () => ["settings"] as const,
  roles: () => ["roles"] as const,
  health: () => ["health"] as const,
};

function describe(error: unknown, fallback: string): string {
  return error instanceof ApiError ? error.message : fallback;
}

// --------------------------------------------------------------------------- //
// Reads
// --------------------------------------------------------------------------- //
export function useDashboard(days: number) {
  return useQuery({
    queryKey: queryKeys.dashboard(days),
    queryFn: () => dashboardApi.overview(days),
  });
}

export function useGrowthGraph(days: number) {
  return useQuery({
    queryKey: queryKeys.growthGraph(days),
    queryFn: () => dashboardApi.growthGraph(days),
  });
}

export function useOpportunities() {
  return useQuery({ queryKey: queryKeys.opportunities(), queryFn: () => growthApi.opportunities() });
}

export function useOpportunity(id: string) {
  return useQuery({
    queryKey: queryKeys.opportunity(id),
    queryFn: () => growthApi.opportunity(id),
    enabled: Boolean(id),
  });
}

/** The Growth Allocation Engine's business/PayPal/hybrid comparison for one opportunity. */
export function useGrowthMission(opportunityId: string | null) {
  return useQuery({
    queryKey: ["growth-mission", opportunityId],
    queryFn: () => growthApi.missions(opportunityId as string),
    enabled: Boolean(opportunityId),
    staleTime: 60_000,
  });
}

export function useGrowthArbitrage() {
  return useQuery({ queryKey: ["growth-arbitrage"], queryFn: () => growthApi.arbitrage() });
}

export function useGrowthAllocation() {
  return useQuery({ queryKey: ["growth-allocation"], queryFn: () => growthApi.allocation() });
}

export function useReviewIntelligence(days: number) {
  return useQuery({ queryKey: queryKeys.reviews(days), queryFn: () => growthApi.reviews(days) });
}

export function useReviewList(params: {
  page?: number;
  page_size?: number;
  topic?: string;
  sentiment?: string;
  daypart?: string;
  rating?: number;
  q?: string;
}) {
  return useQuery({
    queryKey: queryKeys.reviewList(params),
    queryFn: () => growthApi.reviewList(params),
    // Keeps the current page on screen while the next one loads, so paging
    // and filtering never flash an empty card.
    placeholderData: (previous) => previous,
  });
}

export function useDismissOpportunity() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ id, note }: { id: string; note?: string }) =>
      growthApi.setStatus(id, "DISMISSED", note ?? ""),
    onSuccess: (opportunity) => {
      void qc.invalidateQueries({ queryKey: ["opportunities"] });
      void qc.invalidateQueries({ queryKey: ["growth"] });
      toast.success("Dismissed", {
        description: `${opportunity.title} will not be raised again.`,
      });
    },
    onError: (error) => toast.error(describe(error, "Could not dismiss that")),
  });
}

export function useCreateOpportunity() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (payload: Parameters<typeof growthApi.createOpportunity>[0]) =>
      growthApi.createOpportunity(payload),
    onSuccess: (created) => {
      // The canvas reads the same query, so it redraws with the new node.
      void qc.invalidateQueries({ queryKey: ["opportunities"] });
      void qc.invalidateQueries({ queryKey: ["growth"] });
      toast.success("Added to the board", { description: created.title });
    },
    onError: (error) => toast.error(describe(error, "Could not add that opportunity")),
  });
}

export function useDismissSignal() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => growthApi.dismissSignal(id),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ["signals"] });
      toast.success("Signal dismissed", {
        description: "It will not be raised against this merchant again.",
      });
    },
    onError: (error) => toast.error(describe(error, "Could not dismiss the signal")),
  });
}

export function useCompetitors(days = 90) {
  return useQuery({
    queryKey: queryKeys.competitors(days),
    queryFn: () => growthApi.competitors(days),
  });
}

export function useSignals(days = 30) {
  return useQuery({ queryKey: queryKeys.signals(days), queryFn: () => growthApi.signals(days) });
}

export function useInventory() {
  return useQuery({ queryKey: queryKeys.inventory(), queryFn: growthApi.inventory });
}

export function useCustomerMetrics(days: number) {
  return useQuery({
    queryKey: queryKeys.customers(days),
    queryFn: () => dashboardApi.customerMetrics(days),
  });
}

export function useProductAnalytics(days: number) {
  return useQuery({
    queryKey: queryKeys.products(days),
    queryFn: () => dashboardApi.products(days),
  });
}

export function useCampaigns(params: { page?: number; status?: string } = {}) {
  return useQuery({
    queryKey: queryKeys.campaigns(params),
    queryFn: () => campaignApi.list(params),
  });
}

export function useCampaign(id: string) {
  return useQuery({
    queryKey: queryKeys.campaign(id),
    queryFn: () => campaignApi.get(id),
    enabled: Boolean(id),
  });
}

export function useExperiments(params: { page?: number; status?: string } = {}) {
  return useQuery({
    queryKey: queryKeys.experiments(params),
    queryFn: () => experimentApi.list(params),
  });
}

export function useExperiment(id: string) {
  return useQuery({
    queryKey: queryKeys.experiment(id),
    queryFn: () => experimentApi.get(id),
    enabled: Boolean(id),
  });
}

export function useAgentRuns(
  params: { limit?: number; agent_name?: string; channel?: "web" | "voice" } = {},
) {
  return useQuery({
    queryKey: queryKeys.agentRuns(params),
    queryFn: () => agentApi.runs(params),
  });
}

export function useAgentRun(id: string) {
  return useQuery({
    queryKey: queryKeys.agentRun(id),
    queryFn: () => agentApi.run(id),
    enabled: Boolean(id),
  });
}

export function useAuditLogs(params: { page?: number; action?: string } = {}) {
  return useQuery({
    queryKey: queryKeys.auditLogs(params),
    queryFn: () => adminApi.auditLogs(params),
  });
}

export function useSettings() {
  return useQuery({ queryKey: queryKeys.settings(), queryFn: adminApi.settings });
}

export function useRoles() {
  return useQuery({ queryKey: queryKeys.roles(), queryFn: adminApi.roles });
}

// --------------------------------------------------------------------------- //
// Mutations
// --------------------------------------------------------------------------- //
export function useDetectOpportunities() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (days: number) => growthApi.detect(days),
    onSuccess: (radar) => {
      void qc.invalidateQueries({ queryKey: queryKeys.opportunities() });
      toast.success(
        `${radar.opportunities.length} opportunities detected`,
        { description: "Re-running detection refreshes existing ones rather than duplicating them." },
      );
    },
    onError: (error) => toast.error(describe(error, "Detection failed")),
  });
}

export function useInvestigate() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (payload: { question?: string; opportunity_id?: string; days?: number }) =>
      agentApi.investigate(payload),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: queryKeys.opportunities() });
      void qc.invalidateQueries({ queryKey: ["agent-runs"] });
    },
    onError: (error) => toast.error(describe(error, "The investigation could not be completed")),
  });
}

export function useAskAgent() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ message, opportunityId }: { message: string; opportunityId?: string }) =>
      agentApi.ask(message, opportunityId),
    onSuccess: () => void qc.invalidateQueries({ queryKey: ["agent-runs"] }),
    onError: (error) => toast.error(describe(error, "The agent could not answer")),
  });
}

export function useApproveOpportunity() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({
      id,
      approve,
      note,
      executeNow = true,
    }: {
      id: string;
      approve: boolean;
      note?: string;
      executeNow?: boolean;
    }) => agentApi.approve(id, { approve, note, execute_now: executeNow }),
    onSuccess: (outcome) => {
      void qc.invalidateQueries({ queryKey: queryKeys.opportunities() });
      void qc.invalidateQueries({ queryKey: ["experiments"] });
      void qc.invalidateQueries({ queryKey: ["campaigns"] });
      void qc.invalidateQueries({ queryKey: ["agent-runs"] });
      toast[outcome.approved ? "success" : "info"](outcome.message);
    },
    onError: (error) =>
      toast.error(describe(error, "Could not complete the approval"), {
        description:
          error instanceof ApiError && error.isForbidden
            ? "Approving and executing requires the Admin or Owner role."
            : undefined,
      }),
  });
}

export function useMeasureExperiment() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (experimentId: string) => agentApi.measure(experimentId),
    onSuccess: (summary) => {
      void qc.invalidateQueries({ queryKey: ["experiments"] });
      void qc.invalidateQueries({ queryKey: queryKeys.experiment(summary.experiment_id) });
      void qc.invalidateQueries({ queryKey: ["agent-runs"] });
      void qc.invalidateQueries({ queryKey: ["campaigns"] });
      void qc.invalidateQueries({ queryKey: ["growth-arbitrage"] });
      void qc.invalidateQueries({ queryKey: ["growth-allocation"] });
      toast.success(`Decision: ${summary.decision}`, {
        description: `${summary.conversion_lift_pct >= 0 ? "+" : ""}${summary.conversion_lift_pct.toFixed(1)}% conversion lift`,
      });
    },
    onError: (error) => toast.error(describe(error, "Measurement failed")),
  });
}

export function useTeamMembers() {
  return useQuery({ queryKey: ["team-members"], queryFn: adminApi.users });
}

export function usePermissionCatalogue() {
  return useQuery({
    queryKey: ["permission-catalogue"],
    queryFn: adminApi.permissions,
    staleTime: 30 * 60_000,
  });
}

export function useInviteMember() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: adminApi.inviteUser,
    onSuccess: (result) => {
      void qc.invalidateQueries({ queryKey: ["team-members"] });
      const emailed = Boolean(result.meta?.emailed);
      const configured = Boolean(result.meta?.email_configured);
      toast.success(emailed ? "Invitation emailed" : "Invitation created", {
        description: emailed
          ? "They have the sign-in link and temporary password."
          : configured
            ? "The mail server rejected the message — share the password manually."
            : "Email is not configured, so share the temporary password yourself.",
      });
    },
    onError: (error) => toast.error(describe(error, "Could not invite that person")),
  });
}

export function useChangeMemberRole() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: adminApi.changeRole,
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ["team-members"] });
      toast.success("Role updated");
    },
    onError: (error) => toast.error(describe(error, "Could not change that role")),
  });
}

export function useSendTestEmail() {
  return useMutation({
    mutationFn: adminApi.sendTestEmail,
    onSuccess: (result) => toast.success(result.message ?? "Test email sent"),
    onError: (error) => toast.error(describe(error, "Could not send the test email")),
  });
}

export function useCreateRole() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: adminApi.createRole,
    onSuccess: (role) => {
      void qc.invalidateQueries({ queryKey: queryKeys.roles() });
      toast.success(`Role '${role.name}' created`, {
        description: `${role.permissions.length} permissions. Assign it from the members list.`,
      });
    },
    onError: (error) => toast.error(describe(error, "Could not create that role")),
  });
}

export function useDeleteRole() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: adminApi.deleteRole,
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: queryKeys.roles() });
      toast.success("Role deleted");
    },
    onError: (error) => toast.error(describe(error, "Could not delete that role")),
  });
}

export function useCreateCampaign() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (payload: Record<string, unknown>) => campaignApi.create(payload),
    onSuccess: (campaign) => {
      void qc.invalidateQueries({ queryKey: ["campaigns"] });
      toast.success("Campaign drafted", {
        description: "It needs your explicit approval before anything is sent.",
      });
      return campaign;
    },
    onError: (error) => toast.error(describe(error, "Could not create the campaign")),
  });
}

export function useCreateExperiment() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (payload: Record<string, unknown>) => experimentApi.create(payload),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ["experiments"] });
      toast.success("Experiment drafted", {
        description: "Approve it to split the audience and start the trading window.",
      });
    },
    onError: (error) => toast.error(describe(error, "Could not create the experiment")),
  });
}

export function useExperimentApproval() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ id, approve, note }: { id: string; approve: boolean; note?: string }) =>
      experimentApi.approve(id, approve, note),
    onSuccess: (experiment) => {
      void qc.invalidateQueries({ queryKey: ["experiments"] });
      void qc.invalidateQueries({ queryKey: queryKeys.experiment(experiment.id) });
      toast.success(`Experiment ${experiment.status.toLowerCase().replace("_", " ")}`, {
        description:
          experiment.status === "RUNNING"
            ? "Control and test are split on a hash of the customer id."
            : undefined,
      });
    },
    onError: (error) => toast.error(describe(error, "Could not update the experiment")),
  });
}

export function useCampaignApproval() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ id, approve, note }: { id: string; approve: boolean; note?: string }) =>
      campaignApi.approve(id, approve, note),
    onSuccess: (campaign) => {
      void qc.invalidateQueries({ queryKey: ["campaigns"] });
      void qc.invalidateQueries({ queryKey: queryKeys.campaign(campaign.id) });
      toast.success(`Campaign ${campaign.status.toLowerCase().replace("_", " ")}`);
    },
    onError: (error) => toast.error(describe(error, "Could not update the campaign")),
  });
}

export function useExecuteCampaign() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => campaignApi.execute(id),
    onSuccess: (campaign) => {
      void qc.invalidateQueries({ queryKey: ["campaigns"] });
      void qc.invalidateQueries({ queryKey: queryKeys.campaign(campaign.id) });
      void qc.invalidateQueries({ queryKey: ["growth-allocation"] });
      toast.success("Campaign launched", {
        description: "No messaging provider is connected yet, so no messages were sent and no funds moved.",
      });
    },
    onError: (error) =>
      toast.error(describe(error, "Could not launch the campaign"), {
        description:
          error instanceof ApiError && error.code === "APPROVAL_REQUIRED"
            ? "It needs an explicit approval on record first."
            : undefined,
      }),
  });
}

export function useInventoryAction() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({
      itemId,
      action,
      quantity,
      note,
    }: {
      itemId: string;
      action: string;
      quantity?: number;
      note?: string;
    }) => growthApi.inventoryAction(itemId, { action, quantity, note }),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: queryKeys.inventory() });
      toast.success("Recorded", {
        description: "Your decision is logged. The system never places an order itself.",
      });
    },
    onError: (error) => toast.error(describe(error, "Could not record the action")),
  });
}

export function useReviewSearch() {
  return useMutation({
    mutationFn: ({ query, topic }: { query: string; topic?: string }) =>
      growthApi.reviewSearch(query, topic),
    onError: (error) => toast.error(describe(error, "Search failed")),
  });
}

// --------------------------------------------------------------------------- //
// Inventory automation
// --------------------------------------------------------------------------- //
export function useInventoryItems(params: {
  page?: number;
  page_size?: number;
  status?: string;
  q?: string;
} = {}) {
  return useQuery({
    queryKey: ["inventory", "items", params],
    queryFn: () => inventoryApi.items(params),
    placeholderData: (previous) => previous,
  });
}

export function useInventoryItem(id: string | null) {
  return useQuery({
    queryKey: ["inventory", "item", id],
    queryFn: () => inventoryApi.item(id as string),
    enabled: Boolean(id),
  });
}

export function useInventoryLedger(params: Record<string, unknown> = {}) {
  return useQuery({
    queryKey: ["inventory", "ledger", params],
    queryFn: () => inventoryApi.ledger(params),
    placeholderData: (previous) => previous,
  });
}

export function useStockBook(params: { start?: string; end?: string } = {}) {
  return useQuery({
    queryKey: ["inventory", "book", params],
    queryFn: () => inventoryApi.book(params),
  });
}

export function useAutomationRuns(params: Record<string, unknown> = {}) {
  return useQuery({
    queryKey: ["inventory-automation", params],
    queryFn: () => inventoryApi.automation(params),
    placeholderData: (previous) => previous,
  });
}

export function useAutomationTrace(correlationId: string | null) {
  return useQuery({
    queryKey: ["inventory-automation", "trace", correlationId],
    queryFn: () => inventoryApi.trace(correlationId as string),
    enabled: Boolean(correlationId),
  });
}

export function useVendors() {
  return useQuery({ queryKey: ["inventory", "vendors"], queryFn: inventoryApi.vendors });
}

export function useCreateVendor() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (payload: Record<string, unknown>) => inventoryApi.createVendor(payload),
    onSuccess: (vendor) => {
      void qc.invalidateQueries({ queryKey: ["inventory", "vendors"] });
      toast.success(`${vendor.name} added`, {
        description: "Link it to the items it supplies before automation can pick it.",
      });
    },
    onError: (error) => toast.error(describe(error, "Could not add the vendor")),
  });
}

export function usePurchaseOrders(params: Record<string, unknown> = {}) {
  return useQuery({
    queryKey: ["purchase-orders", params],
    queryFn: () => inventoryApi.purchaseOrders(params),
    placeholderData: (previous) => previous,
  });
}

export function useAdjustStock() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({
      id,
      ...payload
    }: {
      id: string;
      movement_type: string;
      quantity: number;
      note?: string;
    }) => inventoryApi.adjust(id, payload),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ["inventory"] });
      toast.success("Stock adjusted", { description: "The ledger records who and why." });
    },
    onError: (error) => toast.error(describe(error, "Could not adjust the stock")),
  });
}

export function useSetInventoryPolicy() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ id, ...payload }: { id: string } & Record<string, unknown>) =>
      inventoryApi.setPolicy(id, payload),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ["inventory"] });
      toast.success("Reorder policy saved");
    },
    onError: (error) => toast.error(describe(error, "Could not save the policy")),
  });
}

export function useForceReorder() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => inventoryApi.reorder(id),
    onSuccess: (result) => {
      void qc.invalidateQueries({ queryKey: ["inventory"] });
      void qc.invalidateQueries({ queryKey: ["purchase-orders"] });
      void qc.invalidateQueries({ queryKey: ["inventory-automation"] });
      const tone = result.status === "COMPLETED" || result.status === "AWAITING_APPROVAL";
      if (tone) {
        toast.success(result.reference ? `Order ${result.reference}` : "Replenishment ran", {
          description: result.reason,
        });
      } else {
        toast.info("No order raised", { description: result.reason });
      }
    },
    onError: (error) => toast.error(describe(error, "Replenishment failed")),
  });
}

export function useApprovePurchaseOrder() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ id, approve, note }: { id: string; approve: boolean; note?: string }) =>
      inventoryApi.approveOrder(id, approve, note),
    onSuccess: (order) => {
      void qc.invalidateQueries({ queryKey: ["purchase-orders"] });
      void qc.invalidateQueries({ queryKey: ["inventory"] });
      toast.success(`${order.reference} ${order.status.toLowerCase().replace("_", " ")}`);
    },
    onError: (error) => toast.error(describe(error, "Could not update the order")),
  });
}

export function useReceivePurchaseOrder() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({
      id,
      lines,
    }: {
      id: string;
      lines: { line_id: string; quantity: number }[];
    }) => inventoryApi.receiveOrder(id, lines),
    onSuccess: (order) => {
      void qc.invalidateQueries({ queryKey: ["purchase-orders"] });
      void qc.invalidateQueries({ queryKey: ["inventory"] });
      toast.success(`${order.reference} ${order.status.toLowerCase().replace("_", " ")}`, {
        description: "Stock and the ledger were updated.",
      });
    },
    onError: (error) => toast.error(describe(error, "Could not record the receipt")),
  });
}

// --------------------------------------------------------------------------- //
// Agent memory
// --------------------------------------------------------------------------- //
export function useMemoryStatus() {
  return useQuery({
    queryKey: ["memory", "status"],
    queryFn: () => memoryApi.status(),
    staleTime: 60_000,
  });
}

export function useMemorySearch(query: string, kind: string) {
  return useQuery({
    // Only runs once the query is long enough for the backend to accept it, so
    // typing a single character does not produce a 422 in the console.
    enabled: query.trim().length >= 2,
    queryKey: ["memory", "search", query, kind],
    queryFn: () => memoryApi.search({ q: query.trim(), limit: 20, kind: kind || undefined }),
  });
}

export function useRememberNote() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (payload: { text: string; kind?: string; tags?: string[] }) =>
      memoryApi.remember(payload),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ["memory"] });
      toast.success("Queued for the agents to learn", {
        description: "Building the knowledge graph takes a few seconds.",
      });
    },
    onError: (error) => toast.error(describe(error, "Could not save that memory")),
  });
}

export function useForgetMemory() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: () => memoryApi.forget(),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ["memory"] });
      toast.success("Memory erased for this merchant");
    },
    onError: (error) => toast.error(describe(error, "Could not erase memory")),
  });
}

// --------------------------------------------------------------------------- //
// Bulk import
// --------------------------------------------------------------------------- //
export function useInventoryImportPreview() {
  return useMutation({
    mutationFn: ({ file, mapping }: { file: File; mapping?: ImportMapping }) =>
      inventoryApi.importPreview(file, mapping),
    onError: (error) => toast.error(describe(error, "Could not read that file")),
  });
}

export function useInventoryImportCommit() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ file, mapping }: { file: File; mapping: ImportMapping }) =>
      inventoryApi.importCommit(file, mapping),
    onSuccess: (result) => {
      void qc.invalidateQueries({ queryKey: ["inventory"] });
      void qc.invalidateQueries({ queryKey: ["inventory-automation"] });
      if (result.failed > 0) {
        toast.warning(`Imported ${result.created + result.updated} of ${result.total_rows} rows`, {
          description: `${result.failed} row${result.failed === 1 ? "" : "s"} failed after passing preview - see the details below.`,
        });
      } else {
        toast.success(`${result.created} created, ${result.updated} updated`, {
          description:
            result.skipped > 0
              ? `${result.skipped} row${result.skipped === 1 ? "" : "s"} skipped (flagged in the preview).`
              : "Every valid row was imported.",
        });
      }
    },
    onError: (error) => toast.error(describe(error, "Import failed")),
  });
}
