"use client";

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { useState } from "react";

import { isApiError } from "@/lib/api/errors";

export function makeQueryClient(): QueryClient {
  return new QueryClient({
    defaultOptions: {
      queries: {
        staleTime: 30_000,
        // Retrying a 403 three times produces three identical failures and delays
        // the message the operator needs.
        retry: (failureCount, error) => {
          if (isApiError(error) && error.status >= 400 && error.status < 500)
            return false;
          return failureCount < 1;
        },
        refetchOnWindowFocus: true,
      },
      mutations: { retry: false },
    },
  });
}

export function QueryProvider({ children }: { children: React.ReactNode }) {
  // useState, not a module singleton: one client per browser session, and never
  // shared between requests on the server.
  const [client] = useState(makeQueryClient);
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}
