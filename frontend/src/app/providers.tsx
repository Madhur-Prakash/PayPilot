"use client";

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { ThemeProvider } from "next-themes";
import * as React from "react";
import { Toaster } from "sonner";

import { TooltipProvider } from "@/components/ui/primitives";
import { ApiError } from "@/lib/api/client";
import { QUERY_STALE_TIME_MS } from "@/lib/constants/config";
import { installUnauthorizedHandler, useAuthStore } from "@/stores/auth";

function makeQueryClient() {
  return new QueryClient({
    defaultOptions: {
      queries: {
        staleTime: QUERY_STALE_TIME_MS,
        refetchOnWindowFocus: false,
        retry: (failureCount, error) => {
          // Never retry a decision the server already made: an auth or permission
          // failure will fail identically every time and just delays the message.
          if (error instanceof ApiError && !error.isRetryable) return false;
          return failureCount < 2;
        },
      },
      mutations: { retry: false },
    },
  });
}

export function Providers({ children }: { children: React.ReactNode }) {
  const [queryClient] = React.useState(makeQueryClient);
  const bootstrap = useAuthStore((s) => s.bootstrap);
  const status = useAuthStore((s) => s.status);

  React.useEffect(() => {
    installUnauthorizedHandler();
  }, []);

  React.useEffect(() => {
    // Exchange the HttpOnly refresh cookie for an access token on first paint.
    if (status === "idle") void bootstrap();
  }, [status, bootstrap]);

  return (
    <ThemeProvider attribute="class" defaultTheme="light" enableSystem disableTransitionOnChange>
      <QueryClientProvider client={queryClient}>
        <TooltipProvider delayDuration={200}>
          {children}
          <Toaster position="bottom-right" closeButton richColors />
        </TooltipProvider>
      </QueryClientProvider>
    </ThemeProvider>
  );
}
