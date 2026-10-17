import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { ExportScreen } from "@/app/(app)/checklist/export/export-screen";
import { PERMISSION } from "@/lib/can";

const push = vi.fn();

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push, replace: vi.fn() }),
  useSearchParams: () => new URLSearchParams("projectId=p1"),
}));

const MODULES = [
  { id: "m1", projectId: "p1", name: "Auth" },
  { id: "m2", projectId: "p1", name: "Billing" },
];

function renderScreen(permissions: string[]) {
  const fetchMock = vi.fn(async (url: string) => {
    const path = String(url);
    if (path.startsWith("/api/projects/p1/export")) {
      return new Response("bytes", {
        headers: { "content-disposition": 'attachment; filename="qa-checklist.xlsx"' },
      });
    }
    if (path.startsWith("/api/projects")) {
      return Response.json({
        items: [{ id: "p1", name: "api", status: "ready", permissions }],
        page: 1,
        limit: 100,
        totalCount: 1,
        totalPages: 1,
      });
    }
    return Response.json({
      items: MODULES,
      page: 1,
      limit: 100,
      totalCount: MODULES.length,
      totalPages: 1,
    });
  });
  vi.stubGlobal("fetch", fetchMock);
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={client}>
      <ExportScreen />
    </QueryClientProvider>,
  );
  return fetchMock;
}

function exportCalls(fetchMock: ReturnType<typeof vi.fn>): string[] {
  return fetchMock.mock.calls
    .map(([url]) => String(url))
    .filter((url) => url.startsWith("/api/projects/p1/export"));
}

afterEach(() => {
  vi.unstubAllGlobals();
  push.mockReset();
});

describe("ExportScreen", () => {
  it("disables a part the caller's role cannot read", async () => {
    renderScreen([PERMISSION.CHECKLIST_READ]);

    expect(await screen.findByRole("checkbox", { name: "Mock data" })).toHaveAttribute(
      "data-disabled",
    );
    expect(
      screen.getByRole("checkbox", { name: "Test checklist" }),
    ).not.toHaveAttribute("data-disabled");
  });

  it("asks for a module before exporting a chosen set", async () => {
    const fetchMock = renderScreen([PERMISSION.CHECKLIST_READ]);
    fireEvent.click(await screen.findByRole("radio", { name: "Choose modules" }));
    await screen.findByRole("checkbox", { name: "Billing" });

    fireEvent.click(screen.getByRole("button", { name: "Export" }));

    expect(await screen.findByText("Choose at least one module.")).toBeInTheDocument();
    expect(exportCalls(fetchMock)).toEqual([]);
  });

  it("exports the chosen modules and returns to the list", async () => {
    URL.createObjectURL = vi.fn(() => "blob:x");
    URL.revokeObjectURL = vi.fn();
    const fetchMock = renderScreen([
      PERMISSION.CHECKLIST_READ,
      PERMISSION.MOCKDATA_READ,
    ]);
    fireEvent.click(await screen.findByRole("radio", { name: "Choose modules" }));
    fireEvent.click(await screen.findByRole("checkbox", { name: "Billing" }));

    fireEvent.click(screen.getByRole("button", { name: "Export" }));

    await waitFor(() =>
      expect(exportCalls(fetchMock)).toEqual([
        "/api/projects/p1/export?include=checklist&moduleIds=m2",
      ]),
    );
    await waitFor(() => expect(push).toHaveBeenCalledWith("/checklist?projectId=p1"));
  });
});
