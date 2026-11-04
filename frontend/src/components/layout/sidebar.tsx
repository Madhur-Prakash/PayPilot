"use client";

import { motion } from "framer-motion";
import { Gauge, PanelLeftClose, PanelLeftOpen } from "lucide-react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import * as React from "react";

import { Separator, Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/primitives";
import { NAV_SECTIONS } from "@/lib/constants/navigation";
import { cn } from "@/lib/utils";
import { useAuthStore } from "@/stores/auth";

export function Sidebar({
  collapsed,
  onToggle,
}: {
  collapsed: boolean;
  onToggle: () => void;
}) {
  const pathname = usePathname();
  const can = useAuthStore((s) => s.can);
  // Highlight only the most specific match, so /supply does not light up on /supply/negotiations.
  const activeHref = React.useMemo(() => {
    const matches = NAV_SECTIONS.flatMap((section) => section.items)
      .map((item) => item.href)
      .filter((href) => pathname === href || pathname.startsWith(`${href}/`));
    return matches.sort((a, b) => b.length - a.length)[0];
  }, [pathname]);

  return (
    <aside
      className={cn(
        "sticky top-0 hidden h-screen shrink-0 flex-col border-r border-sidebar-border bg-sidebar text-sidebar-foreground transition-[width] duration-300 lg:flex",
        collapsed ? "w-[68px]" : "w-64",
      )}
    >
      {/* Brand */}
      <div className="flex h-16 items-center gap-2.5 px-4">
        <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-sidebar-accent text-white">
          <Gauge className="h-4.5 w-4.5" strokeWidth={2.25} />
        </div>
        {!collapsed && (
          <div className="min-w-0 flex-1">
            <p className="truncate text-sm font-semibold leading-tight text-white">
              PayPilot
            </p>
            <p className="truncate text-2xs text-sidebar-foreground/60">AI operating system for merchants</p>
          </div>
        )}
        <button
          type="button"
          onClick={onToggle}
          aria-label={collapsed ? "Expand navigation" : "Collapse navigation"}
          className="ml-auto rounded-md p-1.5 text-sidebar-foreground/50 transition-colors hover:bg-white/5 hover:text-white focus-ring"
        >
          {collapsed ? (
            <PanelLeftOpen className="h-4 w-4" />
          ) : (
            <PanelLeftClose className="h-4 w-4" />
          )}
        </button>
      </div>

      <Separator className="bg-sidebar-border" />

      {/* Navigation */}
      <nav className="flex-1 space-y-5 overflow-y-auto px-3 py-4">
        {NAV_SECTIONS.map((section) => {
          const visible = section.items.filter((item) => !item.permission || can(item.permission));
          if (visible.length === 0) return null;

          return (
            <div key={section.label} className="space-y-1">
              {!collapsed && (
                <p className="px-2 pb-1 text-2xs font-semibold uppercase tracking-widest text-sidebar-foreground/40">
                  {section.label}
                </p>
              )}
              {visible.map((item) => {
                const active = item.href === activeHref;
                const link = (
                  <Link
                    key={item.href}
                    href={item.href}
                    className={cn(
                      "group relative flex items-center gap-2.5 rounded-lg px-2.5 py-2 text-sm transition-colors focus-ring",
                      active
                        ? "text-white"
                        : "text-sidebar-foreground/75 hover:bg-white/5 hover:text-white",
                      collapsed && "justify-center px-0",
                    )}
                  >
                    {active && (
                      <motion.span
                        layoutId="nav-active"
                        className="absolute inset-0 rounded-lg bg-sidebar-accent/90"
                        transition={{ type: "spring", stiffness: 380, damping: 32 }}
                      />
                    )}
                    <item.icon
                      className={cn("relative z-10 h-4 w-4 shrink-0", active && "text-white")}
                      strokeWidth={active ? 2.2 : 1.9}
                    />
                    {!collapsed && <span className="relative z-10 truncate">{item.label}</span>}
                  </Link>
                );

                return collapsed ? (
                  <Tooltip key={item.href}>
                    <TooltipTrigger asChild>{link}</TooltipTrigger>
                    <TooltipContent side="right">
                      <p className="font-medium">{item.label}</p>
                      <p className="text-muted-foreground">{item.description}</p>
                    </TooltipContent>
                  </Tooltip>
                ) : (
                  link
                );
              })}
            </div>
          );
        })}
      </nav>
    </aside>
  );
}
