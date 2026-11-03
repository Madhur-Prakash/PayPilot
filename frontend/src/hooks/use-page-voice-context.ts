"use client";

/**
 * Lets a page tell the voice assistant what's actually on screen.
 *
 * Call it with a short, current sentence ("Revenue up 12%, 3 items low on
 * stock…") built from the same data the page already rendered - never a
 * second fetch. While a call is live and the merchant is on this route, the
 * store forwards it to the assistant as a system message, so it can answer
 * "what am I looking at" or reference a number without another tool round-trip.
 *
 * Pass `null` while the data is still loading so the assistant isn't fed a
 * half-formed summary.
 */

import * as React from "react";
import { usePathname } from "next/navigation";

import { useVoiceAgentStore } from "@/stores/voice-agent";

export function usePageVoiceContext(summary: string | null): void {
  const pathname = usePathname();
  const setPageContext = useVoiceAgentStore((s) => s.setPageContext);

  React.useEffect(() => {
    setPageContext(pathname, summary);
    return () => setPageContext(pathname, null);
  }, [pathname, summary, setPageContext]);
}
