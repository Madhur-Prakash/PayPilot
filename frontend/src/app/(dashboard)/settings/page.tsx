"use client";

import { useQuery } from "@tanstack/react-query";
import {
  Bot,
  CheckCircle2,
  Database,
  Fingerprint,
  Mic,
  ScrollText,
  Store,
  XCircle,
} from "lucide-react";
import * as React from "react";

import { ErrorState, LoadingRows } from "@/components/common/states";
import {
  Badge,
  Card,
  CardContent,
  CardHeader,
  CardTitle,
  Separator,
  Tabs,
  TabsContent,
  TabsList,
  TabsTrigger,
} from "@/components/ui/primitives";
import { useRoles, useSettings } from "@/hooks/use-api";
import { adminApi } from "@/lib/api/endpoints";
import { cn } from "@/lib/utils";
import { MembersPanel } from "@/components/settings/members-panel";
import { RoleBuilder } from "@/components/settings/role-builder";
import { useAuthStore } from "@/stores/auth";

export default function SettingsPage() {
  const settings = useSettings();
  const roles = useRoles();
  const health = useQuery({ queryKey: ["health"], queryFn: adminApi.health });
  const user = useAuthStore((s) => s.user);

  return (
    <div className="space-y-6">
      <div>
        <h2 className="text-xl font-semibold tracking-tight">Settings</h2>
        <p className="text-sm text-muted-foreground">
          Merchant, integrations and the permission model the backend enforces
        </p>
      </div>

      <Tabs defaultValue="integrations">
        <TabsList>
          <TabsTrigger value="integrations">Integrations</TabsTrigger>
          <TabsTrigger value="members">Members</TabsTrigger>
          <TabsTrigger value="rbac">Roles and permissions</TabsTrigger>
          <TabsTrigger value="account">Account</TabsTrigger>
        </TabsList>

        {/* Integrations */}
        <TabsContent value="integrations" className="space-y-4">
          {settings.isLoading && <LoadingRows rows={3} />}
          {settings.error && (
            <ErrorState error={settings.error} onRetry={() => void settings.refetch()} />
          )}

          {settings.data && (
            <>
              <Card>
                <CardHeader>
                  <CardTitle className="flex items-center gap-2 text-base">
                    <Store className="h-4 w-4" />
                    Merchant
                  </CardTitle>
                </CardHeader>
                <CardContent className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
                  <Field label="Name" value={settings.data.merchant.name} />
                  <Field label="Category" value={settings.data.merchant.category} />
                  <Field label="City" value={settings.data.merchant.city || "--"} />
                  <Field
                    label="Data source"
                    value={dataSourceLabel(settings.data.merchant.data_source)}
                  />
                </CardContent>
              </Card>

              <div className="grid gap-4 md:grid-cols-2">
                <IntegrationCard
                  icon={Bot}
                  title="LLM (Groq)"
                  configured={settings.data.integrations.llm.configured}
                  detail={
                    settings.data.integrations.llm.model ??
                    "Set GROQ_API_KEY and GROQ_MODEL to enable"
                  }
                  note={settings.data.integrations.llm.note}
                />
                <IntegrationCard
                  icon={ScrollText}
                  title="Langfuse"
                  configured={settings.data.integrations.langfuse.configured}
                  detail={settings.data.integrations.langfuse.host}
                  note="Agent traces, LLM generations, tool calls and latency."
                />
                <IntegrationCard
                  icon={Mic}
                  title="Vapi voice"
                  configured={settings.data.integrations.vapi.configured}
                  detail={
                    settings.data.integrations.vapi.configured
                      ? "Assistant configured"
                      : "Set VAPI_PUBLIC_KEY and VAPI_ASSISTANT_ID"
                  }
                  note="Voice calls the same backend agents as the dashboard."
                />
                <IntegrationCard
                  icon={Database}
                  title="Embeddings"
                  configured
                  detail={`${settings.data.integrations.embeddings.provider} · ${settings.data.integrations.embeddings.dimensions} dims`}
                  note={
                    settings.data.integrations.embeddings.provider === "hash"
                      ? "Deterministic local embeddings - no network calls. Set EMBEDDING_PROVIDER=fastembed for true semantic search."
                      : "Local ONNX sentence-transformer."
                  }
                />
              </div>

              {health.data && (
                <Card>
                  <CardHeader>
                    <CardTitle className="text-base">System health</CardTitle>
                  </CardHeader>
                  <CardContent className="space-y-2">
                    <div className="flex flex-wrap gap-2">
                      {Object.entries(health.data.checks).map(([key, value]) => (
                        <Badge
                          key={key}
                          variant={
                            value === "ok" || value === "configured"
                              ? "success"
                              : value === "unreachable"
                                ? "destructive"
                                : "muted"
                          }
                        >
                          {key}: {value}
                        </Badge>
                      ))}
                    </div>
                    <p className="text-2xs leading-relaxed text-muted-foreground">
                      {health.data.note}
                    </p>
                  </CardContent>
                </Card>
              )}
            </>
          )}
        </TabsContent>

        {/* RBAC */}
        {/* Members */}
        <TabsContent value="members" className="space-y-4">
          <MembersPanel />
        </TabsContent>

        <TabsContent value="rbac" className="space-y-4">
          <Card>
            <CardContent className="flex items-start gap-3 p-4">
              <Fingerprint className="mt-0.5 h-4 w-4 shrink-0 text-primary" />
              <p className="text-sm leading-relaxed text-muted-foreground">
                These permissions are enforced server-side on every request. The interface hides
                controls a role cannot use, but hiding is a convenience — the backend re-derives the
                permission set from the stored role and rejects anything else.
              </p>
            </CardContent>
          </Card>

          {roles.isLoading && <LoadingRows rows={4} />}
          {roles.data?.map((role) => (
            <Card key={role.name} className={cn(user?.role === role.name && "border-primary/40")}>
              <CardHeader className="pb-3">
                <div className="flex items-center gap-2">
                  <CardTitle className="text-base">{role.name}</CardTitle>
                  {user?.role === role.name && <Badge>Your role</Badge>}
                  <span className="ml-auto text-2xs text-muted-foreground">
                    {role.permissions.length} permissions
                  </span>
                </div>
                <p className="text-sm text-muted-foreground">{role.description}</p>
              </CardHeader>
              <CardContent className="flex flex-wrap gap-1.5">
                {role.permissions.map((permission) => (
                  <Badge key={permission} variant="secondary" className="font-mono normal-case">
                    {permission}
                  </Badge>
                ))}
              </CardContent>
            </Card>
          ))}

          <Separator className="my-2" />
          {roles.data && <RoleBuilder roles={roles.data} />}
        </TabsContent>

        {/* Account */}
        <TabsContent value="account" className="space-y-4">
          <Card>
            <CardHeader>
              <CardTitle className="text-base">Your account</CardTitle>
            </CardHeader>
            <CardContent className="grid gap-3 sm:grid-cols-2">
              <Field label="Name" value={user?.user.full_name ?? "--"} />
              <Field label="Email" value={user?.user.email ?? "--"} />
              <Field label="Role" value={user?.role ?? "--"} />
              <Field label="Status" value={user?.user.status ?? "--"} />
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle className="text-base">Your effective permissions</CardTitle>
              <p className="text-sm text-muted-foreground">
                Derived from your role on this merchant
              </p>
            </CardHeader>
            <CardContent className="flex flex-wrap gap-1.5">
              {user?.permissions.map((permission) => (
                <Badge key={permission} variant="secondary" className="font-mono normal-case">
                  {permission}
                </Badge>
              ))}
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle className="text-base">Workspaces</CardTitle>
            </CardHeader>
            <CardContent className="space-y-2">
              {user?.memberships.map((membership) => (
                <div
                  key={membership.merchant.id}
                  className="flex items-center justify-between rounded-lg border border-border px-3 py-2"
                >
                  <div>
                    <p className="text-sm font-medium">{membership.merchant.name}</p>
                    <p className="text-2xs text-muted-foreground">
                      {membership.merchant.category} · {membership.merchant.data_source}
                    </p>
                  </div>
                  <Badge variant="outline">{membership.role}</Badge>
                </div>
              ))}
            </CardContent>
          </Card>
        </TabsContent>
      </Tabs>
    </div>
  );
}

/** The backend's internal provenance token, shown as a plain-language label. */
function dataSourceLabel(source: string): string {
  const labels: Record<string, string> = {
    SEEDED: "Baseline",
    LIVE: "Live",
    SIMULATED: "Preview",
    PUBLIC_WEB: "Web",
  };
  return labels[source] ?? source;
}

function Field({ label, value, badge }: { label: string; value: string; badge?: string }) {
  return (
    <div>
      <p className="text-2xs font-medium uppercase tracking-wide text-muted-foreground">{label}</p>
      <p className="mt-0.5 flex items-center gap-2 text-sm font-medium capitalize">
        {value}
        {badge && <Badge variant="warning">{badge}</Badge>}
      </p>
    </div>
  );
}

function IntegrationCard({
  icon: Icon,
  title,
  configured,
  detail,
  note,
}: {
  icon: typeof Bot;
  title: string;
  configured: boolean;
  detail: string;
  note: string;
}) {
  return (
    <Card>
      <CardContent className="space-y-2 p-5">
        <div className="flex items-center justify-between gap-2">
          <p className="flex items-center gap-2 text-sm font-medium">
            <Icon className="h-4 w-4 text-muted-foreground" />
            {title}
          </p>
          {configured ? (
            <Badge variant="success" className="gap-1">
              <CheckCircle2 className="h-3 w-3" />
              Configured
            </Badge>
          ) : (
            <Badge variant="muted" className="gap-1">
              <XCircle className="h-3 w-3" />
              Not configured
            </Badge>
          )}
        </div>
        <p className="font-mono text-2xs text-muted-foreground">{detail}</p>
        <Separator />
        <p className="text-2xs leading-relaxed text-muted-foreground">{note}</p>
      </CardContent>
    </Card>
  );
}
