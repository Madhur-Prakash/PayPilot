import {
  Activity,
  BarChart3,
  BookOpen,
  Bot,
  Boxes,
  Brain,
  Building2,
  LayoutDashboard,
  LineChart,
  Mic,
  type LucideIcon,
  Megaphone,
  MessageSquareQuote,
  ScanSearch,
  ScrollText,
  Settings,
  Radar,
  ShoppingCart,
  Swords,
  Target,
  TestTubeDiagonal,
  Users,
  Workflow,
} from "lucide-react";

export interface NavItem {
  label: string;
  href: string;
  icon: LucideIcon;
  /** Hidden when the user lacks this permission. The backend enforces it regardless. */
  permission?: string;
  description: string;
}

export interface NavSection {
  label: string;
  items: NavItem[];
}

/** Grouped to mirror the growth loop, not the database schema. */
export const NAV_SECTIONS: NavSection[] = [
  {
    label: "Observe",
    items: [
      {
        label: "Command Center",
        href: "/dashboard",
        icon: LayoutDashboard,
        permission: "dashboard:read",
        description: "How the business is performing right now",
      },
      {
        label: "Growth Graph",
        href: "/growth",
        icon: LineChart,
        permission: "growth:read",
        description: "What changed, and where it concentrates",
      },
    ],
  },
  {
    label: "Diagnose",
    items: [
      {
        label: "Opportunities",
        href: "/opportunities",
        icon: Target,
        permission: "growth:read",
        description: "Quantified, evidence-backed growth opportunities",
      },
      {
        label: "Reviews",
        href: "/reviews",
        icon: MessageSquareQuote,
        permission: "reviews:read",
        description: "What customers are actually saying",
      },
      {
        label: "Competitors",
        href: "/competitors",
        icon: Swords,
        permission: "competitors:read",
        description: "Where rivals are ahead, and where you are",
      },
      {
        label: "External Signals",
        href: "/signals",
        icon: Radar,
        permission: "signals:read",
        description: "Market events scored against your revenue exposure",
      },
    ],
  },
  {
    label: "Act",
    items: [
      {
        label: "Campaigns",
        href: "/campaigns",
        icon: Megaphone,
        permission: "campaign:read",
        description: "Interventions, and their approval state",
      },
      {
        label: "Experiments",
        href: "/experiments",
        icon: TestTubeDiagonal,
        permission: "experiment:read",
        description: "Control vs test, lift, ROI and the decision",
      },
      {
        label: "Impact Tree",
        href: "/impact",
        icon: Workflow,
        permission: "growth:read",
        description: "What launched, what moved, what the control proved",
      },
    ],
  },
  {
    label: "Understand",
    items: [
      {
        label: "Customers",
        href: "/customers",
        icon: Users,
        permission: "customers:read",
        description: "Segments, retention and churn risk",
      },
      {
        label: "Products",
        href: "/products",
        icon: BarChart3,
        permission: "products:read",
        description: "Performance and market-basket pairs",
      },
      {
        label: "Inventory",
        href: "/inventory",
        icon: Boxes,
        permission: "inventory:read",
        description: "Days of cover and revenue at risk",
      },
      {
        label: "Inventory Book",
        href: "/inventory/book",
        icon: BookOpen,
        permission: "inventory:ledger_read",
        description: "Opening, movements and closing per SKU",
      },
      {
        label: "Stock Ledger",
        href: "/inventory/ledger",
        icon: ScrollText,
        permission: "inventory:ledger_read",
        description: "Every movement, and what caused it",
      },
      {
        label: "Vendors",
        href: "/vendors",
        icon: Building2,
        permission: "vendor:read",
        description: "Who the automation can order from",
      },
      {
        label: "Purchase Orders",
        href: "/purchase-orders",
        icon: ShoppingCart,
        permission: "purchase_order:read",
        description: "Automated and manual orders, and the approval gate",
      },
      {
        label: "Automation",
        href: "/inventory/automation",
        icon: Workflow,
        permission: "automation:view",
        description: "Every automated decision and why it was made",
      },
    ],
  },
  {
    label: "Agents",
    items: [
      {
        label: "Agent Activity",
        href: "/agents",
        icon: Bot,
        permission: "agents:view",
        description: "What the agents did, and why",
      },
      {
        label: "Agent Memory",
        href: "/memory",
        icon: Brain,
        permission: "memory:read",
        description: "What the agents carry forward between runs",
      },
      {
        label: "Voice",
        href: "/voice",
        icon: Mic,
        permission: "agents:run",
        description: "Ask the Growth Scientist out loud",
      },
      {
        label: "AI Observability",
        href: "/observability",
        icon: ScanSearch,
        permission: "agents:view",
        description: "Langfuse traces, token usage, latency per agent run",
      },
      {
        label: "Audit Log",
        href: "/activity",
        icon: Activity,
        permission: "audit:read",
        description: "Every consequential action, with its actor",
      },
      {
        label: "Settings",
        href: "/settings",
        icon: Settings,
        permission: "settings:manage",
        description: "Merchant, integrations and RBAC",
      },
    ],
  },
];

export const ALL_NAV_ITEMS: NavItem[] = NAV_SECTIONS.flatMap((section) => section.items);
