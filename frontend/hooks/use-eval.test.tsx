import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { renderHook, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";

import {
  useDeleteEvalSet,
  useSetPairExcluded,
  useStartEvalRun,
} from "@/hooks/use-eval";

function setup() {
  const fetchMock = vi.fn(async () => Response.json({}));
  vi.stubGlobal("fetch", fetchMock);
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const invalidate = vi.spyOn(client, "invalidateQueries");
  const wrapper = ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={client}>{children}</QueryClientProvider>
  );
  return { fetchMock, invalidate, wrapper };
}

function call(fetchMock: ReturnType<typeof vi.fn>) {
  const [url, init] = fetchMock.mock.calls[0] as unknown as [string, RequestInit];
  return { url, init };
}

afterEach(() => vi.unstubAllGlobals());

describe("eval mutations", () => {
  it("useStartEvalRun POSTs the set's runs and refreshes runs and sets", async () => {
    const { fetchMock, invalidate, wrapper } = setup();
    const { result } = renderHook(() => useStartEvalRun("s1", "p1"), { wrapper });
    result.current.mutate();
    await waitFor(() => expect(invalidate).toHaveBeenCalledTimes(2));
    const { url, init } = call(fetchMock);
    expect(url).toContain("/api/eval-sets/s1/runs");
    expect(init.method).toBe("POST");
    const keysInvalidated = invalidate.mock.calls.map((c) => c[0]?.queryKey);
    expect(keysInvalidated).toContainEqual(["eval", "runs", "s1"]);
    expect(keysInvalidated).toContainEqual(["eval", "sets", "p1"]);
  });

  it("useSetPairExcluded PUTs the flag and refreshes the set", async () => {
    const { fetchMock, invalidate, wrapper } = setup();
    const { result } = renderHook(() => useSetPairExcluded("s1"), { wrapper });
    result.current.mutate({ pairId: "x", excluded: true });
    await waitFor(() => expect(invalidate).toHaveBeenCalled());
    const { url, init } = call(fetchMock);
    expect(url).toContain("/api/eval-pairs/x/excluded");
    expect(init.method).toBe("PUT");
    expect(JSON.parse(init.body as string)).toEqual({ excluded: true });
    expect(invalidate.mock.calls[0][0]?.queryKey).toEqual(["eval", "set", "s1"]);
  });

  it("useDeleteEvalSet DELETEs the set and refreshes the project's sets", async () => {
    const { fetchMock, invalidate, wrapper } = setup();
    fetchMock.mockImplementation(async () => new Response(null, { status: 204 }));
    const { result } = renderHook(() => useDeleteEvalSet("p1"), { wrapper });
    result.current.mutate("s1");
    await waitFor(() => expect(invalidate).toHaveBeenCalled());
    const { url, init } = call(fetchMock);
    expect(url).toContain("/api/eval-sets/s1");
    expect(init.method).toBe("DELETE");
    expect(invalidate.mock.calls[0][0]?.queryKey).toEqual(["eval", "sets", "p1"]);
  });
});
