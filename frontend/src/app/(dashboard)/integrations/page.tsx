"use client";

/**
 * Integrations hub: what PayPilot connects to, whether each path is live or a labelled
 * fallback, and a working console for the read-only tools (market reference, supplier
 * portal, Zapier, PayPal's Agent Toolkit over MCP).
 */

import {
  Ban, Bell, Boxes, Globe, Link2, MonitorPlay, ShieldCheck, Store, Wrench,
} from "lucide-react";
import Link from "next/link";
import * as React from "react";

import { ErrorState, LoadingCard } from "@/components/common/states";
import { MetricTile, PageHeader } from "@/components/supply/shared";
import { Button } from "@/components/ui/button";
import { Badge, Card, CardContent, CardDescription, CardHeader, CardTitle, Input } from "@/components/ui/primitives";
import {
  useBenchmark, useClosePortal, useIntegrationStatus, useMcpCall, useMcpTools, useOpenPortal, useZapierTest,
} from "@/hooks/use-integrations";
import { cn, formatMoney, formatRelativeTime, toNumber } from "@/lib/utils";
import { useAuthStore } from "@/stores/auth";
import type { IntegrationMode, IntegrationRow, PortalSession } from "@/types/integrations";

const MODE_STYLE: Record<IntegrationMode, { label: string; tone: string }> = {
  LIVE: { label: "Live", tone: "bg-success/12 text-success" },
  SANDBOX: { label: "PayPal sandbox", tone: "bg-primary/10 text-primary" },
  SIMULATED: { label: "Simulated fallback", tone: "bg-warning/14 text-warning" },
  DISABLED: { label: "Disabled", tone: "bg-muted text-muted-foreground" },
  NOT_USED: { label: "Not used", tone: "bg-muted text-muted-foreground" },
  BLUEPRINT: { label: "Blueprint ready", tone: "bg-primary/10 text-primary" },
  COLLECTION: { label: "Collection", tone: "bg-primary/10 text-primary" },
  SPEC_EXPORT: { label: "Spec export", tone: "bg-primary/10 text-primary" },
};

function ModeChip({ mode }: { mode: IntegrationMode }) {
  const s = MODE_STYLE[mode] ?? { label: mode, tone: "bg-muted text-muted-foreground" };
  return <span className={cn("inline-flex items-center rounded-md px-1.5 py-0.5 text-2xs font-semibold", s.tone)}>{s.label}</span>;
}

function IntegrationCard({ row }: { row: IntegrationRow }) {
  const internal = row.where.startsWith("/");
  return (
    <Card className={cn(row.mode === "NOT_USED" && "opacity-70")}>
      <CardContent className="space-y-2 p-4">
        <div className="flex items-start justify-between gap-2">
          <p className="text-sm font-semibold">{row.name}</p>
          <ModeChip mode={row.mode} />
        </div>
        <p className="text-xs text-muted-foreground">{row.used_for}</p>
        {row.mode !== "NOT_USED" && (internal
          ? <Link href={row.where} className="text-xs font-medium text-primary hover:underline">Open →</Link>
          : <span className="font-mono text-2xs text-muted-foreground">{row.where}</span>)}
      </CardContent>
    </Card>
  );
}

// --------------------------------------------------------------------------- //
// Channel3 - market reference
// --------------------------------------------------------------------------- //
function MarketReference() {
  const [query, setQuery] = React.useState("premium coffee beans");
  const [price, setPrice] = React.useState("18");
  const benchmark = useBenchmark();
  const data = benchmark.data;
  return (
    <Card>
      <CardHeader className="pb-2">
        <CardTitle className="flex items-center gap-2 text-base"><Store className="h-4 w-4 text-primary" /> Market price reference <Badge variant="outline" className="text-2xs">Channel3</Badge></CardTitle>
        <CardDescription>What a product retails for elsewhere - context for the person approving a purchase. It never changes a limit, budget or offer.</CardDescription>
      </CardHeader>
      <CardContent className="space-y-3">
        <form className="flex flex-wrap gap-2" onSubmit={(e) => { e.preventDefault(); benchmark.mutate({ query, expected_price: toNumber(price) ?? undefined }); }}>
          <Input value={query} onChange={(e) => setQuery(e.target.value)} className="min-w-56 flex-1" aria-label="Product" />
          <Input value={price} onChange={(e) => setPrice(e.target.value)} className="w-28" inputMode="decimal" aria-label="Planned selling price" placeholder="Our price" />
          <Button type="submit" loading={benchmark.isPending} disabled={query.trim().length < 2}>Look up</Button>
        </form>
        {data && (
          <div className="space-y-3">
            <div className="flex flex-wrap items-center gap-3 text-xs">
              <ModeChip mode={data.mode} />
              <span className="text-muted-foreground">{data.note}</span>
            </div>
            {data.stats && (
              <div className="grid gap-3 sm:grid-cols-4">
                <MetricTile icon={Boxes} label="Lowest" value={formatMoney(data.stats.min)} />
                <MetricTile icon={Boxes} tone="primary" label="Median" value={formatMoney(data.stats.median)} />
                <MetricTile icon={Boxes} label="Highest" value={formatMoney(data.stats.max)} />
                {data.position && (
                  <MetricTile icon={Boxes} tone={Math.abs(Number(data.position.difference_pct)) <= 10 ? "success" : "warning"}
                    label={`Our ${formatMoney(data.position.expected_selling_price)}`} value={`${data.position.difference_pct}%`} hint={data.position.verdict} />
                )}
              </div>
            )}
            <ul className="divide-y rounded-lg border text-sm">
              {data.offers.map((o, i) => (
                <li key={i} className="flex items-center justify-between gap-3 px-3 py-2">
                  <span className="min-w-0 truncate">{o.title}<span className="ml-2 text-xs text-muted-foreground">{o.merchant}</span></span>
                  <span className="font-medium tabular-nums">{formatMoney(o.price)}</span>
                </li>
              ))}
            </ul>
            <p className="text-2xs text-muted-foreground">{data.disclaimer}</p>
          </div>
        )}
      </CardContent>
    </Card>
  );
}

// --------------------------------------------------------------------------- //
// Kernel - supplier portal
// --------------------------------------------------------------------------- //
function SupplierPortal() {
  const [url, setUrl] = React.useState("https://www.example.com/");
  const [session, setSession] = React.useState<PortalSession | null>(null);
  const open = useOpenPortal();
  const close = useClosePortal();
  const canOpen = useAuthStore((s) => s.can("procurement:negotiate"));
  // Only an https link is ever rendered as a link, whatever the API returned.
  const safeLive = session?.live_view_url.startsWith("https://") ? session.live_view_url : "";
  return (
    <Card>
      <CardHeader className="pb-2">
        <CardTitle className="flex items-center gap-2 text-base"><Globe className="h-4 w-4 text-primary" /> Supplier portal check <Badge variant="outline" className="text-2xs">Kernel</Badge></CardTitle>
        <CardDescription>Open a supplier&apos;s public catalogue page in a cloud browser and watch it live to confirm the product and price exist. Observe-only: it never logs in, fills a form or pays.</CardDescription>
      </CardHeader>
      <CardContent className="space-y-3">
        <form className="flex flex-wrap gap-2" onSubmit={(e) => { e.preventDefault(); open.mutate({ url }, { onSuccess: setSession }); }}>
          <Input value={url} onChange={(e) => setUrl(e.target.value)} className="min-w-64 flex-1" aria-label="Supplier page URL" />
          <Button type="submit" loading={open.isPending} disabled={!canOpen || url.trim().length < 10} className="gap-1.5">
            <MonitorPlay className="h-3.5 w-3.5" /> Open browser
          </Button>
        </form>
        {!canOpen && <p className="text-xs text-muted-foreground">Your role can view this but not open sessions (needs procurement:negotiate).</p>}
        {session && (
          <div className="space-y-2 rounded-lg border p-3 text-sm">
            <div className="flex flex-wrap items-center gap-2"><ModeChip mode={session.mode} /><span className="font-mono text-2xs">{session.session_id}</span></div>
            <p className="text-xs text-muted-foreground">{session.note}</p>
            <div className="flex flex-wrap gap-2">
              {safeLive && (
                <Button asChild size="sm"><a href={safeLive} target="_blank" rel="noopener noreferrer">Watch live ↗</a></Button>
              )}
              <Button size="sm" variant="outline" loading={close.isPending}
                onClick={() => close.mutate(session.session_id, { onSuccess: () => setSession(null) })}>Close session</Button>
              <span className="self-center text-2xs text-muted-foreground">expires automatically after {session.timeout_seconds}s</span>
            </div>
          </div>
        )}
      </CardContent>
    </Card>
  );
}

// --------------------------------------------------------------------------- //
// PayPal Agent Toolkit over MCP
// --------------------------------------------------------------------------- //
function PayPalMcp() {
  const tools = useMcpTools();
  const call = useMcpCall();
  const [last, setLast] = React.useState<{ tool: string; mode: string; body: string } | null>(null);
  const run = (tool: string) =>
    call.mutate({ tool }, { onSuccess: (r) => setLast({ tool, mode: r.mode, body: JSON.stringify(r.data, null, 2) }) });
  return (
    <Card>
      <CardHeader className="pb-2">
        <CardTitle className="flex items-center gap-2 text-base"><ShieldCheck className="h-4 w-4 text-primary" /> PayPal Agent Toolkit (MCP) <Badge variant="outline" className="text-2xs">read-only</Badge></CardTitle>
        <CardDescription>PayPal&apos;s own agent tools, reached through PayPilot&apos;s tool registry. Reads are allowed; anything that creates, pays, captures, refunds or sends is blocked before a request leaves the server.</CardDescription>
      </CardHeader>
      <CardContent className="space-y-3">
        {tools.isLoading && <LoadingCard lines={3} />}
        {tools.error && <ErrorState error={tools.error} onRetry={() => void tools.refetch()} />}
        {tools.data && (
          <>
            <div className="flex items-center gap-2 text-xs text-muted-foreground">
              <ModeChip mode={tools.data.mode as IntegrationMode} />
              {tools.data.endpoint && <span className="font-mono text-2xs">{tools.data.endpoint}</span>}
            </div>
            <div className="flex flex-wrap gap-1.5">
              {tools.data.tools.map((t) => t.read_only ? (
                <Button key={t.name} size="sm" variant="outline" className="gap-1.5 font-mono text-2xs" title={t.description}
                  loading={call.isPending && call.variables?.tool === t.name} onClick={() => run(t.name)}>
                  <Wrench className="h-3 w-3" /> {t.name}
                </Button>
              ) : (
                <span key={t.name} title="Blocked: not a read tool"
                  className="inline-flex items-center gap-1 rounded-md border border-dashed px-2 py-1 font-mono text-2xs text-muted-foreground line-through">
                  <Ban className="h-3 w-3" /> {t.name}
                </span>
              ))}
            </div>
            <p className="text-2xs text-muted-foreground">{tools.data.policy}</p>
          </>
        )}
        {last && (
          <div className="space-y-1">
            <p className="text-xs font-medium">{last.tool} <span className="text-muted-foreground">({last.mode.toLowerCase()})</span></p>
            <pre className="max-h-64 overflow-auto rounded-lg border bg-muted/40 p-3 text-2xs">{last.body}</pre>
          </div>
        )}
      </CardContent>
    </Card>
  );
}

// --------------------------------------------------------------------------- //
// Page
// --------------------------------------------------------------------------- //
export default function IntegrationsPage() {
  const status = useIntegrationStatus();
  const zapierTest = useZapierTest();
  const canTest = useAuthStore((s) => s.can("settings:manage"));
  const rows = status.data?.integrations ?? [];
  const core = rows.filter((r) => r.category === "core");
  const sponsors = rows.filter((r) => r.category === "sponsor");
  const live = rows.filter((r) => r.mode === "LIVE" || r.mode === "SANDBOX").length;
  const fallback = rows.filter((r) => r.mode === "SIMULATED").length;
  const z = status.data?.zapier;

  return (
    <div className="space-y-5">
      <PageHeader eyebrow="Governance" title="Integrations"
        description="Everything PayPilot connects to, and what each connection is really doing. Anything running on a fallback says so; anything not used is listed as not used." />

      {status.error && <ErrorState error={status.error} onRetry={() => void status.refetch()} />}
      {status.isLoading && <LoadingCard lines={6} />}

      {status.data && (
        <>
          <div className="grid gap-3 sm:grid-cols-3">
            <MetricTile icon={Link2} tone="success" label="Running against the real service" value={live} />
            <MetricTile icon={Link2} tone="warning" label="On a labelled fallback" value={fallback} hint="Add the key in .env to go live" />
            <MetricTile icon={Boxes} label="Elasticsearch" value={status.data.elastic.configured ? (status.data.elastic.reachable ? "Reachable" : "Unreachable") : "Not configured"}
              hint={status.data.elastic.version ? `v${status.data.elastic.version}` : "search uses a keyword fallback"} />
          </div>

          <section className="space-y-2">
            <h3 className="text-sm font-semibold">PayPal</h3>
            <div className="grid gap-3 md:grid-cols-2">{core.map((r) => <IntegrationCard key={r.key} row={r} />)}</div>
          </section>
          <section className="space-y-2">
            <h3 className="text-sm font-semibold">Sponsor tools</h3>
            <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-3">{sponsors.map((r) => <IntegrationCard key={r.key} row={r} />)}</div>
          </section>
        </>
      )}

      <div className="grid gap-5 xl:grid-cols-2">
        <MarketReference />
        <SupplierPortal />
      </div>
      <PayPalMcp />

      {z && (
        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="flex items-center gap-2 text-base"><Bell className="h-4 w-4 text-primary" /> Zapier notifications <Badge variant="outline" className="text-2xs">outbound only</Badge></CardTitle>
            <CardDescription>Signed business events go to your Zapier Catch Hook. Zapier never approves, pays or changes a limit.</CardDescription>
          </CardHeader>
          <CardContent className="space-y-3 text-sm">
            <div className="flex flex-wrap items-center gap-4">
              <ModeChip mode={z.configured ? "LIVE" : "SIMULATED"} />
              <span>{z.delivered} delivered</span><span>{z.pending} pending</span>
              <span className={z.failed ? "text-destructive" : ""}>{z.failed} failed</span>
              {z.last_delivered_at && <span className="text-muted-foreground">last {formatRelativeTime(z.last_delivered_at)}</span>}
              <Button size="sm" variant="outline" className="ml-auto" disabled={!canTest} loading={zapierTest.isPending} onClick={() => zapierTest.mutate()}>
                Send test event
              </Button>
            </div>
            {!z.configured && <p className="text-xs text-muted-foreground">Set ZAPIER_WEBHOOK_URL (Webhooks by Zapier → Catch Hook) to start delivery.</p>}
            <p className="text-2xs text-muted-foreground">Events sent: {z.event_types.join(" · ")}</p>
          </CardContent>
        </Card>
      )}
    </div>
  );
}
