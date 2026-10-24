import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import { ContentLanguageSection } from "@/components/projects/content-language-section";
import type { ProjectResponse } from "@/lib/api/types";

const { toastSuccess } = vi.hoisted(() => ({ toastSuccess: vi.fn() }));
vi.mock("sonner", () => ({ toast: { success: toastSuccess, error: vi.fn() } }));

function project(permissions: string[]): ProjectResponse {
  return {
    id: "p1",
    contentLanguage: "en",
    permissions,
  } as unknown as ProjectResponse;
}

function renderSection(p: ProjectResponse) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <ContentLanguageSection project={p} />
    </QueryClientProvider>,
  );
}

afterEach(() => {
  vi.unstubAllGlobals();
  toastSuccess.mockClear();
});

describe("ContentLanguageSection", () => {
  it("saves the chosen language with project.update", async () => {
    const fetchMock = vi.fn(async (_url: string, init?: RequestInit) =>
      Response.json({ ...project([]), ...JSON.parse(String(init?.body)) }),
    );
    vi.stubGlobal("fetch", fetchMock);
    renderSection(project(["project.update"]));

    expect(screen.getByRole("button", { name: "Save" })).toBeDisabled();
    const user = userEvent.setup();
    await user.click(screen.getByRole("combobox"));
    await user.click(await screen.findByRole("option", { name: "日本語" }));
    await user.click(screen.getByRole("button", { name: "Save" }));

    await waitFor(() =>
      expect(toastSuccess).toHaveBeenCalledWith("Content language saved"),
    );
    const [url, init] = fetchMock.mock.calls[0];
    expect(String(url)).toContain("/projects/p1");
    expect(init?.method).toBe("PATCH");
    expect(JSON.parse(String(init?.body))).toEqual({ contentLanguage: "ja" });
  });

  it("is read-only without project.update", () => {
    renderSection(project([]));

    expect(screen.getByText("Content is written in English.")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Save" })).not.toBeInTheDocument();
    expect(screen.queryByRole("combobox")).not.toBeInTheDocument();
  });
});
