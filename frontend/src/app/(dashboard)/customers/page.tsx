"use client";

import { Clock, TrendingDown, UserMinus, UserPlus, Users } from "lucide-react";
import * as React from "react";

import { ErrorState, LoadingKpis, LoadingRows } from "@/components/common/states";
import { RangePicker, useRangeDays } from "@/components/dashboard/range-picker";
import { Stagger, StaggerItem } from "@/components/ui/motion";
import {
  Badge,
  Card,
  CardContent,
  CardHeader,
  CardTitle,
  Progress,
  Separator,
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from "@/components/ui/primitives";
import { useCustomerMetrics } from "@/hooks/use-api";
import { cn, formatCompactCurrency, formatNumber, formatPercent } from "@/lib/utils";

export default function CustomersPage() {
  const [days, setDays] = useRangeDays(30);
  const { data, isLoading, error, refetch } = useCustomerMetrics(days);

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h2 className="text-xl font-semibold tracking-tight">Customers</h2>
          <p className="text-sm text-muted-foreground">
            Retention, repeat behaviour and churn risk
          </p>
        </div>
        <RangePicker days={days} onChange={setDays} />
      </div>

      {isLoading && <LoadingKpis count={4} />}
      {error && <ErrorState error={error} onRetry={() => void refetch()} />}

      {data && (
        <>
          <Stagger className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
            <StaggerItem>
              <MetricTile
                icon={Users}
                label="Active customers"
                value={formatNumber(data.active_customers)}
                sub={`of ${formatNumber(data.total_customers)} known`}
              />
            </StaggerItem>
            <StaggerItem>
              <MetricTile
                icon={UserPlus}
                label="Repeat rate"
                value={formatPercent(data.repeat_rate)}
                sub={`${formatNumber(data.repeat_customers)} returned in period`}
                tooltip="Share of customers active this period who ordered at least twice within it."
              />
            </StaggerItem>
            <StaggerItem>
              <MetricTile
                icon={Clock}
                label="Retention"
                value={formatPercent(data.retention_rate)}
                sub="came back from last period"
                tooltip="Share of last period's customers who ordered again this period."
              />
            </StaggerItem>
            <StaggerItem>
              <MetricTile
                icon={UserMinus}
                label="Churn risk"
                value={formatNumber(data.churn_risk_customers)}
                sub="no order in 30+ days"
                tone="destructive"
              />
            </StaggerItem>
          </Stagger>

          <div className="grid gap-4 lg:grid-cols-2">
            <Card>
              <CardHeader>
                <CardTitle>Segments</CardTitle>
                <p className="text-sm text-muted-foreground">
                  RFM-style classification of the whole base
                </p>
              </CardHeader>
              <CardContent className="space-y-3">
                {data.cohorts.map((cohort) => (
                  <div key={cohort.key} className="space-y-1.5">
                    <div className="flex items-center justify-between text-sm">
                      <span className="font-medium">{cohort.label}</span>
                      <span className="text-muted-foreground tnum">
                        {formatNumber(cohort.customers)} · {formatPercent(cohort.share_pct)}
                      </span>
                    </div>
                    <Progress
                      value={cohort.share_pct}
                      className="h-1.5"
                      indicatorClassName={
                        cohort.key === "CHURNED"
                          ? "bg-destructive"
                          : cohort.key === "AT_RISK"
                            ? "bg-warning"
                            : cohort.key === "LOYAL"
                              ? "bg-success"
                              : "bg-primary"
                      }
                    />
                  </div>
                ))}
              </CardContent>
            </Card>

            <Card>
              <CardHeader>
                <CardTitle>By trading slot</CardTitle>
                <p className="text-sm text-muted-foreground">
                  Where repeat customers are being lost
                </p>
              </CardHeader>
              <CardContent className="space-y-2.5">
                {data.by_daypart.map((slot) => (
                  <div
                    key={slot.daypart}
                    className="rounded-lg border border-border bg-card p-3"
                  >
                    <div className="flex items-center justify-between">
                      <span className="text-sm font-medium">{slot.label.split(" (")[0]}</span>
                      <span className="text-sm tnum">
                        {formatCompactCurrency(slot.revenue)}
                      </span>
                    </div>
                    <div className="mt-1.5 grid grid-cols-3 gap-2 text-2xs">
                      <Cell
                        label="Customers"
                        value={formatNumber(slot.unique_customers)}
                      />
                      <Cell
                        label="Repeat"
                        value={formatNumber(slot.repeat_customers)}
                        delta={slot.repeat_customers_change_pct}
                      />
                      <Cell
                        label="Service"
                        value={
                          slot.avg_service_minutes != null
                            ? `${slot.avg_service_minutes.toFixed(1)}m`
                            : "--"
                        }
                        delta={slot.service_minutes_change_pct}
                        invertDelta
                      />
                    </div>
                  </div>
                ))}
              </CardContent>
            </Card>
          </div>

          {data.retention_curve.length > 0 && (
            <Card>
              <CardHeader>
                <CardTitle>Cohort retention</CardTitle>
                <p className="text-sm text-muted-foreground">
                  Share of each acquisition cohort still ordering, by month
                </p>
              </CardHeader>
              <CardContent>
                <RetentionTable rows={data.retention_curve} />
              </CardContent>
            </Card>
          )}
        </>
      )}
    </div>
  );
}

function MetricTile({
  icon: Icon,
  label,
  value,
  sub,
  tone,
  tooltip,
}: {
  icon: typeof Users;
  label: string;
  value: string;
  sub?: string;
  tone?: "destructive";
  tooltip?: string;
}) {
  const content = (
    <Card>
      <CardContent className="space-y-1.5 p-5">
        <p className="flex items-center gap-1.5 text-xs font-medium uppercase tracking-wide text-muted-foreground">
          <Icon className="h-3.5 w-3.5" />
          {label}
        </p>
        <p
          className={cn(
            "text-2xl font-semibold leading-none tracking-tight tnum",
            tone === "destructive" && "text-destructive",
          )}
        >
          {value}
        </p>
        {sub && <p className="text-2xs text-muted-foreground">{sub}</p>}
      </CardContent>
    </Card>
  );

  if (!tooltip) return content;
  return (
    <Tooltip>
      <TooltipTrigger asChild>
        <div className="cursor-help">{content}</div>
      </TooltipTrigger>
      <TooltipContent>{tooltip}</TooltipContent>
    </Tooltip>
  );
}

function Cell({
  label,
  value,
  delta,
  invertDelta,
}: {
  label: string;
  value: string;
  delta?: number | null;
  invertDelta?: boolean;
}) {
  const bad = delta == null ? false : invertDelta ? delta > 0 : delta < 0;
  return (
    <div>
      <p className="uppercase tracking-wide text-muted-foreground">{label}</p>
      <p className="flex items-center gap-1 font-medium tnum">
        {value}
        {delta != null && Math.abs(delta) >= 1 && (
          <span className={cn("text-2xs", bad ? "text-destructive" : "text-success")}>
            {delta >= 0 ? "+" : ""}
            {delta.toFixed(0)}%
          </span>
        )}
      </p>
    </div>
  );
}

function RetentionTable({
  rows,
}: {
  rows: { cohort_month: string; cohort_size: number; month_index: number; retention_pct: number }[];
}) {
  const cohorts = Array.from(new Set(rows.map((row) => row.cohort_month))).sort();
  const maxIndex = Math.max(...rows.map((row) => row.month_index));
  const lookup = new Map(rows.map((row) => [`${row.cohort_month}:${row.month_index}`, row]));

  return (
    <div className="overflow-x-auto">
      <table className="w-full min-w-[520px] border-separate border-spacing-1 text-center text-2xs">
        <thead>
          <tr>
            <th className="text-left font-medium text-muted-foreground">Cohort</th>
            <th className="font-medium text-muted-foreground">Size</th>
            {Array.from({ length: maxIndex + 1 }).map((_, index) => (
              <th key={index} className="font-medium text-muted-foreground">
                M{index}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {cohorts.map((cohort) => {
            const size = lookup.get(`${cohort}:0`)?.cohort_size ?? 0;
            return (
              <tr key={cohort}>
                <td className="text-left font-medium">{cohort}</td>
                <td className="text-muted-foreground tnum">{formatNumber(size)}</td>
                {Array.from({ length: maxIndex + 1 }).map((_, index) => {
                  const cell = lookup.get(`${cohort}:${index}`);
                  if (!cell) return <td key={index} />;
                  const intensity = Math.min(cell.retention_pct / 100, 1);
                  return (
                    <td
                      key={index}
                      className="rounded tnum"
                      style={{
                        backgroundColor: `hsl(var(--primary) / ${(intensity * 0.7).toFixed(2)})`,
                        color: intensity > 0.55 ? "white" : undefined,
                      }}
                    >
                      {cell.retention_pct.toFixed(0)}
                    </td>
                  );
                })}
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
