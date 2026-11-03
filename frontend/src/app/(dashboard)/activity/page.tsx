"use client";

import { Activity, ShieldAlert, ShieldCheck, User } from "lucide-react";
import * as React from "react";

import { EmptyState, ErrorState, LoadingRows } from "@/components/common/states";
import { Button } from "@/components/ui/button";
import { Stagger, StaggerItem } from "@/components/ui/motion";
import {
  Badge,
  Card,
  CardContent,
  CardHeader,
  CardTitle,
} from "@/components/ui/primitives";
import { useAuditLogs } from "@/hooks/use-api";
import { cn, formatDateTime } from "@/lib/utils";

const FILTERS = [
  { label: "All", value: undefined },
  { label: "Approvals", value: "CAMPAIGN_APPROVED" },
  { label: "Executions", value: "CAMPAIGN_EXECUTED" },
  { label: "Agent runs", value: "AGENT_RUN" },
  { label: "Denials", value: "PERMISSION_DENIED" },
  { label: "Logins", value: "LOGIN" },
];

/** Security-relevant actions get a distinct read so they stand out in the feed. */
const SECURITY_ACTIONS = new Set([
  "PERMISSION_DENIED",
  "MERCHANT_SCOPE_VIOLATION",
  "LOGIN_FAILED",
  "TOKEN_REUSE_DETECTED",
]);

export default function ActivityPage() {
  const [action, setAction] = React.useState<string | undefined>(undefined);
  const { data, isLoading, error, refetch } = useAuditLogs({ action });

  return (
    <div className="space-y-6">
      <div>
        <h2 className="text-xl font-semibold tracking-tight">Audit Log</h2>
        <p className="text-sm text-muted-foreground">
          Every consequential action, with the actor who took it
        </p>
      </div>

      <Card>
        <CardHeader className="pb-3">
          <CardTitle className="flex items-center gap-2 text-base">
            <Activity className="h-4 w-4" />
            Filter
          </CardTitle>
        </CardHeader>
        <CardContent className="flex flex-wrap gap-1.5">
          {FILTERS.map((filter) => (
            <Button
              key={filter.label}
              size="sm"
              variant={action === filter.value ? "default" : "outline"}
              onClick={() => setAction(filter.value)}
            >
              {filter.label}
            </Button>
          ))}
        </CardContent>
      </Card>

      {isLoading && <LoadingRows rows={6} />}
      {error && <ErrorState error={error} onRetry={() => void refetch()} />}

      {data && data.items.length === 0 && (
        <EmptyState icon={Activity} title="No matching entries" />
      )}

      {data && data.items.length > 0 && (
        <Stagger className="space-y-2">
          {data.items.map((entry) => {
            const security = SECURITY_ACTIONS.has(entry.action);
            const failed = entry.status !== "SUCCESS";
            return (
              <StaggerItem key={entry.id}>
                <Card className={cn(security && "border-warning/35 bg-warning/4")}>
                  <CardContent className="flex flex-wrap items-start gap-3 p-4">
                    <div
                      className={cn(
                        "mt-0.5 flex h-7 w-7 shrink-0 items-center justify-center rounded-lg",
                        security
                          ? "bg-warning/15 text-warning"
                          : failed
                            ? "bg-destructive/10 text-destructive"
                            : "bg-primary/10 text-primary",
                      )}
                    >
                      {security ? (
                        <ShieldAlert className="h-3.5 w-3.5" />
                      ) : failed ? (
                        <ShieldAlert className="h-3.5 w-3.5" />
                      ) : (
                        <ShieldCheck className="h-3.5 w-3.5" />
                      )}
                    </div>

                    <div className="min-w-0 flex-1">
                      <div className="flex flex-wrap items-center gap-2">
                        <span className="font-mono text-2xs font-medium">{entry.action}</span>
                        <Badge variant="outline">{entry.actor_type}</Badge>
                        {failed && <Badge variant="destructive">{entry.status}</Badge>}
                      </div>
                      <p className="mt-1 text-sm leading-relaxed">{entry.description}</p>
                      <div className="mt-1 flex flex-wrap items-center gap-2 text-2xs text-muted-foreground">
                        {entry.actor_label && (
                          <span className="flex items-center gap-1">
                            <User className="h-3 w-3" />
                            {entry.actor_label}
                          </span>
                        )}
                        {entry.resource && (
                          <span>
                            {entry.resource}
                            {entry.resource_id ? ` · ${entry.resource_id.slice(0, 8)}` : ""}
                          </span>
                        )}
                      </div>
                    </div>

                    <span className="shrink-0 text-2xs text-muted-foreground">
                      {formatDateTime(entry.created_at)}
                    </span>
                  </CardContent>
                </Card>
              </StaggerItem>
            );
          })}
        </Stagger>
      )}
    </div>
  );
}
