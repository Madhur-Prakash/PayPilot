"use client";

/** React Query hooks for the sponsor integrations. */

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";

import { ApiError } from "@/lib/api/client";
import { integrationsApi } from "@/lib/api/integrations";

function describe(error: unknown, fallback: string): string {
  return error instanceof ApiError ? error.message : fallback;
}

export function useIntegrationStatus() {
  return useQuery({ queryKey: ["integrations-status"], queryFn: integrationsApi.status, refetchInterval: 30_000 });
}

export function useEvidenceSearch(q: string, kinds?: string[]) {
  const trimmed = q.trim();
  return useQuery({
    queryKey: ["evidence-search", trimmed, kinds?.join(",") ?? ""],
    queryFn: () => integrationsApi.search({ q: trimmed, kinds: kinds?.length ? kinds.join(",") : undefined }),
    enabled: trimmed.length >= 2,
    staleTime: 15_000,
  });
}

export function useProcurementTimeline(limit = 12) {
  return useQuery({ queryKey: ["procurement-timeline", limit], queryFn: () => integrationsApi.timeline(limit), refetchInterval: 30_000 });
}

export function useStudioDatasets() {
  return useQuery({ queryKey: ["studio-datasets"], queryFn: integrationsApi.studioDatasets, staleTime: 60_000 });
}

export function useMcpTools() {
  return useQuery({ queryKey: ["paypal-mcp-tools"], queryFn: integrationsApi.mcpTools, retry: false });
}

export function useBenchmark() {
  return useMutation({
    mutationFn: integrationsApi.benchmark,
    onError: (e) => toast.error(describe(e, "Could not fetch the market reference.")),
  });
}

export function useMcpCall() {
  return useMutation({
    mutationFn: ({ tool, args }: { tool: string; args?: Record<string, unknown> }) => integrationsApi.mcpCall(tool, args),
    onError: (e) => toast.error(describe(e, "The PayPal MCP call failed.")),
  });
}

export function useOpenPortal() {
  return useMutation({
    mutationFn: integrationsApi.openPortal,
    onError: (e) => toast.error(describe(e, "Could not open the supplier page.")),
  });
}

export function useClosePortal() {
  return useMutation({ mutationFn: integrationsApi.closePortal });
}

export function useZapierTest() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: integrationsApi.zapierTest,
    onSuccess: (data) => {
      if (data.sent) toast.success("Signed test event delivered to Zapier.");
      else toast.info(data.note ?? "Zapier is not configured.");
      void qc.invalidateQueries({ queryKey: ["integrations-status"] });
    },
    onError: (e) => toast.error(describe(e, "Zapier did not accept the test event.")),
  });
}

export function useReindex() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: integrationsApi.reindex,
    onSuccess: (data) => {
      toast.success(data.engine === "elasticsearch" ? `Indexed ${String(data.documents)} documents.` : String(data.note));
      void qc.invalidateQueries({ queryKey: ["evidence-search"] });
    },
    onError: (e) => toast.error(describe(e, "Re-indexing failed.")),
  });
}
