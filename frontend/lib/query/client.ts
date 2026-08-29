import { QueryClient } from "@tanstack/react-query";

import { isApiError } from "@/lib/api/errors";

/**
 * The QueryClient factory, in a module with **no** `"use client"` directive.
 *
 * It lives apart from `provider.tsx` deliberately: that file is a client module, so
 * everything it exports is client-only, and a Server Component calling one gets
 * "Attempted to call makeQueryClient() from the server". Server Components need this
 * to prefetch into a client that is then dehydrated onto the page, so the factory has
 * to be reachable from both sides.
 */
export function makeQueryClient(): QueryClient {
  return new QueryClient({
    defaultOptions: {
      queries: {
        staleTime: 30_000,
        // Retrying a 403 three times produces three identical failures and delays
        // the message the operator needs.
        retry: (failureCount, error) => {
          if (isApiError(error) && error.status >= 400 && error.status < 500) return false;
          return failureCount < 1;
        },
        refetchOnWindowFocus: true,
      },
      mutations: { retry: false },
    },
  });
}
