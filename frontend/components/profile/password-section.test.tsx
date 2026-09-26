import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { PasswordSection } from "@/components/profile/password-section";
import { SessionProvider } from "@/components/layout/session-context";
import type { UserResponse } from "@/lib/api/types";

const user = { id: "u1", name: "Dev", email: "dev@example.com" } as UserResponse;

function renderSection(resetEnabled: boolean) {
  return render(
    <QueryClientProvider client={new QueryClient()}>
      <SessionProvider user={user}>
        <PasswordSection resetEnabled={resetEnabled} />
      </SessionProvider>
    </QueryClientProvider>,
  );
}

afterEach(() => vi.unstubAllGlobals());

describe("PasswordSection", () => {
  it("offers a reset link only when mail is on", () => {
    // PasswordField reads the password policy on mount; stubbed so the request
    // resolves harmlessly instead of leaving an unhandled rejection in test output.
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => Response.json({ minLength: 12, maxBytes: 72 })),
    );

    const { unmount } = renderSection(true);
    expect(screen.getByRole("button", { name: /email me a reset link/i })).toBeInTheDocument();
    unmount();

    renderSection(false);
    expect(screen.queryByRole("button", { name: /email me a reset link/i })).toBeNull();
  });

  it("keeps the change-password fields", () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => Response.json({ minLength: 12, maxBytes: 72 })),
    );
    renderSection(false);
    expect(screen.getByLabelText(/current password/i)).toBeInTheDocument();
  });
});
