"use client";

/** PayPal webhooks: verified before they are trusted, recorded once, re-processable if a handler failed. */

import type { ColDef } from "ag-grid-community";
import { RotateCcw } from "lucide-react";
import * as React from "react";

import { ErrorState } from "@/components/common/states";
import { DataGrid } from "@/components/data/data-grid";
import { ModeBadge, PageHeader, StatusPill } from "@/components/supply/shared";
import { Card, CardContent } from "@/components/ui/primitives";
import { usePayPalStatus, usePayPalWebhooks } from "@/hooks/use-supply";
import { paypalApi } from "@/lib/api/supply";
import { formatDateTime } from "@/lib/utils";
import { useAuthStore } from "@/stores/auth";
import type { WebhookEventRow } from "@/types/supply";

export default function WebhooksPage() {
  const { data, isLoading, error, refetch } = usePayPalWebhooks();
  const status = usePayPalStatus();
  const canManage = useAuthStore((s) => s.can("paypal:manage"));
  const columns = React.useMemo<ColDef<WebhookEventRow>[]>(() => [
    { field: "received_at", headerName: "Received", valueFormatter: (p) => formatDateTime(p.value as string), minWidth: 150 },
    { field: "event_type", headerName: "Event", minWidth: 220 },
    { field: "event_id", headerName: "Event id", cellClass: "font-mono text-2xs", minWidth: 180 },
    { field: "verification_status", headerName: "Verification", cellRenderer: (p: { value: string }) => <StatusPill status={p.value === "REJECTED" ? "REJECTED" : p.value} /> },
    { field: "processing_status", headerName: "Processing", cellRenderer: (p: { value: string }) => <StatusPill status={p.value} /> },
    { field: "attempts", headerName: "Deliveries", maxWidth: 110 },
    { field: "error", headerName: "Note", minWidth: 200 },
    { field: "mode", headerName: "Mode", cellRenderer: (p: { value: string }) => <ModeBadge mode={p.value} />, maxWidth: 150 },
    {
      headerName: "", maxWidth: 110, sortable: false, filter: false,
      cellRenderer: (p: { data?: WebhookEventRow }) =>
        canManage && p.data?.processing_status === "FAILED" ? (
          <button type="button" className="inline-flex items-center gap-1 text-2xs text-primary hover:underline"
            onClick={() => void paypalApi.reprocessWebhook(p.data!.webhook_event_id).then(() => refetch())}>
            <RotateCcw className="h-3 w-3" /> retry
          </button>
        ) : null,
    },
  ], [canManage, refetch]);
  return (
    <div className="space-y-5">
      <PageHeader eyebrow="Finance" title="PayPal webhooks"
        description={`Receiver: POST /api/v1/paypal/webhooks. Signatures are verified with PayPal's verify-webhook-signature API (${status.data?.webhook_configured ? "webhook id configured" : "no webhook id configured - real events are rejected"}); the event id is the replay guard.`}
        actions={status.data && <ModeBadge mode={status.data.mode} />} />
      {error && <ErrorState error={error} onRetry={() => void refetch()} />}
      <Card>
        <CardContent className="p-3">
          <DataGrid rows={data} columns={columns} loading={isLoading} getRowId={(r) => r.webhook_event_id}
            emptyMessage="No webhooks received yet." />
        </CardContent>
      </Card>
    </div>
  );
}
