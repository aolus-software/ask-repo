import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { PreferencesScreen } from "@/components/notifications/preferences-screen";
import type { NotificationPreferencesResponse } from "@/lib/api/types";

const { toastSuccess, toastError } = vi.hoisted(() => ({
  toastSuccess: vi.fn(),
  toastError: vi.fn(),
}));

vi.mock("sonner", () => ({
  toast: { success: toastSuccess, error: toastError },
}));

const PREFERENCES: NotificationPreferencesResponse = {
  items: [{ eventType: "project.ready", inApp: true, email: false }],
  emailEnabled: true,
};

function renderScreen() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <PreferencesScreen />
    </QueryClientProvider>,
  );
}

/** The row's own switch, named via `aria-labelledby` from "A project finished
 * indexing" -- `project.ready`'s category title (`lib/notifications.ts`). Toggling
 * it is enough to enable Save. */
async function toggleFirstRow() {
  fireEvent.click(
    await screen.findByRole("switch", { name: "A project finished indexing" }),
  );
}

afterEach(() => {
  vi.unstubAllGlobals();
  toastSuccess.mockClear();
  toastError.mockClear();
});

describe("PreferencesScreen", () => {
  it("toasts on a successful save", async () => {
    const fetchMock = vi.fn(async (_url: string, init?: RequestInit) =>
      init?.method === "PUT"
        ? new Response(null, { status: 204 })
        : Response.json(PREFERENCES),
    );
    vi.stubGlobal("fetch", fetchMock);
    renderScreen();

    await toggleFirstRow();
    fireEvent.click(screen.getByRole("button", { name: /save preferences/i }));

    await waitFor(() => expect(toastSuccess).toHaveBeenCalledWith("Preferences saved"));
    expect(toastError).not.toHaveBeenCalled();
  });

  it("shows a form-level alert, and no toast, when the save fails", async () => {
    const fetchMock = vi.fn(async (_url: string, init?: RequestInit) =>
      init?.method === "PUT"
        ? new Response(
            JSON.stringify({
              detail: { code: "INTERNAL_ERROR", message: "Could not save that." },
            }),
            { status: 500 },
          )
        : Response.json(PREFERENCES),
    );
    vi.stubGlobal("fetch", fetchMock);
    renderScreen();

    await toggleFirstRow();
    fireEvent.click(screen.getByRole("button", { name: /save preferences/i }));

    expect(await screen.findByText("Could not save that.")).toBeInTheDocument();
    expect(toastSuccess).not.toHaveBeenCalled();
    expect(toastError).not.toHaveBeenCalled();
  });
});
