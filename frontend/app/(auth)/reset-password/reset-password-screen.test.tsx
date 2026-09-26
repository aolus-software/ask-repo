import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { ResetPasswordScreen } from "@/app/(auth)/reset-password/reset-password-screen";

vi.mock("next/navigation", () => ({ useRouter: () => ({ push: vi.fn() }) }));

beforeEach(() => {
  vi.stubGlobal(
    "fetch",
    vi.fn(async () => Response.json({ minLength: 12, maxBytes: 72 })),
  );
});
afterEach(() => {
  vi.unstubAllGlobals();
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
});
