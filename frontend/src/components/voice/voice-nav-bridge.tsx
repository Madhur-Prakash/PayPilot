"use client";

/**
 * Wires the voice store to the router, the same way `installUnauthorizedHandler`
 * wires the auth store to the API client. Mounted once in the dashboard layout;
 * renders nothing.
 */

import { usePathname, useRouter } from "next/navigation";
import * as React from "react";

import { installVoiceNavigator, useVoiceAgentStore } from "@/stores/voice-agent";

export function VoiceNavBridge() {
  const router = useRouter();
  const pathname = usePathname();
  const loadConfig = useVoiceAgentStore((s) => s.loadConfig);
  const setPathname = useVoiceAgentStore((s) => s.setPathname);

  React.useEffect(() => {
    installVoiceNavigator((href) => router.push(href));
  }, [router]);

  React.useEffect(() => {
    void loadConfig();
  }, [loadConfig]);

  React.useEffect(() => {
    setPathname(pathname);
  }, [pathname, setPathname]);

  return null;
}
