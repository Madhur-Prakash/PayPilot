"use client";

/**
 * Topbar entry point: "Talk to Growth Scientist"
 * → navigates directly to the AI Voice Assistant page (/voice).
 */

import { Mic } from "lucide-react";
import Link from "next/link";

import { Button } from "@/components/ui/button";

export function VoiceButton() {
  return (
    <Button
      variant="outline"
      size="sm"
      asChild
      className="gap-2 border-primary/25 bg-primary/5 text-primary hover:bg-primary/10"
    >
      <Link href="/voice">
        <Mic className="h-4 w-4" />
        <span className="hidden sm:inline">Talk to Growth Scientist</span>
        <span className="sm:hidden">Voice</span>
      </Link>
    </Button>
  );
}
