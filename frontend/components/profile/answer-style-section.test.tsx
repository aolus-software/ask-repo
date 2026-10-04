import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { AnswerStyleSection } from "@/components/profile/answer-style-section";
import type { AnswerStyle } from "@/lib/api/types";

const { toastSuccess } = vi.hoisted(() => ({ toastSuccess: vi.fn() }));
vi.mock("sonner", () => ({ toast: { success: toastSuccess, error: vi.fn() } }));

const SAVED: AnswerStyle = { detail: "brief", familiarity: null, format: null };

function renderSection() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <AnswerStyleSection />
    </QueryClientProvider>,
  );
}

afterEach(() => {
  vi.unstubAllGlobals();
  toastSuccess.mockClear();
});

describe("AnswerStyleSection", () => {
  it("shows the saved values, with Default for an unset dial", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => Response.json(SAVED)),
    );
    renderSection();

    const brief = await screen.findByRole("radio", { name: "Brief" });
    await waitFor(() => expect(brief).toHaveAttribute("aria-checked", "true"));
    expect(screen.getByRole("radiogroup", { name: "Familiarity" })).toBeInTheDocument();
    const defaults = screen.getAllByRole("radio", { name: "Default" });
    expect(
      defaults.filter((r) => r.getAttribute("aria-checked") === "true"),
    ).toHaveLength(2);
  });

  it("sends null for Default and every key on save", async () => {
    const fetchMock = vi.fn(async (_url: string, init?: RequestInit) =>
      init?.method === "PUT"
        ? Response.json(JSON.parse(String(init.body)))
        : Response.json(SAVED),
    );
    vi.stubGlobal("fetch", fetchMock);
    renderSection();

    fireEvent.click(await screen.findByRole("radio", { name: "Bullets" }));
    fireEvent.click(screen.getAllByRole("radio", { name: "Default" })[0]);
    fireEvent.click(screen.getByRole("button", { name: /save answer style/i }));

    await waitFor(() =>
      expect(toastSuccess).toHaveBeenCalledWith("Answer style saved"),
    );
    const put = fetchMock.mock.calls.find(([, init]) => init?.method === "PUT");
    expect(JSON.parse(String(put?.[1]?.body))).toEqual({
      detail: null,
      familiarity: null,
      format: "bullets",
    });
  });

  it("says it never changes the shared checklist", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => Response.json(SAVED)),
    );
    renderSection();

    expect(
      await screen.findByText(/never changes the QA Checklist or Mock Data/),
    ).toBeInTheDocument();
  });
});
