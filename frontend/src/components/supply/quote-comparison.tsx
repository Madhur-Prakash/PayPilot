"use client";

/** Quote comparison: eligible offers ranked by deterministic score, plus the ones policy excluded. */

import type { ColDef } from "ag-grid-community";
import { Crown } from "lucide-react";
import * as React from "react";

import { DataGrid } from "@/components/data/data-grid";
import { formatMoney, toNumber } from "@/lib/utils";
import type { Recommendation } from "@/types/supply";

interface Row {
  rank: number | string;
  supplier: string;
  score: string;
  unit: string;
  landed: string;
  landedUnit: string;
  shipping: string;
  lead: number;
  terms: string;
  reliability: string;
  margin: string;
  budget: string;
  policy: string;
}

export function QuoteComparison({ recommendation }: { recommendation: Partial<Recommendation> | undefined }) {
  const rows = React.useMemo<Row[]>(() => {
    if (!recommendation) return [];
    const ranked: Row[] = (recommendation.ranking ?? []).map((r) => ({
      rank: r.rank,
      supplier: r.supplier_name,
      score: (toNumber(r.score) ?? 0).toFixed(3),
      unit: formatMoney(r.unit_price),
      landed: formatMoney(r.landed_total),
      landedUnit: formatMoney(r.landed_unit_cost),
      shipping: formatMoney(r.shipping),
      lead: r.lead_time_days,
      terms: r.payment_terms.replace("_", " "),
      reliability: `${((toNumber(r.reliability) ?? 0) * 100).toFixed(0)}%`,
      margin: `${r.expected_margin_pct}%`,
      budget: `${r.budget_utilisation_pct}%`,
      policy: "Inside policy",
    }));
    const excluded: Row[] = (recommendation.ineligible ?? []).map((r) => ({
      rank: "—",
      supplier: r.supplier_name,
      score: "—",
      unit: "—",
      landed: formatMoney(r.landed_total),
      landedUnit: "—",
      shipping: "—",
      lead: r.lead_time_days,
      terms: "—",
      reliability: "—",
      margin: "—",
      budget: "—",
      policy: r.violations[0] ?? "Outside policy",
    }));
    return [...ranked, ...excluded];
  }, [recommendation]);

  const columns = React.useMemo<ColDef<Row>[]>(
    () => [
      {
        field: "rank",
        headerName: "#",
        maxWidth: 70,
        cellRenderer: (p: { value: number | string }) =>
          p.value === 1 ? (
            <span className="inline-flex items-center gap-1 font-semibold text-success">
              <Crown className="h-3.5 w-3.5" /> 1
            </span>
          ) : (
            p.value
          ),
      },
      { field: "supplier", headerName: "Supplier agent", minWidth: 180 },
      { field: "score", headerName: "Score", maxWidth: 100 },
      { field: "landed", headerName: "Landed total" },
      { field: "landedUnit", headerName: "Landed / unit" },
      { field: "unit", headerName: "Unit price" },
      { field: "shipping", headerName: "Shipping", maxWidth: 110 },
      { field: "lead", headerName: "Days", maxWidth: 90 },
      { field: "terms", headerName: "Terms", maxWidth: 110 },
      { field: "reliability", headerName: "Reliability", maxWidth: 120 },
      { field: "margin", headerName: "Exp. margin", maxWidth: 120 },
      { field: "budget", headerName: "Budget used", maxWidth: 120 },
      {
        field: "policy",
        headerName: "Policy",
        minWidth: 220,
        cellClass: (p) => (p.value === "Inside policy" ? "text-success font-medium" : "text-warning"),
      },
    ],
    [],
  );

  return (
    <div className="space-y-3">
      <DataGrid rows={rows} columns={columns} emptyMessage="No final offers yet - finish the negotiation first." />
      {recommendation?.weights && (
        <p className="text-2xs text-muted-foreground">
          Deterministic weights:{" "}
          {Object.entries(recommendation.weights)
            .map(([k, v]) => `${k.replace("_", " ")} ${((toNumber(v) ?? 0) * 100).toFixed(0)}%`)
            .join(" · ")}
          . Only offers the backend validated as inside policy are scored.
        </p>
      )}
    </div>
  );
}
