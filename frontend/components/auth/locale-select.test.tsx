import userEvent from "@testing-library/user-event";
import { render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { LocaleSelect } from "@/components/auth/locale-select";

const { refresh, toastError } = vi.hoisted(() => ({
  refresh: vi.fn(),
  toastError: vi.fn(),
}));
vi.mock("next/navigation", () => ({ useRouter: () => ({ refresh }) }));
vi.mock("sonner", () => ({ toast: { error: toastError } }));

afterEach(() => {
  vi.unstubAllGlobals();
  refresh.mockClear();
  toastError.mockClear();
});

describe("LocaleSelect", () => {
  it("posts the chosen language to the locale route and refreshes", async () => {
    const fetchMock = vi.fn(async () => new Response(null, { status: 204 }));
    vi.stubGlobal("fetch", fetchMock);
    render(<LocaleSelect />);

    const user = userEvent.setup();
    await user.click(screen.getByRole("combobox", { name: "Language" }));
    await user.click(await screen.findByRole("option", { name: "Bahasa Melayu" }));

    await waitFor(() => expect(refresh).toHaveBeenCalled());
    const [url, init] = fetchMock.mock.calls[0] as unknown as [string, RequestInit];
    expect(url).toBe("/api/auth/locale");
    expect(init.method).toBe("POST");
    expect(JSON.parse(String(init.body))).toEqual({ language: "ms" });
  });

  it.each([
    ["a refused request", async () => new Response(null, { status: 500 })],
    [
      "a network error",
      async () => {
        throw new TypeError("Failed to fetch");
      },
    ],
  ])("toasts and does not refresh on %s", async (_label, impl) => {
    vi.stubGlobal("fetch", vi.fn(impl));
    render(<LocaleSelect />);

    const user = userEvent.setup();
    await user.click(screen.getByRole("combobox", { name: "Language" }));
    await user.click(await screen.findByRole("option", { name: "Bahasa Melayu" }));

    await waitFor(() =>
      expect(toastError).toHaveBeenCalledWith("Something went wrong. Please try again."),
    );
    expect(refresh).not.toHaveBeenCalled();
  });
});
