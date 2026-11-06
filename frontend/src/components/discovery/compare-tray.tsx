"use client";

/** A floating tray of the products picked for comparison (2-4), on every discovery screen. */

import { AnimatePresence, motion } from "framer-motion";
import { GitCompareArrows, X } from "lucide-react";
import { useRouter } from "next/navigation";

import { ProductImage } from "@/components/discovery/shared";
import { Button } from "@/components/ui/button";
import { MAX_COMPARE, useCompareStore } from "@/stores/compare";

export function CompareTray() {
  const items = useCompareStore((s) => s.items);
  const remove = useCompareStore((s) => s.remove);
  const clear = useCompareStore((s) => s.clear);
  const router = useRouter();

  return (
    <div className="pointer-events-none fixed inset-x-0 bottom-4 z-40 flex justify-center px-4">
    <AnimatePresence>
      {items.length > 0 && (
        <motion.div initial={{ y: 80, opacity: 0 }} animate={{ y: 0, opacity: 1 }} exit={{ y: 80, opacity: 0 }}
          className="pointer-events-auto w-full max-w-[720px] rounded-2xl border border-border bg-card/95 p-3 shadow-xl backdrop-blur">
          <div className="flex flex-wrap items-center gap-3">
            <div className="flex flex-1 items-center gap-2 overflow-x-auto">
              {items.map((item) => (
                <div key={item.id} className="relative flex w-40 shrink-0 items-center gap-2 rounded-lg border border-border bg-background p-1.5 pr-6">
                  <ProductImage src={item.image_url} alt={item.title} className="h-9 w-9 rounded p-0.5" />
                  <span className="line-clamp-2 text-2xs leading-tight">{item.title}</span>
                  <button type="button" onClick={() => remove(item.id)} aria-label={`Remove ${item.title}`}
                    className="absolute right-1 top-1 rounded p-0.5 text-muted-foreground hover:bg-muted hover:text-foreground">
                    <X className="h-3 w-3" />
                  </button>
                </div>
              ))}
              {Array.from({ length: Math.max(0, 2 - items.length) }).map((_, i) => (
                <div key={i} className="flex h-12 w-40 shrink-0 items-center justify-center rounded-lg border border-dashed border-border text-2xs text-muted-foreground">
                  Pick another product
                </div>
              ))}
            </div>
            <div className="flex items-center gap-1.5">
              <Button size="sm" variant="ghost" onClick={clear}>Clear</Button>
              <Button size="sm" className="gap-1.5" disabled={items.length < 2}
                onClick={() => router.push(`/discovery/compare?ids=${items.map((i) => encodeURIComponent(i.id)).join(",")}`)}>
                <GitCompareArrows className="h-4 w-4" /> Compare {items.length}/{MAX_COMPARE}
              </Button>
            </div>
          </div>
        </motion.div>
      )}
    </AnimatePresence>
    </div>
  );
}
