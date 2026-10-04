import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { ProjectDetailScreen } from "@/app/(app)/projects/[id]/project-detail-screen";
import { PERMISSION } from "@/lib/can";

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn(), replace: vi.fn() }),
}));

function renderScreen(permissions: string[]) {
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string) =>
      String(url).endsWith("/projects/p1")
        ? Response.json({
            id: "p1",
            name: "Proj",
            repoUrl: "https://x/y",
            branch: "main",
            status: "ready",
            permissions,
          })
        : Response.json({ items: [], total: 0 }),
    ),
  );
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <ProjectDetailScreen id="p1" />
    </QueryClientProvider>,
  );
}

afterEach(() => {
  vi.unstubAllGlobals();
  window.location.hash = "";
});

describe("ProjectDetailScreen tabs", () => {
  it("opens the Eval tab when the URL hash is #eval", async () => {
    window.location.hash = "#eval";
    renderScreen([PERMISSION.EVAL_READ]);
    const tab = await screen.findByRole("tab", { name: "Eval" });
    expect(tab).toHaveAttribute("aria-selected", "true");
  });

  it("stays on Overview when the hash names a tab the caller cannot see", async () => {
    window.location.hash = "#eval";
    renderScreen([]);
    const tab = await screen.findByRole("tab", { name: "Overview" });
    expect(tab).toHaveAttribute("aria-selected", "true");
  });
});
