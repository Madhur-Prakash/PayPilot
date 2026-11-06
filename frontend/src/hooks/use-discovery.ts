"use client";

/** React Query hooks for Product Discovery, Supply Intelligence, the Merchant OS agents and payments. */

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";

import { ApiError } from "@/lib/api/client";
import { discoveryApi, merchantAgentsApi, paymentsApi, supplyIntelApi } from "@/lib/api/discovery";
import type { AgentKey, SearchRequest } from "@/types/discovery";

function describe(error: unknown, fallback: string): string {
  return error instanceof ApiError ? error.message : fallback;
}

/** True when the backend says Channel3 has no API key - the UI shows setup steps instead of an error. */
export function isChannel3Unconfigured(error: unknown): boolean {
  return error instanceof ApiError && error.code === "CHANNEL3_NOT_CONFIGURED";
}

const INTEL_KEYS = [["supply-intel"], ["recommendations"], ["discovery-history"], ["discovered"], ["autopilot"],
  ["agent-activity"], ["payments-history"], ["approvals"], ["payments"], ["command-center"]];

function useInvalidateIntel() {
  const qc = useQueryClient();
  return () => INTEL_KEYS.forEach((key) => void qc.invalidateQueries({ queryKey: key }));
}

// --------------------------------------------------------------------------- //
// Discovery
// --------------------------------------------------------------------------- //
export function useDiscoveryStatus() {
  return useQuery({ queryKey: ["discovery-status"], queryFn: discoveryApi.status, staleTime: 5 * 60_000 });
}

export function useProductSearch() {
  const invalidate = useInvalidateIntel();
  return useMutation({
    mutationFn: (body: SearchRequest) => discoveryApi.search(body),
    onSuccess: () => invalidate(),
    onError: (error) => {
      if (!isChannel3Unconfigured(error)) toast.error(describe(error, "Search failed"));
    },
  });
}

export function useSearchHistory(limit = 30) {
  return useQuery({ queryKey: ["discovery-history", limit], queryFn: () => discoveryApi.history(limit) });
}

export function useDiscovered(params: { limit?: number; shortlisted?: boolean } = {}) {
  return useQuery({ queryKey: ["discovered", params], queryFn: () => discoveryApi.discovered(params) });
}

export function useProductDetail(id: string | null) {
  return useQuery({
    queryKey: ["product-detail", id],
    queryFn: () => discoveryApi.product(id as string),
    enabled: Boolean(id),
    staleTime: 5 * 60_000,
    retry: (count, error) => !isChannel3Unconfigured(error) && count < 1,
  });
}

export function useComparison(ids: string[]) {
  return useQuery({
    queryKey: ["comparison", ids.join(",")],
    queryFn: () => discoveryApi.compare(ids),
    enabled: ids.length >= 2,
    staleTime: 10 * 60_000,
    retry: false,
  });
}

export function useSimilar() {
  return useMutation({
    mutationFn: discoveryApi.similar,
    onError: (error) => toast.error(describe(error, "Could not load similar products")),
  });
}

export function useEnrich() {
  const invalidate = useInvalidateIntel();
  return useMutation({
    mutationFn: (url: string) => discoveryApi.enrich(url),
    onSuccess: () => invalidate(),
    onError: (error) => toast.error(describe(error, "Could not read that product page")),
  });
}

export function useShortlist() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ id, value }: { id: string; value: boolean }) => discoveryApi.shortlist(id, value),
    onSuccess: (row) => {
      void qc.invalidateQueries({ queryKey: ["discovered"] });
      toast.success(row.is_shortlisted ? "Added to your shortlist" : "Removed from your shortlist");
    },
    onError: (error) => toast.error(describe(error, "Could not update the shortlist")),
  });
}

export function useAssistantTurn() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ message, conversationId }: { message: string; conversationId?: string | null }) =>
      discoveryApi.assistantTurn(message, conversationId),
    onSuccess: (result) => {
      qc.setQueryData(["conversation", result.conversation.id], result.conversation);
      void qc.invalidateQueries({ queryKey: ["conversations"] });
    },
    onError: (error) => {
      if (!isChannel3Unconfigured(error)) toast.error(describe(error, "The shopping assistant did not answer"));
    },
  });
}

export function useConversations() {
  return useQuery({ queryKey: ["conversations"], queryFn: discoveryApi.conversations });
}

export function useConversation(id: string | null) {
  return useQuery({ queryKey: ["conversation", id], queryFn: () => discoveryApi.conversation(id as string), enabled: Boolean(id) });
}

// --------------------------------------------------------------------------- //
// Supply intelligence
// --------------------------------------------------------------------------- //
export function useSupplyIntel(days = 30) {
  return useQuery({ queryKey: ["supply-intel", days], queryFn: () => supplyIntelApi.overview(days) });
}

export function useCatalogProducts() {
  return useQuery({ queryKey: ["catalog-products"], queryFn: supplyIntelApi.catalogProducts });
}

export function usePricing() {
  return useMutation({
    mutationFn: supplyIntelApi.pricing,
    onError: (error) => {
      if (!isChannel3Unconfigured(error)) toast.error(describe(error, "Market price check failed"));
    },
  });
}

export function useAlternatives() {
  return useMutation({
    mutationFn: ({ productId, limit }: { productId: string; limit?: number }) => supplyIntelApi.alternatives(productId, limit),
    onError: (error) => {
      if (!isChannel3Unconfigured(error)) toast.error(describe(error, "Could not find alternatives"));
    },
  });
}

export function useSaveAlternative() {
  const invalidate = useInvalidateIntel();
  return useMutation({
    mutationFn: ({ productId, channel3Id }: { productId: string; channel3Id: string }) =>
      supplyIntelApi.saveAlternative(productId, channel3Id),
    onSuccess: (rec) => {
      invalidate();
      toast.success(`${rec.reference} saved for approval`);
    },
    onError: (error) => toast.error(describe(error, "Could not save the alternative")),
  });
}

export function useRecommendations(params: { status?: string; kind?: string } = {}) {
  return useQuery({ queryKey: ["recommendations", params], queryFn: () => supplyIntelApi.recommendations(params),
    refetchInterval: 30_000 });
}

export function useGenerateRecommendations() {
  const invalidate = useInvalidateIntel();
  return useMutation({
    mutationFn: supplyIntelApi.generate,
    onSuccess: (result) => {
      invalidate();
      toast.success(result.recommendations.length
        ? `${result.recommendations.length} recommendation(s) ready for review`
        : "No new recommendations - see the notes");
    },
    onError: (error) => {
      if (!isChannel3Unconfigured(error)) toast.error(describe(error, "Could not generate recommendations"));
    },
  });
}

type RecAction = "approve" | "reject" | "execute" | "measure";

export function useRecommendationAction() {
  const invalidate = useInvalidateIntel();
  return useMutation({
    mutationFn: ({ id, action, note, retailPrice }: { id: string; action: RecAction; note?: string; retailPrice?: number | null }) => {
      if (action === "approve") return supplyIntelApi.approve(id, note);
      if (action === "reject") return supplyIntelApi.reject(id, note);
      if (action === "execute") return supplyIntelApi.execute(id, retailPrice);
      return supplyIntelApi.measure(id);
    },
    onSuccess: (rec) => {
      invalidate();
      toast.success(`${rec.reference}: ${rec.status.toLowerCase()}`);
    },
    onError: (error) => toast.error(describe(error, "That action could not be completed")),
  });
}

export function useRequestPurchase() {
  const invalidate = useInvalidateIntel();
  return useMutation({
    mutationFn: ({ id, ...body }: { id: string; quantity: number; unit_cost: number; payee_email: string }) =>
      supplyIntelApi.purchase(id, body),
    onSuccess: (approval) => {
      invalidate();
      toast.success(`${approval.reference} sent for payment approval`);
    },
    onError: (error) => toast.error(describe(error, "Could not request the purchase")),
  });
}

export function useAutopilot() {
  return useQuery({ queryKey: ["autopilot"], queryFn: supplyIntelApi.autopilot });
}

export function useRunAutopilot() {
  const invalidate = useInvalidateIntel();
  return useMutation({
    mutationFn: supplyIntelApi.runAutopilot,
    onSuccess: (run) => {
      invalidate();
      toast.success(run.requires_approval ? "Autopilot finished - recommendations wait for your approval" : "Autopilot finished");
    },
    onError: (error) => {
      if (!isChannel3Unconfigured(error)) toast.error(describe(error, "The autopilot could not finish"));
    },
  });
}

// --------------------------------------------------------------------------- //
// Agents
// --------------------------------------------------------------------------- //
export function useAgentCatalogue() {
  return useQuery({ queryKey: ["agent-catalogue"], queryFn: merchantAgentsApi.catalogue, staleTime: 10 * 60_000 });
}

export function useAgentActivity(params: { limit?: number; agent_name?: string; status?: string } = {}) {
  return useQuery({ queryKey: ["agent-activity", params], queryFn: () => merchantAgentsApi.activity(params),
    refetchInterval: 15_000 });
}

export function useExecuteAgents() {
  const invalidate = useInvalidateIntel();
  return useMutation({
    mutationFn: ({ message, agent, params }: { message: string; agent?: AgentKey | null; params?: Record<string, unknown> }) =>
      merchantAgentsApi.execute(message, agent, params),
    onSuccess: () => invalidate(),
    onError: (error) => toast.error(describe(error, "The agents could not complete the request")),
  });
}

// --------------------------------------------------------------------------- //
// Payments
// --------------------------------------------------------------------------- //
export function usePaymentHistory(kind?: string) {
  return useQuery({ queryKey: ["payments-history", kind], queryFn: () => paymentsApi.history({ kind }), refetchInterval: 15_000 });
}

export function usePaymentOrder(executionId: string | null) {
  return useQuery({ queryKey: ["payment-order", executionId], queryFn: () => paymentsApi.order(executionId as string),
    enabled: Boolean(executionId) });
}

export function useCreatePaymentOrder() {
  const invalidate = useInvalidateIntel();
  return useMutation({
    mutationFn: ({ approvalId, idempotencyKey }: { approvalId: string; idempotencyKey: string }) =>
      paymentsApi.createOrder(approvalId, idempotencyKey),
    onSuccess: (execution) => {
      invalidate();
      if (execution.status === "FAILED") toast.error(`PayPal refused the order: ${execution.error}`);
      else toast.success(execution.status === "PAYER_ACTION_REQUIRED"
        ? "PayPal order created - approve it in PayPal, then capture"
        : "PayPal order created - ready to capture");
    },
    onError: (error) => toast.error(describe(error, "Could not create the PayPal order")),
  });
}

export function useCaptureOrder() {
  const invalidate = useInvalidateIntel();
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (executionId: string) => paymentsApi.capture(executionId),
    onSuccess: (execution) => {
      invalidate();
      void qc.invalidateQueries({ queryKey: ["payment-order", execution.execution_id] });
      toast.success(`Captured ${execution.paypal_capture_id || "payment"}`);
    },
    onError: (error) => toast.error(describe(error, "Capture failed")),
  });
}
