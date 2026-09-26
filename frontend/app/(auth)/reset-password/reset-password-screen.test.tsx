import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { ResetPasswordScreen } from "@/app/(auth)/reset-password/reset-password-screen";

let fetchMock: ReturnType<typeof vi.fn>;

beforeEach(() => {
  fetchMock = vi.fn(async () => Response.json({ minLength: 12, maxBytes: 72 }));
  vi.stubGlobal("fetch", fetchMock);
});
const REAL_LOCATION = window.location;

afterEach(() => {
  vi.unstubAllGlobals();
  Object.defineProperty(window, "location", {
    configurable: true,
    value: REAL_LOCATION,
  });
  window.history.replaceState(null, "", "/");
});

function renderScreen() {
  const client = new QueryClient();
  return render(
    <QueryClientProvider client={client}>
      <ResetPasswordScreen />
    </QueryClientProvider>,
  );
}

describe("ResetPasswordScreen", () => {
  it("offers the form when the fragment carries a token", async () => {
    window.history.replaceState(null, "", "/reset-password#token=abc");
    renderScreen();
    expect(
      await screen.findByRole("button", { name: /set password/i }),
    ).toBeInTheDocument();
  });

  it("ignores a token in the query string", async () => {
    window.history.replaceState(null, "", "/reset-password?token=abc");
    renderScreen();
    expect(
      await screen.findByText(/this link is missing its token/i),
    ).toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: /set password/i }),
    ).not.toBeInTheDocument();
  });

  it("strips the token from the address bar once it has been read", async () => {
    window.history.replaceState(null, "", "/reset-password#token=abc");
    renderScreen();
    await screen.findByRole("button", { name: /set password/i });
    await waitFor(() => expect(window.location.hash).toBe(""));
    expect(window.location.pathname).toBe("/reset-password");
  });

  it("logs out locally and sends the visitor to a login screen that carries the success message", async () => {
    window.history.replaceState(null, "", "/reset-password#token=abc");
    const originalLocation = window.location;
    Object.defineProperty(window, "location", {
      configurable: true,
      value: { ...originalLocation, href: originalLocation.href },
    });

    renderScreen();
    const user = userEvent.setup();
    await user.type(
      await screen.findByLabelText(/new password/i),
      "a-perfectly-fine-passphrase",
    );
    await user.click(screen.getByRole("button", { name: /set password/i }));

    await waitFor(() => expect(window.location.href).toContain("/login?reset=1"));
    const calledPaths = fetchMock.mock.calls.map(([input]) => String(input));
    expect(calledPaths).toContain("/api/auth/logout");
  });
});
