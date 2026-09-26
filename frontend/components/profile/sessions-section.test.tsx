import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { SessionsSection } from "@/components/profile/sessions-section";
import { SessionProvider } from "@/components/layout/session-context";
import type { SessionSummary, UserResponse } from "@/lib/api/types";

const user: UserResponse = {
  id: "u1",
  name: "Dev",
  email: "dev@example.com",
  isAdmin: false,
  mustChangePassword: false,
  lastLoginAt: new Date().toISOString(),
  createdAt: new Date().toISOString(),
  updatedAt: new Date().toISOString(),
};

function session(id: string, current: boolean): SessionSummary {
  const now = new Date().toISOString();
  return {
    id,
    userAgent: "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_0) Chrome/129.0 Safari/537.36",
    ipAddress: "203.0.113.9",
    startedAt: now,
    lastActiveAt: now,
    expiresAt: now,
    current,
  };
}

function renderSection() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <SessionProvider user={user}>
        <SessionsSection />
      </SessionProvider>
    </QueryClientProvider>,
  );
}

afterEach(() => vi.unstubAllGlobals());

describe("SessionsSection", () => {
  it("marks the current session and names the device", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => Response.json([session("a", true)])));
    renderSection();
    expect(await screen.findByText("This device")).toBeInTheDocument();
    expect(screen.getByText("Chrome on macOS")).toBeInTheDocument();
  });

  it("revokes another session in place, after confirming", async () => {
    const fetchMock = vi.fn(async (_url: string, init?: RequestInit) =>
      init?.method === "DELETE"
        ? new Response(null, { status: 204 })
        : Response.json([session("a", true), session("b", false)]),
    );
    vi.stubGlobal("fetch", fetchMock);
    renderSection();

    const buttons = await screen.findAllByRole("button", { name: /^log out$/i });
    fireEvent.click(buttons[1]);
    fireEvent.click(await screen.findByRole("button", { name: /sign it out/i }));

    await waitFor(() =>
      expect(fetchMock).toHaveBeenCalledWith(
        expect.stringContaining("/me/sessions/b"),
        expect.objectContaining({ method: "DELETE" }),
      ),
    );
  });
});
