"use client";

/** React Query hooks for Supply Agents, approvals, PayPal and unified intelligence. */

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";

import { ApiError } from "@/lib/api/client";
import { approvalsApi, intelligenceApi, paypalApi, supplyApi, type ProcurementCreate } from "@/lib/api/supply";

function describe(error: unknown, fallback: string): string {
  return error instanceof ApiError ? error.message : fallback;
}

/** Everything that changes when money or stock moves. */
const SUPPLY_KEYS = [
  ["procurement"],
  ["procurements"],
  ["supply-overview"],
  ["supply-demand"],
  ["approvals"],
  ["supplier-invoices"],
  ["goods-receipts"],
  ["reconciliations"],
  ["payments"],
  ["command-center"],
  ["events"],
  ["suppliers"],
  ["purchase-orders"],
  ["inventory"],
];

function useInvalidateSupply() {
  const qc = useQueryClient();
  return () => SUPPLY_KEYS.forEach((key) => void qc.invalidateQueries({ queryKey: key }));
}

// --------------------------------------------------------------------------- //
// Reads
// --------------------------------------------------------------------------- //
export function useCommandCenter(days = 30) {
  return useQuery({ queryKey: ["command-center", days], queryFn: () => intelligenceApi.commandCenter(days),
    refetchInterval: 30_000 });
}

export function useBusinessEvents(params: { limit?: number; module?: string; correlation_id?: string } = {}) {
  return useQuery({ queryKey: ["events", params], queryFn: () => intelligenceApi.events(params), refetchInterval: 20_000 });
}

export function useSupplyOverview() {
  return useQuery({ queryKey: ["supply-overview"], queryFn: supplyApi.overview, refetchInterval: 20_000 });
}

export function useDemand() {
  return useQuery({ queryKey: ["supply-demand"], queryFn: supplyApi.demand });
}

export function useSuppliers() {
  return useQuery({ queryKey: ["suppliers"], queryFn: supplyApi.suppliers });
}

export function useSupplier(id: string) {
  return useQuery({ queryKey: ["suppliers", id], queryFn: () => supplyApi.supplier(id), enabled: Boolean(id) });
}

export function useProcurements(params: { page?: number; page_size?: number; status?: string } = {}) {
  return useQuery({ queryKey: ["procurements", params], queryFn: () => supplyApi.procurements(params),
    placeholderData: (previous) => previous, refetchInterval: 15_000 });
}

/** Polls quickly while a negotiation is live, slowly otherwise. */
export function useProcurement(id: string) {
  return useQuery({
    queryKey: ["procurement", id],
    queryFn: () => supplyApi.procurement(id),
    enabled: Boolean(id),
    refetchInterval: (query) => {
      const status = query.state.data?.status;
      return status === "SOURCING" || status === "NEGOTIATING" ? 2_500 : 15_000;
    },
  });
}

export function useProcurementMessages(id: string, live = true) {
  return useQuery({ queryKey: ["procurement", id, "messages"], queryFn: () => supplyApi.messages(id),
    enabled: Boolean(id), refetchInterval: live ? 3_000 : false });
}

export function useAgentMessages(params: { message_type?: string; limit?: number } = {}) {
  return useQuery({ queryKey: ["agent-messages", params], queryFn: () => supplyApi.allMessages(params),
    refetchInterval: 15_000 });
}

export function useGoodsReceipts() {
  return useQuery({ queryKey: ["goods-receipts"], queryFn: supplyApi.receipts });
}

export function useSupplierInvoices(status?: string) {
  return useQuery({ queryKey: ["supplier-invoices", status], queryFn: () => supplyApi.invoices(status) });
}

export function useReconciliations() {
  return useQuery({ queryKey: ["reconciliations"], queryFn: supplyApi.reconciliations });
}

export function useApprovals(status?: string) {
  return useQuery({ queryKey: ["approvals", status], queryFn: () => approvalsApi.list(status), refetchInterval: 15_000 });
}

export function useApproval(id: string | null) {
  return useQuery({ queryKey: ["approvals", "one", id], queryFn: () => approvalsApi.get(id as string), enabled: Boolean(id) });
}

export function usePayments(kind?: string) {
  return useQuery({ queryKey: ["payments", kind], queryFn: () => approvalsApi.payments(kind) });
}

export function usePayPalStatus() {
  return useQuery({ queryKey: ["paypal", "status"], queryFn: paypalApi.status });
}

export function usePayPalTransactions(params: { page?: number; page_size?: number; category?: string } = {}) {
  return useQuery({ queryKey: ["paypal", "transactions", params], queryFn: () => paypalApi.transactions(params),
    placeholderData: (previous) => previous });
}

export function usePayPalIntelligence(days = 30) {
  return useQuery({ queryKey: ["paypal", "intelligence", days], queryFn: () => paypalApi.intelligence(days) });
}

export function usePayPalWebhooks() {
  return useQuery({ queryKey: ["paypal", "webhooks"], queryFn: paypalApi.webhooks, refetchInterval: 20_000 });
}

export function usePayPalInvoices() {
  return useQuery({ queryKey: ["paypal", "invoices"], queryFn: paypalApi.invoices });
}

export function usePayPalPayouts() {
  return useQuery({ queryKey: ["paypal", "payouts"], queryFn: paypalApi.payouts });
}

export function usePayPalSubscriptions() {
  return useQuery({ queryKey: ["paypal", "subscriptions"], queryFn: paypalApi.subscriptions });
}

export function usePayPalPlans() {
  return useQuery({ queryKey: ["paypal", "plans"], queryFn: paypalApi.plans });
}

// --------------------------------------------------------------------------- //
// Mutations
// --------------------------------------------------------------------------- //
export function useCreateProcurement() {
  const invalidate = useInvalidateSupply();
  return useMutation({
    mutationFn: (payload: ProcurementCreate) => supplyApi.createProcurement(payload),
    onSuccess: (request) => {
      invalidate();
      toast.success(`${request.reference} raised`, {
        description: `RFQ ${request.rfq_reference} - budget ${request.policy.max_budget} ${request.currency}`,
      });
    },
    onError: (error) => toast.error(describe(error, "Could not raise the procurement request")),
  });
}

export function useProcurementAutopilot() {
  const invalidate = useInvalidateSupply();
  return useMutation({
    mutationFn: (payload: { inventory_item_id?: string }) => supplyApi.autopilot(payload),
    onSuccess: ({ data }) => {
      invalidate();
      if (data) toast.success(`${data.reference}: ${data.status.toLowerCase().replace(/_/g, " ")}`);
      else toast.info("Nothing is at stockout risk right now.");
    },
    onError: (error) => toast.error(describe(error, "The procurement workflow failed")),
  });
}

export function useAdvanceNegotiation(id: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: () => supplyApi.advance(id),
    onSuccess: ({ data }) => {
      qc.setQueryData(["procurement", id], data);
      void qc.invalidateQueries({ queryKey: ["procurement", id, "messages"] });
      void qc.invalidateQueries({ queryKey: ["approvals"] });
      void qc.invalidateQueries({ queryKey: ["procurements"] });
    },
    onError: (error) => toast.error(describe(error, "Could not advance the negotiation")),
  });
}

export function useDecideProcurement(id: string) {
  const invalidate = useInvalidateSupply();
  return useMutation({
    mutationFn: ({ approve, note }: { approve: boolean; note?: string }) => supplyApi.decide(id, approve, note),
    onSuccess: (request) => {
      invalidate();
      toast.success(request.status === "REJECTED" ? "Purchase rejected" : "Purchase approved - order issued");
    },
    onError: (error) => toast.error(describe(error, "Could not record the decision")),
  });
}

export function useDecideApproval() {
  const invalidate = useInvalidateSupply();
  return useMutation({
    mutationFn: ({ id, approve, note }: { id: string; approve: boolean; note?: string }) =>
      approvalsApi.decide(id, approve, note),
    onSuccess: (approval) => {
      invalidate();
      toast.success(`${approval.reference} ${approval.status.toLowerCase()}`);
    },
    onError: (error) => toast.error(describe(error, "Could not record the decision")),
  });
}

export function useExecuteApproval() {
  const invalidate = useInvalidateSupply();
  return useMutation({
    mutationFn: (id: string) => approvalsApi.execute(id),
    onSuccess: (execution) => {
      invalidate();
      toast.success(`Payout ${execution.status.toLowerCase()}`, { description: `${execution.mode} - ${execution.paypal_payout_batch_id}` });
    },
    onError: (error) => toast.error(describe(error, "Could not execute the payout")),
  });
}

export function useReceiveGoods() {
  const invalidate = useInvalidateSupply();
  return useMutation({
    mutationFn: ({ orderId, lines, notes }: { orderId: string; lines: { line_id: string; quantity: number }[]; notes?: string }) =>
      supplyApi.receive(orderId, lines, notes),
    onSuccess: (receipt) => {
      invalidate();
      toast.success(`${receipt.reference} booked`, {
        description: receipt.is_partial ? "Partial delivery - matching re-run." : "Order fully received - matching re-run.",
      });
    },
    onError: (error) => toast.error(describe(error, "Could not record the receipt")),
  });
}

export function useMatchInvoice() {
  const invalidate = useInvalidateSupply();
  return useMutation({
    mutationFn: (invoiceId: string) => supplyApi.match(invoiceId),
    onSuccess: (match) => {
      invalidate();
      toast[match.status === "DISCREPANCY" ? "warning" : "success"](`Three-way match: ${match.status.toLowerCase().replace(/_/g, " ")}`);
    },
    onError: (error) => toast.error(describe(error, "Matching failed")),
  });
}

export function useApprovePayment() {
  const invalidate = useInvalidateSupply();
  return useMutation({
    mutationFn: ({ invoiceId, approve, note }: { invoiceId: string; approve: boolean; note?: string }) =>
      supplyApi.approvePayment(invoiceId, approve, note),
    onSuccess: () => {
      invalidate();
      toast.success("Payment decision recorded");
    },
    onError: (error) => toast.error(describe(error, "Could not record the payment decision")),
  });
}

export function usePayInvoice() {
  const invalidate = useInvalidateSupply();
  return useMutation({
    mutationFn: (invoiceId: string) => supplyApi.pay(invoiceId),
    onSuccess: (execution) => {
      invalidate();
      if (execution.status === "PAYER_ACTION_REQUIRED") {
        toast.info("Approve the payment in PayPal", { description: "Then return here and capture it." });
      } else {
        toast.success(`PayPal payment ${execution.status.toLowerCase()}`, {
          description: `${execution.mode} - capture ${execution.paypal_capture_id}`,
        });
      }
    },
    onError: (error) => toast.error(describe(error, "Payment failed")),
  });
}

export function useCapturePayment() {
  const invalidate = useInvalidateSupply();
  return useMutation({
    mutationFn: (executionId: string) => supplyApi.capture(executionId),
    onSuccess: () => {
      invalidate();
      toast.success("Payment captured");
    },
    onError: (error) => toast.error(describe(error, "Capture failed")),
  });
}

export function useReconcile() {
  const invalidate = useInvalidateSupply();
  return useMutation({
    mutationFn: (orderId: string) => supplyApi.reconcile(orderId),
    onSuccess: () => {
      invalidate();
      toast.success("Reconciled - inventory and margin updated");
    },
    onError: (error) => toast.error(describe(error, "Not ready to reconcile")),
  });
}

export function usePayPalSync() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (days?: number) => paypalApi.sync(days),
    onSuccess: (result) => {
      void qc.invalidateQueries({ queryKey: ["paypal"] });
      void qc.invalidateQueries({ queryKey: ["command-center"] });
      toast.success(`Synced ${String(result.inserted)} new, ${String(result.updated)} updated`, {
        description: `${String(result.mode)} - ${String(result.windows)} window(s) of <= 31 days`,
      });
    },
    onError: (error) => toast.error(describe(error, "Sync failed")),
  });
}

export function useCreatePayPalInvoice() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: paypalApi.createInvoice,
    onSuccess: (invoice) => {
      void qc.invalidateQueries({ queryKey: ["paypal", "invoices"] });
      toast.success(`Invoice ${invoice.invoice_number || invoice.paypal_invoice_id} ${invoice.status.toLowerCase()}`);
    },
    onError: (error) => toast.error(describe(error, "Could not create the invoice")),
  });
}

export function usePayPalInvoiceAction() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ id, action, note }: { id: string; action: "remind" | "cancel" | "refresh"; note?: string }) =>
      paypalApi.invoiceAction(id, action, note),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ["paypal", "invoices"] });
      toast.success("Invoice updated");
    },
    onError: (error) => toast.error(describe(error, "Invoice action failed")),
  });
}

export function useRequestCashback() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: paypalApi.requestCashback,
    onSuccess: (approval) => {
      void qc.invalidateQueries({ queryKey: ["approvals"] });
      toast.success(`${approval.reference} awaiting approval`, { description: "A person with payment:approve must approve it." });
    },
    onError: (error) => toast.error(describe(error, "Could not request the payout")),
  });
}

export function useSubscriptionAction() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ id, action, reason }: { id: string; action: "suspend" | "activate" | "cancel" | "recover"; reason?: string }) =>
      paypalApi.subscriptionAction(id, action, reason),
    onSuccess: (row) => {
      void qc.invalidateQueries({ queryKey: ["paypal", "subscriptions"] });
      toast.success(`Subscription ${row.status.toLowerCase()}`);
    },
    onError: (error) => toast.error(describe(error, "Subscription action failed")),
  });
}

export function useCreatePlan() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: paypalApi.createPlan,
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ["paypal", "plans"] });
      toast.success("Plan created");
    },
    onError: (error) => toast.error(describe(error, "Could not create the plan")),
  });
}

export function useSimulateWebhook() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: paypalApi.simulateWebhook,
    onSuccess: (result) => {
      void qc.invalidateQueries({ queryKey: ["paypal"] });
      toast.success(`Webhook ${result.outcome}`, { description: result.event?.event_type });
    },
    onError: (error) => toast.error(describe(error, "Webhook simulation failed")),
  });
}
