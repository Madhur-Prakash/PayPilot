"use client";

/**
 * Motion vocabulary.
 *
 * Motion here is functional, not decorative: it shows where a value came from
 * (counters count), what just arrived (staggered entrance), and what the system
 * is doing right now (live pulse). Everything respects `prefers-reduced-motion`
 * via `useReducedMotion`, and degrades to the final state rather than to nothing.
 */

import { type HTMLMotionProps, motion, useInView, useReducedMotion } from "framer-motion";
import * as React from "react";

import { cn } from "@/lib/utils";

export const EASE_OUT = [0.22, 1, 0.36, 1] as const;

// --------------------------------------------------------------------------- //
// Entrance
// --------------------------------------------------------------------------- //
export function FadeIn({
  children,
  delay = 0,
  y = 10,
  className,
  ...props
}: HTMLMotionProps<"div"> & { delay?: number; y?: number }) {
  const reduced = useReducedMotion();
  return (
    <motion.div
      initial={reduced ? false : { opacity: 0, y }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.42, delay, ease: EASE_OUT }}
      className={className}
      {...props}
    >
      {children}
    </motion.div>
  );
}

/** Staggers direct children so a list reads as arriving, not appearing at once. */
export function Stagger({
  children,
  className,
  gap = 0.055,
  ...props
}: HTMLMotionProps<"div"> & { gap?: number }) {
  const reduced = useReducedMotion();
  return (
    <motion.div
      initial="hidden"
      animate="show"
      variants={{
        hidden: {},
        show: { transition: { staggerChildren: reduced ? 0 : gap } },
      }}
      className={className}
      {...props}
    >
      {children}
    </motion.div>
  );
}

export function StaggerItem({ children, className, ...props }: HTMLMotionProps<"div">) {
  return (
    <motion.div
      variants={{
        hidden: { opacity: 0, y: 12 },
        show: { opacity: 1, y: 0, transition: { duration: 0.4, ease: EASE_OUT } },
      }}
      className={className}
      {...props}
    >
      {children}
    </motion.div>
  );
}

// --------------------------------------------------------------------------- //
// Animated number
// --------------------------------------------------------------------------- //
/**
 * Counts to `value` when scrolled into view.
 *
 * The animation is the point: a KPI that counts up tells you it was *computed*,
 * not typed. Formatting stays with the caller so currency/percent rules live in
 * one place.
 */
export function AnimatedNumber({
  value,
  format,
  duration = 0.9,
  className,
}: {
  value: number;
  format: (n: number) => string;
  duration?: number;
  className?: string;
}) {
  const reduced = useReducedMotion();
  const ref = React.useRef<HTMLSpanElement>(null);
  const inView = useInView(ref, { once: true, margin: "-40px" });
  const [display, setDisplay] = React.useState(reduced ? value : 0);

  React.useEffect(() => {
    if (reduced) {
      setDisplay(value);
      return;
    }
    if (!inView) return;

    let frame = 0;
    const start = performance.now();
    const from = 0;
    const tick = (now: number) => {
      const progress = Math.min((now - start) / (duration * 1000), 1);
      // Ease-out cubic: fast first, settles precisely on the real figure.
      const eased = 1 - (1 - progress) ** 3;
      setDisplay(from + (value - from) * eased);
      if (progress < 1) frame = requestAnimationFrame(tick);
      else setDisplay(value);
    };
    frame = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(frame);
  }, [inView, value, duration, reduced]);

  return (
    <span ref={ref} className={cn("tnum", className)}>
      {format(display)}
    </span>
  );
}

// --------------------------------------------------------------------------- //
// Live indicator
// --------------------------------------------------------------------------- //
export function LivePulse({
  className,
  tone = "primary",
}: {
  className?: string;
  tone?: "primary" | "success" | "warning" | "destructive";
}) {
  const toneClass = {
    primary: "bg-primary",
    success: "bg-success",
    warning: "bg-warning",
    destructive: "bg-destructive",
  }[tone];
  return (
    <span className={cn("relative flex h-2 w-2", className)}>
      <span className={cn("absolute inline-flex h-full w-full rounded-full opacity-60 animate-pulse-ring", toneClass)} />
      <span className={cn("relative inline-flex h-2 w-2 rounded-full", toneClass)} />
    </span>
  );
}

// --------------------------------------------------------------------------- //
// Hover lift
// --------------------------------------------------------------------------- //
export function HoverLift({
  children,
  className,
  disabled,
  ...props
}: HTMLMotionProps<"div"> & { disabled?: boolean }) {
  const reduced = useReducedMotion();
  return (
    <motion.div
      whileHover={reduced || disabled ? undefined : { y: -3 }}
      transition={{ duration: 0.22, ease: EASE_OUT }}
      className={className}
      {...props}
    >
      {children}
    </motion.div>
  );
}

export { motion };
