import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { PasswordSection } from "@/components/profile/password-section";
import { SessionProvider } from "@/components/layout/session-context";
import type { UserResponse } from "@/lib/api/types";

const { toastSuccess, toastError } = vi.hoisted(() => ({
  toastSuccess: vi.fn(),
  toastError: vi.fn(),
}));

vi.mock("sonner", () => ({
  toast: { success: toastSuccess, error: toastError },
}));

const user = { id: "u1", name: "Dev", email: "dev@example.com" } as UserResponse;

const POLICY_RESPONSE = Response.json({ minLength: 12, maxBytes: 72 });

function renderSection(resetEnabled: boolean) {
  return render(
    <QueryClientProvider client={new QueryClient()}>
      <SessionProvider user={user}>
        <PasswordSection resetEnabled={resetEnabled} />
      </SessionProvider>
    </QueryClientProvider>,
  );
}

/** Every call routed by URL, so the password-policy read and the reset request coexist. */
function stubFetch(resetResponse: () => Response) {
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string) => {
      if (url.includes("password-policy")) return POLICY_RESPONSE.clone();
      return resetResponse();
    }),
  );
}

afterEach(() => {
  vi.unstubAllGlobals();
  toastSuccess.mockClear();
  toastError.mockClear();
});

describe("PasswordSection", () => {
  it("offers a reset link only when mail is on", () => {
    stubFetch(() => new Response(null, { status: 202 }));
    const { unmount } = renderSection(true);
    expect(
      screen.getByRole("button", { name: /email me a reset link/i }),
    ).toBeInTheDocument();
    unmount();

    renderSection(false);
    expect(screen.queryByRole("button", { name: /email me a reset link/i })).toBeNull();
  });

  it("keeps the change-password fields", () => {
    stubFetch(() => new Response(null, { status: 202 }));
    renderSection(false);
    expect(screen.getByLabelText(/current password/i)).toBeInTheDocument();
  });

  it("shows the neutral success toast on a 202", async () => {
    stubFetch(() => new Response(null, { status: 202 }));
    renderSection(true);
    fireEvent.click(screen.getByRole("button", { name: /email me a reset link/i }));

    await waitFor(() =>
      expect(toastSuccess).toHaveBeenCalledWith(
        "If mail can reach you, a reset link is on its way.",
      ),
    );
    expect(toastError).not.toHaveBeenCalled();
  });

  it("shows the same neutral success toast on a 429 RATE_LIMITED, not an error", async () => {
    stubFetch(
      () =>
        new Response(
          JSON.stringify({
            detail: { code: "RATE_LIMITED", message: "Too many requests" },
          }),
          { status: 429 },
        ),
    );
    renderSection(true);
    fireEvent.click(screen.getByRole("button", { name: /email me a reset link/i }));

    await waitFor(() =>
      expect(toastSuccess).toHaveBeenCalledWith(
        "If mail can reach you, a reset link is on its way.",
      ),
    );
    expect(toastError).not.toHaveBeenCalled();
  });

  it("shows the server's own message on a 409 PASSWORD_RESET_UNAVAILABLE", async () => {
    stubFetch(
      () =>
        new Response(
          JSON.stringify({
            detail: {
              code: "PASSWORD_RESET_UNAVAILABLE",
              message: "Ask an administrator.",
            },
          }),
          { status: 409 },
        ),
    );
    renderSection(true);
    fireEvent.click(screen.getByRole("button", { name: /email me a reset link/i }));

    await waitFor(() =>
      expect(toastError).toHaveBeenCalledWith("Ask an administrator."),
    );
    expect(toastSuccess).not.toHaveBeenCalled();
  });
});
