import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import { EvalPairTable } from "@/components/eval/eval-pair-table";
import type { EvalPair } from "@/lib/api/types";

const PAIR: EvalPair = {
  id: "p1",
  position: 1,
  questionType: "explain",
  question: "How does login work?",
  referenceAnswer: "It checks the password hash.",
  sourceFile: "app/auth.py",
  startLine: 10,
  endLine: 40,
  excluded: false,
};

function renderTable(canRun: boolean) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <EvalPairTable setId="s1" pairs={[PAIR]} canRun={canRun} />
    </QueryClientProvider>,
  );
}

afterEach(() => vi.unstubAllGlobals());

describe("EvalPairTable", () => {
  it("shows the exclude switch only with eval.run", () => {
    renderTable(false);
    expect(screen.queryByRole("switch")).not.toBeInTheDocument();
  });

  it("PUTs the exclusion when toggled", async () => {
    const fetchMock = vi.fn(async () => Response.json({ ...PAIR, excluded: true }));
    vi.stubGlobal("fetch", fetchMock);
    renderTable(true);

    await userEvent.click(screen.getByRole("switch"));

    await waitFor(() => expect(fetchMock).toHaveBeenCalled());
    const [url, init] = fetchMock.mock.calls[0] as unknown as [string, RequestInit];
    expect(url).toContain("/api/eval-pairs/p1/excluded");
    expect(init.method).toBe("PUT");
    expect(JSON.parse(init.body as string)).toEqual({ excluded: true });
  });

  it("expands the reference answer on click", async () => {
    renderTable(false);
    expect(screen.queryByText("It checks the password hash.")).not.toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: /how does login work/i }));
    expect(await screen.findByText("It checks the password hash.")).toBeVisible();
  });
});
