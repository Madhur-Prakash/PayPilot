"use client";

/**
 * Loading, empty, error and permission states.
 *
 * Every page uses these, so no screen can render a blank rectangle while it
 * waits, and every failure tells the user what happened and what to do next.
 */

import { AlertTriangle, Inbox, Lock, RefreshCw, WifiOff } from "lucide-react";
import type { LucideIcon } from "lucide-react";
import * as React from "react";

import { Button } from "@/components/ui/button";
import { Card, CardContent, Skeleton } from "@/components/ui/primitives";
import { ApiError } from "@/lib/api/client";
import { cn } from "@/lib/utils";

// --------------------------------------------------------------------------- //
// Loading
// --------------------------------------------------------------------------- //
export function LoadingCard({ className, lines = 3 }: { className?: string; lines?: number }) {
  return (
    <Card className={className}>
      <CardContent className="space-y-3 p-5">
        <Skeleton className="h-4 w-1/3" />
        {Array.from({ length: lines }).map((_, i) => (
          <Skeleton key={i} className={cn("h-3", i === lines - 1 ? "w-2/3" : "w-full")} />
        ))}
      </CardContent>
    </Card>
  );
}

export function LoadingKpis({ count = 4 }: { count?: number }) {
  return (
    <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
      {Array.from({ length: count }).map((_, i) => (
        <Card key={i}>
          <CardContent className="space-y-3 p-5">
            <Skeleton className="h-3 w-24" />
            <Skeleton className="h-8 w-32" />
            <Skeleton className="h-3 w-20" />
          </CardContent>
        </Card>
      ))}
    </div>
  );
}

export function LoadingChart({ height = 280 }: { height?: number }) {
  return (
    <div className="space-y-3">
      <Skeleton className="h-4 w-40" />
      <Skeleton className="w-full rounded-lg" style={{ height }} />
    </div>
  );
}

export function LoadingRows({ rows = 5 }: { rows?: number }) {
  return (
    <div className="space-y-2">
      {Array.from({ length: rows }).map((_, i) => (
        <Skeleton key={i} className="h-14 w-full rounded-lg" />
      ))}
    </div>
  );
}

// --------------------------------------------------------------------------- //
// Shell
// --------------------------------------------------------------------------- //
function StateShell({
  icon: Icon,
  tone = "muted",
  title,
  description,
  children,
  className,
}: {
  icon: LucideIcon;
  tone?: "muted" | "destructive" | "warning";
  title: string;
  description?: React.ReactNode;
  children?: React.ReactNode;
  className?: string;
}) {
  const toneClasses = {
    muted: "bg-muted text-muted-foreground",
    destructive: "bg-destructive/10 text-destructive",
    warning: "bg-warning/12 text-warning",
  }[tone];

  return (
    <div
      className={cn(
        "flex flex-col items-center justify-center gap-3 rounded-xl border border-dashed border-border px-6 py-12 text-center",
        className,
      )}
    >
      <div className={cn("flex h-11 w-11 items-center justify-center rounded-full", toneClasses)}>
        <Icon className="h-5 w-5" />
      </div>
      <div className="space-y-1">
        <p className="text-sm font-semibold">{title}</p>
        {description && (
          <p className="mx-auto max-w-md text-sm text-muted-foreground">{description}</p>
        )}
      </div>
      {children}
    </div>
  );
}

// --------------------------------------------------------------------------- //
// Empty
// --------------------------------------------------------------------------- //
export function EmptyState({
  title = "Nothing here yet",
  description,
  icon = Inbox,
  action,
  className,
}: {
  title?: string;
  description?: React.ReactNode;
  icon?: LucideIcon;
  action?: React.ReactNode;
  className?: string;
}) {
  return (
    <StateShell icon={icon} title={title} description={description} className={className}>
      {action}
    </StateShell>
  );
}

// --------------------------------------------------------------------------- //
// Error
// --------------------------------------------------------------------------- //
export function ErrorState({
  error,
  onRetry,
  className,
}: {
  error: unknown;
  onRetry?: () => void;
  className?: string;
}) {
  const apiError = error instanceof ApiError ? error : null;

  // A 403 is not a failure - it is the system working. Say so plainly.
  if (apiError?.isForbidden) {
    return (
      <StateShell
        icon={Lock}
        tone="warning"
        title="You do not have access to this"
        description={
          <>
            {apiError.message}
            {typeof apiError.details?.role === "string" && (
              <>
                {" "}
                Your role is <span className="font-medium">{String(apiError.details.role)}</span>.
              </>
            )}
          </>
        }
        className={className}
      />
    );
  }

  const isNetwork = apiError?.status === 0;
  return (
    <StateShell
      icon={isNetwork ? WifiOff : AlertTriangle}
      tone="destructive"
      title={isNetwork ? "Cannot reach the API" : "Something went wrong"}
      description={
        apiError?.message ??
        (error instanceof Error ? error.message : "An unexpected error occurred.")
      }
      className={className}
    >
      <div className="flex flex-col items-center gap-2">
        {onRetry && (
          <Button variant="outline" size="sm" onClick={onRetry}>
            <RefreshCw className="h-4 w-4" />
            Try again
          </Button>
        )}
        {apiError?.requestId && (
          <p className="font-mono text-2xs text-muted-foreground">
            request {apiError.requestId.slice(0, 12)}
          </p>
        )}
      </div>
    </StateShell>
  );
}

// --------------------------------------------------------------------------- //
// Async boundary
// --------------------------------------------------------------------------- //
/**
 * One place that decides loading vs error vs empty vs content, so every screen
 * behaves the same way without repeating the ternaries.
 */
export function QueryBoundary<T>({
  isLoading,
  error,
  data,
  onRetry,
  loading,
  empty,
  isEmpty,
  children,
}: {
  isLoading: boolean;
  error: unknown;
  data: T | undefined;
  onRetry?: () => void;
  loading?: React.ReactNode;
  empty?: React.ReactNode;
  isEmpty?: (data: T) => boolean;
  children: (data: T) => React.ReactNode;
}) {
  if (isLoading) return <>{loading ?? <LoadingRows />}</>;
  if (error) return <ErrorState error={error} onRetry={onRetry} />;
  if (data === undefined) return <>{empty ?? <EmptyState />}</>;
  if (isEmpty?.(data)) return <>{empty ?? <EmptyState />}</>;
  return <>{children(data)}</>;
}
