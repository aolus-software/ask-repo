import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { ForgotPasswordScreen } from "@/app/(auth)/forgot-password/forgot-password-screen";

afterEach(() => vi.unstubAllGlobals());

function renderScreen() {
  const client = new QueryClient({ defaultOptions: { mutations: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <ForgotPasswordScreen />
    </QueryClientProvider>,
  );
}

async function submit(email: string) {
  fireEvent.change(screen.getByLabelText(/email/i), { target: { value: email } });
  fireEvent.click(screen.getByRole("button", { name: /send reset link/i }));
}

describe("ForgotPasswordScreen", () => {
  it.each([202, 429])("shows the same confirmation on %i", async (status) => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () =>
        status === 202
          ? new Response(null, { status })
          : Response.json({ detail: { code: "RATE_LIMITED", message: "slow" } }, { status }),
      ),
    );
    renderScreen();
    await submit("dev@example.com");
    await waitFor(() =>
      expect(screen.getByText(/if that account exists/i)).toBeInTheDocument(),
    );
    expect(screen.queryByText(/slow/i)).not.toBeInTheDocument();
  });

  it("explains when reset is unavailable", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () =>
        Response.json(
          { detail: { code: "PASSWORD_RESET_UNAVAILABLE", message: "Ask an administrator." } },
          { status: 409 },
        ),
      ),
    );
    renderScreen();
    await submit("dev@example.com");
    await waitFor(() => expect(screen.getByText(/ask an administrator/i)).toBeInTheDocument());
  });
});
