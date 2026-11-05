import { useQuery, useQueryClient } from "@tanstack/react-query";
import * as React from "react";

import { apiGet } from "@/lib/api/client";
import type { Shelf } from "@/types/shelf";

const KEY = ["gear-shelf"];

/** The gear shelf. The backend caches Channel3 results for 30 minutes, so this is cheap to refetch. */
export function useShelf() {
  return useQuery({
    queryKey: KEY,
    queryFn: () => apiGet<Shelf>("/integrations/shelf"),
    staleTime: 5 * 60_000,
  });
}

/** Bypass the backend cache - spends one Channel3 search per shelf slot. */
export function useRefreshShelf() {
  const client = useQueryClient();
  const [pending, setPending] = React.useState(false);
  const refresh = React.useCallback(async () => {
    setPending(true);
    try {
      const fresh = await apiGet<Shelf>("/integrations/shelf", { params: { refresh: true } });
      client.setQueryData(KEY, fresh);
    } finally {
      setPending(false);
    }
  }, [client]);
  return { refresh, pending };
}
