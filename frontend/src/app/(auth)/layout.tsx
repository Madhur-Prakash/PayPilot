"use client";

import { motion } from "framer-motion";
import {
  BadgeCheck,
  Gauge,
  LineChart,
  ShieldCheck,
  Stethoscope,
  TestTubeDiagonal,
} from "lucide-react";
import { useRouter } from "next/navigation";
import * as React from "react";

import { APP_NAME, APP_TAGLINE } from "@/lib/constants/config";
import { useAuthStore } from "@/stores/auth";

const LOOP = [
  { icon: LineChart, label: "Observe", copy: "Deterministic metrics computed in SQL" },
  { icon: Stethoscope, label: "Diagnose", copy: "Evidence-backed opportunities, sized in dollars" },
  { icon: TestTubeDiagonal, label: "Act", copy: "Controlled experiments with a held-out control" },
  { icon: BadgeCheck, label: "Learn", copy: "Measured lift, ROI and a SCALE or STOP decision" },
];

export default function AuthLayout({ children }: { children: React.ReactNode }) {
  const router = useRouter();
  const status = useAuthStore((s) => s.status);

  React.useEffect(() => {
    if (status === "authenticated") router.replace("/dashboard");
  }, [status, router]);

  return (
    <div className="grid min-h-screen lg:grid-cols-[1.05fr_1fr]">
      {/* Narrative panel. Hidden on small screens - the form is what matters there. */}
      <div className="relative hidden overflow-hidden bg-sidebar px-12 py-14 text-sidebar-foreground lg:flex lg:flex-col">
        <div className="grid-texture pointer-events-none absolute inset-0 opacity-[0.14]" />
        <div className="pointer-events-none absolute -left-24 top-10 h-80 w-80 rounded-full bg-primary/25 blur-[110px]" />
        <div className="pointer-events-none absolute bottom-0 right-0 h-72 w-72 rounded-full bg-chart-3/20 blur-[110px]" />

        <div className="relative z-10 flex items-center gap-3">
          <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-primary text-primary-foreground">
            <Gauge className="h-5 w-5" strokeWidth={2.25} />
          </div>
          <div>
            <p className="text-sm font-semibold text-white">{APP_NAME}</p>
            <p className="text-2xs text-sidebar-foreground/60">Merchant growth intelligence</p>
          </div>
        </div>

        <div className="relative z-10 mt-auto space-y-10">
          <div className="space-y-4">
            <motion.h2
              initial={{ opacity: 0, y: 14 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ duration: 0.5, ease: [0.22, 1, 0.36, 1] }}
              className="max-w-md text-[2.1rem] font-semibold leading-[1.15] tracking-tight text-white"
            >
              {APP_TAGLINE}
            </motion.h2>
            <motion.p
              initial={{ opacity: 0, y: 14 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ duration: 0.5, delay: 0.08, ease: [0.22, 1, 0.36, 1] }}
              className="max-w-md text-[0.9375rem] leading-relaxed text-sidebar-foreground/70"
            >
              It does not just analyse the business. It finds the opportunity, explains the
              evidence behind it, and helps you run a controlled test to find out whether acting on
              it actually worked.
            </motion.p>
          </div>

          <div className="grid max-w-md gap-3">
            {LOOP.map((step, index) => (
              <motion.div
                key={step.label}
                initial={{ opacity: 0, x: -12 }}
                animate={{ opacity: 1, x: 0 }}
                transition={{ duration: 0.42, delay: 0.16 + index * 0.07 }}
                className="flex items-start gap-3 rounded-xl border border-white/10 bg-white/[0.04] p-3.5"
              >
                <div className="mt-0.5 flex h-7 w-7 shrink-0 items-center justify-center rounded-lg bg-primary/20 text-primary">
                  <step.icon className="h-3.5 w-3.5" />
                </div>
                <div className="min-w-0">
                  <p className="text-sm font-medium text-white">{step.label}</p>
                  <p className="text-xs text-sidebar-foreground/60">{step.copy}</p>
                </div>
              </motion.div>
            ))}
          </div>

          <div className="flex items-start gap-2.5 border-t border-white/10 pt-6 text-2xs leading-relaxed text-sidebar-foreground/50">
            <ShieldCheck className="mt-0.5 h-3.5 w-3.5 shrink-0" />
            <p>
              Analytics run on a seeded demo dataset. PayPal runs in sandbox or simulation mode - no live PayPal transaction, customer-messaging or
              competitor-platform feed. Actions that move money always require explicit human
              approval.
            </p>
          </div>
        </div>
      </div>

      <div className="flex items-center justify-center px-5 py-10 sm:px-10">
        <div className="w-full max-w-[26rem]">{children}</div>
      </div>
    </div>
  );
}
