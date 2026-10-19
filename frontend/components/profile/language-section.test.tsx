import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { LanguageSection } from "@/components/profile/language-section";
import { ENDONYMS, LANGUAGES } from "@/lib/i18n/languages";

const { toastSuccess, refresh } = vi.hoisted(() => ({
  toastSuccess: vi.fn(),
  refresh: vi.fn(),
}));
vi.mock("sonner", () => ({ toast: { success: toastSuccess, error: vi.fn() } }));
vi.mock("next/navigation", () => ({ useRouter: () => ({ refresh }) }));

function stubFetch(stored: { language: string | null }) {
  const fetchMock = vi.fn(async (_url: string, init?: RequestInit) =>
    init?.method === "PUT"
      ? Response.json(JSON.parse(String(init.body)))
      : Response.json(stored),
  );
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

function putBody(fetchMock: ReturnType<typeof stubFetch>) {
  const put = fetchMock.mock.calls.find(([, init]) => init?.method === "PUT");
  return JSON.parse(String(put?.[1]?.body));
}

function renderSection() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <LanguageSection />
    </QueryClientProvider>,
  );
}

afterEach(() => {
  vi.unstubAllGlobals();
  toastSuccess.mockClear();
  refresh.mockClear();
});

describe("LanguageSection", () => {
  it("checks Browser default when no language was ever chosen", async () => {
    stubFetch({ language: null });
    renderSection();

    const radio = await screen.findByRole("radio", { name: "Browser default" });
    await waitFor(() => expect(radio).toHaveAttribute("aria-checked", "true"));
  });

  it("offers every language by its own name", async () => {
    stubFetch({ language: null });
    renderSection();

    for (const code of LANGUAGES) {
      expect(
        await screen.findByRole("radio", { name: ENDONYMS[code] }),
      ).toBeInTheDocument();
    }
  });

  it("saves the chosen language, toasts and refreshes the route", async () => {
    const fetchMock = stubFetch({ language: null });
    renderSection();

    await screen.findByRole("radio", { name: "日本語" });
    fireEvent.click(screen.getByRole("radio", { name: "日本語" }));
    fireEvent.click(screen.getByRole("button", { name: "Save language" }));

    await waitFor(() => expect(toastSuccess).toHaveBeenCalledWith("Language saved"));
    expect(putBody(fetchMock)).toEqual({ language: "ja" });
    expect(refresh).toHaveBeenCalled();
  });

  it("sends null for Browser default", async () => {
    const fetchMock = stubFetch({ language: "ko" });
    renderSection();

    const ko = await screen.findByRole("radio", { name: "한국어" });
    await waitFor(() => expect(ko).toHaveAttribute("aria-checked", "true"));
    fireEvent.click(screen.getByRole("radio", { name: "Browser default" }));
    fireEvent.click(screen.getByRole("button", { name: "Save language" }));

    await waitFor(() => expect(toastSuccess).toHaveBeenCalled());
    expect(putBody(fetchMock)).toEqual({ language: null });
  });

  it("keeps Save disabled until loaded and while nothing changed", async () => {
    let release: (value: Response) => void = () => {};
    const gate = new Promise<Response>((resolve) => {
      release = resolve;
    });
    vi.stubGlobal(
      "fetch",
      vi.fn(() => gate),
    );
    renderSection();

    expect(screen.getByRole("button", { name: "Save language" })).toBeDisabled();
    release(Response.json({ language: "id" }));

    const radio = await screen.findByRole("radio", { name: "Bahasa Indonesia" });
    await waitFor(() => expect(radio).toHaveAttribute("aria-checked", "true"));
    expect(screen.getByRole("button", { name: "Save language" })).toBeDisabled();
    fireEvent.click(screen.getByRole("radio", { name: "English" }));
    expect(screen.getByRole("button", { name: "Save language" })).toBeEnabled();
  });
});
