"use client";

import { AnimatePresence, motion } from "framer-motion";
import { Gauge, X } from "lucide-react";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import * as React from "react";

import { Sidebar } from "@/components/layout/sidebar";
import { Topbar } from "@/components/layout/topbar";
import { Button } from "@/components/ui/button";
import { VoiceAgentDock } from "@/components/voice/voice-agent-dock";
import { VoiceNavBridge } from "@/components/voice/voice-nav-bridge";
import { NAV_SECTIONS } from "@/lib/constants/navigation";
import { cn } from "@/lib/utils";
import { useAuthStore } from "@/stores/auth";

export default function DashboardLayout({ children }: { children: React.ReactNode }) {
  const router = useRouter();
  const pathname = usePathname();
  const status = useAuthStore((s) => s.status);
  const can = useAuthStore((s) => s.can);

  const [collapsed, setCollapsed] = React.useState(false);
  const [mobileNavOpen, setMobileNavOpen] = React.useState(false);

  // Route guard. The backend rejects unauthenticated requests regardless; this
  // just avoids rendering a shell the user cannot use.
  React.useEffect(() => {
    if (status === "unauthenticated") router.replace("/login");
  }, [status, router]);

  React.useEffect(() => setMobileNavOpen(false), [pathname]);

  if (status === "idle" || status === "loading") {
    return (
      <div className="flex min-h-screen items-center justify-center">
        <div className="flex flex-col items-center gap-3">
          <div className="flex h-11 w-11 animate-pulse items-center justify-center rounded-xl bg-primary text-primary-foreground">
            <Gauge className="h-5 w-5" />
          </div>
          <p className="text-sm text-muted-foreground">Restoring your session…</p>
        </div>
      </div>
    );
  }

  if (status === "unauthenticated") return null;

  return (
    <div className="flex min-h-screen">
      <VoiceNavBridge />
      <VoiceAgentDock />
      <Sidebar collapsed={collapsed} onToggle={() => setCollapsed((c) => !c)} />

      {/* Mobile navigation */}
      <AnimatePresence>
        {mobileNavOpen && (
          <>
            <motion.div
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              exit={{ opacity: 0 }}
              onClick={() => setMobileNavOpen(false)}
              className="fixed inset-0 z-40 bg-foreground/40 backdrop-blur-sm lg:hidden"
            />
            <motion.nav
              initial={{ x: "-100%" }}
              animate={{ x: 0 }}
              exit={{ x: "-100%" }}
              transition={{ type: "spring", stiffness: 340, damping: 34 }}
              className="fixed inset-y-0 left-0 z-50 w-72 overflow-y-auto bg-sidebar p-4 text-sidebar-foreground lg:hidden"
            >
              <div className="mb-4 flex items-center justify-between">
                <span className="text-sm font-semibold text-white">Growth Autopilot</span>
                <Button
                  variant="ghost"
                  size="icon-sm"
                  onClick={() => setMobileNavOpen(false)}
                  aria-label="Close navigation"
                  className="text-sidebar-foreground/70 hover:bg-white/5 hover:text-white"
                >
                  <X className="h-4 w-4" />
                </Button>
              </div>
              {NAV_SECTIONS.map((section) => {
                const visible = section.items.filter(
                  (item) => !item.permission || can(item.permission),
                );
                if (!visible.length) return null;
                return (
                  <div key={section.label} className="mb-4 space-y-1">
                    <p className="px-2 pb-1 text-2xs font-semibold uppercase tracking-widest text-sidebar-foreground/40">
                      {section.label}
                    </p>
                    {visible.map((item) => {
                      const active = pathname === item.href;
                      return (
                        <Link
                          key={item.href}
                          href={item.href}
                          className={cn(
                            "flex items-center gap-2.5 rounded-lg px-2.5 py-2 text-sm",
                            active
                              ? "bg-sidebar-accent text-white"
                              : "text-sidebar-foreground/75 hover:bg-white/5",
                          )}
                        >
                          <item.icon className="h-4 w-4" />
                          {item.label}
                        </Link>
                      );
                    })}
                  </div>
                );
              })}
            </motion.nav>
          </>
        )}
      </AnimatePresence>

      <div className="flex min-w-0 flex-1 flex-col">
        <Topbar onOpenMobileNav={() => setMobileNavOpen(true)} />
        <main className="flex-1 px-4 pb-16 pt-6 lg:px-6">
          <div className="mx-auto w-full max-w-[1400px]">{children}</div>
        </main>
      </div>
    </div>
  );
}
