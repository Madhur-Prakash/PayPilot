"use client";

/**
 * Integrations - the honest status page.
 *
 * Every tool PayPilot uses, whether it is running against the real service or a labelled
 * stand-in, and where in the product it lives. Nothing here is hand-written marketing: the
 * rows come from GET /integrations/status, the same function the backend uses to decide what
 * it may claim, and the system checks come from GET /health.
 */

import { useQuery } from "@tanstack/react-query";
import { CheckCircle2, CircleDashed, FlaskConical, ShieldCheck } from "lucide-react";
import * as React from "react";

import { ErrorState, LoadingCard } from "@/components/common/states";
import { PageHeader } from "@/components/supply/shared";
import { Badge, Card, CardContent } from "@/components/ui/primitives";
import { useIntegrationStatus } from "@/hooks/use-integrations";
import { adminApi } from "@/lib/api/endpoints";
import { cn } from "@/lib/utils";
import type { IntegrationMode, IntegrationRow } from "@/types/integrations";

type Tone = "real" | "stand-in" | "off";

const MODE: Record<string, { label: string; tone: Tone }> = {
  LIVE: { label: "Live", tone: "real" },
  SANDBOX: { label: "PayPal sandbox", tone: "real" },
  DEPLOYED: { label: "Deployed", tone: "real" },
  SDK: { label: "Official SDK", tone: "real" },
  SIMULATED: { label: "Simulated", tone: "stand-in" },
  BLUEPRINT: { label: "Blueprint only", tone: "stand-in" },
  COLLECTION: { label: "Collection", tone: "stand-in" },
  SPEC_EXPORT: { label: "Spec export", tone: "stand-in" },
  DISABLED: { label: "Off", tone: "off" },
  NOT_USED: { label: "Not used", tone: "off" },
};

const TONE_CLASS: Record<Tone, string> = {
  real: "border-success/40 bg-success/10 text-success",
  "stand-in": "border-warning/40 bg-warning/10 text-warning",
  off: "border-border bg-muted text-muted-foreground",
};

function ModeBadge({ mode }: { mode: IntegrationMode | string }) {
  const m = MODE[mode] ?? { label: mode, tone: "off" as Tone };
  return <Badge variant="outline" className={cn("whitespace-nowrap", TONE_CLASS[m.tone])}>{m.label}</Badge>;
}

function Summary({ rows }: { rows: IntegrationRow[] }) {
  const count = (t: Tone) => rows.filter((r) => (MODE[r.mode]?.tone ?? "off") === t).length;
  const items = [
    { icon: CheckCircle2, label: "Running against the real service", value: count("real"), tone: "text-success" },
    { icon: FlaskConical, label: "Labelled stand-in or prepared", value: count("stand-in"), tone: "text-warning" },
    { icon: CircleDashed, label: "Off or not used", value: count("off"), tone: "text-muted-foreground" },
  ];
  return (
    <div className="grid gap-3 sm:grid-cols-3">
      {items.map(({ icon: Icon, label, value, tone }) => (
        <Card key={label}>
          <CardContent className="flex items-center gap-3 p-4">
            <Icon className={cn("h-5 w-5", tone)} />
            <div>
              <div className="text-2xl font-semibold leading-none">{value}</div>
              <div className="mt-1 text-xs text-muted-foreground">{label}</div>
            </div>
          </CardContent>
        </Card>
      ))}
    </div>
  );
}

function Section({ title, rows }: { title: string; rows: IntegrationRow[] }) {
  if (!rows.length) return null;
  return (
    <section className="space-y-3">
      <h2 className="text-sm font-semibold uppercase tracking-wide text-muted-foreground">{title}</h2>
      <div className="grid gap-3 md:grid-cols-2">
        {rows.map((r) => (
          <Card key={r.key}>
            <CardContent className="space-y-2 p-4">
              <div className="flex items-start justify-between gap-3">
                <h3 className="font-semibold">{r.name}</h3>
                <ModeBadge mode={r.mode} />
              </div>
              <p className="text-sm text-muted-foreground">{r.used_for}</p>
              <p className="font-mono text-xs text-muted-foreground">{r.where}</p>
            </CardContent>
          </Card>
        ))}
      </div>
    </section>
  );
}

export default function IntegrationsPage() {
  const status = useIntegrationStatus();
  const health = useQuery({ queryKey: ["health"], queryFn: adminApi.health });
  const rows = status.data?.integrations ?? [];

  return (
    <div className="space-y-6">
      <PageHeader
        eyebrow="Governance"
        title="Integrations"
        description="Every tool PayPilot uses, whether it is running against the real service or a labelled stand-in, and where in the product it lives. Nothing is claimed that the code does not do."
      />

      {status.isLoading && <LoadingCard lines={4} />}
      {status.error && <ErrorState error={status.error} onRetry={() => void status.refetch()} />}

      {status.data && (
        <>
          <Summary rows={rows} />
          <Section title="PayPal" rows={rows.filter((r) => r.category === "core")} />
          <Section title="Sponsor tools" rows={rows.filter((r) => r.category === "sponsor")} />
        </>
      )}

      {health.data && (
        <section className="space-y-3">
          <h2 className="flex items-center gap-2 text-sm font-semibold uppercase tracking-wide text-muted-foreground">
            <ShieldCheck className="h-4 w-4" /> System checks
          </h2>
          <Card>
            <CardContent className="grid gap-x-8 gap-y-2 p-4 sm:grid-cols-2 lg:grid-cols-3">
              {Object.entries(health.data.checks).map(([key, value]) => (
                <div key={key} className="flex items-center justify-between gap-3 text-sm">
                  <span className="capitalize text-muted-foreground">{key.replace(/_/g, " ")}</span>
                  <span className="font-medium">{String(value)}</span>
                </div>
              ))}
            </CardContent>
          </Card>
          {health.data.note && <p className="text-xs text-muted-foreground">{health.data.note}</p>}
        </section>
      )}
    </div>
  );
}
