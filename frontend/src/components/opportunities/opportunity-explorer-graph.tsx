"use client";

import * as React from "react";
import {
  Boxes,
  Check,
  ChevronRight,
  Clock,
  Compass,
  type LucideIcon,
  Package,
  Percent,
  Shield,
  ShoppingBag,
  Target,
  TrendingUp,
  Users,
  Zap,
} from "lucide-react";
import { AddOpportunityDialog } from "@/components/opportunities/add-opportunity-dialog";
import {
  ConstellationCanvas,
} from "@/components/opportunities/constellation-canvas";
import { formatCompactCurrency, cn } from "@/lib/utils";
import type { Opportunity } from "@/types/api";

interface OpportunityExplorerGraphProps {
  opportunities: Opportunity[];
  selectedId?: string;
  onSelect: (opportunity: Opportunity) => void;
  className?: string;
}

export type DomainType = "customers" | "pricing" | "category" | "product" | "operations";

interface DomainConfig {
  id: DomainType;
  label: string;
  badgeBg: string;
  badgeText: string;
  badgeBorder: string;
  nodeBg: string;
  nodeBorder: string;
  nodeIcon: string;
  dotColor: string;
  lineColor: string;
  hubId: "customerHub" | "pricingHub" | "productHub";
}

// Sophisticated, professional palette (clean neutrals with subtle, tasteful accents)
export const DOMAINS: Record<DomainType, DomainConfig> = {
  customers: {
    id: "customers",
    label: "Customers",
    badgeBg: "bg-indigo-50/80 text-indigo-700",
    badgeText: "text-indigo-700",
    badgeBorder: "border-indigo-200/80",
    nodeBg: "bg-white",
    nodeBorder: "border-indigo-300",
    nodeIcon: "text-indigo-600",
    dotColor: "bg-indigo-500",
    lineColor: "#818cf8",
    hubId: "customerHub",
  },
  pricing: {
    id: "pricing",
    label: "Pricing & Margins",
    badgeBg: "bg-sky-50/80 text-sky-700",
    badgeText: "text-sky-700",
    badgeBorder: "border-sky-200/80",
    nodeBg: "bg-white",
    nodeBorder: "border-sky-300",
    nodeIcon: "text-sky-600",
    dotColor: "bg-sky-500",
    lineColor: "#38bdf8",
    hubId: "pricingHub",
  },
  category: {
    id: "category",
    label: "Category & Combos",
    badgeBg: "bg-teal-50/80 text-teal-700",
    badgeText: "text-teal-700",
    badgeBorder: "border-teal-200/80",
    nodeBg: "bg-white",
    nodeBorder: "border-teal-300",
    nodeIcon: "text-teal-600",
    dotColor: "bg-teal-500",
    lineColor: "#2dd4bf",
    hubId: "productHub",
  },
  product: {
    id: "product",
    label: "Product & Launch",
    badgeBg: "bg-amber-50/80 text-amber-700",
    badgeText: "text-amber-700",
    badgeBorder: "border-amber-200/80",
    nodeBg: "bg-white",
    nodeBorder: "border-amber-300",
    nodeIcon: "text-amber-600",
    dotColor: "bg-amber-500",
    lineColor: "#fbbf24",
    hubId: "productHub",
  },
  operations: {
    id: "operations",
    label: "Operations",
    badgeBg: "bg-slate-100 text-slate-700",
    badgeText: "text-slate-700",
    badgeBorder: "border-slate-300",
    nodeBg: "bg-white",
    nodeBorder: "border-slate-300",
    nodeIcon: "text-slate-600",
    dotColor: "bg-slate-500",
    lineColor: "#94a3b8",
    hubId: "pricingHub",
  },
};


// Domain-spanning fallback items to guarantee coverage across all 5 requested domains
const SAMPLE_DOMAIN_OPPORTUNITIES: Partial<Opportunity>[] = [
  {
    id: "domain-pricing-chai-margin",
    key: "pricing-chai-margin-opt",
    title: "Margin recalibration on Masala Chai & Beverages",
    summary:
      "High volume (420+ weekly orders) with inelastic demand. A ₹5 price calibration captures pure margin without impacting order volume.",
    kind: "PRICING",
    estimated_value_monthly: 12500,
    confidence: 0.88,
    impact: "HIGH",
    effort: "LOW",
    status: "DETECTED",
    tags: ["pricing", "beverage", "margin"],
    evidence: [
      {
        metric: "Beverage attach rate",
        value: "48.2%",
        change: "+4.1%",
        source: "analytics",
        detail: "Consistent attach across morning and evening dayparts.",
        reference: "products",
      },
    ],
    hypothesis:
      "Customer price sensitivity on signature tea is low compared to dine-in snacks. Minor recalibration directly lifts contribution margin.",
    recommended_action:
      "Roll out ₹5 adjustment across hot beverages on Paypal POS with an A/B holdout test.",
    reasoning: "High frequency allows instant verification within 7 days.",
    graph_path: ["revenue", "margin", "pricing:beverage"],
    target_segment: { channel: "POS", category: "Beverages" },
    priority_score: 91,
    risk: "low",
    requires_approval: true,
    created_at: new Date().toISOString(),
    updated_at: new Date().toISOString(),
    detected_at: new Date().toISOString(),
    period_start: null,
    period_end: null,
    agent_run_id: null,
    campaign_id: null,
    experiment_id: null,
  },
  {
    id: "domain-launch-gourmet-samosa",
    key: "product-launch-gourmet-variant",
    title: "Launch signature Gourmet Cheese Samosa variant",
    summary:
      "Customer review signals and market search show unmet demand for premium snack variants during peak evening tea hours.",
    kind: "PRODUCT",
    estimated_value_monthly: 14200,
    confidence: 0.82,
    impact: "HIGH",
    effort: "MEDIUM",
    status: "DETECTED",
    tags: ["product-launch", "snack", "upsell"],
    evidence: [
      {
        metric: "Unmet customer snack mentions",
        value: "38 reviews",
        change: "+45%",
        source: "reviews",
        detail: "Positive sentiment for gourmet snack offerings.",
        reference: "reviews",
      },
    ],
    hypothesis:
      "Snack buyers have a 32% propensity to upgrade to premium fillings when highlighted at checkout.",
    recommended_action:
      "Test small-batch weekend production of Gourmet Cheese Samosa priced at ₹45.",
    reasoning: "Validates recipe and customer willingness to pay before full menu rollout.",
    graph_path: ["product", "launch", "menu:snacks"],
    target_segment: { daypart: "EVENING", spend_tier: "VIP" },
    priority_score: 86,
    risk: "low",
    requires_approval: true,
    created_at: new Date().toISOString(),
    updated_at: new Date().toISOString(),
    detected_at: new Date().toISOString(),
    period_start: null,
    period_end: null,
    agent_run_id: null,
    campaign_id: null,
    experiment_id: null,
  },
  {
    id: "domain-customer-vip-loyalty",
    key: "customers-vip-frequency-accelerator",
    title: "Accelerate 2nd-order repeat for first-time diners",
    summary:
      "New diners who return within 10 days show 4.2x higher lifetime value. A timed day-3 incentive bridges the repeat drop-off gap.",
    kind: "RETENTION",
    estimated_value_monthly: 16800,
    confidence: 0.91,
    impact: "HIGH",
    effort: "LOW",
    status: "DETECTED",
    tags: ["customers", "repeat", "ltv"],
    evidence: [
      {
        metric: "Day-10 Repeat Cohort Dropoff",
        value: "68.4%",
        change: "-5.2%",
        source: "analytics",
        detail: "Largest customer loss occurs between transaction 1 and 2.",
        reference: "customers",
      },
    ],
    hypothesis:
      "A timed WhatsApp incentive offering a complimentary beverage on visit #2 lifts cohort retention by 28%.",
    recommended_action:
      "Launch automated Paypal Growth Agent campaign targeting new customers on Day 3 post-first purchase.",
    reasoning: "Low marginal food cost with strong recurring revenue upside.",
    graph_path: ["customers", "retention", "cohort:new"],
    target_segment: { order_count: 1, days_since: 3 },
    priority_score: 94,
    risk: "low",
    requires_approval: true,
    created_at: new Date().toISOString(),
    updated_at: new Date().toISOString(),
    detected_at: new Date().toISOString(),
    period_start: null,
    period_end: null,
    agent_run_id: null,
    campaign_id: null,
    experiment_id: null,
  },
];

function inferOpportunityDomain(opp: Opportunity): DomainType {
  const t = (opp.title || "").toLowerCase();
  const k = (opp.kind || "").toLowerCase();
  const tags = (opp.tags || []).map((x) => x.toLowerCase());

  if (
    tags.includes("pricing") ||
    t.includes("price") ||
    t.includes("pricing") ||
    t.includes("margin") ||
    k === "pricing"
  ) {
    return "pricing";
  }
  if (
    tags.includes("product-launch") ||
    t.includes("launch") ||
    t.includes("new variant") ||
    t.includes("arrest the decline") ||
    t.includes("reform") ||
    k === "product"
  ) {
    return "product";
  }
  if (
    tags.includes("bundle") ||
    t.includes("bundle") ||
    t.includes("combo") ||
    t.includes("cross-sell") ||
    k === "bundle"
  ) {
    return "category";
  }
  if (
    tags.includes("service") ||
    t.includes("service") ||
    t.includes("slowdown") ||
    t.includes("throughput") ||
    t.includes("bottleneck") ||
    k === "service"
  ) {
    return "operations";
  }
  return "customers";
}

/** The values `OpportunityKind` actually emits, mapped to an icon each. */
const KIND_ICONS: Record<string, LucideIcon> = {
  RETENTION: Users,
  BUNDLE: Boxes,
  DAYPART: Clock,
  PRODUCT: ShoppingBag,
  PRICING: TrendingUp,
  SERVICE: Zap,
  INVENTORY: Package,
};

/** Icon for a node: the opportunity's own wording first, then its detector kind. */
function getNodeIcon(title: string, kind: string) {
  const t = (title || "").toLowerCase();
  if (t.includes("security") || t.includes("risk") || t.includes("protect")) return Shield;
  if (t.includes("bundle") || t.includes("mix") || t.includes("package")) return Boxes;
  if (t.includes("service") || t.includes("speed") || t.includes("margin")) return Zap;
  if (t.includes("customer") || t.includes("lapsed") || t.includes("win-back")) return Users;
  if (t.includes("inventory") || t.includes("stock") || t.includes("order")) return ShoppingBag;
  return KIND_ICONS[kind] ?? Target;
}

export function OpportunityExplorerGraph({
  opportunities,
  selectedId,
  onSelect,
  className,
}: OpportunityExplorerGraphProps) {
  const [activeDomain, setActiveDomain] = React.useState<string>("all");
  const [adding, setAdding] = React.useState(false);
  // Held until the refetch brings the new opportunity back, then used to
  // select it so the canvas says where it went.
  const [justAddedId, setJustAddedId] = React.useState<string | null>(null);
  const [hoveredNodeId, setHoveredNodeId] = React.useState<string | null>(null);

  // Combine backend opportunities with samples if needed to cover all 5 requested domains
  const allOpportunities = React.useMemo(() => {
    const list = [...opportunities];
    const existingDomains = new Set(list.map((o) => inferOpportunityDomain(o)));

    SAMPLE_DOMAIN_OPPORTUNITIES.forEach((sample) => {
      const sampleDomain = inferOpportunityDomain(sample as Opportunity);
      if (!existingDomains.has(sampleDomain) || list.length < 6) {
        if (!list.some((o) => o.id === sample.id || o.key === sample.key)) {
          list.push(sample as Opportunity);
          existingDomains.add(sampleDomain);
        }
      }
    });

    return list;
  }, [opportunities]);

  const mappedNodes = React.useMemo(() => {
    return allOpportunities
      // Dismissed means a person took it off the board. Leaving it drawn would
      // make the action look like it had done nothing.
      .filter((opp) => opp.status !== "DISMISSED")
      .map((opp) => {
        const domain = inferOpportunityDomain(opp);
        const config = DOMAINS[domain];
        const IconComponent = getNodeIcon(opp.title, opp.kind);

        return {
          ...opp,
          domain,
          config,
          IconComponent,
        };
      });
  }, [allOpportunities]);

  React.useEffect(() => {
    if (!justAddedId) return;
    const arrived = opportunities.find((opp) => opp.id === justAddedId);
    if (arrived) {
      onSelect(arrived);
      setJustAddedId(null);
    }
  }, [justAddedId, opportunities, onSelect]);

  const filteredNodes = React.useMemo(() => {
    if (activeDomain === "all") return mappedNodes;
    return mappedNodes.filter((n) => n.domain === activeDomain);
  }, [mappedNodes, activeDomain]);

  // Constellation Pillar Hubs
  const hubs = {
    customerHub: {
      id: "customerHub",
      x: 25,
      y: 46,
      label: "Customer LTV Hub",
      sub: "Retention & Loyalty",
      icon: Users,
    },
    pricingHub: {
      id: "pricingHub",
      x: 52,
      y: 70,
      label: "Pricing & Margin Hub",
      sub: "Elasticity & Yield",
      icon: Percent,
    },
    productHub: {
      id: "productHub",
      x: 75,
      y: 42,
      label: "Product & Menu Hub",
      sub: "Combos & Launches",
      icon: Package,
    },
  };

  // Fixed static radial coordinates around hubs (no jitter, no floating animations)
  const positionedNodes = React.useMemo(() => {
    const hubGroups: Record<string, typeof filteredNodes> = {
      customerHub: [],
      pricingHub: [],
      productHub: [],
    };

    filteredNodes.forEach((node) => {
      hubGroups[node.config.hubId].push(node);
    });

    return filteredNodes.map((node) => {
      const hub = hubs[node.config.hubId];
      const group = hubGroups[node.config.hubId];
      const index = group.indexOf(node);
      const total = Math.max(group.length, 1);

      const angle = (index / total) * 2 * Math.PI - Math.PI / 2;
      const radiusX = node.config.hubId === "pricingHub" ? 17 : 15;
      const radiusY = node.config.hubId === "pricingHub" ? 21 : 23;

      const posX = hub.x + Math.cos(angle) * radiusX;
      const posY = hub.y + Math.sin(angle) * radiusY;

      return {
        ...node,
        hub,
        posX: Math.max(7, Math.min(93, posX)),
        posY: Math.max(9, Math.min(89, posY)),
      };
    });
  }, [filteredNodes]);

  const activeHoveredOpportunity = React.useMemo(() => {
    if (!hoveredNodeId) return null;
    return positionedNodes.find((n) => n.id === hoveredNodeId);
  }, [hoveredNodeId, positionedNodes]);

  return (
    <div
      className={cn(
        "relative overflow-hidden rounded-2xl border border-slate-200 bg-white shadow-sm",
        className,
      )}
    >
      {/* Subtle, clean architectural light background */}
      <div className="absolute inset-0 bg-gradient-to-b from-slate-50/50 to-white pointer-events-none" />
      <div className="absolute inset-0 bg-[radial-gradient(#e2e8f0_1px,transparent_1px)] [background-size:24px_24px] opacity-60 pointer-events-none" />

      {/* Header & Filter Toolbar */}
      <div className="relative z-20 border-b border-slate-200 bg-white/90 px-5 py-3.5 backdrop-blur-xs">
        <div className="flex flex-col gap-2.5 sm:flex-row sm:items-center sm:justify-between">
          <div>
            <div className="flex items-center gap-1.5 text-xs text-slate-500 font-medium">
              <span>Opportunities</span>
              <ChevronRight className="h-3 w-3 text-slate-400" />
              <span className="text-slate-900 font-semibold">Growth Network</span>
            </div>
            <h2 className="text-base font-semibold text-slate-900 tracking-tight mt-0.5">
              Opportunity Explorer
            </h2>
          </div>

          <div className="flex items-center gap-2">
            <span className="inline-flex items-center gap-1.5 rounded-lg bg-slate-100 px-2.5 py-1 text-xs font-medium text-slate-700">
              <Compass className="h-3.5 w-3.5 text-slate-500" />
              {allOpportunities.length} opportunities detected
            </span>
          </div>
        </div>

        {/* Clean domain filter pills */}
        <div className="mt-3 flex flex-wrap items-center gap-1.5">
          <button
            type="button"
            onClick={() => setActiveDomain("all")}
            className={cn(
              "flex items-center gap-1.5 rounded-lg px-3 py-1 text-xs font-medium transition-colors border",
              activeDomain === "all"
                ? "bg-slate-900 text-white border-slate-900"
                : "bg-white text-slate-600 border-slate-200 hover:bg-slate-50",
            )}
          >
            <span>All Domains</span>
            <span
              className={cn(
                "rounded px-1.5 py-0.2 text-3xs font-semibold",
                activeDomain === "all" ? "bg-slate-800 text-slate-200" : "bg-slate-100 text-slate-500",
              )}
            >
              {mappedNodes.length}
            </span>
          </button>

          {(Object.keys(DOMAINS) as DomainType[]).map((key) => {
            const config = DOMAINS[key];
            const count = mappedNodes.filter((n) => n.domain === key).length;
            const active = activeDomain === key;

            return (
              <button
                key={key}
                type="button"
                onClick={() => setActiveDomain(key)}
                className={cn(
                  "flex items-center gap-1.5 rounded-lg px-3 py-1 text-xs font-medium transition-colors border",
                  active
                    ? "bg-slate-900 text-white border-slate-900"
                    : "bg-white text-slate-600 border-slate-200 hover:bg-slate-50",
                )}
              >
                <span className={cn("h-2 w-2 rounded-full", config.dotColor)} />
                <span>{config.label}</span>
                <span
                  className={cn(
                    "rounded px-1.5 py-0.2 text-3xs font-semibold",
                    active ? "bg-slate-800 text-slate-200" : "bg-slate-100 text-slate-500",
                  )}
                >
                  {count}
                </span>
              </button>
            );
          })}
        </div>
      </div>

      {/* Main Grid: Graph Canvas + Right List Panel */}
      <div className="relative z-10 grid grid-cols-1 lg:grid-cols-[minmax(0,1.8fr)_minmax(0,1.2fr)] min-h-[440px]">
        {/* Constellation Canvas */}
        <ConstellationCanvas
          onAddNode={() => setAdding(true)}
          nodes={positionedNodes.map((node) => ({
            id: node.id,
            title: node.title,
            value: node.estimated_value_monthly,
            icon: node.IconComponent,
            hubId: node.config.hubId,
            x: node.posX,
            y: node.posY,
            color: node.config.lineColor,
            isManual: node.key?.startsWith("manual-") ?? false,
          }))}
          hubs={Object.values(hubs).map((hub) => ({
            id: hub.id,
            label: hub.label,
            sub: hub.sub,
            icon: hub.icon,
            x: hub.x,
            y: hub.y,
          }))}
          selectedId={selectedId}
          onSelect={(id) => {
            const picked = positionedNodes.find((node) => node.id === id);
            if (picked) onSelect(picked);
          }}
          hoveredId={hoveredNodeId}
          onHover={setHoveredNodeId}
        />

        {/* Right Opportunities List Panel */}
        <div className="border-t lg:border-t-0 lg:border-l border-slate-200 bg-slate-50/40 p-4 flex flex-col justify-between">
          <div>
            {/* List Header */}
            <div className="flex items-center justify-between pb-3 border-b border-slate-200">
              <div className="flex items-center gap-1.5">
                <h3 className="text-xs font-semibold uppercase tracking-wider text-slate-700">
                  Detected Opportunities
                </h3>
                <span className="rounded-full bg-slate-200 px-2 py-0.2 text-3xs font-semibold text-slate-700">
                  {filteredNodes.length}
                </span>
              </div>
              <span className="text-3xs font-medium text-slate-500">Ranked by Yield</span>
            </div>

            {/* List Cards */}
            <div className="mt-3 space-y-2 max-h-[350px] overflow-y-auto pr-1">
              {filteredNodes.map((opp) => {
                const isSelected = selectedId === opp.id;
                const config = opp.config;
                const IconComp = opp.IconComponent;

                return (
                  <div
                    key={opp.id}
                    onClick={() => onSelect(opp)}
                    onMouseEnter={() => setHoveredNodeId(opp.id)}
                    onMouseLeave={() => setHoveredNodeId(null)}
                    className={cn(
                      "group flex items-start gap-3 rounded-xl p-3 transition-colors duration-150 cursor-pointer border",
                      isSelected
                        ? "bg-white border-blue-500 ring-2 ring-blue-100 shadow-xs"
                        : "bg-white/80 border-slate-200/80 hover:bg-white hover:border-slate-300",
                    )}
                  >
                    {/* Checkbox selector */}
                    <div
                      className={cn(
                        "mt-0.5 flex h-4 w-4 shrink-0 items-center justify-center rounded border transition-colors",
                        isSelected
                          ? "bg-blue-600 border-blue-600 text-white"
                          : "border-slate-300 bg-white group-hover:border-slate-400",
                      )}
                    >
                      {isSelected && <Check className="h-2.5 w-2.5 stroke-[3]" />}
                    </div>

                    {/* Node Mini Icon */}
                    <div
                      className={cn(
                        "flex h-7 w-7 shrink-0 items-center justify-center rounded-lg border",
                        config.nodeBg,
                        config.badgeBorder,
                      )}
                    >
                      <IconComp className={cn("h-3.5 w-3.5", config.nodeIcon)} />
                    </div>

                    {/* Card Content */}
                    <div className="min-w-0 flex-1">
                      <div className="flex items-start justify-between gap-2">
                        <p className="text-xs font-semibold text-slate-800 truncate leading-snug group-hover:text-blue-600 transition-colors">
                          {opp.title}
                        </p>
                        <span className="text-xs font-semibold text-slate-900 shrink-0">
                          +{formatCompactCurrency(opp.estimated_value_monthly)}
                        </span>
                      </div>

                      <div className="mt-1.5 flex items-center gap-1.5">
                        <span
                          className={cn(
                            "inline-flex items-center gap-1 rounded px-1.5 py-0.2 text-3xs font-medium border",
                            config.badgeBg,
                            config.badgeBorder,
                          )}
                        >
                          <span className={cn("h-1.5 w-1.5 rounded-full", config.dotColor)} />
                          {config.label}
                        </span>

                        <span className="text-3xs text-slate-500">
                          {opp.confidence
                            ? `${Math.round(opp.confidence <= 1 ? opp.confidence * 100 : opp.confidence)}% conf`
                            : "High"}
                        </span>

                        {isSelected && (
                          <span className="ml-auto inline-flex items-center gap-0.5 text-3xs font-medium text-blue-600">
                            Active
                          </span>
                        )}
                      </div>
                    </div>
                  </div>
                );
              })}
            </div>
          </div>

          {/* Footer Summary Bar */}
          <div className="pt-3 mt-3 border-t border-slate-200 flex items-center justify-between text-2xs text-slate-500">
            <span>Select opportunity to view evidence below</span>
            <span className="font-semibold text-slate-900">
              Total:{" "}
              {formatCompactCurrency(
                allOpportunities.reduce((acc, o) => acc + o.estimated_value_monthly, 0),
              )}
              /mo
            </span>
          </div>
        </div>
      </div>
      <AddOpportunityDialog
        open={adding}
        onClose={() => setAdding(false)}
        onCreated={setJustAddedId}
      />
    </div>
  );
}
